"""离线翻译预算账核心；不具备 SDK/provider/消息执行能力。

唯一支持 offline_test。合成对账收据只使离线状态可继续，不能用于真实费用准入。
短事务仅锁独立预算→请求，不查询或改变 Article/Run。
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from uuid import UUID, uuid4

from django.db import IntegrityError, connection, models, transaction
from django.utils import timezone

from stable.models import SourceSite, TranslationRequestAttempt, TranslationRetryBudget


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
    operation_uuid: UUID | None = None
    budget_uuid: UUID | None = None


def _decision(reason, budget=None, attempt=None, *, allowed=False):
    return BudgetDecision(allowed, reason, budget.pk if budget else None,
                          attempt.pk if attempt else None,
                          budget.operation_uuid if budget else None,
                          budget.budget_uuid if budget else None)


def _aware(value):
    return type(value) is datetime and timezone.is_aware(value)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _identity_valid(identity):
    return (type(identity) is BudgetIdentity and type(identity.scope_kind) is str
            and identity.scope_kind == "managed_translation_retry"
            and type(identity.source_site) in (str, SourceSite) and 0 < len(identity.source_site) <= 32
            and all(type(v) is str and 0 < len(v) <= limit for v, limit in (
                (identity.source_article_id, 255),
                (identity.provider, 128), (identity.model, 255)))
            and _hash(identity.source_sha256) and _hash(identity.policy_sha256)
            and (identity.operation_uuid is None or type(identity.operation_uuid) is UUID)
            and (identity.article_pk_snapshot is None or (_integer(identity.article_pk_snapshot, 1)
                                                       and identity.article_pk_snapshot <= 9223372036854775807)))


def source_identity_sha256(source_site, source_article_id):
    """精确持久来源 pair；不 strip/lower、URL 别名或按正文猜身份。"""
    raw = json.dumps(["managed-translation-request-source-v1", source_site, source_article_id],
                     ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _json_snapshot(value):
    """拒绝自定义序列化/callable、循环、非finite；审计数据上限64KiB/16层。"""
    visiting = set()

    def validate(item, depth):
        if depth > 16:
            raise ValueError("JSON depth")
        kind = type(item)
        if kind in (dict, list):
            marker = id(item)
            if marker in visiting:
                raise ValueError("JSON cycle")
            visiting.add(marker)
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("JSON key")
                    validate(child, depth + 1)
            else:
                for child in item:
                    validate(child, depth + 1)
            visiting.remove(marker)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("JSON finite")
        elif kind not in (str, int, bool, type(None)):
            raise ValueError("JSON builtin")
    if type(value) is not dict:
        raise ValueError("JSON object")
    validate(value, 0)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > 65536:
        raise ValueError("JSON size")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _preflight(mode, identity=None, now=None):
    if type(mode) is not str or mode != "offline_test":
        return _decision("supported_mode_missing")
    if connection.in_atomic_block:
        return _decision("outer_transaction_forbidden")
    if identity is not None and not _identity_valid(identity):
        return _decision("invalid_identity")
    if identity is not None and not _aware(now):
        return _decision("invalid_clock")
    return None


def _actual_now(now):
    # 输入快照不能替代锁后 actual clock；较晚快照也不能倒退。
    return max(now, timezone.now())


def _locked_root(identity):
    roots = TranslationRetryBudget.objects.select_for_update()
    if identity.operation_uuid is not None:
        root = roots.filter(operation_uuid=identity.operation_uuid).first()
        if root:
            return root, None
    history = list(roots.filter(scope_kind=identity.scope_kind,
                               source_site_snapshot=identity.source_site,
                               source_article_id_snapshot=identity.source_article_id).order_by("pk"))
    if not history:
        return None, None
    active = [root for root in history if root.retired_at is None]
    root = active[0] if active else history[-1]
    if not active or (identity.operation_uuid is not None
                      and identity.operation_uuid != root.operation_uuid):
        return root, "operation_resolution_required"
    return root, None


def _identity_reason(root, identity):
    if ((root.scope_kind, root.source_site_snapshot, root.source_article_id_snapshot)
            != (identity.scope_kind, identity.source_site, identity.source_article_id)
            or root.identity_sha256 != source_identity_sha256(identity.source_site, identity.source_article_id)):
        return "identity_changed"
    return None


def _admission(root, identity, now):
    reason = _identity_reason(root, identity)
    if reason:
        return reason
    if root.retired_at is not None:
        return "budget_retired"
    attempts = list(root.request_attempts.order_by("seq"))
    # 未结消费先于版本变化/期限处理；这些变化绝不清除未知或退槽。
    if any(a.state in ("reserved", "unknown") for a in attempts):
        return "usage_unknown"
    if any(a.usage_validation != "known" or a.reconciliation_state != "offline_reconciled"
           or a.state != "reconciled" for a in attempts):
        return "cost_unreconciled"
    if (root.requests_reserved != len(attempts)
            or [a.seq for a in attempts] != list(range(1, len(attempts) + 1))
            or any((a.operation_uuid, a.budget_uuid, a.source_site_snapshot,
                    a.source_article_id_snapshot, a.identity_sha256, a.source_sha256) != (
                        root.operation_uuid, root.budget_uuid, root.source_site_snapshot,
                        root.source_article_id_snapshot, root.identity_sha256, root.source_sha256)
                   for a in attempts)):
        return "ledger_inconsistent"
    if (root.source_sha256, root.policy_sha256, root.provider_snapshot, root.model_snapshot) != (
            identity.source_sha256, identity.policy_sha256, identity.provider, identity.model):
        return "budget_version_changed"
    if root.state != "open":
        return root.blocked_reason or "budget_" + root.state
    now = _actual_now(now)
    if now < root.opened_at or now >= root.deadline_at:
        return "budget_deadline_expired"
    if root.requests_reserved >= root.request_limit:
        return "request_limit_exhausted"
    return None


def _write_locked(model, pk, **values):
    """唯一内部更新面，仅可写状态字段；调用点已持有预算/请求锁。"""
    permitted = {TranslationRetryBudget: {"requests_reserved"},
                 TranslationRequestAttempt: {"state", "usage_report", "usage_validation",
                                             "reconciliation_state", "receipt_sha256"}}
    if not connection.in_atomic_block or not values.keys() <= permitted[model]:
        raise ValueError("budget write outside locked state contract")
    updated = models.QuerySet.update(model.objects.filter(pk=pk), **values)
    if updated != 1:
        raise ValueError("budget row disappeared")


def resolve_budget(identity: BudgetIdentity, *, mode: str, now: datetime,
                   initial_contract: dict | None = None) -> BudgetDecision:
    refusal = _preflight(mode, identity, now)
    if refusal:
        return refusal
    with transaction.atomic():
        root, reason = _locked_root(identity)
        if root is None:
            if initial_contract is None:
                return _decision("budget_missing")
            if identity.operation_uuid is not None:
                return _decision("operation_resolution_required")
            if (type(initial_contract) is not dict or set(initial_contract) != {
                    "request_limit", "opened_at", "deadline_at", "policy_snapshot", "baseline_receipt"}):
                return _decision("invalid_initial_contract")
            limit = initial_contract["request_limit"]
            opened, deadline = initial_contract["opened_at"], initial_contract["deadline_at"]
            if not _integer(limit, 1) or limit > 2147483647 or not _aware(opened) or not _aware(deadline):
                return _decision("invalid_initial_contract")
            try:
                policy, _ = _json_snapshot(initial_contract["policy_snapshot"])
                baseline, _ = _json_snapshot(initial_contract["baseline_receipt"])
            except (ValueError, UnicodeError):
                return _decision("invalid_initial_contract")
            if baseline != {"kind": "synthetic_no_prior_consumption"}:
                return _decision("legacy_usage_unknown")
            if policy.get("mode") != "offline_test":
                return _decision("supported_mode_missing")
            actual = _actual_now(now)
            if not opened <= actual < deadline:
                return _decision("budget_deadline_expired")
            try:
                # 不存在的行无锁可取；唯一约束是首次建立串行权威。
                # 独立 savepoint 保证预期 unique 冲突不毒化外层事务。
                with transaction.atomic():
                    root = TranslationRetryBudget.objects.create(
                        operation_uuid=uuid4(), budget_uuid=uuid4(), scope_kind=identity.scope_kind,
                        article_pk_snapshot=identity.article_pk_snapshot,
                        source_site_snapshot=identity.source_site,
                        source_article_id_snapshot=identity.source_article_id,
                        identity_sha256=source_identity_sha256(identity.source_site, identity.source_article_id),
                        source_sha256=identity.source_sha256, policy_sha256=identity.policy_sha256,
                        provider_snapshot=identity.provider, model_snapshot=identity.model,
                        policy_snapshot=policy, opened_at=opened, deadline_at=deadline,
                        request_limit=limit,
                    )
            except IntegrityError as error:
                diag = getattr(error.__cause__, "diag", None)
                if getattr(diag, "constraint_name", None) != "uq_tr_budget_active_source":
                    raise
                root, reason = _locked_root(identity)
                if root is None:
                    raise
        reason = _identity_reason(root, identity) or reason or _admission(root, identity, _actual_now(now))
        return _decision(reason or "budget_resolved", root, allowed=reason is None)


def reserve_request(identity: BudgetIdentity, *, mode: str, now: datetime,
                    claim_execution_uuid: UUID, claimed_at: datetime,
                    provider_attempt_index: int,
                    run_pk_snapshot: int | None = None) -> BudgetDecision:
    refusal = _preflight(mode, identity, now)
    if refusal:
        return refusal
    if (type(claim_execution_uuid) is not UUID or not _aware(claimed_at)
            or not _integer(provider_attempt_index, 1) or provider_attempt_index > 2147483647
            or (run_pk_snapshot is not None and (not _integer(run_pk_snapshot, 1)
                                                 or run_pk_snapshot > 9223372036854775807))):
        return _decision("invalid_claim_identity")
    with transaction.atomic():
        root, resolution_reason = _locked_root(identity)
        if root is None:
            return _decision("budget_missing")
        reason = _identity_reason(root, identity) or resolution_reason
        if reason:
            return _decision(reason, root)
        existing = root.request_attempts.filter(claim_execution_uuid=claim_execution_uuid,
                                               provider_attempt_index=provider_attempt_index).first()
        if existing:
            return _decision("request_already_reserved", root, existing)
        actual = _actual_now(now)
        reason = _admission(root, identity, actual)
        if reason:
            return _decision(reason, root)
        if claimed_at < root.opened_at or claimed_at > actual:
            return _decision("invalid_claim_identity", root)
        actual = _actual_now(now)
        if actual >= root.deadline_at:
            return _decision("budget_deadline_expired", root)
        next_seq = root.requests_reserved + 1
        _write_locked(TranslationRetryBudget, root.pk, requests_reserved=next_seq)
        attempt = TranslationRequestAttempt.objects.create(
            budget=root, operation_uuid=root.operation_uuid, budget_uuid=root.budget_uuid,
            claim_execution_uuid=claim_execution_uuid, article_pk_snapshot=identity.article_pk_snapshot,
            run_pk_snapshot=run_pk_snapshot, claimed_at=claimed_at,
            source_site_snapshot=root.source_site_snapshot,
            source_article_id_snapshot=root.source_article_id_snapshot,
            identity_sha256=root.identity_sha256, source_sha256=root.source_sha256,
            seq=next_seq, provider_attempt_index=provider_attempt_index, reserved_at=actual,
        )
        decision = _decision("request_reserved", root, attempt, allowed=True)
    # 返回 allowed 之前 reservation 必须已提交；网络能力不存在。
    return decision


def record_usage(*, budget_pk: int, attempt_pk: int, mode: str,
                 usage_report: dict, receipt: dict | None = None) -> BudgetDecision:
    refusal = _preflight(mode)
    if refusal:
        return refusal
    if (not _integer(budget_pk, 1) or not _integer(attempt_pk, 1)
            or budget_pk > 9223372036854775807 or attempt_pk > 9223372036854775807):
        return _decision("invalid_request_identity")
    try:
        report, report_digest = _json_snapshot(usage_report)
        receipt_data, receipt_digest = _json_snapshot(receipt) if receipt is not None else (None, "")
    except (ValueError, UnicodeError):
        return _decision("invalid_usage_report")
    valid = all(_integer(report.get(key)) for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
    valid = valid and report["total_tokens"] == report["prompt_tokens"] + report["completion_tokens"]
    with transaction.atomic():
        root = TranslationRetryBudget.objects.select_for_update().filter(pk=budget_pk).first()
        if root is None:
            return _decision("budget_missing")
        attempt = TranslationRequestAttempt.objects.select_for_update().filter(pk=attempt_pk, budget=root).first()
        if attempt is None:
            return _decision("request_identity_changed", root)
        if (attempt.operation_uuid, attempt.budget_uuid, attempt.source_site_snapshot,
                attempt.source_article_id_snapshot, attempt.identity_sha256, attempt.source_sha256) != (
                root.operation_uuid, root.budget_uuid, root.source_site_snapshot,
                root.source_article_id_snapshot, root.identity_sha256, root.source_sha256):
            return _decision("request_identity_changed", root, attempt)
        synthetic_receipt = {"kind": "synthetic_offline_usage_v1", "budget_uuid": str(root.budget_uuid),
                             "attempt_pk": attempt.pk, "usage_sha256": report_digest}
        reconciled = valid and receipt_data == synthetic_receipt
        state = "reconciled" if reconciled else "usage_reported" if valid else "unknown"
        reconciliation = "offline_reconciled" if reconciled else "unreconciled"
        validation = "known" if valid else "invalid"
        upgrading_receipt = (attempt.state == "usage_reported" and attempt.usage_report == report
                             and attempt.usage_validation == "known" and not attempt.receipt_sha256
                             and attempt.reconciliation_state == "unreconciled" and reconciled)
        if not upgrading_receipt and (attempt.state not in ("reserved", "unknown")
                                     or attempt.usage_validation != "unknown"):
            if (attempt.usage_report == report and attempt.receipt_sha256 == receipt_digest
                    and attempt.state == state and attempt.usage_validation == validation
                    and attempt.reconciliation_state == reconciliation):
                return _decision("usage_already_recorded", root, attempt, allowed=reconciled)
            return _decision("usage_conflict", root, attempt)
        _write_locked(TranslationRequestAttempt, attempt.pk, state=state, usage_report=report,
                      usage_validation=validation, reconciliation_state=reconciliation,
                      receipt_sha256=receipt_digest)
        reason = "offline_usage_reconciled" if reconciled else "cost_unreconciled" if valid else "usage_unknown"
        decision = _decision(reason, root, attempt, allowed=reconciled)
    return decision
