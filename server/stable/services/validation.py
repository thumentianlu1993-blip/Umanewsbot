from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    AutomationLog,
    AutomationPhase,
    AutomationResult,
    AutomationStatus,
    NewsArticle,
    ReviewMode,
    RiskLevel,
    SourceLanguage,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.terms import (
    ArticleEntityResolution,
    ENGLISH_COMMON_WORD_TERM_SEEDS,
    _recognize_non_japanese_external_aliases,
    english_horse_name_has_confirmed_occurrence,
    _find_source_term_match,
    recognize_horse_names,
    recognized_horses_from_resolution,
    resolve_article_entities,
    resolve_article_entities_for_article,
    serialize_recognized_horse_names,
    source_term_matches_text,
    source_terms_by_entry,
    visible_source_parts as _visible_source_parts,
)
from stable.services.news_attribution import article_region_set
from stable.services.publish_readiness import transition_to_publish_ready
from stable.services.term_consistency import apply_consistency_gate


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUOTE_RE = re.compile(r"[「『](.*?)[」』]")
_TOKEN_RE = re.compile(r"[\w一-龥ぁ-んァ-ヴー]+")

SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
ROUTE_AUTO = "auto"
ROUTE_MANUAL = "manual_review"
ROUTE_DUPLICATE = "duplicate"
GLOBAL_RACING_REGION = ""

# Seeded from runtime/multiregion_candidate_audit and the 2026-07-13
# production article review. The shared set lives in terms.py so article-level
# resolution and the publish gate use the same ordinary-word vocabulary.
ENGLISH_DUAL_USE_COMMON_WORD_TERMS = {
    "ace",
    "classic",
    "fast track",
    "good job",
    "hopeful",
    "step forward",
    "tuesday",
}
ENGLISH_RACE_NAME_MARKERS = {
    "classic",
    "cup",
    "derby",
    "futurity",
    "guineas",
    "handicap",
    "invitational",
    "oaks",
    "prix",
    "stakes",
}


@dataclass
class GateIssue:
    code: str
    severity: str
    message: str
    route: str
    payload: dict

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "route": self.route,
            "payload": self.payload,
        }


@dataclass
class ValidationOutcome:
    passed: bool
    reason: str
    details: dict
    issues: list[dict]

    @property
    def blockers(self) -> list[dict]:
        return [issue for issue in self.issues if issue.get("severity") == SEVERITY_BLOCKER]

    @property
    def warnings(self) -> list[dict]:
        return [issue for issue in self.issues if issue.get("severity") == SEVERITY_WARNING]


@dataclass
class ValidationBatchContext:
    term_entries: list[TermEntry]
    terms_by_language: dict[str, dict[int, list[str]]]
    recognized_horses_by_article: dict[int, list]
    duplicate_candidates: list[NewsArticle]
    term_entry_ids_by_article: dict[int, set[int]]
    structured_entities_by_article: dict[int, dict[str, list[str]]]
    entity_resolutions_by_article: dict[int, ArticleEntityResolution] | None = None
    accepted_term_ids_by_article: dict[int, set[int]] | None = None
    auto_horse_term_ids_by_article: dict[int, set[int]] | None = None
    term_snapshot_sha256: str = ""
    term_index_build_count: int = 1
    entity_prefetch_count: int = 0
    race_entity_prefetch_count: int = 0
    horse_alias_prefetch_count: int = 0
    horse_term_prefetch_count: int = 0
    term_entry_prefetch_count: int = 0
    term_alias_prefetch_count: int = 0
    duplicate_corpus_prefetch_count: int = 1
    term_pattern_check_count: int = 0


@dataclass(frozen=True)
class EnglishTermMatchContext:
    matched_text: str
    matched_context: str
    position: str
    tokens_before: tuple[str, ...] = ()
    tokens_after: tuple[str, ...] = ()
    matched_span: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class EnglishTermSemanticDecision:
    classification: str
    confidence: float
    reason: str
    match: EnglishTermMatchContext
    evidence: tuple[str, ...] = ()


def _source_text(article: NewsArticle) -> str:
    title, body = _visible_source_parts(article)
    return "\n".join([title, body]).strip()


def _content_source() -> str:
    if not getattr(settings, "AUTO_REWRITE_ENABLED", False):
        return "base_translation"
    source = (getattr(settings, "AUTO_PUBLISH_CONTENT_SOURCE", "base_translation") or "base_translation").strip().lower()
    return source if source in {"base_translation", "rewrite"} else "base_translation"


def _publish_title(article: NewsArticle, content_source: str) -> str:
    if content_source == "rewrite":
        return article.rewrite_title_zh or ""
    return article.title_zh or article.translated_title_zh or ""


def _publish_summary(article: NewsArticle, content_source: str) -> str:
    if content_source == "rewrite":
        return article.rewrite_summary_zh or ""
    return article.summary_zh or article.translated_summary_zh or article.push_summary_zh or ""


def _publish_body(article: NewsArticle, content_source: str) -> str:
    if content_source == "rewrite":
        return article.rewrite_body_zh or ""
    return article.body_zh or article.translated_body_zh or ""


def _publish_text(article: NewsArticle, content_source: str) -> str:
    return "\n".join(
        [
            _publish_title(article, content_source),
            _publish_summary(article, content_source),
            _publish_body(article, content_source),
        ]
    ).strip()


def _issue(code: str, severity: str, message: str, *, route: str = ROUTE_AUTO, payload: dict | None = None) -> GateIssue:
    return GateIssue(code=code, severity=severity, message=message, route=route, payload=payload or {})


def _summarize_issues(issues: list[GateIssue]) -> str:
    if not issues:
        return "门禁校验通过"
    blockers = [issue.message for issue in issues if issue.severity == SEVERITY_BLOCKER]
    warnings = [issue.message for issue in issues if issue.severity == SEVERITY_WARNING]
    infos = [issue.message for issue in issues if issue.severity == SEVERITY_INFO]
    if blockers:
        return "；".join(blockers[:4])
    if warnings:
        return "warning：" + "；".join(warnings[:4])
    return "info：" + "；".join(infos[:4])


def _important_numbers(text: str) -> list[str]:
    numbers = []
    seen: set[str] = set()
    for item in _NUMBER_RE.findall(text or ""):
        if len(item) < 2:
            continue
        if item in seen:
            continue
        seen.add(item)
        numbers.append(item)
    return numbers[:24]


def _quote_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    for quote in _QUOTE_RE.findall(text or ""):
        normalized = quote.strip()
        if len(normalized) >= 8:
            fragments.append(normalized[:18])
    return fragments[:10]


