from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Callable

from django.db import connection
from django.db.models import Q
from django.db.models.functions import Lower

from stable.models import ExternalHorseAlias, NewsArticle, SourceLanguage, TermAlias, TermEntry, TermType


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

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["external_horse_ids"] = list(self.external_horse_ids or [])
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
        return {item.term_id for item in self.entities if item.term_id and item.entity_type != "common_word"}

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


def _normalized_term_candidate(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").replace("’", "'").replace("‘", "'")
    return " ".join(normalized.casefold().split())


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
    r"^\s*(?:\([A-Z]{2,3}\)|,?\s*(?:colt|filly|gelding|mare|horse)\b|"
    r"(?:wins?|won|finished|runs?|ran|returns?|heads?|targets?|entered|defeated|is\s+trained|was\s+ridden|"
    r"will\s+(?:run|target|race|start)|is\s+entered)\b)",
    re.IGNORECASE,
)
_ENGLISH_STRONG_HORSE_BEFORE_RE = re.compile(
    r"(?:(?:^|\b)(?:stall|draw|odds|sire|dam|runner|horse|filly|colt|gelding|mare)\s*(?:[:#-]|\s)\s*|"
    r"(?:^|\n)\s*\d+\s+|\binner\s+)$",
    re.IGNORECASE,
)


def _entity_candidate_keys(text: str, source_language: str) -> set[str]:
    if source_language == SourceLanguage.ENGLISH:
        words = re.findall(
            r"[0-9A-Za-z]+(?:['’.-][0-9A-Za-z]+)*['’]?",
            unicodedata.normalize("NFKC", text or ""),
        )
        keys: set[str] = set()
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
        query_keys = {
            variant
            for item in normalized_keys
            for variant in (item, item.replace("'", "’"), item.replace("'", "‘"))
        }
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
            entry_queryset = entry_queryset.annotate(candidate_key=Lower("source_ja")).filter(
                Q(source_ja__in=keys)
                | Q(candidate_key__in=query_keys)
                | Q(target_zh__in=keys)
                | Q(pk__in=alias_term_ids)
            )
        entries = list(entry_queryset.order_by("-priority", "source_ja", "id"))
        terms_by_entry: dict[int, list[str]] = {}
        for entry in entries:
            if entry.source_language == language:
                terms_by_entry.setdefault(entry.id, []).extend(entry.all_japanese_terms())
            if entry.target_zh and entry.target_zh in keys:
                terms_by_entry.setdefault(entry.id, []).append(entry.target_zh)
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


def _english_title_proper_horse_context(field_name: str, matched_text: str) -> bool:
    if field_name != "title":
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'’.-]*", matched_text or "")
    return (
        len(words) >= 2
        and all(word[:1].isupper() for word in words)
        and _normalized_term_candidate(matched_text) not in ENGLISH_COMMON_WORD_TERM_SEEDS
    )


def _english_candidate_strong_horse_context(
    text: str,
    field_name: str,
    start: int,
    end: int,
    matched_text: str,
) -> bool:
    if _normalized_term_candidate(matched_text) == "nyra":
        return False
    return _english_strong_horse_context(text, start, end) or _english_title_proper_horse_context(
        field_name, matched_text
    )


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
    )


def _resolve_english_entities(
    title: str,
    body: str,
    source_language: str,
    entries: list[TermEntry],
    terms_by_entry: dict[int, list[str]],
    external_aliases: list[ExternalHorseAlias],
) -> tuple[list[ArticleEntity], list[ArticleEntity]]:
    fields = (("title", title), ("body", body))
    entities: list[ArticleEntity] = []
    suppressed: list[ArticleEntity] = []
    person_terms = _person_term_lookup(entries)

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
                        strong = _english_candidate_strong_horse_context(
                            text, field_name, match.start(), match.end(), match.group(0)
                        )
                        entities.append(
                            _make_entity(
                                "horse" if strong else "common_word",
                                match.group(0),
                                field_name,
                                match.start(),
                                match.end(),
                                canonical_text=entry.source_ja,
                                target_zh=entry.target_zh,
                                confidence=95 if strong else 90,
                                evidence=["strong_horse_context" if strong else "ordinary_english_context"],
                                conflict_flags=[] if strong else ["horse_term_without_strong_context"],
                                term=entry,
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
                if any(
                    item.field_name == field_name
                    and item.start == match.start()
                    and item.end == match.end()
                    for item in entities
                ):
                    continue
                strong = _english_candidate_strong_horse_context(
                    text, field_name, match.start(), match.end(), match.group(0)
                )
                entities.append(
                    _make_entity(
                        "horse" if strong else "common_word",
                        match.group(0),
                        field_name,
                        match.start(),
                        match.end(),
                        canonical_text=alias_text,
                        confidence=alias.confidence if strong else 85,
                        evidence=["external_horse_alias", "strong_horse_context" if strong else "ordinary_english_context"],
                        conflict_flags=[] if strong else ["horse_alias_without_strong_context"],
                        needs_preserve=strong,
                        external_horse_ids=[alias.external_horse_id],
                    )
                )
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
            if token in non_horse_words and not common_word_strong and not exact_non_horse_terms:
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
                    if entry.term_type == TermType.HORSE and candidate in non_horse_words:
                        strong = _strong_japanese_common_word_horse_context(text, match.start(), match.end())
                        if not strong:
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
            title, body, source_language, entries, terms_by_entry, external_aliases
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
    article_list = list(articles)
    rows = []
    for article in article_list:
        language = article.source_language or SourceLanguage.JAPANESE
        text = "\n".join(
            part for part in (article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or "") if part
        )
        rows.append((language, text))
    index = _build_article_entity_index(rows)
    return {
        article.id: resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
            preloaded_index=index,
        )
        for article in article_list
    }


def apply_contextual_term_mappings(
    text: str,
    resolution: ArticleEntityResolution,
) -> str:
    mapped = text or ""
    for term in sorted(resolution.accepted_terms, key=lambda item: len(item.matched_text), reverse=True):
        mapped = _replace_source_term(mapped, term.matched_text, term.target_zh, resolution.source_language)
    return mapped


def recognized_horses_from_resolution(resolution: ArticleEntityResolution) -> list[RecognizedHorseName]:
    recognized: list[RecognizedHorseName] = []
    seen: set[tuple[str, str]] = set()
    for item in resolution.entities:
        if item.entity_type not in {"horse", "unknown_horse"}:
            continue
        key = (item.field_name, item.matched_text)
        if key in seen:
            continue
        seen.add(key)
        source = "external_alias" if item.external_horse_ids else (
            "formal_term" if item.entity_type == "horse" and item.term_id else "heuristic"
        )
        recognized.append(
            RecognizedHorseName(
                name_ja=item.canonical_text,
                source=source,
                matched_text=item.matched_text,
                confidence=item.confidence,
                external_horse_ids=list(item.external_horse_ids or []),
                primary_external_horse_id=(item.external_horse_ids or [""])[0],
                needs_preserve=item.needs_preserve,
                has_translation=bool(item.target_zh),
                first_position=item.start,
                detection_reason=item.evidence[0] if item.evidence else "article_entity_resolution",
                conflict_flags=list(item.conflict_flags),
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
    "リベンジ",
    "セール",
    "セレクトセール",
    "セッション",
    "ステークス",
    "ユーロ",
    "豪快",
    "期待",
}
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
