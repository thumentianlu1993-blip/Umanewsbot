"""Five source-candidate PG scenarios; no execution is claimed by C206.

Fixtures are synthetic. Only scheduling and observations wrap real queries/calls;
no resolver DTO, ORM result, staff state transition or future helper is faked.
"""
import copy
import io
import json
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.db.models.query import QuerySet
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable import views
from stable.models import (
    ArticleHorseLink, ArticleHorseLinkStatus, ArticleTranslationStatus,
    HorseProfile, HorseProfileStatus, NewsArticle, RacingRegion,
    SourceLanguage, SourceMode, SourceSite, TermEntry, TermType, WorkflowStatus,
)
from stable.services import article_entity_reprocessing as producer
from stable.services import horse_profiles


BARRIER_SECONDS = 5
OBSERVE_SECONDS = 5
LOCK_SECONDS = 10
STATEMENT_SECONDS = 20
TOTAL_SECONDS = 40


class PGScenarioError(RuntimeError):
    """Fixture/observation/thread/timeout failure: ERROR, never business RED."""


def require(condition, message):
    if not condition:
        raise PGScenarioError(message)


class _Scenario:
    """Two thread-owned connections, a bounded lifetime, and failure receipts."""
    def __init__(self, article_id, deadline):
        self.article_id = article_id
        self.deadline = deadline
        self.main = connections["default"]
        self.main_ident = threading.get_ident()
        self.worker_ident = None
        self.worker_pid = None
        self.worker_raw = None
        self.worker_result = None
        self.worker_error = None
        self.worker_trace = None
        self.worker_committed = False
        self.worker_done = threading.Event()
        self.worker = None
        self.gates = []
        self.receipts = []
        self.initial_rows = None
        self.initial_ready = threading.Event()
        self.parent_acquired = threading.Event()
        self.link_acquired = threading.Event()
        self.a_parent_acquired = threading.Event()
        self.receipt_lock = threading.Lock()
        self.sql_deadline = threading.local()

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def note(self, **values):
        with self.receipt_lock:
            self.receipts.append(values)

    def gate(self):
        event = threading.Event()
        self.gates.append(event)  # only release gates, never observation flags
        return event

    def wait(self, event, label, seconds=BARRIER_SECONDS):
        end = min(self.deadline, time.monotonic() + seconds)
        while not event.is_set():
            if self.worker_done.is_set():
                self.raise_worker_error()
                raise PGScenarioError("worker ended before " + label)
            remaining = end - time.monotonic()
            require(remaining > 0, "bounded barrier not reached: " + label)
            event.wait(min(0.02, remaining))

    def budget_sql(self, execute, sql, params, many, context):
        remaining = min(self.deadline, getattr(self.sql_deadline, "end", self.deadline)) - time.monotonic()
        require(remaining > 0, "bounded scenario/observation budget exhausted before SQL")
        statement_ms = max(1, int(min(STATEMENT_SECONDS, remaining) * 1000))
        lock_ms = max(1, int(min(LOCK_SECONDS, remaining) * 1000))
        # Raw cursor only sets session limits, bypassing this wrapper's recursion.
        # The actual candidate statement/result still uses the real execute below.
        with context["connection"].connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false), "
                "set_config('lock_timeout', %s, false)",
                (str(statement_ms) + "ms", str(lock_ms) + "ms"),
            )
        if threading.get_ident() != self.worker_ident:
            return execute(sql, params, many, context)
        # Only observe the actual worker execute; never change SQL/params/results.
        import hashlib
        import re
        full_sql = sql if isinstance(sql, str) and len(sql) <= 16384 else None
        encoded = full_sql.encode("utf-8") if full_sql is not None else None
        if encoded is not None and len(encoded) > 16384:
            full_sql = encoded = None
        operation = (full_sql.split(None, 1)[0].upper() if full_sql else None)
        from_tables = re.findall(r'\bFROM\s+"([^"]+)"', full_sql or "", re.I)
        for_update_targets = (from_tables if operation == "SELECT" and len(from_tables) == 1
                              and not re.search(r'\bJOIN\b|;', full_sql, re.I)
                              and re.search(r'\bFOR UPDATE\s*$', full_sql, re.I) else [])
        insert = re.match(r'INSERT\s+INTO\s+"([^"]+)"', full_sql or "", re.I)
        with self.receipt_lock:
            self._worker_sql_sequence = getattr(self, "_worker_sql_sequence", 0) + 1
            statement = {
                "pid": self.worker_pid, "sequence": self._worker_sql_sequence,
                "thread_ident": threading.get_ident(),
                "same_worker_connection": context["connection"].connection is self.worker_raw,
                "sql_capture_complete": full_sql is not None, "sql_full": full_sql,
                "sql_prefix": full_sql.strip()[:192] if full_sql else None,
                "sql_sha256": hashlib.sha256(encoded).hexdigest() if encoded is not None else None,
                "operation": operation, "for_update_targets": for_update_targets,
                "insert_target": insert.group(1) if insert else None, "running": True,
            }
            self._active_worker_statement = statement
        returned_normally = False
        try:
            result = execute(sql, params, many, context)
            returned_normally = True
            return result
        finally:
            with self.receipt_lock:
                statement["running"] = False
                if for_update_targets or insert:
                    self.receipts.append({"B_execute_finished": {
                        **statement, "returned_normally": returned_normally,
                    }})

    def __enter__(self):
        require(self.remaining() > 0, "fixture setup exhausted overall 40-second budget")
        self.main.ensure_connection()
        require(self.main.vendor == "postgresql", "isolated PostgreSQL is required; no skip/fallback")
        require(self.main.get_autocommit() and not self.main.in_atomic_block,
                "TransactionTestCase must begin outside a wrapping transaction")
        self.main_budget = self.main.execute_wrapper(self.budget_sql)
        self.main_budget.__enter__()
        try:
            with self.main.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                self.main_pid = cursor.fetchone()[0]
        except BaseException:
            self.main_budget.__exit__(*sys.exc_info())
            self.main.close()
            raise
        return self

    def start(self, work):
        require(self.worker is None, "exactly one worker connection is allowed")
        def run():
            db = connections["default"]
            try:
                self.worker_ident = threading.get_ident()
                db.ensure_connection()
                require(db.vendor == "postgresql", "worker is not PostgreSQL")
                require(db.get_autocommit() and not db.in_atomic_block,
                        "worker must start in autocommit")
                self.worker_raw = db.connection
                with db.execute_wrapper(self.budget_sql):
                    with db.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        self.worker_pid = cursor.fetchone()[0]
                    require(self.worker_pid != self.main_pid, "two distinct PG backends are required")
                    self.worker_result = work()
                    require(db.get_autocommit() and not db.in_atomic_block,
                            "worker returned before its transaction/FK commit")
                    self.worker_committed = True
            except BaseException as error:
                self.worker_error = error
                self.worker_trace = traceback.format_exc()
            finally:
                # Each thread closes only its own Django connection.
                db.close()
                self.worker_done.set()
        self.worker = threading.Thread(target=run, name="c206-pg-scan", daemon=True)
        self.worker.start()

    def join(self):
        if self.worker is None:
            return []
        issues = []
        # Reserve a bounded cancellation window; DB statements are already capped.
        self.worker.join(max(0.0, self.remaining() - 1.0))
        if self.worker.is_alive():
            try:
                remaining = self.remaining()
                if self.worker_raw is not None and remaining > 0.01:
                    self.worker_raw.cancel_safe(timeout=min(0.5, remaining))
            except BaseException as error:
                issues.append("bounded cancellation: " + repr(error))
            self.worker.join(self.remaining())
        if self.worker.is_alive():
            issues.append("worker survived 40-second bounded join/cancellation")
        return issues

    def raise_worker_error(self):
        if self.worker_error is not None:
            raise PGScenarioError("worker DB/fixture error; original trace retained: "
                                  + repr(self.worker_error)) from self.worker_error

    def await_worker(self):
        issues = self.join()
        require(not issues, "; ".join(issues))
        self.raise_worker_error()
        require(self.worker_done.is_set() and self.worker_committed,
                "worker has not naturally returned through commit")
        return self.worker_result

    def __exit__(self, kind, error, tb):
        for gate in self.gates:
            gate.set()
        issues = self.join()
        snapshot = None
        snapshot_error = None
        try:
            # Before TransactionTestCase flushes anything, preserve actual state.
            snapshot = list(ArticleHorseLink.objects.filter(article_id=self.article_id)
                            .order_by("id").values())
        except BaseException as caught:
            snapshot_error = repr(caught)
        if self.remaining() <= 0:
            issues.append("overall 40-second budget exhausted")
        self.note(final_snapshot=snapshot, snapshot_error=snapshot_error,
                  elapsed_seconds=time.monotonic() - (self.deadline - TOTAL_SECONDS),
                  worker_error=repr(self.worker_error) if self.worker_error else None,
                  worker_trace=self.worker_trace, worker_committed=self.worker_committed,
                  cleanup_issues=issues, primary_error=repr(error) if error else None)
        print("\nL02_PG_SCENARIO " + json.dumps({
            "article_id": self.article_id, "A_pid": self.main_pid,
            "B_pid": self.worker_pid, "receipts": self.receipts,
        }, ensure_ascii=False, default=str), flush=True)
        self.main_budget.__exit__(kind, error, tb)
        self.main.close()
        if issues or snapshot_error is not None:
            raise PGScenarioError("bounded cleanup/state observation failed: "
                                  + repr(issues) + " " + repr(snapshot_error)) from error
        if self.worker_error is not None:
            self.raise_worker_error()
        return False


