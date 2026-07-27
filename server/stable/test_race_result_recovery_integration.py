from __future__ import annotations

import json
import tempfile
import csv
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from stable.models import (
    RaceEvent,
    RaceEventModule,
    RaceEventPriority,
    RaceEventResult,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceGrade,
    RacingRegion,
)
from stable.services import historical_batch_runner
from stable.services import race_event_crawl_orchestration as orchestration
from stable.services import race_result_recovery_inventory


RECOVERY_SOURCE_MAP = (
    {
        "region": RacingRegion.JAPAN,
        "source": "jra",
        "adapter": "jra_detail",
        "event_ids": [80, 81, 82, 83],
    },
    {
        "region": RacingRegion.JAPAN,
        "source": "nar",
        "adapter": "nar_detail",
        "event_ids": [184, 185],
    },
    {
        "region": RacingRegion.UNITED_KINGDOM,
        "source": "sporting_life",
        "adapter": "uk_sporting_life_detail",
        "event_ids": [917, 918, 919, 920, 921, 922, 923, 925, 926, 927, 928],
    },
    {
        "region": RacingRegion.FRANCE,
        "source": "zeturf",
        "adapter": "france_zeturf_detail",
        "event_ids": [733, 734, 735, 736],
    },
    {
        "region": RacingRegion.UNITED_STATES,
        "source": "sporting_life",
        "adapter": "us_sporting_life_results",
        "event_ids": [
            406, 407, 411, 412, 413, 414, 415, 416, 417, 418, 419, 420,
            421, 422, 423, 424, 425, 426, 427,
        ],
    },
)

EXPECTED_EVENT_IDS_BY_REGION = {
    RacingRegion.JAPAN: {80, 81, 82, 83, 184, 185},
    RacingRegion.UNITED_KINGDOM: {917, 918, 919, 920, 921, 922, 923, 925, 926, 927, 928},
    RacingRegion.FRANCE: {733, 734, 735, 736},
    RacingRegion.UNITED_STATES: {
        406,
        407,
        411,
        412,
        413,
        414,
        415,
        416,
        417,
        418,
        419,
        420,
        421,
        422,
        423,
        424,
        425,
        426,
        427,
    },
}

EXCLUDED_EVENT_IDS = {
    79,
    405,
    408,
    409,
    410,
    729,
    730,
    731,
    732,
    924,
    15441,
    15484,
    15487,
    15587,
    15640,
    16176,
    16193,
    16198,
    16199,
}


class RaceResultRecoveryPlanIntegrationTests(SimpleTestCase):
    def _plan(self) -> dict:
        regions = []
        adapters = []
        for entry in RECOVERY_SOURCE_MAP:
            regions.append(
                {
                    "region": entry["region"],
                    "source": entry["source"],
                    "source_authority": orchestration.DEFAULT_SOURCE_AUTHORITY_MATRIX[
                        entry["source"]
                    ]["authority"],
                    "event_ids": list(entry["event_ids"]),
                    "modules": {RaceEventModule.RESULTS: {}},
                }
            )
            adapters.append(entry["adapter"])
        return {
            "run_id": "race-result-recovery-20260727",
            "purpose": "race_result_recovery",
            "target_layer": "race_event",
            "inventory_manifest_sha256": "a" * 64,
            "inventory_artifact_path": "/approved/recovery-inventory.json",
            "inventory_artifact_sha256": "b" * 64,
            "source_map_version": "2026-07-27-gap-v2",
            "allow_network": False,
            "batch_size": 40,
            "max_source_cache_bytes": 512 * 1024 * 1024,
            "rate_limit": {"max_requests": 75, "request_interval_seconds": 1},
            "regions": regions,
            "adapters": adapters,
        }

    def test_results_only_recovery_plan_accepts_exact_forty_event_source_map(self):
        validated = orchestration.validate_plan(self._plan())

        observed: dict[str, set[int]] = {}
        for region_plan in validated["regions"]:
            observed.setdefault(region_plan["region"], set()).update(region_plan["event_ids"])

        self.assertEqual(observed, EXPECTED_EVENT_IDS_BY_REGION)
        all_ids = set().union(*observed.values())
        self.assertEqual(len(all_ids), 40)
        self.assertTrue(all_ids.isdisjoint(EXCLUDED_EVENT_IDS))
        self.assertTrue(
            all(set(region["modules"]) == {RaceEventModule.RESULTS}
                for region in validated["regions"])
        )

    def test_recovery_source_map_rejects_event_924_or_scope_shrink(self):
        for mutation in ("inject_live_event", "drop_missing_event"):
            with self.subTest(mutation=mutation):
                plan = self._plan()
                if mutation == "inject_live_event":
                    plan["regions"][2]["event_ids"].append(924)
                else:
                    plan["regions"][4]["event_ids"].remove(406)
                with self.assertRaisesRegex(
                    orchestration.PlanValidationError,
                    "source.map|frozen.*event|event.*scope",
                ):
                    orchestration.validate_plan(plan)

    def test_recovery_source_map_version_is_required(self):
        plan = self._plan()
        plan.pop("source_map_version")

        with self.assertRaisesRegex(
            orchestration.PlanValidationError,
            "source map version",
        ):
            orchestration.validate_plan(plan)

    def test_non_recovery_results_only_plan_keeps_legacy_three_module_gate(self):
        plan = self._plan()
        plan.pop("purpose")
        with self.assertRaisesRegex(
            orchestration.PlanValidationError,
            "missing required modules.*runners.*history_winners",
        ):
            orchestration.validate_plan(plan)


