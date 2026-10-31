#!/usr/bin/env python3
"""在真实候选应用镜像中执行唯一镜像合同；无Docker、数据库或宿主回退。"""
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time
import traceback
import unittest

# tools来自只读、冻结的控制源码；业务与测试始终来自实际应用镜像。
sys.path[:0] = ['/app/server', '/source']
from tools.test_impact.core import digest
from tools.test_impact.source_binding import verify_source_binding
from tools.test_impact.special_profiles import IMAGE_TEST, expected_image, validate_special_batch


def verify_application_source(plan, binding):
    verify_source_binding(plan, binding, Path('/source'))
    if Path('/app/.umanews-release-commit').read_text().strip() != plan['test_sha']:
        raise ValueError('application revision mismatch')
    expected = {name.removeprefix('server/'): info for name, info in binding['files'].items() if name.startswith('server/')}
    actual = {str(p.relative_to('/app/server')) for p in Path('/app/server').rglob('*')
              if p.is_file() and 'runtime' != p.relative_to('/app/server').parts[0]}
    if actual != set(expected):
        raise ValueError('application server file set mismatch')
    for name, info in expected.items():
        file = Path('/app/server') / name
        body = file.read_bytes()
        oid = hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()
        if file.is_symlink() or oid != info['blob']:
            raise ValueError('application server source mismatch: '+name)


def main():
    plan = json.loads(Path('/control/plan.json').read_text())
    batch = next(b for b in plan['batches'] if b['key'] == sys.argv[1])
    validate_special_batch(batch)
    if batch['profile'] != 'application-image': raise ValueError('application profile required')
    report = {'key': batch['key'], 'profile': batch['profile'], 'plan_digest': digest(plan),
              **{k: plan[k] for k in ('run_id', 'run_attempt', 'test_tree')},
              'image_id': expected_image(plan, batch), 'executed': [], 'failures': [], 'errors': [],
              'skips': [], 'expected_failures': [], 'unexpected_successes': [],
              'exit_code': 1, 'lifecycle': 'incomplete', 'python': platform.python_version()}
    start = time.monotonic()
    try:
        if os.getuid() != 10001 or os.getgid() != 10001 or Path('/var/run/docker.sock').exists():
            raise ValueError('unsafe application container identity')
        if set(os.listdir('/sys/class/net')) != {'lo'}: raise ValueError('application network not isolated')
        try:
            socket.create_connection(('1.1.1.1',443), 1)
        except OSError:
            pass
        else:
            raise ValueError('application external network available')
        binding = json.loads(Path('/control/source-binding.json').read_text())
        verify_application_source(plan, binding)
        os.environ.clear()
        os.environ.update(DJANGO_SETTINGS_MODULE='app.settings', DB_ENGINE='sqlite', SQLITE_PATH='/tmp/image-contract.sqlite3',
                          DOTENV_DISABLED='1', SECRET_KEY='synthetic-image-contract', IMPACT_APPLICATION_IMAGE_CONTRACT='true')
        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        import django
        django.setup()
        class Result(unittest.TextTestResult):
            def startTest(self, test): report['executed'].append(test.id()); super().startTest(test)
            def addSkip(self, test, reason): report['skips'].append({'id': test.id(), 'reason': reason}); super().addSkip(test, reason)
        suite = unittest.defaultTestLoader.loadTestsFromName(IMAGE_TEST)
        result = unittest.TextTestRunner(resultclass=Result).run(suite)
        for field in ('failures', 'errors'):
            report[field] = [{'id': t.id(), 'traceback': err} for t, err in getattr(result, field)]
        report['expected_failures'] = [t.id() for t, _ in result.expectedFailures]
        report['unexpected_successes'] = [t.id() for t in result.unexpectedSuccesses]
        report.update(exit_code=int(not result.wasSuccessful()), lifecycle='complete',
                      isolation={'uid': 10001, 'interfaces': ['lo'], 'docker_socket': 'absent'}, application_revision=plan['test_sha'])
    except BaseException:
        report['errors'].append({'id': 'infrastructure', 'traceback': traceback.format_exc()})
    report['seconds'] = time.monotonic() - start
    Path('/output', batch['key']+'.json').write_text(json.dumps(report, indent=2)+'\n')
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
