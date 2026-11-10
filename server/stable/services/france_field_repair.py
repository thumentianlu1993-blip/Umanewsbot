"""固定法国字段清单的计划、事务修复和带证据CAS的恢复；不重放名单/状态。"""
import copy
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q, Max
from stable import models
from .france_basic_fields import GROUP_FIELDS, basic_sha, digest, validate_basic, apply_basic_locked
from .france_release import read_bound
from .france_pre_race_authority import lock_context, write_reason
from .race_data_source_adapters import load_multisource_policy
from .race_data_sync_enrollment import _lock_multisource_event
from .race_event_public_cache import invalidate_public_race_cache

TIME_FIELDS = ('race_datetime','local_date','local_start_time','timezone_name')
CARD_FIELDS = ('trainer_name','carried_weight','odds_value')
CARD_REFS = ('allocated_weight','adjusted_weight','odds_source','odds_observed_at','france_card_fields')


class SnapshotEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(timezone.utc).isoformat(timespec='microseconds')
        return super().default(value)


def frozen(value):
    # 比较时刻而非输入偏移；保留完整微秒，避免DB转UTC后的假漂移或精度丢失。
    return json.loads(json.dumps(value,cls=SnapshotEncoder))


def fields_for(item):
    return tuple(sorted({name for group in item['groups'] for name in GROUP_FIELDS[group]} |
                        (set(TIME_FIELDS) if item.get('time') else set())))


def refs_slice(event, groups):
    refs=event.source_refs or {};basic=refs.get('france_basic_v1',{})
    result={'basic':{k:v for k,v in basic.get('fields',{}).items() if k in groups}}
    if result['basic']:
        result['basic_identity']=basic.get('identity');result['basic_version']=basic.get('version')
    if 'distance' in groups:
        result['units']={k:v for k,v in refs.get('field_units',{}).items() if k=='distance_text'}
    return result


def card_refs_slice(runner):
    refs=runner.source_refs or {}
    return {**{k:refs[k] for k in CARD_REFS if k in refs},
        'field_units':{k:v for k,v in refs.get('field_units',{}).items() if k in ('carried_weight','odds_value')}}


def subject_query(event, item):
    query=Q(subject_type='event',subject_key=str(event.pk),field_name__in=fields_for(item))
    for row in item.get('runners',[]):
        runner=event.runners.select_for_update().get(pk=row['runner_id'])
        keys={row['external_runner_id'],runner.external_runner_id,'geny:'+row['external_runner_id']}
        query |= Q(subject_type='participant',subject_key__in=keys,field_name__in=CARD_FIELDS)
    return query


def snapshot(context,item):
    event=context.event;query=subject_query(event,item)
    runners=[]
    for spec in item.get('runners',[]):
        row=event.runners.select_for_update().get(pk=spec['runner_id'])
        runners.append(dict(id=row.pk,horse_name=row.horse_name,horse_number=row.horse_number,
            external_runner_id=spec['external_runner_id'],runner_external_runner_id=row.external_runner_id,
            manual_lock_flags=row.manual_lock_flags,
            values={f:getattr(row,f) for f in CARD_FIELDS},refs=card_refs_slice(row)))
    values=dict(event={f:getattr(event,f) for f in fields_for(item)},refs=refs_slice(event,item['groups']),runners=runners)
    guards=copy.deepcopy(context.guards)
    # 持久CAS不绑定已结束任务的领取计数；执行时仍持锁并拒绝活跃正式claim。
    if guards['tracking'] is not None:
        guards['tracking'].pop('claim_generation',None)
    return frozen(dict(values=values,guards=guards,
        identity={f:getattr(event,f) for f in ('pk','country_region','local_date','original_name','racecourse','status','manual_lock_flags')},
        authorities=list(event.field_authorities.select_for_update().filter(query).order_by('subject_type','subject_key','field_name').values()),
        last_change=event.field_changes.filter(query).aggregate(last=Max('pk'))['last']))


