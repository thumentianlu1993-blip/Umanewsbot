from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from stable.models import RaceEventModule, RacingRegion
from stable.services import historical_batch_runner
from stable.services import race_event_crawl_orchestration as orchestration


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
        "source": "toba",
        "adapter": "us_toba_chart_discovery",
        "event_ids": [406, 407, 411, 412, 413, 414, 415, 416, 417, 418, 419, 420],
    },
    {
        "region": RacingRegion.UNITED_STATES,
        "source": "sporting_life",
        "adapter": "us_sporting_life_results",
        "event_ids": [421, 422, 423, 424, 425, 426, 427],
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
            "source_map_version": "2026-07-27",
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

    def test_non_recovery_results_only_plan_keeps_legacy_three_module_gate(self):
        plan = self._plan()
        plan.pop("purpose")
        with self.assertRaisesRegex(
            orchestration.PlanValidationError,
            "missing required modules.*runners.*history_winners",
        ):
            orchestration.validate_plan(plan)


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
    def test_empty_region_yields_one_results_blocker_per_frozen_event(self):
        plan = {
            "run_id": "empty-region-recovery",
            "purpose": "race_result_recovery",
            "target_layer": "race_event",
            "inventory_manifest_sha256": "b" * 64,
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

            report = orchestration.audit_coverage(
                plan_path=plan_path,
                candidate_jsonl=candidates,
                series_mapping_path=mapping,
                run_dir=root,
            )

        missing = [
            blocker
            for blocker in report["blockers"]
            if blocker["code"] == "missing_event_candidate"
        ]
        self.assertEqual({blocker["event_id"] for blocker in missing}, {733, 734})
        self.assertEqual(report["expected_target_count"], 2)
        self.assertNotIn("missing_runners", report["blocker_codes"])
        self.assertNotIn("missing_history_winners", report["blocker_codes"])

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
