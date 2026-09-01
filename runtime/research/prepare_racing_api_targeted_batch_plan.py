#!/usr/bin/env python3
"""Prepare deterministic, non-executable TRA batches from an approved seed ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = "racing-api-targeted-batch-plan.v1"
SEED_MANIFEST_SCHEMA = "targeted-horse-seed-ledger.v1"
SEED_SCHEMA = "targeted-horse-seed.v1"
SEED_SCHEMA_V2 = "targeted-horse-seed.v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _regular(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _object(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(_regular(path, label=label).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _seed_rows(path: Path) -> list[dict]:
    resolved = _regular(path, label="seed ledger")
    rows = []
    seen = set()
    try:
        for line_number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("schema_version") not in {
                SEED_SCHEMA,
                SEED_SCHEMA_V2,
            }:
                raise ValueError(f"seed contract drift at line {line_number}")
            seed_id = str(row.get("seed_id") or "")
            target = row.get("target")
            if (
                not seed_id
                or seed_id in seen
                or not isinstance(target, Mapping)
                or not str(target.get("country_region") or "")
                or not str(row.get("name") or "")
            ):
                raise ValueError(f"seed identity drift at line {line_number}")
            if row.get("schema_version") == SEED_SCHEMA and not str(
                target.get("local_date") or ""
            ):
                raise ValueError(f"seed identity drift at line {line_number}")
            if row.get("schema_version") == SEED_SCHEMA_V2 and (
                not str(target.get("canonical_name_original") or "").strip()
                or not str(target.get("racecourse") or "").strip()
                or not str(target.get("grade_text") or "").strip()
                or not str(target.get("discipline") or "").strip()
                or not str(target.get("edition_year", target.get("year")) or "").strip()
            ):
                raise ValueError(f"v2 seed target identity drift at line {line_number}")
            seen.add(seed_id)
            rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("seed ledger is invalid JSONL") from exc
    if not rows:
        raise ValueError("seed ledger is empty")
    return rows


def _edition_year(seed: Mapping[str, object]) -> int:
    target = seed["target"]
    assert isinstance(target, Mapping)
    value = target.get("edition_year", target.get("year"))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("seed edition year is invalid") from exc


def _sort_key(seed: Mapping[str, object]) -> tuple:
    target = seed["target"]
    assert isinstance(target, Mapping)
    return (
        str(target.get("country_region") or ""),
        _edition_year(seed),
        str(target.get("local_date") or ""),
        str(seed.get("seed_id") or ""),
    )


def prepare_batch_plan(
    *,
    seed_root: Path,
    approved_seed_manifest_sha256: str,
    approved_seed_ledger_sha256: str,
    output_dir: Path,
    batch_size_cap: int = 20,
    max_search_candidates: int = 3,
    max_results_pages_per_horse: int = 3,
    max_parent_profiles: int = 2,
    min_interval_ms: int = 250,
    spacing_minutes: int = 30,
) -> dict:
    integers = (
        batch_size_cap,
        max_search_candidates,
        max_results_pages_per_horse,
        max_parent_profiles,
        min_interval_ms,
        spacing_minutes,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in integers):
        raise ValueError("batch parameters must be integers")
    if (
        not 1 <= batch_size_cap <= 100
        or not 1 <= max_search_candidates <= 20
        or not 1 <= max_results_pages_per_horse <= 20
        or not 0 <= max_parent_profiles <= 2
        or min_interval_ms < 200
        or spacing_minutes < 5
    ):
        raise ValueError("batch parameters are outside safety bounds")
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("output directory must be absent or empty")
    if not SHA256_RE.fullmatch(approved_seed_manifest_sha256) or not SHA256_RE.fullmatch(
        approved_seed_ledger_sha256
    ):
        raise ValueError("approved seed SHA is invalid")

    root = seed_root.resolve(strict=True)
    if seed_root.is_symlink() or not root.is_dir():
        raise ValueError("seed root must be a regular directory")
    manifest_path = _regular(root / "seed-ledger-manifest.json", label="seed manifest")
    ledger_path = _regular(root / "targeted-horse-seeds.jsonl", label="seed ledger")
    complete = _regular(root / "COMPLETE", label="seed COMPLETE marker")
    if (
        sha256_path(manifest_path) != approved_seed_manifest_sha256
        or sha256_path(ledger_path) != approved_seed_ledger_sha256
        or complete.read_text(encoding="ascii").strip() != approved_seed_manifest_sha256
    ):
        raise ValueError("seed artifact identity mismatch")
    seed_manifest = _object(manifest_path, label="seed manifest")
    ledger_identity = seed_manifest.get("seed_ledger")
    rows = _seed_rows(ledger_path)
    if (
        seed_manifest.get("schema_version") != SEED_MANIFEST_SCHEMA
        or seed_manifest.get("status") != "complete"
        or seed_manifest.get("completion_marker") != "COMPLETE"
        or seed_manifest.get("database_writes") != 0
        or not isinstance(ledger_identity, Mapping)
        or ledger_identity.get("sha256") != approved_seed_ledger_sha256
        or ledger_identity.get("rows") != len(rows)
        or seed_manifest.get("seed_count") != len(rows)
    ):
        raise ValueError("seed manifest contract drift")

    per_seed_ceiling = (
        1
        + max_search_candidates * max_results_pages_per_horse
        + 2
        + 2 * max_parent_profiles
    )
    groups: dict[tuple[str, int], list[dict]] = {}
    for seed in sorted(rows, key=_sort_key):
        target = seed["target"]
        assert isinstance(target, Mapping)
        key = (str(target["country_region"]), _edition_year(seed))
        groups.setdefault(key, []).append(seed)

    batches = []
    ordinal = 0
    for (region, year), seeds in sorted(groups.items()):
        for offset in range(0, len(seeds), batch_size_cap):
            ordinal += 1
            batch_rows = seeds[offset : offset + batch_size_cap]
            filename = f"{ordinal:04d}-{region}-{year}-{offset // batch_size_cap + 1:02d}.jsonl"
            path = output_dir / "seed-ledgers" / filename
            payload = "".join(f"{canonical_json(row)}\n" for row in batch_rows).encode("utf-8")
            _atomic_write(path, payload)
            ceiling = len(batch_rows) * per_seed_ceiling
            batches.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "batch_id": filename.removesuffix(".jsonl"),
                    "ordinal": ordinal,
                    "country_region": region,
                    "edition_year": year,
                    "seed_count": len(batch_rows),
                    "request_ceiling": ceiling,
                    "theoretical_min_duration_seconds": ceiling * min_interval_ms / 1000,
                    "not_before_offset_minutes": (ordinal - 1) * spacing_minutes,
                    "approval_status": "proposed_not_approved",
                    "seed_ledger": {
                        "path": str(path.relative_to(output_dir)),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size": len(payload),
                        "rows": len(batch_rows),
                    },
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "batch-plan.jsonl"
    _atomic_write(plan_path, "".join(f"{canonical_json(row)}\n" for row in batches).encode("utf-8"))
    region_counts = Counter(str(seed["target"]["country_region"]) for seed in rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROPOSED_NOT_APPROVED",
        "completion_marker": "PREPARED",
        "approval": False,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "seed_artifact": {
            "root": str(root),
            "manifest_sha256": approved_seed_manifest_sha256,
            "ledger_sha256": approved_seed_ledger_sha256,
            "rows": len(rows),
            "target_manifest_sha256": seed_manifest.get("target_manifest_sha256"),
            "target_ledger_sha256": seed_manifest.get("target_ledger_sha256"),
        },
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
        },
        "counts": {
            "seeds": len(rows),
            "batches": len(batches),
            "request_ceiling": sum(row["request_ceiling"] for row in batches),
            "theoretical_min_duration_seconds": sum(
                row["theoretical_min_duration_seconds"] for row in batches
            ),
            "schedule_span_minutes": (len(batches) - 1) * spacing_minutes,
            "by_region": dict(sorted(region_counts.items())),
        },
        "batch_plan": {
            "path": plan_path.name,
            "sha256": sha256_path(plan_path),
            "size": plan_path.stat().st_size,
            "rows": len(batches),
        },
        "execution_blockers": [
            "each network batch requires a separate exact G3 approval",
            "each network batch requires a fresh exclusive-account proof",
        ],
        "prior_probe_context": {
            "montjeu_status": "provider_partial",
            "effect": "does_not_block_post_2021_batches_but_forbids_inferring_pre_2000_completeness",
        },
    }
    manifest_path = output_dir / "batch-plan-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", f"{sha256_path(manifest_path)}\n".encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-root", required=True, type=Path)
    parser.add_argument("--approved-seed-manifest-sha256", required=True)
    parser.add_argument("--approved-seed-ledger-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--batch-size-cap", type=int, default=20)
    parser.add_argument("--max-search-candidates", type=int, default=3)
    parser.add_argument("--max-results-pages-per-horse", type=int, default=3)
    parser.add_argument("--max-parent-profiles", type=int, default=2)
    parser.add_argument("--min-interval-ms", type=int, default=250)
    parser.add_argument("--spacing-minutes", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    print(canonical_json(prepare_batch_plan(**vars(parse_args()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
