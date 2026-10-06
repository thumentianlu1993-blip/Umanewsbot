"""B037：通过现有 selector/task 入口验证同轮重投与迟到结果边界。"""

from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from threading import Barrier, Event, Thread
import time
from unittest.mock import patch

from django.db import connection, connections, transaction
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
class TranslationClaimFixture(TransactionTestCase):
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


class TranslationClaimFenceRedTests(TranslationClaimFixture):
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


class TranslationClaimFenceBoundaryTests(TranslationClaimFixture):
    def test_success_run_save_failure_rolls_back_article_without_dispatch(self):
        args, kwargs, run = self.claimed_message()
        save = TranslationRun.save

        def failed_save(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "success":
                raise RuntimeError("mock success run save failure")
            return save(instance, *save_args, **save_kwargs)

        with patch("stable.tasks.translate_article", return_value=self.translation_result()):
            with patch.object(TranslationRun, "save", new=failed_save):
                with self.assertRaises(RuntimeError):
                    translate_article_task.run(*args, **kwargs)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.body_zh, "")
        self.assertEqual(run.status, "started")
        self.automation.assert_not_called()
        self.notification.assert_not_called()

    def test_ordinary_translation_keeps_existing_manual_field_protection(self):
        NewsArticle.objects.filter(pk=self.article.pk).update(
            translation_status="pending", translation_next_retry_at=None,
            body_zh="编辑正文", manually_edited_fields=["body_zh"],
        )
        with patch("stable.tasks.translate_article", return_value=self.translation_result()):
            result = translate_article_task.run(self.article.pk)
        self.article.refresh_from_db()
        self.assertTrue(result["translated"])
        self.assertEqual(self.article.body_zh, "编辑正文")
        self.assertEqual(self.article.translated_body_zh, "本轮正文")
        self.assertEqual(self.automation.call_count, 1)

    def test_force_published_keeps_workflow_and_does_not_dispatch(self):
        NewsArticle.objects.filter(pk=self.article.pk).update(
            workflow_status="published", automation_status="published",
            translation_status="translated", translation_next_retry_at=None,
        )
        with patch("stable.tasks.translate_article", return_value=self.translation_result()):
            result = translate_article_task.run(self.article.pk, force=True)
        self.article.refresh_from_db()
        self.assertTrue(result["translated"])
        self.assertEqual(self.article.workflow_status, "published")
        self.assertEqual(self.article.automation_status, "published")
        self.automation.assert_not_called()

    def test_outer_transaction_denies_external_call_without_consuming(self):
        args, kwargs, run = self.claimed_message()
        with transaction.atomic(), patch("stable.tasks.translate_article") as translate:
            result = translate_article_task.run(*args, **kwargs)
        self.assertEqual(result["reason"], "claim_outer_transaction")
        translate.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "claimed")

    def test_source_change_rejects_result_and_preserves_current_manual_fields(self):
        args, kwargs, run = self.claimed_message()

        def provider(*_args, **_kwargs):
            NewsArticle.objects.filter(pk=self.article.pk).update(
                body_ja_normalized="new source", body_zh="编辑正文",
                manually_edited_fields=["body_zh"],
            )
            return self.translation_result()

        with patch("stable.tasks.translate_article", side_effect=provider):
            result = translate_article_task.run(*args, **kwargs)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(result["reason"], "input_changed")
        self.assertEqual(self.article.body_zh, "编辑正文")
        self.assertEqual(self.article.body_ja_normalized, "new source")
        self.assertEqual(run.status, "started")
        self.automation.assert_not_called()

    def test_exact_deadline_denies_entry_without_provider_call(self):
        args, kwargs, run = self.claimed_message()
        self.now += timedelta(seconds=1800)
        with patch("stable.tasks.translate_article") as translate:
            result = translate_article_task.run(*args, **kwargs)
        self.assertEqual(result["reason"], "claim_expired")
        translate.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "claimed")

    def test_result_at_deadline_is_not_committed_or_dispatched(self):
        args, kwargs, run = self.claimed_message()

        def provider(*_args, **_kwargs):
            self.now += timedelta(seconds=1800)
            return self.translation_result()

        with patch("stable.tasks.translate_article", side_effect=provider):
            result = translate_article_task.run(*args, **kwargs)
        self.assertEqual(result["reason"], "claim_expired")
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(run.status, "started")
        self.automation.assert_not_called()

    def test_later_consumption_does_not_reset_start_or_deadline(self):
        args, kwargs, run = self.claimed_message()
        initial = dict(run.raw_response["recovery_claim_v1"])
        self.now += timedelta(seconds=60)

        def provider(article, **_kwargs):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(article.translation_started_at, NOW)
            return self.translation_result()

        with patch("stable.tasks.translate_article", side_effect=provider):
            translate_article_task.run(*args, **kwargs)
        run.refresh_from_db()
        terminal = run.raw_response["recovery_claim_v1"]
        self.assertEqual(terminal["claimed_at"], initial["claimed_at"])
        self.assertEqual(terminal["deadline_at"], initial["deadline_at"])

    def test_old_message_without_envelope_is_closed(self):
        _, _, run = self.claimed_message()
        with patch("stable.tasks.translate_article") as translate:
            result = translate_article_task.run(self.article.pk, preclaimed_retry=True)
        self.assertEqual(result["reason"], "claim_missing")
        translate.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "claimed")

    def test_wrong_run_and_invalid_identity_do_not_consume_current_claim(self):
        args, kwargs, run = self.claimed_message()
        for value in [True, 0, "invalid", run.id + 100000]:
            with self.subTest(run_id=value):
                with patch("stable.tasks.translate_article") as translate:
                    result = translate_article_task.run(*args, **{**kwargs, "claim_run_id": value})
                self.assertTrue(result["skipped"])
                translate.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "claimed")

    def test_dispatch_release_only_finishes_bound_run(self):
        _, _, run = self.claimed_message()
        other = TranslationRun.objects.create(article=self.article, status="started")
        self.assertTrue(recovery.release_failed_translation_dispatch(
            self.article.pk, claimed_at=NOW, run_id=run.id, error=RuntimeError("mock dispatch failure"),
        ))
        run.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(other.status, "started")
        self.notification.assert_not_called()

    def test_stale_recovery_only_finishes_bound_run(self):
        _, _, run = self.claimed_message()
        other = TranslationRun.objects.create(article=self.article, status="started")
        self.now += timedelta(minutes=31)
        self.assertTrue(recovery.recover_one_stale_translation(
            self.article.pk, expected_started_at=NOW, now=self.now,
        ))
        run.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "interrupted")
        self.assertEqual(other.status, "started")
        self.notification.assert_not_called()

    def test_recovery_and_release_run_save_failure_leave_no_state_or_notification(self):
        _, _, run = self.claimed_message()
        save = TranslationRun.save

        def failed_save(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "failed":
                raise RuntimeError("mock run save failure")
            return save(instance, *save_args, **save_kwargs)

        with patch.object(TranslationRun, "save", new=failed_save):
            with self.assertRaises(RuntimeError):
                recovery.release_failed_translation_dispatch(
                    self.article.pk, claimed_at=NOW, run_id=run.id, error=RuntimeError("mock dispatch failure"),
                )
            self.now += timedelta(minutes=31)
            with self.assertRaises(RuntimeError):
                recovery.recover_one_stale_translation(self.article.pk, expected_started_at=NOW, now=self.now)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.translation_started_at, NOW)
        self.assertEqual(run.status, "started")
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "claimed")
        self.notification.assert_not_called()
        self.mail.assert_not_called()

    def test_notification_failure_does_not_retry_or_rewrite_translation(self):
        args, kwargs, run = self.claimed_message()
        self.notification.side_effect = RuntimeError("mock notification failure")
        with patch("stable.tasks.translate_article", side_effect=ValueError("invalid mock response")) as translate:
            with self.assertRaises(ValueError):
                translate_article_task.run(*args, **kwargs)
        self.assertEqual(translate.call_count, 1)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 1)
        self.assertEqual(run.status, "failed")
        with patch("stable.tasks.translate_article") as repeated:
            self.assertTrue(translate_article_task.run(*args, **kwargs)["skipped"])
        repeated.assert_not_called()
        self.assertEqual(self.notification.call_count, 1)

    def test_managed_service_keeps_exact_run_and_metadata_with_no_external_lock(self):
        from stable.services import translation
        args, kwargs, run = self.claimed_message()
        other = TranslationRun.objects.create(article=self.article, status="started")

        class Provider:
            name = "dummy"

            def translate(provider_self, article):
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(TranslationRun.objects.get(pk=run.pk).status, "started")
                return self.translation_result()

        with patch.object(translation, "get_translation_provider", return_value=Provider()):
            with patch.object(translation, "resolve_article_entities_for_article", return_value=SimpleNamespace()):
                with patch.object(translation, "_translation_terms", return_value=[]):
                    result = translate_article_task.run(*args, **kwargs)
        self.assertTrue(result["translated"])
        run.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.raw_response["model"], "mock-only")
        self.assertEqual(run.raw_response["recovery_claim_v1"]["phase"], "completed")
        self.assertEqual(other.status, "started")

    def test_ordinary_service_cannot_overwrite_managed_claim_metadata(self):
        from stable.services import translation
        _, _, run = self.claimed_message()
        original = dict(run.raw_response)

        class Provider:
            name = "dummy"

            def translate(provider_self, article):
                return self.translation_result()

        with patch.object(translation, "get_translation_provider", return_value=Provider()):
            with patch.object(translation, "resolve_article_entities_for_article", return_value=SimpleNamespace()):
                with patch.object(translation, "_translation_terms", return_value=[]):
                    translation.translate_article(self.article)
        run.refresh_from_db()
        self.assertEqual(run.status, "started")
        self.assertEqual(run.raw_response, original)
        self.assertEqual(self.article.translation_runs.filter(status="success").count(), 1)

    def test_two_pg_connections_consume_only_once(self):
        self.assertEqual(connection.vendor, "postgresql", "真实并发验收必须是 PG")
        args, kwargs, _ = self.claimed_message()
        gate = Barrier(3)
        other_done = Event()
        results, errors, backend_ids = [], [], []

        def provider(*_args, **_kwargs):
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(other_done.wait(10), "第二消费者未按时退出")
            return self.translation_result()

        def worker():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_ids.append(cursor.fetchone()[0])
                gate.wait(10)
                result = translate_article_task.run(*args, **kwargs)
                results.append(result)
                if result.get("skipped"):
                    other_done.set()
            except BaseException as exc:
                errors.append(exc)
                other_done.set()
            finally:
                connections.close_all()

        threads = [Thread(target=worker, daemon=True) for _ in range(2)]
        with patch("stable.tasks.translate_article", side_effect=provider) as translate:
            try:
                for thread in threads:
                    thread.start()
                gate.wait(10)
                for thread in threads:
                    thread.join(15)
            finally:
                other_done.set()
                for thread in threads:
                    thread.join(5)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(set(backend_ids)), 2)
        print("B037 isolated PG backend IDs:", sorted(backend_ids), "both connections closed")
        self.assertEqual(translate.call_count, 1)
        self.assertEqual(sum(bool(r.get("skipped")) for r in results), 1)
        self.assertEqual(sum(bool(r.get("translated")) for r in results), 1)


