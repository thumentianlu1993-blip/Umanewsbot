from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import Mock, patch

import requests
from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NotificationLog,
    OperationLog,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TaskExecutionLog,
    TranslationRun,
    WorkflowStatus,
)


UTC = dt_timezone.utc
NOW = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


def article_for_retry(**overrides) -> NewsArticle:
    values = {
        "source_site": SourceSite.TDN,
        "source_mode": SourceMode.LATEST,
        "racing_region": RacingRegion.FRANCE,
        "source_language": SourceLanguage.ENGLISH,
        "source_article_id": f"retry-{NewsArticle.objects.count()}",
        "source_url": f"https://example.com/retry/{NewsArticle.objects.count()}",
        "title_ja": "French racing translation retry",
        "body_ja_raw": "French racing body " * 20,
        "body_ja_normalized": "French racing body " * 20,
        "published_at": NOW,
        "translation_status": ArticleTranslationStatus.FAILED,
        "workflow_status": WorkflowStatus.TRANSLATION_FAILED,
        "automation_status": AutomationStatus.FAILED,
        "translation_error_message": "provider unavailable",
        "translation_error_category": "transient_provider_unavailable",
        "translation_retry_count": 0,
        "translation_next_retry_at": NOW,
    }
    values.update(overrides)
    return NewsArticle.objects.create(**values)


class TranslationErrorClassificationTests(TestCase):
    def classify(self, error, **kwargs):
        from stable.services.translation_recovery import classify_translation_error

        return classify_translation_error(error, **kwargs)

    def test_http_429_is_rate_limited_and_honors_retry_after_seconds(self):
        response = Mock(status_code=429, headers={"Retry-After": "120"})
        result = self.classify(requests.HTTPError("429 Too Many Requests", response=response))

        self.assertEqual(result.category, "transient_rate_limited")
        self.assertEqual(result.retry_after_seconds, 120)
        self.assertTrue(result.auto_retryable)

    def test_retry_after_http_date_is_parsed(self):
        response = Mock(
            status_code=503,
            headers={"Retry-After": "Sun, 13 Jul 2026 00:05:00 GMT"},
        )
        result = self.classify(
            requests.HTTPError("503 unavailable", response=response),
            now=NOW,
        )

        self.assertEqual(result.category, "transient_provider_unavailable")
        self.assertEqual(result.retry_after_seconds, 300)

    def test_provider_unavailable_statuses_are_transient(self):
        for status in (502, 503, 504):
            with self.subTest(status=status):
                response = Mock(status_code=status, headers={})
                result = self.classify(requests.HTTPError(str(status), response=response))
                self.assertEqual(result.category, "transient_provider_unavailable")
                self.assertTrue(result.auto_retryable)

    def test_timeout_is_transient(self):
        result = self.classify(requests.Timeout("read timed out"))

        self.assertEqual(result.category, "transient_timeout")
        self.assertTrue(result.auto_retryable)

    def test_auth_and_permanent_payload_are_not_retried(self):
        for status, category in ((400, "permanent_payload"), (401, "permanent_auth"), (403, "permanent_auth")):
            with self.subTest(status=status):
                response = Mock(status_code=status, headers={})
                result = self.classify(requests.HTTPError(str(status), response=response))
                self.assertEqual(result.category, category)
                self.assertFalse(result.auto_retryable)

    def test_unknown_error_is_saved_but_not_automatically_retried(self):
        result = self.classify(RuntimeError("unexpected response shape"))

        self.assertEqual(result.category, "unknown")
        self.assertFalse(result.auto_retryable)
        self.assertIn("unexpected response shape", result.error_summary)


class TranslationBackoffTests(TestCase):
    def test_default_backoff_is_60_300_900_seconds_without_jitter(self):
        from stable.services.translation_recovery import retry_delay_seconds

        self.assertEqual([retry_delay_seconds(i, jitter_seconds=0) for i in (1, 2, 3)], [60, 300, 900])

    def test_retry_after_never_allows_earlier_retry(self):
        from stable.services.translation_recovery import retry_delay_seconds

        self.assertEqual(retry_delay_seconds(1, retry_after_seconds=600, jitter_seconds=0), 600)

    @override_settings(TRANSLATION_AUTO_RETRY_MAX_ATTEMPTS=3)
    def test_third_failed_retry_enters_visible_exhausted_terminal_state(self):
        from stable.services.translation_recovery import record_translation_failure

        article = article_for_retry(translation_retry_count=2)
        response = Mock(status_code=503, headers={})
        error = requests.HTTPError("503 unavailable", response=response)

        record_translation_failure(article, error, now=NOW, is_retry=True)

        article.refresh_from_db()
        self.assertEqual(article.translation_retry_count, 3)
        self.assertEqual(article.translation_error_category, "transient_provider_unavailable")
        self.assertIsNone(article.translation_next_retry_at)
        self.assertEqual(article.translation_retry_exhausted_at, NOW)
        self.assertEqual(article.workflow_status, WorkflowStatus.TRANSLATION_FAILED)

    def test_permanent_failure_never_gets_next_retry_time(self):
        from stable.services.translation_recovery import record_translation_failure

        article = article_for_retry()
        response = Mock(status_code=401, headers={})

        record_translation_failure(
            article,
            requests.HTTPError("401 unauthorized", response=response),
            now=NOW,
            is_retry=False,
        )

        article.refresh_from_db()
        self.assertEqual(article.translation_error_category, "permanent_auth")
        self.assertIsNone(article.translation_next_retry_at)


