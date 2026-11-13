"""英国精确发布包；官方目录、旧身份修正与历史结果在同一事务中应用。"""
import hashlib
import json
from pathlib import Path
from datetime import date
from django.db import transaction
from django.utils import timezone
from stable import models
from .race_data_source_adapters import canonical_sha,load_multisource_policy,fetch_bound_observation,run_multisource_claim
from .race_data_sync_enrollment import _lock_multisource_event,attach_multisource_observation,rebind_multisource_enrollment
from .race_data_sync_control import claim_multisource_events
from .race_source_identity import ArchivedResultReceipt,archived_result_observation_sha
from .france_release import read_bound
from .france_field_repair import frozen
from .france_release_handoff import control_snapshot,validate_handoff
from .us_release import snapshot as base_snapshot,baseline_matches,archive_fetch,_set_fields,restore_release
from .uk_pre_race import route_for,bind_source
from .us_public_fields import blocking_multisource_manual_locks

ACTION='uk_release_data'


def snapshot(ids,targets):
    result=base_snapshot(ids)
    result['HistoricalRaceEventTarget']=frozen(list(models.HistoricalRaceEventTarget.objects.filter(pk__in=targets).order_by('pk').values()))
    return result


def execute(path,expected_sha256,*,apply=False,restore=False,now=None):
    path=Path(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();now=now or timezone.now()
    if digest!=expected_sha256:raise ValueError('manifest_digest')
    manifest=json.loads(raw);items=manifest.get('items',[])
    if manifest.get('action')!=ACTION or manifest.get('schema_version')!=1 or not 1<=len(items)<=1000:raise ValueError('manifest_scope')
    targets=[i['target_id'] for i in items if i.get('target_id')]
    if len(set(targets))!=len(targets):raise ValueError('duplicate_target')
    snapshotter=lambda ids:snapshot(ids,targets)
    if restore:return restore_release(digest,apply=apply,now=now,action=ACTION,snapshotter=snapshotter)
    existing=[i['event_id'] for i in items if i.get('event_id')];slugs=[i['slug'] for i in items if not i.get('event_id')]
    if len(set(existing))!=len(existing) or len(set(slugs))!=len(slugs):raise ValueError('duplicate_event')
    rebind=manifest.get('rebind',[]);rebind_ids=[r['event_id'] for r in rebind]
    if len(set(rebind_ids))!=len(rebind_ids) or set(rebind_ids)&set(existing):raise ValueError('rebind_scope')
    ids=sorted(set(existing+rebind_ids));before=read_bound(path.parent,manifest['baseline'])
    policy=load_multisource_policy(now=now)
    if not policy.valid(now) or policy.digest!=manifest['policy_digest']:raise ValueError('policy_drift')
    fetch=archive_fetch(path.parent,manifest['archive'])
    with transaction.atomic():
        previous=models.OperationLog.objects.filter(action_type=ACTION,target_type='manifest',target_id=digest).first()
        if previous:return dict(action='replay',manifest_sha256=digest,**json.loads(previous.detail)['report'])
        locked={};handoffs={}
        for pk in ids:
            event,lifecycle=_lock_multisource_event(pk);locked[pk]=event
            if (lifecycle and (lifecycle.manual_pause_reason or lifecycle.claim_token)
                    or event.field_authorities.filter(manual_lock=True).exists()
                    or blocking_multisource_manual_locks(event)):raise ValueError('manual_or_busy')
            tracking=getattr(event,'live_tracking',None)
            if tracking and tracking.active_attempt_token:raise ValueError('claim_busy')
        actual=snapshotter(ids)
        if not baseline_matches(actual,before,rebind_ids):raise ValueError('baseline_drift')
        before=actual
        needing=set(models.RaceDataSyncEnrollment.objects.filter(authority_version=2,state='enrolled').exclude(standing_policy_digest=policy.digest).values_list('event_id',flat=True))
        if needing!=set(rebind_ids):raise ValueError('policy_rebind_incomplete')
        for r in rebind:rebind_multisource_enrollment(event_id=r['event_id'],policy=policy,now=now,expected_route_digest=r['old_route_digest'],apply=True)
        outcomes=[]
        for item in items:
            event=locked.get(item.get('event_id'))
            if event:
                if event.country_region!='united_kingdom':raise ValueError('event_scope')
                enrollment=getattr(event,'race_data_sync_enrollment',None)
                if enrollment:
                    if not item.get('result_rows'):raise ValueError('scheduled_enrollment_requires_handoff')
                    handoffs[event.pk]=control_snapshot(event,lock=True)
                    validate_handoff(event,handoffs[event.pk],region='united_kingdom')
                elif getattr(event,'projection_control',None) and event.projection_control.write_owner not in {'unmanaged','historical'}:raise ValueError('owner_conflict')
                # 固定包逐项声明替换公开投影，旧revision/audit保留；before-image用于精确恢复。
                if item.get('reset_projection') is not True and (event.runners.exists() or event.results.exists()):raise ValueError('projection_reset_not_bound')
                if item.get('reset_projection'):
                    if any(any((r.manual_lock_flags or {}).values()) for r in event.runners.all()):raise ValueError('runner_manual_lock')
                    event.results.all().delete();event.runners.all().delete()
                    event.result_confirmed_at=None
                    event.field_authorities.all().delete()
                    event.source_identities.update(automation_allowed=False,proof_network_allowed=False)
                    event.identity_keys.all().delete()
                    controls=models.RaceEventProjectionControl.objects.filter(event=event)
                    controls.update(current_racecard_revision=None,current_result_revision=None,last_known_good_racecard_revision=None,
                        last_known_good_result_revision=None,last_provisional_result_revision=None)
                    if enrollment:
                        handoffs[event.pk]=control_snapshot(event,lock=True)
                    else:controls.update(write_owner='unmanaged')
            else:
                if models.RaceEvent.objects.filter(slug=item['slug']).exists():raise ValueError('slug_exists')
                spec=item['series'];series=None
                if spec.get('id'):
                    series=models.RaceSeries.objects.select_for_update().get(pk=spec['id'])
                    if series.country_region!='united_kingdom' or canonical_sha(frozen(models.RaceSeries.objects.filter(pk=series.pk).values().get()))!=spec['baseline']:raise ValueError('series_drift')
                    if models.RaceEvent.objects.filter(race_series=series,edition_year=item['year']).exists():raise ValueError('edition_exists')
                else:
                    if models.RaceSeries.objects.filter(key=spec['key']).exists():raise ValueError('series_exists')
                    series=models.RaceSeries.objects.create(key=spec['key'],country_region='united_kingdom',canonical_name_original=spec['name'],
                        review_status='approved',source_refs={'primary':item['source_url'],'manifest_sha256':digest})
                event=models.RaceEvent(year=item['year'],edition_year=item['year'],slug=item['slug'],original_name=item['name'],
                    country_region='united_kingdom',race_series=series)
            event.racecourse=item['racecourse'];_set_fields(event,item['fields'])
            if event.timezone_name!='Europe/London' or event.local_date.year!=event.year:raise ValueError('event_date')
            event.full_clean(exclude=['chinese_name','grade_text','surface']);event.save()
            if item.get('target_id'):
                target=models.HistoricalRaceEventTarget.objects.select_for_update().get(pk=item['target_id'])
                if target.country_region!='united_kingdom' or target.year!=event.year:raise ValueError('target_scope')
                target.event=event;target.race_series=event.race_series;target.local_date=event.local_date;target.racecourse=event.racecourse
                target.source_refs={**target.source_refs,'uk_release_manifest':digest}
                target.resolution_status='imported';target.expectation_status='cancelled' if event.status=='cancelled' else 'held'
                target.full_clean();target.save()
            entry={'event_id':event.pk,'slug':event.slug,'rows':0};outcomes.append(entry)
            if not item.get('result_rows'):continue
            route=route_for(event,policy);value=fetch_bound_observation(event=event,route=route,now=now,fetcher=fetch)
            if len(value['roster'])!=item['result_rows']:raise ValueError('result_count')
            bind_source(event,value,route=route,now=now)
            receipt=ArchivedResultReceipt(digest,archived_result_observation_sha(value))
            decision=attach_multisource_observation(value,policy=policy,now=now,legacy_handoff=handoffs.get(event.pk),archive_receipt=receipt)
            if decision.action not in {'acquired','attached','replay'}:raise ValueError('attach_'+decision.reason_code)
            # 同provider由Free迁移到Pro时，旧checkpoint仍占同一唯一键，必须在同包内换绑。
            models.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event=event,source_key=route.provider,
                data_kind__in=route.capabilities).update(contract_digest=route.contract_digest,registry_digest=route.digest,
                    next_poll_at=now,consecutive_failures=0,circuit_reason='',stale_at=None)
            claims=claim_multisource_events(event_ids=[event.pk],now=now,historical=True)
            if len(claims)!=1:raise ValueError('claim_unavailable')
            outcome=run_multisource_claim(claim=claims[0],now=now,fetcher=fetch,archive_receipt=receipt)
            if not outcome.get('processed'):raise ValueError('result_'+outcome.get('reason','unknown'))
            event.refresh_from_db()
            if event.status!='finished' or event.results.count()!=item['result_rows']:raise ValueError('public_projection_incomplete')
            entry['rows']=event.results.count()
        all_ids=sorted(set(ids)|{e['event_id'] for e in outcomes})
        report={'events':outcomes,'result_rows':sum(e['rows'] for e in outcomes),'rebind_ids':rebind_ids}
        if apply:models.OperationLog.objects.create(action_type=ACTION,target_type='manifest',target_id=digest,
            detail=json.dumps({'before':before,'after':snapshotter(all_ids),'event_ids':all_ids,'report':report},ensure_ascii=False))
        else:transaction.set_rollback(True)
        return dict(action='applied' if apply else 'dry_run_rolled_back',manifest_sha256=digest,**report)


def probe_release_commit(path,expected_sha256):
    from .us_release import probe_release_commit as probe
    return probe(path,expected_sha256,action=ACTION)
