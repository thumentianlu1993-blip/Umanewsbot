from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from django.db import transaction
from django.utils import timezone

from stable.models import (
    ArticleStatus,
    CrawlJob,
    CrawlStatus,
    NewsArticle,
    NewsImage,
    NewsSnapshot,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)

from .sources import find_builtin_source
from .storage import download_image


@dataclass(frozen=True)
class ArticleUpsertResult:
    article: NewsArticle
    created: bool
    source_elevated: bool = False

    def __iter__(self) -> Iterator[object]:
        yield self.article
        yield self.created


RANKED_NETKEIBA_MODES = {SourceMode.ACCESS, SourceMode.ATTENTION}


def _should_elevate_netkeiba_source(article: NewsArticle, draft) -> bool:
    return (
        article.source_site == SourceSite.NETKEIBA
        and draft.source_site == SourceSite.NETKEIBA
        and article.source_mode == SourceMode.LATEST
        and draft.source_mode in RANKED_NETKEIBA_MODES
    )


def _should_update_primary_source(article: NewsArticle, draft, *, source_elevated: bool) -> bool:
    if source_elevated:
        return True
    if article.source_site != SourceSite.NETKEIBA or draft.source_site != SourceSite.NETKEIBA:
        return True
    return article.source_mode == draft.source_mode


def upsert_article_from_draft(draft, crawl_job: CrawlJob | None = None) -> ArticleUpsertResult:
    now = timezone.now()
    source_config = find_builtin_source(draft.source_site, draft.source_mode)
    source_elevated = False
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
            source_elevated = _should_elevate_netkeiba_source(article, draft)
            if _should_update_primary_source(article, draft, source_elevated=source_elevated):
                article.source_mode = draft.source_mode
                article.source_config = source_config or article.source_config
                article.crawl_job = crawl_job or article.crawl_job
                if source_config:
                    article.source_note = source_config.name
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
    return ArticleUpsertResult(article=article, created=created, source_elevated=source_elevated)
