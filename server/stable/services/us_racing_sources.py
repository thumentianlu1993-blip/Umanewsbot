"""美国公开来源的纯解析；候选证据不授予生产身份或网络权限。"""
from datetime import date, datetime
import hashlib
import json
from io import BytesIO
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


def text(node):
    return node.get_text(' ', strip=True) if node else ''


def name_key(value):
    """只做可解释的赛名缩写处理，不模糊匹配、不授予生产身份。"""
    value = re.sub(r'\s*\((?:Grade|Gr\.|G)\s*[IVX123]+\)\s*$', '', value, flags=re.I)
    value = re.sub(r'\bS\.\s*$', 'STAKES', value, flags=re.I)
    return re.sub(r'\s+', ' ', value).strip().casefold()


def evidence(raw, url):
    value = raw if isinstance(raw, bytes) else str(raw).encode()
    return dict(source_url=url, raw_sha256=hashlib.sha256(value).hexdigest())


def candidate(provider, *, venue, local_date, race_name, year=None, source_race_id='', **fields):
    key = [provider, local_date or str(year), venue, source_race_id or name_key(race_name)]
    if local_date is None:
        key.append('not_run')
    return dict(provider=provider, venue=venue, local_date=local_date, race_name=race_name,
        source_race_id=source_race_id,
        candidate_key=hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest(), **fields)


def catalogue(rows):
    groups = {}
    for row in rows:
        values = groups.setdefault(row['candidate_key'], [])
        if row not in values:
            values.append(row)
    conflicts = [dict(candidate_key=k, reason='source_conflict', evidence=v) for k,v in groups.items() if len(v)>1]
    items = [v[0] for v in groups.values() if len(v)==1 and v[0]['local_date']]
    by_name = {}
    for row in items:
        k = (row['provider'], row['venue'], row['local_date'], name_key(row['race_name']))
        by_name.setdefault(k, []).append(row)
    conflicts += [dict(reason='same_name_multiple_occurrences', evidence=values)
                  for values in by_name.values() if len(values)>1]
    return dict(items=items,
        unresolved=[v[0] for v in groups.values() if len(v)==1 and not v[0]['local_date']],
        conflicts=conflicts, production_identity_granted=False)


