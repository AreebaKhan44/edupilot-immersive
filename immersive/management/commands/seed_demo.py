"""python manage.py seed_demo  -> demo users + two sample books (published) so you can try everything at once."""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from immersive.models import Book, Lesson
from immersive.services import pipeline

SAMPLE = """Chapter 1: The Solar System
The solar system consists of the Sun and everything that orbits it. The Sun is a star at the center of the solar system and provides light and heat. Eight planets orbit the Sun in nearly circular paths called orbits. Mercury is the closest planet to the Sun and has almost no atmosphere. Venus is the hottest planet because its thick atmosphere traps heat. Earth is the only planet known to support life because it has liquid water. Mars is called the red planet because of iron oxide on its surface. Jupiter is the largest planet and has a giant storm called the Great Red Spot. Saturn is famous for its bright rings made of ice and rock.

Chapter 2: The Plant Cell
The cell is the basic unit of life. The nucleus controls the activities of the cell and stores genetic material. Mitochondria produce energy for the cell through respiration. The cell membrane controls what enters and leaves the cell. Ribosomes build proteins that the cell needs to grow. Plant cells also have a rigid cell wall and chloroplasts that capture sunlight for photosynthesis.

Chapter 3: Electric Circuits
An electric circuit is a closed path that allows electric current to flow. A battery provides the voltage that pushes the current through the circuit. A bulb converts electrical energy into light and heat. A resistor limits the current in a circuit. Ohm's law states that voltage equals current multiplied by resistance. In a closed circuit the bulb glows, but opening the switch breaks the path and the current stops.
"""


class Command(BaseCommand):
    help = "Create demo users (teacher/student/admin) and sample lessons"

    def handle(self, *args, **opts):
        for name in ("Teacher", "Student", "Reviewer"):
            Group.objects.get_or_create(name=name)
        admin, _ = User.objects.get_or_create(username="admin", defaults={"is_staff": True, "is_superuser": True})
        admin.set_password("admin12345"); admin.save()
        teacher, _ = User.objects.get_or_create(username="teacher")
        teacher.set_password("teacher12345"); teacher.save(); teacher.groups.add(Group.objects.get(name="Teacher"))
        student, _ = User.objects.get_or_create(username="student")
        student.set_password("student12345"); student.save(); student.groups.add(Group.objects.get(name="Student"))
        if not Book.objects.filter(title="Science Grade 7 (demo)").exists():
            book = Book.objects.create(owner=teacher, title="Science Grade 7 (demo)", subject="Science", grade="7", raw_text=SAMPLE)
            for lesson in pipeline.create_lessons_from_book(book):
                lesson.approved_by = admin
                lesson.save()
                pipeline.publish_lesson(lesson, teacher)   # published + quiz given to students
        self.stdout.write(self.style.SUCCESS(
            "Demo ready.\n  admin / admin12345 (reviewer)\n  teacher / teacher12345\n  student / student12345"))
