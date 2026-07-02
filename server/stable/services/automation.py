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
    ArticleTranslationStatus,
    ContentCategory,
    NewsArticle,
    NotificationType,
    PublishedByMode,
    ReviewMode,
    RiskLevel,
    SourceLanguage,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.terms import (
    extract_unknown_horse_names,
    resolve_terms_for_language,
    source_term_matches_text,
    source_terms_by_entry,
)
from stable.services.multiregion import auto_publish_policy_for_article
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
P0_OVERSEAS_RACES_BY_LANGUAGE = {
    SourceLanguage.ENGLISH: [
        "prix de l'arc de triomphe",
        "arc de triomphe",
        "breeders' cup",
        "hong kong cup",
        "hong kong mile",
        "hong kong sprint",
        "hong kong vase",
        "the everest",
        "dubai world cup",
        "dubai sheema classic",
        "dubai turf",
        "saudi cup",
        "kentucky derby",
    ],
    SourceLanguage.CHINESE_TRADITIONAL: [
        "凱旋門賞",
        "育馬者盃",
        "香港盃",
        "香港一哩錦標",
        "香港短途錦標",
        "香港瓶",
        "杜拜世界盃",
        "杜拜司馬經典賽",
        "杜拜草地大賽",
        "沙特盃",
    ],
}

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
HIGH_FOCUS_KEYWORDS_BY_LANGUAGE = {
    SourceLanguage.JAPANESE: HIGH_FOCUS_KEYWORDS,
    SourceLanguage.ENGLISH: [
        "withdrawn",
        "withdrawal",
        "injury",
        "injured",
        "retired",
        "retirement",
        "stallion",
        "breeding",
        "transferred",
        "jockey change",
        "stewards",
        "suspension",
        "disciplinary",
        "scratched",
        "scratch",
        "draw",
        "barrier",
        "entries",
        "entry",
        "declarations",
        "workout",
        "gallop",
        "result",
        "results",
    ],
    SourceLanguage.CHINESE_TRADITIONAL: [
        "退出",
        "受傷",
        "退役",
        "種馬",
        "繁殖",
        "轉廄",
        "更換騎師",
        "制裁",
        "聆訊",
        "取消出賽",
        "排位",
        "檔位",
        "報名",
        "試閘",
        "晨操",
        "賽果",
    ],
}

OFFICIAL_KEYWORDS_BY_LANGUAGE = {
    SourceLanguage.JAPANESE: ["発表", "お知らせ"],
    SourceLanguage.ENGLISH: ["official", "notice", "statement", "announced", "announcement", "stewards"],
    SourceLanguage.CHINESE_TRADITIONAL: ["公布", "公告", "通知", "宣布", "競賽董事"],
}
INTERVIEW_KEYWORDS_BY_LANGUAGE = {
    SourceLanguage.JAPANESE: ["コメント", "インタビュー"],
    SourceLanguage.ENGLISH: ["interview", "said", "quotes", "commented"],
    SourceLanguage.CHINESE_TRADITIONAL: ["訪問", "專訪", "表示", "稱"],
}
POST_RACE_KEYWORDS_BY_LANGUAGE = {
    SourceLanguage.JAPANESE: ["結果", "制した", "優勝", "着", "レース後"],
    SourceLanguage.ENGLISH: ["result", "results", "won", "winner", "victory", "finished", "post-race"],
    SourceLanguage.CHINESE_TRADITIONAL: ["賽果", "勝出", "奪冠", "第", "賽後"],
}
PRE_RACE_KEYWORDS_BY_LANGUAGE = {
    SourceLanguage.JAPANESE: ["出走", "枠順", "登録", "追い切り", "前哨戦", "展望"],
    SourceLanguage.ENGLISH: ["preview", "entries", "entry", "declarations", "declared", "draw", "barrier", "racecard"],
    SourceLanguage.CHINESE_TRADITIONAL: ["出賽", "排位", "檔位", "報名", "試閘", "賽前", "展望"],
}


def _language_match_text(text: str, source_language: str) -> str:
    if source_language == SourceLanguage.ENGLISH:
        return text.casefold()
    return text


def _keywords_for_language(mapping: dict[str, list[str]], source_language: str) -> list[str]:
    return mapping.get(source_language) or mapping.get(SourceLanguage.JAPANESE, [])


def _contains_language_keyword(text: str, mapping: dict[str, list[str]], source_language: str) -> bool:
    match_text = _language_match_text(text, source_language)
    return any(keyword in match_text for keyword in _keywords_for_language(mapping, source_language))


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


@dataclass(frozen=True)
class RankedRevivalResult:
    article_id: int
    revived: bool
    action: str
    reason: str = ""


