from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import dateparse
from django.utils import timezone

from stable.models import RacingRegion, SourceLanguage, TermType
from stable.services.term_admin import serialize_aliases, source_text_identity


CANDIDATE_HEADERS = [
    "term_type",
    "source_language",
    "racing_region",
    "source_ja",
    "target_zh",
    "aliases_ja",
    "aliases_zh",
    "priority",
    "is_active",
    "notes",
    "race_grade",
]
CONFLICT_HEADERS = [
    "term_type",
    "entity_key",
    "region",
    "recommended_source",
    "recommended_target_zh",
    "alternate_source",
    "alternate_target_zh",
    "aliases_zh",
    "conflict_type",
    "evidence",
    "notes",
]
OFFICIAL_SOURCES = {"hkjc", "hkjc_overseas"}
SUPPORTED_TERM_TYPES = {
    TermType.HORSE,
    TermType.RACE,
    TermType.JOCKEY,
    TermType.TRAINER,
    TermType.RACECOURSE,
    TermType.FIXED_PHRASE,
}
SUPPORTED_SOURCES = {"hkjc", "hkjc_overseas", "wpstud"}
DEFERRED_SOURCES = {"hkjc_racecards_pdf", "hkjc_racecards", "hkjc_pdf"}
REGION_ORDER = {
    "hk": 0,
    "hong_kong": 0,
    "gb": 10,
    "uk": 10,
    "fr": 20,
    "us": 30,
    "au_nz": 40,
    "au": 40,
    "nz": 40,
    "other": 80,
    "jp": 100,
    "japan": 100,
}
SOURCE_ORDER = {"hkjc": 0, "hkjc_overseas": 1, "wpstud": 10}
DEFAULT_SOURCE_URLS = {
    "hkjc": [
        "https://racing.hkjc.com/en-us/local/information/selecthorse",
        "https://racing.hkjc.com/en-us/local/info/horse-former-name",
        "https://racing.hkjc.com/en-us/overseas/",
        "https://racing.hkjc.com/racing/english/learn-racing/learn-question.aspx",
    ],
    "hkjc_overseas": [
        "https://racing.hkjc.com/en-us/overseas/",
    ],
    "wpstud": [
        "https://www.wpstud.com/",
        "https://www.wpstud.com/Translation/Horse/Horse.htm",
        "https://www.wpstud.com/Translation/Horse/HK/Horse_HK.htm",
        "https://www.wpstud.com/horseintro/jpnhorse/JpnHorse.htm",
    ],
}


class TermbaseSeedError(Exception):
    pass


class DeferredSourceError(TermbaseSeedError):
    pass


class MaxRequestsReached(TermbaseSeedError):
    pass


@dataclass(frozen=True)
class SeedFetchOptions:
    allow_network: bool = False
    max_requests: int = 20
    request_interval_seconds: float = 3
    timeout_seconds: float = 15
    limit_pages: int | None = None
    limit_horses: int | None = None
    limit_meetings: int | None = None
    limit_races: int | None = None
    hkjc_overseas_races: tuple[str, ...] = ()


@dataclass
class RequestRecord:
    source: str
    url: str
    status_code: int | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "status_code": self.status_code,
            "error": self.error,
        }


@dataclass
class RawSeedRecord:
    term_type: str
    source_language: str
    source_text: str
    target_zh: str
    source: str
    region: str = "other"
    entity_key: str = ""
    aliases_source: list[str] = field(default_factory=list)
    aliases_zh: list[str] = field(default_factory=list)
    evidence_url: str = ""
    original_target_zh: str = ""
    race_grade: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def source_tier(self) -> str:
        return "official" if self.source in OFFICIAL_SOURCES else "community"


@dataclass
class BuildResult:
    candidates: list[dict[str, str]]
    conflicts: list[dict[str, str]]
    summary: dict[str, Any]
    source_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HKJCOverseasRaceKey:
    race_date: str
    racecourse: str
    race_no: str

    @property
    def identity(self) -> str:
        return f"{self.race_date}:{self.racecourse}:{self.race_no}"

    @property
    def params(self) -> dict[str, str]:
        return {"RaceDate": self.race_date, "Racecourse": self.racecourse, "RaceNo": self.race_no}

    def url(self, language: str) -> str:
        return (
            f"https://racing.hkjc.com/{language}/overseas/racecard"
            f"?RaceDate={self.race_date}&Racecourse={self.racecourse}&RaceNo={self.race_no}"
        )


def default_output_dir() -> Path:
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    return Path(settings.BASE_DIR).parent / "runtime" / "termbase_seed" / stamp


def builtin_fixture_dir() -> Path:
    return Path(settings.BASE_DIR) / "stable" / "fixtures" / "termbase_seed"


def to_simplified_chinese(text: str) -> str:
    value = text or ""
    try:
        from opencc import OpenCC

        return OpenCC("t2s").convert(value)
    except Exception:
        return value.translate(_TRADITIONAL_TO_SIMPLIFIED_FALLBACK)


_TRADITIONAL_TO_SIMPLIFIED_FALLBACK = str.maketrans(
    {
        "麗": "丽",
        "傳": "传",
        "號": "号",
        "馬": "马",
        "賽": "赛",
        "會": "会",
        "練": "练",
        "師": "师",
        "騎": "骑",
        "場": "场",
        "國": "国",
        "級": "级",
        "盃": "杯",
        "獎": "奖",
        "錦": "锦",
        "標": "标",
        "準": "准",
        "僅": "仅",
        "獨": "独",
        "愛": "爱",
        "歡": "欢",
        "聲": "声",
        "貴": "贵",
        "婦": "妇",
        "鑽": "钻",
        "強": "强",
        "擊": "击",
        "沖": "冲",
        "應": "应",
        "昇": "升",
        "頓": "顿",
        "約": "约",
        "漢": "汉",
        "門": "门",
        "優": "优",
        "勝": "胜",
        "後": "后",
        "體": "体",
    }
)


def normalize_region(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "香港": "hk",
        "hong_kong": "hk",
        "hk": "hk",
        "日本": "jp",
        "jpn": "jp",
        "japan": "jp",
        "英国": "gb",
        "英國": "gb",
        "uk": "gb",
        "gb": "gb",
        "france": "fr",
        "法国": "fr",
        "法國": "fr",
        "usa": "us",
        "united_states": "us",
        "美国": "us",
        "美國": "us",
        "澳洲": "au",
        "澳大利亚": "au",
        "紐西蘭": "nz",
        "新西兰": "nz",
    }
    return mapping.get(normalized, normalized or "other")


