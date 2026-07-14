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
from stable.services.terms import resolve_article_entities
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
        self.assertEqual(result.title_zh, "记录更新")
        self.assertEqual(result.body_zh, "记录を更新した。")
        self.assertEqual(
            [item["target_text"] for item in result.metadata["japanese_seed_term_normalizations"]],
            ["记录", "记录"],
        )

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
        self.assertEqual(result.body_zh, "速度很快。")

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
