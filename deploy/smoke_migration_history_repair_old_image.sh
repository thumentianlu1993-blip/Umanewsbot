#!/bin/sh
# Isolated, repeatable compatibility smoke for the pinned pre-repair image.
# The caller must prepare an ephemeral PostgreSQL fixture at an exact partial
# state and label both fixture containers com.umafans.migration-repair-smoke=true.
# This script deliberately refuses production-shaped hosts and never migrates.
set -eu

case "${MIGRATION_REPAIR_SMOKE_ACK:-}" in isolated-ephemeral-postgres) ;; *) echo "isolated smoke acknowledgement is required" >&2; exit 1 ;; esac
case "${EXPECTED_PARTIAL_STATE:-}" in 0068-only|0069-complete) ;; *) echo "EXPECTED_PARTIAL_STATE must be 0068-only or 0069-complete" >&2; exit 1 ;; esac
if [ -z "${PINNED_OLD_IMAGE_ID:-}" ]; then echo "PINNED_OLD_IMAGE_ID is required" >&2; exit 1; fi
if [ -z "${POSTGRES_PASSWORD:-}" ]; then echo "POSTGRES_PASSWORD is required" >&2; exit 1; fi

IMAGE_REF="${PINNED_OLD_IMAGE_REF:-umanewsbot:rollback-pre-release-b-prereq}"
NETWORK="${SMOKE_DOCKER_NETWORK:-umanews-migration-repair-smoke}"
DB_CONTAINER="${SMOKE_DB_CONTAINER:-migration-repair-db}"
REDIS_CONTAINER="${SMOKE_REDIS_CONTAINER:-migration-repair-redis}"
for container in "$DB_CONTAINER" "$REDIS_CONTAINER"; do
  if [ "$(docker inspect --format '{{index .Config.Labels "com.umafans.migration-repair-smoke"}}' "$container")" != true ]; then
    echo "$container is not a labelled isolated smoke fixture" >&2
    exit 1
  fi
done
if [ "$(docker image inspect --format '{{.Id}}' "$IMAGE_REF")" != "$PINNED_OLD_IMAGE_ID" ]; then
  echo "old image digest mismatch" >&2
  exit 1
fi

POSTGRES_DB=umanews_migration_repair_smoke
ADMIN_POSTGRES_USER=umanews_smoke
ADMIN_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
SMOKE_APP_ROLE="umanews_old_image_ro_$$"
SMOKE_APP_PASSWORD="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
POSTGRES_USER="$SMOKE_APP_ROLE"
POSTGRES_PASSWORD="$SMOKE_APP_PASSWORD"
DB_ENGINE=postgres
POSTGRES_HOST="$DB_CONTAINER"
POSTGRES_PORT=5432
CELERY_BROKER_URL="redis://$REDIS_CONTAINER:6379/0"
CELERY_RESULT_BACKEND="$CELERY_BROKER_URL"
RACE_LIVE_SCHEDULER_ENABLED=false
RACE_LIVE_MONITOR_ENABLED=false
RACE_DATA_SYNC_ENABLED=false
HISTORICAL_RACE_BACKFILL_ENABLED=false
HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false
export DB_ENGINE POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export CELERY_BROKER_URL CELERY_RESULT_BACKEND RACE_LIVE_SCHEDULER_ENABLED
export RACE_LIVE_MONITOR_ENABLED RACE_DATA_SYNC_ENABLED
export HISTORICAL_RACE_BACKFILL_ENABLED HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK
run_old_image() {
  mode="$1"; name="$2"; hostname="$3"; shift 3
  if [ "$mode" = rm ]; then
    docker run --rm --network "$NETWORK" -e DB_ENGINE -e POSTGRES_HOST -e POSTGRES_PORT \
      -e POSTGRES_DB -e POSTGRES_USER -e POSTGRES_PASSWORD -e CELERY_BROKER_URL \
      -e CELERY_RESULT_BACKEND -e RACE_LIVE_SCHEDULER_ENABLED -e RACE_LIVE_MONITOR_ENABLED \
      -e RACE_DATA_SYNC_ENABLED -e HISTORICAL_RACE_BACKFILL_ENABLED \
      -e HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK "$IMAGE_REF" "$@"
  elif [ -n "$hostname" ]; then
    docker run -d --name "$name" --hostname "$hostname" --network "$NETWORK" \
      -e DB_ENGINE -e POSTGRES_HOST -e POSTGRES_PORT -e POSTGRES_DB -e POSTGRES_USER \
      -e POSTGRES_PASSWORD -e CELERY_BROKER_URL -e CELERY_RESULT_BACKEND \
      -e RACE_LIVE_SCHEDULER_ENABLED -e RACE_LIVE_MONITOR_ENABLED -e RACE_DATA_SYNC_ENABLED \
      -e HISTORICAL_RACE_BACKFILL_ENABLED -e HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK \
      "$IMAGE_REF" "$@"
  else
    docker run -d --name "$name" --network "$NETWORK" -e DB_ENGINE -e POSTGRES_HOST \
      -e POSTGRES_PORT -e POSTGRES_DB -e POSTGRES_USER -e POSTGRES_PASSWORD \
      -e CELERY_BROKER_URL -e CELERY_RESULT_BACKEND -e RACE_LIVE_SCHEDULER_ENABLED \
      -e RACE_LIVE_MONITOR_ENABLED -e RACE_DATA_SYNC_ENABLED \
      -e HISTORICAL_RACE_BACKFILL_ENABLED -e HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK \
      "$IMAGE_REF" "$@"
  fi
}

