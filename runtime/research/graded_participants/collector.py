from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import (
    DATE_RE, ENGLISH_OPTIONAL_REGIONS, REGION_LABELS, REGION_OUTPUT,
    TARGET_REGIONS, UMAFANS_HOSTS, YEAR_RE, HorseSeed, ParticipantRow,
    classify_region, grade_is_in_scope, infer_names, normalize_grade,
    normalize_identity, normalize_result_status, normalize_space, sha256_bytes,
    unique_preserve, utc_now_iso, validate_request_url,
)

LOGGER = logging.getLogger("graded-race-participants")


class HttpClient:
    def __init__(self, *, delay: float, timeout: float, user_agent: str):
        self.delay = max(0.0, delay); self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=5, connect=5, read=5, status=5, backoff_factor=0.8,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}), respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("http://", adapter); self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.7,en;q=0.6",
        })
        self.request_count = 0

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        current = validate_request_url(url); response: requests.Response | None = None
        for redirect_index in range(6):
            response = self.session.get(
                current, params=params if redirect_index == 0 else None,
                timeout=self.timeout, allow_redirects=False,
            )
            self.request_count += 1
            if response.status_code not in {301, 302, 303, 307, 308}: break
            location = response.headers.get("Location")
            if not location: raise RuntimeError("redirect response has no Location")
            current = validate_request_url(urljoin(current, location))
        else: raise RuntimeError("too many redirects")
        assert response is not None; response.raise_for_status()
        if self.delay: time.sleep(self.delay)
        return response


def resolve_base_url(client: HttpClient, requested: str) -> str:
    requested = requested.rstrip("/"); parsed = urlparse(requested); candidates = [requested]
    if parsed.scheme == "https":
        candidates.append(urlunparse(("http", parsed.netloc, parsed.path, "", "", "")).rstrip("/"))
    for candidate in unique_preserve(candidates):
        try:
            response = client.get(f"{candidate}/sitemap.xml")
            if response.status_code == 200 and b"sitemap" in response.content.lower(): return candidate
        except Exception as exc: LOGGER.warning("Base URL probe failed for %s: %s", candidate, exc)
    raise RuntimeError("UmaFans base URL is unreachable")


