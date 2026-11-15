"""显式固定页清单的旧稿索引；默认 prepare，不迁移或重发新闻。"""
import hashlib
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from stable.models import NewsArticle
from stable.services.news_pipeline import article_revision
from stable.services.news_feed import publication_lock, index_legacy_article


class Command(BaseCommand):
    help = "准备或应用最多500篇旧公开稿的固定索引清单；生产动作由发布包绑定。"

    def add_arguments(self, parser):
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--max-id", type=int)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--manifest")
        parser.add_argument("--manifest-sha256")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--output")

    def handle(self, *args, **options):
        if options["apply"]:
            if not options["manifest"] or not options["manifest_sha256"]:
                raise CommandError("apply 必须提供固定 manifest 及 SHA-256")
            if not (getattr(settings, "NEWS_QUALITY_INDEX_ENABLED", False) or getattr(settings, "NEWS_QUALITY_FEED_ENABLED", False)):
                raise CommandError("索引维护尚未启用")
            raw = Path(options["manifest"]).read_bytes()
            if len(raw)>1000000 or hashlib.sha256(raw).hexdigest() != options["manifest_sha256"]:
                raise CommandError("manifest SHA-256 不匹配或超限")
            manifest = json.loads(raw)
            rows = manifest.get("entries", [])
            if manifest.get("schema") != "p01-legacy-index-v1" or not 1 <= len(rows) <= 500:
                raise CommandError("manifest 范围无效")
            ids = [row["article_id"] for row in rows]
            if len(ids) != len(set(ids)):
                raise CommandError("manifest 编号重复")
            with transaction.atomic():
                publication_lock()
                articles = list(NewsArticle.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
                if len(articles) != len(ids):
                    raise CommandError("文章集合发生变化")
                expected = {row["article_id"]: row["revision_sha"] for row in rows}
                for article in articles:
                    if article.active_news_run_id or article.workflow_status != "published" or not article.published_to_web_at or article_revision(article) != expected[article.pk]:
                        raise CommandError(f"文章 {article.pk} 状态已变化，停止整页应用")
                entries = [index_legacy_article(article).pk for article in articles]
            result = {"status": "indexed", "manifest_sha256": options["manifest_sha256"], "entries": entries}
        else:
            if not options["max_id"] or not 1 <= options["limit"] <= 500 or options["after_id"] < 0:
                raise CommandError("prepare 必须提供正数 max-id，limit 为1..500")
            articles = list(NewsArticle.objects.filter(pk__gt=options["after_id"], pk__lte=options["max_id"],
                active_news_run__isnull=True, workflow_status="published", published_to_web_at__isnull=False).order_by("pk")[:options["limit"]])
            result = {"schema": "p01-legacy-index-v1", "max_id": options["max_id"],
                "next_after_id": articles[-1].pk if articles else options["after_id"],
                "entries": [{"article_id": article.pk, "revision_sha": article_revision(article)} for article in articles]}
        text = json.dumps(result, ensure_ascii=False, indent=2)+"\n"
        if options["output"]:
            with Path(options["output"]).open("x", encoding="utf-8") as stream:
                stream.write(text)
        else:
            self.stdout.write(text)
