from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.article_entity_reprocessing import reprocess_article_entities


class Command(BaseCommand):
    help = "按显式文章 ID 重算上下文实体、机器马名标签与自动马匹关联；默认 dry-run。"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--article-id", action="append", type=int, dest="article_ids")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--translate-sync", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        article_ids = options.get("article_ids") or []
        if not article_ids:
            raise CommandError("必须至少提供一个 --article-id")
        if options.get("translate_sync") and not options.get("commit"):
            raise CommandError("--translate-sync 只能与 --commit 一起使用")
        payload = reprocess_article_entities(
            article_ids,
            commit=bool(options.get("commit")),
            translate_sync=bool(options.get("translate_sync")),
        )
        if options.get("as_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
        else:
            for item in payload["articles"]:
                self.stdout.write(f"article={item['article_id']} status={item['status']}")
