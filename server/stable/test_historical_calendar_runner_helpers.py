"""临时 runner 已退役；直接验证仓库正式工具的等价安全边界。"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from stable import test_historical_race_calendar_pipeline as fixtures
from stable import test_current_year_race_due_checks as due_fixtures


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class KnownCalendarShardRunnerTests(SimpleTestCase):
    def setUp(self):
        self.tool = fixtures._load("prepare_historical_race_calendar_inputs.py")
        self.request_tool = fixtures._load("build_historical_race_calendar_requests.py")
        self.cache_state = fixtures._load("historical_race_calendar_cache_state.py")

    def _prepare_inputs(self, root):
        target = fixtures._target(1, region="united_kingdom", year=2024,
                                  name="Alpha Stakes", course="Ascot", distance="1m")
        source = fixtures._source("bha-2024", region="united_kingdom", year=2024,
                                  adapter="uk_bha", parser="bha_flat",
                                  url="https://www.britishhorseracing.com/files/2024.pdf")
        selection, catalog, cache = root / "selection.json", root / "catalog.json", root / "cache"
        fixtures._write_selection(selection, [target])
        fixtures._write_catalog(catalog, [source])
        cache.mkdir()
        manifest, ledger = fixtures._write_cache_bundle(
            cache, [source], {source["id"]: b'" 1 ASCOT Jun. 15 ALPHA STAKES (P1.)\n'}, [target])
        self.request_tool.build_calendar_requests(selection_path=selection, catalog_path=catalog,
                                                 output_dir=root / "requests")
        return dict(selection_path=selection, catalog_path=catalog, source_cache_root=cache,
                    source_cache_manifest_path=manifest, request_ledger_path=ledger,
                    request_manifest_path=root / "requests/manifest.json",
                    country_region="united_kingdom", year=2024, recorded_at=fixtures.RECORDED_AT)

    def test_prepare_recomputes_with_current_parser_and_binds_inputs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            kwargs = self._prepare_inputs(root)
            first = self.tool.prepare_calendar_inputs(**kwargs, output_dir=root / "first")
            self.assertEqual(first["complete_count"], 1)
            parser = self.tool.parse_bha_flat_schedule_text

            def changed_parser(text, *, year):
                # 模拟代码升级后相同源文本得到不同日期，不能复用上次结果。
                return parser(text.replace("Jun. 15", "Jun. 16"), year=year)

            with patch.object(self.tool, "parse_bha_flat_schedule_text", side_effect=changed_parser) as parse:
                self.tool.prepare_calendar_inputs(**kwargs, output_dir=root / "second")
            parse.assert_called_once()
            self.assertEqual(read_jsonl(root / "first/date_matches.jsonl")[0]["local_date"], "2024-06-15")
            self.assertEqual(read_jsonl(root / "second/date_matches.jsonl")[0]["local_date"], "2024-06-16")
            manifest = json.loads((root / "second/manifest.json").read_text())
            self.assertEqual(manifest["selection"], self.tool.file_identity(kwargs["selection_path"]))
            self.assertEqual(manifest["source_catalog"], self.tool.file_identity(kwargs["catalog_path"]))
            for name in ("selection_path", "catalog_path"):
                path = kwargs[name]
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(self.tool.CalendarPrepareError, "identity does not match"):
                    self.tool.prepare_calendar_inputs(**kwargs, output_dir=root / "rejected")
                self.assertFalse((root / "rejected").exists())
                path.write_bytes(original)

    def test_prepare_refuses_existing_output_without_modifying_it(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            kwargs = self._prepare_inputs(root)
            output = root / "output"
            self.tool.prepare_calendar_inputs(**kwargs, output_dir=output)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            self.assertNotIn("execution-identity.json", before)
            with self.assertRaisesRegex(self.tool.CalendarPrepareError, "already exists"):
                self.tool.prepare_calendar_inputs(**kwargs, output_dir=output)
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def _retry(self, adapter, host, *, succeeds):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            provider = root / "provider.jsonl"
            urls = [f"https://{host}/a", f"https://{host}/b"]
            write_jsonl(provider, [{"adapter_key": adapter, "target_id": i + 1,
                        "urls": {"calendar_source": {"url": url}}} for i, url in enumerate(urls)])
            previous = [{"source_url": urls[0], "status": "succeeded"},
                        {"source_url": urls[1], "status": "failed", "error": "timeout"}]
            write_jsonl(cache / "request-ledger.jsonl", previous)
            (cache / "summary.json").write_text(json.dumps({"failure_count": 1}))
            retry, old = self.cache_state.begin_cache_retry(cache, provider)
            self.assertEqual([r["urls"]["calendar_source"]["url"] for r in read_jsonl(retry)], [urls[1]])
            write_jsonl(cache / "request-ledger.jsonl", [{"source_url": urls[1],
                        "status": "succeeded" if succeeds else "failed"}])
            (cache / "summary.json").write_text(json.dumps({"failure_count": int(not succeeds)}))
            self.cache_state.finish_cache_retry(cache, provider, old)
            final = read_jsonl(cache / "request-ledger.jsonl")
            self.assertEqual({r["source_url"] for r in final}, set(urls))
            self.assertEqual(final[0], previous[0])
            attempts = read_jsonl(cache / "request-attempt-ledger.jsonl")
            self.assertEqual(len(attempts), 3)
            self.assertEqual(attempts[1], previous[1])
            self.assertEqual(self.cache_state.cache_is_complete(cache, provider), succeeds)
            self.assertEqual(json.loads((cache / "summary.json").read_text())["failure_count"], int(not succeeds))
            self.assertEqual([r["phase"] for r in read_jsonl(cache / "request-attempt-summaries.jsonl")],
                             ["before_retry", "retry"])

    def test_standard_cache_retry_preserves_success_and_attempts(self):
        self._retry("france_galop", "www.france-galop.com", succeeds=True)

    def test_toba_cache_retry_preserves_failed_attempts(self):
        self._retry("toba", "toba.org", succeeds=True)

    def test_cache_cli_enforces_network_budget_interval_and_disk(self):
        tool = fixtures._load("cache_historical_race_date_sources.py")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = root / "provider.jsonl"
            urls = ["https://toba.org/a", "https://toba.org/b", "https://toba.org/c"]
            write_jsonl(provider, [{"adapter_key": "toba", "target_id": i + 1,
                        "urls": {"calendar_source": {"url": url}}} for i, url in enumerate(urls)])
            args = ["cache", "--provider-jsonl", str(provider), "--output-root", str(root / "cache"),
                    "--request-ledger", str(root / "ledger.jsonl"), "--summary", str(root / "summary.json"),
                    "--allow-network"]
            env = {"HISTORICAL_RACE_BACKFILL_ENABLED": "true", "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK": "true",
                   "RACE_EVENT_CRAWL_MAX_REQUESTS": "2", "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": "0.03",
                   "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(root / "budget.json"),
                   "RACE_EVENT_CRAWL_HOST_INTERVAL_ARTIFACT": str(root / "interval.json"),
                   "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(root / "cache"),
                   "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(root / "cache/source_cache_manifest.json")}
            calls = []

            def fetch(url, **kwargs):
                calls.append(time.monotonic())
                return b"<html>valid source</html>", {"status": 200, "final_url": url,
                        "redirect_chain": [], "headers": {"content-type": "text/html"}}

            with patch.object(tool, "fetch_https", side_effect=fetch) as http:
                for missing in ("cli", "HISTORICAL_RACE_BACKFILL_ENABLED", "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK"):
                    gate_env = {k: v for k, v in env.items() if k != missing}
                    with self.subTest(missing=missing), patch.dict(os.environ, gate_env, clear=True), patch.object(
                            sys, "argv", args[:-1] if missing == "cli" else args):
                        with self.assertRaises(SystemExit):
                            tool.main()
                    http.assert_not_called()
                with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", args):
                    self.assertEqual(tool.main(), 2)
                self.assertEqual(http.call_count, 2)
                self.assertGreaterEqual(calls[1] - calls[0], 0.025)
                self.assertEqual(json.loads((root / "budget.json").read_text())["request_count"], 2)
                self.assertEqual([r["status"] for r in read_jsonl(root / "ledger.jsonl")],
                                 ["succeeded", "succeeded", "failed"])
                self.assertIn("budget exhausted", read_jsonl(root / "ledger.jsonl")[-1]["error"])
                # 新缓存目录低磁盘，真实写入保护必须留下失败而非成功产物。
                low = {**env, "RACE_EVENT_CRAWL_MAX_REQUESTS": "0", "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES": "100",
                       "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(root / "low"),
                       "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(root / "low/source_cache_manifest.json")}
                low_args = [str(root / "low") if v == str(root / "cache") else v for v in args]
                with patch.dict(os.environ, low, clear=True), patch.object(sys, "argv", low_args), patch(
                        "race_event_source_cache.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
                    self.assertEqual(tool.main(), 2)
                self.assertTrue(all(r["status"] == "failed" and "disk floor" in r["error"]
                                    for r in read_jsonl(root / "ledger.jsonl")))
                self.assertEqual(json.loads((root / "low/source_cache_manifest.json").read_text())["files"], {})


class CurrentYearSourceOverrideRunnerTests(SimpleTestCase):
    def setUp(self):
        self.tool = fixtures._load("prepare_historical_race_calendar_inputs.py")
        self.request_tool = fixtures._load("build_historical_race_calendar_requests.py")
        self.cache_state = fixtures._load("historical_race_calendar_cache_state.py")

    _retry = KnownCalendarShardRunnerTests._retry
    _partial_hkjc_fixture = fixtures.HistoricalRaceCalendarPrepareTests._partial_hkjc_fixture

    def test_partial_cache_retry_failure_remains_auditable(self):
        self._retry("france_galop", "www.france-galop.com", succeeds=False)

    def _hkjc_inputs(self, root):
        _target, _source, selection, catalog, requests, cache, manifest, ledger = self._partial_hkjc_fixture(
            root, body=b"WED 07/01/26 January Cup G3 3yo+ 1800\n")
        return dict(selection_path=selection, catalog_path=catalog, source_cache_root=cache,
                    source_cache_manifest_path=manifest, request_ledger_path=ledger,
                    request_manifest_path=requests / "manifest.json", country_region="hong_kong",
                    year=2026, recorded_at=fixtures.RECORDED_AT, hkjc_cutoff_date=date(2026, 7, 15))

    def test_hkjc_request_and_prepare_require_identical_cutoff(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            kwargs = self._hkjc_inputs(root)
            self.tool.prepare_calendar_inputs(**kwargs, output_dir=root / "valid")
            request = json.loads(kwargs["request_manifest_path"].read_text())
            prepared = json.loads((root / "valid/manifest.json").read_text())
            self.assertEqual(request["coverage_policy"], prepared["coverage_policy"])
            kwargs["hkjc_cutoff_date"] = date(2026, 7, 14)
            with self.assertRaisesRegex(self.tool.CalendarPrepareError, "coverage policy identity"):
                self.tool.prepare_calendar_inputs(**kwargs, output_dir=root / "invalid")
            self.assertFalse((root / "invalid").exists())

    def test_hkjc_pre_cutoff_catalog_is_rejected_without_mutation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            kwargs = self._hkjc_inputs(root)
            catalog = kwargs["catalog_path"]
            content = json.loads(catalog.read_text())
            content["sources"][0]["options"] = {"season_end_year": 2026}
            catalog.write_text(json.dumps(content))
            before = catalog.read_bytes()
            with self.assertRaises(self.tool.CalendarPrepareError):
                self.tool.prepare_calendar_inputs(**kwargs, output_dir=root / "invalid")
            self.assertFalse((root / "invalid").exists())
            self.assertEqual(catalog.read_bytes(), before)

    def test_classifier_recomputes_for_new_cutoff(self):
        tool = due_fixtures.MODULE
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection, matches, gaps = root / "selection.json", root / "matches.jsonl", root / "gaps.jsonl"
            selection.write_text(json.dumps(due_fixtures.selection_payload([due_fixtures.target(1)])))
            write_jsonl(matches, [{"target_id": 1, "local_date": "2026-07-16", "country_region": "france",
                                  "status": "finished", "source_refs": {}}])
            write_jsonl(gaps, [])
            inputs = due_fixtures.pipeline_inputs(root, selection=selection, date_matches=matches, gaps=gaps)
            kwargs = dict(selection_path=selection, **inputs, date_matches_path=matches, gaps_path=gaps)
            first = tool.classify_due_checks(**kwargs, cutoff=date(2026, 7, 15), output_dir=root / "first")
            before = (root / "first/manifest.json").read_bytes()
            second = tool.classify_due_checks(**kwargs, cutoff=date(2026, 7, 16), output_dir=root / "second")
            self.assertEqual(first["due_event_count"], 0)
            self.assertEqual(second["due_event_count"], 1)
            self.assertNotEqual(before, (root / "second/manifest.json").read_bytes())
            self.assertEqual(before, (root / "first/manifest.json").read_bytes())
            with self.assertRaises(tool.DueCheckError):
                tool.classify_due_checks(**kwargs, cutoff=date(2026, 7, 16), output_dir=root / "first")
