"""统一公开索引与可重放分页；序列水位只在发布短事务内分配。"""
from django.db import connection
from django.db.models import Max
from stable.models import NewsPublicEntry

PUBLICATION_LOCK = 910270101


def publication_lock():
    if not connection.in_atomic_block or connection.vendor != "postgresql":
        raise RuntimeError("public_index_requires_postgresql_transaction")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '3s'")
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [PUBLICATION_LOCK])


def append_public_entry(*, article, receipt, now, priority, region):
    from datetime import timedelta
    publication_lock()
    seq = (NewsPublicEntry.objects.aggregate(value=Max("feed_seq"))["value"] or 0) + 1
    return NewsPublicEntry.objects.create(feed_seq=seq, kind="p01", article=article, receipt=receipt,
        public_revision=str(receipt.pk), sort_time=now, primary_region=region, priority=priority,
        major_until=now + timedelta(hours=24) if priority == "major" else None)


from collections import Counter, deque
from datetime import datetime, timedelta
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q, Exists, OuterRef, Case, When, Value, IntegerField
from django.utils import timezone
from stable.models import NewsFeedSnapshot, HomepageHeadlineSelection, RacingRegion

REGIONS = ("japan", "hong_kong", "united_kingdom", "france", "united_states")
CURSOR_SALT = "p01-news-feed-v1"


def visible_entries():
    """撤回即时过滤；P01 只看本回执，永不跟随来源锚点切换到其他稿。"""
    return NewsPublicEntry.objects.filter(
        Q(kind="p01", receipt__visibility="public") |
        Q(kind="legacy", article__workflow_status="published", article__published_to_web_at__isnull=False,
          superseded_at__isnull=True)
    ).select_related("article__cover_media_asset", "receipt")


def homepage_entries():
    rows = visible_entries().filter(superseded_at__isnull=True)
    if getattr(settings, "RACE_NEWS_EXPOSURE_ENABLED", False) and getattr(settings, "RACE_NEWS_HOMEPAGE_MAX", 2) > 0:
        from stable.models import ArticleRaceLink, RaceNewsExposure
        links = ArticleRaceLink.objects.filter(article_id=OuterRef("article_id"), status__in=["auto", "manual"])
        slots = RaceNewsExposure.objects.filter(article_id=OuterRef("article_id"), channel="homepage", scope_key="site", status="active")
        rows = rows.exclude(Q(kind="legacy") & Exists(links) & ~Exists(slots))
    return rows


def regional_slot_seconds(now):
    start = now - timedelta(days=7)
    snapshots = list(NewsFeedSnapshot.objects.filter(cutoff_at__gte=start-timedelta(days=1), cutoff_at__lte=now).order_by("cutoff_at", "id"))
    seconds = Counter()
    for i, snap in enumerate(snapshots):
        end = min(now, snap.expires_at, snapshots[i+1].cutoff_at if i+1 < len(snapshots) else now)
        duration = max(0, (end-max(start, snap.cutoff_at)).total_seconds())
        for region, count in snap.slots_metadata.get("region_slots", {}).items():
            seconds[region] += duration * count
    return dict(seconds)


@transaction.atomic
def create_snapshot(*, now=None, per_region=100, with_features=False):
    from stable.services.news_pipeline import policy_sha
    now = now or timezone.now()
    publication_lock()
    watermark = NewsPublicEntry.objects.aggregate(value=Max("feed_seq"))["value"] or 0
    candidates = homepage_entries().filter(feed_seq__lte=watermark, sort_time__gte=now-timedelta(days=30), sort_time__lte=now)
    rows = []
    for region in REGIONS:
        rows.extend(candidates.filter(primary_region=region).annotate(active_major=Case(When(major_until__gt=now, then=Value(1)), default=Value(0), output_field=IntegerField())).order_by("-active_major", "-sort_time", "-feed_seq")[:min(100, per_region)])
    active_major = sorted((row for row in rows if row.major_until and row.major_until > now), key=lambda row: (row.sort_time, row.feed_seq), reverse=True)
    major_ids = {row.pk for row in active_major}
    queues = {region: deque(row for row in rows if row.primary_region == region and row.pk not in major_ids) for region in REGIONS}
    slots = regional_slot_seconds(now)
    region_order = sorted(REGIONS, key=lambda region: (slots.get(region, 0), REGIONS.index(region)))
    ordered = list(active_major)
    while any(queues.values()):
        for region in region_order:
            if queues[region]:
                ordered.append(queues[region].popleft())
    headline = None
    hot = []
    if with_features and ordered:
        selection = HomepageHeadlineSelection.objects.filter(slot="homepage_primary").first()
        if selection and selection.article_id:
            manual = visible_entries().filter(feed_seq__lte=watermark, sort_time__lte=now)
            manual = manual.filter(receipt_id=selection.receipt_id) if selection.receipt_id else manual.filter(article_id=selection.article_id, kind="legacy")
            headline = manual.order_by("-sort_time", "-feed_seq").first()
            if headline and headline.pk not in {row.pk for row in ordered}:
                ordered = [headline, *ordered[:499]]
        headline = headline or ordered[0]
        # 热门区只取已进入同一首页资格池的稿件，不创建旁路。
        hot = [row for row in active_major if row.pk != headline.pk][:3]
    featured = {row.pk for row in ([headline] if headline else []) + hot}
    return NewsFeedSnapshot.objects.create(policy_sha=policy_sha(), catalog_watermark=watermark, cutoff_at=now,
        ordered_entry_ids=[row.pk for row in ordered if row.pk not in featured],
        headline_entry_id=headline.pk if headline else None, hot_entry_ids=[row.pk for row in hot],
        slots_metadata={"region_slots": dict(Counter(row.primary_region for row in ordered if row.pk not in major_ids)),
                        "all_region_slots": dict(Counter(row.primary_region for row in ordered)), "region_order": region_order},
        expires_at=now+timedelta(hours=24))


