#!/usr/bin/env python3
"""Collect 2026 graded-race top-five finishers from UmaFans public pages.

This is a read-only research utility. It does not import Django models and does
not write to the UmaFans database. The collector:

1. discovers published race pages through the public sitemap;
2. keeps completed 2026 graded races in Japan, Hong Kong, the United States,
   the United Kingdom and France;
3. extracts official positions 1-5 from the public result tables;
4. enriches horse names from public horse-profile search pages;
5. resolves likely Wikipedia/Wikidata identities with explicit confidence
   states instead of forcing an uncertain match;
6. writes auditable CSV/JSON artifacts.

The output represents the current public, data-quality-complete UmaFans race
pages at collection time. It must not be described as proof that every race in
an external global catalog is present.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("graded-top5-wikipedia")

REGION_LABELS = {
    "日本": "japan",
    "中国香港": "hong_kong",
    "香港": "hong_kong",
    "美国": "united_states",
    "英国": "united_kingdom",
    "法国": "france",
}
REGION_OUTPUT = {
    "japan": "日本",
    "hong_kong": "中国香港",
    "united_states": "美国",
    "united_kingdom": "英国",
    "france": "法国",
}
TARGET_REGIONS = set(REGION_OUTPUT)
TARGET_STANDARD_GRADES = {"G1", "G2", "G3"}
TARGET_JAPAN_GRADES = {
    "G1",
    "G2",
    "G3",
    "J-G1",
    "J-G2",
    "J-G3",
    "JPN1",
    "JPN2",
    "JPN3",
}
WIKI_LANG_PRIORITY = ("zh", "ja", "en", "fr")
WIKI_SITE_KEYS = {"zh": "zhwiki", "ja": "jawiki", "en": "enwiki", "fr": "frwiki"}
HORSE_DESCRIPTION_KEYWORDS = (
    "racehorse",
    "race horse",
    "thoroughbred",
    "競走馬",
    "赛马",
    "賽馬",
    "cheval de course",
    "pur-sang",
)
COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
POSITION_RE = re.compile(r"^\s*(\d+)")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
LATIN_RE = re.compile(r"[A-Za-z]")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return " ".join(value.replace("\u3000", " ").split())


def normalize_identity(value: str) -> str:
    value = normalize_space(value).casefold()
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", value)


def strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", normalize_space(value)).strip()


def contains_han(value: str) -> bool:
    return bool(HAN_RE.search(value or ""))


def contains_kana(value: str) -> bool:
    return bool(KANA_RE.search(value or ""))


def contains_latin(value: str) -> bool:
    return bool(LATIN_RE.search(value or ""))


def normalize_grade(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").upper().strip()
    replacements = {
        "Ⅰ": "1",
        "Ⅱ": "2",
        "Ⅲ": "3",
        "I": "1",
        "II": "2",
        "III": "3",
        "・": "-",
        "—": "-",
        "–": "-",
        "−": "-",
    }
    # Replace the longer Roman forms first before replacing standalone I.
    for source, target in (("III", "3"), ("II", "2"), ("Ⅰ", "1"), ("Ⅱ", "2"), ("Ⅲ", "3")):
        value = value.replace(source, target)
    value = value.replace("・", "-").replace("—", "-").replace("–", "-").replace("−", "-")
    value = re.sub(r"\bGRADE\s*", "G", value)
    value = re.sub(r"\bGROUP\s*", "G", value)
    value = re.sub(r"\s+", "", value)
    value = value.replace("JPNⅠ", "JPN1").replace("JPNⅡ", "JPN2").replace("JPNⅢ", "JPN3")
    value = value.replace("JPNI", "JPN1").replace("JPNII", "JPN2").replace("JPNIII", "JPN3")
    value = value.replace("JG1", "J-G1").replace("JG2", "J-G2").replace("JG3", "J-G3")
    value = value.replace("J-GRADE", "J-G")
    match = re.search(r"JPN[- ]?([123])", value)
    if match:
        return f"JPN{match.group(1)}"
    match = re.search(r"J-?G([123])", value)
    if match:
        return f"J-G{match.group(1)}"
    match = re.search(r"(?:^|[^A-Z])G([123])(?:$|[^0-9])", value)
    if match:
        return f"G{match.group(1)}"
    return value


def grade_is_in_scope(region: str, grade: str) -> bool:
    normalized = normalize_grade(grade)
    if region == "japan":
        return normalized in TARGET_JAPAN_GRADES
    return normalized in TARGET_STANDARD_GRADES


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value or "item"


def wiki_url(language: str, title: str) -> str:
    return f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='():,_-')}"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def unique_preserve(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = normalize_space(value)
        identity = normalize_identity(cleaned)
        if not cleaned or not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(cleaned)
    return result


class HttpClient:
    def __init__(self, *, delay: float, timeout: float, user_agent: str):
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=0.8,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.7,en;q=0.6",
            }
        )
        self.request_count = 0

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        response = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=True)
        self.request_count += 1
        response.raise_for_status()
        if self.delay:
            time.sleep(self.delay)
        return response


@dataclass
class RaceResultRow:
    region: str
    region_label: str
    race_date: str
    race_name_zh: str
    race_name_original: str
    grade: str
    racecourse: str
    finish_position: int
    horse_display_name: str
    jockey_name: str
    trainer_name: str
    finish_time: str
    margin: str
    race_url: str
    race_page_sha256: str
    horse_lookup_key: str = ""
    horse_profile_url: str = ""
    horse_original_name: str = ""
    horse_birth_year: str = ""
    horse_name_zh: str = ""
    horse_name_ja: str = ""
    horse_name_en: str = ""
    wikidata_id: str = ""
    wikipedia_url: str = ""
    wikipedia_language: str = ""
    wikipedia_title: str = ""
    zh_wikipedia_url: str = ""
    ja_wikipedia_url: str = ""
    en_wikipedia_url: str = ""
    fr_wikipedia_url: str = ""
    wikipedia_match_status: str = ""
    wikipedia_match_score: str = ""
    wikipedia_match_evidence: str = ""


@dataclass
class HorseSeed:
    key: str
    regions: set[str] = field(default_factory=set)
    display_names: set[str] = field(default_factory=set)
    original_names: set[str] = field(default_factory=set)
    profile_urls: set[str] = field(default_factory=set)
    birth_years: set[str] = field(default_factory=set)
    name_zh: str = ""
    name_ja: str = ""
    name_en: str = ""
    race_contexts: list[str] = field(default_factory=list)
    candidate_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    wikidata_id: str = ""
    wikipedia_url: str = ""
    wikipedia_language: str = ""
    wikipedia_title: str = ""
    wiki_urls: dict[str, str] = field(default_factory=dict)
    match_status: str = "no_page"
    match_score: int = 0
    match_evidence: str = ""
    alternative_candidates: list[str] = field(default_factory=list)


class UmaFansCollector:
    def __init__(self, *, base_url: str, client: HttpClient, output_dir: Path, year: int, cutoff: date):
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.output_dir = output_dir
        self.year = year
        self.cutoff = cutoff
        self.errors: list[dict[str, str]] = []
        self.source_manifest: list[dict[str, Any]] = []

    def _record_error(self, stage: str, url: str, exc: Exception) -> None:
        LOGGER.warning("%s failed for %s: %s", stage, url, exc)
        self.errors.append({"stage": stage, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    def _get_xml_locs(self, url: str) -> list[str]:
        response = self.client.get(url)
        root = ET.fromstring(response.content)
        return [normalize_space(node.text or "") for node in root.findall(".//{*}loc") if node.text]

    def discover_race_urls(self) -> list[str]:
        candidates = [f"{self.base_url}/sitemap.xml"]
        last_error: Exception | None = None
        shard_urls: list[str] = []
        for sitemap_url in candidates:
            try:
                shard_urls = self._get_xml_locs(sitemap_url)
                if shard_urls:
                    break
            except Exception as exc:  # pragma: no cover - live-network branch
                last_error = exc
                self._record_error("sitemap_index", sitemap_url, exc)
        if not shard_urls:
            raise RuntimeError(f"Unable to read UmaFans sitemap: {last_error}")

        race_urls: list[str] = []
        for shard_url in shard_urls:
            try:
                for loc in self._get_xml_locs(shard_url):
                    if f"/races/{self.year}/" in loc:
                        race_urls.append(loc)
            except Exception as exc:
                self._record_error("sitemap_shard", shard_url, exc)
        race_urls = unique_preserve(race_urls)
        LOGGER.info("Discovered %s race URLs for %s", len(race_urls), self.year)
        return race_urls

    @staticmethod
    def _meta_grid(soup: BeautifulSoup) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for item in soup.select("#overview .race-meta-grid > div"):
            label_node = item.find("span")
            value_node = item.find("b")
            if label_node and value_node:
                metadata[normalize_space(label_node.get_text(" ", strip=True))] = normalize_space(
                    value_node.get_text(" ", strip=True)
                )
        return metadata

    @staticmethod
    def _region_from_page(soup: BeautifulSoup) -> tuple[str, str]:
        node = soup.select_one(".race-hero-meta-text")
        text = normalize_space(node.get_text(" ", strip=True)) if node else ""
        label = text.split("·", 1)[0].strip()
        return REGION_LABELS.get(label, ""), label

    @staticmethod
    def _race_original_name(soup: BeautifulSoup) -> str:
        node = soup.select_one(".race-hero-original")
        text = normalize_space(node.get_text(" ", strip=True)) if node else ""
        match = DATE_RE.search(text)
        if match:
            return text[: match.start()].strip(" ·")
        return text.strip(" ·")

    def parse_race_page(self, url: str) -> list[RaceResultRow]:
        response = self.client.get(url)
        body = response.content
        soup = BeautifulSoup(body, "html.parser")
        if soup.select_one("main.race-page") is None:
            raise RuntimeError("public race page marker missing")
        metadata = self._meta_grid(soup)
        region, region_label = self._region_from_page(soup)
        race_name_node = soup.select_one(".race-hero-name")
        race_name_zh = normalize_space(race_name_node.get_text(" ", strip=True)) if race_name_node else ""
        race_name_original = self._race_original_name(soup)
        grade_node = soup.select_one(".grade-badge")
        grade_raw = metadata.get("等级") or (
            normalize_space(grade_node.get_text(" ", strip=True)) if grade_node else ""
        )
        grade = normalize_grade(grade_raw)
        race_date = metadata.get("日期", "")
        racecourse = metadata.get("马场", "")
        status = metadata.get("状态", "")

        manifest_entry = {
            "url": response.url,
            "requested_url": url,
            "http_status": response.status_code,
            "sha256": sha256_bytes(body),
            "region": region,
            "race_date": race_date,
            "race_name_zh": race_name_zh,
            "grade": grade,
            "status": status,
            "fetched_at": utc_now_iso(),
        }
        self.source_manifest.append(manifest_entry)

        if region not in TARGET_REGIONS:
            return []
        if status != "已完赛":
            return []
        try:
            race_date_value = date.fromisoformat(race_date)
        except ValueError:
            raise RuntimeError(f"completed race has invalid date: {race_date!r}")
        if race_date_value.year != self.year or race_date_value > self.cutoff:
            return []
        if not grade_is_in_scope(region, grade):
            return []

        section = soup.select_one("section#results")
        if section is None:
            raise RuntimeError("completed in-scope race has no result section")
        rows: list[RaceResultRow] = []
        for tr in section.select("tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 8:
                continue
            position_text = normalize_space(cells[0].get_text(" ", strip=True))
            match = POSITION_RE.match(position_text)
            if not match:
                continue
            position = int(match.group(1))
            if not 1 <= position <= 5:
                continue
            horse_name = normalize_space(cells[2].get_text(" ", strip=True))
            if not horse_name:
                continue
            rows.append(
                RaceResultRow(
                    region=region,
                    region_label=REGION_OUTPUT[region],
                    race_date=race_date,
                    race_name_zh=race_name_zh,
                    race_name_original=race_name_original,
                    grade=grade,
                    racecourse=racecourse,
                    finish_position=position,
                    horse_display_name=horse_name,
                    jockey_name=normalize_space(cells[3].get_text(" ", strip=True)),
                    trainer_name=normalize_space(cells[4].get_text(" ", strip=True)),
                    finish_time=normalize_space(cells[5].get_text(" ", strip=True)),
                    margin=normalize_space(cells[6].get_text(" ", strip=True)),
                    race_url=response.url,
                    race_page_sha256=manifest_entry["sha256"],
                )
            )
        if not rows:
            raise RuntimeError("completed in-scope race has no numeric top-five rows")
        return rows

    def collect_races(self, *, max_races: int = 0) -> tuple[list[RaceResultRow], int]:
        race_urls = self.discover_race_urls()
        if max_races:
            race_urls = race_urls[:max_races]
        result_rows: list[RaceResultRow] = []
        included_race_urls: set[str] = set()
        for index, url in enumerate(race_urls, start=1):
            if index == 1 or index % 50 == 0:
                LOGGER.info("Race pages %s/%s; included races=%s", index, len(race_urls), len(included_race_urls))
            try:
                page_rows = self.parse_race_page(url)
                if page_rows:
                    included_race_urls.add(page_rows[0].race_url)
                    result_rows.extend(page_rows)
            except Exception as exc:
                self._record_error("race_page", url, exc)
        return result_rows, len(included_race_urls)

    def find_horse_profile(self, display_name: str, region: str) -> dict[str, str]:
        search_url = f"{self.base_url}/horses/"
        response = self.client.get(search_url, params={"q": display_name})
        soup = BeautifulSoup(response.content, "html.parser")
        exact_cards = []
        for card in soup.select("article.horse-card"):
            name_node = card.select_one(".horse-card-name a")
            if not name_node:
                continue
            card_display = normalize_space(name_node.get_text(" ", strip=True))
            if normalize_identity(card_display) != normalize_identity(display_name):
                continue
            region_node = card.select_one(".region-label")
            card_region_label = normalize_space(region_node.get_text(" ", strip=True)) if region_node else ""
            card_region = REGION_LABELS.get(card_region_label, "")
            original_node = card.select_one(".horse-card-original")
            original = normalize_space(original_node.get_text(" ", strip=True)) if original_node else ""
            if original == "资料整理中":
                original = ""
            exact_cards.append(
                {
                    "display_name": card_display,
                    "original_name": original,
                    "profile_url": urljoin(response.url, name_node.get("href", "")),
                    "region": card_region,
                }
            )
        if not exact_cards:
            return {}
        region_matches = [card for card in exact_cards if card["region"] == region]
        candidates = region_matches or exact_cards
        if len(candidates) != 1:
            return {"ambiguous": "1", "candidate_count": str(len(candidates))}
        candidate = candidates[0]
        try:
            detail = self.client.get(candidate["profile_url"])
            detail_soup = BeautifulSoup(detail.content, "html.parser")
            original_node = detail_soup.select_one(".horse-hero-original")
            detail_text = normalize_space(original_node.get_text(" ", strip=True)) if original_node else ""
            year_match = YEAR_RE.search(detail_text)
            if year_match:
                candidate["birth_year"] = year_match.group(1)
            date_match = re.search(r"\s+·\s+", detail_text)
            first_part = detail_text.split(" · ", 1)[0].strip() if detail_text else ""
            if first_part and first_part != candidate["display_name"]:
                candidate["original_name"] = first_part
            candidate["profile_page_sha256"] = sha256_bytes(detail.content)
        except Exception as exc:
            self._record_error("horse_profile_detail", candidate["profile_url"], exc)
        return candidate

    def enrich_horse_profiles(self, rows: list[RaceResultRow]) -> dict[str, HorseSeed]:
        lookup_cache: dict[tuple[str, str], dict[str, str]] = {}
        horses: dict[str, HorseSeed] = {}
        for index, row in enumerate(rows, start=1):
            cache_key = (row.region, normalize_identity(row.horse_display_name))
            if cache_key not in lookup_cache:
                try:
                    lookup_cache[cache_key] = self.find_horse_profile(row.horse_display_name, row.region)
                except Exception as exc:
                    self._record_error("horse_profile_search", row.horse_display_name, exc)
                    lookup_cache[cache_key] = {}
                if len(lookup_cache) == 1 or len(lookup_cache) % 100 == 0:
                    LOGGER.info("Horse profile lookups=%s/%s rows", len(lookup_cache), len(rows))
            profile = lookup_cache[cache_key]
            profile_url = profile.get("profile_url", "")
            original_name = profile.get("original_name", "")
            birth_year = profile.get("birth_year", "")
            key = profile_url or f"{row.region}|{normalize_identity(original_name or row.horse_display_name)}"
            row.horse_lookup_key = key
            row.horse_profile_url = profile_url
            row.horse_original_name = original_name
            row.horse_birth_year = birth_year

            seed = horses.setdefault(key, HorseSeed(key=key))
            seed.regions.add(row.region)
            seed.display_names.add(row.horse_display_name)
            if original_name:
                seed.original_names.add(original_name)
            if profile_url:
                seed.profile_urls.add(profile_url)
            if birth_year:
                seed.birth_years.add(birth_year)
            context = f"{row.race_date} {row.region_label} {row.grade} {row.race_name_zh} 第{row.finish_position}名"
            if context not in seed.race_contexts:
                seed.race_contexts.append(context)

        for seed in horses.values():
            display = sorted(seed.display_names, key=lambda value: (len(value), value))[0]
            original = sorted(seed.original_names, key=lambda value: (len(value), value))[0] if seed.original_names else ""
            if contains_han(display) and not contains_kana(display):
                seed.name_zh = display
            if contains_kana(original):
                seed.name_ja = original
            elif contains_kana(display):
                seed.name_ja = display
            if original and contains_latin(original) and not contains_kana(original):
                seed.name_en = original
            elif contains_latin(display) and not contains_han(display) and not contains_kana(display):
                seed.name_en = display
        return horses


class WikidataResolver:
    def __init__(self, *, client: HttpClient, output_dir: Path):
        self.client = client
        self.output_dir = output_dir
        self.api_url = "https://www.wikidata.org/w/api.php"
        self.search_cache_path = output_dir / "wikidata_search_cache.json"
        self.search_cache: dict[str, list[dict[str, Any]]] = {}
        if self.search_cache_path.exists():
            try:
                self.search_cache = json.loads(self.search_cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.search_cache = {}

    @staticmethod
    def _query_languages(query: str) -> list[str]:
        if contains_kana(query):
            return ["ja", "en"]
        if contains_han(query) and not contains_latin(query):
            return ["zh", "ja"]
        return ["en", "ja"]

    def _search(self, query: str, language: str) -> list[dict[str, Any]]:
        cache_key = f"{language}|{normalize_space(query)}"
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]
        response = self.client.get(
            self.api_url,
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": language,
                "uselang": language,
                "type": "item",
                "limit": 8,
                "format": "json",
                "maxlag": 5,
            },
        )
        payload = response.json()
        results = payload.get("search", []) if isinstance(payload, dict) else []
        self.search_cache[cache_key] = results
        return results

    @staticmethod
    def _search_queries(seed: HorseSeed) -> list[str]:
        values = [*seed.original_names, seed.name_en, seed.name_ja, seed.name_zh, *seed.display_names]
        stripped = [strip_country_suffix(value) for value in values]
        return unique_preserve([*values, *stripped])[:4]

    def search_candidates(self, horses: dict[str, HorseSeed]) -> set[str]:
        entity_ids: set[str] = set()
        for index, seed in enumerate(horses.values(), start=1):
            for query in self._search_queries(seed):
                for language in self._query_languages(query):
                    try:
                        results = self._search(query, language)
                    except Exception as exc:
                        LOGGER.warning("Wikidata search failed for %s/%s: %s", language, query, exc)
                        continue
                    for rank, result in enumerate(results[:5], start=1):
                        entity_id = result.get("id", "")
                        if not entity_id:
                            continue
                        meta = seed.candidate_meta.setdefault(
                            entity_id,
                            {
                                "rank": rank,
                                "descriptions": set(),
                                "matched_queries": set(),
                                "search_labels": set(),
                            },
                        )
                        meta["rank"] = min(meta["rank"], rank)
                        if result.get("description"):
                            meta["descriptions"].add(normalize_space(result["description"]))
                        if result.get("label"):
                            meta["search_labels"].add(normalize_space(result["label"]))
                        meta["matched_queries"].add(query)
                        entity_ids.add(entity_id)
            if index == 1 or index % 100 == 0:
                LOGGER.info("Wikidata search %s/%s horses; candidate IDs=%s", index, len(horses), len(entity_ids))
        self.search_cache_path.write_text(
            json.dumps(self.search_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return entity_ids

    def fetch_entities(self, entity_ids: set[str]) -> dict[str, dict[str, Any]]:
        ids = sorted(entity_ids)
        entities: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            response = self.client.get(
                self.api_url,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|aliases|descriptions|sitelinks|claims",
                    "languages": "zh|ja|en|fr",
                    "format": "json",
                    "maxlag": 5,
                },
            )
            payload = response.json()
            entities.update(payload.get("entities", {}))
            LOGGER.info("Fetched Wikidata entities %s/%s", min(start + 50, len(ids)), len(ids))
        return entities

    @staticmethod
    def _entity_texts(entity: dict[str, Any], field: str) -> dict[str, list[str]]:
        output: dict[str, list[str]] = defaultdict(list)
        for language, payload in (entity.get(field) or {}).items():
            if field == "aliases":
                output[language].extend(normalize_space(item.get("value", "")) for item in payload)
            elif isinstance(payload, dict):
                output[language].append(normalize_space(payload.get("value", "")))
        return output

    @staticmethod
    def _entity_birth_year(entity: dict[str, Any]) -> str:
        for claim in (entity.get("claims") or {}).get("P569", []):
            value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
            time_value = value.get("time", "") if isinstance(value, dict) else ""
            match = re.match(r"^[+-](\d{4})-", time_value)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _sitelink_urls(entity: dict[str, Any]) -> dict[str, str]:
        urls: dict[str, str] = {}
        sitelinks = entity.get("sitelinks") or {}
        for language, site_key in WIKI_SITE_KEYS.items():
            payload = sitelinks.get(site_key)
            if not payload:
                continue
            title = normalize_space(payload.get("title", ""))
            if title:
                urls[language] = wiki_url(language, title)
        return urls

    @staticmethod
    def _candidate_score(seed: HorseSeed, entity_id: str, entity: dict[str, Any]) -> tuple[int, list[str], bool, bool]:
        meta = seed.candidate_meta[entity_id]
        labels = WikidataResolver._entity_texts(entity, "labels")
        aliases = WikidataResolver._entity_texts(entity, "aliases")
        descriptions = [
            *meta.get("descriptions", set()),
            *[value for values in WikidataResolver._entity_texts(entity, "descriptions").values() for value in values],
        ]
        description_text = " | ".join(descriptions).casefold()
        is_horse = any(keyword.casefold() in description_text for keyword in HORSE_DESCRIPTION_KEYWORDS)
        source_names = unique_preserve(
            [*seed.display_names, *seed.original_names, seed.name_zh, seed.name_ja, seed.name_en]
        )
        source_norms = {normalize_identity(value) for value in source_names if normalize_identity(value)}
        entity_names = [
            *[value for values in labels.values() for value in values],
            *[value for values in aliases.values() for value in values],
            *meta.get("search_labels", set()),
        ]
        entity_norms = {normalize_identity(value) for value in entity_names if normalize_identity(value)}
        exact_name = bool(source_norms & entity_norms)
        fuzzy_name = any(
            source in target or target in source
            for source in source_norms
            for target in entity_norms
            if min(len(source), len(target)) >= 5
        )
        score = max(0, 10 - int(meta.get("rank", 10)))
        evidence = [f"rank={meta.get('rank', '')}"]
        if is_horse:
            score += 55
            evidence.append("horse_description")
        else:
            score -= 25
            evidence.append("no_horse_description")
        if exact_name:
            score += 45
            evidence.append("exact_multilingual_name")
        elif fuzzy_name:
            score += 16
            evidence.append("fuzzy_name")
        birth_year = WikidataResolver._entity_birth_year(entity)
        expected_years = {year for year in seed.birth_years if year}
        birth_mismatch = False
        if birth_year and expected_years:
            if birth_year in expected_years:
                score += 25
                evidence.append(f"birth_year_match={birth_year}")
            else:
                score -= 45
                birth_mismatch = True
                evidence.append(f"birth_year_mismatch={birth_year}/{','.join(sorted(expected_years))}")
        if WikidataResolver._sitelink_urls(entity):
            score += 8
            evidence.append("wikipedia_sitelink")
        return score, evidence, is_horse, exact_name and not birth_mismatch

    def resolve(self, horses: dict[str, HorseSeed]) -> None:
        candidate_ids = self.search_candidates(horses)
        entities = self.fetch_entities(candidate_ids)
        for seed in horses.values():
            scored: list[tuple[int, str, list[str], bool, bool]] = []
            for entity_id in seed.candidate_meta:
                entity = entities.get(entity_id)
                if not entity or entity.get("missing") is not None:
                    continue
                score, evidence, is_horse, strong_identity = self._candidate_score(seed, entity_id, entity)
                if self._sitelink_urls(entity):
                    scored.append((score, entity_id, evidence, is_horse, strong_identity))
            scored.sort(key=lambda item: (-item[0], item[1]))
            if not scored:
                seed.match_status = "no_page"
                seed.match_evidence = "no Wikipedia-linked Wikidata candidate"
                continue
            top = scored[0]
            second = scored[1] if len(scored) > 1 else None
            ambiguous = bool(second and second[0] >= top[0] - 7 and second[3] and top[3])
            if top[0] < 35 or not top[3]:
                seed.match_status = "no_page"
                seed.match_score = top[0]
                seed.match_evidence = "; ".join(top[2])
                seed.alternative_candidates = [f"{item[1]}:{item[0]}" for item in scored[:3]]
                continue
            entity = entities[top[1]]
            urls = self._sitelink_urls(entity)
            if ambiguous:
                seed.match_status = "ambiguous"
                seed.match_score = top[0]
                seed.match_evidence = "; ".join(top[2])
                seed.alternative_candidates = [f"{item[1]}:{item[0]}" for item in scored[:5]]
                continue
            seed.wikidata_id = top[1]
            seed.wiki_urls = urls
            seed.match_score = top[0]
            seed.match_evidence = "; ".join(top[2])
            seed.match_status = "exact" if top[4] and top[0] >= 90 else "probable"
            sitelinks = entity.get("sitelinks") or {}
            for language in WIKI_LANG_PRIORITY:
                if language in urls:
                    site_payload = sitelinks.get(WIKI_SITE_KEYS[language], {})
                    seed.wikipedia_language = language
                    seed.wikipedia_title = normalize_space(site_payload.get("title", ""))
                    seed.wikipedia_url = urls[language]
                    break
            # A language-specific Wikipedia title is a safer name source than a
            # fallback Wikidata label that may simply repeat another language.
            if not seed.name_zh and "zh" in urls:
                seed.name_zh = normalize_space(sitelinks["zhwiki"].get("title", ""))
            if not seed.name_ja and "ja" in urls:
                seed.name_ja = normalize_space(sitelinks["jawiki"].get("title", ""))
            if not seed.name_en and "en" in urls:
                seed.name_en = normalize_space(sitelinks["enwiki"].get("title", ""))


def assign_horse_results(rows: list[RaceResultRow], horses: dict[str, HorseSeed]) -> None:
    for row in rows:
        seed = horses[row.horse_lookup_key]
        row.horse_name_zh = seed.name_zh
        row.horse_name_ja = seed.name_ja
        row.horse_name_en = seed.name_en
        row.wikidata_id = seed.wikidata_id
        row.wikipedia_url = seed.wikipedia_url
        row.wikipedia_language = seed.wikipedia_language
        row.wikipedia_title = seed.wikipedia_title
        row.zh_wikipedia_url = seed.wiki_urls.get("zh", "")
        row.ja_wikipedia_url = seed.wiki_urls.get("ja", "")
        row.en_wikipedia_url = seed.wiki_urls.get("en", "")
        row.fr_wikipedia_url = seed.wiki_urls.get("fr", "")
        row.wikipedia_match_status = seed.match_status
        row.wikipedia_match_score = str(seed.match_score) if seed.match_score else ""
        row.wikipedia_match_evidence = seed.match_evidence


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def write_outputs(
    *,
    output_dir: Path,
    rows: list[RaceResultRow],
    horses: dict[str, HorseSeed],
    collector: UmaFansCollector,
    included_races: int,
    base_url: str,
    cutoff: date,
    started_at: str,
    request_count: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    race_rows = [asdict(row) for row in sorted(rows, key=lambda row: (row.race_date, row.region, row.race_url, row.finish_position))]
    write_csv(output_dir / "race_top5_2026.csv", race_rows)

    occurrences: Counter[str] = Counter(row.horse_lookup_key for row in rows)
    race_counts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        race_counts[row.horse_lookup_key].add(row.race_url)
    horse_rows: list[dict[str, Any]] = []
    for seed in horses.values():
        horse_rows.append(
            {
                "horse_key": seed.key,
                "regions": "|".join(REGION_OUTPUT.get(region, region) for region in sorted(seed.regions)),
                "horse_name_zh": seed.name_zh,
                "horse_name_ja": seed.name_ja,
                "horse_name_en": seed.name_en,
                "display_names": "|".join(sorted(seed.display_names)),
                "original_names": "|".join(sorted(seed.original_names)),
                "birth_year": "|".join(sorted(seed.birth_years)),
                "profile_urls": "|".join(sorted(seed.profile_urls)),
                "wikidata_id": seed.wikidata_id,
                "wikipedia_url": seed.wikipedia_url,
                "wikipedia_language": seed.wikipedia_language,
                "wikipedia_title": seed.wikipedia_title,
                "zh_wikipedia_url": seed.wiki_urls.get("zh", ""),
                "ja_wikipedia_url": seed.wiki_urls.get("ja", ""),
                "en_wikipedia_url": seed.wiki_urls.get("en", ""),
                "fr_wikipedia_url": seed.wiki_urls.get("fr", ""),
                "match_status": seed.match_status,
                "match_score": seed.match_score,
                "match_evidence": seed.match_evidence,
                "alternative_candidates": "|".join(seed.alternative_candidates),
                "graded_race_count": len(race_counts[seed.key]),
                "top5_occurrences": occurrences[seed.key],
                "race_context": " || ".join(sorted(seed.race_contexts)),
            }
        )
    horse_rows.sort(
        key=lambda item: (
            {"exact": 0, "probable": 1, "ambiguous": 2, "no_page": 3}.get(item["match_status"], 9),
            item["horse_name_zh"] or item["horse_name_ja"] or item["horse_name_en"] or item["display_names"],
        )
    )
    write_csv(output_dir / "horse_wikipedia_mapping_2026.csv", horse_rows)
    review_rows = [row for row in horse_rows if row["match_status"] in {"ambiguous", "no_page", "probable"}]
    write_csv(output_dir / "wikipedia_review_queue_2026.csv", review_rows, list(horse_rows[0].keys()) if horse_rows else [])

    with (output_dir / "source_manifest.jsonl").open("w", encoding="utf-8") as handle:
        for item in collector.source_manifest:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    (output_dir / "errors.json").write_text(
        json.dumps(collector.errors, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    region_races: dict[str, set[str]] = defaultdict(set)
    grade_races: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        region_races[row.region].add(row.race_url)
        grade_races[f"{row.region}:{row.grade}"].add(row.race_url)
    summary = {
        "artifact_type": "umafans_2026_graded_top5_wikipedia_mapping",
        "scope": {
            "year": 2026,
            "cutoff_inclusive": cutoff.isoformat(),
            "regions": [REGION_OUTPUT[key] for key in ("japan", "hong_kong", "united_states", "united_kingdom", "france")],
            "japan_grades": sorted(TARGET_JAPAN_GRADES),
            "other_region_grades": sorted(TARGET_STANDARD_GRADES),
            "finish_positions": [1, 2, 3, 4, 5],
            "coverage_basis": "UmaFans current public data-quality-complete race sitemap and public result pages",
            "completeness_warning": "This artifact does not independently prove that every externally catalogued 2026 graded race is present in UmaFans.",
        },
        "source": {
            "base_url": base_url,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "http_request_count": request_count,
            "race_pages_fetched": len(collector.source_manifest),
            "race_page_errors": len([item for item in collector.errors if item["stage"] == "race_page"]),
            "all_errors": len(collector.errors),
        },
        "counts": {
            "included_races": included_races,
            "top5_rows": len(rows),
            "unique_horse_seeds": len(horses),
            "races_by_region": {REGION_OUTPUT[key]: len(value) for key, value in sorted(region_races.items())},
            "races_by_region_grade": {key: len(value) for key, value in sorted(grade_races.items())},
            "wikipedia_status": dict(Counter(seed.match_status for seed in horses.values())),
        },
        "files": [
            "race_top5_2026.csv",
            "horse_wikipedia_mapping_2026.csv",
            "wikipedia_review_queue_2026.csv",
            "source_manifest.jsonl",
            "errors.json",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    readme = f"""# 2026 重赏入版马与 Wikipedia 对应关系\n\n- 生成时间：{summary['source']['completed_at']}\n- 截止日期（含）：{cutoff.isoformat()}\n- 数据范围：日本（JRA G1/G2/G3、J-G1/J-G2/J-G3；NAR Jpn1/Jpn2/Jpn3）、中国香港、美国、英国、法国 G1/G2/G3。\n- 名次：正式赛果第 1—5 名。\n- 数据基线：UmaFans 当前公开且 data-quality-complete 的赛事页。\n- Wikipedia：优先中文，其次日文、英文、法文；不确定匹配不会强行写入。\n\n## 文件\n\n- `race_top5_2026.csv`：赛事—名次级明细。\n- `horse_wikipedia_mapping_2026.csv`：马匹去重映射。\n- `wikipedia_review_queue_2026.csv`：`probable`、`ambiguous`、`no_page` 人工复核队列。\n- `source_manifest.jsonl`：赛事页 URL、抓取时间与 SHA-256。\n- `summary.json`：范围、计数和覆盖声明。\n- `errors.json`：抓取或解析错误。\n\n## 匹配状态\n\n- `exact`：Wikidata 描述为赛马，跨语言名称精确匹配，且无出生年份冲突。\n- `probable`：高概率为同一匹马，但证据未达到 exact 门槛。\n- `ambiguous`：存在分数接近的多个赛马候选，未自动选择。\n- `no_page`：未找到足够可信且带 Wikipedia sitelink 的候选。\n\n注意：该结果覆盖的是 UmaFans 当前公开完整赛事页，不是对外部全球赛事目录的独立全量证明。\n"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return summary


