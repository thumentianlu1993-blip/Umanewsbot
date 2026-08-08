#!/bin/sh
set -eu

ACTIVE=/opt/umanews-release-c4ad7277-CxzJ88Sx/umanewsbot
ROOT=/opt/umanewsbot/backups/release-state/stale-review-reconcile-20260808
BEFORE="$ROOT/before.json"
HOST_EVIDENCE="$ROOT/host-shutdown-evidence.txt"
SCOPE_APPROVAL="$ROOT/scope-approval.txt"
SQL="$ROOT/reconcile_stale_review_claims_20260808.sql"
EXECUTABLE_APPROVAL="$ROOT/executable-approval.txt"

: "${EXPECTED_SQL_SHA256:?EXPECTED_SQL_SHA256 is required}"
: "${EXPECTED_WRAPPER_SHA256:?EXPECTED_WRAPPER_SHA256 is required}"
: "${EXPECTED_EXECUTABLE_APPROVAL_SHA256:?EXPECTED_EXECUTABLE_APPROVAL_SHA256 is required}"
: "${EXPECTED_EXECUTABLE_APPROVAL_SIZE:?EXPECTED_EXECUTABLE_APPROVAL_SIZE is required}"

cd "$ACTIVE"
DEPLOYMENT_LOCK_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export DEPLOYMENT_LOCK_TOKEN
COMPOSE_FILE=docker-compose.prod.lowcost.yml DEPLOYMENT_LOCK_ACTION=manual-release \
  ./deploy/deployment_lock.sh acquire
