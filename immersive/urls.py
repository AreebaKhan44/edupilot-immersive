from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("signup/", views.signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("books/new/", views.book_create, name="book_create"),
    path("books/<int:pk>/", views.book_detail, name="book_detail"),
    path("lessons/<int:pk>/", views.lesson_detail, name="lesson_detail"),
    path("lessons/<int:pk>/edit/", views.lesson_edit, name="lesson_edit"),
    path("lessons/<int:pk>/regenerate/", views.lesson_regenerate, name="lesson_regenerate"),
    path("lessons/<int:pk>/workflow/", views.lesson_workflow, name="lesson_workflow"),
    path("lessons/<int:pk>/quiz-admin/", views.lesson_quiz, name="lesson_quiz"),
    path("books/<int:pk>/bulk/", views.book_bulk, name="book_bulk"),
    path("lessons/<int:pk>/video/", views.video_start, name="video_start"),
    path("lessons/<int:pk>/video/status/", views.video_status, name="video_status"),
    path("lessons/<int:pk>/viewer/", views.viewer, name="viewer"),
    path("lessons/<int:pk>/quiz/", views.quiz, name="quiz"),
    path("progress/", views.progress, name="progress"),
    path("students/<int:pk>/", views.student_detail, name="student_detail"),
    path("work/", views.work_list, name="work_list"),
    path("work/new/<str:kind>/", views.work_create, name="work_create"),
    path("work/<int:pk>/", views.work_detail, name="work_detail"),
    path("work/<int:pk>/manage/", views.work_manage, name="work_manage"),
    path("submissions/<int:pk>/grade/", views.submission_grade, name="submission_grade"),
    # API (naming follows blueprint section 17)
    path("v1/vr/catalog", views.api_catalog, name="api_catalog"),
    path("v1/vr/lessons/<int:pk>/manifest", views.api_manifest, name="api_manifest"),
    path("v1/vr/events/batch", views.api_events_batch, name="api_events"),
]
