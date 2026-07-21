from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from stable.models import HorseCareerRecordAuthorityStatus, RacingRegion


PAYLOAD_SCHEMA_VERSION = "p0-horse-completion.v1"
SOURCE_CACHE_SCHEMA_VERSION = "p0-horse-source-cache.v2"
ARTIFACT_SCHEMA_VERSION = "p0-horse-completion-artifact.v1"
BATCH_MANIFEST_SCHEMA_VERSION = "p0-horse-completion-batch-manifest.v1"
REVIEWED_CANDIDATE_DECISION = "confirm_batch_inclusion"
REVIEWED_CANDIDATE_REGIONS = (
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
)
REVIEWED_CANDIDATE_REQUEST_BUDGETS = {
    RacingRegion.JAPAN: 3,
    RacingRegion.HONG_KONG: 1,
    RacingRegion.UNITED_KINGDOM: 1,
    RacingRegion.FRANCE: 2,
    RacingRegion.UNITED_STATES: 3,
}
REVIEWED_CANDIDATE_REQUIRED_FIELDS = {
    "sample_region",
    "sample_rank",
    "candidate_key",
    "horse_name",
    "aliases",
    "identity_status",
    "review_status",
    "matched_profile_ids",
    "identity_keys",
    "source_namespace",
    "source_namespaces",
    "source_urls",
    "event_regions",
    "reviewed",
    "review_decision",
    "review_notes",
}
REQUIRED_BASIC_PROFILE_FIELDS = (
    "country",
    "sex",
    "color",
    "birth_date",
    "owner_name",
    "trainer_name",
    "breeder_name",
)
REQUIRED_PEDIGREE_FIELDS = (
    "sire",
    "dam",
    "sire_sire",
    "sire_dam",
    "dam_sire",
    "dam_dam",
)
MODULE_NAMES = ("basic_profile", "pedigree", "race_records", "major_wins")
ACTUAL_START_STATUSES = {
    "won",
    "placed",
    "unplaced",
    "did_not_finish",
    "disqualified",
}
NONSTART_STATUSES = {"scratched", "withdrawn"}
MANUAL_SUPPLEMENT_OUTCOME_STATUSES = frozenset(
    {"applied", "already_applied", "blocked", "ignored"}
)
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


class P0HorseCompletionError(ValueError):
    pass


class P0HorseCompletionNetworkDisabled(P0HorseCompletionError):
    pass


class P0HorseCompletionSourceError(P0HorseCompletionError):
    pass


class P0HorseCompletionBatchError(P0HorseCompletionError):
    pass


class P0HorseCompletionSourceClient(Protocol):
    def fetch(self, request: "P0HorseCompletionRequest") -> dict[str, Any]:
        ...


def _source_client_request_count(
    source_client: P0HorseCompletionSourceClient,
) -> int:
    try:
        value = getattr(source_client, "last_request_count")
    except AttributeError:
        return 1
    return 1 if value is None else int(value)


class _PerCandidateSourceClient:
    def __init__(self, delegate: P0HorseCompletionSourceClient):
        self.delegate = delegate
        self.last_request_count = 0

    def fetch(self, request: "P0HorseCompletionRequest") -> dict[str, Any]:
        try:
            return self.delegate.fetch(request)
        finally:
            self.last_request_count = _source_client_request_count(self.delegate)

    def fetch_source_payload(
        self,
        request: "P0HorseCompletionRequest",
    ) -> dict[str, Any]:
        fetch_source_payload = getattr(
            self.delegate,
            "fetch_source_payload",
            None,
        )
        try:
            if callable(fetch_source_payload):
                return fetch_source_payload(request)
            return self.delegate.fetch(request)
        finally:
            self.last_request_count = _source_client_request_count(self.delegate)

    def apply_manual_supplements(
        self,
        payload: dict[str, Any],
        request: "P0HorseCompletionRequest",
    ) -> dict[str, Any]:
        apply_supplements = getattr(
            self.delegate,
            "apply_manual_supplements",
            None,
        )
        if not callable(apply_supplements):
            return payload
        return apply_supplements(payload, request)

    def has_manual_supplements(
        self,
        request: "P0HorseCompletionRequest",
    ) -> bool:
        has_supplements = getattr(
            self.delegate,
            "has_manual_supplements",
            None,
        )
        return bool(
            callable(has_supplements)
            and has_supplements(request)
        )


@dataclass(frozen=True)
class P0HorseCompletionRequest:
    candidate_key: str
    region: str
    horse_name: str
    source_url: str
    external_horse_id: str = ""
    candidate_source_name: str = ""
    expected_sire_name: str = ""
    expected_dam_name: str = ""
    expected_birth_year: int | None = None
    cache_path: str = ""
    allow_network: bool = False
    request_interval_seconds: float = 8.0
    request_budget: int = 1
    batch_limit: int = 10

    def __post_init__(self) -> None:
        if self.region not in REGION_ADAPTERS:
            raise P0HorseCompletionSourceError(f"unsupported P0 horse region: {self.region}")
        if self.request_interval_seconds < 0:
            raise P0HorseCompletionSourceError("request_interval_seconds must not be negative")
        if self.request_budget <= 0:
            raise P0HorseCompletionSourceError("request_budget must be greater than zero")
        if self.batch_limit <= 0:
            raise P0HorseCompletionSourceError("batch_limit must be greater than zero")
        if (
            self.expected_birth_year is not None
            and (
                isinstance(self.expected_birth_year, bool)
                or not isinstance(self.expected_birth_year, int)
                or not 1800 <= self.expected_birth_year <= datetime.now(timezone.utc).year
            )
        ):
            raise P0HorseCompletionSourceError("expected_birth_year is invalid")


@dataclass(frozen=True)
class RegionAdapter:
    key: str
    region: str
    source_names: frozenset[str]

    def normalize(
        self,
        source_payload: dict[str, Any],
        request: P0HorseCompletionRequest,
    ) -> dict[str, Any]:
        return _normalize_source_payload(source_payload, request=request, adapter=self)


REGION_ADAPTERS = {
    RacingRegion.JAPAN: RegionAdapter(
        key="japan_jbis",
        region=RacingRegion.JAPAN,
        source_names=frozenset({"jbis", "jra", "netkeiba", "nar"}),
    ),
    RacingRegion.HONG_KONG: RegionAdapter(
        key="hong_kong_hkjc",
        region=RacingRegion.HONG_KONG,
        source_names=frozenset({"hkjc"}),
    ),
    RacingRegion.UNITED_KINGDOM: RegionAdapter(
        key="united_kingdom_sporting_life",
        region=RacingRegion.UNITED_KINGDOM,
        source_names=frozenset({"sporting_life", "racing_post"}),
    ),
    RacingRegion.FRANCE: RegionAdapter(
        key="france_geny",
        region=RacingRegion.FRANCE,
        source_names=frozenset({"geny", "france_galop"}),
    ),
    RacingRegion.UNITED_STATES: RegionAdapter(
        key="united_states_equibase",
        region=RacingRegion.UNITED_STATES,
        source_names=frozenset({"equibase", "hrn"}),
    ),
}


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def _normalized_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def _valid_http_url(value: Any) -> bool:
    try:
        _HTTP_URL_VALIDATOR(str(value or "").strip())
    except ValidationError:
        return False
    return True


def _deduplicate_strings(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = _normalized_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _normalize_aliases(
    aliases: Any,
    *,
    horse_name: str,
) -> list[dict[str, Any]]:
    rows = [row for row in aliases if isinstance(row, dict)] if isinstance(aliases, list) else []
    original = next(
        (
            row
            for row in rows
            if row.get("is_original") and str(row.get("name") or "").strip()
        ),
        None,
    )
    ordered: list[dict[str, Any]] = []
    if original:
        ordered.append(original)
    ordered.extend(rows)
    if horse_name and not any(
        _normalized_text(row.get("name")) == _normalized_text(horse_name)
        for row in rows
    ):
        ordered.insert(0, {"name": horse_name, "language": "", "is_original": True})

    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ordered:
        name = str(row.get("name") or "").strip()
        key = _normalized_text(name)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "name": name,
                "language": str(row.get("language") or "").strip(),
                "is_original": bool(row.get("is_original")),
            }
        )
    if output:
        output[0]["is_original"] = True
    return output


def _parse_date_precision(value: Any) -> tuple[str | None, int | None, str]:
    text = str(value or "").strip()
    if not text:
        return None, None, "unknown"
    if re.fullmatch(r"\d{4}", text):
        return None, int(text), "year"
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None, None, "unknown"
    return parsed.isoformat(), parsed.year, "exact"


def _result_status(value: Any) -> str:
    normalized = _normalized_text(value).replace(".", "")
    if not normalized:
        return "unknown"
    if normalized.isdigit():
        finish = int(normalized)
        if finish == 1:
            return "won"
        if finish in {2, 3}:
            return "placed"
        return "unplaced"
    status_map = {
        "won": "won",
        "win": "won",
        "placed": "placed",
        "finished": "unplaced",
        "unplaced": "unplaced",
        "dnf": "did_not_finish",
        "pu": "did_not_finish",
        "ur": "did_not_finish",
        "unseated rider": "did_not_finish",
        "unseatedrider": "did_not_finish",
        "f": "did_not_finish",
        "fell": "did_not_finish",
        "bd": "did_not_finish",
        "brought down": "did_not_finish",
        "broughtdown": "did_not_finish",
        "ref": "did_not_finish",
        "ro": "did_not_finish",
        "su": "did_not_finish",
        "did not finish": "did_not_finish",
        "did_not_finish": "did_not_finish",
        "dsq": "disqualified",
        "dq": "disqualified",
        "disqualified": "disqualified",
        "scr": "scratched",
        "scratched": "scratched",
        "nr": "scratched",
        "non runner": "scratched",
        "non-runner": "scratched",
        "wv": "withdrawn",
        "wd": "withdrawn",
        "withdrawn": "withdrawn",
    }
    return status_map.get(normalized, "unknown")


def _start_status(result_status: str) -> str:
    if result_status in ACTUAL_START_STATUSES:
        return "started"
    if result_status in NONSTART_STATUSES:
        return "did_not_start"
    return "unconfirmed"


def _source_reference(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_name",
        "source_url",
        "external_horse_id",
        "external_race_id",
        "external_result_id",
        "race_name",
        "racecourse",
        "race_number",
        "distance_text",
    )
    return {
        key: record[key]
        for key in keys
        if record.get(key) not in ("", None, {})
    }


def _race_merge_key(record: dict[str, Any]) -> str:
    horse_key = _normalized_text(record.get("horse_identity_key"))
    race_date = str(record.get("race_date") or "")
    racecourse = _normalized_text(record.get("racecourse"))
    if not horse_key or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", race_date) or not racecourse:
        return ""

    race_number = _normalized_text(record.get("race_number"))
    if race_number:
        identity = ("venue-slot", horse_key, race_date, racecourse, race_number)
    else:
        race_name = _normalized_text(record.get("race_name"))
        distance = _normalized_text(record.get("distance_text"))
        if not race_name or not distance:
            return ""
        identity = ("race-facts", horse_key, race_date, racecourse, race_name, distance)
    return hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest()


