"""美国已发布的计划奖金：完整日期/赛场/赛名匹配，官方优先，不能代替正式卡。"""
from datetime import datetime
from decimal import Decimal
from io import BytesIO
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pdfplumber

from .us_flat_results import key

USR = 'https://usracing.com/graded-stakes-schedule'
NYRA = 'https://www.nyra.com/belmont/racing/stakes-schedule/'
DMR = 'https://www.dmtc.com/horsemen/nomforms'
CD = 'https://www.churchilldowns.com/overnights/'
GP = 'https://www.gulfstreampark.com/racing-information/stakes/2025-04-29/'
# 已核同一赛事目录的简称/冠名，不做相似度匹配。
ALIASES = {'fasigtiptongoldenrod':'goldenrod', 'jockeyclubderbyinvitational':'jockeyclubderby',
           'jockeycluboaksinvitational':'jockeycluboaks', 'ftlauderdale':'fortlauderdale', 'remsenpresbytwinspires':'remsen',
           'manowarpresbyhorseracingireland':'manowar'}
TRACKS = {'Belmont Park':'BEL', 'Churchill Downs':'CD', 'Del Mar':'DMR', 'Gulfstream Park':'GP',
          'Los Alamitos':'LRC', 'Santa Anita':'SA', 'Parx Racing':'PRX'}


def race_name(value):
    value = re.sub(r'\([^)]*\)', '', value)
    value = re.sub(r'^The\s+|\b(?:Stakes|S\.|Handicap|H\.)\s*', '', value, flags=re.I)
    return ALIASES.get(key(value), key(value))


def amount(raw):
    match = re.fullmatch(r'\$([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\s+(?:Guaranteed|Added))?', raw.strip(), re.I)
    if not match or Decimal(match[1].replace(',','')) <= 0:
        raise ValueError('us_schedule_purse')
    return match[1].replace(',','')


def record(day, venue, name, purse, grade=''):
    return dict(local_date=day, venue=venue, race_name=name, prize_amount=amount(purse),
                prize_currency='USD', grade=grade)


class ScheduleConflict(ValueError):
    def __init__(self, identities, valid_rows):
        super().__init__('us_schedule_conflict')
        self.identities=set(identities)
        self.valid_rows=valid_rows


