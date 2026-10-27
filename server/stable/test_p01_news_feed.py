"""T12–T15/T32/T33：五区首部与固定水位尾部。"""
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils import timezone
from stable.models import NewsArticle, NewsPublicEntry, NewsFeedSnapshot
from stable.services import news_feed

REGIONS = ("japan", "hong_kong", "united_kingdom", "france", "united_states")


class FeedTests(TransactionTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.seq = 0

    def entry(self, region="japan", priority="regional", age=0):
        self.seq += 1
        when = self.now - timedelta(hours=age)
        article = NewsArticle.objects.create(source_site="jra", source_mode="official", source_article_id=str(self.seq),
            title_ja="原文", title_zh=f"稿件{self.seq}", body_zh="合格全文", summary_zh="列表摘要", published_at=when, source_url="https://fixture.invalid/", racing_region=region,
            workflow_status="published", published_to_web_at=when)
        return NewsPublicEntry.objects.create(feed_seq=self.seq, kind="legacy", article=article, public_revision=str(self.seq),
            sort_time=when, primary_region=region, priority=priority, major_until=when+timedelta(hours=24) if priority=="major" else None)

    def test_regional_round_robin_and_expired_major(self):
        old = self.entry("japan", "major", 25)
        for region in REGIONS:
            self.entry(region)
        major = self.entry("united_states", "major")
        snap = news_feed.create_snapshot(now=self.now)
        self.assertEqual(snap.ordered_entry_ids[0], major.pk)
        rows = list(NewsPublicEntry.objects.filter(pk__in=snap.ordered_entry_ids))
        regions = {row.pk: row.primary_region for row in rows}
        self.assertEqual({regions[pk] for pk in snap.ordered_entry_ids[1:6]}, set(REGIONS))
        self.assertGreater(snap.ordered_entry_ids.index(old.pk), 1)

    def test_tail_remains_accessible_without_duplicates_after_insertion_and_withdrawal(self):
        entries = [self.entry(region) for region in REGIONS for _ in range(4)]
        snap = news_feed.create_snapshot(now=self.now, per_region=2)
        self.assertEqual(len(snap.ordered_entry_ids), 10)
        first = news_feed.snapshot_page(snap.generation, size=3, now=self.now)
        newcomer = self.entry()
        victim = entries[0]
        NewsArticle.objects.filter(pk=victim.article_id).update(workflow_status="withdrawn")
        seen = [row.pk for row in first["entries"]]
        cursor = first["next_cursor"]
        for _ in range(20):
            if not cursor:
                break
            page = news_feed.snapshot_page(snap.generation, cursor=cursor, size=3, now=self.now)
            seen.extend(row.pk for row in page["entries"])
            cursor = page["next_cursor"]
        self.assertEqual(len(seen), len(set(seen)))
        expected = {row.pk for row in entries} - ({victim.pk} if victim.pk not in {row.pk for row in first["entries"]} else set())
        self.assertEqual(set(seen), expected)
        self.assertNotIn(newcomer.pk, seen)

    def test_expired_and_tampered_cursor_fail_closed(self):
        self.entry()
        snap = news_feed.create_snapshot(now=self.now)
        with self.assertRaises(ValueError):
            news_feed.snapshot_page(snap.generation, now=self.now+timedelta(hours=25))
        with self.assertRaises(ValueError):
            news_feed.snapshot_page(snap.generation, cursor="tampered", now=self.now)

    def test_legacy_publication_indexes_atomically_and_rollback_leaves_no_entry(self):
        from django.db import transaction
        article = NewsArticle.objects.create(source_site="jra", source_mode="official", source_article_id="legacy-new",
            title_ja="原文", published_at=self.now, source_url="https://fixture.invalid/")
        with self.settings(NEWS_QUALITY_FEED_ENABLED=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                article.workflow_status = "published"
                article.published_to_web_at = self.now
                article.save(update_fields=["workflow_status", "published_to_web_at"])
                self.assertTrue(NewsPublicEntry.objects.filter(article=article).exists())
                raise RuntimeError("模拟提交前崩溃")
            self.assertFalse(NewsPublicEntry.objects.filter(article=article).exists())
            article.save(update_fields=["workflow_status", "published_to_web_at"])
            entry = NewsPublicEntry.objects.get(article=article)
            article.title_zh = "修复标题"
            article.save(update_fields=["title_zh"])
            self.assertEqual(NewsPublicEntry.objects.filter(article=article).count(), 1)
            self.assertEqual(entry.sort_time, self.now)

    def test_manual_headline_outside_30_day_pool_has_no_implicit_expiry(self):
        from stable.models import HomepageHeadlineSelection
        old = self.entry("france", age=1000)
        self.entry()
        HomepageHeadlineSelection.objects.create(slot="homepage_primary", article=old.article, selected_at=self.now)
        snapshot = news_feed.create_snapshot(now=self.now, with_features=True)
        self.assertEqual(snapshot.headline_entry_id, old.pk)
        self.assertNotIn(old.pk, snapshot.ordered_entry_ids)

    def test_large_japan_supply_cannot_hide_other_regions_or_tail(self):
        articles = []
        for index in range(520):
            articles.append(NewsArticle(source_site="jra", source_mode="official", source_article_id=f"bulk-{index}",
                title_ja="原文", title_zh="合格稿", published_at=self.now, source_url="https://fixture.invalid/",
                racing_region="japan", workflow_status="published", published_to_web_at=self.now))
        NewsArticle.objects.bulk_create(articles)
        NewsPublicEntry.objects.bulk_create([NewsPublicEntry(feed_seq=i+1, kind="legacy", article=row, public_revision=f"bulk-{i}",
            sort_time=self.now, primary_region="japan", priority="regional") for i, row in enumerate(articles)])
        self.seq = 520
        others = [self.entry(region) for region in REGIONS[1:]]
        snapshot = news_feed.create_snapshot(now=self.now)
        self.assertEqual(len(snapshot.ordered_entry_ids), 104)
        self.assertTrue({row.pk for row in others}.issubset(snapshot.ordered_entry_ids[:5]))
        seen, cursor = [], None
        for _ in range(12):
            page = news_feed.snapshot_page(snapshot.generation, cursor=cursor, size=50, now=self.now)
            seen.extend(row.pk for row in page["entries"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(len(seen), 524)
        self.assertEqual(len(set(seen)), 524)

    def test_snapshot_waits_for_publisher_commit_before_capturing_watermark(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from django.db import close_old_connections, transaction
        entered, release = Event(), Event()
        article = NewsArticle.objects.create(source_site="jra", source_mode="official", source_article_id="late-commit",
            title_ja="原文", published_at=self.now, source_url="https://fixture.invalid/", workflow_status="published", published_to_web_at=self.now)
        def publisher():
            close_old_connections()
            try:
                with transaction.atomic():
                    news_feed.publication_lock()
                    entry = news_feed.index_legacy_article(article)
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("test publisher release timeout")
                    return entry.pk
            finally:
                close_old_connections()
        def snapshot():
            close_old_connections()
            try:
                return news_feed.create_snapshot(now=self.now)
            finally:
                close_old_connections()
        with self.settings(NEWS_QUALITY_INDEX_ENABLED=True), ThreadPoolExecutor(max_workers=2) as pool:
            publishing = pool.submit(publisher)
            self.assertTrue(entered.wait(2))
            building = pool.submit(snapshot)
            try:
                self.assertFalse(building.done())
            finally:
                release.set()
            entry_id, snap = publishing.result(timeout=5), building.result(timeout=5)
        self.assertEqual(snap.catalog_watermark, 1)
        self.assertIn(entry_id, snap.ordered_entry_ids)

    def test_archive_cursor_keeps_watermark_after_new_publication(self):
        for _ in range(30):
            self.entry()
        response = self.client.get("/news/archive/")
        self.assertEqual(response.status_code, 200)
        cursor = response.context.get("next_cursor")
        self.assertTrue(cursor, "档案必须返回签名水位 cursor")
        first_ids = {row.public_entry_id for row in response.context["articles"]}
        newcomer = self.entry()
        page = self.client.get("/news/archive/", {"cursor": cursor})
        other_ids = {row.public_entry_id for row in page.context["articles"]}
        self.assertEqual(len(first_ids | other_ids), 30)
        self.assertFalse(first_ids & other_ids)
        self.assertNotIn(newcomer.pk, other_ids)

    def test_manual_headline_can_be_only_eligible_item_outside_recent_pool(self):
        from stable.models import HomepageHeadlineSelection
        old = self.entry("france", age=1000)
        HomepageHeadlineSelection.objects.create(slot="homepage_primary", article=old.article, selected_at=self.now)
        snapshot = news_feed.create_snapshot(now=self.now, with_features=True)
        self.assertEqual(snapshot.headline_entry_id, old.pk)
