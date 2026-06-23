from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    AutomationLog,
    AutomationPhase,
    AutomationResult,
    AutomationStatus,
    ContentCategory,
    NewsArticle,
    NotificationType,
    PublishedByMode,
    ReviewMode,
    RiskLevel,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.terms import extract_unknown_horse_names, resolve_terms
from stable.services.race_grades import better_race_priority, normalize_race_grade, race_priority_for_grade


P0_OVERSEAS_RACES = [
    "凱旋門賞",
    "凯旋门赏",
    "ブリーダーズカップ",
    "育马者杯",
    "香港カップ",
    "香港マイル",
    "香港スプリント",
    "香港ヴァーズ",
    "香港杯",
    "香港一哩锦标",
    "香港短途锦标",
    "香港瓶",
    "エベレスト",
    "珠峰锦标赛",
    "ドバイワールドカップ",
    "ドバイシーマクラシック",
    "ドバイターフ",
    "迪拜世界杯",
    "迪拜司马经典赛",
    "迪拜草地大赛",
    "サウジカップ",
    "沙特杯",
]

HIGH_FOCUS_KEYWORDS = [
    "回避",
    "故障",
    "負傷",
    "引退",
    "種牡馬",
    "繁殖",
    "転厩",
    "騎手変更",
    "制裁",
    "審議",
    "裁定",
    "出走取消",
    "枠順",
    "追い切り",
    "調教",
    "登録",
    "結果",
]


def _configured_high_value_sources() -> set[tuple[str, str]]:
    rules = getattr(settings, "HIGH_VALUE_SOURCE_RULES", []) or []
    configured: set[tuple[str, str]] = set()
    for rule in rules:
        if not rule or ":" not in rule:
            continue
        site, mode = rule.split(":", 1)
        configured.add((site.strip(), mode.strip()))
    return configured


def is_high_value_source(article: NewsArticle) -> bool:
    return (article.source_site, article.source_mode) in _configured_high_value_sources()


def is_high_value_article(article: NewsArticle) -> bool:
    threshold = int(getattr(settings, "HIGH_VALUE_WARNING_SCORE_THRESHOLD", 90))
    return article.score_total >= threshold or is_high_value_source(article)


def automation_content_source() -> str:
    if not getattr(settings, "AUTO_REWRITE_ENABLED", False):
        return "base_translation"
    configured = (getattr(settings, "AUTO_PUBLISH_CONTENT_SOURCE", "base_translation") or "base_translation").strip().lower()
    return configured if configured in {"base_translation", "rewrite"} else "base_translation"


def prepare_base_translation_for_publish(article: NewsArticle) -> list[str]:
    manual_fields = set(article.manually_edited_fields or [])
    updated: list[str] = []
    if "title_zh" not in manual_fields and not article.title_zh and article.translated_title_zh:
        article.title_zh = article.translated_title_zh
        updated.append("title_zh")
    if "summary_zh" not in manual_fields and not article.summary_zh:
        article.summary_zh = article.translated_summary_zh or (article.translated_body_zh or "")[:160]
        updated.append("summary_zh")
    if "body_zh" not in manual_fields and not article.body_zh and article.translated_body_zh:
        article.body_zh = article.translated_body_zh
        updated.append("body_zh")
    if "push_summary_zh" not in manual_fields and not article.push_summary_zh:
        article.push_summary_zh = article.translated_summary_zh or (article.translated_body_zh or "")[:160]
        updated.append("push_summary_zh")
    if not article.base_translation_zh and article.translated_body_zh:
        article.base_translation_zh = article.translated_body_zh
        updated.append("base_translation_zh")
    if updated:
        article.save(update_fields=[*updated, "updated_at"])
    return updated


@dataclass
class AutomationDecision:
    review_mode: str
    risk_level: str
    automation_status: str
    score_total: int
    quality_score: int
    rewrite_confidence: int
    content_category: str
    decision_summary: str
    decision_reason: dict


def _source_text(article: NewsArticle) -> str:
    return "\n".join(
        part
        for part in [
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            article.translated_title_zh,
            article.translated_body_zh,
        ]
        if part
    )


def _public_text(article: NewsArticle) -> str:
    return "\n".join(
        part
        for part in [
            article.rewrite_title_zh,
            article.rewrite_summary_zh,
            article.rewrite_body_zh,
            article.title_zh,
            article.summary_zh,
            article.body_zh,
            article.translated_title_zh,
            article.translated_body_zh,
        ]
        if part
    )


def log_automation(
    article: NewsArticle,
    *,
    phase: str,
    result: str,
    reason: str = "",
    score: int | None = None,
    confidence: int | None = None,
    payload: dict | None = None,
    error_message: str = "",
) -> AutomationLog:
    return AutomationLog.objects.create(
        article=article,
        phase=phase,
        result=result,
        score=score,
        confidence=confidence,
        reason=reason,
        payload=payload or {},
        error_message=error_message,
    )


