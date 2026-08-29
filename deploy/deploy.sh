#!/bin/sh
set -eu
unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found. Copy .env.example to .env and fill production values first."
  exit 1
fi

COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="docker-compose.prod.yml"

# Acquire the host-local deployment lock before any stateful action; the lock
# covers the historical preflight as well (spec 5.4). The release trap is
# installed only after a successful acquire so a contender that loses the
# race never touches the winner's lock.
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=deploy ./deploy/deployment_lock.sh acquire
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

python3 ./deploy/ensure_migration_history_repair_runtime.py
./deploy/check_restricted_recovery_marker.sh
./deploy/verify_persistent_release_mounts.sh

INITIAL_INSTALL_MODE="${HISTORICAL_RUNNER_INITIAL_INSTALL:-false}"
case "$INITIAL_INSTALL_MODE" in true|false) ;; *) echo "HISTORICAL_RUNNER_INITIAL_INSTALL must be true or false" >&2; exit 1 ;; esac
if [ "$INITIAL_INSTALL_MODE" = "true" ]; then
  initial_database_vendor="$($COMPOSE -f "$COMPOSE_FILE" exec -T web python manage.py shell -c "from django.db import connection; print(connection.vendor)")"
  if [ "$initial_database_vendor" != "postgresql" ]; then
    echo "historical initial-install requires PostgreSQL (actual: ${initial_database_vendor:-unknown})" >&2
    exit 1
  fi
  COMPOSE_FILE="$COMPOSE_FILE" ./deploy/historical_runner_preflight.sh --initial-install
  initial_schema_gate="$($COMPOSE -f "$COMPOSE_FILE" exec -T web python manage.py shell -c "from django.db import connection; c=connection.cursor(); c.execute(\"SELECT EXISTS (SELECT 1 FROM django_migrations WHERE app='stable' AND name IN ('0070_horse_identity_evidence_commit_receipt','0071_historical_calendar_release_b'))\"); print('historical-initial-install-0070-or-later' if c.fetchone()[0] else 'historical-initial-install-pre-0070')")"
  if [ "$initial_schema_gate" != "historical-initial-install-pre-0070" ]; then
    echo "historical initial-install is restricted to pre-0070 schema" >&2
    exit 1
  fi
else
  COMPOSE_FILE="$COMPOSE_FILE" ./deploy/historical_runner_preflight.sh
fi

"$COMPOSE" -f "$COMPOSE_FILE" pull nginx
"$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps nginx nginx -t
UMANEWS_RELEASE_COMMIT="$(git rev-parse HEAD)"
case "$UMANEWS_RELEASE_COMMIT" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "release commit must be a 40-character lowercase git OID" >&2; exit 1 ;;
esac
export UMANEWS_RELEASE_COMMIT
"$COMPOSE" -f "$COMPOSE_FILE" build web

if [ "$INITIAL_INSTALL_MODE" = "true" ]; then
  COMPOSE_FILE="$COMPOSE_FILE" ./deploy/run_historical_initial_install_release.sh
  exit 0
fi

REPAIR_RUNTIME_ROOT="$ROOT_DIR/runtime/migration_history_repair"
if [ -L "$REPAIR_RUNTIME_ROOT" ]; then echo "repair runtime root must not be a symlink" >&2; exit 1; fi
PREFLIGHT_ROOT="$REPAIR_RUNTIME_ROOT/preflight"
if [ -L "$PREFLIGHT_ROOT" ]; then echo "preflight root must not be a symlink" >&2; exit 1; fi
umask 077
mkdir -p "$PREFLIGHT_ROOT"
chmod 700 "$PREFLIGHT_ROOT"
RELEASE_B_PREFLIGHT_DIR="$(mktemp -d "$PREFLIGHT_ROOT/before.XXXXXXXX")"
RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$RELEASE_B_PREFLIGHT_DIR/preflight.json"
export RELEASE_B_PREFLIGHT_ARTIFACT_PATH
unset RELEASE_B_EXPECTED_MIGRATION_LEAF_SET
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CANDIDATE_COMMIT="$UMANEWS_RELEASE_COMMIT" RELEASE_B_PREFLIGHT_ACTION=deploy \
  ./deploy/run_historical_calendar_release_b_preflight.sh
RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(sed -n 's/.*"artifact_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH")"
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed -n 's/.*"database_identity_sha256":"\([0-9a-f]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
RESTRICTED_RECOVERY_ATTEMPT_MODE="$(sed -n 's/.*"recovery_intent_mode":"\([a-z-]*\)".*/\1/p' "$RELEASE_B_PREFLIGHT_ARTIFACT_PATH" | head -n 1)"
EXPECTED_CANDIDATE_COMMIT="$UMANEWS_RELEASE_COMMIT"
EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_CANDIDATE_COMMIT EXPECTED_CANDIDATE_IMAGE_ID EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 RESTRICTED_RECOVERY_ATTEMPT_MODE
if [ "${#RELEASE_B_PREFLIGHT_ARTIFACT_SHA256}" -ne 64 ]; then echo "invalid artifact SHA" >&2; exit 1; fi
if [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ]; then echo "invalid database identity SHA" >&2; exit 1; fi

COMPOSE_FILE="$COMPOSE_FILE" RELEASE_ACTION=deploy ./deploy/run_application_release.sh
