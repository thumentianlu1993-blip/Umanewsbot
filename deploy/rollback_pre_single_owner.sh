#!/bin/sh
# Pre-contract rollback bridge: only for rolling back the FIRST release of
# the single-migration-owner change to a frozen pre-contract image.
#
# The old image predates the release contract, so this bridge keeps the new
# control-plane checkout (no git checkout), restores the frozen old image as
# the compose image tag, and starts exactly one old web whose own entrypoint
# is the single migration owner for that old image. It never runs the new
# one-shot release task and never calls the old rollback scripts.
#
# Usage:
#   COMPOSE_FILE=<allowlisted> ./deploy/rollback_pre_single_owner.sh <frozen-old-image-tag>
#
# Environment:
#   COMPOSE_FILE                 docker-compose.prod.yml or docker-compose.prod.lowcost.yml
#   SCHEMA_COMPATIBLE_WITH_TARGET  REQUIRED, explicitly "true" or "false";
#                                  "false" stops before the image switch when
#                                  the current schema is not compatible with
#                                  the frozen image; unset/empty/any other
#                                  value fails closed before any action; this
#                                  script never restores the database itself
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE="./deploy/docker/compose-wrapper.sh"

if [ "${1:-}" = "" ]; then
  echo "Usage: COMPOSE_FILE=<allowlisted> ./deploy/rollback_pre_single_owner.sh <frozen-old-image-tag>" >&2
  exit 1
fi
FROZEN_IMAGE_TAG="$1"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *)
    echo "COMPOSE_FILE must be docker-compose.prod.yml or docker-compose.prod.lowcost.yml" >&2
    exit 1
    ;;
esac

# Operator acknowledgement is secondary to the live catalog gate below; it
# can never declare a 0076/0077 database compatible with a pre-contract image.
case "${SCHEMA_COMPATIBLE_WITH_TARGET:-}" in
  true|false) ;;
  *)
    echo "SCHEMA_COMPATIBLE_WITH_TARGET must be set explicitly to true or false;" >&2
    echo "decide schema compatibility with the frozen image before running this bridge." >&2
    exit 1
    ;;
esac

DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN

if ! COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=pre-contract-rollback ./deploy/deployment_lock.sh acquire; then
  echo "pre-contract rollback: another deployment holds the lock; refusing to proceed" >&2
  exit 1
fi
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Verify the lock token before any Compose call.
./deploy/deployment_lock.sh verify

# This bridge is only valid at the exact ordinary legacy 0075 state.  The
# current control image, not the frozen target, reads the live recorder and
# PostgreSQL catalog.  In particular, irreversible 0077 and recoverable 0076
# are rejected before image inspection, service probes, stops, or retagging.
"$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps \
  web python manage.py check_historical_calendar_release_b_schema \
  --direction=forward \
  --expected-migration-leaf-set=stable.0075_race_data_source_priority_and_reported_position

# The frozen image must exist locally before any service is stopped.
if ! docker image inspect "$FROZEN_IMAGE_TAG" >/dev/null 2>&1; then
  echo "pre-contract rollback: frozen image not present locally: tag rejected before any stop" >&2
  exit 1
fi

# The frozen race_live_worker state file persists the RESTORE INTENT across
# retries; it never decides stopping. Every attempt still probes the CURRENT
# state for stops and drain membership, and a probe failure fails closed even
# when the file exists (same contract as the shared orchestration). A
# persisted intent is only trusted when it is a regular, non-symlink,
# user-owned mode-600 file bound to this compose file, the
# pre-contract-rollback action and the current HEAD.
. "$ROOT_DIR/deploy/race_live_state.sh"

RACE_LIVE_STATE_FILE="${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}.race-live-state"
race_live_intent=""
if [ -f "$RACE_LIVE_STATE_FILE" ] || [ -L "$RACE_LIVE_STATE_FILE" ]; then
  if ! validate_race_live_state_file "$RACE_LIVE_STATE_FILE" "$COMPOSE_FILE" "pre-contract-rollback"; then
    echo "frozen race_live_worker intent file failed trust validation; review it and delete it manually before retrying" >&2
    exit 1
  fi
  race_live_intent="$(race_live_state_field "$RACE_LIVE_STATE_FILE" state)"
  echo "pre-contract rollback: reusing frozen race_live_worker restore intent ($race_live_intent) from a previous attempt"
fi

RACE_DATA_SYNC_STATE_FILE="${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}.race-data-sync-state"
race_data_sync_intent=""
if [ -f "$RACE_DATA_SYNC_STATE_FILE" ] || [ -L "$RACE_DATA_SYNC_STATE_FILE" ]; then
  if ! validate_race_live_state_file "$RACE_DATA_SYNC_STATE_FILE" "$COMPOSE_FILE" "pre-contract-rollback"; then
    echo "frozen race_sync_v2_worker intent file failed trust validation; review it and delete it manually before retrying" >&2
    exit 1
  fi
  race_data_sync_intent="$(race_live_state_field "$RACE_DATA_SYNC_STATE_FILE" state)"
  echo "pre-contract rollback: reusing frozen race_sync_v2_worker stop intent ($race_data_sync_intent) from a previous attempt"
fi

