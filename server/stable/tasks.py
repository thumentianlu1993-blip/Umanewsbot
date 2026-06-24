from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import (
    ArticleStatus,
    ArticleTranslationStatus,
    AutomationPhase,
    AutomationStatus,
    CrawlJob,
    NewsArticle,
    NewsSource,
    NotificationLog,
    NotificationType,
    PublishedByMode,
    PushTarget,
    ReviewMode,
    SourceMode,
    TaskExecutionLog,
    TaskStatus,
    WorkflowStatus,
)
from stable.services.automation import (
    apply_score_decision,
    automation_content_source,
    important_manual_notification_payload,
    is_ready_for_auto_publish,
    mark_automation_failed,
    prepare_base_translation_for_publish,
    publish_article_automatically,
    score_article_for_automation,
)
from stable.services.ingestion import upsert_article_from_draft
from stable.services.notifications import send_automation_notification, send_high_value_warning_notification
from stable.services.operations import log_operation
from stable.services.pushing import push_article_to_targets
from stable.services.queueing import dispatch_task
from stable.services.rewriting import apply_rewrite_result, rewrite_article
from stable.services.sources import find_builtin_source, sync_builtin_sources
from stable.services.term_discovery import discover_and_aggregate_article
from stable.services.translation import translate_article
from stable.services.validation import apply_validation_outcome, validate_rewrite
from stable.services.external_horse_data import ExternalHorseDataImporter, ImportOptions


User = get_user_model()
JRA_SKIPPABLE_DETAIL_ERRORS = (ValueError, AttributeError, IndexError, TypeError)


def _log_start(task_name: str, payload: dict | None = None) -> TaskExecutionLog:
    return TaskExecutionLog.objects.create(task_name=task_name, status=TaskStatus.STARTED, payload=payload or {})


def _log_success(log: TaskExecutionLog, detail: str) -> None:
    log.status = TaskStatus.SUCCESS
    log.detail = detail
    log.finished_at = timezone.now()
    log.save()


def _log_failure(log: TaskExecutionLog, detail: str) -> None:
    log.status = TaskStatus.FAILED
    log.detail = detail
    log.finished_at = timezone.now()
    log.save()


def _start_crawl_job(source: NewsSource | None) -> CrawlJob:
    return CrawlJob.objects.create(source=source, status=TaskStatus.STARTED)


def _finish_crawl_job(
    job: CrawlJob,
    *,
    success_count: int = 0,
    fail_count: int = 0,
    error_message: str = "",
    message: str = "",
) -> None:
    job.status = TaskStatus.FAILED if error_message else TaskStatus.SUCCESS
    job.success_count = success_count
    job.fail_count = fail_count
    job.error_message = error_message or message
    job.finished_at = timezone.now()
    job.save()
    if job.source:
        job.source.last_crawl_at = job.finished_at
        job.source.last_crawl_status = job.status
        job.source.last_crawl_message = error_message or message or f"新增 {success_count}，重复 {fail_count}"
        job.source.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])


def _auto_translate_article_after_ingest(article: NewsArticle) -> dict | None:
    if not getattr(settings, "AUTO_TRANSLATE_ON_INGEST", True):
        return None
    try:
        if getattr(settings, "AUTO_TRANSLATE_SYNC", True):
            return translate_article_task.run(article.id)
        return dispatch_task(translate_article_task, article.id)
    except Exception as exc:
        return {"article_id": article.id, "translated": False, "error": str(exc)}


def _discover_terms_after_ingest(article: NewsArticle) -> dict | None:
    if not getattr(settings, "TERM_DISCOVERY_ENABLED", False):
        return None
    try:
        return dispatch_task(discover_term_candidates_task, article.id)
    except Exception as exc:
        return {"article_id": article.id, "discovered": False, "error": str(exc)}


