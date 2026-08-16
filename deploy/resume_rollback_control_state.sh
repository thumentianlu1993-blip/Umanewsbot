#!/bin/sh
# Audited retry entry for a markerless (recovery_intent_mode=not-required)
# B-to-B rollback whose one-shot failed after the pinned control state was
# persisted. rollback*.sh copies this file into the immutable control dir
# before checkout; invoke that preserved copy, never a target-checkout helper.
set -eu

ROOT_DIR="${UMANEWS_ROOT_DIR:-$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)}"
cd "$ROOT_DIR"
COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;; *) echo "COMPOSE_FILE is not allowlisted" >&2; exit 1 ;; esac
if [ -z "${EXPECTED_ROLLBACK_TARGET_COMMIT:-}" ]; then echo "EXPECTED_ROLLBACK_TARGET_COMMIT is required" >&2; exit 1; fi
if [ -z "${EXPECTED_ROLLBACK_TARGET_IMAGE_ID:-}" ]; then echo "EXPECTED_ROLLBACK_TARGET_IMAGE_ID is required" >&2; exit 1; fi
if [ -z "${EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256:-}" ]; then echo "EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256 is required" >&2; exit 1; fi
if [ -z "${EXPECTED_ROLLBACK_CONTROL_STATE_SHA256:-}" ]; then echo "EXPECTED_ROLLBACK_CONTROL_STATE_SHA256 is required" >&2; exit 1; fi
EXPECTED_ROLLBACK_RECOVERY_INTENT_MODE="${EXPECTED_ROLLBACK_RECOVERY_INTENT_MODE:-}"
for digest in "$EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256" "$EXPECTED_ROLLBACK_CONTROL_STATE_SHA256"; do
  case "$digest" in *[!0-9a-f]*) echo "expected rollback attempt identity is malformed" >&2; exit 1 ;; esac
  if [ "${#digest}" -ne 64 ]; then echo "expected rollback attempt identity is malformed" >&2; exit 1; fi
done

MARKER_ROOT="$ROOT_DIR/runtime/migration_history_repair"
CONTROL_STATE="$MARKER_ROOT/restricted-recovery-control.json"
CONTROL_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
COMPLETED_CONTROL_STATE="$MARKER_ROOT/restricted-recovery-control.completed.$EXPECTED_ROLLBACK_TARGET_COMMIT.$EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256.$EXPECTED_ROLLBACK_CONTROL_STATE_SHA256.json"
COMPLETED_ONLY=false
STATE_SOURCE="$CONTROL_STATE"
if [ ! -e "$CONTROL_STATE" ] && [ ! -L "$CONTROL_STATE" ]; then
  COMPLETED_ONLY=true
  STATE_SOURCE="$COMPLETED_CONTROL_STATE"
fi
verify_control_state_files() {
  python3 - "$STATE_SOURCE" "$CONTROL_DIR" "$COMPOSE_FILE" "$EXPECTED_ROLLBACK_TARGET_COMMIT" "$EXPECTED_ROLLBACK_TARGET_IMAGE_ID" "$EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256" "$EXPECTED_ROLLBACK_CONTROL_STATE_SHA256" "$COMPLETED_ONLY" <<'PY'
import hashlib
import json
import os
import stat
import sys

(
    state_path,
    control_dir,
    compose_file,
    target_commit,
    target_image_id,
    artifact_sha256,
    expected_state_sha256,
    completed_only,
) = sys.argv[1:]
state_path = os.path.abspath(state_path)
control_dir = os.path.abspath(control_dir)

def trusted_read(path, expected_mode):
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_fd = os.open(os.path.dirname(path), parent_flags)
    try:
        parent_info = os.fstat(parent_fd)
        if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid()
                or stat.S_IMODE(parent_info.st_mode) != 0o700):
            raise ValueError("untrusted rollback control parent")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(os.path.basename(path), flags, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != expected_mode):
                raise ValueError("untrusted rollback control file")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size) != (
                after.st_dev, after.st_ino, after.st_size
            ):
                raise ValueError("rollback control file changed during read")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)

