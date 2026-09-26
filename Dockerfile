FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/mediafiles /app/staticfiles /app/backups /app/exports

# Collect static files at build time.
# We override DATABASES to use a dummy sqlite backend so Django can start
# without a real Postgres connection — collectstatic never touches the DB.
# sqlite3 is part of Python's stdlib so no extra install is needed.
# Set DJANGO_SECRET_KEY and FIELD_ENCRYPTION_KEY as build args in Render:
#   Dashboard → <service> → Settings → Environment → Build environment variables
ARG DJANGO_SECRET_KEY
ARG FIELD_ENCRYPTION_KEY
ARG PAYVESSEL_API_KEY=""
ARG PAYVESSEL_API_SECRET=""
ARG PAYVESSEL_BUSINESS_ID=""
RUN DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY} \
    FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY} \
    PAYVESSEL_API_KEY=${PAYVESSEL_API_KEY} \
    PAYVESSEL_API_SECRET=${PAYVESSEL_API_SECRET} \
    PAYVESSEL_BUSINESS_ID=${PAYVESSEL_BUSINESS_ID} \
    DATABASE_URL="" \
    python -c "
    import django, os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
    from django.conf import settings
    settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': '/tmp/build.db'}}
    django.setup()
    from django.core.management import call_command
    call_command('collectstatic', '--noinput')
    "

EXPOSE 8000

# Render runs migrations via a pre-deploy command set in the dashboard
# (Settings → Deploy → Pre-deploy command):
#   python manage.py migrate --noinput && python manage.py setup_roles
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
