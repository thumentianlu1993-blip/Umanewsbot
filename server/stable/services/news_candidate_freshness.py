from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


DATE_ONLY_CANDIDATE = "candidate_date_within_one_day"
DATE_ONLY_HISTORICAL = "historical_date_outside_one_day"
PRECISE_TIME_NOT_APPLICABLE = "precise_time_not_applicable"
FRESHNESS_UNRESOLVED = "freshness_unresolved"


@dataclass(frozen=True)
class CandidateFreshnessResult:
    decision: str
    reason: str
    crawled_at: datetime
    source_timezone: str = ""
    published_local_date: date | None = None
    crawled_local_date: date | None = None
    date_difference_days: int | None = None

    @property
    def status(self) -> str:
        return self.decision

    def as_metadata(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "crawled_at": self.crawled_at.isoformat(),
            "source_timezone": self.source_timezone,
            "published_local_date": (
                self.published_local_date.isoformat()
                if self.published_local_date is not None
                else None
            ),
            "crawled_local_date": (
                self.crawled_local_date.isoformat()
                if self.crawled_local_date is not None
                else None
            ),
            "date_difference_days": self.date_difference_days,
        }


def _unresolved(
    *,
    crawled_at: datetime,
    reason: str,
    source_timezone: str = "",
) -> CandidateFreshnessResult:
    return CandidateFreshnessResult(
        decision=FRESHNESS_UNRESOLVED,
        reason=reason,
        crawled_at=crawled_at,
        source_timezone=source_timezone,
    )


def classify_candidate_freshness(
    *,
    published_at: datetime | None,
    published_at_evidence: dict | None,
    published_at_verified: bool | None,
    crawled_at: datetime,
) -> CandidateFreshnessResult:
    """Classify date-only freshness using the source-local calendar dates.

    Date-only values are commonly normalized to local noon.  The normalized
    clock component must therefore never enter an hour-based age calculation.
    """

    evidence = (
        dict(published_at_evidence)
        if isinstance(published_at_evidence, dict)
        else {}
    )
    source_timezone = str(evidence.get("timezone") or "").strip()

    if timezone.is_naive(crawled_at):
        return _unresolved(
            crawled_at=crawled_at,
            reason="naive_crawled_at",
            source_timezone=source_timezone,
        )
    if published_at is None:
        return _unresolved(
            crawled_at=crawled_at,
            reason="published_at_missing",
            source_timezone=source_timezone,
        )
    if timezone.is_naive(published_at):
        return _unresolved(
            crawled_at=crawled_at,
            reason="naive_published_at",
            source_timezone=source_timezone,
        )
    if evidence.get("verified") is not True:
        return _unresolved(
            crawled_at=crawled_at,
            reason="published_at_evidence_unverified",
            source_timezone=source_timezone,
        )
    if published_at_verified is not True:
        return _unresolved(
            crawled_at=crawled_at,
            reason="published_at_unverified",
            source_timezone=source_timezone,
        )

    precision = str(evidence.get("precision") or "").strip().lower()
    try:
        source_zone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return _unresolved(
            crawled_at=crawled_at,
            reason="invalid_published_timezone",
            source_timezone=source_timezone,
        )
    if precision in {"minute", "second"}:
        return CandidateFreshnessResult(
            decision=PRECISE_TIME_NOT_APPLICABLE,
            reason=PRECISE_TIME_NOT_APPLICABLE,
            crawled_at=crawled_at,
            source_timezone=source_timezone,
        )
    if precision != "date":
        return _unresolved(
            crawled_at=crawled_at,
            reason="published_at_precision_missing"
            if not precision
            else "published_at_precision_unknown",
            source_timezone=source_timezone,
        )

    published_local_date = published_at.astimezone(source_zone).date()
    crawled_local_date = crawled_at.astimezone(source_zone).date()
    difference = abs((crawled_local_date - published_local_date).days)
    decision = (
        DATE_ONLY_CANDIDATE
        if difference <= 1
        else DATE_ONLY_HISTORICAL
    )
    return CandidateFreshnessResult(
        decision=decision,
        reason=decision,
        crawled_at=crawled_at,
        source_timezone=source_timezone,
        published_local_date=published_local_date,
        crawled_local_date=crawled_local_date,
        date_difference_days=difference,
    )
