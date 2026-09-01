#!/usr/bin/env python3
"""Prepare bounded Wikipedia winner-source events for uncovered graded targets.

This is an artifact-only planner.  It subtracts exact TOBA target bindings and
exact winner rows already present in frozen history payloads from the reviewed
2005-2025 target denominator, then groups the remaining targets by race series.
It performs no network or database work and does not approve any source row.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_VERSION = "graded-winner-source-events.v1"
TARGET_SCHEMA_VERSION = "graded-horse-target-ledger.v1"
REGIONS = frozenset({"france", "ireland", "united_kingdom", "united_states"})
OUTPUT_NAMES = frozenset({"events.csv", "uncovered-targets.jsonl"})


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _require_sha(path: Path, expected: str, *, label: str) -> Path:
    resolved = _regular(path, label=label)
    if sha256_path(resolved) != expected:
        raise ValueError(f"{label} SHA-256 mismatch")
    return resolved


def _jsonl(path: Path, *, label: str) -> list[dict]:
    rows: list[dict] = []
    try:
        for ordinal, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{label} row {ordinal} must be an object")
            rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSONL") from exc
    return rows


def _identity(path: Path, *, rows: int | None = None) -> dict:
    value = {"path": path.name, "sha256": sha256_path(path), "size": path.stat().st_size}
    if rows is not None:
        value["rows"] = rows
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _target_rows(path: Path, expected_sha256: str) -> list[dict]:
    source = _require_sha(path, expected_sha256, label="target ledger")
    rows = _jsonl(source, label="target ledger")
    keys: set[str] = set()
    selected: list[dict] = []
    for ordinal, row in enumerate(rows, 1):
        target_key = str(row.get("target_key") or "")
        region = str(row.get("country_region") or "")
        series = str(row.get("series_key") or "")
        year = int(row.get("year") or 0)
        if (
            row.get("schema_version") != TARGET_SCHEMA_VERSION
            or not target_key
            or target_key in keys
            or region not in REGIONS
            or not series
        ):
            raise ValueError(f"target ledger row {ordinal} contract drift")
        keys.add(target_key)
        if 2005 <= year <= 2025:
            selected.append(row)
    if not selected:
        raise ValueError("target ledger has no 2005-2025 targets")
    return selected


def _toba_keys(path: Path, expected_sha256: str, target_keys: set[str]) -> set[str]:
    source = _require_sha(path, expected_sha256, label="TOBA automatic bindings")
    rows = _jsonl(source, label="TOBA automatic bindings")
    keys: set[str] = set()
    for ordinal, row in enumerate(rows, 1):
        target_key = str(row.get("target_key") or "")
        if (
            row.get("adapter_key") != "toba"
            or row.get("country_region") != "united_states"
            or not target_key
            or target_key in keys
            or not str(row.get("anchor_horse_name") or "").strip()
        ):
            raise ValueError(f"TOBA binding row {ordinal} contract drift")
        keys.add(target_key)
    return keys & target_keys


def _history_keys(
    specs: Iterable[tuple[str, Path, str]], target_keys: set[tuple[str, str, int]]
) -> tuple[set[tuple[str, str, int]], list[dict]]:
    covered: set[tuple[str, str, int]] = set()
    identities: list[dict] = []
    for region, path, expected_sha256 in specs:
        if region not in REGIONS:
            raise ValueError(f"unsupported history region: {region}")
        source = _require_sha(path, expected_sha256, label=f"{region} history")
        records = _jsonl(source, label=f"{region} history")
        local_keys: set[tuple[str, str, int]] = set()
        for ordinal, record in enumerate(records, 1):
            slug = str(record.get("slug") or "")
            modules = record.get("modules")
            items = (
                ((modules.get("history_winners") or {}).get("items") or [])
                if isinstance(modules, Mapping)
                else []
            )
            if not slug or not isinstance(items, list):
                raise ValueError(f"{region} history row {ordinal} contract drift")
            for item in items:
                if not isinstance(item, Mapping):
                    raise ValueError(f"{region} history item contract drift")
                year = int(item.get("winner_year") or 0)
                horse = str(item.get("horse_name") or "").strip()
                key = (region, slug, year)
                if not horse or key in local_keys:
                    raise ValueError(f"{region} history winner identity drift")
                local_keys.add(key)
                if key in target_keys:
                    covered.add(key)
        identities.append(
            {
                "region": region,
                "path": str(source),
                "sha256": expected_sha256,
                "records": len(records),
                "matched_target_occurrences": len(local_keys & target_keys),
            }
        )
    return covered, identities


def _parse_history_specs(values: list[str]) -> list[tuple[str, Path, str]]:
    specs: list[tuple[str, Path, str]] = []
    for value in values:
        parts = value.split("=", 2)
        if len(parts) != 3 or not all(parts):
            raise ValueError("history input must be REGION=PATH=SHA256")
        specs.append((parts[0], Path(parts[1]), parts[2]))
    regions = [row[0] for row in specs]
    if len(regions) != len(set(regions)):
        raise ValueError("history region inputs must be unique")
    return specs


def prepare(
    *,
    target_ledger: Path,
    expected_target_sha256: str,
    toba_bindings: Path,
    expected_toba_sha256: str,
    history_inputs: list[str],
    output_dir: Path,
) -> dict:
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("output directory must be absent or empty")
    targets = _target_rows(target_ledger, expected_target_sha256)
    target_keys = {str(row["target_key"]) for row in targets}
    target_occurrences = {
        (str(row["country_region"]), str(row["series_key"]), int(row["year"]))
        for row in targets
    }
    if len(target_occurrences) != len(targets):
        raise ValueError("target occurrence identity is not unique")
    toba_covered = _toba_keys(toba_bindings, expected_toba_sha256, target_keys)
    history_covered, history_identities = _history_keys(
        _parse_history_specs(history_inputs), target_occurrences
    )

    uncovered = [
        row
        for row in targets
        if str(row["target_key"]) not in toba_covered
        and (
            str(row["country_region"]),
            str(row["series_key"]),
            int(row["year"]),
        )
        not in history_covered
    ]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in uncovered:
        grouped[(str(row["country_region"]), str(row["series_key"]))].append(row)
    events: list[dict] = []
    for (region, series), rows in sorted(grouped.items()):
        rows.sort(key=lambda item: (int(item["year"]), str(item["target_key"])))
        names = Counter(
            str(row.get("canonical_name_original") or row.get("original_name") or "").strip()
            for row in rows
        )
        if "" in names:
            raise ValueError(f"uncovered series has no source query name: {region}:{series}")
        query = sorted(names, key=lambda name: (-names[name], -len(name), name.casefold()))[0]
        years = sorted(int(row["year"]) for row in rows)
        events.append(
            {
                "year": years[0],
                "slug": series,
                "series_key": series,
                "original_name": query,
                "target_count": len(rows),
                "target_years": ",".join(str(year) for year in years),
                "country_region": region,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    events_path = output_dir / "events.csv"
    with events_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "year",
                "slug",
                "series_key",
                "original_name",
                "target_count",
                "target_years",
                "country_region",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(events)
    uncovered_path = output_dir / "uncovered-targets.jsonl"
    uncovered.sort(key=lambda row: (int(row["year"]), str(row["target_key"])))
    _atomic_write(
        uncovered_path,
        "".join(canonical_json(row) + "\n" for row in uncovered).encode("utf-8"),
    )
    counts = {
        "target_occurrences_2005_2025": len(targets),
        "covered_by_toba": len(toba_covered),
        "covered_by_frozen_history": len(history_covered),
        "uncovered_target_occurrences": len(uncovered),
        "source_events": len(events),
        "by_region": dict(sorted(Counter(row["country_region"] for row in uncovered).items())),
    }
    if counts["covered_by_toba"] + counts["covered_by_frozen_history"] + len(uncovered) != len(targets):
        raise ValueError("source event conservation drift")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PREPARED_NOT_APPROVED",
        "approval": False,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "year_window": {"minimum": 2005, "maximum": 2025},
        "target_ledger": {
            "path": str(_regular(target_ledger, label="target ledger")),
            "sha256": expected_target_sha256,
            "selected_rows": len(targets),
        },
        "toba_bindings": {
            "path": str(_regular(toba_bindings, label="TOBA automatic bindings")),
            "sha256": expected_toba_sha256,
            "matched_target_occurrences": len(toba_covered),
        },
        "frozen_histories": history_identities,
        "counts": counts,
        "outputs": {
            events_path.name: _identity(events_path, rows=len(events)),
            uncovered_path.name: _identity(uncovered_path, rows=len(uncovered)),
        },
        "next_gate": "bounded_source_capture_and_exact_offline_replay",
    }
    manifest_path = output_dir / "event-manifest.json"
    _atomic_write(manifest_path, (canonical_json(manifest) + "\n").encode("utf-8"))
    manifest_sha = sha256_path(manifest_path)
    _atomic_write(output_dir / "PREPARED", (manifest_sha + "\n").encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-ledger", required=True, type=Path)
    parser.add_argument("--expected-target-sha256", required=True)
    parser.add_argument("--toba-bindings", required=True, type=Path)
    parser.add_argument("--expected-toba-sha256", required=True)
    parser.add_argument("--history-input", action="append", default=[])
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = prepare(
        target_ledger=args.target_ledger,
        expected_target_sha256=args.expected_target_sha256,
        toba_bindings=args.toba_bindings,
        expected_toba_sha256=args.expected_toba_sha256,
        history_inputs=args.history_input,
        output_dir=args.output_dir,
    )
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
