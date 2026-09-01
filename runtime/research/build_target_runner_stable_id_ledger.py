#!/usr/bin/env python3
"""从已完成的 targeted-horse materialization 生成实际出赛马稳定 ID 补全总账。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Mapping

from racing_api_horse_export import (
    _atomic_write,
    canonical_json,
    normalize_space,
    payload_sha256,
    runner_disposition,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
RACE_ID_RE = re.compile(r"rac_[A-Za-z0-9_]+$")
REGION_TO_SCOPE = {"GB": "united_kingdom", "IRE": "ireland", "FR": "france", "USA": "united_states", "US": "united_states"}


class StableIdLedgerError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise StableIdLedgerError(f"{label} must be a regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StableIdLedgerError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise StableIdLedgerError(f"{label} root must be an object")
    return payload


def _bound_path(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise StableIdLedgerError(f"{label} path is invalid")
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise StableIdLedgerError(f"{label} path escapes artifact") from exc
    if path.is_symlink() or not resolved.is_file():
        raise StableIdLedgerError(f"{label} is not a regular file")
    return resolved


def _require_exact_materialization_members(root: Path, manifest: Mapping[str, object]) -> None:
    expected_files = {"materialization-manifest.json", "COMPLETE"}
    rows = manifest.get("materialized")
    if not isinstance(rows, list):
        raise StableIdLedgerError("materialization rows are missing")
    for row in rows:
        if not isinstance(row, Mapping):
            raise StableIdLedgerError("materialization row must be an object")
        relative_root = Path(str(row.get("path") or ""))
        if not str(relative_root) or relative_root.is_absolute():
            raise StableIdLedgerError("materialized run path is invalid")
        try:
            run_root = (root / relative_root).resolve(strict=True)
            run_root.relative_to(root)
        except (OSError, ValueError) as exc:
            raise StableIdLedgerError("materialized run path escapes artifact") from exc
        run_manifest_path = _bound_path(
            run_root, "run-manifest.json", "materialized run manifest"
        )
        run_manifest = _read_json(run_manifest_path, "materialized run manifest")
        prefix = relative_root.as_posix()
        expected_files.update({f"{prefix}/run-manifest.json", f"{prefix}/COMPLETE"})
        normalized = run_manifest.get("normalized")
        responses = run_manifest.get("responses")
        if not isinstance(normalized, Mapping) or not isinstance(responses, list):
            raise StableIdLedgerError("materialized run member identities are missing")
        identities = [(normalized, "normalized export")]
        identities.extend((response, "materialized response") for response in responses)
        for identity, label in identities:
            if not isinstance(identity, Mapping):
                raise StableIdLedgerError(f"{label} identity is invalid")
            path = _bound_path(run_root, identity.get("path"), label)
            if (
                _sha256(path) != identity.get("sha256")
                or path.stat().st_size != identity.get("size")
            ):
                raise StableIdLedgerError(f"{label} identity mismatch")
            expected_files.add(f"{prefix}/{path.relative_to(run_root).as_posix()}")
    actual_files = set()
    actual_directories = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise StableIdLedgerError("materialization contains a symlink")
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
        elif path.is_dir():
            actual_directories.add(path.relative_to(root).as_posix())
    expected_directories = set()
    for value in expected_files:
        parent = Path(value).parent
        while str(parent) not in {"", "."}:
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    if actual_files != expected_files or actual_directories != expected_directories:
        raise StableIdLedgerError("materialization member set drift")


def _discipline(race_type: object) -> str:
    value = normalize_space(race_type).casefold()
    if value == "flat":
        return "flat"
    if value in {"chase", "hurdle", "nh flat", "nh_flat"}:
        return "jumps"
    raise StableIdLedgerError(f"unsupported target race type: {race_type!r}")


def _raw_target_race(target_race: Mapping[str, object]) -> dict:
    return {
        key: value
        for key, value in target_race.items()
        if key
        not in {
            "actual_starters",
            "excluded_non_runner_count",
            "source_mode",
        }
    }


def _target_occurrence(
    *,
    seed_id: str,
    run_manifest_sha256: str,
    target_race: Mapping[str, object],
    runner: Mapping[str, object],
) -> dict:
    race_id = normalize_space(target_race.get("race_id"))
    if not RACE_ID_RE.fullmatch(race_id):
        raise StableIdLedgerError("target race ID is invalid")
    local_date = normalize_space(target_race.get("date"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
        raise StableIdLedgerError("target race date is invalid")
    region_code = normalize_space(target_race.get("region")).upper()
    if region_code not in REGION_TO_SCOPE:
        raise StableIdLedgerError(f"target race region is unsupported: {region_code!r}")
    grade = normalize_space(target_race.get("pattern")).upper().replace("GROUP ", "G")
    if grade not in {"G1", "G2", "G3"}:
        raise StableIdLedgerError(f"target race grade is unsupported: {grade!r}")
    raw_race = _raw_target_race(target_race)
    return {
        "race_id": race_id,
        "target_race_payload_sha256": payload_sha256(raw_race),
        "source_targeted_seed_id": seed_id,
        "source_materialized_run_manifest_sha256": run_manifest_sha256,
        "source_runner_payload_sha256": payload_sha256(runner),
        "source_runner_name": normalize_space(runner.get("horse")),
        "source_runner_position": normalize_space(runner.get("position")),
        "target": {
            "year": int(local_date[:4]),
            "country_region": REGION_TO_SCOPE[region_code],
            "local_date": local_date,
            "canonical_name_original": normalize_space(target_race.get("race_name")),
            "race_name_aliases": [],
            "racecourse": normalize_space(target_race.get("course")),
            "racecourse_aliases": [],
            "grade_text": grade,
            "discipline": _discipline(target_race.get("type")),
        },
    }


def _load_materialized_target_races(
    materialized_dir: Path,
    *,
    approved_manifest_sha256: str,
) -> tuple[dict, list[tuple[str, str, dict | None, dict | None]]]:
    if not SHA256_RE.fullmatch(str(approved_manifest_sha256 or "")):
        raise StableIdLedgerError("approved materialization SHA-256 is invalid")
    if materialized_dir.is_symlink():
        raise StableIdLedgerError("materialization root cannot be a symlink")
    root = materialized_dir.resolve(strict=True)
    manifest_path = root / "materialization-manifest.json"
    if _sha256(manifest_path) != approved_manifest_sha256:
        raise StableIdLedgerError("materialization manifest SHA-256 mismatch")
    manifest = _read_json(manifest_path, "materialization manifest")
    complete = root / "COMPLETE"
    if (
        manifest.get("schema_version") != "targeted-horse-batch-materialization.v1"
        or manifest.get("status") != "complete"
        or manifest.get("database_writes") != 0
        or complete.is_symlink()
        or not complete.is_file()
        or complete.read_text(encoding="ascii").strip() != approved_manifest_sha256
    ):
        raise StableIdLedgerError("targeted materialization is not complete")
    source_batch_sha = normalize_space(manifest.get("source_batch_manifest_sha256"))
    if not SHA256_RE.fullmatch(source_batch_sha):
        raise StableIdLedgerError("source targeted batch identity is missing")
    rows = manifest.get("materialized")
    if not isinstance(rows, list) or not rows or len(rows) != manifest.get("selected_seed_count"):
        raise StableIdLedgerError("materialized seed list is invalid")
    _require_exact_materialization_members(root, manifest)
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise StableIdLedgerError("materialized seed receipt must be an object")
        run_root_relative = normalize_space(row.get("path"))
        run_manifest_path = _bound_path(root, f"{run_root_relative}/run-manifest.json", "run manifest")
        run_root = run_manifest_path.parent
        run_manifest_sha = normalize_space(row.get("manifest_sha256"))
        if not SHA256_RE.fullmatch(run_manifest_sha) or _sha256(run_manifest_path) != run_manifest_sha:
            raise StableIdLedgerError("materialized run manifest identity mismatch")
        run_manifest = _read_json(run_manifest_path, "materialized run manifest")
        run_complete = run_root / "COMPLETE"
        if (
            run_manifest.get("schema_version") != "targeted-horse-run.v1"
            or run_manifest.get("status") != "complete"
            or run_manifest.get("database_writes") != 0
            or run_complete.is_symlink()
            or not run_complete.is_file()
            or run_complete.read_text(encoding="ascii").strip() != run_manifest_sha
        ):
            raise StableIdLedgerError("materialized target run contract drift")
        normalized_identity = run_manifest.get("normalized")
        if not isinstance(normalized_identity, Mapping):
            raise StableIdLedgerError("materialized normalized identity is missing")
        normalized_path = _bound_path(run_root, normalized_identity.get("path"), "normalized export")
        if (
            _sha256(normalized_path) != normalized_identity.get("sha256")
            or normalized_path.stat().st_size != normalized_identity.get("size")
        ):
            raise StableIdLedgerError("materialized normalized export identity mismatch")
        normalized = _read_json(normalized_path, "normalized export")
        if normalized.get("schema_version") != "targeted-horse-export.v1" or normalized.get("database_writes") != 0:
            raise StableIdLedgerError("normalized targeted export contract drift")
        seed_id = normalize_space(row.get("seed_id"))
        target_race = normalized.get("target_race")
        if target_race is None:
            target_occurrence = normalized.get("target_occurrence")
            if (
                normalized.get("identity_mode") != "external_anchor_profile_only"
                or normalized.get("scope_target_races") != []
                or not isinstance(target_occurrence, Mapping)
                or target_occurrence.get("status") != "missing_from_provider_results"
                or not HORSE_ID_RE.fullmatch(normalize_space(normalized.get("horse_id")))
            ):
                raise StableIdLedgerError("profile-only target occurrence gap contract drift")
            result.append(
                (
                    seed_id,
                    run_manifest_sha,
                    None,
                    {
                        "schema_version": "target-runner-stable-id-gap.v1",
                        "gap_code": "target_occurrence_identity_unresolved",
                        "seed_id": seed_id,
                        "horse_id": normalize_space(normalized.get("horse_id")),
                        "source_materialized_run_manifest_sha256": run_manifest_sha,
                        "target_occurrence": dict(target_occurrence),
                    },
                )
            )
        elif isinstance(target_race, Mapping):
            if normalized.get("identity_mode") == "external_anchor_profile_only":
                raise StableIdLedgerError("profile-only materialization unexpectedly has a target race")
            result.append((seed_id, run_manifest_sha, dict(target_race), None))
        else:
            raise StableIdLedgerError("normalized target race is invalid")
    return manifest, result


def build_stable_id_seed_ledger(
    *,
    materialized_dir: Path,
    approved_materialization_manifest_sha256: str,
    output_dir: Path,
) -> dict:
    if output_dir.is_symlink() or (output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))):
        raise StableIdLedgerError("output directory must be absent or empty")
    source_manifest, target_races = _load_materialized_target_races(
        materialized_dir,
        approved_manifest_sha256=approved_materialization_manifest_sha256,
    )
    source_batch_sha = source_manifest["source_batch_manifest_sha256"]
    horses: dict[str, dict] = {}
    observed_race_hashes: dict[str, str] = {}
    source_occurrence_count = 0
    profile_only_gaps = []
    for seed_id, run_manifest_sha, target_race, gap in target_races:
        if gap is not None:
            profile_only_gaps.append(gap)
            continue
        if target_race is None:
            raise StableIdLedgerError("target race/gap conservation drift")
        race_id = normalize_space(target_race.get("race_id"))
        raw_race_hash = payload_sha256(_raw_target_race(target_race))
        previous_hash = observed_race_hashes.setdefault(race_id, raw_race_hash)
        if previous_hash != raw_race_hash:
            raise StableIdLedgerError(f"target race payload conflict: {race_id}")
        starters = target_race.get("actual_starters")
        if not isinstance(starters, list) or not starters:
            raise StableIdLedgerError("target race actual starters are missing")
        source_occurrence_count += 1
        seen_in_race = set()
        for runner in starters:
            if not isinstance(runner, Mapping):
                raise StableIdLedgerError("actual starter must be an object")
            horse_id = normalize_space(runner.get("horse_id"))
            if not HORSE_ID_RE.fullmatch(horse_id) or horse_id in seen_in_race:
                raise StableIdLedgerError("actual starter horse identity is invalid or duplicated")
            if runner_disposition(runner.get("position")) in {"non_runner", "unresolved"}:
                raise StableIdLedgerError("actual starter list contains a non-starter or unresolved status")
            seen_in_race.add(horse_id)
            occurrence = _target_occurrence(
                seed_id=seed_id,
                run_manifest_sha256=run_manifest_sha,
                target_race=target_race,
                runner=runner,
            )
            entry = horses.setdefault(
                horse_id,
                {
                    "source_names": set(),
                    "target_occurrences": {},
                },
            )
            entry["source_names"].add(normalize_space(runner.get("horse")))
            existing = entry["target_occurrences"].get(race_id)
            if existing is not None and canonical_json(existing) != canonical_json(occurrence):
                raise StableIdLedgerError(f"runner occurrence conflict: {horse_id}/{race_id}")
            entry["target_occurrences"][race_id] = occurrence

    seeds = []
    for horse_id in sorted(horses):
        entry = horses[horse_id]
        occurrences = [entry["target_occurrences"][key] for key in sorted(entry["target_occurrences"])]
        seed_id = f"target-runner-{horse_id}-{hashlib.sha256(canonical_json(occurrences).encode()).hexdigest()[:12]}"
        seeds.append(
            {
                "schema_version": "targeted-runner-stable-id-seed.v1",
                "seed_id": seed_id,
                "horse_id": horse_id,
                "source_names": sorted(name for name in entry["source_names"] if name),
                "source_targeted_batch_manifest_sha256": source_batch_sha,
                "target_occurrences": occurrences,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "target-runner-stable-id-seeds.v1.jsonl"
    gap_path = output_dir / "target-occurrence-gaps.v1.jsonl"
    _atomic_write(
        ledger_path,
        "".join(f"{canonical_json(seed)}\n" for seed in seeds).encode("utf-8"),
    )
    _atomic_write(
        gap_path,
        "".join(f"{canonical_json(gap)}\n" for gap in profile_only_gaps).encode("utf-8"),
    )
    manifest = {
        "schema_version": "target-runner-stable-id-ledger.v1",
        "status": "complete",
        "coverage_status": "complete" if not profile_only_gaps else "complete_with_gaps",
        "database_writes": 0,
        "network_requests": 0,
        "source_materialization": {
            "path": str(materialized_dir.resolve(strict=True)),
            "manifest_sha256": approved_materialization_manifest_sha256,
            "source_targeted_batch_manifest_sha256": source_batch_sha,
        },
        "source_target_occurrence_count": source_occurrence_count,
        "source_materialized_seed_count": len(target_races),
        "profile_only_gap_count": len(profile_only_gaps),
        "unique_target_race_count": len(observed_race_hashes),
        "unique_actual_starter_count": len(seeds),
        "seed_ledger": {
            "path": ledger_path.name,
            "sha256": _sha256(ledger_path),
            "size": ledger_path.stat().st_size,
            "rows": len(seeds),
        },
        "semantic_gaps": {
            "path": gap_path.name,
            "sha256": _sha256(gap_path),
            "size": gap_path.stat().st_size,
            "rows": len(profile_only_gaps),
        },
    }
    manifest_path = output_dir / "manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "COMPLETE", f"{_sha256(manifest_path)}\n".encode("ascii"))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialized-dir", type=Path, required=True)
    parser.add_argument("--approved-materialization-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_stable_id_seed_ledger(
            materialized_dir=args.materialized_dir,
            approved_materialization_manifest_sha256=args.approved_materialization_manifest_sha256,
            output_dir=args.output_dir,
        )
    except (OSError, StableIdLedgerError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return 75
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
