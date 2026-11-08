"""HKJC 官方页面的纯解析与导航。年份、日期和场次均来自调用参数及页面。"""
from collections import Counter
from datetime import datetime
import hashlib
import re
from urllib.parse import parse_qs, urlsplit, urljoin, urlencode
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup


def text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def race_name(value):
    value=re.sub(r'\s*\((?:HANDICAP|H)\)\s*', ' ', value, flags=re.I)
    return re.sub(r'[^\w]', '', re.sub(r'^THE\s+', '', value.strip(), flags=re.I)).casefold()


def event_names(event):
    names=[event.original_name, event.chinese_name]
    if hasattr(event, 'aliases'):
        names.extend(event.aliases.values_list('text', flat=True))
    return {race_name(n) for n in names if n}


def identity(url):
    parsed=urlsplit(url)
    q={k.lower():v for k,v in parse_qs(parsed.query).items()}
    try:
        if any(len(q.get(k,[]))!=1 for k in ('racedate','racecourse','raceno')):
            raise ValueError
        day=datetime.strptime(q['racedate'][0].replace('-','/'), '%Y/%m/%d').date()
        course=q['racecourse'][0].upper();number=int(q['raceno'][0])
        if course not in {'ST','HV'} or not 1<=number<=20:raise ValueError
    except (KeyError, ValueError):
        raise ValueError('hkjc_identity_missing') from None
    return day,course,str(number)


def parse_card(page, *, url, route, now):
    if not route.permits_url(url) or route.region!='hong_kong':raise ValueError('hkjc_route_mismatch')
    day,course,number=identity(url)
    soup=BeautifulSoup(str(page),'html.parser')
    headers=[n for n in soup.select('div.f_fs13') if re.match(r'Race\s+\d+\s+-',text(n))]
    if len(headers)!=1:raise ValueError('hkjc_card_header_missing')
    lines=list(headers[0].stripped_strings)
    title=re.fullmatch(r'Race\s+(\d+)\s*-\s*(.+)',lines[0])
    meta=re.fullmatch(r'(.+), (Sha Tin|Happy Valley), (\d{2}:\d{2})',lines[1]) if len(lines)>1 else None
    if (not title or not meta or title[1]!=number
        or datetime.strptime(meta[1],'%A, %B %d, %Y').date()!=day
        or {'Sha Tin':'ST','Happy Valley':'HV'}[meta[2]]!=course):
        raise ValueError('hkjc_card_identity_mismatch')
    table=soup.select_one('table.starter')
    if table is None:raise ValueError('hkjc_card_missing')
    columns=[text(c) for c in table.select('thead tr')[0].find_all(['td','th'],recursive=False)]
    if not {'Horse No.','Horse','Wt.','Jockey','Draw','Trainer','Brand No.'}<=set(columns):
        raise ValueError('hkjc_card_columns_missing')
    rows=[]
    for tr in table.select('tbody tr'):
        cells=tr.find_all('td',recursive=False);values=list(map(text,cells))
        if values==columns:continue
        if len(cells)!=len(columns):raise ValueError('hkjc_card_partial')
        fields=dict(zip(columns,values));horse=cells[columns.index('Horse')].select_one('a[href]')
        hid={k.lower():v for k,v in parse_qs(urlsplit(horse['href']).query).items()}.get('horseid',[''])[0] if horse else ''
        if not hid or not text(horse) or not fields['Horse No.'].isdigit():raise ValueError('hkjc_card_horse_missing')
        weight=fields['Wt.'];withdrawn=bool(re.search(r'\bWithdrawn\b',text(tr),re.I))
        rows.append(dict(external_runner_id=hid,number=fields['Horse No.'],horse_name=text(horse),
            barrier=fields['Draw'],jockey_name=fields['Jockey'],trainer_name=fields['Trainer'],
            carried_weight=weight+'lb' if weight and weight!='---' else '',reported_finish_position=None,
            status='withdrawn' if withdrawn else 'declared',raw_status='WV' if withdrawn else '',
            finish_time='',margin='',field_provenance={'source_url':url}))
    if not rows or len({r['number'] for r in rows})!=len(rows):raise ValueError('hkjc_roster_invalid')
    venue='hkjc:'+course
    if venue not in route.venue_aliases:raise ValueError('hkjc_course_mismatch')
    return dict(provider=route.provider,region=route.region,identity_namespace=route.identity_namespace,
        external_race_id=f'HK{day:%Y%m%d}{course}{int(number):02d}',canonical_url=url,
        fetched_at=now.isoformat(),raw_sha256=getattr(page,'raw_sha256',hashlib.sha256(str(page).encode()).hexdigest()),
        parser_version=route.parser_version,operator=route.operator,venue_key=venue,local_date=day.isoformat(),
        timezone=route.timezone,meeting_session='single',race_number=number,raw_names=[title[2]],
        roster=rows,result_phase='',declaration_status='confirmed',roster_complete=True,
        off_time=datetime.combine(day,datetime.strptime(meta[3],'%H:%M').time(),ZoneInfo(route.timezone)).isoformat())


