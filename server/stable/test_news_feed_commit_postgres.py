"""C153 real-PG RED candidate; not runnable against SQLite or production.

Synthetic fixtures only. No SQL/save/projection doubles. 14 methods correspond
exactly to C152-R01; only the standard django profile may execute them later.
"""
from datetime import datetime, timezone
import json
from threading import Event, Thread
import time
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import Client, RequestFactory, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from stable.models import (HomepageHeadlineSelection, NewsArticle, NewsFeedChange,
                           NewsFeedClock, NewsFeedState, OperationLog)
from stable.services.news_feed_commit import (FeedCaptureBoundaryError,
                                             NewsFeedCaptureError,
                                             capture_news_change)
from stable.services.public_news_snapshot import project_news

SCOPE = 'public-detail'
GENERATION = UUID('00000000-0000-4000-8000-000000000153')
STAMP = datetime(2026, 10, 15, 0, 0, 39, 123456, tzinfo=timezone.utc)


class InjectedFailure(Exception):
    """Explicit test fault, never a naturally observed production incident."""


def sqlstate(error):
    for _ in range(6):
        if error is None:
            return None
        code = getattr(error, 'sqlstate', None) or getattr(error, 'pgcode', None)
        if code:
            return code
        error = error.__cause__
    return None


@override_settings(NEWS_FEED_CAPTURE_ENABLED=True)
class FeedCommitPrimitiveTransactionTests(TransactionTestCase):
    databases = {'default'}

    def setUp(self):
        target = connection.settings_dict
        if (connection.vendor != 'postgresql' or connection.in_atomic_block
                or target['HOST'] != '127.0.0.1' or str(target['PORT']) != '5432'
                or target['USER'] != 'bounded_ci' or target['NAME'] != 'test_bounded_ci'):
            raise RuntimeError('C153 fixture requires standard private PG TransactionTestCase target before connecting')
        self.workers = []
        with connection.cursor() as cursor:
            cursor.execute('SELECT version(), pg_backend_pid(), current_database()')
            version, self.a_pid, self.database = cursor.fetchone()
            if 'PostgreSQL 16.' not in version or self.database != 'test_bounded_ci':
                raise RuntimeError('C153 only standard django test_bounded_ci / PG16')
            cursor.execute('SHOW max_connections')
            self.server_max_connections = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('application_name','c153-A',false)")
        print('C153_FIXTURE', self.id(), version, self.a_pid, self.database,
              'server_max_connections', self.server_max_connections, flush=True)
        with override_settings(NEWS_FEED_CAPTURE_ENABLED=False):
            self.staff = get_user_model().objects.create_user(username='c153-staff', is_staff=True)
            self.nonstaff = get_user_model().objects.create_user(username='c153-reader', is_staff=False)
            self.a = self.article('a')
            self.b = self.article('b')
        self.clock = NewsFeedClock.objects.create(scope=SCOPE, generation=GENERATION,
                                                 last_seq=0, initialized=True)
        for article in (self.a, self.b):
            self.seed_state(article)
        # Normal fixture SQL/schema success is a prerequisite, never business RED.
        if NewsFeedChange.objects.exists() or NewsFeedState.objects.count() != 2:
            raise RuntimeError('C153 invalid T0 fixture')
        self.assertEqual(NewsArticle.objects.get(pk=self.a.pk).title_zh, 'synthetic a')

    def article(self, label, **changes):
        values = dict(source_site='jra', source_mode='official', source_article_id='c153-'+label,
                      source_url='https://synthetic.invalid/c153/'+label,
                      title_ja='Synthetic '+label, title_zh='synthetic '+label,
                      summary_zh='', manually_edited_fields=['title_zh', 'summary_zh'],
                      published_at=STAMP, published_to_web_at=STAMP,
                      workflow_status='published', public_slug='c153-'+label)
        values.update(changes)
        return NewsArticle.objects.create(**values)

    def seed_state(self, article, visible=True):
        return NewsFeedState.objects.create(
            scope=self.clock, generation=GENERATION, news_id=article.pk,
            current_visible=visible, ever_public=visible, revision_seq=0,
            fingerprint=project_news(article)['version'] if visible else None)

    def request(self, article, payload, user=None):
        from stable.views import article_update_api
        req = RequestFactory().post(reverse('api-article-update', args=[article.pk]),
                                    json.dumps(payload), content_type='application/json')
        req.user = self.staff if user is None else user
        return article_update_api(req, article.pk)

    def state(self, article):
        return NewsFeedState.objects.get(scope_id=SCOPE, generation=GENERATION, news_id=article.pk)

    def events(self):
        return list(NewsFeedChange.objects.filter(scope_id=SCOPE, generation=GENERATION)
                    .order_by('seq').values_list('seq', 'news_id', 'kind'))

    def snapshots(self, article):
        return (NewsArticle.objects.values().get(pk=article.pk),
                NewsFeedClock.objects.values().get(scope=SCOPE),
                NewsFeedState.objects.values().get(scope_id=SCOPE, generation=GENERATION, news_id=article.pk),
                self.events(), list(OperationLog.objects.order_by('pk').values()))

    def save_title(self, article, title):
        article.title_zh = title
        article.mark_manual_edits(['title_zh'])
        article.save()

    def worker(self, action, lock_timeout='10s'):
        facts = {'ready': Event(), 'done': Event(), 'errors': [], 'results': [],
                 'pid': None, 'closed': False, 'join_attempted': False}
        def run():
            try:
                db = connections['default']
                with db.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid(), current_database()')
                    facts['pid'], database = cursor.fetchone()
                    if database != self.database:
                        raise RuntimeError('worker test DB mismatch')
                    cursor.execute("SELECT set_config('lock_timeout', %s, false), "
                                   "set_config('statement_timeout','15s',false), "
                                   "set_config('application_name','c153-B',false)", [lock_timeout])
                facts['ready'].set()
                facts['results'].append(action())
            except BaseException as error:
                facts['errors'].append(error)
            finally:
                connections.close_all()  # In the owning thread, not the A proxy.
                facts['closed'] = connections['default'].connection is None
                facts['done'].set()
        facts['thread'] = Thread(target=run, daemon=True)
        self.workers.append(facts)
        facts['thread'].start()
        ready = facts['ready'].wait(5)
        if not ready and facts['errors']:
            raise RuntimeError('B private session prerequisite failed') from facts['errors'][0]
        self.assertTrue(ready, 'B private session must actually be ready')
        self.assertIsNotNone(facts['pid'])
        self.assertNotEqual(facts['pid'], self.a_pid)
        return facts

    def finish_worker(self, facts):
        if facts['join_attempted']:
            return
        facts['join_attempted'] = True
        facts['thread'].join(12)
        self.assertFalse(facts['thread'].is_alive(), 'owned B thread must exit within 12s')
        self.assertTrue(facts['closed'], 'B must close its own connection')
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_stat_clear_snapshot()')
            cursor.execute('SELECT pid FROM pg_stat_activity WHERE pid=%s', [facts['pid']])
            self.assertEqual(cursor.fetchall(), [], 'owned B backend must be absent')
        print('C153_WORKER_CLOSED', self.id(), facts['pid'], facts['closed'], flush=True)

    def tearDown(self):
        try:
            for facts in self.workers:
                self.finish_worker(facts)
        finally:
            super().tearDown()

    def observe_clock_wait(self, facts):
        stop = time.monotonic()+5
        observed = False
        round_number = 0
        while time.monotonic() < stop:
            round_number += 1
            with connection.cursor() as cursor:
                # Two actual statements: clear first, then fresh activity+blockers.
                cursor.execute('SELECT pg_stat_clear_snapshot()')
                print('C153_FRESH_CLEAR_EXECUTED', self.id(), round_number,
                      self.a_pid, facts['pid'], flush=True)
                cursor.execute('SELECT query, wait_event_type, pg_blocking_pids(pid) '
                               'FROM pg_stat_activity WHERE pid=%s', [facts['pid']])
                rows = cursor.fetchall()
            matched = bool(rows and NewsFeedClock._meta.db_table in rows[0][0]
                           and 'FOR UPDATE' in rows[0][0].upper()
                           and rows[0][1] == 'Lock' and rows[0][2] == [self.a_pid])
            print('C153_FRESH_SAMPLE', self.id(), round_number, self.a_pid, facts['pid'],
                  {'clock_query': bool(rows and NewsFeedClock._meta.db_table in rows[0][0]),
                   'wait': rows[0][1] if rows else None,
                   'blockers': rows[0][2] if rows else [], 'observed': matched}, flush=True)
            if matched:
                observed = True
                break
            time.sleep(.025)  # Existing bounded polling, not a snapshot workaround.
        self.assertTrue(observed, 'fresh same-round Clock query/Lock/A blocker required')
        self.assertFalse(facts['done'].is_set(), 'B cannot commit while A holds Clock')
        try:
            with transaction.atomic():  # Protect NOWAIT diagnostic, not capture reentry.
                NewsArticle.objects.select_for_update(nowait=True).get(pk=self.b.pk)
        except DatabaseError as error:
            # The diagnostic savepoint has already exited/rolled back here.
            # Only the actual NOWAIT lock violation earns a business FAIL;
            # failed rollback and unknown SQL/connection errors remain ERROR.
            if sqlstate(error) != '55P03' or connection.needs_rollback:
                raise
            raise self.failureException(
                'Clock-first lock order violated: B locked Article before Clock '
                '(actual Article NOWAIT SQLSTATE 55P03 after savepoint rollback)'
            ) from error

    def on_change_insert(self, callback):
        table = connection.ops.quote_name(NewsFeedChange._meta.db_table)
        def wrapper(execute, sql, params, many, context):
            result = execute(sql, params, many, context)  # Real PG mutation first.
            if sql.lstrip().upper().startswith('INSERT INTO') and table in sql:
                callback()
            return result
        return connection.execute_wrapper(wrapper)

    def test_clock_before_article_and_commit_prefix(self):
        observed = []
        facts = None
        def after_insert():
            self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])
            self.clock.refresh_from_db()
            self.assertEqual(self.clock.last_seq, 1)
            self.assertEqual(self.state(self.a).revision_seq, 1)
            self.observe_clock_wait(facts)
            observed.append(True)
        try:
            with self.on_change_insert(after_insert), capture_news_change(self.a.pk):
                self.save_title(self.a, 'corrected A')
                facts = self.worker(lambda: self.request(self.b, {'title_zh': 'corrected B'}))
        finally:
            if facts is not None:
                self.finish_worker(facts)  # A unit already exited, before join.
        self.assertEqual(observed, [True], 'real provisional INSERT and lock sample required')
        self.assertEqual(facts['errors'], [])
        self.assertEqual(facts['results'][0].status_code, 200)
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct'), (2, self.b.pk, 'correct')])
        self.clock.refresh_from_db()
        self.assertEqual(self.clock.last_seq, 2)
        self.assertEqual([self.state(x).revision_seq for x in (self.a, self.b)], [1, 2])

    def test_clock_timeout_has_no_business_write(self):
        before = self.snapshots(self.b)
        facts = None
        try:
            with transaction.atomic():
                NewsFeedClock.objects.select_for_update().get(scope=SCOPE)
                facts = self.worker(lambda: self.request(self.b, {'title_zh': 'must roll back'}), '1s')
                self.assertTrue(facts['done'].wait(5), 'real 1s lock_timeout must terminate B within bounded observation')
        finally:
            if facts is not None:
                self.finish_worker(facts)
        self.assertEqual(len(facts['errors']), 1, 'no-Clock skeleton must fail this oracle')
        self.assertEqual(sqlstate(facts['errors'][0]), '55P03')
        self.assertEqual(facts['results'], [])
        self.assertEqual(self.snapshots(self.b), before)
        self.request(self.b, {'title_zh': 'legal next'})
        self.assertEqual(self.events(), [(1, self.b.pk, 'correct')])

    def test_rollback_reuses_transaction_counter(self):
        before = self.snapshots(self.a)
        reached = []
        def fault():
            reached.append(True)
            self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])
            raise InjectedFailure('explicit precommit fault after actual INSERT')
        caught = False
        try:
            with self.on_change_insert(fault):
                self.request(self.a, {'title_zh': 'rollback candidate'})
        except InjectedFailure:
            caught = True
        self.assertTrue(caught and reached == [True], 'must reach allocated real event before rollback')
        self.assertEqual(self.snapshots(self.a), before)
        self.request(self.b, {'title_zh': 'next after rollback'})
        self.assertEqual(self.events(), [(1, self.b.pk, 'correct')])

    def test_lost_ack_keeps_committed_event(self):
        try:
            response = self.request(self.a, {'title_zh': 'committed but ack lost'})
            self.assertEqual(response.status_code, 200)
            raise InjectedFailure('ACK fault outside already-committed unit')
        except InjectedFailure:
            pass
        first = self.events()
        second = self.events()  # A autocommit performs another committed read.
        self.assertEqual(first, [(1, self.a.pk, 'correct')])
        self.assertEqual(second, first)
        self.assertEqual(NewsArticle.objects.get(pk=self.a.pk).title_zh, 'committed but ack lost')
        self.assertEqual(self.state(self.a).revision_seq, 1)
        self.assertEqual(OperationLog.objects.filter(action_type='article_updated_api').count(), 1)

    def test_multiple_saves_nested_same_unit_final_only(self):
        with capture_news_change(self.a.pk):
            self.save_title(self.a, 'intermediate')
            with capture_news_change(self.a.pk):
                self.a.public_slug = 'article-draft'
                self.save_title(self.a, 'final')  # Actual model slug second-save.
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])
        self.a.refresh_from_db()
        self.assertFalse(self.a.public_slug.endswith('-draft'))
        self.assertEqual(self.state(self.a).fingerprint, project_news(self.a)['version'])
        with capture_news_change(self.a.pk):
            self.save_title(self.a, 'temporary again')
            self.save_title(self.a, 'final')
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])

    def test_transient_publish_then_hidden_no_false_history(self):
        with override_settings(NEWS_FEED_CAPTURE_ENABLED=False):
            hidden = self.article('hidden', workflow_status='withdrawn')
        self.seed_state(hidden, visible=False)  # Old timestamp is not past-public proof.
        with capture_news_change(hidden.pk):
            hidden.workflow_status = 'published'
            hidden.save()
            hidden.workflow_status = 'withdrawn'
            hidden.save()
        self.assertEqual(self.events(), [])
        self.assertFalse(self.state(hidden).ever_public)
        self.assertEqual(self.state(hidden).revision_seq, 0)
        with capture_news_change(self.a.pk):
            self.a.workflow_status = 'withdrawn'
            self.a.save()
        self.assertEqual(self.events(), [(1, self.a.pk, 'withdraw')])
        state = self.state(self.a)
        self.assertFalse(state.current_visible)
        self.assertIsNone(state.fingerprint)
        self.assertTrue(state.ever_public)

    def test_delete_recreate_net_and_republication_position(self):
        pk = self.a.pk
        values = NewsArticle.objects.values().get(pk=pk)
        with capture_news_change(pk):
            NewsArticle.objects.get(pk=pk).delete()
            self.assertTrue(NewsFeedState.objects.filter(news_id=pk).exists())
            NewsArticle.objects.create(**values)
        self.assertEqual(self.events(), [])
        with capture_news_change(pk):
            NewsArticle.objects.get(pk=pk).delete()
        self.assertEqual(self.events(), [(1, pk, 'withdraw')])
        self.assertTrue(NewsFeedState.objects.filter(news_id=pk, ever_public=True).exists())
        with capture_news_change(pk):
            NewsArticle.objects.create(**values)
        self.assertEqual(self.events(), [(1, pk, 'withdraw'), (2, pk, 'publish')])
        self.assertEqual(self.state(self.a).revision_seq, 2)

    def test_event_check_failure_rolls_back_api_and_journal(self):
        before = self.snapshots(self.a)
        table = connection.ops.quote_name(NewsFeedChange._meta.db_table)
        constraint = connection.ops.quote_name('c153_test_reject_new_event')
        with connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK (seq <= 0)')
        error = None
        try:
            try:
                self.request(self.a, {'title_zh': 'rejected event candidate'})
            except Exception as exc:
                error = exc
            self.assertIsNotNone(error, 'actual Change INSERT must violate temporary CHECK')
            self.assertEqual(sqlstate(error), '23514')
            self.assertEqual(self.snapshots(self.a), before)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {constraint}')
                cursor.execute('SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass AND conname=%s',
                               [NewsFeedChange._meta.db_table, 'c153_test_reject_new_event'])
                self.assertEqual(cursor.fetchall(), [], 'temporary constraint must be absent')

    def test_unrelated_outer_atomic_and_savepoint_refused(self):
        before = self.snapshots(self.a)
        for savepoint in (False, True):
            with self.subTest(savepoint=savepoint), transaction.atomic():
                def attempt():
                    with self.assertRaises(FeedCaptureBoundaryError):
                        with capture_news_change(self.a.pk):
                            self.save_title(self.a, 'must never enter')
                if savepoint:
                    with transaction.atomic():
                        attempt()
                else:
                    attempt()
        self.assertEqual(self.snapshots(self.a), before)

    def test_caught_nested_unit_error_poison_rolls_back(self):
        before = self.snapshots(self.a)
        with self.assertRaises(NewsFeedCaptureError):
            with capture_news_change(self.a.pk):
                self.save_title(self.a, 'before nested failure')
                try:
                    with capture_news_change(self.a.pk):
                        raise InjectedFailure('caught nested test fault')
                except InjectedFailure:
                    pass
        self.assertEqual(self.snapshots(self.a), before)

    def test_final_persisted_projection_not_dirty_instance(self):
        with capture_news_change(self.a.pk):
            self.save_title(self.a, 'persisted A')
            self.a.title_zh = 'dirty B not saved'
        stored = NewsArticle.objects.get(pk=self.a.pk)
        self.assertEqual(stored.title_zh, 'persisted A')
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])
        self.assertEqual(self.state(self.a).fingerprint, project_news(stored)['version'])
        self.assertEqual(project_news(stored)['summary'], '')
        self.assertEqual(project_news(stored)['public_path'], f'/news/{self.a.pk}/')
        self.assertEqual(project_news(stored)['published_at'], '2026-10-15T00:00:00Z')
        with capture_news_change(stored.pk):
            stored.editor_notes = 'synthetic internal note'
            stored.published_to_web_at = STAMP.replace(second=1, microsecond=0)
            stored.save()
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])

    def test_disabled_existing_api_contract(self):
        before_clock = NewsFeedClock.objects.values().get(scope=SCOPE)
        business_atomic = []
        article_table = connection.ops.quote_name(NewsArticle._meta.db_table)
        def trace_business_update(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith('UPDATE') and article_table in sql:
                business_atomic.append(connection.in_atomic_block)
            return execute(sql, params, many, context)
        with override_settings(NEWS_FEED_CAPTURE_ENABLED=False), CaptureQueriesContext(connection) as queries, connection.execute_wrapper(trace_business_update):
            response = self.request(self.a, {'title_zh': 'disabled old path'})
        self.assertEqual(json.loads(response.content), {'updated': True, 'fields': ['title_zh']})
        self.assertFalse(any('stable_newsfeed' in q['sql'].lower() for q in queries))
        self.assertEqual(business_atomic, [False], 'disabled business save retains autocommit; existing headline callback has its own atomic')
        self.assertEqual(NewsFeedClock.objects.values().get(scope=SCOPE), before_clock)
        url = reverse('api-article-update', args=[self.a.pk])
        with override_settings(NEWS_FEED_CAPTURE_ENABLED=False):
            anonymous = Client()
            self.assertEqual(anonymous.post(url, '{}', content_type='application/json').status_code, 302)
            regular = Client(); regular.force_login(self.nonstaff)
            self.assertEqual(regular.post(url, '{}', content_type='application/json').status_code, 403)
            staff = Client(); staff.force_login(self.staff)
            self.assertEqual(staff.get(url).status_code, 405)
            missing = reverse('api-article-update', args=[2**62])
            self.assertEqual(staff.post(missing, '{}', content_type='application/json').status_code, 404)
            csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.staff)
            self.assertEqual(csrf.post(url, '{}', content_type='application/json').status_code, 403)
        self.assertEqual(self.events(), [])

    def test_enabled_api_visibility_and_operationlog_atomic(self):
        response = self.request(self.a, {'title_zh': 'public correction', 'summary_zh': ''})
        self.assertEqual(json.loads(response.content), {'updated': True, 'fields': ['title_zh', 'summary_zh']})
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct')])
        self.assertEqual(OperationLog.objects.filter(action_type='article_updated_api').count(), 1)
        self.request(self.a, {'workflow_status': 'withdrawn'})
        self.request(self.a, {'workflow_status': 'published'})
        self.assertEqual(self.events(), [(1, self.a.pk, 'correct'), (2, self.a.pk, 'withdraw'),
                                        (3, self.a.pk, 'publish')])
        # Removing a homepage slot is not withdrawing an otherwise public detail.
        slot = HomepageHeadlineSelection.objects.create(article=self.a)
        with capture_news_change(self.a.pk):
            slot.article = None; slot.save()
        self.assertEqual(len(self.events()), 3)
        with override_settings(NEWS_FEED_CAPTURE_ENABLED=False):
            untimed = self.article('untimed', published_to_web_at=None)
        self.seed_state(untimed, visible=False)
        self.request(untimed, {'title_zh': 'still not public without web time'})
        self.assertEqual(len(self.events()), 3)

    def test_clock_uninitialized_or_state_desync_fails_closed(self):
        for invalid in ('uninitialized', 'desynchronized'):
            with self.subTest(invalid=invalid):
                if invalid == 'uninitialized':
                    NewsFeedClock.objects.filter(scope=SCOPE).update(initialized=False)
                else:
                    NewsFeedState.objects.filter(news_id=self.a.pk).update(fingerprint='wrong-but-not-null')
                before = self.snapshots(self.a)
                with self.assertRaises(NewsFeedCaptureError):
                    self.request(self.a, {'title_zh': 'must refuse before business write'})
                self.assertEqual(self.snapshots(self.a), before)
                NewsFeedClock.objects.filter(scope=SCOPE).update(initialized=True)
