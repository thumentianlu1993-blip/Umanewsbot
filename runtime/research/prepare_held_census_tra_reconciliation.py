#!/usr/bin/env python3
"""Prepare reviewed held starter-slot to TRA ``hrs_*`` reconciliation candidates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping


RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from build_held_actual_starter_census import (  # noqa: E402
    SCHEMA_VERSION as CENSUS_SCHEMA_VERSION,
    STARTER_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)
from prepare_held_winner_seed_extension import (  # noqa: E402
    SCHEMA_VERSION as SEED_PROPOSAL_SCHEMA_VERSION,
    _atomic_write,
    _normalize_name,
    _read_json,
    _read_jsonl,
    _regular,
    _require_sha,
    _split_country,
    canonical_json,
    load_existing_seed_artifact,
    sha256_path,
)
from racing_api_horse_export import runner_disposition  # noqa: E402


SCHEMA_VERSION = "held-census-tra-reconciliation-proposal.v1"
BINDING_SCHEMA_VERSION = "held-starter-tra-binding-candidate.v1"
REVIEW_SCHEMA_VERSION = "held-starter-tra-reconciliation-review.v1"
TARGET_SUMMARY_SCHEMA_VERSION = "held-starter-tra-reconciliation-summary.v1"
STABLE_LEDGER_SEED_SCHEMAS = {
    "target-runner-stable-id-ledger.v1": "targeted-runner-stable-id-seed.v1",
    "target-runner-stable-id-ledger.v2": "targeted-runner-stable-id-seed.v2",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
SEED_OUTPUT_NAMES = {
    "existing-seed-bindings.jsonl",
    "new-seed-candidates.jsonl",
    "all-held-targeted-horse-seeds.jsonl",
}


def _write_jsonl(path: Path, rows: list[dict]) -> dict:
    body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
    _atomic_write(path, body)
    return {
        "path": path.name,
        "rows": len(rows),
        "size": len(body),
        "sha256": sha256_path(path),
    }


def _output_identity(root: Path, manifest: Mapping[str, object], filename: str) -> list[dict]:
    outputs = manifest.get("outputs")
    identity = outputs.get(filename) if isinstance(outputs, Mapping) else None
    path = _regular(root / filename, label=filename)
    rows = _read_jsonl(path, label=filename)
    if (
        not isinstance(identity, Mapping)
        or identity.get("sha256") != sha256_path(path)
        or identity.get("size") != path.stat().st_size
        or identity.get("rows") != len(rows)
    ):
        raise ValueError(f"output identity drift: {filename}")
    return rows


def load_census(
    root: Path,
    *,
    approved_manifest_sha256: str,
) -> tuple[list[dict], list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("census root must be a regular directory")
    manifest_path = resolved / "census-manifest.json"
    manifest = _read_json(manifest_path, label="census manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="census manifest")
    marker = _regular(resolved / "PREPARED", label="census marker")
    if (
        manifest.get("schema_version") != CENSUS_SCHEMA_VERSION
        or manifest.get("status") != "PREPARED_NOT_EXECUTABLE"
        or manifest.get("execution_ready") is not False
        or marker.read_text(encoding="ascii").strip() != manifest_sha
    ):
        raise ValueError("census contract drift")
    starters = _output_identity(resolved, manifest, "held-actual-starter-census.jsonl")
    summaries = _output_identity(resolved, manifest, "target-summaries.jsonl")
    if (
        not starters
        or not summaries
        or any(row.get("schema_version") != STARTER_SCHEMA_VERSION for row in starters)
        or any(row.get("schema_version") != SUMMARY_SCHEMA_VERSION for row in summaries)
        or len(starters) != manifest.get("counts", {}).get("actual_starter_occurrences")
        or len(summaries) != manifest.get("counts", {}).get("held_targets")
    ):
        raise ValueError("census row conservation drift")
    return starters, summaries, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "starter_rows": len(starters),
        "target_rows": len(summaries),
        "target_artifact": manifest.get("target_artifact"),
    }


def load_seed_target_map(
    root: Path,
    *,
    approved_manifest_sha256: str,
    expected_target_keys: set[str],
) -> tuple[dict[str, str], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("seed proposal root must be a regular directory")
    manifest_path = resolved / "proposal-manifest.json"
    manifest = _read_json(manifest_path, label="seed proposal manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="seed proposal manifest")
    marker = _regular(resolved / "PREPARED", label="seed proposal marker")
    outputs = manifest.get("outputs")
    if (
        manifest.get("schema_version") != SEED_PROPOSAL_SCHEMA_VERSION
        or manifest.get("status") != "PREPARED_NOT_EXECUTABLE"
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(outputs, Mapping)
        or set(outputs) != SEED_OUTPUT_NAMES
    ):
        raise ValueError("seed proposal contract drift")
    bindings = _output_identity(resolved, manifest, "existing-seed-bindings.jsonl")
    candidates = _output_identity(resolved, manifest, "new-seed-candidates.jsonl")
    combined = _output_identity(resolved, manifest, "all-held-targeted-horse-seeds.jsonl")
    mapping: dict[str, str] = {}
    replaced_seed_ids: set[str] = set()
    replacement_seed_ids: set[str] = set()
    for row in bindings:
        seed_id = str(row.get("seed_id") or "")
        target_key = str(row.get("target_key") or "")
        disposition = row.get("disposition")
        if not seed_id or not target_key:
            raise ValueError("existing seed binding row drift")
        if disposition == "reuse_existing_complete_seed":
            mapped_seed_id = seed_id
        elif disposition == "replace_conflicting_existing_seed":
            mapped_seed_id = str(row.get("replacement_seed_id") or "")
            if (
                not mapped_seed_id
                or mapped_seed_id == seed_id
                or not SHA256_RE.fullmatch(str(row.get("replacement_seed_sha256") or ""))
            ):
                raise ValueError("replacement seed binding row drift")
            replaced_seed_ids.add(seed_id)
            replacement_seed_ids.add(mapped_seed_id)
        else:
            raise ValueError("existing seed binding row drift")
        if mapped_seed_id in mapping:
            raise ValueError("seed ID is mapped to multiple targets")
        mapping[mapped_seed_id] = target_key
    seen_replacement_candidates: set[str] = set()
    for row in candidates:
        seed = row.get("seed")
        seed_id = str(seed.get("seed_id") or "") if isinstance(seed, Mapping) else ""
        target_key = str(row.get("target_key") or "")
        disposition = row.get("disposition")
        if not seed_id or not target_key:
            raise ValueError("new seed candidate mapping drift")
        if disposition == "replace_conflicting_existing_seed":
            if (
                seed_id not in replacement_seed_ids
                or mapping.get(seed_id) != target_key
                or str(row.get("replaced_seed_id") or "") not in replaced_seed_ids
                or not SHA256_RE.fullmatch(str(row.get("replaced_seed_sha256") or ""))
            ):
                raise ValueError("replacement seed candidate mapping drift")
            seen_replacement_candidates.add(seed_id)
        elif disposition == "add_missing_organizer_official_seed":
            if seed_id in mapping:
                raise ValueError("new seed candidate mapping drift")
            mapping[seed_id] = target_key
        else:
            raise ValueError("new seed candidate mapping drift")
    combined_ids = {str(row.get("seed_id") or "") for row in combined}
    if (
        "" in combined_ids
        or seen_replacement_candidates != replacement_seed_ids
        or combined_ids.intersection(replaced_seed_ids)
        or combined_ids != set(mapping)
        or set(mapping.values()) != expected_target_keys
        or len(mapping) != len(expected_target_keys)
    ):
        raise ValueError("seed-to-target conservation drift")
    return mapping, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "seed_rows": len(mapping),
        "outputs": {
            name: {
                "sha256": outputs[name]["sha256"],
                "rows": outputs[name]["rows"],
            }
            for name in sorted(SEED_OUTPUT_NAMES)
        },
    }


def load_approved_seed_artifact(
    root: Path,
    *,
    approved_manifest_sha256: str,
    approved_ledger_sha256: str,
    target_identity: Mapping[str, object],
    proposal_identity: Mapping[str, object],
    expected_seed_ids: set[str],
) -> tuple[dict[str, dict], dict]:
    seeds, identity = load_existing_seed_artifact(
        root,
        approved_manifest_sha256=approved_manifest_sha256,
        approved_ledger_sha256=approved_ledger_sha256,
        target_identity=target_identity,
    )
    manifest = _read_json(root.resolve(strict=True) / "seed-ledger-manifest.json", label="approved seed manifest")
    approval = manifest.get("held_winner_seed_extension_approval")
    proposal_outputs = proposal_identity.get("outputs")
    if not isinstance(approval, Mapping) or not isinstance(proposal_outputs, Mapping):
        raise ValueError("approved seed artifact is not bound to held seed extension approval")
    try:
        approved_proposal_root = Path(str(approval.get("proposal_root") or "")).resolve(strict=True)
        expected_proposal_root = Path(str(proposal_identity.get("root") or "")).resolve(strict=True)
    except OSError as exc:
        raise ValueError("approved seed proposal root is unavailable") from exc
    approved_outputs = approval.get("approved_outputs")
    if (
        approved_proposal_root != expected_proposal_root
        or approval.get("proposal_manifest_sha256") != proposal_identity.get("manifest_sha256")
        or not isinstance(approved_outputs, Mapping)
        or {
            name: approved_outputs.get(name)
            for name in sorted(SEED_OUTPUT_NAMES)
        }
        != {
            name: proposal_outputs[name]["sha256"]
            for name in sorted(SEED_OUTPUT_NAMES)
        }
        or not SHA256_RE.fullmatch(str(approval.get("decision_sha256") or ""))
        or approval.get("independence_acknowledgement")
        != "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR"
        or set(seeds) != expected_seed_ids
    ):
        raise ValueError("approved seed artifact does not bind the exact held seed proposal and seed set")
    return seeds, {
        **identity,
        "held_seed_proposal_manifest_sha256": proposal_identity.get("manifest_sha256"),
        "decision_sha256": approval["decision_sha256"],
        "independence_acknowledgement": approval["independence_acknowledgement"],
    }


def load_stable_runner_ledger(
    root: Path,
    *,
    approved_manifest_sha256: str,
) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("stable runner ledger root must be a regular directory")
    manifest_path = resolved / "manifest.json"
    manifest = _read_json(manifest_path, label="stable runner manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="stable runner manifest")
    marker = _regular(resolved / "COMPLETE", label="stable runner marker")
    identity = manifest.get("seed_ledger")
    source_bulk_run = manifest.get("source_bulk_run")
    source_route = manifest.get("source_route")
    if (
        manifest.get("schema_version") not in STABLE_LEDGER_SEED_SCHEMAS
        or manifest.get("status") != "complete"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(identity, Mapping)
        or (
            source_route == "bulk_results"
            and (
                not isinstance(source_bulk_run, Mapping)
                or not SHA256_RE.fullmatch(
                    str(source_bulk_run.get("manifest_sha256") or "")
                )
                or not SHA256_RE.fullmatch(
                    str(source_bulk_run.get("normalized_sha256") or "")
                )
                or not str(source_bulk_run.get("root") or "")
                or not str(source_bulk_run.get("batch_id") or "")
            )
        )
        or source_route not in {None, "bulk_results"}
    ):
        raise ValueError("stable runner ledger contract drift")
    ledger_path = _regular(resolved / str(identity.get("path") or ""), label="stable runner ledger")
    rows = _read_jsonl(ledger_path, label="stable runner ledger")
    if (
        sha256_path(ledger_path) != identity.get("sha256")
        or ledger_path.stat().st_size != identity.get("size")
        or len(rows) != identity.get("rows")
        or any(
            row.get("schema_version")
            != STABLE_LEDGER_SEED_SCHEMAS[manifest["schema_version"]]
            for row in rows
        )
    ):
        raise ValueError("stable runner ledger identity drift")
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "schema_version": manifest["schema_version"],
        "stable_horse_rows": len(rows),
        "source_target_occurrence_count": manifest.get("source_target_occurrence_count"),
        "unique_target_race_count": manifest.get("unique_target_race_count"),
        "source_route": source_route,
        "source_bulk_run": dict(source_bulk_run) if isinstance(source_bulk_run, Mapping) else None,
    }


def _recall_key(value: object) -> str:
    name, _country = _split_country(value)
    return _normalize_name(name)


def _validate_tra_occurrence(
    occurrence: Mapping[str, object],
    summary: Mapping[str, object],
) -> None:
    target = occurrence.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("TRA occurrence target is missing")
    if (
        target.get("country_region") != summary.get("country_region")
        or target.get("local_date") != summary.get("local_date")
        or target.get("grade_text") != summary.get("grade")
        or target.get("discipline") != summary.get("discipline")
    ):
        raise ValueError("TRA occurrence disagrees with expected target summary")
    if runner_disposition(occurrence.get("source_runner_position")) in {"non_runner", "unresolved"}:
        raise ValueError("stable runner ledger contains non-runner or unresolved occurrence")


def build_proposal(
    *,
    census_rows: list[dict],
    census_summaries: list[dict],
    census_identity: dict,
    seed_to_target: Mapping[str, str],
    seed_identity: dict,
    approved_seed_identity: dict,
    stable_rows: list[dict],
    stable_identity: dict,
    output_dir: Path,
    stable_scope_only: bool = False,
) -> dict:
    if output_dir.exists():
        raise ValueError("output directory must not already exist")
    if not isinstance(stable_scope_only, bool):
        raise ValueError("stable_scope_only must be a boolean")
    stable_seed_ids = {
        str(occurrence.get("source_targeted_seed_id") or "")
        for stable in stable_rows
        for occurrence in stable.get("target_occurrences", [])
        if isinstance(occurrence, Mapping)
    }
    if "" in stable_seed_ids or not stable_seed_ids:
        raise ValueError("stable runner scope has missing source seed identities")
    missing_seed_ids = stable_seed_ids - set(seed_to_target)
    if missing_seed_ids:
        raise ValueError("stable occurrence seed is outside approved held target map")
    selected_target_keys = {seed_to_target[seed_id] for seed_id in stable_seed_ids}
    if stable_scope_only:
        census_rows = [
            row for row in census_rows if str(row.get("target_key") or "") in selected_target_keys
        ]
        census_summaries = [
            row
            for row in census_summaries
            if str(row.get("target_key") or "") in selected_target_keys
        ]
        if not census_rows or not census_summaries:
            raise ValueError("stable scope selects no held census rows")
    output_dir.mkdir(parents=True, mode=0o700)
    expected_by_target: dict[str, list[dict]] = defaultdict(list)
    for row in census_rows:
        if row.get("provider_horse_id") is not None:
            raise ValueError("input census already contains a provider horse ID")
        expected_by_target[str(row.get("target_key") or "")].append(row)
    summaries = {str(row.get("target_key") or ""): row for row in census_summaries}
    if "" in summaries or set(summaries) != set(expected_by_target):
        raise ValueError("census target summaries drift")

    tra_by_target: dict[str, list[dict]] = defaultdict(list)
    seen_target_horse_ids = set()
    for stable in stable_rows:
        horse_id = str(stable.get("horse_id") or "")
        occurrences = stable.get("target_occurrences")
        if not HORSE_ID_RE.fullmatch(horse_id) or not isinstance(occurrences, list) or not occurrences:
            raise ValueError("stable horse row is invalid")
        for occurrence in occurrences:
            if not isinstance(occurrence, Mapping):
                raise ValueError("stable horse occurrence is invalid")
            seed_id = str(occurrence.get("source_targeted_seed_id") or "")
            target_key = seed_to_target.get(seed_id)
            if target_key is None:
                raise ValueError("stable occurrence seed is outside approved held target map")
            _validate_tra_occurrence(occurrence, summaries[target_key])
            identity = (target_key, horse_id)
            if identity in seen_target_horse_ids:
                raise ValueError("TRA horse is duplicated within one target")
            seen_target_horse_ids.add(identity)
            tra_by_target[target_key].append(
                {
                    "horse_id": horse_id,
                    "race_id": occurrence["race_id"],
                    "source_runner_name": occurrence["source_runner_name"],
                    "source_runner_position": occurrence["source_runner_position"],
                    "source_runner_payload_sha256": occurrence["source_runner_payload_sha256"],
                    "source_materialized_run_manifest_sha256": occurrence[
                        "source_materialized_run_manifest_sha256"
                    ],
                    "source_targeted_seed_id": seed_id,
                }
            )
    if set(tra_by_target) - set(expected_by_target):
        raise ValueError("stable runner ledger contains an unexpected target")

    bindings = []
    review_items = []
    target_reports = []
    for target_key in sorted(expected_by_target):
        expected = expected_by_target[target_key]
        observed = tra_by_target.get(target_key, [])
        expected_by_name: dict[str, list[dict]] = defaultdict(list)
        observed_by_name: dict[str, list[dict]] = defaultdict(list)
        for row in expected:
            expected_by_name[_recall_key(row.get("horse_name"))].append(row)
        for row in observed:
            observed_by_name[_recall_key(row.get("source_runner_name"))].append(row)
        matched_expected = set()
        matched_observed = set()
        for recall_key in sorted(set(expected_by_name) | set(observed_by_name)):
            expected_group = expected_by_name.get(recall_key, [])
            observed_group = observed_by_name.get(recall_key, [])
            if recall_key and len(expected_group) == 1 and len(observed_group) == 1:
                source_row = expected_group[0]
                tra_row = observed_group[0]
                matched_expected.add(source_row["starter_occurrence_key"])
                matched_observed.add(tra_row["horse_id"])
                bindings.append(
                    {
                        "schema_version": BINDING_SCHEMA_VERSION,
                        "target_key": target_key,
                        "starter_occurrence_key": source_row["starter_occurrence_key"],
                        "source_runner_key": source_row["source_runner_key"],
                        "source_horse_name": source_row["horse_name"],
                        "source_payload_sha256": source_row["source_payload_sha256"],
                        "tra_horse_id": tra_row["horse_id"],
                        "tra_runner_name": tra_row["source_runner_name"],
                        "tra_runner_position": tra_row["source_runner_position"],
                        "tra_runner_payload_sha256": tra_row["source_runner_payload_sha256"],
                        "tra_race_id": tra_row["race_id"],
                        "recall_key": recall_key,
                        "binding_status": "unique_occurrence_name_candidate_requires_review",
                    }
                )
            elif expected_group or observed_group:
                review_items.append(
                    {
                        "schema_version": REVIEW_SCHEMA_VERSION,
                        "target_key": target_key,
                        "recall_key": recall_key,
                        "reason": (
                            "ambiguous_name_group"
                            if len(expected_group) > 1 or len(observed_group) > 1
                            else "source_or_tra_name_unmatched"
                        ),
                        "source_slots": [
                            {
                                "starter_occurrence_key": row["starter_occurrence_key"],
                                "horse_name": row["horse_name"],
                            }
                            for row in expected_group
                        ],
                        "tra_runners": [
                            {
                                "horse_id": row["horse_id"],
                                "runner_name": row["source_runner_name"],
                                "race_id": row["race_id"],
                            }
                            for row in observed_group
                        ],
                    }
                )
        unmatched_expected = len(expected) - len(matched_expected)
        unmatched_observed = len(observed) - len(matched_observed)
        target_reports.append(
            {
                "schema_version": TARGET_SUMMARY_SCHEMA_VERSION,
                "target_key": target_key,
                "expected_actual_starters": len(expected),
                "tra_actual_starters": len(observed),
                "unique_binding_candidates": len(expected) - unmatched_expected,
                "unmatched_or_ambiguous_source_slots": unmatched_expected,
                "unmatched_or_ambiguous_tra_runners": unmatched_observed,
                "count_conserved": len(expected) == len(observed),
                "reconciliation_complete": False,
            }
        )
    if len({row["starter_occurrence_key"] for row in bindings}) != len(bindings):
        raise ValueError("source starter slot is bound more than once")
    if len({(row["target_key"], row["tra_horse_id"]) for row in bindings}) != len(bindings):
        raise ValueError("TRA runner is bound more than once within a target")
    identities = {
        "binding-candidates.jsonl": _write_jsonl(output_dir / "binding-candidates.jsonl", bindings),
        "review-items.jsonl": _write_jsonl(output_dir / "review-items.jsonl", review_items),
        "target-summaries.jsonl": _write_jsonl(output_dir / "target-summaries.jsonl", target_reports),
    }
    count_mismatches = sum(not row["count_conserved"] for row in target_reports)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PREPARED_NOT_EXECUTABLE",
        "execution_ready": False,
        "approval": False,
        "network_requests": 0,
        "database_writes": 0,
        "generator": {"path": Path(__file__).name, "sha256": sha256_path(Path(__file__).resolve())},
        "census": census_identity,
        "held_seed_proposal": seed_identity,
        "approved_held_seed_artifact": approved_seed_identity,
        "stable_runner_ledger": stable_identity,
        "scope": {
            "mode": "stable_occurrence_seed_intersection" if stable_scope_only else "full_census",
            "source_targeted_seed_ids": sorted(stable_seed_ids),
            "target_keys": sorted(selected_target_keys),
        },
        "counts": {
            "targets": len(target_reports),
            "expected_actual_starter_slots": len(census_rows),
            "tra_actual_starter_occurrences": sum(len(rows) for rows in tra_by_target.values()),
            "unique_binding_candidates": len(bindings),
            "review_items": len(review_items),
            "targets_with_count_mismatch": count_mismatches,
            "source_slots_unmatched_or_ambiguous": sum(
                row["unmatched_or_ambiguous_source_slots"] for row in target_reports
            ),
            "tra_runners_unmatched_or_ambiguous": sum(
                row["unmatched_or_ambiguous_tra_runners"] for row in target_reports
            ),
        },
        "binding_contract": {
            "name_is_recall_only": True,
            "binding_candidates_are_not_approved_identities": True,
            "cross_target_name_merge": False,
            "required_for_complete": [
                "target count conservation",
                "zero unmatched or ambiguous source slots",
                "zero unmatched or ambiguous TRA runners",
                "independent exact-SHA identity review",
            ],
        },
        "outputs": identities,
        "execution_blockers": [
            "candidate bindings require independent identity review",
            "PREPARED reconciliation cannot write staging or canonical horse identity",
        ],
        "completion_marker": "PREPARED",
    }
    manifest_path = output_dir / "proposal-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census-root", type=Path, required=True)
    parser.add_argument("--approved-census-manifest-sha256", required=True)
    parser.add_argument("--held-seed-proposal-root", type=Path, required=True)
    parser.add_argument("--approved-held-seed-proposal-manifest-sha256", required=True)
    parser.add_argument("--approved-held-seed-root", type=Path, required=True)
    parser.add_argument("--approved-held-seed-manifest-sha256", required=True)
    parser.add_argument("--approved-held-seed-ledger-sha256", required=True)
    parser.add_argument("--stable-runner-ledger-root", type=Path, required=True)
    parser.add_argument("--approved-stable-runner-manifest-sha256", required=True)
    parser.add_argument(
        "--stable-scope-only",
        action="store_true",
        help="Reconcile only held targets referenced by the exact stable runner ledger.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    census_rows, summaries, census_identity = load_census(
        args.census_root,
        approved_manifest_sha256=args.approved_census_manifest_sha256,
    )
    target_keys = {str(row["target_key"]) for row in summaries}
    seed_map, seed_identity = load_seed_target_map(
        args.held_seed_proposal_root,
        approved_manifest_sha256=args.approved_held_seed_proposal_manifest_sha256,
        expected_target_keys=target_keys,
    )
    target_identity = census_identity.get("target_artifact")
    if not isinstance(target_identity, Mapping):
        raise ValueError("census target artifact identity is missing")
    _approved_seeds, approved_seed_identity = load_approved_seed_artifact(
        args.approved_held_seed_root,
        approved_manifest_sha256=args.approved_held_seed_manifest_sha256,
        approved_ledger_sha256=args.approved_held_seed_ledger_sha256,
        target_identity=target_identity,
        proposal_identity=seed_identity,
        expected_seed_ids=set(seed_map),
    )
    stable_rows, stable_identity = load_stable_runner_ledger(
        args.stable_runner_ledger_root,
        approved_manifest_sha256=args.approved_stable_runner_manifest_sha256,
    )
    manifest = build_proposal(
        census_rows=census_rows,
        census_summaries=summaries,
        census_identity=census_identity,
        seed_to_target=seed_map,
        seed_identity=seed_identity,
        approved_seed_identity=approved_seed_identity,
        stable_rows=stable_rows,
        stable_identity=stable_identity,
        output_dir=args.output_dir,
        stable_scope_only=args.stable_scope_only,
    )
    print(canonical_json(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