def _normalize_race_record(record: dict[str, Any]) -> dict[str, Any]:
    race_date, race_year, date_precision = _parse_date_precision(record.get("race_date"))
    result_status = _result_status(record.get("result_status") or record.get("finish"))
    explicit_start_status = _normalized_text(record.get("start_status")).replace(
        " ",
        "_",
    )
    start_status = (
        explicit_start_status
        if explicit_start_status in {"started", "did_not_start", "unconfirmed"}
        else _start_status(result_status)
    )
    source_name = str(record.get("source_name") or "").strip()
    source_url = str(record.get("source_url") or "").strip()
    normalized = {
        **deepcopy(record),
        "race_name": str(record.get("race_name") or "").strip(),
        "race_date": race_date,
        "race_year": race_year,
        "race_date_precision": date_precision,
        "racecourse": str(record.get("racecourse") or "").strip(),
        "race_number": str(record.get("race_number") or "").strip(),
        "distance_text": str(record.get("distance_text") or "").strip(),
        "finish_position": str(record.get("finish_position") or record.get("finish") or "").strip(),
        "result_status": result_status,
        "start_status": start_status,
        "event_id": record.get("event_id"),
        "result_id": record.get("result_id"),
        "source_name": source_name,
        "source_url": source_url,
        "is_overseas": bool(record.get("is_overseas")),
    }
    normalized.pop("finish", None)
    reference = _source_reference(normalized)
    incoming_refs = record.get("source_refs") if isinstance(record.get("source_refs"), dict) else {}
    sources = [
        deepcopy(item)
        for item in incoming_refs.get("sources", [])
        if isinstance(item, dict)
    ]
    if reference:
        sources.append(reference)
    normalized["source_refs"] = {
        **{key: deepcopy(value) for key, value in incoming_refs.items() if key != "sources"},
        "sources": _deduplicate_source_references(sources),
    }
    return normalized


def summarize_p0_horse_race_record_counts(
    records: Iterable[dict[str, Any]],
) -> dict[str, int]:
    normalized_records = [
        _normalize_race_record(record)
        for record in records
        if isinstance(record, dict)
    ]
    return {
        "actual_start_count": sum(
            record["start_status"] == "started"
            for record in normalized_records
        ),
        "nonstarter_count": sum(
            record["start_status"] == "did_not_start"
            for record in normalized_records
        ),
        "unconfirmed_count": sum(
            record["start_status"] == "unconfirmed"
            for record in normalized_records
        ),
        "abnormal_official_status_count": sum(
            record["result_status"] in {"did_not_finish", "disqualified"}
            for record in normalized_records
        ),
        "overseas_start_count": sum(
            record["start_status"] == "started" and record.get("is_overseas")
            for record in normalized_records
        ),
    }


