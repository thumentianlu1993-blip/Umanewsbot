"""F02 tests-only fixture: fail closed before any connection outside proven CI PG16."""
from __future__ import annotations
import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import tempfile

PGDATA='/tmp/pgdata'
PGEXE='/usr/lib/postgresql/16/bin/postgres'
NAMESPACES=('net','mnt','pid','user')
KEYS=set('mode uid python_exe interfaces docker_socket endpoint listener_inode listener_owner_pid pid start_ticks stable namespaces python_namespaces pgdata pg_uid pg_mode symlinks fs_type fs_magic mount_root mountpoint mount_rw propagation nested_mounts device_matches pg_exe pg_exe_sha256 pgdata_inode pgdata_device mount_id cmdline_pgdata python_pid python_start_ticks config_private listener_fd'.split())

class GuardError(ValueError):
    pass

def require(ok, code='internal_ci_binding_rejected'):
    if not ok:raise GuardError(code)

def read(path, limit=1048576):
    with open(path,'rb') as stream:data=stream.read(limit+1)
    require(len(data)<=limit,'proc_budget')
    return data

def process(pid):
    data=read(f'/proc/{pid}/stat').decode()
    parts=data[data.rfind(')')+2:].split()
    return {'start':int(parts[19]),'ppid':int(parts[1])}

def namespaces(pid):
    return {key:int(os.readlink(f'/proc/{pid}/ns/{key}').split('[')[1].rstrip(']')) for key in NAMESPACES}

def mount_table(pid):
    rows=[]
    for line in read(f'/proc/{pid}/mountinfo').decode().splitlines():
        a,b=line.split(' - ',1);fields=a.split();after=b.split()
        require(len(fields)>=6 and len(after)>=3,'mount_parse')
        rows.append({'id':int(fields[0]),'device':fields[2],'root':fields[3],
                     'point':fields[4],'options':fields[5].split(','),
                     'optional':fields[6:],'type':after[0]})
    return rows

def private_pgdata():
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in ('tmp','pgdata'):
            nextfd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            info=os.stat(part,dir_fd=fd,follow_symlinks=False)
            require((info.st_dev,info.st_ino)==(os.fstat(nextfd).st_dev,os.fstat(nextfd).st_ino),'directory_replaced')
            os.close(fd);fd=nextfd
        info=os.fstat(fd)
        require(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o700,'pgdata_not_private')
        piddata=None
        for name in ('postmaster.pid','postgresql.conf','pg_hba.conf'):
            child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
            try:
                st=os.fstat(child)
                require(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and st.st_nlink==1
                        and stat.S_IMODE(st.st_mode)==0o600,'config_not_private')
                if name=='postmaster.pid':
                    piddata=os.read(child,4097);require(len(piddata)<=4096,'pidfile_budget')
            finally:os.close(child)
        # f_type is the first native long of Linux statfs; buffer is larger than struct statfs.
        buffer=ctypes.create_string_buffer(512)
        lib=ctypes.CDLL(None,use_errno=True)
        require(lib.fstatfs(fd,ctypes.byref(buffer))==0,'statfs_failed')
        magic=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_long)).contents.value
        return info,magic,piddata
    finally:os.close(fd)

