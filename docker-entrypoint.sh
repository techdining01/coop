#!/bin/bash
set -e

host="$1"
shift
cmd="$@"

until python -c "import psycopg2; psycopg2.connect(host='$host', user='$POSTGRES_USER', password='$POSTGRES_PASSWORD', dbname='$POSTGRES_DB')" 2>/dev/null; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - executing command"
python manage.py migrate --noinput
python manage.py create_superuser
exec $cmd
