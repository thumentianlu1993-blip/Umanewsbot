"""Per-method component observation gate; no spawning, IO, candidate imports or receipt mutation."""
import base64
import hashlib
import re
import errno
import math
import os
import signal

SCHEMA = 'pg-lifecycle-v2'

def _adopted_proof_valid(receipt):
    """Validate positive ECHILD evidence independently of complete/worker success."""
    try:
        if type(receipt) is not dict:return False
        proof=receipt.get('adopted_wait');orphans=receipt.get('orphans')
        if type(proof) is not dict or set(proof)!={'status','deadline_monotonic','echild','error','events'}:return False
        if type(proof['status']) is not str or proof['status']!='ECHILD' or proof['echild'] is not True or proof['error'] is not None:return False
        deadline=proof['deadline_monotonic']
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<0:return False
        events=proof['events']
        if type(events) is not list or not events or type(orphans) is not list:return False
        reaped={};terminal=0
        def child(value):
            if type(value) is not dict or set(value)!={'pid','status','returncode','namespace'}:return False
            pid=value['pid'];status=value['status'];code=value['returncode'];namespace=value['namespace']
            return (type(pid) is int and pid>0 and type(status) is int and status>=0
                    and (os.WIFEXITED(status) or os.WIFSIGNALED(status))
                    and type(code) is int and os.waitstatus_to_exitcode(status)==code
                    and type(namespace) is str and bool(namespace)
                    and type(receipt.get('namespace')) is str and namespace==receipt['namespace'])
        for index,event in enumerate(events):
            if type(event) is not dict or type(event.get('kind')) is not str:return False
            kind=event['kind']
            if kind=='REAPED':
                if set(event)!={'kind','pid','status','returncode','namespace'}:return False
                value={k:v for k,v in event.items() if k!='kind'}
                if not child(value) or value['pid'] in reaped:return False
                reaped[value['pid']]=value
            elif kind=='ECHILD':
                if set(event)!={'kind','errno'} or type(event['errno']) is not int or event['errno']!=errno.ECHILD or index!=len(events)-1:return False
                terminal+=1
            elif kind=='EINTR':
                if set(event)!={'kind','errno'} or type(event['errno']) is not int or event['errno']!=errno.EINTR:return False
            elif kind=='NOT_READY':
                if set(event)!={'kind','pid','status','returncode'} or type(event['pid']) is not int or event['pid']!=0 or type(event['status']) is not int or event['status']!=0 or event['returncode'] is not None:return False
            else:return False
        observed={}
        for value in orphans:
            if not child(value) or value['pid'] in observed:return False
            observed[value['pid']]=value
        return terminal==1 and reaped==observed
    except (KeyError,TypeError,ValueError,OverflowError,OSError):return False



PREFIX='tools.test_impact.test_pg_lifecycle.RealPGTests.'
KINDS={
 'test_real_foreground_pid_and_separate_stop_wait':'P1',
 'test_real_worker7_does_not_hide_stop_wait0':'P2',
 'test_real_sigstop_forces_real_stop_timeout_not_success':'P3',
 'test_real_initdb_failure_has_no_fake_postmaster_zero':'P6a',
 'test_real_early_postmaster_exit_is_reaped':'P5',
}

def component_evidence_errors(value):
    """Return evidence errors without changing the input, original status, receipt or numbers."""
    try:return _errors(value)
    except Exception as exc:return ['INVALID_EVIDENCE_STRUCTURE:'+type(exc).__name__+':'+str(exc)]

