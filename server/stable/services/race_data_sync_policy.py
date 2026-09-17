from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from stable import models


SOURCE_CLASS_LICENSED_API = "licensed_api"
SOURCE_CLASS_OFFICIAL_OPERATOR = "official_operator"
SOURCE_CLASS_TRUSTED_PUBLISHER = "trusted_publisher"

_SOURCE_CLASS_ALIASES = {
    "licensed_api": SOURCE_CLASS_LICENSED_API,
    "racing_api": SOURCE_CLASS_LICENSED_API,
    "racingapi": SOURCE_CLASS_LICENSED_API,
    "the_racing_api": SOURCE_CLASS_LICENSED_API,
    "official": SOURCE_CLASS_OFFICIAL_OPERATOR,
    "official_operator": SOURCE_CLASS_OFFICIAL_OPERATOR,
    "official_website": SOURCE_CLASS_OFFICIAL_OPERATOR,
    "third_party": SOURCE_CLASS_TRUSTED_PUBLISHER,
    "trusted_publisher": SOURCE_CLASS_TRUSTED_PUBLISHER,
}

_SOURCE_CLASS_PRIORITIES = {
    SOURCE_CLASS_LICENSED_API: 300,
    SOURCE_CLASS_OFFICIAL_OPERATOR: 200,
    SOURCE_CLASS_TRUSTED_PUBLISHER: 100,
}


def normalize_source_class(value: str | None) -> str:
    return _SOURCE_CLASS_ALIASES.get(str(value or "").strip().lower(), "")


def source_priority(value: str | None) -> int:
    return _SOURCE_CLASS_PRIORITIES.get(normalize_source_class(value), 0)


@dataclass(frozen=True)
class SourceArbitrationDecision:
    apply: bool
    reason_code: str
    candidate_priority: int
    current_priority: int


def arbitrate_source_value(
    *,
    current_source_key: str,
    current_source_class: str,
    current_observed_at: datetime | None,
    candidate_source_key: str,
    candidate_source_class: str,
    candidate_observed_at: datetime | None,
    has_current_value: bool,
    values_equal: bool,
    manual_locked: bool = False,
) -> SourceArbitrationDecision:
    """Choose one source without requiring per-race human confirmation.

    Class priority is authoritative.  Equal-class sources use observation time,
    then the provider key as a stable final tie-breaker so repeated runs cannot
    oscillate between two otherwise equal observations.
    """

    candidate_priority = source_priority(candidate_source_class)
    current_priority = source_priority(current_source_class)
    base = {
        "candidate_priority": candidate_priority,
        "current_priority": current_priority,
    }
    if manual_locked:
        return SourceArbitrationDecision(False, "manual_lock", **base)
    if not candidate_source_key or candidate_priority == 0:
        return SourceArbitrationDecision(False, "source_class_not_eligible", **base)
    if not has_current_value:
        return SourceArbitrationDecision(True, "empty_field", **base)
    if candidate_priority > current_priority:
        return SourceArbitrationDecision(True, "higher_priority_source", **base)
    if candidate_priority < current_priority:
        return SourceArbitrationDecision(False, "lower_priority_source", **base)

    current_key = str(current_source_key or "").strip()
    candidate_key = str(candidate_source_key or "").strip()
    if current_key == candidate_key:
        if values_equal:
            return SourceArbitrationDecision(False, "idempotent_replay", **base)
        if current_observed_at and candidate_observed_at:
            if candidate_observed_at > current_observed_at:
                return SourceArbitrationDecision(True, "newer_same_source", **base)
            return SourceArbitrationDecision(False, "stale_same_source", **base)
        return SourceArbitrationDecision(True, "same_source_refresh", **base)

    if current_observed_at and candidate_observed_at:
        if candidate_observed_at > current_observed_at:
            return SourceArbitrationDecision(True, "newer_equal_priority_source", **base)
        if candidate_observed_at < current_observed_at:
            return SourceArbitrationDecision(False, "older_equal_priority_source", **base)
    elif candidate_observed_at and not current_observed_at:
        return SourceArbitrationDecision(True, "dated_equal_priority_source", **base)
    elif current_observed_at and not candidate_observed_at:
        return SourceArbitrationDecision(False, "undated_equal_priority_source", **base)

    if not current_key or candidate_key < current_key:
        return SourceArbitrationDecision(True, "stable_provider_tiebreak", **base)
    return SourceArbitrationDecision(False, "stable_provider_tiebreak", **base)


def calculate_next_poll_at(
    *,
    data_kind: str,
    now: datetime,
    race_datetime: datetime | None,
    local_date: date | None = None,
    timezone_name: str = "UTC",
    result_confirmed: bool = False,
    event_terminal: bool = False,
) -> datetime | None:
    """Return the next dynamic checkpoint for one race-data kind.

    Pre-race checks follow local calendar days (D-4: 3h, D-1: 1h, D: 10m).  Results use explicit T+ checkpoints and retain a correction
    watch after the first confirmed result.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if race_datetime is not None and (
        race_datetime.tzinfo is None or race_datetime.utcoffset() is None
    ):
        raise ValueError("race_datetime must be timezone-aware")
    if data_kind not in models.RaceDataSyncDataKind.values:
        raise ValueError("unsupported race data kind")
    if event_terminal:
        return None

    if data_kind in {models.RaceDataSyncDataKind.RACE_TIME, models.RaceDataSyncDataKind.RACECARD}:
        zone = ZoneInfo(timezone_name)
        today = now.astimezone(zone).date()
        race_date = local_date or (race_datetime.astimezone(zone).date() if race_datetime else None)
        if race_date is None:
            return now + timedelta(hours=12)
        offset = (race_date - today).days
        if offset < 0 or (race_datetime and now >= race_datetime + timedelta(minutes=5)):
            return None
        interval = timedelta(hours=12 if offset > 4 else 3 if offset >= 2 else 1) if offset else timedelta(minutes=10)
        due = now + interval
        # Enter the faster tier on its local midnight, including date-only events.
        next_boundary = datetime.combine(today + timedelta(days=1), time(), tzinfo=zone)
        if offset in {1, 2, 5}:
            due = min(due, next_boundary)
        if race_datetime is not None:
            due = min(due, race_datetime + timedelta(minutes=5))
        elif offset == 0:
            due = min(due, next_boundary)
        return due

    if race_datetime is None:
        return None
    result_window_start = race_datetime + timedelta(minutes=3)
    if now < result_window_start:
        return result_window_start
    elapsed = now - race_datetime
    if result_confirmed:
        if elapsed < timedelta(days=2):
            return now + timedelta(hours=6)
        if elapsed < timedelta(days=7):
            return now + timedelta(days=1)
        return None

    for minutes in (5, 10, 15, 20, 25, 30):
        checkpoint = race_datetime + timedelta(minutes=minutes)
        if now < checkpoint:
            return checkpoint
    if elapsed < timedelta(hours=2):
        return now + timedelta(minutes=15)
    if elapsed < timedelta(hours=6):
        return now + timedelta(minutes=30)
    if elapsed < timedelta(days=1):
        return now + timedelta(hours=3)
    if elapsed < timedelta(days=7):
        return now + timedelta(hours=6)
    return now + timedelta(days=1)
