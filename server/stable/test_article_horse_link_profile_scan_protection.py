"""L02 profile扫描：真实人工否决不得被已读AUTO的迟到写入覆盖。"""
import copy
import json
import threading
import time
import traceback
from contextlib import ExitStack
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.db.models.query import QuerySet
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable import views
from stable.models import (
    ArticleHorseLink, ArticleHorseLinkStatus, ArticleTranslationStatus,
    HorseProfile, HorseProfileStatus, NewsArticle, RacingRegion,
    SourceLanguage, SourceMode, SourceSite, TermEntry, TermType, WorkflowStatus,
)
from stable.tasks import scan_article_horse_links_task


TOTAL_SECONDS = 40
BARRIER_SECONDS = 5
STATEMENT_SECONDS = 20
LOCK_SECONDS = 10


class ProfileScanScenarioError(RuntimeError):
    """准备、调度、PG及有限收尾错误是ERROR，不当业务RED。"""


def require(condition, message):
    if not condition:
        raise ProfileScanScenarioError(message)


def row_values(row):
    return copy.deepcopy({field.attname: getattr(row, field.attname)
                          for field in row._meta.concrete_fields})


class _ProfileScanWindow:
    def __init__(self, method):
        self.method = method
        self.started = time.monotonic()
        self.deadline = self.started + TOTAL_SECONDS
        self.main = connections["default"]
        self.article_id = self.profile_id = self.link_id = None
        self.worker = self.worker_ident = self.worker_pid = self.worker_raw = None
        self.result = self.error = self.trace = None
        self.main_results = []
        self.committed = False
        self.initial_seen = self.initial_returned = False
        self.ready = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.notes = []
        self.note_lock = threading.Lock()
        self.stack = ExitStack()

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def note(self, **values):
        with self.note_lock:
            self.notes.append(copy.deepcopy(values))

    def budget_sql(self, execute, sql, params, many, context):
        remaining = self.remaining()
        require(remaining > 0, "40-second scenario budget exhausted before SQL")
        with context["connection"].connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false), "
                "set_config('lock_timeout', %s, false)",
                (str(max(1, int(min(STATEMENT_SECONDS, remaining) * 1000))) + "ms",
                 str(max(1, int(min(LOCK_SECONDS, remaining) * 1000))) + "ms"),
            )
        return execute(sql, params, many, context)

    def wait(self, event, label):
        end = min(self.deadline, time.monotonic() + BARRIER_SECONDS)
        while not event.is_set():
            require(not self.done.is_set(), "worker ended before " + label + ": " + repr(self.error))
            remaining = end - time.monotonic()
            require(remaining > 0, "5-second barrier expired: " + label)
            event.wait(min(0.02, remaining))

    def __enter__(self):
        try:
            self.main.ensure_connection()
            require(self.main.vendor == "postgresql", "isolated PostgreSQL required; no skip/fallback")
            require(self.main.get_autocommit() and not self.main.in_atomic_block,
                    "TransactionTestCase must use main autocommit")
            self.stack.enter_context(self.main.execute_wrapper(self.budget_sql))
            with self.main.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                self.main_pid = cursor.fetchone()[0]
            original_first = QuerySet.first
            original_upsert = QuerySet.update_or_create

            def first(queryset, *args, **kwargs):
                row = original_first(queryset, *args, **kwargs)
                if (threading.get_ident() == self.worker_ident
                        and queryset.model is ArticleHorseLink and not self.initial_seen
                        and row is not None and row.pk == self.link_id
                        and row.article_id == self.article_id
                        and row.horse_profile_id == self.profile_id):
                    db = connections[queryset.db]
                    require(db is connections["default"] and db.connection is self.worker_raw,
                            "initial read must use the recorded worker connection")
                    require(not queryset.query.select_for_update and db.get_autocommit()
                            and not db.in_atomic_block,
                            "initial read gate must be outside business transaction/row locks")
                    require(self.worker_pid != self.main_pid, "distinct PG backends required")
                    require(row.status == ArticleHorseLinkStatus.AUTO, "real initial relation is not AUTO")
                    initial = row_values(row)
                    identity = id(row)
                    self.initial_seen = True
                    self.note(real_initial_row=initial, first_query_completed=True,
                              original_object_identity=identity, worker_autocommit=True,
                              worker_in_atomic_block=False, select_for_update=False,
                              A_pid=self.main_pid, B_pid=self.worker_pid)
                    # 原查询已结束；先让真实人工remove提交，再原样返回旧对象。
                    self.ready.set()
                    self.wait(self.release, "real staff removal committed")
                    require(id(row) == identity and row_values(row) == initial,
                            "observer changed or refreshed the original AUTO object")
                    self.initial_returned = True
                    self.note(returned_original_object_identity=id(row),
                              returned_same_initial_object=True)
                return row

            def upsert(queryset, *args, **kwargs):
                profile_id = kwargs.get("horse_profile_id") or getattr(kwargs.get("horse_profile"), "pk", None)
                article_id = kwargs.get("article_id") or getattr(kwargs.get("article"), "pk", None)
                observe = (threading.get_ident() == self.worker_ident
                           and queryset.model is ArticleHorseLink
                           and profile_id == self.profile_id and article_id == self.article_id)
                if observe:
                    self.note(optional_upsert_defaults=kwargs.get("defaults", {}))
                # 透明转发，无屏障，也不要求正确GREEN必须调用此方法。
                result = original_upsert(queryset, *args, **kwargs)
                if observe:
                    self.note(optional_upsert_return={"pk": result[0].pk,
                              "status": result[0].status, "created": result[1]})
                return result

            self.stack.enter_context(patch.object(QuerySet, "first", new=first))
            self.stack.enter_context(patch.object(QuerySet, "update_or_create", new=upsert))
        except BaseException:
            self.stack.close()
            self.main.close()
            raise
        return self

    def start(self):
        require(self.worker is None, "only one worker allowed")

        def run():
            db = connections["default"]
            try:
                self.worker_ident = threading.get_ident()
                db.ensure_connection()
                self.worker_raw = db.connection
                require(db.vendor == "postgresql" and db.get_autocommit()
                        and not db.in_atomic_block, "worker requires PG autocommit")
                with db.execute_wrapper(self.budget_sql):
                    with db.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        self.worker_pid = cursor.fetchone()[0]
                    require(self.worker_pid != self.main_pid, "worker backend is not independent")
                    self.result = scan_article_horse_links_task.run(profile_id=self.profile_id, commit=True)
                    require(db.get_autocommit() and not db.in_atomic_block, "worker returned before commit")
                    self.committed = True
            except BaseException as error:
                self.error = error
                self.trace = traceback.format_exc()
            finally:
                try:
                    db.close()
                except BaseException as error:
                    if self.error is None:
                        self.error, self.trace = error, traceback.format_exc()
                finally:
                    self.done.set()

        self.worker = threading.Thread(target=run, name="c228-profile-scan", daemon=True)
        self.worker.start()

    def join(self):
        if self.worker is None:
            return []
        issues = []
        self.worker.join(max(0.0, self.remaining() - 1))
        if self.worker.is_alive():
            try:
                if self.worker_raw is not None and self.remaining() > 0.01:
                    self.worker_raw.cancel_safe(timeout=min(0.5, self.remaining()))
            except BaseException as error:
                issues.append("bounded cancellation: " + repr(error))
            self.worker.join(self.remaining())
        if self.worker.is_alive():
            issues.append("worker survived 40-second bounded join/cancellation")
        return issues

    def finish(self):
        issues = self.join()
        require(not issues, repr(issues))
        require(self.error is None, "worker ERROR: " + repr(self.error) + " " + str(self.trace))
        require(self.done.is_set() and self.committed and self.initial_returned,
                "worker did not return original initial object and naturally commit")
        return self.result

    def run_main(self):
        result = scan_article_horse_links_task.run(profile_id=self.profile_id, commit=True)
        require(self.main.get_autocommit() and not self.main.in_atomic_block,
                "control task did not naturally finish")
        self.main_results.append(copy.deepcopy(result))
        if self.worker is None and self.result is None:
            self.result = copy.deepcopy(result)
        return result

    def __exit__(self, kind, error, tb):
        self.release.set()
        issues = self.join()
        snapshot_error = None
        try:
            rows = list(ArticleHorseLink.objects.filter(article_id=self.article_id).order_by("id").values())
        except BaseException as caught:
            rows = None
            snapshot_error = repr(caught)
        if not self.remaining():
            issues.append("40-second scenario budget exhausted")
        try:
            self.stack.close()
        except BaseException as caught:
            issues.append("observer/budget restoration: " + repr(caught))
        finally:
            try:
                self.main.close()
            except BaseException as caught:
                issues.append("main connection close: " + repr(caught))
        print("\nL02_PROFILE_SCAN_SCENARIO " + json.dumps({
            "method": self.method, "article_id": self.article_id, "profile_id": self.profile_id,
            "link_id": self.link_id, "A_pid": self.main_pid, "B_pid": self.worker_pid,
            "notes": self.notes, "actual_task_result": self.result,
            "actual_main_task_results": self.main_results, "worker_started": self.worker is not None,
            "worker_committed": self.committed if self.worker is not None else None,
            "worker_error": repr(self.error) if self.error else None,
            "worker_trace": self.trace, "final_rows": rows, "snapshot_error": snapshot_error,
            "cleanup_issues": issues, "primary_error": repr(error) if error else None,
            "elapsed_seconds": time.monotonic() - self.started,
        }, ensure_ascii=False, default=str), flush=True)
        if issues or snapshot_error or self.error:
            raise ProfileScanScenarioError("scenario cleanup/worker ERROR; see original receipt") from error


