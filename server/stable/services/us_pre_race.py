"""美国赛前候选与正式卡发现；使用现有租约、候选和身份登记。"""
from .us_public_fields import blocking_multisource_manual_locks
from datetime import date, timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models
from . import race_pre_race as pre
from .race_data_source_adapters import canonical_sha, load_multisource_policy, fetch_source_page

US = 'us_pre_race_v1'
LABELS = {'nominations':'报名名单','preliminary_field':'预想参赛名单','declared_overnight':'临时出马资料',
          'final_card':'出马表','provisional_card':'临时出马资料','declared_card':'出马表','published_card':'出马表','card':'出马表'}
RANK = {'nominations':0,'preliminary_field':1,'declared_overnight':2,'final_card':3,'provisional_card':2,'declared_card':3,'published_card':3,'card':3}


def enabled():
    return (getattr(settings,'RACE_DATA_SYNC_US_PRE_RACE_ENABLED',False) is True
        and settings.RACE_DATA_SYNC_ENABLED is True and settings.RACE_DATA_SYNC_ALLOW_NETWORK is True
        and 'us_racing' in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
        and 'united_states' in settings.RACE_DATA_SYNC_ENABLED_REGIONS)


def route_for(event, policy):
    binding=(event.source_refs or {}).get('us_target_v1',{})
    routes=[r for r in policy.routes if r.provider=='us_racing' and r.region=='united_states'
            and r.timezone==event.timezone_name and binding.get('venue') in r.venue_aliases]
    if len(routes)!=1:raise ValueError('us_route_missing')
    return routes[0]


def preview_document(document, *, target):
    data=document['data'];stage=data['source_stage'];rows=data.get('runners',data.get('items',[]))
    if (stage not in RANK or data['local_date']!=target['local_date'] or not rows
            or data.get('gaps') or data.get('fields_complete') is False):
        raise ValueError('us_preview_incomplete')
    source=document['source'];items=[]
    for row in rows:
        number=row.get('program_number',row.get('horse_number',''))
        # Overnight PP是临时编号，不冒充最终马号。
        item=dict(horse_name=row['horse_name'],horse_number=str(number or ''),barrier=str(row.get('post_position',row.get('barrier','')) or ''),
            jockey_name=row.get('jockey_name',''),trainer_name=row.get('trainer_name',''),carried_weight=row.get('carried_weight',''),
            running_status=row.get('running_status','declared'),source_refs={'primary':source['url'],'field_units':{'carried_weight':'lb'}})
        odds=str(row.get('odds_raw') or '')
        if odds:
            from .race_field_normalization import parse_display_odds
            if parse_display_odds(odds,odds_format='fractional').state=='normalized':
                item.update(odds_value=odds,odds_kind='current',odds_format='fractional',odds_observed_at=source['fetched_at'])
                item['source_refs']['field_units']['odds_value']='fractional'
                item['source_refs'].update(odds_source='Sporting Life',odds_observed_at=source['fetched_at'])
        items.append(item)
    if len({i['horse_name'] for i in items})!=len(items):raise ValueError('us_preview_duplicate')
    return dict(stage=stage,items=items,off_time=data.get('off_time') or '',race_number=str(data.get('race_number') or ''),
        local_date=target['local_date'],race_name=target['race_name'],venue=target['venue'],source=source,
        final_card=RANK[stage]==3 and data.get('roster_complete') is True)


def fetch_preview(event, *, route, now, fetcher):
    from .us_race_source import ObservationStore
    from .us_prerelease_collection import collect_prerace, nsa_preview
    target=(event.source_refs or {}).get('us_target_v1',{})
    if target.get('local_date')!=str(event.local_date):raise ValueError('us_event_target_missing')
    store=ObservationStore(route=route,now=now,fetcher=fetcher)
    day=date.fromisoformat(target['local_date'])
    if target.get('provider')=='nsa':
        document=nsa_preview(store,target)
        if document['kind']=='not_published':
            return dict(stage='not_published',items=[],source=document['source'],local_date=target['local_date'])
        return preview_document(document,target=target)
    report=collect_prerace(store,start=day,end=day,target_keys={target['candidate_key']},
        flat_report=dict(start=day.isoformat(),end=day.isoformat(),results=[],sources=[]))
    target_rows=[r for r in report['targets'] if r['candidate_key']==target['candidate_key']]
    if len(target_rows)!=1:raise ValueError('us_preview_target_missing')
    choices=[]
    for index in target_rows[0]['documents']:
        document=report['documents'][index]
        if document['data']['source_stage'] not in RANK:continue
        try:choices.append(preview_document(document,target=target))
        except ValueError:continue
    if not choices:
        if report['errors'] or target_rows[0]['errors']:raise ValueError('us_preview_source_check_failed')
        stage = 'not_published' if target_rows[0].get('card_status') == 'not_published' else 'coverage_unverified'
        return dict(stage=stage,items=[],source={},local_date=target['local_date'],schedule=target_rows[0].get('schedule'),schedule_checks=report.get('schedule_checks',[]))
    choices.sort(key=lambda p:(RANK[p['stage']],p['source']['fetched_at']),reverse=True)
    return dict(choices[0],schedule=target_rows[0].get('schedule'),schedule_checks=report.get('schedule_checks',[]))


