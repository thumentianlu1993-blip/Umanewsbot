"""赛事结果的资源分级；预算例外只能来自已验证的精确取数 claim。"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.db.models import Case, When, Value, IntegerField

_result_transport = ContextVar("race_result_transport", default=None)


def needs_priority_result(event):
    return (event.status in ("scheduled", "running", "finished")
            and event.result_confirmed_at is None)


def due_priority(*, prefix="", now):
    """先领取当天未确认赛果，避免旧检查点占满 selector 的批次。"""
    return Case(When(**{
        prefix + "result_confirmed_at__isnull": True,
        prefix + "race_datetime__gte": now - timedelta(days=1),
        prefix + "race_datetime__lte": now + timedelta(minutes=10),
        "then": Value(0),
    }), default=Value(1), output_field=IntegerField())


def claim_queue(*, claim, event, retry=False):
    if "result" in claim.data_kinds and needs_priority_result(event):
        return "race_realtime_retry" if retry else "race_realtime"
    return "race_sync_v2"


def claim_priority(*, claim, event, retry=False):
    # Redis BRPOP 先遍历 priority_steps，再遍历队列；不依赖 set 的迭代顺序。
    return 0 if retry and "result" in claim.data_kinds and needs_priority_result(event) else 3


@contextmanager
def result_transport_scope(claim):
    from .race_data_sync_control import lock_and_validate_race_data_sync_claim_for_apply
    with transaction.atomic():
        decision, locked = lock_and_validate_race_data_sync_claim_for_apply(
            claim=claim, now=timezone.now(), required_data_kinds=("result",),
        )
        scope = None
        if locked is not None and needs_priority_result(locked.event):
            scope = (frozenset(row.source_key for row in locked.checkpoints),
                     locked.enrollment.source_identity.region_code,
                     locked.tracking.claim_expires_at)
            if claim.checkpoint_plan[0].get("authority", {}).get("authority_version") == 2:
                # 多来源区域来自该次绑定，不能拿 owner 来源的区域替代。
                from .race_data_source_adapters import claim_binding
                binding, route = claim_binding(claim, now=timezone.now())
                scope = (frozenset((route.provider,)), route.region, locked.tracking.claim_expires_at)
    token = _result_transport.set(scope)
    try:
        yield
    finally:
        _result_transport.reset(token)


def priority_transport_active(*, provider, region):
    scope = _result_transport.get()
    return bool(scope and provider in scope[0] and region == scope[1]
                and scope[2] is not None and timezone.now() < scope[2])


def retry_delay(*, priority, reason, now=None):
    if reason in {"artifact_daily_requests_exceeded", "artifact_daily_bytes_exceeded"}:
        now = now or timezone.now()
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0) - now
    if reason in {"access_denied", "http_403", "http_406", "jra_http_403", "jra_http_406"}:
        return timedelta(hours=1)
    return timedelta(minutes=1 if priority else 5)