def result_roster_evidence(soup, rows, *, url, raw_sha256):
    """完整赛果与独立的逐马事件表对账，拒绝只截取前四名或漏掉最后一马。"""
    tables=[]
    for t in soup.select('table'):
        first=t.find('tr')
        if first and [text(c) for c in first.find_all(['td','th'],recursive=False)]==['Pla.','Horse No.','Horse','Incident']:
            tables.append(t)
    if not tables:return None
    if len(tables)!=1:raise ValueError('hkjc_incident_roster_ambiguous')
    actual=[]
    for tr in tables[0].select('tr')[1:]:
        cells=tr.find_all(['td','th'],recursive=False)
        if len(cells)!=4:raise ValueError('hkjc_incident_roster_partial')
        name=re.sub(r'\s*\([A-Z]{1,2}\d{3}\)\s*$', '', text(cells[2]))
        actual.append((text(cells[1]),name.casefold()))
    expected=[(r['number'],re.sub(r'\s*\([A-Z]{1,2}\d{3}\)\s*$','',r['horse_name']).casefold()) for r in rows]
    if len(set(actual))!=len(actual) or sorted(actual)!=sorted(expected):raise ValueError('hkjc_incident_roster_mismatch')
    return dict(url=url,sha256=raw_sha256,row_count=len(actual),kind='official_racing_incident_roster')


def parse_nominations(page, *, event, url):
    parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.netloc!='campaigns.hkjc.com'
        or not re.fullmatch(r'/[a-z0-9-]+/en/[a-z0-9-]+-racing-info/?',parsed.path)):
        raise ValueError('hkjc_nomination_url')
    soup=BeautifulSoup(str(page),'html.parser')
    names={race_name(text(h)) for h in soup.select('h1')}
    dates=[]
    for item in soup.select('.mrd-race-info-detail-item'):
        if text(item.select_one('.mrd-race-info-detail-item-top'))=='Date':
            dates.append(datetime.strptime(text(item.select_one('.mrd-race-info-detail-item-bottom')),'%d %b %Y').date())
    if dates!=[event.local_date] or not names.intersection(event_names(event)) or event.racecourse not in {'Sha Tin','沙田','沙田马场','沙田馬場'}:
        raise ValueError('hkjc_nomination_identity_mismatch')
    tables=[t for t in soup.select('table') if [text(c) for c in t.select('thead th')]==['Country/Region','Horse Name','Age','Sex','Trainer']]
    if len(tables)!=1:raise ValueError('hkjc_nomination_table_missing')
    whole=text(soup)
    total=re.search(r'Entries:\s*(\d+)\s*\(overseas:\s*(\d+),\s*local:\s*(\d+)\)',whole)
    stamp=re.search(r'As of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})',whole)
    if not total or not stamp:raise ValueError('hkjc_nomination_count_missing')
    observed=datetime.strptime(stamp[1],'%B %d, %Y').date()
    if observed>event.local_date:raise ValueError('hkjc_nomination_asof_mismatch')
    items=[];expected={};counts=Counter();country=''
    for tr in tables[0].select('tbody tr'):
        cells=[text(c) for c in tr.find_all(['td','th'],recursive=False)]
        if len(cells)!=5:raise ValueError('hkjc_nomination_partial')
        region,name,age,sex,trainer=cells
        if region:
            match=re.fullmatch(r'([A-Z]{2,3})\s*\((\d+)\)',region)
            if not match or match[1] in expected:raise ValueError('hkjc_nomination_country_count')
            country=match[1];expected[country]=int(match[2])
        if not country or not name or not age.isdigit() or not sex or not trainer:raise ValueError('hkjc_nomination_partial')
        counts[country]+=1
        items.append(dict(horse_name=name,horse_number='',barrier='',jockey_name='',trainer_name=trainer,
            carried_weight='',running_status='declared',source_refs={'primary':url,'country_region':country,
                'age':age,'sex':sex,'as_of':observed.isoformat(),'stage':'registration'}))
    n,overseas,local=map(int,total.groups())
    if (len(items)!=n or n!=overseas+local or counts['HKG']!=local or dict(counts)!=expected
        or len({r['horse_name'] for r in items})!=n):raise ValueError('hkjc_nomination_roster_incomplete')
    return dict(stage='registration',items=items,as_of=observed.isoformat(),published_count=n)


