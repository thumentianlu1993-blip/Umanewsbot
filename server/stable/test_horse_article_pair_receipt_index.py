"""C255 source-only schema/capture/private-reader oracle; not executed here.

Missing model/table/API is NOT_READY ERROR, never a manufactured business RED.
Positive archives come only from the real admitted writer. Owner corruption
below is explicit negative preparation, not a trusted receipt producer. No
scanner/enforce/release integration, production retention policy, new DB roles
or same-credential INSERT-authentication guarantee belongs to this slice.
"""
import copy
import hashlib
import importlib
import inspect
import json
import re
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable import test_horse_article_binding_persistence as fixture_data
from stable.models import ArticleHorseLink, HorseExternalIdentity, HorseProfile, NewsArticle, OperationLog, TaskExecutionLog, TermEntry
from stable.services.horse_article_binding_persistence import commit_strong_horse_binding


MODULE = "stable.services.horse_article_pair_receipt_index"
FIELDS = {"id", "article_id_snapshot", "profile_id_snapshot", "producer_namespace", "request_id",
          "request_key", "operation_log_id_snapshot", "original_link_id", "original_actor_id",
          "receipt_detail", "receipt_detail_sha256", "protocol_version", "recorded_at"}
UNIQUES = {"uq_horse_pair_receipt_pair": ("article_id_snapshot", "profile_id_snapshot"),
           "uq_horse_pair_receipt_key": ("request_key",),
           "uq_horse_pair_receipt_log": ("operation_log_id_snapshot",)}
CHECKS = {"ck_hpair_index_ids", "ck_hpair_index_hashes", "ck_hpair_index_bytes"}
BOUNDARIES = {"weak_mutation_allowed": False, "historical_coverage": "indexed_receipt_only",
              "historical_request_uniqueness": "not_proved", "current_write_authority": "not_evaluated",
              "source_license": "not_evaluated", "automatic_action": "none"}
REFERENCES = {"index_id", "request_key", "operation_log_id", "original_link_id", "original_actor_id",
              "receipt_detail_sha256", "after_sha256"}
RESULT_KEYS = {"schema_version", "state", "article_id", "profile_id", *REFERENCES, *BOUNDARIES}
MAX_BYTES = 4_194_304
TOTAL_SECONDS, BARRIER_SECONDS = 30, 5


class PairIndexScenarioError(RuntimeError):
    """Fixture/API/role/driver/thread prerequisites are ERROR, not business RED."""


def require(value, message):
    if not value:
        raise PairIndexScenarioError(message)


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(row):
    return json.loads(json.dumps({f.attname: getattr(row, f.attname) for f in row._meta.concrete_fields},
                                default=lambda v: v.isoformat()))


def rows(model):
    return copy.deepcopy(list(model.objects.order_by("pk").values()))


def sqlstate(error):
    cause = error.__cause__
    return getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)


def emit(kind, **data):
    print("\nC255_PAIR_INDEX " + json.dumps({"kind": kind, **data}, ensure_ascii=False, default=str), flush=True)


def _lock_query_target(sql):
    """Observe generated SELECT row locks, never rewrite or execute SQL.

    Keep quoted names/literals opaque and ignore nested SELECT's FROM. An OF
    list names relation aliases; absent OF locks all eligible FROM relations,
    including JOINs. Unsupported row-lock shapes raise instead of disappearing
    from the observed sequence. This is a test observer, not a SQL authority.
    """
    tokens=re.findall(r'''--[^\n]*|/\*.*?\*/|"(?:[^"]|"")*"|'(?:[^']|'')*'|[A-Za-z_][A-Za-z_0-9$]*|%s|[^\s]''',sql,re.S)
    top=[];depth=0
    for token in tokens:
        if token.startswith(('--','/*')):continue
        if token==')':depth-=1
        if depth==0:top.append(token)
        if token=='(':depth+=1
        if depth<0:raise ValueError('unbalanced SQL parentheses')
    if depth:raise ValueError('unbalanced SQL parentheses')
    def word(token,value):return not token.startswith(('"',"'")) and token.upper()==value
    def identifier(token):
        if token.startswith('"') and token.endswith('"'):return token[1:-1].replace('""','"')
        if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9$]*',token):return token.lower()
        raise ValueError('unsupported relation/alias token: '+token)
    strengths=(('NO','KEY','UPDATE'),('KEY','SHARE'),('UPDATE',),('SHARE',))
    locks=[]
    for i,token in enumerate(top):
        if not word(token,'FOR'):continue
        for strength in strengths:
            if len(top)>i+len(strength) and all(word(top[i+1+j],v) for j,v in enumerate(strength)):
                locks.append((i,' '.join(strength),i+1+len(strength)));break
    lexical_locks=sum(
        any(len(tokens)>i+len(s) and all(word(tokens[i+1+j],v) for j,v in enumerate(s)) for s in strengths)
        for i,x in enumerate(tokens) if word(x,'FOR'))
    if lexical_locks!=len(locks):raise ValueError('nested row-lock clause is not a main-relation observation')
    if not locks:return None
    if len(locks)!=1 or not word(top[0],'SELECT'):raise ValueError('unsupported top-level row-lock statement')
    lock_at,strength,after_lock=locks[0]
    from_positions=[i for i,x in enumerate(top[:lock_at]) if word(x,'FROM')]
    if len(from_positions)!=1:raise ValueError('ambiguous main FROM')
    start=from_positions[0]+1
    reserved={'JOIN','INNER','LEFT','RIGHT','FULL','CROSS','NATURAL','OUTER','ON','USING',
              'WHERE','GROUP','HAVING','ORDER','LIMIT','OFFSET','FETCH','FOR','WINDOW',
              'UNION','INTERSECT','EXCEPT','TABLESAMPLE'}
    def relation(i):
        if i>=len(top):raise ValueError('missing FROM relation')
        if word(top[i],'ONLY'):i+=1
        if i>=len(top):raise ValueError('missing ONLY relation')
        parts=[identifier(top[i])];i+=1
        while i+1<len(top) and top[i]=='.':parts.append(identifier(top[i+1]));i+=2
        alias=None
        if i<len(top) and word(top[i],'AS'):
            if i+1>=len(top):raise ValueError('missing FROM alias')
            alias=identifier(top[i+1]);i+=2
        elif i<len(top) and (top[i].startswith('"') or re.fullmatch(r'[A-Za-z_][A-Za-z_0-9$]*',top[i])) and top[i].upper() not in reserved:
            alias=identifier(top[i]);i+=1
        return dict(relation_parts=parts,table=parts[-1],alias=alias,lock_name=alias or parts[-1]),i
    primary,end=relation(start);relations=[primary]
    from_end=next((i for i in range(end,lock_at) if any(word(top[i],x) for x in
                  ('WHERE','GROUP','HAVING','ORDER','LIMIT','OFFSET','FETCH','WINDOW'))),lock_at)
    for i in range(end,from_end):
        if word(top[i],'JOIN') or top[i]==',':relations.append(relation(i+1)[0])
    of=[]
    if after_lock<len(top) and word(top[after_lock],'OF'):
        i=after_lock+1
        while i<len(top):
            of.append(identifier(top[i]));i+=1
            if i>=len(top) or top[i]!=',':break
            i+=1
        if not of:raise ValueError('empty row-lock OF list')
    else:i=after_lock
    if i<len(top) and word(top[i],'NOWAIT'):i+=1
    elif i+1<len(top) and word(top[i],'SKIP') and word(top[i+1],'LOCKED'):i+=2
    if top[i:] not in ([],[';']):raise ValueError('unsupported row-lock suffix')
    by_name={r['lock_name']:r for r in relations}
    if len(by_name)!=len(relations) or any(x not in by_name for x in of):
        raise ValueError('unresolved or duplicate row-lock alias')
    return dict(primary_table=primary['table'],primary_relation=primary,
                joined_relations=relations[1:],strength=strength,of_aliases=of,
                lock_scope='explicit_OF' if of else 'implicit_all_FROM_relations',
                locked_relations=[by_name[x] for x in of] if of else relations,
                primary_locked=not of or primary['lock_name'] in of,
                basis='top-level SELECT FROM relation plus alias-resolved FOR lock clause')


