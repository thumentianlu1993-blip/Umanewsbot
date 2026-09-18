"""窄单场 HTML 适配；不搜索、不联网、不猜测缺席即退赛。"""
from datetime import datetime
import json
import re
from urllib.parse import parse_qs, urlsplit
from bs4 import BeautifulSoup
from .race_pre_race_refresh import validate_bound_url


def text(node):return node.get_text(' ',strip=True) if node else ''


def _horse_name(value):
    return re.sub(r'\s*\([A-Z]{2,3}\)\s*$','',value).strip()


def _sporting(html,event,url):
    from stable.race_reference_parsers.sporting_life import _next_data, parse_legacy_page
    race=_next_data(html)['props']['pageProps']['race'];summary=race['race_summary']
    race_id=re.search(r'/racecard/(\d+)/',url).group(1)
    if str(summary.get('race_summary_reference',{}).get('id'))!=race_id or summary.get('date')!=event.local_date.isoformat():raise ValueError('refresh_page_identity_mismatch')
    if summary.get('race_stage') not in {'DORMANT','DECLARED','RACECARD'}:raise ValueError('refresh_not_pre_race')
    rows,results,_=parse_legacy_page(html,source_url=url)
    rides=race.get('rides',[])
    if results or len(rows)!=len(rides) or len(rows)!=summary.get('ride_count'):raise ValueError('refresh_partial_roster')
    by_number={str(ride.get('cloth_number')):ride for ride in rides}
    for row in rows:
        ride=by_number[row['horse_number']];raw=ride.get('ride_status','')
        if raw=='RUNNER':row['running_status']='declared'
        elif raw in {'NON_RUNNER','NONRUNNER','WITHDRAWN','SCRATCHED'}:row['running_status']='scratched'
        else:raise ValueError('refresh_unknown_status')
        row.update(odds_kind='current',odds_format='fractional')
        if (ride.get('betting') or {}).get('updated_at'):row['odds_source_at']=ride['betting']['updated_at']
    return rows


def _zeturf(html,event,url):
    from stable.race_reference_parsers.zeturf import parse_legacy_page,_title_parts
    if _title_parts(html)['date']!=event.local_date.isoformat():raise ValueError('refresh_page_identity_mismatch')
    rows,results,_=parse_legacy_page(html,source_url=url)
    soup=BeautifulSoup(html,'html.parser')
    if results or len(rows)!=len(soup.select('table.table-runners tbody tr[data-runner]')):raise ValueError('refresh_partial_roster')
    for row in rows:row.update(odds_kind='current',odds_format='decimal')
    return rows


def _nyra(soup,event,url):
    q=parse_qs(urlsplit(url).query);section=soup.select_one('[data-rdl-race]')
    if section is None or q['day']!=[event.local_date.isoformat()] or event.timezone_name!='America/New_York':raise ValueError('refresh_page_identity_mismatch')
    day_button=section.select_one('[data-dropdown-trigger]')
    expected=event.local_date.strftime('%A, %B ')+str(event.local_date.day)
    if text(day_button)!=expected:raise ValueError('refresh_page_date_mismatch')
    body=text(section)
    # Single selected race has a heading separate from the meeting navigation.
    content=section.select_one('div.py-7')
    if content is None:raise ValueError('refresh_page_identity_mismatch')
    headline=text(content)
    if not re.match(r'Race\s+'+re.escape(q['race'][0])+r'\b',headline) or 'Belmont Park' not in headline:raise ValueError('refresh_page_identity_mismatch')
    rows=[]
    for horse in content.select('a[href*="equibase.com/profiles/"]'):
        block=horse.find_parent('div',class_='order-3')
        if not block:raise ValueError('refresh_partial_roster')
        row=block.parent;number=text(row.select_one('.order-1'))
        odds=text(row.select_one('[title="Current Odds"]'));ml=text(row.select_one('[title="Morning Line Odds"]')).removeprefix('ML ')
        people=block.select('div.text-zinc-800');crew=text(people[0]).split(' • ') if people else []
        weight=re.search(r'(\d+)lbs',text(block))
        hid=parse_qs(urlsplit(horse['href']).query).get('refno',[''])[0]
        kind='current' if re.fullmatch(r'\d+/\d+|EVS',odds) else 'morning_line'
        rows.append(dict(horse_name=_horse_name(text(horse)),horse_number=number,barrier='',
            jockey_name=crew[0] if len(crew)==2 else '',trainer_name=crew[1] if len(crew)==2 else '',
            carried_weight=weight.group(1)+'lb' if weight else '',running_status='scratched' if odds=='SCR' else 'declared',
            odds_value=odds if kind=='current' else ml,odds_kind=kind,odds_format='fractional',source_refs={'horse_id':hid,'field_units':{'carried_weight':'lb'}}))
    return rows