def _normalize_term_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    replacements = {
        "（": "(",
        "）": ")",
        "・": "",
        "·": "",
        " ": "",
        "\u3000": "",
        "-": "",
        "－": "",
        "Ⅰ": "i",
        "Ⅱ": "ii",
        "Ⅲ": "iii",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _term_preserved(
    entry: TermEntry,
    publish_text: str,
    source_language: str | None = None,
    source_terms: list[str] | None = None,
) -> bool:
    normalized_publish = _normalize_term_text(publish_text)
    if source_terms is None:
        source_terms = entry.source_terms_for_language(source_language) if source_language else entry.all_source_terms()
    candidates = [*source_terms, entry.target_zh, *(entry.aliases_zh or [])]
    return any(candidate and _normalize_term_text(candidate) in normalized_publish for candidate in candidates)


def _pending_horse_original_preserved(publish_text: str, source_terms: list[str]) -> bool:
    normalized_publish = _normalize_term_text(publish_text)
    return any(term and _normalize_term_text(term) in normalized_publish for term in source_terms)


def _formal_chinese_horse_target_exactly_mentioned(
    publish_text: str,
    candidates: list[str],
) -> bool:
    """Accept an unambiguous formal Chinese name mention after source confirmation.

    Short Chinese translations such as ``辉煌`` remain context-classified because
    they are commonly used as ordinary predicates.  Longer formal names can be
    preserved by an exact terminal match without requiring a result-card phrase.
    """
    normalized_publish = unicodedata.normalize("NFKC", publish_text or "")
    for candidate in candidates:
        normalized_candidate = unicodedata.normalize(
            "NFKC", candidate or ""
        ).strip()
        if not normalized_candidate:
            continue
        han_characters = re.findall(r"[\u3400-\u9fff]", normalized_candidate)
        if len(han_characters) < 3:
            continue
        if re.search(
            rf"{re.escape(normalized_candidate)}(?![0-9A-Za-z_\u3400-\u9fff])",
            normalized_publish,
        ):
            return True
    return False


def _source_term_hit(text: str, source_terms: list[str], source_language: str | None) -> bool:
    return any(source_term_matches_text(text, term, source_language) for term in source_terms)


def _setting_list(name: str) -> set[str]:
    value = getattr(settings, name, [])
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = value or []
    return {str(item).strip().casefold() for item in items if str(item).strip()}


def _term_gate_region_allowed(entry: TermEntry, article: NewsArticle, source_language: str | None) -> bool:
    if entry.is_pending_horse_translation:
        return True
    if source_language != SourceLanguage.ENGLISH:
        return True
    term_region = entry.racing_region or GLOBAL_RACING_REGION
    if term_region == GLOBAL_RACING_REGION:
        return True
    return term_region in article_region_set(article)


def _article_regions_payload(article: NewsArticle) -> list[str]:
    return sorted(article_region_set(article)) or [article.racing_region or GLOBAL_RACING_REGION]


def _ambiguous_english_term_reason(entry: TermEntry, source_terms: list[str], *, is_core: bool) -> str:
    configured = _setting_list("MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS")
    candidates = [entry.source_ja, *source_terms]
    if any((candidate or "").strip().casefold() in configured for candidate in candidates):
        return "high_ambiguity_config"
    if is_core:
        return ""
    visible_candidates = [(candidate or "").strip() for candidate in candidates if (candidate or "").strip()]
    if any(candidate.isascii() and candidate.isalpha() and len(candidate) <= 4 for candidate in visible_candidates):
        return "short_english_token"
    if any(candidate.isascii() and candidate.isupper() and len(candidate) <= 8 for candidate in visible_candidates):
        return "uppercase_english_token"
    return ""


def _ignored_source_term_reason(matched_source_term: str) -> str:
    configured = _setting_list("MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS")
    if (matched_source_term or "").strip().casefold() in configured:
        return "confirmed_non_term_config"
    return ""


def _matched_source_term(text: str, source_terms: list[str], source_language: str | None) -> str:
    for term in source_terms:
        matched = _find_source_term_match(text, term, source_language)
        if matched:
            return matched
    return ""


def _nfkc_text_with_source_offsets(text: str) -> tuple[str, list[int]]:
    normalized_parts: list[str] = []
    source_offsets: list[int] = []
    for index, character in enumerate(text or ""):
        normalized = unicodedata.normalize("NFKC", character)
        normalized_parts.append(normalized)
        source_offsets.extend([index] * len(normalized))
    return "".join(normalized_parts), source_offsets


def _source_span_from_normalized(
    source_offsets: list[int],
    start: int,
    end: int,
) -> tuple[int, int]:
    if start >= end or not source_offsets:
        return start, end
    return source_offsets[start], source_offsets[end - 1] + 1


def _source_term_match_span(text: str, candidate: str, source_language: str | None) -> tuple[int, int, str] | None:
    if not candidate:
        return None
    if source_language == SourceLanguage.ENGLISH:
        normalized_text, source_offsets = _nfkc_text_with_source_offsets(text or "")
        normalized_candidate = unicodedata.normalize("NFKC", candidate)
        pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(normalized_candidate) + r"(?![0-9A-Za-z])", re.IGNORECASE)
        match = pattern.search(normalized_text)
        if not match:
            return None
        source_start, source_end = _source_span_from_normalized(source_offsets, match.start(), match.end())
        original = (text or "")[source_start:source_end]
        return (source_start, source_end, original or match.group(0))
    index = (text or "").find(candidate)
    return (index, index + len(candidate), candidate) if index >= 0 else None


def _source_term_match_context(
    source: str,
    title: str,
    first_block: str,
    source_terms: list[str],
    source_language: str | None,
) -> EnglishTermMatchContext:
    for position, text in (("title", title), ("lead", first_block), ("body", source)):
        for term in source_terms:
            span = _source_term_match_span(text, term, source_language)
            if not span:
                continue
            start, end, matched = span
            context_start = max(0, start - 80)
            context_end = min(len(text or ""), end + 80)
            snippet = (text or "")[context_start:context_end].strip()
            tokens_before = tuple(re.findall(r"[A-Za-z0-9']+", (text or "")[context_start:start])[-8:])
            tokens_after = tuple(re.findall(r"[A-Za-z0-9']+", (text or "")[end:context_end])[:8])
            return EnglishTermMatchContext(
                matched_text=matched,
                matched_context=snippet,
                position=position,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                matched_span=(start, end),
            )
    return EnglishTermMatchContext(matched_text="", matched_context="", position="unknown")


def _all_source_term_match_contexts(
    title: str,
    body: str,
    source_terms: list[str],
) -> list[EnglishTermMatchContext]:
    matches: list[EnglishTermMatchContext] = []
    seen: set[tuple[str, int, int]] = set()
    for field, text in (("title", title), ("body", body)):
        normalized_text, source_offsets = _nfkc_text_with_source_offsets(text or "")
        for term in sorted(source_terms, key=lambda value: (-len(value), value.casefold())):
            normalized_term = unicodedata.normalize("NFKC", term or "")
            if not normalized_term:
                continue
            pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(normalized_term) + r"(?![0-9A-Za-z])", re.IGNORECASE)
            for match in pattern.finditer(normalized_text):
                source_start, source_end = _source_span_from_normalized(source_offsets, match.start(), match.end())
                key = (field, source_start, source_end)
                if key in seen:
                    continue
                seen.add(key)
                context_start = max(0, source_start - 80)
                context_end = min(len(text or ""), source_end + 80)
                snippet = (text or "")[context_start:context_end].strip()
                position = "title" if field == "title" else ("lead" if source_start < 500 else "body")
                matches.append(
                    EnglishTermMatchContext(
                        matched_text=(text or "")[source_start:source_end] or match.group(0),
                        matched_context=snippet,
                        position=position,
                        tokens_before=tuple(re.findall(r"[A-Za-z0-9']+", (text or "")[context_start:source_start])[-8:]),
                        tokens_after=tuple(re.findall(r"[A-Za-z0-9']+", (text or "")[source_end:context_end])[:8]),
                        matched_span=(source_start, source_end),
                    )
                )
    order = {"title": 0, "lead": 1, "body": 2}
    return sorted(matches, key=lambda item: (order[item.position], item.matched_span[0], item.matched_span[1]))


def _english_term_candidate_keys(entry: TermEntry, source_terms: list[str]) -> set[str]:
    return {
        (candidate or "").strip().casefold()
        for candidate in [entry.source_ja, *source_terms]
        if (candidate or "").strip()
    }


def _settings_common_english_terms() -> set[str]:
    configured = _setting_list("MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS")
    return ENGLISH_COMMON_WORD_TERM_SEEDS | configured


