#!/usr/bin/env python3
"""离线验证受审官方赛果 manifest/gap/summary 三文件包。"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from runtime.research.build_official_graded_race_manifest import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_FILES = {
    "official_result_manifest.json",
    "official_result_gaps.json",
    "summary.json",
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PackageValidationError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PackageValidationError(f"package member must be a regular non-symlink file: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageValidationError(f"package member JSON is invalid: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PackageValidationError(f"package member root is invalid: {path.name}")
    return payload


def validate_package(root: Path, *, year: int, expected_summary_sha256: str) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise PackageValidationError("package path must be a regular non-symlink directory")
    actual_files = {item.name for item in root.iterdir()}
    if actual_files != EXPECTED_FILES:
        raise PackageValidationError("package file set is not exact")
    summary_path = root / "summary.json"
    if not SHA_RE.fullmatch(expected_summary_sha256) or sha256_file(summary_path) != expected_summary_sha256:
        raise PackageValidationError("package summary SHA-256 mismatch")
    manifest = _load_json(root / "official_result_manifest.json")
    gaps = _load_json(root / "official_result_gaps.json")
    summary = _load_json(summary_path)
    for name, payload in (("manifest", manifest), ("gaps", gaps), ("summary", summary)):
        if payload.get("schema_version") != 1 or payload.get("year") != year:
            raise PackageValidationError(f"package {name} identity drift")
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest))
    gaps_sha = sha256_bytes(canonical_json_bytes(gaps))
    if summary.get("official_result_manifest_sha256") != manifest_sha:
        raise PackageValidationError("package manifest SHA-256 drift")
    if summary.get("official_result_gaps_sha256") != gaps_sha:
        raise PackageValidationError("package gaps SHA-256 drift")
    catalog_sha = summary.get("catalog_set_sha256")
    review_sha = summary.get("reviewed_mapping_sha256")
    if not isinstance(catalog_sha, str) or not SHA_RE.fullmatch(catalog_sha):
        raise PackageValidationError("package catalog SHA-256 is invalid")
    if not isinstance(review_sha, str) or not SHA_RE.fullmatch(review_sha):
        raise PackageValidationError("package review SHA-256 is invalid")
    if manifest.get("catalog_sha256") != catalog_sha or gaps.get("catalog_set_sha256") != catalog_sha:
        raise PackageValidationError("package catalog binding drift")
    if manifest.get("reviewed_mapping_sha256") != review_sha or gaps.get("reviewed_mapping_sha256") != review_sha:
        raise PackageValidationError("package review binding drift")
    package_identity = {
        "catalog_set_sha256": catalog_sha,
        "reviewed_mapping_sha256": review_sha,
        "official_result_manifest_sha256": manifest_sha,
        "official_result_gaps_sha256": gaps_sha,
    }
    if summary.get("package_sha256") != sha256_bytes(canonical_json_bytes(package_identity)):
        raise PackageValidationError("package identity SHA-256 drift")
    races = manifest.get("races")
    gap_rows = gaps.get("gaps")
    if not isinstance(races, list) or not isinstance(gap_rows, list):
        raise PackageValidationError("package row collections are invalid")
    race_keys = [str(item.get("race_key") or "") for item in races if isinstance(item, dict)]
    gap_keys = [str(item.get("catalog_key") or "") for item in gap_rows if isinstance(item, dict)]
    if len(race_keys) != len(races) or len(gap_keys) != len(gap_rows):
        raise PackageValidationError("package row is invalid")
    if not all(race_keys + gap_keys) or len(set(race_keys + gap_keys)) != len(race_keys) + len(gap_keys):
        raise PackageValidationError("package race/gap keys are blank, duplicated, or overlapping")
    expected_counts = (
        summary.get("catalog_count"),
        summary.get("collect_count"),
        summary.get("gap_count"),
    )
    actual_counts = (len(races) + len(gap_rows), len(races), len(gap_rows))
    if expected_counts != actual_counts:
        raise PackageValidationError("package conservation drift")
    return {
        "schema_version": 1,
        "year": year,
        "summary_sha256": expected_summary_sha256,
        "package_sha256": summary["package_sha256"],
        "catalog_count": actual_counts[0],
        "collect_count": actual_counts[1],
        "gap_count": actual_counts[2],
        "manifest_sha256": manifest_sha,
    }


def _resolve_repo_package(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise PackageValidationError("package path must be repository-relative without parent traversal")
    candidate = REPO_ROOT / relative
    current = REPO_ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PackageValidationError("package path must not contain symlinks")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(REPO_ROOT):
        raise PackageValidationError("package path resolves outside repository")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="验证官方赛果受审三文件包")
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--year", required=True, type=int)
    args = parser.parse_args()
    try:
        result = validate_package(
            _resolve_repo_package(args.package_dir),
            year=args.year,
            expected_summary_sha256=args.summary_sha256,
        )
    except (OSError, PackageValidationError, ValueError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
