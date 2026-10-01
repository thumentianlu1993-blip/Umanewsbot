import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from stable.services.race_public_coverage import build_public_race_coverage


class Command(BaseCommand):
    help = (
        "只读输出全部公开主赛事的覆盖分类、缺口及下一步；不抓取、不落告警、不写比赛。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--event-id", type=int, action="append")
        parser.add_argument("--summary", action="store_true")

    def handle(self, *args, **options):
        report = build_public_race_coverage(
            now=timezone.now(), event_ids=options["event_id"]
        )
        if options["summary"]:
            report.pop("entries")
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
