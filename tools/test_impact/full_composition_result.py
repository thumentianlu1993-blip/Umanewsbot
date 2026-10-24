"""父级 parsed plan/report 机制汇总；不接正式 runner，不认证真实 full 执行。

调用方须提供候选外固定 identity/catalog/rules/protected_native_ids；parent 中两份
collection、capabilities 的形状和 READY 字段不认证其独立性或实际资格。
expected children 始终由既有 derive_children 推导，不能由候选传入覆盖。
每个 child（包括 ordinary 空集）经既有适配器真实调用原 core，再核完整 E 结构。
没有全量实际调度、原始日志认证、root/image、PG/CID、上传或交付资格实现。
"""
from tools.test_impact import core
from tools.test_impact import full_composition as composition
from tools.test_impact import full_composition_evidence as evidence


class ParentEvidenceRejected(ValueError):
    """父级角色/报告封装或汇总不符；不是 native 业务 RED。"""


def _require(condition, message):
    if not condition:
        raise ParentEvidenceRejected('parent evidence: ' + message)


def verify_parent_result(parent, children, reports, capabilities, *,
                         identity, catalog, rules, protected_native_ids):
    """真实串联已有三接口，最多返回 PARENT_MECHANISM_VALID_GATE_NOT_READY。

    不接受 expected_children、core_passed 或独立认证布尔。capabilities 原样交给
    既有结构检查，缺失/BLOCKED 不补造 READY；通过其形状检查也不表示资格完成。
    原 child plan/report 对象不重写，原 core/child 异常及 cause 原样传播。
    返回子结果中的 canonical report digest 仍仅是 parsed dict 摘要。
    """
    context = dict(identity=identity, catalog=catalog, rules=rules,
                   protected_native_ids=protected_native_ids)
    expected_children = composition.derive_children(parent, **context)
    expected_by_role = {child['role']: child for child in expected_children}
    _require(type(children) is list and len(children) == len(expected_children),
             'missing/duplicate/extra child role')
    by_role = {}
    for child in children:
        _require(type(child) is dict and set(child) == {'role', 'plan', 'plan_digest'}, 'child fields')
        role = child['role']
        _require(type(role) is str and role in expected_by_role and role not in by_role,
                 'unknown/duplicate child role')
        by_role[role] = child
    _require(set(by_role) == set(expected_by_role), 'incomplete child roles')
    _require(type(reports) is list, 'report envelopes list required')
    grouped = {role: [] for role in expected_by_role}
    for envelope in reports:
        _require(type(envelope) is dict and set(envelope) == {'role', 'child_plan_digest', 'report'},
                 'report envelope fields')
        role = envelope['role']
        _require(type(role) is str and role in grouped, 'unknown report role')
        # 只分组，不去重、不丢额外报告、不改 raw key/digest。child adapter/core 实际核验它们。
        grouped[role].append(envelope)
    child_results = []
    for expected in expected_children:
        role = expected['role']
        child_results.append(evidence.verify_child_evidence(expected, by_role[role], grouped[role]))
    # 只有全部真实 child core 数据合同通过后，仍需原完整 E/命名空间/零 skip 结构检查。
    structure = composition.check_execution_structure(
        parent, children, reports, capabilities, **context)
    _require(sum(result['count'] for result in child_results) == structure['count'] == parent['count'],
             'child/structure/parent count mismatch')
    return dict(status='PARENT_MECHANISM_VALID_GATE_NOT_READY', parent_full_digest=core.digest(parent),
                count=structure['count'], lifecycle_policy=parent['lifecycle_policy'],
                child_results=child_results, structure_result=structure)


def formal_gate(*args, **kwargs):
    """父级机制成功不补齐独立采集、能力资格、PG/CID、调度/上传/delivery。"""
    raise evidence.FormalGateNotReady('parent mechanism only; trusted collect/capability/PG-CID/scheduling/upload/delivery NOT_READY')
