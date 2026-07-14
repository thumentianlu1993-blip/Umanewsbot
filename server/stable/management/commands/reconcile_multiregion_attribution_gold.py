from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.attribution_gold_reconciliation import reconcile_gold_label_drift


class Command(BaseCommand):
    help = "对账 Gold 审核后正文漂移；仅在身份、标题、正文语义和人工地区结论均稳定时刷新 SHA。"

    def add_arguments(self, parser):
        parser.add_argument("--labels", required=True)
        parser.add_argument("--review-snapshot", required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--minimum-overlap", type=float, default=0.95)
        parser.add_argument("--minimum-body-length", type=int, default=100)
        parser.add_argument("--minimum-length-ratio", type=float, default=0.20)

    def handle(self, *args, **options):
        try:
            summary = reconcile_gold_label_drift(
                labels_path=Path(options["labels"]),
                review_snapshot_path=Path(options["review_snapshot"]),
                output_dir=Path(options["output_dir"]),
                minimum_overlap=options["minimum_overlap"],
                minimum_body_length=options["minimum_body_length"],
                minimum_length_ratio=options["minimum_length_ratio"],
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
