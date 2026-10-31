#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" == 0 && "$(id -g)" == 0 ]]
[[ "$1" == run && "$3" == root-django ]]
[[ ! -S /var/run/docker.sock ]]
mkdir -p /tmp/work /tmp/pgwork
cp -a --no-preserve=ownership /source/. /tmp/work/
cd /tmp/work
git init -q
git add -Af .
test_commit=$(git hash-object -t commit -w /control/test-commit.raw)
[[ "$(git write-tree)" == "$(git rev-parse "$test_commit^{tree}")" ]]
git update-ref refs/heads/impact "$test_commit"
git symbolic-ref HEAD refs/heads/impact
chown 10001:10001 /tmp/pgwork
as_tester() { setpriv --reuid=10001 --regid=10001 --clear-groups "$@"; }
as_tester initdb -D /tmp/pgwork/data -A trust --encoding=UTF8 --no-locale >/tmp/pg-init.log
as_tester pg_ctl -D /tmp/pgwork/data -l /tmp/pgwork/postgres.log -o '-h 127.0.0.1 -p 5432 -k /tmp/pgwork' -w start
as_tester createuser -h 127.0.0.1 -U tester --superuser bounded_ci
as_tester createdb -h 127.0.0.1 -U tester -O bounded_ci bounded_ci
# Docker destroys this one-shot namespace and PG when the worker exits.
exec setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs python scripts/test_plan_worker.py "$@"
