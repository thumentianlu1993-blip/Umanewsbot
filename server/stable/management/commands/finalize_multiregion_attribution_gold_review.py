from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.attribution_gold_review import (
    finalize_gold_review_package,
    finalize_provisional_single_review_package,
)


class Command(BaseCommand):
    help = "合并两份独立标注，生成冲突裁决表或结构合格的 Gold Labels。"

    def add_arguments(self, parser):
        parser.add_argument("--package-dir", required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--adjudication")
        parser.add_argument(
            "--provisional-single-review",
            action="store_true",
            help="显式按单人审核生成标签并保留审核来源；结构与质量达标后仍须通过生产 Shadow。",
        )
        parser.add_argument("--reviewer-file", help="单审模式下的完整 reviewer CSV。")

    def handle(self, *args, **options):
        try:
            if options["provisional_single_review"]:
                if not options.get("reviewer_file"):
                    raise ValueError("单审模式必须提供 --reviewer-file")
                if options.get("adjudication"):
                    raise ValueError("单审模式不接受 --adjudication")
                report = finalize_provisional_single_review_package(
                    package_dir=Path(options["package_dir"]),
                    reviewer_path=Path(options["reviewer_file"]),
                    output_dir=Path(options["output_dir"]),
                )
            else:
                if options.get("reviewer_file"):
                    raise ValueError("--reviewer-file 只能与 --provisional-single-review 一起使用")
                report = finalize_gold_review_package(
                    package_dir=Path(options["package_dir"]),
                    output_dir=Path(options["output_dir"]),
                    adjudication_path=Path(options["adjudication"]) if options.get("adjudication") else None,
                )
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(asdict(report), ensure_ascii=False, indent=2))
