from __future__ import annotations

from collections.abc import Mapping
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
    RacingRegion,
    SourceKind,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)

from .sources import find_builtin_source
from .news_attribution import (
    AttributionPreview,
    AttributionResult,
    apply_article_attribution,
    content_scoped_candidate_source_enabled,
)
from .storage import download_image


@dataclass(frozen=True)
class ArticleUpsertResult:
    article: NewsArticle
    created: bool
    source_elevated: bool = False

    def __iter__(self) -> Iterator[object]:
        yield self.article
        yield self.created


RANKED_NEWS_MODES = {SourceMode.ACCESS, SourceMode.ATTENTION}


def _draft_value(draft, field_name: str, fallback):
    value = getattr(draft, field_name, None)
    return value or fallback


def _source_metadata(draft, source_config) -> dict:
    return {
        "racing_region": _draft_value(
            draft,
            "racing_region",
            getattr(source_config, "racing_region", RacingRegion.JAPAN) if source_config else RacingRegion.JAPAN,
        ),
        "source_language": _draft_value(
            draft,
            "source_language",
            getattr(source_config, "source_language", SourceLanguage.JAPANESE) if source_config else SourceLanguage.JAPANESE,
        ),
        "source_kind": _draft_value(
            draft,
            "source_kind",
            getattr(source_config, "source_kind", SourceKind.NEWS) if source_config else SourceKind.NEWS,
        ),
    }


def _draft_html(draft) -> str:
    return getattr(draft, "original_content_html", "") or draft.metadata.get("html", "")


def _json_safe_metadata_value(value):
    if isinstance(value, Mapping):
        return {
            key: _json_safe_metadata_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_metadata_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [
            _json_safe_metadata_value(item)
            for item in sorted(value, key=lambda item: repr(item))
        ]
    return value


def _draft_metadata(draft) -> dict:
    return {
        key: _json_safe_metadata_value(value)
        for key, value in (draft.metadata or {}).items()
        if key != "html"
    }


def _draft_article_source_site(draft):
    return getattr(draft, "canonical_source_site", None) or draft.source_site


def _should_elevate_ranked_source(article: NewsArticle, draft) -> bool:
    return (
        article.source_site == _draft_article_source_site(draft)
        and article.source_mode == SourceMode.LATEST
        and draft.source_mode in RANKED_NEWS_MODES
    )


def _should_update_primary_source(article: NewsArticle, draft, *, source_elevated: bool) -> bool:
    article_source_site = _draft_article_source_site(draft)
    if source_elevated:
        return True
    if article.source_site != article_source_site:
        return True
    if article.source_mode in RANKED_NEWS_MODES:
        return article.source_mode == draft.source_mode
    if article_source_site == SourceSite.TDN and draft.source_site == SourceSite.TDN_FRANCE:
        return True
    if (
        article_source_site == SourceSite.TDN
        and draft.source_site == SourceSite.TDN
        and article.source_config
        and article.source_config.source_site == SourceSite.TDN_FRANCE
    ):
        return False
    return article.source_mode == draft.source_mode


def upsert_article_from_draft(
    draft,
    crawl_job: CrawlJob | None = None,
    *,
    attribution_preview: AttributionPreview | AttributionResult | None = None,
) -> ArticleUpsertResult:
    source_config = find_builtin_source(draft.source_site, draft.source_mode)
    article_source_site = _draft_article_source_site(draft)
    content_scoped_source_enabled = content_scoped_candidate_source_enabled(
        source_site=article_source_site,
    )
    if content_scoped_source_enabled:
        if type(attribution_preview) not in (
            AttributionPreview,
            AttributionResult,
        ):
            raise ValueError("attribution_preview_required")

    now = timezone.now()
    source_metadata = _source_metadata(draft, source_config)
    draft_metadata = _draft_metadata(draft)
    has_published_evidence = "published_at_verified" in draft_metadata
    draft_published_verified = draft_metadata.get("published_at_verified") if has_published_evidence else None
    draft_published_evidence = draft_metadata.get("published_at_evidence") or {}
    source_elevated = False
    with transaction.atomic():
        article, created = NewsArticle.objects.get_or_create(
            source_site=article_source_site,
            source_article_id=draft.source_article_id,
            defaults={
                "source_config": source_config,
                "crawl_job": crawl_job,
                "source_mode": draft.source_mode,
                "racing_region": source_metadata["racing_region"],
                "source_language": source_metadata["source_language"],
                "title_ja": draft.title_ja,
                "body_ja_raw": draft.body_ja_raw,
                "body_ja_normalized": draft.body_ja_normalized,
                "original_content_html": _draft_html(draft),
                "original_author": draft.metadata.get("author", ""),
                "published_at": draft.published_at,
                "published_at_verified": draft_published_verified if has_published_evidence else None,
                "published_at_evidence": draft_published_evidence,
                "source_url": draft.source_url,
                "is_first_crawled": True,
                "first_seen_at": now,
                "last_seen_at": now,
                "crawl_status": CrawlStatus.SUCCESS,
                "status": ArticleStatus.CRAWLED,
                "workflow_status": WorkflowStatus.PENDING_TRANSLATION,
                "source_note": source_config.name if source_config else draft.source_site,
                "translation_metadata": draft_metadata,
                "tags_json": list(source_config.default_tags) if source_config else [],
            },
        )
        if not created:
            source_elevated = _should_elevate_ranked_source(article, draft)
            if _should_update_primary_source(article, draft, source_elevated=source_elevated):
                article.source_mode = draft.source_mode
                article.source_config = source_config or article.source_config
                article.crawl_job = crawl_job or article.crawl_job
                if not article.attribution_locked:
                    article.racing_region = source_metadata["racing_region"]
                article.source_language = source_metadata["source_language"]
                if source_config:
                    article.source_note = source_config.name
            article.title_ja = draft.title_ja or article.title_ja
            article.body_ja_raw = draft.body_ja_raw or article.body_ja_raw
            article.body_ja_normalized = draft.body_ja_normalized or article.body_ja_normalized
            article.original_content_html = _draft_html(draft) or article.original_content_html
            article.original_author = draft.metadata.get("author", article.original_author)
            if not has_published_evidence:
                article.published_at = draft.published_at or article.published_at
            elif draft_published_verified is True and draft.published_at:
                previous_published_at = article.published_at
                evidence = dict(draft_published_evidence)
                if previous_published_at and previous_published_at != draft.published_at:
                    evidence["previous_published_at"] = previous_published_at.isoformat()
                article.published_at = draft.published_at
                article.published_at_verified = True
                article.published_at_evidence = evidence
            elif draft_published_verified is False and article.published_at_verified is not True:
                article.published_at_verified = False
                article.published_at_evidence = draft_published_evidence
            article.source_url = draft.source_url or article.source_url
            article.last_seen_at = now
            article.crawl_status = CrawlStatus.SUCCESS
            article.translation_metadata = {**article.translation_metadata, **draft_metadata}
            article.save()

        NewsSnapshot.objects.create(
            article=article,
            source_site=draft.source_site,
            source_mode=draft.source_mode,
            rank=draft.rank,
            comment_count=draft.comment_count,
            attention_count=draft.attention_count,
            snapshot_metadata=dict(draft_metadata),
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
        apply_article_attribution(
            article,
            source_config=article.source_config,
            is_new_article=created,
            attribution_preview=attribution_preview,
        )
    return ArticleUpsertResult(article=article, created=created, source_elevated=source_elevated)
