"""宿主状态机故障注入；物理DDL/恢复由独立PG与镜像演练验证。"""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stable.services import release_p02_recovery as c

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p02_coordinator_tests", ROOT / "deploy/release_p02.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class Crash(RuntimeError):
    pass


class FakeRuntime:
    """明确模拟服务/镜像；不能据此生成真实生产或Docker验收声明。"""
    def __init__(self, directory, plan):
        self.directory, self.plan = directory, plan
        self.events, self.prefix = [], 0
        self.services = {s: s in {"web", "worker", "beat", "nginx"} for s in host.SERVICES}
        self.source = {"counts_sha256": "1" * 64, "catalog_sha256": "2" * 64, "security_sha256": "3" * 64}
        self.static = {"file_count": 5, "sha256": "4" * 64}
        self.fail_on = ""

    def mark(self, event):
        self.events.append(event)
        if self.fail_on == event:
            raise Crash(event)

    def verify(self):
        self.mark("verify")

    def verify_rehearsal(self):
        self.mark("verify_rehearsal")

    def guard_legacy(self):
        self.mark("guard_legacy")

    def snapshot(self):
        self.mark("snapshot")
        return {**self.plan, **self.source, "prefix": self.prefix, "services": dict(self.services), "old_image_ids": ["sha256:" + "5" * 64]}

    def ensure_marker(self, sha):
        self.mark("ensure_marker")
        self.intent_sha = sha

    def clear_marker(self, sha):
        self.mark("clear_marker")

    def close(self, intent):
        self.mark("close")
        self.services = {s: s == "nginx" for s in host.SERVICES}

    emergency_close = close

    def closed_snapshot(self):
        self.mark("closed_snapshot")
        return {**self.source, "prefix": self.prefix}

    def backup_and_restore(self, intent, closed):
        self.mark("backup_and_restore")
        directory = c.private_directory(self.directory / "backup")
        files = {}
        for name in ("database.dump", "roles.sql", "config.tar", "assets.tar", "images.tar"):
            path = directory / name
            path.write_bytes(b"synthetic coordinator test")
            path.chmod(0o600)
            files[name] = c.file_evidence(path)[1]
        return {"files": files, "restore": {"status": "verified", **self.source, "database_identity_sha256": "6" * 64}}

    def apply_schema(self, intent_sha):
        self.mark("apply_schema")
        self.prefix = 6
        c.write_artifact(self.directory / "schema-complete.json", kind="schema-complete", intent_sha=intent_sha,
            catalog_sha256="7" * 64, recorder_sha256="8" * 64, target=c.STEPS[-1])

    def collect_static(self):
        self.mark("collect_static")
        return dict(self.static)

    def verify_static(self, evidence):
        self.mark("verify_static")
        if any(evidence.get(key) != value for key, value in self.static.items()):
            raise ValueError("static changed")

    def verify_schema_complete(self, evidence):
        self.mark("verify_schema_complete")
        if self.prefix != 6:
            raise ValueError("schema changed")

    def readonly_probe(self, intent):
        self.mark("readonly_probe")
        return {"ok": True, "paths": ["/healthz/", "/races/"]}

    def restore_services(self, intent):
        self.services["web"] = True
        self.mark("restore_services")
        self.services = dict(intent["restore_services"])

    def verify_restored(self, intent):
        self.mark("verify_restored")
        if self.services != intent["restore_services"]:
            raise ValueError("wrong services")


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.directory.chmod(0o700)
        self.plan = {"schema_version": c.VERSION, "kind": "plan", "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64, "database_identity_sha256": "c" * 64,
            "config_sha256": "d" * 64, "migration_contract_sha256": c.migration_contract()}
        self.runtime = FakeRuntime(self.directory, self.plan)
        self.coordinator = host.Coordinator(self.directory, self.plan, "f" * 64, self.runtime)

    def tearDown(self):
        self.temp.cleanup()

    def intent_sha(self):
        return c.read_json(self.directory / "intent.json")[1]["sha256"]

    def test_backup_restore_and_static_probes_precede_normal_service_restart(self):
        result = self.coordinator.run()
        self.assertEqual(result["status"], "restored")
        actions = [x for x in self.runtime.events if x != "verify"]
        for before, after in (("close", "backup_and_restore"), ("backup_and_restore", "apply_schema"),
                              ("apply_schema", "collect_static"), ("readonly_probe", "restore_services"),
                              ("verify_restored", "clear_marker")):
            self.assertLess(actions.index(before), actions.index(after))
        self.assertTrue((self.directory / "complete.json").exists())
        self.assertTrue((self.directory / "restored.json").exists())

    def test_every_checkpoint_resumes_same_intent_without_replacing_backup(self):
        # 每个子案例使用独立目录/runtime，不复用前一个案例的完成态。
        for stage in ("intent", "stopped", "closed", "backup", "handoff", "schema", "static", "probe", "complete", "restoring", "restored"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw).resolve()
                directory.chmod(0o700)
                runtime = FakeRuntime(directory, self.plan)
                coordinator = host.Coordinator(directory, self.plan, "f" * 64, runtime)
                def crash(observed):
                    if observed == stage:
                        raise Crash(stage)
                with self.assertRaises(Crash):
                    coordinator.run(checkpoint=crash)
                sha = c.read_json(directory / "intent.json")[1]["sha256"]
                backup = directory / "backup.json"
                backup_before = c.read_json(backup)[1] if backup.exists() else None
                coordinator.run(resume_sha=sha)
                self.assertEqual(c.read_json(directory / "intent.json")[1]["sha256"], sha)
                if backup_before:
                    self.assertEqual(c.read_json(backup)[1], backup_before)

    def test_static_failure_cannot_sign_complete_or_start_normal_services(self):
        self.runtime.fail_on = "collect_static"
        with self.assertRaises(Crash):
            self.coordinator.run()
        self.assertFalse((self.directory / "complete.json").exists())
        self.assertNotIn("restore_services", self.runtime.events)
        self.runtime.fail_on = ""
        self.coordinator.run(resume_sha=self.intent_sha())

    def test_partial_restore_failure_stops_applications_and_preserves_completion(self):
        self.runtime.fail_on = "restore_services"
        with self.assertRaises(Crash):
            self.coordinator.run()
        self.assertTrue((self.directory / "complete.json").exists())
        self.assertFalse((self.directory / "restored.json").exists())
        self.assertFalse(self.runtime.services["web"])
        self.runtime.fail_on = ""
        self.coordinator.run(resume_sha=self.intent_sha())

    def test_rehearsal_failure_never_stops_or_prepares_production(self):
        self.runtime.fail_on = "verify_rehearsal"
        with self.assertRaises(Crash):
            self.coordinator.run()
        self.assertFalse((self.directory / "intent.json").exists())
        self.assertTrue(self.runtime.services["web"])

    def test_resume_requires_original_sha(self):
        self.coordinator.run()
        with self.assertRaisesRegex(ValueError, "original intent SHA"):
            self.coordinator.run()
        with self.assertRaises(ValueError):
            self.coordinator.run(resume_sha="0" * 64)

    def test_completed_schema_does_not_allow_changed_static_before_restart(self):
        def crash(stage):
            if stage == "complete":
                raise Crash(stage)
        with self.assertRaises(Crash):
            self.coordinator.run(checkpoint=crash)
        self.runtime.static["sha256"] = "9" * 64
        self.runtime.events.clear()
        with self.assertRaisesRegex(ValueError, "static changed"):
            self.coordinator.run(resume_sha=self.intent_sha())
        self.assertNotIn("restore_services", self.runtime.events)

    def test_resume_after_backup_rejects_changed_source_cut(self):
        def crash(stage):
            if stage == "backup":
                raise Crash(stage)
        with self.assertRaises(Crash):
            self.coordinator.run(checkpoint=crash)
        self.runtime.source["counts_sha256"] = "0" * 64
        self.runtime.events.clear()
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.coordinator.run(resume_sha=self.intent_sha())
        self.assertNotIn("apply_schema", self.runtime.events)

    def test_receipt_failure_after_restore_stops_writers(self):
        original = c.write_artifact
        def write(path, **kwargs):
            if Path(path).name == "restored.json":
                raise OSError("disk full")
            return original(path, **kwargs)
        with patch.object(c, "write_artifact", side_effect=write), self.assertRaises(OSError):
            self.coordinator.run()
        self.assertFalse(self.runtime.services["worker"])

    def test_restored_resume_failed_verification_stops_writers(self):
        self.coordinator.run()
        self.runtime.fail_on = "verify_restored"
        with self.assertRaises(Crash):
            self.coordinator.run(resume_sha=self.intent_sha())
        self.assertFalse(self.runtime.services["worker"])


if __name__ == "__main__":
    unittest.main()
