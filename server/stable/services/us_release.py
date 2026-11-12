"""美国精确数据包：离线原件、全包事务、现有多源写入与定向回滚。"""
from .us_public_fields import blocking_multisource_manual_locks
import hashlib
import json
from datetime import date, datetime, time
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone
from stable import models
from .race_data_source_adapters import canonical_sha, load_multisource_policy, fetch_bound_observation, run_multisource_claim
from .race_data_sync_enrollment import _lock_multisource_event, attach_multisource_observation, rebind_multisource_enrollment
from .race_data_sync_control import claim_multisource_events
from .race_source_identity import ArchivedResultReceipt, archived_result_observation_sha, identity_key, resolve_observation
from .race_pre_race import SourceBytes
from .france_release import read_bound
from .france_field_repair import frozen

DIRECT=('RaceEvent','RaceEventRunner','RaceEventResult','RaceEventProjectionControl','RaceEventLifecycleControl',
        'RaceEventLiveTracking','RaceDataSyncEnrollment','RaceResultSourceIdentity','RaceEventIdentityKey','RaceEventFieldAuthority')
PATCH_FIELDS={'local_date','local_start_time','race_datetime','timezone_name','grade_text','normalized_grade',
    'priority','distance_text','surface','normalized_surface','normalized_race_type','going_text','eligibility_text','prize_amount','prize_currency','visibility_status','status','source_refs'}
ACTION='us_release_data'


def snapshot(event_ids):
    data={}
    for name in DIRECT:
        model=getattr(models,name)
        query={'pk__in':event_ids} if name=='RaceEvent' else {'event_id__in':event_ids}
        data[name]=list(model.objects.filter(**query).order_by('pk').values())
    data['RaceDataSyncSourceBinding']=list(models.RaceDataSyncSourceBinding.objects.filter(enrollment__event_id__in=event_ids).order_by('pk').values())
    data['RaceEventLiveProviderCheckpoint']=list(models.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event_id__in=event_ids).order_by('pk').values())
    return frozen(data)


def baseline_matches(current,expected,rebind_ids):
    """旧地区仅换绑控制合同；正常poll时刻不使同一授权范围失效。"""
    rebind_ids=set(rebind_ids)
    stable={
        'RaceEvent':{'id','country_region','local_date','timezone_name','manual_lock_flags'},
        'RaceEventProjectionControl':{'id','event_id','write_owner','owner_generation','owner_manifest_sha256'},
        'RaceEventLifecycleControl':{'id','event_id','mode','manual_pause_reason','enrollment_manifest_sha256','manifest_data'},
        'RaceEventLiveTracking':{'id','event_id','tracking_enabled','source_route_version','selection_reason'},
        'RaceEventLiveProviderCheckpoint':{'id','tracking_id','source_key','data_kind','contract_digest','registry_digest'},
    }
    public={'RaceEventRunner','RaceEventResult','RaceEventFieldAuthority','RaceEventIdentityKey'}
    def narrow(data):
        tracking={r['id']:r['event_id'] for r in data.get('RaceEventLiveTracking',[])}
        enrollment={r['id']:r['event_id'] for r in data.get('RaceDataSyncEnrollment',[])}
        result={}
        for name,rows in data.items():
            result[name]=[]
            for row in rows:
                event=(row['id'] if name=='RaceEvent' else row.get('event_id',tracking.get(row.get('tracking_id'),enrollment.get(row.get('enrollment_id')))))
                if event not in rebind_ids:result[name].append(row);continue
                if name in public:continue
                if name in stable:row={k:v for k,v in row.items() if k in stable[name]}
                else:row={k:v for k,v in row.items() if k!='updated_at'}
                result[name].append(row)
        return result
    return narrow(current)==narrow(expected)


