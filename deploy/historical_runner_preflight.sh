#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
RUNNER_NAME="${HISTORICAL_RUNNER_CONTAINER_NAME:-umanews-historical-runner}"
SECRET_DIR="${HISTORICAL_RUNNER_SECRET_DIR:-/opt/umanewsbot/runtime/historical_runner_secrets}"

require_healthy_service() {
  service="$1"
  container_id="$($COMPOSE -f "$COMPOSE_FILE" ps -q "$service")"
  [ -n "$container_id" ] || {
    echo "required existing service is absent: $service; run explicit infrastructure bootstrap if appropriate" >&2
    exit 1
  }
  state="$(docker inspect "$container_id" --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')"
  [ "$state" = "true healthy" ] || {
    echo "required existing service is not healthy: $service state=$state" >&2
    exit 1
  }
}

for service in web redis; do
  require_healthy_service "$service"
done
if "$COMPOSE" -f "$COMPOSE_FILE" config --services | grep -qx db; then
  require_healthy_service db
fi

if [ "${1:-}" = "--initial-install" ]; then
  docker container inspect "$RUNNER_NAME" >/dev/null 2>&1 && { echo "historical-runner container trace exists" >&2; exit 1; }
  docker network inspect "${HISTORICAL_RUNNER_INTERNAL_NETWORK:-umanews-historical-runner-db}" >/dev/null 2>&1 && { echo "historical-runner network trace exists" >&2; exit 1; }
  docker network inspect "${HISTORICAL_RUNNER_EGRESS_NETWORK:-umanews-historical-runner-egress}" >/dev/null 2>&1 && { echo "historical-runner egress network trace exists" >&2; exit 1; }
  if [ -d "$SECRET_DIR" ] && [ -n "$(find "$SECRET_DIR" -type f -print -quit 2>/dev/null)" ]; then
    echo "historical_runner_secrets trace exists" >&2
    exit 1
  fi
  "$COMPOSE" -f "$COMPOSE_FILE" exec -T web python manage.py shell -c \
    "from django.db import connection; c=connection.cursor(); names=['stable_historicalbatchrun','stable_historicalbatchlock','stable_historicalbatchrunevent']; c.execute('SELECT to_regclass(name) FROM unnest(%s::text[]) name',[names]); assert all(row[0] is None for row in c.fetchall()), 'HistoricalBatchRun table trace already exists'; c.execute(\"SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='historical_runner_control')\"); assert not c.fetchone()[0], 'historical_runner_control role trace already exists'"
  echo "initial HistoricalBatchRun host-only preflight passed"
  exit 0
fi

deadline=$(($(date +%s) + ${HISTORICAL_RUNNER_PAUSE_TIMEOUT_SECONDS:-300}))
status="$($COMPOSE -f "$COMPOSE_FILE" exec -T web python manage.py manage_historical_batch_runner status --json)"
case "$status" in *'"state": "running"'*)
  "$COMPOSE" -f "$COMPOSE_FILE" exec -T web python manage.py manage_historical_batch_runner pause \
    --actor deployment-preflight --reason migration
esac
while :; do
  status="$($COMPOSE -f "$COMPOSE_FILE" exec -T web python manage.py manage_historical_batch_runner status --json)"
  case "$status" in
    *'"state": "idle"'*|*'"state": "planned"'*|*'"state": "paused"'*|*'"state": "completed"'*|*'"state": "failed"'*|*'"state": "blocked"'*) break ;;
  esac
  [ "$(date +%s)" -lt "$deadline" ] || { echo "historical runner did not reach a migration-safe state" >&2; exit 1; }
  sleep 5
done
case "$status" in *'"phase": "apply"'*'"state": "running"'*) echo "HistoricalBatchRun is still applying" >&2; exit 1 ;; esac
"$COMPOSE" -f "$COMPOSE_FILE" exec -T web python manage.py manage_historical_batch_runner preflight --json
echo "historical runner migration preflight passed"
