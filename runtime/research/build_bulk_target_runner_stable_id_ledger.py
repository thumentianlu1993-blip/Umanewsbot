#!/usr/bin/env python3
"""Build a zero-search stable-ID horse ledger from one COMPLETE bulk range run."""

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

from prepare_held_winner_seed_extension import (  # noqa: E402
    _atomic_write,
    _read_json,
    canonical_json,
    sha256_path,
)
from racing_api_bulk_range_batch_export import (  # noqa: E402
    CHECKPOINT_SCHEMA_VERSION,
    DEFINITION_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    _batch_definition,
    load_planned_batch,
)
from racing_api_bulk_results_export import reconcile_partition  # noqa: E402
from racing_api_horse_export import (  # noqa: E402
    normalize_space,
    payload_sha256,
    runner_disposition,
)


LEDGER_SCHEMA_VERSION = "target-runner-stable-id-ledger.v1"
SEED_SCHEMA_VERSION = "targeted-runner-stable-id-seed.v1"
RECONCILIATION_SCHEMA_VERSION = "bulk-result-reconciliation.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
RACE_ID_RE = re.compile(r"rac_[A-Za-z0-9_]+$")
ALLOWED_DIRECTORIES = {"cache", "normalized"}


class BulkStableIdLedgerError(ValueError):
    pass


