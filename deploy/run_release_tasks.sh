#!/bin/sh
# Protected host wrapper for bounded release task phases.
#
# This is an internal entry: it refuses to run without the current deployment
# lock owner token, and verifies the lock before any Compose call. Operators
# must use deploy/deploy.sh, deploy/rollback*.sh or deploy/manual_release.sh
# instead of calling this wrapper directly.
#
# Environment:
#   COMPOSE_FILE            docker-compose.prod.yml or docker-compose.prod.lowcost.yml
#   DEPLOYMENT_LOCK_TOKEN   owner token of the held deployment lock
set -eu

ROOT_DIR="${UMANEWS_ROOT_DIR:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *)
    echo "COMPOSE_FILE must be docker-compose.prod.yml or docker-compose.prod.lowcost.yml" >&2
    exit 1
    ;;
esac

if [ -z "${DEPLOYMENT_LOCK_TOKEN:-}" ]; then
  echo "DEPLOYMENT_LOCK_TOKEN is required; run_release_tasks.sh is a protected internal entry" >&2
  exit 1
fi

RELEASE_HANDOFF_MODE="${RELEASE_HANDOFF_MODE:-release-b}"
case "$RELEASE_HANDOFF_MODE" in release-b) ;; *) echo "RELEASE_HANDOFF_MODE is invalid" >&2; exit 1 ;; esac
if [ -z "${RELEASE_B_PREFLIGHT_ARTIFACT_PATH:-}" ]; then echo "RELEASE_B_PREFLIGHT_ARTIFACT_PATH is required" >&2; exit 1; fi
if [ -z "${RELEASE_B_PREFLIGHT_ARTIFACT_SHA256:-}" ]; then echo "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 is required" >&2; exit 1; fi
if [ -z "${EXPECTED_CANDIDATE_COMMIT:-}" ]; then echo "EXPECTED_CANDIDATE_COMMIT is required" >&2; exit 1; fi
if [ -z "${EXPECTED_CANDIDATE_IMAGE_ID:-}" ]; then echo "EXPECTED_CANDIDATE_IMAGE_ID is required" >&2; exit 1; fi
if [ -z "${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}" ]; then echo "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 is required" >&2; exit 1; fi
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
  "") RESTRICTED_RECOVERY_ATTEMPT_MODE="not-required" ;;
  *) echo "invalid recovery_intent_mode in exact handoff artifact" >&2; exit 1 ;;
esac
artifact_handoff_action="$(sed -n 's/.*"handoff_action":"\([^"]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
case "$artifact_handoff_action" in
  forward-resume)
    provenance_sha256="${RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256:-}"
    case "$provenance_sha256" in *[!0-9a-f]*) echo "forward-resume provenance artifact SHA is invalid" >&2; exit 1 ;; esac
    if [ "${#provenance_sha256}" -ne 64 ]; then echo "forward-resume provenance artifact SHA is invalid" >&2; exit 1; fi
    ;;
  deploy|manual-release|rollback|initial-install)
    unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
    provenance_sha256=""
    ;;
  *) echo "invalid handoff_action in exact handoff artifact" >&2; exit 1 ;;
esac
CANONICAL_RESTRICTED_RECOVERY_MARKER_PATH="$ROOT_DIR/runtime/migration_history_repair/restricted-recovery.json"
if [ -n "${RESTRICTED_RECOVERY_MARKER_PATH:-}" ] && [ "$RESTRICTED_RECOVERY_MARKER_PATH" != "$CANONICAL_RESTRICTED_RECOVERY_MARKER_PATH" ]; then
  echo "restricted recovery marker path must be canonical" >&2; exit 1
fi
RESTRICTED_RECOVERY_MARKER_PATH="$CANONICAL_RESTRICTED_RECOVERY_MARKER_PATH"
export RESTRICTED_RECOVERY_MARKER_PATH

# Verify the deployment lock before any Compose call.
./deploy/deployment_lock.sh verify

