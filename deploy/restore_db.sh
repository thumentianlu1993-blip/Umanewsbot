#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found."
  exit 1
fi

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/restore_db.sh <backup-file.sql.gz>"
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE"
  exit 1
fi

set -a
. ./.env
set +a

gzip -dc "$BACKUP_FILE" | docker run --rm -i \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  postgres:16 \
  psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "Restore completed from $BACKUP_FILE"

