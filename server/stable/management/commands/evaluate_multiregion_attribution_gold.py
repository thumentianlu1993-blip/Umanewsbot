from __future__ import annotations

import json
from dataclasses import asdict

from django.core.management.base import BaseCommand

from stable.services.attribution_quality import evaluate_gold_labels_against_database, load_gold_labels


class Command(BaseCommand):
    help = "只读评估版本化多地区 gold labels；不修改文章归属。"

    def add_arguments(self, parser):
        parser.add_argument("--labels", required=True)
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--provisional",
            action="store_true",
            help="允许单审标签进入指标分母；仍须满足全部覆盖与质量门槛。",
        )

    def handle(self, *args, **options):
        labels = load_gold_labels(options["labels"])
        report = evaluate_gold_labels_against_database(labels, allow_provisional=options["provisional"])
        payload = asdict(report)
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return
        self.stdout.write(
            f"labels={report.total_labels} valid={report.valid_denominator} qualified={report.qualified} "
            f"no_go={','.join(report.no_go_reasons) or '-'}"
        )
