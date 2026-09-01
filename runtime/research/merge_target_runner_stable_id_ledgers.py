#!/usr/bin/env python3
"""Merge immutable per-batch TRA runner ledgers into one cross-batch ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Mapping


RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from prepare_held_census_tra_reconciliation import (  # noqa: E402
    load_stable_runner_ledger,
)
from prepare_held_winner_seed_extension import (  # noqa: E402
    _atomic_write,
    canonical_json,
    sha256_path,
)


SCHEMA_VERSION = "target-runner-stable-id-ledger.v2"
SEED_SCHEMA_VERSION = "targeted-runner-stable-id-seed.v2"
SOURCE_SEED_SCHEMAS = {
    "targeted-runner-stable-id-seed.v1",
    "targeted-runner-stable-id-seed.v2",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
RACE_ID_RE = re.compile(r"rac_[A-Za-z0-9_]+$")


class StableRunnerMergeError(ValueError):
    pass


def _source_batch_shas(seed: Mapping[str, object]) -> list[str]:
    if seed.get("schema_version") == "targeted-runner-stable-id-seed.v1":
        values = [str(seed.get("source_targeted_batch_manifest_sha256") or "")]
    else:
        raw = seed.get("source_targeted_batch_manifest_sha256s")
        if not isinstance(raw, list):
            raise StableRunnerMergeError("stable v2 seed source batch list is missing")
        values = [str(value or "") for value in raw]
    if (
        not values
        or values != sorted(set(values))
        or any(not SHA256_RE.fullmatch(value) for value in values)
    ):
        raise StableRunnerMergeError("stable seed source batch identity drift")
    return values


def _validate_source_observations(occurrence: Mapping[str, object]) -> list[dict] | None:
    raw = occurrence.get("source_observations")
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise StableRunnerMergeError("stable source observation list is invalid")
    observations = []
    for observation in raw:
        if (
            not isinstance(observation, Mapping)
            or not str(observation.get("source_targeted_seed_id") or "")
            or not SHA256_RE.fullmatch(
                str(observation.get("source_materialized_run_manifest_sha256") or "")
            )
            or not SHA256_RE.fullmatch(
                str(observation.get("source_runner_payload_sha256") or "")
            )
        ):
            raise StableRunnerMergeError("stable source observation contract drift")
        observations.append(dict(observation))
    ordered = sorted(observations, key=canonical_json)
    if len({canonical_json(value) for value in ordered}) != len(ordered):
        raise StableRunnerMergeError("stable source observation is duplicated")
    primary = ordered[0]
    if any(occurrence.get(key) != value for key, value in primary.items()):
        raise StableRunnerMergeError("stable primary source observation drift")
    return ordered


def _semantic_occurrence(occurrence: Mapping[str, object]) -> dict:
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


def _merge_observed_occurrences(existing: dict, incoming: Mapping[str, object]) -> dict:
    if canonical_json(_semantic_occurrence(existing)) != canonical_json(
        _semantic_occurrence(incoming)
    ):
        raise StableRunnerMergeError("horse occurrence semantic conflict")
    observations = {
        canonical_json(observation): dict(observation)
        for occurrence in (existing, incoming)
        for observation in occurrence.get("source_observations", [])
        if isinstance(observation, Mapping)
    }
    ordered = [observations[key] for key in sorted(observations)]
    if not ordered:
        raise StableRunnerMergeError("horse occurrence observations are missing")
    if len(
        {
            str(observation.get("source_runner_payload_sha256") or "")
            for observation in ordered
        }
    ) != 1:
        raise StableRunnerMergeError(
            "horse runner payload differs across observations"
        )
    merged = dict(existing)
    merged["source_observations"] = ordered
    merged.update(ordered[0])
    return merged


def _validate_occurrence(occurrence: Mapping[str, object]) -> tuple[str, str, bool]:
    race_id = str(occurrence.get("race_id") or "")
    seed_id = str(occurrence.get("source_targeted_seed_id") or "")
    payload_sha = str(occurrence.get("target_race_payload_sha256") or "")
    target = occurrence.get("target")
    if (
        not RACE_ID_RE.fullmatch(race_id)
        or not seed_id
        or not SHA256_RE.fullmatch(payload_sha)
        or not isinstance(target, Mapping)
        or not SHA256_RE.fullmatch(
            str(occurrence.get("source_materialized_run_manifest_sha256") or "")
        )
        or not SHA256_RE.fullmatch(
            str(occurrence.get("source_runner_payload_sha256") or "")
        )
        or not str(occurrence.get("source_runner_name") or "").strip()
        or not str(occurrence.get("source_runner_position") or "").strip()
    ):
        raise StableRunnerMergeError("stable target occurrence contract drift")
    observations = _validate_source_observations(occurrence)
    observation_aware = observations is not None
    occurrence_key = canonical_json(
        {"race_id": race_id}
        if observation_aware
        else {"race_id": race_id, "source_targeted_seed_id": seed_id}
    )
    race_identity = canonical_json(
        {
            "race_id": race_id,
            "target_race_payload_sha256": payload_sha,
            "target": dict(target),
        }
        if observation_aware
        else {
            "race_id": race_id,
            "target_race_payload_sha256": payload_sha,
            "target": dict(target),
            "source_targeted_seed_id": seed_id,
        }
    )
    return occurrence_key, race_identity, observation_aware


def merge_stable_runner_ledgers(
    *,
    source_roots: list[Path],
    approved_manifest_sha256s: list[str],
    output_dir: Path,
) -> dict:
    if len(source_roots) < 2 or len(source_roots) != len(
        approved_manifest_sha256s
    ):
        raise StableRunnerMergeError(
            "merge requires at least two paired stable ledgers"
        )
    if output_dir.is_symlink() or (
        output_dir.exists()
        and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise StableRunnerMergeError("output directory must be absent or empty")

    sources = []
    source_keys = set()
    merged: dict[str, dict] = {}
    occurrence_identities: dict[str, str] = {}
    physical_race_ids = set()
    source_horse_rows = 0
    source_occurrence_rows = 0
    for root, approved_sha in zip(
        source_roots, approved_manifest_sha256s, strict=True
    ):
        rows, identity = load_stable_runner_ledger(
            root,
            approved_manifest_sha256=approved_sha,
        )
        source_key = (identity["root"], identity["manifest_sha256"])
        if source_key in source_keys:
            raise StableRunnerMergeError("source stable ledger is duplicated")
        source_keys.add(source_key)
        sources.append(identity)
        source_horse_rows += len(rows)
        for seed in rows:
            horse_id = str(seed.get("horse_id") or "")
            names = seed.get("source_names")
            occurrences = seed.get("target_occurrences")
            if (
                seed.get("schema_version") not in SOURCE_SEED_SCHEMAS
                or not HORSE_ID_RE.fullmatch(horse_id)
                or not isinstance(names, list)
                or any(not isinstance(name, str) for name in names)
                or not isinstance(occurrences, list)
                or not occurrences
            ):
                raise StableRunnerMergeError("source stable seed contract drift")
            entry = merged.setdefault(
                horse_id,
                {
                    "source_names": set(),
                    "source_batch_shas": set(),
                    "occurrences": {},
                },
            )
            entry["source_names"].update(
                name.strip() for name in names if name.strip()
            )
            entry["source_batch_shas"].update(_source_batch_shas(seed))
            for occurrence in occurrences:
                if not isinstance(occurrence, Mapping):
                    raise StableRunnerMergeError(
                        "stable target occurrence must be an object"
                    )
                source_occurrence_rows += 1
                occurrence_key, race_identity, observation_aware = _validate_occurrence(
                    occurrence
                )
                physical_race_ids.add(str(occurrence["race_id"]))
                previous_race = occurrence_identities.setdefault(
                    occurrence_key, race_identity
                )
                if previous_race != race_identity:
                    raise StableRunnerMergeError(
                        f"target occurrence identity conflict: {occurrence_key}"
                    )
                previous_occurrence = entry["occurrences"].get(occurrence_key)
                if previous_occurrence is not None:
                    if observation_aware:
                        entry["occurrences"][occurrence_key] = (
                            _merge_observed_occurrences(
                                previous_occurrence, occurrence
                            )
                        )
                        continue
                    if canonical_json(previous_occurrence) == canonical_json(occurrence):
                        raise StableRunnerMergeError(
                            "duplicate horse occurrence across source ledgers: "
                            f"{horse_id}/{occurrence_key}"
                        )
                    raise StableRunnerMergeError(
                        "horse occurrence conflict across source ledgers: "
                        f"{horse_id}/{occurrence_key}"
                    )
                entry["occurrences"][occurrence_key] = dict(occurrence)

    seeds = []
    for horse_id in sorted(merged):
        entry = merged[horse_id]
        occurrences = [
            entry["occurrences"][key] for key in sorted(entry["occurrences"])
        ]
        seed_id = (
            f"target-runner-{horse_id}-"
            f"{hashlib.sha256(canonical_json(occurrences).encode()).hexdigest()[:12]}"
        )
        seeds.append(
            {
                "schema_version": SEED_SCHEMA_VERSION,
                "seed_id": seed_id,
                "horse_id": horse_id,
                "source_names": sorted(entry["source_names"]),
                "source_targeted_batch_manifest_sha256s": sorted(
                    entry["source_batch_shas"]
                ),
                "target_occurrences": occurrences,
            }
        )

    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output_dir.chmod(0o700)
    ledger_path = output_dir / "target-runner-stable-id-seeds.v2.jsonl"
    body = b"".join(
        (canonical_json(seed) + "\n").encode("utf-8") for seed in seeds
    )
    _atomic_write(ledger_path, body)
    merged_occurrence_count = sum(
        len(seed["target_occurrences"]) for seed in seeds
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "network_requests": 0,
        "database_writes": 0,
        "source_stable_ledgers": sorted(
            sources,
            key=lambda value: (value["manifest_sha256"], value["root"]),
        ),
        "source_stable_ledger_count": len(sources),
        "source_stable_horse_row_count": source_horse_rows,
        "source_target_occurrence_count": source_occurrence_rows,
        "merged_target_occurrence_count": merged_occurrence_count,
        "unique_target_race_count": len(occurrence_identities),
        "unique_physical_race_count": len(physical_race_ids),
        "unique_actual_starter_count": len(seeds),
        "cross_batch_duplicate_horse_count": source_horse_rows - len(seeds),
        "source_observation_count": sum(
            len(occurrence.get("source_observations", []))
            for seed in seeds
            for occurrence in seed["target_occurrences"]
        ),
        "seed_ledger": {
            "path": ledger_path.name,
            "sha256": sha256_path(ledger_path),
            "size": ledger_path.stat().st_size,
            "rows": len(seeds),
        },
    }
    manifest_path = output_dir / "manifest.json"
    _atomic_write(
        manifest_path,
        (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
    )
    _atomic_write(
        output_dir / "COMPLETE",
        (sha256_path(manifest_path) + "\n").encode("ascii"),
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stable-runner-ledger-root", action="append", type=Path, default=[]
    )
    parser.add_argument(
        "--approved-stable-runner-manifest-sha256", action="append", default=[]
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = merge_stable_runner_ledgers(
            source_roots=args.stable_runner_ledger_root,
            approved_manifest_sha256s=(
                args.approved_stable_runner_manifest_sha256
            ),
            output_dir=args.output_dir,
        )
    except (OSError, StableRunnerMergeError, TypeError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return 75
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
