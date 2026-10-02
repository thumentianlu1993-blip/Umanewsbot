#!/usr/bin/env python3
"""仅由 network-none 非 root 容器调用；收集或执行一个有界分片。"""
import contextlib
import faulthandler
import importlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'server'), str(ROOT/'.codex/scripts'), str(ROOT/'scripts'), str(ROOT/'runtime/research')]
from tools.test_impact.core import digest, shard_tests
from run_bounded_stable_tests import isolated_environment, flatten


def setup(profile):
    source = {'PATH':os.environ['PATH'], 'HOME':'/home/tester','POSTGRES_PORT':'5432',
              'POSTGRES_DB':'release_0078_ci' if profile=='release-postgres' else 'bounded_ci',
              'POSTGRES_USER':'release_0078_ci' if profile=='release-postgres' else 'bounded_ci'}
    os.environ.clear()
    os.environ.update(isolated_environment(source))
    os.environ.update(DOTENV_DISABLED='1', RELEASE_0078_TEST_POSTGRES='1', RUN_HISTORICAL_PIPELINE_PERF='1')
    import dotenv
    dotenv.load_dotenv = lambda *args, **kw: False
    sys.argv = ['manage.py','test']
    import django
    django.setup()
    from django.conf import settings
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.CACHES = {'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}}


def isolation_probe(profile):
    if os.getuid() == 0 or Path('/var/run/docker.sock').exists():
        raise ValueError('unsafe container privilege')
    interfaces = set(os.listdir('/sys/class/net'))
    if interfaces != {'lo'}:
        raise ValueError('network namespace has non-loopback interfaces')
    checks = [
        [sys.executable,'-I','-c',"import socket; socket.create_connection(('1.1.1.1',443),1)"],
        ['curl','--connect-timeout','1','--max-time','2','https://1.1.1.1'],
    ]
    for cmd in checks:
        if subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode == 0:
            raise ValueError('subprocess network isolation failed')
    if subprocess.run(['docker','run','--pull=never','--rm','hello-world'],capture_output=True,timeout=5).returncode == 0:
        raise ValueError('nested Docker unexpectedly available')
    return {'interfaces':sorted(interfaces),'external_python':'blocked','curl':'blocked','nested_docker':'daemon-blocked'}


def load(labels):
    if len(labels) != len(set(labels)):
        raise ValueError('duplicate human labels')
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(labels)
    cases = list(flatten(suite))
    if any(isinstance(c,unittest.loader._FailedTest) for c in cases):
        raise ValueError('collection failed: '+'\n'.join(loader.errors))
    return cases


def collect(plan, catalog):
    cases, aliases, declared_skips = {}, [], []
    for label in plan['labels']:
        loaded = load([label])
        for case in loaded:
            ident = case.id()
            method=getattr(case,case._testMethodName)
            skipped=getattr(case.__class__,'__unittest_skip__',False) or getattr(method,'__unittest_skip__',False)
            if skipped:
                reason=getattr(case.__class__,'__unittest_skip_why__','') or getattr(method,'__unittest_skip_why__','')
                entry={'id':ident,'reason':reason}
                if entry not in declared_skips: declared_skips.append(entry)
            profile = next((p for m,p in catalog['profiles'].items() if ident.startswith(m+'.')), None)
            if profile is None:
                raise ValueError('unowned test: '+ident)
            if ident in cases:
                aliases.append({'id':ident,'label':label})
                if cases[ident]['profile'] != profile:
                    raise ValueError('profile ownership conflict')
            else:
                cases[ident] = {'id':ident,'profile':profile}
    if plan['labels'] and not cases:
        raise ValueError('empty test collection')
    plan['aliases'] = aliases
    plan['collection_skips'] = declared_skips
    plan['batches'] = shard_tests(list(cases.values()))
    if plan['mode']=='targeted' and len(cases)>400:
        plan['mode']='expanded'
    plan['count']=len(cases)
    return plan


def execute(plan, batch):
    started=time.monotonic()
    report={'key':batch['key'],'profile':batch['profile'],'plan_digest':digest(plan),
            **{k:plan[k] for k in ('run_id','run_attempt','test_tree')},
            'executed':[], 'failures':[], 'errors':[], 'skips':[], 'expected_failures':[],
            'unexpected_successes':[], 'lifecycle':'incomplete','exit_code':1,
            'python':platform.python_version(),'os':platform.platform()}
    class Result(unittest.TextTestResult):
        def startTest(self,test):
            print('RUN '+test.id(), flush=True)
            report['executed'].append(test.id()); super().startTest(test)
        def addSkip(self,test,reason):
            report['skips'].append({'id':test.id(),'reason':reason}); super().addSkip(test,reason)
    try:
        report['isolation']=isolation_probe(batch['profile'])
        if batch['profile']!='python':
            from django.db import connection
            with connection.cursor() as c:
                c.execute('SELECT version()'); report['postgresql']=c.fetchone()[0]
            if 'PostgreSQL 16.' not in report['postgresql']:
                raise ValueError('PostgreSQL 16 required')
        import django
        report['django']=django.get_version()
        cases=load(batch['ids'])
        actual=[c.id() for c in cases]
        if len(actual)!=len(set(actual)) or set(actual)!=set(batch['ids']) or not 0<len(actual)<=200:
            raise ValueError('batch selection mismatch')
        result_holder=[]
        faulthandler.dump_traceback_later(120, repeat=True)
        if batch['profile']=='django':
            from django.test.runner import DiscoverRunner
            class Runner(DiscoverRunner):
                def get_resultclass(self): return Result
                def run_suite(self,suite,**kw):
                    result=super().run_suite(suite,**kw); result_holder.append(result); return result
            status=Runner(verbosity=0,interactive=False).run_tests(batch['ids'])
        else:
            result=unittest.TextTestRunner(verbosity=0,resultclass=Result).run(unittest.TestSuite(cases))
            result_holder.append(result); status=not result.wasSuccessful()
        result=result_holder[0]
        for field in ('failures','errors'):
            report[field]=[{'id':t.id(),'traceback':e} for t,e in getattr(result,field)]
        report['expected_failures']=[t.id() for t,_ in result.expectedFailures]
        report['unexpected_successes']=[t.id() for t in result.unexpectedSuccesses]
        report['exit_code']=int(bool(status)); report['lifecycle']='complete'
    except BaseException:
        report['errors'].append({'id':'infrastructure','traceback':traceback.format_exc()})
    finally:
        faulthandler.cancel_dump_traceback_later()
    report['seconds']=time.monotonic()-started
    return report


def main():
    args=sys.argv[1:]
    mode=args[0]
    plan=json.loads(Path('/control/plan.json').read_text())
    profile='django' if mode=='collect' else args[2]
    setup(profile)
    if mode=='collect':
        plan=collect(plan,json.loads((ROOT/'tools/test_impact/catalog.json').read_text()))
        Path('/output/execution-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
        return 0
    batch=next(b for b in plan['batches'] if b['key']==args[1])
    if batch['profile']!=profile:
        raise ValueError('profile mismatch')
    report=execute(plan,batch)
    Path('/output/'+batch['key']+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report['exit_code']


if __name__=='__main__':
    raise SystemExit(main())