class RaceResultRecoveryExpectedTargetTests(TestCase):
    def _plan(self, root: Path) -> dict:
        plan = RaceResultRecoveryPlanIntegrationTests()._plan()
        recovery_date = timezone.localdate() - timedelta(days=2)
        artifact = race_result_recovery_inventory.build_recovery_inventory(
            start_date=recovery_date,
            end_date=recovery_date,
            as_of=timezone.now(),
            expected_event_ids=[
                event_id
                for entry in RECOVERY_SOURCE_MAP
                for event_id in entry["event_ids"]
            ],
        )
        inventory_path = root / "inventory.json"
        identity = race_result_recovery_inventory.write_immutable_inventory(
            artifact,
            inventory_path,
        )
        plan.update(
            {
                "inventory_manifest_sha256": artifact["manifest_sha256"],
                "inventory_artifact_path": str(inventory_path),
                "inventory_artifact_sha256": identity["sha256"],
            }
        )
        return plan

    def _create_frozen_events(self) -> None:
        timezone_by_region = {
            RacingRegion.JAPAN: "Asia/Tokyo",
            RacingRegion.UNITED_KINGDOM: "Europe/London",
            RacingRegion.FRANCE: "Europe/Paris",
            RacingRegion.UNITED_STATES: "America/New_York",
        }
        for entry in RECOVERY_SOURCE_MAP:
            for event_id in entry["event_ids"]:
                RaceEvent.objects.create(
                    id=event_id,
                    year=2026,
                    slug=f"recovery-event-{event_id}",
                    series_key=f"recovery-series-{event_id}",
                    original_name=f"Recovery Event {event_id}",
                    chinese_name=f"恢复赛事 {event_id}",
                    country_region=entry["region"],
                    racecourse="Approved Racecourse",
                    grade_text="G1",
                    normalized_grade=RaceGrade.G1,
                    surface=RaceEventSurface.TURF,
                    distance_text="1600m",
                    local_date=timezone.localdate() - timedelta(days=2),
                    timezone_name=timezone_by_region[entry["region"]],
                    priority=RaceEventPriority.P1,
                    status=RaceEventStatus.SCHEDULED,
                    visibility_status=RaceEventVisibility.PUBLISHED,
                )

    def test_exact_recovery_event_ids_generate_forty_bound_expected_targets(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            targets = orchestration.expected_targets_from_plan(plan)

        self.assertEqual(len(targets), 40)
        self.assertEqual(
            [target["race_event_id"] for target in targets],
            [
                event_id
                for entry in RECOVERY_SOURCE_MAP
                for event_id in entry["event_ids"]
            ],
        )
        self.assertTrue(all(target["preflight_status"] == "ready" for target in targets))
        self.assertEqual(
            {
                (target["race_event_id"], target["source"])
                for target in targets
            },
            {
                (event_id, entry["source"])
                for entry in RECOVERY_SOURCE_MAP
                for event_id in entry["event_ids"]
            },
        )
        self.assertTrue(all(target["modules"] == [RaceEventModule.RESULTS] for target in targets))
        self.assertTrue(all(target["adapter_input"] for target in targets))

    def test_recovery_expected_targets_fail_closed_when_event_disappears(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            RaceEvent.objects.filter(pk=80).delete()
            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "recovery inventory drift",
            ):
                orchestration.expected_targets_from_plan(plan)

    def test_recovery_expected_targets_require_exact_inventory_file_sha(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            plan["inventory_artifact_sha256"] = "f" * 64

            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "artifact SHA does not match",
            ):
                orchestration.expected_targets_from_plan(plan)

    def test_recovery_expected_targets_fail_closed_on_region_drift(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            RaceEvent.objects.filter(pk=80).update(
                country_region=RacingRegion.UNITED_KINGDOM
            )
            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "recovery inventory drift.*event_identity_drift",
            ):
                orchestration.expected_targets_from_plan(plan)

    def test_recovery_expected_targets_fail_closed_on_result_or_status_drift(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            RaceEvent.objects.filter(pk=80).update(status=RaceEventStatus.FINISHED)
            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "recovery inventory drift.*event_identity_drift",
            ):
                orchestration.expected_targets_from_plan(plan)

        RaceEvent.objects.filter(pk=80).update(status=RaceEventStatus.SCHEDULED)
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            RaceEventResult.objects.create(
                event_id=80,
                finish_position=1,
                horse_name="Late Result",
                is_confirmed=False,
            )
            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "recovery inventory drift.*result_identity_drift",
            ):
                orchestration.expected_targets_from_plan(plan)

    def test_create_run_emits_reviewable_recovery_snapshot(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "approved-plan.json"
            plan_path.write_text(json.dumps(self._plan(root)), encoding="utf-8")

            state = orchestration.create_run(plan_path, root / "run")
            snapshot = json.loads(
                Path(state.artifacts["expected_targets"]).read_text(encoding="utf-8")
            )
            approval = json.loads(
                Path(state.artifacts["expected_targets_approval"]).read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(snapshot["expected_target_count"], 40)
        self.assertEqual(snapshot["preflight_blocker_count"], 0)
        self.assertEqual(approval["status"], "pending")

    def test_existing_recovery_snapshot_is_rejected_after_inventory_drift(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "approved-plan.json"
            plan_path.write_text(json.dumps(self._plan(root)), encoding="utf-8")
            run_dir = root / "run"
            orchestration.create_run(plan_path, run_dir)
            RaceEvent.objects.filter(pk=80).update(status=RaceEventStatus.FINISHED)

            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "recovery inventory drift.*event_identity_drift",
            ):
                orchestration.create_run(plan_path, run_dir)

    def test_adapter_inputs_are_source_scoped_within_shared_regions(self):
        self._create_frozen_events()
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = {
                "targets": orchestration.expected_targets_from_plan(
                    self._plan(Path(tmp))
                )
            }
            with self.assertNumQueries(2):
                inputs = orchestration.materialize_adapter_event_inputs(
                    expected_snapshot=snapshot,
                    run_dir=tmp,
                )
            jra_rows = list(
                csv.DictReader(
                    Path(inputs["japan:jra"]).open(encoding="utf-8-sig")
                )
            )
            nar_rows = list(
                csv.DictReader(
                    Path(inputs["japan:nar"]).open(encoding="utf-8-sig")
                )
            )

        self.assertEqual(
            {row["slug"] for row in jra_rows},
            {f"recovery-event-{event_id}" for event_id in (80, 81, 82, 83)},
        )
        self.assertEqual(
            {row["slug"] for row in nar_rows},
            {f"recovery-event-{event_id}" for event_id in (184, 185)},
        )
        self.assertEqual(
            {int(row["event_id"]) for row in jra_rows},
            {80, 81, 82, 83},
        )
        self.assertEqual(
            {int(row["event_id"]) for row in nar_rows},
            {184, 185},
        )


class RaceResultRecoveryJraControlTests(SimpleTestCase):
    def _tool(self):
        tools_dir = Path(__file__).resolve().parents[2] / "runtime" / "tools"
        sys.path.insert(0, str(tools_dir))
        try:
            spec = importlib.util.spec_from_file_location(
                "prepare_jra_race_detail_candidates_recovery_test",
                tools_dir / "prepare_jra_race_detail_candidates.py",
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(tools_dir))

    def test_jra_manifest_accepts_runner_materialized_list_and_control_inputs(self):
        manifest = orchestration.adapter_manifest_for_key("jra_detail")

        self.assertFalse(manifest.inputs["source_html"]["required"])
        for argument in (
            "--request-policy",
            "--request-shard-id",
            "--request-state",
            "--host-state-root",
        ):
            self.assertIn(argument, manifest.command)

    def test_jra_control_inputs_bind_exact_hosts_paths_and_shared_budget(self):
        manifest = orchestration.adapter_manifest_for_key("jra_detail")
        plan = {
            "run_id": "race-result-recovery-20260727",
            "rate_limit": {"max_requests": 75, "request_interval_seconds": 1},
        }
        with tempfile.TemporaryDirectory() as tmp:
            inputs = orchestration.materialize_adapter_control_inputs(
                plan=plan,
                manifest=manifest,
                run_dir=tmp,
            )
            policy = json.loads(Path(inputs["request_policy"]).read_text(encoding="utf-8"))

        self.assertEqual(policy["allowed_hosts"], ["www.jra.go.jp"])
        self.assertEqual(policy["redirect_hosts"], ["www.jra.go.jp"])
        self.assertEqual(policy["max_requests"], 75)
        self.assertEqual(policy["minimum_interval_seconds"], 1)
        self.assertEqual(
            policy["url_patterns"]["www.jra.go.jp"],
            [
                r"/datafile/seiseki/replay/2026/jyusyo\.html",
                r"/datafile/seiseki/replay/2026/\d{3}\.html",
                r"/datafile/seiseki/g1/[a-z0-9_-]+/result/[a-z0-9_-]+2026\.html",
            ],
        )
        self.assertTrue(Path(inputs["source_html"]).name == "jra.html")
        self.assertIn("jra_detail", inputs["request_shard_id"])

    def test_jra_download_reserves_shared_and_controlled_request_budgets(self):
        tool = self._tool()
        context = {
            "request_policy": {"approved": True},
            "shard_id": "recovery-jra",
            "shard_state_path": "/tmp/recovery-jra-state.json",
            "host_state_root": "/tmp/recovery-jra-hosts",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            tool,
            "before_network_request",
        ) as shared_budget, patch.object(
            tool,
            "controlled_http_get",
            return_value=b"official jra html",
        ) as controlled, patch.object(
            tool,
            "write_source_cache",
        ) as cache:
            destination = Path(tmp) / "source.html"
            body = tool._download(
                tool.JRA_RESULT_LIST_URL,
                destination,
                allow_network=True,
                timeout=30,
                request_context=context,
            )

        self.assertEqual(body, b"official jra html")
        shared_budget.assert_not_called()
        controlled.assert_called_once_with(
            tool.JRA_RESULT_LIST_URL,
            policy=context["request_policy"],
            shard_id=context["shard_id"],
            shard_state_path=context["shard_state_path"],
            host_state_root=context["host_state_root"],
            timeout=30,
            headers={"User-Agent": "UmaFansBot/1.0"},
            before_request=shared_budget,
        )
        cache.assert_called_once()

    def test_jra_recovery_mode_accepts_scheduled_targets_without_legacy_widening(self):
        tool = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / "events.csv"
            events.write_text(
                "slug,status\nscheduled-race,scheduled\nfinished-race,finished\n",
                encoding="utf-8",
            )

            legacy = tool._read_finished_events(events)
            recovery = tool._read_finished_events(events, recovery_mode=True)

        self.assertEqual([row["slug"] for row in legacy], ["finished-race"])
        self.assertEqual(
            [row["slug"] for row in recovery],
            ["scheduled-race", "finished-race"],
        )

    def test_jra_recovery_prepare_emits_candidate_for_scheduled_target(self):
        tool = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.csv"
            events.write_text(
                "year,slug,original_name,aliases,status\n"
                "2026,recovery-event-80,小倉記念,,scheduled\n",
                encoding="utf-8",
            )
            source_html = root / "jra.html"
            source_html.write_bytes(
                (
                    '<table><tr><td>GIII 小倉記念</td>'
                    '<td><a href="/datafile/seiseki/replay/2026/063.html">'
                    "結果</a></td></tr></table>"
                ).encode("cp932")
            )
            args = SimpleNamespace(
                output_dir=str(root / "output"),
                events_csv=str(events),
                source_html=str(source_html),
                allow_network=True,
                recovery_mode=True,
                limit=0,
                timeout_seconds=30,
                fail_fast=True,
                request_policy=str(root / "policy.json"),
                request_shard_id="recovery-jra",
                request_state=str(root / "request-state.json"),
                host_state_root=str(root / "host-state"),
            )
            Path(args.request_policy).write_text("{}", encoding="utf-8")
            with patch.object(
                tool,
                "_request_context_from_args",
                return_value={"controlled": True},
            ), patch.object(
                tool,
                "_download",
                return_value=b"detail",
            ), patch.object(
                tool,
                "_parse_detail_page",
                return_value=(
                    [{"horse_name": "Runner"}],
                    [{"horse_name": "Winner", "jockey_name": "Jockey"}],
                    {"race_title": "小倉記念"},
                ),
            ):
                summary = tool.prepare_candidates(args)

            records = [
                json.loads(line)
                for line in (
                    Path(args.output_dir) / "jra_detail_candidates_2026.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(summary["events"], 1)
        self.assertEqual(records[0]["slug"], "recovery-event-80")

    def test_jra_interruption_is_preserved_without_inventing_a_finish_position(self):
        tool = self._tool()
        source_url = "https://www.jra.go.jp/datafile/seiseki/replay/2026/063.html"
        body = (
            '<div class="race_header">2026年7月19日 小倉</div>'
            '<div class="race_title">小倉記念</div>'
            "<table>"
            "<tr><th>着順</th></tr>"
            '<tr><td class="place">1</td><td class="num">1</td>'
            '<td class="horse">Winner</td></tr>'
            '<tr><td class="place">2</td><td class="num">2</td>'
            '<td class="horse">Runner-up</td></tr>'
            '<tr><td class="place">中止</td><td class="num">5</td>'
            '<td class="horse">エヒト</td></tr>'
            "</table>"
        ).encode("cp932")

        runners, results, metadata = tool._parse_detail_page(
            body,
            source_url=source_url,
        )

        self.assertEqual([row["finish_position"] for row in results], [1, 2])
        self.assertNotIn(
            "5",
            {row["horse_number"] for row in results},
            "中止马不得被补造为数值名次",
        )
        interrupted = next(row for row in runners if row["horse_number"] == "5")
        self.assertEqual(interrupted["running_status"], "pulled_up")
        self.assertEqual(
            interrupted["source_refs"]["jra_finish_position_text"],
            "中止",
        )
        self.assertEqual(metadata["row_count"], 3)
        self.assertEqual(metadata["result_count"], 2)

        record = {
            "modules": {
                RaceEventModule.RUNNERS: {"items": runners},
                RaceEventModule.RESULTS: {"items": results},
            }
        }
        orchestration._annotate_recovery_result_order(record)

        self.assertTrue(record["metadata"]["result_order_complete"])
        self.assertEqual(
            record["metadata"]["result_order_check"]["reason"],
            "complete",
        )


class RaceResultRecoveryAdapterModeTests(SimpleTestCase):
    def _tool(self, filename: str):
        tools_dir = Path(__file__).resolve().parents[2] / "runtime" / "tools"
        sys.path.insert(0, str(tools_dir))
        try:
            spec = importlib.util.spec_from_file_location(
                f"{Path(filename).stem}_recovery_test",
                tools_dir / filename,
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(tools_dir))

    def test_runner_passes_recovery_mode_to_all_status_filtered_detail_adapters(self):
        plan = {
            "run_id": "race-result-recovery-20260727",
            "purpose": "race_result_recovery",
            "rate_limit": {"max_requests": 75, "request_interval_seconds": 1},
        }
        for key in (
            "nar_detail",
            "uk_sporting_life_detail",
            "france_zeturf_detail",
            "us_sporting_life_results",
        ):
            with self.subTest(adapter=key), tempfile.TemporaryDirectory() as tmp:
                manifest = orchestration.adapter_manifest_for_key(key)
                inputs = orchestration.materialize_adapter_control_inputs(
                    plan=plan,
                    manifest=manifest,
                    run_dir=tmp,
                )

                self.assertEqual(inputs["recovery_flag"], "--recovery-mode")
                self.assertIn("{recovery_flag}", manifest.command)

    def test_uk_and_us_sporting_life_use_disjoint_standard_outputs(self):
        uk = orchestration.adapter_manifest_for_key(
            "uk_sporting_life_detail"
        )
        us = orchestration.adapter_manifest_for_key(
            "us_sporting_life_results"
        )

        uk_outputs = {
            str(output["key"]): str(output.get("standard_name") or "")
            for output in uk.outputs
        }
        us_outputs = {
            str(output["key"]): str(output.get("standard_name") or "")
            for output in us.outputs
        }

        self.assertEqual(set(uk_outputs), set(us_outputs))
        for key in uk_outputs:
            with self.subTest(output=key):
                self.assertNotEqual(uk_outputs[key], us_outputs[key])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collected = {}
            for manifest, marker in ((uk, "uk"), (us, "us")):
                adapter_dir = root / "adapter_runs" / manifest.key
                for output in manifest.outputs:
                    output_path = adapter_dir / str(output["path"])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if output_path.suffix == ".jsonl":
                        output_path.write_text(
                            json.dumps({"marker": marker}) + "\n",
                            encoding="utf-8",
                        )
                    elif output_path.suffix == ".json":
                        output_path.write_text("{}\n", encoding="utf-8")
                    else:
                        output_path.write_text(
                            "marker\n" + marker + "\n",
                            encoding="utf-8",
                        )
                collected[marker] = orchestration.AdapterRunner(
                    manifest
                )._collect_outputs(root, adapter_dir)

            uk_candidate = Path(
                collected["uk"]["candidate_jsonl"].path
            )
            us_candidate = Path(
                collected["us"]["candidate_jsonl"].path
            )

            self.assertNotEqual(uk_candidate, us_candidate)
            self.assertEqual(
                json.loads(uk_candidate.read_text(encoding="utf-8"))["marker"],
                "uk",
            )
            self.assertEqual(
                json.loads(us_candidate.read_text(encoding="utf-8"))["marker"],
                "us",
            )

    def test_legacy_mode_still_filters_scheduled_targets(self):
        cases = (
            ("prepare_uk_sportinglife_race_detail_candidates.py", True),
            ("prepare_france_zeturf_race_detail_candidates.py", False),
        )
        for filename, multiple_paths in cases:
            with self.subTest(tool=filename), tempfile.TemporaryDirectory() as tmp:
                tool = self._tool(filename)
                events = Path(tmp) / "events.csv"
                events.write_text(
                    "slug,status\nscheduled-race,scheduled\nfinished-race,finished\n",
                    encoding="utf-8",
                )
                path_arg = [events] if multiple_paths else events

                legacy = tool._read_events(path_arg)
                recovery = tool._read_events(path_arg, recovery_mode=True)

                self.assertEqual([row["slug"] for row in legacy], ["finished-race"])
                self.assertEqual(
                    [row["slug"] for row in recovery],
                    ["scheduled-race", "finished-race"],
                )

    def test_nar_recovery_mode_fetches_results_for_due_scheduled_target(self):
        tool = self._tool("prepare_nar_race_detail_candidates.py")

        self.assertFalse(
            tool._should_fetch_results({"status": "scheduled"}, recovery_mode=False)
        )
        self.assertTrue(
            tool._should_fetch_results({"status": "scheduled"}, recovery_mode=True)
        )
        self.assertTrue(
            tool._should_fetch_results({"status": "finished"}, recovery_mode=False)
        )

    def test_nar_recovery_mode_rechecks_published_racecard_sibling(self):
        tool = self._tool("prepare_nar_race_detail_candidates.py")
        introduction = (
            "https://www.keiba.go.jp/dirtgraderace/2026/"
            "0720_mercurycup/introduction.html"
        )

        self.assertEqual(
            tool._detail_url_candidates(introduction, recovery_mode=False),
            [introduction],
        )
        self.assertEqual(
            tool._detail_url_candidates(introduction, recovery_mode=True),
            [
                introduction,
                "https://www.keiba.go.jp/dirtgraderace/2026/"
                "0720_mercurycup/racecard.html",
            ],
        )

    def test_france_recovery_uses_frozen_exact_result_routes(self):
        tool = self._tool(
            "prepare_france_zeturf_race_detail_candidates.py"
        )

        self.assertEqual(
            tool._recovery_exact_result_url({"event_id": "733"}),
            "https://www.zeturf.fr/fr/course-du-jour/2026-07-19/"
            "R1C1-chantilly-goffs-prix-robert-papin",
        )
        self.assertEqual(
            tool._recovery_exact_result_url({"event_id": "736"}),
            "https://www.zeturf.fr/fr/course-du-jour/2026-07-22/"
            "R5C6-vichy-grand-prix-de-vichy",
        )
        self.assertEqual(
            tool._recovery_exact_result_url({"event_id": "999"}),
            "",
        )

    def test_sporting_life_also_ran_without_positions_is_not_complete_order(self):
        tool = self._tool("prepare_uk_sportinglife_race_detail_candidates.py")
        runners = [
            {"horse_number": "5", "horse_name": "Gold Phoenix", "running_status": "declared"},
            {"horse_number": "3", "horse_name": "Cabo Spirit", "running_status": "declared"},
            {"horse_number": "2", "horse_name": "Mondego", "running_status": "unknown"},
            {"horse_number": "1", "horse_name": "Astronomer", "running_status": "withdrawn"},
        ]
        partial_results = [
            {"finish_position": 1, "horse_number": "5", "horse_name": "Gold Phoenix"},
            {"finish_position": 2, "horse_number": "3", "horse_name": "Cabo Spirit"},
        ]
        complete_results = [
            *partial_results,
            {"finish_position": 3, "horse_number": "2", "horse_name": "Mondego"},
        ]

        partial = tool._result_order_completeness(runners, partial_results)
        complete = tool._result_order_completeness(runners, complete_results)

        self.assertFalse(partial["complete"])
        self.assertEqual(partial["missing_horse_numbers"], ["2"])
        self.assertTrue(complete["complete"])
        self.assertEqual(complete["missing_horse_numbers"], [])


class RaceResultRecoveryCandidateIntegrationTests(SimpleTestCase):
    def _candidate_result(self, *, confirmed: bool = True) -> dict:
        return {
            "finish_position": 1,
            "horse_number": "1",
            "horse_name": "Source Horse",
            "jockey_name": "Source Jockey",
            "running_status": "declared",
            "is_confirmed": confirmed,
            "source_refs": {"primary": "https://source.example/results/1"},
        }

    def _artifact_result(self, path: Path, *, source: str, authority: str) -> dict:
        return {
            "key": f"{source}_fixture",
            "source": source,
            "source_authority": authority,
            "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
            "artifacts": {"candidate_jsonl": {"path": str(path)}},
        }

    def test_recovery_aggregate_filters_adapter_extra_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "adapter.jsonl"
            candidate.write_text(
                json.dumps(
                    {
                        "event_id": 917,
                        "source_name": "sporting_life",
                        "modules": {
                            RaceEventModule.RUNNERS: {"items": [{"horse_name": "Source Horse"}]},
                            RaceEventModule.RESULTS: {"items": [self._candidate_result()]},
                            RaceEventModule.HISTORY_WINNERS: {
                                "items": [{"winner_year": 2026, "horse_name": "Source Horse"}]
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = orchestration.aggregate_candidate_artifacts(
                results=[
                    self._artifact_result(
                        candidate,
                        source="sporting_life",
                        authority="third_party_high_access",
                    )
                ],
                run_dir=root,
                purpose="race_result_recovery",
                approved_modules=[RaceEventModule.RESULTS],
            )
            records = [
                json.loads(line)
                for line in Path(result["path"]).read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(records), 1)
        self.assertEqual(set(records[0]["modules"]), {RaceEventModule.RESULTS})
        self.assertTrue(records[0]["metadata"]["result_order_complete"])

    def test_recovery_aggregate_marks_partial_runner_coverage_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "partial.jsonl"
            candidate.write_text(
                json.dumps(
                    {
                        "event_id": 426,
                        "source_name": "sporting_life",
                        "modules": {
                            RaceEventModule.RUNNERS: {
                                "items": [
                                    {
                                        "horse_number": "5",
                                        "horse_name": "Gold Phoenix",
                                        "running_status": "declared",
                                    },
                                    {
                                        "horse_number": "2",
                                        "horse_name": "Mondego",
                                        "running_status": "declared",
                                    },
                                ]
                            },
                            RaceEventModule.RESULTS: {
                                "items": [
                                    {
                                        "finish_position": 1,
                                        "horse_number": "5",
                                        "horse_name": "Gold Phoenix",
                                    }
                                ]
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = orchestration.aggregate_candidate_artifacts(
                results=[
                    self._artifact_result(
                        candidate,
                        source="sporting_life",
                        authority="third_party_high_access",
                    )
                ],
                run_dir=root,
                purpose="race_result_recovery",
                approved_modules=[RaceEventModule.RESULTS],
            )
            record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

        self.assertFalse(record["metadata"]["result_order_complete"])
        self.assertEqual(
            record["metadata"]["result_order_check"]["missing_horse_numbers"],
            ["2"],
        )

    def test_recovery_aggregate_rejects_same_number_with_different_horse_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "identity-mismatch.jsonl"
            candidate.write_text(
                json.dumps(
                    {
                        "event_id": 426,
                        "source_name": "sporting_life",
                        "modules": {
                            RaceEventModule.RUNNERS: {
                                "items": [
                                    {
                                        "horse_number": "5",
                                        "horse_name": "Gold Phoenix",
                                    }
                                ]
                            },
                            RaceEventModule.RESULTS: {
                                "items": [
                                    {
                                        "finish_position": 1,
                                        "horse_number": "5",
                                        "horse_name": "Wrong Horse",
                                    }
                                ]
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = orchestration.aggregate_candidate_artifacts(
                results=[
                    self._artifact_result(
                        candidate,
                        source="sporting_life",
                        authority="third_party_high_access",
                    )
                ],
                run_dir=root,
                purpose="race_result_recovery",
                approved_modules=[RaceEventModule.RESULTS],
            )
            record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

        self.assertFalse(record["metadata"]["result_order_complete"])
        self.assertEqual(
            record["metadata"]["result_order_check"]["reason"],
            "runner_missing_from_result_order",
        )

    def test_recovery_aggregate_marks_discovery_only_result_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "toba.jsonl"
            candidate.write_text(
                json.dumps(
                    {
                        "event_id": 406,
                        "source_name": "toba",
                        "modules": {
                            RaceEventModule.HISTORY_WINNERS: {
                                "items": [
                                    {
                                        "winner_year": 2026,
                                        "horse_name": "Reference Winner",
                                    }
                                ]
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = orchestration.aggregate_candidate_artifacts(
                results=[
                    self._artifact_result(
                        candidate,
                        source="toba",
                        authority="reference",
                    )
                ],
                run_dir=root,
                purpose="race_result_recovery",
                approved_modules=[RaceEventModule.RESULTS],
            )
            record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

        self.assertFalse(record["metadata"]["result_order_complete"])
        self.assertEqual(
            record["metadata"]["result_order_check"]["reason"],
            "discovery_only_result",
        )

    def test_recovery_candidate_schema_and_authority_for_approved_sources(self):
        source_cases = (
            ("jra", "official", "official_candidate"),
            ("nar", "official", "official_candidate"),
            ("sporting_life", "third_party_high_access", "provisional_candidate"),
            ("zeturf", "third_party_high_access", "provisional_candidate"),
            ("toba", "reference", "chart_discovery_candidate"),
        )
        for source, authority, expected_phase in source_cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                candidate = root / f"{source}.jsonl"
                candidate.write_text(
                    json.dumps(
                        {
                            "event_id": 1,
                            "source_name": source,
                            "source_authority": authority,
                            "modules": {
                                RaceEventModule.RESULTS: {
                                    "items": [self._candidate_result()]
                                }
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result = orchestration.aggregate_candidate_artifacts(
                    results=[self._artifact_result(candidate, source=source, authority=authority)],
                    run_dir=root,
                    purpose="race_result_recovery",
                    approved_modules=[RaceEventModule.RESULTS],
                )
                record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
                item = record["modules"][RaceEventModule.RESULTS]["items"][0]

                self.assertEqual(record["source_authority"], authority)
                self.assertEqual(record["result_phase"], expected_phase)
                self.assertEqual(
                    set(item["values"]),
                    {"raw", "normalized", "display_zh"},
                )
                self.assertIn("source_url", item["provenance"])
                self.assertIn("source_kind", item["provenance"])
                if authority != "official":
                    self.assertFalse(item["is_confirmed"])

    def test_tra_results_remain_provisional_even_when_payload_claims_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "tra.jsonl"
            candidate.write_text(
                json.dumps(
                    {
                        "event_id": 924,
                        "source_name": "the_racing_api",
                        "source_authority": "third_party",
                        "modules": {
                            RaceEventModule.RESULTS: {
                                "items": [self._candidate_result(confirmed=True)]
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = orchestration.aggregate_candidate_artifacts(
                results=[
                    self._artifact_result(
                        candidate,
                        source="the_racing_api",
                        authority="third_party",
                    )
                ],
                run_dir=root,
                purpose="race_result_recovery",
                approved_modules=[RaceEventModule.RESULTS],
            )
            record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            item = record["modules"][RaceEventModule.RESULTS]["items"][0]

        self.assertEqual(record["result_phase"], "provisional_candidate")
        self.assertFalse(item["is_confirmed"])
        self.assertFalse(record["confirmation_eligible"])

    def test_manual_only_route_is_blocked_before_transport(self):
        manifest = orchestration.AdapterManifest.from_dict(
            {
                "key": "equibase_manual_chart",
                "region": RacingRegion.UNITED_STATES,
                "source": "equibase",
                "modules": [RaceEventModule.RESULTS],
                "source_authority": "official",
                "access_mode": "manual_browser_only",
                "requires_network": True,
                "command": ["python", "-c", "print('transport must not run')"],
                "outputs": [{"key": "candidate_jsonl", "path": "candidate.jsonl"}],
            }
        )
        runner = orchestration.AdapterRunner(manifest)

        with tempfile.TemporaryDirectory() as tmp, patch(
            "stable.services.race_event_crawl_orchestration.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as transport:
            output = Path(tmp) / "adapter_runs" / manifest.key / "candidate.jsonl"
            output.parent.mkdir(parents=True)
            output.write_text("", encoding="utf-8")
            try:
                runner.run(
                    inputs={},
                    run_dir=tmp,
                    allow_network=True,
                    execution_policy={"max_requests": 1},
                )
            except orchestration.PlanValidationError as exc:
                self.assertRegex(str(exc), "manual_browser_only|manual-only")

        self.assertEqual(transport.call_count, 0)

    def test_equibase_adapter_is_local_input_only(self):
        manifest = orchestration.adapter_manifest_for_key("us_equibase_results")

        self.assertFalse(manifest.requires_network)
        self.assertIn("pdf_dir", manifest.inputs)
        self.assertNotIn("{network_flag}", manifest.command)
        self.assertFalse(
            any(
                part.startswith(("http://", "https://")) or "--allow-network" in part
                for part in manifest.command
            )
        )


class RaceResultRecoveryCoverageAndRunnerIntegrationTests(SimpleTestCase):
    def _write_controlled_candidate_state(
        self,
        root: Path,
        candidate: dict,
    ) -> Path:
        candidate_path = root / "candidates" / "combined_candidates.jsonl"
        candidate_path.parent.mkdir(parents=True)
        candidate_path.write_text(
            json.dumps(candidate) + "\n",
            encoding="utf-8",
        )
        state = orchestration.RunState(
            run_id="coverage-test",
            run_dir=str(root),
            artifacts={
                "combined_candidates": str(candidate_path),
                "combined_candidates_identity": orchestration.file_identity(
                    candidate_path
                ),
            },
        )
        state.write()
        return candidate_path

    def test_recovery_coverage_blocks_explicitly_incomplete_finish_order(self):
        plan = {
            "purpose": "race_result_recovery",
            "inventory_manifest_sha256": "b" * 64,
            "regions": [
                {
                    "region": RacingRegion.UNITED_STATES,
                    "source": "sporting_life",
                    "event_ids": [426],
                }
            ],
        }
        candidate = {
            "event_id": 426,
            "source_provider": "sporting_life",
            "racing_region": RacingRegion.UNITED_STATES,
            "metadata": {
                "result_order_complete": False,
                "result_order_check": {"missing_horse_numbers": ["2", "4", "7", "9"]},
            },
            "modules": {
                RaceEventModule.RESULTS: {
                    "items": [
                        {
                            "finish_position": 1,
                            "horse_number": "5",
                            "horse_name": "Gold Phoenix",
                        }
                    ]
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_controlled_candidate_state(
                root,
                candidate,
            )

            result = orchestration._audit_recovery_coverage(
                plan=plan,
                candidate_jsonl=candidate_path,
                run_dir=root,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["complete_count"], 0)
        self.assertIn("incomplete_result_order", result["blocker_codes"])

    def test_recovery_coverage_blocks_missing_completeness_proof(self):
        plan = {
            "purpose": "race_result_recovery",
            "inventory_manifest_sha256": "b" * 64,
            "regions": [
                {
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "event_ids": [80],
                }
            ],
        }
        candidate = {
            "event_id": 80,
            "source_provider": "jra",
            "racing_region": RacingRegion.JAPAN,
            "modules": {
                RaceEventModule.RESULTS: {
                    "items": [
                        {
                            "finish_position": 1,
                            "horse_number": "1",
                            "horse_name": "Unverified Roster",
                        }
                    ]
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_controlled_candidate_state(
                root,
                candidate,
            )
            result = orchestration._audit_recovery_coverage(
                plan=plan,
                candidate_jsonl=candidate_path,
                run_dir=root,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("incomplete_result_order", result["blocker_codes"])

    def test_recovery_coverage_rejects_external_candidate_override(self):
        plan = {
            "purpose": "race_result_recovery",
            "inventory_manifest_sha256": "b" * 64,
            "regions": [
                {
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "event_ids": [80],
                }
            ],
        }
        controlled = {
            "event_id": 80,
            "source_provider": "jra",
            "racing_region": RacingRegion.JAPAN,
            "metadata": {"result_order_complete": False},
            "modules": {
                RaceEventModule.RESULTS: {
                    "items": [{"finish_position": 1, "horse_name": "Controlled"}]
                }
            },
        }
        forged = {
            **controlled,
            "metadata": {"result_order_complete": True},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_controlled_candidate_state(root, controlled)
            forged_path = root / "forged.jsonl"
            forged_path.write_text(
                json.dumps(forged) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "controlled combined candidate",
            ):
                orchestration._audit_recovery_coverage(
                    plan=plan,
                    candidate_jsonl=forged_path,
                    run_dir=root,
                )

    def test_recovery_coverage_blocks_wrong_source_or_region(self):
        plan = {
            "purpose": "race_result_recovery",
            "inventory_manifest_sha256": "b" * 64,
            "regions": [
                {
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "event_ids": [80],
                }
            ],
        }
        candidate = {
            "event_id": 80,
            "source_provider": "sporting_life",
            "racing_region": RacingRegion.UNITED_STATES,
            "metadata": {"result_order_complete": True},
            "modules": {
                RaceEventModule.RESULTS: {
                    "items": [{"finish_position": 1, "horse_name": "Wrong Source"}]
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_controlled_candidate_state(
                root,
                candidate,
            )
            result = orchestration._audit_recovery_coverage(
                plan=plan,
                candidate_jsonl=candidate_path,
                run_dir=root,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("candidate_source_mismatch", result["blocker_codes"])
        self.assertIn("candidate_region_mismatch", result["blocker_codes"])

    def test_recovery_coverage_rejects_combined_candidate_identity_drift(self):
        plan = {
            "purpose": "race_result_recovery",
            "inventory_manifest_sha256": "b" * 64,
            "regions": [
                {
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "event_ids": [80],
                }
            ],
        }
        candidate = {
            "event_id": 80,
            "source_provider": "jra",
            "racing_region": RacingRegion.JAPAN,
            "metadata": {"result_order_complete": False},
            "modules": {
                RaceEventModule.RESULTS: {
                    "items": [{"finish_position": 1, "horse_name": "Original"}]
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = self._write_controlled_candidate_state(
                root,
                candidate,
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        **candidate,
                        "metadata": {"result_order_complete": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "identity changed",
            ):
                orchestration._audit_recovery_coverage(
                    plan=plan,
                    candidate_jsonl=candidate_path,
                    run_dir=root,
                )

    def test_partial_recovery_scope_is_rejected_before_coverage_audit(self):
        plan = {
            "run_id": "empty-region-recovery",
            "purpose": "race_result_recovery",
            "target_layer": "race_event",
            "inventory_manifest_sha256": "b" * 64,
            "inventory_artifact_path": "/approved/recovery-inventory.json",
            "inventory_artifact_sha256": "c" * 64,
            "source_map_version": "2026-07-27-gap-v2",
            "allow_network": False,
            "batch_size": 2,
            "rate_limit": {"max_requests": 2, "request_interval_seconds": 1},
            "regions": [
                {
                    "region": RacingRegion.FRANCE,
                    "source": "zeturf",
                    "source_authority": "third_party_high_access",
                    "event_ids": [733, 734],
                    "modules": {RaceEventModule.RESULTS: {}},
                }
            ],
            "adapters": ["france_zeturf_detail"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            candidates = root / "empty.jsonl"
            mapping = root / "mapping.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            candidates.write_text("", encoding="utf-8")
            mapping.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(
                orchestration.PlanValidationError,
                "frozen event scope",
            ):
                orchestration.audit_coverage(
                    plan_path=plan_path,
                    candidate_jsonl=candidates,
                    series_mapping_path=mapping,
                    run_dir=root,
                )

    def test_recovery_commands_have_disjoint_runner_phase_classification(self):
        read_commands = set(historical_batch_runner._READ_MANAGEMENT_COMMANDS)
        write_commands = set(historical_batch_runner._WRITE_MANAGEMENT_COMMANDS)
        recovery_read = {name for name in read_commands if "race_result_recovery" in name}
        recovery_write = {name for name in write_commands if "race_result_recovery" in name}

        self.assertGreaterEqual(len(recovery_read), 2, "inventory/crawl/verify need explicit read classification")
        self.assertGreaterEqual(len(recovery_write), 1, "apply needs explicit write classification")
        self.assertTrue(recovery_read.isdisjoint(recovery_write))
        self.assertEqual(
            historical_batch_runner._phase_permissions("crawl"),
            (True, False),
        )
        self.assertEqual(
            historical_batch_runner._phase_permissions("apply"),
            (False, True),
        )
        self.assertEqual(
            historical_batch_runner._phase_permissions("verify"),
            (False, False),
        )