TERMINAL_RANKED_REVIVAL_STATUSES = {
    WorkflowStatus.PUBLISHED,
    WorkflowStatus.WITHDRAWN,
    WorkflowStatus.REJECTED,
    WorkflowStatus.DUPLICATE,
}
REVIVABLE_IGNORED_REASON_KEYWORDS = ("分数低", "发布价值不足", "价值或确定性不足")


def _has_blocker(article: NewsArticle) -> bool:
    return any((issue or {}).get("severity") == "blocker" for issue in (article.gate_issues or []))


def _ranked_revival_payload(article: NewsArticle, *, now, action: str) -> dict:
    previous = article.decision_reason.get("ranked_revival", {}) if isinstance(article.decision_reason, dict) else {}
    payload = {
        "revived_at": now.isoformat(),
        "source_site": article.source_site,
        "source_mode": article.source_mode,
        "previous_workflow_status": article.workflow_status,
        "previous_automation_status": article.automation_status,
        "previous_translation_status": article.translation_status,
        "action": action,
    }
    if action == "translation_retry":
        payload["translation_retry_requested_at"] = now.isoformat()
    if previous:
        payload["previous_revival"] = previous
    return payload


def _translation_incomplete(article: NewsArticle) -> bool:
    if article.translation_status != ArticleTranslationStatus.TRANSLATED:
        return True
    return not (article.translated_title_zh and article.translated_body_zh)


def _ignored_reason_is_revivable(article: NewsArticle) -> bool:
    reason = article.decision_reason if isinstance(article.decision_reason, dict) else {}
    hard_rules = [str(item) for item in reason.get("hard_rules") or []]
    summary = str(reason.get("summary") or article.decision_summary or "")
    text = " ".join([*hard_rules, summary])
    if any(keyword in text for keyword in REVIVABLE_IGNORED_REASON_KEYWORDS):
        return True
    return not hard_rules and not summary


def revive_article_after_ranked_source_elevation(article: NewsArticle, *, now=None) -> RankedRevivalResult:
    now = now or timezone.now()
    if article.workflow_status in TERMINAL_RANKED_REVIVAL_STATUSES:
        return RankedRevivalResult(article_id=article.id, revived=False, action="blocked", reason="terminal_status")
    if _has_blocker(article):
        return RankedRevivalResult(article_id=article.id, revived=False, action="blocked", reason="hard_gate_blocker")

    reason = dict(article.decision_reason or {})
    existing_revival = reason.get("ranked_revival") or {}
    if (
        existing_revival.get("action") == "translation_retry"
        and existing_revival.get("translation_retry_requested_at")
        and article.translation_status in {ArticleTranslationStatus.PENDING, ArticleTranslationStatus.TRANSLATING}
        and article.workflow_status == WorkflowStatus.PENDING_TRANSLATION
    ):
        return RankedRevivalResult(
            article_id=article.id,
            revived=False,
            action="already_retrying_translation",
            reason="translation_retry_in_progress",
        )

    if _translation_incomplete(article) or article.workflow_status == WorkflowStatus.TRANSLATION_FAILED:
        action = "translation_retry"
        reason["ranked_revival"] = _ranked_revival_payload(article, now=now, action=action)
        article.ranked_revived_at = now
        article.workflow_status = WorkflowStatus.PENDING_TRANSLATION
        article.translation_status = ArticleTranslationStatus.PENDING
        article.automation_status = AutomationStatus.PENDING
        article.review_mode = ""
        article.decision_reason = reason
        article.save(
            update_fields=[
                "ranked_revived_at",
                "workflow_status",
                "translation_status",
                "automation_status",
                "review_mode",
                "decision_reason",
                "updated_at",
            ]
        )
        log_automation(
            article,
            phase=AutomationPhase.SCORE,
            result=AutomationResult.SUCCESS,
            reason="榜单唤醒：重新派发翻译",
            payload={"ranked_revival": reason["ranked_revival"]},
        )
        return RankedRevivalResult(article_id=article.id, revived=True, action=action)

    if article.workflow_status not in {WorkflowStatus.IGNORED, WorkflowStatus.PENDING_REVIEW, WorkflowStatus.PENDING_EDIT}:
        return RankedRevivalResult(article_id=article.id, revived=False, action="blocked", reason="status_not_revivable")
    if article.workflow_status == WorkflowStatus.IGNORED and not _ignored_reason_is_revivable(article):
        return RankedRevivalResult(article_id=article.id, revived=False, action="blocked", reason="hard_rule_ignored")

    action = "rescore"
    reason["ranked_revival"] = _ranked_revival_payload(article, now=now, action=action)
    article.ranked_revived_at = now
    article.workflow_status = WorkflowStatus.PENDING_EDIT
    article.review_mode = ReviewMode.AUTO
    article.automation_status = AutomationStatus.PENDING
    article.automation_error_message = ""
    article.decision_reason = reason
    article.save(
        update_fields=[
            "ranked_revived_at",
            "workflow_status",
            "review_mode",
            "automation_status",
            "automation_error_message",
            "decision_reason",
            "updated_at",
        ]
    )
    log_automation(
        article,
        phase=AutomationPhase.SCORE,
        result=AutomationResult.SUCCESS,
        reason="榜单唤醒：重新评分",
        payload={"ranked_revival": reason["ranked_revival"]},
    )
    return RankedRevivalResult(article_id=article.id, revived=True, action=action)


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
    source_language = article.source_language or SourceLanguage.JAPANESE
    if article.source_site == "jra" or _contains_language_keyword(f"{title}\n{text}", OFFICIAL_KEYWORDS_BY_LANGUAGE, source_language):
        return ContentCategory.OFFICIAL
    quote_count = text.count("「") + text.count("『")
    if _contains_language_keyword(text, INTERVIEW_KEYWORDS_BY_LANGUAGE, source_language) or (
        quote_count >= 4 and any(word in text for word in ["騎手", "調教師", "師"])
    ):
        return ContentCategory.INTERVIEW
    if _contains_language_keyword(text, POST_RACE_KEYWORDS_BY_LANGUAGE, source_language):
        return ContentCategory.POST_RACE
    if _contains_language_keyword(text, PRE_RACE_KEYWORDS_BY_LANGUAGE, source_language):
        return ContentCategory.PRE_RACE
    if len(text) < 900:
        return ContentCategory.FLASH
    return ContentCategory.OTHER


