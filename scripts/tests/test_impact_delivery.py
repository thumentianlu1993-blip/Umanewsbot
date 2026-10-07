"""交付不可仅凭同名绿色job或旧run的结果。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from scripts.verify_delivery_test_evidence import verify_jobs, verify_protection, compare_collection, verify_mode
from scripts.decide_full_regression import should_run


class DeliveryTests(unittest.TestCase):
    def jobs(self):
        return [{'id':1,'name':'tests','conclusion':'success','steps':[{'name':n,'conclusion':'success'} for n in
                 ['checkout-test-tree','static-contracts','generate-plan','execute-isolated-plan','verify-execution','upload-evidence']]},
                {'id':2,'name':'test-plan-gate','conclusion':'success','steps':[{'name':'require-complete-plan','conclusion':'success'}]}]

    def test_same_name_success_without_verification_is_rejected(self):
        jobs=self.jobs();jobs[0]['steps']=jobs[0]['steps'][:-2]
        with self.assertRaisesRegex(ValueError,'step'):verify_jobs(jobs)

    def test_cancelled_and_old_attempt_jobs_are_not_accepted(self):
        jobs=self.jobs();jobs[0]['conclusion']='cancelled'
        with self.assertRaises(ValueError):verify_jobs(jobs)
        with self.assertRaises(ValueError):verify_jobs(self.jobs()+self.jobs())

    def test_complete_steps_accepted(self):verify_jobs(self.jobs())

    def test_strict_and_admin_enforcement_required(self):
        valid={'required_status_checks':{'strict':True,'contexts':['test-plan-gate']},'enforce_admins':{'enabled':True}}
        verify_protection(valid)
        valid['enforce_admins']['enabled']=False
        with self.assertRaises(ValueError):verify_protection(valid)

    def test_bootstrap_requires_actual_prefixed_check_without_weakening_normal_pr(self):
        bootstrap='impact-validation / test-plan-gate'
        valid={'required_status_checks':{'strict':True,'contexts':[bootstrap]},'enforce_admins':{'enabled':True}}
        verify_protection(valid, bootstrap)
        with self.assertRaises(ValueError):verify_protection(valid)
        valid['required_status_checks']['contexts']=['test-plan-gate']
        with self.assertRaises(ValueError):verify_protection(valid, bootstrap)

    def test_nightly_failed_same_sha_retries_weekly_unchanged_runs(self):
        now=datetime.now(timezone.utc)
        latest={'tested_sha':'a','conclusion':'success','updated_at':now.isoformat()}
        self.assertFalse(should_run('a',latest,now))
        self.assertTrue(should_run('b',latest,now))
        latest['head_sha']='b'
        self.assertTrue(should_run('b',latest,now), 'workflow ref must not replace tested SHA')
        latest['conclusion']='failure';self.assertTrue(should_run('a',latest,now))
        latest['conclusion']='success';self.assertTrue(should_run('a',latest,now+timedelta(days=7)))


class CollectionEvidenceTests(unittest.TestCase):
    def test_empty_self_consistent_evidence_is_rejected(self):
        plan={'batches':[],'count':0}
        collected={'batches':[{'key':'batch-000','profile':'python','ids':['m.C.test_x']}],'count':1}
        with self.assertRaisesRegex(ValueError,'collection'):
            compare_collection(plan,collected)


class ScopeEvidenceTests(unittest.TestCase):
    def test_targeted_cannot_claim_documentation_to_skip_collection(self):
        with self.assertRaisesRegex(ValueError,'mode'):
            verify_mode('targeted','docs-only')


class BootstrapTests(unittest.TestCase):
    def test_manual_calibration_cannot_substitute_pr_delivery(self):
        from scripts.verify_delivery_test_evidence import authorize_run
        run={'event':'workflow_dispatch','path':'.github/workflows/release_0078_contract.yml'}
        plan={'bootstrap':True,'head_sha':'head','test_sha':'head'};review={'commit':'head'}
        with self.assertRaisesRegex(ValueError,'pull_request'):
            authorize_run(run,plan,review,False,'head','merge')
        for has_catalog,approval in [(True,review),(False,None),(False,{'commit':'other'})]:
            with self.assertRaises(ValueError):authorize_run(run,plan,approval,has_catalog,'head','merge')

    def test_ordinary_pr_still_requires_exact_merge_identity(self):
        from scripts.verify_delivery_test_evidence import authorize_run
        for has_catalog in (False, True):
            self.assertEqual(authorize_run(
                {'event':'pull_request','path':'.github/workflows/affected_tests.yml'},
                {'test_sha':'merge'}, {'commit':'head'}, has_catalog, 'head', 'merge'), '')
        with self.assertRaises(ValueError):
            authorize_run({'event':'pull_request','path':'.github/workflows/affected_tests.yml'},
                          {'test_sha':'head'},None,True,'head','merge')


class WorkflowIdentityTests(unittest.TestCase):
    def test_all_pr_source_bindings_use_event_merge_not_cached_payload(self):
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/affected_tests.yml'
        bindings = re.findall(r'^\s*(?:ref|TEST_SHA): \$\{\{ (.+) \}\}$', workflow.read_text().split('      - name: collect-catalog-without-running', 1)[0], re.M)
        self.assertEqual(len(bindings), 3)  # checkout、静态检查、计划必须绑定同一个事件。
        for event, cached_merge, expected in (
            ('pull_request', 'stale-merge-for-previous-head', 'current-event-merge'),
            ('pull_request', None, 'current-event-merge'),
            ('pull_request', 'current-event-merge', 'current-event-merge'),
            ('workflow_dispatch', None, 'explicit-candidate'),
            ('schedule', None, 'explicit-candidate'),
        ):
            context = {
                'github': SimpleNamespace(event_name=event, sha='current-event-merge',
                    event=SimpleNamespace(pull_request=SimpleNamespace(merge_commit_sha=cached_merge))),
                'inputs': SimpleNamespace(candidate_sha='explicit-candidate'),
            }
            for expression in bindings:
                with self.subTest(event=event, cached_merge=cached_merge, expression=expression):
                    actual = eval(expression.replace('&&', 'and').replace('||', 'or'), {'__builtins__': {}}, context)
                    self.assertEqual(actual, expected)


class FrozenWorkerBindingTests(unittest.TestCase):
    """Offline technical cases: real worker functions, synthetic cases, no Django/PG."""
    def setUp(self):
        import json
        import os
        import shutil
        import subprocess
        import tempfile
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        repo = self.directory/'repo'; repo.mkdir()
        self.source = self.directory/'source'; self.source.mkdir()
        for name, content in {'entry.sh':b'#!/bin/sh\n', 'nested/file with space.py':b'VALUE = 1\n'}.items():
            for directory in (repo,self.source):
                p=directory/name;p.parent.mkdir(exist_ok=True);p.write_bytes(content)
                if name.endswith('.sh'):p.chmod(0o755)
        def git(*args):
            return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.PIPE)
        git('init','-q');git('add','.')
        git('-c','user.name=synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','synthetic binding fixture')
        self.plan={'source':'git','test_sha':git('rev-parse','HEAD').decode().strip(),
                   'test_tree':git('rev-parse','HEAD^{tree}').decode().strip()}
        entries={}
        for record in git('ls-tree','-rz','HEAD').split(b'\0'):
            if record:
                meta,path=record.split(b'\t',1);mode,kind,oid=meta.decode().split()
                entries[path.decode()]={'mode':mode,'blob':oid}
        import base64
        raw_commit=git('cat-file','commit',self.plan['test_sha'])
        self.binding={**{k:self.plan[k] for k in ('test_sha','test_tree')},'files':entries,
                      'commit_base64':base64.b64encode(raw_commit).decode('ascii')}
        subprocess.check_call(['git','-C',str(self.source),'init','-q'],stdout=subprocess.DEVNULL)
        subprocess.check_call(['git','-C',str(self.source),'add','-Af','.'])
        restored=subprocess.check_output(['git','-C',str(self.source),'hash-object','-t','commit','-w','--stdin'],input=raw_commit).decode().strip()
        subprocess.check_call(['git','-C',str(self.source),'update-ref','refs/heads/impact',restored])
        subprocess.check_call(['git','-C',str(self.source),'symbolic-ref','HEAD','refs/heads/impact'])
        self.root=Path(__file__).resolve().parents[2]

    def worker_function(self, name, **namespace):
        import ast
        t=ast.parse((self.root/'scripts/test_plan_worker.py').read_text())
        fn=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'real-worker-'+name,'exec'),namespace)
        return namespace[name]

    def test_real_collector_assigns_all_29_new_ids_to_django(self):
        import ast
        import json
        from tools.test_impact.core import shard_tests
        catalog=json.loads((self.root/'tools/test_impact/catalog.json').read_text())
        labels=['stable.test_horse_career_record_from_review','stable.test_managed_readonly_steps']
        ids=[]
        for label in labels:
            t=ast.parse((self.root/'server'/Path(label.replace('.','/')).with_suffix('.py')).read_text())
            ids.extend(label+'.'+cls.name+'.'+fn.name for cls in t.body if isinstance(cls,ast.ClassDef)
                       for fn in cls.body if isinstance(fn,ast.FunctionDef) and fn.name.startswith('test'))
        self.assertEqual(len(ids),29)
        def case(ident):
            return SimpleNamespace(id=lambda:ident,_testMethodName='test_case',test_case=lambda:None)
        collect=self.worker_function('collect',load=lambda labels:[case(i) for i in ids if i.startswith(labels[0]+'.')],shard_tests=shard_tests)
        actual=collect({'labels':labels,'mode':'full'},catalog)
        self.assertEqual(actual['count'],29)
        self.assertEqual({i for b in actual['batches'] for i in b['ids']},set(ids))
        self.assertEqual({b['profile'] for b in actual['batches']},{'django'})
        self.assertEqual(actual['collection_skips'],[])
        for label in labels:
            bad={**catalog,'profiles':{k:v for k,v in catalog['profiles'].items() if k!=label}}
            with self.assertRaisesRegex(ValueError,'unowned test'):collect({'labels':[label],'mode':'full'},bad)

    def test_actual_git_snapshot_accepts_exact_tree_and_executable_modes(self):
        from tools.test_impact.source_binding import verify_source_binding
        self.assertEqual(verify_source_binding(self.plan,self.binding,self.source),self.plan['test_sha'])

    def test_missing_wrong_type_and_illegal_plan_sha_are_rejected(self):
        from tools.test_impact.source_binding import verify_source_binding
        for key in ('test_sha','test_tree'):
            for value in (None,True,123,[],{},b'a'*40,'a'*39,'A'*40,'a'*40+'\n','HEAD'):
                with self.subTest(key=key,value=repr(value)),self.assertRaises(ValueError):
                    verify_source_binding({**self.plan,key:value},self.binding,self.source)
            missing=self.plan.copy();missing.pop(key)
            with self.assertRaises(ValueError):verify_source_binding(missing,self.binding,self.source)
        with self.assertRaises(ValueError):verify_source_binding({**self.plan,'source':'local'},self.binding,self.source)

    def test_wrong_or_historical_binding_cannot_replace_plan_version(self):
        from tools.test_impact.source_binding import verify_source_binding
        for key in ('test_sha','test_tree'):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                verify_source_binding(self.plan,{**self.binding,key:'0'*40},self.source)
        forged={**self.plan,'test_tree':'0'*40}
        with self.assertRaisesRegex(ValueError,'commit identity mismatch'):
            verify_source_binding(forged,{**self.binding,'test_tree':'0'*40},self.source)

    def test_modified_missing_extra_symlink_and_mode_source_fail_closed(self):
        from tools.test_impact.source_binding import verify_source_binding
        p=self.source/'nested/file with space.py';original=p.read_bytes()
        p.write_bytes(b'VALUE = 2\n')
        with self.assertRaises(ValueError):verify_source_binding(self.plan,self.binding,self.source)
        p.write_bytes(original);p.chmod(0o755)
        with self.assertRaises(ValueError):verify_source_binding(self.plan,self.binding,self.source)
        p.chmod(0o644);p.unlink()
        with self.assertRaises(ValueError):verify_source_binding(self.plan,self.binding,self.source)
        p.symlink_to(self.directory/'repo/nested/file with space.py')
        with self.assertRaises(ValueError):verify_source_binding(self.plan,self.binding,self.source)
        p.unlink();p.write_bytes(original);extra=self.source/'extra.py';extra.write_text('')
        with self.assertRaisesRegex(ValueError,'unexpected'):verify_source_binding(self.plan,self.binding,self.source)

    def test_malformed_binding_files_are_rejected(self):
        from tools.test_impact.source_binding import verify_source_binding
        for files in (None,[],{}, {'../escape':{'mode':'100644','blob':'0'*40}},
                      {'entry.sh':{'mode':'120000','blob':'0'*40}}, {'entry.sh':{'mode':'100755','blob':True}}):
            with self.subTest(files=files),self.assertRaises(ValueError):
                verify_source_binding(self.plan,{**self.binding,'files':files},self.source)

    def test_real_setup_clears_host_values_then_injects_verified_code_sha(self):
        import os
        import sys
        import types
        from unittest.mock import Mock, patch
        from scripts.run_bounded_stable_tests import isolated_environment
        from tools.test_impact.source_binding import verify_source_binding
        django=types.ModuleType('django');django.setup=Mock()
        conf=types.ModuleType('django.conf');conf.settings=SimpleNamespace()
        dotenv=types.ModuleType('dotenv');dotenv.load_dotenv=Mock()
        setup=self.worker_function('setup',ROOT=self.source,os=os,sys=sys,
                                   isolated_environment=isolated_environment,verify_source_binding=verify_source_binding)
        with patch.dict(sys.modules,{'django':django,'django.conf':conf,'dotenv':dotenv}),patch.dict(os.environ,{'PATH':os.environ['PATH'],'A045_TEST_CODE_SHA':'0'*40,'HOST_SENTINEL':'discard'}),patch.object(sys,'argv',[]):
            setup('django',self.plan,self.binding)
            self.assertEqual(os.environ['A045_TEST_CODE_SHA'],self.plan['test_sha'])
            self.assertNotIn('HOST_SENTINEL',os.environ)
            django.setup.assert_called_once_with()
        django.setup.reset_mock()
        with patch.dict(sys.modules,{'django':django,'django.conf':conf,'dotenv':dotenv}),self.assertRaises(ValueError):
            setup('django',{**self.plan,'test_sha':None},self.binding)
        django.setup.assert_not_called()

    def test_real_main_passes_control_plan_and_binding_to_setup(self):
        import json
        import sys
        from unittest.mock import Mock, patch
        control=self.directory/'control';control.mkdir()
        (control/'plan.json').write_text(json.dumps(self.plan))
        (control/'source-binding.json').write_text(json.dumps(self.binding))
        setup=Mock()
        def path(value):
            return control/Path(value).name if str(value).startswith('/control/') else Path(value)
        stop=RuntimeError('synthetic collection boundary')
        main=self.worker_function('main',sys=sys,json=json,Path=path,ROOT=self.root,
                                  setup=setup,collect=Mock(side_effect=stop))
        with patch.object(sys,'argv',['worker','collect']),self.assertRaisesRegex(RuntimeError,'synthetic collection boundary'):
            main()
        setup.assert_called_once_with('django',self.plan,self.binding)

    def test_formal_executor_rejects_unresolved_commit_and_tree_before_docker(self):
        import argparse
        import ast
        import json
        import subprocess
        import sys
        from unittest.mock import Mock, patch
        from tools.test_impact.git_input import git, commit
        from tools.test_impact.source_binding import validate_source_plan
        from tools.test_impact.core import digest
        planfile=self.directory/'plan.json'
        t=ast.parse((self.root/'scripts/run_test_plan.py').read_text())
        fn=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        gate=Mock(side_effect=RuntimeError('offline Docker boundary'))
        namespace=dict(argparse=argparse,Path=Path,ROOT=self.directory/'repo',json=json,
                       git=git,commit=commit,validate_source_plan=validate_source_plan,
                       digest=digest,verify_local_docker=gate)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'real-executor-main','exec'),namespace)
        argv=['runner','--plan',str(planfile),'--output',str(self.directory/'output')]
        for change in ({'test_sha':'0'*40},{'test_tree':'0'*40},{'test_sha':None},{'test_tree':True}):
            planfile.write_text(json.dumps({**self.plan,'mode':'full',**change}))
            with patch.object(sys,'argv',argv),self.assertRaises((ValueError,subprocess.CalledProcessError)):
                namespace['main']()
            gate.assert_not_called()
        planfile.write_text(json.dumps({**self.plan,'mode':'full'}))
        with patch.object(sys,'argv',argv),self.assertRaisesRegex(RuntimeError,'offline Docker boundary'):
            namespace['main']()
        gate.assert_called_once_with()

    def test_worker_refuses_wrong_actual_head_and_forged_commit_payload(self):
        import base64
        import subprocess
        from tools.test_impact.source_binding import verify_source_binding
        self.assertEqual(verify_source_binding(self.plan,self.binding,self.source,require_git_head=True),self.plan['test_sha'])
        for value in (None,True,'not-base64',base64.b64encode(b'tree '+self.plan['test_tree'].encode()+b'\n\nforged\n').decode()):
            with self.subTest(value=value),self.assertRaises(ValueError):
                verify_source_binding(self.plan,{**self.binding,'commit_base64':value},self.source)
        subprocess.check_call(['git','-C',str(self.source),'-c','user.name=synthetic','-c','user.email=synthetic@example.invalid',
                               'commit','--allow-empty','-qm','different actual HEAD'])
        with self.assertRaisesRegex(ValueError,'actual frozen HEAD mismatch'):
            verify_source_binding(self.plan,self.binding,self.source,require_git_head=True)


class HistoricalMigrationFixtureCompatibilityTests(unittest.TestCase):
    """Real historical hash functions with AST-only fixture extraction, no Django."""
    def fixture_functions(self, root):
        import ast
        import hashlib
        import shutil
        source=Path(__file__).resolve().parents[2]
        tree=ast.parse((source/'server/stable/release_0078_test_fixture.py').read_text())
        nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name=='copy_historical_migrations') or
               (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POST_GENERATION_MIGRATIONS' for t in n.targets))]
        namespace={'ROOT':root,'Path':Path,'shutil':shutil}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-historical-fixture','exec'),namespace)
        return namespace['copy_historical_migrations']

    def contract(self, generation, module_path):
        import ast
        import hashlib
        root=Path(__file__).resolve().parents[2]
        t=ast.parse((root/('server/stable/services/release_'+generation+'_recovery.py')).read_text())
        nodes=[n for n in t.body if (isinstance(n,ast.FunctionDef) and n.name=='migration_contract') or
               (isinstance(n,ast.Assign) and any(isinstance(a,ast.Name) and a.id=='MIGRATION_CONTRACT_SHA256' for a in n.targets))]
        namespace={'Path':Path,'hashlib':hashlib,'__file__':str(module_path)}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-historical-contract-'+generation,'exec'),namespace)
        return namespace['migration_contract'],namespace['MIGRATION_CONTRACT_SHA256']

    def test_exact_historical_copies_match_original_0078_and_0079_hashes(self):
        import tempfile
        root=Path(__file__).resolve().parents[2]
        copy=self.fixture_functions(root)
        with tempfile.TemporaryDirectory() as tmp:
            for generation in ('0078','0079'):
                with self.subTest(generation=generation):
                    target=Path(tmp)/generation/'stable/migrations';target.parent.mkdir(parents=True)
                    copy(target,generation=generation)
                    contract,expected=self.contract(generation,target.parent/'services/release.py')
                    self.assertEqual(contract(),expected)
                    self.assertFalse((target/'0081_managed_readonly_steps.py').exists())
                    self.assertTrue((target/'0078_externalhorse_profile_snapshot.py').exists())
                    self.assertEqual((target/'0079_multisource_race_enrollment.py').exists(),generation=='0079')

    def test_unknown_future_and_nested_known_names_remain_in_hash_and_are_refused(self):
        import tempfile
        import shutil
        original=Path(__file__).resolve().parents[2]
        for relative in ('0082_unknown.py','0081_unknown.py','nested/0081_managed_readonly_steps.py','__pycache__/0081_managed_readonly_steps.py'):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'source';directory=root/'server/stable/migrations';directory.parent.mkdir(parents=True)
                shutil.copytree(original/'server/stable/migrations',directory)
                extra=directory/relative;extra.parent.mkdir(exist_ok=True);extra.write_text('# unreviewed migration\n')
                copy=self.fixture_functions(root)
                for generation in ('0078','0079'):
                    target=Path(tmp)/generation/'stable/migrations';target.parent.mkdir(parents=True);copy(target,generation=generation)
                    self.assertTrue((target/relative).exists())
                    contract,_=self.contract(generation,target.parent/'services/release.py')
                    with self.assertRaisesRegex(ValueError,generation+' migration file/content contract drift'):contract()

    def test_current_directory_is_still_refused_by_unchanged_production_contracts(self):
        root=Path(__file__).resolve().parents[2]
        for generation in ('0078','0079'):
            contract,_=self.contract(generation,root/('server/stable/services/release_'+generation+'_recovery.py'))
            with self.subTest(generation=generation),self.assertRaisesRegex(ValueError,generation+' migration file/content contract drift'):
                contract()
