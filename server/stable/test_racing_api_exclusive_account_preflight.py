from __future__ import annotations

import hashlib
import io
import json
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from django.core.management import call_command

from stable.services.racing_api_exclusive_account_preflight import (
    PROOF_SCHEMA,
    RacingApiExclusivePreflightError,
    THE_RACING_API_SOURCE,
    collect_celery_idle_snapshot,
    generate_exclusive_account_proof,
)


@override_settings(
    RACE_LIVE_SCHEDULER_ENABLED=False,
    RACE_LIVE_MONITOR_ENABLED=False,
    RACE_LIVE_ENABLED_REGIONS=(),
    RACE_DATA_SYNC_ENABLED=False,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
    RACE_DATA_SYNC_ALLOW_NETWORK=False,
)
class RacingApiExclusiveAccountPreflightTests(TestCase):
    def _host_evidence(
        self,
        root: Path,
        *,
        now: datetime,
        host_role: str,
        host_name: str,
        matches: list[dict] | None = None,
    ) -> tuple[Path, str]:
        payload = {
            "schema_version": "racing-api-host-process-preflight.v2",
            "captured_at": now.isoformat().replace("+00:00", "Z"),
            "host": host_name,
            "host_role": host_role,
            "scope_id": "batch-1",
            "scope_manifest_sha256": "a" * 64,
            "host_ps_available": True,
            "docker_ps_available": True,
            "containers": [{"id": "abcdef123456", "name": "umanews-web"}],
            "matching_processes": matches or [],
            "network_requests": 0,
            "database_writes": 0,
        }
        path = root / f"{host_role}-host-evidence.json"
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _celery(**_kwargs):
        return {
            "workers": ["celery@worker"],
            "expected_workers": ["worker"],
            "active_count": 0,
            "reserved_count": 0,
            "scheduled_count": 0,
            "active_confirm_count": 0,
        }

    @staticmethod
    def _queues():
        return {"celery": 0, "race_live": 0, "race_sync_v2": 0}

    def _generate(
        self,
        *,
        root: Path,
        now: datetime,
        runner_host_path: Path,
        runner_host_sha: str,
        production_host_path: Path,
        production_host_sha: str,
    ):
        return generate_exclusive_account_proof(
            credential_alias="tra-primary",
            scope_id="batch-1",
            scope_manifest_sha256="a" * 64,
            runner_host_evidence_path=runner_host_path,
            runner_host_evidence_sha256=runner_host_sha,
            production_host_evidence_path=production_host_path,
            production_host_evidence_sha256=production_host_sha,
            expected_worker_nodes=["worker"],
            reserved_by="owner",
            decision_source_reference="owner-g3-batch-1",
            output_file=root / "exclusive-proof.json",
            valid_minutes=15,
            now=now,
            celery_collector=self._celery,
            queue_collector=self._queues,
        )

    def test_generates_private_short_lived_proof_from_closed_live_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            runner_path, runner_sha = self._host_evidence(
                root, now=now, host_role="runner", host_name="mac-runner"
            )
            production_path, production_sha = self._host_evidence(
                root, now=now, host_role="production", host_name="production-host"
            )
            proof = self._generate(
                root=root,
                now=now + timedelta(seconds=10),
                runner_host_path=runner_path,
                runner_host_sha=runner_sha,
                production_host_path=production_path,
                production_host_sha=production_sha,
            )
            output = root / "exclusive-proof.json"
            self.assertEqual(proof["checks"]["other_backfill_processes"], 0)
            self.assertEqual(proof["schema_version"], PROOF_SCHEMA)
            self.assertEqual(THE_RACING_API_SOURCE, "the_racing_api")
            self.assertEqual(
                [row["role"] for row in proof["evidence"]["host_processes"]],
                ["runner", "production"],
            )
            self.assertEqual(proof["database_writes"], 0)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(
                datetime.fromisoformat(proof["valid_until"].replace("Z", "+00:00"))
                - datetime.fromisoformat(proof["observed_at"].replace("Z", "+00:00")),
                timedelta(minutes=15),
            )
            self.assertEqual(len(hashlib.sha256(output.read_bytes()).hexdigest()), 64)

    def test_management_command_writes_only_redacted_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_evidence = root / "runner-host-evidence.json"
            runner_evidence.write_text("{}\n", encoding="utf-8")
            runner_evidence.chmod(0o600)
            production_evidence = root / "production-host-evidence.json"
            production_evidence.write_text("{}\n", encoding="utf-8")
            production_evidence.chmod(0o600)
            output = root / "exclusive-proof.json"

            def fake_generate(**kwargs):
                kwargs["output_file"].write_text("{}\n", encoding="utf-8")
                kwargs["output_file"].chmod(0o600)
                return {
                    "status": "approved",
                    "scope_id": kwargs["scope_id"],
                    "valid_until": "2026-08-30T00:15:00Z",
                }

            stdout = io.StringIO()
            with patch(
                "stable.management.commands.generate_racing_api_exclusive_account_proof.generate_exclusive_account_proof",
                side_effect=fake_generate,
            ) as mocked:
                call_command(
                    "generate_racing_api_exclusive_account_proof",
                    credential_alias="tra-primary",
                    scope_id="batch-1",
                    scope_manifest_sha256="a" * 64,
                    runner_host_evidence=runner_evidence,
                    runner_host_evidence_sha256="b" * 64,
                    production_host_evidence=production_evidence,
                    production_host_evidence_sha256="c" * 64,
                    expected_worker_node=["worker"],
                    reserved_by="owner",
                    decision_source_reference="owner-g3-batch-1",
                    valid_minutes=15,
                    output_file=output,
                    stdout=stdout,
                )
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["status"], "approved")
            self.assertEqual(summary["scope_id"], "batch-1")
            self.assertEqual(summary["database_writes"], 0)
            self.assertNotIn("credential_alias", summary)
            self.assertEqual(mocked.call_args.kwargs["expected_worker_nodes"], ["worker"])

    @override_settings(RACE_DATA_SYNC_ALLOW_NETWORK=True)
    def test_network_flag_fails_closed_without_writing_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            runner_path, runner_sha = self._host_evidence(
                root, now=now, host_role="runner", host_name="mac-runner"
            )
            production_path, production_sha = self._host_evidence(
                root, now=now, host_role="production", host_name="production-host"
            )
            with self.assertRaisesRegex(
                RacingApiExclusivePreflightError, "preflight is not closed"
            ):
                self._generate(
                    root=root,
                    now=now,
                    runner_host_path=runner_path,
                    runner_host_sha=runner_sha,
                    production_host_path=production_path,
                    production_host_sha=production_sha,
                )
            self.assertFalse((root / "exclusive-proof.json").exists())

    def test_host_process_match_or_stale_capture_fails_closed(self):
        for case, captured_at, matches in (
            (
                "matching_process",
                datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
                [
                    {
                        "source": "host",
                        "pid": 123,
                        "marker": "racing_api_horse_export.py",
                        "command_sha256": "b" * 64,
                    }
                ],
            ),
            (
                "stale",
                datetime(2026, 8, 29, 23, 55, tzinfo=timezone.utc),
                [],
            ),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                runner_path, runner_sha = self._host_evidence(
                    root,
                    now=captured_at,
                    host_role="runner",
                    host_name="mac-runner",
                    matches=matches,
                )
                production_path, production_sha = self._host_evidence(
                    root,
                    now=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
                    host_role="production",
                    host_name="production-host",
                )
                with self.assertRaisesRegex(
                    RacingApiExclusivePreflightError, "not clean and fresh"
                ):
                    self._generate(
                        root=root,
                        now=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
                        runner_host_path=runner_path,
                        runner_host_sha=runner_sha,
                        production_host_path=production_path,
                        production_host_sha=production_sha,
                    )

    def test_runner_and_production_evidence_must_cover_distinct_hosts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)
            runner_path, runner_sha = self._host_evidence(
                root, now=now, host_role="runner", host_name="same-host"
            )
            production_path, production_sha = self._host_evidence(
                root, now=now, host_role="production", host_name="same-host"
            )
            with self.assertRaisesRegex(
                RacingApiExclusivePreflightError, "must cover distinct hosts"
            ):
                self._generate(
                    root=root,
                    now=now,
                    runner_host_path=runner_path,
                    runner_host_sha=runner_sha,
                    production_host_path=production_path,
                    production_host_sha=production_sha,
                )

    def test_celery_snapshot_requires_same_workers_and_two_empty_active_reads(self):
        inspector = Mock()
        inspector.ping.return_value = {"celery@worker": {"ok": "pong"}}
        inspector.active.side_effect = [
            {"celery@worker": []},
            {"celery@worker": []},
        ]
        inspector.reserved.return_value = {"celery@worker": []}
        inspector.scheduled.return_value = {"celery@worker": []}
        with patch("app.celery.app.control.inspect", return_value=inspector):
            snapshot = collect_celery_idle_snapshot(expected_worker_nodes=["worker"])
        self.assertEqual(snapshot["workers"], ["celery@worker"])
        self.assertEqual(snapshot["active_confirm_count"], 0)

        inspector = Mock()
        inspector.ping.return_value = {"celery@worker": {"ok": "pong"}}
        inspector.active.side_effect = [
            {"celery@worker": []},
            {"celery@worker": []},
        ]
        inspector.reserved.return_value = {"celery@worker": []}
        inspector.scheduled.return_value = {"other@worker": []}
        with (
            patch("app.celery.app.control.inspect", return_value=inspector),
            self.assertRaisesRegex(
                RacingApiExclusivePreflightError, "partial snapshot"
            ),
        ):
            collect_celery_idle_snapshot(expected_worker_nodes=["worker"])


if __name__ == "__main__":
    import unittest

    unittest.main()
