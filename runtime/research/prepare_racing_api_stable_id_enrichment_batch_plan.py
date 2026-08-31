#!/usr/bin/env python3
"""Prepare zero-search profile/career batches for approved stable TRA horse IDs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping


RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from prepare_held_census_tra_reconciliation import (  # noqa: E402
    BINDING_SCHEMA_VERSION,
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
from publish_held_census_tra_reconciliation_approval import (  # noqa: E402
    APPROVAL_SCHEMA_VERSION as RECONCILIATION_APPROVAL_SCHEMA_VERSION,
)
from build_bulk_target_runner_stable_id_ledger import (  # noqa: E402
    _load_complete_bulk_run,
)
from build_target_runner_stable_id_ledger import (  # noqa: E402
    _load_materialized_target_races,
)
from racing_api_targeted_batch_export import batch_request_ceiling  # noqa: E402


SCHEMA_VERSION = "racing-api-targeted-batch-plan.v1"
STABLE_SEED_SCHEMA_VERSIONS = {
    "targeted-runner-stable-id-seed.v1",
    "targeted-runner-stable-id-seed.v2",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
RECONCILIATION_COVERAGE_SCHEMA_VERSION = "stable-id-reconciliation-coverage.v1"
RECONCILIATION_COVERAGE_BINDING_SCHEMA_VERSION = (
    "stable-id-reconciliation-coverage-binding.v1"
)
RECONCILIATION_COVERAGE_MEMBERS = {
    "COMPLETE",
    "coverage-bindings.jsonl",
    "coverage-manifest.json",
}


def _stable_lineage_identities(
    stable_identity: Mapping[str, object],
) -> set[tuple[str, str]]:
    pending = [
        (
            Path(str(stable_identity.get("root") or "")),
            str(stable_identity.get("manifest_sha256") or ""),
        )
    ]
    output = set()
    while pending:
        root, manifest_sha = pending.pop()
        rows, identity = load_stable_runner_ledger(
            root,
            approved_manifest_sha256=manifest_sha,
        )
        del rows
        key = (identity["root"], identity["manifest_sha256"])
        if key in output:
            continue
        output.add(key)
        manifest = _read_json(
            Path(identity["root"]) / "manifest.json",
            label="stable lineage manifest",
        )
        sources = manifest.get("source_stable_ledgers")
        if sources is None:
            continue
        if not isinstance(sources, list):
            raise ValueError("stable lineage source identities drift")
        for source in sources:
            if not isinstance(source, Mapping):
                raise ValueError("stable lineage source identity is invalid")
            pending.append(
                (
                    Path(str(source.get("root") or "")),
                    str(source.get("manifest_sha256") or ""),
                )
            )
    return output


def _load_reconciliation_coverage(
    resolved: Path,
    manifest: Mapping[str, object],
    *,
    approved_manifest_sha256: str,
    stable_identity: Mapping[str, object],
    expected_horse_ids: set[str],
    expected_occurrence_keys: set[str],
) -> dict:
    if {path.name for path in resolved.iterdir()} != RECONCILIATION_COVERAGE_MEMBERS:
        raise ValueError("reconciliation coverage has missing or extra members")
    manifest_path = _regular(
        resolved / "coverage-manifest.json", label="reconciliation coverage manifest"
    )
    marker = _regular(resolved / "COMPLETE", label="reconciliation coverage marker")
    manifest_sha = sha256_path(manifest_path)
    stable = manifest.get("stable_runner_ledger")
    counts = manifest.get("counts")
    binding_identity = manifest.get("coverage_bindings")
    components = manifest.get("components")
    if (
        not SHA256_RE.fullmatch(approved_manifest_sha256)
        or manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != RECONCILIATION_COVERAGE_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("coverage_complete") is not True
        or manifest.get("planning_eligible") is not True
        or manifest.get("network_execution_authorized") is not False
        or manifest.get("database_write_authorized") is not False
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or not isinstance(stable, Mapping)
        or stable.get("root") != stable_identity.get("root")
        or stable.get("manifest_sha256") != stable_identity.get("manifest_sha256")
        or not isinstance(counts, Mapping)
        or counts.get("overlap_or_gap_count") != 0
        or not isinstance(binding_identity, Mapping)
        or binding_identity.get("path") != "coverage-bindings.jsonl"
        or not isinstance(components, list)
        or not components
    ):
        raise ValueError("approved reconciliation coverage contract drift")
    component_keys = []
    stable_lineage = None
    for component in components:
        if not isinstance(component, Mapping):
            raise ValueError("reconciliation coverage component is invalid")
        component_type = str(component.get("type") or "")
        expected_schema = {
            "held_census_reconciliation_approval": (
                "held-census-tra-reconciliation-approval.v1"
            ),
            "external_census_occurrence_approval": (
                "external-result-actual-starter-census-approval.v1"
            ),
        }.get(component_type)
        component_sha = str(component.get("manifest_sha256") or "")
        try:
            component_root = Path(str(component.get("root") or "")).resolve(strict=True)
        except OSError as exc:
            raise ValueError("reconciliation coverage component root is unavailable") from exc
        if component_type == "provider_native_bulk_run":
            if stable_lineage is None:
                stable_lineage = _stable_lineage_identities(stable_identity)
            try:
                _bulk_manifest, _normalized, _targets, source_identity = (
                    _load_complete_bulk_run(
                        component_root,
                        approved_manifest_sha256=component_sha,
                    )
                )
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(
                    "reconciliation coverage bulk component identity drift"
                ) from exc
            source_stable = component.get("source_stable_runner_ledger")
            if not isinstance(source_stable, Mapping):
                raise ValueError(
                    "reconciliation coverage bulk component identity drift"
                )
            try:
                _source_rows, source_stable_identity = load_stable_runner_ledger(
                    Path(str(source_stable.get("root") or "")),
                    approved_manifest_sha256=str(
                        source_stable.get("manifest_sha256") or ""
                    ),
                )
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(
                    "reconciliation coverage bulk stable identity drift"
                ) from exc
            if (
                source_identity.get("root") != str(component_root)
                or source_identity.get("manifest_sha256") != component_sha
                or dict(source_stable) != source_stable_identity
                or (
                    source_stable_identity["root"],
                    source_stable_identity["manifest_sha256"],
                )
                not in stable_lineage
                or source_stable_identity.get("source_route") != "bulk_results"
                or source_stable_identity.get("source_bulk_run") != source_identity
            ):
                raise ValueError(
                    "reconciliation coverage bulk component identity drift"
                )
        elif component_type == "provider_native_targeted_materialization":
            if stable_lineage is None:
                stable_lineage = _stable_lineage_identities(stable_identity)
            try:
                materialization_manifest_path = _regular(
                    component_root / "materialization-manifest.json",
                    label="reconciliation coverage targeted materialization",
                )
                if sha256_path(materialization_manifest_path) != component_sha:
                    raise ValueError("targeted materialization SHA-256 mismatch")
                materialization, _materialized_rows = (
                    _load_materialized_target_races(
                        component_root,
                        approved_manifest_sha256=component_sha,
                    )
                )
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(
                    "reconciliation coverage targeted component identity drift"
                ) from exc
            source_materialization = {
                "path": str(component_root),
                "manifest_sha256": component_sha,
                "source_targeted_batch_manifest_sha256": materialization[
                    "source_batch_manifest_sha256"
                ],
            }
            source_stable = component.get("source_stable_runner_ledger")
            if not isinstance(source_stable, Mapping):
                raise ValueError(
                    "reconciliation coverage targeted stable identity drift"
                )
            try:
                _source_rows, source_stable_identity = load_stable_runner_ledger(
                    Path(str(source_stable.get("root") or "")),
                    approved_manifest_sha256=str(
                        source_stable.get("manifest_sha256") or ""
                    ),
                )
                source_stable_manifest = _read_json(
                    Path(source_stable_identity["root"]) / "manifest.json",
                    label="reconciliation coverage targeted source stable manifest",
                )
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(
                    "reconciliation coverage targeted stable identity drift"
                ) from exc
            if (
                dict(source_stable) != source_stable_identity
                or (
                    source_stable_identity["root"],
                    source_stable_identity["manifest_sha256"],
                )
                not in stable_lineage
                or source_stable_identity.get("source_route") is not None
                or source_stable_manifest.get("source_materialization")
                != source_materialization
                or component.get("source_targeted_batch_manifest_sha256")
                != materialization["source_batch_manifest_sha256"]
            ):
                raise ValueError(
                    "reconciliation coverage targeted component identity drift"
                )
        else:
            component_manifest = _regular(
                component_root / "approval-manifest.json",
                label="reconciliation coverage component manifest",
            )
            component_marker = _regular(
                component_root / "COMPLETE",
                label="reconciliation coverage component marker",
            )
            component_payload = _read_json(
                component_manifest,
                label="reconciliation coverage component manifest",
            )
            if (
                expected_schema is None
                or sha256_path(component_manifest) != component_sha
                or component_marker.read_text(encoding="ascii").strip()
                != component_sha
                or component_payload.get("schema_version") != expected_schema
                or component_payload.get("status") != "complete"
            ):
                raise ValueError(
                    "reconciliation coverage component identity drift"
                )
        component_keys.append((component_type, component_sha))
    if len(component_keys) != len(set(component_keys)):
        raise ValueError("reconciliation coverage component is duplicated")
    component_binding_counts = {
        (str(component.get("type") or ""), str(component.get("manifest_sha256") or "")):
        component.get("binding_rows")
        for component in components
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in component_binding_counts.values()
    ):
        raise ValueError("reconciliation coverage component binding count drift")
    binding_path = _regular(
        resolved / "coverage-bindings.jsonl",
        label="reconciliation coverage bindings",
    )
    bindings = _read_jsonl(binding_path, label="reconciliation coverage bindings")
    occurrence_keys = [str(row.get("occurrence_key") or "") for row in bindings]
    binding_horse_ids = {str(row.get("horse_id") or "") for row in bindings}
    observed_component_counts = Counter(
        (
            str(row.get("component_type") or ""),
            str(row.get("component_manifest_sha256") or ""),
        )
        for row in bindings
    )
    if (
        sha256_path(binding_path) != binding_identity.get("sha256")
        or binding_path.stat().st_size != binding_identity.get("size")
        or len(bindings) != binding_identity.get("rows")
        or len(bindings) != counts.get("covered_occurrences")
        or counts.get("stable_occurrences") != len(expected_occurrence_keys)
        or counts.get("stable_horses") != len(expected_horse_ids)
        or counts.get("unique_tra_horse_ids") != len(expected_horse_ids)
        or len(occurrence_keys) != len(set(occurrence_keys))
        or set(occurrence_keys) != expected_occurrence_keys
        or binding_horse_ids != expected_horse_ids
        or dict(observed_component_counts) != component_binding_counts
        or any(
            row.get("schema_version")
            != RECONCILIATION_COVERAGE_BINDING_SCHEMA_VERSION
            or not SHA256_RE.fullmatch(
                str(row.get("component_binding_sha256") or "")
            )
            or not SHA256_RE.fullmatch(
                str(row.get("stable_occurrence_sha256") or "")
            )
            or row.get("occurrence_key")
            != canonical_json(
                {
                    "horse_id": row.get("horse_id"),
                    "race_id": row.get("race_id"),
                    "source_targeted_seed_id": row.get("source_targeted_seed_id"),
                }
            )
            for row in bindings
        )
    ):
        raise ValueError("approved reconciliation coverage binding conservation drift")
    return {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "schema_version": RECONCILIATION_COVERAGE_SCHEMA_VERSION,
        "approved_binding_rows": len(bindings),
        "unique_tra_horse_ids": len(binding_horse_ids),
        "component_count": len(components),
    }


def _load_approved_reconciliation(
    root: Path,
    *,
    approved_manifest_sha256: str,
    stable_identity: Mapping[str, object],
    expected_horse_ids: set[str],
    expected_occurrence_keys: set[str] | None = None,
) -> dict:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("approved reconciliation root must be a regular directory")
    coverage_manifest_path = resolved / "coverage-manifest.json"
    if coverage_manifest_path.is_file() and not coverage_manifest_path.is_symlink():
        coverage_manifest = _read_json(
            coverage_manifest_path, label="reconciliation coverage manifest"
        )
        if coverage_manifest.get("schema_version") == RECONCILIATION_COVERAGE_SCHEMA_VERSION:
            if expected_occurrence_keys is None:
                raise ValueError("reconciliation coverage requires exact occurrence identities")
            return _load_reconciliation_coverage(
                resolved,
                coverage_manifest,
                approved_manifest_sha256=approved_manifest_sha256,
                stable_identity=stable_identity,
                expected_horse_ids=expected_horse_ids,
                expected_occurrence_keys=expected_occurrence_keys,
            )
    manifest_path = resolved / "approval-manifest.json"
    manifest = _read_json(manifest_path, label="reconciliation approval manifest")
    manifest_sha = sha256_path(manifest_path)
    marker = _regular(resolved / "COMPLETE", label="reconciliation COMPLETE marker")
    source = manifest.get("source_proposal")
    binding_identity = manifest.get("approved_bindings")
    counts = manifest.get("counts")
    decision = manifest.get("decision")
    decision_identity = manifest.get("approval_decision")
    if (
        not SHA256_RE.fullmatch(approved_manifest_sha256)
        or manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != RECONCILIATION_APPROVAL_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or not isinstance(source, Mapping)
        or not isinstance(binding_identity, Mapping)
        or not isinstance(counts, Mapping)
        or not isinstance(decision, Mapping)
        or not isinstance(decision_identity, Mapping)
        or counts.get("review_items") != 0
        or counts.get("count_mismatches") != 0
        or not SHA256_RE.fullmatch(str(decision.get("sha256") or ""))
        or not str(decision.get("reviewed_by") or "").strip()
        or not str(decision.get("reviewed_at") or "").strip()
        or not str(decision.get("decision_source_reference") or "").strip()
        or decision.get("independence_acknowledgement")
        != "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR"
    ):
        raise ValueError("approved reconciliation contract drift")
    decision_path = _regular(
        resolved / str(decision_identity.get("path") or ""),
        label="reconciliation approval decision",
    )
    if (
        sha256_path(decision_path) != decision_identity.get("sha256")
        or decision_path.stat().st_size != decision_identity.get("size")
        or decision_identity.get("sha256") != decision.get("sha256")
    ):
        raise ValueError("reconciliation approval decision identity drift")
    proposal_root = Path(str(source.get("root") or ""))
    proposal_manifest_path = _regular(
        proposal_root.resolve(strict=True) / "proposal-manifest.json",
        label="source reconciliation proposal manifest",
    )
    proposal_sha = sha256_path(proposal_manifest_path)
    if proposal_sha != source.get("manifest_sha256"):
        raise ValueError("source reconciliation proposal identity drift")
    proposal = _read_json(proposal_manifest_path, label="source reconciliation proposal manifest")
    proposal_stable = proposal.get("stable_runner_ledger")
    proposal_outputs = proposal.get("outputs")
    approved_outputs = source.get("approved_outputs")
    if (
        proposal.get("schema_version") != "held-census-tra-reconciliation-proposal.v1"
        or proposal.get("status") != "PREPARED_NOT_EXECUTABLE"
        or not isinstance(proposal_stable, Mapping)
        or proposal_stable.get("root") != stable_identity.get("root")
        or proposal_stable.get("manifest_sha256") != stable_identity.get("manifest_sha256")
        or not isinstance(proposal_outputs, Mapping)
        or not isinstance(approved_outputs, Mapping)
        or set(proposal_outputs)
        != {"binding-candidates.jsonl", "review-items.jsonl", "target-summaries.jsonl"}
        or set(approved_outputs) != set(proposal_outputs)
        or any(
            approved_outputs.get(name) != identity.get("sha256")
            for name, identity in proposal_outputs.items()
            if isinstance(identity, Mapping)
        )
    ):
        raise ValueError("approved reconciliation does not bind the exact stable runner ledger")
    binding_path = _regular(resolved / str(binding_identity.get("path") or ""), label="approved bindings")
    bindings = _read_jsonl(binding_path, label="approved bindings")
    binding_horse_ids = {str(row.get("tra_horse_id") or "") for row in bindings}
    slot_keys = [str(row.get("starter_occurrence_key") or "") for row in bindings]
    target_horses = [
        (str(row.get("target_key") or ""), str(row.get("tra_horse_id") or ""))
        for row in bindings
    ]
    if (
        sha256_path(binding_path) != binding_identity.get("sha256")
        or binding_path.stat().st_size != binding_identity.get("size")
        or len(bindings) != binding_identity.get("rows")
        or len(bindings) != counts.get("approved_starter_bindings")
        or len(expected_horse_ids) != counts.get("unique_tra_horse_ids")
        or binding_horse_ids != expected_horse_ids
        or "" in binding_horse_ids
        or "" in slot_keys
        or len(slot_keys) != len(set(slot_keys))
        or len(target_horses) != len(set(target_horses))
        or any(row.get("schema_version") != BINDING_SCHEMA_VERSION for row in bindings)
    ):
        raise ValueError("approved reconciliation binding conservation drift")
    return {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "approved_binding_rows": len(bindings),
        "unique_tra_horse_ids": len(binding_horse_ids),
        "source_proposal_manifest_sha256": proposal_sha,
    }


def _planning_bucket(seed: Mapping[str, object]) -> tuple[str, int]:
    occurrences = seed.get("target_occurrences")
    if not isinstance(occurrences, list) or not occurrences:
        raise ValueError("stable seed target occurrences are missing")
    targets = []
    for occurrence in occurrences:
        target = occurrence.get("target") if isinstance(occurrence, Mapping) else None
        if not isinstance(target, Mapping):
            raise ValueError("stable seed target occurrence contract drift")
        region = str(target.get("country_region") or "")
        local_date = str(target.get("local_date") or "")
        try:
            year = int(target.get("year") or local_date[:4])
        except (TypeError, ValueError) as exc:
            raise ValueError("stable seed target year is invalid") from exc
        if not region or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
            raise ValueError("stable seed target region/date is invalid")
        targets.append((region, year, local_date, str(occurrence.get("race_id") or "")))
    first = sorted(targets)[0]
    return first[0], first[1]


def prepare_batch_plan(
    *,
    stable_runner_ledger_root: Path,
    approved_stable_runner_manifest_sha256: str,
    approved_reconciliation_root: Path,
    approved_reconciliation_manifest_sha256: str,
    output_dir: Path,
    batch_size_cap: int = 5,
    max_results_pages_per_horse: int = 201,
    max_parent_profiles: int = 2,
    min_interval_ms: int = 250,
    spacing_minutes: int = 30,
) -> dict:
    integers = (
        batch_size_cap,
        max_results_pages_per_horse,
        max_parent_profiles,
        min_interval_ms,
        spacing_minutes,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in integers):
        raise ValueError("stable enrichment batch parameters must be integers")
    if (
        not 1 <= batch_size_cap <= 20
        or not 1 <= max_results_pages_per_horse <= 201
        or not 0 <= max_parent_profiles <= 2
        or min_interval_ms < 250
        or spacing_minutes < 5
    ):
        raise ValueError("stable enrichment batch parameters are outside safety bounds")
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("batch plan output directory must be absent or empty")
    stable_rows, stable_identity = load_stable_runner_ledger(
        stable_runner_ledger_root,
        approved_manifest_sha256=approved_stable_runner_manifest_sha256,
    )
    horse_ids = {str(row.get("horse_id") or "") for row in stable_rows}
    occurrence_keys = {
        canonical_json(
            {
                "horse_id": row.get("horse_id"),
                "race_id": occurrence.get("race_id"),
                "source_targeted_seed_id": occurrence.get("source_targeted_seed_id"),
            }
        )
        for row in stable_rows
        for occurrence in row.get("target_occurrences", [])
        if isinstance(occurrence, Mapping)
    }
    occurrence_count = sum(
        len(row.get("target_occurrences", [])) for row in stable_rows
    )
    if (
        "" in horse_ids
        or len(horse_ids) != len(stable_rows)
        or any(
            row.get("schema_version") not in STABLE_SEED_SCHEMA_VERSIONS
            or not HORSE_ID_RE.fullmatch(str(row.get("horse_id") or ""))
            for row in stable_rows
        )
        or len(occurrence_keys) != occurrence_count
    ):
        raise ValueError("stable runner seed identity drift")
    authority_identity = _load_approved_reconciliation(
        approved_reconciliation_root,
        approved_manifest_sha256=approved_reconciliation_manifest_sha256,
        stable_identity=stable_identity,
        expected_horse_ids=horse_ids,
        expected_occurrence_keys=occurrence_keys,
    )
    groups: dict[tuple[str, int], list[dict]] = {}
    for seed in sorted(stable_rows, key=lambda row: str(row["horse_id"])):
        groups.setdefault(_planning_bucket(seed), []).append(seed)
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output_dir.chmod(0o700)
    batches = []
    ordinal = 0
    max_search_candidates = 1
    for (region, year), seeds in sorted(groups.items()):
        for offset in range(0, len(seeds), batch_size_cap):
            ordinal += 1
            rows = seeds[offset : offset + batch_size_cap]
            filename = f"{ordinal:04d}-{region}-{year}-{offset // batch_size_cap + 1:02d}.jsonl"
            path = output_dir / "seed-ledgers" / filename
            body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
            _atomic_write(path, body)
            ceiling = batch_request_ceiling(
                rows,
                max_search_candidates=max_search_candidates,
                max_results_pages_per_horse=max_results_pages_per_horse,
                max_parent_profiles=max_parent_profiles,
            )
            batches.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "batch_id": filename.removesuffix(".jsonl"),
                    "ordinal": ordinal,
                    "country_region": region,
                    "edition_year": year,
                    "seed_count": len(rows),
                    "request_ceiling": ceiling,
                    "theoretical_min_duration_seconds": ceiling * min_interval_ms / 1000,
                    "not_before_offset_minutes": (ordinal - 1) * spacing_minutes,
                    "approval_status": "proposed_not_approved",
                    "seed_ledger": {
                        "path": str(path.relative_to(output_dir)),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "size": len(body),
                        "rows": len(rows),
                    },
                }
            )
    plan_path = output_dir / "batch-plan.jsonl"
    _atomic_write(plan_path, b"".join((canonical_json(row) + "\n").encode("utf-8") for row in batches))
    region_counts = Counter(_planning_bucket(seed)[0] for seed in stable_rows)
    per_seed_ceiling = max_results_pages_per_horse + 2 + 2 * max_parent_profiles
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROPOSED_NOT_APPROVED",
        "completion_marker": "PREPARED",
        "approval": False,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "seed_artifact": stable_identity,
        "stable_id_authority": authority_identity,
        "approved_reconciliation": authority_identity,
        "parameters": {
            "batch_size_cap": batch_size_cap,
            "max_search_candidates": max_search_candidates,
            "max_results_pages_per_horse": max_results_pages_per_horse,
            "max_parent_profiles": max_parent_profiles,
            "per_seed_request_ceiling": per_seed_ceiling,
            "min_interval_ms": min_interval_ms,
            "max_requests_per_second": 1000 / min_interval_ms,
            "spacing_minutes": spacing_minutes,
            "max_concurrent_batches": 1,
            "exclusive_account_proof_required_per_batch": True,
            "search_requests_per_seed": 0,
            "results_page_limit": 100,
            "results_skip_ceiling": 20000,
        },
        "counts": {
            "seeds": len(stable_rows),
            "batches": len(batches),
            "request_ceiling": sum(row["request_ceiling"] for row in batches),
            "theoretical_min_duration_seconds": sum(
                row["theoretical_min_duration_seconds"] for row in batches
            ),
            "schedule_span_minutes": (len(batches) - 1) * spacing_minutes,
            "by_planning_region": dict(sorted(region_counts.items())),
        },
        "batch_plan": {
            "path": plan_path.name,
            "sha256": sha256_path(plan_path),
            "size": plan_path.stat().st_size,
            "rows": len(batches),
        },
        "execution_blockers": [
            "each network batch requires fresh exclusive-account proof and exact G3 approval",
            "batch output remains artifact-only with database_writes=0",
            "any page ceiling, schema, career target, or provider identity drift safe-stops the batch",
        ],
    }
    manifest_path = output_dir / "batch-plan-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-runner-ledger-root", type=Path, required=True)
    parser.add_argument("--approved-stable-runner-manifest-sha256", required=True)
    parser.add_argument("--approved-reconciliation-root", type=Path, required=True)
    parser.add_argument("--approved-reconciliation-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size-cap", type=int, default=5)
    parser.add_argument("--max-results-pages-per-horse", type=int, default=201)
    parser.add_argument("--max-parent-profiles", type=int, default=2)
    parser.add_argument("--min-interval-ms", type=int, default=250)
    parser.add_argument("--spacing-minutes", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    manifest = prepare_batch_plan(**vars(parse_args()))
    print(canonical_json(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
