"""协议/进程边界控制不是真实PG资格；RealPGTests仅在精确资格环境显式启用。

本卡只冻结源码，不运行。真实PG方法不借模拟returncode认证PG；P0/P9/P10的
旧入口/外层SIGKILL/原runner收据资格仍须原12oracle的独立精确运行卡。
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import unittest

from tools.test_impact import pg_lifecycle as pg
from tools.test_impact.core import digest

IMAGE = 'sha256:' + 'f' * 64


def plan_fixture():
    return dict(source='git', test_sha='a'*40, test_tree='b'*40, run_id='9', run_attempt='1',
                image_id=IMAGE, mode='targeted', labels=['m.C.test_a', 'r.C.test_b'],
                batches=[dict(key='batch-000', profile='django', ids=['m.C.test_a']),
                         dict(key='batch-001', profile='release-postgres', ids=['r.C.test_b'])], count=2)


def synthetic_receipt(request, native, worker_exit=0):
    """数据合同fixture，所有PID/numeric均为模拟；不得用它作PG实测证明。"""
    value = pg.new_receipt(request)
    value.update(namespace='fixture-only-not-real-PG', supervisor_pid=100, uid=10001, gid=10001,
                 last_phase='complete', complete=True, supervisor_exit=worker_exit,
                 native_raw_sha256=hashlib.sha256(native).hexdigest(),
                 output_plan_digest=digest(json.loads(native)) if request['mode']=='collect' else request['input_plan_digest'])
    for name, pid in [('worker', 102), ('postmaster', 101), ('pg_stop', 103)]:
        if name != 'worker' and not value['pg_required']:
            continue
        value[name].update(status='REAPED', started=True, pid=pid, ppid=100, argv=['fixture-only', name],
                           returncode=worker_exit if name=='worker' else 0, reaped=True)
    return value


def save_synthetic_lifecycle(output, input_plan, mode, key='', profile='', worker_exit=0):
    """供既有FakeExecutor保持完整新schema；不调用PG/Docker。"""
    output=Path(output)
    request=pg.make_request(input_plan, mode, key, profile, 'a'*32)
    raw=(output/pg.native_filename(mode,key)).read_bytes()
    receipt=synthetic_receipt(request,raw,worker_exit)
    pg.write_receipt(output/pg.request_filename(mode,key),request)
    pg.write_receipt(output/pg.receipt_filename(mode,key),receipt)
    cleanup=dict(clean=True,rm_exit=0,absent=True,exit_state=dict(
        Id='c'*64, Image=input_plan['image_id'], State=dict(Running=False,Pid=0,ExitCode=worker_exit,OOMKilled=False)))
    binding=pg.make_host_binding((output/pg.request_filename(mode,key)).read_bytes(),
                                (output/pg.receipt_filename(mode,key)).read_bytes(),raw,cleanup)
    pg.write_receipt(output/pg.host_filename(mode,key),binding)
    return receipt


def native_fixture_inputs(namespace):
    """旧invoke AST单元的最小合法只读输入，非真实source binding。"""
    namespace['image_id']=IMAGE
    plan=plan_fixture()
    return dict(frozen_plan_bytes=json.dumps(plan).encode(), frozen_binding_bytes=b'{}', raw_commit=b'synthetic-only')


class PGProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.plan=plan_fixture()
        self.request=pg.make_request(self.plan,'run','batch-000','django','a'*32)
        self.native=b'{"exit_code":0}\n'
        self.receipt=synthetic_receipt(self.request,self.native)

    def assertCode(self, code, function, *args, **kwargs):
        with self.assertRaises(pg.ReceiptError) as raised: function(*args,**kwargs)
        self.assertEqual(raised.exception.code,code)

    def test_valid_fixture_is_only_data_contract_and_inputs_stay_unchanged(self):
        original=copy.deepcopy(self.receipt)
        pg.validate_receipt(self.receipt,self.request,self.native)
        self.assertEqual(self.receipt,original)
        self.assertEqual(self.receipt['namespace'],'fixture-only-not-real-PG')

    def test_input_digest_negative_has_unequal_valid_value_and_frozen_expected(self):
        pg.validate_receipt(self.receipt,self.request,self.native)
        expected=copy.deepcopy(self.request);raw=json.dumps(self.plan).encode()
        actual=self.receipt['input_plan_digest'];self.assertRegex(actual,r'\A[0-9a-f]{64}\Z')
        forged=('0' if actual[0]!='0' else '1')+actual[1:]
        self.assertRegex(forged,r'\A[0-9a-f]{64}\Z');self.assertNotEqual(forged,actual)
        candidate=copy.deepcopy(self.receipt);candidate['input_plan_digest']=forged
        self.assertEqual(self.request,expected);self.assertEqual(json.dumps(self.plan).encode(),raw)
        self.assertCode('INPUT_PLAN_DIGEST_MISMATCH',pg.validate_receipt,candidate,self.request,self.native)

    def test_equal_digest_copy_is_noop_and_still_valid(self):
        b=pg.make_request(self.plan,'run','batch-001','release-postgres','b'*32)
        self.assertEqual(b['input_plan_digest'],self.request['input_plan_digest'])
        before=copy.deepcopy(self.receipt)
        self.receipt['input_plan_digest']=b['input_plan_digest']
        self.assertEqual(before,self.receipt)
        pg.validate_receipt(self.receipt,self.request,self.native)

    def test_nonce_key_profile_and_whole_receipt_exchange_rejected(self):
        pg.validate_receipt(self.receipt,self.request,self.native)
        other=pg.make_request(self.plan,'run','batch-001','release-postgres','b'*32)
        for field in ('nonce','key','profile'):
            changed=copy.deepcopy(self.receipt);changed[field]=other[field]
            self.assertCode('NONCE_MISMATCH' if field=='nonce' else 'RECEIPT_IDENTITY_MISMATCH',
                            pg.validate_receipt,changed,self.request,self.native)
        self.assertCode('NONCE_MISMATCH',pg.validate_receipt,synthetic_receipt(other,self.native),self.request,self.native)

    def test_two_concurrent_control_snapshots_are_independent_and_stable(self):
        raw=json.dumps(self.plan).encode()
        a,ra=pg.prepare_control(self.root,raw,b'{}',b'commit','run','batch-000','django','a'*32)
        b,rb=pg.prepare_control(self.root,raw,b'{}',b'commit','run','batch-001','release-postgres','b'*32)
        self.assertNotEqual(a,b);self.assertNotEqual(a.parent,b.parent)
        barrier=threading.Barrier(2)
        def read(control):
            before={p.name:p.read_bytes() for p in control.iterdir()}
            barrier.wait(timeout=5)
            for _ in range(20): self.assertEqual({p.name:p.read_bytes() for p in control.iterdir()},before)
            return before
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa=pool.submit(read,a);fb=pool.submit(read,b);aa,bb=fa.result(),fb.result()
        self.assertEqual(set(aa),{'plan.json','source-binding.json','test-commit.raw','pg-lifecycle-request.json'})
        self.assertEqual(aa['plan.json'],bb['plan.json']);self.assertNotEqual(ra['nonce'],rb['nonce'])
        pg.release_control(a);self.assertTrue(b.is_dir())
        self.assertEqual({p.name:p.read_bytes() for p in b.iterdir()},bb)
        self.assertCode('NONCE_MISMATCH',pg.validate_receipt,synthetic_receipt(rb,self.native),ra,self.native)
        pg.release_control(b)

    def test_source_run_attempt_image_and_budget_cannot_drift(self):
        for field in ('test_sha','test_tree','run_id','run_attempt','image_id','inner_seconds','cleanup_seconds'):
            changed=copy.deepcopy(self.request);v=changed[field];changed[field]=v+1 if type(v)is int else v+'0'
            self.assertCode('REQUEST_IDENTITY_MISMATCH',pg.validate_request,changed,self.plan,'run','batch-000','django')

    def test_false_zero_or_absence_does_not_replace_numeric_wait(self):
        for stage in ('postmaster','pg_stop'):
            for value in (None,False,1,-9):
                receipt=copy.deepcopy(self.receipt);receipt[stage]['returncode']=value
                self.assertCode('PG_NUMERIC_INCOMPLETE',pg.validate_receipt,receipt,self.request,self.native)
        changed=copy.deepcopy(self.receipt);changed['postmaster']['reaped']=False
        self.assertCode('PG_NUMERIC_INCOMPLETE',pg.validate_receipt,changed,self.request,self.native)

    def test_worker_failure_is_preserved_when_numeric_pg_cleanup_is_complete(self):
        native=b'{"exit_code":7}\n'
        value=synthetic_receipt(self.request,native,7)
        pg.validate_receipt(value,self.request,native)
        self.assertEqual(value['worker']['returncode'],7);self.assertEqual(value['supervisor_exit'],7)

    def test_require_pg_missing_or_early_exit_never_becomes_na(self):
        receipt=copy.deepcopy(self.receipt);receipt['pg_required']=False
        self.assertCode('PG_NUMERIC_INCOMPLETE',pg.validate_receipt,receipt,self.request,self.native)
        receipt=copy.deepcopy(self.receipt);receipt['complete']=False
        self.assertCode('PG_NUMERIC_INCOMPLETE',pg.validate_receipt,receipt,self.request,self.native)

    def test_run_python_na_is_explicit_and_has_no_pg_numbers(self):
        plan=copy.deepcopy(self.plan);plan['batches'][0]['profile']='python'
        request=pg.make_request(plan,'run','batch-000','python','a'*32)
        receipt=synthetic_receipt(request,self.native)
        pg.validate_receipt(receipt,request,self.native)
        self.assertIsNone(receipt['postmaster']['returncode']);self.assertEqual(receipt['postmaster']['status'],'NOT_APPLICABLE')

    def test_duplicate_json_keys_symlink_and_nonfinite_json_are_rejected(self):
        p=self.root/'x.json';p.write_text('{"nonce":"a","nonce":"b"}')
        with self.assertRaises(pg.ReceiptError):pg.read_json(p)
        p.write_text('{"v":NaN}')
        with self.assertRaises(pg.ReceiptError):pg.read_json(p)
        p.write_text('{}');link=self.root/'link';link.symlink_to(p)
        with self.assertRaises(pg.ReceiptError):pg.read_json(link)

    def test_output_bytes_and_unknown_receipt_fields_rejected(self):
        self.assertCode('OUTPUT_HASH_MISMATCH',pg.validate_receipt,self.receipt,self.request,b'different')
        value=copy.deepcopy(self.receipt);value['ready']=True
        self.assertCode('RECEIPT_SCHEMA',pg.validate_receipt,value,self.request,self.native)

    def test_saved_receipt_requires_owned_cid_join_and_stable_hashes(self):
        (self.root/'batch-000.json').write_bytes(self.native)
        save_synthetic_lifecycle(self.root,self.plan,'run','batch-000','django')
        pg.verify_saved_lifecycle(self.root,self.plan,'run','batch-000','django')
        host=self.root/pg.host_filename('run','batch-000');value=pg.read_json(host);value['ownership']='unobserved';pg.write_receipt(host,value)
        self.assertCode('OWNED_CID_REQUIRED',pg.verify_saved_lifecycle,self.root,self.plan,'run','batch-000','django')

    def test_lifecycle_names_never_enter_batch_report_glob(self):
        self.assertEqual(pg.receipt_filename('collect',''),'lifecycle-collection.json')
        self.assertEqual(pg.receipt_filename('run','batch-000'),'lifecycle-batch-000.json')
        for mode,key in [('collect',''),('run','batch-000')]:
            (self.root/pg.receipt_filename(mode,key)).write_text('{}')
        self.assertEqual(list(self.root.glob('batch-*.json')),[])
        with self.assertRaises(pg.ReceiptError):pg.receipt_filename('run','../batch-000')


def _p5_postmaster_reaped(session, process):
    record=session.records.get('postmaster',{})
    return (process is not None and session.processes.get('postmaster') is process
            and record is session.receipt['postmaster'] and record.get('started') is True
            and record.get('reaped') is True and type(record.get('returncode')) is int
            and record['returncode']==-signal.SIGKILL and type(process.returncode) is int
            and process.returncode==-signal.SIGKILL)


def _confirm_p5_postmaster_exit(session, process):
    """仅测试故障前件：用原数字wait，最多3秒且不越过原业务/内deadline。"""
    if session.processes.get('postmaster') is not process:
        raise AssertionError('P5_SAVED_POSTMASTER_MISMATCH')
    deadline=min(session.business_deadline,session.deadline,pg.time.monotonic()+3)
    code=session._wait('postmaster',deadline,False)
    if type(code) is not int or code!=-signal.SIGKILL or not _p5_postmaster_reaped(session,process):
        raise AssertionError('P5_EXIT_PRECONDITION_UNKNOWN')


def _cleanup_p5_after_confirmed_exit(session):
    """P5任何失败路径都不许fallback启动第四次pg_stop；未证实就留UNKNOWN。"""
    if not _p5_postmaster_reaped(session,session.processes.get('postmaster')):
        session.error('P5_EXIT_PRECONDITION_UNKNOWN');session.persist_partial()
        raise AssertionError('P5_EXIT_PRECONDITION_UNKNOWN')
    session.stop_and_wait()


class P5ExitPreconditionTests(unittest.TestCase):
    """纯边界源码：模拟Popen依赖，不是PG资格；本卡冻结但不执行。"""
    def setUp(self):
        import shutil
        from unittest import mock
        self.mock=mock
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        plan=plan_fixture();request=pg.make_request(plan,'run','batch-000','django','a'*32)
        self.session=pg.Session(request,plan,Path(self.tmp.name),root=Path(self.tmp.name))
        self.addCleanup(shutil.rmtree,self.session.log_dir,ignore_errors=True)
        self.session.business_deadline=102.;self.session.deadline=132.
        self.process=mock.Mock(pid=900,returncode=None)
        self.process.poll.side_effect=lambda:self.process.returncode
        record=pg.step_record();record.update(pid=900,ppid=1,started=True,status='RUNNING',argv=['synthetic-p5-postmaster'])
        self.session.processes['postmaster']=self.process
        self.session.records['postmaster']=record;self.session.receipt['postmaster']=record
        self.session._spawn=mock.Mock(side_effect=AssertionError('pure boundary must not spawn'))

    def test_unobserved_kill_requires_numeric_wait_before_cleanup(self):
        import subprocess
        outcomes=iter([subprocess.TimeoutExpired('synthetic-p5',.1),-9])
        def wait(timeout=None):
            outcome=next(outcomes)
            if isinstance(outcome,BaseException):raise outcome
            self.process.returncode=outcome;return outcome
        self.process.wait.side_effect=wait
        with self.mock.patch.object(pg.time,'monotonic',return_value=100.):
            _confirm_p5_postmaster_exit(self.session,self.process)
        self.assertEqual(self.process.wait.call_count,2)
        self.process.poll.assert_not_called()
        self.assertEqual(self.session.receipt['postmaster']['returncode'],-9)
        self.assertTrue(self.session.receipt['postmaster']['reaped'])
        self.session._spawn.assert_not_called()

    def test_precondition_timeout_blocks_registered_cleanup_stop(self):
        self.session.business_deadline=100.5
        with self.mock.patch.object(pg.time,'monotonic',side_effect=[100.,101.]):
            with self.assertRaises(TimeoutError):
                _confirm_p5_postmaster_exit(self.session,self.process)
        with self.assertRaisesRegex(AssertionError,'P5_EXIT_PRECONDITION_UNKNOWN'):
            _cleanup_p5_after_confirmed_exit(self.session)
        self.assertTrue(self.session.receipt['postmaster']['timed_out'])
        self.assertFalse(self.session.receipt['postmaster']['reaped'])
        self.assertFalse(self.session.closed)
        self.assertFalse(self.session.receipt['pg_stop']['started'])
        self.assertEqual(self.session.receipt['primary_error'],'P5_EXIT_PRECONDITION_UNKNOWN')
        self.session._spawn.assert_not_called()

    def test_confirmed_exit_enters_original_cleanup_without_stop_spawn(self):
        def wait(timeout=None):self.process.returncode=-9;return -9
        self.process.wait.side_effect=wait
        with self.mock.patch.object(pg.time,'monotonic',return_value=100.):
            _confirm_p5_postmaster_exit(self.session,self.process)
            with self.mock.patch.object(pg.os,'waitpid',side_effect=ChildProcessError(10,'synthetic ECHILD')):
                _cleanup_p5_after_confirmed_exit(self.session)
        self.assertTrue(self.session.closed)
        self.assertFalse(self.session.receipt['pg_stop']['started'])
        self.assertEqual(self.session.receipt['primary_error'],'PG_EXIT_BEFORE_STOP')
        self.assertEqual(self.session.receipt['secondary_errors'],['PG_POSTMASTER_EXIT:-9'])
        self.session._spawn.assert_not_called()

    def test_startup_failure_cannot_fall_through_to_fourth_stop(self):
        with self.assertRaisesRegex(AssertionError,'P5_EXIT_PRECONDITION_UNKNOWN'):
            _cleanup_p5_after_confirmed_exit(self.session)
        self.assertFalse(self.session.closed)
        self.assertFalse(self.session.receipt['pg_stop']['started'])
        self.process.poll.assert_not_called()
        self.session._spawn.assert_not_called()


@unittest.skipUnless(os.environ.get('UMANEWS_REAL_PG_QUALIFICATION')=='1',
                     'requires separate exact real-PG qualification card/container')
class RealPGTests(unittest.TestCase):
    """真实PG组件仅在显式隔离资格域运行；不证明native/full。"""
    def setUp(self):
        self.assertEqual(sys.platform,'linux');self.assertEqual(os.getuid(),10001)
        plan=pg.read_json(Path(os.environ['UMANEWS_PG_QUALIFICATION_PLAN']))
        batch=next(b for b in plan['batches'] if b['profile']!='python')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        request=pg.make_request(plan,'run',batch['key'],batch['profile'],'a'*32)
        self.session=pg.Session(request,plan,self.root,root=self.root,data_dir=self.root/'pgdata')
        if self._testMethodName=='test_real_early_postmaster_exit_is_reaped':
            self.addCleanup(_cleanup_p5_after_confirmed_exit,self.session)
        else:
            self.addCleanup(self.session.stop_and_wait)

    def start(self):
        self.session.prepare_pg();self.session.start_postgres();self.session.wait_ready()

    def test_real_foreground_pid_and_separate_stop_wait(self):
        self.start();self.session.command('worker',[sys.executable,'-I','-c','pass'],5)
        self.session.stop_and_wait()
        self.assertEqual(self.session.receipt['postmaster']['ppid'],os.getpid())
        self.assertEqual(self.session.receipt['pg_stop']['returncode'],0)
        self.assertEqual(self.session.receipt['postmaster']['returncode'],0)
        self.assertTrue(self.session.receipt['postmaster']['reaped'])

    def test_real_worker7_does_not_hide_stop_wait0(self):
        self.start();self.session.command('worker',[sys.executable,'-I','-c','raise SystemExit(7)'],5)
        self.session.stop_and_wait()
        self.assertEqual(self.session.receipt['worker']['returncode'],7)
        self.assertEqual(self.session.receipt['pg_stop']['returncode'],0)
        self.assertEqual(self.session.receipt['postmaster']['returncode'],0)

    def test_real_sigstop_forces_real_stop_timeout_not_success(self):
        self.start();os.kill(self.session.processes['postmaster'].pid,signal.SIGSTOP)
        self.session.stop_and_wait()
        self.assertNotEqual(self.session.receipt['pg_stop']['returncode'],0)
        self.assertNotEqual(self.session.receipt['postmaster']['returncode'],0)

    def test_real_initdb_failure_has_no_fake_postmaster_zero(self):
        self.session.data_dir.mkdir();(self.session.data_dir/'occupied').write_text('owned-test')
        with self.assertRaisesRegex(RuntimeError,'INITDB_FAILED:'):self.session.prepare_pg()
        initdb=self.session.receipt['tools'][0]
        self.assertIs(type(initdb['returncode']),int);self.assertNotEqual(initdb['returncode'],0)
        self.assertTrue(initdb['reaped'])
        self.assertIsNone(self.session.receipt['postmaster']['returncode'])
        self.assertFalse(self.session.receipt['postmaster']['started'])

    def test_real_early_postmaster_exit_is_reaped(self):
        self.start();process=self.session.processes['postmaster'];os.kill(process.pid,signal.SIGKILL)
        _confirm_p5_postmaster_exit(self.session,process)
        _cleanup_p5_after_confirmed_exit(self.session)
        self.assertEqual(self.session.receipt['postmaster']['returncode'],-signal.SIGKILL)
        self.assertTrue(self.session.receipt['postmaster']['reaped'])
