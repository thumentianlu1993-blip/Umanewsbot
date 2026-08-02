#!/bin/sh
set -eu

PRODUCTION_ROOT="/opt/umanewsbot"
COMPOSE_FILE="docker-compose.prod.lowcost.yml"
PRODUCTION_IMAGE="umanewsbot:prod"
MIN_MEMORY_KIB=$((1536 * 1024))
LOW_SWAP_MEMORY_KIB=$((2048 * 1024))
MIN_SWAP_KIB=$((1024 * 1024))
MIN_DISK_KIB=$((6 * 1024 * 1024))

PHASE="${1:-}"
case "$PHASE" in
  prepare|start-beat) ;;
  *)
    echo "用法: $0 prepare|start-beat" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd -P)"
DISCOVERED_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
TEST_MODE="${RACE_LIVE_P0_TEST_MODE:-0}"

fail_test_mode() {
  echo "测试模式 test mode 安全校验失败：仅允许临时根和根内有效 sentinel 哨兵。" >&2
  exit 2
}

path_is_within_root() {
  candidate_path="$1"
  case "$candidate_path" in
    "$ROOT_DIR"|"$ROOT_DIR"/*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "$DISCOVERED_ROOT" = "$PRODUCTION_ROOT" ]; then
  if [ "$TEST_MODE" != "0" ] \
    || [ -n "${RACE_LIVE_P0_TEST_SENTINEL:-}" ] \
    || [ -n "${RACE_LIVE_P0_MEMINFO_FILE:-}" ] \
    || [ -n "${RACE_LIVE_P0_REPOSITORY_PATH:-}" ] \
    || [ -n "${RACE_LIVE_P0_DOCKER_DATA_PATH:-}" ] \
    || [ -n "${RACE_LIVE_P0_TEST_OBSERVATION_INTERVAL_SECONDS:-}" ] \
    || env | grep -q '^P0_FAKE_'; then
    echo "生产根禁止启用 test mode 或任何 fake path 覆盖。" >&2
    exit 2
  fi
  ROOT_DIR="$PRODUCTION_ROOT"
  MEMINFO_FILE="/proc/meminfo"
  REPOSITORY_PATH="$PRODUCTION_ROOT"
  DOCKER_DATA_PATH=""
else
  [ "$TEST_MODE" = "1" ] || fail_test_mode
  [ -n "${TMPDIR:-}" ] && [ -d "$TMPDIR" ] || fail_test_mode
  TEST_TEMP_ROOT="$(CDPATH= cd -- "$TMPDIR/.." 2>/dev/null && pwd -P)" \
    || fail_test_mode
  [ "$TEST_TEMP_ROOT" = "$DISCOVERED_ROOT" ] || fail_test_mode

  ROOT_DIR="$DISCOVERED_ROOT"
  if [ -e "$ROOT_DIR/$COMPOSE_FILE" ]; then
    echo "测试模式 test mode 拒绝包含生产 $COMPOSE_FILE 的根目录。" >&2
    exit 2
  fi

  TEST_SENTINEL="${RACE_LIVE_P0_TEST_SENTINEL:-}"
  [ -n "$TEST_SENTINEL" ] && [ -f "$TEST_SENTINEL" ] \
    && [ ! -L "$TEST_SENTINEL" ] || fail_test_mode
  TEST_SENTINEL_DIR="$(CDPATH= cd -- "$(dirname "$TEST_SENTINEL")" 2>/dev/null && pwd -P)" \
    || fail_test_mode
  TEST_SENTINEL_PATH="$TEST_SENTINEL_DIR/$(basename "$TEST_SENTINEL")"
  path_is_within_root "$TEST_SENTINEL_PATH" || fail_test_mode
  IFS= read -r TEST_SENTINEL_VALUE < "$TEST_SENTINEL" || fail_test_mode
  [ "$TEST_SENTINEL_VALUE" = "race-live-p0-deployment-contract-test" ] \
    || fail_test_mode

  TEST_MEMINFO_INPUT="${RACE_LIVE_P0_MEMINFO_FILE:-$ROOT_DIR/state/meminfo}"
  [ -f "$TEST_MEMINFO_INPUT" ] || fail_test_mode
  TEST_MEMINFO_DIR="$(
    CDPATH= cd -- "$(dirname "$TEST_MEMINFO_INPUT")" 2>/dev/null && pwd -P
  )" || fail_test_mode
  MEMINFO_FILE="$TEST_MEMINFO_DIR/$(basename "$TEST_MEMINFO_INPUT")"

  TEST_REPOSITORY_INPUT="${RACE_LIVE_P0_REPOSITORY_PATH:-$ROOT_DIR}"
  REPOSITORY_PATH="$(
    CDPATH= cd -- "$TEST_REPOSITORY_INPUT" 2>/dev/null && pwd -P
  )" || fail_test_mode

  TEST_DOCKER_INPUT="${RACE_LIVE_P0_DOCKER_DATA_PATH:-}"
  if [ -n "$TEST_DOCKER_INPUT" ]; then
    TEST_DOCKER_CANONICAL="$(
      CDPATH= cd -- "$TEST_DOCKER_INPUT" 2>/dev/null && pwd -P
    )" || fail_test_mode
    DOCKER_DATA_PATH="$TEST_DOCKER_INPUT"
  else
    TEST_DOCKER_CANONICAL=""
    DOCKER_DATA_PATH=""
  fi
  path_is_within_root "$MEMINFO_FILE" || fail_test_mode
  path_is_within_root "$REPOSITORY_PATH" || fail_test_mode
  if [ -n "$TEST_DOCKER_CANONICAL" ]; then
    path_is_within_root "$TEST_DOCKER_CANONICAL" || fail_test_mode
  fi
fi

if [ "$TEST_MODE" = "1" ]; then
  HEALTH_TIMEOUT_SECONDS=0
  OBSERVATION_INTERVAL_SECONDS="$(
    printf '%s' "${RACE_LIVE_P0_TEST_OBSERVATION_INTERVAL_SECONDS:-0}"
  )"
  [ "$OBSERVATION_INTERVAL_SECONDS" = "0" ] || fail_test_mode
else
  HEALTH_TIMEOUT_SECONDS=180
  OBSERVATION_INTERVAL_SECONDS=60
fi

cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/.env"
COMPOSE="$ROOT_DIR/deploy/docker/compose-wrapper.sh"
DRAIN_SCRIPT="$ROOT_DIR/deploy/wait_for_celery_drain.sh"
HISTORICAL_PREFLIGHT="$ROOT_DIR/deploy/historical_runner_preflight.sh"

[ -f "$ENV_FILE" ] || {
  echo "缺少生产环境文件 .env。" >&2
  exit 1
}
[ -x "$COMPOSE" ] || {
  echo "Compose 包装脚本不存在或不可执行。" >&2
  exit 1
}

# 接入共享部署锁（与 deploy.sh 同型）：覆盖 prepare/start-beat 全部有状态路径。
# acquire 成功才安装 release trap；竞争失败者零有状态调用且不得触碰赢家锁。
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
release_lock() {
  COMPOSE_FILE="$COMPOSE_FILE" "$ROOT_DIR"/deploy/deployment_lock.sh release >/dev/null 2>&1 || true
}
if ! COMPOSE_FILE="$COMPOSE_FILE" DEPLOYMENT_LOCK_ACTION=p0-closed-admission \
  "$ROOT_DIR/deploy/deployment_lock.sh" acquire; then
  echo "另一部署/回滚/恢复流程持有部署锁；拒绝继续。" >&2
  exit 1
fi
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

STATE="PRE_STOP_PREFLIGHT"
INITIAL_BEAT_STATE="unknown"
WORKER_STOPPED=0
ROLLBACK_IMAGE=""
IMAGE_TAG_MAY_HAVE_CHANGED=0
CANDIDATE_WEB_STARTED=0
BEAT_STARTED_BY_COMMAND=0
STOP_ATTEMPTED=0
STOP_UNCHANGED_CONFIRMED=0
STOP_OBSERVED_STATE="unknown"

read_env_value() {
  env_key="$1"
  env_count="$(
    awk -v key="$env_key" '
      /^[[:space:]]*#/ { next }
      {
        line = $0
        sub(/^[[:space:]]*export[[:space:]]+/, "", line)
        if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
          count += 1
        }
      }
      END { print count + 0 }
    ' "$ENV_FILE"
  )"
  [ "$env_count" -eq 1 ] || return 1
  awk -v key="$env_key" '
    /^[[:space:]]*#/ { next }
    {
      line = $0
      sub(/^[[:space:]]*export[[:space:]]+/, "", line)
      if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
        sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "", line)
        sub(/[[:space:]]*$/, "", line)
        print line
      }
    }
  ' "$ENV_FILE"
}

verify_closed_env_file() {
  scheduler_value="$(read_env_value RACE_LIVE_SCHEDULER_ENABLED)" || {
    echo "关闭态门禁失败：scheduler 值缺失或重复。" >&2
    return 1
  }
  monitor_value="$(read_env_value RACE_LIVE_MONITOR_ENABLED)" || {
    echo "关闭态门禁失败：monitor 值缺失或重复。" >&2
    return 1
  }
  runner_value="$(read_env_value RACE_LIVE_RUNNER_MODE)" || {
    echo "关闭态门禁失败：runner mode 值缺失或重复。" >&2
    return 1
  }
  if [ "$scheduler_value" != "false" ] \
    || [ "$monitor_value" != "false" ] \
    || [ "$runner_value" != "disabled" ]; then
    echo "关闭态门禁失败：scheduler/monitor/runner 未精确处于 false/false/disabled。" >&2
    return 1
  fi
  echo "关闭态 flags 校验通过：scheduler=false monitor=false runner=disabled。"
}

get_service_state() {
  queried_service="$1"
  if ! service_snapshot="$(
    "$COMPOSE" -f "$COMPOSE_FILE" ps --format json "$queried_service" 2>/dev/null
  )"; then
    printf '%s\n' "unknown"
    return 0
  fi

  compact_snapshot="$(printf '%s' "$service_snapshot" | tr -d '[:space:]')"
  case "$compact_snapshot" in
    ""|"[]")
      printf '%s\n' "absent"
      return 0
      ;;
  esac

  state_field_count="$(
    printf '%s' "$compact_snapshot" \
      | awk -F '"State":"' '{ print NF - 1 }'
  )"
  [ "$state_field_count" -eq 1 ] || {
    printf '%s\n' "unknown"
    return 0
  }
  parsed_state="$(
    printf '%s' "$compact_snapshot" \
      | sed -n 's/.*"State":"\([^"]*\)".*/\1/p'
  )"
  case "$parsed_state" in
    running|stopped|exited|created|dead|restarting|paused|removing)
      printf '%s\n' "$parsed_state"
      ;;
    *)
      printf '%s\n' "unknown"
      ;;
  esac
}

