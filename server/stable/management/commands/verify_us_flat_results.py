"""美国平地赛果来源验收，不读写业务数据库。"""
from datetime import date, datetime
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from stable.services.us_flat_collection import FlatSourceStore, collect_flat_results
from stable.services.us_source_collection import atomic_json


class Command(BaseCommand):
    help = '自动发现、采集或默认离线重放美国平地完整赛果'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--start', required=True, type=date.fromisoformat)
        parser.add_argument('--end', required=True, type=date.fromisoformat)
        parser.add_argument('--output-dir', required=True)
        parser.add_argument('--cache-dir', required=True)
        parser.add_argument('--program-sources', help='chart URL 到补马号出马表 URL 的 JSON 字典')
        parser.add_argument('--allow-network', action='store_true')
        parser.add_argument('--reuse-cache', action='store_true', help='有界续传；保留旧原件抓取时刻')
        parser.add_argument('--max-requests', type=int, default=80)
        parser.add_argument('--now', type=datetime.fromisoformat, help='仅离线重放的带时区验收时刻')

    def handle(self, **opts):
        if opts['allow_network'] and opts['now']:
            raise CommandError('us_live_timestamp_override_forbidden')
        try:
            programs = json.loads(Path(opts['program_sources']).read_text()) if opts['program_sources'] else {}
            if not isinstance(programs, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k,v in programs.items()):
                raise ValueError('us_program_sources_schema')
            store = FlatSourceStore(opts['cache_dir'], allow_network=opts['allow_network'],
                reuse_cache=opts['reuse_cache'], now=opts['now'], max_requests=opts['max_requests'])
            report = collect_flat_results(store, start=opts['start'], end=opts['end'], program_sources=programs)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        atomic_json(Path(opts['output_dir'])/'report.json', report)
        self.stdout.write(json.dumps({k:report[k] for k in ('acceptance','targets','runner_count','scratch_count','network_requests')},ensure_ascii=False))
        if report['acceptance'] != 'result_source_passed':
            raise CommandError('us_flat_result_incomplete')
