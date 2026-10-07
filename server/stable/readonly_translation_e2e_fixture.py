"""B057测试专用helper：真实ORM/有限外部SDK与存储异常，最多2worker+主连接。

不是生产入口。不替换provider/授权/read/save/final成功，只在外部wire与实际存储提交点观察/退出。
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import time
from threading import Event, Thread, get_ident
from uuid import uuid4
from unittest.mock import patch

from django.db import IntegrityError, OperationalError, connection, connections, transaction
from django.db.models import F
from django.db.models.query import QuerySet
from stable.models import (ArticleTranslationStatus, ManagedReadonlyTaskBudget, ManagedReadonlyStep,
                           NewsArticle, NotificationLog, RacingRegion, TranslationRequestAttempt, TranslationRun)
from stable.services import managed_readonly_steps as ro, managed_readonly_translation as job
from stable.services import translation, translation_recovery as recovery
from stable.tasks import translate_article_task
from stable.test_managed_translation_budget_consumer import NOW, USAGE, fixture_requirement
from stable.test_translation_failure_recovery_change import article_for_retry


class CommittedFixtureExit(BaseException):
    """有限提交后退出；不是业务FAIL，不伪造持久状态。"""


class RemainingReadonlyE2EFixture:
    def new_scenario(self, *, register=True):
        self.clock.return_value = NOW
        # 第一子场景使用原setUp真实article，避免遗留due文章抢走batch_size=1 selector。
        if hasattr(self, "case_reader_index"):
            body = "There is more than enough time to decide after the sale. " * 6
            self.article = article_for_retry(source_article_id="b057-" + str(uuid4()),
                translation_next_retry_at=NOW, racing_region=RacingRegion.UNITED_STATES,
                title_ja="Stable update", body_ja_raw=body, body_ja_normalized=body)
        self.case_reader_index, self.case_sdk_index = len(self.readers), len(self.sdks)
        self.user_retry_message()
        if register:
            self.register()
        fixture_requirement(connection.vendor == "postgresql" and not connection.in_atomic_block,
                            "B057仅真实PG且无外层atomic")

    def normal_script(self, **fields):
        return [{"content": json.dumps(self.payload, ensure_ascii=False), "usage": USAGE, **fields}]

    @contextmanager
    def case_scope(self, script=None, *, reader_fault="none"):
        sdk = self.fake(script if script is not None else self.normal_script())
        reader = ro._ClosedSourceExcerptReader(reader_fault)
        self.sdks.append(sdk); self.readers.append(reader)
        try:
            with recovery._offline_budget_scope(self.identity), ro.readonly_scope(self.readroot.pk), \
                    translation._offline_sdk_dependency(sdk), ro.reader_dependency(reader):
                try:
                    yield reader, sdk
                finally:
                    reader.before_read_release.set(); sdk.choices_release.set()
        finally:
            self.constructor.assert_not_called()
            fixture_requirement(reader.closed and sdk._closed, "所有closed依赖须关闭")

    def case_consume(self, script=None, *, reader_fault="none"):
        args, kwargs = self.message
        with self.case_scope(script, reader_fault=reader_fault):
            result = translate_article_task.run(*args, **kwargs)
        print("B057_ACTUAL_CONSUMER", self.envelope, result, flush=True)
        return result

    def case_reads(self):
        return sum(e["event"] == "business_read" for r in self.readers[self.case_reader_index:] for e in r.trace)

    def case_creates(self):
        return [e for s in self.sdks[self.case_sdk_index:] for e in s.trace if e["event"] == "create"]

    def actual_run(self):
        return TranslationRun.objects.get(pk=self.envelope.run_id)

    def counters(self):
        self.budget.refresh_from_db(); self.readroot.refresh_from_db()
        return (self.readroot.tool_reads_reserved, self.budget.requests_reserved,
                self.readroot.steps.count(), self.budget.request_attempts.count())

    def business_snapshot(self):
        self.article.refresh_from_db(); run = self.actual_run()
        # OperationLog/task execution日志属于原task入口，不要求全task零写。
        return (deepcopy(NewsArticle.objects.filter(pk=self.article.pk).values().get()),
                deepcopy(TranslationRun.objects.filter(pk=run.pk).values().get()))

    def assert_not_applied(self):
        self.article.refresh_from_db(); run = self.actual_run()
        self.assertNotEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(self.article.body_zh, "")
        self.assertNotEqual(run.status, "success")
        self.assertNotIn(job.FINAL_KEY, run.raw_response)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def committed_read(self):
        with self.case_scope(reader_fault="exit_after_commit"):
            job.prepare_registered_read_phase(self.envelope)
            with self.assertRaises(ro.ReadFixtureExit):
                ro.execute_step(self.envelope, {"body_chars": 256}, now=NOW)
        step = self.readroot.steps.get()
        fixture_requirement(step.state == "completed" and self.case_reads() == 1
                            and self.counters() == (1, 0, 1, 0), "真实completed read前置须成立")
        return deepcopy((step.pk, step.step_uuid, step.result_sha256, step.read_at, step.result))

    @contextmanager
    def running_workers(self, action, *, count=1, releases=()):
        fixture_requirement(count in (1, 2), "worker上限2")
        state = {"pids": [], "results": [], "errors": [], "closed": [], "finished": Event()}
        ready = [Event() for _ in range(count)]
        def worker(index):
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET statement_timeout = 10000")
                    cursor.execute("SET lock_timeout = 8000")
                    cursor.execute("SELECT pg_backend_pid()")
                    state["pids"].append(cursor.fetchone()[0])
                ready[index].set()
                state["results"].append(action(index))
            except BaseException as exc:
                state["errors"].append(exc)
            finally:
                connections.close_all()
                state["closed"].append(connections["default"].connection is None)
                state["finished"].set()
        threads = [Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
        for thread in threads:thread.start()
        try:
            for event in ready:fixture_requirement(event.wait(8), "独立PG worker连接前置")
            fixture_requirement(len(set(state["pids"])) == count, "独立PG pid必须唯一")
            yield state
        finally:
            for event in releases:event.set()
            # 仅释放本fixture有限gate；连接实际close由各worker finally负责。
            for reader in self.readers[self.case_reader_index:]:reader.before_read_release.set()
            for sdk in self.sdks[self.case_sdk_index:]:sdk.choices_release.set()
            for thread in threads:thread.join(12)
            fixture_requirement(not any(t.is_alive() for t in threads), "worker须有界退出")
            fixture_requirement(state["closed"] == [True] * count, "所有worker连接须关闭")

    def workers_clean(self, state):
        fixture_requirement(not state["errors"], "后台异常为ERROR: " + repr(state["errors"]))
        self.assertEqual(len(state["results"]), len(state["pids"]))

    def wait_lock_graph(self, pids, owner, *, owner_is_worker=False):
        end = time.monotonic() + 8
        rows = []
        while time.monotonic() < end:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pid, wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity "
                               "WHERE pid=ANY(%s)", [pids + [owner]])
                rows = cursor.fetchall()
            graph = {pid: (kind, blockers) for pid, kind, blockers in rows}
            if owner_is_worker:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT xact_start IS NOT NULL FROM pg_stat_activity WHERE pid=%s", [owner])
                    owner_transaction = cursor.fetchone()[0]
            else:owner_transaction = connection.in_atomic_block
            def reaches(pid, seen):
                if pid == owner:return owner in graph and owner_transaction
                if pid in seen or pid not in graph:return False
                kind, blockers = graph[pid]
                return kind == "Lock" and bool(blockers) and all(
                    p in set(pids + [owner]) and reaches(p, seen | {pid}) for p in blockers)
            if all(reaches(pid, set()) for pid in pids):
                print("B057_ACTUAL_LOCK_GRAPH", owner, pids, rows, flush=True)
                return
            time.sleep(.025)
        fixture_requirement(False, "未观测真实PG阻塞链: " + repr(rows))

    def no_business_locks(self, pid):
        with connection.cursor() as cursor:
            cursor.execute("SELECT state, xact_start, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s", [pid])
            state, xact, blockers = cursor.fetchone()
            cursor.execute("SELECT count(*) FROM pg_locks WHERE pid=%s AND granted "
                           "AND locktype IN ('tuple','transactionid')", [pid])
            locks = cursor.fetchone()[0]
        self.assertEqual((xact, blockers, locks), (None, [], 0))
        print("B057_ACTUAL_NETWORK_NO_LOCKS", pid, state, flush=True)

    @contextmanager
    def wire_gate(self, stage):
        fixture_requirement(stage in {"before_create", "after_usage_choices"}, "有限wire gate")
        ready, release = Event(), Event()
        observed = {"pid": None, "hits": 0}
        def pause():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                observed["pid"] = cursor.fetchone()[0]
            observed["hits"] += 1; ready.set()
            if not release.wait(8):raise RuntimeError("B057 wire observation timeout")
        if stage == "before_create":
            original = translation._ClosedOfflineSDKClient.create
            def create(client, **kwargs):
                pause(); return original(client, **kwargs)
            target = patch.object(translation._ClosedOfflineSDKClient, "create", new=create)
        else:
            original = translation._ClosedOfflineSDKResponse.choices.fget
            def choices(response):
                pause(); return original(response)
            target = patch.object(translation._ClosedOfflineSDKResponse, "choices", new=property(choices))
        with target:
            try:yield ready, release, observed
            finally:release.set()

    @contextmanager
    def checkpoint_commit_gate(self, *, exit_after=False, worker_only=False):
        ready, release = Event(), Event()
        original = QuerySet.update
        observer_thread, run_id = get_ident(), self.envelope.run_id
        observed = {"hits": 0, "observer_thread": observer_thread}
        def after_commit():
            observed["hits"] += 1; observed["writer_thread"] = get_ident(); ready.set()
            if exit_after:raise CommittedFixtureExit("real checkpoint/progress committed")
            if not release.wait(8):raise RuntimeError("B057 checkpoint observation timeout")
        def update(queryset, **values):
            changed = original(queryset, **values)
            raw = values.get("raw_response")
            # E08 pauses its one worker, never the controller's negative fence writes.
            # The synchronous E10 committed-exit case keeps the creating thread as its owner.
            writer_is_target = get_ident() != observer_thread if worker_only else get_ident() == observer_thread
            if (writer_is_target and connection.in_atomic_block and changed == 1
                    and queryset.model is TranslationRun and type(raw) is dict
                    and type(raw.get(recovery.RESULT_KEY)) is dict
                    and raw[recovery.RESULT_KEY].get("run_id") == run_id
                    and type(raw.get(job.PROGRESS_KEY)) is dict
                    and raw[job.PROGRESS_KEY].get("state") == "checkpoint_saved"):
                transaction.on_commit(after_commit)
            return changed
        with patch.object(QuerySet, "update", new=update):
            try:yield ready, release, observed
            finally:release.set()

    def mutate_fence(self, kind):
        if kind == "grant":
            with self.case_scope():ro.revoke_read_grant(self.readroot.pk)
        elif kind == "deadline":self.clock.return_value = self.readroot.deadline_at
        elif kind == "source":NewsArticle.objects.filter(pk=self.article.pk).update(body_ja_normalized="changed source")
        elif kind == "source_pair":NewsArticle.objects.filter(pk=self.article.pk).update(source_article_id="changed-" + str(uuid4()))
        elif kind in {"workflow_version", "query_version", "result_version"}:
            QuerySet.update(ManagedReadonlyTaskBudget.objects.filter(pk=self.readroot.pk), **{kind:"unknown-v99"})
        elif kind == "permission_epoch":
            QuerySet.update(ManagedReadonlyTaskBudget.objects.filter(pk=self.readroot.pk), permission_epoch=F("permission_epoch") + 1)
        elif kind in {"claim_uuid", "schema_bool", "revision_float", "unknown_namespace", "null_plan"}:
            run = self.actual_run(); raw = deepcopy(run.raw_response)
            if kind == "claim_uuid":raw[recovery.CLAIM_KEY]["claim_execution_uuid"] = str(uuid4())
            elif kind == "schema_bool":raw[job.PLAN_KEY]["schema_version"] = True
            elif kind == "revision_float":raw[job.PROGRESS_KEY]["revision"] = float(raw[job.PROGRESS_KEY]["revision"])
            elif kind == "unknown_namespace":raw[job.PREFIX + "unknown_v99"] = {}
            else:raw[job.PLAN_KEY] = None
            TranslationRun.objects.filter(pk=run.pk).update(raw_response=raw)
        else:raise RuntimeError("unknown finite fence")

    @contextmanager
    def storage_fault(self, stage):
        allowed = {"plan", "read_reserve", "read_result", "model_attempt", "model_cas", "usage",
                   "checkpoint", "checkpoint_progress", "final_article", "final_run"}
        fixture_requirement(stage in allowed, "有限storage异常枚举")
        hits = []
        def fail():
            hits.append(stage)
            if stage in {"read_reserve", "model_attempt"}:raise IntegrityError("B057 storage " + stage)
            raise OperationalError("B057 storage " + stage)
        original_update, original_save = QuerySet.update, TranslationRun.save
        article_save, step_save, attempt_save = NewsArticle.save, ManagedReadonlyStep.save, TranslationRequestAttempt.save
        def update(queryset, **values):
            raw = values.get("raw_response", {})
            progress = raw.get(job.PROGRESS_KEY, {}) if type(raw) is dict else {}
            if ((stage == "read_result" and queryset.model is ManagedReadonlyStep and values.get("state") == "completed")
                    or (stage == "model_cas" and queryset.model is TranslationRun and progress.get("state") == "model_started")
                    or (stage == "usage" and queryset.model is TranslationRequestAttempt and "usage_report" in values)
                    or (stage == "checkpoint_progress" and queryset.model is TranslationRun and progress.get("state") == "checkpoint_saved")
                    or (stage == "final_run" and queryset.model is TranslationRun and values.get("status") == "success")):
                fail()
            return original_update(queryset, **values)
        def save_run(run, *args, **kwargs):
            if ((stage == "plan" and job.PLAN_KEY in run.raw_response)
                    or (stage == "checkpoint" and recovery.RESULT_KEY in run.raw_response
                        and run.raw_response[job.PROGRESS_KEY]["state"] == "model_started")):fail()
            return original_save(run, *args, **kwargs)
        def save_article(article, *args, **kwargs):
            if stage == "final_article" and article.translation_status == "translated":fail()
            return article_save(article, *args, **kwargs)
        def save_step(step, *args, **kwargs):
            if stage == "read_reserve":fail()
            return step_save(step, *args, **kwargs)
        def save_attempt(attempt, *args, **kwargs):
            if stage == "model_attempt":fail()
            return attempt_save(attempt, *args, **kwargs)
        with patch.object(QuerySet, "update", new=update), patch.object(TranslationRun, "save", new=save_run), \
                patch.object(NewsArticle, "save", new=save_article), patch.object(ManagedReadonlyStep, "save", new=save_step), \
                patch.object(TranslationRequestAttempt, "save", new=save_attempt):
            yield hits

    @contextmanager
    def parent_locked_workers(self, *, count=1, releases=(), fence=None):
        with ExitStack() as stack:
            with transaction.atomic():
                self.budget.__class__.objects.select_for_update().get(pk=self.budget.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    owner = cursor.fetchone()[0]
                state = stack.enter_context(self.running_workers(
                    lambda _: self.case_consume(), count=count, releases=releases))
                self.wait_lock_graph(state["pids"], owner)
                if fence == "grant":
                    # 主连接在parent→read顺序内提交真实grant撤销，worker正在实际PG排队。
                    root = ManagedReadonlyTaskBudget.objects.select_for_update().get(pk=self.readroot.pk)
                    QuerySet.update(ManagedReadonlyTaskBudget.objects.filter(pk=root.pk), state="revoked",
                                    permission_epoch=root.permission_epoch + 1, blocked_reason="grant_revoked")
                elif fence == "deadline":self.clock.return_value = self.readroot.deadline_at
                elif fence is not None:raise RuntimeError("unknown finite locked fence")
            yield state  # parent/read锁已真实commit释放；测试可继续观测winner外部wire。

    @contextmanager
    def running_workers_during_parent_lock(self, fence):
        with self.parent_locked_workers(fence=fence) as state:
            yield state

    @contextmanager
    def final_commit_gate(self):
        """真正final事务的Run CAS已执行、commit前暂停；不替代写入成功或行锁。"""
        ready, release = Event(), Event()
        observed = {"pid": None, "hits": 0}
        original = QuerySet.update
        def update(queryset, **values):
            changed = original(queryset, **values)
            if queryset.model is TranslationRun and values.get("status") == "success":
                fixture_requirement(connection.in_atomic_block and changed == 1, "真实final CAS事务前置")
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    observed["pid"] = cursor.fetchone()[0]
                observed["hits"] += 1; ready.set()
                if not release.wait(8):raise RuntimeError("B057 final commit gate timeout")
            return changed
        with patch.object(QuerySet, "update", new=update):
            try:yield ready, release, observed
            finally:release.set()