service_state_is_stopped() {
  case "$1" in
    absent|stopped|exited|created|dead) return 0 ;;
    *) return 1 ;;
  esac
}

get_beat_state() {
  beat_service_state="$(get_service_state beat)"
  case "$beat_service_state" in
    running) printf '%s\n' "running" ;;
    absent|stopped|exited|dead) printf '%s\n' "stopped" ;;
    *) printf '%s\n' "unknown" ;;
  esac
}

assert_beat_stopped() {
  checked_beat_state="$(get_beat_state)"
  if [ "$checked_beat_state" != "stopped" ]; then
    echo "Beat 停止态不可确认：state=${checked_beat_state}。" >&2
    return 1
  fi
  echo "Beat 停止态已确认。"
}

assert_beat_running() {
  checked_beat_state="$(get_beat_state)"
  if [ "$checked_beat_state" != "running" ]; then
    echo "Beat 运行态不可确认：state=${checked_beat_state}。" >&2
    return 1
  fi
  echo "Beat 运行态已确认。"
}

read_memory_kib() {
  memory_key="$1"
  awk -v key="$memory_key" '
    $1 == key ":" && $2 ~ /^[0-9]+$/ {
      value = $2
      count += 1
    }
    END {
      if (count == 1) {
        print value
      } else {
        exit 1
      }
    }
  ' "$MEMINFO_FILE"
}

