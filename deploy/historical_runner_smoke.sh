#!/bin/sh
set -eu

PHASE="${1:-}"
CONTAINER_NAME="${HISTORICAL_RUNNER_CONTAINER_NAME:-umanews-historical-runner}"
CONTROL_ROLE="${HISTORICAL_RUNNER_CONTROL_ROLE:-historical_runner_control}"
[ "$PHASE" = "crawl" ] || [ "$PHASE" = "apply" ] || {
  echo "usage: $0 crawl|apply" >&2
  exit 2
}
case "$CONTROL_ROLE" in *[!a-zA-Z0-9_]*) echo "invalid control role" >&2; exit 1 ;; esac

docker container inspect "$CONTAINER_NAME" >/dev/null
cpus="$(docker inspect "$CONTAINER_NAME" --format '{{.HostConfig.NanoCpus}}')"
memory="$(docker inspect "$CONTAINER_NAME" --format '{{.HostConfig.Memory}}')"
pids="$(docker inspect "$CONTAINER_NAME" --format '{{.HostConfig.PidsLimit}}')"
[ "$cpus" -gt 0 ] && [ "$cpus" -le 2000000000 ]
[ "$memory" -gt 0 ] && [ "$memory" -le 2147483648 ]
[ "$pids" -gt 0 ] && [ "$pids" -le 256 ]
[ "$(docker inspect "$CONTAINER_NAME" --format '{{.HostConfig.ReadonlyRootfs}}')" = "true" ]
case "$(docker inspect "$CONTAINER_NAME" --format '{{json .HostConfig.CapDrop}}')" in
  *'"ALL"'*) ;;
  *) echo "runner must drop all Linux capabilities" >&2; exit 1 ;;
esac
case "$(docker inspect "$CONTAINER_NAME" --format '{{json .HostConfig.SecurityOpt}}')" in
  *'"no-new-privileges"'*) ;;
  *) echo "runner must enable no-new-privileges" >&2; exit 1 ;;
esac
[ "$(docker inspect "$CONTAINER_NAME" --format '{{.HostConfig.LogConfig.Type}}')" = "json-file" ]
[ "$(docker inspect "$CONTAINER_NAME" --format '{{index .HostConfig.LogConfig.Config "max-size"}}')" = "20m" ]
[ "$(docker inspect "$CONTAINER_NAME" --format '{{index .HostConfig.LogConfig.Config "max-file"}}')" = "5" ]
networks="$(docker inspect "$CONTAINER_NAME" --format '{{json .NetworkSettings.Networks}}')"
internal_network="${HISTORICAL_RUNNER_INTERNAL_NETWORK:-umanews-historical-runner-db}"
egress_network="${HISTORICAL_RUNNER_EGRESS_NETWORK:-umanews-historical-runner-egress}"
case "$networks" in *"\"$internal_network\""*) ;; *) echo "runner internal network missing" >&2; exit 1 ;; esac

if [ "$PHASE" = "crawl" ]; then
  case "$networks" in *"\"$egress_network\""*) ;; *) echo "crawl egress network missing" >&2; exit 1 ;; esac
  if docker exec "$CONTAINER_NAME" python manage.py shell -c \
    "from django.db import connection; c=connection.cursor(); c.execute(\"UPDATE stable_raceevent SET notes=notes WHERE FALSE\")"; then
    echo "crawl control role unexpectedly wrote a business table" >&2
    exit 1
  fi
  docker exec -e EXPECTED_CONTROL_ROLE="$CONTROL_ROLE" "$CONTAINER_NAME" python manage.py shell -c \
    "import os; from django.db import connection; from stable.models import HistoricalBatchRun; c=connection.cursor(); c.execute('SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit, rolconnlimit FROM pg_roles WHERE rolname=current_user'); row=c.fetchone(); expected=os.environ['EXPECTED_CONTROL_ROLE']; assert row == (expected, False, False, False, False, False, False, 5), row; print(HistoricalBatchRun.objects.count())"
else
  case "$networks" in *"\"$egress_network\""*) echo "apply runner unexpectedly has egress network" >&2; exit 1 ;; esac
  docker exec "$CONTAINER_NAME" python manage.py shell -c \
    "from django.db import connection; c=connection.cursor(); c.execute('SELECT 1'); assert c.fetchone()[0] == 1"
  if docker exec "$CONTAINER_NAME" python -c \
    "import socket; socket.create_connection(('1.1.1.1', 443), timeout=3)"; then
    echo "apply runner unexpectedly reached the public network" >&2
    exit 1
  fi
fi

echo "historical runner $PHASE isolation smoke passed"
