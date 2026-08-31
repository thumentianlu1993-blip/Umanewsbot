#!/usr/bin/env python3
"""Audit full-target TRA bulk-result partitions without network or DB writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping


from prepare_held_winner_seed_extension import (
    _atomic_write,
    _read_json,
    _read_jsonl,
    _regular,
    _require_sha,
    canonical_json,
    sha256_path,
)


SCHEMA_VERSION = "racing-api-bulk-partition-readiness-audit.v2"
PARTITION_SCHEMA_VERSION = "racing-api-bulk-region-year-partition.v1"
TARGET_CLASS_SCHEMA_VERSION = "racing-api-bulk-target-classification.v1"
TARGET_MANIFEST_SCHEMA = "graded-horse-target-ledger.v1"
COVERAGE_MANIFEST_SCHEMA = "graded-race-source-coverage-plan.v1"
VALID_REGIONS = {"france", "ireland", "united_kingdom", "united_states"}
VALID_STATES = {
    "calendar_candidate_result_required",
    "held_candidate_current_target_review_required",
    "held_result_current_target",
    "not_due_official_calendar",
    "source_route_only",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
# Provider guidance recommends one results query per calendar date.  Ten pages
# is a deliberately conservative fail-closed ceiling for one region/day; it is
# not an expected request count.
MAX_BULK_PAGES_PER_RANGE = 10
PROVIDER_RESULTS_WINDOW_MONTHS = 12


def _bulk_query_earliest_date(as_of_date: date) -> date:
    """Return a conservative date strictly inside TRA's rolling 12-month window.

    Live provider evidence on 2026-09-01 showed that ``/v1/results`` rejects
    older dates with ``start date must be 12 months or less in the past``.
    We deliberately add one day after the calendar-year anniversary so the
    boundary cannot drift because of provider time-zone or inclusive/exclusive
    interpretation.  Races on that single boundary day remain gaps and route
    through reviewed external anchors plus stable-ID endpoints.
    """

    try:
        anniversary = as_of_date.replace(year=as_of_date.year - 1)
    except ValueError:  # February 29 -> February 28 in the prior year.
        anniversary = as_of_date.replace(year=as_of_date.year - 1, day=28)
    return anniversary + timedelta(days=1)


def _write_jsonl(path: Path, rows: list[dict]) -> dict:
    body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
    _atomic_write(path, body)
    return {
        "path": path.name,
        "rows": len(rows),
        "size": len(body),
        "sha256": sha256_path(path),
    }


def load_target_artifact(
    root: Path,
    *,
    expected_manifest_sha256: str,
    expected_ledger_sha256: str,
) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("target artifact root must be a regular directory")
    manifest_path = _regular(resolved / "target-ledger-manifest.json", label="target manifest")
    manifest = _read_json(manifest_path, label="target manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, expected_manifest_sha256, label="target manifest")
    marker = _regular(resolved / "COMPLETE", label="target COMPLETE marker")
    identity = manifest.get("target_ledger")
    if (
        manifest.get("schema_version") != TARGET_MANIFEST_SCHEMA
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("database_writes") != 0
        or manifest.get("blocking_source_count_conflicts") != []
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(identity, Mapping)
    ):
        raise ValueError("target artifact is not reviewed COMPLETE")
    relative = str(identity.get("path") or "")
    if Path(relative).name != relative:
        raise ValueError("target ledger path is invalid")
    ledger_path = _regular(resolved / relative, label="target ledger")
    ledger_sha = sha256_path(ledger_path)
    _require_sha(ledger_sha, expected_ledger_sha256, label="target ledger")
    rows = _read_jsonl(ledger_path, label="target ledger")
    target_keys = [str(row.get("target_key") or "") for row in rows]
    if (
        identity.get("sha256") != ledger_sha
        or identity.get("rows") != len(rows)
        or "" in target_keys
        or len(target_keys) != len(set(target_keys))
    ):
        raise ValueError("target ledger identity or key conservation drift")
    try:
        as_of_date = date.fromisoformat(str(manifest.get("as_of_date") or ""))
    except ValueError as exc:
        raise ValueError("target artifact as_of_date is invalid") from exc
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "ledger_sha256": ledger_sha,
        "rows": len(rows),
        "as_of_date": as_of_date.isoformat(),
    }


def load_coverage_artifact(
    root: Path,
    *,
    expected_manifest_sha256: str,
    expected_plan_sha256: str,
    target_identity: Mapping[str, object],
) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("coverage artifact root must be a regular directory")
    manifest_path = _regular(resolved / "coverage-plan-manifest.json", label="coverage manifest")
    manifest = _read_json(manifest_path, label="coverage manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, expected_manifest_sha256, label="coverage manifest")
    marker = _regular(resolved / "PREPARED", label="coverage PREPARED marker")
    outputs = manifest.get("outputs")
    target = manifest.get("target_artifact")
    if (
        manifest.get("schema_version") != COVERAGE_MANIFEST_SCHEMA
        or manifest.get("status") != "review_required"
        or manifest.get("execution_ready") is not False
        or manifest.get("completion_marker") != "PREPARED"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(outputs, Mapping)
        or not isinstance(target, Mapping)
        or target.get("manifest_sha256") != target_identity.get("manifest_sha256")
        or target.get("ledger_sha256") != target_identity.get("ledger_sha256")
        or target.get("rows") != target_identity.get("rows")
        or target.get("as_of_date") != target_identity.get("as_of_date")
    ):
        raise ValueError("coverage artifact does not bind the exact target denominator")
    identity = outputs.get("target-source-plan.jsonl")
    if not isinstance(identity, Mapping):
        raise ValueError("coverage target-source plan identity is missing")
    path = _regular(resolved / "target-source-plan.jsonl", label="coverage target-source plan")
    plan_sha = sha256_path(path)
    _require_sha(plan_sha, expected_plan_sha256, label="coverage target-source plan")
    rows = _read_jsonl(path, label="coverage target-source plan")
    keys = [str(row.get("target_key") or "") for row in rows]
    if (
        identity.get("sha256") != plan_sha
        or identity.get("rows") != len(rows)
        or identity.get("size") != path.stat().st_size
        or "" in keys
        or len(keys) != len(set(keys))
        or any(row.get("evidence_state") not in VALID_STATES for row in rows)
    ):
        raise ValueError("coverage target-source plan conservation drift")
    evidence_inputs = manifest.get("evidence_inputs")
    calendar_identity = (
        evidence_inputs.get("calendar")
        if isinstance(evidence_inputs, Mapping)
        else None
    )
    calendar_as_of_date = (
        str(calendar_identity.get("as_of_date") or "")
        if isinstance(calendar_identity, Mapping)
        else ""
    )
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "plan_sha256": plan_sha,
        "rows": len(rows),
        "status": manifest["status"],
        "execution_ready": False,
        "calendar_as_of_date": calendar_as_of_date,
    }


def _ranges_for_year(
    year: int, as_of_date: date, bulk_query_earliest_date: date
) -> list[dict]:
    if year > as_of_date.year:
        raise ValueError("due target year is after as_of_date")
    start = max(date(year, 1, 1), bulk_query_earliest_date)
    end = as_of_date if year == as_of_date.year else date(year, 12, 31)
    if end < start:
        raise ValueError("as_of_date is before the target year")
    ranges = []
    cursor = start
    while cursor <= end:
        ranges.append((cursor, cursor))
        cursor += timedelta(days=1)
    return [
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "max_pages_protocol_ceiling": MAX_BULK_PAGES_PER_RANGE,
        }
        for start, end in ranges
    ]


def build_readiness(
    *,
    target_rows: list[dict],
    coverage_rows: list[dict],
    target_identity: dict,
    coverage_identity: dict,
    execution_as_of_date: date | None = None,
) -> dict:
    targets = {str(row.get("target_key") or ""): row for row in target_rows}
    coverage = {str(row.get("target_key") or ""): row for row in coverage_rows}
    if "" in targets or "" in coverage or set(targets) != set(coverage):
        raise ValueError("target and coverage key sets do not conserve")
    target_catalog_as_of_date = date.fromisoformat(target_identity["as_of_date"])
    as_of_date = execution_as_of_date or target_catalog_as_of_date
    if (
        as_of_date < target_catalog_as_of_date
        or as_of_date.year != target_catalog_as_of_date.year
    ):
        raise ValueError("execution as_of_date is outside target catalog year")
    coverage_calendar_as_of = str(
        coverage_identity.get("calendar_as_of_date") or ""
    )
    if coverage_calendar_as_of:
        try:
            coverage_calendar_date = date.fromisoformat(coverage_calendar_as_of)
        except ValueError as exc:
            raise ValueError("coverage calendar as_of_date is invalid") from exc
        if (
            coverage_calendar_date < as_of_date
            or coverage_calendar_date.year != as_of_date.year
        ):
            raise ValueError("coverage calendar is stale for execution as_of_date")
    bulk_query_earliest_date = _bulk_query_earliest_date(as_of_date)
    classified = {"bulk": [], "historical": [], "not_due": []}
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for target_key in sorted(targets):
        target = targets[target_key]
        source = coverage[target_key]
        region = str(target.get("country_region") or "")
        try:
            year = int(target.get("year"))
        except (TypeError, ValueError) as exc:
            raise ValueError("target year is invalid") from exc
        if year > as_of_date.year:
            raise ValueError("due target year is after as_of_date")
        if (
            region not in VALID_REGIONS
            or source.get("country_region") != region
            or int(source.get("year") or 0) != year
            or source.get("grade_text") != target.get("grade_text")
            or source.get("discipline") != target.get("discipline")
        ):
            raise ValueError("target and coverage classification fields disagree")
        row = {
            "schema_version": TARGET_CLASS_SCHEMA_VERSION,
            "target_key": target_key,
            "country_region": region,
            "year": year,
            "grade_text": target.get("grade_text"),
            "discipline": target.get("discipline"),
            "evidence_state": source.get("evidence_state"),
            "local_date_known": bool(str(target.get("local_date") or "")),
        }
        local_date_text = str(target.get("local_date") or "")
        local_date_value = None
        if local_date_text:
            try:
                local_date_value = date.fromisoformat(local_date_text)
            except ValueError as exc:
                raise ValueError("target local_date is invalid") from exc
            if local_date_value.year != year:
                raise ValueError("target local_date year disagrees with target year")
        if source.get("evidence_state") == "not_due_official_calendar":
            row["route_class"] = "not_due_excluded_from_results"
            classified["not_due"].append(row)
        elif not (
            year == as_of_date.year
            or (
                local_date_value is not None
                and bulk_query_earliest_date <= local_date_value <= as_of_date
            )
        ):
            row["route_class"] = "external_anchor_then_targeted_horse_results"
            classified["historical"].append(row)
        else:
            row["route_class"] = "bulk_results_region_year_then_stable_id"
            classified["bulk"].append(row)
            grouped[(region, year)].append(row)
    partitions = []
    for (region, year), rows in sorted(grouped.items()):
        ranges = _ranges_for_year(year, as_of_date, bulk_query_earliest_date)
        target_keys = sorted(row["target_key"] for row in rows)
        evidence_counts = Counter(row["evidence_state"] for row in rows)
        partitions.append(
            {
                "schema_version": PARTITION_SCHEMA_VERSION,
                "country_region": region,
                "year": year,
                "target_count": len(rows),
                "target_keys_sha256": hashlib.sha256(
                    ("\n".join(target_keys) + "\n").encode("utf-8")
                ).hexdigest(),
                "evidence_state_counts": dict(sorted(evidence_counts.items())),
                "ranges": ranges,
                "range_count": len(ranges),
                "protocol_request_ceiling": len(ranges) * MAX_BULK_PAGES_PER_RANGE,
                "actual_request_count": None,
                "execution_ready": False,
            }
        )
    by_region = []
    for region in sorted(VALID_REGIONS):
        bulk = [row for row in classified["bulk"] if row["country_region"] == region]
        historical = [
            row
            for row in classified["historical"]
            if row["country_region"] == region
        ]
        future = [row for row in classified["not_due"] if row["country_region"] == region]
        region_partitions = [row for row in partitions if row["country_region"] == region]
        by_region.append(
            {
                "country_region": region,
                "bulk_eligible_targets": len(bulk),
                "historical_targeted_anchor_targets": len(historical),
                "not_due_targets": len(future),
                "bulk_region_year_units": len(region_partitions),
                "bulk_date_ranges": sum(row["range_count"] for row in region_partitions),
                "protocol_request_ceiling": sum(
                    row["protocol_request_ceiling"] for row in region_partitions
                ),
            }
        )
    protocol_ceiling = sum(row["protocol_request_ceiling"] for row in partitions)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_ENTITLEMENT_PROOF_AND_EXECUTION_PLAN",
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "execution_as_of_date": as_of_date.isoformat(),
        "target_artifact": target_identity,
        "coverage_artifact": coverage_identity,
        "assumptions": {
            "target_catalog_as_of_date": target_catalog_as_of_date.isoformat(),
            "provider_results_window_months": PROVIDER_RESULTS_WINDOW_MONTHS,
            "bulk_query_earliest_date": bulk_query_earliest_date.isoformat(),
            "bulk_query_boundary_policy": "strictly_inside_window_route_boundary_gap_to_stable_id",
            "previous_year_unknown_date_policy": "route_to_external_anchor_then_targeted_horse",
            "provider_window_evidence": "http_422_start_date_must_be_12_months_or_less_in_the_past",
            "bulk_range_max_inclusive_days": 1,
            "bulk_partition_strategy": "one_region_per_calendar_date",
            "bulk_limit": 100,
            "bulk_skip_max": 20000,
            "max_pages_protocol_ceiling_per_range": MAX_BULK_PAGES_PER_RANGE,
            "historical_add_on_entitlement": "requires_fresh_account_proof",
            "north_america_entitlement": "requires_fresh_account_proof",
        },
        "counts": {
            "targets": len(targets),
            "due_targets": len(classified["bulk"]) + len(classified["historical"]),
            "bulk_eligible_rolling_window_targets": len(classified["bulk"]),
            "historical_targeted_anchor_targets": len(classified["historical"]),
            "not_due_targets": len(classified["not_due"]),
            "bulk_region_year_units": len(partitions),
            "bulk_date_ranges": sum(row["range_count"] for row in partitions),
            "protocol_request_ceiling": protocol_ceiling,
            "protocol_minimum_seconds_at_4_requests_per_second": protocol_ceiling / 4,
        },
        "by_region": by_region,
        "partitions": partitions,
        "classified_targets": classified,
        "blockers": [
            "bulk results are limited to the provider rolling 12-month window",
            "protocol page ceiling is a fail-closed maximum, not an approved or expected request budget",
            "bulk daily outputs require exact target reconciliation and gap review before stable-ID extraction",
            "the conservative boundary day and all unreconciled targets remain gaps for stable-ID recovery",
            "historical targets require reviewed external anchors and targeted horse results",
            "each network batch still requires exclusive-account proof, exact G3, and execution ledger",
        ],
    }


def write_audit(report: Mapping[str, object], output_dir: Path) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("audit output directory must not already exist")
    output_dir.mkdir(parents=True, mode=0o700)
    classified = report["classified_targets"]
    outputs = {
        "bulk-partitions.jsonl": _write_jsonl(
            output_dir / "bulk-partitions.jsonl", list(report["partitions"])
        ),
        "bulk-eligible-targets.jsonl": _write_jsonl(
            output_dir / "bulk-eligible-targets.jsonl", list(classified["bulk"])
        ),
        "historical-targeted-anchor-targets.jsonl": _write_jsonl(
            output_dir / "historical-targeted-anchor-targets.jsonl",
            list(classified["historical"]),
        ),
        "not-due-targets.jsonl": _write_jsonl(
            output_dir / "not-due-targets.jsonl", list(classified["not_due"])
        ),
    }
    persisted = {key: value for key, value in report.items() if key not in {"partitions", "classified_targets"}}
    persisted["outputs"] = outputs
    report_path = output_dir / "readiness-audit.json"
    _atomic_write(
        report_path,
        (json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    report_sha = sha256_path(report_path)
    _atomic_write(output_dir / "PREPARED", (report_sha + "\n").encode("ascii"))
    return {
        "status": report["status"],
        "output_dir": str(output_dir.resolve()),
        "report_sha256": report_sha,
        "network_requests": 0,
        "database_writes": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--expected-target-manifest-sha256", required=True)
    parser.add_argument("--expected-target-ledger-sha256", required=True)
    parser.add_argument("--coverage-root", type=Path, required=True)
    parser.add_argument("--expected-coverage-manifest-sha256", required=True)
    parser.add_argument("--expected-coverage-plan-sha256", required=True)
    parser.add_argument("--execution-as-of-date", type=date.fromisoformat)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        target_rows, target_identity = load_target_artifact(
            args.target_root,
            expected_manifest_sha256=args.expected_target_manifest_sha256,
            expected_ledger_sha256=args.expected_target_ledger_sha256,
        )
        coverage_rows, coverage_identity = load_coverage_artifact(
            args.coverage_root,
            expected_manifest_sha256=args.expected_coverage_manifest_sha256,
            expected_plan_sha256=args.expected_coverage_plan_sha256,
            target_identity=target_identity,
        )
        report = build_readiness(
            target_rows=target_rows,
            coverage_rows=coverage_rows,
            target_identity=target_identity,
            coverage_identity=coverage_identity,
            execution_as_of_date=args.execution_as_of_date,
        )
        summary = write_audit(report, args.output_dir)
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
