#!/usr/bin/env python3
"""候选目录外的交付核验器。只读 Git/GitHub；不合并、不导入候选代码。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


def checked(command, cwd=None):
    return subprocess.check_output(command,cwd=cwd,stderr=subprocess.PIPE)


def api(repo,path):
    return json.loads(checked(['gh','api',f'repos/{repo}/{path}']))


def require(condition,message):
    if not condition:raise ValueError(message)


def verify_jobs(jobs):
    require(len({j['id'] for j in jobs})==len(jobs),'duplicate jobs')
    for name,steps in {'tests':{'checkout-test-tree','static-contracts','generate-plan','execute-isolated-plan','verify-execution','upload-evidence'},
                       'test-plan-gate':{'require-complete-plan'}}.items():
        matches=[j for j in jobs if j['name']==name]
        require(len(matches)==1 and matches[0]['conclusion']=='success',f'missing/failed job: {name}')
        actual={s['name']:s['conclusion'] for s in matches[0]['steps']}
        require(all(actual.get(s)=='success' for s in steps),f'missing/skipped step: {name}')


def verify_protection(protection):
    checks=protection.get('required_status_checks') or {}
    contexts=set(checks.get('contexts',[])) | {c['context'] for c in checks.get('checks',[])}
    require(checks.get('strict') is True and 'test-plan-gate' in contexts and
            protection.get('enforce_admins',{}).get('enabled') is True,
            'strict required test-plan-gate including admins is not active')


def compare_collection(plan, collected):
    require(plan['batches']==collected['batches'] and plan['count']==collected['count'],
            'independent collection mismatch')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository',type=Path,required=True)
    p.add_argument('--repo',required=True,help='GitHub owner/repo')
    p.add_argument('--pr',type=int,required=True);p.add_argument('--run',type=int,required=True)
    p.add_argument('--trusted-sha',required=True,help='由协调者从实时 main 或独立审核记录取得')
    p.add_argument('--reviewed-controls',type=Path,help='候选目录外的独立review白名单：exact commit + control_blobs')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.repository.resolve()
    require(not Path(__file__).resolve().is_relative_to(root),'extract verifier outside candidate and invoke python -I')
    require(sys.flags.isolated,'python -I required')
    require(re.fullmatch('[0-9a-f]{40}',a.trusted_sha),'exact trusted SHA required')
    def git(*args):return checked(['git','-C',str(root),*args])
    current=api(a.repo,'commits/main')['sha']
    pr=api(a.repo,f'pulls/{a.pr}')
    base,head,test=pr['base']['sha'],pr['head']['sha'],pr['merge_commit_sha']
    require(pr['state']=='open' and pr['base']['ref']=='main','not an open main PR')
    require(current==base,'STALE_BASE')
    require(test and pr['mergeable'] is not False,'unavailable merge tree')
    for sha in (base,head,test,a.trusted_sha):
        require(re.fullmatch('[0-9a-f]{40}',sha),'invalid SHA')
        git('cat-file','-e',sha+'^{commit}')
    require(git('show','-s','--format=%P',test).decode().split()==[base,head],'STALE_BASE or merge identity')
    review=None
    if a.reviewed_controls:
        require(not a.reviewed_controls.resolve().is_relative_to(root),'review allowlist must be coordinator-owned')
        review=json.loads(a.reviewed_controls.read_text())
        require(review['commit']==head,'independent review belongs to another head')
    if a.trusted_sha!=base:
        require(review and review.get('trusted_sha')==a.trusted_sha,'bootstrap verifier requires independent review binding')
    # 校验运行的本文件来自声明的受信对象。
    require(git('show',a.trusted_sha+':scripts/verify_delivery_test_evidence.py')==Path(__file__).read_bytes(),'verifier provenance mismatch')
    run=api(a.repo,f'actions/runs/{a.run}')
    require(run['event']=='pull_request' and run['head_sha']==head and run['conclusion']=='success','not successful exact PR run')
    require(run['path']=='.github/workflows/affected_tests.yml','wrong workflow')
    attempt=run['run_attempt']
    jobs=api(a.repo,f'actions/runs/{a.run}/attempts/{attempt}/jobs?per_page=100')['jobs']
    verify_jobs(jobs)
    artifacts=api(a.repo,f'actions/runs/{a.run}/artifacts?per_page=100')['artifacts']
    matches=[x for x in artifacts if x['name']==f'impact-{a.run}-{attempt}' and not x['expired']]
    require(len(matches)==1,'missing/ambiguous artifact')
    archive=checked(['gh','api',f'repos/{a.repo}/actions/artifacts/{matches[0]["id"]}/zip'])
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        require(sum(i.file_size for i in z.infolist())<100_000_000,'artifact too large')
        names=z.namelist();require(len(names)==len(set(names)),'duplicate zip names')
        plan=json.loads(z.read('execution-plan.json'))
        reports=[json.loads(z.read(n)) for n in names if re.fullmatch('batch-[0-9]+.json',n)]
    require(plan['source']=='git' and plan['mode']!='validation-only','diagnostic evidence is not deliverable')
    require(plan['base_sha']==base and plan['head_sha']==head and plan['test_sha']==test,'STALE_BASE or stale head')
    require(plan['test_tree']==git('rev-parse',test+'^{tree}').decode().strip(),'tree mismatch')
    require(plan['run_id']==str(a.run) and plan['run_attempt']==str(attempt),'artifact run mismatch')
    entries={record.split(b'\t',1)[1].decode():record.split(b'\t',1)[0].decode().split()[2] for record in git('ls-tree','-rz',test).split(b'\0') if record}
    controls={path:oid for path,oid in entries.items() if path.startswith(('tools/test_impact/','deploy/test-impact/')) or path in (
        'requirements.txt','scripts/plan_affected_tests.py','scripts/run_test_plan.py','scripts/test_plan_worker.py',
        'scripts/verify_test_plan.py','scripts/impact_ci.py','scripts/run_bounded_stable_tests.py',
        '.github/workflows/affected_tests.yml','.github/workflows/full_regression.yml')}
    require(plan['control_blobs']==controls,'missing or unexpected control identities')
    base_has_catalog=bool(git('ls-tree',base,'tools/test_impact/catalog.json').strip())
    require(plan['bootstrap'] is (not base_has_catalog),'forged bootstrap bypass')
    for path,oid in controls.items():
        require(git('rev-parse',test+':'+path).decode().strip()==oid,'candidate control mismatch: '+path)
        try:trusted=git('rev-parse',base+':'+path).decode().strip()
        except subprocess.CalledProcessError:trusted=None
        require(oid==trusted or (review and review['control_blobs'].get(path)==oid),'unreviewed control: '+path)
    # 从受信 Git 对象提取纯数据规划器；绝不以候选目录作为 Python 搜索路径。
    with tempfile.TemporaryDirectory(prefix='trusted-impact-') as raw:
        bundle=Path(raw)
        paths=['tools/test_impact/core.py','tools/test_impact/git_input.py','scripts/plan_affected_tests.py','scripts/run_test_plan.py']
        for path in paths:
            out=bundle/path;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(git('show',a.trusted_sha+':'+path))
        if plan['mode']!='docs-only':
            steps={s['name']:s['conclusion'] for j in jobs if j['name']=='tests' for s in j['steps']}
            require(steps.get('upload-test-image')=='success','missing actual image upload step')
            images=[x for x in artifacts if x['name']==f'impact-image-{a.run}-{attempt}' and not x['expired']]
            require(len(images)==1,'missing exact-run test image')
            image_archive=checked(['gh','api',f'repos/{a.repo}/actions/artifacts/{images[0]["id"]}/zip'])
            with zipfile.ZipFile(io.BytesIO(image_archive)) as z:
                require(z.namelist()==['impact-image.tar'] and z.getinfo('impact-image.tar').file_size<4_000_000_000,'invalid image artifact')
                image_path=bundle/'image.tar'
                with z.open('impact-image.tar') as src,image_path.open('wb') as dst:
                    import shutil
                    shutil.copyfileobj(src,dst)
            # 校验本地Docker上下文，不允许生产/远程daemon；加载后按digest运行。
            endpoint=checked(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}']).decode().strip()
            require(not os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT') and endpoint.startswith('unix://'),'local Docker required')
            checked(['docker','load','-i',str(image_path)])
            require(re.fullmatch('sha256:[0-9a-f]{64}',plan['image_id']),'invalid image ID')
            source_plan=bundle/'selection.json';source_plan.write_text(json.dumps(plan))
            trusted_controls=bundle/'execution-controls'
            for path in ('scripts/test_plan_worker.py','scripts/run_bounded_stable_tests.py','deploy/test-impact/entrypoint.sh','tools/test_impact/core.py'):
                control=trusted_controls/path;control.parent.mkdir(parents=True,exist_ok=True)
                control.write_bytes(git('cat-file','blob',controls[path]))
            collection_dir=bundle/'collection'
            checked([sys.executable,'-I',str(bundle/'scripts/run_test_plan.py'),'--repository',str(root),
                     '--plan',str(source_plan),'--output',str(collection_dir),'--collect-only','--image',plan['image_id'],'--controls',str(trusted_controls)])
            compare_collection(plan,json.loads((collection_dir/'execution-plan.json').read_text()))
        else:
            compare_collection(plan,{'batches':[],'count':0})
        config=bundle/'input.json'
        config.write_text(json.dumps({'root':str(root),'base':base,'head':head,'test':test,'plan':plan,'reports':reports}))
        program="""import json,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/scripts']
