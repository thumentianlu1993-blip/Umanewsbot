"""只读展示差异，不包含 apply；离线模式不访问数据库。"""
import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from stable.models import RaceEvent, HorseRaceRecord
from stable.services.race_information_display import event_fields, horse_record_fields, prepare_context
from stable.services.race_field_normalization import RACE_INFORMATION_DISPLAY_VERSION


@contextmanager
def read_only_database(alias):
    connection = connections[alias]
    if connection.vendor == 'postgresql':
        with transaction.atomic(using=alias):
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            yield
    elif connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA query_only')
            previous = cursor.fetchone()[0]
            cursor.execute('PRAGMA query_only=ON')
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'PRAGMA query_only={int(previous)}')
    else:
        raise CommandError('不支持该数据库的只读会话保护')


class Command(BaseCommand):
    help = '预览赛事信息归一化差异；离线JSONL或显式范围的只读数据库扫描，不回写'

    def add_arguments(self, parser):
        parser.add_argument('--input', help='离线JSONL文件，最多每行64KiB')
        parser.add_argument('--from-db', action='store_true')
        parser.add_argument('--database', choices=['default'], help='必须显式选择；默认连接应由操作者配置为只读账户')
        parser.add_argument('--model', choices=['event', 'horse_record'], default='event')
        parser.add_argument('--region')
        parser.add_argument('--year', type=int)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--limit', type=int, default=200)
        parser.add_argument('--output', required=True, help='新报告目录，拒绝覆盖')
        parser.add_argument('--code-sha', required=True, help='运行代码的固定40位Git SHA')

    def handle(self, *args, **options):
        import re
        if bool(options['input']) == bool(options['from_db']):
            raise CommandError('必须且只能指定 --input 或 --from-db')
        if not 1 <= options['limit'] <= 10000 or options['after_id'] < 0:
            raise CommandError('limit须为1至10000，after-id不得为负')
        if not re.fullmatch(r'[0-9a-f]{40}', options['code_sha']):
            raise CommandError('code-sha必须为固定40位Git SHA')
        if options['from_db'] and (not options['database'] or not options['region'] or not options['year']):
            raise CommandError('库内扫描必须显式指定 --database --region --year')
        output = Path(options['output'])
        try:
            output.mkdir(parents=True, exist_ok=False, mode=0o700)
        except FileExistsError as exc:
            raise CommandError('报告目录已存在，拒绝覆盖') from exc
        summary = {'version': RACE_INFORMATION_DISPLAY_VERSION, 'code_sha': options['code_sha'],
                   'implementation_sha256': hashlib.sha256((Path(__file__).read_bytes() + Path(__file__).parents[2].joinpath('services/race_information_display.py').read_bytes() + Path(__file__).parents[2].joinpath('services/race_field_normalization.py').read_bytes() + Path(__file__).parents[2].joinpath('services/race_term_display.py').read_bytes())).hexdigest(),
                   'started_at': datetime.now(timezone.utc).isoformat(), 'completed': False,
                   'model': options['model'], 'region': options['region'], 'year': options['year'],
                   'after_id': options['after_id'], 'limit': options['limit'], 'rows': 0,
                   'consistent_snapshot': False, 'database_writes': 0, 'field_counts': {}, 'last_pk': options['after_id']}
        counts = {}
        def redact(text):
            def clean_url(match):
                try:
                    parsed = urlsplit(match[0])
                    # 去除userinfo、query和fragment；保留非敏感host/path作定位。
                    netloc = parsed.netloc.rsplit('@', 1)[-1]
                    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path,
                                       '[redacted]' if parsed.query or parsed.fragment else '', ''))
                except ValueError:
                    return '[redacted-url]'
            return re.sub(r'https?://[^\s]+', clean_url, text, flags=re.I)[:512]

        mapping = {'position': 'finish_position', 'date': 'race_date' if options['model'] == 'horse_record' else 'local_date', 'grade': 'grade_text', 'distance': 'distance_text', 'name': 'chinese_name', 'racecourse': 'racecourse',
                   'surface': 'surface', 'eligibility': 'eligibility_text', 'weight': 'carried_weight',
                   'finish_time': 'finish_time', 'margin': 'margin', 'odds': 'odds_value', 'popularity': 'popularity'}
        def write_row(handle, record, fields):
            changes = {}
            for key, field in fields.items():
                counts.setdefault(key, Counter())[field.state] += 1
                # 只输出所选字段原值，绝不dump整个raw_payload/source_refs。
                raw = record.get(mapping.get(key, key), '')
                if key == 'name':
                    raw = record.get('chinese_name') or record.get('race_name') or record.get('original_name') or ''
                if hasattr(raw, 'isoformat'):
                    raw = raw.isoformat()
                if isinstance(raw, str):
                    raw = redact(raw)
                elif not isinstance(raw, (int, float, bool, type(None))):
                    raw = '[non_scalar]'
                changes[key] = {'raw': raw, 'display': redact(field.text), 'state': field.state,
                                'reason': field.reason_code, 'input_sha256': field.input_sha256}
            row = {'pk': record.get('id'), 'fields': changes}
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            summary['rows'] += 1
            summary['last_pk'] = record.get('id', summary['last_pk'])
        try:
            with (output / 'diff.jsonl').open('x', encoding='utf-8') as handle:
                if options['input']:
                    source_path = Path(options['input'])
                    digest = hashlib.sha256()
                    previous = options['after_id']
                    with source_path.open('rb') as source:
                        while summary['rows'] < options['limit']:
                            line = source.readline(65537)
                            if not line:
                                break
                            if len(line) > 65536:
                                raise CommandError('输入行超过64KiB')
                            digest.update(line)
                            record = json.loads(line)
                            if not isinstance(record, dict) or type(record.get('id')) is not int:
                                raise CommandError('每行必须为包含整数id的对象')
                            if record['id'] <= options['after_id']:
                                continue
                            if record['id'] <= previous:
                                raise CommandError('离线输入必须按id严格递增')
                            previous = record['id']
                            fields = horse_record_fields(record) if options['model'] == 'horse_record' else event_fields(record)
                            write_row(handle, record, fields)
                    summary['input_prefix_sha256'] = digest.hexdigest()
                    summary['term_resolution'] = 'offline_not_loaded'
                else:
                    model = RaceEvent if options['model'] == 'event' else HorseRaceRecord
                    region_field, year_field = ('country_region', 'year') if model is RaceEvent else ('race_region', 'race_year')
                    remaining = options['limit']
                    with read_only_database(options['database']):
                        while remaining:
                            queryset = model.objects.using(options['database'])
                            if model is HorseRaceRecord:
                                queryset = queryset.select_related('event', 'result')
                            batch = list(queryset.filter(
                                **{region_field: options['region'], year_field: options['year'], 'pk__gt': summary['last_pk']}
                            ).order_by('pk')[:min(remaining, 200)])
                            if not batch:
                                break
                            prepare_context({'focus_events' if model is RaceEvent else 'race_records': batch}, force=True)
                            for obj in batch:
                                record = {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields
                                          if f.attname not in {'raw_payload', 'source_refs'}}
                                write_row(handle, record, obj.public_display)
                            remaining -= len(batch)
                    summary['term_resolution'] = 'database_batch'
            summary['completed'] = True
        except (ValueError, OSError, TypeError) as exc:
            raise CommandError('输入格式或文件读取失败；不完整报告已保留') from exc
        finally:
            summary['finished_at'] = datetime.now(timezone.utc).isoformat()
            summary['field_counts'] = counts
            (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(f"只读预览完成：{summary['rows']}条；业务写入0；{output}")
