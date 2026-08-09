#!/usr/bin/env python3
"""把既有七文件与新增地区官方赛果收口为一个 SHA 绑定的年度研究 bundle。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.research.build_official_graded_race_manifest import (  # noqa: E402
    atomic_write,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from runtime.research.validate_official_graded_race_package import validate_package  # noqa: E402


LEGACY_FILES = {
    "source_manifest.jsonl",
    "summary.json",
    "errors.json",
    "README.md",
}
OFFICIAL_FILES = {
    "official_participants.jsonl",
    "official_sources.jsonl",
    "summary.json",
}


class BundleBuildError(ValueError):
    pass


def _regular_files(root: Path, expected: set[str], *, label: str) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise BundleBuildError(f"{label} path must be a regular non-symlink directory")
    actual = {item.name for item in root.iterdir()}
    if actual != expected:
        raise BundleBuildError(f"{label} file set is not exact")
    identities = {}
    for name in sorted(expected):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise BundleBuildError(f"{label} member must be a regular non-symlink file: {name}")
        identities[name] = sha256_file(path)
    return identities


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleBuildError(f"{label} JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise BundleBuildError(f"{label} root is invalid")
    return payload


def build_bundle(
    *,
    year: int,
    legacy_dir: Path,
    official_dir: Path,
    reviewed_package_dir: Path,
    reviewed_summary_sha256: str,
) -> dict[str, Any]:
    legacy_expected = {
        *LEGACY_FILES,
        f"race_participants_{year}.csv",
        f"horse_names_{year}.csv",
        f"horse_name_review_queue_{year}.csv",
    }
    legacy_files = _regular_files(legacy_dir, legacy_expected, label="legacy artifact")
    official_files = _regular_files(official_dir, OFFICIAL_FILES, label="official artifact")
    legacy_summary = _load_json(legacy_dir / "summary.json", label="legacy summary")
    if (
        legacy_summary.get("schema_version") != 1
        or legacy_summary.get("year") != year
        or legacy_summary.get("outcome") not in {"complete", "partial"}
        or not isinstance(legacy_summary.get("counts"), dict)
    ):
        raise BundleBuildError("legacy summary identity is invalid")
    package = validate_package(
        reviewed_package_dir,
        year=year,
        expected_summary_sha256=reviewed_summary_sha256,
    )
    official_summary = _load_json(official_dir / "summary.json", label="official summary")
    if (
        official_summary.get("schema_version") != 1
        or official_summary.get("status") != "complete"
        or official_summary.get("year") != year
    ):
        raise BundleBuildError("official summary is not complete for requested year")
    if official_summary.get("manifest_sha256") != package["manifest_sha256"]:
        raise BundleBuildError("official result manifest binding drift")
    if official_summary.get("race_count") != package["collect_count"]:
        raise BundleBuildError("official collected race count drift")
    for name in ("official_participants.jsonl", "official_sources.jsonl"):
        if (official_summary.get("files") or {}).get(name) != official_files[name]:
            raise BundleBuildError(f"official summary file SHA drift: {name}")
    file_identity = {
        **{f"legacy/{name}": digest for name, digest in legacy_files.items()},
        **{f"official/{name}": digest for name, digest in official_files.items()},
        **{
            f"reviewed_package/{name}": sha256_file(reviewed_package_dir / name)
            for name in sorted(
                {
                    "official_result_manifest.json",
                    "official_result_gaps.json",
                    "summary.json",
                }
            )
        },
    }
    identity = {
        "year": year,
        "reviewed_package_sha256": package["package_sha256"],
        "files": file_identity,
    }
    return {
        "schema_version": "graded-race-completion-bundle.v1",
        **identity,
        "bundle_sha256": sha256_bytes(canonical_json_bytes(identity)),
        "counts": {
            "legacy_outcome": legacy_summary["outcome"],
            "legacy_races": legacy_summary["counts"].get("included_races"),
            "legacy_participants": legacy_summary["counts"].get("participant_rows"),
            "official_catalog": package["catalog_count"],
            "official_collected": package["collect_count"],
            "official_gaps": package["gap_count"],
            "official_participants": official_summary.get("participant_count"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成年度分级赛完整研究 bundle manifest")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--legacy-dir", required=True)
    parser.add_argument("--official-dir", required=True)
    parser.add_argument("--reviewed-package-dir", required=True)
    parser.add_argument("--reviewed-summary-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        payload = build_bundle(
            year=args.year,
            legacy_dir=Path(args.legacy_dir),
            official_dir=Path(args.official_dir),
            reviewed_package_dir=Path(args.reviewed_package_dir),
            reviewed_summary_sha256=args.reviewed_summary_sha256,
        )
        output = Path(args.output)
        if output.exists() or output.is_symlink():
            raise BundleBuildError("bundle manifest output already exists")
        atomic_write(output, canonical_json_bytes(payload))
    except (OSError, BundleBuildError, ValueError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
