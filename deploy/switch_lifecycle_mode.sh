#!/bin/sh
# Switch lifecycle among reviewed false/off, true/shadow and manifest-bound
# true/enforce modes.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT_DIR"

COMPOSE="$ROOT_DIR/deploy/docker/compose-wrapper.sh"
LOCK="$ROOT_DIR/deploy/deployment_lock.sh"
VERIFY="$ROOT_DIR/deploy/verify_lifecycle_runtime_coherence.sh"
HEALTH="$ROOT_DIR/deploy/wait_for_compose_service_healthy.sh"
CANONICAL_ENV_FILE="/opt/umanewsbot/.env"
manifest_snapshot=""

fail() { echo "lifecycle mode switch: $*" >&2; exit 1; }
require() { eval "value=\${$1:-}"; [ -n "$value" ] || fail "$1 is required"; }

for name in ACTIVE_RELEASE_ENV_FILE COMPOSE_FILE \
  EXPECTED_COMPOSE_PROJECT EXPECTED_RELEASE_DIR EXPECTED_IMAGE_ID \
  EXPECTED_RELEASE_COMMIT TARGET_LIFECYCLE_ENABLED TARGET_LIFECYCLE_MODE \
  DEPLOYMENT_LOCK_TOKEN; do
  require "$name"
done

