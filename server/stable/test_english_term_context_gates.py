from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermAlias,
    TermAliasType,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.validation import validate_rewrite


BASE_SETTINGS = {
    "AUTO_DUPLICATE_HIGH_THRESHOLD": 0,
    "AUTO_DUPLICATE_REVIEW_THRESHOLD": 0,
    "AUTO_REWRITE_ENABLED": False,
    "MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS": [],
    "MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS": [],
}


@override_settings(**BASE_SETTINGS, ENGLISH_TERM_CONTEXT_MODE="enforce")
class EnglishTermContextGateTests(TestCase):
    def _term(self, source: str, *, target: str = "测试译名", term_type: str = TermType.HORSE, priority: int = 100):
        return TermEntry.objects.create(
            term_type=term_type,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja=source,
            target_zh=target,
            priority=priority,
        )

    def _article(self, *, title: str, body: str, translated_title: str = "赛马新闻", translated_body: str | None = None, **overrides):
        translated_body = translated_body or ("这是一篇经过翻译的赛马新闻正文，内容包含赛事背景、参赛阵容和相关消息。" * 8)
        defaults = {
            "source_site": SourceSite.SKY_SPORTS_RACING,
            "source_mode": SourceMode.LATEST,
            "source_article_id": f"english-context-{NewsArticle.objects.count() + 1}",
            "source_language": SourceLanguage.ENGLISH,
            "racing_region": RacingRegion.UNITED_KINGDOM,
            "title_ja": title,
            "body_ja_raw": body,
            "body_ja_normalized": body,
            "translated_title_zh": translated_title,
            "title_zh": translated_title,
            "translated_summary_zh": "赛事最新消息。",
            "summary_zh": "赛事最新消息。",
            "translated_body_zh": translated_body,
            "body_zh": translated_body,
            "published_at": timezone.now(),
            "source_url": f"https://example.com/context/{NewsArticle.objects.count() + 1}",
            "workflow_status": WorkflowStatus.PENDING_EDIT,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "automation_status": AutomationStatus.PENDING,
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def _classifications(self, outcome, source: str):
        return [
            item
            for item in outcome.details.get("english_term_classifications", [])
            if item.get("source_ja", "").casefold() == source.casefold()
        ]

    def _core_blockers(self, outcome, source: str):
        return [
            issue
            for issue in outcome.issues
            if issue.get("code") == "core_term_missing"
            and (issue.get("payload") or {}).get("source_ja", "").casefold() == source.casefold()
        ]

    def test_same_word_instances_are_classified_independently(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Sha Tin review",
            body=(
                "Brilliant was brilliant at Sha Tin. The horse won after a strong late run. "
                + "Connections reviewed the performance and confirmed plans for the next meeting. " * 5
            ),
        )

        outcome = validate_rewrite(article)

        classifications = self._classifications(outcome, "Brilliant")
        self.assertEqual(len(classifications), 2)
        self.assertEqual(
            [item["term_semantic_classification"] for item in classifications],
            ["proper_noun", "common_word"],
        )
        self.assertTrue(all(item.get("matched_span") for item in classifications))
        self.assertEqual(len(self._core_blockers(outcome, "Brilliant")), 1)

    def test_nearby_entity_relation_does_not_contaminate_a_later_common_word(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Sha Tin review",
            body=(
                "Brilliant won easily before another runner produced a brilliant performance. "
                "Connections reviewed the result and confirmed plans for the next meeting. " * 5
            ),
        )

        outcome = validate_rewrite(article)

        classifications = self._classifications(outcome, "Brilliant")
        self.assertGreaterEqual(len(classifications), 2)
        self.assertEqual(
            [item["term_semantic_classification"] for item in classifications[:2]],
            ["proper_noun", "common_word"],
        )

    def test_production_common_word_contexts_do_not_block(self):
        cases = {
            "Brilliant": "The filly produced a brilliant performance in testing conditions.",
            "Something": "Something went wrong before the start, according to the trainer.",
            "Versatile": "She is a versatile filly who can race over several distances.",
            "Incredible": "The jockey described the crowd as incredible after the race.",
            "Reputation": "The colt arrived with a huge reputation from his home stable.",
            "Threat": "The favourite still posed a threat in the closing stages.",
            "Title": "The champion is seeking another title this season.",
            "Soon": "It is too soon to decide where the horse will run next.",
            "Yet": "The runner has yet to win at this distance.",
        }
        for index, (term, sentence) in enumerate(cases.items(), start=1):
            with self.subTest(term=term):
                TermEntry.objects.all().delete()
                self._term(term)
                article = self._article(
                    source_article_id=f"common-context-{index}",
                    title="Stable update",
                    body=(sentence + " The report also reviewed preparations for the next meeting. ") * 5,
                )

                outcome = validate_rewrite(article)

                self.assertFalse(self._core_blockers(outcome, term))
                classifications = self._classifications(outcome, term)
                self.assertTrue(classifications)
                self.assertTrue(all(item["term_semantic_classification"] == "common_word" for item in classifications))

    def test_real_single_word_horse_contexts_still_block_when_not_preserved(self):
        cases = [
            "Brilliant won at Sha Tin after leading inside the final furlong.",
            "Brilliant finished second and will return next month.",
            "Brilliant, ridden by Ryan Moore, starts from stall four.",
            "Brilliant is trained by John Smith and carries 126 pounds.",
            "Brilliant (IRE) heads the field at Ascot.",
        ]
        for index, sentence in enumerate(cases, start=1):
            with self.subTest(sentence=sentence):
                NewsArticle.objects.all().delete()
                TermEntry.objects.all().delete()
                self._term("Brilliant", target="辉煌")
                article = self._article(
                    source_article_id=f"proper-context-{index}",
                    title="Ascot runner update",
                    body=(sentence + " Connections expect a competitive performance. ") * 4,
                )

                outcome = validate_rewrite(article)

                self.assertTrue(self._core_blockers(outcome, "Brilliant"))
                classifications = self._classifications(outcome, "Brilliant")
                self.assertTrue(any(item["term_semantic_classification"] == "proper_noun" for item in classifications))

    def test_race_jockey_and_trainer_proper_names_keep_their_blockers(self):
        terms = [
            (TermType.RACE, "King George Stakes", "英皇锦标"),
            (TermType.JOCKEY, "Ryan Moore", "莫雅"),
            (TermType.TRAINER, "John Smith", "约翰史密斯"),
        ]
        for term_type, source, target in terms:
            self._term(source, target=target, term_type=term_type)
        article = self._article(
            title="King George Stakes entries confirmed",
            body=(
                "Ryan Moore will ride the favourite for trainer John Smith in the King George Stakes. "
                "The field and draw were confirmed after final declarations. "
            )
            * 5,
        )

        outcome = validate_rewrite(article)

        blocker_sources = {
            issue["payload"]["source_ja"]
            for issue in outcome.issues
            if issue.get("code") == "core_term_missing"
        }
        self.assertTrue({source for _, source, _ in terms}.issubset(blocker_sources))

    def test_title_capitalization_alone_is_uncertain_and_conservative(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Brilliant Result",
            body="The meeting produced a close finish. Officials published the result after review. " * 6,
        )

        outcome = validate_rewrite(article)

        classifications = self._classifications(outcome, "Brilliant")
        self.assertEqual(classifications[0]["term_semantic_classification"], "uncertain")
        self.assertEqual(classifications[0]["match_position"], "title")
        blocker = self._core_blockers(outcome, "Brilliant")[0]
        self.assertEqual(blocker["payload"]["term_semantic_classification"], "uncertain")

    def test_uncertain_background_match_warns_without_blocking(self):
        self._term("Brilliant", target="辉煌", priority=10)
        lead = "The report reviewed the meeting, runners and conditions in detail. " * 12
        article = self._article(
            title="Weekly racing review",
            body=lead + "Brilliant Result was used as a promotional heading without identifying a runner.",
        )

        outcome = validate_rewrite(article)

        self.assertFalse(self._core_blockers(outcome, "Brilliant"))
        warning = next(
            issue
            for issue in outcome.issues
            if issue.get("code") == "background_term_missing"
            and (issue.get("payload") or {}).get("source_ja") == "Brilliant"
        )
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["payload"]["term_semantic_classification"], "uncertain")

    def test_high_priority_uncertain_background_match_still_only_warns(self):
        self._term("Brilliant", target="辉煌", priority=100)
        lead = "The report reviewed the meeting, runners and conditions in detail. " * 12
        article = self._article(
            title="Weekly racing review",
            body=lead + "Brilliant Result was used as a promotional heading without identifying a runner.",
        )

        outcome = validate_rewrite(article)

        self.assertFalse(self._core_blockers(outcome, "Brilliant"))
        warning = next(
            issue
            for issue in outcome.issues
            if issue.get("code") == "background_term_missing"
            and (issue.get("payload") or {}).get("source_ja") == "Brilliant"
        )
        self.assertEqual(warning["severity"], "warning")

    def test_preserved_alias_short_circuits_uncertain_classification(self):
        entry = self._term("Brilliant", target="辉煌")
        TermAlias.objects.create(
            term=entry,
            source_language=SourceLanguage.ENGLISH,
            text="Brilliant Result",
            alias_type=TermAliasType.ALIAS,
        )
        article = self._article(
            title="Brilliant Result",
            body="Officials used Brilliant Result as the heading for the latest meeting report. " * 5,
            translated_title="Brilliant Result",
        )

        outcome = validate_rewrite(article)

        self.assertFalse(self._core_blockers(outcome, "Brilliant"))

    def test_case_and_full_width_normalization_keep_the_actual_match_auditable(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Runner update",
            body="Ｂｒｉｌｌｉａｎｔ won at Ascot after a strong late challenge. " * 5,
        )

        outcome = validate_rewrite(article)

        classifications = self._classifications(outcome, "Brilliant")
        self.assertTrue(classifications)
        self.assertEqual(classifications[0]["matched_text"], "Ｂｒｉｌｌｉａｎｔ")
        self.assertEqual(classifications[0]["term_semantic_classification"], "proper_noun")

    def test_html_attributes_scripts_and_navigation_are_not_match_sources(self):
        self._term("Title", target="冠军头衔")
        normalized = (
            '<a title="Title" href="/next">Next</a>'
            '<script>const title = "Title";</script>'
            '<nav>Title | Contact | Home</nav>'
            "The visible racing report discusses runners and going conditions. " * 6
        )
        article = self._article(title="Meeting report", body=normalized)

        outcome = validate_rewrite(article)

        self.assertFalse(self._classifications(outcome, "Title"))
        self.assertFalse(self._core_blockers(outcome, "Title"))

    def test_region_filter_runs_before_context_classifier(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="Brilliant",
            target_zh="辉煌",
            priority=100,
        )
        article = self._article(
            title="Ascot runner update",
            body="Brilliant won at Ascot and returned to the winner's enclosure. " * 5,
        )

        with patch("stable.services.validation._classify_english_term_context") as classifier:
            outcome = validate_rewrite(article)

        classifier.assert_not_called()
        self.assertTrue(outcome.details["term_gate_region_excluded_terms"])