available_disk_kib() {
  disk_path="$1"
  df -Pk "$disk_path" | awk '
    NR == 2 && $4 ~ /^[0-9]+$/ {
      print $4
      found = 1
    }
    END {
      if (!found) {
        exit 1
      }
    }
  '
}

resolve_docker_data_path() {
  if [ -n "$DOCKER_DATA_PATH" ]; then
    printf '%s\n' "$DOCKER_DATA_PATH"
    return 0
  fi
  docker info --format '{{.DockerRootDir}}'
}

verify_no_recent_oom() {
  command -v journalctl >/dev/null 2>&1 || {
    echo "无法读取最近 15 分钟 OOM 证据：journalctl 不可用。" >&2
    return 1
  }
  if ! oom_snapshot="$(journalctl -k --since "15 minutes ago" --no-pager 2>&1)"; then
    echo "无法读取最近 15 分钟 OOM 证据。" >&2
    return 1
  fi
  if printf '%s\n' "$oom_snapshot" \
    | grep -Eiq 'no journal files were found|permission denied|failed to'; then
    echo "无法确认最近 15 分钟 OOM 证据。" >&2
    return 1
  fi
  if printf '%s\n' "$oom_snapshot" \
    | grep -Eiq 'oom-kill|out of memory|killed process'; then
    echo "资源门禁失败：最近 15 分钟发现 OOM kill。" >&2
    return 1
  fi
}

