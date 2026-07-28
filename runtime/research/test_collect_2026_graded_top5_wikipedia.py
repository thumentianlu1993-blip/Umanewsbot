from __future__ import annotations

import importlib.util
import csv
import io
import json
import re
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import date
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("collect_2026_graded_top5_wikipedia.py")
SPEC = importlib.util.spec_from_file_location("graded_top5_collector", SCRIPT_PATH)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class FakeResponse:
    def __init__(self, body: str, url: str = "https://umafans.run/races/2026/test/"):
        self.content = body.encode("utf-8")
        self.url = url
        self.status_code = 200


class FakeClient:
    def __init__(self, responses: dict[str, FakeResponse | Exception]):
        self.responses = responses
        self.calls: list[str] = []
        self.request_count = 0

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        self.request_count += 1
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value


def race_html(*, status: str = "已完赛", rows: list[tuple[str, str]] | None = None) -> str:
    rows = rows or [("1", "甲"), ("2", "乙"), ("3", "丙"), ("4", "丁"), ("5", "戊")]
    body_rows = "".join(
        f"<tr><td>{position}</td><td>1</td><td>{horse}</td><td>骑师</td>"
        f"<td>练马师</td><td>1:34</td><td></td><td>资料</td></tr>"
        for position, horse in rows
    )
    return f"""
    <main class="race-page">
      <div class="race-hero-meta-text">日本 · 东京</div>
      <h1 class="race-hero-name">测试重赏</h1>
      <div class="race-hero-original">Test Stakes · 2026-07-01</div>
      <span class="grade-badge">G1</span>
      <section id="overview"><div class="race-meta-grid">
        <div><span>等级</span><b>G1</b></div>
        <div><span>日期</span><b>2026-07-01</b></div>
        <div><span>马场</span><b>东京</b></div>
        <div><span>状态</span><b>{status}</b></div>
      </div></section>
      <section id="results"><table><tbody>{body_rows}</tbody></table></section>
    </main>
    """


def write_manifest(root: Path, race_urls: list[str]) -> tuple[dict, str]:
    manifest = {
        **collector.current_tool_identity_record(),
        "year": 2026,
        "cutoff": "2026-07-26",
        "base_url": "https://umafans.run",
        "requested_base_url": "https://umafans.run",
        "race_urls": sorted(race_urls),
        "race_urls_sha256": collector.sha256_bytes(
            collector.canonical_json_bytes(sorted(race_urls))
        ),
        "created_at": "2026-07-26T00:00:00+00:00",
    }
    collector.atomic_write_json(root / "run_manifest.json", manifest)
    return manifest, collector.sha256_bytes((root / "run_manifest.json").read_bytes())


def sample_row(key: str = "japan|甲", horse_display_name: str = "甲") -> object:
    return collector.RaceResultRow(
        region="japan", region_label="日本", race_date="2026-07-01",
        race_name_zh="测试重赏", race_name_original="Test Stakes", grade="G1",
        racecourse="东京", finish_position=1, horse_display_name=horse_display_name,
        jockey_name="", trainer_name="", finish_time="", margin="",
        race_url="https://umafans.run/races/2026/test/",
        race_page_sha256="abc", horse_lookup_key=key,
    )


class CollectorCompatibilityTests(unittest.TestCase):
    def parse(self, html: str):
        url = "https://umafans.run/races/2026/test/"
        instance = collector.UmaFansCollector(
            base_url="https://umafans.run",
            client=FakeClient({url: FakeResponse(html)}),
            output_dir=Path(tempfile.mkdtemp()),
            year=2026,
            cutoff=date(2026, 7, 26),
        )
        return instance.parse_race_page(url)

    def test_finished_status_labels_are_accepted(self):
        self.assertEqual(len(self.parse(race_html(status="已完赛"))), 5)
        self.assertEqual(len(self.parse(race_html(status="已结束"))), 5)

    def test_dead_heat_official_positions_are_accepted(self):
        rows = self.parse(
            race_html(rows=[("1", "甲"), ("2", "乙"), ("2", "丙"), ("4", "丁"), ("5", "戊")])
        )
        self.assertEqual([row.finish_position for row in rows], [1, 2, 2, 4, 5])

    def test_duplicate_horse_in_top_five_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unique"):
            self.parse(
                race_html(rows=[("1", "甲"), ("2", "乙"), ("3", "甲"), ("4", "丁"), ("5", "戊")])
            )


