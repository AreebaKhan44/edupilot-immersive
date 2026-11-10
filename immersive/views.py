import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .forms import AssignmentForm, BookForm, GradeForm, SignupForm, SubmissionForm, scene_formset
from datetime import timedelta

from .models import (Assignment, Book, ClassSession, Enrolment, GuardianLink, LearningEvent, Lesson, LessonVersion, LessonVideo,
                     QuizAttempt, SchoolClass, SceneImage, Submission, HEADSET_MODES)
from .services import analytics, outcomes, pipeline
from .services.textproc import clean


from .roles import is_reviewer, is_teacher  # noqa: E402,F401  (role rules live in roles.py)


def can_view(user, lesson):
    return lesson.is_published or lesson.book.owner_id == user.id or is_reviewer(user)


def is_owner_of(user, lesson):
    return lesson.book.owner_id == user.id or user.is_staff


def can_take_quiz(user, lesson):
    """Students can take a quiz only once the teacher has published it (assigned it); teachers can preview."""
    if is_owner_of(user, lesson) or is_reviewer(user):
        return True
    return lesson.is_published and analytics.active_quiz(lesson) is not None


def build_review(questions, answers):
    """Per-question review (what the student chose vs. the right answer)."""
    review = []
    for q in questions:
        choice = answers.get(str(q.pk), -1)
        review.append({"q": q, "choice": choice, "ok": choice == q.answer_index})
    return review


def get_lesson_for_view(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("book"), pk=pk)
    if not can_view(request.user, lesson):
        raise PermissionDenied
    return lesson


def get_lesson_for_edit(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("book"), pk=pk)
    if lesson.book.owner_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    return lesson


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        return redirect("dashboard")
    return render(request, "registration/signup.html", {"form": form})


def _teacher_dashboard_extras(user):
    """Data for the redesigned teacher dashboard: greeting, headline stats, classes, sessions, lesson thumbnails."""
    now = timezone.localtime()
    month_ago = timezone.now() - timedelta(days=30)
    hour = now.hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    my_classes = SchoolClass.objects.filter(teacher=user)
    my_enrol = Enrolment.objects.filter(school_class__teacher=user)
    my_sessions = ClassSession.objects.filter(school_class__teacher=user)
    my_work = Assignment.objects.filter(owner=user)
    classes = list(my_classes.select_related("subject").annotate(n=Count("enrolments"))[:4])
    for i, c in enumerate(classes):
        c.tone = "abcd"[i % 4]
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = list(my_sessions.filter(scheduled_for__gte=start_today, status__in=[ClassSession.SCHEDULED, ClassSession.LIVE])
                    .select_related("school_class", "lesson")[:4])
    today = now.date()
    for sess in sessions:
        d = timezone.localtime(sess.scheduled_for).date()
        sess.day_label = "Today" if d == today else "Tomorrow" if d == today + timedelta(days=1) else timezone.localtime(sess.scheduled_for).strftime("%d %b")
    return {
        "greeting": greeting,
        "dash_classes": classes,
        "dash_sessions": sessions,
        "dash_stats": {
            "classes": my_classes.count(), "classes_new": my_classes.filter(created__gte=month_ago).count(),
            "students": my_enrol.values("student").distinct().count(),
            "students_new": my_enrol.filter(joined__gte=month_ago).values("student").distinct().count(),
            "sessions": my_sessions.count(), "sessions_new": my_sessions.filter(scheduled_for__gte=month_ago).count(),
            "work": my_work.count(), "work_new": my_work.filter(created__gte=month_ago).count(),
        },
    }