raw_state = trusted_read(state_path, 0o600)
if completed_only == "true":
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        root_flags |= os.O_NOFOLLOW
    root_fd = os.open(os.path.dirname(state_path), root_flags)
    try:
        if os.path.basename(state_path) not in os.listdir(root_fd):
            raise ValueError("exact completed rollback receipt is absent")
    finally:
        os.close(root_fd)
state = json.loads(raw_state.decode("utf-8"))
unsigned = {key: value for key, value in state.items() if key != "state_sha256"}
canonical = json.dumps(
    unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
if state.get("state_sha256") != hashlib.sha256(canonical).hexdigest():
    raise ValueError("rollback control state SHA mismatch")
if (state.get("state_sha256") != expected_state_sha256
        or state.get("initiating_artifact_sha256") != artifact_sha256):
    raise ValueError("rollback control state attempt identity mismatch")
if state.get("schema_version") != "rollback-control-state/v1":
    raise ValueError("rollback control state schema mismatch")
if (os.path.abspath(state.get("control_dir", "")) != control_dir
        or state.get("compose_file") != compose_file
        or state.get("target_commit") != target_commit
        or state.get("target_image_id") != target_image_id
        or state.get("recovery_intent_mode") not in {"required", "not-required"}):
    raise ValueError("rollback control state binding mismatch")
directory_info = os.stat(control_dir, follow_symlinks=False)
if (not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != os.getuid()
        or stat.S_IMODE(directory_info.st_mode) != 0o700):
    raise ValueError("untrusted rollback control directory")
expected = {
    "application_release": (os.path.join(control_dir, "application-release.sh"), 0o500),
    "control_state_creator": (os.path.join(control_dir, "create-control-state.py"), 0o500),
    "control_state_verifier": (os.path.join(control_dir, "verify-control-state.py"), 0o500),
    "preflight": (os.path.join(control_dir, "preflight.sh"), 0o500),
    "release_tasks": (os.path.join(control_dir, "release-tasks.sh"), 0o500),
    "resume_rollback": (os.path.join(control_dir, "resume-rollback-release.sh"), 0o500),
    "compose_override": (os.path.join(control_dir, "compose-control.yml"), 0o400),
}
control_files = state.get("control_files")
if not isinstance(control_files, dict) or set(control_files) != set(expected):
    raise ValueError("rollback control file catalog mismatch")
for name, (path, mode) in expected.items():
    binding = control_files.get(name)
    if (not isinstance(binding, dict) or binding.get("path") != path
            or binding.get("mode") != format(mode, "04o")):
        raise ValueError("rollback control file binding mismatch")
    actual = hashlib.sha256(trusted_read(path, mode)).hexdigest()
    if binding.get("sha256") != actual:
        raise ValueError("rollback control file SHA mismatch")
if state.get("control_override") != expected["compose_override"][0]:
    raise ValueError("rollback control override binding mismatch")
PY
}

# First verification happens before lock-helper or Docker/Compose execution;
# repeat under the acquired lock to close the ordinary mutation window.
verify_control_state_files

# The exact attempt-specific completed receipt is a durable success boundary.
# If the active state was already removed, return before lock, Git, Docker, or
# Compose. Other receipts are ignored because STATE_SOURCE is exact, not globbed.
if [ "$COMPLETED_ONLY" = "true" ]; then
  echo "markerless B-to-B rollback retry was already completed"
  exit 0
fi

DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=rollback ./deploy/deployment_lock.sh acquire
release_lock() { ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true; }
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
verify_control_state_files

