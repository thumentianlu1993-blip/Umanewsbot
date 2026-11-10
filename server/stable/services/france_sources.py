"""法国来源语义。输入为浏览器可见 DOM 的文本和表格，不读取页面内部状态。"""
from collections import Counter
from datetime import datetime
import re
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


def document_from_html(page, url):
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(str(page),'html.parser')
    doc=dict(url=url,title=soup.title.get_text() if soup.title else '',text=soup.get_text('\n',strip=True),
        tables=[dict(rows=[[c.get_text(' ',strip=True) for c in tr.select('th,td')] for tr in t.select('tr')]) for t in soup.select('table')])
    if urlsplit(url).hostname=='www.geny.com':
        if url.endswith('/partants-pronostics'):
            tables=[t['rows'] for t in doc['tables'] if t['rows'] and t['rows'][0][:3]==['N°','Cas.','Cheval']]
            if len(tables)!=1:raise ValueError('geny_card_table')
            doc['rows']=tables[0]
        elif url.endswith('/arrivee-rapports'):
            doc['rows']=[]
            for box in soup.select('div.h-10.flex-row'):
                children=box.find_all('div',recursive=False)
                if len(children)!=2:continue
                rank=children[0].get_text('',strip=True)
                leaves=[text(x.get_text('',strip=True)) for x in children[1].select('div[dir="auto"]')]
                if re.fullmatch(r'\d+(?:er|e)|Tb|Arr|TJ',rank) and len(leaves)==6:
                    doc['rows'].append(dict(rank=rank,leaves=leaves))
    return doc


def validate_event_identity(value, event, route):
    if value['local_date']!=event.local_date.isoformat():raise ValueError('france_date_mismatch')
    if not race_name_keys(value['race_name']) & {key for n in event_names(event) for key in race_name_keys(n)}:
        raise ValueError('france_name_mismatch')
    venues=[k for k,names in route.venue_aliases.items() if name_key(value['venue']) in {name_key(n) for n in names}]
    expected=[k for k,names in route.venue_aliases.items() if name_key(event.racecourse) in {name_key(n) for n in names}]
    if len(venues)!=1 or venues!=expected:raise ValueError('france_venue_mismatch')
    return venues[0]


def discover_geny_url(*, event, route, now, fetcher):
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    refs=event.source_refs or {}
    hints=[refs.get('primary','')]+refs.get('reference_urls',[])
    hints={u.rsplit('/',1)[0] for u in hints if isinstance(u,str) and route.permits_url(u) and '/course/' in u}
    if len(hints)==1:
        url=next(iter(hints))+'/partants-pronostics'
        if geny_key(url)[2]!=event.local_date.isoformat():raise ValueError('france_date_mismatch')
        return url
    index='https://www.geny.com/programme/'+event.local_date.isoformat()
    if not route.permits_url(index):raise ValueError('source_url_rejected')
    page=fetcher(index,route=route,now=now)
    names=event_names(event)
    courses=[n for aliases in route.venue_aliases.values() if name_key(event.racecourse) in {name_key(n) for n in aliases} for n in aliases]
    wanted={name_key(course)+key for course in courses for name in names if name for key in race_name_keys(name)}
    matches=set()
    for link in BeautifulSoup(str(page),'html.parser').select('a[href]'):
        url=urljoin(index,link['href'])
        if not route.permits_url(url):continue
        try:key=geny_key(url)
        except ValueError:continue
        if key[2]==event.local_date.isoformat() and name_key(key[3]) in wanted:
            matches.add(url.rsplit('/',1)[0]+'/partants-pronostics')
    if len(matches)!=1:raise ValueError('source_discovery_ambiguous' if matches else 'not_published')
    return matches.pop()


def race_name_keys(value):
    plain=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()
    return {name_key(value),re.sub('[^a-z0-9]','',plain)}


def event_names(event):
    names=[event.original_name,event.chinese_name]
    if hasattr(event,'aliases'):names.extend(event.aliases.values_list('text',flat=True))
    if getattr(event,'race_series_id',None):
        from stable.models import RaceSeriesName
        from django.db.models import Q
        names.extend(RaceSeriesName.objects.filter(series_id=event.race_series_id,is_active=True).filter(
            Q(valid_from_year=0)|Q(valid_from_year__lte=event.year)).filter(
            Q(valid_to_year=0)|Q(valid_to_year__gte=event.year)).values_list('text',flat=True))
    return names


