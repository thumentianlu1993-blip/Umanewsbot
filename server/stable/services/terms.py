from __future__ import annotations

import re
from functools import lru_cache
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Callable

from django.db import connection
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.html import strip_tags

from stable.models import (
    ArticleRaceLinkStatus,
    ExternalHorseAlias,
    NewsArticle,
    RaceEventResult,
    RaceEventRunner,
    SourceLanguage,
    TermAlias,
    TermEntry,
    TermType,
)


@dataclass
class ResolvedTerm:
    term_type: str
    source_ja: str
    target_zh: str
    matched_text: str
    race_grade: str
    priority: int
    notes: str


@dataclass
class ArticleTermApplyResult:
    updated_fields: list[str]
    skipped_fields: list[str]
    unchanged_fields: list[str]


@dataclass
class RecognizedHorseName:
    name_ja: str
    source: str
    matched_text: str
    confidence: int
    external_horse_ids: list[str]
    primary_external_horse_id: str
    needs_preserve: bool
    has_translation: bool
    first_position: int
    detection_reason: str
    conflict_flags: list[str]
    source_field: str = ""
    matched_span: tuple[int, int] = ()
    matched_context: str = ""
    classification: str = ""
    reason: str = ""


@dataclass
class ArticleEntity:
    entity_type: str
    matched_text: str
    canonical_text: str
    target_zh: str
    field_name: str
    start: int
    end: int
    confidence: int
    evidence: list[str]
    conflict_flags: list[str]
    needs_preserve: bool = False
    term_id: int | None = None
    external_horse_ids: list[str] | None = None
    priority: int = 0
    term_type: str = ""
    classification: str = ""
    reason: str = ""
    matched_context: str = ""
    entity_evidence: list[str] | None = None

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["external_horse_ids"] = list(self.external_horse_ids or [])
        payload["entity_evidence"] = list(self.entity_evidence or self.evidence)
        payload["matched_span"] = [self.start, self.end]
        payload["primary_external_horse_id"] = (self.external_horse_ids or [""])[0]
        return payload


@dataclass
class ArticleEntityResolution:
    source_language: str
    entities: list[ArticleEntity]
    suppressed_candidates: list[ArticleEntity]
    accepted_terms: list[ResolvedTerm]
    machine_horse_tags: list[str]

    @property
    def accepted_term_ids(self) -> set[int]:
        return {
            item.term_id
            for item in self.entities
            if item.term_id and item.entity_type not in {"common_word", "ambiguous"}
        }

    def as_dict(self) -> dict:
        return {
            "source_language": self.source_language,
            "entities": [item.as_dict() for item in self.entities],
            "suppressed_candidates": [item.as_dict() for item in self.suppressed_candidates],
            "accepted_terms": serialize_terms(self.accepted_terms),
            "accepted_term_ids": sorted(self.accepted_term_ids),
            "machine_horse_tags": list(self.machine_horse_tags),
        }


@dataclass
class ArticleEntityIndex:
    entries_by_language: dict[str, list[TermEntry]]
    terms_by_language: dict[str, dict[int, list[str]]]
    external_aliases_by_language: dict[str, list[ExternalHorseAlias]]
    non_horse_words_by_language: dict[str, set[str]]


