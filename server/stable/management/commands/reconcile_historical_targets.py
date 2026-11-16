"""执行固定 SHA 的历史目录收口清单。"""
import json
from django.core.management.base import BaseCommand, CommandError
from stable.services.historical_target_reconciliation import execute


class Command(BaseCommand):
    help = '核对、应用或恢复已审查的 2025 年历史目录精确清单'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--sha256', required=True)
        parser.add_argument('--mode', choices=['dry-run', 'apply', 'restore'], default='dry-run')

    def handle(self, *args, **options):
        try:
            report = execute(options['manifest'], options['sha256'], mode=options['mode'])
        except (ValueError, KeyError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False))