def parse_schedule(raw, *, url):
    soup = BeautifulSoup(raw, 'lxml') if not raw.startswith(b'%PDF') else None
    rows = []
    if url == USR:
        table = soup.select_one('table#gradedStakes')
        if not table:raise ValueError('us_schedule_table')
        for tr in table.select('tbody tr'):
            cells = tr.find_all('td', recursive=False)
            if len(cells) != 4:raise ValueError('us_schedule_row')
            values = [c.get_text(' ', strip=True) for c in cells]
            if values[2] not in TRACKS:continue
            day = datetime.strptime(values[0], '%b %d, %Y').date().isoformat()
            rows.append(record(day, TRACKS[values[2]], values[1], values[3]))
    elif url == NYRA:
        for table in soup.select('table'):
            headings = [h.get_text(' ', strip=True) for h in table.select('thead th')]
            if headings[:4] != ['Date','Race','Grade','Purse']:continue
            for tr in table.select('tbody tr'):
                cells = [c.get_text(' ', strip=True) for c in tr.find_all('td', recursive=False)]
                if len(cells) < 8:raise ValueError('us_schedule_row')
                text = cells[0].replace('Sept.', 'Sep').replace('.', '')
                try:day = datetime.strptime(text, '%b %d, %Y').date().isoformat()
                except ValueError:day = datetime.strptime(text, '%B %d, %Y').date().isoformat()
                grade = {'I':'G1','II':'G2','III':'G3'}.get(cells[2], '')
                if grade:rows.append(record(day, 'BEL', cells[1], cells[3], grade))
    elif url == DMR:
        title = next((h.get_text(' ',strip=True) for h in soup.select('h1,h2,h3') if 'Season Stakes Nomination Forms' in h.get_text()), '')
        year = re.match(r'^(\d{4}) (?:Bing Crosby|Summer) Season Stakes Nomination Forms$', title)
        if not year:raise ValueError('us_schedule_year')
        for tr in soup.select('table tbody tr'):
            cells = tr.find_all('td', recursive=False)
            if len(cells) != 3:raise ValueError('us_schedule_row')
            dates = list(cells[0].stripped_strings)
            name = cells[1].select_one('strong')
            if len(dates) != 2 or name is None:raise ValueError('us_schedule_row')
            clean = re.sub(r'(\d)(?:st|nd|rd|th)', r'\1', dates[1]).replace('.', '')
            weekday, rest = clean.split(' ',1)
            day = datetime.strptime(rest+' '+year[1], '%b %d %Y')
            if day.strftime('%a') != weekday:raise ValueError('us_schedule_weekday')
            name = name.get_text(' ',strip=True)
            grade = re.search(r'\(Gr\. (I{1,3})\)', name)
            if grade:rows.append(record(day.date().isoformat(), 'DMR', name, next(cells[2].stripped_strings), 'G'+str(len(grade[1]))))
    elif url == GP:
        for section in soup.select('.stakes-box .single-item'):
            heading = section.select_one('h5')
            if not heading:continue
            day = datetime.strptime(heading.get_text(' ',strip=True), '%A, %b %d, %Y').date().isoformat()
            for span in section.select('.link-wrap > span'):
                text = span.get_text(' ',strip=True)
                match = re.fullmatch(r'(.+?) \((G[123])\), .+ - (\$[\d,]+)', text)
                if match:rows.append(record(day, 'GP', match[1], match[3], match[2]))
    elif re.fullmatch(r'https://www.churchilldowns.com/wp-content/uploads/sites/3/\d{4}/\d{2}/[A-Za-z0-9_.-]+\.pdf', url):
        with pdfplumber.open(BytesIO(raw)) as pdf:
            # 文件含印刷层重叠，只有完整可读的逐项日期/金额/级别段入库。
            texts = [p.extract_text(x_tolerance=1.5) or '' for p in pdf.pages]
        if not texts or any('CHURCHILL' not in text for text in texts):raise ValueError('us_schedule_track')
        pattern = r'(?m)^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), ([A-Za-z]+ \d{1,2}, \d{4})\s+(\$[\d,]+)\n(?:\(Includes [^\n]+\)\n)?THE ([^\n]+?) - Grade (I{1,3})\n'
        for text in texts:
            for match in re.finditer(pattern, text):
                day = datetime.strptime(match[2], '%B %d, %Y')
                if day.strftime('%A') != match[1]:raise ValueError('us_schedule_weekday')
                rows.append(record(day.date().isoformat(), 'CD', match[4], match[3], 'G'+str(len(match[5]))))
    else:raise ValueError('us_schedule_source')
    unique = {};conflicts=set()
    for row in rows:
        identity = (row['venue'],row['local_date'],race_name(row['race_name']))
        if identity in unique and unique[identity] != row:conflicts.add(identity)
        unique[identity] = row
    if conflicts:raise ScheduleConflict(conflicts,[row for identity,row in unique.items() if identity not in conflicts])
    if not unique:raise ValueError('us_schedule_empty')
    return list(unique.values())


def select_schedule(target, observations):
    matches = []
    for row in observations:
        if (row['source_class']=='official_operator' and row['venue']==target['venue']
            and race_name(row['race_name'])==race_name(target['race_name'])
            and row['local_date'][:4]==target['local_date'][:4] and row['local_date']!=target['local_date']):
            raise ValueError('us_schedule_date_conflict')
        if (row['venue'], row['local_date'], race_name(row['race_name'])) != (target['venue'], target['local_date'], race_name(target['race_name'])):continue
        if row.get('grade') and row['grade'] != target['grade']:raise ValueError('us_schedule_grade_conflict')
        matches.append(row)
    if not matches:return None
    matches.sort(key=lambda r:(r['source_class']=='official_operator', r['source']['fetched_at']), reverse=True)
    chosen = matches[0]
    peers = [r for r in matches if r['source_class']==chosen['source_class']]
    if len({r['prize_amount'] for r in peers}) != 1:raise ValueError('us_schedule_purse_conflict')
    return dict(chosen, race_name=target['race_name'], candidate_key=target['candidate_key'], prize_stage='announced',
                comparisons=[r for r in matches[1:] if r['prize_amount'] != chosen['prize_amount']])


