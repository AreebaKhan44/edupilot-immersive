"""Lessons that were already published keep their quiz: give each one a published quiz Assignment."""
from django.db import migrations


def forwards(apps, schema_editor):
    Lesson = apps.get_model("immersive", "Lesson")
    Assignment = apps.get_model("immersive", "Assignment")
    for lesson in Lesson.objects.filter(status="published").select_related("book"):
        n = lesson.questions.count()
        if n and not Assignment.objects.filter(lesson=lesson, kind="quiz").exists():
            Assignment.objects.create(owner_id=lesson.book.owner_id, kind="quiz", lesson=lesson, title=f"Quiz: {lesson.title}",
                                      total_marks=n, description="Quiz generated from the lesson plan.", published=True)


class Migration(migrations.Migration):
    dependencies = [("immersive", "0002_assignments_submissions")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
