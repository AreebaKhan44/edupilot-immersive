"""Student / class analytics built from QuizAttempt, Submission and LearningEvent rows."""
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from ..models import Assignment, LearningEvent, Lesson, QuizAttempt, Submission


def is_teacher(user):
    return user.is_staff or user.groups.filter(name__in=["Teacher", "Reviewer"]).exists()


def students_qs():
    return User.objects.filter(is_staff=False).exclude(groups__name__in=["Teacher", "Reviewer"]).distinct()


def visible_assignments(kinds=None):
    """Work that students can see: published, and (if tied to a lesson) the lesson must be published too."""
    qs = Assignment.objects.filter(published=True).filter(Q(lesson__isnull=True) | Q(lesson__status=Lesson.PUBLISHED))
    if kinds:
        qs = qs.filter(kind__in=kinds)
    return qs.select_related("lesson", "owner")


def active_quiz(lesson):
    return lesson.assignments.filter(kind=Assignment.QUIZ, published=True).first()


def latest_attempt(user, lesson):
    return QuizAttempt.objects.filter(user=user, lesson=lesson).order_by("-created", "-pk").first()


def quiz_state(user, lesson):
    """Where does this student stand with this lesson's quiz?
    A quiz can be submitted only ONCE; it opens again only when the teacher has ticked 'allow retry'."""
    last = latest_attempt(user, lesson)
    if last is None:
        return {"code": "open", "attempt": None, "can_attempt": True, "label": "Not attempted"}
    if last.retry_allowed:
        return {"code": "retry", "attempt": last, "can_attempt": True, "label": "Retry allowed by teacher"}
    if last.is_graded:
        return {"code": "graded", "attempt": last, "can_attempt": False, "label": f"Marks {last.marks}/{last.total}"}
    return {"code": "submitted", "attempt": last, "can_attempt": False, "label": "Submitted – waiting for teacher's marks"}


def student_overview(user):
    """Everything the student dashboard / progress page needs."""
    attempts = list(QuizAttempt.objects.filter(user=user).select_related("lesson").order_by("created"))
    per_lesson = {}
    for a in attempts:
        d = per_lesson.setdefault(a.lesson_id, {"lesson": a.lesson, "attempts": 0, "graded": 0, "waiting": 0, "best": None,
                                                "last": None, "sum": 0, "best_score": None, "total": a.total})
        d["attempts"] += 1
        if a.is_graded:
            d["graded"] += 1
            d["sum"] += a.final_percent
            d["last"] = a.final_percent
            if d["best"] is None or a.final_percent >= d["best"]:
                d["best"], d["best_score"], d["total"] = a.final_percent, a.marks, a.total
        else:
            d["waiting"] += 1
    for d in per_lesson.values():
        d["avg"] = round(d["sum"] / d["graded"]) if d["graded"] else None
    percents = [a.final_percent for a in attempts if a.is_graded]     # only teacher-marked quizzes count

    subs = list(Submission.objects.filter(student=user).select_related("assignment", "assignment__lesson"))
    work_subs = [s for s in subs if s.assignment.kind == Assignment.ASSIGNMENT]
    graded = [s for s in work_subs if s.is_graded]
    graded_pct = [round(100 * s.marks / s.assignment.total_marks) for s in graded if s.assignment.total_marks]

    visible = list(visible_assignments())
    subs_by_assignment = {s.assignment_id: s for s in subs}
    latest_by_lesson = {}
    for a in attempts:                       # attempts are ordered oldest -> newest
        latest_by_lesson[a.lesson_id] = a
    pending = []
    for a in visible:
        if a.kind == Assignment.QUIZ:
            last = latest_by_lesson.get(a.lesson_id)
            if last is not None and not last.retry_allowed:
                continue                     # already submitted (once) – nothing left to do
            a.retry = bool(last and last.retry_allowed)
        else:
            sub = subs_by_assignment.get(a.pk)
            if sub is not None and not sub.retry_allowed:
                continue
            a.retry = bool(sub and sub.retry_allowed)
        pending.append(a)
    pending.sort(key=lambda a: (a.due_date is None, a.due_date or timezone.now()))

    # marks published by the teacher (assignments + quizzes) for the "My marks" card
    marks_rows = []
    for sub_ in work_subs:
        if sub_.is_graded:
            marks_rows.append({"kind": "assignment", "title": sub_.assignment.title, "marks": sub_.marks,
                               "total": sub_.assignment.total_marks, "feedback": sub_.feedback, "when": sub_.graded_at,
                               "url": sub_.assignment.get_absolute_url()})
    for a in attempts:
        if a.is_graded:
            marks_rows.append({"kind": "quiz", "title": f"Quiz: {a.lesson.title}", "marks": a.marks, "total": a.total,
                               "feedback": a.feedback, "when": a.graded_at, "url": a.lesson.get_absolute_url()})
    marks_rows.sort(key=lambda r: r["when"] or timezone.now(), reverse=True)

    events = LearningEvent.objects.filter(user=user)
    scene_pairs = {(e.lesson_id, (e.payload or {}).get("scene_id")) for e in events.filter(event_type="vr.scene.viewed")}
    scenes_by_lesson = {}
    for lid, sid in scene_pairs:
        scenes_by_lesson.setdefault(lid, set()).add(sid)
    videos = set(events.filter(event_type__in=["vr.video.played", "vr.video.completed"]).values_list("lesson_id", flat=True))

    lessons = list(Lesson.objects.filter(status=Lesson.PUBLISHED).select_related("book").prefetch_related("scenes"))
    lesson_rows = []
    for l in lessons:
        n_scenes = len(l.scenes.all())
        seen = len(scenes_by_lesson.get(l.pk, ()))
        pl = per_lesson.get(l.pk)
        last = latest_by_lesson.get(l.pk)
        if last is None:
            qs_ = {"code": "open", "can_attempt": True, "label": "Not attempted"}
        elif last.retry_allowed:
            qs_ = {"code": "retry", "can_attempt": True, "label": "Retry allowed by teacher"}
        elif last.is_graded:
            qs_ = {"code": "graded", "can_attempt": False, "label": f"Marks {last.marks}/{last.total}"}
        else:
            qs_ = {"code": "submitted", "can_attempt": False, "label": "Submitted – waiting for marks"}
        lesson_rows.append({"lesson": l, "scenes": n_scenes, "seen": min(seen, n_scenes), "video": l.pk in videos,
                            "quiz": pl, "has_quiz": bool(active_quiz(l)), "quiz_state": qs_})
    return {
        "attempts": list(reversed(attempts)), "n_attempts": len(attempts),
        "avg_pct": round(sum(percents) / len(percents)) if percents else None,
        "best_pct": max(percents) if percents else None,
        "trend": percents[-10:], "per_lesson": sorted(per_lesson.values(), key=lambda d: d["lesson"].title),
        "submissions": subs, "n_submitted": len(work_subs), "n_graded": len(graded),
        "avg_assignment_pct": round(sum(graded_pct) / len(graded_pct)) if graded_pct else None,
        "pending": pending, "marks_rows": marks_rows, "lesson_rows": lesson_rows, "n_lessons": len(lessons),
        "scenes_viewed": sum(len(v) for v in scenes_by_lesson.values()), "videos_watched": len(videos),
    }


