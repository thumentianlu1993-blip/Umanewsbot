"""英国 TRA 付费卡表/赛果解析；纯数据函数，不发请求、不写数据库。"""
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from zoneinfo import ZoneInfo

PARSER_VERSION = 'uk-tra-paid-v1'
NON_FINISHERS = {
    'PU': 'pulled_up', 'F': 'fell', 'UR': 'unseated_rider', 'REF': 'refused',
    'RR': 'refused', 'BD': 'did_not_finish', 'RO': 'did_not_finish',
    'SU': 'did_not_finish', 'DNF': 'did_not_finish', 'DSQ': 'disqualified',
    'DQ': 'disqualified', 'NR': 'non_runner',
}


def name_key(value):
    value=re.sub(r'\s*\([A-Z]{2,3}\)\s*$','',str(value))
    return re.sub(r'[^\w]','',unicodedata.normalize('NFKC',value).casefold())


def text(row,key,*,required=False):
    value=row.get(key,'')
    if value is None:value=''
    if not isinstance(value,str) or len(value)>2048 or (required and not value.strip()):
        raise ValueError('uk_field:'+key)
    return value.strip()


def decimal_text(value):
    try:
        number=Decimal(value)
        if not number.is_finite() or number<0:raise ValueError('uk_numeric')
    except (InvalidOperation,TypeError):raise ValueError('uk_numeric') from None
    return format(number,'f')


def _identity(raw):
    if not isinstance(raw,dict):raise ValueError('uk_race_schema')
    external=text(raw,'race_id',required=True)
    if not re.fullmatch(r'rac_\d+',external) or raw.get('region')!='GB':raise ValueError('uk_race_identity')
    day=date.fromisoformat(text(raw,'date',required=True))
    off=datetime.fromisoformat(text(raw,'off_dt',required=True).replace('Z','+00:00'))
    if off.tzinfo is None or off.astimezone(ZoneInfo('Europe/London')).date()!=day:
        raise ValueError('uk_off_time')
    return dict(external_race_id=external,local_date=day.isoformat(),
        course=text(raw,'course',required=True),off_time=off.isoformat(),
        race_name=text(raw,'race_name',required=True),region='GB')


def _runners(raw):
    rows=raw.get('runners')
    if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError('uk_runner_count')
    ids=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('uk_runner_schema')
        key=text(row,'horse_id',required=True)
        if not re.fullmatch(r'hrs_\d+',key) or key in ids:raise ValueError('uk_runner_identity')
        ids.add(key)
        text(row,'horse',required=True)
    return rows


def card_quote(raw):
    """保留单家来源报价；优先 Bet365，否则按名称选首个有效报价，不计算综合赔率。"""
    quotes=[]
    for quote in raw.get('odds',[]) if isinstance(raw.get('odds',[]),list) else []:
        if not isinstance(quote,dict):continue
        bookmaker=str(quote.get('bookmaker') or '').strip()
        try:value=decimal_text(quote.get('decimal',''))
        except ValueError:continue
        if not bookmaker or len(bookmaker)>128 or Decimal(value)<=1:continue
        quotes.append((bookmaker,value,str(quote.get('updated') or '')))
    if not quotes:return '',{}
    bookmaker,value,updated=min(quotes,key=lambda q:(q[0].casefold()!='bet365',q[0].casefold()))
    return value,dict(odds_source='TRA / '+bookmaker,odds_format='decimal',bookmaker_updated_raw=updated)


def _runner(raw,*,result=False):
    number=text(raw,'number',required=True)
    nonrunner=number.upper()=='NR'
    if not nonrunner and (not number.isdigit() or int(number)<=0):raise ValueError('uk_program_number')
    weight=text(raw,'weight_lbs' if result else 'lbs')
    draw=text(raw,'draw')
    if draw and not draw.isdigit():raise ValueError('uk_draw')
    price,quote=card_quote(raw) if not result and not nonrunner else ('',{})
    return dict(odds_value=price,external_runner_id=raw['horse_id'],horse_name=text(raw,'horse',required=True),
        number='' if nonrunner else number,barrier='' if draw=='0' else draw,
        jockey_name=text(raw,'jockey'),trainer_name=text(raw,'trainer'),
        carried_weight=decimal_text(weight)+' lb' if weight else '',
        status='non_runner' if nonrunner else 'declared',status_reported=True,
        raw_status='NR' if nonrunner else '',reported_finish_position=None,finish_time='',margin='',
        field_provenance=dict(quote,weight_unit='lb',source_fields={'horse_id':raw['horse_id'],'number':number}))


