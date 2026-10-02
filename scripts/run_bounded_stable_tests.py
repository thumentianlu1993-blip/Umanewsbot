#!/usr/bin/env python3
"""隔离执行明确清单，最多 200 项；绝不回退到 stable 全量发现。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / 'docs/changes/fix-known-test-failures/failure_inventory.json'
LIMIT = 200


def read_inventory():
    rows = json.loads(INVENTORY.read_text())['failures']
    if (len(rows) != 50 or len({r['test'] for r in rows}) != 50
            or len({r['replacement'] for r in rows}) != 50
            or {r['group'] for r in rows} != set(range(1, 22))):
        raise ValueError('invalid failure inventory')
    return rows


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def validate_selection(suite):
    cases = list(flatten(suite))
    if not 0 < len(cases) <= LIMIT:
        raise ValueError(f'selection must contain 1..{LIMIT} tests, got {len(cases)}')
    if any(isinstance(case, unittest.loader._FailedTest) for case in cases):
        raise ValueError('test load failed; database setup refused')
    ids = [case.id() for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate test IDs')
    return ids


def evidence_passes(expected, executed, failures, errors, skipped, unexpected):
    return (len(expected) == len(executed) and set(expected) == set(executed)
            and not (failures or errors or skipped or unexpected))


def isolated_environment(source):
    host = source.get('POSTGRES_HOST', '127.0.0.1')
    database = source.get('POSTGRES_DB', 'bounded_ci')
    user = source.get('POSTGRES_USER', 'bounded_ci')
    port = source.get('POSTGRES_PORT', '55482')
    if (host != '127.0.0.1' or database not in ('bounded_ci', 'release_0078_ci')
            or user != database or not port.isdigit() or not 1 <= int(port) <= 65535):
        raise ValueError('only a dedicated local synthetic PostgreSQL destination is allowed')
    values = {key: source[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in source}
    values.update(DB_ENGINE='postgres', POSTGRES_HOST=host, POSTGRES_PORT=port,
                  POSTGRES_DB=database, POSTGRES_USER=user, POSTGRES_PASSWORD='synthetic-ci-only',
                  DJANGO_SETTINGS_MODULE='app.settings', CELERY_BROKER_URL='memory://',
                  CELERY_RESULT_BACKEND='cache+memory://', CELERY_TASK_ALWAYS_EAGER='1',
                  PYTHONDONTWRITEBYTECODE='1')
    return values


def build_validated_suite(labels, builder, **kwargs):
    raw_ids = validate_selection(unittest.TestLoader().loadTestsFromNames(labels))
    suite = builder(labels, **kwargs)
    if sorted(validate_selection(suite)) != sorted(raw_ids):
        raise ValueError('Django collection changed the declared selection')
    return suite


def run_with_evidence(runner, labels, payload):
    payload['passed'] = False
    try:
        status = runner.run_tests(labels)
    except BaseException:
        payload['passed'] = False
        raise
    payload['passed'] = not status and evidence_passes(
        payload['selected'], payload['executed'], payload['failures'], payload['errors'],
        payload['skipped'], payload['unexpected_successes'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--group', type=int, choices=range(1,22))
    selection.add_argument('--label', action='append')
    selection.add_argument('--batch', choices=('1', '2', '3', '4'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--keepdb', action='store_true', help='仅复用专用测试数据库')
    parser.add_argument('--list-only', action='store_true')
    args = parser.parse_args()
    rows = read_inventory()
    labels = ([r['replacement'] for r in rows if r['group'] == args.group]
              if args.group else args.label)
    batches = json.loads((INVENTORY.parent / 'regression_batches.json').read_text())['batches']
    if args.batch:
        labels = batches[args.batch]['labels']
    if any(label in ('stable', 'stable.tests_legacy') or not label.startswith('stable.') for label in labels):
        parser.error('explicit stable test class/module/method required; broad suites refused')
    output = args.output.resolve()
    environment = isolated_environment(os.environ)
    os.environ.clear()
    os.environ.update(environment)
    # macOS 的 /var 是符号链接；合成产物统一使用真实临时目录。
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
    os.environ['TMPDIR'] = tempfile.tempdir
    sys.dont_write_bytecode = True
    import dotenv
    dotenv.load_dotenv = lambda *a, **kw: False
    original_connect = socket.socket.connect
    allowed = ('127.0.0.1', int(environment['POSTGRES_PORT']))

    def connect(sock, address):
        if not isinstance(address, tuple) or address[:2] != allowed:
            raise RuntimeError('network disabled outside dedicated test PostgreSQL')
        return original_connect(sock, address)

    socket.socket.connect = connect
    sys.path.insert(0, str(ROOT / 'server'))
    sys.argv = ['manage.py', 'test']
    import django
    django.setup()
    from django.conf import settings
    from django.test.runner import DiscoverRunner
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    executed, durations = [], {}

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            executed.append(test.id())
            self.started = time.monotonic()
            super().startTest(test)

        def stopTest(self, test):
            durations[test.id()] = time.monotonic() - self.started
            super().stopTest(test)

    payload = {
        'schema_version': 1,
        'sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD'], cwd=ROOT)).hexdigest(),
        'inventory_sha256': hashlib.sha256(INVENTORY.read_bytes()).hexdigest(),
        'python': platform.python_version(), 'django': django.get_version(),
        'platform': platform.platform(), 'labels': labels, 'group': args.group, 'batch': args.batch,
        'passed': False,
    }

    class Runner(DiscoverRunner):
        def build_suite(self, test_labels=None, **kw):
            suite = build_validated_suite(test_labels, super().build_suite, **kw)
            payload['selected'] = validate_selection(suite)
            if args.batch and sorted(payload['selected']) != batches[args.batch]['expected_ids']:
                raise ValueError('batch collection drifted from reviewed manifest')
            print(json.dumps({'count': len(payload['selected']), 'selected': payload['selected']}), flush=True)
            return suite

        def get_resultclass(self):
            return Result

        def run_suite(self, suite, **kwargs):
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute('SELECT version()')
                payload['postgresql'] = cursor.fetchone()[0]
            result = super().run_suite(suite, **kwargs)
            payload.update(tests_run=result.testsRun, executed=executed, durations=durations,
                           failures=[(t.id(), e) for t, e in result.failures],
                           errors=[(t.id(), e) for t, e in result.errors],
                           skipped=[(t.id(), e) for t, e in result.skipped],
                           unexpected_successes=[t.id() for t in result.unexpectedSuccesses])
            return result

    start = time.monotonic()
    try:
        runner = Runner(verbosity=1, interactive=False, keepdb=args.keepdb)
        if args.list_only:
            runner.build_suite(labels)
            payload['collection_only'] = True
        else:
            run_with_evidence(runner, labels, payload)
    finally:
        payload['seconds'] = time.monotonic() - start
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return 0 if args.list_only or payload['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
