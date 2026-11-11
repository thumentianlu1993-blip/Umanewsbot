"""美国平地全场赛果；DRF 物理冲线与裁定名次分离，补源必须整场一致。"""
from datetime import datetime
from io import BytesIO
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import pdfplumber

# 代码是来源赛场标识，不是生产 RaceEvent 身份。
VENUES = {
    'BEL': ('Belmont Park', 'Belmont', 'America/New_York'),
    'CD': ('Churchill Downs', 'Churchill', 'America/New_York'),
    'CNL': ('Colonial Downs', 'Colonial', 'America/New_York'),
    'DEL': ('Delaware Park', 'Delaware', 'America/New_York'),
    'DMR': ('Del Mar', 'Del Mar', 'America/Los_Angeles'),
    'GP': ('Gulfstream', 'Gulfstream', 'America/New_York'),
    'KD': ('Kentucky Downs', 'Ky Downs', 'America/Chicago'),
    'LRC': ('Los Alamitos Racecourse', 'Los Alamitos', 'America/Los_Angeles'),
    'KEE': ('Keeneland', 'Keeneland', 'America/New_York'),
    'PID': ('Presque Isle Downs', 'Presque Isle', 'America/New_York'),
    'PRX': ('Philadelphia', 'Parx', 'America/New_York'),
    'RP': ('Remington Park', 'Remington', 'America/Chicago'),
    'SA': ('Santa Anita', 'Santa Anita', 'America/Los_Angeles'),
    'SAR': ('Saratoga', 'Saratoga', 'America/New_York'),
}
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
    'dimondnecklce': 'diamondnecklace'}


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
    return dict(local_date=identity['date'], track=identity['track'], race_number=race_number,
                winning_time=splits[-1], fractional_times=splits[:-1], runners=rows, scratches=scratches,
                margin_semantics='lengths_ahead_of_next_physical_finisher', demotion_notes=notes)


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


def parse_sporting_life(raw, identity):
    data = next_data(raw)['race']; summary = data['race_summary']
    when = datetime.fromisoformat(summary['date']+'T'+summary['time']).replace(tzinfo=ZoneInfo('Europe/London'))
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
    if len(runners) != summary['ride_count']:
        raise ValueError('us_sl_runner_count')
    return dict(runners=runners, scratches=scratches, provider='sporting_life')


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
