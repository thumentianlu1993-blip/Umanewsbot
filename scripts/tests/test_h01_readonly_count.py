import unittest
import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import scripts.h01_readonly_count as reader
from scripts.h01_readonly_count import run_counts

class Cursor:
    def __init__(self,rows):self.rows=list(rows);self.sql=[]
    def execute(self,sql,params=None):self.sql.append((sql,params))
    def fetchmany(self,n):return self.rows.pop(0)[:n]
    def close(self):pass
class Connection:
    def __init__(self,rows):self.cursor_value=Cursor(rows);self.session={};self.rolled_back=False;self.closed=False
    def set_autocommit(self,value):self.session['autocommit']=value
    def set_read_only(self,value):self.session['readonly']=value
    def set_isolation_level(self,value):self.session['isolation_level']=value
    def cursor(self):return self.cursor_value
    def rollback(self):self.rolled_back=True
    def close(self):self.closed=True
class CountTests(unittest.TestCase):
    def test_project_psycopg3_connect_and_transaction_contract(self):
        import psycopg
        events=[]
        class Driver3Connection:
            def __init__(self):
                self.cursor_value=Cursor(CountTests().good_rows())
                self.rolled_back=self.closed=False
            def set_autocommit(self,value):events.append(('autocommit',value))
            def set_read_only(self,value):events.append(('read_only',value))
            def set_isolation_level(self,value):events.append(('isolation_level',value))
            def cursor(self):
                events.append(('cursor',None))
                return self.cursor_value
            def rollback(self):self.rolled_back=True
            def close(self):self.closed=True
        database=Driver3Connection()
        with patch('psycopg.connect',return_value=database) as connect, \
                patch.dict('sys.modules',{'psycopg2':None}), \
                patch.dict(reader.os.environ,{'H01_READONLY_DSN':'synthetic-dsn'}):
            result=reader._execute_database('a'*40,deadline=reader.time.monotonic()+2.9)
        self.assertEqual(result['status'],'capacity_preflight_finished')
        connect.assert_called_once_with('synthetic-dsn',connect_timeout=2)
        self.assertEqual(events[:4],[('autocommit',False),('read_only',True),
            ('isolation_level',psycopg.IsolationLevel.REPEATABLE_READ),('cursor',None)])
        self.assertTrue(database.rolled_back and database.closed)

    def test_project_psycopg3_transaction_setup_failure_is_closed(self):
        class Driver3Connection:
            rolled_back=closed=False
            def set_autocommit(self,value):pass
            def set_read_only(self,value):raise RuntimeError('private setting')
            def set_isolation_level(self,value):raise AssertionError('must stop')
            def cursor(self):raise AssertionError('no SELECT before valid transaction')
            def rollback(self):self.rolled_back=True
            def close(self):self.closed=True
        database=Driver3Connection()
        with patch('psycopg.connect',return_value=database), \
                patch.dict('sys.modules',{'psycopg2':None}), \
                patch.dict(reader.os.environ,{'H01_READONLY_DSN':'synthetic-dsn'}):
            result=reader._execute_database('a'*40,deadline=reader.time.monotonic()+2)
        self.assertEqual(result['reason'],'database_or_input_error')
        self.assertEqual(result['selects'],0)
        self.assertTrue(database.rolled_back and database.closed)
        self.assertNotIn('private',json.dumps(result))

    def test_remaining_second_limits_sql_and_blocking_worker_is_terminated(self):
        class Clock:
            value=0
            def __call__(self):
                old=self.value
                self.value=119
                return old
        c=Connection(self.good_rows())
        run_counts(c,revision='a'*40,clock=Clock())
        self.assertTrue(any('statement_timeout' in sql and '1000' in sql for sql,_ in c.cursor_value.sql))
        import time
        def blocked():
            time.sleep(10)
            return {'status':'incorrect_success'}
        before=time.monotonic()
        result=reader._bounded_worker(blocked,deadline=before+0.1)
        self.assertLess(time.monotonic()-before,0.5)
        self.assertEqual(result['reason'],'wall_time')
        self.assertEqual(result['status'],'partial')

    def test_actual_blocked_driver_phases_and_cli_share_kill_deadline(self):
        import time
        import multiprocessing
        for phase in ('set_autocommit','set_read_only','set_isolation_level','cursor','execute','fetchmany','rollback','close'):
            with self.subTest(phase=phase):
                c=Connection(self.good_rows())
                owner=c if phase in ('set_autocommit','set_read_only','set_isolation_level','cursor','rollback','close') else c.cursor_value
                original=getattr(owner,phase)
                def blocked(*args, _original=original, **kwargs):
                    time.sleep(10)
                    return _original(*args,**kwargs)
                setattr(owner,phase,blocked)
                before=time.monotonic()
                result=reader._bounded_worker(lambda:run_counts(c,revision='a'*40),deadline=before+0.05)
                self.assertLess(time.monotonic()-before,0.5)
                self.assertEqual(result['reason'],'wall_time')
                self.assertFalse(any(child.is_alive() for child in multiprocessing.active_children()))
        def blocked_database(*args,**kwargs):
            time.sleep(10)
        digest=reader.hashlib.sha256(reader.Path(reader.__file__).read_bytes()).hexdigest()
        with patch.object(reader,'MAX_SECONDS',0.05),patch.object(reader,'_execute_database',blocked_database),redirect_stdout(io.StringIO()) as output:
            before=time.monotonic()
            self.assertEqual(reader.main(['--execute','--revision','a'*40,'--expected-tool-sha256',digest]),2)
            self.assertLess(time.monotonic()-before,0.5)
        self.assertEqual(json.loads(output.getvalue())['reason'],'wall_time')

    def test_readonly_and_schema_fail_closed(self):
        c=Connection([[('missing_schema',False)]])
        r=run_counts(c,revision='a'*40,clock=lambda:0)
        self.assertEqual(r['status'],'partial');self.assertEqual(r['reason'],'schema_mismatch');self.assertTrue(c.rolled_back);self.assertTrue(c.closed);self.assertEqual(c.session,dict(readonly=True,isolation_level=__import__('psycopg').IsolationLevel.REPEATABLE_READ,autocommit=False))
        self.assertEqual(r['selects'],1)
    def test_timeout_partial_does_not_retry(self):
        c=Connection([]);times=iter([0,121]);r=run_counts(c,revision='a'*40,clock=lambda:next(times))
        self.assertEqual(r['reason'],'wall_time');self.assertEqual(r['selects'],0);self.assertTrue(c.rolled_back)

    def good_rows(self):
        return [[('stable_'+t,True) for t in reader.COLUMNS],[('2026-10-03T00:00:00+00:00','on','repeatable read','160000')]]+[[] for _ in reader.QUERIES[2:]]
    def test_valid_fixed_queries_and_never_inventory_complete(self):
        c=Connection(self.good_rows());r=run_counts(c,revision='a'*40,clock=lambda:0);self.assertEqual(r['status'],'capacity_preflight_finished');self.assertEqual(r['selects'],len(reader.QUERIES));self.assertFalse(r['inventory_complete']);self.assertTrue(c.closed)
    def test_rows_bytes_query_cap(self):
        c=Connection([[('x',True)]*501]);r=run_counts(c,revision='a'*40,clock=lambda:0);self.assertEqual(r['reason'],'row_limit')
        rows=self.good_rows();rows[2]=[('private'*1000,1)]
        with patch.object(reader,'MAX_BYTES',1024):r=run_counts(Connection(rows),revision='a'*40,clock=lambda:0)
        self.assertEqual(r['reason'],'byte_limit');self.assertNotIn('private',json.dumps(r))
        queries=reader.QUERIES+tuple(('extra'+str(i),'SELECT 1',None) for i in range(20));rows=self.good_rows()+[[] for _ in range(20)]
        with patch.object(reader,'QUERIES',queries):r=run_counts(Connection(rows),revision='a'*40,clock=lambda:0)
        self.assertEqual(r['reason'],'query_limit');self.assertEqual(r['selects'],24)
    def test_sql_failure_no_secret_echo_no_retry(self):
        c=Connection([])
        def error(*args):raise RuntimeError('password=private')
        c.cursor_value.execute=error;r=run_counts(c,revision='a'*40,clock=lambda:0);self.assertEqual(r['reason'],'database_or_input_error');self.assertNotIn('private',json.dumps(r));self.assertTrue(c.rolled_back)
    def test_transaction_mismatch(self):
        rows=self.good_rows();rows[1]=[('time','off','read committed','160000')];r=run_counts(Connection(rows),revision='a'*40,clock=lambda:0);self.assertEqual(r['reason'],'transaction_mismatch');self.assertEqual(r['selects'],2)
    def test_default_cli_no_connection_and_fixed_binding(self):
        with redirect_stdout(io.StringIO()) as output:self.assertEqual(reader.main([]),0)
        self.assertEqual(json.loads(output.getvalue())['mode'],'templates_only')
        with redirect_stdout(io.StringIO()):self.assertEqual(reader.main(['--execute','--revision','a'*40]),2)
    def test_news_end_exclusive(self):
        sql=next(sql for name,sql,_ in reader.QUERIES if name=='recent_news_links');self.assertIn("< TIMESTAMPTZ '2026-10-04",sql)

    def test_invalid_revision_never_echoes_payload(self):
        c=Connection([]);r=run_counts(c,revision='password=private',clock=lambda:0);self.assertNotIn('private',json.dumps(r));self.assertTrue(c.closed)

if __name__=='__main__':unittest.main()
