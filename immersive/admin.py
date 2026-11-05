from django.contrib import admin
from . import models

class SceneInline(admin.TabularInline):
    model = models.Scene
    extra = 0

@admin.register(models.Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "book", "status", "version", "generator")
    list_filter = ("status", "generator")
    inlines = [SceneInline]

admin.site.register(models.Book)
admin.site.register(models.Question)
admin.site.register(models.LessonVideo)
admin.site.register(models.QuizAttempt)
admin.site.register(models.LearningEvent)

for m in (models.Curriculum, models.Subject, models.Outcome, models.SchoolClass, models.Enrolment, models.ClassSession,
          models.OutcomeProgress, models.SupportTask, models.GradeAudit, models.GuardianLink, models.Device,
          models.DeviceBooking, models.DeviceFault, models.AuditEvent, models.Assignment, models.Submission):
    if not admin.site.is_registered(m):
        admin.site.register(m)
