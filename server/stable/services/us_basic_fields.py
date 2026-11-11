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
        for field,candidate in fields.items():
            old=getattr(event,field)
            authority=event.field_authorities.select_for_update().filter(subject_type='event',subject_key=str(event.pk),field_name=field).first()
            authorities[field]=authority
            decision=arbitrate_source_value(current_source_key=authority.source_key if authority else '',
                current_source_class=authority.source_class if authority else '',current_observed_at=authority.observed_at if authority else None,
                candidate_source_key=source.source_key,candidate_source_class=source_class,candidate_observed_at=observed,
                has_current_value=old not in (None,''),values_equal=old==candidate,
                manual_locked=bool((event.manual_lock_flags or {}).get('basic') or (event.manual_lock_flags or {}).get(field) or authority and authority.manual_lock))
            if not decision.apply and decision.reason_code!='idempotent_replay':deny=True
        if deny:continue
        for field,candidate in fields.items():
            old=getattr(event,field)
            if old==candidate:continue
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
    if (flags.allows(provider=source.source_key,region=source.region_code,field_name='us_basic.race_metadata')
        and not (event.manual_lock_flags or {}).get('basic') and refs.get('us_race_metadata')!=meta):
        refs['us_race_metadata']=meta;changed.add('source_refs')
    if changed:
        event.source_refs=refs
        event.save(update_fields=changed|{'updated_at'})
