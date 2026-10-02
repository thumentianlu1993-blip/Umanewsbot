"""F02 宿主产物验证与可注入转存；不调用 DB、Docker、SSH。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import signal
import threading
import stat
import tempfile
import time

from scripts import f02_readonly_export as export

METADATA_TOTAL_MAX = 128 * 1024 * 1024
CONTENT_MAX = 30 * 1024 * 1024
FILE_MAX = 64 * 1024 * 1024
CONTROL_MAX = 64 * 1024
HASH = re.compile(r'[0-9a-f]{64}\Z')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
METADATA_NAMES = {export.FILENAMES.get(k, k + '.jsonl') for k in (*export.LIMITS, 'aggregates')} | {'receipt.json'}
IDENTITY = ('container_id', 'image_id', 'release_sha', 'exporter_script_sha256', 'manifest_sha256')


class TransferError(ValueError):
    """固定错误码；调用者不得输出底层异常/正文。"""


def require(condition, code):
    if not condition:
        raise TransferError(code)


def parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, TypeError, UnicodeError):
        raise TransferError('invalid_json') from None


def check_path(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'invalid_path')
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink(), 'symlink_path')
    return path


def private_directory(path):
    path = check_path(path)
    try:
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid(), 'directory_not_private')
    except OSError:
        raise TransferError('directory_unavailable') from None
    return path


def read_file(path, maximum):
    path = check_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.geteuid(),
                    'file_not_private_regular')
            require(info.st_size <= maximum, 'file_byte_budget')
            data = stream.read(maximum + 1)
            require(len(data) <= maximum, 'file_byte_budget')
            return data
    except OSError:
        raise TransferError('file_unavailable') from None


def capsule_sha(capsule):
    return export.digest(export.encoded(capsule))


def _validate_capsule(c):
    require(isinstance(c, dict), 'invalid_capsule')
    required = {'schema_version', 'kind', 'observation_id', *IDENTITY, 'source_schema_sha256',
                'container_output_root', 'execution_uid', 'verifier_sha256', 'copy_timeout_seconds', 'verify_timeout_seconds'}
    expected = required | ({'selection'} if c.get('kind') == 'sealed_content' else set())
    require(set(c) == expected and c['schema_version'] == 1 and c['kind'] in ('metadata', 'sealed_content'), 'invalid_capsule')
    require(isinstance(c['observation_id'], str) and NAME.fullmatch(c['observation_id']), 'invalid_observation')
    for field in ('container_id', 'exporter_script_sha256', 'manifest_sha256', 'source_schema_sha256', 'verifier_sha256'):
        require(isinstance(c[field], str) and HASH.fullmatch(c[field]), 'invalid_capsule_hash')
    require(c['verifier_sha256'] == verifier_sha(), 'verifier_identity_mismatch')
    require(isinstance(c['image_id'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', c['image_id']), 'invalid_image')
    require(isinstance(c['release_sha'], str) and re.fullmatch(r'[0-9a-f]{40}', c['release_sha']), 'invalid_release')
    require(type(c['execution_uid']) is int and c['execution_uid'] >= 0, 'invalid_uid')
    for field in ('copy_timeout_seconds', 'verify_timeout_seconds'):
        require(type(c[field]) is int and 1 <= c[field] <= 60, 'invalid_timeout')
    root = Path(c['container_output_root'])
    require(root.is_absolute() and '..' not in root.parts, 'invalid_container_output_root')
    require(root.parts[-3:] == ('runtime', 'next_version', 'F02'), 'invalid_container_output_root')
    require(len(export.encoded(c)) <= CONTROL_MAX, 'capsule_byte_budget')
    if c['kind'] == 'sealed_content':
        selection = c['selection']
        try:
            export.validate_selection(selection)
        except (export.ExportError, KeyError, TypeError, ValueError):
            raise TransferError('invalid_selection') from None
        require(selection['release_sha'] == c['release_sha'] and selection['source_schema_sha256'] == c['source_schema_sha256'],
                'selection_identity_mismatch')


def validate_capsule(c):
    try:
        _validate_capsule(c)
    except TransferError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        raise TransferError('invalid_capsule') from None


def rows(data):
    result = [parse(line) for line in data.splitlines() if line]
    require(all(isinstance(row, dict) for row in result), 'invalid_rows')
    return result


def valid_count(count, limit):
    return type(count) is int and 0 <= count <= limit


def verify_metadata(saved, receipt, c):
    observation = receipt.get('observation', {})
    require(all(observation.get(key) == value for key, value in {
        'release_sha': c['release_sha'], 'script_sha256': c['exporter_script_sha256'],
        'schema_sha256': c['source_schema_sha256'], 'read_only': 'on', 'isolation': 'repeatable read'}.items()), 'metadata_identity')
    start, cutoff = (datetime.fromisoformat(observation[key]) for key in ('start', 'observed_at'))
    require(start.tzinfo is not None and cutoff.tzinfo is not None and cutoff - start == timedelta(days=28), 'metadata_window')
    datasets = {}
    for key, limit in export.LIMITS.items():
        values = rows(saved[export.FILENAMES.get(key, key + '.jsonl')])
        count = receipt['counts'].get(key)
        ids = [row.get('id') for row in values]
        require(valid_count(count, limit) and count == len(values) and len(set(ids)) == count
                and all(type(i) is int and i > 0 for i in ids), 'metadata_count')
        datasets[key] = values
    regions = {region: 0 for region in export.REGIONS}
    for row in datasets['cohort']:
        first = datetime.fromisoformat(row['first_seen_at'])
        require(row['racing_region'] in regions and first.tzinfo is not None and start <= first < cutoff
                and isinstance(row['input_sha256'], str) and HASH.fullmatch(row['input_sha256']), 'metadata_cohort')
        regions[row['racing_region']] += 1
    require(regions == receipt.get('region_counts'), 'metadata_region_count')
    aggregates = rows(saved['funnel_aggregates.jsonl'])
    require(all(valid_count(row.get('article_count'), export.LIMITS['cohort']) for row in aggregates)
            and sum(row['article_count'] for row in aggregates) == len(datasets['cohort']), 'metadata_aggregate_count')


def verify_content(saved, receipt, c, source_metadata_dir):
    selection = c['selection']
    require(receipt.get('custodian') == 'R' and receipt.get('release_sha') == c['release_sha'], 'content_identity')
    for field in ('source_observation_id', 'source_metadata_manifest_sha256', 'source_schema_sha256'):
        require(receipt.get(field) == selection[field], 'content_source_mismatch')
    require(receipt.get('selection_sha256') == export.digest(export.encoded(selection)), 'selection_sha_mismatch')
    require(source_metadata_dir is not None, 'missing_source_metadata')
    # The already reviewed exporter checks full source package and selected IDs/hash/updated_at.
    try:
        export.verify_source_metadata(selection, source_metadata_dir)
    except (export.ExportError, KeyError, TypeError, ValueError, OSError):
        raise TransferError('source_metadata_invalid') from None
    source_receipt = parse(read_file(Path(source_metadata_dir) / 'receipt.json', CONTROL_MAX))
    source_c = dict(c, kind='metadata', observation_id=selection['source_observation_id'],
                    manifest_sha256=selection['source_metadata_manifest_sha256'])
    del source_c['selection']
    # Independently enforce every source dataset/count/private directory, not only cohort.
    verify_bundle(source_metadata_dir, source_c)
    require(source_receipt['observation']['script_sha256'] == c['exporter_script_sha256'], 'source_script_mismatch')
    values = rows(saved['content.jsonl'])
    count = receipt.get('counts', {}).get('articles')
    require(valid_count(count, 150) and count == len(values) == len(selection['samples']), 'content_count')
    expected = {sample['id']: sample for sample in selection['samples']}
    require(len({row.get('id') for row in values}) == count, 'content_duplicate')
    for row in values:
        reference = expected.get(row.get('id'))
        require(reference is not None and all(row.get(key) == reference[key] for key in ('input_sha256', 'updated_at')), 'content_input')
        digest_row = dict(row)
        digest_row.pop('redacted_content_sha256', None)
        require(row.get('redacted_content_sha256') == export.digest(export.encoded(digest_row)), 'redacted_hash')
        require(isinstance(row.get('raw_content_sha256'), str) and HASH.fullmatch(row['raw_content_sha256']), 'raw_content_hash')
        require(row.get('human_verification_status') == 'not_reviewed' and row.get('machine_validation_status') == 'not_run'
                and row.get('model_annotation_status') == 'none', 'annotation_status_changed')
    require(valid_count(receipt.get('input_bytes'), CONTENT_MAX), 'content_input_budget')


def _verify_bundle(directory, capsule, source_metadata_dir=None):
    """只返回计数与承诺；不返回/打印任何行数据。"""
    try:
        validate_capsule(capsule)
        directory = private_directory(directory)
        require(directory.name == capsule['observation_id'], 'observation_path_mismatch')
        manifest_bytes = read_file(directory / 'manifest.json', min(CONTROL_MAX, FILE_MAX))
        require(export.digest(manifest_bytes) == capsule['manifest_sha256'], 'manifest_sha_mismatch')
        manifest = parse(manifest_bytes)
        expected_names = METADATA_NAMES if capsule['kind'] == 'metadata' else {'content.jsonl', 'receipt.json'}
        require(manifest.get('schema_version') == 1 and manifest.get('complete') is True
                and manifest.get('kind') == capsule['kind'] and manifest.get('observation_id') == capsule['observation_id']
                and set(manifest.get('files', {})) == expected_names, 'invalid_manifest')
        require({p.name for p in directory.iterdir()} == expected_names | {'manifest.json'}, 'extra_or_missing_file')
        total = len(manifest_bytes)
        saved = {}
        for name in sorted(expected_names):
            maximum = CONTROL_MAX if name == 'receipt.json' else (16 * 1024 * 1024 if name == 'cohort_metadata.jsonl' else FILE_MAX)
            if name == 'content.jsonl':
                maximum = CONTENT_MAX
            data = read_file(directory / name, min(maximum, FILE_MAX))
            total += len(data)
            budget = METADATA_TOTAL_MAX if capsule['kind'] == 'metadata' else CONTENT_MAX + 2 * CONTROL_MAX
            require(total <= budget, 'total_byte_budget')
            require(export.digest(data) == manifest['files'][name], 'file_sha_mismatch')
            saved[name] = data
        receipt = parse(saved['receipt.json'])
        require(receipt.get('complete') is True and receipt.get('kind') == capsule['kind']
                and receipt.get('observation_id') == capsule['observation_id']
                and receipt.get('human_verification_status') == 'not_reviewed', 'invalid_receipt')
        if capsule['kind'] == 'metadata':
            verify_metadata(saved, receipt, capsule)
        else:
            verify_content(saved, receipt, capsule, source_metadata_dir)
        return {'kind': capsule['kind'], 'observation_id': capsule['observation_id'], 'counts': receipt['counts'],
                'manifest_sha256': capsule['manifest_sha256'], 'bytes': total, 'human_verification_status': 'not_reviewed'}
    except TransferError:
        raise
    except (ValueError, TypeError, KeyError, OSError, AttributeError, OverflowError):
        raise TransferError('invalid_package') from None




_VERIFICATION_DEPTH = 0


@contextmanager
def verification_deadline(seconds):
    """Main-thread wall clock deadline; nested source verification shares the outer budget."""
    global _VERIFICATION_DEPTH
    require(threading.current_thread() is threading.main_thread(), 'verification_requires_main_thread')
    if _VERIFICATION_DEPTH:
        yield
        return
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), 'verification_timer_busy')
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise TransferError('verify_timeout')
    signal.signal(signal.SIGALRM, expired)
    _VERIFICATION_DEPTH += 1
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        _VERIFICATION_DEPTH -= 1
        signal.signal(signal.SIGALRM, previous)


def verify_bundle(directory, capsule, source_metadata_dir=None):
    validate_capsule(capsule)
    with verification_deadline(capsule['verify_timeout_seconds']):
        return _verify_bundle(directory, capsule, source_metadata_dir)


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir_private(path):
    path = check_path(path)
    if not path.exists():
        # Create only missing ancestors; do not chmod someone else's existing dirs.
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for item in reversed(missing):
            item.mkdir(mode=0o700)
            fsync_directory(item.parent)
    return private_directory(path)


def atomic_json(path, value):
    path = check_path(path)
    private_directory(path.parent)
    require(not path.is_symlink(), 'symlink_control')
    if path.exists():
        read_file(path, CONTROL_MAX)
    data = export.encoded(value)
    require(len(data) <= CONTROL_MAX, 'control_byte_budget')
    fd, temporary = tempfile.mkstemp(prefix='.control-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def artifact_lock(root):
    """OS advisory lock自动释放；文件存在不代表锁仍活跃。"""
    root = private_directory(root)
    fd = os.open(root / '.transfer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, 'invalid_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TransferError('busy') from None
        owner = {'owner_uid': os.geteuid(), 'pid': os.getpid(), 'thread': 'B-003',
                 'operation': 'F02_artifact_transfer', 'sha': verifier_sha(),
                 'resource_root': str(root), 'started_at': datetime.now().astimezone().isoformat(),
                 'liveness': 'OS flock released on process exit'}
        os.ftruncate(fd, 0)
        os.write(fd, export.encoded(owner))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)


def outcome(c, state, code=None, **values):
    observation = c.get('observation_id') if isinstance(c, dict) else None
    if not isinstance(observation, str) or not NAME.fullmatch(observation):
        observation = None
    try:
        digest = capsule_sha(c)
    except Exception:
        digest = None
    result = {'state': state, 'capsule_sha256': digest, 'observation_id': observation,
              'delivered_to_R': False, **values}
    if code:
        result['code'] = code
    return result


def source_matches(probe, c):
    require(isinstance(probe, dict) and probe.get('state') == 'complete', 'source_not_complete')
    require(all(probe.get(key) == c[key] for key in IDENTITY)
            and probe.get('execution_uid') == c['execution_uid'], 'source_identity_drift')


def commitment(c, attempt):
    return {'schema_version': 1, 'capsule_sha256': capsule_sha(c), 'attempt_id': attempt,
            'observation_id': c['observation_id'], **{key: c[key] for key in IDENTITY},
            'execution_uid': c['execution_uid']}


def verify_commitment(path, c, attempt):
    require(parse(read_file(path, CONTROL_MAX)) == commitment(c, attempt), 'commitment_mismatch')


def verifier_sha():
    return export.digest(Path(__file__).read_bytes())


def finish(c, home, attempt, final, summary, writer):
    receipt = {'schema_version': 1, 'state': 'host_verified', 'capsule_sha256': capsule_sha(c),
               'attempt_id': attempt, 'observation_id': c['observation_id'],
               **{key: c[key] for key in IDENTITY}, 'host_manifest_sha256': summary['manifest_sha256'],
               'artifact_path': str(final), 'verifier_sha256': verifier_sha(),
               'verification_method': 'f02_transfer.verify_bundle', 'counts': summary['counts'], 'bytes': summary['bytes'],
               'verified_at': datetime.now().astimezone().isoformat(), 'delivered_to_R': False}
    complete = home / 'transfer.complete'
    if complete.exists():
        old = parse(read_file(complete, CONTROL_MAX))
        # Do not accept a control file as proof without independently verifying final first.
        for key in ('schema_version', 'state', 'capsule_sha256', 'observation_id', *IDENTITY,
                    'host_manifest_sha256', 'artifact_path', 'counts', 'bytes', 'delivered_to_R'):
            require(old.get(key) == receipt[key], 'transfer_receipt_conflict')
    else:
        writer(complete, receipt)
    return outcome(c, 'host_verified', manifest_sha256=c['manifest_sha256'], artifact_path=str(final), counts=summary['counts'])


def _transfer(c, root, adapter, attempt_id, disk_free, clock, writer, source_metadata_dir):
    home = mkdir_private(root / capsule_sha(c))
    binding = home / 'capsule.json'
    if binding.exists():
        require(parse(read_file(binding, CONTROL_MAX)) == c, 'capsule_conflict')
    else:
        writer(binding, c)
    final_root = mkdir_private(home / 'runtime/next_version/F02')
    final = final_root / c['observation_id']
    attempts = mkdir_private(home / 'attempts')
    if final.exists() or final.is_symlink():
        # A final without receipt is only recoverable with persisted source commitment.
        valid_attempts = []
        for path in attempts.iterdir():
            private_directory(path)
            require(NAME.fullmatch(path.name), 'invalid_existing_attempt')
            if (path / 'invalid.json').exists():
                continue
            if (path / 'source.commit.json').exists():
                verify_commitment(path / 'source.commit.json', c, path.name)
                valid_attempts.append(path.name)
        require(len(valid_attempts) == 1, 'final_without_source_commitment')
        started = clock()
        summary = verify_bundle(final, c, source_metadata_dir)
        require(clock() - started <= c['verify_timeout_seconds'], 'verify_timeout')
        return finish(c, home, valid_attempts[0], final, summary, writer)
    existing = list(attempts.iterdir())
    require(len(existing) <= 3, 'attempt_budget')
    # Unknown or invalid attempts cannot be bypassed by using another attempt name.
    if existing:
        require(len(existing) == 1, 'multiple_unresolved_attempts')
        attempt = private_directory(existing[0])
    else:
        attempt = mkdir_private(attempts / attempt_id)
    active_id = attempt.name
    require(NAME.fullmatch(active_id), 'invalid_existing_attempt')
    if (attempt / 'invalid.json').exists():
        read_file(attempt / 'invalid.json', CONTROL_MAX)
        return outcome(c, 'invalid_package', 'prior_attempt_invalid')
    stage_root = mkdir_private(attempt / 'runtime/next_version/F02')
    stage = stage_root / c['observation_id']
    committed = (attempt / 'source.commit.json').exists()
    if committed:
        verify_commitment(attempt / 'source.commit.json', c, active_id)
    started = clock()
    probe = adapter.probe(timeout=c['copy_timeout_seconds'])
    require(clock() - started <= c['copy_timeout_seconds'], 'probe_timeout')
    lost = isinstance(probe, dict) and probe.get('state') == 'source_lost'
    if not lost:
        source_matches(probe, c)
    if stage.exists() or stage.is_symlink():
        if not committed:
            return outcome(c, 'transfer_unknown', 'stage_without_commitment')
        started = clock()
        try:
            summary = verify_bundle(stage, c, source_metadata_dir)
        except TransferError:
            return outcome(c, 'source_lost' if lost else 'transfer_unknown', 'stage_not_complete')
        require(clock() - started <= c['verify_timeout_seconds'], 'verify_timeout')
        # Full independently verified stage + persisted pre-copy identity is sufficient even if source disappeared.
    else:
        if lost:
            return outcome(c, 'source_lost', 'no_verified_host_package')
        # If commitment exists but no stage, prior copy outcome is still unknown. Never recopy automatically.
        if committed:
            return outcome(c, 'transfer_unknown', 'committed_copy_outcome_unknown')
        budget = METADATA_TOTAL_MAX if c['kind'] == 'metadata' else CONTENT_MAX + 2 * CONTROL_MAX
        if disk_free(home) < budget * 2 + 4 * CONTROL_MAX:
            # No copy started; retain the attempt for a later explicit inspection/resume.
            return outcome(c, 'produced_not_transferred', 'insufficient_space')
        writer(attempt / 'source.commit.json', commitment(c, active_id))
        mkdir_private(stage)
        started = clock()
        # Adapter must enforce its timeout itself and return only after owned copy process has stopped.
        # Exceptions leave stage+commitment intact; caller must inspect, never blind retry.
        adapter.copy(stage, timeout=c['copy_timeout_seconds'])
        require(clock() - started <= c['copy_timeout_seconds'], 'copy_timeout')
        started = clock()
        post = adapter.probe(timeout=c['copy_timeout_seconds'])
        require(clock() - started <= c['copy_timeout_seconds'], 'probe_timeout')
        if not (isinstance(post, dict) and post.get('state') == 'source_lost'):
            try:
                source_matches(post, c)
            except TransferError:
                writer(attempt / 'invalid.json', {'code': 'source_identity_drift', 'capsule_sha256': capsule_sha(c)})
                raise
        started = clock()
        try:
            summary = verify_bundle(stage, c, source_metadata_dir)
        except TransferError:
            writer(attempt / 'invalid.json', {'code': 'copied_package_invalid', 'capsule_sha256': capsule_sha(c)})
            raise
        require(clock() - started <= c['verify_timeout_seconds'], 'verify_timeout')
    # Source commitment and bundle are intact. Rename is same filesystem; no overwrite under the OS lock.
    require(not final.exists() and not final.is_symlink(), 'final_conflict')
    fsync_payload(stage)
    fsync_directory(stage)
    os.rename(stage, final)
    fsync_directory(stage_root)
    fsync_directory(final_root)
    return finish(c, home, active_id, final, summary, writer)


def transfer(capsule, artifact_root, adapter, attempt_id, *, disk_free=None, clock=time.monotonic,
             writer=atomic_json, source_metadata_dir=None):
    """编排本地host阶段；adapter仅来自外部已审调用者，不解析shell命令。

    probe(timeout=seconds) returns identity/state; copy(private_destination, timeout=seconds)
    must not emit content and must reap owned processes on timeout. No automatic copy retries.
    """
    try:
        validate_capsule(capsule)
        require(isinstance(attempt_id, str) and NAME.fullmatch(attempt_id), 'invalid_attempt')
        root = mkdir_private(artifact_root)
        with artifact_lock(root):
            return _transfer(capsule, root, adapter, attempt_id,
                             disk_free or (lambda p: shutil.disk_usage(p).free), clock, writer, source_metadata_dir)
    except TransferError as error:
        code = str(error)
        unknown = {'busy', 'copy_timeout', 'probe_timeout', 'verify_timeout', 'file_unavailable', 'directory_unavailable', 'source_not_complete'}
        state = 'capture_unknown' if code == 'source_not_complete' else ('transfer_unknown' if code in unknown else 'invalid_package')
        return outcome(capsule, state, code)
    except Exception:
        # Unknown mutations/transport outcomes are never retried here; no raw exception text.
        return outcome(capsule, 'transfer_unknown', 'operation_outcome_unknown')



def fsync_payload(directory):
    for path in directory.iterdir():
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'invalid_payload_fsync')
            os.fsync(fd)
        finally:
            os.close(fd)


def inspect_host(capsule, artifact_root, source_metadata_dir=None):
    """纯只读验收：host receipt、source commitment与当前final必须同时匹配。"""
    validate_capsule(capsule)
    root = private_directory(artifact_root)
    home = private_directory(root / capsule_sha(capsule))
    require(parse(read_file(home / 'capsule.json', CONTROL_MAX)) == capsule, 'capsule_conflict')
    receipt = parse(read_file(home / 'transfer.complete', CONTROL_MAX))
    attempt = receipt.get('attempt_id')
    require(isinstance(attempt, str) and NAME.fullmatch(attempt), 'invalid_receipt_attempt')
    attempt_path = private_directory(home / 'attempts' / attempt)
    require(not (attempt_path / 'invalid.json').exists(), 'prior_attempt_invalid')
    verify_commitment(attempt_path / 'source.commit.json', capsule, attempt)
    final = home / 'runtime/next_version/F02' / capsule['observation_id']
    started = time.monotonic()
    summary = verify_bundle(final, capsule, source_metadata_dir)
    require(time.monotonic() - started <= capsule['verify_timeout_seconds'], 'verify_timeout')
    expected = {'schema_version': 1, 'state': 'host_verified', 'capsule_sha256': capsule_sha(capsule),
                'observation_id': capsule['observation_id'], **{key: capsule[key] for key in IDENTITY},
                'host_manifest_sha256': summary['manifest_sha256'], 'artifact_path': str(final),
                'counts': summary['counts'], 'bytes': summary['bytes'], 'delivered_to_R': False}
    require(all(receipt.get(key) == value for key, value in expected.items()), 'transfer_receipt_conflict')
    require(isinstance(receipt.get('verifier_sha256'), str) and HASH.fullmatch(receipt['verifier_sha256']), 'missing_verifier_identity')
    return outcome(capsule, 'host_verified', manifest_sha256=summary['manifest_sha256'], counts=summary['counts'])


def record_delivery(capsule, artifact_root, acknowledgement, *, r_key=None, source_metadata_dir=None):
    """只接受独立R认证回执。R密钥由可信custodian调用面提供，不来自producer/capsule。

    此函数不建立R身份/发密钥；生产接入须另行绑定已有可信custodian。缺少认证材料默认拒绝。
    """
    validate_capsule(capsule)
    require(isinstance(r_key, bytes) and 32 <= len(r_key) <= 256, 'R_authentication_required')
    ack = acknowledgement
    expected_names = {'schema_version', 'issuer', 'capsule_sha256', 'manifest_sha256', 'observation_id', 'received_at', 'signature'}
    require(isinstance(ack, dict) and set(ack) == expected_names, 'invalid_R_ack')
    require(ack['schema_version'] == 1 and ack['issuer'] == 'R'
            and ack['capsule_sha256'] == capsule_sha(capsule) and ack['manifest_sha256'] == capsule['manifest_sha256']
            and ack['observation_id'] == capsule['observation_id'], 'R_ack_identity_mismatch')
    try:
        require(datetime.fromisoformat(ack['received_at']).tzinfo is not None, 'invalid_R_ack_time')
    except (ValueError, TypeError):
        raise TransferError('invalid_R_ack_time') from None
    unsigned = dict(ack)
    unsigned.pop('signature')
    signature = hmac.new(r_key, export.encoded(unsigned), hashlib.sha256).hexdigest()
    require(isinstance(ack['signature'], str) and hmac.compare_digest(signature, ack['signature']), 'R_ack_authentication_failed')
    root = private_directory(artifact_root)
    with artifact_lock(root):
        inspect_host(capsule, root, source_metadata_dir)
        home = root / capsule_sha(capsule)
        path = home / 'R.received'
        receipt = {'schema_version': 1, 'state': 'delivered_to_R', 'issuer': 'R',
                   'capsule_sha256': capsule_sha(capsule), 'manifest_sha256': capsule['manifest_sha256'],
                   'observation_id': capsule['observation_id'], 'received_at': ack['received_at'],
                   'authenticated_ack_sha256': export.digest(export.encoded(ack)), 'delivered_to_R': True}
        if path.exists():
            require(parse(read_file(path, CONTROL_MAX)) == receipt, 'R_ack_conflict')
        else:
            atomic_json(path, receipt)
        return receipt


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        raise TransferError('invalid_arguments')


def main(argv=None):
    parser = QuietParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=QuietParser)
    verify = commands.add_parser('verify')
    verify.add_argument('--capsule', required=True)
    verify.add_argument('--bundle', required=True)
    verify.add_argument('--source-metadata-dir')
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--capsule', required=True)
    inspect.add_argument('--artifact-root', required=True)
    inspect.add_argument('--source-metadata-dir')
    # CLI has no transport or R-key provisioning command. R acknowledgement is a trusted API invocation.
    try:
        args = parser.parse_args(argv)
        capsule = parse(read_file(Path(args.capsule), CONTROL_MAX))
        validate_capsule(capsule)
        if args.command == 'verify':
            result = verify_bundle(Path(args.bundle), capsule, args.source_metadata_dir)
        else:
            result = inspect_host(capsule, args.artifact_root, args.source_metadata_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except TransferError as error:
        print(json.dumps({'state': 'invalid_package', 'code': str(error)}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({'state': 'invalid_package', 'code': 'operation_failed'}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
