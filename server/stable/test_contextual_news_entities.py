from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    ArticleTranslationStatus,
    ExternalHorseAlias,
    HorseProfile,
    HorseProfileStatus,
    NewsArticle,
    NewsSource,
    OperationLog,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
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
from stable.services.translation import OpenAICompatibleTranslationProvider, translate_article
from stable.services.rewriting import FallbackRewriteProvider, OpenAICompatibleRewriteProvider
from stable.services.validation import validate_rewrite


BASE_SETTINGS = {
    "AUTO_DUPLICATE_HIGH_THRESHOLD": 0,
    "AUTO_DUPLICATE_REVIEW_THRESHOLD": 0,
    "AUTO_REWRITE_ENABLED": False,
    "ENGLISH_TERM_CONTEXT_MODE": "enforce",
    "TRANSLATION_MODEL": "test-model",
    "TRANSLATION_MAX_ATTEMPTS": 1,
    "TRANSLATION_UNKNOWN_HORSE_LIMIT": 20,
}


def _resolve(title: str, body: str, language: str):
    from stable.services.terms import resolve_article_entities

    return resolve_article_entities(title, body, source_language=language)


def _entities(resolution, entity_type: str):
    return [item for item in resolution.entities if item.entity_type == entity_type]


def _fake_response(payload: dict):
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


