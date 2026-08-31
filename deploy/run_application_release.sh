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
#   freeze worker/race_live_worker/race_sync_v2_worker hostname+running state
#   -> stop beat
#   -> drain all celery workers (complete expected node snapshot required)
#   -> stop worker
#   -> stop optional workers only if they were running
#   -> stop web
#   -> release task (one all-phase run normally; control/target/control for rollback)
#   -> up web
#   -> bounded wait for web healthy
#   -> up worker/beat/nginx
#   -> restore optional workers only if they were running
#   -> ps
set -eu

ROOT_DIR="${UMANEWS_ROOT_DIR:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
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
RELEASE_HANDOFF_MODE="${RELEASE_HANDOFF_MODE:-release-b}"
case "$RELEASE_HANDOFF_MODE" in release-b) ;; *) echo "RELEASE_HANDOFF_MODE is invalid" >&2; exit 1 ;; esac
if [ -z "${RELEASE_B_PREFLIGHT_ARTIFACT_PATH:-}" ]; then echo "RELEASE_B_PREFLIGHT_ARTIFACT_PATH is required for the exact Release B handoff" >&2; exit 1; fi
if [ -z "${RELEASE_B_PREFLIGHT_ARTIFACT_SHA256:-}" ]; then echo "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 is required for the exact Release B handoff" >&2; exit 1; fi
if [ -z "${EXPECTED_CANDIDATE_COMMIT:-}" ]; then echo "EXPECTED_CANDIDATE_COMMIT is required for the exact Release B handoff" >&2; exit 1; fi
if [ -z "${EXPECTED_CANDIDATE_IMAGE_ID:-}" ]; then echo "EXPECTED_CANDIDATE_IMAGE_ID is required for the exact Release B handoff" >&2; exit 1; fi
if [ -z "${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}" ]; then echo "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 is required for the exact Release B handoff" >&2; exit 1; fi
RELEASE_TASK_WRAPPER_PATH="${RELEASE_TASK_WRAPPER_PATH:-$ROOT_DIR/deploy/run_release_tasks.sh}"
case "$RELEASE_TASK_WRAPPER_PATH" in "$ROOT_DIR"/*) ;; *) echo "release task wrapper must stay under the repository root" >&2; exit 1 ;; esac
if [ ! -f "$RELEASE_TASK_WRAPPER_PATH" ] || [ -L "$RELEASE_TASK_WRAPPER_PATH" ]; then echo "release task wrapper is untrusted" >&2; exit 1; fi
if [ -n "${RELEASE_TARGET_IMAGE_TAG:-}" ]; then
  target_image_id="$(docker image inspect --format '{{.Id}}' "$RELEASE_TARGET_IMAGE_TAG")" || exit 1
  if [ "$target_image_id" != "$EXPECTED_CANDIDATE_IMAGE_ID" ]; then echo "preserved rollback target image ID mismatch" >&2; exit 1; fi
fi

# Only a new handoff artifact that actually carries the SHA-bound field enables
# recovery-attempt semantics. Legacy/non-Release-B retries may still provide
# the older handoff-shaped environment, and an inherited mode must not leak
# into them. The in-container verifier remains authoritative for the artifact.
artifact_attempt_mode=""
if [ "$RELEASE_HANDOFF_MODE" = "release-b" ] && [ -f "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ] && [ ! -L "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ]; then
  artifact_attempt_mode="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
fi
case "$artifact_attempt_mode" in
  required|not-required)
    if [ -n "${RESTRICTED_RECOVERY_ATTEMPT_MODE:-}" ] && [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" != "$artifact_attempt_mode" ]; then
      echo "RESTRICTED_RECOVERY_ATTEMPT_MODE does not match the exact handoff artifact" >&2
      exit 1
    fi
    RESTRICTED_RECOVERY_ATTEMPT_MODE="$artifact_attempt_mode"
    ;;
  "")
    RESTRICTED_RECOVERY_ATTEMPT_MODE="not-required"
    ;;
  *)
    echo "invalid recovery_intent_mode in exact handoff artifact" >&2
    exit 1
    ;;
esac
artifact_handoff_action="$(sed -n 's/.*"handoff_action":"\([^"]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
case "$artifact_handoff_action" in
  forward-resume)
    provenance_sha256="${RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256:-}"
    case "$provenance_sha256" in *[!0-9a-f]*) echo "forward-resume provenance artifact SHA is invalid" >&2; exit 1 ;; esac
    if [ "${#provenance_sha256}" -ne 64 ]; then echo "forward-resume provenance artifact SHA is invalid" >&2; exit 1; fi
    RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="$provenance_sha256"
    export RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
    ;;
  deploy|manual-release|rollback|initial-install)
    unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
    ;;
  *) echo "invalid handoff_action in exact handoff artifact" >&2; exit 1 ;;
esac
artifact_0077_binding_mode="$(sed -n 's/.*"release_0077_recovery_binding_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
case "$artifact_0077_binding_mode" in
  admission-only|bound|not-required) ;;
  "") artifact_0077_binding_mode="not-required" ;;
  *) echo "invalid 0077 recovery binding mode in exact handoff artifact" >&2; exit 1 ;;
esac

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

# A 0075 -> 0077 deploy is forward-only. Before stopping any service, bind the
# original admission handoff to one exact mode-0600 custom-format backup and a
# successful pg_restore --list result. The closed-state handoff itself is
# created later, only after every application service has stopped.
if [ "$artifact_0077_binding_mode" = "admission-only" ]; then
  if [ "$RELEASE_ACTION" != "deploy" ] || [ "$artifact_handoff_action" != "deploy" ]; then
    echo "0077 admission-only handoff is valid only for deploy" >&2
    exit 1
  fi
  verified_backup_path="${RELEASE_0077_VERIFIED_BACKUP_PATH:-}"
  verified_backup_sha256="${RELEASE_0077_VERIFIED_BACKUP_SHA256:-}"
  if [ -z "$verified_backup_path" ] || [ -z "$verified_backup_sha256" ]; then
    echo "0077 deploy requires RELEASE_0077_VERIFIED_BACKUP_PATH and RELEASE_0077_VERIFIED_BACKUP_SHA256 before any stop" >&2
    exit 1
  fi
  recovery_manifest_dir="$ROOT_DIR/runtime/migration_history_repair/release-0077-recovery"
  if [ -L "$recovery_manifest_dir" ]; then
    echo "0077 recovery manifest directory must not be a symlink" >&2
    exit 1
  fi
  umask 077
  mkdir -p "$recovery_manifest_dir"
  chmod 700 "$recovery_manifest_dir"
  RELEASE_0077_RECOVERY_MANIFEST_PATH="$recovery_manifest_dir/$EXPECTED_CANDIDATE_COMMIT.json"
  origin_handoff_sha256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"
  db_container_ids="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q db 2>/dev/null)"
  db_container_id="$(printf '%s\n' "$db_container_ids" | head -n 1 | tr -d '[:space:]')"
  if [ -z "$db_container_id" ] || [ "$(printf '%s\n' "$db_container_ids" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')" -ne 1 ]; then
    echo "0077 recovery manifest requires exactly one database container" >&2
    exit 1
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "$db_container_id" 2>/dev/null)" != "true" ]; then
    echo "0077 recovery manifest requires a running database container" >&2
    exit 1
  fi
  manifest_result="$(python3 "$ROOT_DIR/deploy/create_release_0077_recovery_manifest.py" \
    --output-path "$RELEASE_0077_RECOVERY_MANIFEST_PATH" \
    --candidate-commit "$EXPECTED_CANDIDATE_COMMIT" \
    --candidate-image-id "$EXPECTED_CANDIDATE_IMAGE_ID" \
    --database-identity-sha256 "$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" \
    --origin-handoff-sha256 "$origin_handoff_sha256" \
    --backup-path "$verified_backup_path" \
    --backup-sha256 "$verified_backup_sha256" \
    --pg-restore-container-id "$db_container_id" \
    --source-leaf stable.0075_race_data_source_priority_and_reported_position)"
  RELEASE_0077_RECOVERY_MANIFEST_SHA256="$(printf '%s' "$manifest_result" | sed -n 's/.*"manifest_sha256":"\([0-9a-f]*\)".*/\1/p')"
  RELEASE_0077_RECOVERY_ORIGIN_HANDOFF_SHA256="$origin_handoff_sha256"
  if [ "${#RELEASE_0077_RECOVERY_MANIFEST_SHA256}" -ne 64 ]; then
    echo "0077 recovery manifest generator returned an invalid SHA" >&2
    exit 1
  fi
  export RELEASE_0077_RECOVERY_MANIFEST_PATH RELEASE_0077_RECOVERY_MANIFEST_SHA256 RELEASE_0077_RECOVERY_ORIGIN_HANDOFF_SHA256
