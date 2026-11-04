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


BASIC_MODULE_SCHEMA = 'hkjc-basic-profile-module.v1'
BASIC_MODULE_PRODUCER_VERSION = 'h03-hkjc-basic-producer.v1'
BASIC_MODULE_FIELDS = ('country', 'sex', 'color', 'birth_date', 'owner_name',
                       'trainer_name', 'breeder_name')


def _basic_module_json_guard(value):
    """限制原JSON结构；有限非选定数值不进入projection，不接纳人工补件。"""
    import math

    stack = [(value, 0)]
    remaining = 100000
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        if remaining < 0 or depth > 32:
            _reject('module_json_limit')
        if type(item) is dict:
            if (any(type(key) is not str for key in item)
                    or 'manual_supplements' in item
                    or 'manual_supplement_outcomes' in item
                    or item.get('entry_method') == 'manual_review'
                    or item.get('evidence_role') == 'manual_supplement'):
                _reject('module_json_or_manual_marker')
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is float:
            if not math.isfinite(item):
                _reject('module_json')
        elif item is not None and type(item) not in (str, int, bool):
            _reject('module_json')


def _basic_module_canonical(value):
    try:
        _basic_module_json_guard(value)
        content = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _reject('module_json')
    if len(content) > MAX_CACHE_BYTES:
        _reject('module_size')
    return content


def _basic_module_has_failure(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is dict:
            if any(item.get(key) for key in ('failure_reason', 'failure_reasons', 'conflict')):
                return True
            stack.extend(item.values())
        elif type(item) is list:
            stack.extend(item)
    return False


def produce_hkjc_basic_module(raw_bytes, *, expected_sha256, source_ref, permission_binding):
    """从绑定原件解析完整七字段模块；不声明whole完整、身份核准或来源许可。"""
    from datetime import date, datetime, timezone

    if type(raw_bytes) is not bytes:
        _reject('cache_bytes')
    if len(raw_bytes) > MAX_CACHE_BYTES:
        _reject('cache_size')
    if type(expected_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        _reject('content_hash_unbound')
    if hashlib.sha256(raw_bytes).hexdigest() != expected_sha256:
        _reject('content_hash_mismatch')
    try:
        _key(source_ref)
        if type(permission_binding) is not dict or set(permission_binding) != {'reference', 'sha256'}:
            _reject('module_permission_binding')
        _key(permission_binding['reference'])
        if (type(permission_binding['sha256']) is not str
                or not re.fullmatch('[0-9a-f]{64}', permission_binding['sha256'])):
            _reject('module_permission_binding')
    except ValueError:
        _reject('module_input_binding')
    try:
        payload = json.loads(raw_bytes.decode('utf-8', errors='strict'),
                             object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        _reject('cache_json')
    _basic_module_json_guard(payload)
    if type(payload) is not dict:
        _reject('cache_json')
    source = payload.get('source')
    if (payload.get('schema_version') != 'p0-horse-source-cache.v2'
            or payload.get('region') != 'hong_kong'
            or payload.get('adapter_key') != 'hong_kong_hkjc'
            or type(source) is not dict or source.get('name') != 'hkjc'):
        _reject('cache_scope')
    _provider_identity(source)
    try:
        source_time = _time(source.get('fetched_at'))
        if source_time.utcoffset() != timedelta(0):
            _reject('source_time')
    except (ValueError, TypeError, AttributeError):
        _reject('source_time')
    basic = payload.get('basic_profile')
    if type(basic) is not dict or payload.get('failure_reason') or payload.get('failure_reasons') or payload.get('conflict'):
        _reject('module_selected_failure')
    for selected in (source, payload.get('identity'), basic, payload.get('source_evidence')):
        if _basic_module_has_failure(selected):
            _reject('module_selected_failure')
    coverage = payload.get('coverage', {})
    if type(coverage) is not dict:
        _reject('module_selected_failure')
    for group in ('basic_profile', 'source_evidence'):
        if group in coverage:
            checked = coverage[group]
            if (type(checked) is not dict or _basic_module_has_failure(checked)
                    or ('complete' in checked and checked['complete'] is not True)):
                _reject('module_selected_failure')
    identity = payload.get('identity', {})
    if type(identity) is not dict:
        _reject('module_identity')
    for key in ('horse_name', 'sire_name', 'dam_name'):
        value = identity.get(key)
        if value is not None and value != '' and (type(value) is not str or not value.strip()):
            _reject('module_identity')
    year = identity.get('birth_year')
    if year is not None and year != '':
        if type(year) is not int or not 1800 <= year <= datetime.now(timezone.utc).year:
            _reject('module_identity')
    projection = {}
    from django.core.exceptions import ValidationError
    from stable.models import HorseProfile

    for field in BASIC_MODULE_FIELDS:
        value = basic.get(field)
        if type(value) is not str or not value.strip():
            _reject('module_basic_field')
        try:
            typed = value
            if field == 'birth_date':
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value.strip()):
                    _reject('module_basic_date')
                typed = date.fromisoformat(value.strip())
                if year is not None and year != '' and typed.year != year:
                    _reject('module_identity')
            HorseProfile._meta.get_field(field).clean(typed, None)
        except (ValidationError, ValueError, TypeError):
            _reject('module_basic_field')
        projection[field] = typed.isoformat() if field == 'birth_date' else value
    module = dict(
        schema_version=BASIC_MODULE_SCHEMA, producer_version=BASIC_MODULE_PRODUCER_VERSION,
        module='basic_profile', source_binding=dict(
            source_sha256=expected_sha256, source_ref=source_ref,
            carrier_schema=payload['schema_version'], provider='hkjc',
            external_horse_id=source['external_horse_id'], source_url=source['url'],
            fetched_at=source['fetched_at']),
        permission_binding=dict(reference=permission_binding['reference'], sha256=permission_binding['sha256']),
        projection=projection, projection_sha256=hashlib.sha256(_basic_module_canonical(projection)).hexdigest(),
        coverage=dict(basic_profile='validated_complete',
                      pedigree=dict(status='missing' if 'pedigree' not in payload else 'present_unassessed', raw_path='$.pedigree'),
                      career=dict(status='missing' if 'career' not in payload else 'present_unassessed', raw_path='$.career'),
                      whole_canonical='not_assessed'))
    _basic_module_canonical(module)
    return module


def basic_module_to_h02_record(module, *, raw_bytes, expected_sha256, source_ref, permission_binding):
    """重建模块后适配原八字段；complete只属于新模块content，不重标原件。"""
    rebuilt = produce_hkjc_basic_module(raw_bytes, expected_sha256=expected_sha256,
                                        source_ref=source_ref, permission_binding=permission_binding)
    content = _basic_module_canonical(rebuilt)
    if _basic_module_canonical(module) != content:
        _reject('module_rebuild_mismatch')
    source = rebuilt['source_binding']
    content_sha = hashlib.sha256(content).hexdigest()
    return dict(ref='h03-basic:' + content_sha, horse_key='hkjc:' + source['external_horse_id'],
                profile_id=None, source_time=source['fetched_at'], source_ref=source_ref,
                content=content.decode('utf-8'), content_sha256=content_sha, parse_status='complete')
