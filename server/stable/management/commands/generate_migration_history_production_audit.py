from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_schema import (
    capture_reviewed_production_audit,
)


class Command(BaseCommand):
    help = "只读生成 migration-history repair production audit baseline。"

    def handle(self, *args, **options):
        try:
            payload = capture_reviewed_production_audit()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
