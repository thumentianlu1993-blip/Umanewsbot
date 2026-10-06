"""B041：schema 技术检查与未实施业务 RED 明确分组。"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Thread
from uuid import uuid4
from dataclasses import replace
import time
from unittest.mock import patch

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
        self.now = NOW
        clock = patch("django.utils.timezone.now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
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
                           source_article_id_snapshot="unknown", requests_reserved=1,
                           identity_sha256=identity_digest(self.article.source_site, "unknown"))
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
                      article_pk_snapshot=self.article.pk, requests_reserved=1,
                      identity_sha256=identity_digest(self.article.source_site, self.article.source_article_id))
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
                      source_article_id_snapshot="last-slot", request_limit=1,
                      identity_sha256=identity_digest(self.article.source_site, "last-slot"))
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


class BudgetCoreHelpersMixin:
    def fresh_root(self, suffix, **overrides):
        values = dict(self.values, operation_uuid=uuid4(), budget_uuid=uuid4(),
                      source_article_id_snapshot="boundary-" + suffix,
                      identity_sha256=identity_digest(self.article.source_site, "boundary-" + suffix))
        values.update(overrides)
        self.budget = TranslationRetryBudget.objects.create(**values)
        self.identity = replace(self.identity, source_article_id=self.budget.source_article_id_snapshot,
                                operation_uuid=self.budget.operation_uuid,
                                article_pk_snapshot=self.budget.article_pk_snapshot)
        return self.budget

    def usage(self):
        return {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}

    def receipt(self, result, report=None):
        raw = json.dumps(report or self.usage(), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return {"kind": "synthetic_offline_usage_v1", "budget_uuid": str(self.budget.budget_uuid),
                "attempt_pk": result.attempt_pk, "usage_sha256": hashlib.sha256(raw).hexdigest()}

    def reconcile(self, result):
        recorded = core.record_usage(budget_pk=self.budget.pk, attempt_pk=result.attempt_pk,
                                     mode="offline_test", usage_report=self.usage(),
                                     receipt=self.receipt(result))
        self.assertTrue(recorded.allowed)
        return recorded

    def contract(self, **overrides):
        contract = dict(request_limit=2, opened_at=NOW, deadline_at=NOW + timedelta(minutes=30),
                        policy_snapshot={"mode": "offline_test", "version": 1},
                        baseline_receipt={"kind": "synthetic_no_prior_consumption"})
        contract.update(overrides)
        return contract

class TranslationBudgetBoundaryTests(BudgetCoreHelpersMixin, BudgetFixture):
    def test_repeat_claim_index_and_pending_new_claim_never_refund(self):
        claim = uuid4()
        first = self.reserve(claim_execution_uuid=claim)
        replay = self.reserve(claim_execution_uuid=claim)
        self.assertTrue(first.allowed)
        self.assertFalse(replay.allowed)
        self.assertEqual((replay.reason, replay.attempt_pk), ("request_already_reserved", first.attempt_pk))
        self.assertEqual(self.reserve().reason, "usage_unknown")
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.count(), 1)

    def test_known_offline_receipt_allows_next_index_but_not_topup(self):
        claim = uuid4()
        first = self.reserve(claim_execution_uuid=claim)
        self.reconcile(first)
        second = self.reserve(claim_execution_uuid=claim, provider_attempt_index=2)
        self.assertTrue(second.allowed)
        self.reconcile(second)
        third = self.reserve(claim_execution_uuid=claim, provider_attempt_index=3)
        self.assertFalse(third.allowed)
        self.assertEqual(third.reason, "request_limit_exhausted")
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.request_limit, self.budget.requests_reserved), (2, 2))
        self.assertEqual(list(self.budget.request_attempts.values_list("seq", flat=True).order_by("seq")), [1, 2])

    def test_usage_without_receipt_and_fake_money_remain_unreconciled(self):
        first = self.reserve()
        result = core.record_usage(budget_pk=self.budget.pk, attempt_pk=first.attempt_pk,
                                   mode="offline_test", usage_report=self.usage(),
                                   receipt={"price": 0, "currency": "synthetic"})
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "cost_unreconciled")
        self.assertEqual(self.reserve().reason, "cost_unreconciled")
        attempt = TranslationRequestAttempt.objects.get(pk=first.attempt_pk)
        self.assertEqual((attempt.usage_validation, attempt.reconciliation_state), ("known", "unreconciled"))
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)

    def test_late_offline_receipt_idempotency_and_conflicting_report(self):
        first = self.reserve()
        without = core.record_usage(budget_pk=self.budget.pk, attempt_pk=first.attempt_pk,
                                    mode="offline_test", usage_report=self.usage())
        self.assertEqual(without.reason, "cost_unreconciled")
        self.reconcile(first)
        repeated = self.reconcile(first)
        self.assertEqual(repeated.reason, "usage_already_recorded")
        changed = dict(self.usage(), total_tokens=6, completion_tokens=3)
        conflict = core.record_usage(budget_pk=self.budget.pk, attempt_pk=first.attempt_pk,
                                     mode="offline_test", usage_report=changed)
        self.assertEqual(conflict.reason, "usage_conflict")
        self.assertEqual(TranslationRequestAttempt.objects.get(pk=first.attempt_pk).usage_report, self.usage())

    def test_invalid_missing_bool_negative_and_total_usage_stays_unknown(self):
        reports = ({}, {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
                   {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
                   {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 6})
        for index, report in enumerate(reports):
            with self.subTest(report=report):
                self.fresh_root("invalid-" + str(index))
                first = self.reserve()
                result = core.record_usage(budget_pk=self.budget.pk, attempt_pk=first.attempt_pk,
                                           mode="offline_test", usage_report=report)
                self.assertEqual(result.reason, "usage_unknown")
                self.assertFalse(self.reserve().allowed)
                self.budget.refresh_from_db()
                self.assertEqual(self.budget.requests_reserved, 1)
                attempt = TranslationRequestAttempt.objects.get(pk=first.attempt_pk)
                self.assertEqual(attempt.state, "unknown")
                self.assertEqual(attempt.usage_report, report)

    def test_unsafe_usage_json_and_receipts_cannot_execute_or_unblock(self):
        first = self.reserve()
        cyclic = {}; cyclic["cycle"] = cyclic
        hook = type("Hook", (), {"__str__": lambda obj: self.fail("serialization hook called")})()
        for report in ({"value": float("nan")}, cyclic, {"value": hook}, {"value": "x" * 65537}):
            with self.subTest(kind=type(report)):
                result = core.record_usage(budget_pk=self.budget.pk, attempt_pk=first.attempt_pk,
                                           mode="offline_test", usage_report=report)
                self.assertEqual(result.reason, "invalid_usage_report")
        attempt = TranslationRequestAttempt.objects.get(pk=first.attempt_pk)
        self.assertEqual((attempt.state, attempt.usage_report), ("reserved", {}))

    def test_version_drift_never_creates_new_budget_and_unknown_wins(self):
        changes = ({"source_sha256": "c" * 64}, {"policy_sha256": "d" * 64},
                   {"provider": "other"}, {"model": "other"})
        for change in changes:
            self.assertEqual(self.reserve(replace(self.identity, **change)).reason, "budget_version_changed")
        first = self.reserve()
        self.assertTrue(first.allowed)
        for change in changes:
            self.assertEqual(self.reserve(replace(self.identity, **change)).reason, "usage_unknown")
        self.assertEqual(TranslationRetryBudget.objects.count(), 1)
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.deadline_at), (1, self.values["deadline_at"]))

    def test_same_source_new_uuid_resolves_authority_without_rotating(self):
        changed = replace(self.identity, operation_uuid=uuid4())
        result = core.resolve_budget(changed, mode="offline_test", now=NOW, initial_contract=self.contract())
        self.assertEqual((result.budget_pk, result.operation_uuid), (self.budget.pk, self.budget.operation_uuid))
        self.assertEqual(result.reason, "operation_resolution_required")
        self.assertFalse(self.reserve(changed).allowed)
        self.assertEqual(TranslationRetryBudget.objects.count(), 1)

    def test_retired_history_and_old_uuid_never_allocate_new_operation(self):
        self.fresh_root("retired", state="closed", retired_at=NOW)
        before = TranslationRetryBudget.objects.count()
        self.assertEqual(self.reserve().reason, "budget_retired")
        missing_uuid = replace(self.identity, operation_uuid=None)
        result = core.resolve_budget(missing_uuid, mode="offline_test", now=NOW,
                                     initial_contract=self.contract())
        self.assertEqual((result.reason, result.budget_pk), ("operation_resolution_required", self.budget.pk))
        self.assertEqual(TranslationRetryBudget.objects.count(), before)

    def test_legacy_without_exact_synthetic_baseline_cannot_initialize_zero(self):
        identity = replace(self.identity, source_article_id="legacy-no-journal", operation_uuid=None)
        result = core.resolve_budget(identity, mode="offline_test", now=NOW,
                                     initial_contract=self.contract(baseline_receipt={"kind": "legacy_usage_unknown"}))
        self.assertEqual(result.reason, "legacy_usage_unknown")
        self.assertEqual(TranslationRetryBudget.objects.count(), 1)
        self.assertEqual(core.resolve_budget(identity, mode="offline_test", now=NOW).reason, "budget_missing")

    def test_first_root_allocates_uuid_once_and_freezes_initial_contract(self):
        identity = replace(self.identity, source_article_id="first-explicit", operation_uuid=None)
        first = core.resolve_budget(identity, mode="offline_test", now=NOW, initial_contract=self.contract())
        self.assertTrue(first.allowed)
        second = core.resolve_budget(identity, mode="offline_test", now=NOW,
                                     initial_contract=self.contract(request_limit=20, deadline_at=NOW + timedelta(days=1)))
        self.assertEqual((first.budget_pk, first.operation_uuid), (second.budget_pk, second.operation_uuid))
        root = TranslationRetryBudget.objects.get(pk=first.budget_pk)
        self.assertEqual((root.request_limit, root.deadline_at), (2, NOW + timedelta(minutes=30)))

    def test_exact_source_pair_and_invalid_input_cannot_guess_identity(self):
        for source_id in (self.identity.source_article_id.upper(), " " + self.identity.source_article_id):
            changed = replace(self.identity, source_article_id=source_id)
            self.assertEqual(self.reserve(changed).reason, "identity_changed")
        invalids = (replace(self.identity, article_pk_snapshot=True), replace(self.identity, source_sha256="short"),
                    replace(self.identity, operation_uuid="not-uuid"))
        for identity in invalids:
            self.assertEqual(self.reserve(identity).reason, "invalid_identity")
        self.assertEqual(self.reserve(provider_attempt_index=True).reason, "invalid_claim_identity")
        self.assertEqual(self.reserve(now=NOW.replace(tzinfo=None)).reason, "invalid_clock")
        self.assertEqual(self.reserve(claimed_at=NOW + timedelta(seconds=1)).reason, "invalid_claim_identity")

    def test_outer_atomic_never_returns_committable_reservation(self):
        with transaction.atomic():
            self.assertEqual(self.reserve().reason, "outer_transaction_forbidden")
            self.assertEqual(core.resolve_budget(self.identity, mode="offline_test", now=NOW).reason,
                             "outer_transaction_forbidden")
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, TranslationRequestAttempt.objects.count()), (0, 0))

    def test_attempt_insert_failure_rolls_back_counter(self):
        with patch.object(TranslationRequestAttempt, "save", side_effect=IntegrityError("synthetic insert failure")):
            with self.assertRaises(IntegrityError):
                self.reserve()
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.request_attempts.count()), (0, 0))

    def test_usage_persistence_failure_rolls_back_without_refund(self):
        first = self.reserve()
        with patch.object(core, "_write_locked", side_effect=IntegrityError("synthetic usage failure")):
            with self.assertRaises(IntegrityError):
                self.reconcile(first)
        self.budget.refresh_from_db()
        attempt = TranslationRequestAttempt.objects.get(pk=first.attempt_pk)
        self.assertEqual((self.budget.requests_reserved, attempt.state, attempt.usage_report), (1, "reserved", {}))
        self.assertEqual(self.reserve().reason, "usage_unknown")

    def test_usage_wrong_budget_or_snapshot_cannot_modify_attempt(self):
        first = self.reserve()
        other = self.fresh_root("wrong-budget")
        result = core.record_usage(budget_pk=other.pk, attempt_pk=first.attempt_pk,
                                   mode="offline_test", usage_report=self.usage())
        self.assertEqual(result.reason, "request_identity_changed")
        bad_attempt = self.attempt(operation_uuid=uuid4())
        result = core.record_usage(budget_pk=other.pk, attempt_pk=bad_attempt.pk,
                                   mode="offline_test", usage_report=self.usage())
        self.assertEqual(result.reason, "request_identity_changed")
        self.assertEqual(TranslationRequestAttempt.objects.get(pk=first.attempt_pk).state, "reserved")

    def test_late_report_after_article_delete_only_audits_original_attempt(self):
        first = self.reserve()
        old_pk = self.article.pk
        self.article.delete()
        new_article = article_for_retry(id=old_pk, source_article_id="reused-after-request")
        self.now = self.budget.deadline_at + timedelta(days=1)
        self.reconcile(first)
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.deadline_at), (1, self.values["deadline_at"]))
        new_article.refresh_from_db()
        self.assertEqual(new_article.translation_status, "failed")
        self.assertEqual(new_article.translation_runs.count(), 0)

    def test_identity_save_bulk_update_and_normal_counter_updates_are_forbidden(self):
        first = self.reserve()
        for obj, field, value in ((self.budget, "source_article_id_snapshot", "rotated"),
                                  (TranslationRequestAttempt.objects.get(pk=first.attempt_pk),
                                   "claim_execution_uuid", uuid4())):
            setattr(obj, field, value)
            with self.assertRaises(ValidationError):
                obj.save(update_fields=[field])
            with self.assertRaises(ValidationError):
                type(obj).objects.bulk_update([obj], [field])
            with self.assertRaises(ValidationError):
                type(obj).objects.filter(pk=obj.pk).update(**{field: value})
        with self.assertRaises(ValidationError):
            TranslationRetryBudget.objects.filter(pk=self.budget.pk).update(requests_reserved=0)


    def test_first_create_database_unique_conflict_is_handled_after_two_missing_reads(self):
        identity = replace(self.identity, source_article_id="forced-first-conflict", operation_uuid=None)
        gate = Barrier(2, timeout=10)
        original_lookup = core._locked_root
        original_create = TranslationRetryBudget.objects.create
        conflicts = []

        def lookup(value):
            result = original_lookup(value)
            if result[0] is None:
                gate.wait()
            return result

        def create(**values):
            try:
                return original_create(**values)
            except IntegrityError as error:
                conflicts.append(error.__cause__.diag.constraint_name)
                raise

        with patch.object(core, "_locked_root", side_effect=lookup), patch.object(
                TranslationRetryBudget.objects, "create", side_effect=create):
            results = self.parallel(lambda: core.resolve_budget(
                identity, mode="offline_test", now=NOW, initial_contract=self.contract()))
        self.assertEqual(conflicts, ["uq_tr_budget_active_source"])
        self.assertTrue(all(result.allowed for result in results))
        self.assertEqual(len({result.budget_pk for result in results}), 1)
        self.assertEqual(TranslationRetryBudget.objects.filter(
            source_article_id_snapshot="forced-first-conflict").count(), 1)
        print("B041_FIRST_ROOT_UNIQUE_CONFLICT", conflicts, flush=True)

    def test_update_or_create_cannot_rotate_identity_or_reopen_budget(self):
        with self.assertRaises(ValidationError):
            TranslationRetryBudget.objects.update_or_create(
                pk=self.budget.pk, defaults={"operation_uuid": uuid4(), "requests_reserved": 0})
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.operation_uuid, self.values["operation_uuid"])

    def test_exact_deadline_and_future_clock_are_not_renewed(self):
        self.now = self.budget.deadline_at
        self.assertEqual(self.reserve().reason, "budget_deadline_expired")
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.deadline_at), (0, self.values["deadline_at"]))

    def test_production_mode_usage_and_resolution_also_refuse_without_writes(self):
        first = self.reserve()
        self.assertEqual(core.resolve_budget(self.identity, mode="production", now=NOW).reason,
                         "supported_mode_missing")
        result = core.record_usage(budget_pk=self.budget.pk, attempt_pk=first.attempt_pk,
                                   mode="production", usage_report=self.usage(), receipt=self.receipt(first))
        self.assertEqual(result.reason, "supported_mode_missing")
        self.assertEqual(TranslationRequestAttempt.objects.get(pk=first.attempt_pk).state, "reserved")


class TranslationBudgetLockTests(BudgetCoreHelpersMixin, BudgetFixture):
    def held_budget_workers(self, actions, after_wait=None):
        self.assertEqual(connection.vendor, "postgresql")
        pids, results, errors = {}, {}, []
        ready = [Event() for _ in actions]
        threads = []
        evidence = []

        def worker(index, action):
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    pids[index] = cursor.fetchone()[0]
                ready[index].set()
                results[index] = action()
            except BaseException as error:
                errors.append(error)
            finally:
                ready[index].set()
                connections["default"].close()

        try:
            with transaction.atomic():
                TranslationRetryBudget.objects.select_for_update().get(pk=self.budget.pk)
                for index, action in enumerate(actions):
                    thread = Thread(target=worker, args=(index, action), daemon=True)
                    threads.append(thread); thread.start()
                for event in ready:
                    self.assertTrue(event.wait(5), "worker connection did not open")
                self.assertEqual(errors, [])
                self.assertEqual(len(set(pids.values())), len(actions))
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pid, wait_event_type, pg_blocking_pids(pid) "
                                       "FROM pg_stat_activity WHERE pid = ANY(%s)", [list(pids.values())])
                        rows = cursor.fetchall()
                    if len(rows) == len(actions) and all(wait == "Lock" and blockers for _, wait, blockers in rows):
                        evidence = rows
                        break
                    time.sleep(0.02)
                self.assertTrue(evidence, "no actual PG budget lock wait observed")
                print("B041_BUDGET_LOCK_WAIT", evidence, flush=True)
                if after_wait:
                    after_wait()
        finally:
            for thread in threads:
                thread.join(20)
            for index, thread in enumerate(threads):
                if thread.is_alive() and index in pids:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_cancel_backend(%s)", [pids[index]])
                    thread.join(5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), len(actions))
        return results

    def test_last_slot_two_actual_locked_consumers_have_one_winner(self):
        self.fresh_root("locked-last-slot", request_limit=1)
        results = self.held_budget_workers([self.reserve, self.reserve])
        self.assertEqual(sum(result.allowed for result in results.values()), 1)
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.request_attempts.count()), (1, 1))

    def test_reserve_lock_wait_crossing_deadline_refuses_without_slot(self):
        def advance():
            self.now = self.budget.deadline_at
        results = self.held_budget_workers([self.reserve], after_wait=advance)
        self.assertEqual(results[0].reason, "budget_deadline_expired")
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.request_attempts.count()), (0, 0))

    def test_late_usage_waits_budget_lock_and_preserves_deadline_and_count(self):
        first = self.reserve()
        def advance():
            self.now = self.budget.deadline_at + timedelta(seconds=1)
        results = self.held_budget_workers([lambda: self.reconcile(first)], after_wait=advance)
        self.assertTrue(results[0].allowed)
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.deadline_at), (1, self.values["deadline_at"]))
        self.assertEqual(self.reserve().reason, "budget_deadline_expired")


class TranslationBudgetDeleteCompatibilityTests(BudgetCoreHelpersMixin, BudgetFixture):
    def test_admin_single_and_bulk_delete_keep_audit_and_headline_invalidation(self):
        from django.contrib import admin
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from stable.models import HomepageHeadlineRecommendation, HomepageHeadlineSelection, NewsArticle, OperationLog

        user = get_user_model().objects.create_superuser(username="b041-delete", password="synthetic-only")
        request = RequestFactory().post("/admin/stable/newsarticle/")
        request.user = user
        article_admin = admin.site._registry[NewsArticle]
        self.assertTrue(article_admin.has_delete_permission(request, self.article))
        self.assertNotIn(TranslationRetryBudget, admin.site._registry)
        self.assertNotIn(TranslationRequestAttempt, admin.site._registry)
        for bulk in (False, True):
            with self.subTest(bulk=bulk):
                if bulk:
                    self.article = article_for_retry(source_article_id="boundary-admin-bulk")
                    self.fresh_root("admin-bulk", article_pk_snapshot=self.article.pk)
                first = self.reserve()
                self.assertTrue(first.allowed)
                selection, _ = HomepageHeadlineSelection.objects.get_or_create(slot="homepage_primary")
                selection.article = self.article
                selection.version = 10
                selection.save()
                recommendation = HomepageHeadlineRecommendation.objects.create(
                    article=self.article, engine_version="synthetic-only")
                run = TranslationRun.objects.create(article=self.article, provider_name="synthetic",
                                                    model_name="offline-only", status="started")
                old_pk, run_pk = self.article.pk, run.pk
                if bulk:
                    article_admin.delete_queryset(request, NewsArticle.objects.filter(pk=old_pk))
                else:
                    article_admin.delete_model(request, self.article)
                self.assertFalse(NewsArticle.objects.filter(pk=old_pk).exists())
                self.assertFalse(TranslationRun.objects.filter(pk=run_pk).exists())
                selection.refresh_from_db(); recommendation.refresh_from_db()
                self.assertEqual((selection.article_id, selection.version), (None, 11))
                self.assertEqual(recommendation.status, "invalidated")
                self.assertTrue(OperationLog.objects.filter(action_type="headline_invalidated").exists())
                self.budget.refresh_from_db()
                attempt = TranslationRequestAttempt.objects.get(pk=first.attempt_pk)
                self.assertEqual((self.budget.requests_reserved, self.budget.article_pk_snapshot,
                                  attempt.article_pk_snapshot, attempt.state), (1, old_pk, old_pk, "reserved"))
                self.assertEqual(self.budget.deadline_at, self.values["deadline_at"])


class TranslationBudgetMigrationBoundaryTests(TransactionTestCase):
    def test_empty_test_database_reverse_and_forward_keep_original_article(self):
        from django.db.migrations.executor import MigrationExecutor
        from django.db.migrations.recorder import MigrationRecorder
        from stable.models import NewsArticle

        self.assertEqual(connection.vendor, "postgresql")
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"), "只允许 Django 隔离 testDB")
        self.assertEqual(TranslationRetryBudget.objects.count(), 0, "逆迁移仅针对空账表")
        article = article_for_retry(source_article_id="migration-original-kept")
        tables = {TranslationRetryBudget._meta.db_table, TranslationRequestAttempt._meta.db_table}
        try:
            MigrationExecutor(connection).migrate([("stable", "0079_multisource_race_enrollment")])
            self.assertFalse(tables & set(connection.introspection.table_names()))
            self.assertNotIn(("stable", "0080_translation_retry_budget"),
                             MigrationRecorder(connection).applied_migrations())
            self.assertTrue(NewsArticle.objects.filter(pk=article.pk).exists())
        finally:
            MigrationExecutor(connection).migrate([("stable", "0080_translation_retry_budget")])
        self.assertTrue(tables <= set(connection.introspection.table_names()))
        self.assertTrue(NewsArticle.objects.filter(pk=article.pk).exists())
        self.assertEqual(TranslationRetryBudget.objects.count(), 0)
        self.assertIn(("stable", "0080_translation_retry_budget"),
                      MigrationRecorder(connection).applied_migrations())
        print("B041_EMPTY_LEDGER_MIGRATION_BOUNDARY", {
            "reverse": "0079", "forward_restored": "0080", "tables": sorted(tables),
            "original_article_kept": True, "empty_budget_tables_only": True}, flush=True)
