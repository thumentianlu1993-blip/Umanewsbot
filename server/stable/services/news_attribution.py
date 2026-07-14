from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from django.conf import settings
from django.db.models import Q, QuerySet

from stable.models import (
    AttributionStatus,
    ContentCategory,
    NewsArticle,
    NewsArticleRelatedRegion,
    NewsSource,
    RacingRegion,
    SourceLanguage,
    SourceSite,
    TermEntry,
    TermType,
)
from stable.services.terms import source_term_matches_text, source_terms_by_entry


SUPPORTED_REGIONS = {
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
    RacingRegion.OTHER,
}
ENTITY_TERM_TYPES = {TermType.HORSE, TermType.JOCKEY, TermType.TRAINER, TermType.OWNER}
EVENT_TERM_TYPES = {TermType.RACE, TermType.RACECOURSE}
FRANCE_CONTEXT_TERM_TYPES = {TermType.FARM, TermType.ORG}
REGION_ORDER = [
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
    RacingRegion.OTHER,
]
REGION_KEYWORDS = {
    RacingRegion.JAPAN: [
        "japan",
        "japanese",
        "jra",
        "nar",
        "tokyo racecourse",
        "nakayama",
        "kyoto",
        "hanshin",
        "sapporo",
        "新潟",
        "東京",
        "中山",
        "京都",
        "阪神",
    ],
    RacingRegion.HONG_KONG: [
        "hong kong",
        "hkjc",
        "sha tin",
        "happy valley",
        "香港",
        "沙田",
        "跑马地",
    ],
    RacingRegion.UNITED_KINGDOM: [
        "britain",
        "british",
        "ascot",
        "epsom",
        "newmarket",
        "york",
        "goodwood",
        "cheltenham",
        "doncaster",
    ],
    RacingRegion.FRANCE: [
        "france",
        "french",
        "france galop",
        "longchamp",
        "chantilly",
        "deauville",
        "saint-cloud",
        "saint cloud",
        "prix ",
        "arc de triomphe",
        "arqana",
    ],
    RacingRegion.UNITED_STATES: [
        "united states",
        "america",
        "american",
        "kentucky",
        "churchill",
        "saratoga",
        "belmont",
        "breeders' cup",
        "breeders cup",
        "del mar",
        "keeneland",
    ],
}
EVENT_REGION_KEYWORDS = {
    RacingRegion.JAPAN: [
        "tokyo racecourse",
        "nakayama racecourse",
        "kyoto racecourse",
        "hanshin racecourse",
        "sapporo racecourse",
        "新潟競馬場",
        "東京競馬場",
        "中山競馬場",
        "京都競馬場",
        "阪神競馬場",
    ],
    RacingRegion.HONG_KONG: ["sha tin", "happy valley", "沙田", "跑马地"],
    RacingRegion.UNITED_KINGDOM: [
        "ascot",
        "epsom",
        "newmarket",
        "at york",
        "york racecourse",
        "goodwood",
        "cheltenham",
        "doncaster",
    ],
    RacingRegion.FRANCE: [
        "longchamp",
        "chantilly",
        "deauville",
        "saint-cloud",
        "saint cloud",
        "prix ",
        "arc de triomphe",
    ],
    RacingRegion.UNITED_STATES: [
        "churchill",
        "saratoga",
        "belmont",
        "breeders' cup",
        "breeders cup",
        "del mar",
        "keeneland",
    ],
}
IRELAND_KEYWORDS = ["ireland", "irish", "curragh", "leopardstown", "fairyhouse", "naas"]
OUT_OF_SCOPE_TITLE_KEYWORDS = [
    "australia",
    "australian",
    "canada",
    "canadian",
    "ontario",
    "saudi arabia",
    "saudi",
    "dubai",
    "uae",
    "yulong",
    "オーストラリア",
    "サウジアラビア",
    "ドバイ",
]
GLOBAL_SOURCE_SITES = {SourceSite.TDN, SourceSite.TDN_FRANCE}
ATTRIBUTION_RULE_VERSION = "multiregion-v3"
ENFORCE_NEW_ARTICLES_STAGES = {
    "new_articles",
    "web_test_groups",
    "recent_backfill",
    "formal_groups",
}


@dataclass(frozen=True)
class AttributionResult:
    primary_region: str
    related_regions: list[str] = field(default_factory=list)
    content_category: str = ContentCategory.NEWS
    source: str = "auto"
    reason: str = ""
    evidence: dict = field(default_factory=dict)
    status: str = AttributionStatus.APPLIED
    confidence: int = 0
    confidence_band: str = "low"
    rule_version: str = ATTRIBUTION_RULE_VERSION
    conflict_reasons: list[str] = field(default_factory=list)


