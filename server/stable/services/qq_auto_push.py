from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from stable.models import (
    ContentCategory,
    NewsArticle,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    QQPushErrorType,
    RacingRegion,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)
from stable.services.news_attribution import (
    article_region_set,
    article_related_region_labels,
    region_label,
    related_region_queries_enabled,
)

from .onebot import BotPusher


logger = logging.getLogger(__name__)

SCOPE_ALL_PUBLIC = "all_public"
SCOPE_HIGH_VALUE_ONLY = "high_value_only"
VALID_SCOPES = {SCOPE_ALL_PUBLIC, SCOPE_HIGH_VALUE_ONLY}
IMPORTANCE_STRATEGY_RANKED = "ranked"
VALID_IMPORTANCE_STRATEGIES = {IMPORTANCE_STRATEGY_RANKED}
RANKED_NEWS_MODES = {SourceMode.ACCESS, SourceMode.ATTENTION}
RANKED_NEWS_SOURCE_SITES = {
    SourceSite.NETKEIBA,
    SourceSite.SPONICHI,
    SourceSite.SKY_SPORTS_RACING,
    SourceSite.HORSE_RACING_NATION,
}
AUTO_PUSH_SUMMARY_LIMIT = 160
FIRST_PHASE_REGIONS = {
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
}


@dataclass(frozen=True)
class PushEligibility:
    allowed: bool
    reason: str = ""


def normalize_qq_push_scope(scope: str | None = None) -> str:
    candidate = (scope if scope is not None else getattr(settings, "QQ_PUSH_SCOPE", SCOPE_HIGH_VALUE_ONLY)) or ""
    normalized = candidate.strip().lower()
    if normalized in VALID_SCOPES:
        return normalized
    logger.warning("Unsupported QQ_PUSH_SCOPE=%s, fallback to %s", candidate, SCOPE_HIGH_VALUE_ONLY)
    return SCOPE_HIGH_VALUE_ONLY


def normalize_qq_push_importance_strategy(strategy: str | None = None) -> str:
    candidate = (
        strategy
        if strategy is not None
        else getattr(settings, "QQ_PUSH_IMPORTANCE_STRATEGY", IMPORTANCE_STRATEGY_RANKED)
    ) or ""
    normalized = candidate.strip().lower()
    if normalized in VALID_IMPORTANCE_STRATEGIES:
        return normalized
    logger.warning(
        "Unsupported QQ_PUSH_IMPORTANCE_STRATEGY=%s, fallback to %s",
        candidate,
        IMPORTANCE_STRATEGY_RANKED,
    )
    return IMPORTANCE_STRATEGY_RANKED


def target_allowed_regions(target: PushTarget | None = None) -> set[str]:
    if target is None:
        return set(FIRST_PHASE_REGIONS)
    raw_regions = target.allowed_regions or []
    if not isinstance(raw_regions, list) or not raw_regions:
        return {RacingRegion.JAPAN}
    regions = {str(region).strip() for region in raw_regions if str(region).strip() in FIRST_PHASE_REGIONS}
    return regions or {RacingRegion.JAPAN}


def target_push_scope(target: PushTarget | None = None, scope: str | None = None) -> str:
    if scope is not None:
        return normalize_qq_push_scope(scope)
    target_scope = (getattr(target, "push_scope", "") or "").strip() if target is not None else ""
    return normalize_qq_push_scope(target_scope or None)


def target_importance_strategy(target: PushTarget | None = None, strategy: str | None = None) -> str:
    if strategy is not None:
        return normalize_qq_push_importance_strategy(strategy)
    target_strategy = (getattr(target, "importance_strategy", "") or "").strip() if target is not None else ""
    return normalize_qq_push_importance_strategy(target_strategy or None)


def article_region(article: NewsArticle) -> str:
    return (getattr(article, "racing_region", "") or "").strip()


def article_regions(article: NewsArticle) -> set[str]:
    regions = article_region_set(article, include_related=related_region_queries_enabled())
    return {region for region in regions if region in FIRST_PHASE_REGIONS}


def content_category_allowed_for_qq(article: NewsArticle) -> bool:
    category = article.content_category or ContentCategory.NEWS
    configured = getattr(settings, "MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES", [])
    allowed = {str(item).strip() for item in configured if str(item).strip()}
    if not allowed:
        return True
    return category in allowed


def is_article_public(article: NewsArticle) -> bool:
    return article.workflow_status == WorkflowStatus.PUBLISHED and article.published_to_web_at is not None


def has_publish_blocker(article: NewsArticle) -> bool:
    return bool(article.gate_blockers)


def is_ranked_news(article: NewsArticle) -> bool:
    return article.source_site in RANKED_NEWS_SOURCE_SITES and article.source_mode in RANKED_NEWS_MODES


def build_public_article_url(article: NewsArticle) -> str:
    return f"{settings.SITE_URL.rstrip('/')}{article.public_path}"


