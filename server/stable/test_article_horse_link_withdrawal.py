"""L02：真实旧扫描任务不得重建撤回清理后已删除的自动关系。"""
import copy
import json
import threading
import time
import traceback
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections, transaction
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


class WithdrawalScenarioError(RuntimeError):
    """准备、线程、数据库或时限问题是 ERROR，不充当业务 RED。"""


def require(condition, message):
    if not condition:
        raise WithdrawalScenarioError(message)


class _WithdrawalWindow:
    def __init__(self, name):
        self.name = name
        self.deadline = time.monotonic() + 40
        self.article_id = None
        self.main = connections["default"]
        self.worker = None
        self.worker_ident = self.worker_pid = self.worker_raw = None
        self.loaded = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.result = self.error = self.trace = None
        self.committed = False
        self.hold = False
        self.notes = []

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def budget_sql(self, execute, sql, params, many, context):
        remaining = self.remaining()
        require(remaining > 0, "40-second scenario budget exhausted before SQL")
        with context["connection"].connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false), "
                "set_config('lock_timeout', %s, false)",
                (str(max(1, int(min(20, remaining) * 1000))) + "ms",
                 str(max(1, int(min(10, remaining) * 1000))) + "ms"),
            )
        return execute(sql, params, many, context)

    def wait(self, event, label):
        end = min(self.deadline, time.monotonic() + 5)
        while not event.is_set():
            require(not self.done.is_set(), "worker ended before " + label + ": " + repr(self.error))
            require(time.monotonic() < end, "5-second barrier expired: " + label)
            event.wait(min(0.02, max(0.0, end - time.monotonic())))

    def __enter__(self):
        self.main.ensure_connection()
        require(self.main.vendor == "postgresql", "isolated PostgreSQL required; no skip/fallback")
        require(self.main.get_autocommit() and not self.main.in_atomic_block,
                "scenario requires TransactionTestCase autocommit")
        self.main_budget = self.main.execute_wrapper(self.budget_sql)
        self.main_budget.__enter__()
        try:
            with self.main.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                self.main_pid = cursor.fetchone()[0]
        except BaseException as error:
            self.main_budget.__exit__(type(error), error, error.__traceback__)
            self.main.close()
            raise
        original = QuerySet._fetch_all
        def fetch(queryset):
            fresh = queryset._result_cache is None
            original(queryset)
            if (fresh and threading.get_ident() == self.worker_ident
                    and queryset.model is NewsArticle and not self.loaded.is_set()
                    and not queryset.query.select_for_update):
                rows = queryset._result_cache
                if len(rows) == 1 and rows[0].pk == self.article_id:
                    article = rows[0]
                    require(connections["default"].get_autocommit(), "B preload retained a transaction")
                    self.notes.append({"real_task_loaded_article": {
                        "id": article.pk, "workflow_status": article.workflow_status,
                        "title_ja": article.title_ja, "body_ja_normalized": article.body_ja_normalized,
                    }})
                    self.loaded.set()
                    if self.hold:
                        self.wait(self.release, "withdrawal and deletion committed")
        self.query_patch = patch.object(QuerySet, "_fetch_all", new=fetch)
        self.query_patch.__enter__()
        return self

    def start(self, *, hold_loaded_article):
        require(self.worker is None, "only one worker allowed")
        self.hold = hold_loaded_article
        def run():
            db = connections["default"]
            try:
                self.worker_ident = threading.get_ident()
                db.ensure_connection()
                self.worker_raw = db.connection
                require(db.vendor == "postgresql" and db.get_autocommit(), "worker must use PG autocommit")
                with db.execute_wrapper(self.budget_sql):
                    with db.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        self.worker_pid = cursor.fetchone()[0]
                    require(self.worker_pid != self.main_pid, "worker must own a separate backend")
                    self.result = scan_article_horse_links_task.run(article_id=self.article_id, commit=True)
                    require(db.get_autocommit() and not db.in_atomic_block, "task returned before commit")
                    self.committed = True
            except BaseException as error:
                self.error = error
                self.trace = traceback.format_exc()
            finally:
                db.close()
                self.done.set()
        self.worker = threading.Thread(target=run, name="c216-old-scan", daemon=True)
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
                issues.append(repr(error))
            self.worker.join(self.remaining())
        if self.worker.is_alive():
            issues.append("worker survived bounded join/cancellation")
        return issues

    def finish(self):
        issues = self.join()
        require(not issues, repr(issues))
        require(self.error is None, "worker error: " + repr(self.error) + " " + str(self.trace))
        require(self.done.is_set() and self.committed, "worker did not naturally commit")
        return self.result

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
        print("\nL02_WITHDRAWAL_SCENARIO " + json.dumps({
            "method": self.name, "article_id": self.article_id,
            "A_pid": self.main_pid, "B_pid": self.worker_pid, "notes": self.notes,
            "actual_task_result": self.result, "worker_committed": self.committed,
            "worker_error": repr(self.error) if self.error else None, "worker_trace": self.trace,
            "final_rows": rows, "snapshot_error": snapshot_error, "cleanup_issues": issues,
            "primary_error": repr(error) if error else None,
            "elapsed_seconds": 40 - self.remaining(),
        }, ensure_ascii=False, default=str), flush=True)
        self.query_patch.__exit__(kind, error, tb)
        self.main_budget.__exit__(kind, error, tb)
        self.main.close()
        if issues or snapshot_error or self.error:
            raise WithdrawalScenarioError("scenario cleanup/worker ERROR; see original receipt") from error


@override_settings(AUTO_REWRITE_ENABLED=False, AUTO_DUPLICATE_HIGH_THRESHOLD=0,
                   AUTO_DUPLICATE_REVIEW_THRESHOLD=0, ENGLISH_TERM_CONTEXT_MODE="enforce")
