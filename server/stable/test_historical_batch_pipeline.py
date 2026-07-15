from __future__ import annotations

import csv
import hashlib
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from stable.models import (
    HistoricalBatchRun,
    HistoricalRaceEventTarget,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventDataCandidate,
    RaceEventCandidateStatus,
    RaceEventModule,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_batch_pipeline import (
    HistoricalBatchPipelineError,
    build_historical_batch_shard_plan,
    merge_historical_race_fragments,
)
from stable.services.historical_batch_runner import validate_runner_plan, validate_runner_resource_limits
from stable.services.historical_batch_verifier import (
    verify_historical_batch_stage,
    write_verification_report,
)
from stable.services.historical_race_batches import target_identity


SHA_A = "a" * 64
SHA_B = "b" * 64
IMAGE_ID = "sha256:" + "c" * 64
REVISION = "d" * 40
RECORDED_AT = "2026-07-15T00:00:00Z"


def _canonical(payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(_canonical(row) for row in rows))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_events(path: Path, targets: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "target_id",
        "target_sha256",
        "inventory_artifact_sha256",
        "year",
        "slug",
        "series_key",
        "country_region",
        "original_name",
        "chinese_name",
        "racecourse",
        "local_date",
        "distance_text",
        "source_refs",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for target in targets:
            writer.writerow(
                {
                    "target_id": target["target_id"],
                    "target_sha256": target["target_sha256"],
                    "inventory_artifact_sha256": target["inventory_artifact_sha256"],
                    "year": target["year"],
                    "slug": f"race-{target['target_id']}",
                    "series_key": target["series_key"],
                    "country_region": target["country_region"],
                    "original_name": f"Race {target['target_id']}",
                    "chinese_name": f"赛事{target['target_id']}",
                    "racecourse": "Tokyo",
                    "local_date": f"{target['year']}-01-01",
                    "distance_text": "1600m",
                    "source_refs": "{}",
                }
            )
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HistoricalBatchPlanFixture:
    def make(self, root: Path, *, count: int = 2) -> tuple[Path, dict]:
        inputs = root / "bootstrap"
        targets = [
            {
                "target_id": index,
                "target_sha256": hashlib.sha256(f"target-{index}".encode()).hexdigest(),
                "inventory_artifact_sha256": SHA_A,
                "series_key": f"japan-series-{index}",
                "year": 2020 + index,
                "country_region": RacingRegion.HONG_KONG,
            }
            for index in range(1, count + 1)
        ]
        selection_path = inputs / "selection_snapshot.json"
        selection_sha = _write_json(
            selection_path,
            {
                "schema_version": "1.0",
                "inventory_manifest_sha256": SHA_A,
                "targets": targets,
            },
        )
        manifest_path = inputs / "manifest.json"
        manifest_sha = _write_json(
            manifest_path,
            {
                "schema_version": "1.0",
                "inventory_manifest_sha256": SHA_A,
                "target_count": len(targets),
                "artifacts": {
                    "selection_snapshot": {
                        "path": selection_path.name,
                        "sha256": selection_sha,
                        "size": selection_path.stat().st_size,
                    }
                },
            },
        )
        approval_path = inputs / "approval.json"
        approval_sha = _write_json(
            approval_path,
            {
                "status": "approved",
                "approved_by": "test-operator",
                "approved_at": "2026-07-15T00:00:00Z",
                "manifest_identity": {
                    "path": manifest_path.name,
                    "sha256": manifest_sha,
                    "size": manifest_path.stat().st_size,
                },
                "approved_target_ids": [target["target_id"] for target in targets],
            },
        )
        events_path = inputs / "events.csv"
        _write_events(events_path, targets)
        tool_root = root / "tools"
        tool_root.mkdir()
        tool_path = tool_root / "prepare_hkjc_race_detail_candidates.py"
        tool_path.write_text("print('fixture')\n", encoding="utf-8")
        tool_sha = hashlib.sha256(tool_path.read_bytes()).hexdigest()
        descriptor = {
            "schema_version": "1.0",
            "batch_id": "2016-2025-batch-test",
            "stage_id": "details",
            "selection": {"path": str(selection_path), "sha256": selection_sha},
            "approval": {"path": str(approval_path), "sha256": approval_sha},
            "batch_manifest": {"path": str(manifest_path), "sha256": manifest_sha},
            "image_id": IMAGE_ID,
            "image_revision": REVISION,
            "tool_root": str(tool_root),
            "tool_manifest": {tool_path.name: tool_sha},
            "resource_limits": {
                "request_budget": count,
                "max_source_cache_bytes": 1024 * 1024,
                "min_free_disk_bytes": 5 * 1024 * 1024 * 1024,
                "request_interval_seconds": 1,
            },
            "shards": [
                {
                    "id": "japan-01",
                    "country_region": RacingRegion.HONG_KONG,
                    "target_ids": [target["target_id"] for target in targets],
                    "request_budget": count,
                    "recipes": [
                        {
                            "tool": tool_path.name,
                            "inputs": {"events_csv": [str(events_path)]},
                            "outputs": {"output_dir": "outputs/hkjc"},
                            "options": {"allow_network": True, "fail_fast": True},
                        }
                    ],
                }
            ],
        }
        descriptor_path = inputs / "descriptor.json"
        _write_json(descriptor_path, descriptor)
        return descriptor_path, descriptor


class HistoricalBatchPlanTests(SimpleTestCase, HistoricalBatchPlanFixture):
    def test_calendar_parser_builds_verify_plan_without_network_write_or_resource_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root)
            selection_path = Path(descriptor["selection"]["path"])
            selection = json.loads(selection_path.read_text())
            for target in selection["targets"]:
                target["country_region"] = RacingRegion.UNITED_KINGDOM
                target["year"] = 2024
            selection_sha = _write_json(selection_path, selection)
            manifest_path = Path(descriptor["batch_manifest"]["path"])
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"]["selection_snapshot"].update(
                sha256=selection_sha, size=selection_path.stat().st_size
            )
            manifest_sha = _write_json(manifest_path, manifest)
            approval_path = Path(descriptor["approval"]["path"])
            approval = json.loads(approval_path.read_text())
            approval["manifest_identity"].update(
                sha256=manifest_sha, size=manifest_path.stat().st_size
            )
            approval_sha = _write_json(approval_path, approval)

            catalog = root / "bootstrap" / "catalog.json"
            _write_json(catalog, {"schema_version": "1.0", "sources": []})
            ledger = root / "bootstrap" / "ledger.jsonl"
            _write_jsonl(ledger, [{"status": "succeeded"}])
            cache = root / "bootstrap" / "cache"
            cache.mkdir()
            cache_manifest = root / "bootstrap" / "cache-manifest.json"
            _write_json(cache_manifest, {"schema_version": "1.0", "files": {}})
            tool_root = Path(__file__).resolve().parents[2] / "runtime" / "tools"
            tool_name = "prepare_historical_race_calendar_inputs.py"
            tool_path = tool_root / tool_name

            descriptor.update(
                phase="verify",
                selection={"path": str(selection_path), "sha256": selection_sha},
                batch_manifest={"path": str(manifest_path), "sha256": manifest_sha},
                approval={"path": str(approval_path), "sha256": approval_sha},
                tool_root=str(tool_root),
                tool_manifest={tool_name: hashlib.sha256(tool_path.read_bytes()).hexdigest()},
            )
            descriptor.pop("resource_limits")
            descriptor["shards"][0].update(
                country_region=RacingRegion.UNITED_KINGDOM,
                request_budget=0,
                recipes=[
                    {
                        "tool": tool_name,
                        "inputs": {
                            "selection_snapshot": [str(selection_path)],
                            "source_catalog": [str(catalog)],
                            "source_cache_manifest": [str(cache_manifest)],
                            "request_ledger": [str(ledger)],
                            "source_cache_root": [str(cache)],
                        },
                        "outputs": {"output_dir": "outputs/calendar"},
                        "options": {
                            "country_region": RacingRegion.UNITED_KINGDOM,
                            "year": 2024,
                            "recorded_at": RECORDED_AT,
                        },
                    }
                ],
            )
            path = root / "verify-descriptor.json"
            _write_json(path, descriptor)
            result = build_historical_batch_shard_plan(
                descriptor_path=path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            plan = json.loads((root / "published" / "runner-plan.json").read_text())

            self.assertEqual(result["target_count"], 2)
            self.assertEqual(plan["phase"], "verify")
            self.assertFalse(plan["network_enabled"])
            self.assertFalse(plan["write_enabled"])
            self.assertNotIn("resource_limits", plan)
            self.assertEqual(plan["steps"][0]["outputs"], [])
            self.assertEqual(
                plan["steps"][0]["output_directories"],
                [{"path": str((root / "published" / "outputs" / "calendar").resolve())}],
            )

            invalid = deepcopy(descriptor)
            invalid["resource_limits"] = {
                "request_budget": 1,
                "max_source_cache_bytes": 1024,
                "min_free_disk_bytes": 5 * 1024 * 1024 * 1024,
                "request_interval_seconds": 1,
            }
            invalid_path = root / "invalid-verify-descriptor.json"
            _write_json(invalid_path, invalid)
            with self.assertRaises(HistoricalBatchPipelineError):
                build_historical_batch_shard_plan(
                    descriptor_path=invalid_path,
                    shard_id="japan-01",
                    output_dir=root / "invalid-published",
                )

            invalid_null = deepcopy(descriptor)
            invalid_null["resource_limits"] = None
            invalid_null_path = root / "invalid-null-verify-descriptor.json"
            _write_json(invalid_null_path, invalid_null)
            with self.assertRaises(HistoricalBatchPipelineError):
                build_historical_batch_shard_plan(
                    descriptor_path=invalid_null_path,
                    shard_id="japan-01",
                    output_dir=root / "invalid-null-published",
                )

    def test_builds_canonical_plan_bound_to_selection_approval_tools_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            result = build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            output = root / "published"
            plan = json.loads((output / "runner-plan.json").read_text())
            scope = json.loads((output / "scope.json").read_text())
            self.assertEqual(result["target_count"], 2)
            self.assertEqual(scope["target_ids"], [1, 2])
            self.assertEqual(plan["image_id"], IMAGE_ID)
            self.assertEqual(plan["resource_limits"]["request_budget"], 2)
            self.assertNotIn("argv", json.loads(descriptor_path.read_text())["shards"][0]["recipes"][0])
            self.assertTrue((output / "inputs" / "events.csv").is_file())
            self.assertFalse((output / "inputs" / "events.csv").is_symlink())

    def test_rejects_all_identity_and_approval_drift_without_partial_output(self):
        mutations = (
            lambda descriptor: descriptor["selection"].update(sha256=SHA_B),
            lambda descriptor: descriptor["approval"].update(sha256=SHA_A),
            lambda descriptor: descriptor["batch_manifest"].update(sha256=SHA_A),
            lambda descriptor: descriptor.update(image_id="latest"),
            lambda descriptor: descriptor.update(image_revision="short"),
            lambda descriptor: descriptor["tool_manifest"].update(
                {"prepare_hkjc_race_detail_candidates.py": SHA_A}
            ),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _descriptor_path, descriptor = self.make(root)
                mutate(descriptor)
                descriptor_path = root / "descriptor-mutated.json"
                _write_json(descriptor_path, descriptor)
                output = root / "published"
                with self.assertRaises(HistoricalBatchPipelineError):
                    build_historical_batch_shard_plan(
                        descriptor_path=descriptor_path,
                        shard_id="japan-01",
                        output_dir=output,
                    )
                self.assertFalse(output.exists())

    def test_rejects_pending_incomplete_or_overbroad_approval(self):
        for approved_ids, status in (([1], "approved"), ([1, 2, 3], "approved"), ([1, 2], "pending")):
            with self.subTest(ids=approved_ids, status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _descriptor_path, descriptor = self.make(root)
                approval_path = Path(descriptor["approval"]["path"])
                approval = json.loads(approval_path.read_text())
                approval["approved_target_ids"] = approved_ids
                approval["status"] = status
                descriptor["approval"]["sha256"] = _write_json(approval_path, approval)
                descriptor_path = root / "descriptor.json"
                _write_json(descriptor_path, descriptor)
                with self.assertRaises(HistoricalBatchPipelineError):
                    build_historical_batch_shard_plan(
                        descriptor_path=descriptor_path,
                        shard_id="japan-01",
                        output_dir=root / "published",
                    )

    def test_selection_non_integer_identity_values_are_rejected(self):
        for field, value in (("target_id", True), ("target_id", 1.5), ("year", True), ("year", 2024.5)):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _descriptor_path, descriptor = self.make(root)
                selection_path = Path(descriptor["selection"]["path"])
                selection = json.loads(selection_path.read_text())
                selection["targets"][0][field] = value
                selection_sha = _write_json(selection_path, selection)

                manifest_path = Path(descriptor["batch_manifest"]["path"])
                manifest = json.loads(manifest_path.read_text())
                manifest["artifacts"]["selection_snapshot"].update(
                    sha256=selection_sha,
                    size=selection_path.stat().st_size,
                )
                manifest_sha = _write_json(manifest_path, manifest)

                approval_path = Path(descriptor["approval"]["path"])
                approval = json.loads(approval_path.read_text())
                approval["manifest_identity"].update(
                    sha256=manifest_sha,
                    size=manifest_path.stat().st_size,
                )
                descriptor["selection"]["sha256"] = selection_sha
                descriptor["batch_manifest"]["sha256"] = manifest_sha
                descriptor["approval"]["sha256"] = _write_json(approval_path, approval)
                descriptor_path = root / "descriptor-boolean.json"
                _write_json(descriptor_path, descriptor)
                with self.assertRaises(HistoricalBatchPipelineError):
                    build_historical_batch_shard_plan(
                        descriptor_path=descriptor_path,
                        shard_id="japan-01",
                        output_dir=root / "published",
                    )

    def test_rejects_missing_duplicate_cross_region_and_oversized_shards(self):
        cases = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root)
            missing = deepcopy(descriptor)
            missing["shards"][0]["target_ids"] = [1]
            cases.append(missing)
            duplicate = deepcopy(descriptor)
            duplicate["shards"].append(deepcopy(duplicate["shards"][0]))
            duplicate["shards"][1]["id"] = "japan-02"
            cases.append(duplicate)
            cross_region = deepcopy(descriptor)
            cross_region["shards"][0]["country_region"] = RacingRegion.FRANCE
            cases.append(cross_region)
            for index, case in enumerate(cases):
                path = root / f"invalid-{index}.json"
                _write_json(path, case)
                with self.subTest(index=index), self.assertRaises(HistoricalBatchPipelineError):
                    build_historical_batch_shard_plan(
                        descriptor_path=path,
                        shard_id=case["shards"][0]["id"],
                        output_dir=root / f"out-{index}",
                    )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root, count=251)
            path = root / "invalid-oversized.json"
            _write_json(path, descriptor)
            with self.assertRaises(HistoricalBatchPipelineError):
                build_historical_batch_shard_plan(
                    descriptor_path=path,
                    shard_id="japan-01",
                    output_dir=root / "out",
                )

    def test_rejects_raw_argv_unknown_policy_and_actual_input_scope_mismatch(self):
        mutations = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root)
            raw = deepcopy(descriptor)
            raw["shards"][0]["recipes"][0]["argv"] = ["python", "bad.py"]
            mutations.append(raw)
            unknown = deepcopy(descriptor)
            unknown["shards"][0]["recipes"][0]["tool"] = "unknown.py"
            mutations.append(unknown)
            mismatched = deepcopy(descriptor)
            events = Path(mismatched["shards"][0]["recipes"][0]["inputs"]["events_csv"][0])
            rows = list(csv.DictReader(events.open(encoding="utf-8-sig")))[:1]
            _write_events(
                events,
                [
                    {
                        "target_id": int(rows[0]["target_id"]),
                        "target_sha256": rows[0]["target_sha256"],
                        "inventory_artifact_sha256": rows[0]["inventory_artifact_sha256"],
                        "year": int(rows[0]["year"]),
                        "series_key": rows[0]["series_key"],
                        "country_region": rows[0]["country_region"],
                    }
                ],
            )
            mutations.append(mismatched)
            for index, case in enumerate(mutations):
                path = root / f"invalid-recipe-{index}.json"
                _write_json(path, case)
                with self.subTest(index=index), self.assertRaises(HistoricalBatchPipelineError):
                    build_historical_batch_shard_plan(
                        descriptor_path=path,
                        shard_id="japan-01",
                        output_dir=root / f"out-{index}",
                    )

    def test_rejects_invalid_budget_output_overlap_existing_destination_and_symlink(self):
        for budget in (0, 251, "2"):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _descriptor_path, descriptor = self.make(root)
                descriptor["shards"][0]["request_budget"] = budget
                path = root / "descriptor.json"
                _write_json(path, descriptor)
                with self.assertRaises(HistoricalBatchPipelineError):
                    build_historical_batch_shard_plan(
                        descriptor_path=path,
                        shard_id="japan-01",
                        output_dir=root / "out",
                    )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            output = root / "out"
            output.mkdir()
            with self.assertRaises(HistoricalBatchPipelineError):
                build_historical_batch_shard_plan(
                    descriptor_path=descriptor_path,
                    shard_id="japan-01",
                    output_dir=output,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root)
            events = Path(descriptor["shards"][0]["recipes"][0]["inputs"]["events_csv"][0])
            real = events.with_suffix(".real")
            events.rename(real)
            events.symlink_to(real)
            path = root / "descriptor.json"
            _write_json(path, descriptor)
            with self.assertRaises(HistoricalBatchPipelineError):
                build_historical_batch_shard_plan(
                    descriptor_path=path,
                    shard_id="japan-01",
                    output_dir=root / "out",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root)
            descriptor["shards"][0]["recipes"][0]["outputs"]["output_dir"] = (
                "inputs/selection_snapshot.json"
            )
            path = root / "descriptor-reserved-output.json"
            _write_json(path, descriptor)
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "outputs/"):
                build_historical_batch_shard_plan(
                    descriptor_path=path,
                    shard_id="japan-01",
                    output_dir=root / "out",
                )

    def test_canonical_output_is_stable_when_descriptor_keys_and_target_order_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, descriptor = self.make(root)
            first = build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "first",
            )
            descriptor["shards"][0]["target_ids"].reverse()
            reordered = json.loads(json.dumps(descriptor, sort_keys=False))
            second_descriptor = root / "second-descriptor.json"
            _write_json(second_descriptor, reordered)
            second = build_historical_batch_shard_plan(
                descriptor_path=second_descriptor,
                shard_id="japan-01",
                output_dir=root / "second",
            )
            self.assertEqual(first["plan_contract_sha256"], second["plan_contract_sha256"])
            self.assertEqual(first["scope_sha256"], second["scope_sha256"])

    def test_all_initial_typed_recipe_policies_build_and_bind_exact_scope(self):
        cases = (
            (
                "discover_historical_race_band_sources.py",
                RacingRegion.JAPAN,
                lambda paths: {"selection_snapshot": [str(paths["selection"])]},
                {"output_jsonl": "outputs/providers.jsonl", "issues_json": "outputs/issues.json"},
                {"year": 2024},
            ),
            (
                "cache_historical_race_date_sources.py",
                RacingRegion.JAPAN,
                lambda paths: {"provider_jsonl": [str(paths["providers"])]},
                {
                    "output_root": "outputs/cache",
                    "request_ledger": "outputs/request-ledger.jsonl",
                    "summary": "outputs/cache-summary.json",
                },
                {"allow_network": True, "timeout": 30},
            ),
            (
                "prepare_jra_race_detail_candidates.py",
                RacingRegion.JAPAN,
                lambda paths: {
                    "events_csv": [str(paths["events"])],
                    "source_html": [str(paths["source_html"])],
                },
                {"output_dir": "outputs/jra"},
                {"allow_network": True, "fail_fast": True},
            ),
            (
                "prepare_hkjc_race_detail_candidates.py",
                RacingRegion.HONG_KONG,
                lambda paths: {"events_csv": [str(paths["events"])]},
                {"output_dir": "outputs/hkjc"},
                {"allow_network": True, "fail_fast": True},
            ),
            (
                "prepare_uk_sportinglife_race_detail_candidates.py",
                RacingRegion.UNITED_KINGDOM,
                lambda paths: {"events_csv": [str(paths["events"])]},
                {"output_dir": "outputs/uk"},
                {"allow_network": True, "fail_fast": True},
            ),
            (
                "prepare_france_zeturf_race_detail_candidates.py",
                RacingRegion.FRANCE,
                lambda paths: {"events_csv": [str(paths["events"])]},
                {"output_dir": "outputs/france"},
                {"allow_network": True, "fail_fast": True},
            ),
            (
                "prepare_us_equibase_result_candidates.py",
                RacingRegion.UNITED_STATES,
                lambda paths: {
                    "events_csv": [str(paths["events"])],
                    "runner_jsonl": [str(paths["runners"])],
                    "pdf_dir": [str(paths["pdf_dir"])],
                },
                {"output_dir": "outputs/us"},
                {"fail_fast": True},
            ),
            (
                "prepare_cached_historical_race_details.py",
                RacingRegion.JAPAN,
                lambda paths: {
                    "events_csv": [str(paths["events"])],
                    "source_cache_manifest": [str(paths["cache_manifest"])],
                },
                {
                    "output_jsonl": "outputs/cached.jsonl",
                    "gap_json": "outputs/cached-gaps.json",
                    "summary": "outputs/cached-summary.json",
                },
                {},
            ),
            (
                "package_historical_race_detail_candidates.py",
                RacingRegion.JAPAN,
                lambda paths: {
                    "events_csv": [str(paths["events"])],
                    "candidate_jsonl": [str(paths["candidates"])],
                    "source_cache_manifest": [str(paths["cache_manifest"])],
                },
                {
                    "output_jsonl": "outputs/formal.jsonl",
                    "gap_json": "outputs/formal-gaps.json",
                    "summary": "outputs/formal-summary.json",
                },
                {},
            ),
            (
                "merge_historical_race_batch_fragments.py",
                RacingRegion.JAPAN,
                lambda paths: {
                    "selection": [str(paths["selection"])],
                    "fragment": [str(paths["candidates"])],
                    "source_cache_manifest": [str(paths["cache_manifest"])],
                },
                {"output_dir": "outputs/merged"},
                {"mode": "detail", "recorded_at": RECORDED_AT},
            ),
        )
        repository_root = Path(__file__).resolve().parents[2]
        tool_root = repository_root / "runtime" / "tools"
        for index, (tool_name, region, inputs_builder, outputs, options) in enumerate(cases):
            with self.subTest(tool=tool_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                descriptor_path, descriptor = self.make(root)
                selection_path = Path(descriptor["selection"]["path"])
                selection = json.loads(selection_path.read_text())
                for target in selection["targets"]:
                    target["country_region"] = region
                    if tool_name == "discover_historical_race_band_sources.py":
                        target["year"] = 2024
                selection_sha = _write_json(selection_path, selection)
                events_path = Path(descriptor["shards"][0]["recipes"][0]["inputs"]["events_csv"][0])
                _write_events(events_path, selection["targets"])
                manifest_path = Path(descriptor["batch_manifest"]["path"])
                manifest = json.loads(manifest_path.read_text())
                manifest["artifacts"]["selection_snapshot"].update(
                    sha256=selection_sha, size=selection_path.stat().st_size
                )
                manifest_sha = _write_json(manifest_path, manifest)
                approval_path = Path(descriptor["approval"]["path"])
                approval = json.loads(approval_path.read_text())
                approval["manifest_identity"].update(
                    sha256=manifest_sha, size=manifest_path.stat().st_size
                )
                approval_sha = _write_json(approval_path, approval)
                providers = root / "bootstrap" / "providers.jsonl"
                _write_jsonl(
                    providers,
                    [
                        {
                            "target_id": target["target_id"],
                            "series_key": target["series_key"],
                            "edition_year": target["year"],
                        }
                        for target in selection["targets"]
                    ],
                )
                runners = root / "bootstrap" / "runners.jsonl"
                _write_jsonl(runners, [{"slug": "fixture"}])
                candidates = root / "bootstrap" / "candidates.jsonl"
                if tool_name == "package_historical_race_detail_candidates.py":
                    candidate_rows = [
                        {"year": target["year"], "slug": f"race-{target['target_id']}"}
                        for target in selection["targets"]
                    ]
                elif tool_name == "merge_historical_race_batch_fragments.py":
                    candidate_rows = [
                        {
                            "target_id": target["target_id"],
                            "series_key": target["series_key"],
                            "edition_year": target["year"],
                        }
                        for target in selection["targets"]
                    ]
                else:
                    candidate_rows = [{"fixture": True}]
                _write_jsonl(candidates, candidate_rows)
                source_html = root / "bootstrap" / "source.html"
                source_html.write_text("fixture", encoding="utf-8")
                cache_manifest = root / "bootstrap" / "source_cache_manifest.json"
                _write_json(cache_manifest, {"schema_version": "1.0", "files": {}})
                pdf_dir = root / "bootstrap" / "pdfs"
                pdf_dir.mkdir()
                (pdf_dir / "chart.pdf").write_bytes(b"fixture")
                paths = {
                    "selection": selection_path,
                    "events": events_path,
                    "providers": providers,
                    "runners": runners,
                    "candidates": candidates,
                    "source_html": source_html,
                    "cache_manifest": cache_manifest,
                    "pdf_dir": pdf_dir,
                }
                tool_path = tool_root / tool_name
                descriptor["selection"]["sha256"] = selection_sha
                descriptor["batch_manifest"]["sha256"] = manifest_sha
                descriptor["approval"]["sha256"] = approval_sha
                descriptor["tool_root"] = str(tool_root)
                descriptor["tool_manifest"] = {tool_name: hashlib.sha256(tool_path.read_bytes()).hexdigest()}
                descriptor["shards"][0]["country_region"] = region
                descriptor["shards"][0]["recipes"] = [
                    {
                        "tool": tool_name,
                        "inputs": inputs_builder(paths),
                        "outputs": outputs,
                        "options": options,
                    }
                ]
                descriptor_path = root / f"descriptor-{index}.json"
                _write_json(descriptor_path, descriptor)
                result = build_historical_batch_shard_plan(
                    descriptor_path=descriptor_path,
                    shard_id="japan-01",
                    output_dir=root / "published",
                )
                self.assertEqual(result["target_count"], 2)
                if tool_name == "discover_historical_race_band_sources.py":
                    missing_year = deepcopy(descriptor)
                    missing_year["shards"][0]["recipes"][0]["options"].pop("year")
                    missing_year_path = root / "descriptor-missing-year.json"
                    _write_json(missing_year_path, missing_year)
                    with self.assertRaisesMessage(
                        HistoricalBatchPipelineError, "required options"
                    ):
                        build_historical_batch_shard_plan(
                            descriptor_path=missing_year_path,
                            shard_id="japan-01",
                            output_dir=root / "missing-year-published",
                        )

                    selection["targets"][1]["year"] = 2025
                    mixed_selection_sha = _write_json(selection_path, selection)
                    manifest["artifacts"]["selection_snapshot"].update(
                        sha256=mixed_selection_sha,
                        size=selection_path.stat().st_size,
                    )
                    mixed_manifest_sha = _write_json(manifest_path, manifest)
                    approval["manifest_identity"].update(
                        sha256=mixed_manifest_sha,
                        size=manifest_path.stat().st_size,
                    )
                    descriptor["selection"]["sha256"] = mixed_selection_sha
                    descriptor["batch_manifest"]["sha256"] = mixed_manifest_sha
                    descriptor["approval"]["sha256"] = _write_json(
                        approval_path, approval
                    )
                    mixed_year_path = root / "descriptor-mixed-year.json"
                    _write_json(mixed_year_path, descriptor)
                    with self.assertRaisesMessage(
                        HistoricalBatchPipelineError, "actual target scope"
                    ):
                        build_historical_batch_shard_plan(
                            descriptor_path=mixed_year_path,
                            shard_id="japan-01",
                            output_dir=root / "mixed-year-published",
                        )
                if tool_name in {
                    "prepare_jra_race_detail_candidates.py",
                    "prepare_hkjc_race_detail_candidates.py",
                    "prepare_uk_sportinglife_race_detail_candidates.py",
                    "prepare_france_zeturf_race_detail_candidates.py",
                }:
                    limited = deepcopy(descriptor)
                    limited["shards"][0]["recipes"][0]["options"]["limit"] = 1
                    limited_path = root / "descriptor-truncated-limit.json"
                    _write_json(limited_path, limited)
                    with self.assertRaisesMessage(
                        HistoricalBatchPipelineError, "truncate"
                    ):
                        build_historical_batch_shard_plan(
                            descriptor_path=limited_path,
                            shard_id="japan-01",
                            output_dir=root / "truncated-limit-published",
                        )
                if tool_name == "prepare_france_zeturf_race_detail_candidates.py":
                    date_filtered = deepcopy(descriptor)
                    date_filtered["shards"][0]["recipes"][0]["options"].update(
                        start_date="2099-01-01",
                        end_date="2099-12-31",
                    )
                    date_filtered_path = root / "descriptor-date-filtered.json"
                    _write_json(date_filtered_path, date_filtered)
                    with self.assertRaisesMessage(
                        HistoricalBatchPipelineError, "actual target scope"
                    ):
                        build_historical_batch_shard_plan(
                            descriptor_path=date_filtered_path,
                            shard_id="japan-01",
                            output_dir=root / "date-filtered-published",
                        )
                if tool_name in {
                    "package_historical_race_detail_candidates.py",
                    "merge_historical_race_batch_fragments.py",
                }:
                    if tool_name == "package_historical_race_detail_candidates.py":
                        candidate_rows.append(
                            {"target_id": 1, "year": 2099, "slug": "outside"}
                        )
                    else:
                        candidate_rows.append({"target_id": 999})
                    _write_jsonl(candidates, candidate_rows)
                    with self.assertRaises(HistoricalBatchPipelineError):
                        build_historical_batch_shard_plan(
                            descriptor_path=descriptor_path,
                            shard_id="japan-01",
                            output_dir=root / "invalid-published",
                        )
                if tool_name == "merge_historical_race_batch_fragments.py":
                    _write_jsonl(candidates, candidate_rows[:1])
                    conflicting_gap = root / "bootstrap" / "conflicting-gap.jsonl"
                    _write_jsonl(
                        conflicting_gap,
                        [
                            {
                                "target_id": selection["targets"][1]["target_id"],
                                "series_key": selection["targets"][0]["series_key"],
                                "edition_year": selection["targets"][0]["year"],
                            }
                        ],
                    )
                    descriptor["shards"][0]["recipes"][0]["inputs"]["gap"] = [
                        str(conflicting_gap)
                    ]
                    conflicting_descriptor = root / "descriptor-conflicting-gap.json"
                    _write_json(conflicting_descriptor, descriptor)
                    with self.assertRaisesMessage(
                        HistoricalBatchPipelineError, "identities conflict"
                    ):
                        build_historical_batch_shard_plan(
                            descriptor_path=conflicting_descriptor,
                            shard_id="japan-01",
                            output_dir=root / "conflicting-gap-published",
                        )


class HistoricalBatchFormalResourceTests(TestCase, HistoricalBatchPlanFixture):
    def test_formal_runner_rejects_boolean_limits_and_selection_identity_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            plan = json.loads((root / "published" / "runner-plan.json").read_text())
            for field in plan["resource_limits"]:
                with self.subTest(field=field):
                    invalid = deepcopy(plan)
                    invalid["resource_limits"][field] = True
                    with self.assertRaisesMessage(Exception, "resource_limits"):
                        validate_runner_plan(invalid)
            for mutation in (
                lambda value: value["selection_identity"].update(sha256=SHA_B),
                lambda value: value["selection_identity"].update(approved_target_ids=[True]),
                lambda value: value["selection_identity"].update(approved_target_ids=[1, 1]),
                lambda value: value["selection_identity"].update(approved_target_ids=[999]),
            ):
                invalid = deepcopy(plan)
                mutation(invalid)
                with self.assertRaises(Exception):
                    validate_runner_plan(invalid)

    def test_formal_runner_rejects_rebound_approval_manifest_relationship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            plan_path = root / "published" / "runner-plan.json"
            plan = json.loads(plan_path.read_text())
            approval_path = Path(plan["batch_identity"]["approval"]["path"])
            approval = json.loads(approval_path.read_text())
            approval["manifest_identity"]["sha256"] = SHA_B
            approval_sha = _write_json(approval_path, approval)
            plan["batch_identity"]["approval"].update(
                sha256=approval_sha,
                size=approval_path.stat().st_size,
            )
            with self.assertRaisesMessage(Exception, "scope"):
                validate_runner_plan(plan)

    def test_formal_runner_rejects_argv_paths_outside_declared_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            plan = json.loads((root / "published" / "runner-plan.json").read_text())
            selection_path = plan["batch_identity"]["selection"]["path"]

            overwritten = deepcopy(plan)
            old_output = overwritten["steps"][0]["output_directories"][0]["path"]
            overwritten["steps"][0]["output_directories"][0]["path"] = selection_path
            overwritten["steps"][0]["argv"] = [
                selection_path if value == old_output else value
                for value in overwritten["steps"][0]["argv"]
            ]
            with self.assertRaisesMessage(Exception, "outputs/"):
                validate_runner_plan(overwritten)

            undeclared = deepcopy(plan)
            declared_input = undeclared["steps"][0]["inputs"][0]["path"]
            undeclared["steps"][0]["argv"] = [
                str(root / "published" / "scope.json")
                if value == declared_input
                else value
                for value in undeclared["steps"][0]["argv"]
            ]
            with self.assertRaisesMessage(Exception, "undeclared artifact path"):
                validate_runner_plan(undeclared)

            broad_directory = deepcopy(plan)
            broad_directory["steps"][0]["argv"] = [
                str(root / "published" / "inputs")
                if value == declared_input
                else value
                for value in broad_directory["steps"][0]["argv"]
            ]
            with self.assertRaisesMessage(Exception, "undeclared input path"):
                validate_runner_plan(broad_directory)

    @override_settings(
        HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET=1,
        HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES=1024 * 1024,
        HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES=5 * 1024 * 1024 * 1024,
    )
    def test_resource_identity_mismatch_is_rejected_before_run_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            plan = json.loads((root / "published" / "runner-plan.json").read_text())
            with self.assertRaisesMessage(Exception, "resource identity"):
                validate_runner_resource_limits(plan)
            token = root / "owner.token"
            token.write_text("secret", encoding="utf-8")
            token.chmod(0o600)
            with self.assertRaisesMessage(Exception, "resource identity"):
                call_command(
                    "run_historical_batch_stage",
                    plan=str(root / "published" / "runner-plan.json"),
                    owner_token_file=str(token),
                    lock_file=str(root / "published" / ".runner.lock"),
                    run_id="resource-mismatch",
                )
            self.assertEqual(HistoricalBatchRun.objects.count(), 0)

    @override_settings(
        HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET=2,
        HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES=1024 * 1024,
        HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES=5 * 1024 * 1024 * 1024,
    )
    def test_matching_resource_identity_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor_path, _descriptor = self.make(root)
            build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="japan-01",
                output_dir=root / "published",
            )
            plan = json.loads((root / "published" / "runner-plan.json").read_text())
            self.assertEqual(validate_runner_resource_limits(plan), plan["resource_limits"])


