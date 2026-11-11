"""NSA 条件册和官方结果 PDF；不把未提供的逐匹字段合成出来。"""
from datetime import datetime
from collections import Counter
import re

from .us_racing_sources import pdf_pages, candidate, evidence, catalogue

VENUES = {
    'FOXFIELD': 'Foxfield',
    'FAR HILLS': 'Far Hills',
    'INTERNATIONAL GOLD CUP': 'International Gold Cup',
    'MONTPELIER': 'Montpelier',
    'COLONIAL CUP': 'Camden',
}
STATUSES = {
    'PU': 'pulled_up', 'F': 'fell', 'LR': 'unseated_rider',
    'UR': 'unseated_rider', 'DQ': 'disqualified', 'BD': 'brought_down',
    'RO': 'ran_out', 'DNF': 'did_not_finish',
}


def parse_conditions(raw, *, url):
    rows = []
    meeting = None
    for page in pdf_pages(raw):
        content = page['text']
        day = re.search(r'(?m)^(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY), ([A-Z]+ \d{1,2}, \d{4})$', content)
        if day:
            heading = content[:day.start()]
            venues = [name for token, name in VENUES.items() if token in heading]
            meeting = dict(local_date=datetime.strptime(day[1].title(), '%B %d, %Y').date().isoformat(),
                           venue=venues[0] if len(venues)==1 else '')
        for match in re.finditer(r'(?m)^([A-Z /]+) RACE (\d+)\n(?:THE )?([^\n]+?) \((?:Grade|Gr\.) ([123])\)', content):
            if not meeting or not meeting['venue']:
                raise ValueError('us_nsa_meeting_unrecognized')
            rows.append(candidate('nsa', **meeting, race_name=match[3], source_race_id=match[2],
                grade='G'+match[4], timezone='America/New_York', race_kind='hurdle',
                source_page=page['number'], **evidence(raw,url)))
    if not rows:
        raise ValueError('us_nsa_graded_calendar_empty')
    return catalogue(rows)


def _lines(words):
    lines = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if not lines or abs(word['top'] - lines[-1][0]['top']) > 2:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda w: w['x0']) for line in lines]


def _race_headers(content, day, venue, raw, url, counts):
    sections = re.split(r'(?m)^(\d+(?:st|nd|rd|th) Race \(#\d+\)\.)', content)
    records = {}
    for i in range(1, len(sections), 2):
        number = re.search(r'#(\d+)', sections[i])[1]
        ordinal = re.match(r'\d+', sections[i])[0]
        body = sections[i+1]
        header = re.split(r'(?m)^(?:\d{2}|PU|F|LR|UR|DQ|BD|RO|DNF) ', body)[0]
        grade = re.search(r'(.+?) \((?:Grade |G)([123])\)', ' '.join(header.split()))
        # Stakes names can contain periods (William H. Allison); grade is the reliable delimiter.
        if grade:
            name = re.sub(r'^\$[\d,]+\.\s*(?:The )?', '', grade[1])
        else:
            name = re.sub(r'^\s*\$[\d,]+\.\s*(?:The )?', '', ' '.join(header.split())).split('. ')[0]
        end = re.search(r'WINNING MARGIN:\s*(.*?)\s+TIME:\s*(.*?)\s+TURF:\s*([^\n]+)', body)
        if not name or not end:
            raise ValueError('us_nsa_result_truncated')
        if ordinal in records:
            raise ValueError('us_nsa_duplicate_race')
        records[ordinal] = candidate('nsa', venue=venue, local_date=day, race_name=name,
            source_race_id=f'{number}:{ordinal}' if counts[number]>1 else number,
            book_race_id=number, grade='G'+grade[2] if grade else '', race_number=ordinal,
            timezone='America/New_York', race_time_raw=end[2], winning_margin_raw=end[1],
            going=end[3], runners=[], production_complete=False,
            gaps=['runner_odds','runner_margins','program_numbers','independent_roster_count'],
            **evidence(raw,url))
    return records


