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
from stable.services.news_attribution import filter_articles_visible_in_region


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
    queryset = (
        NewsArticle.objects.filter(
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at__isnull=False,
            published_to_web_at__gte=now - timedelta(hours=lookback_hours),
        )
        .order_by("-score_total", "-published_to_web_at", "id")
    )
    return filter_articles_visible_in_region(queryset, region)


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
        # Resolve race identity once per article for exposure governance
        _race_identity = None
        _race_angle = "other"
        if getattr(settings, "RACE_NEWS_EXPOSURE_ENABLED", False):
            from stable.services.race_news_exposure import (
                classify_angle,
                resolve_race_identity,
            )
            _race_identity = resolve_race_identity(article)
            if _race_identity:
                from stable.models import RaceEvent
                event = RaceEvent.objects.filter(pk=_race_identity["event_id"]).first()
                if event:
                    angle_result = classify_angle(article=article, event=event)
                    _race_angle = angle_result["angle"]

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
            # Atomically bind exposure reservation + quota reservation +
            # delivery creation for this target.  The exposure reservation
            # runs in its own savepoint so a later quota rejection can roll
            # back JUST the exposure (no orphan row) while the quota ledger
            # bookkeeping (row created, used unchanged) still commits.
            # A hard failure (exception) anywhere rolls back the whole
            # bundle via the outer atomic block.
            existing_delivery: QQPushDelivery | None = None
            delivery: QQPushDelivery | None = None
            skip_reason = ""
            skip_payload: dict | None = None
            with transaction.atomic():
                existing_delivery = QQPushDelivery.objects.filter(article=article, target=target).first()
                if existing_delivery is not None:
                    skip_reason = _existing_delivery_skip_reason(existing_delivery)
                    if skip_reason:
                        skip_payload = {"delivery_id": existing_delivery.id}
                exposure_id = None
                exposure_savepoint = None
                # Check race exposure slot availability
                if not skip_reason and _race_identity:
                    from stable.models import RaceEvent, RaceNewsExposure
                    from stable.services.race_news_exposure import reserve_qq_exposure
                    event = RaceEvent.objects.filter(pk=_race_identity["event_id"]).first()
                    if event:
                        exposure_savepoint = transaction.savepoint()
                        exposure_result = reserve_qq_exposure(
                            event=event,
                            article=article,
                            target=target,
                            angle=_race_angle,
                        )
                        if exposure_result is None:
                            skip_reason = "no_slot_available"
                        # Do NOT deliver waiting slot-2 — it hasn't matured
                        # yet.  The waiting exposure intentionally stays
                        # committed (matches the instant-push path) so it
                        # can be promoted once the delay elapses.
                        elif exposure_result.get("status") == "waiting":
                            skip_reason = "slot2_waiting"
                            exposure_savepoint = None
                        else:
                            exposure_id = exposure_result.get("id")
                if not skip_reason:
                    reserved, quota_reason = _reserve_qq_quotas(
                        target=target,
                        window=window,
                        group_hour_limit=group_hour_limit,
                        site_hour_limit=site_hour_limit,
                    )
                    if not reserved:
                        skip_reason = quota_reason
                        # Quota rejected AFTER the exposure slot was
                        # reserved: roll back ONLY the exposure savepoint
                        # so no orphan exposure row is committed (no
                        # delivery will ever reference it).  The quota
                        # ledger rows themselves still commit with `used`
                        # unchanged, preserving the pre-existing quota
                        # bookkeeping contract.
                        if exposure_savepoint is not None:
                            transaction.savepoint_rollback(exposure_savepoint)
                if not skip_reason:
                    delivery = existing_delivery or ensure_qq_push_deliveries(article, [target])[0]
                    if exposure_id:
                        # Link the exposure to its delivery inside the same
                        # transaction so the pair commits or rolls back together.
                        RaceNewsExposure.objects.filter(pk=exposure_id).update(delivery=delivery)
            if skip_reason:
                _record_target_decision(
                    window=window,
                    target=target,
                    article=article,
                    status=WindowDecisionStatus.SKIPPED,
                    reason=skip_reason,
                    payload=skip_payload,
                )
                zero_reasons.append(skip_reason)
                continue
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
