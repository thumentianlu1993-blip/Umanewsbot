#!/usr/bin/env python3
"""Audit an immutable legacy race-detail bundle against a target ledger.

This tool is deliberately read-only with respect to Django and databases.  It
only verifies file identities, validates complete result/runner modules, and
classifies bundle rows as exact target matches or manual-review candidates.
It never treats a PREPARED target ledger as reviewed COMPLETE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "legacy-historical-detail-bundle-audit.v1"
TARGET_SCHEMA_VERSION = "graded-horse-target-ledger.v1"
BUNDLE_ARTIFACT_KIND = "historical_race_detail_source_bundle"
COUNTRY_SUFFIX_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<country>[A-Z]{2,3})\)\s*$")


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
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


def _require_regular(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _read_json(path: Path, *, label: str) -> dict:
    resolved = _require_regular(path, label=label)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _read_jsonl(path: Path, *, label: str) -> list[dict]:
    resolved = _require_regular(path, label=label)
    rows = []
    try:
        with resolved.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{label} row {line_number} is not an object")
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return rows


def _safe_child(root: Path, relative_path: object, *, label: str) -> Path:
    text = str(relative_path or "")
    if not text or Path(text).is_absolute():
        raise ValueError(f"{label} path must be relative")
    candidate = root / text
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError(f"{label} escapes artifact root")
    return _require_regular(candidate, label=label)


def _verify_identity(
    root: Path, identity: object, *, label: str, require_size: bool = True
) -> Path:
    if not isinstance(identity, Mapping):
        raise ValueError(f"{label} identity is missing")
    path = _safe_child(root, identity.get("path"), label=label)
    expected_size = identity.get("size")
    expected_sha = str(identity.get("sha256") or "").lower()
    size_invalid = require_size and (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or path.stat().st_size != expected_size
    )
    if size_invalid or sha256_path(path) != expected_sha:
        raise ValueError(f"{label} identity mismatch")
    return path


def _safe_https(url: object) -> bool:
    parsed = urlparse(str(url or ""))
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def load_target_artifact(root: Path) -> tuple[list[dict], dict]:
    resolved_root = root.resolve(strict=True)
    if root.is_symlink() or not resolved_root.is_dir():
        raise ValueError("target artifact root must be a regular directory")
    manifest_path = _require_regular(
        resolved_root / "target-ledger-manifest.json", label="target manifest"
    )
    manifest = _read_json(manifest_path, label="target manifest")
    if manifest.get("schema_version") != TARGET_SCHEMA_VERSION:
        raise ValueError("target manifest schema is unsupported")
    ledger_identity = manifest.get("target_ledger")
    ledger_path = _verify_identity(
        resolved_root,
        ledger_identity,
        label="target ledger",
        require_size=False,
    )
    rows = _read_jsonl(ledger_path, label="target ledger")
    if not isinstance(ledger_identity, Mapping) or ledger_identity.get("rows") != len(rows):
        raise ValueError("target ledger row count mismatch")
    by_key = {}
    for row in rows:
        key = str(row.get("target_key") or "")
        if (
            row.get("schema_version") != TARGET_SCHEMA_VERSION
            or not key
            or key in by_key
        ):
            raise ValueError("target ledger identity is invalid or duplicated")
        by_key[key] = row
    marker_name = str(manifest.get("completion_marker") or "")
    marker_path = _require_regular(resolved_root / marker_name, label="target marker")
    marker_bound = (
        marker_path.read_text(encoding="ascii").strip() == sha256_path(manifest_path)
    )
    if not marker_bound:
        raise ValueError("target marker does not bind target manifest")
    reviewed_complete = (
        marker_name == "COMPLETE"
        and manifest.get("status") == "complete"
        and manifest.get("blocking_source_count_conflicts") in (None, [])
    )
    return rows, {
        "root": str(resolved_root),
        "manifest_sha256": sha256_path(manifest_path),
        "ledger_sha256": sha256_path(ledger_path),
        "row_count": len(rows),
        "marker": marker_name,
        "reviewed_complete": reviewed_complete,
    }


def load_legacy_bundle(root: Path) -> tuple[list[dict], list[dict], dict]:
    resolved_root = root.resolve(strict=True)
    if root.is_symlink() or not resolved_root.is_dir():
        raise ValueError("legacy bundle root must be a regular directory")
    manifest_path = _require_regular(resolved_root / "manifest.json", label="bundle manifest")
    manifest = _read_json(manifest_path, label="bundle manifest")
    if manifest.get("artifact_kind") != BUNDLE_ARTIFACT_KIND:
        raise ValueError("legacy bundle artifact kind is unsupported")
    rows = []
    layers = manifest.get("layers")
    if not isinstance(layers, Mapping):
        raise ValueError("legacy bundle layers are missing")
    for layer_name, layer in sorted(layers.items()):
        if not isinstance(layer, Mapping) or not isinstance(layer.get("chunks"), list):
            raise ValueError("legacy bundle layer is invalid")
        for chunk in layer["chunks"]:
            if not isinstance(chunk, Mapping):
                raise ValueError("legacy bundle chunk is invalid")
            _verify_identity(resolved_root, chunk.get("manifest"), label="chunk manifest")
            candidate_path = _verify_identity(
                resolved_root, chunk.get("candidates"), label="chunk candidates"
            )
            chunk_rows = _read_jsonl(candidate_path, label="chunk candidates")
            if chunk.get("target_count") != len(chunk_rows):
                raise ValueError("chunk target count mismatch")
            for row in chunk_rows:
                row = dict(row)
                row["_bundle_layer"] = str(layer_name)
                row["_bundle_chunk"] = str(chunk.get("chunk_id") or "")
                row["_bundle_candidate_path"] = str(candidate_path)
                rows.append(row)
    outputs = manifest.get("outputs")
    gap_identity = outputs.get("gaps.jsonl") if isinstance(outputs, Mapping) else None
    if gap_identity is None:
        layer_gap_count = sum(
            int(layer.get("gap_count") or 0)
            for layer in layers.values()
            if isinstance(layer, Mapping)
        )
        if layer_gap_count:
            raise ValueError("compact legacy bundle omits non-zero gap identities")
        gaps = []
    else:
        gap_path = _verify_identity(resolved_root, gap_identity, label="bundle gaps")
        gaps = _read_jsonl(gap_path, label="bundle gaps")
    expected_scope_count = manifest.get("scope_count")
    if expected_scope_count is None:
        expected_scope_count = len(rows) + len(gaps)
    expected_gap_count = manifest.get("gap_count")
    if expected_gap_count is None:
        expected_gap_count = len(gaps)
    if (
        manifest.get("record_count") != len(rows)
        or expected_gap_count != len(gaps)
        or expected_scope_count != len(rows) + len(gaps)
    ):
        raise ValueError("legacy bundle conserved counts are invalid")
    return rows, gaps, {
        "root": str(resolved_root),
        "manifest_sha256": sha256_path(manifest_path),
        "scope_count": len(rows) + len(gaps),
        "record_count": len(rows),
        "gap_count": len(gaps),
    }


def _validated_candidate(
    row: Mapping[str, object], *, bundle_root: Path
) -> dict:
    pending = row.get("pending_target")
    modules = row.get("modules")
    source = row.get("source")
    if not isinstance(pending, Mapping) or not isinstance(modules, Mapping):
        raise ValueError("legacy candidate target/modules are missing")
    if not isinstance(source, Mapping) or not _safe_https(source.get("url")):
        raise ValueError("legacy candidate source URL is invalid")
    try:
        local_date = date.fromisoformat(str(row.get("local_date") or ""))
    except ValueError as exc:
        raise ValueError("legacy candidate local_date is invalid") from exc
    year = pending.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or local_date.year != year:
        raise ValueError("legacy candidate year/date mismatch")
    runner_module = modules.get("runners")
    result_module = modules.get("results")
    if not isinstance(runner_module, Mapping) or not isinstance(result_module, Mapping):
        raise ValueError("legacy candidate result modules are missing")
    runners = runner_module.get("items")
    results = result_module.get("items")
    if (
        runner_module.get("is_complete") is not True
        or result_module.get("is_complete") is not True
        or not isinstance(runners, list)
        or not isinstance(results, list)
        or not runners
        or not results
    ):
        raise ValueError("legacy candidate result modules are incomplete")
    if any(not str(item.get("horse_name") or "").strip() for item in runners + results):
        raise ValueError("legacy candidate contains unnamed horses")
    target_id = pending.get("target_id")
    if not isinstance(target_id, int) or isinstance(target_id, bool):
        raise ValueError("legacy candidate target_id is invalid")
    candidate_path = Path(str(row.get("_bundle_candidate_path") or ""))
    chunk_root = candidate_path.parent
    source_path = chunk_root / "sources" / f"target-{target_id}.html"
    source_identity = row.get("approved_source_cache_identity")
    if not isinstance(source_identity, Mapping):
        raise ValueError("legacy candidate source cache identity is missing")
    source_file = _require_regular(source_path, label="legacy candidate source cache")
    if (
        source_file.stat().st_size != source_identity.get("size")
        or sha256_path(source_file) != str(source_identity.get("sha256") or "").lower()
        or str(source_identity.get("source_url") or "") != str(source.get("url") or "")
    ):
        raise ValueError("legacy candidate source cache identity mismatch")
    if not source_file.resolve().is_relative_to(bundle_root.resolve()):
        raise ValueError("legacy candidate source cache escapes bundle")
    result_names = [str(item.get("horse_name") or "").strip() for item in results]
    winners = []
    for result in results:
        refs = result.get("source_refs")
        refs = refs if isinstance(refs, Mapping) else {}
        raw_position = (
            result.get("official_finish_position")
            or refs.get("official_finish_position")
            or result.get("finish_position")
        )
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if position == 1:
            raw_name = str(refs.get("horse_name_raw") or result.get("horse_name") or "").strip()
            suffix_match = COUNTRY_SUFFIX_RE.fullmatch(raw_name)
            winners.append(
                {
                    "name": (
                        suffix_match.group("name").strip()
                        if suffix_match
                        else str(result.get("horse_name") or raw_name).strip()
                    ),
                    "country_suffix": suffix_match.group("country") if suffix_match else "",
                    "expected_finish_position": "1",
                    "source_name_raw": raw_name,
                }
            )
    if not winners:
        raise ValueError("legacy candidate has no position-1 anchor")
    winners.sort(
        key=lambda winner: (
            str(winner["name"]).casefold(),
            str(winner["country_suffix"]),
        )
    )
    return {
        "legacy_target_id": target_id,
        "region": str(pending.get("region") or ""),
        "year": year,
        "legacy_series_key": str(pending.get("series_key") or ""),
        "local_date": local_date.isoformat(),
        "source_url": str(source.get("url") or ""),
        "source_cache_sha256": sha256_path(source_file),
        "source_cache_size": source_file.stat().st_size,
        "actual_starter_count": len(results),
        "declared_runner_count": len(runners),
        "actual_starter_names": result_names,
        "anchor_horse": winners[0],
        "winner_anchor_count": len(winners),
        "bundle_layer": str(row.get("_bundle_layer") or ""),
        "bundle_chunk": str(row.get("_bundle_chunk") or ""),
    }


def audit_bundle(
    *, target_root: Path, bundle_root: Path, output_dir: Path
) -> dict:
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("output directory must be absent or empty")
    target_rows, target_identity = load_target_artifact(target_root)
    bundle_rows, bundle_gaps, bundle_identity = load_legacy_bundle(bundle_root)
    target_index: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for target in target_rows:
        target_index[
            (
                str(target.get("country_region") or ""),
                int(target.get("year") or 0),
                str(target.get("series_key") or ""),
            )
        ].append(target)
    exact = []
    review = []
    for source in bundle_rows:
        item = _validated_candidate(source, bundle_root=bundle_root)
        matches = target_index.get(
            (item["region"], item["year"], item["legacy_series_key"]), []
        )
        if len(matches) == 1:
            target = matches[0]
            item.update(
                {
                    "match_status": "exact_series_year_unique",
                    "target_key": target["target_key"],
                    "target_series_key": target["series_key"],
                    "discipline": target["discipline"],
                    "grade_text": target["grade_text"],
                    "target_artifact_reviewed_complete": target_identity[
                        "reviewed_complete"
                    ],
                    "target": {
                        "year": target["year"],
                        "country_region": target["country_region"],
                        "local_date": item["local_date"],
                        "canonical_name_original": target.get(
                            "canonical_name_original"
                        ),
                        "race_name_aliases": list(
                            dict.fromkeys(
                                value
                                for value in (
                                    target.get("original_name"),
                                    target.get("canonical_name_original"),
                                )
                                if value
                            )
                        ),
                        "racecourse": target.get("racecourse"),
                        "grade_text": target["grade_text"],
                        "discipline": target["discipline"],
                    },
                }
            )
            exact.append(item)
        else:
            item.update(
                {
                    "match_status": (
                        "target_match_missing" if not matches else "target_match_not_unique"
                    ),
                    "candidate_target_keys": [row["target_key"] for row in matches],
                }
            )
            review.append(item)
    normalized_gaps = []
    for gap in bundle_gaps:
        item = {
            "legacy_target_id": gap.get("target_id"),
            "region": gap.get("region"),
            "year": gap.get("year"),
            "legacy_series_key": gap.get("series_key"),
            "reason_code": gap.get("reason_code"),
            "source_url": (gap.get("source_gap") or {}).get("source_url")
            if isinstance(gap.get("source_gap"), Mapping)
            else "",
        }
        matches = target_index.get(
            (
                str(item["region"] or ""),
                int(item["year"] or 0),
                str(item["legacy_series_key"] or ""),
            ),
            [],
        )
        item["candidate_target_keys"] = [row["target_key"] for row in matches]
        normalized_gaps.append(item)
    exact.sort(key=lambda row: (row["region"], row["local_date"], row["target_key"]))
    review.sort(
        key=lambda row: (row["region"], row["local_date"], row["legacy_series_key"])
    )
    normalized_gaps.sort(
        key=lambda row: (str(row["region"]), int(row["year"] or 0), str(row["legacy_series_key"]))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = (
        (output_dir / "exact-target-matches.jsonl", exact),
        (output_dir / "manual-review-candidates.jsonl", review),
        (output_dir / "legacy-gaps.jsonl", normalized_gaps),
    )
    for path, rows in outputs:
        _atomic_write(
            path,
            "".join(f"{canonical_json(row)}\n" for row in rows).encode("utf-8"),
        )
    counts = Counter(
        (row["year"], row["grade_text"], row["discipline"]) for row in exact
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "review_required",
        "database_writes": 0,
        "target_artifact": target_identity,
        "legacy_bundle": bundle_identity,
        "exact_target_match_count": len(exact),
        "manual_review_candidate_count": len(review),
        "legacy_gap_count": len(normalized_gaps),
        "exact_actual_starter_count": sum(row["actual_starter_count"] for row in exact),
        "exact_unique_starter_name_count": len(
            {
                name.casefold()
                for row in exact
                for name in row["actual_starter_names"]
            }
        ),
        "counts": [
            {
                "year": key[0],
                "grade_text": key[1],
                "discipline": key[2],
                "count": count,
            }
            for key, count in sorted(counts.items())
        ],
        "outputs": {
            path.name: {
                "sha256": sha256_path(path),
                "size": path.stat().st_size,
                "rows": len(rows),
            }
            for path, rows in outputs
        },
    }
    manifest_path = output_dir / "audit-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    _atomic_write(
        output_dir / "AUDITED",
        f"{sha256_path(manifest_path)}\n".encode("ascii"),
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = audit_bundle(
        target_root=args.target_root,
        bundle_root=args.bundle_root,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