def _guard(event,lifecycle,now):
    if blocking_multisource_manual_locks(event) or event.field_authorities.filter(manual_lock=True).exists():raise ValueError('manual_lock')
    control=getattr(event,'projection_control',None)
    owned=control and control.write_owner=='data_sync' and models.RaceDataSyncEnrollment.objects.filter(event=event,authority_version=2,state='enrolled').exists()
    if lifecycle and (lifecycle.manual_pause_reason or lifecycle.mode not in {'off','shadow'} and not owned
            or lifecycle.claim_token and lifecycle.claim_expires_at and lifecycle.claim_expires_at>now):raise ValueError('lifecycle_busy')
    if control and control.write_owner not in {'unmanaged','data_sync'}:raise ValueError('owner_conflict')
    tracking=getattr(event,'live_tracking',None)
    if tracking and tracking.active_attempt_token and tracking.claim_expires_at and tracking.claim_expires_at>now:raise ValueError('claim_busy')


def archive_fetch(root,spec):
    archive=read_bound(root,spec);pages={}
    for item in archive['documents']:
        url=item['url'];relative=Path(item['file']);path=(root/relative).resolve()
        if url in pages or relative.is_absolute() or not path.is_relative_to(root.resolve()) or (root/relative).is_symlink():raise ValueError('archive_path')
        raw=path.read_bytes()
        if len(raw)>8*1024*1024 or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('archive_digest')
        observed=datetime.fromisoformat(item['fetched_at'])
        if timezone.is_naive(observed):raise ValueError('archive_timestamp')
        pages[url]=SourceBytes(raw,observed_at=observed)
    def fetch(url,**kwargs):
        if url not in pages:raise ValueError('unlisted_source_page')
        return pages[url]
    fetch.archive_program_urls=tuple(url for url in pages if url.startswith('https://www.truenicks.com/articles/'))
    return fetch


def _set_fields(event,fields):
    if set(fields)-PATCH_FIELDS:raise ValueError('unlisted_field')
    for key,value in fields.items():
        if value is not None:
            if key=='local_date':value=date.fromisoformat(value)
            elif key=='local_start_time':value=time.fromisoformat(value)
            elif key=='race_datetime':value=datetime.fromisoformat(value)
        if (event.manual_lock_flags or {}).get(key) and getattr(event,key)!=value:raise ValueError('manual_field_lock')
        setattr(event,key,value)


def _create_or_update(item,locked,digest):
    if item.get('event_id'):
        event=locked[item['event_id']]
        if event.country_region!='united_states':raise ValueError('event_region')
    else:
        if models.RaceEvent.objects.filter(slug=item['slug']).exists():raise ValueError('new_slug_exists')
        series=None
        if not item.get('division_parent_id'):
            spec=item['series']
            if spec.get('id'):
                series=models.RaceSeries.objects.select_for_update().get(pk=spec['id'])
                if canonical_sha(frozen(models.RaceSeries.objects.filter(pk=series.pk).values().get()))!=spec['baseline']:raise ValueError('series_drift')
            else:
                if models.RaceSeries.objects.filter(key=spec['key']).exists():raise ValueError('series_key_exists')
                series=models.RaceSeries.objects.create(key=spec['key'],country_region='united_states',
                    canonical_name_original=spec['name'],review_status='approved',source_refs={'primary':item['source_url'],'manifest_sha256':digest})
            if series.country_region!='united_states' or series.review_status!='approved':raise ValueError('series_scope')
        event=models.RaceEvent(year=item['year'],edition_year=item['year'],slug=item['slug'],original_name=item['name'],
            country_region='united_states',racecourse=item['racecourse'],race_series=series,division_parent_id=item.get('division_parent_id'))
    _set_fields(event,item['fields'])
    if event.local_date and event.local_date.year!=event.year:raise ValueError('event_year')
    event.full_clean(exclude=['chinese_name','grade_text','surface']);event.save()
    return event


