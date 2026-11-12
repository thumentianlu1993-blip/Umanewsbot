"""美国赛前 PDF 解析，原件字段与发布阶段分别保留。"""
from datetime import datetime
from io import BytesIO
import hashlib
import re
from zoneinfo import ZoneInfo

import pdfplumber
from pdfplumber.utils import extract_text

# 这些是已经核对过的官方 overnight 版式；坐标仅用于版式识别后的列切分。
OVERNIGHT_VENUES = {'CAM': ('CAMDEN','COLONIALCUP','CAROLINACUP','SPRINGDALERACECOURSE'), 'FH': 'FARHILLS', 'FX': 'FOXFIELD', 'GRM': 'GREATMEADOW',
    'MTP': 'MONTPELIER', 'CNL': 'COLONIALDOWNS', 'CD': 'CHURCHILLDOWNS', 'SAR': 'SARATOGA', 'DMR': 'WWW.DMTC.COM'}


def final_result_roster(result, target):
    """已赛验收使用完整赛果中的最终名单，不伪造历史报名或赛前快照。"""
    from .us_flat_results import horse_key
    identity=result['identity']
    runners=result['runners'];scratches=result['scratches'];all_rows=runners+scratches
    field_raw = target.get('field_size_raw')
    if field_raw == '':
        proof = result.get('runner_count_evidence') or {}
        expected_count = proof.get('count')
        digest = proof.get('source_sha256')
        if (proof.get('basis') != 'sporting_life_declared' or type(expected_count) is not int or expected_count <= 0
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or digest != result.get('sources', {}).get('supplement')):
            raise ValueError('us_final_roster_count_evidence')
    else:
        if not isinstance(field_raw, str) or not re.fullmatch(r'[1-9][0-9]*', field_raw):
            raise ValueError('us_final_roster_count_evidence')
        expected_count = int(field_raw)

    if (result['candidate_key']!=target['candidate_key'] or identity['track']!=target['venue']
            or identity['date']!=target['local_date']
            or (target.get('source_race_id') and str(identity['race_number'])!=str(target['source_race_id']))
            or result['gaps'] or not runners or result['runner_count']!=len(runners)
            or len(runners)!=expected_count
            or len({horse_key(r['horse_name']) for r in all_rows})!=len(all_rows)
            or any(not r.get('program_number') for r in all_rows)
            or len({str(r['program_number']) for r in all_rows})!=len(all_rows)):
        raise ValueError('us_final_roster_identity_or_completeness')
    return dict(local_date=identity['date'],venue=identity['track'],race_number=identity['race_number'],
        source_stage='final_result_roster',pre_race_snapshot=False,roster_complete=True,
        active_count=len(runners),declared_count=len(all_rows),runners=runners,scratches=scratches,
        result_sources=result['sources'],gaps=[])


def parse_usracing_prerace(raw, target):
    """公开预想名单与待定表；TBA不转成正式马号、骑手或最终出马证明。"""
    from bs4 import BeautifulSoup
    from .us_flat_results import VENUES,horse_key,key
    def _prerace_name(value):
        value=re.sub(r'^The\s+','',value,flags=re.I)
        return key(re.sub(r'\b(?:Stakes|S\.)\s*','',value,flags=re.I))
    soup=BeautifulSoup(raw,'lxml');text=lambda n:' '.join(n.get_text(' ',strip=True).split())
    heading=soup.find('h1');tables=soup.select('table')
    if heading is None or _prerace_name(text(heading))!=_prerace_name(target['race_name']) or not tables:
        raise ValueError('us_usracing_title')
    info={}
    for tr in tables[0].select('tr'):
        cells=tr.select('td,th')
        if len(cells)==2:info[text(cells[0])]=text(cells[1])
    venue=VENUES[target['venue']][0]
    if (datetime.strptime(info.get('Date',''),'%A, %B %d, %Y').date().isoformat()!=target['local_date']
            or info.get('Track') not in {venue,venue+' Racetrack'}
            or {'Grade I':'G1','Grade II':'G2','Grade III':'G3'}.get(info.get('Grade'))!=target['grade']):
        raise ValueError('us_usracing_identity')
    matched=[]
    for table in tables:
        trs=table.select('tr')
        if trs and [text(c) for c in trs[0].select('td,th')]==['#','Horse','Jockey','Trainer','Odds']:
            matched.append(trs[1:])
    if len(matched)!=1 or not matched[0]:raise ValueError('us_usracing_field_table')
    rows=[[text(c) for c in tr.select('td')] for tr in matched[0]]
    if any(len(r)!=5 for r in rows):raise ValueError('us_usracing_field_columns')
    pending=rows==[['TBA','Official entries pending','TBA','TBA','TBA']]
    items=[]
    if not pending:
        for number,horse,jockey,trainer,odds in rows:
            if not horse or not trainer or horse=='TBA' or trainer=='TBA':
                raise ValueError('us_usracing_field_missing')
            if number!='TBA' or jockey!='TBA' or odds!='TBA':
                # 正式抽签后的版式尚未有实况样本，不能套用预想名单合同。
                raise ValueError('us_usracing_drawn_card_requires_full_source')
            items.append(dict(horse_name=horse,trainer_name=trainer,horse_number='',jockey_name='',
                carried_weight='',barrier='',odds_raw='',running_status='prospective'))
        if len({horse_key(x['horse_name']) for x in items})!=len(items):
            raise ValueError('us_usracing_duplicate_horse')
    return dict(local_date=target['local_date'],venue=target['venue'],race_name=text(heading),
        source_stage='not_published' if pending else 'preliminary_field',items=items,
        published_count=len(items),published_table_complete=True,final_roster_complete=False,
        nomination_status='not_asserted_by_source',race_information=info)


