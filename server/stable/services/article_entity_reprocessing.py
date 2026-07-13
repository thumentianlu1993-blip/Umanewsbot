from __future__ import annotations

from typing import Iterable

from django.db import transaction

from stable.models import NewsArticle, OperationLog, SourceLanguage, TermEntry, TermType
from stable.services.horse_profiles import reconcile_article_horse_links
from stable.services.terms import ArticleEntityResolution, resolve_article_entities
from stable.tasks import translate_article_task


def _source_default_tags(article: NewsArticle) -> list[str]:
    if not article.source_config_id:
        return []
    return list(article.source_config.default_tags or [])


def _tag_plan(article: NewsArticle, resolution: ArticleEntityResolution) -> dict[str, list[str] | bool]:
    current = list(dict.fromkeys(tag.strip() for tag in (article.tags_json or []) if tag and tag.strip()))
    machine_tags = list(resolution.machine_horse_tags)
    defaults = set(_source_default_tags(article))
    if "tags_json" in set(article.manually_edited_fields or []):
        return {
            "locked": True,
            "before": current,
            "after": current,
            "add": [],
            "delete": [],
        }
    previous_machine = set((article.translation_metadata or {}).get("machine_horse_tags") or [])
    active_horse_targets = set(
        TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE, target_zh__in=current)
        .exclude(target_zh="")
        .values_list("target_zh", flat=True)
    )
    # Explicit reprocessing owns all unlocked horse-term tags on the selected
    # article.  Always include active horse targets: an interrupted/older run
    # may already have written incomplete provenance while leaving legacy tags.
    legacy_candidates = previous_machine | active_horse_targets
    delete = [tag for tag in current if tag in legacy_candidates and tag not in machine_tags and tag not in defaults]
    after = [tag for tag in current if tag not in delete]
    for tag in [*_source_default_tags(article), *machine_tags]:
        if tag and tag not in after:
            after.append(tag)
    return {
        "locked": False,
        "before": current,
        "after": after,
        "add": [tag for tag in after if tag not in current],
        "delete": delete,
    }


def build_article_entity_reprocess_plan(
    article: NewsArticle,
    *,
    resolution: ArticleEntityResolution | None = None,
) -> dict:
    resolution = resolution or resolve_article_entities(
        article.title_ja,
        article.body_ja_normalized or article.body_ja_raw,
        source_language=article.source_language or SourceLanguage.JAPANESE,
    )
    return {
        "article_id": article.id,
        "entities": resolution.as_dict(),
        "terms": [item.__dict__ for item in resolution.accepted_terms],
        "tags": _tag_plan(article, resolution),
        "links": reconcile_article_horse_links(article, resolution, commit=False),
    }


def _commit_article(article_id: int, *, translate_sync: bool) -> dict:
    with transaction.atomic():
        article = NewsArticle.objects.select_for_update().get(pk=article_id)
        before_public = {
            "id": article.id,
            "workflow_status": article.workflow_status,
            "published_to_web_at": article.published_to_web_at,
            "qq_delivery_count": article.qq_push_deliveries.count(),
        }
        pre_translation_resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        pre_translation_tag_plan = _tag_plan(article, pre_translation_resolution)
        if translate_sync:
            translate_article_task.run(article.id, force=True, suppress_automation=True)
            article.refresh_from_db()
        resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        tag_plan = pre_translation_tag_plan if translate_sync else _tag_plan(article, resolution)
        if not tag_plan["locked"]:
            article.tags_json = tag_plan["after"]
        metadata = dict(article.translation_metadata or {})
        metadata["machine_horse_tags"] = list(resolution.machine_horse_tags)
        metadata["article_entity_resolution"] = resolution.as_dict()
        article.translation_metadata = metadata
        article.save(update_fields=["tags_json", "translation_metadata", "updated_at"])
        link_plan = reconcile_article_horse_links(article, resolution, commit=True)
        after_public = {
            "id": article.id,
            "workflow_status": article.workflow_status,
            "published_to_web_at": article.published_to_web_at,
            "qq_delivery_count": article.qq_push_deliveries.count(),
        }
        if before_public != after_public:
            raise RuntimeError(f"public identity changed: before={before_public} after={after_public}")
        OperationLog.objects.create(
            action_type="article_entities_reprocessed",
            target_type="news_article",
            target_id=str(article.id),
            detail=(
                f"tags_add={tag_plan['add']} tags_delete={tag_plan['delete']} "
                f"links_create={len(link_plan['create'])} links_update={len(link_plan['update'])} "
                f"links_delete={link_plan['delete_ids']} translate_sync={translate_sync}"
            ),
        )
        return {
            "article_id": article.id,
            "status": "committed",
            "entities": resolution.as_dict(),
            "terms": [item.__dict__ for item in resolution.accepted_terms],
            "tags": tag_plan,
            "links": link_plan,
        }


def reprocess_article_entities(
    article_ids: Iterable[int],
    *,
    commit: bool = False,
    translate_sync: bool = False,
) -> dict:
    ids = list(dict.fromkeys(int(article_id) for article_id in article_ids))
    results: list[dict] = []
    if not commit:
        articles = NewsArticle.objects.filter(id__in=ids).select_related("source_config")
        by_id = {article.id: article for article in articles}
        for article_id in ids:
            article = by_id.get(article_id)
            if article is None:
                results.append({"article_id": article_id, "status": "failed", "error": "article not found"})
                continue
            results.append({"status": "dry_run", **build_article_entity_reprocess_plan(article)})
        return {"mode": "dry_run", "article_ids": ids, "articles": results}

    for article_id in ids:
        try:
            results.append(_commit_article(article_id, translate_sync=translate_sync))
        except Exception as exc:
            OperationLog.objects.create(
                action_type="article_entities_reprocess_failed",
                target_type="news_article",
                target_id=str(article_id),
                detail=str(exc),
            )
            results.append({"article_id": article_id, "status": "failed", "error": str(exc)})
    return {"mode": "commit", "article_ids": ids, "articles": results}
