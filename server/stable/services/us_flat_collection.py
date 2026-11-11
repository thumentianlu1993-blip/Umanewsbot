"""平地赛果独立采集/回放：有界网络、原件摘要、逐场错误；无数据库。"""
from datetime import date
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .us_source_collection import SourceStore, allowed_url
from .us_racing_sources import parse_toba_calendar
from .us_flat_results import (VENUES, key, next_data, parse_chart, parse_sporting_life,
    parse_abr, parse_program_entries, supplement_programs, merge_result)

DRF_INDEX = 'https://www1.drf.com/StakesResults/MainMenu.do'
SL_INDEX = 'https://www.sportinglife.com/racing/results/'


def flat_url_allowed(url):
    if allowed_url(url):
        return urlsplit(url).hostname == 'toba.org'
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != p.hostname or p.fragment:
        return False
    if p.hostname == 'www1.drf.com':
        if url == DRF_INDEX:
            return True
        return bool(p.path == '/displayChart.do' and re.fullmatch(
            r'filepath=/download/simulcastweekly/charts/\d{4}/[A-Z]{2,3}\d{10}\.pdf', p.query))
    patterns = {
        'www.sportinglife.com': r'/racing/results/\d{4}-\d{2}-\d{2}(?:/[a-z0-9-]+/\d+/[a-z0-9-]+)?',
        'www.americasbestracing.net': r'/races/\d{4}-[a-z0-9-]+',
        'www.truenicks.com': r'/articles/\d+/[a-z0-9-]+',
    }
    return not p.query and bool(re.fullmatch(patterns.get(p.hostname, r'(?!)'), p.path))


