#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


HEX64 = re.compile(r"[0-9a-f]{64}")
COVERAGE_TIERS = {"historical_hard", "historical_best_effort", "new_formal"}
DETAIL_STATUSES = {"complete", "gap", "pending", "not_applicable"}
DETAIL_PACKAGE_STATUSES = {"complete", "gap", "pending", "not_applicable"}
ACCOUNTING_STATUSES = {"satisfied", "blocked"}
BARRIER_EVIDENCE_STATUSES = {"complete", "not_applicable_with_evidence", "unknown"}
SELECTION_FILES = {
    "historical_hard_selection.jsonl": "historical_hard",
    "historical_best_effort_selection.jsonl": "historical_best_effort",
    "new_formal_selection.jsonl": "new_formal",
}


class CoverageVerificationError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageVerificationError(f"artifact JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CoverageVerificationError(f"artifact JSON object is required: {path}")
    return value


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CoverageVerificationError(f"artifact JSONL is invalid: {path.name}:{line_no}") from exc
            if not isinstance(row, dict):
                raise CoverageVerificationError(f"artifact JSONL object is required: {path.name}:{line_no}")
            yield line_no, row


def _validate_statuses(row: dict[str, Any], line_no: int) -> None:
    values = {
        "coverage_tier": (row.get("coverage_tier"), COVERAGE_TIERS),
        "detail_status": (row.get("detail_status"), DETAIL_STATUSES),
        "detail_package_status": (row.get("detail_package_status"), DETAIL_PACKAGE_STATUSES),
        "accounting_status": (row.get("accounting_status"), ACCOUNTING_STATUSES),
        "barrier_evidence_status": (row.get("barrier_evidence_status"), BARRIER_EVIDENCE_STATUSES),
    }
    for name, (value, allowed) in values.items():
        if value not in allowed:
            raise CoverageVerificationError(f"unknown {name} at coverage ledger row {line_no}")
    if row.get("policy_acceptance_status") != row.get("accounting_status"):
        raise CoverageVerificationError("policy/accounting status alias mismatch")
    detail = row["detail_status"]
    package = row["detail_package_status"]
    accounting = row["accounting_status"]
    barrier = row["barrier_evidence_status"]
    blockers = row.get("hard_blockers")
    if not isinstance(blockers, list) or detail != package:
        raise CoverageVerificationError("invalid detail/package status combination")
    if detail in {"gap", "pending"}:
        valid = accounting == "blocked" and barrier == "unknown" and bool(blockers)
    elif detail == "not_applicable":
        valid = accounting == "satisfied" and barrier == "not_applicable_with_evidence" and not blockers
    elif accounting == "satisfied":
        valid = barrier in {"complete", "not_applicable_with_evidence"} and not blockers
    else:
        valid = bool(blockers)
    if not valid:
        raise CoverageVerificationError("invalid coverage status combination")


def verify_coverage(artifact_root: Path | str, *, phase: str) -> dict[str, Any]:
    root = Path(artifact_root)
    if phase == "full_history":
        raise CoverageVerificationError("full_history is unavailable without a complete 1998-2024 master baseline")
    if phase != "remaining_historical":
        raise CoverageVerificationError("only --phase remaining_historical is supported")
    manifest = _read(root / "manifest.json")
    if manifest.get("scope") != "remaining_targets_only" or manifest.get("full_history_baseline_available") is not False:
        raise CoverageVerificationError("artifact scope could be misreported as full history")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CoverageVerificationError("artifact manifest is invalid")
    for name, identity in artifacts.items():
        path = root / str(identity.get("path") or "")
        if not path.is_file() or path.stat().st_size != int(identity.get("size", -1)) or _sha(path) != identity.get("sha256"):
            raise CoverageVerificationError(f"artifact identity mismatch: {name}")
    ledger = root / "coverage_ledger.jsonl"
    seen: dict[int, tuple[str, str]] = {}
    tiers: Counter[str] = Counter()
    details: Counter[str] = Counter()
    package_details: Counter[str] = Counter()
    accountings: Counter[str] = Counter()
    barriers: Counter[str] = Counter()
    blockers: list[int] = []
    for line_no, row in _iter_jsonl(ledger):
        try:
            target_id = int(row["target_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CoverageVerificationError(f"coverage ledger row is invalid: {line_no}") from exc
        target_sha = str(row.get("target_sha256") or "")
        if not HEX64.fullmatch(target_sha) or target_id in seen:
            raise CoverageVerificationError("coverage ledger target identity is invalid or duplicated")
        _validate_statuses(row, line_no)
        seen[target_id] = (target_sha, row["coverage_tier"])
        tiers[row["coverage_tier"]] += 1
        details[row["detail_status"]] += 1
        package_details[row["detail_package_status"]] += 1
        accountings[row["accounting_status"]] += 1
        barriers[row["barrier_evidence_status"]] += 1
        if row["coverage_tier"] == "historical_hard" and row["accounting_status"] != "satisfied":
            blockers.append(target_id)
    selected: dict[int, tuple[str, str]] = {}
    selection_counts: Counter[str] = Counter()
    for name, expected_tier in SELECTION_FILES.items():
        for line_no, row in _iter_jsonl(root / name):
            try:
                target_id = int(row["target_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CoverageVerificationError(f"selection target identity is invalid: {name}:{line_no}") from exc
            target_sha = str(row.get("target_sha256") or "")
            tier = str(row.get("coverage_tier") or "")
            if not HEX64.fullmatch(target_sha) or tier != expected_tier or target_id in selected:
                raise CoverageVerificationError("selection target identity/tier is invalid or duplicated")
            selected[target_id] = (target_sha, tier)
            selection_counts[tier] += 1
    if selected != seen:
        raise CoverageVerificationError("selection and coverage ledger identities do not match")
    summary = _read(root / "summary.json")
    if len(seen) != int(manifest.get("target_count", -1)) or len(seen) != int(summary.get("target_count", -1)):
        raise CoverageVerificationError("coverage target count conservation failed")
    if (
        dict(sorted(tiers.items())) != summary.get("coverage_tier_counts")
        or dict(sorted(details.items())) != summary.get("detail_status_counts")
        or dict(sorted(package_details.items())) != summary.get("detail_package_status_counts")
        or dict(sorted(accountings.items())) != summary.get("accounting_status_counts")
        or dict(sorted(accountings.items())) != summary.get("acceptance_status_counts")
        or dict(sorted(barriers.items())) != summary.get("barrier_evidence_status_counts")
        or {
            tier: selection_counts[tier]
            for tier in SELECTION_FILES.values()
        } != summary.get("selection_counts")
    ):
        raise CoverageVerificationError("coverage summary conservation failed")
    return {
        "phase": phase,
        "scope": "remaining_targets_only",
        "passed": not blockers,
        "target_count": len(seen),
        "historical_hard_count": tiers["historical_hard"],
        "blocking_count": len(blockers),
        "blocking_target_ids": sorted(blockers),
        "best_effort_reported_not_blocking": tiers["historical_best_effort"],
        "new_formal_reported_not_blocking": tiers["new_formal"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify historical race coverage-policy artifacts.")
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_coverage(args.artifact_root, phase=args.phase)
    except CoverageVerificationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
