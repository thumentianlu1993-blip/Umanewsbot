"""采集失败语义、重试与有界私有原件；不授予取数或发布权限。"""
from contextvars import ContextVar
from datetime import timedelta
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from django.conf import settings

_CAPTURE = ContextVar('race_failure_capture', default=None)
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
MAX_DOCUMENTS = 12
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVES = 128
RETENTION_SECONDS = 7 * 86400


def safe_code(reason):
    return reason if isinstance(reason, str) and re.fullmatch(r'[a-z0-9_-]{1,64}', reason) else 'source_parse_failed'


def category(reason):
    reason = safe_code(reason)
    # Only explicit availability states qualify as waiting. Unknown errors remain faults.
    if reason in {'not_published', 'not_found', 'jra_not_published', 'jra_race_url_not_found',
                  'racecard_not_found', 'course_not_found', 'race_name_not_found', 'region_not_found', 'local_date_not_found', 'response_empty', 'uk_result_not_published', 'geny_result_not_final', 'result_not_final', 'awaiting_source_window', 'uk_awaiting_final_card', 'us_card_not_final'}:
        return 'not_published'
    if reason in {'result_incomplete', 'roster_incomplete', 'partial_result', 'jra_result_incomplete', 'reference_result_incomplete', 'hkjc_nomination_roster_incomplete', 'jra_registration_roster_incomplete', 'uk_roster_incomplete', 'us_result_incomplete'}:
        return 'incomplete'
    if reason in {'snapshot_lease_busy', 'snapshot_lease_rejected', 'lease_active', 'lease_stale',
                  'jra_host_rate_limited', 'rate_limited', 'host_rate_limited',
                  'artifact_daily_requests_exceeded', 'artifact_daily_bytes_exceeded',
                  'transport_capacity_exceeded', 'budget_deferred', 'host_reservation_rate_limited', 'host_reservation_circuit_open', 'jra_host_circuit_open', 'manual_or_owner_lock', 'handed_off', 'older_source', 'older_or_incomplete_source', 'pre_race_write_guard_stale', 'formal_claim_active', 'coverage_unverified'}:
        return 'waiting'
    if re.search(r'(?:^|_)http_(?:401|403|406)$', reason) or reason in {'access_denied', 'france_login_required'}:
        return 'access'
    if re.search(r'(?:^|_)http_(?:429|5\d\d)$', reason) or reason in {
        'transport_failed', 'jra_transport_failed', 'timeout', 'snapshot_fetch_failed',
        'browser_transport_failed', 'us_browser_transport_failed', 'france_browser_transport_failed'}:
        return 'network'
    if any(part in reason for part in ('identity', 'ambiguous', 'source_id_changed', 'source_number_changed')):
        return 'identity'
    if any(part in reason for part in ('disabled', 'policy', 'permission', 'route_rejected', 'contract', 'artifact_root')):
        return 'configuration'
    return 'parser'


def is_fault(reason):
    return category(reason) not in {'not_published', 'incomplete', 'waiting'}


def delay(reason, *, attempts=1, repeated=False):
    kind = category(reason)
    exponent = min(max(int(attempts) - 1, 0), 6)
    minutes = {'not_published': 1, 'incomplete': 2, 'waiting': 1,
               'network': min(60, 5 * 2**exponent), 'access': 60,
               'identity': 60, 'configuration': 60,
               'parser': min(180, 15 * 2**exponent)}[kind]
    if repeated and kind in {'parser', 'identity'}:
        minutes = max(minutes, 60)
    return timedelta(minutes=minutes)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def attempt_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _CAPTURE.set({'documents': {}, 'bytes': 0, 'omitted': 0, 'location': []})
        try:
            return function(*args, **kwargs)
        finally:
            _CAPTURE.reset(token)
    return wrapped


def reset_capture():
    if _CAPTURE.get() is not None:
        _CAPTURE.set({'documents': {}, 'bytes': 0, 'omitted': 0, 'location': []})


