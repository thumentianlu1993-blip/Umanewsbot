"""T11/T15/T24/T31/T34：报告不缩分母、不把目标当100%硬门槛。"""
from datetime import timedelta
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone
from stable.models import NewsPublicationReceipt, NewsDiscoveryObservation, CrawlJob
from stable.services.news_quality_report import timeliness, build_report
from stable.services.news_pipeline import digest, policy_sha
from stable.test_p01_news_workflow import WorkflowFixture


class TimelinessTests(SimpleTestCase):
    def test_major_at_seventy_minutes_is_late_but_not_a_quality_failure(self):
        now = timezone.now()
        result = timeliness(source_time=now-timedelta(minutes=70), time_verified=True, priority="major", published_at=now, now=now)
        self.assertEqual(result["status"], "late")
        self.assertEqual(result["delay_seconds"], 4200)
        self.assertNotIn("quality_failed", result)

    def test_unknown_source_time_never_uses_discovery_as_substitute(self):
        now = timezone.now()
        result = timeliness(source_time=now, time_verified=False, priority="major", published_at=now, now=now)
        self.assertEqual(result["status"], "unknown")

    def test_ordinary_target_is_beijing_same_day(self):
        from datetime import datetime, timezone as tz
        source = datetime(2026, 10, 27, 15, 58, tzinfo=tz.utc)
        result = timeliness(source_time=source, time_verified=True, priority="regional", published_at=source+timedelta(minutes=3), now=source+timedelta(minutes=3))
        self.assertEqual(result["status"], "late")


class ReportTests(WorkflowFixture, TransactionTestCase):
    def report(self, **kwargs):
        now = timezone.now()
        return build_report(start=now-timedelta(hours=2), end=now, **kwargs)

    def test_independent_major_inventory_includes_missed_and_unknown_events(self):
        now = timezone.now()
        events = [{"id": "missed", "identity_key": "news-event-v1:policy:missing", "primary_region": "france", "source_time": (now-timedelta(minutes=70)).isoformat(), "time_verified": True, "provenance": "fixture-independent"},
                  {"id": "unknown", "identity_key": "news-event-v1:policy:unknown", "primary_region": "japan", "source_time": None, "time_verified": False, "provenance": "fixture-independent"}]
        report = self.report(independent_events=events)
        self.assertEqual(report["major"]["denominator"], 2)
        self.assertEqual(report["major"]["unknown"], 1)
        self.assertEqual(report["major"]["overdue"], 1)
        self.assertFalse(report["window"]["full_168_hours"])
        self.assertEqual(report["status"], "observation_incomplete")

    def test_duplicate_discoveries_do_not_hide_three_failed_details(self):
        for _ in range(2):
            job = CrawlJob.objects.create(source=self.source)
            for index in range(3):
                NewsDiscoveryObservation.objects.create(crawl_job=job, source=self.source, kind="stub", item_key=f"candidate-{index}",
                    primary_region="france", stage="detail", outcome="failed", reason="fixture_template_changed", observed_at=timezone.now())
        report = self.report()
        self.assertEqual(report["discovery"]["candidates"], 3)
        self.assertEqual(report["discovery"]["failed"], 3)

    def test_snapshot_counts_are_not_successful_response_exposure(self):
        from stable.services.news_feed import create_snapshot
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            self.finish()
        snapshot = create_snapshot(with_features=True)
        report = self.report()
        self.assertEqual(report["exposure"]["status"], "unknown")
        self.assertEqual(report["exposure"]["responses"], 0)
        self.assertGreater(report.get("seat_seconds", {}).get("france", 0), 0)

    def test_actual_response_ids_require_independent_access_log_reconciliation(self):
        from stable.services.news_feed import create_snapshot
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            self.finish()
        receipt = NewsPublicationReceipt.objects.get(run=self.run)
        snapshot = create_snapshot(with_features=True)
        records = [{"event": "news_feed_response", "response_id": "fixture-response", "generation": str(snapshot.generation),
            "at": timezone.now().isoformat(), "status": 200,
            "entries": [{"id": receipt.public_entry.pk, "region": "france"}], "followed_entry_ids": []}]
        unknown = self.report(exposure_records=records)
        self.assertEqual(unknown["exposure"]["status"], "unknown")
        gap = self.report(exposure_records=records, exposure_access={"complete": True, "response_ids": ["fixture-response", "missing-record"]})
        self.assertEqual(gap["exposure"]["status"], "log_gap")

    def test_older_policy_window_cannot_be_stitched_into_complete_week(self):
        now = timezone.now()
        timeline = [{"start": (now-timedelta(hours=168)).isoformat(), "end": (now-timedelta(hours=100)).isoformat(), "policy_sha": "old"},
                    {"start": (now-timedelta(hours=100)).isoformat(), "end": now.isoformat(), "policy_sha": policy_sha()}]
        report = build_report(start=now-timedelta(hours=168), end=now, evidence={"policy_timeline": timeline})
        self.assertFalse(report["hard_checks"].get("single_policy", True))
        self.assertEqual(report["status"], "observation_incomplete")
