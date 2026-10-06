"""B037：通过现有 selector/task 入口验证同轮重投与迟到结果边界。"""

from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings

from stable.models import NewsArticle, TranslationRun
from stable.services import translation_recovery as recovery
from stable.tasks import translate_article_task
from stable.test_translation_failure_recovery_change import article_for_retry


NOW = datetime(2026, 10, 6, 0, 0, tzinfo=dt_timezone.utc)


@override_settings(
    TRANSLATION_AUTO_RETRY_ENABLED=True,
    TRANSLATION_AUTO_RETRY_BATCH_SIZE=1,
    TRANSLATION_AUTO_RETRY_JITTER_SECONDS=0,
    TRANSLATION_STALE_AFTER_SECONDS=1800,
    TRANSLATION_PROVIDER="dummy",
    TRANSLATION_MODEL="mock-only",
    AUTOMATION_ENABLED=True,
    TRANSLATION_FAILURE_EMAIL_ENABLED=False,
)
class TranslationClaimFenceRedTests(TransactionTestCase):
    """未来 envelope 直接取 selector 的输出；基线不因新签名而失败。"""

    def setUp(self):
        self.now = NOW
        self.clock = patch("django.utils.timezone.now", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.notify = patch.object(recovery, "notify_terminal_translation_failure")
        self.notification = self.notify.start()
        self.addCleanup(self.notify.stop)
        self.mail_patch = patch.object(recovery, "send_mail")
        self.mail = self.mail_patch.start()
        self.addCleanup(self.mail_patch.stop)
        self.dispatch_patch = patch("stable.tasks.dispatch_task")
        self.automation = self.dispatch_patch.start()
        self.addCleanup(self.dispatch_patch.stop)
        self.article = article_for_retry(translation_next_retry_at=NOW)

    def claimed_message(self):
        with patch.object(recovery.translate_article_task, "delay") as delay:
            result = recovery.dispatch_due_translation_retries(now=self.now)
        self.assertEqual(result.dispatched_ids, [self.article.pk])
        self.assertEqual(delay.call_count, 1)
        args, kwargs = delay.call_args
        self.assertEqual(args, (self.article.pk,))
        self.article.refresh_from_db()
        run = self.article.translation_runs.get(status="started")
        return args, kwargs, run

    def translation_result(self):
        return SimpleNamespace(
            title_zh="本轮译文", body_zh="本轮正文", push_summary_zh="摘要",
            metadata={"provider": "dummy", "model": "mock-only", "machine_horse_tags": []},
        )

    def replace_with_new_claim(self):
        self.article.refresh_from_db()
        started = self.article.translation_started_at
        self.now += timedelta(minutes=31)
        self.assertTrue(recovery.recover_one_stale_translation(
            self.article.pk, expected_started_at=started, now=self.now,
        ))
        self.article.refresh_from_db()
        self.now = self.article.translation_next_retry_at
        claim = recovery.claim_translation_retry(
            self.article.pk, expected_due_at=self.now, now=self.now,
        )
        self.assertTrue(claim.claimed)
        self.article.refresh_from_db()
        run = self.article.translation_runs.get(status="started")
        return run, self.article.translation_started_at

    def test_same_preclaimed_message_is_consumed_once(self):
        args, kwargs, _ = self.claimed_message()
        nested = []

        def provider(*_args, **_kwargs):
            # 可控交错：首位 provider 尚未返回，第二位同消息入场。
            if not nested:
                nested.append(None)
                nested[0] = translate_article_task.run(*args, **kwargs)
            return self.translation_result()

        with patch("stable.tasks.translate_article", side_effect=provider) as translate:
            translate_article_task.run(*args, **kwargs)
        self.assertEqual(translate.call_count, 1)
        self.assertTrue(nested[0]["skipped"])
        self.assertEqual(self.automation.call_count, 1)

    def test_late_success_cannot_overwrite_new_claim(self):
        args, kwargs, _ = self.claimed_message()
        newer = []

        def provider(*_args, **_kwargs):
            newer.append(self.replace_with_new_claim())
            return self.translation_result()

        with patch("stable.tasks.translate_article", side_effect=provider):
            result = translate_article_task.run(*args, **kwargs)
        self.article.refresh_from_db()
        new_run, started = newer[0]
        new_run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.translation_started_at, started)
        self.assertEqual(new_run.status, "started")
        self.assertEqual(self.article.body_zh, "")
        self.assertTrue(result["skipped"])
        self.automation.assert_not_called()
        self.notification.assert_not_called()

    def test_late_terminal_exception_cannot_notify_or_fail_new_claim(self):
        args, kwargs, _ = self.claimed_message()
        newer = []

        def provider(*_args, **_kwargs):
            newer.append(self.replace_with_new_claim())
            raise ValueError("invalid mock response")

        with patch("stable.tasks.translate_article", side_effect=provider):
            try:
                result = translate_article_task.run(*args, **kwargs)
            except ValueError:
                # 旧实现会重抛；下面仍检查真实业务污染，而非以异常当 RED。
                result = {}
        self.article.refresh_from_db()
        new_run, started = newer[0]
        new_run.refresh_from_db()
        self.notification.assert_not_called()
        self.mail.assert_not_called()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.translation_started_at, started)
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertEqual(new_run.status, "started")
        self.assertTrue(result["skipped"])

    def test_terminal_notification_observes_committed_article_and_exact_run_once(self):
        args, kwargs, run = self.claimed_message()
        observed = []

        def notified(article):
            observed.append((
                connection.in_atomic_block,
                NewsArticle.objects.get(pk=article.pk).translation_status,
                TranslationRun.objects.get(pk=run.pk).status,
            ))

        self.notification.side_effect = notified
        with patch("stable.tasks.translate_article", side_effect=ValueError("invalid mock response")):
            with self.assertRaises(ValueError):
                translate_article_task.run(*args, **kwargs)
        self.assertEqual(observed, [(False, "failed", "failed")])
        with patch("stable.tasks.translate_article") as translate:
            repeated = translate_article_task.run(*args, **kwargs)
        self.assertTrue(repeated["skipped"])
        translate.assert_not_called()
        self.assertEqual(self.notification.call_count, 1)
        self.mail.assert_not_called()

    def test_terminal_run_save_failure_rolls_back_without_notification(self):
        args, kwargs, run = self.claimed_message()
        save = TranslationRun.save

        def failed_save(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "failed":
                raise RuntimeError("mock run save failure")
            return save(instance, *save_args, **save_kwargs)

        with patch("stable.tasks.translate_article", side_effect=ValueError("invalid mock response")):
            with patch.object(TranslationRun, "save", new=failed_save):
                with self.assertRaises((ValueError, RuntimeError)):
                    translate_article_task.run(*args, **kwargs)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertEqual(run.status, "started")
        self.notification.assert_not_called()
        self.mail.assert_not_called()
