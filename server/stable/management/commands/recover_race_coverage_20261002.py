import json
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from stable.services.race_coverage_recovery import (
    verify_package,
    recover_events,
    RecoveryBlocked,
)


class Command(BaseCommand):
    help = "仅恢复固定七场历史赛事；默认 dry-run，本地证据校验，不访问网络"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--sha256", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            payloads = verify_package(
                manifest_path=options["manifest"], expected_sha256=options["sha256"]
            )
            result = recover_events(
                payloads=payloads,
                manifest_sha256=options["sha256"],
                now=timezone.now(),
                apply=options["apply"],
            )
        except (RecoveryBlocked, OSError, KeyError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