def _regular(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise BulkStableIdLedgerError(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise BulkStableIdLedgerError(f"{label} must be a regular file")
    return resolved


def _bound_member(root: Path, relative: object, *, label: str) -> Path:
    value = str(relative or "")
    if not value or Path(value).is_absolute():
        raise BulkStableIdLedgerError(f"{label} path is invalid")
    try:
        path = (root / value).resolve(strict=True)
        path.relative_to(root)
    except (OSError, ValueError) as exc:
        raise BulkStableIdLedgerError(f"{label} path escapes bulk run") from exc
    return _regular(path, label=label)


def _discipline(value: object) -> str:
    normalized = normalize_space(value).casefold()
    if normalized == "flat":
        return "flat"
    if normalized in {"chase", "hurdle", "nh flat", "nh_flat", "jumps"}:
        return "jumps"
    raise BulkStableIdLedgerError(f"unsupported target discipline: {value!r}")


def _target_payload(target: Mapping[str, object], race: Mapping[str, object]) -> dict:
    local_date = normalize_space(race.get("date"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
        raise BulkStableIdLedgerError("bulk target race date is invalid")
    try:
        year = int(target.get("year"))
    except (TypeError, ValueError) as exc:
        raise BulkStableIdLedgerError("bulk target year is invalid") from exc
    grade = normalize_space(target.get("grade_text")).upper()
    country_region = normalize_space(target.get("country_region"))
    if year != int(local_date[:4]) or grade not in {"G1", "G2", "G3"}:
        raise BulkStableIdLedgerError("bulk target year or grade drift")
    if country_region not in {
        "united_kingdom",
        "france",
        "ireland",
        "united_states",
    }:
        raise BulkStableIdLedgerError("bulk target region is unsupported")
    names = target.get("race_name_aliases")
    courses = target.get("racecourse_aliases")
    if not isinstance(names, list) or not isinstance(courses, list):
        raise BulkStableIdLedgerError("bulk target aliases are invalid")
    return {
        "year": year,
        "country_region": country_region,
        "local_date": local_date,
        "canonical_name_original": normalize_space(
            target.get("canonical_name_original")
        ),
        "race_name_aliases": list(names),
        "racecourse": normalize_space(target.get("racecourse")),
        "racecourse_aliases": list(courses),
        "grade_text": grade,
        "discipline": _discipline(target.get("discipline")),
    }


def _load_complete_bulk_run(
    root: Path,
    *,
    approved_manifest_sha256: str,
) -> tuple[dict, dict, list[dict], dict]:
    if not SHA256_RE.fullmatch(str(approved_manifest_sha256 or "")):
        raise BulkStableIdLedgerError("approved bulk run SHA-256 is invalid")
    if root.is_symlink():
        raise BulkStableIdLedgerError("bulk run root must not be a symlink")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise BulkStableIdLedgerError("bulk run root must be a directory")
    manifest_path = _regular(
        resolved / "batch-manifest.json", label="bulk run manifest"
    )
    manifest_sha = sha256_path(manifest_path)
    if manifest_sha != approved_manifest_sha256:
        raise BulkStableIdLedgerError("bulk run manifest SHA-256 mismatch")
    manifest = _read_json(manifest_path, label="bulk run manifest")
    marker = _regular(resolved / "COMPLETE", label="bulk run COMPLETE marker")
    batch = manifest.get("batch")
    plan = manifest.get("plan")
    normalized_identity = manifest.get("normalized")
    definition_identity = manifest.get("batch_definition")
    checkpoint_identity = manifest.get("checkpoint")
    responses = manifest.get("responses")
    summary = manifest.get("summary")
    range_units = manifest.get("range_units")
    if (
        manifest.get("schema_version") != RUN_SCHEMA_VERSION
        or manifest.get("status") not in {"complete", "complete_with_gaps"}
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(batch, Mapping)
        or not isinstance(plan, Mapping)
        or not isinstance(normalized_identity, Mapping)
        or not isinstance(definition_identity, Mapping)
        or not isinstance(checkpoint_identity, Mapping)
        or not isinstance(responses, list)
        or not responses
        or not isinstance(summary, Mapping)
        or not isinstance(range_units, list)
        or not range_units
        or isinstance(manifest.get("gap_count"), bool)
        or not isinstance(manifest.get("gap_count"), int)
        or manifest.get("gap_count") < 0
        or manifest.get("reconciliation_status")
        != ("complete" if manifest.get("gap_count") == 0 else "needs_review")
        or manifest.get("request_count") != len(manifest.get("request_ledger") or [])
        or not isinstance(manifest.get("openapi_contract"), Mapping)
    ):
        raise BulkStableIdLedgerError("bulk run manifest contract drift")

    batch_id = normalize_space(batch.get("batch_id"))
    try:
        planned_batch, targets, current_plan = load_planned_batch(
            Path(str(plan.get("root") or "")),
            expected_manifest_sha256=str(plan.get("manifest_sha256") or ""),
            expected_plan_sha256=str(plan.get("plan_sha256") or ""),
            batch_id=batch_id,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise BulkStableIdLedgerError(str(exc)) from exc
    planned_public = {
        key: value for key, value in planned_batch.items() if key != "region_year_units"
    }
    if (
        dict(batch) != planned_public
        or range_units != planned_batch["region_year_units"]
        or dict(plan) != current_plan
    ):
        raise BulkStableIdLedgerError("bulk run-to-plan identity drift")

    expected_files = {"batch-manifest.json", "COMPLETE"}
    definition_path = _bound_member(
        resolved,
        definition_identity.get("path"),
        label="bulk batch definition",
    )
    checkpoint_path = _bound_member(
        resolved,
        checkpoint_identity.get("path"),
        label="bulk range checkpoint",
    )
    definition = _read_json(definition_path, label="bulk batch definition")
    checkpoint = _read_json(checkpoint_path, label="bulk range checkpoint")
    expected_definition = _batch_definition(
        batch=planned_batch,
        plan_identity=current_plan,
        openapi_contract=manifest["openapi_contract"],
    )
    if (
        str(definition_path.relative_to(resolved)) != "batch-definition.json"
        or definition_identity.get("schema_version") != DEFINITION_SCHEMA_VERSION
        or definition_identity.get("sha256") != sha256_path(definition_path)
        or definition_identity.get("size") != definition_path.stat().st_size
        or definition != expected_definition
    ):
        raise BulkStableIdLedgerError("bulk batch definition identity drift")
    if (
        str(checkpoint_path.relative_to(resolved)) != "checkpoint.json"
        or checkpoint_identity.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint_identity.get("status") != "complete"
        or checkpoint_identity.get("cumulative_request_count")
        != manifest.get("request_count")
        or checkpoint_identity.get("sha256") != sha256_path(checkpoint_path)
        or checkpoint_identity.get("size") != checkpoint_path.stat().st_size
        or checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("status") != "complete"
        or checkpoint.get("definition_sha256") != sha256_path(definition_path)
        or checkpoint.get("cumulative_request_count") != manifest.get("request_count")
        or checkpoint.get("pages") != responses
        or not isinstance(checkpoint.get("attempt_request_ledgers"), list)
        or [
            item
            for attempt in checkpoint.get("attempt_request_ledgers", [])
            if isinstance(attempt, Mapping)
            for item in attempt.get("request_ledger", [])
        ]
        != manifest.get("request_ledger")
    ):
        raise BulkStableIdLedgerError("bulk range checkpoint identity drift")
    expected_files.update({"batch-definition.json", "checkpoint.json"})
    response_urls = []
    for row in responses:
        if not isinstance(row, Mapping):
            raise BulkStableIdLedgerError("bulk response identity is invalid")
        path = _bound_member(resolved, row.get("path"), label="bulk response")
        relative = str(path.relative_to(resolved))
        if (
            relative in expected_files
            or sha256_path(path) != row.get("sha256")
            or path.stat().st_size != row.get("size")
            or not str(row.get("url") or "").startswith("https://")
        ):
            raise BulkStableIdLedgerError("bulk response identity drift")
        response = _read_json(path, label="bulk response")
        if response.get("url") != row.get("url"):
            raise BulkStableIdLedgerError("bulk response URL drift")
        expected_files.add(relative)
        response_urls.append(row["url"])
    request_urls = [
        str(row.get("url") or "")
        for row in manifest["request_ledger"]
        if isinstance(row, Mapping)
    ]
    collapsed_request_urls = []
    for url in request_urls:
        if not collapsed_request_urls or collapsed_request_urls[-1] != url:
            collapsed_request_urls.append(url)
    if collapsed_request_urls != response_urls:
        raise BulkStableIdLedgerError("bulk request/response ledger drift")

    normalized_path = _bound_member(
        resolved, normalized_identity.get("path"), label="bulk normalized result"
    )
    normalized_relative = str(normalized_path.relative_to(resolved))
    if (
        sha256_path(normalized_path) != normalized_identity.get("sha256")
        or normalized_path.stat().st_size != normalized_identity.get("size")
    ):
        raise BulkStableIdLedgerError("bulk normalized result identity drift")
    expected_files.add(normalized_relative)
    normalized = _read_json(normalized_path, label="bulk normalized result")
    races = normalized.get("races")
    if (
        normalized.get("schema_version") != RECONCILIATION_SCHEMA_VERSION
        or normalized.get("status") not in {"complete", "needs_review"}
        or normalized.get("database_writes") != 0
        or normalized.get("batch_id") != batch_id
        or not isinstance(races, list)
    ):
        raise BulkStableIdLedgerError("bulk normalized result contract drift")
    repeated = reconcile_partition(targets=targets, races=races)
    for key, value in repeated.items():
        if normalized.get(key) != value:
            raise BulkStableIdLedgerError(
                f"bulk normalized reconciliation drift: {key}"
            )
    expected_summary = {
        key: repeated[key]
        for key in (
            "target_count",
            "mapped_targets",
            "participant_count",
            "excluded_non_runner_count",
        )
    }
    if dict(summary) != expected_summary:
        raise BulkStableIdLedgerError("bulk run summary drift")

    actual_files = set()
    for path in resolved.rglob("*"):
        if path.is_symlink():
            raise BulkStableIdLedgerError("bulk run contains a symlink")
        if path.is_file():
            actual_files.add(str(path.relative_to(resolved)))
        elif path.is_dir() and str(path.relative_to(resolved)) not in ALLOWED_DIRECTORIES:
            raise BulkStableIdLedgerError("bulk run contains an unexpected directory")
    if actual_files != expected_files:
        raise BulkStableIdLedgerError("bulk run member set drift")
    return manifest, normalized, targets, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "normalized_sha256": normalized_identity["sha256"],
        "plan_manifest_sha256": plan["manifest_sha256"],
        "batch_id": batch_id,
    }


def build_bulk_stable_id_seed_ledger(
    *,
    bulk_run_dir: Path,
    approved_bulk_run_manifest_sha256: str,
    output_dir: Path,
) -> dict:
    if output_dir.is_symlink() or (
        output_dir.exists()
        and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise BulkStableIdLedgerError("output directory must be absent or empty")
    manifest, normalized, targets, source_identity = _load_complete_bulk_run(
        bulk_run_dir,
        approved_manifest_sha256=approved_bulk_run_manifest_sha256,
    )
    target_by_key = {str(row["target_key"]): row for row in targets}
    race_by_id = {str(row.get("race_id") or ""): row for row in normalized["races"]}
    mapping_by_target = {
        str(row["target_key"]): row for row in normalized["mappings"]
    }
    horses: dict[str, dict] = {}
    seen_target_horses = set()
    for participant in normalized["participants"]:
        target_key = str(participant.get("target_key") or "")
        race_id = str(participant.get("race_id") or "")
        horse_id = normalize_space(participant.get("horse_id"))
        target = target_by_key.get(target_key)
        mapping = mapping_by_target.get(target_key)
        race = race_by_id.get(race_id)
        runner = participant.get("runner")
        if (
            not HORSE_ID_RE.fullmatch(horse_id)
            or not RACE_ID_RE.fullmatch(race_id)
            or not isinstance(target, Mapping)
            or not isinstance(mapping, Mapping)
            or mapping.get("race_id") != race_id
            or not isinstance(race, Mapping)
            or not isinstance(runner, Mapping)
            or runner_disposition(runner.get("position"))
            in {"non_runner", "unresolved"}
            or (target_key, horse_id) in seen_target_horses
        ):
            raise BulkStableIdLedgerError("bulk participant identity drift")
        seen_target_horses.add((target_key, horse_id))
        occurrence = {
            "race_id": race_id,
            "target_race_payload_sha256": mapping["race_payload_sha256"],
            "source_targeted_seed_id": target_key,
            "source_materialized_run_manifest_sha256": source_identity[
                "manifest_sha256"
            ],
            "source_runner_payload_sha256": payload_sha256(runner),
            "source_runner_name": normalize_space(participant.get("horse_name")),
            "source_runner_position": normalize_space(
                participant.get("reported_position")
            ),
            "source_route": "bulk_results",
            "source_bulk_batch_id": source_identity["batch_id"],
            "source_bulk_run_manifest_sha256": source_identity[
                "manifest_sha256"
            ],
            "target": _target_payload(target, race),
        }
        entry = horses.setdefault(
            horse_id,
            {"source_names": set(), "target_occurrences": {}},
        )
        entry["source_names"].add(occurrence["source_runner_name"])
        existing = entry["target_occurrences"].get(race_id)
        if existing is not None:
            if canonical_json(existing) == canonical_json(occurrence):
                raise BulkStableIdLedgerError(
                    f"duplicate bulk horse occurrence: {horse_id}/{race_id}"
                )
            raise BulkStableIdLedgerError(
                f"conflicting bulk horse occurrence: {horse_id}/{race_id}"
            )
        entry["target_occurrences"][race_id] = occurrence

    seeds = []
    for horse_id in sorted(horses):
        entry = horses[horse_id]
        occurrences = [
            entry["target_occurrences"][race_id]
            for race_id in sorted(entry["target_occurrences"])
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
                "source_names": sorted(
                    name for name in entry["source_names"] if name
                ),
                "source_targeted_batch_manifest_sha256": source_identity[
                    "manifest_sha256"
                ],
                "target_occurrences": occurrences,
            }
        )
    if len(seen_target_horses) != normalized["participant_count"]:
        raise BulkStableIdLedgerError("bulk participant conservation drift")

    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output_dir.chmod(0o700)
    ledger_path = output_dir / "target-runner-stable-id-seeds.v1.jsonl"
    body = b"".join(
        (canonical_json(seed) + "\n").encode("utf-8") for seed in seeds
    )
    _atomic_write(ledger_path, body)
    occurrence_count = sum(len(seed["target_occurrences"]) for seed in seeds)
    output_manifest = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "status": "complete",
        "network_requests": 0,
        "database_writes": 0,
        "source_route": "bulk_results",
        "source_bulk_run": source_identity,
        "source_target_occurrence_count": len(mapping_by_target),
        "unique_target_race_count": len(mapping_by_target),
        "actual_starter_occurrence_count": occurrence_count,
        "unique_actual_starter_count": len(seeds),
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
            json.dumps(
                output_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    _atomic_write(
        output_dir / "COMPLETE",
        (sha256_path(manifest_path) + "\n").encode("ascii"),
    )
    return output_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk-run-dir", type=Path, required=True)
    parser.add_argument("--approved-bulk-run-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    try:
        result = build_bulk_stable_id_seed_ledger(**vars(parse_args()))
    except (OSError, TypeError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return 75
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
