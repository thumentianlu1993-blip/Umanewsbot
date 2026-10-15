"""Real synthetic ORM reads on private migrated SQLite; not PostgreSQL proof."""
from datetime import datetime, timedelta, timezone
import atexit
import importlib
from pathlib import Path
import tempfile
from django.conf import settings

STANDALONE = not settings.configured
if STANDALONE:
    from django.apps import AppConfig
    _temporary = tempfile.TemporaryDirectory(prefix='c145-sqlite-', dir=str(Path(__file__).resolve().parents[3]))
    settings.configure(
        SECRET_KEY='C145_SYNTHETIC_TEST_ONLY', SECRET_KEY_FALLBACKS=[],
        INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth',
                        AppConfig('stable', importlib.import_module('stable'))],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3',
                              'NAME': str(Path(_temporary.name)/'synthetic.sqlite3')}},
        USE_TZ=True, TIME_ZONE='UTC', DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
    )
    import django
    django.setup()
    def _cleanup():
        from django.db import connections
        connections.close_all()
        _temporary.cleanup()
    atexit.register(_cleanup)

from django.core import signing
from django.db import connection
from django.http import QueryDict
from django.test import TestCase, override_settings
from stable.models import NewsArticle, RaceEvent, ArticleRaceLink, RaceNewsExposure
from stable.services import public_news_snapshot as core
from stable.services import public_news_snapshot_loader as loader

STAMP = datetime(2026,10,14,2,0,59,987650,tzinfo=timezone.utc)


def setUpModule():
    if STANDALONE:
        from django.core.management import call_command
        call_command('migrate', interactive=False, verbosity=0)


def params(token=None):
    query = QueryDict('', mutable=True)
    if token is not None: query['cursor'] = token
    return query


