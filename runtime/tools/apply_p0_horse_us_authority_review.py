from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched_v2.json"
)
DEFAULT_REVIEW = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "reviewed_us_career_source_authority_v1.json"
)
DEFAULT_PREPARED_REVIEW = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "prepared_us_career_source_authority_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched_v3.json"
)
DEFAULT_MODULE_REVIEW = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched_v3_research_module_review.json"
)
DEFAULT_READINESS_REPORT = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched_v3_production_readiness_report.json"
)

REVIEW_SCHEMA = "p0-horse-us-career-source-authority-review.v1"
APPLICATION_SCHEMA = "p0-horse-us-career-source-authority-application.v1"
MODULE_REVIEW_SCHEMA = "p0-horse-research-module-review.v1"
READINESS_REPORT_SCHEMA = "p0-horse-production-readiness-report.v1"
REVIEW_SCOPE = "exact_frozen_us_career_record_source_composition"
DECISION_SCOPE = (
    "project_owner_source_composition_authority_decision_"
    "not_per_field_manual_review"
)
TRUSTED_INPUT_SHA256 = (
    "a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7"
)
# Updated only when an independently approved manifest is frozen in the repo.
TRUSTED_APPROVED_REVIEW_SHA256 = (
    "29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077"
)
PRODUCTION_READINESS_BLOCKERS = [
    "not_horse_profile_completion_plan",
    "missing_production_profile_ids",
    "missing_production_reviewer_id",
    "missing_commit_compatible_module_approvals",
]

ALLOWED_RECORD_HOSTS = {
    "www.horseracingnation.com": "horseracingnation",
    "horseracingnation.com": "horseracingnation",
    "www.sportinglife.com": "sporting_life",
    "sportinglife.com": "sporting_life",
    "www.racingpost.com": "racing_post",
    "racingpost.com": "racing_post",
}
SOURCE_NAME_ALIASES = {
    "hrn": "horseracingnation",
    "horse_racing_nation": "horseracingnation",
    "horseracingnation": "horseracingnation",
    "sporting_life": "sporting_life",
    "sportinglife": "sporting_life",
    "racing_post": "racing_post",
    "racingpost": "racing_post",
}
FORT_GEORGE_SOURCE_COUNTS = {
    "horseracingnation": 6,
    "sporting_life": 6,
    "racing_post": 1,
}
IDENTITY_FIELDS = (
    "horse_name",
    "sire_name",
    "dam_name",
    "birth_year",
)
STABLE_RECORD_FIELDS = (
    "external_result_id",
    "external_race_id",
    "race_date",
    "race_name",
    "racecourse",
    "finish",
    "finish_position",
    "result_status",
    "start_status",
    "source_name",
    "source_url",
)
NONSTART_FINISH_VALUES = {
    "scr",
    "scratched",
    "w",
    "wv",
    "withdrawn",
    "nr",
    "non runner",
}


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_frozen_write(path: Path, content: bytes) -> None:
    if path.exists():
        existing = path.read_bytes()
        if existing != content:
            raise ValueError(f"refusing to overwrite frozen artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _required_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{context} must not contain outer whitespace")
    return value


def _validated_timestamp(value: Any, *, context: str) -> str:
    timestamp = _required_string(value, context=context)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")
    return timestamp


def _input_data(input_bytes: bytes) -> dict[str, Any]:
    try:
        data = json.loads(input_bytes)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("input must be valid JSON bytes") from exc
    if not isinstance(data, dict) or not isinstance(data.get("horses"), list):
        raise ValueError("input must contain a horses array")
    return data


def _horse_name(horse: dict[str, Any]) -> str:
    return _required_string(
        (horse.get("candidate") or {}).get("horse_name")
        or (horse.get("identity") or {}).get("horse_name"),
        context="horse_name",
    )


def _identity(horse: dict[str, Any]) -> dict[str, Any]:
    identity = horse.get("identity")
    if not isinstance(identity, dict):
        raise ValueError(f"{_horse_name(horse)} requires identity")
    result = {field: identity.get(field) for field in IDENTITY_FIELDS}
    for field in IDENTITY_FIELDS[:-1]:
        _required_string(
            result[field],
            context=f"{_horse_name(horse)} identity.{field}",
        )
    birth_year = result["birth_year"]
    if (
        isinstance(birth_year, bool)
        or not isinstance(birth_year, int)
        or birth_year < 1800
    ):
        raise ValueError(
            f"{_horse_name(horse)} identity.birth_year must be an integer"
        )
    return result


def _record_provider(record: dict[str, Any]) -> str:
    source_url = _required_string(
        record.get("source_url"),
        context="record source_url",
    )
    parsed = urlsplit(source_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("record source_url has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.fragment
    ):
        raise ValueError("record source_url is not an allowed canonical URL")
    provider = ALLOWED_RECORD_HOSTS.get((parsed.hostname or "").lower())
    if provider is None:
        raise ValueError("record source_url provider is not allowed")
    source_name = _normalized(record.get("source_name"))
    if source_name:
        named_provider = SOURCE_NAME_ALIASES.get(source_name)
        if named_provider is None or named_provider != provider:
            raise ValueError("record source_name conflicts with source_url")
    return provider


def _record_source_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("career records must contain objects")
        counter[_record_provider(record)] += 1
    return dict(counter)


def _stable_record_keys(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {field: record.get(field) for field in STABLE_RECORD_FIELDS}
        for record in records
    ]


def _record_set_sha256(records: list[dict[str, Any]]) -> str:
    return _sha256_bytes(_compact_json_bytes(records))


def _stable_record_keys_sha256(records: list[dict[str, Any]]) -> str:
    return _sha256_bytes(_compact_json_bytes(_stable_record_keys(records)))


def _canonical_race_component(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _canonical_race_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _canonical_race_component(record.get("race_date")),
        _canonical_race_component(record.get("racecourse")),
        _canonical_race_component(record.get("race_name")),
    )


def _source_bound_record_ids(
    records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for record in records:
        provider = _record_provider(record)
        for field_name in ("external_result_id", "external_race_id"):
            external_id = record.get(field_name)
            if isinstance(external_id, str) and external_id.strip():
                result.append(
                    {
                        "provider": provider,
                        "id_type": field_name,
                        "external_id": external_id.strip(),
                    }
                )
    return result


def _canonical_race_keys(
    records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "race_date": key[0],
            "racecourse": key[1],
            "race_name": key[2],
        }
        for key in (_canonical_race_key(record) for record in records)
    ]


def _assert_unique_records(
    records: list[dict[str, Any]],
    *,
    horse_name: str,
) -> None:
    source_bound_ids: set[tuple[str, str, str]] = set()
    stable_keys: set[bytes] = set()
    canonical_race_keys: set[tuple[str, str, str]] = set()
    for index, record in enumerate(records):
        provider = _record_provider(record)
        for field_name in ("external_result_id", "external_race_id"):
            external_id = record.get(field_name)
            if not isinstance(external_id, str) or not external_id.strip():
                continue
            source_bound_id = (provider, field_name, external_id.strip())
            if source_bound_id in source_bound_ids:
                raise ValueError(
                    f"{horse_name} duplicate source-bound record ID: "
                    f"{field_name}={external_id.strip()}"
                )
            source_bound_ids.add(source_bound_id)

        stable_key = _compact_json_bytes(_stable_record_keys([record])[0])
        if stable_key in stable_keys:
            raise ValueError(
                f"{horse_name} duplicate stable record key at index {index}"
            )
        stable_keys.add(stable_key)

        canonical_race_key = _canonical_race_key(record)
        if not all(canonical_race_key):
            raise ValueError(
                f"{horse_name} canonical race key is incomplete at index {index}"
            )
        if canonical_race_key in canonical_race_keys:
            raise ValueError(
                f"{horse_name} duplicate canonical race key at index {index}"
            )
        canonical_race_keys.add(canonical_race_key)


def _equibase_evidence(horse: dict[str, Any]) -> dict[str, Any]:
    name = _horse_name(horse)
    career = horse.get("career")
    source = horse.get("source")
    if not isinstance(career, dict) or not isinstance(source, dict):
        raise ValueError(f"{name} requires career and source")
    count = career.get("official_or_source_start_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"{name} requires a non-negative official count")
    source_name = _required_string(
        career.get("official_start_count_source"),
        context=f"{name} official_start_count_source",
    )
    if _normalized(source_name) != "equibase":
        raise ValueError(f"{name} official count source must be Equibase")
    source_url = _required_string(
        career.get("official_start_count_source_url"),
        context=f"{name} official_start_count_source_url",
    )
    parsed = urlsplit(source_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} Equibase URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower()
        not in {"www.equibase.com", "equibase.com"}
        or parsed.path != "/profiles/Results.cfm"
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.fragment
    ):
        raise ValueError(f"{name} official count URL is not canonical Equibase")
    external_id = _required_string(
        source.get("external_horse_id"),
        context=f"{name} source.external_horse_id",
    )
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("refno") != [external_id]:
        raise ValueError(f"{name} Equibase refno does not match source identity")
    verified_at = _validated_timestamp(
        career.get("official_start_count_verified_at"),
        context=f"{name} official_start_count_verified_at",
    )
    return {
        "count": count,
        "source_name": source_name,
        "source_url": source_url,
        "verified_at": verified_at,
        "external_horse_id": external_id,
    }


def _expected_source_counts(
    horse_name: str,
    *,
    record_count: int,
) -> dict[str, int]:
    if horse_name == "Fort George":
        return dict(FORT_GEORGE_SOURCE_COUNTS)
    return {"horseracingnation": record_count}


def _allowed_source_policy() -> dict[str, Any]:
    return {
        "default_us_horse": {
            "horseracingnation": "all_records",
        },
        "Fort George": dict(FORT_GEORGE_SOURCE_COUNTS),
        "official_start_count_source": "equibase",
    }


def _review_row(horse: dict[str, Any]) -> dict[str, Any]:
    name = _horse_name(horse)
    career = horse.get("career")
    if not isinstance(career, dict) or not isinstance(career.get("records"), list):
        raise ValueError(f"{name} requires career.records")
    records = career["records"]
    _assert_unique_records(records, horse_name=name)
    source_counts = _record_source_counts(records)
    expected_counts = _expected_source_counts(name, record_count=len(records))
    if source_counts != expected_counts:
        raise ValueError(
            f"{name} source composition is not reviewable: "
            f"{source_counts!r} != {expected_counts!r}"
        )
    stable_keys = _stable_record_keys(records)
    source_bound_ids = _source_bound_record_ids(records)
    canonical_race_keys = _canonical_race_keys(records)
    return {
        "identity": _identity(horse),
        "official_start_count_evidence": _equibase_evidence(horse),
        "record_count": len(records),
        "record_source_counts": source_counts,
        "record_set_sha256": _record_set_sha256(records),
        "stable_record_keys_sha256": _stable_record_keys_sha256(records),
        "stable_record_keys": stable_keys,
        "source_bound_record_id_count": len(source_bound_ids),
        "source_bound_record_ids_sha256": _sha256_bytes(
            _compact_json_bytes(source_bound_ids)
        ),
        "canonical_race_key_count": len(canonical_race_keys),
        "canonical_race_keys_sha256": _sha256_bytes(
            _compact_json_bytes(canonical_race_keys)
        ),
        "pre_review_record_authority_status": career.get(
            "record_authority_status"
        ),
        "approved_record_authority_status": "source_records_verified",
    }


def prepare_review_manifest(
    input_bytes: bytes,
    *,
    input_path: str,
    prepared_by: str | None = None,
    prepared_at: str | None = None,
    review_status: str = "pending",
    reviewed_by: str | None = None,
    review_reference: str | None = None,
    review_recorded_at: str | None = None,
) -> dict[str, Any]:
    data = _input_data(input_bytes)
    if (
        review_status != "pending"
        or reviewed_by
        or review_reference
        or review_recorded_at
    ):
        raise ValueError(
            "prepare may only create a pending review artifact"
        )
    preparer = _required_string(prepared_by, context="prepared_by")
    prepared_timestamp = _validated_timestamp(
        prepared_at,
        context="prepared_at",
    )
    us_horses = [
        horse
        for horse in data["horses"]
        if horse.get("region") == "united_states"
    ]
    if len(data["horses"]) != 50 or len(us_horses) != 10:
        raise ValueError("review artifact requires the frozen 50/10 batch")
    rows = [_review_row(horse) for horse in us_horses]
    if len({_horse_name(horse) for horse in us_horses}) != 10:
        raise ValueError("review artifact requires ten unique US horses")
    return {
        "schema_version": REVIEW_SCHEMA,
        "review_status": "pending",
        "prepared_by": preparer,
        "prepared_at": prepared_timestamp,
        "reviewed_by": None,
        "approved_at": None,
        "decision_source_reference": None,
        "decision_scope": DECISION_SCOPE,
        "review_scope": REVIEW_SCOPE,
        "input": {
            "path": input_path,
            "sha256": _sha256_bytes(input_bytes),
        },
        "horse_count": len(data["horses"]),
        "us_horse_count": len(us_horses),
        "row_count": len(rows),
        "allowed_source_policy": _allowed_source_policy(),
        "horses": rows,
    }


def _contains_conflict(value: Any) -> bool:
    if isinstance(value, dict):
        if _normalized(value.get("status")) == "conflict":
            return True
        return any(_contains_conflict(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_conflict(item) for item in value)
    return False


def _record_start_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    actual = 0
    nonstarter = 0
    unknown = 0
    for record in records:
        start_status = _normalized(record.get("start_status"))
        result_status = _normalized(record.get("result_status"))
        finish = _normalized(
            record.get("finish") or record.get("finish_position")
        )
        if (
            start_status in {"did_not_start", "not_started"}
            or result_status in {"scratched", "withdrawn", "did_not_start"}
            or finish in NONSTART_FINISH_VALUES
        ):
            nonstarter += 1
        elif (
            result_status == "unknown"
            or record.get("result_evidence_status")
            == "requires_authoritative_supplement"
            or finish == "n/a"
        ):
            unknown += 1
        else:
            actual += 1
    return {
        "actual": actual,
        "nonstarter": nonstarter,
        "unknown": unknown,
    }


def _manifest_rows(
    manifest: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    blockers: list[str] = []
    rows = manifest.get("horses")
    if not isinstance(rows, list):
        return {}, ["review_horses_invalid"]
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("identity"), dict):
            blockers.append("review_horse_row_invalid")
            continue
        name = row["identity"].get("horse_name")
        if not isinstance(name, str) or not name or name in by_name:
            blockers.append("review_horse_identity_duplicate_or_invalid")
            continue
        by_name[name] = row
    return by_name, blockers


def _validate_review(
    data: dict[str, Any],
    *,
    input_bytes: bytes,
    input_path: str,
    manifest: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if manifest.get("schema_version") != REVIEW_SCHEMA:
        blockers.append("review_schema_mismatch")
    if manifest.get("review_status") != "approved":
        blockers.append("review_not_approved")
    if manifest.get("review_scope") != REVIEW_SCOPE:
        blockers.append("review_scope_mismatch")
    if manifest.get("allowed_source_policy") != _allowed_source_policy():
        blockers.append("allowed_source_policy_mismatch")
    try:
        _required_string(
            manifest.get("prepared_by"),
            context="prepared_by",
        )
        _validated_timestamp(
            manifest.get("prepared_at"),
            context="prepared_at",
        )
        _required_string(manifest.get("reviewed_by"), context="reviewed_by")
        _required_string(
            manifest.get("decision_source_reference"),
            context="decision_source_reference",
        )
        _validated_timestamp(
            manifest.get("approved_at"),
            context="approved_at",
        )
        if manifest.get("decision_scope") != DECISION_SCOPE:
            raise ValueError("decision_scope mismatch")
    except ValueError:
        blockers.append("review_metadata_invalid")
    input_binding = manifest.get("input")
    if not isinstance(input_binding, dict):
        blockers.append("review_input_binding_invalid")
    else:
        if input_binding.get("path") != input_path:
            blockers.append("input_path_mismatch")
        if input_binding.get("sha256") != _sha256_bytes(input_bytes):
            blockers.append("input_sha256_mismatch")
    if manifest.get("horse_count") != len(data.get("horses") or []):
        blockers.append("horse_count_mismatch")

    us_horses = [
        horse
        for horse in data.get("horses") or []
        if isinstance(horse, dict) and horse.get("region") == "united_states"
    ]
    if (
        len(data.get("horses") or []) != 50
        or len(us_horses) != 10
        or manifest.get("us_horse_count") != 10
        or manifest.get("row_count") != 10
    ):
        blockers.append("review_batch_cardinality_mismatch")
    rows_by_name, row_blockers = _manifest_rows(manifest)
    blockers.extend(row_blockers)
    if set(rows_by_name) != {_horse_name(horse) for horse in us_horses}:
        blockers.append("review_horse_set_mismatch")

    for horse in us_horses:
        name = _horse_name(horse)
        row = rows_by_name.get(name)
        if row is None:
            continue
        try:
            identity = _identity(horse)
        except ValueError:
            blockers.append(f"identity_invalid:{name}")
            continue
        if row.get("identity") != identity:
            blockers.append(f"identity_mismatch:{name}")

        try:
            official_evidence = _equibase_evidence(horse)
        except ValueError:
            blockers.append(f"official_start_count_evidence_invalid:{name}")
            official_evidence = None
        if row.get("official_start_count_evidence") != official_evidence:
            blockers.append(
                f"official_start_count_evidence_mismatch:{name}"
            )

        career = horse.get("career") or {}
        field_status = horse.get("field_status") or {}
        records = career.get("records")
        if not isinstance(records, list):
            blockers.append(f"career_records_invalid:{name}")
            continue
        try:
            _assert_unique_records(records, horse_name=name)
            source_counts = _record_source_counts(records)
        except ValueError as exc:
            blockers.append(f"record_uniqueness_or_source_invalid:{name}")
            blockers.append(f"record_validation_error:{name}:{exc}")
            blockers.append(f"record_source_not_allowed:{name}")
            source_counts = None
        expected_counts = _expected_source_counts(
            name,
            record_count=len(records),
        )
        if (
            source_counts is not None
            and (
                source_counts != expected_counts
                or row.get("record_source_counts") != source_counts
            )
        ):
            blockers.append(f"record_source_composition_mismatch:{name}")
        if row.get("record_count") != len(records):
            blockers.append(f"record_count_mismatch:{name}")
        if row.get("record_set_sha256") != _record_set_sha256(records):
            blockers.append(f"record_set_sha256_mismatch:{name}")
        if (
            row.get("stable_record_keys_sha256")
            != _stable_record_keys_sha256(records)
            or row.get("stable_record_keys") != _stable_record_keys(records)
        ):
            blockers.append(f"stable_record_summary_mismatch:{name}")
        try:
            source_bound_ids = _source_bound_record_ids(records)
        except ValueError:
            source_bound_ids = None
        if source_bound_ids is not None:
            if (
                row.get("source_bound_record_id_count")
                != len(source_bound_ids)
                or row.get("source_bound_record_ids_sha256")
                != _sha256_bytes(_compact_json_bytes(source_bound_ids))
            ):
                blockers.append(f"source_bound_id_summary_mismatch:{name}")
        canonical_race_keys = _canonical_race_keys(records)
        if (
            row.get("canonical_race_key_count")
            != len(canonical_race_keys)
            or row.get("canonical_race_keys_sha256")
            != _sha256_bytes(_compact_json_bytes(canonical_race_keys))
        ):
            blockers.append(f"canonical_race_summary_mismatch:{name}")

        start_counts = _record_start_counts(records)
        official_count = career.get("official_or_source_start_count")
        if (
            career.get("source_start_count_quality") != "official_verified"
            or official_count != start_counts["actual"]
            or field_status.get("career_count_matches") is not True
        ):
            blockers.append(f"official_count_not_aligned:{name}")
        if field_status.get("career_missing_start_count", 0) != 0:
            blockers.append(f"career_missing_start_count_nonzero:{name}")
        if field_status.get("career_excess_start_count", 0) != 0:
            blockers.append(f"career_excess_start_count_nonzero:{name}")
        if (
            field_status.get("unknown_record_count", 0) != 0
            or start_counts["unknown"] != 0
        ):
            blockers.append(f"unknown_record_count_nonzero:{name}")
        if _contains_conflict(horse):
            blockers.append(f"conflict_present:{name}")
        if career.get("record_authority_status") not in {
            "count_aligned_records_unverified",
            "source_records_verified",
        }:
            blockers.append(f"pre_review_authority_invalid:{name}")
        if (
            row.get("pre_review_record_authority_status")
            != career.get("record_authority_status")
            or row.get("approved_record_authority_status")
            != "source_records_verified"
        ):
            blockers.append(f"review_authority_transition_mismatch:{name}")

    return list(dict.fromkeys(blockers))


def strict_complete_horse_count(data: dict[str, Any]) -> int:
    count = 0
    for horse in data.get("horses") or []:
        if not isinstance(horse, dict):
            continue
        field_status = horse.get("field_status") or {}
        career = horse.get("career") or {}
        if (
            not field_status.get("missing_basic_profile_fields")
            and not field_status.get("missing_pedigree_fields")
            and field_status.get("career_count_matches") is True
            and field_status.get("career_missing_start_count", 0) == 0
            and field_status.get("career_excess_start_count", 0) == 0
            and field_status.get("unknown_record_count", 0) == 0
            and career.get("record_authority_status")
            == "source_records_verified"
            and career.get("career_collection_status") == "complete"
            and not _contains_conflict(horse)
        ):
            count += 1
    return count


def _base_reports(
    *,
    data: dict[str, Any],
    input_sha256: str,
    review_sha256: str,
    decision: str,
    blockers: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    strict_count = strict_complete_horse_count(data)
    source_review_approved = decision == "approved"
    module_review = {
        "schema_version": MODULE_REVIEW_SCHEMA,
        "mode": "research_read_only_module_review",
        "module": "race_records",
        "decision": (
            "source_composition_approved"
            if source_review_approved
            else "blocked"
        ),
        "blockers": blockers,
        "input_sha256": input_sha256,
        "review_artifact_sha256": review_sha256,
        "reviewed_horse_count": 10 if source_review_approved else 0,
        "approved_horse_count": 10 if source_review_approved else 0,
        "commit_artifact_compatible": False,
        "production_application_authorized": False,
        "rows": [],
        "database_write_count": 0,
    }
    readiness_blockers = list(blockers)
    if source_review_approved:
        readiness_blockers.extend(PRODUCTION_READINESS_BLOCKERS)
    readiness_report = {
        "schema_version": READINESS_REPORT_SCHEMA,
        "mode": "production_readiness_report",
        "decision": "blocked",
        "blockers": list(dict.fromkeys(readiness_blockers)),
        "input_sha256": input_sha256,
        "review_artifact_sha256": review_sha256,
        "horse_count": len(data.get("horses") or []),
        "strict_complete_before": strict_count,
        "strict_complete_after": strict_count,
        "strict_complete_target": 50,
        "us_authority_reviewed_count": (
            10 if source_review_approved else 0
        ),
        "commit_artifact_compatible": False,
        "commit_artifact_type": None,
        "load_completion_artifact_compatible": False,
        "safe_simulation_performed": False,
        "assessment_type": "static_schema_compatibility_check",
        "commit_validation": {
            "loader": (
                "stable.services.horse_profile_completion."
                "load_completion_artifact"
            ),
            "loader_preflight_result": (
                "rejected_not_horse_profile_completion_plan"
            ),
            "formal_simulation_status": (
                "not_run_missing_commit_artifact"
            ),
        },
        "production_write_enabled": False,
        "database_write_count": 0,
        "ready_for_separate_production_commit_review": False,
    }
    return module_review, readiness_report


def apply_authority_review(
    input_bytes: bytes,
    *,
    review_bytes: bytes | None,
    input_path: str,
    expected_review_sha256: str | None = None,
) -> dict[str, Any]:
    data = _input_data(input_bytes)
    input_sha256 = _sha256_bytes(input_bytes)
    blockers: list[str] = []
    if input_sha256 != TRUSTED_INPUT_SHA256:
        blockers.append("input_sha256_not_trusted_frozen_v2")
    if expected_review_sha256 != TRUSTED_APPROVED_REVIEW_SHA256:
        blockers.append(
            "review_artifact_sha256_not_independently_frozen"
        )
    if review_bytes is None:
        blockers.append("review_artifact_missing")
        module_review, readiness_report = _base_reports(
            data=data,
            input_sha256=input_sha256,
            review_sha256="",
            decision="blocked",
            blockers=blockers,
        )
        return {
            "decision": "blocked",
            "blockers": blockers,
            "data": data,
            "module_review": module_review,
            "readiness_report": readiness_report,
        }
    review_sha256 = _sha256_bytes(review_bytes)
    if review_sha256 != expected_review_sha256:
        blockers.append("review_artifact_sha256_argument_mismatch")
    if review_sha256 != TRUSTED_APPROVED_REVIEW_SHA256:
        blockers.append(
            "review_artifact_sha256_not_independently_frozen"
        )
    try:
        manifest = json.loads(review_bytes)
    except (TypeError, json.JSONDecodeError):
        manifest = {}
        blockers.append("review_artifact_invalid_json")
    else:
        if not isinstance(manifest, dict):
            manifest = {}
            blockers.append("review_artifact_invalid")
        else:
            blockers.extend(
                _validate_review(
                    data,
                    input_bytes=input_bytes,
                    input_path=input_path,
                    manifest=manifest,
                )
            )
    blockers = list(dict.fromkeys(blockers))
    if blockers:
        module_review, readiness_report = _base_reports(
            data=data,
            input_sha256=input_sha256,
            review_sha256=review_sha256,
            decision="blocked",
            blockers=blockers,
        )
        return {
            "decision": "blocked",
            "blockers": blockers,
            "data": data,
            "module_review": module_review,
            "readiness_report": readiness_report,
        }

    strict_before = strict_complete_horse_count(data)
    derived = copy.deepcopy(data)
    review_rows = {
        row["identity"]["horse_name"]: row
        for row in manifest["horses"]
    }
    module_rows: list[dict[str, Any]] = []
    for horse in derived["horses"]:
        if horse.get("region") != "united_states":
            continue
        name = _horse_name(horse)
        career = horse["career"]
        field_status = horse["field_status"]
        before_authority = career.get("record_authority_status")
        career["record_authority_status"] = "source_records_verified"
        career["career_collection_status"] = "complete"
        field_status["record_authority_status"] = "source_records_verified"
        review_row = review_rows[name]
        career["authority_review"] = {
            "schema_version": REVIEW_SCHEMA,
            "review_artifact_sha256": review_sha256,
            "prepared_by": manifest["prepared_by"],
            "prepared_at": manifest["prepared_at"],
            "reviewed_by": manifest["reviewed_by"],
            "approved_at": manifest["approved_at"],
            "decision_source_reference": manifest[
                "decision_source_reference"
            ],
            "decision_scope": manifest["decision_scope"],
            "record_set_sha256": review_row["record_set_sha256"],
            "stable_record_keys_sha256": review_row[
                "stable_record_keys_sha256"
            ],
            "record_source_counts": review_row["record_source_counts"],
        }
        module_rows.append(
            {
                "identity": review_row["identity"],
                "module": "race_records",
                "decision": "approved",
                "before_record_authority_status": before_authority,
                "after_record_authority_status": "source_records_verified",
                "record_count": review_row["record_count"],
                "record_source_counts": review_row[
                    "record_source_counts"
                ],
                "record_set_sha256": review_row["record_set_sha256"],
            }
        )
    derived["schema_version"] = "p0-horse-research.v3"
    derived["career_authority_review_application"] = {
        "schema_version": APPLICATION_SCHEMA,
        "input_sha256": input_sha256,
        "review_artifact_sha256": review_sha256,
        "prepared_by": manifest["prepared_by"],
        "prepared_at": manifest["prepared_at"],
        "reviewed_by": manifest["reviewed_by"],
        "approved_at": manifest["approved_at"],
        "decision_source_reference": manifest[
            "decision_source_reference"
        ],
        "decision_scope": manifest["decision_scope"],
        "approved_region": "united_states",
        "approved_horse_count": 10,
        "record_authority_status": "source_records_verified",
        "database_write_count": 0,
    }
    strict_after = strict_complete_horse_count(derived)
    if strict_before != 40 or strict_after != 50:
        raise ValueError(
            "reviewed derivative must move strict completeness from 40 to 50"
        )
    module_review, readiness_report = _base_reports(
        data=data,
        input_sha256=input_sha256,
        review_sha256=review_sha256,
        decision="approved",
        blockers=[],
    )
    module_review["rows"] = module_rows
    readiness_report["strict_complete_before"] = strict_before
    readiness_report["strict_complete_after"] = strict_after
    return {
        "decision": "approved",
        "blockers": [],
        "data": derived,
        "module_review": module_review,
        "readiness_report": readiness_report,
    }


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _prepare_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    input_bytes = input_path.read_bytes()
    manifest = prepare_review_manifest(
        input_bytes,
        input_path=_relative_path(input_path),
        prepared_by=args.prepared_by,
        prepared_at=args.prepared_at,
    )
    content = canonical_json_bytes(manifest)
    _atomic_frozen_write(output_path, content)
    print(
        json.dumps(
            {
                "mode": "prepare_review",
                "output": _relative_path(output_path),
                "sha256": _sha256_bytes(content),
                "review_status": manifest["review_status"],
                "row_count": manifest["row_count"],
                "database_write_count": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _apply_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    review_path = Path(args.review)
    output_path = Path(args.output)
    module_review_path = Path(args.module_review_output)
    readiness_report_path = Path(args.readiness_report_output)
    if output_path.resolve() in {input_path.resolve(), review_path.resolve()}:
        raise ValueError("derived output must not overwrite an input artifact")
    input_bytes = input_path.read_bytes()
    review_bytes = review_path.read_bytes()
    result = apply_authority_review(
        input_bytes,
        review_bytes=review_bytes,
        input_path=_relative_path(input_path),
        expected_review_sha256=args.approved_review_sha256,
    )
    if result["decision"] != "approved":
        print(
            json.dumps(
                {
                    "mode": "apply_review",
                    "decision": "blocked",
                    "blockers": result["blockers"],
                    "database_write_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    output_bytes = canonical_json_bytes(result["data"])
    _atomic_frozen_write(output_path, output_bytes)
    output_sha256 = _sha256_bytes(output_bytes)

    module_review = result["module_review"]
    module_review["derived_output"] = {
        "path": _relative_path(output_path),
        "sha256": output_sha256,
    }
    module_review["review_artifact"] = {
        "path": _relative_path(review_path),
        "sha256": _sha256_bytes(review_bytes),
    }
    module_review_bytes = canonical_json_bytes(module_review)
    _atomic_frozen_write(module_review_path, module_review_bytes)

    readiness_report = result["readiness_report"]
    readiness_report["derived_output"] = module_review["derived_output"]
    readiness_report["review_artifact"] = module_review["review_artifact"]
    readiness_report["research_module_review"] = {
        "path": _relative_path(module_review_path),
        "sha256": _sha256_bytes(module_review_bytes),
    }
    readiness_report_bytes = canonical_json_bytes(readiness_report)
    _atomic_frozen_write(
        readiness_report_path,
        readiness_report_bytes,
    )
    print(
        json.dumps(
            {
                "mode": "apply_review",
                "decision": "approved",
                "output": _relative_path(output_path),
                "output_sha256": output_sha256,
                "module_review": _relative_path(module_review_path),
                "module_review_sha256": _sha256_bytes(module_review_bytes),
                "readiness_report": _relative_path(
                    readiness_report_path
                ),
                "readiness_report_sha256": _sha256_bytes(
                    readiness_report_bytes
                ),
                "strict_complete_before": readiness_report[
                    "strict_complete_before"
                ],
                "strict_complete_after": readiness_report[
                    "strict_complete_after"
                ],
                "commit_artifact_compatible": False,
                "database_write_count": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and apply the reviewed US career source composition "
            "without database writes."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--input", default=str(DEFAULT_INPUT))
    prepare.add_argument("--output", default=str(DEFAULT_PREPARED_REVIEW))
    prepare.add_argument("--prepared-by", required=True)
    prepare.add_argument("--prepared-at", required=True)
    prepare.set_defaults(handler=_prepare_command)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--input", default=str(DEFAULT_INPUT))
    apply.add_argument("--review", default=str(DEFAULT_REVIEW))
    apply.add_argument(
        "--approved-review-sha256",
        required=True,
        help=(
            "Exact SHA-256 of the independently frozen approved review "
            "manifest; it must also match the code trust anchor."
        ),
    )
    apply.add_argument("--output", default=str(DEFAULT_OUTPUT))
    apply.add_argument(
        "--module-review-output",
        default=str(DEFAULT_MODULE_REVIEW),
    )
    apply.add_argument(
        "--readiness-report-output",
        default=str(DEFAULT_READINESS_REPORT),
    )
    apply.set_defaults(handler=_apply_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
