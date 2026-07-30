# Shared helpers for the frozen race_live_worker restore-intent file.
# Sourced by deploy/run_application_release.sh, deploy/rollback_pre_single_owner.sh
# and deploy/resume_stopped_release.sh. POSIX sh; callers run with set -eu.
#
# The file binds a restore intent to the exact attempt that froze it:
# state, node, compose file, action, HEAD and freeze time, written mode 600.
# Readers must validate ownership, permissions, non-symlink regularity and the
# compose_file/action/head binding before trusting it.

race_live_state_field() {
  awk -F= -v key="$2" '$1 == key {print $2; exit}' "$1"
}

# write_race_live_state_file <file> <state> <node> <compose_file> <action>
write_race_live_state_file() {
  _wrls_head="$(git rev-parse HEAD)"
  {
    printf 'state=%s\n' "$2"
    printf 'node=%s\n' "$3"
    printf 'compose_file=%s\n' "$4"
    printf 'action=%s\n' "$5"
    printf 'head=%s\n' "$_wrls_head"
    printf 'frozen_at_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  } > "$1"
  chmod 600 "$1"
}

# validate_race_live_state_file <file> <compose_file> <allowed actions (space separated)>
# Prints the rejection reason to stderr; returns 0 only for a trustworthy file.
validate_race_live_state_file() {
  _vrsl_file="$1"
  _vrsl_compose="$2"
  _vrsl_actions="$3"

  if [ -L "$_vrsl_file" ]; then
    echo "race-live intent file is a symlink; refusing to trust it" >&2
    return 1
  fi
  if [ ! -f "$_vrsl_file" ]; then
    echo "race-live intent file is not a regular file; refusing to trust it" >&2
    return 1
  fi
  if [ -n "$(find "$_vrsl_file" ! -user "$(id -u)" 2>/dev/null)" ]; then
    echo "race-live intent file is not owned by the current user; refusing to trust it" >&2
    return 1
  fi
  _vrsl_mode="$(stat -f '%Lp' "$_vrsl_file" 2>/dev/null || stat -c '%a' "$_vrsl_file" 2>/dev/null)"
  case "$_vrsl_mode" in
    *00) ;;
    *)
      echo "race-live intent file grants group/other permissions; refusing to trust it" >&2
      return 1
      ;;
  esac

  _vrsl_state="$(race_live_state_field "$_vrsl_file" state)"
  case "$_vrsl_state" in
    running|not-running) ;;
    *)
      echo "race-live intent file has an invalid state; refusing to trust it" >&2
      return 1
      ;;
  esac

  _vrsl_compose_field="$(race_live_state_field "$_vrsl_file" compose_file)"
  if [ "$_vrsl_compose_field" != "$_vrsl_compose" ]; then
    echo "race-live intent file is bound to a different compose file; refusing to trust it" >&2
    return 1
  fi

  _vrsl_action="$(race_live_state_field "$_vrsl_file" action)"
  _vrsl_action_ok=false
  for _vrsl_allowed in $_vrsl_actions; do
    if [ "$_vrsl_action" = "$_vrsl_allowed" ]; then
      _vrsl_action_ok=true
      break
    fi
  done
  if [ "$_vrsl_action_ok" != "true" ]; then
    echo "race-live intent file was frozen by a different action; refusing to trust it" >&2
    return 1
  fi

  _vrsl_head="$(race_live_state_field "$_vrsl_file" head)"
  _vrsl_current_head="$(git rev-parse HEAD)"
  if [ -z "$_vrsl_head" ] || [ "$_vrsl_head" != "$_vrsl_current_head" ]; then
    echo "race-live intent file is bound to a different HEAD; refusing to trust it" >&2
    return 1
  fi

  return 0
}
