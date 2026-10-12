"""标准库fake进程/Docker边界合同，绝不加载业务或访问daemon。"""
import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
import sys
import time
import ast
import shutil
import uuid
import subprocess
from unittest.mock import patch
from tools.test_impact.core import digest, verify_results
from tools.test_impact.serial_ci import Serial, Executor, OwnedObserver, append, absent, remove_owned, save


class FakeExecutor:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.clean = True
        self.code = {}
        self.drift = None
        self.cancel = False
        self.verify_code = 0
        self.active = self.peak = 0
        self.profiles = ['django', 'release-postgres']

    def run(self, command, deadline, ledger):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append(command)
        out = Path(command[command.index('--output') + 1])
        phase = 'verify' if command[1].endswith('verify_test_plan.py') else 'native'
        if phase == 'verify':
            if not self.verify_code:
                plan=json.loads(Path(command[command.index('--plan')+1]).read_text())
                reports=[json.loads(x.read_text()) for x in out.parent.rglob('batch-*.json')]
                try: save(out, verify_results(plan,reports))
                except ValueError: self.verify_code=1
            self.active -= 1
            return dict(exit=self.verify_code, stdout='', stderr='fake verifier failure' if self.verify_code else '', process_absent=True, cancelled=False)
        if command[1].endswith('impact_ci.py'):
            selection=json.loads((out.parent/'execution-plan.json').read_text())
            selection.update(mode='validation-only',validation_scope='inventory')
            save(out,selection)
            self.active-=1
            return dict(exit=0,stdout='',stderr='',process_absent=True,cancelled=False)
        out.mkdir(parents=True, exist_ok=True)
        plan = json.loads(Path(command[command.index('--plan') + 1]).read_text())
        if '--collect-only' in command:
            if plan['mode'] == 'docs-only':
                plan.update(batches=[], count=0)
            else:
                plan.update(image_id='sha256:fake', count=2, aliases=[{'id':'m.C.test_a','label':'m'}],
                            batches=[{'key':'batch-000','profile':self.profiles[0],'ids':['m.C.test_a']},
                                     {'key':'batch-001','profile':self.profiles[1],'ids':['r.C.test_b']}])
                if '--export-image' in command:
                    image = Path(command[command.index('--export-image') + 1])
                    image.write_bytes(b'exported fake image')
                    append(ledger, {'kind':'process-observed','stage':'image-export','returncode':0})
            save(out / 'execution-plan.json', plan)
            key = 'collection'
        else:
            key = command[command.index('--batch') + 1]
            batch = next(b for b in plan['batches'] if b['key'] == key)
            code = self.code.get(key, 0)
            if self.drift == 'image':
                self.active-=1
                return dict(exit=1,stdout='',stderr='collection/execution image mismatch',process_absent=True,cancelled=False)
            report = dict(key=key, profile=batch['profile'], plan_digest=digest(plan),
                          **{k:plan[k] for k in ('run_id','run_attempt','test_tree')},
                          executed=batch['ids'], failures=[{'id':batch['ids'][0]}] if code else [],
                          errors=[], skips=[], expected_failures=[], unexpected_successes=[],
                          lifecycle='complete', exit_code=code)
            if self.drift == 'report': report['test_tree']='wrong'
            if self.drift == 'bool': report['exit_code']=False
            save(out / (key + '.json'), report)
            (out / (key + '.log')).write_text(''.join('RUN '+i+'\n' for i in batch['ids']))
            if self.drift == 'plan':
                plan['aliases']=[]
                save(out / 'execution-plan.json',plan)
        self.active -= 1
        return dict(exit=self.code.get(key,0),stdout='',stderr='',process_absent=not self.cancel,cancelled=self.cancel)

    def cleanup(self, ledger, deadline=None):
        return self.clean, [{'name':'fake-owned','clean':self.clean}]


class SerialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.output=self.root/'evidence'
        self.selection=self.root/'selection.json'
        save(self.selection,dict(base_sha='a'*40,mode='full',source='git',test_sha='a'*40,test_tree='b'*40,run_id='9',run_attempt='1',labels=['m','r']))
        self.fake=FakeExecutor(self.root)
        self.now=0
        self.serial=Serial(self.output,{'start':0},self.fake,clock=lambda:self.now)
        self.image=self.root/'image.tar'

    def collect(self): self.serial.collect(self.selection,self.image)

    def test_once_collect_same_image_two_profiles_serial(self):
        self.collect();raw=(self.output/'execution-plan.json').read_bytes()
        self.serial.execute()
        self.assertEqual(self.fake.peak,1)
        self.assertEqual(sum('--collect-only' in c for c in self.fake.calls),1)
        self.assertEqual(sum('--build' in c for c in self.fake.calls),1)
        self.assertEqual([c[c.index('--image')+1] for c in self.fake.calls[1:]],['sha256:fake']*2)
        self.assertEqual(raw,(self.output/'execution-plan.json').read_bytes())
        self.assertEqual(self.serial.status['not_started'],[])
        self.assertTrue((self.output/'batch-000.json').exists() and (self.output/'batch-001.json').exists())

    def test_business_failure_clean_continues_keeps_image(self):
        self.collect();self.fake.code['batch-000']=1
        with self.assertRaises(RuntimeError):self.serial.execute()
        self.assertEqual(len(self.serial.status['attempted']),2)
        self.assertTrue(self.serial.status['image_complete'])
        self.assertFalse(self.serial.status['fatal'])
        self.assertTrue(self.image.exists())

    def test_cleanup_unknown_stops_remaining(self):
        self.collect();self.fake.clean=False
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(self.serial.status['not_started'],['batch-001'])

    def test_duplicate_no_new_resource(self):
        self.collect();self.serial.execute();n=len(self.fake.calls)
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(len(self.fake.calls),n)

    def test_preexisting_report_no_overwrite(self):
        self.collect();(self.output/'batch-000.json').write_text('original')
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual((self.output/'batch-000.json').read_text(),'original')
        self.assertEqual(len(self.fake.calls),1)

    def test_frozen_plan_drift_before_launch(self):
        self.collect();p=self.output/'execution-plan.json';d=json.loads(p.read_text());d['aliases']=[];save(p,d)
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(len(self.fake.calls),1)

    def test_identity_plan_bool_drift_stops(self):
        for kind in ['report','plan','bool']:
            with self.subTest(kind=kind):
                if kind!='report':self.setUp()
                self.collect();self.fake.drift=kind
                with self.assertRaises(ValueError):self.serial.execute()
                self.assertEqual(self.serial.status['not_started'],['batch-001'])

    def test_budget_no_start_release_preserves_denominator(self):
        self.collect();self.now=4000
        # First600+30+600 fits; remainingrelease2100+30+600 does not.
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(self.serial.status['expected'],['batch-000','batch-001'])
        self.assertEqual(self.serial.status['not_started'],['batch-001'])

    def test_all_budget_refused_no_invocation(self):
        self.collect();self.now=6000
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(len(self.fake.calls),1)
        self.assertEqual(self.serial.status['not_started'],self.serial.status['expected'])

    def test_build_collect_cancel_preserves_partial(self):
        self.fake.cancel=True
        with self.assertRaises(RuntimeError):self.collect()
        self.assertTrue(self.serial.status['fatal'])
        self.assertIn('partial_image',self.serial.status)

    def test_batch_cancel_stops(self):
        self.collect();self.fake.cancel=True
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(self.serial.status['not_started'],['batch-001'])

    def test_docs_only_zero_native_batches(self):
        d=json.loads(self.selection.read_text());d['mode']='docs-only';d['labels']=[];save(self.selection,d)
        self.collect();self.serial.execute()
        self.assertEqual(len(self.fake.calls),1)
        self.assertFalse(self.serial.status['image_complete'])
        self.assertEqual(self.serial.status['expected'],[])

    def test_verify_failure_records_exit_missing_summary(self):
        self.collect();self.serial.execute();self.fake.verify_code=1
        with self.assertRaises(RuntimeError):self.serial.verify()
        d=json.loads((self.output/'verify-attempt.json').read_text())
        self.assertEqual(d['exit'],1);self.assertFalse(d['summary_exists'])
        self.assertIn('fake verifier failure',d['stderr'])
        self.assertFalse(list(self.output.glob('batch-*status*.json')))

    def test_ordinary_verify_summary_and_duplicate_rejected(self):
        self.collect();self.serial.execute();self.serial.verify()
        self.assertTrue((self.output/'summary.json').exists())
        with self.assertRaises(ValueError):self.serial.verify()

    def test_collection_duplicate_keys_rejected(self):
        self.collect()
        with self.assertRaises(ValueError):self.collect()
        self.assertEqual(len(self.fake.calls),1)

    def test_final_reserve_cannot_borrow_platform_minutes(self):
        self.now=6200
        with self.assertRaises(RuntimeError):self.serial.reserve('image')
        self.assertTrue(self.serial.status['fatal'])

    def test_toolchain_inventory_same_image_separate_output(self):
        data=json.loads(self.selection.read_text());data.update(mode='validation-only',validation_scope='toolchain');save(self.selection,data)
        self.collect();self.serial.execute();self.serial.verify()
        raw=(self.output/'execution-plan.json').read_bytes()
        self.serial.inventory()
        self.assertEqual(raw,(self.output/'execution-plan.json').read_bytes())
        self.assertTrue(self.serial.status['inventory_complete'])
        self.assertNotIn('--build',self.fake.calls[-1])
        self.assertIn('sha256:fake',self.fake.calls[-1])
        self.assertFalse(list((self.output/'inventory').glob('batch-*.json')))

    def test_verify_failure_missing_batch_preserves_diagnostics(self):
        self.collect();self.fake.code['batch-000']=1
        with self.assertRaises(RuntimeError):self.serial.execute()
        (self.output/'batch-001.json').unlink()
        with self.assertRaises(RuntimeError):self.serial.verify()
        self.assertEqual(json.loads((self.output/'verify-attempt.json').read_text())['missing'],['batch-001'])

    def test_cleanup_exception_preserves_process_exit(self):
        self.collect()
        def unknown(*a):raise RuntimeError('unknowninspect')
        self.fake.cleanup=unknown
        with self.assertRaises(ValueError):self.serial.execute()
        self.assertEqual(self.serial.status['phase_results']['batch-000']['exit'],0)
        self.assertTrue(self.serial.status['fatal'])

    def test_pure_subprocess_timeout_group_is_recorded_partial(self):
        ledger=self.root/'process-events'
        result=Executor().run([sys.executable,'-c','import time; time.sleep(30)'],time.monotonic()+.05,ledger)
        self.assertTrue(result['cancelled'])
        self.assertNotEqual(result['exit'],0)
        self.assertEqual(json.loads(ledger.read_text().splitlines()[0])['kind'],'supervisor-process')

    def test_pure_subprocess_signal_cancel_is_partial(self):
        ledger=self.root/'signal-events'
        code='import os,signal,time; time.sleep(.03); os.kill(os.getppid(),signal.SIGTERM); time.sleep(30)'
        result=Executor().run([sys.executable,'-c',code],time.monotonic()+2,ledger)
        self.assertTrue(result['cancelled'])
        self.assertNotEqual(result['exit'],0)

    def test_native_image_drift_no_report_stops_remaining(self):
        self.collect();self.fake.drift='image'
        with self.assertRaises(FileNotFoundError):self.serial.execute()
        self.assertEqual(self.serial.status['not_started'],['batch-001'])
        self.assertTrue(self.serial.status['fatal'])

    def test_collect_nonzero_retains_export_index_not_complete(self):
        self.fake.code['collection']=1
        with self.assertRaises(RuntimeError):self.collect()
        self.assertTrue(self.serial.status['partial_image']['exists'])
        self.assertFalse(self.serial.status['partial_image']['collect_success_confirmed'])
        self.assertFalse(self.serial.status.get('image_complete',False))

    def test_non_docs_empty_is_not_success(self):
        self.collect();plan=json.loads((self.output/'execution-plan.json').read_text());plan['batches']=[];plan['count']=0
        save(self.output/'execution-plan.json',plan)
        self.serial.status['plan_raw']=__import__('hashlib').sha256((self.output/'execution-plan.json').read_bytes()).hexdigest()
        self.serial.status['plan_canonical']=digest(plan)
        with self.assertRaises(ValueError):self.serial.execute()

    def test_failed_business_image_upload_budget_still_eligible(self):
        self.collect();self.fake.code['batch-000']=1
        with self.assertRaises(RuntimeError):self.serial.execute()
        self.serial.reserve('image')
        self.assertTrue(self.serial.status['image_complete'])
        workflow=Path('.github/workflows/affected_tests.yml').read_text()
        image=workflow.split('      - name: upload-test-image',1)[1].split('      - name:',1)[0]
        self.assertIn("if: always() && steps.collect.outcome == 'success'",image)
        self.assertNotIn('steps.execute.outcome',image)

    def test_verify_frozen_drift_writes_independent_attempt(self):
        self.collect();self.serial.execute();p=self.output/'execution-plan.json';d=json.loads(p.read_text());d['image_id']='wrong';save(p,d)
        with self.assertRaises(ValueError):self.serial.verify()
        self.assertIn('frozen plan changed',json.loads((self.output/'verify-attempt.json').read_text())['error'])

    def test_final_actual_upload_outcomes_and_verify_required(self):
        self.collect();self.serial.execute();self.serial.verify();self.serial.finish()
        with self.assertRaises(RuntimeError):self.serial.final('failure','success')
        self.assertFalse(self.serial.status['success'])
        self.serial.final('success','success')
        self.assertTrue(self.serial.status['success'])
        with self.assertRaises(RuntimeError):self.serial.final('success','failure')
        self.assertFalse(self.serial.status['success'])

    def test_final_docs_zero_batches_skips_image_upload(self):
        data=json.loads(self.selection.read_text());data.update(mode='docs-only',labels=[]);save(self.selection,data)
        self.collect();self.serial.execute();self.serial.verify();self.serial.finish()
        self.serial.final('skipped','success')
        self.assertTrue(self.serial.status['success'])

    def test_missing_job_identity_refused_before_new_resources(self):
        self.collect();state=json.loads(self.serial.status_path.read_text());del state['job_identity'];save(self.serial.status_path,state)
        with self.assertRaises(ValueError):Serial(self.output,{'start':0},self.fake,clock=lambda:0)
        self.assertEqual(len(self.fake.calls),1)