@dataclass
class AttributionTermIndex:
    candidates_by_key: dict[str, list[tuple[int, int, str]]]
    candidate_count: int = 0

    @staticmethod
    def _candidate_key(candidate: str) -> str:
        normalized = unicodedata.normalize("NFKC", candidate or "").casefold()
        latin_tokens = re.findall(r"[0-9a-z]+", normalized)
        if latin_tokens:
            return max(latin_tokens, key=lambda item: (len(item), item))
        compact = "".join(normalized.split())
        return compact[:2]

    @staticmethod
    def _text_keys(text: str) -> set[str]:
        normalized = unicodedata.normalize("NFKC", text or "").casefold()
        keys = set(re.findall(r"[0-9a-z]+", normalized))
        compact = "".join(normalized.split())
        keys.update(compact[index : index + 2] for index in range(max(0, len(compact) - 1)))
        if compact:
            keys.add(compact[:1])
        return keys

    @classmethod
    def build(cls, terms_by_entry: dict[int, list[str]]) -> "AttributionTermIndex":
        candidates: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        candidate_count = 0
        for entry_id, terms in terms_by_entry.items():
            for order, term in enumerate(terms):
                key = cls._candidate_key(term)
                if not key:
                    continue
                candidates[key].append((entry_id, order, term))
                candidate_count += 1
        return cls(candidates_by_key=dict(candidates), candidate_count=candidate_count)

    def match(self, text: str, source_language: str) -> dict[int, str]:
        best_matches: dict[int, tuple[int, str]] = {}
        for key in self._text_keys(text):
            for entry_id, order, term in self.candidates_by_key.get(key, []):
                current = best_matches.get(entry_id)
                if current is not None and current[0] <= order:
                    continue
                if source_term_matches_text(text, term, source_language):
                    best_matches[entry_id] = (order, term)
        return {entry_id: match[1] for entry_id, match in best_matches.items()}


@dataclass
class AttributionBatchContext:
    entries: list[TermEntry]
    entries_by_id: dict[int, TermEntry]
    terms_by_language: dict[str, dict[int, list[str]]]
    term_indexes: dict[str, AttributionTermIndex]
    source_configs_by_id: dict[int, NewsSource]
    preload_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls, articles: Iterable[NewsArticle] | None = None) -> "AttributionBatchContext":
        article_rows = list(articles or [])
        source_configs_by_id: dict[int, NewsSource] = {}
        missing_source_ids: set[int] = set()
        for article in article_rows:
            source_id = article.source_config_id
            if not source_id:
                continue
            cached = article._state.fields_cache.get("source_config")
            if cached is not None:
                source_configs_by_id[source_id] = cached
            else:
                missing_source_ids.add(source_id)
        missing_source_ids.difference_update(source_configs_by_id)
        if missing_source_ids:
            source_configs_by_id.update(NewsSource.objects.in_bulk(missing_source_ids))

        entries = list(
            TermEntry.objects.filter(
                is_active=True,
                term_type__in=[*ENTITY_TERM_TYPES, *EVENT_TERM_TYPES, *FRANCE_CONTEXT_TERM_TYPES],
                racing_region__in=SUPPORTED_REGIONS,
            ).exclude(racing_region="")
        )
        languages = [SourceLanguage.JAPANESE, SourceLanguage.ENGLISH, SourceLanguage.CHINESE_TRADITIONAL]
        terms_by_language = {language: source_terms_by_entry(entries, language) for language in languages}
        term_indexes = {
            language: AttributionTermIndex.build(terms_by_language[language])
            for language in languages
        }
        return cls(
            entries=entries,
            entries_by_id={entry.pk: entry for entry in entries},
            terms_by_language=terms_by_language,
            term_indexes=term_indexes,
            source_configs_by_id=source_configs_by_id,
            preload_counts={
                "term_index_builds": 1,
                "terms": len(entries),
                "indexed_candidates": sum(index.candidate_count for index in term_indexes.values()),
                "sources": len(source_configs_by_id),
            },
        )


def attribution_mode() -> str:
    mode = str(getattr(settings, "MULTIREGION_ATTRIBUTION_MODE", "") or "").strip().lower()
    if mode in {"off", "shadow", "enforce"}:
        return mode
    return "enforce" if bool(getattr(settings, "MULTIREGION_ATTRIBUTION_ENABLED", False)) else "off"


