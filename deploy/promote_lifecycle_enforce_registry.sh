#!/bin/sh
# Disarm the legacy lifecycle canary only for the first registry, then promote
# one reviewed registry while the resident runtime remains false/off. Successor
# registries are predecessor-bound and never touch legacy canary evidence.
# This script never owns migrations
# or collectstatic; schema deployment remains the existing single release task.
# Ordering contract: backup_db.sh completes and is validated before any env
# root clear, legacy disarm, or registry database write.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT_DIR"

COMPOSE="$ROOT_DIR/deploy/docker/compose-wrapper.sh"
LOCK="$ROOT_DIR/deploy/deployment_lock.sh"
VERIFY="$ROOT_DIR/deploy/verify_lifecycle_runtime_coherence.sh"
CANONICAL_ENV_FILE="/opt/umanewsbot/.env"

fail() { echo "lifecycle enforce registry promotion: $*" >&2; exit 1; }
require() { eval "value=\${$1:-}"; [ -n "$value" ] || fail "$1 is required"; }

for name in ACTIVE_RELEASE_ENV_FILE COMPOSE_FILE EXPECTED_COMPOSE_PROJECT \
  EXPECTED_RELEASE_DIR EXPECTED_IMAGE_ID EXPECTED_RELEASE_COMMIT \
  REGISTRY_FILE REGISTRY_SHA256 DEPLOYMENT_LOCK_TOKEN; do
  require "$name"