class OwnedTests(unittest.TestCase):
    def test_rm_nonzero_even_known_absence_is_failure(self):
        def run(cmd,**kw):return types.SimpleNamespace(returncode=9 if cmd[1]=='rm' else 1,stdout='',stderr='' if cmd[1]=='rm' else 'Error: No such object: owned')
        self.assertFalse(remove_owned('owned',run)['clean'])

    def test_inspect_daemon_error_is_unknown(self):
        self.assertFalse(absent(types.SimpleNamespace(returncode=1,stdout='',stderr='Cannot connect to Docker daemon'),'owned'))

    def test_exact_absence_not_prefix_or_other_name(self):
        self.assertTrue(absent(types.SimpleNamespace(returncode=1,stdout='',stderr='Error: No such object: owned'),'owned'))
        self.assertFalse(absent(types.SimpleNamespace(returncode=1,stdout='',stderr='Error: No such object: other'),'owned'))

    def test_native_optional_owned_cleanup_propagates_actual_rm_failure(self):
        source=Path('scripts/run_test_plan.py').read_text()
        node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='invoke')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);output=root/'evidence';output.mkdir();src=root/'source';src.mkdir();ctrl=root/'control';ctrl.mkdir()
            observer=OwnedObserver(root/'events',time.monotonic()+6600,600)
            commands=[]
            def native_run(cmd,stage,**kw):
                commands.append(cmd)
                Path(cmd[cmd.index('--cidfile')+1]).write_text('c'*64)
                (root/'batch-000'/'batch-000.json').write_text('{}')
                return types.SimpleNamespace(returncode=0)
            observer.run=native_run
            def docker(cmd,**kw):
                return types.SimpleNamespace(returncode=9 if cmd[1]=='rm' else 1,stdout='',stderr='' if cmd[1]=='rm' else 'Error: No such object: '+'c'*64)
            namespace=dict(temp=root,source=src,control=ctrl,image_id='sha256:fake',output=output,uuid=uuid,shutil=shutil,subprocess=subprocess,OBSERVER=observer)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'native-owned-invoke','exec'),namespace)
            with patch('tools.test_impact.serial_ci.subprocess.run',side_effect=docker), self.assertRaises(RuntimeError):
                namespace['invoke']('run','batch-000','django')
            events=[json.loads(line) for line in (root/'events').read_text().splitlines()]
            self.assertEqual(events[-1]['rm_exit'],9)
            self.assertTrue(events[-1]['absent'])
            self.assertFalse(events[-1]['clean'])
            self.assertNotIn('--rm',commands[0])
            self.assertEqual(commands[0][commands[0].index('--memory')+1],'4g')

    def test_true_invoke_admission_uses_profile_and_final(self):
        with tempfile.TemporaryDirectory() as d:
            observer=OwnedObserver(Path(d)/'events',0,600)
            with self.assertRaises(RuntimeError):observer.admission(2100)


