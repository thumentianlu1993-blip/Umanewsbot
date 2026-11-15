"""T21：五地区历史工具有界清单，不允许绕过新稿不可变合同。"""
from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from stable.models import NewsArticle
from stable.services.news_body_history import build_inventory_row, compute_before_fingerprint, validate_approved_decisions
from stable.test_news_body_history import _make_approved_manifest, _apply_flow, VALID_SHA


class HistoryScopeTests(TestCase):
    def article(self, source="jra", **extra):
        return NewsArticle.objects.create(source_site=source, source_mode="official", source_article_id="fixture-history",
            title_ja="原文标题", published_at=timezone.now(), source_url="https://fixture.invalid/news/1",
            original_content_html='<div class="news_body"><p>正文 27。</p><blockquote>完整引语。</blockquote></div>',
            body_ja_raw="旧模板污染正文", body_ja_normalized="旧模板污染正文", translated_body_zh="旧译", body_zh="旧译", translation_status="translated", **extra)

    def decision(self, article):
        return {"article_id": article.pk, "decision": "approve_fields", "reviewer": "fixture-human", "reason": "已核对正文污染",
            "before_fingerprint": compute_before_fingerprint(article), "approved_fields": ["translated_body_zh", "body_zh"],
            "exact_output": {"translated_body_zh": "修正全文", "body_zh": "修正全文"}}

    def test_jra_cached_html_inventory_is_supported_without_network(self):
        article = self.article()
        row = build_inventory_row(article)
        self.assertEqual(row.body_parse_status, "ok")
        with TemporaryDirectory() as temp:
            call_command("inventory_news_body_history", source_site="jra", max_id=article.pk, output_dir=temp, stdout=StringIO())
            self.assertTrue(Path(temp, "inventory.jsonl").exists())

    def test_non_manifest_source_cannot_be_written(self):
        article = self.article()
        manifest = _make_approved_manifest([self.decision(article)])
        # 旧清单缺 source_sites 时仅承接既有 HRN 范围，不隐式扩至日本。
        with TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, "source|来源"):
            _apply_flow(article, manifest, Path(temp))
        article.refresh_from_db()
        self.assertEqual(article.body_zh, "旧译")

    def test_full_body_update_cannot_leave_old_rewrite_covering_new_text(self):
        article = self.article(rewrite_body_zh="旧的截短改写")
        decision = self.decision(article)
        manifest = _make_approved_manifest([decision])
        manifest["source_sites"] = ["jra"]
        errors = validate_approved_decisions(manifest, candidate_manifest_sha256=VALID_SHA)
        self.assertTrue(any("rewrite_body_zh" in error for error in errors), errors)

    def test_explicit_source_full_text_apply_preserves_publication_time(self):
        published = timezone.now()
        article = self.article(workflow_status="published", published_to_web_at=published)
        manifest = _make_approved_manifest([self.decision(article)])
        manifest["source_sites"] = ["jra"]
        with TemporaryDirectory() as temp:
            _apply_flow(article, manifest, Path(temp))
        article.refresh_from_db()
        self.assertEqual(article.body_zh, "修正全文")
        self.assertEqual(article.published_to_web_at, published)
