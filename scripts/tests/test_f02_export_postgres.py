"""F02 isolated PG16 contracts. Without an explicitly bound synthetic manifest, never connect."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest
from scripts import f02_readonly_export as export
from scripts import f02_transfer as transfer

class GuardError(ValueError):
    pass

def validate_manifest(value):
    keys={'schema_version','run_id','nonce','network_internal','host_ports','production_mounts','connection',
          'pg_image_id','python_image_id','psycopg_version','dependency_sha256','exporter_sha256','verifier_sha256',
          'schema_sha256','driver_sha256','runtime_root','runtime_attestation_sha256'}
    try:
        if (set(value)!=keys or value['schema_version']!=1 or value['network_internal'] is not True
                or value['host_ports']!=[] or value['production_mounts']!=[] or value['psycopg_version']!='3.2.6'
                or not re.fullmatch(r'synthetic-b005-[a-z0-9-]{1,32}',value['run_id'])
                or not re.fullmatch('[0-9a-f]{64}',value['nonce'])):
            raise GuardError('synthetic_manifest_rejected')
        conn=value['connection']
        if (set(conn)!={'host','port','dbname','admin_user','admin_password','reader_user','reader_password'}
                or conn['host']!='f02-pg-'+value['run_id'] or conn['port']!=5432
                or conn['dbname']!='f02_'+value['run_id'].replace('-','_')
                or conn['admin_user']!='f02_fixture_admin' or conn['reader_user']!='f02_fixture_reader'
                or not all(isinstance(conn[k],str) and bool(conn[k]) for k in ('admin_password','reader_password'))):
            raise GuardError('synthetic_target_rejected')
        for key in ('pg_image_id','python_image_id'):
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',value[key]):raise GuardError('unbound_image')
        for key in ('dependency_sha256','runtime_attestation_sha256'):
            if not re.fullmatch('[0-9a-f]{64}',value[key]):raise GuardError('unbound_runtime')
        files={'exporter_sha256':Path(export.__file__),'verifier_sha256':Path(transfer.__file__),
               'schema_sha256':Path(__file__).with_name('f02_pg_schema.sql'),'driver_sha256':Path(__file__)}
        for key,path in files.items():
            if value[key]!=hashlib.sha256(path.read_bytes()).hexdigest():raise GuardError('fixed_source_mismatch')
        root=transfer.check_path(value['runtime_root'])
        if 'b005' not in str(root).lower():raise GuardError('not_dedicated_runtime')
        return value
    except GuardError:
        raise
    except Exception:
        raise GuardError('synthetic_manifest_rejected') from None

class PGGuardTests(unittest.TestCase):
    def test_production_or_inherited_target_refused(self):
        for value in ({}, {'connection':{'host':'production','dbname':'umanews'}}, {'network_internal':False}):
            with self.assertRaises(GuardError):
                validate_manifest(value)

# Guard fixtures contain no real endpoints, credentials or network operations.
def guard_snapshot():
    return {'mode':'internal-ci-v2','uid':10001,'python_exe':'/venv/bin/python',
            'interfaces':['lo'],'docker_socket':False,'endpoint':['127.0.0.1',5432],
            'listener_inode':123,'listener_owner_pid':77,'pid':77,'start_ticks':987,
            'stable':True,'namespaces':{'net':1,'mnt':2,'pid':3,'user':4},
            'python_namespaces':{'net':1,'mnt':2,'pid':3,'user':4},
            'pgdata':'/tmp/pgdata','pg_uid':10001,'pg_mode':448,'symlinks':False,
            'fs_type':'tmpfs','fs_magic':16914836,'mount_root':'/','mountpoint':'/tmp',
            'mount_rw':True,'propagation':False,'nested_mounts':False,'device_matches':True,
            'pg_exe':'/usr/lib/postgresql/16/bin/postgres','pg_exe_sha256':'a'*64,
            'pgdata_inode':44,'pgdata_device':55,'mount_id':66,'cmdline_pgdata':'/tmp/pgdata',
            'python_pid':88,'python_start_ticks':99,'config_private':True,'listener_fd':3}

class InternalCIGuardTests(unittest.TestCase):
    def refuse(self, **delta):
        from scripts.tests import f02_pg_fixture as fixture
        from unittest.mock import Mock
        self.assertEqual(fixture.validate(guard_snapshot()),guard_snapshot())
        snapshot=guard_snapshot();snapshot.update(delta)
        connect=Mock()
        with self.assertRaises(fixture.GuardError):
            fixture.prepare_fixture(_capture=lambda:snapshot,_connect=connect)
        connect.assert_not_called()

    def test_collect_has_no_skip_and_no_connection(self):
        self.assertFalse(getattr(PostgreSQLContracts,'__unittest_skip__',False))
        self.assertEqual(len(unittest.TestLoader().getTestCaseNames(PostgreSQLContracts)),12)
        from scripts.tests import f02_pg_fixture
        from unittest.mock import patch
        with patch.object(f02_pg_fixture,'prepare_fixture') as prepare:
            suite=unittest.TestLoader().loadTestsFromTestCase(PostgreSQLContracts)
            self.assertEqual(suite.countTestCases(),12)
            prepare.assert_not_called()

    def test_listener_endpoint_refused(self):self.refuse(endpoint=['0.0.0.0',5432])
    def test_listener_inode_owner_refused(self):self.refuse(listener_owner_pid=78)
    def test_pid_reuse_refused(self):self.refuse(stable=False)
    def test_namespace_mismatch_refused(self):
        for key in ('net','mnt','pid','user'):
            value=guard_snapshot()['python_namespaces'];value[key]+=1
            self.refuse(python_namespaces=value)
    def test_non_tmpfs_refused(self):self.refuse(fs_type='overlay')
    def test_pgdata_permissions_refused(self):
        self.refuse(pg_mode=493);self.refuse(pg_uid=0)
    def test_symlink_refused(self):self.refuse(symlinks=True)
    def test_nested_mount_refused(self):self.refuse(nested_mounts=True)
    def test_mount_propagation_refused(self):self.refuse(propagation=True)
    def test_device_mismatch_refused(self):self.refuse(device_matches=False)
    def test_unknown_binding_field_refused(self):self.refuse(unknown=True)

class FixtureFailureTests(unittest.TestCase):
    def lost(self, object_kind, number, stage):
        import tempfile,types,shutil
        from unittest.mock import Mock,patch
        from scripts.tests import f02_pg_fixture as fixture
        class SQL:
            def __init__(self,text):self.text=text
            def format(self,*args):return SQL(self.text.format(*args))
            def __str__(self):return self.text
        fake_psycopg=types.SimpleNamespace(sql=types.SimpleNamespace(SQL=SQL,Identifier=lambda s:s,Literal=lambda s:'<private>'))
        roles={};database={};queries=[];last=[None,None];role_count=[0]
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def execute(self,query,params=None):
                text=str(query);queries.append(text);last[:]=[text,params]
                if text.startswith(('CREATE ROLE','CREATE DATABASE')):
                    journal=json.loads((obj.root/'fixture-intent.json').read_text())
                    expected_kind='role' if text.startswith('CREATE ROLE') else 'database'
                    assert len(journal['pending_intents'])==1 and journal['pending_intents'][0]['kind']==expected_kind
                if text.startswith('CREATE ROLE'):
                    role_count[0]+=1;name='f02_fixture_'+('admin' if role_count[0]==1 else 'reader');roles[name]=role_count[0]+100
                    if object_kind=='role' and role_count[0]==number and stage=='create':raise RuntimeError('synthetic response lost')
                if text.startswith('CREATE DATABASE'):
                    database['oid']=201
                    if object_kind=='database' and stage=='create':raise RuntimeError('synthetic response lost')
            def fetchall(self):return []
            def fetchone(self):
                text,params=last
                if 'FROM pg_roles' in text:
                    if object_kind=='role' and role_count[0]==number and stage=='oid':raise RuntimeError('synthetic oid response lost')
                    return {'oid':roles[params[0]]}
                if 'FROM pg_database' in text:
                    if not database:return None
                    if object_kind=='database' and stage=='oid':raise RuntimeError('synthetic oid response lost')
                    return {'oid':database['oid'],'owner':'f02_fixture_admin'} if 'owner' in text else {'oid':database['oid']}
                raise AssertionError('unexpected synthetic query')
        conn=Mock();conn.cursor.side_effect=lambda:Cursor()
        binding=guard_snapshot();binding['uid']=os.getuid();binding['pgdata_device']=Path('/tmp').stat().st_dev
        obj=fixture.Fixture(binding,lambda:binding,Mock())
        obj.connection=Mock(return_value=conn)
        real_mkdtemp=tempfile.mkdtemp
        def local_private_temp(*args,**kwargs):return str(Path(real_mkdtemp(*args,**kwargs)).resolve())
        with patch.dict('sys.modules',{'psycopg':fake_psycopg}),patch.object(fixture,'dependency_proof',return_value={}),patch.object(fixture.tempfile,'mkdtemp',side_effect=local_private_temp):
            try:
                with self.assertRaises(RuntimeError):obj.prepare()
                try:obj.cleanup()
                except fixture.GuardError:pass
                self.assertEqual(obj.cleanup_status,'unknown_container_cleanup_required')
                self.assertTrue(obj.receipt().get('pending_intents'))
                journal=json.loads((obj.root/'fixture-intent.json').read_text())
                self.assertEqual(journal['pending_intents'],obj.receipt()['pending_intents'])
                self.assertEqual(journal['cleanup_status'],'unknown_container_cleanup_required')
                self.assertFalse(any(query.startswith('DROP ') for query in queries))
                self.assertTrue(obj.root.is_dir())
                self.assertTrue(roles or database)
            finally:
                if obj.root is not None:shutil.rmtree(obj.root)
    def test_first_role_create_response_lost(self):self.lost('role',1,'create')
    def test_first_role_oid_response_lost(self):self.lost('role',1,'oid')
    def test_second_role_create_response_lost(self):self.lost('role',2,'create')
    def test_second_role_oid_response_lost(self):self.lost('role',2,'oid')
    def test_database_create_response_lost(self):self.lost('database',1,'create')
    def test_database_oid_response_lost(self):self.lost('database',1,'oid')

class PostgreSQLContracts(unittest.TestCase):
    BASE_COHORT=8

    @classmethod
    def setUpClass(cls):
        cls.fixture=None
        if os.environ.get('F02_SYNTHETIC_MANIFEST'):
            path=Path(os.environ['F02_SYNTHETIC_MANIFEST'])
            data=transfer.read_file(path,65536)
            if hashlib.sha256(data).hexdigest()!=os.environ.get('F02_SYNTHETIC_MANIFEST_SHA256'):
                raise GuardError('manifest_sha_mismatch')
            cls.config=validate_manifest(json.loads(data))
        else:
            from scripts.tests import f02_pg_fixture
            cls.fixture=f02_pg_fixture.prepare_fixture()
            cls.addClassCleanup(cls.fixture.cleanup)
            cls.config=cls.fixture.config
        import psycopg
        from psycopg.rows import dict_row
        if psycopg.__version__!='3.2.6':raise GuardError('unverified_driver_version')
        cls.psycopg=psycopg;cls.dict_row=dict_row
        cls.root=transfer.mkdir_private(cls.config['runtime_root'])
        cls.sequence=0
        # Guard schema initialized only by the controlled synthetic container provisioner.
        connection=cls.connect('admin')
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database() AS db, current_user AS role, current_setting('server_version_num')::int AS version")
                actual=cursor.fetchone()
                if actual['db']!=cls.config['connection']['dbname'] or actual['role']!='f02_fixture_admin' or actual['version']//10000!=16:
                    raise GuardError('not_synthetic_PG16')
                cursor.execute('SELECT run_id,nonce FROM f02_control.validation_guard')
                guard=cursor.fetchone()
                if guard!={'run_id':cls.config['run_id'],'nonce':cls.config['nonce']}:
                    raise GuardError('synthetic_guard_mismatch')
        except GuardError:
            raise
        except Exception:
            raise GuardError('synthetic_guard_unavailable') from None
        finally:
            connection.close()

    @classmethod
    def connect(cls,role='reader'):
        if cls.fixture is not None:
            return cls.fixture.connection(role)
        c=cls.config['connection']
        try:
            return cls.psycopg.connect(host=c['host'],port=c['port'],dbname=c['dbname'],user=c[role+'_user'],
                                      password=c[role+'_password'],autocommit=True,row_factory=cls.dict_row,
                                      connect_timeout=3,options='-c statement_timeout=15000 -c lock_timeout=1000')
        except Exception:
            raise GuardError('synthetic_connection_failed') from None

    def setUp(self):
        self.admin=self.connect('admin');self.reader=self.connect()
        self.addCleanup(self.admin.close);self.addCleanup(self.reader.close)
        ddl=Path(__file__).with_name('f02_pg_schema.sql').read_text()
        with self.admin.cursor() as c:
            # Dedicated synthetic DB + previously verified nonce only. Never run ordinary migrations.
            c.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')
            c.execute(ddl)
            c.execute('GRANT USAGE ON SCHEMA public TO f02_fixture_reader; GRANT SELECT ON ALL TABLES IN SCHEMA public TO f02_fixture_reader')
            c.execute("INSERT INTO public.stable_newssource(id,source_site,source_mode,racing_region,source_language) VALUES(1,'jra','direct','japan','ja')")
            for i,region in enumerate(export.REGIONS,1):
                c.execute("INSERT INTO public.stable_newsarticle(id,title_ja,body_ja_raw,racing_region,first_seen_at,workflow_status,source_site,source_mode,source_language) VALUES(%s,'synthetic','synthetic body',%s,now()-interval '1 day','pending_review','jra','direct','ja')",(i,region))
            c.execute("INSERT INTO public.stable_newssource(id,source_site,source_mode,racing_region,enabled,production_approved) VALUES(2,'synthetic','direct','france',false,false),(3,'synthetic','feed','',true,false)")
            c.execute("INSERT INTO public.stable_newsarticle(id,racing_region,first_seen_at,workflow_status,title_ja,body_ja_raw,published_to_web_at,withdrawn_at,duplicate_of_id) VALUES(100,'japan',now()-interval '1 day','pending_translation','synthetic empty','',NULL,NULL,NULL),(101,'japan',now()-interval '1 day','translation_failed','synthetic failed','synthetic body',NULL,NULL,NULL),(102,'japan',now()-interval '1 day','published','synthetic withdrawn','synthetic body',now()-interval '1 day',now(),1)")
            c.execute("INSERT INTO public.stable_crawljob(id,source_id,status,started_at) VALUES(1,NULL,'failed',now()-interval '1 day')")
            c.execute("INSERT INTO public.stable_productionwindow(id,kind,window_start,window_end) VALUES(1,'publish',now()-interval '1 day',now()),(2,'crawl',now()-interval '1 day',now())")
            c.execute("INSERT INTO public.stable_windowcandidatedecision(id,window_id,article_id,status,reason) VALUES(1,1,1,'selected','selected'),(2,2,1,'selected','selected')")
            c.execute("INSERT INTO public.stable_racenewsexposure(id,article_id,event_id,channel,slot,status) VALUES(1,1,1,'homepage',1,'active'),(2,1,1,'qq',1,'active')")
        type(self).sequence+=1
        self.output=transfer.mkdir_private(self.root/('case-'+str(self.sequence))/'runtime/next_version/F02')
        self.marker=self.root/('marker-'+str(self.sequence));self.marker.write_text('a'*40);self.marker.chmod(0o600)

    def metadata(self):
        return export.collect_metadata(self.reader,'a'*40,hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest())

    def source(self):
        snapshot=self.metadata()
        receipt=export.publish_metadata(snapshot,self.output,'metadata')
        row=snapshot['cohort'][0]
        selection={'custodian':'R','source_observation_id':'metadata','release_sha':'a'*40,
                   'source_metadata_manifest_sha256':receipt['manifest_sha256'],
                   'source_schema_sha256':snapshot['observation']['schema_sha256'],
                   'samples':[{'id':row['id'],'input_sha256':row['input_sha256'],'updated_at':row['updated_at'].isoformat()}]}
        return snapshot,selection

    def cli(self,mode,obs,selection=None,script_sha=None,release='a'*40):
        import subprocess,sys
        c=self.config['connection']
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','POSTGRES_HOST':c['host'],'POSTGRES_PORT':str(c['port']),
             'POSTGRES_DB':c['dbname'],'POSTGRES_USER':c['reader_user'],'POSTGRES_PASSWORD':c['reader_password'],
             'POSTGRES_SSLMODE':'disable','PYTHONNOUSERSITE':'1'}
        argv=[sys.executable,'-B',str(Path(export.__file__).resolve()),'--mode',mode,'--output-root',str(self.output),
              '--observation-id',obs,'--resident-marker',str(self.marker),'--expected-release-sha',release,
              '--expected-script-sha256',script_sha or hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest()]
        if selection is not None:
            path=self.root/('selection-'+str(self.sequence)+'.json');transfer.atomic_json(path,selection)
            argv+=['--selection',str(path),'--selection-sha256',hashlib.sha256(path.read_bytes()).hexdigest(),
                   '--source-metadata-dir',str(self.output/'metadata')]
        result=subprocess.run(argv,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=185,check=False,start_new_session=True)
        self.assertLess(len(result.stdout),8192);self.assertEqual(result.stderr,b'')
        return result.returncode,json.loads(result.stdout)

    def test_P01_real_metadata_content_CLI(self):
        code,result=self.cli('metadata','metadata');self.assertEqual(code,0)
        self.assertEqual(result['counts']['cohort'],self.BASE_COHORT)
        snapshot=self.metadata();row=snapshot['cohort'][0]
        self.assertTrue(any(r['workflow_status']=='translation_failed' for r in snapshot['cohort']))
        self.assertTrue(any(r['empty_body'] for r in snapshot['cohort']))
        self.assertEqual(snapshot['counts']['decisions'],1)
        self.assertEqual(snapshot['counts']['homepage_exposures'],1)
        selection={'custodian':'R','source_observation_id':'metadata','release_sha':'a'*40,
                   'source_metadata_manifest_sha256':result['manifest_sha256'],'source_schema_sha256':snapshot['observation']['schema_sha256'],
                   'samples':[{'id':row['id'],'input_sha256':row['input_sha256'],'updated_at':row['updated_at'].isoformat()}]}
        code,result=self.cli('content','content',selection);self.assertEqual(code,0);self.assertEqual(result['counts'],{'articles':1})

    def test_P02_readonly_settings_and_DML_rejected_by_transaction(self):
        # Admin has DML privileges, so SQLSTATE25006 proves transaction semantics rather than permission denial.
        seen={}
        def callback(c,obs,schema):
            c.execute("SELECT current_setting('statement_timeout') AS s,current_setting('lock_timeout') AS l,current_setting('idle_in_transaction_session_timeout') AS i,current_setting('TimeZone') AS tz")
            seen.update(c.fetchone());self.assertEqual(obs['read_only'],'on');self.assertEqual(obs['isolation'],'repeatable read')
            try:c.execute('INSERT INTO public.stable_crawljob(id) VALUES(999)')
            except self.psycopg.Error as e:seen['write_state']=e.sqlstate
        export.readonly(self.admin,callback)
        self.assertEqual(seen,{'s':'15s','l':'1s','i':'15s','tz':'UTC','write_state':'25006'})
        with self.admin.cursor() as c:c.execute('SELECT count(*) AS n FROM public.stable_crawljob WHERE id=999');self.assertEqual(c.fetchone()['n'],0)

    def test_P03_real_two_connection_snapshot(self):
        def callback(c,obs,schema):
            c.execute('SELECT count(*) AS n FROM public.stable_newsarticle');first=c.fetchone()['n']
            with self.admin.cursor() as w:w.execute("INSERT INTO public.stable_newsarticle(id,racing_region) VALUES(99,'japan')")
            c.execute('SELECT count(*) AS n FROM public.stable_newsarticle');self.assertEqual(c.fetchone()['n'],first)
        export.readonly(self.reader,callback)
        self.assertEqual(self.metadata()['counts']['cohort'],self.BASE_COHORT+1)

    def test_P04_half_open_window_and_unknown_source(self):
        with self.admin.cursor() as c:
            c.execute("INSERT INTO public.stable_newsarticle(id,racing_region,first_seen_at) VALUES(90,'japan',now()-interval '29 days'),(91,'japan',now()+interval '1 day'),(92,'other',now())")
        snapshot=self.metadata();self.assertEqual(snapshot['counts']['cohort'],self.BASE_COHORT);self.assertIsNone(snapshot['crawl_jobs'][0]['source_id'])
        from datetime import datetime,timedelta,timezone
        start=datetime(2026,1,1,tzinfo=timezone.utc);cutoff=start+timedelta(days=28)
        with self.admin.cursor() as c:
            c.execute('SELECT value FROM (VALUES(%s::timestamptz),(%s::timestamptz)) AS q(value) WHERE value>=%s AND value<%s',(start,cutoff,start,cutoff))
            self.assertEqual([r['value'] for r in c.fetchall()],[start])

    def test_P05_real_statement_lock_idle_timeouts(self):
        import time
        from unittest.mock import patch
        def state_for(connection,sql):
            codes=[]
            def cb(c,obs,sha):
                try:c.execute(sql)
                except self.psycopg.Error as e:codes.append(e.sqlstate)
            export.readonly(connection,cb);return codes
        self.assertEqual(state_for(self.reader,'SELECT pg_sleep(16)'),['57014'])
        locker=self.connect('admin');self.addCleanup(locker.close);locker.execute('BEGIN');locker.execute('LOCK TABLE public.stable_newsarticle IN ACCESS EXCLUSIVE MODE')
        self.assertEqual(state_for(self.reader,'SELECT count(*) FROM public.stable_newsarticle'),['55P03']);locker.rollback()
        connection=self.connect('admin');self.addCleanup(connection.close)
        def idle(c,obs,sha):
            time.sleep(16);c.execute('SELECT 1')
        with self.assertRaises(Exception):export.readonly(connection,idle)
        self.assertTrue(connection.closed)

    def test_P06_missing_column_and_schema_drift(self):
        _,selection=self.source()
        with self.admin.cursor() as c:c.execute('ALTER TABLE public.stable_newsarticle ADD COLUMN synthetic_drift integer')
        with self.assertRaisesRegex(export.ExportError,'source_schema_drift'):export.collect_content(self.reader,selection)
        with self.admin.cursor() as c:c.execute('ALTER TABLE public.stable_newsarticle DROP COLUMN title_ja')
        with self.assertRaisesRegex(export.ExportError,'schema_mismatch'):self.metadata()

    def test_P07_actual_input_and_missing_ID_drift(self):
        _,selection=self.source()
        with self.admin.cursor() as c:c.execute("UPDATE public.stable_newsarticle SET title_ja='synthetic changed',updated_at=now() WHERE id=1")
        rows=export.collect_content(self.reader,selection)
        with self.assertRaisesRegex(export.ExportError,'stale_input'):export.publish_content(rows,selection,self.output,'stale')
        with self.admin.cursor() as c:c.execute('DELETE FROM public.stable_newsarticle WHERE id=1')
        with self.assertRaisesRegex(export.ExportError,'content_id_mismatch'):export.collect_content(self.reader,selection)

    def test_P08_real_count_budget_boundary_each_dataset(self):
        for key,limit in export.LIMITS.items():
            table=export.TABLES[key]
            with self.admin.cursor() as c:
                c.execute('TRUNCATE public.'+table)
                columns={'cohort':"id,racing_region",'windows':"id,kind",'decisions':"id,window_id",'homepage_exposures':"id,article_id,channel"}.get(key,'id')
                values={'cohort':"n,'japan'",'windows':"n,'publish'",'decisions':"n,1",'homepage_exposures':"n,1,'homepage'"}.get(key,'n')
                c.execute('INSERT INTO public.'+table+'('+columns+') SELECT '+values+' FROM generate_series(1,%s) AS q(n)',(limit,))
            snapshot=self.metadata();self.assertEqual(snapshot['counts'][key],limit)
            with self.admin.cursor() as c:c.execute('INSERT INTO public.'+table+'('+columns+') SELECT '+values+' FROM generate_series(%s::bigint,%s::bigint) AS q(n)',(limit+1,limit+1))
            with self.assertRaisesRegex(export.ExportError,'detail_budget_exceeded'):self.metadata()
            # Reset full fixture after each case so unrelated over-budget tables cannot mask this one.
            if key!=list(export.LIMITS)[-1]:self.setUp()

    def test_P09_real_content_byte_limits_and_UTF8(self):
        for count,size,valid in ((1,512*1024,True),(1,512*1024+1,False),(60,512*1024,True),(61,512*1024,False),(150,8,True),(151,8,False)):
            with self.admin.cursor() as c:
                c.execute('TRUNCATE public.stable_newsarticle')
                c.execute("INSERT INTO public.stable_newsarticle(id,racing_region,body_ja_raw) SELECT n,'japan',repeat('x',%s) FROM generate_series(1,%s) AS q(n)",(size,count))
            snapshot=self.metadata();selection={'custodian':'R','source_observation_id':'metadata','release_sha':'a'*40,
                'source_schema_sha256':snapshot['observation']['schema_sha256'],
                'samples':[{'id':r['id'],'input_sha256':r['input_sha256'],'updated_at':r['updated_at'].isoformat()} for r in snapshot['cohort']]}
            if valid:self.assertEqual(len(export.collect_content(self.reader,selection)),count)
            else:
                with self.assertRaisesRegex(export.ExportError,'selection_budget_exceeded' if count>150 else 'content_budget_exceeded'):export.collect_content(self.reader,selection)
        selection['samples']=selection['samples'][:150]
        with self.admin.cursor() as c:c.execute("UPDATE public.stable_newsarticle SET body_ja_raw=repeat('汉',262144) WHERE id=1")
        with self.assertRaisesRegex(export.ExportError,'content_budget_exceeded'):export.collect_content(self.reader,selection)
        selection['samples']*=3
        with self.assertRaises(export.ExportError):export.collect_content(self.reader,selection)

    def test_P10_NULL_and_PG_Python_hash_agree(self):
        snapshot=self.metadata();row=snapshot['cohort'][0]
        self.assertIsNone(row['published_at_verified']);self.assertIsNone(row['source_config_id'])
        self.assertEqual(row['input_sha256'],export.digest('synthetic\nsynthetic body'))

    def test_P11_wrong_preconnection_bindings_fail_closed(self):
        for sha,release in (('e'*64,'a'*40),(None,'e'*40)):
            code,result=self.cli('metadata','wrong',script_sha=sha,release=release)
            self.assertNotEqual(code,0);self.assertFalse((self.output/'wrong').exists())
            self.assertIn(result['error_code'],('script_binding_mismatch','resident_release_mismatch'))

    def test_P12_database_failure_and_existing_observation_not_overwritten(self):
        code,result=self.cli('metadata','once');self.assertEqual(code,0)
        before=(self.output/'once/manifest.json').read_bytes()
        code,result=self.cli('metadata','once');self.assertNotEqual(code,0)
        self.assertEqual(before,(self.output/'once/manifest.json').read_bytes())
        with self.admin.cursor() as c:
            c.execute('ALTER TABLE public.stable_newsarticle RENAME TO synthetic_news')
            c.execute('CREATE VIEW public.stable_newsarticle AS SELECT * FROM public.synthetic_news WHERE 1/0=0')
            c.execute('GRANT SELECT ON public.stable_newsarticle TO f02_fixture_reader')
        code,result=self.cli('metadata','error');self.assertNotEqual(code,0)
        self.assertIn(result['error_code'],('database_read_failed','local_operation_failed'))
        self.assertFalse((self.output/'error/manifest.json').exists())
