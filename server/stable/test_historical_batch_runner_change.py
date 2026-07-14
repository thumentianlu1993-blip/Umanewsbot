from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess
import sys
from io import StringIO
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from stable.models import (
    HistoricalBatchLock,
    HistoricalBatchPhase,
    HistoricalBatchRun,
    HistoricalBatchRunEvent,
    HistoricalBatchRunStatus,
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_batch_runner import (
    RunnerLeaseError,
    RunnerPlanError,
    RunnerStateError,
    acquire_runner_lease,
    create_runner_run,
    execute_runner_plan,
    heartbeat_runner_lease,
    load_runtime_state,
    redact_runner_text,
    release_runner_lease,
    request_runner_pause,
    resume_runner_run,
    runner_checkpoint_matches,
    runner_secret_values_from_environment,
    runner_status_payload,
    takeover_runner_lease,
    validate_runner_plan,
    write_runtime_state,
)
from stable.services.historical_race_batches import (
    STANDARD_REGION_BATCH_LIMIT,
    select_historical_band_batch_targets,
    write_band_batch_artifact,
)
from stable.services.historical_race_inventory import InventoryValidationError


class HistoricalBatchScaleChangeTests(TestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="japan-batch006-scale",
            country_region=RacingRegion.JAPAN,
            canonical_name_original="Batch 006 Scale",
            chinese_name="第六批扩容测试",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )

    def _target(self, year: int, suffix: int) -> HistoricalRaceEventTarget:
        series = RaceSeries.objects.create(
            key=f"japan-batch006-scale-{suffix}",
            country_region=RacingRegion.JAPAN,
            canonical_name_original=f"Batch 006 Scale {suffix}",
            chinese_name=f"第六批扩容测试 {suffix}",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=year,
            country_region=RacingRegion.JAPAN,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.PENDING,
            original_name=series.canonical_name_original,
            chinese_name=series.chinese_name,
            artifact_sha256="a" * 64,
        )

    def test_standard_region_limit_is_250(self):
        self.assertEqual(STANDARD_REGION_BATCH_LIMIT, 250)

    def test_explicit_50_target_batch_remains_supported(self):
        for index in range(55):
            self._target(2025 - (index % 10), index)
        selected = select_historical_band_batch_targets(
            year_start=2016,
            year_end=2025,
            inventory_manifest_sha256="a" * 64,
            region_limit=50,
        )
        self.assertEqual(len(selected), 50)

    def test_region_limit_251_is_rejected(self):
        with self.assertRaisesMessage(InventoryValidationError, "between 1 and 250"):
            select_historical_band_batch_targets(
                year_start=2016,
                year_end=2025,
                inventory_manifest_sha256="a" * 64,
                region_limit=251,
            )

    def test_artifact_records_actual_approved_region_limit(self):
        target = self._target(2025, 1)
        with TemporaryDirectory() as tmp:
            result = write_band_batch_artifact(
                [target],
                output_dir=Path(tmp) / "batch006",
                inventory_manifest_sha256="a" * 64,
                year_start=2016,
                year_end=2025,
                approved_region_limit=80,
            )
            summary = json.loads(Path(result["output_dir"], "summary.json").read_text(encoding="utf-8"))
            manifest = json.loads(Path(result["output_dir"], "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(result["approved_region_limit"], 80)
        self.assertEqual(summary["approved_region_limit"], 80)
        self.assertEqual(manifest["approved_region_limit"], 80)


class HistoricalBatchRunnerPlanTests(SimpleTestCase):
    def _plan(self, root: Path, *, phase: str = "crawl") -> dict:
        tool = root / "tools" / "sample.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text("print('ok')\n", encoding="utf-8")
        tool_sha = hashlib.sha256(tool.read_bytes()).hexdigest()
        output = root / "artifacts" / "out.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        return {
            "schema_version": "1.0",
            "batch_id": "2016-2025-batch-006",
            "phase": phase,
            "network_enabled": phase == "crawl",
            "write_enabled": phase == "apply",
            "image_id": "sha256:" + "1" * 64,
            "image_revision": "a" * 40,
            "artifact_root": str(root / "artifacts"),
            "tool_root": str(root / "tools"),
            "tool_manifest": {"sample.py": tool_sha},
            "steps": [
                {
                    "id": "sample",
                    "kind": "python_tool",
                    "argv": ["python", str(tool)],
                    "inputs": [],
                    "outputs": [str(output)],
                }
            ],
        }

    def test_valid_structured_plan_is_accepted(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            normalized = validate_runner_plan(plan)
        self.assertEqual(normalized["phase"], HistoricalBatchPhase.CRAWL)

    def test_string_command_and_shell_are_rejected(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            plan["steps"][0]["argv"] = "sh -c echo unsafe"
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)

    def test_step_id_cannot_escape_log_directory(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            plan["steps"][0]["id"] = "../../outside"
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)

    def test_python_and_management_steps_reject_disguised_executables(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            plan["steps"][0]["argv"][0] = "/bin/rm"
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)
            plan = self._plan(root)
            plan["steps"][0]["argv"][0] = str(root / "python")
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)
            plan = self._plan(root)
            plan["steps"][0] = {
                "id": "fake-management",
                "kind": "management",
                "argv": ["/bin/rm", "manage.py", "build_historical_race_band_batch"],
                "inputs": [],
                "outputs": [],
            }
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)
            plan["steps"][0]["argv"][0] = str(root / "python")
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)

    def test_non_apply_phase_rejects_write_arguments(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            plan["steps"][0] = {
                "id": "write-in-crawl",
                "kind": "management",
                "argv": ["python", "manage.py", "manage_historical_race_detail_sources", "--action=apply"],
                "inputs": [],
                "outputs": [],
            }
            with self.assertRaisesMessage(RunnerPlanError, "write argument"):
                validate_runner_plan(plan)
            plan["steps"][0]["argv"] = ["sh", "-c", "echo unsafe"]
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)

    def test_illegal_phase_permission_combinations_are_rejected(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            plan["write_enabled"] = True
            with self.assertRaisesMessage(RunnerPlanError, "permission"):
                validate_runner_plan(plan)
            plan = self._plan(Path(tmp), phase="apply")
            plan["network_enabled"] = True
            with self.assertRaisesMessage(RunnerPlanError, "permission"):
                validate_runner_plan(plan)

    def test_tool_manifest_drift_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            Path(plan["steps"][0]["argv"][1]).write_text("print('changed')\n", encoding="utf-8")
            with self.assertRaisesMessage(RunnerPlanError, "tool SHA"):
                validate_runner_plan(plan)

    def test_tool_path_escape_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            outside = root / "outside.py"
            outside.write_text("print('unsafe')\n", encoding="utf-8")
            plan["steps"][0]["argv"][1] = str(outside)
            with self.assertRaisesMessage(RunnerPlanError, "tool path"):
                validate_runner_plan(plan)

    def test_apply_step_requires_approval_and_expected_sha(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp), phase="apply")
            plan["steps"][0] = {
                "id": "apply",
                "kind": "management",
                "argv": ["python", "manage.py", "import_historical_race_event_candidates", "--apply"],
                "inputs": [],
                "outputs": [],
            }
            with self.assertRaisesMessage(RunnerPlanError, "approval"):
                validate_runner_plan(plan)

    def test_apply_phase_rejects_python_tools_that_bypass_importer_gates(self):
        with TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp), phase="apply")
            with self.assertRaisesMessage(RunnerPlanError, "approval-aware management"):
                validate_runner_plan(plan)

    def test_input_identity_must_match_file_sha(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            input_path = root / "artifacts" / "input.json"
            input_path.write_text("{}\n", encoding="utf-8")
            plan["steps"][0]["inputs"] = [
                {"path": str(input_path), "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}
            ]
            validate_runner_plan(plan)
            input_path.write_text('{"changed": true}\n', encoding="utf-8")
            with self.assertRaisesMessage(RunnerPlanError, "input SHA"):
                validate_runner_plan(plan)

    def test_apply_step_accepts_only_structured_approved_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, phase="apply")
            approval_path = root / "artifacts" / "approval.json"
            candidate_path = root / "artifacts" / "candidates.jsonl"
            candidate_path.write_text("{}\n", encoding="utf-8")
            candidate_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
            approval_path.write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "approved_by": "operator",
                        "approved_at": "2026-07-14T00:00:00Z",
                        "expected_sha256": candidate_sha,
                    }
                ),
                encoding="utf-8",
            )
            approval_sha = hashlib.sha256(approval_path.read_bytes()).hexdigest()
            plan["steps"][0] = {
                "id": "apply",
                "kind": "management",
                "argv": [
                    "python",
                    "manage.py",
                    "import_historical_race_event_candidates",
                    "--jsonl",
                    str(candidate_path),
                    "--expected-sha256",
                    candidate_sha,
                    "--apply",
                ],
                "inputs": [
                    {"path": str(approval_path), "sha256": approval_sha},
                    {"path": str(candidate_path), "sha256": candidate_sha},
                ],
                "outputs": [],
                "approval": {
                    "status": "approved",
                    "path": str(approval_path),
                    "sha256": approval_sha,
                },
                "expected_sha256": candidate_sha,
            }
            self.assertEqual(validate_runner_plan(plan)["phase"], HistoricalBatchPhase.APPLY)

    def test_apply_step_rejects_command_path_not_bound_to_declared_input(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, phase="apply")
            approval_path = root / "artifacts" / "approval.json"
            candidate_path = root / "artifacts" / "candidates.jsonl"
            other_path = root / "artifacts" / "other.jsonl"
            candidate_path.write_text("{}\n", encoding="utf-8")
            other_path.write_text('{"unapproved": true}\n', encoding="utf-8")
            candidate_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
            approval_path.write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "approved_by": "operator",
                        "approved_at": "2026-07-14T00:00:00Z",
                        "expected_sha256": candidate_sha,
                    }
                ),
                encoding="utf-8",
            )
            approval_sha = hashlib.sha256(approval_path.read_bytes()).hexdigest()
            plan["steps"][0] = {
                "id": "apply-unbound",
                "kind": "management",
                "argv": [
                    "python",
                    "manage.py",
                    "import_historical_race_event_candidates",
                    "--jsonl",
                    str(other_path),
                    "--expected-sha256",
                    candidate_sha,
                    "--apply",
                ],
                "inputs": [
                    {"path": str(approval_path), "sha256": approval_sha},
                    {"path": str(candidate_path), "sha256": candidate_sha},
                ],
                "outputs": [],
                "approval": {
                    "status": "approved",
                    "path": str(approval_path),
                    "sha256": approval_sha,
                },
                "expected_sha256": candidate_sha,
            }
            with self.assertRaisesMessage(RunnerPlanError, "declared input"):
                validate_runner_plan(plan)

    def test_apply_step_rejects_approval_metadata_not_bound_to_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, phase="apply")
            approval_path = root / "artifacts" / "approval.json"
            candidate_path = root / "artifacts" / "candidates.jsonl"
            candidate_path.write_text("{}\n", encoding="utf-8")
            candidate_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
            approval_path.write_text(
                json.dumps(
                    {
                        "status": "pending",
                        "approved_by": "operator",
                        "approved_at": "2026-07-14T00:00:00Z",
                        "expected_sha256": candidate_sha,
                    }
                ),
                encoding="utf-8",
            )
            approval_sha = hashlib.sha256(approval_path.read_bytes()).hexdigest()
            plan["steps"][0] = {
                "id": "apply-pending",
                "kind": "management",
                "argv": [
                    "python",
                    "manage.py",
                    "import_historical_race_event_candidates",
                    "--jsonl",
                    str(candidate_path),
                    "--expected-sha256",
                    candidate_sha,
                    "--apply",
                ],
                "inputs": [
                    {"path": str(approval_path), "sha256": approval_sha},
                    {"path": str(candidate_path), "sha256": candidate_sha},
                ],
                "outputs": [],
                "approval": {
                    "status": "approved",
                    "path": str(approval_path),
                    "sha256": approval_sha,
                },
                "expected_sha256": candidate_sha,
            }
            with self.assertRaisesMessage(RunnerPlanError, "approval file"):
                validate_runner_plan(plan)

    def test_date_discovery_commit_is_allowed_and_bound_to_artifact(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, phase="apply")
            artifact_dir = root / "artifacts" / "date-artifact"
            artifact_dir.mkdir()
            approval_path = artifact_dir / "approval.json"
            manifest_path = artifact_dir / "manifest.json"
            manifest_path.write_text('{"schema_version": "1.0"}\n', encoding="utf-8")
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            approval_path.write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "approved_by": "operator",
                        "approved_at": "2026-07-14T00:00:00Z",
                        "manifest_identity": {"path": "manifest.json", "sha256": manifest_sha},
                    }
                ),
                encoding="utf-8",
            )
            approval_sha = hashlib.sha256(approval_path.read_bytes()).hexdigest()
            plan["steps"][0] = {
                "id": "date-commit",
                "kind": "management",
                "argv": [
                    "python",
                    "manage.py",
                    "build_historical_race_date_discovery",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--approval",
                    str(approval_path),
                    "--commit",
                ],
                "inputs": [
                    {"path": str(approval_path), "sha256": approval_sha},
                    {"path": str(manifest_path), "sha256": manifest_sha},
                ],
                "outputs": [],
                "approval": {
                    "status": "approved",
                    "path": str(approval_path),
                    "sha256": approval_sha,
                },
                "expected_sha256": manifest_sha,
            }
            self.assertEqual(validate_runner_plan(plan)["phase"], HistoricalBatchPhase.APPLY)

    def test_redaction_removes_all_configured_secret_values(self):
        value = redact_runner_text("db=secret-token api=api-key", ["secret-token", "api-key"])
        self.assertEqual(value, "db=[REDACTED] api=[REDACTED]")

    def test_environment_secret_values_are_included_in_redaction_set(self):
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "db-secret", "PUBLIC_VALUE": "visible"}, clear=True):
            values = runner_secret_values_from_environment(["owner-secret"])
        self.assertIn("db-secret", values)
        self.assertIn("owner-secret", values)
        self.assertNotIn("visible", values)