def _errors(value):
    errors=[]
    def require(ok,code):
        if not ok:errors.append(code)
    ident=value.get('canonical_id','')
    if not isinstance(ident,str) or not ident.startswith(PREFIX) or ident[len(PREFIX):] not in KINDS:return ['UNEXPECTED_METHOD']
    kind=KINDS[ident[len(PREFIX):]]
    receipt=value.get('receipt')
    if type(receipt)is not dict:return ['NO_SESSION_RECEIPT']
    if type(value.get('request_schema_version')) is not str or value['request_schema_version']!=SCHEMA or type(receipt.get('schema_version')) is not str or receipt['schema_version']!=SCHEMA:return ['LIFECYCLE_VERSION_MISMATCH']
    if not _adopted_proof_valid(receipt):return ['ADOPTED_REAP_INCOMPLETE']
    parent=receipt.get('supervisor_pid')
    require(type(parent)is int and parent>0,'SUPERVISOR_PID')
    require(type(receipt.get('uid'))is int and receipt['uid']==10001 and type(receipt.get('gid'))is int and receipt['gid']==10001,'SUPERVISOR_IDENTITY')
    require(value.get('session_closed') is True,'SESSION_NOT_CLOSED')
    require(value.get('data_dir_exists_after_cleanup') is False and value.get('log_dir_exists_after_cleanup') is False,'SESSION_TMP_NOT_REMOVED')
    require(receipt.get('signal_events')==[],'UNEXPECTED_SUPERVISOR_SIGNAL')
    data=value.get('data_dir_original')
    require(type(data)is str and data.startswith('/tmp/') and '..' not in data.split('/') and data.endswith('/pgdata'),'PRIVATE_PGDATA')
    raw_handles=value.get('actual_popen_handles')
    if type(raw_handles)is not list:return errors+['HANDLE_SET']
    handles={}
    for handle in raw_handles:
        name=handle.get('name')
        require(type(name)is str and name not in handles,'HANDLE_SET_DUPLICATE')
        handles[name]=handle
    records={name:receipt.get(name) for name in ('worker','postmaster','pg_stop')}
    tools=receipt.get('tools')
    if type(tools)is not list:return errors+['TOOLS_SET']
    for record in tools:
        name=record.get('purpose')
        require(type(name)is str and name not in records,'TOOLS_SET_DUPLICATE')
        records[name]=record
    ready=[record.get('purpose') for record in tools if type(record.get('purpose'))is str and re.fullmatch(r'ready-[0-9]{3,}',record['purpose'])]
    mandatory=['initdb']
    if kind!='P6a':mandatory+=['postmaster']+ready
    if kind in ('P1','P2'):mandatory+=['worker','pg_stop']
    elif kind=='P3':mandatory+=['pg_stop']
    for name in mandatory:require(name in handles,'EXPECTED_HANDLE:'+name)
    allowed=set(mandatory)
    for name in handles:require(name in allowed,'UNEXPECTED_HANDLE:'+str(name))
    require(all(name=='initdb' or name in ready for name in (r.get('purpose') for r in tools)),'UNEXPECTED_TOOL')
    for name in ('worker','postmaster','pg_stop'):
        if name not in mandatory:
            expected=dict(status='NOT_STARTED',started=False,pid=None,ppid=None,argv=[],returncode=None,reaped=False,timed_out=False,signals=[])
            require(records[name]==expected and name not in handles,'NOT_STARTED:'+name)
    pids=[]
    for name in mandatory:
        record=records.get(name);handle=handles.get(name)
        if type(record)is not dict:
            require(False,'STEP_EVIDENCE:'+name);continue
        numeric=(record.get('started')is True and type(record.get('pid'))is int and record['pid']>0 and record['pid']!=parent
                 and type(record.get('ppid'))is int and record['ppid']==parent and record.get('reaped')is True
                 and type(record.get('returncode'))is int and record.get('status')=='REAPED'
                 and type(record.get('timed_out'))is bool and type(record.get('signals'))is list
                 and all((type(n) is int or type(n) is signal.Signals) and n in (9,15) for n in record['signals']))
        require(numeric,'STEP_EVIDENCE:'+name)
        if numeric:pids.append(record['pid'])
        joined=(type(handle)is dict and handle.get('popen_instance')is True and type(handle.get('pid'))is int
                and type(handle.get('returncode'))is int and handle['pid']==record.get('pid')
                and handle['returncode']==record.get('returncode') and handle.get('argv')==record.get('argv'))
        require(joined,'HANDLE_JOIN:'+name)
        expected_argv=(['initdb','-D',data,'-A','trust','--encoding=UTF8','--no-locale'] if name=='initdb' else
            ['postgres','-D',data,'-h','127.0.0.1','-p','5432','-k','/tmp'] if name=='postmaster' else
            ['pg_ctl','-D',data,'-m','immediate','-t','8','-w','stop'] if name=='pg_stop' else
            [value.get('supervisor_python','/venv/bin/python'),'-I','-c','pass' if kind=='P1' else 'raise SystemExit(7)'] if name=='worker' else
            ['pg_isready','-h','127.0.0.1','-p','5432','-t','1'])
        require(record.get('argv')==expected_argv,'EXPECTED_ARGV:'+name)
        if not (kind=='P3' and name in ('postmaster','pg_stop')):
            require(record.get('timed_out')is False and record.get('signals')==[],'UNEXPECTED_TIMEOUT_OR_TERMINATION:'+name)
    require(len(pids)==len(set(pids)),'DUPLICATE_COMPONENT_PID')
    def exit_is(name,code):
        actual=records.get(name) or {}
        require(type(actual.get('returncode'))is int and actual['returncode']==code,'EXPECTED_EXIT:'+name+':'+str(code))
    def nonzero(name):
        actual=records.get(name) or {}
        require(type(actual.get('returncode'))is int and actual['returncode']!=0,'EXPECTED_NONZERO:'+name)
    if kind=='P6a':
        nonzero('initdb');require(not ready,'UNEXPECTED_READINESS')
    else:
        exit_is('initdb',0)
        require(bool(ready) and type(records[ready[-1]].get('returncode'))is int and records[ready[-1]]['returncode']==0,'READINESS_FINAL_ZERO')
        for name in ready:require(type(records[name].get('returncode'))is int and records[name]['returncode'] in (0,1,2),'READINESS_NUMERIC:'+name)
    if kind in ('P1','P2'):
        exit_is('worker',0 if kind=='P1' else 7);exit_is('postmaster',0);exit_is('pg_stop',0)
    elif kind=='P5':exit_is('postmaster',-9)
    elif kind=='P3':
        post=records.get('postmaster') or {};stop=records.get('pg_stop') or {}
        nonzero('postmaster')
        require(post.get('timed_out')is True and 9 in post.get('signals',[]),'P3_PG_TERMINATION_EVIDENCE')
        if stop.get('timed_out')is True:
            require(any(s in (9,15) for s in stop.get('signals',[])) and type(stop.get('returncode'))is int,'P3_STOP_TIMEOUT_EVIDENCE')
            expected_primary="PG_STOP_WAIT:TimeoutError('pg_stop deadline')"
        else:
            nonzero('pg_stop')
            require(stop.get('timed_out')is False and stop.get('signals')==[],'P3_STOP_NONZERO_EVIDENCE')
            expected_primary='PG_STOP_EXIT:'+str(stop.get('returncode'))
        require(receipt.get('primary_error')==expected_primary and receipt.get('secondary_errors')==['PG_DIRECT_WAIT_TIMEOUT','PG_POSTMASTER_EXIT:'+str(post.get('returncode'))],'ERROR_POLICY:P3')
    if kind in ('P1','P2','P6a'):
        require(receipt.get('primary_error')is None and receipt.get('secondary_errors')==[],'ERROR_POLICY:'+kind)
    elif kind=='P5':
        require(receipt.get('primary_error')=='PG_EXIT_BEFORE_STOP' and receipt.get('secondary_errors')==['PG_POSTMASTER_EXIT:-9'],'ERROR_POLICY:P5')
    logs=receipt.get('logs');expected_logs={name+suffix for name in handles if name!='worker' for suffix in ('.stdout','.stderr')}
    require(type(logs)is dict and set(logs)==expected_logs,'LOG_SET')
    if type(logs)is dict:
        total=0
        for name,value in logs.items():
            try:
                raw=base64.b64decode(value['base64'],validate=True);total+=len(raw)
                require(type(value['bytes'])is int and value['bytes']==len(raw) and value['sha256']==hashlib.sha256(raw).hexdigest(),'LOG_EVIDENCE:'+name)
            except (ValueError,KeyError,TypeError):require(False,'LOG_EVIDENCE:'+name)
        require(total<=512*1024,'LOG_LIMIT')
    return errors

def apply_component_gate(value,evidence_errors,stop):
    """Append dedicated first evidence cause and stop before another method; preserve receipt/status."""
    errors=component_evidence_errors(value)
    if not errors:
        value['signal_evidence']={name:[dict(source_type='signal.Signals' if type(n) is signal.Signals else 'builtins.int',numeric_value=int(n)) for n in value['receipt'][name]['signals']] for name in ('worker','postmaster','pg_stop')}
    value['component_evidence_errors']=errors
    value['component_evidence_status']='REJECTED' if errors else 'ACCEPTED_COMPONENT_ONLY'
    value['evidence_error']=('COMPONENT_EVIDENCE:'+str(value.get('canonical_id'))+':'+errors[0]) if errors else None
    if errors:
        evidence_errors.append(value['evidence_error']);stop();return False
    return True