def meeting_races(page, *, url):
    """全日页只用于目录发现，绝不把该页前四名当完整赛果。"""
    base=urlsplit(url);q={k.lower():v for k,v in parse_qs(base.query).items()}
    day=datetime.strptime(q['racedate'][0],'%Y/%m/%d').date();course=q['racecourse'][0]
    soup=BeautifulSoup(str(page),'html.parser');output=[]
    if not re.search(r'Race Meeting:\s*'+re.escape(day.strftime('%d/%m/%Y')),text(soup)):
        raise ValueError('hkjc_meeting_date_mismatch')
    for block in soup.select('.race_result > div.margin_top15'):
        number=text(block.select_one('.bg_blue'))
        match=re.fullmatch(r'Race\s+(\d+)',number)
        if not match:continue
        headings=block.find_all('div',recursive=False)
        description=text(headings[1]) if len(headings)>1 else ''
        output.append(dict(race_number=match[1],description=description,
            url=urljoin(url,'localresults?'+urlencode(dict(racedate=day.strftime('%Y/%m/%d'),Racecourse=course,RaceNo=match[1])))))
    if not output or len({r['race_number'] for r in output})!=len(output):raise ValueError('hkjc_meeting_races_missing')
    return output


def parse_entries(page, *, event, url):
    """本地报名表的号码可能是候补顺序；一律不冒充正式马号。"""
    parsed=urlsplit(url);q={k.lower():v for k,v in parse_qs(parsed.query).items()}
    courses={'Sha Tin':'ST','沙田':'ST','沙田马场':'ST','沙田馬場':'ST',
             'Happy Valley':'HV','跑马地':'HV','跑馬地':'HV'}
    course=courses.get(event.racecourse)
    if (parsed.scheme!='https' or parsed.netloc!='racing.hkjc.com'
        or parsed.path!='/en-us/local/information/entries' or not course
        or q.get('racedate')!=[event.local_date.strftime('%Y/%m/%d')]
        or q.get('racecourse')!=[course]):raise ValueError('hkjc_entries_identity_mismatch')
    soup=BeautifulSoup(str(page),'html.parser');matches=[]
    for table in soup.select('table.loc'):
        block=table.parent.parent;heading=text(block).split('Horse (Brand No)',1)[0]
        m=re.search(r'Race Name\s*:\s*(.+?)\s+Distance',heading)
        if not m or race_name(m[1]) not in event_names(event):continue
        if not re.search(re.escape(event.local_date.strftime('%d/%m/%Y'))+r'\s+'+('Sha Tin' if course=='ST' else 'Happy Valley'),heading):
            raise ValueError('hkjc_entries_page_mismatch')
        section=re.search(r'Sec\./Div\. No\s*:\s*(\d+)',heading)
        selected=q.get('sectionno')
        if selected and (not section or selected!=[section[1]]):continue
        matches.append(block)
    if not matches and not soup.select('#entriescontent') and not any(message in text(soup) for message in ('No information.','Information will be released shortly.')):
        raise ValueError('hkjc_entries_page_missing')
    if len(matches)!=1:raise ValueError('not_published' if not matches else 'hkjc_entries_ambiguous')
    items=[]
    for table in matches[0].select('table.loc, table.loc_reserved'):
        columns=[text(c) for c in table.select_one('thead tr').find_all(['td','th'],recursive=False)]
        if not {'Horse (Brand No)','Trainer','Wt.'}<=set(columns):raise ValueError('hkjc_entries_columns')
        reserve='loc_reserved' in table.get('class',[])
        for tr in table.select('tbody tr'):
            values=[text(c) for c in tr.find_all(['td','th'],recursive=False)]
            if len(values)!=len(columns):raise ValueError('hkjc_entries_partial')
            fields=dict(zip(columns,values));name=fields['Horse (Brand No)']
            if not name or not fields['Trainer']:raise ValueError('hkjc_entries_partial')
            weight=fields['Wt.']
            if weight not in ('','-') and not weight.isdigit():raise ValueError('hkjc_entries_weight')
            items.append(dict(horse_name=re.sub(r'\s*\([A-Z]{1,2}\d{3}\)$','',name),horse_number='',barrier='',
                jockey_name='',trainer_name=fields['Trainer'],carried_weight=weight+'lb' if weight.isdigit() else '',
                running_status='declared',source_refs={'primary':url,'selection_status':'reserve' if reserve else 'entry',
                    'source_fields':fields,'stage':'registration'}))
    if not items or len({r['horse_name'] for r in items})!=len(items):raise ValueError('hkjc_entries_roster')
    return dict(stage='registration',items=items,published_count=len(items))


