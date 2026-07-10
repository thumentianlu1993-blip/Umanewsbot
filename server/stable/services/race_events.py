from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleRaceLinkType,
    ContentCategory,
    NewsArticle,
    RaceEvent,
    RaceEventCandidateStatus,
    RaceEventDataCandidate,
    RaceEventDataQuality,
    RaceEventHistoryWinner,
    RaceEventModule,
    RaceEventResult,
    RaceEventRunner,
    RaceRunnerStatus,
    TaskExecutionLog,
    TaskStatus,
    WorkflowStatus,
)
from stable.services.operations import log_operation
from stable.services.terms import source_term_matches_text


User = get_user_model()

DYNAMIC_RUNNER_FIELDS = {"odds_value", "popularity", "running_status"}
BASIC_EVENT_FIELDS = {
    "original_name",
    "chinese_name",
    "country_region",
    "racecourse",
    "grade_text",
    "normalized_grade",
    "surface",
    "distance_text",
    "eligibility_text",
    "race_datetime",
    "timezone_name",
    "local_date",
    "local_start_time",
    "priority",
    "status",
    "visibility_status",
    "data_quality_status",
    "is_featured",
    "source_refs",
}

HORSE_COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")


@dataclass
class RaceArticleMatch:
    article: NewsArticle
    status: str
    link_type: str
    confidence: int
    matched_text: str
    reason: str


def _task_log(task_name: str, status: str, payload: dict | None = None, detail: str = "") -> TaskExecutionLog:
    now = timezone.now()
    return TaskExecutionLog.objects.create(
        task_name=task_name,
        status=status,
        payload=payload or {},
        detail=detail,
        started_at=now,
        finished_at=now,
    )


def _locked(event: RaceEvent, key: str) -> bool:
    flags = event.manual_lock_flags or {}
    return bool(flags.get(key))


def _diff_values(current: Any, candidate: Any) -> dict:
    if current == candidate:
        return {"changed": False, "current": current, "candidate": candidate}
    return {"changed": True, "current": current, "candidate": candidate}


def build_candidate_diff(event: RaceEvent, module: str, payload: dict) -> dict:
    if module == RaceEventModule.BASIC:
        return {
            field: _diff_values(getattr(event, field, None), payload.get(field))
            for field in BASIC_EVENT_FIELDS
            if field in payload
        }
    current_counts = {
        RaceEventModule.HISTORY_WINNERS: event.history_winners.count(),
        RaceEventModule.RUNNERS: event.runners.count(),
        RaceEventModule.RESULTS: event.results.count(),
        RaceEventModule.NEWS_LINKS: event.article_links.count(),
    }
    candidate_count = len(payload) if isinstance(payload, list) else len(payload.get("items", []))
    return {
        "count": {
            "changed": current_counts.get(module, 0) != candidate_count,
            "current": current_counts.get(module, 0),
            "candidate": candidate_count,
        }
    }


def save_data_candidate(
    *,
    event: RaceEvent,
    module: str,
    source_name: str,
    candidate_payload: dict,
    source_url: str = "",
    raw_payload: dict | None = None,
    confidence: int = 0,
) -> RaceEventDataCandidate:
    candidate = RaceEventDataCandidate.objects.create(
        event=event,
        module=module,
        source_name=source_name,
        source_url=source_url,
        confidence=max(0, min(int(confidence or 0), 100)),
        candidate_payload=candidate_payload,
        diff_payload=build_candidate_diff(event, module, candidate_payload),
        raw_payload=raw_payload or {},
    )
    _task_log(
        "race_event_candidate_saved",
        TaskStatus.SUCCESS,
        payload={"event_id": event.pk, "candidate_id": candidate.pk, "module": module, "source_name": source_name},
        detail=f"赛事候选资料已保存：{event} {module} {source_name}",
    )
    return candidate