def p0_horse_hits(article: NewsArticle) -> list[dict]:
    text = _source_text(article)
    hits: list[dict] = []
    seen: set[int] = set()
    source_language = article.source_language or SourceLanguage.JAPANESE
    entries = list(TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE).exclude(target_zh=""))
    terms_by_entry = source_terms_by_entry(entries, source_language)
    for entry in entries:
        if entry.pk in seen:
            continue
        if any(source_term_matches_text(text, term, source_language) for term in terms_by_entry.get(entry.pk, [])):
            seen.add(entry.pk)
            hits.append({"source_ja": entry.source_ja, "target_zh": entry.target_zh, "priority": entry.priority})
    hits.sort(key=lambda item: (-item["priority"], item["source_ja"]))
    return hits


def race_priority(article: NewsArticle) -> dict:
    text = _source_text(article)
    source_language = article.source_language or SourceLanguage.JAPANESE
    race_terms = [
        term
        for term in resolve_terms_for_language(text, source_language, limit=60)
        if term.term_type == TermType.RACE
    ]
    combined_races = " ".join([term.source_ja for term in race_terms] + [term.target_zh for term in race_terms] + [text])
    best = {"priority": "", "grade": "", "source": "", "term": ""}
    for term in race_terms:
        grade = normalize_race_grade(getattr(term, "race_grade", ""))
        priority = race_priority_for_grade(grade)
        if priority and better_race_priority(best["priority"], priority) == priority:
            best = {"priority": priority, "grade": grade, "source": "term", "term": term.source_ja}
    if best["priority"]:
        return best

    language_match_text = _language_match_text(combined_races, source_language)
    language_p0_races = P0_OVERSEAS_RACES + _keywords_for_language(P0_OVERSEAS_RACES_BY_LANGUAGE, source_language)
    if any(_language_match_text(name, source_language) in language_match_text for name in language_p0_races):
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
    if (
        (article.source_language or SourceLanguage.JAPANESE) == SourceLanguage.JAPANESE
        and extract_unknown_horse_names(article.title_ja, body, limit=3)
        and not p0_horse_hits(article)
    ):
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
    source_language = article.source_language or SourceLanguage.JAPANESE
    match_text = _language_match_text(text, source_language)
    high_focus_hits = [
        keyword
        for keyword in _keywords_for_language(HIGH_FOCUS_KEYWORDS_BY_LANGUAGE, source_language)
        if _language_match_text(keyword, source_language) in match_text
    ]
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
    publish_policy = auto_publish_policy_for_article(article)
    decision_reason["publish_policy"] = publish_policy.as_dict()

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

    if article.racing_region != "japan" and not publish_policy.allowed:
        return AutomationDecision(
            review_mode=ReviewMode.MANUAL,
            risk_level=RiskLevel.MEDIUM,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            score_total=score_total,
            quality_score=quality_score,
            rewrite_confidence=0,
            content_category=category,
            decision_summary=f"转人工：多地区自动发布策略未放行（{publish_policy.reason}）",
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
    if not auto_publish_policy_for_article(article).allowed:
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
    if (article.decision_reason or {}).get("disable_auto_qq"):
        return

    from stable.services.qq_auto_push import enqueue_qq_auto_push_for_article

    enqueue_qq_auto_push_for_article(article.id)


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
