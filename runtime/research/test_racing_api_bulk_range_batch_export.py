#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("racing_api_bulk_range_batch_export.py")
BUILDER_SCRIPT = Path(__file__).with_name(
    "build_bulk_target_runner_stable_id_ledger.py"
)
STABLE_PLAN_SCRIPT = Path(__file__).with_name(
    "prepare_racing_api_stable_id_enrichment_batch_plan.py"
)
COVERAGE_SCRIPT = Path(__file__).with_name(
    "build_stable_id_reconciliation_coverage.py"
)


def load_tool():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("bulk_range_batch_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_bulk_target_runner_stable_id_ledger", BUILDER_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_stable_plan():
    spec = importlib.util.spec_from_file_location(
        "prepare_racing_api_stable_id_enrichment_batch_plan",
        STABLE_PLAN_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_coverage():
    spec = importlib.util.spec_from_file_location(
        "build_stable_id_reconciliation_coverage",
        COVERAGE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fingerprint_identity(root: Path) -> dict:
    horse_export = sys.modules["racing_api_horse_export"]
    payload = {
        "fingerprint_generated_at": "2026-08-29T15:33:04+08:00",
        "full_openapi_sha256": horse_export.EXPECTED_OPENAPI_FULL_SHA256,
        "openapi_version": horse_export.EXPECTED_OPENAPI_VERSION,
        "selected_contract": {
            "paths": list(horse_export.EXPECTED_OPENAPI_SELECTED_PATHS),
            "sha256": horse_export.EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
        },
        "selected_schema": {
            "names": list(horse_export.EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES),
            "sha256": horse_export.EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
        },
        "source_url": horse_export.OPENAPI_SOURCE_URL,
    }
    path = root / "openapi-fingerprint.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return horse_export.load_openapi_fingerprint(
        path, hashlib.sha256(path.read_bytes()).hexdigest()
    )


class RacingApiBulkRangeBatchExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()
        cls.builder = load_builder()
        cls.stable_plan = load_stable_plan()
        cls.coverage = load_coverage()
        cls.plan_module = sys.modules["prepare_racing_api_bulk_range_batch_plan"]

    def target(self) -> dict:
        return {
            "target_key": "france:2005:arc",
            "country_region": "france",
            "year": 2005,
            "local_date": "",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "race_name_aliases": ["Qatar Prix de l'Arc de Triomphe"],
            "racecourse": "ParisLongchamp",
            "racecourse_aliases": ["ParisLongchamp (FR)"],
            "grade_text": "G1",
            "discipline": "flat",
        }

    def classified(self) -> dict:
        return {
            "schema_version": "racing-api-bulk-target-classification.v1",
            "target_key": "france:2005:arc",
            "country_region": "france",
            "year": 2005,
            "grade_text": "G1",
            "discipline": "flat",
            "evidence_state": "source_route_only",
            "local_date_known": False,
            "route_class": "bulk_results_region_year_then_stable_id",
        }

    def partition(self, ranges: int = 1) -> dict:
        keys_sha = hashlib.sha256(b"france:2005:arc\n").hexdigest()
        date_ranges = [
            {
                "start_date": "2005-01-01",
                "end_date": "2005-06-30" if ranges == 2 else "2005-12-31",
                "max_pages_protocol_ceiling": 10,
            }
        ]
        if ranges == 2:
            date_ranges.append(
                {
                    "start_date": "2005-07-01",
                    "end_date": "2005-12-31",
                    "max_pages_protocol_ceiling": 10,
                }
            )
        return {
            "schema_version": "racing-api-bulk-region-year-partition.v1",
            "country_region": "france",
            "year": 2005,
            "target_count": 1,
            "target_keys_sha256": keys_sha,
            "evidence_state_counts": {"source_route_only": 1},
            "ranges": date_ranges,
            "range_count": ranges,
            "protocol_request_ceiling": ranges * 10,
            "actual_request_count": None,
            "execution_ready": False,
        }

    def race(self, *, name="Qatar Prix de l'Arc de Triomphe") -> dict:
        return {
            "race_id": "rac_arc_2005",
            "date": "2005-10-02",
            "off_dt": "2005-10-02T16:05:00+02:00",
            "region": "FR",
            "course": "ParisLongchamp (FR)",
            "course_id": "crs_parislongchamp",
            "race_name": name,
            "type": "Flat",
            "class": "Group 1",
            "pattern": "G1",
            "dist": "1m4f",
            "surface": "Turf",
            "runners": [
                {"horse_id": "hrs_1", "horse": "Winner (FR)", "position": "1"},
                {"horse_id": "hrs_2", "horse": "Second (IRE)", "position": "2"},
                {"horse_id": "hrs_3", "horse": "Withdrawn (GB)", "position": "NR"},
            ],
        }

    def make_plan(self, root: Path, *, ranges: int = 1) -> tuple[Path, dict]:
        target_root = root / "target"
        target_root.mkdir()
        target_identity = {
            "root": str(target_root.resolve()),
            "manifest_sha256": "1" * 64,
            "ledger_sha256": "2" * 64,
            "rows": 1,
            "as_of_date": "2026-08-29",
        }
        readiness = {
            "root": str((root / "readiness").resolve()),
            "report_sha256": "3" * 64,
            "partitions_sha256": "4" * 64,
            "bulk_targets_sha256": "5" * 64,
            "target_artifact": dict(target_identity),
            "counts": {},
        }
        output = root / "plan"
        with patch.object(
            self.plan_module,
            "load_readiness_artifact",
            return_value=([self.partition(ranges)], [self.classified()], readiness),
        ), patch.object(
            self.plan_module,
            "load_target_artifact",
            return_value=([self.target()], target_identity),
        ):
            summary = self.plan_module.prepare_plan(
                readiness_root=root / "readiness",
                expected_readiness_report_sha256="3" * 64,
                target_root=target_root,
                expected_target_manifest_sha256="1" * 64,
                expected_target_ledger_sha256="2" * 64,
                output_dir=output,
            )
        return output, summary

    def test_run_complete_range_batch_emits_actual_starters_and_exact_receipt(self):
        class FakeClient:
            request_ceiling = 10

            def __init__(self, race):
                self.race = race
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                return {
                    "results": [self.race],
                    "total": 1,
                    "limit": 100,
                    "skip": 0,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            manifest = self.module.run_bulk_range_batch_artifact(
                plan_root=plan,
                expected_plan_manifest_sha256=summary["manifest_sha256"],
                expected_batch_plan_sha256=summary["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=output,
                client=FakeClient(self.race()),
                openapi_fingerprint_identity=fingerprint_identity(root),
            )
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["summary"]["mapped_targets"], 1)
            self.assertEqual(manifest["summary"]["participant_count"], 2)
            self.assertEqual(manifest["summary"]["excluded_non_runner_count"], 1)
            self.assertEqual(manifest["request_count"], 1)
            self.assertEqual(manifest["database_writes"], 0)
            self.assertTrue((output / "COMPLETE").is_file())
            self.assertFalse((output / "PREPARED").exists())

            stable_output = root / "stable-ledger"
            stable = self.builder.build_bulk_stable_id_seed_ledger(
                bulk_run_dir=output,
                approved_bulk_run_manifest_sha256=hashlib.sha256(
                    (output / "batch-manifest.json").read_bytes()
                ).hexdigest(),
                output_dir=stable_output,
            )
            seeds = [
                json.loads(line)
                for line in (
                    stable_output / "target-runner-stable-id-seeds.v1.jsonl"
                )
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(stable["unique_actual_starter_count"], 2)
            self.assertEqual(stable["actual_starter_occurrence_count"], 2)
            self.assertEqual(
                {seed["horse_id"] for seed in seeds}, {"hrs_1", "hrs_2"}
            )
            self.assertTrue(
                all(
                    seed["target_occurrences"][0]["source_route"]
                    == "bulk_results"
                    for seed in seeds
                )
            )
            self.assertTrue((stable_output / "COMPLETE").is_file())

            stable_manifest_sha = hashlib.sha256(
                (stable_output / "manifest.json").read_bytes()
            ).hexdigest()
            coverage_root = root / "bulk-coverage"
            coverage = self.coverage.build_coverage(
                stable_runner_ledger_root=stable_output,
                approved_stable_runner_manifest_sha256=stable_manifest_sha,
                held_approval_roots=[],
                held_approval_manifest_sha256s=[],
                external_approval_roots=[],
                external_approval_manifest_sha256s=[],
                provider_native_bulk_run_roots=[output],
                provider_native_bulk_run_manifest_sha256s=[
                    hashlib.sha256(
                        (output / "batch-manifest.json").read_bytes()
                    ).hexdigest()
                ],
                output_dir=coverage_root,
            )
            self.assertEqual(coverage["counts"]["components"], 1)
            self.assertEqual(coverage["counts"]["covered_occurrences"], 2)
            coverage_sha = hashlib.sha256(
                (coverage_root / "coverage-manifest.json").read_bytes()
            ).hexdigest()
            merged_ready = self.stable_plan.prepare_batch_plan(
                stable_runner_ledger_root=stable_output,
                approved_stable_runner_manifest_sha256=stable_manifest_sha,
                approved_reconciliation_root=coverage_root,
                approved_reconciliation_manifest_sha256=coverage_sha,
                output_dir=root / "coverage-enrichment-plan",
                batch_size_cap=5,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
            )
            self.assertEqual(merged_ready["counts"]["seeds"], 2)
            self.assertEqual(
                merged_ready["stable_id_authority"]["component_count"], 1
            )
            coverage_manifest_path = coverage_root / "coverage-manifest.json"
            drifted_coverage = json.loads(
                coverage_manifest_path.read_text(encoding="utf-8")
            )
            drifted_coverage["components"][0]["source_stable_runner_ledger"][
                "root"
            ] = str(root / "unrelated-stable-ledger")
            coverage_manifest_path.write_text(
                json.dumps(
                    drifted_coverage,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            drifted_coverage_sha = hashlib.sha256(
                coverage_manifest_path.read_bytes()
            ).hexdigest()
            (coverage_root / "COMPLETE").write_text(
                drifted_coverage_sha + "\n", encoding="ascii"
            )
            with self.assertRaisesRegex(
                ValueError, "bulk stable identity drift"
            ):
                self.stable_plan.prepare_batch_plan(
                    stable_runner_ledger_root=stable_output,
                    approved_stable_runner_manifest_sha256=stable_manifest_sha,
                    approved_reconciliation_root=coverage_root,
                    approved_reconciliation_manifest_sha256=drifted_coverage_sha,
                    output_dir=root / "drifted-coverage-enrichment-plan",
                    batch_size_cap=5,
                    max_results_pages_per_horse=1,
                    max_parent_profiles=0,
                )

    def test_bulk_stable_builder_rejects_extra_run_member(self):
        class FakeClient:
            request_ceiling = 10

            def __init__(self, race):
                self.race = race
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                return {
                    "results": [self.race],
                    "total": 1,
                    "limit": 100,
                    "skip": 0,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            self.module.run_bulk_range_batch_artifact(
                plan_root=plan,
                expected_plan_manifest_sha256=summary["manifest_sha256"],
                expected_batch_plan_sha256=summary["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=output,
                client=FakeClient(self.race()),
                openapi_fingerprint_identity=fingerprint_identity(root),
            )
            manifest_sha = hashlib.sha256(
                (output / "batch-manifest.json").read_bytes()
            ).hexdigest()
            (output / "unexpected.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "member set drift"):
                self.builder.build_bulk_stable_id_seed_ledger(
                    bulk_run_dir=output,
                    approved_bulk_run_manifest_sha256=manifest_sha,
                    output_dir=root / "stable-ledger",
                )
            self.assertFalse((root / "stable-ledger").exists())

    def test_unmatched_target_stays_prepared(self):
        class FakeClient:
            request_ceiling = 10
            request_count = 0
            request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                return {
                    "results": [],
                    "total": 0,
                    "limit": 100,
                    "skip": 0,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            manifest = self.module.run_bulk_range_batch_artifact(
                plan_root=plan,
                expected_plan_manifest_sha256=summary["manifest_sha256"],
                expected_batch_plan_sha256=summary["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=output,
                client=FakeClient(),
                openapi_fingerprint_identity=fingerprint_identity(root),
            )
            self.assertEqual(manifest["status"], "needs_review")
            self.assertEqual(manifest["gap_count"], 1)
            self.assertTrue((output / "PREPARED").is_file())

    def test_target_ledger_tamper_and_client_ceiling_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            target_path = next((plan / "target-ledgers").glob("*.jsonl"))
            target_path.write_text(target_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target ledger identity drift"):
                self.module.load_planned_batch(
                    plan,
                    expected_manifest_sha256=summary["manifest_sha256"],
                    expected_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                )

    def test_same_race_in_non_overlapping_ranges_fails_closed(self):
        race_payload = self.race()

        class FakeClient:
            request_ceiling = 20
            request_count = 0
            request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                return {
                    "results": [race_payload],
                    "total": 1,
                    "limit": 100,
                    "skip": 0,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root, ranges=2)
            with self.assertRaisesRegex(ValueError, "duplicate across ranges"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=root / "run",
                    client=FakeClient(),
                    openapi_fingerprint_identity=fingerprint_identity(root),
                )

    def test_page_checkpoint_resume_skips_cached_page_and_preserves_requests(self):
        target_race = self.race()
        first_page = []
        for ordinal in range(100):
            race = dict(target_race)
            race["race_id"] = f"rac_dummy_{ordinal:03d}"
            race["race_name"] = f"Unrelated race {ordinal}"
            race["runners"] = []
            first_page.append(race)

        class FailingClient:
            request_ceiling = 10

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                if "skip=0" in url:
                    return {
                        "results": first_page,
                        "total": 101,
                        "limit": 100,
                        "skip": 0,
                        "query": [],
                    }
                self.request_ledger[-1]["status"] = None
                raise RuntimeError("simulated page-two transport failure")

        class ResumeClient:
            request_ceiling = 8

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []
                self.urls = []

            def request_json(self, url):
                self.urls.append(url)
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                if "skip=100" not in url:
                    raise AssertionError("resume refetched an already checkpointed page")
                return {
                    "results": [target_race],
                    "total": 101,
                    "limit": 100,
                    "skip": 100,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            identity = fingerprint_identity(root)
            with self.assertRaisesRegex(RuntimeError, "page-two"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=FailingClient(),
                    openapi_fingerprint_identity=identity,
                )
            checkpoint = json.loads(
                (output / "checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["status"], "safe_stopped")
            self.assertEqual(checkpoint["cumulative_request_count"], 2)
            self.assertEqual(len(checkpoint["pages"]), 1)
            self.assertTrue(
                (output / "cache" / "range-0001-page-0001.json").is_file()
            )
            self.assertFalse((output / "batch-manifest.json").exists())

            resume_client = ResumeClient()
            manifest = self.module.run_bulk_range_batch_artifact(
                plan_root=plan,
                expected_plan_manifest_sha256=summary["manifest_sha256"],
                expected_batch_plan_sha256=summary["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=output,
                client=resume_client,
                openapi_fingerprint_identity=identity,
                resume=True,
                prior_request_count=2,
            )
            self.assertEqual(len(resume_client.urls), 1)
            self.assertIn("skip=100", resume_client.urls[0])
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["request_count"], 3)
            self.assertEqual(len(manifest["request_ledger"]), 3)
            self.assertEqual(len(manifest["responses"]), 2)
            self.assertEqual(manifest["summary"]["mapped_targets"], 1)
            self.assertEqual(
                json.loads(
                    (output / "checkpoint.json").read_text(encoding="utf-8")
                )["status"],
                "complete",
            )
            stable = self.builder.build_bulk_stable_id_seed_ledger(
                bulk_run_dir=output,
                approved_bulk_run_manifest_sha256=hashlib.sha256(
                    (output / "batch-manifest.json").read_bytes()
                ).hexdigest(),
                output_dir=root / "stable-ledger",
            )
            self.assertEqual(stable["unique_actual_starter_count"], 2)

    def test_resume_rejects_checkpoint_cache_and_count_drift_before_network(self):
        class FailingClient:
            request_ceiling = 10

            def __init__(self, race):
                self.race = race
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                if self.request_count == 1:
                    return {
                        "results": [self.race],
                        "total": 2,
                        "limit": 100,
                        "skip": 0,
                        "query": [],
                    }
                self.request_ledger[-1]["status"] = None
                raise RuntimeError("stop")

        class NoNetworkClient:
            def __init__(self, request_ceiling=8):
                self.request_ceiling = request_ceiling
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, _url):
                raise AssertionError("network must not be reached")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            identity = fingerprint_identity(root)
            with self.assertRaisesRegex(RuntimeError, "stop"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=FailingClient(self.race()),
                    openapi_fingerprint_identity=identity,
                )
            cache_path = output / "cache" / "range-0001-page-0001.json"
            wrapper = json.loads(cache_path.read_text(encoding="utf-8"))
            wrapper["captured_at"] = "tampered"
            cache_path.write_text(
                json.dumps(wrapper, sort_keys=True) + "\n", encoding="utf-8"
            )
            client = NoNetworkClient()
            with self.assertRaisesRegex(ValueError, "response identity drift"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=client,
                    openapi_fingerprint_identity=identity,
                    resume=True,
                    prior_request_count=2,
                )
            self.assertEqual(client.request_count, 0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            identity = fingerprint_identity(root)
            with self.assertRaisesRegex(RuntimeError, "stop"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=FailingClient(self.race()),
                    openapi_fingerprint_identity=identity,
                )
            definition_path = output / "batch-definition.json"
            definition = json.loads(definition_path.read_text(encoding="utf-8"))
            definition["ranges"][0]["end_date"] = "2005-12-30"
            definition_path.write_text(
                json.dumps(definition, sort_keys=True) + "\n", encoding="utf-8"
            )
            client = NoNetworkClient()
            with self.assertRaisesRegex(ValueError, "definition drift"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=client,
                    openapi_fingerprint_identity=identity,
                    resume=True,
                    prior_request_count=2,
                )
            self.assertEqual(client.request_count, 0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)
            output = root / "run"
            identity = fingerprint_identity(root)
            with self.assertRaisesRegex(RuntimeError, "stop"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=FailingClient(self.race()),
                    openapi_fingerprint_identity=identity,
                )
            client = NoNetworkClient(request_ceiling=9)
            with self.assertRaisesRegex(ValueError, "does not bind checkpoint"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=output,
                    client=client,
                    openapi_fingerprint_identity=identity,
                    resume=True,
                    prior_request_count=1,
                )
            self.assertEqual(client.request_count, 0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, summary = self.make_plan(root)

            class WrongCeiling:
                request_ceiling = 200

            with self.assertRaisesRegex(ValueError, "request ceiling"):
                self.module.run_bulk_range_batch_artifact(
                    plan_root=plan,
                    expected_plan_manifest_sha256=summary["manifest_sha256"],
                    expected_batch_plan_sha256=summary["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=root / "run",
                    client=WrongCeiling(),
                    openapi_fingerprint_identity=fingerprint_identity(root),
                )


if __name__ == "__main__":
    unittest.main()
