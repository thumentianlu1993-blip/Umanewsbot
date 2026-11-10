"""法国固定范围数据包：目录、来源名称、重复映射和完整历史赛果的原子回放。"""
import hashlib
import json
from datetime import date
from pathlib import Path
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from stable import models
from .race_data_source_adapters import canonical_sha,load_multisource_policy,fetch_bound_observation,run_multisource_claim
from .race_data_sync_enrollment import attach_multisource_observation,_lock_multisource_event
from .race_data_sync_control import claim_multisource_events
from .race_source_identity import resolve_observation
from .france_archive import replay_page
from .france_release_handoff import validate_handoff, record_handoff

EVENT_FIELDS=('id','year','edition_year','slug','original_name','chinese_name','country_region','racecourse',
    'race_series_id','local_date','local_start_time','race_datetime','timezone_name','grade_text','normalized_grade',
    'distance_text','status','visibility_status','source_refs','manual_lock_flags','result_confirmed_at')
PATCH_FIELDS={'original_name','local_date','timezone_name','local_start_time','race_datetime','grade_text',
    'normalized_grade','distance_text','eligibility_text','source_refs'}
SERIES_FIELDS=('id','key','canonical_name_original','country_region','review_status','source_refs')


def model_baseline(obj,fields):
    return canonical_sha({k:(v.isoformat() if hasattr(v,'isoformat') else v) for k in fields for v in [getattr(obj,k)]})


def event_baseline(event):
    return canonical_sha(json.loads(json.dumps({'event':model_baseline(event,EVENT_FIELDS),
        'results':list(event.results.order_by('pk').values()),
        'runners':list(event.runners.order_by('pk').values())},default=str)))


def series_baseline(series):
    return model_baseline(series,SERIES_FIELDS)


def read_bound(root,spec):
    relative=Path(spec['file']);path=(root/relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()) or (root/relative).is_symlink():raise ValueError('artifact_path')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise ValueError('artifact_digest')
    return json.loads(raw)