class _Producer:
    """Actual synthetic admission material; no product double or old TestCase inheritance."""
    def __init__(self, owner, token="c255", *, peer=None, request_id=None):
        self.owner, self.token = owner, token
        if peer is None:
            self.actor = get_user_model().objects.create_user(username=token, is_staff=True)
            self.other = get_user_model().objects.create_user(username=token+"-reader", is_staff=True)
            self.term = TermEntry.objects.create(term_type="horse", source_ja="Aurora", target_zh="极光", source_language="en")
            self.horse = HorseProfile.objects.create(primary_term=self.term, original_name="Aurora", review_status="published")
            self.identity_bytes = raw(dict(source="the_racing_api", namespace="horse", external_id=token,
                                           horse_profile_id=self.horse.pk))
            self.identity = HorseExternalIdentity.objects.create(horse_profile=self.horse, source="the_racing_api",
                namespace="horse", external_id=token, status="verified", evidence_url="https://example.invalid/identity",
                payload_sha256=sha(self.identity_bytes), verified_at=timezone.now(), verified_by=self.actor)
        else:
            for key in ("actor", "other", "term", "horse", "identity_bytes", "identity"):
                setattr(self, key, getattr(peer, key))
        self.article = NewsArticle.objects.create(source_site="tdn", source_mode="latest", source_article_id=token,
            source_url="https://example.invalid/"+token, title_ja="", body_ja_raw="Aurora won.", source_language="en",
            workflow_status="published", published_at=timezone.now(), published_to_web_at=timezone.now())
        self.pack = fixture_data.HorseArticleBindingPersistenceTests.make_bundle(self)
        self.pack["request_id"] = request_id or token
        self.temp = tempfile.TemporaryDirectory(); owner.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"synthetic-server.json"
        self.scope = dict(bundle_path=str(self.path), bundle_sha256="", producer_namespace="synthetic-server",
            request_id=self.pack["request_id"], article_id=self.article.pk, profile_id=self.horse.pk,
            identity_id=self.identity.pk, actor_ids=[self.actor.pk], revoked=False,
            not_before=(timezone.now()-timedelta(days=1)).isoformat(), expires_at=(timezone.now()+timedelta(days=1)).isoformat(),
            contract_refs=[copy.deepcopy(fixture_data.LITERAL["article_input"]["snapshot"]["evidence"][0]["contract_ref"])],
            responsibility=dict(identity_producer="isolated-fixture", relationship_owner="isolated-fixture",
                                write_owner="explicit-test-domain"))
        self.write()
        self.handle = token; owner.registry[self.handle] = self.scope; owner.producers.append(self)

    def write(self):
        self.path.write_bytes(raw(self.pack)); self.path.chmod(0o600)
        self.scope["bundle_sha256"] = sha(self.path.read_bytes())

    def call(self):
        return commit_strong_horse_binding(self.handle, self.actor)

    def created(self):
        result = self.call()
        require(result.get("status") == "created", "real writer admission/precondition: "+repr(result))
        self.link = ArticleHorseLink.objects.get(pk=result["link_id"])
        self.log = OperationLog.objects.get(pk=result["receipt_id"])
        self.value = json.loads(self.log.detail); self.key = self.link.metadata["request_key"]
        require(raw(self.value).decode()==self.log.detail and self.value["after"]==snapshot(self.link)
                and self.value["after_sha256"]==sha(raw(snapshot(self.link))) and self.log.target_id==self.key,
                "real original receipt does not bind actual full row")
        emit("real_writer_created", result=result, link=snapshot(self.link), log=snapshot(self.log),
             producer_SHA=sha(self.path.read_bytes()))
        return result


