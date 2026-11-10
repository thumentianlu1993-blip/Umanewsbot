"""法国来源公开字段合同；保留原始公斤和报价平台。"""
import re


def france_source(source):
    return (source.source_key, source.region_code) == ('geny', 'france')


def result_odds(provenance):
    value=str(provenance.get('win_odds') or '')
    return value if re.fullmatch(r'\d+(?:\.\d+)?',value) else ''


def public_refs(provenance):
    return dict(field_units={'carried_weight':'kg','odds_value':'decimal','margin':'length'},
        primary=provenance.get('source_url',''),margin_basis=provenance.get('margin_relation',''),
        odds_source=provenance.get('odds_source',''),odds_observed_at=provenance.get('odds_observed_at',''),
        allocated_weight=provenance.get('allocated_weight',''),adjusted_weight=provenance.get('adjusted_weight',''))


def fill_card_gaps_locked(*, event, runner, row, source, observation, now):
    """同场身份已由结果writer核验；旧卡只补空值/同值证据，绝不以实际负重填卡。"""
    from datetime import datetime
    from django.utils import timezone
    from stable import models
    from .france_sources import geny_key, name_key
    from .france_basic_fields import digest
    from .race_data_sync_pipeline import RaceDataSyncFlags, _audit_defaults
    from .race_data_sync_policy import arbitrate_source_value, source_priority
    card = row['field_provenance'].get('card_fields')
    if not isinstance(card,dict):
        return {}
    try:
        key=geny_key(card['source_url'])
        observed=datetime.fromisoformat(card['observed_at'])
        if (key[1]!=source.external_race_id or key[2]!=event.local_date.isoformat() or key[4]!='partants-pronostics'
            or card['number']!=row['number'] or name_key(card['horse_name'])!=name_key(row['horse_name'])
            or name_key(card['horse_name'])!=name_key(runner.horse_name)
            or timezone.is_naive(observed) or observed>now or not re.fullmatch('[a-f0-9]{64}',card['raw_sha256'])):
            raise ValueError('france_card_identity')
    except (KeyError,ValueError,TypeError):
        raise ValueError('france_card_contract') from None
    flags=RaceDataSyncFlags.from_settings()
    updated=[];decisions={}
    refs=dict(runner.source_refs or {})
    proofs=dict(refs.get('france_card_fields') or {})
    subject=row['external_runner_id']
    for field,contract in [('trainer_name','trainer_name'),('carried_weight','carried_weight'),('odds_value','odds')]:
        candidate=card.get(field,'')
        if not candidate or not flags.allows(provider='geny',region='france',field_name='participants.'+contract):
            continue
        if not isinstance(candidate,str) or len(candidate)>(255 if field=='trainer_name' else 64):
            raise ValueError('france_card_field')
        if field=='carried_weight' and not re.fullmatch(r'\d+(?:\.\d+)? kg',candidate):
            raise ValueError('france_card_weight')
        if field=='odds_value' and not re.fullmatch(r'\d+(?:\.\d+)?',candidate):
            raise ValueError('france_card_odds')
        old=getattr(runner,field)
        authority=event.field_authorities.select_for_update().filter(subject_type='participant',subject_key=subject,field_name=field).first()
        locked=bool((event.manual_lock_flags or {}).get('runners') or (runner.manual_lock_flags or {}).get(field)
            or event.field_authorities.filter(subject_type='participant',subject_key__in=(subject,runner.external_runner_id,'geny:'+subject),field_name=field,manual_lock=True).exists())
        if locked or (runner.pk is not None and old and old!=candidate):
            decisions[field]='manual_lock' if locked else 'nonempty_conflict'
            continue
        decision=arbitrate_source_value(current_source_key=authority.source_key if authority else '',
            current_source_class=authority.source_class if authority else '',current_observed_at=authority.observed_at if authority else None,
            candidate_source_key='geny',candidate_source_class='trusted_publisher',candidate_observed_at=observed,
            has_current_value=bool(old) and runner.pk is not None,values_equal=old==candidate,manual_locked=locked)
        if (authority and authority.observed_at and observed<authority.observed_at) or (not decision.apply and decision.reason_code!='idempotent_replay'):
            decisions[field]='authority_conflict';continue
        proof=dict(value=candidate,source_url=card['source_url'],raw_sha256=card['raw_sha256'],observed_at=card['observed_at'])
        if old==candidate and proofs.get(field)==proof:
            decisions[field]='replayed';continue
        models.RaceEventFieldChange.objects.create(event=event,subject_type='participant',subject_key=subject,field_name=field,
            old_value=old,new_value=candidate,applied=True,decision='applied',
            **{**_audit_defaults(observation=observation,task_id='france_card_fill',run_id=''),
               'source_url':card['source_url'],'raw_sha256':card['raw_sha256'],'operation_mode':'france_card_fill'})
        authority=authority or models.RaceEventFieldAuthority(event=event,subject_type='participant',subject_key=subject,field_name=field)
        authority.source_key='geny';authority.source_class='trusted_publisher';authority.source_url=card['source_url']
        authority.external_id=source.external_race_id;authority.observed_at=observed
        authority.authority_level=source_priority('trusted_publisher');authority.value_sha256=digest(candidate);authority.save()
        setattr(runner,field,candidate);updated.append(field);proofs[field]=proof
        if field=='carried_weight':
            refs['field_units']={**refs.get('field_units',{}),'carried_weight':'kg'}
            refs.update(allocated_weight=candidate,adjusted_weight=card.get('adjusted_weight',''))
        if field=='odds_value':
            refs['field_units']={**refs.get('field_units',{}),'odds_value':'decimal'}
            refs.update(odds_source='Genybet',odds_observed_at=card['observed_at'])
        decisions[field]='applied'
    if updated:
        refs['france_card_fields']=proofs;runner.source_refs=refs
        if runner.pk is not None:
            runner.save(update_fields=(*updated,'source_refs','updated_at'))
    return decisions
