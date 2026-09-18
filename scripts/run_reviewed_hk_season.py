#!/usr/bin/env python3
"""生产宿主机执行入口：共享部署锁、备份、固定资料包、既有容器内单事务导入。"""
import argparse
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess

RELEASE = '7e111914d57083299ce452b6222ab9d38476e420'
ROOT = Path('/opt/umanews-release-7e111914-PR205-20260918/umanewsbot')
WEB = 'umanewsbot-web-1'
HOST_PACKAGE = Path('/opt/umanewsbot-persistent/runtime/artifacts/hk-season-20260918')
CONTAINER_PACKAGE = '/tmp/reviewed-hk-season-20260918'


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(ok, why):
    if not ok:
        raise RuntimeError(why)


def require_healthy(services):
    check(all(s['State']['Running'] and not s['State']['OOMKilled'] and
          s['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
          for s in services), 'service healthcheck failed')


@contextmanager
def held_deployment_lock(lock, env, evidence):
    run([lock, 'acquire'], env=env)
    state = {'uncertain': False}
    try:
        yield state
    finally:
        if state['uncertain']:
            (evidence / 'operation-uncertain.json').write_text(json.dumps({
                'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'lock_retained': True,
                'reason': 'Apply started without verified terminal state; inspect container process and receipt before releasing lock.'}))
        else:
            run([lock, 'release'], env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    seal_path = HOST_PACKAGE / 'seal.json'
    check(sha(seal_path) == args.seal_sha256, 'seal mismatch')
    seal = json.loads(seal_path.read_text())
    check(set(seal['files']) == {'import_reviewed_hk_season.py', 'run_reviewed_hk_season.py', 'manifest.json',
          'sources/season-2627-en-us.json', 'sources/season-2627-zh-hk.json',
          'sources/chief-executive-result-en.html', 'sources/chief-executive-result-zh.html',
          'sources/racecard-20260906.pdf'}, 'package scope')
    check(all(sha(HOST_PACKAGE / name) == value for name, value in seal['files'].items()), 'package file drift')
    check(sha(__file__) == seal['files']['run_reviewed_hk_season.py'], 'wrapper drift')
    evidence = HOST_PACKAGE / 'evidence'; evidence.mkdir(mode=0o700, exist_ok=True)
    env = dict(os.environ, DEPLOYMENT_LOCK_TOKEN=secrets.token_hex(32),
               DEPLOYMENT_LOCK_ACTION='manual-release', COMPOSE_FILE='docker-compose.prod.lowcost.yml',
               COMPOSE_PROJECT_NAME='umanewsbot', EXPECTED_COMPOSE_PROJECT='umanewsbot')
    lock = str(ROOT / 'deploy/deployment_lock.sh')
    with held_deployment_lock(lock, env, evidence) as window:
        for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda n, f: (_ for _ in ()).throw(SystemExit(128+n)))
        Path('/tmp/umanews-deployment.lock/operation.json').write_text(json.dumps({
            'owner': 'Codex-root', 'operation': 'reviewed HKJC 2627 import', 'pid': os.getpid(),
            'seal_sha256': args.seal_sha256, 'apply': args.apply}))
        services = json.loads(run(['docker', 'inspect'] + ['umanewsbot-'+s+'-1' for s in
            ['web', 'worker', 'beat', 'race_sync_v2_worker', 'db', 'redis', 'nginx', 'onebot']]))
        require_healthy(services)
        check(services[0]['Config']['Labels']['com.docker.compose.project.working_dir'] == str(ROOT), 'active root drift')
        check(run(['docker', 'exec', WEB, 'cat', '/app/.umanews-release-commit']) == RELEASE, 'release drift')
        repair = ROOT / 'runtime/migration_history_repair'
        check(not any((repair / p).exists() for p in ['release-0078-recovery/active.json',
            'restricted-recovery.json', 'restricted-recovery.transition.json', 'restricted-recovery-control.json']), 'release recovery active')
        check(shutil.disk_usage('/opt').free >= 8*1024**3, 'disk limit')
        for p in Path('/proc').iterdir():
            if not p.name.isdigit(): continue
            try: command = (p / 'cmdline').read_bytes()
            except OSError: continue
            check(not any(x in command for x in [b'run_horse_import_', b'run_historical_batch',
                b'horse-db-rollout-20260916', b'import_external_horse_data']), 'collector process active')
        run(['docker', 'exec', WEB, 'mkdir', '-p', CONTAINER_PACKAGE+'/sources'])
        for name in seal['files']:
            run(['docker', 'cp', str(HOST_PACKAGE/name), WEB+':'+CONTAINER_PACKAGE+'/'+name])
        script = CONTAINER_PACKAGE + '/import_reviewed_hk_season.py'
        def shell(code):
            return run(['docker', 'exec', WEB, 'python', 'manage.py', 'shell', '-c', code]).splitlines()[-1]
        def execute(apply=False):
            argv = [script, '--manifest', CONTAINER_PACKAGE+'/manifest.json', '--sources', CONTAINER_PACKAGE+'/sources',
                '--manifest-sha256', seal['manifest_sha256'], '--script-sha256', seal['files']['import_reviewed_hk_season.py']]
            if apply: argv.append('--apply')
            return json.loads(shell('import sys,runpy;sys.argv='+repr(argv)+';runpy.run_path('+repr(script)+",run_name='__main__')"))
        preview = execute()
        (evidence/'preview.json').write_text(json.dumps(preview, indent=2))
        check(preview['status'] in ['dry_run', 'already_applied'], 'dry-run failed')
        if args.apply and preview['status'] != 'already_applied':
            check(not (evidence/'apply.started.json').exists(), 'previous apply attempt requires explicit inspection')
            snapshots = shell('import json,runpy; s=runpy.run_path('+repr(script)+
                ");print(json.dumps({str(pk):s['event_snapshot'](pk) for pk in [2,828,830,924]},default=str))")
            (evidence/'private-before.json').write_text(snapshots)
            backup_env = dict(env, BACKUP_TARGET='local', BACKUP_DIR=str(HOST_PACKAGE/'backups'))
            backup = run([str(ROOT/'deploy/backup_db.sh')], cwd=ROOT, env=backup_env)
            (evidence/'backup.log').write_text(backup)
            files = list((HOST_PACKAGE/'backups').glob('*.dump'))
            check(len(files) == 1 and files[0].is_file() and files[0].stat().st_size > 1024**2, 'backup missing or ambiguous')
            check(files[0].stat().st_mode & 0o777 == 0o600, 'backup permissions')
            check(shutil.disk_usage('/opt').free >= 8*1024**3, 'post-backup disk limit')
            (evidence/'backup.json').write_text(json.dumps({'path':str(files[0]),'sha256':sha(files[0]),'size':files[0].stat().st_size}))
            check(execute()['status'] == 'dry_run', 'post-backup baseline drift')
            (evidence/'apply.started.json').write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'seal_sha256':args.seal_sha256}))
            window['uncertain'] = True
            result = execute(True)
            (evidence/'apply.json').write_text(json.dumps(result, indent=2))
            check(result['status'] == 'applied' and result['create_count'] == 34, 'unexpected apply result')
            verify = execute()
            check(verify['status'] == 'already_applied', 'post-apply verification failed')
            (evidence/'verify.json').write_text(json.dumps(verify, indent=2))
        else:
            result = preview
        after = json.loads(run(['docker', 'inspect'] + [s['Id'] for s in services]))
        require_healthy(after)
        window['uncertain'] = False
        print(json.dumps({'status':result['status'],'create_count':result['create_count'],
            'seal_sha256':args.seal_sha256,'services_unchanged':True}))


if __name__ == '__main__': main()
