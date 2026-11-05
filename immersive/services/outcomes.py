"""Outcome progression, grade audit and follow-up (workflow doc s.5 stages 11-13, s.8).

Rules from the blueprint that are enforced here:
  * progress comes only from submitted evidence and teacher-reviewed marks (never from clicks / time spent);
  * every attempt is recorded separately; a changed mark needs a reason and leaves an audit record;
  * gaps -> targeted support + reassessment; achieved -> extension (both are editable suggestions).
"""
from django.conf import settings
from django.utils import timezone

from ..models import AuditEvent, GradeAudit, OutcomeProgress, SupportTask


def _progress(student, lesson):
    if lesson is None or lesson.outcome_id is None:
        return None
    obj, _ = OutcomeProgress.objects.get_or_create(student=student, outcome_id=lesson.outcome_id)
    return obj


def mark_started(student, lesson):
    """Student opened the lesson: 'In progress' (only if nothing better is recorded yet)."""
    p = _progress(student, lesson)
    if p and p.status == OutcomeProgress.NOT_STARTED:
        p.status = OutcomeProgress.IN_PROGRESS
        p.save(update_fields=["status", "updated"])
    return p


def record_evidence(student, lesson):
    """Student submitted a quiz / task: 'Evidence submitted' and waiting for review."""
    p = _progress(student, lesson)
    if p:
        p.status, p.reviewed = OutcomeProgress.EVIDENCE, False
        p.attempts += 1
        p.save(update_fields=["status", "reviewed", "attempts", "updated"])
    return p


def record_review(student, lesson, marks, total, teacher):
    """Teacher awarded marks: Developing / Achieved (mastery threshold from settings), reviewed=True, follow-up suggested."""
    p = _progress(student, lesson)
    if p is None or not total:
        return p
    pct = round(100 * marks / total)
    achieved = pct >= settings.EDUPILOT_MASTERY_PERCENT
    p.status = OutcomeProgress.ACHIEVED if achieved else OutcomeProgress.DEVELOPING
    p.reviewed = True
    p.best_percent = max(p.best_percent or 0, pct)
    p.save(update_fields=["status", "reviewed", "best_percent", "updated"])
    kind = SupportTask.EXTENSION if achieved else SupportTask.SUPPORT
    note = ("Extension: try a design/application task on this outcome." if achieved else
            "Targeted support: revisit the lesson, do guided practice, then reassess.")
    # drop an older open suggestion of the opposite kind, keep one open suggestion of the right kind
    SupportTask.objects.filter(student=student, outcome_id=lesson.outcome_id, auto=True, status=SupportTask.OPEN).exclude(kind=kind).update(status=SupportTask.DISMISSED)
    if not SupportTask.objects.filter(student=student, outcome_id=lesson.outcome_id, kind=kind, status=SupportTask.OPEN).exists():
        SupportTask.objects.create(student=student, outcome_id=lesson.outcome_id, lesson=lesson, kind=kind, note=note, auto=True, created_by=teacher)
    return p


def audit_grade(kind, ref_id, student, old_marks, new_marks, reason, by):
    GradeAudit.objects.create(kind=kind, ref_id=ref_id, student=student, old_marks=old_marks, new_marks=new_marks, reason=reason[:300], by=by)
    AuditEvent.objects.create(user=by, action=f"grade.{kind}", detail=f"{student.get_username()}: {old_marks} -> {new_marks} ({reason[:120]})")


def needs_override_reason(old_marks, new_marks):
    """Changing marks that were already awarded is an override and must carry a reason."""
    return old_marks is not None and old_marks != new_marks


def log(user, action, detail=""):
    AuditEvent.objects.create(user=user if getattr(user, "pk", None) else None, action=action, detail=detail[:300])


def now():
    return timezone.now()
