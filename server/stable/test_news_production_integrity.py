from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import (
    CrawlJob,
    NewsSource,
    NotificationChannel,
    NotificationLog,
    NotificationStatus,
    NotificationType,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowStatus,
    TaskExecutionLog,
    TaskStatus,
)


def _activity(*, active_source_ids=(), available=True):
    return {
        "available": available,
        "active_source_ids": list(active_source_ids),
        "active_tasks": [],
        "reserved_tasks": [],
        "errors": [],
    }


class CrawlTerminalStateTests(TestCase):
    def setUp(self):
        self.source = NewsSource.objects.create(
            name="测试来源",
            homepage_url="https://example.com/",
            feed_url="https://example.com/feed",
            source_site="",
            source_mode="",
        )

    def test_finish_crawl_job_claims_started_terminal_once(self):
        from stable.tasks import _finish_crawl_job

        job = CrawlJob.objects.create(source=self.source, status=TaskStatus.STARTED)

        claimed = _finish_crawl_job(job, success_count=2, fail_count=3)

        self.assertTrue(claimed)
        job.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertEqual(job.success_count, 2)
        self.assertEqual(self.source.last_crawl_status, TaskStatus.SUCCESS)

    def test_late_finish_cannot_overwrite_reconciled_terminal(self):
        from stable.tasks import _finish_crawl_job

        job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.FAILED,
            finished_at=timezone.now(),
            error_message="stale_reconciled",
        )

        claimed = _finish_crawl_job(job, success_count=8)

        self.assertFalse(claimed)
        job.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertEqual(job.success_count, 0)
        self.assertEqual(self.source.last_crawl_status, "")
        self.assertTrue(
            TaskExecutionLog.objects.filter(
                task_name="crawl_job_terminal_state",
                detail="terminal_state_already_claimed",
            ).exists()
        )


