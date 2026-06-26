from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import json
import tempfile
from io import StringIO
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

import requests
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.base import CanonicalNewsDraft
from stable.adapters.base import SourceArticleDetail, SourceArticleStub
from stable.adapters.international import (
    AtTheRacesFranceAdapter,
    BloodHorseAdapter,
    BHAAdapter,
    FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS,
    FIRST_VERSION_INTERNATIONAL_PROBES,
    FranceGalopEnglishNewsAdapter,
    HorseRacingNationAdapter,
    HKJCRacingNewsAdapter,
    PaulickReportAdapter,
    SCMPRacingAdapter,
    SkySportsRacingAdapter,
    SponichiAdapter,
    SportingLifeAdapter,
    TDNAdapter,
    TDNFranceKeywordAdapter,
)
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    ContentCategory,
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalImportStatus,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceOdds,
    ExternalRaceResult,
    CrawlJob,
    NewsImage,
    NewsArticle,
    NewsSnapshot,
    NewsSource,
    NotificationLog,
    OperationLog,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    QQPushErrorType,
    RacingRegion,
    ReviewMode,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermAlias,
    TermAliasType,
    TermCandidate,
    TermCandidateStatus,
    TermEntry,
    TaskExecutionLog,
    TaskStatus,
    WorkflowStatus,
)
from stable.services.onebot import BotPusher, OneBotRequestError
from stable.services.qq_auto_push import (
    build_qq_auto_push_message,
    ensure_qq_push_deliveries,
    qq_push_next_attempt_delay,
    should_push_news_to_qq,
    target_allowed_regions,
)
from stable.services.pushing import build_push_message, push_article_to_targets
from stable.services.automation import score_article_for_automation
from stable.services.notifications import send_high_value_warning_notification
from stable.services.rewriting import OpenAICompatibleRewriteProvider, _loads_rewrite_payload
from stable.services.sources import BUILTIN_SOURCE_DEFINITIONS, sync_builtin_sources
from stable.services.ingestion import ArticleUpsertResult, upsert_article_from_draft
from stable.services.term_admin import commit_term_import, preview_term_import
from stable.services.term_candidate_review import accept_candidate, merge_candidate, set_candidate_status
from stable.services.term_discovery import (
    TermDiscoveryFinding,
    aggregate_finding,
    discover_and_aggregate_article,
    discover_term_findings,
    match_formal_terms,
    normalize_japanese_term,
)
from stable.services.terms import (
    apply_created_term_to_article,
    apply_term_mappings,
    extract_horse_tags,
    extract_unknown_horse_names,
    recognize_horse_names,
    resolve_terms,
    resolve_terms_for_language,
)
from stable.services.text import extract_article_text
from stable.services.translation import (
    OpenAICompatibleTranslationProvider,
    TranslationResponseError,
    translate_article as run_translation_service,
)
from stable.services.validation import apply_validation_outcome, validate_rewrite
from stable.services.external_horse_data import (
    ExternalHorseDataAlreadyRunning,
    ExternalHorseDataImporter,
    ExternalHorseDataNetworkDisabled,
    ImportOptions,
)
from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError, HKJCImportOptions
from stable.tasks import (
    _crawl_jra_source,
    _crawl_international_source,
    _crawl_netkeiba_mode,
    _resolve_auto_publish_batch_limit,
    auto_publish_batch_task,
    batch_translate_articles_task,
    discover_term_candidates_task,
    process_article_automation_task,
    qq_auto_push_article_task,
    qq_push_delivery_task,
    score_article_task,
    send_notification_task,
    translate_article_task,
)


User = get_user_model()


class TermResolverTests(TestCase):
    def test_resolve_terms_and_apply_mappings(self):
        TermEntry.objects.create(
            term_type="horse",
            source_ja="ソダシ",
            target_zh="纯白少女",
            aliases_ja=["Sodashi"],
            priority=10,
        )
        matches = resolve_terms("ソダシが勝利した", limit=10)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].target_zh, "纯白少女")
        self.assertEqual(apply_term_mappings("ソダシが勝利した"), "纯白少女が勝利した")

    def test_terms_with_same_text_can_coexist_by_source_language(self):
        TermEntry.objects.create(term_type="race", source_language=SourceLanguage.JAPANESE, source_ja="Title", target_zh="日文标题")
        TermEntry.objects.create(term_type="race", source_language=SourceLanguage.ENGLISH, source_ja="Title", target_zh="英文标题")
        TermEntry.objects.create(
            term_type="race",
            source_language=SourceLanguage.CHINESE_TRADITIONAL,
            source_ja="香港打吡大賽",
            target_zh="香港打吡大赛",
        )

        english_terms = resolve_terms_for_language("Title preview", SourceLanguage.ENGLISH, limit=10)
        zh_hant_terms = resolve_terms_for_language("香港打吡大賽前瞻", SourceLanguage.CHINESE_TRADITIONAL, limit=10)

        self.assertEqual([term.target_zh for term in english_terms], ["英文标题"])
        self.assertEqual([term.target_zh for term in zh_hant_terms], ["香港打吡大赛"])
        self.assertEqual(apply_term_mappings("Title preview", source_language=SourceLanguage.ENGLISH), "英文标题 preview")
        self.assertEqual(apply_term_mappings("Title preview", source_language=SourceLanguage.JAPANESE), "日文标题 preview")
        self.assertEqual(
            apply_term_mappings("香港打吡大賽前瞻", source_language=SourceLanguage.CHINESE_TRADITIONAL),
            "香港打吡大赛前瞻",
        )

    def test_same_term_concept_can_have_multilingual_aliases(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            priority=100,
        )
        TermAlias.objects.create(term=term, source_language=SourceLanguage.ENGLISH, text="Equinox", alias_type=TermAliasType.PRIMARY)
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.CHINESE_TRADITIONAL,
            text="春秋分",
            alias_type=TermAliasType.PRIMARY,
        )

        english_terms = resolve_terms_for_language("Equinox returns in a feature", SourceLanguage.ENGLISH, limit=10)
        japanese_terms = resolve_terms_for_language("イクイノックスが始動", SourceLanguage.JAPANESE, limit=10)

        self.assertEqual([(item.source_ja, item.target_zh, item.matched_text) for item in english_terms], [("イクイノックス", "春秋分", "Equinox")])
        self.assertEqual([(item.source_ja, item.target_zh, item.matched_text) for item in japanese_terms], [("イクイノックス", "春秋分", "イクイノックス")])
        self.assertEqual(resolve_terms_for_language("イクイノックス", SourceLanguage.ENGLISH, limit=10), [])
        self.assertEqual(extract_horse_tags("Equinox lines up at Ascot.", source_language=SourceLanguage.ENGLISH), ["春秋分"])

    def test_english_term_matching_is_case_insensitive_and_preserves_matched_text(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            priority=100,
        )
        TermAlias.objects.create(term=term, source_language=SourceLanguage.ENGLISH, text="Equinox", alias_type=TermAliasType.PRIMARY)

        matches = resolve_terms_for_language("EQUINOX returns at Ascot", SourceLanguage.ENGLISH, limit=10)

        self.assertEqual([(item.target_zh, item.matched_text) for item in matches], [("春秋分", "EQUINOX")])
        self.assertEqual(apply_term_mappings("EQUINOX returns at Ascot", source_language=SourceLanguage.ENGLISH), "春秋分 returns at Ascot")
        self.assertEqual(apply_term_mappings("PREQUINOX returns", source_language=SourceLanguage.ENGLISH), "PREQUINOX returns")

    def test_apply_single_created_english_term_is_case_insensitive_for_article_language(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=100,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="single-term-english-case",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="EQUINOX returns",
            translated_title_zh="EQUINOX returns",
            translated_body_zh="EQUINOX returns at Ascot. PREQUINOX stays unchanged.",
            body_zh="EQUINOX returns at Ascot.",
            published_at=timezone.now(),
            source_url="https://example.com/single-term-english-case",
        )

        result = apply_created_term_to_article(article, term)

        article.refresh_from_db()
        self.assertIn("translated_title_zh", result.updated_fields)
        self.assertEqual(article.translated_title_zh, "春秋分 returns")
        self.assertEqual(article.translated_body_zh, "春秋分 returns at Ascot. PREQUINOX stays unchanged.")
        self.assertEqual(article.body_zh, "春秋分 returns at Ascot.")

    def test_multilingual_alias_matching_bulk_loads_aliases(self):
        for index in range(8):
            term = TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.JAPANESE,
                source_ja=f"テストホース{index}",
                target_zh=f"测试马{index}",
                priority=index,
            )
            TermAlias.objects.create(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text=f"Test Horse {index}",
                alias_type=TermAliasType.PRIMARY,
            )

        with CaptureQueriesContext(connection) as captured:
            terms = resolve_terms_for_language("Test Horse 7 returns at Sha Tin", SourceLanguage.ENGLISH, limit=10)

        self.assertEqual([term.target_zh for term in terms], ["测试马7"])
        self.assertLessEqual(len(captured.captured_queries), 3)

    def test_english_article_does_not_use_japanese_horse_heuristic(self):
        recognized = recognize_horse_names("ASCOT PREVIEW", "TITLE runs at Ascot.", source_language=SourceLanguage.ENGLISH)

        self.assertEqual(recognized, [])

    def test_english_external_horse_alias_is_recognized_without_japanese_heuristic(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            confidence=96,
        )

        recognized = recognize_horse_names(
            "Lucky Star wins at Sha Tin",
            "The gelding Lucky Star was too strong in the Class 3 contest.",
            source_language=SourceLanguage.ENGLISH,
        )

        self.assertEqual(len(recognized), 1)
        self.assertEqual(recognized[0].source, "external_alias")
        self.assertEqual(recognized[0].matched_text, "Lucky Star")
        self.assertEqual(recognized[0].external_horse_ids, ["HKH001"])
        self.assertTrue(recognized[0].needs_preserve)

    def test_english_external_horse_alias_preserves_source_spelling(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH002",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            confidence=96,
        )

        recognized = recognize_horse_names(
            "LUCKY STAR wins at Sha Tin",
            "The gelding was too strong.",
            source_language=SourceLanguage.ENGLISH,
        )

        self.assertEqual(len(recognized), 1)
        self.assertEqual(recognized[0].name_ja, "Lucky Star")
        self.assertEqual(recognized[0].matched_text, "LUCKY STAR")

    def test_english_external_horse_alias_lookup_uses_article_candidates(self):
        for index in range(20):
            ExternalHorseAlias.objects.create(
                source="hkjc",
                racing_region=RacingRegion.HONG_KONG,
                source_language=SourceLanguage.ENGLISH,
                external_horse_id=f"UNRELATED{index}",
                name_ja=f"Unrelated Horse {index}",
                name_en=f"Unrelated Horse {index}",
                normalized_name=f"Unrelated Horse {index}",
                confidence=80,
            )
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH003",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            confidence=96,
        )

        with CaptureQueriesContext(connection) as captured:
            recognized = recognize_horse_names(
                "Lucky Star wins again",
                "A sharp performance at Sha Tin.",
                source_language=SourceLanguage.ENGLISH,
            )

        self.assertEqual([item.matched_text for item in recognized], ["Lucky Star"])
        self.assertLessEqual(len(captured.captured_queries), 4)

    def test_extract_horse_tags_returns_translated_horse_names(self):
        TermEntry.objects.create(term_type="horse", source_ja="ソダシ", target_zh="纯净之辉", priority=100)
        TermEntry.objects.create(term_type="horse", source_ja="リバティアイランド", target_zh="自由岛", priority=90)
        TermEntry.objects.create(term_type="race", source_ja="桜花賞", target_zh="樱花赏", priority=80)

        tags = extract_horse_tags("ソダシとリバティアイランドが桜花賞に出走する。")

        self.assertEqual(tags, ["纯净之辉", "自由岛"])

    def test_extract_unknown_horse_names_skips_known_horses_and_keeps_unmapped(self):
        TermEntry.objects.create(term_type="horse", source_ja="クロワデュノール", target_zh="北十字星", priority=100)

        names = extract_unknown_horse_names(
            "【大阪杯レース後コメント】クロワデュノール北村友一騎手ら",
            "1着 クロワデュノール(北村友一騎手)\n2着 メイショウタバル(武豊騎手)\n3着 ダノンデサイル(坂井瑠星騎手)",
        )

        self.assertIn("メイショウタバル", names)
        self.assertIn("ダノンデサイル", names)
        self.assertNotIn("クロワデュノール", names)

    def test_extract_unknown_horse_names_skips_generic_racing_words(self):
        names = extract_unknown_horse_names(
            "【平安S】ロードクロンヌがリベンジへ",
            "昨年の雪辱を期すロードクロンヌが平安Sに向かう。アクションプランも出走予定。",
        )

        self.assertNotIn("リベンジ", names)

    def test_external_horse_alias_is_recognized_and_preserved_without_mapping(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )

        recognized = recognize_horse_names("マヤノライジンが出走", "マヤノライジンは重賞へ向かう。")
        external = [item for item in recognized if item.name_ja == "マヤノライジン"][0]

        self.assertEqual(external.source, "external_alias")
        self.assertTrue(external.needs_preserve)
        self.assertFalse(external.has_translation)
        self.assertEqual(external.external_horse_ids, ["1001"])
        self.assertEqual(apply_term_mappings("マヤノライジンが出走"), "マヤノライジンが出走")
        self.assertIn("マヤノライジン", extract_unknown_horse_names("マヤノライジンが出走", ""))

    def test_formal_horse_term_takes_priority_over_external_alias(self):
        TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神", priority=100)
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )

        recognized = recognize_horse_names("マヤノライジンが出走", "")
        formal = [item for item in recognized if item.name_ja == "マヤノライジン"][0]

        self.assertEqual(formal.source, "formal_term")
        self.assertFalse(formal.needs_preserve)
        self.assertTrue(formal.has_translation)
        self.assertEqual(apply_term_mappings("マヤノライジンが出走"), "摩耶雷神が出走")
        self.assertNotIn("マヤノライジン", extract_unknown_horse_names("マヤノライジンが出走", ""))

    def test_common_word_external_alias_requires_strong_horse_context(self):
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="タイトル",
            target_zh="标题",
            notes="non_horse_common_word: 测试普通词",
        )
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="2001",
            name_ja="タイトル",
            normalized_name="タイトル",
            alias_source="test",
        )

        ordinary = recognize_horse_names("記事のタイトルを変更", "ページタイトルを確認した。")
        strong = recognize_horse_names("タイトルが出走", "タイトルは武豊騎手とのコンビで重賞へ向かう。")

        self.assertNotIn("タイトル", [item.name_ja for item in ordinary])
        self.assertIn("タイトル", [item.name_ja for item in strong])

    def test_external_horse_alias_keeps_multiple_horse_ids(self):
        for horse_id in ["3001", "3002"]:
            ExternalHorseAlias.objects.create(
                source="netkeiba",
                external_horse_id=horse_id,
                name_ja="ドウメイホース",
                normalized_name="ドウメイホース",
                alias_source="test",
            )

        recognized = recognize_horse_names("ドウメイホースが出走", "")
        item = [entry for entry in recognized if entry.name_ja == "ドウメイホース"][0]

        self.assertCountEqual(item.external_horse_ids, ["3001", "3002"])

    def test_unknown_horse_limit_is_applied_after_known_horse_terms(self):
        for name in ["アカホース", "アオホース", "クロホース"]:
            TermEntry.objects.create(term_type="horse", source_ja=name, target_zh=f"{name}译名")
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="4001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )

        names = extract_unknown_horse_names(
            "アカホース アオホース クロホース マヤノライジンが出走",
            "",
            limit=1,
        )

        self.assertEqual(names, ["マヤノライジン"])


class RaceGradeTests(TestCase):
    def test_normalize_race_grade_covers_common_jra_classes(self):
        from stable.services.automation import normalize_race_grade

        cases = {
            "宝塚記念・GI": "G1",
            "安田記念（ＧⅠ）": "G1",
            "札幌記念 GII": "G2",
            "金鯱賞（Ｇ２）": "G2",
            "中山金杯 GIII": "G3",
            "京都金杯（ＧⅢ）": "G3",
            "リステッド競走": "L",
            "Listed": "L",
            "オープン特別": "OP",
            "OP": "OP",
            "メイクデビュー東京": "NEWCOMER",
            "新馬戦": "NEWCOMER",
            "未勝利戦": "MAIDEN",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_race_grade(raw), expected)

    def test_race_grade_drives_automation_priority_and_keeps_low_classes_low(self):
        from stable.services.automation import race_priority

        TermEntry.objects.create(term_type="race", source_ja="宝塚記念", target_zh="宝塚纪念", race_grade="G1")
        g1_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="race-grade-g1",
            title_ja="【宝塚記念】注目馬が出走",
            body_ja_raw="宝塚記念に出走する。GIの大一番に向けて調整は順調。",
            body_ja_normalized="宝塚記念に出走する。GIの大一番に向けて調整は順調。",
            translated_body_zh="宝塚纪念的赛前消息。" * 20,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            source_url="https://example.com/race-grade-g1",
        )
        self.assertEqual(race_priority(g1_article)["priority"], "P0")

        TermEntry.objects.create(term_type="race", source_ja="新馬戦", target_zh="新马战", race_grade="NEWCOMER")
        newcomer_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="race-grade-newcomer",
            title_ja="東京新馬戦の出走馬が決定",
            body_ja_raw="東京新馬戦に若駒が出走する。",
            body_ja_normalized="東京新馬戦に若駒が出走する。",
            translated_body_zh="新马战消息。" * 20,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            source_url="https://example.com/race-grade-newcomer",
        )
        decision = score_article_for_automation(newcomer_article)
        self.assertNotEqual(decision.decision_reason["signals"]["race_priority"], "P0")
        self.assertLess(decision.score_total, 75)


