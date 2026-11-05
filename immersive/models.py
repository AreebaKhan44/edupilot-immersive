import uuid
from django.conf import settings
from django.db import models
from django.urls import reverse

User = settings.AUTH_USER_MODEL

LEARNING_MODES = [
    ("regular", "Regular digital learning"), ("interactive_2d", "Interactive 2D"), ("interactive_3d", "Interactive 3D"),
    ("ar", "Augmented reality (AR)"), ("vr", "Virtual reality (VR)"), ("virtual_lab", "Virtual laboratory"),
    ("scenario", "Scenario learning"), ("collaborative", "Collaborative learning"), ("physical", "Physical learning"),
]
HEADSET_MODES = ("ar", "vr")
LEVELS = [
    ("playgroup", "Playgroup / Pre-nursery"), ("nursery", "Nursery"), ("kg", "Kindergarten / Prep"),
    ("g1_2", "Grades 1-2"), ("g3_5", "Grades 3-5"), ("g6_8", "Grades 6-8"), ("g9_10", "Grades 9-10 / equivalent"),
    ("g11_12", "Grades 11-12 / equivalent"), ("foundation", "Foundation / Diploma"), ("undergrad", "Undergraduate"),
    ("postgrad", "Postgraduate"), ("vocational", "Vocational / Professional"),
]
SUBJECT_FAMILIES = [
    ("languages", "Languages and literacy"), ("maths", "Mathematics"), ("sciences", "Natural sciences"),
    ("computing", "Computing and technology"), ("humanities", "Humanities and social sciences"),
    ("religious", "Religious and ethical education"), ("commerce", "Commerce and business"), ("arts", "Arts and design"),
    ("health_pe", "Health and physical education"), ("life_skills", "Home economics and life skills"),
    ("engineering", "Engineering and architecture"), ("health_sci", "Health sciences"),
    ("agri", "Agriculture and veterinary"), ("law", "Law and public administration"),
    ("hospitality", "Hospitality and tourism"), ("vocational", "Technical and vocational"),
    ("professional", "Specialist professional"), ("research", "Research and interdisciplinary"),
]

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
    # --- lesson builder / content metadata (workflow doc s.6-7) ---
    outcome = models.ForeignKey("Outcome", null=True, blank=True, on_delete=models.SET_NULL, related_name="lessons")
    mode = models.CharField(max_length=20, choices=LEARNING_MODES, default="interactive_3d", db_default="interactive_3d")
    duration_minutes = models.PositiveIntegerField(default=40, db_default=40)
    success_criteria = models.TextField(blank=True, default="", db_default="")
    prerequisites = models.TextField(blank=True, default="", db_default="")
    alternative_route = models.TextField(blank=True, default="", db_default="",
                                         help_text="Screen-based or physical route to the same outcome, for learners without a headset.")
    device_requirements = models.CharField(max_length=200, blank=True, default="", db_default="")
    accessibility_features = models.CharField(max_length=200, blank=True, default="", db_default="",
                                              help_text="e.g. captions, narration audio, text equivalent, adjustable contrast")
    licence = models.CharField(max_length=100, blank=True, default="", db_default="")
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
                "visual": s.visual, "image": s.image_url, "audio": reverse("scene_audio", args=[self.pk, s.order]),
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
    feedback = models.TextField(blank=True, default="", db_default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    retry_allowed = models.BooleanField(default=False, db_default=False)   # teacher lets the student submit again (one more time)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="one_submission_per_student")]

    @property
    def is_graded(self):
        return self.marks is not None


class QuizAttempt(models.Model):
    """One submitted quiz. `score` is the automatic MCQ count (a suggestion for the teacher);
    `marks` is what the teacher finally awards and the only number the student sees."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attempts")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attempts")
    assignment = models.ForeignKey(Assignment, null=True, blank=True, on_delete=models.SET_NULL, related_name="attempts")
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    answers = models.JSONField(default=dict)
    marks = models.PositiveIntegerField(null=True, blank=True)       # awarded by the teacher
    feedback = models.TextField(blank=True, default="", db_default="")
    graded_at = models.DateTimeField(null=True, blank=True)
    retry_allowed = models.BooleanField(default=False, db_default=False)   # teacher lets the student attempt again
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    @property
    def percent(self):
        """Automatic score in % (what the MCQ checker counted)."""
        return round(100 * self.score / self.total) if self.total else 0

    @property
    def is_graded(self):
        return self.marks is not None

    @property
    def final_percent(self):
        """Teacher-awarded marks in % (None until graded)."""
        if self.marks is None:
            return None
        return round(100 * self.marks / self.total) if self.total else 0


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


# =====================================================================================
# Immersive LMS workflow (Immersive_LMS_Complete_Workflow.docx): curriculum -> classes ->
# sessions -> evidence -> reviewed result -> support/progression -> reports, plus lab operations.
# =====================================================================================

class Curriculum(models.Model):
    """Curriculum / board with a syllabus version (s.2). Old versions are kept, never overwritten."""
    name = models.CharField(max_length=150)
    country = models.CharField(max_length=80, blank=True)
    version = models.CharField(max_length=30, default="1.0")
    effective_from = models.DateField(null=True, blank=True)
    review_owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_curricula")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "-version"]
        constraints = [models.UniqueConstraint(fields=["name", "version"], name="one_curriculum_version")]
        verbose_name_plural = "curricula"

    def __str__(self):
        return f"{self.name} v{self.version}"


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    family = models.CharField(max_length=20, choices=SUBJECT_FAMILIES, default="sciences")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Outcome(models.Model):
    """A learning outcome: code + description + expected evidence (s.2 'Curriculum outcomes')."""
    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name="outcomes")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="outcomes")
    level = models.CharField(max_length=12, choices=LEVELS, default="g6_8")
    code = models.CharField(max_length=40)
    description = models.TextField()
    expected_evidence = models.CharField(max_length=300, blank=True)
    prerequisites = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="unlocks")

    class Meta:
        ordering = ["curriculum_id", "subject_id", "code"]
        constraints = [models.UniqueConstraint(fields=["curriculum", "code"], name="one_outcome_code_per_curriculum")]

    def __str__(self):
        return f"{self.code} - {self.description[:60]}"


class SchoolClass(models.Model):
    name = models.CharField(max_length=100)
    level = models.CharField(max_length=12, choices=LEVELS, default="g6_8")
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.SET_NULL, related_name="classes")
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="teaching_classes")
    academic_year = models.CharField(max_length=20, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "class"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("class_detail", args=[self.pk])


class Enrolment(models.Model):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="enrolments")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrolments")
    joined = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["school_class", "student"], name="one_enrolment_per_class")]


class ClassSession(models.Model):
    """A scheduled lesson delivery for a class (s.5 stages 8-10)."""
    SCHEDULED, LIVE, ENDED, CANCELLED = "scheduled", "live", "ended", "cancelled"
    STATUS = [(SCHEDULED, "Scheduled"), (LIVE, "Live"), (ENDED, "Ended"), (CANCELLED, "Cancelled")]
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="sessions")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="sessions")
    scheduled_for = models.DateTimeField()
    room = models.CharField(max_length=80, blank=True)
    mode = models.CharField(max_length=20, choices=LEARNING_MODES, default="interactive_3d")
    status = models.CharField(max_length=10, choices=STATUS, default=SCHEDULED)
    notes = models.TextField(blank=True)             # teacher observations recorded during delivery
    lesson_version = models.PositiveIntegerField(default=1)   # session stays linked to the version taught
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="created_sessions")

    class Meta:
        ordering = ["scheduled_for"]

    def __str__(self):
        return f"{self.school_class} - {self.lesson} @ {self.scheduled_for:%d %b %H:%M}"


class OutcomeProgress(models.Model):
    """Outcome progression (s.8): Not started > In progress > Evidence submitted > Developing/Achieved (> Reviewed).
    Built only from submitted evidence and teacher-reviewed marks - never from time spent or clicks."""
    NOT_STARTED, IN_PROGRESS, EVIDENCE, DEVELOPING, ACHIEVED = "not_started", "in_progress", "evidence", "developing", "achieved"
    STATUS = [(NOT_STARTED, "Not started"), (IN_PROGRESS, "In progress"), (EVIDENCE, "Evidence submitted"),
              (DEVELOPING, "Developing"), (ACHIEVED, "Achieved")]
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="outcome_progress")
    outcome = models.ForeignKey(Outcome, on_delete=models.CASCADE, related_name="progress")
    status = models.CharField(max_length=12, choices=STATUS, default=NOT_STARTED)
    reviewed = models.BooleanField(default=False)
    best_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "outcome"], name="one_progress_per_outcome")]


class SupportTask(models.Model):
    """Follow-up (s.5 stage 13): targeted support after gaps, or an extension after achievement. Teacher can edit/close."""
    SUPPORT, EXTENSION = "support", "extension"
    KINDS = [(SUPPORT, "Targeted support / reassessment"), (EXTENSION, "Extension task")]
    OPEN, DONE, DISMISSED = "open", "done", "dismissed"
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="support_tasks")
    outcome = models.ForeignKey(Outcome, null=True, blank=True, on_delete=models.CASCADE, related_name="support_tasks")
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name="support_tasks")
    kind = models.CharField(max_length=10, choices=KINDS, default=SUPPORT)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=10, default=OPEN)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    auto = models.BooleanField(default=False)          # suggested by the system, teacher may edit or reject
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class GradeAudit(models.Model):
    """Score override record (s.8): who changed which marks, from what to what, why, and when. The original is never lost."""
    ATTEMPT, SUBMISSION = "attempt", "submission"
    kind = models.CharField(max_length=12)
    ref_id = models.PositiveIntegerField()
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    old_marks = models.PositiveIntegerField(null=True, blank=True)
    new_marks = models.PositiveIntegerField()
    reason = models.CharField(max_length=300, blank=True)
    by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]


class GuardianLink(models.Model):
    """A guardian may only see the learners linked to them (s.10)."""
    guardian = models.ForeignKey(User, on_delete=models.CASCADE, related_name="guarded")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="guardians")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guardian", "student"], name="one_guardian_link")]


class Device(models.Model):
    AVAILABLE, ISSUED, MAINTENANCE, RETIRED = "available", "issued", "maintenance", "retired"
    STATUS = [(AVAILABLE, "Available"), (ISSUED, "Issued"), (MAINTENANCE, "In maintenance"), (RETIRED, "Retired")]
    code = models.CharField(max_length=40, unique=True)
    model = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100, blank=True)
    accessories = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=AVAILABLE)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.model})" if self.model else self.code


class DeviceBooking(models.Model):
    """Booking request > approval > issue > return and inspection (s.11)."""
    REQUESTED, APPROVED, ISSUED, RETURNED, REJECTED = "requested", "approved", "issued", "returned", "rejected"
    STATUS = [(REQUESTED, "Requested"), (APPROVED, "Approved"), (ISSUED, "Issued"), (RETURNED, "Returned"), (REJECTED, "Rejected")]
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name="bookings")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="bookings")
    status = models.CharField(max_length=10, choices=STATUS, default=REQUESTED)
    requested_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    return_note = models.CharField(max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
        constraints = [models.UniqueConstraint(fields=["session", "device"], name="one_booking_per_device_session")]


class DeviceFault(models.Model):
    OPEN, ASSIGNED, RESOLVED = "open", "assigned", "resolved"
    STATUS = [(OPEN, "Open"), (ASSIGNED, "Assigned"), (RESOLVED, "Resolved")]
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="faults")
    reported_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    description = models.TextField()
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_faults")
    status = models.CharField(max_length=10, choices=STATUS, default=OPEN)
    created = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]


class AuditEvent(models.Model):
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)
    detail = models.CharField(max_length=300, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
