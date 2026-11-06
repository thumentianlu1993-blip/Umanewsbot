"""宿主操作边界测试：不连接Docker、业务队列或生产。"""
from pathlib import Path
import io
import os
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
from p02_release_runtime import DockerRuntime, APPS
import p02_release_assets as assets


class RuntimeTests(unittest.TestCase):
    def test_current_generation_pointer_survives_config_archive_and_rotation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "source"
            (root / "generations/one").mkdir(parents=True)
            (root / "generations/one/manifest.json").write_bytes(b"original")
            (root / "current").symlink_to("generations/one", target_is_directory=True)
            expected = assets.config_inventory(root)
            copy = Path(raw) / "copy"
            assets.materialize_config(root, copy)
            self.assertTrue((copy / "current").is_symlink())
            self.assertEqual(os.readlink(copy / "current"), "generations/one")
            with self.assertRaises(ValueError):
                assets.backup({"config": copy}, Path(raw) / "ordinary.tar")
            archive = Path(raw) / "config.tar"
            files = assets.backup({"config": copy}, archive, allow_directory_links=True)
            assets.verify_archive(archive, files, allow_directory_links=True)
            restored = Path(raw) / "restored"
            with tarfile.open(archive) as stream:
                stream.extractall(restored, filter="data")
            self.assertEqual(assets.config_inventory(restored / "config"), expected)
            current = restored / "config/current"
            self.assertEqual((current / "manifest.json").read_bytes(), b"original")
            (restored / "config/generations/two").mkdir()
            (restored / "config/generations/two/manifest.json").write_bytes(b"new")
            replacement = restored / "config/next"
            replacement.symlink_to("generations/two", target_is_directory=True)
            os.replace(replacement, current)
            self.assertEqual((current / "manifest.json").read_bytes(), b"new")

    def test_config_directory_pointer_rejects_unsafe_targets(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "source"
            (root / "generations/one").mkdir(parents=True)
            (Path(raw) / "outside").mkdir()
            for target in (str(root / "generations/one"), "../outside", "missing", "current"):
                with self.subTest(target=target):
                    pointer = root / "current"
                    pointer.symlink_to(target, target_is_directory=True)
                    try:
                        with self.assertRaises(ValueError):
                            assets.config_inventory(root)
                    finally:
                        pointer.unlink()

    def test_config_archive_rejects_tampered_pointer_and_link_descendants(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "source"
            (root / "generations/one").mkdir(parents=True)
            (root / "generations/one/data").write_bytes(b"payload")
            (root / "current").symlink_to("generations/one", target_is_directory=True)
            expected = assets.inventory({"config": root}, allow_directory_links=True)
            for attack in ("escape", "dangling", "cycle", "descendant", "duplicate"):
                with self.subTest(attack=attack):
                    path = Path(raw) / (attack + ".tar")
                    with tarfile.open(path, "w") as stream:
                        stream.add(root, arcname="config")
                        if attack in {"descendant", "duplicate"}:
                            info = tarfile.TarInfo("config/current/injected" if attack == "descendant" else "config")
                            if attack == "duplicate":
                                info.type = tarfile.DIRTYPE
                            stream.addfile(info, io.BytesIO(b""))
                    if attack not in {"descendant", "duplicate"}:
                        original = path.read_bytes()
                        with tarfile.open(fileobj=io.BytesIO(original)) as src, tarfile.open(path, "w") as dst:
                            for info in src:
                                if info.name == "config/current":
                                    info.linkname = {"escape": "../../outside", "dangling": "missing", "cycle": "current"}[attack]
                                dst.addfile(info, src.extractfile(info) if info.isfile() else None)
                    with self.assertRaises(ValueError):
                        assets.verify_archive(path, expected, allow_directory_links=True)

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