def pending_count(user):
    """How many visible tasks the student still has to do (bell badge). Mirrors the 'pending' rule of student_overview."""
    last_attempt = {}
    for a in QuizAttempt.objects.filter(user=user).order_by("created"):
        last_attempt[a.lesson_id] = a
    subs = {s.assignment_id: s for s in Submission.objects.filter(student=user)}
    n = 0
    for a in visible_assignments():
        if a.kind == Assignment.QUIZ:
            last = last_attempt.get(a.lesson_id)
            if last is not None and not last.retry_allowed:
                continue
        else:
            sub = subs.get(a.pk)
            if sub is not None and not sub.retry_allowed:
                continue
        n += 1
    return n


def class_overview(teacher):
    """Per-student summary of work on this teacher's lessons / assignments."""
    mine_lessons = Lesson.objects.filter(book__owner=teacher)
    mine_work = Assignment.objects.filter(owner=teacher, kind=Assignment.ASSIGNMENT, published=True)
    rows = []
    for st in students_qs().order_by("username"):
        att = list(QuizAttempt.objects.filter(user=st, lesson__in=mine_lessons))
        subs = list(Submission.objects.filter(student=st, assignment__owner=teacher, assignment__kind=Assignment.ASSIGNMENT))
        pct = [a.final_percent for a in att if a.is_graded]
        last = max([a.created for a in att] + [s.submitted_at for s in subs], default=None)
        if not att and not subs and not LearningEvent.objects.filter(user=st, lesson__in=mine_lessons).exists():
            continue
        rows.append({"student": st, "attempts": len(att), "avg": round(sum(pct) / len(pct)) if pct else None,
                     "best": max(pct) if pct else None, "submitted": len(subs), "of": mine_work.count(),
                     "views": LearningEvent.objects.filter(user=st, lesson__in=mine_lessons, event_type="vr.scene.viewed").count(),
                     "last": last})
    return rows
