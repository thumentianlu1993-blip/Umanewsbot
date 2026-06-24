from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalHorseAlias,
    ExternalImportStatus,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceOdds,
    ExternalRaceResult,
    NewsImage,
    NewsArticle,
    NewsSnapshot,
    NewsSource,
    NotificationLog,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    QQPushErrorType,
    ReviewMode,
    SourceMode,
    SourceSite,
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
    should_push_news_to_qq,
)
from stable.services.pushing import build_push_message, push_article_to_targets
from stable.services.automation import score_article_for_automation
from stable.services.notifications import send_high_value_warning_notification
from stable.services.rewriting import _loads_rewrite_payload
from stable.services.sources import sync_builtin_sources
from stable.services.term_admin import preview_term_import
from stable.services.term_candidate_review import accept_candidate, merge_candidate, set_candidate_status
from stable.services.term_discovery import (
    TermDiscoveryFinding,
    aggregate_finding,
    discover_and_aggregate_article,
    discover_term_findings,
    match_formal_terms,
    normalize_japanese_term,
)
from stable.services.terms import apply_term_mappings, extract_horse_tags, extract_unknown_horse_names, resolve_terms
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
from stable.tasks import (
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

    @override_settings(QQ_PUSH_SCOPE="high_value_only", AUTO_REVIEW_THRESHOLD=75)
    def test_high_value_scope_uses_score_threshold(self):
        self.assertTrue(should_push_news_to_qq(self.article).allowed)
        self.article.score_total = 20
        self.article.save(update_fields=["score_total", "updated_at"])

        result = should_push_news_to_qq(self.article)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "not_high_value")

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

    def test_auto_push_message_uses_summary_and_public_url(self):
        message = build_qq_auto_push_message(self.article)

        self.assertIn("【UmaFans】中文标题", message)
        self.assertIn("中文摘要", message)
        self.assertIn("阅读全文：http://testserver/news/", message)

    def test_auto_push_message_truncates_body_when_summary_blank(self):
        self.article.summary_zh = ""
        self.article.push_summary_zh = ""
        self.article.translated_summary_zh = ""
        self.article.rewrite_summary_zh = ""
        self.article.save()

        message = build_qq_auto_push_message(self.article)

        self.assertIn("……", message)
        self.assertIn("阅读全文：http://testserver/news/", message)

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=3)
    def test_delivery_url_unavailable_records_retryable_error_type(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(False, "HTTP 404")):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.RETRYING)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.URL_UNAVAILABLE)

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

    @override_settings(QQ_PUSH_ENABLED=True, QQ_PUSH_SCOPE="high_value_only")
    def test_article_task_queues_only_active_targets(self):
        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            result = qq_auto_push_article_task.run(self.article.id)

        self.assertEqual(len(result["queued_delivery_ids"]), 1)
        self.assertEqual(QQPushDelivery.objects.count(), 1)
        self.assertEqual(QQPushDelivery.objects.get().target, self.target)
        delay.assert_called_once()

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

    def test_dashboard_and_sources_page_available(self):
        dashboard = self.client.get(reverse("console-dashboard"))
        source_page = self.client.get(reverse("console-source-list"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "工作台")
        self.assertEqual(source_page.status_code, 200)
        self.assertContains(source_page, "来源管理")

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
        tags: list[str] | None = None,
    ) -> NewsArticle:
        published_at = published_at or timezone.now()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=source_mode,
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

    def test_term_toggle_active(self):
        response = self.client.post(reverse("console-term-toggle", args=[self.term.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.term.refresh_from_db()
        self.assertFalse(self.term.is_active)

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

    def test_import_terms_management_command_supports_dry_run(self):
        out = StringIO()
        call_command("import_terms", "--dry-run", stdout=out)
        self.assertIn("预检", out.getvalue())
        self.assertFalse(TermEntry.objects.filter(source_ja="キタサンブラック").exists())

    def test_term_api_create_and_toggle(self):
        create_response = self.client.post(
            reverse("api-term-create"),
            data='{"term_type":"org","source_ja":"JRA","target_zh":"日本中央竞马会","aliases_ja":["日本中央競馬会"],"aliases_zh":["JRA"],"priority":5,"is_active":true,"notes":""}',
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 200)
        payload = create_response.json()
        term_id = payload["term"]["id"]
        toggle_response = self.client.post(reverse("api-term-toggle-active", args=[term_id]))
        self.assertEqual(toggle_response.status_code, 200)
        self.assertFalse(TermEntry.objects.get(pk=term_id).is_active)


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
        self.assertContains(response, "已存在相同日文原词", status_code=400)
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
