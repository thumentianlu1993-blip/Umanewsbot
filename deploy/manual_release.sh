#!/bin/sh
# Protected manual release entry for existing environments.
#
# After the removal of web-entrypoint migrations, `compose up web` no longer
# prepares the schema. Use this top-level command to run the single release
# task by hand. It acquires the same deployment lock, refuses to proceed
# while any application service (web, worker, beat, race_live_worker) is
# running, restarting or unreadable, and leaves all application services
# stopped afterwards. Service recovery must go through the audited
# deploy/rollback orchestration, never through this script.
#
# Environment:
#   COMPOSE_FILE  docker-compose.prod.yml or docker-compose.prod.lowcost.yml
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE="./deploy/docker/compose-wrapper.sh"

COMPOSE_FILE="${COMPOSE_FILE:-}"
case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *)
    echo "COMPOSE_FILE must be docker-compose.prod.yml or docker-compose.prod.lowcost.yml" >&2
    exit 1
    ;;
esac

DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN

# Install the release trap only after a successful acquire; a contender that
# loses the race must never touch the winner's lock.
if ! COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=manual-release ./deploy/deployment_lock.sh acquire; then
  echo "manual release: another deployment holds the lock; refusing to proceed" >&2
  exit 1
fi
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Fail closed if any application service is running, restarting, or its
# state cannot be read. No Compose `run` may happen before this gate. A
# failing `compose ps -q` probe is a probe failure, never "not running".
for service in web worker beat race_live_worker; do
  if ! ps_output="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q "$service" 2>/dev/null)"; then
    echo "manual release: cannot list $service containers; failing closed" >&2
    exit 1
  fi
  cid="$(printf '%s' "$ps_output" | head -n 1 | tr -d '[:space:]')"
  if [ -z "$cid" ]; then
    continue
  fi
  state="$(docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.Status}}' "$cid" 2>/dev/null)" || {
    echo "manual release: cannot read $service container state; failing closed" >&2
    exit 1
  }
  running="$(printf '%s' "$state" | awk '{print $1}')"
  health="$(printf '%s' "$state" | awk '{print $2}')"
  status="$(printf '%s' "$state" | awk '{print $3}')"
  case "$running" in
    true|false) ;;
    *)
      echo "manual release: unreadable $service container state; failing closed" >&2
      exit 1
      ;;
  esac
  if [ "$running" = "true" ] || [ "$health" = "restarting" ] || [ "$status" = "restarting" ]; then
    echo "manual release: $service is still running or restarting; stop it via the audited orchestration first" >&2
    exit 1
  fi
done

COMPOSE_FILE="$COMPOSE_FILE" ./deploy/run_release_tasks.sh
echo "manual release: release task completed; all application services remain stopped"
