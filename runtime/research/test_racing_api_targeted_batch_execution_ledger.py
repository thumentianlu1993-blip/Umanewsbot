#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime.research.racing_api_targeted_batch_execution_ledger import (
    TargetedBatchExecutionError,
    claim_batch_execution,
    complete_batch_execution,
    mark_batch_safe_stopped,
    preflight_next_batch_execution,
    prepare_next_batch_g3_proposal,
    publish_batch_g3_approval,
)
from runtime.research.racing_api_horse_export import (
    EXPECTED_OPENAPI_FULL_SHA256,
    EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
    EXPECTED_OPENAPI_SELECTED_PATHS,
    EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES,
    EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
    EXPECTED_OPENAPI_VERSION,
    OPENAPI_SOURCE_URL,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_write(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)


class TargetedBatchExecutionLedgerTests(unittest.TestCase):
    def _openapi_fingerprint(
        self,
        root: Path,
        *,
        name: str = "openapi-fingerprint.json",
        generated_at: str = "2026-08-29T15:33:04+08:00",
    ) -> tuple[Path, str]:
        path = root / name
        payload = {
            "fingerprint_generated_at": generated_at,
            "full_openapi_sha256": EXPECTED_OPENAPI_FULL_SHA256,
            "openapi_version": EXPECTED_OPENAPI_VERSION,
            "selected_contract": {
                "paths": list(EXPECTED_OPENAPI_SELECTED_PATHS),
                "sha256": EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
            },
            "selected_schema": {
                "names": list(EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES),
                "sha256": EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
            },
            "source_url": OPENAPI_SOURCE_URL,
        }
        private_write(path, json.dumps(payload, sort_keys=True) + "\n")
        return path, sha(path)

    def _plan(self, root: Path, *, batches: int = 2) -> dict:
        plan_root = root / "plan"
        plan_root.mkdir(mode=0o700)
        seed_root = plan_root / "seed-ledgers"
        seed_root.mkdir(mode=0o700)
        rows = []
        total_seeds = 0
        total_ceiling = 0
        for ordinal in range(1, batches + 1):
            seeds = [
                {
                    "schema_version": "targeted-horse-seed.v1",
                    "seed_id": f"batch-{ordinal}-seed-{seed_ordinal}",
                    "name": f"Horse {seed_ordinal}",
                    "target": {
                        "country_region": "france",
                        "year": 2024,
                        "local_date": "2024-01-01",
                    },
                }
                for seed_ordinal in (1, 2)
            ]
            seed_path = seed_root / f"{ordinal:04d}-france-2024-01.jsonl"
            private_write(
                seed_path,
                "".join(
                    json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                    for seed in seeds
                ),
            )
            rows.append(
                {
                    "schema_version": "racing-api-targeted-batch-plan.v1",
                    "batch_id": f"{ordinal:04d}-france-2024-01",
                    "ordinal": ordinal,
                    "country_region": "france",
                    "edition_year": 2024,
                    "seed_count": 2,
                    "request_ceiling": 8,
                    "theoretical_min_duration_seconds": 2.0,
                    "not_before_offset_minutes": (ordinal - 1) * 30,
                    "approval_status": "proposed_not_approved",
                    "seed_ledger": {
                        "path": str(seed_path.relative_to(plan_root)),
                        "sha256": sha(seed_path),
                        "size": seed_path.stat().st_size,
                        "rows": 2,
                    },
                }
            )
            total_seeds += 2
            total_ceiling += 8
        plan_path = plan_root / "batch-plan.jsonl"
        private_write(
            plan_path,
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
                for row in rows
            ),
        )
        manifest = {
            "schema_version": "racing-api-targeted-batch-plan.v1",
            "status": "PROPOSED_NOT_APPROVED",
            "completion_marker": "PREPARED",
            "approval": False,
            "execution_ready": False,
            "network_requests": 0,
            "database_writes": 0,
            "parameters": {
                "batch_size_cap": 2,
                "max_search_candidates": 1,
                "max_results_pages_per_horse": 1,
                "max_parent_profiles": 0,
                "per_seed_request_ceiling": 4,
                "min_interval_ms": 250,
                "max_requests_per_second": 4.0,
                "spacing_minutes": 30,
                "max_concurrent_batches": 1,
                "exclusive_account_proof_required_per_batch": True,
            },
            "counts": {
                "seeds": total_seeds,
                "batches": batches,
                "request_ceiling": total_ceiling,
            },
            "batch_plan": {
                "path": plan_path.name,
                "sha256": sha(plan_path),
                "size": plan_path.stat().st_size,
                "rows": batches,
            },
        }
        manifest_path = plan_root / "batch-plan-manifest.json"
        private_write(manifest_path, json.dumps(manifest, sort_keys=True) + "\n")
        private_write(plan_root / "PREPARED", sha(manifest_path) + "\n")
        return {
            "plan_root": plan_root,
            "expected_plan_manifest_sha256": sha(manifest_path),
            "expected_batch_plan_sha256": sha(plan_path),
            "execution_ledger_path": root / "state" / "execution-ledger.json",
            "rows": rows,
        }

    def _prepare_and_approve(
        self,
        *,
        paths: dict,
        root: Path,
        suffix: str,
        batch_output: Path,
        budget_root: Path,
        now: datetime,
    ) -> dict:
        fingerprint_path, fingerprint_sha = self._openapi_fingerprint(root)
        proposal_root = root / f"proposal-{suffix}"
        proposal = prepare_next_batch_g3_proposal(
            **{key: paths[key] for key in (
                "plan_root",
                "expected_plan_manifest_sha256",
                "expected_batch_plan_sha256",
                "execution_ledger_path",
            )},
            batch_output_dir=batch_output,
            account_budget_root=budget_root,
            credential_alias="tra-primary",
            account_scope_id=f"batch-{suffix}",
            openapi_fingerprint_path=fingerprint_path,
            approved_openapi_fingerprint_sha256=fingerprint_sha,
            output_dir=proposal_root,
            now=now,
        )
        approval_root = root / f"approval-{suffix}"
        approval = publish_batch_g3_approval(
            proposal_root=proposal_root,
            approved_proposal_manifest_sha256=proposal["proposal_manifest_sha256"],
            approved_by="owner",
            decision_source_reference=f"owner-g3-{suffix}",
            output_dir=approval_root,
            now=now + timedelta(seconds=1),
        )
        return {
            "proposal": proposal,
            "proposal_root": proposal_root,
            "approval": approval,
            "approval_root": approval_root,
            "openapi_fingerprint_path": fingerprint_path,
            "openapi_fingerprint_sha256": fingerprint_sha,
        }

    def _proof(self, root: Path, *, scope_id: str, proposal_sha: str, now: datetime) -> tuple[Path, str]:
        proof = {
            "schema_version": "racing-api-exclusive-account-proof.v1",
            "status": "approved",
            "host": "api.theracingapi.com",
            "credential_alias": "tra-primary",
            "scope_id": scope_id,
            "scope_manifest_sha256": proposal_sha,
            "observed_at": now.isoformat().replace("+00:00", "Z"),
            "valid_until": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
            "checks": {
                "race_live_scheduler_enabled": False,
                "race_live_runner_active": 0,
                "race_data_sync_network_enabled": False,
                "race_data_sync_active_claims": 0,
                "other_backfill_processes": 0,
                "manual_caller_window_reserved": True,
            },
        }
        path = root / f"proof-{scope_id}.json"
        private_write(path, json.dumps(proof, sort_keys=True) + "\n")
        return path, sha(path)

    def _claim(
        self,
        *,
        paths: dict,
        approved: dict,
        batch_output: Path,
        budget_root: Path,
        proof_path: Path,
        proof_sha: str,
        request_ceiling: int,
        resume: bool,
        now: datetime,
        fingerprint_path: Path | None = None,
        fingerprint_sha: str | None = None,
    ) -> dict:
        scope = approved["approval"]["scope"]
        return claim_batch_execution(
            **{key: paths[key] for key in (
                "plan_root",
                "expected_plan_manifest_sha256",
                "expected_batch_plan_sha256",
                "execution_ledger_path",
            )},
            approval_root=approved["approval_root"],
            approved_g3_manifest_sha256=approved["approval"]["approval_manifest_sha256"],
            exclusive_proof_path=proof_path,
            exclusive_proof_sha256=proof_sha,
            seed_ledger_path=Path(scope["batch"]["seed_ledger_path"]),
            output_dir=batch_output,
            account_budget_root=budget_root,
            credential_alias="tra-primary",
            account_scope_id=scope["account"]["scope_id"],
            account_scope_manifest_sha256=approved["proposal"]["proposal_manifest_sha256"],
            request_ceiling=request_ceiling,
            account_request_ceiling=request_ceiling,
            max_search_candidates=1,
            max_results_pages_per_horse=1,
            max_parent_profiles=0,
            openapi_fingerprint_path=(
                fingerprint_path or approved["openapi_fingerprint_path"]
            ),
            approved_openapi_fingerprint_sha256=(
                fingerprint_sha or approved["openapi_fingerprint_sha256"]
            ),
            resume=resume,
            now=now,
        )

    def _complete_artifact(
        self,
        output: Path,
        *,
        seed_path: Path,
        request_ceiling: int,
        request_count: int,
        openapi_contract: dict,
    ):
        output.mkdir(mode=0o700, exist_ok=True)
        manifest = {
            "schema_version": "targeted-horse-batch-run.v1",
            "status": "complete",
            "database_writes": 0,
            "seed_ledger": {
                "path": str(seed_path),
                "sha256": sha(seed_path),
                "size": seed_path.stat().st_size,
                "rows": 2,
            },
            "parameters": {
                "max_search_candidates": 1,
                "max_results_pages_per_horse": 1,
                "max_parent_profiles": 0,
                "content_pool_schema_version": "racing-api-content-pool.v1",
                "openapi_contract": openapi_contract,
            },
            "planned_seed_count": 2,
            "completed_seed_count": 2,
            "request_ceiling": request_ceiling,
            "request_count": request_count,
        }
        manifest_path = output / "batch-manifest.json"
        private_write(manifest_path, json.dumps(manifest, sort_keys=True) + "\n")
        private_write(output / "COMPLETE", sha(manifest_path) + "\n")
        return manifest_path

    def _preflight(
        self,
        *,
        paths: dict,
        approved: dict,
        batch_output: Path,
        budget_root: Path,
        request_ceiling: int,
        resume: bool,
        now: datetime,
    ) -> dict:
        scope = approved["approval"]["scope"]
        return preflight_next_batch_execution(
            **{key: paths[key] for key in (
                "plan_root",
                "expected_plan_manifest_sha256",
                "expected_batch_plan_sha256",
                "execution_ledger_path",
            )},
            approval_root=approved["approval_root"],
            approved_g3_manifest_sha256=approved["approval"]["approval_manifest_sha256"],
            seed_ledger_path=Path(scope["batch"]["seed_ledger_path"]),
            output_dir=batch_output,
            account_budget_root=budget_root,
            credential_alias="tra-primary",
            account_scope_id=scope["account"]["scope_id"],
            account_scope_manifest_sha256=approved["proposal"]["proposal_manifest_sha256"],
            request_ceiling=request_ceiling,
            account_request_ceiling=request_ceiling,
            max_search_candidates=1,
            max_results_pages_per_horse=1,
            max_parent_profiles=0,
            openapi_fingerprint_path=approved["openapi_fingerprint_path"],
            approved_openapi_fingerprint_sha256=approved["openapi_fingerprint_sha256"],
            resume=resume,
            now=now,
        )

    def test_preflight_validates_exact_next_scope_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._plan(root)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            output = root / "batch-output-1"
            budget = root / "budget-1"
            approved = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="one",
                batch_output=output,
                budget_root=budget,
                now=now,
            )
            ledger_before = paths["execution_ledger_path"].read_bytes()
            lock_path = paths["execution_ledger_path"].with_suffix(".json.lock")
            lock_before = lock_path.read_bytes()

            result = self._preflight(
                paths=paths,
                approved=approved,
                batch_output=output,
                budget_root=budget,
                request_ceiling=8,
                resume=False,
                now=now + timedelta(seconds=2),
            )

            self.assertEqual(result["status"], "ready_for_fresh_exclusive_proof")
            self.assertEqual(result["next_batch"]["ordinal"], 1)
            self.assertEqual(result["next_batch"]["request_ceiling"], 8)
            self.assertFalse(result["proof_loaded"])
            self.assertFalse(result["ledger_mutated"])
            self.assertEqual(result["network_requests"], 0)
            self.assertEqual(result["database_writes"], 0)
            self.assertEqual(paths["execution_ledger_path"].read_bytes(), ledger_before)
            self.assertEqual(lock_path.read_bytes(), lock_before)
            self.assertFalse(output.exists())
            self.assertFalse(budget.exists())

    def test_preflight_rejects_command_drift_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._plan(root)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            output = root / "batch-output-1"
            budget = root / "budget-1"
            approved = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="one",
                batch_output=output,
                budget_root=budget,
                now=now,
            )
            ledger_before = paths["execution_ledger_path"].read_bytes()

            with self.assertRaisesRegex(
                TargetedBatchExecutionError,
                "network command arguments drift",
            ):
                self._preflight(
                    paths=paths,
                    approved=approved,
                    batch_output=output,
                    budget_root=budget,
                    request_ceiling=7,
                    resume=False,
                    now=now + timedelta(seconds=2),
                )

            self.assertEqual(paths["execution_ledger_path"].read_bytes(), ledger_before)
            self.assertFalse(output.exists())
            self.assertFalse(budget.exists())

    def test_exact_approval_claim_completion_and_spacing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._plan(root)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            output_one = root / "batch-output-1"
            budget_one = root / "budget-1"
            approved_one = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="one",
                batch_output=output_one,
                budget_root=budget_one,
                now=now,
            )
            proof_one, proof_one_sha = self._proof(
                root,
                scope_id="batch-one",
                proposal_sha=approved_one["proposal"]["proposal_manifest_sha256"],
                now=now,
            )
            claim = self._claim(
                paths=paths,
                approved=approved_one,
                batch_output=output_one,
                budget_root=budget_one,
                proof_path=proof_one,
                proof_sha=proof_one_sha,
                request_ceiling=8,
                resume=False,
                now=now + timedelta(seconds=2),
            )
            with self.assertRaisesRegex(TargetedBatchExecutionError, "already running"):
                self._claim(
                    paths=paths,
                    approved=approved_one,
                    batch_output=output_one,
                    budget_root=budget_one,
                    proof_path=proof_one,
                    proof_sha=proof_one_sha,
                    request_ceiling=8,
                    resume=False,
                    now=now + timedelta(seconds=3),
                )
            manifest_path = self._complete_artifact(
                output_one,
                seed_path=Path(approved_one["approval"]["scope"]["batch"]["seed_ledger_path"]),
                request_ceiling=8,
                request_count=5,
                openapi_contract=approved_one["approval"]["scope"]["run"]["openapi_contract"],
            )
            completed = complete_batch_execution(
                **{key: paths[key] for key in (
                    "plan_root",
                    "expected_plan_manifest_sha256",
                    "expected_batch_plan_sha256",
                    "execution_ledger_path",
                )},
                claim_token=claim["claim_token"],
                batch_manifest_path=manifest_path,
                now=now + timedelta(seconds=4),
            )
            self.assertEqual(completed["total_request_count"], 5)

            output_two = root / "batch-output-2"
            budget_two = root / "budget-2"
            approved_two = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="two",
                batch_output=output_two,
                budget_root=budget_two,
                now=now + timedelta(seconds=5),
            )
            proof_two, proof_two_sha = self._proof(
                root,
                scope_id="batch-two",
                proposal_sha=approved_two["proposal"]["proposal_manifest_sha256"],
                now=now + timedelta(seconds=5),
            )
            with self.assertRaisesRegex(TargetedBatchExecutionError, "cannot start before"):
                self._claim(
                    paths=paths,
                    approved=approved_two,
                    batch_output=output_two,
                    budget_root=budget_two,
                    proof_path=proof_two,
                    proof_sha=proof_two_sha,
                    request_ceiling=8,
                    resume=False,
                    now=now + timedelta(minutes=1),
                )

    def test_safe_stop_requires_new_retry_g3_and_counts_consumed_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._plan(root, batches=1)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            output = root / "batch-output"
            budget_one = root / "budget-1"
            approved_one = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="one",
                batch_output=output,
                budget_root=budget_one,
                now=now,
            )
            proof_one, proof_one_sha = self._proof(
                root,
                scope_id="batch-one",
                proposal_sha=approved_one["proposal"]["proposal_manifest_sha256"],
                now=now,
            )
            claim_one = self._claim(
                paths=paths,
                approved=approved_one,
                batch_output=output,
                budget_root=budget_one,
                proof_path=proof_one,
                proof_sha=proof_one_sha,
                request_ceiling=8,
                resume=False,
                now=now + timedelta(seconds=2),
            )
            output.mkdir(mode=0o700)
            private_write(
                output / "batch-definition.json",
                json.dumps(
                    {
                        "schema_version": "targeted-horse-batch-definition.v1",
                        "database_writes": 0,
                        "seed_ledger": {
                            "sha256": approved_one["approval"]["scope"]["batch"]["seed_ledger_sha256"]
                        },
                        "parameters": {
                            "max_search_candidates": 1,
                            "max_results_pages_per_horse": 1,
                            "max_parent_profiles": 0,
                            "content_pool_schema_version": "racing-api-content-pool.v1",
                            "openapi_contract": approved_one["approval"]["scope"]["run"]["openapi_contract"],
                        },
                        "seeds": [{"seed_id": "a"}, {"seed_id": "b"}],
                    },
                    sort_keys=True,
                )
                + "\n",
            )
            private_write(
                output / "checkpoint.json",
                json.dumps(
                    {
                        "schema_version": "targeted-horse-batch-checkpoint.v1",
                        "status": "safe_stopped",
                        "completed": {"a": {"manifest_sha256": "a" * 64}},
                        "last_error": {"type": "TimeoutError"},
                    },
                    sort_keys=True,
                )
                + "\n",
            )
            stopped = mark_batch_safe_stopped(
                **{key: paths[key] for key in (
                    "plan_root",
                    "expected_plan_manifest_sha256",
                    "expected_batch_plan_sha256",
                    "execution_ledger_path",
                )},
                claim_token=claim_one["claim_token"],
                request_count=5,
                error_type="TimeoutError",
                error_message="safe stop",
                now=now + timedelta(seconds=3),
            )
            self.assertEqual(stopped["phase"], "safe_stopped")

            budget_two = root / "budget-2"
            approved_two = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="two",
                batch_output=output,
                budget_root=budget_two,
                now=now + timedelta(seconds=4),
            )
            retry_scope = approved_two["approval"]["scope"]["run"]
            self.assertTrue(retry_scope["resume"])
            self.assertEqual(retry_scope["request_ceiling"], 4)
            self.assertEqual(retry_scope["prior_request_count"], 5)
            self.assertEqual(retry_scope["cumulative_request_ceiling"], 9)
            proof_two, proof_two_sha = self._proof(
                root,
                scope_id="batch-two",
                proposal_sha=approved_two["proposal"]["proposal_manifest_sha256"],
                now=now + timedelta(seconds=4),
            )
            claim_two = self._claim(
                paths=paths,
                approved=approved_two,
                batch_output=output,
                budget_root=budget_two,
                proof_path=proof_two,
                proof_sha=proof_two_sha,
                request_ceiling=4,
                resume=True,
                now=now + timedelta(seconds=5),
            )
            manifest_path = self._complete_artifact(
                output,
                seed_path=Path(approved_two["approval"]["scope"]["batch"]["seed_ledger_path"]),
                request_ceiling=4,
                request_count=3,
                openapi_contract=approved_two["approval"]["scope"]["run"]["openapi_contract"],
            )
            completed = complete_batch_execution(
                **{key: paths[key] for key in (
                    "plan_root",
                    "expected_plan_manifest_sha256",
                    "expected_batch_plan_sha256",
                    "execution_ledger_path",
                )},
                claim_token=claim_two["claim_token"],
                batch_manifest_path=manifest_path,
                now=now + timedelta(seconds=6),
            )
            self.assertEqual(completed["total_request_count"], 8)
            self.assertEqual(len(completed["attempts"]), 2)

    def test_claim_rejects_command_drift_and_proof_scope_drift_without_claiming(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._plan(root, batches=1)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            output = root / "batch-output"
            budget = root / "budget"
            approved = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="one",
                batch_output=output,
                budget_root=budget,
                now=now,
            )
            proof, proof_sha = self._proof(
                root,
                scope_id="batch-one",
                proposal_sha=approved["proposal"]["proposal_manifest_sha256"],
                now=now,
            )
            with self.assertRaisesRegex(TargetedBatchExecutionError, "command arguments drift"):
                self._claim(
                    paths=paths,
                    approved=approved,
                    batch_output=output,
                    budget_root=budget,
                    proof_path=proof,
                    proof_sha=proof_sha,
                    request_ceiling=7,
                    resume=False,
                    now=now + timedelta(seconds=2),
                )
            alternate_path, alternate_sha = self._openapi_fingerprint(
                root,
                name="alternate-openapi-fingerprint.json",
                generated_at="2026-08-30T00:00:00+00:00",
            )
            with self.assertRaisesRegex(TargetedBatchExecutionError, "approval does not bind"):
                self._claim(
                    paths=paths,
                    approved=approved,
                    batch_output=output,
                    budget_root=budget,
                    proof_path=proof,
                    proof_sha=proof_sha,
                    request_ceiling=8,
                    resume=False,
                    now=now + timedelta(seconds=2),
                    fingerprint_path=alternate_path,
                    fingerprint_sha=alternate_sha,
                )
            wrong_proof, wrong_proof_sha = self._proof(
                root,
                scope_id="wrong-scope",
                proposal_sha=approved["proposal"]["proposal_manifest_sha256"],
                now=now,
            )
            with self.assertRaisesRegex(ValueError, "identity drift"):
                self._claim(
                    paths=paths,
                    approved=approved,
                    batch_output=output,
                    budget_root=budget,
                    proof_path=wrong_proof,
                    proof_sha=wrong_proof_sha,
                    request_ceiling=8,
                    resume=False,
                    now=now + timedelta(seconds=2),
                )
            ledger = json.loads(
                paths["execution_ledger_path"].read_text(encoding="utf-8")
            )
            self.assertIsNone(ledger["active"])
            self.assertEqual(ledger["completed"], [])

    def test_zero_request_preflight_failure_restarts_fresh_with_new_paths_and_g3(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._plan(root, batches=1)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            first_output = root / "batch-output-1"
            first_budget = root / "budget-1"
            approved_one = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="one",
                batch_output=first_output,
                budget_root=first_budget,
                now=now,
            )
            proof_one, proof_one_sha = self._proof(
                root,
                scope_id="batch-one",
                proposal_sha=approved_one["proposal"]["proposal_manifest_sha256"],
                now=now,
            )
            claim = self._claim(
                paths=paths,
                approved=approved_one,
                batch_output=first_output,
                budget_root=first_budget,
                proof_path=proof_one,
                proof_sha=proof_one_sha,
                request_ceiling=8,
                resume=False,
                now=now + timedelta(seconds=2),
            )
            mark_batch_safe_stopped(
                **{key: paths[key] for key in (
                    "plan_root",
                    "expected_plan_manifest_sha256",
                    "expected_batch_plan_sha256",
                    "execution_ledger_path",
                )},
                claim_token=claim["claim_token"],
                request_count=0,
                error_type="ValueError",
                error_message="local preflight failed",
                now=now + timedelta(seconds=3),
            )
            approved_two = self._prepare_and_approve(
                paths=paths,
                root=root,
                suffix="two",
                batch_output=root / "batch-output-2",
                budget_root=root / "budget-2",
                now=now + timedelta(seconds=4),
            )
            run = approved_two["approval"]["scope"]["run"]
            self.assertFalse(run["resume"])
            self.assertEqual(run["attempt_number"], 2)
            self.assertEqual(run["prior_request_count"], 0)
            self.assertEqual(run["request_ceiling"], 8)
            self.assertEqual(len(approved_two["approval"]["scope"]["prior_attempt_sha256"]), 1)


if __name__ == "__main__":
    unittest.main()
