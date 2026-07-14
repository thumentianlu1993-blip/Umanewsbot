from __future__ import annotations

import importlib
import json
from unittest.mock import patch

from django.apps import apps as django_apps
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import (
    ArticleTranslationStatus,
    ExternalHorseAlias,
    NewsArticle,
    QQPushDelivery,
    QQPushDeliveryStatus,
    PushTarget,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermAlias,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.terms import (
    ArticleEntity,
    ArticleEntityResolution,
    ResolvedTerm,
    resolve_article_entities,
)
from stable.services.translation import (
    OpenAICompatibleTranslationProvider,
    TranslationResponseError,
    TranslationResult,
)


TRANSLATION_SETTINGS = {
    "TRANSLATION_MODEL": "test-model",
    "TRANSLATION_MAX_ATTEMPTS": 1,
    "TRANSLATION_UNKNOWN_HORSE_LIMIT": 30,
    "AUTOMATION_ENABLED": True,
}


def _fake_response(*, title: str = "赛马新闻", body: str, summary: str = "赛马摘要"):
    usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
    choice = type(
        "Choice",
        (),
        {
            "message": type(
                "Message",
                (),
                {"content": json.dumps({"title_zh": title, "body_zh": body, "push_summary_zh": summary}, ensure_ascii=False)},
            )(),
            "finish_reason": "stop",
        },
    )()
    return type("Response", (), {"choices": [choice], "usage": usage})()


def _article(
    *,
    title: str = "赛马新闻",
    body: str,
    source_id: str = "jp-normalization",
    source_language: str = SourceLanguage.JAPANESE,
) -> NewsArticle:
    return NewsArticle.objects.create(
        source_site=SourceSite.NETKEIBA,
        source_mode=SourceMode.LATEST,
        source_article_id=f"{source_id}-{NewsArticle.objects.count() + 1}",
        source_language=source_language,
        racing_region=RacingRegion.JAPAN,
        title_ja=title,
        body_ja_raw=body,
        body_ja_normalized=body,
        published_at=timezone.now(),
        source_url=f"https://example.com/{source_id}/{NewsArticle.objects.count() + 1}",
    )


def _term(
    source: str,
    target: str,
    *,
    term_type: str = TermType.HORSE,
    notes: str = "",
    priority: int = 100,
) -> TermEntry:
    return TermEntry.objects.create(
        term_type=term_type,
        source_language=SourceLanguage.JAPANESE,
        racing_region=RacingRegion.JAPAN,
        source_ja=source,
        target_zh=target,
        notes=notes,
        priority=priority,
    )


def _normalization_module():
    return importlib.import_module("stable.services.japanese_racing_translation")


def _migration_module():
    return importlib.import_module("stable.migrations.0030_japanese_racing_translation_terms")


@override_settings(**TRANSLATION_SETTINGS)
class JapaneseRacingFormatPlanTests(TestCase):
    def test_8304_known_yearling_and_sire_have_exact_format(self):
        _term("ヤングスター", "少女星")
        _term("イクイノックス", "春秋分")
        source = "最高額は「ヤングスターの2025」(牡、イクイノックス)だった。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertIn("__UMA_FORMAT_1__", plan.protected_body)
        self.assertEqual(plan.items[0].rule, "yearling_lot")
        self.assertEqual(plan.items[0].field_name, "body")
        self.assertEqual(plan.items[0].target_text, "「少女星2025」（公马，父春秋分）")

    def test_yearling_with_existing_father_prefix_does_not_duplicate_father(self):
        _term("デアリングタクト", "谋勇兼备")
        _term("イクイノックス", "春秋分")
        source = "「デアリングタクトの2026」(牡、父イクイノックス)が上場する。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual(plan.items[0].target_text, "「谋勇兼备2026」（公马，父春秋分）")
        self.assertNotIn("父父", plan.items[0].target_text)

    def test_yearling_sex_inside_quotes_moves_outside(self):
        source = "341番の「コッパの2026(牡)」は半弟となる。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual(plan.items[0].target_text, "「コッパ2026」（公马）")

    def test_multiple_unknown_yearlings_keep_full_names_and_order(self):
        source = "「スキアの2025」と「スイススカイダイバーの2025」が上場した。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual([item.placeholder for item in plan.items], ["__UMA_FORMAT_1__", "__UMA_FORMAT_2__"])
        self.assertEqual(
            [item.target_text for item in plan.items],
            ["「スキア2025」", "「スイススカイダイバー2025」"],
        )

    def test_internal_short_term_accepted_elsewhere_does_not_split_unknown_mare(self):
        _term("フォリー", "青草地")
        source = "フォリーが出走した。続いて「プティフォリーの2025」が上場した。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual(plan.items[-1].target_text, "「プティフォリー2025」")
        self.assertNotIn("青草地", plan.items[-1].target_text)

    def test_unmarked_fixed_phrase_does_not_override_same_exact_horse_in_race_context(self):
        _term("テストホース", "测试马")
        _term("テストホース", "测试短语", term_type=TermType.FIXED_PHRASE)
        source = "1番 テストホース（牡3）が出走する。"

        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        exact = [item for item in resolution.entities if item.matched_text == "テストホース"]
        self.assertEqual(exact[0].entity_type, "horse")
        self.assertEqual(exact[0].target_zh, "测试马")

    def test_seeded_common_word_allows_confirmed_horse_in_strong_race_context(self):
        ExternalHorseAlias.objects.create(
            source="fixture",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            external_horse_id="SESSION-HORSE",
            name_ja="セッション",
            normalized_name="セッション",
            confidence=100,
        )
        source = "1番 セッション（牡3）が出走する。"

        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        exact = [item for item in resolution.entities if item.matched_text == "セッション"]
        self.assertEqual(exact[0].entity_type, "unknown_horse")
        self.assertEqual(exact[0].external_horse_ids, ["SESSION-HORSE"])

    def test_chinese_translation_of_foreign_horse_does_not_match_japanese_common_word(self):
        foreign_horse = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Movin Out",
            target_zh="出走",
            priority=100,
        )
        japanese_horse = _term("テストホース", "测试马")

        resolution = resolve_article_entities(
            "出走予定",
            "テストホースが次走に出走する。",
            source_language=SourceLanguage.JAPANESE,
        )

        self.assertFalse(any(item.term_id == foreign_horse.id for item in resolution.entities))
        exact = [item for item in resolution.entities if item.term_id == japanese_horse.id]
        self.assertEqual([item.matched_text for item in exact], ["テストホース"])
        self.assertEqual(resolution.machine_horse_tags, ["测试马"])

    def test_chinese_article_still_matches_foreign_horse_by_chinese_target(self):
        horse = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="Romantic Warrior",
            target_zh="浪漫勇士",
            priority=100,
        )

        resolution = resolve_article_entities(
            "浪漫勇士復出",
            "浪漫勇士將於下月復出。",
            source_language=SourceLanguage.CHINESE_TRADITIONAL,
        )

        exact = [item for item in resolution.entities if item.term_id == horse.id]
        self.assertEqual([item.matched_text for item in exact], ["浪漫勇士", "浪漫勇士"])
        self.assertEqual(resolution.machine_horse_tags, ["浪漫勇士"])

    def test_workout_time_has_exact_format_and_plain_seconds_are_untouched(self):
        source = "5ハロン64秒5―11秒7をマーク。別の時計は64秒5だった。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual([item.target_text for item in plan.items], ["5F 64.5，末脚 11.7"])
        self.assertIn("別の時計は64秒5だった", plan.protected_body)

    def test_post_race_interview_signature_has_finish_before_horse(self):
        source = "永森大智騎手(ザガラ＝1着)「最後は馬を信じた」"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual(plan.items[0].target_text, "永森大智骑手(1着 ザガラ)")

    def test_post_race_interview_never_crosses_a_line_boundary(self):
        source = "永森大智\n騎手(ザガラ＝1着)はコメントした。"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertFalse(any(item.rule == "post_race_interview" for item in plan.items))

    def test_racecard_only_replaces_line_final_unknown_jockey_marker(self):
        source = "※○○は騎手未定もしくは回避予定\nアイルドフルール　○○\n説明○○はそのまま\n说明：記号 ○○"
        resolution = resolve_article_entities("", source, source_language=SourceLanguage.JAPANESE)

        plan = _normalization_module().build_japanese_format_plan("", source, resolution)

        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.items[0].rule, "undecided_jockey")
        self.assertEqual(plan.items[0].target_text, "骑手未定")
        self.assertIn("※○○は騎手未定もしくは回避予定", plan.protected_body)
        self.assertIn("説明○○はそのまま", plan.protected_body)
        self.assertIn("说明：記号 ○○", plan.protected_body)


