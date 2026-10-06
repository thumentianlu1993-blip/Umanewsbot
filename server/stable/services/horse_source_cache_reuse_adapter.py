"""HKJC source-cache.v2 到 H02 的离线旁路，不读路径、不取数、不认证任意JSON。

expected_sha256/ref/source_ref必须来自调用方明确限定的可信输入；自身算hash不替代
来源认证。原件内容和source.fetched_at保留；profile身份仍由H01决定。
"""
import hashlib
import json
import re
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit

from .horse_target_inventory import _key, _time

MAX_CACHE_BYTES = 128 * 1024
HKJC_HOST = 'racing.hkjc.com'
HKJC_PATH = '/racing/information/English/Horse/Horse.aspx'
LEGACY_SENTINEL = '__legacy_existing_cache_validation_only__'


class CacheReuseAdapterError(ValueError):
    """仅输出固定原因码；不泄漏原件、URL、异常repr或绝对路径。"""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _reject(code):
    raise CacheReuseAdapterError(code) from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject('cache_json')
        result[key] = value
    return result


def _nonfinite(value):
    _reject('cache_json')


def _provider_identity(source):
    external_id = source.get('external_horse_id')
    if type(external_id) is not str or not external_id or external_id == LEGACY_SENTINEL:
        _reject('stable_identity_missing')
    horse_key = 'hkjc:' + external_id
    try:
        _key(horse_key)
    except ValueError:
        _reject('stable_identity_missing')
    url = source.get('url')
    if type(url) is not str or '#' in url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        _reject('provider_origin')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != HKJC_HOST
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.path != HKJC_PATH):
            _reject('provider_origin')
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=2, errors='strict')
    except CacheReuseAdapterError:
        raise
    except (ValueError, UnicodeError):
        _reject('provider_origin')
    if pairs != [('HorseId', external_id)]:
        _reject('provider_identity_url')
    return horse_key


def adapt_hkjc_source_cache(raw_bytes, *, expected_sha256, ref, source_ref):
    """返回H02八字段record；缺证/无效输入抛固定CacheReuseAdapterError。

    不调用legacy validator、名称匹配、runner、source client或任何存储/网络接口。
    此处complete指通过既有整份canonical资料validator，不等于已公开或真实来源已认证。
    """
    if type(raw_bytes) is not bytes:
        _reject('cache_bytes')
    if len(raw_bytes) > MAX_CACHE_BYTES:
        _reject('cache_size')
    if type(expected_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        _reject('content_hash_unbound')
    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha != expected_sha256:
        _reject('content_hash_mismatch')
    try:
        _key(ref); _key(source_ref)
    except ValueError:
        _reject('cache_locator')
    try:
        content = raw_bytes.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        _reject('cache_utf8')
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (ValueError, RecursionError):
        _reject('cache_json')
    if type(payload) is not dict:
        _reject('cache_json')
    source = payload.get('source')
    if (payload.get('schema_version') != 'p0-horse-source-cache.v2'
            or payload.get('region') != 'hong_kong'
            or payload.get('adapter_key') != 'hong_kong_hkjc'
            or type(source) is not dict or source.get('name') != 'hkjc'):
        _reject('cache_scope')
    horse_key = _provider_identity(source)
    source_time = source.get('fetched_at')
    try:
        parsed_time = _time(source_time)
        if parsed_time.utcoffset() != timedelta(0):
            _reject('source_time')
    except (ValueError, TypeError, AttributeError):
        _reject('source_time')
    # Import only after byte binding, scope/identity/provenance checks; never create a client.
    from .p0_horse_completion_source_clients import (
        P0HorseSourceBlocked, validate_p0_horse_source_cache,
    )
    try:
        validate_p0_horse_source_cache(payload, allow_manual_supplements=False)
    except (P0HorseSourceBlocked, ValueError, TypeError, RecursionError):
        _reject('cache_validation')
    return dict(ref=ref, horse_key=horse_key, profile_id=None, source_time=source_time,
                source_ref=source_ref, content=content, content_sha256=actual_sha,
                parse_status='complete')