echo "release task: starting one-shot container (compose=$COMPOSE_FILE)"
artifact_mount_root="$ROOT_DIR/runtime/migration_history_repair"
case "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" in "$artifact_mount_root"/*) ;; *) echo "artifact path outside repair runtime" >&2; exit 1 ;; esac
set -- -f "$COMPOSE_FILE"
if [ -n "${RELEASE_CONTROL_COMPOSE_OVERRIDE:-}" ]; then
  if [ ! -f "$RELEASE_CONTROL_COMPOSE_OVERRIDE" ] || [ -L "$RELEASE_CONTROL_COMPOSE_OVERRIDE" ]; then echo "control compose override is untrusted" >&2; exit 1; fi
  set -- "$@" -f "$RELEASE_CONTROL_COMPOSE_OVERRIDE"
fi
run_control_phase() {
  phase="$1"
  shift
  ./deploy/docker/compose-wrapper.sh "$@" run --rm --no-deps \
    -v "$artifact_mount_root:$artifact_mount_root:rw" \
    -e "RELEASE_TASK_PHASE=$phase" \
    -e "RELEASE_B_PREFLIGHT_ARTIFACT_PATH=$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
    -e "RELEASE_HANDOFF_MODE=$RELEASE_HANDOFF_MODE" \
    -e "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256=$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
    -e "EXPECTED_CANDIDATE_COMMIT=$EXPECTED_CANDIDATE_COMMIT" \
    -e "EXPECTED_CANDIDATE_IMAGE_ID=$EXPECTED_CANDIDATE_IMAGE_ID" \
    -e "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256=$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" \
    -e "EXPECTED_COMPOSE_FILE=$COMPOSE_FILE" \
    -e "EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256=$(cat "${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}/token_sha256")" \
    -e "RESTRICTED_RECOVERY_MARKER_PATH=$RESTRICTED_RECOVERY_MARKER_PATH" \
    -e "RESTRICTED_RECOVERY_ACTIVE=${RESTRICTED_RECOVERY_ACTIVE:-false}" \
    -e "RESTRICTED_RECOVERY_ATTEMPT_MODE=$RESTRICTED_RECOVERY_ATTEMPT_MODE" \
    -e "RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256=$provenance_sha256" \
    -e "RELEASE_EXPECTED_MARKER_DEVICE=${RELEASE_EXPECTED_MARKER_DEVICE:-}" \
    -e "RELEASE_EXPECTED_MARKER_INODE=${RELEASE_EXPECTED_MARKER_INODE:-}" \
    web /app/deploy/docker/run-release-tasks.sh
}

if [ -n "${RELEASE_CONTROL_COMPOSE_OVERRIDE:-}" ]; then
  if [ -z "${RELEASE_TARGET_IMAGE_TAG:-}" ]; then echo "rollback target image tag is required for split release" >&2; exit 1; fi
  case "$RELEASE_TARGET_IMAGE_TAG" in
    umanewsbot:rollback-target-*) ;;
    *) echo "rollback target image tag is invalid for split release" >&2; exit 1 ;;
  esac
  target_tag_token="${RELEASE_TARGET_IMAGE_TAG#umanewsbot:rollback-target-}"
  case "$target_tag_token" in *[!0-9a-f]*|"") echo "rollback target image tag is invalid for split release" >&2; exit 1 ;; esac
  if [ "${#target_tag_token}" -ne 64 ]; then echo "rollback target image tag is invalid for split release" >&2; exit 1; fi
  target_image_id="$(docker image inspect --format '{{.Id}}' "$RELEASE_TARGET_IMAGE_TAG")" || exit 1
  if [ "$target_image_id" != "$EXPECTED_CANDIDATE_IMAGE_ID" ]; then echo "rollback target image ID mismatch before collectstatic" >&2; exit 1; fi

  # The pinned control image owns verification/migration and intent completion,
  # but never writes static output. The target override changes only web.image,
  # so Compose keeps the exact production static volume definition.
  control_output="$(run_control_phase migrate-verify "$@")"
  printf '%s\n' "$control_output"
  identity_count="$(printf '%s\n' "$control_output" | awk '/^release-marker-identity=/{count++} END {print count+0}')"
  marker_identity="$(printf '%s\n' "$control_output" | sed -n 's/^release-marker-identity=//p')"
  if [ "$identity_count" -ne 1 ]; then echo "split migrate phase returned invalid marker identity count" >&2; exit 1; fi
  RELEASE_EXPECTED_MARKER_DEVICE=""
  RELEASE_EXPECTED_MARKER_INODE=""
  if [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" = "required" ]; then
    RELEASE_EXPECTED_MARKER_DEVICE="${marker_identity%%:*}"
    RELEASE_EXPECTED_MARKER_INODE="${marker_identity#*:}"
    case "$RELEASE_EXPECTED_MARKER_DEVICE" in ""|*[!0-9]*) echo "split migrate phase returned invalid marker identity" >&2; exit 1 ;; esac
    case "$RELEASE_EXPECTED_MARKER_INODE" in ""|*[!0-9]*) echo "split migrate phase returned invalid marker identity" >&2; exit 1 ;; esac
  elif [ "$marker_identity" != "none" ]; then
    echo "markerless split migrate phase returned unexpected marker identity" >&2
    exit 1
  fi
  target_override="$(mktemp "$artifact_mount_root/target-collectstatic.XXXXXXXX.yml")"
  cleanup_target_override() { rm -f "$target_override"; }
  trap cleanup_target_override EXIT
  trap 'cleanup_target_override; exit 129' HUP
  trap 'cleanup_target_override; exit 130' INT
  trap 'cleanup_target_override; exit 143' TERM
  chmod 600 "$target_override"
  printf 'services:\n  web:\n    image: "%s"\n' "$RELEASE_TARGET_IMAGE_TAG" > "$target_override"
  chmod 400 "$target_override"
  target_image_id="$(docker image inspect --format '{{.Id}}' "$RELEASE_TARGET_IMAGE_TAG")" || exit 1
  if [ "$target_image_id" != "$EXPECTED_CANDIDATE_IMAGE_ID" ]; then echo "rollback target image ID mismatch immediately before collectstatic" >&2; exit 1; fi
  ./deploy/docker/compose-wrapper.sh -f "$COMPOSE_FILE" -f "$target_override" \
    run --rm --no-deps web python manage.py collectstatic --noinput
  target_image_id="$(docker image inspect --format '{{.Id}}' "$RELEASE_TARGET_IMAGE_TAG")" || exit 1
  if [ "$target_image_id" != "$EXPECTED_CANDIDATE_IMAGE_ID" ]; then echo "rollback target image ID mismatch after collectstatic" >&2; exit 1; fi
  run_control_phase complete-intent "$@"
  cleanup_target_override
  trap - EXIT HUP INT TERM
else
  run_control_phase all "$@"
fi
echo "release task: completed"
