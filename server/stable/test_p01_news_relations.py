"""T36：稿件关系交集及所有公开关联入口。"""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TransactionTestCase
from stable.models import TermEntry, HorseProfile, ArticleHorseLink, NewsPublicationReceipt, HorseFollow
from stable.services.news_publication import verified_relations
from stable.services.news_public_read import related_horse_entries
from stable.services.ingestion import upsert_article_from_draft
from stable.test_p01_news_workflow import WorkflowFixture, workflow_draft


class ReceiptRelationTests(WorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.a = HorseProfile.objects.create(primary_term=TermEntry.objects.create(source_ja="Horse A", term_type="horse"), original_name="Horse A", review_status="published")
        self.b = HorseProfile.objects.create(primary_term=TermEntry.objects.create(source_ja="Horse B", term_type="horse"), original_name="Horse B", review_status="published")
        ArticleHorseLink.objects.create(article=self.article, horse_profile=self.a, status="manual")

    def test_writer_freezes_only_current_occurrence_and_confirmed_link_intersection(self):
        occurrence = {"term_id": self.b.primary_term_id, "type": "horse", "block_id": "b0", "start": 0, "end": 7, "text": "Horse B"}
        self.run.entity_snapshot = {"occurrences": [occurrence]}
        self.run.editorial_snapshot = {}
        self.assertEqual(verified_relations(self.run)["horse_ids"], [])
        ArticleHorseLink.objects.create(article=self.article, horse_profile=self.b, status="candidate")
        self.assertEqual(verified_relations(self.run)["horse_ids"], [])
        ArticleHorseLink.objects.filter(article=self.article, horse_profile=self.b).update(status="manual")
        self.assertEqual(verified_relations(self.run)["horse_ids"], [self.b.pk])
        self.assertTrue(ArticleHorseLink.objects.filter(article=self.article, horse_profile=self.a, status="manual").exists())

    def test_readers_never_expand_anchor_links_to_all_receipts(self):
        # 发布 writer 的交集另测；此处冻结两个不同关系回执来攻击读取端。
        a_relations = {"horse_ids": [self.a.pk], "race_ids": [], "evidence": [], "gaps": []}
        b_relations = {"horse_ids": [self.b.pk], "race_ids": [], "evidence": [], "gaps": []}
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True), patch(
            "stable.services.news_publication.verified_relations", side_effect=[a_relations, b_relations]
        ):
            self.finish()
            first = NewsPublicationReceipt.objects.get(run=self.run)
            article = upsert_article_from_draft(workflow_draft("30")).article
            newer = self.finish(article.active_news_run)
            second = NewsPublicationReceipt.objects.get(run=newer)
        with self.settings(NEWS_QUALITY_FEED_ENABLED=True, ALLOWED_HOSTS=["testserver"]):
            from stable.views import _public_horse_article_entries
            from stable.services.horse_profiles import followed_articles
            self.assertEqual([row["article"].pk for row in _public_horse_article_entries(self.a)], [first.pk])
            self.assertEqual([row["article"].pk for row in _public_horse_article_entries(self.b)], [second.pk])
            HorseFollow.objects.create(token_hash="fixture-follow", horse_profile=self.a)
            self.assertEqual([row["article"].pk for row in followed_articles("fixture-follow")], [first.pk])
            response = self.client.get(second.public_path)
            self.assertContains(response, self.b.public_path)
            # 正文关联栏不能继承 A；相关稿件卡片可能合法列出首稿。
            self.assertEqual([link.horse_profile.pk for link in response.context["horse_links"]], [self.b.pk])
            NewsPublicationReceipt.objects.filter(pk=second.pk).update(visibility="withdrawn")
            self.assertEqual(related_horse_entries([self.b.pk]), [])
            self.assertEqual([row["article"].pk for row in related_horse_entries([self.a.pk])], [first.pk])

    def test_race_relation_requires_occurrence_at_identity_evidence_span(self):
        self.run.entity_snapshot = {"occurrences": [{"type": "race", "block_id": "b1", "start": 0, "end": 7, "text": "Other R"}]}
        self.run.editorial_snapshot = {"identity": {"fields": {"canonical_race_id": "99"},
            "evidence": {"canonical_race_id": {"block_id": "b0", "start": 0, "end": 7}}}}
        with patch("stable.services.news_publication.ArticleRaceLink.objects.filter", return_value=[]) as query:
            self.assertEqual(verified_relations(self.run)["race_ids"], [])
        query.assert_not_called()
