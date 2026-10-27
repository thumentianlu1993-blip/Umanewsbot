"""公开快照与已发布来源不可被绕过 service 的 ORM 写覆盖。"""
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase
from stable.models import NewsArticle, NewsPublicationReceipt, NewsPublicEntry, NewsProcessingRun
from stable.test_p01_news_workflow import WorkflowFixture


class ImmutablePublicationTests(WorkflowFixture, TransactionTestCase):
    def test_direct_public_snapshot_and_source_updates_are_rejected(self):
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            self.finish()
        receipt = NewsPublicationReceipt.objects.get(run=self.run)
        mutations = [
            (NewsPublicationReceipt.objects.filter(pk=receipt.pk), {"content": {"body": "未审核"}}),
            (NewsArticle.objects.filter(pk=self.article.pk), {"body_zh": "未审核"}),
            (NewsArticle.objects.filter(pk=self.article.pk), {"body_ja_raw": "重抓覆盖"}),
            (NewsPublicEntry.objects.filter(receipt=receipt), {"sort_time": receipt.published_at.replace(year=2020)}),
            (NewsProcessingRun.objects.filter(pk=self.run.pk), {"source_snapshot": {"title": "替换"}}),
        ]
        for queryset, fields in mutations:
            with self.subTest(model=queryset.model.__name__), self.assertRaises(DatabaseError), transaction.atomic():
                queryset.update(**fields)

    def test_receipt_delete_is_rejected_even_without_dependents(self):
        # SQL 触发器必须防止绕过应用层的删除，不依赖 ORM 的 PROTECT。
        from django.db import connection
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            self.finish()
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM stable_newspublicentry")