class HistoricalBatchFragmentFixture:
    def make(self, root: Path) -> tuple[Path, list[dict]]:
        targets = [
            {
                "target_id": 1,
                "target_sha256": hashlib.sha256(b"target-1").hexdigest(),
                "inventory_artifact_sha256": SHA_A,
                "series_key": "series-one",
                "year": 2024,
                "country_region": RacingRegion.UNITED_KINGDOM,
            },
            {
                "target_id": 2,
                "target_sha256": hashlib.sha256(b"target-2").hexdigest(),
                "inventory_artifact_sha256": SHA_A,
                "series_key": "series-two",
                "year": 2025,
                "country_region": RacingRegion.UNITED_KINGDOM,
            },
        ]
        selection = root / "selection.json"
        _write_json(
            selection,
            {"schema_version": "1.0", "inventory_manifest_sha256": SHA_A, "targets": targets},
        )
        return selection, targets

    def date_row(self, target: dict, *, local_date: str, url: str | None = None) -> dict:
        return {
            "target_id": target["target_id"],
            "target_sha256": target["target_sha256"],
            "inventory_artifact_sha256": SHA_A,
            "adapter_key": "sporting_life",
            "series_key": target["series_key"],
            "edition_year": target["year"],
            "local_date": local_date,
            "distance_text": "2m4f",
            "urls": {
                "result_url": {
                    "url": url or f"https://example.test/{target['target_id']}",
                    "source_provider": "sporting_life",
                    "source_authority": "third_party_high_access",
                    "redirect_chain": [],
                }
            },
        }

    def make_cache(self, root: Path, targets: list[dict]) -> tuple[Path, dict[int, dict]]:
        cache_root = root / "cache"
        cache_root.mkdir()
        files = {}
        identities = {}
        for target in targets:
            source_url = f"https://example.test/{target['target_id']}"
            source = cache_root / f"{target['target_id']}.html"
            source.write_bytes(f"body-{target['target_id']}".encode())
            identity = {
                "source_url": source_url,
                "path": source.name,
                "size": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            files[source.name] = identity
            identities[target["target_id"]] = identity
        manifest = cache_root / "source_cache_manifest.json"
        _write_json(manifest, {"schema_version": "1.0", "files": files})
        return manifest, identities

    def detail_row(
        self,
        target: dict,
        *,
        cache_identity: dict | None = None,
        winner: str = "Winner",
        first: str = "First",
    ) -> dict:
        source_url = f"https://example.test/{target['target_id']}"
        identity = cache_identity or {
            "source_url": source_url,
            "path": f"{target['target_id']}.html",
            "size": 4,
            "sha256": SHA_B,
        }
        return {
            "target_id": target["target_id"],
            "target_sha256": target["target_sha256"],
            "inventory_artifact_sha256": SHA_A,
            "source_name": "sporting_life",
            "source_url": source_url,
            "modules": {
                "runners": {
                    "is_complete": True,
                    "items": [{"horse_number": "1", "horse_name": first, "source_refs": {}}],
                    "source_cache_identity": identity,
                },
                "results": {
                    "is_complete": True,
                    "items": [{"finish_position": 1, "horse_number": "2", "horse_name": winner, "source_refs": {}}],
                    "source_cache_identity": identity,
                },
            },
        }

    def gap_row(self, target: dict, reason: str = "source_unavailable") -> dict:
        return {
            "target_id": target["target_id"],
            "target_sha256": target["target_sha256"],
            "reason_code": reason,
            "evidence_identity": {"path": "request-ledger.jsonl", "sha256": SHA_B},
            "source_url": f"https://example.test/{target['target_id']}",
            "recorded_at": "2026-07-15T00:00:00Z",
        }


class HistoricalBatchFragmentMergeTests(SimpleTestCase, HistoricalBatchFragmentFixture):
    def test_fractional_json_fragment_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            fragment = self.date_row(targets[0], local_date="2024-01-01")
            fragment["target_id"] = float(targets[0]["target_id"]) + 0.5
            fragments = root / "fragments.jsonl"
            _write_jsonl(fragments, [fragment])
            with self.assertRaisesMessage(
                HistoricalBatchPipelineError, "fragment target is outside selection"
            ):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[],
                    output_dir=root / "output",
                    recorded_at=RECORDED_AT,
                )

    def test_rejects_impossible_dates_and_malformed_evidence_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            fragments = root / "fragments.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.date_row(targets[0], local_date="2024-02-30"),
                    self.date_row(targets[1], local_date="2025-01-01"),
                ],
            )
            result = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[],
                output_dir=root / "bad-date",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 1)
            invalid_gap = json.loads((root / "bad-date" / "gaps.jsonl").read_text())
            self.assertEqual(invalid_gap["target_id"], targets[0]["target_id"])
            self.assertEqual(invalid_gap["reason_code"], "invalid_fragment")

            _write_jsonl(fragments, [self.date_row(targets[0], local_date="2024-01-01")])
            gaps = root / "gaps.jsonl"
            gap = self.gap_row(targets[1])
            gap["recorded_at"] = "2026-13-40T00:00:00Z"
            _write_jsonl(gaps, [gap])
            with self.assertRaises(HistoricalBatchPipelineError):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[gaps],
                    evidence_paths=[],
                    output_dir=root / "bad-gap-time",
                    recorded_at=RECORDED_AT,
                )

    def test_date_merge_is_complete_deterministic_and_preserves_original_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            first = root / "a.jsonl"
            second = root / "b.jsonl"
            _write_jsonl(first, [self.date_row(targets[1], local_date="2025-01-01")])
            _write_jsonl(second, [self.date_row(targets[0], local_date="2024-01-01")])
            one = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[first, second],
                gap_paths=[],
                evidence_paths=[],
                output_dir=root / "out-one",
                recorded_at=RECORDED_AT,
            )
            two = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[second, first],
                gap_paths=[],
                evidence_paths=[],
                output_dir=root / "out-two",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(one["complete_count"], 2)
            self.assertEqual(one["gap_count"], 0)
            self.assertEqual(one["data_complete_rate"], 1.0)
            self.assertEqual(one["complete_sha256"], two["complete_sha256"])
            rows = [json.loads(line) for line in (root / "out-one" / "complete.jsonl").read_text().splitlines()]
            self.assertEqual([row["distance_text"] for row in rows], ["2m4f", "2m4f"])

    def test_date_merge_binds_real_provider_rows_without_embedded_target_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            rows = []
            for target in targets:
                row = self.date_row(
                    target,
                    local_date=f"{target['year']}-01-01",
                )
                row.pop("target_id")
                row.pop("target_sha256")
                row.pop("inventory_artifact_sha256")
                rows.append(row)
            fragments = root / "providers.jsonl"
            _write_jsonl(fragments, rows)
            result = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 2)
            merged = [
                json.loads(line)
                for line in (root / "out" / "complete.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                [row["target_sha256"] for row in merged],
                [target["target_sha256"] for target in targets],
            )
            conflicting = self.date_row(targets[0], local_date="2024-01-01")
            conflicting["series_key"] = targets[1]["series_key"]
            conflicting["edition_year"] = targets[1]["year"]
            _write_jsonl(fragments, [conflicting, self.date_row(targets[1], local_date="2025-01-01")])
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "identities conflict"):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[],
                    output_dir=root / "conflicting-identities",
                    recorded_at=RECORDED_AT,
                )

    def test_missing_without_evidence_and_complete_gap_overlap_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            complete = root / "complete.jsonl"
            gaps = root / "gaps.jsonl"
            _write_jsonl(complete, [self.date_row(targets[0], local_date="2024-01-01")])
            _write_jsonl(gaps, [])
            with self.assertRaises(HistoricalBatchPipelineError):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[complete],
                    gap_paths=[gaps],
                    evidence_paths=[],
                    output_dir=root / "missing",
                    recorded_at=RECORDED_AT,
                )

    def test_legacy_json_array_gap_is_bound_to_selection_and_input_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            complete = root / "complete.jsonl"
            gaps = root / "package-gaps.json"
            _write_jsonl(
                complete,
                [self.date_row(targets[0], local_date="2024-01-01")],
            )
            _write_json(
                gaps,
                [
                    {
                        "target_id": targets[1]["target_id"],
                        "year": targets[1]["year"],
                        "slug": "series-two-2025",
                        "reason": "missing_candidate",
                    }
                ],
            )
            result = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[complete],
                gap_paths=[gaps],
                evidence_paths=[],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 1)
            self.assertEqual(result["gap_count"], 1)
            gap = json.loads((root / "out" / "gaps.jsonl").read_text())
            self.assertEqual(gap["target_sha256"], targets[1]["target_sha256"])
            self.assertEqual(gap["reason_code"], "missing_candidate")
            self.assertEqual(gap["evidence_identity"]["sha256"], hashlib.sha256(gaps.read_bytes()).hexdigest())
            _write_jsonl(gaps, [self.gap_row(targets[0]), self.gap_row(targets[1])])
            with self.assertRaises(HistoricalBatchPipelineError):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[complete],
                    gap_paths=[gaps],
                    evidence_paths=[],
                    output_dir=root / "overlap",
                    recorded_at=RECORDED_AT,
                )

    def test_single_line_formal_gap_jsonl_remains_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            complete = root / "complete.jsonl"
            gaps = root / "gap.jsonl"
            _write_jsonl(
                complete,
                [self.date_row(targets[0], local_date="2024-01-01")],
            )
            _write_jsonl(gaps, [self.gap_row(targets[1])])
            result = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[complete],
                gap_paths=[gaps],
                evidence_paths=[],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 1)
            self.assertEqual(result["gap_count"], 1)
            merged_gap = json.loads((root / "out" / "gaps.jsonl").read_text())
            self.assertEqual(
                merged_gap["evidence_identity"]["sha256"],
                hashlib.sha256(gaps.read_bytes()).hexdigest(),
            )
            self.assertNotEqual(
                merged_gap["evidence_identity"]["sha256"],
                self.gap_row(targets[1])["evidence_identity"]["sha256"],
            )

    def test_conflicting_date_or_url_becomes_evidenced_conflict_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            rows = root / "rows.jsonl"
            gaps = root / "gaps.jsonl"
            _write_jsonl(
                rows,
                [
                    self.date_row(targets[0], local_date="2024-01-01"),
                    self.date_row(targets[0], local_date="2024-01-02"),
                    self.date_row(targets[1], local_date="2025-01-01"),
                ],
            )
            _write_jsonl(gaps, [])
            result = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[rows],
                gap_paths=[gaps],
                evidence_paths=[],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 1)
            self.assertEqual(result["gap_count"], 1)
            self.assertEqual(result["conflict_count"], 1)
            conflict = json.loads((root / "out" / "gaps.jsonl").read_text().splitlines()[0])
            self.assertEqual(conflict["reason_code"], "conflicting_fragments")
            self.assertEqual(len(conflict["conflicting_evidence"]), 2)

    def test_detail_merge_requires_complete_nonempty_unique_modules_and_https_cache_identity(self):
        mutators = (
            lambda row: row["modules"].pop("results"),
            lambda row: row["modules"]["runners"].update(items=[]),
            lambda row: row["modules"]["results"].update(is_complete=False),
            lambda row: row["modules"]["runners"]["items"].append(
                {"horse_number": "1", "horse_name": "Duplicate"}
            ),
            lambda row: row.update(source_url="http://example.test/1"),
        )
        for index, mutate in enumerate(mutators):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                selection, targets = self.make(root)
                cache_manifest, cache_identities = self.make_cache(root, targets)
                invalid = self.detail_row(
                    targets[0], cache_identity=cache_identities[targets[0]["target_id"]]
                )
                mutate(invalid)
                fragments = root / "fragments.jsonl"
                gaps = root / "gaps.jsonl"
                _write_jsonl(
                    fragments,
                    [
                        invalid,
                        self.detail_row(
                            targets[1], cache_identity=cache_identities[targets[1]["target_id"]]
                        ),
                    ],
                )
                _write_jsonl(gaps, [])
                result = merge_historical_race_fragments(
                    mode="detail",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[gaps],
                    evidence_paths=[],
                    output_dir=root / "out",
                    source_cache_manifest_paths=[cache_manifest],
                    recorded_at=RECORDED_AT,
                )
                self.assertEqual(result["complete_count"], 1)
                self.assertEqual(result["gap_count"], 1)

    def test_detail_merge_allows_multiple_blank_horse_numbers_from_official_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            cache_manifest, cache_identities = self.make_cache(root, targets)
            rows = []
            for target in targets:
                row = self.detail_row(
                    target,
                    cache_identity=cache_identities[target["target_id"]],
                )
                row["modules"]["runners"]["items"] = [
                    {"horse_number": "", "horse_name": "Runner A"},
                    {"horse_number": None, "horse_name": "Runner B"},
                ]
                rows.append(row)
            fragments = root / "fragments.jsonl"
            _write_jsonl(fragments, rows)
            result = merge_historical_race_fragments(
                mode="detail",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[],
                source_cache_manifest_paths=[cache_manifest],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 2)
            self.assertEqual(result["gap_count"], 0)

    def test_detail_conflict_does_not_last_write_win_and_unicode_is_lossless(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            cache_manifest, cache_identities = self.make_cache(root, targets)
            fragments = root / "fragments.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.detail_row(
                        targets[0],
                        cache_identity=cache_identities[targets[0]["target_id"]],
                        winner="勝馬",
                        first="一号馬",
                    ),
                    self.detail_row(
                        targets[0],
                        cache_identity=cache_identities[targets[0]["target_id"]],
                        winner="Other",
                        first="一号馬",
                    ),
                    self.detail_row(
                        targets[1],
                        cache_identity=cache_identities[targets[1]["target_id"]],
                        winner="Vainqueur",
                        first="Premier",
                    ),
                ],
            )
            result = merge_historical_race_fragments(
                mode="detail",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[],
                output_dir=root / "out",
                source_cache_manifest_paths=[cache_manifest],
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["conflict_count"], 1)
            self.assertIn("Vainqueur", (root / "out" / "complete.jsonl").read_text())

    def test_detail_merge_rejects_source_cache_file_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            cache_manifest, cache_identities = self.make_cache(root, targets)
            fragments = root / "fragments.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.detail_row(
                        target,
                        cache_identity=cache_identities[target["target_id"]],
                    )
                    for target in targets
                ],
            )
            (cache_manifest.parent / "1.html").write_bytes(b"drifted")
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "drifted"):
                merge_historical_race_fragments(
                    mode="detail",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[],
                    source_cache_manifest_paths=[cache_manifest],
                    output_dir=root / "out",
                    recorded_at=RECORDED_AT,
                )
            self.assertFalse((root / "out").exists())

    def test_detail_merge_rejects_symlinked_source_cache_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            cache_manifest, cache_identities = self.make_cache(root, targets)
            fragments = root / "fragments.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.detail_row(
                        target,
                        cache_identity=cache_identities[target["target_id"]],
                    )
                    for target in targets
                ],
            )
            cached = cache_manifest.parent / "1.html"
            real = cache_manifest.parent / "1-real.html"
            cached.rename(real)
            cached.symlink_to(real.name)
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "symlink"):
                merge_historical_race_fragments(
                    mode="detail",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[],
                    source_cache_manifest_paths=[cache_manifest],
                    output_dir=root / "out",
                    recorded_at=RECORDED_AT,
                )

    def test_manual_evidence_applies_only_when_target_and_old_value_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            fragments = root / "fragments.jsonl"
            evidence = root / "evidence.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.date_row(targets[0], local_date="2024-01-01"),
                    self.date_row(targets[1], local_date="2025-01-01"),
                ],
            )
            _write_jsonl(
                evidence,
                [
                    {
                        "target_id": 1,
                        "target_sha256": targets[0]["target_sha256"],
                        "field": "local_date",
                        "expected_old_value": "2024-01-01",
                        "new_value": "2024-01-02",
                        "source_url": "https://authority.test/result",
                        "source_authority": "official",
                        "reason": "official correction",
                        "reviewed_by": "operator",
                        "reviewed_at": "2026-07-15T00:00:00Z",
                    }
                ],
            )
            merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[evidence],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            row = json.loads((root / "out" / "complete.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["local_date"], "2024-01-02")
            self.assertEqual(row["manual_evidence"][0]["reviewed_by"], "operator")

            bad = json.loads(evidence.read_text().splitlines()[0])
            bad["expected_old_value"] = "wrong"
            _write_jsonl(evidence, [bad])
            stale_old_value = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[evidence],
                output_dir=root / "bad",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(stale_old_value["complete_count"], 1)
            self.assertEqual(stale_old_value["gap_count"], 1)
            stale_gap = json.loads((root / "bad" / "gaps.jsonl").read_text())
            self.assertEqual(stale_gap["reason_code"], "conflicting_manual_evidence")

            bad["expected_old_value"] = "2024-01-01"
            bad["target_sha256"] = SHA_B
            _write_jsonl(evidence, [bad])
            stale_target = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[evidence],
                output_dir=root / "bad-target",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(stale_target["complete_count"], 1)
            self.assertEqual(stale_target["gap_count"], 1)

            protected = json.loads(evidence.read_text().splitlines()[0])
            protected.update(
                target_sha256=targets[0]["target_sha256"],
                field="target_sha256",
                expected_old_value=targets[0]["target_sha256"],
                new_value=SHA_B,
                reviewed_at=RECORDED_AT,
            )
            _write_jsonl(evidence, [protected])
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "protected identity"):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[evidence],
                    output_dir=root / "protected",
                    recorded_at=RECORDED_AT,
                )

            bad["expected_old_value"] = "2024-01-01"
            bad["target_sha256"] = targets[0]["target_sha256"]
            bad["reviewed_at"] = RECORDED_AT
            bad["new_value"] = "2024-02-30"
            _write_jsonl(evidence, [bad])
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "local_date"):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[evidence],
                    output_dir=root / "bad-new-value",
                    recorded_at=RECORDED_AT,
                )
            bad["new_value"] = "2024-01-02"
            bad["reviewed_at"] = "not-a-timestamp"
            _write_jsonl(evidence, [bad])
            with self.assertRaises(HistoricalBatchPipelineError):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[evidence],
                    output_dir=root / "bad-time",
                    recorded_at=RECORDED_AT,
                )

    def test_conflicting_manual_evidence_becomes_target_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            fragments = root / "fragments.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.date_row(targets[0], local_date="2024-01-01"),
                    self.date_row(targets[1], local_date="2025-01-01"),
                ],
            )
            base = {
                "target_id": 1,
                "target_sha256": targets[0]["target_sha256"],
                "field": "local_date",
                "expected_old_value": "2024-01-01",
                "source_url": "https://authority.test/result",
                "source_authority": "official",
                "reason": "official correction",
                "reviewed_by": "operator",
                "reviewed_at": RECORDED_AT,
            }
            evidence = root / "evidence.jsonl"
            _write_jsonl(
                evidence,
                [
                    {**base, "new_value": "2024-01-02"},
                    {**base, "new_value": "2024-01-03"},
                ],
            )
            result = merge_historical_race_fragments(
                mode="date",
                selection_path=selection,
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[evidence],
                output_dir=root / "out",
                recorded_at=RECORDED_AT,
            )
            self.assertEqual(result["complete_count"], 1)
            self.assertEqual(result["gap_count"], 1)
            gap = json.loads((root / "out" / "gaps.jsonl").read_text())
            self.assertEqual(gap["reason_code"], "conflicting_manual_evidence")

    def test_atomic_publish_leaves_no_final_directory_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            fragments = root / "fragments.jsonl"
            _write_jsonl(fragments, [self.date_row(targets[0], local_date="2024-01-01")])
            output = root / "published"
            with self.assertRaises(HistoricalBatchPipelineError):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[],
                    output_dir=output,
                    recorded_at=RECORDED_AT,
                )
            self.assertFalse(output.exists())

    def test_atomic_publish_removes_final_directory_when_parent_fsync_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, targets = self.make(root)
            fragments = root / "fragments.jsonl"
            _write_jsonl(
                fragments,
                [
                    self.date_row(targets[0], local_date="2024-01-01"),
                    self.date_row(targets[1], local_date="2025-01-01"),
                ],
            )
            output = root / "published"
            with patch(
                "stable.services.historical_batch_pipeline._fsync_tree"
            ), patch(
                "stable.services.historical_batch_pipeline.os.fsync",
                side_effect=OSError("injected parent fsync failure"),
            ), self.assertRaises(OSError):
                merge_historical_race_fragments(
                    mode="date",
                    selection_path=selection,
                    fragment_paths=[fragments],
                    gap_paths=[],
                    evidence_paths=[],
                    output_dir=output,
                    recorded_at=RECORDED_AT,
                )
            self.assertFalse(output.exists())