case "$COMPOSE_FILE" in docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;; *) fail "COMPOSE_FILE is not allowlisted" ;; esac
case "$EXPECTED_COMPOSE_PROJECT" in *[!a-z0-9_-]*|"") fail "invalid expected Compose project" ;; esac
case "$EXPECTED_IMAGE_ID" in -*|*[!A-Za-z0-9:._-]*|"") fail "invalid expected image ID" ;; esac
case "$EXPECTED_RELEASE_DIR" in /*) ;; *) fail "EXPECTED_RELEASE_DIR must be absolute" ;; esac
physical_expected_release="$(CDPATH= cd -- "$EXPECTED_RELEASE_DIR" 2>/dev/null && pwd -P)" || fail "release directory cannot be resolved"
[ "$ROOT_DIR" = "$physical_expected_release" ] || fail "this checkout is not the expected physical release directory"
[ "$ACTIVE_RELEASE_ENV_FILE" = "$EXPECTED_RELEASE_DIR/.env" ] || fail "active release env path does not match release directory"
case "$CANONICAL_ENV_FILE" in /*) ;; *) fail "canonical env path must be absolute" ;; esac
canonical_parent="$(dirname "$CANONICAL_ENV_FILE")"
(CDPATH= cd -- "$canonical_parent" 2>/dev/null && pwd -P >/dev/null) || fail "canonical env parent cannot be resolved"
[ "$CANONICAL_ENV_FILE" != "$ACTIVE_RELEASE_ENV_FILE" ] || fail "canonical and active env files must differ"
case "$EXPECTED_RELEASE_COMMIT" in *[!0-9a-f]*|"") fail "release commit must be a lowercase 40-character OID" ;; esac
[ "${#EXPECTED_RELEASE_COMMIT}" -eq 40 ] || fail "release commit must be a lowercase 40-character OID"
case "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" in false/off|true/shadow|true/enforce) ;; *) fail "only false/off, true/shadow and true/enforce are supported" ;; esac

canary_sha=""
canary_ids=""
registry_sha=""
registry_membership_sha=""
registry_member_count=""
registry_activation_id=""
enforce_root_kind=""
if [ "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" = "true/enforce" ]; then
  if [ -n "${REGISTRY_FILE:-}${REGISTRY_SHA256:-}" ]; then
    enforce_root_kind="registry"
    for name in REGISTRY_FILE REGISTRY_SHA256 EXPECTED_REGISTRY_MEMBERSHIP_SHA256 \
      EXPECTED_REGISTRY_MEMBER_COUNT; do require "$name"; done
    [ -z "${EXPECTED_REGISTRY_ACTIVATION_ID:-}" ] \
      || fail "registry activation ID is generated inside the held deployment lock"
    for value in "$REGISTRY_SHA256" "$EXPECTED_REGISTRY_MEMBERSHIP_SHA256"; do
      case "$value" in *[!0-9a-f]*|"") fail "registry hashes must be lowercase SHA-256" ;; esac
      [ "${#value}" -eq 64 ] || fail "registry hashes must be lowercase SHA-256"
    done
    case "$EXPECTED_REGISTRY_MEMBER_COUNT" in *[!0-9]*|""|0|0?*) fail "EXPECTED_REGISTRY_MEMBER_COUNT must be positive" ;; esac
    registry_sha="$REGISTRY_SHA256"
    registry_membership_sha="$EXPECTED_REGISTRY_MEMBERSHIP_SHA256"
    registry_member_count="$EXPECTED_REGISTRY_MEMBER_COUNT"
    artifact_file="$REGISTRY_FILE"
    artifact_sha="$REGISTRY_SHA256"
  else
    enforce_root_kind="canary"
    for name in MANIFEST_FILE MANIFEST_SHA256 EXPECTED_CANARY_EVENT_IDS; do require "$name"; done
    [ "$EXPECTED_CANARY_EVENT_IDS" = "186,187" ] || fail "EXPECTED_CANARY_EVENT_IDS must be exactly 186,187"
    case "$MANIFEST_SHA256" in *[!0-9a-f]*|"") fail "MANIFEST_SHA256 must be lowercase SHA-256" ;; esac
    [ "${#MANIFEST_SHA256}" -eq 64 ] || fail "MANIFEST_SHA256 must be lowercase SHA-256"
    canary_sha="$MANIFEST_SHA256"
    canary_ids="$EXPECTED_CANARY_EVENT_IDS"
    artifact_file="$MANIFEST_FILE"
    artifact_sha="$MANIFEST_SHA256"
  fi

  manifest_snapshot="$(mktemp "${TMPDIR:-/tmp}/umanews-enforce-artifact.XXXXXX")" || fail "cannot create artifact snapshot"
  chmod 600 "$manifest_snapshot"
  cleanup_early_manifest() { rm -f "$manifest_snapshot"; }
  trap cleanup_early_manifest EXIT HUP INT TERM
  python3 - "$artifact_file" "$artifact_sha" "$manifest_snapshot" <<'PY' \
    || fail "artifact no-follow/size/SHA validation failed"
import hashlib
import os
import stat
import sys

source, expected_sha, destination = sys.argv[1:]
flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(source, flags)
try:
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > 16 * 1024 * 1024:
        raise SystemExit(1)
    data = bytearray()
    while len(data) <= 16 * 1024 * 1024:
        chunk = os.read(fd, min(65536, 16 * 1024 * 1024 + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    raw = bytes(data)
    if len(raw) != metadata.st_size or len(raw) > 16 * 1024 * 1024:
        raise SystemExit(1)
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise SystemExit(1)
finally:
    os.close(fd)

out_fd = os.open(destination, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0))
try:
    view = memoryview(raw)
    while view:
        written = os.write(out_fd, view)
        if written <= 0:
            raise SystemExit(1)
        view = view[written:]
    os.fsync(out_fd)
finally:
    os.close(out_fd)
PY
  if [ "$enforce_root_kind" = "registry" ]; then
    validate_registry_artifact_roots() {
      python3 - "$manifest_snapshot" "$registry_membership_sha" "$registry_member_count" <<'PY'
import json
import re
import sys

path, expected_membership, expected_count = sys.argv[1:]
with open(path, "rb") as stream:
    value = json.load(stream)
actual_membership = value.get("membership_sha256")
actual_count = value.get("member_count")
if not isinstance(actual_membership, str) or re.fullmatch(r"[0-9a-f]{64}", actual_membership) is None:
    raise SystemExit(1)
if type(actual_count) is not int or actual_count <= 0:
    raise SystemExit(1)
if actual_membership != expected_membership or str(actual_count) != expected_count:
    raise SystemExit(1)
PY
    }
    validate_registry_artifact_roots \
      || fail "caller registry membership root does not match frozen artifact"
  fi
fi

lock_held=0
recovery_required=0
completed=0
keep_lock=0

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null
}

validate_env_file() {
  file="$1"
  [ ! -L "$file" ] || { echo "lifecycle mode switch: $file must not be a symlink" >&2; return 1; }
  [ -f "$file" ] || { echo "lifecycle mode switch: $file must be a regular file" >&2; return 1; }
  foreign="$(find "$file" ! -user "$(id -un)" -print 2>/dev/null)" || { echo "lifecycle mode switch: cannot verify owner for $file" >&2; return 1; }
  [ -z "$foreign" ] || { echo "lifecycle mode switch: $file is not owned by the current user" >&2; return 1; }
  [ "$(file_mode "$file")" = "600" ] || { echo "lifecycle mode switch: $file must have mode 0600" >&2; return 1; }
  enabled_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENABLED"{n++} END{print n+0}' "$file")"
  mode_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_MODE"{n++} END{print n+0}' "$file")"
  canary_sha_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256"{n++} END{print n+0}' "$file")"
  canary_ids_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS"{n++} END{print n+0}' "$file")"
  registry_sha_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256"{n++} END{print n+0}' "$file")"
  registry_membership_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256"{n++} END{print n+0}' "$file")"
  registry_member_count_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT"{n++} END{print n+0}' "$file")"
  registry_activation_count="$(awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID"{n++} END{print n+0}' "$file")"
  [ "$enabled_count" -eq 1 ] || { echo "lifecycle mode switch: $file must contain exactly one lifecycle enabled key" >&2; return 1; }
  [ "$mode_count" -eq 1 ] || { echo "lifecycle mode switch: $file must contain exactly one lifecycle mode key" >&2; return 1; }
  [ "$canary_sha_count" -le 1 ] || { echo "lifecycle mode switch: $file contains duplicate canary SHA keys" >&2; return 1; }
  [ "$canary_ids_count" -le 1 ] || { echo "lifecycle mode switch: $file contains duplicate canary event ID keys" >&2; return 1; }
  for count in "$registry_sha_count" "$registry_membership_count" "$registry_member_count_count" "$registry_activation_count"; do
    [ "$count" -le 1 ] || { echo "lifecycle mode switch: $file contains duplicate registry trust-root keys" >&2; return 1; }
  done
  file_enabled="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENABLED)"
  file_mode_value="$(read_key "$file" RACE_EVENT_LIFECYCLE_MODE)"
  file_canary_sha="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256)"
  file_canary_ids="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS)"
  file_registry_sha="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256)"
  file_registry_membership="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256)"
  file_registry_count="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT)"
  file_registry_activation="$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID)"
  if { [ -n "$file_canary_sha" ] && [ -z "$file_canary_ids" ]; } \
    || { [ -z "$file_canary_sha" ] && [ -n "$file_canary_ids" ]; }; then
    echo "lifecycle mode switch: $file has an incomplete canary root" >&2
    return 1
  fi
  registry_nonempty=0
  registry_empty=0
  for value in "$file_registry_sha" "$file_registry_membership" "$file_registry_count" "$file_registry_activation"; do
    if [ -n "$value" ]; then registry_nonempty=$((registry_nonempty + 1)); else registry_empty=$((registry_empty + 1)); fi
  done
  [ "$registry_nonempty" -eq 0 ] || [ "$registry_empty" -eq 0 ] \
    || { echo "lifecycle mode switch: $file has an incomplete registry root" >&2; return 1; }
  [ -z "$file_canary_sha" ] || [ "$registry_nonempty" -eq 0 ] \
    || { echo "lifecycle mode switch: $file enables both legacy and registry roots" >&2; return 1; }
  if [ "$file_enabled/$file_mode_value" = "true/enforce" ]; then
    [ -n "$file_canary_sha" ] || [ "$registry_nonempty" -eq 4 ] \
      || { echo "lifecycle mode switch: $file enforce mode lacks a trust root" >&2; return 1; }
  else
    [ -z "$file_canary_sha" ] && [ "$registry_nonempty" -eq 0 ] \
      || { echo "lifecycle mode switch: $file has a trust root outside enforce" >&2; return 1; }
  fi
}

read_key() {
  awk -F= -v wanted="$2" '$1==wanted{print substr($0,index($0,"=")+1)}' "$1"
}

rewrite_env() {
  file="$1" enabled="$2" mode="$3" enforce_sha="$4" enforce_ids="$5"
  enforce_registry_sha="$6" enforce_registry_membership="$7"
  enforce_registry_count="$8" enforce_registry_activation="$9"
  tmp="$(mktemp "${file}.lifecycle.tmp.XXXXXX")" || return 1
  chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
  if ! awk -v enabled="$enabled" -v mode="$mode" -v enforce_sha="$enforce_sha" -v enforce_ids="$enforce_ids" \
    -v registry_sha="$enforce_registry_sha" -v membership_sha="$enforce_registry_membership" \
    -v member_count="$enforce_registry_count" -v activation_id="$enforce_registry_activation" '
    /^RACE_EVENT_LIFECYCLE_ENABLED=/{print "RACE_EVENT_LIFECYCLE_ENABLED=" enabled; next}
    /^RACE_EVENT_LIFECYCLE_MODE=/{print "RACE_EVENT_LIFECYCLE_MODE=" mode; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=" enforce_sha; saw_sha=1; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=" enforce_ids; saw_ids=1; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=" registry_sha; saw_registry_sha=1; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=" membership_sha; saw_membership_sha=1; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=" member_count; saw_member_count=1; next}
    /^RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=/{print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=" activation_id; saw_activation_id=1; next}
    {print}
    END {
      if (!saw_sha) print "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=" enforce_sha
      if (!saw_ids) print "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=" enforce_ids
      registry_any = registry_sha != "" || membership_sha != "" || member_count != "" || activation_id != ""
      if (registry_any && !saw_registry_sha) print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=" registry_sha
      if (registry_any && !saw_membership_sha) print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=" membership_sha
      if (registry_any && !saw_member_count) print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=" member_count
      if (registry_any && !saw_activation_id) print "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=" activation_id
    }
  ' "$file" > "$tmp"; then
    rm -f "$tmp"; return 1
  fi
  if ! python3 - "$tmp" <<'PY'
import os
import sys

with open(sys.argv[1], "rb") as stream:
    os.fsync(stream.fileno())
PY
  then
    rm -f "$tmp"; return 1
  fi
  mv -f "$tmp" "$file" || { rm -f "$tmp"; return 1; }
  chmod 600 "$file" || return 1
  validate_env_file "$file" || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENABLED)" = "$enabled" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_MODE)" = "$mode" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256)" = "$enforce_sha" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS)" = "$enforce_ids" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256)" = "$enforce_registry_sha" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256)" = "$enforce_registry_membership" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT)" = "$enforce_registry_count" ] || return 1
  [ "$(read_key "$file" RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID)" = "$enforce_registry_activation" ] || return 1
}

verify_runtime() {
  beat_state="$1" enabled="$2" mode="$3" enforce_sha="$4" enforce_ids="$5"
  expected_registry_sha="${6:-}" expected_registry_membership="${7:-}"
  expected_registry_count="${8:-}" expected_registry_activation="${9:-}"
  EXPECTED_BEAT_STATE="$beat_state" \
  EXPECTED_LIFECYCLE_ENABLED="$enabled" \
  EXPECTED_LIFECYCLE_MODE="$mode" \
  EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256="$enforce_sha" \
  EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS="$enforce_ids" \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_SHA256="$expected_registry_sha" \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256="$expected_registry_membership" \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT="$expected_registry_count" \
  EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID="$expected_registry_activation" \
  EXPECTED_COMPOSE_PROJECT="$EXPECTED_COMPOSE_PROJECT" \
  EXPECTED_RELEASE_DIR="$EXPECTED_RELEASE_DIR" \
  EXPECTED_IMAGE_ID="$EXPECTED_IMAGE_ID" \
  EXPECTED_RELEASE_COMMIT="$EXPECTED_RELEASE_COMMIT" \
  COMPOSE_FILE="$COMPOSE_FILE" "$VERIFY"
}

compose_exec_registry_verify() {
  "$COMPOSE" -f "$COMPOSE_FILE" \
    --project-directory "$EXPECTED_RELEASE_DIR" \
    --project-name "$EXPECTED_COMPOSE_PROJECT" \
    exec -T web python manage.py verify_race_event_lifecycle_enforce_registry \
    --manifest-stdin --manifest-sha256 "$registry_sha" \
    --expected-commit "$EXPECTED_RELEASE_COMMIT" "$@" < "$manifest_snapshot"
}

activate_race_event_lifecycle_enforce_registry() {
  activation_id="$1"
  [ -n "$activation_id" ] || return 1
  compose_exec_registry_verify --expected-state inactive --activate \
    --activation-id "$activation_id"
}

parse_registry_result_activation_id() {
  expected_outcome="$1"
  output="$2"
  python3 - "$expected_outcome" "$registry_member_count" "$output" <<'PY'
import re
import sys

expected, expected_count, raw = sys.argv[1:]
lines = [line.strip() for line in raw.splitlines() if line.strip()]
if expected == "verified_active":
    pattern = re.compile(
        r"^outcome=verified_active members=([1-9][0-9]*) activation_id=([0-9a-f]{64})$"
    )
else:
    pattern = re.compile(
        rf"^outcome={re.escape(expected)} activation_id=([0-9a-f]{{64}})$"
    )
matches = [pattern.fullmatch(line) for line in lines]
matches = [match for match in matches if match]
if len(lines) != 1 or len(matches) != 1:
    raise SystemExit(1)
if expected == "verified_active":
    if matches[0].group(1) != expected_count:
        raise SystemExit(1)
    print(matches[0].group(2))
else:
    print(matches[0].group(1))
PY
}

resolve_registry_activation_id() {
  if inactive_output="$(compose_exec_registry_verify --expected-state inactive 2>/dev/null)"; then
    candidate="$(generate_registry_activation_id)" || return 1
    registry_activation_id="$candidate"
    activated_output="$(activate_race_event_lifecycle_enforce_registry "$registry_activation_id")" || return 1
    parsed="$(parse_registry_result_activation_id activated "$activated_output")" || return 1
    [ "$parsed" = "$candidate" ] || return 1
    printf '%s\n' "$parsed"
    return 0
  fi

  # A previous attempt may have committed DB activation before env rewrite or
  # container recreation failed.  Strongly re-bind the same artifact to the
  # active DB registry, obtain its existing ID, then execute an idempotent
  # activation replay with that exact ID.  No fresh ID is generated here.
  active_output="$(compose_exec_registry_verify --expected-state active)" || return 1
  existing="$(parse_registry_result_activation_id verified_active "$active_output")" || return 1
  registry_activation_id="$existing"
  replay_output="$(activate_race_event_lifecycle_enforce_registry "$registry_activation_id")" || return 1
  replay_id="$(parse_registry_result_activation_id replay "$replay_output")" || return 1
  [ "$replay_id" = "$existing" ] || return 1
  printf '%s\n' "$existing"
}

generate_registry_activation_id() {
  generated="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" || return 1
  case "$generated" in *[!0-9a-f]*|"") return 1 ;; esac
  [ "${#generated}" -eq 64 ] || return 1
  printf '%s\n' "$generated"
}

compose_exec_canary_verify() {
  "$COMPOSE" -f "$COMPOSE_FILE" \
    --project-directory "$EXPECTED_RELEASE_DIR" \
    --project-name "$EXPECTED_COMPOSE_PROJECT" \
    exec -T web python manage.py verify_race_event_lifecycle_enforce_canary \
    --manifest-stdin --manifest-sha256 "$canary_sha" \
    --expected-commit "$EXPECTED_RELEASE_COMMIT" \
    --expected-event-ids "$canary_ids" "$@" < "$manifest_snapshot"
}

wait_for_web_healthy() {
  COMPOSE_PROJECT_NAME="$EXPECTED_COMPOSE_PROJECT" \
  COMPOSE_FILE="$COMPOSE_FILE" SERVICE_NAME=web \
  SERVICE_HEALTH_TIMEOUT_SECONDS="${SERVICE_HEALTH_TIMEOUT_SECONDS:-300}" \
    "$HEALTH"
}

compose_mutation() {
  "$COMPOSE" -f "$COMPOSE_FILE" \
    --project-directory "$EXPECTED_RELEASE_DIR" \
    --project-name "$EXPECTED_COMPOSE_PROJECT" "$@"
}

stop_verified_host_lifecycle_offenders() {
  census="$(mktemp "${TMPDIR:-/tmp}/umanews-lifecycle-recovery-census.XXXXXX")" || return 1
  candidates="$(mktemp "${TMPDIR:-/tmp}/umanews-lifecycle-recovery-candidates.XXXXXX")" || {
    rm -f "$census"; return 1;
  }
  if ! docker ps --filter label=com.docker.compose.service --format '{{.ID}}' > "$census"; then
    rm -f "$census" "$candidates"
    return 1
  fi

  while IFS= read -r cid; do
    [ -n "$cid" ] || continue
    case "$cid" in
      -*|*[!A-Za-z0-9_.-]*) rm -f "$census" "$candidates"; return 1 ;;
    esac

    labels="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.oneoff"}}|{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$cid")" || {
      rm -f "$census" "$candidates"; return 1;
    }
    IFS='|' read -r host_service host_project host_oneoff host_workdir host_extra <<EOF
$labels
EOF
    [ -n "$host_service" ] || { rm -f "$census" "$candidates"; return 1; }
    [ -n "$host_project" ] || { rm -f "$census" "$candidates"; return 1; }
    [ -n "$host_workdir" ] || { rm -f "$census" "$candidates"; return 1; }
    [ -z "$host_extra" ] || { rm -f "$census" "$candidates"; return 1; }
    case "$host_oneoff" in True|true|False|false) ;; *) rm -f "$census" "$candidates"; return 1 ;; esac

    host_running="$(docker inspect --format '{{.State.Running}}' "$cid")" || {
      rm -f "$census" "$candidates"; return 1;
    }
    case "$host_running" in true|false) ;; *) rm -f "$census" "$candidates"; return 1 ;; esac
    [ "$host_running" = "true" ] || continue

    case "$host_service" in
      worker|beat)
        # A generic worker/beat name is not an ownership boundary.  Only the
        # exact reviewed project, a physical Umanews release directory, and
        # the frozen image/revision together authorize a stop.
        [ "$host_project" = "$EXPECTED_COMPOSE_PROJECT" ] || {
          rm -f "$census" "$candidates"; return 1;
        }
        host_workdir_physical="$(CDPATH= cd -- "$host_workdir" 2>/dev/null && pwd -P)" || {
          rm -f "$census" "$candidates"; return 1;
        }
        host_is_current=0
        if [ "$host_workdir_physical" = "$physical_expected_release" ]; then
          host_is_current=1
        else
          host_workdir_base="$(basename "$host_workdir_physical")"
          host_workdir_parent_base="$(basename "$(dirname "$host_workdir_physical")")"
          case "$host_workdir_base/$host_workdir_parent_base" in
            umanews-release-?*/*|umanewsbot/umanews-release-?*) ;;
            *) rm -f "$census" "$candidates"; return 1 ;;
          esac
        fi

        host_image="$(docker inspect --format '{{.Image}}' "$cid")" || {
          rm -f "$census" "$candidates"; return 1;
        }
        [ "$host_image" = "$EXPECTED_IMAGE_ID" ] || {
          rm -f "$census" "$candidates"; return 1;
        }
        host_revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$host_image")" || {
          rm -f "$census" "$candidates"; return 1;
        }
        [ "$host_revision" = "$EXPECTED_RELEASE_COMMIT" ] || {
          rm -f "$census" "$candidates"; return 1;
        }

        if [ "$host_is_current" -eq 0 ] \
          || [ "$host_oneoff" = "True" ] || [ "$host_oneoff" = "true" ]; then
          printf '%s\n' "$cid" >> "$candidates" || {
            rm -f "$census" "$candidates"; return 1;
          }
        fi
        ;;
    esac
  done < "$census"
  rm -f "$census"

  stopped=0
  while IFS= read -r cid; do
    [ -n "$cid" ] || continue
    docker stop "$cid" || { rm -f "$candidates"; return 1; }
    stopped=$((stopped + 1))
  done < "$candidates"
  rm -f "$candidates"

  # A failed coherence check with no precisely attributable offender is not
  # repairable here.  Do not turn a transient/unknown verifier failure into a
  # successful recovery merely because a second probe happens to pass.
  [ "$stopped" -gt 0 ] || return 1
  return 0
}

