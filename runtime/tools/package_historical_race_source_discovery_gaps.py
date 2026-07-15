#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from historical_race_calendar_common import (
    CalendarArtifactError,
    atomic_publish_directory,
    canonical_bytes,
    file_identity,
    load_selection,
    valid_timestamp,
    validate_source_url,
)


class SourceDiscoveryGapError(CalendarArtifactError):
    pass


def _load_evidence(path: Path, *, country_region: str, year: int) -> dict:
    if path.is_symlink() or not path.is_file():
        raise SourceDiscoveryGapError("source discovery evidence is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceDiscoveryGapError("source discovery evidence is unreadable") from exc
    sources = payload.get("sources") if isinstance(payload, dict) else None
    recipe = payload.get("source_recipe") if isinstance(payload, dict) else None
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("country_region") != country_region
        or payload.get("edition_year") != year
        or payload.get("discovery_status") != "source_discovery_pending"
        or not isinstance(sources, list)
        or not isinstance(recipe, list)
    ):
        raise SourceDiscoveryGapError("source discovery evidence is outside requested scope")
    for source in sources:
        if not isinstance(source, dict):
            raise SourceDiscoveryGapError("source discovery evidence source is invalid")
        adapter_key = str(source.get("adapter_key") or "")
        try:
            validate_source_url(str(source.get("url") or ""), adapter_key)
        except CalendarArtifactError as exc:
            raise SourceDiscoveryGapError(str(exc)) from exc
        if (
            not str(source.get("source_id") or "")
            or not str(source.get("source_authority") or "")
            or not str(source.get("status") or "")
        ):
            raise SourceDiscoveryGapError("source discovery evidence source is invalid")
    return payload


def package_source_discovery_gaps(
    *,
    selection_path: Path,
    evidence_path: Path,
    country_region: str,
    year: int,
    recorded_at: str,
    output_dir: Path,
) -> dict:
    try:
        _selection, targets = load_selection(selection_path)
    except CalendarArtifactError as exc:
        raise SourceDiscoveryGapError(str(exc)) from exc
    if not valid_timestamp(recorded_at):
        raise SourceDiscoveryGapError("recorded_at must be timezone-aware")
    if any(
        target["country_region"] != country_region or target["year"] != year
        for target in targets
    ):
        raise SourceDiscoveryGapError("selection is outside requested scope")
    evidence = _load_evidence(evidence_path, country_region=country_region, year=year)
    evidence_identity = file_identity(evidence_path)
    source_evidence = [
        {
            "source_id": source["source_id"],
            "source_url": source["url"],
            "source_authority": source["source_authority"],
            "status": source["status"],
        }
        for source in evidence["sources"]
    ]
    gaps = [
        {
            "target_id": target["target_id"],
            "target_sha256": target["target_sha256"],
            "inventory_artifact_sha256": target["inventory_artifact_sha256"],
            "series_key": target["series_key"],
            "edition_year": target["year"],
            "reason_code": "source_discovery_pending",
            "recorded_at": recorded_at,
            "evidence_identity": evidence_identity,
            "source_evidence": source_evidence,
            "source_recipe": evidence["source_recipe"],
            "issues": [
                {
                    "code": "annual_source_url_not_resolved",
                    "target_id": target["target_id"],
                    "edition_year": year,
                }
            ],
        }
        for target in targets
    ]
    summary = {
        "schema_version": "1.0",
        "country_region": country_region,
        "edition_year": year,
        "scope_count": len(targets),
        "complete_count": 0,
        "gap_count": len(gaps),
        "accounted_count": len(gaps),
        "provider_row_count": 0,
        "accounted_rate": 1.0,
        "data_complete_rate": 0.0,
        "recorded_at": recorded_at,
    }

    def write(temporary: Path) -> None:
        providers_path = temporary / "provider_rows.jsonl"
        providers_path.write_bytes(b"")
        gaps_path = temporary / "gaps.jsonl"
        gaps_path.write_bytes(b"".join(canonical_bytes(row) for row in gaps))
        summary_path = temporary / "summary.json"
        summary_path.write_bytes(canonical_bytes(summary))
        manifest = {
            "schema_version": "1.0",
            "selection": file_identity(selection_path),
            "source_discovery_evidence": file_identity(evidence_path),
            "artifacts": {
                "provider_rows": file_identity(providers_path, relative_to=temporary),
                "gaps": file_identity(gaps_path, relative_to=temporary),
                "summary": file_identity(summary_path, relative_to=temporary),
            },
        }
        (temporary / "manifest.json").write_bytes(canonical_bytes(manifest))

    try:
        atomic_publish_directory(output_dir, write)
    except CalendarArtifactError as exc:
        raise SourceDiscoveryGapError(str(exc)) from exc
    return {**summary, "output_dir": str(output_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把冻结 selection 封装为可审计的年度来源发现缺口。"
    )
    parser.add_argument("--selection-snapshot", required=True, type=Path)
    parser.add_argument("--discovery-evidence", required=True, type=Path)
    parser.add_argument("--country-region", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = package_source_discovery_gaps(
            selection_path=args.selection_snapshot,
            evidence_path=args.discovery_evidence,
            country_region=args.country_region,
            year=args.year,
            recorded_at=args.recorded_at,
            output_dir=args.output_dir,
        )
    except (SourceDiscoveryGapError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
