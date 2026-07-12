from __future__ import annotations

from dataclasses import dataclass


ZERO_REASON_ORDER = [
    "search_missed_latest",
    "published_at_unverified",
    "translation_retry_waiting",
    "translation_retry_exhausted",
    "attribution_needs_review",
    "related_region_visible",
]


@dataclass(frozen=True)
class FrancePipelineReport:
    counts: dict[str, int]
    losses: dict[str, int]


def classify_zero_output_reasons(counts: dict[str, int]) -> list[str]:
    return [reason for reason in ZERO_REASON_ORDER if int(counts.get(reason, 0)) > 0]


def summarize_france_pipeline(
    *,
    source_candidates: int,
    deduped_articles: int,
    translated: int,
    attributed: int,
    gate_passed: int,
    selected: int,
    web_published: int,
    qq_delivered: int,
) -> FrancePipelineReport:
    counts = {
        "source_candidates": source_candidates,
        "deduped_articles": deduped_articles,
        "translated": translated,
        "attributed": attributed,
        "gate_passed": gate_passed,
        "selected": selected,
        "web_published": web_published,
        "qq_delivered": qq_delivered,
    }
    return FrancePipelineReport(
        counts=counts,
        losses={
            "dedupe": max(0, source_candidates - deduped_articles),
            "translation": max(0, deduped_articles - translated),
            "attribution": max(0, translated - attributed),
            "gate": max(0, attributed - gate_passed),
            "selection": max(0, gate_passed - selected),
            "web": max(0, selected - web_published),
            "qq": max(0, web_published - qq_delivered),
        },
    )