def _source(context,item,packet,policy,now):
    basic=packet['basic'];event=context.event
    provider='geny' if basic['source_url'].startswith('https://www.geny.com/') else 'france_galop'
    routes=[r for r in policy.routes if r.provider==provider and r.region=='france' and r.permits_url(basic['source_url'])]
    if len(routes)!=1 or not routes[0].valid(now):
        raise ValueError('repair_source_route')
    route=routes[0]
    source_id=item.get('source_identity_id')
    if source_id:
        source=models.RaceResultSourceIdentity.objects.select_for_update().get(pk=source_id,event=event)
        if (source.source_key!=provider or source.region_code!='france' or source.review_status!='approved'
            or source.terms_status!='approved' or not source.automation_allowed):
            raise ValueError('repair_source_identity')
        from .race_data_sync_admission import binding_admission_reason
        binding=models.RaceDataSyncSourceBinding.objects.filter(source_identity=source,state='active').first()
        if binding is None or binding_admission_reason(binding=binding,route=route,now=now):
            raise ValueError('repair_binding_drift')
    else:
        if context.enrollment is not None:
            raise ValueError('repair_source_identity_required')
        source=SimpleNamespace(source_key=provider,external_race_id=basic['identity'].get('external_race_id',''),canonical_url=basic['source_url'])
    validate_basic(basic,sha=basic_sha(basic),provider=provider,region='france',external_id=source.external_race_id,event=event)
    return source,route


def _apply_item(context,item,packet,policy,now,manifest_sha):
    from .race_data_sync_pipeline import RaceDataSyncFlags, _apply_schedule_fields_locked
    source,route=_source(context,item,packet,policy,now)
    event=context.event;basic=packet['basic'];flags=RaceDataSyncFlags.from_settings()
    admitted={'france_basic.'+g for g in item['groups'] if flags.allows(provider=source.source_key,region='france',field_name='france_basic.'+g)}
    if len(admitted)!=len(item['groups']):
        raise ValueError('repair_runtime_admission_closed')
    audit=dict(run_id=manifest_sha,trigger_task='france_field_repair')
    # 同一合同校验全包，但只应用manifest明确列出的字段组。
    selected={**basic,'fields':{k:v for k,v in basic['fields'].items() if k in item['groups']}}
    if set(selected['fields'])!=set(item['groups']):
        raise ValueError('repair_source_field_missing')
    decisions=apply_basic_locked(event=event,basic=selected,source=source,source_class=route.source_class,
        admitted_fields=admitted,audit=audit,now=now)
    if any(v not in {'applied','replayed'} for v in decisions.values()):
        raise ValueError('repair_field_conflict:'+str(decisions))
    if item.get('time'):
        if event.status!='finished':
            raise ValueError('repair_time_requires_historical_terminal')
        proof=packet.get('time_evidence',{})
        if (proof.get('source_timezone') not in {'Europe/Paris','Asia/Shanghai'} or proof.get('kind')!='scheduled_start'
            or proof.get('raw_sha256')!=basic['raw_sha256']):
            raise ValueError('repair_time_evidence')
        stamp=datetime.fromisoformat(packet['off_time']);local=stamp.astimezone(ZoneInfo('Europe/Paris'))
        if stamp.tzinfo is None or local.date()!=event.local_date or local.hour==local.minute==0:
            raise ValueError('repair_time_invalid')
        if not flags.schedule_apply_enabled or not all(flags.allows(provider=source.source_key,region='france',field_name=f)
            for f in ('off_time','local_start_time','timezone_name')):
            raise ValueError('repair_time_admission')
        _apply_schedule_fields_locked(event=event,source=source,
            payload=dict(off_time=stamp.isoformat(),local_start_time=local.strftime('%H:%M:%S'),timezone_name='Europe/Paris'),
            observation=None,lifecycle=context.lifecycle,locked_claim=context,admitted_fields={'off_time','local_start_time','timezone_name'},
            allow_schedule_apply=True,processed_fields=set(),audit={**audit,'source_key':source.source_key,'source_url':basic['source_url']},
            candidate_watermark=datetime.fromisoformat(basic['observed_at']),candidate_source_class=route.source_class,reschedule=False)
        if event.race_datetime!=stamp or event.local_start_time!=local.time().replace(tzinfo=None):
            raise ValueError('repair_time_conflict')
    if item.get('runners'):
        from .france_public_fields import fill_card_gaps_locked
        from .race_data_sync_results import runner_slot_identity_matches
        observation=models.RaceResultObservation.objects.get(pk=item['observation_id'],source_identity=source)
        rows={row['external_runner_id']:row for row in packet.get('card_rows',[])}
        for spec in item['runners']:
            runner=event.runners.select_for_update().get(pk=spec['runner_id']);row=rows[spec['external_runner_id']]
            if runner.horse_number!=row['number'] or not runner_slot_identity_matches(event=event,source=source,runner=runner,
                external_runner_id=row['external_runner_id'],horse_name=row['horse_name']):
                raise ValueError('repair_runner_identity')
            decisions=fill_card_gaps_locked(event=event,runner=runner,row=row,source=source,observation=observation,now=now)
            if any(v not in {'applied','replayed'} for v in decisions.values()):
                raise ValueError('repair_runner_conflict')


