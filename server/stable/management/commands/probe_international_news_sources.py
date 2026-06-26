from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.adapters.international import (
    FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS,
    FIRST_VERSION_INTERNATIONAL_PROBES,
    INTERNATIONAL_ADAPTERS,
)
from stable.models import SourceMode


class Command(BaseCommand):
    help = "Dry-run probe international news adapters without writing articles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            action="append",
            choices=sorted(INTERNATIONAL_ADAPTERS.keys()),
            help="只探测指定来源；可重复传入。默认探测第一版最终国际来源。",
        )
        parser.add_argument(
            "--mode",
            choices=[SourceMode.LATEST, SourceMode.ACCESS, SourceMode.ATTENTION, SourceMode.OFFICIAL],
            help="探测指定来源模式；不传时按第一版来源矩阵使用各自默认/榜单 mode。",
        )
        parser.add_argument("--limit", type=int, default=2, help="每个来源解析的真实新闻数量，默认 2。")
        parser.add_argument("--json", action="store_true", help="以 JSON 输出探测结果。")

    def handle(self, *args, **options):
        limit = max(1, options["limit"])
        requested_mode = options.get("mode")
        if options.get("source"):
            probe_targets = []
            for key in options["source"]:
                adapter_cls = INTERNATIONAL_ADAPTERS.get(key)
                if adapter_cls is None:
                    raise CommandError(f"Unknown source: {key}")
                mode = requested_mode or adapter_cls.source_mode
                probe_targets.append((key, mode))
        elif requested_mode:
            probe_targets = [(key, requested_mode) for key in FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS]
        else:
            probe_targets = list(FIRST_VERSION_INTERNATIONAL_PROBES)
        results = []
        for key, mode in probe_targets:
            adapter_cls = INTERNATIONAL_ADAPTERS.get(key)
            if adapter_cls is None:
                raise CommandError(f"Unknown source: {key}")
            adapter = adapter_cls()
            source_result = {
                "source": key,
                "region": adapter.racing_region,
                "source_language": adapter.source_language,
                "source_mode": mode,
                "listing_url": adapter.listing_url(1, mode=mode),
                "articles": [],
                "error": "",
            }
            try:
                stubs = adapter.fetch_listing(mode, 1)[:limit]
                for stub in stubs:
                    detail = adapter.fetch_detail(stub.source_url)
                    published_at = detail.published_at or stub.published_at
                    source_result["articles"].append(
                        {
                            "title": detail.title_ja or stub.title_ja,
                            "url": stub.source_url,
                            "published_at": published_at.isoformat() if published_at else "",
                            "body_length": len(detail.body_ja_normalized or detail.body_ja_raw or ""),
                            "has_html": bool(detail.original_content_html),
                            "rank": stub.rank,
                        }
                    )
            except Exception as exc:  # pragma: no cover - live network probe.
                source_result["error"] = str(exc)
            results.append(source_result)

        if options["json"]:
            self.stdout.write(json.dumps(results, ensure_ascii=False, indent=2))
            return

        for item in results:
            self.stdout.write(
                f"[{item['source']}] {item['region']} / {item['source_language']} / {item['source_mode']} / {item['listing_url']}"
            )
            if item["error"]:
                self.stdout.write(f"  ERROR: {item['error']}")
                continue
            for article in item["articles"]:
                rank_text = f"rank={article['rank']} | " if article.get("rank") else ""
                self.stdout.write(f"  - {rank_text}{article['title']} | body={article['body_length']} | {article['url']}")