def import_region_value(value: str) -> str:
    mapping = {
        "hk": RacingRegion.HONG_KONG,
        "hong_kong": RacingRegion.HONG_KONG,
        "jp": RacingRegion.JAPAN,
        "japan": RacingRegion.JAPAN,
        "gb": RacingRegion.UNITED_KINGDOM,
        "uk": RacingRegion.UNITED_KINGDOM,
        "fr": RacingRegion.FRANCE,
        "france": RacingRegion.FRANCE,
        "us": RacingRegion.UNITED_STATES,
        "united_states": RacingRegion.UNITED_STATES,
        "other": RacingRegion.OTHER,
    }
    return mapping.get(normalize_region(value), RacingRegion.OTHER)


def parse_hkjc_overseas_race_key(raw: str) -> HKJCOverseasRaceKey:
    parts: dict[str, str] = {}
    for piece in (raw or "").split(","):
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        parts[key.strip().lower()] = value.strip()
    raw_date = parts.get("racedate") or parts.get("race_date")
    racecourse = (parts.get("racecourse") or parts.get("race_course") or "").upper()
    race_no = parts.get("raceno") or parts.get("race_no")
    parsed_date = _parse_race_key_date(raw_date or "")
    if not parsed_date or not racecourse or not race_no:
        raise TermbaseSeedError(
            "HKJC overseas Race Card 参数格式错误；请使用 "
            "--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>"
        )
    try:
        race_no_value = str(int(race_no))
    except (TypeError, ValueError) as exc:
        raise TermbaseSeedError(
            "HKJC overseas Race Card 参数格式错误；RaceNo 必须是数字。"
        ) from exc
    return HKJCOverseasRaceKey(race_date=parsed_date.strftime("%Y%m%d"), racecourse=racecourse, race_no=race_no_value)


def _parse_race_key_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("/", "-")
    parsed = dateparse.parse_date(normalized)
    if parsed:
        return parsed
    if re.fullmatch(r"\d{8}", raw):
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def stable_entity_key(*values: str) -> str:
    for value in values:
        key = source_text_identity(value or "")
        if key:
            return key
    return ""


def validate_sources(sources: list[str]) -> list[str]:
    normalized = [source.strip().lower() for source in sources if source and source.strip()]
    if not normalized:
        raise TermbaseSeedError("需要至少选择一个来源：hkjc、hkjc_overseas 或 wpstud。")
    deferred = [source for source in normalized if source in DEFERRED_SOURCES]
    if deferred:
        raise DeferredSourceError(f"首版暂不支持来源：{', '.join(deferred)}")
    unsupported = [source for source in normalized if source not in SUPPORTED_SOURCES]
    if unsupported:
        raise TermbaseSeedError(f"不支持的来源：{', '.join(unsupported)}")
    return normalized


class SeedNetworkClient:
    user_agent = "umanewsbot/1.0 (+https://umafans.run; termbase seed preparation)"

    def __init__(self, options: SeedFetchOptions):
        self.options = options
        self.requests: list[RequestRecord] = []

    def get_text(self, url: str, *, source: str) -> str | None:
        if len(self.requests) >= self.options.max_requests:
            raise MaxRequestsReached(f"max_requests={self.options.max_requests} reached")
        if self.requests and self.options.request_interval_seconds > 0:
            time.sleep(self.options.request_interval_seconds)
        try:
            response = requests.get(
                url,
                timeout=self.options.timeout_seconds,
                headers={"User-Agent": self.user_agent},
            )
        except requests.RequestException as exc:
            self.requests.append(RequestRecord(source=source, url=url, error=str(exc)))
            return None
        self.requests.append(RequestRecord(source=source, url=getattr(response, "url", url), status_code=response.status_code))
        if response.status_code < 200 or response.status_code >= 300:
            self.requests[-1].error = f"HTTP {response.status_code}"
            return None
        response.encoding = response.encoding or "utf-8"
        return response.text


def collect_seed_records(
    *,
    sources: list[str],
    input_dir: Path | None = None,
    options: SeedFetchOptions | None = None,
) -> tuple[list[RawSeedRecord], list[RequestRecord], list[dict[str, str]]]:
    selected_sources = validate_sources(sources)
    options = options or SeedFetchOptions()
    overseas_exact_keys = [parse_hkjc_overseas_race_key(raw) for raw in options.hkjc_overseas_races]
    root = input_dir or builtin_fixture_dir()
    records: list[RawSeedRecord] = []
    failures: list[dict[str, str]] = []
    requests_info: list[RequestRecord] = []

    if options.allow_network:
        client = SeedNetworkClient(options)
        for source in selected_sources:
            if source == "hkjc_overseas":
                overseas_records, overseas_failures = _collect_hkjc_overseas_network_records(
                    client,
                    exact_keys=overseas_exact_keys,
                    options=options,
                )
                records.extend(overseas_records)
                failures.extend(overseas_failures)
                continue
            urls = DEFAULT_SOURCE_URLS[source]
            if options.limit_pages is not None:
                urls = urls[: max(0, options.limit_pages)]
            for url in urls:
                try:
                    html = client.get_text(url, source=source)
                except MaxRequestsReached as exc:
                    failures.append(
                        {
                            "source": source,
                            "url": url,
                            "error": str(exc),
                            "status_code": "",
                        }
                    )
                    requests_info.extend(client.requests)
                    return records, requests_info, failures
                request_record = client.requests[-1] if client.requests else None
                if not html:
                    if request_record:
                        failures.append(
                            {
                                "source": source,
                                "url": request_record.url,
                                "error": request_record.error or "empty response",
                                "status_code": "" if request_record.status_code is None else str(request_record.status_code),
                            }
                        )
                    break
                records.extend(parse_source_html(html, source=source, source_url=url, fallback_region=_region_from_url(url)))
                if source == "hkjc":
                    try:
                        records.extend(
                            _collect_hkjc_horse_detail_records(
                                client,
                                html=html,
                                source_url=url,
                                limit_horses=options.limit_horses,
                            )
                        )
                    except MaxRequestsReached as exc:
                        failures.append(
                            {
                                "source": source,
                                "url": url,
                                "error": str(exc),
                                "status_code": "",
                            }
                        )
                        requests_info.extend(client.requests)
                        return records, requests_info, failures
        requests_info.extend(client.requests)
        return records, requests_info, failures

    for source in selected_sources:
        if source == "hkjc_overseas":
            overseas_records, overseas_failures = _collect_hkjc_overseas_fixture_records(
                root,
                exact_keys=overseas_exact_keys,
                options=options,
            )
            records.extend(overseas_records)
            failures.extend(overseas_failures)
            continue
        patterns = _fixture_patterns_for_source(source)
        matched = [path for pattern in patterns for path in root.glob(pattern)]
        if not matched:
            failures.append({"source": source, "url": str(root), "error": "no fixture files found", "status_code": ""})
            continue
        for path in sorted(set(matched)):
            html = path.read_text(encoding="utf-8")
            records.extend(parse_source_html(html, source=source, source_url=_source_url_from_html(html) or path.as_posix()))
    return records, requests_info, failures


