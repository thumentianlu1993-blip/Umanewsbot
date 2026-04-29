#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/rollback_lowcost.sh <git-ref>"
  exit 1
fi

TARGET_REF="$1"

git fetch --all --tags
git checkout "$TARGET_REF"
COMPOSE="./deploy/docker/compose-wrapper.sh"

"$COMPOSE" -f docker-compose.prod.lowcost.yml build web
"$COMPOSE" -f docker-compose.prod.lowcost.yml up -d --remove-orphans
"$COMPOSE" -f docker-compose.prod.lowcost.yml exec web python manage.py migrate --noinput
