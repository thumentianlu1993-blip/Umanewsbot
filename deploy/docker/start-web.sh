#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py
python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py seed_admin \
    --username "${DJANGO_SUPERUSER_USERNAME}" \
    --password "${DJANGO_SUPERUSER_PASSWORD}" \
    --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}"
fi

exec gunicorn app.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --access-logfile - \
  --error-logfile -

