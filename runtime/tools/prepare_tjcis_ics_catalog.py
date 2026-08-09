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
PARSER_VERSION = "2026.08.1"
REGION_ADAPTERS = {
    "japan": "japan_official_catalog",
    "hong_kong": "hkjc_official_catalog",
    "united_kingdom": "bha_pattern_catalog",
    "france": "france_galop_pattern_catalog",
    "united_states": "toba_graded_stakes_catalog",
    "australia": "racing_australia_pattern_catalog",
    "germany": "deutscher_galopp_pattern_catalog",
    "middle_east": "middle_east_official_pattern_catalog",
}
REGION_PREFIXES = {
    "japan": "japan",
    "hong_kong": "hong-kong",
    "united_kingdom": "united-kingdom",
    "france": "france",
    "united_states": "united-states",
    "australia": "australia",
    "germany": "germany",
    "middle_east": "middle-east",
    "united_arab_emirates": "united-arab-emirates",
    "saudi_arabia": "saudi-arabia",
    "qatar": "qatar",
    "bahrain": "bahrain",
}
MIN_REGION_ROWS = {
    "japan": 50,
    "hong_kong": 3,
    "united_kingdom": 50,
    "france": 50,
    "united_states": 300,
    "australia": 100,
    "germany": 15,
    "middle_east": 10,
}
CSV_FIELDS = [
    "record_type",
    "country",
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
GRADE_RE = re.compile(r"(?:HK\s*)?G\s*([123])(?=$|[^0-9]|\d{1,3},\d{3})", re.I)
LISTED_RE = re.compile(r"\((?:L|LR)\)", re.I)
DOTS_RE = re.compile(r"\s*(?:\.\s*){2,}")
AGE_PATTERN = (
    r"(?:[2-9]\s*(?:y(?:o)?|u(?:p)?)|[2-9]\s*[-/]\s*[2-9](?:\s*y(?:o)?)?"
    r"|[2-9]-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))"
)
AGE_RE = re.compile(rf"\b{AGE_PATTERN}\b", re.I)
DISTANCE_SURFACE_RE = re.compile(r"\b(?:a\s*)?(\d+(?:\.\d+)?)(?:\s*a)?\s*(T|D|AWT)\b", re.I)
JUMP_DISTANCE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
ROW_END_RE = re.compile(
    rf"\b{AGE_PATTERN}\b.*"
    r"\b(?:a\s*)?\d+(?:\.\d+)?(?:\s*a)?(?:\s*(?:T|D|AWT))?\b",
    re.I,
)
DECLARED_TOTAL_RE = re.compile(r"Total\s+(?:Graded|Group)\s+races\s*:\s*\.*\s*(\d+)", re.I)
DECLARED_GRADE_RE = re.compile(r"Number\s+of\s+G\s*([123])\s+races\s*:\s*\.*\s*(\d+)", re.I)
SUPPLEMENT_BOUNDARY_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:APPENDIX\b|\*+[ \t]*Race additions and changes in red\b)",
    re.I,
)
SOURCE_CONFLICT_POLICY = "explicit_graded_rows_with_regional_official_corrections"
UNSUPPORTED_SECTION_RE = re.compile(
    r"PT(?:I|II|IV)[—-](?:ARGENTINA|BRAZIL|CANADA|CHILE|CZECHREPUBLIC|INDIA|IRE(?:LAND)?(?:JUMPS?)?|IRISHJUMPS|ITALY|ITALIANJUMPS|KOREA|MACAU|MALAYSIA|NEWZEALAND(?:JUMPS)?|PANAMA|PERU|PUERTORICO|SCANDINAVIA|SINGAPORE|SOUTHAFRICA|SPAIN|SWITZERLANDJUMPS|URUGUAY|VENEZUELA|INDEX)"
)
UNSUPPORTED_COUNTRY_TITLES = {
    "ARGENTINA",
    "BRAZIL",
    "CANADA",
    "CHILE",
    "CZECHREPUBLIC",
    "INDIA",
    "IRELAND",
    "IRELANDJUMPRACES",
    "IRISHJUMPRACES",
    "ITALY",
    "ITALIANJUMPRACES",
    "INDEX",
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
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    punctuation_spaced = "".join(" " if unicodedata.category(char)[0] in {"P", "S"} else char for char in value)
    ascii_value = unicodedata.normalize("NFKD", punctuation_spaced).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    if not slug:
        slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{REGION_PREFIXES[region]}-{slug}"


def _raw_identity_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def canonical_series_name(name: str) -> str:
    value = re.sub(r"\[[^\]]*]", " ", name)
    value = re.sub(r"\s*\(\s*[HR]\s*\)\s*$", "", value, flags=re.I)
    value = re.sub(r"\bH\.?\s+(?=(?:Stp|Hurdle)\b)", "", value, flags=re.I)
    value = re.sub(r"(?:\s+[SHR]\.?)\s*$", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _page_context(text: str) -> tuple[str | None, str]:
    upper = unicodedata.normalize("NFKC", text).upper().replace(" ", "")
    if re.search(r"PTIV[—-]INDEX", upper):
        return None, "flat"
    if "JUMPS" in upper or "JUMPRACES" in upper:
        if "GBJUMPS" in upper or "GREATBRITAINJUMPS" in upper or "GREATBRITAINJUMPRACES" in upper:
            return "united_kingdom", "jumps"
        if "FRJUMPS" in upper or "FRANCEJUMPS" in upper or "FRENCHJUMPS" in upper or "FRENCHJUMPRACES" in upper:
            return "france", "jumps"
        if "JPNJUMPS" in upper or "JAPANJUMPS" in upper or "JAPANESEJUMPS" in upper:
            return "japan", "jumps"
        if "USAJUMPS" in upper or "UNITEDSTATESJUMPS" in upper:
            return "united_states", "jumps"
    if re.search(r"PTI[—-](?:FRANCE|FRA|FR)", upper):
        return "france", "flat"
    if re.search(r"PTI[—-](?:GB|GREATBRITAIN)", upper):
        return "united_kingdom", "flat"
    if re.search(r"PTI[—-](?:USA|UNITEDSTATES)", upper):
        return "united_states", "flat"
    if re.search(r"PT(?:I|II)[—-](?:JPN|JAPAN)", upper):
        return "japan", "flat"
    if re.search(r"PT(?:I|II)[—-](?:HONGKONG|HKG|HK)", upper):
        return "hong_kong", "flat"
    if re.search(r"PTI[—-]AUSTRALIA", upper):
        return "australia", "flat"
    if re.search(r"PTI[—-]GERMANY", upper):
        return "germany", "flat"
    if re.search(r"PTI[—-]UNITEDARABEMIRATES", upper):
        return "united_arab_emirates", "flat"
    if re.search(r"PT(?:I|II)[—-](?:OTHERRACES.*)?BAHRAIN", upper, re.S):
        return "bahrain", "flat"
    if re.search(r"PT(?:I|II)[—-](?:OTHER(?:RACES)?.*)?QATAR", upper, re.S):
        return "qatar", "flat"
    if re.search(r"PT(?:I|II)[—-](?:OTHERRACES.*)?(?:KINGDOMOF)?SAUDIARABIA", upper, re.S):
        return "saudi_arabia", "flat"
    if "PTI—OTHER" in upper or "PTI-OTHER" in upper:
        return "other", "flat"
    return None, "flat"


def _has_unsupported_country_title(text: str) -> bool:
    compact_lines = [
        re.sub(r"\s+", "", unicodedata.normalize("NFKC", line)).upper()
        for line in text.splitlines()
    ]
    if any(UNSUPPORTED_SECTION_RE.match(line) for line in compact_lines):
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


def _country_segment(text: str, region: str) -> str:
    headings = {
        "bahrain": r"BAHRAIN",
        "qatar": r"QATAR",
        "saudi_arabia": r"(?:Kingdom\s+of\s+)?SAUDI\s+ARABIA",
    }
    heading = headings.get(region)
    if not heading:
        return text
    match = re.search(rf"(?:^|\n)\s*{heading}\s*(?:\n|$)", text, re.I)
    if not match:
        return text
    first_grade = GRADE_RE.search(text)
    if first_grade and first_grade.start() < match.start():
        # Some legacy/extracted fixtures place the section marker as a footer.
        return text
    tail = text[match.start() :]
    next_country = re.search(
        r"\n\s*(?:ITALY|KINGDOM\s+OF\s+SAUDI\s+ARABIA|SAUDI\s+ARABIA|BAHRAIN|"
        r"QATAR|UNITED\s+ARAB\s+EMIRATES|TURKEY|SPAIN|POLAND|SCANDINAVIA|KOREA|MACAU|MALAYSIA)\s*\n",
        tail[match.end() - match.start() :],
        re.I,
    )
    if next_country:
        return tail[: match.end() - match.start() + next_country.start()]
    return tail


MIDDLE_EAST_HEADING_RE = re.compile(
    r"(?im)^\s*(UNITED\s+ARAB\s+EMIRATES|BAHRAIN|QATAR|(?:KINGDOM\s+OF\s+)?SAUDI\s+ARABIA)\s*$"
)


def _middle_east_country_segments(text: str) -> list[tuple[str, str]]:
    """Split a multi-country Other Races page without guessing race identity."""
    matches = list(MIDDLE_EAST_HEADING_RE.finditer(text))
    if len(matches) < 2:
        return []
    regions = {
        "UNITED ARAB EMIRATES": "united_arab_emirates",
        "BAHRAIN": "bahrain",
        "QATAR": "qatar",
        "SAUDI ARABIA": "saudi_arabia",
        "KINGDOM OF SAUDI ARABIA": "saudi_arabia",
    }
    first_grade = GRADE_RE.search(text)
    footer_layout = bool(first_grade and first_grade.start() < matches[0].start())
    segments = []
    for index, match in enumerate(matches):
        heading = re.sub(r"\s+", " ", match.group(1)).upper()
        region = regions[heading]
        if footer_layout:
            start = matches[index - 1].end() if index else 0
            end = match.end()
        else:
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = _country_segment(text[start:end], region)
        if GRADE_RE.search(segment):
            segments.append((region, segment))
    return segments


def _parse_page_records(text: str, *, region: str, discipline: str, year: int) -> list[dict]:
    season = _season_label(text, year) if region == "hong_kong" else ""
    rows = []
    buffer: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if _metadata_line(line):
            continue
        if buffer:
            buffered = " ".join(buffer)
            if DOTS_RE.search(buffered) and AGE_RE.search(buffered) and not (
                GRADE_RE.search(buffered) or LISTED_RE.search(buffered)
            ):
                buffer = []
        if line.lstrip().startswith("*") and (GRADE_RE.search(line) or LISTED_RE.search(line)):
            buffer = []
            row = _parse_record(line, region=region, discipline=discipline, year=year, season_label=season)
            if row:
                rows.append(row)
            continue
        if buffer and (GRADE_RE.search(line) or LISTED_RE.search(line)):
            buffered = " ".join(buffer)
            if GRADE_RE.search(buffered) or LISTED_RE.search(buffered) or DOTS_RE.search(buffered):
                buffer = []
        buffer.append(line)
        combined = " ".join(buffer)
        if not _record_complete(combined, discipline=discipline):
            continue
        row = _parse_record(combined, region=region, discipline=discipline, year=year, season_label=season)
        if row:
            rows.append(row)
        buffer = []
    return rows


def _season_label(text: str, year: int) -> str:
    match = re.search(r"Racing season\s+\w+\s+(\d{4})\s*-\s*\w+\s+(\d{4})", text, re.I)
    if match:
        return f"{match.group(1)}/{match.group(2)[-2:]}"
    return f"{year - 1}/{str(year)[-2:]}"


def _metadata_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line).upper()
    return (
        not compact
        or re.search(r"PT(?:I|II|IV)[—-]", compact) is not None
        or compact.startswith(("PTI—", "PTII—", "PTIV—", "PARTI", "PARTII", "PARTIV"))
        or compact.startswith(("RACEPURSE", "RACEAGE", "GRADESIN", "RACESIN", "NUMBEROF", "TOTAL"))
        or compact.startswith(("UNITEDSTATESOFAMERICA(", "(USDOLLARS)", "(DOLLARS)", "(POUNDS)", "(FRANCS)", "(EURO)", "(YEN)"))
        or ("SURFACETYPE" in compact and ("METERS" in compact or "FURLONGS" in compact))
        or compact in {
            "FRANCE",
            "JAPAN",
            "HONGKONG",
            "GREATBRITAIN",
            "GREATBRITAINJUMPRACES",
            "FRENCHJUMPRACES",
            "JAPANESEJUMPRACES",
            "UNITEDSTATESJUMPS",
            "UNITEDSTATESJUMPRACES",
            "UNITEDSTATESOFAMERICA",
            "OTHERRACES",
            "AUSTRALIA",
            "GERMANY",
            "UNITEDARABEMIRATES",
            "BAHRAIN",
            "QATAR",
            "SAUDIARABIA",
            "KINGDOMOFSAUDIARABIA",
        }
        or re.fullmatch(r"\d{4}AQPSRACES:?", compact) is not None
        or compact.startswith("(RACINGSEASON")
        or re.fullmatch(r"\d+-\d+", compact) is not None
    )


def _record_complete(value: str, *, discipline: str) -> bool:
    if value.lstrip().startswith("*") and GRADE_RE.search(value):
        return True
    if discipline == "jumps":
        return bool((GRADE_RE.search(value) or LISTED_RE.search(value)) and AGE_RE.search(value))
    return bool(ROW_END_RE.search(value))


def _clean_name(value: str) -> str:
    value = DOTS_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = re.sub(
        r"^(?:(?:HONG KONG(?:\s+SAR,?\s*CHINA)?|JAPAN|UNITED STATES OF AMERICA|AUSTRALIA|GERMANY|UNITED ARAB EMIRATES|BAHRAIN|(?:KINGDOM OF )?SAUDI ARABIA)\s+)?"
        r"(?:(?:JAPANESE|UNITED STATES) JUMP ?RACES\s+)?"
        r"(?:\([^)]*(?:DOLLARS|POUNDS|YEN|METERS|FURLONGS|SURFACE|HK\$)[^)]*\)\s*)+",
        "",
        value,
        flags=re.I,
    ).strip()
    value = re.sub(r"\s+[123]\s*$", "", value)
    value = re.sub(r"\s*QA\s*$", "", value, flags=re.I)
    return value.strip(" .").rstrip(" (")


def _parse_record(raw: str, *, region: str, discipline: str, year: int, season_label: str) -> dict | None:
    grade = GRADE_RE.search(raw)
    if not grade:
        return None
    not_held = raw.lstrip().startswith("*")
    name = _clean_name(raw[: grade.start()]).lstrip("*").strip()
    if not name or name.upper() in {"RACE", "PURSE"}:
        return None
    suffix = raw[grade.end() :]
    is_aqps = region == "france" and re.match(r"\s*AQ\b", suffix, re.I) is not None
    surface_match = DISTANCE_SURFACE_RE.search(suffix)
    age_match = AGE_RE.search(suffix)
    jump_distance_match = JUMP_DISTANCE_RE.search(suffix[age_match.end() :]) if age_match else None
    distance = (
        surface_match.group(1)
        if surface_match
        else jump_distance_match.group(1)
        if discipline == "jumps" and jump_distance_match
        else ""
    )
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
            "international_cataloguing_standards_aqps_asterisk_not_held"
            if is_aqps and not_held
            else "international_cataloguing_standards_aqps"
            if is_aqps
            else "international_cataloguing_standards_asterisk_not_held"
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
        proposed_rows: list[tuple[dict, str]] = []
        proposed_counts: dict[str, int] = {}
        for row in duplicates:
            identity_text = " ".join(
                str(row.get(field) or "")
                for field in ("racecourse", "discipline", "distance_text", "surface", "grade_text")
            )
            identity_slug = stable_series_key(row["country_region"], identity_text).split(
                REGION_PREFIXES[row["country_region"]] + "-", 1
            )[-1]
            proposed = f"{row['series_key']}-{identity_slug}"
            proposed_rows.append((row, proposed))
            proposed_counts[proposed] = proposed_counts.get(proposed, 0) + 1
        seen = set()
        for row, proposed in proposed_rows:
            if proposed_counts[proposed] > 1:
                full_name_slug = _raw_identity_slug(row["original_name"])
                proposed = f"{proposed}-{full_name_slug}"
            if proposed in seen:
                raise IcsCatalogError(
                    f"{row['year']} 同名同场赛事无法自动区分：{row['original_name']}/{row['racecourse']}"
                )
            row["series_key"] = proposed
            seen.add(proposed)
    return deduplicated


def _normalized_identity_component(value: str) -> str:
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value or ""))
    punctuation_spaced = "".join(" " if unicodedata.category(char)[0] in {"P", "S"} else char for char in text)
    ascii_value = unicodedata.normalize("NFKD", punctuation_spaced).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def _global_disambiguate_ambiguous_series(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        identity = _normalized_identity_component(canonical_series_name(row["original_name"]))
        grouped.setdefault((row["country_region"], identity), []).append(row)

    for candidates in grouped.values():
        if len({row["series_key"] for row in candidates}) < 2:
            continue
        proposed_buckets: dict[str, list[dict]] = {}
        for row in candidates:
            distance = str(row.get("distance_text") or "").strip()
            try:
                distance = f"{float(distance):g}" if distance else ""
            except ValueError:
                pass
            identity_text = " ".join(
                str(value or "")
                for value in (
                    row.get("racecourse"),
                    row.get("discipline"),
                    distance,
                    row.get("surface"),
                )
            )
            suffix = _raw_identity_slug(_normalized_identity_component(identity_text))
            base = stable_series_key(row["country_region"], row["original_name"])
            proposed_buckets.setdefault(f"{base}-{suffix}", []).append(row)

        for proposed, bucket in proposed_buckets.items():
            year_counts: dict[int, int] = {}
            for row in bucket:
                year_counts[row["year"]] = year_counts.get(row["year"], 0) + 1
            requires_full_name = any(count > 1 for count in year_counts.values())
            for row in bucket:
                row["series_key"] = (
                    f"{proposed}-{_raw_identity_slug(_normalized_identity_component(row['original_name']))}"
                    if requires_full_name
                    else proposed
                )
    return rows


def _declared_counts(pages: list[str]) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], dict[str, int]]]:
    total_values: dict[tuple[str, str], set[int]] = {}
    grade_values: dict[tuple[str, str], dict[str, set[int]]] = {}
    current_region = None
    current_discipline = "flat"
    for page_text in pages:
        appendix_starts = SUPPLEMENT_BOUNDARY_RE.search(page_text)
        if appendix_starts:
            page_text = page_text[: appendix_starts.start()]
        detected_region, detected_discipline = _page_context(page_text)
        if detected_region:
            current_region, current_discipline = detected_region, detected_discipline
        elif _has_unsupported_country_title(page_text):
            current_region, current_discipline = None, "flat"
        if current_region == "other":
            current_region = "hong_kong"
        if current_region:
            for match in DECLARED_TOTAL_RE.finditer(page_text):
                key = (current_region, current_discipline)
                total_values.setdefault(key, set()).add(int(match.group(1)))
            for match in DECLARED_GRADE_RE.finditer(page_text):
                key = (current_region, current_discipline)
                grade = f"G{match.group(1)}"
                grade_values.setdefault(key, {}).setdefault(grade, set()).add(int(match.group(2)))
        if appendix_starts:
            current_region, current_discipline = None, "flat"
    conflicts = {key: sorted(values) for key, values in total_values.items() if len(values) > 1}
    grade_conflicts = {
        (key, grade): sorted(values)
        for key, grades in grade_values.items()
        for grade, values in grades.items()
        if len(values) > 1
    }
    if conflicts or grade_conflicts:
        raise IcsCatalogError(
            f"official declared count conflict: totals={conflicts} grades={grade_conflicts}"
        )
    totals = {key: next(iter(values)) for key, values in total_values.items()}
    grades = {
        key: {grade: next(iter(values)) for grade, values in values_by_grade.items()}
        for key, values_by_grade in grade_values.items()
    }
    return totals, grades