@login_required
def dashboard(request):
    user = request.user
    if not is_teacher(user) and user.groups.filter(name="Guardian").exists():
        return redirect("guardian_home")
    ctx = {"teacher": is_teacher(user), "reviewer": is_reviewer(user), "now": timezone.now()}
    if ctx["teacher"]:
        books = Book.objects.filter(owner=user).annotate(n=Count("lessons"))
        for b in books:
            b.n_pub = b.lessons.filter(status=Lesson.PUBLISHED).count()
        ctx["books"] = books
        ctx["my_lessons"] = Lesson.objects.filter(book__owner=user).select_related("book").annotate(
            nq=Count("questions", distinct=True)).order_by("-updated")[:8]
        for l in ctx["my_lessons"]:
            first = l.scenes.exclude(image="").first()
            l.thumb = first.image_url if first else ""
        work = Assignment.objects.filter(owner=user).annotate(n_sub=Count("submissions", distinct=True), n_att=Count("attempts", distinct=True))[:8]
        ctx["my_work"] = work
        subs_to_grade = Submission.objects.filter(assignment__owner=user, assignment__kind=Assignment.ASSIGNMENT,
                                                  marks__isnull=True).select_related("student", "assignment")
        quiz_to_grade = QuizAttempt.objects.filter(Q(assignment__owner=user) | Q(assignment__isnull=True, lesson__book__owner=user),
                                                   marks__isnull=True).select_related("user", "lesson", "assignment")
        rows = [{"kind": "assignment", "icon": "📄", "who": x.student.username, "title": x.assignment.title, "when": x.submitted_at,
                 "url": x.assignment.get_absolute_url(), "extra": ""} for x in subs_to_grade]
        rows += [{"kind": "quiz", "icon": "📝", "who": x.user.username, "title": x.assignment.title if x.assignment else f"Quiz: {x.lesson.title}",
                  "when": x.created, "url": x.assignment.get_absolute_url() if x.assignment else x.lesson.get_absolute_url(),
                  "extra": f"auto-check {x.score}/{x.total}"} for x in quiz_to_grade]
        rows.sort(key=lambda r: r["when"], reverse=True)
        ctx["to_grade"] = rows[:10]
        ctx["class_rows"] = analytics.class_overview(user)[:8]
        ctx["stats"] = {"books": books.count(), "published": Lesson.objects.filter(book__owner=user, status=Lesson.PUBLISHED).count(),
                        "drafts": Lesson.objects.filter(book__owner=user).exclude(status=Lesson.PUBLISHED).count(),
                        "to_grade": len(rows)}
        ctx.update(_teacher_dashboard_extras(user))
        if ctx["reviewer"]:
            ctx["review_queue"] = Lesson.objects.filter(status=Lesson.REVIEW).select_related("book")
        return render(request, "immersive/dashboard_teacher.html", ctx)
    ov = analytics.student_overview(user)
    ctx.update(ov)
    ctx["diary"] = analytics.visible_assignments([Assignment.DIARY])[:4]
    seen = set(Submission.objects.filter(student=user, assignment__kind=Assignment.DIARY).values_list("assignment_id", flat=True))
    for d in ctx["diary"]:
        d.seen = d.pk in seen
    return render(request, "immersive/dashboard_student.html", ctx)


@login_required
def book_create(request):
    """Upload -> 1) lesson plans (units, objectives, scenes, plan phases, quiz)  2) pictures from the PDF attached to the right
    scenes  3) a picture drawn from the content for every scene that still has none  -> the teacher reviews the plan and
    then watches it in 3D. Nothing reaches students until the teacher publishes (unless 'publish' was ticked)."""
    if not is_teacher(request.user):
        raise PermissionDenied
    form = BookForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        book = form.save(commit=False)
        book.owner = request.user
        text, pages, images = form.cleaned_data.get("raw_text", ""), None, None
        if form.cleaned_data.get("pdf"):
            try:
                text, pages, images = pipeline.read_pdf_upload(form.cleaned_data["pdf"])
            except Exception as exc:  # noqa: BLE001
                form.add_error("pdf", f"Could not read PDF: {exc}")
        if not form.errors:
            book.raw_text = clean(text)
            if len(book.raw_text) < 60:
                form.add_error(None, "Not enough text found (scanned PDF? try pasting the text).")
            else:
                book.save()
                lessons = pipeline.create_lessons_from_book(book, pages, images)
                cd = form.cleaned_data
                n_book = book.images.filter(kind=SceneImage.BOOK).count()
                n_gen = book.images.filter(kind=SceneImage.GENERATED).count()
                note = ""
                if cd.get("publish_now"):
                    if settings.EDUPILOT_REQUIRE_REVIEW:
                        for l in lessons:
                            l.status = Lesson.REVIEW
                            l.save(update_fields=["status"])
                        note = " Review is switched on, so they were sent to the reviewer; students will see them after approval + publish."
                    else:
                        for l in lessons:
                            pipeline.publish_lesson(l, request.user, with_quiz=bool(cd.get("make_quiz")))
                        note = " Published: students can already see them on their dashboard."
                if cd.get("make_video"):
                    pipeline.start_video_jobs(lessons)
                    note += " Videos are rendering in the background (one lesson at a time)."
                messages.success(request, f"Lesson plan ready: {len(lessons)} lesson(s). Pictures: {n_book} from your book, {n_gen} drawn from the "
                                          f"lesson content. Review the plan, then open it in 3D.{note}")
                return redirect(book)
    return render(request, "immersive/book_form.html", {"form": form})


