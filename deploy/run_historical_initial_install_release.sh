#!/bin/sh
# Internal bridge selected only after deploy.sh has proved the exact reviewed
# pre-0070 origin. It creates the same durable required intent as recovery.
set -eu
unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
REPAIR_RUNTIME_ROOT="$ROOT_DIR/runtime/migration_history_repair"
PREFLIGHT_ROOT="$REPAIR_RUNTIME_ROOT/preflight"
if [ -L "$PREFLIGHT_ROOT" ]; then echo "preflight root must not be a symlink" >&2; exit 1; fi
umask 077
mkdir -p "$PREFLIGHT_ROOT"
chmod 700 "$PREFLIGHT_ROOT"
RELEASE_B_PREFLIGHT_DIR="$(mktemp -d "$PREFLIGHT_ROOT/initial.XXXXXXXX")"
RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_DIR/preflight.json"
EXPECTED_CANDIDATE_COMMIT="${UMANEWS_RELEASE_COMMIT:?UMANEWS_RELEASE_COMMIT is required}"
export RELEASE_B_PREFLIGHT_ARTIFACT_PATH EXPECTED_CANDIDATE_COMMIT
COMPOSE_FILE="${COMPOSE_FILE:-}" \
  RELEASE_B_EXPECTED_MIGRATION_LEAF_SET=stable.0067_historical_calendar_release_a \
  RELEASE_B_PREFLIGHT_ACTION=initial-install \
  "$ROOT_DIR/deploy/run_historical_calendar_release_b_preflight.sh"
RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
RESTRICTED_RECOVERY_ATTEMPT_MODE="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_PRODUCTION_DB_IDENTITY_SHA256
export RESTRICTED_RECOVERY_ATTEMPT_MODE EXPECTED_CANDIDATE_IMAGE_ID
if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ] || [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ] || [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" != required ]; then
  echo "historical initial-install handoff is invalid" >&2; exit 1
fi
RELEASE_HANDOFF_MODE=release-b COMPOSE_FILE="${COMPOSE_FILE:-}" RELEASE_ACTION=deploy \
  UMANEWS_ROOT_DIR="$ROOT_DIR" "$ROOT_DIR/deploy/run_application_release.sh"
