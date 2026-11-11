"""美国发布前来源、赛前覆盖与只读身份对账。"""
from datetime import date, datetime
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.us_prerelease_collection import PrereleaseStore, collect_nsa, collect_prerace
from stable.services.us_race_inventory import reconcile_inventory
from stable.services.us_racing_sources import parse_toba_calendar
from stable.services.us_source_collection import atomic_json


class Command(BaseCommand):
    help = '默认离线生成美国障碍全场结果、赛前覆盖和生产快照对账；不连接业务数据库'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--start',required=True,type=date.fromisoformat)
        parser.add_argument('--end',required=True,type=date.fromisoformat)
        parser.add_argument('--cache-dir',required=True)
        parser.add_argument('--output-dir',required=True)
        parser.add_argument('--flat-report',required=True)
        parser.add_argument('--events-snapshot',required=True,help='只读导出的 JSON，events 字段为赛事数组')
        parser.add_argument('--reviewed-aliases',required=True)
        parser.add_argument('--allow-network',action='store_true')
        parser.add_argument('--reuse-cache',action='store_true')
        parser.add_argument('--max-requests',type=int,default=80)
        parser.add_argument('--now',type=datetime.fromisoformat)

    def handle(self, **opts):
        if opts['allow_network'] and opts['now']:
            raise CommandError('us_live_timestamp_override_forbidden')
        try:
            inputs={k:Path(opts[k]).read_bytes() for k in ('flat_report','events_snapshot','reviewed_aliases')}
            flat,snapshot,aliases=(json.loads(inputs[k]) for k in ('flat_report','events_snapshot','reviewed_aliases'))
            store=PrereleaseStore(opts['cache_dir'],allow_network=opts['allow_network'],reuse_cache=opts['reuse_cache'],
                max_requests=opts['max_requests'],now=opts['now'])
            nsa=collect_nsa(store,start=opts['start'],end=opts['end'])
            calendar={'items':[],'unresolved':[],'conflicts':[]}
            for year in range(opts['start'].year,opts['end'].year+1):
                url=f'https://toba.org/graded-stakes/{year}-races/'
                doc=store.get(url);parsed=parse_toba_calendar(doc['body'],url=url);store.accept(doc)
                for key in calendar:calendar[key].extend(parsed[key])
            inventory=reconcile_inventory(calendar,nsa['targets'],snapshot['events'],
                start=opts['start'].isoformat(),end=opts['end'].isoformat(),reviewed_aliases=aliases)
            prerace=collect_prerace(store,start=opts['start'],end=opts['end'],flat_report=flat)
            report=dict(schema_version=1,as_of=store.now.isoformat(),start=opts['start'].isoformat(),end=opts['end'].isoformat(),
                input_sha256={k:hashlib.sha256(v).hexdigest() for k,v in inputs.items()},
                inventory=inventory,nsa=nsa,prerace=prerace,network_requests=store.request_count,
                production_ready=False,acceptance='coverage_gaps' if nsa['errors'] else prerace['acceptance'])
        except (ValueError,KeyError,TypeError,OSError) as exc:
            raise CommandError(str(exc)) from exc
        atomic_json(Path(opts['output_dir'])/'report.json',report)
        self.stdout.write(json.dumps(dict(acceptance=report['acceptance'],inventory=inventory['target_count'],nsa=nsa['source_counts'],prerace=prerace['counts'],network_requests=store.request_count),ensure_ascii=False))
        if report['acceptance']=='coverage_gaps':
            raise CommandError('us_prerelease_incomplete')