def _crawl_netkeiba_mode(mode: str, pages: int, source: NewsSource | None = None) -> dict:
    adapter = NetkeibaAdapter()
    job = _start_crawl_job(source)
    new_count = 0
    seen_count = 0
    try:
        for page in range(1, pages + 1):
            stubs = adapter.fetch_listing(mode, page)
            if not stubs:
                break
            for stub in stubs:
                detail = adapter.fetch_detail(stub.source_article_id)
                draft = adapter.normalize_source_payload(stub, detail)
                article, created = upsert_article_from_draft(draft, crawl_job=job)
                if created:
                    new_count += 1
                    _discover_terms_after_ingest(article)
                    _auto_translate_article_after_ingest(article)
                else:
                    seen_count += 1
            if mode in {SourceMode.ACCESS, SourceMode.ATTENTION}:
                break
        _finish_crawl_job(job, success_count=new_count, fail_count=seen_count)
        return {"new_count": new_count, "seen_count": seen_count, "crawl_job_id": job.id}
    except Exception as exc:
        _finish_crawl_job(job, success_count=new_count, fail_count=seen_count, error_message=str(exc))
        raise


def _crawl_jra_source(source: NewsSource | None = None) -> dict:
    adapter = JRAAdapter()
    job = _start_crawl_job(source)
    months = {
        timezone.localtime().strftime("%Y%m"),
        (timezone.localtime() - timedelta(days=31)).strftime("%Y%m"),
    }
    new_count = 0
    seen_count = 0
    skipped_errors: list[str] = []
    try:
        for month in sorted(months):
            for stub in adapter.fetch_listing(SourceMode.OFFICIAL, month):
                try:
                    detail = adapter.fetch_detail(stub.source_url)
                except JRA_SKIPPABLE_DETAIL_ERRORS as exc:
                    skipped_errors.append(f"{stub.source_url}: {exc}")
                    continue
                draft = adapter.normalize_source_payload(stub, detail)
                article, created = upsert_article_from_draft(draft, crawl_job=job)
                if created:
                    new_count += 1
                    _discover_terms_after_ingest(article)
                    _auto_translate_article_after_ingest(article)
                else:
                    seen_count += 1
        skipped_errors = [*adapter.skipped_items, *skipped_errors]
        message = ""
        if skipped_errors:
            message = f"新增 {new_count}，重复 {seen_count}；跳过 {len(skipped_errors)} 条：{skipped_errors[0][:120]}"
        _finish_crawl_job(job, success_count=new_count, fail_count=seen_count, message=message)
        return {
            "new_count": new_count,
            "seen_count": seen_count,
            "skipped_count": len(skipped_errors),
            "crawl_job_id": job.id,
        }
    except Exception as exc:
        _finish_crawl_job(job, success_count=new_count, fail_count=seen_count, error_message=str(exc))
        raise


