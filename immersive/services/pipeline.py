"""Glue: book text -> Lesson/Scene/Question rows + media."""
import io
import threading
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction

from ..models import Assignment, Lesson, LessonVideo, Question, Scene
from . import media
from .storyboard import build_plan, make_quiz
from .textproc import clean, split_chapters


def extract_pdf_text(uploaded_file):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(uploaded_file.read()))
    return "\n\n".join((p.extract_text() or "") for p in reader.pages)


def apply_plan(lesson, plan):
    lesson.title = plan.get("title") or lesson.title
    lesson.objective = plan.get("objective", "")
    lesson.generator = plan.get("generator", "offline")
    lesson.save()
    lesson.scenes.all().delete()
    lesson.questions.all().delete()
    for i, s in enumerate(plan["scenes"], 1):
        Scene.objects.create(lesson=lesson, order=i, title=s["title"], narration=s["narration"],
                             key_points=s.get("key_points", []), visual=s.get("visual", {}))
    for q in plan.get("quiz", []):
        Question.objects.create(lesson=lesson, text=q["text"], options=q["options"],
                                answer_index=q["answer_index"], explanation=q.get("explanation", ""))


def media_dir(lesson):
    d = Path(settings.MEDIA_ROOT) / "scenes" / f"lesson_{lesson.pk}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_images(lesson):
    scenes = list(lesson.scenes.all())
    d = media_dir(lesson)
    for sc in scenes:
        fname = f"scene_{sc.order}_v{lesson.version}.png"
        media.render_slide(sc, d / fname, sc.order, len(scenes), lesson.title, lesson.book.language)
        sc.image = f"scenes/lesson_{lesson.pk}/{fname}"
        sc.save(update_fields=["image"])


@transaction.atomic
def create_lessons_from_book(book):
    created = []
    for i, (title, body) in enumerate(split_chapters(clean(book.raw_text), book.title), 1):
        lesson = Lesson.objects.create(book=book, order=i, title=title, source_text=body)
        apply_plan(lesson, build_plan(title, body, book.language))
        created.append(lesson)
    for lesson in created:
        generate_images(lesson)
    return created


def regenerate(lesson):
    lesson.version += 1
    lesson.status = Lesson.DRAFT
    lesson.approved_by = None
    lesson.save()
    apply_plan(lesson, build_plan(lesson.title, lesson.source_text, lesson.book.language))
    generate_images(lesson)


def run_video_job(video_id):
    video = LessonVideo.objects.select_related("lesson__book").get(pk=video_id)
    lesson = video.lesson
    try:
        video.status = LessonVideo.WORKING
        video.save(update_fields=["status"])
        rel = f"videos/lesson_{lesson.pk}_v{lesson.version}_{video.pk}.mp4"
        out = Path(settings.MEDIA_ROOT) / rel
        voice = media.render_video(lesson, out, lesson.book.language)
        video.file, video.voice, video.status = rel, voice, LessonVideo.DONE
        video.log = "OK" + ("" if voice != "silent" else " (no TTS engine available – video is silent; install gTTS or espeak-ng)")
    except Exception as exc:  # noqa: BLE001
        video.status, video.log = LessonVideo.FAILED, str(exc)[:1500]
    video.save()


def start_video_job(lesson, background=True):
    video = LessonVideo.objects.create(lesson=lesson, lesson_version=lesson.version)
    if background:
        def worker():
            try:
                run_video_job(video.pk)
            finally:
                connection.close()
        threading.Thread(target=worker, daemon=True).start()
    else:
        run_video_job(video.pk)
    return video


# ---------------------------------------------------------------- teacher -> student publishing
def start_video_jobs(lessons, background=True):
    """Render videos for several lessons ONE AT A TIME (a 9-unit book must not start 9 ffmpeg processes at once)."""
    videos = []
    for lesson in lessons:
        if not lesson.videos.filter(status__in=[LessonVideo.PENDING, LessonVideo.WORKING]).exists():
            videos.append(LessonVideo.objects.create(lesson=lesson, lesson_version=lesson.version))
    if not videos:
        return []
    ids = [v.pk for v in videos]
    if background:
        def worker():
            try:
                for vid in ids:
                    run_video_job(vid)
            finally:
                connection.close()
        threading.Thread(target=worker, daemon=True).start()
    else:
        for vid in ids:
            run_video_job(vid)
    return videos


def assign_quiz(lesson, owner, due_date=None, title=""):
    """Make the lesson's quiz visible on student dashboards (one active quiz assignment per lesson)."""
    a = lesson.assignments.filter(kind=Assignment.QUIZ).first()
    if a:
        a.published = True
        if due_date is not None:
            a.due_date = due_date
        a.save()
        return a
    return Assignment.objects.create(owner=owner, kind=Assignment.QUIZ, lesson=lesson, due_date=due_date,
                                     title=title or f"Quiz: {lesson.title}", total_marks=lesson.questions.count(),
                                     description="Quiz generated from the lesson plan.")


def regenerate_quiz(lesson, count=5):
    lesson.questions.all().delete()
    for q in make_quiz(lesson.source_text, max_q=count):
        Question.objects.create(lesson=lesson, text=q["text"], options=q["options"],
                                answer_index=q["answer_index"], explanation=q.get("explanation", ""))
    a = lesson.assignments.filter(kind=Assignment.QUIZ).first()
    if a:
        a.total_marks = lesson.questions.count()
        a.save(update_fields=["total_marks"])
    return lesson.questions.count()


def publish_lesson(lesson, owner, with_quiz=True):
    lesson.status = Lesson.PUBLISHED
    lesson.save(update_fields=["status", "updated"])
    if with_quiz and lesson.questions.exists():
        assign_quiz(lesson, owner)


def unpublish_lesson(lesson):
    lesson.status = Lesson.DRAFT
    lesson.approved_by = None
    lesson.save(update_fields=["status", "approved_by", "updated"])
    lesson.assignments.filter(kind=Assignment.QUIZ).update(published=False)
