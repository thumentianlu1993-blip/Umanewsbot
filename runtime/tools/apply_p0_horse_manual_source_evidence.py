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

from runtime.tools.collect_p0_horse_research_50 import (
    BASIC_PROFILE_EVIDENCE,
    CAREER_RECORD_EVIDENCE,
    CAREER_RESULT_EVIDENCE,
    US_EQUIBASE_PROFILE_EVIDENCE,
    apply_basic_profile_verifications,
    apply_career_record_verifications,
    apply_career_result_verifications,
    apply_us_equibase_profile_verifications,
    finalize_career_collection_status,
    _manual_evidence_horse_index,
    _manual_evidence_verification_key,
    parse_basic_profile_verifications,
    parse_career_record_verifications,
    parse_career_result_verifications,
    parse_us_equibase_profile_verifications,
    refresh_research_career_counts,
    summarize_field_status,
)

TOOL_VERSION = "p0-horse-manual-source-evidence.v5"
DEFAULT_GAP_SNAPSHOT = (
    ROOT
    / "runtime/horse_profile_completion/"
    "manual-source-evidence-20260719/"
    "basic_profile_gap_snapshot.json"
)
TRUSTED_GAP_SNAPSHOT_SHA256_BY_BATCH = {
    "basic-profile-source-research-20260719": (
        "e5fb77a2ebee0b74edc826c2971ea6cd"
        "afae387b11a713e4eb86d9defc7f6180"
    ),
}


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _basic_profile_gap_snapshot(
    data: dict[str, Any],
    verifications: list[dict[str, Any]],
    *,
    input_path: Path,
    input_sha256: str,
) -> dict[str, Any]:
    horses = _manual_evidence_horse_index(data)
    rows = []
    for verification in verifications:
        horse = horses.get(_manual_evidence_verification_key(verification))
        current_value = (
            (horse.get("basic_profile") or {}).get(
                verification["field_name"]
            )
            if horse
            else None
        )
        rows.append(
            {
                "region": verification["region"],
                "horse_name": verification["horse_name"],
                "external_horse_id": verification[
                    "expected_external_horse_id"
                ],
                "field_name": verification["field_name"],
                "current_value": current_value,
                "proposed_value": verification["canonical_value"],
                "gap_status": (
                    "missing"
                    if current_value in ("", None)
                    else "already_populated"
                ),
                "source_name": verification["source_name"],
                "source_url": verification["source_url"],
            }
        )
    return {
        "schema_version": "p0-horse-basic-profile-gap-snapshot.v1",
        "input_path": str(input_path),
        "input_sha256": input_sha256,
        "evidence_batch_id": (
            verifications[0]["batch_id"] if verifications else ""
        ),
        "row_count": len(rows),
        "missing_count": sum(
            row["gap_status"] == "missing" for row in rows
        ),
        "rows": rows,
    }


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _business_payload_sha256(data: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "manual_evidence_application",
            "manual_evidence_application_history",
        }
    }
    return _sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_bytes(content)
    temporary_path.replace(path)


def _freeze_gap_snapshot(
    path: Path,
    snapshot: dict[str, Any],
    *,
    trusted_sha256: str,
) -> bytes:
    if path.exists():
        content = path.read_bytes()
        if _sha256_bytes(content) != trusted_sha256:
            raise ValueError(
                "existing basic profile gap snapshot does not match "
                "the trusted SHA-256"
            )
        existing = json.loads(content.decode("utf-8"))
        if (
            existing.get("schema_version")
            != snapshot["schema_version"]
            or existing.get("evidence_batch_id")
            != snapshot["evidence_batch_id"]
            or existing.get("row_count") != snapshot["row_count"]
        ):
            raise ValueError(
                "existing basic profile gap snapshot does not match "
                "the current evidence batch"
            )
        return content
    content = _json_bytes(snapshot)
    if _sha256_bytes(content) != trusted_sha256:
        raise ValueError(
            "new basic profile gap snapshot does not match the trusted "
            "SHA-256"
        )
    _atomic_write(path, content)
    return content


