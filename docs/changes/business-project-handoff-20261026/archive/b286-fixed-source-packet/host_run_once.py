"""Prepared, NOT RUN. Future exact ROOT card binds manifest SHA and a new owned output path."""
from pathlib import Path
import hashlib,json,os,re,signal,subprocess,sys,time
import importlib.util

PACKAGE=Path(__file__).resolve().parent
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()

def _owned_cleanup_absent(rm,absent,cid,out,err):
    """One exact owned CID, numeric waits, explicit false timeouts, one raw absence line."""
    if type(rm) is not dict or type(absent) is not dict or type(cid) is not str or re.fullmatch('[0-9a-f]{64}',cid) is None:return False
    if type(rm.get('returncode')) is not int or rm['returncode']!=0 or rm.get('timed_out') is not False:return False
    if type(absent.get('returncode')) is not int or absent['returncode']!=1 or absent.get('timed_out') is not False:return False
    if type(out) is not bytes or out.strip() not in (b'',b'[]') or type(err) is not bytes:return False
    match=re.fullmatch(rb'(?i:error: no such object: )([0-9a-f]{64})(?:\r?\n)?',err)
    return match is not None and match.group(1)==cid.encode('ascii')

def main():
    assert len(sys.argv)==3,'usage: host_run_once.py MANIFEST_SHA256 NEW_ABSOLUTE_OUTPUT_DIR'
    manifest_path=PACKAGE/'control/execution-manifest.json'
    try:
        assert manifest_path.is_file() and not manifest_path.is_symlink() and manifest_path.stat().st_size<=16*1024*1024 and sha(manifest_path)==sys.argv[1]
        manifest=json.loads(manifest_path.read_text());index=json.loads((PACKAGE/'index.json').read_text())
        expected={x['path'] for x in index['members']}|{'index.json'}
        assert {str(f.relative_to(PACKAGE)) for f in PACKAGE.rglob('*') if f.is_file()}==expected
        for pin in index['members']:
            file=PACKAGE/pin['path']
            assert file.resolve().is_relative_to(PACKAGE) and file.is_file() and not file.is_symlink() and file.stat().st_size<=16*1024*1024
            assert sha(file)==pin['sha256'] and file.stat().st_size==pin['size']
        control=PACKAGE/'control';source=PACKAGE/'source'
        for name,pin in manifest['control_payload_sha256'].items():
            file=control/name
            assert type(name) is str and '/' not in name and name not in ('.','..') and file.is_file() and not file.is_symlink() and file.stat().st_size<=16*1024*1024 and sha(file)==pin
        assert 'run_realpg5.py' in manifest['control_payload_sha256']
        # Only the hash-bound runner library is loaded; its canonical main guard remains false.
        spec=importlib.util.spec_from_file_location('trusted_realpg5_admission',PACKAGE/'control/run_realpg5.py')
        trusted=importlib.util.module_from_spec(spec);spec.loader.exec_module(trusted)
        _protocol_admission=trusted._protocol_admission
        control=PACKAGE/'control';source=PACKAGE/'source'
        request=json.loads((control/'qualification-request.json').read_bytes())
        binding=json.loads((control/'closure-binding.json').read_bytes());plan=json.loads((control/'plan.json').read_bytes())
        assert manifest['head']==binding['test_sha']==plan['test_sha'] and manifest['tree']==binding['test_tree']==plan['test_tree'] and plan['image_id']==manifest['image_id']
        raw=(control/'test-commit.raw').read_bytes()
        assert trusted.obj('commit',raw)==binding['test_sha'] and raw.split(b'\n',1)[0]==b'tree '+binding['test_tree'].encode()
        assert trusted.tree(binding['all_tree_entries'])==binding['test_tree']
        actual={str(f.relative_to(source)) for f in source.rglob('*') if f.is_file() or f.is_symlink()}
        assert actual==set(binding['closure_files'])==set(manifest['source_closure'])
        for name,pin in binding['closure_files'].items():
            file=source/name
            assert file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(source) and file.stat().st_size<=16*1024*1024
            raw=file.read_bytes()
            assert sha(file)==pin['sha256'] and len(raw)==pin['size'] and trusted.obj('blob',raw)==pin['blob']
            assert binding['all_tree_entries'][name]==dict(mode=pin['mode'],blob=pin['blob']) and manifest['source_closure'][name]==pin
    except (AssertionError,OSError,KeyError,TypeError,ValueError) as exc:
        raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: package/closure/control binding') from exc
    _protocol_admission(manifest,request,source/'tools/test_impact/pg_lifecycle.py',control/'component_evidence_gate.py')
    output=Path(sys.argv[2]);assert str(output)==manifest['planned_output_dir'] and output.is_absolute() and not output.exists() and output.parent.is_dir()
    output.mkdir(mode=0o700);artifacts=output/'container-output';artifacts.mkdir(mode=0o777);artifacts.chmod(0o777)
    started=time.monotonic();end=started+600
    env=dict(PATH='/opt/homebrew/bin:/usr/bin:/bin',HOME='/Users/mentianlu',LANG='C',LC_ALL='C')
    docker=['docker','--context',manifest['context']]
    calls=[]
    def call(label,args,limit):
        remaining=end-time.monotonic()
        if remaining<=0:raise TimeoutError('outer 600s deadline')
        proc=subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        timeout=False
        try:stdout,stderr=proc.communicate(timeout=min(limit,remaining))
        except subprocess.TimeoutExpired:
            timeout=True;os.killpg(proc.pid,signal.SIGKILL)
            stdout,stderr=proc.communicate(timeout=max(.01,min(2,end-time.monotonic())))
        (output/(label+'.stdout.raw')).write_bytes(stdout);(output/(label+'.stderr.raw')).write_bytes(stderr)
        row=dict(label=label,command=args,returncode=proc.returncode,timed_out=timeout,host_pid=proc.pid,numeric_wait_reaped=True,elapsed_from_outer_start=time.monotonic()-started)
        calls.append(row);(output/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')
        return row,stdout,stderr
    primary=None;cid=None;ownership=False;joined=False;cleanup=None;run_record=None;cleanup_end=None
    try:
        c,raw,_=call('pre-context',['docker','context','inspect',manifest['context']],10)
        assert c['returncode']==0 and not c['timed_out']
        context=json.loads(raw)[0];assert context['Name']==manifest['context'] and context['Endpoints']['docker']['Host']=='unix:///Users/mentianlu/.colima/umanews-impact-ci/docker.sock'
        c,raw,_=call('pre-image',docker+['image','inspect',manifest['image_id']],10)
        image=json.loads(raw)[0];assert c['returncode']==0 and image['Id']==manifest['image_id'] and image['Config']['User']=='10001:10001'
        args=docker+['run','--pull','never','--platform','linux/amd64','--name',manifest['container_name'],'--cidfile',str(output/'owned.cid'),'--label','umanews.realpg5.owner='+manifest['run_nonce'],'--user','10001:10001','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','256','--memory','2g','--cpus','2','--read-only','--tmpfs',manifest['resources']['tmpfs'],'--mount','type=bind,src='+str(PACKAGE/'source')+',dst=/source,readonly','--mount','type=bind,src='+str(PACKAGE/'control')+',dst=/control,readonly','--mount','type=bind,src='+str(artifacts)+',dst=/output','--workdir','/source','--entrypoint','/venv/bin/python']
        for name,value in manifest['container_environment'].items():args+=['--env',name+'='+value]
        args += [manifest['image_id'],'-I','-S','-B','-v','/control/run_realpg5.py']
        (output/'execution-start.json').write_text(json.dumps(dict(manifest_sha256=sys.argv[1],package_index_sha256=sha(PACKAGE/'index.json'),command=args,environment_exact=env,outer_seconds=600,foreground_cap=540,cleanup_cap=40,evidence_reserve=20,source_scope='four-file Git-proven closure, not full tree physical checkout'),indent=2)+'\n')
        run_record,_,_=call('container-run',args,min(540,max(.01,end-time.monotonic()-60)))
        if run_record['timed_out'] or run_record['returncode']!=0:primary='CONTAINER_RUN_FAILED_OR_TIMEOUT'
    except BaseException as exc:primary='PRIMARY:'+repr(exc)
    finally:
        cleanup_end=min(end-20,time.monotonic()+40)
        def cleanup_limit(cap):
            left=cleanup_end-time.monotonic()
            if left<=0:raise TimeoutError('outer cleanup deadline; no budget extension')
            return min(cap,left)
        try:
            cidpath=output/'owned.cid'
            if cidpath.is_file() and not cidpath.is_symlink():
                candidate=cidpath.read_text().strip();assert re.fullmatch('[0-9a-f]{64}',candidate);cid=candidate
                c,raw,_=call('post-inspect',docker+['inspect',cid],cleanup_limit(8))
                assert c['returncode']==0
                state=json.loads(raw)[0]
                ownership=state['Id']==cid and state['Image']==manifest['image_id'] and state['Config']['Labels'].get('umanews.realpg5.owner')==manifest['run_nonce'] and state['Name']=='/'+manifest['container_name']
                assert ownership,'CID ownership mismatch: no deletion authorized'
                mounts={m['Destination']:m for m in state['Mounts']}
                isolation=(state['Config']['User']=='10001:10001' and state['HostConfig']['NetworkMode']=='none' and state['HostConfig']['ReadonlyRootfs'] is True and state['HostConfig']['PidsLimit']==256 and state['HostConfig']['Memory']==2*1024**3 and state['HostConfig'].get('Tmpfs')=={'/tmp':'rw,exec,size=1g,uid=10001,gid=10001,mode=0700'} and state['HostConfig']['NanoCpus']==2*10**9 and 'ALL' in state['HostConfig']['CapDrop'] and any(v.startswith('no-new-privileges') for v in state['HostConfig']['SecurityOpt']) and set(mounts)=={'/source','/control','/output'} and mounts['/source']['RW'] is False and mounts['/control']['RW'] is False and mounts['/output']['RW'] is True and mounts['/source']['Source']==str(PACKAGE/'source') and mounts['/control']['Source']==str(PACKAGE/'control') and mounts['/output']['Source']==str(artifacts))
                wait,raw,_=call('docker-wait',docker+['wait',cid],cleanup_limit(5))
                wait_code=int(raw.strip()) if wait['returncode']==0 and not wait['timed_out'] else None
                joined=(isolation and not state['State']['Running'] and state['State']['Pid']==0 and state['State']['OOMKilled'] is False and type(wait_code)is int and run_record is not None and not run_record['timed_out'] and state['State']['ExitCode']==wait_code==run_record['returncode'])
                (output/'cid-outer-join.json').write_text(json.dumps(dict(cid=cid,ownership=ownership,isolation=bool(isolation),inspect_state=state['State'],docker_wait_numeric=wait_code,run_cli_numeric=None if run_record is None else run_record['returncode'],joined=bool(joined),scope='container exit, not replacement for direct postmaster/stop Popen waits'),indent=2)+'\n')
            else:cleanup='UNKNOWN_CID_MISSING_NO_NAME_ONLY_DELETE'
        except BaseException as exc:
            if primary is None:primary='OUTER_JOIN_OR_CLEANUP:'+repr(exc)
            else:primary+='; secondary:'+repr(exc)
        if ownership:
            # Ownership is independently established before deletion; cleanup still runs if later joins fail.
            try:
                rm,_,_=call('owned-rm',docker+['rm','-f',cid],cleanup_limit(20))
                absent,out,err=call('owned-absence',docker+['inspect',cid],cleanup_limit(5))
                cleanup=_owned_cleanup_absent(rm,absent,cid,out,err)
            except BaseException as exc:
                cleanup='UNKNOWN:'+repr(exc)
                if primary is None:primary='OUTER_CLEANUP:'+repr(exc)
                else:primary+='; cleanup:'+repr(exc)
    # Everything stays in this unique output directory on failure or success. No artifact deletion here.
    summary_path=artifacts/'container-summary.json'
    summary=json.loads(summary_path.read_text()) if summary_path.is_file() and not summary_path.is_symlink() else None
    good=(primary is None and joined and cleanup is True and summary is not None and summary.get('status')=='COMPONENT_5_METHODS_PASS_PENDING_HOST_JOIN_AND_REVIEW')
    result=dict(lifecycle_schema=request['schema_version'],status='FIRST_COMPONENT5_RESULT_PENDING_SAME_R' if good else 'FIRST_FAILURE_OR_UNKNOWN_STOPPED_NO_RERUN',primary=primary,cid=cid,ownership=ownership,outer_join=bool(joined),owned_cleanup=cleanup,container_summary=summary,elapsed_seconds=time.monotonic()-started,one_invocation=True,PG_qualification='PENDING_REVIEW_OR_UNKNOWN',B249='UNKNOWN_PRESERVED',formal_full='NOT_READY',root_image='NOT_CLOSED')
    (output/'host-result.json').write_text(json.dumps(result,indent=2)+'\n')
    inventory=[]
    for file in sorted(output.rglob('*')):
        if file.is_file() and not file.is_symlink():inventory.append(dict(path=str(file.relative_to(output)),size=file.stat().st_size,sha256=sha(file)))
    (output/'result-index.json').write_text(json.dumps(dict(self_excluded='result-index.json',members=inventory),indent=2)+'\n')
    return 0 if good else 75

if __name__ == '__main__':
    raise SystemExit(main())
