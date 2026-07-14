from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable.management.commands.orchestrate_race_event_crawl import Command
from stable.models import TaskExecutionLog, TaskStatus
from stable.services import race_event_crawl_orchestration as orchestration


class HistoricalRaceNetworkLoggingTests(TestCase):
    def _state(self):
        return SimpleNamespace(
            run_id="historical-1984-sample",
            run_dir="/tmp/historical-1984-sample",
            stage="plan",
            artifacts={"expected_target_count": 45},
        )

    def test_prepare_records_safe_historical_network_run_identity_and_success(self):
        command = Command()
        plan = {
            "historical_inventory_sha256": "a" * 64,
            "allow_network": True,
            "regions": [{"region": "japan"}, {"region": "france"}],
        }
        state = self._state()

        with patch.object(orchestration, "prepare_adapters", return_value=[{"status": "succeeded"}]):
            result = command._prepare_with_historical_log(plan, state, resume=False)

        log = TaskExecutionLog.objects.get(task_name="historical_race_network_prepare")
        self.assertEqual(result, [{"status": "succeeded"}])
        self.assertEqual(log.status, TaskStatus.SUCCESS)
        self.assertEqual(log.payload["inventory_sha256"], "a" * 64)
        self.assertEqual(log.payload["run_id"], "historical-1984-sample")
        self.assertEqual(log.payload["target_count"], 45)
        self.assertEqual(log.payload["regions"], ["france", "japan"])
        self.assertNotIn("plan", log.payload)
        self.assertIsNotNone(log.finished_at)

    def test_resume_failure_is_logged_without_secret_or_full_document(self):
        command = Command()
        plan = {
            "historical_inventory_sha256": "b" * 64,
            "allow_network": True,
            "regions": [{"region": "united_kingdom"}],
        }
        state = self._state()
        error = RuntimeError("API_KEY=super-secret <html>full upstream response</html>")

        with patch.object(orchestration, "prepare_adapters", side_effect=error):
            with self.assertRaises(RuntimeError):
                command._prepare_with_historical_log(plan, state, resume=True)

        log = TaskExecutionLog.objects.get(task_name="historical_race_network_resume")
        self.assertEqual(log.status, TaskStatus.FAILED)
        self.assertNotIn("super-secret", log.detail)
        self.assertNotIn("<html>", log.detail)
        self.assertLessEqual(len(log.detail), 2000)
        self.assertTrue(log.payload["resume"])

    def test_non_historical_prepare_does_not_create_historical_log(self):
        command = Command()
        with patch.object(orchestration, "prepare_adapters", return_value=[]):
            command._prepare_with_historical_log(
                {"allow_network": True, "regions": []},
                self._state(),
                resume=False,
            )

        self.assertFalse(TaskExecutionLog.objects.exists())

    @override_settings(
        POSTGRES_APPLICATION_NAME="umanews-historical-runner:batch006:crawl"
    )
    def test_runner_prepare_uses_runner_audit_without_business_task_log(self):
        command = Command()
        plan = {
            "historical_inventory_sha256": "c" * 64,
            "allow_network": True,
            "regions": [{"region": "united_states"}],
        }

        with patch.object(orchestration, "prepare_adapters", return_value=[{"status": "succeeded"}]):
            result = command._prepare_with_historical_log(plan, self._state(), resume=False)

        self.assertEqual(result, [{"status": "succeeded"}])
        self.assertFalse(TaskExecutionLog.objects.exists())