@override_settings(**BASE_SETTINGS)
class EnglishTermContextModeTests(TestCase):
    def _term(self, source: str, *, target: str = "测试译名"):
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja=source,
            target_zh=target,
            priority=100,
        )

    def _article(self, *, title: str, body: str):
        translated_body = "这是一篇经过翻译的赛马新闻正文，内容包含赛事背景、参赛阵容和相关消息。" * 8
        return NewsArticle.objects.create(
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_mode=SourceMode.LATEST,
            source_article_id=f"english-context-mode-{NewsArticle.objects.count() + 1}",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja=title,
            body_ja_raw=body,
            body_ja_normalized=body,
            translated_title_zh="赛马新闻",
            title_zh="赛马新闻",
            translated_summary_zh="赛事最新消息。",
            summary_zh="赛事最新消息。",
            translated_body_zh=translated_body,
            body_zh=translated_body,
            published_at=timezone.now(),
            source_url="https://example.com/context/mode",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            automation_status=AutomationStatus.PENDING,
        )

    def _core_blockers(self, outcome, source: str):
        return [
            issue
            for issue in outcome.issues
            if issue.get("code") == "core_term_missing"
            and (issue.get("payload") or {}).get("source_ja", "").casefold() == source.casefold()
        ]

    def test_off_keeps_legacy_gate_result(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Stable update",
            body="The filly produced a brilliant performance in testing conditions. " * 6,
        )

        with self.settings(
            ENGLISH_TERM_CONTEXT_MODE="off",
            MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=[],
        ):
            outcome = validate_rewrite(article)

        self.assertTrue(self._core_blockers(outcome, "Brilliant"))
        self.assertFalse(outcome.details.get("english_term_context_shadow"))

    def test_shadow_records_difference_without_changing_legacy_result(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Stable update",
            body="The filly produced a brilliant performance in testing conditions. " * 6,
        )
        before = {
            "workflow_status": article.workflow_status,
            "automation_status": article.automation_status,
            "gate_issues": article.gate_issues,
        }

        with self.settings(
            ENGLISH_TERM_CONTEXT_MODE="shadow",
            MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=[],
        ):
            outcome = validate_rewrite(article)

        article.refresh_from_db()
        self.assertTrue(self._core_blockers(outcome, "Brilliant"))
        self.assertTrue(outcome.details["english_term_context_shadow"]["would_remove_blocker"])
        self.assertEqual(article.workflow_status, before["workflow_status"])
        self.assertEqual(article.automation_status, before["automation_status"])
        self.assertEqual(article.gate_issues, before["gate_issues"])

    def test_shadow_records_legacy_blocker_removed_with_page_chrome(self):
        self._term("Title", target="冠军头衔")
        article = self._article(
            title="Meeting report",
            body=(
                '<nav>Title | Contact | Home</nav>'
                "The visible racing report discusses runners and going conditions. " * 6
            ),
        )

        with self.settings(
            ENGLISH_TERM_CONTEXT_MODE="shadow",
            MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=[],
        ):
            outcome = validate_rewrite(article)

        self.assertTrue(self._core_blockers(outcome, "Title"))
        shadow = outcome.details["english_term_context_shadow"]
        self.assertTrue(shadow["would_remove_blocker"])
        self.assertEqual(shadow["terms"][0]["reason"], "not_in_visible_source")
        self.assertIsNone(shadow["terms"][0]["issue"])

    def test_enforce_applies_context_result(self):
        self._term("Brilliant", target="辉煌")
        article = self._article(
            title="Stable update",
            body="The filly produced a brilliant performance in testing conditions. " * 6,
        )

        with self.settings(
            ENGLISH_TERM_CONTEXT_MODE="enforce",
            MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=[],
        ):
            outcome = validate_rewrite(article)

        self.assertFalse(self._core_blockers(outcome, "Brilliant"))
        self.assertTrue(
            any(issue["code"] == "english_term_common_word_downgraded" for issue in outcome.issues)
        )