def _declared_totals(pages: list[str]) -> dict[tuple[str, str], int]:
    totals, _grades = _declared_counts(pages)
    return totals


def parse_ics_pages(
    pages: list[str],
    *,
    year: int,
    declared_count_conflicts: list[dict] | None = None,
) -> list[dict]:
    rows = []
    current_region = None
    current_discipline = "flat"
    for page_text in pages:
        appendix_starts = SUPPLEMENT_BOUNDARY_RE.search(page_text)
        if appendix_starts:
            page_text = page_text[: appendix_starts.start()]
        detected_region, detected_discipline = _page_context(page_text)
        if detected_region:
            current_region, current_discipline = detected_region, detected_discipline
        elif _has_unsupported_country_title(page_text):
            current_region, current_discipline = None, "flat"
        region, discipline = current_region, current_discipline
        country_segments = _middle_east_country_segments(page_text)
        if country_segments:
            for country_region, country_text in country_segments:
                rows.extend(
                    _parse_page_records(
                        country_text,
                        region=country_region,
                        discipline="flat",
                        year=year,
                    )
                )
            current_region, current_discipline = country_segments[-1][0], "flat"
            if appendix_starts:
                current_region, current_discipline = None, "flat"
            continue
        if not region:
            continue
        text = _hong_kong_segment(page_text) if region == "other" else _country_segment(page_text, region)
        if region == "other":
            region = "hong_kong"
        if not text:
            continue
        rows.extend(_parse_page_records(text, region=region, discipline=discipline, year=year))
        if appendix_starts:
            current_region, current_discipline = None, "flat"
    if not rows:
        raise IcsCatalogError(f"{year} Blue Book parsed zero graded rows")
    parsed_totals = {}
    for row in rows:
        key = (row["country_region"], row["discipline"])
        parsed_totals[key] = parsed_totals.get(key, 0) + 1
    declared_totals, declared_grades = _declared_counts(pages)
    for key, declared in declared_totals.items():
        parsed_grades = {
            grade: sum(
                row["country_region"] == key[0]
                and row["discipline"] == key[1]
                and row["grade_text"] == grade
                for row in rows
            )
            for grade in ("G1", "G2", "G3")
        }
        expected_grades = declared_grades.get(key, {})
        grade_mismatch = any(parsed_grades[grade] != value for grade, value in expected_grades.items())
        if parsed_totals.get(key, 0) != declared or grade_mismatch:
            conflict = {
                "year": year,
                "region": key[0],
                "discipline": key[1],
                "parsed_total": parsed_totals.get(key, 0),
                "declared_total": declared,
                "parsed_grades": parsed_grades,
                "declared_grades": expected_grades,
            }
            if declared_count_conflicts is not None:
                declared_count_conflicts.append(conflict)
                continue
            raise IcsCatalogError(
                f"{year} {key[0]}/{key[1]} graded total mismatch: "
                f"parsed={parsed_totals.get(key, 0)} declared={declared}; "
                f"parsed_grades={parsed_grades} declared_grades={expected_grades}"
            )
    middle_east_countries = {"united_arab_emirates", "saudi_arabia", "qatar", "bahrain"}
    for row in rows:
        source_region = row["country_region"]
        row["country"] = source_region if source_region in middle_east_countries else source_region
        if source_region in middle_east_countries:
            row["country_region"] = "middle_east"
    return _deduplicate_and_disambiguate_same_year_keys(rows)


