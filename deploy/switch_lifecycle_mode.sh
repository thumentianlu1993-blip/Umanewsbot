#!/bin/sh
# Switch lifecycle only between the reviewed false/off and true/shadow modes.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT_DIR"

COMPOSE="$ROOT_DIR/deploy/docker/compose-wrapper.sh"
LOCK="$ROOT_DIR/deploy/deployment_lock.sh"
VERIFY="$ROOT_DIR/deploy/verify_lifecycle_runtime_coherence.sh"
CANONICAL_ENV_FILE="/opt/umanewsbot/.env"

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
case "$TARGET_LIFECYCLE_ENABLED/$TARGET_LIFECYCLE_MODE" in false/off|true/shadow) ;; *) fail "only false/off and true/shadow are supported" ;; esac

export DEPLOYMENT_LOCK_ACTION=lifecycle-mode-switch
export COMPOSE_FILE
"$LOCK" acquire
lock_held=1
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
  [ "$enabled_count" -eq 1 ] || { echo "lifecycle mode switch: $file must contain exactly one lifecycle enabled key" >&2; return 1; }
  [ "$mode_count" -eq 1 ] || { echo "lifecycle mode switch: $file must contain exactly one lifecycle mode key" >&2; return 1; }
}

read_key() {
  awk -F= -v wanted="$2" '$1==wanted{print substr($0,index($0,"=")+1)}' "$1"
}

rewrite_env() {
  file="$1" enabled="$2" mode="$3"
  tmp="$(mktemp "${file}.lifecycle.tmp.XXXXXX")" || return 1
  chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
  if ! awk -v enabled="$enabled" -v mode="$mode" '
    /^RACE_EVENT_LIFECYCLE_ENABLED=/{print "RACE_EVENT_LIFECYCLE_ENABLED=" enabled; next}
    /^RACE_EVENT_LIFECYCLE_MODE=/{print "RACE_EVENT_LIFECYCLE_MODE=" mode; next}
    {print}
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
}

verify_runtime() {
  beat_state="$1" enabled="$2" mode="$3"
  EXPECTED_BEAT_STATE="$beat_state" \
  EXPECTED_LIFECYCLE_ENABLED="$enabled" \
  EXPECTED_LIFECYCLE_MODE="$mode" \
  EXPECTED_COMPOSE_PROJECT="$EXPECTED_COMPOSE_PROJECT" \
  EXPECTED_RELEASE_DIR="$EXPECTED_RELEASE_DIR" \
  EXPECTED_IMAGE_ID="$EXPECTED_IMAGE_ID" \
  EXPECTED_RELEASE_COMMIT="$EXPECTED_RELEASE_COMMIT" \
  COMPOSE_FILE="$COMPOSE_FILE" "$VERIFY"
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
  compose_mutation stop beat || recovery_rc=1
  rewrite_env "$CANONICAL_ENV_FILE" false off || recovery_rc=1
  rewrite_env "$ACTIVE_RELEASE_ENV_FILE" false off || recovery_rc=1
  compose_mutation up -d --no-deps --force-recreate web worker || recovery_rc=1
  if ! verify_runtime stopped false off; then
    if stop_verified_host_lifecycle_offenders \
      && verify_runtime stopped false off; then
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
  exit "$status"
}
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
  # This preflight runs while all three resident services are still untouched.
  # A stale or cross-project runtime therefore fails with zero service or file
  # mutation and the EXIT trap releases the already-held shared lock.
  verify_runtime running false off
fi

recovery_required=1
compose_mutation stop beat
stamp="$(date -u '+%Y%m%dT%H%M%SZ').$$"
canonical_backup="${CANONICAL_ENV_FILE}.lifecycle-backup.$stamp"
active_backup="${ACTIVE_RELEASE_ENV_FILE}.lifecycle-backup.$stamp"
cp -p "$CANONICAL_ENV_FILE" "$canonical_backup"
chmod 600 "$canonical_backup"
cp -p "$ACTIVE_RELEASE_ENV_FILE" "$active_backup"
chmod 600 "$active_backup"
rewrite_env "$CANONICAL_ENV_FILE" "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE"
rewrite_env "$ACTIVE_RELEASE_ENV_FILE" "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE"
compose_mutation up -d --no-deps --force-recreate web worker
verify_runtime stopped "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE"
compose_mutation up -d --no-deps --force-recreate beat
verify_runtime running "$TARGET_LIFECYCLE_ENABLED" "$TARGET_LIFECYCLE_MODE"

completed=1
echo "lifecycle mode switch completed; backups retained"
