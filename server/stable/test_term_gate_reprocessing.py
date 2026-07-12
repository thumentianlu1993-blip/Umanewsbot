from __future__ import annotations

import json
from importlib import import_module
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, override_settings, tag
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleTranslationStatus,
    AutomationLog,
    AutomationStatus,
    ExternalDataSource,
    ExternalHorseAlias,
    NewsArticle,
    NewsArticleRelatedRegion,
    QQPushDelivery,
    RaceEvent,
    RaceEventRunner,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermEntry,
    TermAlias,
    TermAliasType,
    TermType,
    WorkflowStatus,
)


REPROCESS_SETTINGS = {
    "AUTO_DUPLICATE_HIGH_THRESHOLD": 0,
    "AUTO_DUPLICATE_REVIEW_THRESHOLD": 0,
    "AUTO_REWRITE_ENABLED": False,
    "ENGLISH_TERM_CONTEXT_MODE": "enforce",
    "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS": 24,
    "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS": ["brilliant", "contact", "class"],
    "MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS": [],
}


@override_settings(**REPROCESS_SETTINGS)
class TermGateReprocessContractTests(TestCase):
    def _run_model(self):
        return apps.get_model("stable", "TermGateReprocessRun")

    def _lock_model(self):
        return apps.get_model("stable", "TermGateReprocessLock")

    def _article(self, *, source_article_id: str, first_seen_at=None, body=None, **overrides):
        body = body or ("The filly produced a brilliant performance before the next meeting. " * 7)
        translated_body = "这是一篇赛事新闻，介绍参赛阵容、备战情况和下一场比赛计划。" * 10
        defaults = {
            "source_site": SourceSite.SKY_SPORTS_RACING,
            "source_mode": SourceMode.LATEST,
            "source_article_id": source_article_id,
            "source_language": SourceLanguage.ENGLISH,
            "racing_region": RacingRegion.UNITED_KINGDOM,
            "title_ja": "Stable update",
            "body_ja_raw": body,
            "body_ja_normalized": body,
            "translated_title_zh": "马房动态",
            "title_zh": "马房动态",
            "translated_summary_zh": "马房公布最新动态。",
            "summary_zh": "马房公布最新动态。",
            "translated_body_zh": translated_body,
            "body_zh": translated_body,
            "published_at": timezone.now(),
            "source_url": f"https://example.com/reprocess/{source_article_id}",
            "workflow_status": WorkflowStatus.PENDING_REVIEW,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "automation_status": AutomationStatus.MANUAL_REVIEW_REQUIRED,
            "gate_issues": [
                {
                    "code": "core_term_missing",
                    "severity": "blocker",
                    "payload": {"source_ja": "Brilliant"},
                }
            ],
            "score_total": 85,
            "first_seen_at": first_seen_at or timezone.now(),
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def _dry_run(self, *extra_args):
        out = StringIO()
        call_command(
            "reprocess_term_gate_blocked_articles",
            "--region",
            RacingRegion.UNITED_KINGDOM,
            "--hours",
            "24",
            "--limit",
            "100",
            "--max-seconds",
            "60",
            "--dry-run",
            "--json",
            *extra_args,
            stdout=out,
        )
        return json.loads(out.getvalue())

    def _commit(self, run_id, manifest_sha256):
        out = StringIO()
        call_command(
            "reprocess_term_gate_blocked_articles",
            "--commit",
            "--run-id",
            str(run_id),
            "--manifest-sha256",
            manifest_sha256,
            "--json",
            stdout=out,
        )
        return json.loads(out.getvalue())

    def setUp(self):
        self.term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Brilliant",
            target_zh="辉煌",
            priority=100,
        )

    def test_run_and_singleton_lock_models_expose_required_fields(self):
        run_fields = {field.name for field in self._run_model()._meta.get_fields()}
        lock_fields = {field.name for field in self._lock_model()._meta.get_fields()}

        self.assertTrue(
            {
                "mode",
                "selectors",
                "status",
                "cursor",
                "rule_version",
                "settings_sha256",
                "term_snapshot_sha256",
                "candidate_payload",
                "result_payload",
                "manifest_sha256",
                "statistics",
                "error_message",
                "started_at",
                "finished_at",
            }.issubset(run_fields)
        )
        self.assertTrue(
            {"key", "locked_by_run", "owner_token", "lease_expires_at", "heartbeat_at"}.issubset(lock_fields)
        )

    def test_singleton_lock_key_is_unique(self):
        Lock = self._lock_model()
        Lock.objects.create(key="term-gate-reprocess")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Lock.objects.create(key="term-gate-reprocess")

    def test_run_admin_is_read_only_for_staff(self):
        Run = self._run_model()
        model_admin = admin.site._registry[Run]
        request = RequestFactory().get("/admin/stable/termgatereprocessrun/")
        request.user = get_user_model().objects.create_superuser(
            username="term-gate-admin",
            email="term-gate@example.com",
            password="test-only-password",
        )

        self.assertTrue(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_term_snapshot_changes_when_alias_content_changes_without_timestamp_change(self):
        from stable.services.term_gate_reprocessing import build_term_snapshot_sha256

        alias = TermAlias.objects.create(
            term=self.term,
            source_language=SourceLanguage.ENGLISH,
            text="Brilliant Star",
            alias_type=TermAliasType.ALIAS,
        )
        before = build_term_snapshot_sha256()
        TermAlias.objects.filter(pk=alias.pk).update(text="Brilliant Runner")

        after = build_term_snapshot_sha256()

        self.assertNotEqual(after, before)

    def test_cursor_round_trip_preserves_timestamp_and_id(self):
        from stable.services.term_gate_reprocessing import decode_reprocess_cursor, encode_reprocess_cursor

        first_seen_at = timezone.now().replace(microsecond=123456)
        window_start = first_seen_at - timedelta(hours=24)
        window_end = first_seen_at + timedelta(hours=1)
        cursor = encode_reprocess_cursor(
            first_seen_at=first_seen_at,
            article_id=987,
            window_start=window_start,
            window_end=window_end,
        )

        decoded = decode_reprocess_cursor(cursor)

        self.assertEqual(decoded.first_seen_at, first_seen_at)
        self.assertEqual(decoded.article_id, 987)
        self.assertEqual(decoded.window_start, window_start)
        self.assertEqual(decoded.window_end, window_end)

    def test_cursor_paginates_equal_timestamps_without_duplicates_or_gaps(self):
        same_time = timezone.now() - timedelta(hours=1)
        articles = [
            self._article(source_article_id=f"same-time-{index}", first_seen_at=same_time)
            for index in range(3)
        ]

        first_page = self._dry_run("--limit", "2")
        second_page = self._dry_run("--limit", "2", "--cursor", first_page["next_cursor"])

        combined = [*first_page["candidate_ids"], *second_page["candidate_ids"]]
        self.assertEqual(combined, [article.id for article in articles])
        self.assertEqual(len(combined), len(set(combined)))

    def test_cursor_keeps_the_original_absolute_window_when_time_advances(self):
        initial_now = timezone.now().replace(microsecond=0)
        first = self._article(
            source_article_id="fixed-window-first",
            first_seen_at=initial_now - timedelta(hours=23, minutes=30),
        )
        second = self._article(
            source_article_id="fixed-window-second",
            first_seen_at=initial_now - timedelta(hours=23),
        )

        with patch("stable.services.term_gate_reprocessing.timezone.now", return_value=initial_now):
            first_page = self._dry_run("--limit", "1")

        arrived_later = self._article(
            source_article_id="fixed-window-arrived-later",
            first_seen_at=initial_now + timedelta(minutes=30),
        )
        with patch(
            "stable.services.term_gate_reprocessing.timezone.now",
            return_value=initial_now + timedelta(hours=2),
        ):
            second_page = self._dry_run("--limit", "1", "--cursor", first_page["next_cursor"])

        self.assertEqual(first_page["candidate_ids"], [first.id])
        self.assertEqual(second_page["candidate_ids"], [second.id])
        self.assertNotIn(arrived_later.id, second_page["candidate_ids"])
        self.assertEqual(first_page["window_start"], second_page["window_start"])
        self.assertEqual(first_page["window_end"], second_page["window_end"])

    def test_max_seconds_stops_with_a_resumable_cursor(self):
        for index in range(3):
            self._article(source_article_id=f"time-budget-{index}")

        with patch(
            "stable.services.term_gate_reprocessing.monotonic",
            side_effect=[0.0, 0.1, 1.1, 1.2, 1.3, 1.4],
        ):
            payload = self._dry_run("--max-seconds", "1")

        self.assertEqual(payload["stop_reason"], "max_seconds")
        self.assertLess(payload["summary"]["completed_count"], 3)
        self.assertTrue(payload["next_cursor"])

    def test_dry_run_persists_auditable_run_but_does_not_write_articles(self):
        article = self._article(source_article_id="dry-run-no-article-write")
        before = NewsArticle.objects.values(
            "workflow_status",
            "automation_status",
            "gate_issues",
            "ranked_revived_at",
            "updated_at",
        ).get(pk=article.pk)

        payload = self._dry_run()

        after = NewsArticle.objects.values(
            "workflow_status",
            "automation_status",
            "gate_issues",
            "ranked_revived_at",
            "updated_at",
        ).get(pk=article.pk)
        run = self._run_model().objects.get(pk=payload["run_id"])
        self.assertEqual(after, before)
        self.assertEqual(run.manifest_sha256, payload["manifest_sha256"])
        self.assertEqual(run.candidate_payload[0]["article_id"], article.id)
        self.assertTrue(run.term_snapshot_sha256)
        self.assertTrue(run.settings_sha256)

    def test_wrong_manifest_sha_rejects_commit_without_writes(self):
        article = self._article(source_article_id="wrong-manifest")
        dry_run = self._dry_run()

        with self.assertRaises(CommandError):
            self._commit(dry_run["run_id"], "0" * 64)

        article.refresh_from_db()
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertIsNone(article.ranked_revived_at)

    def test_dry_run_uses_global_singleton_lease(self):
        from stable.services.term_gate_reprocessing import ReprocessLeaseActive, claim_reprocess_lease

        Run = self._run_model()
        first = Run.objects.create(mode="dry_run", selectors={"region": RacingRegion.HONG_KONG})
        second = Run.objects.create(mode="dry_run", selectors={"region": RacingRegion.UNITED_KINGDOM})
        claim_reprocess_lease(first, owner_token="owner-one")

        with self.assertRaises(ReprocessLeaseActive):
            claim_reprocess_lease(second, owner_token="owner-two")

    def test_commit_reports_active_lease_as_command_error(self):
        from stable.services.term_gate_reprocessing import ReprocessLeaseActive

        with patch(
            "stable.management.commands.reprocess_term_gate_blocked_articles.commit_reprocess_run",
            side_effect=ReprocessLeaseActive("another run is active"),
        ):
            with self.assertRaisesRegex(CommandError, "another run is active"):
                self._commit(1, "a" * 64)

    def test_lease_conflict_rejects_the_new_audit_run_instead_of_leaving_it_running(self):
        from stable.services.term_gate_reprocessing import (
            ReprocessLeaseActive,
            claim_reprocess_lease,
            run_reprocess_dry_run,
        )

        holder = self._run_model().objects.create(mode="dry_run", selectors={"region": RacingRegion.HONG_KONG})
        claim_reprocess_lease(holder, owner_token="holder")

        with self.assertRaisesRegex(ReprocessLeaseActive, "lease_expires_at"):
            run_reprocess_dry_run(
                region=RacingRegion.UNITED_KINGDOM,
                hours=24,
                limit=10,
                max_seconds=60,
                owner_token="contender",
            )

        contender = self._run_model().objects.exclude(pk=holder.pk).latest("id")
        self.assertEqual(contender.status, "rejected")
        self.assertTrue(contender.finished_at)

    def test_expired_lease_can_be_taken_over_but_old_owner_cannot_release_it(self):
        from stable.services.term_gate_reprocessing import (
            claim_reprocess_lease,
            release_reprocess_lease,
        )

        Run = self._run_model()
        first = Run.objects.create(mode="dry_run", selectors={"region": RacingRegion.HONG_KONG})
        second = Run.objects.create(mode="dry_run", selectors={"region": RacingRegion.UNITED_KINGDOM})
        claim_reprocess_lease(first, owner_token="owner-one", now=timezone.now() - timedelta(hours=1))
        claim_reprocess_lease(second, owner_token="owner-two", now=timezone.now())

        released = release_reprocess_lease(owner_token="owner-one")

        lock = self._lock_model().objects.get(key="term-gate-reprocess")
        self.assertFalse(released)
        self.assertEqual(lock.locked_by_run_id, second.id)
        self.assertEqual(lock.owner_token, "owner-two")

    def test_current_owner_can_renew_the_lease_by_elapsed_time(self):
        from stable.services.term_gate_reprocessing import claim_reprocess_lease, renew_reprocess_lease

        started_at = timezone.now()
        run = self._run_model().objects.create(mode="dry_run", selectors={})
        claim_reprocess_lease(run, owner_token="owner-one", now=started_at, lease_minutes=30)

        renewed = renew_reprocess_lease(owner_token="owner-one", now=started_at + timedelta(minutes=10))

        lock = self._lock_model().objects.get(key="term-gate-reprocess")
        self.assertTrue(renewed)
        self.assertEqual(lock.heartbeat_at, started_at + timedelta(minutes=10))
        self.assertEqual(lock.lease_expires_at, started_at + timedelta(minutes=40))

    def test_global_snapshot_drift_rejects_entire_commit(self):
        article = self._article(source_article_id="global-drift")
        dry_run = self._dry_run()
        self.term.target_zh = "新译名"
        self.term.save(update_fields=["target_zh", "updated_at"])

        payload = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])

        article.refresh_from_db()
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["reason"], "global_snapshot_drift")
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertIsNone(article.ranked_revived_at)

    def test_validation_setting_drift_rejects_entire_commit(self):
        article = self._article(source_article_id="settings-drift")
        dry_run = self._dry_run()

        with self.settings(AUTO_REWRITE_ENABLED=True, AUTO_PUBLISH_CONTENT_SOURCE="rewrite"):
            payload = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])

        article.refresh_from_db()
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["reason"], "global_snapshot_drift")
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)

    def test_term_snapshot_drift_after_initial_commit_check_rolls_back_the_batch(self):
        article = self._article(source_article_id="late-term-snapshot-drift")
        dry_run = self._dry_run()
        run = self._run_model().objects.get(pk=dry_run["run_id"])

        with patch(
            "stable.services.term_gate_reprocessing.build_term_snapshot_sha256",
            return_value="f" * 64,
        ):
            payload = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])

        article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["reason"], "global_snapshot_drift")
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertIsNone(article.ranked_revived_at)
        self.assertFalse(AutomationLog.objects.filter(article=article, phase="validate").exists())
        self.assertEqual(run.status, "rejected")

    def test_article_drift_is_skipped_without_overwriting_new_state(self):
        article = self._article(source_article_id="article-drift")
        dry_run = self._dry_run()
        article.title_zh = "运营人工修改后的标题"
        article.save(update_fields=["title_zh", "updated_at"])

        payload = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])

        article.refresh_from_db()
        self.assertIn(article.id, payload["skipped_article_ids"])
        self.assertEqual(payload["skipped_reasons"][str(article.id)], "article_input_drift")
        self.assertEqual(article.title_zh, "运营人工修改后的标题")
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)

    def test_commit_recovers_candidate_without_publishing_or_qq_delivery(self):
        article = self._article(source_article_id="commit-candidate")
        dry_run = self._dry_run()

        payload = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])

        article.refresh_from_db()
        self.assertEqual(payload["restored_candidate_ids"], [article.id])
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertNotEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertIsNone(article.published_to_web_at)
        self.assertIsNotNone(article.ranked_revived_at)
        self.assertFalse(QQPushDelivery.objects.filter(article=article).exists())
        self.assertTrue(AutomationLog.objects.filter(article=article, phase="validate").exists())

    def test_commit_batch_failure_rolls_back_articles_and_logs(self):
        first = self._article(source_article_id="atomic-first")
        second = self._article(source_article_id="atomic-second")
        dry_run = self._dry_run()
        from stable.services.term_gate_reprocessing import commit_reprocess_run

        with patch(
            "stable.services.term_gate_reprocessing.apply_validation_outcome",
            side_effect=[None, RuntimeError("synthetic commit failure")],
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic commit failure"):
                commit_reprocess_run(
                    dry_run_id=dry_run["run_id"],
                    manifest_sha256=dry_run["manifest_sha256"],
                )

        first.refresh_from_db()
        second.refresh_from_db()
        run = self._run_model().objects.get(pk=dry_run["run_id"])
        self.assertEqual(first.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertEqual(second.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertIsNone(first.ranked_revived_at)
        self.assertIsNone(second.ranked_revived_at)
        self.assertFalse(AutomationLog.objects.filter(article__in=[first, second], phase="validate").exists())
        self.assertEqual(run.status, "failed")
        self.assertIn("synthetic commit failure", run.error_message)

    def test_repeated_commit_is_idempotent(self):
        article = self._article(source_article_id="repeat-commit")
        dry_run = self._dry_run()
        first = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])
        log_count = AutomationLog.objects.filter(article=article, phase="validate").count()

        second = self._commit(dry_run["run_id"], dry_run["manifest_sha256"])

        article.refresh_from_db()
        self.assertEqual(second["status"], "already_committed")
        self.assertEqual(second["restored_candidate_ids"], first["restored_candidate_ids"])
        self.assertEqual(AutomationLog.objects.filter(article=article, phase="validate").count(), log_count)

    def test_terminal_and_published_articles_never_become_candidates(self):
        rejected = self._article(
            source_article_id="terminal-rejected",
            workflow_status=WorkflowStatus.REJECTED,
        )
        published = self._article(
            source_article_id="terminal-published",
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        payload = self._dry_run()

        self.assertNotIn(rejected.id, payload["candidate_ids"])
        self.assertNotIn(published.id, payload["candidate_ids"])
        self.assertIn(rejected.id, payload["skipped"]["manual_terminal_state"])

    def test_dry_run_reports_old_candidates_as_a_count_without_loading_every_id(self):
        old = timezone.now() - timedelta(hours=48)
        for index in range(3):
            self._article(source_article_id=f"outside-lookback-{index}", first_seen_at=old)
        self._article(
            source_article_id="outside-lookback-other-review",
            first_seen_at=old,
            gate_issues=[{"code": "possible_duplicate_content", "severity": "blocker"}],
        )

        payload = self._dry_run()

        self.assertEqual(payload["outside_lookback_count"], 3)
        self.assertNotIn("outside_lookback", payload["skipped"])

    def test_summary_reports_uncertain_matches_and_affected_articles(self):
        self.term.priority = 10
        self.term.save(update_fields=["priority", "updated_at"])
        lead = "The report reviewed the meeting, runners and conditions in detail. " * 12
        article = self._article(
            source_article_id="uncertain-summary",
            body=lead + "Brilliant Result was used as a promotional heading.",
        )

        payload = self._dry_run()

        self.assertEqual(payload["candidate_ids"], [article.id])
        self.assertEqual(payload["summary"]["uncertain_match_count"], 1)
        self.assertEqual(payload["summary"]["uncertain_article_count"], 1)
        self.assertEqual(payload["summary"]["uncertain_background_article_count"], 1)
        self.assertEqual(payload["summary"]["uncertain_core_article_count"], 0)

    def test_candidate_scan_has_a_hard_cap_and_can_resume_past_non_candidates(self):
        seen_at = timezone.now() - timedelta(hours=1)
        for index in range(200):
            self._article(
                source_article_id=f"bounded-scan-skip-{index:03d}",
                first_seen_at=seen_at + timedelta(microseconds=index),
                gate_issues=[],
            )
        candidate = self._article(
            source_article_id="bounded-scan-candidate",
            first_seen_at=seen_at + timedelta(seconds=1),
        )

        first_page = self._dry_run("--limit", "1")
        second_page = self._dry_run("--limit", "1", "--cursor", first_page["next_cursor"])

        self.assertEqual(first_page["stop_reason"], "scan_limit")
        self.assertEqual(first_page["scanned_count"], 200)
        self.assertEqual(first_page["candidate_ids"], [])
        self.assertTrue(first_page["next_cursor"])
        self.assertEqual(second_page["candidate_ids"], [candidate.id])

    def test_validation_time_budget_stops_between_articles_and_keeps_a_resume_cursor(self):
        from stable.services import term_gate_reprocessing as service

        for index in range(3):
            self._article(source_article_id=f"slow-validation-{index}")
        real_validate = service.validate_rewrite

        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()

        def slow_validate(*args, **kwargs):
            outcome = real_validate(*args, **kwargs)
            clock.value += 2.0
            return outcome

        with patch("stable.services.term_gate_reprocessing.monotonic", clock), patch(
            "stable.services.term_gate_reprocessing.validate_rewrite",
            side_effect=slow_validate,
        ):
            payload = self._dry_run("--max-seconds", "1")

        self.assertEqual(payload["stop_reason"], "max_seconds")
        self.assertEqual(payload["summary"]["completed_count"], 1)
        self.assertTrue(payload["next_cursor"])

    def test_context_build_stops_at_deadline_before_first_article_validation(self):
        from stable.services import term_gate_reprocessing as service

        self._article(source_article_id="slow-context-build")
        real_build = service.build_validation_batch_context

        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()

        def slow_build(articles, **kwargs):
            clock.value = 2.0
            callback = kwargs.get("progress_callback")
            if callback:
                callback()
            return real_build(articles)

        with patch("stable.services.term_gate_reprocessing.monotonic", clock), patch(
            "stable.services.term_gate_reprocessing.build_validation_batch_context",
            side_effect=slow_build,
        ), patch("stable.services.term_gate_reprocessing.validate_rewrite") as validate:
            payload = self._dry_run("--max-seconds", "1")

        validate.assert_not_called()
        self.assertEqual(payload["stop_reason"], "max_seconds")
        self.assertEqual(payload["summary"]["completed_count"], 0)
        self.assertTrue(payload["next_cursor"])

    def test_batch_context_recognizes_the_same_external_horse_alias_as_normal_validation(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context
        from stable.services.terms import recognize_horse_names, serialize_recognized_horse_names

        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.NETKEIBA,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="lucky-star-1",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
        )
        article = self._article(
            source_article_id="batch-horse-alias",
            title_ja="Lucky Star returns",
            body="Lucky Star won at Ascot and will return for another race. " * 5,
            body_ja_raw="Lucky Star won at Ascot and will return for another race. " * 5,
            body_ja_normalized="Lucky Star won at Ascot and will return for another race. " * 5,
        )

        expected = serialize_recognized_horse_names(
            recognize_horse_names(article.title_ja, article.body_ja_normalized, source_language=SourceLanguage.ENGLISH)
        )
        context = build_validation_batch_context([article])
        actual = serialize_recognized_horse_names(context.recognized_horses_by_article[article.id])

        self.assertTrue(expected)
        self.assertEqual(actual, expected)

    def test_batch_term_index_only_checks_buckets_present_in_each_article(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        TermEntry.objects.bulk_create(
            [
                TermEntry(
                    term_type=TermType.HORSE,
                    source_language=SourceLanguage.ENGLISH,
                    racing_region=RacingRegion.UNITED_KINGDOM,
                    source_ja=f"UnusedHorse{index}",
                    target_zh=f"未使用马名{index}",
                    priority=100,
                )
                for index in range(500)
            ]
        )
        article = self._article(
            source_article_id="bucketed-term-index",
            body="Brilliant won at Ascot after a strong late run. " * 5,
        )

        context = build_validation_batch_context([article])

        self.assertLess(context.term_pattern_check_count, 20)
        self.assertIn(self.term.id, context.term_entry_ids_by_article[article.id])

    def test_batch_context_excludes_translated_terms_from_unrelated_regions(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        unrelated = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Regional Outsider",
            target_zh="地区外马名",
            priority=100,
        )
        article = self._article(
            source_article_id="region-filtered-term-index",
            body="Regional Outsider and Brilliant were both mentioned in the report. " * 5,
        )

        context = build_validation_batch_context([article])

        self.assertIn(self.term.id, [entry.id for entry in context.term_entries])
        self.assertNotIn(unrelated.id, [entry.id for entry in context.term_entries])
        self.assertNotIn(unrelated.id, context.term_entry_ids_by_article[article.id])

    def test_batch_context_keeps_pending_horse_terms_across_regions(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        pending = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Pending Regional Horse",
            target_zh="",
            priority=100,
        )
        article = self._article(
            source_article_id="pending-cross-region-term-index",
            body="Pending Regional Horse will make its next start after training well. " * 5,
        )

        context = build_validation_batch_context([article])

        self.assertIn(pending.id, [entry.id for entry in context.term_entries])
        self.assertIn(pending.id, context.term_entry_ids_by_article[article.id])

    def test_batch_context_keeps_terms_from_related_regions(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        related_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Related Region Runner",
            target_zh="关联地区赛驹",
            priority=100,
        )
        article = self._article(
            source_article_id="related-region-term-index",
            body="Related Region Runner will make its next start after training well. " * 5,
        )
        NewsArticleRelatedRegion.objects.create(
            article=article,
            region=RacingRegion.UNITED_STATES,
            source="test",
            reason="cross-region coverage",
            confidence=100,
        )

        context = build_validation_batch_context([article])

        self.assertIn(related_term.id, [entry.id for entry in context.term_entries])
        self.assertIn(related_term.id, context.term_entry_ids_by_article[article.id])

    def test_batch_term_index_strips_sentence_punctuation_from_bucket_tokens(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        article = self._article(
            source_article_id="bucketed-term-punctuation",
            body="Officials confirmed the field. Brilliant. The horse then entered the parade ring.",
        )

        context = build_validation_batch_context([article])

        self.assertIn(self.term.id, context.term_entry_ids_by_article[article.id])

    def test_only_effective_race_links_contribute_structured_entity_evidence(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context
        from stable.services.validation import validate_rewrite

        article = self._article(
            source_article_id="structured-link-status",
            body=("The report reviewed the meeting, runners and conditions in detail. " * 12)
            + "Brilliant Result was used as a promotional heading.",
            body_ja_raw=("The report reviewed the meeting, runners and conditions in detail. " * 12)
            + "Brilliant Result was used as a promotional heading.",
            body_ja_normalized=("The report reviewed the meeting, runners and conditions in detail. " * 12)
            + "Brilliant Result was used as a promotional heading.",
        )
        event = RaceEvent.objects.create(
            year=2026,
            slug="structured-link-status",
            original_name="Test Stakes",
            chinese_name="测试锦标",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="Listed",
            surface="turf",
        )
        RaceEventRunner.objects.create(event=event, horse_name="Brilliant")
        link = ArticleRaceLink.objects.create(
            event=event,
            article=article,
            status=ArticleRaceLinkStatus.CANDIDATE,
        )

        candidate_outcome = validate_rewrite(article, batch_context=build_validation_batch_context([article]))
        candidate_classification = next(
            item for item in candidate_outcome.details["english_term_classifications"] if item["source_ja"] == "Brilliant"
        )
        self.assertEqual(candidate_classification["term_semantic_classification"], "uncertain")
        self.assertFalse(candidate_classification["entity_evidence"])

        link.status = ArticleRaceLinkStatus.AUTO
        link.save(update_fields=["status", "updated_at"])
        active_outcome = validate_rewrite(article, batch_context=build_validation_batch_context([article]))
        active_classification = next(
            item for item in active_outcome.details["english_term_classifications"] if item["source_ja"] == "Brilliant"
        )
        self.assertEqual(active_classification["term_semantic_classification"], "proper_noun")
        self.assertTrue(active_classification["entity_evidence"])

        link.removed_at = timezone.now()
        link.save(update_fields=["removed_at", "updated_at"])
        removed_outcome = validate_rewrite(article, batch_context=build_validation_batch_context([article]))
        removed_classification = next(
            item for item in removed_outcome.details["english_term_classifications"] if item["source_ja"] == "Brilliant"
        )
        self.assertEqual(removed_classification["term_semantic_classification"], "uncertain")
        self.assertFalse(removed_classification["entity_evidence"])

    def test_thirty_six_article_projection_preserves_region_funnel_counts(self):
        expected = {
            RacingRegion.UNITED_KINGDOM: 9,
            RacingRegion.HONG_KONG: 3,
            RacingRegion.FRANCE: 7,
            RacingRegion.UNITED_STATES: 17,
        }
        self.term.racing_region = ""
        self.term.save(update_fields=["racing_region", "updated_at"])
        source_by_region = {
            RacingRegion.UNITED_KINGDOM: SourceSite.SKY_SPORTS_RACING,
            RacingRegion.HONG_KONG: SourceSite.HKJC_NEWS,
            RacingRegion.FRANCE: SourceSite.TDN_FRANCE,
            RacingRegion.UNITED_STATES: SourceSite.TDN,
        }
        for region, count in expected.items():
            for index in range(count):
                self._article(
                    source_article_id=f"projection-{region}-{index:02d}",
                    racing_region=region,
                    source_site=source_by_region[region],
                )

        observed = {}
        for region in expected:
            out = StringIO()
            call_command(
                "reprocess_term_gate_blocked_articles",
                "--region",
                region,
                "--hours",
                "24",
                "--limit",
                "100",
                "--max-seconds",
                "60",
                "--dry-run",
                "--json",
                stdout=out,
            )
            payload = json.loads(out.getvalue())
            observed[region] = payload["summary_by_region"][region]["candidate_count"]

        self.assertEqual(observed, expected)
        self.assertEqual(sum(observed.values()), 36)

    @tag("performance")
    def test_one_hundred_article_dry_run_stays_within_query_budget(self):
        for index in range(100):
            self._article(source_article_id=f"performance-{index:03d}")

        with patch(
            "stable.services.term_gate_reprocessing._max_rss_bytes",
            side_effect=[100, 250],
            create=True,
        ), CaptureQueriesContext(connection) as queries:
            payload = self._dry_run()

        self.assertEqual(payload["summary"]["candidate_count"], 100)
        self.assertLessEqual(len(queries), 35)
        self.assertEqual(payload["performance"]["term_index_build_count"], 1)
        self.assertEqual(payload["performance"]["race_entity_prefetch_count"], 2)
        self.assertEqual(payload["performance"]["horse_alias_prefetch_count"], 1)
        self.assertEqual(payload["performance"]["horse_term_prefetch_count"], 0)
        self.assertEqual(payload["performance"]["entity_prefetch_count"], 3)
        self.assertEqual(payload["performance"]["duplicate_corpus_prefetch_count"], 1)
        self.assertEqual(payload["performance"]["peak_rss_delta_bytes"], 150)
        self.assertEqual(payload["performance"]["sql_query_count"], len(queries))

    def test_term_gate_migration_follows_current_main_migration_head(self):
        term_gate = import_module("stable.migrations.0028_term_gate_reprocess_runs").Migration

        self.assertEqual(term_gate.dependencies, [("stable", "0027_p0_horse_profile_completion")])
