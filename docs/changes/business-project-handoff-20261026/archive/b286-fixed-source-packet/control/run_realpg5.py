"""Prepared only. Exact original RealPGTests5, result observation after original cleanup."""
import ast
import stat
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest

CONTROL=Path('/control');SOURCE=Path('/source');OUTPUT=Path('/output')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def load(name):
    path=CONTROL/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024*1024:
        raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: control file')
    return json.loads(path.read_bytes())
def obj(kind,raw):return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def tree(entries):
    children={}
    for name,entry in entries.items():
        first,sep,rest=name.partition('/')
        if sep:children.setdefault(first,{})[rest]=entry
        else:children[first]=(entry['mode'],entry['blob'])
    raw=b''
    for name,value in sorted(children.items(),key=lambda pair:(pair[0]+('/' if isinstance(pair[1],dict) else '')).encode()):
        mode,oid=('40000',tree(value)) if isinstance(value,dict) else value
        raw+=mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(oid)
    return obj('tree',raw)
def write(name,value):
    with (OUTPUT/name).open('x') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def _protocol_admission(manifest, request, producer_path, gate_path):
    """Read/hash/parse only; no business imports, eval, child processes or v1 fallback."""
    def regular(path):
        path=Path(path)
        before=path.lstat()
        if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size>16*1024*1024:
            raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: unsafe or oversized source')
        raw=path.read_bytes();after=path.lstat()
        if path.is_symlink() or not stat.S_ISREG(after.st_mode) or len(raw)>16*1024*1024 or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: source changed while read')
        return raw
    try:
        if type(manifest) is not dict or type(request) is not dict:
            raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: input shape')
        producer=regular(producer_path);consumer=regular(gate_path)
        pins=(manifest['source_closure']['tools/test_impact/pg_lifecycle.py']['sha256'],manifest['control_payload_sha256']['component_evidence_gate.py'])
        for raw,pin in zip((producer,consumer),pins):
            if type(pin) is not str or not re.fullmatch('[0-9a-f]{64}',pin) or hashlib.sha256(raw).hexdigest()!=pin:
                raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: source hash')
        versions=[]
        for raw in (producer,consumer):
            parsed=ast.parse(raw)
            writes=[n for n in ast.walk(parsed) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id=='SCHEMA']
            declarations=[n for n in parsed.body if isinstance(n,(ast.Assign,ast.AnnAssign)) and
                          ((isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='SCHEMA') or
                           (isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='SCHEMA'))]
            if len(writes)>1 or len(declarations)>1 or writes and not declarations:
                raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: ambiguous SCHEMA')
            node=declarations[0].value if declarations else None
            versions.append(node.value if isinstance(node,ast.Constant) else None)
    except (OSError,KeyError,TypeError,SyntaxError,UnicodeError,ValueError) as exc:
        raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: '+str(exc)) from exc
    admitted=(manifest.get('lifecycle_schema'),request.get('schema_version'),versions[0],versions[1])
    for label,value in zip(('manifest','request','producer','consumer'),admitted):
        if type(value) is not str or value!='pg-lifecycle-v2':
            raise ValueError('LIFECYCLE_VERSION_MISMATCH: '+label)
    return dict(lifecycle_schema='pg-lifecycle-v2',producer_sha256=hashlib.sha256(producer).hexdigest(),consumer_sha256=hashlib.sha256(consumer).hexdigest())

