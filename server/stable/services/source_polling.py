from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from stable.models import CrawlJob, NewsSource, SourceKind, SourceMode, SourceSite, TaskStatus
from stable.services.source_permissions import permission_audit_reason_for_source


FIXED_SCHEDULE_SOURCES = {
    (SourceSite.NETKEIBA, SourceMode.LATEST),
    (SourceSite.NETKEIBA, SourceMode.ACCESS),
    (SourceSite.NETKEIBA, SourceMode.ATTENTION),
    (SourceSite.JRA, SourceMode.OFFICIAL),
}


@dataclass(frozen=True)
class SourcePollItem:
    source: NewsSource
    reason: str


@dataclass(frozen=True)
class SourcePollSelection:
    selected: list[SourcePollItem]
    skipped: list[SourcePollItem]
    deferred: list[SourcePollItem]

    @property
    def deferred_count(self) -> int:
        return len(self.deferred)


def _setting_list(name: str) -> set[str]:
    value = getattr(settings, name, [])
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    return {str(item).strip() for item in value if str(item).strip()}


def source_poll_key(source: NewsSource) -> str:
    return f"{source.source_site}:{source.source_mode}"


def is_fixed_schedule_source(source: NewsSource) -> bool:
    return (source.source_site, source.source_mode) in FIXED_SCHEDULE_SOURCES


def _latest_job(source: NewsSource) -> CrawlJob | None:
    return source.crawl_jobs.order_by("-started_at", "-id").first()


def _latest_completed_at(source: NewsSource) -> object | None:
    latest_completed = (
        source.crawl_jobs.exclude(status=TaskStatus.STARTED)
        .order_by("-started_at", "-id")
        .values_list("finished_at", flat=True)
        .first()
    )
    return latest_completed or source.last_crawl_at


def _is_running(source: NewsSource, *, now, running_timeout_minutes: int) -> tuple[bool, bool]:
    latest = _latest_job(source)
    if latest is None or latest.status != TaskStatus.STARTED:
        return False, False
    stale = latest.started_at <= now - timedelta(minutes=running_timeout_minutes)
    return True, stale


def select_due_enabled_news_sources(
    *,
    now=None,
    max_sources: int | None = None,
    allowed_regions: set[str] | None = None,
    allowed_sources: set[str] | None = None,
) -> SourcePollSelection:
    now = now or timezone.now()
    max_sources = max(0, int(max_sources if max_sources is not None else getattr(settings, "NEWS_SOURCE_POLL_MAX_SOURCES", 3)))
    allowed_regions = allowed_regions if allowed_regions is not None else _setting_list("NEWS_SOURCE_POLL_ALLOWED_REGIONS")
    allowed_sources = allowed_sources if allowed_sources is not None else _setting_list("NEWS_SOURCE_POLL_ALLOWED_SOURCES")
    running_timeout_minutes = max(1, int(getattr(settings, "NEWS_SOURCE_POLL_RUNNING_TIMEOUT_MINUTES", 60)))
    retry_stale_running = bool(getattr(settings, "NEWS_SOURCE_POLL_RETRY_STALE_RUNNING", False))

    queryset = (
        NewsSource.objects.filter(enabled=True, deleted_at__isnull=True)
        .exclude(source_kind=SourceKind.DATABASE)
        .order_by("-priority", "id")
    )
    selected: list[SourcePollItem] = []
    skipped: list[SourcePollItem] = []
    due: list[SourcePollItem] = []

    for source in queryset:
        if is_fixed_schedule_source(source):
            skipped.append(SourcePollItem(source, "fixed_schedule"))
            continue
        if source.production_approved is not True:
            skipped.append(SourcePollItem(source, "production_not_approved"))
            continue
        if allowed_regions and source.racing_region not in allowed_regions:
            skipped.append(SourcePollItem(source, "region_not_allowed"))
            continue
        if allowed_sources and source_poll_key(source) not in allowed_sources and str(source.id) not in allowed_sources:
            skipped.append(SourcePollItem(source, "source_not_allowed"))
            continue
        running, stale_running = _is_running(source, now=now, running_timeout_minutes=running_timeout_minutes)
        if running and (not stale_running or not retry_stale_running):
            skipped.append(SourcePollItem(source, "stale_running" if stale_running else "running"))
            continue
        completed_at = _latest_completed_at(source)
        if completed_at is not None and completed_at > now - timedelta(minutes=source.crawl_interval_minutes):
            skipped.append(SourcePollItem(source, "not_due"))
            continue
        due_reason = "never_run" if completed_at is None else "due"
        permission_reason = permission_audit_reason_for_source(source)
        due.append(
            SourcePollItem(
                source,
                f"{due_reason};{permission_reason}",
            )
        )

    selected = due[:max_sources]
    deferred = due[max_sources:]
    return SourcePollSelection(selected=selected, skipped=skipped, deferred=deferred)