@override_settings(**TRANSLATION_SETTINGS)
class JapaneseTranslationProviderIntegrationTests(TestCase):
    def _provider(self) -> OpenAICompatibleTranslationProvider:
        return OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")

    def test_provider_restores_format_and_records_audit_metadata(self):
        _term("ヤングスター", "少女星")
        _term("イクイノックス", "春秋分")
        article = _article(body="最高額は「ヤングスターの2025」(牡、イクイノックス)だった。")
        provider = self._provider()
        response = _fake_response(body="最高价拍品是__UMA_FORMAT_1__。")

        with patch.object(provider, "_request_completion", return_value=response) as request:
            result = provider.translate(article)

        prompt = request.call_args.args[0][1]["content"]
        self.assertIn("__UMA_FORMAT_1__", prompt)
        self.assertIn("「少女星2025」（公马，父春秋分）", result.body_zh)
        self.assertNotIn("__UMA_FORMAT_", result.body_zh)
        self.assertEqual(
            result.metadata["japanese_format_normalizations"][0]["target_text"],
            "「少女星2025」（公马，父春秋分）",
        )

    def test_seeded_term_placeholder_restores_exact_target_in_title_and_body(self):
        article = _article(title="レコード更新", body="レコードを更新した。")
        provider = self._provider()
        response = _fake_response(
            title="__UMA_SEED_1__更新",
            body="__UMA_SEED_2__を更新した。",
        )

        with patch.object(provider, "_request_completion", return_value=response) as request:
            result = provider.translate(article)

        prompt = request.call_args.args[0][1]["content"]
        self.assertIn("__UMA_SEED_1__", prompt)
        self.assertIn("__UMA_SEED_2__", prompt)
        self.assertIn("[seed-placeholder] __UMA_SEED_1__ => 记录（源词：レコード", prompt)
        self.assertIn("[seed-placeholder] __UMA_SEED_2__ => 记录（源词：レコード", prompt)
        self.assertEqual(result.title_zh, "记录更新")
        self.assertEqual(result.body_zh, "记录を更新した。")
        self.assertEqual(
            [item["target_text"] for item in result.metadata["japanese_seed_term_normalizations"]],
            ["记录", "记录"],
        )

    def test_seeded_term_restoration_deduplicates_model_suffix_at_placeholder_boundary(self):
        article = _article(body="タイプは不器用で、オープン級を2勝した。")
        provider = self._provider()
        resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized,
            source_language=SourceLanguage.JAPANESE,
        )
        format_plan = _normalization_module().build_japanese_format_plan(
            article.title_ja,
            article.body_ja_normalized,
            resolution,
        )
        seed_plan = _normalization_module().build_japanese_seed_term_plan(
            article.title_ja,
            article.body_ja_normalized,
            resolution,
            format_plan,
        )
        placeholders = {item.source_text: item.placeholder for item in seed_plan.items}
        response = _fake_response(
            body=(
                f"虽属不够灵活的{placeholders['タイプ']}类型，"
                f"但在{placeholders['オープン']}级别赛事两胜。"
            )
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertEqual(result.body_zh, "虽属不够灵活的类型，但在公开级别赛事两胜。")
        self.assertNotIn("类型类型", result.body_zh)
        self.assertNotIn("公开级级别", result.body_zh)

    def test_seeded_term_restoration_keeps_legitimate_single_character_boundary(self):
        module = _normalization_module()
        plan = module.JapaneseSeedTermPlan(
            protected_title="",
            protected_body="__UMA_SEED_1__会场",
            items=(
                module.JapaneseSeedTermItem(
                    placeholder="__UMA_SEED_1__",
                    field_name="body",
                    source_text="セール",
                    target_text="拍卖会",
                    start=0,
                    end=3,
                ),
            ),
        )

        restored = module.restore_japanese_seed_term_placeholders(
            plan.protected_body,
            plan,
            field_name="body",
        )

        self.assertEqual(restored, "拍卖会会场")

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_missing_seed_term_placeholder_retries_then_restores_exact_target(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        first = _fake_response(body="速度很快。")
        second = _fake_response(body="__UMA_SEED_1__很快。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        self.assertEqual(request.call_count, 2)
        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("本次具体异常占位符：__UMA_SEED_1__", retry_prompt)
        self.assertIn("不得合并、压缩或省略原文细节", retry_prompt)
        self.assertIn("__UMA_SEED_1__（正文）", retry_prompt)
        self.assertEqual(result.body_zh, "速度很快。")

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_reports_seed_and_unexpected_format_violations_together(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        first = _fake_response(body="__UMA_FORMAT_1__很快。")
        second = _fake_response(body="__UMA_SEED_1__很快。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("本次具体异常占位符：__UMA_FORMAT_1__", retry_prompt)
        self.assertIn("原文不存在以下占位符，译文必须删除：__UMA_FORMAT_1__", retry_prompt)
        self.assertIn("本次具体异常占位符：__UMA_SEED_1__", retry_prompt)
        self.assertEqual(result.body_zh, "速度很快。")

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_rejects_invented_keep_and_term_placeholders(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        first = _fake_response(
            body="__UMA_SEED_1__很快。__UMA_KEEP_999____UMA_TERM_999__"
        )
        second = _fake_response(body="__UMA_SEED_1__很快。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("本次具体异常占位符：__UMA_KEEP_999__、__UMA_TERM_999__", retry_prompt)
        self.assertIn(
            "原文不存在以下占位符，译文必须删除：__UMA_KEEP_999__、__UMA_TERM_999__",
            retry_prompt,
        )
        self.assertNotIn("__UMA_", result.body_zh)

    def test_repeated_entity_placeholder_matching_source_count_is_allowed(self):
        article = _article(body="1番 ノリヤンモーニンが先行し、ノリヤンモーニンが勝った。")
        provider = self._provider()
        response = _fake_response(
            body="1号 __UMA_KEEP_1__领放，__UMA_KEEP_1__获胜。",
            summary="__UMA_KEEP_1__获胜。",
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertEqual(result.body_zh.count("ノリヤンモーニン"), 2)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_uses_pronoun_for_excess_unknown_horse_reference(self):
        ExternalHorseAlias.objects.create(
            source="fixture",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            external_horse_id="NORIYAN-MORNIN",
            name_ja="ノリヤンモーニン",
            normalized_name="ノリヤンモーニン",
            confidence=100,
        )
        article = _article(body="ノリヤンモーニンが先行した。そのまま押し切った。")
        provider = self._provider()
        first = _fake_response(
            body="__UMA_KEEP_1__领放，__UMA_KEEP_1__坚持到了最后。",
        )
        second = _fake_response(
            body="__UMA_KEEP_1__领放，该马坚持到了最后。",
        )

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("只有原文显式出现马名的位置才复制该占位符", retry_prompt)
        self.assertEqual(result.body_zh, "ノリヤンモーニン领放，该马坚持到了最后。")

    @override_settings(TRANSLATION_MAX_ATTEMPTS=1)
    def test_excess_unknown_horse_placeholder_still_fails_closed(self):
        ExternalHorseAlias.objects.create(
            source="fixture",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            external_horse_id="NORIYAN-MORNIN",
            name_ja="ノリヤンモーニン",
            normalized_name="ノリヤンモーニン",
            confidence=100,
        )
        article = _article(body="ノリヤンモーニンが先行した。そのまま押し切った。")
        provider = self._provider()
        response = _fake_response(
            body="__UMA_KEEP_1__领放，__UMA_KEEP_1__坚持到了最后。",
        )

        with patch.object(provider, "_request_completion", return_value=response):
            with self.assertRaisesRegex(TranslationResponseError, "invented protected entity placeholder"):
                provider.translate(article)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_requires_every_repeated_entity_placeholder_occurrence(self):
        article = _article(body="1番 ノリヤンモーニンが先行し、ノリヤンモーニンが勝った。")
        provider = self._provider()
        first = _fake_response(body="1号 __UMA_KEEP_1__领放并获胜。")
        second = _fake_response(body="1号 __UMA_KEEP_1__领放，__UMA_KEEP_1__获胜。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("本次具体异常占位符：__UMA_KEEP_1__", retry_prompt)
        self.assertIn("按原文所属字段及出现次数原样复制", retry_prompt)
        self.assertEqual(result.body_zh.count("ノリヤンモーニン"), 2)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_rejects_invented_placeholder_in_push_summary(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        first = _fake_response(
            body="__UMA_SEED_1__很快。",
            summary="__UMA_KEEP_999__状态良好。",
        )
        second = _fake_response(body="__UMA_SEED_1__很快。", summary="速度表现出色。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("本次具体异常占位符：__UMA_KEEP_999__", retry_prompt)
        self.assertNotIn("__UMA_", result.push_summary_zh)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_rejects_malformed_internal_placeholders_in_body_and_summary(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        first = _fake_response(
            body=(
                "__UMA_SEED_1__X很快。__UMA_KEEP_X____UMA_KEEP_3__"
                "__UMA_KEEP_1_____UMA_KEEP_2__999__"
            ),
            summary="速度出色。__UMA_KEEPP_1__状态良好。",
        )
        second = _fake_response(body="__UMA_SEED_1__很快。", summary="速度出色。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("__UMA_KEEP_X__", retry_prompt)
        self.assertIn("___UMA_KEEP_3__", retry_prompt)
        self.assertIn("__UMA_KEEP_1___", retry_prompt)
        self.assertIn("__UMA_KEEP_2__999__", retry_prompt)
        self.assertIn("__UMA_KEEPP_1__", retry_prompt)
        self.assertNotIn("__UMA_KEEPP_1__状态良好", retry_prompt)
        self.assertNotIn("__UMA_", result.body_zh)
        self.assertNotIn("__UMA_", result.push_summary_zh)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_retry_rejects_case_mutated_and_partial_internal_placeholder_prefixes(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        first = _fake_response(
            title="__Uma_FORMAT_1__标题。UMA_FORMAT_2__副标题",
            body=(
                "__UMA_SEED_1__很快。__uma_keep_1____UMAKEEP_2____UMA-KEEP_3__"
                "__UM_KEEP_4____U_MA_TERM_4____UMAKEPP_5__。"
                "__UM__KEEP_6__。_X_UMA_KEEP_7__"
            ),
            summary="_UMA_TERM_1__状态良好。__UMA TERM_2__。UMA/TERM_3__",
        )
        second = _fake_response(body="__UMA_SEED_1__很快。", summary="速度表现出色。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        retry_prompt = request.call_args_list[1].args[0][1]["content"]
        self.assertIn("__Uma_FORMAT_1__", retry_prompt)
        self.assertIn("UMA_FORMAT_2__", retry_prompt)
        self.assertIn("__uma_keep_1__", retry_prompt)
        self.assertIn("__UMAKEEP_2__", retry_prompt)
        self.assertIn("__UMA-KEEP_3__", retry_prompt)
        self.assertIn("__UM_KEEP_4__", retry_prompt)
        self.assertIn("__U_MA_TERM_4__", retry_prompt)
        self.assertIn("__UMAKEPP_5__", retry_prompt)
        self.assertIn("__UM__KEEP_6__", retry_prompt)
        self.assertIn("_X_UMA_KEEP_7__", retry_prompt)
        self.assertIn("_UMA_TERM_1__", retry_prompt)
        self.assertIn("__UMA TERM_2__", retry_prompt)
        self.assertIn("UMA/TERM_3__", retry_prompt)
        self.assertNotRegex(result.title_zh, r"(?i)UMA_(?:KEEP|TERM|FORMAT|SEED)")
        self.assertNotRegex(result.body_zh, r"(?i)UMA_(?:KEEP|TERM|FORMAT|SEED)")
        self.assertNotRegex(result.push_summary_zh, r"(?i)UMA_(?:KEEP|TERM|FORMAT|SEED)")

    def test_contextual_term_mapping_does_not_rewrite_valid_placeholder_namespace(self):
        article = _article(
            body="MYSTERY runs. KEEP is retired.",
            source_language=SourceLanguage.ENGLISH,
        )
        entity = ArticleEntity(
            entity_type="unknown_horse",
            matched_text="MYSTERY",
            canonical_text="MYSTERY",
            target_zh="",
            field_name="body",
            start=0,
            end=7,
            confidence=90,
            evidence=["test"],
            conflict_flags=[],
            needs_preserve=True,
        )
        term = ResolvedTerm(
            term_type=TermType.FIXED_PHRASE,
            source_ja="KEEP",
            target_zh="保持",
            matched_text="KEEP",
            race_grade="",
            priority=100,
            notes="",
        )
        resolution = ArticleEntityResolution(
            source_language=SourceLanguage.ENGLISH,
            entities=[entity],
            suppressed_candidates=[],
            accepted_terms=[term],
            machine_horse_tags=["MYSTERY"],
        )
        provider = self._provider()
        response = _fake_response(
            body="__UMA_KEEP_1__参赛，KEEP已经退役。",
            summary="__UMA_KEEP_1__参赛。",
        )

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article, entity_resolution=resolution)

        self.assertEqual(result.body_zh, "MYSTERY参赛，保持已经退役。")
        self.assertEqual(result.push_summary_zh, "MYSTERY参赛。")

    def test_closed_placeholder_may_touch_normal_ascii_prose(self):
        provider = self._provider()
        violations = provider._malformed_placeholder_violations(
            "__UMA_FORMAT_1__GI首胜",
            "__UMA_SEED_1__3连胜，__UMA_KEEP_1__GI首胜。",
            "__UMA_TERM_1__3岁时获胜。",
        )

        self.assertEqual(violations, [])
        self.assertEqual(
            provider._summary_placeholder_violations(
                "__UMA_KEEP_1__3岁将出战。",
                "",
                "__UMA_KEEP_1__（3歳）がGIに出走する。",
            ),
            [],
        )

    def test_closed_placeholders_may_be_separated_by_ascii_race_abbreviation(self):
        provider = self._provider()

        violations = provider._malformed_placeholder_violations(
            "",
            "其母赢得__UMA_KEEP_2__C__UMA_KEEP_3__＆母马短途赛。",
            "__UMA_KEEP_2__GI__UMA_KEEP_3__冠军。",
        )

        self.assertEqual(violations, [])
        malformed = provider._malformed_placeholder_violations(
            "",
            "__UMA_KEEP_2__999__并非合法相邻占位符。",
            "",
        )
        self.assertEqual(
            [item["placeholder"] for item in malformed],
            ["__UMA_KEEP_2__999__"],
        )

    def test_legitimate_identifier_containing_uma_prefix_is_not_a_placeholder(self):
        provider = self._provider()
        violations = provider._malformed_placeholder_violations(
            "YUMA_RACING发布消息，__UMAFANS__上线，@UMA_KEEP_1__可用。",
            "PUMA_RACING赞助赛事，@uma_musu与@_UMAhorse同步发布。",
            "Yuma_Racing状态良好，代号为_UMAJI。",
        )

        self.assertEqual(violations, [])

    @override_settings(TRANSLATION_MAX_ATTEMPTS=3)
    def test_retry_keeps_seed_constraint_when_next_attempt_is_incomplete(self):
        article = _article(body="スピードがある。" + "長い文章です。" * 100)
        provider = self._provider()
        first = _fake_response(body="速度很快。")
        second = _fake_response(body="__UMA_SEED_1__だけ")
        third = _fake_response(body="__UMA_SEED_1__很快。" + "完整翻译。" * 100)

        with patch.object(provider, "_request_completion", side_effect=[first, second, third]) as request:
            result = provider.translate(article)

        self.assertEqual(request.call_count, 3)
        final_prompt = request.call_args_list[2].args[0][1]["content"]
        self.assertIn("本次具体异常占位符：__UMA_SEED_1__", final_prompt)
        self.assertIn("此前所有占位符约束仍然有效", final_prompt)
        self.assertIn("请重点核对并完整翻译以下原文末段", final_prompt)
        self.assertTrue(result.body_zh.startswith("速度很快。"))

    @override_settings(TRANSLATION_MAX_ATTEMPTS=1)
    def test_duplicate_or_cross_field_seed_term_placeholder_fails_explicitly(self):
        article = _article(body="スピードがある。")
        provider = self._provider()
        response = _fake_response(
            title="__UMA_SEED_1__误入标题",
            body="__UMA_SEED_1____UMA_SEED_1__很快。",
        )

        with patch.object(provider, "_request_completion", return_value=response):
            with self.assertRaisesRegex(TranslationResponseError, "seed term placeholder"):
                provider.translate(article)

    def test_consumed_unknown_yearling_does_not_trigger_old_missing_horse_warning(self):
        _term("フォリー", "青草地")
        article = _article(body="フォリーが出走し、「プティフォリーの2025」が上場した。")
        provider = self._provider()
        response = _fake_response(body="青草地出赛，__UMA_FORMAT_1__上拍。")

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        self.assertIn("プティフォリー2025", result.body_zh)
        self.assertNotIn("プティ青草地", result.body_zh)
        self.assertNotIn("missing_unknown_horse_names", result.metadata)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=2)
    def test_missing_body_placeholder_retries_even_if_title_contains_it(self):
        article = _article(body="5ハロン64秒5―11秒7をマークした。")
        provider = self._provider()
        first = _fake_response(title="__UMA_FORMAT_1__", body="追い切りを行った。")
        second = _fake_response(body="__UMA_FORMAT_1__を記録した。")

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as request:
            result = provider.translate(article)

        self.assertEqual(request.call_count, 2)
        self.assertIn("5F 64.5，末脚 11.7", result.body_zh)

    def test_final_missing_format_placeholder_fails_explicitly(self):
        article = _article(body="5ハロン64秒5―11秒7をマークした。")
        provider = self._provider()

        with patch.object(provider, "_request_completion", return_value=_fake_response(body="追い切りを行った。")):
            with self.assertRaisesRegex(TranslationResponseError, "format placeholder"):
                provider.translate(article)

    @override_settings(TRANSLATION_MAX_ATTEMPTS=1)
    def test_duplicate_or_cross_field_format_placeholder_fails_explicitly(self):
        article = _article(body="5ハロン64秒5―11秒7をマークした。")
        provider = self._provider()
        response = _fake_response(
            title="__UMA_FORMAT_1__误入标题",
            body="__UMA_FORMAT_1____UMA_FORMAT_1__を記録した。",
        )

        with patch.object(provider, "_request_completion", return_value=response):
            with self.assertRaisesRegex(TranslationResponseError, "format placeholder"):
                provider.translate(article)

    def test_prompt_requires_translation_of_unprotected_common_katakana(self):
        article = _article(body="スピードがあり、スムーズにコーナーを回った。")
        provider = self._provider()

        messages = provider._build_messages(article, [], [])

        prompt = messages[1]["content"]
        self.assertIn("普通片假名", prompt)
        self.assertIn("不得保留原文", prompt)

    @override_settings(TRANSLATION_TERM_LIMIT=1)
    def test_seeded_common_terms_stay_in_prompt_beyond_base_term_limit(self):
        _term("テストホース", "测试马", priority=1000)
        article = _article(body="テストホースはスピードがある。")
        provider = self._provider()

        with patch.object(
            provider,
            "_request_completion",
            return_value=_fake_response(body="测试马__UMA_SEED_1__很快。"),
        ) as request:
            result = provider.translate(article)

        prompt = request.call_args.args[0][1]["content"]
        self.assertIn("スピード => 速度", prompt)
        self.assertTrue(any(term["matched_text"] == "スピード" for term in result.metadata["terms"]))

    @override_settings(TRANSLATION_TERM_LIMIT=1)
    def test_seeded_english_org_alias_stays_in_prompt_beyond_base_term_limit(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.JAPAN,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=1000,
        )
        article = _article(
            body="Equinox yearlings consigned by Shadai Farm were sold.",
            source_language=SourceLanguage.ENGLISH,
        )
        provider = self._provider()

        with patch.object(
            provider,
            "_request_completion",
            return_value=_fake_response(body="春秋分产驹由__UMA_SEED_1__牧场送拍。"),
        ) as request:
            result = provider.translate(article)

        prompt = request.call_args.args[0][1]["content"]
        self.assertIn("Shadai => 社台", prompt)
        self.assertTrue(any(term["matched_text"] == "Shadai" for term in result.metadata["terms"]))

    def test_seeded_common_terms_are_mapped_and_never_become_horse_tags(self):
        article = _article(body="セレクトセールではスムーズなタイプがオープン級を走る。")
        provider = self._provider()
        resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized,
            source_language=SourceLanguage.JAPANESE,
        )
        format_plan = _normalization_module().build_japanese_format_plan(
            article.title_ja,
            article.body_ja_normalized,
            resolution,
        )
        seed_plan = _normalization_module().build_japanese_seed_term_plan(
            article.title_ja,
            article.body_ja_normalized,
            resolution,
            format_plan,
        )
        response = _fake_response(body=seed_plan.protected_body)

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(article)

        for source in ("セレクトセール", "セール", "スムーズ", "タイプ", "オープン"):
            self.assertNotIn(source, result.body_zh)
        self.assertEqual(result.metadata["machine_horse_tags"], [])


class JapaneseTranslationTermMigrationTests(TestCase):
    def _run_seed(self):
        migration = _migration_module()
        migration.seed_japanese_racing_translation_terms(django_apps, None)
        return migration

    def test_seed_creates_unique_multilingual_concepts_and_exact_targets(self):
        self._run_seed()

        shadai = TermEntry.objects.get(source_ja="社台")
        horse_park = TermEntry.objects.get(source_ja="ノーザンホースパーク")
        self.assertEqual(shadai.target_zh, "社台")
        self.assertEqual(horse_park.target_zh, "北方马公园")
        self.assertTrue(TermAlias.objects.filter(term=shadai, source_language=SourceLanguage.JAPANESE, text="社台").exists())
        self.assertTrue(TermAlias.objects.filter(term=shadai, source_language=SourceLanguage.ENGLISH, text="Shadai").exists())
        self.assertTrue(
            TermAlias.objects.filter(
                term=horse_park,
                source_language=SourceLanguage.ENGLISH,
                text="Northern Horse Park",
            ).exists()
        )
        expected_common = {
            "レコード": "记录",
            "セレクトセール": "精选拍卖会",
            "セール": "拍卖会",
            "セッション": "场次",
            "スピード": "速度",
            "タイプ": "类型",
            "コーナー": "弯道",
            "ペース": "步速",
            "オープン": "公开级",
            "スムーズ": "顺畅",
            "トップハンデ": "最高负磅",
            "ハイペース": "快步速",
            "スパイク": "钉鞋",
        }
        self.assertEqual(
            dict(TermEntry.objects.filter(source_ja__in=expected_common).values_list("source_ja", "target_zh")),
            expected_common,
        )

    def test_seed_is_idempotent_and_english_alias_lookup_is_case_insensitive(self):
        self._run_seed()
        before = (TermEntry.objects.count(), TermAlias.objects.count())

        self._run_seed()

        self.assertEqual((TermEntry.objects.count(), TermAlias.objects.count()), before)
        resolution = resolve_article_entities(
            "SHAdaI sale",
            "A yearling consigned by shadai Farm was sold.",
            source_language=SourceLanguage.ENGLISH,
        )
        self.assertTrue(any(term.target_zh == "社台" for term in resolution.accepted_terms))

    def test_seed_reactivates_existing_term_and_alias(self):
        sale = TermEntry.objects.get(source_ja="セール")
        sale.is_active = False
        sale.save(update_fields=["is_active", "updated_at"])
        alias = TermAlias.objects.get(term=sale, source_language=SourceLanguage.JAPANESE, text="セール")
        alias.is_active = False
        alias.save(update_fields=["is_active", "updated_at"])

        self._run_seed()

        sale.refresh_from_db()
        alias.refresh_from_db()
        self.assertTrue(sale.is_active)
        self.assertTrue(alias.is_active)

    def test_conflicting_existing_target_fails_without_overwrite(self):
        existing = TermEntry.objects.create(
            term_type=TermType.ORG,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="社台",
            target_zh="错误目标",
        )

        with self.assertRaises(RuntimeError):
            self._run_seed()

        existing.refresh_from_db()
        self.assertEqual(existing.target_zh, "错误目标")

    def test_alias_owned_by_another_concept_fails(self):
        other = TermEntry.objects.create(
            term_type=TermType.ORG,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="另一机构",
            target_zh="另一机构",
        )
        TermAlias.objects.create(term=other, source_language=SourceLanguage.ENGLISH, text="shadai")

        with self.assertRaises(RuntimeError):
            self._run_seed()

    def test_reverse_keeps_operational_terms(self):
        migration = self._run_seed()
        before = (TermEntry.objects.count(), TermAlias.objects.count())

        migration.unseed_japanese_racing_translation_terms(django_apps, None)

        self.assertEqual((TermEntry.objects.count(), TermAlias.objects.count()), before)


@override_settings(**TRANSLATION_SETTINGS)
class PublishedArticleForceRetranslationSafetyTests(TestCase):
    def test_force_retranslation_updates_content_without_publication_or_qq_side_effects(self):
        published_at = timezone.now()
        article = _article(body="5ハロン64秒5―11秒7をマークした。", source_id="published-force")
        article.workflow_status = WorkflowStatus.PUBLISHED
        article.translation_status = ArticleTranslationStatus.TRANSLATED
        article.published_to_web_at = published_at
        article.manually_edited_fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
        article.title_zh = "旧标题"
        article.body_zh = "旧正文"
        article.summary_zh = "旧摘要"
        article.push_summary_zh = "旧推送摘要"
        article.save()
        target = PushTarget.objects.create(name="测试群", group_id="123456", is_active=True)
        QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            max_attempts=3,
        )
        result = TranslationResult(
            title_zh="新标题",
            body_zh="5F 64.5，末脚 11.7",
            push_summary_zh="新摘要",
            metadata={"provider": "test", "model": "test", "machine_horse_tags": []},
        )

        with patch("stable.tasks.translate_article", return_value=result), patch("stable.tasks.dispatch_task") as dispatch:
            from stable.tasks import translate_article_task

            outcome = translate_article_task.run(article.id, force=True)

        article.refresh_from_db()
        self.assertTrue(outcome["translated"])
        self.assertEqual(article.body_zh, "5F 64.5，末脚 11.7")
        self.assertEqual(article.manually_edited_fields, ["title_zh", "body_zh", "summary_zh", "push_summary_zh"])
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.published_to_web_at, published_at)
        self.assertEqual(QQPushDelivery.objects.filter(article=article).count(), 1)
        dispatch.assert_not_called()
