#!/usr/bin/env python3
"""Capture one exact netkeiba result as a manual, non-bulk winner reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from race_event_safe_http import fetch_https  # noqa: E402
from race_event_source_cache import write_source_cache  # noqa: E402

from audit_legacy_historical_detail_bundle import (  # noqa: E402
    _atomic_write,
    canonical_json,
    sha256_path,
)


SCHEMA_VERSION = "manual-netkeiba-result-reference.v1"
URL_RE = re.compile(r"https://en\.netkeiba\.com/db/race/(?P<race_id>[A-Za-z0-9]+)/$")


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._title_depth = 0
        self._race_name_depth = 0
        self._grade_depth = 0
        self._table_depth = 0
        self._row_depth = 0
        self._cell_depth = 0
        self._buffer: list[str] = []
        self.title = ""
        self.race_name = ""
        self.grade = ""
        self.rows: list[list[str]] = []
        self._row: list[str] = []

    @staticmethod
    def _classes(attrs) -> set[str]:
        return {
            value
            for key, raw in attrs
            if key == "class"
            for value in str(raw or "").split()
        }

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if tag == "title":
            self._title_depth = 1
            self._buffer = []
        elif tag == "span" and "RaceName_main" in classes:
            self._race_name_depth = 1
            self._buffer = []
        elif tag == "span" and "Icon_GradeType" in classes:
            self._grade_depth = 1
            self._buffer = []
        elif tag == "table" and "ResultsByRaceDetail" in classes:
            self._table_depth = 1
        elif self._table_depth and tag == "tr":
            self._row_depth = 1
            self._row = []
        elif self._row_depth and tag in {"td", "th"}:
            self._cell_depth = 1
            self._buffer = []

    def handle_endtag(self, tag):
        if tag == "title" and self._title_depth:
            self.title = " ".join("".join(self._buffer).split())
            self._title_depth = 0
        elif tag == "span" and self._race_name_depth:
            self.race_name = " ".join("".join(self._buffer).split())
            self._race_name_depth = 0
        elif tag == "span" and self._grade_depth:
            self.grade = " ".join("".join(self._buffer).split()).upper()
            self._grade_depth = 0
        elif tag in {"td", "th"} and self._cell_depth:
            self._row.append(" ".join("".join(self._buffer).split()))
            self._cell_depth = 0
        elif tag == "tr" and self._row_depth:
            if self._row:
                self.rows.append(self._row)
            self._row_depth = 0
        elif tag == "table" and self._table_depth:
            self._table_depth = 0

    def handle_data(self, data):
        if self._title_depth or self._race_name_depth or self._grade_depth or self._cell_depth:
            self._buffer.append(data)


def parse_result(
    body: bytes,
    *,
    expected_race_name: str,
    expected_date: date,
    expected_grade: str,
    expected_winner: str,
) -> dict:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("result page is not UTF-8") from exc
    parser = ResultParser()
    parser.feed(text)
    expected_title_date = expected_date.strftime("%d %b %Y").upper()
    data_rows = [row for row in parser.rows if row and row[0].strip().isdigit()]
    winners = [row for row in data_rows if row[0].strip() == "1"]
    if (
        parser.race_name.casefold() != expected_race_name.strip().casefold()
        or parser.grade != expected_grade.strip().upper()
        or expected_title_date not in parser.title.upper()
        or len(winners) != 1
        or len(winners[0]) < 4
        or winners[0][3].strip().casefold() != expected_winner.strip().casefold()
    ):
        raise ValueError("manual result reference does not match expected race/winner")
    return {
        "race_name": parser.race_name,
        "local_date": expected_date.isoformat(),
        "grade_text": parser.grade,
        "winner_name": winners[0][3].strip(),
        "winner_finish_position": "1",
        "parsed_result_rows": len(data_rows),
    }


def capture_reference(
    *,
    url: str,
    expected_race_name: str,
    expected_date: date,
    expected_grade: str,
    expected_winner: str,
    output_dir: Path,
    allow_network: bool,
) -> dict:
    match = URL_RE.fullmatch(url)
    if not match:
        raise ValueError("only one exact en.netkeiba.com race result URL is allowed")
    if not allow_network or os.environ.get("MANUAL_RACE_REFERENCE_NETWORK_ENABLED", "").lower() != "true":
        raise ValueError("manual result capture network gate is disabled")
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("output directory must be absent or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "sources" / "result.html"
    body, response = fetch_https(
        url,
        allowed_hosts=("en.netkeiba.com",),
        allowed_path_pattern=r"/db/race/[A-Za-z0-9]+/",
        allowed_content_types=("text/html",),
        max_bytes=2 * 1024 * 1024,
        max_redirects=0,
        timeout=30,
        headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run; one-result manual reference)"},
    )
    if response.get("status") != 200 or response.get("final_url") != url or response.get("redirect_chain"):
        raise ValueError("manual result response identity drift")
    parsed = parse_result(
        body,
        expected_race_name=expected_race_name,
        expected_date=expected_date,
        expected_grade=expected_grade,
        expected_winner=expected_winner,
    )
    source_identity = write_source_cache(source_path, body, source_url=url)
    request_ledger_path = output_dir / "request-ledger.jsonl"
    request = {
        "ordinal": 1,
        "method": "GET",
        "url": url,
        "status": 200,
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "response_size": len(body),
    }
    _atomic_write(request_ledger_path, f"{canonical_json(request)}\n".encode("utf-8"))
    reference = {
        "schema_version": SCHEMA_VERSION,
        "status": "proposed_not_approved",
        "source_authority": "human_reviewed_reference",
        "systematic_reuse_approved": False,
        "race_id": match.group("race_id"),
        "source": {
            "url": url,
            "cache_path": str(source_path.resolve()),
            "sha256": source_identity["sha256"],
            "size": source_identity["size"],
        },
        "result": parsed,
    }
    reference_path = output_dir / "winner-reference.json"
    _atomic_write(
        reference_path,
        (json.dumps(reference, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROPOSED_NOT_APPROVED",
        "completion_marker": "PREPARED",
        "approval": False,
        "network_requests": 1,
        "database_writes": 0,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": source_identity,
        "request_ledger": {
            "path": request_ledger_path.name,
            "sha256": sha256_path(request_ledger_path),
            "size": request_ledger_path.stat().st_size,
            "rows": 1,
        },
        "reference": {
            "path": reference_path.name,
            "sha256": sha256_path(reference_path),
            "size": reference_path.stat().st_size,
        },
    }
    manifest_path = output_dir / "capture-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", f"{sha256_path(manifest_path)}\n".encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-race-name", required=True)
    parser.add_argument("--expected-date", required=True, type=date.fromisoformat)
    parser.add_argument("--expected-grade", required=True)
    parser.add_argument("--expected-winner", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--allow-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(canonical_json(capture_reference(**vars(parse_args()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
