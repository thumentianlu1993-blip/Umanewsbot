#!/usr/bin/env python3
"""从 Racing Australia 两个跨年赛季表生成单一日历年的 G1-G3 目录。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


PARSER_VERSION = "racing-australia-calendar.v1"
FIELDS = (
    "record_type", "country_region", "country", "year", "series_key",
    "canonical_name_original", "source_race_name", "provider_group_id",
    "grade_text", "racecourse", "source_state", "source_venue_key", "local_date",
    "distance_text", "surface", "expectation_status", "source_scope",
    "discipline", "raw_source_cache_path", "raw_source_cache_sha256",
    "raw_source_url",
)
VENUE_KEYS = {
    # 2024-25 及更早赛季页使用的 venue 代码
    "ASCT": "Ascot", "BEND": "Bendigo", "BLMT": "Belmont", "CANB": "Canberra",
    "CAUL": "Caulfield", "DOOM": "Doomben", "E FM": "Eagle Farm",
    "FLEM": "Flemington", "GCST": "Gold Coast", "GEEL": "Geelong",
    "GOSF": "Gosford", "HAWK": "Hawkesbury", "HOB": "Hobart",
    "K GR": "Kembla Grange", "KEMB": "Kembla Grange", "LAUN": "Launceston",
    "MORP": "Morphettville", "MORPP": "Morphettville Parks",
    "NCLE": "Newcastle", "NTHM": "Northam", "RAND": "Royal Randwick",
    "RHIL": "Rosehill Gardens", "SANH": "Sandown Hillside", "SCNE": "Scone",
    "SCTC": "Sunshine Coast", "THE VALLEY": "The Valley", "WYNG": "Wyong",
    # 2025-26 赛季起使用的 venue 全名（含冠名前缀变体，归一到正式马场名）
    "Ascot": "Ascot", "Belmont": "Belmont", "Bendigo": "Bendigo",
    "Canberra": "Canberra", "Caulfield": "Caulfield", "Doomben": "Doomben",
    "Eagle Farm": "Eagle Farm", "Flemington": "Flemington", "Geelong": "Geelong",
    "Gold Coast": "Gold Coast", "Gosford": "Gosford", "Hawkesbury": "Hawkesbury",
    "Hobart": "Hobart", "Kembla Grange": "Kembla Grange", "Launceston": "Launceston",
    "Morphettville": "Morphettville", "Morphettville Parks": "Morphettville Parks",
    "Newcastle": "Newcastle", "Northam": "Northam", "Rosehill Gardens": "Rosehill Gardens",
    "Royal Randwick": "Royal Randwick", "Scone": "Scone", "Sunshine Coast": "Sunshine Coast",
    "The Valley": "The Valley", "Wyong": "Wyong",
    "Aquis Park Gold Coast": "Gold Coast", "Ladbrokes Geelong": "Geelong",
    "Southside Pakenham": "Pakenham", "Sportsbet Sandown Hillside": "Sandown Hillside",
}
STATE_CODES = {"ACT", "NSW", "QLD", "SA", "TAS", "VIC", "WA"}


class CatalogError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise CatalogError(f"source HTML must be a regular non-symlink file: {path}")
    return path.resolve(strict=True)


def parse_source(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise CatalogError("source must use URL=PATH")
    url, raw_path = spec.split("=", 1)
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "racingaustralia.horse", "www.racingaustralia.horse"
    }:
        raise CatalogError("source URL is outside Racing Australia allowlist")
    return url.strip(), regular(Path(raw_path))


def validate_adjacent_seasons(sources: list[tuple[str, Path]], *, year: int) -> None:
    seasons = set()
    for url, _path in sources:
        match = re.search(r"/(\d{4})-(\d{4})\.aspx$", urlparse(url).path, re.I)
        if not match or int(match.group(2)) != int(match.group(1)) + 1:
            raise CatalogError("source URL lacks a valid Racing Australia season identity")
        seasons.add((int(match.group(1)), int(match.group(2))))
    if seasons != {(year - 1, year), (year, year + 1)}:
        raise CatalogError("sources must be the two seasons adjacent to the requested calendar year")
    if len({path.name for _url, path in sources}) != len(sources):
        raise CatalogError("source cache basenames must be unique")
    if any(path.parent.name != "australia" or path.parent.parent.name != "source" for _url, path in sources):
        raise CatalogError("source files must use the controlled source/australia cache directory")


def _require_season_table(soup: BeautifulSoup, url: str) -> None:
    """fail closed：缓存文件必须含数据表；RA 404 错误页没有任何 table，直接拒绝。"""
    if soup.find("table") is None:
        raise CatalogError(
            f"Racing Australia season source is not a valid Group/Listed table (possible 404 error page): {url}"
        )
    table = soup.find("table", class_="tableizer-table")
    if table is not None:
        first_row = table.find("tr")
        header = (
            [" ".join(cell.get_text(" ", strip=True).split()) for cell in first_row.find_all(["th", "td"])]
            if first_row is not None
            else []
        )
        if not header or header[0] != "Meeting Date" or "Registered Race Name" not in header:
            raise CatalogError(
                f"Racing Australia season source has an unrecognised tableizer header (possible 404 error page): {url}"
            )


def parse_rows(
    url: str,
    path: Path,
    *,
    year: int,
    unknown_venues: set[str] | None = None,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    _require_season_table(soup, url)
    rows = []
    for tr in soup.find_all("tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in tr.find_all("td")]
        if len(cells) != 14:
            continue
        local_date = None
        for date_format in ("%d-%b-%y", "%d/%b/%Y"):
            try:
                local_date = datetime.strptime(cells[0], date_format).date()
                break
            except ValueError:
                continue
        if local_date is None:
            continue
        grade = cells[3].upper()
        if local_date.year != year or grade not in {"G1", "G2", "G3"}:
            continue
        source_state = cells[4].upper()
        if source_state not in STATE_CODES:
            raise CatalogError("Racing Australia row has invalid state identity")
        group_id = cells[1].replace(",", "")
        distance = cells[8].replace(",", "")
        if not group_id.isdigit() or not distance.isdigit():
            raise CatalogError("Racing Australia row identity is invalid")
        venue_key = cells[6]
        racecourse = VENUE_KEYS.get(venue_key)
        if racecourse is None:
            # 未知 venue：保留原文并记录，不静默丢弃、不臆造映射
            racecourse = venue_key
            if unknown_venues is not None:
                unknown_venues.add(venue_key)
        registered_name = cells[13]
        source_race_name = cells[7]
        if not registered_name or not source_race_name or not racecourse:
            raise CatalogError("Racing Australia row lacks required race identity")
        rows.append(
            {
                "record_type": "catalog",
                "country_region": "australia",
                "country": "australia",
                "year": str(year),
                "series_key": f"australia-ra-{group_id}-{local_date.isoformat()}",
                "canonical_name_original": registered_name,
                "source_race_name": source_race_name,
                "provider_group_id": group_id,
                "grade_text": grade,
                "racecourse": racecourse,
                "source_state": source_state,
                "source_venue_key": venue_key,
                "local_date": local_date.isoformat(),
                "distance_text": distance,
                "surface": "turf",
                "expectation_status": "held",
                "source_scope": "racing_australia_group_and_listed_calendar",
                "discipline": "flat",
                "raw_source_cache_path": f"source/australia/{path.name}",
                "raw_source_cache_sha256": sha256(path),
                "raw_source_url": url,
            }
        )
    if not rows:
        # 每个赛季页都必须为目标日历年贡献 G1-G3 行；否则 fail closed，
        # 避免单季缺数据时只产出半个日历年
        raise CatalogError(f"Racing Australia season source yielded no {year} G1-G3 rows: {url}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--source", action="append", required=True, help="URL=PATH; repeat for both seasons")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if len(args.source) != 2:
            raise CatalogError("exactly two adjacent season sources are required")
        sources = [parse_source(spec) for spec in args.source]
        validate_adjacent_seasons(sources, year=args.year)
        unknown_venues: set[str] = set()
        rows = [
            row
            for url, path in sources
            for row in parse_rows(url, path, year=args.year, unknown_venues=unknown_venues)
        ]
        rows.sort(key=lambda row: (row["local_date"], int(row["provider_group_id"])))
        keys = [row["series_key"] for row in rows]
        if not rows or len(keys) != len(set(keys)):
            raise CatalogError("calendar catalog is empty or contains duplicate occurrence identity")
        output = Path(args.output)
        temporary = output.with_name(f".{output.name}.{os.getpid()}.csv")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        summary = {
            "parser_version": PARSER_VERSION,
            "year": args.year,
            "row_count": len(rows),
            "grade_counts": {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")},
            "unknown_venues": sorted(unknown_venues),
            "output_sha256": sha256(output),
            "sources": [
                {"url": url, "cache_path": f"source/australia/{path.name}", "sha256": sha256(path)}
                for url, path in sources
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (CatalogError, OSError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
