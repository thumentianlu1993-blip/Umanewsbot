"""T16/T17/T23：持久化认领、人工编辑隔离、未知请求恢复。"""
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from stable.models import NewsArticle, NewsStageAttempt
from stable.services.ingestion import upsert_article_from_draft
from stable.services.news_pipeline import start_revision, claim_stage, commit_stage, digest
from stable.test_france_news_freshness_change import draft_for


@override_settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY={"version": "test-v1"})
class StageClaimTests(TestCase):
    def setUp(self):
        self.article = upsert_article_from_draft(draft_for()).article
        self.run = start_revision(self.article)
        self.run.stage = "entity_check"
        self.run.save(update_fields=["stage"])

    def test_only_one_live_claim_and_generation_advances(self):
        attempt = claim_stage(self.run.pk, {"text": "fixture"})
        self.assertIsNotNone(attempt, "待处理阶段应获得持久化认领")
        self.assertIsNone(claim_stage(self.run.pk, {"text": "fixture"}))
        self.article.refresh_from_db()
        self.run.refresh_from_db()
        self.assertEqual(attempt.generation, self.article.news_generation)
        self.assertEqual(self.run.generation, attempt.generation)
        self.assertEqual(self.run.state, "running")
        self.assertGreater(self.run.lease_until, timezone.now())
        self.assertEqual(NewsStageAttempt.objects.count(), 1)

    @override_settings(NEWS_QUALITY_MODE="off")
    def test_off_never_claims_or_unbinds(self):
        self.assertIsNone(claim_stage(self.run.pk, {}))
        self.article.refresh_from_db()
        self.assertEqual(self.article.active_news_run_id, self.run.pk)

    def test_worker_result_after_manual_change_never_commits(self):
        attempt = claim_stage(self.run.pk, {"text": "fixture"})
        self.assertIsNotNone(attempt)
        NewsArticle.objects.filter(pk=self.article.pk).update(editor_notes="new note", body_zh="人工稿")
        NewsStageAttempt.objects.filter(pk=attempt.pk).update(state="completed", result={"entities": []}, output_sha=digest({"entities": []}))
        self.assertFalse(commit_stage(attempt.pk, attempt.generation))
        self.run.refresh_from_db()
        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "人工稿")
        self.assertEqual(self.run.state, "stale")
        self.assertEqual(self.run.entity_snapshot, {})

    def test_superseded_revision_never_applies_old_result(self):
        attempt = claim_stage(self.run.pk, {"text": "fixture"})
        self.assertIsNotNone(attempt)
        newer = start_revision(self.article, snapshot={**self.run.source_snapshot, "body": "new body"})
        NewsStageAttempt.objects.filter(pk=attempt.pk).update(state="completed", result={"entities": []}, output_sha=digest({"entities": []}))
        self.assertFalse(commit_stage(attempt.pk, attempt.generation))
        newer.refresh_from_db()
        self.assertEqual(newer.entity_snapshot, {})
