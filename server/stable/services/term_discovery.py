from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from stable.models import (
    NewsArticle,
    SourceLanguage,
    TermCandidate,
    TermCandidateEvidence,
    TermEntry,
    TermType,
)
from stable.services.terms import recognize_horse_names, source_terms_by_entry


SUPPORTED_TERM_TYPES = {TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.OWNER}
MAX_CONTEXTS_PER_EVIDENCE = 5
CONTEXT_RADIUS = 50


@dataclass(frozen=True)
class TermDiscoveryFinding:
    term_type: str
    source_ja: str
    confidence: int
    detector: str
    reason: str
    source_field: str
    context: str


def normalize_japanese_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.translate(str.maketrans({"（": "(", "）": ")", "・": "·"}))
    return normalized.casefold()


def _term_matches(source_terms: list[str], normalized: str) -> bool:
    return any(normalize_japanese_term(value) == normalized for value in source_terms if value)


def match_formal_terms(
    term_type: str,
    source_ja: str,
    source_language: str = SourceLanguage.JAPANESE,
) -> tuple[list[TermEntry], list[TermEntry]]:
    normalized = normalize_japanese_term(source_ja)
    same_type: list[TermEntry] = []
    other_type: list[TermEntry] = []
    entries = list(TermEntry.objects.all())
    terms_by_entry = source_terms_by_entry(entries, source_language)
    for entry in entries:
        if not _term_matches(terms_by_entry.get(entry.pk, []), normalized):
            continue
        if entry.term_type == term_type:
            same_type.append(entry)
        else:
            other_type.append(entry)
    return same_type, other_type


def _context(text: str, source_ja: str) -> str:
    index = text.find(source_ja)
    if index < 0:
        return ""
    start = max(0, index - CONTEXT_RADIUS)
    end = min(len(text), index + len(source_ja) + CONTEXT_RADIUS)
    return text[start:end].strip()


def _finding(term_type: str, source_ja: str, confidence: int, detector: str, reason: str, field: str, text: str):
    if not source_ja or source_ja not in text:
        return None
    return TermDiscoveryFinding(term_type, source_ja, confidence, detector, reason, field, _context(text, source_ja))


def _regex_findings(text: str, field: str) -> list[TermDiscoveryFinding]:
    patterns = [
        (TermType.RACE, re.compile(r"([一-龥々ァ-ヴーA-Za-z0-9・]{2,30}(?:賞|杯|ステークス|記念|カップ|ダービー))"), 85, "race_context", "命中比赛名后缀"),
        (TermType.JOCKEY, re.compile(r"([一-龥々]{2,8})騎手"), 90, "jockey_context", "紧邻“騎手”"),
        (TermType.JOCKEY, re.compile(r"([ァ-ヴー]{3,20})ジョッキー"), 90, "jockey_context", "紧邻“ジョッキー”"),
        (TermType.OWNER, re.compile(r"(?:馬主|オーナー)[はの、:：\s]*([一-龥々ァ-ヴーA-Za-z0-9・株式会社有限会社]{2,30})"), 82, "owner_context", "命中马主或オーナー上下文"),
    ]
    results: list[TermDiscoveryFinding] = []
    for term_type, pattern, confidence, detector, reason in patterns:
        for match in pattern.finditer(text):
            source_ja = match.group(1).strip(" 、。:：")
            finding = _finding(term_type, source_ja, confidence, detector, reason, field, text)
            if finding:
                results.append(finding)
    return results


def discover_term_findings(article: NewsArticle) -> list[TermDiscoveryFinding]:
    fields = [
        ("title_ja", article.title_ja or ""),
        ("body_ja_normalized", article.body_ja_normalized or ""),
    ]
    if not article.body_ja_normalized and article.body_ja_raw:
        fields.append(("body_ja_raw", article.body_ja_raw))

    results: list[TermDiscoveryFinding] = []
    title = article.title_ja or ""
    body = article.body_ja_normalized or article.body_ja_raw or ""
    source_language = article.source_language or SourceLanguage.JAPANESE
    for horse in recognize_horse_names(title, body, limit=None, source_language=source_language):
        if not horse.needs_preserve:
            continue
        matched_text = horse.matched_text or horse.name_ja
        field, text = ("title_ja", title) if matched_text in title else ("body_ja_normalized", body)
        detector = "external_horse_alias" if horse.source == "external_alias" else "unknown_horse"
        reason = "本地外部马名索引命中且缺少中文译名" if horse.source == "external_alias" else "疑似未知马名"
        confidence = max(85, horse.confidence) if horse.source == "external_alias" else horse.confidence
        finding = _finding(TermType.HORSE, matched_text, confidence, detector, reason, field, text)
        if finding:
            results.append(finding)
    for field, text in fields:
        if source_language == SourceLanguage.JAPANESE:
            results.extend(_regex_findings(text, field))
    return results


