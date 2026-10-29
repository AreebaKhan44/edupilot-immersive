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
    pdf = forms.FileField(required=False, label="…or upload a PDF", help_text="Text-based PDFs only (scanned PDFs need OCR).")
    raw_text = forms.CharField(required=False, label="Paste book content here",
                               widget=forms.Textarea(attrs={"rows": 14, "placeholder": "Chapter 1: The Solar System\nThe Sun is a star ..."}))

    publish_now = forms.BooleanField(required=False, initial=True, label="Publish lessons to students right away")
    make_quiz = forms.BooleanField(required=False, initial=True, label="Also publish the auto-generated quiz")
    make_video = forms.BooleanField(required=False, initial=True, label="Auto-generate narrated video for every lesson")

    class Meta:
        model = Book
        fields = ["title", "subject", "grade", "language", "raw_text"]

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
        if commit:
            inst.save()
        return inst


SceneFormSet = modelformset_factory(Scene, form=SceneForm, extra=0)


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
