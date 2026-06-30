from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from stable.models import (
    ArticleTranslationStatus,
    ExternalHorseAlias,
    NewsArticle,
    NewsSource,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RacingRegion,
    ReviewMode,
    SourceLanguage,
    TaskStatus,
    TermCandidate,
    TermCandidateStatus,
    TermEntry,
    WorkflowStatus,
)

PRODUCTION_REGIONS = [
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
]


@dataclass(frozen=True)
class AutoPublishPolicyDecision:
    allowed: bool
    reason: str
    region: str
    source_key: str
    per_run_limit: int | None = None
    daily_limit: int | None = None
    term_candidate_backlog: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def region_label(region: str) -> str:
    labels = dict(RacingRegion.choices)
    return labels.get(region, region or "未设置")


def _setting_list(name: str) -> set[str]:
    value = getattr(settings, name, [])
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    return {str(item).strip() for item in value if str(item).strip()}


def _setting_int_map(name: str) -> dict[str, int]:
    value = getattr(settings, name, {})
    if isinstance(value, dict):
        items = value.items()
    else:
        raw = (value or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
            for item in raw.split(","):
                key, _, number = item.partition(":")
                if key.strip() and number.strip():
                    parsed[key.strip()] = number.strip()
        items = parsed.items() if isinstance(parsed, dict) else []
    result: dict[str, int] = {}
    for key, number in items:
        try:
            result[str(key).strip()] = max(0, int(number))
        except (TypeError, ValueError):
            continue
    return result


def article_source_key(article: NewsArticle) -> str:
    return f"{article.source_site}:{article.source_mode}"


def _term_candidate_backlog(article: NewsArticle) -> int:
    return (
        TermCandidate.objects.filter(
            status=TermCandidateStatus.PENDING,
            source_language=article.source_language or SourceLanguage.JAPANESE,
            evidence__article__racing_region=article.racing_region,
        )
        .distinct()
        .count()
    )


def auto_publish_policy_for_article(article: NewsArticle) -> AutoPublishPolicyDecision:
    region = article.racing_region or RacingRegion.JAPAN
    source_key = article_source_key(article)
    per_run_limits = _setting_int_map("MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS")
    daily_limits = _setting_int_map("MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS")
    per_run_limit = per_run_limits.get(region)
    daily_limit = daily_limits.get(region)
    if region == RacingRegion.JAPAN:
        return AutoPublishPolicyDecision(True, "japan_default", region, source_key, per_run_limit, daily_limit)

    allowed_regions = _setting_list("MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS")
    allowed_sources = _setting_list("MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES")
    if region not in allowed_regions:
        return AutoPublishPolicyDecision(False, "region_not_allowed", region, source_key, per_run_limit, daily_limit)
    if allowed_sources and source_key not in allowed_sources and str(article.source_config_id or "") not in allowed_sources:
        return AutoPublishPolicyDecision(False, "source_not_allowed", region, source_key, per_run_limit, daily_limit)

    backlog = _term_candidate_backlog(article)
    threshold = max(0, int(getattr(settings, "MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD", 50)))
    if threshold and backlog >= threshold:
        return AutoPublishPolicyDecision(False, "term_candidate_backlog", region, source_key, per_run_limit, daily_limit, backlog)
    return AutoPublishPolicyDecision(True, "allowed", region, source_key, per_run_limit, daily_limit, backlog)


def auto_publish_count_today(region: str, *, now=None) -> int:
    now = now or timezone.now()
    today = timezone.localdate(now)
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    return NewsArticle.objects.filter(
        racing_region=region,
        published_by_mode="auto",
        auto_publish_at__gte=today_start,
    ).count()


def _count_by(queryset, field: str) -> dict[str, int]:
    return {row[field] or "": row["count"] for row in queryset.values(field).annotate(count=Count("id"))}


def summarize_multiregion_news_production(*, now=None) -> dict[str, Any]:
    now = now or timezone.now()
    today = timezone.localdate(now)
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    recent_start = now - timedelta(hours=24)
    regions: dict[str, dict[str, Any]] = {}

    for region in PRODUCTION_REGIONS:
        sources = NewsSource.objects.filter(racing_region=region, deleted_at__isnull=True)
        enabled_sources = sources.filter(enabled=True)
        articles = NewsArticle.objects.filter(racing_region=region)
        active_articles = articles.exclude(
            workflow_status__in=[
                WorkflowStatus.PUBLISHED,
                WorkflowStatus.WITHDRAWN,
                WorkflowStatus.IGNORED,
                WorkflowStatus.DUPLICATE,
            ]
        )
        recent_articles = articles.filter(first_seen_at__gte=recent_start)
        qq_recent = QQPushDelivery.objects.filter(article__racing_region=region, created_at__gte=recent_start)
        term_candidates = TermCandidate.objects.filter(evidence__article__racing_region=region).distinct()
        term_entries = TermEntry.objects.filter(
            Q(racing_region="") | Q(racing_region=region),
            source_language__in=[SourceLanguage.JAPANESE, SourceLanguage.ENGLISH, SourceLanguage.CHINESE_TRADITIONAL],
        )
        external_aliases = ExternalHorseAlias.objects.filter(racing_region=region)
        regions[region] = {
            "label": region_label(region),
            "sources": {
                "total": sources.count(),
                "enabled": enabled_sources.count(),
                "latest_crawl_at": enabled_sources.order_by("-last_crawl_at").values_list("last_crawl_at", flat=True).first(),
                "crawl_statuses": _count_by(sources, "last_crawl_status"),
                "success_no_new": sources.filter(last_crawl_status=TaskStatus.SUCCESS, last_crawl_message__icontains="新增 0").count(),
                "failed": sources.filter(last_crawl_status=TaskStatus.FAILED).count(),
            },
            "articles": {
                "total": articles.count(),
                "today_new": articles.filter(first_seen_at__gte=today_start).count(),
                "recent_24h": recent_articles.count(),
                "workflow": _count_by(active_articles, "workflow_status"),
                "translation": _count_by(active_articles, "translation_status"),
                "automation": _count_by(active_articles, "automation_status"),
                "today_auto_published": articles.filter(
                    workflow_status=WorkflowStatus.PUBLISHED,
                    published_by_mode="auto",
                    auto_publish_at__gte=today_start,
                ).count(),
                "today_manual_published": articles.filter(
                    workflow_status=WorkflowStatus.PUBLISHED,
                    published_by_mode="manual",
                    published_to_web_at__gte=today_start,
                ).count(),
                "today_public": articles.filter(
                    workflow_status=WorkflowStatus.PUBLISHED,
                    published_to_web_at__gte=today_start,
                ).count(),
                "public_total": articles.filter(workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False).count(),
            },
            "qq_delivery": _count_by(qq_recent, "status"),
            "term_operations": {
                "formal_terms_by_language": _count_by(term_entries, "source_language"),
                "external_aliases": external_aliases.count(),
                "external_aliases_by_language": _count_by(external_aliases, "source_language"),
                "pending_candidates": term_candidates.filter(status=TermCandidateStatus.PENDING).count(),
                "pending_candidates_by_language": _count_by(term_candidates.filter(status=TermCandidateStatus.PENDING), "source_language"),
            },
        }
    return {
        "generated_at": now.isoformat(),
        "windows": {"today": str(today), "recent_hours": 24},
        "regions": regions,
        "settings": {
            "news_source_poll_enabled": bool(getattr(settings, "NEWS_SOURCE_POLL_ENABLED", False)),
            "news_source_poll_max_sources": int(getattr(settings, "NEWS_SOURCE_POLL_MAX_SOURCES", 3)),
            "multiregion_auto_publish_allowed_regions": sorted(_setting_list("MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS")),
            "multiregion_auto_publish_allowed_sources": sorted(_setting_list("MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES")),
        },
    }


def region_production_rows(*, selected_region: str = "", now=None) -> list[dict[str, Any]]:
    summary = summarize_multiregion_news_production(now=now)
    regions = [selected_region] if selected_region else PRODUCTION_REGIONS
    rows: list[dict[str, Any]] = []
    for region in regions:
        if region not in summary["regions"]:
            continue
        item = summary["regions"][region]
        articles = item["articles"]
        qq = item["qq_delivery"]
        rows.append(
            {
                "region": region,
                "label": item["label"],
                "enabled_sources": item["sources"]["enabled"],
                "today_new": articles["today_new"],
                "pending_translation": articles["workflow"].get(WorkflowStatus.PENDING_TRANSLATION, 0),
                "translation_failed": articles["translation"].get(ArticleTranslationStatus.FAILED, 0),
                "pending_review": articles["workflow"].get(WorkflowStatus.PENDING_REVIEW, 0),
                "auto_published": articles["today_auto_published"],
                "manual_published": articles["today_manual_published"],
                "public": articles["today_public"],
                "qq_sent": qq.get(QQPushDeliveryStatus.SENT, 0),
                "qq_pending": qq.get(QQPushDeliveryStatus.PENDING, 0) + qq.get(QQPushDeliveryStatus.RETRYING, 0),
                "qq_skipped": qq.get(QQPushDeliveryStatus.SKIPPED, 0),
                "qq_failed": qq.get(QQPushDeliveryStatus.FAILED, 0),
                "pending_term_candidates": item["term_operations"]["pending_candidates"],
            }
        )
    return rows
