#!/bin/sh
# Resume only the exact reviewed candidate after a 0068/0069 partial migration.
# All application services must remain stopped. This entry never builds, pulls,
# checks out, selects a latest artifact, or accepts a different candidate.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;; *) echo "COMPOSE_FILE is not allowlisted" >&2; exit 1 ;; esac

if [ -z "${RELEASE_B_PREFLIGHT_ARTIFACT_SHA256:-}" ]; then echo "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 provenance is required" >&2; exit 1; fi
if [ -z "${EXPECTED_CANDIDATE_COMMIT:-}" ]; then echo "EXPECTED_CANDIDATE_COMMIT is required" >&2; exit 1; fi
if [ -z "${EXPECTED_CANDIDATE_IMAGE_ID:-}" ]; then echo "EXPECTED_CANDIDATE_IMAGE_ID is required" >&2; exit 1; fi
MARKER="$ROOT_DIR/runtime/migration_history_repair/restricted-recovery.json"
CONTROL_STATE="$ROOT_DIR/runtime/migration_history_repair/restricted-recovery-control.json"
RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"
export RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256

# An active rollback receipt changes the entry point completely. Verify the
# state, trusted parents and every pinned file with the current reviewed host
# verifier before reading any state-derived path or invoking Git/Docker/lock.
# Only verifier output is parsed; the JSON receipt is never sourced or grepped.
if [ -e "$CONTROL_STATE" ] || [ -L "$CONTROL_STATE" ]; then
  VERIFIED_CONTROL_STATE="$(python3 ./deploy/verify_rollback_control_state.py \
    --state-path "$CONTROL_STATE" --compose-file "$COMPOSE_FILE" \
    --target-commit "$EXPECTED_CANDIDATE_COMMIT" \
    --target-image-id "$EXPECTED_CANDIDATE_IMAGE_ID" \
    --artifact-sha256 "$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256")"
  CONTROL_STATE_SHA256="$(printf '%s\n' "$VERIFIED_CONTROL_STATE" | sed -n '1p')"
  PINNED_RESUME="$(printf '%s\n' "$VERIFIED_CONTROL_STATE" | sed -n '3p')"
  CONTROL_ATTEMPT_MODE="$(printf '%s\n' "$VERIFIED_CONTROL_STATE" | sed -n '4p')"
  exec env UMANEWS_ROOT_DIR="$ROOT_DIR" COMPOSE_FILE="$COMPOSE_FILE" \
    EXPECTED_ROLLBACK_TARGET_COMMIT="$EXPECTED_CANDIDATE_COMMIT" \
    EXPECTED_ROLLBACK_TARGET_IMAGE_ID="$EXPECTED_CANDIDATE_IMAGE_ID" \
    EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
    EXPECTED_ROLLBACK_CONTROL_STATE_SHA256="$CONTROL_STATE_SHA256" \
    EXPECTED_ROLLBACK_RECOVERY_INTENT_MODE="$CONTROL_ATTEMPT_MODE" \
    "$PINNED_RESUME"
fi
if [ "$(git rev-parse HEAD)" != "$EXPECTED_CANDIDATE_COMMIT" ]; then echo "HEAD differs from reviewed repair candidate" >&2; exit 1; fi
if [ "$(docker image inspect --format '{{.Id}}' umanewsbot:prod)" != "$EXPECTED_CANDIDATE_IMAGE_ID" ]; then echo "image differs from reviewed repair candidate" >&2; exit 1; fi

DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=resume-release ./deploy/deployment_lock.sh acquire
release_lock() { ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true; }
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

artifact_mount_root="$ROOT_DIR/runtime/migration_history_repair"
CONTROL_DIR=""
CONTROL_OVERRIDE=""
TARGET_IMAGE_TAG="umanewsbot:prod"
RESUME_RELEASE_ACTION="deploy"
set -- -f "$COMPOSE_FILE"
if [ -n "$CONTROL_OVERRIDE" ]; then set -- "$@" -f "$CONTROL_OVERRIDE"; fi
./deploy/docker/compose-wrapper.sh "$@" run --rm --no-deps \
  -v "$artifact_mount_root:$artifact_mount_root:ro" \
  web python manage.py verify_historical_calendar_restricted_recovery \
  --marker-path="$MARKER" \
  --artifact-sha256="$RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256" \
  --candidate-commit="$EXPECTED_CANDIDATE_COMMIT" \
  --candidate-image-id="$EXPECTED_CANDIDATE_IMAGE_ID"

CONTROL_PREFLIGHT="$ROOT_DIR/deploy/run_historical_calendar_release_b_preflight.sh"
CONTROL_APPLICATION="$ROOT_DIR/deploy/run_application_release.sh"
CONTROL_RELEASE_TASKS="$ROOT_DIR/deploy/run_release_tasks.sh"

if [ -L "$artifact_mount_root" ]; then echo "repair runtime root must not be a symlink" >&2; exit 1; fi
mkdir -p "$artifact_mount_root/preflight"
chmod 700 "$artifact_mount_root" "$artifact_mount_root/preflight"
RELEASE_B_PREFLIGHT_DIR="$(mktemp -d "$artifact_mount_root/preflight/resume.XXXXXXXX")"
RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_DIR/preflight.json"
export RELEASE_B_PREFLIGHT_ARTIFACT_PATH
unset EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RELEASE_B_EXPECTED_MIGRATION_LEAF_SET
COMPOSE_FILE="$COMPOSE_FILE" RELEASE_B_PREFLIGHT_ACTION=forward-resume \
  UMANEWS_ROOT_DIR="$ROOT_DIR" RELEASE_B_BINDING_IMAGE_NAME="$TARGET_IMAGE_TAG" \
  RELEASE_CONTROL_COMPOSE_OVERRIDE="$CONTROL_OVERRIDE" \
  RESTRICTED_RECOVERY_MARKER_PATH="$MARKER" "$CONTROL_PREFLIGHT"
RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
RESTRICTED_RECOVERY_ATTEMPT_MODE="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RESTRICTED_RECOVERY_ATTEMPT_MODE
if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ] || [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ]; then
  echo "fresh restricted-resume handoff is invalid" >&2; exit 1
fi

COMPOSE_FILE="$COMPOSE_FILE" RELEASE_ACTION="$RESUME_RELEASE_ACTION" RESTRICTED_RECOVERY_ACTIVE=true \
  UMANEWS_ROOT_DIR="$ROOT_DIR" RELEASE_TASK_WRAPPER_PATH="$CONTROL_RELEASE_TASKS" \
  RELEASE_TARGET_IMAGE_TAG="$TARGET_IMAGE_TAG" RELEASE_CONTROL_COMPOSE_OVERRIDE="$CONTROL_OVERRIDE" \
  RESTRICTED_RECOVERY_MARKER_PATH="$MARKER" "$CONTROL_APPLICATION"
echo "migration-history repair forward resume completed"
