import json
from django.core.management.base import BaseCommand, CommandError
from stable.services.historical_empty_race_repair import execute


class Command(BaseCommand):
    help = '按冻结清单修正历史取消赛事及补入空表赛果；默认只读核验，支持条件回滚'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--expected-sha256', required=True)
        parser.add_argument('--mode', choices=['dry-run', 'apply', 'restore'], default='dry-run')

    def handle(self, *args, **options):
        try:
            report = execute(options['manifest'], options['expected_sha256'], mode=options['mode'])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(report, ensure_ascii=False))
