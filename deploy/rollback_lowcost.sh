#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ "${1:-}" = "" ]; then
  echo "Usage: ./deploy/rollback_lowcost.sh <git-ref>"
  exit 1
fi

TARGET_REF="$1"

COMPOSE="./deploy/docker/compose-wrapper.sh"
COMPOSE_FILE="docker-compose.prod.lowcost.yml"

# Acquire the host-local deployment lock before any stateful action. The
# release trap is installed only after a successful acquire so a contender
# that loses the race never touches the winner's lock.
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=rollback ./deploy/deployment_lock.sh acquire
release_lock() {
  ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

git fetch --all --tags
# Resolve the target once and bind every later check to the immutable OID.
TARGET_OID="$(git rev-parse --verify "$TARGET_REF^{commit}")"
# The resolved OID must be a single 40-character lowercase hex commit ID;
# reject empty, multi-line or otherwise malformed output before any
# cat-file, preflight or checkout.
case "$TARGET_OID" in
  *[!0-9a-f]*)
    echo "rollback: resolved OID is malformed; refusing before any check" >&2
    exit 1
    ;;
esac
if [ "${#TARGET_OID}" -ne 40 ]; then
  echo "rollback: resolved OID is not a 40-character commit id; refusing before any check" >&2
  exit 1
fi
# The target must carry the release contract and every v1 helper; refuse
# before any checkout or service stop. Forward migrate is NOT a database
# rollback.
for helper in \
  deploy/release_contract_v1 \
  deploy/run_application_release.sh \
  deploy/deployment_lock.sh \
  deploy/run_release_tasks.sh \
  deploy/wait_for_compose_service_healthy.sh \
  deploy/wait_for_celery_drain.sh \
  deploy/docker/run-release-tasks.sh \
  deploy/docker/start-web.sh \
  deploy/docker/compose-wrapper.sh
do
  if ! git cat-file -e "$TARGET_OID:$helper"; then
    echo "rollback: target is missing required v1 helper $helper; refusing before checkout" >&2
    exit 1
  fi
done

# The generic rollback release task cannot unapply a migration that is absent
# from the target checkout. Cross-schema rollback needs a separately reviewed
# stopped-service procedure; fail before preflight, checkout, or service stop.
if ! git cat-file -e "$TARGET_OID:server/stable/migrations/0071_historical_calendar_release_b.py"; then
  echo "rollback: target predates Release B schema; use the reviewed cross-schema recovery procedure" >&2
  exit 1
fi

# The existing web is still running here, so the historical runner preflight
# preconditions hold (same semantics as deploy; no --initial-install branch).
COMPOSE_FILE="$COMPOSE_FILE" ./deploy/historical_runner_preflight.sh

git checkout "$TARGET_OID"
UMANEWS_RELEASE_COMMIT="$TARGET_OID"
export UMANEWS_RELEASE_COMMIT
"$COMPOSE" -f "$COMPOSE_FILE" build web

# This generic path is B-to-B only: it keeps 0071 applied. Validate the target
# image against the current Release B schema; reverse compatibility belongs
# exclusively to the separately reviewed cross-schema recovery procedure.
COMPOSE_FILE="$COMPOSE_FILE" EXPECTED_CANDIDATE_COMMIT="$TARGET_OID" \
  ./deploy/run_historical_calendar_release_b_preflight.sh

COMPOSE_FILE="$COMPOSE_FILE" RELEASE_ACTION=rollback ./deploy/run_application_release.sh