def _load_source_conflict_approval(path_value: str | None) -> tuple[dict | None, dict | None]:
    if not path_value:
        return None, None
    path = Path(path_value).resolve()
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IcsCatalogError(f"无法读取来源冲突审批：{path}") from exc
    required = (
        "status",
        "approved_by",
        "approved_at",
        "policy",
        "review_path",
        "review_sha256",
        "expected_conflict_keys",
        "expected_conflicts_sha256",
    )
    missing = [field for field in required if not approval.get(field)]
    if missing:
        raise IcsCatalogError(f"来源冲突审批缺少字段：{missing}")
    if approval["status"] != "approved" or approval["policy"] != SOURCE_CONFLICT_POLICY:
        raise IcsCatalogError("来源冲突审批状态或策略不匹配")
    configured_review_path = Path(approval["review_path"])
    review_path = (
        configured_review_path.resolve()
        if configured_review_path.is_absolute()
        else (path.parent / configured_review_path).resolve()
    )
    if not review_path.is_file() or _sha256(review_path) != approval["review_sha256"]:
        raise IcsCatalogError("来源冲突审核文件身份不匹配")
    keys = approval["expected_conflict_keys"]
    if not isinstance(keys, list) or len(keys) != len({str(key) for key in keys}):
        raise IcsCatalogError("来源冲突审批键必须是无重复列表")
    if not re.fullmatch(r"[0-9a-f]{64}", str(approval["expected_conflicts_sha256"])):
        raise IcsCatalogError("来源冲突 payload SHA 格式错误")
    return approval, {"path": str(path), "sha256": _sha256(path)}