def _cell(chars, left, right, *, horse=False):
    selected = [c for c in chars if left-.3 <= c['x0'] < right-.3]
    if horse and selected:
        # 名后的低字号速度评分是独立脚注，不能成为马名的一部分。
        size = max(c['size'] for c in selected)
        selected = [c for c in selected if c['size'] >= size-.2]
    return ' '.join((extract_text(selected, x_tolerance=1.5) or '').split())


def parse_overnight(raw, *, local_date, venue, race_number, source_url=''):
    if venue not in OVERNIGHT_VENUES or not isinstance(race_number, int) or race_number < 1:
        raise ValueError('us_overnight_identity')
    day = datetime.strptime(local_date, '%Y-%m-%d').date()
    try:
        with pdfplumber.open(BytesIO(raw)) as pdf:
            lines = []
            for page in pdf.pages:
                lines.extend(page.extract_text_lines(x_tolerance=1.5))
    except Exception as exc:
        raise ValueError('us_overnight_pdf') from exc
    if not lines:
        raise ValueError('us_overnight_empty')
    compact = re.sub(r'\s+', '', '\n'.join(l['text'] for l in lines)).upper()
    stamp = day.strftime('%B').upper()+str(day.day)+','+str(day.year)
    if stamp not in compact[:500]:
        raise ValueError('us_overnight_date')
    venue_headers=OVERNIGHT_VENUES[venue]
    if isinstance(venue_headers,str):venue_headers=(venue_headers,)
    if not any(header in compact[:500] for header in venue_headers):
        # NYRA overnight页首没有场地字样，必须有NSA当日目录给出的Saratoga文件身份。
        if not (venue == 'SAR' and re.fullmatch(
                r'https://nationalsteeplechase\.com/wp-content/uploads/\d{4}/\d{2}/Saratoga-[A-Za-z]+-\d+\.pdf', source_url)
                and 'PPHORSESEX/AGEWGTJOCKEYOWNERTRAINER' in compact[:500]):
            raise ValueError('us_overnight_venue')
    pattern = r'^(\d+)(?:st|nd|rd|th)\s*Race\.\s*\(C[X]?\d+\)'
    starts = [(i, int(m[1])) for i, l in enumerate(lines) if (m := re.match(pattern, l['text'], re.I))]
    matches = [(i,n) for i,n in starts if n == race_number]
    if len(matches) != 1:
        raise ValueError('us_overnight_race')
    start = matches[0][0]; stop = next((i for i,n in starts if i>start), len(lines))
    body = lines[start:stop]
    header = next((l for l in lines[:start] if l['text'].startswith('PP Horse')), None)
    if venue == 'DMR':
        bounds = [32.2,145.6,241,258.9,321.3,471.5,612]
        number_left = 17
    elif venue in {'CNL','CD'}:
        bounds = [32.2,128.6,241 if venue=='CD' else 246.5,
                  258.9 if venue=='CD' else 264.6,338.3 if venue=='CD' else 327,531.1,612]
        number_left = 17
    elif header:
        chars = sorted(header['chars'], key=lambda c:c['x0'])
        heading = ''.join(c['text'] for c in chars)
        def pos(word):
            return chars[heading.index(word)]['x0']
        bounds = [pos('Horse'),pos('Sex/Age') if venue=='SAR' else pos('Med'),
                  pos('Wgt'),pos('Jockey'),pos('Owner'),pos('Trainer'),
                  pos('Equip') if 'Equip' in heading else 612]
        number_left = pos('PP')-.3
        # NYRA的数字负重右对齐，列标题在数值右侧。
        if venue == 'SAR':
            bounds[2] = 220
        else:
            bounds[5] -= 6
    else:
        raise ValueError('us_overnight_columns')
    rows = []; count = None; conditions = []; started = False; also_eligible = False
    for line in body:
        s = line['text']
        if s.startswith('--Also Eligibles--'):
            also_eligible = True
        num = _cell(line['chars'], number_left, bounds[0])
        weight = _cell(line['chars'],bounds[2],bounds[3])
        if re.fullmatch(r'\d+', num) and re.fullmatch(r'\*?\d{3}', weight):
            horse = _cell(line['chars'],bounds[0],bounds[1],horse=True)
            # NYRA把(O)附于速度评分右侧；不是马名或国家后缀。
            horse = re.sub(r'\s*\(O\)$','',horse)
            annotation = '(S)' if venue=='DMR' and horse.endswith('(S)') else ''
            if annotation:
                horse=horse[:-3].rstrip()
            trainer = _cell(line['chars'],bounds[5],bounds[6])
            jockey = _cell(line['chars'],bounds[3],bounds[4])
            if not horse or not trainer:
                raise ValueError('us_overnight_runner')
            rows.append(dict(entry_number=int(num), horse_name=horse, carried_weight=weight.lstrip('*')+' lb',
                jockey_name=jockey, trainer_name=trainer, also_eligible=also_eligible,
                number_kind='overnight_pp', barrier=None, entry_annotation=annotation))
            started=True
        elif started and re.fullmatch(r'\d+(?:-\d+AE)?',s):
            parts=re.fullmatch(r'(\d+)(?:-(\d+)AE)?',s)
            count=int(parts[1])+int(parts[2] or 0)
            break
        elif not started:
            conditions.append(s)
    if (not rows or count is None or count != len(rows)
            or len({r['entry_number'] for r in rows}) != count
            or len({r['horse_name'] for r in rows}) != count):
        raise ValueError('us_overnight_count')
    conditions=' '.join(conditions)
    clock=re.search(r'Post\s*(?:Time\s*:\s*)?(\d{1,2}:\d{2}\s*[AP]M)',conditions,re.I)
    if not clock and race_number == 1:
        clock=re.search(r'POST TIME:\s*(\d{1,2}:\d{2}\s*[AP]M)',' '.join(l['text'] for l in lines[:start]))
    off=datetime.combine(day,datetime.strptime(clock[1].replace(' ',''),'%I:%M%p').time(),ZoneInfo('America/Los_Angeles' if venue=='DMR' else 'America/New_York')) if clock else None
    return dict(local_date=local_date,venue=venue,race_number=race_number,source_stage='declared_overnight',
        declared_count=count,roster_complete=True,runners=rows,conditions_raw=conditions,
        source_url=source_url,raw_sha256=hashlib.sha256(raw).hexdigest(),
        off_time=off.isoformat() if off else None)


