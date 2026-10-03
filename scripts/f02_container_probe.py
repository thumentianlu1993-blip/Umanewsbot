"""Standalone Linux F02 probe. No DB, network, subprocess or package imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import time

class ProbeError(ValueError):
    pass

def check(value, code):
    if not value:
        raise ProbeError(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def private_path(path):
    path = Path(path)
    check(path.is_absolute() and '..' not in path.parts, 'invalid_path')
    check(not any(p.is_symlink() for p in (path, *path.parents)), 'linked_path')
    return path

def read(path, maximum=65536, mode=0o600):
    path = private_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        check(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
              and stat.S_IMODE(info.st_mode) == mode and info.st_size <= maximum, 'invalid_file')
        data = stream.read(maximum + 1)
        check(len(data) <= maximum, 'byte_budget')
        return data

def validate(binding):
    keys = {'schema_version', 'script_path', 'script_sha256', 'probe_sha256', 'marker_path', 'release_sha',
            'output_root', 'observation_id', 'manifest_sha256', 'execution_uid', 'control_root', 'timeout_seconds'}
    check(isinstance(binding, dict) and set(binding) == keys and binding['schema_version'] == 1, 'invalid_binding')
    for key in ('script_sha256', 'probe_sha256', 'manifest_sha256'):
        check(isinstance(binding[key], str) and re.fullmatch('[0-9a-f]{64}', binding[key]), 'invalid_hash')
    check(re.fullmatch('[0-9a-f]{40}', binding['release_sha']), 'invalid_release')
    check(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', binding['observation_id']), 'invalid_observation')
    check(type(binding['timeout_seconds']) is int and 1 <= binding['timeout_seconds'] <= 10, 'invalid_timeout')
    check(type(binding['execution_uid']) is int and binding['execution_uid'] == os.geteuid(), 'invalid_uid')
    root = private_path(binding['output_root'])
    check(root.parts[-3:] == ('runtime', 'next_version', 'F02'), 'invalid_output_root')
    stage = root.parents[2]
    for key in ('script_path', 'control_root'):
        check(stage in private_path(binding[key]).parents, 'path_outside_stage')
    private_path(binding['marker_path'])
    control = private_path(binding['control_root'])
    check(control.is_dir() and stat.S_IMODE(control.stat().st_mode) == 0o700
          and control.stat().st_uid == os.geteuid(), 'invalid_control')
    check(sha(Path(__file__).read_bytes()) == binding['probe_sha256'], 'probe_binding_mismatch')

def inspect(binding):
    validate(binding)
    script_sha = sha(read(binding['script_path'], 1024 * 1024))
    marker = read(binding['marker_path'], 128, 0o644).decode().strip()
    check(script_sha == binding['script_sha256'] and marker == binding['release_sha'], 'source_drift')
    directory = private_path(Path(binding['output_root']) / binding['observation_id'])
    if not directory.exists():
        state, manifest_sha = 'capture_unknown', binding['manifest_sha256']
    else:
        check(stat.S_IMODE(directory.stat().st_mode) == 0o700 and directory.stat().st_uid == os.geteuid(), 'invalid_directory')
        data = read(directory / 'manifest.json')
        manifest = json.loads(data)
        check(manifest.get('complete') is True and manifest.get('observation_id') == binding['observation_id'], 'incomplete_manifest')
        manifest_sha = sha(data)
        check(manifest_sha == binding['manifest_sha256'], 'manifest_drift')
        state = 'complete'
    return {'state': state, 'release_sha': marker, 'exporter_script_sha256': script_sha,
            'manifest_sha256': manifest_sha, 'execution_uid': os.geteuid(), 'output_root': binding['output_root'],
            'observation_id': binding['observation_id'], 'owned_probe_stopped': True}

def proc_identity(pid):
    # Linux only; do not guess on unsupported hosts or after PID reuse.
    path = Path('/proc') / str(pid)
    try:
        values = (path / 'stat').read_text().rsplit(') ', 1)[1].split()
        return {'start_ticks': values[19], 'state': values[0], 'uid': path.stat().st_uid,
                'argv': (path / 'cmdline').read_bytes().split(b'\0')}
    except FileNotFoundError:
        return None
    except (OSError, ValueError, IndexError):
        raise ProbeError('process_identity_unknown') from None

def operation_status(binding, operation_id):
    check(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', operation_id), 'invalid_operation')
    record = json.loads(read(Path(binding['control_root']) / (operation_id + '.pid.json')))
    check(set(record) == {'pid', 'start_ticks', 'uid', 'probe_sha256', 'operation_id', 'binding_sha256'}, 'invalid_pid_record')
    check(record['operation_id'] == operation_id and record['probe_sha256'] == binding['probe_sha256']
          and record['binding_sha256'] == sha(encoded(binding)) and record['uid'] == binding['execution_uid']
          and type(record['pid']) is int and record['pid'] > 0, 'pid_record_mismatch')
    actual = proc_identity(record['pid'])
    if actual is None or actual['state'] == 'Z':
        return {'state': 'stopped', 'operation_id': operation_id}
    args = actual['argv']
    owned = (actual['start_ticks'] == record['start_ticks'] and actual['uid'] == record['uid']
             and str(Path(__file__)).encode() in args and b'--operation-id' in args
             and args[args.index(b'--operation-id') + 1] == operation_id.encode())
    # A different running process with reused PID is unknown, never kill it.
    return {'state': 'running' if owned else 'unknown', 'operation_id': operation_id}

def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False) + '\n').encode()

def save_once(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding', required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--check-operation-id')
    args = parser.parse_args(argv)
    def expire(signum, frame):
        raise ProbeError('probe_timeout_or_cancelled')
    old_alarm = signal.signal(signal.SIGALRM, expire)
    old_term = signal.signal(signal.SIGTERM, expire)
    started = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, 10)
    binding = None
    registered = False
    try:
        binding = json.loads(read(args.binding))
        validate(binding)
        check(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.operation_id), 'invalid_operation')
        check(Path('/proc/self/stat').exists(), 'linux_process_identity_required')
        control = private_path(binding['control_root'])
        check(control.is_dir() and stat.S_IMODE(control.stat().st_mode) == 0o700 and control.stat().st_uid == os.geteuid(), 'invalid_control')
        identity = proc_identity(os.getpid())
        save_once(control / (args.operation_id + '.pid.json'), {
            'pid': os.getpid(), 'start_ticks': identity['start_ticks'], 'uid': os.geteuid(),
            'probe_sha256': binding['probe_sha256'], 'operation_id': args.operation_id, 'binding_sha256': sha(encoded(binding))})
        registered = True
        signal.setitimer(signal.ITIMER_REAL, max(0.001, binding['timeout_seconds'] - (time.monotonic()-started)))
        result = operation_status(binding, args.check_operation_id) if args.check_operation_id else inspect(binding)
        # Exit marker precedes stdout; successful work is done before the process returns the receipt.
        save_once(control / (args.operation_id + '.exit.json'), {'operation_id': args.operation_id, 'state': 'stopped'})
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'state': 'unknown', 'code': 'probe_failed'}))
        return 2
    finally:
        if old_alarm is not None:
            signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, old_alarm)
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)

if __name__ == '__main__':
    raise SystemExit(main())