def _source_conflict_key(conflict: dict) -> str:
    return f"{conflict['year']}:{conflict['region']}:{conflict['discipline']}"


def _source_conflicts_sha256(conflicts: list[dict]) -> str:
    payload = sorted(conflicts, key=_source_conflict_key)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pdf_pages(path: Path) -> list[str]:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                pages.append(page.extract_text() or "")
            finally:
                # pdfplumber/pdfminer caches layout objects per page. A full
                # Blue Book is hundreds of pages, so release each page before
                # advancing to keep the runner's memory bounded.
                page.close()
    return pages


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


def _suspicious_catalog_names(rows: list[dict]) -> list[str]:
    suspicious = []
    for row in rows:
        name = str(row.get("original_name") or "")
        upper = name.upper()
        name_without_qualifiers = re.sub(r"\([^)]*\)|\[[^]]*]", " ", name)
        if (
            len(name) > 160
            or "RACE PAGE" in upper
            or "(L)" in upper
            or "TOTAL RACES" in upper
            or re.search(r"\b\d{1,3},\d{3}\b", name_without_qualifiers)
        ):
            suspicious.append(name)
    return suspicious


def prepare_catalog(args) -> dict:
    years = sorted(set(args.years))
    if not years or years[0] < 1998:
        raise IcsCatalogError("TJCIS 在线整本归档仅支持从 1998 年开始")
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not args.resume:
        raise IcsCatalogError(f"输出目录非空：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_conflict_approval, source_conflict_approval_identity = _load_source_conflict_approval(
        getattr(args, "source_conflict_approval", None)
    )
    approved_conflict_keys = set(source_conflict_approval["expected_conflict_keys"]) if source_conflict_approval else set()

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
    source_count_conflicts = []
    accepted_years: dict[int, tuple[list[dict], dict, str]] = {}
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
            year_source_conflicts = [] if source_conflict_approval else None
            rows = parse_ics_pages(
                _pdf_pages(pdf_path),
                year=year,
                declared_count_conflicts=year_source_conflicts,
            )
            if year_source_conflicts is not None:
                unexpected = {
                    _source_conflict_key(conflict) for conflict in year_source_conflicts
                } - approved_conflict_keys
                if unexpected:
                    raise IcsCatalogError(f"出现未审批的来源计数冲突：{sorted(unexpected)}")
                source_count_conflicts.extend(year_source_conflicts)
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
            suspicious_names = _suspicious_catalog_names(rows)
            if suspicious_names:
                raise IcsCatalogError(
                    f"{year} Blue Book 出现疑似跨行/索引污染：{suspicious_names[:3]}"
                )
        except IcsCatalogError as exc:
            if not args.continue_on_year_error:
                raise
            year_errors[str(year)] = str(exc)
            continue
        accepted_years[year] = (rows, identity, url)

    actual_conflict_keys = {_source_conflict_key(conflict) for conflict in source_count_conflicts}
    if source_conflict_approval and actual_conflict_keys != approved_conflict_keys:
        raise IcsCatalogError(
            "来源冲突审批集合与实际不一致："
            f"missing={sorted(approved_conflict_keys - actual_conflict_keys)} "
            f"unexpected={sorted(actual_conflict_keys - approved_conflict_keys)}"
        )
    if source_conflict_approval and _source_conflicts_sha256(source_count_conflicts) != source_conflict_approval[
        "expected_conflicts_sha256"
    ]:
        raise IcsCatalogError("来源冲突完整 payload 与审批 SHA 不一致")

    _global_disambiguate_ambiguous_series(
        [row for rows, _identity, _url in accepted_years.values() for row in rows]
    )
    for year, (rows, identity, url) in accepted_years.items():
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
            "source_count_conflicts": source_count_conflicts,
            "source_conflict_approval": source_conflict_approval_identity,
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
        "source_count_conflicts": source_count_conflicts,
        "source_conflict_approval": source_conflict_approval_identity,
        "status": (
            "partial"
            if year_errors
            else "complete_with_approved_source_conflicts"
            if source_count_conflicts
            else "complete"
        ),
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
    parser.add_argument("--source-conflict-approval")
    args = parser.parse_args()
    try:
        result = prepare_catalog(args)
    except IcsCatalogError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["year_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
