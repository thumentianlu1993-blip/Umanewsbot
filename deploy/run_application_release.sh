#!/bin/sh
# Shared application release orchestration for deploy and post-contract
# rollback. Callers must have already completed their own preconditions
# (.env, historical preflight, pull/build, or ref validation/checkout/build)
# and must hold the deployment lock.
#
# Environment:
#   COMPOSE_FILE            docker-compose.prod.yml or docker-compose.prod.lowcost.yml
#   DEPLOYMENT_LOCK_TOKEN   owner token of the held deployment lock
#
# Order (any failure stops all later steps):
#   freeze worker/race_live_worker hostname+running state
#   -> stop beat
#   -> drain all celery workers (complete expected node snapshot required)
#   -> stop worker
#   -> stop race_live_worker only if it was running
#   -> stop web
#   -> single one-shot release task
#   -> up web
#   -> bounded wait for web healthy
#   -> up worker/beat/nginx
#   -> restore race_live_worker only if it was running
#   -> ps
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

if [ -z "${DEPLOYMENT_LOCK_TOKEN:-}" ]; then
  echo "DEPLOYMENT_LOCK_TOKEN is required" >&2
  exit 1
fi

# The intent file records which entry froze it; deploy.sh passes
# RELEASE_ACTION=deploy, rollback.sh passes RELEASE_ACTION=rollback.
RELEASE_ACTION="${RELEASE_ACTION:-deploy}"
case "$RELEASE_ACTION" in
  deploy|rollback) ;;
  *)
    echo "RELEASE_ACTION must be deploy or rollback" >&2
    exit 1
    ;;
esac

. "$ROOT_DIR/deploy/race_live_state.sh"

# Verify the deployment lock before any Compose call.
./deploy/deployment_lock.sh verify

# The frozen race_live_worker state file persists the RESTORE INTENT across
# retries of the same release: a failed attempt keeps the file, a retry reads
# the intent from it, and only a fully successful release removes it. The
# file never decides stopping: every attempt still probes the CURRENT state
# to decide stops and drain membership, and a probe failure fails closed
# even when the file exists. A persisted intent is only trusted when it is a
# regular, non-symlink, user-owned mode-600 file bound to this compose file,
# this action and the current HEAD.
RACE_LIVE_STATE_FILE="${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}.race-live-state"
race_live_intent=""
if [ -f "$RACE_LIVE_STATE_FILE" ] || [ -L "$RACE_LIVE_STATE_FILE" ]; then
  if ! validate_race_live_state_file "$RACE_LIVE_STATE_FILE" "$COMPOSE_FILE" "$RELEASE_ACTION"; then
    echo "frozen race_live_worker intent file failed trust validation; review it and delete it manually before retrying" >&2
    exit 1
  fi
  race_live_intent="$(race_live_state_field "$RACE_LIVE_STATE_FILE" state)"
  echo "release: reusing frozen race_live_worker restore intent ($race_live_intent) from a previous attempt"
fi

# Freeze current container hostname and running state for this release.
# Prints "<running|not-running> <node>" or returns non-zero on probe failure
# (a failing `compose ps -q`, an inspect error, or invalid/empty output).
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

# Every attempt probes the CURRENT race_live_worker state for stopping and
# drain membership, regardless of any frozen restore intent.
race_live_probe="$(probe_service race_live_worker)" || {
  echo "failed to read race_live_worker container state; failing closed before any stop" >&2
  exit 1
}
race_live_current="$(printf '%s' "$race_live_probe" | awk '{print $1}')"
race_live_node="$(printf '%s' "$race_live_probe" | awk '{print $2}')"

if [ -z "$race_live_intent" ]; then
  race_live_intent="$race_live_current"
  write_race_live_state_file \
    "$RACE_LIVE_STATE_FILE" "$race_live_intent" "$race_live_node" \
    "$COMPOSE_FILE" "$RELEASE_ACTION"
fi

expected_workers=""
if [ "$worker_state" = "running" ]; then
  expected_workers="$worker_node"
fi
if [ "$race_live_current" = "running" ]; then
  expected_workers="${expected_workers:+$expected_workers }$race_live_node"
fi

echo "release: stopping beat"
"$COMPOSE" -f "$COMPOSE_FILE" stop beat

echo "release: waiting for all celery workers to drain"
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CELERY_WORKERS="$expected_workers" ./deploy/wait_for_celery_drain.sh

echo "release: stopping worker"
"$COMPOSE" -f "$COMPOSE_FILE" stop worker

if [ "$race_live_current" = "running" ]; then
  echo "release: stopping race_live_worker (currently running)"
  "$COMPOSE" -f "$COMPOSE_FILE" stop race_live_worker
fi

echo "release: stopping web"
"$COMPOSE" -f "$COMPOSE_FILE" stop web

echo "release: running the single one-shot release task"
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_TOKEN="$DEPLOYMENT_LOCK_TOKEN" ./deploy/run_release_tasks.sh

echo "release: starting web"
"$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps web

echo "release: waiting for web to become healthy"
COMPOSE_FILE="$COMPOSE_FILE" SERVICE_NAME=web ./deploy/wait_for_compose_service_healthy.sh

echo "release: starting worker, beat and nginx"
"$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps worker beat nginx

if [ "$race_live_intent" = "running" ]; then
  echo "release: restoring race_live_worker (frozen restore intent)"
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps race_live_worker
fi

"$COMPOSE" -f "$COMPOSE_FILE" ps
rm -f "$RACE_LIVE_STATE_FILE"
echo "release: application release completed"
