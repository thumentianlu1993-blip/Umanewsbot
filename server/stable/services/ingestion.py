from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from stable.models import ArticleStatus, CrawlJob, CrawlStatus, NewsArticle, NewsImage, NewsSnapshot, WorkflowStatus

from .sources import find_builtin_source
from .storage import download_image


def upsert_article_from_draft(draft, crawl_job: CrawlJob | None = None) -> tuple[NewsArticle, bool]:
    now = timezone.now()
    source_config = find_builtin_source(draft.source_site, draft.source_mode)
    with transaction.atomic():
        article, created = NewsArticle.objects.get_or_create(
            source_site=draft.source_site,
            source_article_id=draft.source_article_id,
            defaults={
                "source_config": source_config,
                "crawl_job": crawl_job,
                "source_mode": draft.source_mode,
                "title_ja": draft.title_ja,
                "body_ja_raw": draft.body_ja_raw,
                "body_ja_normalized": draft.body_ja_normalized,
                "original_content_html": draft.metadata.get("html", ""),
                "original_author": draft.metadata.get("author", ""),
                "published_at": draft.published_at,
                "source_url": draft.source_url,
                "is_first_crawled": True,
                "first_seen_at": now,
                "last_seen_at": now,
                "crawl_status": CrawlStatus.SUCCESS,
                "status": ArticleStatus.CRAWLED,
                "workflow_status": WorkflowStatus.PENDING_TRANSLATION,
                "source_note": source_config.name if source_config else draft.source_site,
                "translation_metadata": draft.metadata,
                "tags_json": list(source_config.default_tags) if source_config else [],
            },
        )
        if not created:
            article.source_config = source_config or article.source_config
            article.crawl_job = crawl_job or article.crawl_job
            article.title_ja = draft.title_ja or article.title_ja
            article.body_ja_raw = draft.body_ja_raw or article.body_ja_raw
            article.body_ja_normalized = draft.body_ja_normalized or article.body_ja_normalized
            article.original_content_html = draft.metadata.get("html", article.original_content_html)
            article.original_author = draft.metadata.get("author", article.original_author)
            article.published_at = draft.published_at or article.published_at
            article.source_url = draft.source_url or article.source_url
            article.last_seen_at = now
            article.crawl_status = CrawlStatus.SUCCESS
            article.translation_metadata = {**article.translation_metadata, **draft.metadata}
            article.save()

        NewsSnapshot.objects.create(
            article=article,
            source_site=draft.source_site,
            source_mode=draft.source_mode,
            rank=draft.rank,
            comment_count=draft.comment_count,
            attention_count=draft.attention_count,
            snapshot_metadata=draft.metadata,
            captured_at=now,
        )

        for image_draft in draft.images:
            image, _ = NewsImage.objects.get_or_create(
                article=article,
                original_url=image_draft.original_url,
                defaults={"caption_ja": image_draft.caption_ja, "sort_order": image_draft.sort_order},
            )
            image.caption_ja = image_draft.caption_ja
            image.sort_order = image_draft.sort_order
            if image.original_url and not image.local_path:
                try:
                    image.local_path = download_image(image.original_url)
                except Exception:
                    image.local_path = ""
            image.save()
    return article, created