def _looks_like_race_name(text: str) -> bool:
    normalized = (text or "").strip().casefold()
    if not normalized:
        return False
    tokens = re.findall(r"[a-z0-9']+", normalized)
    return any(token in ENGLISH_RACE_NAME_MARKERS for token in tokens)


def _english_match_looks_like_entity_context(entry: TermEntry, context: EnglishTermMatchContext) -> bool:
    if entry.term_type != TermType.HORSE:
        return False
    snippet = context.matched_context or ""
    matched = re.escape(context.matched_text or entry.source_ja)
    if re.search(
        matched + r"\s+(?:wins?|won|returns?|returned|runs?|ran|heads?|headed|targets?|targeted|entered|prepares?)\b",
        snippet,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        matched
        + r"\s+(?:will|would|could|may|might|can|is|was|being|has been)\s+"
        + r"(?:target|return|run|head|enter|prepare|trial)\b",
        snippet,
        re.IGNORECASE,
    ):
        return True
    return False


def _english_match_looks_like_common_word_context(entry: TermEntry, context: EnglishTermMatchContext) -> bool:
    matched = (context.matched_text or entry.source_ja or "").strip().casefold()
    snippet = f" {context.matched_context.casefold()} "
    if not matched:
        return False
    common_patterns = {
        "agenda": [r"\bagenda\s+(?:for|also|includes?)\b", r"\bthe\s+agenda\b"],
        "contact": [r"\bcontact\s+(?:the|details?|office|us)\b"],
        "live": [r"\blive\s+(?:stream|coverage|updates?|broadcast)\b", r"\bwatch\s+live\b"],
        "number": [r"\bnumber\s+of\b", r"\b(?:office|stream|racecard|contact)\s+number\b"],
        "were": [r"\bwere\s+\w+ed\b", r"\b(?:races?|they|there)\s+were\b"],
    }
    for pattern in common_patterns.get(matched, []):
        if re.search(pattern, snippet):
            return True
    return False


def _english_term_semantic_payload(decision: EnglishTermSemanticDecision) -> dict:
    return {
        "term_semantic_classification": decision.classification,
        "confidence": decision.confidence,
        "classification_reason": decision.reason,
        "matched_text": decision.match.matched_text,
        "matched_context": decision.match.matched_context,
        "match_position": decision.match.position,
        "tokens_before": list(decision.match.tokens_before),
        "tokens_after": list(decision.match.tokens_after),
        "matched_span": list(decision.match.matched_span),
        "entity_evidence": list(decision.evidence),
    }


def _classify_english_term_match_v2(
    entry: TermEntry,
    match: EnglishTermMatchContext,
    *,
    structured_entities: dict[str, list[str]] | None = None,
) -> EnglishTermSemanticDecision:
    if entry.term_type in {TermType.RACE, TermType.JOCKEY, TermType.TRAINER}:
        return EnglishTermSemanticDecision("proper_noun", 0.95, f"{entry.term_type}_term_type", match)
    before = [token.casefold() for token in match.tokens_before]
    after = [token.casefold() for token in match.tokens_after]
    matched_key = unicodedata.normalize("NFKC", match.matched_text or entry.source_ja).casefold()
    if matched_key in (structured_entities or {}):
        return EnglishTermSemanticDecision(
            "proper_noun", 0.99, "structured_race_entity", match,
            tuple((structured_entities or {}).get(matched_key, [])),
        )
    if len(after) >= 2 and after[0] == "was" and after[1] == matched_key:
        return EnglishTermSemanticDecision("proper_noun", 0.95, "horse_subject_copular_relation", match)
    if before and before[-1] in {"was", "is", "as"}:
        return EnglishTermSemanticDecision("common_word", 0.95, "predicate_adjective_context", match)
    if match.tokens_after and re.fullmatch(r"[A-Z]{2,3}", match.tokens_after[0]):
        return EnglishTermSemanticDecision("proper_noun", 0.95, "horse_country_suffix", match)
    local_context = " ".join([*before[-4:], "__match__", *after[:8]])
    entity_patterns = [
        r"__match__\s+(?:wins?|won|finished|runs?|ran|returns?|heads?|targets?|is\s+trained\s+by)\b",
        r"__match__\s+(?:ridden|trained)\s+by\b",
    ]
    if any(re.search(pattern, local_context, re.IGNORECASE) for pattern in entity_patterns):
        return EnglishTermSemanticDecision("proper_noun", 0.95, "horse_entity_relation", match)
    common_patterns = {
        "brilliant": [r"\b(?:a|an)\s+__match__\b"],
        "something": [r"__match__\s+(?:went|is|was|around)\b"],
        "versatile": [r"__match__\s+(?:filly|colt|horse|runner)\b"],
        "incredible": [r"\b(?:as|was|is)\s+__match__\b"],
        "reputation": [r"\b(?:huge|strong|big)\s+__match__\b"],
        "threat": [r"\bposed?\s+a\s+__match__\b"],
        "title": [r"\b(?:another|the)\s+__match__\b"],
        "soon": [r"\btoo\s+__match__\b"],
        "yet": [r"\b(?:has|have|had)\s+__match__\s+to\b"],
        "contact": [r"__match__\s+(?:details?|the|office|us)\b"],
        "class": [r"__match__\s+\d+\b"],
    }
    if any(re.search(pattern, local_context, re.IGNORECASE) for pattern in common_patterns.get(matched_key, [])):
        return EnglishTermSemanticDecision("common_word", 0.95, "ordinary_english_context", match)
    return EnglishTermSemanticDecision("uncertain", 0.45, "insufficient_context_evidence", match)


def _v2_term_gate_result(
    entry: TermEntry,
    matches: list[EnglishTermMatchContext],
    article: NewsArticle,
    *,
    structured_entities: dict[str, list[str]] | None = None,
) -> tuple[list[dict], GateIssue]:
    payloads: list[dict] = []
    decisions = [
        _classify_english_term_match_v2(entry, match, structured_entities=structured_entities)
        for match in matches
    ]
    for decision in decisions:
        is_core = decision.match.position in {"title", "lead"} or (
            entry.priority >= 80 and decision.classification == "proper_noun"
        )
        payloads.append(
            {
                "term_id": entry.id,
                "source_ja": entry.source_ja,
                "source_language": entry.source_language,
                "target_zh": entry.target_zh,
                "term_type": entry.term_type,
                "priority": entry.priority,
                "position": "core" if is_core else "background",
                "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                "article_region": article.racing_region or GLOBAL_RACING_REGION,
                **_english_term_semantic_payload(decision),
            }
        )
    blocking = [
        payload for payload in payloads
        if payload["term_semantic_classification"] in {"proper_noun", "uncertain"} and payload["position"] == "core"
    ]
    background = [
        payload for payload in payloads
        if payload["term_semantic_classification"] in {"proper_noun", "uncertain"} and payload["position"] == "background"
    ]
    if blocking:
        return payloads, _issue(
            "core_term_missing",
            SEVERITY_BLOCKER,
            "核心术语未稳定保留：" + entry.source_ja,
            route=ROUTE_MANUAL,
            payload=blocking[0],
        )
    if background:
        return payloads, _issue(
            "background_term_missing",
            SEVERITY_WARNING,
            "背景术语未稳定保留：" + entry.source_ja,
            payload=background[0],
        )
    return payloads, _issue(
        "english_term_common_word_downgraded",
        SEVERITY_WARNING,
        "普通英文词命中已降级：" + entry.source_ja,
        payload=payloads[0],
    )


