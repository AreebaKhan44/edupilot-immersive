"""Views for the Immersive LMS workflow (see Immersive_LMS_Complete_Workflow.docx)."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import (ClassForm, CurriculumForm, DeviceForm, EnrolForm, FaultForm, LessonDesignForm, OutcomeForm,
                    SessionForm, SubjectForm)
from .models import (Assignment, AuditEvent, ClassSession, Curriculum, Device, DeviceBooking, DeviceFault, Enrolment, GradeAudit,
                     GuardianLink, Lesson, Outcome, OutcomeProgress, QuizAttempt, SchoolClass, Subject, Submission,
                     SupportTask, HEADSET_MODES)
from .services import analytics, outcomes
from .views import is_reviewer, is_teacher

User = get_user_model()


def teacher_required(user):
    if not is_teacher(user):
        raise PermissionDenied


def own_class(request, pk):
    c = get_object_or_404(SchoolClass.objects.select_related("subject", "teacher"), pk=pk)
    if c.teacher_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    return c


# ---------------------------------------------------------------- lesson design -----
def release_checklist(lesson):
    """Content checks from workflow s.7 / s.14 - shown to the teacher before publishing."""
    items = [
        ("Linked to a curriculum outcome", lesson.outcome_id is not None),
        ("Success criteria written", bool(lesson.success_criteria.strip())),
        ("Quiz / assessment questions exist", lesson.questions.exists()),
        ("Accessibility features listed", bool(lesson.accessibility_features.strip())),
    ]
    if lesson.mode in HEADSET_MODES or lesson.mode == "interactive_3d":
        items.append(("Screen-based alternative route (no headset needed)", bool(lesson.alternative_route.strip())))
    return items


@login_required
def lesson_design(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("book", "outcome"), pk=pk)
    if lesson.book.owner_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    form = LessonDesignForm(request.POST or None, instance=lesson)
    if request.method == "POST" and form.is_valid():
        form.save()
        outcomes.log(request.user, "lesson.design", f"lesson {lesson.pk}")
        messages.success(request, "Lesson design saved.")
        return redirect("lesson_design", pk=lesson.pk)
    return render(request, "immersive/lesson_design.html", {"lesson": lesson, "form": form, "checklist": release_checklist(lesson),
                                                            "require_alt": settings.EDUPILOT_REQUIRE_ALT_ROUTE})


# ---------------------------------------------------------------- curriculum -------
@login_required
def curriculum_home(request):
    teacher_required(request.user)
    forms = {"curriculum": CurriculumForm(prefix="c"), "subject": SubjectForm(prefix="s"), "outcome": OutcomeForm(prefix="o")}
    if request.method == "POST":
        which = request.POST.get("form")
        cls = {"curriculum": (CurriculumForm, "c"), "subject": (SubjectForm, "s"), "outcome": (OutcomeForm, "o")}.get(which)
        if cls is None:
            raise Http404
        f = cls[0](request.POST, prefix=cls[1])
        if f.is_valid():
            obj = f.save(commit=False)
            if which == "curriculum":
                obj.review_owner = request.user
            obj.save()
            outcomes.log(request.user, f"{which}.created", str(obj))
            messages.success(request, f"{which.title()} saved.")
            return redirect("curriculum_home")
        forms[which] = f
    cur = Curriculum.objects.annotate(n=Count("outcomes"))
    out = Outcome.objects.select_related("curriculum", "subject").annotate(n_lessons=Count("lessons", distinct=True))
    return render(request, "immersive/curriculum.html", {"forms": forms, "curricula": cur, "outcome_list": out, "subjects": Subject.objects.all()})


# ---------------------------------------------------------------- classes ----------
@login_required
def class_list(request):
    teacher_required(request.user)
    qs = SchoolClass.objects.select_related("subject").annotate(n=Count("enrolments", distinct=True))
    if not request.user.is_staff:
        qs = qs.filter(teacher=request.user)
    form = ClassForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.teacher = request.user
        c.save()
        messages.success(request, "Class created.")
        return redirect(c)
    return render(request, "immersive/class_list.html", {"classes": qs, "form": form})


@login_required
def class_detail(request, pk):
    c = own_class(request, pk)
    enrol_form, session_form = EnrolForm(), SessionForm(teacher=request.user)
    if request.method == "POST":
        which = request.POST.get("form")
        if which == "enrol":
            enrol_form = EnrolForm(request.POST)
            if enrol_form.is_valid():
                names = [n.strip() for n in enrol_form.cleaned_data["usernames"].replace("\n", ",").split(",") if n.strip()]
                found = User.objects.filter(username__in=names)
                for u in found:
                    Enrolment.objects.get_or_create(school_class=c, student=u)
                missing = sorted(set(names) - {u.username for u in found})
                messages.success(request, f"{found.count()} student(s) enrolled.")
                if missing:
                    messages.error(request, "Unknown username(s): " + ", ".join(missing))
                return redirect(c)
        elif which == "session":
            session_form = SessionForm(request.POST, teacher=request.user)
            if session_form.is_valid():
                s = session_form.save(commit=False)
                s.school_class, s.created_by, s.lesson_version = c, request.user, s.lesson.version
                s.save()
                outcomes.log(request.user, "session.scheduled", str(s))
                messages.success(request, "Session scheduled.")
                return redirect(c)
        else:
            raise Http404
    students = [e.student for e in c.enrolments.select_related("student").order_by("student__username")]
    outs = list(Outcome.objects.filter(lessons__sessions__school_class=c).distinct().select_related("subject"))
    prog = {(p.student_id, p.outcome_id): p for p in OutcomeProgress.objects.filter(student__in=students, outcome__in=outs)}
    matrix = [{"student": s, "cells": [prog.get((s.pk, o.pk)) for o in outs]} for s in students]
    return render(request, "immersive/class_detail.html", {
        "c": c, "students": students, "enrol_form": enrol_form, "session_form": session_form, "outs": outs, "matrix": matrix,
        "sessions": c.sessions.select_related("lesson").prefetch_related("bookings__device"),
        "support": SupportTask.objects.filter(student__in=students, status=SupportTask.OPEN).select_related("student", "outcome")})


@require_POST
@login_required
def class_unenrol(request, pk, student_id):
    c = own_class(request, pk)
    Enrolment.objects.filter(school_class=c, student_id=student_id).delete()
    messages.success(request, "Student removed from the class.")
    return redirect(c)


@require_POST
@login_required
def session_action(request, pk):
    """Teacher controls during delivery (s.6): launch / end / cancel, and record observations."""
    s = get_object_or_404(ClassSession.objects.select_related("school_class"), pk=pk)
    own_class(request, s.school_class_id)
    action = request.POST.get("action")
    now = timezone.now()
    if action == "launch" and s.status == ClassSession.SCHEDULED:
        s.status, s.started_at = ClassSession.LIVE, now
    elif action == "end" and s.status == ClassSession.LIVE:
        s.status, s.ended_at = ClassSession.ENDED, now
    elif action == "cancel" and s.status in (ClassSession.SCHEDULED, ClassSession.LIVE):
        s.status = ClassSession.CANCELLED
    elif action == "notes":
        s.notes = request.POST.get("notes", "")[:2000]
    else:
        messages.error(request, "That action is not possible for this session's current status.")
        return redirect(s.school_class)
    s.save()
    outcomes.log(request.user, f"session.{action}", str(s))
    return redirect(s.school_class)


@require_POST
@login_required
def support_action(request, pk):
    t = get_object_or_404(SupportTask.objects.select_related("student"), pk=pk)
    teacher_required(request.user)
    if not request.user.is_staff and not SchoolClass.objects.filter(teacher=request.user, enrolments__student=t.student).exists():
        raise PermissionDenied
    action = request.POST.get("action")
    if action in ("done", "dismissed"):
        t.status = action
        t.save(update_fields=["status"])
    elif action == "edit":
        t.note = request.POST.get("note", "")[:1000]
        t.auto = False
        t.save(update_fields=["note", "auto"])
    return redirect(request.POST.get("next") or "class_list")


# ---------------------------------------------------------------- student ----------
@login_required
def my_learning(request):
    """Student: today's sessions, pending follow-up, outcome progress (s.6 student workflow)."""
    user = request.user
    class_ids = list(Enrolment.objects.filter(student=user).values_list("school_class_id", flat=True))
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    upcoming = ClassSession.objects.filter(school_class_id__in=class_ids, scheduled_for__gte=start).exclude(
        status=ClassSession.CANCELLED).select_related("lesson", "school_class")[:10]
    progress = OutcomeProgress.objects.filter(student=user).select_related("outcome__subject")
    tasks = SupportTask.objects.filter(student=user, status=SupportTask.OPEN).select_related("outcome", "lesson")
    ov = analytics.student_overview(user)
    done_lessons = sum(1 for r in ov["lesson_rows"] if (r["scenes"] and r["seen"] >= r["scenes"]) or r["quiz"])
    graded = [a for a in ov["attempts"] if a.is_graded]
    passed = sum(1 for a in graded if a.final_percent >= 50)
    work_total = analytics.visible_assignments([Assignment.ASSIGNMENT]).count()
    parts = [(done_lessons, ov["n_lessons"]), (passed, ov["n_attempts"]), (ov["n_graded"], work_total)]
    den = sum(b for _, b in parts)
    ctx = dict(ov)
    ctx.update({"upcoming": upcoming, "progress": progress, "tasks": tasks, "today": start.date(),
                "done_lessons": done_lessons, "passed": passed, "work_total": work_total,
                "overall": round(100 * sum(a for a, _ in parts) / den) if den else 0,
                "pct_lessons": round(100 * done_lessons / ov["n_lessons"]) if ov["n_lessons"] else 0,
                "pct_quizzes": round(100 * passed / ov["n_attempts"]) if ov["n_attempts"] else 0,
                "pct_work": round(100 * ov["n_graded"] / work_total) if work_total else 0})
    return render(request, "immersive/my_learning.html", ctx)