def capture_document(payload, *, request_key, provider='', region='', registry_digest=''):
    capture = _CAPTURE.get()
    if capture is None:
        return
    if not isinstance(payload, dict):
        capture['omitted'] += 1
        return
    # No URLs, authentication headers, cookies, exception messages or request bodies.
    # These are the same response envelopes accepted by the private snapshot store.
    document = {key: payload[key] for key in ('html', 'bytes_b64', 'response', 'raw_sha256') if key in payload}
    if not document and any(key in payload for key in ('racecards', 'results')):
        document = {'response': payload}
    if not document:
        capture['omitted'] += 1
        return
    try:
        encoded = _encoded(document)
    except (ValueError, TypeError):
        capture['omitted'] += 1
        return
    digest = hashlib.sha256(encoded).hexdigest()
    key = (str(request_key).split(':', 1)[1] if re.fullmatch(r'(?:bytes|html):[0-9a-f]{64}', str(request_key))
           else hashlib.sha256(str(request_key).encode()).hexdigest())
    identity = key + ':' + digest
    if identity in capture['documents']:
        return
    if len(capture['documents']) >= MAX_DOCUMENTS or capture['bytes'] + len(encoded) > MAX_CAPTURE_BYTES:
        capture['omitted'] += 1
        return
    # Freeze immediately: parsers may mutate the dictionaries they consume.
    capture['documents'][identity] = dict(request_sha256=key, content_sha256=digest,
        provider=safe_code(provider), region=safe_code(region), registry_digest=registry_digest if isinstance(registry_digest, str) and re.fullmatch('[0-9a-f]{64}', registry_digest) else '',
        payload=json.loads(encoded))
    capture['bytes'] += len(encoded)


def observe_response(value, *, url, route=None, provider='', region=''):
    """进程内缓存命中也须记录本次真正交给解析器的内容。"""
    if isinstance(value, bytes):
        import base64
        payload = {'bytes_b64': base64.b64encode(value).decode('ascii')}
    elif isinstance(value, str):
        payload = {'html': str(value)}
        if getattr(value, 'raw_sha256', None):
            payload['raw_sha256'] = value.raw_sha256
    elif isinstance(value, dict):
        payload = {'response': value}
    else:
        return value
    capture_document(payload, request_key=url,
                     provider=route.provider if route else provider,
                     region=route.region if route else region,
                     registry_digest=route.digest if route else hashlib.sha256((provider+url).encode()).hexdigest())
    return value


def observe_fetch(function):
    @wraps(function)
    def wrapped(url, **kwargs):
        value = function(url, **kwargs)
        return observe_response(value, url=url, route=kwargs.get('route'), region=kwargs.get('region', ''))
    return wrapped


class ResponseCache(dict):
    def __init__(self, *, provider, region):
        super().__init__()
        self.provider, self.region = provider, region

    def __getitem__(self, key):
        return observe_response(super().__getitem__(key), url=key, provider=self.provider, region=self.region)


def capture_exception(exc):
    capture = _CAPTURE.get()
    if capture is None:
        return
    locations = []
    tb = exc.__traceback__
    while tb is not None:
        path = Path(tb.tb_frame.f_code.co_filename)
        if path.parent.name == 'services' and path.parent.parent.name == 'stable':
            locations.append(dict(module=path.name, function=tb.tb_frame.f_code.co_name, line=tb.tb_lineno))
        tb = tb.tb_next
    capture['location'] = locations[-8:]