verify_resources() {
  [ -r "$MEMINFO_FILE" ] || {
    echo "资源门禁失败：meminfo 不可读。" >&2
    return 1
  }
  mem_available_kib="$(read_memory_kib MemAvailable)" || {
    echo "资源门禁失败：MemAvailable 不可读。" >&2
    return 1
  }
  swap_free_kib="$(read_memory_kib SwapFree)" || {
    echo "资源门禁失败：SwapFree 不可读。" >&2
    return 1
  }
  if [ "$mem_available_kib" -lt "$MIN_MEMORY_KIB" ]; then
    echo "资源门禁失败：MemAvailable 低于 1536 MiB。" >&2
    return 1
  fi
  if [ "$swap_free_kib" -lt "$MIN_SWAP_KIB" ] \
    && [ "$mem_available_kib" -lt "$LOW_SWAP_MEMORY_KIB" ]; then
    echo "资源门禁失败：低 swap 时 MemAvailable 低于 2048 MiB。" >&2
    return 1
  fi

  docker_path="$(resolve_docker_data_path)" || {
    echo "资源门禁失败：Docker 数据目录不可确认。" >&2
    return 1
  }
  [ -d "$REPOSITORY_PATH" ] && [ -d "$docker_path" ] || {
    echo "资源门禁失败：仓库或 Docker 数据目录不存在。" >&2
    return 1
  }
  repository_available_kib="$(available_disk_kib "$REPOSITORY_PATH")" || {
    echo "资源门禁失败：仓库文件系统空间不可读。" >&2
    return 1
  }
  docker_available_kib="$(available_disk_kib "$docker_path")" || {
    echo "资源门禁失败：Docker 文件系统空间不可读。" >&2
    return 1
  }
  if [ "$repository_available_kib" -lt "$MIN_DISK_KIB" ] \
    || [ "$docker_available_kib" -lt "$MIN_DISK_KIB" ]; then
    echo "资源门禁失败：仓库或 Docker 文件系统可用空间低于 6 GiB。" >&2
    return 1
  fi
  verify_no_recent_oom || return 1
  echo "资源门禁通过：内存、swap、磁盘与最近 OOM 均满足关闭态部署阈值。"
}

image_id_for_tag() {
  image_tag="$1"
  docker image inspect "$image_tag" --format '{{.Id}}' 2>/dev/null
}

container_image_id() {
  service_name="$1"
  service_container="$("$COMPOSE" -f "$COMPOSE_FILE" ps -q "$service_name")" \
    || return 1
  [ -n "$service_container" ] || return 1
  docker inspect "$service_container" --format '{{.Image}}' 2>/dev/null
}

assert_service_images_match_candidate() {
  candidate_id="$(image_id_for_tag "$PRODUCTION_IMAGE")" || return 1
  [ -n "$candidate_id" ] || return 1
  for image_service in "$@"; do
    running_image_id="$(container_image_id "$image_service")" || return 1
    [ "$running_image_id" = "$candidate_id" ] || {
      echo "镜像一致性失败：$image_service 未使用候选镜像。" >&2
      return 1
    }
  done
}

verify_migration_plan_zero() {
  migration_code='from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
count = len(plan)
print(f"pending_migrations={count}")
raise SystemExit(0 if count == 0 else 42)'
  "$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps web \
    python manage.py shell -c "$migration_code"
}

