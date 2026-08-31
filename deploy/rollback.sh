#!/bin/sh
set -eu
unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/rollback.sh <git-ref>"
  exit 1
fi

TARGET_REF="$1"

COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="docker-compose.prod.yml"

# Acquire the host-local deployment lock before any stateful action. The
# release trap is installed only after a successful acquire so a contender
# that loses the race never touches the winner's lock.
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=rollback ./deploy/deployment_lock.sh acquire
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
PRE_CONTROL_RESTORE_ARMED=false
restore_pre_control_state() {
  restore_failed=false
  if [ "$ORIGINAL_HEAD_KIND" = branch ]; then
    if ! git checkout "${ORIGINAL_HEAD_REF#refs/heads/}" >/dev/null 2>&1; then restore_failed=true; fi
    if [ "$(git symbolic-ref --quiet HEAD 2>/dev/null || true)" != "$ORIGINAL_HEAD_REF" ]; then restore_failed=true; fi
  else
    if ! git checkout --detach "$ORIGINAL_HEAD_OID" >/dev/null 2>&1; then restore_failed=true; fi
    if git symbolic-ref --quiet HEAD >/dev/null 2>&1; then restore_failed=true; fi
  fi
  if [ "$(git rev-parse HEAD 2>/dev/null || true)" != "$ORIGINAL_HEAD_OID" ]; then restore_failed=true; fi
  if ! docker tag "$ORIGINAL_PROD_IMAGE_ID" umanewsbot:prod >/dev/null 2>&1; then restore_failed=true; fi
  if [ "$(docker image inspect --format '{{.Id}}' umanewsbot:prod 2>/dev/null || true)" != "$ORIGINAL_PROD_IMAGE_ID" ]; then restore_failed=true; fi
  if [ "$restore_failed" = true ]; then
    echo "rollback: failed to restore original HEAD/image before durable control state" >&2
    return 1
  fi
}
on_exit() {
  rc=$?
  if [ "$PRE_CONTROL_RESTORE_ARMED" = true ]; then
    restore_pre_control_state || rc=1
  fi
  release_lock
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# The active marker belongs to the current candidate/provenance. Refuse before
# fetch, checkout, build, image retagging, or any other candidate mutation.
python3 ./deploy/ensure_migration_history_repair_runtime.py
./deploy/check_restricted_recovery_marker.sh

git fetch --all --tags
# Resolve the target once and bind every later check to the immutable OID.
TARGET_OID="$(git rev-parse --verify "$TARGET_REF^{commit}")"
# The resolved OID must be a single 40-character lowercase hex commit ID;
# reject empty, multi-line or otherwise malformed output before any
# cat-file, preflight or checkout.
case "$TARGET_OID" in
  *[!0-9a-f]*)
    echo "rollback: resolved OID is malformed; refusing before any check" >&2
    exit 1
    ;;
esac
if [ "${#TARGET_OID}" -ne 40 ]; then
  echo "rollback: resolved OID is not a 40-character commit id; refusing before any check" >&2
  exit 1
fi
# The target must carry the release contract and every v1 helper; refuse
# before any checkout or service stop. Forward migrate is NOT a database
# rollback.
for helper in \
  deploy/release_contract_v1 \
  deploy/run_application_release.sh \
  deploy/deployment_lock.sh \
  deploy/run_release_tasks.sh \
  deploy/wait_for_compose_service_healthy.sh \
  deploy/wait_for_celery_drain.sh \
  deploy/docker/run-release-tasks.sh \
  deploy/docker/start-web.sh \
  deploy/docker/compose-wrapper.sh
do
  if ! git cat-file -e "$TARGET_OID:$helper"; then
    echo "rollback: target is missing required v1 helper $helper; refusing before checkout" >&2
    exit 1
  fi
done

# Read the target migration without checkout and require one exact reviewed
# content/dependency contract. Mere path existence is not schema eligibility.
python3 ./deploy/verify_rollback_target_migration.py --target-oid "$TARGET_OID" >/dev/null

