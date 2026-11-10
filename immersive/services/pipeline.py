"""Glue: book text -> Lesson/Scene/Question rows + media."""
import hashlib
import io
import shutil
import threading
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction

from ..models import Assignment, Lesson, LessonVersion, LessonVideo, Question, Scene, SceneImage, Submission
from . import bookimages, diagrams, media
from .storyboard import build_plan, make_quiz
from .textproc import clean, split_chapters


def extract_pdf_text(uploaded_file):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(uploaded_file.read()))
    return "\n\n".join((p.extract_text() or "") for p in reader.pages)


DEFAULT_ACCESS = "narration audio, text captions, adjustable text size, reduced motion, keyboard controls, picture descriptions"
DEFAULT_LIMITS = ("Auto-generated pictures and 3D shapes are illustrative (not to scale). Check every label against the book "
                  "before teaching; a subject reviewer must approve scientific content.")


def apply_plan(lesson, plan):
    """Write a plan (scenes, quiz, lesson-plan phases) into the lesson. Pictures from the book / teacher survive a
    regeneration; pictures the system drew are redrawn for the new text."""
    lesson.title = plan.get("title") or lesson.title
    lesson.objective = plan.get("objective", "")
    lesson.generator = plan.get("generator", "offline")
    lp = plan.get("lesson_plan") or {}
    lesson.plan = lp
    for field, key in (("success_criteria", "success_criteria"), ("assessment_objectives", "assessment_objectives"),
                       ("rubric", "rubric"), ("alternative_route", "fallback")):
        if not (getattr(lesson, field) or "").strip() and lp.get(key):     # never overwrite what a teacher wrote
            setattr(lesson, field, lp[key])
    if not lesson.accessibility_features.strip():
        lesson.accessibility_features = DEFAULT_ACCESS
    if not lesson.limitations.strip():
        lesson.limitations = DEFAULT_LIMITS
    lesson.save()
    _drop_generated_pictures(lesson)
    lesson.pictures.update(scene=None)          # book / uploaded pictures are kept and re-attached below
    lesson.scenes.all().delete()
    lesson.questions.all().delete()
    for i, s in enumerate(plan["scenes"], 1):
        Scene.objects.create(lesson=lesson, order=i, title=s["title"], narration=s["narration"],
                             key_points=s.get("key_points", []), visual=s.get("visual", {}))
    for q in plan.get("quiz", []):
        Question.objects.create(lesson=lesson, text=q["text"], options=q["options"],
                                answer_index=q["answer_index"], explanation=q.get("explanation", ""))
    bookimages.reassign(lesson)


def _drop_generated_pictures(lesson):
    root = Path(settings.MEDIA_ROOT)
    for pic in lesson.pictures.filter(kind=SceneImage.GENERATED):
        try:
            (root / pic.file).unlink()
        except OSError:
            pass
    lesson.pictures.filter(kind=SceneImage.GENERATED).delete()


def media_dir(lesson):
    d = Path(settings.MEDIA_ROOT) / "scenes" / f"lesson_{lesson.pk}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_images(lesson):
    """Slide picture per scene (lesson page thumbnails + video frames). Uses the scene's book/generated picture."""
    scenes = list(lesson.scenes.prefetch_related("pictures"))
    d = media_dir(lesson)
    for sc in scenes:
        fname = f"scene_{sc.order}_v{lesson.version}.png"
        media.render_slide(sc, d / fname, sc.order, len(scenes), lesson.title, lesson.book.language,
                           picture=media.scene_picture_path(sc))
        sc.image = f"scenes/lesson_{lesson.pk}/{fname}"
        sc.save(update_fields=["image"])


def generate_scene_pictures(lesson):
    """Every scene that has no picture from the book gets one drawn from its own content, so the student always sees
    a picture that explains the scene (a built-in illustration for known subjects, otherwise a flow / cycle / concept map)."""
    d, lang, made = media_dir(lesson), lesson.book.language, 0
    for sc in lesson.scenes.prefetch_related("pictures"):
        if sc.pictures.exists():
            continue
        v = sc.visual or {}
        vtype = v.get("type", "cluster")
        fname = f"pic_{sc.order}_v{lesson.version}.png"
        if vtype in diagrams.BUILTIN_VISUALS:
            diagrams.render_builtin(vtype, v.get("color", "#5579ff"), v.get("labels", []), d / fname, lang)
            caption, alt = f"Illustration: {sc.title}", f"Illustration of the {vtype} model for: {sc.title}"
        else:
            spec = diagrams.validate_spec(v.get("diagram"), sc.title) or diagrams.make_spec(sc.title, sc.narration, sc.key_points, v.get("labels", []), lang)
            diagrams.render_diagram(spec, d / fname, lang, v.get("color", "#5579ff"))
            caption, alt = spec.get("title", sc.title), diagrams.describe(spec)
        SceneImage.objects.create(book=lesson.book, lesson=lesson, scene=sc, kind=SceneImage.GENERATED,
                                  file=f"scenes/lesson_{lesson.pk}/{fname}", caption=caption[:300], alt_text=alt[:300], order=1)
        made += 1
    return made


def refresh_pictures(lesson):
    """After a scene was edited: redraw the generated pictures (book/uploaded ones stay) and the slide pictures."""
    _drop_generated_pictures(lesson)
    generate_scene_pictures(lesson)
    generate_images(lesson)


def read_pdf_upload(uploaded_file):
    """Uploaded PDF -> (text, pages, images)."""
    pages, images = bookimages.read_pdf(uploaded_file.read())
    return "\n\n".join(pages), pages, images