class TranslationClaimPostLockDeadlineTests(TranslationClaimFixture):
    """R01：真实PG锁等待期间越过固定deadline，身份/阶段/源内容不变。"""

    def locked_deadline_case(self, mode, lock_target):
        self.assertEqual(connection.vendor, "postgresql", "锁等待反例必须使用隔离PG")
        self.now = NOW
        if self.article.translation_runs.exists():
            self.article = article_for_retry(translation_next_retry_at=NOW)
        args, kwargs, run = self.claimed_message()
        deadline = NOW + timedelta(seconds=1800)
        self.now = deadline - timedelta(seconds=1)
        backend_ready, provider_ready, release_provider = Event(), Event(), Event()
        backend_ids, results, errors = [], [], []

        def provider(*_args, **_kwargs):
            self.assertFalse(connection.in_atomic_block)
            if mode != "consume":
                provider_ready.set()
                if not release_provider.wait(10):
                    raise AssertionError("provider handoff timed out")
            if mode == "terminal":
                raise ValueError("invalid mock response")
            return self.translation_result()

        def worker():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_ids.append(cursor.fetchone()[0])
                backend_ready.set()
                results.append(translate_article_task.run(*args, **kwargs))
            except BaseException as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        def observe_actual_lock_wait():
            stop = time.monotonic() + 5
            expected_table = "stable_newsarticle" if lock_target == "article" else "stable_translationrun"
            while time.monotonic() < stop:
                with connection.cursor() as cursor:
                    # 主线程同一连接查询活动；不新增第三条 observer 连接。
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = %s",
                        [backend_ids[0]],
                    )
                    row = cursor.fetchone()
                if row and row[0] == "Lock" and "FOR UPDATE" in row[1] and expected_table in row[1]:
                    print("B037-R01 observed PG lock wait:", mode, lock_target, backend_ids[0], row[0])
                    return
                time.sleep(0.01)
            self.fail("worker did not enter the expected PostgreSQL row-lock wait")

        def state():
            return (
                NewsArticle.objects.filter(pk=self.article.pk).values(
                    "translation_status", "workflow_status", "automation_status", "body_zh",
                    "translated_body_zh", "translation_retry_count", "translation_next_retry_at",
                    "translation_started_at", "translated_at", "translation_metadata", "decision_reason",
                ).get(),
                TranslationRun.objects.filter(pk=run.pk).values(
                    "status", "raw_response", "error_message", "model_name", "provider_name",
                ).get(),
            )

        thread = Thread(target=worker, daemon=True)
        self.notification.reset_mock()
        self.automation.reset_mock()
        self.mail.reset_mock()
        with patch("stable.tasks.translate_article", side_effect=provider) as translate:
            try:
                if mode != "consume":
                    thread.start()
                    self.assertTrue(backend_ready.wait(5))
                    self.assertTrue(provider_ready.wait(5))
                with transaction.atomic():
                    model, pk = (NewsArticle, self.article.pk) if lock_target == "article" else (TranslationRun, run.pk)
                    model.objects.select_for_update().get(pk=pk)
                    before = state()
                    if mode == "consume":
                        thread.start()
                        self.assertTrue(backend_ready.wait(5))
                    else:
                        release_provider.set()
                    observe_actual_lock_wait()
                    # article锁测试精确到期，run锁测试越过一秒；原claim字段不改。
                    self.now = deadline + timedelta(seconds=int(lock_target == "run"))
                thread.join(10)
            finally:
                release_provider.set()
                if thread.ident is not None:
                    thread.join(10)
        self.assertFalse(thread.is_alive(), "owned worker thread must exit")
        self.assertEqual(state(), before)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("reason"), "claim_expired")
        self.assertEqual(translate.call_count, 0 if mode == "consume" else 1)
        self.automation.assert_not_called()
        self.notification.assert_not_called()
        self.mail.assert_not_called()

    def test_consumption_waiting_for_locks_past_deadline_never_calls_provider(self):
        for target in ("article", "run"):
            with self.subTest(lock_target=target):
                self.locked_deadline_case("consume", target)

    def test_success_waiting_for_locks_past_deadline_never_commits_or_dispatches(self):
        for target in ("article", "run"):
            with self.subTest(lock_target=target):
                self.locked_deadline_case("success", target)

    def test_terminal_error_waiting_for_locks_past_deadline_never_commits_or_notifies(self):
        for target in ("article", "run"):
            with self.subTest(lock_target=target):
                self.locked_deadline_case("terminal", target)
