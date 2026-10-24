"""C262 source-only real scanner oracle; no execution in this author card.

Positive archives only come from the actual admitted writer. Owner mutations
are explicitly negative fixtures. No future guard/error class is imported;
missing current model/API/driver/thread prerequisites are scenario ERROR.
UNKNOWN_NO_INDEX leaves the existing independent weak policy intact. This is
not historical coverage, owner INSERT authentication or production enforce.
"""
import ast
import copy
import hashlib
import inspect
import io
import json
import re
import sys
import threading
import time
import traceback
from contextlib import contextmanager

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from stable import test_horse_article_strong_evidence_protection as existing_fixture
from stable import test_horse_article_pair_receipt_index as index_fixture
from stable.models import ArticleHorseLink, HorseProfile, HorseExternalIdentity, NewsArticle, OperationLog, TaskExecutionLog, TermEntry
from stable.services import horse_profiles
from stable.services.article_entity_reprocessing import _commit_article
from stable.services.horse_article_binding_persistence import commit_strong_horse_binding
from stable.services.horse_article_pair_receipt_index import classify_pair_receipt_history
from stable.services.terms import resolve_article_entities
from stable.tasks import scan_article_horse_links_task


INDEX_TABLE = 'stable_horsearticlepairreceiptindex'
ISOLATION_CODE = 'pair_history_requires_read_committed'
PAIR_BUDGET_CODE = 'pair_history_pair_budget_exceeded'
ELAPSED_BUDGET_CODE = 'pair_history_elapsed_budget_exceeded'
PAIR_LIMIT, DATA_SELECT_LIMIT, RAW_INPUT_LIMIT = 16, 32, 64 * 1024 * 1024
TOTAL_SECONDS, WORK_SECONDS, BARRIER_SECONDS = 30, 24, 5
_EMIT_LOCK = threading.Lock()


class ScannerScenarioError(RuntimeError):
    """API/schema/fixture/driver/window prerequisites, never manufactured RED."""


def require(value, message):
    if not value:
        raise ScannerScenarioError(message)


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, default=lambda x: {'bytes_hex':x.hex()} if type(x) is bytes else x.isoformat()).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def row(instance):
    return {f.attname: copy.deepcopy(getattr(instance, f.attname)) for f in instance._meta.concrete_fields}


def rows(model):
    return copy.deepcopy(list(model.objects.order_by('pk').values()))


def sqlstate(error):
    cause = getattr(error, '__cause__', None)
    return getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None)


def emit(kind, **value):
    with _EMIT_LOCK:
        print('\nC262_PAIR_SCANNER ' + json.dumps(dict(kind=kind, **value), ensure_ascii=False, default=str), flush=True)


def metadata(db):
    """Independent real cursor; never consumes/replaces the observed result."""
    with db.connection.cursor() as cursor, db.wrap_database_errors:
        cursor.execute("SELECT pg_backend_pid(),current_setting('transaction_isolation'),"
                       "current_setting('statement_timeout'),current_setting('lock_timeout'),txid_current_if_assigned()")
        pid, level, statement, lock, xid = cursor.fetchone()
    return dict(pid=pid, isolation=level, statement_timeout=statement, lock_timeout=lock,
                alias=db.alias, xid=xid, raw_connection=id(db.connection), atomic=db.in_atomic_block,
                autocommit=db.get_autocommit())


def milliseconds(value):
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(ms|s|min|h)?', value)
    require(match is not None, 'unrecognized actual PG timeout: '+repr(value))
    return float(match[1]) * {None:1, 'ms':1, 's':1000, 'min':60000, 'h':3600000}[match[2]]


class _Observe:
    """Transparent actual SQL/call observer, with explicitly labelled real faults."""
    def __init__(self, db, *, before=None, after=None, fault=None, role="weak"):
        self.db, self.before, self.after, self.fault = db, before, after, fault
        self.notes, self.reader_calls, self.forbidden, self.faults = [], [], [], []
        self.role=role;self.producer_calls=[]

    def __enter__(self):
        self.initial = metadata(self.db); self.old_profile = sys.getprofile()
        def profile(frame, event, arg):
            if event != 'call' or '/stable/services/' not in frame.f_code.co_filename:return
            name=frame.f_code.co_name
            if name=='classify_pair_receipt_history':
                self.reader_calls.append(dict(article_id=frame.f_locals['article_id'],
                    profile_id=frame.f_locals['profile_id'], **metadata(self.db)))
            if name in {'_admit','commit_strong_horse_binding','_capture_created_receipt'}:
                (self.forbidden if self.role=="weak" else self.producer_calls).append(name)
        sys.setprofile(profile)
        self.context=self.db.execute_wrapper(self.execute);self.context.__enter__()
        return self

    def execute(self, execute, sql, params, many, context):
        recovery=bool(re.match(r'^\s*(ROLLBACK|RELEASE\s+SAVEPOINT|COMMIT)\b',sql,re.I))
        sampled=(copy.deepcopy(self.notes[-1]['actual'] if self.notes else self.initial)
                 if recovery else metadata(context['connection']))
        note=dict(sequence=len(self.notes)+1,sql=sql,params=copy.deepcopy(params),many=many,
                  thread_ident=threading.get_ident(),thread_name=threading.current_thread().name,
                  actual=sampled,metadata_origin='last_pre_recovery_sample' if recovery else 'immediate_actual_sample',
                  execution_state='attempted',original_statement_executed=False)
        self.notes.append(note)
        try:
            note['lock']=index_fixture._lock_query_target(sql)
            if self.before is not None:self.before(note)
            if self.fault is not None:self.fault(self, note, context)
            note['original_statement_executed']=True
            value=execute(sql,params,many,context);note['execution_state']='completed'
            cursor=context.get('cursor')
            if cursor is not None and cursor.description:note['columns']=[x[0] for x in cursor.description]
            if self.after is not None:self.after(note)
            return value
        except BaseException as error:
            note.update(raised_type=type(error).__name__,raised_message=str(error),SQLSTATE=sqlstate(error))
            if note['execution_state']=='attempted':note['execution_state']='raised'
            raise
        finally:
            if note.get('lock') is not None or INDEX_TABLE in sql or note['execution_state']=='raised':
                emit('actual_SQL',observation=copy.deepcopy(note))

    def __exit__(self, *exc):
        try:return self.context.__exit__(*exc)
        finally:
            sys.setprofile(self.old_profile)
            emit('actual_call_trace',role=self.role,initial=self.initial,reader_calls=self.reader_calls,producer_calls=self.producer_calls,
                 forbidden_calls=self.forbidden,faults=self.faults,SQL=self.notes)

    def data(self):
        return [n for n in self.notes if n['sql'].lstrip().upper().startswith('SELECT') and INDEX_TABLE in n['sql']]

    def weak_dml(self):
        return [n for n in self.notes if re.match(r'^\s*(INSERT|UPDATE|DELETE)\b',n['sql'],re.I)
                and '"stable_articlehorselink"' in n['sql']]


