#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py

exec celery -A app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_RACE_LIVE_WORKER_CONCURRENCY:-1}" \
  --queues="race_live" \
  --prefetch-multiplier=1 \
  --soft-time-limit="${CELERY_RACE_LIVE_WORKER_SOFT_TIME_LIMIT:-45}" \
  --time-limit="${CELERY_RACE_LIVE_WORKER_TIME_LIMIT:-60}" \
  --without-gossip \
  --without-mingle
