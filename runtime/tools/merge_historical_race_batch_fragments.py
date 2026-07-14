#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

import django  # noqa: E402

django.setup()

from stable.services.historical_batch_pipeline import (  # noqa: E402
    HistoricalBatchPipelineError,
    merge_historical_race_fragments,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="确定性合并 historical race date/detail fragments。"
    )
    parser.add_argument("--mode", required=True, choices=("date", "detail"))
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--fragment", action="append", required=True, type=Path)
    parser.add_argument("--gap", action="append", default=[], type=Path)
    parser.add_argument("--evidence", action="append", default=[], type=Path)
    parser.add_argument("--source-cache-manifest", action="append", default=[], type=Path)
    parser.add_argument("--recorded-at", default="")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = merge_historical_race_fragments(
            mode=args.mode,
            selection_path=args.selection,
            fragment_paths=args.fragment,
            gap_paths=args.gap,
            evidence_paths=args.evidence,
            source_cache_manifest_paths=args.source_cache_manifest,
            recorded_at=args.recorded_at,
            output_dir=args.output_dir,
        )
    except (HistoricalBatchPipelineError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