def parse_pattern_schedule(raw):
    """读取官方 Pattern Book 的赛季目录，包含分级赛和另列的四岁系列。"""
    import io
    import pdfplumber
    rows={}
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            content=page.extract_text() or ''
            if 'SCHEDULE OF RACES' not in content or 'Race Date' not in content:continue
            for m in re.finditer(r'(\d{2}/\d{2}/\d{2})\s+(.+?)\s+(G[123]|LR)\s+([\d,]+)\s+(\S+)\s+(\d{3,4})\s+',content):
                day=datetime.strptime(m[1],'%d/%m/%y').date().isoformat()
                item=dict(local_date=day,name=m[2],grade=m[3],prize_hkd=int(m[4].replace(',','')),distance_m=int(m[6]),racecourse='Happy Valley' if race_name(m[2])=='januarycup' else 'Sha Tin')
                key=(day,race_name(item['name']))
                if key in rows and rows[key]!=item:raise ValueError('hkjc_schedule_conflict')
                rows[key]=item
            # PDF 跨页 spread 可能重复同一目录，按身份去重；不读取后面的历史赛果目录。
            if rows:break
    if not rows:raise ValueError('hkjc_schedule_missing')
    return sorted(rows.values(),key=lambda r:(r['local_date'],r['name']))


def course_code(event,route):
    found=[key.split(':')[-1] for key,names in route.venue_aliases.items() if event.racecourse in names]
    if len(found)!=1 or found[0] not in {'ST','HV'}:raise ValueError('hkjc_course_mismatch')
    return found[0]


def discover_card(*,event,route,now,fetcher):
    """按参数化日期进入官方卡表，再跟随该赛日真实导航，不猜比赛号码。"""
    course=course_code(event,route)
    base='https://racing.hkjc.com/en-us/local/information/racecard'
    url=base+'?'+urlencode(dict(racedate=event.local_date.strftime('%Y/%m/%d'),Racecourse=course))
    if not route.permits_url(url):raise ValueError('source_url_rejected')
    page=fetcher(url,route=route,now=now);soup=BeautifulSoup(str(page),'html.parser')
    header=[h for h in soup.select('div.f_fs13') if re.match(r'Race\s+\d+\s+-',text(h))]
    if not header:
        if 'No information.' in text(soup):return None
        raise ValueError('hkjc_card_header_missing')
    if len(header)!=1:raise ValueError('hkjc_card_header_ambiguous')
    number=re.match(r'Race\s+(\d+)',text(header[0]))[1]
    selected=url+'&RaceNo='+number
    # 首个页面也必须匹配所请求的日期与马场，禁止默认旧页回退。
    initial=parse_card(page,url=selected,route=route,now=now)
    links={selected:page}
    for a in soup.select('a[href]'):
        target=urljoin(url,a['href'])
        if urlsplit(target).path!=base.removeprefix('https://racing.hkjc.com'):continue
        try:day,c,n=identity(target)
        except ValueError:continue
        if day==event.local_date and c==course and route.permits_url(target):links.setdefault(target,None)
    if len(links)>20:raise ValueError('hkjc_card_links_ambiguous')
    matches=[]
    for target,raw in links.items():
        if raw is None:raw=fetcher(target,route=route,now=now)
        obs=initial if target==selected else parse_card(raw,url=target,route=route,now=now)
        if event_names(event).intersection(race_name(n) for n in obs['raw_names']):matches.append((target,raw,obs))
    if len(matches)>1:raise ValueError('hkjc_card_identity_ambiguous')
    return matches[0] if matches else None


def discover_result_url(*,event,route,now,fetcher):
    course=course_code(event,route)
    url='https://racing.hkjc.com/en-us/local/information/resultsall?'+urlencode(dict(
        racedate=event.local_date.strftime('%Y/%m/%d'),Racecourse=course))
    if not route.permits_url(url):raise ValueError('source_url_rejected')
    page=fetcher(url,route=route,now=now)
    matches=[r['url'] for r in meeting_races(page,url=url)
        if any(race_name(r['description'].rsplit(' - ',1)[-1])==name for name in event_names(event))]
    if len(matches)!=1:raise ValueError('hkjc_result_identity_not_unique')
    return matches[0]
