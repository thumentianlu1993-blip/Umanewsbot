"""固定官方证据包修复香港赛事；离线原子回放，默认回滚。"""
import hashlib
import json
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from stable import models
from stable.management.commands.backfill_japan_results import read_artifact, url_key
from stable.services.race_data_source_adapters import (
    canonical_sha, load_multisource_policy, parse_hkjc_observation, run_multisource_claim,
)
from stable.services.race_source_identity import event_snapshot, resolve_observation, normalize_name
from stable.services.race_data_sync_enrollment import attach_multisource_observation, _lock_multisource_event
from stable.services.race_data_sync_control import claim_multisource_events
from stable.services.race_event_public_cache import invalidate_public_race_cache


def snapshot(event):
    def rows(manager):
        return [{k:v for k,v in row.items() if k not in ('created_at','updated_at')}
                for row in manager.order_by('pk').values()]
    basic={k:getattr(event,k) for k in ('status','race_datetime','local_start_time','distance_text',
        'race_series_id','edition_year','manual_lock_flags')}
    refs={k:v for k,v in (event.source_refs or {}).items() if k not in ("pre_race_checks","source_discovery_v2")}
    return canonical_sha(dict(identity=event_snapshot(event),source_refs=refs,basic=json.loads(json.dumps(basic,default=str)),
        runners=json.loads(json.dumps(rows(event.runners),default=str)),
        results=json.loads(json.dumps(rows(event.results),default=str))))


def register_name(event, text, spec):
    series=models.RaceSeries.objects.select_for_update().get(pk=event.race_series_id)
    if (series.country_region!='hong_kong' or series.review_status!='approved' or not series.source_refs
        or any((series.manual_lock_flags or {}).values())):
        raise ValueError('series_not_approved')
    normalized=normalize_name(text)
    names=models.RaceSeriesName.objects.filter(series__country_region='hong_kong',
        normalized_text=normalized,is_active=True).filter(
        Q(valid_from_year=0)|Q(valid_from_year__lte=event.edition_year)).filter(
        Q(valid_to_year=0)|Q(valid_to_year__gte=event.edition_year))
    if names.exclude(series=series).exists():raise ValueError('source_name_conflict')
    if names.filter(series=series).exists():return
    models.RaceSeriesName.objects.create(series=series,text=text,source_language='en',name_type='alias',
        valid_from_year=event.edition_year,valid_to_year=event.edition_year,
        source_refs={'url':spec['url'],'raw_sha256':spec['sha256'],'basis':'hkjc_official_result_header'})


