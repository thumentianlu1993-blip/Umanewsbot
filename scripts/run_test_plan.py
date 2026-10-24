#!/usr/bin/env python3
"""固定 Git 快照，在无外网容器中收集/执行；不提供宿主回退。"""
import argparse
import base64
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
from tools.test_impact.git_input import git, commit
from tools.test_impact.core import digest
from tools.test_impact.serial_ci import OwnedObserver
from tools.test_impact.source_binding import validate_source_plan, verify_source_binding


OBSERVER=None
STAGE='preflight'

def docker(*args, **kw):
    if OBSERVER is not None:
        return OBSERVER.run(['docker',*args],STAGE,check=True,**kw)
    return subprocess.run(['docker',*args],check=True,**kw)


def verify_local_docker():
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise ValueError('explicit Docker overrides refused; use a verified local context')
    endpoint=subprocess.check_output(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}'],text=True).strip()
    if not endpoint.startswith('unix://'):
        raise ValueError('only a local Docker socket is allowed')
    docker('info',stdout=subprocess.DEVNULL)


class ObservedTemporaryDirectory:
    """证据无法落盘时保留唯一原件；不改变默认native临时目录行为。"""
    def __init__(self, observer):self.observer=observer;self.name=None;self.retain_temp=False
    def __enter__(self):
        self.name=tempfile.mkdtemp(prefix='impact-');return self.name
    def __exit__(self,*error):
        if self.retain_temp or (self.observer is not None and self.observer.retain_temp):
            try:print('OWNED_TEMP_RETAINED '+self.name,file=sys.stderr,flush=True)
            except BaseException:pass
        else:
            try:shutil.rmtree(self.name)
            except BaseException as exc:
                self.retain_temp=True
                if error and error[1] is not None:
                    error[1].add_note('temporary cleanup failed; retained '+self.name+': '+repr(exc))
                else:raise


def source_temporary(observer):
    return ObservedTemporaryDirectory(observer)