def _unique_strings(values: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
            if limit and len(result) >= limit:
                break
    return result


def _conflict_payload(entries: list[TermEntry]) -> list[dict]:
    return [
        {"id": entry.id, "term_type": entry.term_type, "source_ja": entry.source_ja, "target_zh": entry.target_zh}
        for entry in entries[:20]
    ]


@transaction.atomic
def aggregate_finding(article: NewsArticle, finding: TermDiscoveryFinding) -> TermCandidate | None:
    if finding.term_type not in SUPPORTED_TERM_TYPES:
        return None
    text = "\n".join([article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""])
    if finding.source_ja not in text:
        return None
    minimum = int(getattr(settings, "TERM_DISCOVERY_MIN_CONFIDENCE", 60))
    if finding.confidence < minimum:
        return None
    source_language = article.source_language or SourceLanguage.JAPANESE
    normalized = normalize_japanese_term(finding.source_ja)
    same_type, other_type = match_formal_terms(finding.term_type, finding.source_ja, source_language)
    if same_type:
        return None
    now = timezone.now()
    defaults = {
        "source_ja": finding.source_ja,
        "source_language": source_language,
        "target_zh": "",
        "aliases_ja": [],
        "aliases_zh": [],
        "suggested_target_zh": "",
        "confidence": finding.confidence,
        "detection_reasons": [finding.reason],
        "conflicts": _conflict_payload(other_type),
        "first_seen_at": now,
        "last_seen_at": now,
    }
    try:
        candidate, _ = TermCandidate.objects.select_for_update().get_or_create(
            term_type=finding.term_type,
            source_language=source_language,
            normalized_key=normalized,
            defaults=defaults,
        )
    except IntegrityError:
        candidate = TermCandidate.objects.select_for_update().get(
            term_type=finding.term_type,
            source_language=source_language,
            normalized_key=normalized,
        )
    evidence, _ = TermCandidateEvidence.objects.select_for_update().get_or_create(candidate=candidate, article=article)
    contexts = _unique_strings([*(evidence.contexts or []), finding.context], MAX_CONTEXTS_PER_EVIDENCE)
    source_fields = _unique_strings([*(evidence.source_fields or []), finding.source_field])
    detectors = _unique_strings([*(evidence.detectors or []), finding.detector])
    reasons = _unique_strings([*(evidence.reasons or []), finding.reason])
    evidence.contexts = contexts
    evidence.source_fields = source_fields
    evidence.detectors = detectors
    evidence.reasons = reasons
    evidence.occurrence_count = max(1, text.count(finding.source_ja))
    evidence.confidence = max(evidence.confidence, finding.confidence)
    evidence.save()

    aggregates = candidate.evidence.aggregate(
        occurrence_count=models.Sum("occurrence_count"),
        article_count=models.Count("article", distinct=True),
        confidence=models.Max("confidence"),
    )
    candidate.source_ja = candidate.source_ja or finding.source_ja
    candidate.occurrence_count = aggregates["occurrence_count"] or 0
    candidate.article_count = aggregates["article_count"] or 0
    candidate.confidence = aggregates["confidence"] or finding.confidence
    candidate.detection_reasons = _unique_strings([*(candidate.detection_reasons or []), finding.reason])
    candidate.conflicts = _conflict_payload(other_type)
    candidate.last_seen_at = now
    candidate.save()
    return candidate


def discover_and_aggregate_article(article: NewsArticle) -> dict:
    findings = discover_term_findings(article)
    candidate_ids: list[int] = []
    for finding in findings:
        candidate = aggregate_finding(article, finding)
        if candidate and candidate.id not in candidate_ids:
            candidate_ids.append(candidate.id)
    return {"article_id": article.id, "finding_count": len(findings), "candidate_ids": candidate_ids}