from plan_affected_tests import create_plan
from tools.test_impact.core import verify_results
x=json.loads(Path(sys.argv[2]).read_text()); p=x['plan']
e=create_plan(Path(x['root']),x['base'],x['head'],x['test'],bootstrap=p['bootstrap'])
for field in ('domains','labels','hashes','changed_paths','content_digest','allowed_skips'):
 if p[field]!=e[field]: raise ValueError('trusted plan mismatch: '+field)
if e['mode']=='full' and p['mode']!='full': raise ValueError('full scope downgraded')
print(json.dumps(verify_results(p,x['reports'])))
"""
        verified=json.loads(checked([sys.executable,'-I','-c',program,str(bundle),str(config)]))
    protection=api(a.repo,'branches/main/protection')
    verify_protection(protection)
    # 第二次读取收尾；实际 merge 仍由 strict 服务端检查防止之后的竞态。
    require(api(a.repo,'commits/main')['sha']==base and api(a.repo,f'pulls/{a.pr}')['head']['sha']==head,'STALE_BASE')
    receipt={'status':'verified','base_sha':base,'head_sha':head,'test_sha':test,'test_tree':plan['test_tree'],
             'run_id':a.run,'run_attempt':attempt,'artifact_id':matches[0]['id'],
             'artifact_sha256':hashlib.sha256(archive).hexdigest(),'trusted_sha':a.trusted_sha,
             'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'summary':verified}
    a.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
