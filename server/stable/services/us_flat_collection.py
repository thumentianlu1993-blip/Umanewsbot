"""平地赛果独立采集/回放：有界网络、原件摘要、逐场错误；无数据库。"""
from datetime import date
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .us_source_collection import SourceStore, allowed_url
from .us_racing_sources import parse_toba_calendar
from .us_flat_results import (VENUES, key, next_data, parse_chart, parse_sporting_life,
    parse_abr, parse_program_entries, supplement_programs, merge_result, sporting_schedule)

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
        'www.americasbestracing.net': r'/(?:races|the-sport|gambling)/\d{4}-[a-z0-9-]+',
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
    if not found:
        raise ValueError('not_published')
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


def chart_from_final_summary(target, raw):
    """DRF月目录已上架、汇总页未更新时，以独立终报确定唯一单场身份。"""
    matches = []
    for meeting in next_data(raw)['meetings']:
        parent = meeting['meeting_summary']
        course = parent['course']
        if (course['country']['long_name'] != 'United States'
                or course['name'] != VENUES[target['venue']][0]):
            continue
        for summary in meeting['races']:
            name = re.fullmatch(r'Race ([1-9][0-9]*) - (.+?) - Grade ([123])', summary['name'])
            if not name or race_key(re.sub(r' Stakes$', ' S', name[2], flags=re.I)) != race_key(target['race_name']):
                continue
            matches.append((parent, summary, name))
    if not matches:
        raise ValueError('not_published')
    if len(matches) != 1:
        raise ValueError('us_sl_result_identity_ambiguous')
    parent, summary, name = matches[0]
    when = sporting_schedule(summary)
    number = int(name[1])
    race_id = summary['race_summary_reference']['id']
    if (parent['date'] != target['local_date']
            or when.astimezone(ZoneInfo(VENUES[target['venue']][2])).date().isoformat() != target['local_date']
            or summary['course_name'] != parent['course']['name']
            or 'G' + name[3] != target['grade'] or not 1 <= number <= 16
            or type(race_id) is not int or race_id <= 0
            or (target.get('source_race_id') and str(number) != str(target['source_race_id']))):
        raise ValueError('us_sl_result_identity_mismatch')
    if summary['race_stage'] != 'WEIGHEDIN' or summary.get('hidden') or parent.get('abandoned'):
        raise ValueError('not_published')
    day = date.fromisoformat(target['local_date'])
    url = ('https://www1.drf.com/displayChart.do?filepath=/download/simulcastweekly/charts/'
           + day.strftime('%y%m') + '/' + target['venue'] + day.strftime('%Y%m%d') + f'{number:02}.pdf')
    return dict(url=url, track=target['venue'], date=target['local_date'], race_number=number,
                name=target['race_name'], sporting_race_id=race_id, sporting_race_name=summary['name'],
                sporting_scheduled_at=when.isoformat(), identity_basis='sporting_life_final_summary')


def discover_program_entries(identity, *, read, initial):
    """从赛页实际文章链接有界发现；最多四页、两跳，不预填某场文章URL。"""
    from .us_flat_results import parse_abr_program
    root='https://www.americasbestracing.net'
    slug=re.sub(r'[^a-z0-9]+','-',re.sub(r'\s*\(G[123]\)\s*$','',identity['name']).lower()).strip('-')
    queue=[(initial,0)];seen={initial['url']};visited=0
    while queue and visited<4:
        item,depth=queue.pop(0)
        doc=read(item) if isinstance(item,str) else item
        visited+=1
        try:return parse_abr_program(doc['body'],identity),doc
        except ValueError:pass
        if depth>=2:continue
        links=sorted({urljoin(doc['url'],a['href']) for a in BeautifulSoup(doc['body'],'lxml').select('a[href]')
            if slug in urljoin(doc['url'],a['href']) and flat_url_allowed(urljoin(doc['url'],a['href']))})
        pending=[]
        for url in links[:8]:
            if url in seen or not url.startswith(root+('/the-sport/')) and not url.startswith(root+'/gambling/'):continue
            seen.add(url);pending.append((url,depth+1))
        queue=pending+queue
    raise ValueError('us_program_supplement_not_discovered')


def archived_program_entries(identity, *, urls, read):
    """精确冻结包内按原文身份检索补表；仅档案导入使用，不声称当前网络可用。"""
    urls=sorted(urls)
    if len(urls)>30:raise ValueError('us_archive_program_limit')
    matches=[]
    for url in urls:
        if not flat_url_allowed(url):raise ValueError('us_archive_program_url')
        doc=read(url)
        try:entries=parse_program_entries(doc['body'],identity)
        except ValueError:continue
        matches.append((entries,doc))
    if len(matches)!=1:raise ValueError('us_archive_program_not_found_or_ambiguous')
    return matches[0]