def parse_toba_calendar(raw, *, url):
    parsed = urlsplit(url)
    year = re.fullmatch(r'/graded-stakes/(\d{4})-races/', parsed.path)
    if not year or parsed.scheme != 'https' or parsed.netloc != 'toba.org' or parsed.query or parsed.fragment:
        raise ValueError('us_calendar_url')
    soup = _html(raw)
    tables = [t for t in soup.select('table') if [text(c) for c in t.select('thead th')] ==
              ['Track','Date','Division','Stake','Gr','Age','Sex','Dis','Sur','Field','Total Purse','Winner']]
    if len(tables) != 1:
        raise ValueError('us_calendar_headers')
    rows = []
    for tr in tables[0].select('tbody tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 12:
            raise ValueError('us_calendar_row')
        values = [text(c) for c in cells]
        if not values[0] or not values[3]:
            raise ValueError('us_calendar_identity')
        if values[1].lower() == 'not run':
            day = None
        else:
            try:
                day = datetime.strptime(values[1], '%d-%b-%y').date()
            except ValueError:
                raise ValueError('us_calendar_date') from None
            if day.year != int(year[1]):
                raise ValueError('us_calendar_year')
        grade = 'G' + values[4] if values[4] in {'1','2','3'} else values[4]
        links = sorted({urljoin(url,a['href']) for a in tr.select('a[href]')})
        ids = set()
        for link in links:
            parsed_link = urlsplit(link)
            if parsed_link.hostname != 'www.equibase.com':
                continue
            q = parse_qs(parsed_link.query)
            if (q.get('TID') == [values[0]] and q.get('CTRY') == ['USA'] and day
                    and q.get('DT') == [day.strftime('%m/%d/%Y')]):
                ids.update(n for n in q.get('RACE', []) if n.isdigit())
        if len(ids)>1:
            raise ValueError('us_calendar_number_ambiguous')
        rows.append(candidate('toba', venue=values[0], local_date=day.isoformat() if day else None,
            source_race_id=next(iter(ids), ''),
            year=int(year[1]), race_name=values[3], grade=grade, division_raw=values[2],
            age_condition=values[5], sex_condition=values[6], distance_raw=values[7],
            surface_raw=values[8], field_size_raw=values[9], purse_raw=values[10],
            winner=values[11], reference_urls=links,
            **evidence(raw,url)))
    if not rows:
        raise ValueError('us_calendar_empty')
    return catalogue(rows)


def _html(raw):
    value = raw.decode('utf-8-sig') if isinstance(raw, bytes) else str(raw)
    if not value.rstrip().lower().endswith('</html>'):
        raise ValueError('us_document_truncated')
    return BeautifulSoup(value, 'lxml')


def _del_mar_context(event):
    if (event is None or event.racecourse not in {'Del Mar', '德尔马'}
            or event.timezone_name != 'America/Los_Angeles'):
        raise ValueError('us_event_context_mismatch')


def parse_del_mar_card(raw, *, url, event):
    _del_mar_context(event)
    p = urlsplit(url)
    expected_path = '/racing/entries/' + event.local_date.isoformat()
    if (p.scheme != 'https' or p.netloc != 'www.dmtc.com'
            or p.path != expected_path or p.query or p.fragment):
        raise ValueError('us_card_url_mismatch')
    soup = _html(raw)
    heading = text(soup.select_one('h2.month-year'))
    heading = re.sub(r'(\d)(?:st|nd|rd|th)\b', r'\1', heading)
    try:
        source_day = datetime.strptime(heading, '%A, %B %d %Y').date()
    except ValueError:
        raise ValueError('us_card_date_missing') from None
    if source_day != event.local_date:
        raise ValueError('us_card_date_mismatch')
    if not soup.select('div.race-container') and 'There are currently no Entries available for this date.' in text(soup):
        return dict(stage='not_published', source_stage='not_published', items=[],
            local_date=source_day.isoformat(), venue='Del Mar', race_name=event.original_name,
            roster_complete=False, gaps=['entries_not_published'])
    names = {name_key(n) for n in (event.original_name, event.chinese_name) if n}
    races = [r for r in soup.select('div.race-container')
             if name_key(text(r.select_one('[title="Race Conditions"] .text-success'))) in names]
    if len(races) != 1:
        raise ValueError('us_card_ambiguous' if races else 'us_race_not_found')
    race = races[0]
    race_id = re.fullmatch(r'race-container-([1-9]\d*)', race.get('id', ''))
    if not race_id:
        raise ValueError('us_race_number_missing')
    headers = [text(h) for h in race.select('thead tr:first-child th')]
    if headers != ['PGM#', 'PP', 'RUNNER', 'RUNNER', 'JOCKEY', 'TRAINER', 'E/M', 'WGT', 'M/L']:
        raise ValueError('us_card_headers')
    rows = []
    for tr in race.select('tbody tr'):
        if 'visible-xs' in tr.get('class', []):
            continue
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 9:
            raise ValueError('us_card_row')
        number = text(cells[0])
        scratched = number == 'SCR'
        silk = cells[0].select_one('.silk')
        silk_ids = [m[1] for c in (silk.get('class', []) if silk else [])
                    if (m := re.fullmatch(r'silk([1-9]\d*)', c))]
        # SCR replaces the visible number; the same program silk identifier remains.
        if len(silk_ids) != 1 or (not scratched and number != silk_ids[0]):
            raise ValueError('us_program_number_unverified')
        number = silk_ids[0]
        horse = text(cells[2].select_one('strong'))
        barrier, jockey, trainer, weight, odds = (text(cells[i]) for i in (1, 4, 5, 7, 8))
        if (not horse or not trainer or not re.fullmatch(r'\d{2,3}', weight)
                or not (barrier.isdigit() or scratched and barrier == '-')
                or not (odds == '-' or re.fullmatch(r'\d+/\d+', odds))):
            raise ValueError('us_card_row')
        rows.append(dict(horse_name=horse, horse_number=number, barrier='' if barrier == '-' else barrier,
            jockey_name='' if jockey == '-' else jockey, trainer_name=trainer,
            carried_weight=weight + ' lb', running_status='non_runner' if scratched else 'declared',
            odds_value='' if odds == '-' else odds, odds_kind='morning_line', odds_format='fractional',
            source_refs=dict(primary=url, field_units={'carried_weight': 'lb'},
                program_number_source='silk_class' if scratched else 'PGM',
                barrier_kind='current_post_position')))
    numbers = [r['horse_number'] for r in rows]
    if (not rows or len(set(numbers)) != len(numbers)
            or len({r['horse_name'] for r in rows}) != len(rows)
            or sorted(map(int, numbers)) != list(range(1, len(rows) + 1))):
        raise ValueError('us_card_roster')
    conditions = text(race.select_one('[title="Race Conditions"] .text-muted-dark'))
    clock = re.search(r'POST TIME:\s*(\d{1,2}:\d{2}[AP]M)\b', conditions)
    if not clock:
        raise ValueError('us_card_time_missing')
    off = datetime.combine(source_day, datetime.strptime(clock[1], '%I:%M%p').time(),
                           ZoneInfo('America/Los_Angeles'))
    program_path = '/data/pdf/racing/programs/' + source_day.strftime('%Y%m%d') + '.pdf'
    programs = [urljoin(url, a['href']) for a in soup.select('a[href]')
                if text(a) == 'Program' and urljoin(url, a['href']) == 'https://www.dmtc.com' + program_path]
    provisional = 'programs for this race are not finalized' in text(race).lower()
    return dict(stage='numbered', source_stage='final_card' if programs and not provisional else 'provisional_card',
        local_date=source_day.isoformat(), venue='Del Mar', venue_key='DMR',
        race_name=text(race.select_one('[title="Race Conditions"] .text-success')),
        race_number=race_id[1], external_race_id=f'DMR:{source_day:%Y%m%d}:{race_id[1]}',
        off_time=off.isoformat(), timezone='America/Los_Angeles', conditions_raw=conditions,
        items=rows, program_url=programs[0] if programs else '',
        # No independent declared count in the HTML: do not certify production completeness.
        roster_complete=False, gaps=['independent_roster_count'])


def discover_del_mar_url(*, event, route, now, fetcher):
    _del_mar_context(event)
    url = 'https://www.dmtc.com/racing/entries/' + event.local_date.isoformat()
    if not route.permits_url(url):
        raise ValueError('source_url_rejected')
    parse_del_mar_card(fetcher(url, route=route, now=now), url=url, event=event)
    return url


def del_mar_observation(raw, *, url, route, now, event):
    if not route.permits_url(url) or route.timezone != 'America/Los_Angeles':
        raise ValueError('source_url_rejected')
    payload = parse_del_mar_card(raw, url=url, event=event)
    if payload['source_stage'] != 'final_card':
        raise ValueError('us_card_not_final')
    venues = [k for k, names in route.venue_aliases.items() if payload['venue'] in names]
    if len(venues) != 1:
        raise ValueError('venue_unreviewed')
    rows = [dict(external_runner_id='number:' + r['horse_number'], horse_name=r['horse_name'],
        number=r['horse_number'], barrier=r['barrier'], jockey_name=r['jockey_name'],
        trainer_name=r['trainer_name'], carried_weight=r['carried_weight'], status=r['running_status'],
        raw_status='SCR' if r['running_status'] == 'non_runner' else '',
        odds_value=r['odds_value'], reported_finish_position=None, finish_time='', margin='',
        field_provenance=r['source_refs']) for r in payload['items']]
    return dict(provider=route.provider, region=route.region, identity_namespace=route.identity_namespace,
        external_race_id=payload['external_race_id'], canonical_url=url,
        fetched_at=(getattr(raw, 'observed_at', None) or now).isoformat(),
        raw_sha256=getattr(raw, 'raw_sha256', hashlib.sha256(str(raw).encode()).hexdigest()),
        parser_version=route.parser_version, operator=route.operator, venue_key=venues[0],
        local_date=payload['local_date'], timezone=route.timezone, meeting_session='single',
        race_number=payload['race_number'], raw_names=[payload['race_name']], roster=rows,
        off_time=payload['off_time'], result_phase='', roster_complete=False, gaps=payload['gaps'])


def pdf_pages(raw):
    import pdfplumber
    if not isinstance(raw, bytes) or not raw.startswith(b'%PDF-'):
        raise ValueError('us_pdf_required')
    from pdfplumber.utils.exceptions import PdfminerException
    try:
        with pdfplumber.open(BytesIO(raw)) as document:
            if not 1 <= len(document.pages) <= 64:
                raise ValueError('us_pdf_page_limit')
            return [dict(number=i, text=p.extract_text(x_tolerance=1) or '',
                         words=p.extract_words(x_tolerance=1, use_text_flow=True))
                    for i,p in enumerate(document.pages,1)]
    except PdfminerException:
        raise ValueError('us_pdf_invalid') from None


def parse_del_mar_nominations(raw, *, url, event):
    _del_mar_context(event)
    pages = pdf_pages(raw)
    content = '\n'.join(p['text'] for p in pages)
    first_name = content.splitlines()[0]
    day_match = re.search(r'TO BE RUN ([A-Z]+, [A-Z]+ \d{1,2}, \d{4})', content)
    count = re.search(r'WITH (\d+) NOMINATIONS', content)
    if not day_match or not count:
        raise ValueError('us_nomination_headers')
    day = datetime.strptime(day_match[1].title(), '%A, %B %d, %Y').date()
    if day != event.local_date or name_key(first_name) != name_key(event.original_name):
        raise ValueError('us_nomination_identity')
    grade_match = re.search(r'\(Grade (I{1,3})\)', content)
    rows = []
    table = content.split('Horse Owner Trainer', 1)
    if len(table) != 2:
        raise ValueError('us_nomination_headers')
    body = table[1].split('CLOSED ', 1)
    if len(body) != 2:
        raise ValueError('us_nomination_truncated')
    for line in body[0].strip().splitlines():
        # This source packs colour, sex and age into a dot-delimited cell.
        row = re.fullmatch(r'(.+?)\s+((?:b|ch|gr/ro|gr|dk b/)[./]*[bcfghmr]\.(\d+))\s+(.+)', line)
        if not row:
            raise ValueError('us_nomination_row')
        rows.append(dict(horse_name=row[1], horse_number='', barrier='', jockey_name='', trainer_name='',
            carried_weight='', age=int(row[3]), description_raw=row[2], owner_trainer_raw=row[4],
            running_status='nominated', source_refs={'primary':url}))
    if len(rows) != int(count[1]) or len({r['horse_name'] for r in rows}) != len(rows):
        raise ValueError('us_nomination_count')
    return dict(stage='registration', source_stage='nominations', local_date=day.isoformat(),
        venue='DMR', race_name=first_name, grade='G'+str(len(grade_match[1])) if grade_match else '',
        items=rows, production_complete=False, gaps=['structured_trainer'], **evidence(raw,url))


def parse_del_mar_changes(raw, *, url, event):
    _del_mar_context(event)
    soup = _html(raw)
    title = next((text(h) for h in soup.select('h1') if text(h).startswith('Del Mar Changes for ')), '')
    expected = event.local_date.strftime('%A, %B ') + str(event.local_date.day)
    title = re.sub(r'(\d)(?:st|nd|rd|th)\b', r'\1', title)
    if title != 'Del Mar Changes for ' + expected:
        raise ValueError('us_changes_date_mismatch')
    rows = []
    for box in soup.select('#main-content .panel'):
        heading = re.fullmatch(r'Race ([1-9]\d*)', text(box.select_one('h3')))
        body = box.select_one('.panel-body')
        if not heading or body is None:
            raise ValueError('us_changes_headers')
        # br is the source's row delimiter; nested bold text stays on the same row.
        for br in body.select('br'):
            br.replace_with('\n')
        lines = [' '.join(s.split()) for s in body.get_text().splitlines() if s.strip()]
        changes = []
        going = ''
        unparsed = []
        for line in lines:
            status = re.fullmatch(r'#\s*(\d+)\s+(.+?)\s+Scratch Reason\s*-\s*(.+)', line)
            weight = re.fullmatch(r'#\s*(\d+)\s+(.+?)\s+Weight Carried\s*-\s*(\d+) lbs changed to (\d+) lbs', line)
            surface = re.fullmatch(r'Current (?:Dirt|Turf) Track Condition:\s*(.+)', line)
            if status:
                changes.append(dict(kind='scratch', horse_number=status[1], horse_name=status[2], reason=status[3]))
            elif weight:
                changes.append(dict(kind='weight', horse_number=weight[1], horse_name=weight[2],
                    old_weight=weight[3]+' lb', new_weight=weight[4]+' lb'))
            elif surface:
                going = surface[1]
            elif not line.startswith('Scratch -'):
                unparsed.append(line)
        rows.append(dict(race_number=heading[1], changes=changes, going=going, other_changes_raw=unparsed))
    if not rows or len({r['race_number'] for r in rows}) != len(rows):
        raise ValueError('us_changes_empty_or_duplicate')
    return dict(local_date=event.local_date.isoformat(), items=rows, production_complete=False,
        gaps=['source_year_missing'], year_evidence='request_context_only',
        source_heading=text(soup.select_one('h2.bigger')), **evidence(raw,url))


def reconcile_sources(documents):
    """跨源报告关联只发现冲突，不自动修改清单或产生强身份。"""
    groups = {}
    for doc in documents:
        rows = [doc] if doc.get('stage') == 'registration' else doc.get('items', [])
        for row in rows:
            if not row.get('local_date') or not row.get('grade'):
                continue
            k = (row['local_date'], row['venue'], name_key(row['race_name']))
            groups.setdefault(k, []).append(row)
    return dict(conflicts=[dict(reason='grade_conflict', evidence=rows)
        for rows in groups.values() if len({r['grade'] for r in rows})>1],
        production_identity_granted=False)


def parse_document(provider, kind, raw, *, url, event=None):
    """采集命令入口；没有经过样例验证的格式必须明确拒绝。"""
    if (provider, kind) == ('del_mar', 'card'):
        return parse_del_mar_card(raw, url=url, event=event)
    if (provider, kind) == ('toba', 'calendar'):
        return parse_toba_calendar(raw, url=url)
    if (provider, kind) == ('del_mar', 'nominations'):
        return parse_del_mar_nominations(raw, url=url, event=event)
    if (provider, kind) == ('del_mar', 'changes'):
        return parse_del_mar_changes(raw, url=url, event=event)
    if (provider, kind) == ('us', 'reconcile'):
        return reconcile_sources(raw)
    if provider == 'nsa' and kind in {'calendar', 'result'}:
        from .us_nsa_sources import parse_conditions, parse_results
        return (parse_conditions if kind=='calendar' else parse_results)(raw, url=url)
    raise ValueError('us_source_format_unsupported')
