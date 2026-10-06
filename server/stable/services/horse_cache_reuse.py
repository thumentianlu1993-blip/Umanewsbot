"""H02：对显式可信 producer 快照作纯离线缓存分类，不取数、不公开、不写库。

内容为 UTF-8 原件文本；parse_status 是 producer 的解析事实，本服务不冒充解析器。
调用方必须显式提供新鲜度秒数、时钟和实体版本，不以文件 mtime 或名称推断身份。
"""
from copy import deepcopy
from datetime import timedelta
import hashlib

from .horse_target_inventory import (
    _digest, _int, _key, _plain, _sha, _time, _validate, plan_inventory,
)

CACHE_FIELDS = {'ref', 'horse_key', 'profile_id', 'source_time', 'source_ref',
                'content', 'content_sha256', 'parse_status'}


def _validate_caches(records):
    if type(records) is not list or len(records) > 10000:
        raise ValueError('cache_collection_limit')
    total = 0
    refs = set()
    for record in records:
        if type(record) is not dict or set(record) != CACHE_FIELDS:
            raise ValueError('cache_schema')
        for field in ('ref', 'horse_key', 'source_ref'):
            _key(record[field])
        _int(record['profile_id'], True, 1)
        _time(record['source_time'], True)
        _digest(record['content_sha256'], True)
        if record['parse_status'] not in ('complete', 'partial', 'invalid', 'unknown'):
            raise ValueError('cache_parse_status')
        if type(record['content']) is not str:
            raise ValueError('cache_content')
        if len(record['content']) > 128 * 1024:
            raise ValueError('cache_content_limit')
        size = len(record['content'].encode('utf-8'))
        total += size
        if size > 128 * 1024 or total > 2 * 1024 * 1024:
            raise ValueError('cache_content_limit')
        if record['ref'] in refs:
            raise ValueError('duplicate_cache_ref')
        refs.add(record['ref'])
    return sorted(deepcopy(records), key=lambda record: record['ref'])


def plan_cache_reuse(snapshot, cache_records, entity_versions, *, as_of, max_age_seconds):
    """返回完整分类及每个(entity_key, entity_version)最多一个 H03 候选。

    候选幂等键不受遍历顺序影响；entity_version 必须由消费方维护，内容更新时换版本。
    对冲突/证据不足不生成候选；refresh 候选 content=None，绝不携带陈旧事实作复用。
    """
    p = _validate(snapshot)
    inventory = plan_inventory(p)
    now = _time(as_of)
    _int(max_age_seconds)
    if _time(p['snapshot_at']) > now:
        raise ValueError('snapshot_time_future')
    records = _validate_caches(cache_records)
    if type(entity_versions) is not dict:
        raise ValueError('entity_versions_schema')
    target_keys = {target['key'] for target in inventory['targets']}
    for key, version in entity_versions.items():
        _key(key); _key(version)
        if key not in target_keys:
            raise ValueError('version_target_unknown')
    _plain(entity_versions)

    # Mirror H01's strong-identity gate: any revoked/observed row blocks that key.
    identities = {}
    for identity in p['identities']:
        identities.setdefault(identity['horse_key'], []).append(identity)
    bindings = {}
    conflicts = set()
    for key, values in identities.items():
        profiles = {value['profile_id'] for value in values}
        if len(profiles) > 1:
            conflicts.add(key)
        if len(profiles) == 1 and all(value['status'] == 'verified' for value in values):
            bindings[key] = 'profile:' + str(next(iter(profiles)))
    grouped = {}
    for record in records:
        target_key = bindings.get(record['horse_key'], 'source:' + record['horse_key'])
        grouped.setdefault(target_key, []).append(record)
    decisions, candidates, used = [], [], set()
    for target in inventory['targets']:
        key = target['key']
        matched = grouped.get(key, [])
        used.update(record['ref'] for record in matched)
        proof = [identity for identity in p['identities']
                 if bindings.get(identity['horse_key']) == key]
        proof.sort(key=lambda item: (item['horse_key'], item['evidence_sha'], item['verified_at']))
        reasons = []
        status = 'reusable'
        chosen = matched
        version = entity_versions.get(key)
        if key.removeprefix('source:') in conflicts or any(
                key.startswith('profile:') and record['profile_id'] is not None
                and key != 'profile:' + str(record['profile_id'])
                for record in matched):
            status, reasons = 'identity_conflict', ['identity_binding_conflict']
        elif not target['resolved'] or not proof:
            status, reasons = 'insufficient', ['strong_identity_missing']
        elif version is None:
            status, reasons = 'insufficient', ['entity_version_missing']
        elif any(record['source_time'] is None for record in matched):
            status, reasons = 'insufficient', ['source_time_missing']
        elif any(_time(record['source_time']) > now for record in matched):
            status, reasons = 'insufficient', ['source_time_future']
        elif not matched:
            status, reasons = 'refresh_required', ['cache_missing']
        else:
            latest = max(_time(record['source_time']) for record in matched)
            chosen = [record for record in matched if _time(record['source_time']) == latest]
            if any(record['content_sha256'] is None for record in chosen):
                status, reasons = 'insufficient', ['content_hash_missing']
            elif any(hashlib.sha256(record['content'].encode('utf-8')).hexdigest()
                     != record['content_sha256'] for record in chosen):
                status, reasons = 'refresh_required', ['content_hash_mismatch']
            elif len({record['content_sha256'] for record in chosen}) > 1:
                status, reasons = 'cache_conflict', ['same_time_content_conflict']
            elif any(record['parse_status'] != 'complete' for record in chosen):
                status, reasons = 'refresh_required', ['cache_partial']
            elif now - latest > timedelta(seconds=max_age_seconds):
                status, reasons = 'refresh_required', ['cache_expired']
        refs = sorted(record['ref'] for record in chosen)
        decision = dict(entity_key=key, entity_version=version, status=status,
                        reasons=reasons, cache_refs=refs,
                        public_state=target['layers']['public_state'],
                        profile_exists=target['layers']['profile_exists'],
                        memberships=deepcopy(target['memberships']))
        decisions.append(decision)
        if status in ('reusable', 'refresh_required'):
            candidates.append(dict(entity_key=key, entity_version=version, action=status,
                                   idempotency_key=_sha({'entity_key': key, 'entity_version': version}),
                                   cache_refs=refs, target_refs=deepcopy(target['refs']),
                                   identity_evidence=deepcopy(proof),
                                   cache_evidence=[{field: deepcopy(record[field]) for field in
                                                    ('ref', 'horse_key', 'source_ref', 'source_time',
                                                     'content_sha256', 'parse_status')}
                                                   for record in chosen],
                                   content=chosen[0]['content'] if status == 'reusable' else None))
    result = dict(schema_version='horse-cache-reuse.v1', as_of=as_of,
                  max_age_seconds=max_age_seconds, inventory_sha256=inventory['content_sha256'],
                  cache_input_sha256=_sha(records), decisions=decisions, candidates=candidates,
                  unused_cache_refs=sorted(record['ref'] for record in records if record['ref'] not in used),
                  complete=False, published=False)
    result['content_sha256'] = _sha(result)
    return result
