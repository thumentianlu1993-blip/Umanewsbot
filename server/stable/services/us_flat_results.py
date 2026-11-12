"""美国平地全场赛果；DRF 物理冲线与裁定名次分离，补源必须整场一致。"""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import pdfplumber

from .us_venues import VENUES

ORDINALS = ('FIRST SECOND THIRD FOURTH FIFTH SIXTH SEVENTH EIGHTH NINTH TENTH '
            'ELEVENTH TWELFTH THIRTEENTH FOURTEENTH FIFTEENTH SIXTEENTH').split()
GLYPHS = str.maketrans('¥¦§¨©ª«¬¤®', '0123456789')
# 报纸栏宽造成的缩写，逐项在同一 chart 的赛后叙述中确认全名。
NAME_ALIASES = {'primtimemmy': 'primetimeemmy', 'comanchebrve': 'comanchebrave',
    'cantodellaterr': 'cantodellaterra', 'laterthnplnned': 'laterthanplanned',
    'crossovercapitl': 'crossovercapital', 'expensivequen': 'expensivequeen',
    'kensingtonlne': 'kensingtonlane', 'cortndamprzzo': 'cortinadamprezzo',
    'fllmoontonght': 'fullmoontonight', 'scommesssicur': 'scommessasicura',
    'stickupwithoutgun': 'stickupwithoutagun', 'benvenutocllini': 'benvenutocellini',
    'lerntodiscover': 'learntodiscover', 'takechargestr': 'takechargestar',
    'programtrding': 'programtrading', 'fvoritememory': 'favoritememory',
    'opulentrestrint': 'opulentrestraint', 'victoriousdrem': 'victoriousdream',
    'dimondnecklce': 'diamondnecklace', 'zabeelchmpion': 'zabeelchampion',
    'scorpionsrevng': 'scorpionsrevenge', 'twopsteight': 'twopasteight'}


def key(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower())


def horse_key(value):
    value = re.sub(r'(?:\s*\((?:IRE|GB|FR|CHI|ARG|AUS|NZ|CAN|USA|JPN|GER|BRZ|PER|SAF)\)|-(?:Ire|GB|Fr|Chi|Arg|Aus|NZ|Can|USA|Jpn|Ger|Brz|Per|SAf))$', '', value, flags=re.I)
    value = key(value.lstrip('ëí'))
    return NAME_ALIASES.get(value, value)


def margin(raw):
    if not raw:
        return None
    if raw in {'Ç', 'É', 'ó'}:
        return {'Ç': 'head', 'É': 'neck', 'ó': 'nose'}[raw]
    value = raw.translate(GLYPHS)
    for symbol, fraction in [('ô', '1/2'), ('õ', '1/4'), ('ö', '3/4')]:
        if value.endswith(symbol):
            whole = value[:-1]
            if whole and not re.fullmatch(r'[0-9]+', whole):
                raise ValueError('us_chart_margin')
            return (whole + ' ' if whole else '') + fraction
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('us_chart_margin')
    return value


def correction_marker(text):
    markers=re.findall(r'^\s*((?:CORRECTED|REVISED) CHART)\s*$',text,re.I|re.M)
    return markers[0] if markers else ''


def parse_chart(raw, identity):
    """只接收来源目录确定的身份；返回表格物理顺序，不以 PP 当马号。"""
    try:
        with pdfplumber.open(BytesIO(raw)) as pdf:
            if not 1 <= len(pdf.pages) <= 2:
                raise ValueError('us_chart_page_count')
            result = _chart_page(pdf.pages[-1], identity)
            def signature(rows):
                return [(horse_key(r['chart_name']), r['finish_position'], r['weight_lbs'], r['post_position'], r['odds_net'], r['margin_raw']) for r in rows]
            if any(signature(_chart_page(p, identity, table_only=True)) != signature(result['runners']) for p in pdf.pages[:-1]):
                raise ValueError('us_chart_repeated_page_mismatch')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('us_chart_pdf_invalid') from exc
    return result