def _source_reference_key(source: dict[str, Any]) -> str:
    url = str(source.get("source_url") or "").strip()
    if url:
        return f"url:{url}"
    return json.dumps(
        {
            key: source.get(key, "")
            for key in (
                "source_name",
                "external_horse_id",
                "external_race_id",
                "external_result_id",
            )
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _deduplicate_source_references(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict) or not source:
            continue
        key = _source_reference_key(source)
        if key in deduplicated:
            deduplicated[key].update(
                {
                    name: deepcopy(value)
                    for name, value in source.items()
                    if value not in ("", None, {})
                }
            )
        else:
            deduplicated[key] = deepcopy(source)
    return [deduplicated[key] for key in sorted(deduplicated)]


def _result_field_evidence(record: dict[str, Any]) -> dict[str, Any]:
    evidence = record.get("field_evidence")
    if not isinstance(evidence, list):
        return {}
    return next(
        (
            deepcopy(item)
            for item in evidence
            if isinstance(item, dict) and item.get("field_name") == "result"
        ),
        {},
    )


def _usable_evidence_layer(layer: Any) -> bool:
    if not isinstance(layer, dict):
        return False
    return str(layer.get("status") or "").strip() not in {
        "",
        "unknown",
        "not_collected",
        "not_applied",
        "blocked",
    }


def _incoming_result_evidence_layer(
    incoming: dict[str, Any],
    *,
    normalized: bool,
) -> dict[str, Any]:
    source_url = str(incoming.get("source_url") or "").strip()
    observed_at = str(incoming.get("source_fetched_at") or "").strip()
    if normalized:
        return {
            "value": incoming.get("result_status"),
            "status": "mapped",
            "source_name": "umanews",
            "source_url": source_url,
            "observed_at": observed_at,
            "conversion_rule": "cross_source_result_status_merge_v1",
        }
    return {
        "value": incoming.get("finish_position"),
        "status": "observed",
        "source_name": str(incoming.get("source_name") or "").strip(),
        "source_url": source_url,
        "observed_at": observed_at,
        "conversion_rule": "cross_source_result_value_merge_v1",
    }


def _merge_formal_result_field_evidence(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_rows = [
        deepcopy(item)
        for item in existing.get("field_evidence") or []
        if isinstance(item, dict)
    ]
    incoming_rows = [
        deepcopy(item)
        for item in incoming.get("field_evidence") or []
        if isinstance(item, dict)
    ]
    existing_result = _result_field_evidence(existing)
    incoming_result = _result_field_evidence(incoming)
    direct_raw = deepcopy(existing_result.get("direct_raw") or {})
    if not direct_raw:
        direct_raw = deepcopy(incoming_result.get("direct_raw") or {})
    if not direct_raw:
        direct_raw = _incoming_result_evidence_layer(incoming, normalized=False)

    canonical_raw = deepcopy(incoming_result.get("canonical_raw") or {})
    if not _usable_evidence_layer(canonical_raw):
        canonical_raw = _incoming_result_evidence_layer(incoming, normalized=False)
    normalized = deepcopy(incoming_result.get("normalized") or {})
    if not _usable_evidence_layer(normalized):
        normalized = _incoming_result_evidence_layer(incoming, normalized=True)

    merged_rows = [
        item for item in existing_rows if item.get("field_name") != "result"
    ]
    existing_names = {
        str(item.get("field_name") or "")
        for item in merged_rows
    }
    merged_rows.extend(
        item
        for item in incoming_rows
        if item.get("field_name") != "result"
        and str(item.get("field_name") or "") not in existing_names
    )
    merged_rows.append(
        {
            "field_name": "result",
            "direct_raw": direct_raw,
            "canonical_raw": canonical_raw,
            "normalized": normalized,
        }
    )
    return merged_rows


def _merge_race_records(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, value in incoming.items():
        if key == "source_refs":
            continue
        if merged.get(key) in ("", None, {}, []) and value not in ("", None, {}, []):
            merged[key] = deepcopy(value)
    existing_result = _normalized_text(existing.get("result_status"))
    incoming_result = _normalized_text(incoming.get("result_status"))
    if existing_result in {"", "unknown"} and incoming_result not in {"", "unknown"}:
        for key in (
            "result_status",
            "finish_position",
            "result_evidence_status",
            "official_result_code",
            "official_result_reason",
        ):
            if incoming.get(key) not in ("", None, {}, []):
                merged[key] = deepcopy(incoming[key])
        if _normalized_text(existing.get("start_status")) in {"", "unconfirmed"}:
            merged["start_status"] = deepcopy(incoming.get("start_status"))
        merged["field_evidence"] = _merge_formal_result_field_evidence(
            existing,
            incoming,
        )
    sources = [
        *existing.get("source_refs", {}).get("sources", []),
        *incoming.get("source_refs", {}).get("sources", []),
    ]
    merged["source_refs"] = {
        **deepcopy(existing.get("source_refs", {})),
        **{
            key: deepcopy(value)
            for key, value in incoming.get("source_refs", {}).items()
            if key != "sources"
        },
        "sources": _deduplicate_source_references(sources),
    }
    merged["is_overseas"] = bool(existing.get("is_overseas") or incoming.get("is_overseas"))
    return merged


def _race_records_are_merge_compatible(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> bool:
    left_result = _normalized_text(existing.get("result_status"))
    right_result = _normalized_text(incoming.get("result_status"))
    if (
        left_result not in {"", "unknown"}
        and right_result not in {"", "unknown"}
        and left_result != right_result
    ):
        return False
    left_finish = _normalized_text(existing.get("finish_position"))
    right_finish = _normalized_text(incoming.get("finish_position"))
    left_finish_unresolved = not left_finish or left_result in {"", "unknown"}
    right_finish_unresolved = not right_finish or right_result in {"", "unknown"}
    if (
        not left_finish_unresolved
        and not right_finish_unresolved
        and left_finish != right_finish
    ):
        return False
    return True


def normalize_p0_horse_race_records(
    records: Iterable[dict[str, Any]],
    *,
    source_start_count: int | None,
    official_start_count_source: str = "",
    official_start_count_source_url: str = "",
    official_start_count_verified_at: str = "",
    record_authority_status: str = "unknown",
) -> dict[str, Any]:
    record_authority_status = str(record_authority_status or "unknown").strip()
    if record_authority_status not in HorseCareerRecordAuthorityStatus.values:
        raise P0HorseCompletionSourceError(
            "unsupported record authority status: "
            f"{record_authority_status}"
        )
    normalized_records: list[dict[str, Any]] = []
    merge_indexes: dict[str, int] = {}
    deduplicated_count = 0

    for raw_record in records:
        if not isinstance(raw_record, dict):
            continue
        record = _normalize_race_record(raw_record)
        merge_key = _race_merge_key(record)
        if merge_key and merge_key in merge_indexes:
            index = merge_indexes[merge_key]
            if _race_records_are_merge_compatible(normalized_records[index], record):
                normalized_records[index] = _merge_race_records(
                    normalized_records[index], record
                )
                deduplicated_count += 1
                continue
        if merge_key:
            merge_indexes.setdefault(merge_key, len(normalized_records))
        normalized_records.append(record)

    record_counts = summarize_p0_horse_race_record_counts(normalized_records)
    collected_start_count = record_counts["actual_start_count"]
    unconfirmed_count = record_counts["unconfirmed_count"]
    overseas_start_count = record_counts["overseas_start_count"]
    blocker_reasons: list[str] = []
    missing_start_count: int | None = None
    excess_start_count = 0
    start_count_delta: int | None = None
    if source_start_count is None:
        blocker_reasons.append("source_start_count_unknown")
        gap_count = 1
    else:
        start_count_delta = collected_start_count - int(source_start_count)
        missing_start_count = max(-start_count_delta, 0)
        excess_start_count = max(start_count_delta, 0)
        gap_count = missing_start_count + excess_start_count
        if missing_start_count:
            blocker_reasons.append("source_start_count_mismatch")
            blocker_reasons.append(
                f"source_start_count_missing:{missing_start_count}"
            )
        elif excess_start_count:
            blocker_reasons.append("source_start_count_mismatch")
            blocker_reasons.append(
                f"source_start_count_exceeded:{excess_start_count}"
            )
    if unconfirmed_count:
        blocker_reasons.append("unconfirmed_start_status")
        gap_count += unconfirmed_count

    if source_start_count is not None:
        if not str(official_start_count_source or "").strip():
            blocker_reasons.append("official_start_count_source_missing")
        if not _valid_http_url(official_start_count_source_url):
            blocker_reasons.append("official_start_count_source_url_missing")
        try:
            verified_at = datetime.fromisoformat(
                str(official_start_count_verified_at or "").replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            verified_at = None
        if verified_at is None or verified_at.utcoffset() is None:
            blocker_reasons.append("official_start_count_verified_at_missing")

    missing_core_count = sum(
        not record["race_name"]
        or record["race_date_precision"] != "exact"
        or not record["racecourse"]
        or not record["source_name"]
        or not _valid_http_url(record["source_url"])
        for record in normalized_records
    )
    if missing_core_count:
        blocker_reasons.append("race_record_core_evidence_missing")
        gap_count += missing_core_count

    if (
        record_authority_status
        == HorseCareerRecordAuthorityStatus.COUNT_ALIGNED_RECORDS_UNVERIFIED
    ):
        blocker_reasons.append(
            "official_count_aligned_per_record_authority_pending:"
            f"{official_start_count_source or 'unknown'}"
        )
    elif (
        record_authority_status
        == HorseCareerRecordAuthorityStatus.SOURCE_BLOCKED
    ):
        blocker_reasons.append(
            "official_per_record_source_blocked:"
            f"{official_start_count_source or 'unknown'}"
        )
    elif (
        record_authority_status
        != HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED
    ):
        blocker_reasons.append("per_record_authority_unknown")

    status = "complete" if not blocker_reasons else "partial"
    return {
        "race_records": normalized_records,
        "career_history": {
            "status": status,
            "official_or_source_start_count": source_start_count,
            "official_start_count_source": official_start_count_source,
            "official_start_count_source_url": official_start_count_source_url,
            "official_start_count_verified_at": (
                official_start_count_verified_at or None
            ),
            "record_authority_status": record_authority_status,
            "collected_start_count": collected_start_count,
            "gap_count": gap_count,
            "missing_start_count": missing_start_count,
            "excess_start_count": excess_start_count,
            "start_count_delta": start_count_delta,
            "linked_race_event_count": sum(
                bool(record.get("event_id")) for record in normalized_records
            ),
            "unlinked_race_record_count": sum(
                not record.get("event_id") for record in normalized_records
            ),
            "overseas_start_count": overseas_start_count,
            "deduplicated_source_record_count": deduplicated_count,
            "blocker_reasons": _deduplicate_strings(blocker_reasons),
        },
    }


def _coverage_group(payload: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    required = list(fields)
    missing = [field for field in required if payload.get(field) in ("", None)]
    present_count = len(required) - len(missing)
    return {
        "complete": not missing,
        "missing_fields": missing,
        "present_count": present_count,
        "required_count": len(required),
        "coverage_ratio": round(present_count / len(required), 4) if required else 1.0,
    }


def _candidate_source_name(request: P0HorseCompletionRequest) -> str:
    explicit = str(request.candidate_source_name or "").strip()
    candidate_key = str(request.candidate_key or "")
    key_source = ""
    if candidate_key.startswith("external:"):
        parts = candidate_key.split(":", 2)
        if len(parts) == 3:
            key_source = parts[1].strip()
    if (
        explicit
        and key_source
        and _normalized_text(explicit) != _normalized_text(key_source)
    ):
        raise P0HorseCompletionSourceError(
            "candidate source namespace conflicts with candidate key"
        )
    return explicit or key_source


def _require_expected_identity_matches_payload(
    request: P0HorseCompletionRequest,
    identity: dict[str, Any],
    aliases: Any,
    target_source_name: str,
    target_external_horse_id: str,
) -> None:
    source_horse_name = str(identity.get("horse_name") or "").strip()
    if not source_horse_name:
        raise P0HorseCompletionSourceError(
            "identity_incomplete: source payload horse_name"
        )
    source_names = {_normalized_text(source_horse_name)}
    if isinstance(aliases, list):
        for alias in aliases:
            alias_name = alias.get("name") if isinstance(alias, dict) else alias
            normalized_alias = _normalized_text(alias_name)
            if normalized_alias:
                source_names.add(normalized_alias)
    if _normalized_text(request.horse_name) not in source_names:
        raise P0HorseCompletionSourceError(
            "identity_mismatch: source payload horse_name"
        )

    expected = {
        "horse_name": request.horse_name,
        "sire_name": request.expected_sire_name,
        "dam_name": request.expected_dam_name,
        "birth_year": request.expected_birth_year,
    }
    candidate_source_name = _candidate_source_name(request)
    has_provider_bound_identity = (
        bool(candidate_source_name)
        and _normalized_text(candidate_source_name)
        == _normalized_text(target_source_name)
        and str(request.external_horse_id or "").strip()
        == target_external_horse_id
        and bool(target_external_horse_id)
    )
    must_lock_identity = (
        not has_provider_bound_identity
        or request.region == RacingRegion.UNITED_STATES
        or any(
            expected[field] not in ("", None)
            for field in ("sire_name", "dam_name", "birth_year")
        )
    )
    if not must_lock_identity:
        return
    if any(expected[field] in ("", None) for field in expected):
        raise P0HorseCompletionSourceError(
            "identity_incomplete: expected horse_name, sire_name, dam_name, "
            "and birth_year"
        )
    for field in ("sire_name", "dam_name", "birth_year"):
        expected_value = expected[field]
        actual_value = identity.get(field)
        if actual_value in ("", None):
            raise P0HorseCompletionSourceError(
                f"identity_incomplete: source payload {field}"
            )
        if _normalized_text(expected_value) != _normalized_text(actual_value):
            raise P0HorseCompletionSourceError(
                f"identity_mismatch: source payload {field}"
            )


def _provider_bound_identity_key(provider: str, external_horse_id: str) -> str:
    if not provider or not external_horse_id:
        return ""
    return f"{provider}:{external_horse_id}"


def _pedigree_identity_key(identity: dict[str, Any]) -> str:
    fields = ("horse_name", "sire_name", "dam_name", "birth_year")
    values = [_normalized_text(identity.get(field)) for field in fields]
    if not all(values):
        return ""
    digest = hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()
    return f"pedigree:{digest}"


def _identity_source_evidence(
    *,
    candidate_source_name: str,
    candidate_source_url: str,
    candidate_external_horse_id: str,
    target_source_name: str,
    target_source_url: str,
    target_external_horse_id: str,
    target_fetched_at: str,
    adapter_key: str,
    supplemental_sources: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "source_name": target_source_name,
            "source_url": target_source_url,
            "external_horse_id": target_external_horse_id,
            "fetched_at": target_fetched_at,
            "adapter_key": adapter_key,
            "evidence_role": "completion_source",
        }
    ]
    if candidate_source_name and (
        candidate_external_horse_id or _valid_http_url(candidate_source_url)
    ):
        rows.append(
            {
                "source_name": candidate_source_name,
                "source_url": candidate_source_url,
                "external_horse_id": candidate_external_horse_id,
                "fetched_at": "",
                "adapter_key": "",
                "evidence_role": "reviewed_candidate",
            }
        )
    for source in supplemental_sources:
        if not isinstance(source, dict):
            continue
        evidence_role = str(
            source.get("evidence_role")
            or "supplemental_completion_source"
        ).strip()
        row = {
            "source_name": str(source.get("name") or "").strip(),
            "source_url": str(source.get("url") or "").strip(),
            "external_horse_id": str(
                source.get("external_horse_id") or ""
            ).strip(),
            "fetched_at": str(source.get("fetched_at") or "").strip(),
            "adapter_key": (
                "" if evidence_role == "manual_supplement" else adapter_key
            ),
            "evidence_role": evidence_role,
        }
        for field in (
            "entry_method",
            "entered_by",
            "reviewer",
            "field_group",
            "field_name",
            "evidence_note",
            "review_notes",
        ):
            value = str(source.get(field) or "").strip()
            if value:
                row[field] = value
        rows.append(row)

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = (
            str(row["source_name"]),
            str(row["external_horse_id"]),
            str(row["source_url"]),
            str(row["evidence_role"]),
            str(row.get("field_group") or ""),
            str(row.get("field_name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _normalize_source_payload(
    source_payload: dict[str, Any],
    *,
    request: P0HorseCompletionRequest,
    adapter: RegionAdapter,
) -> dict[str, Any]:
    if not isinstance(source_payload, dict):
        raise P0HorseCompletionSourceError("source payload must be an object")
    if source_payload.get("schema_version") != SOURCE_CACHE_SCHEMA_VERSION:
        raise P0HorseCompletionSourceError("source payload schema is unsupported")
    if source_payload.get("region") != request.region:
        raise P0HorseCompletionSourceError("source payload region does not match request")
    if source_payload.get("adapter_key") != adapter.key:
        raise P0HorseCompletionSourceError("source payload adapter does not match request")

    source = source_payload.get("source") if isinstance(source_payload.get("source"), dict) else {}
    source_name = str(source.get("name") or "").strip()
    if source_name not in adapter.source_names:
        raise P0HorseCompletionSourceError("source payload provider is not allowed for region")
    candidate_source_name = _candidate_source_name(request)
    candidate_external_horse_id = str(request.external_horse_id or "").strip()
    target_external_horse_id = str(source.get("external_horse_id") or "").strip()
    if (
        candidate_source_name
        and _normalized_text(candidate_source_name)
        == _normalized_text(source_name)
        and candidate_external_horse_id
        and target_external_horse_id
        and candidate_external_horse_id != target_external_horse_id
    ):
        raise P0HorseCompletionSourceError(
            "source payload external horse ID conflicts with the same-provider candidate"
        )
    identity = (
        deepcopy(source_payload.get("identity"))
        if isinstance(source_payload.get("identity"), dict)
        else {}
    )
    _require_expected_identity_matches_payload(
        request,
        identity,
        source_payload.get("aliases"),
        source_name,
        target_external_horse_id,
    )
    horse_name = str(identity.get("horse_name") or "").strip()
    identity["horse_name"] = horse_name
    candidate_identity_key = _provider_bound_identity_key(
        candidate_source_name,
        candidate_external_horse_id,
    )
    target_identity_key = _provider_bound_identity_key(
        source_name,
        target_external_horse_id,
    )
    identity_keys = _deduplicate_strings(
        [candidate_identity_key, target_identity_key]
    )
    identity.update(
        {
            "source_name": source_name,
            "external_horse_id": target_external_horse_id,
            "candidate_source_name": candidate_source_name,
            "candidate_external_horse_id": candidate_external_horse_id,
            "identity_keys": identity_keys,
        }
    )
    profile_source_url = str(source.get("url") or "").strip()

    career = (
        source_payload.get("career")
        if isinstance(source_payload.get("career"), dict)
        else {}
    )
    raw_records = career.get("records", [])
    enriched_records = []
    pedigree_identity_key = _pedigree_identity_key(identity)
    horse_identity_key = (
        f"external:{source_name}:{target_external_horse_id}"
        if target_identity_key
        else pedigree_identity_key or request.candidate_key
    )
    for raw_record in raw_records if isinstance(raw_records, list) else []:
        if not isinstance(raw_record, dict):
            continue
        enriched_records.append(
            {
                **deepcopy(raw_record),
                "horse_identity_key": horse_identity_key,
                "source_name": source_name,
                "external_horse_id": target_external_horse_id,
                "source_fetched_at": str(source.get("fetched_at") or "").strip(),
            }
        )
    source_start_count = career.get("source_start_count")
    if source_start_count is not None:
        try:
            source_start_count = int(source_start_count)
        except (TypeError, ValueError) as exc:
            raise P0HorseCompletionSourceError("source start count must be an integer") from exc
        if source_start_count < 0:
            raise P0HorseCompletionSourceError(
                "source start count must not be negative"
            )
    normalized_career = normalize_p0_horse_race_records(
        enriched_records,
        source_start_count=source_start_count,
        official_start_count_source=str(
            career.get("official_start_count_source") or ""
        ).strip(),
        official_start_count_source_url=str(
            career.get("official_start_count_source_url")
            or career.get("source_url")
            or ""
        ).strip(),
        official_start_count_verified_at=str(
            career.get("official_start_count_verified_at")
            or career.get("verified_at")
            or ""
        ).strip(),
        record_authority_status=str(
            career.get("record_authority_status") or "unknown"
        ).strip(),
    )
    basic_profile = (
        deepcopy(source_payload.get("basic_profile"))
        if isinstance(source_payload.get("basic_profile"), dict)
        else {}
    )
    pedigree = (
        deepcopy(source_payload.get("pedigree"))
        if isinstance(source_payload.get("pedigree"), dict)
        else {}
    )
    aliases = _normalize_aliases(source_payload.get("aliases"), horse_name=horse_name)
    source_evidence = _identity_source_evidence(
        candidate_source_name=candidate_source_name,
        candidate_source_url=str(request.source_url or "").strip(),
        candidate_external_horse_id=candidate_external_horse_id,
        target_source_name=source_name,
        target_source_url=profile_source_url,
        target_external_horse_id=target_external_horse_id,
        target_fetched_at=str(source.get("fetched_at") or "").strip(),
        adapter_key=adapter.key,
        supplemental_sources=(
            source_payload.get("supplemental_sources", [])
            if isinstance(
                source_payload.get("supplemental_sources"),
                list,
            )
            else ()
        ),
    )
    complete_pedigree_identity = all(
        identity.get(field)
        for field in ("horse_name", "sire_name", "dam_name", "birth_year")
    )
    race_records = normalized_career["race_records"]
    major_wins = [
        {
            "race_name": record["race_name"],
            "race_date": record["race_date"],
            "race_year": record["race_year"],
            "source_name": record["source_name"],
            "source_url": record["source_url"],
        }
        for record in race_records
        if record["result_status"] == "won"
    ]
    latest_exact_date = max(
        (
            record["race_date"]
            for record in race_records
            if record["race_date_precision"] == "exact" and record["race_date"]
        ),
        default=None,
    )
    payload = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "candidate_key": request.candidate_key,
        "region": request.region,
        "horse_name": horse_name,
        "external_horse_id": target_external_horse_id,
        "identity_keys": identity_keys,
        "identity": identity,
        "basic_profile": basic_profile,
        "pedigree": pedigree,
        "race_records": race_records,
        "major_wins": major_wins,
        "aliases": aliases,
        "source_evidence": source_evidence,
        "raw_payload": deepcopy(source_payload),
        "confidence": 100,
        "failure_reason": [],
        "coverage": {
            "basic_profile": _coverage_group(
                basic_profile, REQUIRED_BASIC_PROFILE_FIELDS
            ),
            "pedigree": _coverage_group(pedigree, REQUIRED_PEDIGREE_FIELDS),
            "career_history": {
                "complete": normalized_career["career_history"]["status"] == "complete",
                "missing_fields": list(
                    normalized_career["career_history"]["blocker_reasons"]
                ),
                "present_count": normalized_career["career_history"][
                    "collected_start_count"
                ],
                "required_count": source_start_count,
            },
            "source_evidence": {
                "complete": bool(
                    source_name
                    and (target_external_horse_id or complete_pedigree_identity)
                    and _valid_http_url(profile_source_url)
                    and source.get("fetched_at")
                ),
                "missing_fields": [
                    field
                    for field, value in (
                        ("source_name", source_name),
                        ("source_url", profile_source_url),
                        (
                            "stable_identity",
                            target_external_horse_id or complete_pedigree_identity,
                        ),
                        ("fetched_at", source.get("fetched_at")),
                    )
                    if not value
                ],
                "present_count": sum(
                    bool(value)
                    for value in (
                        source_name,
                        profile_source_url,
                        target_external_horse_id or complete_pedigree_identity,
                        source.get("fetched_at"),
                    )
                ),
                "required_count": 4,
            },
        },
        "career_history": normalized_career["career_history"],
        "records_synced_through": latest_exact_date,
        "module_diff": {
            "basic_profile": deepcopy(basic_profile),
            "pedigree": deepcopy(pedigree),
            "race_records": {"create": len(race_records)},
            "major_wins": {"create": len(major_wins)},
        },
    }
    return validate_p0_horse_completion_payload(payload)


def validate_p0_horse_completion_payload(payload: dict[str, Any]) -> dict[str, Any]:
    checked = deepcopy(payload)
    failures = _deduplicate_strings(checked.get("failure_reason", []))
    identity = checked.get("identity") if isinstance(checked.get("identity"), dict) else {}
    complete_pedigree_identity = all(
        identity.get(field)
        for field in ("horse_name", "sire_name", "dam_name", "birth_year")
    )
    if not checked.get("external_horse_id") and not complete_pedigree_identity:
        failures.append("missing_identity")

    evidence = [
        item
        for item in checked.get("source_evidence", [])
        if isinstance(item, dict)
    ]
    if not evidence or not all(_valid_http_url(item.get("source_url")) for item in evidence):
        failures.append("missing_source_url")
    if not isinstance(checked.get("raw_payload"), dict) or not checked.get("raw_payload"):
        failures.append("missing_raw_payload")

    coverage = checked.get("coverage") if isinstance(checked.get("coverage"), dict) else {}
    for group in ("basic_profile", "pedigree", "career_history", "source_evidence"):
        result = coverage.get(group) if isinstance(coverage.get(group), dict) else {}
        if not result.get("complete"):
            failures.append(f"incomplete_{group}")

    checked["failure_reason"] = _deduplicate_strings(failures)
    checked["confidence"] = min(
        int(checked.get("confidence") or 0),
        79 if checked["failure_reason"] else 100,
    )
    return checked


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise P0HorseCompletionSourceError(f"P0 horse cache is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise P0HorseCompletionSourceError("P0 horse cache must contain an object")
    return payload


def _write_source_cache_atomically(path: Path, payload: dict[str, Any]) -> None:
    payload = _validate_source_cache_payload(
        payload,
        context="canonical cache write",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(_canonical_json_bytes(payload))
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            pass
    except OSError as exc:
        raise P0HorseCompletionSourceError(
            f"P0 horse source cache write failed: {path}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _validate_source_cache_payload(
    source_payload: dict[str, Any],
    *,
    context: str,
    allow_manual_supplements: bool = False,
) -> dict[str, Any]:
    try:
        from stable.services.p0_horse_completion_source_clients import (
            validate_p0_horse_source_cache,
        )

        return validate_p0_horse_source_cache(
            source_payload,
            allow_manual_supplements=allow_manual_supplements,
        )
    except P0HorseCompletionSourceError:
        raise
    except Exception as exc:
        raise P0HorseCompletionSourceError(
            f"{context} source payload failed validation: {exc}"
        ) from exc


def _reject_manual_supplements_from_canonical_source_payload(
    source_payload: dict[str, Any],
    *,
    context: str,
) -> None:
    try:
        from stable.services.p0_horse_completion_source_clients import (
            reject_manual_supplements_from_canonical_source_payload,
        )

        reject_manual_supplements_from_canonical_source_payload(
            source_payload
        )
    except P0HorseCompletionSourceError:
        raise
    except Exception as exc:
        raise P0HorseCompletionSourceError(
            f"{context} source payload failed validation: {exc}"
        ) from exc


def _source_client_has_manual_supplements(
    source_client: P0HorseCompletionSourceClient | None,
    request: P0HorseCompletionRequest,
) -> bool:
    has_supplements = getattr(
        source_client,
        "has_manual_supplements",
        None,
    )
    return bool(
        callable(has_supplements)
        and has_supplements(request)
    )


def _validate_legacy_existing_source_cache_payload(
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    """Allow only the historical missing-target-identity cache shape.

    The sentinel is validation-only: it lets the public strict validator
    continue through every non-identity field, then the original empty target
    provider ID is restored so normalization emits ``missing_identity``.
    """

    try:
        return _validate_source_cache_payload(
            source_payload,
            context="cached",
        )
    except P0HorseCompletionSourceError as exc:
        from stable.services.p0_horse_completion_source_clients import (
            P0HorseSourceBlocked,
        )

        cause = exc.__cause__
        if (
            not isinstance(cause, P0HorseSourceBlocked)
            or str(cause)
            != (
                "identity_incomplete: provider external ID or complete "
                "four-field identity"
            )
        ):
            raise

    compatibility_payload = deepcopy(source_payload)
    source = compatibility_payload.get("source")
    if not isinstance(source, dict) or str(source.get("external_horse_id") or "").strip():
        raise P0HorseCompletionSourceError(
            "legacy existing cache identity compatibility precondition failed"
        )
    source["external_horse_id"] = "__legacy_existing_cache_validation_only__"
    checked = _validate_source_cache_payload(
        compatibility_payload,
        context="legacy existing cached",
    )
    checked["source"]["external_horse_id"] = ""
    return checked


def _parse_json_list(value: Any, *, field: str, row_number: int) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError as exc:
        raise P0HorseCompletionBatchError(
            f"reviewed candidate row {row_number} has invalid JSON in {field}"
        ) from exc
    if not isinstance(parsed, list):
        raise P0HorseCompletionBatchError(
            f"reviewed candidate row {row_number} field {field} must be a JSON list"
        )
    return parsed


def load_reviewed_p0_horse_candidates(
    reviewed_candidates_csv: str | Path,
    *,
    captured_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    path = Path(reviewed_candidates_csv)
    try:
        source_bytes = (
            bytes(captured_bytes)
            if captured_bytes is not None
            else path.read_bytes()
        )
        input_file = io.StringIO(
            source_bytes.decode("utf-8-sig"),
            newline="",
        )
        reader = csv.DictReader(input_file)
        fieldnames = set(reader.fieldnames or [])
        missing_fields = REVIEWED_CANDIDATE_REQUIRED_FIELDS - fieldnames
        if missing_fields:
            raise P0HorseCompletionBatchError(
                "reviewed candidate CSV is missing required fields: "
                + ", ".join(sorted(missing_fields))
            )
        raw_rows = list(reader)
    except (OSError, UnicodeDecodeError) as exc:
        raise P0HorseCompletionBatchError(
            f"reviewed candidate CSV is unreadable: {path}"
        ) from exc

    if len(raw_rows) != 50:
        raise P0HorseCompletionBatchError(
            f"reviewed candidate CSV must contain exactly 50 rows, got {len(raw_rows)}"
        )

    rows: list[dict[str, Any]] = []
    candidate_keys: set[str] = set()
    region_ranks: dict[str, set[int]] = {
        region: set() for region in REVIEWED_CANDIDATE_REGIONS
    }
    for row_number, raw_row in enumerate(raw_rows, start=2):
        row = {key: str(value or "").strip() for key, value in raw_row.items()}
        region = row["sample_region"]
        if region not in region_ranks:
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} has unsupported region: {region}"
            )
        try:
            sample_rank = int(row["sample_rank"])
        except ValueError as exc:
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} has invalid sample_rank"
            ) from exc
        if sample_rank not in range(1, 11) or sample_rank in region_ranks[region]:
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} has invalid or duplicate sample_rank"
            )
        region_ranks[region].add(sample_rank)

        candidate_key = row["candidate_key"]
        if not candidate_key or candidate_key in candidate_keys:
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} has empty or duplicate candidate_key"
            )
        candidate_keys.add(candidate_key)
        if not row["horse_name"]:
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} has an empty horse_name"
            )
        if row["reviewed"].casefold() != "true":
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} is not reviewed"
            )
        if row["review_decision"] != REVIEWED_CANDIDATE_DECISION:
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} is not confirmed for inclusion"
            )

        normalized = dict(row)
        normalized["sample_rank"] = sample_rank
        normalized["reviewed"] = True
        birth_year_text = row.get("birth_year", "")
        if birth_year_text:
            if (
                not re.fullmatch(r"\d{4}", birth_year_text)
                or not 1800
                <= int(birth_year_text)
                <= datetime.now(timezone.utc).year
            ):
                raise P0HorseCompletionBatchError(
                    f"reviewed candidate row {row_number} has invalid birth_year"
                )
            normalized["birth_year"] = int(birth_year_text)
        else:
            normalized["birth_year"] = None
        expected_identity_parts = (
            normalized.get("sire_name", ""),
            normalized.get("dam_name", ""),
            normalized["birth_year"],
        )
        if any(value not in ("", None) for value in expected_identity_parts) and any(
            value in ("", None) for value in expected_identity_parts
        ):
            raise P0HorseCompletionBatchError(
                f"reviewed candidate row {row_number} has incomplete "
                "sire_name, dam_name, or birth_year identity"
            )
        for field in (
            "aliases",
            "matched_profile_ids",
            "identity_keys",
            "source_namespaces",
            "source_urls",
            "event_regions",
        ):
            normalized[field] = _parse_json_list(
                row[field],
                field=field,
                row_number=row_number,
            )
        rows.append(normalized)

    invalid_region_counts = {
        region: len(ranks)
        for region, ranks in region_ranks.items()
        if ranks != set(range(1, 11))
    }
    if invalid_region_counts:
        raise P0HorseCompletionBatchError(
            "reviewed candidate CSV must contain ranks 1-10 exactly once per region: "
            + json.dumps(invalid_region_counts, ensure_ascii=False, sort_keys=True)
        )
    return sorted(
        rows,
        key=lambda row: (
            REVIEWED_CANDIDATE_REGIONS.index(row["sample_region"]),
            row["sample_rank"],
        ),
    )