def _set_unlocked_event_fields(event: RaceEvent, payload: dict) -> list[str]:
    updated_fields: list[str] = []
    for field in BASIC_EVENT_FIELDS:
        if field not in payload or _locked(event, field) or _locked(event, RaceEventModule.BASIC):
            continue
        value = payload[field]
        if getattr(event, field, None) != value:
            setattr(event, field, value)
            updated_fields.append(field)
    return updated_fields


def _clean_race_horse_name(value: Any) -> str:
    return HORSE_COUNTRY_SUFFIX_RE.sub("", str(value or "").strip()).strip()


def _replace_runners(event: RaceEvent, items: Iterable[dict]) -> int:
    if _locked(event, RaceEventModule.RUNNERS):
        return 0
    event.runners.all().delete()
    created = []
    for index, item in enumerate(items, start=1):
        created.append(
            RaceEventRunner(
                event=event,
                sort_order=int(item.get("sort_order") or index),
                horse_number=str(item.get("horse_number") or ""),
                barrier=str(item.get("barrier") or ""),
                horse_name=_clean_race_horse_name(item.get("horse_name")),
                jockey_name=str(item.get("jockey_name") or ""),
                trainer_name=str(item.get("trainer_name") or ""),
                carried_weight=str(item.get("carried_weight") or ""),
                odds_value=str(item.get("odds_value") or ""),
                popularity=str(item.get("popularity") or ""),
                running_status=str(item.get("running_status") or RaceRunnerStatus.DECLARED),
                source_refs=item.get("source_refs") or {},
                raw_payload=item,
            )
        )
    RaceEventRunner.objects.bulk_create([item for item in created if item.horse_name])
    return len(created)


def _replace_results(event: RaceEvent, items: Iterable[dict]) -> int:
    if _locked(event, RaceEventModule.RESULTS):
        return 0
    event.results.all().delete()
    created = []
    for item in items:
        if not item.get("finish_position") or not item.get("horse_name"):
            continue
        created.append(
            RaceEventResult(
                event=event,
                finish_position=int(item["finish_position"]),
                horse_number=str(item.get("horse_number") or ""),
                horse_name=_clean_race_horse_name(item.get("horse_name")),
                jockey_name=str(item.get("jockey_name") or ""),
                trainer_name=str(item.get("trainer_name") or ""),
                finish_time=str(item.get("finish_time") or ""),
                margin=str(item.get("margin") or ""),
                odds_value=str(item.get("odds_value") or ""),
                popularity=str(item.get("popularity") or ""),
                barrier=str(item.get("barrier") or ""),
                carried_weight=str(item.get("carried_weight") or ""),
                running_status=str(item.get("running_status") or ""),
                is_confirmed=bool(item.get("is_confirmed", True)),
                source_refs=item.get("source_refs") or {},
                raw_payload=item,
            )
        )
    RaceEventResult.objects.bulk_create(created)
    return len(created)


def _replace_history_winners(event: RaceEvent, items: Iterable[dict]) -> int:
    if _locked(event, RaceEventModule.HISTORY_WINNERS):
        return 0
    event.history_winners.all().delete()
    created = []
    for item in items:
        if not item.get("winner_year") or not item.get("horse_name"):
            continue
        created.append(
            RaceEventHistoryWinner(
                event=event,
                winner_year=int(item["winner_year"]),
                horse_name=_clean_race_horse_name(item.get("horse_name")),
                jockey_name=str(item.get("jockey_name") or ""),
                trainer_name=str(item.get("trainer_name") or ""),
                finish_time=str(item.get("finish_time") or ""),
                margin=str(item.get("margin") or ""),
                source_refs=item.get("source_refs") or {},
            )
        )
    RaceEventHistoryWinner.objects.bulk_create(created)
    return len(created)


def _safe_link_type(value: str) -> str:
    value = (value or "").strip()
    if value in ArticleRaceLinkType.values:
        return value
    return ArticleRaceLinkType.RELATED