def real_fault(statement, code):
    def fault(observer, note, context):
        if INDEX_TABLE not in note['sql'] or not note['sql'].lstrip().upper().startswith('SELECT') or observer.faults:return
        observer.faults.append(dict(statement=statement,expected_SQLSTATE=code))
        with context['connection'].connection.cursor() as cursor, context['connection'].wrap_database_errors:
            if 'pg_sleep' in statement:cursor.execute("SET LOCAL statement_timeout='30ms'")
            cursor.execute(statement)
        raise ScannerScenarioError('actual driver fault failed to raise')
    return fault


class _Window:
    """Two actual workers plus an independent RC observer; total budget 30s."""
    def __init__(self, owner):
        self.owner=owner;self.started=time.monotonic();self.gates={};self.workers=[];self.samples=[];self.closing=False

    def gate(self, name):
        event=self.gates.setdefault(name,threading.Event())
        if self.closing:event.set()
        return event

    def wait(self, name):
        remaining=WORK_SECONDS-(time.monotonic()-self.started)
        require(remaining>0 and self.gate(name).wait(min(BARRIER_SECONDS,remaining)), 'window deadline: '+name)

    def release(self, name):self.gate(name).set()

    def start(self, name, function):
        self.gate(name+'_done')
        worker=dict(name=name,pid=None,raw=None,value=None,error=None,trace=None,closed=False,observer=None)
        def run():
            db=connections['default']
            try:
                db.ensure_connection();worker['raw']=db.connection
                with db.cursor() as cursor:
                    cursor.execute("SET statement_timeout='10s'");cursor.execute("SET lock_timeout='5s'")
                worker['initial']=metadata(db);worker['pid']=worker['initial']['pid']
                require(worker['initial']['isolation']=='read committed','RC worker base prerequisite; RR control sets only its own transaction')
                worker['value']=function(worker,db)
            except BaseException as error:worker['error']=error;worker['trace']=traceback.format_exc()
            finally:
                db.close();worker['closed']=True;self.release(name+'_done')
        worker['thread']=threading.Thread(target=run,name='c262-'+name,daemon=False)
        self.workers.append(worker);worker['thread'].start();return worker

    def blocked(self, waiter, holder):
        self.wait(waiter['name']+'_attempted')
        require(waiter['pid'] is not None and holder['pid'] is not None and waiter['pid']!=holder['pid'], 'distinct actual PG workers required')
        deadline=min(self.started+WORK_SECONDS,time.monotonic()+3);blockers=[]
        while time.monotonic()<deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_blocking_pids(%s)',(waiter['pid'],));blockers=cursor.fetchone()[0]
            if holder['pid'] in blockers:break
            time.sleep(.01)
        require(holder['pid'] in blockers, 'actual PG blocking sample missing')
        sample=dict(waiter=waiter['pid'],holder=holder['pid'],actual_blockers=blockers)
        self.samples.append(sample);emit('actual_PG_blocking',**sample)

    def __enter__(self):return self

    def __exit__(self, *exc):
        self.closing=True
        for event in list(self.gates.values()):event.set()
        for worker in self.workers:
            thread=worker['thread'];remaining=max(0,TOTAL_SECONDS-(time.monotonic()-self.started))
            thread.join(min(2,remaining))
            if thread.is_alive() and worker['raw'] is not None:
                worker['raw'].cancel();thread.join(min(1,max(0,TOTAL_SECONDS-(time.monotonic()-self.started))))
            if thread.is_alive() and worker['raw'] is not None:
                worker['raw'].close();thread.join(min(1,max(0,TOTAL_SECONDS-(time.monotonic()-self.started))))
        alive=[w['name'] for w in self.workers if w['thread'].is_alive()]
        emit('window_cleanup',seconds=time.monotonic()-self.started,alive=alive,samples=self.samples,
             workers=[{k:w[k] for k in ('name','pid','value','trace','closed')} for w in self.workers])
        require(not alive,'bounded worker cleanup failed: '+repr(alive))
        require(time.monotonic()-self.started<TOTAL_SECONDS,'30-second total window budget exhausted')