def card_observation(payload, *, route):
    from .race_data_source_adapters import aware
    if not payload.get('final_card') or not payload['race_number']:
        raise ValueError('us_card_not_final')
    rows=[]
    for row in payload['items']:
        if not row['horse_number']:raise ValueError('us_card_number_missing')
        rows.append(dict(external_runner_id='number:'+row['horse_number'],number=row['horse_number'],
            horse_name=row['horse_name'],barrier=row['barrier'],jockey_name=row['jockey_name'],trainer_name=row['trainer_name'],
            carried_weight=row['carried_weight'],status=row['running_status'],odds_value=row.get('odds_value',''),field_provenance=row['source_refs']))
    source=payload['source']
    return dict(provider=route.provider,region=route.region,identity_namespace=route.identity_namespace,operator=route.operator,
        external_race_id=payload['venue']+':'+payload['local_date']+':'+payload['race_number'],
        canonical_url=source['url'],fetched_at=source['fetched_at'],raw_sha256=source['sha256'],parser_version=route.parser_version,
        venue_key=payload['venue'],local_date=payload['local_date'],timezone=route.timezone,meeting_session='single',
        race_number=payload['race_number'],raw_names=[payload['race_name']],off_time=payload['off_time'],roster=rows,roster_complete=True)


def complete(claim, *, payload, route, now):
    from .race_data_sync_enrollment import _lock_multisource_event
    from .race_pre_race_refresh import stamp_dynamic_items
    with transaction.atomic():
        event,lifecycle=_lock_multisource_event(claim['event_id'])
        if not enabled() or not route.valid(now) or not pre._valid_claim(event,claim,now):return False
        if (event.country_region!='united_states' or event.divisions.exists() or blocking_multisource_manual_locks(event)
            or event.field_authorities.filter(manual_lock=True).exists()
            or (getattr(event,'projection_control',None) and event.projection_control.write_owner not in {'unmanaged','data_sync'})
            or (lifecycle and lifecycle.mode not in {'off','shadow'})):
            pre._finish_locked(event,claim,now,outcome_reason='manual_or_owner_lock');return False
        if payload.get('source'):
            from .race_data_source_adapters import aware,require_sha
            source=payload['source'];require_sha(source['sha256'])
            if aware(source['fetched_at'])>now or not route.permits_url(source['url']):raise ValueError('us_preview_source_invalid')
        if payload.get('source') or payload.get('schedule_checks'):
            event.source_refs={**(event.source_refs or {}),'us_pre_race_checks':dict(
                source=payload.get('source',{}),schedule_checks=payload.get('schedule_checks',[]),stage=payload['stage'],checked_at=now.isoformat())}
            event.save(update_fields=['source_refs','updated_at'])
        if payload.get('schedule'):
            from .us_stakes_schedule import apply_schedule_locked
            apply_schedule_locked(event,payload['schedule'],route=route,now=now)
        if payload['stage'] in {'not_published', 'coverage_unverified'}:
            pre._finish_locked(event,claim,now,outcome_reason=payload['stage']);return True
        latest=event.data_candidates.filter(source_name=US,module='runners',status='pending').order_by('-fetched_at','-id').first()
        old=latest.raw_payload.get(US,{}) if latest else {}
        if old.get('baseline')==pre.baseline(event) and RANK.get(old.get('stage'),-1)>RANK[payload['stage']]:
            pre._finish_locked(event,claim,now,outcome_reason='older_source');return False
        source=payload['source']
        from .race_data_source_adapters import aware
        observed=aware(source['fetched_at'])
        if observed>now or not route.permits_url(source['url']):raise ValueError('us_preview_source_invalid')
        content=canonical_sha(payload)
        if old.get('content_sha256')!=content or old.get('baseline')!=pre.baseline(event):
            meta=dict(validated=True,baseline=pre.baseline(event),stage=payload['stage'],content_sha256=content,
                route_digest=route.digest,raw_sha256=source['sha256'])
            previous_items=(latest.candidate_payload.get('items',[]) if latest and old.get('baseline')==pre.baseline(event)
                and RANK.get(old.get('stage'),-1)>=RANK[payload['stage']] else [])
            items=(payload['items'] if payload['stage'] in {'nominations','preliminary_field'} else
                stamp_dynamic_items(payload['items'],previous_items,
                    source_url=source['url'],now=observed,strict_roster=bool(payload.get('final_card'))))
            models.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=US,source_url=source['url'],
                candidate_payload={**payload,'items':items},raw_payload={US:meta},fetched_at=observed)
        if payload.get('final_card'):
            from .race_source_identity import identity_key
            target=(event.source_refs or {}).get('us_target_v1',{})
            if (target.get('local_date')!=payload['local_date'] or target.get('venue')!=payload['venue']
                or target.get('race_name')!=payload['race_name'] or not target.get('candidate_key')):
                raise ValueError('us_card_target_drift')
            key=identity_key(card_observation(payload,route=route))
            existing=models.RaceEventIdentityKey.objects.filter(namespace=key['namespace'],key_sha256=key['key_sha256']).first()
            if existing and existing.event_id!=event.pk:raise ValueError('us_card_identity_conflict')
            if models.RaceEventIdentityKey.objects.filter(event=event,namespace=key['namespace']).exclude(key_sha256=key['key_sha256']).exists():
                raise ValueError('us_card_occurrence_changed')
            if not existing:
                models.RaceEventIdentityKey.objects.create(event=event,**key,evidence={'us_target_key':target['candidate_key'],
                    'candidate_sha256':content,'raw_sha256':source['sha256'],'route_digest':route.digest})
        pre._finish_locked(event,claim,now)
        return True


