#!/bin/sh
set -eu

[ "${CONFIRM_INFRASTRUCTURE_BOOTSTRAP:-}" = "create-db-redis-network" ] || {
  echo "set CONFIRM_INFRASTRUCTURE_BOOTSTRAP=create-db-redis-network for explicit first-time provisioning" >&2
  exit 1
}
ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="${1:-docker-compose.prod.lowcost.yml}"
if "$COMPOSE" -f "$COMPOSE_FILE" config --services | grep -qx db; then
  "$COMPOSE" -f "$COMPOSE_FILE" up -d db redis
else
  "$COMPOSE" -f "$COMPOSE_FILE" up -d redis
fi
echo "initial database, Redis and shared Compose network provisioned"