class CheckpointContractTests(unittest.TestCase):
    def test_atomic_write_ignores_incomplete_temp_file(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "item.json"
            path.with_name("item.json.tmp-interrupted").write_text('{"broken":', encoding="utf-8")
            collector.atomic_write_json(path, {"key": "horse-1", "status": "success"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["key"], "horse-1")

    def test_stable_shard_assignment(self):
        first = [collector.stable_shard("horse-a", 4) for _ in range(5)]
        self.assertEqual(len(set(first)), 1)
        self.assertGreaterEqual(first[0], 0)
        self.assertLess(first[0], 4)

    def test_merge_is_deterministic_and_conflicts_fail_closed(self):
        left = [{"key": "b", "value": 2}, {"key": "a", "value": 1}]
        right = [{"key": "a", "value": 1}]
        merged = collector.merge_keyed_records([left, right])
        self.assertEqual([row["key"] for row in merged], ["a", "b"])
        with self.assertRaisesRegex(ValueError, "conflict"):
            collector.merge_keyed_records([[{"key": "a", "value": 1}], [{"key": "a", "value": 2}]])

    def test_lookup_key_uses_source_identity_but_not_race_context(self):
        fallback_a = collector.canonical_lookup_key("japan", "同名马", "", "race-a")
        fallback_b = collector.canonical_lookup_key("japan", "同名马", "", "race-b")
        source_a = collector.canonical_lookup_key("japan", "同名马", "/horses/10/", "race-a")
        source_b = collector.canonical_lookup_key("japan", "同名马", "/horses/11/", "race-a")
        self.assertEqual(fallback_a, fallback_b)
        self.assertNotEqual(source_a, source_b)

    def test_resume_skips_completed_items_and_cache_hit_avoids_network(self):
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(Path(raw), stage="profiles", shard_index=0, shard_count=1)
            store.save_item("horse-a", {"key": "horse-a", "status": "success"})

            def process(key: str):
                calls.append(key)
                return {"key": key, "status": "success"}

            result = collector.run_checkpointed_items(
                ["horse-a", "horse-b"], store=store, process=process, resume=True
            )
            self.assertEqual(calls, ["horse-b"])
            self.assertEqual(result["processed"], 2)
            self.assertEqual(result["cached"], 1)

    def test_partial_failure_preserves_successful_items(self):
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(Path(raw), stage="races", shard_index=0, shard_count=1)

            def process(key: str):
                if key == "bad":
                    raise OSError("network down")
                return {"key": key, "status": "success"}

            result = collector.run_checkpointed_items(
                ["good", "bad"], store=store, process=process, resume=True
            )
            self.assertEqual(store.load_item("good")["status"], "success")
            self.assertEqual(store.load_item("bad")["status"], "retryable_error")
            self.assertEqual(result["failed"], 1)

    def test_manifest_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "run_manifest.json"
            first = {"schema_version": 1, "cutoff": "2026-07-26", "base_url": "https://umafans.run"}
            collector.ensure_run_manifest(path, first)
            collector.ensure_run_manifest(path, first)
            with self.assertRaisesRegex(ValueError, "drift"):
                collector.ensure_run_manifest(path, {**first, "cutoff": "2026-07-27"})

    def test_index_detects_item_content_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(Path(raw), stage="profiles", shard_index=0, shard_count=1)
            store.save_item("horse-a", {"key": "horse-a", "status": "success", "value": 1})
            store.rebuild_index()
            store.item_path("horse-a").write_text(
                '{"key":"horse-a","status":"success","value":2}\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "content drift"):
                store.verify_index()

    def test_index_binds_manifest_upstream_inputs_and_tool_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = collector.StageStore(
                root,
                stage="profiles",
                shard_index=0,
                shard_count=1,
                manifest_sha256="manifest-a",
                upstream_indexes={"races": "races-a"},
                input_keys_sha256=collector.keys_sha256(["horse-a"]),
            )
            store.save_item("horse-a", {"key": "horse-a", "status": "success"})
            index = store.rebuild_index()
            self.assertEqual(index["manifest_sha256"], "manifest-a")
            self.assertEqual(index["upstream_indexes"], {"races": "races-a"})
            self.assertEqual(index["input_keys_sha256"], collector.keys_sha256(["horse-a"]))
            self.assertEqual(index["tool_identity"], collector.current_tool_identity_record())

            tampered = dict(index)
            tampered["upstream_indexes"] = {"races": "races-b"}
            collector.atomic_write_json(store.index_path, tampered)
            with self.assertRaisesRegex(ValueError, "upstream"):
                store.verify_index()

    def test_request_count_is_persisted_and_resumed_cumulatively(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            count = {"value": 0}
            attempts = {"b": 0}
            ticks = iter([0.0, 0.0, 0.0, 1.0, 1.0])
            store = collector.StageStore(root, stage="profiles", shard_index=0, shard_count=1)

            def process(key: str):
                count["value"] += 1
                if key == "b" and attempts["b"] == 0:
                    attempts["b"] += 1
                    raise OSError("retry")
                return {"key": key, "status": "success"}

            first = collector.run_checkpointed_items(
                ["a", "b", "c"], store=store, process=process, resume=True,
                request_counter=lambda: count["value"],
                time_budget_seconds=0.5,
                clock=lambda: next(ticks),
            )
            self.assertTrue(first["safe_stopped"])
            collector.run_checkpointed_items(
                ["a", "b", "c"], store=store, process=process, resume=True,
                request_counter=lambda: count["value"],
            )
            self.assertEqual(store.verify_index()["request_count"], 4)

    def test_budget_stop_saves_progress_and_resume_finishes(self):
        ticks = iter([0.0, 0.0, 1.0, 1.0, 1.0])
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(Path(raw), stage="profiles", shard_index=0, shard_count=1)
            first = collector.run_checkpointed_items(
                ["a", "b"],
                store=store,
                process=lambda key: {"key": key, "status": "success"},
                resume=True,
                time_budget_seconds=0.5,
                clock=lambda: next(ticks),
            )
            self.assertTrue(first["safe_stopped"])
            self.assertEqual(first["processed"], 1)
            second = collector.run_checkpointed_items(
                ["a", "b"],
                store=store,
                process=lambda key: {"key": key, "status": "success"},
                resume=True,
            )
            self.assertFalse(second["safe_stopped"])
            self.assertEqual(second["cached"], 1)
            self.assertEqual(len(store.verify_index()["items"]), 2)

    def test_completed_races_resume_is_byte_noop_even_with_retryable_errors(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = collector.StageStore(root, stage="races", shard_index=0, shard_count=1)
            requests = {"value": 0}

            def first_process(key: str):
                requests["value"] += 1
                if key == "race-b":
                    raise OSError("retryable but stage completed")
                return {"key": key, "status": "success"}

            first = collector.run_checkpointed_items(
                ["race-a", "race-b"],
                store=store,
                process=first_process,
                resume=True,
                request_counter=lambda: requests["value"],
                request_counter_start=0,
                now=lambda: "2026-07-27T00:00:00+00:00",
            )
            self.assertFalse(first["safe_stopped"])
            self.assertEqual(first["failed"], 1)
            self.assertEqual(store.verify_index()["request_count"], 2)
            before = {
                "index": store.index_path.read_bytes(),
                "progress": store.progress_path.read_bytes(),
                "items": {
                    path.name: path.read_bytes()
                    for path in sorted(store.items_dir.glob("*.json"))
                },
            }
            resumed_calls: list[str] = []

            def resumed_process(key: str):
                resumed_calls.append(key)
                requests["value"] += 1
                return {"key": key, "status": "success"}

            second = collector.run_checkpointed_items(
                ["race-a", "race-b"],
                store=store,
                process=resumed_process,
                resume=True,
                request_counter=lambda: requests["value"],
                now=lambda: "2026-07-28T00:00:00+00:00",
            )
            after = {
                "index": store.index_path.read_bytes(),
                "progress": store.progress_path.read_bytes(),
                "items": {
                    path.name: path.read_bytes()
                    for path in sorted(store.items_dir.glob("*.json"))
                },
            }
            self.assertEqual(resumed_calls, [])
            self.assertEqual(second["request_count"], 2)
            self.assertEqual(after, before)

            tampered_progress = json.loads(store.progress_path.read_text(encoding="utf-8"))
            tampered_progress["index_sha256"] = "0" * 64
            collector.atomic_write_json(store.progress_path, tampered_progress)
            with self.assertRaisesRegex(ValueError, "progress index drift"):
                collector.run_checkpointed_items(
                    ["race-a", "race-b"],
                    store=store,
                    process=resumed_process,
                    resume=True,
                    request_counter=lambda: requests["value"],
                )

    def test_safe_stopped_shard_resumes_retryable_items_and_finishes(self):
        ticks = iter([0.0, 0.0, 1.0, 1.0, 1.0])
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw), stage="wikidata_search", shard_index=0, shard_count=1
            )
            attempts: list[str] = []

            def first_process(key: str):
                attempts.append(f"first:{key}")
                raise OSError("temporary")

            first = collector.run_checkpointed_items(
                ["horse-a", "horse-b"],
                store=store,
                process=first_process,
                resume=True,
                time_budget_seconds=0.5,
                clock=lambda: next(ticks),
                now=lambda: "2026-07-27T00:00:00+00:00",
            )
            self.assertTrue(first["safe_stopped"])
            self.assertEqual(first["processed"], 1)

            def resumed_process(key: str):
                attempts.append(f"resume:{key}")
                return {"key": key, "status": "success"}

            second = collector.run_checkpointed_items(
                ["horse-a", "horse-b"],
                store=store,
                process=resumed_process,
                resume=True,
                now=lambda: "2026-07-27T00:10:00+00:00",
            )
            self.assertFalse(second["safe_stopped"])
            self.assertEqual(attempts, [
                "first:horse-a", "resume:horse-a", "resume:horse-b"
            ])
            self.assertEqual(
                [item["status"] for item in store.verify_index()["items"]],
                ["success", "success"],
            )

    def test_resume_recovers_verified_index_ahead_of_safe_stopped_progress(self):
        ticks = iter([0.0, 0.0, 1.0, 1.0, 1.0])
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw), stage="wikidata_search", shard_index=0, shard_count=1
            )
            first = collector.run_checkpointed_items(
                ["horse-a", "horse-b", "horse-c"],
                store=store,
                process=lambda key: {"key": key, "status": "success"},
                resume=True,
                time_budget_seconds=0.5,
                clock=lambda: next(ticks),
                now=lambda: "2026-07-28T00:00:00+00:00",
            )
            self.assertTrue(first["safe_stopped"])
            self.assertEqual(first["processed"], 1)

            old_progress = store.progress_path.read_bytes()
            store.save_item("horse-b", {"key": "horse-b", "status": "success"})
            advanced_index = store.rebuild_index(request_count=2)
            self.assertEqual(len(advanced_index["items"]), 2)
            self.assertEqual(store.progress_path.read_bytes(), old_progress)

            calls: list[str] = []

            def process(key: str):
                calls.append(key)
                return {"key": key, "status": "success"}

            resumed = collector.run_checkpointed_items(
                ["horse-a", "horse-b", "horse-c"],
                store=store,
                process=process,
                resume=True,
                now=lambda: "2026-07-28T00:10:00+00:00",
            )
            self.assertEqual(calls, ["horse-c"])
            self.assertFalse(resumed["safe_stopped"])
            self.assertEqual(resumed["processed"], resumed["total"])

    def test_resume_recovers_verified_partial_index_when_progress_is_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw), stage="profiles", shard_index=0, shard_count=1
            )
            store.save_item("horse-a", {"key": "horse-a", "status": "success"})
            store.input_keys_sha256 = collector.keys_sha256(["horse-a", "horse-b"])
            store.rebuild_index(request_count=1)
            self.assertFalse(store.progress_path.exists())
            calls: list[str] = []

            resumed = collector.run_checkpointed_items(
                ["horse-a", "horse-b"],
                store=store,
                process=lambda key: (
                    calls.append(key)
                    or {"key": key, "status": "success"}
                ),
                resume=True,
                now=lambda: "2026-07-28T00:10:00+00:00",
            )
            self.assertEqual(calls, ["horse-b"])
            self.assertFalse(resumed["safe_stopped"])
            self.assertEqual(resumed["processed"], resumed["total"])

            with tempfile.TemporaryDirectory() as complete_raw:
                complete = collector.StageStore(
                    Path(complete_raw), stage="profiles", shard_index=0, shard_count=1
                )
                for key in ("horse-a", "horse-b"):
                    complete.save_item(key, {"key": key, "status": "success"})
                complete.input_keys_sha256 = collector.keys_sha256(
                    ["horse-a", "horse-b"]
                )
                complete.rebuild_index(request_count=2)
                with self.assertRaisesRegex(
                    ValueError, "progress missing for complete index"
                ):
                    collector.run_checkpointed_items(
                        ["horse-a", "horse-b"],
                        store=complete,
                        process=lambda key: {"key": key, "status": "success"},
                        resume=True,
                    )

    def test_interrupted_resume_items_match_uninterrupted_baseline(self):
        keys = ["horse-a", "horse-b", "horse-c"]
        process = lambda key: {"key": key, "status": "success", "value": key.upper()}
        with tempfile.TemporaryDirectory() as interrupted_raw, tempfile.TemporaryDirectory() as baseline_raw:
            interrupted = collector.StageStore(
                Path(interrupted_raw), stage="profiles", shard_index=0, shard_count=1
            )
            ticks = iter([0.0, 0.0, 1.0, 1.0])
            collector.run_checkpointed_items(
                keys, store=interrupted, process=process, resume=True,
                time_budget_seconds=0.5, clock=lambda: next(ticks),
                now=lambda: "2026-07-26T00:00:00+00:00",
            )
            collector.run_checkpointed_items(
                keys, store=interrupted, process=process, resume=True,
                now=lambda: "2026-07-26T00:00:00+00:00",
            )
            baseline = collector.StageStore(
                Path(baseline_raw), stage="profiles", shard_index=0, shard_count=1
            )
            collector.run_checkpointed_items(
                keys, store=baseline, process=process, resume=True,
                now=lambda: "2026-07-26T00:00:00+00:00",
            )
            interrupted_items = {
                path.name: path.read_bytes() for path in interrupted.items_dir.glob("*.json")
            }
            baseline_items = {
                path.name: path.read_bytes() for path in baseline.items_dir.glob("*.json")
            }
            self.assertEqual(interrupted_items, baseline_items)
            self.assertEqual(
                interrupted.verify_index()["items_sha256"],
                baseline.verify_index()["items_sha256"],
            )

    def test_profile_merge_converges_same_url_and_keeps_fallback_separate(self):
        first = collector.seed_to_record(collector.HorseSeed(key="japan|name-a"))
        first.update(
            {"status": "success", "profile_urls": ["https://umafans.run/horses/10/"],
             "display_names": ["甲"], "regions": ["japan"]}
        )
        second = collector.seed_to_record(collector.HorseSeed(key="japan|alias-a"))
        second.update(
            {"status": "success", "profile_urls": ["https://umafans.run/horses/10/"],
             "display_names": ["A"], "regions": ["japan"]}
        )
        fallback = collector.seed_to_record(collector.HorseSeed(key="japan|同名马"))
        fallback.update(
            {"status": "success", "display_names": ["同名马"], "regions": ["japan"],
             "identity_confidence": "insufficient"}
        )
        merged = collector.merge_profile_records([fallback, second, first])
        self.assertEqual(len(merged), 2)
        canonical = next(item for item in merged if item["profile_urls"])
        self.assertEqual(canonical["lookup_keys"], ["japan|alias-a", "japan|name-a"])
        self.assertIn("japan|同名马", {item["key"] for item in merged})


