from __future__ import annotations

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
