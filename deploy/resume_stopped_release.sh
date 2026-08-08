#!/bin/sh
# Audited resume entry: recover services after a failed release left them
# stopped, WITHOUT re-running the one-shot release task. The audited order
# for a failed release is: fix the root cause -> manual_release.sh (re-run
# the one-shot) -> this script (recover services).
#
# It acquires the shared deployment lock (action=resume-release), refuses to
# proceed while any application service (web, worker, beat, race_live_worker)
# is running, restarting or unreadable, then starts web, waits for healthy,
# starts worker/beat/nginx, and restores race_live_worker only from a
# trustworthy frozen running intent. It never invokes the one-shot release
# task and never stops any service.
#
# Environment:
#   COMPOSE_FILE  docker-compose.prod.yml or docker-compose.prod.lowcost.yml
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

. "$ROOT_DIR/deploy/race_live_state.sh"

DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN

# Install the release trap only after a successful acquire; a contender that
# loses the race must never touch the winner's lock.
if ! COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=resume-release ./deploy/deployment_lock.sh acquire; then
  echo "resume: another deployment holds the lock; refusing to proceed" >&2
  exit 1
fi
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# A stopped-service recovery must never bypass an unfinished migration-history
# transition. Completed receipts do not use either canonical active path.
if ! ./deploy/check_restricted_recovery_marker.sh; then
  echo "resume: active migration repair requires the reviewed forward-resume entry" >&2
  exit 1
fi

# Fail closed if any application service is running, restarting, or its state
# cannot be read (same standard as manual_release.sh). No service may be
# started before this gate.
for service in web worker beat race_live_worker; do
  if ! ps_output="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null)"; then
    echo "resume: cannot list $service containers; failing closed" >&2
    exit 1
  fi
  cid="$(printf '%s' "$ps_output" | head -n 1 | tr -d '[:space:]')"
  if [ -z "$cid" ]; then
    continue
  fi
  state="$(docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.Status}}' "$cid" 2>/dev/null)" || {
    echo "resume: cannot read $service container state; failing closed" >&2
    exit 1
  }
  running="$(printf '%s' "$state" | awk '{print $1}')"
  health="$(printf '%s' "$state" | awk '{print $2}')"
  status="$(printf '%s' "$state" | awk '{print $3}')"
  case "$running" in
    true|false) ;;
    *)
      echo "resume: unreadable $service container state; failing closed" >&2
      exit 1
      ;;
  esac
  if [ "$running" = "true" ] || [ "$health" = "restarting" ] || [ "$status" = "restarting" ]; then
    echo "resume: $service is still running or restarting; use the audited deploy/rollback orchestration instead" >&2
    exit 1
  fi
done

# The frozen intent only decides race_live_worker recovery. An untrustworthy
# intent file must NOT fail the whole resume: warn and skip race-live
# recovery (safe direction) while core services still recover. A trusted
# intent file is consumed: it is deleted only after every recovery step and
# the final status check succeed, regardless of the frozen state.
RACE_LIVE_STATE_FILE="${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}.race-live-state"
race_live_intent=""
intent_file_trusted=false
if [ -f "$RACE_LIVE_STATE_FILE" ] || [ -L "$RACE_LIVE_STATE_FILE" ]; then
  if validate_race_live_state_file "$RACE_LIVE_STATE_FILE" "$COMPOSE_FILE" "deploy rollback pre-contract-rollback"; then
    race_live_intent="$(race_live_state_field "$RACE_LIVE_STATE_FILE" state)"
    intent_file_trusted=true
  else
    echo "resume: race-live intent file is not trustworthy; skipping race_live_worker recovery." >&2
    echo "resume: review the file and delete it manually before relying on it again." >&2
  fi
fi

echo "resume: starting web"
"$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps web

echo "resume: waiting for web to become healthy"
COMPOSE_FILE="$COMPOSE_FILE" SERVICE_NAME=web ./deploy/wait_for_compose_service_healthy.sh

echo "resume: starting worker, beat and nginx"
"$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps worker beat nginx

if [ "$race_live_intent" = "running" ]; then
  echo "resume: restoring race_live_worker from the frozen running intent"
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps race_live_worker
fi

"$COMPOSE" -f "$COMPOSE_FILE" ps

if [ "$intent_file_trusted" = "true" ]; then
  rm -f "$RACE_LIVE_STATE_FILE"
  echo "resume: consumed race-live intent file removed after full recovery"
fi
echo "resume: service recovery completed"
