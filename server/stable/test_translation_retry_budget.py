"""B041：schema 技术检查与未实施业务 RED 明确分组。"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from threading import Barrier, Thread
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase

from stable.models import TranslationRequestAttempt, TranslationRetryBudget, TranslationRun
from stable.services import translation_retry_budget as core
from stable.test_translation_failure_recovery_change import article_for_retry

NOW = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)


def identity_digest(site, source_id):
    return hashlib.sha256(json.dumps(
        ["managed-translation-request-source-v1", site, source_id],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class BudgetFixture(TransactionTestCase):
    def setUp(self):
        self.article = article_for_retry(source_article_id="b041-exact-source")
        self.values = dict(
            operation_uuid=uuid4(), budget_uuid=uuid4(), scope_kind="managed_translation_retry",
            article_pk_snapshot=self.article.pk, source_site_snapshot=self.article.source_site,
            source_article_id_snapshot=self.article.source_article_id,
            identity_sha256=identity_digest(self.article.source_site, self.article.source_article_id),
            source_sha256="a" * 64, provider_snapshot="synthetic", model_snapshot="offline-only",
            policy_snapshot={"mode": "offline_test", "version": 1}, policy_sha256="b" * 64,
            opened_at=NOW, deadline_at=NOW + timedelta(minutes=30), request_limit=2,
        )
        self.budget = TranslationRetryBudget.objects.create(**self.values)
        self.identity = core.BudgetIdentity(
            self.values["scope_kind"], self.article.source_site, self.article.source_article_id,
            "a" * 64, "b" * 64, "synthetic", "offline-only",
            self.budget.operation_uuid, self.article.pk,
        )

    def attempt(self, **overrides):
        values = dict(
            budget=self.budget, operation_uuid=self.budget.operation_uuid,
            budget_uuid=self.budget.budget_uuid, claim_execution_uuid=uuid4(),
            article_pk_snapshot=self.article.pk, run_pk_snapshot=None, claimed_at=NOW,
            source_site_snapshot=self.article.source_site,
            source_article_id_snapshot=self.article.source_article_id,
            identity_sha256=self.budget.identity_sha256, source_sha256="a" * 64,
            seq=1, provider_attempt_index=1, reserved_at=NOW,
        )
        values.update(overrides)
        return TranslationRequestAttempt.objects.create(**values)

    def reserve(self, identity=None, **overrides):
        values = dict(mode="offline_test", now=NOW, claim_execution_uuid=uuid4(),
                      claimed_at=NOW, provider_attempt_index=1)
        values.update(overrides)
        return core.reserve_request(identity or self.identity, **values)

    def parallel(self, action):
        self.assertEqual(connection.vendor, "postgresql", "须官方隔离 PG，不能以 SQLite 替代")
        barrier = Barrier(2, timeout=10)
        results, errors, pids = [], [], []

        def worker():
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                barrier.wait()
                results.append(action())
            except BaseException as error:
                errors.append(error)
            finally:
                connections["default"].close()

        threads = [Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertFalse(any(thread.is_alive() for thread in threads), "线程未清理")
        self.assertEqual(errors, [], "连接/fixture/接口错误不得称业务 RED")
        self.assertEqual(len(set(pids)), 2)
        return results


class TranslationBudgetSchemaTests(BudgetFixture):
    def test_active_source_unique_including_closed(self):
        # 普通 ORM 不是此 SQL 唯一性测试对象；初建 closed 记录仍占来源。
        other = dict(self.values, operation_uuid=uuid4(), budget_uuid=uuid4(), state="closed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TranslationRetryBudget.objects.create(**other)

    def test_counter_bounds_database(self):
        for limit, reserved in ((0, 0), (2, 3)):
            with self.subTest(limit=limit, reserved=reserved):
                values = dict(self.values, operation_uuid=uuid4(), budget_uuid=uuid4(),
                              source_article_id_snapshot=f"bounds-{limit}",
                              request_limit=limit, requests_reserved=reserved)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    TranslationRetryBudget.objects.create(**values)

    def test_attempt_unique_sequence_and_claim_index_database(self):
        attempt = self.attempt()
        for changes in ({"claim_execution_uuid": uuid4()},
                        {"seq": 2, "claim_execution_uuid": attempt.claim_execution_uuid}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                self.attempt(**changes)

    def test_audit_orm_guards_separate_from_database(self):
        attempt = self.attempt()
        for obj in (self.budget, attempt):
            manager = type(obj).objects
            actions = (
                lambda: obj.delete(), lambda: manager.filter(pk=obj.pk).delete(),
                lambda: manager.filter(pk=obj.pk).update(state="closed"),
                lambda: manager.bulk_update([obj], ["state"]), lambda: obj.save(),
                lambda: manager.bulk_create([obj], update_conflicts=True,
                                            update_fields=["state"], unique_fields=["id"]),
            )
            for action in actions:
                with self.assertRaises(ValidationError):
                    action()
        # 不可借 _state.adding + 相同 PK 覆盖不可变身份。
        with self.assertRaises(IntegrityError), transaction.atomic():
            TranslationRetryBudget(id=self.budget.pk, **dict(self.values, source_sha256="c" * 64)).save()

    def test_article_delete_preserves_independent_audit(self):
        run = TranslationRun.objects.create(article=self.article, provider_name="synthetic",
                                            model_name="offline-only", status="started")
        run_pk = run.pk
        attempt = self.attempt(run_pk_snapshot=run_pk)
        pk = self.article.pk
        self.article.delete()
        self.budget.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual((self.budget.article_pk_snapshot, attempt.article_pk_snapshot), (pk, pk))
        self.assertEqual(attempt.run_pk_snapshot, run_pk)
        self.assertFalse(TranslationRun.objects.filter(pk=run_pk).exists())
        for model in (TranslationRetryBudget, TranslationRequestAttempt):
            relations = [field for field in model._meta.fields if field.is_relation]
            self.assertTrue(all(field.related_model is TranslationRetryBudget for field in relations))
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
            foreign_tables = [item["foreign_key"][0] for item in constraints.values()
                              if item.get("foreign_key")]
            self.assertEqual(foreign_tables, [] if model is TranslationRetryBudget
                             else [TranslationRetryBudget._meta.db_table])

    def test_production_mode_refuses_without_writes(self):
        before = (TranslationRetryBudget.objects.count(), TranslationRequestAttempt.objects.count())
        result = self.reserve(mode="production")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "supported_mode_missing")
        self.assertEqual(before, (TranslationRetryBudget.objects.count(), TranslationRequestAttempt.objects.count()))


class TranslationBudgetCoreRedTests(BudgetFixture):
    def test_reservation_persists_counter_and_attempt(self):
        result = self.reserve()
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.count(), 1)
        self.assertTrue(result.allowed)
        self.assertEqual(result.budget_pk, self.budget.pk)

    def test_unknown_consumption_blocks_new_claim_with_specific_reason(self):
        # 正常初建带已用槽/unknown，非绕过普通 ORM update guard。
        self.values.update(operation_uuid=uuid4(), budget_uuid=uuid4(),
                           source_article_id_snapshot="unknown", requests_reserved=1)
        self.budget = TranslationRetryBudget.objects.create(**self.values)
        self.article.source_article_id = "unknown"
        self.attempt(state="unknown")
        identity = core.BudgetIdentity(self.budget.scope_kind, self.article.source_site, "unknown",
                                       "a" * 64, "b" * 64, "synthetic", "offline-only",
                                       self.budget.operation_uuid, self.article.pk)
        result = self.reserve(identity)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "usage_unknown")
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)

    def test_same_source_delete_recreate_resolves_retained_root(self):
        self.article = article_for_retry(source_article_id="delete-recreate-used")
        values = dict(self.values, operation_uuid=uuid4(), budget_uuid=uuid4(),
                      source_article_id_snapshot=self.article.source_article_id,
                      article_pk_snapshot=self.article.pk, requests_reserved=1)
        self.budget = TranslationRetryBudget.objects.create(**values)
        attempt = self.attempt(state="unknown")
        old_pk = self.article.pk
        self.article.delete()
        new_article = article_for_retry(source_article_id="delete-recreate-used")
        self.assertNotEqual(old_pk, new_article.pk)
        identity = core.BudgetIdentity(self.budget.scope_kind, new_article.source_site,
                                       new_article.source_article_id, "a" * 64, "b" * 64,
                                       "synthetic", "offline-only", None, new_article.pk)
        result = core.resolve_budget(identity, mode="offline_test", now=NOW)
        self.assertEqual(result.budget_pk, self.budget.pk)
        self.assertEqual(TranslationRetryBudget.objects.count(), 2)
        self.budget.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.deadline_at, self.values["deadline_at"])
        self.assertEqual(attempt.state, "unknown")
        result = self.reserve(identity)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "usage_unknown")

    def test_old_operation_cannot_authorize_reused_pk_new_source(self):
        old_pk = self.article.pk
        self.article.delete()
        new_article = article_for_retry(id=old_pk, source_article_id="other-source")
        identity = core.BudgetIdentity(self.budget.scope_kind, new_article.source_site,
                                       new_article.source_article_id, "a" * 64, "b" * 64,
                                       "synthetic", "offline-only", self.budget.operation_uuid, old_pk)
        result = self.reserve(identity)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "identity_changed")
        self.assertEqual(TranslationRequestAttempt.objects.count(), 0)

    def test_two_consumers_last_slot_single_reservation(self):
        values = dict(self.values, operation_uuid=uuid4(), budget_uuid=uuid4(),
                      source_article_id_snapshot="last-slot", request_limit=1)
        self.budget = TranslationRetryBudget.objects.create(**values)
        self.identity = core.BudgetIdentity(self.budget.scope_kind, self.budget.source_site_snapshot,
                                            "last-slot", "a" * 64, "b" * 64, "synthetic", "offline-only",
                                            self.budget.operation_uuid, self.article.pk)
        results = self.parallel(self.reserve)
        self.assertEqual(sum(result.allowed for result in results), 1)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.count(), 1)

    def test_concurrent_first_create_resolves_one_authoritative_root(self):
        identity = core.BudgetIdentity(self.budget.scope_kind, self.budget.source_site_snapshot,
                                       "first-create", "a" * 64, "b" * 64, "synthetic", "offline-only")
        contract = dict(request_limit=2, opened_at=NOW, deadline_at=NOW + timedelta(minutes=30),
                        policy_snapshot={"mode": "offline_test", "version": 1},
                        baseline_receipt={"kind": "synthetic_no_prior_consumption"})
        results = self.parallel(lambda: core.resolve_budget(
            identity, mode="offline_test", now=NOW, initial_contract=contract))
        roots = TranslationRetryBudget.objects.filter(source_article_id_snapshot="first-create")
        self.assertEqual(roots.count(), 1)
        self.assertEqual({result.budget_pk for result in results}, {roots.get().pk})