def _fixture_patterns_for_source(source: str) -> list[str]:
    if source == "hkjc":
        return ["hkjc*.html", "hkjc*.htm"]
    if source == "hkjc_overseas":
        return ["hkjc_overseas*.html", "hkjc_overseas*.htm"]
    if source == "wpstud":
        return ["wpstud*.html", "wpstud*.htm", "wp_stud*.html"]
    return []


def _source_url_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.find(attrs={"data-source-url": True})
    return str(node.get("data-source-url", "")).strip() if node else ""


def _collect_hkjc_overseas_network_records(
    client: SeedNetworkClient,
    *,
    exact_keys: list[HKJCOverseasRaceKey],
    options: SeedFetchOptions,
) -> tuple[list[RawSeedRecord], list[dict[str, str]]]:
    records: list[RawSeedRecord] = []
    failures: list[dict[str, str]] = []
    race_keys = exact_keys
    if not race_keys:
        landing_url = DEFAULT_SOURCE_URLS["hkjc_overseas"][0]
        try:
            landing_html = client.get_text(landing_url, source="hkjc_overseas")
        except MaxRequestsReached as exc:
            return records, [_failure("hkjc_overseas", landing_url, str(exc))]
        if not landing_html:
            return records, [_failure_from_last_request(client, landing_url, "hkjc_overseas")]
        race_keys = _discover_hkjc_overseas_race_keys(landing_html, source_url=landing_url)
        if options.limit_meetings is not None:
            race_keys = _limit_hkjc_overseas_meetings(race_keys, options.limit_meetings)
        limit_races = options.limit_races if options.limit_races is not None else 3
        race_keys = race_keys[: max(0, limit_races)]
        if not race_keys:
            return records, [
                _failure(
                    "hkjc_overseas",
                    landing_url,
                    "render_fallback_unavailable: no race card links in direct HTML",
                    failure_type="render_fallback_unavailable",
                )
            ]

    for race_key in race_keys:
        try:
            en_html = client.get_text(race_key.url("en-us"), source="hkjc_overseas")
            zh_html = client.get_text(race_key.url("zh-hk"), source="hkjc_overseas")
        except MaxRequestsReached as exc:
            failures.append(_failure("hkjc_overseas", race_key.url("en-us"), str(exc), race_key=race_key))
            break
        if not en_html or not zh_html:
            failures.append(_failure("hkjc_overseas", race_key.url("en-us"), "race_card_fetch_failed", race_key=race_key))
            continue
        parsed, skipped, parse_failures = parse_hkjc_overseas_racecard_pair(
            en_html,
            zh_html,
            race_key=race_key,
            en_url=race_key.url("en-us"),
            zh_url=race_key.url("zh-hk"),
            fetch_mode="direct",
        )
        records.extend(parsed)
        failures.extend(skipped)
        failures.extend(parse_failures)
    return records, failures


def _collect_hkjc_overseas_fixture_records(
    root: Path,
    *,
    exact_keys: list[HKJCOverseasRaceKey],
    options: SeedFetchOptions,
) -> tuple[list[RawSeedRecord], list[dict[str, str]]]:
    matched = sorted(set(path for pattern in _fixture_patterns_for_source("hkjc_overseas") for path in root.glob(pattern)))
    if not matched:
        return [], [{"source": "hkjc_overseas", "url": str(root), "error": "no fixture files found", "status_code": ""}]

    records: list[RawSeedRecord] = []
    failures: list[dict[str, str]] = []
    racecard_files: dict[str, dict[str, Path]] = {}
    for path in matched:
        html = path.read_text(encoding="utf-8")
        if _looks_like_hkjc_overseas_racecard(html):
            race_key = _race_key_from_html(html, fallback_url=_source_url_from_html(html) or path.as_posix())
            language = _racecard_language_from_html(html) or _language_from_path(path)
            if race_key and language in {"en-us", "zh-hk"}:
                racecard_files.setdefault(race_key.identity, {})[language] = path
            continue
        records.extend(parse_source_html(html, source="hkjc_overseas", source_url=_source_url_from_html(html) or path.as_posix()))

    target_identities = {item.identity for item in exact_keys}
    processed = 0
    for identity, files in sorted(racecard_files.items()):
        if target_identities and identity not in target_identities:
            continue
        if options.limit_races is not None and processed >= options.limit_races:
            break
        en_path = files.get("en-us")
        zh_path = files.get("zh-hk")
        race_key = _race_key_from_html(en_path.read_text(encoding="utf-8") if en_path else zh_path.read_text(encoding="utf-8"), fallback_url=(en_path or zh_path).as_posix())
        if not race_key:
            continue
        if not en_path or not zh_path:
            failures.append(_failure("hkjc_overseas", (en_path or zh_path).as_posix(), "missing bilingual fixture", race_key=race_key))
            continue
        parsed, skipped, parse_failures = parse_hkjc_overseas_racecard_pair(
            en_path.read_text(encoding="utf-8"),
            zh_path.read_text(encoding="utf-8"),
            race_key=race_key,
            en_url=_source_url_from_html(en_path.read_text(encoding="utf-8")) or en_path.as_posix(),
            zh_url=_source_url_from_html(zh_path.read_text(encoding="utf-8")) or zh_path.as_posix(),
            fetch_mode="fixture",
        )
        records.extend(parsed)
        failures.extend(skipped)
        failures.extend(parse_failures)
        processed += 1
    return _dedupe_raw_records(records), failures


def _failure(
    source: str,
    url: str,
    error: str,
    *,
    status_code: str = "",
    failure_type: str = "failure",
    race_key: HKJCOverseasRaceKey | None = None,
) -> dict[str, str]:
    payload = {"source": source, "url": url, "error": error, "status_code": status_code, "type": failure_type}
    if race_key:
        payload.update(race_key.params)
    return payload


def _failure_from_last_request(client: SeedNetworkClient, fallback_url: str, source: str) -> dict[str, str]:
    request_record = client.requests[-1] if client.requests else None
    if not request_record:
        return _failure(source, fallback_url, "empty response")
    return _failure(
        source,
        request_record.url,
        request_record.error or "empty response",
        status_code="" if request_record.status_code is None else str(request_record.status_code),
    )


def _looks_like_hkjc_overseas_racecard(html: str) -> bool:
    text = html or ""
    if re.search(r"data-hkjc-overseas-racecard", text, re.I):
        return True
    return bool(
        re.search(r"data-hkjc-overseas-racecard|RaceDate|Racecourse|RaceNo|horseprofile|simulcastHorseId", text, re.I)
        and re.search(r"race\s*card|出馬表|賽事|Race\s*No|Horse|馬名", BeautifulSoup(text, "lxml").get_text(" ", strip=True), re.I)
    )