def text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def name_key(value):
    value = unicodedata.normalize('NFKD', re.sub(r'\([^)]*\)', '', value))
    return re.sub('[^a-z0-9]', '', value.encode('ascii','ignore').decode().lower())


def decimal(value):
    value = text(value).replace(',', '.')
    return value if re.fullmatch(r'\d+(?:\.\d+)?', value) else ''


def weight(value):
    value = decimal(re.sub(r'\s*kg$', '', text(value)))
    if not value:
        raise ValueError('france_weight_invalid')
    return value + ' kg'


def geny_key(url):
    p = urlsplit(url)
    m = re.fullmatch(r'/course/(\d+)-(\d{4}-\d{2}-\d{2})-([^/]+)/(partants-pronostics|arrivee-rapports)',p.path)
    if p.scheme != 'https' or p.netloc != 'www.geny.com' or p.query or p.fragment or not m:
        raise ValueError('geny_identity_url')
    return m


def parse_geny_card(doc):
    key = geny_key(doc['url'])
    data = doc.get('rows', [])
    if not data or data[0][:3] != ['N°','Cas.','Cheval'] or data[0][6:10] != ['Poids','Déch.','Jockey','Entraîneur']:
        raise ValueError('geny_card_headers')
    rows=[]
    for cells in data[1:]:
        if len(cells)==13 and cells[-1]=='NP':cells=cells[:-1]+['NP','NP']
        if len(cells)!=14 or not cells[0].isdigit() or not cells[2]:
            raise ValueError('geny_card_row')
        adjusted=decimal(cells[7])
        quotes={n:v for n,c in [('PMU',cells[12]),('Genybet',cells[13])] if (v:=decimal(c))}
        rows.append(dict(external_runner_id='number:'+cells[0],horse_name=cells[2],number=cells[0],
            barrier=cells[4].strip('()') if cells[4].strip('()').isdigit() else '',
            jockey_name='' if cells[8]=='NP' else cells[8],trainer_name=cells[9],
            carried_weight=weight(cells[6]),status='non_runner' if 'NP' in cells else 'declared',
            raw_status='NP' if 'NP' in cells else '',reported_finish_position=None,finish_time='',margin='',
            odds_value=quotes.get('Genybet',''),field_provenance=dict(
                source_url=doc['url'],field_units={'carried_weight':'kg','odds_value':'decimal'},
                allocated_weight=weight(cells[6]),adjusted_weight=adjusted+' kg' if adjusted else '',odds_quotes=quotes,odds_source='Genybet')))
    if not rows or len({r['number'] for r in rows})!=len(rows):
        raise ValueError('geny_card_count')
    return dict(external_race_id=key[1],local_date=key[2],roster=rows,roster_complete=True,result_phase='')