def _chart_page(page, identity, table_only=False):
    lines = page.extract_text_lines(x_tolerance=1.5)
    text = '\n'.join(l['text'] for l in lines)
    compact = re.sub(r'\s+', '', text)
    day = datetime.strptime(identity['date'], '%Y-%m-%d')
    stamp = day.strftime('%B').upper() + str(day.day) + ',' + str(day.year)
    race_number = identity['race_number']
    if (stamp not in compact or not 1 <= race_number <= len(ORDINALS)
            or ORDINALS[race_number-1]+'RACE' not in compact
            or key(VENUES[identity['track']][1]) not in key(text.split('Value')[0])):
        raise ValueError('us_chart_identity_mismatch')
    headers = [l for l in lines if all(w in l['text'] for w in ('Horse', 'Jockey', 'M/Eqt', 'Fin'))]
    if len(headers) != 1:
        raise ValueError('us_chart_header')
    h = headers[0]
    chars = sorted(h['chars'], key=lambda c: c['x0'])
    heading = ''.join(c['text'] for c in chars)
    def pos(word):
        return chars[heading.index(word)]['x0']
    stop = next((l for l in lines if l['top'] > h['top'] and re.match(r'OFF\s*AT', l['text'])), None)
    if stop is None:
        raise ValueError('us_chart_footer')
    rows = []
    for line in lines:
        if not h['bottom'] < line['top'] < stop['top']:
            continue
        if re.match(r'[ëíÍ]\s*-', line['text']):
            continue
        cs = sorted(line['chars'], key=lambda c: c['x0'])
        def value(a, b):
            return ''.join(c['text'] for c in cs if a-.3 <= c['x0'] < b-.3).strip()
        name = value(pos('Horse'), pos('M/Eqt.'))
        # 文字提取可能没有空格，按各个标题位置分别切数值。
        age = value(pos('A.'), pos('Wt'))
        weight = value(pos('Wt'), pos('PP'))
        post_end = next(c['x0'] for c in chars[heading.index('PP')+2:] if c['text'].strip())
        post = value(pos('PP'), post_end)
        ending = value(pos('Fin'), pos('Odds'))
        match = re.fullmatch(r'([0-9]+|>)([¥¦§¨©ª«¬¤®ôõöÇÉó]*)(.*)', ending)
        odds = value(pos('Odds'), page.width).rstrip('*').lstrip('Í')
        if (not name or not match or not match[3].strip()
                or not re.fullmatch(r'\d+', age) or not re.fullmatch(r'\d{3}', weight)
                or not re.fullmatch(r'\d+', post) or not re.fullmatch(r'\d+\.\d{2}', odds)):
            raise ValueError('us_chart_runner:' + line['text'])
        finish = None if match[1] == '>' else int(match[1])
        rows.append(dict(chart_name=name.lstrip('ëí'), finish_position=finish, placing=finish,
            demotion_marker=name.startswith('ë'), demoted=False, dead_heat=name.startswith('í'), status='did_not_finish' if finish is None else 'finished',
            age=int(age), weight_lbs=int(weight), post_position=int(post), jockey_raw=match[3].strip(),
            odds_net=odds, margin_raw=match[2], margin_to_next=margin(match[2])))
    if not rows or len({horse_key(r['chart_name']) for r in rows}) != len(rows):
        raise ValueError('us_chart_roster')
    for row in rows:
        base = key(re.sub(r'-[A-Za-z]{2,3}$', '', row['chart_name']))
        if not table_only and base in NAME_ALIASES and NAME_ALIASES[base] not in key(text):
            raise ValueError('us_chart_abbreviation_unverified')
    if table_only:
        return rows
    notes = re.findall(r'ë\s*-\s*(.*?)\s+disqualified\s+and\s+placed\s+(\d+)(?:st|nd|rd|th)', text)
    for name, placing in notes:
        matches = [r for r in rows if horse_key(r['chart_name']) == horse_key(name)]
        if len(matches) != 1 or matches[0]['finish_position'] is None:
            raise ValueError('us_chart_demotion_identity')
        row = matches[0]; old, new = row['finish_position'], int(placing)
        if not old < new <= len(rows) or any(r['dead_heat'] for r in rows):
            raise ValueError('us_chart_demotion_order')
        for other in rows:
            if other['placing'] is not None and old < other['placing'] <= new:
                other['placing'] -= 1
        row.update(placing=new, demoted=True)
    if sum(r['demotion_marker'] for r in rows) != len(notes):
        raise ValueError('us_chart_unknown_demotion')
    trainers = re.search(r'Trainers\s*-\s*(.*?)(?=\nScratched\s*-|\n\$|\n\d+\s*CENT|\Z)', text, re.S)
    if not trainers:
        raise ValueError('us_chart_trainers')
    found = re.findall(r'(?:^|;)\s*(\d+)\s*,\s*(.*?)(?=;|$)', trainers[1].replace('\n', ' '))
    if [int(n) for n, _ in found] != list(range(1, len(rows)+1)):
        raise ValueError('us_chart_trainer_count')
    for row, (_, name) in zip(rows, found):
        row['trainer_raw'] = name.strip()
    timing = re.search(r'TIME\s*.*?\(([^)]+)\)', text, re.S)
    splits = re.findall(r'(?:\d+)?:\d{2}\.\d{2}', timing[1]) if timing else []
    if not splits:
        raise ValueError('us_chart_time')
    scratches = []
    scratch = re.search(r'Scratched\s*-\s*(.*?)(?=\n\$|\n\d+\s*CENT|\Z)', text, re.S)
    if scratch:
        # 每条以最近一场日期括号收尾；国家后缀括号留在名字里。
        clean = re.sub(r'\(\s*\d{1,2}[A-Za-z]{3}\d{2}[^)]*\)', '|', scratch[1].replace('\n', ' '))
        scratches = [n.strip() for n in re.split(r'[|,]', clean) if n.strip()]
        if any(re.search(r'\d{2}[A-Za-z]{3}', n) for n in scratches):
            raise ValueError('us_chart_scratches')
    footer = text[text.index(stop['text']):].split('TIME', 1)[0]
    ground = re.search(r'(?:Course|Track)\s+([A-Za-z -]+)(\s*\(Sealed\))?\.', footer, re.I)
    off = re.search(r'OFF\s*AT\s*(\d{1,2}:\d{2}(?::\d{2})?)(?=\s|Start)', footer)
    return dict(local_date=identity['date'], track=identity['track'], race_number=race_number,
                winning_time=splits[-1], fractional_times=splits[:-1], runners=rows, scratches=scratches,
                going=ground[1].strip().lower() if ground else '',
                going_raw=(ground[1] + (ground[2] or '')).strip() if ground else '',
                off_time_raw=off[1] if off else '',
                margin_semantics='lengths_ahead_of_next_physical_finisher', demotion_notes=notes,
                correction_marker=correction_marker(text))


