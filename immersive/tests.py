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
        self.assertEqual(r.status_code, 302)                     # redirected to the "submitted" page
        a = QuizAttempt.objects.get(); self.assertEqual(a.score, a.total)
        self.assertIsNone(a.marks)                                # final marks come from the teacher

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
        self.assertIsNone(ctx["avg_pct"])                          # not marked yet -> no average
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("attempt_grade", args=[att.pk]), {"marks": 1, "feedback": "ok"})
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("dashboard")).context["avg_pct"], att.percent)
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

    # ---------------------------------------------------------------- one submission, teacher marks, retry
    def published_lesson(self):
        self.teacher_creates_book()
        return Lesson.objects.first()

    def submit_quiz(self, lesson, correct=True):
        data = {f"q{q.pk}": (q.answer_index if correct else (q.answer_index + 1) % len(q.options)) for q in lesson.questions.all()}
        return self.client.post(reverse("quiz", args=[lesson.pk]), data)

    def test_quiz_can_be_submitted_only_once(self):
        lesson = self.published_lesson()
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.submit_quiz(lesson).status_code, 302)
        self.assertEqual(self.submit_quiz(lesson).status_code, 302)           # second try is bounced
        self.assertEqual(QuizAttempt.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("quiz", args=[lesson.pk])).status_code, 302)   # form is closed too
        ctx = self.client.get(reverse("dashboard")).context
        self.assertFalse(any(a.kind == "quiz" and a.lesson_id == lesson.pk for a in ctx["pending"]))
        self.assertContains(self.client.get(reverse("quiz_result", args=[lesson.pk])), "Quiz submitted")

    def test_teacher_sees_submission_gives_marks_student_sees_them(self):
        lesson = self.published_lesson()
        self.client.login(username="s", password="pw12345!x")
        self.submit_quiz(lesson, correct=False)
        att = QuizAttempt.objects.get()
        self.client.login(username="t", password="pw12345!x")
        ctx = self.client.get(reverse("dashboard")).context
        self.assertEqual(ctx["stats"]["to_grade"], 1)
        self.assertEqual(ctx["to_grade"][0]["who"], "s")
        page = self.client.get(reverse("work_detail", args=[att.assignment.pk]))
        self.assertContains(page, "waiting for your marks")
        self.client.post(reverse("attempt_grade", args=[att.pk]), {"marks": att.total + 5})      # out of range -> ignored
        att.refresh_from_db(); self.assertIsNone(att.marks)
        self.client.post(reverse("attempt_grade", args=[att.pk]), {"marks": 1, "feedback": "Revise chapter"})
        att.refresh_from_db(); self.assertEqual((att.marks, att.feedback), (1, "Revise chapter"))
        self.assertEqual(self.client.get(reverse("dashboard")).context["stats"]["to_grade"], 0)
        self.client.login(username="s", password="pw12345!x")
        ctx = self.client.get(reverse("dashboard")).context
        self.assertEqual(ctx["marks_rows"][0]["marks"], 1)
        self.assertContains(self.client.get(reverse("quiz_result", args=[lesson.pk])), "Revise chapter")
        self.assertContains(self.client.get(reverse("dashboard")), "1/")

    def test_retry_only_after_teacher_allows_it(self):
        lesson = self.published_lesson()
        self.client.login(username="s", password="pw12345!x")
        self.submit_quiz(lesson, correct=False)
        att = QuizAttempt.objects.get()
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("attempt_retry", args=[att.pk]))                                  # not graded yet -> refused
        att.refresh_from_db(); self.assertFalse(att.retry_allowed)
        self.client.post(reverse("attempt_grade", args=[att.pk]), {"marks": 0})
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.post(reverse("attempt_retry", args=[att.pk])).status_code, 403)   # students cannot allow it
        self.submit_quiz(lesson); self.assertEqual(QuizAttempt.objects.count(), 1)                 # still locked
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("attempt_retry", args=[att.pk]))
        self.client.login(username="s", password="pw12345!x")
        ctx = self.client.get(reverse("dashboard")).context
        self.assertTrue(any(a.kind == "quiz" and getattr(a, "retry", False) for a in ctx["pending"]))
        self.assertEqual(self.client.get(reverse("quiz", args=[lesson.pk])).status_code, 200)
        self.submit_quiz(lesson)                                                                    # the retry
        self.assertEqual(QuizAttempt.objects.count(), 2)
        self.submit_quiz(lesson)                                                                    # permission is used up
        self.assertEqual(QuizAttempt.objects.count(), 2)
        att.refresh_from_db(); self.assertFalse(att.retry_allowed)

    def test_teacher_quiz_preview_is_not_saved(self):
        lesson = self.published_lesson()
        self.client.login(username="t", password="pw12345!x")
        self.assertEqual(self.submit_quiz(lesson).status_code, 200)
        self.assertEqual(QuizAttempt.objects.count(), 0)

    def test_assignment_only_once_unless_teacher_allows(self):
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("work_create", args=["assignment"]), {"title": "A", "description": "d", "total_marks": 10})
        a = Assignment.objects.get()
        self.client.login(username="s", password="pw12345!x")
        self.client.post(reverse("work_detail", args=[a.pk]), {"text": "first"})
        self.client.post(reverse("work_detail", args=[a.pk]), {"text": "second"})
        sub = Submission.objects.get(); self.assertEqual(sub.text, "first")
        self.assertIsNone(self.client.get(reverse("work_detail", args=[a.pk])).context["form"])
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("submission_retry", args=[sub.pk]))                                # not graded -> refused
        sub.refresh_from_db(); self.assertFalse(sub.retry_allowed)
        self.client.post(reverse("submission_grade", args=[sub.pk]), {"marks": 2})
        self.client.post(reverse("submission_retry", args=[sub.pk]))
        self.client.login(username="s", password="pw12345!x")
        self.client.post(reverse("work_detail", args=[a.pk]), {"text": "better"})
        sub.refresh_from_db()
        self.assertEqual((sub.text, sub.marks, sub.retry_allowed), ("better", None, False))
        self.client.post(reverse("work_detail", args=[a.pk]), {"text": "third"})
        sub.refresh_from_db(); self.assertEqual(sub.text, "better")

    # ---------------------------------------------------------------- lesson plan CRUD
    def test_lesson_delete_removes_everything(self):
        lesson = self.published_lesson(); pk = lesson.pk
        img_dir = f"{TMP}/scenes/lesson_{pk}"
        import os
        self.assertTrue(os.path.isdir(img_dir))
        self.client.login(username="s", password="pw12345!x")
        self.assertEqual(self.client.post(reverse("lesson_delete", args=[pk])).status_code, 403)
        self.assertTrue(Lesson.objects.filter(pk=pk).exists())
        other = User.objects.create_user("t2", password="pw12345!x"); other.groups.add(Group.objects.get(name="Teacher"))
        self.client.login(username="t2", password="pw12345!x")
        self.assertEqual(self.client.post(reverse("lesson_delete", args=[pk])).status_code, 403)   # not the owner
        self.client.login(username="t", password="pw12345!x")
        self.assertEqual(self.client.get(reverse("lesson_delete", args=[pk])).status_code, 405)    # GET never deletes
        r = self.client.post(reverse("lesson_delete", args=[pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Lesson.objects.filter(pk=pk).exists())
        self.assertFalse(Assignment.objects.filter(lesson_id=pk).exists())
        self.assertFalse(os.path.exists(img_dir))
        self.assertEqual(Lesson.objects.count(), 1)                    # the other lesson of the book is untouched

    def test_book_delete(self):
        self.teacher_creates_book()
        book = Book.objects.get()
        self.client.login(username="t", password="pw12345!x")
        self.client.post(reverse("book_delete", args=[book.pk]))
        self.assertEqual((Book.objects.count(), Lesson.objects.count()), (0, 0))

    def test_lesson_edit_update_add_and_delete_scene(self):
        lesson = self.published_lesson()
        self.client.login(username="t", password="pw12345!x")
        url = reverse("lesson_edit", args=[lesson.pk])
        n = lesson.scenes.count()

        def form_data(add=0, **over):
            d = {"title": "New title", "objective": "New objective", "add": "1" if add else "",
                 "form-TOTAL_FORMS": n + add, "form-INITIAL_FORMS": n, "form-MIN_NUM_FORMS": 0, "form-MAX_NUM_FORMS": 1000}
            for i, sc in enumerate(lesson.scenes.all()):
                d.update({f"form-{i}-id": sc.pk, f"form-{i}-title": sc.title, f"form-{i}-narration": sc.narration,
                          f"form-{i}-visual_type": "cluster", f"form-{i}-labels_text": "", f"form-{i}-key_points_text": ""})
            d.update(over)
            return d

        # 1) update
        self.client.post(url, form_data(**{"form-0-title": "Edited scene"}))
        lesson.refresh_from_db(); self.assertEqual(lesson.title, "New title"); self.assertEqual(lesson.status, "draft")
        self.assertEqual(lesson.scenes.first().title, "Edited scene")
        self.assertFalse(lesson.assignments.filter(published=True).exists())   # quiz hidden while the lesson is a draft
        # 2) add a scene
        self.assertContains(self.client.get(url + "?add=1"), "New scene")
        d = form_data(add=1); i = n
        d.update({f"form-{i}-title": "Brand new", f"form-{i}-narration": "Something new to say.", f"form-{i}-visual_type": "atom",
                  f"form-{i}-labels_text": "", f"form-{i}-key_points_text": "one"})
        self.client.post(url, d)
        self.assertEqual(lesson.scenes.count(), n + 1)
        self.assertEqual(lesson.scenes.last().title, "Brand new")
        # 3) delete a scene
        n = lesson.scenes.count()
        self.client.post(url, form_data(**{"form-0-DELETE": "on"}))
        self.assertEqual(lesson.scenes.count(), n - 1)
        self.assertEqual([s.order for s in lesson.scenes.all()], list(range(1, n)))
        # 4) cannot delete every scene
        n = lesson.scenes.count()
        d = form_data(); d.update({f"form-{k}-DELETE": "on" for k in range(n)})
        self.client.post(url, d)
        self.assertEqual(lesson.scenes.count(), n)

    # ---------------------------------------------------------------- voice
    def test_manifest_has_scene_audio_and_audio_endpoint(self):
        from unittest import mock
        lesson = self.published_lesson()
        self.client.login(username="s", password="pw12345!x")
        m = self.client.get(reverse("api_manifest", args=[lesson.pk])).json()
        self.assertEqual(m["scenes"][0]["audio"], reverse("scene_audio", args=[lesson.pk, 1]))

        def fake_synth(text, language, base):
            open(base + ".mp3", "wb").write(b"ID3" + b"0" * 2000)
            return base + ".mp3", "gtts"
        with mock.patch("immersive.services.media.synth", side_effect=fake_synth) as syn:
            r = self.client.get(m["scenes"][0]["audio"])
            self.assertEqual((r.status_code, r["Content-Type"]), (200, "audio/mpeg"))
            b"".join(r.streaming_content)
            self.client.get(m["scenes"][0]["audio"])
            self.assertEqual(syn.call_count, 1)                        # second request is served from the cache
        with mock.patch("immersive.services.media.synth", return_value=(None, "silent")):
            sc = lesson.scenes.get(order=2); sc.narration += " Changed text."; sc.save()
            self.assertEqual(self.client.get(reverse("scene_audio", args=[lesson.pk, 2])).status_code, 404)
        self.assertEqual(self.client.get(reverse("scene_audio", args=[lesson.pk, 99])).status_code, 404)

    def test_viewer_and_lesson_pages_have_voice_controls(self):
        lesson = self.published_lesson()
        self.client.login(username="s", password="pw12345!x")
        v = self.client.get(reverse("viewer", args=[lesson.pk]))
        for el in ('id="mic"', 'id="vsel"', 'id="vrate"', 'id="pause"', 'id="repeat"'):
            self.assertContains(v, el)
        self.assertContains(self.client.get(reverse("lesson_detail", args=[lesson.pk])), "Listen to this scene")