def parse_stakes_nominations(raw, *, local_date, race_name):
    """赛场直供报名PDF；按实际文字间距分开右对齐练马师，不按名字猜切分。"""
    day=datetime.strptime(local_date,'%Y-%m-%d').date()
    try:
        with pdfplumber.open(BytesIO(raw)) as pdf:
            lines=[l for p in pdf.pages for l in p.extract_text_lines(x_tolerance=.3)]
    except Exception as exc:
        raise ValueError('us_nomination_pdf') from exc
    text='\n'.join(l['text'] for l in lines)
    titles=[l['text'] for l in lines[:3] if not re.fullmatch(r'\d+(?:st|nd|rd|th) Running Of',l['text'])]
    normalize=lambda x: re.sub(r'\s+',' ',x).strip().casefold()
    if not titles or normalize(titles[0])!=normalize(race_name):
        raise ValueError('us_nomination_identity')
    stamp=re.search(r'TO BE RUN ([A-Z]+, [A-Z]+ \d{1,2}, \d{4})',text)
    count=re.search(r'CLOSED [^\n]*WITH (\d+) NOMINATIONS',text)
    if not stamp or datetime.strptime(stamp[1].title(),'%A, %B %d, %Y').date()!=day or not count:
        raise ValueError('us_nomination_identity_or_count')
    rows=[]
    pattern=r'(.+?)\s+((?:b|ch|gr/ro|gr|dk b/)[./]*[bcfghmr]\.(\d+))\s+(.+)'
    for l in lines:
        m=re.fullmatch(pattern,l['text'])
        if not m:
            continue
        chars=sorted(l['chars'],key=lambda c:c['x0'])
        # 已核对报表的普通词间距是字号的0.228倍；列间距独立计算。
        # 长owner会缩小整行字号，不能使用固定5pt阈值。
        gaps=[i for i in range(1,len(chars)) if chars[i]['x0']>400 and chars[i]['x0']-chars[i-1]['x1']>chars[i]['size']*.26]
        if not gaps:
            raise ValueError('us_nomination_trainer_boundary')
        split=gaps[-1]
        trainer=' '.join((extract_text(chars[split:],x_tolerance=.3) or '').split())
        left=' '.join((extract_text(chars[:split],x_tolerance=.3) or '').split())
        match=re.fullmatch(pattern,left)
        if not match or not trainer:
            raise ValueError('us_nomination_row')
        rows.append(dict(horse_name=match[1],horse_number='',barrier='',jockey_name='',
            trainer_name=trainer,owner_name=match[4],carried_weight='',age=int(match[3]),
            description_raw=match[2],owner_trainer_raw=m[4],running_status='nominated'))
    if len(rows)!=int(count[1]) or len({r['horse_name'] for r in rows})!=len(rows):
        raise ValueError('us_nomination_count')
    return dict(local_date=local_date,race_name=race_name,source_stage='nominations',
        items=rows,declared_count=len(rows),roster_complete=True)