def _gap_snapshot_binding(
    *,
    path: Path | None,
    content: bytes,
    snapshot: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    binding = {
        "path": str(path) if path is not None else "",
        "sha256": _sha256_bytes(content),
        "row_count": snapshot["row_count"],
        "missing_count": snapshot["missing_count"],
        "role": role,
    }
    if snapshot.get("input_sha256"):
        binding["input_sha256"] = snapshot["input_sha256"]
    if snapshot.get("business_payload_sha256"):
        binding["business_payload_sha256"] = snapshot[
            "business_payload_sha256"
        ]
        binding["hash_scope"] = snapshot["hash_scope"]
    return binding


def apply_evidence(
    *,
    input_path: Path,
    output_path: Path,
    equibase_evidence_path: Path,
    career_result_evidence_path: Path,
    basic_profile_evidence_path: Path = BASIC_PROFILE_EVIDENCE,
    career_record_evidence_path: Path = CAREER_RECORD_EVIDENCE,
    gap_snapshot_path: Path | None = None,
    post_gap_snapshot_path: Path | None = None,
    applied_at: str | None = None,
) -> dict[str, Any]:
    input_bytes = input_path.read_bytes()
    equibase_evidence_bytes = equibase_evidence_path.read_bytes()
    career_result_evidence_bytes = career_result_evidence_path.read_bytes()
    basic_profile_evidence_bytes = basic_profile_evidence_path.read_bytes()
    career_record_evidence_bytes = career_record_evidence_path.read_bytes()
    data = json.loads(input_bytes.decode("utf-8"))
    basic_profile_verifications = parse_basic_profile_verifications(
        basic_profile_evidence_bytes
    )
    current_input_gap_snapshot = _basic_profile_gap_snapshot(
        data,
        basic_profile_verifications,
        input_path=input_path,
        input_sha256=_sha256_bytes(input_bytes),
    )
    current_input_gap_snapshot_bytes = _json_bytes(
        current_input_gap_snapshot
    )
    if gap_snapshot_path is not None:
        trusted_gap_snapshot_sha256 = (
            TRUSTED_GAP_SNAPSHOT_SHA256_BY_BATCH.get(
                basic_profile_verifications[0]["batch_id"]
                if basic_profile_verifications
                else ""
            )
        )
        if not trusted_gap_snapshot_sha256:
            raise ValueError(
                "no trusted SHA-256 registered for the basic profile "
                "gap snapshot batch"
            )
        historical_pre_gap_snapshot_bytes = _freeze_gap_snapshot(
            gap_snapshot_path,
            current_input_gap_snapshot,
            trusted_sha256=trusted_gap_snapshot_sha256,
        )
        historical_pre_gap_snapshot = json.loads(
            historical_pre_gap_snapshot_bytes.decode("utf-8")
        )
    else:
        historical_pre_gap_snapshot_bytes = (
            current_input_gap_snapshot_bytes
        )
        historical_pre_gap_snapshot = current_input_gap_snapshot
    basic_profile_applied_count = apply_basic_profile_verifications(
        data,
        basic_profile_verifications,
    )
    equibase_verifications = parse_us_equibase_profile_verifications(
        equibase_evidence_bytes
    )
    equibase_applied_count = apply_us_equibase_profile_verifications(
        data,
        equibase_verifications,
    )
    career_result_verifications = parse_career_result_verifications(
        career_result_evidence_bytes
    )
    career_result_applied_count = apply_career_result_verifications(
        data,
        career_result_verifications,
    )
    career_record_verifications = parse_career_record_verifications(
        career_record_evidence_bytes
    )
    career_record_applied_count = apply_career_record_verifications(
        data,
        career_record_verifications,
    )
    for horse in data.get("horses") or []:
        refresh_research_career_counts(horse)
        horse["field_status"] = summarize_field_status(horse)
        finalize_career_collection_status(horse, horse["field_status"])
    post_application_gap_snapshot = _basic_profile_gap_snapshot(
        data,
        basic_profile_verifications,
        input_path=output_path,
        input_sha256="",
    )
    post_application_gap_snapshot["business_payload_sha256"] = (
        _business_payload_sha256(data)
    )
    post_application_gap_snapshot["hash_scope"] = (
        "canonical_business_payload_without_manual_application_metadata"
    )
    post_application_gap_snapshot_bytes = _json_bytes(
        post_application_gap_snapshot
    )
    if post_gap_snapshot_path is None and gap_snapshot_path is not None:
        post_gap_snapshot_path = gap_snapshot_path.with_name(
            f"{gap_snapshot_path.stem}_after_application"
            f"{gap_snapshot_path.suffix}"
        )
    if post_gap_snapshot_path is not None:
        _atomic_write(
            post_gap_snapshot_path,
            post_application_gap_snapshot_bytes,
        )
    applied_at = applied_at or datetime.now(timezone.utc).isoformat()
    application_inputs = {
        "input": {
            "path": str(input_path),
            "sha256": _sha256_bytes(input_bytes),
        },
        "basic_profile_evidence": {
            "path": str(basic_profile_evidence_path),
            "sha256": _sha256_bytes(basic_profile_evidence_bytes),
            "row_count": len(basic_profile_verifications),
        },
        "equibase_profile_evidence": {
            "path": str(equibase_evidence_path),
            "sha256": _sha256_bytes(equibase_evidence_bytes),
            "row_count": len(equibase_verifications),
        },
        "career_result_evidence": {
            "path": str(career_result_evidence_path),
            "sha256": _sha256_bytes(career_result_evidence_bytes),
            "row_count": len(career_result_verifications),
        },
        "career_record_evidence": {
            "path": str(career_record_evidence_path),
            "sha256": _sha256_bytes(career_record_evidence_bytes),
            "row_count": len(career_record_verifications),
        },
        "basic_profile_pre_application_gap_snapshot": (
            _gap_snapshot_binding(
                path=gap_snapshot_path,
                content=historical_pre_gap_snapshot_bytes,
                snapshot=historical_pre_gap_snapshot,
                role="baseline_before_first_application",
            )
        ),
        "basic_profile_current_input_gap_snapshot": (
            _gap_snapshot_binding(
                path=None,
                content=current_input_gap_snapshot_bytes,
                snapshot=current_input_gap_snapshot,
                role="current_parent_input_before_this_application",
            )
        ),
        "basic_profile_post_application_gap_snapshot": (
            _gap_snapshot_binding(
                path=post_gap_snapshot_path,
                content=post_application_gap_snapshot_bytes,
                snapshot=post_application_gap_snapshot,
                role="current_output_after_this_application",
            )
        ),
    }
    previous_application = data.get("manual_evidence_application")
    previous_application_id = (
        previous_application.get("application_id")
        if isinstance(previous_application, dict)
        else ""
    )
    application_id = _sha256_bytes(
        json.dumps(
            {
                "tool_version": TOOL_VERSION,
                "applied_at": applied_at,
                "parent_input_sha256": _sha256_bytes(input_bytes),
                "parent_application_id": previous_application_id,
                "inputs": application_inputs,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    application_history = list(
        data.get("manual_evidence_application_history") or []
    )
    if (
        isinstance(previous_application, dict)
        and previous_application.get("application_id")
        and not any(
            item.get("application_id")
            == previous_application.get("application_id")
            for item in application_history
            if isinstance(item, dict)
        )
    ):
        application_history.append(previous_application)
    data["manual_evidence_application_history"] = application_history
    data["manual_evidence_application"] = {
        "schema_version": "p0-horse-manual-evidence-application.v3",
        "tool_version": TOOL_VERSION,
        "application_id": application_id,
        "applied_at": applied_at,
        "parent_input_sha256": _sha256_bytes(input_bytes),
        "parent_application_id": previous_application_id,
        "inputs": application_inputs,
        "basic_profile_verified_target_count": len(
            basic_profile_verifications
        ),
        "basic_profile_verification_count": len(
            basic_profile_verifications
        ),
        "basic_profile_applied_count": basic_profile_applied_count,
        "equibase_profile_verified_target_count": len(
            equibase_verifications
        ),
        "equibase_profile_applied_count": equibase_applied_count,
        "equibase_profile_verification_count": len(
            equibase_verifications
        ),
        "career_result_verified_target_count": len(
            career_result_verifications
        ),
        "career_result_applied_count": career_result_applied_count,
        "career_result_verification_count": len(
            career_result_verifications
        ),
        "career_record_verified_target_count": len(
            career_record_verifications
        ),
        "career_record_verification_count": len(
            career_record_verifications
        ),
        "career_record_applied_count": career_record_applied_count,
    }
    _atomic_write(output_path, _json_bytes(data))
    return {
        "basic_profile_verification_count": len(
            basic_profile_verifications
        ),
        "basic_profile_applied_count": basic_profile_applied_count,
        "equibase_profile_verification_count": len(equibase_verifications),
        "equibase_profile_applied_count": equibase_applied_count,
        "career_result_verification_count": len(
            career_result_verifications
        ),
        "career_result_applied_count": career_result_applied_count,
        "career_record_verification_count": len(
            career_record_verifications
        ),
        "career_record_applied_count": career_record_applied_count,
        "horse_count": len(data.get("horses") or []),
        "manual_evidence_application_id": application_id,
        "manual_evidence_application_history_count": len(
            application_history
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--equibase-evidence",
        type=Path,
        default=US_EQUIBASE_PROFILE_EVIDENCE,
    )
    parser.add_argument(
        "--career-result-evidence",
        type=Path,
        default=CAREER_RESULT_EVIDENCE,
    )
    parser.add_argument(
        "--basic-profile-evidence",
        type=Path,
        default=BASIC_PROFILE_EVIDENCE,
    )
    parser.add_argument(
        "--career-record-evidence",
        type=Path,
        default=CAREER_RECORD_EVIDENCE,
    )
    parser.add_argument(
        "--gap-snapshot-output",
        type=Path,
        default=DEFAULT_GAP_SNAPSHOT,
    )
    parser.add_argument(
        "--post-gap-snapshot-output",
        type=Path,
    )
    args = parser.parse_args()
    summary = apply_evidence(
        input_path=args.input,
        output_path=args.output,
        equibase_evidence_path=args.equibase_evidence,
        career_result_evidence_path=args.career_result_evidence,
        basic_profile_evidence_path=args.basic_profile_evidence,
        career_record_evidence_path=args.career_record_evidence,
        gap_snapshot_path=args.gap_snapshot_output,
        post_gap_snapshot_path=args.post_gap_snapshot_output,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