state_owner="$(stat -c '%u' "$CONTROL_STATE" 2>/dev/null || stat -f '%u' "$CONTROL_STATE")"
state_mode="$(stat -c '%a' "$CONTROL_STATE" 2>/dev/null || stat -f '%Lp' "$CONTROL_STATE")"
if [ -L "$CONTROL_STATE" ] || [ ! -f "$CONTROL_STATE" ] || [ "$state_owner" != "$(id -u)" ] || [ "$state_mode" != "600" ]; then echo "rollback control state is untrusted" >&2; exit 1; fi
field() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p" "$CONTROL_STATE"; }
STATE_COMPOSE_FILE="$(field compose_file)"
STATE_CONTROL_DIR="$(field control_dir)"
CONTROL_IMAGE_ID="$(field control_image_id)"
CONTROL_OVERRIDE="$(field control_override)"
STATE_TARGET_COMMIT="$(field target_commit)"
STATE_TARGET_IMAGE_ID="$(field target_image_id)"
TARGET_IMAGE_TAG="$(field target_image_tag)"
STATE_SHA256="$(field state_sha256)"
ATTEMPT_MODE="$(field recovery_intent_mode)"
INITIATING_ARTIFACT_PATH="$(field initiating_artifact_path)"
INITIATING_ARTIFACT_SHA256="$(field initiating_artifact_sha256)"
INITIATING_DATABASE_IDENTITY_SHA256="$(field initiating_database_identity_sha256)"
INITIATING_LOCK_TOKEN_SHA256="$(field initiating_lock_token_sha256)"
case "$ATTEMPT_MODE" in required|not-required) ;; *) echo "rollback control state recovery mode is invalid" >&2; exit 1 ;; esac
if [ -n "$EXPECTED_ROLLBACK_RECOVERY_INTENT_MODE" ] && [ "$ATTEMPT_MODE" != "$EXPECTED_ROLLBACK_RECOVERY_INTENT_MODE" ]; then echo "rollback control state recovery mode mismatch" >&2; exit 1; fi
if [ "$STATE_COMPOSE_FILE" != "$COMPOSE_FILE" ] || [ "$STATE_TARGET_COMMIT" != "$EXPECTED_ROLLBACK_TARGET_COMMIT" ] || [ "$STATE_TARGET_IMAGE_ID" != "$EXPECTED_ROLLBACK_TARGET_IMAGE_ID" ]; then echo "rollback control state target binding mismatch" >&2; exit 1; fi
for digest in "$STATE_SHA256" "$INITIATING_ARTIFACT_SHA256" "$INITIATING_DATABASE_IDENTITY_SHA256" "$INITIATING_LOCK_TOKEN_SHA256"; do
  case "$digest" in *[!0-9a-f]*) echo "rollback control state provenance is malformed" >&2; exit 1 ;; esac
  if [ "${#digest}" -ne 64 ]; then echo "rollback control state provenance is malformed" >&2; exit 1; fi
done
if [ "$STATE_CONTROL_DIR" != "$CONTROL_DIR" ]; then echo "rollback control directory binding mismatch" >&2; exit 1; fi
case "$CONTROL_DIR" in "$MARKER_ROOT"/rollback-control.*) ;; *) echo "rollback control directory is outside repair runtime" >&2; exit 1 ;; esac
if [ "$CONTROL_OVERRIDE" != "$CONTROL_DIR/compose-control.yml" ]; then echo "rollback control override path mismatch" >&2; exit 1; fi
case "$TARGET_IMAGE_TAG" in umanewsbot:rollback-target-*) ;; *) echo "rollback target tag is invalid" >&2; exit 1 ;; esac
if [ -e "$COMPLETED_CONTROL_STATE" ] || [ -L "$COMPLETED_CONTROL_STATE" ]; then
  python3 "$CONTROL_DIR/create-control-state.py" complete \
    --state-path "$CONTROL_STATE" \
    --completed-path "$COMPLETED_CONTROL_STATE" \
    --expected-state-sha256 "$STATE_SHA256" >/dev/null
  echo "markerless B-to-B rollback retry was already completed"
  exit 0
fi

MARKER="$MARKER_ROOT/restricted-recovery.json"
TRANSITION="$MARKER_ROOT/restricted-recovery.transition.json"
if [ "$ATTEMPT_MODE" = "not-required" ]; then
  for marker in "$MARKER" "$TRANSITION"; do
    if [ -e "$marker" ] || [ -L "$marker" ]; then echo "markerless rollback control state conflicts with restricted marker" >&2; exit 1; fi
  done
else
  if [ ! -e "$MARKER" ] && [ ! -L "$MARKER" ]; then echo "required rollback control state is missing restricted marker" >&2; exit 1; fi