fi

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

RACE_DATA_SYNC_STATE_FILE="${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}.race-data-sync-state"
race_data_sync_intent=""
if [ -f "$RACE_DATA_SYNC_STATE_FILE" ] || [ -L "$RACE_DATA_SYNC_STATE_FILE" ]; then
  if ! validate_race_live_state_file "$RACE_DATA_SYNC_STATE_FILE" "$COMPOSE_FILE" "$RELEASE_ACTION"; then
    echo "frozen race_sync_v2_worker intent file failed trust validation; review it and delete it manually before retrying" >&2
    exit 1
  fi
  race_data_sync_intent="$(race_live_state_field "$RACE_DATA_SYNC_STATE_FILE" state)"
  echo "release: reusing frozen race_sync_v2_worker restore intent ($race_data_sync_intent) from a previous attempt"
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
    "$COMPOSE_FILE" "$RELEASE_ACTION"
fi

if [ -z "$race_data_sync_intent" ]; then
  race_data_sync_intent="$race_data_sync_current"
  write_race_live_state_file \
    "$RACE_DATA_SYNC_STATE_FILE" "$race_data_sync_intent" "$race_data_sync_node" \
    "$COMPOSE_FILE" "$RELEASE_ACTION"
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

if [ "$race_data_sync_current" = "running" ]; then
  echo "release: stopping race_sync_v2_worker (currently running)"
  "$COMPOSE" -f "$COMPOSE_FILE" stop race_sync_v2_worker
