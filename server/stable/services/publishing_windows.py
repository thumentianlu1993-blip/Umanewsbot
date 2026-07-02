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


@dataclass(frozen=True)
class PublishSelectionResult:
    selected: list[NewsArticle]
    zero_reasons: list[str] = field(default_factory=list)


def content_fingerprint(article: NewsArticle) -> str:
    text = f"{article.effective_title}\n{article.effective_summary}"
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hard_gate_article(article: NewsArticle) -> tuple[bool, str]:
    if is_ready_for_auto_publish(article):
        return True, "ready"
    return False, "hard_gate_blocked"


def _candidate_queryset(region: str, *, now):
    lookback_hours = int(getattr(settings, "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", 3))
    cutoff = now - timedelta(hours=lookback_hours)
    return (
        NewsArticle.objects.filter(
            racing_region=region,
        )
        .filter(Q(first_seen_at__gte=cutoff) | Q(ranked_revived_at__gte=cutoff))
        .exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED])
        .order_by("-score_total", "-quality_score", "-ranked_revived_at", "-first_seen_at", "id")
    )


def _candidate_payload(article: NewsArticle, *, extra: dict | None = None) -> dict:
    revival = (article.decision_reason or {}).get("ranked_revival") or {}
    payload = {
        "ranked_revival": bool(article.ranked_revived_at),
        "ranked_revived_at": article.ranked_revived_at.isoformat() if article.ranked_revived_at else "",
        "ranked_revival_source_site": revival.get("source_site", ""),
        "ranked_revival_source_mode": revival.get("source_mode", ""),
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
    fingerprints: dict[str, NewsArticle] = {}
    for article in _candidate_queryset(region, now=now):
        allowed, reason = hard_gate_article(article)
        if not allowed:
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.BLOCKED,
                reason=reason,
                payload=_candidate_payload(article),
            )
            continue
        fingerprint = content_fingerprint(article)
        previous = fingerprints.get(fingerprint)
        if previous is not None:
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.SKIPPED,
                reason="dedupe_loser",
                payload=_candidate_payload(article, extra={"winner_article_id": previous.id, "fingerprint": fingerprint}),
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
                    payload=_candidate_payload(article),
                )
            return PublishSelectionResult(selected=[], zero_reasons=[quota_reason])

    for rank, article in enumerate(selected, start=1):
        _record_candidate(
            window=window,
            article=article,
            status=WindowDecisionStatus.SELECTED,
            reason="region_minimum_fill" if article.decision_reason.get("region_minimum_fill") else "selected",
            rank=rank,
            payload=_candidate_payload(article),
        )
    for article in ready:
        if article.id not in selected_ids:
            _record_candidate(
                window=window,
                article=article,
                status=WindowDecisionStatus.SKIPPED,
                reason="region_window_limit" if len(selected) >= max_count else "below_min_score",
                payload=_candidate_payload(article),
            )

    zero_reasons: list[str] = []
    if not selected:
        if not ready:
            zero_reasons.append("no_ready_candidates")
        else:
            zero_reasons.append("all_candidates_below_min_score")
    return PublishSelectionResult(selected=selected, zero_reasons=zero_reasons)