fi
if [ "$(git rev-parse HEAD)" != "$STATE_TARGET_COMMIT" ]; then echo "HEAD differs from pinned rollback target" >&2; exit 1; fi
if [ "$(docker image inspect --format '{{.Id}}' umanewsbot:prod)" != "$STATE_TARGET_IMAGE_ID" ] || [ "$(docker image inspect --format '{{.Id}}' "$TARGET_IMAGE_TAG")" != "$STATE_TARGET_IMAGE_ID" ]; then echo "rollback target image drifted" >&2; exit 1; fi
if [ "$(docker image inspect --format '{{.Id}}' "$CONTROL_IMAGE_ID")" != "$CONTROL_IMAGE_ID" ]; then echo "rollback control image drifted" >&2; exit 1; fi

control_dir_owner="$(stat -c '%u' "$CONTROL_DIR" 2>/dev/null || stat -f '%u' "$CONTROL_DIR")"
control_dir_mode="$(stat -c '%a' "$CONTROL_DIR" 2>/dev/null || stat -f '%Lp' "$CONTROL_DIR")"
if [ -L "$CONTROL_DIR" ] || [ ! -d "$CONTROL_DIR" ] || [ "$control_dir_owner" != "$(id -u)" ] || [ "$control_dir_mode" != "700" ]; then echo "rollback control directory is untrusted" >&2; exit 1; fi
CONTROL_PREFLIGHT="$CONTROL_DIR/preflight.sh"
CONTROL_APPLICATION="$CONTROL_DIR/application-release.sh"
CONTROL_RELEASE_TASKS="$CONTROL_DIR/release-tasks.sh"
for control_file in "$CONTROL_PREFLIGHT" "$CONTROL_APPLICATION" "$CONTROL_RELEASE_TASKS" "$CONTROL_DIR/resume-rollback-release.sh"; do
  control_owner="$(stat -c '%u' "$control_file" 2>/dev/null || stat -f '%u' "$control_file")"
  control_mode="$(stat -c '%a' "$control_file" 2>/dev/null || stat -f '%Lp' "$control_file")"
  if [ -L "$control_file" ] || [ ! -f "$control_file" ] || [ "$control_owner" != "$(id -u)" ] || [ "$control_mode" != "500" ]; then echo "rollback control script is untrusted" >&2; exit 1; fi
done
override_owner="$(stat -c '%u' "$CONTROL_OVERRIDE" 2>/dev/null || stat -f '%u' "$CONTROL_OVERRIDE")"
override_mode="$(stat -c '%a' "$CONTROL_OVERRIDE" 2>/dev/null || stat -f '%Lp' "$CONTROL_OVERRIDE")"
if [ -L "$CONTROL_OVERRIDE" ] || [ ! -f "$CONTROL_OVERRIDE" ] || [ "$override_owner" != "$(id -u)" ] || [ "$override_mode" != "400" ]; then echo "rollback control override is untrusted" >&2; exit 1; fi