fi

echo "release: stopping web"
"$COMPOSE" -f "$COMPOSE_FILE" stop web

if [ "$artifact_0077_binding_mode" = "admission-only" ]; then
  echo "release: binding closed-state 0077 recovery handoff"
  closed_preflight_root="$ROOT_DIR/runtime/migration_history_repair/preflight"
  closed_preflight_dir="$(mktemp -d "$closed_preflight_root/closed.XXXXXXXX")"
  chmod 700 "$closed_preflight_dir"
  closed_preflight_path="$closed_preflight_dir/preflight.json"
  original_database_identity_sha256="$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256"
  RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$closed_preflight_path" \
    RELEASE_B_EXPECTED_MIGRATION_LEAF_SET=stable.0075_race_data_source_priority_and_reported_position \
    RELEASE_B_PREFLIGHT_ACTION=deploy \
    COMPOSE_FILE="$COMPOSE_FILE" \
    EXPECTED_CANDIDATE_COMMIT="$EXPECTED_CANDIDATE_COMMIT" \
    RELEASE_0077_RECOVERY_MANIFEST_PATH="$RELEASE_0077_RECOVERY_MANIFEST_PATH" \
    RELEASE_0077_RECOVERY_MANIFEST_SHA256="$RELEASE_0077_RECOVERY_MANIFEST_SHA256" \
    RELEASE_0077_RECOVERY_ORIGIN_HANDOFF_SHA256="$RELEASE_0077_RECOVERY_ORIGIN_HANDOFF_SHA256" \
    "$ROOT_DIR/deploy/run_historical_calendar_release_b_preflight.sh"
  RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$closed_preflight_path"
  RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$closed_preflight_path")"
  rebound_database_identity_sha256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$closed_preflight_path" | head -n 1)"
  rebound_binding_mode="$(sed -n 's/.*"release_0077_recovery_binding_mode":"\([a-z-]*\)".*/\1/p' "$closed_preflight_path" | head -n 1)"
  if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ] || \
     [ "$rebound_database_identity_sha256" != "$original_database_identity_sha256" ] || \
     [ "$rebound_binding_mode" != "bound" ]; then
    echo "closed-state 0077 recovery handoff binding failed" >&2
    exit 1
  fi
  EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$rebound_database_identity_sha256"
  export RELEASE_B_PREFLIGHT_ARTIFACT_PATH RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_PRODUCTION_DB_IDENTITY_SHA256
fi

echo "release: running the bounded release task phases"
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_TOKEN="$DEPLOYMENT_LOCK_TOKEN" \
  RELEASE_HANDOFF_MODE="$RELEASE_HANDOFF_MODE" \
  RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
  RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
  EXPECTED_CANDIDATE_COMMIT="$EXPECTED_CANDIDATE_COMMIT" \
  EXPECTED_CANDIDATE_IMAGE_ID="$EXPECTED_CANDIDATE_IMAGE_ID" \
  EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" \
  RESTRICTED_RECOVERY_ACTIVE="${RESTRICTED_RECOVERY_ACTIVE:-false}" \
  RESTRICTED_RECOVERY_ATTEMPT_MODE="$RESTRICTED_RECOVERY_ATTEMPT_MODE" \
  RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="${RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256:-}" \
  RELEASE_CONTROL_COMPOSE_OVERRIDE="${RELEASE_CONTROL_COMPOSE_OVERRIDE:-}" \
  RELEASE_TARGET_IMAGE_TAG="${RELEASE_TARGET_IMAGE_TAG:-}" \
  UMANEWS_ROOT_DIR="$ROOT_DIR" "$RELEASE_TASK_WRAPPER_PATH"

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

if [ "$race_data_sync_intent" = "running" ]; then
  echo "release: restoring race_sync_v2_worker (frozen restore intent)"
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps race_sync_v2_worker
fi

"$COMPOSE" -f "$COMPOSE_FILE" ps
rm -f "$RACE_LIVE_STATE_FILE"
rm -f "$RACE_DATA_SYNC_STATE_FILE"
echo "release: application release completed"
