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


def create_snapshot(*, now=None, per_region=100):
    from stable.models import NewsFeedSnapshot
    from django.utils import timezone
    from datetime import timedelta
    now = now or timezone.now()
    return NewsFeedSnapshot.objects.create(expires_at=now+timedelta(hours=24))


def snapshot_page(generation, *, cursor=None, size=12, now=None):
    return {"entries": [], "next_cursor": None}