def confirm_del_mar_roster(card, overnight):
    from .us_flat_results import horse_key
    if (card['venue_key'] != 'DMR' or overnight['venue'] != 'DMR'
            or card['local_date'] != overnight['local_date']
            or str(card['race_number']) != str(overnight['race_number'])
            or not overnight['roster_complete']
            or overnight['declared_count'] != len(overnight['runners'])):
        raise ValueError('us_delmar_roster_identity')
    a={(int(r['horse_number']),horse_key(r['horse_name'])) for r in card['items']}
    b={(r['entry_number'],horse_key(r['horse_name'])) for r in overnight['runners']}
    if a!=b or len(a)!=len(card['items']) or len(b)!=overnight['declared_count']:
        raise ValueError('us_delmar_independent_roster')
    return dict(card,roster_complete=True,declared_count=overnight['declared_count'],
        roster_count_source='official_overnight_footer',
        gaps=[g for g in card['gaps'] if g!='independent_roster_count'])


def parse_sporting_card(raw, identity):
    """同时接收当前出马和历史出马原件；历史页面不提供赛前时点证明。"""
    from .us_flat_results import VENUES, next_data, horse_key
    data=next_data(raw)['race'];summary=data['race_summary']
    zone=ZoneInfo(VENUES[identity['track']][2])
    off=datetime.fromisoformat(summary['date']+'T'+summary['time']).replace(tzinfo=ZoneInfo('Europe/London')).astimezone(zone)
    stage=summary['race_stage']
    if (off.date().isoformat()!=identity['date'] or summary['course_name']!=VENUES[identity['track']][0]
            or not re.match(r'Race '+str(identity['race_number'])+r'\b',summary['name'])
            or stage not in {'DORMANT','DECLARED','RACECARD','WEIGHEDIN'}):
        raise ValueError('us_sl_card_identity_or_stage')
    historical=stage=='WEIGHEDIN';runners=[];gaps=[]
    for ride in data['rides']:
        status=ride['ride_status']
        if status not in {'RUNNER','NONRUNNER','WITHDRAWN'}:
            raise ValueError('us_sl_card_status')
        number=ride['cloth_number'];draw=ride.get('draw_number')
        if not isinstance(number,int) or number<1:
            raise ValueError('us_sl_card_number')
        weight=re.fullmatch(r'(\d+)-(\d+)',ride.get('handicap',''))
        if not weight or int(weight[2])>=14:
            raise ValueError('us_sl_card_weight')
        row=dict(program_number=number,post_position=draw if draw and draw>0 else None,
            horse_name=ride['horse']['name'],age=ride['horse'].get('age'),
            jockey_name=ride.get('jockey',{}).get('name',''),trainer_name=ride.get('trainer',{}).get('name',''),
            owner_name=ride.get('owner',{}).get('name',''),carried_weight=str(int(weight[1])*14+int(weight[2]))+' lb',
            running_status='declared' if status=='RUNNER' else 'scratched',
            odds_raw=ride.get('betting',{}).get('current_odds',''),odds_stage='historical' if historical else 'pre_race')
        for field in ('horse_name','age','jockey_name','trainer_name','post_position'):
            if not row[field] and status=='RUNNER':gaps.append(str(number)+':'+field)
        runners.append(row)
    active=sum(r['running_status']=='declared' for r in runners)
    # 历史ride_count为实际出走数；赛前在退赛发生后也只计有效参赛者。
    if (not runners or active!=summary['ride_count']
            or len({r['program_number'] for r in runners})!=len(runners)
            or len({horse_key(r['horse_name']) for r in runners})!=len(runners)):
        raise ValueError('us_sl_card_count')
    return dict(local_date=identity['date'],venue=identity['track'],race_number=identity['race_number'],
        race_name=summary['name'],off_time=off.isoformat(),source_stage='historical_card' if historical else 'declared_card',
        provider_stage=stage,declared_count=len(runners),active_count=active,roster_complete=True,
        distance_raw=summary.get('distance',''),surface=summary.get('course_surface',{}).get('surface',''),
        runners=runners,gaps=sorted(set(gaps)),fields_complete=not gaps)