def _discover_hkjc_overseas_race_keys(html: str, *, source_url: str) -> list[HKJCOverseasRaceKey]:
    soup = BeautifulSoup(html or "", "lxml")
    keys: list[HKJCOverseasRaceKey] = []
    seen: set[str] = set()
    for node in soup.find_all(attrs={"data-race-date": True}):
        raw = (
            f"RaceDate={node.get('data-race-date')},"
            f"Racecourse={node.get('data-racecourse') or node.get('data-race-course')},"
            f"RaceNo={node.get('data-race-no') or node.get('data-raceno')}"
        )
        try:
            key = parse_hkjc_overseas_race_key(raw)
        except TermbaseSeedError:
            continue
        if key.identity not in seen:
            seen.add(key.identity)
            keys.append(key)
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if not re.search(r"RaceDate|Racecourse|RaceNo|racecard", href, re.I):
            continue
        absolute = urljoin(source_url, href)
        key = _race_key_from_url(absolute)
        if key and key.identity not in seen:
            seen.add(key.identity)
            keys.append(key)
    for match in re.finditer(r"RaceDate[=:](?P<date>\d{4}[-/]?\d{2}[-/]?\d{2}).{0,120}?Racecourse[=:](?P<course>[A-Z0-9]+).{0,120}?RaceNo[=:](?P<no>\d+)", html or "", re.I):
        try:
            key = parse_hkjc_overseas_race_key(
                f"RaceDate={match.group('date')},Racecourse={match.group('course')},RaceNo={match.group('no')}"
            )
        except TermbaseSeedError:
            continue
        if key.identity not in seen:
            seen.add(key.identity)
            keys.append(key)
    return keys


def _limit_hkjc_overseas_meetings(keys: list[HKJCOverseasRaceKey], limit_meetings: int | None) -> list[HKJCOverseasRaceKey]:
    if limit_meetings is None:
        return keys
    seen_meetings: set[tuple[str, str]] = set()
    result: list[HKJCOverseasRaceKey] = []
    for key in keys:
        meeting = (key.race_date, key.racecourse)
        if meeting not in seen_meetings and len(seen_meetings) >= max(0, limit_meetings):
            continue
        seen_meetings.add(meeting)
        result.append(key)
    return result


def _race_key_from_url(url: str) -> HKJCOverseasRaceKey | None:
    params = parse_qs(urlparse(url).query)
    raw = (
        f"RaceDate={_first_value(params, 'RaceDate')},"
        f"Racecourse={_first_value(params, 'Racecourse')},"
        f"RaceNo={_first_value(params, 'RaceNo')}"
    )
    try:
        return parse_hkjc_overseas_race_key(raw)
    except TermbaseSeedError:
        return None


def _first_value(params: dict[str, list[str]], name: str) -> str:
    for key, values in params.items():
        if key.lower() == name.lower() and values:
            return values[0]
    return ""


def _race_key_from_html(html: str, *, fallback_url: str) -> HKJCOverseasRaceKey | None:
    soup = BeautifulSoup(html or "", "lxml")
    node = soup.find(attrs={"data-race-date": True})
    if node:
        try:
            return parse_hkjc_overseas_race_key(
                f"RaceDate={node.get('data-race-date')},"
                f"Racecourse={node.get('data-racecourse') or node.get('data-race-course')},"
                f"RaceNo={node.get('data-race-no') or node.get('data-raceno')}"
            )
        except TermbaseSeedError:
            pass
    return _race_key_from_url(_source_url_from_html(html) or fallback_url)


def _racecard_language_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    node = soup.find(attrs={"data-language": True}) or soup.find("html")
    raw = str(node.get("data-language") or node.get("lang") or "").lower() if node else ""
    if raw.startswith("zh"):
        return "zh-hk"
    if raw.startswith("en"):
        return "en-us"
    return ""


def _language_from_path(path: Path) -> str:
    name = path.name.lower()
    if "zh" in name or "ch" in name:
        return "zh-hk"
    if "en" in name:
        return "en-us"
    return ""


def parse_hkjc_overseas_racecard_pair(
    en_html: str,
    zh_html: str,
    *,
    race_key: HKJCOverseasRaceKey,
    en_url: str,
    zh_url: str,
    fetch_mode: str,
) -> tuple[list[RawSeedRecord], list[dict[str, str]], list[dict[str, str]]]:
    en_card = _extract_hkjc_overseas_card(en_html, language="en-us", source_url=en_url)
    zh_card = _extract_hkjc_overseas_card(zh_html, language="zh-hk", source_url=zh_url)
    if en_card["not_available"] or zh_card["not_available"]:
        return [], [_failure("hkjc_overseas", en_url, "race_card_not_available", failure_type="skipped_races", race_key=race_key)], []
    if not en_card["rows"] and not zh_card["rows"] and _looks_like_next_shell(en_html):
        return [], [], [
            _failure(
                "hkjc_overseas",
                en_url,
                "render_fallback_unavailable: race card content not present in direct HTML",
                failure_type="render_fallback_unavailable",
                race_key=race_key,
            )
        ]
    if not en_card["rows"] or not zh_card["rows"]:
        return [], [], [_failure("hkjc_overseas", en_url, "race_card_parse_failed", race_key=race_key)]

    region = _hkjc_overseas_region(en_card, zh_card, race_key)
    base_evidence = {
        "source": "hkjc_overseas",
        "race_key": race_key.params,
        "en_url": en_url,
        "zh_url": zh_url,
        "fetch_mode": fetch_mode,
        "region": region,
        "raw_region": en_card.get("raw_region") or zh_card.get("raw_region") or race_key.racecourse,
    }
    records: list[RawSeedRecord] = []
    if en_card["race_name"] and zh_card["race_name"]:
        records.append(
            RawSeedRecord(
                term_type=TermType.RACE,
                source_language=SourceLanguage.ENGLISH,
                source_text=en_card["race_name"],
                target_zh=to_simplified_chinese(zh_card["race_name"]),
                original_target_zh=zh_card["race_name"],
                source="hkjc_overseas",
                region=region,
                entity_key=stable_entity_key(en_card["race_name"]),
                evidence_url=en_url,
                race_grade=_race_grade_from_name(en_card["race_name"]),
                evidence={**base_evidence, "entity": "race", "alignment": "race_key"},
            )
        )

    zh_by_no = {row.get("horse_no") or str(index + 1): row for index, row in enumerate(zh_card["rows"])}
    seen_jockeys: set[str] = set()
    for index, en_row in enumerate(en_card["rows"]):
        row_key = en_row.get("horse_no") or str(index + 1)
        zh_row = zh_by_no.get(row_key) or (zh_card["rows"][index] if index < len(zh_card["rows"]) else {})
        horse_en = en_row.get("horse", "")
        horse_zh = zh_row.get("horse", "")
        horse_profile = en_row.get("horse_profile") or zh_row.get("horse_profile") or {}
        if horse_en and horse_zh:
            records.append(
                RawSeedRecord(
                    term_type=TermType.HORSE,
                    source_language=SourceLanguage.ENGLISH,
                    source_text=horse_en,
                    target_zh=to_simplified_chinese(horse_zh),
                    original_target_zh=horse_zh,
                    source="hkjc_overseas",
                    region=region,
                    entity_key=stable_entity_key(horse_en),
                    evidence_url=en_url,
                    evidence={
                        **base_evidence,
                        "entity": "horse",
                        "horse_no": row_key,
                        "alignment": "horse_no",
                        "horse_profile": horse_profile,
                    },
                )
            )
        jockey_en = en_row.get("jockey", "")
        jockey_zh = zh_row.get("jockey", "")
        jockey_key = source_text_identity(jockey_en)
        if jockey_en and jockey_zh and jockey_key not in seen_jockeys:
            seen_jockeys.add(jockey_key)
            records.append(
                RawSeedRecord(
                    term_type=TermType.JOCKEY,
                    source_language=SourceLanguage.ENGLISH,
                    source_text=jockey_en,
                    target_zh=to_simplified_chinese(jockey_zh),
                    original_target_zh=jockey_zh,
                    source="hkjc_overseas",
                    region=region,
                    entity_key=stable_entity_key(jockey_en),
                    evidence_url=en_url,
                    evidence={**base_evidence, "entity": "jockey", "horse_no": row_key, "alignment": "horse_no"},
                )
            )
    return _dedupe_raw_records(records), [], []