def p0_horse_completion_cache_path(
    cache_dir: str | Path,
    candidate_key: str,
) -> Path:
    normalized_key = str(candidate_key or "")
    if not normalized_key:
        raise P0HorseCompletionBatchError("candidate_key is required for cache routing")
    digest = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{digest}.json"


def _candidate_external_horse_id(candidate: dict[str, Any]) -> str:
    source_namespace = str(candidate.get("source_namespace") or "").strip()
    for identity_key in candidate.get("identity_keys", []):
        text = str(identity_key or "").strip()
        prefix = f"{source_namespace}:"
        if source_namespace and text.startswith(prefix):
            return text[len(prefix) :]
    candidate_key = str(candidate.get("candidate_key") or "")
    prefix = f"external:{source_namespace}:"
    if source_namespace and candidate_key.startswith(prefix):
        return candidate_key[len(prefix) :]
    return ""


def _candidate_source_url(candidate: dict[str, Any]) -> str:
    return next(
        (
            str(value).strip()
            for value in candidate.get("source_urls", [])
            if _valid_http_url(value)
        ),
        "",
    )


def _candidate_requires_identity_enrichment(candidate: dict[str, Any]) -> bool:
    return any(
        str(candidate.get(field) or "") == "needs_identity_enrichment"
        for field in ("identity_status", "review_status")
    )


