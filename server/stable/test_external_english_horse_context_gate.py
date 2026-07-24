from __future__ import annotations

import json
import re
from io import StringIO
from unittest.mock import ANY, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleTranslationStatus,
    AutomationStatus,
    ExternalDataSource,
    ExternalHorseAlias,
    HorseProfile,
    HorseProfileStatus,
    NewsArticle,
    NewsArticleRelatedRegion,
    NotificationChannel,
    NotificationLog,
    NotificationStatus,
    NotificationType,
    PublishedByMode,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RaceEvent,
    RaceEventResult,
    RaceEventRunner,
    RaceEventSurface,
    RacingRegion,
    ReviewMode,
    RiskLevel,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermEntry,
    TermGateReprocessRun,
    TermGateReprocessStatus,
    TermTranslationStatus,
    TermType,
    WorkflowStatus,
)
from stable.services.notifications import send_high_value_warning_notification
from stable.services.rewriting import OpenAICompatibleRewriteProvider
from stable.services.term_discovery import discover_term_findings
from stable.services.terms import (
    apply_contextual_term_mappings,
    apply_generated_text_contextual_mappings,
    english_horse_name_has_confirmed_occurrence,
    resolve_article_entities,
)
from stable.services.translation import (
    DummyTranslationProvider,
    OpenAICompatibleTranslationProvider,
    translate_article,
)
from stable.services.validation import validate_rewrite, warning_signature


SETTINGS = {
    "AUTO_DUPLICATE_HIGH_THRESHOLD": 0,
    "AUTO_DUPLICATE_REVIEW_THRESHOLD": 0,
    "AUTO_REWRITE_ENABLED": False,
    "AUTOMATION_WARNING_EMAIL_ENABLED": True,
    "AUTOMATION_WARNING_NOTIFY_EMAILS": ["alerts@example.com"],
    "ENGLISH_TERM_CONTEXT_MODE": "enforce",
    "MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS": [],
    "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS": [],
    "MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS": [],
}

POLLUTING_WORDS = (
    "Africa",
    "Amount",
    "Campaign",
    "DUTY",
    "East",
    "Emphasis",
    "Engage",
    "Established",
    "Expanded",
    "Really Good",
    "Set",
    "Top",
    "Work",
)

ARTICLE_9595_EQUIVALENT_BODY = """
His previous business remit included Africa, the Middle East and Asia Pacific.
There has been a fair amount of change, with a particular emphasis on listening.
He backed a campaign to abolish the beer duty escalator and promised to meet and
engage with stakeholders. The organisation has established a new plan, while his
role expanded to cover racing and breeding. He said the team had done really good
work, with work already underway, and would work together to set the programme up.
The aim is to support top-class horses throughout the sport. The St Leger
winner-turned-stallion Logician was among the horses he followed most closely.
""".strip()

HORSE_ISSUE_CODES = {
    "pending_horse_original_missing",
    "external_horse_not_preserved",
    "unknown_horse_not_preserved",
    "core_term_missing",
    "background_term_missing",
}


def _fake_translation_response(payload: dict):
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


