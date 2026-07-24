from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.news_body_history import (
    _COHORT_SOURCE_SITE,
    _MAX_INVENTORY_PAGE,
    CohortDriftError,
    generate_inventory,
)


class Command(BaseCommand):
    help = (
        "对冻结 HRN cohort 生成只读总账 inventory，"
        "不发网络请求、不写数据库。"
        "可选 --expected-count 和 --expected-id-set-sha256 用于 cohort 漂移检测。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--source-site", default=_COHORT_SOURCE_SITE)
        parser.add_argument("--max-id", type=int, required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--revision", default="")
        parser.add_argument("--page-size", type=int, default=_MAX_INVENTORY_PAGE)
        parser.add_argument("--expected-count", type=int)
        parser.add_argument("--expected-id-set-sha256")

    def handle(self, *args, **options):
        source_site = options["source_site"]
        max_id = options["max_id"]
        output_dir = Path(options["output_dir"])
        revision = options["revision"]
        page_size = options["page_size"]
        expected_count = options.get("expected_count")
        expected_id_set_sha256 = options.get("expected_id_set_sha256")

        if source_site != _COHORT_SOURCE_SITE:
            raise CommandError(f"只支持 {_COHORT_SOURCE_SITE} 的历史正文盘点")
        if max_id < 1:
            raise CommandError("--max-id 必须 >= 1")
        if not (1 <= page_size <= _MAX_INVENTORY_PAGE):
            raise CommandError(f"--page-size 必须在 1..{_MAX_INVENTORY_PAGE} 之间")
        if expected_count is not None and expected_count < 0:
            raise CommandError("--expected-count 必须 >= 0")

        try:
            result = generate_inventory(
                source_site=source_site,
                max_id=max_id,
                output_dir=output_dir,
                revision=revision,
                page_size=page_size,
                expected_count=expected_count,
                expected_id_set_sha256=expected_id_set_sha256,
            )
        except CohortDriftError as exc:
            raise CommandError(f"cohort 漂移: {exc}") from exc

        self.stdout.write(
            json.dumps(
                {
                    "status": "ok",
                    "cohort_count": result["cohort"].count,
                    "counts": result["counts"],
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