def _blocked_candidate_payload(
    candidate: dict[str, Any],
    *,
    failure_reason: str,
    request: P0HorseCompletionRequest,
    network_request_count: int,
    error: Exception,
) -> dict[str, Any]:
    identity_enrichment_required = _candidate_requires_identity_enrichment(candidate)
    failures = [failure_reason]
    if identity_enrichment_required:
        failures.insert(0, "identity_enrichment_required")
    source_name = str(candidate.get("source_namespace") or "").strip()
    source_url = _candidate_source_url(candidate)
    candidate_external_horse_id = _candidate_external_horse_id(candidate)
    candidate_identity_key = _provider_bound_identity_key(
        source_name,
        candidate_external_horse_id,
    )
    return validate_p0_horse_completion_payload(
        {
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "candidate_key": candidate["candidate_key"],
            "region": candidate["sample_region"],
            "horse_name": candidate["horse_name"],
            "external_horse_id": "",
            "identity_keys": [candidate_identity_key] if candidate_identity_key else [],
            "identity": {
                "horse_name": candidate["horse_name"],
                "sire_name": "",
                "dam_name": "",
                "birth_year": None,
                "source_name": "",
                "external_horse_id": "",
                "candidate_source_name": source_name,
                "candidate_external_horse_id": candidate_external_horse_id,
                "identity_keys": (
                    [candidate_identity_key] if candidate_identity_key else []
                ),
            },
            "basic_profile": {},
            "pedigree": {},
            "race_records": [],
            "major_wins": [],
            "aliases": [
                {
                    "name": str(alias).strip(),
                    "language": "",
                    "is_original": index == 0,
                }
                for index, alias in enumerate(candidate.get("aliases", []))
                if str(alias).strip()
            ],
            "source_evidence": (
                [
                    {
                        "source_name": source_name,
                        "source_url": source_url,
                        "external_horse_id": candidate_external_horse_id,
                        "fetched_at": "",
                        "adapter_key": "",
                        "evidence_role": "reviewed_candidate",
                    }
                ]
                if source_url
                else []
            ),
            "raw_payload": {"reviewed_candidate": deepcopy(candidate)},
            "confidence": 0,
            "failure_reason": failures,
            "coverage": {
                group: {
                    "complete": False,
                    "missing_fields": ["source_payload_unavailable"],
                    "present_count": 0,
                    "required_count": 1,
                }
                for group in (
                    "basic_profile",
                    "pedigree",
                    "career_history",
                    "source_evidence",
                )
            },
            "career_history": {
                "status": "blocked",
                "official_or_source_start_count": None,
                "collected_start_count": 0,
                "gap_count": None,
                "blocker_reasons": [failure_reason],
            },
            "records_synced_through": None,
            "module_diff": {
                "basic_profile": {},
                "pedigree": {},
                "race_records": {"create": 0},
                "major_wins": {"create": 0},
            },
            "retrieval": {
                "cache_hit": False,
                "cache_path": request.cache_path,
                "network_request_count": network_request_count,
                "request_interval_seconds": request.request_interval_seconds,
                "request_budget": request.request_budget,
                "batch_limit": request.batch_limit,
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        }
    )


def run_p0_horse_completion_adapter(
    request: P0HorseCompletionRequest,
    *,
    source_client: P0HorseCompletionSourceClient | None = None,
) -> dict[str, Any]:
    adapter = REGION_ADAPTERS[request.region]
    cache_path = Path(request.cache_path).expanduser() if request.cache_path else None
    has_manual_supplements = _source_client_has_manual_supplements(
        source_client,
        request,
    )
    if cache_path and cache_path.is_file():
        source_payload = _read_cache(cache_path)
        source_payload = _validate_legacy_existing_source_cache_payload(
            source_payload,
        )
        apply_supplements = getattr(
            source_client,
            "apply_manual_supplements",
            None,
        )
        if callable(apply_supplements):
            source_payload = apply_supplements(
                source_payload,
                request,
            )
        if has_manual_supplements:
            source_payload = _validate_source_cache_payload(
                source_payload,
                context="cached working copy",
                allow_manual_supplements=True,
            )
        else:
            _reject_manual_supplements_from_canonical_source_payload(
                source_payload,
                context="cached working copy",
            )
        cache_hit = True
        network_request_count = 0
    else:
        if not request.allow_network:
            raise P0HorseCompletionNetworkDisabled(
                "P0 horse completion network access is disabled and no cache is available"
            )
        if source_client is None:
            raise P0HorseCompletionSourceError(
                "network-enabled completion requires a controlled source client"
            )
        fetch_source_payload = getattr(
            source_client,
            "fetch_source_payload",
            None,
        )
        source_snapshot = (
            fetch_source_payload(request)
            if callable(fetch_source_payload)
            else source_client.fetch(request)
        )
        _reject_manual_supplements_from_canonical_source_payload(
            source_snapshot,
            context="network",
        )
        try:
            canonical_source_payload = _validate_source_cache_payload(
                source_snapshot,
                context="network",
            )
        except P0HorseCompletionSourceError:
            canonical_source_payload = None
        if canonical_source_payload is not None and cache_path:
            _write_source_cache_atomically(
                cache_path,
                canonical_source_payload,
            )
            canonical_source_payload = _read_cache(cache_path)
            canonical_source_payload = _validate_source_cache_payload(
                canonical_source_payload,
                context="canonical cached",
            )
        source_payload = (
            canonical_source_payload
            if canonical_source_payload is not None
            else source_snapshot
        )
        apply_supplements = getattr(
            source_client,
            "apply_manual_supplements",
            None,
        )
        if callable(apply_supplements):
            source_payload = apply_supplements(
                source_payload,
                request,
            )
        source_payload = _validate_source_cache_payload(
            source_payload,
            context="network working copy",
            allow_manual_supplements=has_manual_supplements,
        )
        cache_hit = False
        network_request_count = _source_client_request_count(source_client)
    payload = adapter.normalize(source_payload, request)
    payload["retrieval"] = {
        "cache_hit": cache_hit,
        "network_request_count": network_request_count,
        "request_interval_seconds": request.request_interval_seconds,
        "request_budget": request.request_budget,
        "batch_limit": request.batch_limit,
    }
    return payload


def _ensure_manual_supplement_outcomes(
    payload: dict[str, Any],
    manual_supplements: list[dict[str, Any]],
) -> None:
    if not manual_supplements:
        return
    raw_payload = (
        payload.get("raw_payload")
        if isinstance(payload.get("raw_payload"), dict)
        else {}
    )
    payload["raw_payload"] = raw_payload
    outcomes = (
        deepcopy(raw_payload.get("manual_supplement_outcomes"))
        if isinstance(
            raw_payload.get("manual_supplement_outcomes"),
            list,
        )
        else []
    )
    existing_keys = {
        (
            str(row.get("field_group") or ""),
            str(row.get("field_name") or ""),
        )
        for row in outcomes
        if isinstance(row, dict)
    }
    blocked = bool(payload.get("failure_reason"))
    fallback_status = "blocked" if blocked else "ignored"
    fallback_reason = (
        ",".join(str(reason) for reason in payload.get("failure_reason", []))
        if blocked
        else "manual_supplement_not_processed"
    )
    evidence = (
        payload.get("source_evidence")
        if isinstance(payload.get("source_evidence"), list)
        else []
    )
    payload["source_evidence"] = evidence
    for supplement in manual_supplements:
        field_group = str(supplement.get("field_group") or "")
        field_name = str(supplement.get("field_name") or "")
        key = (field_group, field_name)
        if key in existing_keys:
            continue
        source = (
            supplement.get("source")
            if isinstance(supplement.get("source"), dict)
            else {}
        )
        outcomes.append(
            {
                "field_group": field_group,
                "field_name": field_name,
                "current_value": deepcopy(
                    supplement.get("current_value")
                ),
                "proposed_value": deepcopy(
                    supplement.get("proposed_value")
                ),
                "status": fallback_status,
                "reason": fallback_reason,
                "source": deepcopy(source),
            }
        )
        evidence.append(
            {
                "source_name": str(source.get("name") or "").strip(),
                "source_url": str(source.get("url") or "").strip(),
                "external_horse_id": str(
                    source.get("external_horse_id") or ""
                ).strip(),
                "fetched_at": str(source.get("fetched_at") or "").strip(),
                "adapter_key": "",
                "evidence_role": "manual_supplement",
                "entry_method": "manual_review",
                "entered_by": str(
                    source.get("entered_by") or ""
                ).strip(),
                "reviewer": str(source.get("reviewer") or "").strip(),
                "field_group": field_group,
                "field_name": field_name,
                "outcome_status": fallback_status,
                "outcome_reason": fallback_reason,
            }
        )
    raw_payload["manual_supplement_outcomes"] = outcomes


def _load_review_manifest_binding(
    review_manifest_path: str | Path,
    *,
    reviewed_path: Path,
    reviewed_bytes: bytes,
    candidate_count: int,
    manifest_bytes: bytes | None = None,
    expected_sha256: str | None = None,
    authorized_by_setting: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(review_manifest_path)
    if manifest_bytes is None:
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise P0HorseCompletionBatchError(
                f"P0 horse review manifest is unreadable: {manifest_path}"
            ) from exc
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise P0HorseCompletionBatchError(
            f"P0 horse review manifest is invalid: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest must be a JSON object"
        )
    if manifest.get("artifact_type") != "p0_horse_candidate_review_manifest":
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest has an invalid artifact_type"
        )
    if manifest.get("decision") != REVIEWED_CANDIDATE_DECISION:
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest does not confirm batch inclusion"
        )

    files = manifest.get("files")
    reviewed_name = reviewed_path.name
    file_entry = files.get(reviewed_name) if isinstance(files, dict) else None
    if not isinstance(file_entry, dict):
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest does not contain the reviewed CSV basename"
        )
    if file_entry.get("path") != reviewed_name:
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest CSV path does not match its basename"
        )

    reviewed_sha256 = hashlib.sha256(reviewed_bytes).hexdigest()
    manifest_sha256 = file_entry.get("sha256")
    if (
        not isinstance(manifest_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)
        or manifest_sha256 != reviewed_sha256
    ):
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest CSV SHA-256 does not match"
        )
    manifest_size = file_entry.get("size")
    if (
        isinstance(manifest_size, bool)
        or not isinstance(manifest_size, int)
        or manifest_size != len(reviewed_bytes)
    ):
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest CSV size does not match"
        )
    manifest_row_count = manifest.get("row_count")
    if (
        isinstance(manifest_row_count, bool)
        or not isinstance(manifest_row_count, int)
        or manifest_row_count != candidate_count
    ):
        raise P0HorseCompletionBatchError(
            "P0 horse review manifest row_count does not match reviewed candidates"
        )

    return {
        "path": str(manifest_path),
        "size_bytes": len(manifest_bytes),
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "expected_sha256": str(expected_sha256 or ""),
        "authorized_by_setting": authorized_by_setting,
        "artifact_type": manifest["artifact_type"],
        "decision": manifest["decision"],
        "row_count": manifest_row_count,
        "reviewed_csv_entry": {
            "path": reviewed_name,
            "size_bytes": manifest_size,
            "sha256": manifest_sha256,
        },
    }