def snapshot_page(generation, *, cursor=None, size=12, now=None):
    now = now or timezone.now()
    try:
        snapshot = NewsFeedSnapshot.objects.get(generation=generation, expires_at__gt=now)
        state = signing.loads(cursor, salt=CURSOR_SALT, max_age=86400) if cursor else {"g": str(generation), "head": 0, "tail": None}
        if state.get("g") != str(generation) or not isinstance(state.get("head"), int) or not 0 <= state["head"] <= len(snapshot.ordered_entry_ids):
            raise ValueError("cursor_invalid")
        if state.get("tail") is not None:
            tail_time, tail_seq = state["tail"]
            tail_time = datetime.fromisoformat(tail_time)
            if not isinstance(tail_seq, int) or tail_time.tzinfo is None:
                raise ValueError("cursor_invalid")
    except (NewsFeedSnapshot.DoesNotExist, signing.BadSignature, ValueError, TypeError, KeyError) as error:
        raise ValueError("feed_generation_or_cursor_invalid") from error
    size = max(1, min(50, size))
    ids = snapshot.ordered_entry_ids
    entries = []
    pos = state["head"]
    # 已撤回的原席位直接跳过，不改变原序列；填满页时只消耗本 generation 剩余条目。
    while pos < len(ids) and len(entries) < size:
        take = ids[pos:pos+size-len(entries)]
        by_id = {row.pk: row for row in visible_entries().filter(pk__in=take)}
        entries.extend(by_id[pk] for pk in take if pk in by_id)
        pos += len(take)
    tail = state.get("tail")
    has_more = pos < len(ids)
    if not has_more:
        excluded = ids + snapshot.hot_entry_ids + ([snapshot.headline_entry_id] if snapshot.headline_entry_id else [])
        tail_query = visible_entries().filter(feed_seq__lte=snapshot.catalog_watermark).exclude(pk__in=excluded)
        if tail:
            tail_query = tail_query.filter(Q(sort_time__lt=tail_time) | Q(sort_time=tail_time, feed_seq__lt=tail_seq))
        tail_rows = list(tail_query.order_by("-sort_time", "-feed_seq")[:size-len(entries)+1])
        remaining = size-len(entries)
        chosen = tail_rows[:remaining]
        entries.extend(chosen)
        if chosen:
            tail = [chosen[-1].sort_time.isoformat(), chosen[-1].feed_seq]
        has_more = len(tail_rows) > remaining
    next_cursor = signing.dumps({"g": str(generation), "head": pos, "tail": tail}, salt=CURSOR_SALT, compress=True) if has_more else None
    return {"snapshot": snapshot, "entries": entries, "next_cursor": next_cursor}


@transaction.atomic
def index_legacy_article(article):
    """与旧发布 writer 同事务调用。旧数据仅由显式回填命令建立索引。"""
    if article.active_news_run_id or not getattr(settings, "NEWS_QUALITY_FEED_ENABLED", False):
        return None
    publication_lock()
    if article.workflow_status != "published" or not article.published_to_web_at:
        return None
    revision = article.published_to_web_at.isoformat()
    existing = NewsPublicEntry.objects.filter(kind="legacy", article=article, public_revision=revision).first()
    if existing:
        return existing
    NewsPublicEntry.objects.filter(kind="legacy", article=article, superseded_at__isnull=True).update(superseded_at=timezone.now())
    seq = (NewsPublicEntry.objects.aggregate(value=Max("feed_seq"))["value"] or 0)+1
    return NewsPublicEntry.objects.create(feed_seq=seq, kind="legacy", article=article, public_revision=revision,
        sort_time=article.published_to_web_at, primary_region=article.racing_region, priority="regional")
