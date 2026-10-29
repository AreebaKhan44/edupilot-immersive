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


def student_overview(user):
    """Everything the student dashboard / progress page needs."""
    attempts = list(QuizAttempt.objects.filter(user=user).select_related("lesson").order_by("created"))
    per_lesson = {}
    for a in attempts:
        d = per_lesson.setdefault(a.lesson_id, {"lesson": a.lesson, "attempts": 0, "best": 0, "last": 0, "sum": 0,
                                                "best_score": 0, "total": a.total})
        d["attempts"] += 1
        d["best"] = max(d["best"], a.percent)
        if a.percent >= d["best"]:
            d["best_score"], d["total"] = a.score, a.total
        d["last"] = a.percent
        d["sum"] += a.percent
    for d in per_lesson.values():
        d["avg"] = round(d["sum"] / d["attempts"])
    percents = [a.percent for a in attempts]

    subs = list(Submission.objects.filter(student=user).select_related("assignment", "assignment__lesson"))
    work_subs = [s for s in subs if s.assignment.kind == Assignment.ASSIGNMENT]
    graded = [s for s in work_subs if s.is_graded]
    graded_pct = [round(100 * s.marks / s.assignment.total_marks) for s in graded if s.assignment.total_marks]

    visible = list(visible_assignments())
    done_ids = {s.assignment_id for s in subs}
    attempted_lessons = set(per_lesson)
    pending = []
    for a in visible:
        if a.kind == Assignment.QUIZ and a.lesson_id in attempted_lessons:
            continue
        if a.kind != Assignment.QUIZ and a.pk in done_ids:
            continue
        pending.append(a)
    pending.sort(key=lambda a: (a.due_date is None, a.due_date or timezone.now()))

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
        lesson_rows.append({"lesson": l, "scenes": n_scenes, "seen": min(seen, n_scenes), "video": l.pk in videos,
                            "quiz": pl, "has_quiz": bool(active_quiz(l))})
    return {
        "attempts": list(reversed(attempts)), "n_attempts": len(attempts),
        "avg_pct": round(sum(percents) / len(percents)) if percents else None,
        "best_pct": max(percents) if percents else None,
        "trend": percents[-10:], "per_lesson": sorted(per_lesson.values(), key=lambda d: d["lesson"].title),
        "submissions": subs, "n_submitted": len(work_subs), "n_graded": len(graded),
        "avg_assignment_pct": round(sum(graded_pct) / len(graded_pct)) if graded_pct else None,
        "pending": pending, "lesson_rows": lesson_rows, "n_lessons": len(lessons),
        "scenes_viewed": sum(len(v) for v in scenes_by_lesson.values()), "videos_watched": len(videos),
    }


def class_overview(teacher):
    """Per-student summary of work on this teacher's lessons / assignments."""
    mine_lessons = Lesson.objects.filter(book__owner=teacher)
    mine_work = Assignment.objects.filter(owner=teacher, kind=Assignment.ASSIGNMENT, published=True)
    rows = []
    for st in students_qs().order_by("username"):
        att = list(QuizAttempt.objects.filter(user=st, lesson__in=mine_lessons))
        subs = list(Submission.objects.filter(student=st, assignment__owner=teacher, assignment__kind=Assignment.ASSIGNMENT))
        pct = [a.percent for a in att]
        last = max([a.created for a in att] + [s.submitted_at for s in subs], default=None)
        if not att and not subs and not LearningEvent.objects.filter(user=st, lesson__in=mine_lessons).exists():
            continue
        rows.append({"student": st, "attempts": len(att), "avg": round(sum(pct) / len(pct)) if pct else None,
                     "best": max(pct) if pct else None, "submitted": len(subs), "of": mine_work.count(),
                     "views": LearningEvent.objects.filter(user=st, lesson__in=mine_lessons, event_type="vr.scene.viewed").count(),
                     "last": last})
    return rows
