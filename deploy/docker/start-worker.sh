#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py

exec celery -A app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_WORKER_CONCURRENCY:-2}" \
  --queues="${CELERY_WORKER_QUEUES:-celery}" \
  --prefetch-multiplier="${CELERY_WORKER_PREFETCH_MULTIPLIER:-1}" \
  --max-tasks-per-child="${CELERY_WORKER_MAX_TASKS_PER_CHILD:-20}" \
  --max-memory-per-child="${CELERY_WORKER_MAX_MEMORY_PER_CHILD:-262144}" \
  --without-gossip \
  --without-mingle