def classify_content_category(article: NewsArticle) -> str:
    text = _source_text(article)
    title = article.title_ja or ""
    if article.source_site == "jra" or "発表" in title or "お知らせ" in text:
        return ContentCategory.OFFICIAL
    quote_count = text.count("「") + text.count("『")
    if any(word in text for word in ["コメント", "インタビュー"]) or (
        quote_count >= 4 and any(word in text for word in ["騎手", "調教師", "師"])
    ):
        return ContentCategory.INTERVIEW
    if any(word in text for word in ["結果", "制した", "優勝", "着", "レース後"]):
        return ContentCategory.POST_RACE
    if any(word in text for word in ["出走", "枠順", "登録", "追い切り", "前哨戦", "展望"]):
        return ContentCategory.PRE_RACE
    if len(text) < 900:
        return ContentCategory.FLASH
    return ContentCategory.OTHER


def p0_horse_hits(article: NewsArticle) -> list[dict]:
    text = _source_text(article)
    hits: list[dict] = []
    seen: set[int] = set()
    for entry in TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE).exclude(target_zh=""):
        if entry.pk in seen:
            continue
        if any(term and term in text for term in entry.all_japanese_terms()):
            seen.add(entry.pk)
            hits.append({"source_ja": entry.source_ja, "target_zh": entry.target_zh, "priority": entry.priority})
    hits.sort(key=lambda item: (-item["priority"], item["source_ja"]))
    return hits


def race_priority(article: NewsArticle) -> dict:
    text = _source_text(article)
    race_terms = [term for term in resolve_terms(text, limit=60) if term.term_type == TermType.RACE]
    combined_races = " ".join([term.source_ja for term in race_terms] + [term.target_zh for term in race_terms] + [text])
    best = {"priority": "", "grade": "", "source": "", "term": ""}
    for term in race_terms:
        grade = normalize_race_grade(getattr(term, "race_grade", ""))
        priority = race_priority_for_grade(grade)
        if priority and better_race_priority(best["priority"], priority) == priority:
            best = {"priority": priority, "grade": grade, "source": "term", "term": term.source_ja}
    if best["priority"]:
        return best

    if any(name in combined_races for name in P0_OVERSEAS_RACES):
        return {"priority": "P0", "grade": "G1", "source": "overseas_p0", "term": ""}

    text_grade = normalize_race_grade(combined_races)
    text_priority = race_priority_for_grade(text_grade)
    if "障害" in combined_races and text_priority == "P0":
        text_priority = "P1"
    if text_priority:
        return {"priority": text_priority, "grade": text_grade, "source": "text", "term": ""}
    if "障害" in combined_races:
        return {"priority": "P1", "grade": "", "source": "text", "term": ""}
    return {"priority": "P2", "grade": "", "source": "default", "term": ""}


def _is_duplicate_secondary(article: NewsArticle) -> bool:
    if not article.title_ja:
        return False
    window_start = article.published_at - timedelta(hours=6)
    window_end = article.published_at + timedelta(hours=6)
    return (
        NewsArticle.objects.filter(
            title_ja=article.title_ja,
            published_at__gte=window_start,
            published_at__lte=window_end,
        )
        .exclude(pk=article.pk)
        .filter(Q(pk__lt=article.pk) | Q(first_seen_at__lt=article.first_seen_at))
        .exists()
    )


def _hard_rule_decision(article: NewsArticle, category: str) -> tuple[str | None, str, list[str], list[str]]:
    text = _source_text(article)
    body = article.body_ja_normalized or article.body_ja_raw
    reasons: list[str] = []
    checks: list[str] = []
    if _is_duplicate_secondary(article):
        return ReviewMode.IGNORED, RiskLevel.LOW, ["同标题同时间窗口内已有更早稿件"], checks
    if not body or len(body.strip()) < 80:
        return ReviewMode.IGNORED, RiskLevel.MEDIUM, ["正文过短或为空"], checks
    if len(text.replace("\ufffd", "")) < len(text) - 5:
        return ReviewMode.IGNORED, RiskLevel.HIGH, ["正文疑似乱码或结构损坏"], checks
    if any(word in text for word in ["広告", "PR", "ナビゲーション"]) and len(body) < 240:
        return ReviewMode.IGNORED, RiskLevel.MEDIUM, ["疑似广告或导航类页面"], checks

    quote_count = text.count("「") + text.count("『")
    if category == ContentCategory.INTERVIEW and (quote_count >= 8 or len(body) > 2400):
        checks.append("长采访或引语较多，后续作为 warning 记录")
    if article.translation_status != "translated":
        reasons.append("翻译尚未成功完成")
    if not article.translated_body_zh:
        reasons.append("缺少基准中文翻译")
    if extract_unknown_horse_names(article.title_ja, body, limit=3) and not p0_horse_hits(article):
        checks.append("存在未收录疑似马名，后续作为 warning 记录")
    if reasons:
        return ReviewMode.MANUAL, RiskLevel.MEDIUM, reasons, checks
    return None, RiskLevel.LOW, reasons, checks


