"""F02 argv-only Docker transport. Never connects until an explicit method call."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from scripts import f02_transfer as transfer

class AdapterError(ValueError):
    pass

@dataclass
class Result:
    code: str
    stdout: bytes = field(default=b'', repr=False)
    stderr: bytes = field(default=b'', repr=False)
    returncode: int | None = None
    reaped: bool = False


def group_live(pgid):
    """Check executing members of our newly created session/group; zombies are stopped."""
    if Path('/proc').is_dir():
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                values = path.read_text().rsplit(') ', 1)[1].split()
                if int(values[2]) == pgid and int(values[3]) == pgid and values[0] != 'Z':
                    return True
            except (OSError, ValueError, IndexError):
                continue
        return False
    try:
        result = subprocess.run(['/bin/ps', '-axo', 'pgid=,stat='], capture_output=True, timeout=0.2, check=True)
        if len(result.stdout) > 1024 * 1024:
            return True
        return any(int(line.split()[0]) == pgid and not line.split()[1].startswith(b'Z')
                   for line in result.stdout.splitlines() if len(line.split()) == 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return True  # unknown is live until independently proven otherwise


class Runner:
    def __init__(self, *, grace=2):
        if not 0 < grace <= 2:
            raise AdapterError('invalid_grace')
        self.grace = grace

    def run(self, argv, *, timeout=60, output_limit=8192):
        if (not isinstance(argv, list) or not argv or not all(isinstance(x, str) and '\0' not in x for x in argv)
                or not Path(argv[0]).is_absolute() or not 0 < timeout <= 60 or not 1 <= output_limit <= 65536):
            raise AdapterError('invalid_command')
        started = time.monotonic()
        deadline = started + timeout
        grace = min(self.grace, timeout / 4)
        # No inherited Docker/Python/POSTGRES/SSH settings or stdin. Absolute executable only.
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    shell=False, start_new_session=True, env=env)
        except OSError:
            return Result('spawn_failed')
        buffers = {1: bytearray(), 2: bytearray()}
        reason = None
        selector = selectors.DefaultSelector()
        try:
            for key, stream in ((1, proc.stdout), (2, proc.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, key)
            while True:
                if time.monotonic() >= deadline - 2 * grace:
                    reason = 'timeout'
                    break
                for event, _ in selector.select(min(0.05, max(0, deadline - time.monotonic() - 2 * grace))):
                    data = os.read(event.fd, min(8192, output_limit + 1))
                    if not data:
                        selector.unregister(event.fileobj)
                        continue
                    buffers[event.data].extend(data)
                    if sum(map(len, buffers.values())) > output_limit:
                        reason = 'output_limit'
                        break
                if reason:
                    break
                if proc.poll() is not None and not selector.get_map() and not group_live(proc.pid):
                    break
            if reason:
                self._stop(proc, signal.SIGTERM)
                end_term = min(deadline - grace, time.monotonic() + grace)
                while time.monotonic() < end_term and group_live(proc.pid):
                    time.sleep(0.01)
                if group_live(proc.pid):
                    self._stop(proc, signal.SIGKILL)
                try:
                    proc.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    return Result('reap_unknown')
                while group_live(proc.pid) and time.monotonic() < deadline:
                    time.sleep(0.01)
            else:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            reaped = proc.returncode is not None and not group_live(proc.pid)
            if not reaped:
                return Result('reap_unknown', returncode=proc.returncode)
            if reason:
                return Result(reason, returncode=proc.returncode, reaped=True)
            return Result('ok' if proc.returncode == 0 else 'command_failed', bytes(buffers[1]), bytes(buffers[2]),
                          proc.returncode, True)
        except Exception:
            self._stop(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.SubprocessError:
                pass
            return Result('reap_unknown', returncode=proc.returncode)
        finally:
            selector.close()
            proc.stdout.close()
            proc.stderr.close()

    @staticmethod
    def _stop(proc, sig):
        try:
            os.killpg(proc.pid, sig)  # only session we created; never pkill/killall
        except ProcessLookupError:
            pass


class DockerAdapter:
    """Bound host-local Docker adapter; constructor performs no Docker invocation."""
    def __init__(self, capsule, binding, runner=None):
        import re
        import stat
        transfer.validate_capsule(capsule)
        expected = {'docker_binary', 'socket_path', 'container_python', 'container_probe', 'container_binding',
                    'container_control_root', 'host_control_root', 'operation_prefix'}
        if set(binding) != expected:
            raise AdapterError('invalid_adapter_binding')
        for key in expected - {'operation_prefix'}:
            value = binding[key]
            if not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts or '\0' in value:
                raise AdapterError('invalid_adapter_path')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}', binding['operation_prefix']):
            raise AdapterError('invalid_operation_prefix')
        socket = transfer.check_path(binding['socket_path'])
        if not stat.S_ISSOCK(socket.stat().st_mode):
            raise AdapterError('not_local_unix_socket')
        stage_root = Path(capsule['container_output_root']).parents[2]
        for key in ('container_probe', 'container_binding', 'container_control_root'):
            if stage_root not in Path(binding[key]).parents:
                raise AdapterError('container_path_outside_stage')
        self.capsule = dict(capsule)
        self.binding = dict(binding)
        self.runner = runner or Runner()
        self.host_control = transfer.mkdir_private(binding['host_control_root'])
        self.pending_path = self.host_control / 'pending-probe.json'
        self.pending_probe = self._load_pending()

    def _load_pending(self):
        if not self.pending_path.exists():
            return None
        value = transfer.parse(transfer.read_file(self.pending_path, transfer.CONTROL_MAX))
        expected = {'capsule_sha256': transfer.capsule_sha(self.capsule), 'binding_sha256': transfer.capsule_sha(self.binding)}
        if (set(value) != set(expected) | {'operation_id'} or any(value[k] != v for k, v in expected.items())
                or not isinstance(value['operation_id'], str) or not transfer.NAME.fullmatch(value['operation_id'])):
            raise AdapterError('pending_probe_binding_conflict')
        return value['operation_id']

    def _save_pending(self, operation_id):
        transfer.atomic_json(self.pending_path, {'operation_id': operation_id,
            'capsule_sha256': transfer.capsule_sha(self.capsule), 'binding_sha256': transfer.capsule_sha(self.binding)})
        self.pending_probe = operation_id

    def _clear_pending(self):
        if self._load_pending() != self.pending_probe:
            raise AdapterError('pending_probe_changed')
        self.pending_path.unlink()
        transfer.fsync_directory(self.host_control)
        self.pending_probe = None

    def _call(self, tail, deadline, limit=8192):
        left = deadline - time.monotonic()
        if left <= 0:
            return Result('timeout')
        return self.runner.run([self.binding['docker_binary'], '--host=unix://' + self.binding['socket_path'], *tail],
                               timeout=min(60, left), output_limit=limit)

    def _helper(self, op, deadline, *, check=None):
        argv = ['exec', self.capsule['container_id'], self.binding['container_python'], '-I', '-B',
                self.binding['container_probe'], '--binding', self.binding['container_binding'], '--operation-id', op]
        if check is not None:
            argv.extend(['--check-operation-id', check])
        return self._call(argv, deadline)

    def _recover_helper(self, deadline):
        import uuid
        if self.pending_probe is None:
            return True
        op = self.binding['operation_prefix'] + '-' + uuid.uuid4().hex[:16]
        result = self._helper(op, deadline, check=self.pending_probe)
        if result.code != 'ok' or not result.reaped:
            transfer.atomic_json(self.host_control / 'ambiguous-helpers.json', {
                'capsule_sha256': transfer.capsule_sha(self.capsule),
                'operations': [self.pending_probe, op], 'state': 'unknown'})
            return False
        try:
            reply = transfer.parse(result.stdout)
            if set(reply) != {'state', 'operation_id'} or reply['operation_id'] != self.pending_probe:
                return False
            if reply['state'] != 'stopped':
                return False
        except (transfer.TransferError, TypeError, KeyError):
            return False
        self._clear_pending()
        return True

    def _probe(self, *, timeout):
        if (self.host_control / 'ambiguous-helpers.json').exists():
            return {'state': 'unknown'}
        import uuid
        if not 0 < timeout <= 60:
            raise AdapterError('invalid_timeout')
        end = time.monotonic() + timeout
        if not self._recover_helper(end):
            return {'state': 'unknown'}
        c = self.capsule
        identity = self._call(['inspect', '--type', 'container', '--format', '{{.Id}} {{.Image}} {{.State.Running}}', c['container_id']], end)
        if identity.code != 'ok' or not identity.reaped:
            exists = self._call(['container', 'ls', '--all', '--quiet', '--no-trunc', '--filter', 'id=' + c['container_id']], end)
            return {'state': 'source_lost' if exists.code == 'ok' and exists.reaped and exists.stdout.strip() == b'' else 'unknown'}
        parts = identity.stdout.strip().split()
        expected = [c['container_id'].encode(), c['image_id'].encode(), b'true']
        if parts != expected:
            raise AdapterError('source_identity_drift')
        image = self._call(['image', 'inspect', '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}', c['image_id']], end)
        if image.code != 'ok' or not image.reaped:
            return {'state': 'unknown'}
        if image.stdout.strip() != c['release_sha'].encode():
            raise AdapterError('image_revision_drift')
        op = self.binding['operation_prefix'] + '-' + uuid.uuid4().hex[:16]
        self._save_pending(op)  # persisted before exec; crashes cannot silently clear a residual helper
        result = self._helper(op, end)
        if result.code != 'ok' or not result.reaped:
            self._recover_helper(end)
            return {'state': 'unknown'}
        try:
            reply = transfer.parse(result.stdout)
            keys = {'state', 'release_sha', 'exporter_script_sha256', 'manifest_sha256', 'execution_uid',
                    'output_root', 'observation_id', 'owned_probe_stopped'}
            if set(reply) != keys or reply['owned_probe_stopped'] is not True:
                return {'state': 'unknown'}
            self._clear_pending()
            if reply['state'] != 'complete':
                return {'state': 'capture_unknown'}
            required = {'release_sha': c['release_sha'], 'exporter_script_sha256': c['exporter_script_sha256'],
                        'manifest_sha256': c['manifest_sha256'], 'execution_uid': c['execution_uid'],
                        'output_root': c['container_output_root'], 'observation_id': c['observation_id']}
            if any(reply[key] != value for key, value in required.items()):
                raise AdapterError('source_binding_drift')
            return {'state': 'complete', 'container_id': parts[0].decode(), 'image_id': parts[1].decode(),
                    **{key: reply[key] for key in ('release_sha', 'exporter_script_sha256', 'manifest_sha256', 'execution_uid')}}
        except (transfer.TransferError, TypeError, KeyError):
            return {'state': 'unknown'}

    def _copy(self, destination, *, timeout):
        if self.pending_probe is not None or (self.host_control / 'ambiguous-helpers.json').exists():
            raise AdapterError('owned_helper_outcome_unknown')
        destination = transfer.private_directory(destination)
        if any(destination.iterdir()):
            raise AdapterError('copy_destination_not_empty')
        source = self.capsule['container_id'] + ':' + self.capsule['container_output_root'] + '/' + self.capsule['observation_id'] + '/.'
        result = self._call(['cp', source, str(destination) + '/'], time.monotonic() + timeout)
        if result.code != 'ok' or not result.reaped:
            raise AdapterError('copy_outcome_unknown')

    def probe(self, *, timeout):
        with transfer.artifact_lock(self.host_control):
            self.pending_probe = self._load_pending()
            return self._probe(timeout=timeout)

    def copy(self, destination, *, timeout):
        with transfer.artifact_lock(self.host_control):
            self.pending_probe = self._load_pending()
            return self._copy(destination, timeout=timeout)