def _dedupe_source_terms(values: Iterable[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = (value or "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def clean_visible_source_text(text: str) -> str:
    """Return the existing publish-gate visible-text representation."""
    cleaned = text or ""
    for tag in ("script", "style", "nav", "aside"):
        cleaned = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            " ",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
    cleaned = strip_tags(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def visible_source_parts(article: NewsArticle) -> tuple[str, str]:
    title = article.title_ja or ""
    body = article.body_ja_normalized or article.body_ja_raw or ""
    if (article.source_language or SourceLanguage.JAPANESE) != SourceLanguage.ENGLISH:
        return title, body
    return (
        clean_visible_source_text(title),
        clean_visible_source_text(body),
    )


def _alias_texts_by_term(source_language: str | None = None, term_ids: Iterable[int] | None = None) -> dict[int, list[str]]:
    queryset = TermAlias.objects.filter(is_active=True)
    if source_language:
        queryset = queryset.filter(source_language=source_language)
    if term_ids is not None:
        term_ids = list(term_ids)
        if not term_ids:
            return {}
        queryset = queryset.filter(term_id__in=term_ids)
    queryset = queryset.order_by("term_id", "source_language", "alias_type", "text").values_list("term_id", "text")
    aliases: dict[int, list[str]] = {}
    for term_id, text in queryset:
        aliases.setdefault(term_id, []).append(text)
    return aliases


def _entry_source_terms(
    entry: TermEntry,
    *,
    source_language: str | None,
    alias_lookup: dict[int, list[str]],
) -> list[str]:
    values: list[str] = []
    if source_language is None or source_language == entry.source_language:
        values.extend(entry.all_japanese_terms())
    if source_language in {SourceLanguage.CHINESE, SourceLanguage.CHINESE_TRADITIONAL}:
        values.extend([entry.target_zh, *(entry.aliases_zh or [])])
    values.extend(alias_lookup.get(entry.pk, []))
    return _dedupe_source_terms(values)


def normalize_horse_entity_key(value: str) -> str:
    """Return the shared deterministic key for horse names and evidence."""
    normalized = unicodedata.normalize("NFKC", value or "").replace("’", "'").replace("‘", "'")
    return " ".join(normalized.casefold().split())


# Compatibility for private callers while all cross-service code imports the
# public helper above.
_normalized_term_candidate = normalize_horse_entity_key


def _term_query_key_variants(value: str) -> set[str]:
    variants = {value, value.replace("'", "’"), value.replace("'", "‘")}
    if value and value[-1].isalnum():
        variants.add(f"{value}.")
    if " " in value:
        head, tail = value.rsplit(" ", 1)
        variants.add(f"{head}, {tail}")
        variants.add(f"{head}, {tail}.")
    return variants


def _ambiguous_horse_candidates(entries: Iterable[TermEntry], terms_by_entry: dict[int, list[str]]) -> set[str]:
    owners: dict[str, set[int]] = {}
    for entry in entries:
        if entry.term_type != TermType.HORSE:
            continue
        for candidate in terms_by_entry.get(entry.pk, []):
            normalized = _normalized_term_candidate(candidate)
            if normalized:
                owners.setdefault(normalized, set()).add(entry.pk)
    return {candidate for candidate, term_ids in owners.items() if len(term_ids) > 1}


def source_terms_by_entry(entries: Iterable[TermEntry], source_language: str | None = None) -> dict[int, list[str]]:
    entry_list = list(entries)
    alias_lookup = _alias_texts_by_term(source_language, term_ids=[entry.pk for entry in entry_list])
    return {
        entry.pk: _entry_source_terms(entry, source_language=source_language, alias_lookup=alias_lookup)
        for entry in entry_list
    }


def _contains_latin_letter(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value or ""))


@lru_cache(maxsize=65536)
def _source_term_pattern(candidate: str, source_language: str | None):
    if source_language == SourceLanguage.ENGLISH or _contains_latin_letter(candidate):
        prefix = r"(?<![0-9A-Za-z])" if candidate[:1].isascii() and candidate[:1].isalnum() else ""
        suffix = r"(?![0-9A-Za-z])" if candidate[-1:].isascii() and candidate[-1:].isalnum() else ""
        escaped = "".join(r"['’‘]" if character in "'’‘" else re.escape(character) for character in candidate)
        return re.compile(prefix + escaped + suffix, re.IGNORECASE)
    return None


def _find_source_term_match(text: str, candidate: str, source_language: str | None) -> str:
    if not candidate:
        return ""
    pattern = _source_term_pattern(candidate, source_language)
    if pattern:
        match = pattern.search(text)
        return match.group(0) if match else ""
    return candidate if candidate in text else ""


def source_term_matches_text(text: str, candidate: str, source_language: str | None) -> bool:
    return bool(_find_source_term_match(text or "", candidate, source_language))


def _replace_source_term(text: str, candidate: str, target: str, source_language: str | None) -> str:
    if not candidate:
        return text
    pattern = _source_term_pattern(candidate, source_language)
    if pattern:
        return pattern.sub(target, text)
    return text.replace(candidate, target)


_PERSON_TERM_TYPES = {TermType.JOCKEY, TermType.TRAINER, TermType.OWNER}
ENGLISH_COMMON_WORD_TERM_SEEDS = {
    "ace",
    "action",
    "agenda",
    "classic",
    "contact",
    "determined",
    "digital",
    "embraces",
    "enough",
    "ensured",
    "falcon may",
    "fast track",
    "find",
    "good job",
    "however",
    "hopeful",
    "item",
    "live",
    "more than enough",
    "number",
    "nyra",
    "positive",
    "rating",
    "sign",
    "significantly",
    "significant figures",
    "son",
    "step forward",
    "subsequent",
    "tuesday",
    "were",
    "winning streak",
    "years",
}
_ENGLISH_PERSON_NAME_RE = re.compile(
    r"(?<![0-9A-Za-z])(?:[A-Z][A-Za-z'’.-]+\s+){1,3}[A-Z][A-Za-z'’.-]+(?![0-9A-Za-z])"
)
_ENGLISH_PERSON_AFTER_RE = re.compile(
    r"^\s+(?:has\s+joined|joined|joins|was\s+appointed|is\s+appointed|said|says|told|according\s+to)\b",
    re.IGNORECASE,
)
_ENGLISH_PERSON_ROLE_RE = re.compile(
    r"\b(?:as|the)\s+(?:bloodstock\s+and\s+sales\s+)?(?:coordinator|trainer|jockey|manager|director|agent|owner)\b",
    re.IGNORECASE,
)
_ENGLISH_STRONG_HORSE_AFTER_RE = re.compile(
    r"^\s*(?:\([A-Z]{2,3}\)|,?\s*(?:colt|filly|gelding|mare|horse|stallion|broodmare)\b|"
    r"(?:wins?|won|finished|runs?|ran|returns?|heads?|targets?|aims?|entered|defeated|is\s+trained|was\s+ridden|"
    r"will\s+(?:run|target|race|start)|is\s+entered|"
    r"(?:is|was)\s+too\s+strong\s+in\s+the\s+(?:closing|final)\s+stages)\b|"
    r",\s*(?:ridden|trained)\s+by\b)",
    re.IGNORECASE,
)
_ENGLISH_STRONG_HORSE_BEFORE_RE = re.compile(
    r"(?:(?:^|\b)(?:stall|draw|odds|sire|dam|runner|horse|filly|colt|gelding|mare|stallion|broodmare)\s*(?:[:#-]|\s)\s*|"
    r"(?:^|\n)\s*\d+\s+|\binner\s+|\bwinner(?:-turned)?-(?:stallion|mare)\s+)$",
    re.IGNORECASE,
)


def _entity_candidate_keys(text: str, source_language: str) -> set[str]:
    if source_language == SourceLanguage.ENGLISH:
        words = re.findall(
            r"[0-9A-Za-z]+(?:['’.-][0-9A-Za-z]+)*['’]?",
            unicodedata.normalize("NFKC", text or ""),
        )
        keys: set[str] = set()
        for word in words:
            keys.update(part.casefold() for part in re.split(r"[-.]", word) if part)
        for start in range(len(words)):
            for end in range(start + 1, min(len(words), start + 6) + 1):
                keys.add(" ".join(words[start:end]).casefold())
        return keys
    if source_language == SourceLanguage.JAPANESE:
        keys: set[str] = set()
        for match in _KATAKANA_TOKEN_RE.finditer(text or ""):
            token = _normalize_horse_name(match.group(0))
            if not token:
                continue
            keys.add(token)
            for size in range(2, min(16, len(token)) + 1):
                for start in range(0, len(token) - size + 1):
                    keys.add(token[start : start + size])
        for chunk in re.findall(r"[一-龥々〆ヵヶ]{2,}", text or ""):
            for size in range(2, min(12, len(chunk)) + 1):
                for start in range(0, len(chunk) - size + 1):
                    keys.add(chunk[start : start + size])
        latin_words = re.findall(r"[0-9A-Za-z]+(?:['’.-][0-9A-Za-z]+)*", text or "")
        for start in range(len(latin_words)):
            for end in range(start + 1, min(len(latin_words), start + 6) + 1):
                phrase = " ".join(latin_words[start:end])
                keys.update({phrase, phrase.casefold()})
        return keys
    return _non_japanese_alias_candidate_keys(text, source_language)


def _build_article_entity_index(rows: Iterable[tuple[str, str]]) -> ArticleEntityIndex:
    keys_by_language: dict[str, set[str]] = {}
    for language, text in rows:
        keys_by_language.setdefault(language, set()).update(_entity_candidate_keys(text, language))

    entries_by_language: dict[str, list[TermEntry]] = {}
    terms_by_language: dict[str, dict[int, list[str]]] = {}
    external_aliases_by_language: dict[str, list[ExternalHorseAlias]] = {}
    non_horse_words_by_language: dict[str, set[str]] = {}
    for language, keys in keys_by_language.items():
        if not keys:
            entries_by_language[language] = []
            terms_by_language[language] = {}
            external_aliases_by_language[language] = []
            non_horse_words_by_language[language] = set(_HORSE_STOPWORDS) if language == SourceLanguage.JAPANESE else set()
            continue
        normalized_keys = {_normalized_term_candidate(item) for item in keys if item}
        query_keys = {variant for item in normalized_keys for variant in _term_query_key_variants(item)}
        alias_queryset = TermAlias.objects.filter(is_active=True, source_language=language)
        if language == SourceLanguage.ENGLISH:
            alias_queryset = alias_queryset.annotate(candidate_key=Lower("text")).filter(candidate_key__in=query_keys)
        else:
            alias_queryset = alias_queryset.annotate(candidate_key=Lower("text")).filter(
                Q(text__in=keys) | Q(candidate_key__in=query_keys)
            )
        matched_aliases = list(alias_queryset.order_by("term_id", "alias_type", "text"))
        alias_term_ids = {alias.term_id for alias in matched_aliases}

        entry_queryset = TermEntry.objects.filter(is_active=True)
        if language == SourceLanguage.ENGLISH:
            entry_queryset = entry_queryset.annotate(candidate_key=Lower("source_ja")).filter(
                Q(candidate_key__in=query_keys) | Q(pk__in=alias_term_ids)
            )
        else:
            entry_filter = (
                Q(source_ja__in=keys)
                | Q(candidate_key__in=query_keys)
                | Q(pk__in=alias_term_ids)
            )
            if language in {SourceLanguage.CHINESE, SourceLanguage.CHINESE_TRADITIONAL}:
                entry_filter |= Q(target_zh__in=keys)
            entry_queryset = entry_queryset.annotate(candidate_key=Lower("source_ja")).filter(entry_filter)
        entries = list(entry_queryset.order_by("-priority", "source_ja", "id"))
        terms_by_entry: dict[int, list[str]] = {}
        for entry in entries:
            if entry.source_language == language:
                terms_by_entry.setdefault(entry.id, []).extend(entry.all_japanese_terms())
            if language in {SourceLanguage.CHINESE, SourceLanguage.CHINESE_TRADITIONAL}:
                terms_by_entry.setdefault(entry.id, []).extend([entry.target_zh, *(entry.aliases_zh or [])])
        for alias in matched_aliases:
            terms_by_entry.setdefault(alias.term_id, []).append(alias.text)
        terms_by_entry = {
            term_id: _dedupe_source_terms(values)
            for term_id, values in terms_by_entry.items()
        }

        external_queryset = ExternalHorseAlias.objects.filter(source_language=language).exclude(normalized_name="")
        if language == SourceLanguage.ENGLISH:
            external_queryset = external_queryset.annotate(candidate_key=Lower("normalized_name")).filter(
                candidate_key__in=query_keys
            )
        else:
            external_queryset = external_queryset.filter(normalized_name__in=keys)
        external_aliases = list(
            external_queryset.order_by("normalized_name", "-confidence", "-last_seen_at", "external_horse_id")
        )
        entries_by_language[language] = entries
        terms_by_language[language] = terms_by_entry
        external_aliases_by_language[language] = external_aliases
        non_horse_words = set(_HORSE_STOPWORDS) if language == SourceLanguage.JAPANESE else set()
        for entry in entries:
            if entry.term_type != TermType.FIXED_PHRASE or _NON_HORSE_NOTE_MARKER not in (entry.notes or "").casefold():
                continue
            non_horse_words.update(terms_by_entry.get(entry.id, []))
        non_horse_words_by_language[language] = non_horse_words
    return ArticleEntityIndex(
        entries_by_language,
        terms_by_language,
        external_aliases_by_language,
        non_horse_words_by_language,
    )


def _iter_candidate_matches(text: str, candidate: str, source_language: str):
    pattern = _source_term_pattern(candidate, source_language)
    if pattern:
        yield from pattern.finditer(text or "")
        return
    start = 0
    while candidate and (position := (text or "").find(candidate, start)) >= 0:
        yield _SpanMatch(position, position + len(candidate), candidate)
        start = position + len(candidate)


@dataclass(frozen=True)
class _SpanMatch:
    _start: int
    _end: int
    _text: str

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end

    def group(self, _index: int = 0) -> str:
        return self._text


def _overlaps(start: int, end: int, entities: Iterable[ArticleEntity]) -> bool:
    return any(start < item.end and end > item.start for item in entities)


def _english_strong_horse_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 32) : start]
    after = text[end : min(len(text), end + 56)]
    if _ENGLISH_STRONG_HORSE_AFTER_RE.search(after) or _ENGLISH_STRONG_HORSE_BEFORE_RE.search(before):
        return True
    return False


@dataclass(frozen=True)
class EnglishHorseOccurrenceDecision:
    classification: str
    reason: str
    confidence: int
    evidence: tuple[str, ...] = ()


def _english_ordinary_context(text: str, start: int, end: int) -> str:
    """Return a grammatical reason for an ordinary-use occurrence, if proven.

    These are syntax/phrase-shape rules rather than a horse-name stop list.  They
    intentionally inspect only the current occurrence's sentence-sized window.
    """
    before = text[max(0, start - 48) : start]
    after = text[end : min(len(text), end + 64)]
    matched = text[start:end]
    local = f"{before[-32:]}<{matched}>{after[:40]}"
    rules = (
        (r"\b(?:include[ds]?|including|across|throughout)\s+(?:the\s+)?[^<>]{0,30}<[^>]+>(?:\s*,|\s+and\b)", "geographic_or_business_enumeration"),
        (r"\b(?:a|an|the)\s+(?:fair|large|small|considerable|significant|substantial|certain|particular)\s+<[^>]+>\s+of\b", "ordinary_quantity_noun"),
        (r"\b(?:a|an|the)\s+(?:particular|special|strong|renewed)?\s*<[^>]+>\s+on\b", "ordinary_prepositional_noun"),
        (r"\b(?:a|an|the|his|her|their)\s+<[^>]+>\s+to\s+[a-z]", "ordinary_purpose_noun"),
        (r"\b(?:beer|tax|customs?|import|export)\s+<[^>]+>(?:\s|$)", "ordinary_policy_noun"),
        (r"\b(?:and|to|will|would|can|could|should|must)\s+<[^>]+>\s+(?:with|to|the|a|an)\b", "ordinary_verb_context"),
        (r"\b(?:has|have|had|was|were|is|are)\s+<[^>]+>\s+(?:a|an|the|to|into|across|for|at|after|before)\b", "ordinary_predicate_context"),
        (r"\b(?:role|remit|scope|business|company|organisation|organization|team|plan|work)\s+[^<>]{0,12}<[^>]+>\s+(?:to|into|across|for)\b", "ordinary_business_description"),
        (r"\b(?:a|an|the)\s+<[^>]+>\s+(?:performance|effort|job|idea|plan|change|review|update)\b", "ordinary_adjective_context"),
        (r"\b(?:a|an|the)\s+<[^>]+>\s+(?:filly|colt|mare|gelding|horse|crowd|season|meeting)\b", "ordinary_adjective_context"),
        (r"\b(?:as|too|very|quite|rather|so)\s+<[^>]+>(?:\s+to\b|\s+after\b|[,.])", "ordinary_predicate_adjective"),
        (r"\b(?:with|posed?|seeking|another|huge|great|serious|major)\s+(?:a|an|the|another)?\s*<[^>]+>(?:\s|[,.])", "ordinary_abstract_noun"),
        (r"\b(?:has|have|had)\s+<[^>]+>\s+to\b", "ordinary_adverb_context"),
        (r"(?:^|[.!?]\s*)<[^>]+>\s+(?:went|goes|seems|appears|happened)\b", "ordinary_clause_subject"),
        (r"\b\d+(?:\s+\d+/\d+)?\s+<[^>]+>(?:\s|$)", "ordinary_measurement_unit"),
        (r"<[^>]+>\s+(?:work|job|effort|performance|idea|plan|change)\b", "ordinary_adjective_phrase"),
        (r"<[^>]+>\s*-\s*(?:class|level|quality|flight)\b", "ordinary_compound_modifier"),
        (r"\b(?:done|doing|do|did|good|great|important|valuable|hard|their|his|her|our)\s+(?:\w+\s+){0,2}<[^>]+>(?:\s+(?:already|currently|together|underway|on|for)\b|[,.])", "ordinary_work_noun"),
        (r"<[^>]+>\s+(?:already\s+)?(?:underway|together|continues?|begins?|starts?)\b", "ordinary_subject_noun"),
        (r"\bto\s+<[^>]+>\b[^.!?]{0,36}\bup\b", "ordinary_phrasal_verb"),
    )
    for pattern, reason in rules:
        if re.search(pattern, local, re.IGNORECASE):
            return reason
    return ""


def classify_english_horse_occurrence(
    text: str,
    field_name: str,
    start: int,
    end: int,
    *,
    structured_evidence: Iterable[str] = (),
    structured_identity_is_unique: bool = True,
) -> EnglishHorseOccurrenceDecision:
    evidence = tuple(structured_evidence)
    matched_text = text[start:end]
    matched_key = _normalized_term_candidate(text[start:end])
    after = text[end : min(len(text), end + 64)]
    ordinary_reason = _english_ordinary_context(text, start, end)
    copular_repeat = re.match(
        rf"\s+was\s+({re.escape(text[start:end])})\b", after, re.IGNORECASE
    )
    if (
        copular_repeat
        and re.search(
            r"\b(?:the|this) horse\s+(?:wins?|won|finished|runs?|ran|returns?)\b",
            text[
                end + copular_repeat.end() : min(
                    len(text), end + copular_repeat.end() + 96
                )
            ],
            re.IGNORECASE,
        )
    ):
        return EnglishHorseOccurrenceDecision(
            "confirmed_horse",
            "proper_name_copular_adjective_contrast",
            92,
            ("proper_name_copular_adjective_contrast",),
        )
    if (
        ordinary_reason == "ordinary_adjective_context"
        and matched_text[:1].islower()
    ):
        return EnglishHorseOccurrenceDecision(
            "common_word",
            ordinary_reason,
            95,
            (ordinary_reason,),
        )
    if re.match(
        r"\s+(?:filly|colt|mare|gelding|horse|stallion|broodmare)\s+"
        r"(?:wins?|won|finished|runs?|ran|returns?|heads?|targets?|aims?|entered|defeated|starts?|"
        r"(?:is|was)\s+(?:trained|ridden)\s+by)\b",
        after,
        re.IGNORECASE,
    ) or re.match(
        r"\s+(?:filly|colt|mare|gelding|horse|stallion|broodmare)\s*,\s*"
        r"(?:trained|ridden)\s+by\b",
        after,
        re.IGNORECASE,
    ) or re.match(
        r"\s+(?:is|was)\s+(?:(?:a|an|the)\s+)?(?:[a-z][a-z'’-]*\s+){0,2}"
        r"(?:filly|colt|mare|gelding|horse|stallion|broodmare)"
        r"(?:\s*,?\s*(?:who|that|which|and)\s+|\s*,\s*)"
        r"(?:wins?|won|finished|runs?|ran|returns?|heads?|targets?|aims?|entered|defeated|starts?|"
        r"(?:is|was)\s+(?:trained|ridden)\s+by)\b",
        after,
        re.IGNORECASE,
    ) or re.match(
        r"\s*,\s*(?:(?:a|an|the)\s+)?(?:[a-z][a-z'’-]*\s+){0,2}"
        r"(?:filly|colt|mare|gelding|horse|stallion|broodmare)\s*,\s*"
        r"(?:wins?|won|finished|runs?|ran|returns?|heads?|targets?|aims?|entered|defeated|starts?|"
        r"(?:is|was)\s+(?:trained|ridden)\s+by)\b",
        after,
        re.IGNORECASE,
    ):
        return EnglishHorseOccurrenceDecision(
            "confirmed_horse",
            "horse_entity_noun_race_relation",
            97,
            ("horse_entity_noun", "strong_horse_context"),
        )
    if (
        matched_text[:1].isupper()
        and re.match(
            r"\s+(?:runner|colt|filly|mare|gelding|horse|stallion|broodmare)\b",
            after,
            re.IGNORECASE,
        )
    ):
        return EnglishHorseOccurrenceDecision(
            "confirmed_horse",
            "horse_entity_noun_context",
            95,
            ("horse_entity_noun",),
        )
    if evidence and re.match(
        (
            r"\s+to\s+(?:win|contest|run\s+in|race\s+in|target)\s+"
            r"(?:the\s+)?(?:race|racecard|field|meeting|derby|classic)\b"
        ),
        after,
        re.IGNORECASE,
    ):
        return EnglishHorseOccurrenceDecision(
            "confirmed_horse",
            "structured_entity_local_race_relation",
            100,
            (*evidence, "local_race_relation"),
        )
    if ordinary_reason:
        return EnglishHorseOccurrenceDecision("common_word", ordinary_reason, 95, (ordinary_reason,))
    if evidence and structured_identity_is_unique:
        return EnglishHorseOccurrenceDecision("confirmed_horse", "structured_race_entity", 100, evidence)
    if _english_strong_horse_context(text, start, end):
        if matched_key == "nyra":
            return EnglishHorseOccurrenceDecision("common_word", "organization_acronym", 99, ("organization_acronym",))
        return EnglishHorseOccurrenceDecision("confirmed_horse", "strong_horse_context", 96, ("strong_horse_context",))
    seed_key = re.sub(r"^(?:the|a|an)\s+", "", matched_key)
    if matched_key in ENGLISH_COMMON_WORD_TERM_SEEDS or seed_key in ENGLISH_COMMON_WORD_TERM_SEEDS:
        return EnglishHorseOccurrenceDecision("common_word", "reviewed_common_word_context", 90, ("reviewed_common_word_context",))
    return EnglishHorseOccurrenceDecision("uncertain", "lexical_horse_index_only", 45, ("lexical_horse_index",))


def _person_term_lookup(entries: list[TermEntry]) -> dict[str, TermEntry]:
    return {
        _normalized_term_candidate(entry.source_ja): entry
        for entry in entries
        if entry.term_type in _PERSON_TERM_TYPES
    }


def _make_entity(
    entity_type: str,
    matched_text: str,
    field_name: str,
    start: int,
    end: int,
    *,
    canonical_text: str = "",
    target_zh: str = "",
    confidence: int = 0,
    evidence: Iterable[str] = (),
    conflict_flags: Iterable[str] = (),
    needs_preserve: bool = False,
    term: TermEntry | None = None,
    external_horse_ids: Iterable[str] = (),
    classification: str = "",
    reason: str = "",
    matched_context: str = "",
    entity_evidence: Iterable[str] = (),
) -> ArticleEntity:
    return ArticleEntity(
        entity_type=entity_type,
        matched_text=matched_text,
        canonical_text=canonical_text or matched_text,
        target_zh=target_zh,
        field_name=field_name,
        start=start,
        end=end,
        confidence=confidence,
        evidence=list(evidence),
        conflict_flags=list(conflict_flags),
        needs_preserve=needs_preserve,
        term_id=term.id if term else None,
        external_horse_ids=list(external_horse_ids),
        priority=term.priority if term else 0,
        term_type=term.term_type if term else "",
        classification=classification,
        reason=reason,
        matched_context=matched_context,
        entity_evidence=list(entity_evidence),
    )


def _resolve_english_entities(
    title: str,
    body: str,
    source_language: str,
    entries: list[TermEntry],
    terms_by_entry: dict[int, list[str]],
    external_aliases: list[ExternalHorseAlias],
    structured_entities: dict[str, list[str]] | None = None,
) -> tuple[list[ArticleEntity], list[ArticleEntity]]:
    fields = (("title", title), ("body", body))
    entities: list[ArticleEntity] = []
    suppressed: list[ArticleEntity] = []
    person_terms = _person_term_lookup(entries)
    structured_entities = structured_entities or {}
    structured_occurrence_counts = {
        key: sum(
            1
            for _, candidate_text in fields
            for _ in _iter_candidate_matches(
                candidate_text,
                key,
                SourceLanguage.ENGLISH,
            )
        )
        for key in structured_entities
    }

    def decision_for(text: str, field_name: str, match) -> EnglishHorseOccurrenceDecision:
        key = normalize_horse_entity_key(match.group(0))
        structured_evidence = tuple(structured_entities.get(key, ()))
        decision = classify_english_horse_occurrence(
            text,
            field_name,
            match.start(),
            match.end(),
            structured_evidence=structured_evidence,
            structured_identity_is_unique=(
                structured_occurrence_counts.get(key, 0) <= 1
            ),
        )
        if (
            structured_evidence
            and decision.classification == "confirmed_horse"
        ):
            return EnglishHorseOccurrenceDecision(
                decision.classification,
                decision.reason,
                max(decision.confidence, 100),
                tuple(
                    dict.fromkeys(
                        (*decision.evidence, *structured_evidence)
                    )
                ),
            )
        return decision

    def context_for(text: str, start: int, end: int) -> str:
        return text[max(0, start - 60) : min(len(text), end + 60)].strip()

    for field_name, text in fields:
        for entry in entries:
            if entry.term_type not in _PERSON_TERM_TYPES:
                continue
            for candidate in sorted(terms_by_entry.get(entry.id, []), key=len, reverse=True):
                for match in _iter_candidate_matches(text, candidate, source_language):
                    entities.append(
                        _make_entity(
                            "person",
                            match.group(0),
                            field_name,
                            match.start(),
                            match.end(),
                            canonical_text=entry.source_ja,
                            target_zh=entry.target_zh,
                            confidence=100,
                            evidence=["formal_person_term"],
                            term=entry,
                        )
                    )

        for match in _ENGLISH_PERSON_NAME_RE.finditer(text):
            start = match.start()
            end = match.end()
            word_matches = list(re.finditer(r"[A-Z][A-Za-z'’.-]+", match.group(0)))
            # The broad capitalized-name matcher is intentionally permissive,
            # but headlines such as "Grace Hamilton Joins Four Star Sales"
            # would otherwise greedily absorb the verb and following words.
            # Prefer the shortest 2+ word prefix immediately followed by a
            # known person verb.
            for word_count in range(2, len(word_matches) + 1):
                candidate_end = start + word_matches[word_count - 1].end()
                candidate_after = text[candidate_end : min(len(text), candidate_end + 120)]
                if _ENGLISH_PERSON_AFTER_RE.search(candidate_after):
                    end = candidate_end
                    break
            if _overlaps(start, end, [item for item in entities if item.field_name == field_name]):
                continue
            matched = text[start:end]
            name_parts = matched.split()
            if any(part.endswith(".") and len(part.rstrip(".")) > 1 for part in name_parts[:-1]):
                continue
            if matched.split()[-1].casefold() in {"sales", "racing", "stud", "farm", "park", "stables"}:
                continue
            after = text[end : min(len(text), end + 120)]
            if not (_ENGLISH_PERSON_AFTER_RE.search(after) or _ENGLISH_PERSON_ROLE_RE.search(after)):
                continue
            term = person_terms.get(_normalized_term_candidate(matched))
            entities.append(
                _make_entity(
                    "person",
                    matched,
                    field_name,
                    start,
                    end,
                    canonical_text=term.source_ja if term else matched,
                    target_zh=term.target_zh if term else "",
                    confidence=95,
                    evidence=["person_job_context"],
                    term=term,
                )
            )

    people_by_surname: dict[str, dict[str, ArticleEntity]] = {}
    first_person_positions: dict[str, int] = {}
    for person in entities:
        parts = re.findall(r"[A-Za-z][A-Za-z'’.-]*", person.canonical_text)
        if len(parts) < 2:
            continue
        surname = parts[-1].casefold()
        people_by_surname.setdefault(surname, {})[person.canonical_text.casefold()] = person
        global_position = person.start if person.field_name == "title" else len(title) + 1 + person.start
        canonical_key = person.canonical_text.casefold()
        first_person_positions[canonical_key] = min(first_person_positions.get(canonical_key, global_position), global_position)
    for surname, owners in sorted(people_by_surname.items()):
        display_surname = next(iter(owners.values())).canonical_text.split()[-1]
        pattern = _source_term_pattern(display_surname, SourceLanguage.ENGLISH)
        for field_name, text in fields:
            for match in pattern.finditer(text):
                field_people = [item for item in entities if item.field_name == field_name]
                if _overlaps(match.start(), match.end(), field_people):
                    continue
                if len(owners) != 1:
                    suppressed.append(
                        _make_entity(
                            "ambiguous",
                            match.group(0),
                            field_name,
                            match.start(),
                            match.end(),
                            confidence=0,
                            evidence=["person_surname_candidate"],
                            conflict_flags=["ambiguous_person_surname"],
                        )
                    )
                    continue
                owner = next(iter(owners.values()))
                global_position = match.start() if field_name == "title" else len(title) + 1 + match.start()
                if global_position <= first_person_positions[owner.canonical_text.casefold()]:
                    suppressed.append(
                        _make_entity(
                            "ambiguous",
                            match.group(0),
                            field_name,
                            match.start(),
                            match.end(),
                            confidence=0,
                            evidence=["person_surname_candidate"],
                            conflict_flags=["surname_before_full_name"],
                        )
                    )
                    continue
                entities.append(
                    _make_entity(
                        "person",
                        match.group(0),
                        field_name,
                        match.start(),
                        match.end(),
                        canonical_text=owner.canonical_text,
                        target_zh=owner.target_zh,
                        confidence=95,
                        evidence=["person_surname_coreference"],
                        term=next((entry for entry in entries if entry.id == owner.term_id), None),
                    )
                )

    for field_name, text in fields:
        field_people = [item for item in entities if item.field_name == field_name and item.entity_type == "person"]
        for entry in entries:
            if entry.term_type in _PERSON_TERM_TYPES:
                continue
            for candidate in sorted(terms_by_entry.get(entry.id, []), key=len, reverse=True):
                for match in _iter_candidate_matches(text, candidate, source_language):
                    if _overlaps(match.start(), match.end(), field_people):
                        suppressed.append(
                            _make_entity(
                                "horse" if entry.term_type == TermType.HORSE else "term",
                                match.group(0),
                                field_name,
                                match.start(),
                                match.end(),
                                canonical_text=entry.source_ja,
                                target_zh=entry.target_zh,
                                confidence=0,
                                evidence=["term_candidate"],
                                conflict_flags=["inside_person_span"],
                                term=entry,
                            )
                        )
                        continue
                    if entry.term_type == TermType.HORSE:
                        decision = decision_for(text, field_name, match)
                        entities.append(
                            _make_entity(
                                "horse" if decision.classification == "confirmed_horse" else (
                                    "common_word" if decision.classification == "common_word" else "ambiguous"
                                ),
                                match.group(0),
                                field_name,
                                match.start(),
                                match.end(),
                                canonical_text=entry.source_ja,
                                target_zh=entry.target_zh,
                                confidence=decision.confidence,
                                evidence=list(decision.evidence),
                                conflict_flags=[] if decision.classification == "confirmed_horse" else ["horse_term_without_strong_context"],
                                needs_preserve=decision.classification == "confirmed_horse" and not entry.has_translation,
                                term=entry,
                                classification=decision.classification,
                                reason=decision.reason,
                                matched_context=context_for(text, match.start(), match.end()),
                                entity_evidence=decision.evidence,
                            )
                        )
                    else:
                        entities.append(
                            _make_entity(
                                "term",
                                match.group(0),
                                field_name,
                                match.start(),
                                match.end(),
                                canonical_text=entry.source_ja,
                                target_zh=entry.target_zh,
                                confidence=95,
                                evidence=["formal_term"],
                                term=entry,
                            )
                        )

        for alias in external_aliases:
            alias_text = _normalize_horse_name(alias.normalized_name or alias.name_en or alias.name_ja)
            for match in _iter_candidate_matches(text, alias_text, source_language):
                if _overlaps(match.start(), match.end(), field_people):
                    suppressed.append(
                        _make_entity(
                            "horse",
                            match.group(0),
                            field_name,
                            match.start(),
                            match.end(),
                            canonical_text=alias_text,
                            confidence=0,
                            evidence=["external_horse_alias"],
                            conflict_flags=["inside_person_span"],
                            external_horse_ids=[alias.external_horse_id],
                        )
                    )
                    continue
                existing = next((
                    item for item in entities
                    if item.field_name == field_name and item.start == match.start() and item.end == match.end()
                ), None)
                if existing:
                    existing.external_horse_ids = list(dict.fromkeys([
                        *(existing.external_horse_ids or []), alias.external_horse_id
                    ]))
                    if "external_horse_alias" not in existing.evidence:
                        existing.evidence.append("external_horse_alias")
                    continue
                decision = decision_for(text, field_name, match)
                entities.append(
                    _make_entity(
                        "unknown_horse" if decision.classification == "confirmed_horse" else (
                            "common_word" if decision.classification == "common_word" else "ambiguous"
                        ),
                        match.group(0),
                        field_name,
                        match.start(),
                        match.end(),
                        canonical_text=alias_text,
                        confidence=max(decision.confidence, alias.confidence if decision.classification == "confirmed_horse" else 0),
                        evidence=["external_horse_alias", *decision.evidence],
                        conflict_flags=[] if decision.classification == "confirmed_horse" else ["horse_alias_without_strong_context"],
                        needs_preserve=decision.classification == "confirmed_horse",
                        external_horse_ids=[alias.external_horse_id],
                        classification=decision.classification,
                        reason=decision.reason,
                        matched_context=context_for(text, match.start(), match.end()),
                        entity_evidence=decision.evidence,
                    )
                )
    formal_horses_by_span: dict[
        tuple[str, int, int], list[ArticleEntity]
    ] = {}
    for entity in entities:
        if entity.term_id and entity.term_type == TermType.HORSE:
            formal_horses_by_span.setdefault(
                (entity.field_name, entity.start, entity.end), []
            ).append(entity)
    ambiguous_members: set[int] = set()
    merged_ambiguous: list[ArticleEntity] = []
    for group in formal_horses_by_span.values():
        targets = {
            (entity.target_zh or "").strip()
            for entity in group
        }
        if len(group) < 2 or len(targets) < 2:
            continue
        primary = group[0]
        term_ids = sorted(
            entity.term_id for entity in group if entity.term_id is not None
        )
        target_values = sorted(targets)
        primary.term_id = None
        primary.target_zh = ""
        primary.canonical_text = primary.matched_text
        primary.needs_preserve = (
            primary.classification == "confirmed_horse"
        )
        primary.priority = max(entity.priority for entity in group)
        primary.external_horse_ids = list(
            dict.fromkeys(
                external_id
                for entity in group
                for external_id in (entity.external_horse_ids or [])
            )
        )
        primary.evidence = list(
            dict.fromkeys(
                [
                    *(item for entity in group for item in entity.evidence),
                    "ambiguous_formal_horse_name",
                    *(f"formal_term_id:{term_id}" for term_id in term_ids),
                    *(
                        f"formal_target_zh:{target}"
                        for target in target_values
                    ),
                ]
            )
        )
        primary.entity_evidence = list(primary.evidence)
        primary.conflict_flags = list(
            dict.fromkeys(
                [
                    *(
                        item
                        for entity in group
                        for item in entity.conflict_flags
                    ),
                    "ambiguous_formal_horse_name",
                    "conflicting_formal_term_ids",
                    "conflicting_formal_targets",
                ]
            )
        )
        primary.reason = "ambiguous_formal_horse_name"
        ambiguous_members.update(id(entity) for entity in group)
        merged_ambiguous.append(primary)
    if ambiguous_members:
        entities = [
            entity
            for entity in entities
            if id(entity) not in ambiguous_members
        ]
        entities.extend(merged_ambiguous)
    return entities, suppressed


def _resolve_japanese_entities(
    title: str,
    body: str,
    entries: list[TermEntry],
    terms_by_entry: dict[int, list[str]],
    external_aliases: list[ExternalHorseAlias],
    non_horse_words: set[str],
) -> tuple[list[ArticleEntity], list[ArticleEntity]]:
    fields = (("title", title), ("body", body))
    entities: list[ArticleEntity] = []
    suppressed: list[ArticleEntity] = []
    horse_candidates: dict[str, list[TermEntry]] = {}
    all_term_candidates: dict[str, list[TermEntry]] = {}
    for entry in entries:
        for candidate in terms_by_entry.get(entry.id, []):
            all_term_candidates.setdefault(candidate, []).append(entry)
            if entry.term_type == TermType.HORSE:
                horse_candidates.setdefault(candidate, []).append(entry)
    aliases_by_name: dict[str, list[ExternalHorseAlias]] = {}
    for alias in external_aliases:
        name = _normalize_horse_name(alias.normalized_name or alias.name_ja)
        if name:
            aliases_by_name.setdefault(name, []).append(alias)

    for field_name, text in fields:
        protected_spans: list[ArticleEntity] = []
        for match in _JAPANESE_KATAKANA_PERSON_RE.finditer(text):
            matched = match.group(0).strip()
            exact_people = [
                term
                for term in all_term_candidates.get(matched, [])
                if term.term_type in _PERSON_TERM_TYPES
            ]
            person = _make_entity(
                "person",
                matched,
                field_name,
                match.start(),
                match.start() + len(matched),
                canonical_text=exact_people[0].source_ja if exact_people else matched,
                target_zh=exact_people[0].target_zh if exact_people else "",
                confidence=100 if exact_people else 96,
                evidence=["formal_person_term" if exact_people else "japanese_person_role_context"],
                term=exact_people[0] if exact_people else None,
            )
            entities.append(person)
            protected_spans.append(person)
            for candidate, term_list in all_term_candidates.items():
                offset = matched.find(candidate)
                if offset < 0:
                    continue
                for term in term_list:
                    if term.term_type in _PERSON_TERM_TYPES and candidate == matched:
                        continue
                    suppressed.append(
                        _make_entity(
                            "horse" if term.term_type == TermType.HORSE else "term",
                            candidate,
                            field_name,
                            match.start() + offset,
                            match.start() + offset + len(candidate),
                            canonical_text=term.source_ja,
                            target_zh=term.target_zh,
                            confidence=0,
                            evidence=["term_candidate"],
                            conflict_flags=["inside_person_span"],
                            term=term,
                        )
                    )
        person_alias_owners: dict[str, list[ArticleEntity]] = {}
        for person in protected_spans:
            for part in re.findall(r"[ァ-ヴー]{3,}", person.matched_text):
                person_alias_owners.setdefault(part, []).append(person)
        for alias_text, owners in person_alias_owners.items():
            canonical_owners = {owner.canonical_text for owner in owners}
            if len(canonical_owners) != 1:
                continue
            owner = owners[0]
            for alias_match in re.finditer(re.escape(alias_text), text):
                if alias_match.start() <= owner.start or _overlaps(
                    alias_match.start(), alias_match.end(), protected_spans
                ):
                    continue
                coreference = _make_entity(
                    "person",
                    alias_match.group(0),
                    field_name,
                    alias_match.start(),
                    alias_match.end(),
                    canonical_text=owner.canonical_text,
                    target_zh=owner.target_zh,
                    confidence=94,
                    evidence=["japanese_person_coreference"],
                    term=next((entry for entry in entries if entry.id == owner.term_id), None),
                )
                entities.append(coreference)
                protected_spans.append(coreference)
        for match in _KATAKANA_TOKEN_RE.finditer(text):
            token = match.group(0)
            if _overlaps(match.start(), match.end(), protected_spans):
                continue
            exact_terms = horse_candidates.get(token, [])
            exact_non_horse_terms = [
                term for term in all_term_candidates.get(token, []) if term.term_type != TermType.HORSE
            ]
            exact_common_word_terms = [
                term
                for term in exact_non_horse_terms
                if _NON_HORSE_NOTE_MARKER in (term.notes or "").casefold()
            ]
            internal_terms = [
                (candidate, term)
                for candidate, term_list in all_term_candidates.items()
                if candidate != token and candidate in token
                for term in term_list
            ]
            internal_horse_terms = [item for item in internal_terms if item[1].term_type == TermType.HORSE]
            aliases = aliases_by_name.get(_normalize_horse_name(token), [])
            strong = _strong_horse_context(
                text, title if field_name == "title" else "", match.start(), match.end(), token
            ) or _score_heuristic_candidate(text, title, match.start(), match.end(), token) >= 3
            common_word_strong = _strong_japanese_common_word_horse_context(text, match.start(), match.end())
            race_abbreviation = _inside_japanese_race_abbreviation(text, match.end(), token)
            if (
                (token in non_horse_words or race_abbreviation)
                and (race_abbreviation or token in _HORSE_ALWAYS_COMMON_WORDS or not common_word_strong)
                and not exact_non_horse_terms
            ):
                common_word = _make_entity(
                    "common_word",
                    token,
                    field_name,
                    match.start(),
                    match.end(),
                    confidence=100,
                    evidence=["japanese_common_word_seed"],
                    conflict_flags=["horse_candidate_common_word"],
                )
                entities.append(common_word)
                protected_spans.append(common_word)
                for candidate, term in internal_terms:
                    offset = token.find(candidate)
                    suppressed.append(
                        _make_entity(
                            "horse" if term.term_type == TermType.HORSE else "term",
                            candidate,
                            field_name,
                            match.start() + offset,
                            match.start() + offset + len(candidate),
                            canonical_text=term.source_ja,
                            target_zh=term.target_zh,
                            confidence=0,
                            evidence=["term_candidate"],
                            conflict_flags=["inside_common_word_span"],
                            term=term,
                        )
                    )
                continue
            if exact_common_word_terms and not common_word_strong:
                # A reviewed common-word concept wins in ordinary prose, while
                # explicit racecard/result context can still prove a real horse
                # with the same surface form below.
                continue
            if exact_terms:
                term = exact_terms[0]
                entity = _make_entity(
                    "horse",
                    token,
                    field_name,
                    match.start(),
                    match.end(),
                    canonical_text=term.source_ja,
                    target_zh=term.target_zh,
                    confidence=100,
                    evidence=["formal_full_horse_term"],
                    needs_preserve=not term.has_translation,
                    term=term,
                )
            elif aliases:
                entity = _make_entity(
                    "unknown_horse",
                    token,
                    field_name,
                    match.start(),
                    match.end(),
                    confidence=max(alias.confidence for alias in aliases),
                    evidence=["external_full_horse_alias"],
                    needs_preserve=True,
                    external_horse_ids=[alias.external_horse_id for alias in aliases if alias.external_horse_id],
                )
            elif exact_non_horse_terms:
                continue
            elif internal_horse_terms or strong:
                entity = _make_entity(
                    "unknown_horse",
                    token,
                    field_name,
                    match.start(),
                    match.end(),
                    confidence=90 if internal_horse_terms else 78,
                    evidence=[
                        "longest_full_horse_token",
                        "internal_horse_term" if internal_horse_terms else "strong_horse_context",
                    ],
                    needs_preserve=True,
                )
            else:
                continue
            entities.append(entity)
            protected_spans.append(entity)
            for candidate, term in internal_terms:
                offset = token.find(candidate)
                suppressed.append(
                    _make_entity(
                        "horse" if term.term_type == TermType.HORSE else "term",
                        candidate,
                        field_name,
                        match.start() + offset,
                        match.start() + offset + len(candidate),
                        canonical_text=term.source_ja,
                        target_zh=term.target_zh,
                        confidence=0,
                        evidence=["formal_internal_horse_term"],
                        conflict_flags=["inside_longer_entity"],
                        term=term,
                    )
                )

        for entry in entries:
            for candidate in sorted(terms_by_entry.get(entry.id, []), key=len, reverse=True):
                for match in _iter_candidate_matches(text, candidate, SourceLanguage.JAPANESE):
                    if _overlaps(match.start(), match.end(), protected_spans):
                        continue
                    entity_type = "horse" if entry.term_type == TermType.HORSE else (
                        "person" if entry.term_type in _PERSON_TERM_TYPES else "term"
                    )
                    race_abbreviation = _inside_japanese_race_abbreviation(text, match.end(), candidate)
                    if entry.term_type == TermType.HORSE and (candidate in non_horse_words or race_abbreviation):
                        strong = _strong_japanese_common_word_horse_context(text, match.start(), match.end())
                        if race_abbreviation or candidate in _HORSE_ALWAYS_COMMON_WORDS or not strong:
                            entities.append(
                                _make_entity(
                                    "common_word",
                                    match.group(0),
                                    field_name,
                                    match.start(),
                                    match.end(),
                                    canonical_text=entry.source_ja,
                                    target_zh=entry.target_zh,
                                    confidence=95,
                                    evidence=["ordinary_japanese_context"],
                                    conflict_flags=["horse_term_without_strong_context"],
                                    term=entry,
                                )
                            )
                            continue
                    entities.append(
                        _make_entity(
                            entity_type,
                            match.group(0),
                            field_name,
                            match.start(),
                            match.end(),
                            canonical_text=entry.source_ja,
                            target_zh=entry.target_zh,
                            confidence=100,
                            evidence=["formal_term"],
                            needs_preserve=entry.term_type == TermType.HORSE and not entry.has_translation,
                            term=entry,
                        )
                    )
    return entities, suppressed


def _resolve_formal_entities(
    title: str,
    body: str,
    source_language: str,
    entries: list[TermEntry],
    terms_by_entry: dict[int, list[str]],
    external_aliases: list[ExternalHorseAlias],
) -> tuple[list[ArticleEntity], list[ArticleEntity]]:
    entities: list[ArticleEntity] = []
    suppressed: list[ArticleEntity] = []
    for field_name, text in (("title", title), ("body", body)):
        candidates: list[ArticleEntity] = []
        for entry in entries:
            entity_type = "horse" if entry.term_type == TermType.HORSE else (
                "person" if entry.term_type in _PERSON_TERM_TYPES else "term"
            )
            for candidate in terms_by_entry.get(entry.id, []):
                for match in _iter_candidate_matches(text, candidate, source_language):
                    candidates.append(
                        _make_entity(
                            entity_type,
                            match.group(0),
                            field_name,
                            match.start(),
                            match.end(),
                            canonical_text=entry.source_ja,
                            target_zh=entry.target_zh,
                            confidence=100,
                            evidence=["formal_term"],
                            needs_preserve=entry.term_type == TermType.HORSE and not entry.has_translation,
                            term=entry,
                        )
                    )
        for alias in external_aliases:
            alias_text = _normalize_horse_name(
                alias.normalized_name or alias.name_zh_hant or alias.name_en or alias.name_ja
            )
            for match in _iter_candidate_matches(text, alias_text, source_language):
                candidates.append(
                    _make_entity(
                        "horse",
                        match.group(0),
                        field_name,
                        match.start(),
                        match.end(),
                        canonical_text=alias_text,
                        confidence=alias.confidence,
                        evidence=["external_horse_alias"],
                        needs_preserve=True,
                        external_horse_ids=[alias.external_horse_id],
                    )
                )
        accepted_for_field: list[ArticleEntity] = []
        for candidate in sorted(
            candidates,
            key=lambda item: (item.start, -(item.end - item.start), -item.priority, item.entity_type),
        ):
            if _overlaps(candidate.start, candidate.end, accepted_for_field):
                candidate.conflict_flags.append("inside_longer_entity")
                suppressed.append(candidate)
                continue
            accepted_for_field.append(candidate)
        entities.extend(accepted_for_field)
    return entities, suppressed


def _accepted_terms_from_entities(entities: list[ArticleEntity], entries: list[TermEntry]) -> list[ResolvedTerm]:
    entries_by_id = {entry.id: entry for entry in entries}
    accepted: list[ResolvedTerm] = []
    seen: set[tuple[int, str]] = set()
    for entity in entities:
        if entity.entity_type in {"common_word", "unknown_horse", "ambiguous"} or not entity.term_id or not entity.target_zh:
            continue
        key = (entity.term_id, entity.matched_text.casefold())
        if key in seen:
            continue
        seen.add(key)
        entry = entries_by_id[entity.term_id]
        accepted.append(
            ResolvedTerm(
                term_type=entry.term_type,
                source_ja=entry.source_ja,
                target_zh=entry.target_zh,
                matched_text=entity.matched_text,
                race_grade=getattr(entry, "race_grade", ""),
                priority=entry.priority,
                notes=entry.notes,
            )
        )
    accepted.sort(key=lambda item: (-item.priority, -len(item.matched_text), item.matched_text.casefold()))
    return accepted


def resolve_article_entities(
    title_text: str,
    body_text: str,
    *,
    source_language: str = SourceLanguage.JAPANESE,
    preloaded_index: ArticleEntityIndex | None = None,
    structured_entities: dict[str, list[str]] | None = None,
) -> ArticleEntityResolution:
    title = title_text or ""
    body = body_text or ""
    full_text = "\n".join(part for part in (title, body) if part)
    index = preloaded_index or _build_article_entity_index([(source_language, full_text)])
    entries = index.entries_by_language.get(source_language, [])
    terms_by_entry = index.terms_by_language.get(source_language, {})
    external_aliases = index.external_aliases_by_language.get(source_language, [])
    non_horse_words = index.non_horse_words_by_language.get(source_language, set())
    if source_language == SourceLanguage.JAPANESE:
        entities, suppressed = _resolve_japanese_entities(
            title, body, entries, terms_by_entry, external_aliases, non_horse_words
        )
    elif source_language == SourceLanguage.ENGLISH:
        entities, suppressed = _resolve_english_entities(
            title, body, source_language, entries, terms_by_entry, external_aliases, structured_entities
        )
    else:
        entities, suppressed = _resolve_formal_entities(
            title, body, source_language, entries, terms_by_entry, external_aliases
        )
    entities.sort(key=lambda item: (0 if item.field_name == "title" else 1, item.start, -item.end, item.entity_type, item.matched_text))
    suppressed.sort(key=lambda item: (0 if item.field_name == "title" else 1, item.start, -item.end, item.matched_text))
    accepted_terms = _accepted_terms_from_entities(entities, entries)
    tags: list[str] = []
    for entity in entities:
        if entity.entity_type not in {"horse", "unknown_horse"}:
            continue
        tag = (entity.target_zh or (entity.matched_text if entity.needs_preserve else "")).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return ArticleEntityResolution(source_language, entities, suppressed, accepted_terms, tags[:12])


def resolve_article_entities_batch(
    articles: Iterable[NewsArticle],
) -> dict[int, ArticleEntityResolution]:
    return resolve_article_entities_for_articles(articles)


def _structured_horse_entities_for_articles(
    articles: Iterable[NewsArticle],
) -> dict[int, dict[str, list[str]]]:
    article_list = [
        article
        for article in articles
        if (article.source_language or SourceLanguage.JAPANESE) == SourceLanguage.ENGLISH
    ]
    article_ids = [article.id for article in article_list if article.id]
    result: dict[int, dict[str, list[str]]] = {article_id: {} for article_id in article_ids}
    if not article_ids:
        return result
    link_filter = Q(
        event__article_links__article_id__in=article_ids,
        event__article_links__status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL],
        event__article_links__removed_at__isnull=True,
    )
    for kind, queryset in (
        ("runner", RaceEventRunner.objects.filter(link_filter)),
        ("result", RaceEventResult.objects.filter(link_filter)),
    ):
        rows = queryset.values(
            "id", "event_id", "event__article_links__article_id", "horse_name"
        ).distinct()
        for row in rows:
            name = normalize_horse_entity_key(row["horse_name"])
            if not name:
                continue
            result[row["event__article_links__article_id"]].setdefault(name, []).append(
                f"race_{kind}:{row['id']}:event:{row['event_id']}:horse_name"
            )
    return result


