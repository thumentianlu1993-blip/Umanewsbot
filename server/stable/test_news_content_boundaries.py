from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.adapters.international import SportingLifeAdapter, TDNAdapter
from stable.models import (
    ArticleTranslationStatus,
    NewsArticle,
    OperationLog,
    PublishedByMode,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)
from stable.services.translation import OpenAICompatibleTranslationProvider
from stable.tasks import translate_article_task


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "news_content_boundaries"


def fixture_html(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class InternationalNewsContentBoundaryTests(TestCase):
    def test_sporting_life_8086_extracts_only_real_article_body(self):
        detail = SportingLifeAdapter().parse_detail_html(
            fixture_html("sporting_life_8086.html"),
            url="https://www.sportinglife.com/racing/news/david-ord-tribute-to-graham-bradley/233144",
        )

        self.assertIn("Graham Bradley always had time", detail.body_ja_raw)
        self.assertIn("the years roll on", detail.body_ja_raw)
        self.assertIn("Graham Bradley celebrates at Cheltenham", detail.body_ja_raw)
        self.assertNotIn("Fast Results", detail.body_ja_raw)
        self.assertNotIn("Premium banner", detail.body_ja_raw)
        self.assertNotIn("Share Tweet", detail.body_ja_raw)
        self.assertNotIn("Safer Gambling", detail.body_ja_raw)
        self.assertEqual(detail.metadata["body_parse_status"], "ok")
        self.assertIn("Article__ArticleBody", detail.metadata["body_selector"])

    def test_sporting_life_removes_production_social_button_component(self):
        detail = SportingLifeAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Tribute"></head><body>
            <div class="Article__ArticleBody-sc-production"><p>Real tribute body.</p>
            <div class="ArticleSocialMediaButtons__StyledInnerContainer-sc-production"><div>Share</div><div>Tweet</div><div>Email</div></div></div>
            </body></html>""",
            url="https://www.sportinglife.com/racing/news/tribute/233144",
        )

        self.assertEqual(detail.body_ja_raw, "Real tribute body.")
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["structured_noise"], 1)

    def test_sporting_life_8267_removes_betting_noise_but_keeps_exceptions(self):
        detail = SportingLifeAdapter().parse_detail_html(
            fixture_html("sporting_life_8267.html"),
            url="https://www.sportinglife.com/racing/news/weather-set-fair-for-go-racing-in-yorkshire-summer-festival/233189",
        )

        self.assertIn("Sky Bet Go Racing In Yorkshire Summer Festival", detail.body_ja_raw)
        self.assertIn("Blue Horizon is 7/2", detail.body_ja_raw)
        self.assertIn("forecast is dry and warm", detail.body_ja_raw)
        self.assertIn("the popular summer festival covers nine days", detail.body_ja_raw)
        self.assertIn("Friday July 24 – York Music Showcase", detail.body_ja_raw)
        self.assertNotIn("£100 charity bet", detail.body_ja_raw)
        self.assertNotIn("Charity Tipping Challenge", detail.body_ja_raw)
        self.assertNotIn("winning tipster", detail.body_ja_raw)
        self.assertNotIn("Backed by Sky Bet", detail.body_ja_raw)
        self.assertNotIn("BOOK NOW", detail.body_ja_raw)
        self.assertNotIn("claim £30 in free bets", detail.body_ja_raw)
        self.assertNotIn("More from Sporting Life", detail.body_ja_raw)
        self.assertNotIn("gambling problem", detail.body_ja_raw)
        self.assertGreaterEqual(detail.metadata["body_cleaning"]["removed_count"], 3)
        self.assertIn("betting_promotion", detail.metadata["body_cleaning"]["removed_rules"])

    def test_schedule_translation_line_coverage_is_not_mistaken_for_truncation(self):
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        source = "\n\n".join(
            [
                "The festival returns this week.",
                "The programme runs for nine days.",
                "Full list of racecourses and dates",
                *[
                    f"Friday July {day} - Racecourse {day} family programme with live music and a full afternoon card"
                    for day in range(17, 27)
                ],
            ]
        )
        complete = "\n".join(
            [
                "赛马节本周回归，活动为期九天。",
                "完整赛马场及日期列表：",
                *[f"7月{day}日周五 - 第{day}赛马场" for day in range(17, 27)],
            ]
        )

        self.assertFalse(provider._looks_incomplete(source, complete))

    def test_schedule_translation_missing_tail_lines_is_still_incomplete(self):
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        source = "\n\n".join(
            [
                "The festival returns this week.",
                "The programme runs for nine days.",
                "Full list of racecourses and dates",
                *[
                    f"Friday July {day} - Racecourse {day} family programme with live music and a full afternoon card"
                    for day in range(17, 27)
                ],
            ]
        )
        truncated = "\n".join(
            [
                "赛马节本周回归。",
                "完整赛马场及日期列表：",
                *[f"7月{day}日周五 - 第{day}赛马场" for day in range(17, 21)],
            ]
        )

        self.assertTrue(provider._looks_incomplete(source, truncated))

    def test_sporting_life_minified_sibling_blocks_are_cleaned_independently(self):
        detail = SportingLifeAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Festival preview"></head><body>
            <div class="Article__ArticleBody-sc-production-8267"><div>
            <p>The Sky Bet Go Racing In Yorkshire Summer Festival returns this week.</p><p>Blue Horizon is 7/2 for the feature race.</p><p>Each person is given a £100 charity bet for the meeting.</p><h2>More from Sporting Life</h2><p>Free bets and safer gambling.</p>
            </div></div></body></html>""",
            url="https://www.sportinglife.com/racing/news/festival-preview/233189",
        )

        self.assertEqual(detail.metadata["body_parse_status"], "ok")
        self.assertIn("Sky Bet Go Racing In Yorkshire Summer Festival", detail.body_ja_raw)
        self.assertIn("Blue Horizon is 7/2", detail.body_ja_raw)
        self.assertNotIn("charity bet", detail.body_ja_raw)
        self.assertNotIn("More from Sporting Life", detail.body_ja_raw)
        self.assertNotIn("Free bets", detail.body_ja_raw)

    def test_tdn_8316_removes_results_cta_and_tail(self):
        detail = TDNAdapter().parse_detail_html(
            fixture_html("tdn_8316.html"),
            url="https://www.thoroughbreddailynews.com/charity-event/",
        )

        self.assertIn("event brought together owners", detail.body_ja_raw)
        self.assertIn("programme will return next year", detail.body_ja_raw)
        self.assertNotIn("complete list of results", detail.body_ja_raw)
        self.assertNotIn("Read Today's Paper", detail.body_ja_raw)
        self.assertIn("tdn_results_cta", detail.metadata["body_cleaning"]["removed_rules"])

    def test_tdn_8318_removes_leading_editor_note_and_link_only_paragraph(self):
        detail = TDNAdapter().parse_detail_html(
            fixture_html("tdn_8318.html"),
            url="https://www.thoroughbreddailynews.com/promising-juvenile/",
        )

        self.assertNotIn("Editor's Note", detail.body_ja_raw)
        self.assertNotIn("click here", detail.body_ja_raw)
        self.assertIn("more than enough time", detail.body_ja_raw)
        self.assertIn("paper trail in the formbook", detail.body_ja_raw)
        self.assertNotIn("Read Today's Paper", detail.body_ja_raw)

    def test_tdn_editor_note_link_without_click_here_is_removed(self):
        detail = TDNAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Guild statement"></head><body>
            <span itemprop="articleBody"><p>Editor's Note: The following is an edited press release.</p><p>To view July 12 interview with the racing officials.</p><p>The Guild will continue its safety work.</p></span>
            </body></html>""",
            url="https://www.thoroughbreddailynews.com/guild-statement/",
        )

        self.assertEqual(detail.body_ja_raw, "The Guild will continue its safety work.")
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["tdn_editor_note"], 1)
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["tdn_leading_link"], 1)

    def test_missing_trusted_body_selector_never_falls_back_to_page_body(self):
        detail = SportingLifeAdapter().parse_detail_html(
            "<html><head><title>Navigation shell</title></head><body><nav>Fast Results</nav><footer>Terms</footer></body></html>",
            url="https://www.sportinglife.com/racing/news/layout-drift/999999",
        )

        self.assertEqual(detail.body_ja_raw, "")
        self.assertEqual(detail.body_ja_normalized, "")
        self.assertEqual(detail.metadata["body_parse_status"], "selector_not_found")
        self.assertNotIn("Fast Results", detail.body_ja_raw)

    def test_body_that_is_empty_after_cleaning_stays_empty(self):
        detail = TDNAdapter().parse_detail_html(
            """
            <html><body><span itemprop="articleBody">
              <p>Editor's Note: magazine-only introduction.</p>
              <p>Read Today's Paper</p>
            </span></body></html>
            """,
            url="https://www.thoroughbreddailynews.com/template-only/",
        )

        self.assertEqual(detail.body_ja_raw, "")
        self.assertEqual(detail.metadata["body_parse_status"], "empty_after_cleaning")

    def test_cleaning_metadata_is_a_summary_and_does_not_copy_html(self):
        html = fixture_html("tdn_8316.html")
        adapter = TDNAdapter()
        detail = adapter.parse_detail_html(html, url="https://www.thoroughbreddailynews.com/charity-event/")
        serialized_metadata = json.dumps(detail.metadata)

        self.assertEqual(detail.original_content_html, html)
        self.assertNotIn("<!doctype html>", serialized_metadata)
        self.assertNotIn("original_content_html", detail.metadata)
        self.assertIsInstance(detail.metadata["body_cleaning"]["removed_rules"], dict)


class RepairArticleContentBoundariesCommandTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="production-8316",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Breeders' Cup Charity Event Raises Funds",
            body_ja_raw="Old body with complete list of results and Read Today's Paper.",
            body_ja_normalized="Old body with complete list of results and Read Today's Paper.",
            original_content_html=fixture_html("tdn_8316.html"),
            translated_title_zh="旧标题",
            translated_body_zh="旧译文",
            title_zh="人工旧标题",
            body_zh="人工旧译文",
            manually_edited_fields=["title_zh", "body_zh"],
            published_at=timezone.now(),
            published_to_web_at=timezone.now(),
            source_url="https://www.thoroughbreddailynews.com/charity-event/",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_by_mode=PublishedByMode.AUTO,
        )

    def test_command_requires_explicit_article_ids(self):
        with self.assertRaises(CommandError):
            call_command("repair_article_content_boundaries")

    def test_dry_run_reports_hashes_without_writing(self):
        before_body = self.article.body_ja_raw
        before_metadata = dict(self.article.translation_metadata)
        out = StringIO()

        call_command("repair_article_content_boundaries", "--article-id", str(self.article.id), stdout=out)

        payload = json.loads(out.getvalue())
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["articles"][0]["article_id"], self.article.id)
        self.assertEqual(payload["articles"][0]["body_parse_status"], "ok")
        self.assertNotEqual(payload["articles"][0]["before_sha256"], payload["articles"][0]["after_sha256"])
        self.article.refresh_from_db()
        self.assertEqual(self.article.body_ja_raw, before_body)
        self.assertEqual(self.article.translation_metadata, before_metadata)
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())

    def test_commit_updates_only_source_body_and_audit_metadata(self):
        before_workflow = self.article.workflow_status
        before_published_at = self.article.published_to_web_at
        before_title_zh = self.article.title_zh
        before_body_zh = self.article.body_zh

        call_command(
            "repair_article_content_boundaries",
            "--article-id",
            str(self.article.id),
            "--commit",
            stdout=StringIO(),
        )

        self.article.refresh_from_db()
        self.assertIn("event brought together owners", self.article.body_ja_raw)
        self.assertNotIn("complete list of results", self.article.body_ja_raw)
        self.assertEqual(self.article.workflow_status, before_workflow)
        self.assertEqual(self.article.published_to_web_at, before_published_at)
        self.assertEqual(self.article.title_zh, before_title_zh)
        self.assertEqual(self.article.body_zh, before_body_zh)
        self.assertEqual(
            self.article.translation_metadata["content_boundary_repair"]["body_parse_status"],
            "ok",
        )
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_content_boundary_repaired",
                target_type="article",
                target_id=str(self.article.id),
            ).exists()
        )
        self.assertFalse(QQPushDelivery.objects.filter(article=self.article).exists())

    def test_commit_rejects_selector_failure_without_partial_write(self):
        self.article.original_content_html = "<html><body><nav>TDN shell</nav></body></html>"
        self.article.save(update_fields=["original_content_html", "updated_at"])
        before_body = self.article.body_ja_raw

        with self.assertRaises(CommandError):
            call_command(
                "repair_article_content_boundaries",
                "--article-id",
                str(self.article.id),
                "--commit",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_ja_raw, before_body)
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, AUTOMATION_ENABLED=False)
class ForcePublishedArticleTranslationTests(TestCase):
    def setUp(self):
        self.published_to_web_at = timezone.now()
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="force-translation-published",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Updated source title",
            body_ja_raw="Updated source body.",
            body_ja_normalized="Updated source body.",
            translated_title_zh="旧机器标题",
            translated_body_zh="旧机器正文",
            translated_summary_zh="旧机器摘要",
            title_zh="人工旧标题",
            body_zh="人工旧正文",
            summary_zh="人工旧摘要",
            push_summary_zh="人工旧推送摘要",
            manually_edited_fields=["title_zh", "body_zh", "summary_zh", "push_summary_zh"],
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            published_to_web_at=self.published_to_web_at,
            source_url="https://www.thoroughbreddailynews.com/force-translation/",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_by_mode=PublishedByMode.AUTO,
        )
        target = PushTarget.objects.create(name="Existing delivery", group_id="content-boundary-existing")
        self.delivery = QQPushDelivery.objects.create(
            article=self.article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            message_id="existing-message",
            sent_at=timezone.now(),
        )

    def _result(self):
        return type(
            "Result",
            (),
            {
                "title_zh": "修复后标题",
                "body_zh": "修复后的干净正文",
                "push_summary_zh": "修复后摘要",
                "metadata": {"provider": "test", "model": "test-model"},
            },
        )()

    def test_force_task_overwrites_approved_copy_without_republishing(self):
        with patch("stable.tasks.translate_article", return_value=self._result()):
            translate_article_task.run(self.article.id, force=True)

        self.article.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.article.title_zh, "修复后标题")
        self.assertEqual(self.article.body_zh, "修复后的干净正文")
        self.assertEqual(self.article.summary_zh, "修复后摘要")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(self.article.published_to_web_at, self.published_to_web_at)
        self.assertEqual(self.delivery.message_id, "existing-message")
        self.assertEqual(QQPushDelivery.objects.filter(article=self.article).count(), 1)

    def test_translate_news_force_flag_is_explicit_and_runs_synchronously(self):
        with patch("stable.tasks.translate_article", return_value=self._result()):
            call_command(
                "translate_news",
                "--article-id",
                str(self.article.id),
                "--sync",
                "--force",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "修复后的干净正文")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(QQPushDelivery.objects.filter(article=self.article).count(), 1)

    def test_translate_news_force_requires_explicit_id_and_sync(self):
        with self.assertRaises(CommandError):
            call_command("translate_news", "--pending", "--sync", "--force", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "translate_news",
                "--article-id",
                str(self.article.id),
                "--force",
                stdout=StringIO(),
            )

    def test_translate_news_force_rejects_missing_explicit_id_before_work(self):
        with patch("stable.tasks.translate_article") as translate:
            with self.assertRaises(CommandError):
                call_command(
                    "translate_news",
                    "--article-id",
                    str(self.article.id),
                    "--article-id",
                    "999999",
                    "--sync",
                    "--force",
                    stdout=StringIO(),
                )

        translate.assert_not_called()

    def test_translate_news_force_treats_skipped_task_as_failure(self):
        self.article.translation_status = ArticleTranslationStatus.TRANSLATING
        self.article.save(update_fields=["translation_status", "updated_at"])

        with self.assertRaises(CommandError):
            call_command(
                "translate_news",
                "--article-id",
                str(self.article.id),
                "--sync",
                "--force",
                stdout=StringIO(),
                stderr=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "人工旧正文")

    @override_settings(AUTOMATION_ENABLED=True)
    def test_force_published_translation_does_not_dispatch_automation(self):
        with patch("stable.tasks.translate_article", return_value=self._result()), patch(
            "stable.tasks.dispatch_task"
        ) as dispatch:
            translate_article_task.run(self.article.id, force=True)

        dispatch.assert_not_called()

    def test_translate_news_force_failure_returns_command_error(self):
        with patch("stable.tasks.translate_article", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaises(CommandError):
                call_command(
                    "translate_news",
                    "--article-id",
                    str(self.article.id),
                    "--sync",
                    "--force",
                    stdout=StringIO(),
                    stderr=StringIO(),
                )

        self.article.refresh_from_db()
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(self.article.body_zh, "人工旧正文")
        self.assertIsNone(self.article.translation_next_retry_at)

    def test_force_translation_failure_keeps_existing_public_copy(self):
        with patch("stable.tasks.translate_article", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaises(RuntimeError):
                translate_article_task.run(self.article.id, force=True)

        self.article.refresh_from_db()
        self.assertEqual(self.article.title_zh, "人工旧标题")
        self.assertEqual(self.article.body_zh, "人工旧正文")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(self.article.published_to_web_at, self.published_to_web_at)
        self.assertEqual(QQPushDelivery.objects.filter(article=self.article).count(), 1)

    def test_force_translation_does_not_consume_automatic_retry_budget(self):
        self.article.translation_status = ArticleTranslationStatus.FAILED
        self.article.translation_retry_count = 2
        self.article.translation_next_retry_at = timezone.now() + timedelta(minutes=10)
        self.article.save(
            update_fields=[
                "translation_status",
                "translation_retry_count",
                "translation_next_retry_at",
                "updated_at",
            ]
        )

        with patch("stable.tasks.translate_article", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaises(RuntimeError):
                translate_article_task.run(self.article.id, force=True)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 2)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
