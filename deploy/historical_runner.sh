#!/bin/sh
set -eu

ACTION="${1:-status}"
CONTAINER_NAME="${HISTORICAL_RUNNER_CONTAINER_NAME:-umanews-historical-runner}"
INTERNAL_NETWORK="${HISTORICAL_RUNNER_INTERNAL_NETWORK:-umanews-historical-runner-db}"
EGRESS_NETWORK="${HISTORICAL_RUNNER_EGRESS_NETWORK:-umanews-historical-runner-egress}"
SECRET_DIR="${HISTORICAL_RUNNER_SECRET_DIR:-/opt/umanewsbot/runtime/historical_runner_secrets}"
CONTROL_ROLE="${HISTORICAL_RUNNER_CONTROL_ROLE:-historical_runner_control}"

status() {
  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    docker container inspect "$CONTAINER_NAME" --format '{{json .State}}'
  else
    printf '%s\n' '{"Status":"absent"}'
  fi
}

stop_runner() {
  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    docker stop --timeout 30 "$CONTAINER_NAME"
  fi
}

validate_env_file() {
  file="$1"
  phase="$2"
  [ -f "$file" ] || { echo "runner env file missing: $file" >&2; exit 1; }
  mode="$(stat -c '%a' "$file" 2>/dev/null || stat -f '%Lp' "$file")"
  [ "$mode" = "600" ] || { echo "runner env file must be 0600: $file" >&2; exit 1; }
  seen_keys=" "
  while IFS='=' read -r key _value; do
    case "$key" in ''|'#'*) continue ;; esac
    case "$seen_keys" in
      *" $key "*) echo "duplicate runner env key: $key" >&2; exit 1 ;;
    esac
    seen_keys="$seen_keys$key "
    case "$key" in
      DEBUG|SECRET_KEY|DB_ENGINE|POSTGRES_DB|POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_HOST|POSTGRES_PORT|POSTGRES_SSLMODE|POSTGRES_CONNECT_TIMEOUT|POSTGRES_APPLICATION_NAME|HISTORICAL_RACE_BACKFILL_ENABLED|HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK|HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET|HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES|HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES) ;;
      *) echo "runner $phase env contains forbidden key: $key" >&2; exit 1 ;;
    esac
  done < "$file"
}