def resolve_article_entities_for_articles(
    articles: Iterable[NewsArticle],
    *,
    structured_entities_by_article: dict[int, dict[str, list[str]]] | None = None,
) -> dict[int, ArticleEntityResolution]:
    article_list = list(articles)
    rows = []
    visible_parts_by_article: dict[int, tuple[str, str]] = {}
    for article in article_list:
        language = article.source_language or SourceLanguage.JAPANESE
        visible_parts_by_article[article.id] = visible_source_parts(article)
        text = "\n".join(part for part in visible_parts_by_article[article.id] if part)
        rows.append((language, text))
    index = _build_article_entity_index(rows)
    english_articles = [
        article
        for article in article_list
        if (article.source_language or SourceLanguage.JAPANESE) == SourceLanguage.ENGLISH
    ]
    structured_by_article = (
        structured_entities_by_article
        if structured_entities_by_article is not None
        else _structured_horse_entities_for_articles(english_articles)
    )
    return {
        article.id: resolve_article_entities(
            visible_parts_by_article[article.id][0],
            visible_parts_by_article[article.id][1],
            source_language=article.source_language or SourceLanguage.JAPANESE,
            preloaded_index=index,
            structured_entities=structured_by_article.get(article.id, {}),
        )
        for article in article_list
    }


