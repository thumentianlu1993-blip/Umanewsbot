#!/usr/bin/env python3
"""固定 Git 快照，在无外网容器中收集/执行；不提供宿主回退。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.test_impact.git_input import git
from tools.test_impact.core import digest


def docker(*args, **kw):
    return subprocess.run(['docker',*args],check=True,**kw)


def verify_local_docker():
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise ValueError('explicit Docker overrides refused; use a verified local context')
    endpoint=subprocess.check_output(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}'],text=True).strip()
    if not endpoint.startswith('unix://'):
        raise ValueError('only a local Docker socket is allowed')
    docker('info',stdout=subprocess.DEVNULL)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--batch')
    parser.add_argument('--image',default='umanews-test-impact:local')
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text())
    if plan['source']!='git':
        raise ValueError('local dirty plans are diagnostic only; commit snapshot before execution')
    if git(ROOT,'rev-parse',plan['test_sha']+'^{tree}').decode().strip()!=plan['test_tree']:
        raise ValueError('test tree mismatch')
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    if plan['mode']=='docs-only':
        # 静态合同由 workflow 独立步骤执行，不启动 Docker/PG。
        plan.update(batches=[],count=0)
        (output/'execution-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
        return
    verify_local_docker()
    with tempfile.TemporaryDirectory(prefix='impact-') as temp:
        temp=Path(temp); source=temp/'source'; source.mkdir()
        archive=temp/'source.tar'; archive.write_bytes(git(ROOT,'archive',plan['test_sha']))
        with tarfile.open(archive) as tar:
            tar.extractall(source,filter='data')
        if args.build:
            context=temp/'build'; context.mkdir()
            shutil.copy(source/'requirements.txt',context/'requirements.txt')
            shutil.copy(source/'deploy/test-impact/Dockerfile',context/'Dockerfile')
            with (output/'image-build.log').open('w') as log:
                docker('build','-t',args.image,str(context),stdout=log,stderr=subprocess.STDOUT)
        image_id=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',args.image],text=True).strip()
        plan['image_id']=image_id
        control=temp/'control'; control.mkdir()
        (control/'plan.json').write_text(json.dumps(plan))
        def invoke(mode,key='',profile=''):
            out=temp/(key or 'collection'); out.mkdir(); out.chmod(0o777)
            container_name='impact-'+uuid.uuid4().hex
            command=['run','--name',container_name,'--rm','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
                     '--pids-limit','256','--memory','4g','--cpus','2','--read-only','--tmpfs','/tmp:rw,exec,size=3g',
                     '--mount',f'type=bind,src={source},dst=/source,readonly',
                     '--mount',f'type=bind,src={control},dst=/control,readonly',
                     '--mount',f'type=bind,src={out},dst=/output',image_id,mode,key,profile]
            with (output/((key or 'collection')+'.log')).open('w') as log:
                try:
                    completed=subprocess.run(['docker',*command],stdout=log,stderr=subprocess.STDOUT,timeout=2100 if profile=='release-postgres' else 600)
                finally:
                    subprocess.run(['docker','rm','-f',container_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            for file in out.glob('*.json'): shutil.copy(file,output/file.name)
            return completed.returncode
        if not args.batch:
            if invoke('collect'):
                raise ValueError('collection failed; see collection.log')
            plan=json.loads((output/'execution-plan.json').read_text())
        else:
            # 分片必须使用收集时的同一镜像。
            original=json.loads(args.plan.read_text())
            if original['image_id']!=image_id:
                raise ValueError('collection/execution image mismatch')
            plan=original
        (control/'plan.json').write_text(json.dumps(plan))
        if args.collect_only:
            print(json.dumps({'mode':plan['mode'],'count':plan['count'],'batches':len(plan['batches']),'image_id':image_id})); return
        batches=[b for b in plan['batches'] if not args.batch or b['key']==args.batch]
        if not batches: raise ValueError('no selected batches')
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes=list(pool.map(lambda b:invoke('run',b['key'],b['profile']),batches))
        print(json.dumps({'mode':plan['mode'],'count':sum(len(b['ids']) for b in batches),'batches':len(batches),'failed_batches':sum(bool(c) for c in codes)}))
        if any(codes): raise SystemExit(1)


if __name__=='__main__': main()
