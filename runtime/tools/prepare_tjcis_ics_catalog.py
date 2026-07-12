#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib import request
from urllib.parse import urljoin

import pdfplumber
from bs4 import BeautifulSoup


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from race_event_request_budget import before_network_request  # noqa: E402
from race_event_source_cache import write_source_cache  # noqa: E402


BASE_URL = "https://www.tjcis.com"
PAST_EDITIONS_URL = f"{BASE_URL}/default.asp?content=PASSYR"
CURRENT_EDITION_URL = f"{BASE_URL}/default.asp?content=ICS"
PARSER_VERSION = "2026.07.1"
REGION_ADAPTERS = {
    "japan": "japan_official_catalog",
    "hong_kong": "hkjc_official_catalog",
    "united_kingdom": "bha_pattern_catalog",
    "france": "france_galop_pattern_catalog",
    "united_states": "toba_graded_stakes_catalog",
}
REGION_PREFIXES = {
    "japan": "japan",
    "hong_kong": "hong-kong",
    "united_kingdom": "united-kingdom",
    "france": "france",
    "united_states": "united-states",
}
MIN_REGION_ROWS = {
    "japan": 50,
    "hong_kong": 3,
    "united_kingdom": 50,
    "france": 50,
    "united_states": 300,
}
CSV_FIELDS = [
    "record_type",
    "year",
    "series_key",
    "canonical_name_original",
    "original_name",
    "chinese_name",
    "grade_text",
    "racecourse",
    "local_date",
    "distance_text",
    "surface",
    "expectation_status",
    "founded_year",
    "ended_year",
    "series_status",
    "season_label",
    "source_scope",
    "discipline",
    "raw_source_cache_path",
    "raw_source_cache_sha256",
    "raw_source_url",
    "source_duplicate_count",
]
GRADE_RE = re.compile(r"(?<![A-Z])(?:HK\s*)?G\s*([123])(?!\d)", re.I)
LISTED_RE = re.compile(r"\((?:L|LR)\)", re.I)
DOTS_RE = re.compile(r"\s*\.{2,}\s*")
AGE_RE = re.compile(r"\b(?:[2-9](?:yo|up)|[2-9]-[2-9]yo)\b", re.I)
DISTANCE_SURFACE_RE = re.compile(r"\b(?:a\s*)?(\d+(?:\.\d+)?)(?:\s*a)?\s*(T|D|AWT)\b", re.I)
ROW_END_RE = re.compile(r"\b(?:[2-9](?:yo|up)|[2-9]-[2-9]yo)\b.*\b(?:a\s*)?\d+(?:\.\d+)?(?:\s*a)?(?:\s*(?:T|D|AWT))?\b", re.I)
DECLARED_TOTAL_RE = re.compile(r"Total\s+(?:Graded|Group)\s+races\s*:\s*\.*\s*(\d+)", re.I)
UNSUPPORTED_SECTION_RE = re.compile(
    r"PT(?:I|II|IV)[—-](?:ARGENTINA|AUSTRALIA|BRAZIL|CANADA|CHILE|CZECHREPUBLIC|GERMAN(?:Y|JUMPS)|INDIA|IRELAND|IRISHJUMPS|ITALY|ITALIANJUMPS|KOREA|MACAU|MALAYSIA|NEWZEALAND(?:JUMPS)?|PANAMA|PERU|PUERTORICO|SCANDINAVIA|SINGAPORE|SOUTHAFRICA|SPAIN|SWITZERLANDJUMPS|UNITEDARABEMIRATES|URUGUAY|VENEZUELA)"
)
UNSUPPORTED_COUNTRY_TITLES = {
    "ARGENTINA",
    "AUSTRALIA",
    "BRAZIL",
    "CANADA",
    "CHILE",
    "CZECHREPUBLIC",
    "GERMANY",
    "INDIA",
    "IRELAND",
    "ITALY",
    "KOREA",
    "MACAU",
    "MALAYSIA",
    "NEWZEALAND",
    "PANAMA",
    "PERU",
    "PUERTORICO",
    "SCANDINAVIA",
    "SINGAPORE",
    "SOUTHAFRICA",
    "SPAIN",
    "SWITZERLAND",
    "UNITEDARABEMIRATES",
    "URUGUAY",
    "VENEZUELA",
}