verify_candidate_closed_settings() {
  settings_code='from django.conf import settings
schedule = settings.CELERY_BEAT_SCHEDULE
assert settings.RACE_LIVE_SCHEDULER_ENABLED is False
assert settings.RACE_LIVE_MONITOR_ENABLED is False
assert settings.RACE_LIVE_RUNNER_MODE == "disabled"
assert "select-due-race-live-events" not in schedule
assert "monitor-race-live-sla" not in schedule
print("race_live_flags=closed schedule=closed")'
  "$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps web \
    python manage.py shell -c "$settings_code"
}

verify_candidate_django() {
  "$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps web \
    python manage.py check
}

capture_queue_snapshot() {
  queue_snapshot_code='import json
import redis
from django.conf import settings

target_tasks = {
    "stable.tasks.select_due_race_live_events_task": "selector",
    "stable.tasks.monitor_race_live_sla_task": "monitor",
}
counts = {"selector": 0, "monitor": 0}
lengths = {}
client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
try:
    for queue_name in ("celery", "race_live"):
        messages = client.lrange(queue_name, 0, -1)
        lengths[queue_name] = len(messages)
        for raw_message in messages:
            message = json.loads(raw_message)
            if not isinstance(message, dict):
                raise ValueError("broker message is not an object")
            headers = message.get("headers")
            if not isinstance(headers, dict):
                raise ValueError("broker message headers are unreadable")
            counter_name = target_tasks.get(headers.get("task"))
            if counter_name is not None:
                counts[counter_name] += 1
finally:
    client.close()
print(
    "celery_length={} race_live_length={} "
    "selector_count={} monitor_count={}".format(
        lengths["celery"],
        lengths["race_live"],
        counts["selector"],
        counts["monitor"],
    )
)'
  if ! queue_snapshot_line="$(
    "$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps web \
      python manage.py shell --no-imports -c "$queue_snapshot_code"
  )"; then
    echo "队列/task 计数不可读；保持 fail closed。" >&2
    return 1
  fi

  set -f
  set -- $queue_snapshot_line
  set +f
  [ "$#" -eq 4 ] || {
    echo "队列/task 计数格式不可确认。" >&2
    return 1
  }
  case "$1 $2 $3 $4" in
    "celery_length="*" race_live_length="*" selector_count="*" monitor_count="*) ;;
    *)
      echo "队列/task 计数字段不可确认。" >&2
      return 1
      ;;
  esac
  SNAPSHOT_CELERY_LENGTH="${1#celery_length=}"
  SNAPSHOT_RACE_LIVE_LENGTH="${2#race_live_length=}"
  SNAPSHOT_SELECTOR_COUNT="${3#selector_count=}"
  SNAPSHOT_MONITOR_COUNT="${4#monitor_count=}"
  for snapshot_value in \
    "$SNAPSHOT_CELERY_LENGTH" \
    "$SNAPSHOT_RACE_LIVE_LENGTH" \
    "$SNAPSHOT_SELECTOR_COUNT" \
    "$SNAPSHOT_MONITOR_COUNT"; do
    case "$snapshot_value" in
      ""|*[!0-9]*)
        echo "队列/task 计数不是非负整数。" >&2
        return 1
        ;;
    esac
  done
}

verify_no_target_beat_logs() {
  if ! beat_log_snapshot="$(
    "$COMPOSE" -f "$COMPOSE_FILE" logs --no-color \
      --since "$OBSERVATION_SINCE" beat 2>&1
  )"; then
    echo "Beat 观察日志不可读。" >&2
    return 1
  fi
  if printf '%s\n' "$beat_log_snapshot" \
    | grep -Eq \
      'select-due-race-live-events|monitor-race-live-sla|select_due_race_live_events_task|monitor_race_live_sla_task'; then
    echo "Beat 观察日志出现关闭态目标 schedule entry。" >&2
    return 1
  fi
}

verify_web_healthy_once() {
  web_service_state="$(get_service_state web)"
  [ "$web_service_state" = "running" ] || return 1
  "$COMPOSE" -f "$COMPOSE_FILE" exec -T web \
    curl -fsS http://127.0.0.1:8000/healthz/ >/dev/null
  curl -fsS http://127.0.0.1/healthz/ >/dev/null
}

verify_web_healthy() {
  health_deadline=$(($(date +%s) + HEALTH_TIMEOUT_SECONDS))
  while :; do
    if verify_web_healthy_once; then
      return 0
    fi
    [ "$(date +%s)" -lt "$health_deadline" ] || {
      echo "web/nginx 健康状态未在期限内确认。" >&2
      return 1
    }
    sleep 5
  done
}

