"""B039：现有 task 入口的结果检查点 RED；没有业务占位或真实调用。"""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from threading import Barrier, Event, Thread
from types import SimpleNamespace
import time
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import SimpleTestCase

from stable.models import NewsArticle, TranslationRun
from stable.services import translation_recovery as recovery
from stable.tasks import translate_article_task
from stable.test_translation_claim_fence import TranslationClaimFixture


RESULT_KEY = "recovery_result_v1"
CONTRACT_VERSION = "translation-result-apply-v1"


class SimulatedProcessExit(BaseException):
    """模拟终态事务内退出，不被现有 provider except Exception 捕获。"""


def checkpoint_digest(payload):
    unsigned = {key: value for key, value in payload.items() if key != "payload_sha256"}
    encoded = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TranslationResultCheckpointFixture(TranslationClaimFixture):
    def full_result(self):
        result = self.translation_result()
        result.metadata.update({
            "terms": [], "accepted_term_ids": [], "entities": [],
            "usage": {}, "raw": {"body_zh": "原始未恢复文本"},
            "warning": "mock-only-result-not-real-cost",
        })
        return result

    def result_checkpoint(self, run, *, suppress=False, usage=None):
        claim = run.raw_response[recovery.CLAIM_KEY]
        result = self.full_result()
        if usage is not None:
            result.metadata["usage"] = usage
        payload = {
            "schema_version": 1, "application_contract_version": CONTRACT_VERSION,
            "article_id": self.article.pk, "run_id": run.pk,
            "claimed_at": claim["claimed_at"], "input_sha256": claim["input_sha256"],
            "deadline_at": claim["deadline_at"], "checkpoint_at": self.now.isoformat(),
            "title_zh": result.title_zh, "body_zh": result.body_zh,
            "push_summary_zh": result.push_summary_zh, "metadata": result.metadata,
            "suppress_automation": suppress,
            "usage_report": deepcopy(result.metadata["usage"]),
            "usage_reconciliation": "unreconciled",
        }
        payload["payload_sha256"] = checkpoint_digest(payload)
        return payload

    def stored_checkpoint(self, *, suppress=False, usage=None):
        args, kwargs, run = self.claimed_message()
        article, consumed, reason = recovery.consume_translation_claim(*args, run.pk, kwargs["claim_started_at"])
        self.assertEqual(reason, "")
        self.assertEqual(article.pk, self.article.pk)
        self.assertEqual(consumed.pk, run.pk)
        run.refresh_from_db()
        checkpoint = self.result_checkpoint(run, suppress=suppress, usage=usage)
        run.raw_response = {**run.raw_response, RESULT_KEY: checkpoint}
        run.save(update_fields=["raw_response", "updated_at"])
        return args, kwargs, run, checkpoint

    def replay(self, args, kwargs):
        with patch("stable.tasks.translate_article") as provider:
            with patch("stable.services.translation.get_translation_provider") as factory:
                with patch("stable.services.translation.resolve_article_entities_for_article") as resolver:
                    result = translate_article_task.run(*args, **kwargs)
        provider.assert_not_called()
        factory.assert_not_called()
        resolver.assert_not_called()
        self.notification.assert_not_called()
        self.mail.assert_not_called()
        return result

    def article_snapshot(self):
        return NewsArticle.objects.values(
            "translation_status", "translation_started_at", "translation_retry_count",
            "translation_next_retry_at", "translation_metadata", "title_zh", "body_zh",
            "translated_title_zh", "translated_body_zh", "manually_edited_fields",
        ).get(pk=self.article.pk)

    def assert_skipped_without_mutation(self, args, kwargs, run):
        before = self.article_snapshot()
        run.refresh_from_db()
        raw, status = deepcopy(run.raw_response), run.status
        result = self.replay(args, kwargs)
        self.assertTrue(result.get("skipped"), result)
        self.assertFalse(result.get("translated"), result)
        self.assertEqual(self.article_snapshot(), before)
        run.refresh_from_db()
        self.assertEqual(run.raw_response, raw)
        self.assertEqual(run.status, status)
        self.automation.assert_not_called()


