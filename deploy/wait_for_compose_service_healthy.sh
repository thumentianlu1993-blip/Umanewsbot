#!/bin/sh
# Bounded wait until the web service reports exactly "true healthy".
#
# Environment:
#   COMPOSE_FILE                    allowlisted production compose file
#   SERVICE_NAME                    only "web" is supported
#   SERVICE_HEALTH_TIMEOUT_SECONDS  default 300
#
# Only "true healthy" returns 0. "false *" or any "unhealthy" fails
# immediately. absent/starting/restarting/inspect errors retry every 2
# seconds until the timeout, which then fails non-zero. Logs contain only
# the service name, the first 12 characters of the container ID and the
# last observed state.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE="./deploy/docker/compose-wrapper.sh"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *)
    echo "COMPOSE_FILE must be docker-compose.prod.yml or docker-compose.prod.lowcost.yml" >&2
    exit 1
    ;;
esac

SERVICE_NAME="${SERVICE_NAME:-}"
if [ "$SERVICE_NAME" != "web" ]; then
  echo "only the web service is supported by this health wait" >&2
  exit 1
fi

TIMEOUT_SECONDS="${SERVICE_HEALTH_TIMEOUT_SECONDS:-300}"
deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
last_state="absent"

while :; do
  container_id="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q "$SERVICE_NAME" 2>/dev/null | head -n 1 | tr -d '[:space:]' || true)"
  state=""
  if [ -n "$container_id" ]; then
    state="$(docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || printf 'inspect-error')"
  fi
  case "$state" in
    "true healthy")
      echo "$SERVICE_NAME is healthy"
      exit 0
      ;;
    false\ *|*unhealthy*)
      short_id="$(printf '%s' "$container_id" | cut -c1-12)"
      echo "$SERVICE_NAME container $short_id failed health wait (state: $state)" >&2
      exit 1
      ;;
    inspect-error)
      last_state="inspect-error"
      ;;
    "")
      last_state="absent"
      ;;
    *)
      last_state="$state"
      ;;
  esac
  if [ "$(date +%s)" -ge "$deadline" ]; then
    short_id="$(printf '%s' "$container_id" | cut -c1-12)"
    echo "$SERVICE_NAME did not become healthy within ${TIMEOUT_SECONDS}s (container ${short_id:-none}, last state: $last_state)" >&2
    exit 1
  fi
  sleep 2
done