recover_off() {
  set +e
  recovery_rc=0
  # Failure convergence writes RACE_EVENT_LIFECYCLE_ENABLED=false and then
  # RACE_EVENT_LIFECYCLE_MODE=off to both reviewed env files.
  # Stop both schedulers and consumers before touching the trust root.  This
  # closes the queued-task window even when failure happens after activation.
  compose_mutation stop beat worker || recovery_rc=1
  # Clear RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256 and
  # RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS without requiring artifact access.
  rewrite_env_off "$CANONICAL_ENV_FILE" || recovery_rc=1
  rewrite_env_off "$ACTIVE_RELEASE_ENV_FILE" || recovery_rc=1
  compose_mutation up -d --no-deps --force-recreate web worker || recovery_rc=1
  if ! verify_runtime stopped false off "" ""; then
    if stop_verified_host_lifecycle_offenders \
      && verify_runtime stopped false off "" ""; then
      :
    else
      recovery_rc=1
    fi
  fi
  if [ "$recovery_rc" -ne 0 ]; then
    compose_mutation stop beat worker >/dev/null 2>&1 || true
    echo "lifecycle mode switch: safe convergence failed; worker and Beat stop attempted; lock and evidence retained" >&2
    keep_lock=1
    set -e
    return 1
  fi
  set -e
  return 0
}