def run_reviewed_p0_horse_completion_batch(
    *,
    reviewed_candidates_csv: str | Path,
    review_manifest_path: str | Path | None = None,
    expected_review_manifest_sha256: str | None = None,
    manual_supplements_csv: str | Path | None = None,
    cache_dir: str | Path,
    output_dir: str | Path,
    allow_network: bool = False,
    network_regions: Iterable[str] = (),
    source_client_factory: (
        Callable[[str], P0HorseCompletionSourceClient] | None
    ) = None,
    request_interval_seconds: float = 8.0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    custom_source_client_factory = source_client_factory is not None
    requested_regions = tuple(network_regions)
    requested_region_set = set(requested_regions)
    unknown_regions = requested_region_set - set(REVIEWED_CANDIDATE_REGIONS)
    if unknown_regions:
        raise P0HorseCompletionBatchError(
            "unsupported reviewed P0 horse network region: "
            + ", ".join(sorted(unknown_regions))
        )
    selected_regions = tuple(
        region
        for region in REVIEWED_CANDIDATE_REGIONS
        if region in requested_region_set
    )
    if allow_network and not selected_regions:
        raise P0HorseCompletionBatchError(
            "network-enabled reviewed batch requires at least one explicit region"
        )
    if not allow_network and selected_regions:
        raise P0HorseCompletionBatchError(
            "network_regions require allow_network=true"
        )
    if manual_supplements_csv is not None and not allow_network:
        raise P0HorseCompletionBatchError(
            "manual supplements require an authorized network dry-run"
        )
    if allow_network and not settings.HORSE_PROFILE_COMPLETION_ALLOW_NETWORK:
        raise P0HorseCompletionBatchError(
            "HORSE_PROFILE_COMPLETION_ALLOW_NETWORK is disabled"
        )
    authorized_manifest_bytes: bytes | None = None
    review_manifest_authorized_by_setting = False
    if allow_network:
        expected_sha256 = str(expected_review_manifest_sha256 or "")
        configured_sha256 = str(
            settings.HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256 or ""
        )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise P0HorseCompletionBatchError(
                "expected_review_manifest_sha256 must be a lowercase SHA-256"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", configured_sha256):
            raise P0HorseCompletionBatchError(
                "HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256 "
                "must be a lowercase SHA-256"
            )
        if expected_sha256 != configured_sha256:
            raise P0HorseCompletionBatchError(
                "expected_review_manifest_sha256 does not match "
                "HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256"
            )
        if review_manifest_path is None:
            raise P0HorseCompletionBatchError(
                "network-enabled reviewed batch requires a P0 horse review manifest"
            )
        manifest_path = Path(review_manifest_path)
        try:
            authorized_manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise P0HorseCompletionBatchError(
                f"P0 horse review manifest is unreadable: {manifest_path}"
            ) from exc
        if (
            hashlib.sha256(authorized_manifest_bytes).hexdigest()
            != expected_sha256
        ):
            raise P0HorseCompletionBatchError(
                "P0 horse review manifest SHA-256 does not match "
                "the frozen authorization"
            )
        review_manifest_authorized_by_setting = True
    output = Path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise P0HorseCompletionBatchError(
            f"P0 horse completion artifact output directory is not empty: {output}"
        )

    reviewed_path = Path(reviewed_candidates_csv)
    try:
        reviewed_bytes = reviewed_path.read_bytes()
    except OSError as exc:
        raise P0HorseCompletionBatchError(
            f"reviewed candidate CSV is unreadable: {reviewed_path}"
        ) from exc
    reviewed_sha256 = hashlib.sha256(reviewed_bytes).hexdigest()
    candidates = load_reviewed_p0_horse_candidates(
        reviewed_path,
        captured_bytes=reviewed_bytes,
    )
    manual_supplements_by_candidate: dict[
        str,
        list[dict[str, Any]],
    ] = {}
    manual_supplements_input: dict[str, Any] | None = None
    if manual_supplements_csv is not None:
        from stable.services.p0_horse_completion_source_clients import (
            P0HorseSourceBlocked,
            load_reviewed_manual_supplements,
        )

        manual_path = Path(manual_supplements_csv)
        try:
            manual_bytes = manual_path.read_bytes()
            manual_supplements_by_candidate = (
                load_reviewed_manual_supplements(
                    manual_path,
                    reviewed_candidates=candidates,
                    captured_bytes=manual_bytes,
                )
            )
        except (OSError, P0HorseSourceBlocked) as exc:
            raise P0HorseCompletionBatchError(
                f"manual supplements are invalid: {exc}"
            ) from exc
        manual_supplements_input = {
            "path": str(manual_path),
            "size_bytes": len(manual_bytes),
            "sha256": hashlib.sha256(manual_bytes).hexdigest(),
            "approved_field_count": sum(
                len(rows)
                for rows in manual_supplements_by_candidate.values()
            ),
            "candidate_count": len(manual_supplements_by_candidate),
        }
        candidate_index = {
            candidate["candidate_key"]: candidate
            for candidate in candidates
        }
        manual_regions = {
            candidate_index[candidate_key]["sample_region"]
            for candidate_key in manual_supplements_by_candidate
        }
        outside_selected_regions = manual_regions - set(selected_regions)
        if outside_selected_regions:
            raise P0HorseCompletionBatchError(
                "manual supplements target outside selected network regions: "
                + ", ".join(sorted(outside_selected_regions))
            )
        if manual_supplements_by_candidate and custom_source_client_factory:
            raise P0HorseCompletionBatchError(
                "manual supplements require default source clients"
            )
    review_manifest_input = (
        _load_review_manifest_binding(
            review_manifest_path,
            reviewed_path=reviewed_path,
            reviewed_bytes=reviewed_bytes,
            candidate_count=len(candidates),
            manifest_bytes=authorized_manifest_bytes,
            expected_sha256=expected_review_manifest_sha256,
            authorized_by_setting=review_manifest_authorized_by_setting,
        )
        if review_manifest_path is not None
        else None
    )
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if source_client_factory is None:
        def source_client_factory(
            region: str,
        ) -> P0HorseCompletionSourceClient:
            import requests

            from stable.services.p0_horse_completion_source_clients import (
                build_p0_horse_completion_source_client,
            )

            client_kwargs: dict[str, Any] = {}
            if manual_supplements_by_candidate:
                client_kwargs["manual_supplements_by_candidate"] = (
                    manual_supplements_by_candidate
                )
            return build_p0_horse_completion_source_client(
                region,
                transport=requests.Session(),
                **client_kwargs,
            )

    source_clients = {
        region: source_client_factory(region)
        for region in selected_regions
    }
    payloads: list[dict[str, Any]] = []
    for candidate in candidates:
        region = candidate["sample_region"]
        region_network_allowed = allow_network and region in selected_regions
        cache_path = p0_horse_completion_cache_path(
            cache_dir,
            candidate["candidate_key"],
        )
        request = P0HorseCompletionRequest(
            candidate_key=candidate["candidate_key"],
            region=region,
            horse_name=candidate["horse_name"],
            source_url=_candidate_source_url(candidate),
            external_horse_id=_candidate_external_horse_id(candidate),
            candidate_source_name=str(
                candidate.get("source_namespace") or ""
            ).strip(),
            expected_sire_name=str(candidate.get("sire_name") or "").strip(),
            expected_dam_name=str(candidate.get("dam_name") or "").strip(),
            expected_birth_year=candidate.get("birth_year"),
            cache_path=str(cache_path),
            allow_network=region_network_allowed,
            request_interval_seconds=request_interval_seconds,
            request_budget=REVIEWED_CANDIDATE_REQUEST_BUDGETS[region],
            batch_limit=int(
                getattr(settings, "HORSE_PROFILE_COMPLETION_REGION_BATCH_LIMIT", 100)
            ),
        )
        delegate_source_client = source_clients.get(region)
        source_client = (
            _PerCandidateSourceClient(delegate_source_client)
            if delegate_source_client is not None
            else None
        )
        try:
            payload = run_p0_horse_completion_adapter(
                request,
                source_client=source_client,
            )
            if _candidate_requires_identity_enrichment(candidate):
                identity = (
                    payload.get("identity")
                    if isinstance(payload.get("identity"), dict)
                    else {}
                )
                identity_resolved = bool(
                    payload.get("external_horse_id")
                ) or all(
                    identity.get(field)
                    for field in (
                        "horse_name",
                        "sire_name",
                        "dam_name",
                        "birth_year",
                    )
                )
                payload["failure_reason"] = _deduplicate_strings(
                    reason
                    for reason in payload.get("failure_reason", [])
                    if not (
                        identity_resolved
                        and reason
                        in {"identity_enrichment_required", "missing_identity"}
                    )
                )
                if not identity_resolved:
                    payload["failure_reason"] = _deduplicate_strings(
                        [
                            *payload["failure_reason"],
                            "identity_enrichment_required",
                        ]
                    )
                payload = validate_p0_horse_completion_payload(payload)
        except P0HorseCompletionNetworkDisabled as exc:
            payload = _blocked_candidate_payload(
                candidate,
                failure_reason="network_disabled_cache_missing",
                request=request,
                network_request_count=0,
                error=exc,
            )
        except P0HorseCompletionSourceError as exc:
            payload = _blocked_candidate_payload(
                candidate,
                failure_reason="source_cache_or_adapter_error",
                request=request,
                network_request_count=int(
                    getattr(source_client, "last_request_count", 0) or 0
                ),
                error=exc,
            )
        except Exception as exc:
            from stable.services.p0_horse_completion_source_clients import (
                P0HorseSourceBlocked,
            )

            payload = _blocked_candidate_payload(
                candidate,
                failure_reason=(
                    "source_cache_or_adapter_error"
                    if isinstance(exc, P0HorseSourceBlocked)
                    else "unexpected_adapter_error"
                ),
                request=request,
                network_request_count=int(
                    getattr(source_client, "last_request_count", 0) or 0
                ),
                error=exc,
            )
        _ensure_manual_supplement_outcomes(
            payload,
            manual_supplements_by_candidate.get(
                candidate["candidate_key"],
                [],
            ),
        )
        payloads.append(payload)

    return _publish_reviewed_p0_horse_completion_artifacts(
        payloads,
        output=output,
        reviewed_path=reviewed_path,
        reviewed_bytes=reviewed_bytes,
        reviewed_sha256=reviewed_sha256,
        candidate_count=len(candidates),
        review_manifest_input=review_manifest_input,
        manual_supplements_input=manual_supplements_input,
        manual_supplements_by_candidate=manual_supplements_by_candidate,
        allow_network=allow_network,
        selected_regions=selected_regions,
        request_interval_seconds=request_interval_seconds,
        generated_at=timestamp,
    )


def _write_bytes(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _validate_staged_file(
    staging_dir: Path,
    filename: str,
    metadata: dict[str, Any],
) -> None:
    if Path(filename).name != filename or metadata.get("path") != filename:
        raise P0HorseCompletionBatchError(
            f"staged P0 horse artifact has an invalid path: {filename}"
        )
    path = staging_dir / filename
    if not path.is_file():
        raise P0HorseCompletionBatchError(
            f"staged P0 horse artifact is missing: {filename}"
        )
    content = path.read_bytes()
    if (
        metadata.get("size_bytes") != len(content)
        or metadata.get("sha256") != hashlib.sha256(content).hexdigest()
    ):
        raise P0HorseCompletionBatchError(
            f"staged P0 horse artifact failed content validation: {filename}"
        )


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_manual_supplement_outcome_contract(
    payloads: list[dict[str, Any]],
    manual_supplements_by_candidate: dict[
        str,
        list[dict[str, Any]],
    ],
) -> None:
    from stable.services.p0_horse_completion_source_clients import (
        P0HorseSourceBlocked,
        manual_supplement_evidence_fingerprint,
    )

    payload_index: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        candidate_key = str(payload.get("candidate_key") or "")
        if not candidate_key or candidate_key in payload_index:
            raise P0HorseCompletionBatchError(
                "manual supplement outcome reconciliation requires unique "
                "candidate keys"
            )
        payload_index[candidate_key] = payload

    expected_candidate_keys = set(manual_supplements_by_candidate)
    missing_candidates = expected_candidate_keys - set(payload_index)
    if missing_candidates:
        raise P0HorseCompletionBatchError(
            "manual supplement outcome reconciliation is missing candidates: "
            + ", ".join(sorted(missing_candidates))
        )

    for candidate_key, payload in payload_index.items():
        expected_rows = manual_supplements_by_candidate.get(
            candidate_key,
            [],
        )
        actual_rows = _manual_supplement_outcomes(payload)
        if not expected_rows:
            if actual_rows:
                raise P0HorseCompletionBatchError(
                    "manual supplement outcomes exist without approved input "
                    f"for candidate: {candidate_key}"
                )
            continue

        invalid_statuses = sorted(
            {
                str(row.get("status") or "")
                for row in actual_rows
                if str(row.get("status") or "")
                not in MANUAL_SUPPLEMENT_OUTCOME_STATUSES
            }
        )
        if invalid_statuses:
            raise P0HorseCompletionBatchError(
                "manual supplement outcome has an invalid status for "
                f"{candidate_key}: {', '.join(invalid_statuses)}"
            )
        try:
            expected_fingerprints = [
                manual_supplement_evidence_fingerprint(row)
                for row in expected_rows
            ]
            actual_fingerprints = [
                manual_supplement_evidence_fingerprint(row)
                for row in actual_rows
            ]
        except (TypeError, ValueError, P0HorseSourceBlocked) as exc:
            raise P0HorseCompletionBatchError(
                "manual supplement outcome evidence is invalid for "
                f"{candidate_key}: {exc}"
            ) from exc
        if len(actual_fingerprints) != len(set(actual_fingerprints)):
            raise P0HorseCompletionBatchError(
                "manual supplement outcomes contain duplicate evidence for "
                f"candidate: {candidate_key}"
            )
        if sorted(actual_fingerprints) != sorted(expected_fingerprints):
            raise P0HorseCompletionBatchError(
                "manual supplement outcomes do not match the approved input "
                f"for candidate: {candidate_key}"
            )


def _publish_reviewed_p0_horse_completion_artifacts(
    payloads: Iterable[dict[str, Any]],
    *,
    output: Path,
    reviewed_path: Path,
    reviewed_bytes: bytes,
    reviewed_sha256: str,
    candidate_count: int,
    review_manifest_input: dict[str, Any] | None,
    manual_supplements_input: dict[str, Any] | None,
    manual_supplements_by_candidate: dict[
        str,
        list[dict[str, Any]],
    ],
    allow_network: bool,
    selected_regions: tuple[str, ...],
    request_interval_seconds: float,
    generated_at: str,
) -> dict[str, Any]:
    payload_rows = list(payloads)
    _validate_manual_supplement_outcome_contract(
        payload_rows,
        manual_supplements_by_candidate,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.staging-",
            dir=output.parent,
        )
    )
    published = False
    try:
        artifact_manifest = write_p0_horse_completion_artifacts(
            payload_rows,
            staging,
            reviewed_input_sha256=reviewed_sha256,
            generated_at=generated_at,
        )
        artifact_manifest_bytes = _canonical_json_bytes(artifact_manifest)
        artifact_manifest_name = "p0_horse_completion_artifact_manifest.json"
        _write_bytes(
            staging / artifact_manifest_name,
            artifact_manifest_bytes,
        )

        summary = json.loads(
            (staging / "summary.json").read_text(encoding="utf-8")
        )
        files = dict(artifact_manifest["files"])
        files[artifact_manifest_name] = {
            "path": artifact_manifest_name,
            "size_bytes": len(artifact_manifest_bytes),
            "sha256": hashlib.sha256(artifact_manifest_bytes).hexdigest(),
        }
        batch_manifest = {
            "artifact_type": "p0_horse_completion_batch_manifest",
            "schema_version": BATCH_MANIFEST_SCHEMA_VERSION,
            "generated_at": generated_at,
            "read_only": True,
            "network_allowed": allow_network,
            "network_regions": list(selected_regions),
            "database_writes": 0,
            "request_interval_seconds": request_interval_seconds,
            "reviewed_candidates_input": {
                "path": str(reviewed_path),
                "size_bytes": len(reviewed_bytes),
                "sha256": reviewed_sha256,
                "candidate_count": candidate_count,
            },
            "summary": summary,
            "files": {name: files[name] for name in sorted(files)},
        }
        if review_manifest_input is not None:
            batch_manifest["review_manifest_input"] = review_manifest_input
        if manual_supplements_input is not None:
            batch_manifest["manual_supplements_input"] = (
                {
                    **manual_supplements_input,
                    "outcome_summary": deepcopy(
                        summary.get("manual_supplements", {})
                    ),
                }
            )

        batch_manifest_name = "p0_horse_completion_batch_manifest.json"
        batch_manifest_bytes = _canonical_json_bytes(batch_manifest)
        _write_bytes(staging / batch_manifest_name, batch_manifest_bytes)

        persisted_artifact_manifest = json.loads(
            (staging / artifact_manifest_name).read_text(encoding="utf-8")
        )
        persisted_batch_manifest = json.loads(
            (staging / batch_manifest_name).read_text(encoding="utf-8")
        )
        if persisted_artifact_manifest != artifact_manifest:
            raise P0HorseCompletionBatchError(
                "staged P0 horse artifact manifest failed content validation"
            )
        if persisted_batch_manifest != batch_manifest:
            raise P0HorseCompletionBatchError(
                "staged P0 horse batch manifest failed content validation"
            )

        expected_files = set(batch_manifest["files"]) | {batch_manifest_name}
        actual_files = {
            path.name for path in staging.iterdir() if path.is_file()
        }
        if actual_files != expected_files or any(
            not path.is_file() for path in staging.iterdir()
        ):
            raise P0HorseCompletionBatchError(
                "staged P0 horse artifact file set is incomplete"
            )
        for filename, metadata in batch_manifest["files"].items():
            _validate_staged_file(staging, filename, metadata)
        if (
            len(batch_manifest_bytes) != (staging / batch_manifest_name).stat().st_size
            or hashlib.sha256(
                (staging / batch_manifest_name).read_bytes()
            ).hexdigest()
            != hashlib.sha256(batch_manifest_bytes).hexdigest()
        ):
            raise P0HorseCompletionBatchError(
                "staged P0 horse batch manifest failed byte validation"
            )

        for path in sorted(staging.iterdir()):
            _fsync_file(path)
        _fsync_directory(staging)

        if output.exists() and (
            not output.is_dir() or any(output.iterdir())
        ):
            raise P0HorseCompletionBatchError(
                f"P0 horse completion artifact output directory is not empty: {output}"
            )
        os.replace(staging, output)
        published = True
        _fsync_directory(output.parent)
        return batch_manifest
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(row) for row in rows)


def _csv_bytes(rows: list[dict[str, Any]], fieldnames: list[str]) -> bytes:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field: (
                    json.dumps(row.get(field), ensure_ascii=False, sort_keys=True)
                    if isinstance(row.get(field), (dict, list))
                    else row.get(field, "")
                )
                for field in fieldnames
            }
        )
    return buffer.getvalue().encode("utf-8")