def next_data(raw):
    soup = BeautifulSoup(raw, 'lxml')
    node = soup.select_one('#__NEXT_DATA__')
    if node is None:
        raise ValueError('us_sl_payload_missing')
    try:
        p = json.loads(node.string)['props']['pageProps']
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('us_sl_payload_invalid') from exc
    if p.get('hasError'):
        raise ValueError('us_sl_error_page')
    return p


def sporting_schedule(summary, raw=None):
    """Sporting Life summary 使用 UTC；完整页额外核对同场 JSON-LD。"""
    when = datetime.fromisoformat(summary['date']+'T'+summary['time'])
    when = when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)
    if raw is not None:
        soup = BeautifulSoup(raw, 'lxml')
        for node in soup.select('script[type="application/ld+json"]'):
            value = json.loads(node.string or '')
            entries = value if isinstance(value, list) else [value]
            for entry in entries:
                if entry.get('@type') != 'SportsEvent':
                    continue
                stamp = datetime.fromisoformat(entry['startDate'].replace('Z', '+00:00'))
                race_id = str(summary['race_summary_reference']['id'])
                if (stamp.tzinfo is None or stamp != when or entry.get('name') != summary['name']
                        or entry.get('location', {}).get('name') != summary['course_name']
                        or not re.search(r'/'+re.escape(race_id)+r'/', entry.get('url', ''))):
                    raise ValueError('us_sl_clock_conflict')
    return when


def actual_sporting_time(summary, scheduled, identity):
    raw = summary.get('off_time')
    if not raw:
        return ''
    if not re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', raw):
        raise ValueError('us_sl_actual_clock')
    clock = datetime.strptime(raw, '%H:%M:%S' if raw.count(':') == 2 else '%H:%M').time()
    zone = ZoneInfo(VENUES[identity['track']][2])
    options = [datetime.combine(scheduled.date()+timedelta(days=delta), clock, timezone.utc)
               for delta in (-1, 0, 1)]
    options = [value for value in options if abs(value-scheduled) <= timedelta(hours=3)
               and value.astimezone(zone).date().isoformat() == identity['date']]
    if len(options) != 1:
        raise ValueError('us_sl_actual_clock_ambiguous')
    return options[0].astimezone(zone).isoformat()