# ---------------------------------------------------------------- guardian ---------
@login_required
def guardian_home(request):
    kids = [g.student for g in GuardianLink.objects.filter(guardian=request.user).select_related("student")]
    rows = []
    for k in kids:   # a guardian sees ONLY linked learners (s.10)
        rows.append({"student": k,
                     "progress": OutcomeProgress.objects.filter(student=k).select_related("outcome"),
                     "attempts": QuizAttempt.objects.filter(user=k, marks__isnull=False).select_related("lesson")[:5],
                     "subs": Submission.objects.filter(student=k, marks__isnull=False).select_related("assignment")[:5]})
    return render(request, "immersive/guardian.html", {"rows": rows})


# ---------------------------------------------------------------- lab ops ----------
@login_required
def lab(request):
    teacher_required(request.user)
    manager = request.user.is_staff or is_reviewer(request.user)
    forms = {"device": DeviceForm(prefix="d"), "fault": FaultForm(prefix="f")}
    if request.method == "POST":
        which = request.POST.get("form")
        if which == "device":
            if not manager:
                raise PermissionDenied
            f = DeviceForm(request.POST, prefix="d")
            if f.is_valid():
                f.save()
                messages.success(request, "Device added to inventory.")
                return redirect("lab")
            forms["device"] = f
        elif which == "fault":
            f = FaultForm(request.POST, prefix="f")
            if f.is_valid():
                fault = f.save(commit=False)
                fault.reported_by = request.user
                fault.save()
                Device.objects.filter(pk=fault.device_id).exclude(status=Device.RETIRED).update(status=Device.MAINTENANCE)
                outcomes.log(request.user, "device.fault", f"{fault.device}: {fault.description[:100]}")
                messages.success(request, "Fault recorded; the device is marked 'in maintenance'.")
                return redirect("lab")
            forms["fault"] = f
        else:
            raise Http404
    sessions = ClassSession.objects.filter(status=ClassSession.SCHEDULED, scheduled_for__gte=timezone.now()).select_related(
        "school_class", "lesson")
    if not request.user.is_staff:
        sessions = sessions.filter(school_class__teacher=request.user)
    return render(request, "immersive/lab.html", {
        "manager": manager, "forms": forms, "devices": Device.objects.all(), "faults": DeviceFault.objects.select_related("device", "owner")[:20],
        "bookings": DeviceBooking.objects.select_related("device", "session__school_class", "session__lesson").exclude(
            status__in=[DeviceBooking.RETURNED, DeviceBooking.REJECTED]), "sessions": sessions,
        "available": Device.objects.filter(status=Device.AVAILABLE), "staff_users": User.objects.filter(is_staff=True)})


