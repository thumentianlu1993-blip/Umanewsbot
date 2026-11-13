"""英国报名与正式卡发现，复用候选、租约和多源写入合同。"""
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models
from . import race_pre_race as pre
from .race_data_source_adapters import canonical_sha,load_multisource_policy,aware,require_sha
from .uk_collection import fetch_payload
from .uk_sources import PARSER_VERSION
from .uk_race_source import source_observation
from .us_public_fields import blocking_multisource_manual_locks

UK='uk_pre_race_v1'
LABELS={'nominations':'报名名单','weights_published':'负磅公布名单','declared_card':'出马表'}
RANK={'nominations':0,'weights_published':1,'declared_card':2}


def enabled():
    return (getattr(settings,'RACE_DATA_SYNC_UK_PRE_RACE_ENABLED',False) is True
        and settings.RACE_DATA_SYNC_ENABLED and settings.RACE_DATA_SYNC_ALLOW_NETWORK
        and 'the_racing_api' in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
        and 'united_kingdom' in settings.RACE_DATA_SYNC_ENABLED_REGIONS)


def route_for(event,policy):
    routes=[r for r in policy.routes if r.provider=='the_racing_api' and r.region=='united_kingdom'
        and r.parser_version==PARSER_VERSION and r.timezone==event.timezone_name
        and any(event.racecourse in aliases for aliases in r.venue_aliases.values())]
    if len(routes)!=1:raise ValueError('uk_route_missing')
    return routes[0]


def bind_source(event,value,*,route,now):
    """仅由已审核目标+日期+马场+唯一名称匹配建立付费外部ID，冲突则回滚。"""
    if not (event.source_refs or {}).get('uk_target_v1'):raise ValueError('uk_target_missing')
    if (value['local_date']!=str(event.local_date) or value['parser_version']!=PARSER_VERSION
            or not route.permits_url(value['canonical_url'])):raise ValueError('uk_binding_scope')
    lookup=dict(source_key=route.provider,region_code=route.region,identity_namespace=route.identity_namespace)
    bound=models.RaceResultSourceIdentity.objects.select_for_update().filter(**lookup,external_race_id=value['external_race_id']).first()
    if bound:
        if (bound.event_id!=event.pk or bound.review_status!='approved' or bound.terms_status!='approved'
                or not bound.automation_allowed or bound.registry_digest!=route.digest):raise ValueError('uk_binding_conflict')
        return bound
    if models.RaceResultSourceIdentity.objects.filter(event=event,**lookup).exists():raise ValueError('uk_binding_changed')
    return models.RaceResultSourceIdentity.objects.create(event=event,**lookup,external_race_id=value['external_race_id'],
        canonical_url=value['canonical_url'],host=urlsplit(value['canonical_url']).hostname,
        identity_fields={'multisource_v2':value},review_status='approved',terms_status='approved',
        automation_allowed=True,proof_network_allowed=True,reviewed_at=now,evidence_url=value['canonical_url'],
        evidence_sha256=value['raw_sha256'],valid_until=aware(route.valid_until),registry_digest=route.digest,
        result_authority='supplemental')


def preview_items(payload):
    source=next(d for d in payload['source_documents'] if d['url']==payload.get('primary_source_url',payload['source_documents'][0]['url']))
    from .uk_public_fields import public_refs
    return [dict(odds_value=r.get('odds_value',''),odds_kind='current',odds_format='decimal',odds_observed_at=source['fetched_at'],horse_name=r['horse_name'],horse_number=r['number'],barrier=r['barrier'],
        jockey_name=r['jockey_name'],trainer_name=r['trainer_name'],carried_weight=r['carried_weight'],
        running_status=r['status'],source_refs=public_refs({**r['field_provenance'],'uk_paid_v1':True,'source_url':source['url'],'odds_observed_at':source['fetched_at']}))
        for r in payload['roster']]