def chart_actual_time(raw, *, scheduled, identity):
    """官方带时区计划时间锚定 DRF 的12小时钟点；缺证据不猜测。"""
    if not raw or not scheduled:
        return ''
    anchor = datetime.fromisoformat(scheduled)
    zone = ZoneInfo(VENUES[identity['track']][2])
    if anchor.tzinfo is None or anchor.astimezone(zone).date().isoformat() != identity['date']:
        raise ValueError('us_chart_clock_anchor')
    match = re.fullmatch(r'(0?[1-9]|1[0-2]):([0-5]\d)(?::([0-5]\d))?', raw)
    if not match:
        raise ValueError('us_chart_clock_format')
    hour, minute, second = int(match[1]) % 12, int(match[2]), int(match[3] or 0)
    day = datetime.fromisoformat(identity['date'])
    options = [day.replace(hour=hour+half, minute=minute, second=second, tzinfo=zone) for half in (0, 12)]
    options = [value for value in options if abs(value.astimezone(timezone.utc)-anchor) <= timedelta(hours=3)]
    if len(options) != 1:
        raise ValueError('us_chart_clock_ambiguous')
    return options[0].isoformat()


def parse_sporting_life(raw, identity):
    data = next_data(raw)['race']; summary = data['race_summary']
    when = sporting_schedule(summary, raw)
    if (when.astimezone(ZoneInfo(VENUES[identity['track']][2])).date().isoformat() != identity['date']
            or summary['course_name'] != VENUES[identity['track']][0]
            or not re.match(r'Race '+str(identity['race_number'])+r'\b', summary['name'])
            or summary['race_stage'] != 'WEIGHEDIN'):
        raise ValueError('us_sl_identity_or_stage')
    runners, scratches = [], []
    for ride in data['rides']:
        row = dict(horse_name=ride['horse']['name'], program_number=ride['cloth_number'],
                   jockey=ride.get('jockey', {}).get('name', ''), trainer=ride.get('trainer', {}).get('name', ''))
        if not isinstance(row['program_number'], int) or row['program_number'] <= 0:
            raise ValueError('us_sl_program_number')
        if ride['ride_status'] in {'NONRUNNER', 'WITHDRAWN'}:
            scratches.append(row)
        elif ride['ride_status'] == 'RUNNER':
            position = ride.get('finish_position')
            casualty = ride.get('casualty', {})
            if position and position > 0:
                row.update(placing=position, status='finished')
            elif casualty.get('reason') in {'PU', 'DNF'} or casualty.get('code') in {'PU', 'DNF'}:
                row.update(placing=None, status='did_not_finish')
            else:
                raise ValueError('us_sl_finish_unknown:' + str(casualty))
            runners.append(row)
        else:
            raise ValueError('us_sl_status_unknown')
    if type(summary.get('ride_count')) is not int or summary['ride_count'] <= 0 or len(runners) != summary['ride_count']:
        raise ValueError('us_sl_runner_count')
    return dict(runners=runners, scratches=scratches, provider='sporting_life', declared_runner_count=summary['ride_count'],
                off_time=actual_sporting_time(summary, when, identity),
                scheduled_off_time=when.astimezone(ZoneInfo(VENUES[identity['track']][2])).isoformat(),
                off_time_basis='sporting_life_actual_utc' if summary.get('off_time') else '')


def parse_abr(raw, identity):
    soup = BeautifulSoup(raw, 'lxml')
    stamp = soup.select_one('.race-date'); title = soup.select_one('h1')
    if not stamp or not title:
        raise ValueError('us_abr_identity')
    day = stamp.get_text(' ', strip=True).replace('Sept.', 'Sep').replace('.', '')
    if datetime.strptime(day, '%b %d, %Y').date().isoformat() != identity['date'] or key(title.get_text()) != key(re.sub(r'\s*\(G[123]\)\s*$', '', identity['name'])):
        raise ValueError('us_abr_identity')
    runners = []
    for node in soup.select('.race-results .results-container .result'):
        def get(selector):
            element = node.select_one(selector)
            value = element.get_text(' ', strip=True) if element else ''
            if not value:
                raise ValueError('us_abr_required_field_missing:' + selector)
            return value
        fields = {li.select_one('.key').get_text().strip(' /').lower():li.select_one('.value').get_text(' ',strip=True)
                  for li in node.select('li') if li.select_one('.key') and li.select_one('.value')}
        placing = re.fullmatch(r'(\d+)(st|nd|rd|th)', get('.position').replace(' ', ''))
        if not placing:
            raise ValueError('us_abr_placing')
        runners.append(dict(horse_name=get('.entry-header .title'), program_number=int(get('.entry-header .number')),
            placing=int(placing[1]), status='finished', jockey=fields.get('jockey',''), trainer=fields.get('trainer','')))
    if not runners:
        raise ValueError('us_abr_no_results')
    scratches = [dict(horse_name=n.get_text(' ', strip=True), program_number=None)
                 for n in soup.select('.scratches .name')]
    return dict(runners=runners, scratches=scratches, provider='americas_best_racing')