def parse_card(raw):
    race=_identity(raw)
    if raw.get('is_abandoned') is not False:raise ValueError('uk_abandoned_or_unknown')
    if raw.get('race_status') not in {'declared','result'}:raise ValueError('uk_card_stage')
    rows=[_runner(row) for row in _runners(raw)]
    active=[r for r in rows if r['status']!='non_runner']
    size=text(raw,'field_size',required=True)
    if not size.isdigit() or int(size)!=len(active):raise ValueError('uk_field_size')
    if len({r['number'] for r in active})!=len(active):raise ValueError('uk_duplicate_number')
    prize=text(raw,'prize').replace('£','').replace(',','').strip()
    metadata=dict(distance_text=text(raw,'distance'),distance_furlongs=text(raw,'distance_f'),
        race_type=text(raw,'type'),grade_text=text(raw,'pattern'),going_text=text(raw,'going'),
        surface=text(raw,'surface'),eligibility_text=' '.join(filter(None,[text(raw,'age_band'),text(raw,'sex_restriction')])),
        winner_prize_amount=decimal_text(prize) if prize else '',prize_currency=text(raw,'prize_currency'),
        winner_prize_stage='result' if raw['race_status']=='result' else 'announced')
    return dict(**race,roster=rows,roster_complete=True,result_phase='',
        card_stage=raw['race_status'],metadata=metadata,
        gaps=['non_runner_number_missing:'+r['external_runner_id'] for r in rows if not r['number']])


def parse_result(raw,*,card):
    race=_identity(raw);card_value=parse_card(card)
    if card_value['card_stage']!='result':raise ValueError('uk_result_not_confirmed')
    for key in ('external_race_id','local_date','course'):
        if race[key]!=card_value[key]:raise ValueError('uk_card_result_identity')
    card_rows={r['horse_id']:r for r in card['runners']}
    runners=_runners(raw)
    actual_ids={r['horse_id'] for r in runners}
    expected_ids={r['horse_id'] for r in card['runners'] if r['number'].upper()!='NR'}
    if actual_ids!=expected_ids:raise ValueError('uk_card_result_roster')
    nr_rows=[r for r in card_value['roster'] if r['status']=='non_runner']
    nr_text=text(raw,'non_runners')
    listed=[name_key(n.strip()) for n in nr_text.split(',') if n.strip()]
    if Counter(listed)!=Counter(name_key(r['horse_name']) for r in nr_rows):
        raise ValueError('uk_nonrunner_names')
    rows=[]
    for runner in runners:
        prior=card_rows[runner['horse_id']]
        if name_key(prior['horse'])!=name_key(runner['horse']) or prior['number']!=runner['number']:
            raise ValueError('uk_horse_identity')
        row=_runner(runner,result=True)
        position=text(runner,'position',required=True).upper()
        if position.isdigit() and 1<=int(position)<=100:
            row.update(reported_finish_position=int(position),status='finished')
        elif position in NON_FINISHERS:
            row['status']=NON_FINISHERS[position]
        else:raise ValueError('uk_finish_status')
        odds=text(runner,'sp_dec')
        row.update(raw_status=position,finish_time=text(runner,'time'),margin=text(runner,'btn'))
        row['field_provenance'].update(win_odds=decimal_text(odds) if odds else '',odds_source='TRA SP',
            odds_format='decimal',odds_fractional=text(runner,'sp'),margin_basis='behind_previous',
            margin_unit='length',margin_behind_winner=text(runner,'ovr_btn'),time_source='TRA',
            card_fields=dict(jockey_name=text(prior,'jockey'),trainer_name=text(prior,'trainer'),
                carried_weight=decimal_text(prior['lbs'])+' lb' if prior.get('lbs') else ''))
        rows.append(row)
    counts=Counter(r['reported_finish_position'] for r in rows if r['reported_finish_position'] is not None)
    if not counts:raise ValueError('uk_no_finisher')
    seen=0
    for position,count in sorted(counts.items()):
        if position!=seen+1:raise ValueError('uk_finish_order')
        seen+=count
    for row in rows:
        if counts.get(row['reported_finish_position'],0)>1:row['status']='dead_heat'
    return dict(**race,roster=rows+nr_rows,roster_complete=True,result_phase='official',
        metadata={**card_value['metadata'],'winning_time_detail':text(raw,'winning_time_detail')},
        gaps=card_value['gaps'])


