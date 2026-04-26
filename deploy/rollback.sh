#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/rollback.sh <git-ref>"
  exit 1
fi

TARGET_REF="$1"

git fetch --all --tags
git checkout "$TARGET_REF"
docker compose -f docker-compose.prod.yml build web
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput

