from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.tools.research_p0_horse_pedigree import (
    horse_identity_key,
    netkeiba_profile_external_id,
    normalized_name,
    valid_http_url,
)


DEFAULT_INPUT = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched.json"
)
DEFAULT_MANIFEST = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "reviewed_parent_identity_evidence.json"
)
DEFAULT_PARENT_BIRTH_YEAR_EVIDENCE = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "reviewed_parent_birth_year_evidence.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched_v2.json"
)
MANIFEST_SCHEMA = "p0-horse-parent-identity-review.v2"
APPLICATION_SCHEMA = "p0-horse-parent-identity-review-application.v2"
PARENT_BIRTH_YEAR_EVIDENCE_SCHEMA = (
    "p0-horse-parent-birth-year-evidence.v1"
)
LEGACY_METHOD = "exact_parent_name_unique_match"
LEGACY_METHODS = {
    LEGACY_METHOD,
    "exact_parent_name_and_known_sire_match",
}
REVIEWED_METHOD = "reviewed_parent_source_external_id_binding"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_bytes(content)
    temporary_path.replace(path)


def _validated_review_recorded_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("review_recorded_at must be a non-empty string")
    normalized = value.strip()
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("review_recorded_at must be a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("review_recorded_at must include a timezone offset")
    return normalized


def _target_source_identity(horse: dict[str, Any]) -> tuple[str, str]:
    source = horse.get("source") or {}
    source_name = normalized_name(source.get("name"))
    external_id_value = source.get("external_horse_id")
    if not source_name or not isinstance(external_id_value, str):
        raise ValueError("reviewed target horse requires provider-bound source identity")
    external_id = external_id_value.strip()
    if not external_id:
        raise ValueError("reviewed target horse external ID is empty")
    return source_name, external_id


def _netkeiba_external_id(source_url: Any) -> str:
    external_id = netkeiba_profile_external_id(source_url)
    if external_id is None:
        raise ValueError("legacy parent evidence URL is not a Netkeiba horse profile")
    return external_id


def _required_string(
    row: dict[str, Any],
    key: str,
    *,
    context: str,
) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires {key}")
    if value != value.strip():
        raise ValueError(f"{context} {key} must not contain outer whitespace")
    return value


def _optional_string(
    row: dict[str, Any],
    key: str,
    *,
    context: str,
) -> str:
    value = row.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{context} {key} must be a string")
    if value != value.strip():
        raise ValueError(f"{context} {key} must not contain outer whitespace")
    return value


def _validated_url(value: str, *, context: str) -> str:
    if not valid_http_url(value):
        raise ValueError(f"{context} must be a valid HTTP(S) URL")
    return value


def _validated_parent_birth_year(
    value: Any,
    *,
    target_birth_year: int | None = None,
) -> int:
    current_year = datetime.now(timezone.utc).year
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1800
        or value > current_year
    ):
        raise ValueError(
            f"parent_birth_year must be an int between 1800 and {current_year}"
        )
    if target_birth_year is not None and value >= target_birth_year:
        raise ValueError(
            "parent_birth_year must be earlier than target horse birth_year"
        )
    return value


def _target_birth_year(horse: dict[str, Any]) -> int:
    identity = horse.get("identity") or {}
    value = identity.get("birth_year")
    current_year = datetime.now(timezone.utc).year
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1800
        or value > current_year
    ):
        raise ValueError(
            "reviewed target horse requires an integer birth_year "
            f"between 1800 and {current_year}"
        )
    return value


def _source_key(
    source_name: Any,
    external_id: Any,
    *,
    context: str,
) -> tuple[str, str]:
    if not isinstance(source_name, str) or source_name != source_name.strip():
        raise ValueError(f"{context} source provider must be an exact string")
    normalized_provider = normalized_name(source_name)
    if not normalized_provider:
        raise ValueError(f"{context} source provider is empty")
    if (
        not isinstance(external_id, str)
        or external_id != external_id.strip()
        or not external_id
    ):
        raise ValueError(f"{context} external ID must be an exact opaque string")
    return normalized_provider, external_id


def _legacy_review_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horse in data.get("horses") or []:
        if not isinstance(horse, dict):
            raise ValueError("horse payload must be an object")
        target_source_name, target_external_id = _target_source_identity(horse)
        target_birth_year = _target_birth_year(horse)
        identity_key = horse_identity_key(horse)
        if not all(part.strip() for part in identity_key.split("|")):
            raise ValueError("reviewed target horse requires complete four-field identity")
        pedigree = horse.get("pedigree") or {}
        for evidence in horse.get("pedigree_field_evidence") or []:
            if (
                not isinstance(evidence, dict)
                or evidence.get("verification_method") not in LEGACY_METHODS
            ):
                continue
            field_name = str(evidence.get("field_name") or "").strip()
            parent_role = {
                "sire_sire": "sire",
                "sire_dam": "sire",
                "dam_sire": "dam",
                "dam_dam": "dam",
            }.get(field_name)
            if parent_role is None:
                raise ValueError(
                    "legacy parent evidence has an unsupported pedigree field"
                )
            parent_name = str(pedigree.get(parent_role) or "").strip()
            if not parent_name:
                raise ValueError("legacy parent evidence requires the parent name")
            value = str(evidence.get("value") or "").strip()
            if not value or normalized_name(pedigree.get(field_name)) != normalized_name(
                value
            ):
                raise ValueError("legacy parent evidence conflicts with pedigree value")
            source_name_value = evidence.get("source_name")
            if not isinstance(source_name_value, str):
                raise ValueError("legacy parent evidence provider must be a string")
            source_name = source_name_value.strip()
            if normalized_name(source_name) != normalized_name("netkeiba_en"):
                raise ValueError("legacy parent evidence has an unexpected provider")
            source_url = str(evidence.get("source_url") or "").strip()
            parent_external_id = _netkeiba_external_id(source_url)
            rows.append(
                {
                    "target_source_name": target_source_name,
                    "target_external_horse_id": target_external_id,
                    "target_identity_key": identity_key,
                    "target_birth_year": target_birth_year,
                    "parent_role": parent_role,
                    "parent_name": parent_name,
                    "field_name": field_name,
                    "value": value,
                    "legacy_verification_method": evidence[
                        "verification_method"
                    ],
                    "parent_source_name": source_name,
                    "parent_external_horse_id": parent_external_id,
                    "parent_source_url": source_url,
                    "legacy_parent_source_name": source_name,
                    "legacy_parent_external_horse_id": parent_external_id,
                    "legacy_parent_source_url": source_url,
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["target_source_name"],
            row["target_external_horse_id"],
            row["field_name"],
        ),
    )


def _parent_birth_year_evidence(
    evidence_bytes: bytes,
) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    artifact = json.loads(evidence_bytes.decode("utf-8"))
    if not isinstance(artifact, dict):
        raise ValueError("parent birth-year evidence must be an object")
    if artifact.get("schema_version") != PARENT_BIRTH_YEAR_EVIDENCE_SCHEMA:
        raise ValueError("unsupported parent birth-year evidence schema")
    if artifact.get("review_status") != "approved":
        raise ValueError("parent birth-year evidence is not approved")
    for key in ("reviewed_by", "review_reference"):
        _required_string(
            artifact,
            key,
            context="parent birth-year evidence",
        )
    _validated_review_recorded_at(artifact.get("review_recorded_at"))
    rows = artifact.get("rows")
    if (
        not isinstance(rows, list)
        or artifact.get("row_count") != len(rows)
    ):
        raise ValueError("parent birth-year evidence row_count is invalid")

    rows_by_legacy_source: dict[tuple[str, str], dict[str, Any]] = {}
    global_parent_identities: dict[
        tuple[str, str],
        tuple[Any, ...],
    ] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("parent birth-year evidence row must be an object")
        legacy_source_name = _required_string(
            row,
            "legacy_parent_source_name",
            context="parent birth-year evidence row",
        )
        legacy_external_id = _required_string(
            row,
            "legacy_parent_external_horse_id",
            context="parent birth-year evidence row",
        )
        legacy_key = _source_key(
            legacy_source_name,
            legacy_external_id,
            context="legacy parent",
        )
        legacy_source_url = _required_string(
            row,
            "legacy_parent_source_url",
            context="parent birth-year evidence row",
        )
        if (
            legacy_key[0] != normalized_name("netkeiba_en")
            or netkeiba_profile_external_id(legacy_source_url)
            != legacy_external_id
        ):
            raise ValueError(
                "parent birth-year evidence legacy source is not the exact "
                "Netkeiba profile identity"
            )

        parent_source_name = row.get(
            "parent_source_name",
            legacy_source_name,
        )
        parent_external_id = row.get(
            "parent_external_horse_id",
            legacy_external_id,
        )
        parent_key = _source_key(
            parent_source_name,
            parent_external_id,
            context="reviewed parent",
        )
        parent_source_url = _validated_url(
            row.get("parent_source_url", legacy_source_url),
            context="parent source URL",
        )
        if (
            parent_key[0] == normalized_name("netkeiba_en")
            and netkeiba_profile_external_id(parent_source_url)
            != parent_external_id
        ):
            raise ValueError(
                "reviewed Netkeiba parent source URL and external ID differ"
            )

        parent_name = _required_string(
            row,
            "parent_name",
            context="parent birth-year evidence row",
        )
        parent_sire_name = _optional_string(
            row,
            "parent_sire_name",
            context="parent birth-year evidence row",
        )
        parent_dam_name = _optional_string(
            row,
            "parent_dam_name",
            context="parent birth-year evidence row",
        )
        if bool(parent_sire_name) != bool(parent_dam_name):
            raise ValueError(
                "parent birth-year evidence must provide both parent "
                "sire and dam names or neither"
            )
        parent_birth_year = _validated_parent_birth_year(
            row.get("parent_birth_year")
        )
        evidence_source_name = _required_string(
            row,
            "birth_year_evidence_source_name",
            context="parent birth-year evidence row",
        )
        evidence_source_url = _validated_url(
            _required_string(
                row,
                "birth_year_evidence_source_url",
                context="parent birth-year evidence row",
            ),
            context="parent birth-year evidence source URL",
        )
        verification_method = _required_string(
            row,
            "birth_year_verification_method",
            context="parent birth-year evidence row",
        )
        evidence_note = _required_string(
            row,
            "birth_year_evidence_note",
            context="parent birth-year evidence row",
        )
        correction_reason = _optional_string(
            row,
            "correction_reason",
            context="parent birth-year evidence row",
        )
        source_identity_changed = (
            parent_key != legacy_key
            or parent_source_url != legacy_source_url
        )
        if source_identity_changed and not correction_reason:
            raise ValueError(
                "parent source identity correction requires correction_reason"
            )
        if correction_reason and not parent_sire_name:
            raise ValueError(
                "corrected parent identity requires full sire and dam names"
            )

        legacy_parent_birth_year = row.get("legacy_parent_birth_year")
        if legacy_parent_birth_year is not None:
            legacy_parent_birth_year = _validated_parent_birth_year(
                legacy_parent_birth_year
            )
        validated_row = {
            "legacy_parent_source_name": legacy_source_name,
            "legacy_parent_source_name_normalized": legacy_key[0],
            "legacy_parent_external_horse_id": legacy_external_id,
            "legacy_parent_source_url": legacy_source_url,
            "legacy_parent_birth_year": legacy_parent_birth_year,
            "parent_source_name": parent_source_name,
            "parent_source_name_normalized": parent_key[0],
            "parent_external_horse_id": parent_external_id,
            "parent_source_url": parent_source_url,
            "parent_name": parent_name,
            "parent_sire_name": parent_sire_name,
            "parent_dam_name": parent_dam_name,
            "parent_birth_year": parent_birth_year,
            "birth_year_evidence_source_name": evidence_source_name,
            "birth_year_evidence_source_name_normalized": normalized_name(
                evidence_source_name
            ),
            "birth_year_evidence_source_url": evidence_source_url,
            "birth_year_verification_method": verification_method,
            "birth_year_evidence_note": evidence_note,
            "correction_reason": correction_reason,
        }
        if legacy_key in rows_by_legacy_source:
            raise ValueError(
                "parent birth-year evidence contains duplicate legacy identities"
            )
        rows_by_legacy_source[legacy_key] = validated_row

        if parent_sire_name:
            full_identity = (
                parent_name,
                parent_source_url,
                parent_sire_name,
                parent_dam_name,
                parent_birth_year,
            )
            existing_identity = global_parent_identities.setdefault(
                parent_key,
                full_identity,
            )
            if existing_identity != full_identity:
                raise ValueError(
                    "parent birth-year evidence has globally inconsistent "
                    "parent identities"
                )
    return artifact, rows_by_legacy_source


def _reviewed_rows(
    data: dict[str, Any],
    parent_birth_year_evidence_bytes: bytes,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    legacy_rows = _legacy_review_rows(data)
    artifact, evidence_by_legacy_source = _parent_birth_year_evidence(
        parent_birth_year_evidence_bytes
    )
    legacy_source_keys = {
        _source_key(
            row["legacy_parent_source_name"],
            row["legacy_parent_external_horse_id"],
            context="legacy parent",
        )
        for row in legacy_rows
    }
    if legacy_source_keys != set(evidence_by_legacy_source):
        raise ValueError(
            "parent birth-year evidence must exactly cover actual legacy "
            "parent identities"
        )

    legacy_identities: dict[tuple[str, str], dict[str, str]] = {}
    for legacy_row in legacy_rows:
        legacy_key = _source_key(
            legacy_row["legacy_parent_source_name"],
            legacy_row["legacy_parent_external_horse_id"],
            context="legacy parent",
        )
        legacy_identity = legacy_identities.setdefault(
            legacy_key,
            {
                "parent_name": legacy_row["parent_name"],
                "parent_source_url": legacy_row[
                    "legacy_parent_source_url"
                ],
            },
        )
        if (
            legacy_identity["parent_name"] != legacy_row["parent_name"]
            or legacy_identity["parent_source_url"]
            != legacy_row["legacy_parent_source_url"]
        ):
            raise ValueError(
                "parent identity is globally inconsistent across target horses"
            )
        identity_field = (
            "parent_sire_name"
            if legacy_row["field_name"].endswith("_sire")
            else "parent_dam_name"
        )
        existing_value = legacy_identity.setdefault(
            identity_field,
            legacy_row["value"],
        )
        if existing_value != legacy_row["value"]:
            raise ValueError(
                "parent identity is globally inconsistent across target horses"
            )
    if any(
        not identity.get("parent_sire_name")
        or not identity.get("parent_dam_name")
        for identity in legacy_identities.values()
    ):
        raise ValueError(
            "legacy parent identity requires both sire and dam fields"
        )

    reviewed_rows: list[dict[str, Any]] = []
    global_parent_identities: dict[
        tuple[str, str],
        tuple[Any, ...],
    ] = {}
    for legacy_row in legacy_rows:
        legacy_key = _source_key(
            legacy_row["legacy_parent_source_name"],
            legacy_row["legacy_parent_external_horse_id"],
            context="legacy parent",
        )
        reviewed_parent = evidence_by_legacy_source[legacy_key]
        legacy_identity = legacy_identities[legacy_key]
        reviewed_parent = reviewed_parent | {
            "parent_sire_name": (
                reviewed_parent["parent_sire_name"]
                or legacy_identity["parent_sire_name"]
            ),
            "parent_dam_name": (
                reviewed_parent["parent_dam_name"]
                or legacy_identity["parent_dam_name"]
            ),
        }
        if (
            reviewed_parent["legacy_parent_source_url"]
            != legacy_row["legacy_parent_source_url"]
            or reviewed_parent["parent_name"]
            != legacy_row["parent_name"]
        ):
            raise ValueError(
                "parent identity is globally inconsistent across target horses"
            )
        reviewed_value = reviewed_parent[
            "parent_sire_name"
            if legacy_row["field_name"].endswith("_sire")
            else "parent_dam_name"
        ]
        correction_reason = reviewed_parent["correction_reason"]
        source_identity_changed = (
            reviewed_parent["parent_source_name_normalized"]
            != legacy_key[0]
            or reviewed_parent["parent_external_horse_id"]
            != legacy_key[1]
            or reviewed_parent["parent_source_url"]
            != legacy_row["legacy_parent_source_url"]
        )
        field_identity_changed = reviewed_value != legacy_row["value"]
        if (source_identity_changed or field_identity_changed) and not correction_reason:
            raise ValueError(
                "reviewed parent identity differs from legacy evidence "
                "without correction_reason"
            )
        if correction_reason and not (
            source_identity_changed or field_identity_changed
        ):
            raise ValueError(
                "parent identity correction_reason is present without a correction"
            )
        parent_birth_year = _validated_parent_birth_year(
            reviewed_parent["parent_birth_year"],
            target_birth_year=legacy_row["target_birth_year"],
        )
        parent_key = (
            reviewed_parent["parent_source_name_normalized"],
            reviewed_parent["parent_external_horse_id"],
        )
        full_identity = (
            reviewed_parent["parent_name"],
            reviewed_parent["parent_source_url"],
            reviewed_parent["parent_sire_name"],
            reviewed_parent["parent_dam_name"],
            parent_birth_year,
        )
        existing_identity = global_parent_identities.setdefault(
            parent_key,
            full_identity,
        )
        if existing_identity != full_identity:
            raise ValueError(
                "parent identity is globally inconsistent across target horses"
            )
        reviewed_rows.append(
            legacy_row
            | {
                "parent_source_name": reviewed_parent["parent_source_name"],
                "parent_source_name_normalized": reviewed_parent[
                    "parent_source_name_normalized"
                ],
                "parent_external_horse_id": reviewed_parent[
                    "parent_external_horse_id"
                ],
                "parent_source_url": reviewed_parent["parent_source_url"],
                "parent_sire_name": reviewed_parent["parent_sire_name"],
                "parent_dam_name": reviewed_parent["parent_dam_name"],
                "parent_birth_year": parent_birth_year,
                "parent_birth_year_evidence_source_name": reviewed_parent[
                    "birth_year_evidence_source_name"
                ],
                "parent_birth_year_evidence_source_name_normalized": (
                    reviewed_parent[
                        "birth_year_evidence_source_name_normalized"
                    ]
                ),
                "parent_birth_year_evidence_source_url": reviewed_parent[
                    "birth_year_evidence_source_url"
                ],
                "parent_birth_year_verification_method": reviewed_parent[
                    "birth_year_verification_method"
                ],
                "parent_birth_year_evidence_note": reviewed_parent[
                    "birth_year_evidence_note"
                ],
                "legacy_parent_birth_year": reviewed_parent[
                    "legacy_parent_birth_year"
                ],
                "reviewed_value": reviewed_value,
                "correction_reason": correction_reason,
            }
        )
    return reviewed_rows, artifact


def prepare_manifest(
    input_bytes: bytes,
    parent_birth_year_evidence_bytes: bytes,
    *,
    reviewed_by: str,
    review_reference: str,
    review_recorded_at: str,
) -> dict[str, Any]:
    reviewer = str(reviewed_by or "").strip()
    reference = str(review_reference or "").strip()
    if not reviewer or not reference:
        raise ValueError("reviewed_by and review_reference are required")
    recorded_at = _validated_review_recorded_at(review_recorded_at)
    data = json.loads(input_bytes.decode("utf-8"))
    rows, birth_year_artifact = _reviewed_rows(
        data,
        parent_birth_year_evidence_bytes,
    )
    if not rows:
        raise ValueError("input has no legacy parent identity evidence to review")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "review_status": "approved",
        "reviewed_by": reviewer,
        "review_reference": reference,
        "review_recorded_at": recorded_at,
        "approved_input_sha256": _sha256_bytes(input_bytes),
        "approved_parent_birth_year_evidence_sha256": _sha256_bytes(
            parent_birth_year_evidence_bytes
        ),
        "parent_birth_year_evidence": {
            "schema_version": birth_year_artifact["schema_version"],
            "review_status": birth_year_artifact["review_status"],
            "reviewed_by": birth_year_artifact["reviewed_by"],
            "review_reference": birth_year_artifact["review_reference"],
            "review_recorded_at": birth_year_artifact["review_recorded_at"],
            "row_count": birth_year_artifact["row_count"],
        },
        "row_count": len(rows),
        "rows": rows,
    }


def apply_manifest(
    input_bytes: bytes,
    manifest_bytes: bytes,
    parent_birth_year_evidence_bytes: bytes,
) -> bytes:
    data = json.loads(input_bytes.decode("utf-8"))
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("unsupported parent identity review manifest schema")
    if manifest.get("review_status") != "approved":
        raise ValueError("parent identity review manifest is not approved")
    for key in ("reviewed_by", "review_reference"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"parent identity review requires {key}")
    _validated_review_recorded_at(manifest.get("review_recorded_at"))
    if manifest.get("approved_input_sha256") != _sha256_bytes(input_bytes):
        raise ValueError("parent identity review input SHA-256 does not match")
    if manifest.get(
        "approved_parent_birth_year_evidence_sha256"
    ) != _sha256_bytes(parent_birth_year_evidence_bytes):
        raise ValueError(
            "parent birth-year evidence SHA-256 does not match"
        )

    actual_rows, birth_year_artifact = _reviewed_rows(
        data,
        parent_birth_year_evidence_bytes,
    )
    reviewed_rows = manifest.get("rows")
    if (
        not isinstance(reviewed_rows, list)
        or manifest.get("row_count") != len(reviewed_rows)
        or reviewed_rows != actual_rows
    ):
        raise ValueError(
            "parent identity review rows do not exactly match legacy evidence "
            "and parent birth-year evidence"
        )

    rows_by_key = {
        (
            row["target_source_name"],
            row["target_external_horse_id"],
            row["field_name"],
        ): row
        for row in reviewed_rows
    }
    if len(rows_by_key) != len(reviewed_rows):
        raise ValueError("parent identity review contains duplicate target fields")
    rows_by_target_parent: dict[
        tuple[str, str, str],
        dict[str, Any],
    ] = {}
    global_parent_identities: dict[
        tuple[str, str],
        tuple[Any, ...],
    ] = {}
    role_fields = {
        "sire": ("sire_sire", "sire_dam"),
        "dam": ("dam_sire", "dam_dam"),
    }
    for row in reviewed_rows:
        target_parent_key = (
            row["target_source_name"],
            row["target_external_horse_id"],
            row["parent_role"],
        )
        parent_identity = rows_by_target_parent.setdefault(
            target_parent_key,
            {
                "horse_name": row["parent_name"],
                "source_name": row["parent_source_name"],
                "source_name_normalized": row[
                    "parent_source_name_normalized"
                ],
                "source_url": row["parent_source_url"],
                "source_external_horse_id": row[
                    "parent_external_horse_id"
                ],
                "sire_name": row["parent_sire_name"],
                "dam_name": row["parent_dam_name"],
                "birth_year": row["parent_birth_year"],
                "legacy_source_name": row["legacy_parent_source_name"],
                "legacy_source_url": row["legacy_parent_source_url"],
                "legacy_source_external_horse_id": row[
                    "legacy_parent_external_horse_id"
                ],
                "legacy_birth_year": row["legacy_parent_birth_year"],
                "correction_reason": row["correction_reason"],
                "fields": {},
            },
        )
        if any(
            (
                parent_identity["horse_name"] != row["parent_name"],
                parent_identity["source_name"] != row["parent_source_name"],
                parent_identity["source_url"] != row["parent_source_url"],
                parent_identity["source_external_horse_id"]
                != row["parent_external_horse_id"],
                parent_identity["sire_name"] != row["parent_sire_name"],
                parent_identity["dam_name"] != row["parent_dam_name"],
                parent_identity["birth_year"] != row["parent_birth_year"],
                parent_identity["correction_reason"]
                != row["correction_reason"],
            )
        ):
            raise ValueError("parent identity review has conflicting parent rows")
        parent_identity["fields"][row["field_name"]] = {
            "legacy_value": row["value"],
            "reviewed_value": row["reviewed_value"],
        }
        global_key = (
            row["parent_source_name_normalized"],
            row["parent_external_horse_id"],
        )
        full_identity = (
            row["parent_name"],
            row["parent_source_url"],
            row["parent_sire_name"],
            row["parent_dam_name"],
            row["parent_birth_year"],
        )
        existing_identity = global_parent_identities.setdefault(
            global_key,
            full_identity,
        )
        if existing_identity != full_identity:
            raise ValueError(
                "parent identity review has globally inconsistent "
                "parent identities"
            )
    for target_parent_key, parent_identity in rows_by_target_parent.items():
        required_fields = set(role_fields[target_parent_key[2]])
        if set(parent_identity["fields"]) != required_fields:
            raise ValueError(
                "parent identity review requires both fields for each parent"
            )

    applied_count = 0
    for horse in data.get("horses") or []:
        target_source_name, target_external_id = _target_source_identity(horse)
        for evidence in horse.get("pedigree_field_evidence") or []:
            if (
                not isinstance(evidence, dict)
                or evidence.get("verification_method") not in LEGACY_METHODS
            ):
                continue
            field_name = str(evidence.get("field_name") or "").strip()
            row = rows_by_key.get(
                (target_source_name, target_external_id, field_name)
            )
            if row is None:
                raise ValueError("approved parent identity row is missing")
            parent_identity = rows_by_target_parent[
                (target_source_name, target_external_id, row["parent_role"])
            ]
            correction_reason = row["correction_reason"]
            if correction_reason:
                evidence["legacy_value"] = evidence.get("value")
                evidence["legacy_source_name"] = evidence.get("source_name")
                evidence["legacy_source_url"] = evidence.get("source_url")
                evidence["legacy_source_external_horse_id"] = row[
                    "legacy_parent_external_horse_id"
                ]
                evidence["legacy_verification_method"] = evidence.get(
                    "verification_method"
                )
                evidence["identity_correction"] = {
                    "status": "approved",
                    "reason": correction_reason,
                    "legacy_source_identity": {
                        "provider": parent_identity["legacy_source_name"],
                        "external_horse_id": parent_identity[
                            "legacy_source_external_horse_id"
                        ],
                        "source_url": parent_identity["legacy_source_url"],
                        "horse_name": parent_identity["horse_name"],
                        "sire_name": parent_identity["fields"][
                            role_fields[row["parent_role"]][0]
                        ]["legacy_value"],
                        "dam_name": parent_identity["fields"][
                            role_fields[row["parent_role"]][1]
                        ]["legacy_value"],
                        "birth_year": parent_identity["legacy_birth_year"],
                    },
                    "reviewed_source_identity": {
                        "provider": parent_identity["source_name"],
                        "external_horse_id": parent_identity[
                            "source_external_horse_id"
                        ],
                        "source_url": parent_identity["source_url"],
                        "horse_name": parent_identity["horse_name"],
                        "sire_name": parent_identity["sire_name"],
                        "dam_name": parent_identity["dam_name"],
                        "birth_year": parent_identity["birth_year"],
                    },
                }
            horse["pedigree"][field_name] = row["reviewed_value"]
            evidence["value"] = row["reviewed_value"]
            evidence["status"] = "verified_secondary_reviewed_source"
            evidence["verification_method"] = REVIEWED_METHOD
            evidence["source_name"] = row["parent_source_name"]
            evidence["source_url"] = row["parent_source_url"]
            evidence["source_external_horse_id"] = row[
                "parent_external_horse_id"
            ]
            evidence["source_identity"] = {
                "horse_name": parent_identity["horse_name"],
                "sire_name": parent_identity["sire_name"],
                "dam_name": parent_identity["dam_name"],
                "birth_year": parent_identity["birth_year"],
            }
            evidence["identity_review"] = {
                "status": manifest["review_status"],
                "reviewed_by": manifest["reviewed_by"],
                "review_reference": manifest["review_reference"],
                "review_recorded_at": manifest["review_recorded_at"],
                "approved_input_sha256": manifest["approved_input_sha256"],
                "approved_parent_birth_year_evidence_sha256": manifest[
                    "approved_parent_birth_year_evidence_sha256"
                ],
                "parent_birth_year_evidence": {
                    "source_name": row[
                        "parent_birth_year_evidence_source_name"
                    ],
                    "source_url": row[
                        "parent_birth_year_evidence_source_url"
                    ],
                    "verification_method": row[
                        "parent_birth_year_verification_method"
                    ],
                    "evidence_note": row[
                        "parent_birth_year_evidence_note"
                    ],
                },
            }
            applied_count += 1

    if applied_count != manifest["row_count"]:
        raise ValueError("not every approved parent identity row was applied")
    data["parent_identity_review_application"] = {
        "schema_version": APPLICATION_SCHEMA,
        "input_sha256": manifest["approved_input_sha256"],
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "parent_birth_year_evidence_sha256": manifest[
            "approved_parent_birth_year_evidence_sha256"
        ],
        "parent_birth_year_evidence_review": {
            "schema_version": birth_year_artifact["schema_version"],
            "review_status": birth_year_artifact["review_status"],
            "reviewed_by": birth_year_artifact["reviewed_by"],
            "review_reference": birth_year_artifact["review_reference"],
            "review_recorded_at": birth_year_artifact["review_recorded_at"],
            "row_count": birth_year_artifact["row_count"],
        },
        "row_count": applied_count,
        "parent_identity_count": len(global_parent_identities),
        "corrected_parent_identity_count": len(
            {
                (
                    row["legacy_parent_source_name"],
                    row["legacy_parent_external_horse_id"],
                )
                for row in reviewed_rows
                if row["correction_reason"]
            }
        ),
        "filled_field_review_count": sum(
            not (
                row["field_name"] == "dam_sire"
                and row["legacy_verification_method"]
                == "exact_parent_name_and_known_sire_match"
            )
            for row in reviewed_rows
        ),
        "reviewed_by": manifest["reviewed_by"],
        "review_reference": manifest["review_reference"],
        "review_recorded_at": manifest["review_recorded_at"],
        "legacy_verification_methods": sorted(LEGACY_METHODS),
        "replacement_verification_method": REVIEWED_METHOD,
    }
    return _json_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    prepare.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    prepare.add_argument(
        "--parent-birth-year-evidence",
        type=Path,
        default=DEFAULT_PARENT_BIRTH_YEAR_EVIDENCE,
    )
    prepare.add_argument("--reviewed-by", required=True)
    prepare.add_argument("--review-reference", required=True)
    prepare.add_argument("--review-recorded-at", required=True)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    apply.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    apply.add_argument(
        "--parent-birth-year-evidence",
        type=Path,
        default=DEFAULT_PARENT_BIRTH_YEAR_EVIDENCE,
    )
    apply.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    args = parser.parse_args()
    if args.operation == "prepare":
        input_bytes = args.input.read_bytes()
        manifest = prepare_manifest(
            input_bytes,
            args.parent_birth_year_evidence.read_bytes(),
            reviewed_by=args.reviewed_by,
            review_reference=args.review_reference,
            review_recorded_at=args.review_recorded_at,
        )
        _atomic_write(args.manifest, _json_bytes(manifest))
        print(args.manifest)
        return 0

    output_bytes = apply_manifest(
        args.input.read_bytes(),
        args.manifest.read_bytes(),
        args.parent_birth_year_evidence.read_bytes(),
    )
    _atomic_write(args.output, output_bytes)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
