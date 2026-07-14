#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found. Copy .env.example to .env and fill production values first."
  exit 1
fi

COMPOSE="./deploy/docker/compose-wrapper.sh"

if [ "${HISTORICAL_RUNNER_INITIAL_INSTALL:-false}" = "true" ]; then
  COMPOSE_FILE=docker-compose.prod.yml ./deploy/historical_runner_preflight.sh --initial-install
else
  COMPOSE_FILE=docker-compose.prod.yml ./deploy/historical_runner_preflight.sh
fi
"$COMPOSE" -f docker-compose.prod.yml pull nginx
"$COMPOSE" -f docker-compose.prod.yml build web
"$COMPOSE" -f docker-compose.prod.yml stop beat
COMPOSE_FILE=docker-compose.prod.yml ./deploy/wait_for_celery_drain.sh
"$COMPOSE" -f docker-compose.prod.yml stop worker
"$COMPOSE" -f docker-compose.prod.yml up -d --no-deps web
"$COMPOSE" -f docker-compose.prod.yml exec web python manage.py migrate --noinput
"$COMPOSE" -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
"$COMPOSE" -f docker-compose.prod.yml up -d --no-deps worker beat nginx
"$COMPOSE" -f docker-compose.prod.yml ps