@login_required
def book_detail(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if book.owner_id != request.user.id and not is_reviewer(request.user):
        raise PermissionDenied
    lessons = list(book.lessons.annotate(ns=Count("scenes", distinct=True), nq=Count("questions", distinct=True)))
    for l in lessons:
        l.video = l.videos.first()
        l.quiz_live = analytics.active_quiz(l) is not None
        l.n_book_pics = l.pictures.filter(kind=SceneImage.BOOK).count()
        l.n_gen_pics = l.pictures.filter(kind=SceneImage.GENERATED).count()
    return render(request, "immersive/book_detail.html", {
        "book": book, "lessons": lessons, "is_owner": book.owner_id == request.user.id or request.user.is_staff,
        "n_unpublished": sum(1 for l in lessons if not l.is_published), "require_review": settings.EDUPILOT_REQUIRE_REVIEW})


@require_POST
@login_required
def book_delete(request, pk):
    """Teacher: delete a whole book with all its lessons, quizzes, pictures and videos."""
    book = get_object_or_404(Book, pk=pk)
    if book.owner_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    title, n = book.title, book.lessons.count()
    pipeline.delete_book(book)
    messages.success(request, f"Book “{title}” and its {n} lesson(s) were deleted.")
    return redirect("dashboard")


@require_POST
@login_required
def book_bulk(request, pk):
    """Publish all / unpublish all lessons of a book, or render videos for all of them."""
    book = get_object_or_404(Book, pk=pk)
    if book.owner_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    action = request.POST.get("action")
    lessons = list(book.lessons.all())
    if action == "publish_all":
        if settings.EDUPILOT_REQUIRE_REVIEW and not request.user.is_staff:
            messages.error(request, "Review is switched on: lessons must be approved by a reviewer first.")
        else:
            for l in lessons:
                pipeline.publish_lesson(l, request.user)
            messages.success(request, f"{len(lessons)} lesson(s) are now visible to students.")
    elif action == "unpublish_all":
        for l in lessons:
            pipeline.unpublish_lesson(l)
        messages.success(request, "All lessons were hidden from students.")
    elif action == "videos_all":
        started = pipeline.start_video_jobs([l for l in lessons if not l.videos.filter(status=LessonVideo.DONE, lesson_version=l.version).exists()])
        messages.success(request, f"Rendering {len(started)} video(s) in the background.")
    else:
        raise Http404
    return redirect(book)


@ensure_csrf_cookie
@login_required
def lesson_detail(request, pk):
    lesson = get_lesson_for_view(request, pk)
    owner = is_owner_of(request.user, lesson)
    scenes = list(lesson.scenes.prefetch_related("pictures"))
    return render(request, "immersive/lesson_detail.html", {
        "lesson": lesson, "scenes": scenes, "videos": lesson.videos.all()[:3], "plan": lesson.plan or {},
        "versions": lesson.versions.all()[:8], "mappings": lesson.mappings.select_related("outcome__curriculum", "reviewed_by"),
        "issues": lesson.issues.filter(status="open"), "loose_pictures": lesson.pictures.filter(scene__isnull=True),
        "latest_video": lesson.videos.filter(status=LessonVideo.DONE).first(),
        "is_owner": owner, "reviewer": is_reviewer(request.user), "require_review": settings.EDUPILOT_REQUIRE_REVIEW,
        "attempts": lesson.attempts.filter(user=request.user)[:5],
        "n_questions": lesson.questions.count(), "quiz_assignment": analytics.active_quiz(lesson),
        "can_quiz": can_take_quiz(request.user, lesson),
        "quiz_state": None if (owner or is_reviewer(request.user)) else analytics.quiz_state(request.user, lesson),
        "lesson_work": lesson.assignments.filter(published=True).exclude(kind=Assignment.QUIZ),
    })


@login_required
def lesson_edit(request, pk):
    """Update lesson plan: edit title/objective and every scene, add a scene, or delete scenes."""
    lesson = get_lesson_for_edit(request, pk)
    add = 1 if (request.POST.get("add") or request.GET.get("add")) == "1" else 0
    formset = scene_formset(add)(request.POST or None, queryset=lesson.scenes.all())
    if request.method == "POST" and formset.is_valid():
        kept = [f for f in formset.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not kept:
            messages.error(request, "A lesson needs at least one scene. Delete the whole lesson instead if you do not need it.")
        else:
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            nxt = lesson.scenes.aggregate(m=Max("order"))["m"] or 0
            for obj in instances:
                if obj.pk is None:
                    nxt += 1
                    obj.lesson, obj.order = lesson, nxt
                obj.save()
            for i, sc in enumerate(lesson.scenes.order_by("order", "pk"), 1):      # keep 1..n without gaps
                if sc.order != i:
                    sc.order = i
                    sc.save(update_fields=["order"])
            lesson.version += 1
            lesson.status, lesson.approved_by = Lesson.DRAFT, None
            lesson.title = (request.POST.get("title", lesson.title).strip() or lesson.title)[:200]
            lesson.objective = request.POST.get("objective", lesson.objective)
            lesson.save()
            pipeline.refresh_pictures(lesson)          # redraw generated pictures for the edited text; book/uploaded ones stay
            lesson.assignments.filter(kind=Assignment.QUIZ).update(published=False)   # back to draft = hidden from students
            messages.success(request, "Saved. Lesson is back to Draft (new version) and pictures were refreshed – publish it again when ready.")
            return redirect(lesson)
    return render(request, "immersive/lesson_edit.html", {"lesson": lesson, "formset": formset, "add": add})


@require_POST
@login_required
def lesson_delete(request, pk):
    """Teacher: delete one lesson plan (scenes, pictures, video, quiz, assignments and student results of that lesson)."""
    lesson = get_lesson_for_edit(request, pk)
    book, title = lesson.book, lesson.title
    pipeline.delete_lesson(lesson)
    messages.success(request, f"Lesson “{title}” was deleted.")
    return redirect(book)


@require_GET
@login_required
def scene_audio(request, pk, order):
    """Narration audio of one scene (server-side TTS). Used by the viewer when the device has no voice for the language."""
    lesson = get_lesson_for_view(request, pk)
    scene = get_object_or_404(lesson.scenes, order=order)
    path = pipeline.scene_audio_file(scene, lesson.book.language)
    if path is None:
        raise Http404("No text-to-speech engine available on the server (install gTTS or espeak-ng).")
    resp = FileResponse(open(path, "rb"), content_type="audio/mpeg" if path.suffix == ".mp3" else "audio/wav")
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


@require_POST
@login_required
def lesson_regenerate(request, pk):
    lesson = get_lesson_for_edit(request, pk)
    pipeline.regenerate(lesson)
    messages.success(request, "Storyboard regenerated from the source text (new version).")
    return redirect(lesson)


@require_POST
@login_required
def lesson_workflow(request, pk):
    """draft -> (review ->) approved -> published (blueprint s.8). With EDUPILOT_REQUIRE_REVIEW=0 (default) the
    teacher can publish straight from draft, so students see the lesson immediately."""
    action = request.POST.get("action")
    lesson = get_lesson_for_edit(request, pk) if action in ("submit", "withdraw", "publish", "unpublish") else get_object_or_404(Lesson, pk=pk)
    needs_review = settings.EDUPILOT_REQUIRE_REVIEW
    if action == "submit" and lesson.status == Lesson.DRAFT:
        lesson.status = Lesson.REVIEW if needs_review else Lesson.APPROVED
        lesson.save()
    elif action == "withdraw" and lesson.status in (Lesson.REVIEW, Lesson.APPROVED):
        lesson.status = Lesson.DRAFT
        lesson.save()
    elif action == "approve" and lesson.status == Lesson.REVIEW and is_reviewer(request.user):
        if lesson.book.owner_id == request.user.id:      # roadmap s.6: creators must not approve their own publications
            messages.error(request, "You created this lesson, so another reviewer must approve it.")
            return redirect(lesson)
        lesson.status, lesson.approved_by = Lesson.APPROVED, request.user
        lesson.save()
    elif action == "reject" and lesson.status == Lesson.REVIEW and is_reviewer(request.user):
        lesson.status = Lesson.DRAFT
        lesson.save()
    elif action == "publish" and lesson.needs_review:
        messages.error(request, "The curriculum changed for this lesson. Re-check its mapping (Lesson design) before publishing again.")
        return redirect(lesson)
    elif action == "publish" and settings.EDUPILOT_REQUIRE_ALT_ROUTE and lesson.mode in HEADSET_MODES and not lesson.alternative_route.strip():
        messages.error(request, "An AR/VR lesson needs a screen-based alternative route before it can be published (open 'Lesson design').")
        return redirect(lesson)
    elif action == "publish" and (lesson.status == Lesson.APPROVED or (not needs_review and lesson.status == Lesson.DRAFT)):
        pipeline.publish_lesson(lesson, request.user, with_quiz=request.POST.get("with_quiz", "1") == "1")
    elif action == "unpublish" and lesson.status == Lesson.PUBLISHED:
        pipeline.unpublish_lesson(lesson)
    else:
        raise PermissionDenied
    messages.success(request, f"Lesson is now: {lesson.get_status_display()}")
    return redirect(lesson)


@require_POST
@login_required
def lesson_quiz(request, pk):
    """Teacher: generate the quiz from the lesson plan, then show it to / hide it from students."""
    lesson = get_lesson_for_edit(request, pk)
    action = request.POST.get("action")
    if action == "generate":
        try:
            count = max(1, min(20, int(request.POST.get("count", 5))))
        except ValueError:
            count = 5
        n = pipeline.regenerate_quiz(lesson, count)
        messages.success(request, f"Quiz generated: {n} question(s)." if n else "Not enough text to build quiz questions from this lesson.")
    elif action == "assign":
        if not lesson.questions.exists():
            messages.error(request, "Generate the quiz first.")
        else:
            due = parse_datetime(request.POST.get("due_date", "") + ":00") if request.POST.get("due_date") else None
            pipeline.assign_quiz(lesson, request.user, due_date=due)
            msg = "Quiz is now on the student dashboard."
            if not lesson.is_published:
                msg += " (Students will see it once the lesson itself is published.)"
            messages.success(request, msg)
    elif action == "unassign":
        lesson.assignments.filter(kind=Assignment.QUIZ).update(published=False)
        messages.success(request, "Quiz hidden from students.")
    else:
        raise Http404
    return redirect(lesson)


@require_POST
@login_required
def video_start(request, pk):
    lesson = get_lesson_for_edit(request, pk)
    if lesson.videos.filter(status__in=[LessonVideo.PENDING, LessonVideo.WORKING]).exists():
        messages.info(request, "A video is already rendering.")
    else:
        pipeline.start_video_job(lesson)
        messages.success(request, "Video rendering started – this page will update when it is ready.")
    return redirect(lesson)


@require_GET
@login_required
def video_status(request, pk):
    lesson = get_lesson_for_view(request, pk)
    v = lesson.videos.first()
    if not v:
        return JsonResponse({"status": "none"})
    return JsonResponse({"status": v.status, "url": v.url, "voice": v.voice, "log": v.log})


@ensure_csrf_cookie
@login_required
def viewer(request, pk):
    lesson = get_lesson_for_view(request, pk)
    if not lesson.scenes.exists():       # the 3D lesson is built from the lesson plan, so the plan must exist first
        messages.error(request, "This lesson has no lesson plan yet. Generate the plan first, then open it in 3D.")
        return redirect(lesson)
    if not is_teacher(request.user):
        outcomes.mark_started(request.user, lesson)
    return render(request, "immersive/viewer.html", {"lesson": lesson, "language": lesson.book.language,
                                                     "version": request.GET.get("version", "")})


@login_required
def quiz(request, pk):
    """Students can submit a quiz ONCE. It opens again only if the teacher allows a retry after seeing the marks."""
    lesson = get_lesson_for_view(request, pk)
    if not can_take_quiz(request.user, lesson):
        raise PermissionDenied("Your teacher has not published this quiz yet.")
    questions = list(lesson.questions.all())
    teacher_preview = is_owner_of(request.user, lesson) or is_reviewer(request.user)
    if not teacher_preview and not analytics.quiz_state(request.user, lesson)["can_attempt"]:
        messages.info(request, "You have already submitted this quiz. Your teacher will give the marks (you can retry only if the teacher allows it).")
        return redirect("quiz_result", pk=lesson.pk)
    if request.method == "POST":
        score, answers = 0, {}
        for q in questions:
            try:
                choice = int(request.POST.get(f"q{q.pk}"))
            except (TypeError, ValueError):
                choice = -1
            score += choice == q.answer_index   # automatic check is always server-side (blueprint s.13)
            answers[str(q.pk)] = choice
        if teacher_preview:      # preview only: nothing is stored, teacher is not a student
            attempt = QuizAttempt(user=request.user, lesson=lesson, score=score, total=len(questions), answers=answers)
            return render(request, "immersive/quiz_result.html", {"lesson": lesson, "attempt": attempt, "review": build_review(questions, answers),
                                                                  "preview": True, "show_answers": True})
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)   # serialise double clicks / two tabs
            state = analytics.quiz_state(request.user, lesson)
            if not state["can_attempt"]:
                messages.error(request, "This quiz was already submitted – a second submission is not allowed.")
                return redirect("quiz_result", pk=lesson.pk)
            if state["attempt"] is not None and state["attempt"].retry_allowed:   # the teacher's retry permission is used up now
                QuizAttempt.objects.filter(pk=state["attempt"].pk).update(retry_allowed=False)
            QuizAttempt.objects.create(user=request.user, lesson=lesson, score=score, total=len(questions), answers=answers,
                                       assignment=analytics.active_quiz(lesson))
            LearningEvent.objects.create(user=request.user, lesson=lesson, event_type="quiz.submitted", payload={"questions": len(questions)})
            outcomes.record_evidence(request.user, lesson)
        messages.success(request, "Quiz submitted. Your teacher will check it and give your marks.")
        return redirect("quiz_result", pk=lesson.pk)
    return render(request, "immersive/quiz.html", {"lesson": lesson, "questions": questions, "teacher_preview": teacher_preview,
                                                   "retry": analytics.quiz_state(request.user, lesson)["code"] == "retry" if not teacher_preview else False})


@login_required
def quiz_result(request, pk):
    """Student: status of my (latest) quiz submission. Marks and the answer review appear only after the teacher has graded it."""
    lesson = get_lesson_for_view(request, pk)
    attempt = analytics.latest_attempt(request.user, lesson)
    if attempt is None:
        return redirect("quiz", pk=lesson.pk)
    state = analytics.quiz_state(request.user, lesson)
    review = build_review(list(lesson.questions.all()), attempt.answers) if attempt.is_graded else []
    return render(request, "immersive/quiz_result.html", {"lesson": lesson, "attempt": attempt, "review": review, "state": state,
                                                          "show_answers": attempt.is_graded, "history": QuizAttempt.objects.filter(user=request.user, lesson=lesson)})


def _attempt_for_teacher(request, pk):
    attempt = get_object_or_404(QuizAttempt.objects.select_related("lesson__book", "assignment", "user"), pk=pk)
    if not is_teacher(request.user) or not (is_owner_of(request.user, attempt.lesson) or
                                            (attempt.assignment_id and attempt.assignment.owner_id == request.user.id)):
        raise PermissionDenied
    return attempt


@require_POST
@login_required
def attempt_grade(request, pk):
    """Teacher awards marks for a submitted quiz (0..number of questions) + optional feedback."""
    attempt = _attempt_for_teacher(request, pk)
    form = GradeForm(request.POST)
    if form.is_valid() and form.cleaned_data["marks"] <= attempt.total:
        new, reason, old = form.cleaned_data["marks"], form.cleaned_data["reason"].strip(), attempt.marks
        if outcomes.needs_override_reason(old, new) and not reason:
            messages.error(request, "These marks were already awarded. Changing them is a score override and needs a reason (it is audited).")
            return redirect(attempt.assignment or attempt.lesson)
        attempt.marks, attempt.feedback, attempt.graded_at = new, form.cleaned_data["feedback"], timezone.now()
        attempt.save(update_fields=["marks", "feedback", "graded_at"])
        if old != new:
            outcomes.audit_grade("attempt", attempt.pk, attempt.user, old, new, reason or "first marking", request.user)
        outcomes.record_review(attempt.user, attempt.lesson, new, attempt.total, request.user)
        messages.success(request, f"Marks saved for {attempt.user.get_username()}: {attempt.marks}/{attempt.total}. The student can see them now.")
    else:
        messages.error(request, f"Marks must be a number from 0 to {attempt.total}.")
    return redirect(attempt.assignment or attempt.lesson)


@require_POST
@login_required
def attempt_retry(request, pk):
    """Teacher lets a student attempt the quiz one more time (usually after low marks) – or takes that permission back."""
    attempt = _attempt_for_teacher(request, pk)
    newest = analytics.latest_attempt(attempt.user, attempt.lesson)
    if newest is None or newest.pk != attempt.pk:
        messages.error(request, "This is not the student's latest attempt (they already retried).")
    elif request.POST.get("action") == "revoke":
        attempt.retry_allowed = False
        attempt.save(update_fields=["retry_allowed"])
        messages.success(request, "Retry permission removed.")
    elif not attempt.is_graded:
        messages.error(request, "Give marks first, then decide about a retry.")
    else:
        attempt.retry_allowed = True
        attempt.save(update_fields=["retry_allowed"])
        messages.success(request, f"{attempt.user.get_username()} can now attempt the quiz again (one more submission).")
    return redirect(attempt.assignment or attempt.lesson)


@login_required
def progress(request):
    if is_teacher(request.user):
        rows = analytics.class_overview(request.user)
        classes = list(SchoolClass.objects.filter(teacher=request.user) if not request.user.is_staff else SchoolClass.objects.all())
        # class / period filters (GET ?class=<id>&days=<n>)
        class_id = request.GET.get("class", "")
        days = request.GET.get("days", "0")
        days = int(days) if days in ("7", "30", "90") else 0
        enrolled = {}
        for e in Enrolment.objects.filter(school_class__in=classes).select_related("school_class"):
            enrolled.setdefault(e.student_id, []).append(e.school_class)
        if class_id.isdigit():
            rows = [r for r in rows if any(c.pk == int(class_id) for c in enrolled.get(r["student"].pk, []))]
        if days:
            since = timezone.now() - timedelta(days=days)
            rows = [r for r in rows if r["last"] and r["last"] >= since]
        for r in rows:
            r["classes"] = ", ".join(c.name for c in enrolled.get(r["student"].pk, [])) or "—"
            r["initial"] = (r["student"].get_username() or "?")[:1].upper()
            r["tone"] = "abcde"[r["student"].pk % 5]
        avgs = [r["avg"] for r in rows if r["avg"] is not None]
        bests = [r["best"] for r in rows if r["best"] is not None]
        kpi = {"students": len(rows), "attempts": sum(r["attempts"] for r in rows),
               "avg": round(sum(avgs) / len(avgs)) if avgs else None, "best": max(bests) if bests else None,
               "submitted": sum(r["submitted"] for r in rows)}
        attempts = QuizAttempt.objects.filter(lesson__book__owner=request.user).select_related("user", "lesson")[:100]
        return render(request, "immersive/progress_teacher.html", {
            "rows": rows, "attempts": attempts, "kpi": kpi, "classes": classes, "sel_class": class_id, "sel_days": days})
    return render(request, "immersive/progress.html", analytics.student_overview(request.user))


@login_required
def student_detail(request, pk):
    """Teacher view of one student's analytics (same page the student sees)."""
    if not is_teacher(request.user):
        raise PermissionDenied
    student = get_object_or_404(analytics.students_qs(), pk=pk)
    outcomes.log(request.user, "record.access", f"student record of {student.get_username()}")    # roadmap s.6: log sensitive record access
    ctx = analytics.student_overview(student)
    ctx["student"] = student
    return render(request, "immersive/progress.html", ctx)


# ---------------------------------------------------------------- assignments, quizzes, diary
def _work_search(qs, q, sort):
    """Keyword search + sort shared by the teacher and student work lists."""
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(lesson__title__icontains=q))
    order = {"old": "created", "title": "title", "due": "due_date"}.get(sort, "-created")
    return qs.order_by(order)