@override_settings(RACE_NEWS_EXPOSURE_ENABLED=True, RACE_NEWS_HOMEPAGE_MAX=2)
class SnapshotLoaderTests(TestCase):
    def news(self, pk, **changes):
        values = dict(id=pk, source_site='jra', source_article_id=f'synthetic-{pk}',
                      title_ja='Synthetic test', title_zh='合成公开标题',
                      summary_zh='', manually_edited_fields=['summary_zh'],
                      published_at=STAMP, published_to_web_at=STAMP,
                      workflow_status='published', public_slug=f'synthetic-{pk}')
        values.update(changes)
        return NewsArticle.objects.create(**values)

    def link(self, article, status='auto', visibility='published'):
        event = RaceEvent.objects.create(year=2026, slug=f'synthetic-{article.pk}',
            chinese_name='合成赛事', original_name='Synthetic race', country_region='japan',
            racecourse='Synthetic course', grade_text='G1', surface='turf',
            visibility_status=visibility, source_refs={'synthetic_test': True})
        ArticleRaceLink.objects.create(article=article, event=event, status=status)
        return event

    def exposure(self, article, event, **changes):
        values = dict(article=article,event=event,channel='homepage',scope_key='site',slot=1,status='active')
        values.update(changes)
        return RaceNewsExposure.objects.create(**values)

    def ids(self):
        with self.assertNumQueries(1): page = loader.load_news_page(params())
        return [item['id'] for item in page.results]

    def test_current_visibility_order_empty_and_single_limited_select(self):
        self.news(1); self.news(2,published_to_web_at=STAMP+timedelta(microseconds=1))
        self.news(3,workflow_status='withdrawn');self.news(4,published_to_web_at=None)
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as capture: page=loader.load_news_page(params())
        self.assertEqual([x['id'] for x in page.results],['2','1'])
        self.assertEqual(len(capture),1)
        sql=capture[0]['sql'].upper()
        self.assertIn('LIMIT 13',sql);self.assertIn('ORDER BY',sql);self.assertNotIn('COUNT(',sql)
        NewsArticle.objects.filter(pk__in=[1,2]).update(workflow_status='withdrawn')
        with self.assertNumQueries(1): empty=loader.load_news_page(params())
        self.assertEqual(empty.results,());self.assertIsNone(empty.next_cursor)

    def test_homepage_site_active_and_link_status_exact_eligibility(self):
        self.news(1)
        for pk,status in [(2,'auto'),(3,'manual'),(4,'candidate'),(5,'removed'),
                          (6,'auto'),(7,'auto'),(8,'auto'),(9,'auto'),(10,'auto')]:
            a=self.news(pk);event=self.link(a,status,visibility='draft')
            if pk==6:self.exposure(a,event)
            if pk==7:self.exposure(a,event,status='waiting')
            if pk==8:self.exposure(a,event,channel='qq')
            if pk==9:self.exposure(a,event,scope_key='target:1')
            if pk==10:self.exposure(a,event,status='replaced')
        self.assertEqual(self.ids(),['6','5','4','1'])

    def test_disabled_policy_and_nonpositive_max_preserve_public_articles(self):
        a=self.news(1);self.link(a)
        for enabled,maximum in [(False,2),(True,0),(True,-1)]:
            with self.subTest(enabled=enabled,maximum=maximum),override_settings(
                RACE_NEWS_EXPOSURE_ENABLED=enabled,RACE_NEWS_HOMEPAGE_MAX=maximum):
                self.assertEqual(self.ids(),['1'])

    def test_detail_ignores_homepage_exposure_and_rechecks_hidden(self):
        a=self.news(1);self.link(a)
        self.assertEqual(self.ids(),[])
        with self.assertNumQueries(1): item=loader.load_news_detail('1')
        self.assertEqual(item['id'],'1')
        NewsArticle.objects.filter(pk=1).update(workflow_status='withdrawn')
        self.news(2,published_to_web_at=None)
        for pk in ['1','2','9999']:
            with self.subTest(pk=pk),self.assertNumQueries(1),self.assertRaises(core.NewsNotFound):
                loader.load_news_detail(pk)

    def test_bad_parameters_cursor_and_id_reject_before_sql(self):
        wrong=signing.dumps({'version':1,'scope':'horses','upper':[],'after':[]},salt=core.CURSOR_SALT)
        for query in [QueryDict('page=1'),params('bad-signature'),params(wrong),QueryDict('cursor=a&cursor=b')]:
            with self.subTest(query=query),self.assertNumQueries(0),self.assertRaises(core.InvalidRequest):
                loader.load_news_page(query)
        with self.assertNumQueries(0),self.assertRaises(core.InvalidRequest):loader.load_news_detail('01')

    def test_sql_twelve_plus_one_keyset_and_new_above_upper_excluded(self):
        for pk in range(7001,7015):self.news(pk)
        with self.assertNumQueries(1):first=loader.load_news_page(params())
        self.assertEqual([x['id'] for x in first.results],[str(x) for x in range(7014,7002,-1)])
        self.assertIsNotNone(first.next_cursor)
        self.news(8000,published_to_web_at=STAMP+timedelta(microseconds=1))
        with self.assertNumQueries(1):second=loader.load_news_page(params(first.next_cursor))
        self.assertEqual([x['id'] for x in second.results],['7002','7001'])
        self.assertIsNone(second.next_cursor)

    def test_sql_original_microseconds_and_strict_id_tie_boundaries(self):
        self.news(9001,published_to_web_at=STAMP+timedelta(microseconds=2))
        self.news(9003,published_to_web_at=STAMP+timedelta(microseconds=1))
        self.news(9002,published_to_web_at=STAMP+timedelta(microseconds=1))
        self.news(9004,published_to_web_at=STAMP+timedelta(microseconds=1))
        self.news(9999,published_to_web_at=STAMP+timedelta(microseconds=3))
        token=core.encode_cursor(core.CursorBoundary(
            (STAMP+timedelta(microseconds=2),9001),(STAMP+timedelta(microseconds=1),9003)))
        with self.assertNumQueries(1):page=loader.load_news_page(params(token))
        self.assertEqual([x['id'] for x in page.results],['9002'])
        self.assertEqual(page.results[0]['published_at'],'2026-10-14T02:00:00Z')

    def test_exposure_changes_are_current_eligibility_not_detail_withdrawal(self):
        a=self.news(1);event=self.link(a);slot=self.exposure(a,event)
        self.assertEqual(self.ids(),['1'])
        RaceNewsExposure.objects.filter(pk=slot.pk).update(status='waiting')
        self.assertEqual(self.ids(),[])
        with self.assertNumQueries(1):self.assertEqual(loader.load_news_detail('1')['id'],'1')