def capture_once():
    require(sys.platform=='linux' and os.getuid()!=0,'not_isolated_linux')
    require(sys.executable=='/venv/bin/python','wrong_python')
    info,magic,piddata=private_pgdata()
    pidfile=piddata.decode().splitlines()
    require(len(pidfile)>=6 and pidfile[1]==PGDATA and pidfile[3]=='5432','postmaster_file')
    pid=int(pidfile[0]);pgprocess=process(pid);pyprocess=process(os.getpid())
    require(Path(f'/proc/{pid}').stat().st_uid==os.getuid(),'postmaster_owner')
    pgexe=os.readlink(f'/proc/{pid}/exe');require(pgexe==PGEXE,'postmaster_binary')
    cmd=read(f'/proc/{pid}/cmdline',8192).split(b'\0')
    cmd=[v.decode() for v in cmd if v]
    require('-D' in cmd and cmd[cmd.index('-D')+1]==PGDATA,'postmaster_data_argument')
    rows=mount_table(os.getpid());pgrows=mount_table(pid)
    mounts=[row for row in rows if row['point']=='/tmp']
    require(len(mounts)==1,'tmp_mount_unbound')
    mount=mounts[0];require(mount in pgrows,'mount_namespace_mismatch')
    nested=any(row['point'].startswith('/tmp/') for row in rows)
    listeners=[]
    for name in ('tcp','tcp6'):
        for line in read(f'/proc/self/net/{name}').decode().splitlines()[1:]:
            fields=line.split()
            if fields[3]=='0A' and int(fields[1].split(':')[1],16)==5432:
                listeners.append((name,fields[1],int(fields[9])))
    require(len(listeners)==1 and listeners[0][:2]==('tcp','0100007F:1538'),'listener_endpoint')
    inode=listeners[0][2];fds=[]
    entries=list(Path(f'/proc/{pid}/fd').iterdir());require(len(entries)<=256,'fd_budget')
    for path in entries:
        if os.readlink(path)==f'socket:[{inode}]':fds.append(int(path.name))
    require(bool(fds),'listener_not_owned')
    # A duplicate fd for the same inherited socket is allowed, but no different LISTEN inode is.
    return {'mode':'internal-ci-v2','uid':os.getuid(),'python_exe':sys.executable,
            'interfaces':sorted(os.listdir('/sys/class/net')),'docker_socket':Path('/var/run/docker.sock').exists(),
            'endpoint':['127.0.0.1',5432],'listener_inode':inode,'listener_owner_pid':pid,
            'pid':pid,'start_ticks':pgprocess['start'],'stable':True,'namespaces':namespaces(pid),
            'python_namespaces':namespaces(os.getpid()),'pgdata':PGDATA,'pg_uid':info.st_uid,
            'pg_mode':stat.S_IMODE(info.st_mode),'symlinks':False,'fs_type':mount['type'],'fs_magic':magic,
            'mount_root':mount['root'],'mountpoint':mount['point'],'mount_rw':'rw' in mount['options'],
            'propagation':bool(mount['optional']),'nested_mounts':nested,
            'device_matches':mount['device']==f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}',
            'pg_exe':pgexe,'pg_exe_sha256':hashlib.sha256(Path(PGEXE).read_bytes()).hexdigest(),
            'pgdata_inode':info.st_ino,'pgdata_device':info.st_dev,'mount_id':mount['id'],
            'cmdline_pgdata':PGDATA,'python_pid':os.getpid(),'python_start_ticks':pyprocess['start'],
            'config_private':True,'listener_fd':min(fds)}

def capture():
    try:
        first=capture_once();second=capture_once()
        require(first==second,'binding_changed')
        return first
    except GuardError:raise
    except Exception:raise GuardError('binding_unavailable') from None

def _validate(value):
    require(isinstance(value,dict) and set(value)==KEYS)
    require(value['mode']=='internal-ci-v2' and type(value['uid']) is int and value['uid']>0)
    require(value['python_exe']=='/venv/bin/python' and value['interfaces']==['lo'] and value['docker_socket'] is False)
    require(value['endpoint']==['127.0.0.1',5432] and value['listener_owner_pid']==value['pid'])
    for key in ('pid','start_ticks','listener_inode','pgdata_inode','pgdata_device','mount_id','python_pid','python_start_ticks'):
        require(type(value[key]) is int and value[key]>0)
    require(type(value['listener_fd']) is int and value['listener_fd']>=0)
    require(value['stable'] is True and set(value['namespaces'])==set(NAMESPACES)
            and value['namespaces']==value['python_namespaces'])
    require(all(type(v) is int and v>0 for v in value['namespaces'].values()))
    require(value['pgdata']==value['cmdline_pgdata']==PGDATA and value['pg_uid']==value['uid'] and value['pg_mode']==0o700)
    require(value['symlinks'] is False and value['config_private'] is True)
    require(value['fs_type']=='tmpfs' and value['fs_magic']==0x01021994 and value['mount_root']=='/' and value['mountpoint']=='/tmp')
    require(value['mount_rw'] is True and value['propagation'] is False and value['nested_mounts'] is False and value['device_matches'] is True)
    require(value['pg_exe']==PGEXE and re.fullmatch('[a-f0-9]{64}',value['pg_exe_sha256']))
    return value

def validate(value):
    try:return _validate(value)
    except GuardError:raise
    except Exception:raise GuardError('internal_ci_binding_rejected') from None

def dependency_proof():
    import psycopg
    require(psycopg.__version__=='3.2.6','driver_version')
    rows={}
    for name in ('psycopg','psycopg-binary'):
        dist=importlib.metadata.distribution(name);require(dist.version=='3.2.6','driver_distribution')
        files=[path for path in dist.files if str(path).endswith(('RECORD','METADATA','__init__.py','.so'))]
        rows[name]={str(path):hashlib.sha256(Path(dist.locate_file(path)).read_bytes()).hexdigest() for path in files}
        require(any(path.endswith('RECORD') for path in rows[name]),'driver_record_missing')
    return rows