rewrite_env_off() {
  rewrite_env "$1" false off "" "" "" "" "" ""
}

on_exit() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [ "$status" -eq 0 ] && [ "$completed" -eq 1 ] && [ "$lock_held" -eq 1 ]; then
    if "$LOCK" release; then
      lock_held=0
    else
      status=1
      keep_lock=1
    fi
  fi
  if [ "$status" -ne 0 ] && [ "$recovery_required" -eq 1 ]; then
    if ! recover_off; then keep_lock=1; fi
  fi
  if [ "$lock_held" -eq 1 ] && [ "$keep_lock" -eq 0 ]; then
    "$LOCK" release || { keep_lock=1; status=1; }
  fi
  if [ "$status" -eq 0 ] && [ "$completed" -ne 1 ]; then status=1; fi
  if [ -n "$manifest_snapshot" ]; then rm -f "$manifest_snapshot"; fi
  exit "$status"
}
export DEPLOYMENT_LOCK_ACTION=lifecycle-mode-switch
export COMPOSE_FILE
"$LOCK" acquire
lock_held=1
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

validate_env_file "$CANONICAL_ENV_FILE"
validate_env_file "$ACTIVE_RELEASE_ENV_FILE"

if [ "$TARGET_LIFECYCLE_ENABLED" = "true" ]; then
  [ "$(read_key "$CANONICAL_ENV_FILE" RACE_EVENT_LIFECYCLE_ENABLED)" = "false" ] || fail "enable requires canonical false/off"
  [ "$(read_key "$CANONICAL_ENV_FILE" RACE_EVENT_LIFECYCLE_MODE)" = "off" ] || fail "enable requires canonical false/off"
  [ "$(read_key "$ACTIVE_RELEASE_ENV_FILE" RACE_EVENT_LIFECYCLE_ENABLED)" = "false" ] || fail "enable requires active release false/off"
  [ "$(read_key "$ACTIVE_RELEASE_ENV_FILE" RACE_EVENT_LIFECYCLE_MODE)" = "off" ] || fail "enable requires active release false/off"
  [ -z "$(read_key "$CANONICAL_ENV_FILE" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256)" ] || fail "enable requires empty canonical canary SHA"
  [ -z "$(read_key "$CANONICAL_ENV_FILE" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS)" ] || fail "enable requires empty canonical canary event IDs"
  [ -z "$(read_key "$ACTIVE_RELEASE_ENV_FILE" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256)" ] || fail "enable requires empty active canary SHA"
  [ -z "$(read_key "$ACTIVE_RELEASE_ENV_FILE" RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS)" ] || fail "enable requires empty active canary event IDs"
  for key in RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256 \
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256 \
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT \
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID; do
    [ -z "$(read_key "$CANONICAL_ENV_FILE" "$key")" ] || fail "enable requires empty canonical registry root"
    [ -z "$(read_key "$ACTIVE_RELEASE_ENV_FILE" "$key")" ] || fail "enable requires empty active registry root"
  done
  # This preflight runs while all three resident services are still untouched.
  # A stale or cross-project runtime therefore fails with zero service or file
  # mutation and the EXIT trap releases the already-held shared lock.
  enable_admission_beat_state=running
  if [ "$enforce_root_kind" = "registry" ]; then
    # Registry promotion deliberately leaves Beat stopped; that is the only
    # reviewed stopped admission.  web/worker still undergo the full census.
    enable_admission_beat_state=stopped
  fi
  verify_runtime "$enable_admission_beat_state" false off "" ""
  if [ "$TARGET_LIFECYCLE_MODE" = "enforce" ]; then
    wait_for_web_healthy
    if [ "$enforce_root_kind" = "canary" ]; then
      compose_exec_canary_verify --phase inactive --disarm
    else
      # Accept either a freshly promoted inactive registry or an exact active
      # artifact left by a previously failed env/container phase.  The latter
      # is fully verified and replayed after writer shutdown below.
      if ! compose_exec_registry_verify --expected-state inactive >/dev/null 2>&1; then
        compose_exec_registry_verify --expected-state active >/dev/null
      fi
    fi
  fi
