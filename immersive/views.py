import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .forms import AssignmentForm, BookForm, GradeForm, SceneFormSet, SignupForm, SubmissionForm
from .models import Assignment, Book, LearningEvent, Lesson, LessonVideo, QuizAttempt, Submission
from .services import analytics, pipeline
from .services.textproc import clean


def is_reviewer(user):
    return user.is_staff or user.groups.filter(name="Reviewer").exists()


def is_teacher(user):
    return user.is_staff or user.groups.filter(name__in=["Teacher", "Reviewer"]).exists()


def can_view(user, lesson):
    return lesson.is_published or lesson.book.owner_id == user.id or is_reviewer(user)


def is_owner_of(user, lesson):
    return lesson.book.owner_id == user.id or user.is_staff


def can_take_quiz(user, lesson):
    """Students can take a quiz only once the teacher has published it (assigned it); teachers can preview."""
    if is_owner_of(user, lesson) or is_reviewer(user):
        return True
    return lesson.is_published and analytics.active_quiz(lesson) is not None


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


@login_required
def dashboard(request):
    user = request.user
    ctx = {"teacher": is_teacher(user), "reviewer": is_reviewer(user), "now": timezone.now()}
    if ctx["teacher"]:
        books = Book.objects.filter(owner=user).annotate(n=Count("lessons"))
        for b in books:
            b.n_pub = b.lessons.filter(status=Lesson.PUBLISHED).count()
        ctx["books"] = books
        ctx["my_lessons"] = Lesson.objects.filter(book__owner=user).select_related("book").annotate(
            nq=Count("questions", distinct=True)).order_by("-updated")[:8]
        work = Assignment.objects.filter(owner=user).annotate(n_sub=Count("submissions", distinct=True), n_att=Count("attempts", distinct=True))[:8]
        ctx["my_work"] = work
        ctx["to_grade"] = Submission.objects.filter(assignment__owner=user, assignment__kind=Assignment.ASSIGNMENT,
                                                    marks__isnull=True).select_related("student", "assignment")[:10]
        ctx["class_rows"] = analytics.class_overview(user)[:8]
        ctx["stats"] = {"books": books.count(), "published": Lesson.objects.filter(book__owner=user, status=Lesson.PUBLISHED).count(),
                        "drafts": Lesson.objects.filter(book__owner=user).exclude(status=Lesson.PUBLISHED).count(),
                        "to_grade": Submission.objects.filter(assignment__owner=user, assignment__kind=Assignment.ASSIGNMENT, marks__isnull=True).count()}
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
    if not is_teacher(request.user):
        raise PermissionDenied
    form = BookForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        book = form.save(commit=False)
        book.owner = request.user
        text = form.cleaned_data.get("raw_text", "")
        if form.cleaned_data.get("pdf"):
            try:
                text = pipeline.extract_pdf_text(form.cleaned_data["pdf"])
            except Exception as exc:  # noqa: BLE001
                form.add_error("pdf", f"Could not read PDF: {exc}")
        if not form.errors:
            book.raw_text = clean(text)
            if len(book.raw_text) < 60:
                form.add_error(None, "Not enough text found (scanned PDF? try pasting the text).")
            else:
                book.save()
                lessons = pipeline.create_lessons_from_book(book)
                cd = form.cleaned_data
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
                messages.success(request, f"{len(lessons)} lesson(s) generated with 3D scenes, pictures and quiz.{note}")
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
    return render(request, "immersive/book_detail.html", {
        "book": book, "lessons": lessons, "is_owner": book.owner_id == request.user.id or request.user.is_staff,
        "n_unpublished": sum(1 for l in lessons if not l.is_published), "require_review": settings.EDUPILOT_REQUIRE_REVIEW})


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
    return render(request, "immersive/lesson_detail.html", {
        "lesson": lesson, "scenes": lesson.scenes.all(), "videos": lesson.videos.all()[:3],
        "latest_video": lesson.videos.filter(status=LessonVideo.DONE).first(),
        "is_owner": owner, "reviewer": is_reviewer(request.user), "require_review": settings.EDUPILOT_REQUIRE_REVIEW,
        "attempts": lesson.attempts.filter(user=request.user)[:5],
        "n_questions": lesson.questions.count(), "quiz_assignment": analytics.active_quiz(lesson),
        "can_quiz": can_take_quiz(request.user, lesson),
        "lesson_work": lesson.assignments.filter(published=True).exclude(kind=Assignment.QUIZ),
    })


@login_required
def lesson_edit(request, pk):
    lesson = get_lesson_for_edit(request, pk)
    qs = lesson.scenes.all()
    formset = SceneFormSet(request.POST or None, queryset=qs)
    if request.method == "POST" and formset.is_valid():
        formset.save()
        lesson.version += 1
        lesson.status, lesson.approved_by = Lesson.DRAFT, None
        lesson.title = request.POST.get("title", lesson.title)[:200]
        lesson.objective = request.POST.get("objective", lesson.objective)
        lesson.save()
        pipeline.generate_images(lesson)
        messages.success(request, "Saved. Lesson is back to Draft (new version) and pictures were refreshed.")
        return redirect(lesson)
    return render(request, "immersive/lesson_edit.html", {"lesson": lesson, "formset": formset})


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
        lesson.status, lesson.approved_by = Lesson.APPROVED, request.user
        lesson.save()
    elif action == "reject" and lesson.status == Lesson.REVIEW and is_reviewer(request.user):
        lesson.status = Lesson.DRAFT
        lesson.save()
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
    return render(request, "immersive/viewer.html", {"lesson": lesson, "language": lesson.book.language})


