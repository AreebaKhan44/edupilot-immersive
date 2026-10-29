import json
import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Assignment, Book, LearningEvent, Lesson, LessonVideo, QuizAttempt, Submission
from .services import media, pipeline
from .services.storyboard import heuristic_plan
from .services.textproc import split_chapters

TEXT = """Chapter 1: The Solar System
The solar system consists of the Sun and everything that orbits it. The Sun is a star at the center of the solar system. Eight planets orbit the Sun in nearly circular paths. Mercury is the closest planet to the Sun and has no atmosphere. Venus is the hottest planet because of its thick atmosphere. Earth is the only planet known to support life because it has liquid water. Mars is called the red planet because of iron oxide on its surface. Jupiter is the largest planet and has a great storm.

Chapter 2: The Plant Cell
The cell is the basic unit of life. The nucleus controls the activities of the cell and stores genetic material. Mitochondria produce energy for the cell through respiration. The cell membrane controls what enters and leaves the cell. Plant cells also have a cell wall and chloroplasts for photosynthesis.
"""

import unittest
unittest_skip_ffmpeg = unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')
TMP = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP)
class FlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.teacher = User.objects.create_user("t", password="pw12345!x")
        self.teacher.groups.add(Group.objects.create(name="Teacher"))
        self.student = User.objects.create_user("s", password="pw12345!x")
        self.admin = User.objects.create_user("a", password="pw12345!x", is_staff=True)

    def make_book(self):
        book = Book.objects.create(owner=self.teacher, title="Sci", raw_text=TEXT)
        return book, pipeline.create_lessons_from_book(book)

    def test_chapters_and_plan(self):
        ch = split_chapters(TEXT, "Sci")
        self.assertEqual(len(ch), 2)
        plan = heuristic_plan(*ch[0])
        self.assertEqual(plan["scenes"][0]["visual"]["type"], "solar")
        self.assertEqual(heuristic_plan(*ch[1])["scenes"][0]["visual"]["type"], "cell")
        self.assertTrue(plan["quiz"])

    def test_pipeline_creates_scenes_images_quiz(self):
        _, lessons = self.make_book()
        self.assertEqual(len(lessons), 2)
        sc = lessons[0].scenes.first()
        self.assertTrue(sc.image)
        self.assertTrue(lessons[0].questions.exists())
        m = lessons[0].manifest()
        self.assertEqual(m["supported_clients"], ["vr", "desktop", "tablet"])

    @override_settings(EDUPILOT_REQUIRE_REVIEW=True)
    def test_publish_workflow_and_visibility(self):
        _, lessons = self.make_book(); lesson = lessons[0]
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("lesson_detail", args=[lesson.pk])).status_code, 403)
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("lesson_workflow", args=[lesson.pk]), {"action": "submit"})
        lesson.refresh_from_db(); self.assertEqual(lesson.status, "review")
        self.assertEqual(self.client.post(reverse("lesson_workflow", args=[lesson.pk]), {"action": "approve"}).status_code, 403)
        self.client.login(username="a", password="pw12345!x")
        self.client.post(reverse("lesson_workflow", args=[lesson.pk]), {"action": "approve"})
        lesson.refresh_from_db(); self.assertEqual(lesson.status, "approved")
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("lesson_workflow", args=[lesson.pk]), {"action": "publish"})
        lesson.refresh_from_db(); self.assertTrue(lesson.is_published)
        self.client.login(username="s", password="pw12345!x")
        for name in ("lesson_detail", "viewer", "quiz"):
            self.assertEqual(self.client.get(reverse(name, args=[lesson.pk])).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("api_manifest", args=[lesson.pk])).json()["title"], lesson.title)

    def test_quiz_graded_on_server(self):
        _, lessons = self.make_book(); lesson = lessons[0]
        pipeline.publish_lesson(lesson, self.teacher)
        self.client.login(username="s", password="pw12345!x")
        data = {f"q{q.pk}": q.answer_index for q in lesson.questions.all()}
        r = self.client.post(reverse("quiz", args=[lesson.pk]), data)
        self.assertEqual(r.status_code, 200)
        a = QuizAttempt.objects.get(); self.assertEqual(a.score, a.total)

    def test_events_dedup(self):
        _, lessons = self.make_book(); lesson = lessons[0]; pipeline.publish_lesson(lesson, self.teacher)
        self.client.login(username="s", password="pw12345!x")
        ev = {"events": [{"event_id": "e1", "event_type": "vr.scene.viewed", "lesson_db_id": lesson.pk, "evidence": {"scene_id": "s1"}}]}
        for _ in range(2):
            r = self.client.post(reverse("api_events"), json.dumps(ev), content_type="application/json")
        self.assertEqual(r.json(), {"accepted": 0, "duplicates": 1})
        self.assertEqual(LearningEvent.objects.count(), 1)

    def test_student_cannot_create_book(self):
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("book_create")).status_code, 403)

    def test_book_form_end_to_end(self):
        self.client.login(username="t", password="pw12345!x")
        r = self.client.post(reverse("book_create"), {"title": "B", "language": "en", "raw_text": TEXT})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Lesson.objects.count(), 2)

    @unittest_skip_ffmpeg
    def test_video_render(self):
        _, lessons = self.make_book()
        v = pipeline.start_video_job(lessons[1], background=False); v.refresh_from_db()
        self.assertEqual(v.status, LessonVideo.DONE, v.log)
        self.assertGreater(media.ffprobe_duration(f"{TMP}/{v.file}"), 5)


    # ---------------------------------------------------------------- teacher -> student flow
    def teacher_creates_book(self, **extra):
        self.client.login(username="t", password="pw12345!x")
        data = {"title": "Sci", "language": "en", "raw_text": TEXT, "publish_now": "on", "make_quiz": "on"}
        data.update(extra)
        r = self.client.post(reverse("book_create"), data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        self.client.logout()

    def test_book_upload_reaches_student_dashboard(self):
        self.teacher_creates_book()
        self.assertEqual(Lesson.objects.filter(status="published").count(), 2)
        self.client.login(username="s", password="pw12345!x")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["lesson_rows"]), 2)
        self.assertContains(r, "3D")
        self.assertTrue(all(row["has_quiz"] for row in r.context["lesson_rows"]))
        self.assertEqual(r.context["n_lessons"], 2)

    def test_unpublished_lessons_hidden_until_teacher_publishes(self):
        self.teacher_creates_book(publish_now="")
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(len(self.client.get(reverse("dashboard")).context["lesson_rows"]), 0)
        lesson = Lesson.objects.first()
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("lesson_workflow", args=[lesson.pk]), {"action": "publish"})  # straight from draft
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(len(self.client.get(reverse("dashboard")).context["lesson_rows"]), 1)

    def test_quiz_hidden_until_teacher_gives_it(self):
        self.teacher_creates_book(make_quiz="")
        lesson = Lesson.objects.first()
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("quiz", args=[lesson.pk])).status_code, 403)
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("lesson_quiz", args=[lesson.pk]), {"action": "generate", "count": 3})
        self.client.post(reverse("lesson_quiz", args=[lesson.pk]), {"action": "assign"})
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("quiz", args=[lesson.pk])).status_code, 200)
        self.assertTrue(any(a.kind == "quiz" for a in self.client.get(reverse("dashboard")).context["pending"]))

    def test_quiz_attempt_shows_in_student_and_teacher_analytics(self):
        self.teacher_creates_book()
        lesson = Lesson.objects.first()
        self.client.login(username="s", password="pw12345!x")
        qs = list(lesson.questions.all())
        data = {f"q{q.pk}": q.answer_index for q in qs[:1]}   # answer only the first question correctly
        self.client.post(reverse("quiz", args=[lesson.pk]), data)
        att = QuizAttempt.objects.get()
        self.assertEqual((att.score, att.total), (1, len(qs)))
        self.assertIsNotNone(att.assignment)
        ctx = self.client.get(reverse("dashboard")).context
        self.assertEqual(ctx["n_attempts"], 1)
        self.assertEqual(ctx["avg_pct"], att.percent)
        self.assertEqual(self.client.get(reverse("progress")).status_code, 200)
        self.client.login(username="t", password="pw12345!x")
        rows = self.client.get(reverse("progress")).context["rows"]
        self.assertEqual((rows[0]["student"].username, rows[0]["attempts"]), ("s", 1))
        self.assertEqual(self.client.get(reverse("student_detail", args=[self.student.pk])).status_code, 200)

    def test_assignment_and_diary_flow(self):
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("work_create", args=["assignment"]), {"title": "Draw the Sun", "description": "Draw & label", "total_marks": 10})
        self.client.post(reverse("work_create", args=["diary"]), {"title": "Bring crayons", "description": "Tomorrow"})
        a = Assignment.objects.get(kind="assignment"); d = Assignment.objects.get(kind="diary")
        self.client.login(username="s", password="pw12345!x")
        titles = [x.title for x in self.client.get(reverse("dashboard")).context["pending"]]
        self.assertIn("Draw the Sun", titles); self.assertIn("Bring crayons", titles)
        self.client.post(reverse("work_detail", args=[a.pk]), {"text": "Done: sun is a star"})
        self.client.post(reverse("work_detail", args=[d.pk]))
        sub = Submission.objects.get(assignment=a)
        self.assertEqual(self.client.get(reverse("dashboard")).context["pending"], [])
        self.client.login(username="t", password="pw12345!x")
        self.assertContains(self.client.get(reverse("work_detail", args=[a.pk])), "sun is a star")
        self.client.post(reverse("submission_grade", args=[sub.pk]), {"marks": 8, "feedback": "Good"})
        self.client.post(reverse("submission_grade", args=[sub.pk]), {"marks": 99})   # out of range: ignored
        sub.refresh_from_db(); self.assertEqual(sub.marks, 8)
        self.client.login(username="s", password="pw12345!x")
        ctx = self.client.get(reverse("progress")).context
        self.assertEqual((ctx["n_submitted"], ctx["n_graded"], ctx["avg_assignment_pct"]), (1, 1, 80))
        self.assertEqual(self.client.get(reverse("work_list")).status_code, 200)

    def test_student_cannot_manage_work(self):
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("work_create", args=["assignment"]), {"title": "X", "description": "", "total_marks": 5})
        a = Assignment.objects.get()
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("work_create", args=["assignment"])).status_code, 403)
        self.assertEqual(self.client.post(reverse("work_manage", args=[a.pk]), {"action": "delete"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("book_bulk", args=[1]), {"action": "publish_all"}).status_code, 404)

    def test_hidden_work_not_visible(self):
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("work_create", args=["assignment"]), {"title": "X", "description": "", "total_marks": 5})
        a = Assignment.objects.get()
        self.client.post(reverse("work_manage", args=[a.pk]), {"action": "toggle"})
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("work_detail", args=[a.pk])).status_code, 404)

    def test_video_event_counts_as_watched(self):
        self.teacher_creates_book()
        lesson = Lesson.objects.first()
        self.client.login(username="s", password="pw12345!x")
        ev = {"events": [{"event_id": "v1", "event_type": "vr.video.played", "lesson_db_id": lesson.pk}]}
        self.client.post(reverse("api_events"), json.dumps(ev), content_type="application/json")
        self.assertEqual(self.client.get(reverse("dashboard")).context["videos_watched"], 1)

    @unittest_skip_ffmpeg
    def test_auto_video_for_all_lessons(self):
        _, lessons = self.make_book()
        pipeline.start_video_jobs(lessons, background=False)
        self.assertEqual(LessonVideo.objects.filter(status=LessonVideo.DONE).count(), 2)

    def test_real_book_layout_toc_and_page_numbers(self):
        book = "Teaching Guide\n\nContents\nUnit 1 Plants .......... 5\nUnit 2 Animals .......... 10\n\n"
        book += "5 1\nUNIT 1\nPlants\nTeaching objectives:\nTo describe the parts of a plant\n" + "A plant has roots, a stem and leaves that make food. " * 4 + "\n"
        book += "Unit 1: Plants\n7\n" + "Roots take water from the soil and hold the plant firmly. " * 3 + "\n"
        book += "10 2\nUNIT 2\nAnimals\n" + "An insect has six legs and three body parts called head thorax and abdomen. " * 4 + "\nUnit 2\n"
        ch = split_chapters(book, "Guide")
        self.assertEqual([t for t, _ in ch], ["Unit 1: Plants", "Unit 2: Animals"])
        self.assertIn("Roots take water", ch[0][1])      # repeated page header folded into the same topic
        self.assertNotIn("....", ch[0][1])