def merge_result(chart, supplement, *, expected_count):
    if len(chart['runners']) != expected_count or len(supplement['runners']) != expected_count:
        raise ValueError('us_result_count_mismatch')
    supplement_rows = {horse_key(r['horse_name']): r for r in supplement['runners']}
    if len(supplement_rows) != expected_count or set(supplement_rows) != {horse_key(r['chart_name']) for r in chart['runners']}:
        raise ValueError('us_result_roster_mismatch:' + ','.join(sorted(set(supplement_rows) ^ {horse_key(r['chart_name']) for r in chart['runners']})))
    rows = []
    for row in chart['runners']:
        other = supplement_rows[horse_key(row['chart_name'])]
        other = dict(other)
        if row['status'] == 'did_not_finish' and other['placing'] == expected_count:
            other['supplement_reported_placing'] = other['placing']
            other.update(placing=None, status='did_not_finish')
        if (row['placing'], row['status']) != (other['placing'], other['status']):
            raise ValueError('us_result_placing_mismatch:' + other['horse_name'])
        if not other['jockey'] or not other['trainer']:
            raise ValueError('us_result_people_missing')
        rows.append(dict(row, **other))
    numbers = [r['program_number'] for r in rows]
    if len(numbers) != len(set(numbers)):
        raise ValueError('us_result_program_duplicate')
    scratches = supplement['scratches']
    if len(scratches) != len(chart['scratches']) or {horse_key(r['horse_name']) for r in scratches} != {horse_key(r) for r in chart['scratches']}:
        raise ValueError('us_result_scratches_mismatch:' + str(chart['scratches']))
    return dict(chart, runners=rows, scratches=scratches, runner_count=len(rows),
        off_time=supplement.get('off_time',''),
        scheduled_off_time=supplement.get('scheduled_off_time',''),
        off_time_basis=supplement.get('off_time_basis',''),
        gaps=['scratch_program_number_missing'] if any(r['program_number'] is None for r in scratches) else [])


