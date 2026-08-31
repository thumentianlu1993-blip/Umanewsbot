#!/usr/bin/env python3
"""Prepare exact-SHA, non-executable TRA bulk range batches from readiness evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping

from audit_racing_api_bulk_partition_readiness import (
    MAX_BULK_PAGES_PER_RANGE,
    PARTITION_SCHEMA_VERSION,
    SCHEMA_VERSION as READINESS_SCHEMA_VERSION,
    TARGET_CLASS_SCHEMA_VERSION,
    load_target_artifact,
)
from prepare_held_winner_seed_extension import (
    _atomic_write,
    _read_json,
    _read_jsonl,
    _regular,
    _require_sha,
    canonical_json,
    sha256_path,
)


SCHEMA_VERSION = "racing-api-bulk-range-batch-plan.v1"
BATCH_SCHEMA_VERSION = "racing-api-bulk-range-batch.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def _file_identity(path: Path, *, rows: int | None = None) -> dict:
    identity = {
        "path": path.name,
        "sha256": sha256_path(path),
        "size": path.stat().st_size,
    }
    if rows is not None:
        identity["rows"] = rows
    return identity


def _validate_output_identity(root: Path, name: str, expected: object) -> tuple[Path, list[dict]]:
    if not isinstance(expected, Mapping) or expected.get("path") != name:
        raise ValueError(f"readiness output identity is missing: {name}")
    path = _regular(root / name, label=f"readiness {name}")
    rows = _read_jsonl(path, label=f"readiness {name}")
    if (
        expected.get("sha256") != sha256_path(path)
        or expected.get("size") != path.stat().st_size
        or expected.get("rows") != len(rows)
    ):
        raise ValueError(f"readiness output identity drift: {name}")
    return path, rows


def load_readiness_artifact(
    root: Path,
    *,
    expected_report_sha256: str,
) -> tuple[list[dict], list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("readiness root must be a regular directory")
    report_path = _regular(resolved / "readiness-audit.json", label="readiness report")
    report = _read_json(report_path, label="readiness report")
    report_sha = sha256_path(report_path)
    _require_sha(report_sha, expected_report_sha256, label="readiness report")
    marker = _regular(resolved / "PREPARED", label="readiness PREPARED marker")
    outputs = report.get("outputs")
    counts = report.get("counts")
    target = report.get("target_artifact")
    if (
        report.get("schema_version") != READINESS_SCHEMA_VERSION
        or report.get("status") != "BLOCKED_ENTITLEMENT_PROOF_AND_EXECUTION_PLAN"
        or report.get("execution_ready") is not False
        or report.get("network_requests") != 0
        or report.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != report_sha
        or not isinstance(outputs, Mapping)
        or not isinstance(counts, Mapping)
        or not isinstance(target, Mapping)
    ):
        raise ValueError("readiness artifact contract drift")
    _, partitions = _validate_output_identity(
        resolved, "bulk-partitions.jsonl", outputs.get("bulk-partitions.jsonl")
    )
    _, bulk_targets = _validate_output_identity(
        resolved, "bulk-eligible-targets.jsonl", outputs.get("bulk-eligible-targets.jsonl")
    )
    if (
        counts.get("bulk_region_year_units") != len(partitions)
        or counts.get("bulk_eligible_2005_plus_targets") != len(bulk_targets)
        or any(row.get("schema_version") != PARTITION_SCHEMA_VERSION for row in partitions)
        or any(row.get("schema_version") != TARGET_CLASS_SCHEMA_VERSION for row in bulk_targets)
    ):
        raise ValueError("readiness count or schema drift")

    target_keys = [str(row.get("target_key") or "") for row in bulk_targets]
    if "" in target_keys or len(target_keys) != len(set(target_keys)):
        raise ValueError("bulk target key conservation drift")
    grouped: dict[tuple[str, int], list[str]] = {}
    for row in bulk_targets:
        if row.get("route_class") != "bulk_results_region_year_then_stable_id":
            raise ValueError("bulk target route classification drift")
        key = (str(row.get("country_region") or ""), int(row.get("year") or 0))
        grouped.setdefault(key, []).append(str(row["target_key"]))
    seen_partitions = set()
    total_ranges = 0
    total_ceiling = 0
    for partition in partitions:
        key = (str(partition.get("country_region") or ""), int(partition.get("year") or 0))
        ranges = partition.get("ranges")
        keys = sorted(grouped.get(key, []))
        expected_key_sha = hashlib.sha256(("\n".join(keys) + "\n").encode("utf-8")).hexdigest()
        if (
            key in seen_partitions
            or not keys
            or not isinstance(ranges, list)
            or not ranges
            or partition.get("target_count") != len(keys)
            or partition.get("target_keys_sha256") != expected_key_sha
            or partition.get("range_count") != len(ranges)
            or partition.get("protocol_request_ceiling")
            != len(ranges) * MAX_BULK_PAGES_PER_RANGE
            or partition.get("execution_ready") is not False
        ):
            raise ValueError("bulk partition conservation drift")
        seen_partitions.add(key)
        total_ranges += len(ranges)
        total_ceiling += int(partition["protocol_request_ceiling"])
    if (
        set(grouped) != seen_partitions
        or counts.get("bulk_date_ranges") != total_ranges
        or counts.get("protocol_request_ceiling") != total_ceiling
    ):
        raise ValueError("bulk partition totals drift")
    return partitions, bulk_targets, {
        "root": str(resolved),
        "report_sha256": report_sha,
        "partitions_sha256": outputs["bulk-partitions.jsonl"]["sha256"],
        "bulk_targets_sha256": outputs["bulk-eligible-targets.jsonl"]["sha256"],
        "target_artifact": dict(target),
        "execution_as_of_date": str(report.get("execution_as_of_date") or ""),
        "counts": dict(counts),
    }


def _validate_parameters(
    *, max_date_ranges_per_batch: int, min_interval_ms: int, spacing_minutes: int
) -> None:
    values = (max_date_ranges_per_batch, min_interval_ms, spacing_minutes)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("batch parameters must be integers")
    if not 1 <= max_date_ranges_per_batch <= 366 or min_interval_ms < 250 or spacing_minutes < 5:
        raise ValueError("batch parameters are outside safety bounds")


def build_batches(
    *,
    partitions: list[dict],
    bulk_targets: list[dict],
    target_rows: list[dict],
    max_date_ranges_per_batch: int = 366,
    min_interval_ms: int = 250,
    spacing_minutes: int = 5,
) -> list[dict]:
    _validate_parameters(
        max_date_ranges_per_batch=max_date_ranges_per_batch,
        min_interval_ms=min_interval_ms,
        spacing_minutes=spacing_minutes,
    )
    target_by_key = {str(row.get("target_key") or ""): row for row in target_rows}
    bulk_by_key = {str(row.get("target_key") or ""): row for row in bulk_targets}
    if (
        len(target_by_key) != len(target_rows)
        or len(bulk_by_key) != len(bulk_targets)
        or "" in target_by_key
        or "" in bulk_by_key
        or not set(bulk_by_key).issubset(target_by_key)
    ):
        raise ValueError("bulk target set is not contained in target ledger")
    for key, classified in bulk_by_key.items():
        target = target_by_key[key]
        if (
            target.get("country_region") != classified.get("country_region")
            or int(target.get("year") or 0) != int(classified.get("year") or 0)
            or target.get("grade_text") != classified.get("grade_text")
            or target.get("discipline") != classified.get("discipline")
        ):
            raise ValueError("bulk target classification does not match target ledger")

    grouped: dict[tuple[str, int], list[str]] = {}
    for key, row in bulk_by_key.items():
        grouped.setdefault((str(row["country_region"]), int(row["year"])), []).append(key)
    sorted_partitions = sorted(
        partitions, key=lambda row: (str(row["country_region"]), int(row["year"]))
    )
    packed: list[list[dict]] = []
    current: list[dict] = []
    current_region = ""
    current_ranges = 0
    for partition in sorted_partitions:
        region = str(partition["country_region"])
        range_count = int(partition["range_count"])
        if range_count > max_date_ranges_per_batch:
            raise ValueError("one region-year exceeds batch range ceiling")
        if current and (
            region != current_region or current_ranges + range_count > max_date_ranges_per_batch
        ):
            packed.append(current)
            current = []
            current_ranges = 0
        current_region = region
        current.append(partition)
        current_ranges += range_count
    if current:
        packed.append(current)

    batches = []
    seen_target_keys = set()
    for ordinal, units in enumerate(packed, 1):
        region = str(units[0]["country_region"])
        years = [int(unit["year"]) for unit in units]
        unit_keys = []
        for unit in units:
            unit_keys.extend(grouped[(region, int(unit["year"]))])
        keys = sorted(unit_keys)
        if seen_target_keys.intersection(keys):
            raise ValueError("target appears in multiple bulk batches")
        seen_target_keys.update(keys)
        range_count = sum(int(unit["range_count"]) for unit in units)
        request_ceiling = range_count * MAX_BULK_PAGES_PER_RANGE
        batch_id = f"{ordinal:04d}-{region}-{min(years)}-{max(years)}"
        rows = [target_by_key[key] for key in keys]
        batches.append(
            {
                "schema_version": BATCH_SCHEMA_VERSION,
                "batch_id": batch_id,
                "ordinal": ordinal,
                "country_region": region,
                "year_start": min(years),
                "year_end": max(years),
                "region_year_units": units,
                "region_year_unit_count": len(units),
                "date_range_count": range_count,
                "target_count": len(keys),
                "target_keys_sha256": hashlib.sha256(
                    ("\n".join(keys) + "\n").encode("utf-8")
                ).hexdigest(),
                "request_ceiling": request_ceiling,
                "theoretical_min_duration_seconds": request_ceiling * min_interval_ms / 1000,
                "not_before_offset_minutes": (ordinal - 1) * spacing_minutes,
                "approval_status": "proposed_not_approved",
                "execution_ready": False,
                "_target_rows": rows,
            }
        )
    if seen_target_keys != set(bulk_by_key):
        raise ValueError("bulk batch target set does not conserve")
    return batches


def prepare_plan(
    *,
    readiness_root: Path,
    expected_readiness_report_sha256: str,
    target_root: Path,
    expected_target_manifest_sha256: str,
    expected_target_ledger_sha256: str,
    output_dir: Path,
    max_date_ranges_per_batch: int = 366,
    min_interval_ms: int = 250,
    spacing_minutes: int = 5,
) -> dict:
    _validate_parameters(
        max_date_ranges_per_batch=max_date_ranges_per_batch,
        min_interval_ms=min_interval_ms,
        spacing_minutes=spacing_minutes,
    )
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("batch plan output directory must not already exist")
    partitions, bulk_targets, readiness = load_readiness_artifact(
        readiness_root, expected_report_sha256=expected_readiness_report_sha256
    )
    target_rows, target_identity = load_target_artifact(
        target_root,
        expected_manifest_sha256=expected_target_manifest_sha256,
        expected_ledger_sha256=expected_target_ledger_sha256,
    )
    expected_target = readiness["target_artifact"]
    if (
        expected_target.get("root") != target_identity.get("root")
        or expected_target.get("manifest_sha256") != target_identity.get("manifest_sha256")
        or expected_target.get("ledger_sha256") != target_identity.get("ledger_sha256")
        or expected_target.get("rows") != target_identity.get("rows")
        or expected_target.get("as_of_date") != target_identity.get("as_of_date")
    ):
        raise ValueError("readiness does not bind the supplied target artifact")
    batches = build_batches(
        partitions=partitions,
        bulk_targets=bulk_targets,
        target_rows=target_rows,
        max_date_ranges_per_batch=max_date_ranges_per_batch,
        min_interval_ms=min_interval_ms,
        spacing_minutes=spacing_minutes,
    )

    output_dir.mkdir(parents=True, mode=0o700)
    persisted_batches = []
    for batch in batches:
        target_batch_rows = batch.pop("_target_rows")
        ledger_path = output_dir / "target-ledgers" / f"{batch['batch_id']}.jsonl"
        payload = b"".join(
            (canonical_json(row) + "\n").encode("utf-8") for row in target_batch_rows
        )
        _atomic_write(ledger_path, payload)
        batch["target_ledger"] = {
            "path": str(ledger_path.relative_to(output_dir)),
            "sha256": sha256_path(ledger_path),
            "size": len(payload),
            "rows": len(target_batch_rows),
        }
        persisted_batches.append(batch)
    plan_path = output_dir / "batch-plan.jsonl"
    _atomic_write(
        plan_path,
        b"".join((canonical_json(row) + "\n").encode("utf-8") for row in persisted_batches),
    )
    by_region = Counter(batch["country_region"] for batch in persisted_batches)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROPOSED_NOT_APPROVED",
        "completion_marker": "PREPARED",
        "approval": False,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "readiness_artifact": readiness,
        "target_artifact": target_identity,
        "parameters": {
            "max_date_ranges_per_batch": max_date_ranges_per_batch,
            "max_pages_per_range": MAX_BULK_PAGES_PER_RANGE,
            "min_interval_ms": min_interval_ms,
            "max_requests_per_second": 1000 / min_interval_ms,
            "spacing_minutes": spacing_minutes,
            "max_concurrent_batches": 1,
            "exclusive_account_proof_required_per_batch": True,
            "exact_g3_required_per_batch": True,
        },
        "counts": {
            "batches": len(persisted_batches),
            "targets": sum(batch["target_count"] for batch in persisted_batches),
            "region_year_units": sum(
                batch["region_year_unit_count"] for batch in persisted_batches
            ),
            "date_ranges": sum(batch["date_range_count"] for batch in persisted_batches),
            "protocol_request_ceiling": sum(
                batch["request_ceiling"] for batch in persisted_batches
            ),
            "maximum_batch_request_ceiling": max(
                batch["request_ceiling"] for batch in persisted_batches
            ),
            "by_region_batches": dict(sorted(by_region.items())),
        },
        "batch_plan": _file_identity(plan_path, rows=len(persisted_batches)),
    }
    manifest_path = output_dir / "batch-plan-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    manifest_sha = sha256_path(manifest_path)
    _atomic_write(output_dir / "PREPARED", (manifest_sha + "\n").encode("ascii"))
    return {
        "status": manifest["status"],
        "output_dir": str(output_dir.resolve()),
        "manifest_sha256": manifest_sha,
        "plan_sha256": manifest["batch_plan"]["sha256"],
        "counts": manifest["counts"],
        "network_requests": 0,
        "database_writes": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness-root", type=Path, required=True)
    parser.add_argument("--expected-readiness-report-sha256", required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--expected-target-manifest-sha256", required=True)
    parser.add_argument("--expected-target-ledger-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-date-ranges-per-batch", type=int, default=4)
    parser.add_argument("--min-interval-ms", type=int, default=250)
    parser.add_argument("--spacing-minutes", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = prepare_plan(
            readiness_root=args.readiness_root,
            expected_readiness_report_sha256=args.expected_readiness_report_sha256,
            target_root=args.target_root,
            expected_target_manifest_sha256=args.expected_target_manifest_sha256,
            expected_target_ledger_sha256=args.expected_target_ledger_sha256,
            output_dir=args.output_dir,
            max_date_ranges_per_batch=args.max_date_ranges_per_batch,
            min_interval_ms=args.min_interval_ms,
            spacing_minutes=args.spacing_minutes,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
