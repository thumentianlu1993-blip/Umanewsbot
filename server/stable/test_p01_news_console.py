"""T26/T28/T29：人工修订、审核恢复和逐稿撤回的后台边界。"""
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from stable.models import NewsPublicationReceipt, NewsProcessingRun, NewsStageAttempt
from stable.services.ingestion import upsert_article_from_draft
from stable.services.news_pipeline import submit_manual_target
from stable.test_p01_news_workflow import WorkflowFixture, workflow_draft


class QualityConsoleTests(WorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser("quality-editor", "fixture@example.invalid", "fixture")
        self.client.force_login(self.user)

    def publish_pair(self):
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            self.finish()
            first = NewsPublicationReceipt.objects.get(run=self.run)
            article = upsert_article_from_draft(workflow_draft("30")).article
            second = NewsPublicationReceipt.objects.get(run=self.finish(article.active_news_run))
        return first, second

    def test_quality_queue_shows_pending_run_and_source_with_staff_only(self):
        response = self.client.get("/admin/news-quality/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.run.source_snapshot["title"])
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        self.assertEqual(self.client.get("/admin/news-quality/").status_code, 403)

    def test_editor_reads_current_manual_revision_without_modifying_anchor(self):
        manual = {"title_zh": "待审的新标题", "body_zh": "待审的人工正文27", "summary_zh": "待审摘要"}
        run = submit_manual_target(self.article, manual, editor=self.user)
        before = type(self.article).objects.values().get(pk=self.article.pk)
        response = self.client.get(reverse("console-article-editor", args=[self.article.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, manual["body_zh"])
        after = type(self.article).objects.values().get(pk=self.article.pk)
        self.assertEqual(before, after)

    def test_withdraw_one_receipt_does_not_withdraw_other_story(self):
        first, second = self.publish_pair()
        response = self.client.post(f"/admin/news-quality/receipts/{first.pk}/withdraw/", {"reason": "原稿事实错误"})
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.visibility, "withdrawn")
        self.assertEqual(second.visibility, "public")
        self.assertEqual(first.visibility_evidence["user_id"], self.user.pk)
        self.assertEqual(self.client.get(second.public_path).status_code, 200)

    def test_whole_source_withdraw_requires_exact_visible_receipt_set(self):
        first, second = self.publish_pair()
        response = self.client.post(f"/admin/news-quality/runs/{second.run_id}/action/", {
            "action": "withdraw_source", "reason": "整来源撤回", "receipt_ids": str(first.pk)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(NewsPublicationReceipt.objects.filter(visibility="public").count(), 2)

    def test_retry_unknown_provider_result_is_refused(self):
        NewsProcessingRun.objects.filter(pk=self.run.pk).update(state="review", reason="provider_unknown")
        NewsStageAttempt.objects.create(run=self.run, stage="entity_check", seq=1,
            generation=self.run.generation, input_sha="a"*64, state="unknown")
        response = self.client.post(f"/admin/news-quality/runs/{self.run.pk}/action/", {"action": "retry", "reason": "再试"})
        self.assertEqual(response.status_code, 409)
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "review")

    def test_manual_event_binding_is_audited_new_run_and_overflow_can_resume(self):
        first, second = self.publish_pair()
        article = upsert_article_from_draft(workflow_draft("31")).article
        run = article.active_news_run
        NewsProcessingRun.objects.filter(pk=run.pk).update(state="review", reason="recall_overflow")
        response = self.client.post(f"/admin/news-quality/runs/{run.pk}/action/", {
            "action": "bind_event", "event_id": str(first.event_id), "receipt_id": str(first.pk),
            "reason": "已核对为同一公告，第一稿为更正对象"})
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertNotEqual(article.active_news_run_id, run.pk)
        new = article.active_news_run
        self.assertEqual(new.editor_provenance["event_binding"]["event_id"], str(first.event_id))
        self.assertEqual(new.editor_provenance["user_id"], self.user.pk)

    def test_candidate_entry_routes_to_current_quality_run(self):
        response = self.client.get(reverse("console-candidate-detail", args=[self.article.pk]))
        self.assertRedirects(response, reverse("console-news-quality-detail", args=[self.run.pk]))

    def test_headline_invalidation_uses_selected_receipt_and_clears_binding(self):
        from stable.models import HomepageHeadlineSelection
        from stable.services.editorial_headlines import invalidate_headline_state_for_article
        first, second = self.publish_pair()
        selection = HomepageHeadlineSelection.objects.create(slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
            article=self.article, receipt=second, selected_by=self.user)
        self.assertEqual(invalidate_headline_state_for_article(self.article.pk), 0)
        NewsPublicationReceipt.objects.filter(pk=second.pk).update(visibility="withdrawn")
        self.assertEqual(invalidate_headline_state_for_article(self.article.pk), 1)
        selection.refresh_from_db()
        self.assertIsNone(selection.article_id)
        self.assertIsNone(selection.receipt_id)