@override_settings(**BASE_SETTINGS)
class ContextualEntityResolutionTests(TestCase):
    def _term(
        self,
        source: str,
        target: str,
        *,
        term_type: str = TermType.HORSE,
        language: str = SourceLanguage.ENGLISH,
        priority: int = 100,
    ) -> TermEntry:
        return TermEntry.objects.create(
            term_type=term_type,
            source_language=language,
            racing_region=RacingRegion.UNITED_KINGDOM if language == SourceLanguage.ENGLISH else RacingRegion.JAPAN,
            source_ja=source,
            target_zh=target,
            priority=priority,
        )

    def test_8317_full_person_and_unique_later_surname_share_translation(self):
        self._term("Donnacha O'Brien", "岳品贤", term_type=TermType.TRAINER)

        resolution = _resolve(
            "Donnacha O'Brien discusses the sale",
            "Donnacha O'Brien inspected the yearling. O'Brien said the colt would race next year.",
            SourceLanguage.ENGLISH,
        )

        people = _entities(resolution, "person")
        self.assertEqual([item.matched_text for item in people], ["Donnacha O'Brien", "Donnacha O'Brien", "O'Brien"])
        self.assertTrue(all(item.target_zh == "岳品贤" for item in people))
        self.assertIn("person_surname_coreference", people[-1].evidence)

    def test_straight_apostrophe_person_term_matches_curly_source_and_surname(self):
        self._term("Donnacha O'Brien", "岳品贤", term_type=TermType.TRAINER)

        resolution = _resolve(
            "Donnacha O’Brien discusses the sale",
            "Donnacha O’Brien inspected the yearling. O’Brien later confirmed the plan.",
            SourceLanguage.ENGLISH,
        )

        people = _entities(resolution, "person")
        self.assertEqual([item.matched_text for item in people], ["Donnacha O’Brien", "Donnacha O’Brien", "O’Brien"])
        self.assertTrue(all(item.target_zh == "岳品贤" for item in people))

    def test_8309_job_context_marks_grace_hamilton_as_person_and_suppresses_horse(self):
        hamilton = self._term("Hamilton", "汉密尔顿")

        resolution = _resolve(
            "Grace Hamilton Joins Four Star Sales As Bloodstock And Sales Coordinator",
            (
                "Grace Hamilton has joined Four Star Sales as Bloodstock and Sales Coordinator. "
                "The company announced on Monday. Hamilton joins Four Star following graduation."
            ),
            SourceLanguage.ENGLISH,
        )

        people = _entities(resolution, "person")
        self.assertEqual([item.matched_text for item in people], ["Grace Hamilton", "Grace Hamilton", "Hamilton"])
        self.assertTrue(all(item.canonical_text == "Grace Hamilton" for item in people))
        self.assertFalse(_entities(resolution, "horse"))
        suppressed = [item for item in resolution.suppressed_candidates if item.term_id == hamilton.id]
        self.assertTrue(suppressed)
        self.assertIn("inside_person_span", suppressed[0].conflict_flags)

    def test_same_surname_for_two_people_is_not_auto_coreferenced(self):
        self._term("Alice Smith", "艾丽斯史密斯", term_type=TermType.JOCKEY)
        self._term("Bob Smith", "鲍勃史密斯", term_type=TermType.TRAINER)

        resolution = _resolve(
            "Alice Smith and Bob Smith attend",
            "Alice Smith spoke before Bob Smith arrived. Smith later declined to comment.",
            SourceLanguage.ENGLISH,
        )

        surname_people = [item for item in _entities(resolution, "person") if item.matched_text == "Smith"]
        self.assertEqual(surname_people, [])
        self.assertTrue(any("ambiguous_person_surname" in item.conflict_flags for item in resolution.suppressed_candidates))

    def test_surname_before_first_full_name_is_not_coreferenced_backwards(self):
        self._term("Donnacha O'Brien", "岳品贤", term_type=TermType.TRAINER)

        resolution = _resolve(
            "O'Brien stable update",
            "Donnacha O'Brien later confirmed the plan. O'Brien said the colt would run.",
            SourceLanguage.ENGLISH,
        )

        title_people = [item for item in _entities(resolution, "person") if item.field_name == "title"]
        self.assertEqual(title_people, [])
        self.assertTrue(any("surname_before_full_name" in item.conflict_flags for item in resolution.suppressed_candidates))

    def test_8086_common_phrases_are_not_horses_but_do_deuce_remains_a_horse(self):
        ordinary = {
            "enough": "够分量",
            "years": "好年月",
            "contact": "常联系",
            "step forward": "加快步",
            "significant figures": "有效数字",
            "winning streak": "连捷",
            "positive": "乐观正面",
            "sign": "先兆",
            "Significantly": "够分量",
            "Falcon May": "猎鹰五月",
        }
        for source, target in ordinary.items():
            self._term(source, target)
        self._term("Do Deuce", "多爵")
        body = (
            "There was more than enough time as the years roll on. We stayed in contact and took a step forward. "
            "The significant figures ended a winning streak, but the team moved significantly faster and stayed positive. "
            "It was a sign, Falcon May wrote. "
            "Do Deuce won the race under his jockey and will run again next month."
        )

        resolution = _resolve("A racing life remembered", body, SourceLanguage.ENGLISH)

        horses = _entities(resolution, "horse")
        self.assertEqual([(item.matched_text, item.target_zh) for item in horses], [("Do Deuce", "多爵")])
        common_targets = {item.target_zh for item in _entities(resolution, "common_word")}
        self.assertTrue(
            set(ordinary.values()).issubset(common_targets),
            [(item.matched_text, item.target_zh, item.entity_type, item.evidence) for item in resolution.entities],
        )

    def test_8318_more_than_enough_is_common_in_body_and_machine_tags(self):
        self._term("more than enough", "好运宝宝")
        resolution = _resolve(
            "Connections have time",
            "There is more than enough time to make a decision after the meeting.",
            SourceLanguage.ENGLISH,
        )

        from stable.services.terms import extract_horse_tags

        self.assertEqual(_entities(resolution, "horse"), [])
        self.assertEqual(extract_horse_tags("", entity_resolution=resolution), [])

    def test_title_case_common_phrase_is_not_promoted_without_horse_action(self):
        self._term("More Than Enough", "好运宝宝")

        resolution = _resolve(
            "More Than Enough Time for a Decision",
            "Connections still have more than enough time before the meeting.",
            SourceLanguage.ENGLISH,
        )

        self.assertEqual(_entities(resolution, "horse"), [])
        self.assertTrue(any(item.matched_text == "More Than Enough" for item in _entities(resolution, "common_word")))

    def test_8330_all_ordinary_matches_produce_no_horse_entities_or_tags(self):
        for source, target in {
            "content": "内容",
            "type": "类型",
            "open": "公开赛",
            "class": "班次",
            "live": "生活",
            "number": "号码",
            "rating": "评分",
            "son": "儿子",
        }.items():
            self._term(source, target)
        body = "This type of content is open to the public. The live class number and rating belong to his son."

        resolution = _resolve("Sales report", body, SourceLanguage.ENGLISH)

        self.assertEqual(_entities(resolution, "horse"), [])
        self.assertTrue(_entities(resolution, "common_word"))
        self.assertEqual(resolution.machine_horse_tags, [])

    def test_automation_priority_uses_contextual_horses_not_raw_term_hits(self):
        self._term("more than enough", "好运宝宝")
        self._term("Do Deuce", "多爵")
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="automation-contextual-horses",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Do Deuce returns",
            body_ja_raw="There is more than enough time. Do Deuce won the race under his jockey.",
            body_ja_normalized="There is more than enough time. Do Deuce won the race under his jockey.",
            published_at=timezone.now(),
            source_url="https://example.com/automation/contextual-horses",
        )

        from stable.services.automation import p0_horse_hits

        hits = p0_horse_hits(article)

        self.assertEqual([item["target_zh"] for item in hits], ["多爵"])

    def test_distinctive_horse_metaphor_keeps_dayjur_without_upgrading_ordinary_words(self):
        self._term("Dayjur", "多爵")
        self._term("the years", "好年月")

        resolution = _resolve(
            "A racing life remembered",
            "The years roll on as the younger men channel their inner Dayjur across the field.",
            SourceLanguage.ENGLISH,
        )

        self.assertEqual([(item.matched_text, item.target_zh) for item in _entities(resolution, "horse")], [("Dayjur", "多爵")])
        self.assertTrue(any(item.matched_text == "The years" for item in _entities(resolution, "common_word")))

    def test_organization_and_distance_number_are_not_strong_horse_context(self):
        self._term("Nyra", "年华")
        self._term("Miles", "道远千里")

        resolution = _resolve(
            "Distance change at Saratoga",
            "NYRA ran two similar races before changing the distance from a mile to 1 1/16 miles for safety.",
            SourceLanguage.ENGLISH,
        )

        self.assertEqual(_entities(resolution, "horse"), [])
        self.assertEqual({item.matched_text.casefold() for item in _entities(resolution, "common_word")}, {"nyra", "miles"})

    def test_strong_racecard_and_result_context_can_upgrade_same_shape_horse(self):
        self._term("Contact", "常联系")

        resolution = _resolve(
            "Ascot declarations",
            "4 Contact (IRE), colt, stall 6, odds 7/2. Contact won the race under Ryan Moore.",
            SourceLanguage.ENGLISH,
        )

        horses = _entities(resolution, "horse")
        self.assertTrue(horses)
        self.assertTrue(all("strong_horse_context" in item.evidence for item in horses))

    def test_resolution_is_deterministic_and_serializable(self):
        self._term("Hamilton", "汉密尔顿")
        first = _resolve(
            "Grace Hamilton joins",
            "Grace Hamilton has joined the team as Sales Coordinator.",
            SourceLanguage.ENGLISH,
        )
        second = _resolve(
            "Grace Hamilton joins",
            "Grace Hamilton has joined the team as Sales Coordinator.",
            SourceLanguage.ENGLISH,
        )

        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(json.loads(json.dumps(first.as_dict(), ensure_ascii=False)), first.as_dict())


