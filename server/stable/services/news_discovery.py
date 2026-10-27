"""复用现有抓取频率，在详情解析之前保存候选和来源窗口。"""
from django.conf import settings
from stable.models import NewsDiscoveryObservation
from stable.services.news_pipeline import digest, source_snapshot


def enabled(source):
    return bool(source and source.enabled and source.production_approved and not source.deleted_at
        and getattr(settings, "NEWS_QUALITY_MODE", "off") in {"shadow", "enforce"}
        and source.pk in getattr(settings, "NEWS_QUALITY_POLICY", {}).get("source_ids", []))


def item_key(item):
    return digest({"item": item.source_article_id or item.source_url})


def discover_listing(adapter, source, job, mode, window):
    if not enabled(source):
        return adapter.fetch_listing(mode, window)
    observation, _ = NewsDiscoveryObservation.objects.get_or_create(
        crawl_job=job, kind="source_window", item_key=digest({"mode": str(mode), "window": str(window)}),
        defaults={"source": source, "primary_region": source.racing_region, "stage": "listing"},
    )
    try:
        stubs = adapter.fetch_listing(mode, window)
        for stub in stubs:
            metadata = stub.metadata or {}
            NewsDiscoveryObservation.objects.get_or_create(
                crawl_job=job, kind="stub", item_key=item_key(stub), defaults={
                    "source": source, "primary_region": source.racing_region,
                    "source_snapshot": {"source_id": stub.source_article_id, "url": stub.source_url, "title": stub.title_ja},
                    "source_time_evidence": {"verified": metadata.get("published_at_verified"),
                        "source_time": stub.published_at.isoformat() if stub.published_at and metadata.get("published_at_verified") is True else None,
                        "evidence": metadata.get("published_at_evidence", {})},
                },
            )
    except Exception as error:
        observation.outcome, observation.reason = "failed", type(error).__name__
        observation.save(update_fields=["outcome", "reason"])
        raise
    observation.outcome = "ok" if stubs else "empty"
    observation.source_snapshot = {"stub_count": len(stubs),
        "query_failure_count": len(getattr(adapter, "last_listing_query_errors", []) or [])}
    observation.save(update_fields=["outcome", "source_snapshot"])
    return stubs


def record_failure(job, stub, error):
    NewsDiscoveryObservation.objects.filter(crawl_job=job, kind="stub", item_key=item_key(stub)).update(
        stage="detail", outcome="failed", reason=type(error).__name__,
    )


def fetch_discovered_detail(adapter, job, stub, lookup):
    try:
        return adapter.fetch_detail(lookup)
    except Exception as error:
        record_failure(job, stub, error)
        raise


def record_ingested(job, draft, article):
    if job is None:
        return
    NewsDiscoveryObservation.objects.filter(crawl_job=job, kind="stub", item_key=item_key(draft)).update(
        stage="ingested", outcome="ok", article=article, run_id=article.active_news_run_id,
        source_snapshot=source_snapshot(article, draft),
        source_time_evidence={"verified": draft.metadata.get("published_at_verified"),
                              "evidence": draft.metadata.get("published_at_evidence", {})},
    )