def _restore_values(context,item,before,now,manifest_sha):
    event=context.event;values=before['values'];refs=copy.deepcopy(event.source_refs or {})
    current=dict(refs.get('france_basic_v1') or {});fields=dict(current.get('fields') or {})
    for group in item['groups']:
        fields.pop(group,None)
    fields.update(values['refs']['basic'])
    if fields:
        current.update(version=values['refs'].get('basic_version',current.get('version',1)),
            identity=values['refs'].get('basic_identity',current.get('identity')),fields=fields)
        refs['france_basic_v1']=current
    else:
        refs.pop('france_basic_v1',None)
    if 'distance' in item['groups']:
        units=dict(refs.get('field_units') or {});units.pop('distance_text',None);units.update(values['refs'].get('units',{}))
        if units:refs['field_units']=units
        else:refs.pop('field_units',None)
    for name,value in values['event'].items():
        old=getattr(event,name)
        setattr(event,name,event._meta.get_field(name).to_python(value))
        models.RaceEventFieldChange.objects.create(event=event,subject_type='event',subject_key=str(event.pk),field_name=name,
            old_value=frozen(old),new_value=value,applied=True,decision='applied',operation_mode='france_restore',run_id=manifest_sha)
    event.source_refs=refs;event.save(update_fields=(*values['event'],'source_refs','updated_at'))
    for saved in values['runners']:
        runner=event.runners.get(pk=saved['id']);rrefs=dict(runner.source_refs or {})
        for name,value in saved['values'].items():
            models.RaceEventFieldChange.objects.create(event=event,subject_type='participant',subject_key=saved['external_runner_id'],field_name=name,
                old_value=getattr(runner,name),new_value=value,applied=True,decision='applied',operation_mode='france_restore',run_id=manifest_sha)
            setattr(runner,name,value)
        for key in CARD_REFS:
            rrefs.pop(key,None)
        units=dict(rrefs.get('field_units') or {})
        for key in ('carried_weight','odds_value'):units.pop(key,None)
        units.update(saved['refs'].get('field_units',{}));rrefs.update(saved['refs']);rrefs['field_units']=units
        runner.source_refs=rrefs;runner.save(update_fields=(*CARD_FIELDS,'source_refs','updated_at'))
    query=subject_query(event,item)
    previous={row['id']:row for row in before['authorities']}
    for authority in event.field_authorities.select_for_update().filter(query):
        row=previous.pop(authority.pk,None)
        if row is None:
            authority.delete()
        else:
            for key,value in row.items():
                if key in {'id','created_at','updated_at'}:continue
                field=next(f for f in authority._meta.fields if f.attname==key)
                setattr(authority,key,value if field.is_relation else field.to_python(value))
            authority.save()
    if previous:
        raise ValueError('restore_authority_missing')
    transaction.on_commit(invalidate_public_race_cache)