def parse_results(raw, *, url, graded_only=False):
    records = {}
    excluded = []
    last_number = None
    meeting = None
    pages = pdf_pages(raw)
    counts = Counter(re.findall(r'\d+(?:st|nd|rd|th) Race \(#(\d+)\)', '\n'.join(p['text'] for p in pages)))
    for page in pages:
        content = page['text']
        header = re.search(r'Race Results Report\n([^\n]+)\n[^\n]+\n([A-Za-z]+, [A-Za-z]+, \d{1,2}, \d{4})', content)
        if not header:
            raise ValueError('us_nsa_result_header')
        day = datetime.strptime(header[2], '%A, %B, %d, %Y').date().isoformat()
        venue = {'Foxfield Fall':'Foxfield'}.get(header[1],header[1])
        current_meeting = (day, venue)
        if meeting is not None and current_meeting != meeting:
            raise ValueError('us_nsa_result_date_conflict')
        meeting = current_meeting
        page_records = _race_headers(content, day, venue, raw, url, counts)
        if graded_only:
            excluded.extend(dict(race_number=r['race_number'], race_name=r['race_name'], local_date=r['local_date'])
                            for r in page_records.values() if not r['grade'])
            page_records = {k:r for k,r in page_records.items() if r['grade'] in {'G1','G2','G3'}}
        if records.keys() & page_records.keys():
            raise ValueError('us_nsa_duplicate_race')
        records.update(page_records)
        lines = _lines(page['words'])
        cols = next((line for line in lines if [w['text'] for w in line] ==
                     ['ORD','HORSE','WGT','RIDER','OWNER','TRAINER','PURSE']), None)
        if cols is None:
            raise ValueError('us_nsa_result_columns')
        bounds = [cols[1]['x0']-1, cols[2]['x0']-1, cols[3]['x0']-2,
                  cols[4]['x0']-2, cols[5]['x0']-6, cols[6]['x0']-2]
        for line in lines:
            raw_line = ' '.join(w['text'] for w in line)
            race_header = re.match(r'(\d+)(?:st|nd|rd|th) Race \(#\d+\)', raw_line)
            if race_header:
                last_number = race_header[1]
                continue
            if not last_number or last_number not in records or line[0]['x0'] >= bounds[0]:
                continue
            # The left ORD cell and numeric WGT cell identify a result row, including unknown statuses.
            def cell(left, right):
                return ' '.join(w['text'] for w in line if left <= w['x0'] < right)
            weight = cell(bounds[1], bounds[2]).lstrip('*')
            if not re.fullmatch(r'\d{3}', weight):
                continue
            ordinal = cell(0, bounds[0])
            if re.fullmatch(r'\d{2}', ordinal) and int(ordinal)>0:
                status, position = 'finished', int(ordinal)
            elif ordinal in STATUSES:
                status, position = STATUSES[ordinal], None
            else:
                raise ValueError('us_nsa_unknown_status')
            horse = re.sub(r'\s*\(L\)', '', cell(bounds[0], bounds[1])).strip()
            jockey = cell(bounds[2], bounds[3])
            trainer = cell(bounds[4], bounds[5])
            if not horse or not jockey or not trainer:
                raise ValueError('us_nsa_result_row')
            records[last_number]['runners'].append(dict(horse_name=horse, horse_number='', barrier='',
                carried_weight=weight+' lb', jockey_name=jockey, trainer_name=trainer,
                status=status, raw_status=ordinal, finish_position=position,
                finish_time='', margin='', odds_value='', source_page=page['number']))
    for race in records.values():
        rows = race['runners']
        if not rows or len({r['horse_name'] for r in rows}) != len(rows):
            raise ValueError('us_nsa_roster')
        positions = [r['finish_position'] for r in rows if r['finish_position']]
        if not positions or positions != sorted(positions) or positions[0] != 1:
            raise ValueError('us_nsa_result_order')
    if not records and not graded_only:
        raise ValueError('us_nsa_results_empty')
    result = catalogue(list(records.values()))
    if graded_only:
        result['excluded_non_graded_races'] = excluded
    return result