class Fixture:
    def __init__(self, binding, reader, connector):
        self.binding=binding;self.capture=reader;self.connector=connector
        self.root=None;self.created_roles=[];self.database_oid=None;self.guard_created=False
        self.pending_intents=[]
        self.run_id='synthetic-b005-'+secrets.token_hex(8)
        self.dbname='f02_'+self.run_id.replace('-','_')
        self.nonce=secrets.token_hex(32)
        self.passwords={role:secrets.token_hex(32) for role in ('admin','reader')}
        self.config=None
        self.cleanup_status='not_started'

    def unchanged(self):
        require(validate(self.capture())==self.binding,'binding_changed')

    def connection(self, role='bootstrap'):
        self.unchanged()
        import psycopg
        from psycopg.rows import dict_row
        user='tester' if role=='bootstrap' else 'f02_fixture_'+role
        conn=self.connector(host='127.0.0.1',port=5432,dbname='postgres' if role=='bootstrap' else self.dbname,
                            user=user,password='' if role=='bootstrap' else self.passwords[role],
                            autocommit=True,row_factory=dict_row,connect_timeout=3,
                            options='-c statement_timeout=15000 -c lock_timeout=1000')
        try:
            with conn.cursor() as c:
                c.execute("SELECT current_database() AS db,current_user AS role,current_setting('server_version_num')::int AS version,pg_backend_pid() AS pid")
                row=c.fetchone()
                require(row['db']==('postgres' if role=='bootstrap' else self.dbname) and row['role']==user
                        and row['version']//10000==16,'sql_binding_mismatch')
                if role=='bootstrap':
                    c.execute("SELECT current_setting('data_directory') AS data")
                    require(c.fetchone()['data']==PGDATA,'sql_data_directory_mismatch')
                child=process(row['pid'])
                require(child['ppid']==self.binding['pid'] and namespaces(row['pid'])==self.binding['namespaces'],'backend_binding_mismatch')
            self.unchanged()
            return conn
        except BaseException:
            conn.close();raise

    def journal(self, pending=None):
        from scripts import f02_transfer as verifier
        payload={'mode':'internal-ci-v2','run_id':self.run_id,
                 'nonce_sha256':hashlib.sha256(self.nonce.encode()).hexdigest(),
                 'pending_intents':self.pending_intents if pending is None else pending,
                 'known_roles':self.created_roles,'known_database_oid':self.database_oid,
                 'cleanup_status':self.cleanup_status}
        verifier.atomic_json(self.root/'fixture-intent.json',payload)

    def begin_intent(self, kind, name):
        require(not self.pending_intents,'previous_creation_unknown')
        self.pending_intents=[{'kind':kind,'name':name}]
        # Durable private intent precedes CREATE, including failed/unknown responses.
        self.journal()

    def finish_intent(self, kind, name):
        require(self.pending_intents==[{'kind':kind,'name':name}],'intent_mismatch')
        # Only reliable OID/ownership evidence permits promotion; failed journal leaves pending.
        self.journal(pending=[])
        self.pending_intents=[]

    def prepare(self):
        from psycopg import sql
        from scripts import f02_readonly_export as exporter,f02_transfer as verifier
        dependencies=dependency_proof()
        self.root=Path(tempfile.mkdtemp(prefix='b005-f02-',dir='/tmp'));self.root.chmod(0o700)
        require(self.root.stat().st_dev==self.binding['pgdata_device'],'runtime_not_tmpfs')
        conn=self.connection()
        try:
            with conn.cursor() as c:
                c.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('f02_fixture_admin','f02_fixture_reader')")
                require(not c.fetchall(),'fixture_roles_exist')
                c.execute('SELECT oid FROM pg_database WHERE datname=%s',(self.dbname,));require(c.fetchone() is None,'fixture_database_exists')
                for role in ('admin','reader'):
                    name='f02_fixture_'+role
                    self.begin_intent('role',name)
                    c.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Identifier(name),sql.Literal(self.passwords[role])))
                    c.execute('SELECT oid FROM pg_roles WHERE rolname=%s',(name,))
                    row=c.fetchone()
                    require(isinstance(row,dict) and type(row.get('oid')) is int and row['oid']>0,'role_oid_unknown')
                    self.created_roles.append((name,row['oid']))
                    self.finish_intent('role',name)
                self.begin_intent('database',self.dbname)
                c.execute(sql.SQL('CREATE DATABASE {} OWNER f02_fixture_admin').format(sql.Identifier(self.dbname)))
                c.execute('SELECT oid,pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname=%s',(self.dbname,))
                row=c.fetchone()
                require(isinstance(row,dict) and type(row.get('oid')) is int and row['oid']>0
                        and row.get('owner')=='f02_fixture_admin','database_oid_unknown')
                self.database_oid=row['oid']
                self.finish_intent('database',self.dbname)
                c.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(self.dbname)))
                c.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO f02_fixture_reader').format(sql.Identifier(self.dbname)))
        finally:conn.close()
        conn=self.connection('admin')
        try:
            with conn.cursor() as c:
                c.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC; CREATE SCHEMA f02_control; CREATE TABLE f02_control.validation_guard(run_id text NOT NULL,nonce text NOT NULL)')
                c.execute('INSERT INTO f02_control.validation_guard VALUES(%s,%s)',(self.run_id,self.nonce))
                self.guard_created=True
        finally:conn.close()
        files={'exporter':Path(exporter.__file__),'verifier':Path(verifier.__file__),
               'schema':Path(__file__).with_name('f02_pg_schema.sql'),'driver':Path(__file__).with_name('test_f02_export_postgres.py'),
               'fixture':Path(__file__)}
        self.config={'mode':'internal-ci-v2','run_id':self.run_id,'nonce':self.nonce,'binding':self.binding,
                     'dependency':dependencies,'source':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in files.items()},
                     'runtime_root':str(self.root),'connection':{'host':'127.0.0.1','port':5432,'dbname':self.dbname,
                     'admin_user':'f02_fixture_admin','reader_user':'f02_fixture_reader',
                     'admin_password':self.passwords['admin'],'reader_password':self.passwords['reader']}}
        verifier.atomic_json(self.root/'internal-ci-binding.json',self.config)
        print('F02_CI_BINDING '+json.dumps(self.receipt(),sort_keys=True),flush=True)
        return self

    def receipt(self):
        sources=self.config['source'] if self.config else {}
        dependency=self.config['dependency'] if self.config else {}
        return {'mode':'internal-ci-v2','run_id':self.run_id,
                'nonce_sha256':hashlib.sha256(self.nonce.encode()).hexdigest(),
                'binding':self.binding,'source':sources,
                'dependency_sha256':hashlib.sha256(json.dumps(dependency,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                'cleanup_status':self.cleanup_status,'pending_intents':self.pending_intents}

    def cleanup(self):
        from psycopg import sql
        try:
            require(not self.pending_intents,'creation_outcome_unknown')
            if self.database_oid is not None:
                if self.guard_created:
                    conn=self.connection('admin')
                    try:
                        with conn.cursor() as c:
                            c.execute('SELECT run_id,nonce FROM f02_control.validation_guard')
                            require(c.fetchall()==[{'run_id':self.run_id,'nonce':self.nonce}],'cleanup_guard_mismatch')
                    finally:conn.close()
                conn=self.connection()
                try:
                    with conn.cursor() as c:
                        c.execute('SELECT oid,pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname=%s',(self.dbname,))
                        require(c.fetchone()=={'oid':self.database_oid,'owner':'f02_fixture_admin'},'cleanup_database_mismatch')
                        c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.dbname)))
                finally:conn.close()
                self.database_oid=None
            if self.created_roles:
                conn=self.connection()
                try:
                    with conn.cursor() as c:
                        for name,oid in reversed(self.created_roles):
                            c.execute('SELECT oid FROM pg_roles WHERE rolname=%s',(name,))
                            require(c.fetchone()=={'oid':oid},'cleanup_role_mismatch')
                            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
                finally:conn.close()
                self.created_roles=[]
            if self.root is not None:
                require(self.root.is_dir() and not self.root.is_symlink() and self.root.stat().st_uid==self.binding['uid'],'cleanup_runtime_mismatch')
                shutil.rmtree(self.root);self.root=None
            self.cleanup_status='complete'
            print('F02_CI_CLEANUP complete',flush=True)
        except BaseException:
            self.cleanup_status='unknown_container_cleanup_required'
            if self.root is not None:
                try:self.journal()
                except Exception:pass
            print('F02_CI_CLEANUP unknown_container_cleanup_required',flush=True)
            raise GuardError('fixture_cleanup_unknown') from None

def prepare_fixture(*, _capture=None, _connect=None):
    reader=_capture or capture
    binding=validate(reader())
    if _connect is None:
        import psycopg
        _connect=psycopg.connect
    fixture=Fixture(binding,reader,_connect)
    try:return fixture.prepare()
    except BaseException:
        # No unknown object is adopted; ambiguous creation is resolved by container teardown.
        if fixture.created_roles or fixture.database_oid or fixture.root:
            fixture.cleanup()
        raise GuardError('fixture_prepare_failed') from None
