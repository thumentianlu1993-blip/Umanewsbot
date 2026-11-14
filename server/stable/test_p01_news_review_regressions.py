"""独立代码review回归：在途人工接管、模型坏形状、真实配置和短发布锁。"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from stable.models import NewsArticle, NewsProcessingRun, NewsPublicationReceipt, NewsStageAttempt, OperationLog
from stable.services import news_pipeline
from stable.services.ingestion import upsert_article_from_draft
from stable.services.news_content import ContentBlocked, validate_entities
from stable.services.news_review import review_action
from stable.test_p01_news_content import CLEAN, ENTITY
from stable.test_p01_news_workflow import WorkflowFixture, workflow_draft


class ReviewRegressionTests(WorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser("review-fix", "fixture@example.invalid", "fixture")
        self.response_mode = ""

    def fake_response(self, attempt, payload):
        response = super().fake_response(attempt, payload)
        data = json.loads(response.choices[0].message.content)
        if self.response_mode == "bad_entity" and attempt.stage == "entity_check":
            data["entities"][0]["block_id"] = []
        if self.response_mode == "long_reject" and attempt.stage == "event_classify":
            data.update(priority="reject", reason="未入选原因" * 180)
        response.choices[0].message.content = json.dumps(data)
        return response

    def test_off_with_empty_boundary_keeps_legacy_ingestion_working(self):
        draft = workflow_draft()
        draft.source_article_id = "off-with-null"
        with self.settings(NEWS_QUALITY_MODE="off", NEWS_QUALITY_POLICY={"activated_at": None}):
            article = upsert_article_from_draft(draft).article
            self.assertIsNone(article.active_news_run_id)
            self.assertFalse(news_pipeline.source_eligible(self.run))

    def test_manual_hold_and_reject_survive_late_provider_outcomes(self):
        from stable.services.news_model_gateway import RequestDenied
        for action in ("hold", "reject"):
            for outcome in ("failed", "unknown", "denied"):
                with self.subTest(action=action, outcome=outcome):
                    draft = workflow_draft()
                    draft.source_article_id = f"{action}-{outcome}"
                    run = upsert_article_from_draft(draft).article.active_news_run
                    news_pipeline.process_news_run(run.pk)
                    before_generation = NewsProcessingRun.objects.get(pk=run.pk).generation
                    def late(attempt_id, payload):
                        review_action(run.pk, action=action, user=self.user, reason="人工停止")
                        if outcome == "denied":
                            raise RequestDenied("source_changed")
                        return SimpleNamespace(state=outcome, error="rate_limited")
                    with patch("stable.services.news_model_gateway.execute_request", side_effect=late):
                        news_pipeline.process_news_run(run.pk)
                    run.refresh_from_db()
                    self.assertEqual(run.state, "review" if action == "hold" else "rejected")
                    self.assertEqual(run.reason, "人工停止")
                    self.assertGreater(run.generation, before_generation + 1)

    def test_manual_hold_survives_late_successful_receipt(self):
        news_pipeline.process_news_run(self.run.pk)
        real_response = self.fake_response
        def hold_during_network(attempt, payload):
            review_action(self.run.pk, action="hold", user=self.user, reason="先核原文")
            return real_response(attempt, payload)
        with patch("stable.services.news_model_gateway._single_request", side_effect=hold_during_network):
            news_pipeline.process_news_run(self.run.pk)
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "review")
        self.assertEqual(self.run.reason, "先核原文")
        self.assertEqual(self.run.stage, "event_classify")
        attempt = self.run.attempts.get()
        self.assertEqual(attempt.state, "completed")
        self.assertEqual(attempt.settlement_version, 1)

    def test_payload_cannot_be_claimed_after_stage_advanced(self):
        news_pipeline.process_news_run(self.run.pk)
        original = news_pipeline.stage_payload
        def advanced(run):
            payload = original(run)
            NewsProcessingRun.objects.filter(pk=run.pk).update(stage="entity_check")
            return payload
        with patch("stable.services.news_pipeline.stage_payload", side_effect=advanced), patch(
                "stable.services.news_model_gateway.execute_request") as provider:
            news_pipeline.process_news_run(self.run.pk)
        provider.assert_not_called()
        self.assertFalse(self.run.attempts.exists())

    def test_invalid_entity_field_types_are_content_rejections(self):
        for key, value in (("block_id", []), ("type", {}), ("start", True), ("text", [])):
            with self.subTest(key=key), self.assertRaises(ContentBlocked):
                validate_entities(CLEAN, {"coverage": "complete", "entities": [{**ENTITY, key: value}]})

    def test_bad_model_schema_settles_cost_once_and_moves_to_review(self):
        self.response_mode = "bad_entity"
        run = self.finish()
        self.assertEqual(run.state, "review")
        self.assertFalse(run.attempts.filter(state__in=["reserved", "inflight", "unknown"]).exists())
        self.assertEqual(run.attempts.filter(stage="entity_check", state="completed").count(), 1)
        self.assertEqual(self.calls.count("entity_check"), 1)

    def test_one_bad_recovery_does_not_stop_pending_dispatch(self):
        draft = workflow_draft()
        draft.source_article_id = "next-dispatch"
        pending = upsert_article_from_draft(draft).article.active_news_run
        NewsProcessingRun.objects.filter(pk=self.run.pk).update(state="running", lease_until=timezone.now()-timedelta(seconds=1))
        with self.settings(NEWS_QUALITY_DISPATCH_ENABLED=True), patch(
                "stable.services.news_pipeline.recover_expired_run", side_effect=ValueError("bad saved schema")), patch(
                "stable.services.news_pipeline.enqueue_news_run", return_value=True) as send:
            report = news_pipeline.scan_news_runs()
        self.assertIn(pending.pk, [call.args[0] for call in send.call_args_list])
        self.assertEqual(report["recovery_errors"], 1)

    def test_long_manual_reason_preserves_full_audit_and_bounded_state(self):
        reason = "完整人工审核原因" * 100
        review_action(self.run.pk, action="hold", user=self.user, reason=reason)
        self.run.refresh_from_db()
        self.assertLessEqual(len(self.run.reason), 255)
        self.assertEqual(OperationLog.objects.get(action_type="news_quality_hold").detail, reason)

    def test_long_editorial_reason_preserves_model_evidence(self):
        self.response_mode = "long_reject"
        run = self.finish()
        self.assertEqual(run.state, "rejected")
        self.assertLessEqual(len(run.reason), 255)
        self.assertEqual(run.editorial_snapshot["reason"], "未入选原因" * 180)

    def test_real_region_limit_strings_allow_first_and_hold_second(self):
        for raw in ('france:1,hong_kong:5', '{"france": 1, "hong_kong": 5}'):
            with self.subTest(raw=raw), self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True,
                    MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=raw):
                run = self.finish()
                self.assertEqual(run.state, "published", run.reason)
                draft = workflow_draft("30")
                next_run = self.finish(upsert_article_from_draft(draft).article.active_news_run)
                self.assertEqual(next_run.state, "ready")
                self.assertEqual(next_run.reason, "publication_capacity")
                self.assertEqual(NewsPublicationReceipt.objects.count(), 1)

    def test_classification_payload_contains_complete_identity_contract(self):
        news_pipeline.process_news_run(self.run.pk)
        self.run.refresh_from_db()
        payload = json.dumps(news_pipeline.stage_payload(self.run), ensure_ascii=False)
        for field in ("canonical_race_id", "source_race_id", "organizer", "venue", "local_date", "race_number",
                      "subject_ref", "episode_ref", "organization", "jurisdiction", "document_id", "effective_date", "scope",
                      "horse:", "date:", "announcement:"):
            self.assertIn(field, payload)

    def test_ingestion_network_never_holds_publication_lock(self):
        from stable.services.news_feed import PUBLICATION_LOCK
        def try_lock():
            try:
                with transaction.atomic(), connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [PUBLICATION_LOCK])
                    return cursor.fetchone()[0]
            finally:
                connections.close_all()
        def download(url):
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(try_lock).result(timeout=5), "采集网络期间不得占用全站发布锁")
            return "fixture/image.jpg"
        draft = workflow_draft()
        draft.source_article_id = "image-lock-check"
        draft.images = [SimpleNamespace(original_url="https://fixture.invalid/image.jpg", caption_ja="", sort_order=0)]
        with self.settings(NEWS_QUALITY_MODE="off", NEWS_QUALITY_INDEX_ENABLED=True), patch(
                "stable.services.ingestion.download_image", side_effect=download):
            article = upsert_article_from_draft(draft).article
        self.assertTrue(article.images.get().local_path, "下载失败不能吞掉发布锁断言")