@shared_task
def crawl_netkeiba_latest(max_pages: int = 3, rush_window: bool = False) -> dict:
    sync_builtin_sources()
    source = find_builtin_source("netkeiba", "latest")
    log = _log_start("crawl_netkeiba_latest", {"max_pages": max_pages, "rush_window": rush_window})
    try:
        result = _crawl_netkeiba_mode("latest", max_pages, source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_netkeiba_access() -> dict:
    sync_builtin_sources()
    source = find_builtin_source("netkeiba", "access")
    log = _log_start("crawl_netkeiba_access")
    try:
        result = _crawl_netkeiba_mode("access", 1, source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_netkeiba_attention() -> dict:
    sync_builtin_sources()
    source = find_builtin_source("netkeiba", "attention")
    log = _log_start("crawl_netkeiba_attention")
    try:
        result = _crawl_netkeiba_mode("attention", 1, source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_jra_news() -> dict:
    sync_builtin_sources()
    source = find_builtin_source("jra", "official")
    log = _log_start("crawl_jra_news")
    try:
        result = _crawl_jra_source(source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_news_source_task(source_id: int) -> dict:
    sync_builtin_sources()
    source = NewsSource.objects.get(pk=source_id, deleted_at__isnull=True)
    log = _log_start("crawl_news_source", {"source_id": source_id})
    try:
        if source.adapter_key == "netkeiba":
            pages = 3 if source.source_mode == SourceMode.LATEST else 1
            result = _crawl_netkeiba_mode(source.source_mode, pages, source=source)
        elif source.adapter_key == "jra":
            result = _crawl_jra_source(source=source)
        else:
            raise NotImplementedError("当前版本仅支持内置 netkeiba / JRA 来源")
        _log_success(log, f"source={source_id} new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def discover_term_candidates_task(article_id: int) -> dict:
    log = _log_start("discover_term_candidates", {"article_id": article_id})
    if not getattr(settings, "TERM_DISCOVERY_ENABLED", False):
        _log_success(log, "term discovery disabled")
        return {"article_id": article_id, "skipped": True, "reason": "term discovery disabled"}
    try:
        article = NewsArticle.objects.get(pk=article_id)
        result = discover_and_aggregate_article(article)
        _log_success(log, f"findings={result['finding_count']} candidates={len(result['candidate_ids'])}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def translate_article_task(article_id: int) -> dict:
    log = _log_start("translate_article", {"article_id": article_id})
    article = None
    try:
        article = NewsArticle.objects.get(pk=article_id)
        previous_attempts = article.translation_runs.count()
        article.translation_status = ArticleTranslationStatus.TRANSLATING
        article.translation_error_message = ""
        article.translation_started_at = timezone.now()
        article.translation_retry_count = previous_attempts
        article.translation_provider = settings.TRANSLATION_PROVIDER
        article.translation_model = settings.TRANSLATION_MODEL
        article.save(
            update_fields=[
                "translation_status",
                "translation_error_message",
                "translation_started_at",
                "translation_retry_count",
                "translation_provider",
                "translation_model",
                "updated_at",
            ]
        )
        result = translate_article(article)
        article.apply_translation_result(result)
        article.status = ArticleStatus.TRANSLATED
        article.translation_status = ArticleTranslationStatus.TRANSLATED
        article.translation_error_message = ""
        article.translated_at = timezone.now()
        article.translation_model = result.metadata.get("model", "")
        article.translation_provider = result.metadata.get("provider", "")
        if article.workflow_status in {WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED}:
            article.workflow_status = WorkflowStatus.PENDING_EDIT
        article.automation_status = AutomationStatus.PENDING
        article.translation_metadata = {**article.translation_metadata, **result.metadata}
        article.save()
        if getattr(settings, "AUTOMATION_ENABLED", False):
            dispatch_task(process_article_automation_task, article.id)
        _log_success(log, f"translated article={article_id}")
        return {
            "article_id": article_id,
            "translated": True,
            "translation_status": article.translation_status,
            "translation_model": article.translation_model,
        }
    except Exception as exc:
        if article is not None:
            article.translation_status = ArticleTranslationStatus.FAILED
            article.translation_error_message = str(exc)
            article.translation_model = article.translation_model or settings.TRANSLATION_MODEL
            article.translation_provider = article.translation_provider or settings.TRANSLATION_PROVIDER
            if article.workflow_status in {WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED}:
                article.workflow_status = WorkflowStatus.TRANSLATION_FAILED
            article.save(
                update_fields=[
                    "translation_status",
                    "translation_error_message",
                    "translation_model",
                    "translation_provider",
                    "workflow_status",
                    "updated_at",
                ]
            )
            if getattr(settings, "AUTOMATION_ENABLED", False):
                dispatch_task(
                    send_notification_task,
                    NotificationType.TRANSLATION_FAILED,
                    {
                        "article_id": article.id,
                        "title": article.effective_title,
                        "error": str(exc),
                        "source_url": article.source_url,
                    },
                )
        _log_failure(log, str(exc))
        raise


@shared_task
def process_article_automation_task(article_id: int) -> dict:
    log = _log_start("process_article_automation", {"article_id": article_id})
    if not getattr(settings, "AUTOMATION_ENABLED", False):
        _log_success(log, "automation disabled")
        return {"article_id": article_id, "skipped": True, "reason": "automation disabled"}
    article = NewsArticle.objects.get(pk=article_id)
    try:
        score_article_task.run(article.id)
        article.refresh_from_db()
        if article.automation_status == AutomationStatus.REWRITE_READY and article.review_mode == ReviewMode.AUTO:
            if automation_content_source() == "rewrite":
                rewrite_article_task.run(article.id)
            else:
                prepare_base_translation_for_publish(article)
                validate_rewrite_task.run(article.id)
            article.refresh_from_db()
        if article.automation_status == AutomationStatus.REWRITTEN and article.review_mode == ReviewMode.AUTO:
            validate_rewrite_task.run(article.id)
            article.refresh_from_db()
        send_high_value_warning_notification(article)
        payload = important_manual_notification_payload(article)
        if payload:
            send_notification_task.run(NotificationType.IMPORTANT_MANUAL, payload)
        _log_success(log, f"automation_status={article.automation_status} review_mode={article.review_mode}")
        return {
            "article_id": article.id,
            "automation_status": article.automation_status,
            "review_mode": article.review_mode,
            "score_total": article.score_total,
        }
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.SCORE, error=exc)
        send_notification_task.run(
            NotificationType.REPEATED_FAILURE,
            {"article_id": article.id, "title": article.effective_title, "error": str(exc)},
        )
        _log_failure(log, str(exc))
        raise


@shared_task
def score_article_task(article_id: int) -> dict:
    log = _log_start("score_article", {"article_id": article_id})
    article = NewsArticle.objects.get(pk=article_id)
    try:
        decision = score_article_for_automation(article)
        apply_score_decision(article, decision)
        _log_success(log, decision.decision_summary)
        return {
            "article_id": article.id,
            "review_mode": decision.review_mode,
            "automation_status": decision.automation_status,
            "score_total": decision.score_total,
        }
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.SCORE, error=exc)
        _log_failure(log, str(exc))
        raise


@shared_task
def rewrite_article_task(article_id: int) -> dict:
    log = _log_start("rewrite_article", {"article_id": article_id})
    article = NewsArticle.objects.get(pk=article_id)
    if article.review_mode != ReviewMode.AUTO:
        _log_success(log, "skipped non-auto article")
        return {"article_id": article.id, "skipped": True}
    try:
        result = rewrite_article(article)
        apply_rewrite_result(article, result)
        _log_success(log, f"confidence={result.confidence}")
        return {"article_id": article.id, "rewritten": True, "confidence": result.confidence}
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.REWRITE, error=exc)
        send_notification_task.run(
            NotificationType.REWRITE_FAILED,
            {"article_id": article.id, "title": article.effective_title, "error": str(exc), "source_url": article.source_url},
        )
        _log_failure(log, str(exc))
        raise


@shared_task
def validate_rewrite_task(article_id: int) -> dict:
    log = _log_start("validate_rewrite", {"article_id": article_id})
    article = NewsArticle.objects.get(pk=article_id)
    try:
        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)
        _log_success(log, outcome.reason)
        return {"article_id": article.id, "validated": outcome.passed, "reason": outcome.reason}
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.VALIDATE, error=exc)
        _log_failure(log, str(exc))
        raise


def _resolve_auto_publish_batch_limit(limit: int | None = None, now=None) -> int:
    if limit is not None:
        return max(0, int(limit))
    base_limit = int(getattr(settings, "AUTO_PUBLISH_BATCH_LIMIT", 4))
    peak_limit = int(getattr(settings, "AUTO_PUBLISH_PEAK_BATCH_LIMIT", 10))
    peak_day = int(getattr(settings, "AUTO_PUBLISH_PEAK_DAY_OF_WEEK", 6))
    peak_start = int(getattr(settings, "AUTO_PUBLISH_PEAK_START_HOUR", 13))
    peak_end = int(getattr(settings, "AUTO_PUBLISH_PEAK_END_HOUR", 16))
    local_now = timezone.localtime(now or timezone.now())
    if local_now.weekday() == peak_day and peak_start <= local_now.hour < peak_end:
        return max(0, peak_limit)
    return max(0, base_limit)


@shared_task
def auto_publish_batch_task(limit: int | None = None) -> dict:
    log = _log_start("auto_publish_batch", {"limit": limit})
    if not getattr(settings, "AUTOMATION_ENABLED", False):
        _log_success(log, "automation disabled")
        return {"published_count": 0, "skipped": True}
    batch_limit = _resolve_auto_publish_batch_limit(limit)
    queryset = (
        NewsArticle.objects.filter(review_mode=ReviewMode.AUTO, automation_status=AutomationStatus.PUBLISH_READY)
        .exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED, WorkflowStatus.DUPLICATE])
        .order_by("-score_total", "-published_at", "-id")
    )
    published_ids: list[int] = []
    failed_ids: list[int] = []
    for article in queryset[:batch_limit]:
        try:
            if not is_ready_for_auto_publish(article):
                continue
            publish_article_automatically(article)
            published_ids.append(article.id)
        except Exception as exc:
            failed_ids.append(article.id)
            mark_automation_failed(article, phase=AutomationPhase.PUBLISH, error=exc)
            send_notification_task.run(
                NotificationType.PUBLISH_FAILED,
                {"article_id": article.id, "title": article.effective_title, "error": str(exc)},
            )
    detail = f"published={len(published_ids)} failed={len(failed_ids)}"
    if failed_ids:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {"published_count": len(published_ids), "batch_limit": batch_limit, "published_ids": published_ids, "failed_ids": failed_ids}


