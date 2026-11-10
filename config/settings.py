"""EduPilot Immersive - Django settings (development defaults)."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*" if DEBUG else "localhost").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "immersive",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "immersive.context.roles",
        "immersive.context.asset_version",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

# ---- PostgreSQL ------------------------------------------------------------
if os.environ.get("DB_ENGINE", "postgres") == "sqlite":   # DB_ENGINE=sqlite -> quick local/testing database
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
  DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME"),
        "USER": os.environ.get("DB_USER"),
        "PASSWORD": os.environ.get("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST"),
        "PORT": os.environ.get("DB_PORT"),
    }
  }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# ---- EduPilot Immersive settings ------------------------------------------
# If "1", a lesson must be approved by a reviewer before students see it (blueprint s.8/22).
# Default is "0": the teacher publishes directly, so what the teacher creates reaches students immediately.
EDUPILOT_REQUIRE_REVIEW = os.environ.get("EDUPILOT_REQUIRE_REVIEW", "0") == "1"
# A quiz result below this % is flagged "low" for the teacher, who can then allow the student one more attempt.
EDUPILOT_LOW_MARKS_PERCENT = int(os.environ.get("EDUPILOT_LOW_MARKS_PERCENT", "50"))
# Outcome counts as "Achieved" when the teacher-awarded marks reach this % (configurable per deployment, workflow s.8).
EDUPILOT_MASTERY_PERCENT = int(os.environ.get("EDUPILOT_MASTERY_PERCENT", "70"))
# If "1", a headset (AR/VR) lesson cannot be published without a screen-based alternative route (workflow s.1).
EDUPILOT_REQUIRE_ALT_ROUTE = os.environ.get("EDUPILOT_REQUIRE_ALT_ROUTE", "0") == "1"
EDUPILOT_MAX_SCENES = int(os.environ.get("EDUPILOT_MAX_SCENES", "6"))
# Optional: set ANTHROPIC_API_KEY to let an LLM draft storyboards (grounded in pasted text only).
EDUPILOT_LLM_MODEL = os.environ.get("EDUPILOT_LLM_MODEL", "claude-sonnet-5-5")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True