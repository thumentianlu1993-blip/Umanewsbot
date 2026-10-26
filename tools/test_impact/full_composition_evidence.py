"""仅核 parsed child plan/raw reports 的原 core 合同，不认证真实执行。

expected_child 必须由候选外固定 full spec/控制提供，不能直接把不可信 child
复制为 expected 来认证来源。完整 plan 含 parent/source/run/image/control 身份，
own digest 把它们绑定进原 raw report；raw report 原 schema 不额外捏造 image 字段。

只有 stdlib 和未改 core；不读文件、不加载业务、不调用进程/收集或外部能力。
本模块不替代 full E 聚合、独立 collect 真实性、capability、PG/CID、upload/delivery。
形状合规的伪报告也可能通过 core 的数据合同，故结果永远不是正式 full GREEN。
"""
import json
import re

from tools.test_impact import core

ROLES = ('ordinary', 'cache_primary3', 'cache_secondary2', 'cache_remaining3',
         'image_singleton', 'root_singleton')
CACHE_ROLES = ('cache_primary3', 'cache_secondary2', 'cache_remaining3')
CAPABILITY_ROLES = ('image_singleton', 'root_singleton')
IDENTITY_FIELDS = frozenset((
    'base_sha', 'head_sha', 'test_sha', 'test_tree', 'run_id', 'run_attempt', 'image_id',
    'catalog_digest', 'rules_digest', 'control_manifest_digest', 'image_supply_policy_digest',
    'capability_subject_pins_digest', 'lifecycle_policy_digest'))
PLAN_FIELDS = IDENTITY_FIELDS | frozenset((
    'source', 'mode', 'labels', 'batches', 'count', 'aliases', 'allowed_skips', 'parent_full_digest'))
RAW_FIELDS = frozenset((
    'key', 'profile', 'plan_digest', 'run_id', 'run_attempt', 'test_tree', 'executed',
    'failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes', 'lifecycle', 'exit_code'))
RAW_TELEMETRY = frozenset(('python', 'os', 'isolation', 'postgresql', 'django', 'seconds'))
QUALIFIED = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*\Z')
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\Z')
BATCH_KEY = re.compile(r'batch-[0-9]{3,}\Z')


class BindingEvidenceRejected(ValueError):
    """可信 spec/输入 schema/命名空间不符；不是 native 业务 RED。"""


class CoreEvidenceRejected(ValueError):
    """实际原 core 拒绝；保留原异常 __cause__，不改写为业务失败。"""


class IncompleteChildEvidence(ValueError):
    """原 core 接受但尚不满足零 skip/精确摘要的 child 证据合同。"""


class FormalGateNotReady(ValueError):
    """尚无完整可信执行与正式交付 API；不得输出正式 GREEN。"""


def _require(condition, message):
    if not condition:
        raise BindingEvidenceRejected('child evidence: ' + message)


def _keys(value, fields, message):
    _require(type(value) is dict and set(value) == set(fields), message)


def _hex(value, size):
    return type(value) is str and re.fullmatch('[0-9a-f]{%d}' % size, value) is not None


def _json(value):
    # JSON 值的严格比较，避免 bool/int 相等及 NaN；own digest 仍真实调用旧 core.digest。
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BindingEvidenceRejected('child evidence: canonical JSON required') from exc


def _names(value, message):
    _require(type(value) is list and all(type(v) is str and QUALIFIED.fullmatch(v) for v in value), message)
    _require(len(value) == len(set(value)), message)


def _trusted_spec(expected):
    _keys(expected, ('role', 'plan', 'plan_digest'), 'trusted child fields')
    role, plan = expected['role'], expected['plan']
    _require(type(role) is str and role in ROLES, 'trusted role')
    optional = {'fixture_inputs'} if role in CACHE_ROLES else {'capability_role'} if role in CAPABILITY_ROLES else set()
    _keys(plan, PLAN_FIELDS | optional, 'trusted child plan fields')
    _require(plan['source'] == 'git', 'Git child source required')
    _require(plan['mode'] in ('targeted', 'expanded'), 'child mode must remain targeted/expanded')
    for field in ('base_sha', 'head_sha', 'test_sha', 'test_tree'):
        _require(_hex(plan[field], 40), 'trusted source identity: ' + field)
    for field in IDENTITY_FIELDS - {'base_sha', 'head_sha', 'test_sha', 'test_tree', 'run_id', 'run_attempt', 'image_id'}:
        _require(_hex(plan[field], 64), 'trusted control digest: ' + field)
    _require(_hex(plan['parent_full_digest'], 64), 'parent digest')
    _require(type(plan['run_id']) is str and re.fullmatch('[1-9][0-9]*', plan['run_id']), 'trusted run ID')
    _require(type(plan['run_attempt']) is int and plan['run_attempt'] > 0, 'trusted run attempt')
    _require(type(plan['image_id']) is str and re.fullmatch('sha256:[0-9a-f]{64}', plan['image_id']), 'immutable child image')
    _require(type(plan['count']) is int and plan['count'] >= 0, 'trusted native count')
    _names(plan['labels'], 'trusted canonical labels')
    _require(type(plan['aliases']) is list and type(plan['allowed_skips']) is dict, 'trusted alias/skip metadata')
    if role in CACHE_ROLES:
        resource = plan['fixture_inputs']
        _keys(resource, ('id', 'manifest_sha256', 'source_sha', 'source_tree'), 'resource quartet')
        _require(type(resource['id']) is str and TOKEN.fullmatch(resource['id'])
                 and _hex(resource['manifest_sha256'], 64), 'resource identity')
        _require(resource['source_sha'] == plan['test_sha'] and resource['source_tree'] == plan['test_tree'],
                 'resource source binding')
        # ID/manifest/精确 native allowlist 已由候选外 compiler spec 固定；这里不认证资产字节。
    if role in CAPABILITY_ROLES:
        _require(plan['capability_role'] == role, 'capability role binding')
    _require(type(plan['batches']) is list, 'trusted batches list')
    seen_keys, ids = set(), []
    for batch in plan['batches']:
        _keys(batch, ('key', 'profile', 'ids'), 'trusted batch fields')
        _require(type(batch['key']) is str and BATCH_KEY.fullmatch(batch['key']) and batch['key'] not in seen_keys,
                 'trusted batch key duplicate/invalid')
        seen_keys.add(batch['key'])
        _require(type(batch['profile']) is str and TOKEN.fullmatch(batch['profile']), 'trusted batch profile')
        _names(batch['ids'], 'trusted batch IDs duplicate/invalid')
        _require(0 < len(batch['ids']) <= 200, 'trusted batch size')
        ids.extend(batch['ids'])
    _require(len(ids) == len(set(ids)) == plan['count'] == len(plan['labels'])
             and set(ids) == set(plan['labels']), 'trusted count/IDs mismatch')
    _require(role == 'ordinary' or plan['count'] > 0, 'nonordinary empty child')
    _json(expected)
    _require(_hex(expected['plan_digest'], 64) and expected['plan_digest'] == core.digest(plan), 'trusted own plan digest')