@login_required
def work_list(request):
    """Students: everything the teacher has given. Teachers: everything they have given."""
    kind = request.GET.get("kind", "")
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "new")
    status = request.GET.get("status", "")
    if is_teacher(request.user):
        qs = Assignment.objects.filter(owner=request.user) if not request.user.is_staff else Assignment.objects.all()
        qs = qs.select_related("lesson", "lesson__book").annotate(n_sub=Count("submissions", distinct=True), n_att=Count("attempts", distinct=True))
        if kind in dict(Assignment.KINDS):
            qs = qs.filter(kind=kind)
        if status == "active":
            qs = qs.filter(published=True)
        elif status == "hidden":
            qs = qs.filter(published=False)
        qs = _work_search(qs, q, sort)
        return render(request, "immersive/work_list.html", {"items": qs, "kind": kind, "teacher_view": True,
                                                            "q": q, "sort": sort, "status": status})
    qs = analytics.visible_assignments()
    if kind in dict(Assignment.KINDS):
        qs = qs.filter(kind=kind)
    qs = _work_search(qs, q, sort)
    subs = {s.assignment_id: s for s in Submission.objects.filter(student=request.user)}
    items = []
    for a in qs:
        s = subs.get(a.pk)
        a.sub = s
        if a.kind == Assignment.QUIZ:
            a.qstate = analytics.quiz_state(request.user, a.lesson)
            a.done = not a.qstate["can_attempt"]
            a.retry = a.qstate["code"] == "retry"
        else:
            a.done = bool(s) and not s.retry_allowed
            a.retry = bool(s and s.retry_allowed)
        items.append(a)
    return render(request, "immersive/work_list.html", {"items": items, "kind": kind, "teacher_view": False, "q": q, "sort": sort, "status": ""})