def collect_flat_results(store, *, start, end, program_sources=None, target_keys=None, programme_sources=None):
    if not isinstance(start, date) or not isinstance(end, date) or not start <= end or (end-start).days > 366:
        raise ValueError('us_date_window')
    program_sources = program_sources or {}
    programme_sources = programme_sources or {}
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
    if target_keys is not None:
        targets = [t for t in targets if t['candidate_key'] in target_keys]
    directory, _ = read_parse(DRF_INDEX, drf_directory)
    used = set()
    for target in targets:
        identity = None
        identity_doc = None
        result_docs = []
        try:
            today = store.now.astimezone(ZoneInfo(VENUES[target['venue']][2])).date().isoformat()
            if target['local_date'] > today:
                pending.append(dict(target, status='scheduled'))
                continue
            try:
                identity = select_chart(target, directory)
            except ValueError as exc:
                if str(exc) != 'not_published':
                    raise
                identity, day_doc = read_parse(SL_INDEX + target['local_date'],
                    lambda raw: chart_from_final_summary(target, raw))
                identity_doc = day_doc
            if identity['url'] in used:
                raise ValueError('us_chart_reused_for_multiple_targets')
            used.add(identity['url'])
            def parse_available_chart(raw, bound_identity):
                if identity_doc is not None and not raw:
                    raise ValueError('not_published')
                return parse_chart(raw, bound_identity)
            chart, chart_doc = read_parse(identity['url'], parse_available_chart, identity, accept=False)
            result_docs.append(chart_doc)
            day_url = SL_INDEX+identity['date']
            if identity_doc is not None:
                supplement_url = sl_result_url(identity_doc['body'], identity)
                if not supplement_url:
                    raise ValueError('not_published')
            else:
                supplement_url, _ = read_parse(day_url, sl_result_url, identity)
            if supplement_url:
                supplement, supplement_doc = read_parse(supplement_url, parse_sporting_life, identity, accept=False)
            else:
                slug = re.sub(r'\s*\(G[123]\)\s*$', '', identity['name']).lower()
                slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
                supplement_url = 'https://www.americasbestracing.net/races/'+identity['date'][:4]+'-'+slug
                supplement, supplement_doc = read_parse(supplement_url, parse_abr, identity, accept=False)
            result_docs.append(supplement_doc)
            field_raw = target.get('field_size_raw')
            if field_raw == '':
                expected_count = supplement.get('declared_runner_count')
                if supplement.get('provider') != 'sporting_life' or type(expected_count) is not int or expected_count <= 0:
                    raise ValueError('us_independent_runner_count_missing')
                count_evidence = dict(count=expected_count, basis='sporting_life_declared', source_sha256=supplement_doc['sha256'])
            else:
                if not isinstance(field_raw, str) or not re.fullmatch(r'[1-9][0-9]*', field_raw):
                    raise ValueError('us_calendar_runner_count_invalid')
                expected_count = int(field_raw)
                count_evidence = dict(count=expected_count, basis='toba_field', source_sha256=target['raw_sha256'])
            result = merge_result(chart, supplement, expected_count=expected_count)
            result['runner_count_evidence'] = count_evidence
            program_doc = None
            if result['gaps']:
                if program_url := program_sources.get(identity['url']):
                    entries, program_doc = read_parse(program_url, parse_program_entries, identity, accept=False)
                else:
                    def read_program(url):
                        _,doc=read_parse(url,lambda raw:None,accept=False)
                        result_docs.append(doc)
                        return doc
                    archive_urls=getattr(store,'archive_program_urls',())
                    if archive_urls:
                        try:entries,program_doc=archived_program_entries(identity,urls=archive_urls,read=read_program)
                        except ValueError as exc:
                            if str(exc)!='us_archive_program_not_found_or_ambiguous':raise
                            entries,program_doc=discover_program_entries(identity,read=read_program,initial=supplement_doc)
                    else:entries,program_doc=discover_program_entries(identity,read=read_program,initial=supplement_doc)
                result_docs.append(program_doc)
                result = supplement_programs(result, entries)
            schedule_doc=None
            if not result.get('off_time'):
                from .us_flat_results import programme_schedule,chart_actual_time
                if programme_sources.get(target['candidate_key']):
                    anchor,schedule_doc=read_parse(programme_sources[target['candidate_key']],programme_schedule,identity,accept=False)
                    result_docs.append(schedule_doc)
                elif program_doc:
                    try:anchor=programme_schedule(program_doc['body'],identity);schedule_doc=program_doc
                    except ValueError:anchor=''
                else:anchor=''
                if anchor:
                    result.update(scheduled_off_time=anchor,
                        off_time=chart_actual_time(chart['off_time_raw'],scheduled=anchor,identity=identity),
                        off_time_basis='drf_actual_anchored_to_programme')
            provenance = {'chart': chart_doc['sha256'], 'supplement': supplement_doc['sha256']}
            if identity_doc is not None:
                provenance['identity'] = identity_doc['sha256']
            if schedule_doc:provenance['schedule']=schedule_doc['sha256']
            if program_doc:
                provenance['program'] = program_doc['sha256']
            result.update(catalogue=target, candidate_key=target['candidate_key'], race_name=target['race_name'], grade=target['grade'],
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
