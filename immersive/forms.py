from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from django.forms import modelformset_factory

from .models import Assignment, Book, Scene, Submission, VISUAL_TYPES


class SignupForm(UserCreationForm):
    role = forms.ChoiceField(choices=[("student", "Student"), ("teacher", "Teacher")], initial="student")

    class Meta:
        model = User
        fields = ("username", "first_name", "email")

    def save(self, commit=True):
        user = super().save(commit)
        group, _ = Group.objects.get_or_create(name="Teacher" if self.cleaned_data["role"] == "teacher" else "Student")
        user.groups.add(group)
        return user


class BookForm(forms.ModelForm):
    pdf = forms.FileField(required=False, label="…or upload a PDF", help_text="Text-based PDFs. Pictures inside the PDF are extracted and shown in the 3D lesson (scanned PDFs need OCR).")
    raw_text = forms.CharField(required=False, label="Paste book content here",
                               widget=forms.Textarea(attrs={"rows": 9, "placeholder": "Chapter 1: The Solar System\nThe Sun is a star ..."}))

    publish_now = forms.BooleanField(required=False, initial=False, label="Publish lessons to students right after the plan is generated")
    make_quiz = forms.BooleanField(required=False, initial=True, label="Also publish the auto-generated quiz")
    make_video = forms.BooleanField(required=False, initial=False, label="Render a narrated video for every lesson")

    class Meta:
        model = Book
        fields = ["title", "subject", "grade", "language", "raw_text"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["title"].widget.attrs["placeholder"] = "e.g. Science Grade 5"
        self.fields["subject"].widget.attrs["placeholder"] = "e.g. Solar System"
        self.fields["grade"].widget.attrs["placeholder"] = "e.g. Grade 5"
        self.fields["raw_text"].widget.attrs.update({"placeholder": "Paste text from your book here…\nExample: Chapter 1: The Solar System\nThe Sun is a star …", "id": "id_raw_text"})

    def clean(self):
        data = super().clean()
        if not (data.get("raw_text") or "").strip() and not data.get("pdf"):
            raise forms.ValidationError("Please paste some book text or upload a PDF.")
        if data.get("pdf") and not data["pdf"].name.lower().endswith(".pdf"):
            raise forms.ValidationError("Only .pdf files are supported.")
        return data


class SceneForm(forms.ModelForm):
    visual_type = forms.ChoiceField(choices=VISUAL_TYPES, label="3D visual")
    key_points_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Key points (one per line)")
    labels_text = forms.CharField(required=False, label="3D labels (comma separated)")

    class Meta:
        model = Scene
        fields = ["title", "narration"]
        widgets = {"narration": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        inst = self.instance
        self.fields["visual_type"].initial = "cluster"          # a brand-new (untouched) extra scene stays "unchanged" and is ignored
        if inst.pk:
            self.fields["visual_type"].initial = inst.visual.get("type", "cluster")
            self.fields["key_points_text"].initial = "\n".join(inst.key_points)
            self.fields["labels_text"].initial = ", ".join(inst.visual.get("labels", []))

    def save(self, commit=True):
        from .services.storyboard import PALETTE
        inst = super().save(commit=False)
        vt = self.cleaned_data["visual_type"]
        inst.visual = {"type": vt, "color": PALETTE.get(vt, "#5579ff"),
                       "labels": [x.strip() for x in self.cleaned_data["labels_text"].split(",") if x.strip()][:5]}
        inst.key_points = [l.strip() for l in self.cleaned_data["key_points_text"].splitlines() if l.strip()][:4]
        from .services.diagrams import make_spec
        inst.visual["diagram"] = make_spec(inst.title, inst.narration, inst.key_points, inst.visual["labels"])   # 3D concept diagram follows the edited text
        if commit:
            inst.save()
        return inst


def scene_formset(extra=0):
    """Scene editor formset: edit every scene, tick DELETE to remove one, extra=1 adds a blank scene."""
    return modelformset_factory(Scene, form=SceneForm, extra=extra, can_delete=True)


SceneFormSet = scene_formset(0)


class DateTimeLocal(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%dT%H:%M", **kw)


class AssignmentForm(forms.ModelForm):
    due_date = forms.DateTimeField(required=False, widget=DateTimeLocal(), input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"])

    class Meta:
        model = Assignment
        fields = ["title", "description", "lesson", "due_date", "total_marks"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *a, teacher=None, kind=Assignment.ASSIGNMENT, **kw):
        super().__init__(*a, **kw)
        self.kind = kind
        from .models import Lesson
        qs = Lesson.objects.select_related("book").order_by("book__title", "order")
        if teacher is not None and not teacher.is_staff:
            qs = qs.filter(book__owner=teacher)
        self.fields["lesson"].queryset = qs
        self.fields["lesson"].required = kind == Assignment.QUIZ
        self.fields["lesson"].label = "Lesson" + ("" if kind == Assignment.QUIZ else " (optional)")
        if kind == Assignment.DIARY:
            del self.fields["total_marks"], self.fields["due_date"]
        if kind == Assignment.QUIZ:
            del self.fields["total_marks"]
            self.fields["title"].required = False

    def clean(self):
        data = super().clean()
        if self.kind == Assignment.QUIZ and data.get("lesson") and not data["lesson"].questions.exists():
            self.add_error("lesson", "This lesson has no quiz questions yet. Generate the quiz on the lesson page first.")
        return data


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["text", "file"]
        labels = {"text": "Your answer", "file": "Attach a file (optional)"}
        widgets = {"text": forms.Textarea(attrs={"rows": 6})}

    def clean(self):
        data = super().clean()
        if not (data.get("text") or "").strip() and not data.get("file"):
            raise forms.ValidationError("Write an answer or attach a file.")
        return data


class GradeForm(forms.Form):
    marks = forms.IntegerField(min_value=0)
    feedback = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    reason = forms.CharField(required=False, max_length=300, label="Reason (needed only when changing marks already given)")


# ---- Immersive LMS workflow forms ---------------------------------------------------
from .models import ClassSession, Curriculum, Device, DeviceFault, Lesson, Outcome, SchoolClass, Subject  # noqa: E402


class LessonDesignForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ["outcome", "mode", "duration_minutes", "success_criteria", "prerequisites", "alternative_route",
                  "device_requirements", "accessibility_features", "licence",
                  "reading_level", "assessment_objectives", "rubric", "cultural_context", "sources", "limitations", "offline_capable"]
        widgets = {k: forms.Textarea(attrs={"rows": 3}) for k in ("success_criteria", "prerequisites", "alternative_route", "assessment_objectives",
                                                                  "rubric", "cultural_context", "sources", "limitations")}


def _placeholders(form, mapping):
    for name, text in mapping.items():
        if name in form.fields:
            form.fields[name].widget.attrs["placeholder"] = text


class CurriculumForm(forms.ModelForm):
    effective_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    class Meta:
        model = Curriculum
        fields = ["name", "country", "version", "effective_from"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _placeholders(self, {"name": "e.g. National Curriculum 2025", "country": "e.g. Pakistan", "version": "e.g. 1.0"})


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "family"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _placeholders(self, {"name": "e.g. Biology"})


class OutcomeForm(forms.ModelForm):
    class Meta:
        model = Outcome
        fields = ["curriculum", "subject", "level", "code", "description", "expected_evidence"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _placeholders(self, {"code": "e.g. SCI5.1", "expected_evidence": "e.g. Labelled diagram or short quiz",
                             "description": "e.g. Students will be able to identify the planets in the solar system and describe their key characteristics."})
        self.fields["curriculum"].empty_label = "Select curriculum"
        self.fields["subject"].empty_label = "Select subject"


class ClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ["name", "level", "subject", "academic_year"]


class EnrolForm(forms.Form):
    usernames = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "placeholder": "student1, student2 (usernames, comma or new line)"}),
                                label="Add students by username")


class SessionForm(forms.ModelForm):
    scheduled_for = forms.DateTimeField(widget=DateTimeLocal(), input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"])

    class Meta:
        model = ClassSession
        fields = ["lesson", "scheduled_for", "room", "mode"]

    def __init__(self, *a, teacher=None, **kw):
        super().__init__(*a, **kw)
        qs = Lesson.objects.filter(status=Lesson.PUBLISHED).select_related("book").order_by("book__title", "order")
        if teacher is not None and not teacher.is_staff:
            qs = qs.filter(book__owner=teacher)
        self.fields["lesson"].queryset = qs


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["code", "model", "location", "accessories"]


class FaultForm(forms.ModelForm):
    class Meta:
        model = DeviceFault
        fields = ["device", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


# ---------------------------------------------------------------- roadmap document forms
from .models import ContentIssue, CurriculumMapping, MarketAssessment, SceneImage  # noqa: E402


class ScenePictureForm(forms.Form):
    """Teacher adds a picture (or a GLB 3D model) to one scene."""
    scene = forms.IntegerField(widget=forms.HiddenInput)
    image = forms.ImageField(required=False)
    model = forms.FileField(required=False, label="3D model (.glb)")
    caption = forms.CharField(required=False, max_length=300)

    def clean_model(self):
        f = self.cleaned_data.get("model")
        if f and not f.name.lower().endswith(".glb"):
            raise forms.ValidationError("Only .glb files are supported.")
        if f and f.size > 15 * 1024 * 1024:
            raise forms.ValidationError("The model must be smaller than 15 MB.")
        return f

    def clean(self):
        data = super().clean()
        if not data.get("image") and not data.get("model"):
            raise forms.ValidationError("Choose a picture or a .glb model.")
        return data


class MappingForm(forms.ModelForm):
    class Meta:
        model = CurriculumMapping
        fields = ["outcome", "note"]


class IssueForm(forms.ModelForm):
    class Meta:
        model = ContentIssue
        fields = ["severity", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class NewCurriculumVersionForm(forms.Form):
    curriculum = forms.ModelChoiceField(queryset=Curriculum.objects.all(), label="Curriculum to update")
    version = forms.CharField(max_length=30, label="New version", widget=forms.TextInput(attrs={"placeholder": "e.g. 2027"}))
    effective_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Why did the curriculum change?"}))
