"""只读来源验收：以官方赛季 PDF 生成窗口，逐场发现并获取来源。"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from django.core.management.base import BaseCommand, CommandError
from stable.services.hkjc_sources import parse_pattern_schedule, discover_result_url
from stable.services.hkjc_pre_race import fetch_hkjc_pre_race
from stable.services.race_data_source_adapters import SourceRoute, parse_hkjc_observation


class Command(BaseCommand):
    help='验收 HKJC 官方来源并输出本地证据，不读取或修改业务数据库'
    requires_system_checks=[]

    def add_arguments(self,parser):
        parser.add_argument('--start',required=True,type=date.fromisoformat)
        parser.add_argument('--end',required=True,type=date.fromisoformat)
        parser.add_argument('--pattern-pdf',required=True)
        parser.add_argument('--output-dir',required=True)
        parser.add_argument('--campaign-url',action='append',default=[])
        parser.add_argument('--allow-network',action='store_true')
        parser.add_argument('--now',type=datetime.fromisoformat)

    def handle(self,**opts):
        import requests
        now=opts['now'] or datetime.now(timezone.utc)
        if now.tzinfo is None or opts['start']>opts['end']:raise CommandError('invalid_date_window')
        out=Path(opts['output_dir']);out.mkdir(parents=True,exist_ok=True)
        pdf=Path(opts['pattern_pdf']).read_bytes();schedule=parse_pattern_schedule(pdf)
        targets=[r for r in schedule if r['grade'] in {'G1','G2','G3'} and opts['start']<=date.fromisoformat(r['local_date'])<=opts['end']]
        if not targets:raise CommandError('empty_schedule_window')
        route=SourceRoute(dict(provider='hkjc',operator='hkjc',region='hong_kong',identity_namespace='hkjc-race-v1',
            allowed_hosts=['racing.hkjc.com','campaigns.hkjc.com'],allowed_path_prefixes=['/en-us/local/information/','/racing-event-hub-'],
            venue_aliases={'hkjc:ST':['Sha Tin','沙田'],'hkjc:HV':['Happy Valley','跑马地']},
            timezone='Asia/Hong_Kong',parser_version='hkjc-official-v1',
            discovery_urls=opts['campaign_url'],valid_from=(now-timedelta(days=1)).isoformat(),valid_until=(now+timedelta(days=1)).isoformat()),'source-acceptance')
        cache={};receipts=[]
        def fetch(url,**kwargs):
            if url in cache:return cache[url]
            if not route.permits_url(url):raise ValueError('source_url_rejected')
            key=hashlib.sha256(url.encode()).hexdigest();path=out/(key+'.html')
            if opts['allow_network']:
                with requests.get(url,timeout=(10,30),allow_redirects=False,stream=True) as response:
                    response.raise_for_status()
                    if response.status_code!=200:raise ValueError('source_http_not_200')
                    raw=b''
                    for chunk in response.iter_content(65536):
                        raw+=chunk
                        if len(raw)>8*1024*1024:raise ValueError('source_too_large')
                path.write_bytes(raw)
            elif path.exists():raw=path.read_bytes()
            else:raise ValueError('offline_cache_missing')
            from stable.services.race_pre_race import JraPage
            page=JraPage(raw.decode('utf-8-sig'),hashlib.sha256(raw).hexdigest(),observed_at=now)
            receipts.append(dict(url=url,sha256=page.raw_sha256,bytes=len(raw),file=path.name));cache[url]=page
            return page
        rows=[]
        for target in targets:
            event=SimpleNamespace(local_date=date.fromisoformat(target['local_date']),original_name=target['name'],
                chinese_name='',racecourse=target['racecourse'])
            record=dict(target)
            try:
                if event.local_date<now.astimezone(__import__('zoneinfo').ZoneInfo(route.timezone)).date():
                    url=discover_result_url(event=event,route=route,now=now,fetcher=fetch)
                    obs=parse_hkjc_observation(fetch(url),url=url,route=route,now=now)
                    if not obs.get('roster_evidence'):raise ValueError('independent_roster_missing')
                    record.update(status='complete_result',url=url,count=len(obs['roster']),observation=obs)
                else:
                    url,page,payload=fetch_hkjc_pre_race(event=event,route=route,now=now,fetcher=fetch)
                    record.update(status=payload['stage'],url=url,count=len(payload['items']),payload=payload)
            except (ValueError,OSError,requests.RequestException) as exc:record.update(status='error',reason=str(exc))
            rows.append(record)
        report=dict(as_of=now.isoformat(),start=opts['start'].isoformat(),end=opts['end'].isoformat(),
            pattern_sha256=hashlib.sha256(pdf).hexdigest(),season_count=len(schedule),targets=rows,receipts=receipts)
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        self.stdout.write(json.dumps({k:report[k] for k in ('as_of','start','end','season_count')},ensure_ascii=False))
        for row in rows:self.stdout.write(json.dumps({k:v for k,v in row.items() if k not in {'payload','observation'}},ensure_ascii=False))
        if any(r['status']=='error' for r in rows):raise CommandError('source_acceptance_incomplete')