@contextmanager
def schedule_real_initial_read(scenario, release=None):
    original = QuerySet._fetch_all
    def fetch(queryset):
        fresh = queryset._result_cache is None
        original(queryset)  # never replace or synthesize the query result
        if not fresh:
            return
        tid = threading.get_ident()
        rows = queryset._result_cache
        if queryset.query.select_for_update:
            if queryset.model is NewsArticle and any(
                    isinstance(row, NewsArticle) and row.pk == scenario.article_id for row in rows):
                if tid == scenario.worker_ident:
                    scenario.parent_acquired.set()
                    scenario.note(B_query_completed="article_for_update")
                elif tid == scenario.main_ident:
                    scenario.a_parent_acquired.set()
                    scenario.note(A_query_completed="article_for_update")
            elif queryset.model is ArticleHorseLink and tid == scenario.worker_ident:
                scenario.link_acquired.set()
                scenario.note(B_query_completed="link_for_update")
        if (tid == scenario.worker_ident and queryset.model is ArticleHorseLink
                and not queryset.query.select_for_update and not scenario.initial_ready.is_set()
                and rows and all(isinstance(row, ArticleHorseLink) for row in rows)):
            scenario.initial_rows = copy.deepcopy([{
                "id": row.pk, "article_id": row.article_id,
                "horse_profile_id": row.horse_profile_id, "status": row.status,
            } for row in rows])
            scenario.note(B_initial_actual_rows=scenario.initial_rows)
            scenario.initial_ready.set()
            if release is not None:
                scenario.wait(release, "staff transaction committed before automatic persist")
    with patch.object(QuerySet, "_fetch_all", new=fetch):
        yield


