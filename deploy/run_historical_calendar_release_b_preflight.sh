#!/bin/sh
# Run the Release B forward schema preflight from the freshly built candidate
# image while every Release A long-lived service is still untouched.
set -eu

ROOT_DIR="${UMANEWS_ROOT_DIR:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *) echo "COMPOSE_FILE is not allowlisted" >&2; exit 1 ;;
esac

EXPECTED_CANDIDATE_COMMIT="${EXPECTED_CANDIDATE_COMMIT:-}"
case "$EXPECTED_CANDIDATE_COMMIT" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "EXPECTED_CANDIDATE_COMMIT must be a lowercase 40-character OID" >&2; exit 1 ;;
esac

if [ -z "${DEPLOYMENT_LOCK_TOKEN:-}" ]; then
  echo "DEPLOYMENT_LOCK_TOKEN is required" >&2
  exit 1
fi
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}"
db_args=""
if [ -n "$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" ]; then
  case "$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" in *[!0-9a-f]*) echo "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 must be a lowercase SHA-256" >&2; exit 1 ;; esac
  if [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ]; then echo "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 must be a lowercase SHA-256" >&2; exit 1; fi
  db_args="--expected-database-identity-sha256=$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256"
fi
./deploy/deployment_lock.sh verify

SCHEMA_PREFLIGHT_DIRECTION="${SCHEMA_PREFLIGHT_DIRECTION:-forward}"
case "$SCHEMA_PREFLIGHT_DIRECTION" in
  forward) ;;
  reverse) echo "reverse schema preflight is unsupported by this B-to-B handoff; use the separately reviewed cross-schema recovery" >&2; exit 1 ;;
  *) echo "SCHEMA_PREFLIGHT_DIRECTION must be forward" >&2; exit 1 ;;
esac
EXPECTED_MIGRATION_LEAF_SET="${RELEASE_B_EXPECTED_MIGRATION_LEAF_SET:-}"
case "$EXPECTED_MIGRATION_LEAF_SET" in
  "") leaf_args="" ;;
  stable.0067_historical_calendar_release_a)
    leaf_args="--expected-migration-leaf-set=stable.0067_historical_calendar_release_a"
    ;;
  stable.0070_horse_identity_evidence_commit_receipt)
    leaf_args="--expected-migration-leaf-set=stable.0070_horse_identity_evidence_commit_receipt"
    ;;
  stable.0068_race_data_sync_pipeline_a_field_audit,stable.0070_horse_identity_evidence_commit_receipt)
    leaf_args="--expected-migration-leaf-set=stable.0068_race_data_sync_pipeline_a_field_audit --expected-migration-leaf-set=stable.0070_horse_identity_evidence_commit_receipt"
    ;;
  stable.0069_race_data_sync_pipeline_a_ledger_guards,stable.0070_horse_identity_evidence_commit_receipt)
    leaf_args="--expected-migration-leaf-set=stable.0069_race_data_sync_pipeline_a_ledger_guards --expected-migration-leaf-set=stable.0070_horse_identity_evidence_commit_receipt"
    ;;
  stable.0071_historical_calendar_release_b)
    leaf_args="--expected-migration-leaf-set=stable.0071_historical_calendar_release_b"
    ;;
  stable.0072_add_extended_racing_regions)
    leaf_args="--expected-migration-leaf-set=stable.0072_add_extended_racing_regions"
    ;;
  stable.0073_lifecycle_enforce_registry)
    leaf_args="--expected-migration-leaf-set=stable.0073_lifecycle_enforce_registry"
    ;;
  stable.0074_race_data_sync_r0_control_plane)
    leaf_args="--expected-migration-leaf-set=stable.0074_race_data_sync_r0_control_plane"
    ;;
  *) echo "RELEASE_B_EXPECTED_MIGRATION_LEAF_SET must be one complete reviewed leaf set" >&2; exit 1 ;;
esac
RELEASE_B_PREFLIGHT_ACTION="${RELEASE_B_PREFLIGHT_ACTION:-}"
case "$RELEASE_B_PREFLIGHT_ACTION" in deploy|manual-release|rollback|forward-resume|initial-install) ;; *) echo "RELEASE_B_PREFLIGHT_ACTION is required" >&2; exit 1 ;; esac
if [ "$RELEASE_B_PREFLIGHT_ACTION" != forward-resume ]; then
  unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
