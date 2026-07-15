#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import json
from collections import Counter
from pathlib import Path

from historical_race_calendar_common import (
    CalendarArtifactError,
    atomic_publish_directory,
    canonical_bytes,
    file_identity,
    hkjc_coverage_policy,
    load_catalog,
    load_selection,
    sha256_bytes,
    sha256_file,
)


class CalendarRequestError(CalendarArtifactError):
    pass


def build_calendar_requests(
    *,
    selection_path: Path,
    catalog_path: Path,
    output_dir: Path,
    hkjc_cutoff_date: date | None = None,
) -> dict:
    try:
        _selection, targets = load_selection(selection_path)
        _catalog, sources = load_catalog(
            catalog_path, hkjc_cutoff_date=hkjc_cutoff_date
        )
    except CalendarArtifactError as exc:
        raise CalendarRequestError(str(exc)) from exc
    scope_pairs = {(target["country_region"], target["year"]) for target in targets}
    if hkjc_cutoff_date is not None and scope_pairs != {
        ("hong_kong", hkjc_cutoff_date.year)
    }:
        raise CalendarRequestError(
            "HKJC partial coverage requires a single edition year selection"
        )
    coverage_policy = hkjc_coverage_policy(
        sources, hkjc_cutoff_date=hkjc_cutoff_date
    )
    coverage_policy_sha256 = (
        sha256_bytes(canonical_bytes(coverage_policy)) if coverage_policy else None
    )
    source_pairs = {(source["country_region"], source["edition_year"]) for source in sources}
    if not sources or not source_pairs <= scope_pairs:
        raise CalendarRequestError("calendar catalog source is outside selection scope")
    missing = [
        target["target_id"]
        for target in targets
        if (target["country_region"], target["year"]) not in source_pairs
    ]
    if missing:
        raise CalendarRequestError(
            f"calendar catalog does not cover selection targets: {missing[:10]}"
        )

    rows = []
    for target in targets:
        for source in sources:
            if (
                source["country_region"] != target["country_region"]
                or source["edition_year"] != target["year"]
            ):
                continue
            rows.append(
                {
                    "adapter_key": source["adapter_key"],
                    "target_id": target["target_id"],
                    "target_sha256": target["target_sha256"],
                    "inventory_artifact_sha256": target[
                        "inventory_artifact_sha256"
                    ],
                    "series_key": target["series_key"],
                    "edition_year": target["year"],
                    "urls": {
                        "calendar_source": {
                            "url": source["url"],
                            "source_id": source["id"],
                            "parser": source["parser"],
                            "content_format": source["content_format"],
                            "source_provider": source["adapter_key"],
                            "source_authority": source["source_authority"],
                            "parser_options": source["options"],
                            "redirect_chain": [],
                        }
                    },
                }
            )
    rows.sort(
        key=lambda row: (
            row["target_id"],
            row["adapter_key"],
            row["urls"]["calendar_source"]["source_id"],
        )
    )
    summary = {
        "schema_version": "1.0",
        "selection_sha256": sha256_file(selection_path),
        "catalog_sha256": sha256_file(catalog_path),
        "target_count": len(targets),
        "source_count": len(sources),
        "provider_row_count": len(rows),
        "unique_request_count": len(
            {
                (row["adapter_key"], row["urls"]["calendar_source"]["url"])
                for row in rows
            }
        ),
        "targets_by_region": dict(
            sorted(Counter(target["country_region"] for target in targets).items())
        ),
    }
    if coverage_policy is not None:
        summary["coverage_policy"] = coverage_policy
        summary["coverage_policy_sha256"] = coverage_policy_sha256
    result = dict(summary)

    def write(temporary: Path) -> None:
        providers = temporary / "provider_rows.jsonl"
        providers.write_bytes(b"".join(canonical_bytes(row) for row in rows))
        summary_path = temporary / "summary.json"
        summary_path.write_bytes(canonical_bytes(summary))
        manifest = {
            "schema_version": "1.0",
            "selection": file_identity(selection_path),
            "source_catalog": file_identity(catalog_path),
            "artifacts": {
                "provider_rows": file_identity(providers, relative_to=temporary),
                "summary": file_identity(summary_path, relative_to=temporary),
            },
        }
        if coverage_policy is not None:
            manifest["coverage_policy"] = coverage_policy
            manifest["coverage_policy_sha256"] = coverage_policy_sha256
        (temporary / "manifest.json").write_bytes(canonical_bytes(manifest))

    try:
        atomic_publish_directory(output_dir, write)
    except CalendarArtifactError as exc:
        raise CalendarRequestError(str(exc)) from exc
    result["output_dir"] = str(output_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从冻结 selection 与年度 source catalog 生成历史赛事赛历来源请求。"
    )
    parser.add_argument("--selection-snapshot", required=True, type=Path)
    parser.add_argument("--source-catalog", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--hkjc-cutoff-date", type=date.fromisoformat)
    args = parser.parse_args()
    try:
        result = build_calendar_requests(
            selection_path=args.selection_snapshot,
            catalog_path=args.source_catalog,
            output_dir=args.output_dir,
            hkjc_cutoff_date=args.hkjc_cutoff_date,
        )
    except (CalendarRequestError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
