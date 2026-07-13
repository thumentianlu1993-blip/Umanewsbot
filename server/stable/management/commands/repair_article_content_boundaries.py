from __future__ import annotations

import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stable.adapters.international import INTERNATIONAL_ADAPTERS
from stable.models import NewsArticle
from stable.services.operations import log_operation


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = "按显式文章 ID 使用已保存 HTML 离线修复国际新闻正文边界；默认 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--article-id", dest="article_ids", action="append", type=int)
        parser.add_argument("--commit", action="store_true", help="事务写回正文和审计元数据。")

    def handle(self, *args, **options):
        article_ids = list(dict.fromkeys(options.get("article_ids") or []))
        if not article_ids:
            raise CommandError("必须至少提供一个 --article-id")

        commit = bool(options.get("commit"))
        if commit:
            with transaction.atomic():
                articles = list(NewsArticle.objects.select_for_update().filter(pk__in=article_ids).order_by("id"))
                payloads = self._repair_articles(articles, requested_ids=article_ids, commit=True)
        else:
            articles = list(NewsArticle.objects.filter(pk__in=article_ids).order_by("id"))
            payloads = self._repair_articles(articles, requested_ids=article_ids, commit=False)

        self.stdout.write(
            json.dumps(
                {"mode": "commit" if commit else "dry_run", "articles": payloads},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    def _repair_articles(
        self,
        articles: list[NewsArticle],
        *,
        requested_ids: list[int],
        commit: bool,
    ) -> list[dict[str, object]]:
        found_ids = {article.id for article in articles}
        missing_ids = [article_id for article_id in requested_ids if article_id not in found_ids]
        if missing_ids:
            raise CommandError(f"文章不存在: {missing_ids}")

        payloads: list[dict[str, object]] = []
        for article in articles:
            adapter_class = INTERNATIONAL_ADAPTERS.get(article.source_site)
            if adapter_class is None:
                raise CommandError(f"文章 {article.id} 的来源 {article.source_site} 不支持国际正文重解析")
            if not article.original_content_html:
                raise CommandError(f"文章 {article.id} 缺少 original_content_html")

            detail = adapter_class().parse_detail_html(article.original_content_html, url=article.source_url)
            parse_status = detail.metadata.get("body_parse_status")
            if parse_status != "ok" or not detail.body_ja_normalized:
                raise CommandError(f"文章 {article.id} 正文重解析失败: {parse_status or 'unknown'}")

            before_sha = _sha256(article.body_ja_raw)
            after_sha = _sha256(detail.body_ja_raw)
            payload = {
                "article_id": article.id,
                "source_site": article.source_site,
                "body_parse_status": parse_status,
                "body_selector": detail.metadata.get("body_selector", ""),
                "body_cleaning": detail.metadata.get("body_cleaning", {}),
                "before_sha256": before_sha,
                "after_sha256": after_sha,
                "before_length": len(article.body_ja_raw or ""),
                "after_length": len(detail.body_ja_raw or ""),
                "changed": before_sha != after_sha,
            }
            payloads.append(payload)

            if not commit:
                continue

            repair_metadata = {
                **payload,
                "repaired_at": timezone.now().isoformat(),
            }
            article.body_ja_raw = detail.body_ja_raw
            article.body_ja_normalized = detail.body_ja_normalized
            article.translation_metadata = {
                **(article.translation_metadata or {}),
                "body_parse_status": parse_status,
                "body_selector": detail.metadata.get("body_selector", ""),
                "body_cleaning": detail.metadata.get("body_cleaning", {}),
                "content_boundary_repair": repair_metadata,
            }
            article.save(
                update_fields=[
                    "body_ja_raw",
                    "body_ja_normalized",
                    "translation_metadata",
                    "updated_at",
                ]
            )
            log_operation(
                action_type="article_content_boundary_repaired",
                target_type="article",
                target_id=article.id,
                detail=f"离线正文边界修复 {before_sha[:12]} -> {after_sha[:12]}",
            )
        return payloads
