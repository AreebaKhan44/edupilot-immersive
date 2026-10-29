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
