"""离线容量清单报告，不抓取、不写库、不授予网络权限。"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from stable.services.race_lifecycle_projection import source_capacity_report


class Command(BaseCommand):
    help = "检查固定 SHA 的 P02 来源五类能力和全部追踪库存容量"

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--sha256', required=True)

    def handle(self, *args, **options):
        raw = Path(options['manifest']).read_bytes()
        if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != options['sha256']:
            raise CommandError('capacity_manifest_digest')
        try:
            value = json.loads(raw)
            report = source_capacity_report(targets=value['targets'], proofs=value['proofs'], budgets=value['budgets'])
        except (ValueError, KeyError, TypeError) as exc:
            raise CommandError('capacity_manifest_invalid') from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
