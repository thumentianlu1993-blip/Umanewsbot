from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_schema import (
    database_vendor_contract,
)


class Command(BaseCommand):
    help = "只读确认生产 release task 连接的是 PostgreSQL。"

    def handle(self, *args, **options):
        vendor = database_vendor_contract()
        result = {
            "ok": vendor["ok"],
            "database_vendor": vendor,
            "drift_paths": [] if vendor["ok"] else ["database.vendor"],
        }
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result["ok"]:
            raise CommandError("production release requires PostgreSQL")
