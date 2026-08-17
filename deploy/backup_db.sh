#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found."
  exit 1
fi

# A caller such as a release wrapper must be able to force a local-only
# rollback snapshot even when the persistent production .env defaults to OSS.
CALLER_BACKUP_TARGET="${BACKUP_TARGET:-}"
CALLER_COMPOSE_FILE="${COMPOSE_FILE:-}"
CALLER_EXPECTED_COMPOSE_PROJECT="${EXPECTED_COMPOSE_PROJECT:-}"

set -a
. ./.env
set +a

BACKUP_DIR="${BACKUP_DIR:-./backups/db}"
BACKUP_TARGET="${BACKUP_TARGET:-local}"
if [ -n "$CALLER_BACKUP_TARGET" ]; then
  BACKUP_TARGET="$CALLER_BACKUP_TARGET"
fi
case "$BACKUP_TARGET" in
  local|oss) ;;
  *)
    echo "Unsupported BACKUP_TARGET: $BACKUP_TARGET" >&2
    exit 1
    ;;
esac

COMPOSE_FILE="${COMPOSE_FILE:-}"
if [ -n "$CALLER_COMPOSE_FILE" ]; then
  COMPOSE_FILE="$CALLER_COMPOSE_FILE"
fi
[ -n "$COMPOSE_FILE" ] || {
  echo "COMPOSE_FILE is required; choose docker-compose.prod.yml (RDS) or docker-compose.prod.lowcost.yml." >&2
  exit 1
}
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *)
    echo "Unsupported COMPOSE_FILE: $COMPOSE_FILE" >&2
    exit 1
    ;;
esac
if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

EXPECTED_COMPOSE_PROJECT="${EXPECTED_COMPOSE_PROJECT:-}"
if [ -n "$CALLER_EXPECTED_COMPOSE_PROJECT" ]; then
  EXPECTED_COMPOSE_PROJECT="$CALLER_EXPECTED_COMPOSE_PROJECT"
fi
case "$EXPECTED_COMPOSE_PROJECT" in
  *[!a-z0-9_-]*|"")
    echo "EXPECTED_COMPOSE_PROJECT is required and must use lowercase letters, digits, underscore, or hyphen." >&2
    exit 1
    ;;
esac
COMPOSE="$ROOT_DIR/deploy/docker/compose-wrapper.sh"
[ -x "$COMPOSE" ] || {
  echo "Compose wrapper is missing or not executable: $COMPOSE" >&2
  exit 1
}
compose_project() {
  "$COMPOSE" -f "$COMPOSE_FILE" --project-directory "$ROOT_DIR" \
    --project-name "$EXPECTED_COMPOSE_PROJECT" "$@"
}

umask 077
mkdir -p "$BACKUP_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/rds_${POSTGRES_DB}_${TS}_$$.dump"
TMP_FILE="$(mktemp "$BACKUP_DIR/.rds_${POSTGRES_DB}_${TS}.dump.tmp.XXXXXX")"
TOC_FILE="$(mktemp "$BACKUP_DIR/.rds_${POSTGRES_DB}_${TS}.toc.tmp.XXXXXX")"

cleanup() {
  rm -f "$TMP_FILE" "$TOC_FILE"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Low-cost production owns PostgreSQL in Compose, so use that existing service.
# RDS production has no db service; there the isolated PostgreSQL client can
# reach the external hostname directly.  The password is passed through the
# environment and never interpolated into the command line.
case "$COMPOSE_FILE" in
  docker-compose.prod.lowcost.yml)
    compose_project exec -T db \
      pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --format=custom --no-owner --no-privileges > "$TMP_FILE"
    ;;
  docker-compose.prod.yml)
    PGPASSWORD="$POSTGRES_PASSWORD"
    export PGPASSWORD
    docker run --rm -e PGPASSWORD postgres:16 \
      pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --format=custom --no-owner --no-privileges > "$TMP_FILE"
    ;;
esac

if [ ! -s "$TMP_FILE" ]; then
  echo "Backup archive is empty." >&2
  exit 1
fi

# Validate the archive with the matching PostgreSQL client before atomically
# publishing the final path.
case "$COMPOSE_FILE" in
  docker-compose.prod.lowcost.yml)
    compose_project exec -T db pg_restore -l \
      < "$TMP_FILE" > "$TOC_FILE"
    ;;
  docker-compose.prod.yml)
    docker run --rm -i postgres:16 pg_restore -l \
      < "$TMP_FILE" > "$TOC_FILE"
    ;;
esac
TOC_COUNT="$(wc -l < "$TOC_FILE" | tr -d ' ')"
case "$TOC_COUNT" in
  ''|*[!0-9]*|0)
    echo "Backup archive catalog is empty." >&2
    exit 1
    ;;
esac

chmod 600 "$TMP_FILE"
mv "$TMP_FILE" "$OUT_FILE"

if command -v sha256sum >/dev/null 2>&1; then
  BACKUP_SHA256="$(sha256sum "$OUT_FILE" | awk '{print $1}')"
else
  BACKUP_SHA256="$(shasum -a 256 "$OUT_FILE" | awk '{print $1}')"
fi

echo "Backup created: $OUT_FILE"
echo "Backup SHA-256: $BACKUP_SHA256"
echo "Backup TOC entries: $TOC_COUNT"

if [ "$BACKUP_TARGET" = "oss" ]; then
  OUT_FILE_ABS="$(CDPATH= cd -- "$(dirname "$OUT_FILE")" && pwd -P)/$(basename "$OUT_FILE")"
  compose_project run --rm --no-deps -T \
    -v "$OUT_FILE_ABS:/run/umanews-backup.dump:ro" \
    web python /app/deploy/upload_backup_to_oss.py /run/umanews-backup.dump
fi