class TranslationResultCheckpointRedTests(TranslationResultCheckpointFixture):
    def test_validated_result_survives_exit_before_terminal_commit(self):
        args, kwargs, run = self.claimed_message()
        result = self.full_result()
        save = TranslationRun.save

        def exit_before_terminal(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "success":
                raise SimulatedProcessExit("mock exit inside terminal transaction")
            return save(instance, *save_args, **save_kwargs)

        with patch("stable.tasks.translate_article", return_value=result) as provider:
            with patch.object(TranslationRun, "save", new=exit_before_terminal):
                with self.assertRaises(SimulatedProcessExit):
                    translate_article_task.run(*args, **kwargs)
        provider.assert_called_once()
        run.refresh_from_db()
        self.article.refresh_from_db()
        self.assertEqual(run.status, "started")
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.body_zh, "")
        self.automation.assert_not_called()
        self.notification.assert_not_called()
        self.assertIn(RESULT_KEY, run.raw_response, "完整结果必须先独立提交，而不是与终态一同回滚")
        checkpoint = run.raw_response[RESULT_KEY]
        self.assertEqual(checkpoint["body_zh"], result.body_zh)
        self.assertEqual(checkpoint["metadata"], result.metadata)
        self.assertIs(checkpoint["suppress_automation"], False)
        self.assertEqual(checkpoint["usage_reconciliation"], "unreconciled")
        self.assertEqual(checkpoint["payload_sha256"], checkpoint_digest(checkpoint))
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY]["phase"], "executing")

    def test_same_envelope_resumes_committed_result_without_provider(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        result = self.replay(args, kwargs)
        self.assertTrue(result.get("translated"), result)
        self.assertFalse(result.get("skipped"), result)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.body_zh, checkpoint["body_zh"])
        self.assertNotEqual(self.article.body_zh, checkpoint["metadata"]["raw"]["body_zh"])
        self.assertEqual(self.article.translation_metadata["usage"], {})
        self.assertEqual(run.raw_response[RESULT_KEY], checkpoint)
        self.assertEqual(run.raw_response[RESULT_KEY]["usage_reconciliation"], "unreconciled")
        self.assertEqual(run.status, "success")
        self.assertEqual(self.automation.call_count, 1)
        replayed = self.replay(args, kwargs)
        self.assertTrue(replayed.get("skipped"), replayed)
        self.assertEqual(self.automation.call_count, 1)

    def test_two_postgresql_replayers_commit_one_terminal_result(self):
        self.assertEqual(connection.vendor, "postgresql", "此断言必须在指定PG窗执行，不能SQLite冒真并发")
        args, kwargs, run, _ = self.stored_checkpoint()
        barrier = Barrier(3, timeout=8)
        results, errors, backend_ids, closed = [], [], [], []

        def worker():
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_ids.append(cursor.fetchone()[0])
                barrier.wait()
                results.append(translate_article_task.run(*args, **kwargs))
            except BaseException as exc:
                errors.append(repr(exc))
            finally:
                connections.close_all()
                closed.append(connections["default"].connection is None)

        threads = [Thread(target=worker, daemon=True) for _ in range(2)]
        with patch("stable.tasks.translate_article") as provider:
            with patch("stable.services.translation.get_translation_provider") as factory:
                try:
                    for thread in threads:
                        thread.start()
                    barrier.wait()
                    for thread in threads:
                        thread.join(timeout=12)
                finally:
                    barrier.abort()
                    for thread in threads:
                        if thread.ident is not None:
                            thread.join(timeout=12)
            factory.assert_not_called()
        self.assertFalse(any(thread.is_alive() for thread in threads), "残留线程不可继续测试")
        self.assertEqual(errors, [])
        self.assertEqual(len(set(backend_ids)), 2)
        self.assertEqual(closed, [True, True])
        print(f"B039 checkpoint actual PG backends={sorted(backend_ids)} closed={closed}", flush=True)
        provider.assert_not_called()
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(bool(item.get("translated")) for item in results), 1, results)
        self.assertEqual(sum(bool(item.get("skipped")) for item in results), 1, results)
        run.refresh_from_db()
        self.assertEqual(run.status, "success")
        self.assertEqual(self.automation.call_count, 1)
        self.notification.assert_not_called()
        self.mail.assert_not_called()