def _recent_notification_exists(notification_type: str, hours: int = 6) -> bool:
    since = timezone.now() - timedelta(hours=hours)
    return NotificationLog.objects.filter(type=notification_type, created_at__gte=since).exists()


@shared_task
def send_notification_task(notification_type: str, payload: dict) -> dict:
    logs = send_automation_notification(notification_type, payload)
    return {"notification_type": notification_type, "log_ids": [log.id for log in logs]}


@shared_task
def detect_automation_anomalies_task() -> dict:
    log = _log_start("detect_automation_anomalies")
    if not getattr(settings, "AUTOMATION_ENABLED", False):
        _log_success(log, "automation disabled")
        return {"skipped": True}
    sent: list[str] = []
    now = timezone.now()
    stale_sources = []
    for source in NewsSource.objects.filter(enabled=True, deleted_at__isnull=True):
        if not source.last_crawl_at:
            continue
        stale_minutes = max(source.crawl_interval_minutes * 3, 180)
        if source.last_crawl_at < now - timedelta(minutes=stale_minutes):
            stale_sources.append(source.name)
    if stale_sources and not _recent_notification_exists(NotificationType.STALE_SOURCE):
        send_notification_task.run(NotificationType.STALE_SOURCE, {"source": ", ".join(stale_sources)})
        sent.append(NotificationType.STALE_SOURCE)

    backlog_count = NewsArticle.objects.filter(automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED).count()
    if backlog_count >= 50 and not _recent_notification_exists(NotificationType.BACKLOG):
        send_notification_task.run(NotificationType.BACKLOG, {"manual_review_count": backlog_count})
        sent.append(NotificationType.BACKLOG)

    last_day_auto = NewsArticle.objects.filter(auto_publish_at__gte=now - timedelta(hours=24)).exists()
    has_publish_ready = NewsArticle.objects.filter(automation_status=AutomationStatus.PUBLISH_READY).exists()
    if not last_day_auto and has_publish_ready and not _recent_notification_exists(NotificationType.NO_AUTO_PUBLISH_24H):
        send_notification_task.run(NotificationType.NO_AUTO_PUBLISH_24H, {"publish_ready_count": has_publish_ready})
        sent.append(NotificationType.NO_AUTO_PUBLISH_24H)

    recent_failures = TaskExecutionLog.objects.filter(status=TaskStatus.FAILED, started_at__gte=now - timedelta(hours=2)).count()
    if recent_failures >= 3 and not _recent_notification_exists(NotificationType.REPEATED_FAILURE):
        send_notification_task.run(NotificationType.REPEATED_FAILURE, {"failed_task_count": recent_failures})
        sent.append(NotificationType.REPEATED_FAILURE)
    _log_success(log, f"notifications={','.join(sent) or 'none'}")
    return {"notifications": sent}