class FlatSourceStore(SourceStore):
    url_allowed = staticmethod(flat_url_allowed)

    def __init__(self, *args, reuse_cache=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.reuse_cache = reuse_cache

    def _get(self, url):
        # 显式续传可以复用已有原件；报告保留各自抓取时刻，不声称刷新。
        network = self.allow_network
        if self.reuse_cache and url in self.receipts['documents']:
            self.allow_network = False
        try:
            return super()._get(url)
        finally:
            self.allow_network = network


def race_key(name):
    name = re.sub(r'\s*\(G[123]\)\s*$', '', name, flags=re.I).strip()
    name = re.sub(r'\s+S\.?$', '', name, flags=re.I)
    return key(name)


def drf_directory(raw):
    soup = BeautifulSoup(raw, 'lxml'); rows = []
    for a in soup.select('a[href]'):
        url = urljoin(DRF_INDEX, a['href'])
        if '/displayChart.do?' not in url:
            continue
        if not flat_url_allowed(url):
            raise ValueError('us_chart_directory_url')
        m = re.search(r'/([A-Z]{2,3})(\d{4})(\d{2})(\d{2})(\d{2})\.pdf$', url)
        tr = a.find_parent('tr'); cells = tr.find_all('td', recursive=False) if tr else []
        if not m or len(cells) < 3 or cells[0].get_text(strip=True) != m[1]:
            raise ValueError('us_chart_directory_row')
        day = date(int(m[2]), int(m[3]), int(m[4])).isoformat()
        rows.append(dict(url=url, track=m[1], date=day, race_number=int(m[5]), name=cells[1].get_text(' ',strip=True)))
    if not rows:
        raise ValueError('us_chart_directory_empty')
    if len({r['url'] for r in rows}) != len(rows):
        raise ValueError('us_chart_directory_duplicate')
    return rows


def select_chart(target, directory):
    found = [r for r in directory if r['date'] == target['local_date'] and r['track'] == target['venue']
             and race_key(r['name']) == race_key(target['race_name'])]
    if target.get('source_race_id'):
        found = [r for r in found if str(r['race_number']) == target['source_race_id']]
    if len(found) != 1:
        raise ValueError('us_chart_identity_missing_or_ambiguous')
    return found[0]


def sl_result_url(raw, identity):
    p = next_data(raw); matches = []
    for meeting in p['meetings']:
        course = meeting['meeting_summary']['course']
        if course['country']['long_name'] != 'United States' or course['name'] != VENUES[identity['track']][0]:
            continue
        for race in meeting['races']:
            if re.match(r'Race '+str(identity['race_number'])+r'\b', race['name']):
                slug = lambda s: re.sub(r'[^a-z0-9]+', '-', s.lower().replace("'", '')).strip('-')
                matches.append(SL_INDEX+race['date']+'/'+slug(course['name'])+'/'+str(race['race_summary_reference']['id'])+'/'+slug(race['name']))
    if len(matches) > 1:
        raise ValueError('us_sl_ambiguous')
    return matches[0] if matches else None


def collect_flat_results(store, *, start, end, program_sources=None):
    if not isinstance(start, date) or not isinstance(end, date) or not start <= end or (end-start).days > 366:
        raise ValueError('us_date_window')
    program_sources = program_sources or {}
    sources, errors, results, pending, targets, unresolved = [], [], [], [], [], []
    catalogue_conflicts, blocked_keys = [], set()
    def read_parse(url, parser, *args, accept=True):
        doc = store.get(url)
        try:
            value = parser(doc['body'], *args)
        except Exception:
            store.reject(doc)
            raise
        if accept:
            store.accept(doc)
        if not any(s['url'] == url for s in sources):
            sources.append({k:v for k,v in doc.items() if k != 'body'})
        return value, doc
    for year in range(start.year, end.year+1):
        url = f'https://toba.org/graded-stakes/{year}-races/'
        data, _ = read_parse(url, lambda body: parse_toba_calendar(body, url=url))
        targets.extend(r for r in data['items'] if r['grade'] in {'G1','G2','G3'} and start.isoformat() <= r['local_date'] <= end.isoformat())
        unresolved.extend(data['unresolved'])
        for conflict in data.get('conflicts', []):
            evidence = [r for r in conflict['evidence'] if r.get('local_date')
                        and start.isoformat() <= r['local_date'] <= end.isoformat()
                        and r.get('grade') in {'G1','G2','G3'}]
            if not evidence:
                continue
            catalogue_conflicts.append(conflict)
            if conflict['reason'] == 'source_conflict':
                for row in evidence:
                    if row['candidate_key'] in blocked_keys:
                        continue
                    blocked_keys.add(row['candidate_key'])
                    errors.append(dict(candidate_key=row['candidate_key'], race_name=row['race_name'],
                        local_date=row['local_date'], reason='us_calendar_source_conflict'))
    directory, _ = read_parse(DRF_INDEX, drf_directory)
    used = set()
    for target in targets:
        identity = None
        result_docs = []
        try:
            today = store.now.astimezone(ZoneInfo(VENUES[target['venue']][2])).date().isoformat()
            if target['local_date'] > today:
                pending.append(dict(target, status='scheduled'))
                continue
            identity = select_chart(target, directory)
            if identity['url'] in used:
                raise ValueError('us_chart_reused_for_multiple_targets')
            used.add(identity['url'])
            chart, chart_doc = read_parse(identity['url'], parse_chart, identity, accept=False)
            result_docs.append(chart_doc)
            day_url = SL_INDEX+identity['date']
            supplement_url, _ = read_parse(day_url, sl_result_url, identity)
            if supplement_url:
                supplement, supplement_doc = read_parse(supplement_url, parse_sporting_life, identity, accept=False)
            else:
                slug = re.sub(r'\s*\(G[123]\)\s*$', '', identity['name']).lower()
                slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
                supplement_url = 'https://www.americasbestracing.net/races/'+identity['date'][:4]+'-'+slug
                supplement, supplement_doc = read_parse(supplement_url, parse_abr, identity, accept=False)
            result_docs.append(supplement_doc)
            result = merge_result(chart, supplement, expected_count=int(target['field_size_raw']))
            program_doc = None
            if result['gaps'] and (program_url := program_sources.get(identity['url'])):
                entries, program_doc = read_parse(program_url, parse_program_entries, identity, accept=False)
                result_docs.append(program_doc)
                result = supplement_programs(result, entries)
            provenance = {'chart': chart_doc['sha256'], 'supplement': supplement_doc['sha256']}
            if program_doc:
                provenance['program'] = program_doc['sha256']
            result.update(candidate_key=target['candidate_key'], race_name=target['race_name'], grade=target['grade'],
                identity=identity, sources=provenance,
                field_sources={'finish_position':'chart','placing':'chart+supplement','status':'chart',
                    'weight_lbs':'chart','post_position':'chart','odds_net':'chart','margin_to_next':'chart',
                    'winning_time':'chart','fractional_times':'chart','jockey_raw':'chart','trainer_raw':'chart',
                    'horse_name':'supplement','jockey':'supplement','trainer':'supplement',
                    'program_number':'supplement','scratch_program_number':'program' if program_doc else 'supplement'})
            for doc in result_docs:
                store.accept(doc)
            results.append(result)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            for doc in result_docs:
                store.reject(doc)
            errors.append(dict(candidate_key=target['candidate_key'], race_name=target['race_name'],
                local_date=target['local_date'], reason=str(exc)))
    complete = bool(results) and not errors and all(not r['gaps'] for r in results)
    return dict(schema_version=1, as_of=store.now.isoformat(), start=start.isoformat(), end=end.isoformat(),
        acceptance='result_source_passed' if complete else 'incomplete', production_ready=False,
        targets=len({t['candidate_key'] for t in targets} | blocked_keys), results=results, pending=pending, errors=errors, sources=sources,
        catalogue_conflicts=catalogue_conflicts, blocked_candidates=sorted(blocked_keys),
        annual_unresolved=unresolved, network_requests=store.request_count,
        runner_count=sum(r['runner_count'] for r in results), scratch_count=sum(len(r['scratches']) for r in results),
        remaining=['生产赛事身份对账','赛后更新时效与七天更正','写入和自然调度、公开页面验收'])