@require_POST
@login_required
def booking_action(request):
    teacher_required(request.user)
    manager = request.user.is_staff or is_reviewer(request.user)
    action = request.POST.get("action")
    if action == "request":
        s = get_object_or_404(ClassSession, pk=request.POST.get("session"))
        own_class(request, s.school_class_id)
        d = get_object_or_404(Device, pk=request.POST.get("device"), status=Device.AVAILABLE)
        clash = DeviceBooking.objects.filter(device=d, session__scheduled_for=s.scheduled_for).exclude(
            status__in=[DeviceBooking.RETURNED, DeviceBooking.REJECTED]).exclude(session=s).exists()
        if clash:
            messages.error(request, "That device is already booked for the same time.")
        else:
            DeviceBooking.objects.get_or_create(session=s, device=d, defaults={"requested_by": request.user})
            messages.success(request, "Booking requested.")
        return redirect("lab")
    if not manager:
        raise PermissionDenied
    b = get_object_or_404(DeviceBooking.objects.select_related("device"), pk=request.POST.get("booking"))
    flow = {"approve": (DeviceBooking.REQUESTED, DeviceBooking.APPROVED), "reject": (DeviceBooking.REQUESTED, DeviceBooking.REJECTED),
            "issue": (DeviceBooking.APPROVED, DeviceBooking.ISSUED), "return": (DeviceBooking.ISSUED, DeviceBooking.RETURNED)}
    if action not in flow or b.status != flow[action][0]:
        messages.error(request, "That step is not possible from the booking's current status.")
        return redirect("lab")
    b.status = flow[action][1]
    if action == "return":
        b.return_note = request.POST.get("return_note", "")[:200]
    b.save()
    if action == "issue":
        Device.objects.filter(pk=b.device_id).update(status=Device.ISSUED)
    elif action == "return" and b.device.status == Device.ISSUED:
        Device.objects.filter(pk=b.device_id).update(status=Device.AVAILABLE)
    outcomes.log(request.user, f"booking.{action}", f"{b.device} / session {b.session_id}")
    return redirect("lab")


