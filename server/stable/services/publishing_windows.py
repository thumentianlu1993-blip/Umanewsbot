from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    AutomationStatus,
    NewsArticle,
    ProductionWindow,
    QuotaLedger,
    QuotaLedgerKind,
    QuotaLedgerScope,
    WindowCandidateDecision,
    WindowDecisionStatus,
    WorkflowStatus,
)
from stable.services.automation import is_ready_for_auto_publish
from stable.services.news_attribution import article_region_set, filter_articles_visible_in_region


@dataclass(frozen=True)
class PublishSelectionResult:
    selected: list[NewsArticle]
    zero_reasons: list[str] = field(default_factory=list)
    pool: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CandidatePool:
    articles: list[NewsArticle]
    channels: dict[int, tuple[str, ...]]
    summary: dict


def content_fingerprint(article: NewsArticle) -> str:
    text = f"{article.effective_title}\n{article.effective_summary}"
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hard_gate_article(article: NewsArticle) -> tuple[bool, str]:
    if is_ready_for_auto_publish(article):
        return True, "ready"
    return False, "hard_gate_blocked"


def _realtime_candidate_queryset(region: str, *, now):
    lookback_hours = int(getattr(settings, "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", 3))
    cutoff = now - timedelta(hours=lookback_hours)
    queryset = (
        NewsArticle.objects.all()
        .filter(Q(first_seen_at__gte=cutoff) | Q(ranked_revived_at__gte=cutoff))
        .exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED])
        .order_by("-score_total", "-quality_score", "-ranked_revived_at", "-first_seen_at", "id")
    )
    return filter_articles_visible_in_region(queryset, region)