class HistoricalBatchRunnerStateTests(SimpleTestCase):
    def test_runtime_state_is_atomic_and_round_trips(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner-state.json"
            payload = {"run_id": "run-1", "phase": "crawl", "completed_steps": ["one"]}
            write_runtime_state(path, payload)
            self.assertEqual(load_runtime_state(path), payload)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_runtime_state_rejects_invalid_json(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner-state.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(RunnerStateError):
                load_runtime_state(path)

    def test_checkpoint_override_must_be_the_fixed_artifact_state_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = {
                "run_id": "fixed-state",
                "batch_id": "batch",
                "phase": "crawl",
                "image_id": "sha256:" + "1" * 64,
                "image_revision": "a" * 40,
                "plan_sha256": "b" * 64,
                "completed_steps": [],
            }
            expected = root / "runner-state.json"
            alternate = root / "operator-supplied.json"
            write_runtime_state(expected, state)
            write_runtime_state(alternate, state)
            run = SimpleNamespace(artifact_root=str(root), checkpoint=state, **{key: state[key] for key in (
                "run_id", "batch_id", "phase", "image_id", "image_revision", "plan_sha256"
            )})
            self.assertTrue(runner_checkpoint_matches(run))
            self.assertFalse(runner_checkpoint_matches(run, alternate))


class HistoricalBatchRunnerCommandTests(TestCase):
    def test_run_stage_command_creates_and_completes_registered_run(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_root = root / "artifacts"
            tool_root = root / "tools"
            artifact_root.mkdir()
            tool_root.mkdir()
            tool = tool_root / "write_output.py"
            output_path = artifact_root / "output.txt"
            tool.write_text(
                "from pathlib import Path\n"
                f"Path({str(output_path)!r}).write_text('ok\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            tool_sha = hashlib.sha256(tool.read_bytes()).hexdigest()
            plan = {
                "schema_version": "1.0",
                "batch_id": "2016-2025-batch-006-command",
                "phase": "crawl",
                "network_enabled": True,
                "write_enabled": False,
                "image_id": "sha256:" + "1" * 64,
                "image_revision": "a" * 40,
                "artifact_root": str(artifact_root),
                "tool_root": str(tool_root),
                "tool_manifest": {"write_output.py": tool_sha},
                "steps": [
                    {
                        "id": "write-output",
                        "kind": "python_tool",
                        "argv": ["python", str(tool)],
                        "inputs": [],
                        "outputs": [str(output_path)],
                    }
                ],
            }
            plan_path = artifact_root / "runner-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            token_path = root / "owner.token"
            token_path.write_text("command-owner\n", encoding="utf-8")
            token_path.chmod(0o600)
            with override_settings(
                HISTORICAL_RUNNER_TOOL_ROOT=str(tool_root),
                HISTORICAL_RACE_BACKFILL_ENABLED=True,
                HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=True,
            ):
                call_command(
                    "run_historical_batch_stage",
                    plan=str(plan_path),
                    owner_token_file=str(token_path),
                    lock_file=str(artifact_root / ".runner.lock"),
                    run_id="command-run",
                    stdout=StringIO(),
                )
            run = HistoricalBatchRun.objects.get(run_id="command-run")
            self.assertEqual(run.status, HistoricalBatchRunStatus.COMPLETED)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "ok\n")
            self.assertEqual(run.checkpoint["completed_steps"][0]["id"], "write-output")

    def test_preflight_rejects_running_record_even_with_expired_or_missing_lease(self):
        with TemporaryDirectory() as tmp:
            run = create_runner_run(
                batch_id="2016-2025-batch-006-preflight",
                phase=HistoricalBatchPhase.CRAWL,
                artifact_root=tmp,
                plan_sha256="a" * 64,
                image_id="sha256:" + "1" * 64,
                image_revision="a" * 40,
            )
            HistoricalBatchRun.objects.filter(pk=run.pk).update(status=HistoricalBatchRunStatus.RUNNING)
            with self.assertRaisesMessage(CommandError, "running"):
                call_command("manage_historical_batch_runner", "preflight", stdout=StringIO())

    def test_preflight_reports_migration_safe_when_no_run_is_active(self):
        output = StringIO()
        call_command("manage_historical_batch_runner", "preflight", stdout=output)
        self.assertIn('"state": "migration_safe"', output.getvalue())


class HistoricalBatchRunnerLeaseTests(TestCase):
    def _run(self, root: Path, *, phase: str = HistoricalBatchPhase.CRAWL) -> HistoricalBatchRun:
        root.mkdir(parents=True, exist_ok=True)
        plan_path = root / "plan.json"
        plan_path.write_text("{}\n", encoding="utf-8")
        return create_runner_run(
            batch_id="2016-2025-batch-006",
            phase=phase,
            artifact_root=str(root),
            plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            image_id="sha256:" + "1" * 64,
            image_revision="a" * 40,
        )

    def test_models_store_run_lock_and_append_only_events(self):
        with TemporaryDirectory() as tmp:
            run = self._run(Path(tmp))
            self.assertEqual(run.status, HistoricalBatchRunStatus.PLANNED)
            HistoricalBatchRunEvent.objects.create(run=run, event_type="created", detail={})
            self.assertEqual(run.events.count(), 2)
            self.assertEqual(run.events.first().event_type, "created")

    def test_run_events_cannot_be_modified(self):
        with TemporaryDirectory() as tmp:
            run = self._run(Path(tmp))
            event = run.events.first()
            event.detail = {"changed": True}
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_event_detail_is_bounded(self):
        with TemporaryDirectory() as tmp:
            run = self._run(Path(tmp))
            with self.assertRaises(ValidationError):
                HistoricalBatchRunEvent.objects.create(
                    run=run,
                    event_type="oversized",
                    detail={"value": "x" * (9 * 1024)},
                )

    def test_model_rejects_illegal_phase_permissions(self):
        with TemporaryDirectory() as tmp:
            run = self._run(Path(tmp))
            run.write_enabled = True
            with self.assertRaises(ValidationError):
                run.full_clean()

    def test_lease_conflict_heartbeat_and_release(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = self._run(root / "a")
            run_b = self._run(root / "b")
            acquire_runner_lease(run=run_a, owner_token="owner-a", lock_path=root / "global.lock")
            with self.assertRaises(RunnerLeaseError):
                acquire_runner_lease(run=run_b, owner_token="owner-b", lock_path=root / "other.lock")
            heartbeat_runner_lease(run=run_a, owner_token="owner-a")
            lock = HistoricalBatchLock.objects.get(key="global")
            self.assertEqual(lock.owner_token_sha256, hashlib.sha256(b"owner-a").hexdigest())
            release_runner_lease(run=run_a, owner_token="owner-a")
            lock.refresh_from_db()
            self.assertIsNone(lock.locked_by_run_id)

    def test_status_requires_matching_unexpired_lease_to_be_healthy(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            self.assertFalse(runner_status_payload(run)["healthy"])
            lease = acquire_runner_lease(run=run, owner_token="owner", lock_path=root / "global.lock")
            run.refresh_from_db()
            payload = runner_status_payload(run)
            self.assertTrue(payload["lock_matches"])
            self.assertTrue(payload["healthy"])
            release_runner_lease(run=run, owner_token="owner")
            lease.close()

    def test_wrong_owner_cannot_heartbeat_or_release(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            acquire_runner_lease(run=run, owner_token="owner", lock_path=root / "global.lock")
            with self.assertRaises(RunnerLeaseError):
                heartbeat_runner_lease(run=run, owner_token="wrong")
            with self.assertRaises(RunnerLeaseError):
                release_runner_lease(run=run, owner_token="wrong")

    def test_expired_different_owner_requires_audited_takeover(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_a = self._run(root / "a")
            run_b = self._run(root / "b")
            acquire_runner_lease(run=run_a, owner_token="owner-a", lock_path=root / "global.lock")
            HistoricalBatchLock.objects.filter(key="global").update(
                lease_expires_at=timezone.now() - timedelta(seconds=1)
            )
            with self.assertRaisesMessage(RunnerLeaseError, "expired"):
                acquire_runner_lease(run=run_b, owner_token="owner-b", lock_path=root / "other.lock")
            release_runner_lease(run=run_a, owner_token="owner-a")

    def test_file_lock_conflict_releases_database_lease(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            lock_path = root / "global.lock"
            with lock_path.open("a+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(RunnerLeaseError):
                    acquire_runner_lease(run=run, owner_token="owner", lock_path=lock_path)
            lock = HistoricalBatchLock.objects.get(key="global")
            self.assertIsNone(lock.locked_by_run_id)
            run.refresh_from_db()
            self.assertEqual(run.status, HistoricalBatchRunStatus.FAILED)
            self.assertIsNone(run.lease_expires_at)
            self.assertIn("file lock is held", run.error_message)
            self.assertTrue(run.events.filter(event_type="lease_failed").exists())

    def test_same_owner_file_lock_conflict_does_not_fail_the_active_run(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            lock_path = root / "global.lock"
            lease = acquire_runner_lease(run=run, owner_token="owner", lock_path=lock_path)
            try:
                with self.assertRaises(RunnerLeaseError):
                    acquire_runner_lease(run=run, owner_token="owner", lock_path=lock_path)
                run.refresh_from_db()
                lock = HistoricalBatchLock.objects.get(key="global")
                self.assertEqual(run.status, HistoricalBatchRunStatus.RUNNING)
                self.assertEqual(lock.locked_by_run_id, run.pk)
            finally:
                release_runner_lease(run=run, owner_token="owner")
                lease.close()

    def test_pause_and_resume_preserve_draft_visibility(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            acquire_runner_lease(run=run, owner_token="owner", lock_path=root / "global.lock")
            request_runner_pause(run=run, requested_by="tester", reason="migration")
            run.refresh_from_db()
            self.assertIsNotNone(run.pause_requested_at)
            run.status = HistoricalBatchRunStatus.PAUSED
            run.paused_at = timezone.now()
            run.save(update_fields={"status", "paused_at"})
            resume_runner_run(run=run, owner_token="owner")
            run.refresh_from_db()
            self.assertEqual(run.status, HistoricalBatchRunStatus.PLANNED)
            self.assertFalse(RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED).exists())

    def test_pause_refreshes_and_rejects_terminal_state(self):
        with TemporaryDirectory() as tmp:
            run = self._run(Path(tmp))
            stale = HistoricalBatchRun.objects.get(pk=run.pk)
            HistoricalBatchRun.objects.filter(pk=run.pk).update(status=HistoricalBatchRunStatus.COMPLETED)
            with self.assertRaisesMessage(RunnerStateError, "terminal"):
                request_runner_pause(run=stale, requested_by="deploy", reason="migration")

    def test_resume_rejects_a_different_owner_token(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            acquire_runner_lease(run=run, owner_token="owner", lock_path=root / "global.lock")
            run.status = HistoricalBatchRunStatus.PAUSED
            run.save(update_fields={"status"})
            with self.assertRaisesMessage(RunnerStateError, "owner token"):
                resume_runner_run(run=run, owner_token="wrong")

    def test_takeover_requires_expired_lease_no_container_no_activity_and_matching_state(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root)
            acquire_runner_lease(run=run, owner_token="owner", lock_path=root / "global.lock")
            HistoricalBatchLock.objects.filter(key="global").update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            for kwargs in (
                {"container_absent": False, "no_active_db_session": True, "checkpoint_matches": True},
                {"container_absent": True, "no_active_db_session": False, "checkpoint_matches": True},
                {"container_absent": True, "no_active_db_session": True, "checkpoint_matches": False},
            ):
                with self.assertRaises(RunnerLeaseError):
                    takeover_runner_lease(
                        run=run,
                        new_owner_token="new-owner",
                        actor="operator",
                        reason="stale",
                        **kwargs,
                    )
            takeover_runner_lease(
                run=run,
                new_owner_token="new-owner",
                actor="operator",
                reason="stale",
                container_absent=True,
                no_active_db_session=True,
                checkpoint_matches=True,
            )
            lock = HistoricalBatchLock.objects.get(key="global")
            self.assertEqual(lock.owner_token_sha256, hashlib.sha256(b"new-owner").hexdigest())
            self.assertTrue(run.events.filter(event_type="takeover").exists())


class HistoricalBatchRunnerExecutionTests(TestCase):
    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
    )
    def test_resume_skips_checkpointed_step_after_later_failure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_root = root / "artifacts"
            tool_root = root / "tools"
            artifact_root.mkdir()
            tool_root.mkdir()
            counter = artifact_root / "counter.txt"
            final_output = artifact_root / "final.txt"
            failure_marker = artifact_root / "failed-once.marker"
            first_tool = tool_root / "count_once.py"
            second_tool = tool_root / "fail_once.py"
            first_tool.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "path = Path(sys.argv[1])\n"
                "value = int(path.read_text() if path.exists() else '0') + 1\n"
                "path.write_text(str(value), encoding='utf-8')\n",
                encoding="utf-8",
            )
            second_tool.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "marker, output = map(Path, sys.argv[1:3])\n"
                "if not marker.exists():\n"
                "    marker.write_text('failed', encoding='utf-8')\n"
                "    print('retry-safe diagnostic', file=sys.stderr)\n"
                "    raise SystemExit(9)\n"
                "output.write_text('done', encoding='utf-8')\n",
                encoding="utf-8",
            )
            plan = {
                "schema_version": "1.0",
                "batch_id": "2016-2025-batch-006-resume",
                "phase": "verify",
                "network_enabled": False,
                "write_enabled": False,
                "image_id": "sha256:" + "1" * 64,
                "image_revision": "a" * 40,
                "artifact_root": str(artifact_root),
                "tool_root": str(tool_root),
                "tool_manifest": {
                    "count_once.py": hashlib.sha256(first_tool.read_bytes()).hexdigest(),
                    "fail_once.py": hashlib.sha256(second_tool.read_bytes()).hexdigest(),
                },
                "steps": [
                    {
                        "id": "count-once",
                        "kind": "python_tool",
                        "argv": ["python", str(first_tool), str(counter)],
                        "inputs": [],
                        "outputs": [str(counter)],
                    },
                    {
                        "id": "fail-once",
                        "kind": "python_tool",
                        "argv": ["python", str(second_tool), str(failure_marker), str(final_output)],
                        "inputs": [],
                        "outputs": [str(final_output)],
                    },
                ],
            }
            plan_path = artifact_root / "runner-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            run = create_runner_run(
                batch_id=plan["batch_id"],
                phase=plan["phase"],
                artifact_root=str(artifact_root),
                plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                image_id=plan["image_id"],
                image_revision=plan["image_revision"],
            )
            with override_settings(HISTORICAL_RUNNER_TOOL_ROOT=str(tool_root)):
                with self.assertRaisesMessage(RunnerStateError, "fail-once"):
                    execute_runner_plan(
                        run=run,
                        plan_path=plan_path,
                        owner_token="owner",
                        lock_path=artifact_root / ".runner.lock",
                    )
                run.refresh_from_db()
                self.assertIn("retry-safe diagnostic", run.error_message)
                execute_runner_plan(
                    run=run,
                    plan_path=plan_path,
                    owner_token="owner",
                    lock_path=artifact_root / ".runner.lock",
                )
            run.refresh_from_db()
            self.assertEqual(run.status, HistoricalBatchRunStatus.COMPLETED)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1")
            self.assertEqual(final_output.read_text(encoding="utf-8"), "done")

    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
    )
    def test_runner_rejects_symlinked_artifact_lock(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_root = root / "artifacts"
            tool_root = root / "tools"
            artifact_root.mkdir()
            tool_root.mkdir()
            outside_lock = root / "outside.lock"
            (artifact_root / ".runner.lock").symlink_to(outside_lock)
            tool = tool_root / "noop.py"
            tool.write_text("print('ok')\n", encoding="utf-8")
            plan = {
                "schema_version": "1.0",
                "batch_id": "2016-2025-batch-006",
                "phase": "verify",
                "network_enabled": False,
                "write_enabled": False,
                "image_id": "sha256:" + "1" * 64,
                "image_revision": "a" * 40,
                "artifact_root": str(artifact_root),
                "tool_root": str(tool_root),
                "tool_manifest": {"noop.py": hashlib.sha256(tool.read_bytes()).hexdigest()},
                "steps": [
                    {
                        "id": "noop",
                        "kind": "python_tool",
                        "argv": ["python", str(tool)],
                        "inputs": [],
                        "outputs": [],
                    }
                ],
            }
            plan_path = artifact_root / "runner-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            run = create_runner_run(
                batch_id=plan["batch_id"],
                phase=plan["phase"],
                artifact_root=str(artifact_root),
                plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                image_id=plan["image_id"],
                image_revision=plan["image_revision"],
            )
            with override_settings(HISTORICAL_RUNNER_TOOL_ROOT=str(tool_root)):
                with self.assertRaisesMessage(RunnerPlanError, "fixed artifact-root"):
                    execute_runner_plan(
                        run=run,
                        plan_path=plan_path,
                        owner_token="owner",
                        lock_path=artifact_root / ".runner.lock",
                    )

    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
    )
    def test_large_output_executes_without_pipe_deadlock_and_checkpoints(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_root = root / "artifacts"
            tool_root = root / "tools"
            artifact_root.mkdir()
            tool_root.mkdir()
            output_path = artifact_root / "result.json"
            tool_path = tool_root / "large_output.py"
            tool_path.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "print('赛' * 100000)\n"
                "Path(sys.argv[1]).write_text('ok\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            plan = {
                "schema_version": "1.0",
                "batch_id": "2016-2025-batch-006",
                "phase": "verify",
                "network_enabled": False,
                "write_enabled": False,
                "image_id": "sha256:" + "1" * 64,
                "image_revision": "a" * 40,
                "artifact_root": str(artifact_root),
                "tool_root": str(tool_root),
                "tool_manifest": {
                    "large_output.py": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
                },
                "steps": [
                    {
                        "id": "large-output",
                        "kind": "python_tool",
                        "argv": ["python", str(tool_path), str(output_path)],
                        "inputs": [],
                        "outputs": [str(output_path)],
                    }
                ],
            }
            plan_path = artifact_root / "runner-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            run = create_runner_run(
                batch_id=plan["batch_id"],
                phase=plan["phase"],
                artifact_root=str(artifact_root),
                plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                image_id=plan["image_id"],
                image_revision=plan["image_revision"],
            )
            with self.settings(HISTORICAL_RUNNER_TOOL_ROOT=str(tool_root)):
                real_popen = subprocess.Popen
                observed = {}

                def capture_popen(*args, **kwargs):
                    observed.update(kwargs)
                    return real_popen(*args, **kwargs)

                with patch("stable.services.historical_batch_runner.subprocess.Popen", side_effect=capture_popen):
                    execute_runner_plan(
                        run=run,
                        plan_path=plan_path,
                        owner_token="owner-token",
                        lock_path=artifact_root / ".runner.lock",
                        secret_values=["owner-token"],
                    )
            run.refresh_from_db()
            self.assertEqual(run.status, HistoricalBatchRunStatus.COMPLETED)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "ok\n")
            self.assertLessEqual(
                len(run.checkpoint["completed_steps"][0]["stdout_summary"].encode("utf-8")),
                3 * 1024,
            )
            self.assertGreater((artifact_root / "runner-logs" / "large-output.stdout.log").stat().st_size, 100000)
            self.assertIsNot(observed["stdout"], subprocess.PIPE)
            self.assertIsNot(observed["stderr"], subprocess.PIPE)
            self.assertIsNone(HistoricalBatchLock.objects.get(key="global").locked_by_run_id)


class HistoricalBatchRunnerOperationsContractTests(SimpleTestCase):
    root = Path(__file__).resolve().parents[2]

    def _read(self, relative: str) -> str:
        path = self.root / relative
        self.assertTrue(path.is_file(), f"missing operations script: {relative}")
        return path.read_text(encoding="utf-8")

    def test_runner_script_enforces_identity_resources_mounts_and_phase_env(self):
        text = self._read("deploy/historical_runner.sh")
        for token in ("--cpus", "--memory", "--pids-limit", "--log-opt", "/app/historical-runtime", "/run/secrets/historical-owner-token"):
            self.assertIn(token, text)
        self.assertNotIn(":/app/runtime", text)
        self.assertIn("HISTORICAL_RUNNER_RUN_ID", text)
        self.assertIn("readlink -f", text)
        self.assertIn("runner env filename must match run id and phase", text)
        self.assertIn("POSTGRES_USER=$CONTROL_ROLE", text)
        self.assertIn("HISTORICAL_RUNNER_APPLY_ROLE", text)
        self.assertIn("duplicate runner env key", text)
        self.assertIn('--network "$INTERNAL_NETWORK"', text)
        self.assertNotIn("--network none", text)
        self.assertIn("runner DB_ENGINE must be postgres", text)
        self.assertIn("grep -Fqx", text)

    def test_runner_takeover_verifies_container_absence_and_mounts_fixed_checkpoint(self):
        text = self._read("deploy/historical_runner.sh")
        self.assertIn("takeover_runner", text)
        self.assertIn("old runner container still exists", text)
        self.assertIn("manage_historical_batch_runner takeover", text)
        self.assertIn("--state-file /app/historical-runtime/runner-state.json", text)
        self.assertIn("--container-absent", text)
        self.assertIn("HISTORICAL_RUNNER_TAKEOVER_ACTOR", text)
        self.assertIn("HISTORICAL_RUNNER_TAKEOVER_REASON", text)

    def test_provisioning_never_recreates_database_redis_or_shared_network(self):
        text = self._read("deploy/provision_historical_runner.sh")
        for forbidden in ("compose down", "docker rm", "docker volume rm", "umanewsbot-db-1 rm", "umanewsbot-redis-1 rm"):
            self.assertNotIn(forbidden, text)
        self.assertIn("historical_runner_control", text)
        self.assertIn("NOSUPERUSER", text)
        self.assertIn("REVOKE ALL ON SCHEMA public", text)
        self.assertIn("has_schema_privilege", text)
        self.assertIn("unexpected business-table write privilege", text)
        self.assertNotIn('-v control_password="$password"', text)

    def test_ordinary_deploy_is_no_deps_and_never_bootstraps(self):
        for relative in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh", "deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            text = self._read(relative)
            self.assertIn("historical_runner_preflight", text)
            self.assertIn("wait_for_celery_drain", text)
            self.assertIn("--no-deps", text)
            self.assertNotIn("bootstrap_infrastructure", text)

    def test_celery_drain_requires_worker_response_and_empty_active_reserved(self):
        text = self._read("deploy/wait_for_celery_drain.sh")
        for token in ("inspect.ping", "inspect.active", "inspect.reserved", "beat remains stopped"):
            self.assertIn(token, text)

    def test_first_migration_preflight_is_explicit_and_fail_closed(self):
        text = self._read("deploy/historical_runner_preflight.sh")
        self.assertIn("--initial-install", text)
        self.assertIn("required existing service is not healthy", text)
        for token in ("historical-runner", "historical_runner_secrets", "HistoricalBatchRun"):
            self.assertIn(token, text)

    def test_isolation_smoke_checks_business_write_network_and_resources(self):
        text = self._read("deploy/historical_runner_smoke.sh")
        for token in (
            "stable_raceevent",
            "1.1.1.1",
            "NanoCpus",
            "Memory",
            "PidsLimit",
            "ReadonlyRootfs",
            "CapDrop",
            "no-new-privileges",
            "max-size",
            "egress network",
            "EXPECTED_CONTROL_ROLE",
        ):
            self.assertIn(token, text)

    def test_read_only_smoke_probe_is_bounded_and_writes_inside_artifact(self):
        probe = self.root / "runtime/tools/historical_runner_smoke_probe.py"
        self.assertTrue(probe.is_file())
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "probe" / "done.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(probe),
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                    "--sleep-seconds",
                    "0",
                    "--label",
                    "runner-smoke",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"label": "runner-smoke", "status": "ok"})
            self.assertIn("runner-smoke", result.stdout)

            escaped = subprocess.run(
                [
                    sys.executable,
                    str(probe),
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(root.parent / "escaped.json"),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(escaped.returncode, 0)

            too_long = subprocess.run(
                [
                    sys.executable,
                    str(probe),
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                    "--sleep-seconds",
                    "301",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(too_long.returncode, 0)