def resolve_article_entities_for_article(
    article: NewsArticle,
    *,
    title_text: str | None = None,
    body_text: str | None = None,
) -> ArticleEntityResolution:
    if title_text is None and body_text is None:
        return resolve_article_entities_for_articles([article])[article.id]
    title = article.title_ja if title_text is None else title_text
    body = (article.body_ja_normalized or article.body_ja_raw) if body_text is None else body_text
    language = article.source_language or SourceLanguage.JAPANESE
    index = _build_article_entity_index([(language, "\n".join(part for part in (title, body) if part))])
    structured = _structured_horse_entities_for_articles([article]).get(article.id, {})
    return resolve_article_entities(
        title,
        body,
        source_language=language,
        preloaded_index=index,
        structured_entities=structured,
    )


def apply_contextual_term_mappings(
    text: str,
    resolution: ArticleEntityResolution,
    *,
    field_name: str | None = None,
    span_offset: int = 0,
) -> str:
    if resolution.source_language == SourceLanguage.ENGLISH:
        replacements: list[tuple[int, int, str]] = []
        for entity in resolution.entities:
            if field_name and entity.field_name != field_name:
                continue
            if not entity.term_id or not entity.target_zh:
                continue
            if entity.entity_type in {"common_word", "ambiguous", "unknown_horse"}:
                continue
            if entity.term_type == TermType.HORSE and entity.classification != "confirmed_horse":
                continue
            raw_span = _raw_span_for_visible_entity(text, resolution, entity)
            if raw_span is None:
                continue
            start = raw_span[0] - span_offset
            end = raw_span[1] - span_offset
            if start < 0 or end > len(text) or start >= end:
                continue
            if _normalized_term_candidate(text[start:end]) != _normalized_term_candidate(entity.matched_text):
                continue
            replacements.append((start, end, entity.target_zh))
        mapped = text or ""
        accepted_end = len(mapped) + 1
        for start, end, target in sorted(replacements, key=lambda item: (item[0], item[1]), reverse=True):
            if end > accepted_end:
                continue
            mapped = mapped[:start] + target + mapped[end:]
            accepted_end = start
        entity_term_pairs = {
            (_normalized_term_candidate(entity.matched_text), entity.target_zh)
            for entity in resolution.entities
            if entity.term_id and entity.target_zh
        }
        # Compatibility for explicitly supplied non-horse ResolvedTerm objects
        # that predate occurrence entities. Production resolver terms always
        # have entities and therefore stay on the span-safe path above.
        for term in resolution.accepted_terms:
            pair = (_normalized_term_candidate(term.matched_text), term.target_zh)
            if term.term_type == TermType.HORSE or pair in entity_term_pairs:
                continue
            mapped = _replace_source_term(mapped, term.matched_text, term.target_zh, resolution.source_language)
        return mapped
    mapped = text or ""
    for term in sorted(resolution.accepted_terms, key=lambda item: len(item.matched_text), reverse=True):
        mapped = _replace_source_term(mapped, term.matched_text, term.target_zh, resolution.source_language)
    return mapped