class ResolutionAndNetworkContractTests(unittest.TestCase):
    def test_partial_search_failure_is_not_no_page(self):
        state = collector.resolution_outcome(
            search_requests=[
                {"status": "success", "candidates": []},
                {"status": "retryable_error", "error_code": "timeout"},
            ],
            entity_requests=[],
        )
        self.assertEqual(state["resolution_state"], "error")
        self.assertEqual(state["wikipedia_match_status"], "")

    def test_missing_entity_is_not_no_page(self):
        state = collector.resolution_outcome(
            search_requests=[{"status": "success", "candidates": ["Q1"]}],
            entity_requests=[{"qid": "Q1", "status": "not_found"}],
        )
        self.assertEqual(state["resolution_state"], "error")
        self.assertEqual(state["wikipedia_match_status"], "")

    def test_redirect_target_is_blocked_before_transport(self):
        self.assertEqual(
            collector.validate_request_url(
                "https://umafans.run/races/2026/a/", allowed_hosts={"umafans.run"}
            ),
            "https://umafans.run/races/2026/a/",
        )
        for url in (
            "http://127.0.0.1/private",
            "https://evil.example/race",
            "ftp://umafans.run/file",
            "https://umafans.run:444/race",
            "https://user@umafans.run/race",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                collector.validate_request_url(url, allowed_hosts={"umafans.run"})

    def test_insufficient_identity_cannot_be_exact(self):
        seed = collector.HorseSeed(
            key="japan|fallback",
            display_names={"Example"},
            identity_confidence="insufficient",
        )
        seed.candidate_meta["Q1"] = {
            "rank": 1,
            "descriptions": {"racehorse"},
            "matched_queries": {"Example"},
            "search_labels": {"Example"},
        }
        entity = {
            "labels": {"en": {"value": "Example"}},
            "descriptions": {"en": {"value": "racehorse"}},
            "aliases": {},
            "claims": {},
            "sitelinks": {"enwiki": {"title": "Example"}},
        }
        result = collector.score_seed_from_entities(
            seed,
            [{"status": "success", "candidates": ["Q1"]}],
            {"Q1": {"status": "success", "entity": entity}},
        )
        self.assertEqual(result.match_status, "probable")

    def test_search_resume_reuses_successful_subrequests(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            row = sample_row("japan|horse")
            _, manifest_sha = write_manifest(root, [row.race_url])
            race_store = collector.StageStore(
                root, stage="races", shard_index=0, shard_count=1,
                manifest_sha256=manifest_sha,
                input_keys_sha256=collector.keys_sha256([row.race_url]),
            )
            race_store.save_item(
                row.race_url,
                {"key": row.race_url, "status": "success",
                 "rows": [asdict(row), asdict(sample_row("japan|other", "乙"))],
                 "source": {"url": row.race_url, "sha256": "abc"}},
            )
            race_store.rebuild_index(request_count=1)
            seed = collector.HorseSeed(
                key="japan|horse", regions={"japan"}, display_names={"Horse"}
            )
            profile = collector.seed_to_record(seed)
            profile.update({"status": "success", "lookup_keys": [seed.key]})
            profile_store = collector.StageStore(
                root, stage="profiles_merged", shard_count=1,
                manifest_sha256=manifest_sha,
                upstream_indexes={"races": collector.upstream_index_sha(race_store)},
                input_keys_sha256=collector.keys_sha256([seed.key]),
            )
            profile_store.save_item(seed.key, profile)
            other_seed = collector.HorseSeed(
                key="japan|other", regions={"japan"}, display_names={"Other"}
            )
            other_profile = collector.seed_to_record(other_seed)
            other_profile.update({"status": "success", "lookup_keys": [other_seed.key]})
            profile_store.save_item(other_seed.key, other_profile)
            profile_store.input_keys_sha256 = collector.keys_sha256(
                [seed.key, other_seed.key]
            )
            profile_store.rebuild_index()
            calls: list[str] = []

            class FakeResolver:
                attempt = 0

                def __init__(self, **kwargs):
                    FakeResolver.attempt += 1

                def _search_queries(self, _seed):
                    return ["Horse"]

                def _query_languages(self, _query):
                    return ["en", "ja"]

                def _search(self, _query, language):
                    calls.append(language)
                    if language == "ja" and FakeResolver.attempt == 1:
                        raise OSError("temporary")
                    return []

            args = collector.parse_args(
                ["--stage", "wikidata_search", "--resume", "--output-dir", raw]
            )
            original_runner = collector.run_checkpointed_items
            ticks = iter([0.0, 0.0, 1.0, 1.0])

            def safe_stop_after_first(*runner_args, **runner_kwargs):
                runner_kwargs["time_budget_seconds"] = 0.5
                runner_kwargs["clock"] = lambda: next(ticks)
                return original_runner(*runner_args, **runner_kwargs)

            with patch.object(collector, "make_client", return_value=FakeClient({})), patch.object(
                collector, "WikidataResolver", FakeResolver
            ), patch.object(
                collector, "run_checkpointed_items", side_effect=safe_stop_after_first
            ):
                collector.run_stage(args)
            with patch.object(collector, "make_client", return_value=FakeClient({})), patch.object(
                collector, "WikidataResolver", FakeResolver
            ):
                collector.run_stage(args)
            self.assertEqual(calls, ["en", "ja", "ja", "en", "ja"])
            result = collector.StageStore(
                root, stage="wikidata_search", shard_index=0, shard_count=1
            ).load_item(seed.key)
            self.assertEqual(result["status"], "success")

    def test_profile_detail_transport_failure_is_retryable(self):
        search_url = "https://umafans.run/horses/"
        detail_url = "https://umafans.run/horses/10/"
        search = """
        <article class="horse-card">
          <div class="horse-card-name"><a href="/horses/10/">甲</a></div>
          <div class="region-label">日本</div>
        </article>
        """
        instance = collector.UmaFansCollector(
            base_url="https://umafans.run",
            client=FakeClient(
                {
                    search_url: FakeResponse(search, search_url),
                    detail_url: OSError("detail transport failed"),
                }
            ),
            output_dir=Path(tempfile.mkdtemp()),
            year=2026,
            cutoff=date(2026, 7, 26),
        )
        with self.assertRaisesRegex(collector.ProfileDetailError, "detail transport"):
            instance.find_horse_profile("甲", "japan")


class ManifestContractTests(unittest.TestCase):
    def test_manifest_recomputes_race_urls_and_all_identity_fields(self):
        identity = collector.current_tool_identity_record()
        manifest = {
            **identity,
            "year": 2026,
            "cutoff": "2026-07-26",
            "base_url": "https://umafans.run",
            "requested_base_url": "https://umafans.run",
            "race_urls": ["https://umafans.run/races/2026/test/"],
            "race_urls_sha256": collector.sha256_bytes(
                collector.canonical_json_bytes(["https://umafans.run/races/2026/test/"])
            ),
            "created_at": "2026-07-26T00:00:00+00:00",
        }
        collector.validate_run_manifest(manifest)
        for field, value in (
            ("race_urls_sha256", "0" * 64),
            ("collector_source_sha256", "0" * 64),
            ("parser_version", "old-parser"),
            ("scorer_version", "old-scorer"),
            ("schema_version", 999),
            ("base_commit", "wrong-commit"),
            ("tool_version", "wrong-tool"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "manifest"):
                collector.validate_run_manifest({**manifest, field: value})


class OfflineFinalizeTests(unittest.TestCase):
    def test_finalize_is_offline_and_deterministic(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            row = sample_row()
            _, manifest_sha = write_manifest(root, [row.race_url])
            race_store = collector.StageStore(
                root, stage="races", shard_index=0, shard_count=1,
                manifest_sha256=manifest_sha,
                input_keys_sha256=collector.keys_sha256([row.race_url]),
            )
            race_store.save_item(
                row.race_url,
                {"key": row.race_url, "status": "success", "rows": [asdict(row)],
                 "source": {"url": row.race_url, "sha256": "abc"}},
            )
            race_store.rebuild_index()
            seed = collector.HorseSeed(key="japan|甲", regions={"japan"}, display_names={"甲"})
            profile = collector.seed_to_record(seed)
            profile.update({"status": "success", "lookup_keys": ["japan|甲"]})
            race_sha = collector.upstream_index_sha(race_store)
            profile_store = collector.StageStore(
                root, stage="profiles_merged", shard_count=1,
                manifest_sha256=manifest_sha,
                upstream_indexes={"races": race_sha},
                input_keys_sha256=collector.keys_sha256([seed.key]),
            )
            profile_store.save_item(seed.key, profile)
            profile_store.rebuild_index()
            profile_sha = collector.upstream_index_sha(profile_store)
            search_store = collector.StageStore(
                root, stage="wikidata_search_merged", shard_count=1,
                manifest_sha256=manifest_sha,
                upstream_indexes={"profiles_merged": profile_sha},
                input_keys_sha256=collector.keys_sha256([seed.key]),
            )
            search_record = dict(profile)
            search_record["search_requests"] = [
                {"query": "甲", "language": "ja", "status": "success", "candidates": []}
            ]
            search_store.save_item(seed.key, search_record)
            search_store.rebuild_index(request_count=1)
            search_sha = collector.upstream_index_sha(search_store)
            entity_store = collector.StageStore(
                root, stage="wikidata_entities_merged", shard_count=1,
                manifest_sha256=manifest_sha,
                upstream_indexes={"wikidata_search_merged": search_sha},
                input_keys_sha256=collector.keys_sha256([]),
            )
            entity_store.rebuild_index(request_count=0)
            entity_sha = collector.upstream_index_sha(entity_store)
            scored = collector.seed_to_record(seed)
            scored.update({"status": "success", "match_status": "no_page"})
            score_store = collector.StageStore(
                root, stage="scored_horses_merged", shard_count=1,
                manifest_sha256=manifest_sha,
                upstream_indexes={
                    "wikidata_search_merged": search_sha,
                    "wikidata_entities_merged": entity_sha,
                },
                input_keys_sha256=collector.keys_sha256([seed.key]),
            )
            score_store.save_item(seed.key, scored)
            score_store.rebuild_index()
            args = collector.parse_args(["--stage", "finalize", "--output-dir", raw])
            with patch.object(collector, "make_client", side_effect=AssertionError("network")):
                collector.run_stage(args)
                first = {
                    path.name: path.read_bytes()
                    for path in (root / "final").iterdir()
                    if path.is_file()
                }
                collector.run_stage(args)
                second = {
                    path.name: path.read_bytes()
                    for path in (root / "final").iterdir()
                    if path.is_file()
                }
            self.assertEqual(first, second)
            self.assertEqual(
                set(first),
                {
                    "race_top5_2026.csv", "horse_wikipedia_mapping_2026.csv",
                    "wikipedia_review_queue_2026.csv", "source_manifest.jsonl",
                    "summary.json", "errors.json", "README.md",
                },
            )

    def test_finalize_aggregates_structured_errors_and_request_counts(self):
        with tempfile.TemporaryDirectory() as raw:
            result = collector.run_synthetic_smoke(Path(raw), stop_after=0)
            self.assertTrue(result["byte_equivalent"])
            final = Path(raw) / "final"
            summary = json.loads((final / "summary.json").read_text(encoding="utf-8"))
            errors = json.loads((final / "errors.json").read_text(encoding="utf-8"))
            review = (final / "wikipedia_review_queue_2026.csv").read_text(encoding="utf-8-sig")
            review_rows = list(csv.DictReader(io.StringIO(review)))
            self.assertGreater(summary["source"]["http_request_count"], 0)
            self.assertEqual(summary["source"]["all_errors"], len(errors))
            self.assertTrue(all({"stage", "key", "status", "error_code"} <= set(item) for item in errors))
            self.assertIn("profile_detail_transport_error", review)
            self.assertEqual(
                summary["counts"]["resolution_error"],
                sum(row["resolution_state"] == "error" for row in review_rows),
            )

    def test_synthetic_smoke_safe_stop_resume_matches_baseline(self):
        with tempfile.TemporaryDirectory() as raw:
            first = collector.run_synthetic_smoke(Path(raw), stop_after=1)
            self.assertEqual(first["exit_code"], 75)
            self.assertEqual(
                json.loads((Path(raw) / "safe_stop.json").read_text())["exit_code"], 75
            )
            resumed = collector.run_synthetic_smoke(Path(raw), stop_after=0)
            self.assertTrue(resumed["safe_stop_evidence_present"])
            self.assertTrue(resumed["byte_equivalent"])
            self.assertEqual(
                resumed["recovered_items_sha256"], resumed["baseline_items_sha256"]
            )


class WorkflowContractTests(unittest.TestCase):
    @staticmethod
    def workflow_text():
        return (
            SCRIPT_PATH.parents[2]
            / ".github/workflows/research_2026_graded_top5_wikipedia.yml"
        ).read_text(encoding="utf-8")

    @staticmethod
    def job_block(workflow: str, job_name: str) -> str:
        remainder = workflow.split(f"\n  {job_name}:\n", 1)[1]
        return re.split(r"\n  [a-z_]+:\n", remainder, maxsplit=1)[0]

    def test_workflow_is_staged_and_does_not_patch_source(self):
        workflow = self.workflow_text()
        self.assertNotIn("path.write_text(text.replace", workflow)
        for job in (
            "tests:",
            "races:",
            "profiles:",
            "merge_profiles:",
            "wikidata_search:",
            "merge_search:",
            "wikidata_entities:",
            "merge_entities:",
            "score_horses:",
            "merge_scores:",
            "finalize:",
        ):
            self.assertIn(job, workflow)
        self.assertIn("fail-fast: false", workflow)
        self.assertIn("github.run_attempt", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("actions/download-artifact@v4", workflow)
        self.assertIn("full_network:", workflow)
        self.assertIn("default: false", workflow)
        self.assertGreaterEqual(
            workflow.count("github.event_name == 'workflow_dispatch' && inputs.full_network"), 10
        )
        self.assertIn("--time-budget-seconds 4500", workflow)
        self.assertIn("timeout-minutes: 90", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("--stage finalize", workflow)
        self.assertNotIn("pattern:", workflow)
        self.assertNotIn("merge-multiple:", workflow)
        self.assertIn("source_run_id:", workflow)
        self.assertIn("source_attempt:", workflow)
        self.assertIn("--stage synthetic_smoke", workflow)
        self.assertIn('SAFE_STOP_CODE: "75"', workflow)
        self.assertIn("/stages/", workflow)
        self.assertNotIn("test_collect_2026_graded_top5_wikipedia.py\n          retention-days", workflow)
        self.assertNotIn(
            'test "$code" -eq 0 -o "$code" -eq "$SAFE_STOP_CODE"',
            workflow,
        )
        for stage in (
            "races", "profiles", "wikidata_search", "wikidata_entities", "score_horses"
        ):
            job = self.job_block(workflow, stage)
            self.assertNotIn("set +e", job)
            self.assertNotIn("code=$?", job)
            self.assertIn("if: always()", job)

    def test_workflow_source_stage_restores_only_existing_prefix(self):
        workflow = self.workflow_text()
        dispatch = workflow.split("permissions:", 1)[0]
        self.assertIn("source_stage:", dispatch)
        for stage in (
            "races", "profiles", "wikidata_search", "wikidata_entities", "score_horses"
        ):
            self.assertRegex(dispatch, rf"(?m)^\s+- {stage}$")

        expected_guards = {
            "races": "inputs.source_stage != ''",
            "profiles": "inputs.source_stage != 'races'",
            "wikidata_search": (
                "contains('wikidata_search,wikidata_entities,score_horses', "
                "inputs.source_stage)"
            ),
            "wikidata_entities": (
                "contains('wikidata_entities,score_horses', inputs.source_stage)"
            ),
            "score_horses": "inputs.source_stage == 'score_horses'",
        }
        for stage, guard in expected_guards.items():
            job = self.job_block(workflow, stage)
            source_name = (
                "${{ inputs.source_run_id }}-${{ inputs.source_attempt }}-"
                f"{stage}-"
            )
            self.assertIn(source_name, job)
            self.assertIn(guard, job)

        self.assertIn(
            "source_run_id, source_attempt and source_stage must be provided together",
            workflow,
        )
        self.assertIn(
            "(inputs.source_run_id == '' || inputs.source_attempt == '' || "
            "inputs.source_stage == '')",
            workflow,
        )
        self.assertIn(
            "(inputs.source_run_id != '' || inputs.source_attempt != '' || "
            "inputs.source_stage != '')",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
