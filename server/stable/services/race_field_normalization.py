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

# 严格展示合同独立于 v1 写入合同；以下函数不查库，也不读取开关。
from decimal import Decimal, localcontext
from fractions import Fraction
import json

RACE_INFORMATION_DISPLAY_VERSION = 'race-information-display.v1'


@dataclass(frozen=True)
class DisplayField:
    text: str
    state: str
    reason_code: str
    input_sha256: str
    rule_version: str = RACE_INFORMATION_DISPLAY_VERSION
    code: str = ''
    meters: Decimal | None = None
    source_unit: str = ''
    approximate: bool = False
    min_age: int | None = None
    max_age: int | None = None
    age_open_ended: bool = False


def display_field(raw, text='', *, state='normalized', reason='normalized', context=None, **values):
    payload = {'raw': raw, 'context': context or {}, 'version': RACE_INFORMATION_DISPLAY_VERSION}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str,
                                       separators=(',', ':')).encode()).hexdigest()
    if state == 'missing':
        text = '—'
    elif state in {'unknown', 'conflict'}:
        text = '待核实'
    return DisplayField(text, state, reason, digest, **values)


def _display_text(raw):
    return unicodedata.normalize('NFKC', str(raw if raw is not None else '')).strip()


def _distance_syntax_text(text):
    """仅分离明确的场地标签和合法千分位；保留其他未消费内容以供拒绝。"""
    prefix = re.match(r'^(ダート|芝|ダ)\s*', text)
    suffix = re.search(r'\s+(turf|dirt)$', text, re.I)
    if prefix and suffix:
        surface = 'turf' if prefix[1] == '芝' else 'dirt'
        if surface != suffix[1].lower():
            return text
    if suffix:
        text = text[:suffix.start()]
    if prefix:
        text = text[prefix.end():]
    return re.sub(r'(?<![\d,.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,.])',
                  lambda match: match[0].replace(',', ''), text).strip()


def _missing(raw, context=None):
    return display_field(raw, state='missing', reason='missing', context=context)


def _unresolved(raw, reason='unsupported_format', *, context=None, conflict=False):
    return display_field(raw, state='conflict' if conflict else 'unknown', reason=reason, context=context)


def _fraction_text(value):
    value = Fraction(value)
    denominator = value.denominator
    for divisor in (2, 5):
        while denominator % divisor == 0:
            denominator //= divisor
    if denominator != 1:
        return f'{value.numerator}/{value.denominator}'
    with localcontext() as ctx:
        ctx.prec = max(40, len(str(value.numerator)) + len(str(value.denominator)) + 5)
        text = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


_NUMBER = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)'
_DISTANCE_TOKEN = re.compile(
    rf'({_NUMBER})\s*(メートル|kilometers?|kilometres?|meters?|metres?|furlongs?|miles?|feet|foot|yards?|'
    r'公里|英里|英尺|千米|米|fur|km|ft|yds?|mi|m|f|y)', re.I)
_UNIT_ALIASES = {
    **{k: 'meter' for k in ('米', 'meter', 'meters', 'metre', 'metres', 'メートル')},
    **{k: 'kilometer' for k in ('km', '公里', '千米', 'kilometer', 'kilometers', 'kilometre', 'kilometres')},
    **{k: 'mile' for k in ('mile', 'miles', 'mi', '英里')},
    **{k: 'foot' for k in ('ft', 'foot', 'feet', '英尺')},
    **{k: 'yard' for k in ('yd', 'yds', 'y', 'yard', 'yards')},
    **{k: 'furlong' for k in ('f', 'fur', 'furlong', 'furlongs')},
}
_METERS = {'meter': Fraction(1), 'kilometer': Fraction(1000), 'mile': Fraction('1609.344'),
           'foot': Fraction('0.3048'), 'yard': Fraction('0.9144'), 'furlong': Fraction('201.168')}


def _number_fraction(text):
    bits = text.split()
    return sum((Fraction(bit) for bit in bits), Fraction(0))