class TextExtractionTests(TestCase):
    def test_extract_article_text_keeps_inline_links_in_same_line(self):
        html = """
        <div class="News_Txt">
          <p>JRAは6日、<a href="/?pid=keyword&id=1">WIN5</a>の通年発売を発表した。</p>
          <p>対象レースは<a href="/?pid=keyword&id=2">JRA</a>ホームページに掲載される。</p>
        </div>
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        text = extract_article_text(soup.select_one(".News_Txt"))
        self.assertIn("JRAは6日、WIN5の通年発売を発表した。", text)
        self.assertIn("対象レースはJRAホームページに掲載される。", text)
        self.assertNotIn("\nWIN5\n", text)
        self.assertNotIn("\nJRA\n", text)


class RewritePayloadTests(TestCase):
    def test_loads_rewrite_payload_tolerates_control_characters(self):
        payload = _loads_rewrite_payload(
            '{"rewrite_title_zh":"标题","rewrite_summary_zh":"摘要","rewrite_body_zh":"第一段\x0b第二段","rewrite_confidence":90}'
        )

        self.assertEqual(payload["rewrite_title_zh"], "标题")
        self.assertEqual(payload["rewrite_body_zh"], "第一段第二段")

    def test_rewrite_prompt_uses_matched_source_alias_for_article_language(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            priority=100,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="rewrite-english-term-prompt",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Equinox returns at Ascot",
            body_ja_raw="Equinox returns at Ascot in a feature race.",
            body_ja_normalized="Equinox returns at Ascot in a feature race.",
            translated_title_zh="春秋分回归",
            translated_body_zh="春秋分将在阿斯科特回归。",
            published_at=timezone.now(),
            source_url="https://example.com/rewrite-english-term-prompt",
        )
        provider = OpenAICompatibleRewriteProvider(api_key="test-key", base_url="https://example.com/v1")

        prompt = provider._messages(article)[1]["content"]

        self.assertIn("[horse] Equinox => 春秋分", prompt)
        self.assertNotIn("[horse] イクイノックス => 春秋分", prompt)


class AdapterTests(TestCase):
    def test_netkeiba_listing_parse(self):
        fragment = """
        <div><a href="https://news.netkeiba.com/?pid=news_view&no=1" title="テスト記事" class="ArticleLink fc">
        <div class="NewsTxtBox"><h2 class="NewsTitle">テスト記事</h2>
        <ul class="Nk_DataList"><li class="Time">1時間前</li><li class="Comment">3</li><li class="Chumoku">8</li></ul>
        </div></a></div>
        """
        payload = "(" + __import__("json").dumps(fragment) + ")"
        with patch("stable.adapters.netkeiba.get_bytes", return_value=payload):
            items = NetkeibaAdapter().fetch_listing(SourceMode.LATEST, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_article_id, "1")
        self.assertEqual(items[0].comment_count, 3)

    def test_jra_listing_parse(self):
        html = """
        <div class="news_unit"><h2>2026年3月25日（水曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202603/032503.html"><div class="txt">クイーンSの競走馬登録抹消</div></a></li></ul>
        </div>
        """
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = JRAAdapter().fetch_listing(SourceMode.OFFICIAL, "202603")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_site, SourceSite.JRA)
        self.assertEqual(items[0].title_ja, "クイーンSの競走馬登録抹消")

    def test_jra_listing_parse_without_year_uses_month_hint(self):
        html = """
        <div class="news_unit"><h2>5月31日（日曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202605/053101.html"><div class="txt">無年份日期新闻</div></a></li></ul>
        </div>
        """
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = JRAAdapter().fetch_listing(SourceMode.OFFICIAL, "202605")
        self.assertEqual(len(items), 1)
        local = items[0].published_at.astimezone(ZoneInfo("Asia/Tokyo"))
        self.assertEqual(local.year, 2026)
        self.assertEqual(local.month, 5)
        self.assertEqual(local.day, 31)

    def test_jra_date_parse_rolls_back_future_no_year_date(self):
        adapter = JRAAdapter()
        now = datetime(2026, 1, 2, 3, 0, tzinfo=dt_timezone.utc)
        with patch("stable.adapters.jra.timezone.now", return_value=now):
            parsed = adapter._parse_heading_date("12月31日（木曜）")
        local = parsed.astimezone(ZoneInfo("Asia/Tokyo"))
        self.assertEqual(local.year, 2025)
        self.assertEqual(local.month, 12)
        self.assertEqual(local.day, 31)

    def test_international_adapters_parse_minimal_article_metadata(self):
        cases = [
            (SponichiAdapter(), RacingRegion.JAPAN, SourceLanguage.JAPANESE, "競馬 テスト記事"),
            (HKJCRacingNewsAdapter(), RacingRegion.HONG_KONG, SourceLanguage.ENGLISH, "HKJC racing preview"),
            (SCMPRacingAdapter(), RacingRegion.HONG_KONG, SourceLanguage.ENGLISH, "Hong Kong racing news"),
            (SportingLifeAdapter(), RacingRegion.UNITED_KINGDOM, SourceLanguage.ENGLISH, "Royal Ascot latest"),
            (SkySportsRacingAdapter(), RacingRegion.UNITED_KINGDOM, SourceLanguage.ENGLISH, "Sky Sports racing latest"),
            (BHAAdapter(), RacingRegion.UNITED_KINGDOM, SourceLanguage.ENGLISH, "BHA racing update"),
            (FranceGalopEnglishNewsAdapter(), RacingRegion.FRANCE, SourceLanguage.ENGLISH, "France Galop English update"),
            (HorseRacingNationAdapter(), RacingRegion.UNITED_STATES, SourceLanguage.ENGLISH, "Kentucky racing report"),
            (AtTheRacesFranceAdapter(), RacingRegion.FRANCE, SourceLanguage.ENGLISH, "France racing at Deauville"),
            (BloodHorseAdapter(), RacingRegion.UNITED_STATES, SourceLanguage.ENGLISH, "Kentucky racing report"),
            (PaulickReportAdapter(), RacingRegion.UNITED_STATES, SourceLanguage.ENGLISH, "US racing report"),
        ]
        listing_html = '<main><article><a href="/news/test-article">France racing at Deauville</a></article></main>'
        detail_html = """
        <html><body>
          <article>
            <h1>France racing at Deauville</h1>
            <time datetime="2026-06-20T10:30:00+00:00">20 June 2026</time>
            <div class="article-body"><p>Preview body with enough racing detail.</p></div>
          </article>
        </body></html>
        """
        for adapter, region, language, title in cases:
            with self.subTest(adapter=adapter.__class__.__name__):
                listing_href = f"{adapter.link_path_keywords[0].rstrip('/')}/test-article"
                listing = listing_html.replace("/news/test-article", listing_href).replace("France racing at Deauville", title)
                detail = detail_html.replace("France racing at Deauville", title)
                stubs = adapter.parse_listing_html(listing, url=adapter.base_url)
                self.assertEqual(len(stubs), 1)
                detail_payload = adapter.parse_detail_html(detail, url=stubs[0].source_url)
                draft = adapter.normalize_source_payload(stubs[0], detail_payload)
                self.assertEqual(draft.title_ja, title)
                self.assertIn("Preview body", draft.body_ja_normalized)
                self.assertEqual(draft.racing_region, region)
                self.assertEqual(draft.source_language, language)
                self.assertTrue(draft.source_url.startswith("https://"))
                self.assertIn("<html>", draft.original_content_html)
                self.assertNotIn("html", draft.metadata)

    def test_international_article_id_includes_url_hash_to_avoid_slug_collision(self):
        adapter = HKJCRacingNewsAdapter()

        first = adapter.parse_listing_html(
            '<article><a href="/english/news/preview">Preview</a></article>',
            url=adapter.base_url,
        )[0]
        second = adapter.parse_listing_html(
            '<article><a href="/english/features/preview">Preview</a></article>',
            url=adapter.base_url,
        )[0]

        self.assertNotEqual(first.source_article_id, second.source_article_id)
        self.assertTrue(first.source_article_id.startswith("preview-"))

    def test_international_listing_ignores_navigation_links(self):
        adapter = AtTheRacesFranceAdapter()
        stubs = adapter.parse_listing_html(
            """
            <nav><a href="/news/site-map">France racing navigation</a></nav>
            <main>
              <article><a href="/news/deauville-preview">France racing at Deauville</a></article>
            </main>
            """,
            url=adapter.base_url,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_url, "https://www.attheraces.com/news/deauville-preview")

    def test_sponichi_access_ranking_keeps_upstream_rank_and_filters_non_racing(self):
        adapter = SponichiAdapter()
        stubs = adapter.parse_listing_html(
            """
            <ul class="tab-contents">
              <a href="/gamble/news/2026/06/25/kiji/20260625s00053000198000c.html">
                1 【鳴門ボート】シリーズ2勝の石野貴之
              </a>
              <a href="/gamble/news/2026/06/25/kiji/20260625s00004048222000c.html">
                4 昨年皐月賞＆有馬記念覇者ミュージアムマイルは放牧中
              </a>
            </ul>
            """,
            url=adapter.listing_url(1, mode=SourceMode.ACCESS),
            mode=SourceMode.ACCESS,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_mode, SourceMode.ACCESS)
        self.assertEqual(stubs[0].rank, 4)
        self.assertEqual(stubs[0].title_ja, "昨年皐月賞＆有馬記念覇者ミュージアムマイルは放牧中")
        self.assertIn("s000040", stubs[0].source_url)

    def test_sky_sports_access_ranking_keeps_top_story_order(self):
        adapter = SkySportsRacingAdapter()
        stubs = adapter.parse_listing_html(
            """
            <main>
              <a href="/football/news/11661/1/not-racing">Football story</a>
              <a href="/racing/news/12426/100/racing-top-story">Racing top story</a>
              <a href="/racing/news/12426/101/royal-ascot-preview">Royal Ascot preview</a>
            </main>
            """,
            url=adapter.listing_url(1, mode=SourceMode.ACCESS),
            mode=SourceMode.ACCESS,
        )

        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[0].source_mode, SourceMode.ACCESS)
        self.assertEqual(stubs[0].rank, 1)
        self.assertEqual(stubs[1].rank, 2)
        self.assertEqual(stubs[0].title_ja, "Racing top story")

    def test_france_galop_english_news_uses_official_english_pages(self):
        adapter = FranceGalopEnglishNewsAdapter()
        stubs = adapter.parse_listing_html(
            """
            <div class="views-row">
              <h2><a href="/en/content/grand-prix-preview">Grand Prix preview</a></h2>
            </div>
            <h2><a href="/fr/content/article-francais">Article français</a></h2>
            """,
            url=adapter.listing_url(1, mode=SourceMode.OFFICIAL),
            mode=SourceMode.OFFICIAL,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_site, SourceSite.FRANCE_GALOP_NEWS)
        self.assertEqual(stubs[0].source_mode, SourceMode.OFFICIAL)
        self.assertEqual(stubs[0].source_url, "https://www.france-galop.com/en/content/grand-prix-preview")

    def test_tdn_latest_listing_uses_public_wordpress_api(self):
        adapter = TDNAdapter()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "link": "https://www.thoroughbreddailynews.com/test-story/",
                        "title": {"rendered": "TDN &amp; racing update"},
                        "date_gmt": "2026-06-25T01:02:03",
                    }
                ]

        with patch("stable.adapters.international.requests.get", return_value=FakeResponse()):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_site, SourceSite.TDN)
        self.assertEqual(stubs[0].title_ja, "TDN & racing update")
        self.assertEqual(stubs[0].source_url, "https://www.thoroughbreddailynews.com/test-story/")
        self.assertIsNotNone(stubs[0].published_at.tzinfo)

    def test_tdn_normalize_preserves_listing_timestamp_when_detail_has_no_date(self):
        adapter = TDNAdapter()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "link": "https://www.thoroughbreddailynews.com/test-story/",
                        "title": {"rendered": "TDN racing update"},
                        "date_gmt": "2026-06-25T01:02:03",
                    }
                ]

        with patch("stable.adapters.international.requests.get", return_value=FakeResponse()):
            stub = adapter.fetch_listing(SourceMode.LATEST, 1)[0]
        detail = adapter.parse_detail_html(
            """
            <html><body>
              <article>
                <h1>TDN racing update</h1>
                <div class="entry-content"><p>Body without a date node.</p></div>
              </article>
            </body></html>
            """,
            url=stub.source_url,
        )

        draft = adapter.normalize_source_payload(stub, detail)

        self.assertIsNone(detail.published_at)
        self.assertEqual(draft.published_at, datetime(2026, 6, 25, 1, 2, 3, tzinfo=dt_timezone.utc))

    def test_tdn_france_keyword_listing_marks_france_region(self):
        adapter = TDNFranceKeywordAdapter()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [{"url": "https://www.thoroughbreddailynews.com/france-galop-story/", "title": "France Galop story"}]

        with patch("stable.adapters.international.requests.get", return_value=FakeResponse()):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 1)
        self.assertEqual(adapter.racing_region, RacingRegion.FRANCE)
        self.assertEqual(stubs[0].source_site, SourceSite.TDN_FRANCE)
        self.assertEqual(stubs[0].title_ja, "France Galop story")

    def test_tdn_france_keyword_draft_uses_tdn_canonical_source_site(self):
        adapter = TDNFranceKeywordAdapter()
        stub = SourceArticleStub(
            source_site=SourceSite.TDN_FRANCE,
            source_mode=SourceMode.LATEST,
            source_article_id="france-galop-story-123",
            source_url="https://www.thoroughbreddailynews.com/france-galop-story/",
            title_ja="France Galop story",
            published_at=timezone.now(),
        )
        detail = SourceArticleDetail(
            title_ja="France Galop story",
            body_ja_raw="France Galop story body",
            body_ja_normalized="France Galop story body",
            published_at=None,
            images=[],
        )

        draft = adapter.normalize_source_payload(stub, detail)

        self.assertEqual(draft.source_site, SourceSite.TDN_FRANCE)
        self.assertEqual(draft.canonical_source_site, SourceSite.TDN)
        self.assertEqual(draft.racing_region, RacingRegion.FRANCE)

    def test_horse_racing_nation_access_prefers_trending_links(self):
        adapter = HorseRacingNationAdapter()
        stubs = adapter.parse_listing_html(
            """
            <div class="ticker">
              <a href="/news/Trending_story_123">Trending story</a>
            </div>
            <main>
              <a href="/news/Latest_story_456">Latest story</a>
            </main>
            """,
            url=adapter.listing_url(1, mode=SourceMode.ACCESS),
            mode=SourceMode.ACCESS,
        )

        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[0].title_ja, "Trending story")
        self.assertEqual(stubs[0].rank, 1)
        self.assertEqual(stubs[1].rank, 2)

    def test_horse_racing_nation_listing_skips_news_index_links(self):
        adapter = HorseRacingNationAdapter()
        stubs = adapter.parse_listing_html(
            """
            <main>
              <a href="/news/news.aspx">Horse Racing News - Today's News Stories</a>
              <a href="/news/Real_story_123">Real racing story</a>
            </main>
            """,
            url=adapter.listing_url(1, mode=SourceMode.LATEST),
            mode=SourceMode.LATEST,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].title_ja, "Real racing story")

    def test_jra_listing_skips_bad_date_and_keeps_following_items(self):
        html = """
        <div class="news_unit"><h2>bad-date</h2>
        <ul class="news_line_list"><li><a href="/news/202605/053099.html"><div class="txt">坏日期</div></a></li></ul>
        </div>
        <div class="news_unit"><h2>5月31日（日曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202605/053101.html"><div class="txt">可解析新闻</div></a></li></ul>
        </div>
        """
        adapter = JRAAdapter()
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = adapter.fetch_listing(SourceMode.OFFICIAL, "202605")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title_ja, "可解析新闻")
        self.assertEqual(len(adapter.skipped_items), 1)

    def test_netkeiba_rank_schedule_and_builtin_interval_stay_aligned(self):
        latest_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-latest-hourly"]["schedule"]
        rush_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-latest-sunday-rush"]["schedule"]
        rush_end_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-latest-sunday-rush-end"]["schedule"]
        access_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-access"]["schedule"]
        attention_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-attention"]["schedule"]

        def minute_values(schedule):
            return {int(item) for item in str(schedule._orig_minute).split(",")}

        latest_minutes = minute_values(latest_schedule)
        access_minutes = minute_values(access_schedule)
        attention_minutes = minute_values(attention_schedule)
        rush_minutes = minute_values(rush_schedule) | minute_values(rush_end_schedule)

        self.assertEqual(access_schedule._orig_minute, 16)
        self.assertEqual(attention_schedule._orig_minute, 26)
        self.assertEqual(access_schedule._orig_hour, "*")
        self.assertEqual(attention_schedule._orig_hour, "*")
        self.assertTrue(latest_minutes.isdisjoint(access_minutes))
        self.assertTrue(latest_minutes.isdisjoint(attention_minutes))
        self.assertTrue(access_minutes.isdisjoint(attention_minutes))
        self.assertTrue(rush_minutes.isdisjoint(access_minutes))
        self.assertTrue(rush_minutes.isdisjoint(attention_minutes))
        definitions = {(item["source_site"], item["source_mode"]): item for item in BUILTIN_SOURCE_DEFINITIONS}
        self.assertEqual(definitions[(SourceSite.NETKEIBA, SourceMode.ACCESS)]["crawl_interval_minutes"], 60)
        self.assertEqual(definitions[(SourceSite.NETKEIBA, SourceMode.ATTENTION)]["crawl_interval_minutes"], 60)
        self.assertEqual(definitions[(SourceSite.SPONICHI, SourceMode.ACCESS)]["feed_url"], "https://www.sponichi.co.jp/gamble/ranking/")


class IngestionSourceElevationTests(TestCase):
    def setUp(self):
        sync_builtin_sources()

    def make_draft(self, source_article_id: str, source_mode: str, *, rank: int | None = None) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=SourceSite.NETKEIBA,
            source_mode=source_mode,
            source_article_id=source_article_id,
            source_url=f"https://news.netkeiba.com/?pid=news_view&no={source_article_id}",
            title_ja=f"榜单来源测试 {source_article_id}",
            body_ja_raw=f"榜单来源测试正文 {source_article_id}",
            body_ja_normalized=f"榜单来源测试正文 {source_article_id}",
            published_at=timezone.now(),
            images=[],
            rank=rank,
            metadata={"source_mode": source_mode},
        )

    def make_source_draft(
        self,
        source_article_id: str,
        source_mode: str,
        *,
        source_site: str,
        canonical_source_site: str | None = None,
        rank: int | None = None,
        racing_region: str = RacingRegion.JAPAN,
        source_language: str = SourceLanguage.JAPANESE,
    ) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=source_site,
            source_mode=source_mode,
            source_article_id=source_article_id,
            source_url=f"https://example.com/{source_site}/{source_article_id}",
            title_ja=f"排序来源测试 {source_article_id}",
            body_ja_raw=f"排序来源测试正文 {source_article_id}",
            body_ja_normalized=f"排序来源测试正文 {source_article_id}",
            published_at=timezone.now(),
            images=[],
            racing_region=racing_region,
            source_language=source_language,
            rank=rank,
            canonical_source_site=canonical_source_site,
            metadata={"source_mode": source_mode},
        )

    def upsert(self, source_article_id: str, source_mode: str, *, rank: int | None = None, crawl_job: CrawlJob | None = None):
        return upsert_article_from_draft(self.make_draft(source_article_id, source_mode, rank=rank), crawl_job=crawl_job)

    def unpack_article(self, result):
        return result[0] if isinstance(result, tuple) else result.article

    def source_elevated(self, result) -> bool:
        if hasattr(result, "source_elevated"):
            return bool(result.source_elevated)
        if isinstance(result, tuple) and len(result) >= 3:
            return bool(result[2])
        return False

    def test_latest_article_elevates_to_access_and_exposes_signal(self):
        self.upsert("rank-elevate-access", SourceMode.LATEST)
        access_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        access_job = CrawlJob.objects.create(source=access_source)

        result = self.upsert("rank-elevate-access", SourceMode.ACCESS, rank=1, crawl_job=access_job)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, access_source)
        self.assertEqual(article.source_note, access_source.name)
        self.assertEqual(article.crawl_job, access_job)
        self.assertTrue(self.source_elevated(result))
        self.assertTrue(
            NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.ACCESS, rank=1).exists()
        )

    def test_latest_article_elevates_to_attention_and_exposes_signal(self):
        self.upsert("rank-elevate-attention", SourceMode.LATEST)
        attention_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ATTENTION)

        result = self.upsert("rank-elevate-attention", SourceMode.ATTENTION, rank=2)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ATTENTION)
        self.assertEqual(article.source_config, attention_source)
        self.assertTrue(self.source_elevated(result))
        self.assertTrue(
            NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.ATTENTION, rank=2).exists()
        )

    def test_access_and_attention_do_not_override_each_other(self):
        result = self.upsert("rank-no-mutual-override", SourceMode.ACCESS, rank=3)
        article = self.unpack_article(result)
        access_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        self.assertEqual(article.source_mode, SourceMode.ACCESS)

        result = self.upsert("rank-no-mutual-override", SourceMode.ATTENTION, rank=4)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, access_source)
        self.assertFalse(self.source_elevated(result))
        self.assertTrue(
            NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.ATTENTION, rank=4).exists()
        )

    def test_latest_does_not_override_ranked_source(self):
        result = self.upsert("rank-not-overwritten-by-latest", SourceMode.ATTENTION, rank=5)
        article = self.unpack_article(result)
        attention_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ATTENTION)
        self.assertEqual(article.source_mode, SourceMode.ATTENTION)

        result = self.upsert("rank-not-overwritten-by-latest", SourceMode.LATEST)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ATTENTION)
        self.assertEqual(article.source_config, attention_source)
        self.assertFalse(self.source_elevated(result))
        self.assertTrue(NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.LATEST).exists())

    def test_international_latest_article_elevates_to_ranked_source(self):
        latest_draft = self.make_source_draft(
            "sky-ranked-elevate",
            SourceMode.LATEST,
            source_site=SourceSite.SKY_SPORTS_RACING,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
        )
        upsert_article_from_draft(latest_draft)
        ranked_source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)

        result = upsert_article_from_draft(
            self.make_source_draft(
                "sky-ranked-elevate",
                SourceMode.ACCESS,
                source_site=SourceSite.SKY_SPORTS_RACING,
                rank=1,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_language=SourceLanguage.ENGLISH,
            )
        )

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, ranked_source)
        self.assertTrue(self.source_elevated(result))

    def test_latest_source_does_not_override_international_ranked_source(self):
        ranked_draft = self.make_source_draft(
            "hrn-ranked-keeps-priority",
            SourceMode.ACCESS,
            source_site=SourceSite.HORSE_RACING_NATION,
            rank=3,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
        )
        result = upsert_article_from_draft(ranked_draft)
        article = self.unpack_article(result)
        ranked_source = NewsSource.objects.get(source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.ACCESS)
        self.assertEqual(article.source_mode, SourceMode.ACCESS)

        result = upsert_article_from_draft(
            self.make_source_draft(
                "hrn-ranked-keeps-priority",
                SourceMode.LATEST,
                source_site=SourceSite.HORSE_RACING_NATION,
                racing_region=RacingRegion.UNITED_STATES,
                source_language=SourceLanguage.ENGLISH,
            )
        )

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, ranked_source)
        self.assertFalse(self.source_elevated(result))
        self.assertTrue(NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.LATEST).exists())

    def test_tdn_france_keyword_dedupes_against_tdn_and_keeps_france_region(self):
        normal_draft = self.make_source_draft(
            "tdn-shared-url",
            SourceMode.LATEST,
            source_site=SourceSite.TDN,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
        )
        france_draft = self.make_source_draft(
            "tdn-shared-url",
            SourceMode.LATEST,
            source_site=SourceSite.TDN_FRANCE,
            canonical_source_site=SourceSite.TDN,
            racing_region=RacingRegion.FRANCE,
            source_language=SourceLanguage.ENGLISH,
        )
        france_source = NewsSource.objects.get(source_site=SourceSite.TDN_FRANCE, source_mode=SourceMode.LATEST)

        first_result = upsert_article_from_draft(normal_draft)
        second_result = upsert_article_from_draft(france_draft)

        article = self.unpack_article(first_result)
        article.refresh_from_db()
        self.assertFalse(second_result.created)
        self.assertEqual(NewsArticle.objects.filter(source_site=SourceSite.TDN, source_article_id="tdn-shared-url").count(), 1)
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertEqual(article.source_config, france_source)
        self.assertTrue(
            NewsSnapshot.objects.filter(
                article=article,
                source_site=SourceSite.TDN_FRANCE,
                source_mode=SourceMode.LATEST,
            ).exists()
        )

        upsert_article_from_draft(normal_draft)
        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertEqual(article.source_config, france_source)


class InternationalSourceMetadataTests(TestCase):
    def test_sync_builtin_sources_includes_region_language_and_kind(self):
        sync_builtin_sources()

        jra = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        hkjc = NewsSource.objects.get(source_site=SourceSite.HKJC_NEWS, source_mode=SourceMode.LATEST)
        france = NewsSource.objects.get(source_site=SourceSite.FRANCE_GALOP_NEWS, source_mode=SourceMode.OFFICIAL)
        sky_ranked = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        hpn_ranked = NewsSource.objects.get(source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.ACCESS)
        at_the_races = NewsSource.objects.get(source_site=SourceSite.AT_THE_RACES, source_mode=SourceMode.LATEST)

        self.assertEqual(jra.racing_region, RacingRegion.JAPAN)
        self.assertEqual(jra.source_language, SourceLanguage.JAPANESE)
        self.assertEqual(hkjc.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(hkjc.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(france.racing_region, RacingRegion.FRANCE)
        self.assertEqual(france.source_language, SourceLanguage.ENGLISH)
        self.assertFalse(france.enabled)
        self.assertEqual(sky_ranked.adapter_key, "sky_sports_racing")
        self.assertEqual(hpn_ranked.adapter_key, "horse_racing_nation")
        self.assertGreater(sky_ranked.priority, NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.LATEST).priority)
        self.assertIn("403", at_the_races.notes)

    def test_sync_builtin_sources_preserves_manual_enabled_flags(self):
        sync_builtin_sources()
        sky_latest = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.LATEST)
        jra = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        sky_latest.enabled = True
        sky_latest.save(update_fields=["enabled", "updated_at"])
        jra.enabled = False
        jra.save(update_fields=["enabled", "updated_at"])

        sync_builtin_sources()

        sky_latest.refresh_from_db()
        jra.refresh_from_db()
        self.assertTrue(sky_latest.enabled)
        self.assertFalse(jra.enabled)

    def test_default_probe_sources_are_first_version_usable_sources(self):
        self.assertIn("sky_sports_racing", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("france_galop_news", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("tdn_france", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("tdn", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("horse_racing_nation", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertNotIn("at_the_races_france", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertNotIn("bloodhorse", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertNotIn("paulick_report", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn(("sky_sports_racing", SourceMode.ACCESS), FIRST_VERSION_INTERNATIONAL_PROBES)
        self.assertIn(("horse_racing_nation", SourceMode.ACCESS), FIRST_VERSION_INTERNATIONAL_PROBES)
        self.assertIn(("france_galop_news", SourceMode.OFFICIAL), FIRST_VERSION_INTERNATIONAL_PROBES)
        self.assertNotIn(("at_the_races_france", SourceMode.LATEST), FIRST_VERSION_INTERNATIONAL_PROBES)

    def test_article_upsert_inherits_region_and_language_from_source(self):
        sync_builtin_sources()
        draft = CanonicalNewsDraft(
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            source_article_id="hkjc-meta-1",
            source_url="https://racingnews.hkjc.com/english/example",
            title_ja="HKJC news",
            body_ja_raw="HKJC body",
            body_ja_normalized="HKJC body",
            published_at=timezone.now(),
            images=[],
        )

        result = upsert_article_from_draft(draft)

        self.assertEqual(result.article.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(result.article.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(result.article.source_config.adapter_key, "hkjc_news")

    def test_article_upsert_keeps_html_out_of_translation_metadata(self):
        sync_builtin_sources()
        draft = CanonicalNewsDraft(
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            source_article_id="hkjc-html-meta",
            source_url="https://racingnews.hkjc.com/english/html-meta",
            title_ja="HKJC HTML metadata",
            body_ja_raw="HKJC body",
            body_ja_normalized="HKJC body",
            published_at=timezone.now(),
            images=[],
            original_content_html="<html><body>full page</body></html>",
            metadata={"html": "<html>legacy html</html>", "author": "HKJC"},
        )

        result = upsert_article_from_draft(draft)

        self.assertEqual(result.article.original_content_html, "<html><body>full page</body></html>")
        self.assertEqual(result.article.translation_metadata.get("author"), "HKJC")
        self.assertNotIn("html", result.article.translation_metadata)
        snapshot = NewsSnapshot.objects.get(article=result.article)
        self.assertEqual(snapshot.snapshot_metadata.get("author"), "HKJC")
        self.assertNotIn("html", snapshot.snapshot_metadata)


class FakeExternalHorseDataAdapter:
    def __init__(self):
        self.fetched_race_ids: list[str] = []

    def race_list(self, year: int, month: int) -> list[str]:
        return [f"{year}{month:02d}0101", f"{year}{month:02d}0102"]

    def fetch_race(self, race_id: str, *, fetch_odds: bool = False) -> dict:
        self.fetched_race_ids.append(race_id)
        return {
            "race": {
                "race_id": race_id,
                "race_name": "東京優駿",
                "race_date": "2026-05-31",
                "extra_field": "保留字段",
            },
            "entry": [
                {
                    "horse_id": "1001",
                    "horse_name": "マヤノライジン",
                    "horse_number": "1",
                    "jockey_name": "武豊",
                    "extra_entry": "保存",
                },
                {
                    "horse_id": "1002",
                    "horse_name": "クロワデュノール",
                    "horse_number": "2",
                },
            ],
            "result": [
                {
                    "horse_id": "1001",
                    "horse_name": "マヤノライジン",
                    "horse_number": "1",
                    "finish_position": "1",
                }
            ],
            "odds": [{"odds_type": "win", "horse_number": "1", "odds": "2.1"}] if fetch_odds else [],
        }

    def fetch_horse(self, horse_id: str) -> dict:
        return {
            "horse": {
                "horse_id": horse_id,
                "father_name": "マヤノトップガン",
                "unknown_future_field": "後で使う",
            },
            "history": [
                {
                    "race_id": "202605310101",
                    "race_name": "東京優駿",
                    "race_date": "2026-05-31",
                    "finish_position": "1",
                }
            ],
        }


@override_settings(EXTERNAL_HORSE_DATA_IMPORT_ENABLED=True)
class ExternalHorseDataImportTests(TestCase):
    def importer(self, **overrides):
        adapter = overrides.pop("adapter", None) or FakeExternalHorseDataAdapter()
        values = {
            "allow_network": True,
            "request_interval_seconds": 0,
            "jitter_seconds": 0,
            "max_races": 1,
            "max_horses": 10,
            "fetch_odds": True,
            "fetch_horse_detail": True,
        }
        values.update(overrides)
        options = ImportOptions(**values)
        return ExternalHorseDataImporter(options, adapter=adapter)

    def test_import_race_preserves_payload_and_is_idempotent(self):
        importer = self.importer()

        first = importer.import_race("202605310101")
        second = importer.import_race("202605310101")

        self.assertEqual(first["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(second["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 2)
        self.assertEqual(ExternalRaceResult.objects.count(), 1)
        self.assertEqual(ExternalRaceOdds.objects.count(), 1)
        self.assertEqual(ExternalHorseAlias.objects.filter(name_ja="マヤノライジン").count(), 1)
        race = ExternalRace.objects.get()
        self.assertEqual(race.raw_payload["extra_field"], "保留字段")
        entry = ExternalRaceEntry.objects.get(horse_id="1001")
        self.assertEqual(entry.raw_payload["extra_entry"], "保存")

    def test_dry_run_does_not_write_external_tables(self):
        importer = self.importer(dry_run=True, allow_network=False)

        result = importer.import_race("202605310101")

        self.assertTrue(result["dry_run"])
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)
        self.assertEqual(ExternalRace.objects.count(), 0)

    @override_settings(EXTERNAL_HORSE_DATA_IMPORT_ENABLED=False)
    def test_real_import_requires_enabled_setting(self):
        with self.assertRaises(ExternalHorseDataNetworkDisabled):
            self.importer().import_race("202605310101")

    def test_single_horse_import_only_creates_alias_with_trusted_name(self):
        importer = self.importer(fetch_horse_detail=True)

        importer.import_horse("1001")
        importer.import_horse("1002", horse_name="マヤノライジン")

        self.assertFalse(ExternalHorseAlias.objects.filter(external_horse_id="1001").exists())
        alias = ExternalHorseAlias.objects.get(external_horse_id="1002")
        self.assertEqual(alias.name_ja, "マヤノライジン")

    def test_source_lock_blocks_parallel_real_imports(self):
        run = ExternalDataImportRun.objects.create(source="netkeiba", target_type="month", status=ExternalImportStatus.STARTED)
        ExternalDataImportLock.objects.create(source="netkeiba", locked_by_run=run, acquired_at=timezone.now())

        with self.assertRaises(ExternalHorseDataAlreadyRunning):
            self.importer().import_race("202605310101")

    def test_month_import_respects_max_races_and_records_coverage_stats(self):
        result = self.importer(max_races=1).import_month(2026, 5)

        self.assertEqual(result["status"], ExternalImportStatus.PAUSED)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["coverage_stats"]["race_count"], 1)
        self.assertEqual(result["coverage_stats"]["unique_horse_name_count"], 2)

    def test_month_import_skips_existing_races_and_processes_next_batch(self):
        first_adapter = FakeExternalHorseDataAdapter()
        second_adapter = FakeExternalHorseDataAdapter()

        first = self.importer(adapter=first_adapter, max_races=1).import_month(2026, 5)
        second = self.importer(adapter=second_adapter, max_races=1).import_month(2026, 5)

        self.assertEqual(first["status"], ExternalImportStatus.PAUSED)
        self.assertEqual(second["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(first_adapter.fetched_race_ids, ["2026050101"])
        self.assertEqual(second_adapter.fetched_race_ids, ["2026050102"])
        self.assertEqual(ExternalRace.objects.count(), 2)
        second_run = ExternalDataImportRun.objects.get(pk=second["run_id"])
        self.assertEqual(second_run.parameters["already_imported_race_count"], 1)

    def test_management_command_dry_run_does_not_write(self):
        out = StringIO()

        call_command("import_external_horse_data", "--race-id", "202605310101", "--dry-run", stdout=out)

        self.assertIn('"dry_run": true', out.getvalue())
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)
        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_management_command_lookup_name_reads_local_alias(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        out = StringIO()

        call_command("import_external_horse_data", "--lookup-name", "マヤノライジン", stdout=out)

        self.assertIn('"external_horse_id": "1001"', out.getvalue())


class HKJCExternalDataImportTests(TestCase):
    def test_hkjc_meeting_parser_filters_recent_result_dates(self):
        # Mutation: if the parser reads option labels instead of JSON values, or forgets the date window,
        # stale meetings such as 2026-04-22 leak into a 60-day import.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-meetings-sample.html"
        )
        parser = HKJCHTMLParser()

        meetings = parser.parse_result_meetings(
            fixture_path.read_text(encoding="utf-8"),
            start_date="2026-04-27",
            end_date="2026-06-26",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults",
        )

        self.assertEqual(
            [meeting["race_date"] for meeting in meetings],
            ["2026-06-24", "2026-06-21", "2026-05-27"],
        )
        self.assertEqual(meetings[0]["source_url"], "https://racing.hkjc.com/en-us/local/information/localresults")
        self.assertEqual(meetings[0]["raw_date"], "24/06/2026")

    def test_hkjc_result_parser_maps_race_and_result_rows(self):
        # Mutation: if horse IDs are parsed from brand numbers instead of horse links, aliases collide across seasons.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-sample.html"
        )
        parser = HKJCHTMLParser()

        race = parser.parse_race_result(
            fixture_path.read_text(encoding="utf-8"),
            race_date="2026-06-24",
            racecourse="HV",
            race_no="1",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
        )

        self.assertEqual(race["race_id"], "HK20260624HV01")
        self.assertEqual(race["race_date"], "2026-06-24")
        self.assertEqual(race["venue"], "Happy Valley")
        self.assertEqual(race["race_number"], "1")
        self.assertEqual(race["race_name"], "ICE HOUSE STREET HANDICAP")
        self.assertEqual(race["race_class"], "Class 5")
        self.assertEqual(race["distance"], "2200M")
        self.assertEqual(race["going"], "GOOD")
        self.assertEqual(race["prize_money"], "HK$ 875,000")
        self.assertEqual(len(race["entries"]), 2)
        self.assertEqual(len(race["results"]), 2)
        self.assertEqual(race["entries"][0]["horse_id"], "HK_2023_J524")
        self.assertEqual(race["entries"][0]["horse_name_en"], "ROSEWOOD FLEETFOOT")
        self.assertEqual(race["entries"][0]["horse_number"], "3")
        self.assertEqual(race["entries"][0]["barrier"], "10")
        self.assertEqual(race["results"][0]["finish_position"], "1")
        self.assertEqual(race["results"][0]["finish_time"], "2:16.62")
        self.assertEqual(race["results"][0]["odds"], "3.2")
        self.assertEqual(race["results"][1]["margin"], "1-1/4")
        self.assertEqual(race["raw_payload"]["source_url"], "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1")

    def test_hkjc_result_parser_handles_realistic_td_header_table(self):
        # Mutation: HKJC result tables often use td header cells; requiring th silently drops every runner.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-realistic-sample.html"
        )
        parser = HKJCHTMLParser()

        race = parser.parse_race_result(
            fixture_path.read_text(encoding="utf-8"),
            race_date="2026-06-24",
            racecourse="HV",
            race_no="1",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
        )

        self.assertEqual(race["race_name"], "ICE HOUSE STREET HANDICAP")
        self.assertEqual(race["course"], 'TURF - "A" Course')
        self.assertEqual(len(race["results"]), 1)
        self.assertEqual(race["results"][0]["horse_id"], "HK_2023_J524")

    def test_hkjc_horse_parser_maps_profile_fields(self):
        # Mutation: if profile label/value rows are parsed positionally, wrapped labels like Country of Origin / Age shift fields.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "horse-profile-sample.html"
        )
        parser = HKJCHTMLParser()

        horse = parser.parse_horse_profile(
            fixture_path.read_text(encoding="utf-8"),
            horse_id="HK_2023_J524",
            source_url="https://racing.hkjc.com/en-us/local/information/horse?horseid=HK_2023_J524",
        )

        self.assertEqual(horse["horse_id"], "HK_2023_J524")
        self.assertEqual(horse["horse_name_en"], "ROSEWOOD FLEETFOOT")
        self.assertEqual(horse["brand_number"], "J524")
        self.assertEqual(horse["country"], "NZ")
        self.assertEqual(horse["age"], "5")
        self.assertEqual(horse["color"], "Bay")
        self.assertEqual(horse["sex"], "Gelding")
        self.assertEqual(horse["trainer"], "P F Yiu")
        self.assertEqual(horse["owner"], "Lam Ka Lai & Yeung Wing Shut")
        self.assertEqual(horse["rating"], "45")
        self.assertEqual(horse["sire"], "Proisir")
        self.assertEqual(horse["dam"], "Ends Meet")
        self.assertEqual(horse["record_summary"], "2-1-1-16")
        self.assertEqual(horse["raw_payload"]["source_url"], "https://racing.hkjc.com/en-us/local/information/horse?horseid=HK_2023_J524")

    def sample_payload(self) -> dict:
        return {
            "races": [
                {
                    "race_id": "HK2026062101",
                    "race_date": "2026-06-21",
                    "venue": "Sha Tin",
                    "race_number": "1",
                    "race_name": "Class 4 Handicap",
                    "class": "Class 4",
                    "distance": "1200m",
                    "surface": "Turf",
                    "going": "Good",
                    "weather": "Fine",
                    "entries": [
                        {
                            "horse_id": "HKH001",
                            "horse_name_en": "Lucky Star",
                            "horse_name_zh_hant": "幸運星",
                            "horse_number": "1",
                            "barrier": "5",
                            "jockey": "Z Purton",
                            "trainer": "C Fownes",
                            "owner": "Happy Syndicate",
                            "weight": "126",
                            "rating": "60",
                        }
                    ],
                    "results": [
                        {
                            "horse_id": "HKH001",
                            "horse_name_en": "Lucky Star",
                            "finish_position": "1",
                            "finish_time": "1:09.88",
                            "margin": "",
                            "odds": "3.5",
                            "running_position": "2-1",
                            "sectional_time": "22.1",
                            "jockey": "Z Purton",
                            "trainer": "C Fownes",
                            "barrier": "5",
                        }
                    ],
                }
            ],
            "horses": [
                {
                    "horse_id": "HKH001",
                    "horse_name_en": "Lucky Star",
                    "horse_name_zh_hant": "幸運星",
                    "sire": "Deep Field",
                    "dam": "Lucky Mare",
                    "birth_date": "2021-03-01",
                    "owner": "Happy Syndicate",
                    "trainer": "C Fownes",
                    "country": "AUS",
                    "colour": "Bay",
                    "career_record": "10-2-1-1",
                }
            ],
        }

    def write_payload(self, payload: dict | None = None) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with handle:
            json.dump(payload or self.sample_payload(), handle, ensure_ascii=False)
        return handle.name

    def hkjc_response(self, *, url: str, text: str, status_code: int = 200):
        response = Mock()
        response.status_code = status_code
        response.url = url
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.text = text
        response.json.side_effect = ValueError("not json")
        return response

    def hkjc_date_page_with_race_links(self) -> str:
        return """
        <html><body>
          <a href="/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1">Race 1</a>
          <a href="/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=2">Race 2</a>
        </body></html>
        """

    def test_dry_run_reports_coverage_without_writing(self):
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=True))
        result = importer.import_race_date("2026-06-21", payload_file=self.write_payload())

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 1, "results": 1, "horses": 1})
        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_payload_import_is_idempotent_and_creates_aliases(self):
        payload_file = self.write_payload()
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        first = importer.import_race_date("2026-06-21", payload_file=payload_file)
        second = importer.import_race_date("2026-06-21", payload_file=payload_file)

        self.assertFalse(first["dry_run"])
        self.assertFalse(second["dry_run"])
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 1)
        self.assertEqual(ExternalRaceResult.objects.count(), 1)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="hkjc", external_horse_id="HKH001").count(), 2)
        race = ExternalRace.objects.get()
        self.assertEqual(race.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(race.going, "Good")
        horse_alias = ExternalHorseAlias.objects.get(source="hkjc", normalized_name="Lucky Star")
        self.assertEqual(horse_alias.source_language, SourceLanguage.ENGLISH)

    def test_commit_requires_payload_file_until_network_import_is_implemented(self):
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        with self.assertRaisesRegex(HKJCImportError, "requires --payload-file"):
            importer.import_race("HK2026062101")

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_commit_rejects_running_hkjc_import_lock(self):
        active_run = ExternalDataImportRun.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            target_type="race_date",
            status=ExternalImportStatus.STARTED,
        )
        ExternalDataImportLock.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            locked_by_run=active_run,
            acquired_at=timezone.now(),
        )
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        with self.assertRaisesRegex(HKJCImportError, "already running"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload())

        self.assertEqual(ExternalDataImportRun.objects.count(), 1)
        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_commit_rejects_payload_over_configured_limits(self):
        payload = self.sample_payload()
        payload["races"] = [*payload["races"], {**payload["races"][0], "race_id": "HK2026062102"}]
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False, max_races=1))

        with self.assertRaisesRegex(HKJCImportError, "max_races"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload(payload))

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_commit_rejects_entry_and_result_horses_over_configured_limits(self):
        payload = self.sample_payload()
        payload["horses"] = []
        payload["races"][0]["entries"] = [
            {"horse_id": "HKH001", "horse_name_en": "Lucky Star", "horse_number": "1"},
            {"horse_id": "HKH002", "horse_name_en": "Fast Runner", "horse_number": "2"},
        ]
        payload["races"][0]["results"] = [
            {"horse_id": "HKH003", "horse_name_en": "Late Charge", "finish_position": "1"},
        ]
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False, max_horses=2))

        with self.assertRaisesRegex(HKJCImportError, "max_horses"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload(payload))

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_hkjc_management_command_lookup_name(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            alias_source="test",
        )
        out = StringIO()

        call_command("import_hkjc_external_data", "--lookup-name", "Lucky Star", stdout=out)

        self.assertIn('"external_horse_id": "HKH001"', out.getvalue())

    def test_hkjc_management_command_stats_run_id_reports_coverage(self):
        payload_file = self.write_payload()
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))
        result = importer.import_race_date("2026-06-21", payload_file=payload_file)
        out = StringIO()

        call_command("import_hkjc_external_data", "--stats-run-id", str(result["run_id"]), stdout=out)

        stats = json.loads(out.getvalue())
        self.assertEqual(stats["run_id"], result["run_id"])
        self.assertEqual(stats["source"], "hkjc")
        self.assertEqual(stats["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(stats["success_count"], 4)
        self.assertEqual(stats["coverage_stats"], {"races": 1, "entries": 1, "results": 1, "horses": 1})
        self.assertEqual(stats["error_count"], 0)

    def test_hkjc_import_options_are_backed_by_runtime_settings(self):
        # Mutation: removing HKJC_IMPORT_* from settings.py would leave production limits stuck at code defaults.
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_REQUEST_INTERVAL_SECONDS"))
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_MAX_RACES_PER_RUN"))
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_MAX_HORSES_PER_RUN"))
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_MAX_REQUESTS_PER_RUN"))

        options = HKJCImportOptions.from_settings()

        self.assertEqual(options.request_interval_seconds, django_settings.HKJC_IMPORT_REQUEST_INTERVAL_SECONDS)
        self.assertEqual(options.max_races, django_settings.HKJC_IMPORT_MAX_RACES_PER_RUN)
        self.assertEqual(options.max_horses, django_settings.HKJC_IMPORT_MAX_HORSES_PER_RUN)
        self.assertEqual(options.max_requests, django_settings.HKJC_IMPORT_MAX_REQUESTS_PER_RUN)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=2,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=10,
    )
    def test_hkjc_network_dry_run_records_request_boundary_without_writing(self):
        # Mutation: treating --allow-network dry-run as a placeholder payload would hide request URLs and status.
        fake_payload = self.sample_payload()
        from stable.services import external_hkjc_data as hkjc_module

        mock_get = Mock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.url = "https://hkjc.example.test/racing/2026-06-21"
        mock_get.return_value.json.return_value = fake_payload
        mock_get.return_value.text = json.dumps(fake_payload)
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command("import_hkjc_external_data", "--race-date", "2026-06-21", "--allow-network", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["network_probe"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 1, "results": 1, "horses": 1})
        self.assertEqual(
            result["requests"],
            [
                {
                    "url": "https://hkjc.example.test/racing/2026-06-21",
                    "status_code": 200,
                    "target_type": "race_date",
                    "target_id": "2026-06-21",
                }
            ],
        )
        self.assertFalse(result["would_write_formal_tables"])
        self.assertTrue(mock_get.called)
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=2,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=10,
    )
    def test_hkjc_network_race_dry_run_parses_html_without_writing(self):
        # Mutation: if --allow-network still expects JSON, real HKJC HTML pages can never enter dry-run.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-sample.html"
        )
        mock_get = Mock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.url = "https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1"
        mock_get.return_value.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_get.return_value.text = fixture_path.read_text(encoding="utf-8")
        mock_get.return_value.json.side_effect = ValueError("not json")
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command("import_hkjc_external_data", "--race-id", "HK20260624HV01", "--allow-network", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["network_probe"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(
            result["requests"],
            [
                {
                    "url": "https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    "status_code": 200,
                    "target_type": "race",
                    "target_id": "HK20260624HV01",
                }
            ],
        )
        self.assertFalse(result["would_write_formal_tables"])
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalRaceResult.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=2,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=10,
    )
    def test_hkjc_network_race_commit_writes_html_payload(self):
        # Mutation: keeping the old "commit requires payload file" gate blocks verified real HKJC race HTML imports.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-sample.html"
        )
        mock_get = Mock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.url = "https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1"
        mock_get.return_value.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_get.return_value.text = fixture_path.read_text(encoding="utf-8")
        mock_get.return_value.json.side_effect = ValueError("not json")
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=True))

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            result = importer.import_race("HK20260624HV01")

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["success_count"], 5)
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 2)
        self.assertEqual(ExternalRaceResult.objects.count(), 2)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="hkjc").count(), 2)
        race = ExternalRace.objects.get()
        self.assertEqual(race.race_id, "HK20260624HV01")
        self.assertEqual(race.race_name, "ICE HOUSE STREET HANDICAP")
        self.assertFalse(ExternalDataImportLock.objects.get(source="hkjc").locked_by_run_id)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_recent_days_dry_run_fetches_races_and_horse_profiles(self):
        # Mutation: if recent-days only fetches race result pages, ExternalHorse details never become available.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_hkjc_external_data",
                "--recent-days",
                "60",
                "--end-date",
                "2026-06-26",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--max-requests",
                "10",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(len(result["requests"]), 4)
        self.assertEqual(result["requests"][0]["target_type"], "meeting_list")
        self.assertEqual(result["requests"][2]["target_type"], "race")
        self.assertEqual(result["requests"][3]["target_type"], "horse")
        self.assertEqual(result["requests"][3]["target_id"], "HK_2023_J524")
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorse.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_dry_run_reports_incomplete_when_horse_limit_truncates_profiles(self):
        # Mutation: without completion metadata, a limited sample can be mistaken for a complete 60-day import.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(
            HKJCImportOptions(dry_run=True, allow_network=True, request_interval_seconds=0, max_requests=10)
        )

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            result = importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(
            result["completion"],
            {
                "is_complete": False,
                "stop_reason": "limit_horses_reached",
                "meetings_found": 3,
                "races_imported": 1,
                "unique_horses_found": 2,
                "horse_profiles_fetched": 1,
                "limit_races": 1,
                "limit_horses": 1,
                "max_requests": 10,
            },
        )

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_date_range_commit_writes_horse_profiles_idempotently(self):
        # Mutation: if horse profile payloads are not part of the verified network payload, commit only creates aliases.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        response_cycle = [
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/localresults",
                text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
            ),
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                text=self.hkjc_date_page_with_race_links(),
            ),
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
            ),
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
            ),
        ]
        mock_get = Mock(side_effect=[*response_cycle, *response_cycle])
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(
            HKJCImportOptions(
                dry_run=False,
                allow_network=True,
                request_interval_seconds=0,
                max_races=5,
                max_horses=5,
                max_requests=10,
            )
        )

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            first = importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)
            second = importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        self.assertFalse(first["dry_run"])
        self.assertFalse(second["dry_run"])
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 2)
        self.assertEqual(ExternalRaceResult.objects.count(), 2)
        self.assertEqual(ExternalHorse.objects.count(), 1)
        horse = ExternalHorse.objects.get(source="hkjc", horse_id="HK_2023_J524")
        self.assertEqual(horse.horse_name_en, "ROSEWOOD FLEETFOOT")
        self.assertEqual(horse.country, "NZ")
        alias = ExternalHorseAlias.objects.get(source="hkjc", external_horse_id="HK_2023_J524", normalized_name="ROSEWOOD FLEETFOOT")
        self.assertEqual(alias.horse_id, horse.id)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=2.5,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_client_applies_request_interval_between_fetches(self):
        # Mutation: removing rate-limit sleep would make this import issue four consecutive requests with no pause.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=True, allow_network=True, request_interval_seconds=2.5))

        with patch.object(hkjc_module, "requests", fake_requests, create=True), patch.object(hkjc_module.time, "sleep") as sleep:
            importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        sleep.assert_has_calls([call(2.5), call(2.5), call(2.5)])

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=2,
    )
    def test_hkjc_network_import_stops_when_request_limit_is_exceeded(self):
        # Mutation: if request counting happens after fetch, a low max_requests guard cannot stop a large range early.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=True, allow_network=True, max_requests=2))

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(HKJCImportError, "max_requests"):
                importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(ExternalRace.objects.count(), 0)


class GlobalRacingSpikeIsolationTests(TestCase):
    def external_counts(self) -> dict[str, int]:
        return {
            "ExternalRace": ExternalRace.objects.count(),
            "ExternalRaceEntry": ExternalRaceEntry.objects.count(),
            "ExternalRaceResult": ExternalRaceResult.objects.count(),
            "ExternalHorse": ExternalHorse.objects.count(),
            "ExternalHorseAlias": ExternalHorseAlias.objects.count(),
        }

    def test_equibase_spike_records_counts_and_does_not_write_formal_tables(self):
        # Mutation: if a spike accidentally upserts ExternalRace or aliases, before/after counts diverge.
        before_counts = self.external_counts()

        from stable.services.global_racing_spikes import run_source_spike

        report = run_source_spike(
            source="equibase",
            fixture_payload={
                "sample_url": "https://www.equibase.com/static/entry/RaceCard.html",
                "request_count": 1,
                "fields": {"entries": True, "results": True, "horse_profile": False},
            },
            dry_run=True,
        )

        self.assertEqual(self.external_counts(), before_counts)
        self.assertEqual(report["before_counts"], before_counts)
        self.assertEqual(report["after_counts"], before_counts)
        self.assertEqual(report["source"], "equibase")
        self.assertEqual(report["readiness_status"], "needs_more_spike")
        self.assertFalse(report["wrote_formal_tables"])

    def test_uk_fr_us_spikes_reject_commit_mode(self):
        # Mutation: accepting commit=True for spike sources would bypass the OpenSpec read-only boundary.
        from stable.services.global_racing_spikes import run_source_spike

        for source in ("equibase", "sporting_life_bha", "france_galop"):
            with self.subTest(source=source):
                with self.assertRaisesMessage(ValueError, "read-only spike"):
                    run_source_spike(source=source, fixture_payload={}, dry_run=False, commit=True)


class PushTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="1",
            title_ja="原文标题",
            title_zh="中文标题",
            summary_zh="中文摘要",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            body_zh="中文正文",
            push_summary_zh="中文摘要",
            published_at=timezone.now(),
            source_url="https://example.com/article/1",
            workflow_status=WorkflowStatus.PENDING_REVIEW,
        )
        self.target = PushTarget.objects.create(name="测试群", group_id="10001", is_default=True)

    def test_build_push_message_contains_source_url(self):
        text, image_url = build_push_message(self.article)
        self.assertIn("中文标题", text)
        self.assertIn("https://example.com/article/1", text)
        self.assertIsNone(image_url)

    def test_build_push_message_skips_blank_summary_when_cleared_manually(self):
        self.article.summary_zh = ""
        self.article.push_summary_zh = "机器摘要"
        self.article.mark_manual_edits(["summary_zh"])
        self.article.save()

        text, _ = build_push_message(self.article)

        self.assertNotIn("机器摘要", text)
        self.assertIn("原文链接：https://example.com/article/1", text)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_push_article_success(self):
        with patch("stable.services.pushing.BotPusher.send_group_message", return_value={"status": "ok"}):
            logs = push_article_to_targets(self.article, [self.target])
        self.assertEqual(len(logs), 1)
        logs[0].refresh_from_db()
        self.article.refresh_from_db()
        self.assertEqual(logs[0].status, "success")
        self.assertEqual(self.article.status, "pushed")


@override_settings(
    SITE_URL="http://testserver",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    QQ_PUSH_SCOPE="all_public",
)
class QQAutoPushTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="qq-auto-1",
            title_ja="原文标题",
            title_zh="中文标题",
            summary_zh="中文摘要",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            body_zh="中文正文" * 80,
            push_summary_zh="中文摘要",
            published_at=timezone.now(),
            source_url="https://example.com/article/qq-auto-1",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            score_total=90,
        )
        self.target = PushTarget.objects.create(name="测试群", group_id="10001", is_default=False, is_active=True)
        self.inactive_target = PushTarget.objects.create(name="停用群", group_id="10002", is_active=False)

    def test_delivery_records_are_unique_per_article_and_target(self):
        first = ensure_qq_push_deliveries(self.article, [self.target])
        second = ensure_qq_push_deliveries(self.article, [self.target])

        self.assertEqual(first[0].id, second[0].id)
        self.assertEqual(QQPushDelivery.objects.count(), 1)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked", AUTO_REVIEW_THRESHOLD=75)
    def test_high_value_scope_uses_ranked_strategy_instead_of_score(self):
        self.assertFalse(should_push_news_to_qq(self.article).allowed)
        self.article.score_total = 20
        self.article.source_mode = SourceMode.ACCESS
        self.article.save(update_fields=["score_total", "source_mode", "updated_at"])

        result = should_push_news_to_qq(self.article)

        self.assertTrue(result.allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked", AUTO_REVIEW_THRESHOLD=75)
    def test_ranked_strategy_allows_attention_source(self):
        self.article.score_total = 20
        self.article.source_mode = SourceMode.ATTENTION
        self.article.save(update_fields=["score_total", "source_mode", "updated_at"])

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked", AUTO_REVIEW_THRESHOLD=75)
    def test_ranked_strategy_allows_international_ranked_sources(self):
        self.article.source_site = SourceSite.SKY_SPORTS_RACING
        self.article.source_mode = SourceMode.ACCESS
        self.article.racing_region = RacingRegion.UNITED_KINGDOM
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.score_total = 20
        self.article.save(
            update_fields=["source_site", "source_mode", "racing_region", "source_language", "score_total", "updated_at"]
        )

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_blank_target_regions_keep_legacy_japan_only_behavior(self):
        self.assertEqual(target_allowed_regions(self.target), {RacingRegion.JAPAN})
        self.target.allowed_regions = [""]
        self.target.save(update_fields=["allowed_regions", "updated_at"])
        self.assertEqual(target_allowed_regions(self.target), {RacingRegion.JAPAN})
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.save(update_fields=["racing_region", "source_language", "updated_at"])

        result = should_push_news_to_qq(self.article, target=self.target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_not_allowed")

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_invalid_target_regions_keep_legacy_japan_only_behavior(self):
        self.target.allowed_regions = ["hongkong"]
        self.target.save(update_fields=["allowed_regions", "updated_at"])
        self.assertEqual(target_allowed_regions(self.target), {RacingRegion.JAPAN})
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.save(update_fields=["racing_region", "source_language", "updated_at"])

        result = should_push_news_to_qq(self.article, target=self.target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_not_allowed")

    @override_settings(QQ_PUSH_SCOPE="all_public", AUTO_REVIEW_THRESHOLD=75)
    def test_all_public_scope_ignores_score(self):
        self.article.score_total = 20
        self.article.save(update_fields=["score_total", "updated_at"])

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="unsupported", AUTO_REVIEW_THRESHOLD=75)
    def test_invalid_scope_falls_back_to_high_value_only(self):
        self.article.score_total = 20
        self.article.save(update_fields=["score_total", "updated_at"])

        self.assertFalse(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="unsupported", AUTO_REVIEW_THRESHOLD=75)
    def test_invalid_importance_strategy_falls_back_to_ranked(self):
        self.article.source_mode = SourceMode.ACCESS
        self.article.score_total = 20
        self.article.save(update_fields=["source_mode", "score_total", "updated_at"])

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked")
    def test_blocker_article_is_not_eligible_for_auto_push(self):
        self.article.source_mode = SourceMode.ACCESS
        self.article.gate_issues = [
            {"code": "missing_body", "severity": "blocker", "message": "正文为空", "route": "manual_review", "payload": {}}
        ]
        self.article.save(update_fields=["source_mode", "gate_issues", "updated_at"])

        self.assertFalse(should_push_news_to_qq(self.article).allowed)

    def test_auto_push_message_uses_summary_and_public_url(self):
        message = build_qq_auto_push_message(self.article)

        self.assertIn("【UmaFans】中文标题", message)
        self.assertIn("中文摘要", message)
        self.assertIn(f"阅读全文：http://testserver/news/{self.article.id}/", message)

    def test_auto_push_message_truncates_body_when_summary_blank(self):
        self.article.summary_zh = ""
        self.article.push_summary_zh = ""
        self.article.translated_summary_zh = ""
        self.article.rewrite_summary_zh = ""
        self.article.save()

        message = build_qq_auto_push_message(self.article)

        self.assertIn("……", message)
        self.assertIn(f"阅读全文：http://testserver/news/{self.article.id}/", message)

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=3)
    def test_delivery_url_unavailable_records_retryable_error_type(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(False, "HTTP 404")):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.RETRYING)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.URL_UNAVAILABLE)

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_delivery_rechecks_blocker_before_sending(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        self.article.gate_issues = [
            {"code": "late_blocker", "severity": "blocker", "message": "发布后发现 blocker", "payload": {}}
        ]
        self.article.save(update_fields=["gate_issues", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible") as url_check,
            patch("stable.services.qq_auto_push.BotPusher.send_group_message") as send_message,
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SKIPPED)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.NOT_ELIGIBLE)
        self.assertEqual(delivery.last_error, "has_blocker")
        url_check.assert_not_called()
        send_message.assert_not_called()

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_skipped_delivery_can_send_after_article_becomes_eligible_again(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.SKIPPED
        delivery.last_error_type = QQPushErrorType.NOT_ELIGIBLE
        delivery.last_error = "has_blocker"
        delivery.save(update_fields=["status", "last_error_type", "last_error", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok"}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, "")
        self.assertEqual(delivery.last_error, "")

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=1)
    def test_delivery_onebot_failure_records_send_failed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", side_effect=RuntimeError("bot down")),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.FAILED)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.SEND_FAILED)

    def test_delivery_success_saves_message_id(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok", "data": {"message_id": 123}}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.message_id, "123")
        self.assertIsNotNone(delivery.sent_at)

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=1, ONEBOT_ACCESS_TOKEN="SECRET")
    def test_delivery_onebot_failed_json_records_send_failed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        class FailedResponse:
            text = '{"status":"failed","retcode":100,"wording":"bad SECRET"}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "failed", "retcode": 100, "wording": "bad SECRET"}

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.onebot.requests.post", return_value=FailedResponse()),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.FAILED)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.SEND_FAILED)
        self.assertNotIn("SECRET", delivery.last_error)

    @override_settings(QQ_PUSH_SENDING_STALE_SECONDS=60)
    def test_active_sending_delivery_is_not_reclaimed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.SENDING
        delivery.attempt_count = 1
        delivery.last_attempt_at = timezone.now()
        delivery.save(update_fields=["status", "attempt_count", "last_attempt_at", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible") as url_check,
            patch("stable.services.qq_auto_push.BotPusher.send_group_message") as send_message,
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENDING)
        self.assertEqual(delivery.attempt_count, 1)
        url_check.assert_not_called()
        send_message.assert_not_called()

    @override_settings(QQ_PUSH_SENDING_STALE_SECONDS=60)
    def test_stale_sending_delivery_is_reclaimed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.SENDING
        delivery.attempt_count = 1
        delivery.max_attempts = 3
        delivery.last_attempt_at = timezone.now() - timedelta(seconds=120)
        delivery.save(update_fields=["status", "attempt_count", "max_attempts", "last_attempt_at", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok", "data": {"message_id": 456}}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.message_id, "456")

    @override_settings(QQ_PUSH_MIN_INTERVAL_SECONDS=60)
    def test_delivery_attempt_delay_uses_target_last_attempt(self):
        first_delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        first_delivery.last_attempt_at = timezone.now() - timedelta(seconds=15)
        first_delivery.save(update_fields=["last_attempt_at", "updated_at"])
        second_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="qq-auto-2",
            title_ja="原文标题2",
            title_zh="中文标题2",
            body_ja_raw="原文正文2",
            body_ja_normalized="原文正文2",
            body_zh="中文正文2",
            published_at=timezone.now(),
            source_url="https://example.com/article/qq-auto-2",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            score_total=90,
        )
        second_delivery = ensure_qq_push_deliveries(second_article, [self.target])[0]

        delay = qq_push_next_attempt_delay(second_delivery)

        self.assertGreaterEqual(delay, 44)
        self.assertLessEqual(delay, 60)

    @override_settings(QQ_PUSH_ENABLED=True, QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked")
    def test_article_task_queues_only_active_targets_for_ranked_news(self):
        self.article.source_mode = SourceMode.ACCESS
        self.article.score_total = 20
        self.article.save(update_fields=["source_mode", "score_total", "updated_at"])
        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            result = qq_auto_push_article_task.run(self.article.id)

        self.assertIn("queued_delivery_ids", result)
        self.assertEqual(len(result["queued_delivery_ids"]), 1)
        self.assertEqual(QQPushDelivery.objects.count(), 1)
        self.assertEqual(QQPushDelivery.objects.get().target, self.target)
        delay.assert_called_once()

    @override_settings(QQ_PUSH_ENABLED=True, QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked")
    def test_article_task_uses_target_region_and_scope_config(self):
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.save(update_fields=["racing_region", "source_language", "updated_at"])
        self.target.allowed_regions = [RacingRegion.HONG_KONG]
        self.target.push_scope = "all_public"
        self.target.save(update_fields=["allowed_regions", "push_scope", "updated_at"])
        uk_us_target = PushTarget.objects.create(
            name="英美群",
            group_id="10003",
            allowed_regions=[RacingRegion.UNITED_KINGDOM, RacingRegion.UNITED_STATES],
            push_scope="all_public",
            is_active=True,
        )

        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            result = qq_auto_push_article_task.run(self.article.id)

        self.assertEqual(QQPushDelivery.objects.count(), 1)
        self.assertEqual(QQPushDelivery.objects.get().target, self.target)
        self.assertIn(str(uk_us_target.id), result["target_skip_reasons"])
        self.assertEqual(result["target_skip_reasons"][str(uk_us_target.id)], "region_not_allowed")
        delay.assert_called_once()

    def test_article_without_region_is_not_auto_push_eligible(self):
        NewsArticle.objects.filter(pk=self.article.pk).update(racing_region="")
        self.article.refresh_from_db()

        result = should_push_news_to_qq(self.article, target=self.target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_missing")

    @override_settings(QQ_PUSH_ENABLED=False)
    def test_manual_push_still_works_when_auto_push_disabled(self):
        with patch("stable.services.pushing.BotPusher.send_group_message", return_value={"status": "ok"}):
            logs = push_article_to_targets(self.article, [self.target])

        self.assertEqual(logs[0].status, "success")

    @override_settings(ONEBOT_ACCESS_TOKEN="SECRET", ONEBOT_TIMEOUT_SECONDS=1)
    def test_onebot_errors_redact_token(self):
        with patch("stable.services.onebot.requests.post", side_effect=requests.RequestException("bad SECRET")):
            with self.assertRaises(OneBotRequestError) as error:
                BotPusher().send_group_message("10001", "测试")

        self.assertNotIn("SECRET", str(error.exception))

    def test_admin_delivery_changelist_is_visible(self):
        user = User.objects.create_superuser("admin2", "admin2@example.com", "admin123456")
        client = Client()
        client.login(username="admin2", password="admin123456")
        ensure_qq_push_deliveries(self.article, [self.target])

        response = client.get(reverse("admin:stable_qqpushdelivery_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "测试群")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ConsoleFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser("admin", "admin@example.com", "admin123456")
        self.client.login(username="admin", password="admin123456")
        sync_builtin_sources()
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="detail-1",
            title_ja="大阪杯回顾",
            translated_title_zh="大阪杯回顾",
            translated_body_zh="这是自动翻译后的正文。",
            translated_summary_zh="自动摘要",
            title_zh="大阪杯回顾",
            summary_zh="自动摘要",
            body_ja_raw="日文正文",
            body_ja_normalized="日文正文",
            body_zh="这是自动翻译后的正文。",
            published_at=timezone.now(),
            source_url="https://example.com/detail-1",
            workflow_status=WorkflowStatus.PENDING_EDIT,
        )

    def _create_article(self, source_article_id: str, title_ja: str) -> NewsArticle:
        return NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id=source_article_id,
            title_ja=title_ja,
            translated_title_zh=title_ja,
            translated_body_zh=f"{title_ja} 的译文",
            title_zh=title_ja,
            body_ja_raw=f"{title_ja} 原文",
            body_ja_normalized=f"{title_ja} 原文",
            body_zh=f"{title_ja} 的译文",
            published_at=timezone.now(),
            source_url=f"https://example.com/{source_article_id}",
            workflow_status=WorkflowStatus.PENDING_EDIT,
        )

    def _post_quick_term(
        self,
        article: NewsArticle,
        source_ja: str,
        target_zh: str,
        *,
        source_context: str = "candidate",
        term_type: str = "horse",
        follow: bool = False,
    ):
        next_url = (
            reverse("console-article-editor", args=[article.id])
            if source_context == "editor"
            else reverse("console-candidate-detail", args=[article.id])
        )
        return self.client.post(
            reverse("console-article-quick-term-create", args=[article.id]),
            {
                "source_ja": source_ja,
                "term_type": term_type,
                "target_zh": target_zh,
                "source_context": source_context,
                "next": next_url,
            },
            follow=follow,
        )

    def _assert_quick_term_toast(self, response, source_ja: str, target_zh: str, context: str):
        self.assertContains(response, f"术语【{source_ja}（{target_zh}）】已添加，点击此处立即应用到文章中")
        self.assertContains(response, "data-quick-term-followup-toast")
        self.assertContains(response, 'data-auto-dismiss-ms="15000"')
        self.assertContains(response, "data-quick-term-followup-close")
        self.assertContains(response, f"apply-created-term-{context}")
        self.assertNotContains(response, f"刚创建术语：{source_ja}")
        self.assertNotContains(response, f"retranslate-created-term-{context}")

    def test_dashboard_and_sources_page_available(self):
        dashboard = self.client.get(reverse("console-dashboard"))
        source_page = self.client.get(reverse("console-source-list"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "工作台")
        self.assertEqual(source_page.status_code, 200)
        self.assertContains(source_page, "来源管理")

    def test_source_pages_show_success_no_new_failure_and_stale_health(self):
        sources = {source.source_mode: source for source in NewsSource.objects.all()}
        latest = sources[SourceMode.LATEST]
        latest.last_crawl_at = timezone.now()
        latest.last_crawl_status = TaskStatus.SUCCESS
        latest.last_crawl_message = "新增 0，重复 120"
        latest.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=latest, status=TaskStatus.SUCCESS, success_count=0, fail_count=120)

        access = sources[SourceMode.ACCESS]
        access.last_crawl_at = timezone.now()
        access.last_crawl_status = TaskStatus.FAILED
        access.last_crawl_message = "解析失败"
        access.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=access, status=TaskStatus.FAILED, error_message="解析失败")

        attention = sources[SourceMode.ATTENTION]
        stale_time = timezone.now() - timedelta(hours=4)
        attention.last_crawl_at = stale_time
        attention.last_crawl_status = TaskStatus.SUCCESS
        attention.last_crawl_message = "新增 3，重复 37"
        attention.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=attention, status=TaskStatus.SUCCESS, success_count=3, fail_count=37, started_at=stale_time, finished_at=stale_time)

        source_page = self.client.get(reverse("console-source-list"))
        dashboard = self.client.get(reverse("console-dashboard"))
        self.assertContains(source_page, "成功无新增")
        self.assertContains(source_page, "新增 0，重复 120")
        self.assertContains(source_page, "解析失败")
        self.assertContains(source_page, "长时间未运行")
        self.assertContains(dashboard, "成功无新增")

    def test_source_health_shows_current_running_job_before_stale_success_cache(self):
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST)
        source.last_crawl_at = timezone.now() - timedelta(minutes=5)
        source.last_crawl_status = TaskStatus.SUCCESS
        source.last_crawl_message = "新增 0，重复 120"
        source.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=source, status=TaskStatus.SUCCESS, success_count=0, fail_count=120, finished_at=timezone.now() - timedelta(minutes=5))
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now())

        source_page = self.client.get(reverse("console-source-list"))

        self.assertContains(source_page, "运行中")
        self.assertNotContains(source_page, "成功无新增")

    def test_source_health_shows_first_running_job_instead_of_not_run_or_stale(self):
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now())

        source_page = self.client.get(reverse("console-source-list"))

        self.assertContains(source_page, "运行中")
        self.assertNotContains(source_page, "长时间未运行")

    def test_source_health_shows_timed_out_running_job(self):
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now() - timedelta(minutes=61))

        source_page = self.client.get(reverse("console-source-list"))

        self.assertContains(source_page, "运行超时")
        self.assertContains(source_page, "超过 60 分钟")

    def test_source_health_shows_old_never_run_source_as_stale(self):
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        old_time = timezone.now() - timedelta(hours=37)
        NewsSource.objects.filter(pk=source.pk).update(created_at=old_time)
        source.refresh_from_db()

        from stable.views import _source_health

        health = _source_health(source, now=timezone.now())

        self.assertEqual(health["label"], "长时间未运行")
        self.assertIn("超过", health["summary"])

    def test_source_health_does_not_mark_disabled_source_as_stale(self):
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        old_time = timezone.now() - timedelta(hours=37)
        NewsSource.objects.filter(pk=source.pk).update(created_at=old_time, enabled=False)
        source.refresh_from_db()

        from stable.views import _source_health

        health = _source_health(source, now=timezone.now())

        self.assertEqual(health["label"], "未运行")
        self.assertFalse(health["is_stale"])

    def test_public_backend_route_and_legacy_console_redirect_work(self):
        dashboard = self.client.get("/admin/")
        legacy = self.client.get("/console/", follow=False)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(legacy.status_code, 302)
        self.assertEqual(legacy["Location"], "/admin/")

    def test_editor_can_publish_article_and_show_on_public_page(self):
        response = self.client.post(
            reverse("console-article-editor", args=[self.article.id]),
            {
                "title_zh": "大阪杯回顾",
                "summary_zh": "中文摘要",
                "body_zh": "这是发布正文。",
                "tags_text": "赛事, 赛后复盘",
                "source_note": "netkeiba",
                "editor_notes": "已校对",
                "publish_without_cover": "1",
                "intent": "publish",
            },
            follow=True,
        )
        self.article.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        public_detail = self.client.get(self.article.public_path)
        self.assertEqual(public_detail.status_code, 200)
        self.assertContains(public_detail, "这是发布正文。")

    def test_candidate_retranslate_endpoint_redirects(self):
        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-candidate-retranslate", args=[self.article.id]),
                {"next": reverse("console-candidate-detail", args=[self.article.id])},
            )
        self.assertEqual(response.status_code, 302)
        mocked_dispatch.assert_called_once_with(translate_article_task, self.article.id)

    def test_apply_created_term_service_updates_only_specified_term(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_ja="マヤノライジン",
            target_zh="摩耶雷神",
            aliases_ja=["マヤノR"],
        )
        TermEntry.objects.create(term_type="race", source_ja="大阪杯", target_zh="大阪杯")
        other_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="detail-other",
            title_ja="其他文章",
            translated_body_zh="マヤノライジン",
            published_at=timezone.now(),
            source_url="https://example.com/detail-other",
        )
        self.article.translated_title_zh = "マヤノライジン挑战"
        self.article.translated_body_zh = "マヤノライジン与マヤノR连续出现。大阪杯保持原样。"
        self.article.base_translation_zh = "基准稿提到マヤノR，也提到大阪杯。"
        self.article.body_zh = "发布稿：マヤノライジン、マヤノライジン。大阪杯。"
        self.article.save()

        result = apply_created_term_to_article(self.article, term)

        self.article.refresh_from_db()
        other_article.refresh_from_db()
        self.assertIn("translated_title_zh", result.updated_fields)
        self.assertIn("translated_body_zh", result.updated_fields)
        self.assertIn("base_translation_zh", result.updated_fields)
        self.assertEqual(self.article.translated_title_zh, "摩耶雷神挑战")
        self.assertEqual(self.article.translated_body_zh, "摩耶雷神与摩耶雷神连续出现。大阪杯保持原样。")
        self.assertEqual(self.article.base_translation_zh, "基准稿提到摩耶雷神，也提到大阪杯。")
        self.assertEqual(self.article.body_zh, "发布稿：摩耶雷神、摩耶雷神。大阪杯。")
        self.assertEqual(other_article.translated_body_zh, "マヤノライジン")

    def test_apply_created_term_service_protects_manual_publish_fields(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.translated_body_zh = "机器稿 マヤノライジン"
        self.article.title_zh = "人工标题 マヤノライジン"
        self.article.body_zh = "人工正文 マヤノライジン"
        self.article.summary_zh = "人工摘要 マヤノライジン"
        self.article.push_summary_zh = "人工推送 マヤノライジン"
        self.article.manually_edited_fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
        self.article.save()

        result = apply_created_term_to_article(self.article, term)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translated_body_zh, "机器稿 摩耶雷神")
        self.assertEqual(self.article.title_zh, "人工标题 マヤノライジン")
        self.assertEqual(self.article.body_zh, "人工正文 マヤノライジン")
        self.assertEqual(self.article.summary_zh, "人工摘要 マヤノライジン")
        self.assertEqual(self.article.push_summary_zh, "人工推送 マヤノライジン")
        self.assertEqual(
            set(result.skipped_fields),
            {"title_zh", "body_zh", "summary_zh", "push_summary_zh"},
        )

    def test_candidate_detail_quick_term_create_defaults_to_horse_and_logs_article(self):
        response = self._post_quick_term(self.article, "マヤノライジン", "摩耶雷神", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "术语已创建：マヤノライジン")
        self.assertContains(response, "摩耶雷神")
        self._assert_quick_term_toast(response, "マヤノライジン", "摩耶雷神", "candidate")
        term = TermEntry.objects.get(source_ja="マヤノライジン")
        self.assertEqual(term.term_type, "horse")
        self.assertEqual(term.target_zh, "摩耶雷神")
        self.assertEqual(term.aliases_ja, [])
        self.assertEqual(term.aliases_zh, [])
        self.assertEqual(term.priority, 0)
        self.assertEqual(term.race_grade, "")
        self.assertTrue(term.is_active)
        self.assertIn(f"文章 #{self.article.id}", term.notes)
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_quick_term_created",
                target_type="term",
                target_id=str(term.id),
                detail__contains=f"文章 #{self.article.id}",
            ).exists()
        )

        refreshed = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        self.assertNotContains(refreshed, "术语【マヤノライジン（摩耶雷神）】已添加")
        self.assertNotContains(refreshed, "apply-created-term-candidate")

    def test_article_editor_quick_term_create_returns_to_editor(self):
        editor_url = reverse("console-article-editor", args=[self.article.id])
        response = self._post_quick_term(
            self.article,
            "大阪杯",
            "大阪杯",
            source_context="editor",
            term_type="race",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], editor_url)
        self._assert_quick_term_toast(response, "大阪杯", "大阪杯", "editor")
        self.assertTrue(TermEntry.objects.filter(term_type="race", source_ja="大阪杯").exists())

    def test_quick_term_followup_keeps_other_article_pending_until_matching_page_renders(self):
        other_article = self._create_article("detail-other-pending", "別記事")

        self._post_quick_term(self.article, "マヤノライジン", "摩耶雷神")

        other_response = self.client.get(reverse("console-candidate-detail", args=[other_article.id]))
        self.assertNotContains(other_response, "术语【マヤノライジン（摩耶雷神）】已添加")

        matching_response = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        self._assert_quick_term_toast(matching_response, "マヤノライジン", "摩耶雷神", "candidate")

    def test_quick_term_followup_keeps_parallel_candidate_and_editor_contexts(self):
        other_article = self._create_article("detail-editor-pending", "編集台記事")

        self._post_quick_term(self.article, "マヤノライジン", "摩耶雷神", source_context="candidate")
        self._post_quick_term(other_article, "ナリタブライアン", "成田白仁", source_context="editor")

        candidate_response = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        editor_response = self.client.get(reverse("console-article-editor", args=[other_article.id]))

        self._assert_quick_term_toast(candidate_response, "マヤノライジン", "摩耶雷神", "candidate")
        self._assert_quick_term_toast(editor_response, "ナリタブライアン", "成田白仁", "editor")

    def test_quick_term_followup_replaces_old_pending_for_same_page(self):
        self._post_quick_term(self.article, "古い馬", "旧译名")
        self._post_quick_term(self.article, "新しい馬", "新译名")

        response = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))

        self.assertNotContains(response, "术语【古い馬（旧译名）】已添加")
        self._assert_quick_term_toast(response, "新しい馬", "新译名", "candidate")

    def test_apply_created_term_from_followup_does_not_dispatch_translation_task(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.translated_body_zh = "マヤノライジン"
        self.article.save(update_fields=["translated_body_zh", "updated_at"])

        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-article-apply-created-term", args=[self.article.id]),
                {
                    "term_id": term.id,
                    "source_context": "candidate",
                    "next": reverse("console-candidate-detail", args=[self.article.id]),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        mocked_dispatch.assert_not_called()

    def test_apply_created_term_endpoint_updates_article_and_sanitizes_next(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.translated_body_zh = "マヤノライジン"
        self.article.base_translation_zh = "基准 マヤノライジン"
        self.article.body_zh = "发布 マヤノライジン"
        self.article.save()

        response = self.client.post(
            reverse("console-article-apply-created-term", args=[self.article.id]),
            {
                "term_id": term.id,
                "source_context": "editor",
                "next": "https://evil.example/",
            },
            follow=True,
        )

        self.article.refresh_from_db()
        self.assertEqual(response.redirect_chain[-1][0], reverse("console-article-editor", args=[self.article.id]))
        self.assertEqual(self.article.translated_body_zh, "摩耶雷神")
        self.assertEqual(self.article.base_translation_zh, "基准 摩耶雷神")
        self.assertEqual(self.article.body_zh, "发布 摩耶雷神")
        self.assertContains(response, "已应用该术语")
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_created_term_applied",
                target_type="article",
                target_id=str(self.article.id),
                detail__contains=f"术语 #{term.id}",
            )
            .filter(detail__contains="更新字段")
            .exists()
        )

    def test_apply_created_term_endpoint_reports_no_change_and_protected_fields(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.title_zh = "人工标题 マヤノライジン"
        self.article.body_zh = "人工正文 マヤノライジン"
        self.article.summary_zh = "人工摘要 マヤノライジン"
        self.article.push_summary_zh = "人工推送 マヤノライジン"
        self.article.manually_edited_fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
        self.article.save()

        response = self.client.post(
            reverse("console-article-apply-created-term", args=[self.article.id]),
            {
                "term_id": term.id,
                "source_context": "candidate",
                "next": reverse("console-candidate-detail", args=[self.article.id]),
            },
            follow=True,
        )

        self.article.refresh_from_db()
        self.assertEqual(self.article.title_zh, "人工标题 マヤノライジン")
        self.assertEqual(self.article.body_zh, "人工正文 マヤノライジン")
        self.assertEqual(self.article.summary_zh, "人工摘要 マヤノライジン")
        self.assertEqual(self.article.push_summary_zh, "人工推送 マヤノライジン")
        self.assertContains(response, "没有可更新字段")
        self.assertContains(response, "已保护人工编辑字段")

    def test_page_level_retranslate_logs_task_result_and_does_not_publish(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.workflow_status = WorkflowStatus.PENDING_EDIT
        self.article.save(update_fields=["workflow_status", "updated_at"])

        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-candidate-retranslate", args=[self.article.id]),
                {
                    "source_context": "candidate",
                    "next": reverse("console-candidate-detail", args=[self.article.id]),
                },
                follow=True,
            )

        self.article.refresh_from_db()
        mocked_dispatch.assert_called_once_with(translate_article_task, self.article.id)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertContains(response, "已重新触发翻译")
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_retranslated",
                target_id=str(self.article.id),
                detail__contains="任务已派发",
            )
            .exists()
        )
        self.assertFalse(
            OperationLog.objects.filter(
                action_type="article_retranslated",
                target_id=str(self.article.id),
                detail__contains=f"来源术语 #{term.id}",
            ).exists()
        )

    def test_quick_term_create_rejects_blank_long_and_duplicate_source(self):
        url = reverse("console-article-quick-term-create", args=[self.article.id])
        TermEntry.objects.create(term_type="horse", source_ja="重複馬", target_zh="重复马")
        cases = [
            (
                {"source_ja": "タイトル", "term_type": "horse", "target_zh": ""},
                "中文译词不能为空。",
            ),
            (
                {"source_ja": "", "term_type": "horse", "target_zh": "空词"},
                "原文不能为空",
            ),
            (
                {"source_ja": "ア" * 81, "term_type": "horse", "target_zh": "过长"},
                "原文过长",
            ),
            (
                {"source_ja": "マヤノライジン\nゲート確認", "term_type": "horse", "target_zh": "整段误选"},
                "不能包含换行",
            ),
            (
                {"source_ja": "重複馬", "term_type": "horse", "target_zh": "重复马二号"},
                "打开已有术语",
            ),
            (
                {"source_ja": "タイプ不正", "term_type": "not-a-term-type", "target_zh": "非法类型"},
                "术语类型不合法",
            ),
        ]

        for payload, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                before_count = TermEntry.objects.count()
                response = self.client.post(
                    url,
                    {**payload, "next": reverse("console-candidate-detail", args=[self.article.id])},
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(TermEntry.objects.count(), before_count)
                self.assertContains(response, expected_message)

    def test_quick_term_create_requires_staff(self):
        url = reverse("console-article-quick-term-create", args=[self.article.id])
        self.client.logout()

        anonymous = self.client.post(url, {"source_ja": "未登录", "term_type": "horse", "target_zh": "未登录"})
        self.assertEqual(anonymous.status_code, 302)
        self.assertFalse(TermEntry.objects.filter(source_ja="未登录").exists())

        normal_user = User.objects.create_user("editor", "editor@example.com", "editor123456")
        self.client.login(username="editor", password="editor123456")
        forbidden = self.client.post(url, {"source_ja": "普通用户", "term_type": "horse", "target_zh": "普通用户"})
        self.assertEqual(forbidden.status_code, 403)
        self.assertFalse(TermEntry.objects.filter(source_ja="普通用户").exists())

    def test_quick_term_create_does_not_retranslate_or_mutate_article_copy(self):
        self.article.title_zh = "旧中文标题"
        self.article.body_zh = "旧中文正文"
        self.article.base_translation_zh = "旧基准翻译"
        self.article.rewrite_body_zh = "旧改写正文"
        self.article.workflow_status = WorkflowStatus.PENDING_EDIT
        self.article.automation_status = AutomationStatus.PENDING
        self.article.save()

        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-article-quick-term-create", args=[self.article.id]),
                {
                    "source_ja": "非联动馬",
                    "term_type": "horse",
                    "target_zh": "非联动马",
                    "next": reverse("console-candidate-detail", args=[self.article.id]),
                },
            )

        self.assertEqual(response.status_code, 302)
        mocked_dispatch.assert_not_called()
        self.article.refresh_from_db()
        self.assertEqual(self.article.title_zh, "旧中文标题")
        self.assertEqual(self.article.body_zh, "旧中文正文")
        self.assertEqual(self.article.base_translation_zh, "旧基准翻译")
        self.assertEqual(self.article.rewrite_body_zh, "旧改写正文")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertEqual(self.article.automation_status, AutomationStatus.PENDING)

    def test_quick_term_create_rejects_missing_article_without_creating_term(self):
        response = self.client.post(
            reverse("console-article-quick-term-create", args=[999999]),
            {
                "source_ja": "存在しない記事",
                "term_type": "horse",
                "target_zh": "不存在文章",
                "next": reverse("console-candidate-detail", args=[self.article.id]),
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(TermEntry.objects.filter(source_ja="存在しない記事").exists())

    def test_candidate_and_editor_templates_include_quick_term_entry(self):
        candidate = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        editor = self.client.get(reverse("console-article-editor", args=[self.article.id]))

        for response in (candidate, editor):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "快速加入术语库")
            self.assertContains(response, "加入术语库后会出现一次性操作")
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
            self.assertContains(response, 'name="next"')
            self.assertContains(response, 'name="source_context"')
            self.assertContains(response, 'data-term-selection-source')
            self.assertContains(response, 'data-fill-selected-term')
            self.assertContains(response, '<option value="horse" selected>马名</option>', html=True)
            self.assertNotContains(response, "应用该术语到当前稿")
        self.assertContains(candidate, 'id="quick-term-candidate-form"')
        self.assertContains(candidate, 'form="quick-term-candidate-form"')
        self.assertContains(editor, 'id="quick-term-editor-form"')
        self.assertContains(editor, 'form="quick-term-editor-form"')

    def test_quick_term_script_prefills_only_original_selection(self):
        candidate = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        html = candidate.content.decode()

        self.assertIn('closest("[data-term-selection-source]")', html)
        self.assertIn("anchorSource !== focusSource", html)
        self.assertIn('status.textContent = "请先在原文标题或正文中选择一个短词。";', html)
        self.assertIn("sourceInput.value = text;", html)

    def test_public_feed_only_shows_published_articles(self):
        NewsArticle.objects.create(
            source_site=SourceSite.JRA,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="draft-2",
            title_ja="草稿新闻",
            title_zh="草稿新闻",
            body_ja_raw="原文",
            body_ja_normalized="原文",
            body_zh="未发布内容",
            published_at=timezone.now(),
            source_url="https://example.com/draft-2",
            workflow_status=WorkflowStatus.PENDING_EDIT,
        )
        self.article.workflow_status = WorkflowStatus.PUBLISHED
        self.article.published_to_web_at = timezone.now()
        self.article.save()
        response = self.client.get("/")
        self.assertContains(response, "大阪杯回顾")
        self.assertNotContains(response, "草稿新闻")

    def test_editor_requires_body_but_allows_blank_summary(self):
        response = self.client.post(
            reverse("console-article-editor", args=[self.article.id]),
            {
                "title_zh": "大阪杯回顾",
                "summary_zh": "",
                "body_zh": "",
                "tags_text": "",
                "source_note": "",
                "editor_notes": "",
                "intent": "save",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "正文不能为空。")

    def test_editor_can_clear_summary_without_being_refilled(self):
        self.article.summary_zh = "旧摘要"
        self.article.push_summary_zh = "机器摘要"
        self.article.translated_summary_zh = "机器摘要"
        self.article.save()

        response = self.client.post(
            reverse("console-article-editor", args=[self.article.id]),
            {
                "title_zh": "大阪杯回顾",
                "summary_zh": "",
                "body_zh": "这是自动翻译后的正文。",
                "tags_text": "",
                "source_note": "",
                "editor_notes": "",
                "intent": "save",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.article.refresh_from_db()
        self.assertEqual(self.article.summary_zh, "")
        self.assertEqual(self.article.effective_summary, "")

    def test_duplicate_reference_links_to_candidate_detail(self):
        original = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            source_article_id="original-for-duplicate-link",
            title_ja="相似原稿",
            translated_title_zh="相似原稿",
            title_zh="相似原稿",
            body_ja_raw="相似原稿の本文",
            body_ja_normalized="相似原稿の本文",
            translated_body_zh="相似原稿的正文。",
            body_zh="相似原稿的正文。",
            published_at=timezone.now(),
            source_url="https://example.com/original-for-duplicate-link",
            workflow_status=WorkflowStatus.PUBLISHED,
        )
        self.article.duplicate_of = original
        self.article.duplicate_score = 0.91
        self.article.workflow_status = WorkflowStatus.DUPLICATE
        self.article.save(update_fields=["duplicate_of", "duplicate_score", "workflow_status", "updated_at"])

        detail = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        candidate_list = self.client.get(reverse("console-candidate-list"))
        duplicate_href = reverse("console-candidate-detail", args=[original.id])

        self.assertContains(detail, f'href="{duplicate_href}"')
        self.assertContains(candidate_list, f'href="{duplicate_href}"')


class PublicHomeInfoFeedTests(TestCase):
    def make_article(
        self,
        source_article_id: str,
        title: str,
        *,
        workflow_status: str = WorkflowStatus.PUBLISHED,
        published_to_web_at=None,
        published_at=None,
        score_total: int = 0,
        race_priority: str = "",
        has_cover: bool = False,
        source_mode: str = SourceMode.LATEST,
        racing_region: str = RacingRegion.JAPAN,
        source_language: str = SourceLanguage.JAPANESE,
        tags: list[str] | None = None,
    ) -> NewsArticle:
        published_at = published_at or timezone.now()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=source_mode,
            racing_region=racing_region,
            source_language=source_language,
            source_article_id=source_article_id,
            title_ja=title,
            translated_title_zh=title,
            title_zh=title,
            body_ja_raw=f"{title} 原文",
            body_ja_normalized=f"{title} 原文",
            translated_body_zh=f"{title} 正文",
            body_zh=f"{title} 正文",
            translated_summary_zh=f"{title} 摘要",
            summary_zh=f"{title} 摘要",
            published_at=published_at,
            source_url=f"https://example.com/{source_article_id}",
            workflow_status=workflow_status,
            published_to_web_at=published_to_web_at if published_to_web_at is not None else published_at,
            source_note="netkeiba",
            tags_json=tags or ["赛马"],
            score_total=score_total,
            decision_reason={"signals": {"race_priority": race_priority}} if race_priority else {},
        )
        if has_cover:
            NewsImage.objects.create(
                article=article,
                original_url=f"https://example.com/images/{source_article_id}.jpg",
                caption_zh=title,
            )
        return article

    def test_article_public_path_uses_article_id(self):
        article = self.make_article("id-public-path", "ID 链接文章")

        self.assertEqual(article.public_path, f"/news/{article.id}/")

    def test_unsaved_article_public_path_is_blank(self):
        article = NewsArticle(title_zh="未保存文章")

        self.assertEqual(article.public_path, "")

    def test_public_article_detail_can_be_visited_by_article_id(self):
        article = self.make_article("id-detail", "ID 详情文章")

        response = self.client.get(f"/news/{article.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ID 详情文章")

    def test_unpublished_article_id_is_not_public(self):
        article = self.make_article(
            "id-unpublished",
            "未发布 ID 文章",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=None,
        )

        response = self.client.get(f"/news/{article.id}/")

        self.assertEqual(response.status_code, 404)

    def test_legacy_non_numeric_slug_redirects_to_article_id_url(self):
        article = self.make_article("legacy-slug", "旧 slug 文章")
        article.public_slug = "legacy-slug-path"
        article.save(update_fields=["public_slug", "updated_at"])

        response = self.client.get("/news/legacy-slug-path/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/news/{article.id}/")

    def test_public_home_links_use_article_id_url(self):
        article = self.make_article("home-id-link", "首页 ID 链接文章")
        article.public_slug = "home-legacy-slug"
        article.save(update_fields=["public_slug", "updated_at"])

        response = self.client.get("/")

        self.assertContains(response, f'href="/news/{article.id}/"')
        self.assertNotContains(response, 'href="/news/home-legacy-slug/"')

    def test_public_home_latest_articles_filter_and_order_published_items(self):
        now = timezone.now()
        self.make_article("older", "较早发布", published_to_web_at=now - timedelta(hours=2))
        self.make_article("newer", "最新发布", published_to_web_at=now)
        self.make_article(
            "draft",
            "待编辑草稿",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=now + timedelta(hours=1),
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        latest_titles = [article.effective_title for article in response.context["latest_articles"]]
        self.assertEqual(latest_titles, ["最新发布", "较早发布"])

    def test_public_home_region_tabs_filter_published_articles(self):
        now = timezone.now()
        self.make_article("jp-region", "日本新闻", published_to_web_at=now - timedelta(minutes=2))
        hk_article = self.make_article(
            "hk-region",
            "香港新闻",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            published_to_web_at=now,
        )
        self.make_article(
            "uk-draft",
            "英国草稿",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=now + timedelta(minutes=1),
        )

        aggregate = self.client.get("/")
        hk = self.client.get("/", {"region": RacingRegion.HONG_KONG})

        self.assertContains(aggregate, "综合")
        self.assertContains(aggregate, "日本")
        self.assertContains(aggregate, "中国香港")
        self.assertContains(aggregate, "英国")
        self.assertContains(aggregate, "法国")
        self.assertContains(aggregate, "美国")
        self.assertEqual([article.effective_title for article in aggregate.context["latest_articles"]], ["香港新闻", "日本新闻"])
        self.assertEqual([article.effective_title for article in hk.context["latest_articles"]], ["香港新闻"])
        self.assertEqual(hk.context["headline_article"], hk_article)
        self.assertNotContains(hk, "日本新闻")
        self.assertNotContains(hk, "英国草稿")

    def test_public_home_pagination_preserves_region_filter(self):
        now = timezone.now()
        for index in range(14):
            self.make_article(
                f"hk-page-{index}",
                f"香港分页新闻 {index}",
                racing_region=RacingRegion.HONG_KONG,
                source_language=SourceLanguage.ENGLISH,
                published_to_web_at=now - timedelta(minutes=index),
            )

        response = self.client.get("/", {"region": RacingRegion.HONG_KONG})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "?region=hong_kong&amp;page=2")

    def test_public_detail_shows_region_source_and_source_language(self):
        article = self.make_article(
            "us-detail",
            "美国详情",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            source_mode=SourceMode.LATEST,
        )

        response = self.client.get(article.public_path)

        self.assertContains(response, "美国")
        self.assertContains(response, "英文")
        self.assertContains(response, "netkeiba")

    def test_public_home_selects_recent_high_value_cover_article_as_headline(self):
        now = timezone.now()
        self.make_article(
            "new-low",
            "最新普通稿",
            published_to_web_at=now,
            score_total=20,
        )
        featured = self.make_article(
            "featured",
            "宝塚纪念重点稿",
            published_to_web_at=now - timedelta(hours=1),
            score_total=95,
            race_priority="P0",
            has_cover=True,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["headline_article"], featured)

    def test_public_home_headline_falls_back_to_latest_published_article(self):
        now = timezone.now()
        old_article = self.make_article(
            "old",
            "七天外旧稿",
            published_to_web_at=now - timedelta(days=10),
            score_total=20,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["headline_article"], old_article)

    def test_public_home_feed_articles_do_not_repeat_headline(self):
        now = timezone.now()
        headline = self.make_article(
            "featured-no-repeat",
            "重点头条",
            published_to_web_at=now,
            score_total=95,
            race_priority="P0",
            has_cover=True,
        )
        regular = self.make_article(
            "regular-no-repeat",
            "普通新闻",
            published_to_web_at=now - timedelta(minutes=5),
            score_total=20,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["headline_article"], headline)
        self.assertNotIn(headline, response.context["feed_articles"])
        self.assertIn(regular, response.context["feed_articles"])

    def test_public_home_hot_articles_prioritize_upstream_access_snapshot(self):
        now = timezone.now()
        snapshot_article = self.make_article(
            "snapshot-hot",
            "原站访问榜文章",
            published_to_web_at=now - timedelta(hours=1),
            score_total=30,
        )
        high_score_article = self.make_article(
            "score-hot",
            "高分无快照文章",
            published_to_web_at=now,
            score_total=95,
        )
        NewsSnapshot.objects.create(
            article=snapshot_article,
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            rank=1,
            comment_count=18,
            attention_count=4,
            captured_at=now,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        hot_articles = [entry["article"] for entry in response.context["hot_articles"]]
        self.assertEqual(hot_articles[0], snapshot_article)

    def test_public_home_hot_articles_fall_back_to_score_and_recency_without_snapshots(self):
        now = timezone.now()
        low_score_newer = self.make_article(
            "low-score-hot",
            "低分新稿",
            published_to_web_at=now,
            score_total=10,
        )
        high_score_older = self.make_article(
            "high-score-hot",
            "高分旧稿",
            published_to_web_at=now - timedelta(hours=3),
            score_total=85,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        hot_articles = [entry["article"] for entry in response.context["hot_articles"]]
        self.assertEqual(hot_articles[:2], [high_score_older, low_score_newer])
        self.assertTrue(all(entry["snapshot"] is None for entry in response.context["hot_articles"]))

    def test_public_home_labels_upstream_hot_signal_without_site_metric_claims(self):
        now = timezone.now()
        hot = self.make_article("label-hot", "访问榜重点稿", published_to_web_at=now)
        NewsSnapshot.objects.create(
            article=hot,
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            rank=2,
            comment_count=88,
            attention_count=66,
            captured_at=now,
        )

        response = self.client.get("/")

        self.assertContains(response, "原站热度")
        self.assertNotContains(response, "本站评论")
        self.assertNotContains(response, "本站浏览")

    def test_public_pages_use_public_stylesheet_instead_of_console_stylesheet(self):
        article = self.make_article("public-css", "公开样式测试", published_to_web_at=timezone.now())

        home = self.client.get("/")
        detail = self.client.get(article.public_path)

        for response in (home, detail):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'stable/public.css')
            self.assertNotContains(response, 'stable/console.css')

    def test_public_detail_uses_public_structure_and_effective_article_fields(self):
        article = self.make_article("detail-public", "原始标题", published_to_web_at=timezone.now())
        article.rewrite_title_zh = "改写标题"
        article.rewrite_summary_zh = "改写摘要"
        article.rewrite_body_zh = "改写正文第一段。\n改写正文第二段。"
        article.source_note = "netkeiba"
        article.save()

        response = self.client.get(article.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-public-detail')
        self.assertContains(response, "改写标题")
        self.assertContains(response, "改写摘要")
        self.assertContains(response, "改写正文第一段")
        self.assertContains(response, "netkeiba")
        self.assertContains(response, article.source_url)

    def test_public_detail_requires_web_publish_time(self):
        article = self.make_article("detail-without-web-time", "无发布时间", published_to_web_at=None)
        article.published_to_web_at = None
        article.save(update_fields=["published_to_web_at", "updated_at"])

        response = self.client.get(article.public_path)

        self.assertEqual(response.status_code, 404)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, AUTOMATION_ENABLED=True, REWRITE_PROVIDER="fallback")
class AutomationFlowTests(TestCase):
    def _translated_article(self, **overrides):
        body_ja = (
            "大阪杯G1（芝2000メートル）はクロワデュノールが1着。北村友一騎手が騎乗し、直線で抜け出した。"
            "道中は中団で脚をため、最後の直線では力強く伸びて後続を振り切った。"
            "管理する斉藤崇史調教師は状態の良さを評価し、今後の大舞台にも期待を寄せている。"
            "勝ち時計は1分57秒台で、良馬場のなか内容の濃い結果となった。"
        )
        body_zh = (
            "大阪杯G1（草地2000米）由北十字星取得第1名。北村友一骑手策骑，直线冲出。"
            "比赛中段保持在中团蓄力，进入最后直线后强势加速，最终甩开后续马群。"
            "练马师斉藤崇史评价其状态良好，也对接下来的大舞台寄予期待。"
            "胜利时间为1分57秒区间，在良好场地下是一场内容扎实的胜利。"
        )
        defaults = {
            "source_site": SourceSite.NETKEIBA,
            "source_mode": SourceMode.LATEST,
            "source_article_id": "auto-1",
            "title_ja": "大阪杯G1 クロワデュノールが優勝",
            "translated_title_zh": "大阪杯G1 北十字星夺冠",
            "title_zh": "大阪杯G1 北十字星夺冠",
            "body_ja_raw": body_ja,
            "body_ja_normalized": body_ja,
            "translated_body_zh": body_zh,
            "translated_summary_zh": "北十字星赢下大阪杯G1。",
            "summary_zh": "北十字星赢下大阪杯G1。",
            "body_zh": body_zh,
            "published_at": timezone.now(),
            "source_url": "https://example.com/auto-1",
            "workflow_status": WorkflowStatus.PENDING_EDIT,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def test_process_article_automation_marks_high_value_article_publish_ready(self):
        TermEntry.objects.create(term_type="horse", source_ja="クロワデュノール", target_zh="北十字星", priority=100)
        article = self._translated_article()

        result = process_article_automation_task.run(article.id)

        article.refresh_from_db()
        self.assertEqual(result["review_mode"], ReviewMode.AUTO)
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertEqual(article.review_mode, ReviewMode.AUTO)
        self.assertGreaterEqual(article.score_total, 75)
        self.assertFalse(article.rewrite_body_zh)
        self.assertEqual(article.base_translation_zh, article.translated_body_zh)
        self.assertEqual(article.decision_reason["gate_issue_counts"]["blocker"], 0)

    def test_takarazuka_article_uses_title_horse_and_race_grade(self):
        TermEntry.objects.create(term_type="horse", source_ja="キタサンブラック", target_zh="北部玄驹", priority=100)
        TermEntry.objects.create(term_type="race", source_ja="宝塚記念", target_zh="宝塚纪念", race_grade="G1", priority=90)
        body = (
            "シュガークンが宝塚記念・GIで一発を狙う。兄キタサンブラックの悔しさを晴らす舞台だ。"
            "ドゥラメンテ、シュガーハート、サクラバクシンオーなど血統面の話題も多い。"
            "最終追い切りでは軽快な動きを見せ、陣営は状態の良さを強調した。"
            "今年の上半期を締めくくる大一番としてファンの注目も集まっている。"
        )
        article = self._translated_article(
            source_article_id="takarazuka-3961-shape",
            title_ja="【宝塚記念】兄キタサンブラックの悔しさを晴らすか シュガークンが一発狙う",
            translated_title_zh="【宝塚纪念】弟弟シュガークン能否为兄长北部玄驹雪耻",
            title_zh="【宝塚纪念】弟弟シュガークン能否为兄长北部玄驹雪耻",
            body_ja_raw=body,
            body_ja_normalized=body,
            translated_body_zh="シュガークン将挑战宝塚纪念，北部玄驹相关背景受到关注。" * 20,
            body_zh="シュガークン将挑战宝塚纪念，北部玄驹相关背景受到关注。" * 20,
        )

        decision = score_article_for_automation(article)

        self.assertGreaterEqual(decision.score_total, 75)
        self.assertEqual(decision.review_mode, ReviewMode.AUTO)
        self.assertEqual(decision.decision_reason["signals"]["race_grade"], "G1")
        self.assertEqual(decision.decision_reason["signals"]["race_priority"], "P0")
        self.assertTrue(decision.decision_reason["signals"]["p0_horse_hits"])

    def test_automation_scoring_uses_terms_for_article_source_language_only(self):
        from stable.services.automation import race_priority

        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="International Star",
            target_zh="国际之星",
            priority=100,
        )
        TermEntry.objects.create(
            term_type="race",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Derby",
            target_zh="德比",
            race_grade="G1",
            priority=100,
        )
        japanese_article = self._translated_article(
            source_article_id="ja-language-term-isolation",
            title_ja="Derby preview for International Star",
            translated_title_zh="Derby preview for International Star",
            body_ja_raw="Derby preview for International Star.",
            body_ja_normalized="Derby preview for International Star.",
            translated_body_zh="Derby preview for International Star.",
        )
        english_article = self._translated_article(
            source_article_id="en-language-term-isolation",
            source_language=SourceLanguage.ENGLISH,
            title_ja="Derby preview for International Star",
            translated_title_zh="Derby preview for International Star",
            body_ja_raw="Derby preview for International Star.",
            body_ja_normalized="Derby preview for International Star.",
            translated_body_zh="Derby preview for International Star.",
        )

        japanese_decision = score_article_for_automation(japanese_article)
        english_decision = score_article_for_automation(english_article)

        self.assertEqual(race_priority(japanese_article)["priority"], "P2")
        self.assertEqual(race_priority(english_article)["priority"], "P0")
        self.assertEqual(japanese_decision.decision_reason["signals"]["p0_horse_hits"], [])
        self.assertTrue(english_decision.decision_reason["signals"]["p0_horse_hits"])

    def test_automation_p0_horse_hits_match_english_terms_case_insensitively(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-uppercase-p0-horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="EQUINOX returns in top form",
            body_ja_raw="EQUINOX returns in a G1 preview. The champion will feature at Ascot.",
            body_ja_normalized="EQUINOX returns in a G1 preview. The champion will feature at Ascot.",
            translated_title_zh="春秋分回归",
            title_zh="春秋分回归",
            translated_body_zh="春秋分将在一级赛前瞻中回归。" * 12,
            body_zh="春秋分将在一级赛前瞻中回归。" * 12,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.decision_reason["signals"]["p0_horse_hits"][0]["target_zh"], "春秋分")

    def test_english_automation_scoring_uses_english_racing_keywords(self):
        article = self._translated_article(
            source_article_id="english-keyword-score",
            source_language=SourceLanguage.ENGLISH,
            title_ja="Breeders' Cup Classic preview: entries and draw confirmed",
            translated_title_zh="育马者杯经典赛前瞻",
            body_ja_raw=(
                "Breeders' Cup Classic preview with entries, draw and barrier updates. "
                "Connections confirmed one runner was withdrawn after an injury. "
            )
            * 8,
            body_ja_normalized=(
                "Breeders' Cup Classic preview with entries, draw and barrier updates. "
                "Connections confirmed one runner was withdrawn after an injury. "
            )
            * 8,
            translated_body_zh="育马者杯经典赛前瞻，报名、排位和伤退消息受到关注。" * 20,
            body_zh="育马者杯经典赛前瞻，报名、排位和伤退消息受到关注。" * 20,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.content_category, ContentCategory.PRE_RACE)
        self.assertEqual(decision.decision_reason["signals"]["race_priority"], "P0")
        self.assertIn("withdrawn", decision.decision_reason["signals"]["high_focus_hits"])
        self.assertIn("entries", decision.decision_reason["signals"]["high_focus_hits"])

    def test_high_value_source_overrides_score_stage_only(self):
        article = self._translated_article(
            source_article_id="access-source-1",
            source_mode=SourceMode.ACCESS,
            title_ja="アクセスランキングの一般ニュース",
            body_ja_raw="レース前の短い展望記事です。" * 20,
            body_ja_normalized="レース前の短い展望記事です。" * 20,
            translated_body_zh="访问量榜新闻的中文正文。" * 20,
            body_zh="访问量榜新闻的中文正文。" * 20,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.review_mode, ReviewMode.AUTO)
        self.assertGreaterEqual(decision.score_total, 75)
        self.assertTrue(decision.decision_reason["signals"]["high_value_source"])
        self.assertTrue(decision.decision_reason["scores"]["high_value_source_override"])

    def test_non_horse_fixed_phrases_are_not_unknown_horse_names(self):
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="タイトル",
            target_zh="头衔",
            notes="non_horse_common_word: 测试普通词",
        )
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="オッズ",
            target_zh="赔率",
            notes="non_horse_common_word: 测试普通词",
        )

        names = extract_unknown_horse_names(
            "【函館記念】マジックサンズがタイトル狙う",
            "3番人気マジックサンズのオッズが注目され、アラタは2つ目のタイトルを狙う。",
        )

        self.assertIn("マジックサンズ", names)
        self.assertNotIn("タイトル", names)
        self.assertNotIn("オッズ", names)

    def test_warning_issues_do_not_block_publish_ready(self):
        article = self._translated_article(
            source_article_id="warning-not-blocking",
            title_ja="【函館記念】マジックサンズがタイトルを狙う",
            translated_title_zh="函馆纪念热门马冲击头衔",
            title_zh="函馆纪念热门马冲击头衔",
            body_ja_raw="マジックサンズは函館記念で24日の追い切り後に2000メートルへ向かう。" * 8,
            body_ja_normalized="マジックサンズは函館記念で24日の追い切り後に2000メートルへ向かう。" * 8,
            translated_body_zh="这匹热门马将向函馆纪念发起挑战，阵营称状态良好。" * 8,
            body_zh="这匹热门马将向函馆纪念发起挑战，阵营称状态良好。" * 8,
        )

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)

        article.refresh_from_db()
        self.assertTrue(outcome.passed)
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertTrue(any(issue["code"] == "unknown_horse_not_preserved" for issue in article.gate_issues))
        self.assertTrue(any(issue["severity"] == "warning" for issue in article.gate_issues))

    def test_external_horse_missing_warns_without_known_term_blocker_and_keeps_all_ids(self):
        for horse_id in ["1001", "1002"]:
            ExternalHorseAlias.objects.create(
                source="netkeiba",
                external_horse_id=horse_id,
                name_ja="マヤノライジン",
                normalized_name="マヤノライジン",
                alias_source="test",
            )
        article = self._translated_article(
            source_article_id="external-horse-warning",
            title_ja="マヤノライジンが出走",
            body_ja_raw="マヤノライジンは重賞へ向かう。" * 10,
            body_ja_normalized="マヤノライジンは重賞へ向かう。" * 10,
            translated_title_zh="摩耶雷神出战",
            title_zh="摩耶雷神出战",
            translated_body_zh="这匹马将向重赏进发。" * 10,
            body_zh="这匹马将向重赏进发。" * 10,
        )

        outcome = validate_rewrite(article)

        external_issue = next(issue for issue in outcome.issues if issue["code"] == "external_horse_not_preserved")
        self.assertTrue(outcome.passed)
        self.assertEqual(external_issue["severity"], "warning")
        self.assertCountEqual(external_issue["payload"]["names"][0]["external_horse_ids"], ["1001", "1002"])
        self.assertFalse(any(issue["code"] in {"core_term_missing", "background_term_missing"} for issue in outcome.issues))

    def test_validation_uses_matched_external_horse_spelling_for_english_article(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            alias_source="test",
        )
        article = self._translated_article(
            source_article_id="english-external-horse-preserved",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            title_ja="LUCKY STAR wins at Sha Tin",
            body_ja_raw="LUCKY STAR was too strong in the closing stages. " * 8,
            body_ja_normalized="LUCKY STAR was too strong in the closing stages. " * 8,
            translated_title_zh="LUCKY STAR 在沙田取胜",
            title_zh="LUCKY STAR 在沙田取胜",
            translated_body_zh="LUCKY STAR 在末段表现强劲。" * 12,
            body_zh="LUCKY STAR 在末段表现强劲。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed)
        self.assertEqual(outcome.details["external_horse_names"], ["LUCKY STAR"])
        self.assertFalse(any(issue["code"] == "external_horse_not_preserved" for issue in outcome.issues))

    def test_validation_preserve_limit_is_not_consumed_by_known_horse_terms(self):
        known_names = [
            "アカホース",
            "アオホース",
            "クロホース",
            "シロホース",
            "キンホース",
            "ギンホース",
            "ミドリホース",
            "サクラホース",
            "モモホース",
            "ユキホース",
            "ソラホース",
            "ナミホース",
        ]
        for index, name in enumerate(known_names):
            TermEntry.objects.create(term_type="horse", source_ja=name, target_zh=f"译名{index}", priority=100)
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="4001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        source_body = " ".join(known_names) + " マヤノライジンは重賞へ向かう。" + "調整は順調。" * 12
        translated_known = " ".join(f"译名{index}" for index in range(len(known_names)))
        article = self._translated_article(
            source_article_id="external-horse-after-known-terms",
            title_ja="重賞展望",
            body_ja_raw=source_body,
            body_ja_normalized=source_body,
            translated_title_zh="重赏展望",
            title_zh="重赏展望",
            translated_body_zh=translated_known + " 这匹马将向重赏进发。" * 10,
            body_zh=translated_known + " 这匹马将向重赏进发。" * 10,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(any(issue["code"] == "external_horse_not_preserved" for issue in outcome.issues))

    def test_core_term_missing_blocks_and_background_term_missing_warns(self):
        TermEntry.objects.create(term_type="race", source_ja="有馬記念", target_zh="有马纪念", priority=90)
        core_article = self._translated_article(
            source_article_id="core-term-missing",
            title_ja="有馬記念の登録馬が発表",
            translated_title_zh="重要赛事报名马公布",
            title_zh="重要赛事报名马公布",
            translated_body_zh="重要赛事报名马公布，阵容受到关注。" * 10,
            body_zh="重要赛事报名马公布，阵容受到关注。" * 10,
        )

        core_outcome = validate_rewrite(core_article)
        apply_validation_outcome(core_article, core_outcome)

        core_article.refresh_from_db()
        self.assertFalse(core_outcome.passed)
        self.assertEqual(core_article.workflow_status, WorkflowStatus.PENDING_REVIEW)
        self.assertTrue(any(issue["code"] == "core_term_missing" for issue in core_article.gate_issues))

        TermEntry.objects.create(term_type="race", source_ja="金鯱賞", target_zh="金鯱赏", priority=10)
        background_body = "前半は陣営の調整過程を詳しく紹介する。" * 40 + "金鯱賞での好走歴にも触れた。"
        background_article = self._translated_article(
            source_article_id="background-term-warning",
            title_ja="夏競馬へ向けた調整進む",
            body_ja_raw=background_body,
            body_ja_normalized=background_body,
            translated_body_zh="前半介绍阵营调整过程，最后概括过往表现。" * 12,
            body_zh="前半介绍阵营调整过程，最后概括过往表现。" * 12,
        )

        background_outcome = validate_rewrite(background_article)
        apply_validation_outcome(background_article, background_outcome)

        background_article.refresh_from_db()
        self.assertTrue(background_outcome.passed)
        self.assertEqual(background_article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertTrue(any(issue["code"] == "background_term_missing" for issue in background_article.gate_issues))

    def test_english_core_term_missing_detects_source_case_insensitively(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=90,
        )
        article = self._translated_article(
            source_article_id="english-core-term-uppercase-missing",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="EQUINOX returns in feature",
            body_ja_raw="EQUINOX returns in feature company at Ascot.",
            body_ja_normalized="EQUINOX returns in feature company at Ascot.",
            translated_title_zh="名马回归",
            title_zh="名马回归",
            translated_body_zh="这匹名马将在阿斯科特回归。" * 12,
            body_zh="这匹名马将在阿斯科特回归。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertFalse(outcome.passed)
        self.assertTrue(any(issue["code"] == "core_term_missing" for issue in outcome.issues))

    def test_duplicate_detection_blocks_highly_similar_article(self):
        published = self._translated_article(
            source_article_id="published-duplicate-source",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        article = self._translated_article(source_article_id="duplicate-candidate")

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)

        article.refresh_from_db()
        self.assertFalse(outcome.passed)
        self.assertEqual(article.workflow_status, WorkflowStatus.DUPLICATE)
        self.assertEqual(article.duplicate_of, published)
        self.assertTrue(any(issue["code"] == "duplicate_content" for issue in article.gate_issues))

    def test_passing_validation_clears_stale_duplicate_state_and_can_publish(self):
        stale_duplicate = self._translated_article(source_article_id="stale-duplicate-reference")
        article = self._translated_article(source_article_id="stale-duplicate-now-clean")
        article.workflow_status = WorkflowStatus.DUPLICATE
        article.duplicate_of = stale_duplicate
        article.duplicate_score = 0.91
        article.duplicate_reason = "旧重复检测结果"
        article.save(
            update_fields=[
                "workflow_status",
                "duplicate_of",
                "duplicate_score",
                "duplicate_reason",
                "updated_at",
            ]
        )

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)
        publish_result = auto_publish_batch_task.run(limit=1)

        article.refresh_from_db()
        self.assertTrue(outcome.passed)
        self.assertEqual(article.duplicate_of, None)
        self.assertEqual(article.duplicate_score, None)
        self.assertEqual(article.duplicate_reason, "")
        self.assertEqual(publish_result["published_count"], 1)
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.automation_status, AutomationStatus.AUTO_PUBLISHED)

    def test_score_short_body_is_ignored(self):
        article = self._translated_article(
            source_article_id="short-1",
            title_ja="短い記事",
            body_ja_raw="短文",
            body_ja_normalized="短文",
            translated_body_zh="短文",
            body_zh="短文",
        )

        score_article_task.run(article.id)

        article.refresh_from_db()
        self.assertEqual(article.review_mode, ReviewMode.IGNORED)
        self.assertEqual(article.workflow_status, WorkflowStatus.IGNORED)
        self.assertEqual(article.automation_status, AutomationStatus.IGNORED)

    def test_auto_publish_batch_only_publishes_ready_articles(self):
        TermEntry.objects.create(term_type="horse", source_ja="クロワデュノール", target_zh="北十字星", priority=100)
        article = self._translated_article()
        process_article_automation_task.run(article.id)

        result = auto_publish_batch_task.run(limit=3)

        article.refresh_from_db()
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.automation_status, AutomationStatus.AUTO_PUBLISHED)
        self.assertEqual(article.published_by_mode, "auto")
        self.assertIsNotNone(article.auto_publish_at)

    @override_settings(
        AUTO_PUBLISH_BATCH_LIMIT=4,
        AUTO_PUBLISH_PEAK_BATCH_LIMIT=10,
        AUTO_PUBLISH_PEAK_DAY_OF_WEEK=6,
        AUTO_PUBLISH_PEAK_START_HOUR=13,
        AUTO_PUBLISH_PEAK_END_HOUR=16,
    )
    def test_auto_publish_limit_uses_sunday_peak_window(self):
        sunday_peak = datetime(2026, 5, 17, 5, 30, tzinfo=dt_timezone.utc)
        sunday_window_end = datetime(2026, 5, 17, 8, 0, tzinfo=dt_timezone.utc)
        monday_same_hour = datetime(2026, 5, 18, 5, 30, tzinfo=dt_timezone.utc)

        self.assertEqual(_resolve_auto_publish_batch_limit(now=sunday_peak), 10)
        self.assertEqual(_resolve_auto_publish_batch_limit(now=sunday_window_end), 4)
        self.assertEqual(_resolve_auto_publish_batch_limit(now=monday_same_hour), 4)
        self.assertEqual(_resolve_auto_publish_batch_limit(limit=2, now=sunday_peak), 2)
        self.assertEqual(_resolve_auto_publish_batch_limit(limit=0, now=sunday_peak), 0)

    def test_public_page_prefers_rewrite_when_not_manually_edited(self):
        article = self._translated_article(
            source_article_id="rewrite-public",
            rewrite_title_zh="改写后的中文标题",
            rewrite_summary_zh="改写后的摘要",
            rewrite_body_zh="改写后的正文内容。",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        response = self.client.get(article.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "改写后的中文标题")
        self.assertContains(response, "改写后的正文内容。")

    def test_notification_without_email_config_is_logged_as_skipped(self):
        send_notification_task.run("rewrite_failed", {"article_id": 123, "title": "测试稿"})

        log = NotificationLog.objects.get(channel="email")
        self.assertEqual(log.status, "skipped")
        self.assertEqual(log.channel, "email")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        AUTOMATION_WARNING_EMAIL_ENABLED=True,
        AUTOMATION_WARNING_NOTIFY_EMAILS=["754652181@qq.com"],
        HIGH_VALUE_SOURCE_RULES=["netkeiba:access"],
    )
    def test_high_value_warning_sends_deduplicated_email(self):
        article = self._translated_article(
            source_article_id="warning-email",
            source_mode=SourceMode.ACCESS,
            title_ja="【函館記念】マジックサンズが挑む",
            translated_title_zh="函馆纪念热门马挑战",
            title_zh="函馆纪念热门马挑战",
            body_ja_raw="マジックサンズは函館記念で上位を狙う。" * 10,
            body_ja_normalized="マジックサンズは函館記念で上位を狙う。" * 10,
            translated_body_zh="热门马将挑战函馆纪念，阵营状态良好。" * 10,
            body_zh="热门马将挑战函馆纪念，阵营状态良好。" * 10,
        )

        process_article_automation_task.run(article.id)
        article.refresh_from_db()
        send_high_value_warning_notification(article)

        sent = NotificationLog.objects.filter(type="high_value_warning", status="sent").count()
        skipped = NotificationLog.objects.filter(type="high_value_warning", status="skipped").count()
        self.assertEqual(sent, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)

    @override_settings(AUTOMATION_WARNING_EMAIL_ENABLED=True, AUTOMATION_WARNING_NOTIFY_EMAILS=[])
    def test_high_value_warning_missing_recipient_is_skipped(self):
        article = self._translated_article(source_article_id="warning-email-skipped", score_total=100)
        article.gate_issues = [
            {
                "code": "numbers_omitted",
                "severity": "warning",
                "message": "发布稿省略较多原文数字",
                "route": "auto",
                "payload": {},
            }
        ]
        article.save(update_fields=["gate_issues", "score_total", "updated_at"])

        logs = send_high_value_warning_notification(article)

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, "skipped")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TermConsoleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser("admin", "admin@example.com", "admin123456")
        self.client.login(username="admin", password="admin123456")
        self.term = TermEntry.objects.create(
            term_type="horse",
            source_ja="イクイノックス",
            target_zh="春秋分",
            aliases_ja=["イクイノ"],
            aliases_zh=["春秋分马"],
            priority=100,
            is_active=True,
        )

    def test_term_list_page_available(self):
        response = self.client.get(reverse("console-term-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "术语映射")
        self.assertContains(response, "イクイノックス")

    def test_term_list_can_search_japanese_and_chinese_aliases(self):
        response = self.client.get(reverse("console-term-list"), {"q": "イクイノ"})
        self.assertContains(response, "イクイノックス")
        response = self.client.get(reverse("console-term-list"), {"q": "春秋分马"})
        self.assertContains(response, "イクイノックス")

    def test_term_list_pagination_preserves_source_language_filter(self):
        for index in range(21):
            TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.ENGLISH,
                source_ja=f"English Horse {index:02d}",
                target_zh=f"英文马{index:02d}",
            )

        response = self.client.get(reverse("console-term-list"), {"source_language": SourceLanguage.ENGLISH})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "source_language=en&amp;page=2")

    def test_term_create_page_can_create_entry(self):
        response = self.client.post(
            reverse("console-term-create"),
            {
                "term_type": "race",
                "source_ja": "大阪杯",
                "target_zh": "大阪杯",
                "aliases_ja_text": "大阪杯GI\n大阪杯ＧＩ",
                "aliases_zh_text": "大阪杯一级赛",
                "priority": "50",
                "is_active": "on",
                "notes": "重要赛事",
                "intent": "save",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TermEntry.objects.filter(term_type="race", source_ja="大阪杯").exists())

    def test_term_create_duplicate_rejected(self):
        response = self.client.post(
            reverse("console-term-create"),
            {
                "term_type": "horse",
                "source_ja": "イクイノックス",
                "target_zh": "春秋分",
                "aliases_ja_text": "",
                "aliases_zh_text": "",
                "priority": "10",
                "is_active": "on",
                "notes": "",
                "intent": "save",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已有术语 ID")

    def test_english_term_create_duplicate_rejected_case_insensitively(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
        )

        response = self.client.post(
            reverse("console-term-create"),
            {
                "term_type": "horse",
                "source_language": SourceLanguage.ENGLISH,
                "source_ja": "EQUINOX",
                "target_zh": "另一个春秋分",
                "aliases_ja_text": "",
                "aliases_zh_text": "",
                "priority": "10",
                "is_active": "on",
                "notes": "",
                "intent": "save",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已有术语 ID")
        self.assertEqual(
            TermEntry.objects.filter(term_type="horse", source_language=SourceLanguage.ENGLISH, source_ja__iexact="equinox").count(),
            1,
        )

    def test_term_toggle_active(self):
        TermAlias.objects.create(
            term=self.term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )
        response = self.client.post(reverse("console-term-toggle", args=[self.term.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.term.refresh_from_db()
        self.assertFalse(self.term.is_active)
        self.assertFalse(TermAlias.objects.get(term=self.term, text="Equinox").is_active)

    def test_preview_term_import_service(self):
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "horse,グランアレグリア,放声欢呼,Gran Alegria|グラン,放声欢呼,100,true,,\n"
            "race,大阪杯,大阪杯,,大阪杯一级赛,20,true,重要赛事,G1\n"
        )
        preview = preview_term_import(csv_text=csv_text, import_mode="create")
        self.assertEqual(preview["summary"]["total"], 2)
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertTrue(preview["can_commit"])
        self.assertEqual(preview["rows"][1]["payload"]["race_grade"], "G1")

    def test_preview_term_import_rejects_invalid_race_grade(self):
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "race,謎の特別,谜之特别,,,,true,,P9\n"
        )
        preview = preview_term_import(csv_text=csv_text, import_mode="create")
        self.assertEqual(preview["summary"]["error_count"], 1)
        self.assertIn("比赛等级", " ".join(preview["rows"][0]["errors"]))

    def test_preview_term_import_service_decodes_gb18030_file(self):
        TermEntry.objects.all().delete()
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes\n"
            "horse,\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9,\u6625\u79cb\u5206,Equinox|\u30a4\u30af\u30a4,\u6625\u79cb\u5206,100,true,\n"
        )
        upload = SimpleUploadedFile("terms_gb18030.csv", csv_text.encode("gb18030"), content_type="text/csv")
        preview = preview_term_import(csv_file=upload, import_mode="create")
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertEqual(preview["detected_encoding"], "gb18030")
        self.assertEqual(preview["rows"][0]["payload"]["source_ja"], "\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9")
        self.assertEqual(preview["rows"][0]["payload"]["target_zh"], "\u6625\u79cb\u5206")

    def test_preview_term_import_service_decodes_cp932_file(self):
        TermEntry.objects.all().delete()
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes\n"
            "horse,\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9,\u6625\u79cb\u5206,Equinox|\u30a4\u30af\u30a4,\u6625\u79cb\u5206,100,true,\n"
        )
        upload = SimpleUploadedFile("terms_cp932.csv", csv_text.encode("cp932"), content_type="text/csv")
        preview = preview_term_import(csv_file=upload, import_mode="create")
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertIn(preview["detected_encoding"], {"cp932", "shift_jis", "gb18030"})
        self.assertEqual(preview["rows"][0]["payload"]["source_ja"], "\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9")
        self.assertEqual(preview["rows"][0]["payload"]["target_zh"], "\u6625\u79cb\u5206")

    def test_term_import_preview_and_commit(self):
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "horse,グランアレグリア,放声欢呼,Gran Alegria|グラン,放声欢呼,100,true,,\n"
            "race,大阪杯,大阪杯,,大阪杯一级赛,20,true,重要赛事,G1\n"
        )
        preview_response = self.client.post(
            reverse("console-term-import"),
            {"import_mode": "create", "csv_text": csv_text, "action": "preview"},
            follow=True,
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "预检结果")
        commit_response = self.client.post(
            reverse("console-term-import"),
            {"action": "commit"},
            follow=True,
        )
        self.assertEqual(commit_response.status_code, 200)
        self.assertTrue(TermEntry.objects.filter(source_ja="グランアレグリア").exists())
        self.assertEqual(TermEntry.objects.get(source_ja="大阪杯").race_grade, "G1")

    def test_term_import_upsert_alias_match_preserves_concept_primary_source(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            aliases_ja=["イクイ"],
            priority=100,
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        preview_rows = [
            {
                "line_no": 1,
                "status": "update",
                "payload": {
                    "term_type": "horse",
                    "source_language": SourceLanguage.ENGLISH,
                    "source_ja": "Equinox",
                    "target_zh": "春秋分",
                    "aliases_ja": ["EQUINOX"],
                    "aliases_zh": ["春秋分马"],
                    "race_grade": "",
                    "priority": 80,
                    "is_active": True,
                    "notes": "英文别名",
                },
            }
        ]

        result = commit_term_import(preview_rows, import_mode="upsert")

        self.assertEqual(result["update_count"], 1)
        term.refresh_from_db()
        self.assertEqual(term.source_language, SourceLanguage.JAPANESE)
        self.assertEqual(term.source_ja, "イクイノックス")
        self.assertEqual(term.aliases_ja, ["イクイ"])
        self.assertEqual(term.target_zh, "春秋分")
        self.assertEqual(term.aliases_zh, ["春秋分马"])
        self.assertEqual(term.priority, 80)
        self.assertTrue(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="Equinox",
                alias_type=TermAliasType.PRIMARY,
            ).exists()
        )
        self.assertFalse(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="EQUINOX",
                alias_type=TermAliasType.ALIAS,
            ).exists()
        )

    def test_term_import_upsert_same_language_case_variant_updates_primary_source(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="旧译名",
            aliases_ja=["Old Alias"],
            priority=10,
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Old Alias",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )
        preview_rows = [
            {
                "line_no": 1,
                "status": "update",
                "payload": {
                    "term_type": "horse",
                    "source_language": SourceLanguage.ENGLISH,
                    "source_ja": "EQUINOX",
                    "target_zh": "春秋分",
                    "aliases_ja": ["Fresh Alias", "equinox"],
                    "aliases_zh": ["春秋分马"],
                    "race_grade": "",
                    "priority": 90,
                    "is_active": True,
                    "notes": "英文主原文大小写更新",
                },
            }
        ]

        result = commit_term_import(preview_rows, import_mode="upsert")

        self.assertEqual(result["update_count"], 1)
        term.refresh_from_db()
        self.assertEqual(term.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(term.source_ja, "EQUINOX")
        self.assertEqual(term.target_zh, "春秋分")
        self.assertEqual(term.aliases_ja, ["Fresh Alias", "equinox"])
        self.assertEqual(term.aliases_zh, ["春秋分马"])
        self.assertEqual(term.priority, 90)
        self.assertEqual(term.notes, "英文主原文大小写更新")
        self.assertTrue(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="EQUINOX",
                alias_type=TermAliasType.PRIMARY,
            ).exists()
        )
        self.assertTrue(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="Fresh Alias",
                alias_type=TermAliasType.ALIAS,
            ).exists()
        )
        self.assertFalse(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="Equinox",
            ).exists()
        )
        self.assertFalse(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="equinox",
            ).exists()
        )
        self.assertEqual(TermAlias.objects.filter(term=term, source_language=SourceLanguage.ENGLISH).count(), 2)

    def test_term_import_upsert_rejects_alias_conflict_with_other_term(self):
        existing = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            is_active=True,
        )
        TermAlias.objects.create(
            term=existing,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        csv_text = (
            "term_type,source_language,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "horse,en,Different Horse,另一匹马,EQUINOX,,10,true,,\n"
        )

        preview = preview_term_import(csv_text=csv_text, import_mode="upsert")

        self.assertEqual(preview["summary"]["error_count"], 1)
        self.assertFalse(preview["can_commit"])
        self.assertIn(f"术语 ID：{existing.pk}", " ".join(preview["rows"][0]["errors"]))
        self.assertFalse(TermEntry.objects.filter(source_ja="Different Horse").exists())

    def test_term_import_commit_rechecks_alias_conflict_with_other_term(self):
        existing = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            is_active=True,
        )
        TermAlias.objects.create(
            term=existing,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        preview_rows = [
            {
                "line_no": 2,
                "status": "create",
                "payload": {
                    "term_type": "horse",
                    "source_language": SourceLanguage.ENGLISH,
                    "source_ja": "Different Horse",
                    "target_zh": "另一匹马",
                    "aliases_ja": ["EQUINOX"],
                    "aliases_zh": [],
                    "race_grade": "",
                    "priority": 10,
                    "is_active": True,
                    "notes": "",
                },
            }
        ]

        result = commit_term_import(preview_rows, import_mode="upsert")

        self.assertEqual(result["skipped_count"], 1)
        self.assertIn(f"术语 ID：{existing.pk}", " ".join(result["failed_rows"][0]["errors"]))
        self.assertFalse(TermEntry.objects.filter(source_ja="Different Horse").exists())

    def test_import_terms_management_command_supports_dry_run(self):
        out = StringIO()
        call_command("import_terms", "--dry-run", stdout=out)
        self.assertIn("预检", out.getvalue())
        self.assertFalse(TermEntry.objects.filter(source_ja="キタサンブラック").exists())

    def test_term_api_create_and_toggle(self):
        create_response = self.client.post(
            reverse("api-term-create"),
            data='{"term_type":"org","source_language":"en","source_ja":"JRA","target_zh":"日本中央竞马会","aliases_ja":["jra","Japan Racing Association"],"aliases_zh":["JRA"],"priority":5,"is_active":true,"notes":""}',
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 200)
        payload = create_response.json()
        term_id = payload["term"]["id"]
        self.assertEqual(payload["term"]["source_language"], SourceLanguage.ENGLISH)
        self.assertTrue(
            TermAlias.objects.filter(
                term_id=term_id,
                source_language=SourceLanguage.ENGLISH,
                text="JRA",
                alias_type=TermAliasType.PRIMARY,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            TermAlias.objects.filter(
                term_id=term_id,
                source_language=SourceLanguage.ENGLISH,
                text="Japan Racing Association",
                alias_type=TermAliasType.ALIAS,
                is_active=True,
            ).exists()
        )
        self.assertFalse(TermAlias.objects.filter(term_id=term_id, text="jra").exists())
        toggle_response = self.client.post(reverse("api-term-toggle-active", args=[term_id]))
        self.assertEqual(toggle_response.status_code, 200)
        self.assertFalse(TermEntry.objects.get(pk=term_id).is_active)
        self.assertFalse(TermAlias.objects.filter(term_id=term_id, is_active=True).exists())

    def test_term_api_update_syncs_source_aliases_case_insensitively(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            aliases_ja=["Old Alias"],
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Old Alias",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )

        response = self.client.post(
            reverse("api-term-update", args=[term.id]),
            data='{"term_type":"horse","source_language":"en","source_ja":"EQUINOX","target_zh":"春秋分","aliases_ja":["equinox","Fresh Alias"],"aliases_zh":[],"priority":5,"is_active":true,"notes":""}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        term.refresh_from_db()
        self.assertEqual(term.aliases_ja, ["Fresh Alias"])
        self.assertTrue(TermAlias.objects.filter(term=term, text="EQUINOX", alias_type=TermAliasType.PRIMARY).exists())
        self.assertTrue(TermAlias.objects.filter(term=term, text="Fresh Alias", alias_type=TermAliasType.ALIAS).exists())
        self.assertFalse(TermAlias.objects.filter(term=term, text="Old Alias").exists())


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TranslationWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser("admin", "admin@example.com", "admin123456")
        self.client.login(username="admin", password="admin123456")
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="translation-1",
            title_ja="原文标题",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            published_at=timezone.now(),
            source_url="https://example.com/translation-1",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

    def test_translate_task_updates_status_and_preserves_manual_fields(self):
        self.article.title_zh = "人工标题"
        self.article.mark_manual_edits(["title_zh"])
        self.article.save()

        fake_result = type(
            "Result",
            (),
            {
                "title_zh": "机器标题",
                "body_zh": "机器正文",
                "push_summary_zh": "机器摘要",
                "metadata": {"provider": "openai-compatible", "model": "gpt-4.1-mini"},
            },
        )()

        with patch("stable.tasks.translate_article", return_value=fake_result):
            translate_article_task.run(self.article.id)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(self.article.translation_model, "gpt-4.1-mini")
        self.assertEqual(self.article.translation_provider, "openai-compatible")
        self.assertEqual(self.article.translated_title_zh, "机器标题")
        self.assertEqual(self.article.body_zh, "机器正文")
        self.assertEqual(self.article.summary_zh, "机器摘要")
        self.assertEqual(self.article.push_summary_zh, "机器摘要")
        self.assertEqual(self.article.title_zh, "人工标题")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)

    def test_translate_task_marks_failure(self):
        with patch("stable.tasks.translate_article", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                translate_article_task.run(self.article.id)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.FAILED)
        self.assertIn("boom", self.article.translation_error_message)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.TRANSLATION_FAILED)

    def test_translation_status_api_exposes_latest_state(self):
        self.article.translation_status = ArticleTranslationStatus.FAILED
        self.article.translation_error_message = "bad gateway"
        self.article.translation_model = "gpt-4.1-mini"
        self.article.save()

        response = self.client.get(reverse("api-article-translation-status", args=[self.article.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["translation_status"], ArticleTranslationStatus.FAILED)
        self.assertEqual(payload["translation_model"], "gpt-4.1-mini")
        self.assertEqual(payload["translation_error_message"], "bad gateway")

    def test_batch_translate_task_processes_pending_articles(self):
        second_article = NewsArticle.objects.create(
            source_site=SourceSite.JRA,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="translation-2",
            title_ja="第二条原文",
            body_ja_raw="第二条正文",
            body_ja_normalized="第二条正文",
            published_at=timezone.now(),
            source_url="https://example.com/translation-2",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        fake_result = type(
            "Result",
            (),
            {
                "title_zh": "批量标题",
                "body_zh": "批量正文",
                "push_summary_zh": "批量摘要",
                "metadata": {"provider": "openai-compatible", "model": "gpt-4.1-mini"},
            },
        )()

        with patch("stable.tasks.translate_article", return_value=fake_result):
            result = batch_translate_articles_task.run(limit=10)

        self.article.refresh_from_db()
        second_article.refresh_from_db()
        self.assertEqual(result["translated_count"], 2)
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(second_article.translation_status, ArticleTranslationStatus.TRANSLATED)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=2)
    def test_provider_retries_when_translation_looks_incomplete(self):
        self.article.body_ja_raw = (
            "樱花赏将在阪神赛马场举行。"
            + "前情介绍。" * 40
            + "\n■第五名 2022年 星映天下。"
            + "\n■第四名 2019年 放声欢呼。"
            + "\n■第三名 2024年 橡木城。"
            + "\n■第二名 2023年 自由岛。"
            + "\n■第一名 2021年 纯净之辉。"
        )
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")

        def fake_response(payload):
            usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 123, "prompt_tokens": 456}})()
            choice = type(
                "Choice",
                (),
                {
                    "message": type("Message", (), {"content": __import__("json").dumps(payload, ensure_ascii=False)})(),
                    "finish_reason": "stop",
                },
            )()
            return type("Response", (), {"choices": [choice], "usage": usage})()

        incomplete = fake_response(
            {
                "title_zh": "樱花赏历届冠军用时排行",
                "body_zh": (
                    "樱花赏将在阪神赛马场举行，本文回顾历届最快夺冠时间。"
                    "\n■第五名 2022年 星映天下。"
                    "\n■第四名 2019年 放声欢呼。"
                    "\n■第三名 2024年 橡木城。"
                    "\n■第二名 2023年 自由岛。"
                    "\n■第一名 2021年 纯净之辉"
                ),
                "push_summary_zh": "樱花赏速度榜回顾。",
            }
        )
        complete = fake_response(
            {
                "title_zh": "樱花赏历届冠军用时排行",
                "body_zh": (
                    "樱花赏将在阪神赛马场举行，本文回顾历届最快夺冠时间。"
                    "\n■第五名 2022年 星映天下。"
                    "\n■第四名 2019年 放声欢呼。"
                    "\n■第三名 2024年 橡木城。"
                    "\n■第二名 2023年 自由岛。"
                    "\n■第一名 2021年 纯净之辉。"
                ),
                "push_summary_zh": "樱花赏速度榜回顾。",
            }
        )

        with patch.object(provider, "_request_completion", side_effect=[incomplete, complete]) as mocked:
            result = provider.translate(self.article)

        self.assertEqual(mocked.call_count, 2)
        self.assertTrue(result.body_zh.endswith("。"))
        self.assertEqual(result.metadata["attempt"], 2)
        self.assertEqual(result.metadata["finish_reason"], "stop")

    def test_translation_service_persists_failed_metadata(self):
        self.article.body_ja_raw = "原文第一段。\n原文第二段。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        class BrokenProvider:
            name = "siliconflow"

            def translate(self, article):
                raise TranslationResponseError(
                    "Translation response appears incomplete",
                    metadata={
                        "provider": "siliconflow",
                        "model": "deepseek-ai/DeepSeek-V3",
                        "finish_reason": "stop",
                        "attempt": 2,
                    },
                )

        with patch("stable.services.translation.get_translation_provider", return_value=BrokenProvider()):
            with self.assertRaises(TranslationResponseError):
                run_translation_service(self.article)

        run = self.article.translation_runs.first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.raw_response["finish_reason"], "stop")
        self.assertEqual(run.raw_response["attempt"], 2)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_uses_title_terms_and_excludes_known_horse_from_unknowns(self):
        TermEntry.objects.create(term_type="horse", source_ja="キタサンブラック", target_zh="北部玄驹", priority=100)
        self.article.title_ja = "【宝塚記念】兄キタサンブラックの悔しさを晴らすか シュガークンが一発狙う"
        self.article.body_ja_raw = "シュガークンがGI宝塚記念に挑む。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 42}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "キタサンブラック的弟弟シュガークン挑战宝塚纪念",
                                "body_zh": "シュガークン将向GI宝塚纪念发起挑战。",
                                "push_summary_zh": "シュガークン挑战宝塚纪念。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()
        response = type("Response", (), {"choices": [choice], "usage": usage})()

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(self.article)

        self.assertIn("北部玄驹", result.title_zh)
        self.assertIn("キタサンブラック", [term["source_ja"] for term in result.metadata["terms"]])
        self.assertNotIn("キタサンブラック", result.metadata["unknown_horse_names"])
        self.assertIn("シュガークン", result.metadata["unknown_horse_names"])

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_protects_external_horse_alias_without_chinese_mapping(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        self.article.title_ja = "マヤノライジンが出走"
        self.article.body_ja_raw = "マヤノライジンは重賞へ向かう。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__出战",
                                "body_zh": "__UMA_KEEP_1__将向重赏进发。",
                                "push_summary_zh": "__UMA_KEEP_1__出战。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("マヤノライジン", result.title_zh)
        self.assertIn("マヤノライジン", result.body_zh)
        self.assertIn("マヤノライジン", result.metadata["external_horse_names"])
        external = [item for item in result.metadata["recognized_horse_names"] if item["source"] == "external_alias"][0]
        self.assertEqual(external["external_horse_ids"], ["1001"])

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_protects_english_external_horse_alias_with_source_spelling(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            alias_source="test",
        )
        self.article.source_site = SourceSite.HKJC_NEWS
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.title_ja = "LUCKY STAR wins at Sha Tin"
        self.article.body_ja_raw = "LUCKY STAR was too strong in the closing stages."
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__ 在沙田取胜",
                                "body_zh": "__UMA_KEEP_1__ 在末段表现强劲。",
                                "push_summary_zh": "__UMA_KEEP_1__ 取胜。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("LUCKY STAR", result.title_zh)
        self.assertEqual(result.metadata["unknown_horse_names"], ["LUCKY STAR"])
        self.assertEqual(result.metadata["external_horse_names"], ["LUCKY STAR"])
        self.assertEqual(result.metadata["external_horse_aliases"][0]["name_ja"], "Lucky Star")

    @override_settings(
        TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3",
        TRANSLATION_MAX_ATTEMPTS=1,
        TRANSLATION_UNKNOWN_HORSE_LIMIT=1,
    )
    def test_provider_unknown_limit_is_not_consumed_by_known_horse_terms(self):
        for name in ["アカホース", "アオホース", "クロホース"]:
            TermEntry.objects.create(term_type="horse", source_ja=name, target_zh=f"{name}译名")
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="4001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        self.article.title_ja = "アカホース アオホース クロホース マヤノライジンが出走"
        self.article.body_ja_raw = "マヤノライジンは重賞へ向かう。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__出战",
                                "body_zh": "__UMA_KEEP_1__将向重赏进发。",
                                "push_summary_zh": "__UMA_KEEP_1__出战。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertEqual(result.metadata["unknown_horse_names"], ["マヤノライジン"])
        self.assertIn("マヤノライジン", result.title_zh)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=2)
    def test_provider_retries_when_unknown_horse_names_are_translated_away(self):
        self.article.title_ja = "【大阪杯レース後コメント】クロワデュノール北村友一騎手ら"
        self.article.body_ja_raw = (
            "1着 クロワデュノール(北村友一騎手)\n"
            "2着 メイショウタバル(武豊騎手)\n"
            "3着 ダノンデサイル(坂井瑠星騎手)"
        )
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")

        def fake_response(payload):
            usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 88, "prompt_tokens": 144}})()
            choice = type(
                "Choice",
                (),
                {
                    "message": type("Message", (), {"content": __import__("json").dumps(payload, ensure_ascii=False)})(),
                    "finish_reason": "stop",
                },
            )()
            return type("Response", (), {"choices": [choice], "usage": usage})()

        first = fake_response(
            {
                "title_zh": "大阪杯赛后评论 北十字星与骑手",
                "body_zh": "冠军北十字星，亚军名将原野，季军野田分位。",
                "push_summary_zh": "赛后评论。",
            }
        )
        second = fake_response(
            {
                "title_zh": "【大阪杯赛后评论】クロワデュノール与北村友一骑手等",
                "body_zh": (
                    "1着 クロワデュノール(北村友一骑手)\n"
                    "2着 メイショウタバル(武丰骑手)\n"
                    "3着 ダノンデサイル(坂井瑠星骑手)。"
                ),
                "push_summary_zh": "クロワデュノール夺冠，メイショウタバル与ダノンデサイル分列二三位。",
            }
        )

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as mocked:
            result = provider.translate(self.article)

        self.assertEqual(mocked.call_count, 2)
        self.assertIn("クロワデュノール", result.body_zh)
        self.assertIn("メイショウタバル", result.body_zh)
        self.assertIn("ダノンデサイル", result.body_zh)
        self.assertEqual(result.metadata["attempt"], 2)
        self.assertIn("メイショウタバル", result.metadata["unknown_horse_names"])

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_restores_unknown_horse_placeholders(self):
        self.article.title_ja = "メイショウタバルが出走"
        self.article.body_ja_raw = "1着 メイショウタバル(武豊騎手)。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__出战",
                                "body_zh": "第1名 __UMA_KEEP_1__(武丰骑手)。",
                                "push_summary_zh": "__UMA_KEEP_1__获胜。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("メイショウタバル", result.title_zh)
        self.assertIn("メイショウタバル", result.body_zh)
        self.assertNotIn("__UMA_KEEP_", result.body_zh)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_accepts_with_warning_when_unknown_horse_still_missing(self):
        self.article.title_ja = "メイショウタバルが出走"
        self.article.body_ja_raw = "1着 メイショウタバル(武豊騎手)。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "名将原野出战",
                                "body_zh": "第1名 名将原野(武丰骑手)。",
                                "push_summary_zh": "名将原野获胜。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("名将原野", result.body_zh)
        self.assertEqual(
            result.metadata["warning"],
            "Translation response changed unknown horse names; accepted with warning",
        )
        self.assertIn("メイショウタバル", result.metadata["missing_unknown_horse_names"])

    def test_translate_task_preserves_manually_cleared_summary_and_populates_horse_tags(self):
        TermEntry.objects.create(term_type="horse", source_ja="ソダシ", target_zh="纯净之辉", priority=100)
        TermEntry.objects.create(term_type="horse", source_ja="リバティアイランド", target_zh="自由岛", priority=90)
        self.article.title_ja = "ソダシとリバティアイランド"
        self.article.body_ja_raw = "ソダシが勝利し、リバティアイランドも健闘した。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.summary_zh = ""
        self.article.mark_manual_edits(["summary_zh"])
        self.article.save()

        fake_result = type(
            "Result",
            (),
            {
                "title_zh": "纯净之辉与自由岛",
                "body_zh": "纯净之辉获胜，自由岛也有出色表现。",
                "push_summary_zh": "机器摘要",
                "metadata": {"provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V3"},
            },
        )()

        with patch("stable.tasks.translate_article", return_value=fake_result):
            translate_article_task.run(self.article.id)

        self.article.refresh_from_db()
        self.assertEqual(self.article.summary_zh, "")
        self.assertEqual(self.article.effective_summary, "")
        self.assertCountEqual(self.article.tags_json, ["纯净之辉", "自由岛"])


class CrawlAutoTranslateTests(TestCase):
    @override_settings(AUTO_TRANSLATE_ON_INGEST=True, AUTO_TRANSLATE_SYNC=True)
    def test_new_article_is_translated_immediately_after_ingest(self):
        stub = type("Stub", (), {"source_article_id": "123"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="existing-123",
            title_ja="原文标题",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            published_at=timezone.now(),
            source_url="https://example.com/news/123",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ), patch("stable.tasks.translate_article_task.run", return_value={"translated": True}) as mocked_translate:
            result = _crawl_netkeiba_mode("latest", 1)

        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)
        mocked_translate.assert_called_once_with(article.id)

    @override_settings(TERM_DISCOVERY_ENABLED=True, AUTO_TRANSLATE_ON_INGEST=False)
    def test_term_discovery_dispatch_failure_does_not_abort_crawl(self):
        stub = type("Stub", (), {"source_article_id": "789"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="existing-789",
            title_ja="术语发现隔离测试",
            body_ja_raw="正文",
            body_ja_normalized="正文",
            published_at=timezone.now(),
            source_url="https://example.com/news/789",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ), patch("stable.tasks.dispatch_task", side_effect=RuntimeError("boom")):
            result = _crawl_netkeiba_mode("latest", 1)

        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=True, AUTO_TRANSLATE_SYNC=True)
    def test_translation_failure_does_not_abort_crawl(self):
        stub = type("Stub", (), {"source_article_id": "456"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="existing-456",
            title_ja="原文标题2",
            body_ja_raw="原文正文2",
            body_ja_normalized="原文正文2",
            published_at=timezone.now(),
            source_url="https://example.com/news/456",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ), patch("stable.tasks.translate_article_task.run", side_effect=RuntimeError("boom")) as mocked_translate:
            result = _crawl_netkeiba_mode("latest", 1)

        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)
        mocked_translate.assert_called_once_with(article.id)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_crawl_success_with_no_new_articles_records_success_summary(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST)
        stub = type("Stub", (), {"source_article_id": "seen-article"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="seen-article",
            title_ja="既存記事",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            published_at=timezone.now(),
            source_url="https://example.com/news/seen-article",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, False)
        ):
            result = _crawl_netkeiba_mode("latest", 1, source=source)

        source.refresh_from_db()
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertEqual(job.success_count, 0)
        self.assertEqual(job.fail_count, 1)
        self.assertEqual(source.last_crawl_status, TaskStatus.SUCCESS)
        self.assertEqual(source.last_crawl_message, "新增 0，重复 1")

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_source_elevated_public_article_dispatches_qq_auto_push(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_article_id": "seen-ranked-article"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            source_article_id="seen-ranked-article",
            title_ja="榜单提升已公开",
            title_zh="榜单提升已公开",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            body_zh="正文",
            published_at=timezone.now(),
            source_url="https://example.com/news/seen-ranked-article",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.dispatch_task") as mocked_dispatch:
            result = _crawl_netkeiba_mode("access", 1, source=source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        mocked_dispatch.assert_called_once_with(qq_auto_push_article_task, article.id)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_international_source_elevated_public_article_dispatches_qq_auto_push(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_url": "https://www.skysports.com/racing/news/sky-ranked-article"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_mode=SourceMode.ACCESS,
            source_article_id="sky-ranked-article",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Sky ranked article",
            title_zh="Sky 榜单文章",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            body_zh="正文",
            published_at=timezone.now(),
            source_url=stub.source_url,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        class FakeInternationalAdapter:
            def fetch_listing(self, mode, page):
                return [stub]

            def fetch_detail(self, source_url):
                return object()

            def normalize_source_payload(self, stub, detail):
                return object()

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {source.adapter_key: FakeInternationalAdapter}), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.dispatch_task") as mocked_dispatch:
            result = _crawl_international_source(source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        mocked_dispatch.assert_called_once_with(qq_auto_push_article_task, article.id)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_jra_detail_structure_error_skips_article_and_continues(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        bad_stub = type("Stub", (), {"source_url": "https://www.jra.go.jp/news/202605/bad.html"})()
        good_stub = type("Stub", (), {"source_url": "https://www.jra.go.jp/news/202605/good.html"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.JRA,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="/news/202605/good.html",
            title_ja="JRA 正常详情",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            published_at=timezone.now(),
            source_url="https://www.jra.go.jp/news/202605/good.html",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.JRAAdapter.fetch_listing", side_effect=[[bad_stub, good_stub], []]), patch(
            "stable.tasks.JRAAdapter.fetch_detail", side_effect=[AttributeError("missing date node"), object()]
        ), patch("stable.tasks.JRAAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ):
            result = _crawl_jra_source(source=source)

        source.refresh_from_db()
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertIn("跳过 1 条", job.error_message)
        self.assertIn("missing date node", job.error_message)
        self.assertIn("跳过 1 条", source.last_crawl_message)
        self.assertIn("missing date node", source.last_crawl_message)


class TermCandidateDiscoveryTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="term-candidate-1",
            title_ja="【大阪杯】メイショウタバルが出走、武豊騎手が騎乗",
            body_ja_raw="馬主は松本好雄。メイショウタバルが大阪杯に挑む。",
            body_ja_normalized="馬主は松本好雄。メイショウタバルが大阪杯に挑む。",
            published_at=timezone.now(),
            source_url="https://example.com/term-candidate-1",
        )

    def test_normalize_and_formal_alias_matching_includes_inactive_terms(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_ja="別名の馬",
            target_zh="测试马",
            aliases_ja=["メイショウタバル"],
            is_active=False,
        )
        self.assertEqual(normalize_japanese_term(" メイショウタバル "), "メイショウタバル")
        self.assertEqual(normalize_japanese_term(" EQUINOX "), "equinox")
        same_type, other_type = match_formal_terms("horse", "メイショウタバル")
        self.assertEqual(same_type, [term])
        self.assertEqual(other_type, [])

    def test_rule_discovery_finds_four_supported_types(self):
        findings = discover_term_findings(self.article)
        values = {(item.term_type, item.source_ja) for item in findings}
        self.assertIn(("horse", "メイショウタバル"), values)
        self.assertIn(("race", "大阪杯"), values)
        self.assertIn(("jockey", "武豊"), values)
        self.assertIn(("owner", "松本好雄"), values)

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_aggregate_is_idempotent_and_preserves_rejected_status(self):
        first = discover_and_aggregate_article(self.article)
        second = discover_and_aggregate_article(self.article)
        self.assertEqual(set(first["candidate_ids"]), set(second["candidate_ids"]))
        horse = TermCandidate.objects.get(term_type="horse", source_ja="メイショウタバル")
        evidence = horse.evidence.get(article=self.article)
        self.assertEqual(evidence.occurrence_count, 2)
        self.assertEqual(horse.article_count, 1)
        horse.status = TermCandidateStatus.REJECTED
        horse.save(update_fields=["status", "updated_at"])
        discover_and_aggregate_article(self.article)
        horse.refresh_from_db()
        self.assertEqual(horse.status, TermCandidateStatus.REJECTED)

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_formal_term_and_absent_source_are_not_persisted(self):
        TermEntry.objects.create(term_type="race", source_ja="大阪杯", target_zh="大阪杯")
        discover_and_aggregate_article(self.article)
        self.assertFalse(TermCandidate.objects.filter(term_type="race", source_ja="大阪杯").exists())
        absent = TermDiscoveryFinding("horse", "不存在的马", 99, "test", "测试", "title_ja", "")
        self.assertIsNone(aggregate_finding(self.article, absent))

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_unknown_horse_and_race_enter_candidate_pool_with_content_fields(self):
        discover_and_aggregate_article(self.article)
        horse = TermCandidate.objects.get(term_type="horse", source_ja="メイショウタバル")
        race = TermCandidate.objects.get(term_type="race", source_ja="大阪杯")

        self.assertEqual(horse.target_zh, "")
        self.assertEqual(horse.aliases_ja, [])
        self.assertEqual(horse.aliases_zh, [])
        self.assertEqual(race.target_zh, "")
        self.assertEqual(race.aliases_ja, [])
        self.assertEqual(race.aliases_zh, [])
        self.assertTrue(horse.evidence.filter(article=self.article).exists())
        self.assertTrue(race.evidence.filter(article=self.article).exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_external_alias_horse_enters_candidate_pool_from_background_body(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="external-alias-candidate",
            title_ja="重賞展望",
            body_ja_raw="前半は調教過程を紹介する。" * 6 + "背景としてマヤノライジンにも触れた。",
            body_ja_normalized="前半は調教過程を紹介する。" * 6 + "背景としてマヤノライジンにも触れた。",
            published_at=timezone.now(),
            source_url="https://example.com/external-alias-candidate",
        )

        discover_and_aggregate_article(article)

        candidate = TermCandidate.objects.get(term_type="horse", source_ja="マヤノライジン")
        evidence = candidate.evidence.get(article=article)
        self.assertIn("本地外部马名索引命中且缺少中文译名", candidate.detection_reasons)
        self.assertIn("external_horse_alias", evidence.detectors)

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_external_alias_horse_with_formal_term_does_not_create_candidate(self):
        TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="external-alias-formal",
            title_ja="マヤノライジンが出走",
            body_ja_raw="マヤノライジンが重賞へ向かう。",
            body_ja_normalized="マヤノライジンが重賞へ向かう。",
            published_at=timezone.now(),
            source_url="https://example.com/external-alias-formal",
        )

        discover_and_aggregate_article(article)

        self.assertFalse(TermCandidate.objects.filter(term_type="horse", source_ja="マヤノライジン").exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_common_word_external_alias_without_strong_context_does_not_enter_candidate_pool(self):
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="タイトル",
            target_zh="标题",
            notes="non_horse_common_word: 测试普通词",
        )
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="2001",
            name_ja="タイトル",
            normalized_name="タイトル",
            alias_source="test",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="external-alias-common-word",
            title_ja="記事のタイトルを変更",
            body_ja_raw="ページタイトルを確認した。",
            body_ja_normalized="ページタイトルを確認した。",
            published_at=timezone.now(),
            source_url="https://example.com/external-alias-common-word",
        )

        discover_and_aggregate_article(article)

        self.assertFalse(TermCandidate.objects.filter(term_type="horse", source_ja="タイトル").exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_formal_alias_prevents_horse_and_race_candidates(self):
        TermEntry.objects.create(term_type="horse", source_ja="正式马名", target_zh="正式马名", aliases_ja=["メイショウタバル"])
        TermEntry.objects.create(term_type="race", source_ja="正式赛事", target_zh="正式赛事", aliases_ja=["大阪杯"])
        discover_and_aggregate_article(self.article)
        self.assertFalse(TermCandidate.objects.filter(term_type="horse", source_ja="メイショウタバル").exists())
        self.assertFalse(TermCandidate.objects.filter(term_type="race", source_ja="大阪杯").exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_cross_type_formal_conflict_is_retained(self):
        TermEntry.objects.create(term_type="owner", source_ja="武豊", target_zh="冲突词")
        discover_and_aggregate_article(self.article)
        candidate = TermCandidate.objects.get(term_type="jockey", source_ja="武豊")
        self.assertEqual(candidate.conflicts[0]["term_type"], "owner")

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_evidence_contexts_are_bounded(self):
        for index in range(7):
            aggregate_finding(
                self.article,
                TermDiscoveryFinding(
                    "horse",
                    "メイショウタバル",
                    78,
                    "test",
                    "测试",
                    "title_ja",
                    f"上下文 {index}",
                ),
            )
        evidence = TermCandidate.objects.get(term_type="horse", source_ja="メイショウタバル").evidence.get(article=self.article)
        self.assertEqual(len(evidence.contexts), 5)

    @override_settings(TERM_DISCOVERY_ENABLED=False)
    def test_task_skips_when_disabled(self):
        result = discover_term_candidates_task.run(self.article.id)
        self.assertTrue(result["skipped"])
        self.assertEqual(TermCandidate.objects.count(), 0)

    @override_settings(TERM_DISCOVERY_ENABLED=True)
    def test_task_records_failure_when_article_is_missing(self):
        with self.assertRaises(NewsArticle.DoesNotExist):
            discover_term_candidates_task.run(999999)
        log = TaskExecutionLog.objects.get(task_name="discover_term_candidates")
        self.assertEqual(log.status, TaskStatus.FAILED)
        self.assertTrue(log.finished_at)


@override_settings(TERM_DISCOVERY_ENABLED=True, TERM_DISCOVERY_MIN_CONFIDENCE=60, CELERY_TASK_ALWAYS_EAGER=True)
class TermCandidateReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="term-admin", password="pass", is_staff=True)
        self.client = Client()
        self.client.force_login(self.user)
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="term-review-1",
            title_ja="メイショウタバルが出走",
            body_ja_raw="メイショウタバルが勝利した。",
            body_ja_normalized="メイショウタバルが勝利した。",
            published_at=timezone.now(),
            source_url="https://example.com/term-review-1",
        )
        discover_and_aggregate_article(self.article)
        self.candidate = TermCandidate.objects.get(term_type="horse")

    def test_accept_candidate_creates_formal_term_and_logs(self):
        self.candidate.target_zh = "名将田原"
        self.candidate.aliases_ja = ["メイショウ"]
        self.candidate.aliases_zh = ["名将田原号"]
        self.candidate.save(update_fields=["target_zh", "aliases_ja", "aliases_zh", "updated_at"])
        term = accept_candidate(
            self.candidate,
            {
                "term_type": "horse",
                "source_ja": self.candidate.source_ja,
                "target_zh": self.candidate.target_zh,
                "aliases_ja": self.candidate.aliases_ja,
                "aliases_zh": self.candidate.aliases_zh,
                "priority": 10,
                "is_active": True,
                "notes": "",
                "review_notes": "确认",
            },
            self.user,
        )
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.ACCEPTED)
        self.assertEqual(self.candidate.accepted_term, term)
        self.assertEqual(term.aliases_ja, ["メイショウ"])
        self.assertEqual(term.aliases_zh, ["名将田原号"])
        self.assertTrue(self.user.operation_logs.filter(action_type="term_candidate_accepted").exists())
        with self.assertRaisesMessage(ValueError, "只有待审核候选"):
            set_candidate_status(self.candidate, self.user, TermCandidateStatus.REJECTED)

    def test_merge_requires_explicit_alias_confirmation(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="正式马名", target_zh="正式译名")
        merge_candidate(self.candidate, self.user, target_term=term, add_as_alias=False)
        term.refresh_from_db()
        self.assertNotIn(self.candidate.source_ja, term.aliases_ja)

    def test_reject_keeps_candidate_and_evidence(self):
        set_candidate_status(self.candidate, self.user, TermCandidateStatus.REJECTED, "误报")
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.REJECTED)
        self.assertTrue(self.candidate.evidence.exists())

    def test_staff_pages_and_single_article_retrigger(self):
        list_response = self.client.get(reverse("console-term-candidate-list"))
        detail_response = self.client.get(reverse("console-term-candidate-detail", args=[self.candidate.id]))
        retrigger_response = self.client.post(
            reverse("console-article-discover-terms", args=[self.article.id]),
            {"next": reverse("console-candidate-detail", args=[self.article.id])},
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "メイショウタバル")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(retrigger_response.status_code, 302)
        self.assertTrue(TaskExecutionLog.objects.filter(task_name="discover_term_candidates", status=TaskStatus.SUCCESS).exists())

    def test_list_filters_by_status_and_type(self):
        response = self.client.get(
            reverse("console-term-candidate-list"),
            {"status": TermCandidateStatus.PENDING, "term_type": "horse", "min_confidence": 70},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メイショウタバル")
        response = self.client.get(reverse("console-term-candidate-list"), {"term_type": "race"})
        self.assertNotContains(response, "メイショウタバル")

    def test_list_filters_by_keyword_source_and_seen_date(self):
        source = NewsSource.objects.create(
            name="功能测试来源",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
        )
        self.article.source_config = source
        self.article.save(update_fields=["source_config", "updated_at"])
        today = timezone.localdate().isoformat()

        response = self.client.get(
            reverse("console-term-candidate-list"),
            {"q": "メイショウ", "source": source.id, "seen_from": today, "seen_to": today},
        )
        self.assertContains(response, "メイショウタバル")
        response = self.client.get(reverse("console-term-candidate-list"), {"q": "不存在"})
        self.assertNotContains(response, "メイショウタバル")

    def test_unauthenticated_user_is_redirected_to_login(self):
        client = Client()
        response = client.get(reverse("console-term-candidate-list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("backend-login"), response.url)

    def test_non_staff_is_forbidden(self):
        non_staff = User.objects.create_user(username="reader", password="pass")
        client = Client()
        client.force_login(non_staff)
        response = client.get(reverse("console-term-candidate-list"))
        self.assertEqual(response.status_code, 403)

    def test_batch_review_only_changes_pending_candidates(self):
        accepted = TermCandidate.objects.create(
            term_type="race",
            source_ja="大阪杯",
            normalized_key="大阪杯",
            status=TermCandidateStatus.ACCEPTED,
        )
        response = self.client.post(
            reverse("console-term-candidate-batch-review"),
            {"candidate_ids": [self.candidate.id, accepted.id], "status": TermCandidateStatus.IGNORED},
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        accepted.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.IGNORED)
        self.assertEqual(accepted.status, TermCandidateStatus.ACCEPTED)

    def test_accept_endpoint_creates_formal_term_with_modified_fields(self):
        self.candidate.target_zh = "名将田原"
        self.candidate.aliases_ja = ["メイショウ"]
        self.candidate.aliases_zh = ["名将"]
        self.candidate.save(update_fields=["target_zh", "aliases_ja", "aliases_zh", "updated_at"])
        response = self.client.post(
            reverse("console-term-candidate-accept", args=[self.candidate.id]),
            {
                "term_type": "horse",
                "source_ja": "メイショウタバル改",
                "target_zh": "名将田原改",
                "aliases_ja_text": "メイショウタバル",
                "aliases_zh_text": "名将田原",
                "priority": "25",
                "notes": "功能测试正式术语",
                "review_notes": "页面修改后接受",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        term = TermEntry.objects.get(source_ja="メイショウタバル改")
        self.assertEqual(self.candidate.status, TermCandidateStatus.ACCEPTED)
        self.assertEqual(self.candidate.accepted_term, term)
        self.assertEqual(term.aliases_ja, ["メイショウタバル"])
        self.assertEqual(term.aliases_zh, ["名将田原"])
        self.assertEqual(term.priority, 25)
        self.assertEqual(self.candidate.review_notes, "页面修改后接受")

    def test_accept_endpoint_rejects_existing_formal_term(self):
        TermEntry.objects.create(term_type="horse", source_ja=self.candidate.source_ja, target_zh="已有译名")
        response = self.client.post(
            reverse("console-term-candidate-accept", args=[self.candidate.id]),
            {
                "term_type": "horse",
                "source_ja": self.candidate.source_ja,
                "target_zh": "重复译名",
                "priority": "0",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "已存在相同原文", status_code=400)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.PENDING)

    def test_merge_endpoint_adds_alias_only_with_explicit_confirmation(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="正式马名", target_zh="正式译名")
        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {
                "target_term": term.id,
                "add_as_alias": "on",
                "review_notes": "确认添加别名",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        term.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.MERGED)
        self.assertEqual(self.candidate.merged_into_term, term)
        self.assertIn(self.candidate.source_ja, term.aliases_ja)
        self.assertTrue(self.candidate.evidence.exists())
        search_response = self.client.get(reverse("console-term-list"), {"q": self.candidate.source_ja})
        self.assertContains(search_response, term.source_ja)

    def test_merge_endpoint_adds_cross_language_alias_to_term_concept(self):
        self.candidate.source_language = SourceLanguage.ENGLISH
        self.candidate.source_ja = "Equinox"
        self.candidate.normalized_key = "Equinox"
        self.candidate.save(update_fields=["source_language", "source_ja", "normalized_key", "updated_at"])
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
        )

        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {
                "target_term": term.id,
                "add_as_alias": "on",
                "review_notes": "英文名并入同一马匹",
            },
        )

        self.assertEqual(response.status_code, 302)
        term.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.MERGED)
        self.assertNotIn("Equinox", term.aliases_ja)
        self.assertTrue(
            TermAlias.objects.filter(term=term, source_language=SourceLanguage.ENGLISH, text="Equinox").exists()
        )
        matches = resolve_terms_for_language("Equinox is back", SourceLanguage.ENGLISH, limit=10)
        self.assertEqual([item.target_zh for item in matches], ["春秋分"])

    def test_merge_endpoint_does_not_duplicate_cross_language_alias_by_case(self):
        self.candidate.source_language = SourceLanguage.ENGLISH
        self.candidate.source_ja = "EQUINOX"
        self.candidate.normalized_key = "equinox"
        self.candidate.save(update_fields=["source_language", "source_ja", "normalized_key", "updated_at"])
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )

        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {
                "target_term": term.id,
                "add_as_alias": "on",
                "review_notes": "英文名大小写合并",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            TermAlias.objects.filter(term=term, source_language=SourceLanguage.ENGLISH, text__iexact="equinox").count(),
            1,
        )

    def test_merge_endpoint_into_candidate_keeps_evidence(self):
        target = TermCandidate.objects.create(
            term_type="horse",
            source_ja="メイショウタバル別候補",
            normalized_key="メイショウタバル別候補",
        )
        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {"target_candidate": target.id, "review_notes": "合并重复候选"},
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.MERGED)
        self.assertEqual(self.candidate.merged_into_candidate, target)
        self.assertTrue(self.candidate.evidence.exists())

    def test_reject_and_ignore_endpoints_keep_evidence_and_log_operations(self):
        reject_response = self.client.post(
            reverse("console-term-candidate-reject", args=[self.candidate.id]),
            {"review_notes": "页面拒绝"},
            follow=True,
        )
        self.assertEqual(reject_response.status_code, 200)
        self.assertContains(reject_response, "候选状态已更新为“已拒绝”。")
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.REJECTED)
        self.assertTrue(self.candidate.evidence.exists())

        ignored = TermCandidate.objects.create(
            term_type="race",
            source_ja="测试忽略杯",
            normalized_key="测试忽略杯",
        )
        ignore_response = self.client.post(
            reverse("console-term-candidate-ignore", args=[ignored.id]),
            {"review_notes": "页面忽略"},
            follow=True,
        )
        self.assertEqual(ignore_response.status_code, 200)
        self.assertContains(ignore_response, "候选状态已更新为“已忽略”。")
        ignored.refresh_from_db()
        self.assertEqual(ignored.status, TermCandidateStatus.IGNORED)
        self.assertTrue(self.user.operation_logs.filter(action_type="term_candidate_rejected").exists())
        self.assertTrue(self.user.operation_logs.filter(action_type="term_candidate_ignored").exists())

    def test_validate_candidate_news_since_midnight_command_reports_today_articles(self):
        TermEntry.objects.create(term_type="race", source_ja="宝塚記念", target_zh="宝塚纪念", race_grade="G1")
        today_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="today-candidate-news",
            title_ja="【宝塚記念】シュガークンが出走",
            body_ja_raw="シュガークンが宝塚記念・GIに挑む。",
            body_ja_normalized="シュガークンが宝塚記念・GIに挑む。",
            translated_body_zh="宝塚纪念候选新闻。",
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            first_seen_at=timezone.now(),
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            source_url="https://example.com/today-candidate-news",
        )
        yesterday = timezone.now() - timedelta(days=1)
        old_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="old-candidate-news",
            title_ja="【大阪杯】古い候補ニュース",
            body_ja_raw="古い候補ニュース。",
            body_ja_normalized="古い候補ニュース。",
            translated_body_zh="旧新闻。",
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=yesterday,
            first_seen_at=yesterday,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            source_url="https://example.com/old-candidate-news",
        )
        discover_and_aggregate_article(today_article)

        out = StringIO()
        call_command("validate_candidate_news_since_midnight", "--format", "json", stdout=out)
        payload = __import__("json").loads(out.getvalue())
        article_ids = [item["article_id"] for item in payload["articles"]]

        self.assertIn(today_article.id, article_ids)
        self.assertNotIn(old_article.id, article_ids)
        self.assertGreaterEqual(payload["candidate_news_count"], 1)
        self.assertIn("race_priority", payload["articles"][0])
        self.assertIn("term_candidate_count", payload["articles"][0])
