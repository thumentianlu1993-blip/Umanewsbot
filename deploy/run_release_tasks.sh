#!/bin/sh
# Protected host wrapper for the single one-shot release task.
#
# This is an internal entry: it refuses to run without the current deployment
# lock owner token, and verifies the lock before any Compose call. Operators
# must use deploy/deploy.sh, deploy/rollback*.sh or deploy/manual_release.sh
# instead of calling this wrapper directly.
#
# Environment:
#   COMPOSE_FILE            docker-compose.prod.yml or docker-compose.prod.lowcost.yml
#   DEPLOYMENT_LOCK_TOKEN   owner token of the held deployment lock
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *)
    echo "COMPOSE_FILE must be docker-compose.prod.yml or docker-compose.prod.lowcost.yml" >&2
    exit 1
    ;;
esac

if [ -z "${DEPLOYMENT_LOCK_TOKEN:-}" ]; then
  echo "DEPLOYMENT_LOCK_TOKEN is required; run_release_tasks.sh is a protected internal entry" >&2
  exit 1
fi

# Verify the deployment lock before any Compose call.
./deploy/deployment_lock.sh verify

echo "release task: starting one-shot container (compose=$COMPOSE_FILE)"
./deploy/docker/compose-wrapper.sh -f "$COMPOSE_FILE" run --rm --no-deps web /app/deploy/docker/run-release-tasks.sh
echo "release task: completed"
