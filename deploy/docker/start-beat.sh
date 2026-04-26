#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py

exec celery -A app beat --loglevel="${CELERY_LOG_LEVEL:-INFO}"