verify_worker_healthy_and_isolated_once() {
  worker_service_state="$(get_service_state worker)"
  [ "$worker_service_state" = "running" ] || return 1
  if ! "$COMPOSE" -f "$COMPOSE_FILE" exec -T worker sh -c '
    queue_option_count="$(
      tr "\000" "\n" < /proc/1/cmdline \
        | grep -Ec "^(--queues($|=)|-Q($|=))" || :
    )"
    exact_queue_count="$(
      tr "\000" "\n" < /proc/1/cmdline \
        | grep -cx -- "--queues=celery" || :
    )"
    [ "$queue_option_count" -eq 1 ] && [ "$exact_queue_count" -eq 1 ]
  '; then
    echo "普通 worker PID1 queues 门禁失败：必须唯一且精确为 --queues=celery。" >&2
    return 1
  fi
  if ! "$COMPOSE" -f "$COMPOSE_FILE" exec -T worker sh -c '
    exec celery -A app inspect ping \
      --destination "celery@$(hostname)" --timeout=5
  ' >/dev/null; then
    echo "普通 worker ping 失败。" >&2
    return 1
  fi
}

verify_worker_healthy_and_isolated() {
  health_deadline=$(($(date +%s) + HEALTH_TIMEOUT_SECONDS))
  while :; do
    if verify_worker_healthy_and_isolated_once; then
      return 0
    fi
    [ "$(date +%s)" -lt "$health_deadline" ] || {
      echo "普通 worker 健康/队列隔离状态未在期限内确认。" >&2
      return 1
    }
    sleep 5
  done
}

verify_race_live_worker_stopped() {
  live_worker_service_state="$(get_service_state race_live_worker)"
  service_state_is_stopped "$live_worker_service_state" || {
    echo "race_live_worker 未处于明确停止终态：state=${live_worker_service_state}。" >&2
    return 1
  }
  echo "race_live_worker 停止态已确认：state=${live_worker_service_state}。"
}

observe_closed_beat_for_five_minutes() {
  observation_minute=1
  while [ "$observation_minute" -le 5 ]; do
    sleep "$OBSERVATION_INTERVAL_SECONDS"

    assert_beat_running || return 1
    assert_service_images_match_candidate web worker beat || return 1
    verify_web_healthy_once || {
      echo "第 ${observation_minute} 轮 web 健康复核失败。" >&2
      return 1
    }
    verify_worker_healthy_and_isolated_once || {
      echo "第 ${observation_minute} 轮普通 worker 健康/队列复核失败。" >&2
      return 1
    }
    verify_race_live_worker_stopped || return 1
    capture_queue_snapshot || return 1
    if [ "$SNAPSHOT_SELECTOR_COUNT" -gt "$BASELINE_SELECTOR_COUNT" ] \
      || [ "$SNAPSHOT_MONITOR_COUNT" -gt "$BASELINE_MONITOR_COUNT" ]; then
      echo "第 ${observation_minute} 轮目标 task 计数超过启动前基线。" >&2
      return 1
    fi
    verify_no_target_beat_logs || return 1
    echo "观察 ${observation_minute}/5：beat/web/worker=running，race_live_worker=${live_worker_service_state}，celery=${SNAPSHOT_CELERY_LENGTH}，race_live=${SNAPSHOT_RACE_LIVE_LENGTH}，selector=${SNAPSHOT_SELECTOR_COUNT}，monitor=${SNAPSHOT_MONITOR_COUNT}。"
    observation_minute=$((observation_minute + 1))
  done
}

restart_safe_services_after_failure() {
  [ "$WORKER_STOPPED" -eq 1 ] || return 0

  if [ "$IMAGE_TAG_MAY_HAVE_CHANGED" -eq 1 ] && [ -n "$ROLLBACK_IMAGE" ]; then
    if ! docker image tag "$ROLLBACK_IMAGE" "$PRODUCTION_IMAGE"; then
      echo "回滚失败：无法恢复旧生产镜像标签。" >&2
      return 1
    fi
    echo "已恢复旧生产镜像标签。"
  fi

  if [ "$CANDIDATE_WEB_STARTED" -eq 1 ]; then
    "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps --force-recreate \
      web worker nginx || {
        echo "回滚失败：旧 web/worker/nginx 未能全部恢复。" >&2
        return 1
      }
    verify_web_healthy || return 1
    verify_worker_healthy_and_isolated || return 1
  else
    "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps worker || {
      echo "恢复失败：普通 worker 未能恢复。" >&2
      return 1
    }
    verify_worker_healthy_and_isolated || return 1
  fi
  echo "失败恢复仅处理了 web/普通 worker/nginx；Beat 未启动。"
}

