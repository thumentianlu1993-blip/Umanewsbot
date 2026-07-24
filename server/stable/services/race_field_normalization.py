"""
Race field normalization — pure-functional service.

All normalization functions are deterministic and database-free.
They accept raw source values and return immutable value objects with
a reason code, rule version, and input hash for auditability.

This module is the single source of truth for:
- finish position / result status normalization
- race grade normalization
- distance normalization
- surface, race-type, layout and going normalization
- eligibility (age & sex restriction) normalization
- historical context recovery

============================================================================
HOW TO USE
============================================================================

    result = normalize_finish_position("01", source_kind="hkjc")
    result.position  # => 1
    result.status   # => NormalizedRaceResultStatus.FINISHED

    grade = normalize_grade("G1", source_language="en")
    grade.grade  # => "G1"

============================================================================
NOTES
============================================================================

- All result objects are frozen dataclasses; see each class for field lists.
- ``status`` on value objects is a string indicating the outcome of
  normalization: ``"normalized"``, ``"preserved"``, ``"unknown"`` or
  ``"conflict"``.
- ``reason.reason_code`` is a more specific, machine-readable string.
- ``reason.status`` parallels the result status above.
- ``version`` is always ``RACE_FIELD_NORMALIZATION_VERSION``.
- ``input_sha256`` is a deterministic hash of the input parameters.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from django.db import models

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

RACE_FIELD_NORMALIZATION_VERSION = "race-field-normalization.v1"

DISTANCE_CONVERSION_CONSTANTS = {
    "mile": 1609.344,
    "furlong": 201.168,
    "yard": 0.9144,
    "foot": 0.3048,
}

# ---------------------------------------------------------------------------
# Reason code constants
# ---------------------------------------------------------------------------

REASON_CODE_CONTEXT_FROM_LINKED_EVENT = "context_from_linked_event"
REASON_CODE_CONTEXT_FROM_VALIDATED_SOURCE_REF = "context_from_validated_source_ref"
REASON_CODE_CONTEXT_FROM_OFFICIAL_VENUE_ID = "context_from_official_venue_id"
REASON_CODE_CONTEXT_FROM_UNIQUE_FORMAL_TERM = "context_from_unique_formal_term"
REASON_CODE_REGION_UNKNOWN = "region_unknown"
REASON_CODE_SOURCE_LANGUAGE_UNKNOWN = "source_language_unknown"
REASON_CODE_CONTEXT_CONFLICT = "context_conflict"
REASON_CODE_NORMALIZED = "normalized"
REASON_CODE_PRESERVED = "preserved"

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NormalizedRaceResultStatus(models.TextChoices):
    FINISHED = "finished", "完赛"
    DEAD_HEAT = "dead_heat", "同着"
    DID_NOT_FINISH = "did_not_finish", "未完赛"
    PULLED_UP = "pulled_up", "拉停"
    UNSEATED_RIDER = "unseated_rider", "落马"
    FELL = "fell", "堕马"
    DISQUALIFIED = "disqualified", "失格"
    BROUGHT_DOWN = "brought_down", "拉停"
    SCRATCHED = "scratched", "退赛"
    NON_RUNNER = "non_runner", "未出赛"
    WITHDRAWN = "withdrawn", "退出"
    UNKNOWN = "unknown", "未知"


class DistancePrecision(models.TextChoices):
    OFFICIAL_METRIC = "official_metric", "官方公制"
    EXACT_CONVERSION = "exact_conversion", "精确换算"
    APPROXIMATE_CONVERSION = "approximate_conversion", "近似换算"
    UNKNOWN = "unknown", "未知"


class NormalizedSurface(models.TextChoices):
    TURF = "turf", "草地"
    DIRT = "dirt", "泥地"
    SYNTHETIC = "synthetic", "合成"
    UNKNOWN = "unknown", "未知"


class NormalizedRaceType(models.TextChoices):
    FLAT = "flat", "平地"
    HURDLE = "hurdle", "障碍"
    STEEPLECHASE = "steeplechase", "越野障碍"
    OTHER = "other", "其他"
    UNKNOWN = "unknown", "未知"


class RaceSexRestriction(models.TextChoices):
    OPEN = "open", "不限"
    FEMALE = "female", "牝马"
    MALE = "male", "牡马"
    MALE_OR_FEMALE = "male_or_female", "牡/牝"
    OTHER = "other", "其他"
    UNKNOWN = "unknown", "未知"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizationReason:
    """Immutable reason sub-object carried by every normalization result."""
    status: str  # "normalized" | "preserved" | "unknown" | "conflict"
    reason_code: str


@dataclass(frozen=True)
class FinishNormalization:
    """Result of finish-position / result-status normalization."""
    position: Optional[int]
    status: NormalizedRaceResultStatus
    start_status: str
    reason: NormalizationReason
    version: str
    input_sha256: str


@dataclass(frozen=True)
class GradeNormalization:
    """Result of race-grade normalization."""
    grade: str
    status: str
    original: str
    reason: NormalizationReason


@dataclass(frozen=True)
class DistanceNormalization:
    """Result of distance normalization."""
    meters: Optional[float]
    precision: DistancePrecision
    source_unit: str
    display_text: str
    original: str
    status: str
    reason: NormalizationReason
    version: str


@dataclass(frozen=True)
class SurfaceNormalization:
    """Result of surface / race-type / layout / going normalization."""
    surface: NormalizedSurface
    race_type: NormalizedRaceType
    course_text: str
    course_layout: str
    going_text: str
    status: str
    original: str
    reason: NormalizationReason


@dataclass(frozen=True)
class EligibilityNormalization:
    """Result of eligibility (age / sex) normalization."""
    min_age: Optional[int]
    max_age: Optional[int]
    age_open_ended: bool
    sex: RaceSexRestriction
    extra_constraints: dict
    status: str
    reason: NormalizationReason


@dataclass(frozen=True)
class ContextRecoveryResult:
    """Result of historical context recovery."""
    region: str
    source_language: str
    reason: NormalizationReason


@dataclass(frozen=True)
class IdentityResolution:
    """Result of term identity resolution (not used in these tests but defined per spec)."""
    term_id: Optional[int]
    status: str
    reason: NormalizationReason


# ---------------------------------------------------------------------------
# Static data maps
# ---------------------------------------------------------------------------

FINISH_STATUS_MAP: dict[str, NormalizedRaceResultStatus] = {
    "DNF": NormalizedRaceResultStatus.DID_NOT_FINISH,
    "did_not_finish": NormalizedRaceResultStatus.DID_NOT_FINISH,
    "PU": NormalizedRaceResultStatus.PULLED_UP,
    "pulled_up": NormalizedRaceResultStatus.PULLED_UP,
    "UR": NormalizedRaceResultStatus.UNSEATED_RIDER,
    "unseated_rider": NormalizedRaceResultStatus.UNSEATED_RIDER,
    "F": NormalizedRaceResultStatus.FELL,
    "fell": NormalizedRaceResultStatus.FELL,
    "Fell": NormalizedRaceResultStatus.FELL,
    "BD": NormalizedRaceResultStatus.BROUGHT_DOWN,
    "brought_down": NormalizedRaceResultStatus.BROUGHT_DOWN,
    "DSQ": NormalizedRaceResultStatus.DISQUALIFIED,
    "disqualified": NormalizedRaceResultStatus.DISQUALIFIED,
    "DQ": NormalizedRaceResultStatus.DISQUALIFIED,
    "SCR": NormalizedRaceResultStatus.SCRATCHED,
    "scratched": NormalizedRaceResultStatus.SCRATCHED,
    "NR": NormalizedRaceResultStatus.NON_RUNNER,
    "non_runner": NormalizedRaceResultStatus.NON_RUNNER,
    "WV": NormalizedRaceResultStatus.WITHDRAWN,
    "withdrawn": NormalizedRaceResultStatus.WITHDRAWN,
    "Withdrawn": NormalizedRaceResultStatus.WITHDRAWN,
    "dead_heat": NormalizedRaceResultStatus.DEAD_HEAT,
    "DH": NormalizedRaceResultStatus.DEAD_HEAT,
}

JP_STATUS_MAP: dict[str, tuple[NormalizedRaceResultStatus, str]] = {
    "取消": (NormalizedRaceResultStatus.SCRATCHED, "non_starter"),
    "除外": (NormalizedRaceResultStatus.SCRATCHED, "non_starter"),
    "中止": (NormalizedRaceResultStatus.DID_NOT_FINISH, "starter"),
    "失格": (NormalizedRaceResultStatus.DISQUALIFIED, "starter"),
}

NON_STARTER_STATUSES = {
    NormalizedRaceResultStatus.SCRATCHED,
    NormalizedRaceResultStatus.NON_RUNNER,
    NormalizedRaceResultStatus.WITHDRAWN,
}

PROVIDER_LANGUAGE_MAP: dict[str, str] = {
    # Japanese providers
    "netkeiba": "ja",
    "jbis": "ja",
    "jra": "ja",
    "nar": "ja",
    # English providers
    "sporting_life": "en",
    "hrn": "en",
    "racing_post": "en",
    "equibase": "en",
    # Chinese (Hong Kong) provider
    "hkjc": "zh-hant",
    # French providers
    "france_galop": "fr",
    "geny": "fr",
    "zeturf": "fr",
}

# Grade mapping: raw_text (NFKC-canonicalized) → normalized grade
GRADE_MAP: dict[str, str] = {
    "G1": "G1",
    "GI": "G1",
    "GROUP 1": "G1",
    "GRADE 1": "G1",
    "GROUPE I": "G1",
    "G2": "G2",
    "GII": "G2",
    "GROUP 2": "G2",
    "GRADE 2": "G2",
    "GROUPE II": "G2",
    "G3": "G3",
    "GIII": "G3",
    "GROUP 3": "G3",
    "GRADE 3": "G3",
    "GROUPE III": "G3",
    "JPN1": "JPN1",
    "JPN2": "JPN2",
    "JPN3": "JPN3",
    "JG1": "JG1",
    "JG2": "JG2",
    "JG3": "JG3",
    "J-G1": "JG1",
    "J-G2": "JG2",
    "J-G3": "JG3",
    "J.G1": "JG1",
    "LISTED": "L",
    "L": "L",
    "リステッド": "L",
}

# HK Chinese grade mapping
HK_GRADE_MAP: dict[str, str] = {
    "一级赛": "G1",
    "一級賽": "G1",
    "香港一级赛": "G1",
    "香港一級賽": "G1",
    "二级赛": "G2",
    "二級賽": "G2",
    "香港二级赛": "G2",
    "香港二級賽": "G2",
    "三级赛": "G3",
    "三級賽": "G3",
    "香港三级赛": "G3",
    "香港三級賽": "G3",
}

# Surface mapping
SURFACE_MAP: dict[str, NormalizedSurface] = {
    "turf": NormalizedSurface.TURF,
    "Turf": NormalizedSurface.TURF,
    "dirt": NormalizedSurface.DIRT,
    "Dirt": NormalizedSurface.DIRT,
    "AW": NormalizedSurface.SYNTHETIC,
    "all-weather": NormalizedSurface.SYNTHETIC,
    "synthetic": NormalizedSurface.SYNTHETIC,
    "ポリトラック": NormalizedSurface.SYNTHETIC,
    "ダート": NormalizedSurface.DIRT,
    "芝": NormalizedSurface.TURF,
}

# Race type mapping
RACE_TYPE_MAP: dict[str, NormalizedRaceType] = {
    "hurdle": NormalizedRaceType.HURDLE,
    "Hurdle": NormalizedRaceType.HURDLE,
    "障害": NormalizedRaceType.HURDLE,
    "steeplechase": NormalizedRaceType.STEEPLECHASE,
    "Steeplechase": NormalizedRaceType.STEEPLECHASE,
    "チェイス": NormalizedRaceType.STEEPLECHASE,
}

# Going words (to prevent them from being treated as surface)
GOING_WORDS = frozenset({
    "Good", "Soft", "Heavy", "Firm", "Yielding", "Standard",
    "good", "soft", "heavy", "firm", "yielding", "standard",
    "bon",  # French
})

# ---------------------------------------------------------------------------
# Utility  helpers
# ---------------------------------------------------------------------------

def compute_input_sha256(**kwargs: Any) -> str:
    """Compute a deterministic SHA-256 from keyword arguments.

    Arguments are sorted by key, converted to string form, joined with pipes,
    and hashed.  This guarantees the same hash for the same inputs every time.
    """
    parts: list[str] = []
    for key in sorted(kwargs):
        value = kwargs[key]
        parts.append(f"{key}={value}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _make_reason(status: str, reason_code: str | None = None) -> NormalizationReason:
    """Build a NormalizationReason, defaulting reason_code to status."""
    return NormalizationReason(status=status, reason_code=reason_code or status)


# ---------------------------------------------------------------------------
# Finish position / result status
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"^(\d+)$")
_ORDINAL_SUFFIX_RE = re.compile(r"^(\d+)(?:st|nd|rd|th)$", re.IGNORECASE)
_CHINESE_POSITION_RE = re.compile(r"^第(\d+)$")


def _parse_numeric_position(raw: str) -> int | None:
    """Try to extract a numeric finish position from *raw*.

    Supports:
    - Plain digits: ``"1"``, ``"01"``, ``"10"``
    - Ordinal suffixes: ``"1st"``, ``"2nd"``, ``"3rd"``, ``"10th"``
    - Chinese prefix: ``"第1"``, ``"第2"``
    """
    text = raw.strip()

    # Chinese: 第1, 第2, 第3
    m = _CHINESE_POSITION_RE.match(text)
    if m:
        return int(m.group(1))

    # Ordinal suffix
    m = _ORDINAL_SUFFIX_RE.match(text)
    if m:
        return int(m.group(1))

    # Plain digits (including leading-zero like "01")
    m = _NUMERIC_RE.match(text)
    if m:
        return int(m.group(1))  # int("01") == 1

    return None


def _start_status_for(status: NormalizedRaceResultStatus) -> str:
    """Derive start status from normalized result status."""
    return "non_starter" if status in NON_STARTER_STATUSES else "starter"


def normalize_finish_position(
    raw_value: Any,
    source_kind: str = "",
    is_dead_heat: bool = False,
) -> FinishNormalization:
    """Normalize a raw finish position string into a ``FinishNormalization``.

    Parameters
    ----------
    raw_value: str or None
        The raw position string from the source.
    source_kind: str
        Source identifier (e.g. ``"hkjc"``, ``"sporting_life"``,
        ``"netkeiba"``, ``"france_galop"``, ``"hrn"``).
    is_dead_heat: bool
        If ``True`` overrides the status to ``DEAD_HEAT`` while keeping
        the numeric position.

    Returns
    -------
    FinishNormalization
    """
    raw_str = str(raw_value).strip() if raw_value is not None else ""
    input_sha = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    # --- empty / None / unrecognisable ---
    if not raw_str:
        return FinishNormalization(
            position=None,
            status=NormalizedRaceResultStatus.UNKNOWN,
            start_status="starter",
            reason=_make_reason("unknown", REASON_CODE_PRESERVED),
            version=RACE_FIELD_NORMALIZATION_VERSION,
            input_sha256=input_sha,
        )

    # --- Japanese status codes (check early so they don't get parsed as numbers) ---
    if raw_str in JP_STATUS_MAP:
        jp_status, jp_start = JP_STATUS_MAP[raw_str]
        return FinishNormalization(
            position=None,
            status=jp_status,
            start_status=jp_start,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
            version=RACE_FIELD_NORMALIZATION_VERSION,
            input_sha256=input_sha,
        )

    # --- Dead heat as raw value ---
    if raw_str in ("DH", "dead_heat"):
        return FinishNormalization(
            position=None,
            status=NormalizedRaceResultStatus.DEAD_HEAT,
            start_status="starter",
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
            version=RACE_FIELD_NORMALIZATION_VERSION,
            input_sha256=input_sha,
        )

    # --- Numeric position ---
    pos = _parse_numeric_position(raw_str)
    if pos is not None:
        status = NormalizedRaceResultStatus.DEAD_HEAT if is_dead_heat else NormalizedRaceResultStatus.FINISHED
        return FinishNormalization(
            position=pos,
            status=status,
            start_status="starter",
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
            version=RACE_FIELD_NORMALIZATION_VERSION,
            input_sha256=input_sha,
        )

    # --- Standard status codes ---
    if raw_str in FINISH_STATUS_MAP:
        st = FINISH_STATUS_MAP[raw_str]
        start_st = _start_status_for(st)
        return FinishNormalization(
            position=None,
            status=st,
            start_status=start_st,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
            version=RACE_FIELD_NORMALIZATION_VERSION,
            input_sha256=input_sha,
        )

    # --- Unknown / unrecognised ---
    return FinishNormalization(
        position=None,
        status=NormalizedRaceResultStatus.UNKNOWN,
        start_status="starter",
        reason=_make_reason("unknown", REASON_CODE_PRESERVED),
        version=RACE_FIELD_NORMALIZATION_VERSION,
        input_sha256=input_sha,
    )


# ---------------------------------------------------------------------------
# Grade normalization
# ---------------------------------------------------------------------------

def normalize_grade(
    raw_value: Any,
    source_language: str = "en",
    source_region: str = "",
) -> GradeNormalization:
    """Normalize a raw race-grade string.

    Parameters
    ----------
    raw_value: str
        Raw grade text (e.g. ``"G1"``, ``"Group 1"``, ``"一级赛"``).
    source_language: str
        Language code (e.g. ``"en"``, ``"ja"``, ``"fr"``, ``"zh"``).
    source_region: str
        Region code (e.g. ``"hk"``).

    Returns
    -------
    GradeNormalization
    """
    raw_str = str(raw_value).strip() if raw_value else ""

    # --- Hong Kong Chinese grade (region-sensitive) ---
    if source_region == "hk" and raw_str in HK_GRADE_MAP:
        return GradeNormalization(
            grade=HK_GRADE_MAP[raw_str],
            status="normalized",
            original=raw_str,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
        )

    # --- Canonicalise: strip middle-dot, NFKC (handles Roman numerals),
    #     then uppercase for case-insensitive matching ---
    canonical = raw_str.strip()
    canonical = canonical.replace("・", "")  # Katakana middle dot ・
    canonical = unicodedata.normalize("NFKC", canonical).upper().strip()

    # --- Mapped grades ---
    if canonical in GRADE_MAP:
        return GradeNormalization(
            grade=GRADE_MAP[canonical],
            status="normalized",
            original=raw_str,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
        )

    # --- Unmapped → preserve original ---
    return GradeNormalization(
        grade=raw_str,
        status="preserved",
        original=raw_str,
        reason=_make_reason("preserved", REASON_CODE_PRESERVED),
    )


# ---------------------------------------------------------------------------
# Distance normalization
# ---------------------------------------------------------------------------

# Recognised unit suffixes (lowercase)
_UNIT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(m|f|y|ft|M|F|Y|FT|米)", re.IGNORECASE)
_COMBINED_M_F_Y = re.compile(
    r"^(\d+)m(\d+)f(?:(\d+)y)?(?:(\d+)ft)?$", re.IGNORECASE
)
_FRACTIONAL_MILES = re.compile(
    r"^(\d+)\s+(\d+)/(\d+)\s*(M|m|F|f)$", re.IGNORECASE
)
_DECIMAL_IMPERIAL = re.compile(
    r"^(\d+\.\d+)\s*(m|f|y|ft|M|F|Y)$", re.IGNORECASE
)
_SIMPLE_UNIT = re.compile(
    r"^(\d+)\s*(f|y|ft|F|Y|FT)$", re.IGNORECASE
)
_SIMPLE_M_RE = re.compile(
    r"^(\d+)\s*(m|M|米)$", re.IGNORECASE
)
_BARE_DIGITS = re.compile(r"^\d+$")


def _approx_if(rough: bool, base: DistancePrecision) -> DistancePrecision:
    """If *rough* is True return APPROXIMATE_CONVERSION, else *base*."""
    if rough:
        return DistancePrecision.APPROXIMATE_CONVERSION
    return base


def _parse_distance_text(text: str) -> tuple[Optional[float], DistancePrecision, str]:
    """Parse a single distance string and return ``(meters, precision, unit_label)``.

    Returns ``(None, UNKNOWN, "")`` on failure.
    """
    raw = text.strip()
    if not raw:
        return None, DistancePrecision.UNKNOWN, ""

    # --- about / approx prefix ---
    is_approx = False
    for prefix in ("about ", "approx ", "approximately "):
        if raw.lower().startswith(prefix):
            is_approx = True
            raw = raw[len(prefix):].strip()
            break

    # --- Chinese surface prefix ---
    for prefix in ("芝", "ダ", "障"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    if not raw:
        return None, DistancePrecision.UNKNOWN, ""

    # 1. Bare digits → official metric
    if _BARE_DIGITS.match(raw):
        return float(raw), DistancePrecision.OFFICIAL_METRIC, "m"

    # 2. Combined imperial: "1m2f", "2m5f191y"
    m = _COMBINED_M_F_Y.match(raw)
    if m:
        miles = float(m.group(1))
        furlongs = float(m.group(2))
        yards = float(m.group(3)) if m.group(3) else float("0")
        feet = float(m.group(4)) if m.group(4) else float("0")
        total = (
            miles * DISTANCE_CONVERSION_CONSTANTS["mile"]
            + furlongs * DISTANCE_CONVERSION_CONSTANTS["furlong"]
            + yards * DISTANCE_CONVERSION_CONSTANTS["yard"]
            + feet * DISTANCE_CONVERSION_CONSTANTS["foot"]
        )
        return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "m+f+y"

    # 3. US fractional: "1 1/16M"
    m = _FRACTIONAL_MILES.match(raw)
    if m:
        whole = float(m.group(1))
        num = float(m.group(2))
        den = float(m.group(3))
        unit_char = m.group(4).upper()
        frac = whole + num / den
        if unit_char == "M":
            total = frac * DISTANCE_CONVERSION_CONSTANTS["mile"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "M"
        elif unit_char == "F":
            total = frac * DISTANCE_CONVERSION_CONSTANTS["furlong"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "f"

    # 4. Decimal imperial: "8.5f", "8.5m"
    m = _DECIMAL_IMPERIAL.match(raw)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit == "f":
            total = val * DISTANCE_CONVERSION_CONSTANTS["furlong"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "f"
        elif unit == "m":
            total = val * DISTANCE_CONVERSION_CONSTANTS["mile"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "m"
        elif unit == "y":
            total = val * DISTANCE_CONVERSION_CONSTANTS["yard"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "y"

    # 5. Spaced tokens: "1m 2f", "4f 213y", "4f 213y 0ft"
    tokens = re.split(r"\s+", raw)
    if len(tokens) > 1:
        miles = float("0")
        furlongs = float("0")
        yards = float("0")
        feet = float("0")
        units: set[str] = set()
        matched_any = False
        for token in tokens:
            m = _SIMPLE_UNIT.match(token)
            if m:
                matched_any = True
                val = float(m.group(1))
                u = m.group(2).lower()
                units.add(u)
                if u in ("f",):
                    furlongs += val
                elif u in ("y",):
                    yards += val
                elif u == "ft":
                    feet += val
                continue
            # token could be "Xm" (mile)
            m2 = _SIMPLE_M_RE.match(token)
            if m2:
                matched_any = True
                num = int(m2.group(1))
                if num < 100:  # miles
                    miles += float(num)
                    units.add("m")
        if matched_any:
            total = (
                miles * DISTANCE_CONVERSION_CONSTANTS["mile"]
                + furlongs * DISTANCE_CONVERSION_CONSTANTS["furlong"]
                + yards * DISTANCE_CONVERSION_CONSTANTS["yard"]
                + feet * DISTANCE_CONVERSION_CONSTANTS["foot"]
            )
            unit_label = "+".join(sorted(units))
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), unit_label

    # 6. Simple imperial units: "6f", "9f", "4f", "213y"
    m = _SIMPLE_UNIT.match(raw)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit == "f":
            total = val * DISTANCE_CONVERSION_CONSTANTS["furlong"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "f"
        elif unit == "y":
            total = val * DISTANCE_CONVERSION_CONSTANTS["yard"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "y"
        elif unit == "ft":
            total = val * DISTANCE_CONVERSION_CONSTANTS["foot"]
            return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "ft"

    # 7. Metric with unit: "1200m", "1200米"
    m = _SIMPLE_M_RE.match(raw)
    if m:
        val = int(m.group(1))
        if val >= 100:  # meters
            return float(val), DistancePrecision.OFFICIAL_METRIC, "m"

    # 8. Simple "Xm" with X < 100 → miles (single token, not already matched)
    if raw.endswith(("m", "M")):
        digits_part = raw.rstrip("mM")
        if digits_part.isdigit():
            val = int(digits_part)
            if val < 100:
                total = float(val) * DISTANCE_CONVERSION_CONSTANTS["mile"]
                return total, _approx_if(is_approx, DistancePrecision.EXACT_CONVERSION), "m"

    return None, DistancePrecision.UNKNOWN, ""


def normalize_distance(
    raw_value: Any,
    source_language: str | None = None,
    source_region: str | None = None,
    official_metric_meters: int | float | None = None,
    raw_text: str | None = None,
) -> DistanceNormalization:
    """Normalize a raw distance text.

    Parameters
    ----------
    raw_value: str
        Primary distance text (e.g. ``"1200m"``, ``"6f"``, ``"1m 2f"``).
    source_language, source_region:
        Optional context (unused for now, reserved for future locale-sensitive
        parsing).
    official_metric_meters:
        Official metric distance from the source; takes precedence over
        parsed value and is used for conflict detection.
    raw_text:
        Alternative raw distance text; parsed and compared against other
        sources for conflict detection.

    Returns
    -------
    DistanceNormalization
    """
    raw_str = str(raw_value).strip() if raw_value is not None else ""
    input_sha = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    # --- Parse primary and optional secondary values ---
    meters_primary, precision_primary, unit_primary = _parse_distance_text(raw_str)

    meters_secondary, _, unit_secondary = (None, DistancePrecision.UNKNOWN, "")
    if raw_text:
        meters_secondary, _, unit_secondary = _parse_distance_text(raw_text.strip())
    elif official_metric_meters is not None:
        # If only official_metric_meters is set (no raw_text), use it
        meters_secondary = float(str(official_metric_meters))

    # --- Determine authoritative meters ---
    has_official = official_metric_meters is not None
    official_m = float(str(official_metric_meters)) if has_official else None

    # Collect all non-None meter estimates for conflict checking
    estimates: dict[str, float] = {}
    if meters_primary is not None:
        estimates["primary"] = meters_primary
    if meters_secondary is not None:
        estimates["secondary"] = meters_secondary
    if official_m is not None:
        estimates["official"] = official_m

    # Check for significant conflict (> 1 meter difference)
    conflict = False
    if len(estimates) >= 2:
        vals = list(estimates.values())
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if abs(vals[i] - vals[j]) > float("1"):
                    conflict = True
                    break
            if conflict:
                break

    if conflict:
        return DistanceNormalization(
            meters=None,
            precision=DistancePrecision.UNKNOWN,
            source_unit="",
            display_text=raw_str,
            original=raw_str,
            status="conflict",
            reason=_make_reason("conflict", "conflict"),
            version=RACE_FIELD_NORMALIZATION_VERSION,
        )

    # --- Determine final meters and precision ---
    if official_m is not None:
        meters = official_m
        precision = DistancePrecision.OFFICIAL_METRIC
    elif meters_primary is not None:
        meters = meters_primary
        precision = precision_primary
    else:
        meters = None
        precision = DistancePrecision.UNKNOWN

    # Determine source_unit
    source_unit = unit_primary
    if not source_unit and unit_secondary:
        source_unit = unit_secondary

    return DistanceNormalization(
        meters=meters,
        precision=precision,
        source_unit=source_unit,
        display_text=raw_str,
        original=raw_str,
        status="normalized",
        reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
        version=RACE_FIELD_NORMALIZATION_VERSION,
    )


# ---------------------------------------------------------------------------
# Surface / race-type / layout / going
# ---------------------------------------------------------------------------

def normalize_surface_race_type_layout_going(
    raw_value: Any,
    source_language: str | None = None,
    source_region: str | None = None,
    going_text: str | None = None,
) -> SurfaceNormalization:
    """Normalize surface, race-type, course layout and going.

    Parameters
    ----------
    raw_value: str
        Raw surface/race-type/course text.
    source_language, source_region:
        Context for regional parsing.
    going_text:
        Optional going text (e.g. ``"bon"``, ``"Good"``, ``"Soft"``).

    Returns
    -------
    SurfaceNormalization
    """
    raw_str = str(raw_value).strip() if raw_value is not None else ""

    surface = NormalizedSurface.UNKNOWN
    race_type = NormalizedRaceType.UNKNOWN
    course_text = raw_str
    course_layout = ""
    going = going_text or ""
    status = "normalized"

    # --- HKJC combined format: "ST / Turf / \"A\"" ---
    if "/" in raw_str:
        parts = [p.strip().strip('"') for p in raw_str.split("/")]
        if len(parts) >= 2:
            course_text = parts[0]
            surface_raw = parts[1]
            course_layout = parts[2] if len(parts) >= 3 else ""

            # Parse surface
            if surface_raw in SURFACE_MAP:
                surface = SURFACE_MAP[surface_raw]
            else:
                surface = NormalizedSurface.UNKNOWN

            # Race type from surface context
            race_type = NormalizedRaceType.FLAT
            if surface == NormalizedSurface.SYNTHETIC:
                race_type = NormalizedRaceType.FLAT

            return SurfaceNormalization(
                surface=surface,
                race_type=race_type,
                course_text=course_text,
                course_layout=course_layout,
                going_text=going,
                status="normalized",
                original=raw_str,
                reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
            )

    # --- Check for going words (before surface/race-type checks) ---
    if raw_str in GOING_WORDS:
        return SurfaceNormalization(
            surface=NormalizedSurface.UNKNOWN,
            race_type=NormalizedRaceType.UNKNOWN,
            course_text=raw_str,
            course_layout="",
            going_text=raw_str,
            status="normalized",
            original=raw_str,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
        )

    # --- Race type (hurdle / steeplechase) ---
    if raw_str in RACE_TYPE_MAP:
        race_type = RACE_TYPE_MAP[raw_str]
        return SurfaceNormalization(
            surface=NormalizedSurface.UNKNOWN,
            race_type=race_type,
            course_text=raw_str,
            course_layout="",
            going_text=going,
            status="normalized",
            original=raw_str,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
        )

    # --- Surface ---
    if raw_str in SURFACE_MAP:
        surface = SURFACE_MAP[raw_str]
        race_type = NormalizedRaceType.FLAT
        return SurfaceNormalization(
            surface=surface,
            race_type=race_type,
            course_text=raw_str,
            course_layout="",
            going_text=going,
            status="normalized",
            original=raw_str,
            reason=_make_reason("normalized", REASON_CODE_NORMALIZED),
        )

    # --- Unknown → preserve original ---
    return SurfaceNormalization(
        surface=NormalizedSurface.UNKNOWN,
        race_type=NormalizedRaceType.UNKNOWN,
        course_text=raw_str,
        course_layout="",
        going_text=going,
        status="preserved",
        original=raw_str,
        reason=_make_reason("preserved", REASON_CODE_PRESERVED),
    )


# ---------------------------------------------------------------------------
# Eligibility (age / sex) normalization
# ---------------------------------------------------------------------------

def normalize_eligibility(
    raw_value: Any,
    source_language: str | None = None,
    source_region: str | None = None,
) -> EligibilityNormalization:
    """Normalize eligibility text into age and sex restriction.

    Parameters
    ----------
    raw_value: str
        Eligibility text (e.g. ``"2yo"``, ``"3U"``, ``"mares"``, ``"牝"``).

    Returns
    -------
    EligibilityNormalization
    """
    raw_str = str(raw_value).strip() if raw_value is not None else ""

    min_age: int | None = None
    max_age: int | None = None
    open_ended = False
    sex = RaceSexRestriction.UNKNOWN
    extra: dict[str, Any] = {}

    # Tokenise by whitespace and "/"
    tokens = re.split(r"[\s/]+", raw_str)
    reliable_tokens: list[str] = []
    unresolved_tokens: list[str] = []

    for token in tokens:
        token = token.strip()
        if not token:
            continue

        # ---- Sex restrictions ----
        if token.lower() in ("mares", "fillies", "f"):
            if sex == RaceSexRestriction.UNKNOWN:
                sex = RaceSexRestriction.FEMALE
            reliable_tokens.append(token)
            continue

        if token == "牝":
            if sex == RaceSexRestriction.UNKNOWN:
                sex = RaceSexRestriction.FEMALE
            reliable_tokens.append(token)
            continue

        if token.lower() == "m":
            # "M" could be male in some contexts, but in "3U f 3UP F/M" it's
            # part of "F/M" which means female/male (open).
            # We handle "F/M" as a combined token below.
            pass

        # ---- Combined "F/M" ----
        if token.upper() == "F/M":
            sex = RaceSexRestriction.OPEN
            reliable_tokens.append(token)
            continue

        # ---- Age patterns ----

        # "2yo" → min=2, max=2
        m = re.match(r"^(\d+)yo$", token, re.IGNORECASE)
        if m:
            age = int(m.group(1))
            min_age = age
            max_age = age
            open_ended = False
            reliable_tokens.append(token)
            continue

        # "2歳" → min=2, max=2 (Japanese)
        m = re.match(r"^(\d+)歳$", token)
        if m:
            age = int(m.group(1))
            min_age = age
            max_age = age
            open_ended = False
            reliable_tokens.append(token)
            continue

        # "3歳以上" → min=3, open-ended
        m = re.match(r"^(\d+)歳以上$", token)
        if m:
            age = int(m.group(1))
            min_age = age
            max_age = None
            open_ended = True
            reliable_tokens.append(token)
            continue

        # "3U", "3UP" → min=3, open-ended
        m = re.match(r"^(\d+)U(?:P)?$", token, re.IGNORECASE)
        if m:
            age = int(m.group(1))
            min_age = age
            max_age = None
            open_ended = True
            reliable_tokens.append(token)
            continue

        # "3yo+" → min=3, open-ended
        m = re.match(r"^(\d+)yo\+$", token, re.IGNORECASE)
        if m:
            age = int(m.group(1))
            min_age = age
            max_age = None
            open_ended = True
            reliable_tokens.append(token)
            continue

        # "4yo+" → min=4, open-ended
        m = re.match(r"^(\d+)yo\+$", token, re.IGNORECASE)
        if m:
            age = int(m.group(1))
            min_age = age
            max_age = None
            open_ended = True
            reliable_tokens.append(token)
            continue

        # ---- Unresolved token ---
        unresolved_tokens.append(token)

    # Build extra_constraints from unresolved tokens
    if unresolved_tokens:
        extra["unresolved"] = " ".join(unresolved_tokens)

    # Determine status
    if min_age is not None or sex != RaceSexRestriction.UNKNOWN:
        status = "normalized"
        reason_code = REASON_CODE_NORMALIZED
    else:
        status = "preserved"
        reason_code = REASON_CODE_PRESERVED

    return EligibilityNormalization(
        min_age=min_age,
        max_age=max_age,
        age_open_ended=open_ended,
        sex=sex,
        extra_constraints=extra,
        status=status,
        reason=_make_reason(status, reason_code),
    )


# ---------------------------------------------------------------------------
# Historical context recovery
# ---------------------------------------------------------------------------

def normalize_context(
    raw_region: str = "",
    horse_profile_racing_region: str = "",
    provider: str = "",
    linked_event_region: str = "",
    validated_source_ref_region: str = "",
    official_venue_id_region: str = "",
    official_venue_id: str = "",
) -> ContextRecoveryResult:
    """Recover race region and source language from available context.

    Priority order (highest first):
    1. ``linked_event_region``
    2. ``validated_source_ref_region``
    3. ``official_venue_id_region`` (or ``official_venue_id``)
    4. Nothing → ``region_unknown``

    ``horse_profile_racing_region`` is **never** used to infer race region
    (explicitly prohibited by spec).

    ``provider`` is only used to set ``source_language``, never region.

    Parameters
    ----------
    raw_region:
        Region text from the raw payload (used for conflict detection).
    horse_profile_racing_region:
        **Ignored** — never inherits race region from horse profile.
    provider:
        Source provider name (sets ``source_language`` only).
    linked_event_region:
        Region from a linked ``RaceEvent.country_region``.
    validated_source_ref_region:
        Region from a validated source reference.
    official_venue_id_region:
        Region derived from an official venue/track ID.
    official_venue_id:
        Official venue/track ID (gives "context_from_official_venue_id"
        reason code even without a direct region mapping).

    Returns
    -------
    ContextRecoveryResult
    """
    # Source language from provider
    source_language = PROVIDER_LANGUAGE_MAP.get(provider, "")

    # Collect region sources (in priority order, excluding horse_profile)
    region_sources: dict[str, str] = {}

    if linked_event_region:
        region_sources["linked_event"] = linked_event_region
    if validated_source_ref_region:
        region_sources["validated_source_ref"] = validated_source_ref_region
    if official_venue_id_region:
        region_sources["official_venue_id"] = official_venue_id_region

    # Determine primary region and source
    primary_region = ""
    primary_source = ""

    for source_key in ("linked_event", "validated_source_ref", "official_venue_id"):
        if source_key in region_sources:
            primary_region = region_sources[source_key]
            primary_source = source_key
            break

    # Check if raw_region conflicts with primary region
    has_region = bool(primary_region or official_venue_id)

    if primary_region and raw_region and primary_region != raw_region:
        # Conflict between primary source and raw_region
        return ContextRecoveryResult(
            region=primary_region,
            source_language=source_language,
            reason=_make_reason("conflict", REASON_CODE_CONTEXT_CONFLICT),
        )

    if not primary_region:
        # No region from any priority source
        if official_venue_id:
            # Have venue ID but no direct region mapping
            return ContextRecoveryResult(
                region="",
                source_language=source_language,
                reason=_make_reason("normalized", REASON_CODE_CONTEXT_FROM_OFFICIAL_VENUE_ID),
            )

        if source_language:
            reason_code = REASON_CODE_REGION_UNKNOWN
        else:
            reason_code = REASON_CODE_SOURCE_LANGUAGE_UNKNOWN

        return ContextRecoveryResult(
            region="",
            source_language=source_language,
            reason=_make_reason("unknown", reason_code),
        )

    # Map source key to reason code
    reason_code_map = {
        "linked_event": REASON_CODE_CONTEXT_FROM_LINKED_EVENT,
        "validated_source_ref": REASON_CODE_CONTEXT_FROM_VALIDATED_SOURCE_REF,
        "official_venue_id": REASON_CODE_CONTEXT_FROM_OFFICIAL_VENUE_ID,
    }
    reason_code = reason_code_map.get(primary_source, REASON_CODE_REGION_UNKNOWN)

    return ContextRecoveryResult(
        region=primary_region,
        source_language=source_language,
        reason=_make_reason("normalized", reason_code),
    )