def public_us_preview(event, *, now):
    if (event.country_region!='united_states' or event.status!='scheduled' or not getattr(settings,'RACE_DATA_SYNC_US_PRE_RACE_ENABLED',False)
        or not settings.RACE_DATA_SYNC_ENABLED or 'us_racing' not in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
        or 'united_states' not in settings.RACE_DATA_SYNC_ENABLED_REGIONS
        or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS or pre._refs(event).get('pre_race_handoff')
        or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED or not pre.preview_window(event,now)
        or event.runners.exists() or blocking_multisource_manual_locks(event)
        or event.field_authorities.filter(manual_lock=True).exists()):return None
    control=getattr(event,'projection_control',None)
    if control and control.write_owner not in {'unmanaged','data_sync'}:return None
    candidate=event.data_candidates.filter(source_name=US,module='runners',status='pending',raw_payload__us_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:return None
    meta=candidate.raw_payload[US]
    if meta.get('baseline')!=pre.baseline(event) or meta.get('stage') not in LABELS:return None
    from .race_pre_race_refresh import dynamic_rows
    return dict(rows=dynamic_rows(event,candidate.candidate_payload['items'],now=now),label=LABELS[meta['stage']],
        checked_at=pre._dt(pre._state(event,US).get('last_checked_at')) or candidate.fetched_at,
        stale=bool(pre._state(event,US).get('reason')))


def discover_us_pre_race(*, now, policy=None, fetcher=None, clock=timezone.now):
    if not enabled():return {'checked':0,'reason':'disabled'}
    policy=policy or load_multisource_policy(now=now)
    if not policy.valid(now):raise ValueError('us_policy_expired')
    fetcher=fetcher or fetch_source_page
    events=models.RaceEvent.objects.filter(country_region='united_states',visibility_status='published',status='scheduled',
        divisions__isnull=True,local_date__gte=now.date()-timedelta(days=1),local_date__lte=now.date()+timedelta(days=61))
    events=sorted((e for e in events if pre.in_window(e,now)),key=lambda e:(pre._state(e,US).get('next_poll_at') or '',e.pk))
    checked=0;errors=[]
    for event in events:
        if checked>=settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE:break
        claim=pre.claim_pre_race(event_id=event.pk,source=US,now=clock())
        if not claim:continue
        checked+=1
        try:
            route=route_for(event,policy)
            payload=fetch_preview(event,route=route,now=clock(),fetcher=fetcher)
            if complete(claim,payload=payload,route=route,now=clock()) and payload.get('final_card'):
                from .race_data_sync_enrollment import attach_multisource_observation
                decision=attach_multisource_observation(card_observation(payload,route=route),policy=policy,now=clock())
                if decision.action not in {'acquired','attached','replay'}:errors.append({'event_id':event.pk,'reason':decision.reason_code})
        except (ValueError,KeyError,TypeError,OSError) as exc:
            reason=str(exc)[:150];errors.append({'event_id':event.pk,'reason':reason})
            pre.finish_pre_race(claim,now=clock(),reason=reason,retry_after=getattr(exc,'retry_after',None))
    return dict(checked=checked,errors=errors)