def _raw_report(report, plan):
    _require(type(report) is dict and RAW_FIELDS <= set(report)
             and set(report) <= RAW_FIELDS | RAW_TELEMETRY, 'raw report fields')
    _require(type(report['key']) is str and BATCH_KEY.fullmatch(report['key']), 'raw batch key')
    _require(type(report['profile']) is str and TOKEN.fullmatch(report['profile']), 'raw profile')
    _require(_hex(report['plan_digest'], 64), 'raw own digest')
    for field in ('run_id', 'run_attempt', 'test_tree'):
        # 值的具体匹配由原 core 核验；只先堵 bool==int 类型旁路。
        _require(type(report[field]) is type(plan[field]), 'raw identity type: ' + field)
    _require(type(report['exit_code']) is int and type(report['lifecycle']) is str, 'raw exit/lifecycle types')
    for field in ('executed', 'failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes'):
        _require(type(report[field]) is list, 'raw outcome list: ' + field)
    _require(all(type(v) is str for v in report['executed']), 'raw executed ID strings')
    _json(report)


def verify_child_evidence(expected_child, child, reports):
    """绑定一个固定 child，再实际调用原 core，最多给出 CHILD_EVIDENCE_VALID_GATE_NOT_READY。

    expected_child 是调用方受信 spec；此函数没有独立采集或 spec 来源认证能力。
    reports 为原 schema 的 parsed raw reports 的显式 role/digest envelope；不接受摘要布尔。
    输入不重写，原 core 收到 child 原 plan 与原 report 对象，自己的 digest/mode 保持。
    返回的 canonical_report_digest 是字典规范摘要，绝不是原日志/文件字节摘要。
    ordinary 空 child 的 count0 也真实经过原 core，不贡献额外 native 分母。
    """
    _trusted_spec(expected_child)
    _require(_json(child) == _json(expected_child), 'trusted child mismatch')
    plan, role, own_digest = child['plan'], child['role'], child['plan_digest']
    _require(type(reports) is list, 'raw report envelopes list required')
    raw_reports, namespaces = [], []
    for envelope in reports:
        _keys(envelope, ('role', 'child_plan_digest', 'report'), 'raw report envelope fields')
        _require(envelope['role'] == role and envelope['child_plan_digest'] == own_digest,
                 'report namespace identity mismatch')
        report = envelope['report']
        _raw_report(report, plan)
        raw_reports.append(report)
        namespaces.append('roles/%s/%s/%s.json' % (role, own_digest, report['key']))
    try:
        # 不接受调用方 core_passed/ready；不自造验证成功或重写 raw report 的 plan_digest。
        result = core.verify_results(plan, raw_reports)
    except (ValueError, KeyError, TypeError) as exc:
        raise CoreEvidenceRejected('child evidence: original core rejected: ' + str(exc)) from exc
    if result['skipped_count'] != 0:
        raise IncompleteChildEvidence('child evidence: zero actual skips required; original core accepted policy is insufficient')
    expected_result = dict(status='passed', skipped_count=0, mode=plan['mode'], count=plan['count'],
                           plan_digest=own_digest, run_id=plan['run_id'], run_attempt=plan['run_attempt'], test_tree=plan['test_tree'])
    if _json(result) != _json(expected_result):
        raise IncompleteChildEvidence('child evidence: original core summary mismatch')
    return dict(status='CHILD_EVIDENCE_VALID_GATE_NOT_READY', role=role,
                parent_full_digest=plan['parent_full_digest'], child_plan_digest=own_digest,
                count=result['count'], core_result=result,
                reports=[dict(namespace=namespace, canonical_report_digest=core.digest(report))
                         for namespace, report in zip(namespaces, raw_reports)])


def formal_gate(*args, **kwargs):
    """无独立 full collect、真实能力及生命周期/交付适配器，任何输入均不得签正式 GREEN。"""
    raise FormalGateNotReady('independent collect/root-image/PG-CID/upload/delivery NOT_READY; child core evidence is not full GREEN')