fi

recovery_required=1
if [ "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" = "true/enforce" ] \
  || [ "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" = "false/off" ]; then
  compose_mutation stop beat worker
else
  compose_mutation stop beat
fi

# Registry activation occurs while the reviewed resident web is still
# false/off and both Celery scheduler/consumer are stopped.  Generate the
# activation trust-root component only after the shared lock is held, then
# atomically activate through the bounded manifest stdin before any env write.
if [ "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" = "true/enforce" ] \
  && [ "$enforce_root_kind" = "registry" ]; then
  registry_activation_id="$(resolve_registry_activation_id)" \
    || fail "cannot activate or strictly replay registry activation ID"
fi

stamp="$(date -u '+%Y%m%dT%H%M%SZ').$$"
canonical_backup="${CANONICAL_ENV_FILE}.lifecycle-backup.$stamp"
active_backup="${ACTIVE_RELEASE_ENV_FILE}.lifecycle-backup.$stamp"
cp -p "$CANONICAL_ENV_FILE" "$canonical_backup"
chmod 600 "$canonical_backup"
cp -p "$ACTIVE_RELEASE_ENV_FILE" "$active_backup"
chmod 600 "$active_backup"
rewrite_env "$CANONICAL_ENV_FILE" "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE" "$canary_sha" "$canary_ids" \
  "$registry_sha" "$registry_membership_sha" "$registry_member_count" "$registry_activation_id"