@shared_task
def import_external_horse_data_task(
    *,
    year: int | None = None,
    month: int | None = None,
    race_id: str = "",
    horse_id: str = "",
    horse_name: str = "",
    allow_network: bool = False,
    max_races: int | None = None,
    max_horses: int | None = None,
    fetch_odds: bool | None = None,
    fetch_horse_detail: bool | None = None,
) -> dict:
    log = _log_start(
        "import_external_horse_data",
        {"year": year, "month": month, "race_id": race_id, "horse_id": horse_id, "allow_network": allow_network},
    )
    importer = ExternalHorseDataImporter(
        ImportOptions.from_settings(
            allow_network=allow_network,
            max_races=max_races,
            max_horses=max_horses,
            fetch_odds=fetch_odds,
            fetch_horse_detail=fetch_horse_detail,
        )
    )
    try:
        if race_id:
            result = importer.import_race(race_id)
        elif horse_id:
            result = importer.import_horse(horse_id, horse_name=horse_name)
        elif year and month:
            result = importer.import_month(year, month)
        else:
            result = importer.import_default()
        _log_success(log, f"status={result.get('status')} run_id={result.get('run_id')}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def batch_translate_articles_task(article_ids: list[int] | None = None, limit: int = 50) -> dict:
    log = _log_start("batch_translate_articles", {"article_ids": article_ids or [], "limit": limit})
    queryset = NewsArticle.objects.all().order_by("-published_at", "-id")
    if article_ids:
        queryset = queryset.filter(pk__in=article_ids)
    else:
        queryset = queryset.filter(
            workflow_status__in=[WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED]
        )
    article_ids_to_process = list(queryset.values_list("id", flat=True)[:limit])
    translated_count = 0
    failed_count = 0
    for article_id in article_ids_to_process:
        try:
            translate_article_task.run(article_id)
            translated_count += 1
        except Exception:
            failed_count += 1
    detail = f"processed={len(article_ids_to_process)} translated={translated_count} failed={failed_count}"
    if failed_count:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {
        "processed": len(article_ids_to_process),
        "translated_count": translated_count,
        "failed_count": failed_count,
        "article_ids": article_ids_to_process,
    }


@shared_task
def push_article_task(article_id: int, target_ids: list[int], user_id: int | None = None) -> dict:
    log = _log_start("push_article", {"article_id": article_id, "target_ids": target_ids})
    try:
        article = NewsArticle.objects.get(pk=article_id)
        targets = list(PushTarget.objects.filter(pk__in=target_ids, is_active=True))
        user = User.objects.filter(pk=user_id).first() if user_id else None
        push_article_to_targets(article, targets, user)
        _log_success(log, f"pushed article={article_id} to {len(targets)} target(s)")
        return {"article_id": article_id, "target_count": len(targets)}
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


def publish_article(article: NewsArticle, user) -> None:
    article.workflow_status = WorkflowStatus.PUBLISHED
    article.published_to_web_at = timezone.now()
    article.published_by = user
    article.published_by_mode = PublishedByMode.MANUAL
    article.save(update_fields=["workflow_status", "published_to_web_at", "published_by", "published_by_mode", "updated_at"])
    log_operation(
        action_type="article_published",
        target_type="article",
        target_id=article.pk,
        detail=f"发布文章《{article.effective_title}》",
        admin=user,
    )
