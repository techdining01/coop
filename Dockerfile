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

# Collect static files at build time using a standalone script.
# The script overrides DATABASES to sqlite so Django can start without
# a real Postgres connection — collectstatic never touches the DB.
# Set these as build arguments in Render:
#   Dashboard → service → Settings → Environment → Build environment variables
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
    python collectstatic_build.py

# Render always routes traffic to port 10000 internally.
EXPOSE 10000

# Render runs migrations via the Pre-Deploy Command in the dashboard:
#   python manage.py migrate --noinput && python manage.py setup_roles
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "120"]
