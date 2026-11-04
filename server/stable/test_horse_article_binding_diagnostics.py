"""C251 frozen selected-receipt diagnostic oracle; source-only, not executed.

The service deliberately does not exist in this card. Missing API is a
NOT_READY scenario ERROR, never business RED. Real PG controls below must be
executed only under a later explicit card. No old TestCase is inherited or
exported; fixture success, SQL results and core authorization are never mocked.
"""
import copy
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import DatabaseError, connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable import test_horse_article_binding_persistence as fixture_data
from stable.models import (
    ArticleHorseLink, HorseExternalIdentity, HorseProfile, NewsArticle,
    OperationLog, TaskExecutionLog, TermEntry,
)
from stable.services.horse_article_binding_persistence import commit_strong_horse_binding


MODULE = "stable.services.horse_article_binding_diagnostics"
FUNCTION = "diagnose_selected_horse_binding_receipt"
MAX_BYTES = 4_194_304
BOUNDARIES = {
    "historical_coverage": "selected_receipt_only",
    "request_uniqueness": "not_checked",
    "current_write_authority": "not_evaluated",
    "source_license": "not_evaluated",
    "automatic_action": "none",
}
RESULT_KEYS = {
    "schema_version", "receipt_id", "expected_request_key", "article_id", "profile_id",
    "selected_receipt_state", "current_pair_state", "current_manual_state",
    "original_link_id", "current_link_id", "receipt_detail_sha256", "after_sha256",
    "current_sha256", "changed_fields", "current_markers", "observed_at", *BOUNDARIES,
}
PARAMETERS = ("receipt_id", "expected_request_key", "expected_article_id", "expected_profile_id", "actor")
FORBIDDEN_CALLS = {
    "commit_strong_horse_binding", "_admit", "_classify", "scan_article_horse_links",
    "reconcile_article_horse_links", "eligible_profile_binding_handles",
    "backfill_profile_strong_bindings", "enqueue_profile_strong_backfill",
}


class DiagnosticScenarioError(RuntimeError):
    """NOT_READY, fixture, driver, thread and scheduling failures are ERROR."""


def require(value, message):
    if not value:
        raise DiagnosticScenarioError(message)


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(row):
    # Independent oracle, not the future diagnostic's snapshot helper.
    return json.loads(json.dumps({f.attname: getattr(row, f.attname)
                                 for f in row._meta.concrete_fields},
                                default=lambda value: value.isoformat()))


def rows(model):
    return copy.deepcopy(list(model.objects.order_by("pk").values()))


def emit(kind, **values):
    print("\nC251_SELECTED_RECEIPT " + json.dumps({"kind": kind, **values},
          ensure_ascii=False, default=str), flush=True)


