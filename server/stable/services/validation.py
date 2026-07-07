from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from stable.models import (
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
    _find_source_term_match,
    recognize_horse_names,
    serialize_recognized_horse_names,
    source_term_matches_text,
    source_terms_by_entry,
)


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


def _source_text(article: NewsArticle) -> str:
    return "\n".join([article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""]).strip()


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
    normalized = (text or "").lower()
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
    if source_language != SourceLanguage.ENGLISH:
        return True
    term_region = entry.racing_region or GLOBAL_RACING_REGION
    return term_region in {GLOBAL_RACING_REGION, article.racing_region or GLOBAL_RACING_REGION}


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


def _matched_source_term(text: str, source_terms: list[str], source_language: str | None) -> str:
    for term in source_terms:
        matched = _find_source_term_match(text, term, source_language)
        if matched:
            return matched
    return ""


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


def detect_duplicate_issue(article: NewsArticle, content_source: str) -> GateIssue | None:
    lookback_days = int(getattr(settings, "AUTO_DUPLICATE_LOOKBACK_DAYS", 7))
    high_threshold = float(getattr(settings, "AUTO_DUPLICATE_HIGH_THRESHOLD", 0.86))
    review_threshold = float(getattr(settings, "AUTO_DUPLICATE_REVIEW_THRESHOLD", 0.72))
    if high_threshold <= 0 and review_threshold <= 0:
        return None

    window_start = (article.published_at or timezone.now()) - timedelta(days=lookback_days)
    candidate_text = _article_similarity_text(article, content_source)
    if not candidate_text.strip():
        return None
    queryset = (
        NewsArticle.objects.filter(
            Q(workflow_status=WorkflowStatus.PUBLISHED)
            | Q(review_mode=ReviewMode.AUTO, automation_status=AutomationStatus.PUBLISH_READY),
            published_at__gte=window_start,
        )
        .exclude(pk=article.pk)
        .order_by("-published_at", "-id")[:80]
    )
    best_article: NewsArticle | None = None
    best_score = 0.0
    for other in queryset:
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


def validate_rewrite(article: NewsArticle) -> ValidationOutcome:
    source = _source_text(article)
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
        "ambiguous_term_downgrades": [],
        "missing_numbers": [],
        "quote_fragments_checked": [],
        "issues": [],
    }

    if not _publish_title(article, content_source):
        issues.append(_issue("missing_title", SEVERITY_BLOCKER, "发布稿缺少标题", route=ROUTE_MANUAL))
    if not publish_body:
        issues.append(_issue("missing_body", SEVERITY_BLOCKER, "发布稿缺少正文", route=ROUTE_MANUAL))
    elif len(publish_body) < 80:
        issues.append(_issue("body_too_short", SEVERITY_BLOCKER, "发布正文过短", route=ROUTE_MANUAL))
    if not article.source_url:
        issues.append(_issue("missing_source_url", SEVERITY_BLOCKER, "缺少原文链接", route=ROUTE_MANUAL))
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
    recognized_horses = recognize_horse_names(
        article.title_ja,
        article.body_ja_normalized or article.body_ja_raw,
        limit=None,
        source_language=article_source_language,
    )
    details["recognized_horse_names"] = serialize_recognized_horse_names(recognized_horses)
    preservable_horses = [item for item in recognized_horses if item.needs_preserve][:preserve_limit]
    unknown_horses = [item.matched_text or item.name_ja for item in preservable_horses]
    details["unknown_horse_names"] = unknown_horses
    external_horses = [item for item in preservable_horses if item.source == "external_alias"]
    details["external_horse_names"] = [item.matched_text or item.name_ja for item in external_horses]
    missing_external_horses = [
        item for item in external_horses if (item.matched_text or item.name_ja) and (item.matched_text or item.name_ja) not in publish_text
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

    missing_terms: list[str] = []
    title = article.title_ja or ""
    first_block = (article.body_ja_normalized or article.body_ja_raw or "")[:500]
    term_entries = list(TermEntry.objects.filter(
        is_active=True,
        term_type__in=[TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.TRAINER],
    ))
    terms_by_entry = source_terms_by_entry(term_entries, article_source_language)
    for entry in term_entries:
        source_terms = terms_by_entry.get(entry.pk, [])
        source_hit = _source_term_hit(source, source_terms, article_source_language)
        if not source_hit:
            continue
        if not _term_gate_region_allowed(entry, article, article_source_language):
            payload = {
                "term_id": entry.id,
                "source_ja": entry.source_ja,
                "matched_text": _matched_source_term(source, source_terms, article_source_language),
                "term_type": entry.term_type,
                "term_region": entry.racing_region or GLOBAL_RACING_REGION,
                "article_region": article.racing_region or GLOBAL_RACING_REGION,
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
        if not _term_preserved(entry, publish_text, article_source_language, source_terms):
            missing_terms.append(entry.source_ja)
            is_core = _is_core_term(entry, source, title, first_block, article_source_language, source_terms)
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
            issues.append(
                _issue(
                    "core_term_missing" if is_core else "background_term_missing",
                    SEVERITY_BLOCKER if is_core else SEVERITY_WARNING,
                    ("核心术语未稳定保留：" if is_core else "背景术语未稳定保留：") + entry.source_ja,
                    route=ROUTE_MANUAL if is_core else ROUTE_AUTO,
                    payload={
                        "source_ja": entry.source_ja,
                        "source_language": entry.source_language,
                        "target_zh": entry.target_zh,
                        "term_type": entry.term_type,
                        "priority": entry.priority,
                        "position": "core" if is_core else "background",
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

    duplicate_issue = detect_duplicate_issue(article, content_source)
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


def apply_validation_outcome(article: NewsArticle, outcome: ValidationOutcome) -> None:
    duplicate_issue = next((issue for issue in outcome.blockers if issue.get("route") == ROUTE_DUPLICATE), None)
    manual_duplicate_issue = next((issue for issue in outcome.blockers if issue.get("code") == "possible_duplicate_content"), None)
    warning_sig = warning_signature(outcome.issues)
    duplicate_payload = (duplicate_issue or manual_duplicate_issue or {}).get("payload") or {}
    if outcome.passed:
        article.automation_status = AutomationStatus.PUBLISH_READY
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