start_runner() {
  : "${HISTORICAL_RUNNER_IMAGE_ID:?full immutable image ID is required}"
  : "${HISTORICAL_RUNNER_IMAGE_REVISION:?image revision is required}"
  : "${HISTORICAL_RUNNER_RUN_ID:?stable runner run id is required}"
  : "${HISTORICAL_RUNNER_PHASE:?crawl, apply or verify is required}"
  : "${HISTORICAL_RUNNER_ARTIFACT_DIR:?approved artifact directory is required}"
  : "${HISTORICAL_RUNNER_PLAN_RELATIVE_PATH:?plan path relative to artifact root is required}"
  : "${HISTORICAL_RUNNER_OWNER_TOKEN_FILE:?owner token file is required}"
  : "${HISTORICAL_RUNNER_ENV_FILE:?phase env file is required}"

  printf '%s\n' "$HISTORICAL_RUNNER_IMAGE_ID" | grep -Eq '^sha256:[0-9a-f]{64}$' || {
    echo "image must be a full sha256 ID" >&2
    exit 1
  }
  printf '%s\n' "$HISTORICAL_RUNNER_RUN_ID" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' || {
    echo "runner run id is invalid" >&2
    exit 1
  }
  actual_revision="$(docker image inspect "$HISTORICAL_RUNNER_IMAGE_ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
  [ "$actual_revision" = "$HISTORICAL_RUNNER_IMAGE_REVISION" ] || { echo "image revision mismatch" >&2; exit 1; }
  [ -d "$HISTORICAL_RUNNER_ARTIFACT_DIR" ] || { echo "artifact directory missing" >&2; exit 1; }
  artifact_dir="$(CDPATH= cd -- "$HISTORICAL_RUNNER_ARTIFACT_DIR" && pwd -P)"
  secret_dir="$(CDPATH= cd -- "$SECRET_DIR" && pwd -P)"
  token_path="$(readlink -f "$HISTORICAL_RUNNER_OWNER_TOKEN_FILE")"
  env_path="$(readlink -f "$HISTORICAL_RUNNER_ENV_FILE")"
  case "$token_path" in "$secret_dir"/*) ;; *) echo "owner token must be stored under historical_runner_secrets" >&2; exit 1 ;; esac
  case "$env_path" in "$secret_dir"/*) ;; *) echo "runner env must be stored under historical_runner_secrets" >&2; exit 1 ;; esac
  [ "$(basename "$token_path")" = "$HISTORICAL_RUNNER_RUN_ID.token" ] || {
    echo "owner token filename must match run id" >&2
    exit 1
  }
  [ "$(basename "$env_path")" = "$HISTORICAL_RUNNER_RUN_ID.$HISTORICAL_RUNNER_PHASE.env" ] || {
    echo "runner env filename must match run id and phase" >&2
    exit 1
  }
  case "$token_path" in "$artifact_dir"/*) echo "owner token cannot be stored in artifact directory" >&2; exit 1 ;; esac
  case "$env_path" in "$artifact_dir"/*) echo "runner env cannot be stored in artifact directory" >&2; exit 1 ;; esac
  token_mode="$(stat -c '%a' "$token_path" 2>/dev/null || stat -f '%Lp' "$token_path")"
  [ "$token_mode" = "600" ] || { echo "owner token must be 0600" >&2; exit 1; }
  validate_env_file "$env_path" "$HISTORICAL_RUNNER_PHASE"
  grep -Fqx 'DB_ENGINE=postgres' "$env_path" || { echo "runner DB_ENGINE must be postgres" >&2; exit 1; }
  grep -Fqx 'POSTGRES_HOST=db' "$env_path" || { echo "runner POSTGRES_HOST must use the internal db alias" >&2; exit 1; }
  grep -Fqx 'POSTGRES_PORT=5432' "$env_path" || { echo "runner POSTGRES_PORT must be 5432" >&2; exit 1; }
  awk -F= '$1 == "POSTGRES_DB" && length(substr($0, index($0, "=") + 1)) > 0 { found=1 } END { exit !found }' "$env_path" || {
    echo "runner POSTGRES_DB must be non-empty" >&2
    exit 1
  }
  awk -F= '$1 == "POSTGRES_PASSWORD" && length(substr($0, index($0, "=") + 1)) > 0 { found=1 } END { exit !found }' "$env_path" || {
    echo "runner POSTGRES_PASSWORD must be non-empty" >&2
    exit 1
  }
  grep -Fqx "POSTGRES_APPLICATION_NAME=umanews-historical-runner:$HISTORICAL_RUNNER_RUN_ID:$HISTORICAL_RUNNER_PHASE" "$env_path" || {
    echo "runner POSTGRES_APPLICATION_NAME must bind run id and phase" >&2
    exit 1
  }

  case "$HISTORICAL_RUNNER_PHASE" in
    crawl)
      grep -Fqx "POSTGRES_USER=$CONTROL_ROLE" "$env_path" || {
        echo "crawl runner must use the minimal control database role" >&2
        exit 1
      }
      grep -Fqx 'HISTORICAL_RACE_BACKFILL_ENABLED=true' "$env_path"
      grep -Fqx 'HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=true' "$env_path"
      ;;
    apply)
      : "${HISTORICAL_RUNNER_APPLY_ROLE:?approved apply database role is required}"
      case "$HISTORICAL_RUNNER_APPLY_ROLE" in
        *[!a-zA-Z0-9_]*) echo "apply role name is invalid" >&2; exit 1 ;;
      esac
      [ "$HISTORICAL_RUNNER_APPLY_ROLE" != "$CONTROL_ROLE" ] || {
        echo "apply role cannot equal the minimal control role" >&2
        exit 1
      }
      grep -Fqx "POSTGRES_USER=$HISTORICAL_RUNNER_APPLY_ROLE" "$env_path" || {
        echo "apply runner must use the explicitly approved business write role" >&2
        exit 1
      }
      grep -Fqx 'HISTORICAL_RACE_BACKFILL_ENABLED=true' "$env_path"
      grep -Fqx 'HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false' "$env_path"
      ;;
    verify)
      grep -Fqx "POSTGRES_USER=$CONTROL_ROLE" "$env_path" || {
        echo "verify runner must use the minimal control database role" >&2
        exit 1
      }
      grep -Fqx 'HISTORICAL_RACE_BACKFILL_ENABLED=true' "$env_path"
      grep -Fqx 'HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false' "$env_path"
      ;;
    *) echo "invalid runner phase" >&2; exit 1 ;;
  esac

  docker network inspect "$INTERNAL_NETWORK" >/dev/null
  [ "$HISTORICAL_RUNNER_PHASE" != "crawl" ] || docker network inspect "$EGRESS_NETWORK" >/dev/null
  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "runner container already exists: $CONTAINER_NAME" >&2
    exit 1
  fi
  docker create \
    --name "$CONTAINER_NAME" \
    --network "$INTERNAL_NETWORK" \
    --network-alias runner \
    --cpus 2 \
    --memory 2g \
    --pids-limit 256 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=256m \
    --log-driver json-file \
    --log-opt max-size=20m \
    --log-opt max-file=5 \
    --env-file "$env_path" \
    --mount "type=bind,src=$artifact_dir,dst=/app/historical-runtime" \
    --mount "type=bind,src=$token_path,dst=/run/secrets/historical-owner-token,readonly" \
    "$HISTORICAL_RUNNER_IMAGE_ID" \
    python manage.py run_historical_batch_stage \
      --plan "/app/historical-runtime/$HISTORICAL_RUNNER_PLAN_RELATIVE_PATH" \
      --owner-token-file /run/secrets/historical-owner-token \
      --lock-file /app/historical-runtime/.runner.lock \
      --run-id "$HISTORICAL_RUNNER_RUN_ID"
  [ "$HISTORICAL_RUNNER_PHASE" != "crawl" ] || docker network connect "$EGRESS_NETWORK" "$CONTAINER_NAME"
  docker start "$CONTAINER_NAME"
}

takeover_runner() {
  : "${HISTORICAL_RUNNER_IMAGE_ID:?full immutable image ID is required}"
  : "${HISTORICAL_RUNNER_IMAGE_REVISION:?image revision is required}"
  : "${HISTORICAL_RUNNER_RUN_ID:?stable runner run id is required}"
  : "${HISTORICAL_RUNNER_PHASE:?crawl, apply or verify is required}"
  : "${HISTORICAL_RUNNER_ARTIFACT_DIR:?approved artifact directory is required}"
  : "${HISTORICAL_RUNNER_OWNER_TOKEN_FILE:?owner token file is required}"
  : "${HISTORICAL_RUNNER_ENV_FILE:?phase env file is required}"
  : "${HISTORICAL_RUNNER_TAKEOVER_ACTOR:?takeover actor is required}"
  : "${HISTORICAL_RUNNER_TAKEOVER_REASON:?takeover reason is required}"

  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "old runner container still exists: $CONTAINER_NAME" >&2
    exit 1
  fi
  printf '%s\n' "$HISTORICAL_RUNNER_IMAGE_ID" | grep -Eq '^sha256:[0-9a-f]{64}$' || {
    echo "image must be a full sha256 ID" >&2
    exit 1
  }
  printf '%s\n' "$HISTORICAL_RUNNER_RUN_ID" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' || {
    echo "runner run id is invalid" >&2
    exit 1
  }
  actual_revision="$(docker image inspect "$HISTORICAL_RUNNER_IMAGE_ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
  [ "$actual_revision" = "$HISTORICAL_RUNNER_IMAGE_REVISION" ] || { echo "image revision mismatch" >&2; exit 1; }
  [ -d "$HISTORICAL_RUNNER_ARTIFACT_DIR" ] || { echo "artifact directory missing" >&2; exit 1; }
  artifact_dir="$(CDPATH= cd -- "$HISTORICAL_RUNNER_ARTIFACT_DIR" && pwd -P)"
  secret_dir="$(CDPATH= cd -- "$SECRET_DIR" && pwd -P)"
  token_path="$(readlink -f "$HISTORICAL_RUNNER_OWNER_TOKEN_FILE")"
  env_path="$(readlink -f "$HISTORICAL_RUNNER_ENV_FILE")"
  case "$token_path" in "$secret_dir"/*) ;; *) echo "owner token must be stored under historical_runner_secrets" >&2; exit 1 ;; esac
  case "$env_path" in "$secret_dir"/*) ;; *) echo "runner env must be stored under historical_runner_secrets" >&2; exit 1 ;; esac
  [ "$(basename "$token_path")" = "$HISTORICAL_RUNNER_RUN_ID.token" ] || {
    echo "owner token filename must match run id" >&2
    exit 1
  }
  [ "$(basename "$env_path")" = "$HISTORICAL_RUNNER_RUN_ID.$HISTORICAL_RUNNER_PHASE.env" ] || {
    echo "runner env filename must match run id and phase" >&2
    exit 1
  }
  [ "$(stat -c '%a' "$token_path" 2>/dev/null || stat -f '%Lp' "$token_path")" = "600" ] || {
    echo "owner token must be 0600" >&2
    exit 1
  }
  validate_env_file "$env_path" "$HISTORICAL_RUNNER_PHASE"
  grep -Fqx 'DB_ENGINE=postgres' "$env_path" || { echo "runner DB_ENGINE must be postgres" >&2; exit 1; }
  grep -Fqx 'POSTGRES_HOST=db' "$env_path" || { echo "runner POSTGRES_HOST must use the internal db alias" >&2; exit 1; }
  grep -Fqx 'POSTGRES_PORT=5432' "$env_path" || { echo "runner POSTGRES_PORT must be 5432" >&2; exit 1; }
  grep -Fqx "POSTGRES_APPLICATION_NAME=umanews-historical-runner:$HISTORICAL_RUNNER_RUN_ID:$HISTORICAL_RUNNER_PHASE" "$env_path" || {
    echo "runner POSTGRES_APPLICATION_NAME must bind run id and phase" >&2
    exit 1
  }
  case "$HISTORICAL_RUNNER_PHASE" in
    crawl|verify)
      grep -Fqx "POSTGRES_USER=$CONTROL_ROLE" "$env_path" || {
        echo "crawl/verify takeover must use the minimal control database role" >&2
        exit 1
      }
      ;;
    apply)
      : "${HISTORICAL_RUNNER_APPLY_ROLE:?approved apply database role is required}"
      grep -Fqx "POSTGRES_USER=$HISTORICAL_RUNNER_APPLY_ROLE" "$env_path" || {
        echo "apply takeover must use the explicitly approved business write role" >&2
        exit 1
      }
      ;;
    *) echo "invalid runner phase" >&2; exit 1 ;;
  esac
  docker network inspect "$INTERNAL_NETWORK" >/dev/null

  docker run --rm \
    --name "${CONTAINER_NAME}-takeover" \
    --network "$INTERNAL_NETWORK" \
    --cpus 1 \
    --memory 512m \
    --pids-limit 128 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --env-file "$env_path" \
    --mount "type=bind,src=$artifact_dir,dst=/app/historical-runtime,readonly" \
    --mount "type=bind,src=$token_path,dst=/run/secrets/historical-owner-token,readonly" \
    "$HISTORICAL_RUNNER_IMAGE_ID" \
    python manage.py manage_historical_batch_runner takeover \
      --run-id "$HISTORICAL_RUNNER_RUN_ID" \
      --owner-token-file /run/secrets/historical-owner-token \
      --actor "$HISTORICAL_RUNNER_TAKEOVER_ACTOR" \
      --reason "$HISTORICAL_RUNNER_TAKEOVER_REASON" \
      --container-absent \
      --state-file /app/historical-runtime/runner-state.json \
      --json
}

case "$ACTION" in
  start) start_runner ;;
  takeover) takeover_runner ;;
  stop) stop_runner ;;
  status) status ;;
  remove) stop_runner; docker rm "$CONTAINER_NAME" 2>/dev/null || true ;;
  *) echo "usage: $0 start|takeover|stop|status|remove" >&2; exit 2 ;;
esac