def parse_program_entries(raw, identity):
    """TrueNicks/BloodHorse 自有稿中的出马表，仅补马号，不覆盖赛后字段。"""
    soup = BeautifulSoup(raw, 'lxml')
    day = datetime.strptime(identity['date'], '%Y-%m-%d')
    suffix = f"/race/USA/{identity['track']}/{day.year}/{day.month}/{day.day}/{identity['race_number']}/"
    sections = [s for s in soup.select('section.race-entry-shortcode')
                if any(a.get('href', '').startswith('https://www.bloodhorse.com'+suffix) for a in s.select('h3 a'))]
    if len(sections) != 1:
        raise ValueError('us_program_identity')
    rows = []
    for tr in sections[0].select('tbody tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 6 or not cells[1].select_one('.postPos') or not cells[1].select_one('a'):
            raise ValueError('us_program_row')
        name = cells[1].select_one('a').get_text(' ', strip=True)
        name = re.sub(r'\s*\([A-Z]{2}\)$', '', name)  # 出生州；不删 IRE 等国家。
        rows.append(dict(horse_name=name, program_number=int(cells[1].select_one('.postPos').get_text())))
    if not rows or len({horse_key(r['horse_name']) for r in rows}) != len(rows):
        raise ValueError('us_program_roster')
    return rows


def supplement_programs(result, entries):
    by_name = {horse_key(e['horse_name']): e for e in entries}
    all_rows = result['runners'] + result['scratches']
    if len(entries) != len(all_rows) or set(by_name) != {horse_key(r['horse_name']) for r in all_rows}:
        raise ValueError('us_program_roster_mismatch')
    for row in all_rows:
        number = by_name[horse_key(row['horse_name'])]['program_number']
        if row['program_number'] not in (None, number):
            raise ValueError('us_program_number_conflict')
    if len({e['program_number'] for e in entries}) != len(entries):
        raise ValueError('us_program_number_duplicate')
    result = dict(result, scratches=[dict(r, program_number=by_name[horse_key(r['horse_name'])]['program_number']) for r in result['scratches']], gaps=[])
    return result


def parse_abr_program(raw, identity):
    """ABR逐马完整介绍中的明示马号，仍由整场最终名单核对。"""
    soup=BeautifulSoup(raw,'lxml');title=soup.select_one('h1');body=soup.select_one('.field-name-body')
    race=re.sub(r'\s*\(G[123]\)\s*$','',identity['name'])
    if not title or not body or key(title.get_text())!=key(identity['date'][:4]+' '+race+' Cheat Sheet'):
        raise ValueError('us_program_identity')
    text=body.get_text(' ',strip=True);day=datetime.fromisoformat(identity['date'])
    month=day.strftime('%b')
    if (not re.search(r'\b'+month+r'(?:t)?\.?\s+'+str(day.day)+r'\b',text[:1400])
        or VENUES[identity['track']][1].lower() not in text[:1400].lower()):
        raise ValueError('us_program_identity')
    rows=[]
    for heading in body.select('strong'):
        match=re.fullmatch(r'(\d+)\.\s+(.+?)\s+\([\d/-]+(?: morning-line odds)?\)',heading.get_text(' ',strip=True))
        if match:rows.append(dict(horse_name=match[2],program_number=int(match[1])))
    if not rows or len({horse_key(r['horse_name']) for r in rows})!=len(rows):raise ValueError('us_program_roster')
    return rows


def programme_schedule(raw, identity):
    """独立赛前原文的完整身份和明确 AM/PM/时区，仅用于锚定 DRF 钟点。"""
    soup=BeautifulSoup(raw,'lxml');day=datetime.fromisoformat(identity['date'])
    suffix=f"/race/USA/{identity['track']}/{day.year}/{day.month}/{day.day}/{identity['race_number']}/"
    sections=[s for s in soup.select('section.race-entry-shortcode')
        if any(a.get('href','').startswith('https://www.bloodhorse.com'+suffix) for a in s.select('h3 a'))]
    if len(sections)==1:
        clocks=[re.fullmatch(r'(\d{1,2}:\d{2}) (AM|PM) \(local\)',n.get_text(' ',strip=True)) for n in sections[0].select('.properties li')]
        clocks=[m for m in clocks if m]
        if len(clocks)!=1:raise ValueError('us_programme_clock')
        clock=datetime.strptime(clocks[0][1]+' '+clocks[0][2],'%I:%M %p').time()
    else:
        body=soup.select_one('.field-name-body');title=soup.select_one('h1')
        normalize=lambda value:key(re.sub(r'\([^)]*\)|\bStakes\b|\bS\.?(?=\s|$)', '', value,flags=re.I))
        race=re.sub(r'\s*\(G[123]\)\s*$','',identity['name'])
        if not title or not body or normalize(title.get_text())!=normalize(str(day.year)+' '+race+' at a Glance'):
            raise ValueError('us_programme_identity')
        text=body.get_text(' ',strip=True)
        date_match=re.search(r'Date: (\w+\.?) (\d{1,2})\b',text)
        race_match=re.search(r'Race: (\d+)\b',text)
        clock_match=re.search(r'Post Time: (\d{1,2}:\d{2}) ([ap])\.m\. ET\b',text)
        if (not date_match or not race_match or not clock_match or int(race_match[1])!=identity['race_number']
            or VENUES[identity['track']][1] not in text or VENUES[identity['track']][2]!='America/New_York'
            or datetime.strptime(date_match[1].replace('Sept.','Sep').replace('.','')+' '+date_match[2]+' '+str(day.year),'%b %d %Y').date()!=day.date()):
            raise ValueError('us_programme_identity')
        clock=datetime.strptime(clock_match[1]+' '+clock_match[2].upper()+'M','%I:%M %p').time()
    return datetime.combine(day.date(),clock,tzinfo=ZoneInfo(VENUES[identity['track']][2])).isoformat()
