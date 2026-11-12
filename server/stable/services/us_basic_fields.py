"""美国目录条件、总奖金及比赛用时的来源合同与受限投影。"""
from decimal import Decimal
import re


def catalogue_values(target):
    values={}
    if target.get('provider')=='nsa' and target.get('distance_text'):values['distance_text']=target['distance_text']
    purse=str(target.get('purse_raw','')).strip()
    if re.fullmatch(r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\$\d+(?:\.\d{2})?',purse):
        values.update(prize_amount=purse[1:].replace(',',''),prize_currency='USD')
    age=str(target.get('age_condition','')).strip()
    sex=str(target.get('sex_condition','')).strip().upper()
    match=re.fullmatch(r'(\d{1,2})(U)?',age)
    if match and sex in {'','F','F&M','F & M'}:
        values['eligibility_text']=match[1]+'yo'+('+' if match[2] else '')+(' fillies' if sex else '')
    return values


def nsa_overnight_catalogue(card):
    text=card['conditions_raw']
    purse=re.search(r'Purse\s+(\$[\d,]+)',text)
    distance=re.search(r'(?i)\b(About\s+)?([1-4]\s+[1-9]/(?:2|4|8|16)|[1-4])\s+Miles',text)
    distance_text=(('about ' if distance[1] else '')+distance[2]+' miles') if distance else ''
    if re.search(r'Two Miles And Three Eighths',text,re.I):distance_text='2 3/8 miles'
    words={'One':1,'Two':2,'Three':3,'Four':4,'Five':5,'Six':6,'Seven':7}
    extra=re.search(r'Two Miles and (One|Two|Three|Four|Five|Six|Seven) Furlongs',text,re.I)
    if extra:distance_text='2 '+str(words[extra[1].title()])+'/8 miles'
    age='4U' if re.search(r'Four Years? Olds? [Aa][Nn][Dd] Upward',text,re.I) else ''
    sex='F&M' if re.search(r'Fillies and Mares',text,re.I) else ''
    return dict(provider='nsa',local_date=card['local_date'],venue=card['venue'],purse_raw=purse[1] if purse else '',
        distance_text=distance_text,age_condition=age,sex_condition=sex,conditions_raw=text,
        source_url=card['source_url'],raw_sha256=card['raw_sha256'])


def apply_metadata_locked(*, event, source, observation, now, source_class):
    from stable import models
    from .race_data_source_adapters import canonical_sha, aware, require_sha
    from .race_data_sync_pipeline import RaceDataSyncFlags, _audit_defaults
    from .race_data_sync_policy import arbitrate_source_value, source_priority
    from .us_public_fields import us_source
    from .us_venues import VENUES
    if not us_source(source):raise ValueError('us_metadata_source')
    meta=observation.field_provenance.get('us_race_metadata')
    if not meta:return
    if meta.get('external_race_id')!=source.external_race_id or meta.get('local_date')!=str(event.local_date):
        raise ValueError('us_metadata_identity')
    require_sha(meta['source_sha256']);observed=aware(meta['observed_at'])
    if observed>now:raise ValueError('us_metadata_future')
    flags=RaceDataSyncFlags.from_settings();changed=set();refs=dict(event.source_refs or {})
    apply_actual_time_locked(event=event,source=source,observation=observation,meta=meta,now=now,source_class=source_class)
    target=meta.get('catalogue') or {}
    values=catalogue_values(target)
    if target and (target.get('local_date')!=str(event.local_date) or target.get('venue')!=source.external_race_id.split(':')[0]):
        raise ValueError('us_catalogue_identity')
    groups=[('prize',{'prize_amount':Decimal(values['prize_amount']),'prize_currency':'USD'})] if 'prize_amount' in values else []
    if 'distance_text' in values:groups.append(('distance',{'distance_text':values['distance_text']}))
    if 'eligibility_text' in values:groups.append(('eligibility',{'eligibility_text':values['eligibility_text']}))
    audit=_audit_defaults(observation=observation,task_id='us_result_basic',run_id='')
    for group,fields in groups:
        if not flags.allows(provider=source.source_key,region=source.region_code,field_name='us_basic.'+group):continue
        authorities={};deny=False
        announced=refs.get('us_pre_race_schedule',{})
        phase_upgrade=(group=='prize' and announced.get('prize_stage')=='announced'
            and announced.get('local_date')==str(event.local_date)
            and announced.get('candidate_key')==(refs.get('us_target_v1') or {}).get('candidate_key'))
        for field,candidate in fields.items():
            old=getattr(event,field)
            authority=event.field_authorities.select_for_update().filter(subject_type='event',subject_key=str(event.pk),field_name=field).first()
            authorities[field]=authority
            render=lambda value:str(value) if isinstance(value,Decimal) else value
            prior=announced.get(field)
            if field=='prize_amount' and prior is not None:prior=Decimal(prior)
            upgrade=(phase_upgrade and authority is not None and authority.source_key=='us_racing_schedule'
                and old==prior and authority.value_sha256==canonical_sha(render(prior)))
            decision=arbitrate_source_value(current_source_key=authority.source_key if authority and not upgrade else '',
                current_source_class=authority.source_class if authority and not upgrade else '',current_observed_at=authority.observed_at if authority and not upgrade else None,
                candidate_source_key=source.source_key,candidate_source_class=source_class,candidate_observed_at=observed,
                has_current_value=old not in (None,''),values_equal=old==candidate,
                manual_locked=bool((event.manual_lock_flags or {}).get('basic') or (event.manual_lock_flags or {}).get(field) or authority and authority.manual_lock))
            if not decision.apply and decision.reason_code!='idempotent_replay':deny=True
        if deny:continue
        for field,candidate in fields.items():
            old=getattr(event,field)
            if old==candidate and not phase_upgrade:continue
            render=lambda value:str(value) if isinstance(value,Decimal) else value
            models.RaceEventFieldChange.objects.create(event=event,subject_type='event',subject_key=str(event.pk),field_name=field,
                old_value=render(old),new_value=render(candidate),applied=True,decision='applied',
                **{**audit,'source_key':source.source_key,'source_url':target['source_url'],'source_class':source_class,
                   'authority_level':source_priority(source_class),'raw_sha256':target['raw_sha256'],'operation_mode':'us_basic'})
            authority=authorities[field] or models.RaceEventFieldAuthority(event=event,subject_type='event',subject_key=str(event.pk),field_name=field)
            authority.source_key=source.source_key;authority.source_class=source_class;authority.source_url=target['source_url']
            authority.external_id=source.external_race_id;authority.observed_at=observed
            authority.authority_level=source_priority(source_class);authority.value_sha256=canonical_sha(render(candidate));authority.save()
            setattr(event,field,candidate);changed.add(field)
        if phase_upgrade:
            refs['us_pre_race_schedule']={**announced,'prize_stage':'superseded_by_result'};changed.add('source_refs')
    if (flags.allows(provider=source.source_key,region=source.region_code,field_name='us_basic.race_metadata')
        and not (event.manual_lock_flags or {}).get('basic') and refs.get('us_race_metadata')!=meta):
        refs['us_race_metadata']=meta;changed.add('source_refs')
    if changed:
        event.source_refs=refs
        event.save(update_fields=changed|{'updated_at'})


def apply_actual_time_locked(*, event, source, observation, meta, now, source_class):
    """已通过赛果发布检查的实际时刻投影；不以计划时间代填。"""
    from zoneinfo import ZoneInfo
    from stable import models
    from .race_data_source_adapters import aware, canonical_sha, require_sha
    from .race_data_sync_pipeline import RaceDataSyncFlags, _audit_defaults
    from .race_data_sync_policy import arbitrate_source_value, source_priority
    from .us_venues import VENUES
    flags=RaceDataSyncFlags.from_settings()
    if not flags.schedule_apply_enabled or not all(flags.allows(provider=source.source_key,region=source.region_code,field_name=f)
        for f in ('off_time','local_start_time','timezone_name')):return False
    stamp=meta.get('off_time')
    if not stamp:return False
    stamp=aware(stamp)
    if stamp!=aware(observation.normalized_payload.get('off_time')):raise ValueError('us_actual_clock_mismatch')
    zone=VENUES[source.external_race_id.split(':')[0]][2]
    local=stamp.astimezone(ZoneInfo(zone))
    if local.date()!=event.local_date or stamp>now:raise ValueError('us_actual_clock_date')
    evidence=meta['field_sources']['off_time'];require_sha(evidence['sha256'])
    proposed=dict(race_datetime=stamp,local_start_time=local.time(),timezone_name=zone)
    lock_fields=set(proposed)|{'basic','race_time','off_time','local_date'}
    if any((event.manual_lock_flags or {}).get(f) for f in lock_fields) or event.field_authorities.filter(
        subject_type='event',field_name__in=lock_fields,manual_lock=True).exists():return False
    authorities={};observed=aware(meta['observed_at'])
    render=lambda v:v.isoformat() if hasattr(v,'isoformat') else v
    for field,candidate in proposed.items():
        old=getattr(event,field)
        authority=event.field_authorities.select_for_update().filter(subject_type='event',subject_key=str(event.pk),field_name=field).first()
        authorities[field]=authority
        decision=arbitrate_source_value(current_source_key=authority.source_key if authority else '',
            current_source_class=authority.source_class if authority else '',current_observed_at=authority.observed_at if authority else None,
            candidate_source_key=source.source_key,candidate_source_class=source_class,candidate_observed_at=observed,
            has_current_value=old not in (None,''),values_equal=old==candidate,manual_locked=False)
        if not decision.apply and decision.reason_code!='idempotent_replay':return False
    audit=_audit_defaults(observation=observation,task_id='us_result_actual_time',run_id='')
    changed=[]
    for field,candidate in proposed.items():
        old=getattr(event,field);authority=authorities[field]
        if old!=candidate:
            models.RaceEventFieldChange.objects.create(event=event,subject_type='event',subject_key=str(event.pk),field_name=field,
                old_value=render(old),new_value=render(candidate),applied=True,decision='applied',
                **{**audit,'source_key':source.source_key,'source_url':evidence['url'],'source_class':source_class,
                   'authority_level':source_priority(source_class),'raw_sha256':evidence['sha256'],'operation_mode':'us_actual_time'})
            setattr(event,field,candidate);changed.append(field)
        authority=authority or models.RaceEventFieldAuthority(event=event,subject_type='event',subject_key=str(event.pk),field_name=field)
        authority.source_key=source.source_key;authority.source_class=source_class;authority.source_url=evidence['url']
        authority.external_id=source.external_race_id;authority.observed_at=observed
        authority.authority_level=source_priority(source_class);authority.value_sha256=canonical_sha(render(candidate));authority.save()
    if changed:event.save(update_fields=changed+['updated_at'])
    return bool(changed)
