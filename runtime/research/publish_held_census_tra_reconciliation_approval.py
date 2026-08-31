#!/usr/bin/env python3
"""Publish an independently approved, zero-gap held-census/TRA reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Mapping


RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from prepare_held_census_tra_reconciliation import (  # noqa: E402
    BINDING_SCHEMA_VERSION,
    SCHEMA_VERSION as PROPOSAL_SCHEMA_VERSION,
    TARGET_SUMMARY_SCHEMA_VERSION,
    build_proposal,
    load_approved_seed_artifact,
    load_census,
    load_seed_target_map,
    load_stable_runner_ledger,
)
from prepare_held_winner_seed_extension import (  # noqa: E402
    _atomic_write,
    _read_json,
    _read_jsonl,
    _regular,
    canonical_json,
    sha256_path,
)


DECISION_SCHEMA_VERSION = "held-census-tra-reconciliation-approval-decision.v1"
APPROVAL_SCHEMA_VERSION = "held-census-tra-reconciliation-approval.v1"
INDEPENDENCE_ACKNOWLEDGEMENT = "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR"
OUTPUT_NAMES = {
    "binding-candidates.jsonl",
    "review-items.jsonl",
    "target-summaries.jsonl",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def _timestamp(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    return parsed.isoformat()


def _output_rows(root: Path, manifest: Mapping[str, object], filename: str) -> tuple[Path, list[dict]]:
    outputs = manifest.get("outputs")
    identity = outputs.get(filename) if isinstance(outputs, Mapping) else None
    path = _regular(root / filename, label=f"proposal output {filename}")
    rows = _read_jsonl(path, label=f"proposal output {filename}")
    if (
        not isinstance(identity, Mapping)
        or identity.get("path") != filename
        or identity.get("sha256") != sha256_path(path)
        or identity.get("size") != path.stat().st_size
        or identity.get("rows") != len(rows)
    ):
        raise ValueError(f"proposal output identity drift: {filename}")
    return path, rows


def _require_zero_gap_counts(counts: object) -> dict:
    if not isinstance(counts, dict):
        raise ValueError("reconciliation counts are missing")
    expected = counts.get("expected_actual_starter_slots")
    observed = counts.get("tra_actual_starter_occurrences")
    bindings = counts.get("unique_binding_candidates")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected < 1
        or observed != expected
        or bindings != expected
        or counts.get("review_items") != 0
        or counts.get("targets_with_count_mismatch") != 0
        or counts.get("source_slots_unmatched_or_ambiguous") != 0
        or counts.get("tra_runners_unmatched_or_ambiguous") != 0
        or isinstance(counts.get("targets"), bool)
        or not isinstance(counts.get("targets"), int)
        or counts["targets"] < 1
    ):
        raise ValueError("reconciliation is not zero-gap and cannot be approved")
    return counts


def _replay_proposal(manifest: Mapping[str, object], expected_outputs: Mapping[str, object]) -> None:
    census_contract = manifest.get("census")
    seed_contract = manifest.get("held_seed_proposal")
    approved_seed_contract = manifest.get("approved_held_seed_artifact")
    stable_contract = manifest.get("stable_runner_ledger")
    scope = manifest.get("scope")
    if not all(
        isinstance(value, Mapping)
        for value in (census_contract, seed_contract, approved_seed_contract, stable_contract)
    ):
        raise ValueError("reconciliation proposal input identities are missing")
    census_rows, summaries, census_identity = load_census(
        Path(str(census_contract.get("root") or "")),
        approved_manifest_sha256=str(census_contract.get("manifest_sha256") or ""),
    )
    target_keys = {str(row["target_key"]) for row in summaries}
    seed_map, seed_identity = load_seed_target_map(
        Path(str(seed_contract.get("root") or "")),
        approved_manifest_sha256=str(seed_contract.get("manifest_sha256") or ""),
        expected_target_keys=target_keys,
    )
    target_identity = census_identity.get("target_artifact")
    if not isinstance(target_identity, Mapping):
        raise ValueError("replayed census target identity is missing")
    _approved_seeds, approved_seed_identity = load_approved_seed_artifact(
        Path(str(approved_seed_contract.get("root") or "")),
        approved_manifest_sha256=str(approved_seed_contract.get("manifest_sha256") or ""),
        approved_ledger_sha256=str(approved_seed_contract.get("ledger_sha256") or ""),
        target_identity=target_identity,
        proposal_identity=seed_identity,
        expected_seed_ids=set(seed_map),
    )
    stable_rows, stable_identity = load_stable_runner_ledger(
        Path(str(stable_contract.get("root") or "")),
        approved_manifest_sha256=str(stable_contract.get("manifest_sha256") or ""),
    )
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "replay"
        replayed = build_proposal(
            census_rows=census_rows,
            census_summaries=summaries,
            census_identity=census_identity,
            seed_to_target=seed_map,
            seed_identity=seed_identity,
            approved_seed_identity=approved_seed_identity,
            stable_rows=stable_rows,
            stable_identity=stable_identity,
            output_dir=output,
            stable_scope_only=(
                isinstance(scope, Mapping)
                and scope.get("mode") == "stable_occurrence_seed_intersection"
            ),
        )
        for filename in OUTPUT_NAMES:
            if sha256_path(output / filename) != expected_outputs[filename]["sha256"]:
                raise ValueError("reconciliation output no longer replays from bound inputs")
        if canonical_json(replayed["counts"]) != canonical_json(manifest.get("counts")):
            raise ValueError("reconciliation counts no longer replay from bound inputs")


def _validate_proposal(
    root: Path,
    *,
    approved_manifest_sha256: str,
) -> tuple[dict, dict[str, Path], dict[str, list[dict]]]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("reconciliation proposal root must be a regular directory")
    if {path.name for path in resolved.iterdir()} != OUTPUT_NAMES | {"proposal-manifest.json", "PREPARED"}:
        raise ValueError("reconciliation proposal has missing or extra members")
    manifest_path = _regular(resolved / "proposal-manifest.json", label="proposal manifest")
    marker = _regular(resolved / "PREPARED", label="proposal marker")
    manifest_sha = sha256_path(manifest_path)
    if (
        not SHA256_RE.fullmatch(approved_manifest_sha256)
        or manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
    ):
        raise ValueError("reconciliation proposal manifest identity mismatch")
    manifest = _read_json(manifest_path, label="reconciliation proposal manifest")
    outputs = manifest.get("outputs")
    scope = manifest.get("scope")
    if (
        manifest.get("schema_version") != PROPOSAL_SCHEMA_VERSION
        or manifest.get("status") != "PREPARED_NOT_EXECUTABLE"
        or manifest.get("execution_ready") is not False
        or manifest.get("approval") is not False
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or manifest.get("completion_marker") != "PREPARED"
        or not isinstance(outputs, Mapping)
        or set(outputs) != OUTPUT_NAMES
        or not isinstance(scope, Mapping)
        or scope.get("mode")
        not in {"full_census", "stable_occurrence_seed_intersection"}
        or not isinstance(scope.get("source_targeted_seed_ids"), list)
        or not scope["source_targeted_seed_ids"]
        or len(scope["source_targeted_seed_ids"])
        != len(set(scope["source_targeted_seed_ids"]))
        or not isinstance(scope.get("target_keys"), list)
        or not scope["target_keys"]
        or len(scope["target_keys"]) != len(set(scope["target_keys"]))
    ):
        raise ValueError("reconciliation proposal contract drift")
    counts = _require_zero_gap_counts(manifest.get("counts"))
    paths = {}
    rows = {}
    for filename in OUTPUT_NAMES:
        paths[filename], rows[filename] = _output_rows(resolved, manifest, filename)
    if (
        len(rows["binding-candidates.jsonl"]) != counts["unique_binding_candidates"]
        or rows["review-items.jsonl"]
        or len(rows["target-summaries.jsonl"]) != counts["targets"]
        or any(row.get("schema_version") != BINDING_SCHEMA_VERSION for row in rows["binding-candidates.jsonl"])
        or any(
            row.get("schema_version") != TARGET_SUMMARY_SCHEMA_VERSION
            or row.get("count_conserved") is not True
            or row.get("unmatched_or_ambiguous_source_slots") != 0
            or row.get("unmatched_or_ambiguous_tra_runners") != 0
            for row in rows["target-summaries.jsonl"]
        )
    ):
        raise ValueError("zero-gap reconciliation row conservation drift")
    _replay_proposal(manifest, outputs)
    return manifest, paths, rows


def publish_approval(
    *,
    proposal_root: Path,
    approved_proposal_manifest_sha256: str,
    decision_file: Path,
    approved_decision_sha256: str,
    output_dir: Path,
) -> dict:
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("approval output directory must be absent or empty")
    manifest, paths, rows = _validate_proposal(
        proposal_root,
        approved_manifest_sha256=approved_proposal_manifest_sha256,
    )
    decision_path = _regular(decision_file, label="reconciliation approval decision")
    if (
        not SHA256_RE.fullmatch(approved_decision_sha256)
        or sha256_path(decision_path) != approved_decision_sha256
    ):
        raise ValueError("reconciliation approval decision SHA mismatch")
    decision = _read_json(decision_path, label="reconciliation approval decision")
    reviewed_at = _timestamp(decision.get("reviewed_at"))
    approved_outputs = decision.get("approved_outputs")
    expected_outputs = {
        name: manifest["outputs"][name]["sha256"]
        for name in sorted(OUTPUT_NAMES)
    }
    if (
        decision.get("schema_version") != DECISION_SCHEMA_VERSION
        or decision.get("decision") != "approve"
        or decision.get("proposal_manifest_sha256") != approved_proposal_manifest_sha256
        or decision.get("independence_acknowledgement") != INDEPENDENCE_ACKNOWLEDGEMENT
        or not str(decision.get("reviewed_by") or "").strip()
        or not str(decision.get("decision_source_reference") or "").strip()
        or not str(decision.get("reason") or "").strip()
        or not isinstance(approved_outputs, Mapping)
        or dict(sorted(approved_outputs.items())) != expected_outputs
    ):
        raise ValueError("approval decision does not bind exact zero-gap reconciliation outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    binding_path = output_dir / "approved-bindings.jsonl"
    summary_path = output_dir / "approved-target-summaries.jsonl"
    decision_copy = output_dir / "approval-decision.json"
    _atomic_write(binding_path, paths["binding-candidates.jsonl"].read_bytes())
    _atomic_write(summary_path, paths["target-summaries.jsonl"].read_bytes())
    _atomic_write(decision_copy, decision_path.read_bytes())
    unique_horse_ids = {str(row["tra_horse_id"]) for row in rows["binding-candidates.jsonl"]}
    approval_manifest = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "status": "complete",
        "completion_marker": "COMPLETE",
        "network_requests": 0,
        "database_writes": 0,
        "source_proposal": {
            "root": str(proposal_root.resolve(strict=True)),
            "manifest_sha256": approved_proposal_manifest_sha256,
            "approved_outputs": expected_outputs,
        },
        "decision": {
            "sha256": approved_decision_sha256,
            "reviewed_by": str(decision["reviewed_by"]).strip(),
            "reviewed_at": reviewed_at,
            "decision_source_reference": str(decision["decision_source_reference"]).strip(),
            "independence_acknowledgement": INDEPENDENCE_ACKNOWLEDGEMENT,
        },
        "counts": {
            "targets": manifest["counts"]["targets"],
            "approved_starter_bindings": len(rows["binding-candidates.jsonl"]),
            "unique_tra_horse_ids": len(unique_horse_ids),
            "review_items": 0,
            "count_mismatches": 0,
        },
        "approved_bindings": {
            "path": binding_path.name,
            "rows": len(rows["binding-candidates.jsonl"]),
            "size": binding_path.stat().st_size,
            "sha256": sha256_path(binding_path),
        },
        "approved_target_summaries": {
            "path": summary_path.name,
            "rows": len(rows["target-summaries.jsonl"]),
            "size": summary_path.stat().st_size,
            "sha256": sha256_path(summary_path),
        },
        "approval_decision": {
            "path": decision_copy.name,
            "size": decision_copy.stat().st_size,
            "sha256": sha256_path(decision_copy),
        },
    }
    manifest_path = output_dir / "approval-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(approval_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "COMPLETE", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return approval_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal-root", type=Path, required=True)
    parser.add_argument("--approved-proposal-manifest-sha256", required=True)
    parser.add_argument("--decision-file", type=Path, required=True)
    parser.add_argument("--approved-decision-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    manifest = publish_approval(**vars(parse_args()))
    print(canonical_json(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
