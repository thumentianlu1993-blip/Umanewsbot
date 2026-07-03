from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone

from stable.models import SourceLanguage, TermType
from stable.services.term_admin import serialize_aliases, source_text_identity


CANDIDATE_HEADERS = [
    "term_type",
    "source_language",
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
SUPPORTED_TERM_TYPES = {
    TermType.HORSE,
    TermType.RACE,
    TermType.JOCKEY,
    TermType.TRAINER,
    TermType.RACECOURSE,
    TermType.FIXED_PHRASE,
}
SUPPORTED_SOURCES = {"hkjc", "wpstud"}
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
SOURCE_ORDER = {"hkjc": 0, "wpstud": 10}
DEFAULT_SOURCE_URLS = {
    "hkjc": [
        "https://racing.hkjc.com/en-us/local/information/selecthorse",
        "https://racing.hkjc.com/en-us/local/info/horse-former-name",
        "https://racing.hkjc.com/en-us/overseas/",
        "https://racing.hkjc.com/racing/english/learn-racing/learn-question.aspx",
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

    @property
    def source_tier(self) -> str:
        return "official" if self.source == "hkjc" else "community"


@dataclass
class BuildResult:
    candidates: list[dict[str, str]]
    conflicts: list[dict[str, str]]
    summary: dict[str, Any]


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


def stable_entity_key(*values: str) -> str:
    for value in values:
        key = source_text_identity(value or "")
        if key:
            return key
    return ""


def validate_sources(sources: list[str]) -> list[str]:
    normalized = [source.strip().lower() for source in sources if source and source.strip()]
    if not normalized:
        raise TermbaseSeedError("需要至少选择一个来源：hkjc 或 wpstud。")
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
    root = input_dir or builtin_fixture_dir()
    records: list[RawSeedRecord] = []
    failures: list[dict[str, str]] = []
    requests_info: list[RequestRecord] = []

    if options.allow_network:
        client = SeedNetworkClient(options)
        for source in selected_sources:
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
        requests_info.extend(client.requests)
        return records, requests_info, failures

    for source in selected_sources:
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
    if source == "wpstud":
        return ["wpstud*.html", "wpstud*.htm", "wp_stud*.html"]
    return []


def _source_url_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.find(attrs={"data-source-url": True})
    return str(node.get("data-source-url", "")).strip() if node else ""


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
    seen: set[tuple[str, str, str, str]] = set()
    result: list[RawSeedRecord] = []
    for record in records:
        key = (record.term_type, record.source_language, source_text_identity(record.source_text), record.source)
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
    for (_term_type, _entity_key), group in sorted(groups.items(), key=lambda item: _group_sort_key(item[1])):
        primary = _select_primary_record(group)
        aliases_zh = _target_aliases(group, primary.target_zh)
        if aliases_zh:
            conflict_rows.extend(_conflict_rows(group, primary, aliases_zh))
        for record in _output_records_for_group(group, primary):
            candidate_rows.append(_candidate_row(record, primary, aliases_zh))

    summary = {
        "generated_at": datetime.now().isoformat(),
        "candidate_count": len(candidate_rows),
        "conflict_count": len(conflict_rows),
        "request_count": len([item for item in requests_info if item.status_code is not None or item.error]),
        "requests": [item.to_dict() for item in requests_info],
        "failures": failures,
        "incomplete": bool(failures or any(item.error for item in requests_info)),
    }
    return BuildResult(candidates=candidate_rows, conflicts=conflict_rows, summary=summary)


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
        return sorted(official, key=lambda record: (record.source_language != SourceLanguage.ENGLISH, source_text_identity(record.source_text)))
    return [primary]


def _candidate_row(record: RawSeedRecord, primary: RawSeedRecord, aliases_zh: list[str]) -> dict[str, str]:
    source_tier = "official" if primary.source == "hkjc" else "community"
    requires_review = "true" if source_tier == "community" else "false"
    notes = {
        "region": normalize_region(primary.region),
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


def write_seed_files(result: BuildResult, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "seed_candidates.csv"
    conflicts_path = output_dir / "seed_conflicts.csv"
    summary_path = output_dir / "summary.json"
    _write_csv(candidates_path, CANDIDATE_HEADERS, result.candidates)
    _write_csv(conflicts_path, CONFLICT_HEADERS, result.conflicts)
    summary = {**result.summary, "output_dir": str(output_dir), "candidates_path": str(candidates_path), "conflicts_path": str(conflicts_path)}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "candidates_path": str(candidates_path),
        "conflicts_path": str(conflicts_path),
        "summary_path": str(summary_path),
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
