#!/bin/sh
# Host-local exclusive deployment lock for deploy/rollback/manual-release.
#
# Subcommands:
#   acquire  - atomically create the lock directory (fails closed if present)
#   verify   - exit 0 only when DEPLOYMENT_LOCK_TOKEN matches the stored hash
#   release  - verify first, then remove the lock directory
#
# Environment:
#   DEPLOYMENT_LOCK_DIR     lock directory (default /tmp/umanews-deployment.lock)
#   DEPLOYMENT_LOCK_ACTION  required for acquire; one of
#                           deploy|rollback|manual-release|pre-contract-rollback|
#                           p0-closed-admission|resume-release|
#                           lifecycle-mode-switch
#   DEPLOYMENT_LOCK_TOKEN   required for all subcommands; only its SHA-256 is
#                           stored, never the raw token
#
# A pre-existing lock directory always fails closed: it is never auto-cleaned
# by PID or age. Remove a stale lock only after manually confirming no
# deploy/rollback process is running.
set -eu

LOCK_DIR="${DEPLOYMENT_LOCK_DIR:-/tmp/umanews-deployment.lock}"
ACTION="${DEPLOYMENT_LOCK_ACTION:-}"
TOKEN="${DEPLOYMENT_LOCK_TOKEN:-}"

usage() {
  echo "Usage: DEPLOYMENT_LOCK_ACTION=<action> DEPLOYMENT_LOCK_TOKEN=<token> $0 acquire|verify|release" >&2
  exit 2
}

sha256_hex() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1
  else
    printf '%s' "$1" | openssl dgst -sha256 | sed 's/^.* //'
  fi
}

command="${1:-}"
case "$command" in
  acquire|verify|release) ;;
  *) usage ;;
esac

if [ -z "$TOKEN" ]; then
  echo "DEPLOYMENT_LOCK_TOKEN is required" >&2
  exit 1
fi

verify_token() {
  if [ ! -f "$LOCK_DIR/token_sha256" ]; then
    echo "no valid deployment lock present" >&2
    exit 1
  fi
  token_hash="$(sha256_hex "$TOKEN")"
  stored_hash="$(cat "$LOCK_DIR/token_sha256")"
  if [ "$token_hash" != "$stored_hash" ]; then
    echo "deployment lock token mismatch" >&2
    exit 1
  fi
}

case "$command" in
  acquire)
    case "$ACTION" in
      deploy|rollback|manual-release|pre-contract-rollback|p0-closed-admission|resume-release|lifecycle-mode-switch) ;;
      *)
        echo "DEPLOYMENT_LOCK_ACTION must be one of deploy|rollback|manual-release|pre-contract-rollback|p0-closed-admission|resume-release|lifecycle-mode-switch" >&2
        exit 1
        ;;
    esac
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      echo "deployment lock already held; another deploy/rollback/manual release is running or a stale lock remains" >&2
      exit 1
    fi
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    printf '%s\n' "$ACTION" > "$LOCK_DIR/action"
    printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$LOCK_DIR/started_at_utc"
    printf '%s\n' "${COMPOSE_FILE:-}" > "$LOCK_DIR/compose_file"
    printf '%s\n' "$(sha256_hex "$TOKEN")" > "$LOCK_DIR/token_sha256"
    echo "deployment lock acquired (action=$ACTION)"
    ;;
  verify)
    verify_token
    ;;
  release)
    verify_token
    rm -rf "$LOCK_DIR"
    echo "deployment lock released"
    ;;
esac