def complete(claim,*,payload,route,now):
    from .race_data_sync_enrollment import _lock_multisource_event
    with transaction.atomic():
        event,lifecycle=_lock_multisource_event(claim['event_id'])
        if not enabled() or not route.valid(now) or not pre._valid_claim(event,claim,now):return False
        if (event.country_region!='united_kingdom' or blocking_multisource_manual_locks(event)
                or event.field_authorities.filter(manual_lock=True).exists()
                or getattr(event,'projection_control',None) and event.projection_control.write_owner not in {'unmanaged','data_sync'}
                or lifecycle and lifecycle.mode not in {'off','shadow'}):
            pre._finish_locked(event,claim,now,outcome_reason='manual_or_owner_lock');return False
        for source in payload['source_documents']:
            require_sha(source['sha256'])
            if aware(source['fetched_at'])>now or not route.permits_url(source['url']):raise ValueError('uk_preview_source')
        stage=payload['stage']
        if stage=='not_published':
            pre._finish_locked(event,claim,now,outcome_reason=stage);return True
        if stage not in RANK or payload.get('gaps') or payload.get('result_phase'):raise ValueError('uk_preview_stage')
        source=next(d for d in payload['source_documents'] if d['url']==payload.get('primary_source_url',payload['source_documents'][0]['url']));observed=aware(source['fetched_at'])
        latest=event.data_candidates.filter(source_name=UK,module='runners',status='pending').order_by('-fetched_at','-id').first()
        old=latest.raw_payload.get(UK,{}) if latest else {};base=pre.baseline(event)
        if old.get('baseline')==base and RANK.get(old.get('stage'),-1)>RANK[stage]:
            pre._finish_locked(event,claim,now,outcome_reason='older_source');return False
        content=canonical_sha(payload)
        if old.get('content_sha256')!=content or old.get('baseline')!=base:
            meta=dict(validated=True,baseline=base,stage=stage,content_sha256=content,route_digest=route.digest)
            models.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=UK,source_url=source['url'],
                candidate_payload={'items':preview_items(payload)},raw_payload={UK:meta},fetched_at=observed)
        if stage=='declared_card':
            value=source_observation(payload,route=route,now=now)
            bind_source(event,value,route=route,now=now)
            from .uk_basic_fields import apply_metadata_locked
            apply_metadata_locked(event=event,metadata=value['uk_race_metadata'],route=route,now=now)
        pre._finish_locked(event,claim,now)
        return True


def public_uk_preview(event,*,now):
    if (event.country_region!='united_kingdom' or event.status!='scheduled'
            or not getattr(settings,'RACE_DATA_SYNC_UK_PRE_RACE_ENABLED',False)
            or not settings.RACE_DATA_SYNC_ENABLED or 'the_racing_api' not in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
            or 'united_kingdom' not in settings.RACE_DATA_SYNC_ENABLED_REGIONS
            or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS
            or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED or not pre.preview_window(event,now)
            or event.race_datetime and now>=event.race_datetime-timedelta(minutes=30)
            or event.runners.exists() or pre._refs(event).get('pre_race_handoff')
            or blocking_multisource_manual_locks(event) or event.field_authorities.filter(manual_lock=True).exists()):return None
    control=getattr(event,'projection_control',None)
    if control and control.write_owner not in {'unmanaged','data_sync'}:return None
    latest=event.data_candidates.filter(source_name=UK,module='runners',status='pending',raw_payload__uk_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not latest:return None
    meta=latest.raw_payload[UK]
    if meta.get('baseline')!=pre.baseline(event) or meta.get('stage') not in LABELS:return None
    from .race_pre_race_refresh import dynamic_rows
    return dict(rows=dynamic_rows(event,latest.candidate_payload['items'],now=now),label=LABELS[meta['stage']],
        checked_at=pre._dt(pre._state(event,UK).get('last_checked_at')) or latest.fetched_at,
        stale=bool(pre._state(event,UK).get('reason')))


def discover_uk_pre_race(*,now,policy=None,fetcher=None,clock=timezone.now):
    if not enabled():return {'checked':0,'reason':'disabled'}
    policy=policy or load_multisource_policy(now=now)
    if not policy.valid(now):raise ValueError('uk_policy_expired')
    events=models.RaceEvent.objects.filter(country_region='united_kingdom',visibility_status='published',status='scheduled',
        local_date__gte=now.date()-timedelta(days=1),local_date__lte=now.date()+timedelta(days=61),source_refs__has_key='uk_target_v1')
    events=sorted((e for e in events if pre.in_window(e,now) and not e.runners.exists()),key=lambda e:(pre._state(e,UK).get('next_poll_at') or '',e.pk))
    checked=0;errors=[]
    for event in events:
        if checked>=settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE:break
        claim=pre.claim_pre_race(event_id=event.pk,source=UK,now=clock())
        if not claim:continue
        checked+=1
        try:
            route=route_for(event,policy);payload=fetch_payload(event=event,route=route,now=clock(),fetcher=fetcher)
            if complete(claim,payload=payload,route=route,now=clock()) and payload.get('stage')=='declared_card':
                from .race_data_sync_enrollment import attach_multisource_observation
                decision=attach_multisource_observation(source_observation(payload,route=route,now=clock()),policy=policy,now=clock())
                if decision.action not in {'acquired','attached','replay'}:errors.append({'event_id':event.pk,'reason':decision.reason_code})
        except (ValueError,KeyError,TypeError,OSError) as exc:
            reason=str(exc)[:150];errors.append({'event_id':event.pk,'reason':reason})
            pre.finish_pre_race(claim,now=clock(),reason=reason,retry_after=getattr(exc,'retry_after',None))
    return dict(checked=checked,errors=errors)
