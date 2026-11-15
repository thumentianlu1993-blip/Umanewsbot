#!/bin/sh
set -eu
case "${1:-}" in
  control) queues=race_control ;;
  realtime) queues=race_realtime_retry,race_realtime ;;
  *) echo "expected control or realtime" >&2; exit 1 ;;
esac
cd /app/server
python /app/deploy/docker/wait_for_services.py
exec celery -A app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency=1 --prefetch-multiplier=1 --queues="$queues" \
  --max-tasks-per-child=50 --max-memory-per-child=262144 \
  --soft-time-limit=180 --time-limit=210 \
  --without-gossip --without-mingle