class IcsCatalogError(RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def require_network_gates(*, allow_network: bool, environ: dict[str, str] | os._Environ[str] = os.environ) -> None:
    if not allow_network:
        raise IcsCatalogError("真实下载必须显式传入 --allow-network")
    if not _enabled(environ.get("HISTORICAL_RACE_BACKFILL_ENABLED")):
        raise IcsCatalogError("HISTORICAL_RACE_BACKFILL_ENABLED 未开启")
    if not _enabled(environ.get("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK")):
        raise IcsCatalogError("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK 未开启")


def _cached_source_identity(destination: Path, *, source_url: str) -> dict:
    configured = os.environ.get("RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST", "").strip()
    manifest_path = Path(configured) if configured else destination.parent / "source_cache_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        root = Path(manifest.get("root") or manifest_path.parent).resolve()
        relative = str(destination.resolve().relative_to(root))
        identity = manifest["files"][relative]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise IcsCatalogError(f"无法验证已有 source cache：{destination}") from exc
    if (
        identity.get("source_url") != source_url
        or not destination.is_file()
        or destination.stat().st_size != int(identity.get("size") or -1)
        or _sha256(destination) != identity.get("sha256")
    ):
        raise IcsCatalogError(f"已有 source cache 身份不一致：{destination}")
    return dict(identity)


def download_to_cache(url: str, destination: Path, *, timeout: int, reuse_existing: bool = False) -> dict:
    if destination.exists():
        if not reuse_existing:
            raise IcsCatalogError(f"source cache 已存在但未启用 --resume：{destination}")
        return _cached_source_identity(destination, source_url=url)
    before_network_request(url)
    req = request.Request(
        url,
        headers={"User-Agent": "UmaFansBot/1.0 (+https://umafans.run; low-frequency historical catalog import)"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    return write_source_cache(destination, body, source_url=url)


def _year_from_link(text: str, href: str) -> int | None:
    matches = re.findall(r"(?:19|20)\d{2}", f"{text} {href}")
    return int(matches[-1]) if matches else None


def discover_edition_links(html: str, *, base_url: str, years) -> dict[int, str]:
    wanted = set(years)
    candidates: dict[int, list[str]] = {}
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = str(anchor["href"])
        if not href.casefold().endswith(".pdf"):
            continue
        year = _year_from_link(anchor.get_text(" ", strip=True), href)
        if year not in wanted:
            continue
        filename = Path(href).name.casefold()
        if not any(marker in filename for marker in ("entirebook", "icsbook", "catstandardsbook", "book.pdf", "catstd")):
            continue
        candidates.setdefault(year, []).append(urljoin(base_url, href))
    links = {year: sorted(urls, key=len)[0] for year, urls in candidates.items()}
    missing = sorted(wanted - set(links))
    if missing:
        raise IcsCatalogError(f"官方索引缺少整本 Blue Book：{missing}")
    return links


def stable_series_key(region: str, name: str) -> str:
    value = canonical_series_name(name)
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    if not slug:
        slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{REGION_PREFIXES[region]}-{slug}"


def canonical_series_name(name: str) -> str:
    value = re.sub(r"\[[^\]]*]", " ", name)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _page_context(text: str) -> tuple[str | None, str]:
    upper = unicodedata.normalize("NFKC", text).upper().replace(" ", "")
    if "JUMPS" in upper or "JUMPRACES" in upper:
        if "GBJUMPS" in upper or "GREATBRITAINJUMPS" in upper or "GREATBRITAINJUMPRACES" in upper:
            return "united_kingdom", "jumps"
        if "FRJUMPS" in upper or "FRANCEJUMPS" in upper or "FRENCHJUMPS" in upper or "FRENCHJUMPRACES" in upper:
            return "france", "jumps"
        if "JPNJUMPS" in upper or "JAPANJUMPS" in upper or "JAPANESEJUMPS" in upper:
            return "japan", "jumps"
        if "USAJUMPS" in upper or "UNITEDSTATESJUMPS" in upper:
            return "united_states", "jumps"
    if re.search(r"PTI[—-](?:FR|FRA|FRANCE)(?:[A-Z-]|$)", upper):
        return "france", "flat"
    if re.search(r"PTI[—-](?:GB|GREATBRITAIN)", upper):
        return "united_kingdom", "flat"
    if re.search(r"PTI[—-](?:USA|UNITEDSTATES)", upper):
        return "united_states", "flat"
    if re.search(r"PT(?:I|II)[—-](?:JPN|JAPAN)", upper):
        return "japan", "flat"
    if re.search(r"PT(?:I|II)[—-](?:HK|HKG|HONGKONG)(?:[A-Z-]|$)", upper):
        return "hong_kong", "flat"
    if "PTI—OTHER" in upper or "PTI-OTHER" in upper:
        return "other", "flat"
    return None, "flat"


def _has_unsupported_country_title(text: str, compact_page: str) -> bool:
    if UNSUPPORTED_SECTION_RE.search(compact_page):
        return True
    titles = {re.sub(r"[^A-Z]", "", line.upper()) for line in text.splitlines()}
    return bool(titles & UNSUPPORTED_COUNTRY_TITLES)


def _hong_kong_segment(text: str) -> str:
    match = re.search(r"(?:^|\n)\s*H\s*O\s*N\s*G\s+K\s*O\s*N\s*G\s*(?:\n|$)", text, re.I)
    if not match:
        return ""
    tail = text[match.start() :]
    next_country = re.search(
        r"\n\s*(?:JAPAN|SCANDINAVIA|UNITED ARAB EMIRATES|KOREA|MACAU|MALAYSIA|PANAMA|PUERTO RICO|SINGAPORE)\s*\n",
        tail[match.end() - match.start() :],
        re.I,
    )
    if next_country:
        return tail[: match.end() - match.start() + next_country.start()]
    return tail


def _season_label(text: str, year: int) -> str:
    match = re.search(r"Racing season\s+\w+\s+(\d{4})\s*-\s*\w+\s+(\d{4})", text, re.I)
    if match:
        return f"{match.group(1)}/{match.group(2)[-2:]}"
    return f"{year - 1}/{str(year)[-2:]}"


def _metadata_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line).upper()
    return (
        not compact
        or compact.startswith(("PTI—", "PTII—", "PTIV—", "PARTI", "PARTII", "PARTIV"))
        or compact.startswith(("RACEPURSE", "RACEAGE", "GRADESIN", "RACESIN", "NUMBEROF", "TOTAL"))
        or compact.startswith(("UNITEDSTATESOFAMERICA(", "(USDOLLARS)", "(DOLLARS)", "(POUNDS)", "(FRANCS)", "(EURO)", "(YEN)"))
        or ("SURFACETYPE" in compact and ("METERS" in compact or "FURLONGS" in compact))
        or compact in {"FRANCE", "JAPAN", "HONGKONG", "GREATBRITAIN", "GREATBRITAINJUMPRACES", "UNITEDSTATESOFAMERICA", "OTHERRACES"}
        or compact.startswith("(RACINGSEASON")
        or re.fullmatch(r"\d+-\d+", compact) is not None
    )


def _record_complete(value: str) -> bool:
    return bool(ROW_END_RE.search(value) or (value.lstrip().startswith("*") and GRADE_RE.search(value)))


def _clean_name(value: str) -> str:
    value = DOTS_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value


def _parse_record(raw: str, *, region: str, discipline: str, year: int, season_label: str) -> dict | None:
    grade = GRADE_RE.search(raw)
    if not grade:
        return None
    not_held = raw.lstrip().startswith("*")
    name = _clean_name(raw[: grade.start()]).lstrip("*").strip()
    if not name or name.upper() in {"RACE", "PURSE"}:
        return None
    suffix = raw[grade.end() :]
    surface_match = DISTANCE_SURFACE_RE.search(suffix)
    distance = surface_match.group(1) if surface_match else ""
    surface_code = surface_match.group(2).upper() if surface_match else ""
    surface = "jumps" if discipline == "jumps" else {
        "T": "turf",
        "D": "dirt",
        "AWT": "synthetic",
        "": "" if not_held else "dirt",
    }[surface_code]
    columns = [part.strip(" .") for part in DOTS_RE.split(raw) if part.strip(" .")]
    racecourse = columns[-1] if len(columns) > 1 else ""
    return {
        "record_type": "catalog",
        "country_region": region,
        "year": year,
        "series_key": stable_series_key(region, name),
        "canonical_name_original": canonical_series_name(name),
        "original_name": name,
        "chinese_name": "",
        "grade_text": f"G{grade.group(1)}",
        "racecourse": racecourse,
        "local_date": "",
        "distance_text": distance,
        "surface": surface,
        "expectation_status": "not_held" if not_held else "held",
        "founded_year": "",
        "ended_year": "",
        "series_status": "unknown",
        "season_label": season_label if region == "hong_kong" else "",
        "source_scope": (
            "international_cataloguing_standards_asterisk_not_held"
            if not_held
            else "international_cataloguing_standards"
        ),
        "discipline": discipline,
    }


def _deduplicate_and_disambiguate_same_year_keys(rows: list[dict]) -> list[dict]:
    exact_rows: dict[tuple, dict] = {}
    for row in rows:
        fingerprint = tuple(
            row.get(field)
            for field in (
                "country_region",
                "year",
                "series_key",
                "original_name",
                "grade_text",
                "racecourse",
                "distance_text",
                "surface",
                "discipline",
                "expectation_status",
            )
        )
        existing = exact_rows.get(fingerprint)
        if existing is None:
            row["source_duplicate_count"] = 1
            exact_rows[fingerprint] = row
        else:
            existing["source_duplicate_count"] += 1
    deduplicated = list(exact_rows.values())
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in deduplicated:
        grouped.setdefault((row["country_region"], row["series_key"]), []).append(row)
    for duplicates in grouped.values():
        if len(duplicates) < 2:
            continue
        seen = set()
        for row in duplicates:
            identity_text = " ".join(
                str(row.get(field) or "")
                for field in ("racecourse", "discipline", "distance_text", "surface", "grade_text")
            )
            identity_slug = stable_series_key(row["country_region"], identity_text).split(
                REGION_PREFIXES[row["country_region"]] + "-", 1
            )[-1]
            proposed = f"{row['series_key']}-{identity_slug}"
            if proposed in seen:
                raise IcsCatalogError(
                    f"{row['year']} 同名同场赛事无法自动区分：{row['original_name']}/{row['racecourse']}"
                )
            row["series_key"] = proposed
            seen.add(proposed)
    return deduplicated


def _declared_totals(pages: list[str]) -> dict[tuple[str, str], int]:
    totals: dict[tuple[str, str], int] = {}
    current_region = None
    current_discipline = "flat"
    for page_text in pages:
        appendix_starts = re.search(r"(?:^|\n)\s*APPENDIX\s*-", page_text, re.I)
        if appendix_starts:
            page_text = page_text[: appendix_starts.start()]
        detected_region, detected_discipline = _page_context(page_text)
        compact_page = re.sub(r"\s+", "", unicodedata.normalize("NFKC", page_text)).upper()
        if detected_region:
            current_region, current_discipline = detected_region, detected_discipline
        elif _has_unsupported_country_title(page_text, compact_page):
            current_region, current_discipline = None, "flat"
        if current_region == "other":
            current_region = "hong_kong"
        if current_region:
            for match in DECLARED_TOTAL_RE.finditer(page_text):
                key = (current_region, current_discipline)
                totals[key] = totals.get(key, 0) + int(match.group(1))
        if appendix_starts:
            current_region, current_discipline = None, "flat"
    return totals


def parse_ics_pages(pages: list[str], *, year: int) -> list[dict]:
    rows = []
    current_region = None
    current_discipline = "flat"
    for page_text in pages:
        appendix_starts = re.search(r"(?:^|\n)\s*APPENDIX\s*-", page_text, re.I)
        if appendix_starts:
            page_text = page_text[: appendix_starts.start()]
        detected_region, detected_discipline = _page_context(page_text)
        compact_page = re.sub(r"\s+", "", unicodedata.normalize("NFKC", page_text)).upper()
        if detected_region:
            current_region, current_discipline = detected_region, detected_discipline
        elif _has_unsupported_country_title(page_text, compact_page):
            current_region, current_discipline = None, "flat"
        region, discipline = current_region, current_discipline
        if not region:
            continue
        text = _hong_kong_segment(page_text) if region == "other" else page_text
        if region == "other":
            region = "hong_kong"
        if not text:
            continue
        season = _season_label(text, year) if region == "hong_kong" else ""
        buffer: list[str] = []
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if _metadata_line(line):
                continue
            if line.lstrip().startswith("*") and (GRADE_RE.search(line) or LISTED_RE.search(line)):
                buffer = []
                row = _parse_record(
                    line,
                    region=region,
                    discipline=discipline,
                    year=year,
                    season_label=season,
                )
                if row:
                    rows.append(row)
                continue
            buffer.append(line)
            combined = " ".join(buffer)
            if not _record_complete(combined):
                continue
            row = _parse_record(combined, region=region, discipline=discipline, year=year, season_label=season)
            if row:
                rows.append(row)
            buffer = []
        if appendix_starts:
            current_region, current_discipline = None, "flat"
    if not rows:
        raise IcsCatalogError(f"{year} Blue Book parsed zero graded rows")
    parsed_totals = {}
    for row in rows:
        key = (row["country_region"], row["discipline"])
        parsed_totals[key] = parsed_totals.get(key, 0) + 1
    for key, declared in _declared_totals(pages).items():
        if parsed_totals.get(key, 0) != declared:
            raise IcsCatalogError(
                f"{year} {key[0]}/{key[1]} graded total mismatch: "
                f"parsed={parsed_totals.get(key, 0)} declared={declared}"
            )
    return _deduplicate_and_disambiguate_same_year_keys(rows)


def _pdf_pages(path: Path) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_year_region_csv(output_dir: Path, rows: list[dict], *, year: int, raw_identity: dict, raw_url: str) -> Path:
    region = rows[0]["country_region"]
    path = output_dir / "derived" / region / f"{year}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "raw_source_cache_path": raw_identity["path"],
                    "raw_source_cache_sha256": raw_identity["sha256"],
                    "raw_source_url": raw_url,
                }
            )
    return path