def observe_real_blocking(scenario):
    end = min(scenario.deadline, time.monotonic() + OBSERVE_SECONDS)
    previous_end = getattr(scenario.sql_deadline, "end", scenario.deadline)
    scenario.sql_deadline.end = end
    try:
        return _observe_real_blocking_until(scenario, end)
    finally:
        scenario.sql_deadline.end = previous_end


def _observe_real_blocking_until(scenario, end):
    while time.monotonic() < end:
        scenario.raise_worker_error()
        require(not scenario.worker_done.is_set(), "B ended before an actual lock wait")
        with scenario.receipt_lock:
            active = getattr(scenario, "_active_worker_statement", None)
            before = dict(active) if active is not None else None
        if not before or not before["running"] or before["operation"] == "BEGIN":
            scenario.worker_done.wait(min(0.02, max(0.0, end - time.monotonic())))
            continue
        with scenario.main.cursor() as cursor:
            # A is inside _commit_article.atomic: explicitly invalidate cached stats.
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT wait_event_type, wait_event, query, pg_blocking_pids(pid) "
                "FROM pg_stat_activity WHERE pid = %s", [scenario.worker_pid],
            )
            row = cursor.fetchone()
        with scenario.receipt_lock:
            active = getattr(scenario, "_active_worker_statement", None)
            after = dict(active) if active is not None else None
        if row and row[0] == "Lock" and scenario.main_pid in row[3]:
            query = row[2].strip()
            correlated = bool(
                after and before["running"] and after["running"]
                and before["sequence"] == after["sequence"]
                and before["pid"] == after["pid"] == scenario.worker_pid
                and before["thread_ident"] == after["thread_ident"] == scenario.worker_ident
                and before["same_worker_connection"] and after["same_worker_connection"]
                and before["sql_capture_complete"] and after["sql_capture_complete"]
                and before["sql_sha256"] == after["sql_sha256"]
                and before["sql_prefix"] and query.startswith(before["sql_prefix"])
            )
            # Retain real PG facts even if association/phase classification fails.
            scenario.note(lock_wait_diagnostic={
                "wait_event_type": row[0], "wait_event": row[1],
                "blocking_pids": row[3], "A_pid": scenario.main_pid, "B_pid": scenario.worker_pid,
                "B_query": row[2][:4096], "B_query_capture_complete": len(row[2]) <= 4096,
                "B_execute_before": before, "B_execute_after": after,
                "same_inflight_execute_correlated": correlated,
                "statistics_snapshot_cleared_in_A_transaction": True,
            })
            require(correlated, "UNKNOWN: actual lock wait is not correlated to one in-flight B execute")
            if (before["operation"] == "SELECT"
                    and before["for_update_targets"] == [NewsArticle._meta.db_table]):
                phase = "parent_first_article_wait"
                require(not scenario.parent_acquired.is_set() and not scenario.link_acquired.is_set(),
                        "B completed a parent/link lock before the observed first parent wait")
            elif ((before["operation"] == "INSERT"
                   and before["insert_target"] == ArticleHorseLink._meta.db_table)
                  or before["sql_full"].upper() == "COMMIT"
                  or before["sql_full"].upper().startswith("SET CONSTRAINTS ")):
                phase = "baseline_fk_wait_control"
                require(not scenario.link_acquired.is_set(),
                        "reverse order observed: B already holds link then waits for A article")
            else:
                raise PGScenarioError("unsupported correlated blocking SQL structure; see raw diagnostic")
            receipt = {
                "observed": True, "phase": phase, "wait_event_type": row[0],
                "wait_event": row[1], "blocking_pids": row[3], "B_query": row[2][:4096],
                "B_execute": before, "same_inflight_execute_correlated": correlated,
                "B_parent_query_completed": scenario.parent_acquired.is_set(),
                "B_link_query_completed": scenario.link_acquired.is_set(),
                "statistics_snapshot_cleared_in_A_transaction": True,
                "GO_or_initial_event_used_as_lock_proof": False,
            }
            scenario.note(lock_observation=receipt)
            return receipt
        # Yield cooperatively; success depends on the next DB observation, not time.
        scenario.worker_done.wait(min(0.02, max(0.0, end - time.monotonic())))
    raise PGScenarioError("5-second real blocking observation deadline; not business RED")


