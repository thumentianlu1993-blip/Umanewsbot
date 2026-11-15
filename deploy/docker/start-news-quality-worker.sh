#!/bin/sh
set -eu
cd /app/server
exec celery -A app worker --loglevel=info --queues=news_quality \
  --hostname='news-quality@%h' --concurrency=2 --prefetch-multiplier=1 \
  --max-tasks-per-child=100 --max-memory-per-child=262144