def execute(path,expected_sha256,*,apply=False,restore=False,now=None):
    path=Path(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();now=now or timezone.now()
    if digest!=expected_sha256:raise ValueError('manifest_digest')
    manifest=json.loads(raw)
    if (manifest.get('action')!=ACTION or manifest.get('schema_version')!=1
            or not 1<=len(manifest.get('items',[]))+len(manifest.get('rebind',[]))<=1000):
        raise ValueError('manifest_scope')
    if restore:return restore_release(digest,apply=apply,now=now)
    items=manifest['items'];existing=[i['event_id'] for i in items if i.get('event_id')]
    if len(existing)!=len(set(existing)):raise ValueError('duplicate_event')
    new_slugs=[i['slug'] for i in items if not i.get('event_id')]
    if len(new_slugs)!=len(set(new_slugs)):raise ValueError('duplicate_slug')
    rebind=manifest.get('rebind',[]);rebind_ids=[r['event_id'] for r in rebind]
    if len(rebind_ids)!=len(set(rebind_ids)):raise ValueError('rebind_scope')
    ids=sorted(set(existing)|set(rebind_ids))
    if any(i.get('division_parent_id') not in existing for i in items if i.get('division_parent_id')):raise ValueError('parent_scope')
    before=read_bound(path.parent,manifest['baseline'])
    policy=load_multisource_policy(now=now)
    if not policy.valid(now) or policy.digest!=manifest['policy_digest']:raise ValueError('policy_drift')
    fetch=archive_fetch(path.parent,manifest['archive'])
    with transaction.atomic():
        previous=models.OperationLog.objects.filter(action_type=ACTION,target_type='manifest',target_id=digest).first()
        if previous:return {'action':'replay','manifest_sha256':digest,**json.loads(previous.detail)['report']}
        locked={}
        for pk in ids:
            event,lifecycle=_lock_multisource_event(pk);_guard(event,lifecycle,now);locked[pk]=event
        actual_before=snapshot(ids)
        if not baseline_matches(actual_before,before,set(rebind_ids)-set(existing)):raise ValueError('baseline_drift')
        before=actual_before
        # 发布前应暂停调度并排空在途；全局policy扩版必须覆盖所有仍在登记的旧策略目标。
        needing=set(models.RaceDataSyncEnrollment.objects.filter(authority_version=2,state='enrolled').exclude(standing_policy_digest=policy.digest).values_list('event_id',flat=True))
        if needing!=set(rebind_ids):raise ValueError('policy_rebind_incomplete')
        for entry in rebind:
            rebind_multisource_enrollment(event_id=entry['event_id'],policy=policy,now=now,expected_route_digest=entry['old_route_digest'],apply=True)
        events=[];outcomes=[];expected={};archive_receipts={}
        for item in items:
            event=_create_or_update(item,locked,digest);events.append(event)
            if item.get('schedule'):
                from .us_stakes_schedule import apply_schedule_locked
                from .us_pre_race import route_for
                if not apply_schedule_locked(event,item['schedule'],route=route_for(event,policy),now=now):
                    raise ValueError('schedule_not_applied')
            outcomes.append({'event_id':event.pk,'slug':event.slug,'rows':0})
            if not item.get('result_rows'):continue
            from .us_pre_race import route_for
            route=route_for(event,policy)
            value=fetch_bound_observation(event=event,route=route,now=now,fetcher=fetch)
            now=timezone.now()
            key=identity_key(value)
            if not key:raise ValueError('strong_identity_missing')
            current=models.RaceEventIdentityKey.objects.filter(namespace=key['namespace'],key_sha256=key['key_sha256']).first()
            if current and current.event_id!=event.pk:raise ValueError('identity_conflict')
            if not current:models.RaceEventIdentityKey.objects.create(event=event,evidence={'manifest_sha256':digest},**key)
            receipt=ArchivedResultReceipt(manifest_sha256=digest,observation_sha256=archived_result_observation_sha(value))
            match=resolve_observation(value,route=route,now=now,archive_receipt=receipt)
            if match.status!='exact' or match.event_id!=event.pk:
                raise ValueError(f'result_identity:{event.pk}:{match.reason or match.status}')
            if len(value['roster'])!=item['result_rows']:raise ValueError('result_count')
            decision=attach_multisource_observation(value,policy=policy,now=now,archive_receipt=receipt)
            if decision.action not in {'acquired','attached','replay'}:raise ValueError('attach_'+decision.reason_code)
            expected[event.pk]=item['result_rows']
            archive_receipts[event.pk]=receipt
            outcomes[-1]['archive_replay']=receipt.evidence(value)
        # 逐场临执行领取，避免前面解析/写入消耗尚未执行目标的租约；仍逐一核对全清单。
        for event_id in expected:
            now=timezone.now()
            claims=claim_multisource_events(event_ids=[event_id],now=now,historical=True)
            if {c.event_id for c in claims}!={event_id}:raise ValueError('historical_claim_incomplete')
            for claim in claims:
                result=run_multisource_claim(claim=claim,now=timezone.now(),fetcher=fetch,
                    archive_receipt=archive_receipts[event_id])
                if not result.get('processed'):
                    raise ValueError(f"result_{result.get('reason','unknown')}:{event_id}:{result.get('identity_reason','')}")
                event=models.RaceEvent.objects.get(pk=claim.event_id)
                if event.status!='finished' or event.results.count()!=expected[event.pk]:raise ValueError('public_projection_incomplete')
                next(o for o in outcomes if o['event_id']==event.pk)['rows']=event.results.count()
        all_ids=sorted(set(ids)|{e.pk for e in events})
        report={'events':outcomes,'result_rows':sum(o['rows'] for o in outcomes),'rebind_ids':rebind_ids}
        after=snapshot(all_ids)
        if apply:
            models.OperationLog.objects.create(action_type=ACTION,target_type='manifest',target_id=digest,
                detail=json.dumps({'before':before,'after':after,'event_ids':all_ids,'report':report},ensure_ascii=False))
        else:transaction.set_rollback(True)
        return dict(action='applied' if apply else 'dry_run_rolled_back',manifest_sha256=digest,**report)


def probe_release_commit(path, expected_sha256):
    """等待同包事务结束后查询数据库收据，不依赖命令输出文件。"""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('manifest_digest')
    manifest = json.loads(raw)
    if manifest.get('action') != ACTION or manifest.get('schema_version') != 1:
        raise ValueError('manifest_scope')
    ids = {item['event_id'] for item in manifest['items'] if item.get('event_id')}
    ids.update(item['event_id'] for item in manifest.get('rebind', []))
    if not ids or len(ids) > 1000 or any(type(pk) is not int or pk <= 0 for pk in ids):
        raise ValueError('commit_probe_anchor_scope')
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='20s'")
                cursor.execute("SET LOCAL statement_timeout='25s'")
        # apply 先按同样顺序锁住这些既有赛事，再写入事务收据。
        # 锁未释放时不能把尚不可见的收据误判为未提交。
        locked = list(models.RaceEvent.objects.select_for_update().filter(pk__in=ids)
                      .order_by('pk').values_list('pk', flat=True))
        if set(locked) != ids:
            raise ValueError('commit_probe_anchor_missing')
        receipts = list(models.OperationLog.objects.filter(
            action_type=ACTION, target_type='manifest', target_id=expected_sha256,
        ).values_list('pk', flat=True)[:2])
        if len(receipts) > 1:
            raise ValueError('commit_probe_receipt_ambiguous')
        return {'action': 'commit_probe', 'manifest_sha256': expected_sha256,
                'committed': bool(receipts)}


def restore_release(digest,*,apply,now):
    """精确after-image CAS；恢复公开数据及旧控制面，新增审计/版本留存但停止发布。"""
    with transaction.atomic():
        receipt=models.OperationLog.objects.select_for_update().get(action_type=ACTION,target_type='manifest',target_id=digest)
        saved=json.loads(receipt.detail);ids=saved['event_ids']
        if models.OperationLog.objects.filter(action_type='us_release_restore',target_id=digest).exists():return {'action':'restore_replay'}
        for pk in ids:
            event,lifecycle=_lock_multisource_event(pk);_guard(event,lifecycle,now)
        if snapshot(ids)!=saved['after']:raise ValueError('restore_after_image_drift')
        before=saved['before']
        # 先移除本包新增投影行，释放(event, position / external id)唯一键，再恢复旧主键。
        for name in ('RaceEventRunner','RaceEventResult','RaceEventFieldAuthority','RaceEventIdentityKey'):
            model=getattr(models,name);old={r['id'] for r in before[name]}
            model.objects.filter(event_id__in=ids).exclude(pk__in=old).delete()
        # 保留的新版revision/observation仅作审计，不再由current指针引用。
        for name,rows in before.items():
            model=getattr(models,name)
            for row in rows:
                values={}
                for key,value in row.items():
                    field=next(f for f in model._meta.concrete_fields if f.attname==key)
                    values[key]=field.to_python(value) if not field.is_relation else value
                pk=values.pop('id')
                if name=='RaceEvent':
                    # 身份恢复仍走集中save校验和路径同步；其余快照字段精确恢复，避免auto_now改写备份。
                    model.objects.update_or_create(pk=pk,defaults=values)
                    model.objects.filter(pk=pk).update(**{k:v for k,v in values.items() if k not in models.RaceEventQuerySet.IDENTITY_FIELDS})
                elif not model.objects.filter(pk=pk).update(**values):
                    model(pk=pk,**values).save_base(raw=True,force_insert=True)
        old_events={r['id'] for r in before['RaceEvent']}
        for name in ('RaceDataSyncSourceBinding','RaceEventLiveProviderCheckpoint','RaceDataSyncEnrollment'):
            model=getattr(models,name);old={r['id'] for r in before[name]}
            owned={r['id'] for r in saved['after'][name]}
            model.objects.filter(pk__in=owned-old).delete()
        for row in saved['after']['RaceResultSourceIdentity']:
            if row['id'] not in {r['id'] for r in before['RaceResultSourceIdentity']}:
                models.RaceResultSourceIdentity.objects.filter(pk=row['id']).update(automation_allowed=False,proof_network_allowed=False)
        for name,updates in [
            ('RaceEventLiveTracking',{'tracking_enabled':False,'active_attempt_token':'','claim_expires_at':None,'next_poll_at':None}),
            ('RaceEventLifecycleControl',{'mode':'off','next_refresh_at':None,'claim_token':'','claim_expires_at':None}),
            ('RaceEventProjectionControl',{'write_owner':'unmanaged','current_racecard_revision_id':None,'current_result_revision_id':None,
                'last_known_good_racecard_revision_id':None,'last_known_good_result_revision_id':None,'last_provisional_result_revision_id':None})]:
            old={r['id'] for r in before[name]}
            getattr(models,name).objects.filter(event_id__in=ids).exclude(pk__in=old).update(**updates)
        models.RaceEvent.objects.filter(pk__in=set(ids)-old_events).update(visibility_status='draft',division_parent=None)
        # 老控制行的序号不能退到已保留审计版本之前。
        for row in saved['after']['RaceEventProjectionControl']:
            control=models.RaceEventProjectionControl.objects.get(pk=row['id'])
            control.next_racecard_revision_no=max(control.next_racecard_revision_no,row['next_racecard_revision_no'])
            control.next_result_revision_no=max(control.next_result_revision_no,row['next_result_revision_no'])
            control.save(update_fields=['next_racecard_revision_no','next_result_revision_no'])
        if apply:models.OperationLog.objects.create(action_type='us_release_restore',target_type='manifest',target_id=digest,detail=json.dumps({'event_ids':ids}))
        else:transaction.set_rollback(True)
        return {'action':'restored' if apply else 'restore_dry_run_rolled_back','manifest_sha256':digest,'event_ids':ids}
