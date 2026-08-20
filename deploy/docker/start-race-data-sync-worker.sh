#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py

exec celery -A app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_RACE_DATA_SYNC_WORKER_CONCURRENCY:-1}" \
  --queues="race_sync_v2" \
  --prefetch-multiplier=1 \
  --max-tasks-per-child="${CELERY_RACE_DATA_SYNC_WORKER_MAX_TASKS_PER_CHILD:-50}" \
  --max-memory-per-child="${CELERY_RACE_DATA_SYNC_WORKER_MAX_MEMORY_PER_CHILD:-262144}" \
  --soft-time-limit="${CELERY_RACE_DATA_SYNC_WORKER_SOFT_TIME_LIMIT:-180}" \
  --time-limit="${CELERY_RACE_DATA_SYNC_WORKER_TIME_LIMIT:-210}" \
  --without-gossip \
  --without-mingle