class TranslationRetryDispatchTests(TestCase):
    @override_settings(TRANSLATION_AUTO_RETRY_ENABLED=False, TRANSLATION_AUTO_RETRY_BATCH_SIZE=10)
    def test_disabled_selector_dispatches_nothing(self):
        from stable.services.translation_recovery import dispatch_due_translation_retries

        article_for_retry()

        with patch("stable.services.translation_recovery.translate_article_task.delay") as delay:
            result = dispatch_due_translation_retries(now=NOW)

        self.assertEqual(result.dispatched_ids, [])
        delay.assert_not_called()

    @override_settings(TRANSLATION_AUTO_RETRY_ENABLED=True, TRANSLATION_AUTO_RETRY_BATCH_SIZE=2)
    def test_selector_dispatches_only_due_transient_failures_up_to_batch_limit(self):
        from stable.services.translation_recovery import dispatch_due_translation_retries

        due = [article_for_retry(source_article_id=f"due-{index}") for index in range(3)]
        article_for_retry(
            source_article_id="future",
            translation_next_retry_at=NOW + timedelta(minutes=1),
        )
        article_for_retry(
            source_article_id="permanent",
            translation_error_category="permanent_auth",
            translation_next_retry_at=None,
        )

        with patch("stable.services.translation_recovery.translate_article_task.delay") as delay:
            result = dispatch_due_translation_retries(now=NOW)

        self.assertEqual(result.dispatched_ids, [due[0].id, due[1].id])
        self.assertEqual(delay.call_count, 2)
        delay.assert_any_call(due[0].id, preclaimed_retry=True)
        delay.assert_any_call(due[1].id, preclaimed_retry=True)
        for article in due[:2]:
            article.refresh_from_db()
            self.assertEqual(article.translation_status, ArticleTranslationStatus.TRANSLATING)
        due[2].refresh_from_db()
        self.assertEqual(due[2].translation_status, ArticleTranslationStatus.FAILED)

        with patch("stable.services.translation_recovery.translate_article_task.delay") as second_delay:
            second = dispatch_due_translation_retries(now=NOW)
        self.assertEqual(second.dispatched_ids, [due[2].id])
        second_delay.assert_called_once_with(due[2].id, preclaimed_retry=True)

    def test_worker_conditional_claim_allows_only_one_concurrent_execution(self):
        from stable.services.translation_recovery import claim_translation_retry

        article = article_for_retry()

        first = claim_translation_retry(article.id, expected_due_at=NOW, now=NOW)
        second = claim_translation_retry(article.id, expected_due_at=NOW, now=NOW)

        self.assertTrue(first.claimed)
        self.assertFalse(second.claimed)
        self.assertEqual(TranslationRun.objects.filter(article=article).count(), 1)

    def test_non_preclaimed_duplicate_task_skips_article_already_translating(self):
        from stable.tasks import translate_article_task

        article = article_for_retry(
            translation_status=ArticleTranslationStatus.TRANSLATING,
            translation_started_at=NOW,
            translation_next_retry_at=None,
        )
        TranslationRun.objects.create(article=article, status="started")

        with patch("stable.tasks.translate_article") as translate:
            result = translate_article_task.run(article.id)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "translation_already_claimed")
        translate.assert_not_called()

    @override_settings(TRANSLATION_STALE_AFTER_SECONDS=1800)
    def test_stale_translating_recovery_is_audited_and_retryable(self):
        from stable.services.translation_recovery import recover_stale_translations

        article = article_for_retry(
            translation_status=ArticleTranslationStatus.TRANSLATING,
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
            translation_started_at=NOW - timedelta(minutes=31),
            translation_next_retry_at=None,
        )

        result = recover_stale_translations(now=NOW)

        article.refresh_from_db()
        self.assertEqual(result.recovered_ids, [article.id])
        self.assertEqual(article.translation_status, ArticleTranslationStatus.FAILED)
        self.assertEqual(article.translation_error_category, "transient_stale_worker")
        self.assertIsNotNone(article.translation_next_retry_at)
        self.assertTrue(
            TaskExecutionLog.objects.filter(
                task_name="recover_stale_translations",
                payload__article_id=article.id,
            ).exists()
        )

    def test_stale_recovery_does_not_overwrite_translation_that_already_finished(self):
        from stable.services.translation_recovery import recover_one_stale_translation

        started_at = NOW - timedelta(minutes=31)
        article = article_for_retry(
            translation_status=ArticleTranslationStatus.TRANSLATED,
            workflow_status=WorkflowStatus.PENDING_EDIT,
            translation_started_at=None,
            translation_next_retry_at=None,
        )

        recovered = recover_one_stale_translation(article.id, expected_started_at=started_at, now=NOW)

        article.refresh_from_db()
        self.assertFalse(recovered)
        self.assertEqual(article.translation_status, ArticleTranslationStatus.TRANSLATED)

    def test_success_clears_retry_state_and_reenters_existing_scoring_pipeline(self):
        from stable.services.translation_recovery import finalize_successful_translation_retry

        article = article_for_retry(
            translation_retry_count=2,
            translation_retry_exhausted_at=NOW - timedelta(minutes=5),
        )

        with patch("stable.services.translation_recovery.run_automation_pipeline") as pipeline:
            finalize_successful_translation_retry(article, now=NOW)

        article.refresh_from_db()
        self.assertEqual(article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(article.translation_error_category, "")
        self.assertIsNone(article.translation_next_retry_at)
        self.assertIsNone(article.translation_retry_exhausted_at)
        self.assertEqual(article.decision_reason["translation_recovery"]["recovered_at"], NOW.isoformat())
        pipeline.assert_called_once_with(article.id)


class ManualTranslationRetryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="operator",
            password="password",
            email="operator@example.com",
        )

    def test_manual_retry_can_reopen_exhausted_article_and_records_operator(self):
        from stable.services.translation_recovery import request_manual_translation_retry

        article = article_for_retry(
            translation_retry_count=3,
            translation_next_retry_at=None,
            translation_retry_exhausted_at=NOW,
        )

        result = request_manual_translation_retry(article, requested_by=self.user, now=NOW)

        article.refresh_from_db()
        self.assertTrue(result.accepted)
        self.assertEqual(article.translation_status, ArticleTranslationStatus.FAILED)
        self.assertEqual(article.translation_next_retry_at, NOW)
        self.assertIsNone(article.translation_retry_exhausted_at)
        self.assertTrue(
            OperationLog.objects.filter(
                admin=self.user,
                action_type="translation_retry_requested",
                target_id=str(article.id),
            ).exists()
        )

    def test_duplicate_manual_retry_returns_existing_state_without_new_run(self):
        from stable.services.translation_recovery import request_manual_translation_retry

        article = article_for_retry()

        first = request_manual_translation_retry(article, requested_by=self.user, now=NOW)
        second = request_manual_translation_retry(article, requested_by=self.user, now=NOW)

        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.reason, "already_due_or_running")
        self.assertLessEqual(TranslationRun.objects.filter(article=article).count(), 1)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        TRANSLATION_FAILURE_EMAIL_ENABLED=True,
        TRANSLATION_FAILURE_NOTIFY_EMAILS=["754652181@qq.com"],
        SITE_URL="https://umafans.run",
    )
    def test_exhausted_notification_is_sent_once_and_links_to_article(self):
        from stable.services.translation_recovery import notify_terminal_translation_failure

        article = article_for_retry(translation_retry_exhausted_at=NOW, translation_next_retry_at=None)

        notify_terminal_translation_failure(article)
        notify_terminal_translation_failure(article)

        notifications = NotificationLog.objects.filter(payload_summary__contains=str(article.id))
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.get().status, "sent")
        self.assertIn(f"/admin/stable/newsarticle/{article.id}/change/", notifications.get().payload_summary)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["754652181@qq.com"])
        self.assertIn(f"/admin/stable/newsarticle/{article.id}/change/", mail.outbox[0].body)

    def test_non_staff_cannot_use_bulk_retry_admin_action(self):
        normal = get_user_model().objects.create_user(username="normal", password="password")
        article = article_for_retry()
        self.client.force_login(normal)

        response = self.client.post(
            reverse("admin:stable_newsarticle_changelist"),
            {"action": "retry_failed_translations", "_selected_action": [article.id]},
        )

        self.assertIn(response.status_code, {302, 403})
        article.refresh_from_db()
        self.assertEqual(article.translation_next_retry_at, NOW)

    def test_staff_changelist_can_filter_and_display_retry_state(self):
        article = article_for_retry(
            translation_retry_count=2,
            translation_next_retry_at=NOW + timedelta(minutes=5),
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("admin:stable_newsarticle_changelist"),
            {"translation_error_category__exact": "transient_provider_unavailable"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, article.title_ja)
        self.assertContains(response, "transient_provider_unavailable")
        self.assertContains(response, "2")