class _Fixture:
    """Real independent synthetic producer; no consumer-side rebasing."""
    def __init__(self, owner):
        self.actor = get_user_model().objects.create_user(username="c251-producer", is_staff=True)
        self.reader = get_user_model().objects.create_user(username="c251-reader", is_staff=True)
        self.term = TermEntry.objects.create(term_type="horse", source_ja="Aurora",
                                             target_zh="极光", source_language="en")
        self.horse = HorseProfile.objects.create(primary_term=self.term, original_name="Aurora",
                                                 review_status="published")
        self.article = NewsArticle.objects.create(source_site="tdn", source_mode="latest",
            source_article_id="c251", source_url="https://example.invalid/c251",
            title_ja="", body_ja_raw="Aurora won.", source_language="en",
            published_at=timezone.now(), workflow_status="published", published_to_web_at=timezone.now())
        self.identity_bytes = raw(dict(source="the_racing_api", namespace="horse",
                                       external_id="hrs_251", horse_profile_id=self.horse.pk))
        self.identity = HorseExternalIdentity.objects.create(horse_profile=self.horse,
            source="the_racing_api", namespace="horse", external_id="hrs_251", status="verified",
            evidence_url="https://example.invalid/c251/identity", payload_sha256=sha(self.identity_bytes),
            verified_at=timezone.now(), verified_by=self.actor)
        self.pack = fixture_data.HorseArticleBindingPersistenceTests.make_bundle(self)
        self.pack["request_id"] = "c251-selected"
        self.temp = tempfile.TemporaryDirectory()
        owner.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reviewed-synthetic.json"
        self.path.write_bytes(raw(self.pack))
        self.path.chmod(0o600)
        self.scope = dict(bundle_path=str(self.path), bundle_sha256=sha(self.path.read_bytes()),
            producer_namespace="synthetic-server", request_id="c251-selected",
            article_id=self.article.pk, profile_id=self.horse.pk, identity_id=self.identity.pk,
            actor_ids=[self.actor.pk], not_before=(timezone.now()-timedelta(days=1)).isoformat(),
            expires_at=(timezone.now()+timedelta(days=1)).isoformat(), revoked=False,
            contract_refs=[copy.deepcopy(fixture_data.LITERAL["article_input"]["snapshot"]["evidence"][0]["contract_ref"])],
            responsibility=dict(identity_producer="isolated-fixture", relationship_owner="isolated-fixture",
                                write_owner="explicit-test-domain"))
        self.registry = {"c251-selected": self.scope}
        context = override_settings(HORSE_ARTICLE_BINDING_HANDLES=self.registry)
        context.enable()
        owner.addCleanup(context.disable)
        result = commit_strong_horse_binding("c251-selected", self.actor)
        require(result.get("status") == "created", "real writer fixture admission failed: " + repr(result))
        self.link = ArticleHorseLink.objects.get(article=self.article, horse_profile=self.horse)
        self.receipt = OperationLog.objects.get(pk=result["receipt_id"])
        self.key = self.link.metadata["request_key"]
        self.original = json.loads(self.receipt.detail)
        self.original_id = self.link.pk
        require(self.link.pk == result["link_id"] and self.link.source == "strong_identity.v1",
                "real strong row absent")
        require(raw(self.original).decode() == self.receipt.detail
                and self.original["after"] == snapshot(self.link)
                and self.original["after_sha256"] == sha(raw(snapshot(self.link)))
                and self.receipt.target_id == self.key,
                "fixture canonical receipt does not bind actual row")
        require(OperationLog.objects.filter(action_type="horse_binding_committed",
            target_type="horse_binding_request").count() == 1, "fixture receipt not unique")
        emit("real_created", result=result, row=snapshot(self.link), receipt_id=self.receipt.pk,
             receipt_detail=self.receipt.detail, producer_SHA=sha(self.path.read_bytes()))

    def selectors(self):
        return dict(receipt_id=self.receipt.pk, expected_request_key=self.key,
                    expected_article_id=self.article.pk, expected_profile_id=self.horse.pk, actor=self.reader)