def _looks_like_next_shell(html: str) -> bool:
    return "_next/static/chunks" in (html or "") and "Loadingcontainer" in (html or "")


def _extract_hkjc_overseas_card(html: str, *, language: str, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    page_text = soup.get_text(" ", strip=True)
    not_available_patterns = [
        "未有資料",
        "未有资料",
        "No information",
        "No race information",
        "Race card not available",
    ]
    not_available = any(pattern.lower() in page_text.lower() for pattern in not_available_patterns)
    root = soup.find(attrs={"data-hkjc-overseas-racecard": True}) or soup
    race_name = _first_text(
        root,
        [
            "[data-race-name]",
            ".race-name",
            ".raceName",
            "h1",
            "h2",
        ],
    )
    raw_region = (
        str(getattr(root, "get", lambda *_args, **_kwargs: "")("data-country") or "")
        or str(getattr(root, "get", lambda *_args, **_kwargs: "")("data-region") or "")
        or _first_text(root, ["[data-country]", "[data-region]", ".country", ".venue"])
    )
    rows = _extract_hkjc_overseas_rows(root, source_url=source_url)
    return {
        "language": language,
        "source_url": source_url,
        "race_name": race_name,
        "raw_region": raw_region,
        "rows": rows,
        "not_available": not_available,
    }


def _first_text(root, selectors: list[str]) -> str:
    for selector in selectors:
        node = root.select_one(selector) if hasattr(root, "select_one") else None
        if node:
            value = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if value:
                return value
    return ""


def _extract_hkjc_overseas_rows(root, *, source_url: str) -> list[dict[str, Any]]:
    tables = []
    if hasattr(root, "select"):
        tables.extend(root.select("table[data-race-card], table[data-hkjc-runners], table.racecard, table.race-card"))
        if not tables:
            tables.extend(root.find_all("table"))
    rows: list[dict[str, Any]] = []
    for table in tables:
        table_rows = _table_rows(table)
        if len(table_rows) < 2:
            continue
        headers = [_hkjc_overseas_header_key(value) for value in table_rows[0]]
        if "horse" not in headers and "jockey" not in headers:
            continue
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if not any(values):
                continue
            row = {headers[index]: values[index].strip() for index in range(min(len(headers), len(values))) if headers[index]}
            link = tr.find("a", href=re.compile("horseprofile|/horse", re.I))
            if link:
                row["horse_profile"] = _hkjc_overseas_horse_profile_evidence(urljoin(source_url, str(link.get("href") or "")))
            else:
                row["horse_profile"] = {}
            if row.get("horse") or row.get("jockey"):
                rows.append(row)
    if rows:
        return rows

    for node in root.select("[data-horse-name], [data-horse]") if hasattr(root, "select") else []:
        horse = str(node.get("data-horse-name") or node.get("data-horse") or "").strip()
        jockey = str(node.get("data-jockey") or "").strip()
        horse_no = str(node.get("data-horse-no") or node.get("data-number") or "").strip()
        profile = str(node.get("data-horse-profile") or node.get("href") or "").strip()
        rows.append(
            {
                "horse_no": horse_no,
                "horse": horse,
                "jockey": jockey,
                "horse_profile": _hkjc_overseas_horse_profile_evidence(urljoin(source_url, profile)) if profile else {},
            }
        )
    return rows


def _hkjc_overseas_header_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    normalized = re.sub(r"\s+", "_", normalized)
    mapping = {
        "no.": "horse_no",
        "no": "horse_no",
        "horse_no.": "horse_no",
        "horse_no": "horse_no",
        "馬號": "horse_no",
        "马号": "horse_no",
        "horse": "horse",
        "horse_name": "horse",
        "馬名": "horse",
        "马名": "horse",
        "jockey": "jockey",
        "騎師": "jockey",
        "骑师": "jockey",
    }
    return mapping.get(normalized, "")


def _hkjc_overseas_horse_profile_evidence(url: str) -> dict[str, str]:
    evidence = {"url": url}
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    h_value = _first_value(params, "h")
    if not h_value:
        match = re.search(r"/horseprofile\?h=([^&]+)", url, re.I)
        h_value = match.group(1) if match else ""
    if h_value:
        evidence["h"] = h_value
        pieces = h_value.split("/")
        if len(pieces) >= 4:
            evidence["meeting_date"] = pieces[0]
            evidence["meeting_venue_code"] = pieces[1]
            evidence["race_no"] = pieces[2]
            evidence["simulcastHorseId"] = pieces[3]
        if len(pieces) >= 5:
            evidence["horse_no"] = pieces[4]
    return evidence


def _hkjc_overseas_region(en_card: dict[str, Any], zh_card: dict[str, Any], race_key: HKJCOverseasRaceKey) -> str:
    raw_values = [
        str(en_card.get("raw_region") or ""),
        str(zh_card.get("raw_region") or ""),
        race_key.racecourse,
    ]
    for raw in raw_values:
        region = _hkjc_overseas_region_from_text(raw)
        if region:
            return region
    return "other"


def _hkjc_overseas_region_from_text(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    mapping = {
        "hk": "hk",
        "hong_kong": "hk",
        "香港": "hk",
        "gb": "gb",
        "uk": "gb",
        "united_kingdom": "gb",
        "england": "gb",
        "英國": "gb",
        "英国": "gb",
        "fr": "fr",
        "france": "fr",
        "法國": "fr",
        "法国": "fr",
        "us": "us",
        "usa": "us",
        "united_states": "us",
        "america": "us",
        "美國": "us",
        "美国": "us",
        "jp": "jp",
        "japan": "jp",
        "日本": "jp",
    }
    if normalized in mapping:
        return mapping[normalized]
    if normalized in {"south_africa", "germany", "australia", "ireland", "korea", "uae", "new_zealand"}:
        return "other"
    if re.fullmatch(r"s\d+", normalized):
        return "other"
    return ""


def _race_grade_from_name(name: str) -> str:
    upper = (name or "").upper()
    match = re.search(r"\bG(?:ROUP|RADE)?\s*([123])\b|\bG([123])\b", upper)
    if not match:
        return ""
    grade = match.group(1) or match.group(2)
    return f"G{grade}"


def _region_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "hk" in path or "hkjc" in parsed.netloc:
        return "hk"
    if "jpn" in path or "jp" in path:
        return "jp"
    return "other"


def parse_source_html(html: str, *, source: str, source_url: str = "", fallback_region: str = "other") -> list[RawSeedRecord]:
    soup = BeautifulSoup(html or "", "lxml")
    records: list[RawSeedRecord] = []
    for table in soup.find_all("table"):
        rows = _table_rows(table)
        if not rows:
            continue
        headers = [_header_key(item) for item in rows[0]]
        if not any(headers):
            continue
        for values in rows[1:]:
            row = {headers[index]: values[index].strip() for index in range(min(len(headers), len(values))) if headers[index]}
            records.extend(_records_from_row(row, source=source, source_url=source_url, fallback_region=fallback_region))
    records.extend(_records_from_text_blocks(soup.get_text("\n"), source=source, source_url=source_url, fallback_region=fallback_region))
    return _dedupe_raw_records(records)


def _collect_hkjc_horse_detail_records(
    client: SeedNetworkClient,
    *,
    html: str,
    source_url: str,
    limit_horses: int | None = None,
) -> list[RawSeedRecord]:
    records: list[RawSeedRecord] = []
    for letter_url in _hkjc_letter_urls(html, source_url=source_url):
        if limit_horses is not None and len(records) >= limit_horses:
            break
        letter_html = client.get_text(letter_url, source="hkjc")
        if not letter_html:
            continue
        records.extend(
            _collect_hkjc_horse_detail_records(
                client,
                html=letter_html,
                source_url=letter_url,
                limit_horses=None if limit_horses is None else max(0, limit_horses - len(records)),
            )
        )
    for link in _hkjc_horse_links(html, source_url=source_url):
        if limit_horses is not None and len(records) >= limit_horses:
            break
        detail_html = client.get_text(link["zh_url"], source="hkjc")
        if not detail_html:
            continue
        record = _hkjc_record_from_horse_detail(
            detail_html,
            english_name=link["english_name"],
            horse_id=link["horse_id"],
            source_url=link["zh_url"],
        )
        if record:
            records.append(record)
    return _dedupe_raw_records(records)


def _hkjc_letter_urls(html: str, *, source_url: str) -> list[str]:
    parsed = urlparse(source_url)
    if "selecthorse" not in parsed.path.lower() or "selecthorsebychar" in parsed.path.lower():
        return []
    soup = BeautifulSoup(html or "", "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="selecthorsebychar"]'):
        href = str(anchor.get("href") or "")
        absolute = urljoin(source_url, href)
        query = parse_qs(urlparse(absolute).query)
        order_type = (query.get("ordertype") or [""])[0].strip()
        if not order_type or not re.fullmatch(r"[A-Z]", order_type):
            continue
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)
    return urls


def _hkjc_horse_links(html: str, *, source_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "lxml")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="horseid="]'):
        english_name = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if not english_name or not re.search(r"[A-Za-z]", english_name):
            continue
        href = str(anchor.get("href") or "")
        absolute = urljoin(source_url, href)
        horse_id = _query_param(absolute, "horseid")
        if not horse_id or horse_id in seen:
            continue
        seen.add(horse_id)
        links.append(
            {
                "horse_id": horse_id,
                "english_name": english_name,
                "zh_url": _hkjc_zh_hk_url(absolute),
            }
        )
    return links


def _hkjc_record_from_horse_detail(html: str, *, english_name: str, horse_id: str, source_url: str) -> RawSeedRecord | None:
    soup = BeautifulSoup(html or "", "lxml")
    title_node = soup.select_one("table.horseProfile span.title_text") or soup.find("title")
    title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True) if title_node else "").strip()
    target = _hkjc_chinese_horse_name_from_title(title)
    if not target:
        return None
    return RawSeedRecord(
        term_type=TermType.HORSE,
        source_language=SourceLanguage.ENGLISH,
        source_text=english_name,
        target_zh=to_simplified_chinese(target),
        original_target_zh=target,
        source="hkjc",
        region="hk",
        entity_key=stable_entity_key(horse_id, english_name, target),
        evidence_url=source_url,
    )


