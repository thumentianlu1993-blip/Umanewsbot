"""C245 static test source: current marked strong rows, not all historical pairs.

Only a later authorized isolated-PG run can establish RED/GREEN. No future
classifier is imported. Fault controls alter isolated rows after real admission;
resolver/receipt/ORM/writer success is never mocked. Loops are not extra methods.
"""
import copy
import hashlib
import io
import json
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.db.models.query import QuerySet
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable import test_horse_article_binding_persistence as fixture_data
from stable import views
from stable.models import ArticleHorseLink, HorseExternalIdentity, HorseProfile, NewsArticle, OperationLog, TermEntry
from stable.services import horse_profiles
from stable.services.horse_article_binding_persistence import commit_strong_horse_binding
from stable.services.terms import resolve_article_entities
from stable.tasks import scan_article_horse_links_task


TOTAL_SECONDS = 40
BARRIER_SECONDS = 5
STATEMENT_SECONDS = 20
LOCK_SECONDS = 10
PROFILE_KEYS = {"created", "updated", "candidate", "skipped_removed", "skipped_manual"}


class StrongProtectionScenarioError(RuntimeError):
    """Fixture/API/driver/thread/deadline errors are ERROR, never business RED."""


def require(condition, message):
    if not condition:
        raise StrongProtectionScenarioError(message)


def emit(kind, **values):
    print("\nC245_STRONG_PROTECTION " + json.dumps({"kind": kind, **values},
          ensure_ascii=False, default=str), flush=True)


def concrete_rows(queryset):
    return copy.deepcopy(list(queryset.order_by("pk").values()))


