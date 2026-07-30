#!/usr/bin/env python3
"""采集 UmaFans 公共页中单年度分级赛的全部实际参赛马。

这是独立、只读、artifact-only 的研究入口。它不导入 Django，不连接数据库，也不读取生产
凭据。网络阶段只允许访问 UmaFans；finalize 阶段完全离线。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlsplit,
    urlunparse,
)
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


SCHEMA_VERSION = 1
PARSER_VERSION = "graded-race-participants-v1"
TOOL_POLICY_VERSION = "year-region-status-name-v1"
SAFE_STOP_EXIT_CODE = 75
PROFILE_SHARD_COUNT = 4
REQUEST_BUDGETS = {"races": 5000, "profiles": 2000}
ALLOWED_HOSTS = ("umafans.run", "www.umafans.run")
ALLOWED_SCHEMES = ("http", "https")
STAGES = ("races", "profiles", "merge_profiles", "finalize", "synthetic_smoke")
TERMINAL_ITEM_STATUSES = frozenset(
    {"success", "skipped", "permanent_error", "not_found", "evidence_gap"}
)
RETRYABLE_ITEM_STATUSES = frozenset({"retryable_error"})

TARGET_REGIONS = (
    "japan",
    "hong_kong",
    "united_states",
    "united_kingdom",
    "france",
    "australia",
    "germany",
    "middle_east",
)
REQUIRED_ENGLISH_REGIONS = frozenset(
    {
        "united_states",
        "united_kingdom",
        "france",
        "australia",
        "germany",
        "middle_east",
    }
)
REGION_OUTPUT = {
    "japan": "日本",
    "hong_kong": "中国香港",
    "united_states": "美国",
    "united_kingdom": "英国",
    "france": "法国",
    "australia": "澳大利亚",
    "germany": "德国",
    "middle_east": "中东",
}
REGION_LABELS = {
    "日本": ("japan", "japan"),
    "中国香港": ("hong_kong", "hong_kong"),
    "香港": ("hong_kong", "hong_kong"),
    "美国": ("united_states", "united_states"),
    "英国": ("united_kingdom", "united_kingdom"),
    "法国": ("france", "france"),
    "澳大利亚": ("australia", "australia"),
    "澳洲": ("australia", "australia"),
    "德国": ("germany", "germany"),
    "中东": ("middle_east", None),
    "阿联酋": ("middle_east", "united_arab_emirates"),
    "沙特阿拉伯": ("middle_east", "saudi_arabia"),
    "沙特": ("middle_east", "saudi_arabia"),
    "卡塔尔": ("middle_east", "qatar"),
    "巴林": ("middle_east", "bahrain"),
}
MIDDLE_EAST_COUNTRIES = frozenset(
    {"united_arab_emirates", "saudi_arabia", "qatar", "bahrain"}
)
MANIFEST_REGIONS = frozenset(
    {"australia", "germany", "middle_east", "out_of_scope"}
)
RACE_PARTICIPANT_FIELDS = (
    "region",
    "region_label",
    "country",
    "race_date",
    "race_name_zh",
    "race_name_original",
    "grade",
    "racecourse",
    "race_url",
    "race_page_sha256",
    "raw_finish_status",
    "horse_number",
    "horse_display_name",
    "profile_url",
    "jockey_name",
    "trainer_name",
    "finish_time",
    "margin",
    "participant_status",
    "normalized_finish_position",
)
HORSE_NAME_FIELDS = (
    "horse_key",
    "regions",
    "countries",
    "profile_url",
    "name_zh",
    "name_ja",
    "name_en",
    "profile_resolution_state",
    "required_english_status",
    "name_completeness",
    "name_issue_codes",
    "occurrence_count",
    "graded_race_count",
    "race_urls",
)
HORSE_REVIEW_FIELDS = HORSE_NAME_FIELDS[:11]
STANDARD_GRADES = frozenset({"G1", "G2", "G3"})
JAPAN_GRADES = frozenset(
    {"G1", "G2", "G3", "J-G1", "J-G2", "J-G3", "JPN1", "JPN2", "JPN3"}
)

NON_FINISH_STATUSES = {
    "DNF": "started_non_finish",
    "PU": "started_non_finish",
    "F": "started_non_finish",
    "UR": "started_non_finish",
    "RO": "started_non_finish",
    "BD": "started_non_finish",
    "中止": "started_non_finish",
    "落馬": "started_non_finish",
    "落马": "started_non_finish",
    "拉停": "started_non_finish",
    "未完赛": "started_non_finish",
    "未完賽": "started_non_finish",
    "骑师落马": "started_non_finish",
    "騎師落馬": "started_non_finish",
    "跌倒": "started_non_finish",
    "拒跑": "started_non_finish",
    "DSQ": "disqualified_after_start",
    "失格": "disqualified_after_start",
    "降着": "disqualified_after_start",
    "取消资格": "disqualified_after_start",
}
NON_STARTER_STATUSES = frozenset(
    {
        "SCR",
        "NR",
        "NON-RUNNER",
        "NON RUNNER",
        "RETIRED",
        "退赛",
        "退賽",
        "取消出赛",
        "取消出賽",
        "取消出走",
        "未出赛",
        "未出賽",
        "除外",
        "出走取消",
    }
)
PUBLIC_FINISHED_STATUSES = frozenset({"完赛", "完賽", "并列", "並列"})

HAN_RE = re.compile(r"[\u3400-\u9fff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
POSITION_RE = re.compile(r"\s*(\d+)(?:\s*(?:着|位|st|nd|rd|th))?\s*", re.I)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
DATE_RE = re.compile(r"\b(19\d{2}|20\d{2})-(\d{2})-(\d{2})\b")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.replace("\u3000", " ").split())


def normalize_identity(value: Any) -> str:
    text = normalize_space(value).casefold()
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", text)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def keys_sha256(keys: Iterable[str]) -> str:
    return sha256_bytes(canonical_json_bytes(sorted(set(map(str, keys)))))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            pass
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8"))


def validate_year(value: Any, *, current_utc_year: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError("year must be one four-digit integer")
    raw = str(value)
    if not re.fullmatch(r"\d{4}", raw):
        raise ValueError("year must be one four-digit integer")
    year = int(raw)
    upper = current_utc_year or datetime.now(timezone.utc).year
    if not 1984 <= year <= upper:
        raise ValueError(f"year must be between 1984 and {upper}")
    return year


def normalize_region_label(label: Any) -> tuple[str, str | None]:
    return REGION_LABELS.get(normalize_space(label), ("", None))


def normalize_country_fact(value: Any) -> str:
    text = normalize_space(value)
    aliases = {
        "日本": "japan",
        "中国香港": "hong_kong",
        "香港": "hong_kong",
        "美国": "united_states",
        "美國": "united_states",
        "英国": "united_kingdom",
        "英國": "united_kingdom",
        "法国": "france",
        "法國": "france",
        "澳大利亚": "australia",
        "澳大利亞": "australia",
        "澳洲": "australia",
        "德国": "germany",
        "德國": "germany",
        "阿联酋": "united_arab_emirates",
        "阿聯酋": "united_arab_emirates",
        "沙特阿拉伯": "saudi_arabia",
        "沙特": "saudi_arabia",
        "卡塔尔": "qatar",
        "卡塔爾": "qatar",
        "巴林": "bahrain",
    }
    if text in aliases:
        return aliases[text]
    machine = re.sub(r"[^a-z]+", "_", text.casefold()).strip("_")
    english = {
        "japan": "japan",
        "jp": "japan",
        "jpn": "japan",
        "hong_kong": "hong_kong",
        "hk": "hong_kong",
        "hkg": "hong_kong",
        "united_states": "united_states",
        "us": "united_states",
        "usa": "united_states",
        "united_kingdom": "united_kingdom",
        "gb": "united_kingdom",
        "gbr": "united_kingdom",
        "uk": "united_kingdom",
        "france": "france",
        "fr": "france",
        "fra": "france",
        "australia": "australia",
        "au": "australia",
        "aus": "australia",
        "germany": "germany",
        "de": "germany",
        "deu": "germany",
        "united_arab_emirates": "united_arab_emirates",
        "ae": "united_arab_emirates",
        "are": "united_arab_emirates",
        "uae": "united_arab_emirates",
        "saudi_arabia": "saudi_arabia",
        "sa": "saudi_arabia",
        "sau": "saudi_arabia",
        "qatar": "qatar",
        "qa": "qatar",
        "qat": "qatar",
        "bahrain": "bahrain",
        "bh": "bahrain",
        "bhr": "bahrain",
    }
    return english.get(machine, "")


def region_for_country_fact(country: Any) -> str:
    canonical = normalize_country_fact(country)
    if canonical in MIDDLE_EAST_COUNTRIES:
        return "middle_east"
    return canonical if canonical in TARGET_REGIONS else ""


def normalize_grade(value: Any) -> str:
    text = normalize_space(value).upper()
    for source, target in (
        ("Ⅲ", "3"),
        ("Ⅱ", "2"),
        ("Ⅰ", "1"),
        ("III", "3"),
        ("II", "2"),
        ("I", "1"),
    ):
        text = text.replace(source, target)
    text = text.replace("・", "-").replace("—", "-").replace("–", "-")
    text = re.sub(r"\bGRADE\s*", "G", text)
    text = re.sub(r"\bGROUP\s*", "G", text)
    text = re.sub(r"\s+", "", text)
    match = re.search(r"JPN-?([123])", text)
    if match:
        return f"JPN{match.group(1)}"
    match = re.search(r"J-?G([123])", text)
    if match:
        return f"J-G{match.group(1)}"
    match = re.search(r"(?:^|[^A-Z])G([123])(?:$|[^0-9])", text)
    if match:
        return f"G{match.group(1)}"
    return text


def grade_is_in_scope(region: str, grade: Any) -> bool:
    normalized = normalize_grade(grade)
    return normalized in (JAPAN_GRADES if region == "japan" else STANDARD_GRADES)


def validate_request_url(
    url: Any,
    *,
    allow_horse_search_query: bool = False,
    expected_scheme: str | None = None,
) -> str:
    parsed = urlparse(normalize_space(url))
    scheme = parsed.scheme.casefold()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError("URL scheme is not allowed")
    if expected_scheme is not None and scheme != expected_scheme.casefold():
        raise ValueError("URL scheme drift")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("URL credentials or port are not allowed")
    if (parsed.hostname or "").casefold() not in ALLOWED_HOSTS:
        raise ValueError("URL host is not allowed")
    if parsed.fragment:
        raise ValueError("canonical URL must not contain fragment")
    path = re.sub(r"/+", "/", parsed.path or "/")
    if (
        "%" in path
        or "/../" in f"{path}/"
        or "/./" in f"{path}/"
    ):
        raise ValueError("URL path is not canonical")
    canonical = urlunparse(
        (scheme, parsed.netloc.casefold(), path, "", "", "")
    )
    if not parsed.query:
        return canonical
    if not allow_horse_search_query or path != "/horses/":
        raise ValueError("canonical URL query is not allowed")
    raw_parts = parsed.query.split("&")
    if any("%" in part.partition("=")[0] for part in raw_parts):
        raise ValueError("encoded query parameter name is not allowed")
    try:
        pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=2,
        )
    except ValueError as exc:
        raise ValueError("horse search query is invalid") from exc
    if not 1 <= len(pairs) <= 2:
        raise ValueError("horse search query field count is invalid")
    if pairs[0][0] != "q" or sum(key == "q" for key, _ in pairs) != 1:
        raise ValueError("horse search query requires one q field")
    if any(key not in {"q", "page"} for key, _ in pairs):
        raise ValueError("horse search query field is not allowed")
    query = pairs[0][1]
    if not query or query != normalize_space(query):
        raise ValueError("horse search q value is invalid")
    page_values = [value for key, value in pairs if key == "page"]
    if len(page_values) > 1:
        raise ValueError("horse search page field is duplicated")
    normalized_pairs = [("q", query)]
    if page_values:
        page = page_values[0]
        if not re.fullmatch(r"[1-9]\d{0,2}", page) or int(page) > 100:
            raise ValueError("horse search page is outside allowed range")
        normalized_pairs.append(("page", page))
    return f"{canonical}?{urlencode(normalized_pairs)}"


def validate_race_url(
    url: Any, year: int, *, expected_scheme: str | None = None
) -> str:
    canonical = validate_request_url(url, expected_scheme=expected_scheme)
    if not urlparse(canonical).path.endswith("/"):
        parsed = urlparse(canonical)
        canonical = urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path + "/", "", "", "")
        )
    if not re.match(rf"^/races/{year}/[^/]+/$", urlparse(canonical).path):
        raise ValueError("race URL is outside exact year")
    return canonical


def validate_profile_url(
    url: Any, *, expected_scheme: str | None = None
) -> str:
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("profile URL must be one unmodified non-empty string")
    if any(
        character.isspace()
        or unicodedata.category(character).startswith("C")
        for character in url
    ):
        raise ValueError("profile URL contains whitespace or control characters")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("profile URL structure is invalid") from exc
    raw_path = parsed.path
    if (
        not raw_path.isascii()
        or not re.fullmatch(r"/horses/[1-9][0-9]*/?", raw_path)
    ):
        raise ValueError("profile URL is not an exact positive integer horse path")
    scheme = parsed.scheme.casefold()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError("profile URL scheme is not allowed")
    if expected_scheme is not None and scheme != expected_scheme.casefold():
        raise ValueError("profile URL scheme drift")
    if parsed.username or parsed.password or port is not None:
        raise ValueError("profile URL credentials or port are not allowed")
    host = (parsed.hostname or "").casefold()
    if host not in ALLOWED_HOSTS:
        raise ValueError("profile URL host is not allowed")
    if parsed.query or parsed.fragment:
        raise ValueError("profile URL query or fragment is not allowed")
    path = raw_path
    if not path.endswith("/"):
        path += "/"
    return urlunparse((scheme, host, path, "", "", ""))


def optional_profile_url(value: Any) -> str:
    if value is None or value == "":
        return ""
    return validate_profile_url(value)


def resolve_profile_href(href: Any, *, base_url: str) -> str:
    if not isinstance(href, str):
        raise ValueError("profile href must be one raw string")
    base = urlsplit(validate_request_url(base_url))
    if re.fullmatch(r"/horses/[1-9][0-9]*/?", href):
        return validate_profile_url(
            urlunparse((base.scheme, base.netloc, href, "", "", "")),
            expected_scheme=base.scheme,
        )
    profile_url = validate_profile_url(href, expected_scheme=base.scheme)
    if urlsplit(profile_url).hostname != base.hostname:
        raise ValueError("absolute profile href host drift")
    return profile_url


def stable_shard(key: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % shard_count


def final_filenames(year: int) -> tuple[str, ...]:
    return (
        f"race_participants_{year}.csv",
        f"horse_names_{year}.csv",
        f"horse_name_review_queue_{year}.csv",
        "source_manifest.jsonl",
        "summary.json",
        "errors.json",
        "README.md",
    )


def _manifest_entry_map(manifest: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not manifest:
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for item in manifest.get("races", []):
        url = str(item["url"])
        if url in entries:
            raise ValueError("region manifest duplicate URL")
        entries[url] = dict(item)
    return entries


def validate_region_manifest(
    manifest: Mapping[str, Any],
    *,
    year: int,
    expected_scheme: str | None = None,
) -> dict[str, Any]:
    if manifest.get("schema_version") != 1:
        raise ValueError("region manifest schema drift")
    if manifest.get("year") != year:
        raise ValueError("region manifest year drift")
    if not isinstance(manifest.get("classification_complete"), bool):
        raise ValueError("region manifest classification flag is invalid")
    raw_entries = manifest.get("races")
    if not isinstance(raw_entries, list):
        raise ValueError("region manifest races must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("region manifest race entry is invalid")
        url = validate_race_url(
            raw.get("url"), year, expected_scheme=expected_scheme
        )
        if url in seen:
            raise ValueError("region manifest duplicate URL")
        seen.add(url)
        region = normalize_space(raw.get("region"))
        country = normalize_space(raw.get("country"))
        evidence = normalize_space(raw.get("evidence"))
        if region not in MANIFEST_REGIONS:
            raise ValueError("region manifest region is invalid")
        if not evidence:
            raise ValueError("region manifest evidence is required")
        if region == "middle_east" and country not in MIDDLE_EAST_COUNTRIES:
            raise ValueError("region manifest middle east country is invalid")
        if region == "australia" and country != "australia":
            raise ValueError("region manifest australia country is invalid")
        if region == "germany" and country != "germany":
            raise ValueError("region manifest germany country is invalid")
        if region == "out_of_scope" and not country:
            raise ValueError("out-of-scope country evidence is required")
        normalized.append(
            {
                "url": url,
                "region": region,
                "country": country,
                "evidence": evidence,
            }
        )
    return {
        "schema_version": 1,
        "year": year,
        "classification_complete": manifest["classification_complete"],
        "races": sorted(normalized, key=lambda item: item["url"]),
    }


def load_region_manifest(
    path: str | Path,
    *,
    year: int,
    worktree_root: str | Path,
    expected_scheme: str | None = None,
) -> dict[str, Any]:
    candidate = Path(path)
    root = Path(worktree_root).resolve(strict=True)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative_parts = candidate.absolute().relative_to(root).parts
    except ValueError:
        relative_parts = ()
    cursor = root
    for part in relative_parts[:-1]:
        cursor = cursor / part
        try:
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError("region manifest symlink path is not allowed")
        except FileNotFoundError as exc:
            raise ValueError("region manifest path does not exist") from exc
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as exc:
        raise ValueError("region manifest file does not exist") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("region manifest symlink is not allowed")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("region manifest must be a regular file")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("region manifest must remain inside worktree") from exc
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("region manifest JSON is invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("region manifest root must be an object")
    return validate_region_manifest(
        raw, year=year, expected_scheme=expected_scheme
    )


def classify_other_coverage(
    *,
    year: int,
    discovered_other_urls: Iterable[str],
    manifest: Mapping[str, Any] | None,
    in_scope_urls: Iterable[str] = (),
) -> dict[str, Any]:
    raw_discovered = list(discovered_other_urls)
    raw_in_scope = list(in_scope_urls)
    schemes = {
        urlparse(validate_race_url(url, year)).scheme
        for url in [*raw_discovered, *raw_in_scope]
    }
    if len(schemes) > 1:
        raise ValueError("coverage URL scheme drift")
    expected_scheme = next(iter(schemes), None)
    discovered = {
        validate_race_url(url, year, expected_scheme=expected_scheme)
        for url in raw_discovered
    }
    evidenced_in_scope = {
        validate_race_url(url, year, expected_scheme=expected_scheme)
        for url in raw_in_scope
    }
    if not evidenced_in_scope <= discovered:
        raise ValueError("in-scope evidence URL was not discovered")
    normalized = (
        validate_region_manifest(
            manifest, year=year, expected_scheme=expected_scheme
        )
        if manifest is not None
        else {
            "schema_version": 1,
            "year": year,
            "classification_complete": False,
            "races": [],
        }
    )
    entries = _manifest_entry_map(normalized)
    manifest_urls = set(entries)
    classified = discovered & manifest_urls
    missing = discovered - manifest_urls
    extra = manifest_urls - discovered
    if normalized["classification_complete"] and (missing or extra):
        raise ValueError(
            "region manifest exact URL coverage mismatch "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    out_of_scope = {url for url in classified if entries[url]["region"] == "out_of_scope"}
    in_scope = (classified - out_of_scope) & evidenced_in_scope
    complete = bool(normalized["classification_complete"])
    regional_coverage = {
        region: (
            "classification_incomplete"
            if not complete
            else "covered"
            if any(entries[url]["region"] == region for url in in_scope)
            else "no_public_in_scope_races"
        )
        for region in ("australia", "germany", "middle_east")
    }
    return {
        "coverage_status": (
            "classification_incomplete"
            if not complete
            else "covered"
            if in_scope
            else "no_public_in_scope_races"
        ),
        "discovered_other_urls": len(discovered),
        "classified_other_urls": len(classified),
        "unclassified_other_urls": len(missing),
        "out_of_scope_other_urls": len(out_of_scope),
        "other_url_digest": keys_sha256(discovered),
        "classified_other_url_digest": keys_sha256(classified),
        "unclassified_other_url_digest": keys_sha256(missing),
        "coverage_by_region": regional_coverage,
    }


def normalize_participant_status(raw_status: Any) -> tuple[str, int | None]:
    raw = normalize_space(raw_status)
    match = POSITION_RE.fullmatch(raw)
    if match:
        position = int(match.group(1))
        if position < 1:
            return "unresolved", None
        return "finished", position
    key = raw.upper()
    if key in NON_FINISH_STATUSES:
        return NON_FINISH_STATUSES[key], None
    if raw in NON_FINISH_STATUSES:
        return NON_FINISH_STATUSES[raw], None
    if key in NON_STARTER_STATUSES or raw in NON_STARTER_STATUSES:
        return "non_starter", None
    if raw in PUBLIC_FINISHED_STATUSES:
        return "finished", None
    return "unresolved", None


def parse_result_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    occurrences: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    seen_exact: set[bytes] = set()
    identity_by_number: dict[str, str] = {}
    duplicate_rows = 0
    result_rows_with_horse = 0
    for raw_row in rows:
        row = {str(key): value for key, value in raw_row.items()}
        name = normalize_space(row.get("horse_display_name"))
        if not name:
            continue
        result_rows_with_horse += 1
        row["horse_display_name"] = name
        row["horse_number"] = normalize_space(row.get("horse_number"))
        row["raw_finish_status"] = normalize_space(row.get("raw_finish_status"))
        profile_url = optional_profile_url(row.get("profile_url"))
        row["profile_url"] = profile_url
        number = row["horse_number"]
        identity = normalize_identity(name)
        if number and number in identity_by_number and identity_by_number[number] != identity:
            raise ValueError(f"horse number identity conflict: {number}")
        if number:
            identity_by_number[number] = identity
        encoded = canonical_json_bytes(row)
        if encoded in seen_exact:
            duplicate_rows += 1
            result_rows_with_horse -= 1
            continue
        seen_exact.add(encoded)
        status, position = normalize_participant_status(row["raw_finish_status"])
        row["participant_status"] = status
        row["normalized_finish_position"] = position
        if status == "non_starter":
            excluded_rows.append(row)
        elif status == "unresolved":
            unresolved_rows.append(row)
        else:
            occurrences.append(row)
    if result_rows_with_horse != (
        len(occurrences) + len(excluded_rows) + len(unresolved_rows)
    ):
        raise ValueError("participant conservation invariant failed")
    return {
        "occurrences": occurrences,
        "unresolved_rows": unresolved_rows,
        "excluded_rows": excluded_rows,
        "result_rows_with_horse": result_rows_with_horse,
        "non_starters_excluded": len(excluded_rows),
        "participant_status_unresolved": len(unresolved_rows),
        "duplicate_result_rows": duplicate_rows,
    }


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list["_HtmlNode"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self) -> str:
        values = [*self.text_parts]
        for child in self.children:
            values.append(child.text())
        return normalize_space(" ".join(values))

    def descendants(self, *, tag: str | None = None) -> Iterable["_HtmlNode"]:
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag=tag)

    def has_class(self, class_name: str) -> bool:
        return class_name in self.attrs.get("class", "").split()

    def first(
        self,
        *,
        tag: str | None = None,
        node_id: str | None = None,
        class_name: str | None = None,
    ) -> "_HtmlNode | None":
        for node in self.descendants(tag=tag):
            if node_id is not None and node.attrs.get("id") != node_id:
                continue
            if class_name is not None and not node.has_class(class_name):
                continue
            return node
        return None


class _TreeParser(HTMLParser):
    VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("document", {})
        self.stack = [self.root]

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        node = _HtmlNode(tag.casefold(), {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.casefold() not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag.casefold():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        wanted = tag.casefold()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == wanted:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].text_parts.append(data)


def _parse_html(body: bytes) -> _HtmlNode:
    parser = _TreeParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return parser.root


def _metadata_grid(root: _HtmlNode) -> dict[str, str]:
    result: dict[str, str] = {}
    overview = root.first(node_id="overview")
    grid = overview.first(class_name="race-meta-grid") if overview else None
    for item in (grid.children if grid else []):
        if item.tag != "div":
            continue
        label = item.first(tag="span")
        value = item.first(tag="b")
        if label and value:
            result[label.text()] = value.text()
    return result


def _all_metadata_grids(root: _HtmlNode) -> dict[str, str]:
    result: dict[str, str] = {}
    for grid in root.descendants():
        if not grid.has_class("race-meta-grid"):
            continue
        for item in grid.children:
            if item.tag != "div":
                continue
            label = item.first(tag="span")
            value = item.first(tag="b")
            if label and value:
                result[label.text()] = value.text()
    return result


def _table_header_indexes(table: _HtmlNode) -> dict[str, int]:
    aliases = {
        "raw_finish_status": {"着顺", "名次", "順位", "结果", "結果"},
        "horse_number": {"马号", "馬番", "馬號", "编号", "番"},
        "horse_display_name": {"马名", "馬名", "赛马", "賽馬"},
        "jockey_name": {"骑师", "騎手", "騎師"},
        "trainer_name": {"练马师", "調教師", "練馬師"},
        "finish_time": {"时间", "タイム", "時間"},
        "margin": {"差距", "着差"},
    }
    indexes: dict[str, int] = {}
    thead = table.first(tag="thead")
    for index, header in enumerate(thead.descendants(tag="th") if thead else []):
        text = header.text()
        for key, names in aliases.items():
            if text in names:
                indexes[key] = index
    return indexes


def parse_race_html(
    html: bytes | str,
    *,
    url: str,
    year: int,
    fetched_at: str | None = None,
    region_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_url = validate_race_url(url, year)
    body = html.encode("utf-8") if isinstance(html, str) else bytes(html)
    root = _parse_html(body)
    main = root.first(tag="main", class_name="race-page")
    if main is None:
        raise ValueError("public race page marker missing")
    metadata = _metadata_grid(root)
    meta_node = root.first(class_name="race-hero-meta-text")
    meta_text = meta_node.text() if meta_node else ""
    region_label = meta_text.split("·", 1)[0].strip()
    region, country = normalize_region_label(region_label)
    manifest_entries = _manifest_entry_map(
        validate_region_manifest(
            region_manifest,
            year=year,
            expected_scheme=urlparse(canonical_url).scheme,
        )
        if region_manifest is not None
        else None
    )
    override = manifest_entries.get(canonical_url)
    if region_label == "其他":
        if override:
            region = override["region"]
            country = override["country"]
        else:
            region = ""
            country = None
    elif override:
        if override["region"] != region:
            raise ValueError("page region conflicts with region manifest")
        if region == "middle_east" and (
            not country or override["country"] != country
        ):
            raise ValueError(
                "page middle east country conflicts with region manifest"
            )
    race_name_node = root.first(class_name="race-hero-name")
    race_name_zh = race_name_node.text() if race_name_node else ""
    original_node = root.first(class_name="race-hero-original")
    original_text = original_node.text() if original_node else ""
    date_match = DATE_RE.search(original_text)
    race_name_original = (
        original_text[: date_match.start()].strip(" ·") if date_match else original_text
    )
    grade_node = root.first(class_name="grade-badge")
    grade = normalize_grade(
        metadata.get("等级")
        or (grade_node.text() if grade_node else "")
    )
    race_date = normalize_space(metadata.get("日期"))
    status = normalize_space(metadata.get("状态"))
    source = {
        "url": canonical_url,
        "http_status": 200,
        "sha256": sha256_bytes(body),
        "region": region,
        "country": country,
        "region_label": region_label,
        "race_date": race_date,
        "race_name_zh": race_name_zh,
        "grade": grade,
        "status": status,
        "fetched_at": fetched_at or utc_now_iso(),
    }
    if region == "out_of_scope":
        return {"status": "skipped", "skip_reason": "out_of_scope", "rows": [], "source": source}
    if not region:
        return {
            "status": "skipped",
            "skip_reason": "region_unresolved",
            "rows": [],
            "source": source,
        }
    if status not in {"已结束", "已完赛"}:
        return {"status": "skipped", "skip_reason": "not_completed", "rows": [], "source": source}
    try:
        page_year = datetime.strptime(race_date, "%Y-%m-%d").year
    except ValueError as exc:
        raise ValueError("completed race has invalid date") from exc
    if page_year != year:
        raise ValueError("race page year conflicts with requested year")
    if not grade_is_in_scope(region, grade):
        return {"status": "skipped", "skip_reason": "grade_out_of_scope", "rows": [], "source": source}
    section = root.first(tag="section", node_id="results")
    if section is None:
        raise ValueError("completed in-scope race has no result section")
    live_status = root.first(
        tag="aside", class_name="race-result-status"
    )
    result_phase = ""
    if live_status is not None:
        phase_classes = [
            item.removeprefix("race-result-status-")
            for item in live_status.attrs.get("class", "").split()
            if item.startswith("race-result-status-")
            and item != "race-result-status-summary"
        ]
        if len(phase_classes) != 1:
            raise ValueError("live result phase is missing or ambiguous")
        result_phase = phase_classes[0]
        conflict_status = normalize_space(
            live_status.attrs.get("data-conflict-status")
        )
        live_status_text = normalize_space(live_status.text())
        pending_conflict = (
            conflict_status == "pending"
            or "赛果待复核" in live_status_text
            or "正在复核" in live_status_text
        )
        if result_phase == "provisional" or pending_conflict:
            source["result_phase"] = result_phase
            source["conflict_status"] = (
                "pending" if pending_conflict else conflict_status
            )
            source["status"] = "result_not_final"
            return {
                "status": "evidence_gap",
                "error_code": "result_not_final",
                "error": (
                    "pending result conflict is not formal participant evidence"
                    if pending_conflict
                    else "provisional result is not formal participant evidence"
                ),
                "rows": [],
                "source": source,
            }
        if result_phase not in {"official", "corrected"}:
            raise ValueError("live result phase is not a trusted final phase")
    else:
        heading = section.first(tag="h2")
        if heading is None or normalize_space(heading.text()) not in {
            "正式赛果",
            "已人工审核赛果",
        }:
            raise ValueError("non-live result phase is not explicitly final")
        result_phase = "static_final"
    source["result_phase"] = result_phase
    table = section.first(tag="table")
    if table is None:
        raise ValueError("completed in-scope race has no result table")
    indexes = _table_header_indexes(table)
    defaults = {
        "raw_finish_status": 0,
        "horse_number": 1,
        "horse_display_name": 2,
        "jockey_name": 3,
        "trainer_name": 4,
        "finish_time": 5,
        "margin": 6,
    }
    raw_rows: list[dict[str, Any]] = []
    tbody = table.first(tag="tbody")
    for tr in (tbody.descendants(tag="tr") if tbody else []):
        cells = list(tr.descendants(tag="td"))
        if not cells:
            continue
        def cell(field: str) -> Any:
            index = indexes.get(field, defaults[field])
            return cells[index] if index < len(cells) else None
        horse_cell = cell("horse_display_name")
        horse_name = horse_cell.text() if horse_cell else ""
        link = horse_cell.first(tag="a") if horse_cell else None
        profile_url = ""
        if link and link.attrs.get("href"):
            profile_url = resolve_profile_href(
                link.attrs["href"], base_url=canonical_url
            )
        raw_rows.append(
            {
                "raw_finish_status": normalize_space(
                    cell("raw_finish_status").text()
                    if cell("raw_finish_status")
                    else ""
                ),
                "horse_number": normalize_space(
                    cell("horse_number").text()
                    if cell("horse_number")
                    else ""
                ),
                "horse_display_name": horse_name,
                "profile_url": profile_url,
                "jockey_name": normalize_space(
                    cell("jockey_name").text()
                    if cell("jockey_name")
                    else ""
                ),
                "trainer_name": normalize_space(
                    cell("trainer_name").text()
                    if cell("trainer_name")
                    else ""
                ),
                "finish_time": normalize_space(
                    cell("finish_time").text()
                    if cell("finish_time")
                    else ""
                ),
                "margin": normalize_space(
                    cell("margin").text()
                    if cell("margin")
                    else ""
                ),
            }
        )
    parsed = parse_result_rows(raw_rows)
    shared = {
        "region": region,
        "region_label": REGION_OUTPUT[region],
        "country": country or region,
        "race_date": race_date,
        "race_name_zh": race_name_zh,
        "race_name_original": race_name_original,
        "grade": grade,
        "racecourse": normalize_space(metadata.get("马场")),
        "race_url": canonical_url,
        "race_page_sha256": source["sha256"],
    }
    occurrences = [{**shared, **row} for row in parsed["occurrences"]]
    unresolved_rows = [
        {**shared, **row} for row in parsed["unresolved_rows"]
    ]
    if not occurrences:
        if unresolved_rows:
            source["status"] = "participant_status_unresolved"
            return {
                "status": "evidence_gap",
                "error_code": "all_participant_status_unresolved",
                "error": (
                    "completed in-scope race has only unknown participant "
                    "statuses"
                ),
                "rows": [],
                "unresolved_rows": unresolved_rows,
                "source": source,
                **{
                    key: parsed[key]
                    for key in (
                        "result_rows_with_horse",
                        "non_starters_excluded",
                        "participant_status_unresolved",
                        "duplicate_result_rows",
                    )
                },
            }
        raise ValueError(
            "completed in-scope race has no proven actual participants"
        )
    return {
        "status": "success",
        "rows": occurrences,
        "unresolved_rows": unresolved_rows,
        "source": source,
        **{key: parsed[key] for key in (
            "result_rows_with_horse",
            "non_starters_excluded",
            "participant_status_unresolved",
            "duplicate_result_rows",
        )},
    }


def canonical_horse_key(occurrence: Mapping[str, Any]) -> str:
    profile_url = optional_profile_url(occurrence.get("profile_url"))
    if profile_url:
        return f"profile|{validate_profile_url(profile_url)}"
    region = normalize_space(occurrence.get("region"))
    country = normalize_space(occurrence.get("country"))
    name = (
        normalize_space(occurrence.get("original_name"))
        or normalize_space(occurrence.get("horse_display_name"))
    )
    return f"name|{region}|{country}|{normalize_identity(name)}"


def _candidate_name_fields(candidate: Mapping[str, Any]) -> dict[str, str]:
    display = normalize_space(candidate.get("display_name") or candidate.get("name_zh"))
    original = normalize_space(candidate.get("original_name"))
    explicit_zh = normalize_space(candidate.get("name_zh"))
    explicit_ja = normalize_space(candidate.get("name_ja"))
    explicit_en = normalize_space(candidate.get("name_en"))
    name_zh = explicit_zh or (
        display if HAN_RE.search(display) and not KANA_RE.search(display) else ""
    )
    name_ja = explicit_ja or (
        original
        if KANA_RE.search(original)
        else display
        if KANA_RE.search(display)
        else ""
    )
    name_en = explicit_en or (
        original
        if LATIN_RE.search(original) and not KANA_RE.search(original)
        else display
        if LATIN_RE.search(display)
        and not HAN_RE.search(display)
        and not KANA_RE.search(display)
        else ""
    )
    return {"name_zh": name_zh, "name_ja": name_ja, "name_en": name_en}


def resolve_other_profile(
    occurrence: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    expected_aliases = _profile_aliases(occurrence)
    exact = [
        dict(candidate)
        for candidate in candidates
        if expected_aliases & _profile_aliases(candidate)
    ]
    if not exact:
        return {"resolution_state": "not_found"}
    if len(exact) > 1:
        return {"resolution_state": "ambiguous", "candidate_count": len(exact)}
    candidate = exact[0]
    evidence_state = _profile_region_evidence_state(occurrence, candidate)
    if evidence_state != "resolved":
        return {
            "resolution_state": evidence_state,
            **({"candidate_count": 1} if evidence_state == "ambiguous" else {}),
        }
    profile_url = validate_profile_url(candidate.get("profile_url"))
    return {
        **candidate,
        **_candidate_name_fields(candidate),
        "profile_url": profile_url,
        "resolution_state": "resolved",
    }


def build_horse_name_record(
    occurrences: Sequence[Mapping[str, Any]], *, profile: Mapping[str, Any]
) -> dict[str, Any]:
    if not occurrences:
        raise ValueError("horse record requires at least one occurrence")
    horse_key = normalize_space(profile.get("horse_key")) or canonical_horse_key(
        occurrences[0]
    )
    regions = sorted({normalize_space(item.get("region")) for item in occurrences})
    countries = sorted({normalize_space(item.get("country")) for item in occurrences})
    names = _candidate_name_fields(profile)
    if not names["name_zh"]:
        for item in occurrences:
            candidate = normalize_space(item.get("horse_display_name"))
            if HAN_RE.search(candidate) and not KANA_RE.search(candidate):
                names["name_zh"] = candidate
                break
    if not names["name_ja"]:
        for item in occurrences:
            candidate = normalize_space(item.get("original_name"))
            if KANA_RE.search(candidate):
                names["name_ja"] = candidate
                break
    if not names["name_en"]:
        for item in occurrences:
            candidate = normalize_space(item.get("original_name"))
            if LATIN_RE.search(candidate) and not HAN_RE.search(candidate) and not KANA_RE.search(candidate):
                names["name_en"] = candidate
                break
    resolution = normalize_space(
        profile.get("resolution_state") or profile.get("profile_resolution_state")
    )
    if resolution not in {"resolved", "not_found", "unresolved", "ambiguous", "error"}:
        raise ValueError("invalid profile resolution state")
    english_required = bool(set(regions) & REQUIRED_ENGLISH_REGIONS)
    required_english_status = (
        "not_applicable"
        if not english_required
        else "complete"
        if names["name_en"]
        else "missing"
    )
    issues: set[str] = set()
    if not names["name_zh"]:
        issues.add("missing_chinese")
    if not names["name_ja"]:
        issues.add("missing_japanese")
    if required_english_status == "missing":
        issues.add("missing_required_english")
    if resolution != "resolved":
        issues.add(f"profile_{resolution}")
    profile_url = optional_profile_url(profile.get("profile_url"))
    race_urls = sorted(
        {normalize_space(item.get("race_url")) for item in occurrences if item.get("race_url")}
    )
    return {
        "horse_key": horse_key,
        "regions": "|".join(regions),
        "countries": "|".join(countries),
        "profile_url": profile_url,
        **names,
        "profile_resolution_state": resolution,
        "required_english_status": required_english_status,
        "name_completeness": (
            "complete"
            if names["name_zh"]
            and names["name_ja"]
            and required_english_status != "missing"
            else "partial"
        ),
        "name_issue_codes": sorted(issues),
        "occurrence_count": len(occurrences),
        "graded_race_count": len(race_urls),
        "race_urls": "|".join(race_urls),
    }


def merge_profile_records(
    records: Iterable[Mapping[str, Any]], expected_keys: Iterable[str]
) -> list[dict[str, Any]]:
    expected = set(map(str, expected_keys))
    by_lookup: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        profile_url = optional_profile_url(record.get("profile_url"))
        record["profile_url"] = profile_url
        key = normalize_space(record.get("key"))
        if not key:
            raise ValueError("profile record key is required")
        if key in by_lookup and canonical_json_bytes(by_lookup[key]) != canonical_json_bytes(record):
            raise ValueError(f"profile record conflict for {key}")
        by_lookup[key] = record
    if set(by_lookup) != expected:
        raise ValueError(
            "profile shard coverage mismatch "
            f"missing={sorted(expected - set(by_lookup))} extra={sorted(set(by_lookup) - expected)}"
        )
    canonical_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key in sorted(by_lookup):
        record = by_lookup[key]
        profile_url = optional_profile_url(record.get("profile_url"))
        canonical = f"profile|{validate_profile_url(profile_url)}" if profile_url else key
        canonical_groups[canonical].append(record)
    merged: list[dict[str, Any]] = []
    for canonical in sorted(canonical_groups):
        members = canonical_groups[canonical]
        states = {normalize_space(item.get("resolution_state")) for item in members}
        profiles = {
            profile_url
            for item in members
            if (profile_url := optional_profile_url(item.get("profile_url")))
        }
        if len(profiles) > 1:
            raise ValueError(f"profile URL conflict for {canonical}")
        rank = {"error": 5, "ambiguous": 4, "unresolved": 3, "not_found": 2, "resolved": 1}
        state = max(states, key=lambda item: rank.get(item, 99))
        if state not in rank:
            raise ValueError("invalid profile resolution state")
        values: dict[str, set[str]] = defaultdict(set)
        for item in members:
            for field in ("name_zh", "name_ja", "name_en", "original_name", "birth_year", "country"):
                value = normalize_space(item.get(field))
                if value:
                    values[field].add(value)
        for field in (
            "name_zh",
            "name_ja",
            "name_en",
            "original_name",
            "birth_year",
            "country",
        ):
            if len(values[field]) > 1:
                raise ValueError(f"profile identity conflict for {canonical}: {field}")
        merged.append(
            {
                "key": canonical,
                "lookup_keys": sorted(item["key"] for item in members),
                "profile_url": next(iter(profiles), ""),
                "resolution_state": state,
                **{field: next(iter(sorted(values[field])), "") for field in (
                    "name_zh",
                    "name_ja",
                    "name_en",
                    "original_name",
                    "birth_year",
                    "country",
                )},
                "status": (
                    "retryable_error"
                    if state == "error"
                    else "not_found"
                    if state == "not_found"
                    else "success"
                ),
            }
        )
    return merged


def validate_resume_identity(saved: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    fields = (
        "year",
        "region_manifest_sha256",
        "manifest_sha256",
        "tool_sha256",
        "checkpoint_sha256",
    )
    for field in fields:
        if saved.get(field) != current.get(field):
            label = (
                "region manifest"
                if field == "region_manifest_sha256"
                else "run manifest"
                if field == "manifest_sha256"
                else field.replace("_sha256", "")
            )
            raise ValueError(f"{label} identity drift")


def current_base_commit() -> str:
    configured = os.environ.get("GITHUB_SHA", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def current_tool_identity_record() -> dict[str, Any]:
    source_sha = sha256_bytes(Path(__file__).read_bytes())
    tool_version = sha256_bytes(
        f"{source_sha}|{PARSER_VERSION}|{TOOL_POLICY_VERSION}|{SCHEMA_VERSION}".encode()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "policy_version": TOOL_POLICY_VERSION,
        "collector_source_sha256": source_sha,
        "tool_version": tool_version,
        "base_commit": current_base_commit(),
    }


class RequestLedger:
    """位于 stage artifact 内的 write-ahead 请求计数账本。"""

    def __init__(
        self,
        path: Path,
        *,
        identity: Mapping[str, Any],
        request_budget: int,
    ):
        if request_budget < 1:
            raise ValueError("request ledger budget must be positive")
        self.path = Path(path)
        self.identity = dict(identity)
        self.request_budget = request_budget

    def initialize(self, request_count: int) -> dict[str, Any]:
        if not 0 <= request_count <= self.request_budget:
            raise ValueError("request ledger initial count exceeds budget")
        if self.path.exists():
            current = self.verify()
            if current["request_count"] < request_count:
                raise ValueError("request ledger count rollback")
            return current
        payload = {
            **self.identity,
            "request_budget": self.request_budget,
            "request_count": request_count,
        }
        atomic_write_json(self.path, payload)
        return payload

    def verify(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("request ledger is missing or invalid") from exc
        for field, expected in self.identity.items():
            if payload.get(field) != expected:
                raise ValueError(f"request ledger identity drift: {field}")
        if payload.get("request_budget") != self.request_budget:
            raise ValueError("request ledger identity drift: request_budget")
        count = payload.get("request_count")
        if not isinstance(count, int) or not 0 <= count <= self.request_budget:
            raise ValueError("request ledger request count drift")
        return payload

    def reserve(self) -> int:
        current = self.verify()
        count = current["request_count"]
        if count >= self.request_budget:
            raise RequestBudgetExceeded(
                f"request budget exhausted before transport: "
                f"{count}/{self.request_budget}"
            )
        payload = {**current, "request_count": count + 1}
        atomic_write_json(self.path, payload)
        return count + 1


class StageStore:
    """原子 item/index/progress checkpoint，绑定运行和上游 identity。"""

    def __init__(
        self,
        root: Path,
        *,
        stage: str,
        year: int,
        shard_index: int | None = None,
        shard_count: int = 1,
        manifest_sha256: str = "unit-test",
        region_manifest_sha256: str = "none",
        upstream_indexes: Mapping[str, str] | None = None,
        input_keys_sha256: str = "",
        request_budget: int = 0,
        tool_identity: Mapping[str, Any] | None = None,
    ):
        if stage not in STAGES and stage != "profiles_merged":
            raise ValueError("invalid checkpoint stage")
        self.root = Path(root)
        self.stage = stage
        self.year = validate_year(year)
        self.shard_index = shard_index
        self.shard_count = shard_count
        self.manifest_sha256 = manifest_sha256
        self.region_manifest_sha256 = region_manifest_sha256
        self.upstream_indexes = dict(sorted((upstream_indexes or {}).items()))
        self.input_keys_sha256 = input_keys_sha256
        if request_budget < 0:
            raise ValueError("request budget must not be negative")
        self.request_budget = request_budget
        self.tool_identity = dict(tool_identity or current_tool_identity_record())
        base = self.root / "stages"
        if stage == "profiles_merged":
            base = base / "profiles" / "merged"
        else:
            base = base / stage
        if shard_index is not None:
            base = base / "shards" / str(shard_index)
        self.path = base
        self.items_dir = base / "items"
        self.index_path = base / "index.json"
        self.progress_path = base / "progress.json"
        self.request_ledger_path = base / "request_ledger.json"

    @staticmethod
    def filename(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"

    def item_path(self, key: str) -> Path:
        return self.items_dir / self.filename(key)

    def load_item(self, key: str) -> dict[str, Any] | None:
        path = self.item_path(key)
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("key") != key:
            raise ValueError(f"checkpoint key mismatch for {key}")
        return value

    def save_item(self, key: str, value: Mapping[str, Any]) -> None:
        payload = dict(value)
        if payload.get("key", key) != key:
            raise ValueError(f"checkpoint key mismatch for {key}")
        payload["key"] = key
        atomic_write_json(self.item_path(key), payload)

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "year": self.year,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "manifest_sha256": self.manifest_sha256,
            "region_manifest_sha256": self.region_manifest_sha256,
            "upstream_indexes": self.upstream_indexes,
            "input_keys_sha256": self.input_keys_sha256,
            "request_budget": self.request_budget,
            "tool_identity": self.tool_identity,
        }

    def request_ledger(self) -> RequestLedger:
        if self.request_budget < 1:
            raise ValueError("stage has no request budget")
        identity = {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "year": self.year,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "manifest_sha256": self.manifest_sha256,
            "region_manifest_sha256": self.region_manifest_sha256,
            "tool_identity": self.tool_identity,
        }
        return RequestLedger(
            self.request_ledger_path,
            identity=identity,
            request_budget=self.request_budget,
        )

    def rebuild_index(self, *, request_count: int | None = None) -> dict[str, Any]:
        prior_requests = 0
        if self.index_path.exists():
            prior_requests = int(
                json.loads(self.index_path.read_text(encoding="utf-8")).get(
                    "request_count", 0
                )
            )
        entries: list[dict[str, Any]] = []
        if self.items_dir.exists():
            for path in sorted(self.items_dir.glob("*.json")):
                payload = path.read_bytes()
                item = json.loads(payload)
                key = normalize_space(item.get("key"))
                if not key or path.name != self.filename(key):
                    raise ValueError("invalid checkpoint item")
                entries.append(
                    {
                        "key": key,
                        "path": path.relative_to(self.root).as_posix(),
                        "status": normalize_space(item.get("status")),
                        "sha256": sha256_bytes(payload),
                    }
                )
        entries.sort(key=lambda item: item["key"])
        if not self.input_keys_sha256:
            self.input_keys_sha256 = keys_sha256(item["key"] for item in entries)
        effective_request_count = (
            prior_requests if request_count is None else request_count
        )
        if (
            not isinstance(effective_request_count, int)
            or effective_request_count < 0
            or (
                self.request_budget
                and effective_request_count > self.request_budget
            )
        ):
            raise ValueError("stage request count exceeds request budget")
        index = {
            **self._identity(),
            "request_count": effective_request_count,
            "items": entries,
            "items_sha256": sha256_bytes(canonical_json_bytes(entries)),
        }
        atomic_write_json(self.index_path, index)
        return index

    def verify_index(self) -> dict[str, Any]:
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("stage checkpoint index is missing or invalid") from exc
        for field, expected in self._identity().items():
            if index.get(field) != expected:
                raise ValueError(f"stage {field} drift")
        entries = index.get("items")
        if not isinstance(entries, list) or entries != sorted(
            entries, key=lambda item: item["key"]
        ):
            raise ValueError("stage index ordering drift")
        if sha256_bytes(canonical_json_bytes(entries)) != index.get("items_sha256"):
            raise ValueError("stage index summary drift")
        seen: set[str] = set()
        for entry in entries:
            key = str(entry["key"])
            if key in seen:
                raise ValueError("stage index duplicate key")
            seen.add(key)
            path = self.root / entry["path"]
            if path != self.item_path(key):
                raise ValueError("checkpoint path drift")
            payload = path.read_bytes()
            if sha256_bytes(payload) != entry["sha256"]:
                raise ValueError("checkpoint content drift")
            item = json.loads(payload)
            if item.get("key") != key or item.get("status", "") != entry["status"]:
                raise ValueError("checkpoint item identity drift")
        if not isinstance(index.get("request_count"), int) or index["request_count"] < 0:
            raise ValueError("stage request count drift")
        if self.request_budget and index["request_count"] > self.request_budget:
            raise ValueError("stage request count exceeds request budget")
        return index


def _validated_progress_relation(
    store: StageStore, index: Mapping[str, Any]
) -> dict[str, Any] | None:
    """校验派生 progress 没有声称超越或矛盾于权威 index。"""
    if not store.progress_path.exists():
        return None
    try:
        progress = json.loads(store.progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    index_sha = sha256_bytes(store.index_path.read_bytes())
    processed = progress.get("processed")
    request_count = progress.get("request_count")
    status_counts = Counter(item["status"] for item in index["items"])
    expected_success = status_counts["success"]
    expected_failed = sum(
        status_counts[status]
        for status in RETRYABLE_ITEM_STATUSES
        | {"permanent_error", "evidence_gap"}
    )
    if progress.get("index_sha256") == index_sha:
        if request_count != index["request_count"]:
            raise ValueError("stage request count index/progress mismatch")
        if (
            progress.get("stage", store.stage) != store.stage
            or processed != len(index["items"])
            or progress.get("success", expected_success) != expected_success
            or progress.get("failed", expected_failed) != expected_failed
        ):
            raise ValueError("stage progress coverage drift")
        return progress
    success = progress.get("success")
    failed = progress.get("failed")
    total = progress.get("total")
    is_strictly_behind = (
        progress.get("stage") == store.stage
        and progress.get("safe_stopped") is True
        and isinstance(processed, int)
        and isinstance(request_count, int)
        and isinstance(success, int)
        and isinstance(failed, int)
        and isinstance(total, int)
        and 0 <= processed <= len(index["items"])
        and 0 <= request_count <= index["request_count"]
        and 0 <= success <= processed
        and 0 <= failed <= processed
        and success + failed <= processed
        and total >= processed
        and (
            processed < len(index["items"])
            or request_count < index["request_count"]
        )
    )
    if not is_strictly_behind:
        raise ValueError("stage progress index drift")
    return progress


def _stage_progress(
    store: StageStore,
    index: Mapping[str, Any],
    *,
    total: int,
    safe_stopped: bool,
    updated_at: str,
    elapsed_seconds: float,
) -> dict[str, Any]:
    status_counts = Counter(item["status"] for item in index["items"])
    return {
        "stage": store.stage,
        "processed": len(index["items"]),
        "total": total,
        "success": status_counts["success"],
        "failed": sum(
            status_counts[status]
            for status in RETRYABLE_ITEM_STATUSES
            | {"permanent_error", "evidence_gap"}
        ),
        "updated_at": updated_at,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "safe_stopped": safe_stopped,
        "index_sha256": sha256_bytes(store.index_path.read_bytes()),
        "request_count": index["request_count"],
    }


def trusted_stage_request_count(store: StageStore) -> int:
    """从完整校验的权威 index 与请求 ledger 恢复累计请求数。"""
    ledger_count = 0
    if store.request_budget:
        ledger = store.request_ledger()
        if ledger.path.exists():
            ledger_count = ledger.verify()["request_count"]
        elif store.index_path.exists() or store.progress_path.exists():
            raise ValueError("stage request ledger is missing")
        else:
            ledger.initialize(0)
    if not store.index_path.exists():
        if store.progress_path.exists():
            raise ValueError("stage request count has progress without index")
        return ledger_count
    index = store.verify_index()
    _validated_progress_relation(store, index)
    if store.request_budget and ledger_count < index["request_count"]:
        raise ValueError("stage request ledger count rollback")
    return ledger_count if store.request_budget else index["request_count"]


def run_checkpointed_items(
    keys: Iterable[str],
    *,
    store: StageStore,
    process: Callable[[str], Mapping[str, Any]],
    resume: bool,
    time_budget_seconds: float = 0,
    checkpoint_every: int = 25,
    request_counter: Callable[[], int] | None = None,
    request_counter_start: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = utc_now_iso,
    deadline: StageDeadline | None = None,
) -> dict[str, Any]:
    all_keys = sorted(set(map(str, keys)))
    planned = [
        key
        for key in all_keys
        if stable_shard(key, store.shard_count) == (store.shard_index or 0)
    ]
    digest = keys_sha256(planned)
    if store.input_keys_sha256 and store.input_keys_sha256 != digest:
        raise ValueError("stage input key drift")
    store.input_keys_sha256 = digest
    prior_requests = trusted_stage_request_count(store)
    indexed_keys: set[str] = set()
    if store.index_path.exists():
        prior = store.verify_index()
        indexed_keys = {item["key"] for item in prior["items"]}
        if not indexed_keys <= set(planned):
            raise ValueError("stage checkpoint coverage drift")
        progress = _validated_progress_relation(store, prior)
        checkpoint_complete = (
            prior_requests == prior["request_count"]
            and indexed_keys == set(planned)
            and all(
                item.get("status") in TERMINAL_ITEM_STATUSES
                for item in prior.get("items", [])
            )
        )
        current_index_sha = sha256_bytes(store.index_path.read_bytes())
        if (
            progress is not None
            and progress.get("index_sha256") == current_index_sha
            and progress.get("safe_stopped") is False
            and checkpoint_complete
        ):
            if progress.get("total") != len(planned):
                raise ValueError("stage progress total drift")
            return progress
        if resume and (
            progress is None
            or progress.get("index_sha256") != current_index_sha
        ):
            progress = _stage_progress(
                store,
                prior,
                total=len(planned),
                safe_stopped=not checkpoint_complete,
                updated_at=now(),
                elapsed_seconds=0,
            )
            atomic_write_json(store.progress_path, progress)
            if checkpoint_complete:
                return progress
    elif resume and store.progress_path.exists():
        raise ValueError("stage index is missing for resume")
    started = clock()
    request_start = (
        request_counter_start
        if request_counter_start is not None
        else request_counter()
        if request_counter
        else 0
    )
    if request_counter and request_start != prior_requests:
        raise ValueError("request counter does not match trusted checkpoint count")
    safe_stopped = False
    processed_since_start = 0
    for key in planned:
        if deadline is not None:
            try:
                deadline.check()
            except StageDeadlineExceeded:
                safe_stopped = True
                break
        if time_budget_seconds and clock() - started >= time_budget_seconds:
            safe_stopped = True
            break
        existing = store.load_item(key)
        if resume and existing and existing.get("status") in TERMINAL_ITEM_STATUSES:
            continue
        try:
            value = dict(process(key))
            value.setdefault("status", "success")
        except RequestBudgetExceeded:
            safe_stopped = True
            break
        except Exception as exc:
            value = {
                "key": key,
                "status": "retryable_error",
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
        store.save_item(key, value)
        processed_since_start += 1
        if processed_since_start % max(1, checkpoint_every) == 0:
            store.rebuild_index(
                request_count=prior_requests
                + (request_counter() - request_start if request_counter else 0)
            )
    index = store.rebuild_index(
        request_count=prior_requests
        + (request_counter() - request_start if request_counter else 0)
    )
    indexed_keys = {item["key"] for item in index["items"]}
    status_counts = Counter(item["status"] for item in index["items"])
    safe_stopped = (
        safe_stopped
        or indexed_keys != set(planned)
        or any(
            status_counts[status] > 0 for status in RETRYABLE_ITEM_STATUSES
        )
    )
    progress = _stage_progress(
        store,
        index,
        total=len(planned),
        safe_stopped=safe_stopped,
        updated_at=now(),
        elapsed_seconds=clock() - started,
    )
    atomic_write_json(store.progress_path, progress)
    return progress


def load_store_records(store: StageStore) -> list[dict[str, Any]]:
    index = store.verify_index()
    return [
        json.loads((store.root / item["path"]).read_text(encoding="utf-8"))
        for item in index["items"]
    ]


def index_sha256(store: StageStore) -> str:
    store.verify_index()
    return sha256_bytes(store.index_path.read_bytes())


def write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None = None
) -> None:
    fields = list(fieldnames or (list(rows[0]) if rows else []))
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    if fields:
        writer.writeheader()
        for raw in rows:
            row = dict(raw)
            for key, value in row.items():
                if isinstance(value, (list, dict)):
                    row[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + handle.getvalue().encode("utf-8"))


def coverage_by_region(
    *,
    occurrences: Sequence[Mapping[str, Any]],
    other_coverage: Mapping[str, Any],
    errors: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    present = {str(row.get("region")) for row in occurrences}
    coverage_errors = [
        item
        for item in errors
        if normalize_space(item.get("stage"))
        in {"discovery", "races", "race_page", "result_row"}
    ]
    global_coverage_error = any(
        normalize_space(item.get("stage")) == "discovery"
        or normalize_space(item.get("region")) not in TARGET_REGIONS
        for item in coverage_errors
    )
    error_regions = {
        normalize_space(item.get("region"))
        for item in coverage_errors
        if normalize_space(item.get("region")) in TARGET_REGIONS
    }
    result: dict[str, str] = {}
    for region in TARGET_REGIONS:
        if global_coverage_error or region in error_regions:
            result[region] = "partial_error"
        elif region in present:
            result[region] = "covered"
        elif region in {"australia", "germany", "middle_east"}:
            regional = other_coverage.get("coverage_by_region", {})
            value = regional.get(region) if isinstance(regional, Mapping) else None
            result[region] = (
                value
                if value in {
                    "covered",
                    "no_public_in_scope_races",
                    "classification_incomplete",
                }
                else "classification_incomplete"
            )
        else:
            result[region] = "no_public_in_scope_races"
    return result


def _deduplicated_errors(
    errors: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for raw in errors:
        record = dict(raw)
        identity = tuple(
            normalize_space(record.get(field))
            for field in (
                "error_code",
                "stage",
                "key",
                "status",
                "raw_finish_status",
                "horse_display_name",
                "occurrence_index",
                "region",
                "country",
            )
        )
        existing = unique.get(identity)
        if existing is None or canonical_json_bytes(record) < canonical_json_bytes(
            existing
        ):
            unique[identity] = record
    return sorted(
        unique.values(),
        key=lambda item: (
            normalize_space(item.get("error_code")),
            normalize_space(item.get("stage")),
            normalize_space(item.get("key")),
            normalize_space(item.get("status")),
            canonical_json_bytes(item),
        ),
    )


def finalize_artifacts(
    *,
    output_dir: Path,
    year: int,
    occurrences: Sequence[Mapping[str, Any]],
    profiles: Sequence[Mapping[str, Any]],
    source_manifest: Sequence[Mapping[str, Any]],
    errors: Sequence[Mapping[str, Any]],
    other_coverage: Mapping[str, Any],
    request_count: int,
    generated_at: str,
) -> dict[str, Any]:
    year = validate_year(year)
    final = Path(output_dir)
    final.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in final.iterdir() if path.is_file()}
    unexpected = existing - set(final_filenames(year))
    if unexpected:
        raise ValueError(f"final directory contains unexpected files: {sorted(unexpected)}")
    grouped_by_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in occurrences:
        row = dict(raw)
        grouped_by_lookup[canonical_horse_key(row)].append(row)
    lookup_to_profile: dict[str, dict[str, Any]] = {}
    for raw in profiles:
        profile = dict(raw)
        profile_url = optional_profile_url(profile.get("profile_url"))
        profile["profile_url"] = profile_url
        keys = profile.get("lookup_keys") or [profile.get("key")]
        for key in sorted(set(map(str, keys))):
            key = str(key)
            if key in lookup_to_profile and canonical_json_bytes(
                lookup_to_profile[key]
            ) != canonical_json_bytes(profile):
                raise ValueError("profile lookup key maps to conflicting profiles")
            lookup_to_profile[key] = profile
    if set(grouped_by_lookup) != set(lookup_to_profile):
        raise ValueError(
            "finalize profile coverage mismatch "
            f"missing={sorted(set(grouped_by_lookup)-set(lookup_to_profile))} "
            f"extra={sorted(set(lookup_to_profile)-set(grouped_by_lookup))}"
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    canonical_profiles: dict[str, dict[str, Any]] = {}
    for lookup_key in sorted(grouped_by_lookup):
        profile = lookup_to_profile[lookup_key]
        profile_url = optional_profile_url(profile.get("profile_url"))
        canonical = (
            f"profile|{validate_profile_url(profile_url)}"
            if profile_url
            else normalize_space(profile.get("key")) or lookup_key
        )
        if canonical in canonical_profiles and canonical_json_bytes(
            canonical_profiles[canonical]
        ) != canonical_json_bytes(profile):
            raise ValueError("canonical profile content conflict")
        canonical_profiles[canonical] = profile
        grouped[canonical].extend(grouped_by_lookup[lookup_key])
    horse_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for canonical in sorted(grouped):
        profile = {**canonical_profiles[canonical], "horse_key": canonical}
        record = build_horse_name_record(
            grouped[canonical], profile=profile
        )
        horse_rows.append(record)
        if record["name_issue_codes"]:
            review_rows.append(
                {
                    "horse_key": record["horse_key"],
                    "regions": record["regions"],
                    "countries": record["countries"],
                    "profile_url": record["profile_url"],
                    "name_zh": record["name_zh"],
                    "name_ja": record["name_ja"],
                    "name_en": record["name_en"],
                    "profile_resolution_state": record["profile_resolution_state"],
                    "required_english_status": record["required_english_status"],
                    "name_completeness": record["name_completeness"],
                    "name_issue_codes": record["name_issue_codes"],
                }
            )
    name_errors = [
        {
            "stage": "horse_name",
            "key": record["horse_key"],
            "status": "unresolved",
            "error_code": issue,
            "error": "horse name completeness issue",
        }
        for record in horse_rows
        for issue in record["name_issue_codes"]
    ]
    all_errors = _deduplicated_errors([*errors, *name_errors])
    horse_keys = [row["horse_key"] for row in horse_rows]
    if len(horse_keys) != len(set(horse_keys)):
        raise ValueError("finalize canonical horse keys are not unique")
    review_keys = [row["horse_key"] for row in review_rows]
    if len(review_keys) != len(set(review_keys)):
        raise ValueError("review queue horse keys are not unique")
    required = [
        row
        for row in horse_rows
        if row["required_english_status"] in {"complete", "missing"}
    ]
    profile_counts = Counter(row["profile_resolution_state"] for row in horse_rows)
    if sum(profile_counts.values()) != len(horse_rows):
        raise ValueError("profile resolution invariant failed")
    participant_counts = Counter(
        normalize_space(item.get("participant_status")) for item in occurrences
    )
    counts = {
        "discovered_urls": len(
            {normalize_space(item.get("url")) for item in source_manifest}
        ),
        "fetched_races": len(source_manifest),
        "included_races": len(
            {normalize_space(item.get("race_url")) for item in occurrences}
        ),
        "participant_rows": len(occurrences),
        "included_participant_rows": len(occurrences),
        "unique_horses": len(horse_rows),
        "non_starters_excluded": sum(
            int(item.get("non_starters_excluded", 0)) for item in source_manifest
        ),
        "participant_status_unresolved": sum(
            int(item.get("participant_status_unresolved", 0))
            for item in source_manifest
        ),
        "started_non_finish": participant_counts["started_non_finish"],
        "disqualified_after_start": participant_counts["disqualified_after_start"],
        "required_english_complete": sum(
            row["required_english_status"] == "complete" for row in required
        ),
        "required_english_missing": sum(
            row["required_english_status"] == "missing" for row in required
        ),
        "profile_resolved": profile_counts["resolved"],
        "profile_not_found": profile_counts["not_found"],
        "profile_unresolved": profile_counts["unresolved"],
        "profile_ambiguous": profile_counts["ambiguous"],
        "profile_error": profile_counts["error"],
        "errors": len(all_errors),
        "coverage_errors": sum(
            normalize_space(item.get("stage"))
            in {"discovery", "races", "race_page", "result_row"}
            for item in all_errors
        ),
        "request_count": request_count,
        **{
            key: int(other_coverage.get(key, 0))
            for key in (
                "discovered_other_urls",
                "classified_other_urls",
                "unclassified_other_urls",
                "out_of_scope_other_urls",
            )
        },
    }
    if counts["required_english_complete"] + counts["required_english_missing"] != len(required):
        raise ValueError("required English invariant failed")
    if sum(
        counts[key]
        for key in (
            "profile_resolved",
            "profile_not_found",
            "profile_unresolved",
            "profile_ambiguous",
            "profile_error",
        )
    ) != counts["unique_horses"]:
        raise ValueError("profile status invariant failed")
    outcome = (
        "partial"
        if all_errors
        or counts["participant_status_unresolved"]
        or counts["required_english_missing"]
        or counts["profile_unresolved"]
        or counts["profile_ambiguous"]
        or counts["profile_error"]
        or counts["profile_not_found"]
        or other_coverage.get("coverage_status") == "classification_incomplete"
        else "complete"
    )
    occurrence_rows = sorted(
        (dict(row) for row in occurrences),
        key=lambda row: (
            normalize_space(row.get("race_date")),
            normalize_space(row.get("race_url")),
            int(row.get("normalized_finish_position") or 9999),
            normalize_space(row.get("horse_number")),
            normalize_space(row.get("horse_display_name")),
        ),
    )
    write_csv(
        final / f"race_participants_{year}.csv",
        occurrence_rows,
        RACE_PARTICIPANT_FIELDS,
    )
    write_csv(
        final / f"horse_names_{year}.csv",
        horse_rows,
        HORSE_NAME_FIELDS,
    )
    write_csv(
        final / f"horse_name_review_queue_{year}.csv",
        review_rows,
        HORSE_REVIEW_FIELDS,
    )
    source_lines = b"".join(
        canonical_json_bytes(item)
        for item in sorted(
            (dict(item) for item in source_manifest),
            key=lambda item: normalize_space(item.get("url")),
        )
    )
    atomic_write_bytes(final / "source_manifest.jsonl", source_lines)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "year": year,
        "generated_at": generated_at,
        "outcome": outcome,
        "counts": counts,
        "coverage_by_region": coverage_by_region(
            occurrences=occurrences,
            other_coverage=other_coverage,
            errors=all_errors,
        ),
        "other_coverage": dict(other_coverage),
    }
    atomic_write_json(final / "summary.json", summary)
    atomic_write_json(final / "errors.json", all_errors)
    atomic_write_text(
        final / "README.md",
        f"""# {year} 年分级赛全部参赛马研究产物

