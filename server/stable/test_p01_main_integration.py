"""P01接入当前主线后的迁移与关闭态兼容性；仅隔离testDB。"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.core.management import call_command
from django.utils import timezone
from stable.models import NewsArticle, NewsProcessingRun


@override_settings(NEWS_QUALITY_MODE='off', NEWS_QUALITY_FEED_ENABLED=False)
class P01MainMigrationTests(TransactionTestCase):
    def test_existing_article_survives_main_to_p01_migration(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        executor=MigrationExecutor(connection)
        leaves=executor.loader.graph.leaf_nodes('stable')
        self.assertEqual(leaves,[('stable','0088_p01_sealed_evidence')])
        article=NewsArticle.objects.create(title_ja='原有新闻',body_ja_raw='正文保持',source_article_id='pre-p01',source_url='https://fixture.invalid/prior',published_at=timezone.now())
        try:
            executor.migrate([('stable','0085_merge_us_divisions')])
            old=executor.loader.project_state([('stable','0085_merge_us_divisions')]).apps.get_model('stable','NewsArticle')
            self.assertEqual(old.objects.get(pk=article.pk).body_ja_raw,'正文保持')
            self.assertNotIn(NewsProcessingRun._meta.db_table,connection.introspection.table_names())
        finally:
            MigrationExecutor(connection).migrate(leaves)
        article.refresh_from_db()
        self.assertEqual(article.body_ja_raw,'正文保持')
        self.assertIsNone(article.active_news_run_id)
        self.assertEqual(article.news_generation,0)
        self.assertEqual(NewsProcessingRun.objects.count(),0)
        old=MigrationExecutor(connection).loader.project_state([('stable','0085_merge_us_divisions')]).apps.get_model('stable','NewsArticle')
        old.objects.create(title_ja='旧应用回滚写入',source_article_id='old-writer',source_url='https://fixture.invalid/rollback',published_at=timezone.now())
        self.assertEqual(NewsArticle.objects.get(source_url='https://fixture.invalid/rollback').news_generation,0)
        call_command('makemigrations', check=True, dry_run=True, verbosity=0)
