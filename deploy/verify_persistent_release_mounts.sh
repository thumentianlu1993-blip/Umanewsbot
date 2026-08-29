#!/bin/sh
# Fail closed when an isolated release would bind empty release-local runtime
# directories or a release-local TLS tree. Values are parsed, never sourced.
set -eu

ROOT_DIR="${UMANEWS_ROOT_DIR:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  echo "persistent release mount preflight requires a regular .env" >&2
  exit 1
fi

read_exact_path() {
  key="$1"
  count="$(awk -F= -v key="$key" '$1 == key { count += 1 } END { print count + 0 }' "$ENV_FILE")"
  if [ "$count" -ne 1 ]; then
    echo "$key must appear exactly once in .env" >&2
    exit 1
  fi
  value="$(awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print }' "$ENV_FILE" | tr -d '\r')"
  case "$value" in
    /*) ;;
    *) echo "$key must be an absolute path" >&2; exit 1 ;;
  esac
  if [ ! -d "$value" ] || [ -L "$value" ]; then
    echo "$key must name an existing non-symlink directory" >&2
    exit 1
  fi
  printf '%s\n' "$value"
}

runtime_root="$(read_exact_path UMANEWS_PERSISTENT_RUNTIME_ROOT)"
tls_root="$(read_exact_path UMANEWS_TLS_CERT_ROOT)"
runtime_root_real="$(realpath "$runtime_root")"

for relative in \
  horse_profile_completion \
  upcoming_racecard_urls \
  secrets \
  race_live_racecards \
  race_live_publications \
  race_data_sync
do
  candidate="$runtime_root/$relative"
  if [ ! -d "$candidate" ] || [ -L "$candidate" ]; then
    echo "persistent runtime directory is missing or is a symlink: $relative" >&2
    exit 1
  fi
  fallback="$ROOT_DIR/runtime/$relative"
  if [ ! -d "$fallback" ] || [ "$(realpath "$fallback")" != "$runtime_root_real/$relative" ]; then
    echo "release-local rollback compatibility path is not bound to persistent runtime: $relative" >&2
    exit 1
  fi
done

tls_root_real="$(realpath "$tls_root")"
tls_fallback="$ROOT_DIR/deploy/certs/letsencrypt"
if [ ! -d "$tls_fallback" ] || [ "$(realpath "$tls_fallback")" != "$tls_root_real/letsencrypt" ]; then
  echo "release-local rollback compatibility path is not bound to persistent TLS material" >&2
  exit 1
fi
for relative in \
  letsencrypt/live/umafans.run/fullchain.pem \
  letsencrypt/live/umafans.run/privkey.pem
do
  candidate="$tls_root/$relative"
  if [ ! -r "$candidate" ]; then
    echo "TLS material is missing or unreadable: $relative" >&2
    exit 1
  fi
  candidate_real="$(realpath "$candidate")"
  case "$candidate_real" in
    "$tls_root_real"/*) ;;
    *) echo "TLS material escapes the persistent certificate root: $relative" >&2; exit 1 ;;
  esac
  if [ ! -f "$candidate_real" ]; then
    echo "TLS material target is not a regular file: $relative" >&2
    exit 1
  fi
done

echo "persistent release mount preflight passed"
