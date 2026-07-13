from __future__ import annotations

import re
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
ATTRIBUTION_RULE_VERSION = "multiregion-v2"
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
class AttributionBatchContext:
    entries: list[TermEntry]
    terms_by_language: dict[str, dict[int, list[str]]]
    preload_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls) -> "AttributionBatchContext":
        entries = list(
            TermEntry.objects.filter(
                is_active=True,
                term_type__in=[*ENTITY_TERM_TYPES, *EVENT_TERM_TYPES, *FRANCE_CONTEXT_TERM_TYPES],
                racing_region__in=SUPPORTED_REGIONS,
            ).exclude(racing_region="")
        )
        languages = [SourceLanguage.JAPANESE, SourceLanguage.ENGLISH, SourceLanguage.CHINESE_TRADITIONAL]
        return cls(
            entries=entries,
            terms_by_language={language: source_terms_by_entry(entries, language) for language in languages},
            preload_counts={"term_index_builds": 1, "terms": len(entries)},
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
    for entry in entries:
        source_terms = terms_by_entry.get(entry.pk, [])
        matched = next((term for term in source_terms if source_term_matches_text(text, term, source_language)), "")
        if not matched:
            continue
        if source_language == SourceLanguage.ENGLISH and matched.casefold() in ordinary_terms:
            continue
        payload = {
            "term_id": entry.pk,
            "term_type": entry.term_type,
            "source_term": matched,
            "region": entry.racing_region,
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


def infer_article_attribution(
    article: NewsArticle,
    source_config: NewsSource | None = None,
    *,
    batch_context: AttributionBatchContext | None = None,
) -> AttributionResult:
    source_region = normalize_region(
        getattr(source_config, "racing_region", "") or getattr(article.source_config, "racing_region", "") or article.racing_region
    )
    text = _source_text(article)
    title_text = article.title_ja or ""
    lead_text = "\n".join([title_text, (article.body_ja_normalized or article.body_ja_raw or "")[:400]])
    keyword_matches = _keyword_regions(lead_text)
    event_keyword_matches = _keyword_regions(title_text, EVENT_REGION_KEYWORDS)
    term_matches = _term_regions(article, lead_text, batch_context=batch_context)
    title_term_matches = _term_regions(article, title_text, batch_context=batch_context)
    event_regions = _dedupe_regions(
        [*event_keyword_matches.keys(), *_regions_from_term_payloads(title_term_matches["event"])]
    )
    entity_regions = _regions_from_term_payloads(title_term_matches["entity"])
    context_regions = _dedupe_regions(
        [
            *keyword_matches.keys(),
            *_regions_from_term_payloads(term_matches["france_context"]),
        ],
        exclude="",
    )
    ireland_matched = [keyword for keyword in IRELAND_KEYWORDS if keyword in text.casefold()]

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

    if len(event_regions) > 1:
        conflict_reasons.append("conflicting_event_centres")
        primary = source_region or RacingRegion.JAPAN
        related: list[str] = []
        status = AttributionStatus.NEEDS_REVIEW
        reason = "conflicting_event_centres"
    else:
        if event_regions:
            primary = event_regions[0]
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

        related = _dedupe_regions(
            [
                *entity_regions,
                *(context_regions if not event_regions and len(context_regions) > 1 else []),
                RacingRegion.UNITED_KINGDOM if ireland_matched else "",
            ],
            exclude=primary,
        )
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
        "entity_regions": entity_regions,
        "context_regions": context_regions,
        "keyword_matches": keyword_matches,
        "event_keyword_matches": event_keyword_matches,
        "term_matches": term_matches,
        "ireland_keywords": ireland_matched,
        "france_theme_matches": france_theme_matches,
        "positive": {
            "event_location": event_regions,
            "subject_origin": entity_regions,
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
    if mode == "shadow":
        summary = dict(article.attribution_summary or {})
        summary["shadow"] = {
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