def execute(path, expected_sha256, *, apply=False, now=None):
    path=Path(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();now=now or timezone.now()
    if digest!=expected_sha256:raise ValueError('manifest_digest')
    manifest=json.loads(raw);items=manifest.get('items',[])
    if (manifest.get('schema_version')!=1 or manifest.get('action')!='repair_hkjc_race_fields'
        or not 1<=len(items)<=1000 or len({i['event_id'] for i in items})!=len(items)):
        raise ValueError('manifest_scope')
    policy=load_multisource_policy(now=now)
    if policy.digest!=manifest.get('policy_digest'):raise ValueError('manifest_policy_drift')
    routes=[r for r in policy.routes if r.provider=='hkjc' and r.region=='hong_kong']
    if len(routes)!=1:raise ValueError('hkjc_route_missing')
    route=routes[0];pages={}
    for item in items:
        for kind in ('result','basic_evidence'):
            if kind not in item:continue
            spec=item[kind];_,content=read_artifact(path.parent,spec)
            url=urlsplit(spec['url'])
            if url.scheme!='https' or url.hostname not in ('racing.hkjc.com','campaigns.hkjc.com'):
                raise ValueError('source_origin')
            if kind=='result':pages[url_key(spec['url'])]=content.decode('utf-8')
    def fetch(url,**kwargs):
        try:return pages[url_key(url)]
        except KeyError:raise ValueError('unlisted_page') from None
    with transaction.atomic():
        receipt=models.OperationLog.objects.filter(action_type='hkjc_field_repair',target_type='manifest',target_id=digest).first()
        if receipt:return dict(action='replay',manifest_sha256=digest,events=json.loads(receipt.detail)['events'])
        locked={}
        for item in sorted(items,key=lambda i:i['event_id']):
            event,lifecycle=_lock_multisource_event(item['event_id']);locked[event.pk]=event
            if event.country_region!='hong_kong' or snapshot(event)!=item['baseline_sha256']:
                raise ValueError('event_baseline_drift')
            if (event.status in ('cancelled','postponed') or any((event.manual_lock_flags or {}).values())
                or event.field_authorities.filter(manual_lock=True).exists()
                or (lifecycle and lifecycle.manual_pause_reason)):
                raise ValueError('event_locked')
            if models.RaceDataSyncEnrollment.objects.filter(event=event).exists():
                raise ValueError('event_already_enrolled')
            if any(r.horse_p0_sources.exists() or r.horse_records.exists() for r in event.results.all()):
                raise ValueError('legacy_result_has_dependents')
            if any(any((r.manual_lock_flags or {}).values()) for r in event.runners.all()):
                raise ValueError('row_locked')
        report=[]
        for item in items:
            event=locked[item['event_id']]
            basic=item.get('basic',{})
            if set(basic)-{'local_start_time','distance_text'}:raise ValueError('basic_scope')
            if basic:
                if 'basic_evidence' not in item:raise ValueError('basic_evidence_missing')
                if 'local_start_time' in basic:
                    clock=time.fromisoformat(basic['local_start_time']) if basic['local_start_time'] else None
                    event.local_start_time=clock
                    event.race_datetime=datetime.combine(event.local_date,clock,ZoneInfo(event.timezone_name)) if clock else None
                event.source_refs={**(event.source_refs or {}),
                    'hkjc_basic_evidence':{**item['basic_evidence'],'manifest_sha256':digest}}
                if 'distance_text' in basic:
                    event.distance_text=basic['distance_text']
                    event.source_refs={**(event.source_refs or {}),'field_units':{
                        **(event.source_refs or {}).get('field_units',{}),'distance_text':'m'},
                        'hkjc_basic_evidence':{**item['basic_evidence'],'manifest_sha256':digest}}
                event.save(update_fields=('local_start_time','race_datetime','distance_text','source_refs','updated_at'))
            if 'result' in item:
                spec=item['result']
                obs=parse_hkjc_observation(fetch(spec['url']),url=spec['url'],route=route,now=now)
                if (obs['local_date']!=str(event.local_date) or obs['external_race_id']!=spec['external_race_id']
                    or obs['result_phase']!='official' or not obs.get('roster_evidence')):
                    raise ValueError('result_scope')
                register_name(event,obs['raw_names'][0],spec)
                match=resolve_observation(obs,route=route,now=now)
                if match.status!='exact' or match.event_id!=event.pk:raise ValueError('result_identity')
                # 既有中文行只用已保存的官方 horseid 和来源场次对账；马号或名称相似均不足以映射。
                by_id={r['external_runner_id']:r for r in obs['roster']}
                for runner in event.runners.all():
                    refs=runner.source_refs or {};horse=urlsplit(refs.get('horse_url',''))
                    hid=parse_qs(horse.query).get('horseid',[''])[0]
                    row=by_id.get(hid)
                    if (horse.hostname!='racing.hkjc.com' or not row or runner.horse_number!=row['number']
                        or url_key(refs.get('result_url') or refs.get('primary',''))[3]!=url_key(spec['url'])[3]):
                        raise ValueError('legacy_runner_identity')
                    runner.source_refs={**refs,'hkjc':hid,'bootstrap_kind':'result'};runner.save(update_fields=('source_refs','updated_at'))
                decision=attach_multisource_observation(obs,policy=policy,now=now)
                if decision.action!='acquired':raise ValueError('attach:'+decision.reason_code)
                claims=claim_multisource_events(event_ids=[event.pk],now=now,historical=True)
                if len(claims)!=1:raise ValueError('historical_claim_unavailable')
                result=run_multisource_claim(claim=claims[0],now=now,fetcher=fetch)
                if not result.get('processed'):raise ValueError('apply:'+result.get('reason','unknown'))
                event.refresh_from_db()
                if event.status!='finished' or event.results.count()!=len(obs['roster']):raise ValueError('projection_incomplete')
            report.append(dict(event_id=event.pk,status=event.status,rows=event.results.count(),
                public_date=str(event.local_date),local_start_time=str(event.local_start_time or ''),
                snapshot_sha256=snapshot(event)))
        if apply:
            models.OperationLog.objects.create(action_type='hkjc_field_repair',target_type='manifest',target_id=digest,
                detail=json.dumps(dict(events=report),ensure_ascii=False))
            transaction.on_commit(invalidate_public_race_cache)
        else:transaction.set_rollback(True)
        return dict(action='applied' if apply else 'dry_run_rolled_back',manifest_sha256=digest,events=report)


class Command(BaseCommand):
    help='固定官方证据包修复香港结果及基础字段，默认回滚；不联网'
    def add_arguments(self,parser):
        parser.add_argument('--manifest',required=True)
        parser.add_argument('--expected-sha256',required=True)
        parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        try:result=execute(options['manifest'],options['expected_sha256'],apply=options['apply'])
        except (ValueError,KeyError,TypeError,OSError) as exc:raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result,ensure_ascii=False))