def _hkjc_chinese_horse_name_from_title(title: str) -> str:
    value = re.sub(r"\s*-\s*.*$", "", title or "").strip()
    value = re.sub(r"\s*\([A-Z0-9]+\)\s*$", "", value).strip()
    if not value or not re.search(r"[\u4e00-\u9fff]", value):
        return ""
    return value


def _query_param(url: str, name: str) -> str:
    values = parse_qs(urlparse(url).query).get(name)
    return values[0].strip() if values else ""


def _hkjc_zh_hk_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    path = re.sub(r"/en-us/", "/zh-hk/", path, count=1, flags=re.IGNORECASE)
    return urlunparse(parsed._replace(path=path))


def _table_rows(table) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def _header_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    normalized = normalized.replace(" ", "_").replace("-", "_")
    mapping = {
        "english_name": "english_name",
        "英文馬名": "english_name",
        "英文马名": "english_name",
        "horse": "english_name",
        "horse_name": "english_name",
        "chinese_name": "target_zh",
        "中文馬名": "target_zh",
        "中文马名": "target_zh",
        "中文譯名": "target_zh",
        "中文译名": "target_zh",
        "日文馬名": "japanese_name",
        "日文马名": "japanese_name",
        "japanese_name": "japanese_name",
        "former_name": "former_name",
        "來港前名": "former_name",
        "来港前名": "former_name",
        "region": "region",
        "代表地區": "region",
        "代表地区": "region",
        "原產地": "origin",
        "原产地": "origin",
        "term_type": "term_type",
        "類型": "term_type",
        "类型": "term_type",
        "race_name": "race_name",
        "賽事": "race_name",
        "赛事": "race_name",
        "jockey": "jockey",
        "騎師": "jockey",
        "骑师": "jockey",
        "trainer": "trainer",
        "練馬師": "trainer",
        "练马师": "trainer",
        "racecourse": "racecourse",
        "馬場": "racecourse",
        "马场": "racecourse",
        "term": "term",
        "術語": "term",
        "术语": "term",
    }
    return mapping.get(normalized, normalized)


