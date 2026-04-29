#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found. Copy .env.example to .env and fill production values first."
  exit 1
fi

COMPOSE="./deploy/docker/compose-wrapper.sh"

"$COMPOSE" -f docker-compose.prod.yml pull
"$COMPOSE" -f docker-compose.prod.yml build web
"$COMPOSE" -f docker-compose.prod.yml up -d --remove-orphans
"$COMPOSE" -f docker-compose.prod.yml exec web python manage.py migrate --noinput
"$COMPOSE" -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
"$COMPOSE" -f docker-compose.prod.yml ps
