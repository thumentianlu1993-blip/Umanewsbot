from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from stable.services.scheduled_race_result_review import run_scheduled_prepare


class Command(BaseCommand):
    help = "准备并投递最近赛事赛果审核包；绝不执行 apply。"

    def add_arguments(self, parser):
        parser.add_argument("--schedule-slot")

    def handle(self, *args, **options):
        slot = None
        if options["schedule_slot"]:
            slot = parse_datetime(options["schedule_slot"])
            if slot is None or slot.tzinfo is None:
                raise CommandError("--schedule-slot 必须是带时区 ISO datetime")
        result = run_scheduled_prepare(schedule_slot=slot)
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))