本目录仅代表采集时 UmaFans 公共、已完赛且数据质量完整的分级赛页面，不证明外部全球赛历完整。
实际参赛马来自正式结果表；退赛和未知状态不进入 occurrence。中文和日文为尽力字段，美国、英国、
法国、澳大利亚、德国和中东要求英文名。覆盖结论与复核问题以 `summary.json` 和
`horse_name_review_queue_{year}.csv` 为准。
""",
    )
    actual = {path.name for path in final.iterdir() if path.is_file()}
    if actual != set(final_filenames(year)):
        raise ValueError("final file contract is not exact")
    return summary


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class FetchResponse:
    content: bytes
    url: str
    status_code: int


class RequestBudgetExceeded(RuntimeError):
    """请求尚未发出时触发的可安全续跑停止信号。"""


class StageDeadlineExceeded(RequestBudgetExceeded):
    """stage 单调时限到达，可安全停止并续跑。"""


@dataclass(frozen=True)
class StageDeadline:
    deadline_at: float
    clock: Callable[[], float] = time.monotonic
    safety_margin: float = 0.0

    def check(self, required_seconds: float = 0.0) -> None:
        if (
            self.clock() + max(required_seconds, 0)
            >= self.deadline_at - max(self.safety_margin, 0)
        ):
            raise StageDeadlineExceeded("stage monotonic deadline reached")

    @classmethod
    def from_budget(
        cls,
        seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> "StageDeadline | None":
        if seconds <= 0:
            return None
        effective_clock = clock or time.monotonic
        started = effective_clock()
        return cls(
            deadline_at=started + seconds,
            clock=effective_clock,
            safety_margin=min(1.0, seconds * 0.05),
        )


class HttpStatusError(RuntimeError):
    def __init__(self, status_code: int | None, url: str, message: str):
        self.status_code = status_code
        self.url = url
        super().__init__(message)


class RetryableHttpError(HttpStatusError):
    """临时 HTTP/transport 错误，可在剩余预算内重试。"""


class PermanentHttpError(HttpStatusError):
    """确定性 HTTP 错误，不应在 resume 中反复请求。"""


class HttpClient:
    def __init__(
        self,
        *,
        delay: float,
        timeout: float,
        request_budget: int,
        request_count_start: int = 0,
        request_reserver: Callable[[], int] | None = None,
        deadline: StageDeadline | None = None,
    ):
        if request_budget < 1:
            raise ValueError("request budget must be positive")
        if not 0 <= request_count_start <= request_budget:
            raise ValueError("request count exceeds request budget")
        self.delay = max(delay, 0)
        self.timeout = timeout
        self.request_budget = request_budget
        self.request_count = request_count_start
        self.request_reserver = request_reserver
        self.deadline = deadline
        self.opener = build_opener(_NoRedirect)

    def check_deadline(self, required_seconds: float = 0.0) -> None:
        if self.deadline is not None:
            self.deadline.check(required_seconds)

    def _sleep(self, seconds: float) -> None:
        self.check_deadline(seconds)
        time.sleep(seconds)
        self.check_deadline()

    def get(
        self, url: str, *, params: Mapping[str, Any] | None = None
    ) -> FetchResponse:
        current = validate_request_url(
            url, allow_horse_search_query=not params
        )
        if params:
            current = validate_request_url(
                f"{current}?{urlencode(params)}",
                allow_horse_search_query=True,
            )
        request_scheme = urlsplit(current).scheme
        profile_request = bool(
            re.fullmatch(
                r"/horses/[1-9][0-9]*/?",
                urlsplit(current).path,
            )
        )
        profile_origin_host = (
            urlsplit(current).hostname if profile_request else None
        )
        for _ in range(6):
            for attempt in range(5):
                self.check_deadline()
                if self.request_count >= self.request_budget:
                    raise RequestBudgetExceeded(
                        f"request budget exhausted before transport: "
                        f"{self.request_count}/{self.request_budget}"
                    )
                if self.request_reserver:
                    reserved = self.request_reserver()
                    if reserved != self.request_count + 1:
                        raise ValueError("request ledger/client count drift")
                    self.request_count = reserved
                else:
                    self.request_count += 1
                request = Request(
                    current,
                    headers={
                        "User-Agent": "UmaFansResearch/1.0 (yearly graded race participants)",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
                    },
                    method="GET",
                )
                try:
                    response = self.opener.open(request, timeout=self.timeout)
                    status = int(response.status)
                    headers = response.headers
                    content = response.read()
                    final_url = response.geturl()
                except HTTPError as exc:
                    status = int(exc.code)
                    headers = exc.headers
                    final_url = exc.geturl()
                    content = exc.read()
                    exc.close()
                    if (
                        status in {408, 425, 429} or 500 <= status <= 599
                    ) and attempt < 4:
                        self._sleep(0.8 * (2**attempt))
                        continue
                    if status in {408, 425, 429} or 500 <= status <= 599:
                        raise RetryableHttpError(
                            status,
                            current,
                            f"retryable HTTP status {status}",
                        ) from exc
                    if 400 <= status <= 499:
                        raise PermanentHttpError(
                            status,
                            current,
                            f"permanent HTTP status {status}",
                        ) from exc
                    if (
                        status in {301, 302, 303, 307, 308}
                    ):
                        pass
                    else:
                        raise PermanentHttpError(
                            status,
                            current,
                            f"unexpected HTTP status {status}",
                        ) from exc
                except URLError:
                    if attempt >= 4:
                        raise RetryableHttpError(
                            None,
                            current,
                            "retryable transport error",
                        )
                    self._sleep(0.8 * (2**attempt))
                    continue
                break
            else:  # pragma: no cover - retry loop always returns or raises
                raise RuntimeError("request retry state is invalid")
            if status not in {301, 302, 303, 307, 308}:
                self.check_deadline()
                response_url = (
                    validate_profile_url(
                        final_url, expected_scheme=request_scheme
                    )
                    if profile_request
                    else validate_request_url(
                        urlunparse((*urlparse(final_url)[:3], "", "", "")),
                        expected_scheme=request_scheme,
                    )
                )
                if (
                    profile_request
                    and urlsplit(response_url).hostname
                    != profile_origin_host
                ):
                    raise ValueError("profile final URL host drift")
                result = FetchResponse(
                    content=content,
                    url=response_url,
                    status_code=status,
                )
                if self.delay:
                    self._sleep(self.delay)
                return result
            location = headers.get("Location")
            if not location:
                raise RuntimeError("redirect has no Location")
            if profile_request:
                redirected = resolve_profile_href(
                    location, base_url=current
                )
                if (
                    urlsplit(redirected).hostname
                    != profile_origin_host
                ):
                    raise ValueError("profile redirect host drift")
                current = redirected
            else:
                current = validate_request_url(
                    urljoin(current, location),
                    allow_horse_search_query=True,
                    expected_scheme=request_scheme,
                )
            self.check_deadline()
        raise RuntimeError("too many redirects")


def _check_client_deadline(
    client: Any, required_seconds: float = 0.0
) -> None:
    checker = getattr(client, "check_deadline", None)
    if callable(checker):
        checker(required_seconds)
        return
    deadline = getattr(client, "deadline", None)
    if deadline is not None:
        deadline.check(required_seconds)


def _validate_discovery_progress(
    state: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    client_request_count: int,
    year: int,
) -> dict[str, Any]:
    for key, expected in identity.items():
        if state.get(key) != expected:
            raise ValueError(f"discovery progress {key} drift")
    queue = state.get("queue")
    visited = state.get("visited")
    discovered = state.get("discovered_urls")
    inflight = normalize_space(state.get("inflight_url"))
    if not all(isinstance(value, list) for value in (queue, visited, discovered)):
        raise ValueError("discovery progress collections are invalid")
    if len(queue) != len(set(queue)) or len(visited) != len(set(visited)):
        raise ValueError("discovery progress URL duplication")
    if set(queue) & set(visited):
        raise ValueError("discovery progress queue/visited overlap")
    scheme_source = identity.get("base_url") or next(
        iter([*queue, *visited, *discovered]), ""
    )
    expected_scheme = (
        urlparse(validate_request_url(scheme_source)).scheme
        if scheme_source
        else None
    )
    normalized_queue = [
        validate_request_url(url, expected_scheme=expected_scheme)
        for url in queue
    ]
    normalized_visited = [
        validate_request_url(url, expected_scheme=expected_scheme)
        for url in visited
    ]
    normalized_discovered = [
        validate_race_url(url, year, expected_scheme=expected_scheme)
        for url in discovered
    ]
    if (
        normalized_queue != queue
        or normalized_visited != visited
        or normalized_discovered != sorted(set(discovered))
    ):
        raise ValueError("discovery progress URL drift")
    if inflight and (not queue or inflight != queue[0]):
        raise ValueError("discovery progress inflight drift")
    request_count = state.get("request_count")
    request_budget = identity.get("request_budget")
    if (
        not isinstance(request_count, int)
        or request_count < 0
        or request_count > client_request_count
        or (not inflight and request_count != client_request_count)
        or (
            inflight
            and client_request_count - request_count > 30
        )
        or (
            isinstance(request_budget, int)
            and client_request_count > request_budget
        )
    ):
        raise ValueError("discovery progress request count drift")
    if bool(state.get("complete")) != (not queue and not inflight):
        raise ValueError("discovery progress completion drift")
    return dict(state)


def discover_race_urls(
    client: HttpClient,
    *,
    base_url: str,
    year: int,
    progress_path: Path | None = None,
    identity: Mapping[str, Any] | None = None,
    resume: bool = False,
    deadline: StageDeadline | None = None,
) -> list[str]:
    base = validate_request_url(base_url)
    expected_scheme = urlparse(base).scheme
    sitemap = urljoin(base, "/sitemap.xml")
    expected_identity = dict(identity or {})
    state = {
        **expected_identity,
        "queue": [sitemap],
        "visited": [],
        "discovered_urls": [],
        "inflight_url": "",
        "request_count": int(getattr(client, "request_count", 0)),
        "complete": False,
    }
    if progress_path is not None and progress_path.exists():
        if not resume:
            raise ValueError("discovery progress exists; resume is required")
        try:
            raw_state = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("discovery progress is corrupt") from exc
        state = _validate_discovery_progress(
            raw_state,
            identity=expected_identity,
            client_request_count=int(getattr(client, "request_count", 0)),
            year=year,
        )
    elif progress_path is not None:
        atomic_write_json(progress_path, state)
    if deadline is not None:
        client.deadline = deadline
    while state["queue"]:
        _check_client_deadline(client)
        current = state["queue"][0]
        state["inflight_url"] = current
        state["request_count"] = int(getattr(client, "request_count", 0))
        if progress_path is not None:
            atomic_write_json(progress_path, state)
        try:
            response = client.get(current)
        except (
            RequestBudgetExceeded,
            RetryableHttpError,
            PermanentHttpError,
        ):
            state["request_count"] = int(
                getattr(client, "request_count", 0)
            )
            if progress_path is not None:
                atomic_write_json(progress_path, state)
            raise
        root = ET.fromstring(response.content)
        root_kind = root.tag.rsplit("}", 1)[-1]
        discovered = set(state["discovered_urls"])
        queued = set(state["queue"]) | set(state["visited"])
        new_sitemaps: list[str] = []
        if root_kind == "sitemapindex":
            locations = [
                normalize_space(node.text)
                for node in root.findall("./{*}sitemap/{*}loc")
                if node.text
            ]
            for location in locations:
                candidate = validate_request_url(
                    location, expected_scheme=expected_scheme
                )
                sitemap_path = urlparse(candidate).path.casefold()
                if not sitemap_path.endswith(".xml") or "sitemap" not in sitemap_path:
                    raise ValueError("sitemapindex contains a non-sitemap URL")
                if candidate not in queued:
                    queued.add(candidate)
                    new_sitemaps.append(candidate)
        elif root_kind == "urlset":
            locations = [
                normalize_space(node.text)
                for node in root.findall("./{*}url/{*}loc")
                if node.text
            ]
            target_path_pattern = re.compile(
                rf"^/races/{year}/[^/]+/$"
            )
            race_path_pattern = re.compile(
                r"^/races/\d{4}/[^/]+/$"
            )
            for location in locations:
                path = urlparse(location).path
                if target_path_pattern.match(path):
                    discovered.add(
                        validate_race_url(
                            location,
                            year,
                            expected_scheme=expected_scheme,
                        )
                    )
                elif race_path_pattern.match(path):
                    continue
        else:
            raise ValueError("unsupported sitemap XML root")
        state["queue"] = [*state["queue"][1:], *sorted(new_sitemaps)]
        state["visited"].append(current)
        state["discovered_urls"] = sorted(discovered)
        state["inflight_url"] = ""
        state["request_count"] = int(getattr(client, "request_count", 0))
        state["complete"] = not state["queue"]
        if progress_path is not None:
            atomic_write_json(progress_path, state)
        _check_client_deadline(client)
    return list(state["discovered_urls"])


def _region_manifest_binding(
    path: str | None,
    *,
    year: int,
    worktree_root: Path,
    expected_scheme: str,
) -> tuple[dict[str, Any] | None, str]:
    if not path:
        return None, "none"
    manifest = load_region_manifest(
        path,
        year=year,
        worktree_root=worktree_root,
        expected_scheme=expected_scheme,
    )
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = worktree_root / candidate
    return manifest, sha256_bytes(candidate.resolve(strict=True).read_bytes())


def _new_run_manifest(
    *,
    year: int,
    base_url: str,
    race_urls: Sequence[str],
    region_manifest_sha256: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        **current_tool_identity_record(),
        "year": year,
        "year_start": f"{year}-01-01",
        "year_end": f"{year}-12-31",
        "base_url": validate_request_url(base_url),
        "target_regions": list(TARGET_REGIONS),
        "grade_policy": {
            "japan": sorted(JAPAN_GRADES),
            "other_regions": sorted(STANDARD_GRADES),
        },
        "participant_status_policy": TOOL_POLICY_VERSION,
        "request_budgets": dict(REQUEST_BUDGETS),
        "region_manifest_sha256": region_manifest_sha256,
        "race_urls": list(race_urls),
        "race_urls_sha256": keys_sha256(race_urls),
        "created_at": created_at,
    }


def validate_run_manifest(
    manifest: Mapping[str, Any],
    *,
    year: int,
    region_manifest_sha256: str,
    expected_base_url: str | None = None,
) -> dict[str, Any]:
    required = {
        *current_tool_identity_record(),
        "year",
        "year_start",
        "year_end",
        "base_url",
        "target_regions",
        "grade_policy",
        "participant_status_policy",
        "request_budgets",
        "region_manifest_sha256",
        "race_urls",
        "race_urls_sha256",
        "created_at",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"run manifest missing fields: {missing}")
    if manifest.get("year") != year:
        raise ValueError("run manifest year drift")
    if manifest.get("year_start") != f"{year}-01-01" or manifest.get(
        "year_end"
    ) != f"{year}-12-31":
        raise ValueError("run manifest year boundary drift")
    if manifest.get("region_manifest_sha256") != region_manifest_sha256:
        raise ValueError("run manifest region manifest drift")
    for key, expected in current_tool_identity_record().items():
        if manifest.get(key) != expected:
            raise ValueError(f"run manifest tool identity drift: {key}")
    if manifest.get("target_regions") != list(TARGET_REGIONS):
        raise ValueError("run manifest region policy drift")
    if manifest.get("participant_status_policy") != TOOL_POLICY_VERSION:
        raise ValueError("run manifest participant policy drift")
    if manifest.get("request_budgets") != REQUEST_BUDGETS:
        raise ValueError("run manifest request budget drift")
    base_url = validate_request_url(manifest.get("base_url"))
    if (
        expected_base_url is not None
        and base_url != validate_request_url(expected_base_url)
    ):
        raise ValueError("run manifest base URL drift")
    expected_scheme = urlparse(base_url).scheme
    urls = manifest.get("race_urls")
    if not isinstance(urls, list) or urls != sorted(set(urls)):
        raise ValueError("run manifest race URL ordering drift")
    for url in urls:
        validate_race_url(url, year, expected_scheme=expected_scheme)
    if manifest.get("race_urls_sha256") != keys_sha256(urls):
        raise ValueError("run manifest race URL digest drift")
    return dict(manifest)


def _bound_store(
    root: Path,
    *,
    stage: str,
    year: int,
    manifest_sha256: str,
    region_manifest_sha256: str,
    shard_index: int | None,
    shard_count: int,
    upstream_indexes: Mapping[str, str],
    input_keys: Iterable[str],
    tool_identity: Mapping[str, Any],
    request_budget: int = 0,
) -> StageStore:
    return StageStore(
        root,
        stage=stage,
        year=year,
        shard_index=shard_index,
        shard_count=shard_count,
        manifest_sha256=manifest_sha256,
        region_manifest_sha256=region_manifest_sha256,
        upstream_indexes=upstream_indexes,
        input_keys_sha256=keys_sha256(input_keys),
        request_budget=request_budget,
        tool_identity=tool_identity,
    )


def _ensure_complete_progress(store: StageStore) -> None:
    index = store.verify_index()
    if trusted_stage_request_count(store) != index["request_count"]:
        raise ValueError(f"{store.stage} request ledger is ahead of checkpoint")
    try:
        progress = json.loads(store.progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{store.stage} progress is missing") from exc
    if progress.get("safe_stopped") is not False:
        raise ValueError(f"{store.stage} stage is not complete")
    if progress.get("index_sha256") != sha256_bytes(store.index_path.read_bytes()):
        raise ValueError(f"{store.stage} progress index drift")


def _race_occurrences(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for item in records:
        if item.get("status") != "success":
            continue
        for raw in item.get("rows", []):
            row = dict(raw)
            identity = (
                normalize_space(row.get("race_url")),
                normalize_space(row.get("horse_number")),
                normalize_identity(row.get("horse_display_name")),
            )
            if identity in identities:
                raise ValueError(f"duplicate race participant identity: {identity}")
            identities.add(identity)
            rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            normalize_space(row.get("race_url")),
            int(row.get("normalized_finish_position") or 9999),
            normalize_space(row.get("horse_number")),
            normalize_space(row.get("horse_display_name")),
        ),
    )


def parse_profile_html(
    html: bytes | str, *, url: str, fallback_display_name: str = ""
) -> dict[str, Any]:
    body = html.encode("utf-8") if isinstance(html, str) else bytes(html)
    root = _parse_html(body)
    main = root.first(tag="main")
    if main is None:
        raise ValueError("public horse profile marker missing")
    display_node = root.first(class_name="horse-hero-name")
    original_node = root.first(class_name="horse-hero-original")
    region_node = root.first(class_name="horse-hero-kicker")
    display = display_node.text() if display_node else ""
    original_text = original_node.text() if original_node else ""
    birth_match = YEAR_RE.search(original_text)
    birth_year = birth_match.group(1) if birth_match else ""
    original = original_text.split(" · ", 1)[0].strip()
    if birth_year and original == birth_year:
        original = ""
    region_label = (
        region_node.text().split("·", 1)[0].strip() if region_node else ""
    )
    region, _ = normalize_region_label(region_label)
    metadata = _all_metadata_grids(root)
    country_raw = normalize_space(metadata.get("国家/地区"))
    country_fact = normalize_country_fact(country_raw)
    country_fact_state = (
        "missing"
        if not country_raw
        else "controlled"
        if country_fact
        else "uncontrolled"
    )
    inferred_region = region_for_country_fact(country_fact)
    record = {
        "profile_url": validate_profile_url(url),
        "display_name": display,
        "original_name": original,
        "birth_year": birth_year,
        "racing_region": (
            region
            or inferred_region
            or ("other" if region_label == "其他" else "")
        ),
        "country": country_fact,
        "country_raw": country_raw,
        "country_fact_state": country_fact_state,
        "profile_page_sha256": sha256_bytes(body),
    }
    return {**record, **_candidate_name_fields(record)}


def parse_profile_search_html(html: bytes | str, *, base_url: str) -> list[dict[str, Any]]:
    body = html.encode("utf-8") if isinstance(html, str) else bytes(html)
    root = _parse_html(body)
    candidates: list[dict[str, Any]] = []
    for card in root.descendants(tag="article"):
        if not card.has_class("horse-card"):
            continue
        name_container = card.first(class_name="horse-card-name")
        link = name_container.first(tag="a") if name_container else None
        if link is None or not link.attrs.get("href"):
            continue
        display = link.text()
        original_node = card.first(class_name="horse-card-original")
        original = original_node.text() if original_node else ""
        if original == "资料整理中":
            original = ""
        region_node = card.first(class_name="region-label")
        region_label = region_node.text() if region_node else ""
        region, country = normalize_region_label(region_label)
        candidate = {
            "profile_url": resolve_profile_href(
                link.attrs["href"], base_url=base_url
            ),
            "display_name": display,
            "original_name": original,
            "racing_region": region or ("other" if region_label == "其他" else ""),
            "country": country or "",
        }
        candidates.append({**candidate, **_candidate_name_fields(candidate)})
    return candidates


def _profile_aliases(record: Mapping[str, Any]) -> set[str]:
    return {
        normalized
        for field in (
            "horse_display_name",
            "display_name",
            "original_name",
            "name_zh",
            "name_ja",
            "name_en",
        )
        if (normalized := normalize_identity(record.get(field)))
    }


def _profile_group_queries(
    occurrences: Sequence[Mapping[str, Any]],
) -> list[str]:
    aliases: dict[str, set[str]] = defaultdict(set)
    for occurrence in occurrences:
        for field in (
            "horse_display_name",
            "display_name",
            "original_name",
            "name_zh",
            "name_ja",
            "name_en",
        ):
            raw = normalize_space(occurrence.get(field))
            normalized = normalize_identity(raw)
            if normalized:
                aliases[normalized].add(raw)
    return [
        sorted(aliases[normalized], key=lambda item: (item.casefold(), item))[0]
        for normalized in sorted(aliases)
    ]


def _profile_identity_matches(
    occurrence: Mapping[str, Any], candidate: Mapping[str, Any]
) -> bool:
    occurrence_aliases = _profile_aliases(occurrence)
    candidate_aliases = _profile_aliases(candidate)
    occurrence_original = normalize_identity(occurrence.get("original_name"))
    if occurrence_original and occurrence_original not in candidate_aliases:
        return False
    return bool(occurrence_aliases and occurrence_aliases & candidate_aliases)


def _profile_country_fact(
    profile: Mapping[str, Any],
) -> tuple[str, str, str]:
    raw_value = (
        profile.get("country_raw")
        if "country_raw" in profile
        else profile.get("country")
    )
    country_raw = normalize_space(raw_value)
    country_canonical = normalize_country_fact(country_raw)
    country_fact_state = (
        "missing"
        if not country_raw
        else "controlled"
        if country_canonical
        else "uncontrolled"
    )
    return country_raw, country_canonical, country_fact_state


def _profile_region_evidence_state(
    occurrence: Mapping[str, Any], profile: Mapping[str, Any]
) -> str:
    expected_region = normalize_space(occurrence.get("region"))
    expected_country = normalize_space(occurrence.get("country"))
    actual_region = normalize_space(profile.get("racing_region"))
    (
        actual_country_raw,
        actual_country_canonical,
        actual_country_fact_state,
    ) = _profile_country_fact(profile)
    expected_year = normalize_space(occurrence.get("birth_year"))
    actual_year = normalize_space(profile.get("birth_year"))
    if not actual_region:
        return "unresolved"
    if expected_region in {"australia", "germany", "middle_east"}:
        if actual_region not in {expected_region, "other"}:
            return "ambiguous"
    elif actual_region != expected_region:
        return "ambiguous"
    if expected_region == "middle_east":
        if expected_year and not actual_year:
            return "unresolved"
        expected_country_raw = normalize_space(
            occurrence.get("country_raw") or expected_country
        )
        expected_country_canonical = normalize_country_fact(
            expected_country_raw
        )
        if (
            expected_country_canonical not in MIDDLE_EAST_COUNTRIES
            or actual_country_canonical not in MIDDLE_EAST_COUNTRIES
        ):
            return "unresolved"
        if actual_country_canonical != expected_country_canonical:
            return "ambiguous"
        if expected_year and actual_year and actual_year != expected_year:
            return "ambiguous"
        return "resolved"
    if expected_region in {"australia", "germany"}:
        if actual_country_fact_state == "uncontrolled":
            return "ambiguous"
        if expected_year and not actual_year:
            return "unresolved"
        expected_country_canonical = normalize_country_fact(expected_country)
        if (
            actual_country_fact_state == "controlled"
            and expected_country_canonical
            and actual_country_canonical != expected_country_canonical
        ):
            return "ambiguous"
        if expected_year and actual_year and actual_year != expected_year:
            return (
                "ambiguous"
                if actual_country_fact_state == "controlled"
                and expected_country_canonical
                else "unresolved"
            )
        if (
            actual_country_fact_state == "controlled"
            and expected_country_canonical == actual_country_canonical
        ):
            return "resolved"
        if expected_year and actual_year == expected_year:
            return "resolved"
        return "unresolved"
    if actual_country_fact_state == "uncontrolled":
        return "ambiguous"
    expected_standard_country = normalize_country_fact(
        expected_country or expected_region
    )
    if (
        actual_country_fact_state == "controlled"
        and actual_country_canonical != expected_standard_country
    ):
        return "ambiguous"
    if expected_year and actual_year and actual_year != expected_year:
        return "ambiguous"
    return "resolved"


def _profile_occurrence_reviews(
    occurrences: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    actual_aliases = sorted(_profile_aliases(profile))
    actual_region = normalize_space(profile.get("racing_region"))
    actual_country = normalize_space(profile.get("country"))
    (
        actual_country_raw,
        actual_country_canonical,
        actual_country_fact_state,
    ) = _profile_country_fact(profile)
    actual_birth_year = normalize_space(profile.get("birth_year"))
    actual_profile_url = optional_profile_url(profile.get("profile_url"))
    for index, occurrence in enumerate(occurrences):
        name_matches = _profile_identity_matches(occurrence, profile)
        region_state = _profile_region_evidence_state(occurrence, profile)
        review_state = (
            "ambiguous"
            if not name_matches or region_state == "ambiguous"
            else "unresolved"
            if region_state == "unresolved"
            else "resolved"
        )
        expected_region = normalize_space(occurrence.get("region"))
        expected_country = normalize_space(occurrence.get("country"))
        expected_country_raw = normalize_space(
            occurrence.get("country_raw") or expected_country
        )
        expected_country_canonical = normalize_country_fact(
            expected_country_raw
        )
        expected_birth_year = normalize_space(
            occurrence.get("birth_year")
        )
        conflict_fields: list[str] = []
        reasons: list[str] = []
        if not name_matches:
            conflict_fields.append("name_aliases")
            reasons.append("name_alias_mismatch")
        allowed_regions = (
            {expected_region, "other"}
            if expected_region in {"australia", "germany", "middle_east"}
            else {expected_region}
        )
        if not actual_region:
            conflict_fields.append("region")
            reasons.append("actual_region_missing")
        elif actual_region not in allowed_regions:
            conflict_fields.append("region")
            reasons.append("region_mismatch")
        if expected_region == "middle_east":
            middle_east_reasons: list[str] = []
            if not expected_country_raw:
                middle_east_reasons.append(
                    "middle_east_expected_country_missing"
                )
            elif expected_country_canonical not in MIDDLE_EAST_COUNTRIES:
                middle_east_reasons.append(
                    "middle_east_expected_country_uncontrolled"
                )
            if not actual_country_raw:
                middle_east_reasons.append(
                    "middle_east_actual_country_missing"
                )
            elif actual_country_canonical not in MIDDLE_EAST_COUNTRIES:
                middle_east_reasons.append(
                    "middle_east_actual_country_uncontrolled"
                )
            if (
                expected_country_canonical in MIDDLE_EAST_COUNTRIES
                and actual_country_canonical in MIDDLE_EAST_COUNTRIES
                and expected_country_canonical != actual_country_canonical
            ):
                middle_east_reasons.append("middle_east_country_mismatch")
            if middle_east_reasons:
                conflict_fields.append("country")
                reasons.extend(middle_east_reasons)
        elif actual_country_fact_state == "uncontrolled":
            conflict_fields.append("country")
            reasons.append("actual_country_uncontrolled")
        elif (
            actual_country_fact_state == "controlled"
            and expected_country_canonical
            and actual_country_canonical != expected_country_canonical
        ):
            conflict_fields.append("country")
            reasons.append("country_mismatch")
        elif (
            actual_country_fact_state == "missing"
            and region_state == "unresolved"
            and expected_country
        ):
            conflict_fields.append("country")
            reasons.append("actual_country_missing")
        if (
            expected_birth_year
            and not actual_birth_year
            and expected_region
            in {"australia", "germany", "middle_east"}
        ):
            conflict_fields.append("birth_year")
            reasons.append("actual_birth_year_missing")
        elif (
            expected_birth_year
            and actual_birth_year != expected_birth_year
        ):
            conflict_fields.append("birth_year")
            reasons.append("birth_year_mismatch")
        reviews.append(
            {
                "occurrence_index": index,
                "review_state": review_state,
                "name_matches": name_matches,
                "region_state": region_state,
                "conflict_fields": sorted(set(conflict_fields)),
                "reasons": sorted(set(reasons)),
                "expected_aliases": sorted(_profile_aliases(occurrence)),
                "actual_aliases": actual_aliases,
                "horse_display_name": normalize_space(
                    occurrence.get("horse_display_name")
                ),
                "original_name": normalize_space(
                    occurrence.get("original_name")
                ),
                "region": normalize_space(occurrence.get("region")),
                "country": normalize_space(occurrence.get("country")),
                "birth_year": normalize_space(
                    occurrence.get("birth_year")
                ),
                "expected_region": expected_region,
                "expected_country": expected_country,
                "expected_country_raw": expected_country_raw,
                "expected_country_canonical": expected_country_canonical,
                "expected_birth_year": expected_birth_year,
                "actual_display_name": normalize_space(
                    profile.get("display_name")
                ),
                "actual_original_name": normalize_space(
                    profile.get("original_name")
                ),
                "actual_region": actual_region,
                "actual_country": actual_country,
                "actual_country_raw": actual_country_raw,
                "actual_country_canonical": actual_country_canonical,
                "actual_country_fact_state": actual_country_fact_state,
                "actual_birth_year": actual_birth_year,
                "race_url": normalize_space(occurrence.get("race_url")),
                "profile_url": actual_profile_url,
            }
        )
    return reviews


def _validate_profile_group(
    occurrences: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]
) -> dict[str, Any]:
    reviews = _profile_occurrence_reviews(occurrences, profile)
    failed_reviews = [
        review for review in reviews if review["review_state"] != "resolved"
    ]
    if failed_reviews:
        resolution_state = (
            "ambiguous"
            if any(
                review["review_state"] == "ambiguous"
                for review in failed_reviews
            )
            else "unresolved"
        )
        return {
            "resolution_state": resolution_state,
            "identity_reviews": reviews,
        }
    return {**profile, "resolution_state": "resolved"}


def _horse_search_page_url(
    url: str,
    *,
    expected_query: str,
    expected_scheme: str | None = None,
) -> str:
    canonical = validate_request_url(
        url,
        allow_horse_search_query=True,
        expected_scheme=expected_scheme,
    )
    pairs = parse_qsl(urlparse(canonical).query, keep_blank_values=True)
    if pairs[0] != ("q", expected_query):
        raise ValueError("horse search pagination query drift")
    return canonical


def _profile_search_next_url(
    html: bytes | str,
    *,
    current_url: str,
    expected_query: str,
) -> str:
    body = html.encode("utf-8") if isinstance(html, str) else bytes(html)
    root = _parse_html(body)
    pagination = root.first(tag="nav", class_name="pagination")
    if pagination is None:
        return ""
    next_links = [
        link
        for link in pagination.descendants(tag="a")
        if normalize_space(link.text()) == "下一页" and link.attrs.get("href")
    ]
    if not next_links:
        return ""
    if len(next_links) != 1:
        raise ValueError("horse search pagination next link is ambiguous")
    return _horse_search_page_url(
        urljoin(current_url, next_links[0].attrs["href"]),
        expected_query=expected_query,
        expected_scheme=urlparse(current_url).scheme,
    )


def _search_profile_candidates(
    client: HttpClient,
    *,
    base_url: str,
    query: str,
) -> list[dict[str, Any]]:
    search_url = urljoin(validate_request_url(base_url), "/horses/")
    canonical_first = f"{search_url}?{urlencode({'q': query})}"
    seen = {canonical_first}
    try:
        response = client.get(search_url, params={"q": query})
    except PermanentHttpError as exc:
        if exc.status_code == 404:
            return []
        raise
    candidates: list[dict[str, Any]] = []
    current_url = canonical_first
    for _ in range(100):
        _check_client_deadline(client)
        candidates.extend(
            parse_profile_search_html(response.content, base_url=base_url)
        )
        next_url = _profile_search_next_url(
            response.content,
            current_url=current_url,
            expected_query=query,
        )
        if not next_url:
            return candidates
        if next_url in seen:
            raise ValueError("horse search pagination cycle or duplicate URL")
        seen.add(next_url)
        current_url = next_url
        _check_client_deadline(client)
        response = client.get(next_url)
        _check_client_deadline(client)
    raise ValueError("horse search pagination page limit exceeded")


def fetch_profile(
    client: HttpClient,
    *,
    base_url: str,
    occurrences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    representative = occurrences[0]
    expected_scheme = urlparse(validate_request_url(base_url)).scheme
    direct_urls = {
        validate_profile_url(
            profile_url, expected_scheme=expected_scheme
        )
        for item in occurrences
        if (profile_url := optional_profile_url(item.get("profile_url")))
    }
    if len(direct_urls) > 1:
        return {"resolution_state": "ambiguous"}
    if direct_urls:
        profile_url = next(iter(direct_urls))
        try:
            response = client.get(profile_url)
        except PermanentHttpError as exc:
            if exc.status_code == 404:
                return {"resolution_state": "not_found"}
            raise
        profile = parse_profile_html(
            response.content,
            url=response.url,
            fallback_display_name=normalize_space(
                representative.get("horse_display_name")
            ),
        )
        if not normalize_space(profile.get("display_name")):
            return {"resolution_state": "unresolved"}
        return _validate_profile_group(occurrences, profile)
    display = normalize_space(representative.get("horse_display_name"))
    group_aliases = {
        alias for occurrence in occurrences for alias in _profile_aliases(occurrence)
    }
    candidates_by_url: dict[str, dict[str, Any]] = {}
    for query in _profile_group_queries(occurrences):
        _check_client_deadline(client)
        for candidate in _search_profile_candidates(
            client, base_url=base_url, query=query
        ):
            if not (group_aliases & _profile_aliases(candidate)):
                continue
            profile_url = validate_profile_url(candidate.get("profile_url"))
            candidates_by_url.setdefault(
                profile_url, {**candidate, "profile_url": profile_url}
            )
        _check_client_deadline(client)
    candidates = [
        candidates_by_url[url] for url in sorted(candidates_by_url)
    ]
    had_identity_candidates = bool(candidates)
    group_regions = {
        normalize_space(occurrence.get("region"))
        for occurrence in occurrences
        if normalize_space(occurrence.get("region"))
    }
    allowed_candidate_regions = set(group_regions)
    if group_regions & {"australia", "germany", "middle_east"}:
        allowed_candidate_regions.add("other")
    candidates = [
        candidate
        for candidate in candidates
        if normalize_space(candidate.get("racing_region"))
        in allowed_candidate_regions
    ]
    if had_identity_candidates and not candidates:
        return {"resolution_state": "unresolved"}
    if group_regions & {"australia", "germany", "middle_east"}:
        detailed_candidates: list[dict[str, Any]] = []
        detail_rejections: list[dict[str, Any]] = []
        missing_detail_name = False
        for candidate in candidates:
            try:
                detail = client.get(candidate["profile_url"])
            except PermanentHttpError as exc:
                if exc.status_code == 404:
                    continue
                raise
            profile = parse_profile_html(
                detail.content, url=detail.url, fallback_display_name=display
            )
            if not normalize_space(profile.get("display_name")):
                missing_detail_name = True
                continue
            validated = _validate_profile_group(
                occurrences, {**candidate, **profile}
            )
            if validated["resolution_state"] != "resolved":
                detail_rejections.append(validated)
                continue
            detailed_candidates.append(validated)
        if candidates and not detailed_candidates:
            if detail_rejections:
                resolution_state = (
                    "ambiguous"
                    if any(
                        item["resolution_state"] == "ambiguous"
                        for item in detail_rejections
                    )
                    else "unresolved"
                )
                evidence = next(
                    item
                    for item in detail_rejections
                    if item["resolution_state"] == resolution_state
                )
                return {
                    "resolution_state": resolution_state,
                    "identity_reviews": evidence["identity_reviews"],
                }
            if missing_detail_name:
                return {"resolution_state": "unresolved"}
            return {"resolution_state": "ambiguous"}
        if not detailed_candidates:
            return {"resolution_state": "not_found"}
        if len(detailed_candidates) > 1:
            return {
                "resolution_state": "ambiguous",
                "candidate_count": len(detailed_candidates),
            }
        return detailed_candidates[0]
    region_candidates = list(candidates)
    if not candidates:
        return {"resolution_state": "not_found"}
    if not region_candidates:
        return {"resolution_state": "unresolved"}
    if len(region_candidates) != 1:
        return {"resolution_state": "ambiguous"}
    candidate = region_candidates[0]
    try:
        detail = client.get(candidate["profile_url"])
    except PermanentHttpError as exc:
        if exc.status_code == 404:
            return {"resolution_state": "not_found"}
        raise
    profile = parse_profile_html(
        detail.content, url=detail.url, fallback_display_name=display
    )
    if not normalize_space(profile.get("display_name")):
        return {"resolution_state": "unresolved"}
    return _validate_profile_group(
        occurrences, {**candidate, **profile}
    )


def _structured_errors(
    records_by_stage: Sequence[tuple[str, Sequence[Mapping[str, Any]]]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stage, records in records_by_stage:
        for record in records:
            status = normalize_space(record.get("status"))
            skip_reason = normalize_space(record.get("skip_reason"))
            if status == "skipped" and skip_reason == "region_unresolved":
                source = record.get("source")
                source = source if isinstance(source, Mapping) else {}
                result.append(
                    {
                        "stage": stage,
                        "key": normalize_space(record.get("key")),
                        "status": status,
                        "error_code": "region_unresolved",
                        "error": "race page region requires review",
                        "skip_reason": skip_reason,
                        "page_region": normalize_space(
                            source.get("region_label")
                        ),
                        "region": normalize_space(source.get("region")),
                        "country": normalize_space(source.get("country")),
                        "source_url": normalize_space(source.get("url")),
                    }
                )
            if status in RETRYABLE_ITEM_STATUSES | {
                "permanent_error",
                "evidence_gap",
            }:
                source = record.get("source")
                source = source if isinstance(source, Mapping) else {}
                result.append(
                    {
                        "stage": stage,
                        "key": normalize_space(record.get("key")),
                        "status": status,
                        "error_code": normalize_space(
                            record.get("error_code") or status
                        ),
                        "error": normalize_space(record.get("error")),
                        "region": normalize_space(source.get("region")),
                        "country": normalize_space(source.get("country")),
                        "source_url": normalize_space(source.get("url")),
                    }
                )
            for unresolved in record.get("unresolved_rows", []):
                result.append(
                    {
                        "stage": "result_row",
                        "key": normalize_space(record.get("key")),
                        "status": "unresolved",
                        "error_code": "participant_status_unresolved",
                        "raw_finish_status": normalize_space(
                            unresolved.get("raw_finish_status")
                        ),
                        "horse_display_name": normalize_space(
                            unresolved.get("horse_display_name")
                        ),
                        "region": normalize_space(unresolved.get("region")),
                        "country": normalize_space(unresolved.get("country")),
                        "source_url": normalize_space(
                            unresolved.get("race_url")
                        ),
                    }
                )
            for review in record.get("identity_reviews", []):
                review_state = normalize_space(review.get("review_state"))
                if review_state == "resolved":
                    continue
                result.append(
                    {
                        "stage": "profile_identity",
                        "key": normalize_space(record.get("key")),
                        "status": review_state,
                        "error_code": (
                            f"profile_occurrence_{review_state}"
                        ),
                        "occurrence_index": review.get(
                            "occurrence_index"
                        ),
                        "horse_display_name": normalize_space(
                            review.get("horse_display_name")
                        ),
                        "original_name": normalize_space(
                            review.get("original_name")
                        ),
                        "region": normalize_space(review.get("region")),
                        "country": normalize_space(review.get("country")),
                        "source_url": normalize_space(
                            review.get("race_url")
                        ),
                        "profile_url": normalize_space(
                            review.get("profile_url")
                        ),
                        "expected_aliases": sorted(
                            review.get("expected_aliases") or []
                        ),
                        "expected_region": normalize_space(
                            review.get("expected_region")
                        ),
                        "expected_country": normalize_space(
                            review.get("expected_country")
                        ),
                        "expected_country_raw": normalize_space(
                            review.get("expected_country_raw")
                        ),
                        "expected_country_canonical": normalize_space(
                            review.get("expected_country_canonical")
                        ),
                        "expected_birth_year": normalize_space(
                            review.get("expected_birth_year")
                        ),
                        "actual_aliases": sorted(
                            review.get("actual_aliases") or []
                        ),
                        "actual_display_name": normalize_space(
                            review.get("actual_display_name")
                        ),
                        "actual_original_name": normalize_space(
                            review.get("actual_original_name")
                        ),
                        "actual_region": normalize_space(
                            review.get("actual_region")
                        ),
                        "actual_country": normalize_space(
                            review.get("actual_country")
                        ),
                        "actual_country_raw": normalize_space(
                            review.get("actual_country_raw")
                        ),
                        "actual_country_canonical": normalize_space(
                            review.get("actual_country_canonical")
                        ),
                        "actual_country_fact_state": normalize_space(
                            review.get("actual_country_fact_state")
                        ),
                        "actual_birth_year": normalize_space(
                            review.get("actual_birth_year")
                        ),
                        "conflict_fields": sorted(
                            review.get("conflict_fields") or []
                        ),
                        "reasons": sorted(review.get("reasons") or []),
                        "name_matches": bool(review.get("name_matches")),
                        "region_state": normalize_space(
                            review.get("region_state")
                        ),
                    }
                )
    return sorted(
        result,
        key=lambda item: (
            item["stage"],
            item["key"],
            item["error_code"],
            canonical_json_bytes(item),
        ),
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://umafans.run/")
    parser.add_argument("--race-region-manifest")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=PROFILE_SHARD_COUNT)
    parser.add_argument("--races-shard-index", type=int, default=0)
    parser.add_argument("--races-shard-count", type=int, default=1)
    parser.add_argument("--time-budget-seconds", type=float, default=0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument(
        "--request-budget",
        type=int,
        default=0,
        help="网络阶段固定请求预算；0 表示使用该 stage 的冻结默认值",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(list(argv))
    try:
        args.year = validate_year(args.year)
    except ValueError as exc:
        parser.error(str(exc))
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("invalid shard parameters")
    if args.request_budget < 0:
        parser.error("request budget must not be negative")
    if args.stage in {"races", "profiles"}:
        expected_budget = REQUEST_BUDGETS[args.stage]
        if args.request_budget not in {0, expected_budget}:
            parser.error(
                f"{args.stage} request budget must equal frozen value "
                f"{expected_budget}"
            )
        args.request_budget = expected_budget
    elif args.request_budget:
        parser.error("non-network stage request budget must be zero")
    return args


def run_synthetic_smoke(
    root: Path, *, year: int = 2025, stop_after: int = 0
) -> dict[str, Any]:
    """无网络验证 safe-stop、精确续跑、四分片 fan-in 与 finalize。"""
    root.mkdir(parents=True, exist_ok=True)
    urls = [
        f"https://umafans.run/races/{year}/synthetic-a/",
        f"https://umafans.run/races/{year}/synthetic-b/",
    ]
    tool_identity = current_tool_identity_record()
    manifest = {
        **tool_identity,
        "year": year,
        "year_start": f"{year}-01-01",
        "year_end": f"{year}-12-31",
        "region_manifest_sha256": "none",
        "race_urls": urls,
        "race_urls_sha256": keys_sha256(urls),
        "created_at": f"{year}-01-01T00:00:00+00:00",
    }
    manifest_path = root / "run_manifest.json"
    if manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        if canonical_json_bytes(current) != canonical_json_bytes(manifest):
            raise ValueError("run manifest drift")
    else:
        atomic_write_json(manifest_path, manifest)
    manifest_sha = sha256_bytes(manifest_path.read_bytes())
    race_store = StageStore(
        root,
        stage="races",
        year=year,
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        tool_identity=tool_identity,
        input_keys_sha256=keys_sha256(urls),
    )
    prior_request_count = trusted_stage_request_count(race_store)
    requests_seen = {"value": prior_request_count}

    def make_race(url: str) -> dict[str, Any]:
        requests_seen["value"] += 1
        suffix = "a" if url.endswith("-a/") else "b"
        return {
            "key": url,
            "status": "success",
            "rows": [
                {
                    "region": "japan",
                    "region_label": "日本",
                    "country": "japan",
                    "race_date": f"{year}-01-01",
                    "race_name_zh": f"合成赛事 {suffix}",
                    "race_name_original": f"Synthetic {suffix}",
                    "grade": "G1",
                    "racecourse": "东京",
                    "raw_finish_status": "1",
                    "normalized_finish_position": 1,
                    "participant_status": "finished",
                    "horse_number": "1",
                    "horse_display_name": f"合成马{suffix}",
                    "profile_url": (
                        "https://umafans.run/horses/"
                        f"{900001 if suffix == 'a' else 900002}/"
                    ),
                    "race_url": url,
                    "race_page_sha256": sha256_bytes(url.encode()),
                }
            ],
            "source": {
                "url": url,
                "sha256": sha256_bytes(url.encode()),
                "non_starters_excluded": 0,
                "participant_status_unresolved": 0,
            },
        }

    kwargs: dict[str, Any] = {}
    if stop_after:
        ticks = iter([0.0, 0.0, 1.0, 1.0, 1.0])
        kwargs = {"time_budget_seconds": 0.5, "clock": lambda: next(ticks)}
    progress = run_checkpointed_items(
        urls,
        store=race_store,
        process=make_race,
        resume=True,
        request_counter=lambda: requests_seen["value"],
        request_counter_start=prior_request_count,
        now=lambda: f"{year}-01-01T00:00:00+00:00",
        **kwargs,
    )
    if progress["safe_stopped"]:
        return {"safe_stopped": True, "exit_code": SAFE_STOP_EXIT_CODE}
    baseline_root = root / "synthetic_uninterrupted_baseline"
    baseline = StageStore(
        baseline_root,
        stage="races",
        year=year,
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        tool_identity=tool_identity,
        input_keys_sha256=keys_sha256(urls),
    )
    run_checkpointed_items(
        urls,
        store=baseline,
        process=make_race,
        resume=True,
        now=lambda: f"{year}-01-01T00:00:00+00:00",
    )
    recovered = {
        path.name: path.read_bytes() for path in race_store.items_dir.glob("*.json")
    }
    uninterrupted = {
        path.name: path.read_bytes() for path in baseline.items_dir.glob("*.json")
    }
    if recovered != uninterrupted:
        raise ValueError("safe-stop resume is not byte equivalent")
    race_records = load_store_records(race_store)
    occurrences = [row for item in race_records for row in item["rows"]]
    grouped = {canonical_horse_key(row): [row] for row in occurrences}
    shard_stores: list[StageStore] = []
    profile_records: list[dict[str, Any]] = []
    for shard in range(PROFILE_SHARD_COUNT):
        keys = [
            key
            for key in grouped
            if stable_shard(key, PROFILE_SHARD_COUNT) == shard
        ]
        store = StageStore(
            root,
            stage="profiles",
            year=year,
            shard_index=shard,
            shard_count=PROFILE_SHARD_COUNT,
            manifest_sha256=manifest_sha,
            upstream_indexes={"races": index_sha256(race_store)},
            input_keys_sha256=keys_sha256(keys),
            tool_identity=tool_identity,
        )
        for key in keys:
            row = grouped[key][0]
            record = {
                "key": key,
                "lookup_keys": [key],
                "profile_url": row["profile_url"],
                "resolution_state": "resolved",
                "name_zh": row["horse_display_name"],
                "name_ja": "",
                "name_en": "",
                "status": "success",
            }
            store.save_item(key, record)
            profile_records.append(record)
        store.rebuild_index(request_count=len(keys))
        shard_stores.append(store)
    merged = merge_profile_records(profile_records, grouped)
    merged_store = StageStore(
        root,
        stage="profiles_merged",
        year=year,
        manifest_sha256=manifest_sha,
        upstream_indexes={
            "races": index_sha256(race_store),
            **{
                f"profiles:{index}": index_sha256(store)
                for index, store in enumerate(shard_stores)
            },
        },
        input_keys_sha256=keys_sha256(grouped),
        tool_identity=tool_identity,
    )
    for record in merged:
        merged_store.save_item(record["key"], record)
    merged_store.rebuild_index(
        request_count=sum(store.verify_index()["request_count"] for store in shard_stores)
    )
    summary = finalize_artifacts(
        output_dir=root / "final",
        year=year,
        occurrences=occurrences,
        profiles=merged,
        source_manifest=[item["source"] for item in race_records],
        errors=[],
        other_coverage=classify_other_coverage(
            year=year, discovered_other_urls=[], manifest=None
        ),
        request_count=race_store.verify_index()["request_count"]
        + merged_store.verify_index()["request_count"],
        generated_at=f"{year}-01-01T00:00:00+00:00",
    )
    return {
        "safe_stopped": False,
        "byte_equivalent": True,
        "summary": summary,
        "final_files": sorted(path.name for path in (root / "final").iterdir()),
    }


def _discovery_progress_identity(
    *,
    year: int,
    base_url: str,
    region_manifest_sha256: str,
    request_budget: int,
) -> RequestLedger:
    base = validate_request_url(base_url)
    tool_identity = current_tool_identity_record()
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "races_discovery",
        "year": year,
        "base_url": base,
        "region_manifest_sha256": region_manifest_sha256,
        "tool_identity": tool_identity,
        "request_budget": request_budget,
    }


def _discovery_request_ledger(
    root: Path,
    *,
    year: int,
    base_url: str,
    region_manifest_sha256: str,
    request_budget: int,
) -> RequestLedger:
    discovery_manifest = _discovery_progress_identity(
        year=year,
        base_url=base_url,
        region_manifest_sha256=region_manifest_sha256,
        request_budget=request_budget,
    )
    tool_identity = discovery_manifest["tool_identity"]
    identity = {
        "schema_version": SCHEMA_VERSION,
        "stage": "races_discovery",
        "year": year,
        "shard_index": 0,
        "shard_count": 1,
        "manifest_sha256": "discovery:"
        + sha256_bytes(canonical_json_bytes(discovery_manifest)),
        "region_manifest_sha256": region_manifest_sha256,
        "tool_identity": tool_identity,
    }
    return RequestLedger(
        root / "stages" / "races" / "discovery_request_ledger.json",
        identity=identity,
        request_budget=request_budget,
    )


def run_stage(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    if args.stage == "synthetic_smoke":
        report = run_synthetic_smoke(
            root, year=args.year, stop_after=1 if args.limit else 0
        )
        atomic_write_json(root / "synthetic_smoke_report.json", report)
        return int(report.get("exit_code", 0))
    worktree_root = Path(__file__).resolve().parents[2]
    selected_base_url = validate_request_url(args.base_url)
    region_manifest, region_manifest_sha = _region_manifest_binding(
        args.race_region_manifest,
        year=args.year,
        worktree_root=worktree_root,
        expected_scheme=urlparse(selected_base_url).scheme,
    )
    manifest_path = root / "run_manifest.json"
    stage_deadline = StageDeadline.from_budget(args.time_budget_seconds)
    client: HttpClient | None = None
    if args.stage == "races":
        discovery_count = 0
        if manifest_path.exists():
            manifest = validate_run_manifest(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                year=args.year,
                region_manifest_sha256=region_manifest_sha,
                expected_base_url=selected_base_url,
            )
            discovery_ledger = _discovery_request_ledger(
                root,
                year=args.year,
                base_url=manifest["base_url"],
                region_manifest_sha256=region_manifest_sha,
                request_budget=args.request_budget,
            )
            if discovery_ledger.path.exists():
                discovery_count = discovery_ledger.verify()["request_count"]
        else:
            discovery_ledger = _discovery_request_ledger(
                root,
                year=args.year,
                base_url=args.base_url,
                region_manifest_sha256=region_manifest_sha,
                request_budget=args.request_budget,
            )
            discovery_count = discovery_ledger.initialize(0)["request_count"]
            client = HttpClient(
                delay=args.delay,
                timeout=args.timeout,
                request_budget=args.request_budget,
                request_count_start=discovery_count,
                request_reserver=discovery_ledger.reserve,
                deadline=stage_deadline,
            )
            try:
                race_urls = discover_race_urls(
                    client,
                    base_url=args.base_url,
                    year=args.year,
                    progress_path=(
                        root
                        / "stages"
                        / "races"
                        / "discovery_progress.json"
                    ),
                    identity=_discovery_progress_identity(
                        year=args.year,
                        base_url=args.base_url,
                        region_manifest_sha256=region_manifest_sha,
                        request_budget=args.request_budget,
                    ),
                    resume=args.resume,
                    deadline=stage_deadline,
                )
            except (RequestBudgetExceeded, RetryableHttpError):
                return SAFE_STOP_EXIT_CODE
            if not race_urls:
                raise ValueError("no trustworthy race URLs were discovered")
            discovery_count = client.request_count
            manifest = _new_run_manifest(
                year=args.year,
                base_url=args.base_url,
                race_urls=race_urls,
                region_manifest_sha256=region_manifest_sha,
                created_at=utc_now_iso(),
            )
            atomic_write_json(manifest_path, manifest)
            validate_run_manifest(
                manifest,
                year=args.year,
                region_manifest_sha256=region_manifest_sha,
                expected_base_url=selected_base_url,
            )
        manifest_sha = sha256_bytes(manifest_path.read_bytes())
        tool_identity = {
            key: manifest[key] for key in current_tool_identity_record()
        }
        store = _bound_store(
            root,
            stage="races",
            year=args.year,
            manifest_sha256=manifest_sha,
            region_manifest_sha256=region_manifest_sha,
            shard_index=0,
            shard_count=1,
            upstream_indexes={},
            input_keys=manifest["race_urls"],
            tool_identity=tool_identity,
            request_budget=REQUEST_BUDGETS["races"],
        )
        stage_ledger = store.request_ledger()
        stage_ledger.initialize(discovery_count)
        prior_request_count = trusted_stage_request_count(store)
        if client is None:
            client = HttpClient(
                delay=args.delay,
                timeout=args.timeout,
                request_budget=args.request_budget,
                request_count_start=prior_request_count,
                request_reserver=stage_ledger.reserve,
                deadline=stage_deadline,
            )
        else:
            if client.request_count != prior_request_count:
                raise ValueError(
                    "race discovery conflicts with existing request checkpoint"
                )
            client.request_reserver = stage_ledger.reserve

        def collect_one(url: str) -> dict[str, Any]:
            try:
                response = client.get(url)
            except RetryableHttpError as exc:
                return {
                    "key": url,
                    "status": "retryable_error",
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                    "source": {
                        "url": url,
                        "region": "",
                        "country": "",
                        "status": "transport_retryable",
                    },
                }
            except PermanentHttpError as exc:
                return {
                    "key": url,
                    "status": "permanent_error",
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                    "source": {
                        "url": url,
                        "region": "",
                        "country": "",
                        "status": "transport_permanent",
                    },
                }
            try:
                parsed = parse_race_html(
                    response.content,
                    url=response.url,
                    year=args.year,
                    region_manifest=region_manifest,
                )
            except ValueError as exc:
                return {
                    "key": url,
                    "status": "permanent_error",
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                    "source": {
                        "url": response.url,
                        "http_status": response.status_code,
                        "sha256": sha256_bytes(response.content),
                        "region": "",
                        "country": "",
                        "region_label": "",
                        "race_date": "",
                        "race_name_zh": "",
                        "grade": "",
                        "status": "parse_error",
                        "fetched_at": utc_now_iso(),
                    },
                }
            parsed["key"] = url
            source = dict(parsed["source"])
            for field in (
                "result_rows_with_horse",
                "non_starters_excluded",
                "participant_status_unresolved",
                "duplicate_result_rows",
            ):
                source[field] = int(parsed.get(field, 0))
            parsed["source"] = source
            return parsed

        progress = run_checkpointed_items(
            manifest["race_urls"],
            store=store,
            process=collect_one,
            resume=args.resume,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
            request_counter_start=prior_request_count,
            deadline=stage_deadline,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    if not manifest_path.exists():
        raise ValueError("run_manifest.json is required; run races first")
    manifest = validate_run_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        year=args.year,
        region_manifest_sha256=region_manifest_sha,
        expected_base_url=selected_base_url,
    )
    manifest_sha = sha256_bytes(manifest_path.read_bytes())
    tool_identity = {key: manifest[key] for key in current_tool_identity_record()}
    race_store = _bound_store(
        root,
        stage="races",
        year=args.year,
        manifest_sha256=manifest_sha,
        region_manifest_sha256=region_manifest_sha,
        shard_index=0,
        shard_count=1,
        upstream_indexes={},
        input_keys=manifest["race_urls"],
        tool_identity=tool_identity,
        request_budget=REQUEST_BUDGETS["races"],
    )
    _ensure_complete_progress(race_store)
    race_records = load_store_records(race_store)
    occurrences = _race_occurrences(race_records)
    has_coverage_gap = any(
        normalize_space(item.get("status")) == "evidence_gap"
        or (
            normalize_space(item.get("status")) == "skipped"
            and normalize_space(item.get("skip_reason"))
            == "region_unresolved"
        )
        for item in race_records
    )
    verified_empty_scope = bool(race_records) and all(
        normalize_space(item.get("status")) == "skipped"
        and normalize_space(item.get("skip_reason"))
        in {"grade_out_of_scope", "out_of_scope"}
        for item in race_records
    )
    if not occurrences and not has_coverage_gap and not verified_empty_scope:
        raise ValueError("no trustworthy in-scope participant occurrences")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in occurrences:
        grouped[canonical_horse_key(row)].append(row)
    races_sha = index_sha256(race_store)

    if args.stage == "profiles":
        if args.shard_count != PROFILE_SHARD_COUNT:
            raise ValueError("profiles require exactly four shards")
        owned_keys = [
            key
            for key in grouped
            if stable_shard(key, PROFILE_SHARD_COUNT) == args.shard_index
        ]
        store = _bound_store(
            root,
            stage="profiles",
            year=args.year,
            manifest_sha256=manifest_sha,
            region_manifest_sha256=region_manifest_sha,
            shard_index=args.shard_index,
            shard_count=PROFILE_SHARD_COUNT,
            upstream_indexes={"races": races_sha},
            input_keys=owned_keys,
            tool_identity=tool_identity,
            request_budget=REQUEST_BUDGETS["profiles"],
        )
        prior_request_count = trusted_stage_request_count(store)
        client = HttpClient(
            delay=args.delay,
            timeout=args.timeout,
            request_budget=args.request_budget,
            request_count_start=prior_request_count,
            request_reserver=store.request_ledger().reserve,
            deadline=stage_deadline,
        )

        def collect_profile(key: str) -> dict[str, Any]:
            try:
                profile = fetch_profile(
                    client,
                    base_url=manifest["base_url"],
                    occurrences=grouped[key],
                )
                state = profile["resolution_state"]
                status = "not_found" if state == "not_found" else "success"
                error_code = ""
            except RequestBudgetExceeded:
                raise
            except RetryableHttpError as exc:
                profile = {"resolution_state": "error"}
                status = "retryable_error"
                error_code = type(exc).__name__
                error = str(exc)
            except PermanentHttpError as exc:
                profile = {"resolution_state": "error"}
                status = "permanent_error"
                error_code = type(exc).__name__
                error = str(exc)
            except ValueError as exc:
                profile = {"resolution_state": "error"}
                status = "permanent_error"
                error_code = type(exc).__name__
                error = str(exc)
            except Exception as exc:
                profile = {"resolution_state": "error"}
                status = "retryable_error"
                error_code = type(exc).__name__
                error = str(exc)
            record = {
                "key": key,
                "lookup_keys": [key],
                **profile,
                "status": status,
                "error_code": error_code,
            }
            if status in {"retryable_error", "permanent_error"}:
                record["error"] = error
            return record

        progress = run_checkpointed_items(
            grouped,
            store=store,
            process=collect_profile,
            resume=args.resume,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
            request_counter_start=prior_request_count,
            deadline=stage_deadline,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    profile_records: list[dict[str, Any]] = []
    profile_stores: list[StageStore] = []
    profile_upstreams: dict[str, str] = {"races": races_sha}
    for shard in range(PROFILE_SHARD_COUNT):
        owned_keys = [
            key
            for key in grouped
            if stable_shard(key, PROFILE_SHARD_COUNT) == shard
        ]
        store = _bound_store(
            root,
            stage="profiles",
            year=args.year,
            manifest_sha256=manifest_sha,
            region_manifest_sha256=region_manifest_sha,
            shard_index=shard,
            shard_count=PROFILE_SHARD_COUNT,
            upstream_indexes={"races": races_sha},
            input_keys=owned_keys,
            tool_identity=tool_identity,
            request_budget=REQUEST_BUDGETS["profiles"],
        )
        _ensure_complete_progress(store)
        profile_stores.append(store)
        profile_records.extend(load_store_records(store))
        profile_upstreams[f"profiles:{shard}"] = index_sha256(store)

    if args.stage == "merge_profiles":
        merged = merge_profile_records(profile_records, grouped)
        store = _bound_store(
            root,
            stage="profiles_merged",
            year=args.year,
            manifest_sha256=manifest_sha,
            region_manifest_sha256=region_manifest_sha,
            shard_index=None,
            shard_count=1,
            upstream_indexes=profile_upstreams,
            input_keys=grouped,
            tool_identity=tool_identity,
        )
        if store.index_path.exists():
            store.verify_index()
            existing = load_store_records(store)
            if canonical_json_bytes(existing) != canonical_json_bytes(merged):
                raise ValueError("merged profile content drift")
            return 0
        for record in merged:
            store.save_item(record["key"], record)
        store.rebuild_index(
            request_count=sum(
                item.verify_index()["request_count"] for item in profile_stores
            )
        )
        return 0

    merged_probe_path = root / "stages" / "profiles" / "merged" / "index.json"
    if not merged_probe_path.exists():
        raise ValueError("merged profiles index is required")
    merged_store = _bound_store(
        root,
        stage="profiles_merged",
        year=args.year,
        manifest_sha256=manifest_sha,
        region_manifest_sha256=region_manifest_sha,
        shard_index=None,
        shard_count=1,
        upstream_indexes=profile_upstreams,
        input_keys=grouped,
        tool_identity=tool_identity,
    )
    merged_profiles = load_store_records(merged_store)
    expected_merged = merge_profile_records(profile_records, grouped)
    if canonical_json_bytes(merged_profiles) != canonical_json_bytes(expected_merged):
        raise ValueError("finalize merged profile fan-in drift")
    source_manifest = []
    for item in race_records:
        if item.get("source"):
            source_manifest.append(dict(item["source"]))
        else:
            source_manifest.append(
                {
                    "url": normalize_space(item.get("key")),
                    "http_status": None,
                    "sha256": "",
                    "region": "",
                    "country": "",
                    "region_label": "",
                    "race_date": "",
                    "race_name_zh": "",
                    "grade": "",
                    "status": normalize_space(item.get("status")),
                    "fetched_at": manifest["created_at"],
                    "non_starters_excluded": 0,
                    "participant_status_unresolved": 0,
                    "error_code": normalize_space(item.get("error_code")),
                }
            )
    discovered_other_urls = {
        item["url"]
        for item in source_manifest
        if item.get("region_label") == "其他"
    }
    other_coverage = classify_other_coverage(
        year=args.year,
        discovered_other_urls=discovered_other_urls,
        manifest=region_manifest,
        in_scope_urls={
            normalize_space(item.get("race_url"))
            for item in occurrences
            if normalize_space(item.get("region"))
            in {"australia", "germany", "middle_east"}
            and normalize_space(item.get("race_url"))
        },
    )
    errors = _structured_errors(
        [("races", race_records), ("profiles", profile_records)]
    )
    finalize_artifacts(
        output_dir=root / "final",
        year=args.year,
        occurrences=occurrences,
        profiles=merged_profiles,
        source_manifest=source_manifest,
        errors=errors,
        other_coverage=other_coverage,
        request_count=race_store.verify_index()["request_count"]
        + merged_store.verify_index()["request_count"],
        generated_at=manifest["created_at"],
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    return run_stage(args)


if __name__ == "__main__":
    raise SystemExit(main())