@override_settings(**BASE_SETTINGS)
class JapaneseCompleteHorseNameTests(TestCase):
    def _internal_term(self, source: str, target: str) -> None:
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja=source,
            target_zh=target,
            priority=100,
        )

    def setUp(self):
        self._internal_term("モーニン", "爵士蓝调")
        self._internal_term("アスク", "请问")
        self._internal_term("フォリー", "青草地")
        self._internal_term("アーヴル", "阿弗尔")
        self._internal_term("ユーロ", "你最好")

    def test_problem_article_full_names_are_protected_and_internal_terms_suppressed(self):
        names = ["ノリヤンモーニン", "マドモアゼルアスク", "プティフォリー", "ルアーヴル", "ユーロファルコン"]
        for name in names:
            with self.subTest(name=name):
                resolution = _resolve(f"{name}が出走", f"1番 {name}（牡3）は追い切りを行った。", SourceLanguage.JAPANESE)
                protected = [item for item in resolution.entities if item.matched_text == name]
                self.assertTrue(protected)
                self.assertEqual(protected[0].entity_type, "unknown_horse")
                self.assertTrue(protected[0].needs_preserve)
                self.assertTrue(any("inside_longer_entity" in item.conflict_flags for item in resolution.suppressed_candidates))

    def test_racecard_unknown_horse_keeps_the_full_original_name(self):
        resolution = _resolve(
            "新馬戦の出馬表",
            "1枠1番 アカツキユーロ 牡3 ○○ 56.0kg",
            SourceLanguage.JAPANESE,
        )

        protected = [item for item in resolution.entities if item.matched_text == "アカツキユーロ"]
        self.assertEqual(len(protected), 1)
        self.assertEqual(protected[0].entity_type, "unknown_horse")
        self.assertTrue(protected[0].needs_preserve)

    def test_racecard_unknown_horse_without_any_internal_term_is_still_preserved(self):
        resolution = _resolve(
            "新馬戦の出馬表",
            "2枠3番 アカツキホープ 牡3 ○○ 56.0kg",
            SourceLanguage.JAPANESE,
        )

        protected = [item for item in resolution.entities if item.matched_text == "アカツキホープ"]
        self.assertEqual(len(protected), 1)
        self.assertEqual(protected[0].entity_type, "unknown_horse")
        self.assertTrue(protected[0].needs_preserve)

    def test_non_horse_fixed_phrase_in_title_is_not_protected_as_unknown_horse(self):
        TermEntry.objects.create(
            term_type=TermType.FIXED_PHRASE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="タイプ",
            target_zh="类型",
            notes="non_horse_common_word",
            priority=100,
        )

        resolution = _resolve("タイプを解説", "このタイプはコースに合う。", SourceLanguage.JAPANESE)

        self.assertFalse(any(item.matched_text == "タイプ" and item.entity_type == "unknown_horse" for item in resolution.entities))

    def test_japanese_sale_words_and_expectation_are_not_horse_entities(self):
        for source, target in {
            "セレクトセール": "精选拍卖会",
            "セール": "拍卖会",
            "期待": "期待",
            "豪快": "豪迈",
        }.items():
            self._internal_term(source, target)
        ExternalHorseAlias.objects.create(
            source="fixture",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            external_horse_id="SESSION-1",
            name_ja="セッション",
            normalized_name="セッション",
            confidence=100,
        )

        resolution = _resolve(
            "セレクトセール2026",
            "今年のセレクトセール当歳セッションでは、豪快な走りへの期待が集まる。",
            SourceLanguage.JAPANESE,
        )

        rejected = {"セレクトセール", "セール", "セッション", "豪快", "期待"}
        self.assertFalse(
            any(
                item.matched_text in rejected and item.entity_type in {"horse", "unknown_horse"}
                for item in resolution.entities
            )
        )
        self.assertEqual(resolution.machine_horse_tags, [])

    def test_katakana_name_before_jockey_role_is_a_person_not_a_horse(self):
        self._internal_term("スミヨン", "苏铭伦")
        self._internal_term("クリストフ", "基斯杜化")
        self._internal_term("ユー", "你")

        resolution = _resolve(
            "ジャンプラ賞結果",
            "クリストフ・スミヨン騎手が勝利した。陣営はクリストフを称賛し、40万ユーロの賞金を獲得した。",
            SourceLanguage.JAPANESE,
        )

        people = _entities(resolution, "person")
        self.assertTrue(any(item.matched_text == "クリストフ・スミヨン" for item in people))
        self.assertTrue(
            any(
                item.matched_text == "クリストフ" and "japanese_person_coreference" in item.evidence
                for item in people
            )
        )
        self.assertFalse(
            any(item.matched_text in {"クリストフ", "スミヨン", "ユーロ", "ユー"} for item in _entities(resolution, "horse"))
        )
        self.assertFalse(
            any(
                item.matched_text in {"クリストフ", "スミヨン", "ユーロ", "ユー"}
                for item in _entities(resolution, "unknown_horse")
            )
        )
        self.assertTrue(
            any(
                item.matched_text == "ユー" and "inside_common_word_span" in item.conflict_flags
                for item in resolution.suppressed_candidates
            )
        )

    def test_exact_katakana_fixed_phrase_is_resolved_as_term_without_special_note(self):
        term = TermEntry.objects.create(
            term_type=TermType.FIXED_PHRASE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="セレクトセール",
            target_zh="精选拍卖会",
            priority=100,
        )

        resolution = _resolve(
            "セレクトセールが開幕",
            "セレクトセールの初日が行われた。",
            SourceLanguage.JAPANESE,
        )

        matched = [item for item in resolution.entities if item.term_id == term.id]
        self.assertEqual([item.entity_type for item in matched], ["term", "term"])
        self.assertFalse(any(item.matched_text == "セレクトセール" and item.entity_type == "unknown_horse" for item in resolution.entities))

    def test_japanese_source_can_resolve_latin_formal_term(self):
        term = TermEntry.objects.create(
            term_type=TermType.FARM,
            source_language=SourceLanguage.JAPANESE,
            source_ja="Shadai",
            target_zh="社台",
            priority=100,
        )

        resolution = _resolve(
            "Shadaiのセール情報",
            "Shadaiは今年の販売計画を発表した。",
            SourceLanguage.JAPANESE,
        )

        matched = [item for item in resolution.entities if item.term_id == term.id]
        self.assertEqual([item.matched_text for item in matched], ["Shadai", "Shadai"])
        self.assertTrue(all(item.target_zh == "社台" for item in matched))

    def test_full_horse_suppresses_internal_fixed_phrase_term(self):
        TermEntry.objects.filter(source_ja="アスク").update(term_type=TermType.FIXED_PHRASE)

        resolution = _resolve(
            "追い切り情報",
            "1番 マドモアゼルアスク（牝3）が追い切りを行った。",
            SourceLanguage.JAPANESE,
        )

        full = [item for item in resolution.entities if item.matched_text == "マドモアゼルアスク"]
        suppressed = [item for item in resolution.suppressed_candidates if item.matched_text == "アスク"]
        self.assertEqual(full[0].entity_type, "unknown_horse")
        self.assertEqual(suppressed[0].term_type, TermType.FIXED_PHRASE)
        self.assertIn("inside_longer_entity", suppressed[0].conflict_flags)

    def test_provider_maps_accepted_terms_before_restoring_full_horse_placeholder(self):
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="8291-placeholder-order",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            title_ja="ノリヤンモーニンが出走",
            body_ja_raw="1番 ノリヤンモーニン（牡3）が出走する。",
            body_ja_normalized="1番 ノリヤンモーニン（牡3）が出走する。",
            published_at=timezone.now(),
            source_url="https://example.com/8291",
        )
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        response = _fake_response(
            {
                "title_zh": "__UMA_KEEP_1__出战",
                "body_zh": "1号 __UMA_KEEP_1__（公马，3岁）出战。",
                "push_summary_zh": "__UMA_KEEP_1__出战。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertIn("ノリヤンモーニン", result.body_zh)
        self.assertNotIn("ノリヤン爵士蓝调", result.body_zh)
        self.assertEqual(result.metadata["machine_horse_tags"], ["ノリヤンモーニン"])

    def test_title_and_body_share_one_placeholder_namespace(self):
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="placeholder-namespace",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            title_ja="ノリヤンモーニンが出走",
            body_ja_raw="1番 プティフォリー（牝3）が出走する。",
            body_ja_normalized="1番 プティフォリー（牝3）が出走する。",
            published_at=timezone.now(),
            source_url="https://example.com/placeholder-namespace",
        )
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        response = _fake_response(
            {
                "title_zh": "__UMA_KEEP_1__出战",
                "body_zh": "1号 __UMA_KEEP_2__（母马，3岁）出战。",
                "push_summary_zh": "__UMA_KEEP_1__与__UMA_KEEP_2__出战。",
            }
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertIn("ノリヤンモーニン", result.title_zh)
        self.assertIn("プティフォリー", result.body_zh)
        self.assertEqual(
            result.metadata["unknown_horse_placeholders"],
            {"__UMA_KEEP_1__": "ノリヤンモーニン", "__UMA_KEEP_2__": "プティフォリー"},
        )

    def test_publish_gate_ignores_internal_horse_term_suppressed_by_full_name(self):
        source_body = "1番 ノリヤンモーニン（牡3）が出走する。今週は順調に追い切りを終え、陣営が状態を説明した。"
        published_body = "1号ノリヤンモーニン（公马，3岁）将参赛。该马本周顺利完成追切，团队介绍了备战状态。" * 3
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="gate-full-horse-name",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            title_ja="ノリヤンモーニンが出走",
            body_ja_raw=source_body,
            body_ja_normalized=source_body,
            translated_title_zh="ノリヤンモーニン将参赛",
            translated_body_zh=published_body,
            translated_summary_zh="ノリヤンモーニン将参赛。",
            title_zh="ノリヤンモーニン将参赛",
            body_zh=published_body,
            summary_zh="ノリヤンモーニン将参赛。",
            published_at=timezone.now(),
            source_url="https://example.com/gate/full-horse",
        )

        outcome = validate_rewrite(article)

        self.assertNotIn("モーニン", outcome.details["missing_known_terms"])
        self.assertFalse(
            any(
                issue["code"] in {"core_term_missing", "background_term_missing"}
                and issue.get("payload", {}).get("source_ja") == "モーニン"
                for issue in outcome.issues
            )
        )


@override_settings(**BASE_SETTINGS)
class ContextualTranslationConsistencyTests(TestCase):
    def _article(self, title: str, body: str) -> NewsArticle:
        return NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id=f"translation-context-{NewsArticle.objects.count() + 1}",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja=title,
            body_ja_raw=body,
            body_ja_normalized=body,
            published_at=timezone.now(),
            source_url=f"https://example.com/context/{NewsArticle.objects.count() + 1}",
        )

    def test_translation_run_prompt_and_metadata_share_the_same_accepted_terms(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="more than enough",
            target_zh="好运宝宝",
            priority=100,
        )
        article = self._article("Stable update", "There is more than enough time to decide after the sale.")
        response = _fake_response(
            {"title_zh": "马房动态", "body_zh": "拍卖后仍有充足时间决定。", "push_summary_zh": "仍有充足时间。"}
        )
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")

        with patch("stable.services.translation.get_translation_provider", return_value=provider), patch.object(
            provider, "_request_completion", return_value=response
        ):
            result = translate_article(article)

        run = article.translation_runs.get()
        self.assertEqual(run.terms_used, result.metadata["terms"])
        self.assertEqual(run.terms_used, [])
        self.assertFalse(any(item.get("target_zh") == "好运宝宝" for item in result.metadata["terms"]))

    def test_person_surname_coreference_is_available_to_prompt_and_final_mapping(self):
        TermEntry.objects.create(
            term_type=TermType.TRAINER,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Donnacha O'Brien",
            target_zh="岳品贤",
            priority=100,
        )
        article = self._article(
            "Donnacha O'Brien talks",
            "Donnacha O'Brien inspected the colt. O'Brien said the horse would run next month.",
        )
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        response = _fake_response(
            {"title_zh": "Donnacha O'Brien谈计划", "body_zh": "Donnacha O'Brien检视了马匹。O'Brien表示下月参赛。", "push_summary_zh": "O'Brien谈计划。"}
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertNotIn("O'Brien", result.body_zh)
        self.assertIn("岳品贤", result.body_zh)
        self.assertTrue(any(item.get("evidence") == ["person_surname_coreference"] for item in result.metadata["entities"]))

    def test_fallback_rewrite_does_not_reintroduce_rejected_horse_mapping(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="more than enough",
            target_zh="好运宝宝",
            priority=100,
        )
        article = self._article("Stable update", "There is more than enough time to decide.")
        article.translated_title_zh = "马房动态"
        article.translated_body_zh = "There is more than enough time to decide."
        article.translated_summary_zh = "There is more than enough time."
        provider = FallbackRewriteProvider()

        result = provider.rewrite(article)

        self.assertNotIn("好运宝宝", result.body_zh)
        self.assertIn("more than enough time", result.body_zh)

    def test_rewrite_prompt_uses_only_contextually_accepted_terms(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="more than enough",
            target_zh="好运宝宝",
            priority=100,
        )
        article = self._article("Stable update", "There is more than enough time to decide.")
        article.translated_title_zh = "马房动态"
        article.translated_body_zh = "仍有充足时间决定。"
        provider = OpenAICompatibleRewriteProvider(api_key="test", base_url="https://example.com/v1")

        prompt = provider._messages(article)[1]["content"]

        self.assertNotIn("more than enough => 好运宝宝", prompt)

    def test_rewrite_restores_full_unknown_japanese_horse_placeholder(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="モーニン",
            target_zh="爵士蓝调",
            priority=100,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="rewrite-full-horse-placeholder",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            title_ja="ノリヤンモーニンが出走",
            body_ja_raw="1番 ノリヤンモーニン（牡3）が出走する。",
            body_ja_normalized="1番 ノリヤンモーニン（牡3）が出走する。",
            translated_title_zh="ノリヤンモーニン出战",
            translated_body_zh="1号ノリヤンモーニン（公马，3岁）出战。",
            published_at=timezone.now(),
            source_url="https://example.com/rewrite/full-horse",
        )
        provider = OpenAICompatibleRewriteProvider(api_key="test", base_url="https://example.com/v1")
        response = _fake_response(
            {
                "rewrite_title_zh": "__UMA_KEEP_1__出战",
                "rewrite_summary_zh": "__UMA_KEEP_1__将出战。",
                "rewrite_body_zh": "1号__UMA_KEEP_1__（公马，3岁）将出战。",
                "rewrite_confidence": 91,
            }
        )

        with patch.object(provider.client.chat.completions, "create", return_value=response):
            result = provider.rewrite(article)

        self.assertIn("ノリヤンモーニン", result.body_zh)
        self.assertNotIn("ノリヤン爵士蓝调", result.body_zh)
        self.assertNotIn("__UMA_KEEP_", result.body_zh)


@override_settings(**BASE_SETTINGS)
class FormalLanguageEntityResolutionTests(TestCase):
    def test_traditional_chinese_horse_term_uses_formal_resolution(self):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.CHINESE_TRADITIONAL,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="春秋分",
            target_zh="春秋分",
            priority=100,
        )

        resolution = _resolve(
            "春秋分退役消息",
            "春秋分已完成競賽生涯，之後將轉任種馬。",
            SourceLanguage.CHINESE_TRADITIONAL,
        )

        matched = [item for item in resolution.entities if item.term_id == term.id]
        self.assertEqual([item.matched_text for item in matched], ["春秋分", "春秋分"])
        self.assertTrue(all(item.entity_type == "horse" for item in matched))
        self.assertEqual(resolution.machine_horse_tags, ["春秋分"])


