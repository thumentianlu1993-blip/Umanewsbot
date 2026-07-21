#!/usr/bin/env python3
"""Reparse local HTML caches for horse identity links (offline, no network).

Walks one or more local cache roots and extracts same-origin horse IDs:

- ``--namespace hkjc``: HKJC ``HorseId=`` anchors from Hong Kong pages.
- ``--namespace nar``: NAR ``k_lineageLoginCode=`` anchors from keiba.go.jp
  pages. ``--probe`` writes only the coverage summary so operators can decide
  whether the NAR evidence source has enough local coverage to enable.

Outputs a JSONL evidence file (one ``{namespace, external_id, name,
normalized_name, source_file}`` row per line) plus a summary JSON with
coverage stats. Missing or unreadable cache roots are recorded honestly in
the summary; the tool never fetches anything.

Usage:
    python runtime/tools/reparse_horse_identity_html_cache.py \
        --namespace hkjc --cache-root /path/to/cache \
        --output evidence_hkjc.jsonl --summary summary_hkjc.json

    python runtime/tools/reparse_horse_identity_html_cache.py \
        --namespace nar --cache-root /path/to/cache --probe \
        --summary nar_probe.json
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "server"))

from stable.services.horse_identity_html_parse import parse_horse_links  # noqa: E402

SUMMARY_SCHEMA_VERSION = "horse-identity-cache-reparse.v1"


def _normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def reparse_cache(*, namespace: str, cache_roots: list[Path]) -> tuple[list[dict], dict]:
    rows: dict[tuple[str, str], dict] = {}
    files_scanned = 0
    files_with_matches = 0
    missing_roots: list[str] = []
    for root in cache_roots:
        if not root.is_dir():
            missing_roots.append(str(root))
            continue
        for path in sorted(root.rglob("*.html")):
            files_scanned += 1
            try:
                html = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            pairs = parse_horse_links(html, namespace=namespace)
            if not pairs:
                continue
            files_with_matches += 1
            for pair in pairs:
                key = (namespace, pair["external_id"])
                row = rows.setdefault(
                    key,
                    {
                        "namespace": namespace,
                        "external_id": pair["external_id"],
                        "name": pair["name"],
                        "source_file": str(path),
                        "source_file_count": 0,
                    },
                )
                if pair["name"] and len(pair["name"]) > len(row["name"]):
                    row["name"] = pair["name"]
                row["source_file_count"] += 1
    evidence = []
    for row in rows.values():
        evidence.append(
            {
                "namespace": row["namespace"],
                "external_id": row["external_id"],
                "name": row["name"],
                "normalized_name": _normalize_name(row["name"]),
                "source_file_count": row["source_file_count"],
                "source_file": row["source_file"],
            }
        )
    evidence.sort(key=lambda item: (item["namespace"], item["external_id"]))
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "namespace": namespace,
        "cache_roots": [str(root) for root in cache_roots],
        "missing_roots": missing_roots,
        "files_scanned": files_scanned,
        "files_with_matches": files_with_matches,
        "unique_ids": len(evidence),
        "named_ids": sum(1 for row in evidence if row["name"]),
        "coverage_ratio": (files_with_matches / files_scanned) if files_scanned else 0.0,
        "status": "ok" if files_scanned else "cache_missing_or_empty",
    }
    return evidence, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--namespace", choices=["hkjc", "nar"], required=True)
    parser.add_argument("--cache-root", action="append", default=[], required=True)
    parser.add_argument("--output", default="", help="JSONL evidence output path")
    parser.add_argument("--summary", default="", help="summary JSON output path")
    parser.add_argument("--probe", action="store_true", help="coverage summary only")
    args = parser.parse_args()

    cache_roots = [Path(value) for value in args.cache_root]
    evidence, summary = reparse_cache(namespace=args.namespace, cache_roots=cache_roots)
    summary["mode"] = "probe" if args.probe else "reparse"

    if not args.probe and args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for row in evidence:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary["output_path"] = str(output_path)
    if args.summary:
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
