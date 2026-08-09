#!/usr/bin/env python3
"""把 TJCIS 新地区目录与逐场人工复核 URL 编译为官方赛果 runner manifest。

本工具完全离线。prepare 生成精确 review queue；compile 只接受 SHA 绑定且逐场完整的
reviewed mapping，不做名称模糊匹配，也不访问网络或数据库。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.research.official_graded_race_sources import (  # noqa: E402
    DISTANCE_OVERRIDE_REASON,
    POLICIES,
    canonical_au_selector_identity,
    canonical_provider_url_identity,
    validate_provider_url,
)


SCHEMA_VERSION = 1
TOOL_VERSION = "official-race-manifest.v2"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TARGET_REGIONS = {"australia", "germany", "middle_east"}
PROVIDER_BY_GEOGRAPHY = {
    ("australia", "australia"): "au_racing_australia",
    ("germany", "germany"): "de_deutscher_galopp",
    ("middle_east", "united_arab_emirates"): "uae_era",
    ("middle_east", "saudi_arabia"): "sa_jcsa",
    ("middle_east", "qatar"): "qa_qrec",
    ("middle_east", "bahrain"): "bh_btc",
}
GAP_REASONS = {
    "official_results_not_published",
    "stable_public_result_unavailable",
    "race_identity_ambiguous",
    "official_date_unresolved",
}


class ManifestBuildError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ManifestBuildError(f"input must be a regular non-symlink file: {path}")
    return path.resolve(strict=True)


def _catalog_key(row: dict[str, str]) -> str:
    identity = {
        key: str(row.get(key) or "").strip()
        for key in (
            "country_region", "country", "year", "series_key", "canonical_name_original",
            "grade_text", "racecourse", "distance_text", "surface", "expectation_status",
        )
    }
    return sha256_bytes(canonical_json_bytes(identity))


def load_catalogs(paths: list[Path], *, year: int) -> tuple[list[dict[str, str]], str]:
    if not paths:
        raise ManifestBuildError("at least one catalog CSV is required")
    rows: list[dict[str, str]] = []
    file_identities = []
    for raw_path in paths:
        path = _regular(raw_path)
        file_identities.append({"name": path.name, "sha256": sha256_file(path)})
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                row = {key: str(value or "").strip() for key, value in raw.items()}
                if row.get("year") != str(year):
                    raise ManifestBuildError(f"catalog year drift: {path.name}")
                region = row.get("country_region") or path.parent.name
                country = row.get("country") or region
                if region not in TARGET_REGIONS or (region, country) not in PROVIDER_BY_GEOGRAPHY:
                    raise ManifestBuildError(f"unsupported catalog geography: {region}/{country}")
                if row.get("grade_text") not in {"G1", "G2", "G3"}:
                    raise ManifestBuildError("catalog contains non-graded row")
                row["country_region"] = region
                row["country"] = country
                row["catalog_key"] = _catalog_key(row)
                rows.append(row)
    keys = [row["catalog_key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise ManifestBuildError("catalog contains duplicate stable identity")
    rows.sort(key=lambda row: row["catalog_key"])
    catalog_set_sha = sha256_bytes(canonical_json_bytes({"files": sorted(file_identities, key=lambda x: (x["name"], x["sha256"])), "row_keys": sorted(keys)}))
    return rows, catalog_set_sha


def prepare_review(paths: list[Path], *, year: int) -> dict[str, Any]:
    rows, catalog_set_sha = load_catalogs(paths, year=year)
    items = []
    for row in rows:
        items.append(
            {
                "catalog_key": row["catalog_key"],
                "region": row["country_region"],
                "country": row["country"],
                "series_key": row["series_key"],
                "race_name": row["canonical_name_original"],
                "source_race_name": row.get("source_race_name") or row["canonical_name_original"],
                "grade": row["grade_text"],
                "racecourse": row["racecourse"],
                "distance": row["distance_text"],
                "expectation_status": row["expectation_status"],
                "provider": PROVIDER_BY_GEOGRAPHY[(row["country_region"], row["country"])],
                "result_url": "",
                "local_date": "",
                "disposition": "not_held" if row["expectation_status"] == "not_held" else "pending_review",
                "gap_reason": "",
                "evidence_url": row.get("raw_source_url", ""),
                "review_notes": "",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "year": year,
        "catalog_set_sha256": catalog_set_sha,
        "reviewed_by": "",
        "reviewed_at": "",
        "items": items,
    }


def compile_review(paths: list[Path], *, year: int, reviewed_path: Path, expected_sha256: str) -> tuple[dict, dict, dict]:
    reviewed_path = _regular(reviewed_path)
    if not SHA_RE.fullmatch(expected_sha256) or sha256_file(reviewed_path) != expected_sha256:
        raise ManifestBuildError("reviewed mapping SHA-256 mismatch")
    try:
        reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestBuildError("reviewed mapping JSON is invalid") from exc
    rows, catalog_set_sha = load_catalogs(paths, year=year)
    for field, expected in (("schema_version", SCHEMA_VERSION), ("tool_version", TOOL_VERSION), ("year", year), ("catalog_set_sha256", catalog_set_sha)):
        if reviewed.get(field) != expected:
            raise ManifestBuildError(f"reviewed mapping identity drift: {field}")
    if not str(reviewed.get("reviewed_by") or "").strip() or not str(reviewed.get("reviewed_at") or "").strip():
        raise ManifestBuildError("reviewed mapping lacks reviewer evidence")
    try:
        reviewed_at = datetime.fromisoformat(
            str(reviewed["reviewed_at"]).strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ManifestBuildError("reviewed mapping reviewed_at is invalid") from exc
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ManifestBuildError("reviewed mapping reviewed_at must be timezone-aware")
    items = reviewed.get("items")
    if not isinstance(items, list):
        raise ManifestBuildError("reviewed mapping items are invalid")
    by_key: dict[str, dict] = {}
    for item in items:
        key = str(item.get("catalog_key") or "") if isinstance(item, dict) else ""
        if not key or key in by_key:
            raise ManifestBuildError("reviewed mapping catalog_key is blank or duplicated")
        by_key[key] = item
    expected_keys = {row["catalog_key"] for row in rows}
    if set(by_key) != expected_keys:
        raise ManifestBuildError("reviewed mapping must cover the catalog exactly")
    races = []
    gaps = []
    seen_result_urls: set[tuple[str, ...]] = set()
    for row in rows:
        item = by_key[row["catalog_key"]]
        override_field_names = (
            "actual_distance",
            "distance_override_reason",
            "distance_override_evidence_url",
        )
        has_override_fields = any(
            str(item.get(field) if item.get(field) is not None else "").strip()
            for field in override_field_names
        )
        fixed = {
            "region": row["country_region"], "country": row["country"],
            "series_key": row["series_key"], "race_name": row["canonical_name_original"],
            "source_race_name": row.get("source_race_name") or row["canonical_name_original"],
            "grade": row["grade_text"], "racecourse": row["racecourse"],
            "distance": row["distance_text"],
            "expectation_status": row["expectation_status"],
            "provider": PROVIDER_BY_GEOGRAPHY[(row["country_region"], row["country"])],
        }
        if any(str(item.get(key) or "").strip() != value for key, value in fixed.items()):
            raise ManifestBuildError(f"reviewed mapping catalog facts drift: {row['catalog_key']}")
        disposition = str(item.get("disposition") or "").strip()
        if row["expectation_status"] == "not_held":
            if disposition != "not_held" or item.get("result_url") or item.get("local_date") or has_override_fields:
                raise ManifestBuildError("not-held race mapping is invalid")
            gaps.append({**fixed, "catalog_key": row["catalog_key"], "disposition": disposition, "gap_reason": "not_held"})
            continue
        if disposition == "collect":
            url = str(item.get("result_url") or "").strip()
            local_date = str(item.get("local_date") or "").strip()
            validate_provider_url(fixed["provider"], url, year=year)
            if not DATE_RE.fullmatch(local_date) or not local_date.startswith(f"{year}-"):
                raise ManifestBuildError("collected race local_date is invalid")
            try:
                date.fromisoformat(local_date)
            except ValueError as exc:
                raise ManifestBuildError("collected race local_date is invalid") from exc
            manifest_distance = fixed["distance"]
            override_distance = str(
                item.get("actual_distance")
                if item.get("actual_distance") is not None
                else ""
            ).strip()
            override_reason = str(item.get("distance_override_reason") or "").strip()
            override_evidence_url = str(
                item.get("distance_override_evidence_url") or ""
            ).strip()
            override_fields = {}
            if override_distance:
                if not override_distance.isdigit() or int(override_distance) <= 0:
                    raise ManifestBuildError("collected race actual_distance is invalid")
                if override_distance == fixed["distance"]:
                    raise ManifestBuildError("collected race distance override is redundant")
                if override_reason != DISTANCE_OVERRIDE_REASON:
                    raise ManifestBuildError("collected race distance override reason is invalid")
                validate_provider_url(fixed["provider"], override_evidence_url, year=year)
                if canonical_provider_url_identity(override_evidence_url) != canonical_provider_url_identity(url):
                    raise ManifestBuildError("collected race distance override evidence identity mismatch")
                manifest_distance = override_distance
                override_fields = {
                    "catalog_distance": fixed["distance"],
                    "distance_override_reason": override_reason,
                    "distance_override_evidence_url": override_evidence_url,
                }
            elif override_reason or override_evidence_url:
                raise ManifestBuildError("collected race distance override is incomplete")
            url_identity = (fixed["provider"], canonical_provider_url_identity(url))
            if fixed["provider"] == "au_racing_australia":
                url_identity += canonical_au_selector_identity(
                    fixed["source_race_name"], manifest_distance, fixed["grade"]
                )
            if url_identity in seen_result_urls:
                raise ManifestBuildError("reviewed mapping duplicates provider/result_url")
            seen_result_urls.add(url_identity)
            races.append({
                "race_key": row["catalog_key"], "provider": fixed["provider"], "result_url": url,
                "region": fixed["region"], "country": fixed["country"], "grade": fixed["grade"],
                "race_name": fixed["race_name"], "source_race_name": fixed["source_race_name"],
                "distance": manifest_distance,
                "local_date": local_date,
                **override_fields,
            })
        elif disposition == "evidence_gap":
            if item.get("result_url") or item.get("local_date") or has_override_fields:
                raise ManifestBuildError("evidence gap must not carry collection fields")
            reason = str(item.get("gap_reason") or "").strip()
            evidence_url = str(item.get("evidence_url") or "").strip()
            parsed = urlsplit(evidence_url)
            provider_hosts = set(POLICIES[fixed["provider"]].hosts)
            tjcis_hosts = {"www.tjcis.com", "tjcis.com"}
            if reason not in GAP_REASONS or parsed.scheme != "https" or parsed.hostname not in provider_hosts | tjcis_hosts:
                raise ManifestBuildError("evidence gap lacks controlled reason/HTTPS evidence")
            if parsed.hostname in provider_hosts:
                validate_provider_url(fixed["provider"], evidence_url, year=year)
            elif str(year) not in evidence_url:
                raise ManifestBuildError("TJCIS gap evidence lacks requested year")
            gaps.append({**fixed, "catalog_key": row["catalog_key"], "disposition": disposition, "gap_reason": reason, "evidence_url": evidence_url, "review_notes": str(item.get("review_notes") or "").strip()})
        else:
            raise ManifestBuildError(f"unreviewed catalog race: {row['catalog_key']}")
    manifest = {"schema_version": 1, "year": year, "catalog_sha256": catalog_set_sha, "reviewed_mapping_sha256": expected_sha256, "races": sorted(races, key=lambda x: x["race_key"])}
    gap_artifact = {"schema_version": 1, "year": year, "catalog_set_sha256": catalog_set_sha, "reviewed_mapping_sha256": expected_sha256, "gaps": sorted(gaps, key=lambda x: x["catalog_key"])}
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest))
    gap_sha = sha256_bytes(canonical_json_bytes(gap_artifact))
    package_identity = {
        "catalog_set_sha256": catalog_set_sha,
        "reviewed_mapping_sha256": expected_sha256,
        "official_result_manifest_sha256": manifest_sha,
        "official_result_gaps_sha256": gap_sha,
    }
    summary = {"schema_version": 1, "year": year, "catalog_count": len(rows), "collect_count": len(races), "gap_count": len(gaps), **package_identity, "package_sha256": sha256_bytes(canonical_json_bytes(package_identity))}
    if len(races) + len(gaps) != len(rows):
        raise ManifestBuildError("catalog conservation failed")
    return manifest, gap_artifact, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="离线编译新地区官方赛果 URL manifest")
    parser.add_argument("--mode", choices=("prepare", "compile"), required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--catalog-csv", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reviewed-mapping")
    parser.add_argument("--reviewed-mapping-sha256")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    try:
        if args.mode == "prepare":
            review = prepare_review([Path(path) for path in args.catalog_csv], year=args.year)
            atomic_write(output / "official_race_url_review.json", canonical_json_bytes(review))
        else:
            if not args.reviewed_mapping or not args.reviewed_mapping_sha256:
                raise ManifestBuildError("compile requires reviewed mapping path and SHA-256")
            manifest, gaps, summary = compile_review([Path(path) for path in args.catalog_csv], year=args.year, reviewed_path=Path(args.reviewed_mapping), expected_sha256=args.reviewed_mapping_sha256)
            atomic_write(output / "official_result_manifest.json", canonical_json_bytes(manifest))
            atomic_write(output / "official_result_gaps.json", canonical_json_bytes(gaps))
            atomic_write(output / "summary.json", canonical_json_bytes(summary))
    except (ManifestBuildError, OSError, ValueError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
