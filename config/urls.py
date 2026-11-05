from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("immersive.urls")),
]
# Media (generated images/videos) is served by Django in development.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