rewrite_env "$ACTIVE_RELEASE_ENV_FILE" "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE" "$canary_sha" "$canary_ids" \
  "$registry_sha" "$registry_membership_sha" "$registry_member_count" "$registry_activation_id"

if [ "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" = "true/enforce" ]; then
  compose_mutation up -d --no-deps --force-recreate web
  wait_for_web_healthy
  # Recreated web consumes the same bounded --manifest-stdin trust root.
  if [ "$enforce_root_kind" = "canary" ]; then
    compose_exec_canary_verify --phase inactive
  else
    compose_exec_registry_verify --expected-state active \
      --activation-id "$registry_activation_id"
  fi
  compose_mutation up -d --no-deps --force-recreate worker
  verify_runtime stopped true enforce "$canary_sha" "$canary_ids" \
    "$registry_sha" "$registry_membership_sha" "$registry_member_count" "$registry_activation_id"
  if [ "$enforce_root_kind" = "canary" ]; then
    compose_exec_canary_verify --phase active --activate
    compose_exec_canary_verify --phase active
  fi
  compose_mutation up -d --no-deps --force-recreate beat
  verify_runtime running true enforce "$canary_sha" "$canary_ids" \
    "$registry_sha" "$registry_membership_sha" "$registry_member_count" "$registry_activation_id"
else
  compose_mutation up -d --no-deps --force-recreate web worker
  verify_runtime stopped "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE" "" ""
  compose_mutation up -d --no-deps --force-recreate beat
  verify_runtime running "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE" "" ""
fi

completed=1
echo "lifecycle mode switch completed; backups retained"
