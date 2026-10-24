"""固定非root worker 的真实PG直接子进程监督及收据；不认证独立full/能力资格。

同UID的worker/可写output不是防伪安全域。来源是受审控制及原source binding，
收据只提供该机制的数值证据，不能回填历史UNKNOWN或单独签full/delivery。
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from tools.test_impact.core import digest
from tools.test_impact.source_binding import validate_source_plan, verify_source_binding

SCHEMA = 'pg-lifecycle-v1'
MAX_BYTES = 16 * 1024 * 1024
LOG_LIMIT = 512 * 1024
REQUEST_FIELDS = frozenset(('schema_version','nonce','mode','key','profile','test_sha','test_tree',
    'run_id','run_attempt','image_id','parent_full_digest','input_plan_digest',
    'invoke_seconds','inner_seconds','cleanup_seconds'))
RECEIPT_FIELDS = REQUEST_FIELDS | frozenset(('pg_required','namespace','supervisor_pid','uid','gid',
    'worker','postmaster','pg_stop','tools','orphans','logs','primary_error','secondary_errors',
    'signal_events','last_phase','complete','supervisor_exit','native_raw_sha256','output_plan_digest'))


class ReceiptError(ValueError):
    def __init__(self, code, detail=''):
        self.code = code
        super().__init__(code + (': ' + detail if detail else ''))


def require(condition, code, detail=''):
    if not condition:
        raise ReceiptError(code, detail)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def raw_hash(data):
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'JSON_DUPLICATE_KEY', key)
        value[key] = item
    return value


def decode_json(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ReceiptError('JSON_NONFINITE', value)))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptError('JSON_INVALID', str(exc)) from exc


def read_regular(path):
    path = Path(path)
    try:
        require(stat.S_ISREG(path.lstat().st_mode), 'UNSAFE_FILE', str(path))
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode) and not path.is_symlink(), 'UNSAFE_FILE', str(path))
            data = stream.read(MAX_BYTES + 1)
            require(len(data) <= MAX_BYTES, 'OVERSIZE_FILE', str(path))
            return data
    except OSError as exc:
        raise ReceiptError('FILE_UNAVAILABLE', str(path)) from exc


def read_json(path):
    return decode_json(read_regular(path))


def write_receipt(path, value):
    path = Path(path)
    data = (canonical(value) + '\n').encode()
    require(len(data) <= MAX_BYTES, 'OVERSIZE_FILE')
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def _stem(mode, key):
    require(mode in ('collect','run'), 'REQUEST_SCHEMA', 'mode')
    require(type(key) is str and (key == '' if mode == 'collect' else re.fullmatch(r'batch-[0-9]{3,}', key)),
            'REQUEST_SCHEMA', 'batch key')
    return 'collection' if mode == 'collect' else key


def native_filename(mode, key):
    return 'execution-plan.json' if _stem(mode,key) == 'collection' else key + '.json'


def receipt_filename(mode, key):
    return 'lifecycle-' + _stem(mode,key) + '.json'


def request_filename(mode, key):
    return 'lifecycle-request-' + _stem(mode,key) + '.json'


def host_filename(mode, key):
    return 'lifecycle-host-' + _stem(mode,key) + '.json'


def make_request(plan, mode, key, profile, nonce):
    validate_source_plan(plan)
    _stem(mode,key)
    profile = 'django' if mode == 'collect' else profile
    require(profile in ('python','django','release-postgres'), 'REQUEST_SCHEMA', 'profile')
    if mode == 'run':
        matches = [b for b in plan.get('batches', []) if b['key'] == key]
        require(len(matches) == 1 and matches[0]['profile'] == profile, 'REQUEST_IDENTITY_MISMATCH', 'batch/profile')
    require(type(nonce) is str and re.fullmatch('[0-9a-f]{32}',nonce), 'REQUEST_SCHEMA', 'nonce')
    require(type(plan.get('image_id')) is str and re.fullmatch('sha256:[0-9a-f]{64}',plan['image_id']), 'REQUEST_SCHEMA', 'image')
    require(all(k in plan and type(plan[k]) in (str,int) and bool(plan[k]) for k in ('run_id','run_attempt')), 'REQUEST_SCHEMA', 'run identity')
    parent_digest=plan.get('parent_full_digest')
    require(parent_digest is None or (type(parent_digest)is str and re.fullmatch('[0-9a-f]{64}',parent_digest)), 'REQUEST_SCHEMA', 'parent digest')
    seconds = 2100 if profile == 'release-postgres' else 600
    return dict(schema_version=SCHEMA,nonce=nonce,mode=mode,key=key,profile=profile,
                test_sha=plan['test_sha'],test_tree=plan['test_tree'],run_id=plan['run_id'],run_attempt=plan['run_attempt'],
                image_id=plan['image_id'],parent_full_digest=plan.get('parent_full_digest'),input_plan_digest=digest(plan),
                invoke_seconds=seconds,inner_seconds=seconds-30,cleanup_seconds=30)


def validate_request(request, plan, mode, key, profile):
    require(type(request) is dict and set(request) == REQUEST_FIELDS, 'REQUEST_SCHEMA')
    expected = make_request(plan,mode,key,profile,request['nonce'])
    require(request['input_plan_digest'] == expected['input_plan_digest'], 'INPUT_PLAN_DIGEST_MISMATCH')
    require(canonical(request) == canonical(expected), 'REQUEST_IDENTITY_MISMATCH')
    return request


def prepare_control(parent, plan_bytes, binding_bytes, commit_bytes, mode, key, profile, nonce=None):
    """每invoke四文件按值冻结；不读取可替换的共享control请求或plan路径。"""
    request = make_request(decode_json(plan_bytes),mode,key,profile,uuid.uuid4().hex if nonce is None else nonce)
    directory = Path(parent)/'invocations'; directory.mkdir(exist_ok=True)
    owned = Path(tempfile.mkdtemp(prefix='invoke-',dir=directory))
    control = owned/'control'; control.mkdir()
    payloads = {'plan.json':plan_bytes,'source-binding.json':binding_bytes,'test-commit.raw':commit_bytes,
                'pg-lifecycle-request.json':(canonical(request)+'\n').encode()}
    for name, data in payloads.items():
        with (control/name).open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        (control/name).chmod(0o444)
    control.chmod(0o555)
    return control, request


def release_control(control):
    control = Path(control)
    control.chmod(0o700)
    shutil.rmtree(control.parent)


def step_record(status='NOT_STARTED'):
    return dict(status=status,started=False,pid=None,ppid=None,argv=[],returncode=None,reaped=False,timed_out=False,signals=[])


def new_receipt(request):
    required = request['mode'] == 'collect' or request['profile'] != 'python'
    try: namespace = os.readlink('/proc/self/ns/pid')
    except OSError: namespace = 'host-process-not-qualified-container'
    return dict(copy.deepcopy(request),pg_required=required,namespace=namespace,supervisor_pid=os.getpid(),uid=os.getuid(),gid=os.getgid(),
                worker=step_record(),postmaster=step_record('NOT_STARTED' if required else 'NOT_APPLICABLE'),
                pg_stop=step_record('NOT_STARTED' if required else 'NOT_APPLICABLE'),tools=[],orphans=[],logs={},
                primary_error=None,secondary_errors=[],signal_events=[],last_phase='source-verified',complete=False,
                supervisor_exit=None,native_raw_sha256=None,output_plan_digest=None)


def _numeric(step, parent, zero=False):
    return (type(step) is dict and step.get('started') is True and type(step.get('pid')) is int and step['pid'] > 0
            and step.get('ppid') == parent and type(step.get('ppid')) is int and step.get('reaped') is True
            and type(step.get('returncode')) is int and (not zero or step['returncode'] == 0)
            and step.get('timed_out') is False and step.get('status') == 'REAPED')


def validate_receipt(receipt, request, native_bytes):
    require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS, 'RECEIPT_SCHEMA')
    require(receipt['input_plan_digest'] == request['input_plan_digest'], 'INPUT_PLAN_DIGEST_MISMATCH')
    require(receipt['nonce'] == request['nonce'], 'NONCE_MISMATCH')
    require(canonical({k:receipt[k] for k in REQUEST_FIELDS}) == canonical(request), 'RECEIPT_IDENTITY_MISMATCH')
    required = request['mode'] == 'collect' or request['profile'] != 'python'
    require(receipt['pg_required'] is required and receipt['complete'] is True and receipt['secondary_errors'] == []
            and receipt['signal_events'] == [] and receipt['uid'] == 10001 and receipt['gid'] == 10001,
            'PG_NUMERIC_INCOMPLETE')
    parent = receipt['supervisor_pid']
    require(type(parent) is int and parent > 0 and _numeric(receipt['worker'],parent), 'WORKER_WAIT_INCOMPLETE')
    worker_exit = receipt['worker']['returncode']
    require(receipt['primary_error'] is None or (worker_exit != 0 and receipt['primary_error'] == 'WORKER_EXIT:'+str(worker_exit)), 'PG_NUMERIC_INCOMPLETE')
    require(type(receipt['supervisor_exit']) is int and receipt['supervisor_exit'] == (worker_exit if worker_exit >= 0 else 128-worker_exit),
            'WORKER_WAIT_INCOMPLETE')
    if required:
        require(_numeric(receipt['pg_stop'],parent,True) and _numeric(receipt['postmaster'],parent,True), 'PG_NUMERIC_INCOMPLETE')
    else:
        for name in ('postmaster','pg_stop'):
            step=receipt[name]
            require(step == step_record('NOT_APPLICABLE'), 'PG_NUMERIC_INCOMPLETE')
    require(type(receipt['tools']) is list and all(_numeric(t,parent) for t in receipt['tools']), 'PG_NUMERIC_INCOMPLETE')
    require(type(receipt['namespace']) is str and bool(receipt['namespace']), 'RECEIPT_SCHEMA')
    require(receipt['native_raw_sha256'] == raw_hash(native_bytes), 'OUTPUT_HASH_MISMATCH')
    native = decode_json(native_bytes)
    expected_digest = digest(native) if request['mode'] == 'collect' else request['input_plan_digest']
    require(receipt['output_plan_digest'] == expected_digest, 'OUTPUT_HASH_MISMATCH')
    if request['mode'] == 'collect':
        require(all(canonical(native.get(k)) == canonical(request[k]) for k in ('test_sha','test_tree','run_id','run_attempt','image_id')),
                'OUTPUT_HASH_MISMATCH')
    else:
        require(type(native.get('exit_code')) is int and native['exit_code'] == worker_exit, 'WORKER_WAIT_INCOMPLETE')
    total = 0
    require(type(receipt['logs']) is dict, 'RECEIPT_SCHEMA')
    for value in receipt['logs'].values():
        try: data=base64.b64decode(value['base64'],validate=True)
        except (ValueError,KeyError,TypeError) as exc: raise ReceiptError('RECEIPT_SCHEMA','log') from exc
        total += len(data)
        require(type(value['bytes']) is int and value['bytes'] == len(data) and value['sha256'] == raw_hash(data) and total <= LOG_LIMIT, 'RECEIPT_SCHEMA','log integrity')
    return receipt


def make_host_binding(request_bytes, receipt_bytes, native_bytes, cleanup=None):
    state = cleanup.get('exit_state') if cleanup else None
    return dict(schema_version=SCHEMA,ownership='owned-cid' if state else 'unobserved',
                request_sha256=raw_hash(request_bytes),receipt_sha256=raw_hash(receipt_bytes),native_sha256=raw_hash(native_bytes),
                cleanup=cleanup)


def verify_saved_lifecycle(output, plan, mode, key, profile, require_owned=True):
    output=Path(output)
    request_bytes=read_regular(output/request_filename(mode,key))
    request=decode_json(request_bytes);validate_request(request,plan,mode,key,profile)
    receipt_bytes=read_regular(output/receipt_filename(mode,key));receipt=decode_json(receipt_bytes)
    native=read_regular(output/native_filename(mode,key));validate_receipt(receipt,request,native)
    host=read_json(output/host_filename(mode,key))
    require(type(host) is dict and set(host)=={'schema_version','ownership','request_sha256','receipt_sha256','native_sha256','cleanup'}
            and host['schema_version']==SCHEMA and host['request_sha256']==raw_hash(request_bytes)
            and host['receipt_sha256']==raw_hash(receipt_bytes) and host['native_sha256']==raw_hash(native), 'HOST_BINDING_MISMATCH')
    if require_owned:
        require(host['ownership']=='owned-cid', 'OWNED_CID_REQUIRED')
        cleanup=host['cleanup'];state=cleanup.get('exit_state',{}) if type(cleanup)is dict else {}
        require(type(state.get('Id')) is str and re.fullmatch('[0-9a-f]{64}',state['Id']) and state.get('Image')==plan['image_id']
                and cleanup.get('clean') is True and type(cleanup.get('rm_exit'))is int and cleanup.get('rm_exit')==0 and cleanup.get('absent') is True,
                'HOST_BINDING_MISMATCH')
        actual=state.get('State',{})
        require(actual.get('Running') is False and type(actual.get('Pid'))is int and actual.get('Pid')==0 and actual.get('OOMKilled') is False
                and type(actual.get('ExitCode'))is int and actual['ExitCode']==receipt['supervisor_exit'], 'HOST_BINDING_MISMATCH')
    return receipt


class Session:
    """仅持有本session实际Popen；CLI固定生产worker，参数化路径仅供受控组件测试。"""
    def __init__(self, request, plan, output, root=None, data_dir=None):
        self.request=request; self.plan=plan; self.output=Path(output)
        self.root=Path(root) if root is not None else Path.cwd()
        self.data_dir=Path(data_dir) if data_dir is not None else Path('/tmp/pgdata')
        self.receipt=new_receipt(request); self.processes={}; self.records={}; self.cancelled=False
        self.start=time.monotonic(); self.deadline=self.start+request['inner_seconds']
        self.business_deadline=self.deadline-request['cleanup_seconds']; self.startup_deadline=min(self.business_deadline,self.start+60)
        self.log_dir=Path(tempfile.mkdtemp(prefix='pg-lifecycle-')); self.closed=False; self.old_handlers={}

    def error(self, code):
        if self.receipt['primary_error'] is None:self.receipt['primary_error']=code
        else:self.receipt['secondary_errors'].append(code)

    def install_signals(self):
        def cancel(signum, frame):
            self.cancelled=True;self.receipt['signal_events'].append(signum)
        for signum in (signal.SIGTERM,signal.SIGINT):
            self.old_handlers[signum]=signal.getsignal(signum);signal.signal(signum,cancel)

    def _spawn(self, name, argv, worker=False):
        if time.monotonic() >= self.deadline:raise TimeoutError('no process budget before spawn')
        record=step_record()
        record.update(argv=[str(a) for a in argv])
        if name in ('worker','postmaster','pg_stop'):self.receipt[name]=record
        else:record['purpose']=name;self.receipt['tools'].append(record)
        self.records[name]=record
        if worker:
            process=subprocess.Popen(argv,cwd=self.root,start_new_session=True)
        else:
            with (self.log_dir/(name+'.stdout')).open('wb') as out,(self.log_dir/(name+'.stderr')).open('wb') as err:
                process=subprocess.Popen(argv,cwd=self.root,stdout=out,stderr=err,start_new_session=True)
        record.update(pid=process.pid,ppid=os.getpid(),started=True,status='RUNNING');self.processes[name]=process
        return process

    def _finish(self, name, code):
        self.records[name].update(returncode=code,reaped=True,status='REAPED')
        return code

    def _wait(self, name, deadline, honour_cancel=True, watch_pg=False):
        process=self.processes[name]
        while True:
            if honour_cancel and self.cancelled:raise RuntimeError('CANCELLED')
            if watch_pg and 'postmaster' in self.processes and self.processes['postmaster'].poll() is not None:
                self._finish('postmaster',self.processes['postmaster'].wait())
                raise RuntimeError('PG_EARLY_EXIT')
            remaining=deadline-time.monotonic()
            if remaining <= 0:
                self.records[name]['timed_out']=True
                raise TimeoutError(name+' deadline')
            try:return self._finish(name,process.wait(timeout=min(.1,remaining)))
            except subprocess.TimeoutExpired:pass

    def _terminate(self, name, deadline):
        process=self.processes.get(name)
        if process is None:return
        if process.poll() is not None:
            self._finish(name,process.wait());return
        for signum,seconds in ((signal.SIGTERM,5),(signal.SIGKILL,2)):
            if time.monotonic() >= deadline:break
            try:os.killpg(process.pid,signum);self.records[name]['signals'].append(signum)
            except ProcessLookupError:pass
            try:self._wait(name,min(deadline,time.monotonic()+seconds),False);return
            except TimeoutError:pass
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL);self.records[name]['signals'].append(signal.SIGKILL)
            except ProcessLookupError:pass
        try:self._finish(name,process.wait(timeout=0))
        except subprocess.TimeoutExpired:self.records[name]['status']='WAIT_UNKNOWN'

    def command(self, name, argv, seconds, startup=False):
        deadline=min(self.startup_deadline if startup else self.business_deadline,time.monotonic()+seconds)
        if deadline <= time.monotonic() or self.cancelled:raise RuntimeError('BUDGET_OR_CANCELLED_BEFORE_START')
        self._spawn(name,argv,worker=name=='worker')
        return self._wait(name,deadline,watch_pg=name=='worker')

    def prepare_pg(self):
        self.receipt['last_phase']='initdb';self.persist_partial()
        code=self.command('initdb',['initdb','-D',str(self.data_dir),'-A','trust','--encoding=UTF8','--no-locale'],60,True)
        if code:raise RuntimeError('INITDB_FAILED:'+str(code))

    def start_postgres(self):
        if self.cancelled or time.monotonic() >= self.startup_deadline:raise RuntimeError('BUDGET_OR_CANCELLED_BEFORE_START')
        self._spawn('postmaster',['postgres','-D',str(self.data_dir),'-h','127.0.0.1','-p','5432','-k','/tmp'])
        self.receipt['last_phase']='postmaster-started';self.persist_partial()

    def wait_ready(self):
        index=0
        while time.monotonic() < self.startup_deadline:
            if self.processes['postmaster'].poll() is not None:
                self._finish('postmaster',self.processes['postmaster'].wait());raise RuntimeError('PG_START_EXIT')
            code=self.command('ready-%03d'%index,['pg_isready','-h','127.0.0.1','-p','5432','-t','1'],2,True)
            if code==0:return
            index+=1
            time.sleep(min(.1,max(0,self.startup_deadline-time.monotonic())))
        raise TimeoutError('PG_READINESS_TIMEOUT')

    def roles(self):
        for role in ('bounded_ci','release_0078_ci'):
            for name,argv in (
                ('role-'+role,['createuser','-h','127.0.0.1','-U','tester','--superuser',role]),
                ('db-'+role,['createdb','-h','127.0.0.1','-U','tester','-O',role,role])):
                if self.command(name,argv,60,True):raise RuntimeError('PG_ROLE_FAILED:'+name)

    def run_worker(self, args):
        self.receipt['last_phase']='worker';self.persist_partial()
        return self.command('worker',[sys.executable,'scripts/test_plan_worker.py',*args],
                            max(0,self.business_deadline-time.monotonic()))

    def stop_and_wait(self):
        if self.closed:return
        # 所有阶段共享原内deadline；不足就记录UNKNOWN，不追加超时。
        cleanup_end=min(self.deadline,time.monotonic()+30)
        for name in list(self.processes):
            if name not in ('postmaster','pg_stop'):
                try:self._terminate(name,min(cleanup_end,time.monotonic()+7))
                except BaseException as exc:self.error('CHILD_REAP:'+name+':'+repr(exc))
        process=self.processes.get('postmaster')
        if process is not None:
            try:
                if process.poll() is None:
                    if time.monotonic() >= cleanup_end:raise TimeoutError('no PG stop budget before spawn')
                    pidfile=self.data_dir/'postmaster.pid'
                    require(read_regular(pidfile).splitlines()[0].decode()==str(process.pid),'PG_PIDFILE_MISMATCH')
                    self._spawn('pg_stop',['pg_ctl','-D',str(self.data_dir),'-m','immediate','-t','8','-w','stop'])
                    try:
                        stop=self._wait('pg_stop',min(cleanup_end,time.monotonic()+10),False)
                        if stop:self.error('PG_STOP_EXIT:'+str(stop))
                    except BaseException as exc:
                        self.error('PG_STOP_WAIT:'+repr(exc));self._terminate('pg_stop',min(cleanup_end,time.monotonic()+2))
                else:
                    self.error('PG_EXIT_BEFORE_STOP')
                try:self._wait('postmaster',min(cleanup_end,time.monotonic()+3),False)
                except TimeoutError:
                    self.error('PG_DIRECT_WAIT_TIMEOUT')
                    try:os.killpg(process.pid,signal.SIGKILL);self.records['postmaster']['signals'].append(signal.SIGKILL)
                    except ProcessLookupError:pass
                    self._wait('postmaster',min(cleanup_end,time.monotonic()+3),False)
                if self.records['postmaster']['returncode']!=0:self.error('PG_POSTMASTER_EXIT:'+str(self.records['postmaster']['returncode']))
            except BaseException as exc:
                self.error('PG_CLEANUP:'+repr(exc))
                # pidfile/stop起因保持；只针对保存的本PG句柄强杀并wait，不碰其它PID。
                try:
                    if process.poll() is None:
                        os.killpg(process.pid,signal.SIGKILL);self.records['postmaster']['signals'].append(signal.SIGKILL)
                    self._wait('postmaster',min(cleanup_end,time.monotonic()+3),False)
                except BaseException as secondary:self.error('PG_REAP_UNKNOWN:'+repr(secondary))
        # 先逐个自有Popen wait，再处理PID1可能收养的后代，不能偷走直接child wait。
        if all(p.returncode is not None for p in self.processes.values()):
            while time.monotonic()<cleanup_end:
                try:pid,status=os.waitpid(-1,os.WNOHANG)
                except ChildProcessError:break
                if pid==0:
                    self.error('ADOPTED_CHILD_STILL_RUNNING');break
                self.receipt['orphans'].append(dict(pid=pid,status=status,namespace=self.receipt['namespace']))
        try:
            total=0
            for path in sorted(self.log_dir.iterdir()):
                if time.monotonic() >= cleanup_end:raise TimeoutError('log preservation deadline')
                with path.open('rb') as stream:data=stream.read(LOG_LIMIT+1)
                total+=len(data)
                if total>LOG_LIMIT:raise RuntimeError('PG_LOG_OVERFLOW')
                self.receipt['logs'][path.name]=dict(base64=base64.b64encode(data).decode(),bytes=len(data),sha256=raw_hash(data))
        except BaseException as exc:self.error('LOG_PRESERVATION:'+repr(exc))
        finally:
            try:shutil.rmtree(self.log_dir)
            except BaseException as exc:self.error('LOG_TMP_CLEANUP:'+repr(exc))
        self.closed=True

    def persist_partial(self):
        write_receipt(self.output/receipt_filename(self.request['mode'],self.request['key']),self.receipt)

    def execute(self, args):
        try:
            self.install_signals();self.persist_partial()
            if self.receipt['pg_required']:
                self.prepare_pg();self.start_postgres();self.wait_ready();self.roles()
            worker=self.run_worker(args)
            if worker:self.error('WORKER_EXIT:'+str(worker))
        except BaseException as exc:self.error(repr(exc))
        finally:
            self.stop_and_wait()
            for signum,previous in self.old_handlers.items():
                try:signal.signal(signum,previous)
                except BaseException as exc:self.error('SIGNAL_RESTORE:'+repr(exc))
        try:
            native=read_regular(self.output/native_filename(self.request['mode'],self.request['key']))
            self.receipt['native_raw_sha256']=raw_hash(native)
            self.receipt['output_plan_digest']=digest(decode_json(native)) if self.request['mode']=='collect' else self.request['input_plan_digest']
        except BaseException as exc:self.error('OUTPUT_OR_LOG:'+repr(exc))
        worker=self.receipt['worker']['returncode']
        clean=(_numeric(self.receipt['worker'],os.getpid()) and not self.cancelled
               and (not self.receipt['pg_required'] or (_numeric(self.receipt['pg_stop'],os.getpid(),True) and _numeric(self.receipt['postmaster'],os.getpid(),True)))
               and not self.receipt['secondary_errors']
               and (self.receipt['primary_error'] is None or self.receipt['primary_error'].startswith('WORKER_EXIT:')))
        code=(worker if worker>=0 else 128-worker) if clean else 73
        self.receipt.update(complete=clean,last_phase='complete' if clean else 'failed',supervisor_exit=code)
        try:self.persist_partial()
        except BaseException as exc:
            print('PG_LIFECYCLE_PERSISTENCE_FAILED '+repr(exc),file=sys.stderr,flush=True);code=73
        return code


def main():
    args=sys.argv[1:]
    require(len(args)==3,'REQUEST_SCHEMA','three original worker arguments required')
    require(os.getuid()==10001 and os.getgid()==10001 and not Path('/var/run/docker.sock').exists(),'UNSAFE_PRIVILEGE')
    plan=read_json('/control/plan.json');request=read_json('/control/pg-lifecycle-request.json')
    validate_request(request,plan,args[0],args[1],args[2])
    verify_source_binding(plan,read_json('/control/source-binding.json'),Path.cwd(),require_git_head=True)
    return Session(request,plan,'/output').execute(args)


if __name__=='__main__':
    raise SystemExit(main())
