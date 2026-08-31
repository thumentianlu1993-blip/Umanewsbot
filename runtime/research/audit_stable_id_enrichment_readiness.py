#!/usr/bin/env python3
"""Audit whether a stable-ID ledger can enter zero-search enrichment planning.

This report is deliberately non-executable.  It binds an immutable v1/v2 stable
runner ledger, immutable held-winner seed proposal/approval artifacts, and exact
prepared or approved external source censuses.  It calculates only a
conservative request budget.  It never publishes reconciliation approval or
accesses the network/database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


from prepare_external_result_actual_starter_census import (
    _load_stable_runner_ledger,
    load_proposal as load_external_census_proposal,
)
from prepare_held_winner_seed_extension import (
    SEED_MANIFEST_SCHEMA_VERSION,
    SEED_SCHEMA_VERSION,
    _read_json,
    _read_jsonl,
    _regular,
    canonical_json,
    sha256_path,
)


SCHEMA_VERSION = "stable-id-enrichment-readiness-audit.v1"
HELD_APPROVAL_DECISION_SCHEMA_VERSION = "held-winner-seed-extension-approval-decision.v1"
EXTERNAL_APPROVAL_SCHEMA_VERSION = "external-result-actual-starter-census-approval.v1"
EXTERNAL_APPROVAL_DECISION_SCHEMA_VERSION = (
    "external-result-actual-starter-census-approval-decision.v1"
)
EXTERNAL_APPROVED_BINDING_SCHEMA_VERSION = (
    "external-result-tra-runner-crosswalk-approved.v1"
)
INDEPENDENCE_ACKNOWLEDGEMENT = "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR"
HELD_APPROVAL_MEMBERS = {
    "COMPLETE",
    "approval-decision.json",
    "seed-ledger-manifest.json",
    "targeted-horse-seeds.jsonl",
}
EXTERNAL_APPROVAL_MEMBERS = {
    "COMPLETE",
    "approval-decision.json",
    "approval-manifest.json",
    "approved-census.jsonl",
    "approved-crosswalk.jsonl",
    "approved-target-summary.jsonl",
}


class StableEnrichmentReadinessError(ValueError):
    pass


def load_stable_runner_ledger(
    root: Path,
    *,
    approved_manifest_sha256: str,
) -> tuple[list[dict], dict]:
    """Compatibility wrapper around the dependency-light stable ledger loader."""

    return _load_stable_runner_ledger(
        root,
        expected_manifest_sha256=approved_manifest_sha256,
    )


def _planning_bucket(seed: Mapping[str, object]) -> tuple[str, int]:
    occurrences = seed.get("target_occurrences")
    if not isinstance(occurrences, list) or not occurrences:
        raise StableEnrichmentReadinessError("stable seed target occurrences are missing")
    targets = []
    for occurrence in occurrences:
        target = occurrence.get("target") if isinstance(occurrence, Mapping) else None
        if not isinstance(target, Mapping):
            raise StableEnrichmentReadinessError("stable seed target occurrence contract drift")
        region = str(target.get("country_region") or "")
        local_date = str(target.get("local_date") or "")
        try:
            year = int(target.get("year") or local_date[:4])
        except (TypeError, ValueError) as exc:
            raise StableEnrichmentReadinessError("stable seed target year is invalid") from exc
        if not region or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
            raise StableEnrichmentReadinessError("stable seed target region/date is invalid")
        targets.append((region, year, local_date, str(occurrence.get("race_id") or "")))
    first = sorted(targets)[0]
    return first[0], first[1]


def _load_held_seed_proposal(root: Path, approved_manifest_sha256: str) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise StableEnrichmentReadinessError("held seed proposal root must be a regular directory")
    manifest_path = _regular(resolved / "proposal-manifest.json", label="held seed proposal manifest")
    manifest = _read_json(manifest_path, label="held seed proposal manifest")
    manifest_sha = sha256_path(manifest_path)
    marker = _regular(resolved / "PREPARED", label="held seed proposal marker")
    outputs = manifest.get("outputs")
    if (
        manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != "held-winner-seed-extension-proposal.v1"
        or manifest.get("status") != "PREPARED_NOT_EXECUTABLE"
        or manifest.get("completion_marker") != "PREPARED"
        or not isinstance(outputs, Mapping)
    ):
        raise StableEnrichmentReadinessError("held seed proposal contract drift")
    identity = outputs.get("all-held-targeted-horse-seeds.jsonl")
    if not isinstance(identity, Mapping):
        raise StableEnrichmentReadinessError("held combined seed identity is missing")
    ledger_path = _regular(
        resolved / str(identity.get("path") or ""),
        label="held combined seed ledger",
    )
    rows = _read_jsonl(ledger_path, label="held combined seed ledger")
    if (
        sha256_path(ledger_path) != identity.get("sha256")
        or ledger_path.stat().st_size != identity.get("size")
        or len(rows) != identity.get("rows")
    ):
        raise StableEnrichmentReadinessError("held combined seed identity drift")
    seed_ids = [str(row.get("seed_id") or "") for row in rows]
    if "" in seed_ids or len(seed_ids) != len(set(seed_ids)):
        raise StableEnrichmentReadinessError("held seed IDs are invalid or duplicated")
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "combined_seed_ledger_sha256": identity["sha256"],
        "seed_rows": len(rows),
        "outputs": {
            name: {
                "sha256": output["sha256"],
                "rows": output["rows"],
            }
            for name, output in sorted(outputs.items())
            if isinstance(output, Mapping)
        },
        "status": manifest["status"],
        "approval": False,
    }


def _bound_rows(
    root: Path,
    identity: object,
    *,
    expected_path: str,
    label: str,
) -> list[dict]:
    if not isinstance(identity, Mapping) or identity.get("path") != expected_path:
        raise StableEnrichmentReadinessError(f"{label} identity is missing")
    path = _regular(root / expected_path, label=label)
    if not path.is_relative_to(root):
        raise StableEnrichmentReadinessError(f"{label} escapes approval root")
    rows = _read_jsonl(path, label=label)
    if (
        sha256_path(path) != identity.get("sha256")
        or path.stat().st_size != identity.get("size")
        or len(rows) != identity.get("rows")
    ):
        raise StableEnrichmentReadinessError(f"{label} identity drift")
    return rows


def _load_approved_held_seed(
    root: Path,
    *,
    approved_manifest_sha256: str,
    approved_ledger_sha256: str,
    proposal_identity: Mapping[str, object],
) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise StableEnrichmentReadinessError(
            "approved held seed root must be a regular directory"
        )
    if {path.name for path in resolved.iterdir()} != HELD_APPROVAL_MEMBERS:
        raise StableEnrichmentReadinessError(
            "approved held seed root contains missing or extra members"
        )
    manifest_path = _regular(
        resolved / "seed-ledger-manifest.json", label="approved held seed manifest"
    )
    manifest_sha = sha256_path(manifest_path)
    marker = _regular(resolved / "COMPLETE", label="approved held seed marker")
    manifest = _read_json(manifest_path, label="approved held seed manifest")
    ledger_identity = manifest.get("seed_ledger")
    approval = manifest.get("held_winner_seed_extension_approval")
    proposal_outputs = proposal_identity.get("outputs")
    if (
        manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != SEED_MANIFEST_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or not isinstance(ledger_identity, Mapping)
        or not isinstance(approval, Mapping)
        or not isinstance(proposal_outputs, Mapping)
    ):
        raise StableEnrichmentReadinessError("approved held seed contract drift")
    try:
        approved_proposal_root = Path(str(approval.get("proposal_root") or "")).resolve(
            strict=True
        )
        expected_proposal_root = Path(
            str(proposal_identity.get("root") or "")
        ).resolve(strict=True)
    except OSError as exc:
        raise StableEnrichmentReadinessError(
            "approved held seed proposal root is unavailable"
        ) from exc
    approved_outputs = approval.get("approved_outputs")
    if (
        approved_proposal_root != expected_proposal_root
        or approval.get("proposal_manifest_sha256")
        != proposal_identity.get("manifest_sha256")
        or not isinstance(approved_outputs, Mapping)
        or {
            name: approved_outputs.get(name)
            for name in sorted(proposal_outputs)
        }
        != {
            name: proposal_outputs[name].get("sha256")
            for name in sorted(proposal_outputs)
            if isinstance(proposal_outputs[name], Mapping)
        }
        or approval.get("independence_acknowledgement")
        != INDEPENDENCE_ACKNOWLEDGEMENT
    ):
        raise StableEnrichmentReadinessError(
            "approved held seed does not bind the exact proposal"
        )
    decision_path = _regular(
        resolved / "approval-decision.json", label="approved held seed decision"
    )
    decision_sha = sha256_path(decision_path)
    decision = _read_json(decision_path, label="approved held seed decision")
    if (
        decision_sha != approval.get("decision_sha256")
        or decision.get("schema_version") != HELD_APPROVAL_DECISION_SCHEMA_VERSION
        or decision.get("decision") != "approve"
        or decision.get("proposal_manifest_sha256")
        != proposal_identity.get("manifest_sha256")
        or decision.get("approved_outputs") != approved_outputs
        or decision.get("independence_acknowledgement")
        != INDEPENDENCE_ACKNOWLEDGEMENT
    ):
        raise StableEnrichmentReadinessError("approved held seed decision drift")
    rows = _bound_rows(
        resolved,
        ledger_identity,
        expected_path="targeted-horse-seeds.jsonl",
        label="approved held seed ledger",
    )
    ledger_sha = str(ledger_identity.get("sha256") or "")
    seed_ids = [str(row.get("seed_id") or "") for row in rows]
    if (
        ledger_sha != approved_ledger_sha256
        or ledger_sha != proposal_identity.get("combined_seed_ledger_sha256")
        or manifest.get("seed_count") != len(rows)
        or "" in seed_ids
        or len(seed_ids) != len(set(seed_ids))
        or any(row.get("schema_version") != SEED_SCHEMA_VERSION for row in rows)
    ):
        raise StableEnrichmentReadinessError("approved held seed ledger drift")
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "ledger_sha256": ledger_sha,
        "seed_rows": len(rows),
        "decision_sha256": decision_sha,
        "proposal_manifest_sha256": proposal_identity["manifest_sha256"],
        "status": manifest["status"],
        "approval": True,
    }


def _load_approved_external_census(
    root: Path,
    *,
    approved_manifest_sha256: str,
    stable_rows: list[dict],
    stable_identity: Mapping[str, object],
) -> tuple[set[str], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise StableEnrichmentReadinessError(
            "external census approval root must be a regular directory"
        )
    if {path.name for path in resolved.iterdir()} != EXTERNAL_APPROVAL_MEMBERS:
        raise StableEnrichmentReadinessError(
            "external census approval root contains missing or extra members"
        )
    manifest_path = _regular(
        resolved / "approval-manifest.json", label="external census approval manifest"
    )
    manifest_sha = sha256_path(manifest_path)
    marker = _regular(resolved / "COMPLETE", label="external census approval marker")
    manifest = _read_json(manifest_path, label="external census approval manifest")
    source = manifest.get("source_proposal")
    counts = manifest.get("counts")
    execution_authority = manifest.get("execution_authority")
    if (
        manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != EXTERNAL_APPROVAL_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("approval") is not True
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or not isinstance(source, Mapping)
        or not isinstance(counts, Mapping)
        or execution_authority
        != {
            "canonical_identity": False,
            "database_write": False,
            "production_registry_change": False,
            "profile_enrichment": False,
        }
    ):
        raise StableEnrichmentReadinessError("external census approval contract drift")
    proposal_root = Path(str(source.get("root") or ""))
    try:
        starters, candidate_crosswalk, proposal_identity = (
            load_external_census_proposal(
                proposal_root,
                expected_manifest_sha256=str(source.get("manifest_sha256") or ""),
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        raise StableEnrichmentReadinessError(
            "external census approval source proposal drift"
        ) from exc
    proposal_manifest = _read_json(
        proposal_root.resolve(strict=True) / "proposal-manifest.json",
        label="external census source proposal manifest",
    )
    proposal_outputs = proposal_manifest.get("outputs")
    approved_outputs = source.get("approved_outputs")
    seed_id = str(source.get("source_targeted_seed_id") or "")
    if (
        source.get("manifest_sha256") != proposal_identity.get("manifest_sha256")
        or source.get("target_key") != proposal_identity.get("target_key")
        or seed_id != proposal_identity.get("source_targeted_seed_id")
        or proposal_identity.get("stable_runner_manifest_sha256")
        != stable_identity.get("manifest_sha256")
        or not isinstance(proposal_outputs, Mapping)
        or not isinstance(approved_outputs, Mapping)
        or approved_outputs
        != {
            name: identity.get("sha256")
            for name, identity in sorted(proposal_outputs.items())
            if isinstance(identity, Mapping)
        }
    ):
        raise StableEnrichmentReadinessError(
            "external census approval does not bind the source proposal"
        )
    census_rows = _bound_rows(
        resolved,
        manifest.get("approved_census"),
        expected_path="approved-census.jsonl",
        label="approved external census",
    )
    crosswalk_rows = _bound_rows(
        resolved,
        manifest.get("approved_crosswalk"),
        expected_path="approved-crosswalk.jsonl",
        label="approved external crosswalk",
    )
    summary_rows = _bound_rows(
        resolved,
        manifest.get("approved_target_summary"),
        expected_path="approved-target-summary.jsonl",
        label="approved external target summary",
    )
    approved_census_identity = manifest.get("approved_census")
    approved_summary_identity = manifest.get("approved_target_summary")
    if (
        not isinstance(approved_census_identity, Mapping)
        or not isinstance(approved_summary_identity, Mapping)
        or approved_census_identity.get("sha256")
        != approved_outputs.get("actual-starter-census.jsonl")
        or approved_summary_identity.get("sha256")
        != approved_outputs.get("target-summary.jsonl")
        or [canonical_json(row) for row in census_rows]
        != [canonical_json(row) for row in starters]
    ):
        raise StableEnrichmentReadinessError(
            "external census approval differs from source proposal rows"
        )
    decision_identity = manifest.get("approval_decision")
    if not isinstance(decision_identity, Mapping):
        raise StableEnrichmentReadinessError(
            "external census approval decision identity is missing"
        )
    decision_path = _regular(
        resolved / "approval-decision.json", label="external census approval decision"
    )
    decision_sha = sha256_path(decision_path)
    decision = _read_json(decision_path, label="external census approval decision")
    if (
        decision_identity.get("path") != "approval-decision.json"
        or decision_identity.get("sha256") != decision_sha
        or decision_identity.get("size") != decision_path.stat().st_size
        or decision.get("schema_version") != EXTERNAL_APPROVAL_DECISION_SCHEMA_VERSION
        or decision.get("status") != "REVIEWED_APPROVED"
        or decision.get("decision") != "approve"
        or decision.get("proposal_manifest_sha256")
        != proposal_identity.get("manifest_sha256")
        or decision.get("approved_outputs") != approved_outputs
        or decision.get("independence_acknowledgement")
        != INDEPENDENCE_ACKNOWLEDGEMENT
        or decision.get("systematic_source_reuse_approved") is not False
        or decision.get("database_write_authorized") is not False
    ):
        raise StableEnrichmentReadinessError("external census approval decision drift")
    stable_occurrences = {}
    for stable in stable_rows:
        horse_id = str(stable.get("horse_id") or "")
        for occurrence in stable.get("target_occurrences", []):
            if (
                isinstance(occurrence, Mapping)
                and occurrence.get("source_targeted_seed_id") == seed_id
            ):
                if horse_id in stable_occurrences:
                    raise StableEnrichmentReadinessError(
                        "external census stable occurrence is duplicated"
                    )
                stable_occurrences[horse_id] = occurrence
    census_keys = {str(row.get("starter_occurrence_key") or "") for row in census_rows}
    approved_keys = {
        str(row.get("starter_occurrence_key") or "") for row in crosswalk_rows
    }
    approved_horse_ids = {str(row.get("tra_horse_id") or "") for row in crosswalk_rows}
    candidates_by_horse_id = {
        str(row.get("candidate_provider_horse_id") or ""): row
        for row in candidate_crosswalk
    }
    if (
        not census_rows
        or len(summary_rows) != 1
        or len(census_keys) != len(census_rows)
        or "" in census_keys
        or approved_keys != census_keys
        or "" in approved_horse_ids
        or len(approved_horse_ids) != len(crosswalk_rows)
        or approved_horse_ids != set(stable_occurrences)
        or len(starters) != len(census_rows)
        or counts.get("actual_starter_occurrences") != len(census_rows)
        or counts.get("approved_occurrence_bindings") != len(crosswalk_rows)
        or counts.get("unique_tra_horse_ids") != len(approved_horse_ids)
        or counts.get("unmatched_source_rows") != 0
        or counts.get("unmatched_tra_rows") != 0
    ):
        raise StableEnrichmentReadinessError(
            "external census approval row conservation drift"
        )
    for row in crosswalk_rows:
        horse_id = str(row.get("tra_horse_id") or "")
        occurrence = stable_occurrences.get(horse_id)
        candidate = candidates_by_horse_id.get(horse_id)
        if (
            not isinstance(occurrence, Mapping)
            or not isinstance(candidate, Mapping)
            or row.get("schema_version")
            != EXTERNAL_APPROVED_BINDING_SCHEMA_VERSION
            or row.get("status") != "approved_exact_occurrence_binding"
            or row.get("source_targeted_seed_id") != seed_id
            or row.get("stable_runner_manifest_sha256")
            != stable_identity.get("manifest_sha256")
            or row.get("approval_decision_sha256") != decision_sha
            or row.get("race_id") != occurrence.get("race_id")
            or row.get("source_runner_payload_sha256")
            != occurrence.get("source_runner_payload_sha256")
            or row.get("target_race_payload_sha256")
            != occurrence.get("target_race_payload_sha256")
            or any(
                row.get(field) != candidate.get(field)
                for field in (
                    "source_targeted_seed_id",
                    "horse_name",
                    "source_finish_position",
                    "tra_runner_name",
                    "tra_runner_country",
                    "tra_runner_finish_position",
                    "race_id",
                    "source_runner_payload_sha256",
                    "target_race_payload_sha256",
                    "capture_source_sha256",
                    "stable_runner_manifest_sha256",
                )
            )
        ):
            raise StableEnrichmentReadinessError(
                "external census approval crosswalk drift"
            )
    return {seed_id}, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "source_proposal_manifest_sha256": proposal_identity["manifest_sha256"],
        "source_targeted_seed_id": seed_id,
        "target_key": proposal_identity["target_key"],
        "stable_runner_manifest_sha256": stable_identity["manifest_sha256"],
        "starter_rows": len(census_rows),
        "approved_crosswalk_rows": len(crosswalk_rows),
        "approved_tra_horse_ids": sorted(approved_horse_ids),
        "decision_sha256": decision_sha,
        "status": manifest["status"],
        "approval": True,
    }


def build_readiness_audit(
    *,
    stable_runner_ledger_root: Path,
    approved_stable_runner_manifest_sha256: str,
    held_seed_proposal_root: Path,
    approved_held_seed_proposal_manifest_sha256: str,
    approved_held_seed_root: Path | None = None,
    approved_held_seed_manifest_sha256: str | None = None,
    approved_held_seed_ledger_sha256: str | None = None,
    external_census_proposals: list[tuple[Path, str]] | None = None,
    external_census_approvals: list[tuple[Path, str]] | None = None,
    batch_size_cap: int = 5,
    max_results_pages_per_horse: int = 201,
    max_parent_profiles: int = 2,
    min_interval_ms: int = 250,
    spacing_minutes: int = 30,
    audited_at: datetime | None = None,
) -> dict:
    values = (
        batch_size_cap,
        max_results_pages_per_horse,
        max_parent_profiles,
        min_interval_ms,
        spacing_minutes,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise StableEnrichmentReadinessError("readiness parameters must be integers")
    if (
        not 1 <= batch_size_cap <= 20
        or not 1 <= max_results_pages_per_horse <= 201
        or not 0 <= max_parent_profiles <= 2
        or min_interval_ms < 250
        or spacing_minutes < 5
    ):
        raise StableEnrichmentReadinessError("readiness parameters exceed safety bounds")
    stable_rows, stable_identity = load_stable_runner_ledger(
        stable_runner_ledger_root,
        approved_manifest_sha256=approved_stable_runner_manifest_sha256,
    )
    held_rows, held_identity = _load_held_seed_proposal(
        held_seed_proposal_root,
        approved_held_seed_proposal_manifest_sha256,
    )
    approved_held_values = (
        approved_held_seed_root,
        approved_held_seed_manifest_sha256,
        approved_held_seed_ledger_sha256,
    )
    if any(value is not None for value in approved_held_values) and not all(
        value is not None for value in approved_held_values
    ):
        raise StableEnrichmentReadinessError(
            "approved held seed root, manifest SHA and ledger SHA must be supplied together"
        )
    approved_held_identity = None
    approved_held_rows: list[dict] = []
    if approved_held_seed_root is not None:
        approved_held_rows, approved_held_identity = _load_approved_held_seed(
            approved_held_seed_root,
            approved_manifest_sha256=str(approved_held_seed_manifest_sha256),
            approved_ledger_sha256=str(approved_held_seed_ledger_sha256),
            proposal_identity=held_identity,
        )
        if {str(row.get("seed_id") or "") for row in approved_held_rows} != {
            str(row.get("seed_id") or "") for row in held_rows
        }:
            raise StableEnrichmentReadinessError(
                "approved held seed set differs from held proposal"
            )
    held_seed_ids = {str(row["seed_id"]) for row in held_rows}
    approved_held_artifact_seed_ids = {
        str(row["seed_id"]) for row in approved_held_rows
    }
    occurrence_seed_ids = {
        str(occurrence.get("source_targeted_seed_id") or "")
        for seed in stable_rows
        for occurrence in seed.get("target_occurrences", [])
        if isinstance(occurrence, Mapping)
    }
    if "" in occurrence_seed_ids:
        raise StableEnrichmentReadinessError("stable occurrence seed identity is missing")
    approved_held_seed_ids = occurrence_seed_ids & approved_held_artifact_seed_ids
    covered_seed_ids = sorted(occurrence_seed_ids & held_seed_ids)
    missing_seed_ids = sorted(occurrence_seed_ids - held_seed_ids)
    external_census_identities = []
    prepared_external_seed_ids = set()
    approved_external_census_identities = []
    approved_external_seed_ids = set()
    occurrence_rows_by_seed = Counter(
        str(occurrence.get("source_targeted_seed_id") or "")
        for seed in stable_rows
        for occurrence in seed.get("target_occurrences", [])
        if isinstance(occurrence, Mapping)
    )
    for root, expected_manifest_sha256 in external_census_proposals or []:
        try:
            _starters, _crosswalk, identity = load_external_census_proposal(
                root,
                expected_manifest_sha256=expected_manifest_sha256,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise StableEnrichmentReadinessError(
                "external census proposal contract drift"
            ) from exc
        seed_id = str(identity.get("source_targeted_seed_id") or "")
        if (
            seed_id not in occurrence_seed_ids
            or seed_id in held_seed_ids
            or seed_id in prepared_external_seed_ids
            or identity.get("stable_runner_manifest_sha256")
            != stable_identity.get("manifest_sha256")
            or identity.get("starter_rows") != occurrence_rows_by_seed[seed_id]
            or identity.get("candidate_crosswalk_rows") != occurrence_rows_by_seed[seed_id]
            or identity.get("approval") is not False
        ):
            raise StableEnrichmentReadinessError(
                "external census proposal does not bind one uncovered stable occurrence seed"
            )
        prepared_external_seed_ids.add(seed_id)
        external_census_identities.append(identity)
    for root, expected_manifest_sha256 in external_census_approvals or []:
        try:
            seed_ids, identity = _load_approved_external_census(
                root,
                approved_manifest_sha256=expected_manifest_sha256,
                stable_rows=stable_rows,
                stable_identity=stable_identity,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise StableEnrichmentReadinessError(
                "external census approval contract drift"
            ) from exc
        if (
            not seed_ids
            or not seed_ids <= occurrence_seed_ids
            or seed_ids & held_seed_ids
            or seed_ids & prepared_external_seed_ids
            or seed_ids & approved_external_seed_ids
            or any(occurrence_rows_by_seed[seed_id] != identity["starter_rows"] for seed_id in seed_ids)
        ):
            raise StableEnrichmentReadinessError(
                "external census approval does not bind uncovered stable occurrence seeds"
            )
        approved_external_seed_ids.update(seed_ids)
        approved_external_census_identities.append(identity)
    uncensused_seed_ids = sorted(
        occurrence_seed_ids
        - held_seed_ids
        - prepared_external_seed_ids
        - approved_external_seed_ids
    )
    approved_seed_ids = approved_held_seed_ids | approved_external_seed_ids
    unapproved_seed_ids = sorted(occurrence_seed_ids - approved_seed_ids)

    bucket_counts: Counter[tuple[str, int]] = Counter(
        _planning_bucket(seed) for seed in stable_rows
    )
    buckets = []
    total_batches = 0
    per_seed_ceiling = max_results_pages_per_horse + 2 + 2 * max_parent_profiles
    for (region, year), horse_count in sorted(bucket_counts.items()):
        batch_count = math.ceil(horse_count / batch_size_cap)
        total_batches += batch_count
        buckets.append(
            {
                "country_region": region,
                "year": year,
                "unique_horses": horse_count,
                "batch_count": batch_count,
                "request_ceiling": horse_count * per_seed_ceiling,
            }
        )
    if uncensused_seed_ids:
        status = "BLOCKED_SOURCE_CENSUS_AND_APPROVAL_GAPS"
    elif unapproved_seed_ids:
        status = (
            "BLOCKED_EXTERNAL_CENSUS_AND_APPROVAL_GAPS"
            if prepared_external_seed_ids
            else "BLOCKED_SOURCE_APPROVAL_GAPS"
        )
    else:
        status = "BLOCKED_APPROVED_RECONCILIATION_MISSING"
    now = audited_at or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "audited_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stable_runner_ledger": stable_identity,
        "held_seed_proposal": held_identity,
        "approved_held_seed_artifact": approved_held_identity,
        "prepared_external_census_proposals": external_census_identities,
        "approved_external_census_artifacts": approved_external_census_identities,
        "counts": {
            "unique_horses": len(stable_rows),
            "target_occurrence_rows": sum(
                len(seed.get("target_occurrences", [])) for seed in stable_rows
            ),
            "occurrence_seed_ids": len(occurrence_seed_ids),
            "held_covered_seed_ids": len(covered_seed_ids),
            "approved_held_seed_ids": len(approved_held_seed_ids),
            "missing_from_held_seed_ids": len(missing_seed_ids),
            "prepared_external_census_proposals": len(external_census_identities),
            "prepared_external_census_seed_ids": len(prepared_external_seed_ids),
            "approved_external_census_artifacts": len(
                approved_external_census_identities
            ),
            "approved_external_census_seed_ids": len(approved_external_seed_ids),
            "approved_occurrence_seed_ids": len(approved_seed_ids),
            "unapproved_occurrence_seed_ids": len(unapproved_seed_ids),
            "uncensused_occurrence_seed_ids": len(uncensused_seed_ids),
            "planned_batches_if_approved": total_batches,
            "request_ceiling_if_approved": len(stable_rows) * per_seed_ceiling,
            "schedule_span_minutes_if_approved": max(0, total_batches - 1) * spacing_minutes,
        },
        "held_covered_seed_ids": covered_seed_ids,
        "approved_held_seed_ids": sorted(approved_held_seed_ids),
        "missing_from_held_seed_ids": missing_seed_ids,
        "prepared_external_census_seed_ids": sorted(prepared_external_seed_ids),
        "approved_external_census_seed_ids": sorted(approved_external_seed_ids),
        "approved_occurrence_seed_ids": sorted(approved_seed_ids),
        "unapproved_occurrence_seed_ids": unapproved_seed_ids,
        "uncensused_occurrence_seed_ids": uncensused_seed_ids,
        "provisional_buckets": buckets,
        "parameters": {
            "batch_size_cap": batch_size_cap,
            "max_results_pages_per_horse": max_results_pages_per_horse,
            "max_parent_profiles": max_parent_profiles,
            "per_seed_request_ceiling": per_seed_ceiling,
            "min_interval_ms": min_interval_ms,
            "spacing_minutes": spacing_minutes,
            "max_concurrent_batches": 1,
            "search_requests_per_seed": 0,
        },
        "blockers": [
            *(
                ["held winner seed proposal has no independent COMPLETE approval"]
                if occurrence_seed_ids & held_seed_ids and approved_held_identity is None
                else []
            ),
            *(
                ["stable occurrences outside held seed/census scope require reviewed source census"]
                if uncensused_seed_ids
                else []
            ),
            *(
                [
                    "prepared external census and candidate hrs_* crosswalk require independent exact-SHA approval"
                ]
                if prepared_external_seed_ids
                else []
            ),
            "exact census-to-TRA reconciliation proposal and independent approval are missing",
            "each enrichment batch still requires fresh exclusive proof and exact G3",
        ],
        "scope_limit": "readiness_and_budget_only_not_execution_approval",
    }


def _markdown(report: Mapping[str, object]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# Stable-ID 零搜索 enrichment readiness",
            "",
            f"状态：`{report['status']}`；`execution_ready=false`。",
            "",
            f"- 唯一马：{counts['unique_horses']}；target occurrence：{counts['target_occurrence_rows']}。",
            f"- held seed 覆盖：{counts['held_covered_seed_ids']}/{counts['occurrence_seed_ids']}；缺失：{', '.join(report['missing_from_held_seed_ids']) or '无'}。",
            f"- 已批准 occurrence seed：{counts['approved_occurrence_seed_ids']}/{counts['occurrence_seed_ids']}；仍未批准：{', '.join(report['unapproved_occurrence_seed_ids']) or '无'}。",
            f"- 外部 census：已准备 {counts['prepared_external_census_seed_ids']}，已批准 {counts['approved_external_census_seed_ids']}；仍完全无 census：{', '.join(report['uncensused_occurrence_seed_ids']) or '无'}。",
            f"- 若全部审核通过，保守上限：{counts['planned_batches_if_approved']} 批 / {counts['request_ceiling_if_approved']} GET / 批间跨度 {counts['schedule_span_minutes_if_approved']} 分钟。",
            "- 该数字只是上限审计，不授权联网、reconciliation 或数据库写入。",
            "",
        ]
    )


def write_audit(report: Mapping[str, object], output_dir: Path) -> dict:
    parent = output_dir.parent.resolve(strict=True)
    if output_dir.exists() or output_dir.is_symlink():
        raise StableEnrichmentReadinessError("output directory must not already exist")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=parent))
    os.chmod(temporary, 0o700)
    try:
        report_path = temporary / "readiness-audit.json"
        markdown_path = temporary / "readiness-audit.md"
        report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
        markdown_path.write_text(_markdown(report), encoding="utf-8")
        os.chmod(report_path, 0o600)
        os.chmod(markdown_path, 0o600)
        report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
        marker = temporary / "AUDITED_BLOCKED"
        marker.write_text(report_sha + "\n", encoding="ascii")
        os.chmod(marker, 0o600)
        os.replace(temporary, output_dir)
    except Exception:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()
        raise
    return {
        "status": report["status"],
        "output_dir": str(output_dir.resolve()),
        "report_sha256": report_sha,
        "network_requests": 0,
        "database_writes": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-runner-ledger-root", type=Path, required=True)
    parser.add_argument("--approved-stable-runner-manifest-sha256", required=True)
    parser.add_argument("--held-seed-proposal-root", type=Path, required=True)
    parser.add_argument("--approved-held-seed-proposal-manifest-sha256", required=True)
    parser.add_argument("--approved-held-seed-root", type=Path)
    parser.add_argument("--approved-held-seed-manifest-sha256")
    parser.add_argument("--approved-held-seed-ledger-sha256")
    parser.add_argument("--external-census-proposal-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--expected-external-census-proposal-manifest-sha256",
        action="append",
        default=[],
    )
    parser.add_argument("--external-census-approval-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--expected-external-census-approval-manifest-sha256",
        action="append",
        default=[],
    )
    parser.add_argument("--batch-size-cap", type=int, default=5)
    parser.add_argument("--max-results-pages-per-horse", type=int, default=201)
    parser.add_argument("--max-parent-profiles", type=int, default=2)
    parser.add_argument("--min-interval-ms", type=int, default=250)
    parser.add_argument("--spacing-minutes", type=int, default=30)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir
    delattr(args, "output_dir")
    try:
        roots = args.external_census_proposal_root
        hashes = args.expected_external_census_proposal_manifest_sha256
        if len(roots) != len(hashes):
            raise StableEnrichmentReadinessError(
                "external census proposal roots and manifest hashes must pair exactly"
            )
        args.external_census_proposals = list(zip(roots, hashes, strict=True))
        delattr(args, "external_census_proposal_root")
        delattr(args, "expected_external_census_proposal_manifest_sha256")
        approval_roots = args.external_census_approval_root
        approval_hashes = args.expected_external_census_approval_manifest_sha256
        if len(approval_roots) != len(approval_hashes):
            raise StableEnrichmentReadinessError(
                "external census approval roots and manifest hashes must pair exactly"
            )
        args.external_census_approvals = list(
            zip(approval_roots, approval_hashes, strict=True)
        )
        delattr(args, "external_census_approval_root")
        delattr(args, "expected_external_census_approval_manifest_sha256")
        report = build_readiness_audit(**vars(args))
        summary = write_audit(report, output_dir)
    except (OSError, StableEnrichmentReadinessError, TypeError, ValueError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
