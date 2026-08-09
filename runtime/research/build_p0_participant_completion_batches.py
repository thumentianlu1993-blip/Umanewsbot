#!/usr/bin/env python3
"""把生产只读参赛马 census 编译为受审、可续跑的 P0 资料补全批次。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable


SOURCE_ARTIFACT_TYPE = "p0_horse_participant_candidates"
BATCH_CONTRACT_SCHEMA = "p0-horse-participant-review-batch.v2"
REVIEW_MANIFEST_TYPE = "p0_horse_candidate_review_manifest"
REVIEW_DECISION = "confirm_batch_inclusion"
ALLOWED_REGIONS = (
    "japan",
    "hong_kong",
    "united_kingdom",
    "france",
    "united_states",
)
ELIGIBLE_REVIEW_STATUSES = {
    "ready_for_profile_resolution",
    "needs_identity_enrichment",
}
JSON_LIST_FIELDS = (
    "aliases",
    "matched_profile_ids",
    "identity_keys",
    "source_namespaces",
    "source_urls",
    "event_regions",
)
CSV_FIELDS = (
    "sample_region",
    "sample_rank",
    "candidate_key",
    "horse_name",
    "aliases",
    "identity_status",
    "review_status",
    "mapping_disposition",
    "matched_profile_ids",
    "identity_keys",
    "source_namespace",
    "source_namespaces",
    "source_urls",
    "event_regions",
    "actual_start_evidence_count",
    "sire_name",
    "dam_name",
    "birth_year",
    "reviewed",
    "review_decision",
    "review_notes",
)


class ParticipantBatchBuildError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_regular_file(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ParticipantBatchBuildError(f"{label} is unreadable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ParticipantBatchBuildError(f"{label} must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
            ):
                raise ParticipantBatchBuildError(
                    f"{label} changed before it could be read"
                )
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(descriptor)
    except ParticipantBatchBuildError:
        raise
    except OSError as exc:
        raise ParticipantBatchBuildError(f"{label} is unreadable") from exc
    return b"".join(chunks)


def _load_source(
    path: Path,
    manifest_path: Path,
) -> tuple[bytes, dict[str, Any], bytes]:
    data = _read_regular_file(path, label="source candidate artifact")
    manifest_bytes = _read_regular_file(
        manifest_path,
        label="source candidate manifest",
    )
    try:
        payload = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ParticipantBatchBuildError(
            "source candidate artifact is invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ParticipantBatchBuildError("source candidate artifact must be an object")
    if payload.get("artifact_type") != SOURCE_ARTIFACT_TYPE:
        raise ParticipantBatchBuildError("source candidate artifact type is invalid")
    if payload.get("read_only") is not True:
        raise ParticipantBatchBuildError("source candidate artifact must be read-only")
    if payload.get("actual_starts_only") is not True:
        raise ParticipantBatchBuildError(
            "source candidate artifact must set actual_starts_only=true"
        )
    year = payload.get("year")
    if isinstance(year, bool) or not isinstance(year, int):
        raise ParticipantBatchBuildError("source candidate artifact year is invalid")
    if not isinstance(payload.get("candidates"), list):
        raise ParticipantBatchBuildError("source candidate collection is invalid")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ParticipantBatchBuildError(
            "source candidate manifest is invalid JSON"
        ) from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("artifact_type") != "p0_horse_participant_candidate_manifest"
        or manifest.get("read_only") is not True
        or not isinstance(manifest.get("files"), dict)
    ):
        raise ParticipantBatchBuildError(
            "source candidate manifest identity is invalid"
        )
    candidate_entry = manifest["files"].get("candidates")
    if (
        not isinstance(candidate_entry, dict)
        or candidate_entry.get("path") != path.name
        or candidate_entry.get("size_bytes") != len(data)
        or candidate_entry.get("sha256") != _sha256(data)
    ):
        raise ParticipantBatchBuildError(
            "source candidate manifest does not bind the candidate artifact"
        )
    return data, payload, manifest_bytes


def _candidate_exclusion(candidate: Any, selected_regions: set[str]) -> str:
    if not isinstance(candidate, dict):
        return "candidate_not_object"
    key = str(candidate.get("candidate_key") or "").strip()
    if not key:
        return "candidate_key_missing"
    event_regions = candidate.get("event_regions")
    if not isinstance(event_regions, list):
        return "event_regions_invalid"
    in_scope = [region for region in event_regions if region in selected_regions]
    if len(in_scope) != 1 or len(event_regions) != 1:
        return "single_region_identity_required"
    if int(candidate.get("actual_start_evidence_count") or 0) <= 0:
        return "actual_start_evidence_missing"
    if candidate.get("review_status") not in ELIGIBLE_REVIEW_STATUSES:
        return "review_status_blocked"
    source_urls = candidate.get("source_urls")
    if not isinstance(source_urls, list) or not any(
        isinstance(value, str) and re.match(r"^https?://", value)
        for value in source_urls
    ):
        return "source_url_missing"
    for field in JSON_LIST_FIELDS:
        if not isinstance(candidate.get(field), list):
            return f"{field}_invalid"
    return ""


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field: (
                    json.dumps(row.get(field), ensure_ascii=False, sort_keys=True)
                    if field in JSON_LIST_FIELDS
                    else row.get(field, "")
                )
                for field in CSV_FIELDS
            }
        )
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _review_row(candidate: dict[str, Any], *, region: str, rank: int) -> dict[str, Any]:
    return {
        **{field: candidate.get(field, "") for field in CSV_FIELDS},
        "sample_region": region,
        "sample_rank": rank,
        "reviewed": True,
        "review_decision": REVIEW_DECISION,
        "review_notes": (
            "范围已批准；实际起跑证据已绑定。马匹身份、完整资料、模块审核与生产写入继续独立门禁。"
        ),
        "birth_year": candidate.get("birth_year") or "",
    }


def build_participant_completion_batches(
    *,
    source_artifact: str | Path,
    source_manifest: str | Path,
    output_dir: str | Path,
    regions: Iterable[str],
    max_rows_per_batch: int,
    decision_reference: str,
) -> dict[str, Any]:
    source_path = Path(source_artifact)
    output = Path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ParticipantBatchBuildError("output directory is not empty")
    selected = tuple(dict.fromkeys(str(region).strip() for region in regions))
    if not selected or any(region not in ALLOWED_REGIONS for region in selected):
        raise ParticipantBatchBuildError("regions must be a non-empty approved subset")
    if not 1 <= max_rows_per_batch <= 100:
        raise ParticipantBatchBuildError("max_rows_per_batch must be within 1..100")
    decision_text = str(decision_reference or "").strip()
    if not decision_text:
        raise ParticipantBatchBuildError("decision_reference is required")
    source_bytes, source, source_manifest_bytes = _load_source(
        source_path,
        Path(source_manifest),
    )
    source_sha = _sha256(source_bytes)
    source_manifest_sha = _sha256(source_manifest_bytes)
    selected_set = set(selected)
    seen: set[str] = set()
    by_region: dict[str, list[dict[str, Any]]] = {region: [] for region in selected}
    exclusions: list[dict[str, Any]] = []
    for candidate in source["candidates"]:
        key = (
            str(candidate.get("candidate_key") or "").strip()
            if isinstance(candidate, dict)
            else ""
        )
        if key and key in seen:
            raise ParticipantBatchBuildError(f"duplicate candidate_key: {key}")
        if key:
            seen.add(key)
        reason = _candidate_exclusion(candidate, selected_set)
        if reason:
            exclusions.append({"candidate_key": key, "reason": reason})
            continue
        region = candidate["event_regions"][0]
        by_region[region].append(candidate)

    staging_parent = output.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=staging_parent)
    )
    published = False
    try:
        copied_source = staging / "source" / source_path.name
        _write(copied_source, source_bytes)
        copied_source_manifest = (
            staging / "source" / "p0_participant_candidate_manifest.json"
        )
        _write(copied_source_manifest, source_manifest_bytes)
        batch_specs: list[dict[str, Any]] = []
        batch_number = 0
        for region in ALLOWED_REGIONS:
            candidates = sorted(
                by_region.get(region, []),
                key=lambda row: str(row["candidate_key"]),
            )
            for start in range(0, len(candidates), max_rows_per_batch):
                batch_number += 1
                chunk = candidates[start : start + max_rows_per_batch]
                batch_name = f"batch-{batch_number:04d}-{region}-{start // max_rows_per_batch + 1:04d}"
                batch_dir = staging / batch_name
                rows = [
                    _review_row(candidate, region=region, rank=index)
                    for index, candidate in enumerate(chunk, start=1)
                ]
                csv_data = _csv_bytes(rows)
                batch_specs.append(
                    {
                        "path": batch_name,
                        "ordinal": batch_number,
                        "region": region,
                        "row_count": len(rows),
                        "candidate_keys": [row["candidate_key"] for row in rows],
                        "csv_data": csv_data,
                    }
                )
        batch_index = {
            "artifact_type": "p0_horse_participant_completion_batch_plan",
            "schema_version": BATCH_CONTRACT_SCHEMA,
            "generated_at": source.get("generated_at", ""),
            "year": source["year"],
            "decision_reference": decision_text,
            "source_candidate_artifact_sha256": source_sha,
            "source_candidate_manifest_sha256": source_manifest_sha,
            "candidate_count": sum(len(rows) for rows in by_region.values()),
            "batch_count": len(batch_specs),
            "batches": [
                {
                    "path": spec["path"],
                    "ordinal": spec["ordinal"],
                    "region": spec["region"],
                    "row_count": spec["row_count"],
                    "candidate_keys": spec["candidate_keys"],
                    "csv_sha256": _sha256(spec["csv_data"]),
                }
                for spec in batch_specs
            ],
        }
        batch_index_data = _canonical_bytes(batch_index)
        _write(staging / "batch_index.json", batch_index_data)
        batch_index_sha = _sha256(batch_index_data)
        batch_rows: list[dict[str, Any]] = []
        for spec in batch_specs:
            batch_name = spec["path"]
            region = spec["region"]
            rows = spec["candidate_keys"]
            csv_data = spec["csv_data"]
            batch_dir = staging / batch_name
            csv_path = batch_dir / "reviewed_candidates.csv"
            _write(csv_path, csv_data)
            manifest = {
                "artifact_type": REVIEW_MANIFEST_TYPE,
                "decision": REVIEW_DECISION,
                "decision_reference": decision_text,
                "generated_at": source.get("generated_at", ""),
                "row_count": spec["row_count"],
                "files": {
                    csv_path.name: {
                        "path": csv_path.name,
                        "size": len(csv_data),
                        "sha256": _sha256(csv_data),
                    }
                },
                "batch_contract": {
                    "schema_version": BATCH_CONTRACT_SCHEMA,
                    "year": source["year"],
                    "actual_starts_only": True,
                    "max_rows_per_region": max_rows_per_batch,
                    "region_counts": {region: len(rows)},
                    "batch_membership": {
                        "path": batch_name,
                        "ordinal": spec["ordinal"],
                        "batch_count": len(batch_specs),
                        "index_path": "../batch_index.json",
                        "index_size": len(batch_index_data),
                        "index_sha256": batch_index_sha,
                    },
                    "source_candidate_artifact": {
                        "path": f"../source/{source_path.name}",
                        "size": len(source_bytes),
                        "sha256": source_sha,
                    },
                    "source_candidate_manifest": {
                        "path": "../source/p0_participant_candidate_manifest.json",
                        "size": len(source_manifest_bytes),
                        "sha256": source_manifest_sha,
                    },
                },
            }
            manifest_data = _canonical_bytes(manifest)
            _write(batch_dir / "review_manifest.json", manifest_data)
            batch_rows.append(
                {
                    "path": batch_name,
                    "ordinal": spec["ordinal"],
                    "region": region,
                    "row_count": spec["row_count"],
                    "csv_sha256": _sha256(csv_data),
                    "review_manifest_sha256": _sha256(manifest_data),
                }
            )
        exclusion_data = b"".join(_canonical_bytes(row) for row in exclusions)
        _write(staging / "exclusions.jsonl", exclusion_data)
        summary = {
            "artifact_type": "p0_horse_participant_completion_batch_index",
            "schema_version": BATCH_CONTRACT_SCHEMA,
            "generated_at": source.get("generated_at", ""),
            "year": source["year"],
            "regions": [region for region in ALLOWED_REGIONS if region in selected_set],
            "decision_reference": decision_text,
            "source_candidate_artifact_sha256": source_sha,
            "source_candidate_manifest_sha256": source_manifest_sha,
            "batch_index_sha256": batch_index_sha,
            "candidate_count": sum(len(rows) for rows in by_region.values()),
            "excluded_count": len(exclusions),
            "batch_count": len(batch_rows),
            "batches": batch_rows,
        }
        _write(staging / "summary.json", _canonical_bytes(summary))
        if output.exists():
            output.rmdir()
        os.replace(staging, output)
        published = True
        return summary
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-artifact", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--region", action="append", required=True, choices=ALLOWED_REGIONS
    )
    parser.add_argument("--max-rows-per-batch", type=int, default=50)
    parser.add_argument("--decision-reference", required=True)
    args = parser.parse_args()
    try:
        summary = build_participant_completion_batches(
            source_artifact=args.source_artifact,
            source_manifest=args.source_manifest,
            output_dir=args.output_dir,
            regions=args.region,
            max_rows_per_batch=args.max_rows_per_batch,
            decision_reference=args.decision_reference,
        )
    except (OSError, ParticipantBatchBuildError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
