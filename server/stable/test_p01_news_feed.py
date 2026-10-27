"""T12–T15/T32/T33：五区首部与固定水位尾部。"""
from datetime import timedelta
from django.test import TransactionTestCase
from django.utils import timezone
from stable.models import NewsArticle, NewsPublicEntry, NewsFeedSnapshot
from stable.services import news_feed

REGIONS = ("japan", "hong_kong", "uk", "france", "usa")


class FeedTests(TransactionTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.seq = 0

    def entry(self, region="japan", priority="regional", age=0):
        self.seq += 1
        when = self.now - timedelta(hours=age)
        article = NewsArticle.objects.create(source_site="jra", source_mode="official", source_article_id=str(self.seq),
            title_ja="原文", title_zh=f"稿件{self.seq}", published_at=when, source_url="https://fixture.invalid/", racing_region=region,
            workflow_status="published", published_to_web_at=when)
        return NewsPublicEntry.objects.create(feed_seq=self.seq, kind="legacy", article=article, public_revision=str(self.seq),
            sort_time=when, primary_region=region, priority=priority, major_until=when+timedelta(hours=24) if priority=="major" else None)

    def test_regional_round_robin_and_expired_major(self):
        old = self.entry("japan", "major", 25)
        for region in REGIONS:
            self.entry(region)
        major = self.entry("usa", "major")
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
