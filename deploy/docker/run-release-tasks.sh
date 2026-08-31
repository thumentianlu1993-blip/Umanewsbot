#!/bin/sh
# Single in-container release task: the only migration owner in this repo.
# Runs inside a one-shot `compose run --rm --no-deps web` container.
# It only prepares schema and static files; it never starts any long-lived
# application process, never seeds data and never calls the network. Rollback
# may pin this control image to the migrate-verify and complete-intent phases;
# target-image collectstatic is deliberately owned by the host wrapper.
set -eu

cd /app/server
RELEASE_TASK_PHASE="${RELEASE_TASK_PHASE:-all}"
case "$RELEASE_TASK_PHASE" in all|migrate-verify|complete-intent) ;; *) echo "invalid RELEASE_TASK_PHASE" >&2; exit 1 ;; esac
python /app/deploy/docker/wait_for_services.py
python manage.py check_production_database_vendor
handoff_action="$(sed -n 's/.*"handoff_action":"\([^"]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
case "$handoff_action" in
  forward-resume)
    recovery_provenance_artifact_sha256="${RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256:-}"
    case "$recovery_provenance_artifact_sha256" in *[!0-9a-f]*) echo "forward-resume provenance artifact SHA is invalid" >&2; exit 1 ;; esac
    if [ "${#recovery_provenance_artifact_sha256}" -ne 64 ]; then echo "forward-resume provenance artifact SHA is invalid" >&2; exit 1; fi
    ;;
  deploy|manual-release|rollback|initial-install)
    unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
    recovery_provenance_artifact_sha256=""
    ;;
  *) echo "release handoff action is invalid" >&2; exit 1 ;;
esac
if [ "$RELEASE_TASK_PHASE" = "complete-intent" ]; then
  completion_identity_args=""
  if [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" = "required" ]; then
    marker_device="${RELEASE_EXPECTED_MARKER_DEVICE:-}"
    marker_inode="${RELEASE_EXPECTED_MARKER_INODE:-}"
    case "$marker_device" in ""|*[!0-9]*) echo "split completion marker identity is invalid" >&2; exit 1 ;; esac
    case "$marker_inode" in ""|*[!0-9]*) echo "split completion marker identity is invalid" >&2; exit 1 ;; esac
    completion_identity_args="--expected-marker-device=$marker_device --expected-marker-inode=$marker_inode"
  fi
else
  python manage.py verify_historical_calendar_release_b_handoff \
    --artifact-path="$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
    --artifact-sha256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
    --candidate-commit="${EXPECTED_CANDIDATE_COMMIT:-}" \
    --candidate-image-id="${EXPECTED_CANDIDATE_IMAGE_ID:-}" \
    --database-identity-sha256="${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}" \
    --compose-file="${EXPECTED_COMPOSE_FILE:-}" \
    --deployment-lock-token-sha256="${EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256:-}" \
    --release-0077-recovery-manifest-path="${RELEASE_0077_RECOVERY_MANIFEST_PATH:-}" \
    --release-0077-recovery-manifest-sha256="${RELEASE_0077_RECOVERY_MANIFEST_SHA256:-}" \
    --release-0077-recovery-origin-handoff-sha256="${RELEASE_0077_RECOVERY_ORIGIN_HANDOFF_SHA256:-}"
  intent_result="$(python manage.py ensure_historical_calendar_recovery_intent \
    --marker-path="$RESTRICTED_RECOVERY_MARKER_PATH" \
    --artifact-path="$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
    --artifact-sha256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
    --provenance-artifact-sha256="$recovery_provenance_artifact_sha256" \
    --candidate-commit="$EXPECTED_CANDIDATE_COMMIT" \
    --candidate-image-id="$EXPECTED_CANDIDATE_IMAGE_ID" \
    --database-identity-sha256="${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}" \
    --attempt-mode="$RESTRICTED_RECOVERY_ATTEMPT_MODE")"
  printf '%s\n' "$intent_result"
  marker_device="$(printf '%s' "$intent_result" | sed -n 's/.*"marker_device": \([0-9][0-9]*\).*/\1/p')"
  marker_inode="$(printf '%s' "$intent_result" | sed -n 's/.*"marker_inode": \([0-9][0-9]*\).*/\1/p')"
  completion_identity_args=""
  if [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" = "required" ]; then
    if [ -z "$marker_device" ] || [ -z "$marker_inode" ]; then
      echo "required recovery intent did not return a bound marker identity" >&2
      exit 1
    fi
    completion_identity_args="--expected-marker-device=$marker_device --expected-marker-inode=$marker_inode"
  fi
fi
if [ "$RELEASE_TASK_PHASE" != "complete-intent" ]; then
  python manage.py migrate --noinput
fi
if [ "$RELEASE_TASK_PHASE" = "migrate-verify" ]; then
  if [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" = "required" ]; then
    printf 'release-marker-identity=%s:%s\n' "$marker_device" "$marker_inode"
  else
    printf '%s\n' 'release-marker-identity=none'
  fi
  exit 0
fi
if [ "$RELEASE_TASK_PHASE" != "migrate-verify" ]; then
  if [ "$handoff_action" = "forward-resume" ]; then
    completion_artifact_sha256="$recovery_provenance_artifact_sha256"
  else
    completion_artifact_sha256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"
  fi
  python manage.py complete_historical_calendar_restricted_recovery \
    --marker-path="$RESTRICTED_RECOVERY_MARKER_PATH" \
    --artifact-path="$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
    --artifact-sha256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
    --attempt-mode="$RESTRICTED_RECOVERY_ATTEMPT_MODE" \
    $completion_identity_args \
    --provenance-artifact-sha256="$completion_artifact_sha256" \
    --candidate-commit="$EXPECTED_CANDIDATE_COMMIT" \
    --candidate-image-id="$EXPECTED_CANDIDATE_IMAGE_ID" \
    --database-identity-sha256="${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}"
fi
if [ "$RELEASE_TASK_PHASE" = "all" ]; then
  python manage.py collectstatic --noinput
fi
