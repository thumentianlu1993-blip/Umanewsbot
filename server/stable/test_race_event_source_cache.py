from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
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


def _load_safe_http_module():
    path = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "race_event_safe_http.py"
    spec = importlib.util.spec_from_file_location("race_event_safe_http_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_date_source_cache_module():
    path = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "cache_historical_race_date_sources.py"
    spec = importlib.util.spec_from_file_location("historical_date_source_cache_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
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

    def test_empty_source_cache_manifest_is_a_valid_terminal_artifact(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self._environment(root):
                manifest_path = self.module.ensure_source_cache_manifest(
                    root / "outputs" / "cache" / ".calendar-cache"
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["root"], str(root.resolve()))
        self.assertEqual(manifest["files"], {})
        self.assertEqual(manifest["total_bytes"], 0)

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

    def test_separate_shard_budgets_share_one_host_request_interval(self):
        budget = _load_budget_module()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = {
                "RACE_EVENT_CRAWL_MAX_REQUESTS": "10",
                "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": "0.05",
                "RACE_EVENT_CRAWL_HOST_INTERVAL_ARTIFACT": str(root / "host-interval.json"),
            }
            with patch.dict(
                os.environ,
                {**common, "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(root / "shard-a.json")},
                clear=False,
            ):
                budget.before_network_request("https://source.test/a")
            started = time.monotonic()
            with patch.dict(
                os.environ,
                {**common, "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(root / "shard-b.json")},
                clear=False,
            ):
                budget.before_network_request("https://source.test/b")
            elapsed = time.monotonic() - started

            host_state = json.loads((root / "host-interval.json").read_text(encoding="utf-8"))
            shard_a = json.loads((root / "shard-a.json").read_text(encoding="utf-8"))
            shard_b = json.loads((root / "shard-b.json").read_text(encoding="utf-8"))

        self.assertGreaterEqual(elapsed, 0.04)
        self.assertEqual(host_state["request_count"], 2)
        self.assertEqual(shard_a["request_count"], 1)
        self.assertEqual(shard_b["request_count"], 1)


class RaceEventSafeHttpTests(SimpleTestCase):
    def setUp(self):
        self.module = _load_safe_http_module()

    def test_rejects_non_https_private_and_unapproved_initial_urls(self):
        for url in (
            "http://www.racingpost.com/results/1",
            "https://127.0.0.1/results/1",
            "https://metadata.google.internal/results/1",
            "https://attacker.example/results/1",
        ):
            with self.subTest(url=url), self.assertRaises(self.module.SafeHttpError):
                self.module.validate_https_url(url, allowed_hosts=("racingpost.com",))

    def test_redirect_handler_rejects_unapproved_redirect_before_following_it(self):
        handler = self.module.ValidatingRedirectHandler(("racingpost.com",))
        request = self.module.Request("https://www.racingpost.com/results/1")

        with self.assertRaisesMessage(self.module.SafeHttpError, "outside allowlist"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://attacker.example/collect",
            )

    def test_fetch_rejects_unapproved_final_url(self):
        response = type(
            "Response",
            (),
            {
                "read": lambda self: b"body",
                "geturl": lambda self: "https://attacker.example/final",
                "status": 200,
                "headers": {},
                "__enter__": lambda self: self,
                "__exit__": lambda self, *args: None,
            },
        )()
        opener = type("Opener", (), {"open": lambda self, request, timeout: response})()

        with patch.object(self.module, "build_opener", return_value=opener):
            with self.assertRaisesMessage(self.module.SafeHttpError, "outside allowlist"):
                self.module.fetch_https(
                    "https://www.racingpost.com/results/1",
                    allowed_hosts=("racingpost.com",),
                    timeout=10,
                )


class HistoricalRaceDateSourceCacheTests(SimpleTestCase):
    def setUp(self):
        self.module = _load_date_source_cache_module()

    def test_network_requires_cli_and_both_historical_switches(self):
        enabled = {
            "HISTORICAL_RACE_BACKFILL_ENABLED": "true",
            "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK": "true",
        }
        self.module.require_network_gates(allow_network=True, environ=enabled)

        for allow_network, environ in (
            (False, enabled),
            (True, {**enabled, "HISTORICAL_RACE_BACKFILL_ENABLED": "false"}),
            (True, {**enabled, "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK": "false"}),
        ):
            with self.subTest(allow_network=allow_network, environ=environ):
                with self.assertRaises(self.module.DateSourceCacheError):
                    self.module.require_network_gates(allow_network=allow_network, environ=environ)

    def test_cache_deduplicates_urls_and_preserves_all_target_references(self):
        rows = [
            {
                "adapter_key": "france_galop",
                "series_key": "arc",
                "edition_year": 2000,
                "urls": {"result_url": {"url": "https://www.france-galop.com/history"}},
            },
            {
                "adapter_key": "france_galop",
                "series_key": "arc",
                "edition_year": 2012,
                "urls": {"result_url": {"url": "https://www.france-galop.com/history"}},
            },
        ]
        identity = {"path": "france_galop/source.html", "sha256": "a" * 64, "size": 4}
        with TemporaryDirectory() as tmp, patch.object(
            self.module, "before_network_request"
        ) as budget, patch.object(
            self.module,
            "fetch_https",
            return_value=(b"body", {"status": 200, "final_url": rows[0]["urls"]["result_url"]["url"], "redirect_chain": []}),
        ) as fetch, patch.object(
            self.module, "write_source_cache", return_value=identity
        ) as cache:
            result = self.module.cache_provider_rows(rows, output_root=Path(tmp), timeout=10)

        budget.assert_called_once_with("https://www.france-galop.com/history")
        fetch.assert_called_once()
        cache.assert_called_once()
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(len(result["request_ledger"][0]["target_references"]), 2)

    def test_pdf_url_rejects_http_200_antibot_html(self):
        with self.assertRaisesMessage(self.module.DateSourceCacheError, "not a PDF"):
            self.module.validate_source_body(
                "https://www.equibase.com/static/chart/pdf/CD102900USA9.pdf",
                b"<!doctype html><title>Pardon Our Interruption</title>",
                {"content-type": "text/html; charset=UTF-8"},
            )

    def test_equibase_pdf_cfm_rejects_http_200_incapsula_html(self):
        with self.assertRaisesMessage(self.module.DateSourceCacheError, "not a PDF"):
            self.module.validate_source_body(
                "https://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&TID=CD",
                b'<html><p>To regain access, enable JavaScript.</p><img src="/_Incapsula_Resource">',
                {"content-type": "text/html; charset=UTF-8"},
            )

    def test_html_url_rejects_known_antibot_page(self):
        with self.assertRaisesMessage(self.module.DateSourceCacheError, "anti-bot"):
            self.module.validate_source_body(
                "https://www.racingpost.com/results/1",
                b"<html><title>Access Denied</title></html>",
                {"content-type": "text/html"},
            )

    def test_toba_yearbook_table_is_not_rejected_for_incapsula_script_reference(self):
        self.module.validate_source_body(
            "https://toba.org/graded-stakes/2024-races/",
            (
                b"<html><table><tr><th>Track</th><th>Date</th><th>Stake</th>"
                b"<th>Winner</th></tr></table><script src='/_Incapsula_Resource'></script></html>"
            ),
            {"content-type": "text/html; charset=UTF-8"},
        )

    def test_toba_network_fetch_uses_browser_compatible_headers(self):
        row = {
            "adapter_key": "toba",
            "target_id": 1,
            "target_sha256": "1" * 64,
            "series_key": "fixture",
            "edition_year": 2024,
            "urls": {
                "calendar_source": {
                    "url": "https://toba.org/graded-stakes/2024-races/"
                }
            },
        }
        body = (
            b"<html><table><tr><th>Track</th><th>Date</th><th>Stake</th>"
            b"<th>Winner</th></tr></table></html>"
        )
        response = {
            "status": 200,
            "final_url": row["urls"]["calendar_source"]["url"],
            "redirect_chain": [],
            "headers": {"content-type": "text/html"},
        }
        with TemporaryDirectory() as tmp, patch.object(
            self.module, "before_network_request"
        ), patch.object(
            self.module, "fetch_https", return_value=(body, response)
        ) as fetch, patch.object(
            self.module,
            "write_source_cache",
            return_value={"path": "toba/body.html", "sha256": "a" * 64, "size": len(body)},
        ):
            result = self.module.cache_provider_rows([row], output_root=Path(tmp), timeout=10)

        self.assertEqual(result["failure_count"], 0)
        headers = fetch.call_args.kwargs["headers"]
        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertIn("text/html", headers["Accept"])
        self.assertEqual(headers["Accept-Language"], "en-US,en;q=0.9")

    def test_toba_incapsula_page_without_yearbook_table_is_rejected(self):
        with self.assertRaisesMessage(self.module.DateSourceCacheError, "anti-bot"):
            self.module.validate_source_body(
                "https://toba.org/graded-stakes/2024-races/",
                b"<html><script src='/_Incapsula_Resource'></script></html>",
                {"content-type": "text/html; charset=UTF-8"},
            )

    def test_irishracing_http_200_unavailable_page_is_rejected(self):
        with self.assertRaisesMessage(self.module.DateSourceCacheError, "unavailable"):
            self.module.validate_source_body(
                "https://www.irishracing.com/raceresults/Sun-29th-Oct-2000/ChurchillDowns/1600",
                b"<html><title>Information Not Available</title></html>",
                {"content-type": "text/html"},
            )

    def test_failed_content_validation_preserves_response_metadata_in_ledger(self):
        row = {
            "adapter_key": "equibase",
            "series_key": "ack-ack",
            "edition_year": 2025,
            "urls": {"result_url": {"url": "https://www.equibase.com/static/chart/pdf/fixture.pdf"}},
        }
        response = {
            "status": 200,
            "final_url": row["urls"]["result_url"]["url"],
            "redirect_chain": ["https://www.equibase.com/static/chart/pdf/fixture.pdf"],
            "headers": {"content-type": "text/html"},
        }
        with TemporaryDirectory() as tmp, patch.object(
            self.module, "before_network_request"
        ), patch.object(
            self.module, "fetch_https", return_value=(b"<html>blocked</html>", response)
        ):
            result = self.module.cache_provider_rows([row], output_root=Path(tmp), timeout=10)

        failed = result["request_ledger"][0]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["http_status"], 200)
        self.assertEqual(failed["final_url"], response["final_url"])
        self.assertEqual(failed["redirect_chain"], response["redirect_chain"])

    def test_partial_cache_succeeds_only_after_all_requests_have_terminal_ledger_rows(self):
        result = {
            "request_count": 2,
            "success_count": 1,
            "failure_count": 1,
            "request_ledger": [
                {"status": "succeeded", "source_url": "https://www.jra.go.jp/a"},
                {"status": "failed", "source_url": "https://www.jra.go.jp/b"},
            ],
        }
        self.assertEqual(self.module.cache_command_exit_code(result, allow_partial=False), 2)
        self.assertEqual(self.module.cache_command_exit_code(result, allow_partial=True), 0)

        result["request_ledger"][1]["status"] = "started"
        with self.assertRaisesMessage(self.module.DateSourceCacheError, "terminal"):
            self.module.cache_command_exit_code(result, allow_partial=True)

    def test_failure_summary_counts_unique_affected_targets(self):
        rows = [
            {
                "adapter_key": "jra",
                "target_id": target_id,
                "target_sha256": str(target_id) * 64,
                "series_key": f"race-{target_id}",
                "edition_year": 2024,
                "urls": {"calendar_source": {"url": "https://www.jra.go.jp/calendar.pdf"}},
            }
            for target_id in (1, 2)
        ]
        with TemporaryDirectory() as tmp, patch.object(
            self.module, "before_network_request"
        ), patch.object(
            self.module, "fetch_https", side_effect=self.module.SafeHttpError("offline")
        ):
            result = self.module.cache_provider_rows(rows, output_root=Path(tmp), timeout=10)

        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failed_urls"], ["https://www.jra.go.jp/calendar.pdf"])
        self.assertEqual(result["affected_target_count"], 2)
        references = result["request_ledger"][0]["target_references"]
        self.assertEqual([item["target_id"] for item in references], [1, 2])

    def test_calendar_provider_rejects_invalid_target_identity_before_network(self):
        row = {
            "adapter_key": "jra",
            "target_id": True,
            "target_sha256": "a" * 64,
            "series_key": "japan-race",
            "edition_year": 2024,
            "urls": {
                "calendar_source": {
                    "url": "https://www.jra.go.jp/calendar.html"
                }
            },
        }
        with TemporaryDirectory() as tmp, patch.object(
            self.module, "before_network_request"
        ) as budget, self.assertRaisesMessage(
            self.module.DateSourceCacheError, "target identity"
        ):
            self.module.cache_provider_rows([row], output_root=Path(tmp), timeout=10)
        budget.assert_not_called()