@login_required
def work_create(request, kind):
    if not is_teacher(request.user):
        raise PermissionDenied
    if kind not in dict(Assignment.KINDS):
        raise Http404
    initial = {}
    if request.GET.get("lesson"):
        initial["lesson"] = request.GET["lesson"]
    form = AssignmentForm(request.POST or None, teacher=request.user, kind=kind, initial=initial)
    if request.method == "POST" and form.is_valid():
        a = form.save(commit=False)
        a.owner, a.kind = request.user, kind
        if kind == Assignment.QUIZ:
            lesson = form.cleaned_data["lesson"]
            a = pipeline.assign_quiz(lesson, request.user, due_date=form.cleaned_data.get("due_date"), title=form.cleaned_data.get("title") or "")
        else:
            a.save()
        messages.success(request, f"{a.get_kind_display()} published: students can see it on their dashboard.")
        return redirect(a if kind != Assignment.QUIZ else "work_list")
    return render(request, "immersive/work_form.html", {"form": form, "kind": kind, "kind_label": dict(Assignment.KINDS)[kind]})


@login_required
def work_detail(request, pk):
    a = get_object_or_404(Assignment.objects.select_related("lesson", "owner"), pk=pk)
    if is_teacher(request.user):
        if a.owner_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied
        subs = a.submissions.select_related("student")
        attempts, newest = [], set()
        if a.kind == Assignment.QUIZ and a.lesson_id:
            attempts = list(QuizAttempt.objects.filter(lesson=a.lesson).exclude(user__in=[a.owner]).select_related("user").order_by("-created"))
            seen_users = set()
            for t in attempts:                      # newest attempt of each student = the one a retry applies to
                if t.user_id not in seen_users:
                    seen_users.add(t.user_id)
                    newest.add(t.pk)
            for t in attempts:
                t.is_newest = t.pk in newest
                t.low = t.is_graded and t.final_percent < settings.EDUPILOT_LOW_MARKS_PERCENT
        return render(request, "immersive/work_detail_teacher.html", {
            "a": a, "subs": subs, "attempts": attempts, "grade_form": GradeForm(), "low_percent": settings.EDUPILOT_LOW_MARKS_PERCENT,
            "seen_count": subs.count() if a.kind == Assignment.DIARY else None})
    if not a.published or (a.lesson_id and not a.lesson.is_published):
        raise Http404
    sub = Submission.objects.filter(assignment=a, student=request.user).first()
    form = None
    if a.kind == Assignment.ASSIGNMENT:
        locked = sub is not None and not sub.retry_allowed     # one submission only, unless the teacher allows another
        if locked:
            if request.method == "POST":
                messages.error(request, "You have already submitted this assignment. A second submission is not allowed.")
                return redirect(a)
        else:
            form = SubmissionForm(request.POST or None, request.FILES or None, instance=sub)
            if request.method == "POST" and form.is_valid():
                s = form.save(commit=False)
                s.assignment, s.student = a, request.user
                s.marks, s.graded_at, s.feedback, s.retry_allowed = None, None, "", False   # a re-submission needs fresh marks
                s.save()
                if a.lesson_id:
                    outcomes.record_evidence(request.user, a.lesson)
                messages.success(request, "Submitted. Your teacher can see it now and will give your marks.")
                return redirect(a)
    elif a.kind == Assignment.DIARY and request.method == "POST":
        Submission.objects.get_or_create(assignment=a, student=request.user)
        return redirect(a)
    qstate = analytics.quiz_state(request.user, a.lesson) if a.kind == Assignment.QUIZ else None
    return render(request, "immersive/work_detail_student.html", {"a": a, "sub": sub, "form": form, "qstate": qstate})


