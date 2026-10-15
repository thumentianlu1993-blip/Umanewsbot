"""No-DB semantic tests, runnable in the existing Django venv via unittest."""
from datetime import datetime, timedelta, timezone
import importlib
from unittest.mock import patch
from django.conf import settings

if not settings.configured:
    from django.apps import AppConfig
    settings.configure(
        SECRET_KEY='C144_TEST_ONLY_NOT_AUTHORITY', SECRET_KEY_FALLBACKS=[],
        INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth',
                        AppConfig('stable', importlib.import_module('stable'))],
        DATABASES={}, USE_TZ=True, TIME_ZONE='UTC',
        DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
    )
    import django
    django.setup()

from django.core import signing
from django.http import QueryDict
from django.test import SimpleTestCase
from stable.models import NewsArticle, WorkflowStatus
from stable.services import public_news_snapshot as core

UTC = timezone.utc
STAMP = datetime(2026, 10, 14, 10, 0, 59, 987654,
                 tzinfo=timezone(timedelta(hours=8)))

def article(pk=7001, **changes):
    values = dict(id=pk, title_zh='手工', rewrite_title_zh='重写',
                  summary_zh='', rewrite_summary_zh='自动摘要',
                  manually_edited_fields=['title_zh', 'summary_zh'],
                  workflow_status=WorkflowStatus.PUBLISHED,
                  published_to_web_at=STAMP)
    values.update(changes)
    return NewsArticle(**values)  # Never saved; existing real model properties.

def payload(upper=None, after=None, **changes):
    value = dict(version=1, scope='news-feed',
                 upper=upper or ['2026-10-14T02:00:59.987654Z', 7001],
                 after=after or ['2026-10-14T02:00:59.987654Z', 6990])
    value.update(changes)
    return signing.dumps(value, salt=core.CURSOR_SALT)

class ProjectionTests(SimpleTestCase):
    def test_manual_title_and_empty_summary_exact_public_fields_and_fixed_version(self):
        result = core.project_news(article())
        self.assertEqual(result, dict(id='7001', title='手工', summary='',
            public_path='/news/7001/', published_at='2026-10-14T02:00:00Z',
            version='news-v1-17030928cc65ce6d0e537b35b4546ad3bba9774569e5a093be94dfac6f840fe5'))

    def test_empty_manual_title_falls_back_and_summary_is_not_card_truncated(self):
        result = core.project_news(article(title_zh='', summary_zh='摘'*140,
                                         manually_edited_fields=['title_zh']))
        self.assertEqual(result['title'], '重写')
        self.assertEqual(result['summary'], '自动摘要')
        result = core.project_news(article(summary_zh='摘'*140,
                                          rewrite_summary_zh='', manually_edited_fields=[]))
        self.assertEqual(result['summary'], '摘'*140)

    def test_real_model_body_summary_fallback_is_preserved(self):
        result = core.project_news(article(manually_edited_fields=[],
                    rewrite_summary_zh='', body_zh='正文'*100))
        self.assertEqual(result['summary'], ('正文'*100)[:180])

    def test_internal_updates_and_subminute_sort_changes_do_not_change_version(self):
        a = article(); first = core.project_news(a)
        a.score_total = 100; a.translation_error_message = 'INTERNAL_NOT_PUBLIC'
        a.updated_at = datetime(2030, 1, 1, tzinfo=UTC)
        a.published_to_web_at = STAMP.replace(second=1, microsecond=0)
        self.assertEqual(core.project_news(a), first)
        self.assertNotEqual(core.article_order_key(a), core.article_order_key(article()))

    def test_visible_correction_changes_version_without_changing_id(self):
        old = core.project_news(article()); new = core.project_news(article(title_zh='更正标题'))
        self.assertEqual(old['id'], new['id'])
        self.assertNotEqual(old['version'], new['version'])

    def test_unpublished_missing_web_time_and_hidden_are_same_not_found(self):
        for values in [dict(workflow_status=WorkflowStatus.WITHDRAWN),
                       dict(workflow_status=WorkflowStatus.PENDING_REVIEW),
                       dict(published_to_web_at=None)]:
            with self.subTest(values=values), self.assertRaises(core.NewsNotFound):
                core.project_news(article(**values))

    def test_visibility_checked_before_reading_or_comparing_content(self):
        class Hidden:
            workflow_status = WorkflowStatus.WITHDRAWN
            published_to_web_at = STAMP
            @property
            def effective_title(self):
                raise AssertionError('hidden content accessed before visibility')
        with self.assertRaises(core.NewsNotFound): core.project_news(Hidden())

    def test_naive_source_timestamp_is_data_error_not_empty_success(self):
        with self.assertRaises(core.SnapshotDataError):
            core.project_news(article(published_to_web_at=STAMP.replace(tzinfo=None)))