@override_settings(CRAWL_JOB_STALE_MINUTES=60)
class StaleCrawlManifestTests(TestCase):
    def setUp(self):
        self.source = NewsSource.objects.create(
            name="遗留来源",
            homepage_url="https://example.org/",
            feed_url="https://example.org/feed",
            source_site="",
            source_mode="",
        )

    def test_dry_run_manifest_is_read_only_and_marks_active_source_skip(self):
        from stable.services.news_production_integrity import build_stale_crawl_manifest

        now = timezone.now()
        old_job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=90),
        )
        recent_job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=10),
        )
        before = list(CrawlJob.objects.values_list("id", "status", "finished_at"))

        manifest = build_stale_crawl_manifest(
            now=now,
            stale_minutes=60,
            activity_evidence=_activity(active_source_ids=[self.source.id]),
        )

        self.assertEqual(before, list(CrawlJob.objects.values_list("id", "status", "finished_at")))
        self.assertEqual([row["job_id"] for row in manifest["jobs"]], [old_job.id])
        self.assertEqual(manifest["jobs"][0]["recommended_action"], "skip_active_evidence")
        self.assertNotIn(recent_job.id, [row["job_id"] for row in manifest["jobs"]])
        self.assertEqual(len(manifest["manifest_sha256"]), 64)

    def test_apply_updates_only_unchanged_inactive_manifest_rows_and_is_idempotent(self):
        from stable.services.news_production_integrity import (
            apply_stale_crawl_manifest,
            build_stale_crawl_manifest,
        )

        now = timezone.now()
        first = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=120),
        )
        second = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=110),
        )
        manifest = build_stale_crawl_manifest(
            now=now,
            stale_minutes=60,
            activity_evidence=_activity(),
        )
        second.status = TaskStatus.SUCCESS
        second.finished_at = now
        second.save(update_fields=["status", "finished_at", "updated_at"])

        result = apply_stale_crawl_manifest(
            manifest,
            expected_sha256=manifest["manifest_sha256"],
            activity_evidence=_activity(),
            now=now + timedelta(minutes=1),
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, TaskStatus.FAILED)
        self.assertIn("stale_reconciled", first.error_message)
        self.assertEqual(second.status, TaskStatus.SUCCESS)
        self.assertEqual(result["updated_ids"], [first.id])
        self.assertEqual(result["status_drift_ids"], [second.id])

        repeated = apply_stale_crawl_manifest(
            manifest,
            expected_sha256=manifest["manifest_sha256"],
            activity_evidence=_activity(),
            now=now + timedelta(minutes=2),
        )
        self.assertEqual(repeated["updated_ids"], [])

    def test_manifest_skips_only_production_window_with_live_lease(self):
        from stable.services.news_production_integrity import build_stale_crawl_manifest

        now = timezone.now()
        job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=90),
        )
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            source=self.source,
            scope_key=f"source:{self.source.id}",
            window_start=now - timedelta(minutes=30),
            window_end=now,
            status=ProductionWindowStatus.RUNNING,
            lease_expires_at=now + timedelta(minutes=5),
        )

        active_manifest = build_stale_crawl_manifest(now=now, activity_evidence=_activity())
        self.assertEqual(active_manifest["jobs"][0]["job_id"], job.id)
        self.assertEqual(active_manifest["jobs"][0]["recommended_action"], "skip_active_evidence")

        window.lease_expires_at = now - timedelta(seconds=1)
        window.save(update_fields=["lease_expires_at", "updated_at"])
        expired_manifest = build_stale_crawl_manifest(now=now, activity_evidence=_activity())
        self.assertEqual(expired_manifest["jobs"][0]["recommended_action"], "reconcile_failed")

    def test_apply_rejects_sha_mismatch_and_incomplete_activity_evidence(self):
        from stable.services.news_production_integrity import (
            apply_stale_crawl_manifest,
            build_stale_crawl_manifest,
        )

        now = timezone.now()
        job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=90),
        )
        manifest = build_stale_crawl_manifest(now=now, activity_evidence=_activity())

        with self.assertRaisesMessage(ValueError, "manifest_sha256_mismatch"):
            apply_stale_crawl_manifest(
                manifest,
                expected_sha256="0" * 64,
                activity_evidence=_activity(),
                now=now,
            )
        with self.assertRaisesMessage(ValueError, "active_execution_evidence_incomplete"):
            apply_stale_crawl_manifest(
                manifest,
                expected_sha256=manifest["manifest_sha256"],
                activity_evidence=_activity(available=False),
                now=now,
            )
        job.refresh_from_db()
        self.assertEqual(job.status, TaskStatus.STARTED)

    def test_management_command_dry_run_writes_manifest_without_changing_jobs(self):
        now = timezone.now()
        job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=90),
        )
        stdout = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "manifest.json"
            with patch(
                "stable.services.news_production_integrity.collect_celery_crawl_activity",
                return_value=_activity(),
            ):
                call_command(
                    "reconcile_stale_crawl_jobs",
                    "--output",
                    str(output_path),
                    stdout=stdout,
                )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        job.refresh_from_db()
        self.assertEqual(job.status, TaskStatus.STARTED)
        self.assertEqual(payload["jobs"][0]["job_id"], job.id)
        self.assertEqual(payload["jobs"][0]["recommended_action"], "reconcile_failed")
        self.assertEqual(json.loads(stdout.getvalue())["mode"], "dry-run")

    def test_management_command_apply_requires_explicit_confirmation(self):
        with self.assertRaisesMessage(CommandError, "--confirm-apply"):
            call_command(
                "reconcile_stale_crawl_jobs",
                "--apply-manifest",
                "/tmp/unused-news-manifest.json",
                "--expected-sha256",
                "0" * 64,
            )

    def test_management_command_refuses_to_overwrite_existing_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "manifest.json"
            output_path.write_text("existing", encoding="utf-8")
            with self.assertRaisesMessage(CommandError, "拒绝覆盖"):
                call_command("reconcile_stale_crawl_jobs", "--output", str(output_path))
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing")

    def test_integrity_audit_command_is_read_only(self):
        now = timezone.now()
        CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.FAILED,
            started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=19),
            error_message="parse failed",
        )
        before = {
            "jobs": CrawlJob.objects.count(),
            "logs": TaskExecutionLog.objects.count(),
        }
        stdout = StringIO()

        call_command("audit_news_production_integrity", stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(before["jobs"], CrawlJob.objects.count())
        self.assertEqual(before["logs"], TaskExecutionLog.objects.count())
        self.assertFalse(payload["index"]["supported"])
        self.assertEqual(payload["crawl_jobs"]["failed"], 1)
        self.assertEqual(payload["sources"][0]["failure_categories"]["parse_error"], 1)

    def test_celery_inspect_without_worker_reply_is_not_treated_as_empty_activity(self):
        from stable.services.news_production_integrity import collect_celery_crawl_activity

        with patch("app.celery.app.control.inspect") as inspect:
            inspect.return_value.active.return_value = None
            inspect.return_value.reserved.return_value = {}
            evidence = collect_celery_crawl_activity()

        self.assertFalse(evidence["available"])
        self.assertEqual(evidence["errors"], ["celery_inspect_no_reply"])

    def test_celery_activity_manifest_redacts_sensitive_kwargs(self):
        from stable.services.news_production_integrity import collect_celery_crawl_activity

        task = {
            "id": "task-1",
            "name": "stable.tasks.crawl_news_source_task",
            "args": [self.source.id],
            "kwargs": {"api_key": "must-not-leak", "window_id": 3},
            "hostname": "worker-1",
        }
        with patch("app.celery.app.control.inspect") as inspect:
            inspect.return_value.active.return_value = {
                "worker-1": [
                    task,
                    {
                        "id": "unrelated-1",
                        "name": "stable.tasks.unrelated_task",
                        "args": ["raw-payload-must-not-enter-manifest"],
                        "kwargs": {},
                        "hostname": "worker-1",
                    },
                ]
            }
            inspect.return_value.reserved.return_value = {"worker-1": []}
            evidence = collect_celery_crawl_activity()

        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["active_source_ids"], [self.source.id])
        self.assertEqual(len(evidence["active_tasks"]), 1)
        self.assertEqual(evidence["active_tasks"][0]["kwargs"]["api_key"], "[REDACTED_SECRET]")

    def test_celery_partial_worker_replies_are_incomplete_evidence(self):
        from stable.services.news_production_integrity import collect_celery_crawl_activity

        with patch("app.celery.app.control.inspect") as inspect:
            inspect.return_value.active.return_value = {"worker-1": []}
            inspect.return_value.reserved.return_value = {"worker-2": []}
            evidence = collect_celery_crawl_activity()

        self.assertFalse(evidence["available"])
        self.assertEqual(evidence["errors"], ["celery_inspect_partial_reply"])

    def test_apply_rejects_duplicate_manifest_job_ids(self):
        from stable.services.news_production_integrity import (
            apply_stale_crawl_manifest,
            build_stale_crawl_manifest,
            manifest_sha256,
        )

        now = timezone.now()
        CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=90),
        )
        manifest = build_stale_crawl_manifest(now=now, activity_evidence=_activity())
        manifest["jobs"].append(dict(manifest["jobs"][0]))
        manifest["manifest_sha256"] = manifest_sha256(manifest)

        with self.assertRaisesMessage(ValueError, "duplicate_manifest_job_id"):
            apply_stale_crawl_manifest(
                manifest,
                expected_sha256=manifest["manifest_sha256"],
                activity_evidence=_activity(),
                now=now,
            )

    def test_apply_rejects_zero_limit_without_mutating_job(self):
        from stable.services.news_production_integrity import (
            apply_stale_crawl_manifest,
            build_stale_crawl_manifest,
        )

        now = timezone.now()
        job = CrawlJob.objects.create(
            source=self.source,
            status=TaskStatus.STARTED,
            started_at=now - timedelta(minutes=90),
        )
        manifest = build_stale_crawl_manifest(now=now, activity_evidence=_activity())

        with self.assertRaisesMessage(ValueError, "invalid_limit"):
            apply_stale_crawl_manifest(
                manifest,
                expected_sha256=manifest["manifest_sha256"],
                activity_evidence=_activity(),
                now=now,
                limit=0,
            )
        job.refresh_from_db()
        self.assertEqual(job.status, TaskStatus.STARTED)


