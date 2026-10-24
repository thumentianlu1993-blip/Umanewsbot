"""关注新闻的limit约束去重文章数；合成fixture仅用于隔离ORM回归。"""
from datetime import datetime, timedelta, timezone

from django.db import connection
from django.test import TestCase

from stable.models import (
    ArticleHorseLink, ArticleHorseLinkStatus, ArticleTranslationStatus,
    HorseProfile, HorseProfileStatus, NewsArticle, RacingRegion,
    SourceLanguage, SourceMode, SourceSite, TermEntry, TermType, WorkflowStatus,
)
from stable.services.horse_profiles import (
    follow_horse, followed_articles, signed_follow_token, token_hash_from_cookie,
)


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FollowedArticleUniqueLimitTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            raise RuntimeError("isolated PostgreSQL test runner required; no skip or SQLite fallback")
        super().setUpClass()

    def setUp(self):
        self.token_hash = token_hash_from_cookie(signed_follow_token())
        self.first_horse = self.profile("one")
        self.second_horse = self.profile("two")
        follow_horse(self.token_hash, self.first_horse, include_descendants=False)
        follow_horse(self.token_hash, self.second_horse, include_descendants=False)

    def profile(self, key):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE, source_language=SourceLanguage.ENGLISH,
            source_ja="C222 Horse " + key, target_zh="合成马" + key,
            racing_region=RacingRegion.UNITED_STATES,
        )
        return HorseProfile.objects.create(
            primary_term=term, original_name=term.source_ja, english_name=term.source_ja,
            display_name_zh=term.target_zh, racing_region=RacingRegion.UNITED_STATES,
            review_status=HorseProfileStatus.PUBLISHED, published_at=BASE,
        )

    def article(self, key, offset, *, status=WorkflowStatus.PUBLISHED, web=True):
        published = BASE + timedelta(seconds=offset)
        return NewsArticle.objects.create(
            source_site=SourceSite.TDN, source_mode=SourceMode.LATEST,
            source_article_id="c222-" + key, source_url="https://example.invalid/c222/" + key,
            source_language=SourceLanguage.ENGLISH, racing_region=RacingRegion.UNITED_STATES,
            title_ja="Synthetic article " + key, body_ja_raw="Synthetic article body.",
            body_ja_normalized="Synthetic article body.", title_zh="合成新闻" + key,
            body_zh="仅用于隔离关系读取回归的合成正文。",
            translation_status=ArticleTranslationStatus.TRANSLATED, workflow_status=status,
            published_at=published, published_to_web_at=published if web else None,
        )

    def link(self, article, horse, status=ArticleHorseLinkStatus.AUTO):
        return ArticleHorseLink.objects.create(
            article=article, horse_profile=horse, status=status,
            confidence=90, source="c222-isolated-fixture",
        )

    def duplicate_fixture(self):
        newer = self.article("newer", 20)
        older = self.article("older", 10)
        self.link(newer, self.first_horse)
        self.link(newer, self.second_horse, ArticleHorseLinkStatus.MANUAL)
        self.link(older, self.first_horse)
        return newer, older

    def ids(self, limit):
        return [entry["article"].pk for entry in followed_articles(self.token_hash, limit=limit)]

    def test_limit_counts_unique_articles_instead_of_relationship_rows(self):
        newer, older = self.duplicate_fixture()
        entries = followed_articles(self.token_hash, limit=2)
        self.assertEqual([entry["article"].pk for entry in entries], [newer.pk, older.pk],
                         "duplicate horse links consumed the distinct-article limit")
        self.assertEqual(self.ids(1), [newer.pk])
        self.assertEqual(self.ids(10), [newer.pk, older.pk])
        for entry in entries:
            # 同文可以由任一原合格关系代表，不新增AUTO/MANUAL或马匹优先策略。
            self.assertEqual(entry["link"].article_id, entry["article"].pk)
            self.assertEqual(entry["link"].horse_profile_id, entry["horse_profile"].pk)

    def test_zero_limit_returns_no_articles_despite_eligible_duplicate_links(self):
        self.duplicate_fixture()
        self.assertEqual(self.ids(0), [])

    def test_ineligible_articles_profiles_and_link_statuses_do_not_consume_limit(self):
        hidden = self.profile("hidden")
        draft = self.profile("draft")
        follow_horse(self.token_hash, hidden, include_descendants=False)
        follow_horse(self.token_hash, draft, include_descendants=False)
        hidden.review_status = HorseProfileStatus.HIDDEN
        hidden.save(update_fields=["review_status", "updated_at"])
        draft.review_status = HorseProfileStatus.DRAFT
        draft.save(update_fields=["review_status", "updated_at"])
        rejected = [
            (self.article("withdrawn", 100, status=WorkflowStatus.WITHDRAWN), self.first_horse, ArticleHorseLinkStatus.AUTO),
            (self.article("review", 101, status=WorkflowStatus.PENDING_REVIEW), self.first_horse, ArticleHorseLinkStatus.MANUAL),
            (self.article("no-web", 102, web=False), self.first_horse, ArticleHorseLinkStatus.AUTO),
            (self.article("candidate", 103), self.first_horse, ArticleHorseLinkStatus.CANDIDATE),
            (self.article("removed", 104), self.first_horse, ArticleHorseLinkStatus.REMOVED),
            (self.article("hidden-horse", 105), hidden, ArticleHorseLinkStatus.AUTO),
            (self.article("draft-horse", 106), draft, ArticleHorseLinkStatus.MANUAL),
        ]
        for article, horse, status in rejected:
            self.link(article, horse, status)
        newer = self.article("eligible-newer", 20)
        older = self.article("eligible-older", 10)
        self.link(newer, self.first_horse, ArticleHorseLinkStatus.MANUAL)
        self.link(older, self.second_horse)
        self.assertEqual(self.ids(2), [newer.pk, older.pk])

    def test_withdrawal_disappears_on_next_read_without_deleting_relation(self):
        newer = self.article("withdraw-transition", 20)
        older = self.article("still-public", 10)
        link = self.link(newer, self.first_horse)
        self.link(older, self.second_horse, ArticleHorseLinkStatus.MANUAL)
        self.assertEqual(self.ids(2), [newer.pk, older.pk])
        newer.workflow_status = WorkflowStatus.WITHDRAWN
        newer.withdrawn_at = BASE + timedelta(seconds=30)
        newer.save(update_fields=["workflow_status", "withdrawn_at", "updated_at"])
        self.assertEqual(self.ids(2), [older.pk])
        self.assertEqual(self.ids(2), [older.pk])
        self.assertTrue(ArticleHorseLink.objects.filter(pk=link.pk, status=ArticleHorseLinkStatus.AUTO).exists())

    def test_equal_publication_time_keeps_descending_article_id_order(self):
        first = self.article("tie-first", 20)
        second = self.article("tie-second", 20)
        self.link(first, self.first_horse)
        self.link(first, self.second_horse, ArticleHorseLinkStatus.MANUAL)
        self.link(second, self.first_horse)
        self.assertEqual(self.ids(10), [second.pk, first.pk])
