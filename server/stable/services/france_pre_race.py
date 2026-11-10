"""法国官方赛前分阶段候选；沿用既有租约、调度与公开字段规则。"""
from datetime import timedelta
import hashlib
from urllib.parse import urljoin, urlsplit, urlencode
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models
from . import race_pre_race as pre
from .race_data_source_adapters import load_multisource_policy, fetch_source_page, canonical_sha

FRANCE='france_pre_race_v1'


def enabled():
    return (getattr(settings,'RACE_DATA_SYNC_FRANCE_PRE_RACE_ENABLED',False) is True
        and settings.RACE_DATA_SYNC_ENABLED is True and settings.RACE_DATA_SYNC_ALLOW_NETWORK is True
        and 'france_galop' in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
        and 'france' in settings.RACE_DATA_SYNC_ENABLED_REGIONS)


def _route(event,policy):
    routes=[r for r in policy.routes if r.provider=='france_galop' and r.region=='france'
        and event.racecourse in {n for names in r.venue_aliases.values() for n in names}]
    if len(routes)!=1:raise ValueError('france_route_missing')
    return routes[0]


def complete(claim, *, payload, url, page, route, now):
    from .race_data_sync_enrollment import _LifecycleLockRetry
    for attempt in range(3):
        try:
            return _complete_atomic(claim, payload=payload, url=url, page=page, route=route, now=now)
        except _LifecycleLockRetry:
            if attempt == 2:
                raise


def _complete_atomic(claim, *, payload, url, page, route, now):
    from time import monotonic
    from .race_pre_race_refresh import stamp_dynamic_items, material_items
    from .race_data_sync_enrollment import _lock_multisource_event
    from .france_pre_race_authority import lock_context, apply_time, write_reason
    started = monotonic()
    with transaction.atomic():
        event, lifecycle = _lock_multisource_event(claim['event_id'])
        context = lock_context(event, lifecycle)
        validation_now = now + timedelta(seconds=monotonic()-started)
        if claim.get('source') != FRANCE or not enabled() or not route.valid(validation_now) or not pre._valid_claim(event,claim,validation_now):return False
        if pre._state(event,FRANCE).get('write_guards') != context.guards:
            pre._finish_locked(event,claim,now,outcome_reason='pre_race_write_guard_stale');return False
        reason = write_reason(context, now=validation_now)
        if reason:
            pre._finish_locked(event,claim,now,reason=reason);return False
        if (any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists()
            or (getattr(event, 'projection_control', None) and event.projection_control.write_owner not in {'unmanaged','data_sync'})):
            pre._finish_locked(event,claim,now,outcome_reason='manual_or_owner_lock');return False
        if pre._refs(event).get('pre_race_handoff') or event.runners.exists():
            pre._finish_locked(event,claim,now,outcome_reason='handed_off')
            return False
        module = 'basic' if payload['stage']=='not_published' else 'runners'
        latest=event.data_candidates.filter(source_name=FRANCE,module=module,status='pending').order_by('-fetched_at','-id').first()
        old=latest.raw_payload.get(FRANCE,{}) if latest else {}
        roster_blocked = ''
        if old.get('baseline')==pre.baseline(event) and pre.STAGES.get(old.get('stage'),-1)>pre.STAGES.get(payload['stage'],-1):
            roster_blocked = 'older_or_incomplete_source'
        if (old.get('baseline')==pre.baseline(event) and old.get('as_of') and payload.get('as_of')
            and old['as_of'] > payload['as_of'] and old.get('stage')==payload['stage']):
            roster_blocked = 'older_source'
        if roster_blocked:
            # 名单阶段只约束名单；时间和基础字段独立按各自水位仲裁。
            module='basic'
            latest=event.data_candidates.filter(source_name=FRANCE,module=module,status='pending').order_by('-fetched_at','-id').first()
            old=latest.raw_payload.get(FRANCE,{}) if latest else {}
        previous=latest.candidate_payload.get('items',[]) if latest and old.get('baseline')==pre.baseline(event) else []
        items=(stamp_dynamic_items(payload['items'],previous,now=now,source_url=url,strict_roster=False,
            observed_at=getattr(page,'observed_at',None),roster_limit=500 if payload['stage']=='registration' else 60)
            if module=='runners' else [])
        from .france_basic_fields import basic_sha
        content=canonical_sha(dict(stage=payload['stage'],source_stage=payload.get('source_stage'),items=material_items(items),
            off_time=payload.get('off_time',''),france_basic_sha256=basic_sha(payload.get('france_basic_v1',{}))))
        admitted=module=='runners' and settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED and 'participants.horse_name' in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        if old.get('content_sha256')!=content or old.get('baseline')!=pre.baseline(event) or old.get('validated')!=admitted:
            latest=models.RaceEventDataCandidate.objects.create(event=event,module=module,source_name=FRANCE,source_url=url,
                candidate_payload={**payload,'items':items},raw_payload={FRANCE:dict(validated=bool(admitted),
                    baseline=pre.baseline(event),stage=payload['stage'],content_sha256=content,
                    raw_sha256=getattr(page,'raw_sha256',hashlib.sha256(str(page).encode()).hexdigest()),
                    route_digest=route.digest,as_of=payload.get('as_of',''))},fetched_at=now)
        time_reason = apply_time(context, payload=payload, url=url, page=page, route=route, candidate=latest, now=now)
        if payload.get('france_basic_v1'):
            from .france_pre_race_authority import apply_basic
            apply_basic(context, payload=payload, route=route, candidate=latest, now=now)
        if payload['stage']=='not_published':
            state=pre._state(event,FRANCE);state['publication_schedule']=payload.get('schedule',[]);pre._save_state(event,FRANCE,state)
        pre._finish_locked(event,claim,now,outcome_reason=time_reason or roster_blocked or ('not_published' if payload['stage']=='not_published' else ''))
        return True