class _Domain:
    """Independent producer fixture; deliberately not a TestCase subclass."""
    def __init__(self, owner, token):
        self.owner = owner
        self.token = token
        self.actor = get_user_model().objects.create_user(username=token, is_staff=True)
        self.other = get_user_model().objects.create_user(username=token+"-other", is_staff=True)
        self.term = TermEntry.objects.create(term_type="horse", source_ja="Aurora", target_zh="极光",
                                             source_language="en")
        self.horse = HorseProfile.objects.create(primary_term=self.term, original_name="Aurora",
                                                 review_status="published")
        self.article = NewsArticle.objects.create(source_site="tdn", source_mode="latest",
            source_article_id=token, source_url="https://example.invalid/"+token,
            title_ja="", body_ja_raw="Aurora won.", source_language="en", published_at=timezone.now(),
            workflow_status="published", published_to_web_at=timezone.now())
        self.identity_bytes = fixture_data.raw(dict(source="the_racing_api", namespace="horse",
            external_id=token, horse_profile_id=self.horse.pk))
        self.identity = HorseExternalIdentity.objects.create(horse_profile=self.horse, source="the_racing_api",
            namespace="horse", external_id=token, status="verified", evidence_url="https://example.invalid/identity",
            payload_sha256=hashlib.sha256(self.identity_bytes).hexdigest(), verified_at=timezone.now(),
            verified_by=self.actor)
        # Reuse only the accepted data builder through its module. No old test
        # class is inherited/exported, and no consumer repairs these bytes.
        self.pack = fixture_data.HorseArticleBindingPersistenceTests.make_bundle(self)
        self.pack["request_id"] = token
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"server-synthetic.json"
        self.path.write_bytes(fixture_data.raw(self.pack))
        self.path.chmod(0o600)
        self.original_bytes = self.path.read_bytes()
        self.scope = dict(bundle_path=str(self.path), bundle_sha256=hashlib.sha256(self.original_bytes).hexdigest(),
            producer_namespace="synthetic-server", request_id=token, article_id=self.article.pk,
            profile_id=self.horse.pk, identity_id=self.identity.pk, actor_ids=[self.actor.pk],
            not_before=(timezone.now()-timedelta(days=1)).isoformat(),
            expires_at=(timezone.now()+timedelta(days=1)).isoformat(), revoked=False,
            contract_refs=[copy.deepcopy(fixture_data.LITERAL["article_input"]["snapshot"]["evidence"][0]["contract_ref"])],
            responsibility=dict(identity_producer="isolated-fixture", relationship_owner="isolated-fixture",
                                write_owner="explicit-test-domain"))
        self.handle = token
        owner.registry[self.handle] = self.scope
        self.client = Client()
        self.client.force_login(self.actor)
        self.original_link_id = None
        self.key = None

    def created(self):
        result = commit_strong_horse_binding(self.handle, self.actor)
        require(result.get("status") == "created", "real strong fixture admission failed: "+repr(result))
        row = ArticleHorseLink.objects.get(article=self.article, horse_profile=self.horse)
        require(row.pk == result["link_id"] and row.status == "auto" and row.source == "strong_identity.v1",
                "writer did not create the real strong row")
        self.original_link_id = row.pk
        self.key = row.metadata["request_key"]
        logs = self.receipts()
        require(len(logs) == 1 and logs[0]["id"] == result["receipt_id"] and logs[0]["target_id"] == self.key,
                "real unique fixture receipt absent")
        receipt = json.loads(logs[0]["detail"])
        require(receipt["link_id"] == row.pk and receipt["after"] == fixture_data.snapshot(row),
                "fixture receipt does not bind actual concrete row")
        emit("real_created", token=self.token, result=result, row=self.rows(), receipts=logs,
             producer_bytes_SHA=hashlib.sha256(self.original_bytes).hexdigest())
        return row

    def rows(self):
        return concrete_rows(ArticleHorseLink.objects.filter(article=self.article, horse_profile=self.horse))

    def receipts(self):
        query = OperationLog.objects.filter(action_type="horse_binding_committed", target_type="horse_binding_request")
        return concrete_rows(query) if self.key else []

    def state(self):
        return {"rows": self.rows(), "receipts": self.receipts(),
                "bundle_bytes": self.path.read_bytes()}

    def readers(self):
        forward = views._public_published_articles().get(pk=self.article.pk).public_horse_links
        reverse_rows = views._public_horse_article_entries(self.horse)
        return {"article_to_horse": self.horse.pk in {x.horse_profile_id for x in forward},
                "horse_to_article": self.article.pk in {x["article"].pk for x in reverse_rows}}

    def staff(self, action):
        rows = self.rows()
        require(len(rows) == 1, "staff fixture current pair missing")
        response = self.client.post(reverse("console-horse-profile-article-link-status", args=[rows[0]["id"]]),
                                    {"action": action})
        require(response.status_code == 302, "real staff action did not redirect")
        row = self.rows()[0]
        expected = {"confirm": "manual", "remove": "removed", "reset": "candidate"}[action]
        require(row["status"] == expected, "real staff action did not persist")
        if action == "confirm":
            require(row["confirmed_by_id"] == self.actor.pk and row["confirmed_at"] is not None,
                    "manual actor/time absent")
        if action == "remove":
            require(row["removed_by_id"] == self.actor.pk and row["removed_at"] is not None,
                    "remove actor/time absent")
        emit("staff_committed", action=action, row=row)

    def weak_precondition(self, path, *, delete=False, auto95=False):
        self.article.refresh_from_db()
        if path == "profile":
            match = horse_profiles._match_article(self.article, self.horse, horse_profiles._profile_match_terms(self.horse))
            require(match is not None and match.status == ("auto" if auto95 else "candidate"),
                    "real profile weak-match action precondition not reached")
            if auto95:
                require(match.confidence == 95, "ordinary title control must really be AUTO95")
            emit("real_weak_precondition", path=path, match_status=match.status, confidence=match.confidence)
        else:
            resolution = resolve_article_entities(self.article.title_ja,
                self.article.body_ja_normalized or self.article.body_ja_raw, source_language="en")
            targets = [x for x in resolution.entities if x.entity_type in {"horse", "unknown_horse"}
                       and (x.term_id == self.term.pk or x.canonical_text == "Aurora")]
            require(not targets if delete else bool(targets), "real resolver desired/delete precondition absent")
            if not delete:
                field = "title" if auto95 else "body"
                require(any(x.field_name == field and x.matched_text == "Aurora" for x in targets),
                        "real resolver expected occurrence absent: "+field)
            emit("real_weak_precondition", path=path, delete=delete, resolution=resolution.as_dict())

    def invoke(self, path):
        if path == "profile":
            result = scan_article_horse_links_task.run(profile_id=self.horse.pk, commit=True)
            require(set(result) == PROFILE_KEYS, "profile result shape changed")
            return result
        if path == "article":
            return scan_article_horse_links_task.run(article_id=self.article.pk, commit=True)
        out = io.StringIO()
        call_command("reprocess_article_entities", "--article-id", str(self.article.pk), "--commit", "--json", stdout=out)
        result = json.loads(out.getvalue())["articles"][0]
        require(result["status"] == "committed", "real reprocess failed (not business RED): "+repr(result))
        links = result["links"]
        return {"created": len(links["create"]), "updated": len(links["update"]),
                "deleted": len(links["delete_ids"]), "raw": result}

    def close(self):
        self.owner.registry.pop(self.handle, None)
        if self.key:
            OperationLog.objects.filter(action_type="horse_binding_committed", target_type="horse_binding_request",
                                        target_id=self.key).delete()
        self.article.delete()
        self.horse.delete()
        self.term.delete()
        self.actor.delete()
        self.other.delete()
        self.temp.cleanup()