on_exit() {
  exit_status="$?"
  trap - EXIT

  if [ "$exit_status" -ne 0 ]; then
    if [ "$PHASE" = "prepare" ]; then
      if [ "$STATE" = "PRE_STOP_PREFLIGHT" ]; then
        if [ "$STOP_ATTEMPTED" -eq 0 ] \
          || [ "$STOP_UNCHANGED_CONFIRMED" -eq 1 ]; then
          echo "Beat 原状态为 ${INITIAL_BEAT_STATE}，未被本命令改变。" >&2
        else
          echo "Beat 原状态为 ${INITIAL_BEAT_STATE}；stop 后状态为 ${STOP_OBSERVED_STATE}，停止未确认。" >&2
        fi
      else
        restart_safe_services_after_failure || exit_status=1
        if assert_beat_stopped; then
          echo "失败复核：Beat 仍保持停止，未自动启动。" >&2
        else
          echo "失败复核：Beat 停止态未知；保持 fail closed。" >&2
          exit_status=1
        fi
      fi
    elif [ "$BEAT_STARTED_BY_COMMAND" -eq 1 ]; then
      "$COMPOSE" -f "$COMPOSE_FILE" stop --timeout 30 beat >/dev/null 2>&1 \
        || exit_status=1
      if ! assert_beat_stopped; then
        echo "start-beat 失败且无法确认 Beat 已重新停止。" >&2
        exit_status=1
      fi
    fi
  fi

  release_lock
  exit "$exit_status"
}

