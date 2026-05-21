from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """
    Lightweight .env loader to support local/dev setups.

    - Only sets values that aren't already present in os.environ.
    - Supports simple KEY=VALUE lines with optional quotes.
    """
    try:
        if not path.exists():
            return
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # Never fail settings import due to .env parsing issues.
        return


# Load `.env` located at the project root (same folder as manage.py).
_load_env_file(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("DJANGO_DEBUG", True)

_allowed_hosts_raw = os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
if _allowed_hosts_raw:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
else:
    # Keep this non-empty so `runserver` works even when DEBUG=False.
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]

# Company/branding (used across emails and UI)
ATS_COMPANY_NAME = os.environ.get("ATS_COMPANY_NAME", "Ultimatix ATS").strip() or "Ultimatix ATS"

# Optional external (Google) form link to include in onboarding document request emails.
# This is an informational/backup link only; documents uploaded via the portal are what get stored in ATS.
ONBOARDING_DOCUMENT_EXTERNAL_FORM_URL = os.environ.get(
    "ONBOARDING_DOCUMENT_EXTERNAL_FORM_URL",
    "https://forms.gle/U3J5hSrVxPxmxwnH8",
).strip()

# Google OAuth (used for Google Calendar / Meet integrations)
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_AUTH_URI = os.environ.get(
    "GOOGLE_OAUTH_AUTH_URI",
    "https://accounts.google.com/o/oauth2/auth",
).strip() or "https://accounts.google.com/o/oauth2/auth"
GOOGLE_OAUTH_TOKEN_URI = os.environ.get(
    "GOOGLE_OAUTH_TOKEN_URI",
    "https://oauth2.googleapis.com/token",
).strip() or "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_CERT_URL = os.environ.get(
    "GOOGLE_OAUTH_CERT_URL",
    "https://www.googleapis.com/oauth2/v1/certs",
).strip() or "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_OAUTH_REDIRECT_URIS_RAW = os.environ.get("GOOGLE_OAUTH_REDIRECT_URIS", "").strip()
GOOGLE_OAUTH_REDIRECT_URIS = [
    item.strip() for item in GOOGLE_OAUTH_REDIRECT_URIS_RAW.split(",") if item.strip()
]

# Gemini (Generative Language API)
# Note: This project uses separate keys for different features/areas when desired.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_ASSESSMENT_API_KEY = os.environ.get("GEMINI_ASSESSMENT_API_KEY", "").strip() or GEMINI_API_KEY
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"

# Ollama (Local LLM; e.g., llama3.1)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip() or "http://127.0.0.1:11434"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300") or "60")
OLLAMA_ENABLED = _env_bool("OLLAMA_ENABLED", True)
OLLAMA_ASSESSMENT_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_ASSESSMENT_TIMEOUT_SECONDS", str(OLLAMA_TIMEOUT_SECONDS)) or str(OLLAMA_TIMEOUT_SECONDS))

# Assessment AI question generation provider: "ollama" (local) or "gemini" (cloud).
ASSESSMENT_LLM_PROVIDER = (os.environ.get("ASSESSMENT_LLM_PROVIDER", "") or "").strip().lower()
if not ASSESSMENT_LLM_PROVIDER:
    ASSESSMENT_LLM_PROVIDER = "ollama" if OLLAMA_ENABLED else "gemini"


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "accounts",
    "app_settings",
    "applicant_tracking",
    "background_verification",
    "candidate_database",
    "candidate_management",
    "candidate_portal",
    "dashboard",
    "interview_evaluation",
    "interview_recording",
    "job_requisition",
    "onboarding",
    "proctoring",
    "recruitment_teams",
    "super_admin",
    "task_management",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "recruitment_tracking_system.demo_ui_middleware.DemoUiDataMiddleware",
    "recruitment_tracking_system.role_access_middleware.RoleAccessMiddleware",
]

ROOT_URLCONF = "recruitment_tracking_system.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "app_settings.context_processors.role_access_context",
            ],
        },
    },
]

WSGI_APPLICATION = "recruitment_tracking_system.wsgi.application"


# Database
_postgres_host = (os.environ.get("POSTGRES_HOST", "") or "").strip()
if _postgres_host:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "ats"),
            "USER": os.environ.get("POSTGRES_USER", "ats"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": _postgres_host,
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

_csrf_origins_raw = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
if _csrf_origins_raw:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins_raw.split(",") if o.strip()]


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