cleanup() { ./deploy/deployment_lock.sh release >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

test "$(sha256sum "$0" | awk '{print $1}')" = "$EXPECTED_WRAPPER_SHA256"
test "$(stat -c '%s:%a' "$0")" = 7422:700
test "$(sha256sum "$SQL" | awk '{print $1}')" = "$EXPECTED_SQL_SHA256"
test "$(stat -c '%s:%a' "$SQL")" = 6380:600
test "$(sha256sum "$EXECUTABLE_APPROVAL" | awk '{print $1}')" = "$EXPECTED_EXECUTABLE_APPROVAL_SHA256"
test "$(stat -c '%s:%a' "$EXECUTABLE_APPROVAL")" = "$EXPECTED_EXECUTABLE_APPROVAL_SIZE:600"
test "$(sha256sum "$BEFORE" | awk '{print $1}')" = d8669dae5ddfe95e6cdce8243852037d793ae70fd83ff4e8216237260728b4d0
test "$(stat -c '%s:%a' "$BEFORE")" = 2731:600
test "$(sha256sum "$HOST_EVIDENCE" | awk '{print $1}')" = 109562de4c91c6499a08deeb9f4c33f26bf8ff4ba550bd3663cb43a937f4882e
test "$(stat -c '%s:%a' "$HOST_EVIDENCE")" = 1691:600
test "$(sha256sum "$SCOPE_APPROVAL" | awk '{print $1}')" = 76789e32fd9bb0c9669c11ae497677288c8cf0ec4bf4a4ea500d425ce2251f7c
test "$(stat -c '%s:%a' "$SCOPE_APPROVAL")" = 1464:600
BACKUP=/opt/umanewsbot/backups/db/pre-stale-review-reconcile-20260808T130500Z.dump
test "$(sha256sum "$BACKUP" | awk '{print $1}')" = 09c9fd99f3a8ad120be0754b1da32b7561f3fa8713c7e6fdf9d83a364b39d7fc
test "$(stat -c '%s:%a' "$BACKUP")" = 411795027:600
test "$(docker exec -i umanewsbot-db-1 pg_restore -l < "$BACKUP" | wc -l)" = 1304

beat_cids="$(./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml ps -q beat)" || exit 1
worker_cids="$(./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml ps -q worker)" || exit 1
race_live_cids="$(./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml ps -q race_live_worker)" || exit 1
oneoff_cids="$(docker ps -q --filter label=com.docker.compose.project=umanewsbot --filter label=com.docker.compose.oneoff=True)" || exit 1
test -z "$beat_cids"
test -z "$worker_cids"
test -z "$race_live_cids"
test -z "$oneoff_cids"
after="$ROOT/after.json"
test ! -e "$after"

current_identity="$(./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell --no-imports -c 'import hashlib,json; from django.db import connection; s=connection.settings_dict; value={"engine":s.get("ENGINE",""),"host":s.get("HOST",""),"name":s.get("NAME",""),"port":str(s.get("PORT","")),"vendor":connection.vendor}; print(hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest())' | tail -n 1)"
test "$current_identity" = a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c

docker cp "$BEFORE" umanewsbot-db-1:/tmp/stale-review-before.json
docker exec -u root umanewsbot-db-1 chown postgres:postgres /tmp/stale-review-before.json
docker exec -u root umanewsbot-db-1 chmod 400 /tmp/stale-review-before.json
test "$(docker exec umanewsbot-db-1 stat -c '%s:%a:%U' /tmp/stale-review-before.json)" = 2731:400:postgres
test "$(docker exec umanewsbot-db-1 sha256sum /tmp/stale-review-before.json | awk '{print $1}')" = d8669dae5ddfe95e6cdce8243852037d793ae70fd83ff4e8216237260728b4d0

apply_lock_token_sha256="$(cat /tmp/umanews-deployment.lock/token_sha256)"
docker cp "$SQL" umanewsbot-db-1:/tmp/reconcile_stale_review_claims_20260808.sql
docker exec -u root umanewsbot-db-1 chown postgres:postgres /tmp/reconcile_stale_review_claims_20260808.sql
docker exec -u root umanewsbot-db-1 chmod 400 /tmp/reconcile_stale_review_claims_20260808.sql
test "$(sha256sum "$SQL" | awk '{print $1}')" = "$EXPECTED_SQL_SHA256"
test "$(docker exec umanewsbot-db-1 stat -c '%s:%a:%U' /tmp/reconcile_stale_review_claims_20260808.sql)" = 6380:400:postgres
test "$(docker exec umanewsbot-db-1 sha256sum /tmp/reconcile_stale_review_claims_20260808.sql | awk '{print $1}')" = "$EXPECTED_SQL_SHA256"
docker exec umanewsbot-db-1 sh -c 'psql -X -v ON_ERROR_STOP=1 -v apply_lock_token_sha256="$1" -v executable_approval_sha256="$2" -v reviewed_sql_sha256="$3" -v reviewed_wrapper_sha256="$4" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/reconcile_stale_review_claims_20260808.sql' sh "$apply_lock_token_sha256" "$EXPECTED_EXECUTABLE_APPROVAL_SHA256" "$EXPECTED_SQL_SHA256" "$EXPECTED_WRAPPER_SHA256"

umask 077
after_json="$(./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell --no-imports -c 'import json; from stable.models import RaceResultReviewRun; rows=list(RaceResultReviewRun.objects.filter(id__in=[39,43,44,45,46,47,48]).order_by("id").values()); print(json.dumps({"schema_version":"stale-review-after/v1","rows":rows},default=str,sort_keys=True,separators=(",",":")))')" || {
  echo "database committed but after export failed; rebuild from terminal_summary" >&2
  exit 1
}
after_tmp="$(mktemp "$ROOT/after.XXXXXXXX.tmp")"
cleanup_after() { rm -f "$after_tmp"; }
trap 'cleanup_after; exit 129' HUP
trap 'cleanup_after; exit 130' INT
trap 'cleanup_after; exit 143' TERM
chmod 600 "$after_tmp"
printf '%s\n' "$after_json" > "$after_tmp"
python3 - "$after_tmp" "$EXPECTED_EXECUTABLE_APPROVAL_SHA256" "$EXPECTED_SQL_SHA256" "$EXPECTED_WRAPPER_SHA256" <<'PY'
import json, sys
path, approval, sql_sha, wrapper_sha = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
assert set(payload) == {"schema_version", "rows"}
assert payload["schema_version"] == "stale-review-after/v1"
rows = payload["rows"]
assert [row["id"] for row in rows] == [39, 43, 44, 45, 46, 47, 48]
fields = {"id","created_at","updated_at","schedule_slot","status","selector_sha256","bundle_sha256","cursor","lease_expires_at","terminal_summary","finished_at"}
for row in rows:
    assert set(row) == fields
    assert row["status"] == "noop"
    summary = row["terminal_summary"]
    assert summary["executable_approval_sha256"] == approval
    assert summary["reviewed_sql_sha256"] == sql_sha
    assert summary["reviewed_wrapper_sha256"] == wrapper_sha
PY
ln "$after_tmp" "$after"
rm -f "$after_tmp"
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c 'from stable.models import RaceResultReviewRun; assert RaceResultReviewRun.objects.filter(status="claimed").count()==0; assert list(RaceResultReviewRun.objects.filter(id__in=[39,43,44,45,46,47,48]).values_list("status",flat=True))==["noop"]*7; print("after-verifier=ok")'
stat -c 'AFTER size=%s mode=%a path=%n' "$after"
sha256sum "$after"