@transaction.atomic
def create_lessons_from_book(book, pages=None, images=None):
    """Book -> lesson plans first (units, objective, scenes, plan phases, quiz), then the pictures:
       1) pictures found in the PDF are attached to the scene they belong to,
       2) every scene still without a picture gets one drawn from its content,
       3) slide pictures are rendered from them.
    `pages`/`images` come from read_pdf_upload(); for pasted text there are no book pictures."""
    created = []
    for i, (title, body) in enumerate(split_chapters(clean(book.raw_text), book.title), 1):
        lesson = Lesson.objects.create(book=book, order=i, title=title, source_text=body)
        apply_plan(lesson, build_plan(title, body, book.language))
        created.append(lesson)
    if images:
        bookimages.attach_images(book, pages or [], bookimages.save_images(book, images), created)
    for lesson in created:
        lesson.refresh_from_db()
        set_sources(lesson)
        generate_scene_pictures(lesson)
        generate_images(lesson)
    return created


def set_sources(lesson):
    """Content passport: where the lesson text and pictures come from."""
    pages = [sc.source_pages for sc in lesson.scenes.exclude(source_pages="")]
    nums = sorted({int(x) for p in pages for x in p.split("-") if x.isdigit()})
    where = f" (pages {nums[0]}-{nums[-1]})" if len(nums) > 1 else (f" (page {nums[0]})" if nums else "")
    n_book = lesson.pictures.filter(kind=SceneImage.BOOK).count()
    n_gen = lesson.pictures.filter(kind=SceneImage.GENERATED).count()
    lesson.sources = (f"Book: {lesson.book.title}{where}, uploaded by {lesson.book.owner.get_username()}. "
                      f"Pictures: {n_book} from the book, {n_gen} auto-generated from the lesson text.")
    lesson.save(update_fields=["sources"])


def regenerate(lesson):
    lesson.version += 1
    lesson.status = Lesson.DRAFT
    lesson.approved_by = None
    lesson.save()
    apply_plan(lesson, build_plan(lesson.title, lesson.source_text, lesson.book.language))
    lesson.refresh_from_db()
    set_sources(lesson)
    generate_scene_pictures(lesson)
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


def snapshot_lesson(lesson, user=None):
    """Immutable copy of the lesson as published (roadmap s.4). One snapshot per version, never overwritten."""
    snap, _ = LessonVersion.objects.get_or_create(
        lesson=lesson, version=lesson.version, defaults={"snapshot": lesson.manifest(), "published_by": user})
    return snap


def publish_lesson(lesson, owner, with_quiz=True):
    lesson.status = Lesson.PUBLISHED
    lesson.needs_review = False
    lesson.save(update_fields=["status", "needs_review", "updated"])
    snapshot_lesson(lesson, owner)
    if with_quiz and lesson.questions.exists():
        assign_quiz(lesson, owner)


def unpublish_lesson(lesson):
    lesson.status = Lesson.DRAFT
    lesson.approved_by = None
    lesson.save(update_fields=["status", "approved_by", "updated"])
    lesson.assignments.filter(kind=Assignment.QUIZ).update(published=False)


# ---------------------------------------------------------------- delete (lesson plan / book) + files
def _lesson_file_footprint(lesson):
    """Everything on disk that belongs to a lesson (pictures, videos, audio, students' uploads)."""
    root = Path(settings.MEDIA_ROOT)
    dirs = [root / "scenes" / f"lesson_{lesson.pk}", root / "audio" / f"lesson_{lesson.pk}"]
    files = [root / v.file for v in lesson.videos.all() if v.file]
    uploads = [root / str(sub.file) for sub in Submission.objects.filter(assignment__lesson=lesson).exclude(file="") if sub.file]
    return dirs, files + uploads


def _remove_footprint(dirs, files):
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    for f in files:
        try:
            f.unlink()
        except OSError:
            pass


def delete_lesson(lesson):
    """Delete a lesson plan with its scenes, quiz, assignments, student attempts/submissions, videos and media files."""
    dirs, files = _lesson_file_footprint(lesson)
    lesson.delete()
    _remove_footprint(dirs, files)


def delete_book(book):
    footprints = [_lesson_file_footprint(l) for l in book.lessons.all()]
    book_dir = Path(settings.MEDIA_ROOT) / "books" / f"book_{book.pk}"
    book.delete()
    for dirs, files in footprints:
        _remove_footprint(dirs, files)
    shutil.rmtree(book_dir, ignore_errors=True)


# ---------------------------------------------------------------- per-scene voice (server side, used when the browser has no voice)
def scene_audio_file(scene, language):
    """Return a cached narration audio file (mp3/wav) for a scene, generating it on first use; None if no TTS engine."""
    h = hashlib.sha1(f"{language}|{scene.narration}".encode("utf-8")).hexdigest()[:12]
    d = Path(settings.MEDIA_ROOT) / "audio" / f"lesson_{scene.lesson_id}"
    d.mkdir(parents=True, exist_ok=True)
    base = d / f"scene_{scene.pk}_{h}"
    for ext in (".mp3", ".wav"):
        if base.with_suffix(ext).exists():
            return base.with_suffix(ext)
    path, _engine = media.synth(scene.narration, language, str(base))
    if not path:
        return None
    for old in d.glob(f"scene_{scene.pk}_*"):          # drop audio of older narration texts
        if not old.name.startswith(base.name):
            old.unlink(missing_ok=True)
    return Path(path)