class _LateStrongWindow:
    """Two actual PG sessions; barrier is before the scanner parent lock.

    This observes a scheduling wait, not pg_blocking_pids or a DB-lock wait.
    Main strong writer must commit before releasing the scanner. No main write
    is awaited while the correctly repaired scanner holds its parent lock.
    """
    def __init__(self, fixture, path):
        self.fixture, self.path = fixture, path
        self.started = time.monotonic()
        self.deadline = self.started + TOTAL_SECONDS
        self.main = connections["default"]
        self.ready, self.release, self.done = threading.Event(), threading.Event(), threading.Event()
        self.worker = self.worker_raw = self.worker_pid = self.worker_ident = None
        self.error = self.trace = self.result = None
        self.initial_seen = self.committed = False
        self.parent_gate_seen = False
        self.initial_cache = None
        self.notes = []

    def remaining(self):
        return max(0, self.deadline-time.monotonic())

    def budget(self, execute, sql, params, many, context):
        remaining = self.remaining()
        require(remaining > 0, "overall scenario deadline exhausted before SQL")
        with context["connection"].connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, false), set_config('lock_timeout', %s, false)",
                (str(max(1, int(min(STATEMENT_SECONDS, remaining)*1000)))+"ms",
                 str(max(1, int(min(LOCK_SECONDS, remaining)*1000)))+"ms"))
        if (threading.get_ident() == self.worker_ident and not self.parent_gate_seen
                and 'FROM "stable_newsarticle"' in sql and "FOR UPDATE" in sql.upper()):
            require(self.initial_seen and self.initial_cache == [], "real initial absent read must precede parent SQL")
            require(context["connection"].connection is self.worker_raw, "parent SQL raw connection changed")
            require(context["connection"].in_atomic_block, "parent lock request must use business transaction")
            self.parent_gate_seen = True
            self.notes.append({"parent_SQL_before_real_execute": sql, "params": params,
                               "parent_lock_acquired": False, "initial_read_and_python_plan_completed": True,
                               "worker_in_atomic_block": True, "same_worker_raw_connection": True})
            self.ready.set()
            wait_started = time.monotonic()
            require(self.release.wait(min(BARRIER_SECONDS, self.remaining())), "before-parent release deadline")
            require(self.initial_cache == [], "observer changed original initial cache while waiting")
            self.notes.append({"scheduling_wait_seconds": time.monotonic()-wait_started,
                               "original_empty_result_unchanged": True,
                               "returned_result_list_identity": id(self.initial_cache)})
        value = execute(sql, params, many, context)
        if threading.get_ident() == self.worker_ident and "FOR UPDATE" in sql.upper():
            self.notes.append({"real_lock_query_returned": sql, "worker_pid": self.worker_pid,
                               "same_worker_raw_connection": context["connection"].connection is self.worker_raw})
        return value

    def __enter__(self):
        self.main.ensure_connection()
        require(self.main.vendor == "postgresql" and self.main.get_autocommit() and not self.main.in_atomic_block,
                "main requires real PG autocommit")
        with self.main.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            self.main_pid = cursor.fetchone()[0]
        original = QuerySet._fetch_all
        def fetch(queryset):
            fresh = queryset._result_cache is None
            original(queryset)
            if (fresh and threading.get_ident() == self.worker_ident and queryset.model is ArticleHorseLink
                    and not self.initial_seen and not queryset.query.select_for_update):
                db = connections[queryset.db]
                require(db is connections["default"] and db.connection is self.worker_raw,
                        "initial read connection identity changed")
                require(db.get_autocommit() and not db.in_atomic_block,
                        "initial read gate must precede business parent lock")
                require(queryset._result_cache == [], "actual initial pair must be absent")
                sql, params = queryset.query.sql_with_params()
                require(self.fixture.article.pk in params, "initial query lacks the fixture article locator")
                cache_identity = id(queryset._result_cache)
                self.initial_seen = True
                self.initial_cache = queryset._result_cache
                self.notes.append({"initial_query": sql, "params": params, "actual_rows": [],
                                   "autocommit": True, "in_atomic_block": False, "select_for_update": False,
                                   "A_pid": self.main_pid, "B_pid": self.worker_pid,
                                   "original_result_list_identity": cache_identity})
                require(id(queryset._result_cache) == cache_identity and queryset._result_cache == [],
                        "observer changed the original empty query result")
            return None
        self.patch = patch.object(QuerySet, "_fetch_all", new=fetch)
        self.patch.start()
        self.main_budget = self.main.execute_wrapper(self.budget)
        self.main_budget.__enter__()
        return self

    def start(self):
        require(self.worker is None, "only one worker is permitted")
        def work():
            db = connections["default"]
            try:
                self.worker_ident = threading.get_ident()
                db.ensure_connection()
                self.worker_raw = db.connection
                require(db.vendor == "postgresql" and db.get_autocommit() and not db.in_atomic_block,
                        "worker requires PG autocommit")
                with db.execute_wrapper(self.budget):
                    with db.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        self.worker_pid = cursor.fetchone()[0]
                    require(self.worker_pid != self.main_pid, "distinct PG sessions required")
                    self.result = self.fixture.invoke(self.path)
                    require(db.get_autocommit() and not db.in_atomic_block, "worker returned before natural commit")
                    self.committed = True
            except BaseException as error:
                self.error, self.trace = error, traceback.format_exc()
            finally:
                try:
                    db.close()
                except BaseException as caught:
                    if self.error is None:
                        self.error, self.trace = caught, traceback.format_exc()
                finally:
                    self.done.set()
        self.worker = threading.Thread(target=work, name="c245-before-parent", daemon=True)
        self.worker.start()

    def wait_ready(self):
        end = min(self.deadline, time.monotonic()+BARRIER_SECONDS)
        while not self.ready.is_set():
            require(not self.done.is_set(), "worker ended before pre-parent SQL gate: "+repr(self.error))
            require(time.monotonic() < end, "pre-parent SQL observation deadline")
            self.ready.wait(min(.02, max(0, end-time.monotonic())))

    def finish(self):
        self.worker.join(max(0, self.remaining()-1))
        require(not self.worker.is_alive(), "worker failed bounded natural completion")
        if self.error is not None:
            raise StrongProtectionScenarioError("worker DB/API error; original trace retained: "+str(self.trace)) from self.error
        require(self.initial_seen and self.parent_gate_seen and self.committed and self.done.is_set(),
                "worker natural commit/initial read/pre-parent gate identity not proven")
        return self.result

    def __exit__(self, kind, error, tb):
        self.release.set()
        issues = []
        if self.worker is not None:
            self.worker.join(max(0, self.remaining()-1))
            if self.worker.is_alive() and self.worker_raw is not None:
                try:
                    self.worker_raw.cancel_safe(timeout=min(.5, max(.01, self.remaining())))
                except BaseException as caught:
                    issues.append("cancel: "+repr(caught))
                self.worker.join(self.remaining())
            if self.worker.is_alive():
                issues.append("worker survived bounded join/cancel")
        snapshot = None
        try:
            snapshot = self.fixture.state()
        except BaseException as caught:
            issues.append("final snapshot: "+repr(caught))
        self.patch.stop()
        self.main_budget.__exit__(kind, error, tb)
        self.main.close()
        emit("two_PG_window", path=self.path, A_pid=self.main_pid, B_pid=self.worker_pid,
             notes=self.notes, committed=self.committed, result=self.result, worker_trace=self.trace,
             final_state=snapshot, primary_error=repr(error) if error else None,
             elapsed_seconds=time.monotonic()-self.started, cleanup_issues=issues,
             scheduling_barrier_is_not_DB_lock_wait_proof=True)
        if self.remaining() <= 0:
            issues.append("overall 40-second deadline")
        if issues:
            raise StrongProtectionScenarioError("bounded cleanup failed: "+repr(issues)) from error
        if self.error is not None and error is None:
            raise StrongProtectionScenarioError("worker system ERROR: "+str(self.trace)) from self.error
        return False


