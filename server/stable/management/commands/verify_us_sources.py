"""只读验收美国来源；完整性不成立时保存报告并非零退出。"""
from datetime import date, datetime
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.us_source_collection import SourceStore, collect_sources, atomic_json


class Command(BaseCommand):
    help = '采集或离线重放美国来源并输出证据；不读写业务数据库'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--start', required=True, type=date.fromisoformat)
        parser.add_argument('--end', required=True, type=date.fromisoformat)
        parser.add_argument('--output-dir', required=True)
        parser.add_argument('--cache-dir')
        parser.add_argument('--allow-network', action='store_true')
        parser.add_argument('--max-requests', type=int, default=80)
        parser.add_argument('--now', type=datetime.fromisoformat, help='仅离线重放时指定带时区的验收时刻')

    def handle(self, **opts):
        if opts['allow_network'] and opts['now']:
            raise CommandError('us_live_timestamp_override_forbidden')
        out = Path(opts['output_dir'])
        try:
            store = SourceStore(opts['cache_dir'] or out/'cache',
                allow_network=opts['allow_network'], now=opts['now'], max_requests=opts['max_requests'])
            report = collect_sources(store,start=opts['start'],end=opts['end'])
        except (ValueError,OSError) as exc:
            raise CommandError(str(exc)) from exc
        atomic_json(out/'report.json',report)
        self.stdout.write(json.dumps(dict(acceptance=report['acceptance'],
            production_ready=report['production_ready'], targets=len(report['targets']),
            documents=len(report['source_documents']), conflicts=len(report['conflicts']),
            errors=len(report['errors']), requests=store.request_count),ensure_ascii=False))
        if report['acceptance'] != 'source_layer_passed':
            raise CommandError('us_source_acceptance_incomplete')