def _review_row(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = [
        row for row in payload.get("source_evidence", []) if isinstance(row, dict)
    ]
    return {
        "candidate_key": payload.get("candidate_key", ""),
        "region": payload.get("region", ""),
        "horse_name": payload.get("horse_name", ""),
        "confidence": payload.get("confidence", 0),
        "failure_reason": payload.get("failure_reason", []),
        "source_urls": [
            row.get("source_url") for row in evidence if row.get("source_url")
        ],
        "career_history_status": payload.get("career_history", {}).get("status", ""),
        "reviewed": False,
        "basic_profile_decision": "",
        "pedigree_decision": "",
        "race_records_decision": "",
        "major_wins_decision": "",
        "reviewer_id": "",
        "reviewed_at": "",
    }


def _manual_supplement_outcomes(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_payload = (
        payload.get("raw_payload")
        if isinstance(payload.get("raw_payload"), dict)
        else {}
    )
    rows = raw_payload.get("manual_supplement_outcomes")
    return (
        [deepcopy(row) for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )


def _empty_manual_supplement_summary() -> dict[str, int]:
    return {
        "approved_field_count": 0,
        "applied_field_count": 0,
        "already_applied_field_count": 0,
        "blocked_field_count": 0,
        "ignored_field_count": 0,
        "approved_candidate_count": 0,
        "applied_candidate_count": 0,
        "blocked_candidate_count": 0,
        "ignored_candidate_count": 0,
    }


def _add_manual_supplement_summary(
    summary: dict[str, int],
    outcomes: list[dict[str, Any]],
) -> None:
    if not outcomes:
        return
    statuses = {
        str(outcome.get("status") or "")
        for outcome in outcomes
    }
    summary["approved_field_count"] += len(outcomes)
    for status in (
        "applied",
        "already_applied",
        "blocked",
        "ignored",
    ):
        summary[f"{status}_field_count"] += sum(
            str(outcome.get("status") or "") == status
            for outcome in outcomes
        )
    summary["approved_candidate_count"] += 1
    if statuses & {"applied", "already_applied"}:
        summary["applied_candidate_count"] += 1
    if "blocked" in statuses:
        summary["blocked_candidate_count"] += 1
    if "ignored" in statuses:
        summary["ignored_candidate_count"] += 1


def _artifact_summary(
    payloads: list[dict[str, Any]],
    *,
    generated_at: str,
    reviewed_input_sha256: str,
) -> dict[str, Any]:
    by_region: dict[str, dict[str, Any]] = {}
    failures: dict[str, int] = {}
    manual_summary = _empty_manual_supplement_summary()
    for payload in payloads:
        region = str(payload.get("region") or "")
        region_summary = by_region.setdefault(
            region,
            {
                "processed_count": 0,
                "complete_candidate_count": 0,
                "blocked_count": 0,
                "network_request_count": 0,
                "cache_hit_count": 0,
                "cache_miss_count": 0,
                "manual_supplements": (
                    _empty_manual_supplement_summary()
                ),
            },
        )
        region_summary["processed_count"] += 1
        retrieval = (
            payload.get("retrieval")
            if isinstance(payload.get("retrieval"), dict)
            else {}
        )
        region_summary["network_request_count"] += int(
            retrieval.get("network_request_count") or 0
        )
        if retrieval.get("cache_hit"):
            region_summary["cache_hit_count"] += 1
        else:
            region_summary["cache_miss_count"] += 1
        if not payload.get("failure_reason"):
            region_summary["complete_candidate_count"] += 1
        else:
            region_summary["blocked_count"] += 1
        for reason in payload.get("failure_reason", []):
            failures[str(reason)] = failures.get(str(reason), 0) + 1
        manual_outcomes = _manual_supplement_outcomes(payload)
        _add_manual_supplement_summary(
            region_summary["manual_supplements"],
            manual_outcomes,
        )
        _add_manual_supplement_summary(
            manual_summary,
            manual_outcomes,
        )
    if failures:
        next_batch_recommendation = "fix_adapters_or_route_blockers_for_manual_review"
    else:
        next_batch_recommendation = "proceed_to_module_review_without_database_commit"
    coverage_counts = {
        group: sum(
            bool(row.get("coverage", {}).get(group, {}).get("complete"))
            for row in payloads
        )
        for group in (
            "basic_profile",
            "pedigree",
            "career_history",
            "source_evidence",
        )
    }
    return {
        "artifact_type": "p0_horse_completion_summary",
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "reviewed_input_sha256": reviewed_input_sha256,
        "read_only": True,
        "processed_count": len(payloads),
        "complete_candidate_count": sum(not row.get("failure_reason") for row in payloads),
        "blocked_count": sum(bool(row.get("failure_reason")) for row in payloads),
        "regions": by_region,
        "failure_reason_counts": failures,
        "coverage_complete_counts": coverage_counts,
        "alias_candidate_count": sum(bool(row.get("aliases")) for row in payloads),
        "major_wins_candidate_count": sum(
            bool(row.get("major_wins")) for row in payloads
        ),
        "network_request_count": sum(
            int(row.get("retrieval", {}).get("network_request_count") or 0)
            for row in payloads
        ),
        "cache_hit_count": sum(
            bool(row.get("retrieval", {}).get("cache_hit")) for row in payloads
        ),
        "cache_miss_count": sum(
            not bool(row.get("retrieval", {}).get("cache_hit"))
            for row in payloads
        ),
        "manual_supplements": manual_summary,
        "failure_examples": {
            reason: [
                {
                    "candidate_key": row.get("candidate_key"),
                    "horse_name": row.get("horse_name"),
                    "source_evidence": row.get("source_evidence", []),
                }
                for row in payloads
                if reason in row.get("failure_reason", [])
            ][:3]
            for reason in sorted(failures)
        },
        "next_batch_recommendation": next_batch_recommendation,
    }


def write_p0_horse_completion_artifacts(
    payloads: Iterable[dict[str, Any]],
    output_dir: str | Path,
    *,
    reviewed_input_sha256: str,
    generated_at: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", str(reviewed_input_sha256 or "")):
        raise ValueError("reviewed_input_sha256 must be a lowercase SHA-256")
    output = Path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"P0 horse completion artifact output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    rows = sorted(
        (validate_p0_horse_completion_payload(row) for row in payloads),
        key=lambda row: (
            str(row.get("region") or ""),
            str(row.get("candidate_key") or ""),
        ),
    )
    candidate_keys = [str(row.get("candidate_key") or "") for row in rows]
    if any(not key for key in candidate_keys):
        raise ValueError("P0 horse completion artifact contains an empty candidate key")
    if len(set(candidate_keys)) != len(candidate_keys):
        raise ValueError("P0 horse completion artifact contains duplicate candidate keys")
    review_rows = [_review_row(row) for row in rows]
    failures = [row for row in rows if row.get("failure_reason")]
    module_diffs = [
        {
            "candidate_key": row.get("candidate_key"),
            "region": row.get("region"),
            "horse_name": row.get("horse_name"),
            "module_diff": row.get("module_diff", {}),
            "failure_reason": row.get("failure_reason", []),
        }
        for row in rows
    ]
    evidence_rows = [
        {
            "candidate_key": row.get("candidate_key"),
            "region": row.get("region"),
            "horse_name": row.get("horse_name"),
            "source_evidence": row.get("source_evidence", []),
            "race_record_source_evidence": [
                {
                    "race_name": record.get("race_name"),
                    "race_date": record.get("race_date"),
                    "race_year": record.get("race_year"),
                    "sources": record.get("source_refs", {}).get("sources", []),
                }
                for record in row.get("race_records", [])
            ],
        }
        for row in rows
    ]
    summary = _artifact_summary(
        rows,
        generated_at=generated_at,
        reviewed_input_sha256=reviewed_input_sha256,
    )
    source_manifest = {
        "artifact_type": "p0_horse_completion_source_evidence",
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "reviewed_input_sha256": reviewed_input_sha256,
        "read_only": True,
        "candidate_count": len(rows),
        "evidence": evidence_rows,
    }

    contents = {
        "p0_horse_completion_candidates.jsonl": _jsonl_bytes(rows),
        "p0_horse_completion_review.csv": _csv_bytes(
            review_rows,
            [
                "candidate_key",
                "region",
                "horse_name",
                "confidence",
                "failure_reason",
                "source_urls",
                "career_history_status",
                "reviewed",
                "basic_profile_decision",
                "pedigree_decision",
                "race_records_decision",
                "major_wins_decision",
                "reviewer_id",
                "reviewed_at",
            ],
        ),
        "p0_horse_completion_failures_and_conflicts.jsonl": _jsonl_bytes(failures),
        "p0_horse_completion_module_diff.jsonl": _jsonl_bytes(module_diffs),
        "source_evidence_manifest.json": _canonical_json_bytes(source_manifest),
        "summary.json": _canonical_json_bytes(summary),
    }
    for filename, content in contents.items():
        _write_bytes(output / filename, content)

    return {
        "artifact_type": "p0_horse_completion_artifact_manifest",
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "reviewed_input_sha256": reviewed_input_sha256,
        "read_only": True,
        "files": {
            filename: {
                "path": filename,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for filename, content in sorted(contents.items())
        },
    }