admin_psql() {
  PGPASSWORD="$ADMIN_POSTGRES_PASSWORD" docker exec -e PGPASSWORD "$DB_CONTAINER" \
    psql -v ON_ERROR_STOP=1 -U "$ADMIN_POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}
app_psql() {
  PGPASSWORD="$SMOKE_APP_PASSWORD" docker exec -e PGPASSWORD "$DB_CONTAINER" \
    psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$SMOKE_APP_ROLE" -d "$POSTGRES_DB" "$@"
}
recorded="$(admin_psql -Atc "select name from django_migrations where app='stable' and name in ('0068_race_data_sync_pipeline_a_field_audit','0069_race_data_sync_pipeline_a_ledger_guards','0070_horse_identity_evidence_commit_receipt','0071_historical_calendar_release_b') order by name" | paste -sd, -)"
case "$EXPECTED_PARTIAL_STATE:$recorded" in
  0068-only:0068_race_data_sync_pipeline_a_field_audit,0070_horse_identity_evidence_commit_receipt) ;;
  0069-complete:0068_race_data_sync_pipeline_a_field_audit,0069_race_data_sync_pipeline_a_ledger_guards,0070_horse_identity_evidence_commit_receipt) ;;
  *) echo "ephemeral fixture recorder does not match EXPECTED_PARTIAL_STATE" >&2; exit 1 ;;
esac

web_name="migration-repair-old-web-$$"
worker_name="migration-repair-old-worker-$$"
beat_name="migration-repair-old-beat-$$"
cleanup() {
  docker rm -f "$web_name" "$worker_name" "$beat_name" >/dev/null 2>&1 || true
  admin_psql -v smoke_role="$SMOKE_APP_ROLE" >/dev/null 2>&1 <<'SQL' || true
SELECT format('DROP OWNED BY %I; DROP ROLE IF EXISTS %I', :'smoke_role', :'smoke_role') \gexec
SQL
}
trap cleanup EXIT HUP INT TERM

# Keep the random password out of SQL text and command arguments. psql imports
# it from the docker-exec environment and applies literal/identifier quoting;
# the role and database bindings cannot become SQL syntax.
SMOKE_ROLE_PASSWORD="$SMOKE_APP_PASSWORD"
export SMOKE_ROLE_PASSWORD
PGPASSWORD="$ADMIN_POSTGRES_PASSWORD" docker exec -i -e PGPASSWORD -e SMOKE_ROLE_PASSWORD \
  "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -v smoke_role="$SMOKE_APP_ROLE" \
  -v smoke_db="$POSTGRES_DB" -U "$ADMIN_POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null <<'SQL'
\getenv smoke_password SMOKE_ROLE_PASSWORD
CREATE ROLE :"smoke_role" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'smoke_password';
ALTER ROLE :"smoke_role" SET default_transaction_read_only = on;
REVOKE ALL ON DATABASE :"smoke_db" FROM :"smoke_role";
GRANT CONNECT ON DATABASE :"smoke_db" TO :"smoke_role";
REVOKE CREATE ON DATABASE :"smoke_db" FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE :"smoke_db" FROM PUBLIC;
SELECT set_config('umanews.smoke_role', :'smoke_role', false);
DO $body$
DECLARE schema_name text;
DECLARE role_name text := current_setting('umanews.smoke_role');
BEGIN
  FOR schema_name IN SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'
  LOOP
    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM PUBLIC', schema_name);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM %I', schema_name, role_name);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', schema_name, role_name);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA %I FROM PUBLIC', schema_name);
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', schema_name, role_name);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', schema_name, role_name);
    EXECUTE format('REVOKE USAGE, UPDATE ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC', schema_name);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I', schema_name, role_name);
    EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', schema_name, role_name);
    EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA %I FROM PUBLIC', schema_name);
    EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA %I FROM %I', schema_name, role_name);
  END LOOP;