@override_settings(**SETTINGS)
class ExternalEnglishHorseContextGateTests(TestCase):
    def _article(self, *, title: str = "Racing leadership update", body: str, **overrides) -> NewsArticle:
        translated_body = "这是一篇经过人工校对的赛马新闻正文，介绍行业动态、参赛情况和后续计划。" * 8
        defaults = {
            "source_site": SourceSite.TDN,
            "source_mode": SourceMode.LATEST,
            "source_article_id": f"external-english-gate-{NewsArticle.objects.count() + 1}",
            "source_language": SourceLanguage.ENGLISH,
            "racing_region": RacingRegion.UNITED_KINGDOM,
            "title_ja": title,
            "body_ja_raw": body,
            "body_ja_normalized": body,
            "translated_title_zh": "赛马新闻",
            "title_zh": "赛马新闻",
            "translated_summary_zh": "赛事和行业最新动态。",
            "summary_zh": "赛事和行业最新动态。",
            "translated_body_zh": translated_body,
            "body_zh": translated_body,
            "published_at": timezone.now(),
            "source_url": "https://example.com/external-english-context",
            "workflow_status": WorkflowStatus.PENDING_EDIT,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "automation_status": AutomationStatus.PENDING,
            "score_total": 100,
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def _pending_term(self, source: str, *, priority: int = 100) -> TermEntry:
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja=source,
            target_zh="",
            translation_status=TermTranslationStatus.PENDING,
            notes="p0_major_race_participant_auto_created",
            priority=priority,
        )

    def _translated_term(self, source: str, target: str) -> TermEntry:
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja=source,
            target_zh=target,
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=100,
        )

    def _external_alias(self, name: str, *, external_id: str = "horse-001") -> ExternalHorseAlias:
        return ExternalHorseAlias.objects.create(
            source=ExternalDataSource.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id=external_id,
            name_ja=name,
            name_en=name,
            normalized_name=name,
            confidence=98,
            alias_source="test_fixture",
        )

    def _entities_for(self, resolution, matched_text: str):
        return [
            item.as_dict()
            for item in resolution.entities
            if item.matched_text.casefold() == matched_text.casefold()
        ]

    def _article_resolver(self):
        from stable.services import terms

        resolver = getattr(terms, "resolve_article_entities_for_article", None)
        self.assertIsNotNone(
            resolver,
            "缺少设计锁定的 article-aware 单篇 resolver：resolve_article_entities_for_article",
        )
        return resolver

    def _batch_resolver(self):
        from stable.services import terms

        resolver = getattr(terms, "resolve_article_entities_for_articles", None)
        self.assertIsNotNone(
            resolver,
            "缺少设计锁定的 article-aware 批量 resolver：resolve_article_entities_for_articles",
        )
        return resolver

    def assertOccurrence(self, payload: dict, *, classification: str, needs_preserve: bool):
        self.assertEqual(payload.get("classification"), classification, payload)
        self.assertEqual(payload.get("needs_preserve"), needs_preserve, payload)
        self.assertTrue(payload.get("matched_text"), payload)
        self.assertTrue(payload.get("matched_context"), payload)
        self.assertTrue(payload.get("matched_span"), payload)
        self.assertTrue(payload.get("reason"), payload)
        self.assertIsInstance(payload.get("confidence"), (int, float), payload)

    def test_article_9595_common_words_do_not_create_horse_warnings(self):
        terms = {word: self._pending_term(word) for word in POLLUTING_WORDS}
        self._translated_term("Logician", "逻辑学家")
        article = self._article(body=ARTICLE_9595_EQUIVALENT_BODY)

        outcome = validate_rewrite(article)

        polluted = [
            issue
            for issue in outcome.issues
            if issue.get("code") in HORSE_ISSUE_CODES
            and ((issue.get("payload") or {}).get("term_id") in {term.id for term in terms.values()}
                 or (issue.get("payload") or {}).get("source_ja") in POLLUTING_WORDS)
        ]
        self.assertEqual(polluted, [])
        entity_payloads = outcome.details.get("article_entities", [])
        by_term_id = {
            payload.get("term_id"): payload
            for payload in entity_payloads
            if payload.get("term_id") in {term.id for term in terms.values()}
        }
        self.assertEqual(set(by_term_id), {term.id for term in terms.values()})
        for word, term in terms.items():
            with self.subTest(word=word):
                self.assertOccurrence(by_term_id[term.id], classification="common_word", needs_preserve=False)

    def _legacy_common_horse_fixture(self):
        built_in_seed = self._translated_term("Agenda", "议程")
        configured_word = self._translated_term("Brilliant", "辉煌")
        article = self._article(
            source_article_id="legacy-common-horse-context-mode",
            title="Business update",
            body=(
                "The agenda for the company meeting covered staffing and budgets. "
                "The team delivered a brilliant performance during the presentation."
            ),
        )
        return article, (built_in_seed, configured_word)

    @staticmethod
    def _term_missing_issues(outcome, term_ids):
        return [
            issue
            for issue in outcome.issues
            if issue["code"] in {"core_term_missing", "background_term_missing"}
            and (issue.get("payload") or {}).get("term_id") in term_ids
        ]

    @override_settings(
        ENGLISH_TERM_CONTEXT_MODE="off",
        MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=["brilliant"],
    )
    def test_off_legacy_common_word_downgrade_includes_translated_horse_entries(self):
        article, terms = self._legacy_common_horse_fixture()
        term_ids = {term.id for term in terms}

        outcome = validate_rewrite(article)

        self.assertEqual(
            self._term_missing_issues(outcome, term_ids),
            [],
            outcome.issues,
        )
        downgraded_ids = {
            (issue.get("payload") or {}).get("term_id")
            for issue in outcome.issues
            if issue["code"] == "english_term_common_word_downgraded"
        }
        self.assertEqual(downgraded_ids & term_ids, term_ids)
        self.assertFalse(outcome.details.get("english_term_context_shadow"))

    @override_settings(
        ENGLISH_TERM_CONTEXT_MODE="shadow",
        MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=["brilliant"],
    )
    def test_shadow_records_occurrence_would_change_but_keeps_legacy_horse_downgrade(self):
        article, terms = self._legacy_common_horse_fixture()
        term_ids = {term.id for term in terms}

        outcome = validate_rewrite(article)

        self.assertEqual(
            self._term_missing_issues(outcome, term_ids),
            [],
            outcome.issues,
        )
        downgraded_ids = {
            (issue.get("payload") or {}).get("term_id")
            for issue in outcome.issues
            if issue["code"] == "english_term_common_word_downgraded"
        }
        self.assertEqual(downgraded_ids & term_ids, term_ids)
        shadow = outcome.details.get("english_term_context_shadow") or {}
        shadow_terms = {
            item.get("term_id"): item
            for item in shadow.get("terms", [])
            if item.get("term_id") in term_ids
        }
        self.assertEqual(set(shadow_terms), term_ids, shadow)
        self.assertTrue(
            all(item.get("classifications") for item in shadow_terms.values()),
            shadow_terms,
        )

    def _legacy_mode_machine_link_fixture(
        self,
        *,
        suffix: str,
        status: str,
    ) -> tuple[NewsArticle, TermEntry, TermEntry]:
        horse_term = self._translated_term("Brilliant", "辉煌")
        accepted_race_term = TermEntry.objects.create(
            term_type=TermType.RACE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Ascot",
            target_zh="雅士谷",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=90,
        )
        translated_body = (
            "公司在雅士谷公布了业务简报，相关背景、后续安排和行业影响均已完整说明。"
            * 8
        )
        article = self._article(
            source_article_id=f"legacy-machine-link-{suffix}",
            title="Business update",
            body=(
                "The board described the Brilliant performance at Ascot "
                "as a successful business presentation."
            ),
            translated_body_zh=translated_body,
            body_zh=translated_body,
        )
        ArticleHorseLink.objects.create(
            article=article,
            horse_profile=self._machine_link_profile(horse_term),
            status=status,
            source="legacy_mode_contract",
            confidence=80,
            matched_text="Brilliant",
        )
        return article, horse_term, accepted_race_term

    def _resolver_with_weak_horse_forced_uncertain(
        self,
        article: NewsArticle,
        horse_term: TermEntry,
    ):
        original_resolver = self._article_resolver()

        def resolve_with_uncertain(*args, **kwargs):
            resolution = original_resolver(*args, **kwargs)
            for entity in resolution.entities:
                if entity.term_id != horse_term.id:
                    continue
                entity.entity_type = "ambiguous"
                entity.classification = "uncertain"
                entity.reason = "mock_lexical_horse_index_only"
                entity.confidence = 45
                entity.needs_preserve = False
                entity.conflict_flags = ["horse_term_without_strong_context"]
            return resolution

        return resolve_with_uncertain

    @staticmethod
    def _legacy_gate_snapshot(outcome) -> dict:
        mismatches = [
            issue
            for issue in outcome.issues
            if issue["code"] == "machine_entity_type_mismatch"
        ]
        return {
            "passed": outcome.passed,
            "reason": outcome.reason,
            "issues": outcome.issues,
            "blockers": outcome.blockers,
            "accepted_term_ids": outcome.details.get("accepted_term_ids"),
            "mismatches": mismatches,
        }

    def test_off_and_shadow_keep_complete_legacy_gate_semantics_when_v2_calls_match_uncertain(self):
        fixtures = (
            ("off", ArticleHorseLinkStatus.AUTO),
            ("shadow", ArticleHorseLinkStatus.CANDIDATE),
        )
        for mode, link_status in fixtures:
            with self.subTest(mode=mode, link_status=link_status):
                article, horse_term, accepted_race_term = (
                    self._legacy_mode_machine_link_fixture(
                        suffix=mode,
                        status=link_status,
                    )
                )
                with override_settings(
                    ENGLISH_TERM_CONTEXT_MODE=mode,
                    MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=["brilliant"],
                ):
                    legacy_outcome = validate_rewrite(article)
                    with patch(
                        "stable.services.validation.resolve_article_entities_for_article",
                        side_effect=self._resolver_with_weak_horse_forced_uncertain(
                            article,
                            horse_term,
                        ),
                    ):
                        mocked_v2_outcome = validate_rewrite(article)

                legacy_snapshot = self._legacy_gate_snapshot(legacy_outcome)
                mocked_snapshot = self._legacy_gate_snapshot(mocked_v2_outcome)
                self.assertEqual(
                    mocked_snapshot,
                    legacy_snapshot,
                    "off/shadow 的 outcome、gate、issues、accepted IDs 和 mismatch "
                    "必须保持完整 legacy 语义，不能由 occurrence uncertain 改写",
                )
                self.assertEqual(
                    mocked_snapshot["accepted_term_ids"],
                    [accepted_race_term.id],
                )
                self.assertTrue(mocked_snapshot["mismatches"])
                self.assertIn(
                    horse_term.id,
                    mocked_snapshot["mismatches"][0]["payload"][
                        "auto_link_term_ids"
                    ],
                )
                if mode == "shadow":
                    shadow = (
                        mocked_v2_outcome.details.get(
                            "english_term_context_shadow"
                        )
                        or {}
                    )
                    self.assertTrue(shadow.get("terms"), shadow)

    @override_settings(
        ENGLISH_TERM_CONTEXT_MODE="enforce",
        MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=["brilliant"],
    )
    def test_enforce_uses_occurrence_classification_for_same_uncertain_machine_link_fixture(self):
        article, horse_term, accepted_race_term = (
            self._legacy_mode_machine_link_fixture(
                suffix="enforce",
                status=ArticleHorseLinkStatus.AUTO,
            )
        )

        with patch(
            "stable.services.validation.resolve_article_entities_for_article",
            side_effect=self._resolver_with_weak_horse_forced_uncertain(
                article,
                horse_term,
            ),
        ):
            outcome = validate_rewrite(article)

        self.assertEqual(
            outcome.details["accepted_term_ids"],
            [accepted_race_term.id],
        )
        self.assertFalse(
            any(
                issue["code"] == "machine_entity_type_mismatch"
                for issue in outcome.issues
            ),
            outcome.issues,
        )
        self.assertTrue(
            any(
                issue["code"] == "english_horse_occurrence_uncertain"
                and (issue.get("payload") or {}).get("term_id") == horse_term.id
                and issue["severity"] == "info"
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    @override_settings(
        ENGLISH_TERM_CONTEXT_MODE="enforce",
        MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS=["brilliant"],
    )
    def test_enforce_keeps_occurrence_classification_for_common_horse_words(self):
        article, terms = self._legacy_common_horse_fixture()
        term_ids = {term.id for term in terms}

        outcome = validate_rewrite(article)

        self.assertEqual(
            self._term_missing_issues(outcome, term_ids),
            [],
            outcome.issues,
        )
        entity_payloads = [
            item
            for item in outcome.details["article_entities"]
            if item.get("term_id") in term_ids
        ]
        self.assertEqual(
            {item["term_id"] for item in entity_payloads},
            term_ids,
        )
        self.assertTrue(
            all(
                item["classification"] == "common_word"
                and item["needs_preserve"] is False
                for item in entity_payloads
            ),
            entity_payloads,
        )

    def test_logician_is_confirmed_and_uses_translated_mapping(self):
        term = self._translated_term("Logician", "逻辑学家")

        resolution = resolve_article_entities(
            "Stallion update",
            "The St Leger winner-turned-stallion Logician remains popular with breeders.",
            source_language=SourceLanguage.ENGLISH,
        )

        payload = self._entities_for(resolution, "Logician")[0]
        self.assertOccurrence(payload, classification="confirmed_horse", needs_preserve=False)
        self.assertEqual(payload["term_id"], term.id)
        self.assertEqual(payload["target_zh"], "逻辑学家")
        self.assertTrue(any(item.target_zh == "逻辑学家" for item in resolution.accepted_terms))

    def test_pending_term_strong_contexts_are_confirmed_and_preserved(self):
        self._pending_term("Brilliant")
        cases = (
            "Brilliant won at Ascot.",
            "Brilliant finished second.",
            "Brilliant, ridden by Ryan Moore, starts from stall four.",
            "Brilliant is trained by John Smith.",
            "Brilliant (IRE) heads the field.",
        )

        for sentence in cases:
            with self.subTest(sentence=sentence):
                resolution = resolve_article_entities("Ascot update", sentence, source_language=SourceLanguage.ENGLISH)
                payload = self._entities_for(resolution, "Brilliant")[0]
                self.assertOccurrence(payload, classification="confirmed_horse", needs_preserve=True)

    def test_external_alias_strong_contexts_are_confirmed_and_preserved(self):
        alias = self._external_alias("Brilliant", external_id="sl-brilliant")
        cases = (
            "Brilliant won at Ascot.",
            "Brilliant finished second.",
            "Brilliant, ridden by Ryan Moore, starts from stall four.",
            "Brilliant is trained by John Smith.",
            "Brilliant (IRE) heads the field.",
        )

        for sentence in cases:
            with self.subTest(sentence=sentence):
                resolution = resolve_article_entities("Ascot update", sentence, source_language=SourceLanguage.ENGLISH)
                payload = self._entities_for(resolution, "Brilliant")[0]
                self.assertOccurrence(payload, classification="confirmed_horse", needs_preserve=True)
                self.assertEqual(payload["external_horse_ids"], [alias.external_horse_id])

    def test_horse_entity_noun_context_does_not_override_strong_race_relation(self):
        pending = self._pending_term("Brilliant")
        alias = self._external_alias("Splendid", external_id="sl-splendid-filly")

        resolution = resolve_article_entities(
            "Ascot result",
            "The Brilliant filly won at Ascot. The Splendid filly won the next race.",
            source_language=SourceLanguage.ENGLISH,
        )

        pending_payload = self._entities_for(resolution, "Brilliant")[0]
        alias_payload = self._entities_for(resolution, "Splendid")[0]
        self.assertEqual(pending_payload["term_id"], pending.id)
        self.assertOccurrence(
            pending_payload,
            classification="confirmed_horse",
            needs_preserve=True,
        )
        self.assertEqual(alias_payload["external_horse_ids"], [alias.external_horse_id])
        self.assertOccurrence(
            alias_payload,
            classification="confirmed_horse",
            needs_preserve=True,
        )

    def test_external_alias_bare_horse_entity_nouns_override_adjective_downgrade(self):
        alias = self._external_alias(
            "Brilliant",
            external_id="sl-bare-horse-entity-noun",
        )
        cases = (
            "The Brilliant filly impressed observers in the paddock.",
            "The Brilliant horse arrived at Ascot before the meeting.",
        )

        for index, sentence in enumerate(cases, start=1):
            with self.subTest(sentence=sentence):
                article = self._article(
                    source_article_id=f"bare-horse-entity-noun-{index}",
                    title="Ascot stable update",
                    body=sentence,
                )
                resolution = self._article_resolver()(article)
                payload = self._entities_for(
                    resolution,
                    "Brilliant",
                )[0]

                self.assertEqual(
                    payload["external_horse_ids"],
                    [alias.external_horse_id],
                )
                self.assertOccurrence(
                    payload,
                    classification="confirmed_horse",
                    needs_preserve=True,
                )

                outcome = validate_rewrite(article)
                recognized = [
                    item
                    for item in outcome.details["recognized_horse_names"]
                    if item["matched_text"] == "Brilliant"
                    and item["needs_preserve"]
                ]
                self.assertEqual(len(recognized), 1, recognized)
                self.assertTrue(
                    any(
                        issue["code"]
                        == "external_horse_not_preserved"
                        for issue in outcome.issues
                    ),
                    outcome.issues,
                )

    def test_entity_noun_relations_win_but_ordinary_adjectives_remain_common(self):
        cases = (
            ("pending", "Brilliant"),
            ("external_alias", "Splendid"),
        )
        for source, name in cases:
            with self.subTest(source=source):
                TermEntry.objects.all().delete()
                ExternalHorseAlias.objects.all().delete()
                if source == "pending":
                    self._pending_term(name)
                else:
                    self._external_alias(name, external_id="sl-splendid-entity-noun")
                resolution = resolve_article_entities(
                    "Ascot stable update",
                    (
                        f"The {name} filly is trained by John Smith. "
                        f"{name} mare, trained by Jane Doe, won last season. "
                        f"The team also produced a {name.lower()} performance."
                    ),
                    source_language=SourceLanguage.ENGLISH,
                )

                payloads = self._entities_for(resolution, name)
                self.assertEqual(len(payloads), 3, payloads)
                expectations = (
                    ("the_filly_is_trained", payloads[0], "confirmed_horse", True),
                    ("mare_trained_by", payloads[1], "confirmed_horse", True),
                    ("ordinary_adjective", payloads[2], "common_word", False),
                )
                for occurrence, payload, classification, needs_preserve in expectations:
                    with self.subTest(source=source, occurrence=occurrence):
                        self.assertOccurrence(
                            payload,
                            classification=classification,
                            needs_preserve=needs_preserve,
                        )

    def test_lowercase_adjective_before_filly_is_not_promoted_by_race_relation(self):
        self._external_alias(
            "Brilliant",
            external_id="sl-lowercase-adjective-filly",
        )
        resolution = resolve_article_entities(
            "Ascot stable update",
            (
                "The yard said a brilliant filly won at Ascot. "
                "Brilliant won the next race. "
                "The Brilliant filly won the finale."
            ),
            source_language=SourceLanguage.ENGLISH,
        )

        payloads = self._entities_for(resolution, "Brilliant")
        self.assertEqual(len(payloads), 3, payloads)
        self.assertOccurrence(
            payloads[0],
            classification="common_word",
            needs_preserve=False,
        )
        self.assertOccurrence(
            payloads[1],
            classification="confirmed_horse",
            needs_preserve=True,
        )
        self.assertOccurrence(
            payloads[2],
            classification="confirmed_horse",
            needs_preserve=True,
        )

    def test_same_surface_is_classified_per_occurrence(self):
        self._pending_term("Brilliant")

        resolution = resolve_article_entities(
            "Ascot review",
            "Brilliant won at Ascot. Later, the trainer praised a brilliant performance from the team.",
            source_language=SourceLanguage.ENGLISH,
        )

        payloads = self._entities_for(resolution, "Brilliant")
        self.assertEqual(len(payloads), 2, payloads)
        self.assertOccurrence(payloads[0], classification="confirmed_horse", needs_preserve=True)
        self.assertOccurrence(payloads[1], classification="common_word", needs_preserve=False)

    def test_pending_repeated_copula_phrase_is_not_horse_context(self):
        self._pending_term("Enough")
        article = self._article(
            source_article_id="pending-repeated-copula",
            title="Leadership reflection",
            body="Enough was enough.",
        )

        resolution = self._article_resolver()(article)
        outcome = validate_rewrite(article)

        payloads = self._entities_for(resolution, "Enough")
        self.assertEqual(len(payloads), 2, payloads)
        for payload in payloads:
            self.assertIn(payload["classification"], {"common_word", "uncertain"}, payload)
            self.assertFalse(payload["needs_preserve"], payload)
        self.assertFalse(
            any(issue["code"] in HORSE_ISSUE_CODES for issue in outcome.issues),
            outcome.issues,
        )

    def test_formal_repeated_copula_phrase_is_not_horse_context_but_win_is_confirmed(self):
        self._translated_term("Work", "工作")
        article = self._article(
            source_article_id="formal-repeated-copula",
            title="Leadership reflection",
            body="Work was work.",
        )

        resolution = self._article_resolver()(article)
        outcome = validate_rewrite(article)
        strong = resolve_article_entities(
            "Ascot result",
            "Work won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )
        coreference = resolve_article_entities(
            "Ascot result",
            "Work was work. The horse won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )

        payloads = self._entities_for(resolution, "Work")
        self.assertEqual(len(payloads), 2, payloads)
        for payload in payloads:
            self.assertIn(payload["classification"], {"common_word", "uncertain"}, payload)
            self.assertFalse(payload["needs_preserve"], payload)
        self.assertFalse(
            any(issue["code"] in HORSE_ISSUE_CODES for issue in outcome.issues),
            outcome.issues,
        )
        strong_payload = self._entities_for(strong, "Work")[0]
        self.assertOccurrence(
            strong_payload,
            classification="confirmed_horse",
            needs_preserve=False,
        )
        coreference_payload = self._entities_for(coreference, "Work")[0]
        self.assertOccurrence(
            coreference_payload,
            classification="confirmed_horse",
            needs_preserve=False,
        )
        self.assertEqual(
            coreference_payload["reason"],
            "proper_name_copular_adjective_contrast",
        )

    def test_external_alias_repeated_copula_phrase_is_not_horse_context(self):
        self._external_alias("Work", external_id="sl-repeated-copula")
        article = self._article(
            source_article_id="alias-repeated-copula",
            title="Leadership reflection",
            body="Work was work.",
        )

        resolution = self._article_resolver()(article)
        outcome = validate_rewrite(article)

        payloads = self._entities_for(resolution, "Work")
        self.assertEqual(len(payloads), 2, payloads)
        for payload in payloads:
            self.assertIn(payload["classification"], {"common_word", "uncertain"}, payload)
            self.assertFalse(payload["needs_preserve"], payload)
        self.assertFalse(
            any(issue["code"] in HORSE_ISSUE_CODES for issue in outcome.issues),
            outcome.issues,
        )
        self.assertNotEqual(payloads[0]["matched_span"], payloads[1]["matched_span"])

    def test_pending_and_alias_bare_is_strong_are_not_horse_context_but_win_is_confirmed(self):
        term = self._pending_term("Work")
        alias = self._external_alias(
            "Work",
            external_id="sl-bare-is-strong",
        )
        article = self._article(
            source_article_id="pending-alias-bare-is-strong",
            title="Leadership reflection",
            body=(
                "Work is strong across the team. "
                "Work is strong."
            ),
        )

        resolution = self._article_resolver()(article)
        outcome = validate_rewrite(article)
        payloads = self._entities_for(resolution, "Work")

        self.assertEqual(len(payloads), 2, payloads)
        for payload in payloads:
            self.assertIn(
                payload["classification"],
                {"common_word", "uncertain"},
                payload,
            )
            self.assertFalse(payload["needs_preserve"], payload)
            self.assertEqual(payload["term_id"], term.id)
            self.assertEqual(
                payload["external_horse_ids"],
                [alias.external_horse_id],
            )
        self.assertFalse(
            any(issue["code"] in HORSE_ISSUE_CODES for issue in outcome.issues),
            outcome.issues,
        )

        strong = resolve_article_entities(
            "Ascot result",
            "Work won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )
        strong_payload = self._entities_for(strong, "Work")[0]
        self.assertOccurrence(
            strong_payload,
            classification="confirmed_horse",
            needs_preserve=True,
        )

    def test_translated_formal_bare_is_strong_is_not_horse_context(self):
        term = self._translated_term("Work", "工作")
        article = self._article(
            source_article_id="translated-formal-bare-is-strong",
            title="Leadership reflection",
            body=(
                "Work is strong across the team. "
                "Work is strong."
            ),
        )

        resolution = self._article_resolver()(article)
        outcome = validate_rewrite(article)
        payloads = self._entities_for(resolution, "Work")

        self.assertEqual(len(payloads), 2, payloads)
        for payload in payloads:
            self.assertIn(
                payload["classification"],
                {"common_word", "uncertain"},
                payload,
            )
            self.assertFalse(payload["needs_preserve"], payload)
            self.assertEqual(payload["term_id"], term.id)
        self.assertFalse(
            any(
                issue["code"] in {"core_term_missing", "background_term_missing"}
                and (issue.get("payload") or {}).get("term_id") == term.id
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_unknown_horse_placeholders_only_protect_confirmed_occurrence_spans(self):
        for source in ("pending", "external_alias"):
            with self.subTest(source=source):
                TermEntry.objects.all().delete()
                ExternalHorseAlias.objects.all().delete()
                if source == "pending":
                    self._pending_term("Brilliant")
                else:
                    self._external_alias("Brilliant", external_id="sl-translation-span")
                article = self._article(
                    source_article_id=f"translation-placeholder-span-{source}",
                    title="Ascot result",
                    body=(
                        "Brilliant won at Ascot under Ryan Moore. "
                        "The team also produced a Brilliant performance."
                    ),
                )
                resolution = self._article_resolver()(article)
                provider = OpenAICompatibleTranslationProvider(
                    api_key="test",
                    base_url="https://example.com/v1",
                )
                protected_sources = []

                def echo_protected_source(messages):
                    prompt = messages[-1]["content"]
                    protected_title = prompt.split("原文标题：", 1)[1].split("\n\n原文正文：", 1)[0]
                    protected_body = prompt.split("原文正文：\n", 1)[1]
                    protected_sources.append(protected_body)
                    return _fake_translation_response(
                        {
                            "title_zh": protected_title,
                            "body_zh": protected_body,
                            "push_summary_zh": "",
                        }
                    )

                with patch.object(provider, "_request_completion", side_effect=echo_protected_source):
                    provider.translate(article, entity_resolution=resolution)

                self.assertEqual(protected_sources[0].count("__UMA_KEEP_1__"), 1)
                self.assertIn("a Brilliant performance", protected_sources[0])

    def test_nested_confirmed_external_aliases_protect_only_longest_complete_horse_name(self):
        self._external_alias(
            "International Star",
            external_id="sl-nested-international-star",
        )
        self._external_alias(
            "Star",
            external_id="sl-nested-star",
        )
        source_body = "International Star won at Ascot under Ryan Moore."
        article = self._article(
            source_article_id="translation-nested-external-alias-placeholder",
            title="Ascot result",
            body=source_body,
        )
        resolution = self._article_resolver()(article)
        confirmed = [
            item.as_dict()
            for item in resolution.entities
            if item.classification == "confirmed_horse"
            and item.matched_text in {"International Star", "Star"}
        ]
        self.assertEqual(
            {item["matched_text"] for item in confirmed},
            {"International Star", "Star"},
            resolution.as_dict(),
        )
        provider = OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        protected_bodies = []

        def echo_protected_source(messages):
            prompt = messages[-1]["content"]
            protected_title = prompt.split("原文标题：", 1)[1].split(
                "\n\n原文正文：",
                1,
            )[0]
            protected_body = prompt.split("原文正文：\n", 1)[1]
            protected_bodies.append(protected_body)
            return _fake_translation_response(
                {
                    "title_zh": protected_title,
                    "body_zh": protected_body,
                    "push_summary_zh": "",
                }
            )

        with patch.object(
            provider,
            "_request_completion",
            side_effect=echo_protected_source,
        ):
            result = provider.translate(
                article,
                entity_resolution=resolution,
            )

        self.assertEqual(
            result.metadata["unknown_horse_placeholders"],
            {"__UMA_KEEP_1__": "International Star"},
        )
        self.assertIn(
            "__UMA_KEEP_1__ won at Ascot",
            protected_bodies[0],
        )
        self.assertNotIn("__UMA_KEEP_2__", protected_bodies[0])
        self.assertEqual(result.body_zh, source_body)

    def test_translated_formal_mapping_only_replaces_confirmed_occurrence_span(self):
        self._translated_term("Brilliant", "辉煌")
        body = (
            "Brilliant won at Ascot under Ryan Moore. "
            "The team also produced a Brilliant performance."
        )
        resolution = resolve_article_entities(
            "Ascot result",
            body,
            source_language=SourceLanguage.ENGLISH,
        )

        mapped = apply_contextual_term_mappings(body, resolution)

        self.assertEqual(
            mapped,
            "辉煌 won at Ascot under Ryan Moore. The team also produced a Brilliant performance.",
        )

    def test_validation_requires_the_confirmed_occurrence_to_be_preserved(self):
        self._pending_term("Brilliant")
        source_body = (
            "Brilliant won at Ascot under Ryan Moore. "
            "The team also produced a Brilliant performance."
        )
        missing_confirmed = self._article(
            source_article_id="validation-occurrence-missing",
            body=source_body,
            translated_body_zh=(
                "报道省略了获胜马匹对应的句子。团队也交出了一场 Brilliant performance。"
                "其余赛事背景和后续计划均已完整说明。"
            )
            * 3,
            body_zh=(
                "报道省略了获胜马匹对应的句子。团队也交出了一场 Brilliant performance。"
                "其余赛事背景和后续计划均已完整说明。"
            )
            * 3,
        )
        preserved_confirmed = self._article(
            source_article_id="validation-occurrence-preserved",
            body=source_body,
            translated_body_zh=(
                "Brilliant won at Ascot under Ryan Moore。团队也交出了一场精彩表现。"
                "其余赛事背景和后续计划均已完整说明。"
            )
            * 3,
            body_zh=(
                "Brilliant won at Ascot under Ryan Moore。团队也交出了一场精彩表现。"
                "其余赛事背景和后续计划均已完整说明。"
            )
            * 3,
        )

        missing_outcome = validate_rewrite(missing_confirmed)
        preserved_outcome = validate_rewrite(preserved_confirmed)

        self.assertTrue(
            any(issue["code"] == "pending_horse_original_missing" for issue in missing_outcome.issues),
            missing_outcome.issues,
        )
        self.assertFalse(
            any(issue["code"] == "pending_horse_original_missing" for issue in preserved_outcome.issues),
            preserved_outcome.issues,
        )

    def test_pending_horse_valid_chinese_racing_relations_preserve_confirmed_occurrence(self):
        self._pending_term("Brilliant")
        valid_translations = (
            "Brilliant赢得了比赛。",
            "Brilliant获胜。",
            "Brilliant将参赛。",
            "Brilliant复出。",
            "Brilliant由莫雅策骑。",
            "Brilliant由约翰训练。",
        )

        for index, translated_sentence in enumerate(valid_translations):
            with self.subTest(translated_sentence=translated_sentence):
                translated_body = translated_sentence + "其余赛事背景与后续计划均已完整说明。" * 8
                article = self._article(
                    source_article_id=f"pending-chinese-preserved-{index}",
                    body="Brilliant won at Ascot.",
                    translated_body_zh=translated_body,
                    body_zh=translated_body,
                )

                outcome = validate_rewrite(article)

                self.assertFalse(
                    any(
                        issue["code"] == "pending_horse_original_missing"
                        for issue in outcome.issues
                    ),
                    outcome.issues,
                )

    def test_external_alias_valid_chinese_racing_relations_preserve_confirmed_occurrence(self):
        self._external_alias("Brilliant", external_id="sl-chinese-preserved")
        valid_translations = (
            "Brilliant赢得了比赛。",
            "Brilliant获胜。",
            "Brilliant将参赛。",
            "Brilliant复出。",
            "Brilliant由莫雅策骑。",
            "Brilliant由约翰训练。",
        )

        for index, translated_sentence in enumerate(valid_translations):
            with self.subTest(translated_sentence=translated_sentence):
                translated_body = translated_sentence + "其余赛事背景与后续计划均已完整说明。" * 8
                article = self._article(
                    source_article_id=f"alias-chinese-preserved-{index}",
                    body="Brilliant won at Ascot.",
                    translated_body_zh=translated_body,
                    body_zh=translated_body,
                )

                outcome = validate_rewrite(article)

                self.assertFalse(
                    any(
                        issue["code"] == "external_horse_not_preserved"
                        for issue in outcome.issues
                    ),
                    outcome.issues,
                )

    def test_chinese_ordinary_occurrence_does_not_mask_confirmed_source_horse(self):
        self._pending_term("Brilliant")
        translated_body = (
            "团队今天交出了一场 Brilliant表现，但译文删除了获胜马匹对应的句子。"
            "其余赛事背景与后续计划均已完整说明。"
        ) * 5
        article = self._article(
            source_article_id="pending-chinese-ordinary-mask",
            body=(
                "Brilliant won at Ascot. "
                "The team also produced a Brilliant performance."
            ),
            translated_body_zh=translated_body,
            body_zh=translated_body,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(
            any(
                issue["code"] == "pending_horse_original_missing"
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_html_source_offsets_protect_only_visible_confirmed_placeholder_span(self):
        self._pending_term("Brilliant")
        hidden = self._external_alias("Hidden Runner", external_id="sl-html-hidden")
        raw_body = (
            "<nav>Hidden Runner won at Ascot.</nav>"
            "<p>Brilliant won at Ascot. The team produced a Brilliant performance.</p>"
            "<aside>Hidden Runner finished second.</aside>"
        )
        article = self._article(
            source_article_id="translation-html-placeholder-span",
            title="Ascot result",
            body=raw_body,
        )
        resolution = self._article_resolver()(article)
        provider = OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        protected_sources = []

        def echo_protected_source(messages):
            prompt = messages[-1]["content"]
            protected_title = prompt.split("原文标题：", 1)[1].split("\n\n原文正文：", 1)[0]
            protected_body = prompt.split("原文正文：\n", 1)[1]
            protected_sources.append(protected_body)
            return _fake_translation_response(
                {
                    "title_zh": protected_title,
                    "body_zh": protected_body,
                    "push_summary_zh": "",
                }
            )

        with patch.object(provider, "_request_completion", side_effect=echo_protected_source):
            provider.translate(article, entity_resolution=resolution)

        protected = protected_sources[0]
        self.assertEqual(protected.count("__UMA_KEEP_1__"), 1)
        self.assertIn("a Brilliant performance", protected)
        self.assertEqual(protected.count(hidden.name_en), 2)

    def test_html_source_offsets_map_only_visible_confirmed_formal_span(self):
        self._translated_term("Brilliant", "辉煌")
        raw_body = (
            "<nav>Brilliant navigation label.</nav>"
            "<p>Brilliant won at Ascot. The team produced a Brilliant performance.</p>"
            "<aside>Brilliant sidebar label.</aside>"
        )
        article = self._article(
            source_article_id="translation-html-mapping-span",
            title="Ascot result",
            body=raw_body,
        )
        resolution = self._article_resolver()(article)

        result = DummyTranslationProvider().translate(article, entity_resolution=resolution)

        self.assertIn("<nav>Brilliant navigation label.</nav>", result.body_zh)
        self.assertIn("<p>辉煌 won at Ascot. The team produced a Brilliant performance.</p>", result.body_zh)
        self.assertIn("<aside>Brilliant sidebar label.</aside>", result.body_zh)

    def test_rewrite_maps_provable_generated_occurrence_without_source_span_indexing(self):
        self._translated_term("Brilliant", "辉煌")
        article = self._article(
            source_article_id="rewrite-generated-occurrence-span",
            title="Ascot result",
            body=(
                "Brilliant won at Ascot under Ryan Moore. "
                "The team also produced a Brilliant performance."
            ),
            translated_title_zh="雅士谷赛果",
            title_zh="雅士谷赛果",
            translated_body_zh="基础翻译正文。",
            body_zh="基础翻译正文。",
        )
        resolution = self._article_resolver()(article)
        provider = OpenAICompatibleRewriteProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        response = _fake_translation_response(
            {
                "rewrite_title_zh": "雅士谷赛果",
                "rewrite_summary_zh": "报道指出 Brilliant won at Ascot。",
                "rewrite_body_zh": (
                    "报道指出，Brilliant won at Ascot。"
                    "团队也交出了一场 Brilliant performance。"
                ),
                "rewrite_confidence": 90,
            }
        )

        with patch.object(provider.client.chat.completions, "create", return_value=response):
            result = provider.rewrite(article, entity_resolution=resolution)

        self.assertEqual(
            result.body_zh,
            "报道指出，辉煌 won at Ascot。团队也交出了一场 Brilliant performance。",
        )

    def _assert_rewrite_provider_occurrence_safe_placeholders(
        self,
        article: NewsArticle,
    ):
        resolution = self._article_resolver()(article)
        provider = OpenAICompatibleRewriteProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        prompts = []

        def reordered_response(**kwargs):
            prompt = kwargs["messages"][-1]["content"]
            prompts.append(prompt)
            protected_title = prompt.split(
                "原文标题：",
                1,
            )[1].split("\n基准中文标题：", 1)[0]
            protected_body = prompt.split(
                "原文正文：\n",
                1,
            )[1].split("\n\n基准中文翻译：", 1)[0]
            self.assertEqual(
                protected_title,
                "Brilliant performance review",
            )
            self.assertNotIn("__UMA_KEEP_", protected_title)
            self.assertEqual(protected_body.count("__UMA_KEEP_1__"), 1)
            self.assertIn(
                "The team delivered a Brilliant performance.",
                protected_body,
            )
            return _fake_translation_response(
                {
                    "rewrite_title_zh": "Brilliant performance review",
                    "rewrite_summary_zh": "团队交出 Brilliant performance。",
                    "rewrite_body_zh": (
                        "团队先交出 a Brilliant performance。"
                        "随后 __UMA_KEEP_1__ won at Ascot。"
                    ),
                    "rewrite_confidence": 91,
                }
            )

        with patch.object(
            provider.client.chat.completions,
            "create",
            side_effect=reordered_response,
        ):
            result = provider.rewrite(
                article,
                entity_resolution=resolution,
            )

        self.assertEqual(len(prompts), 1)
        self.assertEqual(
            result.title_zh,
            "Brilliant performance review",
        )
        self.assertEqual(
            result.summary_zh,
            "团队交出 Brilliant performance。",
        )
        self.assertEqual(
            result.body_zh,
            (
                "团队先交出 a Brilliant performance。"
                "随后 Brilliant won at Ascot。"
            ),
        )

    def test_rewrite_provider_pending_formal_placeholders_only_confirmed_source_occurrence(self):
        self._pending_term("Brilliant")
        article = self._article(
            source_article_id="rewrite-pending-occurrence-placeholder",
            title="Brilliant performance review",
            body=(
                "Brilliant won at Ascot. "
                "The team delivered a Brilliant performance."
            ),
        )

        self._assert_rewrite_provider_occurrence_safe_placeholders(article)

    def test_rewrite_provider_alias_only_placeholders_only_confirmed_source_occurrence(self):
        self._external_alias(
            "Brilliant",
            external_id="sl-rewrite-occurrence-placeholder",
        )
        article = self._article(
            source_article_id="rewrite-alias-occurrence-placeholder",
            title="Brilliant performance review",
            body=(
                "Brilliant won at Ascot. "
                "The team delivered a Brilliant performance."
            ),
        )

        self._assert_rewrite_provider_occurrence_safe_placeholders(article)

    def test_translated_horse_target_in_ordinary_chinese_context_does_not_mask_missing(self):
        term = self._translated_term("Brilliant", "辉煌")
        translated_body = (
            "团队表现辉煌，但译文删除了获胜马匹对应的句子。"
            "其余赛事背景、参赛安排和后续计划均已完整说明。"
        ) * 6
        article = self._article(
            source_article_id="translated-target-ordinary-mask",
            title="Ascot result",
            body=(
                "Brilliant won at Ascot. "
                "The team also produced a brilliant performance."
            ),
            translated_body_zh=translated_body,
            body_zh=translated_body,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(
            any(
                issue["code"] in {"core_term_missing", "background_term_missing"}
                and (issue.get("payload") or {}).get("term_id") == term.id
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_confirmed_source_accepts_exact_formal_chinese_target_mention(self):
        term = self._translated_term("Logician", "逻辑学家")
        term.aliases_zh = ["逻辑大师"]
        term.save(update_fields=["aliases_zh", "updated_at"])

        for index, exact_mention in enumerate(
            ("焦点转向逻辑学家。", "焦点转向逻辑大师。"),
            start=1,
        ):
            with self.subTest(exact_mention=exact_mention):
                translated_body = (
                    exact_mention
                    + "报道完整交代了赛事背景、参赛安排、赛后评价和后续计划。"
                    * 8
                )
                article = self._article(
                    source_article_id=f"translated-target-exact-mention-{index}",
                    title="Stallion update",
                    body="Logician won at Doncaster.",
                    translated_body_zh=translated_body,
                    body_zh=translated_body,
                )

                outcome = validate_rewrite(article)

                missing = [
                    issue
                    for issue in outcome.issues
                    if issue["code"]
                    in {"core_term_missing", "background_term_missing"}
                    and (issue.get("payload") or {}).get("term_id") == term.id
                ]
                self.assertEqual(missing, [], outcome.issues)

    def test_confirmed_source_does_not_accept_chinese_target_substring(self):
        term = self._translated_term("Logician", "逻辑学家")
        translated_body = (
            "文章讨论逻辑学家族的历史，但译文删除了获胜马匹对应的句子。"
            "其余赛事背景、参赛安排、赛后评价和后续计划均已完整说明。"
            * 8
        )
        article = self._article(
            source_article_id="translated-target-substring-only",
            title="Stallion update",
            body="Logician won at Doncaster.",
            translated_body_zh=translated_body,
            body_zh=translated_body,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(
            any(
                issue["code"] in {"core_term_missing", "background_term_missing"}
                and (issue.get("payload") or {}).get("term_id") == term.id
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_translated_horse_target_and_alias_require_generated_horse_context(self):
        from stable.services import validation

        term = self._translated_term("Brilliant", "辉煌")
        term.aliases_zh = ["璀璨"]
        term.save(update_fields=["aliases_zh", "updated_at"])
        original_shared_decision = (
            validation.english_horse_name_has_confirmed_occurrence
        )
        cases = (
            ("辉煌获胜。", True),
            ("辉煌获得亚军。", True),
            ("本场冠军是辉煌。", True),
            ("璀璨获胜。", True),
            ("团队表现辉煌。", False),
            ("团队表现璀璨。", False),
        )

        for index, (generated, should_preserve) in enumerate(cases, start=1):
            with self.subTest(generated=generated):
                translated_body = (
                    generated
                    + "报道完整交代了赛事背景、参赛安排、赛后评价和后续计划。"
                    * 8
                )
                article = self._article(
                    source_article_id=f"translated-target-context-{index}",
                    title="Ascot result",
                    body="Brilliant won at Ascot.",
                    translated_body_zh=translated_body,
                    body_zh=translated_body,
                )
                with patch(
                    "stable.services.validation.english_horse_name_has_confirmed_occurrence",
                    wraps=original_shared_decision,
                ) as shared_decision:
                    outcome = validate_rewrite(article)

                candidate_calls = [
                    list(call.args[1])
                    for call in shared_decision.call_args_list
                    if len(call.args) >= 2
                ]
                self.assertTrue(
                    any(
                        "辉煌" in names and "璀璨" in names
                        for names in candidate_calls
                    ),
                    candidate_calls,
                )
                missing = [
                    issue
                    for issue in outcome.issues
                    if issue["code"]
                    in {"core_term_missing", "background_term_missing"}
                    and (issue.get("payload") or {}).get("term_id") == term.id
                ]
                if should_preserve:
                    self.assertEqual(missing, [], outcome.issues)
                else:
                    self.assertTrue(missing, outcome.issues)

    def test_translation_workflow_does_not_map_reordered_ordinary_occurrence_by_source_ordinal(self):
        self._translated_term("Brilliant", "辉煌")
        article = self._article(
            source_article_id="translation-generated-ordinary-only",
            title="Ascot result",
            body=(
                "Brilliant won at Ascot under Ryan Moore. "
                "The team later produced a Brilliant performance."
            ),
        )
        provider = OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        response = _fake_translation_response(
            {
                "title_zh": "雅士谷赛后报道",
                "body_zh": (
                    "Brilliant performance体现了团队的专业工作，"
                    "但这段译文没有保留获胜马匹对应的句子。赛事背景和后续安排均已说明。"
                ),
                "push_summary_zh": "团队交出 Brilliant performance。",
            }
        )

        with (
            patch("stable.services.translation.get_translation_provider", return_value=provider),
            patch.object(provider, "_request_completion", return_value=response),
        ):
            result = translate_article(article)

        self.assertIn("Brilliant performance", result.body_zh)
        self.assertNotIn("辉煌 performance", result.body_zh)
        article.translated_title_zh = result.title_zh
        article.title_zh = result.title_zh
        article.translated_body_zh = result.body_zh
        article.body_zh = result.body_zh
        article.translated_summary_zh = result.push_summary_zh
        article.summary_zh = result.push_summary_zh
        article.save()

        outcome = validate_rewrite(article)

        self.assertTrue(
            any(
                issue["code"] in {"core_term_missing", "background_term_missing"}
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_translation_workflow_maps_only_generated_occurrence_with_its_own_horse_context(self):
        self._translated_term("Brilliant", "辉煌")
        article = self._article(
            source_article_id="translation-generated-confirmed-and-ordinary",
            title="Ascot result",
            body=(
                "Brilliant won at Ascot under Ryan Moore. "
                "The team later produced a Brilliant performance."
            ),
        )
        provider = OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        response = _fake_translation_response(
            {
                "title_zh": "雅士谷赛后报道",
                "body_zh": (
                    "报道重排了段落：Brilliant won at Ascot。"
                    "团队随后交出了一场 Brilliant performance，赛事背景和后续安排均已说明。"
                ),
                "push_summary_zh": "Brilliant won at Ascot。",
            }
        )

        with (
            patch("stable.services.translation.get_translation_provider", return_value=provider),
            patch.object(provider, "_request_completion", return_value=response),
        ):
            result = translate_article(article)

        self.assertEqual(
            result.body_zh,
            (
                "报道重排了段落：辉煌 won at Ascot。"
                "团队随后交出了一场 Brilliant performance，赛事背景和后续安排均已说明。"
            ),
        )
        self.assertEqual(result.push_summary_zh, "辉煌 won at Ascot。")

    def test_validation_rejects_formal_horse_preservation_by_ordinary_generated_occurrence(self):
        self._translated_term("Brilliant", "辉煌")
        translated_body = (
            "团队交出了一场 Brilliant performance，"
            "但译文删除了获胜马匹对应的句子。赛事背景和后续安排均已说明。"
        ) + "报道还完整交代了赛事筹备、人员安排和后续计划。" * 5
        article = self._article(
            source_article_id="validation-formal-generated-ordinary-only",
            title="Ascot result",
            body=(
                "Brilliant won at Ascot under Ryan Moore. "
                "The team later produced a Brilliant performance."
            ),
            translated_title_zh="雅士谷赛后报道",
            title_zh="雅士谷赛后报道",
            translated_body_zh=translated_body,
            body_zh=translated_body,
            translated_summary_zh="团队赛后表现。",
            summary_zh="团队赛后表现。",
        )

        outcome = validate_rewrite(article)

        self.assertTrue(
            any(
                issue["code"] in {"core_term_missing", "background_term_missing"}
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_generated_chinese_horse_relations_share_mapping_and_validation_semantics(self):
        self._translated_term("Brilliant", "辉煌")
        resolution = resolve_article_entities(
            "Ascot result",
            "Brilliant won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )
        confirmed_cases = (
            "Brilliant获胜。",
            "Brilliant赢得比赛。",
            "Brilliant参赛。",
            "Brilliant复出。",
            "Brilliant由莫雅策骑。",
            "Brilliant由约翰训练。",
            "Brilliant在沙田取胜。",
        )

        for generated in confirmed_cases:
            with self.subTest(generated=generated):
                self.assertEqual(
                    apply_generated_text_contextual_mappings(generated, resolution),
                    generated.replace("Brilliant", "辉煌", 1),
                )
                self.assertTrue(
                    english_horse_name_has_confirmed_occurrence(
                        generated,
                        ["Brilliant"],
                    )
                )

        ordinary = "团队交出了一场 Brilliant表现。"
        self.assertEqual(
            apply_generated_text_contextual_mappings(ordinary, resolution),
            ordinary,
        )
        self.assertFalse(
            english_horse_name_has_confirmed_occurrence(
                ordinary,
                ["Brilliant"],
            )
        )

    def test_generated_mapping_and_validation_call_the_same_public_occurrence_decision(self):
        from stable.services import terms

        classifier = getattr(
            terms,
            "classify_generated_horse_occurrence",
            None,
        )
        self.assertIsNotNone(
            classifier,
            "缺少 mapping/validation 共用的公开 generated occurrence decision",
        )
        self._translated_term("Brilliant", "辉煌")
        resolution = resolve_article_entities(
            "Ascot result",
            "Brilliant won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )
        generated = "Brilliant在沙田取胜。团队交出了一场 Brilliant表现。"

        with patch(
            "stable.services.terms.classify_generated_horse_occurrence",
            wraps=classifier,
        ) as shared_decision:
            mapped = apply_generated_text_contextual_mappings(generated, resolution)
            preserved = english_horse_name_has_confirmed_occurrence(
                generated,
                ["Brilliant"],
            )

        self.assertEqual(
            mapped,
            "辉煌在沙田取胜。团队交出了一场 Brilliant表现。",
        )
        self.assertTrue(preserved)
        self.assertGreaterEqual(shared_decision.call_count, 3)

    def test_generated_chinese_result_relations_share_mapping_and_validation_semantics(self):
        from stable.services import terms

        classifier = getattr(
            terms,
            "classify_generated_horse_occurrence",
            None,
        )
        self.assertIsNotNone(classifier)
        self._translated_term("Brilliant", "辉煌")
        self._external_alias("Brilliant", external_id="sl-generated-result")
        resolution = resolve_article_entities(
            "Ascot result",
            "Brilliant won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )
        confirmed_cases = (
            "Brilliant获得亚军。",
            "Brilliant获得冠军。",
            "Brilliant获得季军。",
            "Brilliant名列第二。",
            "Brilliant跑获第三。",
            "本场冠军是Brilliant。",
        )

        with patch(
            "stable.services.terms.classify_generated_horse_occurrence",
            wraps=classifier,
        ) as shared_decision:
            for generated in confirmed_cases:
                with self.subTest(generated=generated):
                    self.assertEqual(
                        apply_generated_text_contextual_mappings(
                            generated,
                            resolution,
                        ),
                        generated.replace("Brilliant", "辉煌", 1),
                    )
                    self.assertTrue(
                        english_horse_name_has_confirmed_occurrence(
                            generated,
                            ["Brilliant"],
                        )
                    )

        self.assertGreaterEqual(
            shared_decision.call_count,
            len(confirmed_cases) * 2,
        )
        for ordinary in (
            "Brilliant获得支持。",
            "冠军是Brilliant表现。",
        ):
            with self.subTest(ordinary=ordinary):
                self.assertEqual(
                    apply_generated_text_contextual_mappings(
                        ordinary,
                        resolution,
                    ),
                    ordinary,
                )
                self.assertFalse(
                    english_horse_name_has_confirmed_occurrence(
                        ordinary,
                        ["Brilliant"],
                    )
                )

    def test_pending_alias_validation_accepts_chinese_result_relations_but_not_ordinary_phrases(self):
        term = self._pending_term("Brilliant")
        alias = self._external_alias(
            "Brilliant",
            external_id="sl-pending-generated-result",
        )
        cases = (
            ("Brilliant获得亚军。", True),
            ("本场冠军是Brilliant。", True),
            ("Brilliant获得支持。", False),
            ("冠军是Brilliant表现。", False),
        )

        for index, (generated, should_preserve) in enumerate(cases, start=1):
            with self.subTest(generated=generated):
                translated_body = (
                    generated
                    + "报道完整交代了赛事背景、参赛安排、赛后评价和后续计划。"
                    * 8
                )
                article = self._article(
                    source_article_id=f"pending-chinese-result-{index}",
                    title="Ascot result",
                    body="Brilliant won at Ascot.",
                    translated_body_zh=translated_body,
                    body_zh=translated_body,
                )

                outcome = validate_rewrite(article)
                horse_issues = [
                    issue
                    for issue in outcome.issues
                    if issue["code"] in HORSE_ISSUE_CODES
                    and (
                        (issue.get("payload") or {}).get("term_id") == term.id
                        or alias.external_horse_id
                        in (
                            (issue.get("payload") or {}).get(
                                "external_horse_ids",
                                [],
                            )
                        )
                        or "Brilliant" in str(issue.get("payload") or {})
                    )
                ]

                if should_preserve:
                    self.assertEqual(horse_issues, [], outcome.issues)
                else:
                    self.assertTrue(horse_issues, outcome.issues)

    def test_translation_workflow_pending_placeholder_remains_occurrence_safe_after_reordering(self):
        self._pending_term("Brilliant")
        article = self._article(
            source_article_id="translation-generated-pending-placeholder",
            title="Ascot result",
            body=(
                "Brilliant won at Ascot under Ryan Moore. "
                "The team later produced a Brilliant performance."
            ),
        )
        provider = OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )
        response = _fake_translation_response(
            {
                "title_zh": "雅士谷赛后报道",
                "body_zh": (
                    "团队交出了一场 Brilliant performance。"
                    "__UMA_KEEP_1__赢得了比赛，赛事背景和后续安排均已说明。"
                ),
                "push_summary_zh": "__UMA_KEEP_1__赢得了比赛。",
            }
        )

        with (
            patch("stable.services.translation.get_translation_provider", return_value=provider),
            patch.object(provider, "_request_completion", return_value=response),
        ):
            result = translate_article(article)

        self.assertEqual(result.body_zh.count("Brilliant"), 2)
        self.assertIn("Brilliant performance", result.body_zh)
        self.assertIn("Brilliant赢得了比赛", result.body_zh)

    def test_title_case_alias_only_match_is_uncertain_audit_not_warning(self):
        alias = self._external_alias("Brilliant Result", external_id="sl-title-case")
        article = self._article(
            title="Brilliant Result Announced",
            body="Officials published the result after a routine administrative review.",
        )

        outcome = validate_rewrite(article)

        payload = next(
            item
            for item in outcome.details.get("article_entities", [])
            if item.get("matched_text") == "Brilliant Result"
        )
        self.assertOccurrence(payload, classification="uncertain", needs_preserve=False)
        self.assertEqual(payload["external_horse_ids"], [alias.external_horse_id])
        audit_issues = [
            issue
            for issue in outcome.issues
            if (issue.get("payload") or {}).get("classification") == "uncertain"
        ]
        self.assertTrue(audit_issues, outcome.details)
        self.assertTrue(all(issue.get("severity") == "info" for issue in audit_issues), audit_issues)
        self.assertEqual(warning_signature(audit_issues), "")

        article.gate_issues = audit_issues
        article.save(update_fields=["gate_issues", "updated_at"])
        with patch("stable.services.notifications.send_mail") as mocked_send_mail:
            self.assertEqual(send_high_value_warning_notification(article), [])
        mocked_send_mail.assert_not_called()
        self.assertFalse(NotificationLog.objects.filter(type=NotificationType.HIGH_VALUE_WARNING).exists())

    def test_pending_formal_title_case_match_is_also_uncertain_info(self):
        term = self._pending_term("Brilliant Result")
        article = self._article(
            title="Brilliant Result Announced",
            body="Officials published the result after a routine administrative review.",
        )

        outcome = validate_rewrite(article)

        payload = next(
            item for item in outcome.details["article_entities"] if item.get("term_id") == term.id
        )
        self.assertOccurrence(payload, classification="uncertain", needs_preserve=False)
        term_issues = [
            issue for issue in outcome.issues if (issue.get("payload") or {}).get("term_id") == term.id
        ]
        self.assertTrue(term_issues)
        self.assertTrue(all(issue["severity"] == "info" for issue in term_issues), term_issues)
        self.assertFalse({issue["code"] for issue in term_issues} & HORSE_ISSUE_CODES)

    def _machine_link_profile(self, term: TermEntry) -> HorseProfile:
        return HorseProfile.objects.create(
            primary_term=term,
            display_name_zh=term.target_zh or term.source_ja,
            original_name=term.source_ja,
            english_name=term.source_ja,
            racing_region=RacingRegion.UNITED_KINGDOM,
            review_status=HorseProfileStatus.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_uncertain_horse_occurrence_with_machine_link_is_audit_only(self):
        term = self._pending_term("Brilliant Result")
        profile = self._machine_link_profile(term)

        for status in (
            ArticleHorseLinkStatus.AUTO,
            ArticleHorseLinkStatus.CANDIDATE,
        ):
            with self.subTest(status=status):
                article = self._article(
                    source_article_id=f"uncertain-machine-link-{status}",
                    title="Administrative update",
                    body=(
                        "Officials mentioned Brilliant Result during an "
                        "administrative review."
                    ),
                )
                ArticleHorseLink.objects.create(
                    article=article,
                    horse_profile=profile,
                    status=status,
                    source="machine_test",
                    confidence=80,
                    matched_text="Brilliant Result",
                )

                outcome = validate_rewrite(article)
                entity = next(
                    item
                    for item in outcome.details["article_entities"]
                    if item.get("term_id") == term.id
                )
                self.assertOccurrence(
                    entity,
                    classification="uncertain",
                    needs_preserve=False,
                )
                self.assertFalse(
                    any(
                        issue["code"] == "machine_entity_type_mismatch"
                        for issue in outcome.issues
                    ),
                    outcome.issues,
                )
                uncertain_issues = [
                    issue
                    for issue in outcome.issues
                    if issue["code"] == "english_horse_occurrence_uncertain"
                    and (issue.get("payload") or {}).get("term_id") == term.id
                ]
                self.assertTrue(uncertain_issues, outcome.issues)
                self.assertTrue(
                    all(
                        issue["severity"] == "info"
                        for issue in uncertain_issues
                    ),
                    uncertain_issues,
                )

    def test_common_word_machine_link_still_mismatches_and_confirmed_does_not(self):
        common_term = self._translated_term("Agenda", "议程")
        common_profile = self._machine_link_profile(common_term)
        common_article = self._article(
            source_article_id="common-machine-link-mismatch",
            title="Business update",
            body="The agenda for the company meeting covered staffing.",
        )
        ArticleHorseLink.objects.create(
            article=common_article,
            horse_profile=common_profile,
            status=ArticleHorseLinkStatus.AUTO,
            source="machine_test",
            confidence=80,
            matched_text="agenda",
        )

        common_outcome = validate_rewrite(common_article)

        mismatch = [
            issue
            for issue in common_outcome.issues
            if issue["code"] == "machine_entity_type_mismatch"
        ]
        self.assertTrue(mismatch, common_outcome.issues)
        self.assertIn(
            common_term.id,
            mismatch[0]["payload"]["auto_link_term_ids"],
        )

        confirmed_term = self._pending_term("Work")
        confirmed_profile = self._machine_link_profile(confirmed_term)
        confirmed_article = self._article(
            source_article_id="confirmed-machine-link-no-mismatch",
            title="Ascot result",
            body="Work won at Ascot.",
        )
        ArticleHorseLink.objects.create(
            article=confirmed_article,
            horse_profile=confirmed_profile,
            status=ArticleHorseLinkStatus.CANDIDATE,
            source="machine_test",
            confidence=80,
            matched_text="Work",
        )

        confirmed_outcome = validate_rewrite(confirmed_article)
        confirmed_entity = next(
            item
            for item in confirmed_outcome.details["article_entities"]
            if item.get("term_id") == confirmed_term.id
        )
        self.assertOccurrence(
            confirmed_entity,
            classification="confirmed_horse",
            needs_preserve=True,
        )
        self.assertFalse(
            any(
                issue["code"] == "machine_entity_type_mismatch"
                for issue in confirmed_outcome.issues
            ),
            confirmed_outcome.issues,
        )

    def test_person_span_suppressed_horse_candidate_is_explicitly_rejected_for_machine_tag(self):
        term = self._translated_term("Hamilton", "汉密尔顿")
        article = self._article(
            source_article_id="person-span-suppressed-machine-tag",
            title="Grace Hamilton joins Four Star Sales",
            body=(
                "Grace Hamilton has joined Four Star Sales as Bloodstock "
                "and Sales Coordinator."
            ),
            tags_json=["汉密尔顿"],
        )

        resolution = self._article_resolver()(article)
        suppressed = [
            item.as_dict()
            for item in resolution.suppressed_candidates
            if item.term_id == term.id
            and "inside_person_span" in item.conflict_flags
        ]
        self.assertTrue(suppressed, resolution.as_dict())
        self.assertTrue(
            all(
                item["classification"] in {"", "common_word"}
                for item in suppressed
            ),
            suppressed,
        )

        outcome = validate_rewrite(article)

        mismatch = [
            issue
            for issue in outcome.issues
            if issue["code"] == "machine_entity_type_mismatch"
        ]
        self.assertTrue(mismatch, outcome.issues)
        self.assertEqual(mismatch[0]["payload"]["tags"], ["汉密尔顿"])
        self.assertEqual(
            mismatch[0]["payload"]["entity_type"],
            "common_word",
        )

    def test_same_span_merges_formal_term_and_external_identity(self):
        term = self._translated_term("Brilliant", "辉煌")
        alias = self._external_alias("Brilliant", external_id="sl-merged")

        resolution = resolve_article_entities(
            "Ascot declarations",
            "Brilliant won at Ascot under Ryan Moore.",
            source_language=SourceLanguage.ENGLISH,
        )

        payloads = self._entities_for(resolution, "Brilliant")
        self.assertEqual(len(payloads), 1, payloads)
        payload = payloads[0]
        self.assertEqual(payload["term_id"], term.id)
        self.assertEqual(payload["target_zh"], "辉煌")
        self.assertEqual(payload["external_horse_ids"], [alias.external_horse_id])
        self.assertOccurrence(payload, classification="confirmed_horse", needs_preserve=False)

    def test_conflicting_formal_horse_targets_remain_ambiguous_and_are_not_mapped(self):
        first = self._translated_term("Twin Star", "双子星")
        second = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Twin Star",
            target_zh="孪生之星",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=100,
        )
        resolution = resolve_article_entities(
            "Ascot result",
            "Twin Star won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )

        payloads = self._entities_for(resolution, "Twin Star")
        self.assertEqual(len(payloads), 1, payloads)
        payload = payloads[0]
        self.assertOccurrence(
            payload,
            classification="confirmed_horse",
            needs_preserve=True,
        )
        self.assertIsNone(payload["term_id"])
        self.assertEqual(payload["target_zh"], "")
        self.assertIn("ambiguous_formal_horse_name", payload["conflict_flags"])
        ambiguous_targets = {first.target_zh, second.target_zh}
        self.assertFalse(
            ambiguous_targets
            & {term.target_zh for term in resolution.accepted_terms},
            resolution.accepted_terms,
        )
        self.assertEqual(
            apply_generated_text_contextual_mappings(
                "Twin Star won at Ascot.",
                resolution,
            ),
            "Twin Star won at Ascot.",
        )

    def test_single_formal_horse_target_still_maps_generated_strong_occurrence(self):
        term = self._translated_term("Solo Star", "独星")
        resolution = resolve_article_entities(
            "Ascot result",
            "Solo Star won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )

        payload = self._entities_for(resolution, "Solo Star")[0]
        self.assertEqual(payload["term_id"], term.id)
        self.assertEqual(payload["target_zh"], "独星")
        self.assertEqual(
            apply_generated_text_contextual_mappings(
                "Solo Star won at Ascot.",
                resolution,
            ),
            "独星 won at Ascot.",
        )

    def test_pending_formal_and_external_alias_same_span_emit_only_formal_missing_warning(self):
        term = self._pending_term("Brilliant")
        alias = self._external_alias("Brilliant", external_id="sl-formal-precedence")
        article = self._article(
            source_article_id="pending-formal-alias-warning-precedence",
            title="Ascot result",
            body="Brilliant won at Ascot under Ryan Moore.",
        )

        outcome = validate_rewrite(article)

        entity = next(
            item
            for item in outcome.details["article_entities"]
            if item["matched_text"] == "Brilliant"
        )
        self.assertEqual(entity["term_id"], term.id)
        self.assertEqual(entity["external_horse_ids"], [alias.external_horse_id])
        self.assertOccurrence(
            entity,
            classification="confirmed_horse",
            needs_preserve=True,
        )
        horse_issues = [
            issue
            for issue in outcome.issues
            if issue["code"]
            in {"pending_horse_original_missing", "external_horse_not_preserved"}
        ]
        self.assertEqual(
            [issue["code"] for issue in horse_issues],
            ["pending_horse_original_missing"],
            horse_issues,
        )
        recognized = next(
            item
            for item in outcome.details["recognized_horse_names"]
            if item["matched_text"] == "Brilliant"
        )
        self.assertEqual(recognized["source"], "formal_pending_term")
        self.assertEqual(
            recognized["external_horse_ids"],
            [alias.external_horse_id],
        )

    def test_alias_only_confirmed_missing_still_emits_external_warning(self):
        alias = self._external_alias("Brilliant", external_id="sl-alias-only-warning")
        article = self._article(
            source_article_id="alias-only-warning-control",
            title="Ascot result",
            body="Brilliant won at Ascot under Ryan Moore.",
        )

        outcome = validate_rewrite(article)

        entity = next(
            item
            for item in outcome.details["article_entities"]
            if item["matched_text"] == "Brilliant"
        )
        self.assertIsNone(entity["term_id"])
        self.assertEqual(entity["external_horse_ids"], [alias.external_horse_id])
        horse_issues = [
            issue
            for issue in outcome.issues
            if issue["code"]
            in {"pending_horse_original_missing", "external_horse_not_preserved"}
        ]
        self.assertEqual(
            [issue["code"] for issue in horse_issues],
            ["external_horse_not_preserved"],
            horse_issues,
        )

    def test_article_aware_live_batch_and_discovery_share_resolution(self):
        self._external_alias("Brilliant", external_id="sl-shared")
        confirmed = self._article(body="Brilliant won at Ascot under Ryan Moore.")
        uncertain = self._article(
            title="Brilliant Update Published",
            body="Officials published the update after an administrative review.",
        )
        live_resolver = self._article_resolver()
        batch_resolver = self._batch_resolver()

        live = {article.id: live_resolver(article) for article in (confirmed, uncertain)}
        batch = batch_resolver([confirmed, uncertain])

        for article in (confirmed, uncertain):
            self.assertEqual(
                [item.as_dict() for item in live[article.id].entities],
                [item.as_dict() for item in batch[article.id].entities],
            )
        confirmed_findings = discover_term_findings(confirmed)
        uncertain_findings = discover_term_findings(uncertain)
        self.assertTrue(any(item.source_ja == "Brilliant" for item in confirmed_findings))
        self.assertFalse(any(item.source_ja == "Brilliant" for item in uncertain_findings))

    def test_discovery_uses_confirmed_occurrence_field_span_context_instead_of_title_membership(self):
        self._external_alias(
            "Brilliant",
            external_id="sl-discovery-occurrence-location",
        )
        body = (
            "Brilliant won at Ascot under Ryan Moore. "
            "The horse remains unbeaten."
        )
        article = self._article(
            source_article_id="discovery-confirmed-body-ordinary-title",
            title="Brilliant business outlook",
            body=body,
        )
        resolution = self._article_resolver()(article)
        occurrence = next(
            item
            for item in resolution.entities
            if item.field_name == "body"
            and item.matched_text == "Brilliant"
            and item.classification == "confirmed_horse"
        )

        findings = [
            item
            for item in discover_term_findings(article)
            if item.term_type == TermType.HORSE
            and item.source_ja == "Brilliant"
        ]

        self.assertEqual(len(findings), 1, findings)
        finding = findings[0]
        self.assertEqual(
            {
                "source_field": finding.source_field,
                "matched_span": list(
                    getattr(finding, "matched_span", ()) or ()
                ),
                "context": finding.context,
                "classification": getattr(
                    finding,
                    "classification",
                    None,
                ),
            },
            {
                "source_field": "body_ja_normalized",
                "matched_span": [occurrence.start, occurrence.end],
                "context": occurrence.matched_context,
                "classification": occurrence.classification,
            },
        )

    def test_japanese_discovery_falls_back_to_resolved_field_span_when_entity_context_is_empty(self):
        alias = ExternalHorseAlias.objects.create(
            source=ExternalDataSource.SPORTING_LIFE,
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            external_horse_id="sl-discovery-ja-context-fallback",
            name_ja="ザガラ",
            normalized_name="ザガラ",
            confidence=98,
            alias_source="discovery_context_fallback_fixture",
        )
        body = "高知競馬ではザガラが勝利し、関係者が今後の予定を説明した。"
        article = self._article(
            source_article_id="discovery-ja-context-fallback",
            title="高知競馬の結果",
            body=body,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
        )
        resolution = self._article_resolver()(article)
        occurrence = next(
            item
            for item in resolution.entities
            if alias.external_horse_id
            in (item.external_horse_ids or [])
        )
        self.assertEqual(occurrence.field_name, "body")
        self.assertEqual(occurrence.matched_context, "")

        finding = next(
            item
            for item in discover_term_findings(article)
            if item.term_type == TermType.HORSE
            and item.source_ja == "ザガラ"
        )

        self.assertEqual(finding.source_field, "body_ja_normalized")
        self.assertEqual(
            list(finding.matched_span),
            [occurrence.start, occurrence.end],
        )
        self.assertTrue(finding.context, finding)
        self.assertIn("ザガラ", finding.context)
        self.assertEqual(
            finding.context,
            body[
                max(0, occurrence.start - 50) :
                min(len(body), occurrence.end + 50)
            ].strip(),
        )

    def test_live_and_reprocessing_batch_share_visible_text_and_ignore_hidden_aliases(self):
        hidden_nav = self._external_alias("Hidden Runner", external_id="sl-hidden-nav")
        hidden_aside = self._external_alias("Sidebar Horse", external_id="sl-hidden-aside")
        visible = self._external_alias("Visible Star", external_id="sl-visible")
        article = self._article(
            title="Ascot result",
            body=(
                "<nav>Hidden Runner won at Ascot.</nav>"
                "<aside>Sidebar Horse won the trial.</aside>"
                "<p>Visible Star won at Ascot under Ryan Moore.</p>"
            ),
        )

        live_outcome = validate_rewrite(article)
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        batch_context = build_validation_batch_context([article])
        batch_outcome = validate_rewrite(article, batch_context=batch_context)

        def external_occurrences(outcome):
            return [
                {
                    "matched_text": item["matched_text"],
                    "classification": item["classification"],
                    "external_horse_ids": item["external_horse_ids"],
                    "needs_preserve": item["needs_preserve"],
                }
                for item in outcome.details["article_entities"]
                if item.get("external_horse_ids")
            ]

        self.assertEqual(external_occurrences(batch_outcome), external_occurrences(live_outcome))
        self.assertEqual(
            external_occurrences(live_outcome),
            [
                {
                    "matched_text": "Visible Star",
                    "classification": "confirmed_horse",
                    "external_horse_ids": [visible.external_horse_id],
                    "needs_preserve": True,
                }
            ],
        )
        hidden_ids = {hidden_nav.external_horse_id, hidden_aside.external_horse_id}
        for outcome in (live_outcome, batch_outcome):
            self.assertFalse(
                any(
                    hidden_ids & set((issue.get("payload") or {}).get("external_horse_ids") or [])
                    for issue in outcome.issues
                ),
                outcome.issues,
            )

    def _event(self, suffix: str) -> RaceEvent:
        return RaceEvent.objects.create(
            year=2026,
            slug=f"structured-{suffix}",
            original_name=f"Structured {suffix}",
            chinese_name=f"结构化赛事 {suffix}",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="Listed",
            surface=RaceEventSurface.TURF,
        )

    def test_only_active_structured_links_confirm_alias_occurrences(self):
        self._external_alias("Brilliant", external_id="sl-structured")
        resolver = self._batch_resolver()
        fixtures = []
        for status, removed in (
            (ArticleRaceLinkStatus.AUTO, False),
            (ArticleRaceLinkStatus.CANDIDATE, False),
            (ArticleRaceLinkStatus.MANUAL, True),
        ):
            article = self._article(
                source_article_id=f"structured-{status}-{removed}",
                title="Brilliant Update Published",
                body="Officials published the update after an administrative review.",
            )
            event = self._event(f"{status}-{int(removed)}")
            RaceEventRunner.objects.create(event=event, horse_name="Brilliant")
            ArticleRaceLink.objects.create(
                article=article,
                event=event,
                status=status,
                removed_at=timezone.now() if removed else None,
            )
            fixtures.append((article, status, removed))

        resolutions = resolver([item[0] for item in fixtures])

        classifications = {}
        for article, status, removed in fixtures:
            payload = self._entities_for(resolutions[article.id], "Brilliant")[0]
            classifications[(status, removed)] = payload["classification"]
        self.assertEqual(classifications[(ArticleRaceLinkStatus.AUTO, False)], "confirmed_horse")
        self.assertEqual(classifications[(ArticleRaceLinkStatus.CANDIDATE, False)], "uncertain")
        self.assertEqual(classifications[(ArticleRaceLinkStatus.MANUAL, True)], "uncertain")

    def test_structured_jockey_and_trainer_names_do_not_confirm_horse_aliases(self):
        self._external_alias("Brilliant", external_id="sl-role-jockey")
        self._external_alias("Splendid", external_id="sl-role-trainer")
        article = self._article(
            title="Presentation update",
            body="Brilliant and Splendid attended the presentation after racing.",
        )
        event = self._event("role-names")
        RaceEventRunner.objects.create(
            event=event,
            horse_name="Actual Runner",
            jockey_name="Brilliant",
            trainer_name="Splendid",
        )
        ArticleRaceLink.objects.create(
            article=article,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )
        live_resolver = self._article_resolver()

        live = live_resolver(article)
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        reprocessing_context = build_validation_batch_context([article])
        batch = reprocessing_context.entity_resolutions_by_article[article.id]

        for name in ("Brilliant", "Splendid"):
            with self.subTest(name=name):
                live_payload = self._entities_for(live, name)[0]
                batch_payload = self._entities_for(batch, name)[0]
                self.assertEqual(batch_payload, live_payload)
                self.assertOccurrence(
                    live_payload,
                    classification="uncertain",
                    needs_preserve=False,
                )

    def test_structured_horse_evidence_is_scoped_to_the_actual_occurrence(self):
        self._external_alias("Brilliant", external_id="sl-occurrence-structured")
        article = self._article(
            title="Ascot result",
            body=(
                "Brilliant won at Ascot under Ryan Moore. "
                "Later, the trainer praised a brilliant performance by the team."
            ),
        )
        event = self._event("occurrence-scope")
        RaceEventRunner.objects.create(event=event, horse_name="Brilliant")
        ArticleRaceLink.objects.create(
            article=article,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )
        live_resolver = self._article_resolver()
        batch_resolver = self._batch_resolver()

        live = live_resolver(article)
        batch = batch_resolver([article])[article.id]

        self.assertEqual(
            [item.as_dict() for item in batch.entities],
            [item.as_dict() for item in live.entities],
        )
        payloads = self._entities_for(live, "Brilliant")
        self.assertEqual(len(payloads), 2, payloads)
        self.assertOccurrence(
            payloads[0],
            classification="confirmed_horse",
            needs_preserve=True,
        )
        self.assertOccurrence(
            payloads[1],
            classification="common_word",
            needs_preserve=False,
        )

    def test_structured_surface_evidence_does_not_confirm_lexical_only_same_article_occurrence(self):
        alias = self._external_alias(
            "Brilliant",
            external_id="sl-structured-lexical-occurrence",
        )
        body = (
            "Brilliant won at Ascot. "
            "Brilliant Result Announced after an administrative review."
        )
        translated_body = (
            "Brilliant won at Ascot. "
            "其余内容仅说明行政审核后的结果公告和背景信息。"
        ) * 5
        article = self._article(
            source_article_id="structured-surface-lexical-occurrence",
            title="Ascot result",
            body=body,
            translated_body_zh=translated_body,
            body_zh=translated_body,
        )
        event = self._event("surface-lexical-occurrence")
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_name="Brilliant",
        )
        result = RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_name="Brilliant",
        )
        ArticleRaceLink.objects.create(
            article=article,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )

        live = self._article_resolver()(article)
        batch = self._batch_resolver()([article])[article.id]
        from stable.services.term_gate_reprocessing import (
            build_validation_batch_context,
        )

        reprocessing = build_validation_batch_context(
            [article]
        ).entity_resolutions_by_article[article.id]
        for resolution in (batch, reprocessing):
            self.assertEqual(
                [item.as_dict() for item in resolution.entities],
                [item.as_dict() for item in live.entities],
            )

        payloads = self._entities_for(live, "Brilliant")
        self.assertEqual(len(payloads), 2, payloads)
        self.assertEqual(
            [item["matched_span"] for item in payloads],
            [
                [0, len("Brilliant")],
                [
                    body.index("Brilliant", 1),
                    body.index("Brilliant", 1) + len("Brilliant"),
                ],
            ],
        )
        self.assertOccurrence(
            payloads[0],
            classification="confirmed_horse",
            needs_preserve=True,
        )
        self.assertIn(
            f"race_runner:{runner.id}:event:{event.id}:horse_name",
            payloads[0]["entity_evidence"],
        )
        self.assertIn(
            f"race_result:{result.id}:event:{event.id}:horse_name",
            payloads[0]["entity_evidence"],
        )
        self.assertOccurrence(
            payloads[1],
            classification="uncertain",
            needs_preserve=False,
        )
        self.assertFalse(
            any(
                evidence.startswith("race_")
                for evidence in payloads[1]["entity_evidence"]
            ),
            payloads[1],
        )

        outcome = validate_rewrite(article)
        preservable = [
            item
            for item in outcome.details["recognized_horse_names"]
            if item["matched_text"] == "Brilliant"
            and item["needs_preserve"]
        ]
        self.assertEqual(len(preservable), 1, preservable)
        self.assertFalse(
            any(
                issue["code"] in HORSE_ISSUE_CODES
                and (issue.get("payload") or {}).get(
                    "primary_external_horse_id"
                )
                == alias.external_horse_id
                for issue in outcome.issues
            ),
            outcome.issues,
        )

    def test_structured_campaign_requires_local_race_relation_to_override_ordinary_purpose_shape(self):
        alias = self._external_alias(
            "Campaign",
            external_id="sl-structured-campaign",
        )
        article = self._article(
            source_article_id="structured-campaign-local-relation",
            title="Ascot declarations",
            body=(
                "Campaign to win the race starts from stall four. "
                "the Campaign to win the race is the trainer's main hope. "
                "A Campaign performance impressed the company. "
                "They launched a campaign to improve business."
            ),
        )
        event = self._event("campaign-local-relation")
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_name="Campaign",
        )
        ArticleRaceLink.objects.create(
            article=article,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )

        live = self._article_resolver()(article)
        batch = self._batch_resolver()([article])[article.id]
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        reprocessing = build_validation_batch_context(
            [article]
        ).entity_resolutions_by_article[article.id]
        live_payloads = self._entities_for(live, "Campaign")
        self.assertEqual(len(live_payloads), 4, live_payloads)
        self.assertEqual(
            [item.as_dict() for item in batch.entities],
            [item.as_dict() for item in live.entities],
        )
        self.assertEqual(
            [item.as_dict() for item in reprocessing.entities],
            [item.as_dict() for item in live.entities],
        )

        structured_evidence = (
            f"race_runner:{runner.id}:event:{event.id}:horse_name"
        )
        for payload in live_payloads[:2]:
            self.assertOccurrence(
                payload,
                classification="confirmed_horse",
                needs_preserve=True,
            )
            self.assertIn(
                structured_evidence,
                payload["entity_evidence"],
                payload,
            )
            self.assertEqual(
                payload["external_horse_ids"],
                [alias.external_horse_id],
            )
        for payload in live_payloads[2:]:
            self.assertOccurrence(
                payload,
                classification="common_word",
                needs_preserve=False,
            )
            self.assertNotIn(
                structured_evidence,
                payload["entity_evidence"],
                payload,
            )

    def test_non_english_batch_skips_structured_loader_while_english_still_uses_it(self):
        from stable.services import terms

        japanese = self._article(
            source_article_id="structured-loader-ja",
            title="日本語記事",
            body="これは通常の記事本文です。",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
        )
        self._external_alias("Brilliant", external_id="sl-loader-english")
        english = self._article(
            source_article_id="structured-loader-en",
            title="Ascot result",
            body="Brilliant won at Ascot.",
        )
        original_loader = terms._structured_horse_entities_for_articles

        with patch(
            "stable.services.terms._structured_horse_entities_for_articles",
            wraps=original_loader,
        ) as loader:
            resolutions = self._batch_resolver()([japanese, english])

        english_payload = self._entities_for(resolutions[english.id], "Brilliant")[0]
        self.assertOccurrence(
            english_payload,
            classification="confirmed_horse",
            needs_preserve=True,
        )
        loader.assert_called_once()
        loaded_articles = list(loader.call_args.args[0])
        self.assertEqual([article.id for article in loaded_articles], [english.id])

    def test_reprocessing_runner_and_result_queries_are_scoped_to_english_article_ids(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        japanese = self._article(
            source_article_id="reprocessing-query-ja",
            title="日本語記事",
            body="これは通常の記事本文です。",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
        )
        english = self._article(
            source_article_id="reprocessing-query-en",
            title="Ascot result",
            body="Brilliant won at Ascot.",
        )
        for article, suffix, horse_name in (
            (japanese, "query-ja", "ジャパン"),
            (english, "query-en", "Brilliant"),
        ):
            event = self._event(suffix)
            RaceEventRunner.objects.create(event=event, horse_name=horse_name)
            RaceEventResult.objects.create(
                event=event,
                finish_position=1,
                horse_name=horse_name,
            )
            ArticleRaceLink.objects.create(
                article=article,
                event=event,
                status=ArticleRaceLinkStatus.AUTO,
            )

        with CaptureQueriesContext(connection) as captured:
            build_validation_batch_context([japanese, english])

        structured_sql = {
            table: [
                query["sql"]
                for query in captured
                if table in query["sql"]
            ]
            for table in ("stable_raceeventrunner", "stable_raceeventresult")
        }
        self.assertEqual(len(structured_sql["stable_raceeventrunner"]), 1, structured_sql)
        self.assertEqual(len(structured_sql["stable_raceeventresult"]), 1, structured_sql)
        for table, queries in structured_sql.items():
            match = re.search(r'\."article_id" IN \(([^)]*)\)', queries[0])
            self.assertIsNotNone(match, queries[0])
            queried_ids = {
                int(value.strip())
                for value in match.group(1).split(",")
                if value.strip()
            }
            self.assertEqual(queried_ids, {english.id}, {table: queries[0]})

    def test_reprocessing_pure_non_english_batch_avoids_runner_and_result_queries(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        japanese = self._article(
            source_article_id="reprocessing-query-only-ja",
            title="日本語記事",
            body="これは通常の記事本文です。",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
        )
        event = self._event("query-only-ja")
        RaceEventRunner.objects.create(event=event, horse_name="ジャパン")
        RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_name="ジャパン",
        )
        ArticleRaceLink.objects.create(
            article=japanese,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )

        with CaptureQueriesContext(connection) as captured:
            build_validation_batch_context([japanese])

        structured_queries = [
            query["sql"]
            for query in captured
            if "stable_raceeventrunner" in query["sql"]
            or "stable_raceeventresult" in query["sql"]
        ]
        self.assertEqual(structured_queries, [])

    def test_apostrophe_normalized_structured_horse_evidence_is_consistent_across_resolvers(self):
        from stable.services.term_gate_reprocessing import build_validation_batch_context

        fixtures = (
            ("King’s Gambit", "King's Gambit", "curly-runner"),
            ("King's Gambit", "King’s Gambit", "straight-runner"),
        )
        for structured_name, article_name, suffix in fixtures:
            with self.subTest(
                structured_name=structured_name,
                article_name=article_name,
            ):
                alias = self._external_alias(
                    article_name,
                    external_id=f"sl-apostrophe-{suffix}",
                )
                article = self._article(
                    source_article_id=f"apostrophe-structured-{suffix}",
                    title="Ascot result",
                    body=f"{article_name} won at Ascot.",
                )
                event = self._event(f"apostrophe-{suffix}")
                runner = RaceEventRunner.objects.create(
                    event=event,
                    horse_name=structured_name,
                )
                ArticleRaceLink.objects.create(
                    article=article,
                    event=event,
                    status=ArticleRaceLinkStatus.AUTO,
                )

                live = self._article_resolver()(article)
                batch = self._batch_resolver()([article])[article.id]
                reprocessing = build_validation_batch_context(
                    [article]
                ).entity_resolutions_by_article[article.id]
                payloads = [
                    self._entities_for(resolution, article_name)[0]
                    for resolution in (live, batch, reprocessing)
                ]

                self.assertEqual(payloads[1], payloads[0])
                self.assertEqual(payloads[2], payloads[0])
                for payload in payloads:
                    self.assertOccurrence(
                        payload,
                        classification="confirmed_horse",
                        needs_preserve=True,
                    )
                    self.assertIn(
                        alias.external_horse_id,
                        payload["external_horse_ids"],
                    )
                    self.assertIn(
                        f"race_runner:{runner.id}:event:{event.id}:horse_name",
                        payload["entity_evidence"],
                        payload,
                    )

    def test_reprocessing_imports_the_public_terms_horse_entity_key_normalizer(self):
        from stable.services import term_gate_reprocessing, terms

        shared_normalizer = getattr(terms, "normalize_horse_entity_key", None)
        self.assertIsNotNone(
            shared_normalizer,
            "terms 必须公开唯一 horse entity key normalizer",
        )
        reprocessing_normalizer = getattr(
            term_gate_reprocessing,
            "normalize_horse_entity_key",
            None,
        )
        self.assertIs(
            reprocessing_normalizer,
            shared_normalizer,
            "term_gate_reprocessing 必须导入 terms 的公开 helper，不能自建归一化分支",
        )

        self._external_alias("King's Gambit", external_id="sl-shared-normalizer")
        article = self._article(
            source_article_id="reprocessing-shared-normalizer",
            title="Ascot result",
            body="King's Gambit won at Ascot.",
        )
        event = self._event("shared-normalizer")
        RaceEventRunner.objects.create(event=event, horse_name="King’s Gambit")
        ArticleRaceLink.objects.create(
            article=article,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )

        with patch.object(
            term_gate_reprocessing,
            "normalize_horse_entity_key",
            wraps=shared_normalizer,
        ) as normalizer:
            term_gate_reprocessing.build_validation_batch_context([article])

        self.assertGreater(normalizer.call_count, 0)
        normalizer.assert_any_call("King’s Gambit")

    def test_generated_nested_formal_horses_use_longest_non_overlapping_mapping(self):
        long_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="International Star",
            target_zh="国际之星",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=10,
        )
        short_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Star",
            target_zh="星",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=200,
        )
        resolution = resolve_article_entities(
            "Ascot result",
            "International Star won at Ascot. Star finished second.",
            source_language=SourceLanguage.ENGLISH,
        )

        accepted = {
            (term.source_ja, term.matched_text, term.target_zh)
            for term in resolution.accepted_terms
        }
        self.assertIn(
            (long_term.source_ja, "International Star", "国际之星"),
            accepted,
        )
        self.assertIn((short_term.source_ja, "Star", "星"), accepted)
        self.assertEqual(
            apply_generated_text_contextual_mappings(
                "International Star won at Ascot. Star finished second.",
                resolution,
            ),
            "国际之星 won at Ascot. 星 finished second.",
        )
        self.assertEqual(
            apply_generated_text_contextual_mappings(
                "Star won at Ascot.",
                resolution,
            ),
            "星 won at Ascot.",
        )

    def test_generated_nested_formal_horse_mapping_is_stable_for_reverse_order_and_priority(self):
        short_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Star",
            target_zh="星",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=5,
        )
        long_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="International Star",
            target_zh="国际之星",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=500,
        )
        resolution = resolve_article_entities(
            "Ascot result",
            "Star finished second. International Star won at Ascot.",
            source_language=SourceLanguage.ENGLISH,
        )

        accepted_sources = {term.source_ja for term in resolution.accepted_terms}
        self.assertEqual(
            accepted_sources,
            {short_term.source_ja, long_term.source_ja},
        )
        self.assertEqual(
            apply_generated_text_contextual_mappings(
                "International Star won at Ascot. Star finished second.",
                resolution,
            ),
            "国际之星 won at Ascot. 星 finished second.",
        )

    def test_article_aware_batch_query_count_is_bounded(self):
        self._pending_term("Brilliant")
        self._external_alias("Brilliant", external_id="sl-query-budget")
        resolver = self._batch_resolver()
        articles = [
            self._article(
                source_article_id=f"query-{index}",
                body="Brilliant won at Ascot under Ryan Moore.",
            )
            for index in range(20)
        ]

        with CaptureQueriesContext(connection) as ten_queries:
            resolver(articles[:10])
        with CaptureQueriesContext(connection) as twenty_queries:
            resolver(articles)

        self.assertLessEqual(len(ten_queries), 8, [query["sql"] for query in ten_queries])
        self.assertEqual(len(twenty_queries), len(ten_queries), [query["sql"] for query in twenty_queries])

    def test_mixed_language_batch_telemetry_counts_actual_entity_index_queries_without_n_plus_one(self):
        from stable.models import TermAlias, TermAliasType
        from stable.services.term_gate_reprocessing import (
            build_validation_batch_context,
        )

        english_term = self._translated_term("Brilliant", "辉煌")
        japanese_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="ザガラ",
            target_zh="萨加拉",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=100,
        )
        TermAlias.objects.create(
            term=english_term,
            source_language=SourceLanguage.ENGLISH,
            text="Brilliant",
            alias_type=TermAliasType.PRIMARY,
        )
        TermAlias.objects.create(
            term=japanese_term,
            source_language=SourceLanguage.JAPANESE,
            text="ザガラ",
            alias_type=TermAliasType.PRIMARY,
        )
        self._external_alias(
            "Brilliant",
            external_id="sl-mixed-telemetry-en",
        )
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.SPORTING_LIFE,
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            external_horse_id="sl-mixed-telemetry-ja",
            name_ja="ザガラ",
            normalized_name="ザガラ",
            confidence=98,
            alias_source="mixed_telemetry_fixture",
        )
        articles = []
        for index in range(10):
            articles.extend(
                [
                    self._article(
                        source_article_id=f"mixed-telemetry-en-{index}",
                        title="Ascot result",
                        body="Brilliant won at Ascot.",
                    ),
                    self._article(
                        source_article_id=f"mixed-telemetry-ja-{index}",
                        title="日本語記事",
                        body="ザガラが勝利した。",
                        source_language=SourceLanguage.JAPANESE,
                        racing_region=RacingRegion.JAPAN,
                    ),
                ]
            )

        def table_query_count(captured, table_name):
            return sum(
                table_name in query["sql"].casefold()
                for query in captured
            )

        with CaptureQueriesContext(connection) as small_queries:
            small = build_validation_batch_context(articles[:2])
        with CaptureQueriesContext(connection) as large_queries:
            large = build_validation_batch_context(articles)

        for context, captured in (
            (small, small_queries),
            (large, large_queries),
        ):
            external_alias_queries = table_query_count(
                captured,
                ExternalHorseAlias._meta.db_table,
            )
            term_entry_queries = table_query_count(
                captured,
                TermEntry._meta.db_table,
            )
            term_alias_queries = table_query_count(
                captured,
                TermAlias._meta.db_table,
            )
            entity_index_term_queries = (
                term_entry_queries
                - context.term_entry_prefetch_count
                + term_alias_queries
                - context.term_alias_prefetch_count
            )
            self.assertEqual(
                context.horse_alias_prefetch_count,
                external_alias_queries,
            )
            self.assertEqual(
                context.horse_term_prefetch_count,
                entity_index_term_queries,
            )
            self.assertEqual(
                context.entity_prefetch_count,
                context.race_entity_prefetch_count
                + external_alias_queries
                + entity_index_term_queries,
            )
            self.assertEqual(external_alias_queries, 2)
            self.assertEqual(entity_index_term_queries, 4)

        self.assertEqual(
            len(large_queries),
            len(small_queries),
            [query["sql"] for query in large_queries],
        )

    def test_non_english_article_resolvers_keep_raw_translation_source_coordinates(self):
        fixtures = (
            {
                "language": SourceLanguage.JAPANESE,
                "region": RacingRegion.JAPAN,
                "source": "ザガラ",
                "target": "萨加拉",
                "term_type": TermType.HORSE,
                "body": (
                    "<nav>ザガラのメニュー</nav>"
                    "<p>ザガラが1着となった。</p>"
                    "<aside>ザガラの関連記事</aside>"
                ),
            },
            {
                "language": SourceLanguage.CHINESE_TRADITIONAL,
                "region": RacingRegion.HONG_KONG,
                "source": "香港打吡大賽",
                "target": "香港德比大赛",
                "term_type": TermType.RACE,
                "body": (
                    "<nav>香港打吡大賽導覽</nav>"
                    "<p>香港打吡大賽今日舉行。</p>"
                    "<aside>香港打吡大賽相關新聞</aside>"
                ),
            },
        )
        for index, fixture in enumerate(fixtures, start=1):
            with self.subTest(language=fixture["language"]):
                term = TermEntry.objects.create(
                    term_type=fixture["term_type"],
                    source_language=fixture["language"],
                    racing_region=fixture["region"],
                    source_ja=fixture["source"],
                    target_zh=fixture["target"],
                    translation_status=TermTranslationStatus.TRANSLATED,
                    priority=100,
                )
                article = self._article(
                    source_article_id=f"raw-coordinate-{index}",
                    title="原文標題",
                    body=fixture["body"],
                    body_ja_normalized="",
                    source_language=fixture["language"],
                    racing_region=fixture["region"],
                )

                single = self._article_resolver()(article)
                batch = self._batch_resolver()([article])[article.id]

                expected_spans = [
                    [match.start(), match.end()]
                    for match in re.finditer(
                        re.escape(fixture["source"]),
                        fixture["body"],
                    )
                ]
                single_entities = [
                    item.as_dict()
                    for item in single.entities
                    if item.term_id == term.id
                ]
                self.assertEqual(
                    [item["matched_span"] for item in single_entities],
                    expected_spans,
                    "非英文 article-aware resolver 必须使用实际 translation "
                    "source raw 坐标，不能先 clean 后再错位映射",
                )
                self.assertEqual(
                    [item.as_dict() for item in batch.entities],
                    [item.as_dict() for item in single.entities],
                )

    def test_english_article_resolvers_keep_visible_clean_coordinates(self):
        term = TermEntry.objects.create(
            term_type=TermType.RACE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Ascot",
            target_zh="雅士谷",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=100,
        )
        article = self._article(
            source_article_id="english-visible-clean-coordinate",
            title="Racecourse update",
            body=(
                "<nav>Ascot hidden navigation</nav>"
                "<p>Ascot stages the meeting.</p>"
                "<aside>Ascot hidden sidebar</aside>"
            ),
            body_ja_normalized="",
        )

        single = self._article_resolver()(article)
        batch = self._batch_resolver()([article])[article.id]
        entities = [
            item.as_dict()
            for item in single.entities
            if item.term_id == term.id
        ]

        self.assertEqual(len(entities), 1, entities)
        self.assertEqual(entities[0]["matched_text"], "Ascot")
        self.assertEqual(entities[0]["matched_span"], [0, len("Ascot")])
        self.assertEqual(
            [item.as_dict() for item in batch.entities],
            [item.as_dict() for item in single.entities],
        )

    def test_japanese_raw_coordinates_drive_format_and_seed_placeholder_plans(self):
        from stable.services import japanese_racing_translation

        horse = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="ザガラ",
            target_zh="萨加拉",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=100,
        )
        seed = TermEntry.objects.create(
            term_type=TermType.RACE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="レコード",
            target_zh="记录",
            translation_status=TermTranslationStatus.TRANSLATED,
            notes="japanese_racing_translation_seed",
            priority=90,
        )
        raw_body = (
            "<nav>レコード一覧</nav>"
            "<p>永森大智騎手(ザガラ＝1着)はレコード更新を語った。</p>"
            "<aside>レコード関連記事</aside>"
        )
        article = self._article(
            source_article_id="japanese-raw-format-seed-coordinate",
            title="日本語記事",
            body=raw_body,
            body_ja_normalized="",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
        )

        resolution = self._article_resolver()(article)
        horse_entity = next(
            item for item in resolution.entities if item.term_id == horse.id
        )
        self.assertEqual(
            [horse_entity.start, horse_entity.end],
            [
                raw_body.index("ザガラ"),
                raw_body.index("ザガラ") + len("ザガラ"),
            ],
        )

        format_plan = japanese_racing_translation.build_japanese_format_plan(
            article.title_ja,
            raw_body,
            resolution,
        )
        interview = next(
            item
            for item in format_plan.items
            if item.rule == "post_race_interview"
        )
        self.assertEqual(
            raw_body[interview.start : interview.end],
            interview.source_text,
        )
        self.assertEqual(
            interview.target_text,
            "永森大智骑手(1着 萨加拉)",
        )

        seed_plan = japanese_racing_translation.build_japanese_seed_term_plan(
            article.title_ja,
            raw_body,
            resolution,
            format_plan,
        )
        seed_items = [
            item for item in seed_plan.items if item.source_text == "レコード"
        ]
        self.assertEqual(len(seed_items), 3, seed_plan.as_dicts())
        self.assertEqual(
            [
                raw_body[item.start : item.end]
                for item in seed_items
            ],
            ["レコード", "レコード", "レコード"],
        )
        self.assertEqual(
            {item.target_text for item in seed_items},
            {"记录"},
        )


@override_settings(**SETTINGS)
class PublishedEnglishHorseAuditOnlyTests(TestCase):
    def _article(self, *, title: str = "Racing leadership update", body: str, **overrides) -> NewsArticle:
        translated_body = "这是一篇经过人工校对的赛马新闻正文，介绍行业动态、参赛情况和后续计划。" * 8
        defaults = {
            "source_site": SourceSite.TDN,
            "source_mode": SourceMode.LATEST,
            "source_article_id": "published-external-english-gate",
            "source_language": SourceLanguage.ENGLISH,
            "racing_region": RacingRegion.UNITED_KINGDOM,
            "title_ja": title,
            "body_ja_raw": body,
            "body_ja_normalized": body,
            "translated_title_zh": "赛马新闻",
            "title_zh": "赛马新闻",
            "translated_summary_zh": "赛事和行业最新动态。",
            "summary_zh": "赛事和行业最新动态。",
            "translated_body_zh": translated_body,
            "body_zh": translated_body,
            "published_at": timezone.now(),
            "source_url": "https://example.com/published-external-english-context",
            "workflow_status": WorkflowStatus.PENDING_EDIT,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "automation_status": AutomationStatus.PENDING,
            "score_total": 100,
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def _pending_term(self, source: str) -> TermEntry:
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja=source,
            target_zh="",
            translation_status=TermTranslationStatus.PENDING,
            notes="p0_major_race_participant_auto_created",
            priority=100,
        )

    def _dependency_profile(self) -> HorseProfile:
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Snapshot Runner",
            target_zh="快照赛驹",
            translation_status=TermTranslationStatus.TRANSLATED,
            priority=80,
        )
        return HorseProfile.objects.create(
            primary_term=term,
            display_name_zh="快照赛驹",
            original_name="Snapshot Runner",
            english_name="Snapshot Runner",
            racing_region=RacingRegion.UNITED_KINGDOM,
            review_status=HorseProfileStatus.PUBLISHED,
            published_at=timezone.now(),
        )

    @staticmethod
    def _gate_state(article: NewsArticle) -> dict:
        return {
            "gate_issues": json.loads(json.dumps(article.gate_issues)),
            "decision_reason": json.loads(json.dumps(article.decision_reason)),
            "automation_warning_email_signature": article.automation_warning_email_signature,
        }

    def _assert_gate_state(self, article: NewsArticle, expected: dict) -> None:
        article.refresh_from_db()
        self.assertEqual(article.gate_issues, expected["gate_issues"])
        self.assertEqual(article.decision_reason, expected["decision_reason"])
        self.assertEqual(
            article.automation_warning_email_signature,
            expected["automation_warning_email_signature"],
        )

    def _audit_api(self):
        from stable.services import term_gate_reprocessing

        dry_run = getattr(term_gate_reprocessing, "run_published_term_gate_audit_dry_run", None)
        apply = getattr(term_gate_reprocessing, "apply_published_term_gate_audit_run", None)
        self.assertIsNotNone(
            dry_run,
            "缺少 published exact-ID audit-only dry-run API：run_published_term_gate_audit_dry_run",
        )
        self.assertIsNotNone(
            apply,
            "缺少 published exact-ID audit-only apply API：apply_published_term_gate_audit_run",
        )
        return dry_run, apply

    def _published_article(self) -> NewsArticle:
        self._pending_term("Work")
        published_at = timezone.now() - timezone.timedelta(hours=2)
        return self._article(
            source_article_id="published-audit-only",
            title="Leadership update",
            body="The team has done really good work, with work already underway.",
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            review_mode=ReviewMode.AUTO,
            risk_level=RiskLevel.LOW,
            publish_ready_at=published_at - timezone.timedelta(minutes=10),
            ranked_revived_at=published_at - timezone.timedelta(minutes=5),
            published_to_web_at=published_at,
            published_by_mode=PublishedByMode.AUTO,
            gate_issues=[
                {
                    "code": "pending_horse_original_missing",
                    "severity": "warning",
                    "message": "暂无中文译名马名未保留原文：Work",
                    "payload": {"source_ja": "Work"},
                }
            ],
            decision_reason={"gate_issues": [{"code": "pending_horse_original_missing"}]},
            automation_warning_email_signature="old-signature",
        )

    def test_published_apply_changes_only_gate_audit_allowlist(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        target = PushTarget.objects.create(name="审核群", group_id="audit-only-group")
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            message_id="existing-message",
            sent_at=timezone.now(),
        )
        notification = NotificationLog.objects.create(
            type=NotificationType.HIGH_VALUE_WARNING,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            payload_summary="existing warning",
            sent_at=timezone.now(),
        )
        immutable_fields = (
            "workflow_status",
            "automation_status",
            "review_mode",
            "risk_level",
            "publish_ready_at",
            "ranked_revived_at",
            "published_to_web_at",
            "translated_title_zh",
            "translated_body_zh",
            "body_zh",
        )
        before = {field: getattr(article, field) for field in immutable_fields}

        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-test",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        result = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
        )

        self.assertEqual(result["updated_article_ids"], [article.id])
        article.refresh_from_db()
        delivery.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual({field: getattr(article, field) for field in immutable_fields}, before)
        self.assertEqual(delivery.status, QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.message_id, "existing-message")
        self.assertTrue(NotificationLog.objects.filter(pk=notification.pk).exists())
        self.assertEqual(NotificationLog.objects.count(), 1)
        self.assertFalse(any(issue.get("code") in HORSE_ISSUE_CODES for issue in article.gate_issues))

    def test_published_audit_apply_replay_is_idempotent_and_does_not_touch_side_effects(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        target = PushTarget.objects.create(
            name="幂等审核群",
            group_id="published-audit-idempotent-group",
        )
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            message_id="idempotent-existing-message",
            sent_at=timezone.now(),
        )
        notification = NotificationLog.objects.create(
            type=NotificationType.HIGH_VALUE_WARNING,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            payload_summary="idempotent existing warning",
            sent_at=timezone.now(),
        )
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-idempotent",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        first = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
        )
        article.refresh_from_db()
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])
        delivery.refresh_from_db()
        notification.refresh_from_db()
        first_article_updated_at = article.updated_at
        first_gate_state = self._gate_state(article)
        first_run_state = {
            "status": run.status,
            "result_payload": json.loads(json.dumps(run.result_payload)),
            "finished_at": run.finished_at,
            "updated_at": run.updated_at,
        }
        first_side_effect_state = {
            "qq_count": QQPushDelivery.objects.count(),
            "notification_count": NotificationLog.objects.count(),
            "delivery_status": delivery.status,
            "delivery_message_id": delivery.message_id,
            "notification_status": notification.status,
        }

        second = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
        )

        article.refresh_from_db()
        run.refresh_from_db()
        delivery.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual(first["status"], "committed")
        self.assertEqual(second["status"], "already_committed")
        self.assertEqual(second["updated_article_ids"], [article.id])
        self.assertEqual(article.updated_at, first_article_updated_at)
        self._assert_gate_state(article, first_gate_state)
        self.assertEqual(
            {
                "status": run.status,
                "result_payload": run.result_payload,
                "finished_at": run.finished_at,
                "updated_at": run.updated_at,
            },
            first_run_state,
        )
        self.assertEqual(
            {
                "qq_count": QQPushDelivery.objects.count(),
                "notification_count": NotificationLog.objects.count(),
                "delivery_status": delivery.status,
                "delivery_message_id": delivery.message_id,
                "notification_status": notification.status,
            },
            first_side_effect_state,
        )

    def test_published_audit_committed_replay_binds_explicit_reviewer_identity(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-replay-reviewer",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        first = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        self.assertEqual(first["status"], "committed")

        with self.assertRaisesRegex(
            ValueError,
            "reviewer.*identity.*mismatch|reviewer.*match",
        ):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
                reviewer_identity="other-reviewer@example.com",
            )

        replay = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        self.assertEqual(replay["status"], "already_committed")
        self.assertEqual(
            replay["reviewer_identity"],
            "reviewer@example.com",
        )

    def test_published_audit_apply_locks_run_and_rejects_non_succeeded_first_apply(self):
        from stable.services import term_gate_reprocessing

        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = self._gate_state(article)
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-invalid-state",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        TermGateReprocessRun.objects.filter(pk=prepared["run_id"]).update(
            status=TermGateReprocessStatus.RUNNING,
        )
        manager = TermGateReprocessRun.objects
        original_select_for_update = manager.select_for_update

        with (
            patch.object(
                manager,
                "select_for_update",
                wraps=original_select_for_update,
            ) as run_lock,
            self.assertRaisesRegex(ValueError, "status|state|succeeded|prepared"),
        ):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        run_lock.assert_called_once_with()
        self._assert_gate_state(article, before)
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])
        self.assertEqual(run.status, TermGateReprocessStatus.RUNNING)
        self.assertNotIn("updated_article_ids", run.result_payload)

    def test_published_apply_fails_closed_on_allowlist_or_snapshot_drift(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-drift-test",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        article.body_ja_normalized += " Source drift."
        article.save(update_fields=["body_ja_normalized", "updated_at"])

        with self.assertRaisesRegex(ValueError, "drift|fingerprint|snapshot"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

    def test_published_audit_requires_exact_ids_manifest_and_confirmation(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-contract-test",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        with self.assertRaises((TypeError, ValueError)):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[],
                confirm=True,
                operator_identity="ops@example.com",
            )
        with self.assertRaises((TypeError, ValueError)):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256="wrong",
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )
        with self.assertRaises((TypeError, ValueError)):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=False,
                operator_identity="ops@example.com",
            )

    def test_published_audit_service_requires_and_binds_normalized_identities(self):
        dry_run, _ = self._audit_api()
        article = self._published_article()

        with self.assertRaises((TypeError, ValueError)):
            dry_run(
                article_ids=[article.id],
                owner_token="published-audit-implicit-identity",
            )
        with self.assertRaisesRegex(ValueError, "operator|reviewer|identity"):
            dry_run(
                article_ids=[article.id],
                owner_token="published-audit-missing-identity",
                operator_identity="",
                reviewer_identity="",
            )

        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-identity-binding",
            operator_identity="  ops@example.com  ",
            reviewer_identity="  reviewer@example.com  ",
        )
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])

        self.assertEqual(run.selectors["operator_identity"], "ops@example.com")
        self.assertEqual(run.selectors["reviewer_identity"], "reviewer@example.com")
        self.assertEqual(
            run.result_payload["operator_identity"],
            "ops@example.com",
        )
        self.assertEqual(
            run.result_payload["reviewer_identity"],
            "reviewer@example.com",
        )
        self.assertEqual(
            run.result_payload["manifest"]["operator_identity"],
            "ops@example.com",
        )
        self.assertEqual(
            run.result_payload["manifest"]["reviewer_identity"],
            "reviewer@example.com",
        )

    def test_published_audit_apply_requires_matching_prepared_operator(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-apply-identity",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        with self.assertRaises((TypeError, ValueError)):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
            )
        with self.assertRaisesRegex(ValueError, "operator|identity|drift|match"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="other@example.com",
            )

        result = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="  ops@example.com  ",
        )
        self.assertEqual(result["updated_article_ids"], [article.id])

    @override_settings(ENGLISH_TERM_CONTEXT_MODE="off")
    def test_published_audit_uses_and_binds_effective_enforce_mode_when_global_is_off(self):
        dry_run, apply = self._audit_api()
        for word in POLLUTING_WORDS:
            self._pending_term(word)
        published_at = timezone.now() - timezone.timedelta(hours=2)
        article = self._article(
            source_article_id="published-audit-effective-enforce-9595",
            title="Horse Racing Has Always Been My Passion",
            body=ARTICLE_9595_EQUIVALENT_BODY,
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            review_mode=ReviewMode.AUTO,
            risk_level=RiskLevel.LOW,
            published_to_web_at=published_at,
            published_by_mode=PublishedByMode.AUTO,
            gate_issues=[
                {
                    "code": "pending_horse_original_missing",
                    "severity": "warning",
                    "message": "legacy polluted warning",
                    "payload": {"source_ja": "Work"},
                }
            ],
            decision_reason={"gate_issues": [{"code": "pending_horse_original_missing"}]},
            automation_warning_email_signature="legacy-polluted-signature",
        )

        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-effective-enforce-off",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])
        manifest = run.result_payload["manifest"]
        issues = prepared["outcomes"][0]["issues"]

        self.assertFalse(
            any(issue["code"] in HORSE_ISSUE_CODES for issue in issues),
            issues,
        )
        self.assertEqual(prepared["configured_rule_mode"], "off")
        self.assertEqual(prepared["effective_rule_mode"], "enforce")
        self.assertEqual(run.selectors["effective_rule_mode"], "enforce")
        self.assertEqual(run.result_payload["effective_rule_mode"], "enforce")
        self.assertEqual(manifest["configured_rule_mode"], "off")
        self.assertEqual(manifest["effective_rule_mode"], "enforce")
        self.assertEqual(
            manifest["effective_settings"]["ENGLISH_TERM_CONTEXT_MODE"],
            "enforce",
        )

        result = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
        )
        self.assertEqual(result["updated_article_ids"], [article.id])
        article.refresh_from_db()
        self.assertFalse(
            any(issue["code"] in HORSE_ISSUE_CODES for issue in article.gate_issues),
            article.gate_issues,
        )

    @override_settings(ENGLISH_TERM_CONTEXT_MODE="shadow")
    def test_published_audit_uses_enforce_under_shadow_and_rejects_configured_mode_drift(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-effective-enforce-shadow",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        self.assertEqual(prepared["configured_rule_mode"], "shadow")
        self.assertEqual(prepared["effective_rule_mode"], "enforce")
        self.assertFalse(
            any(
                issue["code"] in HORSE_ISSUE_CODES
                for issue in prepared["outcomes"][0]["issues"]
            ),
            prepared["outcomes"][0]["issues"],
        )

        with override_settings(ENGLISH_TERM_CONTEXT_MODE="off"):
            with self.assertRaisesRegex(ValueError, "settings|mode|snapshot|drift"):
                apply(
                    dry_run_id=prepared["run_id"],
                    manifest_sha256=prepared["manifest_sha256"],
                    article_ids=[article.id],
                    confirm=True,
                    operator_identity="ops@example.com",
                )

    def test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()

        with CaptureQueriesContext(connection) as captured:
            prepared = dry_run(
                article_ids=[article.id],
                owner_token="published-audit-evidence-snapshots",
                operator_identity="ops@example.com",
                reviewer_identity="reviewer@example.com",
            )

        self.assertLessEqual(len(captured), 35, [query["sql"] for query in captured])
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])
        manifest = run.result_payload["manifest"]
        for key in (
            "external_horse_alias_snapshot_sha256",
            "structured_horse_evidence_snapshot_sha256",
            "article_horse_link_snapshot_sha256",
            "related_region_snapshot_sha256",
            "duplicate_corpus_snapshot_sha256",
        ):
            self.assertRegex(prepared[key], r"^[0-9a-f]{64}$")
            self.assertEqual(manifest[key], prepared[key])
            self.assertEqual(run.result_payload[key], prepared[key])

        result = apply(
            dry_run_id=prepared["run_id"],
            manifest_sha256=prepared["manifest_sha256"],
            article_ids=[article.id],
            confirm=True,
            operator_identity="ops@example.com",
        )
        self.assertEqual(result["updated_article_ids"], [article.id])

    def test_published_audit_apply_fails_closed_on_external_alias_snapshot_drift(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = {
            "gate_issues": json.loads(json.dumps(article.gate_issues)),
            "decision_reason": json.loads(json.dumps(article.decision_reason)),
            "automation_warning_email_signature": article.automation_warning_email_signature,
        }
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-alias-drift",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="sl-post-prepare-alias",
            name_ja="Unrelated Runner",
            name_en="Unrelated Runner",
            normalized_name="Unrelated Runner",
            confidence=98,
            alias_source="post_prepare_test",
        )

        with self.assertRaisesRegex(ValueError, "alias|evidence|snapshot|drift"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        article.refresh_from_db()
        self.assertEqual(article.gate_issues, before["gate_issues"])
        self.assertEqual(article.decision_reason, before["decision_reason"])
        self.assertEqual(
            article.automation_warning_email_signature,
            before["automation_warning_email_signature"],
        )

    def test_published_audit_apply_fails_closed_on_structured_evidence_snapshot_drift(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        event = RaceEvent.objects.create(
            year=2026,
            slug="published-audit-structured-drift",
            original_name="Published Audit Structured Drift",
            chinese_name="发布审计结构化漂移",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="Listed",
            surface=RaceEventSurface.TURF,
        )
        link = ArticleRaceLink.objects.create(
            article=article,
            event=event,
            status=ArticleRaceLinkStatus.AUTO,
        )
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_name="Prepared Runner",
        )
        result_row = RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_name="Prepared Winner",
        )
        before = {
            "gate_issues": json.loads(json.dumps(article.gate_issues)),
            "decision_reason": json.loads(json.dumps(article.decision_reason)),
            "automation_warning_email_signature": article.automation_warning_email_signature,
        }
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-structured-drift",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        link.removed_at = timezone.now()
        link.save(update_fields=["removed_at", "updated_at"])
        runner.horse_name = "Changed Runner"
        runner.save(update_fields=["horse_name", "updated_at"])
        result_row.horse_name = "Changed Winner"
        result_row.save(update_fields=["horse_name", "updated_at"])

        with self.assertRaisesRegex(ValueError, "structured|evidence|snapshot|drift"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        article.refresh_from_db()
        self.assertEqual(article.gate_issues, before["gate_issues"])
        self.assertEqual(article.decision_reason, before["decision_reason"])
        self.assertEqual(
            article.automation_warning_email_signature,
            before["automation_warning_email_signature"],
        )

    def test_published_audit_apply_fails_closed_on_article_horse_link_snapshot_drift(self):
        dry_run, apply = self._audit_api()
        profile = self._dependency_profile()
        article = self._published_article()
        before = self._gate_state(article)
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-horse-link-drift",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        ArticleHorseLink.objects.create(
            article=article,
            horse_profile=profile,
            status=ArticleHorseLinkStatus.AUTO,
            source="post_prepare_test",
            confidence=90,
            matched_text="Snapshot Runner",
        )

        with self.assertRaisesRegex(ValueError, "horse|link|dependency|snapshot|drift"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self._assert_gate_state(article, before)

    def test_published_audit_apply_fails_closed_on_related_region_snapshot_drift(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = self._gate_state(article)
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-region-link-drift",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        NewsArticleRelatedRegion.objects.create(
            article=article,
            region=RacingRegion.FRANCE,
            source="post_prepare_test",
            reason="snapshot drift fixture",
            confidence=80,
        )

        with self.assertRaisesRegex(ValueError, "region|dependency|snapshot|drift"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self._assert_gate_state(article, before)

    def test_published_audit_apply_fails_closed_on_duplicate_corpus_snapshot_drift(self):
        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = self._gate_state(article)
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-duplicate-corpus-drift",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        self._article(
            source_article_id="post-prepare-duplicate-corpus-row",
            title="Completely unrelated international breeding note",
            body="A separate report discussed long-term breeding administration overseas.",
            translated_title_zh="完全无关的海外育种行政消息",
            title_zh="完全无关的海外育种行政消息",
            translated_body_zh="这是一篇与目标文章内容无关的海外育种行政报道。" * 8,
            body_zh="这是一篇与目标文章内容无关的海外育种行政报道。" * 8,
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        with self.assertRaisesRegex(ValueError, "duplicate|corpus|dependency|snapshot|drift"):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self._assert_gate_state(article, before)

    def test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop(self):
        from stable.services import term_gate_reprocessing

        locker = getattr(
            term_gate_reprocessing,
            "_lock_published_audit_evidence_tables",
            None,
        )
        self.assertIsNotNone(
            locker,
            "缺少 PostgreSQL published-audit evidence table lock helper",
        )

        class RecordingCursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, sql, params=None):
                self.statements.append(sql)

        postgres_cursor = RecordingCursor()
        postgres_connection = type(
            "FakeConnection",
            (),
            {
                "vendor": "postgresql",
                "cursor": lambda self: postgres_cursor,
            },
        )()
        with patch.object(
            term_gate_reprocessing,
            "connection",
            postgres_connection,
        ):
            locker()

        lock_sql = " ".join(postgres_cursor.statements)
        self.assertIn("LOCK TABLE", lock_sql.upper())
        expected_tables = {
            ExternalHorseAlias._meta.db_table,
            ArticleHorseLink._meta.db_table,
            ArticleRaceLink._meta.db_table,
            NewsArticleRelatedRegion._meta.db_table,
            RaceEvent._meta.db_table,
            RaceEventRunner._meta.db_table,
            RaceEventResult._meta.db_table,
        }
        lock_clause = re.search(
            r"LOCK\s+TABLE\s+(.*?)\s+IN\s+SHARE\s+ROW\s+EXCLUSIVE\s+MODE",
            lock_sql,
            re.IGNORECASE,
        )
        self.assertIsNotNone(lock_clause, lock_sql)
        locked_tables = {
            identifier
            for identifier in re.findall(
                r'"([^"]+)"',
                lock_clause.group(1),
            )
        }
        self.assertEqual(locked_tables, expected_tables)
        self.assertNotIn(NewsArticle._meta.db_table, locked_tables)

        nonpostgres_cursor = RecordingCursor()
        nonpostgres_connection = type(
            "FakeConnection",
            (),
            {
                "vendor": "sqlite",
                "cursor": lambda self: nonpostgres_cursor,
            },
        )()
        with patch.object(
            term_gate_reprocessing,
            "connection",
            nonpostgres_connection,
        ):
            locker()
        self.assertEqual(nonpostgres_cursor.statements, [])

    def test_published_audit_postgres_article_table_lock_is_exclusive_and_nonpostgres_noop(self):
        from stable.services import term_gate_reprocessing

        locker = getattr(
            term_gate_reprocessing,
            "_lock_published_audit_article_table",
            None,
        )
        self.assertIsNotNone(
            locker,
            "缺少 published-audit NewsArticle table-first lock helper",
        )

        class RecordingCursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, sql, params=None):
                self.statements.append(sql)

        fake_ops = type(
            "FakeOps",
            (),
            {"quote_name": lambda self, value: f'"{value}"'},
        )()
        postgres_cursor = RecordingCursor()
        postgres_connection = type(
            "FakeConnection",
            (),
            {
                "vendor": "postgresql",
                "ops": fake_ops,
                "cursor": lambda self: postgres_cursor,
            },
        )()
        with patch.object(
            term_gate_reprocessing,
            "connection",
            postgres_connection,
        ):
            locker()

        self.assertEqual(len(postgres_cursor.statements), 1)
        lock_sql = postgres_cursor.statements[0]
        self.assertIn("LOCK TABLE", lock_sql.upper())
        self.assertIn(NewsArticle._meta.db_table, lock_sql)
        self.assertIn("IN EXCLUSIVE MODE", lock_sql.upper())
        self.assertNotIn("ACCESS EXCLUSIVE", lock_sql.upper())

        sqlite_cursor = RecordingCursor()
        sqlite_connection = type(
            "FakeConnection",
            (),
            {
                "vendor": "sqlite",
                "ops": fake_ops,
                "cursor": lambda self: sqlite_cursor,
            },
        )()
        with patch.object(
            term_gate_reprocessing,
            "connection",
            sqlite_connection,
        ):
            locker()
        self.assertEqual(sqlite_cursor.statements, [])

    def test_published_audit_article_table_lock_precedes_all_other_locks_and_target_rows(self):
        from stable.services import term_gate_reprocessing

        article_locker = getattr(
            term_gate_reprocessing,
            "_lock_published_audit_article_table",
            None,
        )
        self.assertIsNotNone(
            article_locker,
            "缺少 published-audit NewsArticle table-first lock helper",
        )
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-article-table-lock-order",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        events = []
        outer_atomic_depth = len(connection.atomic_blocks)
        original_context_builder = (
            term_gate_reprocessing.build_validation_batch_context
        )

        def atomic_event(name):
            self.assertGreater(
                len(connection.atomic_blocks),
                outer_atomic_depth,
            )
            events.append(name)

        def context_probe(*args, **kwargs):
            atomic_event("final_context")
            return original_context_builder(*args, **kwargs)

        target_row_seen = False

        def sql_probe(execute, sql, params, many, context):
            nonlocal target_row_seen
            normalized = " ".join(sql.upper().split())
            if (
                not target_row_seen
                and normalized.startswith("SELECT")
                and NewsArticle._meta.db_table.upper() in normalized
            ):
                target_row_seen = True
                atomic_event("target_article_rows")
            if normalized.startswith(
                f'UPDATE "{NewsArticle._meta.db_table.upper()}"'
            ):
                atomic_event("article_update")
            return execute(sql, params, many, context)

        with (
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_article_table",
                side_effect=lambda: atomic_event("article_table_lock"),
            ),
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_evidence_tables",
                side_effect=lambda: atomic_event("evidence_lock"),
            ),
            patch.object(
                term_gate_reprocessing,
                "_lock_term_snapshot_tables",
                side_effect=lambda: atomic_event("term_lock"),
            ),
            patch.object(
                term_gate_reprocessing,
                "build_validation_batch_context",
                side_effect=context_probe,
            ),
            connection.execute_wrapper(sql_probe),
        ):
            result = apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self.assertEqual(result["updated_article_ids"], [article.id])
        for name in (
            "article_table_lock",
            "evidence_lock",
            "term_lock",
            "target_article_rows",
            "final_context",
            "article_update",
        ):
            self.assertEqual(events.count(name), 1, events)
        ordered = [
            events.index(name)
            for name in (
                "article_table_lock",
                "evidence_lock",
                "term_lock",
                "target_article_rows",
                "final_context",
                "article_update",
            )
        ]
        self.assertEqual(ordered, sorted(ordered), events)
        self.assertEqual(len(connection.atomic_blocks), outer_atomic_depth)

    def test_published_audit_article_table_lock_failure_is_zero_update(self):
        from stable.services import term_gate_reprocessing

        locker = getattr(
            term_gate_reprocessing,
            "_lock_published_audit_article_table",
            None,
        )
        self.assertIsNotNone(
            locker,
            "缺少 published-audit NewsArticle table-first lock helper",
        )
        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = self._gate_state(article)
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-article-lock-failure",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        downstream_locks = []
        article_updates = []

        def sql_probe(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(
                'UPDATE "STABLE_NEWSARTICLE"'
            ):
                article_updates.append(sql)
            return execute(sql, params, many, context)

        with (
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_article_table",
                side_effect=DatabaseError("article table lock unavailable"),
            ),
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_evidence_tables",
                side_effect=lambda: downstream_locks.append("evidence"),
            ),
            patch.object(
                term_gate_reprocessing,
                "_lock_term_snapshot_tables",
                side_effect=lambda: downstream_locks.append("term"),
            ),
            connection.execute_wrapper(sql_probe),
            self.assertRaisesRegex(
                DatabaseError,
                "article table lock unavailable",
            ),
        ):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self.assertEqual(downstream_locks, [])
        self.assertEqual(article_updates, [])
        self._assert_gate_state(article, before)
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])
        self.assertEqual(run.status, TermGateReprocessStatus.SUCCEEDED)
        self.assertNotIn("updated_article_ids", run.result_payload)

    def test_published_audit_postgres_term_lock_covers_exact_tables_and_nonpostgres_is_noop(self):
        from stable.services import term_gate_reprocessing

        locker = getattr(
            term_gate_reprocessing,
            "_lock_term_snapshot_tables",
            None,
        )
        self.assertIsNotNone(
            locker,
            "缺少 PostgreSQL term snapshot table lock helper",
        )

        class RecordingCursor:
            def __init__(self):
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, sql, params=None):
                self.statements.append(sql)

        fake_ops = type(
            "FakeOps",
            (),
            {"quote_name": lambda self, value: f'"{value}"'},
        )()
        postgres_cursor = RecordingCursor()
        postgres_connection = type(
            "FakeConnection",
            (),
            {
                "vendor": "postgresql",
                "ops": fake_ops,
                "cursor": lambda self: postgres_cursor,
            },
        )()
        with patch.object(
            term_gate_reprocessing,
            "connection",
            postgres_connection,
        ):
            locker()

        self.assertEqual(len(postgres_cursor.statements), 1)
        lock_sql = postgres_cursor.statements[0]
        self.assertIn("LOCK TABLE", lock_sql.upper())
        self.assertIn("IN SHARE MODE", lock_sql.upper())
        self.assertIn(TermEntry._meta.db_table, lock_sql)
        from stable.models import TermAlias

        self.assertIn(TermAlias._meta.db_table, lock_sql)
        self.assertNotIn(ExternalHorseAlias._meta.db_table, lock_sql)

        nonpostgres_cursor = RecordingCursor()
        nonpostgres_connection = type(
            "FakeConnection",
            (),
            {
                "vendor": "sqlite",
                "ops": fake_ops,
                "cursor": lambda self: nonpostgres_cursor,
            },
        )()
        with patch.object(
            term_gate_reprocessing,
            "connection",
            nonpostgres_connection,
        ):
            locker()
        self.assertEqual(nonpostgres_cursor.statements, [])

    def test_published_audit_term_lock_precedes_final_context_and_article_update_in_atomic(self):
        from stable.services import term_gate_reprocessing

        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-term-lock-order",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        events = []
        outer_atomic_depth = len(connection.atomic_blocks)
        original_context_builder = (
            term_gate_reprocessing.build_validation_batch_context
        )

        def atomic_event(name):
            self.assertGreater(
                len(connection.atomic_blocks),
                outer_atomic_depth,
            )
            events.append(name)

        def evidence_lock_probe():
            atomic_event("evidence_lock")

        def term_lock_probe():
            atomic_event("term_lock")

        def context_probe(*args, **kwargs):
            atomic_event("final_term_context")
            return original_context_builder(*args, **kwargs)

        def sql_probe(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(
                'UPDATE "STABLE_NEWSARTICLE"'
            ):
                atomic_event("article_update")
            return execute(sql, params, many, context)

        with (
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_evidence_tables",
                side_effect=evidence_lock_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "_lock_term_snapshot_tables",
                side_effect=term_lock_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "build_validation_batch_context",
                side_effect=context_probe,
            ),
            connection.execute_wrapper(sql_probe),
        ):
            result = apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self.assertEqual(result["updated_article_ids"], [article.id])
        self.assertEqual(events.count("evidence_lock"), 1, events)
        self.assertEqual(events.count("term_lock"), 1, events)
        self.assertEqual(events.count("final_term_context"), 1, events)
        self.assertGreaterEqual(events.count("article_update"), 1, events)
        self.assertLess(
            events.index("evidence_lock"),
            events.index("term_lock"),
            events,
        )
        self.assertLess(
            events.index("term_lock"),
            events.index("final_term_context"),
            events,
        )
        self.assertLess(
            events.index("final_term_context"),
            events.index("article_update"),
            events,
        )
        self.assertEqual(len(connection.atomic_blocks), outer_atomic_depth)

    def test_published_audit_term_lock_failure_is_zero_update(self):
        from stable.services import term_gate_reprocessing

        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = self._gate_state(article)
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-term-lock-failure",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        article_updates = []

        def sql_probe(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith(
                'UPDATE "STABLE_NEWSARTICLE"'
            ):
                article_updates.append(sql)
            return execute(sql, params, many, context)

        with (
            patch.object(
                term_gate_reprocessing,
                "_lock_term_snapshot_tables",
                side_effect=DatabaseError("term table lock unavailable"),
            ),
            connection.execute_wrapper(sql_probe),
            self.assertRaisesRegex(
                DatabaseError,
                "term table lock unavailable",
            ),
        ):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self.assertEqual(article_updates, [])
        self._assert_gate_state(article, before)
        run = TermGateReprocessRun.objects.get(pk=prepared["run_id"])
        self.assertEqual(run.status, TermGateReprocessStatus.SUCCEEDED)
        self.assertNotIn("updated_article_ids", run.result_payload)

    def test_published_audit_postgres_lock_precedes_final_snapshots_and_article_update_in_atomic(self):
        from stable.services import term_gate_reprocessing

        locker = getattr(
            term_gate_reprocessing,
            "_lock_published_audit_evidence_tables",
            None,
        )
        self.assertIsNotNone(
            locker,
            "缺少 PostgreSQL published-audit evidence table lock helper",
        )
        dry_run, apply = self._audit_api()
        article = self._published_article()
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-lock-order",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
        events = []
        outer_atomic_depth = len(connection.atomic_blocks)
        original_alias_snapshot = (
            term_gate_reprocessing._external_horse_alias_snapshot_sha256
        )
        original_structured_snapshot = (
            term_gate_reprocessing._structured_horse_evidence_snapshot_sha256
        )
        original_horse_link_snapshot = (
            term_gate_reprocessing._article_horse_link_snapshot_sha256
        )
        original_region_snapshot = (
            term_gate_reprocessing._related_region_snapshot_sha256
        )
        original_duplicate_snapshot = (
            term_gate_reprocessing._duplicate_corpus_snapshot_sha256
        )

        def lock_probe():
            self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
            events.append("lock")

        def alias_snapshot_probe():
            self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
            events.append("alias_snapshot")
            return original_alias_snapshot()

        def structured_snapshot_probe(article_ids):
            self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
            events.append("structured_snapshot")
            return original_structured_snapshot(article_ids)

        def horse_link_snapshot_probe(article_ids):
            self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
            events.append("horse_link_snapshot")
            return original_horse_link_snapshot(article_ids)

        def region_snapshot_probe(article_ids):
            self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
            events.append("region_snapshot")
            return original_region_snapshot(article_ids)

        def duplicate_snapshot_probe(*args, **kwargs):
            self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
            events.append("duplicate_snapshot")
            return original_duplicate_snapshot(*args, **kwargs)

        def sql_probe(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith('UPDATE "STABLE_NEWSARTICLE"'):
                self.assertGreater(len(connection.atomic_blocks), outer_atomic_depth)
                events.append("article_update")
            return execute(sql, params, many, context)

        with (
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_evidence_tables",
                side_effect=lock_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "_external_horse_alias_snapshot_sha256",
                side_effect=alias_snapshot_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "_structured_horse_evidence_snapshot_sha256",
                side_effect=structured_snapshot_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "_article_horse_link_snapshot_sha256",
                side_effect=horse_link_snapshot_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "_related_region_snapshot_sha256",
                side_effect=region_snapshot_probe,
            ),
            patch.object(
                term_gate_reprocessing,
                "_duplicate_corpus_snapshot_sha256",
                side_effect=duplicate_snapshot_probe,
            ),
            connection.execute_wrapper(sql_probe),
        ):
            result = apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        self.assertEqual(result["updated_article_ids"], [article.id])
        self.assertEqual(events.count("lock"), 1, events)
        self.assertEqual(events.count("alias_snapshot"), 1, events)
        self.assertEqual(events.count("structured_snapshot"), 1, events)
        self.assertEqual(events.count("horse_link_snapshot"), 1, events)
        self.assertEqual(events.count("region_snapshot"), 1, events)
        self.assertEqual(events.count("duplicate_snapshot"), 1, events)
        self.assertGreaterEqual(events.count("article_update"), 1, events)
        self.assertLess(events.index("lock"), events.index("alias_snapshot"), events)
        self.assertLess(events.index("lock"), events.index("structured_snapshot"), events)
        self.assertLess(events.index("lock"), events.index("horse_link_snapshot"), events)
        self.assertLess(events.index("lock"), events.index("region_snapshot"), events)
        self.assertLess(events.index("lock"), events.index("duplicate_snapshot"), events)
        for snapshot_event in (
            "alias_snapshot",
            "structured_snapshot",
            "horse_link_snapshot",
            "region_snapshot",
            "duplicate_snapshot",
        ):
            self.assertLess(
                events.index(snapshot_event),
                events.index("article_update"),
                events,
            )
        self.assertEqual(len(connection.atomic_blocks), outer_atomic_depth)

    def test_published_audit_postgres_lock_failure_is_fail_closed_before_article_update(self):
        from stable.services import term_gate_reprocessing

        locker = getattr(
            term_gate_reprocessing,
            "_lock_published_audit_evidence_tables",
            None,
        )
        self.assertIsNotNone(
            locker,
            "缺少 PostgreSQL published-audit evidence table lock helper",
        )
        dry_run, apply = self._audit_api()
        article = self._published_article()
        before = {
            "gate_issues": json.loads(json.dumps(article.gate_issues)),
            "decision_reason": json.loads(json.dumps(article.decision_reason)),
            "automation_warning_email_signature": article.automation_warning_email_signature,
        }
        prepared = dry_run(
            article_ids=[article.id],
            owner_token="published-audit-lock-failure",
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )

        with (
            patch.object(
                term_gate_reprocessing,
                "_lock_published_audit_evidence_tables",
                side_effect=DatabaseError("lock unavailable"),
            ),
            self.assertRaisesRegex(DatabaseError, "lock unavailable"),
        ):
            apply(
                dry_run_id=prepared["run_id"],
                manifest_sha256=prepared["manifest_sha256"],
                article_ids=[article.id],
                confirm=True,
                operator_identity="ops@example.com",
            )

        article.refresh_from_db()
        self.assertEqual(article.gate_issues, before["gate_issues"])
        self.assertEqual(article.decision_reason, before["decision_reason"])
        self.assertEqual(
            article.automation_warning_email_signature,
            before["automation_warning_email_signature"],
        )

    @patch(
        "stable.management.commands.reprocess_term_gate_blocked_articles."
        "run_published_term_gate_audit_dry_run"
    )
    def test_published_audit_command_requires_explicit_identities(self, dry_run_mock):
        dry_run_mock.return_value = {
            "run_id": 1,
            "manifest_sha256": "a" * 64,
            "article_ids": [9595],
            "outcomes": [],
        }

        with self.assertRaisesRegex(CommandError, "operator|reviewer|identity"):
            call_command(
                "reprocess_term_gate_blocked_articles",
                "--published-audit",
                "--dry-run",
                "--article-id",
                "9595",
                stdout=StringIO(),
            )

        dry_run_mock.assert_not_called()

    @patch(
        "stable.management.commands.reprocess_term_gate_blocked_articles."
        "run_published_term_gate_audit_dry_run"
    )
    def test_published_audit_command_normalizes_and_forwards_identities(self, dry_run_mock):
        dry_run_mock.return_value = {
            "run_id": 1,
            "manifest_sha256": "a" * 64,
            "article_ids": [9595],
            "outcomes": [],
        }

        call_command(
            "reprocess_term_gate_blocked_articles",
            "--published-audit",
            "--dry-run",
            "--article-id",
            "9595",
            "--operator",
            "  ops@example.com  ",
            "--reviewer",
            "  reviewer@example.com  ",
            stdout=StringIO(),
        )

        dry_run_mock.assert_called_once_with(
            article_ids=[9595],
            owner_token=ANY,
            operator_identity="ops@example.com",
            reviewer_identity="reviewer@example.com",
        )
