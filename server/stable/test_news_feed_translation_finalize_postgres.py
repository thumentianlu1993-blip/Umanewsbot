"""C159：S1 真实 PG RED 测试候选；本文件尚未执行。

固定应用 a24ac25bce77f5784de0ce8a60154d8143aafd37；C158 获审合同。
只允许后续标准 PG16/test_bounded_ci 资源执行；不允许 SQLite/生产。
不导入尚不存在的取消类型；其 foreign-token/rollback-failure 缺口见 C159 说明。
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Event, Thread, get_ident
import json
import sys
import time
from unittest.mock import patch
from uuid import UUID

from django.db import DatabaseError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from stable.models import (NewsArticle, NewsFeedChange, NewsFeedClock,
                           NewsFeedState, TranslationRun)
from stable.services import translation_recovery as recovery
from stable.services.news_feed_commit import (FeedCaptureBoundaryError,
                                             NewsFeedCaptureError,
                                             capture_news_change)
from stable.services.public_news_snapshot import NewsNotFound, project_news
from stable.services.translation import TranslationResult
from stable.services.translation_retry_budget import BudgetIdentity

SCOPE = 'public-detail'
GENERATION = UUID('00000000-0000-4000-8000-000000000159')
SOURCE_SHA = 'a24ac25bce77f5784de0ce8a60154d8143aafd37'


class InjectedAfterInsert(Exception):
    """实际 INSERT 后测试局部故障，不冒充自然故障。"""


def sqlstate(error):
    for _ in range(8):
        if error is None:
            return None
        value = getattr(error, 'sqlstate', None) or getattr(error, 'pgcode', None)
        if value:
            return value
        error = error.__cause__
    return None


def _cleanup_error_identity(error):
    """只保留异常类型/SQLSTATE/约束名/帧位置，不记录消息、参数或 SQL。"""
    chain, seen = [], set()
    for _ in range(8):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        diag = getattr(error, 'diag', None)
        code = getattr(error, 'sqlstate', None) or getattr(error, 'pgcode', None)
        constraint = getattr(diag, 'constraint_name', None) if diag is not None else None
        if code is not None and not isinstance(code, str):
            raise TypeError('diagnostic SQLSTATE must be text')
        if constraint is not None and not isinstance(constraint, str):
            raise TypeError('diagnostic constraint name must be text')
        frames, tb = [], error.__traceback__
        while tb is not None and len(frames) < 16:
            frames.append({'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
            tb = tb.tb_next
        chain.append({'type': type(error).__module__ + '.' + type(error).__name__,
                      'sqlstate': code, 'constraint_name': constraint, 'frames': frames})
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return chain


def _cleanup_diagnostic_step(record, phase, action):
    """诊断错误延至独立 unittest cleanup ERROR；原 close/异常链继续执行。"""
    event = {'phase': phase, 'thread': get_ident(), 'started': time.monotonic()}
    try:
        event['value'] = action()
        json.dumps(event)  # 禁止通过 default=str/repr 将 wrapper/driver 泄入日志。
    except BaseException as error:
        # 包括控制异常也必须记账并在主线程 cleanup 报 ERROR，不能阻断 owner close。
        # 跨线程只交纯 dict；不传异常、traceback、wrapper 或 driver 对象。
        try:
            identity = _cleanup_error_identity(error)
        except BaseException as formatter_error:
            identity = [{'type': type(error).__module__ + '.' + type(error).__name__,
                         'formatter_error_type': type(formatter_error).__name__}]
        event.pop('value', None)
        event['diagnostic_error'] = identity
        record['errors'].append({'phase': phase, 'identity': identity})
    finally:
        event['finished'] = time.monotonic()
        record['events'].append(event)


def _cleanup_local_state(db, driver):
    if db is None:
        return {'wrapper_present': False, 'driver_present': driver is not None}
    values = db.__dict__
    result = {'wrapper_present': True, 'wrapper_id': id(db), 'alias': values['alias'],
              'owner_thread': values['_thread_ident'], 'observing_thread': get_ident(),
              'driver_present': driver is not None,
              'wrapper_connection_none': values['connection'] is None,
              'pool_config_enabled': bool(values['settings_dict'].get('OPTIONS', {}).get('pool'))}
    for key in ('autocommit', 'in_atomic_block', 'needs_rollback', 'closed_in_transaction'):
        value = values[key]
        if not isinstance(value, bool):
            raise TypeError('diagnostic wrapper flag must be boolean')
        result[key] = value
    if driver is not None:
        result.update(driver_id=id(driver), driver_type=type(driver).__module__ + '.' + type(driver).__name__)
        # psycopg closed 只读取本地 PGconn.status；不读 pool/info/get_autocommit。
        closed = driver.closed
        if not isinstance(closed, (bool, int)):
            raise TypeError('diagnostic driver closed must be a local flag')
        result['driver_closed'] = bool(closed)
    return result


def _cleanup_backend_rows(cursor, target_pid):
    """仅原有健康连接/既有 observer cursor；绝不在关闭后的 target 上调用。"""
    if not isinstance(target_pid, int) or isinstance(target_pid, bool) or target_pid <= 0:
        raise RuntimeError('diagnostic target PID must already be known')
    state = _cleanup_local_state(cursor.db, cursor.db.__dict__['connection'])
    if (not state['autocommit'] or state['in_atomic_block'] or state['needs_rollback']
            or state['wrapper_connection_none'] or state.get('driver_closed', True)
            or state['owner_thread'] != state['observing_thread']):
        raise RuntimeError('diagnostic SQL requires an existing healthy owner-thread autocommit session')
    cursor.execute('SELECT pid, backend_start, datname, usename, application_name, backend_type, '
                   'state, wait_event_type, wait_event, xact_start FROM pg_stat_activity '
                   'WHERE pid=pg_backend_pid() OR pid=%s ORDER BY pid', [target_pid])
    keys = ('pid', 'backend_start', 'datname', 'usename', 'application_name', 'backend_type',
            'state', 'wait_event_type', 'wait_event', 'xact_start')
    rows = []
    for row in cursor.fetchall():
        values = dict(zip(keys, row))
        for key in ('backend_start', 'xact_start'):
            values[key] = values[key].isoformat() if values[key] is not None else None
        rows.append(values)
    return {'local': state, 'rows': rows}


@override_settings(NEWS_FEED_CAPTURE_ENABLED=True,
                   TRANSLATION_PROVIDER='dummy', TRANSLATION_MODEL='c159-synthetic',
                   TRANSLATION_AUTO_RETRY_ENABLED=True,
                   TRANSLATION_AUTO_RETRY_JITTER_SECONDS=0,
                   TRANSLATION_STALE_AFTER_SECONDS=1800,
                   TRANSLATION_FAILURE_EMAIL_ENABLED=False, AUTOMATION_ENABLED=False)
class NewsFeedTranslationFinalizePostgresTests(TransactionTestCase):
    databases = {'default'}

    def setUp(self):
        db = connection.settings_dict
        if (connection.vendor != 'postgresql' or connection.in_atomic_block
                or db['HOST'] != '127.0.0.1' or str(db['PORT']) != '5432'
                or db['USER'] != 'bounded_ci' or db['NAME'] != 'test_bounded_ci'):
            raise RuntimeError('C159 requires standard private PG TransactionTestCase target')
        self.workers = []
        with connection.cursor() as cursor:
            cursor.execute('SELECT version(), pg_backend_pid(), current_database()')
            version, self.a_pid, self.database = cursor.fetchone()
            if 'PostgreSQL 16.' not in version or self.database != 'test_bounded_ci':
                raise RuntimeError('C159 PG16/test_bounded_ci prerequisite')
            cursor.execute("SELECT set_config('lock_timeout','2s',false), "
                           "set_config('statement_timeout','10s',false), "
                           "set_config('application_name','c159-A',false)")
        self.addCleanup(self._restore_timeouts)
        print('C159_FIXTURE', self.id(), SOURCE_SHA, version, self.a_pid,
              self.database, flush=True)
        self.now = datetime.now(dt_timezone.utc)
        timer = patch('django.utils.timezone.now', side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.notice = self._patch(recovery, 'notify_terminal_translation_failure')
        self._patch(recovery, 'send_mail', side_effect=AssertionError('no actual C159 mail'))
        from stable import tasks
        self._patch(tasks, 'dispatch_task', side_effect=AssertionError('no actual C159 dispatch'))
        self.provider = self._patch(tasks, 'translate_article',
                                    side_effect=AssertionError('no actual C159 provider'))
        self.feed_clock = NewsFeedClock.objects.create(
            scope=SCOPE, generation=GENERATION, initialized=True, last_seq=0)
        self.serial = 0

    def _patch(self, owner, name, **kwargs):
        control = patch.object(owner, name, **kwargs)
        result = control.start()
        self.addCleanup(control.stop)
        return result

    def _restore_timeouts(self):
        with connection.cursor() as cursor:
            cursor.execute('RESET lock_timeout')
            cursor.execute('RESET statement_timeout')
            cursor.execute('RESET application_name')

    def fixture(self, *, visible=True, stored=True, state=True, manual=None, prepared=True):
        """真实 claim→prepare→builder→独立 checkpoint；State 在初始数据完成后建立。"""
        self.serial += 1
        article = NewsArticle.objects.create(
            source_site='jra', source_mode='official', source_language='ja',
            source_article_id=f'c159-{self.serial}',
            source_url=f'https://synthetic.invalid/c159/{self.serial}',
            title_ja='synthetic source', body_ja_raw='synthetic body',
            title_zh='旧标题', body_zh='旧正文', summary_zh='旧摘要',
            push_summary_zh='旧推送', published_at=self.now,
            public_slug=f'c159-{self.serial}', workflow_status='translation_failed',
            translation_status='failed', translation_next_retry_at=self.now,
            manually_edited_fields=[] if manual is None else manual)
        claim = recovery.claim_translation_retry(article.pk, expected_due_at=self.now, now=self.now)
        self.assertTrue(claim.claimed, claim.reason)
        if prepared:
            article, run, checkpoint, reason = recovery.prepare_translation_claim(
                article.pk, claim.run_id, claim.claimed_at, suppress_automation=True)
            self.assertEqual(reason, '')
            self.assertIsNone(checkpoint)
        else:
            if stored:
                raise ValueError('unprepared fixture cannot have a stored checkpoint')
            article.refresh_from_db()
            run = TranslationRun.objects.get(pk=claim.run_id)
            # provider-error task 测试由真实 task 自己调用 prepare，不重写常量 claim。
        result = TranslationResult('本轮标题', '本轮正文', '本轮摘要',
                                   {'provider': 'dummy', 'model': 'c159-synthetic',
                                    'machine_horse_tags': []})
        checkpoint = recovery.build_translation_checkpoint(article, run, result,
                                                            suppress_automation=True)
        decoded, _ = recovery.decode_translation_checkpoint(checkpoint, article.pk,
                                                              run.pk, claim.claimed_at)
        self.assertEqual(decoded, checkpoint)
        if stored:
            saved, reason = recovery.save_translation_checkpoint(
                article.pk, run.pk, claim.claimed_at, checkpoint)
            self.assertEqual((saved, reason), (checkpoint, ''))
        # fixture publication precedes capture State; this is not a concurrent writer.
        if visible:
            article.workflow_status = 'published'
            article.published_to_web_at = self.now
            article.save(update_fields=['workflow_status', 'published_to_web_at', 'updated_at'])
        if state:
            self.seed_state(article, visible=visible)
        run.refresh_from_db()
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY]['phase'],
                         'executing' if prepared else 'claimed')
        self.assertEqual(run.status, 'started')
        self.assertEqual(recovery.translation_input_sha256(article),
                         run.raw_response[recovery.CLAIM_KEY]['input_sha256'])
        return article, run, checkpoint, claim.claimed_at

    def seed_state(self, article, *, visible):
        return NewsFeedState.objects.create(
            scope=self.feed_clock, generation=GENERATION, news_id=article.pk,
            current_visible=visible, ever_public=visible, revision_seq=0,
            fingerprint=project_news(article)['version'] if visible else None)

    def finalize(self, fixture, *, error=None):
        article, run, checkpoint, stamp = fixture
        return recovery.finalize_translation_claim(article.pk, run.pk, stamp,
                                                    checkpoint=checkpoint, error=error)

    def snapshot(self, article):
        """精确 W；State/Article/Run 用 list 记录不存在，审计日志不纳入。"""
        return deepcopy({
            'article': list(NewsArticle.objects.filter(pk=article.pk).values()),
            'runs': list(TranslationRun.objects.filter(article_id=article.pk).order_by('pk').values()),
            'state': list(NewsFeedState.objects.filter(scope_id=SCOPE, generation=GENERATION,
                                                       news_id=article.pk).order_by('pk').values()),
            'clock': list(NewsFeedClock.objects.filter(scope=SCOPE).values()),
            'changes': list(NewsFeedChange.objects.filter(scope_id=SCOPE, generation=GENERATION)
                            .order_by('seq').values()),
        })

    def events(self):
        return list(NewsFeedChange.objects.filter(scope_id=SCOPE, generation=GENERATION)
                    .order_by('seq').values_list('seq', 'news_id', 'kind'))

    def assert_event(self, article, kind, seq=1):
        self.assertEqual(self.events()[-1:], [(seq, article.pk, kind)],
                         'S1 must atomically persist the actual final public change')
        self.feed_clock.refresh_from_db()
        self.assertEqual(self.feed_clock.last_seq, seq)
        state = NewsFeedState.objects.get(scope_id=SCOPE, generation=GENERATION, news_id=article.pk)
        self.assertEqual(state.revision_seq, seq)
        self.assertTrue(state.ever_public)
        article.refresh_from_db()
        if kind == 'withdraw':
            self.assertFalse(state.current_visible)
            self.assertIsNone(state.fingerprint)
            with self.assertRaises(NewsNotFound):
                project_news(article)
        else:
            self.assertTrue(state.current_visible)
            self.assertEqual(state.fingerprint, project_news(article)['version'])

    def worker(self, action, *, lock_timeout='2s'):
        facts = dict(ready=Event(), done=Event(), errors=[], results=[], pid=None,
                     closed=False, joined=False)
        diagnostic = self._new_cleanup_diagnostic('worker')
        facts['cleanup_diagnostic'] = diagnostic  # 只共享 JSON 兼容字典。
        def run():
            db, owner_driver = None, None
            try:
                db = connections['default']
                with db.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid(), current_database()')
                    facts['pid'], name = cursor.fetchone()
                    if name != self.database:
                        raise RuntimeError('C159 worker private DB mismatch')
                    cursor.execute("SELECT set_config('lock_timeout',%s,false), "
                                   "set_config('statement_timeout','10s',false), "
                                   "set_config('application_name','c159-B',false)", [lock_timeout])
                    owner_driver = db.__dict__['connection']
                    _cleanup_diagnostic_step(diagnostic, 'owner_identity_in_existing_cursor',
                                             lambda: self._cleanup_owner_identity(cursor, facts['pid'], diagnostic))
                facts['ready'].set()
                facts['results'].append(action())
            except BaseException as error:
                facts['errors'].append(error)
            finally:
                driver = db.__dict__.get('connection') if db is not None else None
                _cleanup_diagnostic_step(diagnostic, 'owner_before_close',
                                         lambda: self._cleanup_owner_state(db, driver, owner_driver, diagnostic))
                _cleanup_diagnostic_step(diagnostic, 'owner_close_start', lambda: None)
                close_returned = False
                try:
                    connections.close_all()  # 当前 worker 自己拥有的连接。
                    close_returned = True
                finally:
                    _cleanup_diagnostic_step(diagnostic, 'owner_close_end',
                                             lambda: {'local': _cleanup_local_state(db, driver),
                                                      'close_returned': close_returned,
                                                      'close_error': _cleanup_error_identity(sys.exception()) if not close_returned else []})
                facts['closed'] = connections['default'].connection is None
                facts['done'].set()
        facts['thread'] = Thread(target=run, daemon=True)
        self.workers.append(facts)
        facts['thread'].start()
        if not facts['ready'].wait(5):
            if facts['errors']:
                raise RuntimeError('C159 worker setup ERROR') from facts['errors'][0]
            self.fail('C159 worker session not ready within 5s')
        self.assertIsNotNone(facts['pid'])
        self.assertNotEqual(facts['pid'], self.a_pid)
        return facts

    def finish_worker(self, facts):
        if facts['joined']:
            return
        facts['thread'].join(15)
        self.assertFalse(facts['thread'].is_alive(), 'owned worker must exit within 15s')
        self.assertTrue(facts['closed'], 'owned worker must close its own session')
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_stat_clear_snapshot()')
            _cleanup_diagnostic_step(facts['cleanup_diagnostic'], 'observer_after_existing_clear',
                                     lambda: self._cleanup_observer(cursor, facts['pid'], facts['cleanup_diagnostic']))
            cursor.execute('SELECT pid FROM pg_stat_activity WHERE pid=%s', [facts['pid']])
            self.assertEqual(cursor.fetchall(), [], 'owned backend must actually disappear')
        facts['joined'] = True
        print('C159_WORKER_CLOSED', self.id(), facts['pid'], facts['closed'], flush=True)

    def tearDown(self):
        try:
            for facts in self.workers:
                self.finish_worker(facts)
        finally:
            super().tearDown()

    def require_worker_result(self, facts):
        self.finish_worker(facts)
        if facts['errors']:
            raise facts['errors'][0]  # 未知 SQL/权限/连接错误保留 ERROR 归因。
        self.assertEqual(len(facts['results']), 1)
        return facts['results'][0]

    def observe_clock_wait(self, facts):
        deadline = time.monotonic() + 1.5  # 小于 worker 的 2s lock_timeout。
        round_number = 0
        while time.monotonic() < deadline:
            round_number += 1
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_stat_clear_snapshot()')
                print('C159_FRESH_CLEAR_EXECUTED', self.id(), round_number,
                      self.a_pid, facts['pid'], flush=True)
                cursor.execute('SELECT query, wait_event_type, pg_blocking_pids(pid) '
                               'FROM pg_stat_activity WHERE pid=%s', [facts['pid']])
                rows = cursor.fetchall()
            matched = bool(rows and NewsFeedClock._meta.db_table in rows[0][0]
                           and 'FOR UPDATE' in rows[0][0].upper()
                           and rows[0][1] == 'Lock' and rows[0][2] == [self.a_pid])
            print('C159_FRESH_SAMPLE', self.id(), round_number, self.a_pid, facts['pid'],
                  {'query': rows[0][0] if rows else None,
                   'wait': rows[0][1] if rows else None,
                   'blockers': rows[0][2] if rows else [], 'observed': matched}, flush=True)
            if matched:
                self.assertFalse(facts['done'].is_set())
                return
            if facts['done'].is_set():
                if facts['errors']:
                    raise facts['errors'][0]
                break
            time.sleep(.025)
        self.fail('missing real fresh same-round Clock/FOR UPDATE/Lock/A blocker')

    def nowait_article_run(self, fixture):
        article, run, _, _ = fixture
        try:
            with transaction.atomic():  # 仅诊断 savepoint，非 finalizer 实现。
                NewsArticle.objects.select_for_update(nowait=True).get(pk=article.pk)
                TranslationRun.objects.select_for_update(nowait=True).get(pk=run.pk)
        except DatabaseError as error:
            if sqlstate(error) != '55P03' or connection.needs_rollback:
                raise
            raise self.failureException('S1 locked Article/Run before Clock (actual NOWAIT 55P03)') from error

    @contextmanager
    def constraint(self, model, name, expression):
        diagnostic = self._new_cleanup_diagnostic('constraint')
        table = connection.ops.quote_name(model._meta.db_table)
        quoted = connection.ops.quote_name(name)
        with connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {quoted} CHECK ({expression})')
        def record_sql_error(execute, sql, params, many, context):
            try:
                return execute(sql, params, many, context)
            except BaseException as error:
                _cleanup_diagnostic_step(diagnostic, 'body_sql_error',
                                         lambda: _cleanup_error_identity(error))
                raise  # 不改 SQLSTATE 分类，不替换原异常/traceback。
        try:
            with connection.execute_wrapper(record_sql_error):
                yield
        finally:
            # 独立健康测试连接清约束；必须在 owning outer 已退出后执行。
            clean = connection.copy(alias='c159-cleanup')
            pid = None
            owner_driver = None
            try:
                with clean.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid(), current_database()')
                    pid, name_db = cursor.fetchone()
                    if name_db != self.database:
                        raise RuntimeError('C159 cleanup target mismatch')
                    cursor.execute("SET statement_timeout='10s'")
                    cursor.execute("SET lock_timeout='2s'")
                    owner_driver = clean.__dict__['connection']
                    _cleanup_diagnostic_step(diagnostic, 'owner_identity_in_existing_cursor',
                                             lambda: self._cleanup_owner_identity(cursor, pid, diagnostic))
                    cursor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {quoted}')
                    cursor.execute('SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass '
                                   'AND conname=%s', [model._meta.db_table, name])
                    self.assertEqual(cursor.fetchall(), [], 'owned CHECK must be absent')
            finally:
                driver = clean.__dict__.get('connection')
                _cleanup_diagnostic_step(diagnostic, 'owner_before_close',
                                         lambda: self._cleanup_owner_state(clean, driver, owner_driver, diagnostic))
                _cleanup_diagnostic_step(diagnostic, 'owner_close_start', lambda: None)
                close_returned = False
                try:
                    clean.close()
                    close_returned = True
                finally:
                    _cleanup_diagnostic_step(diagnostic, 'owner_close_end',
                                             lambda: {'local': _cleanup_local_state(clean, driver),
                                                      'close_returned': close_returned,
                                                      'close_error': _cleanup_error_identity(sys.exception()) if not close_returned else []})
            self.assertIsNone(clean.connection)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_stat_clear_snapshot()')
                _cleanup_diagnostic_step(diagnostic, 'observer_after_existing_clear',
                                         lambda: self._cleanup_observer(cursor, pid, diagnostic))
                cursor.execute('SELECT pid FROM pg_stat_activity WHERE pid=%s', [pid])
                self.assertEqual(cursor.fetchall(), [], 'cleanup backend must disappear')
            print('C159_CHECK_REMOVED', self.id(), model._meta.db_table, name, pid, flush=True)

    def _new_cleanup_diagnostic(self, kind):
        record = {'schema': 'B151-cleanup-v1', 'test': self.id(), 'kind': kind,
                  'registered_thread': get_ident(), 'events': [], 'errors': [], 'target': None}
        self.addCleanup(self._finish_cleanup_diagnostic, record)
        return record

    def _finish_cleanup_diagnostic(self, record):
        encoded = json.dumps(record, sort_keys=True)
        try:
            print('B151_CLEANUP_DIAGNOSTIC ' + encoded, flush=True)
        finally:
            if record['errors']:
                # 独立 ERROR 不取代 test-body/原 helper 的 FAIL 或 ERROR。
                raise RuntimeError('B151 diagnostic errors retained separately: ' +
                                   json.dumps(record['errors'], sort_keys=True))

    def _cleanup_owner_identity(self, cursor, pid, record):
        if pid is None:
            raise RuntimeError('diagnostic owner PID unavailable')
        sample = _cleanup_backend_rows(cursor, pid)  # 原有 cursor，不新开目标 cursor。
        if len(sample['rows']) != 1 or sample['rows'][0]['pid'] != pid:
            raise RuntimeError('diagnostic owner identity mismatch')
        record['target'] = sample['rows'][0]
        if record['target']['datname'] != self.database or record['target']['usename'] != 'bounded_ci':
            raise RuntimeError('diagnostic owner private target mismatch')
        return sample

    def _cleanup_owner_state(self, db, driver, owner_driver, record):
        local = _cleanup_local_state(db, driver)
        record['owner_local_before_close'] = local
        if driver is None or driver is not owner_driver or record['target'] is None:
            raise RuntimeError('diagnostic owner driver/identity changed or missing before close')
        return local

    def _cleanup_observer(self, cursor, pid, record):
        sample = _cleanup_backend_rows(cursor, pid)
        # 先保留实际同轮样本；身份异常仍单独 ERROR，不过滤成 absence。
        record['events'].append({'phase': 'observer_sample', 'thread': get_ident(),
                                 'observed': time.monotonic(), 'value': sample})
        observer = [row for row in sample['rows'] if row['pid'] == self.a_pid]
        if (len(observer) != 1 or self.a_pid == pid
                or observer[0]['datname'] != self.database or observer[0]['usename'] != 'bounded_ci'):
            raise RuntimeError('diagnostic observer identity mismatch')
        target = record['target']
        if target is None:
            raise RuntimeError('diagnostic close-before target identity missing')
        identity_keys = ('pid', 'backend_start', 'datname', 'usename', 'application_name', 'backend_type')
        for row in sample['rows']:
            if row['pid'] == pid and any(row[key] != target[key] for key in identity_keys):
                raise RuntimeError('diagnostic target identity drift; original absence check unchanged')
        return {'observer_pid': self.a_pid, 'target_pid': pid}

    @contextmanager
    def after_change_insert(self, callback):
        table = connection.ops.quote_name(NewsFeedChange._meta.db_table)
        def wrapper(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.lstrip().upper().startswith('INSERT INTO') and table in sql:
                callback()  # 实际 INSERT 已执行；不替代 SQL 或投影。
            return result
        with connection.execute_wrapper(wrapper):
            yield

    def test_success_persists_final_change_and_run(self):
        fixture = self.fixture()
        article, run, checkpoint, _ = fixture
        _, reason = self.finalize(fixture)
        self.assertEqual(reason, '')
        article.refresh_from_db(); run.refresh_from_db()
        self.assertEqual(article.title_zh, checkpoint['title_zh'])
        self.assertEqual(run.status, 'success')
        self.assertEqual(run.raw_response[recovery.RESULT_KEY], checkpoint)
        self.assert_event(article, 'correct')  # a24：真实业务缺 Change Assertion RED 候选。

    def test_error_withdraws_public_article_and_run_together(self):
        fixture = self.fixture(stored=False)
        article, run, _, _ = fixture
        _, reason = self.finalize(fixture, error=ValueError('synthetic terminal failure'))
        self.assertEqual(reason, '')
        article.refresh_from_db(); run.refresh_from_db()
        self.assertEqual(article.workflow_status, 'translation_failed')
        self.assertEqual(run.status, 'failed')
        self.notice.assert_called_once()
        self.assert_event(article, 'withdraw')

    def test_hidden_success_has_no_public_event(self):
        fixture = self.fixture(visible=False)
        self.assertEqual(self.finalize(fixture)[1], '')
        self.assertEqual(self.events(), [])
        self.feed_clock.refresh_from_db()
        self.assertEqual(self.feed_clock.last_seq, 0)

    def test_visible_manual_no_net_change_has_no_event(self):
        fixture = self.fixture(manual=['title_zh', 'body_zh', 'summary_zh', 'push_summary_zh'])
        article = fixture[0]
        before = project_news(article)
        self.assertEqual(self.finalize(fixture)[1], '')
        article.refresh_from_db()
        self.assertEqual(project_news(article), before)
        self.assertEqual(self.events(), [])

    def rejection_matrix(self, mutation, reason, *, error=None):
        for seed in (False, True):
            with self.subTest(state_exists=seed):
                fixture = self.fixture(visible=False, state=seed)
                args = mutation(fixture) or fixture
                before = self.snapshot(fixture[0])
                answer = self.finalize(args, error=error)
                self.assertEqual(answer[1], reason)
                self.assertEqual(self.snapshot(fixture[0]), before)
        self.notice.assert_not_called()

    def test_checkpoint_exists_rejection_preserves_missing_or_existing_state(self):
        self.rejection_matrix(lambda f: None, 'checkpoint_exists', error=ValueError('not consumed'))

    def test_registered_rejection_preserves_missing_or_existing_state(self):
        def register(f):
            run = f[1]
            run.raw_response = {**run.raw_response, 'm02_readonly_c159': {}}
            run.save(update_fields=['raw_response', 'updated_at'])
        for error in (None, ValueError('registered takes priority over checkpoint_exists')):
            self.rejection_matrix(register, 'registered_job_wrapper_required', error=error)

    def test_changed_checkpoint_rejection_preserves_missing_or_existing_state(self):
        def change(f):
            run = f[1]
            run.raw_response = {**run.raw_response, recovery.RESULT_KEY: {}}
            run.save(update_fields=['raw_response', 'updated_at'])
        self.rejection_matrix(change, 'checkpoint_changed')

    def test_claim_stamp_rejection_preserves_missing_or_existing_state(self):
        def change(f):
            return (*f[:3], (self.now + timedelta(seconds=1)).isoformat())
        # checkpoint identity would reject first; error path exercises locked claim instead.
        self.rejection_matrix(change, 'claim_changed', error=ValueError('stale'))

    def test_consumed_claim_rejection_preserves_missing_or_existing_state(self):
        def consume(f):
            run = f[1]
            raw = deepcopy(run.raw_response)
            raw[recovery.CLAIM_KEY]['phase'] = 'completed'
            run.raw_response = raw
            run.save(update_fields=['raw_response', 'updated_at'])
        self.rejection_matrix(consume, 'claim_already_consumed')

    def test_expired_claim_rejection_preserves_missing_or_existing_state(self):
        def expire(f):
            self.now += timedelta(seconds=1801)
        self.rejection_matrix(expire, 'claim_expired')

    def test_source_only_change_rejects_input_without_state_effect(self):
        def source(f):
            article = f[0]
            article.body_ja_raw = 'changed source only'
            article.save(update_fields=['body_ja_raw', 'updated_at'])
        self.rejection_matrix(source, 'input_changed')

    def test_source_only_public_change_keeps_dto_and_rejects_input(self):
        fixture = self.fixture()
        article = fixture[0]
        dto = project_news(article)
        with capture_news_change(article.pk):
            article.body_ja_raw = 'new source with unchanged public projection'
            article.save(update_fields=['body_ja_raw', 'updated_at'])
        self.assertEqual(project_news(article), dto)
        self.assertEqual(self.events(), [])
        before = self.snapshot(article)
        self.assertEqual(self.finalize(fixture)[1], 'input_changed')
        self.assertEqual(self.snapshot(article), before)

    def test_claim_row_fences_preserve_exact_reason_and_write_set(self):
        for mode, reason in (('start', 'claim_changed'), ('article_status', 'claim_changed'),
                             ('run_status', 'claim_already_consumed'), ('missing_claim', 'claim_changed')):
            def mutate(f):
                article, run, _, _ = f
                if mode == 'start':
                    article.translation_started_at = self.now + timedelta(seconds=1)
                    article.save(update_fields=['translation_started_at', 'updated_at'])
                elif mode == 'article_status':
                    article.translation_status = 'failed'
                    article.save(update_fields=['translation_status', 'updated_at'])
                elif mode == 'run_status':
                    run.status = 'failed'
                    run.save(update_fields=['status', 'updated_at'])
                else:
                    run.raw_response = {k: v for k, v in run.raw_response.items() if k != recovery.CLAIM_KEY}
                    run.save(update_fields=['raw_response', 'updated_at'])
            with self.subTest(fence=mode):
                self.rejection_matrix(mutate, reason, error=ValueError('row fence'))

    def test_missing_run_rejection_preserves_missing_or_existing_state(self):
        def remove(f):
            f[1].delete()
        # Keep the original scalar run ID after Model.delete() clears the object PK.
        def missing(f):
            old_pk = f[1].pk
            remove(f)
            f[1].pk = old_pk
        self.rejection_matrix(missing, 'claim_changed', error=ValueError('missing'))

    def test_invalid_checkpoint_returns_before_capture(self):
        for seed in (False, True):
            fixture = self.fixture(visible=False, state=seed)
            bad = (*fixture[:2], {}, fixture[3])
            before = self.snapshot(fixture[0])
            self.assertEqual(self.finalize(bad), (None, 'checkpoint_invalid'))
            self.assertEqual(self.snapshot(fixture[0]), before)

    def test_invalid_claim_arguments_keep_original_reason(self):
        fixture = self.fixture(visible=False, state=False)
        article, _, _, _ = fixture
        before = self.snapshot(article)
        self.assertEqual(recovery.finalize_translation_claim(
            article.pk, True, '', error=ValueError('invalid claim')), (None, 'claim_missing'))
        self.assertEqual(self.snapshot(article), before)

    def test_unknown_outer_is_refused_without_writes(self):
        fixture = self.fixture()
        before = self.snapshot(fixture[0])
        with transaction.atomic():
            with self.assertRaises(FeedCaptureBoundaryError):
                self.finalize(fixture)
        self.assertEqual(self.snapshot(fixture[0]), before)

    def test_enabled_budget_binding_is_refused_without_writes(self):
        fixture = self.fixture()
        article = fixture[0]
        identity = BudgetIdentity('source', article.source_site, article.source_article_id,
                                  recovery.translation_input_sha256(article), 'a'*64,
                                  'dummy', 'c159-synthetic', UUID(int=159), article.pk)
        before = self.snapshot(article)
        with recovery._offline_budget_scope(identity):
            with self.assertRaisesRegex(FeedCaptureBoundaryError,
                                        'translation budget capture boundary unsupported'):
                self.finalize(fixture)
        self.assertEqual(self.snapshot(article), before)

    def test_disabled_preserves_existing_savepoint_and_has_no_feed_sql(self):
        fixture = self.fixture()
        with override_settings(NEWS_FEED_CAPTURE_ENABLED=False), transaction.atomic():
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.finalize(fixture)[1], '')
        tables = [m._meta.db_table for m in (NewsFeedClock, NewsFeedState, NewsFeedChange)]
        self.assertFalse(any(table in q['sql'] for table in tables for q in queries))
        self.assertEqual(self.events(), [])
        fixture[1].refresh_from_db()
        self.assertEqual(fixture[1].status, 'success')

    def test_clock_precedes_article_and_run_locks(self):
        fixture = self.fixture()
        facts = None
        try:
            with transaction.atomic():
                NewsFeedClock.objects.select_for_update().get(scope=SCOPE)
                facts = self.worker(lambda: self.finalize(fixture))
                self.observe_clock_wait(facts)
                self.nowait_article_run(fixture)
        finally:
            if facts is not None:
                self.finish_worker(facts)
        self.assertEqual(self.require_worker_result(facts)[1], '')
        self.assert_event(fixture[0], 'correct')

    def test_deadline_is_checked_after_clock_wait(self):
        fixture = self.fixture(visible=False, state=False)
        before = self.snapshot(fixture[0])
        facts = None
        try:
            with transaction.atomic():
                NewsFeedClock.objects.select_for_update().get(scope=SCOPE)
                facts = self.worker(lambda: self.finalize(fixture))
                self.observe_clock_wait(facts)
                self.now += timedelta(seconds=1801)  # 显式测试执行时钟越过 builder 的真实 deadline。
        finally:
            if facts is not None:
                self.finish_worker(facts)
        self.assertEqual(self.require_worker_result(facts)[1], 'claim_expired')
        self.assertEqual(self.snapshot(fixture[0]), before)

    def test_clock_timeout_preserves_complete_write_set(self):
        fixture = self.fixture()
        before = self.snapshot(fixture[0])
        facts = None
        try:
            with transaction.atomic():
                NewsFeedClock.objects.select_for_update().get(scope=SCOPE)
                facts = self.worker(lambda: self.finalize(fixture), lock_timeout='1s')
                self.assertTrue(facts['done'].wait(4))
        finally:
            if facts is not None:
                self.finish_worker(facts)
        self.assertEqual(len(facts['errors']), 1, 'actual Clock request must time out')
        error = facts['errors'][0]
        if not isinstance(error, DatabaseError) or sqlstate(error) != '55P03':
            raise error
        self.assertEqual(facts['results'], [])
        self.assertEqual(self.snapshot(fixture[0]), before)

    def test_real_change_check_failure_rolls_back_article_run_and_checkpoint(self):
        fixture = self.fixture()
        before = self.snapshot(fixture[0])
        with self.constraint(NewsFeedChange, 'c159_deny_change', 'seq < 0'):
            caught = None
            try:
                self.finalize(fixture)
            except DatabaseError as error:
                if sqlstate(error) != '23514':
                    raise
                caught = error
            self.assertIsNotNone(caught, 'S1 must reach the real Change CHECK')
        self.assertEqual(self.snapshot(fixture[0]), before)
        self.assertEqual(self.finalize(fixture)[1], '')
        self.assert_event(fixture[0], 'correct', 1)

    def test_actual_insert_then_fault_rolls_back_without_sequence_hole(self):
        fixture = self.fixture()
        before = self.snapshot(fixture[0])
        reached = []
        def fail():
            reached.append(self.events())
            raise InjectedAfterInsert('C159 actual INSERT then explicit precommit fault')
        with self.after_change_insert(fail):
            with self.assertRaises(InjectedAfterInsert):
                self.finalize(fixture)
        self.assertEqual(reached, [[(1, fixture[0].pk, 'correct')]])
        self.assertEqual(self.snapshot(fixture[0]), before)
        self.assertEqual(self.finalize(fixture)[1], '')
        self.assert_event(fixture[0], 'correct', 1)

    def test_reentrant_rejection_preserves_prior_authorized_work(self):
        for seed in (False, True):
            for mode in ('checkpoint_exists', 'registered_job_wrapper_required', 'claim_changed'):
                with self.subTest(state_before_outer=seed, reason=mode):
                    fixture = self.fixture(visible=False, state=seed)
                    article, run, _, _ = fixture
                    if mode == 'registered_job_wrapper_required':
                        run.raw_response = {**run.raw_response, 'm02_readonly_c159': {}}
                        run.save(update_fields=['raw_response', 'updated_at'])
                    args = fixture if mode != 'claim_changed' else (*fixture[:3], 'stale')
                    with capture_news_change(article.pk):
                        article.editor_notes = 'prior authorized work'
                        article.save(update_fields=['editor_notes', 'updated_at'])
                        before = self.snapshot(article)
                        self.assertEqual(self.finalize(args, error=ValueError('rejected'))[1], mode)
                        self.assertEqual(self.snapshot(article), before)
                        article.editor_notes = 'later authorized work'
                        article.save(update_fields=['editor_notes', 'updated_at'])
                    article.refresh_from_db()
                    self.assertEqual(article.editor_notes, 'later authorized work')
                    self.assertEqual(self.events(), [])
                    self.assertTrue(NewsFeedState.objects.filter(news_id=article.pk).exists())

    def test_reentrant_rejection_keeps_prior_public_change_for_outer_commit(self):
        fixture = self.fixture()
        article = fixture[0]
        with capture_news_change(article.pk):
            article.title_zh = 'prior authorized public change'
            article.save(update_fields=['title_zh', 'updated_at'])
            before = self.snapshot(article)
            self.assertEqual(self.finalize(fixture, error=ValueError('rejected'))[1], 'checkpoint_exists')
            self.assertEqual(self.snapshot(article), before)
            article.title_zh = 'later authorized public change'
            article.save(update_fields=['title_zh', 'updated_at'])
            self.assertEqual(self.events(), [])
        article.refresh_from_db()
        self.assertEqual(article.title_zh, 'later authorized public change')
        self.assertEqual(len(self.events()), 1)
        self.assert_event(article, 'correct')

    def test_reentrant_success_emits_only_outer_final_event(self):
        fixture = self.fixture()
        article = fixture[0]
        with capture_news_change(article.pk):
            self.assertEqual(self.finalize(fixture)[1], '')
            self.assertEqual(self.events(), [])
            article.refresh_from_db()
            article.title_zh = 'outer final title'
            article.save(update_fields=['title_zh', 'updated_at'])
        self.assertEqual(len(self.events()), 1)
        self.assert_event(article, 'correct')

    def test_reentrant_real_sql_error_poison_prevents_outer_commit(self):
        fixture = self.fixture()
        article = fixture[0]
        before = self.snapshot(article)
        caught_sql = []
        with self.constraint(TranslationRun, 'c159_deny_terminal', "status <> 'success'"):
            with self.assertRaises(NewsFeedCaptureError):
                with capture_news_change(article.pk):
                    article.editor_notes = 'must roll back with poisoned outer'
                    article.save(update_fields=['editor_notes', 'updated_at'])
                    try:
                        self.finalize(fixture)
                    except DatabaseError as error:
                        if sqlstate(error) != '23514':
                            raise
                        caught_sql.append(error)
        self.assertEqual(len(caught_sql), 1, 'actual Run CHECK must be reached')
        self.assertEqual(self.snapshot(article), before)

    def test_own_outer_sql_error_is_not_a_validation_reason(self):
        fixture = self.fixture(visible=False, state=False)
        before = self.snapshot(fixture[0])
        with self.constraint(TranslationRun, 'c159_deny_own_terminal', "status <> 'success'"):
            caught = None
            try:
                self.finalize(fixture)
            except DatabaseError as error:
                if sqlstate(error) != '23514':
                    raise
                caught = error
            self.assertIsNotNone(caught, 'own finalize must reach the actual Run CHECK')
        self.assertEqual(self.snapshot(fixture[0]), before)

    def test_manual_race_reads_fresh_fields_and_synchronized_state(self):
        fixture = self.fixture()
        article = fixture[0]
        facts = None
        try:
            with capture_news_change(article.pk):
                article.title_zh = '人工保留标题'
                article.body_zh = '人工保留正文'
                article.summary_zh = ''
                article.push_summary_zh = ''
                article.mark_manual_edits(['title_zh', 'body_zh', 'summary_zh', 'push_summary_zh'])
                article.save()
                facts = self.worker(lambda: self.finalize(fixture))
                self.observe_clock_wait(facts)
        finally:
            if facts is not None:
                self.finish_worker(facts)
        self.assertEqual(self.require_worker_result(facts)[1], '')
        article.refresh_from_db()
        self.assertEqual((article.title_zh, article.body_zh, article.summary_zh, article.push_summary_zh),
                         ('人工保留标题', '人工保留正文', '', ''))
        self.assertEqual(article.translated_title_zh, fixture[2]['title_zh'])
        self.assertEqual(len(self.events()), 1)  # 只有竞争写自身的 event，apply 无净 DTO 变。
        self.assert_event(article, 'correct')

    def test_withdrawal_race_does_not_resurrect_workflow(self):
        fixture = self.fixture()
        article = fixture[0]
        facts = None
        try:
            with capture_news_change(article.pk):
                article.workflow_status = 'pending_review'
                article.save(update_fields=['workflow_status', 'updated_at'])
                facts = self.worker(lambda: self.finalize(fixture))
                self.observe_clock_wait(facts)
        finally:
            if facts is not None:
                self.finish_worker(facts)
        self.assertEqual(self.require_worker_result(facts)[1], '')
        article.refresh_from_db()
        self.assertEqual(article.workflow_status, 'pending_review')
        self.assertEqual(self.events(), [(1, article.pk, 'withdraw')])
        self.assert_event(article, 'withdraw')

    def test_manual_empty_title_body_keep_existing_fill_semantics(self):
        fixture = self.fixture(manual=['title_zh', 'body_zh', 'summary_zh', 'push_summary_zh'])
        article = fixture[0]
        with capture_news_change(article.pk):
            article.title_zh = ''; article.body_zh = ''
            article.summary_zh = ''; article.push_summary_zh = ''
            article.save()
        self.assertEqual(self.finalize(fixture)[1], '')
        article.refresh_from_db()
        self.assertEqual(article.title_zh, fixture[2]['title_zh'])
        self.assertEqual(article.body_zh, fixture[2]['body_zh'])
        self.assertEqual((article.summary_zh, article.push_summary_zh), ('', ''))
        self.assert_event(article, 'correct', 2)

    def test_intentional_public_state_desync_is_capture_error(self):
        fixture = self.fixture()
        article = fixture[0]
        article.title_zh = 'intentional naked public DTO mutation'
        article.save(update_fields=['title_zh', 'updated_at'])
        before = self.snapshot(article)
        with self.assertRaises(NewsFeedCaptureError):
            self.finalize(fixture)
        self.assertEqual(self.snapshot(article), before)

    def test_checkpoint_resume_task_never_calls_provider(self):
        from stable.tasks import translate_article_task
        fixture = self.fixture()
        article, run, checkpoint, stamp = fixture
        result = translate_article_task.run(article.pk, preclaimed_retry=True,
                                            claim_run_id=run.pk, claim_started_at=stamp,
                                            suppress_automation=True)
        self.assertTrue(result['translated'], result)
        self.provider.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.raw_response[recovery.RESULT_KEY], checkpoint)
        self.assert_event(article, 'correct')

    def test_managed_capture_error_has_no_ordinary_failure_fallback(self):
        from stable.tasks import translate_article_task
        fixture = self.fixture()
        before = self.snapshot(fixture[0])
        with self.constraint(NewsFeedChange, 'c159_deny_task_change', 'seq < 0'):
            caught = None
            try:
                translate_article_task.run(fixture[0].pk, preclaimed_retry=True,
                                            claim_run_id=fixture[1].pk,
                                            claim_started_at=fixture[3], suppress_automation=True)
            except DatabaseError as error:
                if sqlstate(error) != '23514':
                    raise
                caught = error
            self.assertIsNotNone(caught, 'managed finalize must reach the actual Change CHECK')
        self.assertEqual(self.snapshot(fixture[0]), before)  # TaskLog 审计明确不在 W。
        self.provider.assert_not_called()
        self.notice.assert_not_called()

    def test_provider_error_capture_error_has_no_ordinary_failure_fallback(self):
        from stable.tasks import translate_article_task
        fixture = self.fixture(stored=False, prepared=False)
        baselines = []
        provider_error = ValueError('C159 synthetic provider terminal error')
        def synthetic_provider(*args, **kwargs):
            baselines.append(self.snapshot(fixture[0]))  # prepare 独立提交后才取 W 基线。
            raise provider_error
        self.provider.side_effect = synthetic_provider
        caught = None
        with self.constraint(NewsFeedChange, 'c159_deny_provider_failure', 'seq < 0'):
            try:
                translate_article_task.run(fixture[0].pk, preclaimed_retry=True,
                                            claim_run_id=fixture[1].pk,
                                            claim_started_at=fixture[3], suppress_automation=True)
            except DatabaseError as error:
                if sqlstate(error) != '23514':
                    raise
                caught = error
            except ValueError as error:
                if error is not provider_error:
                    raise
                # a24 只有原 provider error，无 Change INSERT；下行给真实业务 Assertion RED。
            self.assertIsNotNone(caught, 'provider-error finalize must reach actual Change CHECK')
        self.assertEqual(len(baselines), 1)
        self.assertEqual(self.snapshot(fixture[0]), baselines[0])
        self.assertEqual(self.provider.call_count, 1)
        self.notice.assert_not_called()

    def test_terminal_notice_runs_after_commit_with_released_clock(self):
        fixture = self.fixture(stored=False)
        probes, probe_errors = [], []
        def probe(snapshot):
            try:
                autocommit = connection.get_autocommit() and not connection.in_atomic_block
                facts = self.worker(lambda: self._probe_clock_nowait())
                probes.append((autocommit, self.require_worker_result(facts), snapshot.pk))
            except BaseException as error:
                probe_errors.append(error)  # robust callback 不能吞掉测试探针的未知 ERROR。
        self.notice.side_effect = probe
        self.assertEqual(self.finalize(fixture, error=ValueError('terminal'))[1], '')
        if probe_errors:
            error = probe_errors[0]
            if isinstance(error, DatabaseError) and sqlstate(error) == '55P03':
                self.fail('terminal notice ran while the actual Clock lock remained held')
            raise error
        self.assertEqual(probes, [(True, True, fixture[0].pk)])
        self.assert_event(fixture[0], 'withdraw')

    def _probe_clock_nowait(self):
        with transaction.atomic():
            NewsFeedClock.objects.select_for_update(nowait=True).get(scope=SCOPE)
        return True

    def test_rollback_discards_terminal_notice_callback(self):
        fixture = self.fixture(stored=False)
        before = self.snapshot(fixture[0])
        with self.constraint(NewsFeedChange, 'c159_deny_notice_change', 'seq < 0'):
            caught = None
            try:
                self.finalize(fixture, error=ValueError('terminal rollback'))
            except DatabaseError as error:
                if sqlstate(error) != '23514':
                    raise
                caught = error
            self.assertIsNotNone(caught, 'terminal failure must reach the actual Change CHECK')
        self.assertEqual(self.snapshot(fixture[0]), before)
        self.notice.assert_not_called()

    def test_notice_failure_does_not_rewrite_committed_terminal(self):
        fixture = self.fixture(stored=False)
        self.notice.side_effect = ValueError('synthetic callback failure')
        self.assertEqual(self.finalize(fixture, error=ValueError('terminal'))[1], '')
        fixture[1].refresh_from_db()
        self.assertEqual(fixture[1].status, 'failed')
        self.assert_event(fixture[0], 'withdraw')