run_prepare() {
  INITIAL_BEAT_STATE="$(get_beat_state)"
  trap 'on_exit' EXIT

  [ "$INITIAL_BEAT_STATE" != "unknown" ] || {
    echo "停服前无法确认 Beat 原状态。" >&2
    return 1
  }
  verify_closed_env_file

  ORIGINAL_IMAGE_ID="$(image_id_for_tag "$PRODUCTION_IMAGE")" || {
    echo "停服前无法确认当前生产镜像 ID。" >&2
    return 1
  }
  [ -n "$ORIGINAL_IMAGE_ID" ] || {
    echo "停服前当前生产镜像 ID 为空。" >&2
    return 1
  }
  for current_service in web worker; do
    current_service_image="$(container_image_id "$current_service")" || {
      echo "停服前无法确认 $current_service 当前镜像。" >&2
      return 1
    }
    [ "$current_service_image" = "$ORIGINAL_IMAGE_ID" ] || {
      echo "停服前 $current_service 镜像与生产 tag 不一致。" >&2
      return 1
    }
  done
  verify_race_live_worker_stopped
  verify_resources

  STOP_ATTEMPTED=1
  if ! "$COMPOSE" -f "$COMPOSE_FILE" stop --timeout 30 beat; then
    STOP_OBSERVED_STATE="$(get_beat_state)"
    if [ "$STOP_OBSERVED_STATE" = "$INITIAL_BEAT_STATE" ]; then
      STOP_UNCHANGED_CONFIRMED=1
    fi
    echo "Beat stop 命令失败，停止不可确认；复核状态=${STOP_OBSERVED_STATE}。" >&2
    return 1
  fi
  if ! assert_beat_stopped; then
    STOP_OBSERVED_STATE="$checked_beat_state"
    if [ "$STOP_OBSERVED_STATE" = "$INITIAL_BEAT_STATE" ]; then
      STOP_UNCHANGED_CONFIRMED=1
    fi
    echo "Beat stop 返回成功但停止未确认；复核状态=${STOP_OBSERVED_STATE}。" >&2
    return 1
  fi
  STATE="BEAT_STOPPED"

  COMPOSE_FILE="$COMPOSE_FILE" "$DRAIN_SCRIPT"
  worker_stop_status=0
  "$COMPOSE" -f "$COMPOSE_FILE" stop --timeout 30 worker \
    || worker_stop_status=$?
  worker_final_state="$(get_service_state worker)"
  if service_state_is_stopped "$worker_final_state"; then
    WORKER_STOPPED=1
    if [ "$worker_stop_status" -ne 0 ]; then
      echo "普通 worker 已停止，但 stop 命令非零；交由失败恢复：state=${worker_final_state}。" >&2
      return "$worker_stop_status"
    fi
  else
    echo "普通 worker 停止态不可确认：state=${worker_final_state}，stop_exit=${worker_stop_status}。" >&2
    if [ "$worker_stop_status" -ne 0 ]; then
      return "$worker_stop_status"
    fi
    return 1
  fi

  verify_resources

  rollback_suffix="$(date -u +%Y%m%dT%H%M%SZ)"
  ROLLBACK_IMAGE="umanewsbot:rollback-race-live-p0-$rollback_suffix"
  docker image tag "$ORIGINAL_IMAGE_ID" "$ROLLBACK_IMAGE"
  echo "已建立本窗口 rollback image tag：$ROLLBACK_IMAGE"

  COMPOSE_FILE="$COMPOSE_FILE" "$HISTORICAL_PREFLIGHT"

  IMAGE_TAG_MAY_HAVE_CHANGED=1
  "$COMPOSE" -f "$COMPOSE_FILE" build web
  CANDIDATE_IMAGE_ID="$(image_id_for_tag "$PRODUCTION_IMAGE")" || {
    echo "构建后无法确认候选镜像 ID。" >&2
    return 1
  }
  [ -n "$CANDIDATE_IMAGE_ID" ] || {
    echo "构建后候选镜像 ID 为空。" >&2
    return 1
  }

  verify_candidate_django
  verify_migration_plan_zero
  verify_candidate_closed_settings
  verify_migration_plan_zero

  "$COMPOSE" -f "$COMPOSE_FILE" run --rm --no-deps web \
    python manage.py collectstatic --noinput

  CANDIDATE_WEB_STARTED=1
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps web
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps worker
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps --force-recreate nginx

  verify_web_healthy
  verify_worker_healthy_and_isolated
  verify_race_live_worker_stopped
  assert_service_images_match_candidate web worker
  assert_beat_stopped

  STATE="CANDIDATE_READY"
  echo "CANDIDATE_READY：web/普通 worker/nginx 已就绪；Beat 与 race_live_worker 保持停止。"
}

run_start_beat() {
  trap 'on_exit' EXIT

  current_beat_state="$(get_beat_state)"
  [ "$current_beat_state" = "stopped" ] || {
    echo "start-beat 前 Beat 必须可确认处于停止态；当前为 ${current_beat_state}。" >&2
    return 1
  }
  verify_closed_env_file
  verify_candidate_closed_settings
  verify_web_healthy
  verify_worker_healthy_and_isolated
  verify_race_live_worker_stopped
  assert_service_images_match_candidate web worker

  capture_queue_snapshot
  BASELINE_CELERY_LENGTH="$SNAPSHOT_CELERY_LENGTH"
  BASELINE_RACE_LIVE_LENGTH="$SNAPSHOT_RACE_LIVE_LENGTH"
  BASELINE_SELECTOR_COUNT="$SNAPSHOT_SELECTOR_COUNT"
  BASELINE_MONITOR_COUNT="$SNAPSHOT_MONITOR_COUNT"
  OBSERVATION_SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "启动前基线：celery=${BASELINE_CELERY_LENGTH}，race_live=${BASELINE_RACE_LIVE_LENGTH}，selector=${BASELINE_SELECTOR_COUNT}，monitor=${BASELINE_MONITOR_COUNT}。"

  BEAT_STARTED_BY_COMMAND=1
  "$COMPOSE" -f "$COMPOSE_FILE" up -d --no-deps beat || return 1
  assert_beat_running || return 1
  assert_service_images_match_candidate web worker beat || return 1
  observe_closed_beat_for_five_minutes || return 1
  BEAT_STARTED_BY_COMMAND=0

  echo "Beat 已在关闭态候选验证后单独启动，并通过连续五轮观察；race_live_worker 仍停止。"
}

case "$PHASE" in
  prepare) run_prepare ;;
  start-beat) run_start_beat ;;
esac