def _raw_span_for_visible_entity(
    text: str,
    resolution: ArticleEntityResolution,
    entity: ArticleEntity,
) -> tuple[int, int] | None:
    """Map a visible-text occurrence back to raw text without reviving hidden HTML."""
    if (
        0 <= entity.start < entity.end <= len(text)
        and _normalized_term_candidate(text[entity.start : entity.end])
        == _normalized_term_candidate(entity.matched_text)
    ):
        return entity.start, entity.end
    peers = [
        item
        for item in resolution.entities
        if item.field_name == entity.field_name
        and _normalized_term_candidate(item.matched_text)
        == _normalized_term_candidate(entity.matched_text)
    ]
    peers.sort(key=lambda item: (item.start, item.end))
    try:
        ordinal = peers.index(entity)
    except ValueError:
        return None
    visible_raw_spans: list[tuple[int, int]] = []
    marker = "__UMA_VISIBLE_OCCURRENCE_MARKER__"
    for match in _iter_candidate_matches(text, entity.matched_text, SourceLanguage.ENGLISH):
        marked = text[: match.start()] + marker + text[match.end() :]
        if marker in clean_visible_source_text(marked):
            visible_raw_spans.append((match.start(), match.end()))
    return visible_raw_spans[ordinal] if ordinal < len(visible_raw_spans) else None