END
$body$;
SQL
unset SMOKE_ROLE_PASSWORD

# Prove TCP password authentication and the role-level read-only default from
# the fixture itself before any old-image process is created.
if ! role_auth="$(app_psql -Atc "select current_user, current_setting('transaction_read_only')")"; then
  echo "old-image role authentication failed before startup" >&2
  exit 1
fi
if [ "$role_auth" != "$SMOKE_APP_ROLE|on" ]; then
  echo "old-image role authentication/read-only identity mismatch before startup" >&2
  exit 1
fi
echo "old-image-role-auth-verified"

audit_digest_sql="select md5(coalesce(string_agg(payload,'|' order by payload),'')) from (select 'migration:'||to_jsonb(t)::text payload from django_migrations t union all select 'receipt:'||to_jsonb(t)::text from stable_horseidentityevidencecommitreceipt t union all select 'operation:'||to_jsonb(t)::text from stable_operationlog t union all select 'field-change:'||to_jsonb(t)::text from stable_raceeventfieldchange t union all select 'event:'||to_jsonb(t)::text from stable_raceevent t union all select 'target:'||to_jsonb(t)::text from stable_historicalraceeventtarget t) audited"
before_audit_digest="$(admin_psql -Atc "BEGIN READ ONLY; $audit_digest_sql; COMMIT")"

run_old_image rm - "" sh -c 'cd /app/server && python manage.py check && python manage.py shell -c "import os; from django.db import DatabaseError, connection, transaction; from stable.models import RaceEventFieldChange; c=connection.cursor(); c.execute(\"select current_user, current_setting('\''transaction_read_only'\'')\"); identity=c.fetchone(); assert identity == (os.environ['\''POSTGRES_USER'\''], '\''on'\''), identity; print(RaceEventFieldChange.objects.order_by(\"pk\").values_list(\"pk\", flat=True).first()); denied=False
try:
    with transaction.atomic():
        with transaction.atomic():
            c.execute(\"insert into django_migrations(app,name,applied) values ('\''smoke-write-probe'\'','\''must-be-denied'\'',now())\")
        raise RuntimeError('\''write probe unexpectedly succeeded'\'')
except DatabaseError:
    denied=True
assert denied, '\''database did not reject explicit write probe'\''
print('\''old-image-db-read-only-verified'\'')"'
run_old_image daemon "$web_name" "" sh -c 'cd /app/server && python manage.py runserver 0.0.0.0:8000 --noreload' >/dev/null
run_old_image daemon "$worker_name" migration-repair-old-worker sh -c 'cd /app/server && celery -A app worker --loglevel=WARNING --concurrency=1' >/dev/null
run_old_image daemon "$beat_name" "" sh -c 'cd /app/server && celery -A app beat --loglevel=WARNING' >/dev/null

attempt=0
until docker exec "$web_name" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/healthz/", timeout=2).read()' >/dev/null 2>&1; do
  attempt=$((attempt + 1)); if [ "$attempt" -ge 30 ]; then echo "old-image web health failed" >&2; exit 1; fi
  sleep 1
done
docker exec "$worker_name" celery -A app inspect ping --destination celery@migration-repair-old-worker --timeout=10 | grep -Fq pong
for service_container in "$web_name" "$worker_name" "$beat_name"; do
  docker inspect --format '{{.State.Running}} {{.State.ExitCode}}' "$service_container" | grep -Fxq 'true 0'
  if docker logs "$service_container" 2>&1 | grep -Eiq 'permission denied|read-only transaction|cannot execute (INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)|traceback|(^|[^A-Z])(ERROR|CRITICAL)([^A-Z]|$)'; then
    echo "old-image service logged a write rejection or runtime error: $service_container" >&2
    exit 1
  fi
done

after_audit_digest="$(admin_psql -Atc "BEGIN READ ONLY; $audit_digest_sql; COMMIT")"
if [ "$before_audit_digest" != "$after_audit_digest" ]; then echo "old-image smoke changed audited migration/business rows" >&2; exit 1; fi
echo "old-image partial-state compatibility smoke passed (state=$EXPECTED_PARTIAL_STATE image=$PINNED_OLD_IMAGE_ID)"
