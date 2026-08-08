#!/bin/sh
# Fail closed when the canonical active or transition recovery marker exists.
# This host-only check never reads, rewrites, chmods, renames, or deletes the
# marker, so provenance survives a rejected ordinary release unchanged.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
MARKER_DIR="$ROOT_DIR/runtime/migration_history_repair"
MARKER_PATH="$MARKER_DIR/restricted-recovery.json"
TRANSITION_PATH="$MARKER_DIR/restricted-recovery.transition.json"
CONTROL_STATE_PATH="$MARKER_DIR/restricted-recovery-control.json"

if [ -L "$MARKER_DIR" ] || [ ! -d "$MARKER_DIR" ]; then
  echo "restricted recovery marker parent is untrusted; refusing ordinary rollback" >&2
  exit 1
fi

dir_owner="$(stat -c '%u' "$MARKER_DIR" 2>/dev/null || stat -f '%u' "$MARKER_DIR")"
dir_mode="$(stat -c '%a' "$MARKER_DIR" 2>/dev/null || stat -f '%Lp' "$MARKER_DIR")"
if [ "$dir_owner" != "$(id -u)" ] || [ "$dir_mode" != "700" ]; then
  echo "restricted recovery marker parent owner/mode is untrusted; refusing ordinary rollback" >&2
  exit 1
fi
if [ ! -e "$MARKER_PATH" ] && [ ! -L "$MARKER_PATH" ] && [ ! -e "$TRANSITION_PATH" ] && [ ! -L "$TRANSITION_PATH" ] && [ ! -e "$CONTROL_STATE_PATH" ] && [ ! -L "$CONTROL_STATE_PATH" ]; then
  exit 0
fi
for candidate in "$MARKER_PATH" "$TRANSITION_PATH" "$CONTROL_STATE_PATH"; do
  if [ ! -e "$candidate" ] && [ ! -L "$candidate" ]; then continue; fi
  if [ -L "$candidate" ] || [ ! -f "$candidate" ]; then
    echo "restricted recovery marker is not a trusted regular file; refusing ordinary release" >&2
    exit 1
  fi
  marker_owner="$(stat -c '%u' "$candidate" 2>/dev/null || stat -f '%u' "$candidate")"
  marker_mode="$(stat -c '%a' "$candidate" 2>/dev/null || stat -f '%Lp' "$candidate")"
  if [ "$marker_owner" != "$(id -u)" ] || [ "$marker_mode" != "600" ]; then
    echo "restricted recovery marker owner/mode is untrusted; refusing ordinary release" >&2
    exit 1
  fi
done

echo "active recovery marker, transition, or rollback control state present; ordinary release is forbidden" >&2
exit 1