def parse_display_distance(raw, *, unit_hint='', official_metric_meters=None, context=None):
    """m/裸数字只有显式来源单位证据才能解析；不按地区、数字大小猜。"""
    ctx = {**(context or {}), 'unit_hint': unit_hint, 'official_metric': official_metric_meters}
    text = _display_text(raw).replace('⁄', '/')
    if not text:
        return _missing(raw, ctx)
    if len(text) > 512:
        return _unresolved(raw, 'input_too_long', context=ctx)
    # NFKC 把 1½ 变成 11/2，不能把它当十一分之二或5.5；先在原串中展开。
    original = str(raw)
    fractions = {'½': '1/2', '¼': '1/4', '¾': '3/4', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8'}
    for symbol, value in fractions.items():
        original = re.sub(rf'(?<=\d){symbol}', ' ' + value, original).replace(symbol, value)
    text = _distance_syntax_text(_display_text(original).replace('⁄', '/'))
    approximate = bool(re.match(r'^(?:约|約|about\s+|abt\.?\s+|approx\.?\s*)', text, re.I))
    text = re.sub(r'^(?:约|約|about\s+|abt\.?\s+|approx\.?\s*)', '', text, flags=re.I).strip()
    annotation = re.search(r'\(约(\d+)米\)$', text)
    rounded_annotation = int(annotation.group(1)) if annotation else None
    if annotation:
        text = text[:annotation.start()].strip()
    hint_text = unit_hint.lower() if isinstance(unit_hint, str) else ''
    hint = _UNIT_ALIASES.get(hint_text, hint_text)
    if hint == 'm':
        hint = 'meter'
    if re.fullmatch(_NUMBER, text):
        if hint not in _METERS:
            return _unresolved(raw, 'ambiguous_unit', context=ctx)
        text += {'meter': '米', 'kilometer': '公里', 'mile': '英里', 'foot': '英尺',
                 'yard': 'yd', 'furlong': 'fur'}[hint]
    values = []
    end = 0
    try:
        for token in _DISTANCE_TOKEN.finditer(text):
            gap = text[end:token.start()].strip()
            if gap.lower() in {'abt', 'abt.', 'about'}:
                approximate = True
            elif gap:
                return _unresolved(raw, 'unconsumed_token', context=ctx)
            amount = _number_fraction(token.group(1))
            unit = token.group(2).lower()
            if unit == 'm':
                if hint not in {'meter', 'mile'}:
                    return _unresolved(raw, 'ambiguous_unit', context=ctx)
                unit = hint
            else:
                unit = _UNIT_ALIASES[unit]
            if amount < 0:
                return _unresolved(raw, 'invalid_distance', context=ctx)
            values.append((amount, unit))
            end = token.end()
        if not values or text[end:].strip() or len({u for _, u in values}) != len(values):
            return _unresolved(raw, 'unconsumed_token', context=ctx)
        metric = all(u in {'meter', 'kilometer'} for _, u in values)
        if not metric and any(u in {'meter', 'kilometer'} for _, u in values):
            return _unresolved(raw, 'mixed_unit_system', context=ctx, conflict=True)
        meters = sum((v * _METERS[u] for v, u in values), Fraction(0))
        if meters <= 0 or meters > 1000000:
            return _unresolved(raw, 'invalid_distance', context=ctx)
        rounded = (meters * 2 + 1) // 2  # 正数精确 ROUND_HALF_UP
        if official_metric_meters is not None and Fraction(str(official_metric_meters)) != meters:
            return _unresolved(raw, 'metric_conflict', context=ctx, conflict=True)
        if rounded_annotation is not None and (metric or rounded_annotation != rounded):
            return _unresolved(raw, 'annotation_conflict', context=ctx, conflict=True)
        if metric:
            label = _fraction_text(meters) + '米'
        else:
            feet = meters / _METERS['foot']
            if len(values) == 1 and values[0][1] == 'foot':
                label = _fraction_text(feet) + '英尺'
            elif feet % 660 == 0:
                label = _fraction_text(feet / 5280) + '英里'
            else:
                miles, remaining = divmod(feet, 5280)
                label = (f'{miles}英里' if miles else '') + (_fraction_text(remaining) + '英尺' if remaining else '')
            label += f'（约{rounded}米）'
        with localcontext() as decimal_context:
            decimal_context.prec = 40
            decimal_meters = Decimal(meters.numerator) / Decimal(meters.denominator)
        return display_field(raw, ('约' if approximate else '') + label, context=ctx,
                             meters=decimal_meters, source_unit='+'.join(u for _, u in values), approximate=approximate)
    except (ValueError, ZeroDivisionError, ArithmeticError):
        return _unresolved(raw, 'invalid_distance', context=ctx)


_DISPLAY_GRADE_LABELS = {**{f'G{i}': f'G{i}' for i in range(1, 4)},
                         **{f'JPN{i}': f'Jpn{i}' for i in range(1, 4)},
                         **{f'JG{i}': f'J-G{i}' for i in range(1, 4)}, 'L': 'L', 'OP': 'OP'}
_DISPLAY_CLASSES = {'NEWCOMER': '新马', 'MAIDEN': '未胜利', '1WIN': '1胜级', '2WIN': '2胜级', '3WIN': '3胜级',
                    '新馬': '新马', '新马': '新马', '未勝利': '未胜利', '未胜利': '未胜利'}


def parse_display_grade(raw, *, normalized_grade='', context=None, verified_race_name=''):
    ctx = {**(context or {}), 'normalized_grade': normalized_grade, 'verified_race_name': verified_race_name}
    text = _display_text(raw).upper()
    stored = _display_text(normalized_grade).upper()
    if not text:
        if stored in _DISPLAY_GRADE_LABELS:
            return display_field(raw, _DISPLAY_GRADE_LABELS[stored], code=stored, context=ctx)
        return _missing(raw, ctx) if not stored else _unresolved(raw, 'unverified_grade', context=ctx)
    if len(text) > 512:
        return _unresolved(raw, 'input_too_long', context=ctx)
    name = _display_text(verified_race_name).upper()
    if name and text.endswith(' ' + name):
        text = text[:-len(name)].rstrip()
    if text in _DISPLAY_CLASSES or re.fullmatch(r'[123]勝(?:クラス)?', text):
        if stored in _DISPLAY_GRADE_LABELS:
            return _unresolved(raw, 'grade_conflict', context=ctx, conflict=True)
        return display_field(raw, '—', state='preserved', reason='race_class_not_grade', context=ctx)
    if text in {'无分级', 'UN GRADED', 'UNGRADED'}:
        return display_field(raw, '无分级', context=ctx) if not stored else _unresolved(raw, 'grade_conflict', context=ctx, conflict=True)
    text = re.sub(r'^(?:重赏|重賞)\s*', '', text)
    compact = re.sub(r'[\s・.\-]', '', text)
    code = ''
    match = re.fullmatch(r'(JPN|JG|GROUP|GROUPE|GRADE|G)(III|II|I|[123])', compact)
    if match:
        system = match.group(1)
        number = {'I': '1', 'II': '2', 'III': '3'}.get(match.group(2), match.group(2))
        code = (system if system in {'JPN', 'JG'} else 'G') + number
    elif compact in {'L', 'LISTED', 'リステッド', 'リステッド競走'}:
        code = 'L'
    elif compact in {'OP', 'OPEN', 'オープン'}:
        code = 'OP'
    # 地方代码仅识别明确体系；不能把“香港一级赛”等转成国际等级。
    elif re.fullmatch(r'(?:HKG|SI|SII|SIII)[123]?', compact):
        return _unresolved(raw, 'local_grade_requires_profile', context=ctx)
    if not code:
        return _unresolved(raw, 'unverified_grade', context=ctx)
    if stored and stored != code:
        return _unresolved(raw, 'grade_conflict', context=ctx, conflict=True)
    return display_field(raw, _DISPLAY_GRADE_LABELS[code], code=code, context=ctx)


def parse_display_eligibility(raw):
    text = _display_text(raw)
    if not text:
        return _missing(raw)
    # 每个片段都必须可识别，不能丢掉额外资格条件。
    sex = ''
    for token, label in [('fillies and mares', '仅限雌马'), ('fillies', '仅限雌马'), ('牝馬', '仅限雌马'),
                         ('牝', '仅限雌马'), ('雌马', '仅限雌马')]:
        if token in text.lower():
            text = re.sub(re.escape(token), '', text, flags=re.I).strip(' ,、・')
            sex = label
            break
    match = re.fullmatch(r'(\d{1,2})\s*(?:yo|歳|岁)(\+|以上|及以上)?', text, re.I)
    if not match:
        return display_field(raw, sex) if sex and not text else _unresolved(raw)
    age, open_ended = int(match[1]), bool(match[2])
    if not 1 <= age <= 30:
        return _unresolved(raw, 'invalid_age')
    label = f'{age}岁' + ('及以上' if open_ended else '') + (f' · {sex}' if sex else '')
    return display_field(raw, label, min_age=age, max_age=None if open_ended else age, age_open_ended=open_ended)


def parse_display_weight(raw, *, unit_hint=''):
    text = _display_text(raw).lower()
    if not text:
        return _missing(raw)
    if re.fullmatch(r'\d+(?:\.\d+)?', text) and unit_hint in {'kg', 'lb'}:
        text += unit_hint
    match = re.fullmatch(r'(\d{1,3}(?:\.\d+)?)\s*(kg|千克|公斤|lb|lbs|磅)', text)
    if not match or not 0 < Decimal(match[1]) <= 1000:
        return _unresolved(raw, 'weight_unit_unknown', context={'unit': unit_hint})
    value = Fraction(match[1])
    if match[2] in {'kg', '千克', '公斤'}:
        label = _fraction_text(value) + '千克'
    else:
        kilos = value * Fraction('0.45359237')
        rounded = (kilos * 20 + 1) // 2
        label = _fraction_text(value) + f'磅（约{Decimal(rounded) / 10:.1f}千克）'
    return display_field(raw, label, context={'unit': unit_hint})


def parse_display_time(raw):
    text = _display_text(raw)
    if not text:
        return _missing(raw)
    match = re.fullmatch(r'(?:(\d{1,3})[:分])?(\d{1,2}(?:\.\d{1,6})?)(?:秒)?', text)
    if not match or Decimal(match[2]) >= 60 or Decimal(match[2]) < 0:
        return _unresolved(raw, 'time_format_unknown')
    if not match[1] and not text.endswith('秒'):
        return _unresolved(raw, 'time_format_unknown')
    seconds = match[2].lstrip('0') or '0'
    if seconds.startswith('.'):
        seconds = '0' + seconds
    return display_field(raw, (f'{int(match[1])}分' if match[1] else '') + seconds + '秒')


_DISPLAY_MARGINS = {'nose': '鼻差', 'nse': '鼻差', 'ハナ': '鼻差', '鼻差': '鼻差',
                    'head': '头差', 'hd': '头差', 'アタマ': '头差', '头差': '头差',
                    'neck': '颈差', 'nk': '颈差', 'クビ': '颈差', '颈差': '颈差',
                    'short head': '短头差', 'shd': '短头差', '同着': '同着', 'dead heat': '同着', 'dh': '同着'}


def parse_display_margin(raw, *, unit_hint='', basis=''):
    text = _display_text(raw).lower().replace('⁄', '/')
    if not text:
        return _missing(raw)
    if text in _DISPLAY_MARGINS:
        return display_field(raw, _DISPLAY_MARGINS[text], context={'basis': basis})
    original = str(raw)
    for symbol, val in [('½', '1/2'), ('¼', '1/4'), ('¾', '3/4')]:
        original = re.sub(rf'(?<=\d){symbol}', ' ' + val, original).replace(symbol, val)
    text = _display_text(original).lower()
    match = re.fullmatch(rf'({_NUMBER})\s*(lengths?|l|马身)?', text)
    try:
        if match and (match[2] or unit_hint == 'length'):
            value = _number_fraction(match[1])
            if value >= 0:
                return display_field(raw, _fraction_text(value) + '马身', context={'basis': basis})
    except (ValueError, ZeroDivisionError):
        pass
    return _unresolved(raw, 'margin_format_unknown')


def parse_display_number(raw, *, popularity=False):
    text = _display_text(raw)
    if not text:
        return _missing(raw)
    pattern = r'(?:第)?(\d{1,3})(?:番人気|热门|人气)?' if popularity else r'(\d{1,4}[A-Za-z]?)'
    match = re.fullmatch(pattern, text)
    if not match:
        return _unresolved(raw)
    value = match[1].upper()
    if popularity:
        return display_field(raw, f'第{int(value)}热门') if int(value) > 0 else _unresolved(raw)
    number = re.match(r'\d+', value)[0]
    return display_field(raw, str(int(number)) + value[len(number):])


def parse_display_odds(raw, *, odds_format=''):
    text = _display_text(raw)
    if not text:
        return _missing(raw)
    labels = {'decimal': '十进制', 'fractional': '分数', 'hong_kong': '香港'}
    if odds_format not in labels:
        return _unresolved(raw, 'odds_format_unknown')
    pattern = r'\d+/[1-9]\d*' if odds_format == 'fractional' else r'\d+(?:\.\d+)?'
    if not re.fullmatch(pattern, text):
        return _unresolved(raw, 'invalid_odds')
    value = Fraction(text)
    if value < (1 if odds_format == 'decimal' else 0):
        return _unresolved(raw, 'invalid_odds')
    return display_field(raw, f'{text}（{labels[odds_format]}）', context={'format': odds_format})


def parse_display_surface(raw):
    text = _display_text(raw).lower()
    labels = {'turf': '草地', '芝': '草地', '草地': '草地', 'dirt': '泥地', 'ダート': '泥地', '泥地': '泥地',
              'synthetic': '复合赛道', '复合赛道': '复合赛道'}
    if not text:
        return _missing(raw)
    return display_field(raw, labels[text]) if text in labels else _unresolved(raw, 'surface_context_unknown')


def parse_display_layout(raw):
    text = _display_text(raw)
    if not text:
        return _missing(raw)
    labels = {'left': '左转', '左回り': '左转', '左': '左转', '左转': '左转',
              'right': '右转', '右回り': '右转', '右': '右转', '右转': '右转',
              'inner': '内圈', '内回り': '内圈', '内': '内圈', '内圈': '内圈',
              'outer': '外圈', '外回り': '外圈', '外': '外圈', '外圈': '外圈', 'straight': '直道', '直道': '直道'}
    tokens = re.split(r'[ /・,、]+', text.lower())
    if all(t in labels for t in tokens):
        values = list(dict.fromkeys(labels[t] for t in tokens))
        if {'左转','右转'} <= set(values) or {'内圈','外圈'} <= set(values):
            return _unresolved(raw, 'layout_conflict', conflict=True)
        return display_field(raw, ' · '.join(values))
    return _unresolved(raw, 'layout_unknown')


def parse_display_race_type(raw):
    text = _display_text(raw).lower()
    labels = {'jumps':'障碍','障害':'障碍','障碍':'障碍','flat':'平地','平地':'平地',
              'hurdle':'栏架障碍','steeplechase':'越野障碍','越野障碍':'越野障碍'}
    if not text:
        return _missing(raw)
    return display_field(raw, labels[text]) if text in labels else _unresolved(raw, 'race_type_unknown')


def parse_display_money(raw, *, currency='', kind=''):
    text = _display_text(raw)
    if not text:
        return display_field(raw, state='missing', reason='unsupported_missing_source')
    currencies = {'USD':'美元','GBP':'英镑','EUR':'欧元','JPY':'日元','HKD':'港元','CNY':'人民币元'}
    if currency not in currencies or kind not in {'total','winner'}:
        return _unresolved(raw, 'money_context_unknown', context={'currency':currency,'kind':kind})
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', text):
        return _unresolved(raw, 'money_format_unknown')
    return display_field(raw, _fraction_text(Fraction(text))+currencies[currency], context={'currency':currency,'kind':kind})
