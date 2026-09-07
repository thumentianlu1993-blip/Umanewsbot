#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "${RELEASE_0078_TEST_POSTGRES:-}" = 1
test "${POSTGRES_HOST:-}" = 127.0.0.1
test "${POSTGRES_DB:-}" = release_0078_ci
test ! -e .env
test ! -e server/.env
evidence="$PWD/runtime/review_evidence/fix-0078-recovery-contract/ci"
mkdir -p "$evidence"
git rev-parse HEAD > "$evidence/commit.txt"
git diff --check
find deploy -name '*.sh' -print0 | xargs -0 -n1 bash -n
sha256sum deploy/release_0078.py server/stable/services/release_0078_recovery.py \
  server/stable/test_release_0078*.py > "$evidence/input-sha256.txt"
python --version > "$evidence/versions.txt"
pg_dump --version >> "$evidence/versions.txt"
cd server
python - <<'PY' 2>&1 | tee "$evidence/contract-tests.log"
import django
import unittest
django.setup()
labels = [
    'stable.test_release_0078_recovery',
    'stable.test_release_0078_entrypoints',
    'stable.test_release_0078_recovery_postgres',
]
suite = unittest.defaultTestLoader.loadTestsFromNames(labels)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped:
    raise SystemExit('Dedicated Linux/PG16 tests must not be skipped: ' + repr(result.skipped))
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
python manage.py check 2>&1 | tee "$evidence/django-check.log"
python manage.py makemigrations --check --dry-run 2>&1 | tee "$evidence/migration-drift.log"
