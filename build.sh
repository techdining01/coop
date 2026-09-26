#!/usr/bin/env bash
set -e

echo "==> Running migrations..."
python manage.py migrate --noinput

echo "==> Admin User Creation..."
python manage.py create_superuser 

echo "==> Setting up roles..."
python manage.py setup_roles

echo "==> Starting gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:10000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