def attribution_summary_namespace(summary: dict | None, namespace: str) -> dict:
    payload = summary or {}
    if "applied" in payload or "shadow" in payload:
        value = payload.get(namespace)
        return value if isinstance(value, dict) else {}
    return payload if namespace == "applied" else {}


def related_region_queries_enabled() -> bool:
    rollout_stage = str(getattr(settings, "MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE", "off") or "off").strip().lower()
    return (
        attribution_mode() == "enforce"
        and rollout_stage in {"web_test_groups", "recent_backfill", "formal_groups"}
        and bool(getattr(settings, "MULTIREGION_RELATED_REGION_QUERIES_ENABLED", False))
    )


def normalize_region(value: str | None) -> str:
    candidate = (value or "").strip()
    return candidate if candidate in SUPPORTED_REGIONS else ""


def _dedupe_regions(regions: Iterable[str], *, exclude: str = "") -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for region in regions:
        normalized = normalize_region(region)
        if not normalized or normalized == exclude or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def article_region_set(article: NewsArticle, *, include_related: bool = True) -> set[str]:
    override = getattr(article, "_attribution_region_override", None)
    if override is not None:
        return {region for region in override if normalize_region(region)}
    regions = {article.racing_region} if normalize_region(article.racing_region) else set()
    if not include_related:
        return regions
    prefetched = getattr(article, "_prefetched_objects_cache", {}).get("related_region_links")
    links = prefetched if prefetched is not None else article.related_region_links.all()
    for link in links:
        region = normalize_region(link.region)
        if region:
            regions.add(region)
    return regions


def region_label(region: str) -> str:
    try:
        return RacingRegion(region).label
    except ValueError:
        return region or "-"


def article_region_labels(article: NewsArticle, *, include_related: bool = True) -> list[str]:
    primary = normalize_region(article.racing_region)
    labels = [region_label(primary)] if primary else []
    labels.extend(article_related_region_labels(article, include_related=include_related))
    return labels


def article_related_region_labels(article: NewsArticle, *, include_related: bool = True) -> list[str]:
    if not include_related:
        return []
    regions = article_region_set(article)
    regions.discard(normalize_region(article.racing_region))
    ordered = [region for region in REGION_ORDER if region in regions]
    return [region_label(region) for region in ordered]


def filter_articles_visible_in_region(queryset: QuerySet, region: str) -> QuerySet:
    normalized = normalize_region(region)
    if not normalized:
        return queryset
    if not related_region_queries_enabled():
        return queryset.filter(racing_region=normalized)
    return queryset.filter(Q(racing_region=normalized) | Q(related_region_links__region=normalized)).distinct()


def is_article_visible_in_region(article: NewsArticle, region: str) -> bool:
    normalized = normalize_region(region)
    if not normalized:
        return True
    if not related_region_queries_enabled():
        return article.racing_region == normalized
    return normalized in article_region_set(article)


def _source_text(article: NewsArticle) -> str:
    return "\n".join(
        [
            article.title_ja or "",
            article.body_ja_normalized or article.body_ja_raw or "",
        ]
    ).strip()


def classify_news_content(article: NewsArticle) -> str:
    text = _source_text(article).casefold()
    if any(word in text for word in ["tips", "nap", "best bet", "value bet", "selection", "selections", "prediction", "preview"]):
        if any(word in text for word in ["preview", "derby preview", "race preview"]):
            return ContentCategory.PREVIEW
        return ContentCategory.TIPS
    if any(word in text for word in ["result", "results", "recap", "report", "won ", "winner", "victory"]):
        return ContentCategory.RESULT_BRIEF
    if any(word in text for word in ["racecard", "runners", "entries", "declarations", "scratchings", "field for"]):
        return ContentCategory.RACECARD_UPDATE
    if any(word in text for word in ["sale", "sales", "auction", "stud", "stallion", "broodmare", "breeding", "foal"]):
        return ContentCategory.SALES_BREEDING
    if any(word in text for word in ["interview", "q&a", "profile"]):
        return ContentCategory.FEATURE
    if any(word in text for word in ["statement", "notice", "announces", "announced", "press release"]):
        return ContentCategory.OFFICIAL_NOTICE
    return ContentCategory.NEWS


