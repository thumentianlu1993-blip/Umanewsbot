from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any

from django.utils import timezone

from stable import models


MATRIX_VERSION = "race-live-target-matrix-v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_GROUP_GRADES = frozenset(
    {models.RaceGrade.G1, models.RaceGrade.G2, models.RaceGrade.G3}
)
_JAPAN_HONG_KONG_GRADES = _GROUP_GRADES | frozenset(
    {
        models.RaceGrade.JPN1,
        models.RaceGrade.JPN2,
        models.RaceGrade.JPN3,
        models.RaceGrade.JG1,
        models.RaceGrade.JG2,
        models.RaceGrade.JG3,
    }
)
_EXCEPTION_KEYS = frozenset(
    {
        "schema_version",
        "approved_commit",
        "event_ids",
        "reason",
        "approval_evidence_sha256",
        "generated_at",
        "valid_until",
        "scope_digest",
    }
)


@dataclass(frozen=True)
class RaceLiveTargetEligibilityDecision:
    eligible: bool
    reason: str
    matrix_version: str
    exception_digest: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        return None
    return parsed


def _valid_exception(
    artifact: Any,
    *,
    event_id: int,
    expected_approved_commit: str | None,
    now: datetime,
) -> str:
    if not isinstance(artifact, dict) or set(artifact) != _EXCEPTION_KEYS:
        return ""
    if artifact["schema_version"] != 1:
        return ""
    approved_commit = str(artifact["approved_commit"])
    if (
        _COMMIT_RE.fullmatch(approved_commit) is None
        or (
            expected_approved_commit is not None
            and (
                _COMMIT_RE.fullmatch(expected_approved_commit) is None
                or approved_commit != expected_approved_commit
            )
        )
    ):
        return ""
    event_ids = artifact["event_ids"]
    if (
        not isinstance(event_ids, list)
        or not event_ids
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in event_ids
        )
        or len(event_ids) != len(set(event_ids))
        or event_ids != sorted(event_ids)
        or event_id not in event_ids
    ):
        return ""
    if (
        not isinstance(artifact["reason"], str)
        or not artifact["reason"]
        or artifact["reason"] != artifact["reason"].strip()
        or _SHA256_RE.fullmatch(
            str(artifact["approval_evidence_sha256"])
        )
        is None
    ):
        return ""
    generated_at = _parse_aware(artifact["generated_at"])
    valid_until = _parse_aware(artifact["valid_until"])
    if (
        generated_at is None
        or valid_until is None
        or generated_at > now
        or valid_until <= now
        or valid_until <= generated_at
    ):
        return ""
    scoped = dict(artifact)
    scope_digest = scoped.pop("scope_digest")
    actual_scope_digest = hashlib.sha256(_canonical_bytes(scoped)).hexdigest()
    if (
        _SHA256_RE.fullmatch(str(scope_digest)) is None
        or scope_digest != actual_scope_digest
    ):
        return ""
    return hashlib.sha256(_canonical_bytes(artifact)).hexdigest()


def evaluate_race_live_target_eligibility(
    *,
    event_id: int,
    year: int,
    region: str,
    normalized_grade: str,
    exception_artifact: dict[str, Any] | None = None,
    expected_approved_commit: str | None = None,
    now: datetime | None = None,
) -> RaceLiveTargetEligibilityDecision:
    """Evaluate the single fail-closed live target matrix used by all loaders."""
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or isinstance(year, bool)
        or not isinstance(year, int)
        or year <= 0
        or not isinstance(region, str)
        or not isinstance(normalized_grade, str)
    ):
        return RaceLiveTargetEligibilityDecision(
            False,
            "invalid_target",
            MATRIX_VERSION,
            "",
        )

    eligible = False
    reason = "region_not_supported"
    if region in {
        models.RacingRegion.UNITED_KINGDOM,
        models.RacingRegion.FRANCE,
        models.RacingRegion.UNITED_STATES,
    }:
        eligible = year >= 2025 and normalized_grade in _GROUP_GRADES
        reason = (
            "eligible"
            if eligible
            else (
                "year_before_2025"
                if year < 2025
                else "grade_not_eligible"
            )
        )
    elif region == models.RacingRegion.HONG_KONG:
        eligible = normalized_grade in _JAPAN_HONG_KONG_GRADES
        reason = "eligible" if eligible else "grade_not_eligible"
    elif region == models.RacingRegion.JAPAN:
        eligible = normalized_grade in _JAPAN_HONG_KONG_GRADES
        reason = "eligible" if eligible else "grade_not_eligible"

    if eligible:
        return RaceLiveTargetEligibilityDecision(
            True,
            reason,
            MATRIX_VERSION,
            "",
        )

    effective_now = now or timezone.now()
    if not isinstance(effective_now, datetime) or timezone.is_naive(effective_now):
        return RaceLiveTargetEligibilityDecision(
            False,
            "invalid_now",
            MATRIX_VERSION,
            "",
        )
    exception_digest = _valid_exception(
        exception_artifact,
        event_id=event_id,
        expected_approved_commit=expected_approved_commit,
        now=effective_now,
    )
    if exception_digest:
        return RaceLiveTargetEligibilityDecision(
            True,
            "exception_approved",
            MATRIX_VERSION,
            exception_digest,
        )
    return RaceLiveTargetEligibilityDecision(
        False,
        reason,
        MATRIX_VERSION,
        "",
    )