class ArticleHorseLinkWithdrawalPGTests(TransactionTestCase):
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
            source_site=SourceSite.TDN, source_mode=SourceMode.LATEST, source_article_id="c216-synthetic",
            source_url="https://example.invalid/c216", source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES, title_ja="Do Deuce won the race.",
            body_ja_raw="Do Deuce won the race.", body_ja_normalized="Do Deuce won the race.",
            title_zh="多爵合成新闻", body_zh="隔离合成正文，仅用于关系撤回回归。" * 8,
            translation_status=ArticleTranslationStatus.TRANSLATED, workflow_status=WorkflowStatus.PUBLISHED,
            published_at=timezone.now(), published_to_web_at=timezone.now(),
        )
        scenario.article_id = self.article.pk
        initial = scan_article_horse_links_task.run(article_id=self.article.pk, commit=True)
        require(initial == {"created": 1, "updated": 0, "deleted": 0, "candidate": 0,
                            "skipped_removed": 0, "skipped_manual": 0}, "published real task fixture did not create one AUTO")
        self.old_link = ArticleHorseLink.objects.filter(article=self.article).values().get()
        require(self.old_link["status"] == ArticleHorseLinkStatus.AUTO, "initial relation is not AUTO")
        scenario.notes.append({"initial_task_result": initial, "original_AUTO_row": self.old_link})
        staff = get_user_model().objects.create_user(username="c216-staff", is_staff=True)
        self.client.force_login(staff)

    def withdraw_and_clear(self, scenario):
        response = self.client.post(reverse("console-article-editor", args=[self.article.pk]), {
            "intent": "withdraw", "title_zh": self.article.title_zh, "body_zh": self.article.body_zh,
            "racing_region": self.article.racing_region, "content_category": "news",
        })
        require(response.status_code == 302, "real withdrawal POST did not redirect")
        require(scenario.main.get_autocommit() and not scenario.main.in_atomic_block,
                "withdrawal POST transaction has not committed")
        self.withdrawn = NewsArticle.objects.filter(pk=self.article.pk).values().get()
        require(self.withdrawn["workflow_status"] == WorkflowStatus.WITHDRAWN
                and self.withdrawn["withdrawn_at"] is not None, "withdrawal was not persisted")
        # Explicit test setup: the AUTO row has already been physically cleared.
        # This does not claim that the current withdrawal view performs cleanup.
        with transaction.atomic():
            current = NewsArticle.objects.select_for_update().get(pk=self.article.pk)
            require(current.workflow_status == WorkflowStatus.WITHDRAWN, "withdrawal drifted before cleanup")
            ArticleHorseLink.objects.filter(pk=self.old_link["id"]).delete()
        require(not ArticleHorseLink.objects.filter(pk=self.old_link["id"]).exists(), "cleanup did not remove old AUTO")
        scenario.notes.append({"real_withdrawal_status": response.status_code,
                               "withdrawal_committed_row": copy.deepcopy(self.withdrawn),
                               "fixture_cleanup_deleted_AUTO_id": self.old_link["id"]})

    def assert_withdrawn_not_revived(self, scenario, result):
        self.assertEqual(list(ArticleHorseLink.objects.filter(article=self.article).values()), [],
                         "old task recreated an AUTO relation already cleared after withdrawal")
        self.assertEqual(result, {"created": 0, "updated": 0, "deleted": 0, "candidate": 0,
                                  "skipped_removed": 0, "skipped_manual": 0})
        self.assertEqual(NewsArticle.objects.filter(pk=self.article.pk).values().get(), self.withdrawn)
        self.assertFalse(views._public_published_articles().filter(pk=self.article.pk).exists())
        self.assertNotIn(self.article.pk, {row["article"].pk for row in views._public_horse_article_entries(self.profile)})
        repeated = scan_article_horse_links_task.run(article_id=self.article.pk, commit=True)
        scenario.notes.append({"actual_repeat_task_result": repeated})
        self.assertEqual(repeated, result)
        self.assertFalse(ArticleHorseLink.objects.filter(article=self.article).exists())
        self.assertEqual(NewsArticle.objects.filter(pk=self.article.pk).values().get(), self.withdrawn)
        self.assertFalse(views._public_published_articles().filter(pk=self.article.pk).exists())
        self.assertNotIn(self.article.pk, {row["article"].pk for row in views._public_horse_article_entries(self.profile)})

    def test_task_arriving_after_withdrawal_does_not_recreate_cleared_auto(self):
        with _WithdrawalWindow(self.id()) as scenario:
            self.fixture(scenario)
            self.withdraw_and_clear(scenario)
            scenario.start(hold_loaded_article=False)
            result = scenario.finish()
            require(scenario.loaded.is_set() and next(x["real_task_loaded_article"] for x in scenario.notes
                    if "real_task_loaded_article" in x)["workflow_status"] == WorkflowStatus.WITHDRAWN,
                    "delayed task did not load the committed withdrawn article")
            self.assert_withdrawn_not_revived(scenario, result)

    def test_task_loaded_before_withdrawal_revalidates_before_relation_persist(self):
        with _WithdrawalWindow(self.id()) as scenario:
            self.fixture(scenario)
            scenario.start(hold_loaded_article=True)
            try:
                scenario.wait(scenario.loaded, "real task article preload")
                require(next(x["real_task_loaded_article"] for x in scenario.notes
                        if "real_task_loaded_article" in x)["workflow_status"] == WorkflowStatus.PUBLISHED,
                        "old task did not preload a published article")
                self.withdraw_and_clear(scenario)
            finally:
                scenario.release.set()
                result = scenario.finish()
            self.assert_withdrawn_not_revived(scenario, result)