class PairIndexScannerProtectionTests(TransactionTestCase):
    def setUp(self):
        require(connection.vendor=='postgresql' and connection.get_autocommit() and not connection.in_atomic_block,
                'independent isolated PostgreSQL TransactionTestCase required')
        try:self.Index=apps.get_model('stable','HorseArticlePairReceiptIndex')
        except LookupError as error:raise ScannerScenarioError('current index schema absent') from error
        require(INDEX_TABLE in connection.introspection.table_names(),'current migrated index table absent')
        require(metadata(connection)['isolation']=='read committed','actual CI base transaction must be RC; unsupported controls explicitly set their own transaction')
        require(tuple(inspect.signature(classify_pair_receipt_history).parameters)==('article_id','profile_id'),
                'current pair reader API mismatch')
        self.registry={};self.domains=[]
        ctx=override_settings(HORSE_ARTICLE_BINDING_HANDLES=self.registry);ctx.enable();self.addCleanup(ctx.disable)

    @contextmanager
    def domain(self, token):
        d=existing_fixture._Domain(self,'c262-'+token);self.domains.append(d)
        try:yield d
        finally:
            try:d.close()
            finally:self.domains.remove(d)

    def state(self):
        return dict(links=rows(ArticleHorseLink),indexes=rows(self.Index),
            strong_logs=copy.deepcopy(list(OperationLog.objects.filter(action_type='horse_binding_committed',target_type='horse_binding_request').order_by('pk').values())),
            articles=rows(NewsArticle),profiles=rows(HorseProfile),identities=rows(HorseExternalIdentity),
            terms=rows(TermEntry),users=rows(get_user_model()),registry=copy.deepcopy(self.registry),
            producer_bytes=[d.path.read_bytes() for d in self.domains],tasks=rows(TaskExecutionLog),
            other_logs=copy.deepcopy(list(OperationLog.objects.exclude(action_type='horse_binding_committed',target_type='horse_binding_request').order_by('pk').values())))

    def capture(self, d):
        result=commit_strong_horse_binding(d.handle,d.actor)
        require(result.get('status')=='created','actual capture admission prerequisite: '+repr(result))
        link=ArticleHorseLink.objects.get(pk=result['link_id']);log=OperationLog.objects.get(pk=result['receipt_id'])
        value=json.loads(log.detail);d.original_link_id=link.pk;d.key=log.target_id
        archive=self.Index.objects.get(article_id_snapshot=d.article.pk,profile_id_snapshot=d.horse.pk)
        require(raw(value).decode()==log.detail and raw(value['after'])==raw(row(link))
                and value['after_sha256']==sha(raw(row(link))) and archive.receipt_detail==log.detail
                and archive.operation_log_id_snapshot==log.pk and archive.original_link_id==link.pk
                and archive.receipt_detail_sha256==sha(log.detail.encode()) and archive.request_key==log.target_id==value['request_key']
                and archive.original_actor_id==log.admin_id==d.actor.pk and archive.article_id_snapshot==d.article.pk
                and archive.profile_id_snapshot==d.horse.pk,'actual three-piece fixture binding invalid')
        require(classify_pair_receipt_history(d.article.pk,d.horse.pk)['state']=='INDEXED_HISTORY','current archive reader prerequisite')
        emit('actual_three_piece_capture',result=result,link=row(link),log=row(log),archive=row(archive))
        return result

    def prepare(self, d, mode):
        self.capture(d)
        if mode=='erase':ArticleHorseLink.objects.filter(article=d.article,horse_profile=d.horse).update(source='ordinary-erased',metadata={})
        elif mode in ('missing','replacement'):
            ArticleHorseLink.objects.filter(article=d.article,horse_profile=d.horse).delete()
            if mode=='replacement':
                link=ArticleHorseLink.objects.create(article=d.article,horse_profile=d.horse,status='auto',source='ordinary-replacement',confidence=17,metadata={'ordinary':True})
                require(link.pk!=d.original_link_id,'replacement fixture reused historical PK')
        else:raise ScannerScenarioError('unknown negative fixture mode')
        emit('negative_current_preparation',mode=mode,current=d.rows(),historical_link_id=d.original_link_id)

    def resolution(self, d):
        d.article.refresh_from_db()
        return resolve_article_entities(d.article.title_ja,d.article.body_ja_normalized or d.article.body_ja_raw,source_language=d.article.source_language or 'en')

    def invoke(self, d, path, *, commit=True):
        if path=='article':return scan_article_horse_links_task.run(article_id=d.article.pk,commit=commit)
        if path=='profile':return scan_article_horse_links_task.run(profile_id=d.horse.pk,commit=commit)
        if path=='global':return scan_article_horse_links_task.run(commit=commit)
        if path=='profile_pair':return scan_article_horse_links_task.run(article_id=d.article.pk,profile_id=d.horse.pk,commit=commit)
        if path=='direct':return horse_profiles.reconcile_article_horse_links(d.article,self.resolution(d),commit=commit)
        if path=='internal_reprocess':return _commit_article(d.article.pk,translate_sync=False)
        out=io.StringIO()
        if path=='scan_cli':
            args=['--horse-profile-id',str(d.horse.pk),'--commit' if commit else '--dry-run']
            call_command('scan_article_horse_links',*args,stdout=out,no_color=True)
            return ast.literal_eval(out.getvalue().strip().split(': ',1)[1])
        if path=='reprocess':
            args=['--article-id',str(d.article.pk),'--json']+(['--commit'] if commit else [])
            call_command('reprocess_article_entities',*args,stdout=out,no_color=True)
            return json.loads(out.getvalue())['articles'][0]
        raise ScannerScenarioError('unknown actual entrypoint: '+path)

    def outcome(self, function):
        try:return function(),None
        except Exception as error:return None,error

    def counts(self, result, path):
        if path in ('reprocess','internal_reprocess'):
            self.assertEqual(result['status'],'committed');result=result['links']
        if path in ('direct','reprocess','internal_reprocess'):
            return (len(result['create']),len(result['update']),len(result['delete_ids']))
        return (result['created'],result['updated'],result.get('deleted',0))

    def check_preserved(self, before, after, d, path, observer, *, error=False):
        emit('state_comparison',path=path,error=error,before_SHA=sha(raw(before)),after_SHA=sha(raw(after)),
             before_links=before['links'],after_links=after['links'],before_Index_SHA=sha(raw(before['indexes'])),
             after_Index_SHA=sha(raw(after['indexes'])),weak_DML=observer.weak_dml())
        for key in ('links','indexes','strong_logs','profiles','identities','terms','users','registry','producer_bytes'):
            self.assertEqual(after[key],before[key],key)
        if path in ('reprocess','internal_reprocess') and not error:
            def masked(values):
                return [{k:v for k,v in value.items() if not(value['id']==d.article.pk and k in {'tags_json','translation_metadata','updated_at'})} for value in values]
            self.assertEqual(masked(after['articles']),masked(before['articles']))
        else:self.assertEqual(after['articles'],before['articles'])
        self.assertEqual(observer.weak_dml(),[],'zero relation DML, not merely equal final values')
        self.assertEqual(observer.forbidden,[],'weak call cannot re-admit or capture')
        self.assertTrue(all(n['actual']['pid']==observer.initial['pid'] and n['actual']['raw_connection']==observer.initial['raw_connection'] for n in observer.notes))
        old_task_ids={x['id'] for x in before['tasks']};old_log_ids={x['id'] for x in before['other_logs']}
        self.assertEqual([x for x in after['tasks'] if x['id'] in old_task_ids],before['tasks'])
        self.assertEqual([x for x in after['other_logs'] if x['id'] in old_log_ids],before['other_logs'])
        task_delta=[x for x in after['tasks'] if x['id'] not in old_task_ids]
        log_delta=[x for x in after['other_logs'] if x['id'] not in old_log_ids]
        if path in ('reprocess','internal_reprocess'):
            self.assertEqual(task_delta,[])
            if path=='internal_reprocess' and error:self.assertEqual(log_delta,[])
            else:
                self.assertEqual(len(log_delta),1)
                self.assertEqual(log_delta[0]['action_type'],'article_entities_reprocess_failed' if error else 'article_entities_reprocessed')
                self.assertEqual(log_delta[0]['target_id'],str(d.article.pk))
        else:
            self.assertEqual(log_delta,[])
            if path=='direct' or error:self.assertEqual(task_delta,[])
            else:
                self.assertEqual(len(task_delta),1);self.assertEqual(task_delta[0]['task_name'],'horse_article_link_scan')
                self.assertEqual(task_delta[0]['status'],'success')

    def check_observation(self, observer, d, *, pair_count=1):
        self.assertEqual(observer.forbidden,[])
        self.assertTrue(observer.data(),'real new-table observation must occur')
        self.assertEqual(len({(x['article_id'],x['profile_id']) for x in observer.reader_calls}),pair_count)
        self.assertEqual(len(observer.reader_calls),pair_count,'one real reader call per pair/unit')
        self.assertLessEqual(len(observer.data()),2*pair_count)
        shows=[x for x in observer.notes if re.fullmatch(r'\s*SHOW\s+"?transaction_isolation"?\s*;?\s*',x['sql'],re.I)]
        self.assertTrue(shows,'actual transaction SHOW, not a driver default')
        first_history=min(x['sequence'] for x in observer.data())
        self.assertTrue(any(x['sequence']<first_history and x['actual']['isolation']=='read committed' for x in shows))
        for x in observer.reader_calls:
            self.assertTrue(x['atomic']);self.assertFalse(x['autocommit']);self.assertEqual(x['isolation'],'read committed')
            self.assertEqual(x['pid'],observer.initial['pid'])
            self.assertIsNotNone(x['xid'],'reader must run inside the actual parent-locked transaction')
        for note in observer.data():
            self.assertRegex(note['sql'],r'"article_id_snapshot"\s*=\s*%s')
            self.assertRegex(note['sql'],r'"profile_id_snapshot"\s*=\s*%s')
        for mutation in observer.weak_dml():
            actual=mutation['actual']
            prior=[n for n in observer.data() if n['actual']['pid']==actual['pid'] and n['actual']['xid']==actual['xid'] and n['sequence']<mutation['sequence']]
            self.assertTrue(prior,'actual same-transaction history observation must precede weak DML')
        for xid in {n['actual']['xid'] for n in observer.weak_dml()}:
            first=min(n['sequence'] for n in observer.weak_dml() if n['actual']['xid']==xid)
            self.assertTrue(all(n['sequence']<first for n in observer.data() if n['actual']['xid']==xid),'preclassify this article unit before deleting any pair')
        emit('history_observation_contract',pair_count=pair_count,reader_calls=observer.reader_calls,data_SELECTs=len(observer.data()),fixed_SHOW_count=len(shows))

    def normal_protected(self, d, path):
        d.weak_precondition('profile' if path in ('profile','global','profile_pair','scan_cli') else 'article')
        before=self.state()
        with _Observe(connection) as observer:result=self.invoke(d,path)
        after=self.state();self.check_preserved(before,after,d,path,observer)
        self.assertEqual(self.counts(result,path),(0,0,0));self.check_observation(observer,d)
        return result,observer

    def rescope_K2(self, d):
        d.pack['request_id']=d.token+'-K2';d.scope['request_id']=d.pack['request_id']
        d.path.write_bytes(existing_fixture.fixture_data.raw(d.pack));d.path.chmod(0o600)
        d.scope['bundle_sha256']=sha(d.path.read_bytes())

    def check_isolation_error(self, error):
        if isinstance(error,DatabaseError):
            raise ScannerScenarioError('driver error before stable isolation rejection; retain SQLSTATE '+str(sqlstate(error))) from error
        self.assertIsNotNone(error,'unsupported actual transaction must reject before weak DML')
        self.assertEqual(type(error).__name__,'PairHistoryTransactionError')
        self.assertEqual(str(error),ISOLATION_CODE)

    def test_indexed_marker_erasure_blocks_real_tasks_and_CLI(self):
        for path in ('article','profile','global','profile_pair','scan_cli','reprocess'):
            with self.subTest(path=path),self.domain('erase-'+path) as d:
                self.prepare(d,'erase');self.normal_protected(d,path)

    def test_deleted_indexed_pair_is_not_recreated_in_real_entrypoints(self):
        for path in ('article','profile','global','scan_cli','reprocess'):
            with self.subTest(path=path),self.domain('missing-'+path) as d:
                self.prepare(d,'missing');self.normal_protected(d,path)
                self.assertEqual(d.rows(),[])

    def test_replacement_current_PK_is_protected_not_historical_PK(self):
        for path in ('direct','article','profile','reprocess'):
            with self.subTest(path=path),self.domain('replacement-'+path) as d:
                self.prepare(d,'replacement');current=d.rows()[0]['id']
                result,observer=self.normal_protected(d,path)
                if path=='direct':
                    self.assertIn(current,result['protected_ids']);self.assertNotIn(d.original_link_id,result['protected_ids'])

    def test_indexed_erased_relation_is_not_deleted_by_real_resolver(self):
        for path in ('direct','article','reprocess'):
            with self.subTest(path=path),self.domain('delete-'+path) as d:
                self.prepare(d,'erase')
                NewsArticle.objects.filter(pk=d.article.pk).update(title_ja='',body_ja_raw='No runners were named.',body_ja_normalized='')
                d.weak_precondition('article',delete=True);before=self.state()
                with _Observe(connection) as observer:result=self.invoke(d,path)
                self.check_preserved(before,self.state(),d,path,observer)
                self.assertEqual(self.counts(result,path),(0,0,0));self.check_observation(observer,d)

    def test_current_manual_removed_and_marked_priority_needs_no_index_permission(self):
        for path in ('article','profile','reprocess'):
            for current in ('manual','removed','marked'):
                with self.subTest(path=path,current=current),self.domain('priority-'+path+'-'+current) as d:
                    self.capture(d)
                    if current!='marked':d.staff('confirm' if current=='manual' else 'remove')
                    before=self.state()
                    with _Observe(connection) as observer:result=self.invoke(d,path)
                    self.check_preserved(before,self.state(),d,path,observer)
                    self.assertEqual(self.counts(result,path),(0,0,0))
                    self.assertEqual(observer.reader_calls,[],'old complete zero-DML protection remains first')

    def test_mixed_profile_scan_blocks_indexed_but_updates_ordinary_NO_INDEX(self):
        with self.domain('mixed-profile') as d:
            self.prepare(d,'erase')
            ordinary=NewsArticle.objects.create(source_site='tdn',source_mode='latest',source_article_id='c262-ordinary',
                source_url='https://example.invalid/ordinary',title_ja='Aurora won.',body_ja_raw='Aurora won.',source_language='en',
                workflow_status='published',published_at=timezone.now(),published_to_web_at=timezone.now())
            weak=ArticleHorseLink.objects.create(article=ordinary,horse_profile=d.horse,status='auto',source='ordinary',confidence=17)
            match=horse_profiles._match_article(ordinary,d.horse,horse_profiles._profile_match_terms(d.horse))
            require(match is not None and match.status=='auto' and match.confidence==95,'actual ordinary AUTO95 prerequisite')
            require(classify_pair_receipt_history(ordinary.pk,d.horse.pk)['state']=='UNKNOWN_NO_INDEX','ordinary fixture unexpectedly indexed')
            before=d.state();archive_before=rows(self.Index)
            with _Observe(connection) as observer:result=self.invoke(d,'profile')
            weak.refresh_from_db();self.assertEqual(d.state(),before);self.assertEqual(rows(self.Index),archive_before)
            self.assertEqual((weak.source,weak.status,weak.confidence),('auto_match','auto',95));self.assertEqual(result['updated'],1)
            self.check_observation(observer,d,pair_count=2)
            emit('mixed_policy',protected_pair=(d.article.pk,d.horse.pk),ordinary_pair=(ordinary.pk,d.horse.pk),result=result)

    def test_mixed_article_scan_blocks_indexed_and_keeps_ordinary_policy(self):
        with self.domain('mixed-article') as d:
            self.prepare(d,'erase')
            term=TermEntry.objects.create(term_type='horse',source_ja='Solstice',target_zh='至日',source_language='en')
            horse=HorseProfile.objects.create(primary_term=term,original_name='Solstice',review_status='published')
            NewsArticle.objects.filter(pk=d.article.pk).update(body_ja_raw='Aurora and Solstice won.',body_ja_normalized='')
            resolution=self.resolution(d)
            require({d.term.pk,term.pk}<={x.term_id for x in resolution.entities},'real two-target resolver prerequisite')
            ordinary=ArticleHorseLink.objects.create(article=d.article,horse_profile=horse,status='auto',source='ordinary',confidence=17)
            protected_before=d.rows();archive_before=rows(self.Index)
            with _Observe(connection) as observer:result=self.invoke(d,'article')
            self.assertEqual(d.rows(),protected_before);self.assertEqual(rows(self.Index),archive_before)
            ordinary.refresh_from_db();self.assertEqual(ordinary.source,'contextual_entity_resolution');self.assertEqual(result['updated'],1)
            self.check_observation(observer,d,pair_count=2)

    def test_different_K_does_not_release_first_pair_archive(self):
        for path in ('article','profile'):
            with self.subTest(path=path),self.domain('K2-'+path) as d:
                self.prepare(d,'missing');original=rows(self.Index);self.rescope_K2(d)
                result=commit_strong_horse_binding(d.handle,d.actor)
                require(result.get('status')=='history_conflict','current first-pair conflict prerequisite: '+repr(result))
                self.normal_protected(d,path);self.assertEqual(rows(self.Index),original)

    def test_corrupt_or_conflicting_index_candidate_never_falls_back_or_repairs(self):
        for mode in ('hash','protocol','oversize','duplicate'):
            for path in ('article','profile'):
                with self.subTest(mode=mode,path=path),self.domain('bad-'+mode+'-'+path) as d:
                    self.prepare(d,'erase');archive=self.Index.objects.get(article_id_snapshot=d.article.pk,profile_id_snapshot=d.horse.pk)
                    with index_fixture.HorseArticlePairReceiptIndexTests._owner_corruption(self):
                        if mode=='duplicate':
                            data=row(archive);data.pop('id');self.Index.objects.create(**data)
                        else:
                            changes=({'receipt_detail_sha256':'0'*64} if mode=='hash' else
                                     {'protocol_version':'unsupported'} if mode=='protocol' else
                                     {'receipt_detail':'x'*(4_194_304+1),'receipt_detail_sha256':'0'*64})
                            index_fixture.HorseArticlePairReceiptIndexTests._owner_update(self,archive.pk,**changes)
                        expected='UNKNOWN_CONFLICT' if mode=='duplicate' else 'UNKNOWN_CORRUPT_OR_UNSUPPORTED'
                        require(classify_pair_receipt_history(d.article.pk,d.horse.pk)['state']==expected,'real corrupt-candidate prerequisite')
                        _,observer=self.normal_protected(d,path)
                        if mode=='oversize':
                            self.assertTrue(any('OCTET_LENGTH' in n['sql'].upper() for n in observer.data()))
                            self.assertFalse(any('receipt_detail' in n.get('columns',()) for n in observer.data()))

    def test_real_driver_errors_roll_back_pair_and_restore_outer_caller_GUC(self):
        for statement,code in (('SELECT 1/0','22012'),('SELECT 1 FROM stable_c262_missing_relation','42P01'),('SELECT pg_sleep(0.2)','57014')):
            for path in ('direct','profile'):
                with self.subTest(SQLSTATE=code,path=path),self.domain('driver-'+code+'-'+path) as d:
                    self.prepare(d,'erase');before=self.state()
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL statement_timeout='1s'");cursor.execute("SET LOCAL lock_timeout='700ms'")
                        caller=metadata(connection)
                        with _Observe(connection,fault=real_fault(statement,code)) as observer:
                            result,error=self.outcome(lambda:self.invoke(d,path))
                        restored=metadata(connection)
                        after=self.state()
                    emit('actual_driver_result',expected_SQLSTATE=code,error_type=type(error).__name__ if error else None,
                         actual_SQLSTATE=sqlstate(error),faults=observer.faults,caller_GUC=caller,restored_GUC=restored)
                    self.assertIsInstance(error,DatabaseError)
                    self.assertEqual(sqlstate(error),code);self.assertEqual(len(observer.faults),1)
                    self.assertEqual((restored['statement_timeout'],restored['lock_timeout']),(caller['statement_timeout'],caller['lock_timeout']))
                    self.check_preserved(before,after,d,path,observer,error=True)

    def test_public_reprocess_driver_error_has_only_real_failed_audit(self):
        with self.domain('driver-public-reprocess') as d:
            self.prepare(d,'erase');before=self.state()
            with _Observe(connection,fault=real_fault('SELECT 1/0','22012')) as observer:
                result,error=self.outcome(lambda:self.invoke(d,'reprocess'))
            after=self.state();emit('public_failed_reprocess',result=result,error=str(error),faults=observer.faults)
            self.assertIsNone(error);self.assertEqual(result['status'],'failed')
            self.assertEqual(len(observer.faults),1)
            self.assertTrue(any(n.get('SQLSTATE')=='22012' for n in observer.notes))
            self.check_preserved(before,after,d,'reprocess',observer,error=True)

    def test_real_preview_is_readonly_and_commit_reobserves_later_capture(self):
        with self.domain('preview') as d:
            before=self.state()
            preview=horse_profiles.reconcile_article_horse_links(d.article,self.resolution(d),commit=False)
            require(preview['create'],'real preview create prerequisite absent')
            self.assertEqual(self.state(),before)
            self.prepare(d,'missing')
            before=self.state()
            with _Observe(connection) as preview_observer:
                new_preview=horse_profiles.reconcile_article_horse_links(d.article,self.resolution(d),commit=False)
            self.assertEqual(self.state(),before)
            self.assertEqual((new_preview['create'],new_preview['update'],new_preview['delete_ids']),([],[],[]))
            self.normal_protected(d,'article')
            emit('preview_not_permit',initial_preview=preview,later_preview=new_preview,preview_reader_calls=preview_observer.reader_calls)

    def ordinary_delete_set(self, d, count):
        NewsArticle.objects.filter(pk=d.article.pk).update(title_ja='',body_ja_raw='No entrants were named.',body_ja_normalized='')
        horses=[d.horse]
        for number in range(count-1):
            term=TermEntry.objects.create(term_type='horse',source_ja='C262Budget'+str(number),target_zh='预算马'+str(number),source_language='en')
            horses.append(HorseProfile.objects.create(primary_term=term,original_name=term.source_ja,review_status='published'))
        for horse in horses:ArticleHorseLink.objects.create(article=d.article,horse_profile=horse,status='auto',source='ordinary',confidence=17)
        d.weak_precondition('article',delete=True)
        return horses

    def test_exactly16_real_pairs_observed_once_then_ordinary_policy_deletes(self):
        with self.domain('budget16') as d:
            horses=self.ordinary_delete_set(d,PAIR_LIMIT)
            with _Observe(connection) as observer:result=self.invoke(d,'direct')
            self.assertEqual(len(result['delete_ids']),PAIR_LIMIT);self.assertFalse(ArticleHorseLink.objects.filter(article=d.article).exists())
            self.check_observation(observer,d,pair_count=PAIR_LIMIT)
            self.assertEqual({x['profile_id'] for x in observer.reader_calls},{h.pk for h in horses})
            self.assertLessEqual(len(observer.data()),DATA_SELECT_LIMIT)
            emit('bounded_observation_inputs',pairs=PAIR_LIMIT,data_SELECTs=len(observer.data()),
                 raw_UTF8_logical_limit=RAW_INPUT_LIMIT,Python_heap_hard_limit_proved=False,
                 actual_max_sized_archive_input_exercised=False)

    def test_over16_real_action_pairs_reject_before_any_delete(self):
        with self.domain('budget17') as d:
            self.ordinary_delete_set(d,PAIR_LIMIT+1);before=self.state()
            with _Observe(connection) as observer:result,error=self.outcome(lambda:self.invoke(d,'direct'))
            after=self.state();emit('actual_pair_budget_result',result=result,error_type=type(error).__name__ if error else None,error=str(error))
            self.check_preserved(before,after,d,'direct',observer,error=True)
            self.assertIsInstance(error,ValueError);self.assertEqual(str(error),PAIR_BUDGET_CODE)
            self.assertLessEqual(len(observer.data()),DATA_SELECT_LIMIT,'no truncation followed by unchecked writes')

    def test_real_elapsed_guard_budget_rejects_before_any_ordinary_delete(self):
        with self.domain('elapsed-budget') as d:
            self.ordinary_delete_set(d,PAIR_LIMIT);before=self.state();delays=[]
            def after(note):
                if INDEX_TABLE in note['sql'] and note['sql'].lstrip().upper().startswith('SELECT'):
                    # Actual wall-clock delay after the unchanged real read;
                    # no invented response, patched clock or reader return.
                    started=time.monotonic();time.sleep(.4)
                    delays.append(time.monotonic()-started)
            started=time.monotonic()
            with _Observe(connection,after=after) as observer:
                result,error=self.outcome(lambda:self.invoke(d,'direct'))
            seconds=time.monotonic()-started;after_state=self.state()
            emit('actual_elapsed_budget_result',seconds=seconds,actual_read_delays=delays,
                 result=result,error_type=type(error).__name__ if error else None,error=str(error))
            self.check_preserved(before,after_state,d,'direct',observer,error=True)
            self.assertIsInstance(error,ValueError);self.assertEqual(str(error),ELAPSED_BUDGET_CODE)
            self.assertGreaterEqual(sum(delays),5);self.assertLess(seconds,TOTAL_SECONDS)
            self.assertLessEqual(len(observer.data()),DATA_SELECT_LIMIT)

    def test_temporary_GUC_never_relaxes_stricter_caller_and_restores_normally(self):
        for statement,lock in (('0','0'),('1s','700ms')):
            with self.subTest(statement=statement,lock=lock),self.domain('GUC-'+statement) as d:
                self.prepare(d,'erase')
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",(statement,lock))
                    caller=metadata(connection);before=self.state()
                    with _Observe(connection) as observer:result=self.invoke(d,'direct')
                    after=self.state();restored=metadata(connection)
                self.check_preserved(before,after,d,'direct',observer);self.assertEqual(self.counts(result,'direct'),(0,0,0))
                self.check_observation(observer,d)
                for note in observer.data():
                    for key in ('statement_timeout','lock_timeout'):
                        observed=milliseconds(note['actual'][key]);limit=milliseconds(caller[key])
                        self.assertGreater(observed,0);self.assertLessEqual(observed,2000)
                        if limit:self.assertLessEqual(observed,limit)
                self.assertEqual((caller['statement_timeout'],caller['lock_timeout']),(restored['statement_timeout'],restored['lock_timeout']))
                emit('temporary_GUC_minimum',caller=caller,during=[x['actual'] for x in observer.data()],restored=restored)

    def test_actual_RC_admission_precedes_history_on_each_real_backend(self):
        for path in ('article','profile','global','profile_pair','reprocess'):
            with self.subTest(path=path),self.domain('RC-'+path) as d:
                self.prepare(d,'missing');self.normal_protected(d,path)

    def test_actual_SERIALIZABLE_and_unsupported_transaction_reject_before_weak_DML(self):
        for level in ('SERIALIZABLE','READ UNCOMMITTED'):
            for path in ('article','profile','global','profile_pair','internal_reprocess'):
                with self.subTest(level=level,path=path),self.domain('level-'+level.replace(' ','-')+'-'+path) as d:
                    # No index: this is the original ordinary policy, fenced by
                    # the actual writable-transaction prerequisite only.
                    d.weak_precondition('profile' if path in ('profile','global','profile_pair') else 'article')
                    with transaction.atomic():
                        with connection.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL '+level)
                        actual=metadata(connection);before=self.state()
                        with _Observe(connection) as observer:result,error=self.outcome(lambda:self.invoke(d,path))
                        after=self.state();transaction.set_rollback(True)
                    emit('unsupported_actual_transaction',level=actual,result=result,error_type=type(error).__name__ if error else None,
                         error=str(error),SQLSTATE=sqlstate(error),test_outer_rollback_only_cleanup=True)
                    self.check_isolation_error(error);self.check_preserved(before,after,d,path,observer,error=True)
                    self.assertEqual(observer.reader_calls,[],'no old-snapshot history lookup before rejection')
                    self.assertTrue(any(re.fullmatch(r'\s*SHOW\s+"?transaction_isolation"?\s*;?\s*',x['sql'],re.I) for x in observer.notes))

    def test_readonly_pair_reader_remains_usable_in_real_RR_transaction(self):
        with self.domain('readonly-RR') as d:
            self.capture(d);before=self.state()
            with transaction.atomic():
                with connection.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                actual=metadata(connection)
                result=classify_pair_receipt_history(d.article.pk,d.horse.pk)
            self.assertEqual(actual['isolation'],'repeatable read')
            self.assertEqual(result['state'],'INDEXED_HISTORY');self.assertEqual(result['weak_mutation_allowed'],False)
            self.assertEqual(self.state(),before);emit('readonly_RR_control',actual=actual,result=result)

    def test_true_ordinary_NO_INDEX_weak_first_keeps_existing_strong_conflict_policy(self):
        for path in ('article','profile'):
            with self.subTest(path=path),self.domain('ordinary-first-'+path) as d:
                require(classify_pair_receipt_history(d.article.pk,d.horse.pk)['state']=='UNKNOWN_NO_INDEX','ordinary prerequisite')
                d.weak_precondition('profile' if path=='profile' else 'article')
                with _Observe(connection) as observer:result=self.invoke(d,path)
                self.assertEqual(result['created'],1);self.check_observation(observer,d)
                before=self.state();strong=commit_strong_horse_binding(d.handle,d.actor)
                self.assertEqual(strong['status'],'existing_pair_conflict');self.assertEqual(self.state(),before)
                self.assertEqual(classify_pair_receipt_history(d.article.pk,d.horse.pk)['state'],'UNKNOWN_NO_INDEX')
                emit('ordinary_policy_remains_independent',weak_result=result,strong_result=strong)

    def worker_ok(self, worker):
        if worker['error'] is not None:
            raise ScannerScenarioError('actual worker/fixture error '+worker['name']+': '+str(worker['error'])) from worker['error']
        require(worker['closed'],'worker connection cleanup incomplete')

    def actual_parent(self, note):
        return note.get('lock') is not None and note['lock']['primary_table']=='stable_newsarticle'

    def test_RC_strong_first_actual_parent_block_then_no_weak_recreation(self):
        for path in ('article','profile','global','reprocess'):
            with self.subTest(path=path),self.domain('RC-strong-first-'+path) as d:
                d.weak_precondition('profile' if path in ('profile','global') else 'article')
                with _Window(self) as window:
                    def strong(worker, db):
                        with _Observe(db,role='strong-control') as observer:
                            worker['observer']=observer
                            with transaction.atomic():
                                result=self.capture(d)
                                ArticleHorseLink.objects.filter(article=d.article,horse_profile=d.horse).delete()
                                worker['expected']=self.state()
                                emit('strong_uncommitted_negative_missing',actual=metadata(db),result=result,
                                     archive_SHA=sha(raw(worker['expected']['indexes'])),negative_Link_delete=True)
                                window.release('A_ready');window.wait('release_A')
                        emit('strong_natural_commit',result=result,actual=metadata(db))
                        return result
                    def weak(worker, db):
                        def before(note):
                            if self.actual_parent(note):window.release('B_attempted')
                        with _Observe(db,before=before) as observer:
                            worker['observer']=observer;return self.invoke(d,path)
                    a=window.start('A',strong);window.wait('A_ready')
                    b=window.start('B',weak);window.blocked(b,a)
                    window.release('release_A');window.wait('A_done');window.wait('B_done')
                self.worker_ok(a);self.worker_ok(b)
                after=self.state();self.check_preserved(a['expected'],after,d,path,b['observer'])
                self.assertEqual(self.counts(b['value'],path),(0,0,0));self.check_observation(b['observer'],d)
                emit('RC_strong_first_complete',path=path,strong_result=a['value'],weak_result=b['value'],
                     actual_blockers=window.samples,final=after['links'],archives=after['indexes'],natural_commit=True,cleanup=True)

    def test_RC_weak_first_existing_archive_blocks_K2_with_real_parent_wait(self):
        for path in ('article','profile'):
            with self.subTest(path=path),self.domain('RC-weak-first-'+path) as d:
                self.prepare(d,'missing');self.rescope_K2(d)
                d.weak_precondition('profile' if path=='profile' else 'article');before=self.state()
                with _Window(self) as window:
                    def weak(worker, db):
                        first=[]
                        def after(note):
                            if self.actual_parent(note) and not first:
                                first.append(True);window.release('B_parent');window.wait('release_B')
                        with _Observe(db,after=after) as observer:
                            worker['observer']=observer;return self.invoke(d,path)
                    def strong(worker, db):
                        first=[]
                        def pre(note):
                            if self.actual_parent(note):window.release('A_attempted')
                        def post(note):
                            if self.actual_parent(note) and not first:
                                first.append(True);window.release('A_parent');window.wait('release_A')
                        with _Observe(db,before=pre,after=post,role='strong-control') as observer:
                            worker['observer']=observer;return commit_strong_horse_binding(d.handle,d.actor)
                    b=window.start('B',weak);window.wait('B_parent')
                    a=window.start('A',strong);window.blocked(a,b)
                    window.release('release_B');window.wait('B_done');window.wait('A_parent')
                    after_B=self.state();emit('B_committed_before_K2_decision',actual=metadata(connection),links=after_B['links'],Index_SHA=sha(raw(after_B['indexes'])))
                    window.release('release_A');window.wait('A_done')
                self.worker_ok(a);self.worker_ok(b)
                self.check_preserved(before,after_B,d,path,b['observer'])
                self.assertEqual(self.counts(b['value'],path),(0,0,0));self.check_observation(b['observer'],d)
                self.assertEqual(a['value']['status'],'history_conflict','never require K2 created over first receipt')
                self.assertEqual(self.state(),after_B)
                emit('RC_weak_first_complete',path=path,weak_result=b['value'],K2_result=a['value'],actual_blockers=window.samples,cleanup=True)

    def old_RR_window(self, d, path):
        """Old snapshot is real; only the fixture sets transaction isolation."""
        d.weak_precondition('profile' if path in ('profile','global','profile_pair') else 'article')
        with _Window(self) as window:
            def weak(worker, db):
                with transaction.atomic():
                    with db.cursor() as cursor:cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    worker['old_actual']=metadata(db)
                    worker['old_observation']=classify_pair_receipt_history(d.article.pk,d.horse.pk)
                    require(worker['old_actual']['isolation']=='repeatable read' and worker['old_observation']['state']=='UNKNOWN_NO_INDEX',
                            'real old RR snapshot prerequisite')
                    emit('RR_snapshot_established',actual=worker['old_actual'],observation=worker['old_observation'])
                    window.release('B_snapshot');window.wait('A_ready')
                    def before(note):
                        if self.actual_parent(note):window.release('B_attempted')
                    with _Observe(db,before=before) as observer:
                        worker['observer']=observer;return self.invoke(d,path)
            def strong(worker, db):
                with _Observe(db,role='strong-control') as observer:
                    worker['observer']=observer
                    with transaction.atomic():
                        article_before=row(NewsArticle.objects.get(pk=d.article.pk))
                        result=self.capture(d)
                        ArticleHorseLink.objects.filter(article=d.article,horse_profile=d.horse).delete()
                        article_after=row(NewsArticle.objects.get(pk=d.article.pk))
                        require(article_before==article_after,'RR counterexample parent was updated; do not assume 40001')
                        worker['expected']=self.state()
                        emit('RR_parent_only_locked_not_updated',before_SHA=sha(raw(article_before)),after_SHA=sha(raw(article_after)),actual=metadata(db))
                        window.release('A_ready');window.wait('release_A')
                return result
            b=window.start('B',weak);window.wait('B_snapshot')
            a=window.start('A',strong);window.wait('A_ready');window.blocked(b,a)
            window.release('release_A');window.wait('A_done');window.wait('B_done')
        self.worker_ok(a)
        require(b['closed'] and b['observer'] is not None,'RR worker/window cleanup prerequisite')
        observer=metadata(connection)
        require(observer['isolation']=='read committed' and observer['pid'] not in (a['pid'],b['pid']),
                'independent fresh RC final observer required')
        after=self.state()
        emit('RR_final_independent_RC_state',path=path,observer=observer,old_RR=b['old_actual'],
             old_observation=b['old_observation'],actual_blockers=window.samples,
             weak_result=b['value'],weak_error_type=type(b['error']).__name__ if b['error'] else None,
             weak_error=str(b['error']),SQLSTATE=sqlstate(b['error']),links=after['links'],indexes=after['indexes'],
             before_SHA=sha(raw(a['expected'])),after_SHA=sha(raw(after)),cleanup=True)
        if path=='reprocess':
            if b['error'] is not None:raise ScannerScenarioError('public reprocess unexpectedly escaped instead of its existing failed result') from b['error']
            self.assertEqual(b['value']['status'],'failed');self.assertEqual(b['value']['error'],ISOLATION_CODE)
        else:self.check_isolation_error(b['error'])
        self.check_preserved(a['expected'],after,d,path,b['observer'],error=True)
        self.assertEqual(b['observer'].reader_calls,[],'no new history read from an admitted old RR snapshot')
        shows=[x for x in b['observer'].notes if re.fullmatch(r'\s*SHOW\s+"?transaction_isolation"?\s*;?\s*',x['sql'],re.I)]
        self.assertTrue(shows)
        self.assertTrue(all(x['actual']['pid']==b['pid'] and x['actual']['isolation']=='repeatable read' for x in shows))
        self.assertTrue(all(x['actual']['isolation']=='repeatable read' for x in b['observer'].notes),'product cannot silently switch isolation')
        self.assertFalse(any(re.match(r'\s*SET\s+(TRANSACTION|SESSION)\b',x['sql'],re.I) for x in b['observer'].notes),'no product isolation change')
        emit('RR_guard_rejection_complete',path=path,actual_error=ISOLATION_CODE,independent_RC_observer=observer,actual_blockers=window.samples,cleanup=True)

    def test_real_old_RR_snapshot_scanners_and_outer_reprocess_reject_before_weak_DML(self):
        for path in ('article','profile','global','profile_pair','internal_reprocess'):
            with self.subTest(path=path),self.domain('RR-'+path) as d:self.old_RR_window(d,path)

    def test_real_old_RR_public_reprocess_keeps_only_failed_audit(self):
        with self.domain('RR-public') as d:self.old_RR_window(d,'reprocess')
