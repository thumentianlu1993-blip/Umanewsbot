"""验证真实跨进程发布互斥与owner崩溃后的自动释放。"""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p02_lock_tests", ROOT / "deploy/p02_release_lock.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
METADATA = {"owner": "test", "thread": "p02-test", "operation": "isolated-rehearsal",
            "candidate_commit": "a" * 40, "resource_domain": "synthetic-only"}


class ReleaseLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name).resolve() / "release.lock"

    def tearDown(self):
        self.temp.cleanup()

    def wait_absent(self):
        deadline = time.monotonic() + 5
        while self.path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.path.exists())

    def test_second_owner_and_legacy_entrypoint_cannot_acquire(self):
        with module.ReleaseLock(self.path, METADATA) as lock:
            lock.verify()
            with self.assertRaisesRegex(ValueError, "locked"):
                with module.ReleaseLock(self.path, METADATA):
                    self.fail("second owner entered")
            result = subprocess.run(["sh", str(ROOT / "deploy/deployment_lock.sh"), "acquire"],
                env={**os.environ, "DEPLOYMENT_LOCK_DIR": str(self.path),
                     "DEPLOYMENT_LOCK_TOKEN": "another-owner", "DEPLOYMENT_LOCK_ACTION": "deploy"},
                capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.wait_absent()

    def test_legacy_owner_is_preserved(self):
        self.path.mkdir()
        (self.path / "other-owner").write_text("retain")
        with self.assertRaises(ValueError):
            with module.ReleaseLock(self.path, METADATA):
                pass
        self.assertEqual((self.path / "other-owner").read_text(), "retain")

    def test_sigkill_owner_releases_after_last_effect_process_exits(self):
        code = """
import os,sys,json,subprocess,time
sys.path.insert(0,sys.argv[1])
from p02_release_lock import ReleaseLock
with ReleaseLock(sys.argv[2],json.loads(sys.argv[3])) as lock:
    subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.8)'],pass_fds=lock.pass_fds,
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print('held',flush=True)
    time.sleep(30)
"""
        proc = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "deploy"), str(self.path), json.dumps(METADATA)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(proc.stdout.readline(), b"held\n")
            proc.kill()
            proc.wait(timeout=3)
            self.assertTrue(self.path.exists(), "child effect must retain lock custody")
            self.wait_absent()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()

    def test_foreign_lock_contents_are_never_recursively_deleted(self):
        with module.ReleaseLock(self.path, METADATA):
            (self.path / "foreign").write_text("retain")
        self.assertEqual((self.path / "foreign").read_text(), "retain")


if __name__ == "__main__":
    unittest.main()
