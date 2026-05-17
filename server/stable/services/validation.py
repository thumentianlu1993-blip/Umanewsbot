from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings

from stable.models import (
    AutomationLog,
    AutomationPhase,
    AutomationResult,
    AutomationStatus,
    NewsArticle,
    ReviewMode,
    RiskLevel,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.terms import extract_unknown_horse_names


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUOTE_RE = re.compile(r"[「『](.*?)[」』]")


@dataclass
class ValidationOutcome:
    passed: bool
    reason: str
    details: dict


def _source_text(article: NewsArticle) -> str:
    return "\n".join([article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""]).strip()


def _rewrite_text(article: NewsArticle) -> str:
    return "\n".join([article.rewrite_title_zh or "", article.rewrite_summary_zh or "", article.rewrite_body_zh or ""]).strip()


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


def validate_rewrite(article: NewsArticle) -> ValidationOutcome:
    source = _source_text(article)
    rewrite = _rewrite_text(article)
    failures: list[str] = []
    details: dict = {
        "unknown_horse_names": [],
        "missing_known_terms": [],
        "missing_numbers": [],
        "quote_fragments_checked": [],
    }

    if not article.rewrite_title_zh or not article.rewrite_body_zh:
        failures.append("改写稿缺少标题或正文")
    if len(article.rewrite_body_zh or "") < 80:
        failures.append("改写正文过短")
    if article.rewrite_confidence < int(getattr(settings, "REWRITE_CONFIDENCE_MIN", 60)):
        failures.append("改写置信度低于阈值")

    unknown_horses = extract_unknown_horse_names(article.title_ja, article.body_ja_normalized or article.body_ja_raw, limit=12)
    details["unknown_horse_names"] = unknown_horses
    for name in unknown_horses:
        if name and name not in rewrite:
            failures.append(f"未收录马名未原样保留：{name}")

    missing_terms: list[str] = []
    for entry in TermEntry.objects.filter(is_active=True, term_type__in=[TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.TRAINER]):
        source_hit = any(term and term in source for term in entry.all_japanese_terms())
        if not source_hit:
            continue
        if entry.target_zh and entry.target_zh not in rewrite and entry.source_ja not in rewrite:
            missing_terms.append(entry.source_ja)
    details["missing_known_terms"] = missing_terms[:12]
    if missing_terms:
        failures.append("关键术语未在改写稿中稳定保留")

    source_numbers = _important_numbers(source)
    rewrite_numbers = set(_NUMBER_RE.findall(rewrite))
    missing_numbers = [number for number in source_numbers if number not in rewrite_numbers]
    details["missing_numbers"] = missing_numbers[:12]
    if len(missing_numbers) >= 4 and len(missing_numbers) >= max(4, len(source_numbers) // 2):
        failures.append("数字一致性校验失败")

    quote_fragments = _quote_fragments(article.translated_body_zh or article.body_ja_normalized or article.body_ja_raw)
    details["quote_fragments_checked"] = quote_fragments
    if len(quote_fragments) >= 6:
        failures.append("引语较多，保守转人工审核")

    if failures:
        return ValidationOutcome(False, "；".join(failures), details)
    return ValidationOutcome(True, "一致性校验通过", details)


def apply_validation_outcome(article: NewsArticle, outcome: ValidationOutcome) -> None:
    if outcome.passed:
        article.automation_status = AutomationStatus.PUBLISH_READY
        article.review_mode = ReviewMode.AUTO
        article.risk_level = RiskLevel.LOW
        update_fields = ["automation_status", "review_mode", "risk_level", "updated_at"]
    else:
        article.automation_status = AutomationStatus.MANUAL_REVIEW_REQUIRED
        article.review_mode = ReviewMode.MANUAL
        article.risk_level = RiskLevel.MEDIUM
        article.workflow_status = WorkflowStatus.PENDING_REVIEW
        article.automation_error_message = outcome.reason
        update_fields = [
            "automation_status",
            "review_mode",
            "risk_level",
            "workflow_status",
            "automation_error_message",
            "updated_at",
        ]
    article.save(update_fields=update_fields)
    AutomationLog.objects.create(
        article=article,
        phase=AutomationPhase.VALIDATE,
        result=AutomationResult.SUCCESS if outcome.passed else AutomationResult.FAILED,
        score=article.score_total,
        confidence=article.rewrite_confidence,
        reason=outcome.reason,
        payload=outcome.details,
        error_message="" if outcome.passed else outcome.reason,
    )
