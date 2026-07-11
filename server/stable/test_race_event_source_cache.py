from __future__ import annotations

import importlib.util
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


def _load_cache_module():
    path = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "race_event_source_cache.py"
    spec = importlib.util.spec_from_file_location("race_event_source_cache_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_budget_module():
    path = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "race_event_request_budget.py"
    spec = importlib.util.spec_from_file_location("race_event_request_budget_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RaceEventSourceCacheTests(SimpleTestCase):
    def setUp(self):
        self.module = _load_cache_module()

    def _environment(self, root: Path, *, max_bytes: int = 1024, min_free: int = 1):
        return patch.dict(
            os.environ,
            {
                "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(root),
                "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(root / "manifest.json"),
                "RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES": str(max_bytes),
                "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES": str(min_free),
            },
            clear=False,
        )

    def test_multiple_adapters_share_one_cache_byte_budget(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._environment(root, max_bytes=10):
                self.module.write_source_cache(root / "adapter-a" / "a.bin", b"123456", source_url="https://a.test")
                with self.assertRaisesMessage(self.module.SourceCacheBudgetExceeded, "byte budget"):
                    self.module.write_source_cache(root / "adapter-b" / "b.bin", b"12345", source_url="https://b.test")

            self.assertTrue((root / "adapter-a" / "a.bin").is_file())
            self.assertFalse((root / "adapter-b" / "b.bin").exists())
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_bytes"], 6)
            self.assertEqual(len(manifest["files"]), 1)

    def test_disk_floor_fails_before_partial_cache_write(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            disk = type("DiskUsage", (), {"total": 100, "used": 90, "free": 10})()
            with self._environment(root, max_bytes=100, min_free=9), patch.object(
                self.module.shutil,
                "disk_usage",
                return_value=disk,
            ):
                with self.assertRaisesMessage(self.module.SourceCacheBudgetExceeded, "disk floor"):
                    self.module.write_source_cache(root / "source" / "body.html", b"12", source_url="https://a.test")

            self.assertFalse((root / "source" / "body.html").exists())
            self.assertFalse((root / "source" / "body.html.tmp").exists())

    def test_unreadable_manifest_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text("not-json", encoding="utf-8")
            with self._environment(root):
                with self.assertRaisesMessage(self.module.SourceCacheBudgetExceeded, "unreadable"):
                    self.module.write_source_cache(root / "body.html", b"body", source_url="https://a.test")
            self.assertFalse((root / "body.html").exists())

    def test_approved_cache_is_retained_while_unprotected_cache_is_cleaned(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            with self._environment(root):
                protected = self.module.write_source_cache(root / "protected.html", b"protected", source_url="https://a.test")
                temporary = self.module.write_source_cache(root / "temporary.html", b"temporary", source_url="https://b.test")
                self.module.protect_source_cache_files(
                    manifest_path,
                    [protected["path"]],
                    artifact_sha256="a" * 64,
                )
                removed = self.module.cleanup_unprotected_source_cache(manifest_path)

            self.assertEqual(removed, [temporary["path"]])
            self.assertTrue((root / "protected.html").exists())
            self.assertFalse((root / "temporary.html").exists())

    def test_changed_cache_cannot_be_protected_as_approved_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            with self._environment(root):
                identity = self.module.write_source_cache(
                    root / "source.html",
                    b"original",
                    source_url="https://a.test",
                )
                (root / "source.html").write_bytes(b"changed")
                with self.assertRaisesMessage(self.module.SourceCacheBudgetExceeded, "identity changed"):
                    self.module.protect_source_cache_files(
                        manifest_path,
                        [identity["path"]],
                        artifact_sha256="a" * 64,
                    )

    def test_cache_protection_hashes_files_without_reading_them_whole(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            with self._environment(root, max_bytes=10_000):
                identity = self.module.write_source_cache(
                    root / "large.pdf",
                    b"chunk" * 1024,
                    source_url="https://a.test/archive.pdf",
                )
                with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
                    self.module.protect_source_cache_files(
                        manifest_path,
                        [identity["path"]],
                        artifact_sha256="a" * 64,
                    )

    def test_protected_cache_cannot_be_overwritten_with_different_bytes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            with self._environment(root):
                identity = self.module.write_source_cache(
                    root / "official.html",
                    b"approved",
                    source_url="https://a.test",
                )
                self.module.protect_source_cache_files(
                    manifest_path,
                    [identity["path"]],
                    artifact_sha256="a" * 64,
                )
                same = self.module.write_source_cache(
                    root / "official.html",
                    b"approved",
                    source_url="https://a.test",
                )
                with self.assertRaisesMessage(self.module.SourceCacheBudgetExceeded, "protected"):
                    self.module.write_source_cache(
                        root / "official.html",
                        b"changed",
                        source_url="https://a.test",
                    )

            self.assertEqual((root / "official.html").read_bytes(), b"approved")
            self.assertEqual(same["protected_by"], ["a" * 64])

    def test_cleanup_rejects_manifest_path_traversal_without_deleting_outside_file(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "cache"
            root.mkdir()
            outside = base / "outside.html"
            outside.write_text("keep", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "root": str(root),
                        "files": {
                            "../outside.html": {
                                "path": "../outside.html",
                                "size": outside.stat().st_size,
                                "sha256": "0" * 64,
                                "protected_by": [],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesMessage(self.module.SourceCacheBudgetExceeded, "escapes cache root"):
                self.module.cleanup_unprotected_source_cache(manifest)

            self.assertTrue(outside.exists())

    def test_network_adapters_use_the_guarded_cache_writer(self):
        tools = Path(__file__).resolve().parents[2] / "runtime" / "tools"
        adapters = sorted(tools.glob("prepare_*_candidates.py"))
        network_adapters = [path for path in adapters if "before_network_request" in path.read_text(encoding="utf-8")]

        self.assertGreaterEqual(len(network_adapters), 10)
        for path in network_adapters:
            text = path.read_text(encoding="utf-8")
            self.assertIn("race_event_source_cache", text, path.name)

    def test_concurrent_adapters_cannot_overspend_shared_request_budget(self):
        budget = _load_budget_module()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "RACE_EVENT_CRAWL_MAX_REQUESTS": "10",
                "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": "0",
                "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(Path(tmp) / "budget.json"),
            },
            clear=False,
        ):
            def reserve(index):
                try:
                    budget.before_network_request(f"https://source.test/{index}")
                    return True
                except budget.RequestBudgetExceeded:
                    return False

            with ThreadPoolExecutor(max_workers=20) as executor:
                outcomes = list(executor.map(reserve, range(20)))
            state = json.loads((Path(tmp) / "budget.json").read_text(encoding="utf-8"))

        self.assertEqual(sum(outcomes), 10)
        self.assertEqual(state["request_count"], 10)
