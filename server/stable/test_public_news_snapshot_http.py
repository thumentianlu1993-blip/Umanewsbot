"""Direct real Django request/response tests; no network server or public URL."""
from datetime import datetime, timezone
import json
from unittest.mock import patch
from django.core import signing
# Reuse the existing private SQLite setup and actual ORM fixtures, not a runner.
from stable import test_public_news_snapshot_loader as orm_fixture
from django.db import connection, OperationalError
from django.test import RequestFactory, TestCase, override_settings
from stable.models import NewsArticle
from stable.services import public_news_snapshot as core
from stable.services import public_news_snapshot_loader as loader
from stable import public_news_snapshot_http as http


def setUpModule():
    orm_fixture.setUpModule()


def body(response):
    return json.loads(response.content)


@override_settings(RACE_NEWS_EXPOSURE_ENABLED=True, RACE_NEWS_HOMEPAGE_MAX=2)
class SnapshotHTTPTests(TestCase):
    news = orm_fixture.SnapshotLoaderTests.news
    link = orm_fixture.SnapshotLoaderTests.link
    exposure = orm_fixture.SnapshotLoaderTests.exposure

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_envelope_and_signed_cursor_reaches_actual_orm(self):
        for pk in range(7001,7015):self.news(pk)
        with self.assertNumQueries(1):response=http.news_snapshot_list(self.factory.get('/unmounted/q03/news/'))
        result=body(response)
        self.assertEqual(response.status_code,200)
        self.assertEqual(result['api_version'],'1')
        self.assertEqual(set(result),{'api_version','observed_at','results','next_cursor'})
        self.assertEqual(len(result['results']),12)
        self.assertTrue(result['observed_at'].endswith('Z'))
        with self.assertNumQueries(1):second=http.news_snapshot_list(self.factory.get('/unmounted/q03/news/',{'cursor':result['next_cursor']}))
        self.assertEqual([x['id'] for x in body(second)['results']],['7002','7001'])
        self.assertIsNone(body(second)['next_cursor'])

    def test_detail_observed_clock_does_not_change_item_version(self):
        self.news(1)
        clocks=[datetime(2026,10,14,3,0,tzinfo=timezone.utc),datetime(2026,10,14,3,1,tzinfo=timezone.utc)]
        with patch('stable.public_news_snapshot_http.datetime') as clock:
            clock.now.side_effect=clocks
            first=http.news_snapshot_detail(self.factory.get('/unmounted/q03/news/1/'),'1')
            second=http.news_snapshot_detail(self.factory.get('/unmounted/q03/news/1/'),'1')
        a,b=body(first),body(second)
        self.assertEqual(set(a),{'api_version','observed_at','result'})
        self.assertEqual(a['api_version'],'1')
        self.assertEqual(a['observed_at'],'2026-10-14T03:00:00.000000Z')
        self.assertEqual(b['observed_at'],'2026-10-14T03:01:00.000000Z')
        self.assertEqual(a['result'],b['result'])
        self.assertEqual(a['result']['summary'],'')

    def test_empty_is_200_not_unavailable_or_not_found(self):
        with self.assertNumQueries(1):response=http.news_snapshot_list(self.factory.get('/unmounted/q03/news/'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(body(response)['results'],[])
        self.assertIsNone(body(response)['next_cursor'])

    def test_missing_withdrawn_and_missing_web_time_identical_404(self):
        self.news(1,workflow_status='withdrawn');self.news(2,published_to_web_at=None)
        for pk in ['1','2','9999']:
            with self.subTest(pk=pk),self.assertNumQueries(1):
                response=http.news_snapshot_detail(self.factory.get('/unmounted/q03/news/'+pk+'/'),pk)
            self.assertEqual(response.status_code,404)
            self.assertEqual(body(response),{'error':{'code':'not_found'}})

    def test_bad_list_parameters_and_bad_cursor_are_400_before_sql(self):
        wrong=signing.dumps({'version':1,'scope':'horses','upper':[],'after':[]},salt=core.CURSOR_SALT)
        for query,code in [({'page':'1'},'invalid_request'),({'cursor':'tampered'},'invalid_cursor'),({'cursor':wrong},'invalid_cursor')]:
            with self.subTest(query=query),self.assertNumQueries(0):
                response=http.news_snapshot_list(self.factory.get('/unmounted/q03/news/',query))
            self.assertEqual(response.status_code,400);self.assertEqual(body(response),{'error':{'code':code}})

    def test_bad_detail_id_or_query_is_400_before_sql(self):
        for pk,query in [('01',{}),('0',{}),('1',{'workflow_status':'published'}),('1',{'cursor':'x'})]:
            with self.subTest(pk=pk,query=query),self.assertNumQueries(0):
                response=http.news_snapshot_detail(self.factory.get('/unmounted/q03/news/'+pk+'/',query),pk)
            self.assertEqual(response.status_code,400)
            self.assertEqual(body(response),{'error':{'code':'invalid_request'}})

    def test_non_get_is_405_allow_get_without_database_access(self):
        for method in ['post','put','patch','delete','head','options']:
            for detail in [False,True]:
                with self.subTest(method=method,detail=detail),self.assertNumQueries(0):
                    request=getattr(self.factory,method)('/unmounted/q03/news/')
                    response=http.news_snapshot_detail(request,'1') if detail else http.news_snapshot_list(request)
                self.assertEqual(response.status_code,405);self.assertEqual(response['Allow'],'GET')
                self.assertEqual(body(response),{'error':{'code':'method_not_allowed'}})

    def test_injected_database_read_failure_is_sanitized_503(self):
        self.news(1)
        def fault(execute,sql,parameters,many,context):
            if 'stable_newsarticle' in sql and sql.lstrip().upper().startswith('SELECT'):
                raise OperationalError('C146_INJECTED_SQL_PASSWORD_DO_NOT_LEAK')
            return execute(sql,parameters,many,context)
        for detail in [False,True]:
            with self.subTest(detail=detail),connection.execute_wrapper(fault):
                request=self.factory.get('/unmounted/q03/news/')
                response=http.news_snapshot_detail(request,'1') if detail else http.news_snapshot_list(request)
            self.assertEqual(response.status_code,503)
            self.assertEqual(body(response),{'error':{'code':'service_unavailable'}})
            self.assertNotIn(b'C146_INJECTED',response.content)

    def test_injected_projection_damage_after_sql_is_sanitized_503(self):
        self.news(1)
        for detail in [False,True]:
            target=loader if detail else core
            with self.subTest(detail=detail),patch.object(target,'project_news',side_effect=core.SnapshotDataError('C146_INJECTED_WINDOW_SQL_SECRET')):
                with self.assertNumQueries(1):
                    request=self.factory.get('/unmounted/q03/news/')
                    response=http.news_snapshot_detail(request,'1') if detail else http.news_snapshot_list(request)
            self.assertEqual(response.status_code,503)
            self.assertEqual(body(response),{'error':{'code':'service_unavailable'}})
            self.assertNotIn(b'C146_INJECTED',response.content)

    def test_homepage_exclusion_and_if_none_match_do_not_claim_conditional_get(self):
        a=self.news(1);self.link(a)
        self.assertEqual(body(http.news_snapshot_list(self.factory.get('/unmounted/q03/news/')))['results'],[])
        first=http.news_snapshot_detail(self.factory.get('/unmounted/q03/news/1/'),'1')
        version=body(first)['result']['version']
        request=self.factory.get('/unmounted/q03/news/1/',HTTP_IF_NONE_MATCH='"'+version+'"')
        response=http.news_snapshot_detail(request,'1')
        self.assertEqual(response.status_code,200);self.assertNotIn('ETag',response)
        NewsArticle.objects.filter(pk=1).update(workflow_status='withdrawn')
        hidden=http.news_snapshot_detail(request,'1')
        self.assertEqual(hidden.status_code,404)
        self.assertEqual(body(hidden),{'error':{'code':'not_found'}})
