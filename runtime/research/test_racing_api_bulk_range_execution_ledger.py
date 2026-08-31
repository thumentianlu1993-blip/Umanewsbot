#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("racing_api_bulk_range_execution_ledger.py")
POSTPROCESS_SCRIPT = Path(__file__).with_name(
    "audit_bulk_stable_id_postprocess_readiness.py"
)


def load_tool():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("bulk_range_execution_ledger", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_postprocess_tool():
    spec = importlib.util.spec_from_file_location(
        "bulk_stable_postprocess_readiness", POSTPROCESS_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RacingApiBulkRangeExecutionLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()
        cls.plan_module = sys.modules["prepare_racing_api_bulk_range_batch_plan"]
        cls.runner_module = sys.modules["racing_api_bulk_range_batch_export"]
        cls.horse_module = sys.modules["racing_api_horse_export"]
        cls.postprocess_module = load_postprocess_tool()
        cls.stable_builder_module = sys.modules[
            "build_bulk_target_runner_stable_id_ledger"
        ]

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

    def partition(self) -> dict:
        return {
            "schema_version": "racing-api-bulk-region-year-partition.v1",
            "country_region": "france",
            "year": 2005,
            "target_count": 1,
            "target_keys_sha256": hashlib.sha256(b"france:2005:arc\n").hexdigest(),
            "evidence_state_counts": {"source_route_only": 1},
            "ranges": [
                {
                    "start_date": "2005-01-01",
                    "end_date": "2005-12-31",
                    "max_pages_protocol_ceiling": 10,
                }
            ],
            "range_count": 1,
            "protocol_request_ceiling": 10,
            "actual_request_count": None,
            "execution_ready": False,
        }

    def race(self) -> dict:
        return {
            "race_id": "rac_arc_2005",
            "date": "2005-10-02",
            "off_dt": "2005-10-02T16:05:00+02:00",
            "region": "FR",
            "course": "ParisLongchamp (FR)",
            "course_id": "crs_parislongchamp",
            "race_name": "Qatar Prix de l'Arc de Triomphe",
            "type": "Flat",
            "class": "Group 1",
            "pattern": "G1",
            "dist": "1m4f",
            "surface": "Turf",
            "runners": [
                {"horse_id": "hrs_1", "horse": "Winner (FR)", "position": "1"},
                {"horse_id": "hrs_2", "horse": "Second (IRE)", "position": "2"},
            ],
        }

    def fingerprint(self, root: Path) -> tuple[Path, str, dict]:
        payload = {
            "fingerprint_generated_at": "2026-08-29T15:33:04+08:00",
            "full_openapi_sha256": self.horse_module.EXPECTED_OPENAPI_FULL_SHA256,
            "openapi_version": self.horse_module.EXPECTED_OPENAPI_VERSION,
            "selected_contract": {
                "paths": list(self.horse_module.EXPECTED_OPENAPI_SELECTED_PATHS),
                "sha256": self.horse_module.EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
            },
            "selected_schema": {
                "names": list(self.horse_module.EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES),
                "sha256": self.horse_module.EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
            },
            "source_url": self.horse_module.OPENAPI_SOURCE_URL,
        }
        path = root / "openapi-fingerprint.json"
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return path, digest, self.horse_module.load_openapi_fingerprint(path, digest)

    def make_plan(self, root: Path) -> tuple[Path, dict]:
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
        plan = root / "plan"
        with patch.object(
            self.plan_module,
            "load_readiness_artifact",
            return_value=([self.partition()], [self.classified()], readiness),
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
                output_dir=plan,
            )
        return plan, summary

    def proof(
        self,
        path: Path,
        *,
        proposal_sha: str,
        now: datetime,
        credential_alias: str,
        scope_id: str,
    ) -> str:
        payload = {
            "schema_version": "racing-api-exclusive-account-proof.v1",
            "status": "approved",
            "host": "api.theracingapi.com",
            "credential_alias": credential_alias,
            "scope_id": scope_id,
            "scope_manifest_sha256": proposal_sha,
            "observed_at": now.isoformat(),
            "valid_until": (now + timedelta(minutes=10)).isoformat(),
            "checks": {
                "race_live_scheduler_enabled": False,
                "race_live_runner_active": 0,
                "race_data_sync_network_enabled": False,
                "race_data_sync_active_claims": 0,
                "other_backfill_processes": 0,
                "manual_caller_window_reserved": True,
            },
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def prepare_approval_and_claim(self, root: Path, now: datetime):
        plan, summary = self.make_plan(root)
        fingerprint_path, fingerprint_sha, fingerprint_identity = self.fingerprint(root)
        ledger_path = root / "execution-ledger.json"
        batch_output = root / "batch-output"
        budget_root = root / "budget"
        credential_alias = "racing-api-primary"
        scope_id = "bulk-range-b1"
        proposal_root = root / "proposal"
        proposal = self.module.prepare_next_batch_g3_proposal(
            plan_root=plan,
            expected_plan_manifest_sha256=summary["manifest_sha256"],
            expected_batch_plan_sha256=summary["plan_sha256"],
            execution_ledger_path=ledger_path,
            batch_output_dir=batch_output,
            account_budget_root=budget_root,
            credential_alias=credential_alias,
            account_scope_id=scope_id,
            openapi_fingerprint_path=fingerprint_path,
            approved_openapi_fingerprint_sha256=fingerprint_sha,
            output_dir=proposal_root,
            now=now,
        )
        approval_root = root / "approval"
        approval = self.module.publish_batch_g3_approval(
            proposal_root=proposal_root,
            approved_proposal_manifest_sha256=proposal["proposal_manifest_sha256"],
            approved_by="goal-owner",
            decision_source_reference="explicit-test-approval",
            output_dir=approval_root,
            now=now,
        )
        proof_path = root / "exclusive-proof.json"
        proof_sha = self.proof(
            proof_path,
            proposal_sha=proposal["proposal_manifest_sha256"],
            now=now,
            credential_alias=credential_alias,
            scope_id=scope_id,
        )
        claim = self.module.claim_batch_execution(
            plan_root=plan,
            expected_plan_manifest_sha256=summary["manifest_sha256"],
            expected_batch_plan_sha256=summary["plan_sha256"],
            execution_ledger_path=ledger_path,
            approval_root=approval_root,
            approved_g3_manifest_sha256=approval["approval_manifest_sha256"],
            exclusive_proof_path=proof_path,
            exclusive_proof_sha256=proof_sha,
            batch_output_dir=batch_output,
            account_budget_root=budget_root,
            credential_alias=credential_alias,
            account_scope_id=scope_id,
            openapi_fingerprint_path=fingerprint_path,
            approved_openapi_fingerprint_sha256=fingerprint_sha,
            now=now + timedelta(seconds=1),
        )
        return {
            "plan": plan,
            "summary": summary,
            "fingerprint_identity": fingerprint_identity,
            "fingerprint_path": fingerprint_path,
            "fingerprint_sha": fingerprint_sha,
            "ledger_path": ledger_path,
            "batch_output": batch_output,
            "budget_root": budget_root,
            "credential_alias": credential_alias,
            "scope_id": scope_id,
            "approval_root": approval_root,
            "approval": approval,
            "claim": claim,
        }

    def prepare_approval_without_claim(self, root: Path, now: datetime):
        plan, summary = self.make_plan(root)
        fingerprint_path, fingerprint_sha, fingerprint_identity = self.fingerprint(root)
        ledger_path = root / "execution-ledger.json"
        batch_output = root / "batch-output"
        budget_root = root / "budget"
        credential_alias = "racing-api-primary"
        scope_id = "bulk-range-b1"
        proposal_root = root / "proposal"
        proposal = self.module.prepare_next_batch_g3_proposal(
            plan_root=plan,
            expected_plan_manifest_sha256=summary["manifest_sha256"],
            expected_batch_plan_sha256=summary["plan_sha256"],
            execution_ledger_path=ledger_path,
            batch_output_dir=batch_output,
            account_budget_root=budget_root,
            credential_alias=credential_alias,
            account_scope_id=scope_id,
            openapi_fingerprint_path=fingerprint_path,
            approved_openapi_fingerprint_sha256=fingerprint_sha,
            output_dir=proposal_root,
            now=now,
        )
        approval_root = root / "approval"
        approval = self.module.publish_batch_g3_approval(
            proposal_root=proposal_root,
            approved_proposal_manifest_sha256=proposal["proposal_manifest_sha256"],
            approved_by="goal-owner",
            decision_source_reference="explicit-test-approval",
            output_dir=approval_root,
            now=now,
        )
        return {
            "plan": plan,
            "summary": summary,
            "fingerprint_identity": fingerprint_identity,
            "fingerprint_path": fingerprint_path,
            "fingerprint_sha": fingerprint_sha,
            "ledger_path": ledger_path,
            "batch_output": batch_output,
            "budget_root": budget_root,
            "credential_alias": credential_alias,
            "scope_id": scope_id,
            "proposal": proposal,
            "approval_root": approval_root,
            "approval": approval,
        }

    def test_preflight_validates_bulk_scope_without_mutation(self):
        now = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.prepare_approval_without_claim(root, now)
            lock_path = state["ledger_path"].with_suffix(".json.lock")
            ledger_before = state["ledger_path"].read_bytes()
            lock_before = lock_path.read_bytes()

            result = self.module.preflight_next_batch_execution(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                approval_root=state["approval_root"],
                approved_g3_manifest_sha256=state["approval"]["approval_manifest_sha256"],
                batch_output_dir=state["batch_output"],
                account_budget_root=state["budget_root"],
                credential_alias=state["credential_alias"],
                account_scope_id=state["scope_id"],
                openapi_fingerprint_path=state["fingerprint_path"],
                approved_openapi_fingerprint_sha256=state["fingerprint_sha"],
                now=now + timedelta(seconds=1),
            )

            self.assertEqual(result["status"], "ready_for_fresh_exclusive_proof")
            self.assertEqual(result["next_batch"]["target_count"], 1)
            self.assertEqual(result["next_batch"]["request_ceiling"], 10)
            self.assertEqual(result["next_batch"]["endpoint_kinds"], ["bulk_results"])
            self.assertFalse(result["proof_loaded"])
            self.assertFalse(result["ledger_mutated"])
            self.assertEqual(state["ledger_path"].read_bytes(), ledger_before)
            self.assertEqual(lock_path.read_bytes(), lock_before)
            self.assertFalse(state["batch_output"].exists())
            self.assertFalse(state["budget_root"].exists())

    def test_preflight_rejects_bulk_path_drift_without_mutation(self):
        now = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.prepare_approval_without_claim(root, now)
            ledger_before = state["ledger_path"].read_bytes()

            with self.assertRaisesRegex(
                self.module.BulkRangeExecutionError,
                "approval does not bind next scope",
            ):
                self.module.preflight_next_batch_execution(
                    plan_root=state["plan"],
                    expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                    expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                    execution_ledger_path=state["ledger_path"],
                    approval_root=state["approval_root"],
                    approved_g3_manifest_sha256=state["approval"]["approval_manifest_sha256"],
                    batch_output_dir=root / "different-output",
                    account_budget_root=state["budget_root"],
                    credential_alias=state["credential_alias"],
                    account_scope_id=state["scope_id"],
                    openapi_fingerprint_path=state["fingerprint_path"],
                    approved_openapi_fingerprint_sha256=state["fingerprint_sha"],
                    now=now + timedelta(seconds=1),
                )

            self.assertEqual(state["ledger_path"].read_bytes(), ledger_before)
            self.assertFalse((root / "different-output").exists())
            self.assertFalse(state["budget_root"].exists())

    def test_full_g3_claim_run_and_complete_sequence(self):
        now = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)

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
            state = self.prepare_approval_and_claim(root, now)
            manifest = self.runner_module.run_bulk_range_batch_artifact(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=state["batch_output"],
                client=FakeClient(self.race()),
                openapi_fingerprint_identity=state["fingerprint_identity"],
            )
            manifest_sha = hashlib.sha256(
                (state["batch_output"] / "batch-manifest.json").read_bytes()
            ).hexdigest()
            completed = self.module.mark_batch_complete(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                claim_token=state["claim"]["claim_token"],
                batch_output_dir=state["batch_output"],
                expected_batch_manifest_sha256=manifest_sha,
                request_count=manifest["request_count"],
                now=now + timedelta(minutes=1),
            )
            ledger = json.loads(state["ledger_path"].read_text(encoding="utf-8"))
            self.assertEqual(completed["ordinal"], 1)
            self.assertEqual(completed["request_count"], 1)
            self.assertEqual(len(ledger["completed"]), 1)
            self.assertIsNone(ledger["active"])

    def test_completed_bulk_requires_exact_stable_postprocess_before_global_merge(self):
        now = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)

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
            state = self.prepare_approval_and_claim(root, now)
            manifest = self.runner_module.run_bulk_range_batch_artifact(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=state["batch_output"],
                client=FakeClient(self.race()),
                openapi_fingerprint_identity=state["fingerprint_identity"],
            )
            run_manifest_sha = hashlib.sha256(
                (state["batch_output"] / "batch-manifest.json").read_bytes()
            ).hexdigest()
            self.module.mark_batch_complete(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                claim_token=state["claim"]["claim_token"],
                batch_output_dir=state["batch_output"],
                expected_batch_manifest_sha256=run_manifest_sha,
                request_count=manifest["request_count"],
                now=now + timedelta(minutes=1),
            )
            stable_parent = root / "bulk-stable-ledgers"
            before = self.postprocess_module.audit_bulk_stable_postprocess_readiness(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                stable_ledger_parent=stable_parent,
            )
            self.assertEqual(before["status"], "stable_postprocess_required")
            self.assertEqual(before["counts"]["missing_stable_ledgers"], 1)
            self.assertEqual(
                before["next_postprocess"]["batch_id"],
                "0001-france-2005-2005",
            )
            stable_output = stable_parent / "0001-france-2005-2005"
            self.stable_builder_module.build_bulk_stable_id_seed_ledger(
                bulk_run_dir=state["batch_output"],
                approved_bulk_run_manifest_sha256=run_manifest_sha,
                output_dir=stable_output,
            )
            after = self.postprocess_module.audit_bulk_stable_postprocess_readiness(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                stable_ledger_parent=stable_parent,
            )
            self.assertEqual(after["status"], "ready_for_global_stable_merge")
            self.assertEqual(after["counts"]["validated_stable_ledgers"], 1)
            self.assertEqual(len(after["global_merge_inputs"]), 1)
            (stable_parent / "unregistered-batch").mkdir()
            with self.assertRaisesRegex(
                self.postprocess_module.BulkStablePostprocessReadinessError,
                "outside completed bulk batches",
            ):
                self.postprocess_module.audit_bulk_stable_postprocess_readiness(
                    plan_root=state["plan"],
                    expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                    expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                    execution_ledger_path=state["ledger_path"],
                    stable_ledger_parent=stable_parent,
                )

    def test_safe_stop_is_recorded_and_blocks_implicit_retry(self):
        now = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.prepare_approval_and_claim(root, now)
            active = self.module.mark_batch_safe_stopped(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                claim_token=state["claim"]["claim_token"],
                request_count=3,
                error_type="transport",
                error_message="simulated",
                now=now + timedelta(minutes=1),
            )
            self.assertEqual(active["phase"], "safe_stopped")
            with self.assertRaisesRegex(
                self.module.BulkRangeExecutionError, "already active or safe-stopped"
            ):
                self.module.prepare_next_batch_g3_proposal(
                    plan_root=state["plan"],
                    expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                    expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                    execution_ledger_path=state["ledger_path"],
                    batch_output_dir=root / "replacement",
                    account_budget_root=root / "replacement-budget",
                    credential_alias="racing-api-primary",
                    account_scope_id="bulk-range-b1-retry",
                    openapi_fingerprint_path=root / "openapi-fingerprint.json",
                    approved_openapi_fingerprint_sha256=hashlib.sha256(
                        (root / "openapi-fingerprint.json").read_bytes()
                    ).hexdigest(),
                    output_dir=root / "replacement-proposal",
                    now=now + timedelta(minutes=2),
                )

    def test_explicit_resume_requires_fresh_proof_and_preserves_attempts(self):
        now = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
        target_race = self.race()
        second_race = dict(target_race)
        second_race["race_id"] = "rac_unrelated_2005"
        second_race["race_name"] = "Unrelated race"
        second_race["runners"] = []

        class FailingClient:
            request_ceiling = 10

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                if self.request_count == 1:
                    return {
                        "results": [target_race],
                        "total": 2,
                        "limit": 100,
                        "skip": 0,
                        "query": [],
                    }
                self.request_ledger[-1]["status"] = None
                raise RuntimeError("simulated transport stop")

        class ResumeClient:
            request_ceiling = 8

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url):
                if "skip=1" not in url:
                    raise AssertionError("resume did not continue from checkpoint")
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                return {
                    "results": [second_race],
                    "total": 2,
                    "limit": 100,
                    "skip": 1,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.prepare_approval_and_claim(root, now)
            failing_client = FailingClient()
            with self.assertRaisesRegex(RuntimeError, "transport stop"):
                self.runner_module.run_bulk_range_batch_artifact(
                    plan_root=state["plan"],
                    expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                    expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                    batch_id="0001-france-2005-2005",
                    output_dir=state["batch_output"],
                    client=failing_client,
                    openapi_fingerprint_identity=state["fingerprint_identity"],
                )
            safe_stopped = self.module.mark_batch_safe_stopped(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                claim_token=state["claim"]["claim_token"],
                request_count=failing_client.request_count,
                error_type="RuntimeError",
                error_message="simulated transport stop",
                now=now + timedelta(minutes=1),
            )
            self.assertEqual(safe_stopped["attempts"][0]["request_count"], 2)

            expired_proof = root / "expired-resume-proof.json"
            expired_sha = self.proof(
                expired_proof,
                proposal_sha=state["approval"]["proposal_manifest_sha256"],
                now=now - timedelta(minutes=20),
                credential_alias=state["credential_alias"],
                scope_id=state["scope_id"],
            )
            with self.assertRaisesRegex(ValueError, "expired"):
                self.module.resume_batch_execution(
                    plan_root=state["plan"],
                    expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                    expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                    execution_ledger_path=state["ledger_path"],
                    approval_root=state["approval_root"],
                    approved_g3_manifest_sha256=state["approval"]["approval_manifest_sha256"],
                    exclusive_proof_path=expired_proof,
                    exclusive_proof_sha256=expired_sha,
                    batch_output_dir=state["batch_output"],
                    account_budget_root=state["budget_root"],
                    credential_alias=state["credential_alias"],
                    account_scope_id=state["scope_id"],
                    openapi_fingerprint_path=state["fingerprint_path"],
                    approved_openapi_fingerprint_sha256=state["fingerprint_sha"],
                    now=now + timedelta(minutes=2),
                )

            resume_proof = root / "resume-proof.json"
            resume_proof_sha = self.proof(
                resume_proof,
                proposal_sha=state["approval"]["proposal_manifest_sha256"],
                now=now + timedelta(minutes=2),
                credential_alias=state["credential_alias"],
                scope_id=state["scope_id"],
            )
            resumed = self.module.resume_batch_execution(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                approval_root=state["approval_root"],
                approved_g3_manifest_sha256=state["approval"]["approval_manifest_sha256"],
                exclusive_proof_path=resume_proof,
                exclusive_proof_sha256=resume_proof_sha,
                batch_output_dir=state["batch_output"],
                account_budget_root=state["budget_root"],
                credential_alias=state["credential_alias"],
                account_scope_id=state["scope_id"],
                openapi_fingerprint_path=state["fingerprint_path"],
                approved_openapi_fingerprint_sha256=state["fingerprint_sha"],
                now=now + timedelta(minutes=2, seconds=1),
            )
            self.assertEqual(resumed["attempt_number"], 2)
            self.assertEqual(resumed["prior_request_count"], 2)
            self.assertEqual(resumed["remaining_request_ceiling"], 8)

            manifest = self.runner_module.run_bulk_range_batch_artifact(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                batch_id="0001-france-2005-2005",
                output_dir=state["batch_output"],
                client=ResumeClient(),
                openapi_fingerprint_identity=state["fingerprint_identity"],
                resume=True,
                prior_request_count=resumed["prior_request_count"],
            )
            manifest_sha = hashlib.sha256(
                (state["batch_output"] / "batch-manifest.json").read_bytes()
            ).hexdigest()
            completed = self.module.mark_batch_complete(
                plan_root=state["plan"],
                expected_plan_manifest_sha256=state["summary"]["manifest_sha256"],
                expected_batch_plan_sha256=state["summary"]["plan_sha256"],
                execution_ledger_path=state["ledger_path"],
                claim_token=resumed["claim_token"],
                batch_output_dir=state["batch_output"],
                expected_batch_manifest_sha256=manifest_sha,
                request_count=manifest["request_count"],
                now=now + timedelta(minutes=3),
            )
            self.assertEqual(completed["request_count"], 3)
            self.assertEqual(
                [attempt["request_count"] for attempt in completed["attempts"]],
                [2, 1],
            )
            self.assertEqual(
                [attempt["request_ceiling"] for attempt in completed["attempts"]],
                [10, 8],
            )
            ledger = json.loads(state["ledger_path"].read_text(encoding="utf-8"))
            self.assertIsNone(ledger["active"])
            self.assertEqual(len(ledger["completed"][0]["attempts"]), 2)


if __name__ == "__main__":
    unittest.main()
