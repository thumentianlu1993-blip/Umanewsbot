#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.lowcost.yml}"
exec ./deploy/docker/compose-wrapper.sh -f "$COMPOSE_FILE" exec -T worker \
  python manage.py run_scheduled_race_result_review "$@"