def apply_contextual_horse_placeholders(
    text: str,
    resolution: ArticleEntityResolution,
    placeholders: dict[str, str],
    *,
    field_name: str,
) -> str:
    """Protect only confirmed horse occurrence spans for English source text."""
    if resolution.source_language != SourceLanguage.ENGLISH:
        protected = text or ""
        for placeholder, name in placeholders.items():
            protected = protected.replace(name, placeholder)
        return protected
    placeholder_by_name = {
        _normalized_term_candidate(name): placeholder
        for placeholder, name in placeholders.items()
    }
    candidates: list[tuple[int, int, str]] = []
    globally_selected: list[tuple[str, int, int, str]] = []
    for entity in resolution.entities:
        if not entity.needs_preserve:
            continue
        if entity.classification not in {"", "confirmed_horse"}:
            continue
        placeholder = placeholder_by_name.get(_normalized_term_candidate(entity.matched_text))
        if not placeholder:
            continue
        globally_selected.append(
            (entity.field_name, entity.start, entity.end, placeholder)
        )
        if entity.field_name != field_name:
            continue
        raw_span = _raw_span_for_visible_entity(text, resolution, entity)
        if raw_span is None:
            continue
        candidates.append((raw_span[0], raw_span[1], placeholder))

    selected_global: list[tuple[str, int, int, str]] = []
    occupied_by_field: dict[str, list[tuple[int, int]]] = {}
    for candidate in sorted(
        globally_selected,
        key=lambda item: (-(item[2] - item[1]), item[0], item[1], item[2], item[3]),
    ):
        candidate_field, start, end, _ = candidate
        occupied = occupied_by_field.setdefault(candidate_field, [])
        if any(start < other_end and other_start < end for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        selected_global.append(candidate)

    selected_placeholders = {item[3] for item in selected_global}
    for placeholder in list(placeholders):
        if placeholder not in selected_placeholders:
            placeholders.pop(placeholder, None)

    replacements: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-(item[1] - item[0]), item[0], item[1], item[2]),
    ):
        start, end, _ = candidate
        if any(start < other_end and other_start < end for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        replacements.append(candidate)

    protected = text or ""
    for start, end, placeholder in sorted(replacements, key=lambda item: (item[0], item[1]), reverse=True):
        protected = protected[:start] + placeholder + protected[end:]
    return protected


def classify_generated_horse_occurrence(
    text: str,
    start: int,
    end: int,
) -> EnglishHorseOccurrenceDecision:
    """Classify one generated occurrence for both mapping and validation."""
    decision = classify_english_horse_occurrence(
        text or "", "generated", start, end
    )
    if decision.classification == "confirmed_horse":
        return decision
    generated_before = (text or "")[max(0, start - 24) : start]
    generated_after = (text or "")[end : min(len(text or ""), end + 32)]
    if re.match(
        (
            r"^\s*(?:(?:将|已|即将|再次)?(?:"
            r"赢得(?:了)?(?:比赛|赛事|冠军)|"
            r"取胜|获胜|夺冠|出赛|参赛|复出|领衔|"
            r"获得(?:了)?(?:冠军|亚军|季军)|"
            r"(?:名列|跑获)(?:第)?(?:\d+|[一二三四五六七八九十]+)(?:名|位)?|"
            r"由.{0,8}(?:策骑|训练)|"
            r"(?:在|于)[^，。！？\n]{1,12}(?:取胜|获胜|夺冠|出赛|参赛|复出)"
            r"))"
        ),
        generated_after,
    ):
        return EnglishHorseOccurrenceDecision(
            "confirmed_horse",
            "generated_chinese_horse_relation",
            96,
            ("generated_chinese_horse_relation",),
        )
    if (
        re.search(
            r"(?:^|[\s，。！？；：])(?:本场)?(?:冠军|亚军|季军)是\s*$",
            generated_before,
        )
        and re.match(r"^(?:\s|[，。！？；：,.!?;:]|$)", generated_after)
    ):
        return EnglishHorseOccurrenceDecision(
            "confirmed_horse",
            "generated_chinese_result_identity",
            96,
            ("generated_chinese_result_identity",),
        )
    return decision


def english_horse_name_has_confirmed_occurrence(text: str, names: Iterable[str]) -> bool:
    for name in names:
        for match in _iter_candidate_matches(text or "", name, SourceLanguage.ENGLISH):
            decision = classify_generated_horse_occurrence(
                text or "", match.start(), match.end()
            )
            if decision.classification == "confirmed_horse":
                return True
    return False


def apply_generated_text_contextual_mappings(
    text: str,
    resolution: ArticleEntityResolution,
) -> str:
    """Map generated English occurrences only when their own context proves the entity."""
    if resolution.source_language != SourceLanguage.ENGLISH:
        return apply_contextual_term_mappings(text, resolution)
    candidates: dict[tuple[str, str, int], tuple[str, str, int, int]] = {}
    for entity in resolution.entities:
        if (
            entity.term_id
            and entity.target_zh
            and entity.entity_type == "horse"
            and entity.classification == "confirmed_horse"
        ):
            key = (
                normalize_horse_entity_key(entity.matched_text),
                entity.target_zh,
                entity.term_id,
            )
            candidates.setdefault(
                key,
                (
                    entity.matched_text,
                    entity.target_zh,
                    entity.priority,
                    entity.term_id,
                ),
            )
    replacement_candidates: list[
        tuple[int, int, str, int, int]
    ] = []
    for source, target, priority, term_id in candidates.values():
        for match in _iter_candidate_matches(text or "", source, SourceLanguage.ENGLISH):
            decision = classify_generated_horse_occurrence(
                text or "", match.start(), match.end()
            )
            if decision.classification == "confirmed_horse":
                replacement_candidates.append(
                    (
                        match.start(),
                        match.end(),
                        target,
                        priority,
                        term_id,
                    )
                )
    replacements: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, target, priority, term_id in sorted(
        replacement_candidates,
        key=lambda item: (
            -(item[1] - item[0]),
            -item[3],
            item[4],
            item[0],
            item[1],
            item[2],
        ),
    ):
        if any(start < occupied_end and occupied_start < end for occupied_start, occupied_end in occupied):
            continue
        occupied.append((start, end))
        replacements.append((start, end, target))
    mapped = text or ""
    for start, end, target in sorted(replacements, key=lambda item: (item[0], item[1]), reverse=True):
        mapped = mapped[:start] + target + mapped[end:]
    for term in resolution.accepted_terms:
        if term.term_type != TermType.HORSE:
            mapped = _replace_source_term(mapped, term.matched_text, term.target_zh, resolution.source_language)
    return mapped


def recognized_horses_from_resolution(resolution: ArticleEntityResolution) -> list[RecognizedHorseName]:
    recognized: list[RecognizedHorseName] = []
    seen: set[tuple[str, str]] = set()
    formal_span_counts: dict[tuple[str, int, int], int] = {}
    for entity in resolution.entities:
        if entity.term_id and entity.term_type == TermType.HORSE:
            span_key = (entity.field_name, entity.start, entity.end)
            formal_span_counts[span_key] = formal_span_counts.get(span_key, 0) + 1
    for item in resolution.entities:
        if item.entity_type not in {"horse", "unknown_horse"}:
            continue
        key = (item.canonical_text.casefold(), item.target_zh.casefold())
        if key in seen:
            continue
        seen.add(key)
        ambiguous_formal = bool(
            "ambiguous_formal_horse_name" in item.conflict_flags
            or (
                item.term_id
                and formal_span_counts.get(
                    (item.field_name, item.start, item.end), 0
                )
                > 1
            )
        )
        source = (
            "formal_ambiguous_term"
            if ambiguous_formal
            else (
                "formal_term"
                if item.term_id and item.target_zh
                else (
                    "formal_pending_term"
                    if item.term_id
                    else (
                        "external_alias"
                        if item.external_horse_ids
                        else "heuristic"
                    )
                )
            )
        )
        recognized.append(
            RecognizedHorseName(
                name_ja=item.canonical_text,
                source=source,
                matched_text=item.matched_text,
                confidence=item.confidence,
                external_horse_ids=list(item.external_horse_ids or []),
                primary_external_horse_id=(item.external_horse_ids or [""])[0],
                needs_preserve=ambiguous_formal or item.needs_preserve,
                has_translation=bool(item.target_zh) and not ambiguous_formal,
                first_position=item.start,
                detection_reason=item.evidence[0] if item.evidence else "article_entity_resolution",
                conflict_flags=[
                    *item.conflict_flags,
                    *(["ambiguous_formal_horse_name"] if ambiguous_formal else []),
                ],
                source_field=item.field_name,
                matched_span=(item.start, item.end),
                matched_context=item.matched_context,
                classification=item.classification,
                reason=item.reason,
            )
        )
    return recognized


def _resolve_terms_from_entries(text: str, entries, *, source_language: str | None, limit: int) -> list[ResolvedTerm]:
    results: list[ResolvedTerm] = []
    entries = list(entries)
    terms_by_entry = source_terms_by_entry(entries, source_language)
    ambiguous_horse_candidates = _ambiguous_horse_candidates(entries, terms_by_entry)
    for entry in entries:
        matched = None
        candidates = terms_by_entry.get(entry.pk, [])
        for candidate in candidates:
            if entry.term_type == TermType.HORSE and _normalized_term_candidate(candidate) in ambiguous_horse_candidates:
                continue
            matched_candidate = _find_source_term_match(text, candidate, source_language)
            if matched_candidate:
                matched = matched_candidate
                break
        if matched:
            results.append(
                ResolvedTerm(
                    term_type=entry.term_type,
                    source_ja=entry.source_ja,
                    target_zh=entry.target_zh,
                    matched_text=matched,
                    race_grade=getattr(entry, "race_grade", ""),
                    priority=entry.priority,
                    notes=entry.notes,
                )
            )
    results.sort(key=lambda item: (-item.priority, -len(item.matched_text), item.source_ja))
    return results[:limit]


def resolve_terms(text: str, limit: int = 20) -> list[ResolvedTerm]:
    entries = TermEntry.objects.filter(is_active=True).order_by("-priority", "source_ja")
    results = _resolve_terms_from_entries(text or "", entries, source_language=None, limit=max(limit * 3, 20))
    deduped: list[ResolvedTerm] = []
    seen: set[tuple[str, str]] = set()
    for item in results:
        key = (item.source_ja, item.target_zh)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def resolve_terms_for_language(text: str, source_language: str, limit: int = 20) -> list[ResolvedTerm]:
    queryset = TermEntry.objects.filter(is_active=True).order_by("-priority", "source_ja")
    return _resolve_terms_from_entries(text or "", queryset, source_language=source_language, limit=limit)


def serialize_terms(items: list[ResolvedTerm]) -> list[dict]:
    return [asdict(item) for item in items]


def serialize_recognized_horse_names(items: list[RecognizedHorseName]) -> list[dict]:
    return [asdict(item) for item in items]


def apply_term_mappings(text: str, source_language: str | None = None) -> str:
    if not text:
        return text
    mapped = text
    entries = list(TermEntry.objects.filter(is_active=True).order_by("-priority", "source_ja"))
    terms_by_entry = source_terms_by_entry(entries, source_language)
    ambiguous_horse_candidates = _ambiguous_horse_candidates(entries, terms_by_entry)
    for entry in entries:
        if not entry.has_translation:
            continue
        candidates = terms_by_entry.get(entry.pk, [])
        for candidate in sorted(candidates, key=len, reverse=True):
            if entry.term_type == TermType.HORSE and _normalized_term_candidate(candidate) in ambiguous_horse_candidates:
                continue
            mapped = _replace_source_term(mapped, candidate, entry.target_zh, source_language)
    return mapped


def apply_single_term_mapping(text: str, term: TermEntry, source_language: str | None = None) -> str:
    if not text:
        return text
    if not term.has_translation:
        return text
    mapped = text
    candidates = term.source_terms_for_language(source_language) if source_language else term.all_source_terms()
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate:
            mapped = _replace_source_term(mapped, candidate, term.target_zh, source_language)
    return mapped


def apply_created_term_to_article(article: NewsArticle, term: TermEntry) -> ArticleTermApplyResult:
    machine_fields = ["translated_title_zh", "translated_body_zh", "translated_summary_zh", "base_translation_zh"]
    publish_fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
    manual_fields = set(article.manually_edited_fields or [])

    updated_fields: list[str] = []
    skipped_fields: list[str] = []
    unchanged_fields: list[str] = []

    for field_name in [*machine_fields, *publish_fields]:
        current_value = getattr(article, field_name, "") or ""
        mapped_value = apply_single_term_mapping(
            current_value,
            term,
            article.source_language or SourceLanguage.JAPANESE,
        )
        if mapped_value == current_value:
            unchanged_fields.append(field_name)
            continue
        if field_name in publish_fields and field_name in manual_fields:
            skipped_fields.append(field_name)
            continue
        setattr(article, field_name, mapped_value)
        updated_fields.append(field_name)

    if updated_fields:
        article.save(update_fields=[*updated_fields, "updated_at"])

    return ArticleTermApplyResult(
        updated_fields=updated_fields,
        skipped_fields=skipped_fields,
        unchanged_fields=unchanged_fields,
    )


def extract_horse_tags(
    text: str,
    limit: int = 12,
    source_language: str | None = None,
    *,
    entity_resolution: ArticleEntityResolution | None = None,
) -> list[str]:
    if entity_resolution is not None:
        return list(entity_resolution.machine_horse_tags[:limit])
    tags: list[str] = []
    seen: set[str] = set()
    terms = (
        resolve_terms_for_language(text or "", source_language, limit=max(limit * 3, 20))
        if source_language
        else resolve_terms(text or "", limit=max(limit * 3, 20))
    )
    for term in terms:
        if term.term_type != "horse":
            continue
        tag = (term.target_zh or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


_KATAKANA_TOKEN_RE = re.compile(r"[ァ-ヴー]{3,}")
_JAPANESE_KATAKANA_PERSON_RE = re.compile(
    r"[ァ-ヴー]{3,}(?:[・\s　][ァ-ヴー]{3,})*\s*(?=騎手|ジョッキー|調教師)"
)
_HORSE_CONTEXT_RE = re.compile(r"(?:\d+着|\d+番人気|[牡牝セ]\d歳|父|母|産駒|騎手)$")
_STRONG_HORSE_BEFORE_RE = re.compile(
    r"(?:^|[\s\n　])(?:\d+着|\d+番人気|\d+枠\d+番|\d+番|[牡牝セ]\d歳|父|母|母父|産駒|馬名|出走馬)[:：\s　]*$"
)
_STRONG_HORSE_AFTER_RE = re.compile(
    r"^(?:[\s　]*(?:\(|（|号|[牡牝セ]\d(?:歳)?)|(?:が|は|も)?(?:出走|勝利|優勝|重賞|参戦|遠征|"
    r"帰厩|始動|引退|登録|騎乗|制覇|挑戦|挑む|狙う|目指す|向かう|V))"
)
_HORSE_STOPWORDS = {
    "コメント",
    "クラシック",
    "ライバル",
    "スタート",
    "ゴール",
    "レース",
    "ランキング",
    "メンバー",
    "コース",
    "ホームページ",
    "パーティー",
    "トップ",
    "ファン",
    "ファーム",
    "フリー",
    "リベンジ",
    "リーチ",
    "リーディングサイアー",
    "セール",
    "セレクトセール",
    "セッション",
    "ステークス",
    "ユーロ",
    "ユタカ",
    "豪快",
    "期待",
    "サイン",
    "天才",
}
_HORSE_ALWAYS_COMMON_WORDS = {"ユタカ"}
_JAPANESE_RACE_ABBREVIATION_SUFFIXES = {"ジャパン": {"C", "Ｃ"}}
_NON_HORSE_NOTE_MARKER = "non_horse_common_word"


def _normalize_horse_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def _strong_japanese_common_word_horse_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 16) : start]
    after = text[end : min(len(text), end + 24)]
    if _STRONG_HORSE_BEFORE_RE.search(before):
        return True
    if re.match(r"^[\s　]*[（(][牡牝セ]\d", after):
        return True
    return bool(
        re.match(
            r"^[\s　]*(?:が|は|も)?(?:出走|勝利|優勝|参戦|遠征|帰厩|始動|引退|登録|制覇)",
            after,
        )
    )


