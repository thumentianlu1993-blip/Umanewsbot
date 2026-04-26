from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from stable.models import TermEntry


@dataclass
class ResolvedTerm:
    term_type: str
    source_ja: str
    target_zh: str
    matched_text: str
    priority: int
    notes: str


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
_HORSE_CONTEXT_RE = re.compile(r"(?:\d+着|\d+番人気|[牡牝]\d歳|父|母|産駒|騎手)$")
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
}


def extract_unknown_horse_names(title_text: str, body_text: str, limit: int = 12) -> list[str]:
    title = title_text or ""
    body = body_text or ""
    full_text = "\n".join(part for part in [title, body] if part)
    if not full_text:
        return []

    known_horse_terms: set[str] = set()
    for entry in TermEntry.objects.filter(is_active=True, term_type="horse"):
        for candidate in entry.all_japanese_terms():
            normalized = (candidate or "").strip()
            if normalized:
                known_horse_terms.add(normalized)

    candidates: dict[str, dict] = {}
    for match in _KATAKANA_TOKEN_RE.finditer(full_text):
        candidate = match.group(0)
        if candidate in known_horse_terms or candidate in _HORSE_STOPWORDS:
            continue

        before = full_text[max(0, match.start() - 8) : match.start()]
        after = full_text[match.end() : min(len(full_text), match.end() + 8)]
        record = candidates.setdefault(candidate, {"score": 0, "count": 0, "first": match.start()})
        record["count"] += 1
        record["score"] += 1

        if candidate in title:
            record["score"] += 3
        if _HORSE_CONTEXT_RE.search(before):
            record["score"] += 2
        if after.startswith(("(", "（")):
            record["score"] += 2
        if any(hint in after for hint in ("騎手", "は", "が", "で", "に", "を")):
            record["score"] += 1

    ranked = sorted(
        (
            (name, meta["score"], meta["count"], meta["first"])
            for name, meta in candidates.items()
            if meta["score"] >= 3
        ),
        key=lambda item: (-item[1], -item[2], item[3], -len(item[0])),
    )
    return [name for name, _, _, _ in ranked[:limit]]
