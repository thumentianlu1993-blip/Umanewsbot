"""真实 host coordinator/resume/锁与文件权限；Docker 边界使用离线替身。

这些测试不把 fake migration 当数据库证明。真实 DDL 与恢复另由 PG16 套件执行。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless

from stable.services import release_0078_recovery as contract


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "stable.0077_racing_api_horse_identity_staging"
TARGET = "stable.0078_externalhorse_profile_snapshot"
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64
DB = "d" * 64
SERVICES = ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")


FAKE_BOUNDARIES = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
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
        else:
            running = state['services'][service]
            print(('true running ' if running else 'false exited ') + 'node-'+service)
    elif args[:1] == ['run'] and 'pg_restore' in args: print('synthetic custom dump TOC')
    else: raise SystemExit(92)
elif command == 'compose':
    while args and args[0] in ('-f', '--project-name'): args=args[2:]
    event('compose:'+' '.join(args))
    if args[0] == 'ps':
        service = args[-1]
        if service in state['services']: print('cid-'+service)
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
        save(); event('start-after-completion:'+args[-1]); fail('after-service-start')
    elif args[0] == 'exec':
        if 'pg_restore' in args: print('synthetic custom dump TOC')
        else: assert args[-2:] == ['-s','reload']
    elif args[0] == 'run' and 'check_historical_calendar_release_b_schema' in args:
        print(json.dumps({'ok': True, 'migration_leaf_set':[state['leaf']], 'database_identity_sha256':os.environ['EXPECTED_PRODUCTION_DB_IDENTITY_SHA256']}))
    else: raise SystemExit(93)
elif command == 'backup':
    fail('backup-before-write')
    path=Path(os.environ['BACKUP_DIR'])/'test.dump'
    assert not path.exists()
    path.write_bytes(b'new synthetic backup for this release'); path.chmod(0o600)
    event('backup-created'); print('Backup created: '+str(path))
elif command == 'preflight':
    assert not any(value for name,value in state['services'].items() if name!='nginx')
    fail('closed-before-write')
    path=Path(os.environ['RELEASE_B_PREFLIGHT_ARTIFACT_PATH'])
    payload={'schema_version':'migration-history-repair-preflight/v5',
        'target_leaf_set':['stable.0078_externalhorse_profile_snapshot'],
        'migration_contract_sha256':c.migration_contract(),
        'candidate_commit':os.environ['EXPECTED_CANDIDATE_COMMIT'],
        'candidate_image_id':os.environ['EXPECTED_CANDIDATE_IMAGE_ID'],
        'database_identity_sha256':os.environ['EXPECTED_PRODUCTION_DB_IDENTITY_SHA256'],
        'compose_file':os.environ['COMPOSE_FILE'], 'artifact_path':str(path),
        'deployment_lock_token_sha256':hashlib.sha256(os.environ['DEPLOYMENT_LOCK_TOKEN'].encode()).hexdigest(),
        'handoff_action':'forward-resume', 'release_0078_recovery_binding_mode':'bound',
        'writer_activity':{'ok':True,'counts':{},'flags':{}},
        'preflight':{'ok':True,'database_identity_sha256':os.environ['EXPECTED_PRODUCTION_DB_IDENTITY_SHA256'],'migration_leaf_set':[state['leaf']], 'migration_plan':[] if state['leaf'].startswith('stable.0078') else ['0078_externalhorse_profile_snapshot']},
        **{key:os.environ[key.upper()] for key in c.BINDING_FIELDS}}
    payload['artifact_sha256']=c.digest(payload)
    c.publish_once(path,payload); event('closed-written')
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
elif command in ('drain','health'):
    event(command)
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
    def __init__(self, root, leaf=TARGET, compose="docker-compose.prod.yml", manual=False):
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
            self.wrapper(root / path, command)
        self.repair = root / "runtime/migration_history_repair"
        self.repair.mkdir(mode=0o700, parents=True)
        self.restore = {name: name in {"nginx"} if manual else name in {"web", "worker", "beat", "race_sync_v2_worker", "nginx"} for name in SERVICES}
        (root / "test-state.json").write_text(json.dumps({"leaf": leaf, "services": self.restore, "migration_count": 0, "static_complete": False}))
        (root / ".env").write_text("# synthetic closed writer flags\n")
        self.env = {**os.environ, "UMANEWS_ROOT_DIR": str(root), "COMPOSE_FILE": compose,
                    "EXPECTED_CANDIDATE_COMMIT": COMMIT, "EXPECTED_CANDIDATE_IMAGE_ID": IMAGE,
                    "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": DB, "EXPECTED_COMPOSE_PROJECT": "isolated0078",
                    "DEPLOYMENT_LOCK_DIR": str(root / "deployment.lock"), "DEPLOYMENT_LOCK_TOKEN": "original-test-lease",
                    "PATH": str(root / "fake-bin") + os.pathsep + os.environ["PATH"],
                    "PYTHONPATH": str(root / "fault-hooks"), "UMANEWS_0078_TEST_FAULTS": "1"}
        origin_dir = self.repair / "preflight/original"
        origin_dir.mkdir(mode=0o700, parents=True)
        self.origin_path = origin_dir / "preflight.json"
        payload = {"schema_version": "migration-history-repair-preflight/v5", "target_leaf_set": [TARGET],
                   "migration_contract_sha256": "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906",
                   "candidate_commit": COMMIT, "candidate_image_id": IMAGE, "database_identity_sha256": DB,
                   "compose_file": compose, "artifact_path": str(self.origin_path),
                   "deployment_lock_token_sha256": hashlib.sha256(b"original-test-lease").hexdigest(),
                   "handoff_action": "manual-release" if manual else "deploy", "release_0078_recovery_binding_mode": "admission-only",
                   "recovery_intent_mode": "required", "writer_activity": {"ok": True, "counts": {}, "flags": {}},
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

    def initial(self, fault=""):
        if fault:
            (self.root / "fault.txt").write_text(fault)
        acquire = self.command(["sh", "deploy/deployment_lock.sh", "acquire"], {**self.env, "DEPLOYMENT_LOCK_ACTION": "deploy"})
        if acquire.returncode:
            raise AssertionError(acquire.stderr)
        try:
            return self.command([sys.executable, "deploy/release_0078.py", "release"])
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


@skipUnless(os.name == "posix", "requires real Linux shell, POSIX permissions and locks")
class Release0078EntrypointTests(TestCase):
    def harness(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return HostHarness(Path(tmp.name), **kwargs)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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

    def test_real_default_rollback_scripts_refuse_before_mutations(self):
        for script in ("rollback.sh", "rollback_lowcost.sh"):
            with self.subTest(script=script):
                harness = self.harness()
                result = harness.command(["sh", "deploy/" + script, "b" * 40])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("generic application rollback is disabled", result.stderr)
                events = harness.events()
                self.assertFalse(any(event.startswith(("git:checkout", "docker:", "compose:", "backup-", "stop-")) for event in events), events)