def _inside_japanese_race_abbreviation(text: str, end: int, candidate: str) -> bool:
    suffixes = _JAPANESE_RACE_ABBREVIATION_SUFFIXES.get(candidate, set())
    return bool(suffixes and text[end : end + 1] in suffixes)


def non_horse_common_words() -> set[str]:
    words = set(_HORSE_STOPWORDS)
    entries = list(TermEntry.objects.filter(is_active=True, term_type=TermType.FIXED_PHRASE))
    terms_by_entry = source_terms_by_entry(entries, SourceLanguage.JAPANESE)
    for entry in entries:
        note = (entry.notes or "").casefold()
        if _NON_HORSE_NOTE_MARKER not in note:
            continue
        for candidate in terms_by_entry.get(entry.pk, []):
            normalized = (candidate or "").strip()
            if normalized:
                words.add(normalized)
    return words


def _known_horse_terms_by_candidate(source_language: str = SourceLanguage.JAPANESE) -> dict[str, list[TermEntry]]:
    known_horse_terms: dict[str, list[TermEntry]] = {}
    entries = list(TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE))
    terms_by_entry = source_terms_by_entry(entries, source_language)
    for entry in entries:
        for candidate in terms_by_entry.get(entry.pk, []):
            normalized = (candidate or "").strip()
            if normalized:
                known_horse_terms.setdefault(normalized, []).append(entry)
    return known_horse_terms


def _known_horse_terms(source_language: str = SourceLanguage.JAPANESE) -> set[str]:
    return set(_known_horse_terms_by_candidate(source_language))


def _recognize_formal_horse_terms(full_text: str, source_language: str, limit: int | None) -> list[RecognizedHorseName]:
    entries = list(TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE).order_by("-priority", "source_ja"))
    terms_by_entry = source_terms_by_entry(entries, source_language)
    ambiguous_candidates = _ambiguous_horse_candidates(entries, terms_by_entry)
    recognized: list[RecognizedHorseName] = []
    seen: set[tuple[int | str, str]] = set()
    for entry in entries:
        for candidate in sorted(terms_by_entry.get(entry.pk, []), key=len, reverse=True):
            matched_text = _find_source_term_match(full_text, candidate, source_language)
            if not matched_text:
                continue
            position = full_text.find(matched_text)
            if position < 0 and source_language == SourceLanguage.ENGLISH:
                position = full_text.casefold().find(matched_text.casefold())
            normalized_candidate = _normalized_term_candidate(candidate)
            is_ambiguous = normalized_candidate in ambiguous_candidates
            key = ("ambiguous" if is_ambiguous else entry.pk, normalized_candidate)
            if key in seen:
                continue
            seen.add(key)
            has_translation = entry.has_translation
            recognized.append(
                RecognizedHorseName(
                    name_ja=entry.source_ja,
                    source="formal_ambiguous_term" if is_ambiguous else ("formal_term" if has_translation else "formal_pending_term"),
                    matched_text=matched_text,
                    confidence=100,
                    external_horse_ids=[],
                    primary_external_horse_id="",
                    needs_preserve=is_ambiguous or not has_translation,
                    has_translation=has_translation and not is_ambiguous,
                    first_position=max(position, 0),
                    detection_reason="formal_ambiguous_term" if is_ambiguous else ("formal_term" if has_translation else "formal_pending_term"),
                    conflict_flags=["ambiguous_formal_horse_name"] if is_ambiguous else [],
                )
            )
            break
    recognized.sort(key=lambda item: (item.first_position, -len(item.matched_text), -item.confidence, item.name_ja))
    return recognized[:limit] if limit is not None else recognized


def _strong_horse_context(full_text: str, title: str, match_start: int, match_end: int, candidate: str) -> bool:
    before = full_text[max(0, match_start - 12) : match_start]
    after = full_text[match_end : min(len(full_text), match_end + 16)]
    if _STRONG_HORSE_BEFORE_RE.search(before):
        return True
    if _STRONG_HORSE_AFTER_RE.search(after):
        return True
    if re.match(r"^[\s　]*(?:が|は|も).{0,14}(?:出走|参戦|挑戦|挑む|狙う|目指す|向かう|勝利|優勝)", after):
        return True
    if candidate in title:
        index = title.find(candidate)
        title_after = title[index + len(candidate) : index + len(candidate) + 16] if index >= 0 else ""
        return bool(_STRONG_HORSE_AFTER_RE.search(title_after))
    return False


def _score_heuristic_candidate(full_text: str, title: str, match_start: int, match_end: int, candidate: str) -> int:
    before = full_text[max(0, match_start - 8) : match_start]
    after = full_text[match_end : min(len(full_text), match_end + 8)]
    score = 1
    if _HORSE_CONTEXT_RE.search(before):
        score += 2
    if after.startswith(("(", "（")):
        score += 2
    if any(hint in after for hint in ("騎手", "は", "が", "で", "に", "を")):
        score += 1
    return score


def _candidate_tokens(full_text: str) -> list[re.Match[str]]:
    return list(_KATAKANA_TOKEN_RE.finditer(full_text))


def _external_aliases_by_normalized(
    candidates: set[str],
    *,
    source_language: str | None = None,
) -> dict[str, list[ExternalHorseAlias]]:
    if not candidates:
        return {}
    queryset = ExternalHorseAlias.objects.filter(normalized_name__in=candidates)
    if source_language:
        queryset = queryset.filter(source_language=source_language)
    queryset = queryset.order_by("normalized_name", "-confidence", "-last_seen_at", "external_horse_id")
    aliases: dict[str, list[ExternalHorseAlias]] = {}
    for alias in queryset:
        aliases.setdefault(alias.normalized_name, []).append(alias)
    return aliases


def _comparable_horse_name(value: str, source_language: str) -> str:
    normalized = _normalize_horse_name(value)
    if source_language == SourceLanguage.ENGLISH:
        return normalized.casefold()
    return normalized


def _non_japanese_alias_candidate_keys(full_text: str, source_language: str) -> set[str]:
    normalized_text = _normalize_horse_name(full_text)
    if not normalized_text:
        return set()
    if source_language == SourceLanguage.ENGLISH:
        words = re.findall(r"[0-9A-Za-z][0-9A-Za-z'’.-]*", normalized_text)
        keys: set[str] = set()
        max_words = 6
        for start in range(len(words)):
            for end in range(start + 1, min(len(words), start + max_words) + 1):
                keys.add(" ".join(words[start:end]).casefold())
        return keys

    keys = set()
    for chunk in re.split(r"[\s，。、《》「」『』（）()：:；;、,.!?！？\n\r\t]+", normalized_text):
        compact = chunk.strip()
        if not compact:
            continue
        max_len = min(12, len(compact))
        for size in range(2, max_len + 1):
            for start in range(0, len(compact) - size + 1):
                keys.add(compact[start : start + size])
    return keys