# The existing web is still running here, so the historical runner preflight
# preconditions hold (same semantics as deploy; no --initial-install branch).
COMPOSE_FILE="$COMPOSE_FILE" ./deploy/historical_runner_preflight.sh

# Capture the exact pre-rollback Git attachment and production image before
# any checkout or retag of umanewsbot:prod. Until a verified durable control
# state exists, every failure restores both identities; no service stop occurs
# in this window.
ORIGINAL_HEAD_OID="$(git rev-parse HEAD)"
case "$ORIGINAL_HEAD_OID" in *[!0-9a-f]*) echo "rollback: original HEAD OID is malformed" >&2; exit 1 ;; esac
if [ "${#ORIGINAL_HEAD_OID}" -ne 40 ]; then echo "rollback: original HEAD OID is malformed" >&2; exit 1; fi
ORIGINAL_HEAD_REF="$(git symbolic-ref --quiet HEAD 2>/dev/null || true)"
if [ -n "$ORIGINAL_HEAD_REF" ]; then
  case "$ORIGINAL_HEAD_REF" in refs/heads/*) ORIGINAL_HEAD_KIND=branch ;; *) echo "rollback: original HEAD ref is malformed" >&2; exit 1 ;; esac
else
  ORIGINAL_HEAD_KIND=detached
fi
ORIGINAL_PROD_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
case "$ORIGINAL_PROD_IMAGE_ID" in sha256:*) ;; *) echo "rollback: original production image ID is malformed" >&2; exit 1 ;; esac
PRE_CONTROL_RESTORE_ARMED=true

# Freeze the reviewed v2 control plane before checkout. A pre-v2 Release B
# target supplies only the final application image; it must never replace the
# verifier/intent/completion code used by this rollback attempt.
REPAIR_RUNTIME_ROOT="$ROOT_DIR/runtime/migration_history_repair"
if [ -L "$REPAIR_RUNTIME_ROOT" ]; then echo "repair runtime root must not be a symlink" >&2; exit 1; fi
CONTROL_DIR="$(mktemp -d "$REPAIR_RUNTIME_ROOT/rollback-control.XXXXXXXX")"
chmod 700 "$CONTROL_DIR"
cp deploy/run_historical_calendar_release_b_preflight.sh "$CONTROL_DIR/preflight.sh"
cp deploy/run_application_release.sh "$CONTROL_DIR/application-release.sh"
cp deploy/run_release_tasks.sh "$CONTROL_DIR/release-tasks.sh"
cp deploy/resume_rollback_control_state.sh "$CONTROL_DIR/resume-rollback-release.sh"
cp deploy/create_rollback_control_state.py "$CONTROL_DIR/create-control-state.py"
cp deploy/verify_rollback_control_state.py "$CONTROL_DIR/verify-control-state.py"
chmod 500 "$CONTROL_DIR"/*.sh "$CONTROL_DIR/create-control-state.py" "$CONTROL_DIR/verify-control-state.py"
CONTROL_IMAGE_TAG="umanewsbot:rollback-control-$DEPLOYMENT_LOCK_TOKEN"
TARGET_IMAGE_TAG="umanewsbot:rollback-target-$DEPLOYMENT_LOCK_TOKEN"
CONTROL_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
docker tag umanewsbot:prod "$CONTROL_IMAGE_TAG"
CONTROL_OVERRIDE="$CONTROL_DIR/compose-control.yml"
printf 'services:\n  web:\n    image: "%s"\n' "$CONTROL_IMAGE_ID" > "$CONTROL_OVERRIDE"
chmod 400 "$CONTROL_OVERRIDE"

git checkout "$TARGET_OID"
UMANEWS_RELEASE_COMMIT="$TARGET_OID"
export UMANEWS_RELEASE_COMMIT
"$COMPOSE" -f "$COMPOSE_FILE" build web
EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
docker tag umanewsbot:prod "$TARGET_IMAGE_TAG"
if [ "$(docker image inspect --format '{{.Id}}' "$CONTROL_IMAGE_TAG")" != "$CONTROL_IMAGE_ID" ]; then echo "preserved rollback control image drifted" >&2; exit 1; fi
control_owner="$(stat -c '%u' "$CONTROL_DIR" 2>/dev/null || stat -f '%u' "$CONTROL_DIR")"
control_mode="$(stat -c '%a' "$CONTROL_DIR" 2>/dev/null || stat -f '%Lp' "$CONTROL_DIR")"
if [ "$control_owner" != "$(id -u)" ] || [ "$control_mode" != "700" ]; then echo "rollback control directory trust failed" >&2; exit 1; fi
for control_script in "$CONTROL_DIR"/*.sh "$CONTROL_DIR/create-control-state.py" "$CONTROL_DIR/verify-control-state.py"; do
  script_owner="$(stat -c '%u' "$control_script" 2>/dev/null || stat -f '%u' "$control_script")"
  script_mode="$(stat -c '%a' "$control_script" 2>/dev/null || stat -f '%Lp' "$control_script")"
  if [ -L "$control_script" ] || [ ! -f "$control_script" ] || [ "$script_owner" != "$(id -u)" ] || [ "$script_mode" != "500" ]; then echo "rollback control script trust failed" >&2; exit 1; fi
done
override_owner="$(stat -c '%u' "$CONTROL_OVERRIDE" 2>/dev/null || stat -f '%u' "$CONTROL_OVERRIDE")"
override_mode="$(stat -c '%a' "$CONTROL_OVERRIDE" 2>/dev/null || stat -f '%Lp' "$CONTROL_OVERRIDE")"
if [ "$override_owner" != "$(id -u)" ] || [ "$override_mode" != "400" ]; then echo "rollback control override trust failed" >&2; exit 1; fi

# Release 0077 is forward-only.  The verifier above rejects every generic code
# rollback before checkout/build; exact PR133 is not compatible with the five
# new NOT NULL ExternalHorse columns.  A 0076 partial state must be completed
# with the candidate image, while recovery after completed 0077 uses the
# release-bound verified database backup.  No reverse migration is permitted.
PREFLIGHT_ROOT="$REPAIR_RUNTIME_ROOT/preflight"
if [ -L "$PREFLIGHT_ROOT" ]; then echo "preflight root must not be a symlink" >&2; exit 1; fi
umask 077
mkdir -p "$PREFLIGHT_ROOT"
chmod 700 "$PREFLIGHT_ROOT"
RELEASE_B_PREFLIGHT_DIR="$(mktemp -d "$PREFLIGHT_ROOT/before.XXXXXXXX")"
RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_DIR/preflight.json"
export RELEASE_B_PREFLIGHT_ARTIFACT_PATH
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CANDIDATE_COMMIT="$TARGET_OID" \
  UMANEWS_ROOT_DIR="$ROOT_DIR" RELEASE_B_BINDING_IMAGE_NAME="$TARGET_IMAGE_TAG" \
  RELEASE_CONTROL_COMPOSE_OVERRIDE="$CONTROL_OVERRIDE" \
  RELEASE_B_PREFLIGHT_ACTION=rollback \
  RELEASE_B_EXPECTED_MIGRATION_LEAF_SET=stable.0077_racing_api_horse_identity_staging \
  "$CONTROL_DIR/preflight.sh"
RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
RESTRICTED_RECOVERY_ATTEMPT_MODE="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
EXPECTED_CANDIDATE_COMMIT="$TARGET_OID"
export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_CANDIDATE_COMMIT EXPECTED_CANDIDATE_IMAGE_ID EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RESTRICTED_RECOVERY_ATTEMPT_MODE
if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ]; then echo "invalid artifact SHA" >&2; exit 1; fi
if [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ]; then echo "invalid database identity SHA" >&2; exit 1; fi

CONTROL_STATE="$REPAIR_RUNTIME_ROOT/restricted-recovery-control.json"
if [ -e "$CONTROL_STATE" ] || [ -L "$CONTROL_STATE" ]; then echo "active rollback control state exists; use forward-resume" >&2; exit 1; fi
INITIATING_LOCK_TOKEN_SHA256="$(cat "${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}/token_sha256")"
CONTROL_STATE_SHA256="$(python3 "$CONTROL_DIR/create-control-state.py" \
  --state-path "$CONTROL_STATE" \
  --compose-file "$COMPOSE_FILE" \
  --control-dir "$CONTROL_DIR" \
  --control-image-id "$CONTROL_IMAGE_ID" \
  --control-override "$CONTROL_OVERRIDE" \
  --initiating-artifact-path "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" \
  --initiating-artifact-sha256 "$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
  --initiating-database-identity-sha256 "$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" \
  --initiating-lock-token-sha256 "$INITIATING_LOCK_TOKEN_SHA256" \
  --recovery-intent-mode "$RESTRICTED_RECOVERY_ATTEMPT_MODE" \
  --target-commit "$TARGET_OID" \
  --target-image-id "$EXPECTED_CANDIDATE_IMAGE_ID" \
  --target-image-tag "$TARGET_IMAGE_TAG")"
case "$CONTROL_STATE_SHA256" in *[!0-9a-f]*) echo "rollback control state SHA is invalid" >&2; exit 1 ;; esac
if [ "${#CONTROL_STATE_SHA256}" -ne 64 ]; then echo "rollback control state SHA is invalid" >&2; exit 1; fi
python3 "$CONTROL_DIR/verify-control-state.py" \
  --state-path "$CONTROL_STATE" --compose-file "$COMPOSE_FILE" \
  --target-commit "$TARGET_OID" --target-image-id "$EXPECTED_CANDIDATE_IMAGE_ID" \
  --artifact-sha256 "$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256" \
  --expected-state-sha256 "$CONTROL_STATE_SHA256" \
  --recovery-intent-mode "$RESTRICTED_RECOVERY_ATTEMPT_MODE" >/dev/null
PRE_CONTROL_RESTORE_ARMED=false
COMPLETED_CONTROL_STATE="$REPAIR_RUNTIME_ROOT/restricted-recovery-control.completed.$TARGET_OID.$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256.$CONTROL_STATE_SHA256.json"
if [ -e "$COMPLETED_CONTROL_STATE" ] || [ -L "$COMPLETED_CONTROL_STATE" ]; then echo "completed rollback control state collision" >&2; exit 1; fi
if COMPOSE_FILE="$COMPOSE_FILE" RELEASE_ACTION=rollback UMANEWS_ROOT_DIR="$ROOT_DIR" \
  RELEASE_TASK_WRAPPER_PATH="$CONTROL_DIR/release-tasks.sh" \
  RELEASE_TARGET_IMAGE_TAG="$TARGET_IMAGE_TAG" \
  RELEASE_CONTROL_COMPOSE_OVERRIDE="$CONTROL_OVERRIDE" \
  "$CONTROL_DIR/application-release.sh"; then
  :
else
  rc=$?
  if [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" = "not-required" ]; then
    echo "rollback failed with markerless control state; retry only with: COMPOSE_FILE=$COMPOSE_FILE EXPECTED_ROLLBACK_TARGET_COMMIT=$TARGET_OID EXPECTED_ROLLBACK_TARGET_IMAGE_ID=$EXPECTED_CANDIDATE_IMAGE_ID EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=$CONTROL_STATE_SHA256 $CONTROL_DIR/resume-rollback-release.sh" >&2
  fi
  exit "$rc"
fi
python3 "$CONTROL_DIR/create-control-state.py" complete \
  --state-path "$CONTROL_STATE" \
  --completed-path "$COMPLETED_CONTROL_STATE" \
  --expected-state-sha256 "$CONTROL_STATE_SHA256" >/dev/null
