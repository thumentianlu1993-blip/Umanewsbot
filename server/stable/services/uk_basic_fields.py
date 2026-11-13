"""英国基础资料投影，冠军奖金保留来源语义，不覆盖赛事总奖金。"""
from django.conf import settings
from stable import models


def metadata_sha(metadata):
    from .race_data_source_adapters import canonical_sha
    return canonical_sha({k:v for k,v in metadata.items() if k not in {'observed_at','source_sha256'}})


def apply_metadata_locked(*,event,metadata,route,now):
    from .race_data_source_adapters import canonical_sha,aware,require_sha
    from .race_data_sync_policy import arbitrate_source_value,source_priority
    if (event.country_region!='united_kingdom' or route.provider!='the_racing_api'
            or route.region!='united_kingdom' or metadata['local_date']!=str(event.local_date)):
        raise ValueError('uk_metadata_scope')
    if 'uk_basic.metadata' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS:return
    if not settings.RACE_DATA_SYNC_ENABLED:return
    observed=aware(metadata['observed_at']);require_sha(metadata['source_sha256'])
    if observed>now or not route.permits_url(metadata['source_url']):raise ValueError('uk_metadata_source')
    fields={k:metadata[k] for k in ('distance_text','going_text','eligibility_text') if metadata.get(k)}
    surface={'Turf':'turf','AW':'synthetic'}.get(metadata.get('surface'))
    kind={'Flat':'flat','Chase':'steeplechase','Hurdle':'hurdle','NH Flat':'other'}.get(metadata.get('race_type'))
    if surface:fields.update(normalized_surface=surface,surface=metadata['surface'])
    if kind:fields['normalized_race_type']=kind
    changed=[]
    for field,candidate in fields.items():
        authority=event.field_authorities.select_for_update().filter(subject_type='event',subject_key=str(event.pk),field_name=field).first()
        old=getattr(event,field)
        decision=arbitrate_source_value(current_source_key=authority.source_key if authority else '',
            current_source_class=authority.source_class if authority else '',current_observed_at=authority.observed_at if authority else None,
            candidate_source_key=route.provider,candidate_source_class=route.source_class,candidate_observed_at=observed,
            has_current_value=old not in ('',None),values_equal=old==candidate,
            manual_locked=bool((event.manual_lock_flags or {}).get('basic') or (event.manual_lock_flags or {}).get(field) or authority and authority.manual_lock))
        if not decision.apply and decision.reason_code!='idempotent_replay':continue
        if old!=candidate:
            models.RaceEventFieldChange.objects.create(event=event,subject_type='event',subject_key=str(event.pk),field_name=field,
                old_value=old,new_value=candidate,applied=True,decision='applied',source_key=route.provider,
                source_url=metadata['source_url'],source_class=route.source_class,authority_level=source_priority(route.source_class),
                raw_sha256=metadata['source_sha256'],operation_mode='uk_basic')
            setattr(event,field,candidate);changed.append(field)
        authority=authority or models.RaceEventFieldAuthority(event=event,subject_type='event',subject_key=str(event.pk),field_name=field)
        authority.source_key=route.provider;authority.source_class=route.source_class;authority.source_url=metadata['source_url']
        authority.external_id=metadata['external_race_id'];authority.observed_at=observed
        authority.authority_level=source_priority(route.source_class);authority.value_sha256=canonical_sha(candidate);authority.save()
    refs=dict(event.source_refs or {})
    old_meta=refs.get('uk_race_metadata',{})
    if (not (event.manual_lock_flags or {}).get('basic') and old_meta!=metadata
            and (not old_meta.get('observed_at') or observed>=aware(old_meta['observed_at']))):
        refs['uk_race_metadata']=metadata;event.source_refs=refs;changed.append('source_refs')
    if changed:event.save(update_fields=changed+['updated_at'])
