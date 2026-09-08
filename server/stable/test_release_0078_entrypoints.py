"""真实 host coordinator/resume/锁与文件权限；Docker 边界使用离线替身。

这些测试不把 fake migration 当数据库证明。真实 DDL 与恢复另由 PG16 套件执行。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

from stable.services import release_0078_recovery as contract


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "stable.0077_racing_api_horse_identity_staging"
TARGET = "stable.0078_externalhorse_profile_snapshot"
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64
DB = "d" * 64
SERVICES = ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")
WRITER_FLAGS = (
    "RACE_LIVE_SCHEDULER_ENABLED", "RACE_LIVE_MONITOR_ENABLED", "RACE_DATA_SYNC_ENABLED",
    "RACE_DATA_SYNC_SCHEDULER_ENABLED", "RACE_DATA_SYNC_ALLOW_NETWORK", "RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED",
    "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED", "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED",
    "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED", "RACE_DATA_SYNC_RESULT_APPLY_ENABLED",
    "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED", "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED",
    "HISTORICAL_RACE_BACKFILL_ENABLED", "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK",
)


FAKE_BOUNDARIES = r'''#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
from pathlib import Path
root = Path(os.environ['UMANEWS_ROOT_DIR'])
sys.path.insert(0, str(root/'server'))
from stable.services import release_0078_recovery as c
state_path = root/'test-state.json'
state = json.loads(state_path.read_text())
command = sys.argv[1]
args = sys.argv[2:]
def save(): state_path.write_text(json.dumps(state))
def event(name):
    with (root/'events.jsonl').open('a') as stream: stream.write(json.dumps(name)+'\n')
def fail(name):
    flag = root/'fault.txt'
    if flag.exists() and flag.read_text() == name:
        flag.unlink(); event('fault:'+name); raise SystemExit(42)
def option(prefix):
    return next((arg[len(prefix):] for arg in args if arg.startswith(prefix)), '')
def resolved_flags():
    return {name:os.environ.get(name,value) for name,value in state['flags'].items()}
def control_flags():
    effective={name:os.environ.get(name,'false') for name in state['flags']}
    event('control-env:'+json.dumps({'command':args, 'flags':effective},sort_keys=True))
    if any(value not in ('','0','false','off','no') for value in effective.values()):
        raise SystemExit('application writer activity is not quiescent')
def ensure_marker():
    assert not any(value for name,value in state['services'].items() if name!='nginx')
    artifact,_=c.read_json(Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH']))
    c.verify_admission(Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH']), os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_SHA256'], {'release_0078_recovery_binding_mode':'bound'})
    marker=root/'runtime/migration_history_repair/restricted-recovery.json'
    fail('marker-before-write')
    if not marker.exists():
        payload={'schema_version':'migration-history-repair-restricted-recovery/v3', **c.marker_binding(artifact), 'initial_leaf_set':[state['leaf']]}
        payload['marker_sha256']=c.digest(payload)
        c.publish_once(marker,payload)
    return marker
if command == 'git':
    event('git:'+' '.join(args))
    if args[:1] in (['rev-parse'], ['symbolic-ref']): print(os.environ['EXPECTED_CANDIDATE_COMMIT'])
    elif args[:1] in (['fetch'], ['cat-file']): pass
    else: raise SystemExit(91)
elif command == 'docker':
    event('docker:'+' '.join(args))
    if args[:2] == ['image','inspect']:
        print(os.environ['EXPECTED_CANDIDATE_COMMIT'] if 'revision' in ' '.join(args) else os.environ['EXPECTED_CANDIDATE_IMAGE_ID'])
    elif args[:1] == ['inspect']:
        service = args[-1].removeprefix('cid-')
        if 'com.docker.compose.project' in ' '.join(args): print('isolated0078')
        elif '{{.Image}}' in args: print(state.get('images',{}).get(service,os.environ['EXPECTED_CANDIDATE_IMAGE_ID']))
        elif '.Config.Env' in ' '.join(args):
            flags=state.get('container_flags',{}).get(service,state['flags'])
            print(json.dumps([name+'='+value for name,value in flags.items()]))
        else:
            running = state['services'][service]
            print(('true running ' if running else 'false exited ') + 'node-'+service)
    elif args[:1] == ['run'] and 'pg_restore' in args: print('synthetic custom dump TOC')
    else: raise SystemExit(92)
elif command == 'compose':
    while args and args[0] in ('-f', '--project-name'): args=args[2:]
    event('compose:'+' '.join(args))
    child_env={**os.environ, **resolved_flags()}
    if args[0]=='run':
        for index,value in enumerate(args[:-1]):
            if value=='-e':
                key,value=args[index+1].split('=',1)
                child_env[key]=value
        event('one-shot-env:'+json.dumps({'command':args, 'flags':{name:child_env[name] for name in state['flags']}},sort_keys=True))
    if args[0] == 'ps':
        service = args[-1]
        fail('probe-'+service)
        if service in state['services']: print('cid-'+service)
    elif args[0] == 'config':
        print(json.dumps({'name':os.environ.get('COMPOSE_PROJECT_NAME','isolated0078'), 'services':{service:{'environment':resolved_flags()} for service in state['compose_services']}}))
    elif args[0] == 'stop':
        # This is the externally visible side effect: durable intent and
        # active pointer must already exist and validate before it happens.
        pointer, _ = c.read_json(root/'runtime/migration_history_repair/release-0078-recovery/active.json')
        c.verify_intent(Path(pointer['intent_path']), pointer['intent_file']['sha256'], {})
        event('stop-with-verified-intent:'+args[-1])
        state['services'][args[-1]]=False; save(); fail('after-first-stop')
    elif args[0] == 'up':
        receipts=list((root/'runtime/migration_history_repair').glob('restricted-recovery.completed.*.json'))
        assert receipts and state.get('static_complete'), 'writer started before schema/static completion'
        state['services'][args[-1]]=True
        state.setdefault('images',{})[args[-1]]=state.get('start_image_overrides',{}).get(args[-1],os.environ['EXPECTED_CANDIDATE_IMAGE_ID'])
        state.setdefault('container_flags',{})[args[-1]]=state.get('start_flag_overrides',{}).get(args[-1],resolved_flags())
        save(); event('start-after-completion:'+args[-1]); fail('after-service-start')
    elif args[0] == 'exec':
        if 'pg_restore' in args: print('synthetic custom dump TOC')
        elif 'print(connection.vendor)' in args[-1]: print('postgresql')
        elif 'historical-initial-install-0070-or-later' in args[-1]: print(state['initial_install_schema'])
        else: assert args[-2:] == ['-s','reload']
    elif args[0] == 'run' and 'check_historical_calendar_release_b_schema' in args:
        print(json.dumps({'ok': True, 'migration_leaf_set':[state['leaf']], 'database_identity_sha256':state['database_identity']}))
    elif args[0] == 'run' and 'create_historical_calendar_release_b_handoff' in args:
        child_env.update(RELEASE_B_PREFLIGHT_ARTIFACT_PATH=option('--output-path='),RELEASE_B_PREFLIGHT_ACTION=option('--action='))
        raise SystemExit(subprocess.run([sys.executable,__file__,'preflight',*args],env=child_env).returncode)
    elif args[0] == 'run' and args[-2:] == ['web','/app/deploy/docker/run-release-tasks.sh']:
        if state.get('real_control'):
            raise SystemExit(subprocess.run(['sh',str(root/'fake-control-release.sh')],env=child_env).returncode)
        raise SystemExit(state.get('compose_release_rc',0))
    elif args[0] in ('pull','build') or (args[0]=='run' and args[-3:]==['nginx','nginx','-t']):
        pass
    else: raise SystemExit(93)
elif command == 'backup':
    fail('backup-before-write')
    path=Path(os.environ['BACKUP_DIR'])/'test.dump'
    assert not path.exists()
    path.write_bytes(b'new synthetic backup for this release'); path.chmod(0o600)
    event('backup-created'); print('Backup created: '+str(path))
elif command == 'preflight':
    if state.get('real_control'): control_flags()
    bound=bool(os.environ.get('RELEASE_0078_INTENT_PATH'))
    if bound:
        assert not any(value for name,value in state['services'].items() if name!='nginx')
        fail('closed-before-write')
    else: fail('admission-failure')
    path=Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH'])
    payload={'schema_version':'migration-history-repair-preflight/v5',
        'target_leaf_set':['stable.0078_externalhorse_profile_snapshot'],
        'migration_contract_sha256':c.migration_contract(),
        'candidate_commit':os.environ['EXPECTED_CANDIDATE_COMMIT'],
        'candidate_image_id':os.environ['EXPECTED_CANDIDATE_IMAGE_ID'],
        'database_identity_sha256':state['database_identity'],
        'compose_file':os.environ['COMPOSE_FILE'], 'artifact_path':str(path),
        'deployment_lock_token_sha256':hashlib.sha256(os.environ['DEPLOYMENT_LOCK_TOKEN'].encode()).hexdigest(),
        'handoff_action':'forward-resume' if bound else os.environ.get('RELEASE_B_PREFLIGHT_ACTION','deploy'),
        'release_0078_recovery_binding_mode':'bound' if bound else 'admission-only',
        'recovery_intent_mode':'required', 'recovery_origin_action':'release-0078',
        'writer_activity':{'ok':True,'counts':{},'flags':{name:os.environ.get(name,'false') for name in state['flags']} if state.get('real_control') else state['flags']},
        'preflight':{'ok':True,'database_identity_sha256':state['database_identity'],'migration_leaf_set':[state['leaf']], 'migration_plan':[] if state['leaf'].startswith('stable.0078') else ['0078_externalhorse_profile_snapshot']},
        **({key:os.environ[key.upper()] for key in c.BINDING_FIELDS} if bound else {})}
    if bound and state.get('closed_database_identity'):
        # The live closed preflight reports a different database only after
        # all stops. The real coordinator must reject even a re-signed file.
        payload['database_identity_sha256']=state['closed_database_identity']
        payload['preflight']['database_identity_sha256']=state['closed_database_identity']
        event('closed-database-drift')
    payload['artifact_sha256']=c.digest(payload)
    c.publish_once(path,payload); event('closed-written' if bound else 'admission-written')
elif command == 'manage':
    # The real release shell executes every phase. Django/database behavior is
    # the explicit synthetic boundary; the separate PG16 suite owns real DDL.
    control_flags()
    if args[0].endswith('wait_for_services.py'): pass
    elif args[:2]==['manage.py','check_production_database_vendor']: print('postgresql')
    elif args[:2]==['manage.py','verify_historical_calendar_release_b_handoff']:
        c.verify_admission(Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH']),os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_SHA256'],{'release_0078_recovery_binding_mode':'bound'})
    elif args[:2]==['manage.py','ensure_historical_calendar_recovery_intent']:
        marker=ensure_marker(); info=marker.stat()
        print(json.dumps({'marker_device':info.st_dev,'marker_inode':info.st_ino}))
    elif args[:2]==['manage.py','migrate']:
        assert args[2:]==['stable','0078_externalhorse_profile_snapshot','--noinput']
        ensure_marker()
        if not state['leaf'].startswith('stable.0078'):
            state['leaf']='stable.0078_externalhorse_profile_snapshot'; state['migration_count']+=1
            save(); event('migration-committed')
        fail('after-migration')
    elif args[:2]==['manage.py','collectstatic']:
        fail('static-before-complete')
        state['static_complete']=True; save(); event('static-complete')
    elif args[:2]==['manage.py','complete_historical_calendar_restricted_recovery']:
        assert state['static_complete']
        marker=ensure_marker(); payload,_=c.read_json(marker)
        marker.rename(marker.parent/('restricted-recovery.completed.'+payload['marker_sha256']+'.json'))
        event('schema-completed'); fail('after-schema-completion')
    else: raise SystemExit(95)
elif command == 'tasks':
    assert not any(value for name,value in state['services'].items() if name!='nginx')
    artifact,_=c.read_json(Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH']))
    c.verify_admission(Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH']), os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_SHA256'], {'release_0078_recovery_binding_mode':'bound'})
    binding=c.marker_binding(artifact)
    directory=root/'runtime/migration_history_repair'
    marker=directory/'restricted-recovery.json'
    fail('marker-before-write')
    if not marker.exists():
        payload={'schema_version':'migration-history-repair-restricted-recovery/v3', **binding,
                 'initial_leaf_set':[state['leaf']]}
        payload['marker_sha256']=c.digest(payload)
        c.publish_once(marker,payload)
    else: payload,_=c.read_json(marker)
    if not state['leaf'].startswith('stable.0078'):
        state['leaf']='stable.0078_externalhorse_profile_snapshot'; state['migration_count']+=1
        save(); event('migration-committed')
    fail('after-migration')
    fail('static-before-complete')
    state['static_complete']=True; save(); event('static-complete')
    marker.rename(directory/('restricted-recovery.completed.'+payload['marker_sha256']+'.json'))
    event('schema-completed'); fail('after-schema-completion')
elif command in ('drain','health','mount-check','runner-check'):
    event(command)
    if command == 'drain': event('drain-nodes:'+os.environ.get('EXPECTED_CELERY_WORKERS',''))
    fail(command+'-failure')
else: raise SystemExit(94)
'''


FAULT_INJECTION = r'''
import os, sys
from pathlib import Path
if os.environ.get('UMANEWS_0078_TEST_FAULTS') == '1':
    root=Path(os.environ['UMANEWS_ROOT_DIR'])
    sys.path.insert(0,str(root/'server'))
    from stable.services import release_0078_recovery as c
    original=c.publish_once
    def publish(path,payload):
        flag=root/'fault.txt'
        fault=flag.read_text() if flag.exists() else ''
        if (path.name,fault) in [('intent.json','intent-before-write'),('active.json','active-before-write')]:
            flag.unlink(); raise OSError('injected durable publication fault')
        result=original(path,payload)
        if path.name=='complete.json' and fault=='after-release-completion':
            flag.unlink(); raise OSError('injected pointer cleanup interruption')
        return result
    c.publish_once=publish
'''


class HostHarness:
    def __init__(self, root, leaf=TARGET, compose="docker-compose.prod.yml", manual=False, live_flags=False, real_control=False):
        self.root = root
        shutil.copytree(ROOT / "deploy", root / "deploy")
        (root / "server/stable/services").mkdir(parents=True)
        shutil.copy2(ROOT / "server/stable/services/release_0078_recovery.py", root / "server/stable/services/release_0078_recovery.py")
        shutil.copytree(ROOT / "server/stable/migrations", root / "server/stable/migrations")
        for path in (root / "deploy").rglob("*.sh"):
            path.chmod(0o755)
        (root / "fake-bin").mkdir()
        (root / "fault-hooks").mkdir()
        (root / "fault-hooks/sitecustomize.py").write_text(FAULT_INJECTION, encoding="utf-8")
        self.fake = root / "fake-boundaries.py"
        self.fake.write_text(FAKE_BOUNDARIES, encoding="utf-8")
        for name in ("git", "docker"):
            self.wrapper(root / "fake-bin" / name, name)
        for path, command in {
            "deploy/docker/compose-wrapper.sh": "compose", "deploy/backup_db.sh": "backup",
            "deploy/run_historical_calendar_release_b_preflight.sh": "preflight",
            "deploy/run_release_tasks.sh": "tasks", "deploy/wait_for_celery_drain.sh": "drain",
            "deploy/wait_for_compose_service_healthy.sh": "health",
        }.items():
            if real_control and command in {"preflight", "tasks"}:
                continue
            self.wrapper(root / path, command)
        self.real_control = real_control
        if real_control:
            self.wrapper(root / "fake-bin/python", "manage")
            # Only map the container's fixed /app path to this isolated root.
            # Phase order and management command argv remain the production shell.
            shell = (root / "deploy/docker/run-release-tasks.sh").read_text()
            (root / "fake-control-release.sh").write_text(shell.replace("/app/server", str(root / "server")).replace("/app/deploy/", str(root / "deploy") + "/"))
        self.repair = root / "runtime/migration_history_repair"
        self.repair.mkdir(mode=0o700, parents=True)
        self.restore = {name: name in {"nginx"} if manual else name in {"web", "worker", "beat", "race_sync_v2_worker", "nginx"} for name in SERVICES}
        flags = {name: "true" if live_flags and name.startswith("RACE_DATA_SYNC_") else "false" for name in WRITER_FLAGS}
        (root / "test-state.json").write_text(json.dumps({"leaf": leaf, "database_identity": DB, "services": self.restore, "compose_services": list(SERVICES), "migration_count": 0, "static_complete": False,
                                                       "flags": flags, "real_control": real_control}))
        (root / ".env").write_text("# synthetic closed writer flags\n")
        self.env = {**os.environ, **flags,
                    "UMANEWS_ROOT_DIR": str(root), "COMPOSE_FILE": compose, "COMPOSE_PROJECT_NAME": "isolated0078",
                    "EXPECTED_CANDIDATE_COMMIT": COMMIT, "EXPECTED_CANDIDATE_IMAGE_ID": IMAGE,
                    "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": DB, "EXPECTED_COMPOSE_PROJECT": "isolated0078",
                    "RELEASE_B_PREFLIGHT_ACTION": "manual-release" if manual else "deploy", "RESTRICTED_RECOVERY_ATTEMPT_MODE": "required",
                    "DEPLOYMENT_LOCK_DIR": str(root / "deployment.lock"), "DEPLOYMENT_LOCK_TOKEN": "original-test-lease",
                    "PATH": str(root / "fake-bin") + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(root / "fault-hooks"), "UMANEWS_0078_TEST_FAULTS": "1"}
        origin_dir = self.repair / "preflight/original"
        origin_dir.parent.mkdir(mode=0o700)
        origin_dir.mkdir(mode=0o700)
        self.origin_path = origin_dir / "preflight.json"
        payload = {"schema_version": "migration-history-repair-preflight/v5", "target_leaf_set": [TARGET],
                   "migration_contract_sha256": "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906",
                   "candidate_commit": COMMIT, "candidate_image_id": IMAGE, "database_identity_sha256": DB,
                   "compose_file": compose, "artifact_path": str(self.origin_path),
                   "deployment_lock_token_sha256": hashlib.sha256(b"original-test-lease").hexdigest(),
                   "handoff_action": "manual-release" if manual else "deploy", "release_0078_recovery_binding_mode": "admission-only",
                   "recovery_intent_mode": "required", "writer_activity": {"ok": True, "counts": {}, "flags": {name: "false" for name in WRITER_FLAGS}},
                   "preflight": {"ok": True, "database_identity_sha256": DB, "migration_leaf_set": [leaf], "migration_plan": [] if leaf == TARGET else ["0078_externalhorse_profile_snapshot"]}}
        self.origin_sha = contract.digest(payload)
        payload["artifact_sha256"] = self.origin_sha
        contract.publish_once(self.origin_path, payload)
        self.env.update(RELEASE_B_PREFLIGHT_ARTIFACT_PATH=str(self.origin_path), RELEASE_B_PREFLIGHT_ARTIFACT_SHA256=self.origin_sha)
        self.directory = self.repair / "release-0078-recovery" / self.origin_sha

    def wrapper(self, path, command):
        path.write_text('#!/bin/sh\nexec "' + sys.executable + '" "' + str(self.fake) + '" ' + command + ' "$@"\n', encoding="utf-8")
        path.chmod(0o755)

    def command(self, argv, env=None):
        return subprocess.run(argv, cwd=self.root, env=env or self.env, text=True, capture_output=True, timeout=60)

    def initial(self, fault="", *, entrypoint=None):
        if fault:
            (self.root / "fault.txt").write_text(fault)
        acquire = self.command(["sh", "deploy/deployment_lock.sh", "acquire"], {**self.env, "DEPLOYMENT_LOCK_ACTION": "deploy"})
        if acquire.returncode:
            raise AssertionError(acquire.stderr)
        try:
            if self.real_control:
                self.origin_path.unlink()
                admission = self.command(["sh", "deploy/run_historical_calendar_release_b_preflight.sh"])
                if admission.returncode:
                    return admission
                self.origin_sha = contract.read_json(self.origin_path)[0]["artifact_sha256"]
                self.env["RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"] = self.origin_sha
                self.directory = self.repair / "release-0078-recovery" / self.origin_sha
            result = self.command(entrypoint or [sys.executable, "deploy/release_0078.py", "release"])
            if fault and (self.root / "fault.txt").exists():
                raise AssertionError("injected stage was not reached: " + fault + "\n" + result.stdout + result.stderr)
            return result
        finally:
            self.command(["sh", "deploy/deployment_lock.sh", "release"])

    def resume(self, **changes):
        env = {**self.env, **changes}
        intent = self.directory / "intent.json"
        if intent.exists():
            env.update(RELEASE_0078_INTENT_PATH=str(intent), RELEASE_0078_INTENT_SHA256=contract.read_json(intent)[1]["sha256"])
        else:
            env["RELEASE_0078_RECOVERY_MANIFEST_SHA256"] = contract.read_json(self.directory / "manifest.json")[1]["sha256"]
        return self.command(["sh", "deploy/resume_migration_history_repair.sh"], env)

    def events(self):
        path = self.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def state(self):
        return json.loads((self.root / "test-state.json").read_text())

    def top_level(self, entrypoint):
        # These two existing components have independent real-shell tests.
        # Here their successful boundary lets the current top-level script,
        # lock, admission, coordinator and recovery artifacts run together.
        self.wrapper(self.root/'deploy/verify_persistent_release_mounts.sh','mount-check')
        self.wrapper(self.root/'deploy/historical_runner_preflight.sh','runner-check')
        return self.command(['sh',entrypoint])


class Release0078ControlEnvironmentTests(TestCase):
    def test_schema_one_shot_disarms_enabled_flags_without_changing_host(self):
        spec = importlib.util.spec_from_file_location("release_0078_environment_test", ROOT / "deploy/release_0078.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = {name: "true" if name.startswith("RACE_DATA_SYNC_") else "false" for name in WRITER_FLAGS}
        env = {**original, "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": DB}
        observed = []

        def compose(args, host_env):
            # Model Docker's run -e precedence over the service environment;
            # inspecting host_env alone would miss the intended process boundary.
            effective = dict(original)
            for index, value in enumerate(args[:-1]):
                if value == "-e":
                    name, value = args[index + 1].split("=", 1)
                    effective[name] = value
            observed.append({name: effective[name] for name in WRITER_FLAGS})
            self.assertEqual({name: host_env[name] for name in WRITER_FLAGS}, original)
            return json.dumps({"ok": True, "database_identity_sha256": DB, "migration_leaf_set": [TARGET]})

        with patch.object(module, "candidate"), patch.object(module, "compose", side_effect=compose):
            module.schema_state(env, TARGET)
        self.assertEqual(observed, [{name: "false" for name in WRITER_FLAGS}])
        self.assertEqual({name: env[name] for name in WRITER_FLAGS}, original)


@skipUnless(os.name == "posix", "requires real Linux shell, POSIX permissions and locks")
class Release0078EntrypointTests(TestCase):
    def harness(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return HostHarness(Path(tmp.name), **kwargs)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_closed_control_chain(self, harness):
        calls = [json.loads(event.removeprefix("one-shot-env:")) for event in harness.events() if event.startswith("one-shot-env:")]
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call["flags"], {name: "false" for name in WRITER_FLAGS}, call["command"])
        commands = [json.loads(event.removeprefix("control-env:"))["command"] for event in harness.events() if event.startswith("control-env:")]
        phases = [command[1] for command in commands if command[0] == "manage.py"]
        expected = ["check_production_database_vendor", "verify_historical_calendar_release_b_handoff",
                    "ensure_historical_calendar_recovery_intent", "migrate", "collectstatic",
                    "complete_historical_calendar_restricted_recovery"]
        self.assertEqual(phases[-len(expected):], expected)
        for event in harness.events():
            if event.startswith("control-env:"):
                call = json.loads(event.removeprefix("control-env:"))
                self.assertEqual(call["flags"], {name: "false" for name in WRITER_FLAGS}, call["command"])

    def test_live_flags_release_preserves_enabled_services_and_disarms_full_control_chain(self):
        for leaf, compose in ((TARGET, "docker-compose.prod.yml"), (SOURCE, "docker-compose.prod.lowcost.yml")):
            with self.subTest(leaf=leaf, compose=compose):
                harness = self.harness(leaf=leaf, compose=compose, live_flags=True, real_control=True)
                original = harness.state()["flags"]
                env_bytes = (harness.root / ".env").read_bytes()
                self.assertEqual(sum(value == "true" for value in original.values()), 10)
                self.assert_success(harness.initial())
                manifest = contract.read_json(harness.directory / "manifest.json")[0]
                origin = contract.read_json(harness.origin_path)[0]
                self.assertEqual(manifest["writer_flags"], original)
                self.assertEqual(origin["writer_activity"]["flags"], {name: "false" for name in WRITER_FLAGS})
                self.assertEqual((harness.root / ".env").read_bytes(), env_bytes)
                self.assertEqual({name: harness.env[name] for name in WRITER_FLAGS}, original)
                self.assertEqual(harness.state()["services"], harness.restore)
                for service, flags in harness.state()["container_flags"].items():
                    if service != "nginx":
                        self.assertEqual(flags, original)
                self.assertEqual(harness.state()["migration_count"], int(leaf == SOURCE))
                self.assert_closed_control_chain(harness)

    def test_live_flags_resume_reuses_enabled_intent_after_stop_static_and_receipt_failures(self):
        for fault in ("after-first-stop", "static-before-complete", "after-schema-completion"):
            with self.subTest(fault=fault):
                harness = self.harness(leaf=SOURCE, live_flags=True, real_control=True)
                self.assertNotEqual(harness.initial(fault).returncode, 0)
                original = harness.state()["flags"]
                frozen = {name: (harness.directory / name).read_bytes() for name in ("intent.json", "manifest.json")}
                self.assert_success(harness.resume())
                self.assertEqual({name: (harness.directory / name).read_bytes() for name in frozen}, frozen)
                self.assertEqual(harness.state()["services"], harness.restore)
                self.assertEqual(harness.state()["migration_count"], 1)
                self.assertEqual(harness.events().count("backup-created"), 1)
                self.assertEqual(contract.read_json(harness.directory / "manifest.json")[0]["writer_flags"], original)
                self.assert_closed_control_chain(harness)

    def test_live_flags_container_environment_drift_blocks_preparation_and_later_writers(self):
        for phase in ("prepare", "already-running", "new-web"):
            with self.subTest(phase=phase):
                harness = self.harness(live_flags=True, real_control=True)
                if phase != "prepare":
                    self.assertNotEqual(harness.initial("after-schema-completion").returncode, 0)
                state = harness.state()
                drift = {**state["flags"], "RACE_DATA_SYNC_ALLOW_NETWORK": "false"}
                if phase == "new-web":
                    state["start_flag_overrides"] = {"web": drift}
                else:
                    state["container_flags"] = {"web": drift}
                    state["services"]["web"] = True
                (harness.root / "test-state.json").write_text(json.dumps(state))
                result = harness.initial() if phase == "prepare" else harness.resume()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("writer flags differ", result.stderr)
                starts = [event for event in harness.events() if event.startswith("start-after-")]
                self.assertEqual(starts, ["start-after-completion:web"] if phase == "new-web" else [])
                self.assertFalse((harness.directory / "complete.json").exists())
                if phase == "prepare":
                    self.assertNotIn("backup-created", harness.events())
                    self.assertFalse(any(event.startswith("stop-") for event in harness.events()))

    def test_live_flags_compose_override_cannot_change_frozen_enabled_resume_state(self):
        harness = self.harness(live_flags=True, real_control=True)
        self.assertNotEqual(harness.initial("after-schema-completion").returncode, 0)
        env_bytes = (harness.root / ".env").read_bytes()
        result = harness.resume(RACE_DATA_SYNC_ALLOW_NETWORK="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("writer flags differ", result.stderr)
        self.assertEqual((harness.root / ".env").read_bytes(), env_bytes)
        self.assertFalse(any(event.startswith("start-after-") for event in harness.events()))
        self.assertFalse((harness.directory / "complete.json").exists())

    def test_same_schema_and_upgrade_both_compose_modes_require_new_backup(self):
        for leaf in (SOURCE, TARGET):
            for compose in ("docker-compose.prod.yml", "docker-compose.prod.lowcost.yml"):
                with self.subTest(leaf=leaf, compose=compose):
                    harness = self.harness(leaf=leaf, compose=compose)
                    self.assert_success(harness.initial())
                    self.assertEqual(harness.events().count("backup-created"), 1)
                    self.assertEqual(harness.state()["migration_count"], int(leaf == SOURCE))
                    self.assertEqual(harness.state()["services"], harness.restore)
                    self.assertFalse((harness.directory.parent / "active.json").exists())

    def test_backup_failure_never_stops_a_service(self):
        for compose in ("docker-compose.prod.yml", "docker-compose.prod.lowcost.yml"):
            with self.subTest(compose=compose):
                harness = self.harness(compose=compose)
                self.assertNotEqual(harness.initial("backup-before-write").returncode, 0)
                self.assertFalse(any(event.startswith("stop-") for event in harness.events()))
                self.assertEqual(harness.state()["services"], harness.restore)

    def test_backup_path_with_spaces_survives_real_coordinator_arguments(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / 'release with spaces'
        root.mkdir(mode=0o700)
        harness = HostHarness(root)
        self.assert_success(harness.initial())
        manifest = json.loads((harness.directory / 'manifest.json').read_text())
        self.assertIn('release with spaces', manifest['backup_path'])
        self.assertTrue(Path(manifest['backup_path']).is_file())
        self.assertEqual(harness.events().count('backup-created'), 1)

    def test_database_drift_after_stop_blocks_migration_and_all_writer_restart(self):
        harness = self.harness(leaf=SOURCE)
        state = harness.state()
        state['closed_database_identity'] = 'f' * 64
        (harness.root / 'test-state.json').write_text(json.dumps(state))
        result = harness.initial()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('handoff binding mismatch', result.stderr)
        events = harness.events()
        self.assertLess(events.index('stop-with-verified-intent:web'), events.index('closed-database-drift'))
        self.assertEqual(harness.state()['migration_count'], 0)
        self.assertFalse((harness.repair / 'restricted-recovery.json').exists())
        self.assertFalse(any(event.startswith('start-after-') for event in events))
        self.assertTrue((harness.directory.parent / 'active.json').exists())

    def test_replaced_v3_completion_receipt_is_rejected_by_real_resume(self):
        harness = self.harness()
        self.assertNotEqual(harness.initial('after-schema-completion').returncode, 0)
        receipt = next(harness.repair.glob('restricted-recovery.completed.*.json'))
        original_inode = receipt.stat().st_ino
        payload = json.loads(receipt.read_text())
        self.assertEqual(payload['schema_version'], 'migration-history-repair-restricted-recovery/v3')
        receipt.rename(receipt.with_suffix('.preserved'))
        payload['marker_sha256'] = '0' * 64
        receipt.write_bytes(contract.encoded(payload))
        receipt.chmod(0o600)
        self.assertNotEqual(receipt.stat().st_ino, original_inode)
        before = [event for event in harness.events() if event.startswith('start-after-')]
        result = harness.resume()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('completion receipt is invalid', result.stderr)
        self.assertEqual([event for event in harness.events() if event.startswith('start-after-')], before)
        self.assertFalse((harness.directory / 'complete.json').exists())
        self.assertTrue((harness.directory.parent / 'active.json').exists())

    def test_manual_stopped_service_intent_is_preserved(self):
        for compose in ("docker-compose.prod.yml", "docker-compose.prod.lowcost.yml"):
            with self.subTest(compose=compose):
                harness = self.harness(manual=True, compose=compose)
                self.assert_success(harness.initial())
                self.assertEqual(harness.events().count("backup-created"), 1)
                self.assertFalse(any(event.startswith("start-") for event in harness.events()))

    def test_t35_to_t41_real_resume_entry_replays_each_durable_boundary(self):
        faults = ("intent-before-write", "active-before-write", "after-first-stop", "closed-before-write",
                  "marker-before-write", "after-migration", "static-before-complete", "after-schema-completion",
                  "after-service-start", "after-release-completion")
        for leaf in (SOURCE, TARGET):
            for fault in faults:
                with self.subTest(leaf=leaf, fault=fault):
                    harness = self.harness(leaf=leaf)
                    initial = harness.initial(fault)
                    self.assertNotEqual(initial.returncode, 0, "fault did not execute: " + fault)
                    initial_state = harness.state()
                    if fault in {"intent-before-write", "active-before-write"}:
                        self.assertEqual(initial_state["services"], harness.restore)
                    if fault in {"closed-before-write", "marker-before-write", "after-migration", "static-before-complete", "after-schema-completion"}:
                        self.assertFalse(any(v for k, v in initial_state["services"].items() if k != "nginx"))
                    intent_path = harness.directory / "intent.json"
                    before = intent_path.read_bytes() if intent_path.exists() else None
                    self.assert_success(harness.resume())
                    if before is not None:
                        self.assertEqual(intent_path.read_bytes(), before)
                    self.assertEqual(harness.events().count("backup-created"), 1)
                    self.assertEqual(harness.state()["migration_count"], int(leaf == SOURCE))
                    self.assertEqual(harness.state()["services"], harness.restore)
                    self.assertFalse((harness.directory.parent / "active.json").exists())
                    self.assertFalse((harness.root / "deployment.lock").exists())

    def test_t42_new_release_refused_original_intent_resumes_with_new_lock(self):
        harness = self.harness()
        self.assertNotEqual(harness.initial("after-first-stop").returncode, 0)
        events = list(harness.events())
        blocked = harness.command([sys.executable, "deploy/release_0078.py", "guard"])
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(harness.events(), events)
        self.assert_success(harness.resume())
        self.assertEqual(contract.read_json(harness.directory / "intent.json")[0]["initial_lock_sha256"], hashlib.sha256(b"original-test-lease").hexdigest())

    def test_legacy_optional_worker_intent_blocks_guard_and_new_release(self):
        for suffix in (".race-live-state", ".race-data-sync-state"):
            for symlink in (False, True):
                with self.subTest(suffix=suffix, symlink=symlink):
                    harness = self.harness(leaf=SOURCE)
                    path = Path(harness.env["DEPLOYMENT_LOCK_DIR"] + suffix)
                    if symlink:
                        path.symlink_to(harness.root / "missing-old-intent")
                    else:
                        path.write_bytes(b"state=running\naction=deploy\n")
                        path.chmod(0o600)
                    guarded = harness.command([sys.executable, "deploy/release_0078.py", "guard"])
                    self.assertNotEqual(guarded.returncode, 0)
                    self.assertNotEqual(harness.initial().returncode, 0)
                    self.assertFalse(any(event.startswith(("stop-", "backup-created")) for event in harness.events()))
                    self.assertTrue(os.path.lexists(path))
                    if not symlink:
                        self.assertEqual(path.read_bytes(), b"state=running\naction=deploy\n")

    def test_legacy_intent_appearing_during_0078_attempt_blocks_resume(self):
        for suffix in (".race-live-state", ".race-data-sync-state"):
            with self.subTest(suffix=suffix):
                harness = self.harness()
                self.assertNotEqual(harness.initial("after-first-stop").returncode, 0)
                path = Path(harness.env["DEPLOYMENT_LOCK_DIR"] + suffix)
                path.write_bytes(b"state=running\naction=deploy\n")
                path.chmod(0o600)
                before = harness.state()
                self.assertNotEqual(harness.resume().returncode, 0)
                self.assertEqual(harness.state(), before)
                self.assertEqual(path.read_bytes(), b"state=running\naction=deploy\n")

    def test_resume_rejects_wrong_running_application_image_before_more_writers(self):
        for service in ("web", "worker", "beat", "race_sync_v2_worker"):
            with self.subTest(service=service):
                harness = self.harness()
                self.assertNotEqual(harness.initial("after-schema-completion").returncode, 0)
                state = harness.state()
                state["services"][service] = True
                state["images"] = {service: "sha256:" + "0" * 64}
                (harness.root / "test-state.json").write_text(json.dumps(state))
                before = [event for event in harness.events() if event.startswith("start-")]
                result = harness.resume()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual([event for event in harness.events() if event.startswith("start-")], before)
                self.assertFalse((harness.directory / "complete.json").exists())

    def test_new_web_with_wrong_actual_image_blocks_later_writer_start(self):
        harness = self.harness()
        self.assertNotEqual(harness.initial("after-schema-completion").returncode, 0)
        state = harness.state()
        state["start_image_overrides"] = {"web": "sha256:" + "0" * 64}
        (harness.root / "test-state.json").write_text(json.dumps(state))
        self.assertNotEqual(harness.resume().returncode, 0)
        self.assertEqual([event for event in harness.events() if event.startswith("start-")], ["start-after-completion:web"])
        self.assertFalse((harness.directory / "complete.json").exists())

    def test_resolved_writer_flag_override_blocks_resume_despite_unchanged_env_file(self):
        for flag in ("RACE_LIVE_SCHEDULER_ENABLED", "RACE_DATA_SYNC_RESULT_APPLY_ENABLED"):
            with self.subTest(flag=flag):
                harness = self.harness()
                self.assertNotEqual(harness.initial("after-schema-completion").returncode, 0)
                env_bytes = (harness.root / ".env").read_bytes()
                before = [event for event in harness.events() if event.startswith("start-")]
                self.assertNotEqual(harness.resume(**{flag: "true"}).returncode, 0)
                self.assertEqual((harness.root / ".env").read_bytes(), env_bytes)
                self.assertEqual([event for event in harness.events() if event.startswith("start-")], before)
                self.assertFalse((harness.directory / "complete.json").exists())

    def test_resolved_writer_flag_override_blocks_initial_stop(self):
        harness = self.harness()
        harness.env["RACE_LIVE_SCHEDULER_ENABLED"] = "true"
        self.assertNotEqual(harness.initial().returncode, 0)
        self.assertFalse(any(event.startswith("stop-") for event in harness.events()))
        self.assertEqual(harness.state()["services"], harness.restore)

    def test_compose_project_override_cannot_resume_another_service_group(self):
        harness = self.harness()
        self.assertNotEqual(harness.initial("after-schema-completion").returncode, 0)
        before = [event for event in harness.events() if event.startswith("start-")]
        self.assertNotEqual(harness.resume(COMPOSE_PROJECT_NAME="otherproject").returncode, 0)
        self.assertEqual([event for event in harness.events() if event.startswith("start-")], before)
        self.assertFalse((harness.directory / "complete.json").exists())

    def test_replaced_backup_and_wrong_candidate_block_resume_before_more_stops(self):
        for mutation in ("backup", "candidate"):
            with self.subTest(mutation=mutation):
                harness = self.harness()
                self.assertNotEqual(harness.initial("after-first-stop").returncode, 0)
                before = [event for event in harness.events() if event.startswith("stop-")]
                if mutation == "backup":
                    path = harness.directory / "backup/test.dump"
                    path.write_bytes(b"replaced")
                    result = harness.resume()
                else:
                    result = harness.resume(EXPECTED_CANDIDATE_COMMIT="e" * 40)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual([event for event in harness.events() if event.startswith("stop-")], before)

    def test_valid_manifest_source_must_match_original_admission_source(self):
        harness = self.harness(leaf=TARGET)
        self.assertNotEqual(harness.initial("intent-before-write").returncode, 0)
        manifest_path = harness.directory / "manifest.json"
        manifest, _ = contract.read_json(manifest_path)
        # Each field is independently valid, but this pair belongs to an
        # upgrade while the immutable origin admitted same-schema 0078.
        manifest.update(source_leaf=SOURCE, operation="upgrade")
        manifest_path.write_bytes(contract.encoded(manifest))
        self.assertNotEqual(harness.resume().returncode, 0)
        self.assertFalse(any(event.startswith("stop-") for event in harness.events()))
        self.assertEqual(harness.state()["services"], harness.restore)

    def test_real_default_rollback_scripts_refuse_before_mutations(self):
        for script in ("rollback.sh", "rollback_lowcost.sh"):
            with self.subTest(script=script):
                harness = self.harness()
                result = harness.command(["sh", "deploy/" + script, "b" * 40])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("generic application rollback is disabled", result.stderr)
                events = harness.events()
                self.assertFalse(any(event.startswith(("git:checkout", "docker:", "compose:", "backup-", "stop-")) for event in events), events)
