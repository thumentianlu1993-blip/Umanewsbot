#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="${COMPOSE_FILE:?COMPOSE_FILE is required}"
TIMEOUT_SECONDS="${CELERY_DRAIN_TIMEOUT_SECONDS:-900}"
deadline=$(($(date +%s) + TIMEOUT_SECONDS))

while :; do
  if "$COMPOSE" -f "$COMPOSE_FILE" exec -T web python manage.py shell -c '
from app.celery import app

inspect = app.control.inspect(timeout=5)
ping = inspect.ping() or {}
active = inspect.active() or {}
reserved = inspect.reserved() or {}
active_confirm = inspect.active() or {}
if not ping:
    raise SystemExit("no Celery worker responded to drain preflight")
workers = set(ping)
if set(active) != workers or set(reserved) != workers or set(active_confirm) != workers:
    raise SystemExit("Celery inspect returned an incomplete worker snapshot")
active_count = sum(len(tasks) for tasks in active.values())
reserved_count = sum(len(tasks) for tasks in reserved.values())
active_confirm_count = sum(len(tasks) for tasks in active_confirm.values())
print(
    f"celery drain active={active_count} reserved={reserved_count} "
    f"active_confirm={active_confirm_count} workers={len(workers)}"
)
raise SystemExit(0 if active_count == 0 and reserved_count == 0 and active_confirm_count == 0 else 1)
'; then
    exit 0
  fi
  [ "$(date +%s)" -lt "$deadline" ] || {
    echo "Celery worker did not drain within ${TIMEOUT_SECONDS}s; beat remains stopped" >&2
    exit 1
  }
  sleep 5
done
