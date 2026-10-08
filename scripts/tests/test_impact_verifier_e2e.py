"""候选外核验器端到端：真实Git/进程/zip，仅用本地fake替代GitHub。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from scripts.plan_affected_tests import create_plan
from tools.test_impact.git_input import files
ROOT=Path(__file__).resolve().parents[2]


class OutsideVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name);self.repo=self.work/'repo';self.repo.mkdir()
        self.git('init','-q');self.git('config','user.email','ci@example.invalid');self.git('config','user.name','ci')
        self.trusted_dependencies=['tools/test_impact/core.py','tools/test_impact/git_input.py',
               'scripts/plan_affected_tests.py','scripts/run_test_plan.py','tools/test_impact/source_binding.py',
               'scripts/test_plan_worker.py','scripts/run_bounded_stable_tests.py','deploy/test-impact/entrypoint.sh']
        for name in ['scripts/verify_delivery_test_evidence.py',*self.trusted_dependencies]:
            p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
        self.rules={'schema_version':1,'docs':['docs/*.md'],'high_risk':['tools/test_impact/**','.github/**'],
                    'paths':{'service.py':['core']},'symbols':{}}
        self.catalog={'schema_version':1,'domains':{'core':['fake.Tests']},'tests':{},'dependencies':{},'allowed_skips':{}}
        for name,data in [('rules',self.rules),('catalog',self.catalog)]:
            (self.repo/f'tools/test_impact/{name}.json').write_text(json.dumps(data))
        (self.repo/'service.py').write_text('x=1\n');(self.repo/'docs').mkdir();(self.repo/'docs/a.md').write_text('old\n')
        self.git('add','.');self.git('commit','-qm','base');self.base=self.git('rev-parse','HEAD')
        self.verifier=self.work/'trusted-verifier.py';shutil.copyfile(ROOT/'scripts/verify_delivery_test_evidence.py',self.verifier)

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],text=True,stderr=subprocess.DEVNULL).strip()

    def prepare(self,business=False):
        path='service.py' if business else 'docs/a.md';(self.repo/path).write_text('x=2\n' if business else 'new\n')
        self.git('add','.');self.git('commit','-qm','candidate');head=self.git('rev-parse','HEAD')
        merge=self.git('commit-tree',head+'^{tree}','-p',self.base,'-p',head,'-m','synthetic merge')
        plan=create_plan(self.repo,self.base,head,merge);plan.update(mode='docs-only',batches=[],count=0,run_id='11',run_attempt='1')
        plan['control_blobs']={p:oid for p,oid in files(self.repo,merge).items() if p.startswith(('tools/test_impact/','deploy/test-impact/','.github/workflows/')) or p in (
            'requirements.txt','scripts/plan_affected_tests.py','scripts/run_test_plan.py','scripts/test_plan_worker.py',
            'scripts/verify_test_plan.py','scripts/impact_ci.py','scripts/run_bounded_stable_tests.py')}
        archive=self.work/'artifact.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('execution-plan.json',json.dumps(plan))
        jobs=[{'id':1,'name':'tests','conclusion':'success','steps':[{'name':n,'conclusion':'success'} for n in
               ('checkout-test-tree','static-contracts','generate-plan','execute-isolated-plan','verify-execution','upload-evidence')]},
              {'id':2,'name':'test-plan-gate','conclusion':'success','steps':[{'name':'require-complete-plan','conclusion':'success'}]}]
        self.responses={
            'commits/main':{'sha':self.base},
            'pulls/1':{'state':'open','base':{'sha':self.base,'ref':'main'},'head':{'sha':head},'merge_commit_sha':merge,'mergeable':True},
            'actions/runs/11':{'event':'pull_request','head_sha':head,'conclusion':'success','path':'.github/workflows/affected_tests.yml','run_attempt':1},
            'actions/runs/11/attempts/1/jobs?per_page=100':{'jobs':jobs},
            'actions/runs/11/artifacts?per_page=100':{'artifacts':[{'id':22,'name':'impact-11-1','expired':False}]},
            'branches/main/protection':{'required_status_checks':{'strict':True,'contexts':['test-plan-gate']},'enforce_admins':{'enabled':True}},
        }
        bin_dir=self.work/'bin';bin_dir.mkdir()
        gh=bin_dir/'gh';gh.write_text('#!'+sys.executable+'\n'+'''import json,os,pathlib,sys
root=pathlib.Path(os.environ['FAKE_API_ROOT']); path=sys.argv[2].removeprefix('repos/fixture/project/')
with (root/'api-calls.jsonl').open('a') as trace: trace.write(json.dumps(path)+'\\n')
if path=='actions/artifacts/22/zip':sys.stdout.buffer.write((root/'artifact.zip').read_bytes())
else:print(json.dumps(json.loads((root/'responses.json').read_text())[path]))
''');gh.chmod(0o755)
        # 任意误入镜像/容器分支都先在自有fixture中拒绝，不接触宿主daemon。
        docker=bin_dir/'docker'
        docker.write_text('#!'+sys.executable+'\n'+'''import os,pathlib
(pathlib.Path(os.environ['FAKE_API_ROOT'])/'docker-invoked').write_text('forbidden')
raise SystemExit('Docker is forbidden in these offline fixture tests')
''');docker.chmod(0o755)
        return plan

    def run_verifier(self):
        (self.work/'responses.json').write_text(json.dumps(self.responses))
        env={**os.environ,'PATH':str(self.work/'bin')+os.pathsep+os.environ['PATH'],'FAKE_API_ROOT':str(self.work)}
        result=subprocess.run([sys.executable,'-I',str(self.verifier),'--repository',str(self.repo),'--repo','fixture/project',
                               '--pr','1','--run','11','--trusted-sha',self.base,'--output',str(self.work/'receipt.json')],
                              capture_output=True,text=True,env=env,timeout=30)
        self.assertFalse((self.work/'docker-invoked').exists(), 'offline verifier fixture reached Docker')
        return result

    def test_true_docs_only_generates_receipt_outside_candidate(self):
        self.prepare();result=self.run_verifier();self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads((self.work/'receipt.json').read_text())
        self.assertEqual(receipt['summary']['count'],0)
        self.assertEqual(set(receipt['trusted_bundle']['files']),set(self.trusted_dependencies))
        for path,entry in receipt['trusted_bundle']['files'].items():
            self.assertEqual(entry['blob'],self.git('rev-parse',self.base+':'+path))

    def test_business_disguised_as_docs_is_rejected_before_image_download(self):
        self.prepare(business=True);result=self.run_verifier()
        self.assertNotEqual(result.returncode,0);self.assertIn('trusted mode mismatch',result.stderr)
        self.assertFalse((self.work/'receipt.json').exists())

    def test_missing_actual_step_is_rejected(self):
        self.prepare();self.responses['actions/runs/11/attempts/1/jobs?per_page=100']['jobs'][0]['steps'].pop()
        result=self.run_verifier();self.assertNotEqual(result.returncode,0);self.assertIn('missing/skipped step',result.stderr)

    def test_base_advance_is_rejected(self):
        self.prepare();self.responses['commits/main']['sha']='f'*40
        result=self.run_verifier();self.assertNotEqual(result.returncode,0);self.assertIn('STALE_BASE',result.stderr)

    def test_missing_trusted_dependency_is_rejected(self):
        dependency = self.repo/'tools/test_impact/source_binding.py'
        if dependency.exists():
            dependency.unlink();self.git('add','-A');self.git('commit','-qm','missing trusted dependency')
            self.base=self.git('rev-parse','HEAD')
        self.prepare();result=self.run_verifier()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('source_binding.py',result.stderr)
        self.assertFalse((self.work/'receipt.json').exists())

    def test_unreviewed_candidate_control_is_rejected(self):
        control=self.repo/'tools/test_impact/core.py'
        control.write_text(control.read_text()+'\n# unreviewed candidate change\n')
        self.prepare();result=self.run_verifier()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unreviewed control: tools/test_impact/core.py',result.stderr)
        self.assertFalse((self.work/'receipt.json').exists())
