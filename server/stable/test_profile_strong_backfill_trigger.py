"""C241链路oracle：真实提交/真实writer，合成server作用域非生产许可。未运行。"""
import copy
import hashlib
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from celery.exceptions import Retry
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, ProgrammingError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerError

from stable import tasks, test_horse_article_binding_persistence as fixture_data
from stable.models import ArticleHorseLink, HorseExternalIdentity, HorseProfile, NewsArticle, OperationLog, TaskExecutionLog, TermEntry
from stable.services import horse_profiles, queueing
from stable.services.horse_article_strong_backfill import enqueue_profile_strong_backfill
from stable.test_article_entity_binding import LITERAL
from stable.views import _public_horse_article_entries, _public_published_articles


TASK_NAME = "horse_strong_article_backfill"


class ProfileStrongBackfillTriggerTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires isolated PostgreSQL")
        self.actor = get_user_model().objects.create_user(username="c241-publisher", is_staff=True)
        self.other = get_user_model().objects.create_user(username="c241-other", is_staff=True)
        # Actual historical article is created before the later profile.
        self.article = NewsArticle.objects.create(source_site="tdn", source_mode="latest", source_article_id="c241-old",
            source_url="https://example.invalid/c241", title_ja="", body_ja_raw="Aurora won.", source_language="en",
            published_at=timezone.now()-timedelta(days=2), workflow_status="published",
            published_to_web_at=timezone.now()-timedelta(days=2))
        term = TermEntry.objects.create(term_type="horse", source_ja="Aurora", target_zh="极光", source_language="en")
        self.horse = HorseProfile.objects.create(primary_term=term, original_name="Aurora", review_status="draft")
        self.identity_bytes = fixture_data.raw(dict(source="the_racing_api", namespace="horse", external_id="hrs_241",
                                                   horse_profile_id=self.horse.pk))
        self.identity = HorseExternalIdentity.objects.create(horse_profile=self.horse, source="the_racing_api",
            namespace="horse", external_id="hrs_241", status="verified", evidence_url="https://example.invalid/identity/241",
            payload_sha256=hashlib.sha256(self.identity_bytes).hexdigest(), verified_at=timezone.now(), verified_by=self.actor)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = {}
        self.sequence = 0
        ctx = override_settings(CELERY_TASK_ALWAYS_EAGER=True, HORSE_ARTICLE_BINDING_HANDLES=self.registry)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.client.force_login(self.actor)

    def install_current_fixture_handle(self, *, actor_ids=None):
        # Only reuse the accepted data builder; no imported TestCase alias or
        # inherited old 17 test methods. Consumer never edits these bytes.
        self.horse.refresh_from_db()
        pack = fixture_data.HorseArticleBindingPersistenceTests.make_bundle(self)
        self.sequence += 1
        path = Path(self.temp.name) / ("synthetic-producer-"+str(self.sequence)+".json")
        path.write_bytes(fixture_data.raw(pack))
        path.chmod(0o600)
        scope = dict(bundle_path=str(path), bundle_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            producer_namespace="synthetic-server", request_id="c235-one", article_id=self.article.pk,
            profile_id=self.horse.pk, identity_id=self.identity.pk, actor_ids=actor_ids or [self.actor.pk],
            not_before=(timezone.now()-timedelta(days=1)).isoformat(), expires_at=(timezone.now()+timedelta(days=1)).isoformat(),
            revoked=False, contract_refs=[copy.deepcopy(LITERAL["article_input"]["snapshot"]["evidence"][0]["contract_ref"])],
            responsibility=dict(identity_producer="isolated-fixture", relationship_owner="isolated-fixture",
                                write_owner="explicit-test-domain"))
        self.registry["c241-current"] = scope
        return path

    def publish_POST(self):
        response = self.client.post(reverse("console-horse-profile-status", args=[self.horse.pk]), {"status": "published"})
        self.assertEqual(response.status_code, 302)
        self.horse.refresh_from_db()
        self.assertEqual(self.horse.review_status, "published")

    def receipts(self):
        return list(OperationLog.objects.filter(action_type="horse_binding_committed", target_type="horse_binding_request"))

    def assert_link_and_readers(self):
        link = ArticleHorseLink.objects.get(article=self.article, horse_profile=self.horse)
        self.assertEqual(link.status, "auto")
        self.assertEqual(link.source, "strong_identity.v1")
        self.assertEqual(len(self.receipts()), 1)
        self.assertEqual([x.pk for x in _public_published_articles().get(pk=self.article.pk).public_horse_links], [link.pk])
        self.assertEqual([x["article"].pk for x in _public_horse_article_entries(self.horse)], [self.article.pk])
        return link

    def test_outermost_commit_POST_then_real_writer_and_readers(self):
        with patch.object(queueing, "dispatch_task", wraps=queueing.dispatch_task) as observed:
            with transaction.atomic():
                self.publish_POST()
                self.install_current_fixture_handle()
                self.assertFalse(ArticleHorseLink.objects.filter(horse_profile=self.horse).exists())
                self.assertEqual(observed.call_count, 0)
            self.assertEqual(observed.call_count, 1)
        self.assert_link_and_readers()

    def test_outer_rollback_discards_callback_status_and_audit(self):
        with patch.object(queueing, "dispatch_task", wraps=queueing.dispatch_task) as observed:
            with self.assertRaisesRegex(RuntimeError, "outer rollback"):
                with transaction.atomic():
                    self.publish_POST()
                    self.install_current_fixture_handle()
                    raise RuntimeError("outer rollback")
            self.assertEqual(observed.call_count, 0)
        self.horse.refresh_from_db()
        self.assertEqual(self.horse.review_status, "draft")
        self.assertIsNone(self.horse.published_at)
        self.assertFalse(OperationLog.objects.filter(action_type="horse_profile_status_changed", target_id=str(self.horse.pk)).exists())
        self.assertFalse(ArticleHorseLink.objects.exists())

    def test_repeat_publish_keeps_old_time_semantics_without_new_first_callback(self):
        with patch.object(queueing, "dispatch_task", wraps=queueing.dispatch_task) as observed:
            with transaction.atomic():
                self.publish_POST()
                self.install_current_fixture_handle()
            link = self.assert_link_and_readers()
            first_time = self.horse.published_at
            self.publish_POST()
            self.assertGreaterEqual(self.horse.published_at, first_time)
            self.assertEqual(observed.call_count, 1)
        self.assertEqual(ArticleHorseLink.objects.get(pk=link.pk).pk, link.pk)
        self.assertEqual(len(self.receipts()), 1)

    def test_empty_and_wrong_actor_scope_never_dispatch_weak_scanner(self):
        with patch.object(queueing, "dispatch_task", wraps=queueing.dispatch_task) as observed:
            self.publish_POST()
            self.assertEqual(observed.call_count, 0)
            self.install_current_fixture_handle(actor_ids=[self.other.pk])
            result = enqueue_profile_strong_backfill(self.horse.pk, self.actor.pk)
            self.assertEqual(result["status"], "no_eligible_handles")
            self.assertEqual(observed.call_count, 0)
        self.assertFalse(ArticleHorseLink.objects.exists())
        self.assertEqual(self.receipts(), [])

    def test_worker_checks_current_hidden_profile_before_real_writer(self):
        self.publish_POST()
        self.install_current_fixture_handle()
        horse_profiles.transition_review_status(self.horse, "hidden", user=self.actor)
        result = tasks.backfill_profile_strong_article_links_task.run(self.horse.pk, self.actor.pk)
        self.assertEqual(result["status"], "not_public")
        self.assertFalse(ArticleHorseLink.objects.exists())

    def test_draft_artifact_stale_then_new_producer_handle_explicit_replay(self):
        old_path = self.install_current_fixture_handle()
        old_bytes = old_path.read_bytes()
        self.publish_POST()
        self.assertFalse(ArticleHorseLink.objects.exists())
        attempt = TaskExecutionLog.objects.filter(task_name=TASK_NAME).latest("pk")
        self.assertEqual(attempt.payload["result"]["counts"], {"stale_first_apply": 1})
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.install_current_fixture_handle()
        self.assertEqual(old_path.read_bytes(), old_bytes)
        first = enqueue_profile_strong_backfill(self.horse.pk, self.actor.pk)
        self.assertEqual(first["status"], "executed_direct")
        self.assertEqual(first["execution"]["counts"], {"created": 1})
        self.assert_link_and_readers()
        before = list(OperationLog.objects.order_by("pk").values())
        repeated = enqueue_profile_strong_backfill(self.horse.pk, self.actor.pk)
        self.assertEqual(repeated["execution"]["counts"], {"replayed": 1})
        self.assertEqual(list(OperationLog.objects.order_by("pk").values()), before)

    def test_status_audit_constraint_failure_rolls_back_status_and_callback(self):
        def fail_status_audit(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "stable_operationlog"') and "horse_profile_status_changed" in params:
                return execute('INSERT INTO "stable_operationlog" ("action_type") VALUES (NULL)', None, False, context)
            return execute(sql, params, many, context)
        with patch.object(queueing, "dispatch_task", wraps=queueing.dispatch_task) as observed:
            with connection.execute_wrapper(fail_status_audit):
                with self.assertRaises(IntegrityError):
                    horse_profiles.transition_review_status(self.horse, "published", user=self.actor)
            self.assertEqual(observed.call_count, 0)
        self.horse.refresh_from_db()
        self.assertEqual(self.horse.review_status, "draft")
        self.assertIsNone(self.horse.published_at)
        self.assertFalse(ArticleHorseLink.objects.exists())

    def test_same_input_object_return_and_no_actor_no_first_dispatch(self):
        result = horse_profiles.transition_review_status(self.horse, "ready", user=self.actor, note="prepare")
        self.assertIs(result, self.horse)
        self.assertEqual(self.horse.review_status, "ready")
        self.assertEqual(self.horse.review_notes, "prepare")
        self.install_current_fixture_handle()
        with patch.object(queueing, "dispatch_task", wraps=queueing.dispatch_task) as observed:
            result = horse_profiles.transition_review_status(self.horse, "published", user=None)
            self.assertIs(result, self.horse)
            self.assertIsNone(self.horse.published_by)
            self.assertEqual(observed.call_count, 0)
        self.assertFalse(ArticleHorseLink.objects.exists())

    def test_broker_failure_uses_existing_direct_fallback_real_writer(self):
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False):
            with patch.object(tasks.backfill_profile_strong_article_links_task, "delay", side_effect=BrokerError("isolated transport failure")) as send:
                with transaction.atomic():
                    self.publish_POST()
                    self.install_current_fixture_handle()
                self.assertEqual(send.call_count, 1)
        self.assert_link_and_readers()

    def test_dispatch_failure_keeps_committed_publication_and_explicit_recovery(self):
        def fail_link(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "stable_articlehorselink"'):
                return execute('SELECT * FROM "c241_deliberately_missing_relation"', None, False, context)
            return execute(sql, params, many, context)
        with self.assertLogs("stable", level="ERROR"):
            with connection.execute_wrapper(fail_link):
                with transaction.atomic():
                    self.publish_POST()
                    self.install_current_fixture_handle()
        self.horse.refresh_from_db()
        self.assertEqual(self.horse.review_status, "published")
        self.assertFalse(ArticleHorseLink.objects.exists())
        self.assertTrue(TaskExecutionLog.objects.filter(task_name=TASK_NAME, status="failed").exists())
        self.assertTrue(TaskExecutionLog.objects.filter(task_name="horse_strong_backfill_dispatch", status="failed").exists())
        recovered = enqueue_profile_strong_backfill(self.horse.pk, self.actor.pk)
        self.assertEqual(recovered["execution"]["counts"], {"created": 1})
        self.assert_link_and_readers()

    def test_queued_retry_2_5_and_exhaustion_preserves_actual_SQL_exception(self):
        self.publish_POST()
        self.install_current_fixture_handle()
        task = tasks.backfill_profile_strong_article_links_task
        failures = []
        def timeout_insert(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "stable_articlehorselink"'):
                execute("SET LOCAL statement_timeout = '1ms'", None, False, context)
                try:
                    return execute("SELECT pg_sleep(0.02)", None, False, context)
                except OperationalError as exc:
                    failures.append(exc)
                    raise
            return execute(sql, params, many, context)
        for retries, delay in [(0, 2), (1, 5), (2, None)]:
            with self.subTest(retries=retries):
                task.push_request(called_directly=False, is_eager=False, retries=retries,
                                  args=(self.horse.pk, self.actor.pk), kwargs={}, id="isolated-c241")
                try:
                    with override_settings(CELERY_TASK_ALWAYS_EAGER=False):
                        # Observe transport scheduling only, not authorization,
                        # core or ORM success. No broker/durable claim.
                        with patch.object(task, "apply_async", return_value=None) as transport:
                            with self.assertLogs("stable", level="ERROR"):
                                with connection.execute_wrapper(timeout_insert):
                                    with self.assertRaises(OperationalError if delay is None else Retry) as raised:
                                        task.run(self.horse.pk, self.actor.pk)
                            if delay is None:
                                self.assertIs(raised.exception, failures[-1])
                                self.assertEqual(transport.call_count, 0)
                            else:
                                self.assertIs(raised.exception.exc, failures[-1])
                                self.assertEqual(transport.call_count, 1)
                                self.assertEqual(transport.call_args.kwargs["countdown"], delay)
                finally:
                    task.pop_request()
                self.assertFalse(ArticleHorseLink.objects.exists())
                self.assertEqual(self.receipts(), [])
