#!/bin/sh
# Promote exactly the reviewed lifecycle canary controls while runtime is off.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT_DIR"

COMPOSE="$ROOT_DIR/deploy/docker/compose-wrapper.sh"
LOCK="$ROOT_DIR/deploy/deployment_lock.sh"
VERIFY="$ROOT_DIR/deploy/verify_lifecycle_runtime_coherence.sh"

fail() { echo "lifecycle enforce canary promotion: $*" >&2; exit 1; }
require() { eval "value=\${$1:-}"; [ -n "$value" ] || fail "$1 is required"; }

for name in COMPOSE_FILE EXPECTED_COMPOSE_PROJECT EXPECTED_RELEASE_DIR \
  EXPECTED_IMAGE_ID EXPECTED_RELEASE_COMMIT EXPECTED_CANARY_EVENT_IDS \
  MANIFEST_FILE MANIFEST_SHA256 DEPLOYMENT_LOCK_TOKEN; do
  require "$name"
done

case "$COMPOSE_FILE" in docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;; *) fail "COMPOSE_FILE is not allowlisted" ;; esac
case "$EXPECTED_COMPOSE_PROJECT" in *[!a-z0-9_-]*|"") fail "invalid expected Compose project" ;; esac
case "$EXPECTED_IMAGE_ID" in -*|*[!A-Za-z0-9:._-]*|"") fail "invalid expected image ID" ;; esac
[ "$EXPECTED_CANARY_EVENT_IDS" = "186,187" ] || fail "EXPECTED_CANARY_EVENT_IDS must be exactly 186,187"
case "$EXPECTED_RELEASE_COMMIT" in *[!0-9a-f]*|"") fail "expected commit must be a lowercase 40-character OID" ;; esac
[ "${#EXPECTED_RELEASE_COMMIT}" -eq 40 ] || fail "expected commit must be a lowercase 40-character OID"
case "$MANIFEST_SHA256" in *[!0-9a-f]*|"") fail "MANIFEST_SHA256 must be lowercase SHA-256" ;; esac
[ "${#MANIFEST_SHA256}" -eq 64 ] || fail "MANIFEST_SHA256 must be lowercase SHA-256"
case "$EXPECTED_RELEASE_DIR" in /*) ;; *) fail "EXPECTED_RELEASE_DIR must be absolute" ;; esac
physical_expected_release="$(CDPATH= cd -- "$EXPECTED_RELEASE_DIR" 2>/dev/null && pwd -P)" || fail "release directory cannot be resolved"
[ "$ROOT_DIR" = "$physical_expected_release" ] || fail "this checkout is not the expected physical release directory"

manifest_snapshot="$(mktemp "${TMPDIR:-/tmp}/umanews-enforce-canary-manifest.XXXXXX")" || fail "cannot create manifest snapshot"
chmod 600 "$manifest_snapshot"
cleanup_snapshot() { rm -f "$manifest_snapshot"; }
trap cleanup_snapshot EXIT HUP INT TERM

python3 - "$MANIFEST_FILE" "$MANIFEST_SHA256" "$manifest_snapshot" <<'PY' \
  || fail "manifest no-follow/size/SHA validation failed"
import hashlib
import os
import stat
import sys

source, expected_sha, destination = sys.argv[1:]
flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
fd = os.open(source, flags)
try:
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > 1024 * 1024:
        raise SystemExit(1)
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, 1024 * 1024 + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > 1024 * 1024:
            raise SystemExit(1)
    data = b"".join(chunks)
    if len(data) != metadata.st_size or hashlib.sha256(data).hexdigest() != expected_sha:
        raise SystemExit(1)
finally:
    os.close(fd)

out_flags = os.O_WRONLY | os.O_TRUNC
if hasattr(os, "O_NOFOLLOW"):
    out_flags |= os.O_NOFOLLOW
out_fd = os.open(destination, out_flags)
try:
    out_meta = os.fstat(out_fd)
    if not stat.S_ISREG(out_meta.st_mode):
        raise SystemExit(1)
    view = memoryview(data)
    while view:
        written = os.write(out_fd, view)
        if written <= 0:
            raise SystemExit(1)
        view = view[written:]
    os.fsync(out_fd)
finally:
    os.close(out_fd)
PY

verify_off_runtime() {
  EXPECTED_BEAT_STATE=running \
  EXPECTED_LIFECYCLE_ENABLED=false \
  EXPECTED_LIFECYCLE_MODE=off \
  EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256= \
  EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS= \
  EXPECTED_COMPOSE_PROJECT="$EXPECTED_COMPOSE_PROJECT" \
  EXPECTED_RELEASE_DIR="$EXPECTED_RELEASE_DIR" \
  EXPECTED_IMAGE_ID="$EXPECTED_IMAGE_ID" \
  EXPECTED_RELEASE_COMMIT="$EXPECTED_RELEASE_COMMIT" \
  COMPOSE_FILE="$COMPOSE_FILE" "$VERIFY"
}

compose_exec_apply() {
  "$COMPOSE" -f "$COMPOSE_FILE" \
    --project-directory "$EXPECTED_RELEASE_DIR" \
    --project-name "$EXPECTED_COMPOSE_PROJECT" \
    exec -T web python manage.py promote_race_event_lifecycle_enforce_canary \
    --manifest-stdin --manifest-sha256 "$MANIFEST_SHA256" \
    --expected-commit "$EXPECTED_RELEASE_COMMIT" \
    --expected-event-ids "$EXPECTED_CANARY_EVENT_IDS" \
    --apply --confirm-enforce-canary < "$manifest_snapshot"
}

lock_held=0
completed=0

on_exit() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [ "$lock_held" -eq 1 ]; then
    "$LOCK" release || status=1
  fi
  cleanup_snapshot
  if [ "$status" -eq 0 ] && [ "$completed" -ne 1 ]; then status=1; fi
  exit "$status"
}
export DEPLOYMENT_LOCK_ACTION=lifecycle-enforce-canary-promotion
export COMPOSE_FILE
"$LOCK" acquire
lock_held=1
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

verify_off_runtime
compose_exec_apply
verify_off_runtime
completed=1
echo "lifecycle enforce canary promotion completed"
