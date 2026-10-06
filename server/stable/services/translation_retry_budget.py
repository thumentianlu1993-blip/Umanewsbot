"""B041 离线账接口骨架：可导入、零写入，尚未实现状态机。

无 provider/SDK/callable/CLI；生产路径无 caller。仅供独立离线 RED。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class BudgetIdentity:
    scope_kind: str
    source_site: str
    source_article_id: str
    source_sha256: str
    policy_sha256: str
    provider: str
    model: str
    operation_uuid: UUID | None = None
    article_pk_snapshot: int | None = None


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    budget_pk: int | None = None
    attempt_pk: int | None = None


def resolve_budget(identity: BudgetIdentity, *, mode: str, now: datetime,
                   initial_contract: dict | None = None) -> BudgetDecision:
    """技术骨架不创建/解析根；初建冲突处理留待真实 RED 后实施。"""
    return BudgetDecision(False, "core_not_implemented" if mode == "offline_test"
                          else "supported_mode_missing")


def reserve_request(identity: BudgetIdentity, *, mode: str, now: datetime,
                    claim_execution_uuid: UUID, claimed_at: datetime,
                    provider_attempt_index: int,
                    run_pk_snapshot: int | None = None) -> BudgetDecision:
    """技术骨架不写计数、不授权请求；不允许任何外部执行器。"""
    return BudgetDecision(False, "core_not_implemented" if mode == "offline_test"
                          else "supported_mode_missing")


def record_usage(*, budget_pk: int, attempt_pk: int, mode: str,
                 usage_report: dict, receipt: dict | None = None) -> BudgetDecision:
    """技术骨架不对账；receipt 只能是未来离线测试数据。"""
    return BudgetDecision(False, "core_not_implemented" if mode == "offline_test"
                          else "supported_mode_missing")
