"""验证人工原件并生成可绑定的本地年度目录，不联网、不访问数据库。"""
import hashlib
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from stable.services.us_calendar_snapshot import prepare_snapshot


class Command(BaseCommand):
    help = '离线准备 TOBA 年度目录快照（输出目录必须不存在）'

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--captured-at', required=True)

    def handle(self, *args, **options):
        try:
            prepare_snapshot(options['input'], options['output'], year=options['year'],
                captured_at=datetime.fromisoformat(options['captured_at']), now=timezone.now())
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        path = Path(options['output'])/'index.json'
        self.stdout.write(f'{path}\nSHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}')