def execute(path,expected_sha256,*,apply=False,now=None,approved_by_id=None,restore=False):
    now=now or timezone.now();path=Path(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected_sha256:raise ValueError('manifest_digest')
    manifest=json.loads(raw);items=manifest.get('items',[])
    if manifest.get('action')=='france_field_repair':
        from .france_field_repair import execute_repair
        return execute_repair(path.parent,manifest,digest,apply=apply,restore=restore,now=now)
    if restore:
        raise ValueError('restore_requires_field_repair')
    if (manifest.get('schema_version')!=1 or manifest.get('action')!='france_release_data'
        or not 1<=len(items)<=1000):raise ValueError('manifest_scope')
    identities=[('id',x['event_id']) if x.get('event_id') else ('slug',x.get('slug')) for x in items]
    if len(set(identities))!=len(items) or any(not x[1] for x in identities):raise ValueError('duplicate_event')
    handoff_entries=manifest.get('legacy_handoffs',[])
    handoffs={entry['event_id']:entry for entry in handoff_entries}
    result_ids={item['event_id'] for item in items if item.get('event_id') and item.get('result_rows')}
    if len(handoffs)!=len(handoff_entries) or not set(handoffs)<=result_ids:raise ValueError('handoff_scope')
    policy=load_multisource_policy(now=now)
    if not policy.valid(now) or policy.digest!=manifest['policy_digest']:raise ValueError('policy_drift')
    source=read_bound(path.parent,manifest['archive']);pages={}
    observed=parse_datetime(manifest['archive']['observed_at'])
    if observed is None or timezone.is_naive(observed) or observed>now:raise ValueError('archive_observed_at')
    for doc in source['cards']+source['results']:
        if doc['url'] in pages:raise ValueError('duplicate_document')
        pages[doc['url']]=replay_page(doc,observed_at=observed)
    def fetch(url,**kwargs):
        if url not in pages:raise ValueError('unlisted_source_page')
        return pages[url]
    with transaction.atomic():
        # 全包在单一发布停写窗口执行。事务失败与dry-run均回滚，不保留部分发布。
        receipt=models.OperationLog.objects.filter(action_type='france_release_data',target_type='manifest',target_id=digest).first()
        if receipt:return {**json.loads(receipt.detail),'action':'replay'}
        locked={}
        for item in sorted((i for i in items if i.get('event_id')),key=lambda i:i['event_id']):
            event,lifecycle=_lock_multisource_event(item['event_id'])
            if event.country_region!='france' or event_baseline(event)!=item['event_baseline']:raise ValueError('event_baseline_drift')
            if (lifecycle and lifecycle.manual_pause_reason) or any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists():raise ValueError('manual_lock')
            control=getattr(event,'projection_control',None)
            if event.pk in handoffs:
                validate_handoff(event,handoffs[event.pk])
            else:
                if control and control.write_owner not in ('unmanaged','data_sync'):raise ValueError('owner_conflict')
                if getattr(event,'race_data_sync_enrollment',None):raise ValueError('existing_enrollment_requires_separate_rebind')
            locked[event.pk]=event
        series={s.pk:s for s in models.RaceSeries.objects.select_for_update().filter(pk__in=[i['series_id'] for i in items]).order_by('pk')}
        report=[]
        for item in items:
            s=series.get(item['series_id'])
            if not s or s.country_region!='france' or s.review_status!='approved' or series_baseline(s)!=item['series_baseline']:raise ValueError('series_baseline_drift')
            fields=item['fields']
            if set(fields)-PATCH_FIELDS:raise ValueError('unlisted_field')
            if item.get('event_id'):
                event=locked[item['event_id']]
                if event.race_series_id!=s.pk:raise ValueError('series_changed')
                for key,value in fields.items():setattr(event,key,value)
            else:
                year=int(item['year'])
                if models.RaceEvent.objects.filter(Q(slug=item['slug'])|Q(race_series=s,edition_year=year)).exists():raise ValueError('event_already_exists')
                event=models.RaceEvent(year=year,edition_year=year,slug=item['slug'],race_series=s,country_region='france',
                    racecourse=item['racecourse'],status='scheduled',visibility_status='published',**fields)
            if isinstance(event.local_date,str):event.local_date=date.fromisoformat(event.local_date)
            if event.timezone_name!='Europe/Paris' or event.local_date.year!=event.year:raise ValueError('event_scope')
            event.full_clean(exclude=['chinese_name','grade_text','surface']);event.save()
            for text in item['names']:
                normalized=' '.join(text.casefold().split())
                overlap=models.RaceSeriesName.objects.filter(series__country_region='france',normalized_text=normalized,is_active=True).filter(
                    Q(valid_from_year=0)|Q(valid_from_year__lte=event.year)).filter(Q(valid_to_year=0)|Q(valid_to_year__gte=event.year))
                if overlap.exclude(series=s).exists():raise ValueError('source_name_conflict')
                if not overlap.filter(series=s).exists():
                    models.RaceSeriesName.objects.create(series=s,text=text,source_language='fr',name_type='alias',
                        valid_from_year=event.year,valid_to_year=event.year,source_refs={'primary':item['source_url'],'manifest_sha256':digest})
            report.append(dict(event_id=event.pk,slug=event.slug,rows=0))
        # 旧URL使用既有产品映射；不删除任何赛事、系列或历史行。
        for link in manifest.get('canonical_links',[]):
            from .race_result_recovery_projection import approve_canonical_link
            duplicate=models.RaceEvent.objects.select_for_update().get(pk=link['duplicate_event_id'])
            if event_baseline(duplicate)!=link['duplicate_baseline']:raise ValueError('duplicate_baseline_drift')
            canonical=models.RaceEvent.objects.get(pk=link['canonical_event_id'])
            if duplicate.country_region!='france' or canonical.country_region!='france' or duplicate.local_date!=canonical.local_date:raise ValueError('duplicate_identity')
            if not approved_by_id:raise ValueError('canonical_actor_required')
            approve_canonical_link(duplicate_event_id=duplicate.pk,canonical_event_id=canonical.pk,
                identity_sha256=link['identity_sha256'],manifest_sha256=digest,approved_by_id=approved_by_id,approved_at=now)
        for item,entry in zip(items,report):
            if not item.get('result_rows'):continue
            event=models.RaceEvent.objects.get(pk=entry['event_id'])
            routes=[r for r in policy.routes if r.provider=='geny' and r.region=='france' and r.permits_url(item['source_url'])]
            if len(routes)!=1:raise ValueError('geny_route_missing')
            route=routes[0]
            observation=fetch_bound_observation(event=event,route=route,now=now,fetcher=fetch,url_hint=item['source_url'])
            match=resolve_observation(observation,route=route,now=now)
            if match.status!='exact' or match.event_id!=event.pk:raise ValueError('result_identity')
            if len(observation.get('roster',[]))!=item['result_rows']:raise ValueError('result_count')
            decision=attach_multisource_observation(observation,policy=policy,now=now,legacy_handoff=handoffs.get(event.pk))
            if decision.action not in ('acquired','attached','replay'):raise ValueError('attach_'+decision.reason_code)
            claims=claim_multisource_events(event_ids=[event.pk],now=now,historical=True)
            if len(claims)!=1:raise ValueError('historical_claim_unavailable')
            result=run_multisource_claim(claim=claims[0],now=now,fetcher=fetch)
            if not result.get('processed'):raise ValueError('result_'+result.get('reason','unknown'))
            event.refresh_from_db()
            if event.status!='finished' or event.results.count()!=item['result_rows']:raise ValueError('public_projection_incomplete')
            entry['rows']=event.results.count()
            if event.pk in handoffs:record_handoff(event,before=handoffs[event.pk],manifest_sha256=digest)
        result=dict(manifest_sha256=digest,action='applied' if apply else 'dry_run_rolled_back',events=report,
            result_rows=sum(e['rows'] for e in report))
        if apply:models.OperationLog.objects.create(action_type='france_release_data',target_type='manifest',target_id=digest,detail=json.dumps(result))
        else:transaction.set_rollback(True)
        return result
