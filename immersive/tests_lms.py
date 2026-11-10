"""Tests for the Immersive LMS workflow modules and the quiz-submit IntegrityError regression."""
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (AuditEvent, ClassSession, Curriculum, Device, DeviceBooking, DeviceFault, Enrolment, GradeAudit,
                     GuardianLink, Lesson, Outcome, OutcomeProgress, QuizAttempt, SchoolClass, Subject, SupportTask)
from .tests import TEXT

TMP = tempfile.mkdtemp()
PW = "pw12345!x"


@override_settings(MEDIA_ROOT=TMP)
class LmsTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def published_lesson(self):
        self.client.login(username="t", password=PW)
        r = self.client.post(reverse("book_create"), {"title": "Sci", "language": "en", "raw_text": TEXT, "publish_now": "on", "make_quiz": "on"})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        return Lesson.objects.first()

    def submit_quiz(self, lesson, correct=True):
        data = {f"q{q.pk}": (q.answer_index if correct else (q.answer_index + 1) % len(q.options)) for q in lesson.questions.all()}
        return self.client.post(reverse("quiz", args=[lesson.pk]), data)

    def setUp(self):
        self.teacher = User.objects.create_user("t", password=PW)
        self.teacher.groups.add(Group.objects.create(name="Teacher"))
        self.student = User.objects.create_user("s", password=PW)
        self.admin = User.objects.create_user("a", password=PW, is_staff=True)
        self.lesson = self.published_lesson()
        sub = Subject.objects.create(name="Science", family="sciences")
        cur = Curriculum.objects.create(name="Punjab Board", version="2026")
        self.outcome = Outcome.objects.create(curriculum=cur, subject=sub, level="g6_8", code="SCI7.1", description="Explain circuits")
        self.lesson.outcome = self.outcome
        self.lesson.save()
        self.klass = SchoolClass.objects.create(name="7A Science", teacher=self.teacher, subject=sub, level="g6_8")
        Enrolment.objects.create(school_class=self.klass, student=self.student)

    def login(self, name):
        self.client.logout()
        self.client.login(username=name, password=PW)

    # ---- the production bug -------------------------------------------------------
    def test_insert_without_feedback_columns_does_not_violate_not_null(self):
        """Old code that does not know the grading columns must still be able to insert (DB-level defaults)."""
        with connection.cursor() as c:
            c.execute("INSERT INTO immersive_quizattempt (user_id, lesson_id, score, total, answers, created) VALUES (%s, %s, 1, 5, '{}', %s)",
                      [self.student.pk, self.lesson.pk, timezone.now()])
        a = QuizAttempt.objects.get(score=1)
        self.assertEqual((a.feedback, a.retry_allowed, a.marks), ("", False, None))

    def test_quiz_submit_works(self):
        self.login("s")
        self.assertEqual(self.submit_quiz(self.lesson).status_code, 302)
        self.assertEqual(QuizAttempt.objects.filter(user=self.student).count(), 1)

    # ---- outcome progression ------------------------------------------------------
    def test_progress_flow_and_followup(self):
        self.login("s")
        self.client.get(reverse("viewer", args=[self.lesson.pk]))
        self.assertEqual(OutcomeProgress.objects.get().status, "in_progress")
        self.submit_quiz(self.lesson, correct=False)
        self.assertEqual(OutcomeProgress.objects.get().status, "evidence")
        att = QuizAttempt.objects.get()
        self.login("t")
        self.client.post(reverse("attempt_grade", args=[att.pk]), {"marks": 1, "feedback": "revise"})
        p = OutcomeProgress.objects.get()
        self.assertEqual((p.status, p.reviewed), ("developing", True))
        self.assertEqual(SupportTask.objects.get().kind, "support")
        # retry -> full marks -> achieved, support suggestion replaced by an extension
        self.client.post(reverse("attempt_retry", args=[att.pk]))
        self.login("s")
        self.submit_quiz(self.lesson, correct=True)
        att2 = QuizAttempt.objects.order_by("-created").first()
        self.login("t")
        self.client.post(reverse("attempt_grade", args=[att2.pk]), {"marks": att2.total})
        self.assertEqual(OutcomeProgress.objects.get().status, "achieved")
        self.assertEqual(SupportTask.objects.filter(status="open").get().kind, "extension")

    def test_lesson_without_outcome_creates_no_progress(self):
        self.lesson.outcome = None
        self.lesson.save()
        self.login("s")
        self.submit_quiz(self.lesson)
        self.assertEqual(OutcomeProgress.objects.count(), 0)

    # ---- score override ------------------------------------------------------------
    def test_changing_marks_needs_reason_and_is_audited(self):
        self.login("s")
        self.submit_quiz(self.lesson)
        att = QuizAttempt.objects.get()
        self.login("t")
        url = reverse("attempt_grade", args=[att.pk])
        self.client.post(url, {"marks": 2})
        self.client.post(url, {"marks": 4})                       # no reason -> refused
        att.refresh_from_db()
        self.assertEqual(att.marks, 2)
        self.client.post(url, {"marks": 4, "reason": "re-checked answer 3"})
        att.refresh_from_db()
        self.assertEqual(att.marks, 4)
        audits = list(GradeAudit.objects.order_by("created"))
        self.assertEqual([(a.old_marks, a.new_marks) for a in audits], [(None, 2), (2, 4)])
        self.assertEqual(audits[1].reason, "re-checked answer 3")
        self.assertTrue(AuditEvent.objects.filter(action="grade.attempt").exists())

    # ---- classes, sessions, curriculum ---------------------------------------------
    def test_students_cannot_open_teacher_pages(self):
        self.login("s")
        for name in ("class_list", "curriculum_home", "lab", "reports"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.client.get(reverse("my_learning")).status_code, 200)

    def test_schedule_and_run_session(self):
        self.login("t")
        when = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("class_detail", args=[self.klass.pk]),
                             {"form": "session", "lesson": self.lesson.pk, "scheduled_for": when, "room": "Lab 1", "mode": "vr"})
        self.assertEqual(r.status_code, 302)
        s = ClassSession.objects.get()
        self.assertEqual(s.lesson_version, self.lesson.version)
        act = lambda a: self.client.post(reverse("session_action", args=[s.pk]), {"action": a})
        act("end"); s.refresh_from_db(); self.assertEqual(s.status, "scheduled")     # cannot end before launch
        act("launch"); s.refresh_from_db(); self.assertEqual(s.status, "live")
        act("end"); s.refresh_from_db(); self.assertEqual(s.status, "ended")
        self.login("s")
        self.assertContains(self.client.get(reverse("my_learning")), self.lesson.title)

    def test_other_teacher_cannot_open_class(self):
        other = User.objects.create_user("t2", password=PW)
        other.groups.add(Group.objects.get(name="Teacher"))
        self.login("t2")
        self.assertEqual(self.client.get(reverse("class_detail", args=[self.klass.pk])).status_code, 403)

    def test_enrol_by_username_reports_unknown(self):
        self.login("t")
        User.objects.create_user("s9", password=PW)
        r = self.client.post(reverse("class_detail", args=[self.klass.pk]), {"form": "enrol", "usernames": "s9, nobody"}, follow=True)
        self.assertTrue(Enrolment.objects.filter(school_class=self.klass, student__username="s9").exists())
        self.assertContains(r, "nobody")

    def test_curriculum_create_outcome(self):
        self.login("t")
        self.client.post(reverse("curriculum_home"), {"form": "outcome", "o-curriculum": self.outcome.curriculum_id, "o-subject": self.outcome.subject_id,
                                                        "o-level": "g6_8", "o-code": "SCI7.2", "o-description": "Compare series/parallel"})
        self.assertTrue(Outcome.objects.filter(code="SCI7.2").exists())

    def test_lesson_design_saves_and_checklist(self):
        self.login("t")
        r = self.client.post(reverse("lesson_design", args=[self.lesson.pk]), {
            "outcome": self.outcome.pk, "mode": "vr", "duration_minutes": 45, "success_criteria": "Build a circuit",
            "alternative_route": "Use the 2D simulator", "prerequisites": "", "device_requirements": "", "accessibility_features": "captions", "licence": ""})
        self.assertEqual(r.status_code, 302)
        self.lesson.refresh_from_db()
        self.assertEqual((self.lesson.mode, self.lesson.duration_minutes), ("vr", 45))

    @override_settings(EDUPILOT_REQUIRE_ALT_ROUTE=True)
    def test_headset_lesson_needs_alternative_route_to_publish(self):
        self.lesson.status, self.lesson.mode, self.lesson.alternative_route = Lesson.DRAFT, "vr", ""
        self.lesson.save()
        self.login("t")
        self.client.post(reverse("lesson_workflow", args=[self.lesson.pk]), {"action": "publish"})
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.DRAFT)
        self.lesson.alternative_route = "Use the screen simulator"
        self.lesson.save()
        self.client.post(reverse("lesson_workflow", args=[self.lesson.pk]), {"action": "publish"})
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.PUBLISHED)

    # ---- guardian ---------------------------------------------------------------------
    def test_guardian_sees_only_linked_child(self):
        g = User.objects.create_user("g", password=PW)
        g.groups.add(Group.objects.create(name="Guardian"))
        other = User.objects.create_user("s2", password=PW)
        GuardianLink.objects.create(guardian=g, student=self.student)
        OutcomeProgress.objects.create(student=self.student, outcome=self.outcome, status="achieved")
        self.assertTrue(OutcomeProgress.objects.filter(student=other).count() == 0)
        self.login("g")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)       # lands on guardian page
        r = self.client.get(reverse("guardian_home"))
        self.assertContains(r, "SCI7.1")
        self.assertNotContains(r, "s2")

    # ---- lab operations ---------------------------------------------------------------
    def test_lab_booking_and_fault_flow(self):
        d = Device.objects.create(code="Q3-01", model="Quest 3")
        self.login("t")
        when = timezone.now() + timedelta(days=1)
        s = ClassSession.objects.create(school_class=self.klass, lesson=self.lesson, scheduled_for=when, created_by=self.teacher)
        self.client.post(reverse("booking_action"), {"action": "request", "session": s.pk, "device": d.pk})
        b = DeviceBooking.objects.get()
        self.assertEqual(self.client.post(reverse("booking_action"), {"action": "approve", "booking": b.pk}).status_code, 403)   # teacher is not lab manager
        self.login("a")                                                                                   # staff = lab coordinator
        step = lambda a: self.client.post(reverse("booking_action"), {"action": a, "booking": b.pk})
        step("issue"); b.refresh_from_db(); self.assertEqual(b.status, "requested")                       # cannot skip approval
        step("approve"); step("issue")
        d.refresh_from_db(); self.assertEqual(d.status, "issued")
        step("return"); d.refresh_from_db(); self.assertEqual(d.status, "available")
        self.client.post(reverse("lab"), {"form": "fault", "f-device": d.pk, "f-description": "Left controller drifts"})
        d.refresh_from_db(); self.assertEqual(d.status, "maintenance")
        f = DeviceFault.objects.get()
        self.client.post(reverse("fault_action", args=[f.pk]), {"action": "assign", "owner": self.admin.pk})
        self.client.post(reverse("fault_action", args=[f.pk]), {"action": "resolve"})
        d.refresh_from_db(); f.refresh_from_db()
        self.assertEqual((d.status, f.status), ("available", "resolved"))

    def test_device_double_booking_blocked(self):
        d = Device.objects.create(code="Q3-02")
        when = timezone.now() + timedelta(days=2)
        c2 = SchoolClass.objects.create(name="7B", teacher=self.teacher)
        s1 = ClassSession.objects.create(school_class=self.klass, lesson=self.lesson, scheduled_for=when)
        s2 = ClassSession.objects.create(school_class=c2, lesson=self.lesson, scheduled_for=when)
        self.login("t")
        for s in (s1, s2):
            self.client.post(reverse("booking_action"), {"action": "request", "session": s.pk, "device": d.pk})
        self.assertEqual(DeviceBooking.objects.count(), 1)

    # ---- reports & ERP export ---------------------------------------------------------
    def test_reports_and_erp_export(self):
        self.login("s")
        self.submit_quiz(self.lesson)
        self.login("t")
        self.assertEqual(self.client.get(reverse("reports")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api_erp_results")).status_code, 403)       # only reviewers/staff
        att = QuizAttempt.objects.get()
        self.client.post(reverse("attempt_grade", args=[att.pk]), {"marks": 3})
        self.login("a")
        data = self.client.get(reverse("api_erp_results")).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual((data["results"][0]["outcome"], data["results"][0]["marks"]), ("SCI7.1", 3))