def _backlog_enabled_for_region(region: str) -> bool:
    if not bool(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_ENABLED", False)):
        return False
    return region in set(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_ALLOWED_REGIONS", []))


def _backlog_candidate_queryset(region: str, *, now):
    auto_hours = max(1, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_AUTO_HOURS", 24)))
    cutoff = now - timedelta(hours=auto_hours)
    return (
        NewsArticle.objects.filter(
            racing_region=region,
            automation_status=AutomationStatus.PUBLISH_READY,
            publish_ready_at__gte=cutoff,
            publish_ready_at__lte=now,
        )
        .exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED])
        .filter(published_to_web_at__isnull=True)
        .order_by("-score_total", "-quality_score", "publish_ready_at", "id")
    )


def _bounded_rows(queryset, *, limit: int) -> tuple[list[NewsArticle], bool]:
    rows = list(queryset[: limit + 1])
    return rows[:limit], len(rows) > limit


def _candidate_sort_key(article: NewsArticle, *, now):
    ready_at = article.publish_ready_at or now
    recent_at = article.ranked_revived_at or article.first_seen_at or now
    return (-article.score_total, -article.quality_score, ready_at, -recent_at.timestamp(), article.id)


def build_candidate_pool(region: str, *, now) -> CandidatePool:
    realtime_limit = max(1, int(getattr(settings, "MULTIREGION_PUBLISH_REALTIME_SCAN_LIMIT", 200)))
    backlog_limit = max(1, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_SCAN_LIMIT", 200)))
    realtime, realtime_truncated = _bounded_rows(
        _realtime_candidate_queryset(region, now=now),
        limit=realtime_limit,
    )
    backlog_enabled = _backlog_enabled_for_region(region)
    backlog: list[NewsArticle] = []
    backlog_truncated = False
    if backlog_enabled:
        backlog, backlog_truncated = _bounded_rows(
            _backlog_candidate_queryset(region, now=now),
            limit=backlog_limit,
        )

    merged: dict[int, NewsArticle] = {}
    channels: dict[int, set[str]] = {}
    for channel, articles in (("realtime", realtime), ("backlog", backlog)):
        for article in articles:
            merged.setdefault(article.id, article)
            channels.setdefault(article.id, set()).add(channel)
    articles = sorted(merged.values(), key=lambda article: _candidate_sort_key(article, now=now))
    summary = {
        "realtime_limit": realtime_limit,
        "realtime_loaded": len(realtime),
        "realtime_truncated": realtime_truncated,
        "backlog_enabled": backlog_enabled,
        "backlog_limit": backlog_limit,
        "backlog_loaded": len(backlog),
        "backlog_truncated": backlog_truncated,
        "merged_count": len(articles),
    }
    return CandidatePool(
        articles=articles,
        channels={article_id: tuple(sorted(values)) for article_id, values in channels.items()},
        summary=summary,
    )


def publish_ready_age_payload(article: NewsArticle, *, now) -> dict:
    if article.publish_ready_at is None:
        return {
            "publish_ready_at": "",
            "publish_ready_age_minutes": None,
            "publish_ready_age_tier": "legacy_missing",
        }
    age = max(timedelta(0), now - article.publish_ready_at)
    age_hours = age.total_seconds() / 3600
    auto_hours = max(1, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_AUTO_HOURS", 24)))
    review_hours = max(auto_hours, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_REVIEW_HOURS", 72)))
    if age_hours <= auto_hours:
        tier = "auto"
    elif age_hours <= review_hours:
        tier = "manual_review"
    else:
        tier = "expired"
    return {
        "publish_ready_at": article.publish_ready_at.isoformat(),
        "publish_ready_age_minutes": int(age.total_seconds() // 60),
        "publish_ready_age_tier": tier,
    }


def _pool_candidate_extra(pool: CandidatePool, article: NewsArticle) -> dict:
    return {
        "candidate_channels": list(pool.channels.get(article.id, ())),
        "realtime_truncated": pool.summary["realtime_truncated"],
        "backlog_truncated": pool.summary["backlog_truncated"],
    }


def _candidate_payload(article: NewsArticle, *, now=None, extra: dict | None = None) -> dict:
    now = now or timezone.now()
    revival = (article.decision_reason or {}).get("ranked_revival") or {}
    payload = {
        "ranked_revival": bool(article.ranked_revived_at),
        "ranked_revived_at": article.ranked_revived_at.isoformat() if article.ranked_revived_at else "",
        "ranked_revival_source_site": revival.get("source_site", ""),
        "ranked_revival_source_mode": revival.get("source_mode", ""),
        "primary_region": article.racing_region,
        "visible_regions": sorted(article_region_set(article)),
        **publish_ready_age_payload(article, now=now),
    }
    if extra:
        payload.update(extra)
    return payload


def _record_candidate(
    *,
    window: ProductionWindow,
    article: NewsArticle,
    status: str,
    reason: str,
    rank: int | None = None,
    payload: dict | None = None,
) -> None:
    WindowCandidateDecision.objects.update_or_create(
        window=window,
        article=article,
        defaults={
            "status": status,
            "reason": reason,
            "score": article.score_total,
            "rank": rank,
            "payload": payload or {},
        },
    )


def _reserve_site_hour_quota(*, window: ProductionWindow, count: int) -> tuple[bool, str]:
    limit = (
        int(getattr(settings, "MULTIREGION_PUBLISH_SITE_HOURLY_MAX_MAJOR_RACE", 120))
        if window.mode == "major_race"
        else int(getattr(settings, "MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY", 60))
    )
    hour_start = window.window_start.replace(minute=0, second=0, microsecond=0)
    with transaction.atomic():
        ledger, _created = QuotaLedger.objects.select_for_update().get_or_create(
            kind=QuotaLedgerKind.WEB_PUBLISH,
            scope=QuotaLedgerScope.SITE_HOUR,
            scope_key="site",
            window_start=hour_start,
            defaults={"limit": limit, "used": 0},
        )
        ledger.limit = limit
        if ledger.used + count > limit:
            ledger.save(update_fields=["limit", "updated_at"])
            return False, "site_hour_quota_exhausted"
        ledger.used += count
        ledger.save(update_fields=["limit", "used", "updated_at"])
        return True, "reserved"


def _mark_soft_fill(article: NewsArticle) -> None:
    reason = dict(article.decision_reason or {})
    reason["region_minimum_fill"] = True
    reason["disable_auto_qq"] = True
    article.decision_reason = reason
    article.save(update_fields=["decision_reason", "updated_at"])


def select_publish_candidates(region: str, *, window: ProductionWindow, now=None) -> PublishSelectionResult:
    now = now or timezone.now()
    max_count = int(getattr(settings, "MULTIREGION_PUBLISH_REGION_WINDOW_MAX", 5))
    min_count = int(getattr(settings, "MULTIREGION_PUBLISH_REGION_WINDOW_MIN", 1))
    soft_min_score = int(getattr(settings, "MULTIREGION_PUBLISH_SOFT_FILL_MIN_SCORE", 45))
    normal_threshold = int(getattr(settings, "AUTO_REVIEW_THRESHOLD", 75))

    ready: list[NewsArticle] = []
    blocking_reasons: list[str] = []
    fingerprints: dict[str, NewsArticle] = {}
    pool = build_candidate_pool(region, now=now)
    for article in pool.articles:
        candidate_extra = _pool_candidate_extra(pool, article)
        if article.racing_region != region:
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.SKIPPED,
                reason="related_region_waiting_primary_region",
                payload=_candidate_payload(article, now=now, extra=candidate_extra),
            )
            blocking_reasons.append("related_region_visible")
            continue
        age_payload = publish_ready_age_payload(article, now=now)
        if article.automation_status == AutomationStatus.PUBLISH_READY and age_payload["publish_ready_age_tier"] in {
            "legacy_missing",
            "manual_review",
            "expired",
        }:
            allowed = False
            reason = f"publish_ready_{age_payload['publish_ready_age_tier']}"
        else:
            allowed, reason = hard_gate_article(article)
        if not allowed:
            if article.published_at_verified is False:
                reason = "published_at_unverified"
            elif article.translation_retry_exhausted_at:
                reason = "translation_retry_exhausted"
            elif article.translation_next_retry_at:
                reason = "translation_retry_waiting"
            elif article.attribution_status == "needs_review":
                reason = "attribution_needs_review"
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.BLOCKED,
                reason=reason,
                payload=_candidate_payload(article, now=now, extra=candidate_extra),
            )
            blocking_reasons.append(reason)
            continue
        fingerprint = content_fingerprint(article)
        previous = fingerprints.get(fingerprint)
        if previous is not None:
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.SKIPPED,
                reason="dedupe_loser",
                payload=_candidate_payload(
                    article,
                    now=now,
                    extra={**candidate_extra, "winner_article_id": previous.id, "fingerprint": fingerprint},
                ),
            )
            continue
        fingerprints[fingerprint] = article
        ready.append(article)

    normal = [article for article in ready if article.score_total >= normal_threshold]
    soft_fill = [article for article in ready if soft_min_score <= article.score_total < normal_threshold]
    selected = normal[:max_count]
    if len(selected) < min_count and soft_fill:
        fill_count = min(max_count - len(selected), min_count - len(selected))
        for article in soft_fill[:fill_count]:
            _mark_soft_fill(article)
        selected.extend(soft_fill[:fill_count])

    selected_ids = {article.id for article in selected}
    if selected:
        reserved, quota_reason = _reserve_site_hour_quota(window=window, count=len(selected))
        if not reserved:
            for article in selected:
                _record_candidate(
                    window=window,
                    article=article,
                    status=WindowDecisionStatus.SKIPPED,
                    reason=quota_reason,
                    payload=_candidate_payload(article, now=now, extra=_pool_candidate_extra(pool, article)),
                )
            return PublishSelectionResult(selected=[], zero_reasons=[quota_reason], pool=pool.summary)

    for rank, article in enumerate(selected, start=1):
        _record_candidate(
            window=window,
            article=article,
            status=WindowDecisionStatus.SELECTED,
            reason="region_minimum_fill" if article.decision_reason.get("region_minimum_fill") else "selected",
            rank=rank,
            payload=_candidate_payload(article, now=now, extra=_pool_candidate_extra(pool, article)),
        )
    for article in ready:
        if article.id not in selected_ids:
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.SKIPPED,
                reason="region_window_limit" if len(selected) >= max_count else "below_min_score",
                payload=_candidate_payload(
                    article,
                    now=now,
                    extra=_pool_candidate_extra(pool, article),
                ),
            )

    zero_reasons: list[str] = []
    if not selected:
        if not ready:
            zero_reasons.extend(list(dict.fromkeys(blocking_reasons)) or ["no_ready_candidates"])
        else:
            zero_reasons.append("all_candidates_below_min_score")
    return PublishSelectionResult(selected=selected, zero_reasons=zero_reasons, pool=pool.summary)
