#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py

exec celery -A app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_WORKER_CONCURRENCY:-2}" \
  --queues="${CELERY_WORKER_QUEUES:-celery}" \
  --without-gossip \
  --without-mingle