class HistoricalBatchStageVerifierTests(TestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="verify-series",
            country_region=RacingRegion.JAPAN,
            canonical_name_original="Verify Stakes",
            chinese_name="验收锦标",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        self.event = RaceEvent.objects.create(
            year=2024,
            slug="verify-stakes-2024",
            race_series=self.series,
            original_name="Verify Stakes",
            chinese_name="验收锦标",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface="turf",
            distance_text="1600m",
            local_date=date(2024, 1, 1),
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.DRAFT,
            data_quality_status=RaceEventDataQuality.COMPLETE,
            source_refs={
                "detail_discovery": {
                    "approved_detail_sources": [{"url": "https://example.test/1"}]
                }
            },
        )
        self.target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2024,
            country_region=RacingRegion.JAPAN,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            original_name="Verify Stakes",
            chinese_name="验收锦标",
            local_date=date(2024, 1, 1),
            event=self.event,
            module_statuses={"runners": "complete", "results": "complete"},
            field_provenance={"local_date": {"source_url": "https://example.test/1"}},
            source_refs={
                "detail_discovery": {
                    "approved_detail_sources": [{"url": "https://example.test/1"}]
                }
            },
            artifact_sha256=SHA_A,
        )
        RaceEventRunner.objects.create(
            event=self.event,
            sort_order=1,
            horse_number="1",
            horse_name="Runner One",
            source_refs={"primary": "https://example.test/1"},
        )
        RaceEventResult.objects.create(
            event=self.event,
            finish_position=1,
            horse_number="2",
            horse_name="Winner",
            source_refs={"primary": "https://example.test/1"},
        )
        current_target_sha = target_identity(self.target)["target_sha256"]
        for module in (RaceEventModule.RUNNERS, RaceEventModule.RESULTS):
            RaceEventDataCandidate.objects.create(
                event=self.event,
                module=module,
                source_name="fixture",
                source_url="https://example.test/1",
                status=RaceEventCandidateStatus.APPLIED,
                confidence=100,
                candidate_payload={"items": [{}]},
                raw_payload={
                    "historical_target_id": self.target.pk,
                    "target_sha256": current_target_sha,
                    "inventory_artifact_sha256": SHA_A,
                },
            )

    def _write_artifact(
        self,
        root: Path,
        *,
        runner_count: int = 1,
        result_count: int = 1,
        as_gap: bool = False,
    ) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        self.target.refresh_from_db()
        current_target_sha = target_identity(self.target)["target_sha256"]
        selection = root / "selection.json"
        _write_json(
            selection,
            {
                "schema_version": "1.0",
                "inventory_manifest_sha256": SHA_A,
                "targets": [
                    {
                        "target_id": self.target.pk,
                        "target_sha256": current_target_sha,
                        "inventory_artifact_sha256": SHA_A,
                        "series_key": self.series.key,
                        "year": 2024,
                        "country_region": RacingRegion.JAPAN,
                    }
                ],
            },
        )
        complete = root / "complete.jsonl"
        complete_rows = [
            {
                "target_id": self.target.pk,
                "target_sha256": current_target_sha,
                "inventory_artifact_sha256": SHA_A,
                "local_date": "2024-01-01",
                "source_url": "https://example.test/1",
                "source_name": "fixture",
                "modules": {
                    "runners": {"is_complete": True, "items": [{}] * runner_count},
                    "results": {"is_complete": True, "items": [{}] * result_count},
                },
            }
        ]
        _write_jsonl(complete, [] if as_gap else complete_rows)
        gaps = root / "gaps.jsonl"
        _write_jsonl(
            gaps,
            [
                {
                    "target_id": self.target.pk,
                    "target_sha256": current_target_sha,
                    "reason_code": "source_unavailable",
                    "recorded_at": RECORDED_AT,
                    "evidence_identity": {"path": "ledger.jsonl", "sha256": SHA_B},
                }
            ]
            if as_gap
            else [],
        )
        manifest = root / "manifest.json"
        _write_json(
            manifest,
            {
                "schema_version": "1.0",
                "selection": {"path": selection.name, "sha256": hashlib.sha256(selection.read_bytes()).hexdigest()},
                "complete": {"path": complete.name, "sha256": hashlib.sha256(complete.read_bytes()).hexdigest()},
                "gaps": {"path": gaps.name, "sha256": hashlib.sha256(gaps.read_bytes()).hexdigest()},
            },
        )
        return root

    def test_date_detail_source_and_final_verification_succeed_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_artifact(Path(tmp))
            before = self.target.updated_at
            for stage in ("date", "detail-source", "final"):
                with self.subTest(stage=stage):
                    output = root / f"report-{stage}.json"
                    call_command(
                        "verify_historical_race_batch_stage",
                        stage=stage,
                        artifact_dir=str(root),
                        output=str(output),
                    )
                    report = json.loads(output.read_text())
                    self.assertEqual(report["error_count"], 0)
                    self.assertEqual(report["published_count"], 0)
            self.target.refresh_from_db()
            self.assertEqual(self.target.updated_at, before)

    def test_verifier_reports_date_source_count_status_and_visibility_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_artifact(Path(tmp))

            def assert_rejected(label: str) -> None:
                with self.subTest(label=label), self.assertRaises(CommandError):
                    call_command(
                        "verify_historical_race_batch_stage",
                        stage="final",
                        artifact_dir=str(root),
                        output=str(root / f"report-{label}.json"),
                    )

            RaceEvent.objects.filter(pk=self.event.pk).update(local_date=date(2024, 1, 2))
            assert_rejected("date")
            RaceEvent.objects.filter(pk=self.event.pk).update(local_date=date(2024, 1, 1))

            RaceEvent.objects.filter(pk=self.event.pk).update(source_refs={})
            assert_rejected("source")
            RaceEvent.objects.filter(pk=self.event.pk).update(
                source_refs={
                    "detail_discovery": {
                        "approved_detail_sources": [{"url": "https://example.test/1"}]
                    }
                }
            )

            RaceEventRunner.objects.filter(event=self.event).delete()
            assert_rejected("runner-count")
            RaceEventRunner.objects.create(
                event=self.event,
                sort_order=1,
                horse_number="1",
                horse_name="Runner One",
                source_refs={"primary": "https://example.test/1"},
            )

            HistoricalRaceEventTarget.objects.filter(pk=self.target.pk).update(
                resolution_status=HistoricalRaceResolutionStatus.PENDING
            )
            assert_rejected("status")
            HistoricalRaceEventTarget.objects.filter(pk=self.target.pk).update(
                resolution_status=HistoricalRaceResolutionStatus.IMPORTED
            )

            RaceEvent.objects.filter(pk=self.event.pk).update(
                visibility_status=RaceEventVisibility.PUBLISHED
            )
            assert_rejected("visibility")

    def test_verifier_rejects_published_gap_and_uses_latest_applied_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gap_artifact = self._write_artifact(root / "gap", as_gap=True)
            RaceEvent.objects.filter(pk=self.event.pk).update(
                visibility_status=RaceEventVisibility.PUBLISHED
            )
            with self.assertRaises(CommandError):
                call_command(
                    "verify_historical_race_batch_stage",
                    stage="final",
                    artifact_dir=str(gap_artifact),
                    output=str(gap_artifact / "report.json"),
                )

    def test_verifier_rejects_imported_or_identity_drifted_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._write_artifact(root / "gap", as_gap=True)
            report = verify_historical_batch_stage(stage="final", artifact_dir=artifact)
            self.assertIn("gap_target_already_imported", {row["code"] for row in report["errors"]})

            HistoricalRaceEventTarget.objects.filter(pk=self.target.pk).update(
                resolution_status=HistoricalRaceResolutionStatus.PENDING
            )
            gaps = artifact / "gaps.jsonl"
            row = json.loads(gaps.read_text())
            row["target_sha256"] = SHA_B
            _write_jsonl(gaps, [row])
            manifest = json.loads((artifact / "manifest.json").read_text())
            manifest["gaps"]["sha256"] = hashlib.sha256(gaps.read_bytes()).hexdigest()
            _write_json(artifact / "manifest.json", manifest)
            report = verify_historical_batch_stage(stage="final", artifact_dir=artifact)
            self.assertIn(
                "gap_selection_identity_mismatch",
                {error["code"] for error in report["errors"]},
            )

    def test_verifier_rejects_symlinked_manifest_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_artifact(Path(tmp))
            complete = root / "complete.jsonl"
            real = root / "complete-real.jsonl"
            complete.rename(real)
            complete.symlink_to(real.name)
            with self.assertRaisesMessage(HistoricalBatchPipelineError, "symlink"):
                verify_historical_batch_stage(stage="final", artifact_dir=root)
            RaceEvent.objects.filter(pk=self.event.pk).update(
                visibility_status=RaceEventVisibility.DRAFT
            )

            complete_artifact = self._write_artifact(root / "complete")
            existing = RaceEventDataCandidate.objects.filter(
                event=self.event,
                module=RaceEventModule.RESULTS,
                status=RaceEventCandidateStatus.APPLIED,
            ).first()
            existing.source_url = "https://old-invalid.test/result"
            existing.raw_payload = {}
            existing.save(update_fields=["source_url", "raw_payload", "updated_at"])
            RaceEventDataCandidate.objects.create(
                event=self.event,
                module=RaceEventModule.RESULTS,
                source_name="duplicate",
                source_url="https://example.test/1",
                status=RaceEventCandidateStatus.APPLIED,
                confidence=100,
                candidate_payload=existing.candidate_payload,
                raw_payload={
                    "historical_target_id": self.target.pk,
                    "target_sha256": target_identity(self.target)["target_sha256"],
                    "inventory_artifact_sha256": SHA_A,
                },
            )
            report = verify_historical_batch_stage(
                stage="final",
                artifact_dir=complete_artifact,
            )
            self.assertEqual(report["error_count"], 0)

    def test_verifier_never_creates_historical_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_artifact(Path(tmp))
            call_command(
                "verify_historical_race_batch_stage",
                stage="final",
                artifact_dir=str(root),
                output=str(root / "report.json"),
            )
        self.assertEqual(HistoricalBatchRun.objects.count(), 0)

    def test_report_publish_does_not_overwrite_a_concurrent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "report.json"
            real_link = os.link

            def competing_publish(source, target):
                Path(target).write_text("existing\n", encoding="utf-8")
                return real_link(source, target)

            with patch(
                "stable.services.historical_batch_verifier.os.link",
                side_effect=competing_publish,
            ), self.assertRaisesMessage(HistoricalBatchPipelineError, "already exists"):
                write_verification_report(destination, {"error_count": 0})
            self.assertEqual(destination.read_text(encoding="utf-8"), "existing\n")

    def test_postgresql_read_only_transaction_rejects_injected_write(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_artifact(Path(tmp))
            original_name = self.event.original_name

            def injected_write(_row):
                RaceEvent.objects.filter(pk=self.event.pk).update(original_name="forbidden")
                return "https://example.test/1"

            with patch(
                "stable.services.historical_batch_verifier._candidate_source_url",
                side_effect=injected_write,
            ), self.assertRaises(DatabaseError):
                verify_historical_batch_stage(stage="final", artifact_dir=root)
            self.event.refresh_from_db()
            self.assertEqual(self.event.original_name, original_name)


class HistoricalBatchTrackedToolTests(SimpleTestCase):
    def test_merger_cli_bootstraps_project_settings_outside_manage_py(self):
        project_root = Path(__file__).resolve().parents[2]
        environment = os.environ.copy()
        environment.pop("DJANGO_SETTINGS_MODULE", None)
        result = subprocess.run(
            [
                sys.executable,
                str(project_root / "runtime/tools/merge_historical_race_batch_fragments.py"),
                "--help",
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--selection", result.stdout)


@unittest.skipUnless(
    os.environ.get("RUN_HISTORICAL_PIPELINE_PERF") == "1",
    "set RUN_HISTORICAL_PIPELINE_PERF=1 for the 1250-target contract",
)
class HistoricalBatchPipelinePerformanceTests(TestCase, HistoricalBatchPlanFixture):
    def test_plan_and_detail_merge_stay_within_time_and_memory_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _descriptor_path, descriptor = self.make(root, count=1250)
            selection = json.loads(Path(descriptor["selection"]["path"]).read_text())
            descriptor["resource_limits"].pop("request_budget")
            descriptor["shards"] = []
            for shard_index in range(5):
                targets = selection["targets"][shard_index * 250 : (shard_index + 1) * 250]
                events = root / "bootstrap" / f"events-{shard_index:02d}.csv"
                _write_events(events, targets)
                descriptor["shards"].append(
                    {
                        "id": f"hong-kong-{shard_index:02d}",
                        "country_region": RacingRegion.HONG_KONG,
                        "target_ids": [target["target_id"] for target in targets],
                        "request_budget": 250,
                        "recipes": [
                            {
                                "tool": "prepare_hkjc_race_detail_candidates.py",
                                "inputs": {"events_csv": [str(events)]},
                                "outputs": {"output_dir": "outputs/hkjc"},
                                "options": {"allow_network": True, "fail_fast": True},
                            }
                        ],
                    }
                )
            descriptor_path = root / "descriptor-perf.json"
            _write_json(descriptor_path, descriptor)
            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            started = time.monotonic()
            build_historical_batch_shard_plan(
                descriptor_path=descriptor_path,
                shard_id="hong-kong-00",
                output_dir=root / "plan-output",
            )
            plan_seconds = time.monotonic() - started
            rss_after_plan = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            self.assertLessEqual(plan_seconds, 30)
            self.assertLessEqual((rss_after_plan - rss_before) * 1024, 256 * 1024 * 1024)

            cache_root = root / "detail-cache"
            cache_root.mkdir()
            cache_files = {}
            candidates = []
            for target in selection["targets"]:
                source_url = f"https://example.test/{target['target_id']}"
                source = cache_root / f"{target['target_id']}.html"
                source.write_bytes(b"body")
                cache_identity = {
                    "source_url": source_url,
                    "path": source.name,
                    "size": 4,
                    "sha256": hashlib.sha256(b"body").hexdigest(),
                }
                cache_files[source.name] = cache_identity
                candidates.append(
                    {
                        "target_id": target["target_id"],
                        "target_sha256": target["target_sha256"],
                        "inventory_artifact_sha256": SHA_A,
                        "source_name": "fixture",
                        "source_url": source_url,
                        "modules": {
                            "runners": {
                                "is_complete": True,
                                "source_cache_identity": cache_identity,
                                "items": [
                                    {"horse_number": str(item), "horse_name": f"Runner {item}"}
                                    for item in range(1, 21)
                                ],
                            },
                            "results": {
                                "is_complete": True,
                                "source_cache_identity": cache_identity,
                                "items": [
                                    {"finish_position": item, "horse_name": f"Runner {item}"}
                                    for item in range(1, 21)
                                ],
                            },
                        },
                    }
                )
            cache_manifest = cache_root / "source_cache_manifest.json"
            _write_json(cache_manifest, {"schema_version": "1.0", "files": cache_files})
            fragments = root / "detail-fragments.jsonl"
            _write_jsonl(fragments, candidates)
            rss_before_merge = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            started = time.monotonic()
            merge_historical_race_fragments(
                mode="detail",
                selection_path=descriptor["selection"]["path"],
                fragment_paths=[fragments],
                gap_paths=[],
                evidence_paths=[],
                source_cache_manifest_paths=[cache_manifest],
                output_dir=root / "merge-output",
                recorded_at=RECORDED_AT,
            )
            merge_seconds = time.monotonic() - started
            rss_after_merge = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            self.assertLessEqual(merge_seconds, 30)
            self.assertLessEqual(
                (rss_after_merge - rss_before_merge) * 1024,
                256 * 1024 * 1024,
            )

    def test_verifier_uses_at_most_twenty_queries_for_1250_targets(self):
        series = RaceSeries.objects.bulk_create(
            [
                RaceSeries(
                    key=f"perf-series-{index}",
                    country_region=RacingRegion.JAPAN,
                    canonical_name_original=f"Performance {index}",
                    chinese_name=f"性能{index}",
                    review_status=RaceSeriesReviewStatus.APPROVED,
                )
                for index in range(1250)
            ]
        )
        events = RaceEvent.objects.bulk_create(
            [
                RaceEvent(
                    year=2024,
                    slug=f"perf-event-{index}",
                    race_series=item,
                    series_key=item.key,
                    original_name=item.canonical_name_original,
                    chinese_name=item.chinese_name,
                    country_region=RacingRegion.JAPAN,
                    racecourse="Tokyo",
                    grade_text="G1",
                    surface="turf",
                    distance_text="1600m",
                    local_date=date(2024, 1, 1),
                    status=RaceEventStatus.FINISHED,
                    visibility_status=RaceEventVisibility.DRAFT,
                    data_quality_status=RaceEventDataQuality.COMPLETE,
                    source_refs={
                        "detail_discovery": {
                            "approved_detail_sources": [
                                {"url": f"https://example.test/{index}"}
                            ]
                        }
                    },
                )
                for index, item in enumerate(series)
            ]
        )
        targets = HistoricalRaceEventTarget.objects.bulk_create(
            [
                HistoricalRaceEventTarget(
                    race_series=series[index],
                    year=2024,
                    country_region=RacingRegion.JAPAN,
                    resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
                    original_name=series[index].canonical_name_original,
                    chinese_name=series[index].chinese_name,
                    local_date=date(2024, 1, 1),
                    event=events[index],
                    module_statuses={"runners": "complete", "results": "complete"},
                    source_refs={
                        "detail_discovery": {
                            "approved_detail_sources": [
                                {"url": f"https://example.test/{index}"}
                            ]
                        }
                    },
                    artifact_sha256=SHA_A,
                )
                for index in range(1250)
            ]
        )
        RaceEventRunner.objects.bulk_create(
            [
                RaceEventRunner(
                    event=event,
                    sort_order=1,
                    horse_number="1",
                    horse_name="Runner",
                )
                for event in events
            ]
        )
        RaceEventResult.objects.bulk_create(
            [
                RaceEventResult(
                    event=event,
                    finish_position=1,
                    horse_number="1",
                    horse_name="Runner",
                )
                for event in events
            ]
        )
        selection_rows = []
        complete_rows = []
        candidates = []
        for index, target in enumerate(targets):
            target_sha = hashlib.sha256(f"perf-target-{target.pk}".encode()).hexdigest()
            source_url = f"https://example.test/{index}"
            selection_rows.append(
                {
                    "target_id": target.pk,
                    "target_sha256": target_sha,
                    "inventory_artifact_sha256": SHA_A,
                    "series_key": series[index].key,
                    "year": 2024,
                    "country_region": RacingRegion.JAPAN,
                }
            )
            complete_rows.append(
                {
                    "target_id": target.pk,
                    "target_sha256": target_sha,
                    "inventory_artifact_sha256": SHA_A,
                    "local_date": "2024-01-01",
                    "source_name": "fixture",
                    "source_url": source_url,
                    "modules": {
                        "runners": {"is_complete": True, "items": [{}]},
                        "results": {"is_complete": True, "items": [{}]},
                    },
                }
            )
            for module in (RaceEventModule.RUNNERS, RaceEventModule.RESULTS):
                candidates.append(
                    RaceEventDataCandidate(
                        event=events[index],
                        module=module,
                        source_name="fixture",
                        source_url=source_url,
                        status=RaceEventCandidateStatus.APPLIED,
                        confidence=100,
                        candidate_payload={"items": [{}]},
                        raw_payload={
                            "historical_target_id": target.pk,
                            "target_sha256": target_sha,
                            "inventory_artifact_sha256": SHA_A,
                        },
                    )
                )
        RaceEventDataCandidate.objects.bulk_create(candidates)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection_path = root / "selection.json"
            _write_json(
                selection_path,
                {
                    "schema_version": "1.0",
                    "inventory_manifest_sha256": SHA_A,
                    "targets": selection_rows,
                },
            )
            complete_path = root / "complete.jsonl"
            _write_jsonl(complete_path, complete_rows)
            gaps_path = root / "gaps.jsonl"
            _write_jsonl(gaps_path, [])
            _write_json(
                root / "manifest.json",
                {
                    "schema_version": "1.0",
                    "selection": {
                        "path": selection_path.name,
                        "sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
                    },
                    "complete": {
                        "path": complete_path.name,
                        "sha256": hashlib.sha256(complete_path.read_bytes()).hexdigest(),
                    },
                    "gaps": {
                        "path": gaps_path.name,
                        "sha256": hashlib.sha256(gaps_path.read_bytes()).hexdigest(),
                    },
                },
            )
            with CaptureQueriesContext(connection) as queries:
                report = verify_historical_batch_stage(stage="final", artifact_dir=root)
            self.assertEqual(report["error_count"], 0)
            self.assertLessEqual(len(queries), 20)
