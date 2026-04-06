from __future__ import annotations

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import NewsArticle, PushTarget, TaskExecutionLog
from .services.pushing import enqueue_push_for_article


def _article_payload(article: NewsArticle) -> dict:
    return {
        "id": article.id,
        "source_site": article.source_site,
        "source_mode": article.source_mode,
        "source_article_id": article.source_article_id,
        "title_ja": article.title_ja,
        "title_zh": article.title_zh,
        "published_at": article.published_at.isoformat(),
        "status": article.status,
        "source_url": article.source_url,
        "is_first_crawled": article.is_first_crawled,
        "images": [
            {
                "id": image.id,
                "original_url": image.original_url,
                "local_path": image.local_path,
                "caption_ja": image.caption_ja,
                "caption_zh": image.caption_zh,
            }
            for image in article.images.all()
        ],
    }


@staff_member_required
@require_GET
def article_list_api(request: HttpRequest) -> JsonResponse:
    queryset = NewsArticle.objects.all().prefetch_related("images")
    for key in ("source_site", "source_mode", "status"):
        value = request.GET.get(key)
        if value:
            queryset = queryset.filter(**{key: value})
    payload = [_article_payload(article) for article in queryset[:100]]
    return JsonResponse({"results": payload})


@staff_member_required
@require_GET
def article_detail_api(_request: HttpRequest, article_id: int) -> JsonResponse:
    article = get_object_or_404(NewsArticle.objects.prefetch_related("images"), pk=article_id)
    return JsonResponse(_article_payload(article))


@staff_member_required
@require_POST
def article_update_api(request: HttpRequest, article_id: int) -> JsonResponse:
    article = get_object_or_404(NewsArticle, pk=article_id)
    payload = json.loads(request.body.decode("utf-8"))
    changed_fields: list[str] = []
    for field in ("title_zh", "body_zh", "push_summary_zh", "editor_notes", "status"):
        if field in payload:
            setattr(article, field, payload[field])
            changed_fields.append(field)
    if changed_fields:
        article.mark_manual_edits(changed_fields)
        article.save()
    return JsonResponse({"updated": True, "fields": changed_fields})


@staff_member_required
@require_POST
def article_push_api(request: HttpRequest, article_id: int) -> JsonResponse:
    article = get_object_or_404(NewsArticle, pk=article_id)
    payload = json.loads(request.body.decode("utf-8"))
    target_ids = payload.get("target_ids") or []
    targets = list(PushTarget.objects.filter(pk__in=target_ids, is_active=True))
    if not targets:
        targets = list(PushTarget.objects.filter(is_default=True, is_active=True))
    enqueue_push_for_article(article, targets, request.user)
    return JsonResponse({"queued": True, "target_count": len(targets)})


@staff_member_required
@require_GET
def task_log_list_api(_request: HttpRequest) -> JsonResponse:
    logs = TaskExecutionLog.objects.all()[:100]
    return JsonResponse(
        {
            "results": [
                {
                    "task_name": log.task_name,
                    "status": log.status,
                    "detail": log.detail,
                    "started_at": log.started_at.isoformat(),
                    "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                }
                for log in logs
            ]
        }
    )
