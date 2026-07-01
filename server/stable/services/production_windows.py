from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable.models import (
    MajorRaceEvent,
    NewsSource,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowStatus,
    RacingRegion,
    SourceErrorCategory,
    SourceKind,
)


@dataclass(frozen=True)
class WindowBounds:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class WindowClaim:
    claimed: bool
    window: ProductionWindow
    reason: str = ""


@dataclass(frozen=True)
class MajorRaceWindow:
    region: str
    start: datetime
    end: datetime
    events: list[MajorRaceEvent]


@dataclass(frozen=True)
class SourceSelectionItem:
    source: NewsSource
    reason: str


@dataclass(frozen=True)
class SourceSelection:
    selected: list[SourceSelectionItem]
    skipped: list[SourceSelectionItem]


BLOCKED_ERROR_CATEGORIES = {
    SourceErrorCategory.HTTP_403,
    SourceErrorCategory.HTTP_429,
    SourceErrorCategory.CAPTCHA_OR_BLOCKED,
}


def classify_source_error(
    *,
    status_code: int | None = None,
    message: str = "",
    empty_success: bool = False,
) -> str:
    if empty_success:
        return SourceErrorCategory.EMPTY_SUCCESS
    if status_code == 403:
        return SourceErrorCategory.HTTP_403
    if status_code == 429:
        return SourceErrorCategory.HTTP_429
    if status_code and status_code >= 500:
        return SourceErrorCategory.SERVER_ERROR
    normalized = message.lower()
    if "captcha" in normalized or "blocked" in normalized or "forbidden" in normalized:
        return SourceErrorCategory.CAPTCHA_OR_BLOCKED
    if "timeout" in normalized or "timed out" in normalized:
        return SourceErrorCategory.TIMEOUT
    if "parse" in normalized or "解析" in normalized:
        return SourceErrorCategory.PARSE_ERROR
    return SourceErrorCategory.UNKNOWN