def is_public_url_accessible(url: str) -> tuple[bool, str]:
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=getattr(settings, "QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS", 5),
        )
    except requests.RequestException as exc:
        return False, str(exc)
    if response.status_code == 200:
        return True, ""
    return False, f"HTTP {response.status_code}"


def should_push_news_to_qq(
    article: NewsArticle,
    scope: str | None = None,
    *,
    target: PushTarget | None = None,
) -> PushEligibility:
    if not is_article_public(article):
        return PushEligibility(False, "article_not_public")
    if has_publish_blocker(article):
        return PushEligibility(False, "has_blocker")
    regions = article_regions(article)
    if not regions:
        return PushEligibility(False, "region_missing")
    if target is not None and not regions.intersection(target_allowed_regions(target)):
        return PushEligibility(False, "region_not_allowed")
    if not content_category_allowed_for_qq(article):
        return PushEligibility(False, "content_category_not_qq_eligible")
    resolved_scope = target_push_scope(target, scope)
    if resolved_scope == SCOPE_ALL_PUBLIC:
        return PushEligibility(True)
    strategy = target_importance_strategy(target)
    if strategy == IMPORTANCE_STRATEGY_RANKED and is_ranked_news(article):
        return PushEligibility(True)
    return PushEligibility(False, "not_high_value")


def get_auto_push_targets() -> list[PushTarget]:
    return list(PushTarget.objects.filter(is_active=True))


def _collapse_text(text: str) -> str:
    return " ".join((text or "").split())


def _truncate_with_ellipsis(text: str, limit: int = AUTO_PUSH_SUMMARY_LIMIT) -> str:
    collapsed = _collapse_text(text)
    if len(collapsed) <= limit:
        return f"{collapsed}……" if collapsed else ""
    return f"{collapsed[:limit].rstrip()}……"


def _existing_summary(article: NewsArticle) -> str:
    manual_fields = set(article.manually_edited_fields or [])
    candidates: list[str] = []
    if "summary_zh" in manual_fields:
        candidates.append(article.summary_zh)
    candidates.extend([article.rewrite_summary_zh, article.summary_zh])
    if "push_summary_zh" in manual_fields:
        candidates.append(article.push_summary_zh)
    candidates.extend([article.push_summary_zh, article.translated_summary_zh])
    for candidate in candidates:
        collapsed = _collapse_text(candidate)
        if collapsed:
            return collapsed
    return ""


def build_qq_auto_push_message(article: NewsArticle, public_url: str | None = None) -> str:
    title = _collapse_text(article.effective_title)
    summary = _existing_summary(article)
    if not summary:
        summary = _truncate_with_ellipsis(article.effective_body)
    elif len(summary) > AUTO_PUSH_SUMMARY_LIMIT:
        summary = _truncate_with_ellipsis(summary)
    url = public_url or build_public_article_url(article)
    lines = [f"【UmaFans】{title}"]
    primary_label = region_label(article.racing_region)
    related_labels = article_related_region_labels(
        article,
        include_related=related_region_queries_enabled(),
    )
    if primary_label != "日本" or related_labels:
        lines.append(f"地区：{primary_label}")
    if related_labels:
        lines.append(f"关联地区：{' / '.join(related_labels)}")
    if summary:
        lines.append(summary)
    lines.append(f"阅读全文：{url}")
    return "\n".join(lines)


def ensure_qq_push_deliveries(article: NewsArticle, targets: list[PushTarget] | None = None) -> list[QQPushDelivery]:
    max_attempts = max(1, int(getattr(settings, "QQ_PUSH_MAX_ATTEMPTS", 3)))
    deliveries: list[QQPushDelivery] = []
    resolved_targets = targets if targets is not None else get_auto_push_targets()
    for target in resolved_targets:
        try:
            delivery, created = QQPushDelivery.objects.get_or_create(
                article=article,
                target=target,
                defaults={"max_attempts": max_attempts},
            )
        except IntegrityError:
            delivery = QQPushDelivery.objects.get(article=article, target=target)
            created = False
        if not created and delivery.max_attempts != max_attempts and delivery.status != QQPushDeliveryStatus.SENT:
            delivery.max_attempts = max_attempts
            delivery.save(update_fields=["max_attempts", "updated_at"])
        deliveries.append(delivery)
    return deliveries


def _message_id_from_response(response: dict) -> str:
    value = response.get("message_id")
    if value is None and isinstance(response.get("data"), dict):
        value = response["data"].get("message_id")
    return "" if value is None else str(value)


def _set_delivery_failure(delivery: QQPushDelivery, *, error_type: str, error: str) -> QQPushDelivery:
    status = QQPushDeliveryStatus.RETRYING
    if delivery.attempt_count >= delivery.max_attempts:
        status = QQPushDeliveryStatus.FAILED
    delivery.status = status
    delivery.last_error_type = error_type
    delivery.last_error = error[:2000]
    delivery.save(update_fields=["status", "last_error_type", "last_error", "updated_at"])
    return delivery