fi
CANONICAL_RESTRICTED_RECOVERY_MARKER_PATH="$ROOT_DIR/runtime/migration_history_repair/restricted-recovery.json"
if [ -n "${RESTRICTED_RECOVERY_MARKER_PATH:-}" ] && [ "$RESTRICTED_RECOVERY_MARKER_PATH" != "$CANONICAL_RESTRICTED_RECOVERY_MARKER_PATH" ]; then
  echo "restricted recovery marker path must be canonical" >&2; exit 1
fi
RESTRICTED_RECOVERY_MARKER_PATH="$CANONICAL_RESTRICTED_RECOVERY_MARKER_PATH"
restricted_args="--restricted-marker-path=$RESTRICTED_RECOVERY_MARKER_PATH"
if [ "$RELEASE_B_PREFLIGHT_ACTION" = forward-resume ]; then
  if [ -z "${RESTRICTED_RECOVERY_MARKER_PATH:-}" ] || [ -z "${RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256:-}" ]; then
    echo "forward-resume preflight requires marker provenance" >&2; exit 1
  fi
  restricted_args="$restricted_args --provenance-artifact-sha256=$RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256"
fi

RELEASE_B_PREFLIGHT_ARTIFACT_PATH="${RELEASE_B_PREFLIGHT_ARTIFACT_PATH:-}"
if [ -z "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ] || [ -e "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ] || [ -L "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ]; then
  echo "RELEASE_B_PREFLIGHT_ARTIFACT_PATH must name a new no-clobber path" >&2
  exit 1
fi
artifact_dir="$(dirname "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
if [ ! -d "$artifact_dir" ] || [ -L "$artifact_dir" ]; then
  echo "artifact parent must be an existing non-symlink directory" >&2
  exit 1
fi
artifact_mount_root="$ROOT_DIR/runtime/migration_history_repair"
case "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" in
  "$artifact_mount_root"/*) ;;
  *) echo "artifact must stay under runtime/migration_history_repair" >&2; exit 1 ;;
esac
if [ "$(stat -c '%a' "$artifact_dir" 2>/dev/null || stat -f '%Lp' "$artifact_dir")" != "700" ]; then
  echo "artifact parent mode must be 0700" >&2
  exit 1
fi

IMAGE_NAME="${RELEASE_B_BINDING_IMAGE_NAME:-umanewsbot:prod}"
EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_NAME")"
IMAGE_COMMIT="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_NAME")"
if [ "$IMAGE_COMMIT" != "$EXPECTED_CANDIDATE_COMMIT" ]; then
  echo "candidate image revision does not match expected commit" >&2
  exit 1
fi

DEPLOYMENT_LOCK_TOKEN_SHA256="$(cat "${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}/token_sha256")"

set -- -f "$COMPOSE_FILE"
if [ -n "${RELEASE_CONTROL_COMPOSE_OVERRIDE:-}" ]; then
  if [ ! -f "$RELEASE_CONTROL_COMPOSE_OVERRIDE" ] || [ -L "$RELEASE_CONTROL_COMPOSE_OVERRIDE" ]; then echo "control compose override is untrusted" >&2; exit 1; fi
  set -- "$@" -f "$RELEASE_CONTROL_COMPOSE_OVERRIDE"
fi
./deploy/docker/compose-wrapper.sh "$@" run --rm --no-deps \
  -v "$artifact_mount_root:$artifact_mount_root:rw" \
  -e "UMANEWS_RELEASE_COMMIT=$EXPECTED_CANDIDATE_COMMIT" \
  -e "UMANEWS_RELEASE_IMAGE_ID=$EXPECTED_CANDIDATE_IMAGE_ID" \
  web python manage.py create_historical_calendar_release_b_handoff \
  --output-path="$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
  --compose-file="$COMPOSE_FILE" \
  --deployment-lock-token-sha256="$DEPLOYMENT_LOCK_TOKEN_SHA256" \
  --action="$RELEASE_B_PREFLIGHT_ACTION" \
  $leaf_args \
  $db_args \
  $restricted_args \
  --candidate-commit="$EXPECTED_CANDIDATE_COMMIT" \
  --candidate-image-id="$EXPECTED_CANDIDATE_IMAGE_ID"

if [ ! -f "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ] || [ -L "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" ]; then
  echo "candidate did not publish a trusted artifact" >&2
  exit 1
fi
if [ "$(stat -c '%a' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" 2>/dev/null || stat -f '%Lp' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")" != "600" ]; then
  echo "artifact mode must be 0600" >&2
  exit 1
fi
