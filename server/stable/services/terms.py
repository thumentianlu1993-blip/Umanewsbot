from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Callable

from django.db import connection
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
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


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
        return re.compile(prefix + re.escape(candidate) + suffix, re.IGNORECASE)
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


def extract_horse_tags(text: str, limit: int = 12, source_language: str | None = None) -> list[str]:
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
_HORSE_CONTEXT_RE = re.compile(r"(?:\d+着|\d+番人気|[牡牝セ]\d歳|父|母|産駒|騎手)$")
_STRONG_HORSE_BEFORE_RE = re.compile(r"(?:^|[\s\n　])(?:\d+着|\d+番人気|[牡牝セ]\d歳|父|母|母父|産駒|馬名|出走馬)[:：\s　]*$")
_STRONG_HORSE_AFTER_RE = re.compile(
    r"^(?:[\s　]*(?:\(|（|騎手|ジョッキー|号)|(?:が|は|も)?(?:出走|勝利|優勝|重賞|参戦|遠征|帰厩|始動|引退|登録|騎乗|制覇|V))"
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
}
_NON_HORSE_NOTE_MARKER = "non_horse_common_word"


def _normalize_horse_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


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
    if candidate in title:
        index = title.find(candidate)
        title_after = title[index + len(candidate) : index + len(candidate) + 16] if index >= 0 else ""
        return bool(_STRONG_HORSE_AFTER_RE.search(title_after))
    return False


def _score_heuristic_candidate(full_text: str, title: str, match_start: int, match_end: int, candidate: str) -> int:
    before = full_text[max(0, match_start - 8) : match_start]
    after = full_text[match_end : min(len(full_text), match_end + 8)]
    score = 1
    if candidate in title:
        score += 3
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
    candidate_keys = _non_japanese_alias_candidate_keys(full_text, source_language)
    if not candidate_keys:
        return formal_matches[:limit] if limit is not None else formal_matches
    if aliases is None:
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
        candidate_keys: set[str] = set()
        for _, full_text in rows:
            candidate_keys.update(_non_japanese_alias_candidate_keys(full_text, language))
        queryset = ExternalHorseAlias.objects.filter(source_language=language).exclude(normalized_name="")
        if language == SourceLanguage.ENGLISH:
            queryset = queryset.annotate(normalized_key=Lower("normalized_name")).filter(
                normalized_key__in=candidate_keys
            )
        else:
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
