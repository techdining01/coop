"""
Production settings — used on Render.com and any other PaaS/VPS deploy.

Key differences from dev:
- DEBUG = False
- SECURE_SSL_REDIRECT = False  — Render terminates TLS at the edge; the app
  receives plain HTTP internally. Redirecting to HTTPS here causes an infinite
  redirect loop. Render's edge already enforces HTTPS for external traffic.
- SECURE_PROXY_SSL_HEADER set so Django knows the original request was HTTPS.
- HSTS, secure cookies, content-type sniffing protection all on.
"""

from .base import *  # noqa: F401, F403
from decouple import config

DEBUG = False

# Render terminates TLS at its edge proxy — never redirect to HTTPS from
# inside the app or you get an infinite loop.
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {module} {process:d} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