def _records_from_row(row: dict[str, str], *, source: str, source_url: str, fallback_region: str) -> list[RawSeedRecord]:
    target = row.get("target_zh", "").strip()
    if not target:
        return []
    term_type = _term_type_from_row(row)
    if term_type not in SUPPORTED_TERM_TYPES:
        return []
    region = normalize_region(row.get("region") or row.get("origin") or fallback_region)
    english_name = row.get("english_name", "").strip()
    japanese_name = row.get("japanese_name", "").strip()
    term_text = row.get("term", "").strip()
    source_text = _source_text_for_row(term_type, english_name, japanese_name, term_text, row)
    if not source_text:
        return []
    source_language = _source_language_for_text(source_text)
    aliases_source = [value for value in [row.get("former_name", ""), english_name if source_language != SourceLanguage.ENGLISH else "", japanese_name if source_language != SourceLanguage.JAPANESE else ""] if value]
    entity_key = stable_entity_key(english_name, japanese_name, source_text, target)
    return [
        RawSeedRecord(
            term_type=term_type,
            source_language=source_language,
            source_text=source_text,
            target_zh=to_simplified_chinese(target),
            original_target_zh=target,
            source=source,
            region=region,
            entity_key=entity_key,
            aliases_source=aliases_source,
            evidence_url=source_url,
        )
    ]


def _term_type_from_row(row: dict[str, str]) -> str:
    explicit = (row.get("term_type") or "").strip().lower()
    aliases = {
        "horse": TermType.HORSE,
        "馬名": TermType.HORSE,
        "马名": TermType.HORSE,
        "race": TermType.RACE,
        "賽事": TermType.RACE,
        "赛事": TermType.RACE,
        "jockey": TermType.JOCKEY,
        "騎師": TermType.JOCKEY,
        "骑师": TermType.JOCKEY,
        "trainer": TermType.TRAINER,
        "練馬師": TermType.TRAINER,
        "练马师": TermType.TRAINER,
        "racecourse": TermType.RACECOURSE,
        "馬場": TermType.RACECOURSE,
        "马场": TermType.RACECOURSE,
        "fixed_phrase": TermType.FIXED_PHRASE,
        "術語": TermType.FIXED_PHRASE,
        "术语": TermType.FIXED_PHRASE,
    }
    if explicit in aliases:
        return aliases[explicit]
    for field_name, term_type in (
        ("race_name", TermType.RACE),
        ("jockey", TermType.JOCKEY),
        ("trainer", TermType.TRAINER),
        ("racecourse", TermType.RACECOURSE),
        ("term", TermType.FIXED_PHRASE),
    ):
        if row.get(field_name):
            return term_type
    return TermType.HORSE


def _source_text_for_row(term_type: str, english_name: str, japanese_name: str, term_text: str, row: dict[str, str]) -> str:
    if term_type == TermType.HORSE:
        return japanese_name or english_name
    if term_type == TermType.RACE:
        return row.get("race_name", "").strip() or english_name or japanese_name
    if term_type == TermType.JOCKEY:
        return row.get("jockey", "").strip() or term_text or english_name
    if term_type == TermType.TRAINER:
        return row.get("trainer", "").strip() or term_text or english_name
    if term_type == TermType.RACECOURSE:
        return row.get("racecourse", "").strip() or term_text or english_name
    return term_text or english_name or japanese_name


def _source_language_for_text(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text or ""):
        return SourceLanguage.JAPANESE
    if re.search(r"[\u4e00-\u9fff]", text or ""):
        return SourceLanguage.CHINESE_TRADITIONAL
    return SourceLanguage.ENGLISH


def _records_from_text_blocks(text: str, *, source: str, source_url: str, fallback_region: str) -> list[RawSeedRecord]:
    records: list[RawSeedRecord] = []
    for line in (text or "").splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or len(normalized) > 120:
            continue
        match = re.match(r"^(?P<ja>[\u30a0-\u30ffー]+)\s+(?P<en>[A-Za-z][A-Za-z' .-]+)\s+(?P<zh>[\u4e00-\u9fff]{2,20})$", normalized)
        if not match:
            continue
        records.append(
            RawSeedRecord(
                term_type=TermType.HORSE,
                source_language=SourceLanguage.JAPANESE,
                source_text=match.group("ja"),
                target_zh=to_simplified_chinese(match.group("zh")),
                original_target_zh=match.group("zh"),
                source=source,
                region=normalize_region(fallback_region),
                entity_key=stable_entity_key(match.group("en"), match.group("ja")),
                aliases_source=[match.group("en")],
                evidence_url=source_url,
            )
        )
    return records