def resolve_base_url(client: HttpClient, requested: str) -> str:
    requested = requested.rstrip("/")
    parsed = urlparse(requested)
    candidates = [requested]
    if parsed.scheme == "https":
        candidates.append(urlunparse(("http", parsed.netloc, parsed.path, "", "", "")).rstrip("/"))
    elif parsed.scheme == "http":
        candidates.insert(0, urlunparse(("https", parsed.netloc, parsed.path, "", "", "")).rstrip("/"))
    for candidate in unique_preserve(candidates):
        try:
            response = client.get(f"{candidate}/sitemap.xml")
            if response.status_code == 200 and b"sitemap" in response.content.lower():
                return candidate
        except Exception as exc:
            LOGGER.warning("Base URL probe failed for %s: %s", candidate, exc)
    raise RuntimeError(f"No reachable UmaFans base URL among {candidates}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://umafans.run")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--cutoff", default="2026-07-26", help="Inclusive YYYY-MM-DD cutoff")
    parser.add_argument("--output-dir", default="runtime/research/output/2026-graded-top5-wikipedia")
    parser.add_argument("--delay", type=float, default=0.12, help="Delay after every HTTP response")
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--max-races", type=int, default=0, help="Debug limit after sitemap discovery")
    parser.add_argument("--skip-wikipedia", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.year != 2026:
        raise SystemExit("This research artifact is intentionally scoped to 2026")
    cutoff = date.fromisoformat(args.cutoff)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now_iso()
    client = HttpClient(
        delay=args.delay,
        timeout=args.timeout,
        user_agent="UmaFansResearch/1.0 (2026 graded top-five Wikipedia mapping; non-commercial research)",
    )
    base_url = resolve_base_url(client, args.base_url)
    LOGGER.info("Using UmaFans base URL %s", base_url)
    collector = UmaFansCollector(
        base_url=base_url,
        client=client,
        output_dir=output_dir,
        year=args.year,
        cutoff=cutoff,
    )
    rows, included_races = collector.collect_races(max_races=args.max_races)
    if not rows:
        (output_dir / "errors.json").write_text(
            json.dumps(collector.errors, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError("No in-scope top-five rows were collected")
    LOGGER.info("Collected %s top-five rows from %s races", len(rows), included_races)
    horses = collector.enrich_horse_profiles(rows)
    LOGGER.info("Built %s horse identity seeds", len(horses))
    if not args.skip_wikipedia:
        resolver = WikidataResolver(client=client, output_dir=output_dir)
        resolver.resolve(horses)
    else:
        for seed in horses.values():
            seed.match_status = "not_run"
            seed.match_evidence = "Wikipedia resolution skipped"
    assign_horse_results(rows, horses)
    summary = write_outputs(
        output_dir=output_dir,
        rows=rows,
        horses=horses,
        collector=collector,
        included_races=included_races,
        base_url=base_url,
        cutoff=cutoff,
        started_at=started_at,
        request_count=client.request_count,
    )
    LOGGER.info("Summary: %s", json.dumps(summary["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
