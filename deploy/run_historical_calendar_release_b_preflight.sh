#!/bin/sh
# Run the Release B forward schema preflight from the freshly built candidate
# image while every Release A long-lived service is still untouched.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *) echo "COMPOSE_FILE is not allowlisted" >&2; exit 1 ;;
esac

EXPECTED_CANDIDATE_COMMIT="${EXPECTED_CANDIDATE_COMMIT:-}"
case "$EXPECTED_CANDIDATE_COMMIT" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "EXPECTED_CANDIDATE_COMMIT must be a lowercase 40-character OID" >&2; exit 1 ;;
esac

if [ -z "${DEPLOYMENT_LOCK_TOKEN:-}" ]; then
  echo "DEPLOYMENT_LOCK_TOKEN is required" >&2
  exit 1
fi
EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="${EXPECTED_PRODUCTION_DB_IDENTITY_SHA256:-}"
case "$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" in
  *[!0-9a-f]*|"")
    echo "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 must be a lowercase SHA-256" >&2
    exit 1
    ;;
esac
if [ "${#EXPECTED_PRODUCTION_DB_IDENTITY_SHA256}" -ne 64 ]; then
  echo "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256 must be a lowercase SHA-256" >&2
  exit 1
fi
./deploy/deployment_lock.sh verify

SCHEMA_PREFLIGHT_DIRECTION="${SCHEMA_PREFLIGHT_DIRECTION:-forward}"
case "$SCHEMA_PREFLIGHT_DIRECTION" in
  forward|reverse) ;;
  *) echo "SCHEMA_PREFLIGHT_DIRECTION must be forward or reverse" >&2; exit 1 ;;
esac

IMAGE_NAME="umanewsbot:prod"
EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_NAME")"
IMAGE_COMMIT="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_NAME")"
if [ "$IMAGE_COMMIT" != "$EXPECTED_CANDIDATE_COMMIT" ]; then
  echo "candidate image revision does not match expected commit" >&2
  exit 1
fi

./deploy/docker/compose-wrapper.sh -f "$COMPOSE_FILE" run --rm --no-deps \
  -e "UMANEWS_RELEASE_COMMIT=$EXPECTED_CANDIDATE_COMMIT" \
  -e "UMANEWS_RELEASE_IMAGE_ID=$EXPECTED_CANDIDATE_IMAGE_ID" \
  web python manage.py check_historical_calendar_release_b_schema \
  --direction="$SCHEMA_PREFLIGHT_DIRECTION" --json \
  --expected-migration-leaf=stable.0070_horse_identity_evidence_commit_receipt,stable.0071_historical_calendar_release_b \
  --expected-database-identity-sha256="$EXPECTED_PRODUCTION_DB_IDENTITY_SHA256" \
  --candidate-commit="$EXPECTED_CANDIDATE_COMMIT" \
  --candidate-image-id="$EXPECTED_CANDIDATE_IMAGE_ID"
