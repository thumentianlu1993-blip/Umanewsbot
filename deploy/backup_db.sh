#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found."
  exit 1
fi

set -a
. ./.env
set +a

BACKUP_DIR="${BACKUP_DIR:-./backups/db}"
mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="$BACKUP_DIR/rds_${POSTGRES_DB}_${TS}.sql.gz"
BACKUP_TARGET="${BACKUP_TARGET:-local}"

docker run --rm \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  postgres:16 \
  sh -lc "pg_dump -h '$POSTGRES_HOST' -p '$POSTGRES_PORT' -U '$POSTGRES_USER' -d '$POSTGRES_DB' --no-owner --no-privileges | gzip -c" \
  > "$OUT_FILE"

echo "Backup created: $OUT_FILE"

if [ "$BACKUP_TARGET" = "oss" ]; then
  python3 ./deploy/upload_backup_to_oss.py "$OUT_FILE"
fi
