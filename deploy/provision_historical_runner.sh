#!/bin/sh
set -eu

INTERNAL_NETWORK="${HISTORICAL_RUNNER_INTERNAL_NETWORK:-umanews-historical-runner-db}"
EGRESS_NETWORK="${HISTORICAL_RUNNER_EGRESS_NETWORK:-umanews-historical-runner-egress}"
DB_CONTAINER="${HISTORICAL_RUNNER_DB_CONTAINER:-umanewsbot-db-1}"
CONTROL_ROLE="${HISTORICAL_RUNNER_CONTROL_ROLE:-historical_runner_control}"
CONTROL_PASSWORD_FILE="${HISTORICAL_RUNNER_CONTROL_PASSWORD_FILE:-}"
POSTGRES_DB="${POSTGRES_DB:-horse_news}"
POSTGRES_ADMIN_USER="${POSTGRES_ADMIN_USER:-postgres}"

case "$CONTROL_ROLE" in *[!a-zA-Z0-9_]*) echo "invalid control role" >&2; exit 1 ;; esac
[ -n "$CONTROL_PASSWORD_FILE" ] || { echo "HISTORICAL_RUNNER_CONTROL_PASSWORD_FILE is required" >&2; exit 1; }
[ -f "$CONTROL_PASSWORD_FILE" ] || { echo "control password file missing" >&2; exit 1; }
mode="$(stat -c '%a' "$CONTROL_PASSWORD_FILE" 2>/dev/null || stat -f '%Lp' "$CONTROL_PASSWORD_FILE")"
[ "$mode" = "600" ] || { echo "control password file must be 0600" >&2; exit 1; }
password="$(cat "$CONTROL_PASSWORD_FILE")"
[ -n "$password" ] || { echo "control password file is empty" >&2; exit 1; }
password_b64="$(printf '%s' "$password" | base64 | tr -d '\n')"

docker network inspect "$INTERNAL_NETWORK" >/dev/null 2>&1 || docker network create --internal "$INTERNAL_NETWORK"
docker network inspect "$EGRESS_NETWORK" >/dev/null 2>&1 || docker network create "$EGRESS_NETWORK"
docker container inspect "$DB_CONTAINER" >/dev/null
if ! docker container inspect "$DB_CONTAINER" --format '{{json .NetworkSettings.Networks}}' | grep -q "\"$INTERNAL_NETWORK\""; then
  docker network connect --alias db "$INTERNAL_NETWORK" "$DB_CONTAINER"
fi

{
printf "\\set control_password_b64 '%s'\n" "$password_b64"
cat <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L',
  :'control_role',
  convert_from(decode(:'control_password_b64', 'base64'), 'UTF8')
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'control_role') \gexec
SELECT format(
  'ALTER ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 5',
  :'control_role', convert_from(decode(:'control_password_b64', 'base64'), 'UTF8')
) \gexec
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM :"control_role";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM :"control_role";
REVOKE ALL ON SCHEMA public FROM :"control_role";
GRANT CONNECT ON DATABASE :"database_name" TO :"control_role";
GRANT USAGE ON SCHEMA public TO :"control_role";
GRANT SELECT, INSERT, UPDATE ON TABLE stable_historicalbatchrun, stable_historicalbatchlock TO :"control_role";
GRANT SELECT, INSERT ON TABLE stable_historicalbatchrunevent TO :"control_role";
GRANT USAGE, SELECT ON SEQUENCE
  stable_historicalbatchrun_id_seq,
  stable_historicalbatchlock_id_seq,
  stable_historicalbatchrunevent_id_seq
TO :"control_role";

SELECT has_schema_privilege(:'control_role', 'public', 'CREATE') AS unexpected_schema_create \gset
\if :unexpected_schema_create
  \echo 'control role inherits unexpected CREATE privilege on public schema'
  \quit 1
\endif

SELECT EXISTS (
  SELECT 1
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
    AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    AND c.relname NOT IN (
      'stable_historicalbatchrun',
      'stable_historicalbatchlock',
      'stable_historicalbatchrunevent'
    )
    AND (
      has_table_privilege(:'control_role', c.oid, 'INSERT')
      OR has_table_privilege(:'control_role', c.oid, 'UPDATE')
      OR has_table_privilege(:'control_role', c.oid, 'DELETE')
      OR has_table_privilege(:'control_role', c.oid, 'TRUNCATE')
      OR has_table_privilege(:'control_role', c.oid, 'REFERENCES')
      OR has_table_privilege(:'control_role', c.oid, 'TRIGGER')
    )
) AS unexpected_business_write \gset
\if :unexpected_business_write
  \echo 'control role has unexpected business-table write privilege'
  \quit 1
\endif

SELECT EXISTS (
  SELECT 1
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
    AND c.relkind = 'S'
    AND c.relname NOT IN (
      'stable_historicalbatchrun_id_seq',
      'stable_historicalbatchlock_id_seq',
      'stable_historicalbatchrunevent_id_seq'
    )
    AND (
      has_sequence_privilege(:'control_role', c.oid, 'USAGE')
      OR has_sequence_privilege(:'control_role', c.oid, 'UPDATE')
    )
) AS unexpected_business_sequence_write \gset
\if :unexpected_business_sequence_write
  \echo 'control role has unexpected business-sequence write privilege'
  \quit 1
\endif
SQL
} | docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -v control_role="$CONTROL_ROLE" -v database_name="$POSTGRES_DB" -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB"
unset password password_b64
echo "historical runner networks and historical_runner_control role verified"
