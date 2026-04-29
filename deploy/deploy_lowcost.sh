#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found. Copy .env.example to .env and fill values first."
  exit 1
fi

COMPOSE="./deploy/docker/compose-wrapper.sh"

"$COMPOSE" -f docker-compose.prod.lowcost.yml pull db redis nginx
"$COMPOSE" -f docker-compose.prod.lowcost.yml build web
"$COMPOSE" -f docker-compose.prod.lowcost.yml up -d --remove-orphans
"$COMPOSE" -f docker-compose.prod.lowcost.yml exec web python manage.py migrate --noinput
"$COMPOSE" -f docker-compose.prod.lowcost.yml exec web python manage.py collectstatic --noinput
"$COMPOSE" -f docker-compose.prod.lowcost.yml ps
