#!/usr/bin/env python3
"""把 TRA targeted batch 的内容寻址工件展开为可审计的单马 materialization。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping

from racing_api_content_pool import (
    COMPACT_SCHEMA_VERSION,
    ContentAddressedPool,
    ContentPoolError,
    REF_SCHEMA_VERSION,
    canonical_bytes,
)
from racing_api_horse_export import (
    _atomic_write,
    _require_empty_output,
    _sha256_path,
    runner_disposition,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
MAX_BATCH_SEEDS = 100


class MaterializationError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, child in pairs:
        if key in value:
            raise MaterializationError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _load_json(path: Path, *, label: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise MaterializationError(f"{label} must be a regular non-symlink file")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MaterializationError(f"invalid JSON constant: {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise MaterializationError(f"{label} must be a JSON object")
    return value


def _declared_file(root: Path, identity: Mapping[str, object], *, label: str) -> Path:
    relative = Path(str(identity.get("path") or ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise MaterializationError(f"{label} path is invalid")
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise MaterializationError(f"{label} path escapes root") from exc
    expected_sha = str(identity.get("sha256") or "")
    expected_size = identity.get("size")
    if (
        path.is_symlink()
        or not resolved.is_file()
        or not SHA256_RE.fullmatch(expected_sha)
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 1
        or resolved.stat().st_size != expected_size
        or _sha256_path(resolved) != expected_sha
    ):
        raise MaterializationError(f"{label} identity drift")
    return resolved


def _enhance_target_race(race: Mapping[str, object], *, horse_id: str) -> dict:
    runners = race.get("runners")
    if not isinstance(runners, list) or not runners:
        raise MaterializationError("target race runners are invalid")
    actual_starters = []
    excluded = 0
    target_started = False
    for runner in runners:
        if not isinstance(runner, Mapping):
            raise MaterializationError("target race runner must be an object")
        disposition = runner_disposition(runner.get("position"))
        if disposition == "unresolved":
            raise MaterializationError("target race contains unresolved runner status")
        if disposition == "non_runner":
            excluded += 1
            continue
        row = dict(runner)
        actual_starters.append(row)
        target_started |= row.get("horse_id") == horse_id
    if not target_started:
        raise MaterializationError("target horse is not an actual starter")
    return {
        **dict(race),
        "actual_starters": actual_starters,
        "excluded_non_runner_count": excluded,
        "source_mode": "targeted_horse_content_pool",
    }


def _expand_compact(compact: Mapping[str, object], *, pool: ContentAddressedPool) -> dict:
    if (
        compact.get("schema_version") != COMPACT_SCHEMA_VERSION
        or compact.get("database_writes") != 0
    ):
        raise MaterializationError("compact normalized export contract drift")
    horse_id = str(compact.get("horse_id") or "")
    seed_id = str(compact.get("seed_id") or "").strip()
    if not HORSE_ID_RE.fullmatch(horse_id) or not seed_id:
        raise MaterializationError("compact target identity drift")
    try:
        profile = pool.read_json(compact.get("profile_ref", {}))
        page_field_matrix = pool.read_json(compact.get("page_field_matrix_ref", {}))
        raw_parent_refs = compact.get("parent_profile_refs")
        if not isinstance(raw_parent_refs, list):
            raise MaterializationError("compact parent references are invalid")
        parents = [pool.read_json(reference) for reference in raw_parent_refs]
    except ContentPoolError as exc:
        raise MaterializationError(str(exc)) from exc
    if profile.get("horse_id") != horse_id:
        raise MaterializationError("compact target profile identity drift")

    career = compact.get("career")
    records = career.get("records") if isinstance(career, Mapping) else None
    if not isinstance(records, list):
        raise MaterializationError("compact career records are invalid")
    races = []
    race_by_id = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise MaterializationError("compact career record must be an object")
        try:
            race = pool.read_json(record.get("race_ref", {}))
        except ContentPoolError as exc:
            raise MaterializationError(str(exc)) from exc
        race_id = str(record.get("race_id") or "")
        matching = [
            dict(runner)
            for runner in race.get("runners", [])
            if isinstance(runner, Mapping) and runner.get("horse_id") == horse_id
        ]
        if (
            race.get("race_id") != race_id
            or race_id in race_by_id
            or len(matching) != 1
            or record.get("target_runner") != matching[0]
        ):
            raise MaterializationError("compact career race identity drift")
        races.append(race)
        race_by_id[race_id] = race
    if (
        career.get("unique_race_count") != len(races)
        or isinstance(career.get("provider_row_count"), bool)
        or not isinstance(career.get("provider_row_count"), int)
        or career["provider_row_count"] < len(races)
        or isinstance(career.get("page_count"), bool)
        or not isinstance(career.get("page_count"), int)
        or career["page_count"] < 1
    ):
        raise MaterializationError("compact career counts drift")

    identity_mode = compact.get("identity_mode")
    target_race_id = compact.get("target_race_id")
    scope_ids = compact.get("scope_target_race_ids")
    if not isinstance(scope_ids, list) or scope_ids != list(dict.fromkeys(scope_ids)):
        raise MaterializationError("compact scope target identities drift")
    if identity_mode == "external_anchor_profile_only":
        if target_race_id is not None or scope_ids:
            raise MaterializationError("profile-only compact target scope drift")
        target_race = None
        scope_target_races = []
    elif identity_mode in {
        "provider_stable_id_from_target_race",
        "target_occurrence",
        "strong_biodata",
    }:
        if not scope_ids or target_race_id != scope_ids[0]:
            raise MaterializationError("stable target scope drift")
        try:
            scope_target_races = [
                _enhance_target_race(race_by_id[race_id], horse_id=horse_id)
                for race_id in scope_ids
            ]
        except KeyError as exc:
            raise MaterializationError("scope target race is absent from career") from exc
        target_race = scope_target_races[0]
    else:
        raise MaterializationError("compact identity mode is unsupported")

    return {
        "schema_version": "targeted-horse-export.v1",
        "database_writes": 0,
        "seed_id": seed_id,
        "horse_id": horse_id,
        "identity_mode": identity_mode,
        "profile": profile,
        "parent_profiles": parents,
        "career": {
            "provider_row_count": career["provider_row_count"],
            "unique_race_count": career["unique_race_count"],
            "page_count": career["page_count"],
            "races": races,
        },
        "career_authority": compact.get("career_authority"),
        "target_occurrence": compact.get("target_occurrence"),
        "target_race": target_race,
        "scope_target_races": scope_target_races,
        "page_field_matrix": page_field_matrix,
    }


def _validate_source_batch(batch_dir: Path, approved_sha256: str) -> dict:
    if not SHA256_RE.fullmatch(str(approved_sha256 or "")):
        raise MaterializationError("approved batch manifest SHA-256 is invalid")
    try:
        root = batch_dir.resolve(strict=True)
    except OSError as exc:
        raise MaterializationError("source batch directory is missing") from exc
    if batch_dir.is_symlink() or not root.is_dir():
        raise MaterializationError("source batch must be a non-symlink directory")
    manifest_path = root / "batch-manifest.json"
    complete_path = root / "COMPLETE"
    if (
        manifest_path.is_symlink()
        or complete_path.is_symlink()
        or not manifest_path.is_file()
        or not complete_path.is_file()
        or _sha256_path(manifest_path) != approved_sha256
        or complete_path.read_text(encoding="ascii").strip() != approved_sha256
    ):
        raise MaterializationError("source batch COMPLETE identity drift")
    manifest = _load_json(manifest_path, label="source batch manifest")
    completed = manifest.get("completed")
    count = manifest.get("completed_seed_count")
    if (
        manifest.get("schema_version") != "targeted-horse-batch-run.v1"
        or manifest.get("status") != "complete"
        or manifest.get("database_writes") != 0
        or not isinstance(completed, dict)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
        or count > MAX_BATCH_SEEDS
        or count != manifest.get("planned_seed_count")
        or count != len(completed)
    ):
        raise MaterializationError("source batch manifest contract drift")
    pool_identity = manifest.get("content_pool")
    if not isinstance(pool_identity, Mapping) or pool_identity.get("path") != "content-pool-manifest.json":
        raise MaterializationError("source content-pool identity is missing")
    pool_manifest_path = _declared_file(root, pool_identity, label="content-pool manifest")
    pool_manifest = _load_json(pool_manifest_path, label="content-pool manifest")
    try:
        pool = ContentAddressedPool(root / "objects")
        snapshot = pool.snapshot()
    except ContentPoolError as exc:
        raise MaterializationError(str(exc)) from exc
    if snapshot != pool_manifest:
        raise MaterializationError("content-pool snapshot drift")
    expected_pool_files = {"object-index.json", ".pool.lock"} | {
        str(row["path"]) for row in snapshot["objects"]
    }
    actual_pool_files = {
        str(path.relative_to(pool.root))
        for path in pool.root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_pool_files != expected_pool_files or any(path.is_symlink() for path in pool.root.rglob("*")):
        raise MaterializationError("content-pool member set drift")

    definition = _load_json(root / "batch-definition.json", label="batch definition")
    seed_rows = definition.get("seeds") if isinstance(definition, dict) else None
    if (
        definition.get("schema_version") != "targeted-horse-batch-definition.v1"
        or definition.get("seed_ledger") != manifest.get("seed_ledger")
        or definition.get("parameters") != manifest.get("parameters")
        or not isinstance(seed_rows, list)
        or len(seed_rows) != count
    ):
        raise MaterializationError("batch definition drift")
    ordered = []
    seen = set()
    for ordinal, seed_row in enumerate(seed_rows, 1):
        if not isinstance(seed_row, Mapping) or seed_row.get("ordinal") != ordinal:
            raise MaterializationError("batch seed definition order drift")
        seed_id = str(seed_row.get("seed_id") or "")
        receipt = completed.get(seed_id)
        if (
            not seed_id
            or seed_id in seen
            or not isinstance(receipt, Mapping)
            or receipt.get("seed_sha256") != seed_row.get("sha256")
        ):
            raise MaterializationError("batch completion receipt drift")
        _declared_file(root, seed_row, label="batch seed")
        attempt_root = root / str(receipt.get("artifact_dir") or "")
        try:
            attempt_root = attempt_root.resolve(strict=True)
            attempt_root.relative_to(root)
        except (OSError, ValueError) as exc:
            raise MaterializationError("compact run path escapes batch") from exc
        compact_manifest_path = attempt_root / "run-manifest.json"
        if (
            attempt_root.is_symlink()
            or not compact_manifest_path.is_file()
            or _sha256_path(compact_manifest_path) != receipt.get("manifest_sha256")
            or (attempt_root / "COMPLETE").read_text(encoding="ascii").strip()
            != receipt.get("manifest_sha256")
        ):
            raise MaterializationError("compact run manifest identity drift")
        compact_manifest = _load_json(compact_manifest_path, label="compact run manifest")
        compact_pool = compact_manifest.get("content_pool")
        compact_normalized_path = _declared_file(
            attempt_root,
            compact_manifest.get("normalized", {}),
            label="compact normalized export",
        )
        if (
            compact_manifest.get("schema_version") != "targeted-horse-run.v2"
            or compact_manifest.get("status") != "complete"
            or compact_manifest.get("database_writes") != 0
            or not isinstance(compact_pool, Mapping)
            or (
                attempt_root
                / str(compact_pool.get("root_relative_to_run") or "")
            ).resolve()
            != pool.root
        ):
            raise MaterializationError("compact run contract drift")
        compact = _load_json(compact_normalized_path, label="compact normalized export")
        if compact.get("seed_id") != seed_id or compact.get("horse_id") != receipt.get("horse_id"):
            raise MaterializationError("compact normalized identity drift")
        seen.add(seed_id)
        ordered.append(
            {
                "ordinal": ordinal,
                "seed_id": seed_id,
                "horse_id": receipt["horse_id"],
                "compact_manifest": compact_manifest,
                "compact_manifest_sha256": receipt["manifest_sha256"],
                "seed_sha256": receipt["seed_sha256"],
                "compact": compact,
            }
        )
    if seen != set(completed):
        raise MaterializationError("batch completed member set drift")
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": approved_sha256,
        "content_pool_manifest_sha256": pool_identity["sha256"],
        "pool": pool,
        "runs": ordered,
    }


def materialize_targeted_batch(
    *,
    batch_dir: Path,
    approved_batch_manifest_sha256: str,
    output_dir: Path,
    selected_seed_ids: list[str] | None = None,
) -> dict:
    source = _validate_source_batch(batch_dir, approved_batch_manifest_sha256)
    _require_empty_output(output_dir)
    selected = selected_seed_ids or [row["seed_id"] for row in source["runs"]]
    if not selected or selected != list(dict.fromkeys(selected)):
        raise MaterializationError("selected seed IDs must be non-empty and unique")
    selected_set = set(selected)
    unknown = selected_set - {row["seed_id"] for row in source["runs"]}
    if unknown:
        raise MaterializationError("selected seed ID is absent from source batch")
    runs = [row for row in source["runs"] if row["seed_id"] in selected_set]
    if [row["seed_id"] for row in runs] != selected:
        raise MaterializationError("selected seed IDs must follow source batch order")

    output_dir.mkdir(mode=0o700, parents=True)
    materialized = []
    for ordinal, row in enumerate(runs, 1):
        compact_manifest = row["compact_manifest"]
        expanded = _expand_compact(row["compact"], pool=source["pool"])
        run_name = f"{ordinal:05d}-{row['seed_sha256'][:12]}"
        run_dir = output_dir / run_name
        run_dir.mkdir(mode=0o700)
        normalized_path = run_dir / "normalized" / "targeted-horse-export.json"
        _atomic_write(normalized_path, canonical_bytes(expanded))
        responses = []
        for response_ordinal, response in enumerate(compact_manifest.get("responses", []), 1):
            if not isinstance(response, Mapping) or not isinstance(response.get("object_ref"), Mapping):
                raise MaterializationError("compact response reference drift")
            try:
                wrapper = source["pool"].read_json(response["object_ref"])
            except ContentPoolError as exc:
                raise MaterializationError(str(exc)) from exc
            if wrapper.get("url") != response.get("url"):
                raise MaterializationError("compact response URL drift")
            response_path = run_dir / "cache" / f"response-{response_ordinal:04d}.json"
            _atomic_write(response_path, canonical_bytes(wrapper))
            responses.append(
                {
                    "path": str(response_path.relative_to(run_dir)),
                    "sha256": _sha256_path(response_path),
                    "size": response_path.stat().st_size,
                    "url": response["url"],
                    "source_object_ref": dict(response["object_ref"]),
                }
            )
        run_manifest = {
            "schema_version": "targeted-horse-run.v1",
            "status": "complete",
            "database_writes": 0,
            "materialization_mode": "expanded_compact",
            "source_batch_manifest_sha256": source["manifest_sha256"],
            "source_compact_manifest_sha256": row["compact_manifest_sha256"],
            "source_content_pool_manifest_sha256": source[
                "content_pool_manifest_sha256"
            ],
            "openapi_contract": compact_manifest.get("openapi_contract"),
            "request_count": compact_manifest.get("request_count"),
            "request_ledger": compact_manifest.get("request_ledger"),
            "responses": responses,
            "normalized": {
                "path": str(normalized_path.relative_to(run_dir)),
                "sha256": _sha256_path(normalized_path),
                "size": normalized_path.stat().st_size,
            },
        }
        run_manifest_path = run_dir / "run-manifest.json"
        _atomic_write(run_manifest_path, canonical_bytes(run_manifest))
        run_manifest_sha = _sha256_path(run_manifest_path)
        _atomic_write(run_dir / "COMPLETE", f"{run_manifest_sha}\n".encode("ascii"))
        materialized.append(
            {
                "ordinal": ordinal,
                "seed_id": row["seed_id"],
                "horse_id": row["horse_id"],
                "path": run_name,
                "manifest_sha256": run_manifest_sha,
                "materialization_mode": "expanded_compact",
            }
        )
    manifest = {
        "schema_version": "targeted-horse-batch-materialization.v1",
        "status": "complete",
        "database_writes": 0,
        "source_batch_manifest_sha256": source["manifest_sha256"],
        "source_content_pool_manifest_sha256": source[
            "content_pool_manifest_sha256"
        ],
        "recompute_normalized": False,
        "selected_seed_count": len(materialized),
        "materialized": materialized,
    }
    manifest_path = output_dir / "materialization-manifest.json"
    _atomic_write(manifest_path, canonical_bytes(manifest))
    manifest_sha = _sha256_path(manifest_path)
    _atomic_write(output_dir / "COMPLETE", f"{manifest_sha}\n".encode("ascii"))
    return {**manifest, "materialization_manifest_sha256": manifest_sha}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--approved-batch-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selected-seed-id", action="append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize_targeted_batch(
        batch_dir=args.batch_dir,
        approved_batch_manifest_sha256=args.approved_batch_manifest_sha256,
        output_dir=args.output_dir,
        selected_seed_ids=args.selected_seed_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
