#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" != 0 ]]
[[ ! -S /var/run/docker.sock ]]
# 只复制由宿主 git archive 固定的输入，不挂载宿主工作区或凭据。
mkdir -p /tmp/work
cp -a /source/. /tmp/work/
cd /tmp/work
git init -q
git add -Af .
# Preserve the executor-verified commit identity; parents are unnecessary for tests.
test_commit=$(git hash-object -t commit -w /control/test-commit.raw)
[[ "$(git write-tree)" == "$(git rev-parse "$test_commit^{tree}")" ]]
git update-ref refs/heads/impact "$test_commit"
git symbolic-ref HEAD refs/heads/impact
exec python -B -m tools.test_impact.pg_lifecycle "$@"