def parse_geny_result(doc, card):
    key, card_key = geny_key(doc['url']),geny_key(card['url'])
    if key.groups()[:3]!=card_key.groups()[:3]:
        raise ValueError('geny_card_identity')
    if 'ARRIVÉE DÉFINITIVE' not in doc.get('text','').upper():
        raise ValueError('geny_result_not_final')
    value=parse_geny_card(card)
    from .france_basic_fields import digest
    for row in value['roster']:
        row['field_provenance']['card_fields'] = dict(
            source_url=card['url'],raw_sha256=digest(card),horse_name=row['horse_name'],number=row['number'],
            trainer_name=row['trainer_name'],carried_weight=row['carried_weight'],odds_value=row['odds_value'],
            adjusted_weight=row['field_provenance']['adjusted_weight'])
    count=re.search(r'(\d+)\s+partants',doc.get('text',''),re.I)
    if not count or int(count[1])!=len(value['roster']):raise ValueError('geny_roster_count')
    results={}
    for result in doc.get('rows',[]):
        leaves=result.get('leaves',[])
        if len(leaves)!=6 or not leaves[0].rstrip('.').isdigit():
            raise ValueError('geny_result_row')
        number=leaves[0].rstrip('.')
        if number in results:raise ValueError('geny_duplicate_result')
        results[number]=result
    if set(results)-{r['number'] for r in value['roster']}:
        raise ValueError('geny_unknown_runner')
    for row in value['roster']:
        result=results.get(row['number'])
        if result is None:
            if row['status']!='non_runner':raise ValueError('geny_missing_result')
            continue
        if row['status']=='non_runner':raise ValueError('geny_conflicting_nonrunner')
        raw=result['rank'];leaves=result['leaves']
        if name_key(row['horse_name'])!=name_key(leaves[1]):raise ValueError('geny_horse_identity')
        pos=re.fullmatch(r'(\d+)(?:er|e)',raw)
        status='finished' if pos else {'Tb':'fell','Arr':'pulled_up','TJ':'unseated_rider'}.get(raw)
        if not status:raise ValueError('geny_unknown_status')
        kg=re.search(r'\(([\d,.]+) kg\)$',leaves[2])
        if not kg:raise ValueError('geny_result_weight')
        quotes={n:v for n,c in [('PMU',leaves[4]),('Genybet',leaves[5])] if (v:=decimal(c))}
        clock=leaves[3] if re.fullmatch(r'\d+\x27\d+"\d*',leaves[3]) else ''
        margin=leaves[3] if status=='finished' and not clock else ''
        margin={'TETE':'head','ENC':'neck','CENC':'short neck','CTETE':'short head','NEZ':'nose','LOIN':'大差'}.get(margin,margin)
        row.update(status=status,raw_status=raw,reported_finish_position=int(pos[1]) if pos else None,
            carried_weight=weight(kg[1]),finish_time=clock,
            margin=margin,odds_value=quotes.get('Genybet',''))
        row['field_provenance'].update(source_url=doc['url'],odds_quotes=quotes,
            odds_source='Genybet',win_odds=quotes.get('Genybet',''),margin_relation='previous_finisher',source_margin=leaves[3] if not clock else '')
    positions=Counter(r['reported_finish_position'] for r in value['roster'] if r['reported_finish_position'])
    for row in value['roster']:
        if positions[row['reported_finish_position']]>1:row['status']='dead_heat'
    value.update(result_phase='official',roster_complete=True)
    return value


def parse_geny_observation(page, *, url, route, now, card_page=None):
    import hashlib
    from bs4 import BeautifulSoup
    if not route.permits_url(url):raise ValueError('source_url_rejected')
    key=geny_key(url)
    doc=document_from_html(page,url)
    title=re.fullmatch(r"(?:Arrivée et rapports|Partants et pronostics) (?:de la course|du Quinté\+) (.+) à (.+) le (\d+) ([^ ]+) (\d{4}) \| Geny",doc['title'])
    if not title:raise ValueError('geny_title_identity')
    months=['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre']
    try:day=datetime(int(title[5]),months.index(title[4])+1,int(title[3])).date()
    except (ValueError,IndexError):raise ValueError('geny_title_date') from None
    if day.isoformat()!=key[2]:raise ValueError('geny_date_identity')
    venues=[k for k,names in route.venue_aliases.items() if name_key(title[2]) in {name_key(n) for n in names}]
    if len(venues)!=1:raise ValueError('venue_unreviewed')
    card_url=url.rsplit('/',1)[0]+'/partants-pronostics'
    if key[4]=='arrivee-rapports':
        if card_page is None:raise ValueError('geny_card_required')
        value=parse_geny_result(doc,document_from_html(card_page,card_url))
    else:value=parse_geny_card(doc)
    soup=BeautifulSoup(str(page),'html.parser')
    tz=soup.select_one('meta[name="source-timezone"]')
    clock=re.search(r'Départ\s*(\d{1,2})h(\d{2})',doc['text'])
    off=''
    if clock and tz and (int(clock[1]),int(clock[2])) != (0,0):
        zone=tz.get('content','')
        if zone not in ('Europe/Paris','Asia/Shanghai'):raise ValueError('geny_time_zone')
        off=datetime(day.year,day.month,day.day,int(clock[1]),int(clock[2]),tzinfo=ZoneInfo(zone)).astimezone(ZoneInfo('Europe/Paris')).isoformat()
    for row in value['roster']:
        row['field_provenance']['odds_observed_at']=(getattr(page,'observed_at',None) or now).isoformat()
        if 'card_fields' in row['field_provenance']:
            row['field_provenance']['card_fields']['observed_at']=(getattr(card_page,'observed_at',None) or now).isoformat()
    value.update(provider=route.provider,region=route.region,identity_namespace=route.identity_namespace,
        canonical_url=url,fetched_at=(getattr(page,'observed_at',None) or now).isoformat(),raw_sha256=getattr(page,'raw_sha256',hashlib.sha256(str(page).encode()).hexdigest()),
        parser_version=route.parser_version,operator=route.operator,venue_key=venues[0],timezone='Europe/Paris',
        meeting_session='',race_number='',raw_names=[title[1]],off_time=off)
    from .france_basic_fields import parse_basic
    value['france_basic_v1'] = parse_basic(doc, identity=dict(local_date=day.isoformat(),
        external_race_id=key[1], race_name=title[1], venue=title[2]), raw_sha256=value['raw_sha256'],
        observed_at=value['fetched_at'], parser_version=route.parser_version)
    if off:
        value['time_evidence'] = dict(source_timezone=tz.get('content'),kind='scheduled_start',
            source_clock=clock[0],source_url=url,raw_sha256=value['raw_sha256'])
    if card_page is not None:
        value['roster_evidence']=dict(kind='independent_card',url=card_url,
            sha256=hashlib.sha256(str(card_page).encode()).hexdigest(),row_count=len(value['roster']))
    return value