def _set_delivery_not_eligible(delivery: QQPushDelivery, *, reason: str) -> QQPushDelivery:
    delivery.status = QQPushDeliveryStatus.SKIPPED
    delivery.last_error_type = QQPushErrorType.NOT_ELIGIBLE
    delivery.last_error = reason[:2000]
    delivery.save(update_fields=["status", "last_error_type", "last_error", "updated_at"])
    return delivery


def _sending_stale_after() -> int:
    return max(60, int(getattr(settings, "QQ_PUSH_SENDING_STALE_SECONDS", 600)))


def qq_push_next_attempt_delay(delivery: QQPushDelivery) -> int:
    min_interval = max(0, int(getattr(settings, "QQ_PUSH_MIN_INTERVAL_SECONDS", 60)))
    if min_interval <= 0:
        return 0

    latest_attempt_at = (
        QQPushDelivery.objects.filter(target=delivery.target, last_attempt_at__isnull=False)
        .order_by("-last_attempt_at")
        .values_list("last_attempt_at", flat=True)
        .first()
    )
    if latest_attempt_at is None:
        return 0

    elapsed = (timezone.now() - latest_attempt_at).total_seconds()
    if elapsed >= min_interval:
        return 0
    return max(1, math.ceil(min_interval - elapsed))


def _is_stale_sending(delivery: QQPushDelivery) -> bool:
    if delivery.status != QQPushDeliveryStatus.SENDING:
        return False
    if delivery.last_attempt_at is None:
        return True
    return delivery.last_attempt_at <= timezone.now() - timedelta(seconds=_sending_stale_after())


def _claim_delivery_attempt(delivery: QQPushDelivery, *, message: str, public_url: str) -> bool:
    stale_cutoff = timezone.now() - timedelta(seconds=_sending_stale_after())
    claimable_status = Q(
        status__in=[
            QQPushDeliveryStatus.PENDING,
            QQPushDeliveryStatus.RETRYING,
            QQPushDeliveryStatus.FAILED,
            QQPushDeliveryStatus.SKIPPED,
        ]
    )
    stale_sending = Q(status=QQPushDeliveryStatus.SENDING) & (
        Q(last_attempt_at__lte=stale_cutoff) | Q(last_attempt_at__isnull=True)
    )
    locked = QQPushDelivery.objects.filter(
        Q(pk=delivery.pk),
        claimable_status | stale_sending,
        attempt_count__lt=F("max_attempts"),
    ).update(
        status=QQPushDeliveryStatus.SENDING,
        attempt_count=F("attempt_count") + 1,
        last_attempt_at=timezone.now(),
        request_payload={"message": message, "public_url": public_url},
    )
    return bool(locked)


def process_qq_push_delivery(delivery: QQPushDelivery) -> QQPushDelivery:
    if delivery.status == QQPushDeliveryStatus.SENT:
        return delivery
    if delivery.status == QQPushDeliveryStatus.SENDING and not _is_stale_sending(delivery):
        return delivery
    if delivery.attempt_count >= delivery.max_attempts:
        delivery.status = QQPushDeliveryStatus.FAILED
        delivery.save(update_fields=["status", "updated_at"])
        return delivery

    article = delivery.article
    eligibility = should_push_news_to_qq(article, target=delivery.target)
    if not eligibility.allowed:
        return _set_delivery_not_eligible(delivery, reason=eligibility.reason or "not_eligible")

    public_url = build_public_article_url(article)
    message = build_qq_auto_push_message(article, public_url=public_url)
    pusher = BotPusher()
    online, status_error = pusher.is_online()
    if not online:
        return _set_delivery_failure(
            delivery,
            error_type=QQPushErrorType.SEND_FAILED,
            error=status_error or "onebot_offline",
        )

    if not _claim_delivery_attempt(delivery, message=message, public_url=public_url):
        delivery.refresh_from_db()
        return delivery

    delivery.refresh_from_db()
    accessible, error = is_public_url_accessible(public_url)
    if not accessible:
        return _set_delivery_failure(
            delivery,
            error_type=QQPushErrorType.URL_UNAVAILABLE,
            error=error or "public URL unavailable",
        )

    try:
        response = pusher.send_group_message(delivery.target.group_id, message)
    except Exception as exc:
        delivery.refresh_from_db()
        return _set_delivery_failure(
            delivery,
            error_type=QQPushErrorType.SEND_FAILED,
            error=str(exc) or exc.__class__.__name__,
        )

    delivery.status = QQPushDeliveryStatus.SENT
    delivery.response_payload = response
    delivery.message_id = _message_id_from_response(response)
    delivery.last_error_type = ""
    delivery.last_error = ""
    delivery.sent_at = timezone.now()
    delivery.save(
        update_fields=[
            "status",
            "response_payload",
            "message_id",
            "last_error_type",
            "last_error",
            "sent_at",
            "updated_at",
        ]
    )
    return delivery


def enqueue_qq_auto_push_for_article(article_id: int) -> None:
    if not getattr(settings, "QQ_PUSH_ENABLED", False):
        return
    from stable.tasks import qq_auto_push_article_task

    transaction.on_commit(lambda: qq_auto_push_article_task.delay(article_id))
