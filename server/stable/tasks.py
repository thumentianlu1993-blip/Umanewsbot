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
    CrawlJob,
    NewsArticle,
    NewsSource,
    PushTarget,
    SourceMode,
    TaskExecutionLog,
    TaskStatus,
    WorkflowStatus,
)
from stable.services.ingestion import upsert_article_from_draft
from stable.services.operations import log_operation
from stable.services.pushing import push_article_to_targets
from stable.services.queueing import dispatch_task
from stable.services.sources import find_builtin_source, sync_builtin_sources
from stable.services.translation import translate_article


User = get_user_model()


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


def _finish_crawl_job(job: CrawlJob, *, success_count: int = 0, fail_count: int = 0, error_message: str = "") -> None:
    job.status = TaskStatus.FAILED if error_message else TaskStatus.SUCCESS
    job.success_count = success_count
    job.fail_count = fail_count
    job.error_message = error_message
    job.finished_at = timezone.now()
    job.save()
    if job.source:
        job.source.last_crawl_at = job.finished_at
        job.source.last_crawl_status = job.status
        job.source.last_crawl_message = error_message or f"新增 {success_count}，重复 {fail_count}"
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
    try:
        for month in sorted(months):
            for stub in adapter.fetch_listing(SourceMode.OFFICIAL, month):
                detail = adapter.fetch_detail(stub.source_url)
                draft = adapter.normalize_source_payload(stub, detail)
                article, created = upsert_article_from_draft(draft, crawl_job=job)
                if created:
                    new_count += 1
                    _auto_translate_article_after_ingest(article)
                else:
                    seen_count += 1
        _finish_crawl_job(job, success_count=new_count, fail_count=seen_count)
        return {"new_count": new_count, "seen_count": seen_count, "crawl_job_id": job.id}
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
        article.translation_metadata = {**article.translation_metadata, **result.metadata}
        article.save()
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
    article.save(update_fields=["workflow_status", "published_to_web_at", "published_by", "updated_at"])
    log_operation(
        action_type="article_published",
        target_type="article",
        target_id=article.pk,
        detail=f"发布文章《{article.effective_title}》",
        admin=user,
    )
