#!/usr/bin/env python3
"""Combine exact reconciliation authorities into one stable-ledger coverage receipt.

The receipt is deterministic and non-executable.  It accepts independently
approved held-census bindings, independently approved external single-race
crosswalks, provider-native COMPLETE bulk runs, and provider-native COMPLETE
targeted materializations.  It then proves that their union covers every target
occurrence in one immutable stable-runner ledger exactly once.  It performs no
network or database access and grants only eligibility for zero-search planning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping


RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from audit_stable_id_enrichment_readiness import (  # noqa: E402
    _load_approved_external_census,
)
from prepare_held_census_tra_reconciliation import (  # noqa: E402
    BINDING_SCHEMA_VERSION as HELD_BINDING_SCHEMA_VERSION,
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
from prepare_racing_api_stable_id_enrichment_batch_plan import (  # noqa: E402
    _load_approved_reconciliation,
)
from build_bulk_target_runner_stable_id_ledger import (  # noqa: E402
    _load_complete_bulk_run,
)
from build_target_runner_stable_id_ledger import (  # noqa: E402
    _load_materialized_target_races,
    _merge_occurrence_observations,
    _target_occurrence,
)
from racing_api_horse_export import runner_disposition  # noqa: E402


SCHEMA_VERSION = "stable-id-reconciliation-coverage.v1"
BINDING_SCHEMA_VERSION = "stable-id-reconciliation-coverage-binding.v1"
HELD_APPROVAL_SCHEMA_VERSION = "held-census-tra-reconciliation-approval.v1"
EXTERNAL_APPROVAL_SCHEMA_VERSION = "external-result-actual-starter-census-approval.v1"
EXTERNAL_BINDING_SCHEMA_VERSION = "external-result-tra-runner-crosswalk-approved.v1"
OUTPUT_NAME = "coverage-bindings.jsonl"
MEMBERS = {"COMPLETE", "coverage-manifest.json", OUTPUT_NAME}


class ReconciliationCoverageError(ValueError):
    pass


def occurrence_key(horse_id: str, occurrence: Mapping[str, object]) -> str:
    race_id = str(occurrence.get("race_id") or "")
    source_seed_id = str(occurrence.get("source_targeted_seed_id") or "")
    if not horse_id or not race_id or not source_seed_id:
        raise ReconciliationCoverageError("stable occurrence identity is incomplete")
    return canonical_json(
        {
            "horse_id": horse_id,
            "race_id": race_id,
            "source_targeted_seed_id": source_seed_id,
        }
    )


def _stable_occurrences(rows: list[dict]) -> dict[str, tuple[str, dict]]:
    output: dict[str, tuple[str, dict]] = {}
    for seed in rows:
        horse_id = str(seed.get("horse_id") or "")
        occurrences = seed.get("target_occurrences")
        if not horse_id or not isinstance(occurrences, list) or not occurrences:
            raise ReconciliationCoverageError("stable seed occurrence contract drift")
        for occurrence in occurrences:
            if not isinstance(occurrence, Mapping):
                raise ReconciliationCoverageError("stable occurrence must be an object")
            key = occurrence_key(horse_id, occurrence)
            if key in output:
                raise ReconciliationCoverageError("stable occurrence identity is duplicated")
            output[key] = (horse_id, dict(occurrence))
    return output


def _source_observations(occurrence: Mapping[str, object]) -> list[dict]:
    raw = occurrence.get("source_observations")
    if not isinstance(raw, list) or not raw:
        raise ReconciliationCoverageError(
            "provider-native targeted occurrence observations are missing"
        )
    observations = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise ReconciliationCoverageError(
                "provider-native targeted observation must be an object"
            )
        observation = {
            key: str(value.get(key) or "")
            for key in (
                "source_targeted_seed_id",
                "source_materialized_run_manifest_sha256",
                "source_runner_payload_sha256",
            )
        }
        if any(not item for item in observation.values()):
            raise ReconciliationCoverageError(
                "provider-native targeted observation identity is incomplete"
            )
        observations.append(observation)
    ordered = sorted(observations, key=canonical_json)
    if (
        len({canonical_json(value) for value in ordered}) != len(ordered)
        or any(occurrence.get(key) != value for key, value in ordered[0].items())
    ):
        raise ReconciliationCoverageError(
            "provider-native targeted observation ordering drift"
        )
    return ordered


def _targeted_semantic_occurrence(occurrence: Mapping[str, object]) -> dict:
    return {
        key: value
        for key, value in occurrence.items()
        if key
        not in {
            "source_targeted_seed_id",
            "source_materialized_run_manifest_sha256",
            "source_runner_payload_sha256",
            "source_observations",
        }
    }


def _targeted_physical_occurrences(
    rows: list[dict],
) -> dict[tuple[str, str], dict]:
    output = {}
    for seed in rows:
        horse_id = str(seed.get("horse_id") or "")
        occurrences = seed.get("target_occurrences")
        if not horse_id or not isinstance(occurrences, list):
            raise ReconciliationCoverageError(
                "provider-native targeted stable seed contract drift"
            )
        for occurrence in occurrences:
            if not isinstance(occurrence, Mapping):
                raise ReconciliationCoverageError(
                    "provider-native targeted occurrence must be an object"
                )
            _source_observations(occurrence)
            race_id = str(occurrence.get("race_id") or "")
            key = (horse_id, race_id)
            if not race_id or key in output:
                raise ReconciliationCoverageError(
                    "provider-native targeted physical occurrence is duplicated"
                )
            output[key] = dict(occurrence)
    return output


def _approval_manifest(
    root: Path,
    *,
    expected_manifest_sha256: str,
    expected_schema_version: str,
) -> tuple[Path, dict, str]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ReconciliationCoverageError("approval root must be a regular directory")
    manifest_path = _regular(resolved / "approval-manifest.json", label="approval manifest")
    marker = _regular(resolved / "COMPLETE", label="approval COMPLETE marker")
    manifest_sha = sha256_path(manifest_path)
    manifest = _read_json(manifest_path, label="approval manifest")
    if (
        manifest_sha != expected_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != expected_schema_version
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
    ):
        raise ReconciliationCoverageError("approval manifest contract drift")
    return resolved, manifest, manifest_sha


def _source_stable_identity(approval: Mapping[str, object]) -> dict:
    source = approval.get("source_proposal")
    if not isinstance(source, Mapping):
        raise ReconciliationCoverageError("held approval source proposal is missing")
    proposal_root = Path(str(source.get("root") or "")).resolve(strict=True)
    proposal_path = _regular(
        proposal_root / "proposal-manifest.json",
        label="held reconciliation source proposal",
    )
    proposal = _read_json(proposal_path, label="held reconciliation source proposal")
    stable = proposal.get("stable_runner_ledger")
    if (
        sha256_path(proposal_path) != source.get("manifest_sha256")
        or not isinstance(stable, Mapping)
    ):
        raise ReconciliationCoverageError("held approval source stable identity drift")
    return dict(stable)


def _merged_source_identities(root: Path, manifest_sha256: str) -> set[tuple[str, str]]:
    output = set()
    pending = [(root, manifest_sha256)]
    while pending:
        candidate_root, candidate_sha = pending.pop()
        resolved = candidate_root.resolve(strict=True)
        key = (str(resolved), candidate_sha)
        if key in output:
            continue
        manifest_path = _regular(resolved / "manifest.json", label="stable manifest")
        if sha256_path(manifest_path) != candidate_sha:
            raise ReconciliationCoverageError("stable manifest identity drift")
        manifest = _read_json(manifest_path, label="stable manifest")
        output.add(key)
        sources = manifest.get("source_stable_ledgers")
        if sources is None:
            continue
        if not isinstance(sources, list):
            raise ReconciliationCoverageError("merged stable source identities drift")
        for source in sources:
            if not isinstance(source, Mapping):
                raise ReconciliationCoverageError(
                    "merged stable source identity is invalid"
                )
            source_root = Path(str(source.get("root") or ""))
            source_sha = str(source.get("manifest_sha256") or "")
            if not source_sha:
                raise ReconciliationCoverageError("merged stable source SHA is missing")
            pending.append((source_root, source_sha))
    return output


def _held_component(
    root: Path,
    *,
    expected_manifest_sha256: str,
    allowed_stable_identities: set[tuple[str, str]],
    merged_occurrences: Mapping[str, tuple[str, dict]],
) -> tuple[list[dict], dict]:
    resolved, manifest, manifest_sha = _approval_manifest(
        root,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_schema_version=HELD_APPROVAL_SCHEMA_VERSION,
    )
    source_stable = _source_stable_identity(manifest)
    source_root = Path(str(source_stable.get("root") or ""))
    source_rows, source_identity = load_stable_runner_ledger(
        source_root,
        approved_manifest_sha256=str(source_stable.get("manifest_sha256") or ""),
    )
    stable_key = (source_identity["root"], source_identity["manifest_sha256"])
    if stable_key not in allowed_stable_identities:
        raise ReconciliationCoverageError(
            "held approval stable ledger is outside merged source lineage"
        )
    source_occurrences = _stable_occurrences(source_rows)
    _load_approved_reconciliation(
        resolved,
        approved_manifest_sha256=manifest_sha,
        stable_identity=source_identity,
        expected_horse_ids={str(row["horse_id"]) for row in source_rows},
    )
    binding_identity = manifest.get("approved_bindings")
    if not isinstance(binding_identity, Mapping):
        raise ReconciliationCoverageError("held approved binding identity is missing")
    binding_path = _regular(
        resolved / str(binding_identity.get("path") or ""),
        label="held approved bindings",
    )
    bindings = _read_jsonl(binding_path, label="held approved bindings")
    output = []
    seen = set()
    for binding in bindings:
        horse_id = str(binding.get("tra_horse_id") or "")
        race_id = str(binding.get("tra_race_id") or "")
        matches = [
            (key, occurrence)
            for key, (candidate_horse_id, occurrence) in source_occurrences.items()
            if candidate_horse_id == horse_id and occurrence.get("race_id") == race_id
        ]
        if binding.get("schema_version") != HELD_BINDING_SCHEMA_VERSION or len(matches) != 1:
            raise ReconciliationCoverageError("held approved binding stable occurrence drift")
        key, occurrence = matches[0]
        merged = merged_occurrences.get(key)
        if (
            merged is None
            or canonical_json(merged[1]) != canonical_json(occurrence)
            or key in seen
        ):
            raise ReconciliationCoverageError("held approved occurrence is absent or duplicated")
        seen.add(key)
        output.append(
            {
                "schema_version": BINDING_SCHEMA_VERSION,
                "occurrence_key": key,
                "horse_id": horse_id,
                "race_id": race_id,
                "source_targeted_seed_id": occurrence["source_targeted_seed_id"],
                "target_key": binding["target_key"],
                "starter_occurrence_key": binding["starter_occurrence_key"],
                "component_type": "held_census_reconciliation_approval",
                "component_manifest_sha256": manifest_sha,
                "component_binding_sha256": hashlib.sha256(
                    canonical_json(binding).encode("utf-8")
                ).hexdigest(),
                "stable_occurrence_sha256": hashlib.sha256(
                    canonical_json(occurrence).encode("utf-8")
                ).hexdigest(),
            }
        )
    if set(source_occurrences) != seen:
        raise ReconciliationCoverageError(
            "held reconciliation approval does not cover its source stable ledger"
        )
    return output, {
        "type": "held_census_reconciliation_approval",
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "source_stable_runner_ledger": source_identity,
        "binding_rows": len(bindings),
    }


def _external_component(
    root: Path,
    *,
    expected_manifest_sha256: str,
    merged_rows: list[dict],
    merged_identity: Mapping[str, object],
    merged_occurrences: Mapping[str, tuple[str, dict]],
) -> tuple[list[dict], dict]:
    resolved, manifest, manifest_sha = _approval_manifest(
        root,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_schema_version=EXTERNAL_APPROVAL_SCHEMA_VERSION,
    )
    seed_ids, validated = _load_approved_external_census(
        resolved,
        approved_manifest_sha256=manifest_sha,
        stable_rows=merged_rows,
        stable_identity=merged_identity,
    )
    binding_identity = manifest.get("approved_crosswalk")
    if not isinstance(binding_identity, Mapping):
        raise ReconciliationCoverageError("external approved crosswalk identity is missing")
    binding_path = _regular(
        resolved / str(binding_identity.get("path") or ""),
        label="external approved crosswalk",
    )
    bindings = _read_jsonl(binding_path, label="external approved crosswalk")
    output = []
    seen = set()
    for binding in bindings:
        horse_id = str(binding.get("tra_horse_id") or "")
        race_id = str(binding.get("race_id") or "")
        seed_id = str(binding.get("source_targeted_seed_id") or "")
        key = canonical_json(
            {
                "horse_id": horse_id,
                "race_id": race_id,
                "source_targeted_seed_id": seed_id,
            }
        )
        merged = merged_occurrences.get(key)
        if (
            binding.get("schema_version") != EXTERNAL_BINDING_SCHEMA_VERSION
            or seed_id not in seed_ids
            or merged is None
            or key in seen
        ):
            raise ReconciliationCoverageError("external approved occurrence drift")
        occurrence = merged[1]
        if (
            binding.get("source_runner_payload_sha256")
            != occurrence.get("source_runner_payload_sha256")
            or binding.get("target_race_payload_sha256")
            != occurrence.get("target_race_payload_sha256")
        ):
            raise ReconciliationCoverageError("external approved payload drift")
        seen.add(key)
        output.append(
            {
                "schema_version": BINDING_SCHEMA_VERSION,
                "occurrence_key": key,
                "horse_id": horse_id,
                "race_id": race_id,
                "source_targeted_seed_id": seed_id,
                "target_key": binding["target_key"],
                "starter_occurrence_key": binding["starter_occurrence_key"],
                "component_type": "external_census_occurrence_approval",
                "component_manifest_sha256": manifest_sha,
                "component_binding_sha256": hashlib.sha256(
                    canonical_json(binding).encode("utf-8")
                ).hexdigest(),
                "stable_occurrence_sha256": hashlib.sha256(
                    canonical_json(occurrence).encode("utf-8")
                ).hexdigest(),
            }
        )
    expected_keys = {
        key
        for key, (_horse_id, occurrence) in merged_occurrences.items()
        if occurrence.get("source_targeted_seed_id") in seed_ids
    }
    if expected_keys != seen:
        raise ReconciliationCoverageError(
            "external approval does not cover its stable source seed occurrences"
        )
    return output, {
        "type": "external_census_occurrence_approval",
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "source_targeted_seed_ids": sorted(seed_ids),
        "binding_rows": len(bindings),
        "decision_sha256": validated["decision_sha256"],
    }


def _bulk_component(
    root: Path,
    *,
    expected_manifest_sha256: str,
    allowed_stable_identities: set[tuple[str, str]],
    merged_occurrences: Mapping[str, tuple[str, dict]],
) -> tuple[list[dict], dict]:
    try:
        _manifest, normalized, _targets, source_identity = (
            _load_complete_bulk_run(
                root,
                approved_manifest_sha256=expected_manifest_sha256,
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ReconciliationCoverageError(str(exc)) from exc
    matching_sources = []
    for source_root, source_sha in sorted(allowed_stable_identities):
        source_rows, source_stable_identity = load_stable_runner_ledger(
            Path(source_root),
            approved_manifest_sha256=source_sha,
        )
        if (
            source_stable_identity.get("source_route") == "bulk_results"
            and source_stable_identity.get("source_bulk_run") == source_identity
        ):
            matching_sources.append((source_rows, source_stable_identity))
    if len(matching_sources) != 1:
        raise ReconciliationCoverageError(
            "bulk run must bind exactly one stable source ledger"
        )
    source_rows, source_stable_identity = matching_sources[0]
    source_occurrences = _stable_occurrences(source_rows)
    participants = normalized.get("participants")
    if not isinstance(participants, list):
        raise ReconciliationCoverageError("bulk normalized participants are missing")
    output = []
    seen = set()
    for participant in participants:
        if not isinstance(participant, Mapping):
            raise ReconciliationCoverageError("bulk participant is invalid")
        horse_id = str(participant.get("horse_id") or "")
        race_id = str(participant.get("race_id") or "")
        target_key = str(participant.get("target_key") or "")
        key = canonical_json(
            {
                "horse_id": horse_id,
                "race_id": race_id,
                "source_targeted_seed_id": target_key,
            }
        )
        source = source_occurrences.get(key)
        merged = merged_occurrences.get(key)
        if (
            source is None
            or merged is None
            or canonical_json(source[1]) != canonical_json(merged[1])
            or key in seen
        ):
            raise ReconciliationCoverageError(
                "bulk provider-native occurrence is absent or duplicated"
            )
        occurrence = source[1]
        seen.add(key)
        output.append(
            {
                "schema_version": BINDING_SCHEMA_VERSION,
                "occurrence_key": key,
                "horse_id": horse_id,
                "race_id": race_id,
                "source_targeted_seed_id": target_key,
                "target_key": target_key,
                "starter_occurrence_key": (
                    f"provider-native:{source_identity['batch_id']}:{race_id}:{horse_id}"
                ),
                "component_type": "provider_native_bulk_run",
                "component_manifest_sha256": source_identity[
                    "manifest_sha256"
                ],
                "component_binding_sha256": hashlib.sha256(
                    canonical_json(participant).encode("utf-8")
                ).hexdigest(),
                "stable_occurrence_sha256": hashlib.sha256(
                    canonical_json(occurrence).encode("utf-8")
                ).hexdigest(),
            }
        )
    if set(source_occurrences) != seen:
        raise ReconciliationCoverageError(
            "bulk run does not cover its exact stable source ledger"
        )
    return output, {
        "type": "provider_native_bulk_run",
        "root": source_identity["root"],
        "manifest_sha256": source_identity["manifest_sha256"],
        "source_stable_runner_ledger": source_stable_identity,
        "binding_rows": len(output),
    }


def _targeted_materialization_component(
    root: Path,
    *,
    expected_manifest_sha256: str,
    allowed_stable_identities: set[tuple[str, str]],
    merged_occurrences: Mapping[str, tuple[str, dict]],
) -> tuple[list[dict], dict]:
    try:
        resolved = root.resolve(strict=True)
        manifest_path = _regular(
            resolved / "materialization-manifest.json",
            label="targeted materialization manifest",
        )
        if sha256_path(manifest_path) != expected_manifest_sha256:
            raise ReconciliationCoverageError(
                "targeted materialization manifest SHA-256 mismatch"
            )
        manifest, materialized = _load_materialized_target_races(
            resolved,
            approved_manifest_sha256=expected_manifest_sha256,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ReconciliationCoverageError(str(exc)) from exc
    source_materialization = {
        "path": str(resolved),
        "manifest_sha256": expected_manifest_sha256,
        "source_targeted_batch_manifest_sha256": manifest[
            "source_batch_manifest_sha256"
        ],
    }
    matching_sources = []
    for source_root, source_sha in sorted(allowed_stable_identities):
        source_rows, source_stable_identity = load_stable_runner_ledger(
            Path(source_root),
            approved_manifest_sha256=source_sha,
        )
        source_manifest = _read_json(
            Path(source_stable_identity["root"]) / "manifest.json",
            label="targeted source stable manifest",
        )
        if (
            source_stable_identity.get("source_route") is None
            and source_manifest.get("source_materialization")
            == source_materialization
        ):
            matching_sources.append((source_rows, source_stable_identity))
    if len(matching_sources) != 1:
        raise ReconciliationCoverageError(
            "targeted materialization must bind exactly one stable source ledger"
        )
    source_rows, source_stable_identity = matching_sources[0]
    source_occurrences = _targeted_physical_occurrences(source_rows)
    merged_physical = {}
    for merged_key, (horse_id, occurrence) in merged_occurrences.items():
        if occurrence.get("source_observations") is None:
            continue
        _source_observations(occurrence)
        physical_key = (horse_id, str(occurrence.get("race_id") or ""))
        if not physical_key[1] or physical_key in merged_physical:
            raise ReconciliationCoverageError(
                "merged provider-native targeted occurrence is duplicated"
            )
        merged_physical[physical_key] = (merged_key, occurrence)
    expected_by_physical: dict[tuple[str, str], dict] = {}
    binding_payloads: dict[tuple[str, str], list[dict]] = {}
    output = []
    for seed_id, run_manifest_sha, target_race in materialized:
        starters = target_race.get("actual_starters")
        if not isinstance(starters, list) or not starters:
            raise ReconciliationCoverageError(
                "targeted materialization actual starters are missing"
            )
        for runner in starters:
            if (
                not isinstance(runner, Mapping)
                or runner_disposition(runner.get("position"))
                in {"non_runner", "unresolved"}
            ):
                raise ReconciliationCoverageError(
                    "targeted materialization participant is invalid"
                )
            horse_id = str(runner.get("horse_id") or "")
            expected_occurrence = _target_occurrence(
                seed_id=seed_id,
                run_manifest_sha256=run_manifest_sha,
                target_race=target_race,
                runner=runner,
            )
            race_id = expected_occurrence["race_id"]
            physical_key = (horse_id, race_id)
            existing = expected_by_physical.get(physical_key)
            if existing is not None:
                try:
                    expected_occurrence = _merge_occurrence_observations(
                        existing, expected_occurrence
                    )
                except ValueError as exc:
                    raise ReconciliationCoverageError(str(exc)) from exc
            expected_by_physical[physical_key] = expected_occurrence
            binding_payloads.setdefault(physical_key, []).append({
                "seed_id": seed_id,
                "run_manifest_sha256": run_manifest_sha,
                "horse_id": horse_id,
                "race_id": race_id,
                "runner": dict(runner),
            })

    owned = set()
    supported = set()
    for physical_key in sorted(expected_by_physical):
        horse_id, race_id = physical_key
        expected_occurrence = expected_by_physical[physical_key]
        source_occurrence = source_occurrences.get(physical_key)
        merged_row = merged_physical.get(physical_key)
        if source_occurrence is None or merged_row is None:
            raise ReconciliationCoverageError(
                "targeted provider-native occurrence is absent from stable lineage"
            )
        merged_key, merged_occurrence = merged_row
        expected_observations = {
            canonical_json(value) for value in _source_observations(expected_occurrence)
        }
        merged_observations = {
            canonical_json(value) for value in _source_observations(merged_occurrence)
        }
        if (
            canonical_json(source_occurrence) != canonical_json(expected_occurrence)
            or canonical_json(_targeted_semantic_occurrence(merged_occurrence))
            != canonical_json(_targeted_semantic_occurrence(expected_occurrence))
            or not expected_observations <= merged_observations
        ):
            raise ReconciliationCoverageError(
                "targeted provider-native occurrence evidence drift"
            )
        primary = canonical_json(_source_observations(merged_occurrence)[0])
        if primary not in expected_observations:
            supported.add(physical_key)
            continue
        owned.add(physical_key)
        primary_seed_id = str(merged_occurrence["source_targeted_seed_id"])
        binding_payload = {
            "materialization_manifest_sha256": expected_manifest_sha256,
            "observations": sorted(
                binding_payloads[physical_key], key=canonical_json
            ),
            "source_occurrence": source_occurrence,
        }
        output.append(
            {
                "schema_version": BINDING_SCHEMA_VERSION,
                "occurrence_key": merged_key,
                "horse_id": horse_id,
                "race_id": race_id,
                "source_targeted_seed_id": primary_seed_id,
                "target_key": primary_seed_id,
                "starter_occurrence_key": (
                    "provider-native-targeted:"
                    f"{expected_manifest_sha256}:{primary_seed_id}:{race_id}:{horse_id}"
                ),
                "component_type": "provider_native_targeted_materialization",
                "component_manifest_sha256": expected_manifest_sha256,
                "component_binding_sha256": hashlib.sha256(
                    canonical_json(binding_payload).encode("utf-8")
                ).hexdigest(),
                "stable_occurrence_sha256": hashlib.sha256(
                    canonical_json(merged_occurrence).encode("utf-8")
                ).hexdigest(),
            }
        )
    if set(source_occurrences) != set(expected_by_physical) or owned & supported:
        raise ReconciliationCoverageError(
            "targeted materialization does not cover its exact stable source ledger"
        )
    return output, {
        "type": "provider_native_targeted_materialization",
        "root": str(resolved),
        "manifest_sha256": expected_manifest_sha256,
        "source_targeted_batch_manifest_sha256": manifest[
            "source_batch_manifest_sha256"
        ],
        "source_stable_runner_ledger": source_stable_identity,
        "binding_rows": len(output),
        "supporting_occurrence_rows": len(supported),
        "source_occurrence_rows": len(source_occurrences),
    }


def build_coverage(
    *,
    stable_runner_ledger_root: Path,
    approved_stable_runner_manifest_sha256: str,
    held_approval_roots: list[Path],
    held_approval_manifest_sha256s: list[str],
    external_approval_roots: list[Path],
    external_approval_manifest_sha256s: list[str],
    output_dir: Path,
    provider_native_bulk_run_roots: list[Path] | None = None,
    provider_native_bulk_run_manifest_sha256s: list[str] | None = None,
    provider_native_targeted_materialization_roots: list[Path] | None = None,
    provider_native_targeted_materialization_manifest_sha256s: list[str]
    | None = None,
) -> dict:
    provider_native_bulk_run_roots = provider_native_bulk_run_roots or []
    provider_native_bulk_run_manifest_sha256s = (
        provider_native_bulk_run_manifest_sha256s or []
    )
    provider_native_targeted_materialization_roots = (
        provider_native_targeted_materialization_roots or []
    )
    provider_native_targeted_materialization_manifest_sha256s = (
        provider_native_targeted_materialization_manifest_sha256s or []
    )
    if (
        len(held_approval_roots) != len(held_approval_manifest_sha256s)
        or len(external_approval_roots) != len(external_approval_manifest_sha256s)
        or len(provider_native_bulk_run_roots)
        != len(provider_native_bulk_run_manifest_sha256s)
        or len(provider_native_targeted_materialization_roots)
        != len(provider_native_targeted_materialization_manifest_sha256s)
        or not (
            held_approval_roots
            or external_approval_roots
            or provider_native_bulk_run_roots
            or provider_native_targeted_materialization_roots
        )
    ):
        raise ReconciliationCoverageError(
            "coverage requires at least one paired authority component"
        )
    if output_dir.is_symlink() or output_dir.exists():
        raise ReconciliationCoverageError("coverage output directory must not already exist")
    merged_rows, merged_identity = load_stable_runner_ledger(
        stable_runner_ledger_root,
        approved_manifest_sha256=approved_stable_runner_manifest_sha256,
    )
    merged_occurrences = _stable_occurrences(merged_rows)
    allowed_stable_identities = _merged_source_identities(
        stable_runner_ledger_root,
        approved_stable_runner_manifest_sha256,
    )
    rows = []
    components = []
    for root, manifest_sha in zip(
        held_approval_roots, held_approval_manifest_sha256s, strict=True
    ):
        component_rows, identity = _held_component(
            root,
            expected_manifest_sha256=manifest_sha,
            allowed_stable_identities=allowed_stable_identities,
            merged_occurrences=merged_occurrences,
        )
        rows.extend(component_rows)
        components.append(identity)
    for root, manifest_sha in zip(
        provider_native_bulk_run_roots,
        provider_native_bulk_run_manifest_sha256s,
        strict=True,
    ):
        component_rows, identity = _bulk_component(
            root,
            expected_manifest_sha256=manifest_sha,
            allowed_stable_identities=allowed_stable_identities,
            merged_occurrences=merged_occurrences,
        )
        rows.extend(component_rows)
        components.append(identity)
    for root, manifest_sha in zip(
        provider_native_targeted_materialization_roots,
        provider_native_targeted_materialization_manifest_sha256s,
        strict=True,
    ):
        component_rows, identity = _targeted_materialization_component(
            root,
            expected_manifest_sha256=manifest_sha,
            allowed_stable_identities=allowed_stable_identities,
            merged_occurrences=merged_occurrences,
        )
        rows.extend(component_rows)
        components.append(identity)
    for root, manifest_sha in zip(
        external_approval_roots, external_approval_manifest_sha256s, strict=True
    ):
        component_rows, identity = _external_component(
            root,
            expected_manifest_sha256=manifest_sha,
            merged_rows=merged_rows,
            merged_identity=merged_identity,
            merged_occurrences=merged_occurrences,
        )
        rows.extend(component_rows)
        components.append(identity)
    row_keys = [str(row["occurrence_key"]) for row in rows]
    component_keys = [
        (str(component["type"]), str(component["manifest_sha256"]))
        for component in components
    ]
    if (
        len(row_keys) != len(set(row_keys))
        or set(row_keys) != set(merged_occurrences)
        or len(component_keys) != len(set(component_keys))
    ):
        raise ReconciliationCoverageError(
            "component approvals overlap or do not cover the exact stable ledger"
        )
    rows.sort(key=lambda row: row["occurrence_key"])
    components.sort(key=lambda value: (value["type"], value["manifest_sha256"]))
    output_dir.mkdir(parents=True, mode=0o700)
    output_dir.chmod(0o700)
    binding_path = output_dir / OUTPUT_NAME
    body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
    _atomic_write(binding_path, body)
    horse_ids = {str(row["horse_id"]) for row in rows}
    target_keys = {str(row["target_key"]) for row in rows}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "completion_marker": "COMPLETE",
        "coverage_complete": True,
        "planning_eligible": True,
        "network_execution_authorized": False,
        "database_write_authorized": False,
        "network_requests": 0,
        "database_writes": 0,
        "stable_runner_ledger": merged_identity,
        "components": components,
        "counts": {
            "components": len(components),
            "stable_horses": len(merged_rows),
            "stable_occurrences": len(merged_occurrences),
            "covered_occurrences": len(rows),
            "unique_tra_horse_ids": len(horse_ids),
            "covered_targets": len(target_keys),
            "overlap_or_gap_count": 0,
        },
        "coverage_bindings": {
            "path": binding_path.name,
            "rows": len(rows),
            "size": len(body),
            "sha256": sha256_path(binding_path),
        },
        "scope_limit": "zero_search_planning_eligibility_only_not_network_or_database_authority",
    }
    manifest_path = output_dir / "coverage-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    _atomic_write(output_dir / "COMPLETE", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-runner-ledger-root", type=Path, required=True)
    parser.add_argument("--approved-stable-runner-manifest-sha256", required=True)
    parser.add_argument("--held-approval-root", type=Path, action="append", default=[])
    parser.add_argument("--held-approval-manifest-sha256", action="append", default=[])
    parser.add_argument("--external-approval-root", type=Path, action="append", default=[])
    parser.add_argument("--external-approval-manifest-sha256", action="append", default=[])
    parser.add_argument("--provider-native-bulk-run-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--provider-native-bulk-run-manifest-sha256", action="append", default=[]
    )
    parser.add_argument(
        "--provider-native-targeted-materialization-root",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--provider-native-targeted-materialization-manifest-sha256",
        action="append",
        default=[],
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build_coverage(
            stable_runner_ledger_root=args.stable_runner_ledger_root,
            approved_stable_runner_manifest_sha256=args.approved_stable_runner_manifest_sha256,
            held_approval_roots=args.held_approval_root,
            held_approval_manifest_sha256s=args.held_approval_manifest_sha256,
            external_approval_roots=args.external_approval_root,
            external_approval_manifest_sha256s=args.external_approval_manifest_sha256,
            output_dir=args.output_dir,
            provider_native_bulk_run_roots=args.provider_native_bulk_run_root,
            provider_native_bulk_run_manifest_sha256s=(
                args.provider_native_bulk_run_manifest_sha256
            ),
            provider_native_targeted_materialization_roots=(
                args.provider_native_targeted_materialization_root
            ),
            provider_native_targeted_materialization_manifest_sha256s=(
                args.provider_native_targeted_materialization_manifest_sha256
            ),
        )
    except (OSError, ReconciliationCoverageError, TypeError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return 75
    print(canonical_json(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