@override_settings(AUTO_REWRITE_ENABLED=False, AUTO_DUPLICATE_HIGH_THRESHOLD=0,
                   AUTO_DUPLICATE_REVIEW_THRESHOLD=0, ENGLISH_TERM_CONTEXT_MODE="enforce")
class ArticleHorseLinkProfileScanProtectionPGTests(TransactionTestCase):
    def fixture(self, scenario):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE, source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES, source_ja="Do Deuce", target_zh="多爵", priority=100,
        )
        self.profile = HorseProfile.objects.create(
            primary_term=term, original_name="Do Deuce", english_name="Do Deuce", display_name_zh="多爵",
            racing_region=RacingRegion.UNITED_STATES, review_status=HorseProfileStatus.PUBLISHED,
            published_at=timezone.now(),
        )
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.TDN, source_mode=SourceMode.LATEST, source_article_id="c228-synthetic",
            source_url="https://example.invalid/c228", source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES, title_ja="Do Deuce won the race.",
            body_ja_raw="Do Deuce won the race.", body_ja_normalized="Do Deuce won the race.",
            title_zh="多爵合成新闻", body_zh="仅用于隔离profile扫描人工否决回归。" * 8,
            translation_status=ArticleTranslationStatus.TRANSLATED, workflow_status=WorkflowStatus.PUBLISHED,
            published_at=timezone.now(), published_to_web_at=timezone.now(),
        )
        self.link = ArticleHorseLink.objects.create(
            article=self.article, horse_profile=self.profile, status=ArticleHorseLinkStatus.AUTO,
            source="c228-existing", confidence=77, matched_text="original evidence",
            match_reason="preserve committed staff removal", metadata={"fixture": {"original": ["keep"]}},
        )
        scenario.article_id, scenario.profile_id, scenario.link_id = self.article.pk, self.profile.pk, self.link.pk
        user = get_user_model().objects.create_user(username="c228-staff", is_staff=True)
        self.client.force_login(user)
        return user

    def remove(self, scenario, user):
        response = self.client.post(reverse("console-horse-profile-article-link-status", args=[self.link.pk]),
                                    {"action": "remove"})
        require(response.status_code == 302, "real staff removal POST did not redirect")
        require(scenario.main.get_autocommit() and not scenario.main.in_atomic_block,
                "staff POST did not naturally finish its transaction")
        row = ArticleHorseLink.objects.filter(pk=self.link.pk).values().get()
        require(row["status"] == ArticleHorseLinkStatus.REMOVED
                and row["removed_by_id"] == user.pk and row["removed_at"] is not None,
                "real committed REMOVED row lacks status/actor/time")
        scenario.note(real_staff_status=302, staff_committed_row=row)
        return row

    def public_relation(self, visible):
        article = views._public_published_articles().get(pk=self.article.pk)
        self.assertEqual(self.profile.pk in {link.horse_profile_id for link in article.public_horse_links}, visible)
        entries = views._public_horse_article_entries(self.profile)
        self.assertEqual(self.article.pk in {entry["article"].pk for entry in entries}, visible)

    def protected_result(self):
        return {"created": 0, "updated": 0, "candidate": 0, "skipped_removed": 1, "skipped_manual": 0}

    def test_profile_scan_preserves_removal_committed_after_real_initial_AUTO_read(self):
        with _ProfileScanWindow(self.id()) as scenario:
            user = self.fixture(scenario)
            scenario.start()
            try:
                scenario.wait(scenario.ready, "completed real initial AUTO read outside transaction")
                committed = self.remove(scenario, user)
            finally:
                scenario.release.set()
                result = scenario.finish()
            row = ArticleHorseLink.objects.filter(pk=self.link.pk).values().get()
            self.assertEqual(row["status"], ArticleHorseLinkStatus.REMOVED,
                             "profile scan revived a relation after committed staff removal")
            self.assertEqual(row, committed)
            self.assertEqual(result, self.protected_result())
            self.public_relation(False)
            repeated = scenario.run_main()
            self.assertEqual(repeated, result)
            self.assertEqual(ArticleHorseLink.objects.filter(pk=self.link.pk).values().get(), committed)
            self.public_relation(False)

    def test_profile_scan_preserves_already_removed_relation_and_repeat(self):
        with _ProfileScanWindow(self.id()) as scenario:
            user = self.fixture(scenario)
            committed = self.remove(scenario, user)
            self.assertEqual(scenario.run_main(), self.protected_result())
            self.assertEqual(ArticleHorseLink.objects.filter(pk=self.link.pk).values().get(), committed)
            self.public_relation(False)
            self.assertEqual(scenario.run_main(), self.protected_result())
            self.assertEqual(ArticleHorseLink.objects.filter(pk=self.link.pk).values().get(), committed)
            self.public_relation(False)

    def test_profile_scan_updates_ordinary_AUTO_without_duplicate(self):
        with _ProfileScanWindow(self.id()) as scenario:
            self.fixture(scenario)
            result = scenario.run_main()
            self.assertEqual(result, {"created": 0, "updated": 1, "candidate": 0,
                                      "skipped_removed": 0, "skipped_manual": 0})
            rows = list(ArticleHorseLink.objects.filter(article=self.article, horse_profile=self.profile).values())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], self.link.pk)
            self.assertEqual(rows[0]["status"], ArticleHorseLinkStatus.AUTO)
            self.assertEqual(rows[0]["source"], "auto_match")
            self.assertEqual(rows[0]["confidence"], 95)
            self.public_relation(True)