class HorseArticlePairReceiptIndexTests(TransactionTestCase):
    def setUp(self):
        require(connection.vendor=="postgresql" and connection.get_autocommit() and not connection.in_atomic_block,
                "NOT_READY: independent isolated PostgreSQL required")
        try:
            self.Index = apps.get_model("stable", "HorseArticlePairReceiptIndex")
        except LookupError as error:
            raise PairIndexScenarioError("NOT_READY: index model absent") from error
        require(self.Index._meta.db_table in connection.introspection.table_names(), "NOT_READY: migrated index table absent")
        try:
            self.api = importlib.import_module(MODULE)
        except ModuleNotFoundError as error:
            if error.name==MODULE:
                raise PairIndexScenarioError("NOT_READY: index service absent") from error
            raise
        for name, arguments in (("classify_pair_receipt_history", ("article_id", "profile_id")),
                                ("_capture_created_receipt", ("scope", "actor", "article", "profile", "link", "log"))):
            fn=getattr(self.api,name,None); require(callable(fn), "NOT_READY: API "+name)
            params=inspect.signature(fn).parameters
            require(tuple(params)==arguments and all(p.default is inspect.Parameter.empty and p.kind in
                    {inspect.Parameter.POSITIONAL_OR_KEYWORD,inspect.Parameter.KEYWORD_ONLY} for p in params.values()),
                    "NOT_READY: signature "+name)
        for name in ("PairHistoryInputError", "PairReceiptCaptureError"):
            cls=getattr(self.api,name,None)
            require(inspect.isclass(cls) and issubclass(cls,ValueError), "NOT_READY: error class "+name)
        self.reader=self.api.classify_pair_receipt_history
        self.registry={};self.producers=[]
        context=override_settings(HORSE_ARTICLE_BINDING_HANDLES=self.registry)
        context.enable();self.addCleanup(context.disable)
        self.d=_Producer(self)

    def _state(self):
        return {"tables":{model._meta.label:rows(model) for model in (self.Index,ArticleHorseLink,OperationLog,
                    TaskExecutionLog,NewsArticle,HorseProfile,HorseExternalIdentity,TermEntry,get_user_model())},
                "registry":copy.deepcopy(settings.HORSE_ARTICLE_BINDING_HANDLES),
                "producer_bytes":[p.path.read_bytes() for p in self.producers]}

    def _archives(self, producer=None):
        d=producer or self.d
        return self.Index.objects.filter(article_id_snapshot=d.article.pk,profile_id_snapshot=d.horse.pk)

    def _baseline(self):
        self.d.created()
        archive=list(self._archives())
        require(len(archive)==1, "capture prerequisite missing; primary three-piece test owns business RED")
        self.archive=archive[0]
        require(self.archive.receipt_detail==self.d.log.detail and self.archive.receipt_detail_sha256==sha(self.d.log.detail.encode()),
                "real captured baseline malformed; not a corrupt-fixture business assertion")
        return self.archive

    def _assert_archive(self, archive, d=None):
        d=d or self.d
        self.assertEqual(set(snapshot(archive)),FIELDS)
        for key,value in {"article_id_snapshot":d.article.pk,"profile_id_snapshot":d.horse.pk,
                          "operation_log_id_snapshot":d.log.pk,"original_link_id":d.link.pk,
                          "original_actor_id":d.actor.pk,"producer_namespace":d.scope["producer_namespace"],
                          "request_id":d.scope["request_id"],"request_key":d.key,
                          "receipt_detail":d.log.detail,"receipt_detail_sha256":sha(d.log.detail.encode()),
                          "protocol_version":"l02.pair-receipt-index.v1"}.items():
            self.assertEqual(getattr(archive,key),value,key)
        key=sha(raw(dict(schema="l01.horse-link-request.v1",producer_namespace=archive.producer_namespace,
                         request_id=archive.request_id)))
        self.assertEqual(archive.request_key,key)
        self.assertIsNotNone(archive.recorded_at.utcoffset())
        emit("actual_archive_bound", archive=snapshot(archive), actual_log=snapshot(d.log))

    @contextmanager
    def _capture_trace(self):
        """Observe real private calls/returns, without replacing admission or capture."""
        calls=[];returns=[];previous=sys.getprofile()
        def observe(frame,event,value):
            if frame.f_globals.get('__name__')!=MODULE or frame.f_code.co_name!='_capture_created_receipt':return
            if event=='call':
                local=frame.f_locals
                calls.append({'atomic':connection.in_atomic_block,'autocommit':connection.get_autocommit(),
                    'scope':copy.deepcopy(local['scope']),
                    'actual_types':isinstance(local['actor'],get_user_model()) and isinstance(local['article'],NewsArticle)
                        and isinstance(local['profile'],HorseProfile) and isinstance(local['link'],ArticleHorseLink)
                        and isinstance(local['log'],OperationLog),
                    'link_id':local['link'].pk,'log_id':local['log'].pk,'actor_id':local['actor'].pk})
            elif event=='return':returns.append(value)
        sys.setprofile(observe)
        try:yield calls,returns
        finally:sys.setprofile(previous)

    @contextmanager
    def _reader_observer(self, fault=None):
        notes=[];calls=[];old=sys.getprofile()
        def profile(frame,event,arg):
            if event=='call' and '/stable/services/' in frame.f_code.co_filename and frame.f_code.co_name in {
                'commit_strong_horse_binding','_admit','_capture_created_receipt','scan_article_horse_links',
                'reconcile_article_horse_links','backfill_profile_strong_bindings','enqueue_profile_strong_backfill'}:
                calls.append(frame.f_code.co_name)
        def observe(execute,sql,params,many,context):
            upper=sql.lstrip().upper();note=dict(sql=sql,params=copy.deepcopy(params));notes.append(note)
            self.assertNotRegex(upper,r'^(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b')
            self.assertNotIn('FOR UPDATE',upper);self.assertNotIn('PG_ADVISORY',upper)
            if upper.startswith('SELECT') and 'stable_' in sql:
                self.assertIn(self.Index._meta.db_table,sql)
                for forbidden in ('stable_operationlog','stable_articlehorselink','stable_newsarticle',
                                  'stable_horseprofile','stable_horseexternalidentity'):
                    self.assertNotIn(forbidden,sql,'pair reader cannot rediscover through live entities/logs')
                self.assertRegex(sql,r'"article_id_snapshot"\s*=\s*%s')
                self.assertRegex(sql,r'"profile_id_snapshot"\s*=\s*%s')
                self.assertIn(self._pair[0],params or ());self.assertIn(self._pair[1],params or ())
                self.assertNotRegex(upper,r'COUNT\s*\(')
                predicate=upper.split(' WHERE ',1)[-1].split(' ORDER BY ',1)[0]
                self.assertNotIn('"RECORDED_AT"',predicate,'pair history must not be filtered by age/TTL')
            if upper.startswith('SELECT'):
                self.assertNotIn(get_user_model()._meta.db_table,sql,'historical actor is not current read authority')
            if fault is not None:fault(sql,context)
            value=execute(sql,params,many,context)
            cursor=context.get('cursor')
            if cursor is not None and cursor.description:note['columns']=[c[0] for c in cursor.description]
            return value
        sys.setprofile(profile)
        try:
            with connection.execute_wrapper(observe):yield notes
        finally:
            sys.setprofile(old);self.assertEqual(calls,[])
            emit('reader_SQL',notes=notes,forbidden_core_calls=calls)

    def _read(self, state, *, pair=None):
        self._pair=pair or (self.d.article.pk,self.d.horse.pk)
        before=self._state();tx=(connection.get_autocommit(),connection.in_atomic_block)
        with self._reader_observer() as notes:result=self.reader(*self._pair)
        self.assertEqual(self._state(),before,'private reader wrote or repaired state')
        self.assertEqual((connection.get_autocommit(),connection.in_atomic_block),tx)
        self.assertIs(type(result),dict);self.assertEqual(set(result),RESULT_KEYS)
        self.assertEqual(result['schema_version'],'l02.pair-receipt-history.v1')
        self.assertEqual(result['state'],state);self.assertEqual((result['article_id'],result['profile_id']),self._pair)
        for key,value in BOUNDARIES.items():self.assertEqual(result[key],value)
        if state=='INDEXED_HISTORY':
            archive=self.Index.objects.get(article_id_snapshot=self._pair[0],profile_id_snapshot=self._pair[1])
            for out,field in {'index_id':'id','request_key':'request_key','operation_log_id':'operation_log_id_snapshot',
                              'original_link_id':'original_link_id','original_actor_id':'original_actor_id',
                              'receipt_detail_sha256':'receipt_detail_sha256'}.items():
                self.assertEqual(result[out],getattr(archive,field))
            self.assertEqual(result['after_sha256'],json.loads(archive.receipt_detail)['after_sha256'])
        else:
            for key in REFERENCES:self.assertIsNone(result[key])
        observed=[]
        for row in self.Index.objects.order_by('pk'):
            value=snapshot(row)
            observed.append(dict(id=row.pk,full_row_sha256=sha(raw(value)),
                                 receipt_bytes=len(row.receipt_detail.encode())))
        emit('reader_result_zero_write',result=result,archive_observations=observed)
        return result,notes

    @contextmanager
    def _owner_corruption(self):
        """Explicit isolated-owner fixture only; no application bypass flag."""
        table=self.Index._meta.db_table;q=connection.ops.quote_name;saved=rows(self.Index)
        disabled=False;dropped=[]
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint '
                               'WHERE conrelid=%s::regclass AND contype IN (\'c\',\'u\')',(table,))
                constraints=cursor.fetchall()
                cursor.execute(f'ALTER TABLE {q(table)} DISABLE TRIGGER USER');disabled=True
                for name,definition in constraints:
                    cursor.execute(f'ALTER TABLE {q(table)} DROP CONSTRAINT {q(name)}');dropped.append((name,definition))
            yield
        finally:
            if disabled:
                columns=[f.attname for f in self.Index._meta.concrete_fields]
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(f'DELETE FROM {q(table)}')
                        for row in saved:
                            cursor.execute(f'INSERT INTO {q(table)} ({",".join(q(c) for c in columns)}) '
                                           f'VALUES ({",".join(["%s"]*len(columns))})',[row[c] for c in columns])
                        for name,definition in dropped:
                            cursor.execute(f'ALTER TABLE {q(table)} ADD CONSTRAINT {q(name)} {definition}')
                finally:
                    with connection.cursor() as cursor:cursor.execute(f'ALTER TABLE {q(table)} ENABLE TRIGGER USER')

    def _fault_on_insert(self, table):
        reached=[]
        def fault(execute,sql,params,many,context):
            if sql.lstrip().upper().startswith('INSERT') and table in sql and not reached:
                reached.append(True)
                with context['connection'].connection.cursor() as cursor:
                    with context['connection'].wrap_database_errors:cursor.execute('SELECT 1/0')
                raise PairIndexScenarioError('real SQL division control did not raise')
            return execute(sql,params,many,context)
        return reached,fault

    def _owner_update(self, pk, **changes):
        q=connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute('UPDATE '+q(self.Index._meta.db_table)+' SET '+
                           ','.join(q(k)+'=%s' for k in changes)+' WHERE id=%s',[*changes.values(),pk])

    def _owner_clear(self):
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM '+connection.ops.quote_name(self.Index._meta.db_table))

    def test_real_created_commits_actual_link_log_and_index_bytes_together(self):
        """Primary business assertion catches missing or fabricated capture after actual created."""
        with self._capture_trace() as (calls,returns):self.d.created()
        archive=list(self._archives())
        self.assertEqual(len(archive),1,'real created must commit one captured archive')
        self.assertEqual(len(calls),1);self.assertEqual(len(returns),1)
        self.assertTrue(calls[0]['atomic']);self.assertFalse(calls[0]['autocommit']);self.assertTrue(calls[0]['actual_types'])
        self.assertEqual((calls[0]['link_id'],calls[0]['log_id'],calls[0]['actor_id']),
                         (self.d.link.pk,self.d.log.pk,self.d.actor.pk))
        self.assertEqual(calls[0]['scope'],self.d.scope)
        self.assertIsInstance(returns[0],self.Index);self.assertEqual(returns[0].pk,archive[0].pk)
        self._assert_archive(archive[0])
        self._read('INDEXED_HISTORY')

    def test_schema_nonFK_identity_unique_constraints_and_no_mutable_TTL_fields(self):
        """Catches cascaded historical identity, missing unique keys and mutable archive shape."""
        self.assertEqual({f.attname for f in self.Index._meta.concrete_fields},FIELDS)
        self.assertTrue(all(not f.is_relation for f in self.Index._meta.concrete_fields))
        with connection.cursor() as cursor:
            physical={column.name:column for column in connection.introspection.get_table_description(cursor,self.Index._meta.db_table)}
        self.assertEqual(set(physical),FIELDS)
        for field in self.Index._meta.concrete_fields:
            self.assertFalse(field.null);self.assertEqual(field.column,field.attname)
            self.assertFalse(physical[field.column].null_ok)
        for name in ('article_id_snapshot','profile_id_snapshot','operation_log_id_snapshot','original_link_id','original_actor_id'):
            self.assertIn(self.Index._meta.get_field(name).get_internal_type(),('BigIntegerField','PositiveBigIntegerField'))
        for name in ('request_key','receipt_detail_sha256'):
            self.assertEqual(self.Index._meta.get_field(name).max_length,64)
        self.assertEqual(self.Index._meta.get_field('receipt_detail').get_internal_type(),'TextField')
        self.assertEqual(self.Index._meta.get_field('recorded_at').get_internal_type(),'DateTimeField')
        actual={c.name:tuple(c.fields) for c in self.Index._meta.constraints if hasattr(c,'fields') and c.fields}
        for name,fields in UNIQUES.items():self.assertEqual(actual.get(name),fields)
        names={c.name for c in self.Index._meta.constraints};self.assertTrue(CHECKS<=names)
        self.assertFalse(self.Index._meta.get_field('recorded_at').auto_now)
        self.assertNotIn(self.Index,admin.site._registry,'private archive must not install an admin writer')

    def test_pair_request_key_and_log_ID_uniqueness_are_real_DB_rejections(self):
        """Catches lack of pair/K/log uniqueness, not a mocked IntegrityError."""
        archive=self._baseline();base=rows(self.Index)[0];base.pop('id')
        for constraint,changes in {
            'uq_horse_pair_receipt_pair':{'request_key':'0'*64,'operation_log_id_snapshot':archive.operation_log_id_snapshot+10000},
            'uq_horse_pair_receipt_key':{'article_id_snapshot':archive.article_id_snapshot+10000,'operation_log_id_snapshot':archive.operation_log_id_snapshot+10000},
            'uq_horse_pair_receipt_log':{'article_id_snapshot':archive.article_id_snapshot+10000,'request_key':'0'*64},
        }.items():
            with self.subTest(constraint=constraint):
                before=self._state();data={**base,**changes}
                with self.assertRaises(IntegrityError) as caught:
                    with transaction.atomic():self.Index.objects.create(**data)
                self.assertEqual(sqlstate(caught.exception),'23505')
                self.assertEqual(caught.exception.__cause__.diag.constraint_name,constraint)
                self.assertEqual(self._state(),before)

    def test_positive_ID_hash_and_byte_checks_reject_actual_bad_INSERTs(self):
        """Catches dummy schema CHECKs accepting zero IDs, invalid hashes or oversized bytes."""
        archive=self._baseline();base=rows(self.Index)[0];base.pop('id')
        base.update(article_id_snapshot=archive.article_id_snapshot+10000,
                    profile_id_snapshot=archive.profile_id_snapshot+10000,
                    operation_log_id_snapshot=archive.operation_log_id_snapshot+10000,request_key='0'*64)
        for constraint,change in (('ck_hpair_index_ids',{'article_id_snapshot':0}),
                                  ('ck_hpair_index_hashes',{'receipt_detail_sha256':'G'*64}),
                                  ('ck_hpair_index_bytes',{'receipt_detail':'x'*(MAX_BYTES+1)})):
            before=self._state()
            with self.subTest(constraint=constraint),self.assertRaises(IntegrityError) as caught:
                with transaction.atomic():self.Index.objects.create(**{**base,**change})
            self.assertEqual(sqlstate(caught.exception),'23514')
            self.assertEqual(caught.exception.__cause__.diag.constraint_name,constraint)
            self.assertEqual(self._state(),before)

    def test_link_log_and_index_real_SQL_failure_each_rolls_back_whole_created(self):
        """Catches orphan link/log when any later stage fails with a real driver error."""
        for model in (ArticleHorseLink,OperationLog,self.Index):
            with self.subTest(stage=model._meta.db_table):
                before=self._state();reached,fault=self._fault_on_insert(model._meta.db_table)
                with connection.execute_wrapper(fault):
                    with self.assertRaises(DatabaseError) as caught:self.d.call()
                self.assertEqual(sqlstate(caught.exception),'22012');self.assertEqual(reached,[True])
                self.assertEqual(self._state(),before)
                emit('real_three_piece_rollback',stage=model._meta.db_table,SQLSTATE='22012')

    def test_caller_outer_rollback_removes_all_three_uncommitted_rows(self):
        """Catches capture committed independently of the original caller transaction."""
        before=self._state()
        with transaction.atomic():
            self.d.created();self.assertEqual(self._archives().count(),1)
            transaction.set_rollback(True)
        self.assertEqual(self._state(),before)

    def test_real_index_unique_conflict_returns_only_after_whole_tuple_rollback(self):
        """Catches rolling back only the index savepoint while committing orphan link/log."""
        before=self._state();observed=[];armed=[];table=self.Index._meta.db_table
        def duplicate(execute,sql,params,many,context):
            if sql.lstrip().upper().startswith('INSERT') and table in sql and not armed:
                armed.append(True)
                # Explicit negative SQL control: execute the actual INSERT
                # twice in this operation, not two fake admitted writers.
                execute(sql,params,many,context)
                try:return execute(sql,params,many,context)
                except IntegrityError as error:
                    observed.append({'SQLSTATE':sqlstate(error),'constraint':error.__cause__.diag.constraint_name})
                    raise
            return execute(sql,params,many,context)
        with connection.execute_wrapper(duplicate):result=self.d.call()
        self.assertEqual(result['status'],'history_conflict')
        self.assertEqual(len(observed),1);self.assertEqual(observed[0]['SQLSTATE'],'23505')
        self.assertIn(observed[0]['constraint'],UNIQUES)
        self.assertEqual(self._state(),before)
        emit('real_unique_conflict_full_rollback',observations=observed,not_two_admitted_writers=True)

    def test_capture_reads_actual_new_log_bytes_not_only_python_instance(self):
        """Catches capture trusting the old in-memory detail after a real DB insert trigger changes it."""
        before=self._state();q=connection.ops.quote_name;table=q(OperationLog._meta.db_table)
        function_created=trigger_created=False
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE FUNCTION c255_tamper_new_log() RETURNS trigger LANGUAGE plpgsql AS $$ "
                               "BEGIN IF NEW.action_type='horse_binding_committed' AND NEW.target_type='horse_binding_request' "
                               "THEN NEW.detail=NEW.detail || chr(10); END IF; RETURN NEW; END; $$")
                function_created=True
                cursor.execute(f'CREATE TRIGGER c255_tamper_new_log BEFORE INSERT ON {table} '
                               'FOR EACH ROW EXECUTE FUNCTION c255_tamper_new_log()')
                trigger_created=True
            with self.assertRaises(self.api.PairReceiptCaptureError):self.d.call()
        finally:
            with connection.cursor() as cursor:
                if trigger_created:cursor.execute(f'DROP TRIGGER c255_tamper_new_log ON {table}')
                if function_created:cursor.execute('DROP FUNCTION c255_tamper_new_log()')
        self.assertEqual(self._state(),before)

    def test_missing_authority_revocation_and_CAS_have_zero_three_piece_writes(self):
        """Catches an archive supplying permission or bypassing original input CAS."""
        for mode in ('empty_registry','revoked','expired','inactive','CAS'):
            with self.subTest(mode=mode):
                if mode=='revoked':self.d.scope['revoked']=True
                if mode=='expired':self.d.scope['expires_at']=(timezone.now()-timedelta(seconds=1)).isoformat()
                if mode=='inactive':get_user_model().objects.filter(pk=self.d.actor.pk).update(is_active=False)
                if mode=='CAS':NewsArticle.objects.filter(pk=self.d.article.pk).update(title_ja='changed after reviewed snapshot')
                context=override_settings(HORSE_ARTICLE_BINDING_HANDLES={} if mode=='empty_registry' else self.registry)
                with context:
                    before=self._state();result=self.d.call()
                    self.assertEqual(result['status'],'stale_first_apply' if mode=='CAS' else 'blocked_current_authority')
                    self.assertEqual(self._state(),before)
                self.d.scope['revoked']=False
                self.d.scope['expires_at']=(timezone.now()+timedelta(days=1)).isoformat()
                get_user_model().objects.filter(pk=self.d.actor.pk).update(is_active=True)

    def test_real_repeat_and_alias_never_update_first_archive(self):
        """Catches last_seen/upsert or duplicate capture on admitted replay."""
        self._baseline();self.registry['c255-alias']=copy.deepcopy(self.d.scope)
        for handle in (self.d.handle,'c255-alias',self.d.handle):
            before=self._state()
            with self._capture_trace() as (calls,returns):result=commit_strong_horse_binding(handle,self.d.actor)
            self.assertEqual(result['status'],'replayed');self.assertEqual(self._state(),before)
            self.assertEqual(calls,[]);self.assertEqual(returns,[])

    def test_legacy_replay_without_index_does_not_backfill_or_certify_absence(self):
        """Catches auto-indexing old history from a replay or selected receipt."""
        self._baseline()
        # Owner fixture creates explicit missing history; this is never called
        # a normal writer success without capture or a production repair.
        with self._owner_corruption():
            self._owner_clear();before=self._state();result=self.d.call()
            self.assertEqual(result['status'],'replayed');self.assertEqual(self._state(),before)
            self._read('UNKNOWN_NO_INDEX')

    def test_distinct_K_same_pair_is_closed_without_release_or_overwrite(self):
        """Catches deleted current row permitting a new K to replace the first archive."""
        self._baseline();original=rows(self.Index)
        self.d.pack['request_id']='c255-next';self.d.scope['request_id']='c255-next';self.d.write()
        before=self._state();self.assertEqual(self.d.call()['status'],'existing_pair_conflict');self.assertEqual(self._state(),before)
        self.d.link.delete();before=self._state()
        self.assertEqual(self.d.call()['status'],'history_conflict');self.assertEqual(self._state(),before)
        self.assertEqual(rows(self.Index),original)

    def test_actual_admission_peer_conflict_is_not_two_fake_authorizations(self):
        """Catches bypassing real peer constraints to stage a supposed DB race."""
        self._baseline();peer=_Producer(self,'c255-peer',peer=self.d,request_id=self.d.scope['request_id'])
        before=self._state();result=peer.call()
        self.assertEqual(result['status'],'blocked_current_authority');self.assertEqual(self._state(),before)

    def test_deleted_live_log_cannot_allow_same_K_to_move_to_another_article(self):
        """Catches request-key ownership lost when mutable OperationLog is deleted."""
        self._baseline();old=rows(self.Index);self.d.log.delete()
        peer=_Producer(self,'c255-peer',peer=self.d,request_id=self.d.scope['request_id'])
        self.registry.pop(self.d.handle);before=self._state();result=peer.call()
        self.assertEqual(result['status'],'history_conflict');self.assertEqual(self._state(),before)
        self.assertEqual(rows(self.Index),old)

    def test_marker_erasure_missing_row_and_replacement_do_not_change_archive(self):
        """Catches dependence on current marker/PK instead of captured pair history."""
        self._baseline();expected=rows(self.Index)
        ArticleHorseLink.objects.filter(pk=self.d.link.pk).update(source='auto_match',metadata={})
        self._read('INDEXED_HISTORY');self.d.link.delete();self._read('INDEXED_HISTORY')
        replacement=ArticleHorseLink.objects.create(article=self.d.article,horse_profile=self.d.horse,status='auto',source='ordinary')
        result,unused=self._read('INDEXED_HISTORY')
        self.assertNotEqual(replacement.pk,result['original_link_id']);self.assertEqual(rows(self.Index),expected)

    def test_real_staff_confirm_remove_reset_do_not_release_or_mutate_archive(self):
        """Catches staff reset treated as releasing first indexed ownership."""
        self._baseline();client=Client();client.force_login(self.d.other);expected=rows(self.Index)
        for action,status in (('confirm','manual'),('remove','removed'),('reset','candidate')):
            response=client.post(reverse('console-horse-profile-article-link-status',args=[self.d.link.pk]),{'action':action})
            require(response.status_code==302,'real staff POST prerequisite failed')
            self.d.link.refresh_from_db();require(self.d.link.status==status,'real staff state absent')
            self._read('INDEXED_HISTORY');self.assertEqual(rows(self.Index),expected)

    def test_admin_SET_NULL_log_deletion_and_parent_deletion_keep_nonFK_archive(self):
        """Catches live FK cascades/nulling or rechecking a deleted historical actor."""
        self._baseline();expected=rows(self.Index)
        HorseExternalIdentity.objects.filter(pk=self.d.identity.pk).update(verified_by=self.d.other)
        self.d.actor.delete();self.d.log.refresh_from_db();require(self.d.log.admin_id is None,'SET_NULL prerequisite')
        self._read('INDEXED_HISTORY');self.d.log.delete();self._read('INDEXED_HISTORY')
        pair=(self.d.article.pk,self.d.horse.pk)
        self.d.article.delete();self.d.horse.delete()
        self._read('INDEXED_HISTORY',pair=pair);self.assertEqual(rows(self.Index),expected)

    def test_missing_pair_is_UNKNOWN_and_never_history_coverage_or_write_permission(self):
        """Catches empty table interpreted as never-strong or scanner permission."""
        self._read('UNKNOWN_NO_INDEX')

    def test_expired_or_absent_current_registry_cannot_erase_stored_history(self):
        """Catches the reader discovering through registry or retroactively granting replay."""
        self._baseline();self.d.scope['expires_at']=(timezone.now()-timedelta(seconds=1)).isoformat()
        before=self._state();self.assertEqual(self.d.call()['status'],'blocked_current_authority');self.assertEqual(self._state(),before)
        self._read('INDEXED_HISTORY')
        with override_settings(HORSE_ARTICLE_BINDING_HANDLES={}):self._read('INDEXED_HISTORY')

    def test_corrupt_or_unsupported_archives_return_UNKNOWN_without_repair(self):
        """Catches bad SHA/schema/identity/pair material silently accepted or repaired."""
        archive=self._baseline();good=rows(self.Index)[0];data=json.loads(archive.receipt_detail)
        mutations=[{'receipt_detail_sha256':'0'*64},{'protocol_version':'unknown'},
                   {'producer_namespace':'wrong'},{'original_actor_id':archive.original_actor_id+10000},
                   {'original_link_id':archive.original_link_id+10000}]
        for text in ('{bad',archive.receipt_detail+'\n'):
            mutations.append({'receipt_detail':text,'receipt_detail_sha256':sha(text.encode())})
        malformed=copy.deepcopy(data);malformed['after_sha256']='0'*64;text=raw(malformed).decode()
        mutations.append({'receipt_detail':text,'receipt_detail_sha256':sha(text.encode())})
        for index,changes in enumerate(mutations):
            with self.subTest(case=index),self._owner_corruption():
                self._owner_update(archive.pk,**changes)
                self._read('UNKNOWN_CORRUPT_OR_UNSUPPORTED')
        self.assertEqual(rows(self.Index),[good])

    def test_oversize_owner_corruption_uses_byte_header_without_raw_fetch(self):
        """Catches owner-corrupt oversized TEXT fetched before reader size guard."""
        self._baseline()
        with self._owner_corruption():
            self._owner_update(self.archive.pk,receipt_detail='x'*(MAX_BYTES+1),receipt_detail_sha256='0'*64)
            result,notes=self._read('UNKNOWN_CORRUPT_OR_UNSUPPORTED')
            self.assertTrue(any('OCTET_LENGTH' in n['sql'].upper() for n in notes))
            self.assertFalse(any('receipt_detail' in n.get('columns',()) for n in notes))

    def test_owner_broken_uniqueness_is_UNKNOWN_not_first_or_latest_winner(self):
        """Catches LIMIT-one hiding conflicting pair history after owner corruption."""
        self._baseline()
        with self._owner_corruption():
            value=rows(self.Index)[0];value.pop('id');self.Index.objects.create(**value)
            self._read('UNKNOWN_CONFLICT')

    def test_reader_strict_input_types_never_query_an_alternative_pair(self):
        """Catches bool/string/negative ID coercion into an observation."""
        for value in (True,0,-1,'1',None):
            for side in (0,1):
                pair=[self.d.article.pk,self.d.horse.pk];pair[side]=value;self._pair=pair;before=self._state()
                with self.subTest(pair=pair),self._reader_observer():
                    with self.assertRaises(self.api.PairHistoryInputError):self.reader(*pair)
                self.assertEqual(self._state(),before)

    def test_real_driver_missing_table_and_timeout_propagate_without_index_repair(self):
        """Catches DB/driver/missing-table/timeout swallowed as successful UNKNOWN lookup."""
        self._baseline()
        for statement,code in (('SELECT 1/0','22012'),
                               ('SELECT 1 FROM stable_horsearticlepairreceiptindex__c255_missing','42P01'),
                               ('SELECT pg_sleep(0.2)','57014')):
            before=self._state();reached=[];self._pair=(self.d.article.pk,self.d.horse.pk)
            def fault(sql,context):
                if self.Index._meta.db_table in sql and not reached:
                    reached.append(True)
                    with context['connection'].connection.cursor() as cursor:
                        with context['connection'].wrap_database_errors:
                            if 'pg_sleep' in statement:cursor.execute("SET LOCAL statement_timeout='30ms'")
                            cursor.execute(statement)
                    raise PairIndexScenarioError('real database fault control did not raise')
            with self.subTest(SQLSTATE=code),self.assertRaises(DatabaseError) as caught:
                with transaction.atomic(),self._reader_observer(fault):self.reader(*self._pair)
            self.assertEqual(sqlstate(caught.exception),code);self.assertEqual(reached,[True]);self.assertEqual(self._state(),before)

    def test_actual_update_delete_and_noop_update_are_rejected_by_DB_guard(self):
        """Catches Python-only immutability bypassed by queryset/raw SQL."""
        archive=self._baseline();table=connection.ops.quote_name(self.Index._meta.db_table)
        operations=[lambda:self._archives().update(request_id='overwrite'),lambda:self._archives().update(request_id=archive.request_id),
                    lambda:self._archives().delete()]
        for operation in operations:
            before=self._state()
            with self.assertRaises(DatabaseError) as caught:
                with transaction.atomic():operation()
            self.assertEqual(sqlstate(caught.exception),'23000');self.assertEqual(self._state(),before)
        for statement in (f'UPDATE {table} SET request_id=request_id WHERE id=%s',f'DELETE FROM {table} WHERE id=%s'):
            before=self._state()
            with self.assertRaises(DatabaseError) as caught:
                with transaction.atomic(),connection.cursor() as cursor:cursor.execute(statement,(archive.pk,))
            self.assertEqual(sqlstate(caught.exception),'23000');self.assertEqual(self._state(),before)

    def test_owner_TRUNCATE_is_a_separate_capability_not_row_guard_proof(self):
        """Catches claiming row triggers stop privileged TRUNCATE or approving production ACLs."""
        self._baseline();table=self.Index._meta.db_table;before=self._state()
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_user,pg_get_userbyid(c.relowner),'
                           'has_table_privilege(current_user,%s,\'TRUNCATE\') FROM pg_class c WHERE c.oid=%s::regclass',(table,table))
            current,owner,allowed=cursor.fetchone()
        require(allowed,'isolated owner fixture lacks TRUNCATE; not a business immutability failure')
        with transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('TRUNCATE TABLE '+connection.ops.quote_name(table));self.assertEqual(self.Index.objects.count(),0)
            transaction.set_rollback(True)
        self.assertEqual(self._state(),before)
        emit('limited_immutability_boundary',current_role=current,table_owner=owner,isolated_TRUNCATE_allowed=allowed,
             production_ACL_verified=False,same_credentials_INSERT_authentication_proved=False)

    def test_real_parent_lock_and_uncommitted_capture_visibility_two_sessions(self):
        """Catches reversed parent order or capture committed separately; no weak scanner is called."""
        started=time.monotonic()
        emit('two_PG_capture_boundary',boundary='before_observer_controls',final_event_reached=False)
        # Observer-only literal controls; no SQL execution or fabricated writer.
        # A joined table must never replace the exact primary FROM relation.
        for sql,wanted in (
            ('SELECT "stable_articlehorselink".id FROM "stable_articlehorselink" INNER JOIN "stable_horseprofile" '
             'ON "stable_articlehorselink".horse_profile_id="stable_horseprofile".id '
             'ORDER BY "stable_horseprofile".original_name FOR UPDATE',
             ('stable_articlehorselink',None,'implicit_all_FROM_relations',[],True,['stable_horseprofile'])),
            ('SELECT l.id FROM "stable_articlehorselink" l JOIN "stable_horseprofile" h ON l.horse_profile_id=h.id '
             'ORDER BY h.original_name FOR UPDATE',('stable_articlehorselink','l','implicit_all_FROM_relations',[],True,['stable_horseprofile'])),
            ('SELECT U0.id FROM "stable_newsarticle" U0 FOR UPDATE OF U0',
             ('stable_newsarticle','u0','explicit_OF',['u0'],True,[])),
            ('SELECT l.id FROM public."stable_articlehorselink" AS "linkAlias" JOIN "stable_horseprofile" AS h '
             'ON "linkAlias".horse_profile_id=h.id FOR UPDATE OF "linkAlias" NOWAIT',
             ('stable_articlehorselink','linkAlias','explicit_OF',['linkAlias'],True,['stable_horseprofile'])),
            ('SELECT l.id FROM "stable_articlehorselink" l JOIN "stable_horseprofile" h ON l.horse_profile_id=h.id '
             'FOR UPDATE OF h SKIP LOCKED',('stable_articlehorselink','l','explicit_OF',['h'],False,['stable_horseprofile'])),
            ('SELECT l.id FROM "stable_articlehorselink" l JOIN "stable_horseprofile" h ON l.horse_profile_id=h.id '
             'FOR UPDATE OF l,h',('stable_articlehorselink','l','explicit_OF',['l','h'],True,['stable_horseprofile'])),
            ('''SELECT 'FOR UPDATE FROM "stable_horseprofile"', (SELECT id FROM "stable_horseprofile" LIMIT 1)
                FROM "stable_articlehorselink" FOR UPDATE''',
             ('stable_articlehorselink',None,'implicit_all_FROM_relations',[],True,[])),
        ):
            with self.subTest(observer_SQL=sql):
                info=_lock_query_target(sql)
                self.assertEqual((info['primary_table'],info['primary_relation']['alias'],info['lock_scope'],
                    info['of_aliases'],info['primary_locked'],[x['table'] for x in info['joined_relations']]),wanted)
                self.assertEqual(info['strength'],'UPDATE')
        self.assertIsNone(_lock_query_target('SELECT \'FOR UPDATE\' FROM "stable_newsarticle"'))
        for sql in ('SELECT id FROM "stable_newsarticle" n FOR UPDATE OF missing_alias',
                    'SELECT id FROM "stable_newsarticle" FOR UPDATE OF',
                    'SELECT (SELECT id FROM "stable_horseprofile" FOR UPDATE) FROM "stable_newsarticle"'):
            with self.subTest(unsupported_observer_SQL=sql),self.assertRaises(ValueError):_lock_query_target(sql)
        attempted,pending,release,done=(threading.Event() for unused in range(4))
        worker_raw=[];results=[];errors=[];pids=[];lock_tables=[];table=self.Index._meta.db_table
        lock_SQL=[];main_pid=None;blockers=[];milestones=dict(parent_block_observed=False,
            pending_index_insert=False,uncommitted_tuple_invisible=False)
        def worker():
            db=connections['default']
            try:
                db.ensure_connection();worker_raw.append(db.connection)
                with db.cursor() as cursor:
                    cursor.execute("SET statement_timeout='10s'");cursor.execute("SET lock_timeout='5s'")
                    cursor.execute('SELECT pg_backend_pid()');pids.append(cursor.fetchone()[0])
                def observe(execute,sql,params,many,context):
                    note=None;classification_error=None
                    try:info=_lock_query_target(sql)
                    except ValueError as error:info=None;classification_error=str(error)
                    if info is not None or classification_error is not None:
                        note=dict(sequence=len(lock_SQL)+1,sql=sql,params=copy.deepcopy(params),many=many,
                            thread_ident=threading.get_ident(),thread_name=threading.current_thread().name,
                            backend_pid=pids[0],classification=info,classification_error=classification_error,
                            execution_state='attempted')
                        lock_SQL.append(note)
                        primary_locked=info is not None and info['primary_locked'] and info['strength']=='UPDATE'
                        lock_tables.append(info['primary_table'] if primary_locked else None)
                        emit('two_PG_lock_SQL_attempt',observation=copy.deepcopy(note))
                        if primary_locked and info['primary_table']==NewsArticle._meta.db_table:attempted.set()
                    if sql.lstrip().upper().startswith('INSERT') and table in sql:
                        pending.set();require(release.wait(BARRIER_SECONDS),'before-index release deadline')
                    try:
                        value=execute(sql,params,many,context)
                        if note is not None:
                            note['execution_state']='completed'
                            require(classification_error is None,'unclassified actual lock SQL: '+str(classification_error))
                            require(primary_locked,'actual row lock does not UPDATE-lock its primary FROM relation')
                        return value
                    except BaseException as error:
                        if note is not None:
                            note['raised_type']=type(error).__name__;note['raised_message']=str(error)
                            if note['execution_state']=='attempted':note['execution_state']='raised'
                        raise
                    finally:
                        if note is not None:emit('two_PG_lock_SQL_result',observation=copy.deepcopy(note))
                with db.execute_wrapper(observe):result=self.d.call()
                results.append(result)
            except Exception:errors.append(traceback.format_exc())
            finally:db.close();done.set()
        thread=threading.Thread(target=worker,name='c255-real-capture',daemon=False)
        try:
            with transaction.atomic():
                NewsArticle.objects.select_for_update().get(pk=self.d.article.pk)
                with connection.cursor() as cursor:cursor.execute('SELECT pg_backend_pid()');main_pid=cursor.fetchone()[0]
                thread.start();require(attempted.wait(BARRIER_SECONDS),'worker never attempted real parent SQL')
                require(pids and pids[0]!=main_pid,'two distinct PG sessions required')
                blockers=[];deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    with connection.cursor() as cursor:cursor.execute('SELECT pg_blocking_pids(%s)',(pids[0],));blockers=cursor.fetchone()[0]
                    if main_pid in blockers:break
                    time.sleep(.01)
                require(main_pid in blockers,'actual PG parent blocking sample not observed')
                milestones['parent_block_observed']=True
                self._read('UNKNOWN_NO_INDEX')
            require(pending.wait(BARRIER_SECONDS),'real worker never reached index INSERT')
            milestones['pending_index_insert']=True
            require(not errors,'worker failed before pending capture: '+repr(errors))
            self.assertFalse(ArticleHorseLink.objects.filter(article=self.d.article,horse_profile=self.d.horse).exists())
            self.assertFalse(OperationLog.objects.filter(action_type='horse_binding_committed').exists())
            self._read('UNKNOWN_NO_INDEX')
            milestones['uncommitted_tuple_invisible']=True
            release.set();require(done.wait(BARRIER_SECONDS),'natural writer completion deadline')
        finally:
            release.set()
            try:
                if thread.ident is not None:
                    thread.join(5)
                    if thread.is_alive() and worker_raw:worker_raw[0].cancel();thread.join(3)
                    require(not thread.is_alive(),'worker bounded cleanup failed')
            finally:
                emit('two_PG_capture_boundary',boundary='cleanup_finished_before_final_assertions',
                     final_event_reached=False,main_pid=main_pid,worker_pids=list(pids),
                     actual_parent_blockers=blockers,milestones=copy.deepcopy(milestones),
                     worker_results=copy.deepcopy(results),worker_errors=list(errors),
                     worker_cleanup_complete=not thread.is_alive(),lock_tables=list(lock_tables),
                     lock_SQL=copy.deepcopy(lock_SQL))
        require(not errors and len(results)==1,'worker runtime/precondition error: '+repr(errors))
        require(results[0].get('status')=='created','real worker did not naturally create tuple')
        self.assertLess(time.monotonic()-started,TOTAL_SECONDS)
        self.assertEqual(lock_tables[:4],[m._meta.db_table for m in (NewsArticle,HorseProfile,HorseExternalIdentity,ArticleHorseLink)])
        self.d.link=ArticleHorseLink.objects.get(pk=results[0]['link_id'])
        self.d.log=OperationLog.objects.get(pk=results[0]['receipt_id']);self.d.key=self.d.link.metadata['request_key']
        self.assertEqual(self._archives().count(),1);self._assert_archive(self._archives().get());self._read('INDEXED_HISTORY')
        emit('two_PG_capture_committed',main_pid=main_pid,worker_pid=pids[0],actual_parent_blockers=blockers,
             result=results[0],natural_commit=True,worker_errors=errors,cleanup_complete=True,
             uncommitted_tuple_invisible=True,scanner_invoked=False,lock_tables=lock_tables,
             lock_SQL=lock_SQL,final_event_reached=True,milestones=milestones,
             actual_link=snapshot(self.d.link),actual_log=snapshot(self.d.log),actual_index=snapshot(self._archives().get()))
