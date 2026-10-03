"""Synthetic argv responses and real local Python process trees; no Docker/SSH."""
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from scripts import f02_docker_adapter as adapter

class RunnerTests(unittest.TestCase):
    def test_output_is_internal_bounded_and_success_reaped(self):
        result = adapter.Runner().run([sys.executable, '-c', 'print("synthetic")'], timeout=2)
        self.assertEqual(result.code, 'ok')
        self.assertEqual(result.stdout.strip(), b'synthetic')
        self.assertTrue(result.reaped)
        self.assertNotIn('synthetic', repr(result))

    def test_timeout_reaps_TERM_ignoring_child_and_grandchild(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'child-pid'
            child = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'
            parent = ('import subprocess,signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                      'p=subprocess.Popen(' + repr([sys.executable, '-c', child]) + ');'
                      'pathlib.Path(' + repr(str(marker)) + ').write_text(str(p.pid));time.sleep(60)')
            started = time.monotonic()
            result = adapter.Runner(grace=0.1).run([sys.executable, '-c', parent], timeout=0.7)
            self.assertEqual(result.code, 'timeout')
            self.assertTrue(result.reaped)
            self.assertLess(time.monotonic()-started, 2)
            pid = int(marker.read_text())
            # A zombie has stopped executing; this is not a live residual process.
            if Path('/proc').exists() and Path('/proc', str(pid), 'stat').exists():
                self.assertEqual(Path('/proc', str(pid), 'stat').read_text().split(') ')[1][0], 'Z')
            else:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_stdout_stderr_flood_is_bounded_and_reaped(self):
        code = 'import os,time;os.write(1,b"PRIVATE"*10000);os.write(2,b"SECRET"*10000);time.sleep(60)'
        result = adapter.Runner(grace=0.1).run([sys.executable, '-c', code], timeout=1, output_limit=1024)
        self.assertEqual(result.code, 'output_limit')
        self.assertTrue(result.reaped)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn('PRIVATE', repr(result))

    def test_no_shell_and_invalid_argv_refused(self):
        for argv in ('echo SECRET', ['relative', 'x'], [sys.executable, 1]):
            with self.assertRaises(adapter.AdapterError):
                adapter.Runner().run(argv)

from scripts.tests.test_f02_transfer import fixture
from scripts import f02_transfer as transfer

class FakeRunner:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return next(self.responses)

class DockerAdapterTests(unittest.TestCase):
    def setup_adapter(self, base, responses):
        directory, capsule, metadata = fixture(base)
        binding = {'docker_binary': sys.executable, 'socket_path': str(base.resolve() / 'docker.sock'),
                   'container_python': '/usr/local/bin/python', 'container_probe': '/tmp/f02-capsule/tools/probe.py',
                   'container_binding': '/tmp/f02-capsule/control/probe.json', 'container_control_root': '/tmp/f02-capsule/control',
                   'host_control_root': str(base.resolve() / 'adapter-control'),
                   'operation_prefix': 'synthetic-test'}
        import socket
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(binding['socket_path'])
        self.addCleanup(sock.close)
        runner = FakeRunner(responses)
        return adapter.DockerAdapter(capsule, binding, runner), capsule, runner

    def test_actual_inspect_and_probe_values_merged_not_capsule_echo(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            directory, capsule, _ = fixture(base)
            inner = {key: capsule[key] for key in ('release_sha', 'exporter_script_sha256', 'manifest_sha256')}
            inner.update(state='complete', execution_uid=0, output_root=capsule['container_output_root'],
                         observation_id=capsule['observation_id'], owned_probe_stopped=True)
            responses = [adapter.Result('ok', (capsule['container_id']+' '+capsule['image_id']+' true\n').encode(), reaped=True),
                         adapter.Result('ok', (capsule['release_sha']+'\n').encode(), reaped=True),
                         adapter.Result('ok', json.dumps(inner).encode(), reaped=True)]
            # fixture was already created for expected data; use separate directory for adapter fixture.
            other = base.resolve() / 'other'
            other.mkdir(mode=0o700)
            obj, expected, runner = self.setup_adapter(other, responses)
            result = obj.probe(timeout=2)
            self.assertEqual(result['state'], 'complete')
            for key in transfer.IDENTITY:
                self.assertEqual(result[key], expected[key])
            self.assertEqual(len(runner.calls), 3)
            self.assertTrue(all(call[0][1].startswith('--host=unix://') for call in runner.calls))
            self.assertIn('-I', runner.calls[-1][0])

    def test_daemon_unknown_is_distinct_from_confirmed_missing(self):
        for found in (None, b'', b'c'*64):
            with self.subTest(found=found), tempfile.TemporaryDirectory() as temp:
                responses = [adapter.Result('command_failed', returncode=1, reaped=True),
                             adapter.Result('timeout') if found is None else adapter.Result('ok', found, reaped=True)]
                obj, _, _ = self.setup_adapter(Path(temp), responses)
                self.assertEqual(obj.probe(timeout=2)['state'], 'source_lost' if found == b'' else 'unknown')

    def test_exec_timeout_requires_owned_helper_stop_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            obj, capsule, runner = self.setup_adapter(Path(temp), [])
            runner.responses = iter([
                adapter.Result('ok', (capsule['container_id']+' '+capsule['image_id']+' true').encode(), reaped=True),
                adapter.Result('ok', capsule['release_sha'].encode(), reaped=True),
                adapter.Result('timeout', reaped=True),
                adapter.Result('ok', b'{"state":"running"}', reaped=True),
            ])
            self.assertEqual(obj.probe(timeout=2)['state'], 'unknown')
            self.assertTrue(obj.pending_probe)
            with self.assertRaises(adapter.AdapterError):
                obj.copy(Path(temp).resolve(), timeout=2)
            self.assertIn('--check-operation-id', runner.calls[-1][0])

from scripts import f02_container_probe as probe
from unittest.mock import patch
import json

class ContainerProbeTests(unittest.TestCase):
    def test_probe_actual_files_and_marker_not_echoed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            directory, capsule, _ = fixture(base)
            stage = directory.parents[3]
            tools = stage / 'tools'; tools.mkdir(mode=0o700)
            script = tools / 'export.py'; script.write_bytes(b'synthetic fixed script'); script.chmod(0o600)
            marker = base / 'marker'; marker.write_text('a'*40); marker.chmod(0o644)
            control = stage / 'control'; control.mkdir(mode=0o700)
            binding = {'schema_version': 1, 'script_path': str(script), 'script_sha256': probe.sha(script.read_bytes()),
                       'probe_sha256': probe.sha(Path(probe.__file__).read_bytes()), 'marker_path': str(marker),
                       'release_sha': 'a'*40, 'output_root': str(directory.parent), 'observation_id': directory.name,
                       'manifest_sha256': capsule['manifest_sha256'], 'execution_uid': os.geteuid(),
                       'control_root': str(control), 'timeout_seconds': 2}
            result = probe.inspect(binding)
            self.assertEqual(result['state'], 'complete')
            control.chmod(0o755)
            with self.assertRaises(probe.ProbeError):
                probe.inspect(binding)
            control.chmod(0o700)
            marker.write_text('e'*40)
            with self.assertRaises(probe.ProbeError):
                probe.inspect(binding)
            marker.write_text('a'*40)
            script.write_bytes(b'changed')
            with self.assertRaises(probe.ProbeError):
                probe.inspect(binding)

    def test_reused_pid_is_unknown_without_kill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            binding = {'control_root': str(root), 'probe_sha256': 'a'*64, 'execution_uid': os.geteuid()}
            record = {'pid': 123, 'start_ticks': '100', 'uid': os.geteuid(), 'probe_sha256': 'a'*64,
                      'operation_id': 'owned-test', 'binding_sha256': probe.sha(probe.encoded(binding))}
            probe.save_once(root/'owned-test.pid.json', record)
            actual = {'start_ticks': '200', 'state': 'S', 'uid': os.geteuid(),
                      'argv': [str(Path(probe.__file__)).encode(), b'--operation-id', b'owned-test']}
            with patch.object(probe, 'proc_identity', return_value=actual), patch.object(probe.os, 'kill') as kill:
                self.assertEqual(probe.operation_status(binding, 'owned-test')['state'], 'unknown')
                kill.assert_not_called()

    def test_pending_helper_survives_adapter_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            case = DockerAdapterTests('test_exec_timeout_requires_owned_helper_stop_confirmation')
            case.addCleanup = self.addCleanup
            obj, capsule, runner = case.setup_adapter(Path(temp), [])
            runner.responses = iter([
                adapter.Result('ok', (capsule['container_id']+' '+capsule['image_id']+' true').encode(), reaped=True),
                adapter.Result('ok', capsule['release_sha'].encode(), reaped=True),
                adapter.Result('timeout', reaped=True),
                adapter.Result('ok', b'{"state":"running"}', reaped=True),
            ])
            self.assertEqual(obj.probe(timeout=2)['state'], 'unknown')
            restarted = adapter.DockerAdapter(capsule, obj.binding, runner)
            self.assertEqual(restarted.pending_probe, obj.pending_probe)

class HelperChainTests(unittest.TestCase):
    def test_secondary_helper_unknown_quarantines_chain_and_blocks_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            case=DockerAdapterTests('test_exec_timeout_requires_owned_helper_stop_confirmation')
            case.addCleanup=self.addCleanup
            obj,capsule,runner=case.setup_adapter(Path(temp),[])
            runner.responses=iter([
                adapter.Result('ok',(capsule['container_id']+' '+capsule['image_id']+' true').encode(),reaped=True),
                adapter.Result('ok',capsule['release_sha'].encode(),reaped=True),
                adapter.Result('timeout',reaped=True),adapter.Result('timeout',reaped=True)])
            self.assertEqual(obj.probe(timeout=2)['state'],'unknown')
            evidence=json.loads((obj.host_control/'ambiguous-helpers.json').read_text())
            self.assertEqual(len(evidence['operations']),2)
            again=adapter.DockerAdapter(capsule,obj.binding,runner)
            self.assertEqual(again.probe(timeout=2)['state'],'unknown')
            self.assertEqual(len(runner.calls),4)
            with self.assertRaises(adapter.AdapterError):again.copy(Path(temp).resolve(),timeout=2)