def _nar(soup,event,url):
    q=parse_qs(urlsplit(url).query)
    if q['k_raceDate']!=[event.local_date.strftime('%Y/%m/%d')] or event.timezone_name!='Asia/Tokyo':raise ValueError('refresh_page_identity_mismatch')
    header=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日（.）\s*(.+?)\s*第(\d+)競走',text(soup))
    if not header or datetime(*map(int,header.groups()[:3])).date()!=event.local_date or header[5]!=q['k_raceNo'][0]:raise ValueError('refresh_page_identity_mismatch')
    if re.sub(r'\s','',header[4]).replace('沢','泽')!=event.racecourse.replace('沢','泽'):raise ValueError('refresh_page_course_mismatch')
    rows=[];barrier=''
    for horse in soup.select('a.horseName'):
        first=horse.find_parent('tr');following=list(first.find_next_siblings('tr',limit=4))
        if len(following)!=4 or any(r.select_one('a.horseName') for r in following):raise ValueError('refresh_partial_roster')
        if first.select_one('td.courseNum'):barrier=text(first.select_one('td.courseNum'))
        odds_cell=first.select_one('td.odds_weight');raw=text(odds_cell)
        cancelled=' '.join([raw,text(first.select_one('td.horseNum')),text(following[-1].select_one('td.info'))])
        next_cells=following[0].find_all('td',recursive=False);third_cells=following[1].find_all('td',recursive=False)
        weight=re.match(r'(\d+(?:\.\d+)?)',text(next_cells[3])) if len(next_cells)>3 else None
        odds=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:\((\d+)\)|（(\d+)）)?',raw)
        rows.append(dict(horse_name=text(horse),horse_number=text(first.select_one('td.horseNum')),barrier=barrier,
            jockey_name=text(first.select_one('a.jockeyName')),trainer_name=text(third_cells[1]) if len(third_cells)>1 else '',
            carried_weight=weight.group(1)+'kg' if weight else '',running_status='scratched' if re.search('取消|除外',cancelled) else 'declared',
            odds_value=odds[1] if odds else '',popularity=(odds[2] or odds[3] or '') if odds else '',odds_kind='current',odds_format='decimal',
            source_refs={'horse_id':parse_qs(urlsplit(horse['href']).query).get('k_lineageLoginCode',[''])[0]}))
    return rows


def _racing_post(soup,event,url):
    # Public server-rendered card contract verified from the actual React DOM.
    race_id=urlsplit(url).path.strip('/').split('/')[-1]
    sport=[]
    for script in soup.select('script[type="application/ld+json"]'):
        value=json.loads(script.string or script.get_text())
        for node in value if isinstance(value,list) else [value]:
            if node.get('@type')=='SportsEvent':sport.append(node)
    if len(sport)!=1:raise ValueError('refresh_page_identity_mismatch')
    start=datetime.fromisoformat(sport[0].get('startDate','').replace('Z','+00:00'))
    from zoneinfo import ZoneInfo
    if not start.tzinfo or start.astimezone(ZoneInfo(event.timezone_name)).date()!=event.local_date:raise ValueError('refresh_page_date_mismatch')
    forecast={}
    for group in soup.select('[data-testid="Group__BettingForecast"]'):
        price=text(group.find('span',recursive=False))
        for link in group.select('a[href*="/profile/horse/"]'):
            forecast[urlsplit(link['href']).path.split('/')[3]]=price
    rows=[]
    for row in soup.select('[data-testid="Container__RunnerRowDesktop"]'):
        horse=row.select_one('[data-testid="Link__Horse"]')
        number=text(row.select_one('[data-testid="Container__RunnerNumber"]'))
        match=re.fullmatch(r'(\d+)\s*(?:\(\s*(\d+)\s*\))?',number)
        if horse is None or not match or f'race-id={race_id}/' not in horse.get('href',''):raise ValueError('refresh_partial_roster')
        hid=urlsplit(horse['href']).path.split('/')[3]
        def person(kind):
            node=row.select_one(f'[data-testid="Link__{kind}"]')
            return text(node.find('span',recursive=False)) if node else ''
        weight=re.search(r'(\d+)\s*st\s*(\d+)\s*lb',text(row))
        rows.append(dict(horse_name=text(horse),horse_number=match[1],barrier=match[2] or '',jockey_name=person('Jockey'),trainer_name=person('Trainer'),
            carried_weight=f'{weight[1]}st {weight[2]}lb' if weight else '',running_status='non_runner' if re.search(r'\bNon[ -]runner\b',text(row),re.I) else 'declared',
            odds_value=forecast.get(hid,''),odds_kind='forecast',odds_format='fractional',source_refs={'horse_id':hid}))
    return rows


def parse_bound_card(html,*,event,url):
    p=validate_bound_url(url);lower=html.strip().lower()
    if not lower.endswith('</html>') or '</body>' not in lower:raise ValueError('refresh_document_truncated')
    # Date-bound URLs cannot be used for another source-day even with similar runners.
    day=event.local_date.isoformat()
    if p.hostname in {'www.sportinglife.com','www.zeturf.fr','www.racingpost.com'} and '/'+day+'/' not in p.path:raise ValueError('refresh_page_date_mismatch')
    soup=BeautifulSoup(html,'html.parser')
    try:
        if p.hostname=='www.sportinglife.com':items=_sporting(html,event,url)
        elif p.hostname=='www.zeturf.fr':items=_zeturf(html,event,url)
        elif p.hostname=='www.nyra.com':items=_nyra(soup,event,url)
        elif p.hostname=='www.keiba.go.jp':items=_nar(soup,event,url)
        else:items=_racing_post(soup,event,url)
    except (KeyError,TypeError,IndexError,RuntimeError,json.JSONDecodeError) as exc:raise ValueError('refresh_source_parse_failed') from exc
    if not items or any(not r.get('horse_name') or not str(r.get('horse_number','')).isdigit() for r in items):raise ValueError('refresh_partial_roster')
    return {'items':items,'stage':'numbered'}
