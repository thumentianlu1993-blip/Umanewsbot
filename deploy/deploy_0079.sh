#!/bin/sh
# 精确0078→0079／0079同schema前向发布；旧世代恢复仍用原控制镜像。
set -eu
ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.lowcost.yml}"
case "$COMPOSE_FILE" in docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;; *) exit 1 ;; esac
export COMPOSE_FILE
[ -f .env ] || { echo "configuration missing" >&2; exit 1; }
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
DEPLOYMENT_LOCK_ACTION=deploy ./deploy/deployment_lock.sh acquire
release_lock() { ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true; }
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
python3 ./deploy/ensure_migration_history_repair_runtime.py
mode="${1:-deploy}"
case "$mode" in deploy|resume) ;; *) echo "use deploy or resume" >&2; exit 1 ;; esac
./deploy/verify_persistent_release_mounts.sh
EXPECTED_CANDIDATE_COMMIT="$(git rev-parse HEAD)"
export EXPECTED_CANDIDATE_COMMIT
UMANEWS_RELEASE_COMMIT="$EXPECTED_CANDIDATE_COMMIT"
export UMANEWS_RELEASE_COMMIT
if [ "$mode" = deploy ]; then
  python3 ./deploy/release_0079.py guard
  ./deploy/check_restricted_recovery_marker.sh
  ./deploy/historical_runner_preflight.sh
  ./deploy/docker/compose-wrapper.sh -f "$COMPOSE_FILE" build web
  EXPECTED_CANDIDATE_IMAGE_ID="$(docker image inspect --format '{{.Id}}' umanewsbot:prod)"
  export EXPECTED_CANDIDATE_IMAGE_ID
  umask 077
  mkdir -p runtime/migration_history_repair/preflight
  chmod 700 runtime/migration_history_repair/preflight
  dir="$(mktemp -d "$ROOT_DIR/runtime/migration_history_repair/preflight/before-0079.XXXXXXXX")"
  RELEASE_B_PREFLIGHT_ARTIFACT_PATH="$dir/preflight.json"
  RELEASE_B_PREFLIGHT_ACTION=deploy
  export RELEASE_B_PREFLIGHT_ARTIFACT_PATH RELEASE_B_PREFLIGHT_ACTION
  python3 ./deploy/run_release_0079_preflight.py >/dev/null
  RELEASE_B_PREFLIGHT_ARTIFACT_SHA256="$(python3 -c 'import json,os; print(json.load(open(os.environ["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"]))["artifact_sha256"])')"
  EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(python3 -c 'import json,os; print(json.load(open(os.environ["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"]))["database_identity_sha256"])')"
  export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_PRODUCTION_DB_IDENTITY_SHA256
  python3 ./deploy/release_0079.py release
else
  # 恢复必须给原intent SHA和镜像；不重建或重新生成备份。
  : "${RELEASE_0079_INTENT_PATH:?original intent required}"
  : "${RELEASE_0079_INTENT_SHA256:?original intent SHA required}"
  : "${EXPECTED_CANDIDATE_IMAGE_ID:?original candidate image required}"
  python3 ./deploy/release_0079.py resume
fi