def _classify_english_term_context(
    entry: TermEntry,
    source: str,
    title: str,
    first_block: str,
    source_terms: list[str],
    *,
    is_core: bool,
) -> EnglishTermSemanticDecision | None:
    if not is_core:
        return None
    match = _source_term_match_context(source, title, first_block, source_terms, SourceLanguage.ENGLISH)
    keys = _english_term_candidate_keys(entry, source_terms)
    common_terms = _settings_common_english_terms()
    has_common_seed = bool(keys & common_terms)

    if entry.term_type in {TermType.RACE, TermType.JOCKEY, TermType.TRAINER}:
        return EnglishTermSemanticDecision("proper_noun", 0.95, f"{entry.term_type}_term_type", match)
    if has_common_seed:
        if _english_match_looks_like_entity_context(entry, match):
            return EnglishTermSemanticDecision(
                "proper_noun",
                0.95,
                "common_seed_entity_context",
                match,
            )
        if _english_match_looks_like_common_word_context(entry, match):
            return EnglishTermSemanticDecision("common_word", 0.9, "ordinary_english_context", match)
        return EnglishTermSemanticDecision("common_word", 0.85, "ordinary_english_seed_default", match)
    if _looks_like_race_name(entry.source_ja) or any(_looks_like_race_name(term) for term in source_terms):
        return EnglishTermSemanticDecision("proper_noun", 0.9, "race_name_marker", match)
    if entry.term_type == TermType.HORSE:
        return EnglishTermSemanticDecision("proper_noun", 0.8, "horse_term_without_common_seed", match)
    return EnglishTermSemanticDecision("uncertain", 0.4, "unclassified_english_term", match)


def _is_core_term(
    entry: TermEntry,
    source: str,
    title: str,
    first_block: str,
    source_language: str | None = None,
    source_terms: list[str] | None = None,
) -> bool:
    if source_terms is None:
        source_terms = entry.source_terms_for_language(source_language) if source_language else entry.all_source_terms()
    if entry.priority >= 80:
        return True
    if entry.term_type in {TermType.HORSE, TermType.RACE} and _source_term_hit(title, source_terms, source_language):
        return True
    return _source_term_hit(first_block, source_terms, source_language)


