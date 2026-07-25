from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import (
    NewsArticle,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermEntry,
    TermType,
)
from stable.services.translation import (
    DummyTranslationProvider,
    OpenAICompatibleTranslationProvider,
    TranslationResponseError,
)


TRANSLATION_TEST_SETTINGS = {
    "ENGLISH_TERM_CONTEXT_MODE": "enforce",
    "TRANSLATION_MODEL": "test-model",
    "TRANSLATION_MAX_ATTEMPTS": 1,
    "TRANSLATION_TERM_LIMIT": 50,
    "TRANSLATION_UNKNOWN_HORSE_LIMIT": 20,
}


def fake_translation_response(payload: dict):
    usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
    choice = type(
        "Choice",
        (),
        {
            "message": type("Message", (), {"content": json.dumps(payload, ensure_ascii=False)})(),
            "finish_reason": "stop",
        },
    )()
    return type("Response", (), {"choices": [choice], "usage": usage})()


@override_settings(**TRANSLATION_TEST_SETTINGS)
class HorseRacingNationSourceTermTranslationTests(TestCase):
    def _article(
        self,
        title: str,
        body: str,
        *,
        source_site: str = SourceSite.HORSE_RACING_NATION,
        racing_region: str = RacingRegion.UNITED_STATES,
    ) -> NewsArticle:
        sequence = NewsArticle.objects.count() + 1
        return NewsArticle.objects.create(
            source_site=source_site,
            source_mode=SourceMode.LATEST,
            source_article_id=f"hrn-source-term-{sequence}",
            source_language=SourceLanguage.ENGLISH,
            racing_region=racing_region,
            title_ja=title,
            body_ja_raw=body,
            body_ja_normalized=body,
            published_at=timezone.now(),
            source_url=f"https://example.com/hrn-source-term/{sequence}",
        )

    def _british_jockey_club_term(self) -> TermEntry:
        return TermEntry.objects.create(
            term_type=TermType.ORG,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="The Jockey Club",
            target_zh="英国赛马会",
            priority=200,
        )

    def _provider(self) -> OpenAICompatibleTranslationProvider:
        return OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )

    def test_hrn_source_term_overrides_british_glossary_and_is_auditable(self):
        self._british_jockey_club_term()
        article = self._article(
            "The Jockey Club publishes registry update",
            "The Jockey Club confirmed the registration policy.",
        )
        provider = self._provider()
        response = fake_translation_response(
            {
                "title_zh": "__UMA_TERM_1__发布登记更新",
                "body_zh": "__UMA_TERM_1__确认了登记政策。",
                "push_summary_zh": "__UMA_TERM_1__确认新政策。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response) as request:
            result = provider.translate(article)

        prompt = request.call_args.args[0][1]["content"]
        self.assertIn("__UMA_TERM_1__", prompt)
        self.assertIn("确定性术语占位符", prompt)
        self.assertNotIn("The Jockey Club => 英国赛马会", prompt)
        self.assertNotIn("__UMA_TERM_1__ => 英国赛马会", prompt)
        self.assertEqual(result.title_zh, "美国赛马会发布登记更新")
        self.assertEqual(result.body_zh, "美国赛马会确认了登记政策。")
        self.assertEqual(result.push_summary_zh, "美国赛马会确认新政策。")
        self.assertEqual(
            result.metadata["source_term_placeholders"],
            {
                "__UMA_TERM_1__": {
                    "source_site": SourceSite.HORSE_RACING_NATION,
                    "source": "The Jockey Club",
                    "target": "美国赛马会",
                    "field_counts": {"title": 1, "body": 1},
                }
            },
        )

    def test_source_and_person_terms_share_stable_term_numbering_across_fields(self):
        self._british_jockey_club_term()
        TermEntry.objects.create(
            term_type=TermType.JOCKEY,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Irad Ortiz Jr.",
            target_zh="奥天信",
            priority=180,
        )
        article = self._article(
            "The Jockey Club honors Irad Ortiz Jr. at The Jockey Club dinner",
            (
                "The Jockey Club welcomed Irad Ortiz Jr. "
                "The Jockey Club then presented the award."
            ),
        )
        provider = self._provider()
        response = fake_translation_response(
            {
                "title_zh": "__UMA_TERM_1__在__UMA_TERM_1__晚宴表彰__UMA_TERM_2__",
                "body_zh": "__UMA_TERM_1__欢迎__UMA_TERM_2__。__UMA_TERM_1__随后颁奖。",
                "push_summary_zh": "__UMA_TERM_1__表彰__UMA_TERM_2__。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertEqual(result.title_zh.count("美国赛马会"), 2)
        self.assertEqual(result.body_zh.count("美国赛马会"), 2)
        self.assertIn("奥天信", result.title_zh)
        self.assertIn("奥天信", result.body_zh)
        self.assertNotIn("__UMA_TERM_", result.title_zh + result.body_zh + result.push_summary_zh)
        self.assertEqual(
            result.metadata["person_term_placeholders"],
            {"__UMA_TERM_2__": {"source": "Irad Ortiz Jr.", "target": "奥天信"}},
        )

    def test_source_term_uses_case_insensitive_complete_boundaries_not_clubhouse(self):
        self._british_jockey_club_term()
        article = self._article(
            "The Jockey Clubhouse renovation",
            "THE JOCKEY CLUB approved it; the jockey club later confirmed it.",
        )
        provider = self._provider()
        response = fake_translation_response(
            {
                "title_zh": "The Jockey Clubhouse翻新",
                "body_zh": "__UMA_TERM_1__批准；__UMA_TERM_1__随后确认。",
                "push_summary_zh": "__UMA_TERM_1__确认翻新。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response) as request:
            result = provider.translate(article)

        prompt = request.call_args.args[0][1]["content"]
        self.assertIn("The Jockey Clubhouse", prompt)
        self.assertEqual(result.title_zh, "The Jockey Clubhouse翻新")
        self.assertEqual(result.body_zh.count("美国赛马会"), 2)
        self.assertNotIn("英国赛马会", result.body_zh)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_missing_source_term_placeholder_retries_then_fails_closed(self):
        self._british_jockey_club_term()
        article = self._article(
            "The Jockey Club registry",
            "The Jockey Club published the registry.",
        )
        provider = self._provider()
        response = fake_translation_response(
            {
                "title_zh": "赛马会登记册",
                "body_zh": "赛马会发布了登记册。",
                "push_summary_zh": "赛马会发布登记册。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response) as request:
            with self.assertRaisesRegex(TranslationResponseError, "required.*term|placeholder"):
                provider.translate(article)

        self.assertEqual(request.call_count, 2)

    def test_cross_field_or_mutated_source_placeholder_fails_closed(self):
        self._british_jockey_club_term()
        article = self._article(
            "The Jockey Club registry",
            "The registry was published today.",
        )
        provider = self._provider()
        response = fake_translation_response(
            {
                "title_zh": "登记册更新",
                "body_zh": "__UMA_TERM_9__今天发布登记册。",
                "push_summary_zh": "登记册更新。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response):
            with self.assertRaises(TranslationResponseError):
                provider.translate(article)

    def test_summary_can_copy_existing_source_placeholder_but_cannot_invent_one(self):
        self._british_jockey_club_term()
        article = self._article(
            "Registry update",
            "The Jockey Club published the registry.",
        )
        provider = self._provider()
        valid = fake_translation_response(
            {
                "title_zh": "登记册更新",
                "body_zh": "__UMA_TERM_1__发布了登记册。",
                "push_summary_zh": "__UMA_TERM_1__发布登记册。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=valid):
            result = provider.translate(article)

        self.assertEqual(result.push_summary_zh, "美国赛马会发布登记册。")

        invented = fake_translation_response(
            {
                "title_zh": "登记册更新",
                "body_zh": "__UMA_TERM_1__发布了登记册。",
                "push_summary_zh": "__UMA_TERM_999__发布登记册。",
            }
        )
        with patch.object(provider, "_request_completion", return_value=invented):
            with self.assertRaises(TranslationResponseError):
                provider.translate(article)

    def test_dummy_provider_uses_same_hrn_source_term_plan(self):
        self._british_jockey_club_term()
        article = self._article(
            "The Jockey Club registry",
            "The Jockey Club published the registry.",
        )

        result = DummyTranslationProvider().translate(article)

        self.assertIn("美国赛马会", result.title_zh)
        self.assertIn("美国赛马会", result.body_zh)
        self.assertNotIn("英国赛马会", result.title_zh + result.body_zh)
        self.assertEqual(
            next(iter(result.metadata["source_term_placeholders"].values()))["target"],
            "美国赛马会",
        )

    def test_non_hrn_british_article_keeps_existing_british_term(self):
        self._british_jockey_club_term()
        article = self._article(
            "The Jockey Club financial results",
            "The Jockey Club reported higher attendance.",
            source_site=SourceSite.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
        )

        result = DummyTranslationProvider().translate(article)

        self.assertIn("英国赛马会", result.title_zh)
        self.assertIn("英国赛马会", result.body_zh)
        self.assertNotIn("美国赛马会", result.title_zh + result.body_zh)
        self.assertNotIn("source_term_placeholders", result.metadata)