class SelectedHorseBindingReceiptDiagnosticTests(TransactionTestCase):
    """Independent top-level PG transactions; never Django TestCase wrapping."""
    def setUp(self):
        require(connection.vendor == "postgresql" and connection.get_autocommit()
                and not connection.in_atomic_block, "requires independent isolated PostgreSQL autocommit")
        try:
            self.api = importlib.import_module(MODULE)
        except ModuleNotFoundError as error:
            if error.name == MODULE:
                raise DiagnosticScenarioError("NOT_READY: diagnostic service is absent") from error
            raise
        required = {FUNCTION: None, "DiagnosticInputError": ValueError,
                    "DiagnosticAccessError": PermissionError, "DiagnosticTransactionError": RuntimeError}
        for name, parent in required.items():
            value = getattr(self.api, name, None)
            require(callable(value), "NOT_READY: missing API " + name)
            if parent is not None:
                require(inspect.isclass(value) and issubclass(value, parent), "NOT_READY: error contract " + name)
        self.diagnose = getattr(self.api, FUNCTION)
        signature = inspect.signature(self.diagnose)
        require(tuple(signature.parameters) == PARAMETERS and all(
            p.default is inspect.Parameter.empty and p.kind in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            for p in signature.parameters.values()), "NOT_READY: five required named selectors/actor signature")
        self.d = _Fixture(self)

    def _state(self):
        return {"tables": {model._meta.label: rows(model) for model in (
                    ArticleHorseLink, OperationLog, TaskExecutionLog, NewsArticle,
                    HorseProfile, HorseExternalIdentity, TermEntry, get_user_model())},
                "registry": copy.deepcopy(settings.HORSE_ARTICLE_BINDING_HANDLES),
                "producer_bytes": self.d.path.read_bytes()}

    def _session(self):
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation = cursor.fetchone()[0]
            cursor.execute("SHOW transaction_read_only")
            readonly = cursor.fetchone()[0]
            cursor.execute("SHOW statement_timeout")
            timeout = cursor.fetchone()[0]
            cursor.execute("SHOW lock_timeout")
            lock_timeout = cursor.fetchone()[0]
        return isolation, readonly, timeout, lock_timeout, connection.get_autocommit(), connection.in_atomic_block

    @contextmanager
    def _observe(self, control=None):
        notes, calls = [], []
        old_profiler = sys.getprofile()
        def profile(frame, event, arg):
            if event == "call" and frame.f_code.co_name in FORBIDDEN_CALLS:
                if "/stable/services/" in frame.f_code.co_filename:
                    calls.append(frame.f_code.co_name)
        def observe(execute, sql, params, many, context):
            upper = sql.lstrip().upper()
            item = {"sql": sql, "params": copy.deepcopy(params), "many": many}
            notes.append(item)
            self.assertNotRegex(upper, r"^(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b")
            self.assertNotIn("FOR UPDATE", upper)
            self.assertNotIn("PG_ADVISORY", upper)
            if upper.startswith("SELECT") and ("stable_" in sql or "auth_user" in sql):
                # Direct raw cursor observes actual server settings, not a synthesized ORM result.
                with context["connection"].connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    item["isolation"] = cursor.fetchone()[0]
                    cursor.execute("SHOW transaction_read_only")
                    item["readonly"] = cursor.fetchone()[0]
                    cursor.execute("SELECT pg_backend_pid()")
                    item["pid"] = cursor.fetchone()[0]
                self.assertEqual(item["isolation"], "repeatable read")
                self.assertEqual(item["readonly"], "on")
                if "stable_operationlog" in sql:
                    self.assertRegex(sql, r'"id"\s*=\s*%s')
                    self.assertIn(self._active_selectors["receipt_id"], params or ())
                    self.assertNotRegex(upper, r"COUNT\s*\(")
                if "stable_articlehorselink" in sql:
                    self.assertRegex(sql, r'"article_id"\s*=\s*%s')
                    self.assertRegex(sql, r'"horse_profile_id"\s*=\s*%s')
                    self.assertIn(self._active_selectors["expected_article_id"], params or ())
                    self.assertIn(self._active_selectors["expected_profile_id"], params or ())
            if control is not None:
                control("before", item, context)
            value = execute(sql, params, many, context)
            cursor = context.get("cursor")
            if cursor is not None and cursor.description:
                item["columns"] = [column[0] for column in cursor.description]
            if control is not None:
                control("after", item, context)
            return value
        sys.setprofile(profile)
        try:
            with connection.execute_wrapper(observe):
                yield notes
        finally:
            sys.setprofile(old_profiler)
            emit("SQL_observations", notes=notes, forbidden_core_calls=calls)
            self.assertEqual(calls, [], "diagnostic called a writable admission/scanner path")

    def _call(self, *, selectors=None, control=None):
        args = self.d.selectors() if selectors is None else selectors
        self._active_selectors = args
        before, session = self._state(), self._session()
        try:
            with self._observe(control) as notes:
                result = self.diagnose(**args)
        finally:
            after = self._state()
            self.assertEqual(after, before, "diagnostic changed DB rows, original receipt, producer or settings")
            self.assertEqual(self._session(), session, "connection settings/transaction state leaked")
            emit("zero_write_postcondition", before=before["tables"]["stable.ArticleHorseLink"],
                 after=after["tables"]["stable.ArticleHorseLink"],
                 receipt_rows_unchanged=True, producer_SHA=sha(after["producer_bytes"]))
        self.assertIs(type(result), dict)
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["schema_version"], "l02.selected-horse-binding-diagnostic.v1")
        for key, value in BOUNDARIES.items():
            self.assertEqual(result[key], value)
        for output, argument in (("receipt_id", "receipt_id"), ("expected_request_key", "expected_request_key"),
                                 ("article_id", "expected_article_id"), ("profile_id", "expected_profile_id")):
            self.assertEqual(result[output], args[argument])
        self.assertIs(type(result["observed_at"]), str)
        try:
            observed = datetime.fromisoformat(result["observed_at"])
        except ValueError:
            self.fail("diagnostic observed_at is not an ISO timestamp")
        self.assertIsNotNone(observed.utcoffset())
        self.assertEqual(result["changed_fields"], sorted(set(result["changed_fields"])))
        emit("diagnostic_result", result=result)
        return result, notes

    def _comparable(self, result, pair_state):
        current = ArticleHorseLink.objects.filter(article=self.d.article, horse_profile=self.d.horse).first()
        self.assertEqual(result["selected_receipt_state"], "stored_consistent")
        self.assertEqual(result["current_pair_state"], pair_state)
        self.assertEqual(result["original_link_id"], self.d.original_id)
        self.d.receipt.refresh_from_db()
        self.assertEqual(result["receipt_detail_sha256"], sha(self.d.receipt.detail.encode()))
        self.assertEqual(result["after_sha256"], sha(raw(self.d.original["after"])))
        self.assertEqual(result["current_link_id"], current.pk if current else None)
        if current is None:
            self.assertEqual(result["current_manual_state"], "no_current_row")
            self.assertIsNone(result["current_sha256"])
            self.assertIsNone(result["current_markers"])
            self.assertEqual(result["changed_fields"], [])
            return
        actual = snapshot(current)
        self.assertEqual(result["current_sha256"], sha(raw(actual)))
        self.assertEqual(result["changed_fields"], sorted(
            key for key in actual if actual[key] != self.d.original["after"][key]))
        self.assertEqual(result["current_manual_state"], current.status if current.status in {"manual", "removed"} else "none")

    def _not_comparable(self, result, selected_state):
        self.assertEqual(result["selected_receipt_state"], selected_state)
        self.assertEqual(result["current_pair_state"], "not_comparable")
        self.assertEqual(result["current_manual_state"], "not_evaluated")
        for key in ("original_link_id", "current_link_id", "after_sha256", "current_sha256", "current_markers"):
            self.assertIsNone(result[key])
        self.assertEqual(result["changed_fields"], [])

    def test_selected_original_full_row_equal_and_repeat_never_claims_replay(self):
        """Catches after/current comparison bypass and replay/permission conflation."""
        for unused in range(2):
            result, notes = self._call()
            self._comparable(result, "same_pk_equal")
            self.assertEqual(result["current_markers"], {
                "source_namespace": True, "schema_namespace": True, "reserved_keys": True})
            self.assertTrue(any("stable_operationlog" in item["sql"] for item in notes))

    def test_all_markers_erased_same_PK_is_drift_not_ordinary_history_absence(self):
        """Catches dependence on current marker for selected history comparison."""
        ArticleHorseLink.objects.filter(pk=self.d.original_id).update(source="auto_match", metadata={})
        result, unused = self._call()
        self._comparable(result, "same_pk_drifted")
        self.assertEqual(result["changed_fields"], ["metadata", "source"])
        self.assertEqual(result["current_markers"], {
            "source_namespace": False, "schema_namespace": False, "reserved_keys": False})

    def test_missing_current_pair_is_observed_without_weak_recreation(self):
        """Catches repair/get_or_create on selected historical absence."""
        self.d.link.delete()
        result, unused = self._call()
        self._comparable(result, "absent")

    def test_ordinary_replacement_reports_current_and_original_PK_separately(self):
        """Catches same-pair replacement incorrectly accepted as original row."""
        self.d.link.delete()
        replacement = ArticleHorseLink.objects.create(article=self.d.article, horse_profile=self.d.horse,
            status="auto", source="auto_match", confidence=95, metadata={"ordinary": True})
        require(replacement.pk != self.d.original_id, "replacement fixture reused original PK")
        result, unused = self._call()
        self._comparable(result, "replacement_pk")

    def test_manual_and_removed_replacements_keep_current_staff_state(self):
        """Catches historical receipt replacing current protected PK/state."""
        self.d.link.delete()
        for status in ("manual", "removed"):
            with self.subTest(status=status):
                row = ArticleHorseLink.objects.create(article=self.d.article, horse_profile=self.d.horse,
                    status=status, source="manual", metadata={"staff": status},
                    confirmed_by=self.d.actor, confirmed_at=timezone.now(),
                    removed_by=self.d.reader, removed_at=timezone.now())
                result, unused = self._call()
                self._comparable(result, "replacement_pk")
                self.assertEqual(result["current_manual_state"], status)
                row.delete()

    def test_real_staff_confirm_remove_reset_remain_observations_not_release(self):
        """Catches diagnostic mutating staff decisions or reviving reset candidate."""
        client = Client()
        client.force_login(self.d.reader)
        for action, status in (("confirm", "manual"), ("remove", "removed"), ("reset", "candidate")):
            with self.subTest(action=action):
                response = client.post(reverse("console-horse-profile-article-link-status",
                    args=[self.d.original_id]), {"action": action})
                require(response.status_code == 302, "real staff POST failed")
                self.d.link.refresh_from_db()
                require(self.d.link.status == status, "staff POST did not persist expected state")
                result, unused = self._call()
                self._comparable(result, "same_pk_drifted")
                if action == "reset":
                    self.assertEqual(result["current_manual_state"], "none")
                    self.assertTrue(result["current_markers"]["source_namespace"])

    def test_K_pair_and_receipt_namespace_mismatches_do_not_choose_another_record(self):
        """Catches selector mismatch being followed, repaired or called no-history."""
        for field, value in (("expected_request_key", "0"*64),
                             ("expected_article_id", self.d.article.pk+10000),
                             ("expected_profile_id", self.d.horse.pk+10000)):
            with self.subTest(selector=field):
                args = self.d.selectors(); args[field] = value
                result, notes = self._call(selectors=args)
                self._not_comparable(result, "selector_mismatch")
                self.assertFalse(any("stable_articlehorselink" in item["sql"] for item in notes))
        for field in ("action_type", "target_type", "target_id"):
            with self.subTest(log_field=field):
                before = getattr(self.d.receipt, field)
                OperationLog.objects.filter(pk=self.d.receipt.pk).update(**{field: "wrong"})
                result, unused = self._call()
                self._not_comparable(result, "selector_mismatch")
                OperationLog.objects.filter(pk=self.d.receipt.pk).update(**{field: before})

    def test_bad_canonical_schema_after_hash_and_field_bindings_are_not_repaired(self):
        """Catches malformed original accepted as a source/authority assertion."""
        good = raw(self.d.original).decode()
        cases = ["{bad", good+"\n", '{"a":1,"a":2}', '{"value":NaN}']
        mutations = [dict(schema_version="unknown"), dict(after_sha256="0"*64), dict(link_id=True),
                     dict(payload_sha256="bad"), dict(identity_id=False), dict(before="present"),
                     dict(actor_id=self.d.reader.pk), dict(extra="unsupported")]
        for values in mutations:
            value = copy.deepcopy(self.d.original); value.update(values)
            cases.append(raw(value).decode())
        for label in ("after_missing_column", "metadata_binding"):
            value = copy.deepcopy(self.d.original)
            if label == "after_missing_column":
                value["after"].pop("updated_at")
            else:
                value["after"]["metadata"]["request_key"] = "0"*64
            value["after_sha256"] = sha(raw(value["after"]))
            cases.append(raw(value).decode())
        for index, detail in enumerate(cases):
            with self.subTest(case=index):
                OperationLog.objects.filter(pk=self.d.receipt.pk).update(detail=detail)
                result, notes = self._call()
                self._not_comparable(result, "invalid_or_unsupported")
                self.assertEqual(result["receipt_detail_sha256"], sha(detail.encode()))
                self.assertFalse(any("stable_articlehorselink" in item["sql"] for item in notes))
        OperationLog.objects.filter(pk=self.d.receipt.pk).update(detail=good)

    def test_real_admin_deletion_SET_NULL_does_not_rewrite_original_actor(self):
        """Catches receipt admin NULL silently trusted or historic actor repaired."""
        # Identity.verified_by is PROTECT, not SET_NULL. Keep a real verified
        # reviewer on that independent current record before deleting the old
        # log admin; do not turn a fixture ProtectedError into business RED.
        changed = HorseExternalIdentity.objects.filter(pk=self.d.identity.pk).update(verified_by=self.d.reader)
        require(changed == 1, "identity reviewer reassignment precondition failed")
        self.d.actor.delete()
        self.d.receipt.refresh_from_db()
        require(self.d.receipt.admin_id is None, "real SET_NULL precondition absent")
        result, unused = self._call()
        self._not_comparable(result, "invalid_or_unsupported")

    def test_oversize_selected_detail_is_not_fetched_truncated_or_parsed(self):
        """Catches full raw TEXT fetch before selected-record octet-length guard."""
        OperationLog.objects.filter(pk=self.d.receipt.pk).update(detail="x"*(MAX_BYTES+1))
        result, notes = self._call()
        self._not_comparable(result, "invalid_or_unsupported")
        self.assertIsNone(result["receipt_detail_sha256"])
        selected = [item for item in notes if "stable_operationlog" in item["sql"]]
        self.assertTrue(any("OCTET_LENGTH" in item["sql"].upper() for item in selected))
        self.assertFalse(any("detail" in item.get("columns", ()) for item in selected))

    def test_anonymous_forged_inactive_and_stale_nonstaff_reader_is_rejected(self):
        """Catches actor ID or stale in-memory staff fields substituting real reader."""
        actors = [None, AnonymousUser(), SimpleNamespace(pk=self.d.reader.pk, is_authenticated=True,
                                                        is_staff=True, is_active=True)]
        for actor in actors:
            with self.subTest(actor=type(actor).__name__):
                args = self.d.selectors(); args["actor"] = actor
                with self.assertRaises(self.api.DiagnosticAccessError):
                    self._call(selectors=args)
        for field in ("is_active", "is_staff"):
            with self.subTest(stale=field):
                get_user_model().objects.filter(pk=self.d.reader.pk).update(**{field: False})
                # The original authenticated User instance still says True.
                with self.assertRaises(self.api.DiagnosticAccessError):
                    self._call()
                get_user_model().objects.filter(pk=self.d.reader.pk).update(**{field: True})

    def test_strict_selector_input_errors_do_not_become_missing_history(self):
        """Catches bool/string/empty selector coercion and negative ID lookup."""
        invalid = [(name, value) for name in ("receipt_id", "expected_article_id", "expected_profile_id")
                   for value in (True, 0, -1, "1", None)]
        invalid += [("expected_request_key", value) for value in (None, "", "A"*64, "0"*63, 1)]
        for key, value in invalid:
            with self.subTest(selector=key, value=value):
                args = self.d.selectors(); args[key] = value
                with self.assertRaises(self.api.DiagnosticInputError):
                    self._call(selectors=args)

    def test_deleted_selected_PK_means_only_selected_missing_not_pair_history_absence(self):
        """Catches missing PK causing pair-wide search or strong-history conclusion."""
        selected_id = self.d.receipt.pk
        self.d.receipt.delete()
        # Django clears the deleted instance PK, so preserve the explicit selected ID.
        args = self.d.selectors(); args["receipt_id"] = selected_id
        result, notes = self._call(selectors=args)
        self._not_comparable(result, "selected_missing")
        self.assertIsNone(result["receipt_detail_sha256"])
        self.assertFalse(any("stable_articlehorselink" in item["sql"] for item in notes))

    def test_other_same_K_and_different_K_receipts_never_imply_uniqueness(self):
        """Catches hidden history enumeration or duplicate-count authority claim."""
        for key in (self.d.key, "1"*64):
            OperationLog.objects.create(admin=self.d.reader, action_type="horse_binding_committed",
                target_type="horse_binding_request", target_id=key, detail=self.d.receipt.detail)
        result, unused = self._call()
        self._comparable(result, "same_pk_equal")
        self.assertEqual(result["request_uniqueness"], "not_checked")

    def test_missing_registry_and_expired_scope_do_not_grant_or_block_historical_read(self):
        """Catches current write permission conflated with selected stored comparison."""
        self.d.scope["expires_at"] = (timezone.now()-timedelta(seconds=1)).isoformat()
        blocked = commit_strong_horse_binding("c251-selected", self.d.actor)
        require(blocked.get("status") == "blocked_current_authority", "expired writer control did not reject")
        for registry in (self.d.registry, {}):
            with self.subTest(empty=not registry), override_settings(HORSE_ARTICLE_BINDING_HANDLES=registry):
                result, unused = self._call()
                self._comparable(result, "same_pk_equal")

    def test_nested_caller_transaction_is_rejected_without_snapshot_reads(self):
        """Catches nested atomic silently used instead of an independent RR snapshot."""
        self._active_selectors = self.d.selectors()
        before = self._state()
        with transaction.atomic():
            with self._observe() as notes:
                with self.assertRaises(self.api.DiagnosticTransactionError):
                    self.diagnose(**self._active_selectors)
            self.assertFalse(any(item["sql"].lstrip().upper().startswith("SELECT") for item in notes))
        connection.set_autocommit(False)
        try:
            with self._observe() as notes:
                with self.assertRaises(self.api.DiagnosticTransactionError):
                    self.diagnose(**self._active_selectors)
            self.assertFalse(any(item["sql"].lstrip().upper().startswith("SELECT") for item in notes))
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.assertEqual(self._state(), before)

    def test_actual_readonly_transaction_rejects_DML_and_restores_session(self):
        """Catches a nominal read-only diagnostic whose real transaction permits DML."""
        attempts = []
        def probe(phase, item, context):
            if phase != "before" or "stable_operationlog" not in item["sql"] or attempts:
                return
            with context["connection"].connection.cursor() as cursor:
                cursor.execute("SAVEPOINT c251_readonly_probe")
                code, accepted = None, False
                try:
                    with context["connection"].wrap_database_errors:
                        cursor.execute('UPDATE "stable_articlehorselink" SET confidence=1 WHERE id=%s',
                                       (self.d.original_id,))
                    accepted = True
                except DatabaseError as error:
                    cause = error.__cause__
                    code = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
                finally:
                    cursor.execute("ROLLBACK TO SAVEPOINT c251_readonly_probe")
                    cursor.execute("RELEASE SAVEPOINT c251_readonly_probe")
                attempts.append({"accepted": accepted, "SQLSTATE": code})
        result, unused = self._call(control=probe)
        self._comparable(result, "same_pk_equal")
        self.assertEqual(attempts, [{"accepted": False, "SQLSTATE": "25006"}])
        emit("actual_readonly_DML_control", attempts=attempts)

    def _database_failure(self, statement, expected_code):
        reached = []
        def fault(phase, item, context):
            if phase == "before" and "stable_operationlog" in item["sql"] and not reached:
                reached.append(True)
                with context["connection"].connection.cursor() as cursor:
                    with context["connection"].wrap_database_errors:
                        if "pg_sleep" in statement:
                            cursor.execute("SET LOCAL statement_timeout='30ms'")
                        cursor.execute(statement)
                raise DiagnosticScenarioError("real SQL fault control did not raise")
        with self.assertRaises(DatabaseError) as caught:
            self._call(control=fault)
        self.assertEqual(reached, [True])
        cause = caught.exception.__cause__
        code = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
        self.assertEqual(code, expected_code)
        emit("actual_DB_error_propagated", SQLSTATE=code)

    def test_real_driver_error_propagates_instead_of_invalid_or_missing(self):
        """Catches SQL/driver exceptions swallowed as successful diagnostic state."""
        self._database_failure("SELECT 1/0", "22012")

    def test_real_statement_timeout_propagates_and_local_timeout_does_not_leak(self):
        """Catches timeout swallowed or session statement_timeout left changed."""
        self._database_failure("SELECT pg_sleep(0.2)", "57014")

    def test_two_real_PG_sessions_preserve_snapshot_then_new_call_observes_commit(self):
        """Catches READ COMMITTED/multiple-snapshot current-row drift during receipt read."""
        ready, done = threading.Event(), threading.Event()
        observations, errors = [], []
        worker_raw = []
        expected_before, session_before = self._state(), self._session()
        old_hash = sha(raw(snapshot(self.d.link)))
        def worker():
            db = connections["default"]
            try:
                require(ready.wait(5), "snapshot observer did not release worker")
                db.ensure_connection(); worker_raw.append(db.connection)
                with transaction.atomic(using="default"):
                    with db.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout='3s'")
                        cursor.execute("SET LOCAL lock_timeout='2s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        pid = cursor.fetchone()[0]
                    changed = ArticleHorseLink.objects.using("default").filter(pk=self.d.original_id).update(source="c251-later")
                    require(changed == 1, "worker did not update exactly one current row")
                observations.append({"pid": pid, "natural_commit": True})
            except Exception:
                errors.append(traceback.format_exc())
            finally:
                db.close(); done.set()
        thread = threading.Thread(target=worker, name="c251-snapshot-writer", daemon=False)
        thread.start()
        released = []
        def schedule(phase, item, context):
            if phase == "after" and "stable_operationlog" in item["sql"] and not released:
                released.append(item["pid"])
                ready.set()
                require(done.wait(5), "worker failed to finish within snapshot barrier budget")
                require(not errors, "worker driver/SQL failure: " + repr(errors))
        self._active_selectors = self.d.selectors()
        started = time.monotonic()
        try:
            with self._observe(schedule):
                first = self.diagnose(**self._active_selectors)
        finally:
            ready.set()
            thread.join(5)
            if thread.is_alive() and worker_raw:
                worker_raw[0].cancel()
                thread.join(3)
            require(not thread.is_alive(), "worker did not naturally finish/cancel within cleanup budget")
        require(not errors and done.is_set() and len(observations) == 1, "worker completion precondition failed")
        require(released and released[0] != observations[0]["pid"], "two distinct real PG sessions not observed")
        self.assertLess(time.monotonic()-started, 20)
        self.assertEqual(first["current_pair_state"], "same_pk_equal")
        self.assertEqual(first["current_sha256"], old_hash)
        for key, value in BOUNDARIES.items():
            self.assertEqual(first[key], value)
        expected_after = copy.deepcopy(expected_before)
        table = expected_after["tables"]["stable.ArticleHorseLink"]
        require(len(table) == 1, "snapshot fixture has extra links")
        table[0]["source"] = "c251-later"
        self.assertEqual(self._state(), expected_after, "only the independent committed writer may change its source field")
        self.assertEqual(self._session(), session_before)
        second, unused = self._call()
        self._comparable(second, "same_pk_drifted")
        self.assertEqual(second["changed_fields"], ["source"])
        emit("two_PG_snapshot_control", workers=observations, observer_pid=released[0],
             first=first, second=second, worker_errors=errors, cleanup_complete=True,
             scheduling_not_database_lock_wait=True)