def main():
    global OBSERVER, STAGE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',type=Path,default=ROOT)
    parser.add_argument('--controls',type=Path,help='候选外核验器提供的受信执行文件目录')
    parser.add_argument('--export-image',type=Path)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--batch')
    parser.add_argument('--image',default='umanews-test-impact:local')
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--resource-ledger',type=Path)
    parser.add_argument('--invoke-deadline-monotonic',type=float)
    parser.add_argument('--final-reserve-seconds',type=float,default=600)
    args=parser.parse_args()
    if args.resource_ledger:
        if args.invoke_deadline_monotonic is None: raise ValueError('owned observation requires deadline')
        OBSERVER=OwnedObserver(args.resource_ledger,args.invoke_deadline_monotonic,args.final_reserve_seconds)
    else:
        OBSERVER=None
    root=args.repository.resolve()
    plan=json.loads(args.plan.read_text())
    if plan['source']!='git':
        raise ValueError('local dirty plans are diagnostic only; commit snapshot before execution')
    test_sha, test_tree = validate_source_plan(plan)
    commit(root, test_sha)
    if git(root,'rev-parse',test_sha+'^{tree}').decode().strip()!=test_tree:
        raise ValueError('test tree mismatch')
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    if plan['mode']=='docs-only':
        # 静态合同由 workflow 独立步骤执行，不启动 Docker/PG。
        plan.update(batches=[],count=0)
        (output/'execution-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
        return
    if OBSERVER and not args.collect_only and not args.batch:
        raise ValueError('owned observation requires collect-only or exactly one original batch')
    verify_local_docker()
    temporary=source_temporary(OBSERVER)
    with temporary as temp:
        temp=Path(temp); source=temp/'source'; source.mkdir()
        archive=temp/'source.tar'; archive.write_bytes(git(root,'archive',plan['test_sha']))
        with tarfile.open(archive) as tar:
            tar.extractall(source,filter='data')
        if args.controls:
            for file in args.controls.rglob('*'):
                if file.is_file():
                    target=source/file.relative_to(args.controls)
                    if target.read_bytes()!=file.read_bytes(): raise ValueError('trusted execution control mismatch')
                    shutil.copyfile(file,target)
        entries={}
        for record in git(root,'ls-tree','-rz',test_sha).split(b'\0'):
            if not record: continue
            meta, path=record.split(b'\t',1)
            mode, kind, oid=meta.decode().split()
            if kind!='blob': raise ValueError('non-blob frozen source')
            entries[path.decode()]={'mode':mode,'blob':oid}
        raw_commit=git(root,'cat-file','commit',test_sha)
        binding={'test_sha':test_sha,'test_tree':test_tree,'files':entries,
                 'commit_base64':base64.b64encode(raw_commit).decode('ascii')}
        verify_source_binding(plan,binding,source)
        if args.build:
            STAGE='image-build'
            context=temp/'build'; context.mkdir()
            shutil.copy(source/'requirements.txt',context/'requirements.txt')
            shutil.copy(source/'deploy/test-impact/Dockerfile',context/'Dockerfile')
            with (output/'image-build.log').open('w') as log:
                docker('build','-t',args.image,str(context),stdout=log,stderr=subprocess.STDOUT)
        image_id=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',args.image],text=True).strip()
        if args.export_image:
            STAGE='image-export'
            with args.export_image.open('wb') as image_file:
                docker('save',image_id,stdout=image_file)
        plan['image_id']=image_id
        frozen_plan_bytes=json.dumps(plan).encode()
        frozen_binding_bytes=json.dumps(binding).encode()
        def invoke(mode,key='',profile=''):
            from tools.test_impact import pg_lifecycle as lifecycle
            seconds=2100 if profile=='release-postgres' else 600
            if OBSERVER:
                OBSERVER.admission(seconds)
                if key and any((output/(key+s)).exists() for s in ('.json','.log')): raise ValueError('owned duplicate batch output')
            out=temp/(key or 'collection'); out.mkdir(); out.chmod(0o777)
            # 按值捕获phase输入；无共享可替换/control请求/plan，max_workers4保持。
            control,request=lifecycle.prepare_control(temp,frozen_plan_bytes,frozen_binding_bytes,raw_commit,mode,key,profile)
            request_bytes=lifecycle.read_regular(control/'pg-lifecycle-request.json')
            saved_request=output/lifecycle.request_filename(mode,key)
            container_name='impact-'+uuid.uuid4().hex
            command=['run','--name',container_name,'--rm','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
                     '--pids-limit','256','--memory','4g','--cpus','2','--read-only','--tmpfs','/tmp:rw,exec,size=3g',
                     '--mount',f'type=bind,src={source},dst=/source,readonly',
                     '--mount',f'type=bind,src={control},dst=/control,readonly',
                     '--mount',f'type=bind,src={out},dst=/output',image_id,mode,key,profile]
            cidfile=None
            expected=lifecycle.native_filename(mode,key);life=lifecycle.receipt_filename(mode,key)
            primary=None;completed=None;cleanup=None
            def _retain_output():
                if OBSERVER:OBSERVER.retain_temp=True
                else:temporary.retain_temp=True

            def _classify_outputs():
                # 只看本invoke目录项名称及已知项类型；绝不打开/解析未知内容。
                import stat as _stat
                try:
                    entries=tuple(out.iterdir())
                    returned={entry.name for entry in entries}
                    if returned != {expected,life}:
                        _retain_output()
                        return lifecycle.ReceiptError('OUTPUT_SET_MISMATCH',str(sorted(returned)))
                    if any(not _stat.S_ISREG(entry.lstat().st_mode) for entry in entries):
                        _retain_output()
                        return lifecycle.ReceiptError('OUTPUT_SET_MISMATCH','nonregular known output')
                except BaseException as classification:
                    _retain_output()
                    try:classification.add_note('output classification failed; unique invoke originals retained')
                    except BaseException:pass
                    return classification
                return None

            def _preserve_known(exc):
                if OBSERVER:
                    try:
                        # known名称也不能让非普通/过大对象绕过安全分类去读任意内容。
                        import stat as _stat
                        native=out/expected
                        if native.exists() or native.is_symlink():
                            metadata=native.lstat()
                            lifecycle.require(_stat.S_ISREG(metadata.st_mode),'UNSAFE_FILE',expected)
                            lifecycle.require(metadata.st_size<=lifecycle.MAX_BYTES,'OVERSIZE_FILE',expected)
                        OBSERVER.preserve_partial(out,output,expected,key,mode,exc)
                    except BaseException as preserve:
                        OBSERVER.retain_temp=True
                        try:exc.add_note('secondary partial preservation: '+repr(preserve))
                        except BaseException:pass
                else:
                    try:
                        directory=output/'partial-evidence'/((key or 'collection')+'-'+uuid.uuid4().hex)
                        directory.mkdir(parents=True,exist_ok=False)
                        for name,target in ((expected,'native-output.bin'),(life,'lifecycle-output.bin')):
                            if (out/name).exists():
                                with (directory/target).open('xb') as stream:stream.write(lifecycle.read_regular(out/name))
                        lifecycle.write_receipt(directory/'index.json',dict(primary_error=repr(exc),request=request,complete=False))
                    except BaseException as preserve:
                        temporary.retain_temp=True
                        try:exc.add_note('secondary partial preservation: '+repr(preserve))
                        except BaseException:pass

            try:
                with saved_request.open('xb') as stream:stream.write(request_bytes)
                try:
                    if OBSERVER:
                        cids=output/'owned-cids'; cids.mkdir(exist_ok=True)
                        cidfile=cids/(container_name+'.cid')
                        command.remove('--rm')
                        command[1:1]=['--cidfile',str(cidfile)]
                        OBSERVER.start(container_name,cidfile,key,profile,image_id=image_id)
                    with (output/((key or 'collection')+'.log')).open('w') as log:
                        if OBSERVER:
                            completed=OBSERVER.run(['docker',*command],key or 'collection',stdout=log,stderr=subprocess.STDOUT,timeout=seconds)
                        else:
                            completed=subprocess.run(['docker',*command],stdout=log,stderr=subprocess.STDOUT,timeout=seconds)
                except BaseException as exc:primary=exc
                finally:
                    try:
                        if OBSERVER and cidfile is not None:
                            OBSERVER.cleanup(container_name,cidfile)
                            cleanup=OBSERVER.cleanup_facts.get(container_name)
                        elif not OBSERVER:
                            subprocess.run(['docker','rm','-f',container_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
                    except BaseException as exc:
                        if primary is None:primary=exc
                        else:
                            try:primary.add_note('secondary invoke cleanup: '+repr(exc))
                            except BaseException:pass
                classification=_classify_outputs()
                if classification is not None:
                    if primary is None:primary=classification
                    else:
                        try:primary.add_note('secondary output classification: '+repr(classification))
                        except BaseException:pass
                if primary is not None:raise primary
                native_bytes=lifecycle.read_regular(out/expected);receipt_bytes=lifecycle.read_regular(out/life)
                receipt=lifecycle.decode_json(receipt_bytes)
                lifecycle.validate_receipt(receipt,request,native_bytes)
                if completed is None or type(completed.returncode)is not int or completed.returncode!=receipt['supervisor_exit']:
                    raise lifecycle.ReceiptError('WORKER_WAIT_INCOMPLETE','outer/supervisor exit')
                shutil.copyfile(out/expected,output/expected);shutil.copyfile(out/life,output/life)
                lifecycle.write_receipt(output/lifecycle.host_filename(mode,key),
                    lifecycle.make_host_binding(request_bytes,receipt_bytes,native_bytes,cleanup))
                # 已读回验证所有producer字节；default --rm没有owned证明，不能升级CID资格。
                lifecycle.verify_saved_lifecycle(output,lifecycle.decode_json(frozen_plan_bytes),mode,key,profile,require_owned=OBSERVER is not None)
                return completed.returncode
            except BaseException as exc:
                classification=_classify_outputs()
                if classification is not None and classification is not exc:
                    try:exc.add_note('secondary output classification: '+repr(classification))
                    except BaseException:pass
                _preserve_known(exc)
                raise
            finally:
                import sys as _sys
                active_error=_sys.exc_info()[1]
                classification=_classify_outputs()
                if classification is not None:
                    if active_error is None:
                        _preserve_known(classification)
                        raise classification
                    try:active_error.add_note('final output classification: '+repr(classification))
                    except BaseException:pass
                if not (OBSERVER.retain_temp if OBSERVER else temporary.retain_temp):
                    try:lifecycle.release_control(control)
                    except BaseException as release:
                        if OBSERVER:OBSERVER.retain_temp=True
                        else:temporary.retain_temp=True
                        # release自身在except里，不以它覆盖尚在传播的原异常。
                        if active_error is not None:active_error.add_note('control release failed: '+repr(release))
                        else:raise
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
        frozen_plan_bytes=json.dumps(plan).encode()
        if args.collect_only:
            print(json.dumps({'mode':plan['mode'],'count':plan['count'],'batches':len(plan['batches']),'image_id':image_id})); return
        batches=[b for b in plan['batches'] if not args.batch or b['key']==args.batch]
        if not batches: raise ValueError('no selected batches')
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes=list(pool.map(lambda b:invoke('run',b['key'],b['profile']),batches))
        print(json.dumps({'mode':plan['mode'],'count':sum(len(b['ids']) for b in batches),'batches':len(batches),'failed_batches':sum(bool(c) for c in codes)}))
        failures=[]
        for batch in batches:
            file=output/(batch['key']+'.json')
            if file.exists():
                report=json.loads(file.read_text())
                failures.extend({'id':item['id'],'reason':item['traceback'].splitlines()[-1][:240]} for item in report['failures']+report['errors'])
        if failures: print(json.dumps({'failure_count':len(failures),'first_failures':failures[:10]},ensure_ascii=False))
        if any(codes): raise SystemExit(1)


if __name__=='__main__': main()