@require_POST
@login_required
def work_manage(request, pk):
    a = get_object_or_404(Assignment, pk=pk)
    if not is_teacher(request.user) or (a.owner_id != request.user.id and not request.user.is_staff):
        raise PermissionDenied
    action = request.POST.get("action")
    if action == "toggle":
        a.published = not a.published
        a.save(update_fields=["published"])
        messages.success(request, "Visible to students." if a.published else "Hidden from students.")
    elif action == "delete":
        a.delete()
        messages.success(request, "Deleted.")
        return redirect("work_list")
    else:
        raise Http404
    return redirect(a)


@require_POST
@login_required
def submission_grade(request, pk):
    sub = get_object_or_404(Submission.objects.select_related("assignment"), pk=pk)
    a = sub.assignment
    if not is_teacher(request.user) or (a.owner_id != request.user.id and not request.user.is_staff):
        raise PermissionDenied
    form = GradeForm(request.POST)
    if form.is_valid() and form.cleaned_data["marks"] <= a.total_marks:
        new, reason, old = form.cleaned_data["marks"], form.cleaned_data["reason"].strip(), sub.marks
        if outcomes.needs_override_reason(old, new) and not reason:
            messages.error(request, "These marks were already awarded. Changing them is a score override and needs a reason (it is audited).")
            return redirect(a)
        sub.marks, sub.feedback, sub.graded_at = new, form.cleaned_data["feedback"], timezone.now()
        sub.save()
        if old != new:
            outcomes.audit_grade("submission", sub.pk, sub.student, old, new, reason or "first marking", request.user)
        if a.lesson_id:
            outcomes.record_review(sub.student, a.lesson, new, a.total_marks, request.user)
        messages.success(request, f"Graded {sub.student.get_username()}: {sub.marks}/{a.total_marks}.")
    else:
        messages.error(request, f"Marks must be a number from 0 to {a.total_marks}.")
    return redirect(a)

