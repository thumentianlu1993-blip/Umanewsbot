"""B262仅文件/模拟Docker出口协议；不启动PG/Docker，不作真实数值资格。"""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import types
import unittest
import uuid
from unittest.mock import patch

from scripts.run_test_plan import ObservedTemporaryDirectory
from tools.test_impact import pg_lifecycle as pg
from tools.test_impact.core import digest
from tools.test_impact.serial_ci import OwnedObserver
from tools.test_impact.test_pg_lifecycle import native_fixture_inputs, plan_fixture


class InvokeUnknownOutputRetentionTests(unittest.TestCase):
    @staticmethod
    def cleanup_owned(path):
        path=Path(path)
        if not path.exists():return
        for p in path.rglob('*'):
            if p.is_dir() and not p.is_symlink():p.chmod(0o700)
        path.chmod(0o700);shutil.rmtree(path)

    def scenario(self, *, owned, fault, lifecycle='half', unknown=True, classification_error=False):
        # 合法partial前件：原schema完整native，生命周期缺失或截断不能称完整PG收据。
        plan=plan_fixture();batch=plan['batches'][0]
        native=json.dumps(dict(key=batch['key'],profile=batch['profile'],plan_digest=digest(plan),
            run_id=plan['run_id'],run_attempt=plan['run_attempt'],test_tree=plan['test_tree'],
            executed=batch['ids'],failures=[],errors=[],skips=[],expected_failures=[],unexpected_successes=[],
            lifecycle='complete',exit_code=0)).encode()+b'\n'
        self.assertEqual(json.loads(native)['exit_code'],0)
        half=b'{"schema_version":"pg-lifecycle-v1","complete":false,'
        self.assertRaises(json.JSONDecodeError,json.loads,half)
        primary=(subprocess.TimeoutExpired(['docker','run'],600) if fault=='timeout'
                 else RuntimeError('original cleanup failure') if fault=='cleanup' else None)
        calls=[];captured={}
        node=next(n for n in ast.walk(ast.parse(Path('scripts/run_test_plan.py').read_text()))
                  if isinstance(n,ast.FunctionDef) and n.name=='invoke')
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);saved=base/'saved';saved.mkdir()
            observer=OwnedObserver(base/'events',time.monotonic()+6600,600) if owned else None
            temporary=ObservedTemporaryDirectory(observer)
            with temporary as transient:
                temp=Path(transient);self.addCleanup(self.cleanup_owned,temp)
                source=temp/'source';source.mkdir()
                unknown_path=temp/'batch-000'/'.lifecycle-batch-000.owned-atomic.tmp'
                def run(command, stage=None, **kwargs):
                    operation=command[1];calls.append((operation,kwargs.get('timeout')))
                    if operation=='rm':
                        if fault=='cleanup':raise primary
                        return types.SimpleNamespace(returncode=0)
                    self.assertEqual(operation,'run')
                    mount=next(v for v in command if isinstance(v,str) and ',dst=/control,readonly' in v)
                    captured['control']=Path(mount.split('src=',1)[1].split(',dst=',1)[0])
                    self.assertEqual({p.name for p in captured['control'].iterdir()},
                                     {'plan.json','source-binding.json','test-commit.raw','pg-lifecycle-request.json'})
                    if owned:Path(command[command.index('--cidfile')+1]).write_text('c'*64)
                    out=temp/'batch-000';(out/'batch-000.json').write_bytes(native)
                    if lifecycle=='half':(out/'lifecycle-batch-000.json').write_bytes(half)
                    if unknown:unknown_path.write_bytes(b'unique opaque original, never parse')
                    if fault=='timeout':raise primary
                    return types.SimpleNamespace(returncode=0)
                def cleanup(*args):
                    calls.append(('owned-cleanup',None))
                    if fault=='cleanup':raise primary
                if observer is not None:observer.run=run;observer.cleanup=cleanup
                namespace=dict(temp=temp,source=source,output=saved,uuid=uuid,shutil=shutil,subprocess=subprocess,
                               OBSERVER=observer,temporary=temporary)
                namespace.update(native_fixture_inputs(namespace))
                exec(compile(ast.Module(body=[node],type_ignores=[]),'fixed-invoke-source','exec'),namespace)
                unknown_reads=[]
                real_open=Path.open;real_iterdir=Path.iterdir;real_read_regular=pg.read_regular
                def regular_guard(path):
                    if Path(path)==unknown_path:
                        unknown_reads.append(str(path));raise AssertionError('unknown output read through raw helper')
                    return real_read_regular(path)
                def open_guard(path,*args,**kwargs):
                    mode=args[0] if args else kwargs.get('mode','r')
                    if path==unknown_path and 'r' in mode:
                        unknown_reads.append(str(path));raise AssertionError('unknown output read')
                    return real_open(path,*args,**kwargs)
                def iterdir_guard(path):
                    if classification_error and path==temp/'batch-000':raise OSError('classification unreadable')
                    return real_iterdir(path)
                with patch.object(pg,'read_regular',side_effect=regular_guard), \
                     patch('scripts.run_test_plan.subprocess.run',side_effect=run), \
                     patch.object(Path,'open',open_guard),patch.object(Path,'iterdir',iterdir_guard):
                    with self.assertRaises(BaseException) as caught:namespace['invoke']('run','batch-000','django')
                self.assertEqual(unknown_reads,[], 'unknown read attempts must not be swallowed by preservation handling')
                if primary is not None:self.assertIs(caught.exception,primary)
                else:self.assertEqual(getattr(caught.exception,'code',None),'OUTPUT_SET_MISMATCH')
                retained=(observer.retain_temp if observer else temporary.retain_temp)
                if unknown or classification_error:self.assertTrue(retained)
                self.assertEqual(calls[0],('run',600))
                self.assertEqual(sum(op in ('rm','owned-cleanup') for op,_ in calls),1)
                if not owned:self.assertIn(('rm',30),calls)
            # 保留必须跨过真实temp上下文退出；不能只观察一个内存bool。
            if unknown or classification_error:
                self.assertTrue(temp.is_dir());self.assertTrue(captured['control'].is_dir())
                self.assertEqual((temp/'batch-000'/'batch-000.json').read_bytes(),native)
                if unknown:self.assertEqual(unknown_path.read_bytes(),b'unique opaque original, never parse')
            indexes=list(saved.rglob('index.json'));self.assertEqual(len(indexes),1)
            partial=json.loads(indexes[0].read_text());self.assertFalse(partial['complete'])
            self.assertEqual((indexes[0].parent/'native-output.bin').read_bytes(),native)
            if lifecycle=='half':self.assertEqual((indexes[0].parent/'lifecycle-output.bin').read_bytes(),half)
            else:self.assertFalse((indexes[0].parent/'lifecycle-output.bin').exists())
            self.assertFalse(list(saved.glob('batch-*.json')))

    def test_known_partial_baseline_preserves_original_cleanup_cause(self):
        for owned in (True,False):
            with self.subTest(owned=owned):self.scenario(owned=owned,fault='cleanup',unknown=False)

    def test_owned_timeout_keeps_unknown_and_missing_or_half_lifecycle(self):
        for lifecycle in ('missing','half'):
            with self.subTest(lifecycle=lifecycle):self.scenario(owned=True,fault='timeout',lifecycle=lifecycle)

    def test_owned_cleanup_error_keeps_unknown_and_missing_or_half_lifecycle(self):
        for lifecycle in ('missing','half'):
            with self.subTest(lifecycle=lifecycle):self.scenario(owned=True,fault='cleanup',lifecycle=lifecycle)

    def test_nonowned_timeout_keeps_unknown_and_missing_or_half_lifecycle(self):
        for lifecycle in ('missing','half'):
            with self.subTest(lifecycle=lifecycle):self.scenario(owned=False,fault='timeout',lifecycle=lifecycle)

    def test_nonowned_cleanup_error_keeps_unknown_and_missing_or_half_lifecycle(self):
        for lifecycle in ('missing','half'):
            with self.subTest(lifecycle=lifecycle):self.scenario(owned=False,fault='cleanup',lifecycle=lifecycle)

    def test_classification_failure_retains_both_paths_and_original_primary(self):
        for owned in (True,False):
            with self.subTest(owned=owned):self.scenario(owned=owned,fault='timeout',unknown=False,classification_error=True)

    def test_normal_return_with_unknown_output_never_promotes_report(self):
        for owned in (True,False):
            with self.subTest(owned=owned):self.scenario(owned=owned,fault=None)
