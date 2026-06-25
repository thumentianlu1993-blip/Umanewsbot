from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from stable.models import ExternalHorseAlias, NewsArticle, TermEntry, TermType


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


def resolve_terms(text: str, limit: int = 20) -> list[ResolvedTerm]:
    results: list[ResolvedTerm] = []
    for entry in TermEntry.objects.filter(is_active=True).order_by("-priority", "source_ja"):
        matched = None
        for candidate in entry.all_japanese_terms():
            if candidate and candidate in text:
                matched = candidate
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


def serialize_terms(items: list[ResolvedTerm]) -> list[dict]:
    return [asdict(item) for item in items]


def serialize_recognized_horse_names(items: list[RecognizedHorseName]) -> list[dict]:
    return [asdict(item) for item in items]


def apply_term_mappings(text: str) -> str:
    if not text:
        return text
    mapped = text
    entries = list(TermEntry.objects.filter(is_active=True).order_by("-priority", "source_ja"))
    for entry in entries:
        for candidate in sorted(entry.all_japanese_terms(), key=len, reverse=True):
            if candidate:
                mapped = mapped.replace(candidate, entry.target_zh)
    return mapped


def apply_single_term_mapping(text: str, term: TermEntry) -> str:
    if not text:
        return text
    mapped = text
    for candidate in sorted(term.all_japanese_terms(), key=len, reverse=True):
        if candidate:
            mapped = mapped.replace(candidate, term.target_zh)
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
        mapped_value = apply_single_term_mapping(current_value, term)
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


def extract_horse_tags(text: str, limit: int = 12) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for term in resolve_terms(text or "", limit=max(limit * 3, 20)):
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
    for entry in TermEntry.objects.filter(is_active=True, term_type=TermType.FIXED_PHRASE):
        note = (entry.notes or "").casefold()
        if _NON_HORSE_NOTE_MARKER not in note:
            continue
        for candidate in entry.all_japanese_terms():
            normalized = (candidate or "").strip()
            if normalized:
                words.add(normalized)
    return words


def _known_horse_terms() -> set[str]:
    known_horse_terms: set[str] = set()
    for entry in TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE):
        for candidate in entry.all_japanese_terms():
            normalized = (candidate or "").strip()
            if normalized:
                known_horse_terms.add(normalized)
    return known_horse_terms


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


def _external_aliases_by_normalized(candidates: set[str]) -> dict[str, list[ExternalHorseAlias]]:
    if not candidates:
        return {}
    queryset = (
        ExternalHorseAlias.objects.filter(normalized_name__in=candidates)
        .order_by("normalized_name", "-confidence", "-last_seen_at", "external_horse_id")
    )
    aliases: dict[str, list[ExternalHorseAlias]] = {}
    for alias in queryset:
        aliases.setdefault(alias.normalized_name, []).append(alias)
    return aliases


def recognize_horse_names(title_text: str, body_text: str, limit: int | None = 12) -> list[RecognizedHorseName]:
    title = title_text or ""
    body = body_text or ""
    full_text = "\n".join(part for part in [title, body] if part)
    if not full_text:
        return []

    token_matches = _candidate_tokens(full_text)
    normalized_tokens = {_normalize_horse_name(match.group(0)) for match in token_matches if _normalize_horse_name(match.group(0))}
    alias_lookup = _external_aliases_by_normalized(normalized_tokens)
    known_horse_terms = _known_horse_terms()
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
            record["source"] = "formal_term"
            record["score"] = max(record["score"], 100)
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
        if source == "formal_term":
            recognized.append(
                RecognizedHorseName(
                    name_ja=name,
                    source=source,
                    matched_text=name,
                    confidence=100,
                    external_horse_ids=[],
                    primary_external_horse_id="",
                    needs_preserve=False,
                    has_translation=True,
                    first_position=meta["first"],
                    detection_reason="formal_term",
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
