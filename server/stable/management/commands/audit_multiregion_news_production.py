from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.multiregion import summarize_multiregion_news_production


class Command(BaseCommand):
    help = "只读审计多地区新闻生产、发布、QQ 交付和术语运营状态。"

    def add_arguments(self, parser):
        parser.add_argument("--output", help="可选 runtime/ 下 JSON 输出路径")

    def handle(self, *args, **options):
        payload = summarize_multiregion_news_production()
        output = options.get("output")
        if output:
            path = Path(output)
            if not path.is_absolute():
                path = Path("runtime") / path
            if "runtime" not in path.parts:
                raise CommandError("--output must point under runtime/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            payload["output_path"] = str(path)
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