class Collector:
    def __init__(self, *, base_url: str, client: HttpClient, year: int, cutoff: date,
                 region_overrides: dict[str, dict[str, str]]):
        self.base_url = base_url.rstrip("/"); self.client = client
        self.year = year; self.cutoff = cutoff; self.region_overrides = region_overrides

    def xml_locs(self, url: str) -> list[str]:
        response = self.client.get(url); root = ET.fromstring(response.content)
        return [normalize_space(node.text or "") for node in root.findall(".//{*}loc") if node.text]

    def discover_race_urls(self) -> list[str]:
        top = self.xml_locs(f"{self.base_url}/sitemap.xml"); race_urls: list[str] = []
        for loc in top:
            if f"/races/{self.year}/" in loc: race_urls.append(loc); continue
            try: race_urls.extend(item for item in self.xml_locs(loc) if f"/races/{self.year}/" in item)
            except Exception as exc: LOGGER.warning("sitemap shard failed for %s: %s", loc, exc)
        return unique_preserve(race_urls)

    @staticmethod
    def meta_grid(soup: BeautifulSoup) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for item in soup.select("#overview .race-meta-grid > div"):
            label_node = item.find("span"); value_node = item.find("b")
            if label_node and value_node:
                metadata[normalize_space(label_node.get_text(" ", strip=True))] = normalize_space(value_node.get_text(" ", strip=True))
        return metadata

    @staticmethod
    def page_region_label(soup: BeautifulSoup) -> str:
        node = soup.select_one(".race-hero-meta-text")
        text = normalize_space(node.get_text(" ", strip=True)) if node else ""
        return text.split("·", 1)[0].strip()

    @staticmethod
    def race_original_name(soup: BeautifulSoup) -> str:
        node = soup.select_one(".race-hero-original")
        text = normalize_space(node.get_text(" ", strip=True)) if node else ""
        match = DATE_RE.search(text)
        return text[:match.start()].strip(" ·") if match else text.strip(" ·")

    def parse_race_page(self, url: str) -> dict[str, Any]:
        response = self.client.get(url); body = response.content; soup = BeautifulSoup(body, "html.parser")
        if soup.select_one("main.race-page") is None: raise RuntimeError("public race page marker missing")
        metadata = self.meta_grid(soup); region_label_raw = self.page_region_label(soup)
        name_node = soup.select_one(".race-hero-name")
        race_name_zh = normalize_space(name_node.get_text(" ", strip=True)) if name_node else ""
        original_name = self.race_original_name(soup); racecourse = metadata.get("马场", "")
        region = classify_region(
            label=region_label_raw, racecourse=racecourse, race_name_original=original_name,
            url=response.url, overrides=self.region_overrides,
        )
        grade_node = soup.select_one(".grade-badge")
        grade = normalize_grade(metadata.get("等级") or (normalize_space(grade_node.get_text(" ", strip=True)) if grade_node else ""))
        race_date = metadata.get("日期", ""); status = metadata.get("状态", "")
        source = {
            "url": response.url, "requested_url": url, "http_status": response.status_code,
            "sha256": sha256_bytes(body), "region": region, "region_label_raw": region_label_raw,
            "race_date": race_date, "race_name_zh": race_name_zh, "grade": grade,
            "status": status, "fetched_at": utc_now_iso(),
        }
        def skipped(reason: str) -> dict[str, Any]:
            return {"status": "success", "included": False, "skip_reason": reason, "rows": [], "source": source}
        if region not in TARGET_REGIONS: return skipped("region_out_of_scope")
        if status not in {"已结束", "已完赛"}: return skipped("not_completed")
        try: race_date_value = date.fromisoformat(race_date)
        except ValueError as exc: raise RuntimeError(f"invalid completed-race date: {race_date!r}") from exc
        if race_date_value.year != self.year or race_date_value > self.cutoff: return skipped("date_out_of_scope")
        if not grade_is_in_scope(region, grade): return skipped("grade_out_of_scope")
        section = soup.select_one("section#results")
        if section is None: raise RuntimeError("completed in-scope race has no result section")
        rows: list[ParticipantRow] = []; seen_horses: set[str] = set()
        for tr in section.select("tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 8: continue
            finish_text = normalize_space(cells[0].get_text(" ", strip=True))
            finish_position, result_status, started = normalize_result_status(finish_text)
            if not started: continue
            horse_name = normalize_space(cells[2].get_text(" ", strip=True))
            if not horse_name: continue
            horse_identity = normalize_identity(horse_name)
            if horse_identity in seen_horses: raise RuntimeError(f"duplicate participant row for {horse_name}")
            seen_horses.add(horse_identity)
            horse_link = cells[2].find("a"); profile_url = ""
            if horse_link and horse_link.get("href"):
                profile_url = validate_request_url(urljoin(response.url, horse_link.get("href", "")))
            lookup_key = f"{region}|{normalize_identity(profile_url or horse_name)}"
            rows.append(ParticipantRow(
                region=region, region_label=REGION_OUTPUT[region], race_date=race_date,
                race_name_zh=race_name_zh, race_name_original=original_name, grade=grade,
                racecourse=racecourse, finish_position=finish_position,
                finish_position_text=finish_text, result_status=result_status,
                horse_number=normalize_space(cells[1].get_text(" ", strip=True)),
                horse_display_name=horse_name,
                jockey_name=normalize_space(cells[3].get_text(" ", strip=True)),
                trainer_name=normalize_space(cells[4].get_text(" ", strip=True)),
                finish_time=normalize_space(cells[5].get_text(" ", strip=True)),
                margin=normalize_space(cells[6].get_text(" ", strip=True)),
                odds_popularity=normalize_space(cells[7].get_text(" ", strip=True)),
                race_url=response.url, race_page_sha256=source["sha256"],
                horse_lookup_key=lookup_key, horse_profile_url=profile_url,
            ))
        if not rows: raise RuntimeError("completed in-scope race has no actual starters")
        return {"status": "success", "included": True, "rows": [asdict(row) for row in rows], "source": source}

    def find_profile(self, key: str, seed: HorseSeed) -> dict[str, Any]:
        display = sorted(seed.display_names, key=lambda item: (len(item), item))[0]
        response = self.client.get(f"{self.base_url}/horses/", params={"q": display})
        soup = BeautifulSoup(response.content, "html.parser"); candidates: list[dict[str, str]] = []
        for card in soup.select("article.horse-card"):
            name_node = card.select_one(".horse-card-name a")
            if not name_node: continue
            card_display = normalize_space(name_node.get_text(" ", strip=True))
            if normalize_identity(card_display) != normalize_identity(display): continue
            region_node = card.select_one(".region-label")
            card_region_label = normalize_space(region_node.get_text(" ", strip=True)) if region_node else ""
            original_node = card.select_one(".horse-card-original")
            original = normalize_space(original_node.get_text(" ", strip=True)) if original_node else ""
            if original == "资料整理中": original = ""
            candidates.append({
                "display_name": card_display, "region": REGION_LABELS.get(card_region_label, ""),
                "original_name": original,
                "profile_url": validate_request_url(urljoin(response.url, name_node.get("href", ""))),
            })
        region_matches = [item for item in candidates if item["region"] == seed.region]
        candidates = region_matches or candidates
        if not candidates:
            name_zh, name_ja, name_en = infer_names(seed.display_names, "")
            return {"status": "not_found", "region": seed.region, "display_names": sorted(seed.display_names),
                    "profile_url": "", "original_name": "", "birth_year": "",
                    "name_zh": name_zh, "name_ja": name_ja, "name_en": name_en,
                    "name_quality_status": "profile_not_found"}
        if len(candidates) != 1:
            name_zh, name_ja, name_en = infer_names(seed.display_names, "")
            return {"status": "ambiguous", "region": seed.region, "display_names": sorted(seed.display_names),
                    "profile_url": "", "original_name": "", "birth_year": "",
                    "name_zh": name_zh, "name_ja": name_ja, "name_en": name_en,
                    "candidate_count": len(candidates), "name_quality_status": "profile_ambiguous"}
        candidate = candidates[0]; detail = self.client.get(candidate["profile_url"])
        detail_soup = BeautifulSoup(detail.content, "html.parser")
        original_node = detail_soup.select_one(".horse-hero-original")
        detail_text = normalize_space(original_node.get_text(" ", strip=True)) if original_node else ""
        original_name = detail_text.split(" · ", 1)[0].strip() if detail_text else candidate["original_name"]
        if original_name == candidate["display_name"]: original_name = candidate["original_name"]
        year_match = YEAR_RE.search(detail_text); birth_year = year_match.group(1) if year_match else ""
        name_zh, name_ja, name_en = infer_names(seed.display_names, original_name)
        english_required = seed.region not in ENGLISH_OPTIONAL_REGIONS
        return {
            "status": "success", "region": seed.region, "display_names": sorted(seed.display_names),
            "profile_url": candidate["profile_url"], "profile_page_sha256": sha256_bytes(detail.content),
            "original_name": original_name, "birth_year": birth_year,
            "name_zh": name_zh, "name_ja": name_ja, "name_en": name_en,
            "name_quality_status": "missing_required_english" if english_required and not name_en else "complete",
        }
