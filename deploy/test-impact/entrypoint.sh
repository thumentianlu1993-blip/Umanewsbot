#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" != 0 ]]
[[ ! -S /var/run/docker.sock ]]
# 只复制由宿主 git archive 固定的输入，不挂载宿主工作区或凭据。
mkdir -p /tmp/work
cp -a /source/. /tmp/work/
cd /tmp/work
git init -q
git add -A
if [[ "$1" == collect || "$3" != python ]]; then
  initdb -D /tmp/pgdata -A trust --no-locale >/tmp/pg-init.log
  pg_ctl -D /tmp/pgdata -l /tmp/postgres.log -o '-h 127.0.0.1 -p 5432 -k /tmp' -w start >/tmp/pg-start.log
  trap 'pg_ctl -D /tmp/pgdata -m immediate -w stop >/dev/null' EXIT
  createuser -h 127.0.0.1 -U tester --superuser bounded_ci
  createuser -h 127.0.0.1 -U tester --superuser release_0078_ci
  createdb -h 127.0.0.1 -U tester -O bounded_ci bounded_ci
  createdb -h 127.0.0.1 -U tester -O release_0078_ci release_0078_ci
fi
python scripts/test_plan_worker.py "$@"