def execute_repair(root,manifest,manifest_sha,*,apply,restore,now):
    items=manifest.get('items',[]);scope=manifest.get('scope',{})
    if (manifest.get('schema_version')!=1 or not 1<=len(items)<=80 or scope.get('country_region')!='france'
        or sorted(scope.get('event_ids',[]))!=sorted(i['event_id'] for i in items)
        or len(set(scope['event_ids']))!=len(items)):
        raise ValueError('repair_scope')
    start,end=date.fromisoformat(scope['date_from']),date.fromisoformat(scope['date_to'])
    if start>end:raise ValueError('repair_dates')
    for item in items:
        groups=item.get('groups')
        if not isinstance(groups,list) or len(set(groups))!=len(groups) or set(groups)-set(GROUP_FIELDS):
            raise ValueError('repair_fields')
        if not groups and not item.get('time') and not item.get('runners'):raise ValueError('repair_empty')
        if len(item.get('runners',[]))>80:raise ValueError('repair_runner_scope')
        runners=item.get('runners',[])
        if len({r['runner_id'] for r in runners})!=len(runners) or len({r['external_runner_id'] for r in runners})!=len(runners):
            raise ValueError('repair_duplicate_runner')
    if sum(len(item.get('runners',[])) for item in items)>80:raise ValueError('repair_runner_scope')
    policy=load_multisource_policy(now=now)
    if not policy.valid(now) or policy.digest!=manifest['policy_digest']:raise ValueError('policy_drift')
    with transaction.atomic():
        contexts={}
        for item in sorted(items,key=lambda i:i['event_id']):
            event,lifecycle=_lock_multisource_event(item['event_id']);context=lock_context(event,lifecycle)
            if event.country_region!='france' or not start<=event.local_date<=end:raise ValueError('repair_event_scope')
            reason=write_reason(context,now=now,capability=None)
            if reason or any((event.manual_lock_flags or {}).values()):raise ValueError(reason or 'manual_lock')
            contexts[event.pk]=context
        receipt=models.OperationLog.objects.filter(action_type='france_field_repair',target_type='manifest',target_id=manifest_sha).first()
        restored=models.OperationLog.objects.filter(action_type='france_field_restore',target_type='manifest',target_id=manifest_sha).first()
        if restored:
            if restore:return {'action':'restore_replay','manifest_sha256':manifest_sha}
            raise ValueError('repair_already_restored')
        if receipt and not restore:
            return {'action':'replay','manifest_sha256':manifest_sha}
        events=[]
        if restore:
            if not receipt:raise ValueError('repair_receipt_missing')
            saved={entry['event_id']:entry for entry in json.loads(receipt.detail)['events']}
            # 先校验全包，再还原；失败不产生部分恢复。
            for item in items:
                context=contexts[item['event_id']]
                if snapshot(context,item)!=saved[item['event_id']]['after']:
                    raise ValueError('restore_after_image_drift')
            for item in items:
                _restore_values(contexts[item['event_id']],item,saved[item['event_id']]['before'],now,manifest_sha)
            result=dict(action='restored' if apply else 'restore_dry_run_rolled_back',manifest_sha256=manifest_sha)
            if apply:models.OperationLog.objects.create(action_type='france_field_restore',target_type='manifest',target_id=manifest_sha,detail=json.dumps(result))
        else:
            for item in items:
                context=contexts[item['event_id']];before=snapshot(context,item)
                if item.get('before_sha256') and digest(before)!=item['before_sha256']:raise ValueError('repair_before_image_drift')
                if apply and (not item.get('before_sha256') or not item.get('expected_values')):raise ValueError('repair_plan_required')
                packet=read_bound(root,item['source'])
                _apply_item(context,item,packet,policy,now,manifest_sha)
                after=snapshot(context,item)
                if item.get('expected_values') and after['values']!=item['expected_values']:raise ValueError('repair_expected_values_drift')
                events.append(dict(event_id=item['event_id'],before_sha256=digest(before),after_values=after['values'],before=before,after=after))
            result=dict(action='applied' if apply else 'dry_run_rolled_back',manifest_sha256=manifest_sha,events=events)
            if apply:models.OperationLog.objects.create(action_type='france_field_repair',target_type='manifest',target_id=manifest_sha,detail=json.dumps(result))
        if not apply:transaction.set_rollback(True)
        return result
