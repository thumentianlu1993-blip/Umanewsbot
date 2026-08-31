from __future__ import annotations

import json
import os
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import ManagementUtility, call_command
from django.core.management.base import CommandError
from django.test import TestCase

from stable.test_racing_api_horse_staging import RacingApiHorseStagingTests


class StageRacingApiTargetedBatchCommandTests(TestCase):
    def _materialization(self, root: Path) -> tuple[Path, str]:
        builder = RacingApiHorseStagingTests(
            methodName="test_loader_binds_complete_manifest_and_rejects_extra_files"
        )
        return builder._materialization(root)

    def test_help_discovers_batch_staging_command(self):
        stdout = StringIO()

        with redirect_stdout(stdout):
            ManagementUtility(
                ["manage.py", "help", "stage_racing_api_targeted_batch"]
            ).execute()

        output = stdout.getvalue()
        self.assertIn("stage_racing_api_targeted_batch", output)
        self.assertIn("--materialization-dir", output)
        self.assertIn("--approved-manifest-sha256", output)

    def test_allow_write_without_apply_is_rejected_before_service_call(self):
        with mock.patch(
            "stable.management.commands.stage_racing_api_targeted_batch."
            "dry_run_targeted_materialization"
        ) as dry_run, self.assertRaisesRegex(
            CommandError,
            "--allow-write 只能与 --apply 同时使用",
        ):
            call_command(
                "stage_racing_api_targeted_batch",
                materialization_dir=Path("/private/not-read"),
                approved_manifest_sha256="a" * 64,
                allow_write=True,
                no_color=True,
            )

        dry_run.assert_not_called()

    def test_normal_dry_run_prints_zero_write_batch_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._materialization(Path(temporary))
            stdout = StringIO()
            sensitive_username = "do-not-print-username"
            sensitive_password = "do-not-print-password"
            with mock.patch.dict(
                os.environ,
                {
                    "RACING_API_USERNAME": sensitive_username,
                    "RACING_API_PASSWORD": sensitive_password,
                },
                clear=False,
            ):
                call_command(
                    "stage_racing_api_targeted_batch",
                    materialization_dir=root,
                    approved_manifest_sha256=manifest_sha,
                    stdout=stdout,
                    no_color=True,
                )

            output = stdout.getvalue()
            report = json.loads(output)
            self.assertEqual(report["status"], "batch_dry_run")
            self.assertEqual(report["database_writes"], 0)
            self.assertEqual(report["run_count"], 2)
            self.assertEqual(report["unique_target_horse_count"], 2)
            self.assertEqual(report["scope_stable_ids"], ["hrs_1024", "hrs_2048"])
            self.assertEqual(report["scope_guard"]["out_of_scope_horse_writes"], 0)
            self.assertEqual(report["unique_planned_rows"]["external_horses"], 2)
            self.assertEqual(report["unique_planned_rows"]["external_races"], 1)
            self.assertEqual(report["deduplicated_operations"]["external_races"], 1)
            self.assertEqual(report["action_totals"], {
                "create": 12,
                "update": 0,
                "skip": 1,
                "conflict": 0,
            })
            self.assertNotIn(str(root), output)
            self.assertNotIn(sensitive_username, output)
            self.assertNotIn(sensitive_password, output)
            self.assertNotIn("artifact_root", output)

    def test_apply_defaults_fail_closed_before_artifact_read(self):
        with mock.patch.dict(
            os.environ,
            {"RACING_API_STAGING_WRITE_ENABLED": "false"},
            clear=False,
        ), self.assertRaisesRegex(CommandError, "write gate"):
            call_command(
                "stage_racing_api_targeted_batch",
                materialization_dir=Path("/private/not-read"),
                approved_manifest_sha256="a" * 64,
                apply=True,
                allow_write=True,
                no_color=True,
            )

    def test_env_example_keeps_staging_writes_disabled(self):
        env_example = Path(__file__).resolve().parents[2] / ".env.example"

        self.assertIn(
            "RACING_API_STAGING_WRITE_ENABLED=false",
            env_example.read_text(encoding="utf-8").splitlines(),
        )