def _find_non_japanese_alias_match(full_text: str, alias_text: str, source_language: str) -> tuple[int, str]:
    comparable_alias = _comparable_horse_name(alias_text, source_language)
    if not comparable_alias:
        return -1, ""
    if source_language == SourceLanguage.ENGLISH:
        pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(alias_text) + r"(?![0-9A-Za-z])", re.IGNORECASE)
        match = pattern.search(full_text)
        return (match.start(), match.group(0)) if match else (-1, "")
    comparable_text = _comparable_horse_name(full_text, source_language)
    position = comparable_text.find(comparable_alias)
    if position < 0:
        return -1, ""
    return position, full_text[position : position + len(alias_text)]


def _recognize_non_japanese_external_aliases(
    full_text: str,
    source_language: str,
    limit: int | None,
    *,
    aliases: Iterable[ExternalHorseAlias] | None = None,
    known_horse_terms: set[str] | None = None,
    progress_callback: Callable[[], None] | None = None,
) -> list[RecognizedHorseName]:
    formal_matches: list[RecognizedHorseName] = []
    if known_horse_terms is None:
        formal_matches = _recognize_formal_horse_terms(full_text, source_language, limit=None)
        known_horse_terms = {
            _comparable_horse_name(term, source_language) for term in _known_horse_terms(source_language)
        }
    candidates: dict[str, dict] = {}
    if aliases is None:
        candidate_keys = _non_japanese_alias_candidate_keys(full_text, source_language)
        if not candidate_keys:
            return formal_matches[:limit] if limit is not None else formal_matches
        queryset = ExternalHorseAlias.objects.filter(source_language=source_language).exclude(normalized_name="")
        if source_language == SourceLanguage.ENGLISH:
            queryset = queryset.annotate(normalized_key=Lower("normalized_name")).filter(normalized_key__in=candidate_keys)
        else:
            queryset = queryset.filter(normalized_name__in=candidate_keys)
        aliases = queryset.order_by("normalized_name", "-confidence", "-last_seen_at", "external_horse_id")
    for index, alias in enumerate(aliases, start=1):
        if progress_callback and index % 100 == 1:
            progress_callback()
        alias_text = _normalize_horse_name(alias.normalized_name or alias.name_en or alias.name_zh_hant or alias.name_ja)
        comparable_alias = _comparable_horse_name(alias_text, source_language)
        if not comparable_alias or comparable_alias in known_horse_terms:
            continue
        position, matched_text = _find_non_japanese_alias_match(full_text, alias_text, source_language)
        if position < 0:
            continue
        record = candidates.setdefault(
            comparable_alias,
            {
                "name": alias_text,
                "matched_text": matched_text,
                "first": position,
                "score": 0,
                "aliases": [],
            },
        )
        if position < record["first"]:
            record["first"] = position
            record["matched_text"] = matched_text
        record["score"] = max(record["score"], alias.confidence)
        record["aliases"].append(alias)

    recognized: list[RecognizedHorseName] = []
    for meta in candidates.values():
        horse_ids: list[str] = []
        for alias in meta["aliases"]:
            if alias.external_horse_id and alias.external_horse_id not in horse_ids:
                horse_ids.append(alias.external_horse_id)
        recognized.append(
            RecognizedHorseName(
                name_ja=meta["name"],
                source="external_alias",
                matched_text=meta["matched_text"],
                confidence=int(meta["score"]),
                external_horse_ids=horse_ids,
                primary_external_horse_id=horse_ids[0] if horse_ids else "",
                needs_preserve=True,
                has_translation=False,
                first_position=meta["first"],
                detection_reason="external_horse_alias",
                conflict_flags=[],
            )
        )
    recognized.sort(key=lambda item: (item.first_position, -len(item.matched_text), -item.confidence, item.name_ja))
    combined = [*formal_matches, *recognized]
    combined.sort(key=lambda item: (item.first_position, -len(item.matched_text), -item.confidence, item.name_ja))
    return combined[:limit] if limit is not None else combined


def recognize_horse_names_batch(
    articles: Iterable[NewsArticle],
    *,
    limit: int | None = 12,
    progress_callback: Callable[[], None] | None = None,
    known_horse_terms_by_language: dict[str, set[str]] | None = None,
    query_count_callback: Callable[[str, int], None] | None = None,
) -> dict[int, list[RecognizedHorseName]]:
    article_list = list(articles)
    if article_list and all(
        (article.source_language or SourceLanguage.JAPANESE) == SourceLanguage.ENGLISH
        for article in article_list
    ):
        resolutions = resolve_article_entities_for_articles(article_list)
        return {
            article.id: recognized_horses_from_resolution(resolutions[article.id])[:limit]
            if limit is not None
            else recognized_horses_from_resolution(resolutions[article.id])
            for article in article_list
        }
    recognized: dict[int, list[RecognizedHorseName]] = {}
    grouped: dict[str, list[tuple[NewsArticle, str]]] = {}
    for article in article_list:
        if progress_callback:
            progress_callback()
        language = article.source_language or SourceLanguage.JAPANESE
        full_text = "\n".join(
            part for part in [article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""] if part
        )
        if language == SourceLanguage.JAPANESE:
            recognized[article.id] = recognize_horse_names(
                article.title_ja,
                article.body_ja_normalized or article.body_ja_raw,
                limit=limit,
                source_language=language,
            )
            continue
        grouped.setdefault(language, []).append((article, full_text))

    for language, rows in grouped.items():
        if progress_callback:
            progress_callback()
        queryset = ExternalHorseAlias.objects.filter(source_language=language).exclude(normalized_name="")
        if language != SourceLanguage.ENGLISH:
            candidate_keys: set[str] = set()
            for _, full_text in rows:
                candidate_keys.update(_non_japanese_alias_candidate_keys(full_text, language))
            queryset = queryset.filter(normalized_name__in=candidate_keys)
        query_counter = {"count": 0}

        def count_query(execute, sql, params, many, context):
            query_counter["count"] += 1
            return execute(sql, params, many, context)

        with connection.execute_wrapper(count_query):
            aliases = list(queryset.order_by("normalized_name", "-confidence", "-last_seen_at", "external_horse_id"))
        if query_count_callback:
            query_count_callback("horse_alias_prefetch_count", query_counter["count"])
        if progress_callback:
            progress_callback()
        if known_horse_terms_by_language is not None:
            known_terms = known_horse_terms_by_language.get(language, set())
        else:
            known_terms = {_comparable_horse_name(term, language) for term in _known_horse_terms(language)}
            if query_count_callback:
                query_count_callback("horse_term_prefetch_count", 2)
        for article, full_text in rows:
            recognized[article.id] = _recognize_non_japanese_external_aliases(
                full_text,
                language,
                limit,
                aliases=aliases,
                known_horse_terms=known_terms,
                progress_callback=progress_callback,
            )
    return recognized


def recognize_horse_names(
    title_text: str,
    body_text: str,
    limit: int | None = 12,
    source_language: str = SourceLanguage.JAPANESE,
) -> list[RecognizedHorseName]:
    title = title_text or ""
    body = body_text or ""
    full_text = "\n".join(part for part in [title, body] if part)
    if not full_text:
        return []
    if source_language == SourceLanguage.ENGLISH:
        recognized = recognized_horses_from_resolution(
            resolve_article_entities(title, body, source_language=source_language)
        )
        return recognized[:limit] if limit is not None else recognized
    if source_language != SourceLanguage.JAPANESE:
        return _recognize_non_japanese_external_aliases(full_text, source_language, limit)

    token_matches = _candidate_tokens(full_text)
    normalized_tokens = {_normalize_horse_name(match.group(0)) for match in token_matches if _normalize_horse_name(match.group(0))}
    alias_lookup = _external_aliases_by_normalized(normalized_tokens, source_language=source_language)
    known_horse_terms = _known_horse_terms_by_candidate(source_language)
    stopwords = non_horse_common_words()

    candidates: dict[str, dict] = {}
    for match in token_matches:
        candidate = match.group(0)
        normalized = _normalize_horse_name(candidate)
        if not normalized:
            continue

        record = candidates.setdefault(
            candidate,
            {
                "first": match.start(),
                "count": 0,
                "score": 0,
                "source": "",
                "aliases": [],
                "conflict_flags": [],
            },
        )
        record["count"] += 1
        record["first"] = min(record["first"], match.start())

        if candidate in known_horse_terms:
            terms = known_horse_terms[candidate]
            record["source"] = "formal_ambiguous_term" if len(terms) > 1 else "formal_term"
            record["term"] = terms[0]
            record["score"] = max(record["score"], 100)
            if len(terms) > 1:
                record["conflict_flags"] = sorted(
                    set([*record["conflict_flags"], "ambiguous_formal_horse_name"])
                )
            continue

        aliases = alias_lookup.get(normalized, [])
        if aliases:
            conflict_flags = ["non_horse_common_word"] if candidate in stopwords else []
            if conflict_flags and not _strong_horse_context(full_text, title, match.start(), match.end(), candidate):
                record["conflict_flags"] = sorted(set([*record["conflict_flags"], *conflict_flags]))
                continue
            record["source"] = "external_alias"
            record["aliases"] = aliases
            record["score"] = max(record["score"], max(alias.confidence for alias in aliases))
            record["conflict_flags"] = sorted(set([*record["conflict_flags"], *conflict_flags]))
            continue

        if candidate in stopwords:
            continue

        score = _score_heuristic_candidate(full_text, title, match.start(), match.end(), candidate)
        record["score"] += score
        if not record["source"]:
            record["source"] = "heuristic"

    recognized: list[RecognizedHorseName] = []
    for name, meta in candidates.items():
        source = meta["source"]
        if source in {"formal_term", "formal_ambiguous_term"}:
            term = meta.get("term")
            is_ambiguous = source == "formal_ambiguous_term"
            has_translation = bool(term and term.has_translation and not is_ambiguous)
            recognized.append(
                RecognizedHorseName(
                    name_ja=name,
                    source=source if is_ambiguous or has_translation else "formal_pending_term",
                    matched_text=name,
                    confidence=100,
                    external_horse_ids=[],
                    primary_external_horse_id="",
                    needs_preserve=is_ambiguous or not has_translation,
                    has_translation=has_translation,
                    first_position=meta["first"],
                    detection_reason=source if is_ambiguous else ("formal_term" if has_translation else "formal_pending_term"),
                    conflict_flags=meta["conflict_flags"],
                )
            )
            continue
        if source == "external_alias":
            aliases = meta["aliases"]
            horse_ids: list[str] = []
            for alias in aliases:
                if alias.external_horse_id and alias.external_horse_id not in horse_ids:
                    horse_ids.append(alias.external_horse_id)
            recognized.append(
                RecognizedHorseName(
                    name_ja=name,
                    source=source,
                    matched_text=name,
                    confidence=int(meta["score"]),
                    external_horse_ids=horse_ids,
                    primary_external_horse_id=horse_ids[0] if horse_ids else "",
                    needs_preserve=True,
                    has_translation=False,
                    first_position=meta["first"],
                    detection_reason="external_horse_alias",
                    conflict_flags=meta["conflict_flags"],
                )
            )
            continue
        if source == "heuristic" and meta["score"] >= 3:
            recognized.append(
                RecognizedHorseName(
                    name_ja=name,
                    source=source,
                    matched_text=name,
                    confidence=78 if name in title else 70,
                    external_horse_ids=[],
                    primary_external_horse_id="",
                    needs_preserve=True,
                    has_translation=False,
                    first_position=meta["first"],
                    detection_reason="unknown_horse",
                    conflict_flags=meta["conflict_flags"],
                )
            )

    recognized.sort(key=lambda item: (item.first_position, -len(item.matched_text), -item.confidence, item.name_ja))
    return recognized[:limit] if limit is not None else recognized


def extract_unknown_horse_names(title_text: str, body_text: str, limit: int = 12) -> list[str]:
    return [
        item.name_ja
        for item in recognize_horse_names(title_text, body_text, limit=None)
        if item.needs_preserve
    ][:limit]