@override_settings(**BASE_SETTINGS)
class MachineTagsLinksAndValidationTests(TestCase):
    def _article(self, *, body: str, **overrides) -> NewsArticle:
        defaults = {
            "source_site": SourceSite.TDN,
            "source_mode": SourceMode.LATEST,
            "source_article_id": f"entity-output-{NewsArticle.objects.count() + 1}",
            "source_language": SourceLanguage.ENGLISH,
            "racing_region": RacingRegion.UNITED_STATES,
            "title_ja": "Stable update",
            "body_ja_raw": body,
            "body_ja_normalized": body,
            "translated_title_zh": "马房动态",
            "title_zh": "马房动态",
            "translated_body_zh": "这是一篇完整的赛马新闻正文，介绍赛事安排与相关人员的最新动态。" * 5,
            "body_zh": "这是一篇完整的赛马新闻正文，介绍赛事安排与相关人员的最新动态。" * 5,
            "translated_summary_zh": "最新动态",
            "summary_zh": "最新动态",
            "published_at": timezone.now(),
            "source_url": f"https://example.com/output/{NewsArticle.objects.count() + 1}",
            "workflow_status": WorkflowStatus.PUBLISHED,
            "published_to_web_at": timezone.now(),
            "translation_status": ArticleTranslationStatus.TRANSLATED,
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def _profile(self, source: str, target: str) -> HorseProfile:
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja=source,
            target_zh=target,
            priority=100,
        )
        return HorseProfile.objects.create(
            primary_term=term,
            display_name_zh=target,
            original_name=source,
            english_name=source,
            racing_region=RacingRegion.UNITED_STATES,
            review_status=HorseProfileStatus.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_machine_tag_provenance_replaces_only_previous_machine_tags_and_keeps_defaults(self):
        source = NewsSource.objects.create(
            name="TDN test",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            default_tags=["国际"],
        )
        article = self._article(
            body="There is more than enough time.",
            source_config=source,
            tags_json=["国际", "好运宝宝", "专题"],
            translation_metadata={"machine_horse_tags": ["好运宝宝"]},
        )
        result = type(
            "Result",
            (),
            {
                "title_zh": "马房动态",
                "body_zh": "仍有充足时间。",
                "push_summary_zh": "仍有时间。",
                "metadata": {"provider": "test", "model": "test", "machine_horse_tags": []},
            },
        )()

        article.apply_translation_result(result, force=True)

        self.assertEqual(article.tags_json, ["国际", "专题"])

    def test_force_translation_never_overwrites_manually_locked_tags(self):
        article = self._article(
            body="Do Deuce won the race.",
            tags_json=["人工马名"],
            manually_edited_fields=["tags_json"],
        )
        result = type(
            "Result",
            (),
            {
                "title_zh": "多爵取胜",
                "body_zh": "多爵取胜。",
                "push_summary_zh": "多爵取胜。",
                "metadata": {"provider": "test", "model": "test", "machine_horse_tags": ["多爵"]},
            },
        )()

        article.apply_translation_result(result, force=True)

        self.assertEqual(article.tags_json, ["人工马名"])

    def test_ensure_editable_fields_records_machine_tag_provenance(self):
        self._profile("Do Deuce", "多爵")
        article = self._article(body="Do Deuce won the race under his jockey.", workflow_status=WorkflowStatus.PENDING_EDIT)

        article.ensure_editable_fields()

        self.assertEqual(article.tags_json, ["多爵"])
        self.assertEqual(article.translation_metadata["machine_horse_tags"], ["多爵"])

    def test_reconcile_links_deletes_stale_auto_candidate_and_preserves_manual_removed(self):
        from stable.services.horse_profiles import reconcile_article_horse_links

        article = self._article(body="There is more than enough time to decide.")
        profiles = [
            self._profile("Enough", "够分量"),
            self._profile("Years", "好年月"),
            self._profile("Contact", "常联系"),
            self._profile("Sign", "先兆"),
        ]
        statuses = [
            ArticleHorseLinkStatus.AUTO,
            ArticleHorseLinkStatus.CANDIDATE,
            ArticleHorseLinkStatus.MANUAL,
            ArticleHorseLinkStatus.REMOVED,
        ]
        for profile, status in zip(profiles, statuses, strict=True):
            ArticleHorseLink.objects.create(article=article, horse_profile=profile, status=status)
        resolution = _resolve(article.title_ja, article.body_ja_normalized, SourceLanguage.ENGLISH)

        dry_run = reconcile_article_horse_links(article, resolution, commit=False)
        self.assertEqual(set(dry_run["delete_ids"]), set(ArticleHorseLink.objects.filter(status__in=statuses[:2]).values_list("id", flat=True)))
        self.assertEqual(ArticleHorseLink.objects.filter(article=article).count(), 4)
        self.assertEqual(
            {item["status"] for item in dry_run["protected"]},
            {ArticleHorseLinkStatus.MANUAL, ArticleHorseLinkStatus.REMOVED},
        )

        reconcile_article_horse_links(article, resolution, commit=True)
        remaining = set(ArticleHorseLink.objects.filter(article=article).values_list("status", flat=True))
        self.assertEqual(remaining, {ArticleHorseLinkStatus.MANUAL, ArticleHorseLinkStatus.REMOVED})

    def test_validation_reports_machine_entity_type_mismatch_without_dropping_other_blockers(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="more than enough",
            target_zh="好运宝宝",
            priority=100,
        )
        article = self._article(
            body="There is more than enough time to decide after the meeting. " * 6,
            tags_json=["好运宝宝"],
            title_zh="",
            translated_title_zh="",
        )

        outcome = validate_rewrite(article)
        codes = {issue["code"] for issue in outcome.issues}

        self.assertIn("machine_entity_type_mismatch", codes)
        self.assertIn("missing_title", codes)

    def test_validation_reports_horse_candidate_suppressed_inside_person_span(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Hamilton",
            target_zh="汉密尔顿",
            priority=100,
        )
        article = self._article(
            title_ja="Grace Hamilton joins Four Star Sales",
            body="Grace Hamilton has joined Four Star Sales as Bloodstock and Sales Coordinator. " * 5,
            tags_json=["汉密尔顿"],
        )

        outcome = validate_rewrite(article)

        mismatch = [issue for issue in outcome.issues if issue["code"] == "machine_entity_type_mismatch"]
        self.assertEqual(mismatch[0]["payload"]["tags"], ["汉密尔顿"])

    def test_validation_keeps_machine_tag_when_same_horse_is_accepted_elsewhere(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Do Deuce",
            target_zh="多爵",
            priority=100,
        )
        article = self._article(
            title_ja="Do Deuce won the race",
            body=("The report mentioned Do Deuce before reviewing the meeting. " * 6),
            tags_json=["多爵"],
            translation_metadata={"machine_horse_tags": ["多爵"]},
        )

        outcome = validate_rewrite(article)

        self.assertNotIn("machine_entity_type_mismatch", {issue["code"] for issue in outcome.issues})


@override_settings(**BASE_SETTINGS)
class ContextualEntityBatchTests(TestCase):
    def _articles(self, count: int) -> list[NewsArticle]:
        return [
            NewsArticle.objects.create(
                source_site=SourceSite.TDN,
                source_mode=SourceMode.LATEST,
                source_article_id=f"batch-entity-{index}",
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_STATES,
                title_ja=f"Runner {index} update",
                body_ja_raw=f"Runner {index} won the race under its jockey.",
                body_ja_normalized=f"Runner {index} won the race under its jockey.",
                published_at=timezone.now(),
                source_url=f"https://example.com/batch/{index}",
            )
            for index in range(count)
        ]

    def test_ten_and_twenty_article_batches_use_the_same_bounded_term_alias_queries(self):
        from stable.services.terms import resolve_article_entities_batch

        for index in range(20):
            term = TermEntry.objects.create(
                term_type=TermType.HORSE,
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_STATES,
                source_ja=f"Runner {index}",
                target_zh=f"赛驹{index}",
                priority=100,
            )
            TermAlias.objects.create(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text=f"Runner {index}",
                alias_type=TermAliasType.PRIMARY,
            )
            ExternalHorseAlias.objects.create(
                source="fixture",
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_STATES,
                external_horse_id=f"EXT-{index}",
                name_en=f"Runner {index}",
                normalized_name=f"Runner {index}",
                confidence=95,
            )
        articles = self._articles(20)

        with CaptureQueriesContext(connection) as ten_queries:
            ten = resolve_article_entities_batch(articles[:10])
        with CaptureQueriesContext(connection) as twenty_queries:
            twenty = resolve_article_entities_batch(articles)

        self.assertEqual(len(ten), 10)
        self.assertEqual(len(twenty), 20)
        self.assertLessEqual(len(ten_queries), 8)
        self.assertEqual(len(ten_queries), len(twenty_queries))


@override_settings(**BASE_SETTINGS)
class ReprocessArticleEntitiesCommandTests(TestCase):
    def _article(self, source_id: str, *, body: str = "There is more than enough time to decide.") -> NewsArticle:
        published_at = timezone.now()
        return NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id=source_id,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Stable update",
            body_ja_raw=body,
            body_ja_normalized=body,
            translated_title_zh="马房动态",
            translated_body_zh="仍有充足时间。",
            translated_summary_zh="仍有时间。",
            title_zh="马房动态",
            body_zh="仍有充足时间。",
            summary_zh="仍有时间。",
            push_summary_zh="仍有时间。",
            tags_json=["好运宝宝"],
            translation_metadata={"machine_horse_tags": ["好运宝宝"]},
            published_at=published_at,
            source_url=f"https://example.com/reprocess/{source_id}",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=published_at,
            translation_status=ArticleTranslationStatus.TRANSLATED,
        )

    def setUp(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="more than enough",
            target_zh="好运宝宝",
            priority=100,
        )

    def _command(self, *args: str) -> dict:
        stdout = StringIO()
        call_command("reprocess_article_entities", *args, "--json", stdout=stdout)
        return json.loads(stdout.getvalue())

    def test_default_dry_run_reports_diffs_without_database_writes(self):
        article = self._article("8318-dry-run")

        payload = self._command("--article-id", str(article.id))

        article.refresh_from_db()
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["articles"][0]["tags"]["delete"], ["好运宝宝"])
        self.assertEqual(article.tags_json, ["好运宝宝"])
        self.assertFalse(OperationLog.objects.filter(action_type="article_entities_reprocessed").exists())

    def test_dry_run_cleans_legacy_horse_targets_even_with_incomplete_provenance(self):
        article = self._article("8318-incomplete-provenance")
        article.tags_json = ["好运宝宝", "专题"]
        article.translation_metadata = {"machine_horse_tags": ["已替换机器标签"]}
        article.save(update_fields=["tags_json", "translation_metadata", "updated_at"])

        payload = self._command("--article-id", str(article.id))

        article.refresh_from_db()
        self.assertEqual(payload["articles"][0]["tags"]["delete"], ["好运宝宝"])
        self.assertEqual(payload["articles"][0]["tags"]["after"], ["专题"])
        self.assertEqual(article.tags_json, ["好运宝宝", "专题"])

    def test_commit_preserves_public_identity_time_and_qq_delivery(self):
        article = self._article("8318-commit")
        before_time = article.published_to_web_at
        target = PushTarget.objects.create(name="Existing", group_id="entity-existing")
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            message_id="sent-before-reprocess",
            sent_at=timezone.now(),
        )

        payload = self._command("--article-id", str(article.id), "--commit")

        article.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual(payload["mode"], "commit")
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.published_to_web_at, before_time)
        self.assertEqual(article.tags_json, [])
        self.assertEqual(delivery.message_id, "sent-before-reprocess")
        self.assertEqual(QQPushDelivery.objects.filter(article=article).count(), 1)
        self.assertTrue(OperationLog.objects.filter(action_type="article_entities_reprocessed", target_id=str(article.id)).exists())

    def test_commit_rolls_back_only_the_failed_article_and_continues(self):
        first = self._article("entity-atomic-first")
        second = self._article("entity-atomic-second")

        with patch(
            "stable.services.article_entity_reprocessing.reconcile_article_horse_links",
            side_effect=[RuntimeError("first failed"), {"create": [], "update": [], "delete_ids": [], "protected_ids": []}],
        ):
            payload = self._command(
                "--article-id",
                str(first.id),
                "--article-id",
                str(second.id),
                "--commit",
            )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.tags_json, ["好运宝宝"])
        self.assertEqual(second.tags_json, [])
        self.assertEqual(payload["articles"][0]["status"], "failed")
        self.assertEqual(payload["articles"][1]["status"], "committed")
        self.assertFalse(OperationLog.objects.filter(action_type="article_entities_reprocessed", target_id=str(first.id)).exists())
        self.assertTrue(OperationLog.objects.filter(action_type="article_entities_reprocessed", target_id=str(second.id)).exists())
        self.assertTrue(OperationLog.objects.filter(action_type="article_entities_reprocess_failed", target_id=str(first.id)).exists())

    def test_sync_translation_is_explicit_and_failure_does_not_publish_or_push(self):
        article = self._article("entity-translation-failure")

        with patch("stable.services.article_entity_reprocessing.translate_article_task.run", side_effect=RuntimeError("api down")):
            payload = self._command("--article-id", str(article.id), "--commit", "--translate-sync")

        article.refresh_from_db()
        self.assertEqual(payload["articles"][0]["status"], "failed")
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(QQPushDelivery.objects.filter(article=article).count(), 0)
        self.assertTrue(OperationLog.objects.filter(action_type="article_entities_reprocess_failed", target_id=str(article.id)).exists())

    def test_sync_translation_suppresses_automation_dispatch(self):
        article = self._article("entity-translation-success")

        with patch("stable.services.article_entity_reprocessing.translate_article_task.run") as translate:
            payload = self._command("--article-id", str(article.id), "--commit", "--translate-sync")

        self.assertEqual(payload["articles"][0]["status"], "committed")
        translate.assert_called_once_with(article.id, force=True, suppress_automation=True)
        article.refresh_from_db()
        self.assertEqual(article.tags_json, [])

    def test_sync_translation_uses_legacy_tag_plan_captured_before_new_provenance(self):
        article = self._article("entity-translation-provenance-order")

        def simulate_translation(article_id: int, **_kwargs):
            NewsArticle.objects.filter(pk=article_id).update(
                tags_json=["好运宝宝"],
                translation_metadata={"machine_horse_tags": []},
            )

        with patch(
            "stable.services.article_entity_reprocessing.translate_article_task.run",
            side_effect=simulate_translation,
        ):
            payload = self._command("--article-id", str(article.id), "--commit", "--translate-sync")

        article.refresh_from_db()
        self.assertEqual(payload["articles"][0]["status"], "committed")
        self.assertEqual(article.tags_json, [])
