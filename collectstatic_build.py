import os
import django
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Override DB to sqlite so collectstatic can run without a real Postgres
# connection at build time. collectstatic never touches the database.
from django.conf import settings as django_settings
django_settings.DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "/tmp/build.db",
    }
}

django.setup()

from django.core.management import call_command
call_command("collectstatic", "--noinput")