def _fingerprint_text(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall((text or "").lower()):
        if len(token) <= 1:
            continue
        tokens.add(token)
    return tokens


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _fingerprint_text(left)
    right_tokens = _fingerprint_text(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _article_similarity_text(article: NewsArticle, content_source: str | None = None) -> str:
    source = content_source or _content_source()
    return "\n".join(
        [
            article.title_ja or "",
            _publish_title(article, source),
            _publish_summary(article, source),
            _publish_body(article, source)[:1200],
        ]
    )


def detect_duplicate_issue(
    article: NewsArticle,
    content_source: str,
    *,
    candidates: list[NewsArticle] | None = None,
    progress_callback: Callable[[], None] | None = None,
) -> GateIssue | None:
    lookback_days = int(getattr(settings, "AUTO_DUPLICATE_LOOKBACK_DAYS", 7))
    high_threshold = float(getattr(settings, "AUTO_DUPLICATE_HIGH_THRESHOLD", 0.86))
    review_threshold = float(getattr(settings, "AUTO_DUPLICATE_REVIEW_THRESHOLD", 0.72))
    if high_threshold <= 0 and review_threshold <= 0:
        return None

    window_start = (article.published_at or timezone.now()) - timedelta(days=lookback_days)
    candidate_text = _article_similarity_text(article, content_source)
    if not candidate_text.strip():
        return None
    queryset = candidates
    if queryset is None:
        queryset = list(
            NewsArticle.objects.filter(
                Q(workflow_status=WorkflowStatus.PUBLISHED)
                | Q(review_mode=ReviewMode.AUTO, automation_status=AutomationStatus.PUBLISH_READY),
                published_at__gte=window_start,
            )
            .exclude(pk=article.pk)
            .order_by("-published_at", "-id")[:80]
        )
    else:
        queryset = [
            candidate for candidate in queryset
            if candidate.pk != article.pk and candidate.published_at and candidate.published_at >= window_start
        ][:80]
    best_article: NewsArticle | None = None
    best_score = 0.0
    for index, other in enumerate(queryset, start=1):
        if progress_callback and index % 20 == 1:
            progress_callback()
        score = _jaccard_similarity(candidate_text, _article_similarity_text(other, "base_translation"))
        if score > best_score:
            best_score = score
            best_article = other
    if not best_article or best_score < review_threshold:
        return None

    payload = {
        "duplicate_of_id": best_article.id,
        "duplicate_score": round(best_score, 4),
        "duplicate_title": best_article.effective_title,
        "duplicate_url": best_article.source_url,
    }
    if best_score >= high_threshold:
        return _issue(
            "duplicate_content",
            SEVERITY_BLOCKER,
            f"与已发布或待发布文章高度重复：#{best_article.id}，相似度 {best_score:.2f}",
            route=ROUTE_DUPLICATE,
            payload=payload,
        )
    return _issue(
        "possible_duplicate_content",
        SEVERITY_BLOCKER,
        f"与已发布或待发布文章中等相似：#{best_article.id}，相似度 {best_score:.2f}",
        route=ROUTE_MANUAL,
        payload=payload,
    )


def validate_rewrite(
    article: NewsArticle,
    *,
    term_entries: list[TermEntry] | None = None,
    terms_by_language: dict[str, dict[int, list[str]]] | None = None,
    batch_context: ValidationBatchContext | None = None,
    progress_callback: Callable[[], None] | None = None,
) -> ValidationOutcome:
    if progress_callback:
        progress_callback()
    context_mode = str(getattr(settings, "ENGLISH_TERM_CONTEXT_MODE", "off") or "off").strip().lower()
    if context_mode not in {"off", "shadow", "enforce"}:
        context_mode = "off"
    visible_title, visible_body = _visible_source_parts(article)
    legacy_title = article.title_ja or ""
    legacy_body = article.body_ja_normalized or article.body_ja_raw or ""
    title = visible_title if context_mode == "enforce" else legacy_title
    gate_body = visible_body if context_mode == "enforce" else legacy_body
    source = "\n".join([title, gate_body]).strip()
    content_source = _content_source()
    publish_text = _publish_text(article, content_source)
    publish_body = _publish_body(article, content_source)
    issues: list[GateIssue] = []
    details: dict = {
        "content_source": content_source,
        "unknown_horse_names": [],
        "recognized_horse_names": [],
        "external_horse_names": [],
        "missing_known_terms": [],
        "term_gate_region_excluded_terms": [],
        "ignored_non_term_gate_terms": [],
        "ambiguous_term_downgrades": [],
        "english_term_classifications": [],
        "missing_numbers": [],
        "quote_fragments_checked": [],
        "issues": [],
        "article_entities": [],
    }

    if not _publish_title(article, content_source):
        issues.append(_issue("missing_title", SEVERITY_BLOCKER, "发布稿缺少标题", route=ROUTE_MANUAL))
    if not publish_body:
        issues.append(_issue("missing_body", SEVERITY_BLOCKER, "发布稿缺少正文", route=ROUTE_MANUAL))
    elif len(publish_body) < 80:
        issues.append(_issue("body_too_short", SEVERITY_BLOCKER, "发布正文过短", route=ROUTE_MANUAL))
    if not article.source_url:
        issues.append(_issue("missing_source_url", SEVERITY_BLOCKER, "缺少原文链接", route=ROUTE_MANUAL))
    if article.published_at_verified is False:
        issues.append(
            _issue(
                "published_at_unverified",
                SEVERITY_BLOCKER,
                "发布时间缺少可信来源证据",
                route=ROUTE_MANUAL,
                payload={"published_at_evidence": article.published_at_evidence or {}},
            )
        )
    if content_source == "rewrite" and article.rewrite_confidence < int(getattr(settings, "REWRITE_CONFIDENCE_MIN", 60)):
        issues.append(
            _issue(
                "rewrite_confidence_low",
                SEVERITY_WARNING,
                "改写置信度低于阈值",
                payload={"confidence": article.rewrite_confidence},
            )
        )

    preserve_limit = 12
    article_source_language = article.source_language or SourceLanguage.JAPANESE
    occurrence_resolution = (
        (batch_context.entity_resolutions_by_article or {}).get(article.id)
        if batch_context is not None
        else None
    )
    if occurrence_resolution is None:
        occurrence_resolution = resolve_article_entities_for_article(
            article, title_text=visible_title, body_text=visible_body
        )
    # Off/shadow must remain behaviorally identical to the legacy gate.  Keep
    # the occurrence resolver solely as audit/shadow detail in those modes and
    # independently resolve the raw legacy source for all behavioral inputs.
    behavior_resolution = occurrence_resolution
    if (
        article_source_language == SourceLanguage.ENGLISH
        and context_mode in {"off", "shadow"}
    ):
        behavior_resolution = resolve_article_entities(
            legacy_title,
            legacy_body,
            source_language=article_source_language,
        )
    behavior_accepted_term_ids = set(behavior_resolution.accepted_term_ids)
    if (
        behavior_accepted_term_ids
        and article_source_language == SourceLanguage.ENGLISH
        and context_mode in {"off", "shadow"}
    ):
        legacy_accepted_entries = list(
            TermEntry.objects.filter(id__in=behavior_accepted_term_ids)
        )
        legacy_terms_by_entry = source_terms_by_entry(
            legacy_accepted_entries,
            article_source_language,
        )
        legacy_duplicate_winners: dict[
            tuple[str, str, str, str, str], TermEntry
        ] = {}
        for legacy_entry in legacy_accepted_entries:
            duplicate_key = (
                legacy_entry.term_type,
                legacy_entry.source_language,
                legacy_entry.racing_region or GLOBAL_RACING_REGION,
                (legacy_entry.source_ja or "").casefold(),
                (legacy_entry.target_zh or "").casefold(),
            )
            winner = legacy_duplicate_winners.get(duplicate_key)
            if winner is None or (
                legacy_entry.priority,
                legacy_entry.id,
            ) > (
                winner.priority,
                winner.id,
            ):
                legacy_duplicate_winners[duplicate_key] = legacy_entry
            if legacy_entry.term_type != TermType.HORSE:
                continue
            legacy_source_terms = legacy_terms_by_entry.get(
                legacy_entry.id, []
            )
            legacy_is_core = _is_core_term(
                legacy_entry,
                source,
                legacy_title,
                legacy_body[:500],
                article_source_language,
                legacy_source_terms,
            )
            legacy_semantic = _classify_english_term_context(
                legacy_entry,
                source,
                legacy_title,
                legacy_body[:500],
                legacy_source_terms,
                is_core=legacy_is_core,
            )
            if (
                legacy_semantic
                and legacy_semantic.classification == "common_word"
                and legacy_semantic.confidence >= 0.8
            ):
                behavior_accepted_term_ids.discard(legacy_entry.id)
        duplicate_winner_ids = {
            entry.id for entry in legacy_duplicate_winners.values()
        }
        behavior_accepted_term_ids.intersection_update(
            duplicate_winner_ids
        )
    recognized_horses = (
        _recognize_non_japanese_external_aliases(source, article_source_language, None)
        if article_source_language == SourceLanguage.ENGLISH and context_mode in {"off", "shadow"}
        else recognized_horses_from_resolution(behavior_resolution)
    )
    details["article_entities"] = [
        item.as_dict() for item in occurrence_resolution.entities
    ]
    details["accepted_term_ids"] = sorted(behavior_accepted_term_ids)
    if article_source_language == SourceLanguage.ENGLISH:
        details["english_term_classifications"].extend(
            {
                "term_id": occurrence.term_id,
                "source_ja": occurrence.canonical_text,
                "term_type": occurrence.term_type,
                "term_semantic_classification": (
                    "proper_noun" if occurrence.classification == "confirmed_horse" else occurrence.classification
                ),
                "classification": occurrence.classification,
                "confidence": occurrence.confidence / 100,
                "classification_reason": occurrence.reason,
                "matched_text": occurrence.matched_text,
                "matched_context": occurrence.matched_context,
                "matched_span": [occurrence.start, occurrence.end],
                "match_position": occurrence.field_name,
                "position": "core" if occurrence.field_name == "title" or occurrence.start < 500 else "background",
                "entity_evidence": [
                    item
                    for item in (occurrence.entity_evidence or occurrence.evidence)
                    if item.startswith("race_")
                ],
                "external_horse_ids": list(occurrence.external_horse_ids or []),
                "needs_preserve": occurrence.needs_preserve,
            }
            for occurrence in occurrence_resolution.entities
            if occurrence.term_type == TermType.HORSE or occurrence.external_horse_ids
        )
    for occurrence in occurrence_resolution.entities:
        if (
            context_mode == "enforce"
            and
            occurrence.classification == "uncertain"
            and occurrence.external_horse_ids
            and not occurrence.term_id
        ):
            issues.append(
                _issue(
                    "external_horse_occurrence_uncertain",
                    SEVERITY_INFO,
                    "外部马名索引命中缺少充分语境，仅保留审计：" + occurrence.matched_text,
                    payload=occurrence.as_dict(),
                )
            )
    if progress_callback:
        progress_callback()
    details["recognized_horse_names"] = serialize_recognized_horse_names(recognized_horses)
    preservable_horses = [item for item in recognized_horses if item.needs_preserve][:preserve_limit]
    unknown_horses = [item.matched_text or item.name_ja for item in preservable_horses]
    details["unknown_horse_names"] = unknown_horses
    external_horses = [item for item in preservable_horses if item.source == "external_alias"]
    details["external_horse_names"] = [item.matched_text or item.name_ja for item in external_horses]
    missing_external_horses = [
        item
        for item in external_horses
        if (item.matched_text or item.name_ja)
        and (
            not english_horse_name_has_confirmed_occurrence(
                publish_text, [item.matched_text or item.name_ja]
            )
            if article_source_language == SourceLanguage.ENGLISH and context_mode == "enforce"
            else (item.matched_text or item.name_ja) not in publish_text
        )
    ]
    if missing_external_horses:
        issues.append(
            _issue(
                "external_horse_not_preserved",
                SEVERITY_WARNING,
                "外部已知马名未原样保留：" + "、".join((item.matched_text or item.name_ja) for item in missing_external_horses[:6]),
                payload={
                    "names": [
                        {
                            "name_ja": item.name_ja,
                            "matched_text": item.matched_text,
                            "external_horse_ids": item.external_horse_ids,
                            "primary_external_horse_id": item.primary_external_horse_id,
                            "source": item.source,
                            "confidence": item.confidence,
                            "conflict_flags": item.conflict_flags,
                        }
                        for item in missing_external_horses[:12]
                    ]
                },
            )
        )

    missing_unknown_horses: list[str] = []
    for item in preservable_horses:
        if item.source != "heuristic" or not item.needs_preserve:
            continue
        matched_name = item.matched_text or item.name_ja
        if matched_name and matched_name not in publish_text:
            missing_unknown_horses.append(matched_name)
    if missing_unknown_horses:
        issues.append(
            _issue(
                "unknown_horse_not_preserved",
                SEVERITY_WARNING,
                "疑似未收录马名未原样保留：" + "、".join(missing_unknown_horses[:6]),
                payload={"names": missing_unknown_horses[:12]},
            )
        )

    rejected_horse_candidates = [
        *[
            item
            for item in behavior_resolution.entities
            if item.classification == "common_word"
            and item.term_type == TermType.HORSE
        ],
        *[
            item
            for item in behavior_resolution.suppressed_candidates
            if item.term_type == TermType.HORSE
            and any(
                flag
                in {
                    "inside_person_span",
                    "inside_longer_person_span",
                    "inside_longer_entity",
                    "inside_common_word_span",
                }
                for flag in item.conflict_flags
            )
        ],
    ]
    rejected_horse_targets = {
        item.target_zh
        for item in rejected_horse_candidates
        if item.target_zh
    }
    accepted_horse_targets = {
        item.target_zh
        for item in behavior_resolution.entities
        if item.entity_type == "horse" and item.target_zh
    }
    rejected_horse_targets -= accepted_horse_targets
    stale_machine_tags = sorted(rejected_horse_targets & set(article.tags_json or []))
    rejected_horse_term_ids = {
        item.term_id
        for item in rejected_horse_candidates
        if item.term_id
    }
    accepted_horse_term_ids = {
        item.term_id
        for item in behavior_resolution.entities
        if item.entity_type == "horse" and item.term_id
    }
    rejected_horse_term_ids -= accepted_horse_term_ids
    if batch_context is not None:
        auto_link_term_ids = (batch_context.auto_horse_term_ids_by_article or {}).get(article.id, set())
    else:
        auto_link_term_ids = set(
            ArticleHorseLink.objects.filter(
                article=article,
                status__in=[ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.CANDIDATE],
            ).values_list("horse_profile__primary_term_id", flat=True)
        )
    stale_auto_link_term_ids = sorted(rejected_horse_term_ids & auto_link_term_ids)
    if stale_machine_tags or stale_auto_link_term_ids:
        issues.append(
            _issue(
                "machine_entity_type_mismatch",
                SEVERITY_BLOCKER,
                "机器马名标签与正文实体类型不一致：" + "、".join(stale_machine_tags[:6]),
                route=ROUTE_MANUAL,
                payload={
                    "tags": stale_machine_tags,
                    "auto_link_term_ids": stale_auto_link_term_ids,
                    "entity_type": "common_word",
                },
            )
        )

    missing_terms: list[str] = []
    first_block = gate_body[:500]
    accepted_term_ids = (
        (
            behavior_accepted_term_ids
            if article_source_language == SourceLanguage.ENGLISH
            and context_mode in {"off", "shadow"}
            else (batch_context.accepted_term_ids_by_article or {}).get(
                article.id, behavior_accepted_term_ids
            )
        )
        if batch_context is not None
        else behavior_accepted_term_ids
    )
    context_suppressed_term_ids = {
        item.term_id
        for item in behavior_resolution.suppressed_candidates
        if item.term_id
        and any(
            flag in {"inside_person_span", "inside_longer_entity", "inside_common_word_span"}
            for flag in item.conflict_flags
        )
    }
    if batch_context is not None:
        matched_ids = batch_context.term_entry_ids_by_article.get(article.id, set())
        term_entries = [entry for entry in batch_context.term_entries if entry.id in matched_ids]
        terms_by_language = batch_context.terms_by_language
    if term_entries is None:
        term_entries = list(TermEntry.objects.filter(
            is_active=True,
            term_type__in=[TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.TRAINER],
        ))
    terms_by_entry = (
        terms_by_language.get(article_source_language)
        if terms_by_language and article_source_language in terms_by_language
        else source_terms_by_entry(term_entries, article_source_language)
    )
    for index, entry in enumerate(term_entries, start=1):
        if progress_callback and index % 25 == 1:
            progress_callback()
        source_terms = terms_by_entry.get(entry.pk, [])
        english_horse_occurrences = [
            item
            for item in behavior_resolution.entities
            if article_source_language == SourceLanguage.ENGLISH
            and entry.term_type == TermType.HORSE
            and item.term_id == entry.id
        ]
        v2_matches = (
            _all_source_term_match_contexts(visible_title, visible_body, source_terms)
            if article_source_language == SourceLanguage.ENGLISH
            and (
                context_mode == "shadow"
                or (context_mode == "enforce" and not english_horse_occurrences)
            )
            and context_mode in {"shadow", "enforce"}
            else []
        )
        source_hit = (
            bool(v2_matches) if context_mode == "enforce"
            and article_source_language == SourceLanguage.ENGLISH
            and not english_horse_occurrences
            else _source_term_hit(source, source_terms, article_source_language)
        )
        if not source_hit:
            continue
        matched_source_term = _matched_source_term(source, source_terms, article_source_language)
        ignored_reason = _ignored_source_term_reason(matched_source_term)
        if ignored_reason:
            payload = {
                "term_id": entry.id,
                "source_ja": entry.source_ja,
                "matched_text": matched_source_term,
                "term_type": entry.term_type,
                "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                "article_region": article.racing_region or GLOBAL_RACING_REGION,
                "article_regions": _article_regions_payload(article),
                "source_language": entry.source_language,
                "reason": ignored_reason,
            }
            details["ignored_non_term_gate_terms"].append(payload)
            issues.append(
                _issue(
                    "non_term_gate_ignored",
                    SEVERITY_INFO,
                    "已确认非术语不参与发布阻断：" + entry.source_ja,
                    payload=payload,
                )
            )
            continue
        if entry.id in context_suppressed_term_ids:
            continue
        if article_source_language != SourceLanguage.ENGLISH and entry.id not in accepted_term_ids:
            continue
        if not _term_gate_region_allowed(entry, article, article_source_language):
            payload = {
                "term_id": entry.id,
                "source_ja": entry.source_ja,
                "matched_text": _matched_source_term(source, source_terms, article_source_language),
                "term_type": entry.term_type,
                "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                "article_region": article.racing_region or GLOBAL_RACING_REGION,
                "article_regions": _article_regions_payload(article),
                "source_language": entry.source_language,
                "reason": "region_mismatch",
            }
            details["term_gate_region_excluded_terms"].append(payload)
            issues.append(
                _issue(
                    "term_region_excluded",
                    SEVERITY_INFO,
                    "英文术语因地区不匹配已排除：" + entry.source_ja,
                    payload=payload,
                )
            )
            continue
        if context_mode == "enforce" and english_horse_occurrences and not any(
            item.classification == "confirmed_horse" for item in english_horse_occurrences
        ):
            uncertain_occurrences = [
                item for item in english_horse_occurrences if item.classification == "uncertain"
            ]
            for occurrence in uncertain_occurrences:
                payload = occurrence.as_dict()
                payload.update(
                    {
                        "source_ja": entry.source_ja,
                        "source_language": entry.source_language,
                        "term_type": entry.term_type,
                    }
                )
                issues.append(
                    _issue(
                        "english_horse_occurrence_uncertain",
                        SEVERITY_INFO,
                        "英文马名索引命中缺少充分语境，仅保留审计：" + occurrence.matched_text,
                        payload=payload,
                    )
                )
            # Common-word occurrences are already retained in article_entities;
            # neither class participates in horse preservation or term warnings.
            continue
        confirmed_english_horse_source = bool(
            entry.term_type == TermType.HORSE
            and article_source_language == SourceLanguage.ENGLISH
            and context_mode == "enforce"
            and any(
                item.classification == "confirmed_horse"
                for item in english_horse_occurrences
            )
        )
        if confirmed_english_horse_source:
            original_preserved_in_horse_context = (
                english_horse_name_has_confirmed_occurrence(
                    publish_text, source_terms
                )
            )
            if entry.is_pending_horse_translation:
                preserved = original_preserved_in_horse_context
            else:
                translated_candidates = [entry.target_zh, *(entry.aliases_zh or [])]
                preserved = (
                    original_preserved_in_horse_context
                    or english_horse_name_has_confirmed_occurrence(
                        publish_text,
                        [
                            candidate
                            for candidate in translated_candidates
                            if candidate
                        ],
                    )
                    or _formal_chinese_horse_target_exactly_mentioned(
                        publish_text,
                        [
                            candidate
                            for candidate in translated_candidates
                            if candidate
                        ],
                    )
                )
        else:
            preserved = (
                _pending_horse_original_preserved(publish_text, source_terms)
                if entry.is_pending_horse_translation
                else _term_preserved(
                    entry, publish_text, article_source_language, source_terms
                )
            )
        if not preserved:
            missing_terms.append(entry.source_ja)
            classification_payloads: list[dict] = []
            v2_issue = None
            if v2_matches:
                classification_payloads, v2_issue = _v2_term_gate_result(
                    entry,
                    v2_matches,
                    article,
                    structured_entities=(batch_context.structured_entities_by_article.get(article.id, {}) if batch_context else {}),
                )
                if context_mode == "enforce":
                    details["english_term_classifications"].extend(classification_payloads)
                    issues.append(v2_issue)
                    continue
            if context_mode == "shadow":
                legacy_is_core = _is_core_term(entry, source, title, first_block, article_source_language, source_terms)
                legacy_ambiguous = _ambiguous_english_term_reason(entry, source_terms, is_core=legacy_is_core)
                legacy_semantic = _classify_english_term_context(
                    entry, source, title, first_block, source_terms, is_core=legacy_is_core
                )
                legacy_would_block = bool(
                    legacy_is_core
                    and not legacy_ambiguous
                    and not (
                        legacy_semantic
                        and legacy_semantic.classification == "common_word"
                        and legacy_semantic.confidence >= 0.8
                    )
                )
                shadow = details.setdefault(
                    "english_term_context_shadow",
                    {"would_remove_blocker": False, "would_add_blocker": False, "terms": []},
                )
                v2_blocks = bool(v2_issue and v2_issue.severity == SEVERITY_BLOCKER)
                shadow["would_remove_blocker"] = shadow["would_remove_blocker"] or (legacy_would_block and not v2_blocks)
                shadow["would_add_blocker"] = shadow["would_add_blocker"] or (not legacy_would_block and v2_blocks)
                shadow["terms"].append(
                    {
                        "term_id": entry.id,
                        "source_ja": entry.source_ja,
                        "issue": v2_issue.as_dict() if v2_issue else None,
                        "classifications": classification_payloads,
                        "reason": "classified" if v2_issue else "not_in_visible_source",
                    }
                )
            is_core = _is_core_term(entry, source, title, first_block, article_source_language, source_terms)
            if entry.is_pending_horse_translation:
                confirmed_occurrences = [
                    item.as_dict()
                    for item in english_horse_occurrences
                    if item.classification == "confirmed_horse"
                ]
                issues.append(
                    _issue(
                        "pending_horse_original_missing",
                        SEVERITY_BLOCKER if is_core else SEVERITY_WARNING,
                        "暂无中文译名马名未保留原文：" + entry.source_ja,
                        route=ROUTE_MANUAL if is_core else ROUTE_AUTO,
                        payload={
                            "source_ja": entry.source_ja,
                            "matched_text": _matched_source_term(source, source_terms, article_source_language),
                            "source_language": entry.source_language,
                            "term_type": entry.term_type,
                            "priority": entry.priority,
                            "position": "core" if is_core else "background",
                            "classification": "confirmed_horse",
                            "occurrences": confirmed_occurrences,
                        },
                    )
                )
                continue
            ambiguous_reason = (
                _ambiguous_english_term_reason(entry, source_terms, is_core=is_core)
                if article_source_language == SourceLanguage.ENGLISH
                else ""
            )
            if ambiguous_reason:
                payload = {
                    "term_id": entry.id,
                    "source_ja": entry.source_ja,
                    "matched_text": _matched_source_term(source, source_terms, article_source_language),
                    "source_language": entry.source_language,
                    "target_zh": entry.target_zh,
                    "term_type": entry.term_type,
                    "priority": entry.priority,
                    "position": "core" if is_core else "background",
                    "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                    "article_region": article.racing_region or GLOBAL_RACING_REGION,
                    "article_regions": _article_regions_payload(article),
                    "reason": ambiguous_reason,
                }
                details["ambiguous_term_downgrades"].append(payload)
                issues.append(
                    _issue(
                        "ambiguous_term_downgraded",
                        SEVERITY_WARNING,
                        "高歧义英文术语已降级：" + entry.source_ja,
                        payload=payload,
                    )
                )
                continue
            semantic_decision = (
                _classify_english_term_context(entry, source, title, first_block, source_terms, is_core=is_core)
                if article_source_language == SourceLanguage.ENGLISH
                and (
                    entry.term_type != TermType.HORSE
                    or context_mode in {"off", "shadow"}
                )
                else None
            )
            semantic_payload = _english_term_semantic_payload(semantic_decision) if semantic_decision else {}
            if (
                semantic_decision
                and entry.term_type == TermType.HORSE
                and context_mode in {"off", "shadow"}
            ):
                semantic_payload["classification"] = (
                    "confirmed_horse"
                    if semantic_decision.classification == "proper_noun"
                    else semantic_decision.classification
                )
            if english_horse_occurrences and context_mode == "enforce":
                occurrence = next(
                    (
                        item
                        for item in english_horse_occurrences
                        if item.classification == "confirmed_horse"
                    ),
                    english_horse_occurrences[0],
                )
                semantic_payload = {
                    "classification": occurrence.classification,
                    "term_semantic_classification": (
                        "proper_noun"
                        if occurrence.classification == "confirmed_horse"
                        else occurrence.classification
                    ),
                    "confidence": occurrence.confidence / 100,
                    "classification_reason": occurrence.reason,
                    "matched_text": occurrence.matched_text,
                    "matched_context": occurrence.matched_context,
                    "matched_span": [occurrence.start, occurrence.end],
                    "entity_evidence": list(occurrence.entity_evidence or occurrence.evidence),
                    "external_horse_ids": list(occurrence.external_horse_ids or []),
                }
            if semantic_decision:
                classification_payload = {
                    "term_id": entry.id,
                    "source_ja": entry.source_ja,
                    "source_language": entry.source_language,
                    "target_zh": entry.target_zh,
                    "term_type": entry.term_type,
                    "priority": entry.priority,
                    "position": "core" if is_core else "background",
                    "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                    "article_region": article.racing_region or GLOBAL_RACING_REGION,
                    **semantic_payload,
                }
                details["english_term_classifications"].append(classification_payload)
                if semantic_decision.classification == "common_word" and semantic_decision.confidence >= 0.8:
                    issues.append(
                        _issue(
                            "english_term_common_word_downgraded",
                            SEVERITY_WARNING,
                            "普通英文词命中已降级：" + entry.source_ja,
                            payload=classification_payload,
                        )
                    )
                    continue
            issues.append(
                _issue(
                    "core_term_missing" if is_core else "background_term_missing",
                    SEVERITY_BLOCKER if is_core else SEVERITY_WARNING,
                    ("核心术语未稳定保留：" if is_core else "背景术语未稳定保留：") + entry.source_ja,
                    route=ROUTE_MANUAL if is_core else ROUTE_AUTO,
                    payload={
                        "term_id": entry.id,
                        "source_ja": entry.source_ja,
                        "source_language": entry.source_language,
                        "target_zh": entry.target_zh,
                        "term_type": entry.term_type,
                        "priority": entry.priority,
                        "position": "core" if is_core else "background",
                        "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                        "article_region": article.racing_region or GLOBAL_RACING_REGION,
                        **semantic_payload,
                    },
                )
            )
    details["missing_known_terms"] = missing_terms[:12]

    source_numbers = _important_numbers(source)
    publish_numbers = set(_NUMBER_RE.findall(publish_text))
    missing_numbers = [number for number in source_numbers if number not in publish_numbers]
    details["missing_numbers"] = missing_numbers[:12]
    if len(missing_numbers) >= 4 and len(missing_numbers) >= max(4, len(source_numbers) // 2):
        issues.append(
            _issue(
                "numbers_omitted",
                SEVERITY_WARNING,
                "发布稿省略较多原文数字",
                payload={"missing_numbers": missing_numbers[:12], "source_number_count": len(source_numbers)},
            )
        )
    elif missing_numbers:
        issues.append(
            _issue(
                "numbers_omitted_minor",
                SEVERITY_INFO,
                "发布稿省略少量原文数字",
                payload={"missing_numbers": missing_numbers[:12], "source_number_count": len(source_numbers)},
            )
        )

    quote_fragments = _quote_fragments(article.translated_body_zh or article.body_ja_normalized or article.body_ja_raw)
    details["quote_fragments_checked"] = quote_fragments
    if len(quote_fragments) >= 6:
        issues.append(
            _issue(
                "many_quotes",
                SEVERITY_WARNING,
                "引语较多，建议人工抽检",
                payload={"quote_fragments": quote_fragments},
            )
        )

    # Term consistency gate: check canonical Chinese fields for non-standard
    # term usage.  Only active when TERM_CONSISTENCY_ENABLED is set, to avoid
    # adding queries to the existing publish-gate flow.
    if getattr(settings, "TERM_CONSISTENCY_ENABLED", False):
        try:
            consistency_gate = apply_consistency_gate(article)
            if not consistency_gate.passed:
                for blocker in consistency_gate.blockers:
                    issues.append(
                        _issue(
                            "term_consistency_blocker",
                            SEVERITY_BLOCKER,
                            "术语一致性门禁未通过：" + blocker.get("message", ""),
                            route=ROUTE_MANUAL,
                            payload=blocker,
                        )
                    )
        except Exception:
            # Fail-closed: if the gate itself errors, the article has NOT
            # been validated and must not pass the publish gate silently.
            # Mirror automation.mark_publish_ready, which refuses to proceed
            # when the gate raises.
            issues.append(
                _issue("term_consistency_error", SEVERITY_BLOCKER, "术语一致性检查异常，按未通过处理", route=ROUTE_MANUAL)
            )

    duplicate_issue = detect_duplicate_issue(
        article,
        content_source,
        candidates=batch_context.duplicate_candidates if batch_context is not None else None,
        progress_callback=progress_callback,
    )
    if duplicate_issue:
        issues.append(duplicate_issue)

    issue_dicts = [issue.as_dict() for issue in issues]
    details["issues"] = issue_dicts
    passed = not any(issue.severity == SEVERITY_BLOCKER for issue in issues)
    return ValidationOutcome(passed, _summarize_issues(issues), details, issue_dicts)


def _issue_counts(issues: list[dict]) -> dict:
    return {
        "blocker": sum(1 for issue in issues if issue.get("severity") == SEVERITY_BLOCKER),
        "warning": sum(1 for issue in issues if issue.get("severity") == SEVERITY_WARNING),
        "info": sum(1 for issue in issues if issue.get("severity") == SEVERITY_INFO),
    }


def warning_signature(issues: list[dict]) -> str:
    warning_codes = [
        f"{issue.get('code')}:{issue.get('message')}"
        for issue in issues
        if issue.get("severity") == SEVERITY_WARNING
    ]
    return hashlib.sha256("|".join(sorted(warning_codes)).encode("utf-8")).hexdigest() if warning_codes else ""


def apply_validation_outcome(
    article: NewsArticle,
    outcome: ValidationOutcome,
    *,
    ready_at=None,
    refresh_ready_at: bool = False,
) -> None:
    duplicate_issue = next((issue for issue in outcome.blockers if issue.get("route") == ROUTE_DUPLICATE), None)
    manual_duplicate_issue = next((issue for issue in outcome.blockers if issue.get("code") == "possible_duplicate_content"), None)
    warning_sig = warning_signature(outcome.issues)
    duplicate_payload = (duplicate_issue or manual_duplicate_issue or {}).get("payload") or {}
    if outcome.passed:
        ready_at_changed = transition_to_publish_ready(
            article,
            ready_at=ready_at,
            refresh_ready_at=refresh_ready_at,
        )
        article.review_mode = ReviewMode.AUTO
        article.risk_level = RiskLevel.LOW
        if article.workflow_status in {WorkflowStatus.DUPLICATE, WorkflowStatus.PENDING_REVIEW}:
            article.workflow_status = WorkflowStatus.PENDING_EDIT
        article.decision_summary = outcome.reason
        article.automation_error_message = ""
        update_fields = [
            "automation_status",
            "review_mode",
            "risk_level",
            "workflow_status",
            "decision_summary",
            "automation_error_message",
            "updated_at",
        ]
        if ready_at_changed:
            update_fields.append("publish_ready_at")
    else:
        article.automation_status = AutomationStatus.MANUAL_REVIEW_REQUIRED
        article.review_mode = ReviewMode.MANUAL
        article.risk_level = RiskLevel.MEDIUM
        article.workflow_status = WorkflowStatus.DUPLICATE if duplicate_issue else WorkflowStatus.PENDING_REVIEW
        article.decision_summary = outcome.reason
        article.automation_error_message = outcome.reason
        update_fields = [
            "automation_status",
            "review_mode",
            "risk_level",
            "workflow_status",
            "decision_summary",
            "automation_error_message",
            "updated_at",
        ]
    if duplicate_payload.get("duplicate_of_id"):
        article.duplicate_of_id = duplicate_payload["duplicate_of_id"]
        article.duplicate_score = duplicate_payload.get("duplicate_score")
        article.duplicate_reason = outcome.reason
        update_fields.extend(["duplicate_of", "duplicate_score", "duplicate_reason"])
    elif article.duplicate_of_id or article.duplicate_score is not None or article.duplicate_reason:
        article.duplicate_of = None
        article.duplicate_score = None
        article.duplicate_reason = ""
        update_fields.extend(["duplicate_of", "duplicate_score", "duplicate_reason"])
    article.gate_issues = outcome.issues
    article.decision_reason = {**(article.decision_reason or {}), "gate_issues": outcome.issues, "gate_issue_counts": _issue_counts(outcome.issues)}
    article.automation_warning_email_signature = warning_sig
    update_fields.extend(["gate_issues", "decision_reason", "automation_warning_email_signature"])
    article.save(update_fields=update_fields)
    AutomationLog.objects.create(
        article=article,
        phase=AutomationPhase.VALIDATE,
        result=AutomationResult.SUCCESS if outcome.passed else AutomationResult.FAILED,
        score=article.score_total,
        confidence=article.rewrite_confidence,
        reason=outcome.reason,
        payload={**outcome.details, "issue_counts": _issue_counts(outcome.issues)},
        error_message="" if outcome.passed else outcome.reason,
    )