def parse_france_galop_document(doc):
    p=urlsplit(doc['url'])
    if p.scheme!='https' or p.netloc!='www.france-galop.com' or not re.fullmatch(r'/fr/course/detail/\d{4}/[PO]/[A-Za-z0-9=]+',p.path):
        raise ValueError('fg_source_url')
    body=text(doc.get('text',''))
    meta=re.search(r'(\d+)(?:ème|ère|er)\([PO]/\s*\d+\),\s*—\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}h\d{2}),\s*([^\n]+)',doc.get('text',''))
    if not meta:raise ValueError('fg_identity_missing')
    day=datetime.strptime(meta[2],'%d/%m/%Y').date()
    off='' if meta[3]=='00h00' else datetime.strptime(meta[2]+' '+meta[3],'%d/%m/%Y %Hh%M').replace(tzinfo=ZoneInfo('Europe/Paris')).isoformat()
    value=dict(local_date=day.isoformat(),venue=meta[4].strip(),race_number=meta[1],
        race_name=doc['title'].split(' | ')[0],off_time=off,items=[],schedule=[row for table in doc.get('tables',[]) for row in table.get('rows',[]) if len(row)==3 and re.fullmatch(r'\d{2}h\d{2} PARIS',row[-1])])
    from .france_basic_fields import parse_basic
    value['france_basic_v1'] = parse_basic(doc, identity={k:value[k] for k in ('local_date','venue','race_name')})
    if 'AUCUNE LISTE DIFFUSABLE' in body:
        return dict(value,stage='not_published',source_stage='not_published')
    phase=re.search(r'Après\s+([^:]+):',body,re.I)
    if not phase:raise ValueError('fg_stage_missing')
    label=phase[1].strip().casefold()
    if label in ('part. probables','partants probables'):
        stage,source_stage='declared','probable_runners'
    elif label in ('engagements','second-engagements','forfaits','forfait 1','forfait 2','engagements supplementaires','engagements supplémentaires'):
        stage,source_stage='registration','second_entries' if label=='second-engagements' else 'entries'
    else:
        # 未取得正式声明表合同前不按 Partants 单词猜正式出赛。
        raise ValueError('fg_stage_unverified')
    tables=[t['rows'] for t in doc.get('tables',[]) if t.get('rows') and t['rows'][0][:3]==['N°','Cheval','Poids']]
    if len(tables)!=1:raise ValueError('fg_roster_missing')
    headers=tables[0][0]
    if 'Entraîneur' not in headers:raise ValueError('fg_trainer_header')
    for row in tables[0][1:]:
        if len(row)!=len(headers):raise ValueError('fg_roster_row')
        horse=re.split(r'\s+[FMH]\.\s*(?:PS|AQPS)\.',row[1],flags=re.I)[0]
        if not horse:raise ValueError('fg_horse_empty')
        value['items'].append(dict(horse_name=horse,horse_number='',barrier='',jockey_name='',
            trainer_name=row[headers.index('Entraîneur')],carried_weight=weight(row[2]),running_status='declared',
            source_refs=dict(primary=doc['url'],registration_number=row[0],
                field_units={'carried_weight':'kg'},source_stage=source_stage)))
    count=re.search(r'(\d+)\s+Partants'+(r' probables' if source_stage=='probable_runners' else r'\.'),body,re.I)
    if not count or int(count[1])!=len(value['items']) or not value['items']:
        raise ValueError('fg_roster_count')
    return dict(value,stage=stage,source_stage=source_stage)