@override_settings(AUTO_REWRITE_ENABLED=False, AUTO_DUPLICATE_HIGH_THRESHOLD=0,
                   AUTO_DUPLICATE_REVIEW_THRESHOLD=0, ENGLISH_TERM_CONTEXT_MODE="enforce")
class ArticleHorseLinkReconcileProtectionPGTests(TransactionTestCase):
    def profile(self, source, target):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE, source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES, source_ja=source,
            target_zh=target, priority=100,
        )
        return HorseProfile.objects.create(
            primary_term=term, original_name=source, english_name=source,
            display_name_zh=target, racing_region=RacingRegion.UNITED_STATES,
            review_status=HorseProfileStatus.PUBLISHED, published_at=timezone.now(),
        )

    def article(self, *, title, body):
        return NewsArticle.objects.create(
            source_site=SourceSite.TDN, source_mode=SourceMode.LATEST,
            source_article_id="c206-synthetic", source_url="https://example.invalid/c206",
            source_language=SourceLanguage.ENGLISH, racing_region=RacingRegion.UNITED_STATES,
            title_ja=title, body_ja_raw=body, body_ja_normalized=body,
            title_zh="合成测试新闻", body_zh="合成正文，仅用于隔离PG并发合同。" * 8,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            workflow_status=WorkflowStatus.PUBLISHED, published_at=timezone.now(),
            published_to_web_at=timezone.now(), translation_metadata={"fixture": "c206"},
        )

    def link(self, article, profile):
        return ArticleHorseLink.objects.create(
            article=article, horse_profile=profile, status=ArticleHorseLinkStatus.AUTO,
            source="c206-existing", confidence=77, matched_text="original evidence",
            match_reason="preserve after committed staff decision",
            metadata={"fixture": {"original": ["must", "survive"]}},
        )

    def public_bidirectional(self, article, profile, expected):
        visible = views._public_published_articles().get(pk=article.pk)
        forward = {link.horse_profile_id for link in visible.public_horse_links}
        backward = {row["article"].pk for row in views._public_horse_article_entries(profile)}
        self.assertEqual(profile.pk in forward, expected)
        self.assertEqual(article.pk in backward, expected)

    def matrix(self, *, automatic_action, staff_action):
        deadline = time.monotonic() + TOTAL_SECONDS
        with _Scenario(None, deadline) as scenario:
            profile = self.profile("Do Deuce", "多爵")
            title = "Do Deuce won the race." if automatic_action == "update" else "Stable bulletin"
            body = "Do Deuce won the race." if automatic_action == "update" else "The schedule is confirmed."
            article = self.article(title=title, body=body)
            scenario.article_id = article.pk
            link = self.link(article, profile)
            user = get_user_model().objects.create_user(username="c206-staff", is_staff=True)
            client = Client()
            client.force_login(user)
            before = ArticleHorseLink.objects.filter(pk=link.pk).values().get()
            dry = horse_profiles.scan_article_horse_links(article=article, commit=False)
            require(dry["created"] == 0 and dry["updated"] == int(automatic_action == "update")
                    and dry["deleted"] == int(automatic_action == "delete"),
                    "real resolver/dry-run fixture does not produce the required old action")
            require(ArticleHorseLink.objects.filter(pk=link.pk).values().get() == before,
                    "dry-run changed a fixture row")
            release = scenario.gate()
            with schedule_real_initial_read(scenario, release):
                scenario.start(lambda: horse_profiles.scan_article_horse_links(
                    article=NewsArticle.objects.get(pk=article.pk), commit=True))
                try:
                    scenario.wait(scenario.initial_ready, "real initial AUTO snapshot")
                    require(scenario.initial_rows == [{
                        "id": link.pk, "article_id": article.pk,
                        "horse_profile_id": profile.pk, "status": ArticleHorseLinkStatus.AUTO,
                    }], "initial snapshot fixture mismatch")
                    response = client.post(reverse("console-horse-profile-article-link-status",
                                                   args=[link.pk]), {"action": staff_action})
                    require(response.status_code == 302, "real staff status POST did not redirect")
                    require(scenario.main.get_autocommit() and not scenario.main.in_atomic_block,
                            "staff POST did not finish its transaction")
                    committed = ArticleHorseLink.objects.filter(pk=link.pk).values().get()
                    expected_status = (ArticleHorseLinkStatus.MANUAL if staff_action == "confirm"
                                       else ArticleHorseLinkStatus.REMOVED)
                    require(committed["status"] == expected_status, "staff status was not committed")
                    actor_field = "confirmed_by_id" if staff_action == "confirm" else "removed_by_id"
                    time_field = "confirmed_at" if staff_action == "confirm" else "removed_at"
                    require(committed[actor_field] == user.pk and committed[time_field] is not None,
                            "real staff confirmed/removed fields missing")
                    scenario.note(staff_committed_row=committed)
                finally:
                    release.set()
                    # Join inside the patch scope; never leak a query wrapper to a worker.
                    result = scenario.await_worker()
            rows = list(ArticleHorseLink.objects.filter(pk=link.pk).values())
            self.assertEqual(len(rows), 1, "late automatic delete removed a committed protected row")
            self.assertEqual(rows[0], committed, "late automatic write changed the complete protected row")
            self.assertEqual(result, {
                "created": 0, "updated": 0, "deleted": 0, "candidate": 0,
                "skipped_removed": int(staff_action == "remove"),
                "skipped_manual": int(staff_action == "confirm"),
            })
            self.public_bidirectional(article, profile, staff_action == "confirm")
            repeated = horse_profiles.scan_article_horse_links(
                article=NewsArticle.objects.get(pk=article.pk), commit=True)
            self.assertEqual(repeated, result)
            self.assertEqual(ArticleHorseLink.objects.filter(pk=link.pk).values().get(), committed)
            self.public_bidirectional(article, profile, staff_action == "confirm")

    def test_update_preserves_manual_committed_after_initial_read(self):
        self.matrix(automatic_action="update", staff_action="confirm")

    def test_update_preserves_removed_committed_after_initial_read(self):
        self.matrix(automatic_action="update", staff_action="remove")

    def test_delete_preserves_manual_committed_after_initial_read(self):
        self.matrix(automatic_action="delete", staff_action="confirm")

    def test_delete_preserves_removed_committed_after_initial_read(self):
        self.matrix(automatic_action="delete", staff_action="remove")

    def test_commit_and_scan_finish_with_bounded_parent_or_fk_wait_control(self):
        deadline = time.monotonic() + TOTAL_SECONDS
        with _Scenario(None, deadline) as scenario:
            existing_profile = self.profile("Do Deuce", "多爵")
            new_profile = self.profile("Art Power", "艺术力量")
            old_title = "Do Deuce will race. Art Power will race."
            old_body = "Do Deuce ran at the course. Art Power ran at the course."
            article = self.article(title=old_title, body=old_body)
            scenario.article_id = article.pk
            existing_link = self.link(article, existing_profile)
            # C208: observe this same real dry-run; never substitute its result.
            real_dry_reconcile = horse_profiles.reconcile_article_horse_links
            def observe_dry_reconcile(actual_article, actual_resolution, *, commit=True):
                matching = {"source_language": actual_resolution.source_language}
                for name in ("entities", "suppressed_candidates"):
                    entities = getattr(actual_resolution, name)
                    matching[name] = {
                        "total": len(entities), "limit": 8,
                        "rows": [{"term_id": item.term_id, "entity_type": item.entity_type,
                                  "field_name": item.field_name, "classification": item.classification,
                                  "confidence": item.confidence, "start": item.start, "end": item.end,
                                  "matched_text": item.matched_text[:160],
                                  "matched_text_codepoints": len(item.matched_text)}
                                 for item in entities[:8]],
                    }
                scenario.note(M5_actual_dry_matching=matching)
                plan = real_dry_reconcile(actual_article, actual_resolution, commit=commit)
                scenario.note(M5_actual_reconcile_dry_plan=copy.deepcopy(plan))
                return plan
            with patch.object(horse_profiles, "reconcile_article_horse_links", new=observe_dry_reconcile):
                old_dry = horse_profiles.scan_article_horse_links(article=article, commit=False)
            scenario.note(M5_actual_old_dry_full=copy.deepcopy(old_dry), M5_fixture={
                "article_id": article.pk, "existing_link_id": existing_link.pk,
                "source_fields": {"title_ja": article.title_ja, "body_ja_raw": article.body_ja_raw,
                                  "body_ja_normalized": article.body_ja_normalized,
                                  "source_language": article.source_language},
                "L": {"profile_id": existing_profile.pk, "term_id": existing_profile.primary_term_id},
                "N": {"profile_id": new_profile.pk, "term_id": new_profile.primary_term_id},
            })
            require(old_dry["created"] == 1 and old_dry["updated"] == 1
                    and old_dry["deleted"] == 0 and old_dry["candidate"] == 0,
                    "old real source must plan AUTO old L and new N")
            loaded = threading.Event()
            go = scenario.gate()
            def independent_scan():
                stale = NewsArticle.objects.get(pk=article.pk)
                require(stale.title_ja == old_title and stale.body_ja_normalized == old_body,
                        "B did not preload the declared old source")
                require(connections["default"].get_autocommit(), "B preload retained a transaction")
                loaded.set()
                scenario.wait(go, "A owns parent before B scan")
                return horse_profiles.scan_article_horse_links(article=stale, commit=True)
            original_reconcile = producer.reconcile_article_horse_links
            observations = []
            def a_reconcile(actual_article, actual_resolution, *, commit):
                require(actual_article.pk == article.pk and commit,
                        "unexpected actual producer boundary")
                require(scenario.main.in_atomic_block and scenario.a_parent_acquired.is_set(),
                        "A did not actually finish parent FOR UPDATE inside original atomic")
                actual_ids = {item.term_id for item in actual_resolution.entities
                              if item.entity_type in {"horse", "unknown_horse"}}
                require(existing_profile.primary_term_id in actual_ids
                        and new_profile.primary_term_id not in actual_ids,
                        "A real resolver must match L without also creating N")
                go.set()
                scenario.wait(scenario.initial_ready, "B actual initial link read")
                require({row["id"] for row in scenario.initial_rows} == {existing_link.pk},
                        "B old-link fixture changed before write")
                observations.append(observe_real_blocking(scenario))
                return original_reconcile(actual_article, actual_resolution, commit=commit)
            with schedule_real_initial_read(scenario), \
                    patch.object(producer, "reconcile_article_horse_links", new=a_reconcile):
                scenario.start(independent_scan)
                try:
                    scenario.wait(loaded, "B old source preload")
                    NewsArticle.objects.filter(pk=article.pk).update(
                        title_ja="Do Deuce won the race.", body_ja_raw="Do Deuce won the race.",
                        body_ja_normalized="Do Deuce won the race.")
                    require(scenario.main.get_autocommit(), "current fixture source was not committed")
                    out = io.StringIO()
                    call_command("reprocess_article_entities", "--article-id", str(article.pk),
                                 "--commit", "--json", stdout=out)
                    payload = json.loads(out.getvalue())
                    require(payload["mode"] == "commit" and len(payload["articles"]) == 1,
                            "actual command result fixture mismatch")
                    outcome = payload["articles"][0]
                    require(outcome["status"] == "committed",
                            "A command did not commit: " + repr(outcome))
                    require(not scenario.main.in_atomic_block and scenario.main.get_autocommit(),
                            "A returned before the original outer transaction committed")
                    scenario.note(A_natural_outer_commit_completed=True)
                finally:
                    go.set()
                    scan = scenario.await_worker()
            require(len(observations) == 1, "missing exact live lock-wait receipt")
            scenario.note(control_classification=observations[0]["phase"],
                          baseline_may_PASS=True, dynamic_link_first_deadlock_claimed=False)
            if observations[0]["phase"] == "parent_first_article_wait":
                completed = [row["B_query_completed"] for row in scenario.receipts
                             if "B_query_completed" in row]
                require(scenario.parent_acquired.is_set() and scenario.link_acquired.is_set()
                        and "article_for_update" in completed and "link_for_update" in completed,
                        "missing completed parent/link lock observation after commit")
                require(completed.index("article_for_update") < completed.index("link_for_update"),
                        "completed lock order observation is not article before link")
            self.assertEqual([row["link_id"] for row in outcome["links"]["update"]],
                             [existing_link.pk])
            self.assertEqual(outcome["links"]["create"], [])
            self.assertEqual(outcome["links"]["delete_ids"], [])
            self.assertEqual(scan, {"created": 1, "updated": 1, "deleted": 0,
                                    "candidate": 0, "skipped_removed": 0, "skipped_manual": 0})
            rows = list(ArticleHorseLink.objects.filter(article=article).order_by("horse_profile_id").values())
            self.assertEqual(len(rows), 2, "old L and new N must both naturally commit, no partial batch")
            self.assertEqual({row["horse_profile_id"] for row in rows},
                             {existing_profile.pk, new_profile.pk})
            self.assertEqual(next(row["id"] for row in rows
                                  if row["horse_profile_id"] == existing_profile.pk), existing_link.pk)
            self.assertTrue(all(row["article_id"] == article.pk
                                and row["status"] == ArticleHorseLinkStatus.AUTO for row in rows))
            joined = list(ArticleHorseLink.objects.filter(article=article)
                          .select_related("article", "horse_profile").order_by("id"))
            self.assertEqual({(row.article.pk, row.horse_profile.pk) for row in joined},
                             {(article.pk, existing_profile.pk), (article.pk, new_profile.pk)})
