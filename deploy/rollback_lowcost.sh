#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/rollback_lowcost.sh <git-ref>"
  exit 1
fi

TARGET_REF="$1"

COMPOSE="./deploy/docker/compose-wrapper.sh"
git fetch --all --tags
git rev-parse --verify "$TARGET_REF^{commit}" >/dev/null
COMPOSE_FILE=docker-compose.prod.lowcost.yml ./deploy/historical_runner_preflight.sh
"$COMPOSE" -f docker-compose.prod.lowcost.yml stop beat
COMPOSE_FILE=docker-compose.prod.lowcost.yml ./deploy/wait_for_celery_drain.sh
"$COMPOSE" -f docker-compose.prod.lowcost.yml stop worker
git checkout "$TARGET_REF"
"$COMPOSE" -f docker-compose.prod.lowcost.yml build web
"$COMPOSE" -f docker-compose.prod.lowcost.yml up -d --no-deps web
"$COMPOSE" -f docker-compose.prod.lowcost.yml exec web python manage.py migrate --noinput
"$COMPOSE" -f docker-compose.prod.lowcost.yml up -d --no-deps worker beat nginx