def score_article_for_automation(article: NewsArticle) -> AutomationDecision:
    text = _source_text(article)
    category = classify_content_category(article)
    hard_mode, hard_risk, hard_reasons, checks = _hard_rule_decision(article, category)
    horse_hits = p0_horse_hits(article)
    race_signal = race_priority(article)
    priority = race_signal["priority"]
    high_focus_hits = [keyword for keyword in HIGH_FOCUS_KEYWORDS if keyword in text]
    source_score = 15 if article.source_site == "jra" else 10
    high_value_source = is_high_value_source(article)
    value_score = 0
    if horse_hits:
        value_score += 25
    if priority == "P0":
        value_score += 20
    elif priority == "P1":
        value_score += 12
    elif priority == "P2":
        value_score += 6
    if high_focus_hits:
        value_score += 10
    if category in {ContentCategory.FLASH, ContentCategory.OFFICIAL, ContentCategory.POST_RACE, ContentCategory.PRE_RACE}:
        value_score += 8
    age_hours = max(0, int((timezone.now() - article.published_at).total_seconds() // 3600))
    recency_score = 10 if age_hours <= 12 else 6 if age_hours <= 48 else 2
    body = article.body_ja_normalized or article.body_ja_raw
    structure_score = 10 if len(body) >= 240 else 5
    quality_score = min(100, 55 + structure_score + min(20, len(article.translated_body_zh or "") // 120))
    score_total = min(100, source_score + value_score + recency_score + structure_score + min(15, quality_score // 8))

    decision_reason = {
        "hard_rules": hard_reasons,
        "checks": checks,
        "signals": {
            "category": category,
            "high_value_source": high_value_source,
            "content_source": automation_content_source(),
            "p0_horse_hits": horse_hits[:8],
            "race_priority": priority,
            "race_grade": race_signal.get("grade", ""),
            "race_grade_source": race_signal.get("source", ""),
            "race_term": race_signal.get("term", ""),
            "high_focus_hits": high_focus_hits,
            "age_hours": age_hours,
        },
        "scores": {
            "source": source_score,
            "value": value_score,
            "recency": recency_score,
            "structure": structure_score,
            "quality": quality_score,
            "total": score_total,
        },
    }

    if hard_mode == ReviewMode.IGNORED:
        return AutomationDecision(
            review_mode=ReviewMode.IGNORED,
            risk_level=hard_risk,
            automation_status=AutomationStatus.IGNORED,
            score_total=score_total,
            quality_score=quality_score,
            rewrite_confidence=0,
            content_category=category,
            decision_summary=f"忽略：{hard_reasons[0]}",
            decision_reason=decision_reason,
        )
    if hard_mode == ReviewMode.MANUAL:
        return AutomationDecision(
            review_mode=ReviewMode.MANUAL,
            risk_level=hard_risk,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            score_total=score_total,
            quality_score=quality_score,
            rewrite_confidence=0,
            content_category=category,
            decision_summary=f"转人工：{hard_reasons[0]}",
            decision_reason=decision_reason,
        )

    auto_threshold = int(getattr(settings, "AUTO_REVIEW_THRESHOLD", 75))
    manual_threshold = int(getattr(settings, "MANUAL_REVIEW_THRESHOLD", 45))
    if high_value_source:
        score_total = max(score_total, auto_threshold)
        decision_reason["scores"]["total"] = score_total
        decision_reason["scores"]["high_value_source_override"] = True
    if score_total >= auto_threshold:
        mode = ReviewMode.AUTO
        status = AutomationStatus.REWRITE_READY
        risk = RiskLevel.LOW
        summary = f"自动候选：总分 {score_total}，命中 {priority} 赛事/重点信号"
    elif score_total >= manual_threshold:
        mode = ReviewMode.MANUAL
        status = AutomationStatus.MANUAL_REVIEW_REQUIRED
        risk = RiskLevel.MEDIUM
        summary = f"转人工：总分 {score_total}，价值或确定性不足"
    else:
        mode = ReviewMode.IGNORED
        status = AutomationStatus.IGNORED
        risk = RiskLevel.LOW
        summary = f"忽略：总分 {score_total}，发布价值不足"

    return AutomationDecision(
        review_mode=mode,
        risk_level=risk,
        automation_status=status,
        score_total=score_total,
        quality_score=quality_score,
        rewrite_confidence=0,
        content_category=category,
        decision_summary=summary,
        decision_reason=decision_reason,
    )


def apply_score_decision(article: NewsArticle, decision: AutomationDecision) -> None:
    article.review_mode = decision.review_mode
    article.risk_level = decision.risk_level
    article.automation_status = decision.automation_status
    article.score_total = decision.score_total
    article.quality_score = decision.quality_score
    article.rewrite_confidence = decision.rewrite_confidence
    article.content_category = decision.content_category
    article.decision_summary = decision.decision_summary
    article.decision_reason = decision.decision_reason
    article.base_translation_zh = article.base_translation_zh or article.translated_body_zh
    article.automation_error_message = ""
    if decision.review_mode == ReviewMode.MANUAL:
        article.workflow_status = WorkflowStatus.PENDING_REVIEW
    elif decision.review_mode == ReviewMode.IGNORED:
        article.workflow_status = WorkflowStatus.IGNORED
        article.ignored_at = article.ignored_at or timezone.now()
    article.save()
    log_automation(
        article,
        phase=AutomationPhase.SCORE,
        result=AutomationResult.SUCCESS,
        score=decision.score_total,
        confidence=decision.rewrite_confidence,
        reason=decision.decision_summary,
        payload=asdict(decision),
    )


def mark_automation_failed(article: NewsArticle, *, phase: str, error: Exception | str) -> None:
    message = str(error)
    article.automation_status = AutomationStatus.FAILED
    article.review_mode = ReviewMode.MANUAL
    article.risk_level = RiskLevel.HIGH
    article.workflow_status = WorkflowStatus.PENDING_REVIEW
    article.automation_error_message = message
    article.save(
        update_fields=[
            "automation_status",
            "review_mode",
            "risk_level",
            "workflow_status",
            "automation_error_message",
            "updated_at",
        ]
    )
    log_automation(
        article,
        phase=phase,
        result=AutomationResult.FAILED,
        reason="自动化处理失败，转人工审核",
        error_message=message,
    )


def mark_publish_ready(article: NewsArticle, *, reason: str = "改写稿通过一致性校验") -> None:
    article.automation_status = AutomationStatus.PUBLISH_READY
    article.review_mode = ReviewMode.AUTO
    article.risk_level = RiskLevel.LOW
    article.decision_summary = reason
    article.automation_error_message = ""
    article.save(
        update_fields=[
            "automation_status",
            "review_mode",
            "risk_level",
            "decision_summary",
            "automation_error_message",
            "updated_at",
        ]
    )


def is_ready_for_auto_publish(article: NewsArticle) -> bool:
    if article.review_mode != ReviewMode.AUTO:
        return False
    if article.automation_status != AutomationStatus.PUBLISH_READY:
        return False
    if article.workflow_status in {WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED}:
        return False
    if not (article.effective_title and article.effective_summary and article.effective_body and article.source_url):
        return False
    if getattr(settings, "AUTO_PUBLISH_REQUIRE_COVER", False) and not article.cover_image_url:
        return False
    return True


def publish_article_automatically(article: NewsArticle) -> None:
    article.workflow_status = WorkflowStatus.PUBLISHED
    article.automation_status = AutomationStatus.AUTO_PUBLISHED
    article.published_by_mode = PublishedByMode.AUTO
    article.auto_publish_at = timezone.now()
    article.published_to_web_at = article.published_to_web_at or article.auto_publish_at
    article.save(
        update_fields=[
            "workflow_status",
            "automation_status",
            "published_by_mode",
            "auto_publish_at",
            "published_to_web_at",
            "updated_at",
        ]
    )
    log_automation(
        article,
        phase=AutomationPhase.PUBLISH,
        result=AutomationResult.SUCCESS,
        score=article.score_total,
        confidence=article.rewrite_confidence,
        reason="自动批量发布",
        payload={"article_id": article.id, "title": article.effective_title},
    )


def important_manual_notification_payload(article: NewsArticle) -> dict | None:
    reason = article.decision_reason or {}
    signals = reason.get("signals", {})
    if article.review_mode != ReviewMode.MANUAL:
        return None
    if not (signals.get("p0_horse_hits") or signals.get("race_priority") in {"P0", "P1"} or signals.get("high_focus_hits")):
        return None
    return {
        "type": NotificationType.IMPORTANT_MANUAL,
        "article_id": article.id,
        "title": article.effective_title,
        "decision_summary": article.decision_summary,
        "score_total": article.score_total,
        "source_url": article.source_url,
    }