def fetch_france_pre_race(*,event,route,now,fetcher,policy=None):
    from .france_sources import document_from_html, parse_france_galop_document, validate_event_identity, parse_geny_observation, name_key
    from .race_data_source_adapters import discover_source_url
    from .france_public_fields import public_refs
    from zoneinfo import ZoneInfo
    if policy and 0 <= (event.local_date-now.astimezone(ZoneInfo('Europe/Paris')).date()).days <= 4:
        geny_routes=[r for r in policy.routes if r.provider=='geny' and r.region=='france' and r.valid(now)
            and name_key(event.racecourse) in {name_key(n) for names in r.venue_aliases.values() for n in names}]
        if len(geny_routes)>1:raise ValueError('france_route_ambiguous')
        if geny_routes:
            geny=geny_routes[0]
            try:url=discover_source_url(event=event,route=geny,now=now,fetcher=fetcher)
            except ValueError as exc:
                if str(exc)!='not_published':raise
            else:
                page=fetcher(url,route=geny,now=now)
                observation=parse_geny_observation(page,url=url,route=geny,now=now)
                venue=geny.venue_aliases[observation['venue_key']][0]
                validate_event_identity(dict(local_date=observation['local_date'],race_name=observation['raw_names'][0],venue=venue),event,geny)
                items=[dict(horse_name=r['horse_name'],horse_number=r['number'],barrier=r['barrier'],
                    jockey_name=r['jockey_name'],trainer_name=r['trainer_name'],carried_weight=r['carried_weight'],
                    running_status=r['status'],odds_value=r['odds_value'],odds_kind='current',odds_format='decimal',
                    source_refs=public_refs(r['field_provenance'])) for r in observation['roster']]
                return url,page,dict(stage='numbered',source_stage='final_card',off_time=observation['off_time'],items=items,
                    local_date=observation['local_date'],race_name=observation['raw_names'][0],venue=venue,
                    external_race_id=observation['external_race_id'],france_basic_v1=observation['france_basic_v1']),geny
    url=discover_source_url(event=event,route=route,now=now,fetcher=fetcher)
    page=fetcher(url,route=route,now=now)
    payload=parse_france_galop_document(document_from_html(page,url))
    payload['france_basic_v1'].update(observed_at=(getattr(page,'observed_at',None) or now).isoformat(),
        raw_sha256=getattr(page,'raw_sha256',hashlib.sha256(str(page).encode()).hexdigest()),parser_version=route.parser_version)
    validate_event_identity(payload,event,route)
    return url,page,payload,route


def discover_france_pre_race(*,now,policy=None,fetcher=None,clock=timezone.now):
    if not enabled():return {'checked':0,'reason':'disabled'}
    policy=policy or load_multisource_policy(now=now)
    if not policy.valid(now):raise ValueError('france_policy_expired')
    fetcher=fetcher or fetch_source_page
    cache={}
    def cached(url,**kwargs):
        if url not in cache:cache[url]=fetcher(url,**kwargs)
        return cache[url]
    events=models.RaceEvent.objects.filter(country_region='france',visibility_status='published',
        status='scheduled',local_date__range=(now.date()-timedelta(days=1),now.date()+timedelta(days=61)),runners__isnull=True)
    events=sorted((e for e in events if pre.in_window(e,now) and not pre._refs(e).get('pre_race_handoff')),
        key=lambda e:(pre._state(e,FRANCE).get('next_poll_at') or '',e.pk))
    checked=attempted=0
    for event in events:
        if attempted>=settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE:break
        claim=pre.claim_pre_race(event_id=event.pk,source=FRANCE,now=clock())
        if not claim:continue
        attempted+=1
        try:
            route=_route(event,policy)
            url,page,payload,route=fetch_france_pre_race(event=event,route=route,now=clock(),fetcher=cached,policy=policy)
            checked+=bool(complete(claim,payload=payload,url=url,page=page,route=route,now=clock()))
        except (ValueError,OSError) as exc:
            pre.finish_pre_race(claim,now=clock(),reason=str(exc)[:64],retry_after=getattr(exc,'retry_after',None))
    return dict(checked=checked,attempted=attempted)


def public_france_preview(event,*,now):
    if (event.country_region!='france' or event.status!='scheduled'
        or not getattr(settings,'RACE_DATA_SYNC_FRANCE_PRE_RACE_ENABLED',False)
        or not settings.RACE_DATA_SYNC_ENABLED or 'france' not in settings.RACE_DATA_SYNC_ENABLED_REGIONS
        or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        or not pre.preview_window(event,now) or event.runners.exists() or pre._refs(event).get('pre_race_handoff')
        or any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists()):return None
    control=getattr(event,'projection_control',None)
    if control and control.write_owner not in {'unmanaged','data_sync'}:return None
    candidate=event.data_candidates.filter(source_name=FRANCE,module='runners',status='pending',
        raw_payload__france_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:return None
    meta=candidate.raw_payload[FRANCE]
    if meta.get('baseline')!=pre.baseline(event) or meta.get('stage') not in pre.STAGES:return None
    result=pre.preview_payload(event,candidate,meta['stage'],now=now)
    if candidate.candidate_payload.get('source_stage')=='probable_runners':
        result['label']='预计参赛名单（尚未最终确认）'
    return result