done
case "$COMPOSE_FILE" in docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;; *) fail "COMPOSE_FILE is not allowlisted" ;; esac
case "$EXPECTED_RELEASE_COMMIT" in *[!0-9a-f]*|"") fail "expected commit must be lowercase 40-hex" ;; esac
[ "${#EXPECTED_RELEASE_COMMIT}" -eq 40 ] || fail "expected commit must be lowercase 40-hex"
case "$REGISTRY_SHA256" in *[!0-9a-f]*|"") fail "registry SHA must be lowercase SHA-256" ;; esac
[ "${#REGISTRY_SHA256}" -eq 64 ] || fail "registry SHA must be lowercase SHA-256"
case "$EXPECTED_RELEASE_DIR" in /*) ;; *) fail "EXPECTED_RELEASE_DIR must be absolute" ;; esac
physical_release="$(CDPATH= cd -- "$EXPECTED_RELEASE_DIR" 2>/dev/null && pwd -P)" || fail "release directory cannot be resolved"
[ "$ROOT_DIR" = "$physical_release" ] || fail "checkout is not the expected physical release"
[ "$ACTIVE_RELEASE_ENV_FILE" = "$EXPECTED_RELEASE_DIR/.env" ] || fail "active env path mismatch"

snapshot_artifact() {
  source="$1" expected="$2" destination="$3"
  python3 - "$source" "$expected" "$destination" <<'PY'
import hashlib
import os
import stat
import sys

source, expected, destination = sys.argv[1:]
fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
try:
    meta = os.fstat(fd)
    if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= 16 * 1024 * 1024:
        raise SystemExit(1)
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, 16 * 1024 * 1024 + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > 16 * 1024 * 1024:
            raise SystemExit(1)
    data = b"".join(chunks)
    if len(data) != meta.st_size or hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(1)
finally:
    os.close(fd)
out = os.open(destination, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0))
try:
    os.write(out, data)
    os.fsync(out)
finally:
    os.close(out)
PY
}

legacy_snapshot=""
registry_snapshot="$(mktemp "${TMPDIR:-/tmp}/umanews-lifecycle-registry.XXXXXX")"
chmod 600 "$registry_snapshot"
snapshot_artifact "$REGISTRY_FILE" "$REGISTRY_SHA256" "$registry_snapshot" \
  || fail "registry artifact validation failed"
registry_metadata="$(python3 "$ROOT_DIR/deploy/parse_lifecycle_registry_artifact_metadata.py" \
  < "$registry_snapshot")" || fail "registry artifact predecessor metadata is invalid"
set -- $registry_metadata
registry_member_count="${1:-}"
registry_kind="${2:-}"
registry_predecessor="${3:-}"
case "$registry_member_count" in *[!0-9]*|""|0|0?*) fail "registry member count is invalid" ;; esac
case "$registry_kind" in
  first)
    [ "$#" -eq 2 ] || fail "first registry metadata is contradictory"
    for name in LEGACY_MANIFEST_FILE LEGACY_MANIFEST_SHA256 \
      LEGACY_CANARY_APPROVED_COMMIT EXPECTED_CANARY_EVENT_IDS; do
      require "$name"
    done
    case "$LEGACY_MANIFEST_SHA256" in *[!0-9a-f]*|"") fail "legacy artifact SHA must be lowercase SHA-256" ;; esac
    [ "${#LEGACY_MANIFEST_SHA256}" -eq 64 ] || fail "legacy artifact SHA must be lowercase SHA-256"
    case "$LEGACY_CANARY_APPROVED_COMMIT" in *[!0-9a-f]*|"") fail "legacy approved commit must be lowercase 40-hex" ;; esac
    [ "${#LEGACY_CANARY_APPROVED_COMMIT}" -eq 40 ] || fail "legacy approved commit must be lowercase 40-hex"
    [ "$EXPECTED_CANARY_EVENT_IDS" = "186,187" ] || fail "legacy event IDs must be exactly 186,187"
    legacy_snapshot="$(mktemp "${TMPDIR:-/tmp}/umanews-legacy-lifecycle.XXXXXX")"
    chmod 600 "$legacy_snapshot"
    snapshot_artifact "$LEGACY_MANIFEST_FILE" "$LEGACY_MANIFEST_SHA256" "$legacy_snapshot" \
      || fail "legacy artifact validation failed"
    ;;
  successor)
    [ "$#" -eq 3 ] || fail "successor registry metadata is contradictory"
    case "$registry_predecessor" in *[!0-9a-f]*|"") fail "successor predecessor must be lowercase SHA-256" ;; esac
    [ "${#registry_predecessor}" -eq 64 ] || fail "successor predecessor must be lowercase SHA-256"
    for name in LEGACY_MANIFEST_FILE LEGACY_MANIFEST_SHA256 \
      LEGACY_CANARY_APPROVED_COMMIT EXPECTED_CANARY_EVENT_IDS; do
      eval "legacy_value=\${$name:-}"
      [ -z "$legacy_value" ] || fail "successor registry forbids legacy parameter $name"
    done
    ;;
  *) fail "registry artifact kind is invalid" ;;
esac

read_key() { awk -F= -v wanted="$2" '$1==wanted{print substr($0,index($0,"=")+1)}' "$1"; }
rewrite_off() {
  file="$1"
  [ -f "$file" ] && [ ! -L "$file" ] || return 1
  tmp="$(mktemp "${file}.lifecycle-registry.XXXXXX")" || return 1
  chmod 600 "$tmp"
  awk '
    /^RACE_EVENT_LIFECYCLE_ENABLED=/{print "RACE_EVENT_LIFECYCLE_ENABLED=false"; next}
    /^RACE_EVENT_LIFECYCLE_MODE=/{print "RACE_EVENT_LIFECYCLE_MODE=off"; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256="; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS="; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256="; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256="; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT="; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID="; next}
    {print}
  ' "$file" > "$tmp" || { rm -f "$tmp"; return 1; }
  mv -f "$tmp" "$file" && chmod 600 "$file"
}

compose_mutation() {
  "$COMPOSE" -f "$COMPOSE_FILE" --project-directory "$EXPECTED_RELEASE_DIR" \
    --project-name "$EXPECTED_COMPOSE_PROJECT" "$@"
}
verify_off() {
  EXPECTED_BEAT_STATE=stopped EXPECTED_LIFECYCLE_ENABLED=false \
  EXPECTED_LIFECYCLE_MODE=off EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256= \
  EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS= \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_SHA256= \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256= \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT= \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID= \
  EXPECTED_COMPOSE_PROJECT="$EXPECTED_COMPOSE_PROJECT" EXPECTED_RELEASE_DIR="$EXPECTED_RELEASE_DIR" \
  EXPECTED_IMAGE_ID="$EXPECTED_IMAGE_ID" EXPECTED_RELEASE_COMMIT="$EXPECTED_RELEASE_COMMIT" \
  COMPOSE_FILE="$COMPOSE_FILE" "$VERIFY"
}

probe_worker_node() {
  cid="$(compose_mutation ps -q worker)" || return 1
  [ -n "$cid" ] || return 1
  case "$cid" in *[!A-Za-z0-9_.-]*|"") return 1 ;; esac
  state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}}' "$cid")" || return 1
  [ "$state" = "true false" ] || return 1
  node="$(docker inspect --format '{{.Config.Hostname}}' "$cid")" || return 1
  case "$node" in *[!A-Za-z0-9._-]*|"") return 1 ;; esac
  printf '%s\n' "$node"
}

lock_held=0
completed=0
quiesced=0
recovery_required=0
keep_lock=0

recover_off() {
  set +e
  recovery_rc=0
  compose_mutation stop beat worker >/dev/null 2>&1 || recovery_rc=1
  rewrite_off "$CANONICAL_ENV_FILE" || recovery_rc=1
  rewrite_off "$ACTIVE_RELEASE_ENV_FILE" || recovery_rc=1
  if [ "$recovery_rc" -eq 0 ]; then
    compose_mutation up -d --no-deps --force-recreate web worker >/dev/null 2>&1 \
      || recovery_rc=1
  fi
  if [ "$recovery_rc" -eq 0 ]; then
    verify_off || recovery_rc=1
  fi
  if [ "$recovery_rc" -ne 0 ]; then
    # Never permit an old or incoherent worker to run after a failed recovery.
    # Preserve the shared lock and frozen artifact snapshots for an audited
    # manual recovery instead of claiming that false/off was reached.
    compose_mutation stop beat worker >/dev/null 2>&1 || true
    keep_lock=1
    echo "lifecycle enforce registry promotion: recovery failed; Beat/worker stop attempted, deployment lock and evidence retained; manual recovery required" >&2
    set -e
    return 1
  fi
  set -e
  return 0
}

on_exit() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [ "$status" -ne 0 ] && [ "$lock_held" -eq 1 ] && [ "$recovery_required" -eq 1 ]; then
    recover_off || status=1
  elif [ "$status" -ne 0 ] && [ "$lock_held" -eq 1 ] && [ "$quiesced" -eq 1 ]; then
    # No backup-protected database/env mutation has begun. Restore the
    # previously running scheduler/consumer without touching lifecycle roots.
    if ! compose_mutation up -d --no-deps worker beat >/dev/null 2>&1; then
      status=1
      keep_lock=1
      compose_mutation stop beat worker >/dev/null 2>&1 || true
      echo "lifecycle enforce registry promotion: pre-backup service restore failed; deployment lock and evidence retained; manual recovery required" >&2
    fi
  fi
  if [ "$lock_held" -eq 1 ] && [ "$keep_lock" -eq 0 ]; then
    "$LOCK" release || { status=1; keep_lock=1; }
  fi
  if [ "$keep_lock" -eq 0 ]; then
    [ -z "$legacy_snapshot" ] || rm -f "$legacy_snapshot"
    rm -f "$registry_snapshot"
  else
    echo "lifecycle enforce registry promotion: retained evidence legacy=$legacy_snapshot registry=$registry_snapshot" >&2
  fi
  if [ "$status" -eq 0 ] && [ "$completed" -ne 1 ]; then status=1; fi
  exit "$status"
}
export DEPLOYMENT_LOCK_ACTION=lifecycle-enforce-registry-promotion
export COMPOSE_FILE
"$LOCK" acquire
lock_held=1
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Quiesce the only lifecycle scheduler/consumer before taking the rollback
# snapshot.  A successful backup must therefore remain stable until promotion.
worker_node="$(probe_worker_node)" || fail "worker admission probe failed"
quiesced=1
compose_mutation stop beat
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CELERY_WORKERS="$worker_node" \
  "$ROOT_DIR/deploy/wait_for_celery_drain.sh"
compose_mutation stop worker

# The write-before-write recovery point is mandatory.  backup_db.sh currently
# emits a gzip SQL dump; validate that real format, while an externally upgraded
# custom-format helper is validated with pg_restore -l.
backup_output="$(BACKUP_TARGET=local "$ROOT_DIR/deploy/backup_db.sh")"
backup_file="$(printf '%s\n' "$backup_output" | sed -n 's/^Backup created: //p' | tail -n 1)"
[ -n "$backup_file" ] && [ -s "$backup_file" ] || fail "database backup is missing or empty"
chmod 600 "$backup_file"
case "$backup_file" in
  *.dump) pg_restore -l "$backup_file" >/dev/null || fail "database backup catalog validation failed" ;;
  *.gz) gzip -t "$backup_file" || fail "database backup gzip validation failed" ;;
  *) fail "database backup format is not reviewed" ;;
esac
if command -v sha256sum >/dev/null 2>&1; then sha256sum "$backup_file" >/dev/null; else shasum -a 256 "$backup_file" >/dev/null; fi

stamp="$(date -u '+%Y%m%dT%H%M%SZ').$$"
cp -p "$CANONICAL_ENV_FILE" "${CANONICAL_ENV_FILE}.lifecycle-registry-backup.$stamp"
cp -p "$ACTIVE_RELEASE_ENV_FILE" "${ACTIVE_RELEASE_ENV_FILE}.lifecycle-registry-backup.$stamp"
recovery_required=1

rewrite_off "$CANONICAL_ENV_FILE"
rewrite_off "$ACTIVE_RELEASE_ENV_FILE"
compose_mutation up -d --no-deps --force-recreate web worker
verify_off

if [ "$registry_kind" = "first" ]; then
  compose_mutation exec -T web python manage.py verify_race_event_lifecycle_enforce_canary \
    --manifest-stdin --manifest-sha256 "$LEGACY_MANIFEST_SHA256" \
    --expected-commit "$LEGACY_CANARY_APPROVED_COMMIT" --expected-event-ids "$EXPECTED_CANARY_EVENT_IDS" \
    --phase inactive --disarm < "$legacy_snapshot"
fi

promotion_attempt=0
promotion_attempt_limit=$(((registry_member_count + 99) / 100 + 1))
# Zero means this process has not observed a prior batch.  The canonical first
# result may resume a registry partially committed by an earlier attempt.
promotion_previous_remaining=0
while :; do
  promotion_attempt=$((promotion_attempt + 1))
  [ "$promotion_attempt" -le "$promotion_attempt_limit" ] \
    || fail "registry promotion did not converge within bounded batches"
  promotion_output="$(compose_mutation exec -T web python manage.py promote_race_event_lifecycle_enforce_registry \
    --manifest-stdin --manifest-sha256 "$REGISTRY_SHA256" \
    --expected-commit "$EXPECTED_RELEASE_COMMIT" --apply < "$registry_snapshot")" \
    || fail "registry promotion batch failed"
  promotion_result="$(printf '%s\n' "$promotion_output" \
    | python3 "$ROOT_DIR/deploy/parse_lifecycle_registry_promotion_result.py" \
      --expected-total "$registry_member_count" \
      --previous-remaining "$promotion_previous_remaining")" \
    || fail "registry promotion output is unknown or contradictory"
  promotion_outcome="${promotion_result%% *}"
  promotion_remaining="${promotion_result#* }"
  case "$promotion_outcome" in partial|applied|replay) ;; *) fail "registry promotion parser returned an unknown outcome" ;; esac
  case "$promotion_remaining" in *[!0-9]*|"") fail "registry promotion parser returned an invalid remaining count" ;; esac
  promotion_previous_remaining="$promotion_remaining"
  [ "$promotion_outcome" = "partial" ] || break
done
compose_mutation exec -T web python manage.py verify_race_event_lifecycle_enforce_registry \
  --manifest-stdin --manifest-sha256 "$REGISTRY_SHA256" \
  --expected-commit "$EXPECTED_RELEASE_COMMIT" --expected-state inactive < "$registry_snapshot"
verify_off

completed=1
echo "lifecycle enforce registry promoted inactive; runtime remains false/off and Beat stopped"