def parse_nyra_card(raw, identity):
    """NYRA逐场页面：页内选中日期/场次与Owners编号表独立核对。"""
    from bs4 import BeautifulSoup
    from urllib.parse import urlsplit, parse_qs
    soup=BeautifulSoup(raw,'lxml');text=lambda n:' '.join(n.get_text(' ',strip=True).split())
    venues={'BEL':'Belmont Park','SAR':'Saratoga'}
    if identity['track'] not in venues:
        raise ValueError('us_nyra_venue')
    selected=[]
    for a in soup.select('a[href*="race="]'):
        q=parse_qs(urlsplit(a['href']).query)
        if text(a)==f"Race {identity['race_number']}" and q.get('day')==[identity['date']] and q.get('race')==[str(identity['race_number'])]:
            selected.append(a)
    if len(selected)!=1:
        raise ValueError('us_nyra_selected_identity')
    alltext=text(soup)
    clock=re.search(r'(\d{1,2}:\d{2})([ap]) at '+re.escape(venues[identity['track']]),alltext)
    if not clock:
        raise ValueError('us_nyra_time_venue')
    off=datetime.strptime(identity['date']+' '+clock[1]+clock[2].upper()+'M','%Y-%m-%d %I:%M%p').replace(tzinfo=ZoneInfo('America/New_York'))
    owner_heading=soup.find(string=lambda t:t and t.strip()=='Owners')
    if owner_heading is None:
        raise ValueError('us_nyra_owner_count')
    owners={}
    for strong in owner_heading.parent.parent.select('strong'):
        n=text(strong)
        if n in owners:
            raise ValueError('us_nyra_owner_duplicate')
        owners[n]=text(strong.parent)[len(n):].lstrip(' -')
    rows=[]
    for a in soup.select('a[target^="equibase-horse-"]'):
        info=a.parent.parent;box=info.parent
        number=box.select_one('.order-1');current=box.select_one('[title="Current Odds"]');morning=box.select_one('[title="Morning Line Odds"]')
        details=info.find_all('div',recursive=False)
        if number is None or len(details)!=3:
            raise ValueError('us_nyra_runner_columns')
        n=text(number);people=text(details[1]).split(' • ')
        weight=re.fullmatch(r'(\d+)lbs • (?:([BO]) • )?(\d+)/([A-Za-z]+)',text(details[2]))
        if not re.fullmatch(r'\d+[A-Z]?',n) or n not in owners or len(people)!=2 or not weight:
            raise ValueError('us_nyra_runner')
        rows.append(dict(program_number=n,post_position=None,horse_name=text(a),jockey_name=people[0],
            trainer_name=people[1],carried_weight=weight[1]+' lb',equipment_raw=weight[2] or '',age=int(weight[3]),sex=weight[4],owner_name=owners[n],
            running_status='scratched' if current and text(current)=='SCR' else 'declared',
            morning_line_raw=text(morning).removeprefix('ML ') if morning else '',
            current_odds_raw=text(current) if current and text(current)!='SCR' else ''))
    if not rows or {r['program_number'] for r in rows}!=set(owners) or len(rows)!=len(owners):
        raise ValueError('us_nyra_roster_count')
    return dict(local_date=identity['date'],venue=identity['track'],race_number=identity['race_number'],
        off_time=off.isoformat(),source_stage='published_card',declared_count=len(rows),
        active_count=sum(r['running_status']=='declared' for r in rows),roster_complete=True,
        runners=rows,gaps=['post_position_not_provided'],fields_complete=False)