@override_settings(AUTO_REWRITE_ENABLED=False, AUTO_DUPLICATE_HIGH_THRESHOLD=0,
                   AUTO_DUPLICATE_REVIEW_THRESHOLD=0, CELERY_TASK_ALWAYS_EAGER=True)
class CurrentMarkedStrongEvidenceProtectionTests(TransactionTestCase):
    def setUp(self):
        require(connections["default"].vendor == "postgresql", "requires isolated PostgreSQL; no skip/fallback")
        self.sequence, self.registry = 0, {}
        settings_context = override_settings(HORSE_ARTICLE_BINDING_HANDLES=self.registry)
        settings_context.enable()
        self.addCleanup(settings_context.disable)

    @contextmanager
    def domain(self):
        self.sequence += 1
        fixture = _Domain(self, "c245-"+self._testMethodName[5:85]+"-"+str(self.sequence))
        try:
            yield fixture
        finally:
            fixture.close()

    def check_after(self, fixture, expected, result, *, path, phase, public=True):
        actual = fixture.state()
        readers = fixture.readers()
        emit("postconditions", path=path, phase=phase, expected=expected, actual=actual,
             result=result, readers=readers)
        # A first business failure must not hide independent receipt/count/reader
        # observations or the second real invocation of the same writer.
        with self.subTest(phase=phase, check="full_current_rows"):
            self.assertEqual(actual["rows"], expected["rows"], "weak writer overwrote/deleted current marked strong evidence")
        with self.subTest(phase=phase, check="complete_receipt_rows"):
            self.assertEqual(actual["receipts"], expected["receipts"])
        with self.subTest(phase=phase, check="producer_original_bytes"):
            self.assertEqual(actual["bundle_bytes"], expected["bundle_bytes"])
        with self.subTest(phase=phase, check="actual_action_counts"):
            self.assertEqual({k: result.get(k, 0) for k in ("created", "updated", "deleted")},
                             {"created": 0, "updated": 0, "deleted": 0})
        with self.subTest(phase=phase, check="real_public_readers"):
            self.assertEqual(readers, {"article_to_horse": public, "horse_to_article": public})

    def preserve_twice(self, fixture, path, *, public=True):
        expected = fixture.state()
        for phase in ("first", "repeat"):
            result = fixture.invoke(path)
            self.check_after(fixture, expected, result, path=path, phase=phase, public=public)

    def test_profile_task_preserves_real_strong_row_receipt_readers_and_repeat(self):
        with self.domain() as f:
            f.created()
            f.weak_precondition("profile")
            self.preserve_twice(f, "profile")

    def test_article_task_preserves_real_strong_row_receipt_readers_and_repeat(self):
        with self.domain() as f:
            f.created()
            f.weak_precondition("article")
            self.preserve_twice(f, "article")

    def test_explicit_reprocess_does_not_delete_old_strong_provenance_when_input_changes(self):
        with self.domain() as f:
            f.created()
            NewsArticle.objects.filter(pk=f.article.pk).update(body_ja_raw="The schedule is confirmed.")
            f.weak_precondition("reprocess", delete=True)
            self.preserve_twice(f, "reprocess")

    def test_unknown_marked_states_stop_only_the_current_row_without_receipt_repair(self):
        cases = ("missing", "duplicate", "bad_json", "noncanonical", "hash", "replacement_pk",
                 "row_drift", "unknown_version", "source_only", "unknown_source", "schema_only",
                 "unknown_schema_only", "keys_only")
        for path in ("profile", "article"):
            for case in cases:
                with self.subTest(path=path, case=case), self.domain() as f:
                    row = f.created()
                    receipt = OperationLog.objects.get(pk=f.receipts()[0]["id"])
                    if case == "missing":
                        receipt.delete()
                    elif case == "duplicate":
                        OperationLog.objects.create(admin=receipt.admin, action_type=receipt.action_type,
                            target_type=receipt.target_type, target_id=receipt.target_id, detail=receipt.detail)
                    elif case in {"bad_json", "noncanonical", "hash"}:
                        value = json.loads(receipt.detail)
                        if case == "hash":
                            value["after_sha256"] = "0"*64
                        receipt.detail = ("{" if case == "bad_json" else json.dumps(value, indent=2)
                                          if case == "noncanonical" else fixture_data.raw(value).decode())
                        receipt.save(update_fields=["detail"])
                    elif case == "replacement_pk":
                        values = copy.deepcopy(f.rows()[0]); values.pop("id")
                        row.delete()
                        replacement = ArticleHorseLink.objects.create(**values)
                        require(replacement.pk != f.original_link_id, "replacement PK did not change")
                    else:
                        metadata = copy.deepcopy(row.metadata)
                        updates = {}
                        if case == "row_drift":
                            metadata["changed"] = True
                        elif case == "unknown_version":
                            metadata["schema_version"] = "l01.horse-link-metadata.v999"
                        elif case == "source_only":
                            metadata = {}
                        elif case == "unknown_source":
                            metadata = {}
                            updates["source"] = "strong_identity.v999"
                        elif case in {"schema_only", "unknown_schema_only"}:
                            metadata = {"schema_version": metadata["schema_version"] if case == "schema_only"
                                        else "l01.horse-link-metadata.v999"}
                            updates["source"] = "ordinary-custom"
                        else:
                            metadata.pop("schema_version")
                            updates["source"] = "ordinary-custom"
                        ArticleHorseLink.objects.filter(pk=row.pk).update(metadata=metadata, **updates)
                    f.weak_precondition(path)
                    self.preserve_twice(f, path)

    def test_ordinary_custom_source_AUTO_still_updates_to_95_without_duplicate(self):
        with self.domain() as f:
            NewsArticle.objects.filter(pk=f.article.pk).update(title_ja="Aurora won.")
            row = ArticleHorseLink.objects.create(article=f.article, horse_profile=f.horse, status="auto",
                source="custom-ordinary-source", confidence=17, metadata={"fixture": ["ordinary"]})
            f.weak_precondition("profile", auto95=True)
            for phase in ("first", "repeat"):
                result = f.invoke("profile")
                rows = f.rows()
                emit("ordinary_AUTO95", phase=phase, result=result, rows=rows)
                self.assertEqual(result, {"created": 0, "updated": 1, "candidate": 0,
                                          "skipped_removed": 0, "skipped_manual": 0})
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["id"], rows[0]["status"], rows[0]["source"], rows[0]["confidence"]),
                                 (row.pk, "auto", "auto_match", 95))
                self.assertEqual(rows[0]["metadata"], {})

    def test_ordinary_AUTO_is_still_deleted_when_real_resolver_has_no_target(self):
        with self.domain() as f:
            row = ArticleHorseLink.objects.create(article=f.article, horse_profile=f.horse, status="auto",
                                                  source="custom-ordinary-source", metadata={"ordinary": True})
            NewsArticle.objects.filter(pk=f.article.pk).update(body_ja_raw="The schedule is confirmed.")
            f.weak_precondition("article", delete=True)
            result = f.invoke("article")
            self.assertEqual(result["deleted"], 1)
            self.assertFalse(ArticleHorseLink.objects.filter(pk=row.pk).exists())
            self.assertEqual(f.invoke("article")["deleted"], 0)

    def test_unknown_marked_pair_does_not_freeze_other_ordinary_pair_in_same_scan(self):
        with self.domain() as f:
            row = f.created()
            metadata = copy.deepcopy(row.metadata)
            metadata["schema_version"] = "l01.horse-link-metadata.v999"
            ArticleHorseLink.objects.filter(pk=row.pk).update(metadata=metadata)
            term = TermEntry.objects.create(term_type="horse", source_ja="Comet", target_zh="彗星", source_language="en")
            horse = HorseProfile.objects.create(primary_term=term, original_name="Comet", review_status="published")
            try:
                ordinary = ArticleHorseLink.objects.create(article=f.article, horse_profile=horse, status="auto",
                    source="other-custom-source", confidence=17, metadata={"ordinary": True})
                NewsArticle.objects.filter(pk=f.article.pk).update(title_ja="Aurora won. Comet won.")
                f.article.refresh_from_db()
                resolution = resolve_article_entities(f.article.title_ja, f.article.body_ja_raw, source_language="en")
                require(any(x.entity_type == "horse" and x.term_id == term.pk and x.field_name == "title"
                            for x in resolution.entities), "real other ordinary desired precondition absent")
                expected = f.state()
                for phase in ("first", "repeat"):
                    result = f.invoke("article")
                    current = ArticleHorseLink.objects.get(pk=ordinary.pk)
                    emit("same_scan_row_scope", phase=phase, result=result, strong_before=expected,
                         strong_after=f.state(), ordinary=fixture_data.snapshot(current))
                    with self.subTest(phase=phase, check="unknown_current_row_only"):
                        self.assertEqual(f.state(), expected)
                    with self.subTest(phase=phase, check="other_ordinary_pair_mutable"):
                        self.assertEqual((current.status, current.source), ("auto", "contextual_entity_resolution"))
                        self.assertEqual(current.metadata["entity"]["term_id"], term.pk)
                        self.assertGreaterEqual(result["updated"], 1)
            finally:
                horse.delete()
                term.delete()

    def test_real_staff_confirm_remove_prioritize_current_row_even_with_bad_receipt(self):
        for path in ("profile", "article"):
            for action in ("confirm", "remove"):
                with self.subTest(path=path, action=action), self.domain() as f:
                    f.created()
                    f.staff(action)
                    OperationLog.objects.filter(pk=f.receipts()[0]["id"]).update(detail="{bad receipt")
                    f.weak_precondition(path)
                    self.preserve_twice(f, path, public=action == "confirm")

    def test_profile_unknown_marked_pair_does_not_abort_other_ordinary_article(self):
        with self.domain() as f:
            row = f.created()
            metadata = copy.deepcopy(row.metadata)
            metadata["schema_version"] = "l01.horse-link-metadata.v999"
            ArticleHorseLink.objects.filter(pk=row.pk).update(metadata=metadata)
            article = NewsArticle.objects.create(source_site="tdn", source_mode="latest",
                source_article_id=f.token+"-ordinary", source_url="https://example.invalid/ordinary",
                title_ja="Aurora won.", body_ja_raw="Aurora won.", source_language="en",
                published_at=timezone.now()-timedelta(days=1), workflow_status="published",
                published_to_web_at=timezone.now()-timedelta(days=1))
            try:
                ordinary = ArticleHorseLink.objects.create(article=article, horse_profile=f.horse, status="auto",
                    source="other-custom-source", confidence=17, metadata={"ordinary": True})
                match = horse_profiles._match_article(article, f.horse, horse_profiles._profile_match_terms(f.horse))
                require(match is not None and match.status == "auto" and match.confidence == 95,
                        "actual other profile match is not AUTO95")
                require(f.article.published_to_web_at > article.published_to_web_at,
                        "unknown pair must precede ordinary pair in real scanner ordering")
                expected = f.state()
                for phase in ("first", "repeat"):
                    result = f.invoke("profile")
                    current = ArticleHorseLink.objects.get(pk=ordinary.pk)
                    emit("profile_same_scan_row_scope", phase=phase, result=result,
                         strong_before=expected, strong_after=f.state(), ordinary=fixture_data.snapshot(current))
                    with self.subTest(phase=phase, check="unknown_current_row_only"):
                        self.assertEqual(f.state(), expected)
                    with self.subTest(phase=phase, check="later_ordinary_article_mutable"):
                        self.assertEqual((current.status, current.source, current.confidence), ("auto", "auto_match", 95))
                        self.assertEqual(result["updated"], 1)
            finally:
                article.delete()

    def test_real_staff_replacement_current_PK_is_not_historical_receipt_PK(self):
        for path in ("profile", "article"):
            for action in ("confirm", "remove"):
                with self.subTest(path=path, action=action), self.domain() as f:
                    f.created().delete()
                    response = f.client.post(reverse("console-horse-profile-add-article-link", args=[f.horse.pk]),
                                             {"article_id": f.article.pk, "status": "manual"})
                    require(response.status_code == 302 and len(f.rows()) == 1, "real manual replacement failed")
                    require(f.rows()[0]["id"] != f.original_link_id, "manual replacement reused historical PK")
                    f.staff(action)
                    self.assertEqual(json.loads(f.receipts()[0]["detail"])["link_id"], f.original_link_id)
                    self.preserve_twice(f, path, public=action == "confirm")

    def test_real_staff_reset_keeps_marked_candidate_and_never_auto_revives(self):
        for path in ("profile", "article"):
            with self.subTest(path=path), self.domain() as f:
                f.created()
                NewsArticle.objects.filter(pk=f.article.pk).update(title_ja="Aurora won.")
                f.staff("reset")
                f.weak_precondition(path, auto95=True)
                self.preserve_twice(f, path, public=False)

    def test_preservation_does_not_relax_current_authority_or_snapshot_CAS(self):
        for path in ("profile", "article"):
            for change in ("revoked", "expired", "inactive", "outsider", "identity_retired", "input"):
                with self.subTest(path=path, change=change), self.domain() as f:
                    f.created()
                    if change == "revoked":
                        f.scope["revoked"] = True
                    elif change == "expired":
                        f.scope["expires_at"] = (timezone.now()-timedelta(seconds=1)).isoformat()
                    elif change == "inactive":
                        get_user_model().objects.filter(pk=f.actor.pk).update(is_active=False)
                    elif change == "identity_retired":
                        HorseExternalIdentity.objects.filter(pk=f.identity.pk).update(status="retired")
                    elif change == "input":
                        NewsArticle.objects.filter(pk=f.article.pk).update(title_zh="new input snapshot")
                    f.weak_precondition(path)
                    self.preserve_twice(f, path)
                    before = f.state()
                    result = commit_strong_horse_binding(f.handle, f.other if change == "outsider" else f.actor)
                    emit("authority_CAS_recheck", change=change, result=result, before=before, after=f.state())
                    self.assertEqual(result["status"], "historical_applied_drifted" if change == "input"
                                     else "blocked_current_authority")
                    self.assertEqual(f.state(), before)

    def test_preview_is_read_only_and_commit_rechecks_later_real_staff_state(self):
        with self.domain() as f:
            f.created()
            f.weak_precondition("article")
            resolution = resolve_article_entities("", "Aurora won.", source_language="en")
            before = f.state()
            preview = horse_profiles.reconcile_article_horse_links(f.article, resolution, commit=False)
            self.assertEqual(f.state(), before)
            f.staff("remove")
            expected = f.state()
            result = f.invoke("article")
            self.check_after(f, expected, result, path="article", phase="after_preview", public=False)
            emit("preview", preview=preview, later_current=expected)
            with self.subTest(check="preview_strong_protection"):
                self.assertEqual((preview["create"], preview["update"], preview["delete_ids"]), ([], [], []))
            self.check_after(f, expected, f.invoke("article"), path="article", phase="repeat", public=False)

    def late_strong(self, path):
        with self.domain() as f:
            f.weak_precondition(path)
            require(not f.rows(), "late-strong fixture must start absent")
            with _LateStrongWindow(f, path) as window:
                window.start()
                window.wait_ready()
                f.created()
                require(window.main.get_autocommit() and not window.main.in_atomic_block,
                        "strong writer must really commit before scanner release")
                expected = f.state()
                window.notes.append({"main_strong_committed_before_release": True,
                                     "current_rows": expected["rows"], "receipts": expected["receipts"]})
                window.release.set()
                result = window.finish()
                self.check_after(f, expected, result, path=path, phase="after_initial_absent_read")
            self.check_after(f, expected, f.invoke(path), path=path, phase="repeat")

    def test_article_scan_rechecks_strong_committed_after_initial_absent_read(self):
        self.late_strong("article")

    def test_profile_scan_rechecks_strong_committed_after_initial_absent_read(self):
        self.late_strong("profile")
