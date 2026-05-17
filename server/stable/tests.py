from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NotificationLog,
    PushTarget,
    ReviewMode,
    SourceMode,
    SourceSite,
    TermEntry,
    WorkflowStatus,
)
from stable.services.pushing import build_push_message, push_article_to_targets
from stable.services.sources import sync_builtin_sources
from stable.services.term_admin import preview_term_import
from stable.services.terms import apply_term_mappings, extract_horse_tags, extract_unknown_horse_names, resolve_terms
from stable.services.text import extract_article_text
from stable.services.translation import (
    OpenAICompatibleTranslationProvider,
    TranslationResponseError,
    translate_article as run_translation_service,
)
from stable.tasks import (
    _crawl_netkeiba_mode,
    auto_publish_batch_task,
    batch_translate_articles_task,
    process_article_automation_task,
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
        self.assertTrue(article.rewrite_body_zh)
        self.assertEqual(article.base_translation_zh, article.translated_body_zh)

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
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes\n"
            "horse,グランアレグリア,放声欢呼,Gran Alegria|グラン,放声欢呼,100,true,\n"
            "race,大阪杯,大阪杯,,大阪杯一级赛,20,true,重要赛事\n"
        )
        preview = preview_term_import(csv_text=csv_text, import_mode="create")
        self.assertEqual(preview["summary"]["total"], 2)
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertTrue(preview["can_commit"])

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
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes\n"
            "horse,グランアレグリア,放声欢呼,Gran Alegria|グラン,放声欢呼,100,true,\n"
            "race,大阪杯,大阪杯,,大阪杯一级赛,20,true,重要赛事\n"
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
        self.assertTrue(TermEntry.objects.filter(source_ja="大阪杯").exists())

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
