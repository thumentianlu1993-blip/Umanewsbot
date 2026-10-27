"""T10：实质更正绑定准确旧稿，而非随最新稿漂移。"""
import json
from copy import deepcopy
from django.test import TransactionTestCase
from stable.models import NewsPublicationReceipt
from stable.services.ingestion import upsert_article_from_draft
from stable.test_p01_news_workflow import WorkflowFixture, workflow_draft


class CorrectionTests(WorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.correction = None
        self.verify_correction = True

    def fake_response(self, attempt, payload):
        response = super().fake_response(attempt, payload)
        data = json.loads(response.choices[0].message.content)
        if self.correction and attempt.stage == "event_classify":
            fact = data["facts"][0]
            fact.update(relation="correction", prior_fact_ids=[self.correction["fact_id"]],
                correction={key: value for key, value in self.correction.items() if key != "fact_id"})
        if self.correction and attempt.stage == "fact_audit":
            data["corrections"] = [{"receipt_id": self.correction["receipt_id"],
                "old_body_span": self.correction["old_body_span"], "substantive": self.verify_correction,
                "supported": self.verify_correction}]
        response.choices[0].message.content = json.dumps(data)
        return response

    def story(self, value):
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            article = upsert_article_from_draft(workflow_draft(value)).article
            run = self.finish(article.active_news_run)
        return run

    def target(self, receipt):
        self.correction = {"receipt_id": str(receipt.pk), "fact_id": receipt.evidence["editorial"]["facts"][0]["id"],
            "old_body_span": {"start": 0, "end": len(receipt.content["body"])},
            "old_text": receipt.content["body"]}

    def test_correction_targets_original_even_after_intervening_story(self):
        first_run = self.story("27")
        self.assertEqual(first_run.state, "published", first_run.reason)
        first = NewsPublicationReceipt.objects.get(run=first_run)
        self.assertEqual(self.story("30").state, "published")
        self.target(first)
        run = self.story("31")
        self.assertEqual(run.state, "published", run.reason)
        correction = NewsPublicationReceipt.objects.get(run=run)
        self.assertEqual(correction.kind, "correction_story")
        self.assertEqual(correction.previous_receipt_id, first.pk)
        first.refresh_from_db()
        self.assertIn("27", first.content["body"])

    def test_missing_exact_target_or_unverified_substantive_correction_is_held(self):
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        self.target(first)
        self.verify_correction = False
        run = self.story("31")
        self.assertEqual(run.state, "review")
        self.assertIn("correction", run.reason)
        self.assertEqual(NewsPublicationReceipt.objects.count(), 1)

    def test_altered_old_text_cannot_claim_to_correct_another_passage(self):
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        self.target(first)
        self.correction["old_text"] = "并不存在的旧稿内容"
        run = self.story("31")
        self.assertEqual(run.state, "review")
        self.assertIn("correction", run.reason)

    def test_cross_source_matching_document_is_recalled_before_classification(self):
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        draft = workflow_draft("31")
        draft.source_article_id = "another-source-document"
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            run = self.finish(upsert_article_from_draft(draft).article.active_news_run)
        self.assertEqual(run.state, "published", run.reason)
        payload = run.attempts.filter(stage="event_classify").first().usage["input"]
        self.assertIn(str(first.event_id), [row["id"] for row in payload["candidates"]])

    def test_same_correction_after_later_story_is_not_published_twice(self):
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        self.target(first)
        self.assertEqual(self.story("31").state, "published")
        self.correction = None
        self.assertEqual(self.story("50").state, "published")
        self.target(first)
        repeat = self.story("31")
        self.assertEqual(repeat.state, "duplicate", repeat.reason)
        self.assertEqual(NewsPublicationReceipt.objects.filter(kind="correction_story").count(), 1)

    def test_correction_removes_old_priority_without_hiding_original(self):
        from stable.services.news_feed import create_snapshot, visible_entries
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        self.target(first)
        run = self.story("31")
        self.assertEqual(run.state, "published", run.reason)
        snap = create_snapshot()
        self.assertNotIn(first.public_entry.pk, snap.ordered_entry_ids)
        self.assertTrue(visible_entries().filter(receipt=first).exists())

    def test_same_correction_with_different_valid_quote_is_duplicate(self):
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        self.target(first)
        self.assertEqual(self.story("31").state, "published")
        self.correction = None
        self.assertEqual(self.story("50").state, "published")
        self.target(first)
        old = first.content["body"]
        start = old.index("27")
        self.correction.update(old_body_span={"start": start, "end": start + 2}, old_text="27")
        self.assertEqual(self.story("31").state, "duplicate")
        self.assertEqual(NewsPublicationReceipt.objects.filter(kind="correction_story").count(), 1)

    def test_mixed_old_and_new_corrections_only_admit_new_fact(self):
        from stable.services.news_editorial import unpublished_corrections, fact_key
        first = NewsPublicationReceipt.objects.get(run=self.story("27"))
        self.target(first)
        run = self.story("31")
        prior = NewsPublicationReceipt.objects.get(run=run).evidence["editorial"]["facts"][0]
        newer = deepcopy(prior)
        newer["object"] = "32"
        newer["id"] = fact_key(newer)
        self.assertEqual(unpublished_corrections(run.event, [prior, newer]), [newer])
