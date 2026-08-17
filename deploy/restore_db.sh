#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found."
  exit 1
fi

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/restore_db.sh <backup-file.dump|backup-file.sql.gz>"
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE"
  exit 1
fi

CALLER_COMPOSE_FILE="${COMPOSE_FILE:-}"
CALLER_EXPECTED_COMPOSE_PROJECT="${EXPECTED_COMPOSE_PROJECT:-}"
set -a
. ./.env
set +a

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

case "$BACKUP_FILE" in
  *.dump)
    case "$COMPOSE_FILE" in
      docker-compose.prod.lowcost.yml)
        compose_project exec -T db pg_restore -l \
          < "$BACKUP_FILE" >/dev/null
        compose_project exec -T db \
          pg_restore --clean --if-exists --exit-on-error --single-transaction \
          --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
          < "$BACKUP_FILE"
        ;;
      docker-compose.prod.yml)
        PGPASSWORD="$POSTGRES_PASSWORD"
        export PGPASSWORD
        docker run --rm -i postgres:16 pg_restore -l \
          < "$BACKUP_FILE" >/dev/null
        docker run --rm -i -e PGPASSWORD postgres:16 \
          pg_restore --clean --if-exists --exit-on-error --single-transaction \
          --no-owner --no-privileges -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
          -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_FILE"
        ;;
    esac
    ;;
  *.sql.gz|*.gz)
    gzip -t "$BACKUP_FILE"
    SQL_FILE="$(mktemp "${TMPDIR:-/tmp}/umanews-restore.XXXXXX.sql")"
    cleanup() { rm -f "$SQL_FILE"; }
    trap cleanup EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    gzip -dc "$BACKUP_FILE" > "$SQL_FILE"
    case "$COMPOSE_FILE" in
      docker-compose.prod.lowcost.yml)
        compose_project exec -T db \
          psql --single-transaction -v ON_ERROR_STOP=1 \
          -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SQL_FILE"
        ;;
      docker-compose.prod.yml)
        PGPASSWORD="$POSTGRES_PASSWORD"
        export PGPASSWORD
        docker run --rm -i -e PGPASSWORD postgres:16 \
          psql --single-transaction -v ON_ERROR_STOP=1 \
          -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
          -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SQL_FILE"
        ;;
    esac
    ;;
  *)
    echo "Unsupported backup format: $BACKUP_FILE" >&2
    exit 1
    ;;
esac

echo "Restore completed from $BACKUP_FILE"