@require_POST
@login_required
def submission_retry(request, pk):
    """Teacher lets a student re-submit an assignment once more (or takes that back)."""
    sub = get_object_or_404(Submission.objects.select_related("assignment"), pk=pk)
    a = sub.assignment
    if not is_teacher(request.user) or (a.owner_id != request.user.id and not request.user.is_staff):
        raise PermissionDenied
    if request.POST.get("action") == "revoke":
        sub.retry_allowed = False
        messages.success(request, "Re-submission permission removed.")
    elif not sub.is_graded:
        messages.error(request, "Give marks first, then decide about a re-submission.")
        return redirect(a)
    else:
        sub.retry_allowed = True
        messages.success(request, f"{sub.student.get_username()} can submit this assignment once more.")
    sub.save(update_fields=["retry_allowed"])
    return redirect(a)


# ---------------------------------------------------------------- API
@require_GET
@login_required
def api_catalog(request):
    qs = Lesson.objects.filter(status=Lesson.PUBLISHED).select_related("book")
    return JsonResponse({"lessons": [{"id": l.pk, "title": l.title, "version": l.version, "subject": l.book.subject,
                                      "grade": l.book.grade, "supported_clients": ["vr", "desktop", "tablet"]} for l in qs]})


@require_GET
@login_required
def api_manifest(request, pk):
    """Live manifest, or the immutable published snapshot with ?version=N (a session keeps the version it was scheduled with)."""
    lesson = get_lesson_for_view(request, pk)
    v = request.GET.get("version", "")
    if v.isdigit():
        snap = lesson.versions.filter(version=int(v)).first()
        if snap is None:
            raise Http404("That version was never published.")
        return JsonResponse(snap.snapshot)
    return JsonResponse(lesson.manifest())


@require_POST
@login_required
def api_events_batch(request):
    try:
        events = json.loads(request.body)["events"]
        assert isinstance(events, list) and len(events) <= 100
    except Exception:
        return JsonResponse({"error": "expected {\"events\": [...]} (max 100)"}, status=400)
    accepted = dup = 0
    for e in events:
        if not isinstance(e, dict) or not e.get("event_id") or not str(e.get("event_type", "")).startswith("vr."):
            continue
        lesson = Lesson.objects.filter(pk=e.get("lesson_db_id")).first()
        if lesson and not can_view(request.user, lesson):
            continue
        _, created = LearningEvent.objects.get_or_create(
            event_id=str(e["event_id"])[:64],
            defaults={"user": request.user, "lesson": lesson, "event_type": str(e["event_type"])[:60],
                      "payload": e.get("evidence") if isinstance(e.get("evidence"), dict) else {},
                      "occurred_at": parse_datetime(e.get("occurred_at", "") or "")})
        accepted += created
        dup += not created
    return JsonResponse({"accepted": accepted, "duplicates": dup})