@require_POST
@login_required
def fault_action(request, pk):
    if not (request.user.is_staff or is_reviewer(request.user)):
        raise PermissionDenied
    f = get_object_or_404(DeviceFault.objects.select_related("device"), pk=pk)
    action = request.POST.get("action")
    if action == "assign":
        f.owner = get_object_or_404(User, pk=request.POST.get("owner"), is_staff=True)
        f.status = DeviceFault.ASSIGNED
    elif action == "resolve":
        f.status, f.resolved_at = DeviceFault.RESOLVED, timezone.now()
        if not f.device.faults.exclude(pk=f.pk).exclude(status=DeviceFault.RESOLVED).exists() and f.device.status == Device.MAINTENANCE:
            Device.objects.filter(pk=f.device_id).update(status=Device.AVAILABLE)   # back in service
    else:
        raise Http404
    f.save()
    outcomes.log(request.user, f"fault.{action}", str(f.device))
    return redirect("lab")


# ---------------------------------------------------------------- reports ----------
@login_required
def reports(request):
    """Leadership indicators (s.10). Completion/participation are shown separately from mastery."""
    teacher_required(request.user)
    prog = OutcomeProgress.objects.all()
    if not request.user.is_staff:
        prog = prog.filter(student__enrolments__school_class__teacher=request.user).distinct()
    by_status = {code: prog.filter(status=code).count() for code, _ in OutcomeProgress.STATUS}
    awaiting = prog.filter(status=OutcomeProgress.EVIDENCE).count()
    cover = Outcome.objects.select_related("subject", "curriculum").annotate(
        n_pub=Count("lessons", filter=Q(lessons__status=Lesson.PUBLISHED), distinct=True),
        n_ach=Count("progress", filter=Q(progress__status=OutcomeProgress.ACHIEVED), distinct=True),
        n_dev=Count("progress", filter=Q(progress__status=OutcomeProgress.DEVELOPING), distinct=True))
    sessions = ClassSession.objects.all() if request.user.is_staff else ClassSession.objects.filter(school_class__teacher=request.user)
    ctx = {"by_status": by_status, "awaiting": awaiting, "cover": cover, "uncovered": cover.filter(n_pub=0).count(),
           "sess": {s: sessions.filter(status=s).count() for s, _ in ClassSession.STATUS},
           "devices": {s: Device.objects.filter(status=s).count() for s, _ in Device.STATUS},
           "open_faults": DeviceFault.objects.exclude(status=DeviceFault.RESOLVED).count(),
           "open_support": SupportTask.objects.filter(status=SupportTask.OPEN).count(),
           "audits": GradeAudit.objects.select_related("student", "by")[:15], "events": AuditEvent.objects.select_related("user")[:15],
           "mastery": settings.EDUPILOT_MASTERY_PERCENT}
    return render(request, "immersive/reports.html", ctx)


# ---------------------------------------------------------------- ERP export -------
@require_GET
@login_required
def api_erp_results(request):
    """Reviewed results for transfer to the ERP (s.12). Stable ids; only teacher-reviewed marks are exported."""
    if not is_reviewer(request.user):
        raise PermissionDenied
    rows = []
    for a in QuizAttempt.objects.filter(marks__isnull=False).select_related("user", "lesson__outcome"):
        rows.append({"result_id": f"quiz-{a.pk}", "student": a.user.get_username(), "lesson_id": a.lesson_id, "lesson_version": a.lesson.version,
                     "outcome": a.lesson.outcome.code if a.lesson.outcome_id else None, "marks": a.marks, "total": a.total,
                     "reviewed_at": a.graded_at.isoformat() if a.graded_at else None})
    for sub in Submission.objects.filter(marks__isnull=False, assignment__kind="assignment").select_related("student", "assignment__lesson__outcome"):
        a = sub.assignment
        rows.append({"result_id": f"assignment-{sub.pk}", "student": sub.student.get_username(), "lesson_id": a.lesson_id,
                     "lesson_version": a.lesson.version if a.lesson_id else None,
                     "outcome": a.lesson.outcome.code if a.lesson_id and a.lesson.outcome_id else None, "marks": sub.marks,
                     "total": a.total_marks, "reviewed_at": sub.graded_at.isoformat() if sub.graded_at else None})
    return JsonResponse({"count": len(rows), "results": rows})
