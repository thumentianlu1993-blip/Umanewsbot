"""RUN producer 的纯离线 FD/交错合同；不加载业务、Django 或真实 Docker。"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import platform
import select
import sys
import tempfile
import threading
import time
import traceback
import types
import unittest
from unittest.mock import patch

from tools.test_impact.core import digest
from tools.test_impact.serial_ci import Serial, save
from tools.test_impact.test_serial_ci import FakeExecutor
from tools.test_impact.test_pg_lifecycle import save_synthetic_lifecycle


OBSERVED_ID = 'stable.test_race_event_lifecycle.ManifestUSZoneValidationTests.test_non_us_omits_allowlist_succeeds'
DIAGNOSTIC = "manifest 校验: event 1: 'Asia/Tokyo' 不是 America/*"
OBSERVED_LINE = "RUN stable.test_race_event_lifecycle.ManifestUSZoneValidationTests.test_non_us_omits_allowlist_succeedsmanifest 校验: event 1: 'Asia/Tokyo' 不是 America/*"
ROOT = Path(__file__).resolve().parents[2]


def synthetic_case(ident, body=lambda case: None):
    class Case(unittest.TestCase):
        def id(self):
            return ident

        def runTest(self):
            body(self)
    return Case()


def execute_synthetic(cases, stream):
    # Execute the real worker function, excluding setup/import side effects.
    tree = ast.parse((ROOT / 'scripts/test_plan_worker.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    namespace = dict(time=time, digest=digest, platform=platform, unittest=unittest,
                     traceback=traceback, sys=sys, load=lambda labels: cases,
                     isolation_probe=lambda profile: {'synthetic_offline': True})
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'real-worker-execute', 'exec'), namespace)
    django = types.ModuleType('django')
    django.get_version = lambda: 'synthetic-version-only'
    batch = dict(key='batch-000', profile='python', ids=[case.id() for case in cases])
    plan = dict(run_id='9', run_attempt='1', test_tree='b' * 40, batches=[batch])
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()), \
            patch.dict(sys.modules, {'django': django}):
        return namespace['execute'](plan, batch)


class NativeRunProducerTests(unittest.TestCase):
    def interleaved_output(self):
        read_fd, write_fd = os.pipe()
        boundary, diagnostic_done = threading.Event(), threading.Event()
        errors = []

        class BoundaryRaw(io.RawIOBase):
            armed = True

            def writable(self):
                return True

            def write(self, data):
                written = os.write(write_fd, data)
                if self.armed and bytes(data).startswith(b'RUN '):
                    self.armed = False
                    boundary.set()
                    if not diagnostic_done.wait(5):
                        raise RuntimeError('diagnostic writer did not finish at forced boundary')
                return written

        def diagnostic():
            try:
                if not boundary.wait(5):
                    raise RuntimeError('producer did not reach first RUN write boundary')
                os.write(write_fd, (DIAGNOSTIC + '\n').encode())
            except BaseException as error:
                errors.append(repr(error))
            finally:
                diagnostic_done.set()

        # Docker sets PYTHONUNBUFFERED=1: one TextIO write reaches the raw FD.
        stream = io.TextIOWrapper(BoundaryRaw(), encoding='utf-8', write_through=True)
        writer = threading.Thread(target=diagnostic, name='synthetic-diagnostic-writer')
        writer.start()
        try:
            report = execute_synthetic([synthetic_case(OBSERVED_ID)], stream)
        finally:
            boundary.set()
            writer.join(5)
            stream.close()
            os.close(write_fd)
        try:
            output = os.read(read_fd, 65536)
        finally:
            os.close(read_fd)
        self.assertFalse(writer.is_alive(), 'offline diagnostic writer leaked')
        self.assertEqual(errors, [])
        return output, report

    def prepare_serial(self, raw):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        output, selection = root / 'evidence', root / 'selection.json'
        save(selection, dict(base_sha='a' * 40, mode='full', source='git', test_sha='a' * 40,
                             test_tree='b' * 40, run_id='9', run_attempt='1', labels=['m', 'r']))
        fake = FakeExecutor(root)
        original = fake.run

        def run(command, deadline, ledger):
            result = original(command, deadline, ledger)
            if '--collect-only' in command:
                path = output / 'execution-plan.json'
                plan = json.loads(path.read_text())
                plan['batches'][0]['ids'] = [OBSERVED_ID]
                save(path, plan)
                input_plan=json.loads(Path(command[command.index('--plan')+1]).read_text())
                save_synthetic_lifecycle(output,{**input_plan,'image_id':plan['image_id']},'collect')
            elif '--batch' in command and command[command.index('--batch') + 1] == 'batch-000':
                (output / 'batch-000.log').write_bytes(raw)
            return result

        fake.run = run
        serial = Serial(output, {'start': 0}, fake, clock=lambda: 0)
        serial.collect(selection, root / 'image.tar')
        return serial, fake

    def test_run_record_stays_whole_at_forced_diagnostic_write_boundary(self):
        output, report = self.interleaved_output()
        self.assertEqual(output.decode().splitlines(), ['RUN ' + OBSERVED_ID, DIAGNOSTIC])
        self.assertEqual(report['executed'], [OBSERVED_ID])
        self.assertEqual((report['lifecycle'], report['exit_code']), ('complete', 0))
        self.assertEqual((report['failures'], report['errors']), ([], []))

    def test_unchanged_parser_accepts_actual_producer_output(self):
        output, report = self.interleaved_output()
        serial, fake = self.prepare_serial(output)
        try:
            serial.execute()
        except ValueError as error:
            self.fail('producer output rejected by unchanged strict parser: ' + str(error))
        self.assertEqual((serial.output / 'batch-000.log').read_bytes(), output)
        self.assertFalse(serial.status['fatal'])
        self.assertTrue(serial.status['attempted']['batch-001']['complete'])

    def test_unchanged_parser_rejects_original_manifest_join_without_rewriting_it(self):
        raw = (OBSERVED_LINE + '\n').encode()
        serial, fake = self.prepare_serial(raw)
        with self.assertRaisesRegex(ValueError, 'strict native lifecycle/RUN/identity failure'):
            serial.execute()
        self.assertEqual((serial.output / 'batch-000.log').read_bytes(), raw)
        self.assertTrue(serial.status['fatal'])
        self.assertEqual(serial.status['not_started'], ['batch-001'])
        self.assertFalse(any('--batch' in c and c[c.index('--batch') + 1] == 'batch-001'
                             for c in fake.calls))

    def test_buffered_records_are_visible_before_cases_and_outcomes_keep_ids_order(self):
        read_fd, write_fd = os.pipe()
        stream = io.TextIOWrapper(io.BufferedWriter(io.FileIO(write_fd, 'wb', closefd=False)), encoding='utf-8')
        seen = []

        def body(outcome):
            def run(case):
                ready, _, _ = select.select([read_fd], [], [], 0)
                seen.append(os.read(read_fd, 4096) if ready else b'')
                if outcome == 'skip':
                    case.skipTest('synthetic skip')
                elif outcome == 'failure':
                    case.fail('synthetic assertion failure')
                elif outcome == 'error':
                    raise RuntimeError('synthetic error')
            return run

        ids = ['fixture.C.test_pass', 'fixture.C.test_skip', 'fixture.C.test_failure', 'fixture.C.test_error']
        cases = [synthetic_case(ident, body(outcome))
                 for ident, outcome in zip(ids, ['pass', 'skip', 'failure', 'error'])]
        try:
            report = execute_synthetic(cases, stream)
        finally:
            stream.close()
            os.close(write_fd)
            os.close(read_fd)
        self.assertEqual(seen, [b'RUN fixture.C.test_pass\n', b'RUN fixture.C.test_skip\n',
                                b'RUN fixture.C.test_failure\n', b'RUN fixture.C.test_error\n'])
        self.assertEqual(report['executed'], ids)
        self.assertEqual((report['lifecycle'], report['exit_code']), ('complete', 1))
        self.assertEqual(report['skips'], [{'id': 'fixture.C.test_skip', 'reason': 'synthetic skip'}])
        self.assertEqual([x['id'] for x in report['failures']], ['fixture.C.test_failure'])
        self.assertEqual([x['id'] for x in report['errors']], ['fixture.C.test_error'])
        self.assertEqual((report['expected_failures'], report['unexpected_successes']), ([], []))