class InputCursorTests(SimpleTestCase):
    def test_id_canonical_positive_int64_string_only(self):
        self.assertEqual(core.parse_news_id('7001'), 7001)
        for value in ['0', '-1', '01', '+1', '１', ' 1', '1.0', str(2**63), '', None, True, 1]:
            with self.subTest(value=value), self.assertRaises(core.InvalidRequest):
                core.parse_news_id(value)

    def test_single_supported_parameter_only(self):
        self.assertIsNone(core.parse_snapshot_params(QueryDict('')))
        for query in ['cursor=', 'cursor=a&cursor=b', 'workflow_status=published', 'page=1', 'offset=0']:
            with self.subTest(query=query), self.assertRaises(core.InvalidRequest):
                core.parse_snapshot_params(QueryDict(query))

    def test_signed_roundtrip_utc_precision_and_parameter_decode(self):
        boundary = core.CursorBoundary((STAMP, 7001), (STAMP, 6990))
        token = core.encode_cursor(boundary)
        self.assertEqual(core.decode_cursor(token), boundary)
        query = QueryDict('', mutable=True); query['cursor'] = token
        self.assertEqual(core.parse_snapshot_params(query), boundary)
        decoded = signing.loads(token, salt=core.CURSOR_SALT)
        self.assertEqual(decoded['upper'], ['2026-10-14T02:00:59.987654Z', 7001])

    def test_signed_wrong_scope_version_schema_and_boundary_are_rejected(self):
        bad = [dict(scope='horses'), dict(version=2), dict(version=True),
               dict(extra='not accepted'), dict(upper=['2026-10-14T02:00:59', 7001]),
               dict(after=['2026-10-14T02:00:59.987654Z', True]),
               dict(after=['2026-10-14T02:01:00.000000Z', 1])]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(core.InvalidRequest) as err:
                core.decode_cursor(payload(**changes))
            self.assertEqual(err.exception.code, 'invalid_cursor')

    def test_unsigned_tampered_wrong_salt_and_size_are_invalid_cursor(self):
        token = payload()
        for value in [token[:-1], token+'x', '{"scope":"news-feed"}',
                      signing.dumps({'version':1}, salt='other'), 'x'*2049, None, '雪']:
            with self.subTest(value=value), self.assertRaises(core.InvalidRequest) as err:
                core.decode_cursor(value)
            self.assertEqual(err.exception.code, 'invalid_cursor')

    def test_cursor_has_no_unapproved_age_expiry(self):
        with patch('django.core.signing.time.time', return_value=1): token = payload()
        self.assertEqual(core.decode_cursor(token).after[1], 6990)

    def test_original_precision_upper_inclusive_after_strict(self):
        boundary = core.CursorBoundary((STAMP, 7001), (STAMP, 6990))
        self.assertFalse(boundary.allows((STAMP, 6990)))
        self.assertTrue(boundary.allows((STAMP, 6989)))
        self.assertFalse(boundary.allows((STAMP+timedelta(microseconds=1), 1)))
        self.assertTrue(boundary.allows((STAMP-timedelta(microseconds=1), 9999)))

class PageTests(SimpleTestCase):
    def test_twelve_plus_one_and_preserved_upper_for_next_page(self):
        rows = [article(pk) for pk in range(7020, 7006, -1)]
        first = core.build_snapshot_page(iter(rows))
        self.assertEqual([x['id'] for x in first.results], [str(i) for i in range(7020,7008,-1)])
        boundary = core.decode_cursor(first.next_cursor)
        self.assertEqual(boundary.upper, core.article_order_key(rows[0]))
        self.assertEqual(boundary.after[1], 7009)
        candidates = [article(8000), *rows]
        second = core.build_snapshot_page((x for x in candidates if boundary.allows(core.article_order_key(x))), boundary=boundary)
        self.assertEqual([x['id'] for x in second.results], ['7008','7007'])
        self.assertIsNone(second.next_cursor)

    def test_empty_result_and_bounded_thirteen_row_consumption(self):
        empty = core.build_snapshot_page(iter(()))
        self.assertEqual(empty.results, ()); self.assertIsNone(empty.next_cursor)
        def limited():
            for pk in range(20,7,-1): yield article(pk)
            raise AssertionError('read beyond twelve plus one window')
        self.assertEqual(len(core.build_snapshot_page(limited()).results), 12)

    def test_source_window_must_be_public_strictly_ordered_and_in_bounds(self):
        boundary = core.CursorBoundary((STAMP,7001),(STAMP,6990))
        bad_windows = [[article(1),article(2)], [article(1),article(1)],
                       [article(1,workflow_status=WorkflowStatus.WITHDRAWN)]]
        for rows in bad_windows:
            with self.subTest(rows=rows), self.assertRaises(core.SnapshotDataError):
                core.build_snapshot_page(rows)
        with self.assertRaises(core.SnapshotDataError):
            core.build_snapshot_page([article(6990)], boundary=boundary)

    def test_duplicate_pk_at_different_times_in_returned_rows_is_rejected(self):
        rows = [article(7001), article(7001, published_to_web_at=STAMP-timedelta(minutes=1))]
        self.assertGreater(core.article_order_key(rows[0]), core.article_order_key(rows[1]))
        with patch.object(core, 'project_news', wraps=core.project_news) as project:
            with self.assertRaises(core.SnapshotDataError):
                core.build_snapshot_page(rows)
            self.assertEqual(project.call_count, 0)  # Reject before reading DTO/content.

    def test_older_duplicate_pk_in_thirteenth_lookahead_row_is_rejected(self):
        rows = [article(pk) for pk in range(7001, 6989, -1)]
        rows.append(article(7001, published_to_web_at=STAMP-timedelta(minutes=1)))
        self.assertEqual(len(rows), 13)
        self.assertGreater(core.article_order_key(rows[-2]), core.article_order_key(rows[-1]))
        with patch.object(core, 'project_news', wraps=core.project_news) as project:
            with self.assertRaises(core.SnapshotDataError):
                core.build_snapshot_page(iter(rows))
            self.assertEqual(project.call_count, 0)