# Freeze current container hostname and running state (same contract as the
# shared orchestration).
probe_service() {
  service="$1"
  ps_output="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null)" || return 1
  cid="$(printf '%s' "$ps_output" | head -n 1 | tr -d '[:space:]')"
  if [ -z "$cid" ]; then
    printf 'not-running -\n'
    return 0
  fi
  info="$(docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.Config.Hostname}}' "$cid" 2>/dev/null)" || return 1
  running="$(printf '%s' "$info" | awk '{print $1}')"
  node="$(printf '%s' "$info" | awk '{print $3}')"
  case "$running" in
    true|false) ;;
    *) return 1 ;;
  esac
  if [ -z "$node" ]; then
    node="$(printf '%s' "$cid" | cut -c1-12)"
  fi
  if [ "$running" = "true" ]; then
    printf 'running %s\n' "$node"
  else
    printf 'not-running -\n'
  fi
}

worker_probe="$(probe_service worker)" || {
  echo "failed to read worker container state; failing closed before any stop" >&2
  exit 1
}
worker_state="$(printf '%s' "$worker_probe" | awk '{print $1}')"
worker_node="$(printf '%s' "$worker_probe" | awk '{print $2}')"

race_live_probe="$(probe_service race_live_worker)" || {
  echo "failed to read race_live_worker container state; failing closed before any stop" >&2
  exit 1
}
race_live_current="$(printf '%s' "$race_live_probe" | awk '{print $1}')"
race_live_node="$(printf '%s' "$race_live_probe" | awk '{print $2}')"

race_data_sync_probe="$(probe_service race_sync_v2_worker)" || {
  echo "failed to read race_sync_v2_worker container state; failing closed before any stop" >&2
  exit 1
}
race_data_sync_current="$(printf '%s' "$race_data_sync_probe" | awk '{print $1}')"
race_data_sync_node="$(printf '%s' "$race_data_sync_probe" | awk '{print $2}')"

if [ -z "$race_live_intent" ]; then
  race_live_intent="$race_live_current"
  write_race_live_state_file \
    "$RACE_LIVE_STATE_FILE" "$race_live_intent" "$race_live_node" \
    "$COMPOSE_FILE" "pre-contract-rollback" "pre-switch"
fi

if [ -z "$race_data_sync_intent" ]; then
  race_data_sync_intent="$race_data_sync_current"
  write_race_live_state_file \
    "$RACE_DATA_SYNC_STATE_FILE" "$race_data_sync_intent" "$race_data_sync_node" \
    "$COMPOSE_FILE" "pre-contract-rollback" "pre-switch"
fi

expected_workers=""
if [ "$worker_state" = "running" ]; then
  expected_workers="$worker_node"
fi
if [ "$race_live_current" = "running" ]; then
  expected_workers="${expected_workers:+$expected_workers }$race_live_node"
fi
if [ "$race_data_sync_current" = "running" ]; then
  expected_workers="${expected_workers:+$expected_workers }$race_data_sync_node"
fi

echo "pre-contract rollback: stopping beat"
"$COMPOSE" -f "$COMPOSE_FILE" stop beat

echo "pre-contract rollback: waiting for all celery workers to drain"
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CELERY_WORKERS="$expected_workers" ./deploy/wait_for_celery_drain.sh

echo "pre-contract rollback: stopping worker"
"$COMPOSE" -f "$COMPOSE_FILE" stop worker

if [ "$race_live_current" = "running" ]; then
  echo "pre-contract rollback: stopping race_live_worker (currently running)"
  "$COMPOSE" -f "$COMPOSE_FILE" stop race_live_worker
fi

if [ "$race_data_sync_current" = "running" ]; then
  echo "pre-contract rollback: stopping race_sync_v2_worker (not present in the old image catalog)"
  "$COMPOSE" -f "$COMPOSE_FILE" stop race_sync_v2_worker
fi

echo "pre-contract rollback: stopping web"
"$COMPOSE" -f "$COMPOSE_FILE" stop web

if [ "$SCHEMA_COMPATIBLE_WITH_TARGET" = "false" ]; then
  echo "pre-contract rollback: current schema is not compatible with the frozen image;" >&2
  echo "stopping before the image switch. Restore a verified backup or apply an audited" >&2
  echo "reverse migration under separate authorization, then rerun this bridge." >&2
  exit 1
fi

echo "pre-contract rollback: restoring frozen image tag"
update_race_live_state_phase "$RACE_LIVE_STATE_FILE" "switching"
update_race_live_state_phase "$RACE_DATA_SYNC_STATE_FILE" "switching"
docker tag "$FROZEN_IMAGE_TAG" umanewsbot:prod
update_race_live_state_phase "$RACE_LIVE_STATE_FILE" "image-switched"
update_race_live_state_phase "$RACE_DATA_SYNC_STATE_FILE" "image-switched"

echo "pre-contract rollback: starting the single old web (its entrypoint owns migration for the old image)"
"$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps web

echo "pre-contract rollback: waiting for web to become healthy"
COMPOSE_FILE="$COMPOSE_FILE" SERVICE_NAME=web ./deploy/wait_for_compose_service_healthy.sh

echo "pre-contract rollback: starting worker, beat and nginx"
"$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps worker beat nginx

if [ "$race_live_intent" = "running" ]; then
  echo "pre-contract rollback: restoring race_live_worker (frozen restore intent)"
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps race_live_worker
fi

"$COMPOSE" -f "$COMPOSE_FILE" ps
rm -f "$RACE_LIVE_STATE_FILE"
rm -f "$RACE_DATA_SYNC_STATE_FILE"
echo "pre-contract rollback: completed"