def main():
    manifest=load('execution-manifest.json');binding=load('closure-binding.json');plan=load('plan.json')
    request=load('qualification-request.json')
    try:
        for name,pin in manifest['control_payload_sha256'].items():
            file=CONTROL/name
            assert type(name) is str and '/' not in name and name not in ('.','..')
            assert file.is_file() and not file.is_symlink() and file.stat().st_size<=16*1024*1024 and sha(file.read_bytes())==pin
        assert manifest['head']==binding['test_sha']==plan['test_sha']
        assert manifest['tree']==binding['test_tree']==plan['test_tree']
        assert plan['image_id']==manifest['image_id']
        raw=base64.b64decode(binding['commit_base64'],validate=True)
        assert (CONTROL/'test-commit.raw').read_bytes()==raw
        assert obj('commit',raw)==binding['test_sha'] and raw.split(b'\n',1)[0]==b'tree '+binding['test_tree'].encode()
        assert tree(binding['all_tree_entries'])==binding['test_tree']
        actual={str(f.relative_to(SOURCE)) for f in SOURCE.rglob('*') if f.is_file() or f.is_symlink()}
        assert actual==set(binding['closure_files'])==set(manifest['source_closure'])
        for name,pin in binding['closure_files'].items():
            file=SOURCE/name
            assert type(name) is str and not file.is_symlink() and file.is_file() and file.resolve().is_relative_to(SOURCE) and file.stat().st_size<=16*1024*1024
            data=file.read_bytes()
            assert sha(data)==pin['sha256'] and len(data)==pin['size'] and obj('blob',data)==pin['blob']
            assert binding['all_tree_entries'][name]==dict(mode=pin['mode'],blob=pin['blob'])
            assert manifest['source_closure'][name]==pin
    except (AssertionError,OSError,KeyError,TypeError,ValueError) as exc:
        raise ValueError('PROTOCOL_ADMISSION_SOURCE_INVALID: closure/control binding') from exc
    _protocol_admission(manifest,request,SOURCE/'tools/test_impact/pg_lifecycle.py',CONTROL/'component_evidence_gate.py')
    # No business module, test instance, Session or child is created before admission.
    assert sys.platform=='linux' and os.getuid()==os.getgid()==10001
    assert not Path('/var/run/docker.sock').exists()
    assert os.environ['UMANEWS_REAL_PG_QUALIFICATION']=='1'
    assert os.environ['UMANEWS_PG_QUALIFICATION_PLAN']=='/control/plan.json'
    sys.path.insert(0,str(CONTROL))
    from component_evidence_gate import apply_component_gate
    sys.path.insert(0,str(SOURCE))
    producer=importlib.import_module('tools.test_impact.pg_lifecycle')
    batch=next(b for b in plan['batches'] if b['profile']!='python')
    generated=producer.make_request(plan,'run',batch['key'],batch['profile'],'a'*32)
    producer.validate_request(request,plan,'run',batch['key'],batch['profile'])
    assert type(generated.get('schema_version')) is str and generated['schema_version']=='pg-lifecycle-v2'
    assert producer.canonical(generated)==producer.canonical(request)
    for name in ('initdb','postgres','pg_ctl','pg_isready'):
        assert shutil.which(name), 'MISSING_BINARY:'+name
    Path('/tmp/home').mkdir(exist_ok=True)
    write('container-preflight.json',dict(uid=os.getuid(),gid=os.getgid(),pid=os.getpid(),pid_namespace=os.readlink('/proc/self/ns/pid'),python=sys.executable,python_version=sys.version,argv=sys.argv,sys_path_before_source=sys.path,source_binding_scope=binding['scope'],image_id_claim=manifest['image_id'],container_image_identity='host inspect is authority',started_monotonic=time.monotonic()))
    sys.path.insert(0,str(SOURCE))
    module=importlib.import_module('tools.test_impact.test_pg_lifecycle')
    cls=module.RealPGTests
    actual_names={name for name in cls.__dict__ if name.startswith('test_')}
    expected=manifest['expected_ids'];prefix=module.__name__+'.RealPGTests.'
    assert len(expected)==5 and len(set(expected))==5
    assert actual_names=={ident.removeprefix(prefix) for ident in expected} and all(ident.startswith(prefix) for ident in expected)
    assert getattr(cls,'__unittest_skip__',False) is False
    rows=[];evidence_errors=[]
    class ObservedResult(unittest.TextTestResult):
        def startTest(self,test):
            self.current_status='STARTED';super().startTest(test)
        def addSuccess(self,test):self.current_status='ok';super().addSuccess(test)
        def addFailure(self,test,error):self.current_status='FAIL';super().addFailure(test,error)
        def addError(self,test,error):self.current_status='ERROR';super().addError(test,error)
        def addSkip(self,test,reason):self.current_status='SKIP';super().addSkip(test,reason)
        def stopTest(self,test):
            # Original TestCase already ran tearDown and registered cleanups. Observe remaining Session memory only.
            try:
                session=getattr(test,'session',None)
                value=dict(canonical_id=test.id(),unittest_status=self.current_status,observation_phase='after_original_test_cleanups',receipt=None,actual_popen_handles=[],supervisor_python=sys.executable)
                if session is not None:
                    value.update(request_schema_version=session.request.get('schema_version'),receipt=session.receipt,session_closed=session.closed,data_dir_original=str(session.data_dir),data_dir_exists_after_cleanup=session.data_dir.exists(),log_dir_original=str(session.log_dir),log_dir_exists_after_cleanup=session.log_dir.exists())
                    value['actual_popen_handles']=[dict(name=name,pid=process.pid,argv=process.args,returncode=process.returncode,popen_instance=isinstance(process,subprocess.Popen)) for name,process in session.processes.items()]
                apply_component_gate(value,evidence_errors,self.stop)
                rows.append(value)
                with (OUTPUT/'methods.jsonl').open('a') as stream:
                    stream.write(json.dumps(value,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
            except BaseException as exc:
                evidence_errors.append('OBSERVATION_ERROR:'+repr(exc));self.stop()
            finally:super().stopTest(test)
    suite=unittest.defaultTestLoader.loadTestsFromNames(expected)
    assert suite.countTestCases()==5
    result=unittest.TextTestRunner(verbosity=2,failfast=True,resultclass=ObservedResult).run(suite)
    good=result.wasSuccessful() and result.testsRun==5 and len(rows)==5 and all(row['unittest_status']=='ok' for row in rows) and not evidence_errors
    write('container-summary.json',dict(schema='realpg5-component-result-v1',lifecycle_schema=producer.SCHEMA,status='COMPONENT_5_METHODS_PASS_PENDING_HOST_JOIN_AND_REVIEW' if good else 'FIRST_FAILURE_OR_INCOMPLETE_STOPPED',expected_ids=expected,observed_ids=[x['canonical_id'] for x in rows],tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),evidence_errors=evidence_errors,standard_lifecycle_complete='NOT_CLAIMED: source methods call components, not Session.execute',formal_full='NOT_READY',B249='UNKNOWN_PRESERVED'))
    return 0 if good else 74

if __name__ == '__main__':
    raise SystemExit(main())