def _safe_confidence(value: Any, default: int = 100) -> int:
    try:
        return max(0, min(int(value), 100))
    except (TypeError, ValueError):
        return default


def _apply_news_links(event: RaceEvent, items: Iterable[dict], *, user: User | None, source_name: str) -> dict:
    applied = 0
    skipped_missing_article = 0
    skipped_removed = 0
    now = timezone.now()
    for item in items:
        article_id = item.get("article_id") or item.get("id")
        if not article_id:
            skipped_missing_article += 1
            continue
        article = (
            NewsArticle.objects.filter(
                pk=article_id,
                workflow_status=WorkflowStatus.PUBLISHED,
                published_to_web_at__isnull=False,
            )
            .order_by("pk")
            .first()
        )
        if article is None:
            skipped_missing_article += 1
            continue
        existing = ArticleRaceLink.objects.filter(event=event, article=article).first()
        if existing and existing.status == ArticleRaceLinkStatus.REMOVED:
            skipped_removed += 1
            continue
        ArticleRaceLink.objects.update_or_create(
            event=event,
            article=article,
            defaults={
                "link_type": _safe_link_type(str(item.get("link_type") or "")),
                "status": ArticleRaceLinkStatus.MANUAL,
                "source": f"candidate:{source_name}"[:64],
                "confidence": _safe_confidence(item.get("confidence"), default=100),
                "matched_text": str(item.get("matched_text") or "")[:255],
                "match_reason": str(item.get("match_reason") or "后台应用相关新闻候选"),
                "metadata": item.get("metadata") or {},
                "confirmed_by": user,
                "confirmed_at": now,
            },
        )
        applied += 1
    return {
        "created_count": applied,
        "skipped_missing_article": skipped_missing_article,
        "skipped_removed": skipped_removed,
    }


