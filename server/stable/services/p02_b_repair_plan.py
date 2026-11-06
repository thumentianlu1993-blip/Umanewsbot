"""纯离线B库修复计划封装，不执行SQL，也不代替切点、catalog或授权核验。"""
import copy
import re
from datetime import datetime

from stable.services.duplicate_repair_rehearsal import build_plan, digest


def _hex(value, size):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{%d}' % size, value):
        raise ValueError('invalid immutable digest')


def _identity(value):
    if not isinstance(value, dict) or set(value) != {'system_identifier', 'database_oid', 'database'}:
        raise ValueError('incomplete database identity')
    if any(not isinstance(value[k], str) or not re.fullmatch('[1-9][0-9]*', value[k])
           for k in ('system_identifier', 'database_oid')):
        raise ValueError('invalid database identity number')
    if not isinstance(value['database'], str) or not re.fullmatch('[a-z][a-z0-9_]{0,62}', value['database']):
        raise ValueError('invalid database name')


def prepare(*, before, news_keep_ids, rejected_keep_ids, source_identity,
            target_identity, backup_sha256, candidate_commit, catalog_sha256,
            foreign_keys_sha256, observed_at):
    """冻结调用方提供的证据摘要；摘要真实来源由后续只读采集和执行器核验。"""
    for value in (backup_sha256, catalog_sha256, foreign_keys_sha256):
        _hex(value, 64)
    _hex(candidate_commit, 40)
    _identity(source_identity)
    _identity(target_identity)
    if (source_identity['system_identifier'] != target_identity['system_identifier']
            or source_identity['database_oid'] == target_identity['database_oid']
            or source_identity['database'] == target_identity['database']):
        raise ValueError('B must be a distinct database in the bound cluster')
    try:
        observed = datetime.fromisoformat(observed_at)
    except (ValueError, TypeError):
        raise ValueError('invalid observation timestamp') from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError('observation timestamp requires timezone')
    anchors = []
    for values in (news_keep_ids, rejected_keep_ids):
        if not isinstance(values, (list, tuple)) or any(type(i) is not int or i <= 0 for i in values):
            raise ValueError('invalid anchor IDs')
        if len(values) != len(set(values)):
            raise ValueError('duplicate anchor IDs')
        anchors.append(sorted(values))
    # JSON归一化使mapping的整数键与磁盘往返后一致。
    import json
    repair = json.loads(json.dumps(build_plan(before, *anchors, observed_at=observed_at)))
    result = dict(version=1, state='prepared_not_authorized', before=copy.deepcopy(before),
                  news_keep_ids=anchors[0], rejected_keep_ids=anchors[1],
                  source_identity=copy.deepcopy(source_identity), target_identity=copy.deepcopy(target_identity),
                  backup_sha256=backup_sha256, candidate_commit=candidate_commit,
                  catalog_sha256=catalog_sha256, foreign_keys_sha256=foreign_keys_sha256,
                  observed_at=observed_at, repair=repair)
    return {**result, 'sha256': digest(result)}


def verify(plan, *, expected_sha256):
    """校验外部固定摘要并重算规划；不返回生产可执行或获准状态。"""
    _hex(expected_sha256, 64)
    if not isinstance(plan, dict):
        raise ValueError('invalid plan envelope')
    payload = {k: v for k, v in plan.items() if k != 'sha256'}
    if plan.get('sha256') != expected_sha256 or digest(payload) != expected_sha256:
        raise ValueError('repair plan digest drift')
    fields = ('before', 'news_keep_ids', 'rejected_keep_ids', 'source_identity',
              'target_identity', 'backup_sha256', 'candidate_commit', 'catalog_sha256',
              'foreign_keys_sha256', 'observed_at')
    if not all(k in plan for k in fields):
        raise ValueError('incomplete repair plan')
    if prepare(**{k: plan[k] for k in fields}) != plan:
        raise ValueError('repair plan derivation differs')
