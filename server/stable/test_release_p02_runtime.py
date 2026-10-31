"""宿主操作边界测试：不连接Docker、业务队列或生产。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
from p02_release_runtime import DockerRuntime, APPS
import p02_release_assets as assets


class RuntimeTests(unittest.TestCase):
    def test_emergency_stop_does_not_depend_on_web_or_drain(self):
        runtime = object.__new__(DockerRuntime)
        runtime.plan = {"compose_project": "expected"}
        runtime.root = Path("/isolated")
        runtime.env = {}
        runtime.lock = Mock()
        running = {s: s != "web" for s in APPS}
        runtime.probe_service = lambda s: {"running": running[s], "node": s}
        def stop(service):
            running[service] = False
        runtime.emergency_stop = stop
        runtime.emergency_close({})
        self.assertFalse(any(running.values()))

    def test_emergency_stop_attempts_all_services_even_if_one_fails(self):
        runtime = object.__new__(DockerRuntime)
        runtime.lock = Mock()
        attempted = []
        def stop(service):
            attempted.append(service)
            if service == "beat":
                raise ValueError("stop failed")
        runtime.emergency_stop = stop
        runtime.probe_service = lambda s: {"running": s == "beat"}
        with self.assertRaises(ValueError):
            runtime.emergency_close({})
        self.assertEqual(set(attempted), set(APPS))

    def test_contained_certificate_links_materialize_and_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "tls"
            (root / "archive").mkdir(parents=True)
            (root / "live").mkdir()
            (root / "archive/cert.pem").write_bytes(b"test-certificate")
            (root / "live/cert.pem").symlink_to("../archive/cert.pem")
            dest = Path(raw) / "copy"
            assets.materialize_config(root, dest)
            self.assertFalse((dest / "live/cert.pem").is_symlink())
            self.assertEqual((dest / "live/cert.pem").read_bytes(), b"test-certificate")
            (root / "live/outside").symlink_to("../../outside")
            (Path(raw) / "outside").write_text("excluded")
            with self.assertRaises(ValueError):
                assets.config_inventory(root)


if __name__ == "__main__":
    unittest.main()
