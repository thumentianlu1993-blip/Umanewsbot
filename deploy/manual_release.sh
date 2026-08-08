#!/bin/sh
# Protected manual release entry for existing environments.
#
# After the removal of web-entrypoint migrations, `compose up web` no longer
# prepares the schema. Use this top-level command to run the single release
# task by hand. It acquires the same deployment lock, refuses to proceed
# while any application service (web, worker, beat, race_live_worker) is
# running, restarting or unreadable, and leaves all application services
# stopped afterwards. Service recovery must go through the audited
# deploy/rollback orchestration, never through this script.
#
# Environment:
#   COMPOSE_FILE  docker-compose.prod.yml or docker-compose.prod.lowcost.yml
set -eu
unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256

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

DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN

# Install the release trap only after a successful acquire; a contender that
# loses the race must never touch the winner's lock.
if ! COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=manual-release ./deploy/deployment_lock.sh acquire; then
  echo "manual release: another deployment holds the lock; refusing to proceed" >&2
  exit 1
fi
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

python3 ./deploy/ensure_migration_history_repair_runtime.py
./deploy/check_restricted_recovery_marker.sh

# Fail closed if any application service is running, restarting, or its
# state cannot be read. No Compose `run` may happen before this gate. A
# failing `compose ps -q` probe is a probe failure, never "not running".
for service in web worker beat race_live_worker; do
  if ! ps_output="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null)"; then
    echo "manual release: cannot list $service containers; failing closed" >&2
    exit 1
  fi
  cid="$(printf '%s' "$ps_output" | head -n 1 | tr -d '[:space:]')"
  if [ -z "$cid" ]; then
    continue
  fi
  state="$(docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.Status}}' "$cid" 2>/dev/null)" || {
    echo "manual release: cannot read $service container state; failing closed" >&2
    exit 1
  }
  running="$(printf '%s' "$state" | awk '{print $1}')"
  health="$(printf '%s' "$state" | awk '{print $2}')"
  status="$(printf '%s' "$state" | awk '{print $3}')"
  case "$running" in
    true|false) ;;
    *)
      echo "manual release: unreadable $service container state; failing closed" >&2
      exit 1
      ;;
  esac
  if [ "$running" = "true" ] || [ "$health" = "restarting" ] || [ "$status" = "restarting" ]; then
    echo "manual release: $service is still running or restarting; stop it via the audited orchestration first" >&2
    exit 1
  fi
done

EXPECTED_CANDIDATE_COMMIT="$(git rev-parse HEAD)"
EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
IMAGE_COMMIT="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' umanewsbot:prod)"
if [ "$IMAGE_COMMIT" != "$EXPECTED_CANDIDATE_COMMIT" ]; then echo "manual release image revision mismatch" >&2; exit 1; fi
REPAIR_RUNTIME_ROOT="$ROOT_DIR/runtime/migration_history_repair"
if [ -L "$REPAIR_RUNTIME_ROOT" ]; then echo "repair runtime root must not be a symlink" >&2; exit 1; fi
umask 077
mkdir -p "$REPAIR_RUNTIME_ROOT/preflight"
chmod 700 "$REPAIR_RUNTIME_ROOT/preflight"
RELEASE_B_PREFLIGHT_DIR="$(mktemp -d "$REPAIR_RUNTIME_ROOT/preflight/before.XXXXXXXX")"
RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_DIR/preflight.json"
export EXPECTED_CANDIDATE_COMMIT EXPECTED_CANDIDATE_IMAGE_ID RELEASE_B_PREFLIGHT_ARTIFACT_PATH
unset EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RELEASE_B_EXPECTED_MIGRATION_LEAF_SET RELEASE_B_PREFLIGHT_ARTIFACT_SHA256
COMPOSE_FILE="$COMPOSE_FILE" RELEASE_B_PREFLIGHT_ACTION=manual-release ./deploy/run_historical_calendar_release_b_preflight.sh
RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
RESTRICTED_RECOVERY_ATTEMPT_MODE="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RESTRICTED_RECOVERY_ATTEMPT_MODE
if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ] || [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ]; then
  echo "manual release handoff output is invalid" >&2; exit 1
fi

COMPOSE_FILE="$COMPOSE_FILE" ./deploy/run_release_tasks.sh
echo "manual release: release task completed; all application services remain stopped"