@login_required
def quiz(request, pk):
    lesson = get_lesson_for_view(request, pk)
    if not can_take_quiz(request.user, lesson):
        raise PermissionDenied("Your teacher has not published this quiz yet.")
    questions = list(lesson.questions.all())
    teacher_preview = is_owner_of(request.user, lesson) or is_reviewer(request.user)
    if request.method == "POST":
        score, answers, review = 0, {}, []
        for q in questions:
            raw = request.POST.get(f"q{q.pk}")
            try:
                choice = int(raw)
            except (TypeError, ValueError):
                choice = -1
            ok = choice == q.answer_index   # grading is always server-side (blueprint s.13)
            score += ok
            answers[str(q.pk)] = choice
            review.append({"q": q, "choice": choice, "ok": ok})
        attempt = QuizAttempt.objects.create(user=request.user, lesson=lesson, score=score, total=len(questions), answers=answers,
                                             assignment=analytics.active_quiz(lesson))
        LearningEvent.objects.create(user=request.user, lesson=lesson, event_type="quiz.submitted",
                                     payload={"score": score, "total": len(questions)})
        return render(request, "immersive/quiz_result.html", {"lesson": lesson, "attempt": attempt, "review": review})
    return render(request, "immersive/quiz.html", {"lesson": lesson, "questions": questions, "teacher_preview": teacher_preview})


@login_required
def progress(request):
    if is_teacher(request.user):
        rows = analytics.class_overview(request.user)
        attempts = QuizAttempt.objects.filter(lesson__book__owner=request.user).select_related("user", "lesson")[:100]
        return render(request, "immersive/progress_teacher.html", {"rows": rows, "attempts": attempts})
    return render(request, "immersive/progress.html", analytics.student_overview(request.user))


@login_required
def student_detail(request, pk):
    """Teacher view of one student's analytics (same page the student sees)."""
    if not is_teacher(request.user):
        raise PermissionDenied
    student = get_object_or_404(analytics.students_qs(), pk=pk)
    ctx = analytics.student_overview(student)
    ctx["student"] = student
    return render(request, "immersive/progress.html", ctx)


# ---------------------------------------------------------------- assignments, quizzes, diary
@login_required
def work_list(request):
    """Students: everything the teacher has given. Teachers: everything they have given."""
    kind = request.GET.get("kind", "")
    if is_teacher(request.user):
        qs = Assignment.objects.filter(owner=request.user) if not request.user.is_staff else Assignment.objects.all()
        qs = qs.select_related("lesson").annotate(n_sub=Count("submissions", distinct=True), n_att=Count("attempts", distinct=True))
        if kind in dict(Assignment.KINDS):
            qs = qs.filter(kind=kind)
        return render(request, "immersive/work_list.html", {"items": qs, "kind": kind, "teacher_view": True})
    qs = analytics.visible_assignments()
    if kind in dict(Assignment.KINDS):
        qs = qs.filter(kind=kind)
    subs = {s.assignment_id: s for s in Submission.objects.filter(student=request.user)}
    done_lessons = set(QuizAttempt.objects.filter(user=request.user).values_list("lesson_id", flat=True))
    items = []
    for a in qs:
        s = subs.get(a.pk)
        a.sub = s
        a.done = (a.lesson_id in done_lessons) if a.kind == Assignment.QUIZ else bool(s)
        items.append(a)
    return render(request, "immersive/work_list.html", {"items": items, "kind": kind, "teacher_view": False})


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
        attempts = a.attempts.select_related("user") if a.kind == Assignment.QUIZ else []
        return render(request, "immersive/work_detail_teacher.html", {
            "a": a, "subs": subs, "attempts": attempts, "grade_form": GradeForm(),
            "seen_count": subs.count() if a.kind == Assignment.DIARY else None})
    if not a.published or (a.lesson_id and not a.lesson.is_published):
        raise Http404
    sub = Submission.objects.filter(assignment=a, student=request.user).first()
    form = None
    if a.kind == Assignment.ASSIGNMENT:
        form = SubmissionForm(request.POST or None, request.FILES or None, instance=sub)
        if request.method == "POST" and form.is_valid():
            s = form.save(commit=False)
            s.assignment, s.student = a, request.user
            if sub and sub.is_graded:   # re-submission resets the grade
                s.marks, s.graded_at, s.feedback = None, None, ""
            s.save()
            messages.success(request, "Submitted. Your teacher can see it now.")
            return redirect(a)
    elif a.kind == Assignment.DIARY and request.method == "POST":
        Submission.objects.get_or_create(assignment=a, student=request.user)
        return redirect(a)
    best = None
    if a.kind == Assignment.QUIZ:
        best = QuizAttempt.objects.filter(user=request.user, lesson=a.lesson).order_by("-score").first()
    return render(request, "immersive/work_detail_student.html", {"a": a, "sub": sub, "form": form, "best": best})


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
        sub.marks, sub.feedback, sub.graded_at = form.cleaned_data["marks"], form.cleaned_data["feedback"], timezone.now()
        sub.save()
        messages.success(request, f"Graded {sub.student.get_username()}: {sub.marks}/{a.total_marks}.")
    else:
        messages.error(request, f"Marks must be a number from 0 to {a.total_marks}.")
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
    return JsonResponse(get_lesson_for_view(request, pk).manifest())


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