def capture_snapshot(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        result = function(*args, **kwargs)
        capture_document(result[0], request_key=kwargs['scope_key'], provider=kwargs['provider'],
                         region=kwargs['region'], registry_digest=kwargs['registry_digest'])
        return result
    return wrapped


def evidence_payload():
    capture = _CAPTURE.get() or {'documents': {}, 'omitted': 0, 'location': []}
    return dict(schema_version=1, documents=[capture['documents'][key] for key in sorted(capture['documents'])],
                omitted_documents=capture['omitted'], location=capture.get('location', []))


def retain_evidence(payload, *, now):
    """原件独立于可替换快照。锁内去重/淘汰；失败仅留下不可用状态，不掩盖采集失败。"""
    if not payload['documents']:
        return {'status': 'capture_limit' if payload['omitted_documents'] else 'no_captured_response', 'sha256': '',
                'omitted_documents': payload['omitted_documents'], 'location': payload.get('location', [])}
    encoded = _encoded(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    content_digest = hashlib.sha256(_encoded(payload['documents'])).hexdigest()
    result = dict(sha256=digest, content_sha256=content_digest, bytes=len(encoded), omitted_documents=payload['omitted_documents'], location=payload.get('location', []))
    if len(encoded) > MAX_CAPTURE_BYTES + 16384:
        return dict(result, status='capture_limit')
    if len(encoded) > MAX_ARCHIVE_BYTES:
        return dict(result, status='capacity_limit')
    roots = getattr(settings, 'RACE_DATA_RAW_ARTIFACT_ROOTS', ())
    if not roots:
        return dict(result, status='root_unavailable')
    directory = lock = None
    try:
        root = Path(roots[0])
        if root.is_symlink():
            raise OSError('unsafe root')
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.mkdir('failures', mode=0o700, dir_fd=directory)
        except FileExistsError:
            pass
        child = os.open('failures', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        os.close(directory)
        directory = child
        if stat.S_IMODE(os.fstat(directory).st_mode) & 0o077:
            raise OSError('unsafe permissions')
        lock = os.open('.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(lock).st_mode):
            raise OSError('unsafe lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        entries = []
        for name in os.listdir(directory):
            if not re.fullmatch(r'[0-9a-f]{64}\.json', name):
                continue
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise OSError('unsafe evidence')
            if info.st_mtime < now.timestamp() - RETENTION_SECONDS:
                os.unlink(name, dir_fd=directory)
            else:
                entries.append((info.st_mtime, name, info.st_size))
        name = digest + '.json'
        if any(item[1] == name for item in entries):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, 'rb') as handle:
                if handle.read(len(encoded) + 1) != encoded:
                    raise OSError('digest mismatch')
            return dict(result, status='retained')
        minimum_free = max(0, int(getattr(settings, 'RACE_DATA_RAW_MIN_FREE_DISK_BYTES', 0)))
        free = os.fstatvfs(directory)
        if free.f_bavail * free.f_frsize < minimum_free + len(encoded):
            return dict(result, status='disk_low')
        size = sum(item[2] for item in entries)
        entries.sort()
        while entries and (len(entries) >= MAX_ARCHIVES or size + len(encoded) > MAX_ARCHIVE_BYTES):
            _, old, count = entries.pop(0)
            os.unlink(old, dir_fd=directory)
            size -= count
        # One pending file under flock; a killed writer is safely replaced on the next attempt.
        pending = '.pending'
        try:
            old_pending = os.stat(pending, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(old_pending.st_mode):
                raise OSError('unsafe pending file')
            os.unlink(pending, dir_fd=directory)
        except FileNotFoundError:
            pass
        fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.utime(pending, (now.timestamp(), now.timestamp()), dir_fd=directory, follow_symlinks=False)
            os.rename(pending, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        except OSError:
            try:
                os.unlink(pending, dir_fd=directory)
            except FileNotFoundError:
                pass
            raise
        return dict(result, status='retained')
    except OSError:
        return dict(result, status='storage_unavailable')
    finally:
        if lock is not None:
            os.close(lock)
        if directory is not None:
            os.close(directory)


def failure_state(previous, *, reason, now, parser_version='', evidence=None):
    reason = safe_code(reason)
    previous = previous if isinstance(previous, dict) else {}
    evidence = evidence if evidence is not None else retain_evidence(evidence_payload(), now=now)
    fingerprint = hashlib.sha256(_encoded([reason, parser_version, evidence.get('content_sha256', evidence.get('sha256', ''))])).hexdigest()
    same = previous.get('fingerprint') == fingerprint and not previous.get('resolved_at')
    count = min(int(previous.get('attempts', 0)) + 1, 1000000) if same else 1
    category_attempts = min(int(previous.get('category_attempts', 0)) + 1, 1000000) if previous.get('category') == category(reason) and not previous.get('resolved_at') else 1
    return dict(category=category(reason), category_attempts=category_attempts, reason=reason, fault=is_fault(reason), fingerprint=fingerprint,
                attempts=count, repeated_content=bool(same and evidence.get('sha256')),
                first_seen=previous.get('first_seen', now.isoformat()) if same else now.isoformat(),
                last_seen=now.isoformat(), parser_version=parser_version[:128], evidence=evidence,
                needs_attention=category(reason) in {'identity', 'configuration', 'access'} or
                    (category(reason) == 'parser' and count >= 3))


def inspect_evidence(digest):
    """只读核验引用；不会输出原件，也不会把曾经留存当作现在仍存在。"""
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        return 'not_recorded'
    roots = getattr(settings, 'RACE_DATA_RAW_ARTIFACT_ROOTS', ())
    if not roots:
        return 'root_unavailable'
    root_fd = directory = None
    try:
        root_fd = os.open(Path(roots[0]), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.open('failures', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        fd = os.open(digest+'.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                return 'unsafe'
            if info.st_size > MAX_CAPTURE_BYTES + 16384:
                return 'oversized'
            actual = hashlib.sha256()
            total = 0
            while chunk := handle.read(65536):
                total += len(chunk)
                if total > MAX_CAPTURE_BYTES + 16384:
                    return 'oversized'
                actual.update(chunk)
        return 'verified' if actual.hexdigest() == digest else 'digest_mismatch'
    except FileNotFoundError:
        return 'missing_or_evicted'
    except OSError:
        return 'unavailable'
    finally:
        if directory is not None:
            os.close(directory)
        if root_fd is not None:
            os.close(root_fd)
