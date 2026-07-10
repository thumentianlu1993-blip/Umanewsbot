#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from prepare_france_zeturf_race_detail_candidates import _download, _parse_page, _title


GAP_URLS = {
    "fr-france-galop-2026-0417-012": "https://www.zeturf.fr/fr/course-du-jour/2026-04-17/R4C4-saint-cloud-henri-matisse-coolmore-prix-cleopatre",
    "fr-france-galop-2026-0419-125": "https://www.zeturf.fr/fr/course-du-jour/2026-04-19/R5C6-auteuil-prix-du-president-de-la-republique",
    "fr-france-galop-2026-0419-126": "https://www.zeturf.fr/fr/course-du-jour/2026-04-19/R5C7-auteuil-prix-amadou",
    "fr-france-galop-2026-0419-127": "https://www.zeturf.fr/fr/course-du-jour/2026-04-19/R5C5-auteuil-prix-leon-rambaud",
    "fr-france-galop-2026-0419-128": "https://www.zeturf.fr/fr/course-du-jour/2026-04-19/R5C4-auteuil-prix-jean-stern",
    "fr-france-galop-2026-0504-018": "https://www.zeturf.fr/fr/course-du-jour/2026-05-04/R4C2-chantilly-prix-de-guiche",
    "fr-france-galop-2026-0526-139": "https://www.zeturf.fr/fr/course-du-jour/2026-05-26/R4C6-auteuil-prix-christian-de-tredern",
    "fr-france-galop-2026-0627-041": "https://www.zeturf.fr/fr/course-du-jour/2026-06-27/R7C2-deauville-prix-du-bois-b-p-e-lecieux",
}


def _read_events(path: Path) -> dict[str, dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["slug"]: row for row in csv.DictReader(handle) if row.get("slug") in GAP_URLS}


def _cache_name(slug: str) -> str:
    return f"source_zt_gap_{slug}.html"


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    source_dir = output_dir / "sources"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(exist_ok=True)
    events = _read_events(Path(args.events_csv))

    jsonl_path = output_dir / "france_zeturf_gap_detail_candidates_2026.jsonl"
    review_path = output_dir / "france_zeturf_gap_detail_review_2026.csv"
    summary = {
        "source": "zeturf_race_detail_explicit_gap_mapping",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(GAP_URLS),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "skipped": [],
        "errors": [],
    }

    with jsonl_path.open("w", encoding="utf-8") as jsonl, review_path.open("w", encoding="utf-8", newline="") as review_handle:
        writer = csv.DictWriter(
            review_handle,
            fieldnames=[
                "slug",
                "source_title",
                "runners",
                "results",
                "winner",
                "source_url",
            ],
        )
        writer.writeheader()
        for slug, url in GAP_URLS.items():
            event = events.get(slug)
            if not event:
                summary["skipped"].append({"slug": slug, "reason": "event_not_in_csv"})
                continue
            try:
                html = _download(
                    url,
                    source_dir / _cache_name(slug),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_page(html, source_url=url)
            except Exception as exc:
                summary["errors"].append({"slug": slug, "url": url, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            if not runners or not results:
                summary["skipped"].append(
                    {
                        "slug": slug,
                        "reason": "empty_detail",
                        "runners": len(runners),
                        "results": len(results),
                        "title": _title(html),
                    }
                )
                continue
            record = {
                "year": int(event["year"]),
                "slug": slug,
                "source_name": "zeturf",
                "source_url": url,
                "modules": {
                    "runners": {"items": runners},
                    "results": {"items": results},
                },
                "metadata": {
                    **metadata,
                    "source_title": _title(html),
                    "mapping_kind": "explicit_gap_mapping",
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            winner = next((row.get("horse_name", "") for row in results if row.get("finish_position") == 1), "")
            writer.writerow(
                {
                    "slug": slug,
                    "source_title": _title(html),
                    "runners": len(runners),
                    "results": len(results),
                    "winner": winner,
                    "source_url": url,
                }
            )

    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate France gap race detail candidates from explicit ZEturf mappings.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
