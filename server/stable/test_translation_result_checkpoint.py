"""B039：现有 task 入口的结果检查点 RED；没有业务占位或真实调用。"""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from threading import Barrier, Thread
from unittest.mock import patch

from django.db import connection, connections

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
