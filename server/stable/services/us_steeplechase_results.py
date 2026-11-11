"""NSA正式结果、出马表与DRF逐匹字段的交叉核对。"""
from io import BytesIO
import re

import pdfplumber

from .us_flat_results import parse_chart, horse_key
from .us_basic_fields import nsa_overnight_catalogue

NSA_VENUES = {'CAM': {'Camden'}, 'FH': {'Far Hills'}, 'FX': {'Foxfield'}, 'MTP': {'Montpelier'},
    'GRM': {'International Gold Cup'}, 'CNL': {'Colonial Downs'}, 'SAR': {'Saratoga'}}


def merge_steeplechase(raw_chart, identity, official, card):
    track=identity['track']; day=identity['date']; number=identity['race_number']
    if (track not in NSA_VENUES or official['venue'] not in NSA_VENUES[track]
            or official['local_date'] != day or str(official['race_number']) != str(number)
            or card['venue'] != track or card['local_date'] != day or card['race_number'] != number
            or not card.get('roster_complete')):
        raise ValueError('us_nsa_bundle_identity')
    chart=parse_chart(raw_chart,identity)
    with pdfplumber.open(BytesIO(raw_chart)) as pdf:
        text='\n'.join(p.extract_text(x_tolerance=1.5) or '' for p in pdf.pages)
    pools=re.findall(r'Mutuel\s+Pool\s*:?\s*\$([\d,.]+)',text)
    if not pools:
        raise ValueError('us_nsa_betting_status_missing')
    no_pool=all(float(v.replace(',',''))==0 for v in pools)
    by_chart={horse_key(x['chart_name']):x for x in chart['runners']}
    by_official={horse_key(x['horse_name']):x for x in official['runners']}
    by_entry={horse_key(x['horse_name']):x for x in card['runners']}
    if (len(by_chart)!=len(chart['runners']) or len(by_official)!=len(official['runners'])
            or len(by_entry)!=len(card['runners']) or by_chart.keys()!=by_official.keys()
            or not by_official.keys()<=by_entry.keys()):
        raise ValueError('us_nsa_bundle_roster')
    scratch_names={horse_key(n):n for n in chart['scratches']}
    if by_entry.keys()-by_official.keys() != scratch_names.keys() & by_entry.keys():
        raise ValueError('us_nsa_bundle_scratch_roster')
    # 独立的NSA官方终局名单决定非完赛种类；chart的“>”不单独决定DNF。
    # 尤其Noel Laing的Scorpion's Revenge，chart无数字但NSA明确正式第5名。
    previous=None; margins={}
    for row in chart['runners']:
        k=horse_key(row['chart_name']); off=by_official[k]
        if row['placing'] is not None and row['placing']!=off['finish_position']:
            raise ValueError('us_nsa_bundle_placing_conflict')
        if off['status']=='finished':
            margins[k]=None if previous is None else previous['margin_to_next']
            if previous is not None and margins[k] is None:
                raise ValueError('us_nsa_bundle_margin_missing')
            previous=row
        else:
            margins[k]=None
    rows=[]
    first_physical=next((horse_key(x['chart_name']) for x in chart['runners']
                         if by_official[horse_key(x['chart_name'])]['status']=='finished'),None)
    for k,off in by_official.items():
        c=by_chart[k];e=by_entry[k]
        if no_pool and float(c['odds_net'])!=0:
            raise ValueError('us_nsa_betting_conflict')
        rows.append(dict(horse_name=off['horse_name'],program_number=e['entry_number'],
            post_position=c['post_position'],placing=off['finish_position'],status=off['status'],
            raw_status=off['raw_status'],finish_position=c['finish_position'],demoted=c['demoted'],
            weight_lbs=c['weight_lbs'],jockey_name=off['jockey_name'],trainer_name=off['trainer_name'],
            odds_net=None if no_pool else c['odds_net'],
            odds_availability='not_applicable_no_pool' if no_pool else 'reported',
            margin_to_previous=margins[k],margin_availability=('not_applicable_non_finisher'
                if off['status']!='finished' else 'first_physical_finisher' if k==first_physical else 'reported'),
            number_source='official_overnight_pp',chart_finish_unreported=c['finish_position'] is None))
    scratches=[dict(horse_name=n,program_number=by_entry[k]['entry_number'] if k in by_entry else None,
        number_availability='reported' if k in by_entry else 'not_present_in_official_overnight')
        for k,n in scratch_names.items()]
    gaps=['scratch_program_number_missing'] if any(x['program_number'] is None for x in scratches) else []
    return dict(local_date=day,venue=track,race_number=number,book_race_id=official['book_race_id'],race_name=official['race_name'],
        grade=official['grade'],catalogue=nsa_overnight_catalogue(card),runners=rows,scratches=scratches,runner_count=len(rows),
        declared_count=card['declared_count'],roster_complete=True,winning_time=chart['winning_time'],
        fractional_times=chart['fractional_times'],going=official.get('going',''),
        official_winning_margin=official['winning_margin_raw'],
        margin_semantics='behind_previous_physical_finisher',gaps=gaps,fields_complete=not gaps,
        correction_marker=chart.get('correction_marker',''))


def resolve_prior_card_scratches(result, prior_card):
    """两版官方名单证明退赛发生在重新编号之前；旧编号不冒充最终马号。"""
    if (result['venue']!=prior_card['venue'] or result['local_date']!=prior_card['local_date']
            or result['race_number']!=prior_card['race_number'] or not prior_card['roster_complete']
            or len(prior_card['runners'])!=prior_card['declared_count']):
        raise ValueError('us_nsa_prior_card_identity')
    prior={horse_key(x['horse_name']):x for x in prior_card['runners']}
    final={horse_key(x['horse_name']) for x in result['runners']+result['scratches']}
    if len(prior)!=prior_card['declared_count'] or set(prior)!=final:
        raise ValueError('us_nsa_prior_card_roster')
    # 只处理确实不在最后overnight中的马，不用较早编号覆盖任何最终马号。
    scratches=[]
    for row in result['scratches']:
        value=dict(row)
        if value['number_availability']=='not_present_in_official_overnight':
            value.update(number_availability='withdrawn_before_final_overnight',
                prior_entry_number=prior[horse_key(row['horse_name'])]['entry_number'],
                final_program_number_applicable=False)
        scratches.append(value)
    gaps=[g for g in result['gaps'] if g!='scratch_program_number_missing']
    return dict(result,scratches=scratches,gaps=gaps,fields_complete=not gaps,
                prior_declared_count=prior_card['declared_count'])