def collect_schedules(store, targets, *, public_index=None):
    observations=[];checks=[];conflicts=set()
    def read(url, source_class):
        doc = public_index if url == USR and public_index is not None else store.get(url)
        try:rows = parse_schedule(doc['body'], url=url)
        except ScheduleConflict as exc:
            conflicts.update(exc.identities)
            rows=exc.valid_rows
        source = {k:doc[k] for k in ('url','sha256','fetched_at')}
        observations.extend(dict(row, source=source, source_class=source_class) for row in rows)
        store.accept(doc)
        checks.append(dict(source=source, status='checked'))
    if public_index is not None:
        try:read(USR,'trusted_publisher')
        except (ValueError,KeyError,TypeError,OSError) as exc:checks.append(dict(url=USR,status='check_failed',reason=str(exc)))
    venues = {t['venue'] for t in targets}
    for venue,url in [('BEL',NYRA),('DMR',DMR),('GP',GP)]:
        if venue not in venues:continue
        try:read(url,'official_operator')
        except (ValueError,KeyError,TypeError,OSError) as exc:checks.append(dict(url=url,status='check_failed',reason=str(exc)))
    if 'CD' in venues:
        try:
            doc = store.get(CD)
            links = {urljoin(CD,a['href']) for a in BeautifulSoup(doc['body'],'lxml').select('a[href]')
                     if a.get_text(' ',strip=True) == 'Fall Meet Stakes Schedule'}
            if len(links) != 1:raise ValueError('us_schedule_directory')
            read(links.pop(),'official_operator')
        except (ValueError,KeyError,TypeError,OSError) as exc:checks.append(dict(url=CD,status='check_failed',reason=str(exc)))
    selected={}
    for target in targets:
        if (target['venue'],target['local_date'],race_name(target['race_name'])) in conflicts:
            checks.append(dict(candidate_key=target['candidate_key'],status='conflict',reason='us_schedule_conflict'))
            continue
        try:selected[target['candidate_key']]=select_schedule(target,observations)
        except ValueError as exc:checks.append(dict(candidate_key=target['candidate_key'],status='conflict',reason=str(exc)))
    return selected,checks


def apply_schedule_locked(event, schedule, *, route, now):
    """调用方持有赛事事务锁；计划奖金不推进正式卡或赛果状态。"""
    from stable import models
    from .race_data_source_adapters import aware, canonical_sha, require_sha
    from .race_data_sync_pipeline import RaceDataSyncFlags
    from .race_data_sync_policy import arbitrate_source_value, normalize_source_class, source_priority
    flags=RaceDataSyncFlags.from_settings()
    if event.status!='scheduled' or not flags.allows(provider='us_racing',region='united_states',field_name='us_basic.prize'):return False
    target=(event.source_refs or {}).get('us_target_v1',{})
    if (schedule.get('prize_stage')!='announced' or schedule.get('prize_currency')!='USD'
        or any(schedule.get(k)!=target.get(k) for k in ('candidate_key','local_date','venue','race_name'))
        or not target.get('candidate_key') or target.get('local_date')!=str(event.local_date)):
        raise ValueError('us_schedule_target_drift')
    source=schedule['source'];require_sha(source['sha256']);observed=aware(source['fetched_at'])
    source_class=normalize_source_class(schedule['source_class'])
    if observed>now or not route.permits_url(source['url']) or source_class not in {'official_operator','trusted_publisher'}:
        raise ValueError('us_schedule_source_invalid')
    value=Decimal(amount('$'+schedule['prize_amount']))
    fields={'prize_amount':value,'prize_currency':'USD'};authorities={}
    for field,candidate in fields.items():
        authority=event.field_authorities.select_for_update().filter(subject_type='event',subject_key=str(event.pk),field_name=field).first()
        authorities[field]=authority
        decision=arbitrate_source_value(current_source_key=authority.source_key if authority else '',
            current_source_class=authority.source_class if authority else '',current_observed_at=authority.observed_at if authority else None,
            candidate_source_key='us_racing_schedule',candidate_source_class=source_class,candidate_observed_at=observed,
            has_current_value=getattr(event,field) not in (None,''),values_equal=getattr(event,field)==candidate,
            manual_locked=bool((event.manual_lock_flags or {}).get('basic') or (event.manual_lock_flags or {}).get(field) or authority and authority.manual_lock))
        if not decision.apply and decision.reason_code!='idempotent_replay':return False
    for field,candidate in fields.items():
        old=getattr(event,field);render=lambda v:str(v) if isinstance(v,Decimal) else v
        if old!=candidate:
            models.RaceEventFieldChange.objects.create(event=event,subject_type='event',subject_key=str(event.pk),field_name=field,
                old_value=render(old),new_value=render(candidate),applied=True,decision='applied',source_key='us_racing_schedule',
                source_url=source['url'],source_class=source_class,authority_level=source_priority(source_class),
                source_updated_at=observed,raw_sha256=source['sha256'],operation_mode='us_schedule')
        authority=authorities[field] or models.RaceEventFieldAuthority(event=event,subject_type='event',subject_key=str(event.pk),field_name=field)
        authority.source_key='us_racing_schedule';authority.source_class=source_class;authority.source_url=source['url']
        authority.external_id=target['candidate_key'];authority.observed_at=observed
        authority.authority_level=source_priority(source_class);authority.value_sha256=canonical_sha(render(candidate));authority.save()
        setattr(event,field,candidate)
    event.source_refs={**(event.source_refs or {}),'us_pre_race_schedule':schedule}
    event.save(update_fields=['prize_amount','prize_currency','source_refs','updated_at'])

    return True
