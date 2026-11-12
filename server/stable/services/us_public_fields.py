"""美国已核验资料的公开字段语义；不推算赔率、人气或每匹用时。"""
from collections import Counter
import hashlib
import re

UNITS = {'carried_weight': 'lb', 'odds_value': 'us_net', 'margin': 'length'}


def us_source(source):
    return (source.source_key, source.region_code) == ('us_racing', 'united_states')


def result_odds(provenance):
    value = str(provenance.get('win_odds') or '')
    return value if re.fullmatch(r'\d+(?:\.\d+)?', value) else ''


def public_refs(provenance):
    return dict(field_units=dict(UNITS), primary=provenance.get('source_url', ''),
        margin_basis='previous_physical', odds_source=provenance.get('odds_source', ''),
        odds_observed_at=provenance.get('odds_observed_at', ''))


def result_participants(result):
    if result.get('gaps') or len(result['runners']) != result['runner_count']:
        raise ValueError('us_result_incomplete')
    counts = Counter(r['placing'] for r in result['runners'] if r['placing'] is not None)
    rows = []
    previous = None
    for r in result['runners']:
        if r.get('program_number') is None:
            raise ValueError('us_result_program_missing')
        margin = r.get('margin_to_previous') if 'margin_to_previous' in r else (
            previous.get('margin_to_next') if previous is not None and r['finish_position'] is not None else None)
        if r['finish_position'] is not None:
            previous = r
        status = 'dead_heat' if r['placing'] is not None and counts[r['placing']] > 1 else r['status']
        rows.append(dict(external_runner_id='number:'+str(r['program_number']),number=str(r['program_number']),
            horse_name=r['horse_name'],reported_finish_position=r['placing'],status=status,
            raw_status=r.get('raw_status',r['status']),finish_time='',margin='' if margin is None else str(margin),
            barrier=str(r['post_position']),jockey_name=r.get('jockey_name',r.get('jockey','')),
            trainer_name=r.get('trainer_name',r.get('trainer','')),carried_weight=str(r['weight_lbs'])+' lb',
            field_provenance=dict(field_units=dict(UNITS),win_odds=r.get('odds_net'),
                margin_relation='previous_physical',physical_finish_position=r['finish_position'],
                demoted=r.get('demoted',False),odds_availability=r.get('odds_availability','reported'))))
    for r in result['scratches']:
        number = str(r['program_number']) if r.get('program_number') is not None else ''
        if not number and r.get('number_availability') != 'withdrawn_before_final_overnight':
            raise ValueError('us_result_program_missing')
        external = 'number:'+number if number else 'withdrawn:'+hashlib.sha256(r['horse_name'].encode()).hexdigest()[:24]
        rows.append(dict(external_runner_id=external,number=number,horse_name=r['horse_name'],
            reported_finish_position=None,status='scratched',raw_status='scratched',finish_time='',margin='',
            barrier='',jockey_name='',trainer_name='',carried_weight='',
            field_provenance=dict(field_units=dict(UNITS),number_availability=r.get('number_availability','reported'))))
    if len({r['external_runner_id'] for r in rows}) != len(rows):
        raise ValueError('us_result_duplicate_runner')
    return rows


def blocking_multisource_manual_locks(event):
    """美国多源writer从不改场地；场地人工锁保留，不扩大为逐匹赛果锁。"""
    retained={'surface'} if event.country_region=='united_states' else set()
    return any(value for field,value in (event.manual_lock_flags or {}).items() if field not in retained)