case "$INITIATING_ARTIFACT_PATH" in "$MARKER_ROOT"/preflight/*/preflight.json) ;; *) echo "initiating rollback artifact path is invalid" >&2; exit 1 ;; esac
set -- -f "$COMPOSE_FILE" -f "$CONTROL_OVERRIDE"
if [ "$ATTEMPT_MODE" = "not-required" ]; then
  ./deploy/docker/compose-wrapper.sh "$@" run --rm --no-deps \
    web python manage.py check_production_database_vendor
  ./deploy/docker/compose-wrapper.sh "$@" run --rm --no-deps \
    -v "$MARKER_ROOT:$MARKER_ROOT:ro" \
    web python manage.py verify_historical_calendar_release_b_handoff \
    --artifact-only \
    --artifact-path="$INITIATING_ARTIFACT_PATH" \
    --artifact-sha256="$INITIATING_ARTIFACT_SHA256" \
    --candidate-commit="$STATE_TARGET_COMMIT" \
    --candidate-image-id="$STATE_TARGET_IMAGE_ID" \
    --database-identity-sha256="$INITIATING_DATABASE_IDENTITY_SHA256" \
    --compose-file="$COMPOSE_FILE" \
    --deployment-lock-token-sha256="$INITIATING_LOCK_TOKEN_SHA256"
else
  ./deploy/docker/compose-wrapper.sh "$@" run --rm --no-deps \
    -v "$MARKER_ROOT:$MARKER_ROOT:ro" \
    web python manage.py verify_historical_calendar_restricted_recovery \
    --marker-path="$MARKER" \
    --artifact-sha256="$INITIATING_ARTIFACT_SHA256" \
    --candidate-commit="$STATE_TARGET_COMMIT" \
    --candidate-image-id="$STATE_TARGET_IMAGE_ID"
fi
if [ "$ATTEMPT_MODE" = "required" ]; then
  RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="$INITIATING_ARTIFACT_SHA256"
  export RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
else
  unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256
fi

if [ -L "$MARKER_ROOT/preflight" ]; then echo "preflight root must not be a symlink" >&2; exit 1; fi
umask 077
mkdir -p "$MARKER_ROOT/preflight"
chmod 700 "$MARKER_ROOT" "$MARKER_ROOT/preflight"
RELEASE_B_PREFLIGHT_DIR="$(mktemp -d "$MARKER_ROOT/preflight/retry.XXXXXXXX")"
RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_DIR/preflight.json"
export RELEASE_B_PREFLIGHT_ARTIFACT_PATH
unset EXPECTED_PRODUCTION_DB_IDENTITY_SHA256
if [ "$ATTEMPT_MODE" = "not-required" ]; then
  PREFLIGHT_ACTION=rollback
  EXPECTED_LEAF=stable.0073_lifecycle_enforce_registry
else
  PREFLIGHT_ACTION=forward-resume
  EXPECTED_LEAF=""
fi
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CANDIDATE_COMMIT="$STATE_TARGET_COMMIT" \
  UMANEWS_ROOT_DIR="$ROOT_DIR" RELEASE_B_BINDING_IMAGE_NAME="$TARGET_IMAGE_TAG" \
  RELEASE_CONTROL_COMPOSE_OVERRIDE="$CONTROL_OVERRIDE" RELEASE_B_PREFLIGHT_ACTION="$PREFLIGHT_ACTION" \
  RELEASE_B_EXPECTED_MIGRATION_LEAF_SET="$EXPECTED_LEAF" RESTRICTED_RECOVERY_MARKER_PATH="$MARKER" \
  "$CONTROL_PREFLIGHT"
RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
RESTRICTED_RECOVERY_ATTEMPT_MODE="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
EXPECTED_CANDIDATE_COMMIT="$STATE_TARGET_COMMIT"
EXPECTED_CANDIDATE_IMAGE_ID="$STATE_TARGET_IMAGE_ID"
export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RESTRICTED_RECOVERY_ATTEMPT_MODE EXPECTED_CANDIDATE_COMMIT EXPECTED_CANDIDATE_IMAGE_ID
if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ] || [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ] || [ "$RESTRICTED_RECOVERY_ATTEMPT_MODE" != "$ATTEMPT_MODE" ]; then echo "fresh rollback handoff is invalid" >&2; exit 1; fi

if [ "$ATTEMPT_MODE" = required ]; then RESTRICTED_ACTIVE=true; else RESTRICTED_ACTIVE=false; fi
COMPOSE_FILE="$COMPOSE_FILE" RELEASE_ACTION=rollback UMANEWS_ROOT_DIR="$ROOT_DIR" \
  RELEASE_TASK_WRAPPER_PATH="$CONTROL_RELEASE_TASKS" RELEASE_TARGET_IMAGE_TAG="$TARGET_IMAGE_TAG" \
  RELEASE_CONTROL_COMPOSE_OVERRIDE="$CONTROL_OVERRIDE" RESTRICTED_RECOVERY_ACTIVE="$RESTRICTED_ACTIVE" \
  RESTRICTED_RECOVERY_MARKER_PATH="$MARKER" "$CONTROL_APPLICATION"
python3 "$CONTROL_DIR/create-control-state.py" complete \
  --state-path "$CONTROL_STATE" \
  --completed-path "$COMPLETED_CONTROL_STATE" \
  --expected-state-sha256 "$STATE_SHA256" >/dev/null
echo "pinned B-to-B rollback retry completed"