def current_window_bounds(now: datetime | None = None, *, minutes: int) -> WindowBounds:
    now = now or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, timezone=dt_timezone.utc)
    now = now.astimezone(dt_timezone.utc)
    minute = (now.minute // minutes) * minutes
    start = now.replace(minute=minute, second=0, microsecond=0)
    return WindowBounds(start=start, end=start + timedelta(minutes=minutes))


def due_window_starts(
    *,
    last_window_start: datetime | None,
    now: datetime | None = None,
    minutes: int,
    lookback_hours: int | None = None,
) -> list[datetime]:
    now = now or timezone.now()
    lookback_hours = int(
        lookback_hours
        if lookback_hours is not None
        else getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_LOOKBACK_HOURS", 3)
    )
    current = current_window_bounds(now, minutes=minutes).start
    earliest = current - timedelta(hours=max(0, lookback_hours))
    if last_window_start is None:
        start = earliest
    else:
        if timezone.is_naive(last_window_start):
            last_window_start = timezone.make_aware(last_window_start, timezone=dt_timezone.utc)
        start = max(last_window_start.astimezone(dt_timezone.utc) + timedelta(minutes=minutes), earliest)
    starts: list[datetime] = []
    cursor = start
    while cursor < current:
        starts.append(cursor)
        cursor += timedelta(minutes=minutes)
    return starts


def claim_window(
    window: ProductionWindow,
    *,
    now: datetime | None = None,
    lease_minutes: int | None = None,
) -> WindowClaim:
    now = now or timezone.now()
    lease_minutes = int(
        lease_minutes
        if lease_minutes is not None
        else getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_LEASE_MINUTES", 30)
    )
    with transaction.atomic():
        locked = ProductionWindow.objects.select_for_update().get(pk=window.pk)
        if locked.status == ProductionWindowStatus.SUCCEEDED:
            return WindowClaim(False, locked, "already_succeeded")
        if (
            locked.status == ProductionWindowStatus.RUNNING
            and locked.lease_expires_at
            and locked.lease_expires_at > now
        ):
            return WindowClaim(False, locked, "lease_active")
        locked.status = ProductionWindowStatus.RUNNING
        locked.claimed_at = now
        locked.started_at = locked.started_at or now
        locked.lease_expires_at = now + timedelta(minutes=lease_minutes)
        locked.attempt_count += 1
        locked.save(
            update_fields=[
                "status",
                "claimed_at",
                "started_at",
                "lease_expires_at",
                "attempt_count",
                "updated_at",
            ]
        )
        return WindowClaim(True, locked, "claimed")


def update_major_race_boost_window(event: MajorRaceEvent) -> MajorRaceEvent:
    local_zone = ZoneInfo(event.timezone_name)
    if event.local_start_time:
        local_start = datetime.combine(event.local_date, event.local_start_time, tzinfo=local_zone)
        boost_start = local_start - timedelta(hours=3)
        boost_end = local_start + timedelta(hours=1)
    else:
        boost_start = datetime.combine(event.local_date, time.min, tzinfo=local_zone)
        boost_end = boost_start + timedelta(days=1)
    event.boost_start_at = boost_start.astimezone(dt_timezone.utc)
    event.boost_end_at = boost_end.astimezone(dt_timezone.utc)
    event.save(update_fields=["boost_start_at", "boost_end_at", "updated_at"])
    return event


def active_major_race_window(region: str, *, now: datetime | None = None) -> MajorRaceWindow | None:
    now = now or timezone.now()
    events = list(
        MajorRaceEvent.objects.filter(
            racing_region=region,
            is_active=True,
            boost_start_at__lte=now,
            boost_end_at__gt=now,
        ).order_by("boost_start_at", "boost_end_at", "id")
    )
    if not events:
        return None
    return MajorRaceWindow(
        region=region,
        start=min(event.boost_start_at for event in events if event.boost_start_at),
        end=max(event.boost_end_at for event in events if event.boost_end_at),
        events=events,
    )


def _source_key(source: NewsSource) -> str:
    return f"{source.source_site}:{source.source_mode}"


def _source_interval_minutes(source: NewsSource) -> int:
    if source.effective_crawl_interval_minutes:
        return int(source.effective_crawl_interval_minutes)
    if source.production_approved:
        return int(getattr(settings, "MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES", 15))
    return int(source.crawl_interval_minutes)


def _has_active_crawl_window(source: NewsSource, *, now: datetime) -> bool:
    return ProductionWindow.objects.filter(
        kind=ProductionWindowKind.CRAWL,
        source=source,
        status=ProductionWindowStatus.RUNNING,
        lease_expires_at__gt=now,
    ).exists()


def select_production_sources(
    *,
    now: datetime | None = None,
    allowed_regions: set[str] | None = None,
    allowed_sources: set[str] | None = None,
    max_sources: int | None = None,
) -> SourceSelection:
    now = now or timezone.now()
    allowed_regions = allowed_regions or set(getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS", []))
    allowed_sources = allowed_sources or set()
    max_sources = max_sources if max_sources is not None else getattr(settings, "MULTIREGION_CRAWL_MAX_SOURCES_PER_TICK", 50)

    queryset = (
        NewsSource.objects.filter(enabled=True, deleted_at__isnull=True)
        .exclude(source_kind=SourceKind.DATABASE)
        .order_by("-priority", "id")
    )
    selected: list[SourceSelectionItem] = []
    skipped: list[SourceSelectionItem] = []
    due: list[SourceSelectionItem] = []

    for source in queryset:
        if allowed_regions and source.racing_region not in allowed_regions:
            skipped.append(SourceSelectionItem(source, "region_not_allowed"))
            continue
        if allowed_sources and _source_key(source) not in allowed_sources and str(source.id) not in allowed_sources:
            skipped.append(SourceSelectionItem(source, "source_not_allowed"))
            continue
        if not source.production_approved:
            skipped.append(SourceSelectionItem(source, "production_not_approved"))
            continue
        if source.manual_pause_reason:
            skipped.append(SourceSelectionItem(source, "manual_pause"))
            continue
        if source.backoff_until and source.backoff_until > now:
            skipped.append(SourceSelectionItem(source, "backoff_active"))
            continue
        if _has_active_crawl_window(source, now=now):
            skipped.append(SourceSelectionItem(source, "crawl_window_running"))
            continue
        interval = _source_interval_minutes(source)
        if source.last_crawl_at and source.last_crawl_at > now - timedelta(minutes=interval):
            skipped.append(SourceSelectionItem(source, "not_due"))
            continue
        due.append(SourceSelectionItem(source, "never_run" if source.last_crawl_at is None else "due"))

    selected = due[: max(0, int(max_sources))]
    skipped.extend(due[max(0, int(max_sources)) :])
    return SourceSelection(selected=selected, skipped=skipped)


def record_source_crawl_result(
    source: NewsSource,
    *,
    success: bool,
    error_category: str = "",
    now: datetime | None = None,
) -> NewsSource:
    now = now or timezone.now()
    default_interval = int(getattr(settings, "MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES", 15))
    failures_to_backoff = int(getattr(settings, "MULTIREGION_CRAWL_FAILURES_TO_BACKOFF", 3))
    successes_to_recover = int(getattr(settings, "MULTIREGION_CRAWL_SUCCESSES_TO_RECOVER", 3))
    normal_backoff = int(getattr(settings, "MULTIREGION_CRAWL_BACKOFF_MINUTES", 60))
    blocked_backoff = int(getattr(settings, "MULTIREGION_CRAWL_BLOCKED_BACKOFF_MINUTES", 360))

    if success:
        source.success_streak += 1
        source.failure_streak = 0
        source.last_error_category = ""
        if source.success_streak >= successes_to_recover:
            source.backoff_until = None
            source.effective_crawl_interval_minutes = default_interval
    else:
        source.failure_streak += 1
        source.success_streak = 0
        source.last_error_category = error_category or SourceErrorCategory.UNKNOWN
        if source.failure_streak >= failures_to_backoff:
            backoff_minutes = blocked_backoff if source.last_error_category in BLOCKED_ERROR_CATEGORIES else normal_backoff
            source.backoff_until = now + timedelta(minutes=backoff_minutes)
            source.effective_crawl_interval_minutes = max(_source_interval_minutes(source), normal_backoff)

    source.last_crawl_at = now
    source.save(
        update_fields=[
            "success_streak",
            "failure_streak",
            "last_error_category",
            "backoff_until",
            "effective_crawl_interval_minutes",
            "last_crawl_at",
            "updated_at",
        ]
    )
    return source