class ExceptionFailureTests(unittest.TestCase):
    def spawned(self, action, grouped):
        real=subprocess.Popen;created=[]
        def popen(*args,**kw):
            proc=real(*args,**kw);created.append(proc);return proc
        try:
            with patch('tools.test_impact.serial_ci.subprocess.Popen',side_effect=popen):action(created)
        finally:
            for proc in created:
                if proc.poll() is None:
                    if grouped: __import__('os').killpg(proc.pid,__import__('signal').SIGKILL)
                    else:proc.kill()
                proc.wait(timeout=5)
                for stream in (proc.stdout,proc.stderr):
                    if stream:stream.close()

    def test_supervisor_append_failure_reaps_spawned_group(self):
        with tempfile.TemporaryDirectory() as d:
            def action(created):
                with patch('tools.test_impact.serial_ci.append',side_effect=OSError(28,'ledger full')):
                    with self.assertRaises(OSError):Executor().run([sys.executable,'-c','import time;time.sleep(30)'],time.monotonic()+2,Path(d)/'events')
                self.assertIsNotNone(created[0].poll(),'ledger failure left owned child alive')
            self.spawned(action,True)

    def test_observer_event_failure_reaps_exact_child(self):
        with tempfile.TemporaryDirectory() as d:
            observer=OwnedObserver(Path(d)/'events',time.monotonic()+6600,600)
            def action(created):
                with patch.object(observer,'event',side_effect=OSError(28,'event full')):
                    with self.assertRaises(OSError):observer.run([sys.executable,'-c','import time;time.sleep(30)'],'build',timeout=2)
                self.assertIsNotNone(created[0].poll(),'observer event failure left owned child alive')
            self.spawned(action,False)

    def test_signal_install_failure_reaps_and_keeps_first_error(self):
        with tempfile.TemporaryDirectory() as d:
            def action(created):
                with patch('tools.test_impact.serial_ci.signal.signal',side_effect=OSError('signal install original')):
                    with self.assertRaisesRegex(OSError,'signal install original'):
                        Executor().run([sys.executable,'-c','import time;time.sleep(30)'],time.monotonic()+2,Path(d)/'events')
                self.assertIsNotNone(created[0].poll())
            self.spawned(action,True)

    def test_serial_run_exception_still_attempts_cleanup_without_washing(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            class Broken:
                def run(self,*args):raise OSError('primary run error')
                def cleanup(self,*args):calls.append('cleanup');raise ValueError('secondary cleanup')
            serial=Serial(Path(d),{'start':0},Broken(),clock=lambda:0)
            with self.assertRaisesRegex(OSError,'primary run error'):serial.call(['fake'],'batch-000')
            self.assertEqual(calls,['cleanup'])
            self.assertTrue(serial.status['fatal'])

    def test_cleanup_exception_preserves_native_bytes_after_temp_exit(self):
        node=next(n for n in ast.walk(ast.parse(Path('scripts/run_test_plan.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name=='invoke')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);output=root/'evidence';output.mkdir();payload=b'{"marker":"original complete JSON bytes"}\n'
            observer=OwnedObserver(root/'events',time.monotonic()+6600,600)
            with tempfile.TemporaryDirectory() as transient:
                temp=Path(transient);src=temp/'source';src.mkdir();ctrl=temp/'control';ctrl.mkdir()
                def run(command,stage,**kwargs):
                    (temp/'batch-000'/'batch-000.json').write_bytes(payload)
                    return types.SimpleNamespace(returncode=0)
                observer.run=run
                def cleanup(*args):raise RuntimeError('original rm9')
                observer.cleanup=cleanup
                namespace=dict(temp=temp,source=src,control=ctrl,image_id='sha256:fake',output=output,uuid=uuid,shutil=shutil,subprocess=subprocess,OBSERVER=observer)
                exec(compile(ast.Module(body=[node],type_ignores=[]),'native-partial-invoke','exec'),namespace)
                with self.assertRaisesRegex(RuntimeError,'original rm9'):namespace['invoke']('run','batch-000','django')
            blobs=list(output.rglob('native-output.bin'))
            self.assertEqual(len(blobs),1,'cleanup failure destroyed already-written native JSON')
            self.assertEqual(blobs[0].read_bytes(),payload)
            self.assertFalse(list(output.rglob('batch-*.json')))
            with self.assertRaises(ValueError):verify_results({'batches':[{'key':'batch-000','ids':['m.C.test_a'],'profile':'django'}]},[])


    def test_fsync_failure_reaps_group(self):
        with tempfile.TemporaryDirectory() as d:
            def action(created):
                with patch('tools.test_impact.serial_ci.os.fsync',side_effect=OSError(28,'fsync full')):
                    with self.assertRaisesRegex(OSError,'fsync full'):Executor().run([sys.executable,'-c','import time;time.sleep(30)'],time.monotonic()+2,Path(d)/'events')
                self.assertIsNotNone(created[0].poll())
            self.spawned(action,True)

    def test_communicate_exception_reaps_group(self):
        with tempfile.TemporaryDirectory() as d:
            real=subprocess.Popen;created=[]
            def popen(*args,**kwargs):
                proc=real(*args,**kwargs);proc.communicate=lambda **kw:(_ for _ in ()).throw(OSError('communicate primary'));created.append(proc);return proc
            with patch('tools.test_impact.serial_ci.subprocess.Popen',side_effect=popen):
                with self.assertRaisesRegex(OSError,'communicate primary'):Executor().run([sys.executable,'-c','import time;time.sleep(30)'],time.monotonic()+2,Path(d)/'events')
            self.assertIsNotNone(created[0].poll())

    def test_run_exception_stops_unstarted_batch_even_cleanup_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);selection=root/'selection';save(selection,dict(mode='full',source='git',test_sha='a'*40,test_tree='b'*40,run_id='9',run_attempt='1',labels=['m','r']))
            fake=FakeExecutor(root);serial=Serial(root/'out',{'start':0},fake,clock=lambda:0);serial.collect(selection,root/'image')
            def failure(*args):raise OSError('first run cause')
            fake.run=failure
            fake.cleanup=lambda *args:(_ for _ in ()).throw(ValueError('second cleanup cause'))
            with self.assertRaisesRegex(OSError,'first run cause'):serial.execute()
            self.assertEqual(serial.status['not_started'],['batch-001'])
            self.assertTrue(serial.status['fatal'])
            self.assertIn('first run cause',serial.status['phase_results']['batch-000']['error'])

    def partial_case(self, fault, produce=True):
        node=next(n for n in ast.walk(ast.parse(Path('scripts/run_test_plan.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name=='invoke')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);output=root/'out';output.mkdir();payload=b'{"marker":"unaltered native bytes"}\n'
            observer=OwnedObserver(root/'events',time.monotonic()+6600,600)
            with tempfile.TemporaryDirectory() as transient:
                temp=Path(transient);src=temp/'source';src.mkdir();ctrl=temp/'control';ctrl.mkdir()
                def run(*args,**kwargs):
                    if produce:(temp/'batch-000'/'batch-000.json').write_bytes(payload)
                    if fault=='timeout':raise subprocess.TimeoutExpired(['fake'],600)
                    if fault=='cancel':raise __import__('tools.test_impact.serial_ci',fromlist=['SerialCancelled']).SerialCancelled('cancel primary')
                    return types.SimpleNamespace(returncode=0)
                def cleanup(*args):
                    if fault=='inspect':raise OSError('inspect unavailable')
                    if fault=='cleanup-timeout':raise subprocess.TimeoutExpired(['rm'],30)
                observer.run=run;observer.cleanup=cleanup
                ns=dict(temp=temp,source=src,control=ctrl,image_id='fake',output=output,uuid=uuid,shutil=shutil,subprocess=subprocess,OBSERVER=observer)
                exec(compile(ast.Module(body=[node],type_ignores=[]),'native-preserve','exec'),ns)
                with self.assertRaises(BaseException):ns['invoke']('run','batch-000','django')
            indexes=list(output.rglob('index.json'));self.assertEqual(len(indexes),1)
            meta=json.loads(indexes[0].read_text());self.assertTrue(meta['partial']);self.assertFalse(meta['complete']);self.assertEqual(meta['key'],'batch-000')
            self.assertEqual(meta['missing'],not produce)
            if produce:
                self.assertEqual((indexes[0].parent/'native-output.bin').read_bytes(),payload)
                self.assertEqual(meta['raw_sha256'],__import__('hashlib').sha256(payload).hexdigest())
            self.assertFalse(list(output.rglob('batch-*.json')))
            with self.assertRaises(ValueError):verify_results({'batches':[{'key':'batch-000','ids':['m.C.test'],'profile':'django'}]},[])

    def test_inspect_timeout_cancel_preserve_opaque_bytes(self):
        for fault in ('inspect','cleanup-timeout','timeout','cancel'):
            with self.subTest(fault=fault):self.partial_case(fault)

    def test_no_native_json_recorded_missing_without_fabrication(self):self.partial_case('inspect',False)

    def test_evidence_full_retains_unique_temp_and_first_error(self):
        from scripts.run_test_plan import ObservedTemporaryDirectory
        node=next(n for n in ast.walk(ast.parse(Path('scripts/run_test_plan.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name=='invoke')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);output=root/'out';output.mkdir();payload=b'{"diskfull":"unique original"}'
            observer=OwnedObserver(root/'events',time.monotonic()+6600,600);cleanups=[]
            with ObservedTemporaryDirectory(observer) as transient:
                temp=Path(transient);self.addCleanup(shutil.rmtree,temp,ignore_errors=True);src=temp/'source';src.mkdir();ctrl=temp/'control';ctrl.mkdir()
                def run(*a,**kw):(temp/'batch-000'/'batch-000.json').write_bytes(payload);return types.SimpleNamespace(returncode=0)
                def cleanup(*a):cleanups.append(True);raise RuntimeError('primary cleanup cause')
                observer.run=run;observer.cleanup=cleanup
                ns=dict(temp=temp,source=src,control=ctrl,image_id='fake',output=output,uuid=uuid,shutil=shutil,subprocess=subprocess,OBSERVER=observer)
                exec(compile(ast.Module(body=[node],type_ignores=[]),'native-diskfull','exec'),ns)
                original=Path.open
                def diskfull(path,*a,**kw):
                    if path.name=='native-output.bin':raise OSError(28,'evidence full')
                    return original(path,*a,**kw)
                with patch.object(Path,'open',diskfull),self.assertRaisesRegex(RuntimeError,'primary cleanup cause'):ns['invoke']('run','batch-000','django')
            self.assertEqual(cleanups,[True]);self.assertTrue(observer.retain_temp)
            self.assertEqual((temp/'batch-000'/'batch-000.json').read_bytes(),payload)
            self.assertFalse(observer.preservation_errors[0]['persisted'])


if __name__=='__main__':unittest.main()
