import uuid
from django.conf import settings
from django.db import models
from django.urls import reverse

User = settings.AUTH_USER_MODEL

VISUAL_TYPES = [
    ("cluster", "Concept cluster"), ("solar", "Solar system"), ("cell", "Biological cell"),
    ("atom", "Atom / molecule"), ("circuit", "Electric circuit"), ("dna", "DNA helix"),
    ("geometry", "Geometry shapes"),
]


class Book(models.Model):
    LANGS = [("en", "English / Roman Urdu"), ("ur", "Urdu"), ("hi", "Hindi")]
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="books")
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=100, blank=True)
    grade = models.CharField(max_length=50, blank=True)
    language = models.CharField(max_length=5, choices=LANGS, default="en")
    raw_text = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("book_detail", args=[self.pk])


class Lesson(models.Model):
    DRAFT, REVIEW, APPROVED, PUBLISHED = "draft", "review", "approved", "published"
    STATUS = [(DRAFT, "Draft"), (REVIEW, "In review"), (APPROVED, "Approved"), (PUBLISHED, "Published")]
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="lessons")
    order = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200)
    objective = models.TextField(blank=True)
    source_text = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=DRAFT)
    version = models.PositiveIntegerField(default=1)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_lessons")
    generator = models.CharField(max_length=20, default="offline")  # offline | llm
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["book_id", "order"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("lesson_detail", args=[self.pk])

    @property
    def is_published(self):
        return self.status == self.PUBLISHED

    def manifest(self, request=None):
        """Lesson manifest, modelled on blueprint section 10."""
        scenes = []
        for s in self.scenes.all():
            scenes.append({
                "id": f"s{s.order}", "order": s.order, "title": s.title,
                "narration": s.narration, "key_points": s.key_points,
                "visual": s.visual, "image": s.image_url,
                "environment": s.visual.get("type", "cluster"),
                "interactions": [{"type": "label_target", "target": l} for l in s.visual.get("labels", [])],
            })
        return {
            "lesson_id": f"edupilot_{self.book_id}_{self.pk}", "db_id": self.pk, "version": self.version,
            "title": self.title, "board": self.book.subject or "custom", "grade": self.book.grade,
            "subject": self.book.subject, "objective": self.objective, "locale": self.book.language,
            "mode": "interactive_3d", "content_status": self.status, "generator": self.generator,
            "scenes": scenes, "supported_clients": ["vr", "desktop", "tablet"],
            "fallback_ref": "flat_video", "approved_by": self.approved_by.get_username() if self.approved_by else None,
        }


class Scene(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="scenes")
    order = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200)
    narration = models.TextField()
    key_points = models.JSONField(default=list, blank=True)
    visual = models.JSONField(default=dict, blank=True)   # {"type","color","labels"}
    image = models.CharField(max_length=300, blank=True)  # path relative to MEDIA_ROOT

    class Meta:
        ordering = ["lesson_id", "order"]

    def __str__(self):
        return f"{self.lesson_id}#{self.order} {self.title}"

    @property
    def image_url(self):
        return (settings.MEDIA_URL + self.image) if self.image else ""

    @property
    def visual_type(self):
        return self.visual.get("type", "cluster")


class Question(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    options = models.JSONField(default=list)
    answer_index = models.PositiveSmallIntegerField(default=0)
    explanation = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]


class LessonVideo(models.Model):
    PENDING, WORKING, DONE, FAILED = "pending", "working", "done", "failed"
    STATUS = [(PENDING, "Pending"), (WORKING, "Rendering"), (DONE, "Ready"), (FAILED, "Failed")]
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="videos")
    status = models.CharField(max_length=10, choices=STATUS, default=PENDING)
    file = models.CharField(max_length=300, blank=True)   # relative to MEDIA_ROOT
    voice = models.CharField(max_length=30, blank=True)   # gtts | espeak | silent
    log = models.TextField(blank=True)
    lesson_version = models.PositiveIntegerField(default=1)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    @property
    def url(self):
        return (settings.MEDIA_URL + self.file) if self.file else ""


class Assignment(models.Model):
    """Something a teacher gives to students: an assignment, a quiz (from a lesson) or a diary note."""
    ASSIGNMENT, QUIZ, DIARY = "assignment", "quiz", "diary"
    KINDS = [(ASSIGNMENT, "Assignment"), (QUIZ, "Quiz"), (DIARY, "Diary")]
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="given_work")
    kind = models.CharField(max_length=12, choices=KINDS, default=ASSIGNMENT)
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.CASCADE, related_name="assignments")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    total_marks = models.PositiveIntegerField(default=10)
    published = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title}"

    def get_absolute_url(self):
        return reverse("work_detail", args=[self.pk])

    @property
    def icon(self):
        return {"assignment": "📄", "quiz": "📝", "diary": "📔"}.get(self.kind, "📄")

    @property
    def is_overdue(self):
        from django.utils import timezone
        return bool(self.due_date and self.due_date < timezone.now())


class Submission(models.Model):
    """A student's answer to an assignment (text and/or file), or an 'I have seen it' mark for a diary note."""
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="submissions")
    text = models.TextField(blank=True)
    file = models.FileField(upload_to="submissions/%Y/%m/", blank=True)
    marks = models.PositiveIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="one_submission_per_student")]

    @property
    def is_graded(self):
        return self.marks is not None


class QuizAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attempts")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attempts")
    assignment = models.ForeignKey(Assignment, null=True, blank=True, on_delete=models.SET_NULL, related_name="attempts")
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    answers = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    @property
    def percent(self):
        return round(100 * self.score / self.total) if self.total else 0


class LearningEvent(models.Model):
    """Telemetry from the viewer (blueprint s.18): deduplicated by event_id."""
    event_id = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="events")
    lesson = models.ForeignKey(Lesson, null=True, on_delete=models.SET_NULL, related_name="events")
    event_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
