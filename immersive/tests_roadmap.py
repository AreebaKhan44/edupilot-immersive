"""Tests for the roadmap-document features and the book -> plan -> pictures -> 3D flow."""
import io
import shutil
import tempfile
import textwrap

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from .models import (Book, ContentIssue, Curriculum, CurriculumMapping, Lesson, LessonVersion, MarketAssessment, Outcome, SceneImage,
                     Subject, ClassSession, SchoolClass)
from .services import bookimages, diagrams, pipeline
from .tests import TEXT

TMP = tempfile.mkdtemp()


def make_pdf():
    """Two-chapter PDF, each chapter page carries one picture."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    chapters = [p.strip() for p in TEXT.split("\n\n") if p.strip()]
    for n, chap in enumerate(chapters):
        im = Image.new("RGB", (400, 300), (30 + 90 * n, 120, 200 - 80 * n))
        d = ImageDraw.Draw(im)
        for k in range(12):                          # distinct picture content (the logo filter compares pictures)
            d.ellipse([20 + 25 * k * (n + 1) % 300, 20 + 17 * k, 90 + 25 * k * (n + 1) % 300, 100 + 17 * k], outline=(255, 255, 255), width=3)
        c.drawImage(ImageReader(im), 60, 450, width=300, height=225)
        y = 420
        for para in chap.split("\n"):
            for line in textwrap.wrap(para, 90):
                c.drawString(50, y, line)
                y -= 14
        c.showPage()
    c.save()
    return buf.getvalue()


@override_settings(MEDIA_ROOT=TMP)
class RoadmapTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        for g in ("Teacher", "Reviewer", "Student", "Creator"):
            Group.objects.get_or_create(name=g)
        self.teacher = User.objects.create_user("t", password="pw12345!x")
        self.teacher.groups.add(Group.objects.get(name="Teacher"))
        self.reviewer = User.objects.create_user("r", password="pw12345!x")
        self.reviewer.groups.add(Group.objects.get(name="Reviewer"))
        self.student = User.objects.create_user("s", password="pw12345!x")

    def book(self, pdf=False):
        b = Book.objects.create(owner=self.teacher, title="Sci", raw_text=TEXT)
        if pdf:
            class F:   # what read_pdf_upload expects: an object with .read()
                def read(self_inner):
                    return make_pdf()
            text, pages, images = pipeline.read_pdf_upload(F())
            b.raw_text = text
            b.save()
            return b, pipeline.create_lessons_from_book(b, pages, images)
        return b, pipeline.create_lessons_from_book(b)

    # ---- plan first, pictures second
    def test_plan_has_phases_and_every_scene_has_a_picture(self):
        _, lessons = self.book()
        for l in lessons:
            self.assertTrue(l.has_plan)
            self.assertEqual([p["phase"] for p in l.plan["phases"]][0], "Introduction")
            self.assertTrue(l.rubric and l.success_criteria and l.alternative_route)
            for sc in l.scenes.all():
                pics = list(sc.pictures.all())
                self.assertEqual(len(pics), 1)
                self.assertEqual(pics[0].kind, SceneImage.GENERATED)
                self.assertTrue(pics[0].alt_text)

    def test_pdf_pictures_go_to_the_right_lesson(self):
        book, lessons = self.book(pdf=True)
        self.assertEqual(len(lessons), 2)
        self.assertEqual(book.images.filter(kind="book").count(), 2)
        for i, l in enumerate(lessons):
            pics = l.pictures.filter(kind="book")
            self.assertEqual(pics.count(), 1, f"lesson {i}")
            self.assertEqual(pics.first().page, i + 1)
            # the scene that got the book picture does not also get a generated one
            sc = pics.first().scene
            self.assertFalse(sc.pictures.filter(kind="generated").exists())
        m = lessons[0].manifest()
        self.assertTrue(any(im["kind"] == "book" for s in m["scenes"] for im in s["images"]))
        self.assertIn("From your book" if False else "book", {im["kind"] for s in m["scenes"] for im in s["images"]})

    def test_regenerate_keeps_book_pictures(self):
        _, lessons = self.book(pdf=True)
        l = lessons[0]
        pipeline.regenerate(l)
        l.refresh_from_db()
        self.assertEqual(l.pictures.filter(kind="book").count(), 1)
        self.assertTrue(l.pictures.filter(kind="book").first().scene_id)
        self.assertTrue(all(sc.pictures.exists() for sc in l.scenes.all()))

    def test_viewer_needs_a_plan(self):
        b = Book.objects.create(owner=self.teacher, title="x", raw_text="y")
        l = Lesson.objects.create(book=b, title="Empty")
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("viewer", args=[l.pk]))
        self.assertRedirects(r, reverse("lesson_detail", args=[l.pk]), fetch_redirect_response=False)
        _, lessons = self.book()
        self.assertEqual(self.client.get(reverse("viewer", args=[lessons[0].pk])).status_code, 200)

    def test_book_upload_builds_plan_and_does_not_publish(self):
        self.client.force_login(self.teacher)
        r = self.client.post(reverse("book_create"), {"title": "PDF", "language": "en", "pdf": SimpleUploadedFile("b.pdf", make_pdf(), "application/pdf"),
                                                      "make_quiz": "on"})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        book = Book.objects.get(title="PDF")
        self.assertTrue(all(l.status == Lesson.DRAFT for l in book.lessons.all()))
        self.assertTrue(book.images.filter(kind="book").exists())

    def test_diagram_kinds(self):
        flow = diagrams.make_spec("P", "First the leaf absorbs light. Then roots take water. Next the plant makes sugar. Finally it releases oxygen.")
        self.assertEqual(flow["kind"], "flow")
        cyc = diagrams.make_spec("W", "The water cycle repeats again and again. Water evaporates from the seas. Vapour condenses into clouds. Rain falls on the land.")
        self.assertEqual(cyc["kind"], "cycle")
        self.assertIsNone(diagrams.validate_spec({"kind": "x", "nodes": []}))
        self.assertIn("Flow diagram", diagrams.describe(flow))

    def test_scene_picture_upload_and_delete(self):
        _, lessons = self.book()
        l = lessons[0]
        sc = l.scenes.first()
        buf = io.BytesIO()
        Image.new("RGB", (200, 150), (10, 200, 10)).save(buf, "PNG")
        self.client.force_login(self.teacher)
        r = self.client.post(reverse("scene_picture", args=[l.pk]), {"action": "add", "scene": sc.pk, "caption": "Mine",
                                                                       "image": SimpleUploadedFile("a.png", buf.getvalue(), "image/png")})
        self.assertEqual(r.status_code, 302)
        up = sc.pictures.get(kind="upload")
        self.client.post(reverse("scene_picture", args=[l.pk]), {"action": "delete", "picture": up.pk})
        self.assertFalse(sc.pictures.filter(kind="upload").exists())
        self.assertTrue(sc.pictures.exists())            # a scene never ends up without a picture

    # ---- versions, curriculum, mappings
    def test_publish_snapshot_is_immutable(self):
        _, lessons = self.book()
        l = lessons[0]
        pipeline.publish_lesson(l, self.teacher)
        snap = LessonVersion.objects.get(lesson=l, version=l.version)
        self.assertEqual(snap.snapshot["title"], l.title)
        snap.snapshot = {}
        with self.assertRaises(ValueError):
            snap.save()
        pipeline.publish_lesson(l, self.teacher)           # republish same version: still one snapshot
        self.assertEqual(l.versions.count(), 1)
        self.client.force_login(self.student)
        r = self.client.get(reverse("api_manifest", args=[l.pk]) + f"?version={l.version}")
        self.assertEqual(r.json()["title"], l.title)

    def test_new_curriculum_version_flags_lessons(self):
        sci = Subject.objects.create(name="Science")
        cur = Curriculum.objects.create(name="Board", version="2026")
        out = Outcome.objects.create(curriculum=cur, subject=sci, code="S1", description="d")
        _, lessons = self.book()
        lessons[0].outcome = out
        lessons[0].save()
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse("curriculum_new_version"), {"curriculum": cur.pk, "version": "2027", "reason": "x"}).status_code, 403)
        self.client.force_login(self.reviewer)
        self.client.post(reverse("curriculum_new_version"), {"curriculum": cur.pk, "version": "2027", "reason": "Syllabus update"})
        lessons[0].refresh_from_db()
        self.assertTrue(lessons[0].needs_review)
        self.assertTrue(Outcome.objects.filter(curriculum__version="2027", code="S1").exists())
        self.assertEqual(cur.changes.count() + Curriculum.objects.get(version="2027").changes.count(), 1)
        pipeline.publish_lesson(lessons[0], self.teacher)          # publish clears nothing by itself; the workflow view blocks it:
        lessons[0].needs_review = True
        lessons[0].save()
        self.client.force_login(self.teacher)
        self.client.post(reverse("lesson_workflow", args=[lessons[0].pk]), {"action": "publish"})
        self.assertTrue(Lesson.objects.get(pk=lessons[0].pk).needs_review)
        self.client.post(reverse("lesson_adopt_version", args=[lessons[0].pk]), {"action": "adopt"})
        l = Lesson.objects.get(pk=lessons[0].pk)
        self.assertFalse(l.needs_review)
        self.assertEqual(l.outcome.curriculum.version, "2027")

    def test_mapping_needs_a_different_reviewer(self):
        sci = Subject.objects.create(name="Science")
        out = Outcome.objects.create(curriculum=Curriculum.objects.create(name="B", version="1"), subject=sci, code="X", description="d")
        _, lessons = self.book()
        l = lessons[0]
        self.client.force_login(self.teacher)
        self.client.post(reverse("mapping_action", args=[l.pk]), {"action": "propose", "outcome": out.pk, "note": "n"})
        m = CurriculumMapping.objects.get()
        self.client.post(reverse("mapping_action", args=[l.pk]), {"action": "approve", "mapping": m.pk})
        self.assertEqual(CurriculumMapping.objects.get().status, "proposed")          # teacher is not a reviewer
        self.client.force_login(self.reviewer)
        self.client.post(reverse("mapping_action", args=[l.pk]), {"action": "approve", "mapping": m.pk})
        self.assertEqual(CurriculumMapping.objects.get().status, "approved")

    @override_settings(EDUPILOT_REQUIRE_REVIEW=True)
    def test_creator_cannot_approve_own_lesson(self):
        self.teacher.groups.add(Group.objects.get(name="Reviewer"))
        _, lessons = self.book()
        l = lessons[0]
        l.status = Lesson.REVIEW
        l.save()
        self.client.force_login(self.teacher)
        self.client.post(reverse("lesson_workflow", args=[l.pk]), {"action": "approve"})
        self.assertEqual(Lesson.objects.get(pk=l.pk).status, Lesson.REVIEW)
        self.client.force_login(self.reviewer)
        self.client.post(reverse("lesson_workflow", args=[l.pk]), {"action": "approve"})
        self.assertEqual(Lesson.objects.get(pk=l.pk).status, Lesson.APPROVED)

    # ---- markets, pilot, reports, offline
    def test_market_weighted_score(self):
        m = MarketAssessment.objects.create(country="Pakistan", scores={"access": {"score": 5}, "adaptation": {"score": 3}})
        self.assertEqual(m.weighted_score, round((5 * 20 + 3 * 15) / 35, 2))
        self.assertIsNone(MarketAssessment.objects.create(country="UAE").weighted_score)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("markets")).status_code, 403)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse("markets")).status_code, 200)
        self.client.post(reverse("markets"), {"market": m.pk, "score_cycle": "4", "evidence_cycle": "interview", "conf_cycle": "high", "ready_0": "on"})
        m.refresh_from_db()
        self.assertEqual(m.scores["cycle"]["confidence"], "high")
        self.assertTrue(m.readiness["items"]["Applicable law checked"])

    def test_pilot_delivery_target_and_pdf(self):
        _, lessons = self.book()
        klass = SchoolClass.objects.create(name="7A", teacher=self.teacher)
        for fail in (False, False, True):
            ClassSession.objects.create(school_class=klass, lesson=lessons[0], scheduled_for="2026-11-01T09:00:00Z", status="ended", blocking_failure=fail)
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("pilot"))
        delivery = [m for m in r.context["metrics"] if m["name"] == "Technical delivery"][0]
        self.assertFalse(delivery["ok"])
        ContentIssue.objects.create(lesson=lessons[0], severity="critical", description="wrong")
        r = self.client.get(reverse("pilot"))
        self.assertFalse([m for m in r.context["metrics"] if m["name"] == "Content quality"][0]["ok"])
        pdf = self.client.get(reverse("report_pdf"))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(self.client.get(reverse("reports")).status_code, 200)

    def test_offline_pack_and_service_worker(self):
        _, lessons = self.book()
        self.client.force_login(self.student)
        pipeline.publish_lesson(lessons[0], self.teacher)
        pack = self.client.get(reverse("lesson_pack", args=[lessons[0].pk])).json()
        self.assertTrue(any(u.endswith("viewer.js") for u in pack["urls"]))
        self.assertTrue(any("/media/scenes/" in u for u in pack["urls"]))
        sw = self.client.get(reverse("service_worker"))
        self.assertEqual(sw["Service-Worker-Allowed"], "/")

    def test_passport_and_issue_flow(self):
        _, lessons = self.book()
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("lesson_passport", args=[lessons[0].pk]))
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("issue_action", args=[lessons[0].pk]), {"action": "report", "severity": "critical", "description": "label wrong"})
        i = ContentIssue.objects.get()
        self.client.post(reverse("issue_action", args=[lessons[0].pk]), {"action": "fix", "issue": i.pk})
        self.assertEqual(ContentIssue.objects.get().status, "fixed")

    def test_viewer_and_detail_pages_render(self):
        _, lessons = self.book(pdf=True)
        self.client.force_login(self.teacher)
        for name in ("lesson_detail", "viewer", "lesson_design", "lesson_edit"):
            self.assertEqual(self.client.get(reverse(name, args=[lessons[0].pk])).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("book_detail", args=[lessons[0].book_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("curriculum_home")).status_code, 200)