def _candidate_items(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [item for item in payload.get("items", []) if isinstance(item, dict)]


def apply_data_candidate(candidate: RaceEventDataCandidate, *, user: User | None = None) -> dict:
    event = candidate.event
    payload = candidate.candidate_payload or {}
    module = candidate.module
    summary: dict[str, Any] = {"module": module, "updated_fields": [], "created_count": 0}
    with transaction.atomic():
        if module == RaceEventModule.BASIC:
            updated_fields = _set_unlocked_event_fields(event, payload)
            if updated_fields:
                event.save(update_fields=[*updated_fields, "updated_at"])
            summary["updated_fields"] = updated_fields
        elif module == RaceEventModule.RUNNERS:
            summary["created_count"] = _replace_runners(event, _candidate_items(payload))
        elif module == RaceEventModule.RESULTS:
            summary["created_count"] = _replace_results(event, _candidate_items(payload))
        elif module == RaceEventModule.HISTORY_WINNERS:
            summary["created_count"] = _replace_history_winners(event, _candidate_items(payload))
        elif module == RaceEventModule.NEWS_LINKS:
            summary.update(_apply_news_links(event, _candidate_items(payload), user=user, source_name=candidate.source_name))
        else:
            summary["skipped"] = "module_requires_manual_view_support"
        candidate.status = RaceEventCandidateStatus.APPLIED
        candidate.applied_by = user
        candidate.applied_at = timezone.now()
        candidate.save(update_fields=["status", "applied_by", "applied_at", "updated_at"])
    log_operation(
        action_type="race_candidate_applied",
        target_type="race_event",
        target_id=event.pk,
        detail=f"应用赛事候选资料 candidate={candidate.pk} module={module} summary={summary}",
        admin=user,
    )
    _task_log(
        "race_event_candidate_applied",
        TaskStatus.SUCCESS,
        payload={"event_id": event.pk, "candidate_id": candidate.pk, "summary": summary},
        detail=f"赛事候选资料已应用：{event} {module}",
    )
    return summary


def update_runner_dynamic_fields(event: RaceEvent, updates: Iterable[dict], *, source_name: str = "") -> dict:
    updated = 0
    skipped = 0
    now = timezone.now()
    for item in updates:
        horse_number = str(item.get("horse_number") or "")
        horse_name = _clean_race_horse_name(item.get("horse_name"))
        queryset = event.runners.all()
        runner = None
        if horse_number:
            runner = queryset.filter(horse_number=horse_number).first()
        if runner is None and horse_name:
            runner = queryset.filter(horse_name=horse_name).first()
        if runner is None:
            skipped += 1
            continue
        changed_fields = []
        for field in DYNAMIC_RUNNER_FIELDS:
            if field in item and getattr(runner, field) != str(item[field]):
                setattr(runner, field, str(item[field]))
                changed_fields.append(field)
        if changed_fields:
            runner.dynamic_updated_at = now
            runner.save(update_fields=[*changed_fields, "dynamic_updated_at", "updated_at"])
            updated += 1
    _task_log(
        "race_event_dynamic_fields_refreshed",
        TaskStatus.SUCCESS,
        payload={"event_id": event.pk, "source_name": source_name, "updated": updated, "skipped": skipped},
        detail=f"赛事动态字段刷新完成：{event} updated={updated} skipped={skipped}",
    )
    return {"updated": updated, "skipped": skipped}


def record_dynamic_refresh_failure(event: RaceEvent, *, source_name: str, error: str) -> None:
    _task_log(
        "race_event_dynamic_fields_refreshed",
        TaskStatus.FAILED,
        payload={"event_id": event.pk, "source_name": source_name},
        detail=error,
    )


def _event_match_terms(event: RaceEvent) -> list[str]:
    values = [event.chinese_name, event.original_name]
    values.extend(event.aliases.filter(is_active=True).values_list("text", flat=True))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return sorted(result, key=len, reverse=True)


def _article_text(article: NewsArticle, *fields: str) -> str:
    return "\n".join(str(getattr(article, field, "") or "") for field in fields)


def _classify_article_link(article: NewsArticle, event: RaceEvent) -> str:
    if article.content_category in {ContentCategory.PRE_RACE, ContentCategory.PREVIEW, ContentCategory.TIPS}:
        return ArticleRaceLinkType.PRE_RACE
    if article.content_category in {ContentCategory.POST_RACE, ContentCategory.RESULT_BRIEF}:
        return ArticleRaceLinkType.POST_RACE
    if event.local_date and article.published_at:
        article_date = timezone.localdate(article.published_at)
        if article_date < event.local_date:
            return ArticleRaceLinkType.PRE_RACE
        if article_date > event.local_date:
            return ArticleRaceLinkType.POST_RACE
    return ArticleRaceLinkType.RELATED


def _match_article(article: NewsArticle, event: RaceEvent, terms: list[str], *, date_window_days: int) -> RaceArticleMatch | None:
    title_summary = _article_text(article, "title_ja", "title_zh", "translated_title_zh", "summary_zh", "translated_summary_zh")
    body = _article_text(article, "body_ja_normalized", "body_ja_raw", "body_zh", "translated_body_zh")
    for term in terms:
        if source_term_matches_text(title_summary, term, article.source_language):
            return RaceArticleMatch(
                article=article,
                status=ArticleRaceLinkStatus.AUTO,
                link_type=_classify_article_link(article, event),
                confidence=95,
                matched_text=term,
                reason="标题或摘要命中赛事正式名/别名",
            )
    for term in terms:
        if source_term_matches_text(body, term, article.source_language):
            return RaceArticleMatch(
                article=article,
                status=ArticleRaceLinkStatus.CANDIDATE,
                link_type=_classify_article_link(article, event),
                confidence=70,
                matched_text=term,
                reason="正文命中赛事正式名/别名",
            )
    if event.local_date and article.published_at:
        article_date = timezone.localdate(article.published_at)
        if abs((article_date - event.local_date).days) <= date_window_days:
            tags = " ".join(str(item) for item in (article.tags_json or []))
            decision_reason = article.decision_reason or {}
            signals = " ".join([tags, str(decision_reason)])
            for term in terms:
                if source_term_matches_text(signals, term, article.source_language):
                    return RaceArticleMatch(
                        article=article,
                        status=ArticleRaceLinkStatus.CANDIDATE,
                        link_type=_classify_article_link(article, event),
                        confidence=65,
                        matched_text=term,
                        reason="日期窗口内命中标签/自动化决策信号",
                    )
    return None


def associate_articles_for_event(
    event: RaceEvent,
    *,
    articles: Iterable[NewsArticle] | None = None,
    date_window_days: int = 14,
) -> dict:
    terms = _event_match_terms(event)
    if not terms:
        return {"created": 0, "updated": 0, "skipped_removed": 0, "skipped_manual": 0}
    if articles is None:
        queryset = NewsArticle.objects.filter(
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at__isnull=False,
        )
        if event.local_date:
            start = event.local_date - timedelta(days=date_window_days)
            end = event.local_date + timedelta(days=date_window_days)
            queryset = queryset.filter(published_at__date__gte=start, published_at__date__lte=end)
        articles = queryset.order_by("-published_at", "-id")[:500]
    created = 0
    updated = 0
    skipped_removed = 0
    skipped_manual = 0
    for article in articles:
        match = _match_article(article, event, terms, date_window_days=date_window_days)
        if match is None:
            continue
        existing = ArticleRaceLink.objects.filter(event=event, article=article).first()
        if existing and existing.status == ArticleRaceLinkStatus.REMOVED:
            skipped_removed += 1
            continue
        if existing and existing.status == ArticleRaceLinkStatus.MANUAL:
            skipped_manual += 1
            continue
        defaults = {
            "link_type": match.link_type,
            "status": match.status,
            "source": "auto_match",
            "confidence": match.confidence,
            "matched_text": match.matched_text,
            "match_reason": match.reason,
            "metadata": {"date_window_days": date_window_days},
        }
        link, was_created = ArticleRaceLink.objects.update_or_create(event=event, article=article, defaults=defaults)
        created += int(was_created)
        updated += int(not was_created and link.status != ArticleRaceLinkStatus.REMOVED)
    _task_log(
        "race_event_article_association",
        TaskStatus.SUCCESS,
        payload={
            "event_id": event.pk,
            "created": created,
            "updated": updated,
            "skipped_removed": skipped_removed,
            "skipped_manual": skipped_manual,
        },
        detail=f"赛事新闻关联完成：{event}",
    )
    return {
        "created": created,
        "updated": updated,
        "skipped_removed": skipped_removed,
        "skipped_manual": skipped_manual,
    }


def confirm_article_link(link: ArticleRaceLink, *, user: User | None = None) -> ArticleRaceLink:
    link.status = ArticleRaceLinkStatus.MANUAL
    link.confirmed_by = user
    link.confirmed_at = timezone.now()
    link.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    log_operation(
        action_type="race_article_link_confirmed",
        target_type="article_race_link",
        target_id=link.pk,
        detail=f"确认赛事新闻关联 event={link.event_id} article={link.article_id}",
        admin=user,
    )
    return link


def remove_article_link(link: ArticleRaceLink, *, user: User | None = None) -> ArticleRaceLink:
    link.status = ArticleRaceLinkStatus.REMOVED
    link.removed_by = user
    link.removed_at = timezone.now()
    link.save(update_fields=["status", "removed_by", "removed_at", "updated_at"])
    log_operation(
        action_type="race_article_link_removed",
        target_type="article_race_link",
        target_id=link.pk,
        detail=f"移除赛事新闻关联 event={link.event_id} article={link.article_id}",
        admin=user,
    )
    return link
