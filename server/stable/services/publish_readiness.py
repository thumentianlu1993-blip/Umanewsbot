from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone
from django.conf import settings
from django.db.models import Count, Min, Q

from stable.models import AutomationStatus, NewsArticle, WorkflowStatus


def transition_to_publish_ready(
    article: NewsArticle,
    *,
    ready_at: datetime | None = None,
    refresh_ready_at: bool = False,
) -> bool:
    """Apply the single publish-ready transition and report timestamp changes.

    Historical rows deliberately keep a NULL timestamp until an explicitly
    reviewed recovery asks to refresh it. Re-validating an already-ready row
    therefore never makes old content look new by accident.
    """

    was_ready = article.automation_status == AutomationStatus.PUBLISH_READY
    article.automation_status = AutomationStatus.PUBLISH_READY
    if was_ready and not refresh_ready_at:
        return False
    article.publish_ready_at = ready_at or timezone.now()
    return True


def publish_ready_age_summary(queryset, *, now=None) -> dict:
    now = now or timezone.now()
    auto_hours = max(1, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_AUTO_HOURS", 24)))
    review_hours = max(auto_hours, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_REVIEW_HOURS", 72)))
    auto_cutoff = now - timedelta(hours=auto_hours)
    review_cutoff = now - timedelta(hours=review_hours)
    ready = queryset.filter(automation_status=AutomationStatus.PUBLISH_READY).exclude(
        workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED]
    )
    counts = ready.aggregate(
        auto_0_24h=Count(
            "id",
            filter=Q(publish_ready_at__gte=auto_cutoff, publish_ready_at__lte=now),
        ),
        review_24_72h=Count(
            "id",
            filter=Q(publish_ready_at__gte=review_cutoff, publish_ready_at__lt=auto_cutoff),
        ),
        expired_over_72h=Count("id", filter=Q(publish_ready_at__lt=review_cutoff)),
        legacy_missing=Count("id", filter=Q(publish_ready_at__isnull=True)),
        oldest_publish_ready_at=Min("publish_ready_at"),
    )
    oldest = counts["oldest_publish_ready_at"]
    return {
        "auto_0_24h": counts["auto_0_24h"],
        "review_24_72h": counts["review_24_72h"],
        "expired_over_72h": counts["expired_over_72h"],
        "legacy_missing": counts["legacy_missing"],
        "oldest_publish_ready_at": oldest,
        "oldest_age_minutes": int(max(0, (now - oldest).total_seconds()) // 60) if oldest else None,
        "auto_hours": auto_hours,
        "review_hours": review_hours,
    }
