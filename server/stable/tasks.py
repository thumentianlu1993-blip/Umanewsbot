from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import ArticleStatus, NewsArticle, PushTarget, SourceMode, TaskExecutionLog
from stable.services.ingestion import upsert_article_from_draft
from stable.services.pushing import push_article_to_targets
from stable.services.queueing import dispatch_task
from stable.services.translation import translate_article


User = get_user_model()


def _log_start(task_name: str, payload: dict | None = None) -> TaskExecutionLog:
    return TaskExecutionLog.objects.create(task_name=task_name, status="started", payload=payload or {})


def _log_success(log: TaskExecutionLog, detail: str) -> None:
    log.status = "success"
    log.detail = detail
    log.finished_at = timezone.now()
    log.save()


def _log_failure(log: TaskExecutionLog, detail: str) -> None:
    log.status = "failed"
    log.detail = detail
    log.finished_at = timezone.now()
    log.save()


def _crawl_netkeiba_mode(mode: str, pages: int) -> dict:
    adapter = NetkeibaAdapter()
    new_count = 0
    seen_count = 0
    for page in range(1, pages + 1):
        stubs = adapter.fetch_listing(mode, page)
        if not stubs:
            break
        for stub in stubs:
            detail = adapter.fetch_detail(stub.source_article_id)
            draft = adapter.normalize_source_payload(stub, detail)
            article, created = upsert_article_from_draft(draft)
            if created:
                new_count += 1
                dispatch_task(translate_article_task, article.id)
            else:
                seen_count += 1
        if mode in {"access", "attention"}:
            break
    return {"new_count": new_count, "seen_count": seen_count}


@shared_task
def crawl_netkeiba_latest(max_pages: int = 3, rush_window: bool = False) -> dict:
    log = _log_start("crawl_netkeiba_latest", {"max_pages": max_pages, "rush_window": rush_window})
    try:
        result = _crawl_netkeiba_mode("latest", max_pages)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_netkeiba_access() -> dict:
    log = _log_start("crawl_netkeiba_access")
    try:
        result = _crawl_netkeiba_mode("access", 1)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_netkeiba_attention() -> dict:
    log = _log_start("crawl_netkeiba_attention")
    try:
        result = _crawl_netkeiba_mode("attention", 1)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_jra_news() -> dict:
    log = _log_start("crawl_jra_news")
    try:
        adapter = JRAAdapter()
        months = {
            timezone.localtime().strftime("%Y%m"),
            (timezone.localtime() - timedelta(days=31)).strftime("%Y%m"),
        }
        new_count = 0
        seen_count = 0
        for month in sorted(months):
            for stub in adapter.fetch_listing(SourceMode.OFFICIAL, month):
                detail = adapter.fetch_detail(stub.source_url)
                draft = adapter.normalize_source_payload(stub, detail)
                article, created = upsert_article_from_draft(draft)
                if created:
                    new_count += 1
                    dispatch_task(translate_article_task, article.id)
                else:
                    seen_count += 1
        _log_success(log, f"new={new_count} seen={seen_count}")
        return {"new_count": new_count, "seen_count": seen_count}
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def translate_article_task(article_id: int) -> dict:
    log = _log_start("translate_article", {"article_id": article_id})
    try:
        article = NewsArticle.objects.get(pk=article_id)
        result = translate_article(article)
        article.title_zh = result.title_zh
        article.body_zh = result.body_zh
        article.push_summary_zh = result.push_summary_zh
        article.status = ArticleStatus.TRANSLATED
        article.translation_metadata = {**article.translation_metadata, **result.metadata}
        article.save()
        _log_success(log, f"translated article={article_id}")
        return {"article_id": article_id, "translated": True}
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


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