class TranslationResultCheckpointBoundaryTests(TranslationResultCheckpointFixture):
    def test_terminal_save_failure_keeps_checkpoint_for_later_local_resume(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        before = self.article_snapshot()
        save = TranslationRun.save

        def fail_terminal(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "success":
                raise RuntimeError("mock terminal save failure")
            return save(instance, *save_args, **save_kwargs)

        with patch("stable.tasks.translate_article") as provider:
            with patch.object(TranslationRun, "save", new=fail_terminal):
                with self.assertRaisesRegex(RuntimeError, "mock terminal save failure"):
                    translate_article_task.run(*args, **kwargs)
        provider.assert_not_called()
        self.assertEqual(self.article_snapshot(), before)
        run.refresh_from_db()
        self.assertEqual(run.raw_response[RESULT_KEY], checkpoint)
        self.assertEqual(run.status, "started")
        self.automation.assert_not_called()
        self.assertTrue(self.replay(args, kwargs).get("translated"))

    def test_resume_keeps_current_manual_fields_and_complete_metadata(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        NewsArticle.objects.filter(pk=self.article.pk).update(
            body_zh="编辑保留正文", manually_edited_fields=["body_zh"],
        )
        self.assertTrue(self.replay(args, kwargs).get("translated"))
        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "编辑保留正文")
        self.assertEqual(self.article.translated_body_zh, checkpoint["body_zh"])
        for key, value in checkpoint["metadata"].items():
            self.assertEqual(self.article.translation_metadata[key], value)

    def test_persisted_suppress_policy_cannot_be_enabled_by_replay_argument(self):
        args, kwargs, _, _ = self.stored_checkpoint(suppress=True)
        kwargs["suppress_automation"] = False
        self.assertTrue(self.replay(args, kwargs).get("translated"))
        self.automation.assert_not_called()

    def test_persisted_allow_policy_is_not_replaced_by_replay_argument(self):
        args, kwargs, _, _ = self.stored_checkpoint(suppress=False)
        kwargs["suppress_automation"] = True
        self.assertTrue(self.replay(args, kwargs).get("translated"))
        self.assertEqual(self.automation.call_count, 1)

    def test_original_deadline_at_and_after_cutoff_cannot_resume_or_extend(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        deadline = self.now + timedelta(seconds=1800)
        for advance in (0, 1):
            with self.subTest(seconds_after_deadline=advance):
                self.now = deadline + timedelta(seconds=advance)
                self.assert_skipped_without_mutation(args, kwargs, run)
                self.assertEqual(run.raw_response[RESULT_KEY]["deadline_at"], checkpoint["deadline_at"])

    def test_source_changed_cannot_resume_or_use_another_claim(self):
        args, kwargs, run, _ = self.stored_checkpoint()
        NewsArticle.objects.filter(pk=self.article.pk).update(body_ja_normalized="修改后的源正文")
        self.assert_skipped_without_mutation(args, kwargs, run)

    def test_old_checkpoint_cannot_resume_after_stale_recovery_and_new_claim(self):
        args, kwargs, old_run, _ = self.stored_checkpoint()
        newer, started = self.replace_with_new_claim()
        self.assert_skipped_without_mutation(args, kwargs, old_run)
        newer.refresh_from_db()
        self.assertEqual(newer.status, "started")
        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_started_at, started)

    def test_invalid_checkpoint_never_falls_through_to_provider_or_mutates_rows(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        cases = {
            "wrong_article": ("article_id", self.article.pk + 1000),
            "wrong_run": ("run_id", run.pk + 1000),
            "wrong_claim": ("claimed_at", "2000-01-01T00:00:00+00:00"),
            "wrong_source": ("input_sha256", "0" * 64),
            "extended_deadline": ("deadline_at", (self.now + timedelta(days=1)).isoformat()),
            "unknown_schema": ("schema_version", 999),
            "bool_schema": ("schema_version", True),
            "unknown_contract": ("application_contract_version", "unknown-v99"),
            "empty_body": ("body_zh", ""),
            "nonstring_body": ("body_zh", ["invalid"]),
            "bad_metadata": ("metadata", []),
            "bad_suppress": ("suppress_automation", "false"),
            "bad_terms": ("metadata", {**checkpoint["metadata"], "terms": "bad"}),
            "bad_tags": ("metadata", {**checkpoint["metadata"], "machine_horse_tags": "bad"}),
            "reserved_claim": ("metadata", {**checkpoint["metadata"], recovery.CLAIM_KEY: {}}),
            "reserved_result": ("metadata", {**checkpoint["metadata"], RESULT_KEY: {}}),
            "oversize": ("body_zh", "x" * (2 * 1024 * 1024 + 1)),
        }
        nested = "leaf"
        for _ in range(34):
            nested = {"nested": nested}
        cases["too_deep"] = ("metadata", {**checkpoint["metadata"], "debug": nested})
        for name, (key, value) in cases.items():
            with self.subTest(case=name):
                invalid = {**deepcopy(checkpoint), key: value}
                invalid["payload_sha256"] = checkpoint_digest(invalid)
                run.raw_response = {**run.raw_response, RESULT_KEY: invalid}
                run.save(update_fields=["raw_response", "updated_at"])
                self.assert_skipped_without_mutation(args, kwargs, run)
        for bad in (None, [], "bad", {**checkpoint, "payload_sha256": "0" * 64}):
            with self.subTest(invalid_container_or_hash=type(bad).__name__):
                run.raw_response = {**run.raw_response, RESULT_KEY: bad}
                run.save(update_fields=["raw_response", "updated_at"])
                self.assert_skipped_without_mutation(args, kwargs, run)

    def test_unreconciled_usage_can_resume_locally_without_zero_cost_invention(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        for usage in ({}, {"repr": "not-billable-usage"}, {"total_tokens": -1}, {"total_tokens": 12}):
            with self.subTest(reported_usage=usage):
                payload = deepcopy(checkpoint)
                payload["metadata"]["usage"] = usage
                payload["usage_report"] = usage
                payload["payload_sha256"] = checkpoint_digest(payload)
                run.status = "started"
                run.raw_response = {
                    recovery.CLAIM_KEY: {**run.raw_response[recovery.CLAIM_KEY], "phase": "executing"},
                    RESULT_KEY: payload,
                }
                run.save(update_fields=["status", "raw_response", "updated_at"])
                NewsArticle.objects.filter(pk=self.article.pk).update(
                    translation_status="translating", translation_started_at=self.now,
                )
                self.assertTrue(self.replay(args, kwargs).get("translated"))
                run.refresh_from_db()
                self.assertEqual(run.raw_response[RESULT_KEY], payload)
                self.assertEqual(run.raw_response[RESULT_KEY]["usage_reconciliation"], "unreconciled")
                self.assertNotIn("cost", run.raw_response[RESULT_KEY])

    def test_executing_without_checkpoint_still_skips_without_new_provider(self):
        args, kwargs, run = self.claimed_message()
        _, _, reason = recovery.consume_translation_claim(*args, run.pk, kwargs["claim_started_at"])
        self.assertEqual(reason, "")
        self.assert_skipped_without_mutation(args, kwargs, run)

    def test_fresh_provider_metadata_cannot_supply_internal_checkpoint_keys(self):
        args, kwargs, run = self.claimed_message()
        result = self.full_result()
        result.metadata[RESULT_KEY] = {"forged": True}
        with patch("stable.tasks.translate_article", return_value=result) as provider:
            response = translate_article_task.run(*args, **kwargs)
        provider.assert_called_once()
        self.assertTrue(response.get("skipped"), response)
        self.assertFalse(response.get("translated"), response)
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertNotIn(RESULT_KEY, run.raw_response)
        self.automation.assert_not_called()
        self.notification.assert_not_called()
        self.mail.assert_not_called()


class TranslationResultCheckpointFailureTests(TranslationResultCheckpointFixture):
    def test_first_execution_suppress_survives_terminal_exit_and_changed_replay_argument(self):
        args, kwargs, run = self.claimed_message()
        kwargs["suppress_automation"] = True
        save = TranslationRun.save

        def exit_terminal(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "success":
                raise SimulatedProcessExit("mock exit with suppress policy")
            return save(instance, *save_args, **save_kwargs)

        with patch("stable.tasks.translate_article", return_value=self.full_result()) as provider:
            with patch.object(TranslationRun, "save", new=exit_terminal):
                with self.assertRaises(SimulatedProcessExit):
                    translate_article_task.run(*args, **kwargs)
        provider.assert_called_once()
        run.refresh_from_db()
        self.assertIs(run.raw_response[recovery.CLAIM_KEY]["suppress_automation"], True)
        self.assertIs(run.raw_response[RESULT_KEY]["suppress_automation"], True)
        kwargs["suppress_automation"] = False
        self.assertTrue(self.replay(args, kwargs).get("translated"))
        self.automation.assert_not_called()

    def test_checkpoint_write_failure_does_not_count_provider_failure_or_recall(self):
        args, kwargs, run = self.claimed_message()
        save = TranslationRun.save

        def fail_checkpoint(instance, *save_args, **save_kwargs):
            if instance.pk == run.pk and instance.status == "started" and RESULT_KEY in instance.raw_response:
                raise RuntimeError("mock independent checkpoint save failure")
            return save(instance, *save_args, **save_kwargs)

        with patch("stable.tasks.translate_article", return_value=self.full_result()) as provider:
            with patch.object(TranslationRun, "save", new=fail_checkpoint):
                with self.assertRaisesRegex(RuntimeError, "independent checkpoint save failure"):
                    translate_article_task.run(*args, **kwargs)
        provider.assert_called_once()
        self.article.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY]["phase"], "executing")
        self.assertNotIn(RESULT_KEY, run.raw_response)
        self.assert_skipped_without_mutation(args, kwargs, run)

    def test_original_worker_loses_to_replayer_after_checkpoint_commit(self):
        self.assertEqual(connection.vendor, "postgresql")
        args, kwargs, run = self.claimed_message()
        committed, release = Event(), Event()
        results, errors, backend_ids, closed = [], [], [], []
        save_checkpoint = recovery.save_translation_checkpoint

        def pause_after_commit(*call_args, **call_kwargs):
            self.assertFalse(connection.in_atomic_block)
            value = save_checkpoint(*call_args, **call_kwargs)
            self.assertEqual(value[1], "")
            self.assertFalse(connection.in_atomic_block)
            committed.set()
            if not release.wait(10):
                raise AssertionError("original worker release timed out")
            return value

        def worker():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_ids.append(cursor.fetchone()[0])
                results.append(translate_article_task.run(*args, **kwargs))
            except BaseException as exc:
                errors.append(repr(exc))
            finally:
                connections.close_all()
                closed.append(connection.connection is None)

        thread = Thread(target=worker, daemon=True)
        with patch("stable.tasks.translate_article", return_value=self.full_result()) as provider:
            with patch.object(recovery, "save_translation_checkpoint", side_effect=pause_after_commit):
                try:
                    thread.start()
                    self.assertTrue(committed.wait(8))
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        backend_ids.append(cursor.fetchone()[0])
                    replayed = translate_article_task.run(*args, **kwargs)
                    self.assertTrue(replayed.get("translated"), replayed)
                finally:
                    release.set()
                    thread.join(12)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(closed, [True])
        self.assertEqual(len(set(backend_ids)), 2)
        print(f"B039 original/replay actual PG backends={sorted(backend_ids)} worker_closed={closed}", flush=True)
        provider.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].get("skipped"), results)
        run.refresh_from_db()
        self.assertEqual(run.status, "success")
        self.assertEqual(self.automation.call_count, 1)
        self.notification.assert_not_called()
        self.mail.assert_not_called()

    def test_provider_error_cannot_replace_already_committed_success_checkpoint(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        before = self.article_snapshot()
        _, reason = recovery.finalize_translation_claim(
            self.article.pk, run.pk, kwargs["claim_started_at"], error=ValueError("late provider error"),
        )
        self.assertEqual(reason, "checkpoint_exists")
        self.assertEqual(self.article_snapshot(), before)
        run.refresh_from_db()
        self.assertEqual(run.raw_response[RESULT_KEY], checkpoint)
        self.notification.assert_not_called()
        self.mail.assert_not_called()

    def test_another_result_digest_cannot_replace_first_checkpoint(self):
        args, kwargs, run, checkpoint = self.stored_checkpoint()
        other = deepcopy(checkpoint)
        other["body_zh"] = "另一个结果"
        other["payload_sha256"] = checkpoint_digest(other)
        saved, reason = recovery.save_translation_checkpoint(self.article.pk, run.pk, kwargs["claim_started_at"], other)
        self.assertIsNone(saved)
        self.assertEqual(reason, "checkpoint_conflict")
        run.refresh_from_db()
        self.assertEqual(run.raw_response[RESULT_KEY], checkpoint)
        self.assertEqual(self.article_snapshot()["translation_status"], "translating")
        self.automation.assert_not_called()


class TranslationResultCheckpointLockDeadlineTests(TranslationResultCheckpointFixture):
    def locked_checkpoint_case(self, mode, target):
        self.assertEqual(connection.vendor, "postgresql")
        if self.article.translation_runs.exists():
            from stable.test_translation_failure_recovery_change import article_for_retry
            from stable.test_translation_claim_fence import NOW
            self.now = NOW
            self.article = article_for_retry(translation_next_retry_at=self.now)
        if mode == "save":
            args, kwargs, run = self.claimed_message()
        else:
            args, kwargs, run, _ = self.stored_checkpoint()
        deadline = self.now + timedelta(seconds=1800)
        self.now = deadline - timedelta(seconds=1)
        stage_ready, release_stage, backend_ready = Event(), Event(), Event()
        backend_ids, results, errors, closed = [], [], [], []
        finalize = recovery.finalize_translation_claim
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            blocker_pid = cursor.fetchone()[0]

        def provider(*_args, **_kwargs):
            self.assertFalse(connection.in_atomic_block)
            stage_ready.set()
            if not release_stage.wait(10):
                raise AssertionError("checkpoint provider handoff timed out")
            return self.full_result()

        def pause_final(*call_args, **call_kwargs):
            self.assertFalse(connection.in_atomic_block)
            stage_ready.set()
            if not release_stage.wait(10):
                raise AssertionError("checkpoint finalizer handoff timed out")
            return finalize(*call_args, **call_kwargs)

        def worker():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_ids.append(cursor.fetchone()[0])
                backend_ready.set()
                results.append(translate_article_task.run(*args, **kwargs))
            except BaseException as exc:
                errors.append(repr(exc))
            finally:
                connections.close_all()
                closed.append(connection.connection is None)

        def snapshot():
            return self.article_snapshot(), TranslationRun.objects.values("raw_response", "status", "error_message").get(pk=run.pk)

        def observe_wait():
            stop = time.monotonic() + 5
            table = "stable_newsarticle" if target == "article" else "stable_translationrun"
            while time.monotonic() < stop:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute("SELECT wait_event_type, query, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s", [backend_ids[0]])
                    row = cursor.fetchone()
                if row and row[0] == "Lock" and table in row[1] and blocker_pid in row[2]:
                    print(f"B039 checkpoint PG lock mode={mode} target={target} worker={backend_ids[0]} blocker={blocker_pid}", flush=True)
                    return
                time.sleep(0.01)
            self.fail("checkpoint worker never entered exact-owner PG lock wait")

        thread = Thread(target=worker, daemon=True)
        self.automation.reset_mock()
        self.notification.reset_mock()
        self.mail.reset_mock()
        with patch("stable.tasks.translate_article", side_effect=provider) as translated:
            with patch.object(recovery, "finalize_translation_claim", side_effect=pause_final if mode == "finalize" else finalize):
                try:
                    if mode != "entry":
                        thread.start()
                        self.assertTrue(backend_ready.wait(5))
                        self.assertTrue(stage_ready.wait(5))
                    with transaction.atomic():
                        model, pk = (NewsArticle, self.article.pk) if target == "article" else (TranslationRun, run.pk)
                        model.objects.select_for_update().get(pk=pk)
                        before = snapshot()
                        if mode == "entry":
                            thread.start()
                            self.assertTrue(backend_ready.wait(5))
                        else:
                            release_stage.set()
                        observe_wait()
                        self.now = deadline + timedelta(seconds=int(target == "run"))
                    thread.join(10)
                finally:
                    release_stage.set()
                    if thread.ident is not None:
                        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(closed, [True])
        self.assertEqual(snapshot(), before)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("reason"), "claim_expired", results)
        self.assertEqual(translated.call_count, 1 if mode == "save" else 0)
        self.automation.assert_not_called()
        self.notification.assert_not_called()
        self.mail.assert_not_called()

    def test_checkpoint_save_waiting_for_either_lock_cannot_commit_after_deadline(self):
        for target in ("article", "run"):
            with self.subTest(lock_target=target):
                self.locked_checkpoint_case("save", target)

    def test_checkpoint_resume_entry_waiting_for_either_lock_cannot_extend_deadline(self):
        for target in ("article", "run"):
            with self.subTest(lock_target=target):
                self.locked_checkpoint_case("entry", target)

    def test_checkpoint_terminal_waiting_for_either_lock_cannot_commit_after_deadline(self):
        for target in ("article", "run"):
            with self.subTest(lock_target=target):
                self.locked_checkpoint_case("finalize", target)


class TranslationResultCheckpointCodecTests(SimpleTestCase):
    def payload(self):
        from stable.test_translation_claim_fence import NOW
        claim = {"claimed_at": NOW.isoformat(), "deadline_at": (NOW + timedelta(minutes=30)).isoformat(), "input_sha256": "a" * 64}
        article = SimpleNamespace(pk=7)
        run = SimpleNamespace(pk=9, raw_response={recovery.CLAIM_KEY: claim})
        result = SimpleNamespace(title_zh="标题", body_zh="正文", push_summary_zh="摘要", metadata={"provider": "dummy", "model": "mock-only", "terms": [], "machine_horse_tags": [], "usage": {}})
        with patch("django.utils.timezone.now", return_value=NOW):
            return recovery.build_translation_checkpoint(article, run, result, suppress_automation=True)

    def test_codec_roundtrip_preserves_unicode_unknown_usage_and_independent_snapshot(self):
        payload = self.payload()
        snapshot, result = recovery.decode_translation_checkpoint(payload, 7, 9, payload["claimed_at"])
        self.assertEqual(snapshot, payload)
        self.assertEqual(snapshot["payload_sha256"], checkpoint_digest(snapshot))
        self.assertEqual(result.body_zh, "正文")
        payload["metadata"]["usage"]["mutated"] = True
        self.assertEqual(snapshot["metadata"]["usage"], {})
        self.assertEqual(snapshot["usage_reconciliation"], "unreconciled")
        self.assertNotIn("cost", snapshot)

    def test_nonfinite_values_are_rejected_before_json_database_encoding(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                payload = self.payload()
                payload["metadata"]["debug"] = value
                with self.assertRaises(recovery.TranslationCheckpointError):
                    recovery.decode_translation_checkpoint(payload, 7, 9, payload["claimed_at"])

    def test_cycles_are_rejected_without_recursion_or_copy_hooks(self):
        for container in ({}, []):
            with self.subTest(kind=type(container).__name__):
                if isinstance(container, dict):
                    container["self"] = container
                else:
                    container.append(container)
                with self.assertRaises(recovery.TranslationCheckpointError):
                    recovery._checkpoint_json(container)

    def test_nonbuiltin_containers_values_and_keys_are_rejected(self):
        class HostileDict(dict):
            def __deepcopy__(self, memo):
                raise AssertionError("copy hook must never execute")

            def items(self):
                raise AssertionError("container hook must never execute")

        class HostileString(str):
            pass

        for value in (HostileDict(), HostileString("string"), ("tuple",), {"set"}, {1: "nonstring key"}, {HostileString("key"): "value"}):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(recovery.TranslationCheckpointError):
                    recovery._checkpoint_json(value)

    def test_exact_encoded_size_boundary_is_enforced_without_truncation(self):
        limit = recovery.RESULT_MAX_BYTES
        self.assertEqual(len(recovery._checkpoint_json("x" * (limit - 2))), limit)
        with self.assertRaises(recovery.TranslationCheckpointError):
            recovery._checkpoint_json("x" * (limit - 1))
        with self.assertRaises(recovery.TranslationCheckpointError):
            recovery._checkpoint_json("中" * limit)

    def test_exact_depth_boundary_is_enforced(self):
        value = "leaf"
        for _ in range(recovery.RESULT_MAX_DEPTH):
            value = [value]
        recovery._checkpoint_json(value)
        with self.assertRaises(recovery.TranslationCheckpointError):
            recovery._checkpoint_json([value])

    def test_invalid_timestamp_usage_report_and_cost_fields_cannot_be_reconciled(self):
        payload = self.payload()
        for key, value in (("checkpoint_at", "2026-10-06T00:00:00"), ("usage_report", {"total_tokens": 0}), ("usage_reconciliation", "known"), ("cost", 0)):
            with self.subTest(key=key):
                invalid = {**deepcopy(payload), key: value}
                invalid["payload_sha256"] = checkpoint_digest(invalid)
                with self.assertRaises(recovery.TranslationCheckpointError):
                    recovery.decode_translation_checkpoint(invalid, 7, 9, payload["claimed_at"])

    def test_bool_and_nonbuiltin_integer_cannot_be_run_identity(self):
        class Integer(int):
            pass

        for value in (True, Integer(9)):
            with self.subTest(kind=type(value).__name__):
                payload = self.payload()
                payload["run_id"] = value
                with self.assertRaises(recovery.TranslationCheckpointError):
                    recovery.decode_translation_checkpoint(payload, 7, 9, payload["claimed_at"])
