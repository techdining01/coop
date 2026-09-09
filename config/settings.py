from pathlib import Path
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# Fernet key used by apps.core.fields.EncryptedCharField (BVN/NIN at rest)
FIELD_ENCRYPTION_KEY = config("FIELD_ENCRYPTION_KEY")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "whitenoise",
    # third-party
    "rest_framework",
    "django_htmx",
    "waffle",
    "django_celery_beat",
    # local apps
    "apps.accounts",
    "apps.ledger",
    "apps.core",
    "apps.transactions",
    "apps.payments",
    "apps.loans",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "waffle.middleware.WaffleMiddleware",
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST", default="db"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Weekly ledger PDF exports — deliberately NOT under MEDIA_ROOT.
# These are downloaded once by an admin and then deleted; they
# aren't general user-facing media and shouldn't be served by a generic
# media URL. docker-compose.yml mounts this as its own volume.
EXPORTS_ROOT = BASE_DIR / "exports"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery ---

# Use on localhost for dev, or in docker-compose.yml for production. 
CELERY_BROKER_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = config("REDIS_URL", default="redis://127.0.0.1:6379/0")

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# --- Security (tighten further in production via environment) ---
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG

# --- App-specific: minimum length reused by MemberProfile validation ---
BVN_LENGTH = 11
NIN_LENGTH = 11

# --- PayVessel  ---
# Use https://sandbox.payvessel.com until PayVessel's business verification
# is complete (registration docs, settlement bank account, KYC on business
# owners). Switch to https://api.payvessel.com only once that's approved.

PAYVESSEL_BASE_URL = config("PAYVESSEL_BASE_URL", default="https://sandbox.payvessel.com")
PAYVESSEL_API_KEY = config("PAYVESSEL_API_KEY", default="")
PAYVESSEL_API_SECRET = config("PAYVESSEL_API_SECRET", default="")
PAYVESSEL_BUSINESS_ID = config("PAYVESSEL_BUSINESS_ID", default="")

# --- django-waffle ---
# A switch not yet created in the DB (e.g. before an admin has visited
# Django admin's "Switches" section) defaults to ACTIVE, not inactive —
# matching the design's "When on (default), the checks above run and
# block ineligible applications automatically." Without this, waffle's
# own default (WAFFLE_SWITCH_DEFAULT=False) would mean eligibility
# enforcement is silently OFF until someone remembers to create the
# switch 
WAFFLE_SWITCH_DEFAULT = True
