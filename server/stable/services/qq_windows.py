from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable.models import (
    NewsArticle,
    ProductionWindow,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    QuotaLedger,
    QuotaLedgerKind,
    QuotaLedgerScope,
    WindowDecisionStatus,
    WindowTargetDecision,
    WorkflowStatus,
)
from stable.services.qq_auto_push import ensure_qq_push_deliveries, should_push_news_to_qq


@dataclass(frozen=True)
class QQWindowResult:
    deliveries: list[QQPushDelivery]
    zero_reasons: list[str] = field(default_factory=list)


def _record_target_decision(
    *,
    window: ProductionWindow,
    target: PushTarget,
    status: str,
    reason: str,
    article: NewsArticle | None = None,
    payload: dict | None = None,
) -> None:
    article_id = article.id if article else "none"
    decision_key = f"target:{target.id}:article:{article_id}"
    WindowTargetDecision.objects.update_or_create(
        window=window,
        decision_key=decision_key,
        defaults={
            "target": target,
            "article": article,
            "status": status,
            "reason": reason,
            "payload": payload or {},
        },
    )


def _candidate_queryset(region: str, *, now):
    lookback_hours = int(getattr(settings, "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", 3))
    return (
        NewsArticle.objects.filter(
            racing_region=region,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at__isnull=False,
            published_to_web_at__gte=now - timedelta(hours=lookback_hours),
        )
        .order_by("-score_total", "-published_to_web_at", "id")
    )


def _quota_ledger(*, kind: str, scope: str, scope_key: str, window: ProductionWindow, limit: int) -> QuotaLedger:
    hour_start = window.window_start.replace(minute=0, second=0, microsecond=0)
    ledger, _created = QuotaLedger.objects.select_for_update().get_or_create(
        kind=kind,
        scope=scope,
        scope_key=scope_key,
        window_start=hour_start,
        defaults={"limit": limit, "used": 0},
    )
    ledger.limit = limit
    return ledger


def _reserve_qq_quotas(
    *,
    target: PushTarget,
    window: ProductionWindow,
    group_hour_limit: int,
    site_hour_limit: int,
) -> tuple[bool, str]:
    with transaction.atomic():
        group_ledger = _quota_ledger(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.GROUP_HOUR,
            scope_key=f"group:{target.group_id}",
            window=window,
            limit=group_hour_limit,
        )
        site_ledger = _quota_ledger(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.SITE_HOUR,
            scope_key="site",
            window=window,
            limit=site_hour_limit,
        )
        if group_ledger.used + 1 > group_hour_limit:
            group_ledger.save(update_fields=["limit", "updated_at"])
            site_ledger.save(update_fields=["limit", "updated_at"])
            return False, "group_hour_quota_exhausted"
        if site_ledger.used + 1 > site_hour_limit:
            group_ledger.save(update_fields=["limit", "updated_at"])
            site_ledger.save(update_fields=["limit", "updated_at"])
            return False, "site_hour_quota_exhausted"
        group_ledger.used += 1
        site_ledger.used += 1
        group_ledger.save(update_fields=["limit", "used", "updated_at"])
        site_ledger.save(update_fields=["limit", "used", "updated_at"])
        return True, "reserved"


def _existing_delivery_skip_reason(delivery: QQPushDelivery) -> str:
    if delivery.status == QQPushDeliveryStatus.SENT:
        return "already_sent"
    if delivery.status in {
        QQPushDeliveryStatus.PENDING,
        QQPushDeliveryStatus.RETRYING,
        QQPushDeliveryStatus.SENDING,
    }:
        return "already_queued"
    if delivery.attempt_count >= delivery.max_attempts:
        return "already_failed"
    return ""


def select_qq_window_deliveries(
    region: str,
    *,
    window: ProductionWindow,
    targets: list[PushTarget] | None = None,
    now=None,
) -> QQWindowResult:
    now = now or timezone.now()
    targets = targets if targets is not None else list(PushTarget.objects.filter(is_active=True))
    if not targets:
        return QQWindowResult(deliveries=[], zero_reasons=["no_targets"])

    region_limit = int(getattr(settings, "MULTIREGION_QQ_REGION_WINDOW_MAX", 3))
    group_hour_limit = (
        int(getattr(settings, "MULTIREGION_QQ_GROUP_HOURLY_MAX_MAJOR_RACE", 24))
        if window.mode == "major_race"
        else int(getattr(settings, "MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY", 12))
    )
    site_hour_limit = (
        int(getattr(settings, "MULTIREGION_QQ_SITE_HOURLY_MAX_MAJOR_RACE", 80))
        if window.mode == "major_race"
        else int(getattr(settings, "MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY", 40))
    )
    selected_articles = 0
    deliveries: list[QQPushDelivery] = []
    zero_reasons: list[str] = []

    for article in _candidate_queryset(region, now=now):
        if (article.decision_reason or {}).get("disable_auto_qq"):
            for target in targets:
                _record_target_decision(
                    window=window,
                    target=target,
                    article=article,
                    status=WindowDecisionStatus.SKIPPED,
                    reason="soft_fill_no_auto_qq",
                )
            zero_reasons.append("soft_fill_no_auto_qq")
            continue
        if selected_articles >= region_limit:
            for target in targets:
                _record_target_decision(
                    window=window,
                    target=target,
                    article=article,
                    status=WindowDecisionStatus.SKIPPED,
                    reason="region_window_limit",
                )
            continue
        article_deliveries: list[QQPushDelivery] = []
        for target in targets:
            eligibility = should_push_news_to_qq(article, target=target)
            if not eligibility.allowed:
                _record_target_decision(
                    window=window,
                    target=target,
                    article=article,
                    status=WindowDecisionStatus.SKIPPED,
                    reason=eligibility.reason or "not_eligible",
                )
                continue
            existing_delivery = QQPushDelivery.objects.filter(article=article, target=target).first()
            if existing_delivery is not None:
                existing_skip_reason = _existing_delivery_skip_reason(existing_delivery)
                if existing_skip_reason:
                    _record_target_decision(
                        window=window,
                        target=target,
                        article=article,
                        status=WindowDecisionStatus.SKIPPED,
                        reason=existing_skip_reason,
                        payload={"delivery_id": existing_delivery.id},
                    )
                    zero_reasons.append(existing_skip_reason)
                    continue
            reserved, quota_reason = _reserve_qq_quotas(
                target=target,
                window=window,
                group_hour_limit=group_hour_limit,
                site_hour_limit=site_hour_limit,
            )
            if not reserved:
                _record_target_decision(
                    window=window,
                    target=target,
                    article=article,
                    status=WindowDecisionStatus.SKIPPED,
                    reason=quota_reason,
                )
                zero_reasons.append(quota_reason)
                continue
            delivery = existing_delivery or ensure_qq_push_deliveries(article, [target])[0]
            article_deliveries.append(delivery)
            _record_target_decision(
                window=window,
                target=target,
                article=article,
                status=WindowDecisionStatus.SELECTED,
                reason="retry_existing" if existing_delivery is not None else "selected",
                payload={"delivery_id": delivery.id},
            )
        if article_deliveries:
            deliveries.extend(article_deliveries)
            selected_articles += 1

    if not deliveries and not zero_reasons:
        zero_reasons.append("no_eligible_articles")
    return QQWindowResult(deliveries=deliveries, zero_reasons=list(dict.fromkeys(zero_reasons)))