def _dedupe_raw_records(records: list[RawSeedRecord]) -> list[RawSeedRecord]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[RawSeedRecord] = []
    for record in records:
        key = (
            record.term_type,
            record.source_language,
            source_text_identity(record.source_text),
            record.source,
            source_text_identity(record.target_zh),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def build_seed_result(records: list[RawSeedRecord], *, requests_info: list[RequestRecord] | None = None, failures: list[dict[str, str]] | None = None) -> BuildResult:
    requests_info = requests_info or []
    failures = failures or []
    groups: dict[tuple[str, str], list[RawSeedRecord]] = {}
    for record in records:
        if record.term_type not in SUPPORTED_TERM_TYPES:
            continue
        groups.setdefault((record.term_type, record.entity_key or stable_entity_key(record.source_text)), []).append(record)

    candidate_rows: list[dict[str, str]] = []
    conflict_rows: list[dict[str, str]] = []
    source_evidence = {
        "generated_at": datetime.now().isoformat(),
        "candidates": [],
        "conflicts": [],
        "skipped_races": [item for item in failures if item.get("type") == "skipped_races"],
        "failures": [item for item in failures if item.get("type") != "skipped_races"],
    }
    for (_term_type, _entity_key), group in sorted(groups.items(), key=lambda item: _group_sort_key(item[1])):
        primary = _select_primary_record(group)
        aliases_zh = _target_aliases(group, primary.target_zh)
        if aliases_zh:
            rows = _conflict_rows(group, primary, aliases_zh)
            conflict_rows.extend(rows)
            source_evidence["conflicts"].extend(rows)
        for record in _output_records_for_group(group, primary):
            candidate_rows.append(_candidate_row(record, primary, aliases_zh))
            source_evidence["candidates"].append(_record_evidence(record, primary))

    blocking_failures = [item for item in failures if item.get("type") != "skipped_races"]
    summary = {
        "generated_at": datetime.now().isoformat(),
        "candidate_count": len(candidate_rows),
        "conflict_count": len(conflict_rows),
        "request_count": len([item for item in requests_info if item.status_code is not None or item.error]),
        "requests": [item.to_dict() for item in requests_info],
        "failures": failures,
        "skipped_races": source_evidence["skipped_races"],
        "incomplete": bool(blocking_failures or any(item.error for item in requests_info)),
    }
    return BuildResult(candidates=candidate_rows, conflicts=conflict_rows, summary=summary, source_evidence=source_evidence)


def _group_sort_key(group: list[RawSeedRecord]) -> tuple[int, int, str]:
    region = min((REGION_ORDER.get(normalize_region(record.region), REGION_ORDER["other"]) for record in group), default=REGION_ORDER["other"])
    source = min((SOURCE_ORDER.get(record.source, 99) for record in group), default=99)
    key = min((source_text_identity(record.source_text) for record in group if record.source_text), default="")
    return region, source, key


def _select_primary_record(group: list[RawSeedRecord]) -> RawSeedRecord:
    return sorted(
        group,
        key=lambda record: (
            SOURCE_ORDER.get(record.source, 99),
            REGION_ORDER.get(normalize_region(record.region), REGION_ORDER["other"]),
            source_text_identity(record.source_text),
        ),
    )[0]


def _target_aliases(group: list[RawSeedRecord], primary_target: str) -> list[str]:
    aliases: list[str] = []
    seen = {source_text_identity(primary_target)}
    for record in group:
        for value in [record.target_zh, *record.aliases_zh]:
            simplified = to_simplified_chinese(value)
            key = source_text_identity(simplified)
            if simplified and key not in seen:
                seen.add(key)
                aliases.append(simplified)
    return aliases


def _conflict_rows(group: list[RawSeedRecord], primary: RawSeedRecord, aliases_zh: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in group:
        if source_text_identity(record.target_zh) == source_text_identity(primary.target_zh):
            continue
        rows.append(
            {
                "term_type": primary.term_type,
                "entity_key": primary.entity_key,
                "region": normalize_region(primary.region),
                "recommended_source": primary.source,
                "recommended_target_zh": primary.target_zh,
                "alternate_source": record.source,
                "alternate_target_zh": record.target_zh,
                "aliases_zh": serialize_aliases(aliases_zh),
                "conflict_type": "target_zh_mismatch",
                "evidence": _evidence_summary(group),
                "notes": "HKJC 优先；民间来源保留为别名或备注。",
            }
        )
    return rows


def _output_records_for_group(group: list[RawSeedRecord], primary: RawSeedRecord) -> list[RawSeedRecord]:
    official = [record for record in group if record.source == primary.source]
    if official:
        records = sorted(official, key=lambda record: (record.source_language != SourceLanguage.ENGLISH, source_text_identity(record.source_text)))
        result: list[RawSeedRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for record in records:
            key = (record.term_type, record.source_language, source_text_identity(record.source_text))
            if key in seen:
                continue
            seen.add(key)
            result.append(record)
        return result
    return [primary]


def _candidate_row(record: RawSeedRecord, primary: RawSeedRecord, aliases_zh: list[str]) -> dict[str, str]:
    source_tier = "official" if primary.source in OFFICIAL_SOURCES else "community"
    requires_review = "true" if source_tier == "community" else "false"
    notes = {
        "region": normalize_region(primary.region),
        "source": primary.source,
        "sources": ",".join(sorted({item.source for item in [record, primary]})),
        "source_tier": source_tier,
        "requires_review": requires_review,
        "evidence": record.evidence_url or primary.evidence_url,
    }
    original_values = []
    for item in [record, primary]:
        if item.original_target_zh and item.original_target_zh != item.target_zh:
            original_values.append(item.original_target_zh)
    if original_values:
        notes["original_zh_hant"] = "|".join(dict.fromkeys(original_values))
    priority = 100 if source_tier == "official" else 80
    return {
        "term_type": primary.term_type,
        "source_language": record.source_language,
        "racing_region": import_region_value(primary.region),
        "source_ja": record.source_text,
        "target_zh": primary.target_zh,
        "aliases_ja": serialize_aliases(record.aliases_source),
        "aliases_zh": serialize_aliases(aliases_zh),
        "priority": str(priority),
        "is_active": "true",
        "notes": "; ".join(f"{key}={value}" for key, value in notes.items() if value),
        "race_grade": record.race_grade,
    }


def _evidence_summary(group: list[RawSeedRecord]) -> str:
    values = []
    for record in group:
        if record.evidence_url:
            values.append(f"{record.source}:{record.evidence_url}")
    return " | ".join(dict.fromkeys(values))


def _record_evidence(record: RawSeedRecord, primary: RawSeedRecord) -> dict[str, Any]:
    payload = {
        "term_type": primary.term_type,
        "source_language": record.source_language,
        "source_text": record.source_text,
        "target_zh": primary.target_zh,
        "source": record.source,
        "source_tier": record.source_tier,
        "region": normalize_region(primary.region),
        "racing_region": import_region_value(primary.region),
        "evidence_url": record.evidence_url or primary.evidence_url,
    }
    if record.original_target_zh:
        payload["original_zh_hant"] = record.original_target_zh
    if record.evidence:
        payload.update(record.evidence)
    return payload


def write_seed_files(result: BuildResult, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "seed_candidates.csv"
    conflicts_path = output_dir / "seed_conflicts.csv"
    summary_path = output_dir / "summary.json"
    source_evidence_path = output_dir / "source_evidence.json"
    _write_csv(candidates_path, CANDIDATE_HEADERS, result.candidates)
    _write_csv(conflicts_path, CONFLICT_HEADERS, result.conflicts)
    source_evidence_path.write_text(json.dumps(result.source_evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        **result.summary,
        "output_dir": str(output_dir),
        "candidates_path": str(candidates_path),
        "conflicts_path": str(conflicts_path),
        "source_evidence_path": str(source_evidence_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "candidates_path": str(candidates_path),
        "conflicts_path": str(conflicts_path),
        "summary_path": str(summary_path),
        "source_evidence_path": str(source_evidence_path),
    }


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def csv_text_for_candidates(rows: list[dict[str, str]]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=CANDIDATE_HEADERS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return stream.getvalue()