def _keyword_regions(text: str, keyword_map: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {}
    for region, keywords in (keyword_map or REGION_KEYWORDS).items():
        matches = [
            keyword
            for keyword in keywords
            if (
                source_term_matches_text(text, keyword, SourceLanguage.ENGLISH)
                if keyword.isascii()
                else keyword in text
            )
        ]
        if matches:
            evidence[region] = matches[:5]
    return evidence


def _term_regions(
    article: NewsArticle,
    text: str,
    *,
    batch_context: AttributionBatchContext | None = None,
) -> dict[str, list[dict]]:
    source_language = article.source_language or SourceLanguage.ENGLISH
    if batch_context is None:
        entries = list(
            TermEntry.objects.filter(is_active=True)
            .exclude(racing_region="")
            .filter(
                term_type__in=[*ENTITY_TERM_TYPES, *EVENT_TERM_TYPES, *FRANCE_CONTEXT_TERM_TYPES],
                racing_region__in=SUPPORTED_REGIONS,
            )
        )
        terms_by_entry = source_terms_by_entry(entries, source_language)
    else:
        entries = batch_context.entries
        terms_by_entry = batch_context.terms_by_language.get(source_language) or source_terms_by_entry(entries, source_language)
    ordinary_terms = {
        "contact",
        "class",
        "content",
        "link",
        "agent",
        "good",
        "look",
        "live",
        *[str(item).casefold() for item in getattr(settings, "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS", [])],
    }
    matches: dict[str, list[dict]] = {"event": [], "entity": [], "france_context": []}
    if batch_context is not None and source_language in batch_context.term_indexes:
        indexed_matches = batch_context.term_indexes[source_language].match(text, source_language)
        candidates = [
            (batch_context.entries_by_id[entry_id], matched)
            for entry_id, matched in indexed_matches.items()
            if entry_id in batch_context.entries_by_id
        ]
    else:
        candidates = [
            (
                entry,
                next(
                    (term for term in terms_by_entry.get(entry.pk, []) if source_term_matches_text(text, term, source_language)),
                    "",
                ),
            )
            for entry in entries
        ]
    nested_horse_terms = {
        shorter.casefold()
        for shorter_entry, shorter in candidates
        for longer_entry, longer in candidates
        if shorter
        and longer
        and shorter_entry.term_type == TermType.HORSE
        and longer_entry.term_type == TermType.HORSE
        and shorter_entry.pk != longer_entry.pk
        and len(longer) > len(shorter)
        and longer.casefold().endswith(shorter.casefold())
    }
    for entry, matched in candidates:
        if not matched:
            continue
        compact_match = "".join(matched.split())
        if entry.term_type == TermType.HORSE and matched.casefold() in nested_horse_terms:
            continue
        if (
            entry.term_type == TermType.HORSE
            and source_language != SourceLanguage.ENGLISH
            and len(compact_match) <= 2
        ):
            continue
        if source_language == SourceLanguage.ENGLISH and matched.casefold() in ordinary_terms:
            continue
        payload = {
            "term_id": entry.pk,
            "term_type": entry.term_type,
            "source_term": matched,
            "region": entry.racing_region,
            "priority": entry.priority,
        }
        if entry.term_type in EVENT_TERM_TYPES:
            matches["event"].append(payload)
        elif entry.term_type in FRANCE_CONTEXT_TERM_TYPES and entry.racing_region == RacingRegion.FRANCE:
            matches["france_context"].append(payload)
        else:
            matches["entity"].append(payload)
    return matches


def _regions_from_term_payloads(payloads: list[dict]) -> list[str]:
    return _dedupe_regions(item.get("region") for item in payloads)


def _is_global_source(
    article: NewsArticle,
    source_config: NewsSource | None,
    *,
    allow_lazy_source_config: bool = True,
) -> bool:
    config = source_config
    if config is None and allow_lazy_source_config:
        config = getattr(article, "source_config", None)
    site = getattr(config, "source_site", "") or article.source_site
    name = str(getattr(config, "name", "") or "").casefold()
    return site in GLOBAL_SOURCE_SITES or "tdn" in name or "thoroughbred daily news" in name


def _title_context_regions(title_text: str) -> tuple[list[str], dict[str, list[str]], list[str]]:
    matches = _keyword_regions(title_text)
    regions = _dedupe_regions(matches.keys())
    folded = title_text.casefold()
    if re.search(r"英(?:国|g[1-3]|ダービー|ジュライ|キング|・)", title_text.casefold()):
        regions = _dedupe_regions([RacingRegion.UNITED_KINGDOM, *regions])
    if re.search(r"仏(?:国|g[1-3]|ジャック|凱旋門|ムーラン|・)", title_text.casefold()):
        regions = _dedupe_regions([RacingRegion.FRANCE, *regions])
    if any(marker in title_text for marker in ["ジュライカップ", "ジュライC"]):
        regions = _dedupe_regions([RacingRegion.UNITED_KINGDOM, *regions])
    if any(marker in title_text for marker in ["凱旋門賞", "ジャックルマロワ賞", "ムーランドロンシャン賞"]):
        regions = _dedupe_regions([RacingRegion.FRANCE, *regions])
    out_of_scope = [keyword for keyword in OUT_OF_SCOPE_TITLE_KEYWORDS if keyword in folded]
    if re.search(r"\bdrc\b", folded):
        out_of_scope.append("dubai_racing_club")
    if "wbrr" in folded or "world's best racehorse rankings" in folded:
        out_of_scope.append("world_ranking")
    return regions, matches, out_of_scope


def _leading_entity_regions(title_text: str, payloads: list[dict]) -> list[str]:
    folded = title_text.casefold()
    regions: list[str] = []
    for payload in payloads:
        term = str(payload.get("source_term") or "").strip()
        if not term:
            continue
        position = folded.find(term.casefold())
        if position < 0 or position > 48:
            continue
        if term.isascii() and " " not in term and "-" not in term:
            continue
        regions.append(payload.get("region") or "")
    return _dedupe_regions(regions)


def _japanese_source_keeps_home_focus(title_text: str, foreign_region: str) -> bool:
    if "の結果" in title_text and re.match(
        r"^(?:英|仏)(?:国|g[1-3]|ダービー|ジュライ|キング|ジャック|凱旋門|ムーラン|・)",
        title_text.casefold(),
    ):
        return False
    if "の結果" in title_text:
        return True
    if any(marker in title_text for marker in ["馬券発売", "発売決定", "発売（"]):
        return False
    if title_text.startswith("【") and "】" in title_text:
        return True
    if any(marker in title_text for marker in ["日本馬", "JRA所属馬", "日本調教馬"]):
        return True
    if foreign_region == RacingRegion.FRANCE and any(marker in title_text for marker in ["挑戦", "登録", "予定"]):
        return True
    if "夢" in title_text:
        return True
    return False


def _explicit_title_subject_region(title_text: str) -> str:
    folded = title_text.casefold().lstrip()
    prefixes = {
        RacingRegion.HONG_KONG: ("team hong kong ", "hong kong jockey ", "hong kong trainer "),
        RacingRegion.UNITED_KINGDOM: ("english trainer ", "british trainer ", "team britain "),
        RacingRegion.FRANCE: ("french trainer ", "team france "),
        RacingRegion.JAPAN: ("japanese trainer ", "team japan "),
        RacingRegion.UNITED_STATES: ("american trainer ", "team usa ", "team united states "),
    }
    return next((region for region, values in prefixes.items() if folded.startswith(values)), "")


def _event_terms_are_ambiguous(payloads: list[dict]) -> bool:
    return bool(payloads) and all(_event_term_is_ambiguous(payload) for payload in payloads)


def _event_term_is_ambiguous(payload: dict) -> bool:
    return (
        payload.get("term_type") == TermType.RACE
        and (term := str(payload.get("source_term") or "").strip()).isascii()
        and len(term.split()) == 1
    )


def _remove_event_terms_nested_in_entities(event_payloads: list[dict], entity_payloads: list[dict]) -> list[dict]:
    entity_terms = [
        str(payload.get("source_term") or "").strip().casefold()
        for payload in entity_payloads
        if str(payload.get("source_term") or "").strip()
    ]
    return [
        payload
        for payload in event_payloads
        if not any(
            event_term != entity_term
            and re.search(rf"(?<!\w){re.escape(event_term)}(?!\w)", entity_term)
            for entity_term in entity_terms
            if (event_term := str(payload.get("source_term") or "").strip().casefold())
        )
    ]


def _credible_entity_regions(payloads: list[dict]) -> list[str]:
    return _dedupe_regions(
        payload.get("region")
        for payload in payloads
        if (term := str(payload.get("source_term") or "").strip())
        and (not term.isascii() or len(term.split()) > 1 or "-" in term)
    )


def _subject_should_outrank_event(
    title_text: str,
    *,
    leading_entity_region: str,
    event_region: str,
) -> bool:
    if not leading_entity_region or leading_entity_region == event_region:
        return False
    folded = title_text.casefold().strip()
    if folded.startswith(("english trainer ", "british trainer ")):
        return True
    return False


def infer_article_attribution(
    article: NewsArticle,
    source_config: NewsSource | None = None,
    *,
    batch_context: AttributionBatchContext | None = None,
) -> AttributionResult:
    resolved_source_config = source_config
    if resolved_source_config is None and batch_context is not None and article.source_config_id:
        resolved_source_config = batch_context.source_configs_by_id.get(article.source_config_id)
    configured_region = getattr(resolved_source_config, "racing_region", "")
    if resolved_source_config is None and batch_context is None:
        configured_region = getattr(article.source_config, "racing_region", "")
    source_region = normalize_region(
        configured_region or article.racing_region
    )
    text = _source_text(article)
    title_text = article.title_ja or ""
    lead_text = "\n".join([title_text, (article.body_ja_normalized or article.body_ja_raw or "")[:400]])
    keyword_matches = _keyword_regions(lead_text)
    title_context_regions, title_keyword_matches, out_of_scope_title_matches = _title_context_regions(title_text)
    event_keyword_matches = _keyword_regions(title_text, EVENT_REGION_KEYWORDS)
    term_matches = _term_regions(article, lead_text, batch_context=batch_context)
    title_term_matches = _term_regions(article, title_text, batch_context=batch_context)
    title_term_matches["event"] = _remove_event_terms_nested_in_entities(
        title_term_matches["event"],
        title_term_matches["entity"],
    )
    term_matches["event"] = _remove_event_terms_nested_in_entities(
        term_matches["event"],
        term_matches["entity"],
    )
    lead_event_regions = _regions_from_term_payloads(
        [payload for payload in term_matches["event"] if not _event_term_is_ambiguous(payload)]
    )
    event_regions = _dedupe_regions(
        [*event_keyword_matches.keys(), *_regions_from_term_payloads(title_term_matches["event"])]
    )
    entity_regions = _regions_from_term_payloads(title_term_matches["entity"])
    credible_entity_regions = _credible_entity_regions(title_term_matches["entity"])
    leading_entity_regions = _leading_entity_regions(title_text, title_term_matches["entity"])
    context_regions = _dedupe_regions(
        [
            *keyword_matches.keys(),
            *_regions_from_term_payloads(term_matches["france_context"]),
        ],
        exclude="",
    )
    ireland_matched = [keyword for keyword in IRELAND_KEYWORDS if keyword in title_text.casefold()]

    france_theme_markers = [
        "france galop",
        "arqana",
        "haras ",
        "french stud",
        "chantilly training centre",
        "chantilly training center",
    ]
    france_theme_matches = [marker for marker in france_theme_markers if marker in lead_text.casefold()]
    conflict_reasons: list[str] = []
    related: list[str] = []
    source_is_global = _is_global_source(
        article,
        resolved_source_config,
        allow_lazy_source_config=batch_context is None,
    )
    explicit_subject_region = _explicit_title_subject_region(title_text)

    if len(event_regions) > 1:
        title_event_candidates = [region for region in event_regions if region in title_context_regions]
        if source_region in event_regions and not title_event_candidates:
            event_regions = [source_region]
        elif len(title_event_candidates) == 1:
            event_regions = title_event_candidates

    if (
        len(event_regions) == 1
        and event_regions[0] != source_region
        and event_regions[0] not in title_context_regions
        and not event_keyword_matches
        and _event_terms_are_ambiguous(title_term_matches["event"])
    ):
        event_regions = []

    if source_is_global and not event_regions and len(lead_event_regions) == 1:
        event_regions = lead_event_regions

    if len(event_regions) > 1:
        conflict_reasons.append("conflicting_event_centres")
        primary = source_region or RacingRegion.JAPAN
        related = []
        status = AttributionStatus.NEEDS_REVIEW
        reason = "conflicting_event_centres"
    elif source_is_global and out_of_scope_title_matches and not event_regions and not title_context_regions:
        primary = RacingRegion.OTHER
        status = AttributionStatus.NEEDS_REVIEW
        reason = "out_of_scope_title_region"
        conflict_reasons.append("out_of_scope_region")
    else:
        event_region = event_regions[0] if event_regions else ""
        title_context_region = title_context_regions[0] if len(title_context_regions) == 1 else ""
        leading_entity_region = leading_entity_regions[0] if len(leading_entity_regions) == 1 else ""
        if source_is_global:
            if out_of_scope_title_matches and not event_region and title_context_regions:
                primary = source_region or title_context_regions[0]
                related = [RacingRegion.OTHER]
                reason = "mixed_supported_and_out_of_scope_regions"
            elif explicit_subject_region and not event_region:
                primary = explicit_subject_region
                reason = "explicit_title_subject_region"
            elif event_region and _subject_should_outrank_event(
                title_text,
                leading_entity_region=leading_entity_region,
                event_region=event_region,
            ):
                primary = leading_entity_region
                related = [event_region]
                reason = "leading_subject_over_event"
            elif event_region:
                primary = event_region
                reason = "event_region"
            elif title_context_region:
                primary = title_context_region
                reason = "title_context_region"
            elif france_theme_matches:
                primary = RacingRegion.FRANCE
                reason = "france_theme"
            elif len(context_regions) == 1:
                primary = context_regions[0]
                reason = "lead_context_region"
            elif leading_entity_region:
                primary = leading_entity_region
                reason = "leading_entity_region"
            elif source_region:
                primary = source_region
                reason = "source_region_with_ambiguous_context" if len(context_regions) > 1 else "source_region"
            else:
                primary = RacingRegion.JAPAN
                reason = "fallback_japan"
        elif source_region == RacingRegion.JAPAN:
            foreign_region = event_region or (
                title_context_region if title_context_region != RacingRegion.JAPAN else ""
            )
            if foreign_region and not _japanese_source_keeps_home_focus(title_text, foreign_region):
                primary = foreign_region
                reason = "foreign_event_bulletin"
                if RacingRegion.JAPAN in entity_regions or "日本" in title_text:
                    related = [RacingRegion.JAPAN]
            else:
                primary = RacingRegion.JAPAN
                reason = "local_source_subject"
                if foreign_region:
                    related = [foreign_region]
        elif explicit_subject_region and explicit_subject_region != source_region:
            primary = explicit_subject_region
            reason = "explicit_title_subject_region"
            if event_region and event_region != primary:
                related = [event_region]
        elif event_region and event_region != source_region:
            primary = event_region
            reason = "event_region"
        elif source_region:
            primary = source_region
            reason = "local_source_region"
        elif event_region:
            primary = event_region
            reason = "event_region"
        elif france_theme_matches:
            primary = RacingRegion.FRANCE
            reason = "france_theme"
        elif entity_regions:
            primary = entity_regions[0]
            reason = "entity_region"
        elif len(context_regions) == 1:
            primary = context_regions[0]
            reason = "context_region"
        elif source_region:
            primary = source_region
            reason = "source_region_with_ambiguous_context" if context_regions else "source_region"
        elif context_regions:
            primary = context_regions[0]
            reason = "context_region_without_source"
        else:
            primary = RacingRegion.JAPAN
            reason = "fallback_japan"

        if source_is_global and reason in {"event_region", "leading_subject_over_event"}:
            related.extend(credible_entity_regions)
        if ireland_matched:
            related.append(RacingRegion.UNITED_KINGDOM)
        if out_of_scope_title_matches and primary != RacingRegion.OTHER:
            related.append(RacingRegion.OTHER)
        related = _dedupe_regions(related, exclude=primary)
        if len(related) > 3:
            conflict_reasons.append("related_region_spread")
            related = []
            status = AttributionStatus.NEEDS_REVIEW
            primary = source_region or primary
            reason = "related_region_spread"
        else:
            status = AttributionStatus.FALLBACK if reason in {"source_region", "source_region_with_ambiguous_context", "fallback_japan"} else AttributionStatus.APPLIED
    confidence = 90 if status == AttributionStatus.APPLIED and event_regions else 80 if status == AttributionStatus.APPLIED else 55 if status == AttributionStatus.FALLBACK else 30
    confidence_band = "high" if confidence >= 85 else "medium" if confidence >= 60 else "low"
    evidence = {
        "source_region": source_region,
        "event_regions": event_regions,
        "lead_event_regions": lead_event_regions,
        "entity_regions": entity_regions,
        "credible_entity_regions": credible_entity_regions,
        "context_regions": context_regions,
        "keyword_matches": keyword_matches,
        "title_keyword_matches": title_keyword_matches,
        "event_keyword_matches": event_keyword_matches,
        "term_matches": term_matches,
        "title_term_matches": title_term_matches,
        "ireland_keywords": ireland_matched,
        "out_of_scope_title_matches": out_of_scope_title_matches,
        "france_theme_matches": france_theme_matches,
        "positive": {
            "event_location": event_regions,
            "subject_origin": entity_regions,
            "leading_subject_origin": leading_entity_regions,
            "explicit_title_subject_origin": explicit_subject_region,
            "context_region": context_regions,
            "france_theme": france_theme_matches,
        },
        "negative": {"conflicts": conflict_reasons},
    }
    return AttributionResult(
        primary_region=primary,
        related_regions=related,
        content_category=classify_news_content(article),
        source="source_fallback" if status == AttributionStatus.FALLBACK else "auto",
        reason=reason,
        evidence=evidence,
        status=status,
        confidence=confidence,
        confidence_band=confidence_band,
        conflict_reasons=conflict_reasons,
    )


def set_article_regions(
    article: NewsArticle,
    *,
    primary_region: str | None = None,
    related_regions: Iterable[str] | None = None,
    attribution_source: str = "auto",
    reason: str = "",
    evidence: dict | None = None,
    content_category: str | None = None,
    status: str = AttributionStatus.APPLIED,
    confidence: int | None = None,
    rule_version: str = ATTRIBUTION_RULE_VERSION,
    save: bool = True,
) -> NewsArticle:
    primary = normalize_region(primary_region) or article.racing_region or RacingRegion.JAPAN
    related = _dedupe_regions(related_regions or [], exclude=primary)
    article.racing_region = primary
    article.attribution_source = attribution_source
    applied = {
        "primary_region": primary,
        "reason": reason,
        "related_regions": related,
        "evidence": evidence or {},
        "status": status,
        "confidence": confidence,
        "rule_version": rule_version,
    }
    summary = dict(article.attribution_summary or {})
    summary["applied"] = applied
    summary.update(applied)
    article.attribution_summary = summary
    article.attribution_status = status
    article.attribution_confidence = confidence
    article.attribution_rule_version = rule_version
    if content_category:
        article.content_category = content_category
    if save:
        article.save(
            update_fields=[
                "racing_region",
                "attribution_source",
                "attribution_summary",
                "attribution_status",
                "attribution_confidence",
                "attribution_rule_version",
                "content_category",
                "updated_at",
            ]
        )
        existing = {link.region: link for link in article.related_region_links.all()}
        for region in related:
            NewsArticleRelatedRegion.objects.update_or_create(
                article=article,
                region=region,
                defaults={
                    "source": attribution_source,
                    "reason": reason[:255],
                    "confidence": confidence or 0,
                    "is_manual": attribution_source == "manual",
                    "evidence": evidence or {},
                },
            )
        stale = [region for region in existing if region not in related]
        if stale:
            article.related_region_links.filter(region__in=stale).delete()
    return article


def apply_article_attribution(
    article: NewsArticle,
    *,
    source_config: NewsSource | None = None,
    force: bool = False,
    save: bool = True,
    is_new_article: bool | None = None,
) -> AttributionResult:
    mode = "enforce" if force else attribution_mode()
    rollout_stage = str(getattr(settings, "MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE", "off") or "off").strip().lower()
    if not force and mode == "enforce" and rollout_stage in ENFORCE_NEW_ARTICLES_STAGES and is_new_article is not True:
        mode = "shadow"
    if mode == "off" or (article.attribution_locked and not force):
        content_category = article.content_category or classify_news_content(article)
        if save and not article.content_category:
            article.content_category = content_category
            article.save(update_fields=["content_category", "updated_at"])
        return AttributionResult(
            primary_region=normalize_region(article.racing_region) or RacingRegion.JAPAN,
            related_regions=_dedupe_regions(
                article.related_region_links.values_list("region", flat=True),
                exclude=article.racing_region,
            ),
            content_category=content_category,
            source=article.attribution_source or "existing",
            reason="attribution_locked" if article.attribution_locked else "attribution_disabled",
            evidence={},
            status=AttributionStatus.LOCKED_SKIP if article.attribution_locked else AttributionStatus.FALLBACK,
        )

    result = infer_article_attribution(article, source_config=source_config)
    if mode == "shadow" or result.status == AttributionStatus.NEEDS_REVIEW:
        summary = dict(article.attribution_summary or {})
        namespace = "shadow" if mode == "shadow" else "review_candidate"
        summary[namespace] = {
            "primary_region": result.primary_region,
            "related_regions": result.related_regions,
            "reason": result.reason,
            "evidence": result.evidence,
            "status": result.status,
            "confidence": result.confidence,
            "rule_version": result.rule_version,
        }
        if save:
            article.attribution_summary = summary
            article.attribution_status = result.status
            article.attribution_confidence = result.confidence
            article.attribution_rule_version = result.rule_version
            article.save(
                update_fields=[
                    "attribution_summary",
                    "attribution_status",
                    "attribution_confidence",
                    "attribution_rule_version",
                    "updated_at",
                ]
            )
        return result
    set_article_regions(
        article,
        primary_region=result.primary_region,
        related_regions=result.related_regions,
        attribution_source=result.source,
        reason=result.reason,
        evidence=result.evidence,
        content_category=result.content_category,
        status=result.status,
        confidence=result.confidence,
        rule_version=result.rule_version,
        save=save,
    )
    if save and result.evidence.get("ireland_keywords") and "ireland" not in (article.tags_json or []):
        article.tags_json = [*(article.tags_json or []), "ireland"]
        article.save(update_fields=["tags_json", "updated_at"])
    return result
