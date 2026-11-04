from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.article_entity_reprocessing import reprocess_article_entities
from stable.services import article_entity_reprocessing as binding_diagnostics


class Command(BaseCommand):
    help = "按显式文章 ID 重算上下文实体、机器马名标签与自动马匹关联；默认 dry-run。"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--binding-diagnostics", action="store_true")
        parser.add_argument("--binding-input", default=None)
        parser.add_argument("--article-id", action="append", type=int, dest="article_ids")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--translate-sync", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        article_ids = options.get("article_ids") or []
        diagnostic = bool(options.get("binding_diagnostics"))
        binding_input = options.get("binding_input")
        if diagnostic or binding_input is not None:
            try:
                if not diagnostic or options.get("commit") or options.get("translate_sync"):
                    binding_diagnostics._bd_fail("invalid_flags")
                payload = binding_diagnostics.diagnose_article_entity_bindings(article_ids, binding_input=binding_input)
                if options.get("as_json"):
                    encoded = binding_diagnostics._binding_diagnostic_encode_output(payload, as_json=True, scope="invocation")
                else:
                    summary = "\n".join(f"article={row['article_id']} status={row['status']}" for row in payload["articles"])
                    encoded = binding_diagnostics._binding_diagnostic_encode_output(summary, as_json=False, scope="text")
            except CommandError as error:
                code, failure = binding_diagnostics._binding_diagnostic_error_details(error)
                if options.get("as_json"):
                    encoded = binding_diagnostics._binding_diagnostic_encode_output(failure, as_json=True, scope="error")
                    self.stdout.write(encoded.decode("utf-8"), ending="")
                raise CommandError(code) from None
            self.stdout.write(encoded.decode("utf-8"), ending="")
            return
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