class RollingSourceHealthTests(TestCase):
    def test_recent_index_failure_remains_visible_after_latest_success(self):
        from stable.services.news_production_integrity import source_health_snapshot

        now = timezone.now()
        source = NewsSource.objects.create(
            name="滚动健康来源",
            homepage_url="https://health.example/",
            feed_url="https://health.example/feed",
        )
        CrawlJob.objects.create(
            source=source,
            status=TaskStatus.FAILED,
            started_at=now - timedelta(minutes=40),
            finished_at=now - timedelta(minutes=39),
            error_message='cannot find insert offset in index "stable_newsarticle_public_slug_46694cb6"',
        )
        CrawlJob.objects.create(
            source=source,
            status=TaskStatus.SUCCESS,
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=4),
        )

        health = source_health_snapshot(source, now=now)

        self.assertEqual(health["failures_2h"], 1)
        self.assertEqual(health["failures_24h"], 1)
        self.assertIsNotNone(health["last_success_at"])
        self.assertTrue(health["index_error"]["active"])
        self.assertEqual(health["index_error"]["index_name"], "stable_newsarticle_public_slug_46694cb6")
        self.assertTrue(health["index_error_24h"]["active"])

    def test_index_error_older_than_short_window_is_history_not_active_p0(self):
        from stable.services.news_production_integrity import source_health_snapshot

        now = timezone.now()
        source = NewsSource.objects.create(
            name="历史错误来源",
            homepage_url="https://history.example/",
            feed_url="https://history.example/feed",
        )
        CrawlJob.objects.create(
            source=source,
            status=TaskStatus.FAILED,
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3) + timedelta(minutes=1),
            error_message='cannot find insert offset in index "stable_newsarticle_public_slug_46694cb6"',
        )

        health = source_health_snapshot(source, now=now)

        self.assertFalse(health["index_error"]["active"])
        self.assertTrue(health["index_error_24h"]["active"])

    @override_settings(AUTOMATION_ENABLED=True, NEWS_INDEX_P0_COOLDOWN_HOURS=6)
    def test_anomaly_task_emits_p0_even_when_latest_job_succeeds(self):
        from stable.tasks import detect_automation_anomalies_task

        now = timezone.now()
        source = NewsSource.objects.create(
            name="P0 来源",
            homepage_url="https://p0.example/",
            feed_url="https://p0.example/feed",
        )
        CrawlJob.objects.create(
            source=source,
            status=TaskStatus.FAILED,
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=29),
            error_message='cannot find insert offset in index "stable_newsarticle_public_slug_46694cb6"',
        )
        CrawlJob.objects.create(
            source=source,
            status=TaskStatus.SUCCESS,
            started_at=now - timedelta(minutes=3),
            finished_at=now - timedelta(minutes=2),
        )

        with patch("stable.tasks.send_notification_task.run") as send:
            result = detect_automation_anomalies_task.run()

        self.assertIn(NotificationType.OPS_ANOMALY, result["notifications"])
        p0_calls = [call for call in send.call_args_list if call.args[0] == NotificationType.OPS_ANOMALY]
        self.assertEqual(len(p0_calls), 1)
        self.assertEqual(p0_calls[0].args[1]["reason"], "news_index_physical_error")

    @override_settings(AUTOMATION_ENABLED=False, NEWS_INDEX_P0_COOLDOWN_HOURS=6)
    def test_index_p0_remains_enabled_when_content_automation_is_disabled(self):
        from stable.tasks import detect_automation_anomalies_task

        now = timezone.now()
        source = NewsSource.objects.create(
            name="独立 P0 来源",
            homepage_url="https://independent-p0.example/",
            feed_url="https://independent-p0.example/feed",
        )
        CrawlJob.objects.create(
            source=source,
            status=TaskStatus.FAILED,
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=9),
            error_message='overlaps with invalid duplicate tuple in index "stable_newsarticle_public_slug_46694cb6"',
        )

        with patch("stable.tasks.send_notification_task.run") as send:
            result = detect_automation_anomalies_task.run()

        self.assertTrue(result["skipped"])
        self.assertIn(NotificationType.OPS_ANOMALY, result["notifications"])
        self.assertEqual(send.call_args.args[0], NotificationType.OPS_ANOMALY)

    @override_settings(AUTOMATION_ENABLED=False, NEWS_INDEX_P0_COOLDOWN_HOURS=6)
    def test_task_execution_index_error_also_emits_p0(self):
        from stable.tasks import detect_automation_anomalies_task

        TaskExecutionLog.objects.create(
            task_name="auto_publish_ready_articles",
            status=TaskStatus.FAILED,
            detail='failed to re-find parent key in index "stable_newsarticle_public_slug_46694cb6"',
        )

        with patch("stable.tasks.send_notification_task.run") as send:
            result = detect_automation_anomalies_task.run()

        self.assertIn(NotificationType.OPS_ANOMALY, result["notifications"])
        self.assertEqual(send.call_args.args[1]["index_name"], "stable_newsarticle_public_slug_46694cb6")

    @override_settings(AUTOMATION_ENABLED=False, NEWS_INDEX_P0_COOLDOWN_HOURS=6)
    def test_unrelated_ops_anomaly_does_not_suppress_index_p0(self):
        from stable.tasks import detect_automation_anomalies_task

        NotificationLog.objects.create(
            type=NotificationType.OPS_ANOMALY,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SKIPPED,
            payload_summary="ops_anomaly | reason=unrelated_capacity_warning",
        )
        TaskExecutionLog.objects.create(
            task_name="auto_publish_ready_articles",
            status=TaskStatus.FAILED,
            detail='contains unexpected zero page in index "stable_newsarticle_public_slug_46694cb6"',
        )

        with patch("stable.tasks.send_notification_task.run") as send:
            result = detect_automation_anomalies_task.run()

        self.assertIn(NotificationType.OPS_ANOMALY, result["notifications"])
        send.assert_called_once()