def _missing_regions(rows: list[dict]) -> list[str]:
    return [
        region
        for region in REGION_ADAPTERS
        if not any(row.get("country_region") == region for row in rows)
    ]


def _implausibly_small_regions(rows: list[dict]) -> dict[str, int]:
    counts = {
        region: sum(row.get("country_region") == region for row in rows)
        for region in REGION_ADAPTERS
    }
    return {
        region: count
        for region, count in counts.items()
        if count and count < MIN_REGION_ROWS[region]
    }


def prepare_catalog(args) -> dict:
    years = sorted(set(args.years))
    if not years or years[0] < 1998:
        raise IcsCatalogError("TJCIS 在线整本归档仅支持从 1998 年开始")
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not args.resume:
        raise IcsCatalogError(f"输出目录非空：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    expected_sources = [
        output_dir / "source" / "tjcis_past_editions.html",
        output_dir / "source" / "tjcis_current_editions.html",
        *(output_dir / "source" / f"tjcis_ics_{year}.pdf" for year in years),
    ]
    if not args.resume or any(not path.exists() for path in expected_sources):
        require_network_gates(allow_network=args.allow_network)

    index_identities = []
    all_links = {}
    for label, url in (("past", PAST_EDITIONS_URL), ("current", CURRENT_EDITION_URL)):
        destination = output_dir / "source" / f"tjcis_{label}_editions.html"
        identity = download_to_cache(
            url,
            destination,
            timeout=args.timeout_seconds,
            reuse_existing=args.resume,
        )
        index_identities.append(identity)
        html = destination.read_text(encoding="utf-8", errors="replace")
        requested = [year for year in years if (year < datetime.now().year) == (label == "past")]
        if requested:
            all_links.update(discover_edition_links(html, base_url=BASE_URL, years=requested))

    csv_by_region: dict[str, list[dict]] = {region: [] for region in REGION_ADAPTERS}
    raw_sources = []
    counts = {}
    year_errors = {}
    for year in years:
        url = all_links[year]
        pdf_path = output_dir / "source" / f"tjcis_ics_{year}.pdf"
        identity = download_to_cache(
            url,
            pdf_path,
            timeout=args.timeout_seconds,
            reuse_existing=args.resume,
        )
        raw_sources.append(identity)
        try:
            rows = parse_ics_pages(_pdf_pages(pdf_path), year=year)
            missing_regions = _missing_regions(rows)
            if missing_regions:
                raise IcsCatalogError(
                    f"{year} Blue Book 未解析出地区分级赛：{', '.join(missing_regions)}"
                )
            implausible_regions = _implausibly_small_regions(rows)
            if implausible_regions:
                details = ", ".join(
                    f"{region}={count}<{MIN_REGION_ROWS[region]}"
                    for region, count in implausible_regions.items()
                )
                raise IcsCatalogError(f"{year} Blue Book 地区解析数量异常偏低：{details}")
        except IcsCatalogError as exc:
            if not args.continue_on_year_error:
                raise
            year_errors[str(year)] = str(exc)
            continue
        counts[str(year)] = {}
        for region in REGION_ADAPTERS:
            region_rows = [row for row in rows if row["country_region"] == region]
            csv_path = _write_year_region_csv(
                output_dir,
                region_rows,
                year=year,
                raw_identity=identity,
                raw_url=url,
            )
            csv_by_region[region].append(
                {"path": str(csv_path.relative_to(output_dir)), "sha256": _sha256(csv_path), "source_url": url}
            )
            counts[str(year)][region] = len(region_rows)

    manifest_paths = []
    for region, adapter_key in REGION_ADAPTERS.items():
        if not csv_by_region[region]:
            raise IcsCatalogError(f"没有任何成功年份可供 {region} 生成 manifest")
        manifest = {
            "schema_version": "1.0",
            "adapter_key": adapter_key,
            "parser_version": PARSER_VERSION,
            "source_provider": "tjcis",
            "source_authority": "official_archive",
            "supported_years": {"start": years[0], "end": years[-1]},
            "cache_files": csv_by_region[region],
            "raw_sources": raw_sources,
            "index_sources": index_identities,
            "excluded_year_errors": year_errors,
        }
        path = output_dir / f"manifest_{region}.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_paths.append(str(path))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "years": years,
        "counts": counts,
        "manifest_paths": manifest_paths,
        "successful_years": sorted(int(year) for year in counts),
        "year_errors": year_errors,
        "status": "partial" if year_errors else "complete",
        "network_switches_after_run": "operator_must_restore_both_to_false",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def _parse_years(value: str) -> list[int]:
    years = []
    for item in value.split(","):
        item = item.strip()
        if "-" in item:
            start, end = (int(part) for part in item.split("-", 1))
            years.extend(range(start, end + 1))
        elif item:
            years.append(int(item))
    return years


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并离线解析 TJCIS International Cataloguing Standards 年鉴。")
    parser.add_argument("--years", type=_parse_years, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-year-error", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare_catalog(args)
    except IcsCatalogError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["year_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