def parse_preview(raw):
    """早期报名/负磅公布只形成候选，不进入正式卡表 writer。"""
    stage=raw.get('race_status')
    if stage in {'declared','result'}:
        return dict(parse_card(raw),stage='declared_card')
    race=_identity(raw)
    if raw.get('is_abandoned') is not False or stage not in {'entry','weighed'}:
        raise ValueError('uk_preview_stage')
    rows=[]
    for raw_row in _runners(raw):
        row=dict(raw_row)
        # entry 序号不代表最终马号，即使来源临时给出编号也不发布为马号。
        row['number']='NR'
        parsed=_runner(row)
        parsed.update(status='nominated',raw_status='',status_reported=False)
        parsed['odds_value'],quote=card_quote(raw_row)
        parsed['field_provenance'].update(quote)
        parsed['field_provenance']['source_fields']['number']=text(raw_row,'number')
        rows.append(parsed)
    size=text(raw,'field_size',required=True)
    if not size.isdigit() or int(size)!=len(rows):raise ValueError('uk_entry_count')
    return dict(**race,roster=rows,roster_complete=False,result_phase='',gaps=[],
        stage='nominations' if stage=='entry' else 'weights_published')


def supplement_numbers(race,sl,*,source):
    """全场核对的 Sporting Life 补证只填缺失马号，不覆盖 TRA 结果。"""
    from copy import deepcopy
    from urllib.parse import urlsplit
    url=urlsplit(source['url'])
    if (url.scheme!='https' or url.hostname!='www.sportinglife.com' or url.username or url.password
            or url.port not in (None,443) or url.query or url.fragment
            or not re.fullmatch(r'/racing/results/'+re.escape(race['local_date'])+r'/[a-z0-9-]+/\d+/[a-z0-9-]+',url.path)
            or not re.fullmatch('[a-f0-9]{64}',source['sha256'])):
        raise ValueError('uk_supplement_source')
    summary=sl['race_summary']
    if (summary['date']!=race['local_date'] or summary['course_name']!=race['course'].removesuffix(' (AW)')
            or summary['time']!=datetime.fromisoformat(race['off_time']).astimezone(timezone.utc).strftime('%H:%M')
            or summary['race_stage']!='WEIGHEDIN'):
        raise ValueError('uk_supplement_identity')
    rides=sl['rides'];names=[name_key(r['horse']['name']) for r in rides]
    wanted=[name_key(r['horse_name']) for r in race['roster']]
    numbers=[r['cloth_number'] for r in rides]
    if (len(names)!=len(set(names)) or len(wanted)!=len(set(wanted)) or set(names)!=set(wanted)
            or any(type(n) is not int or n<=0 for n in numbers) or len(numbers)!=len(set(numbers))):
        raise ValueError('uk_supplement_roster')
    by_name=dict(zip(names,rides));merged=deepcopy(race)
    for row in merged['roster']:
        other=by_name[name_key(row['horse_name'])]
        nonrunner=other['ride_status'] in {'NONRUNNER','WITHDRAWN'}
        if (nonrunner!=(row['status']=='non_runner') or other['ride_status'] not in {'RUNNER','NONRUNNER','WITHDRAWN'}
                or (row['number'] and row['number']!=str(other['cloth_number']))
                or (row['reported_finish_position'] is not None and row['reported_finish_position']!=other.get('finish_position'))):
            raise ValueError('uk_supplement_conflict')
        if not row['number']:
            row['number']=str(other['cloth_number'])
            row['field_provenance']['number_source']=dict(source)
    active=sum(r['status']!='non_runner' for r in race['roster'])
    if type(summary['ride_count']) is not int or summary['ride_count']!=active:
        raise ValueError('uk_supplement_count')
    merged['gaps']=[gap for gap in merged['gaps'] if not gap.startswith('non_runner_number_missing:')]
    return merged
