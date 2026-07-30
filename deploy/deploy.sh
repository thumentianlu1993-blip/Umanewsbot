#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env not found. Copy .env.example to .env and fill production values first."
  exit 1
fi

COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="docker-compose.prod.yml"

# Acquire the host-local deployment lock before any stateful action; the lock
# covers the historical preflight as well (spec 5.4). The release trap is
# installed only after a successful acquire so a contender that loses the
# race never touches the winner's lock.
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=deploy ./deploy/deployment_lock.sh acquire
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "${HISTORICAL_RUNNER_INITIAL_INSTALL:-false}" = "true" ]; then
  COMPOSE_FILE="$COMPOSE_FILE" ./deploy/historical_runner_preflight.sh --initial-install
else
  COMPOSE_FILE="$COMPOSE_FILE" ./deploy/historical_runner_preflight.sh
fi

"$COMPOSE" -f "$COMPOSE_FILE" pull nginx
"$COMPOSE" -f "$COMPOSE_FILE" build web

COMPOSE_FILE="$COMPOSE_FILE" RELEASE_ACTION=deploy ./deploy/run_application_release.sh
