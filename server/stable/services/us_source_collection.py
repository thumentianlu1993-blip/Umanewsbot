"""美国来源采集/离线重放接口，不读取业务数据库。"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

from .us_racing_sources import parse_document, name_key, text, reconcile_sources

NSA_INDEX = 'https://nationalsteeplechase.com/racing/'
DEL_MAR_NOMS = 'https://www.dmtc.com/horsemen/nominations'


def allowed_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.query or p.fragment or p.netloc != p.hostname:
        return False
    patterns = {
        'toba.org': r'/graded-stakes/\d{4}-races/',
        'nationalsteeplechase.com': r'(?:/racing/|/wp-content/uploads/\d{4}/\d{2}/[A-Za-z0-9_.-]+\.pdf)',
        'www.dmtc.com': r'(?:/horsemen/nominations|/racing/entries/\d{4}-\d{2}-\d{2}|/racing/changes|/data/pdf/horsemen/nominations/[A-Za-z0-9_-]+\.pdf)',
    }
    return bool(re.fullmatch(patterns.get(p.hostname, r'(?!)'), p.path))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.part')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SourceStore:
    def __init__(self, root, *, allow_network=False, now=None, max_requests=80, max_bytes=8*1024*1024):
        self.root = Path(root)
        self.allow_network = allow_network
        self.now = now or datetime.now(timezone.utc)
        self.clock = (lambda: now) if now else (lambda: datetime.now(timezone.utc))
        if self.now.tzinfo is None or not 1 <= max_requests <= 80 or not 1 <= max_bytes <= 8*1024*1024:
            raise ValueError('us_collection_limits')
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.request_count = 0
        self.cache = {}
        self.failures = {}
        self.previous = {}
        self.accepted = set()
        index = self.root / 'receipts.json'
        self.receipts = json.loads(index.read_text()) if index.exists() else {'schema_version':1,'documents':{}}
        if self.receipts.get('schema_version') != 1 or not isinstance(self.receipts.get('documents'),dict):
            raise ValueError('us_cache_schema')

    def get(self, url):
        if not allowed_url(url):
            raise ValueError('us_source_url_rejected')
        if url in self.failures:
            raise ValueError(self.failures[url])
        try:
            return self._get(url)
        except (ValueError,OSError) as exc:
            self.failures[url] = str(exc)
            raise

    def _get(self, url):
        if url in self.cache:
            return self.cache[url]
        if self.allow_network:
            if self.request_count >= self.max_requests:
                raise ValueError('us_request_limit')
            self.request_count += 1
            try:
                with requests.get(url, timeout=(5,20), allow_redirects=False, stream=True,
                                  headers={'User-Agent':'Umanews-Source-Validation/1.0'}) as response:
                    if response.status_code != 200:
                        raise ValueError('us_http_' + str(response.status_code))
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise ValueError('us_document_too_large')
            except requests.Timeout:
                raise ValueError('us_network_timeout') from None
            except requests.RequestException:
                raise ValueError('us_network_error') from None
            body = bytes(body)
            if not body:
                raise ValueError('us_empty_document')
            digest = hashlib.sha256(body).hexdigest()
            meta = dict(url=url, sha256=digest, bytes=len(body), fetched_at=self.clock().isoformat())
            target = self.root / 'raw' / (digest + '.bin')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.' + uuid4().hex + '.part')
            try:
                temporary.write_bytes(body)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            self.previous[url] = self.receipts['documents'].get(url)
            versions = self.receipts.setdefault('versions', {}).setdefault(url, [])
            for version in (self.previous[url], meta):
                if version is not None and version not in versions:
                    versions.append(version)
            self.receipts['documents'][url] = meta
            atomic_json(self.root/'receipts.json', self.receipts)
        else:
            meta = self.receipts['documents'].get(url)
            if meta is None:
                raise ValueError('us_offline_cache_missing')
            if not re.fullmatch(r'[0-9a-f]{64}', str(meta.get('sha256',''))) or meta.get('url') != url:
                raise ValueError('us_cache_schema')
            stamp = datetime.fromisoformat(meta['fetched_at'])
            if stamp.tzinfo is None or stamp > self.now:
                raise ValueError('us_cache_timestamp')
            target = self.root/'raw'/(meta['sha256']+'.bin')
            if not target.is_file():
                raise ValueError('us_offline_cache_missing')
            if target.stat().st_size > self.max_bytes:
                raise ValueError('us_document_too_large')
            body = target.read_bytes()
            if hashlib.sha256(body).hexdigest() != meta['sha256'] or len(body) != meta['bytes']:
                raise ValueError('us_cache_digest_mismatch')
        self.cache[url] = dict(body=body, **meta)
        return self.cache[url]


    def accept(self, doc):
        """当前文档至少一个解析上下文通过，保留回放入口。"""
        url = doc['url']
        self.accepted.add(url)
        if self.allow_network and url in self.previous:
            self.receipts['documents'][url] = {k:v for k,v in doc.items() if k != 'body'}
            atomic_json(self.root/'receipts.json', self.receipts)

    def reject(self, doc):
        """失败原件及回执留在版本历史，恢复本轮刷新前的入口。"""
        url = doc['url']
        if not self.allow_network or url not in self.previous or url in self.accepted:
            return
        previous = self.previous[url]
        if previous is None:
            self.receipts['documents'].pop(url, None)
        else:
            self.receipts['documents'][url] = previous
        atomic_json(self.root/'receipts.json', self.receipts)


def nsa_directory(raw, *, start, end):
    soup = BeautifulSoup(raw, 'lxml')
    tables = [t for t in soup.select('table') if [text(h) for h in t.select('thead th')] ==
              ['DATE','RACE MEET','LOCATION','ENTRIES','RESULTS']]
    if len(tables) != 1:
        raise ValueError('us_nsa_directory_schema')
    meetings = []
    for tr in tables[0].select('tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 5:
            continue
        try:
            day = datetime.strptime(text(cells[0]), '%B %d, %Y').date()
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        links = {}
        for a in tr.select('a[href]'):
            kind = text(a).lower()
            if kind in {'entries', 'results'}:
                target = urljoin(NSA_INDEX, a['href'])
                if not allowed_url(target):
                    raise ValueError('us_source_url_rejected')
                links[kind] = target
        meetings.append(dict(local_date=day.isoformat(), meeting=text(cells[1]), links=links))
    # Explicit links only; never construct a PDF filename.
    books = sorted({urljoin(NSA_INDEX,a['href']) for a in soup.select('a[href]')
        if re.search(r'ConditionBook',a['href'],re.I) and a['href'].lower().endswith('.pdf')
        and any('/'+str(year)+'/' in a['href'] for year in range(start.year,end.year+1))})
    return dict(meetings=meetings, books=books)


def del_mar_nominations_directory(raw, *, year, start, end):
    soup = BeautifulSoup(raw, 'lxml')
    tables = [t for t in soup.select('table') if [text(h) for h in t.select('thead th')] ==
              ['RACE','CLOSED','RUNS','FILES']]
    if len(tables) != 1:
        raise ValueError('us_nomination_directory_schema')
    rows = []
    for tr in tables[0].select('tbody tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != 6:
            raise ValueError('us_nomination_directory_row')
        day_match = re.search(r'([A-Z][a-z]{2})\.\s+(\d{1,2})', text(cells[2]))
        if not day_match:
            raise ValueError('us_nomination_directory_date')
        day = datetime.strptime(f'{year} {day_match[1]} {day_match[2]}', '%Y %b %d').date()
        if not start <= day <= end:
            continue
        links = [urljoin(DEL_MAR_NOMS,a['href']) for a in tr.select('a[href]') if text(a)=='Noms']
        if len(links) != 1 or not allowed_url(links[0]):
            raise ValueError('us_nomination_directory_link')
        name = re.sub(r'\s*\((?:Gr\.|Grade)\s*[IVX123]+\)\s*$', '', text(cells[0])).rstrip(' *')
        rows.append(dict(local_date=day, race_name=name, url=links[0]))
    return rows


def collect_sources(store, *, start, end):
    if not isinstance(start,date) or not isinstance(end,date) or not start <= end or (end-start).days>366:
        raise ValueError('us_date_window')
    documents, errors, conflicts, unresolved = [], [], [], []
    targets = {}
    def read(url):
        try:
            return store.get(url)
        except (ValueError,OSError) as exc:
            errors.append(dict(url=url, reason=str(exc)))
            return None
    def parse(doc, provider, kind, event=None):
        if doc is None:
            return None
        try:
            data = parse_document(provider,kind,doc['body'],url=doc['url'],event=event)
        except (ValueError,TypeError,KeyError) as exc:
            store.reject(doc)
            errors.append(dict(url=doc['url'], reason=str(exc)))
            return None
        store.accept(doc)
        documents.append(dict(provider=provider, kind=kind, url=doc['url'],
            sha256=doc['sha256'], fetched_at=doc['fetched_at'], data=data))
        conflicts.extend(data.get('conflicts',[]))
        unresolved.extend(data.get('unresolved',[]))
        if kind in {'calendar','result'}:
            for row in data.get('items',[]):
                if not row.get('local_date') or row.get('grade') not in {'G1','G2','G3'}:
                    continue
                if not start.isoformat() <= row['local_date'] <= end.isoformat():
                    continue
                target = targets.setdefault(row['candidate_key'], dict(
                    candidate_key=row['candidate_key'], provider=provider, local_date=row['local_date'],
                    venue=row['venue'], race_name=row['race_name'], grade=row['grade'],
                    source_race_id=row.get('source_race_id',''), source_documents=[],
                    stages=[], gaps=['complete_result_source_missing','pre_race_coverage_unverified']))
                target['source_documents'].append(len(documents)-1)
                if target['grade'] != row['grade']:
                    conflicts.append(dict(reason='grade_conflict', evidence=[dict(target), row]))
                if kind=='result':
                    target['stages'].append('result_partial')
                    target['gaps'] = row['gaps'] + ['pre_race_coverage_unverified']
        return data

    for year in range(start.year,end.year+1):
        parse(read(f'https://toba.org/graded-stakes/{year}-races/'), 'toba', 'calendar')
    index = read(NSA_INDEX)
    if index:
        try:
            directory = nsa_directory(index['body'],start=start,end=end)
        except ValueError as exc:
            store.reject(index)
            errors.append(dict(url=NSA_INDEX, reason=str(exc)))
        else:
            store.accept(index)
            if not directory['meetings']:
                errors.append(dict(url=NSA_INDEX, reason='us_nsa_window_not_available'))
            for url in directory['books']:
                parse(read(url),'nsa','calendar')
            for meeting in directory['meetings']:
                if url := meeting['links'].get('results'):
                    data = parse(read(url),'nsa','result')
                    if data and any(r['local_date'] != meeting['local_date'] for r in data['items']):
                        errors.append(dict(url=url, reason='us_nsa_directory_date_mismatch'))
                # Discovery evidence, not an assertion that an unparsed entries PDF is complete.
            documents.append(dict(provider='nsa',kind='directory',url=NSA_INDEX,sha256=index['sha256'],
                fetched_at=index['fetched_at'],data=directory))

    nominations = []
    index = read(DEL_MAR_NOMS)
    if index:
        try:
            nominations = del_mar_nominations_directory(index['body'], year=datetime.fromisoformat(index['fetched_at']).astimezone(ZoneInfo('America/Los_Angeles')).year,start=start,end=end)
            store.accept(index)
        except ValueError as exc:
            store.reject(index)
            errors.append(dict(url=DEL_MAR_NOMS, reason=str(exc)))
    for row in nominations:
        obj = SimpleNamespace(local_date=row['local_date'], original_name=row['race_name'],chinese_name='',
                              racecourse='Del Mar',timezone_name='America/Los_Angeles')
        parse(read(row['url']),'del_mar','nominations',obj)
    conflicts.extend(reconcile_sources([d['data'] for d in documents])['conflicts'])

    card_events = {(t['local_date'], name_key(t['race_name'])):t['race_name']
                   for t in targets.values() if t['venue']=='DMR'
                   and date.fromisoformat(t['local_date']) <= store.now.date()+timedelta(days=14)}
    card_events.update({(r['local_date'].isoformat(),name_key(r['race_name'])):r['race_name'] for r in nominations})
    for (day,key), name in sorted(card_events.items()):
        obj = SimpleNamespace(local_date=date.fromisoformat(day),original_name=name,chinese_name='',
                              racecourse='Del Mar',timezone_name='America/Los_Angeles')
        url = 'https://www.dmtc.com/racing/entries/'+day
        data = parse(read(url),'del_mar','card',obj)
        if data:
            for target in targets.values():
                if (target['venue'], target['local_date'],name_key(target['race_name'])) == ('DMR',day,key):
                    target['stages'].append(data['source_stage'])
                    target['source_documents'].append(len(documents)-1)
    # The default changes page has no year: capture as partial evidence only for today's requested window.
    today = store.now.astimezone(ZoneInfo('America/Los_Angeles')).date()
    if start <= today <= end:
        obj = SimpleNamespace(local_date=today,original_name='',chinese_name='',
                              racecourse='Del Mar',timezone_name='America/Los_Angeles')
        parse(read('https://www.dmtc.com/racing/changes'),'del_mar','changes',obj)

    if not targets:
        errors.append(dict(url='',reason='us_empty_target_window'))
    return dict(schema_version=1,as_of=store.now.isoformat(),start=start.isoformat(),end=end.isoformat(),
        acceptance='incomplete',production_ready=False,
        targets=sorted(targets.values(),key=lambda t:(t['local_date'],t['venue'],t['race_name'],t['source_race_id'])),
        source_documents=documents,conflicts=conflicts,annual_unresolved=unresolved,errors=errors,
        remaining=['完整结果主源和字段覆盖','跨来源冲突与生产身份对账','候选写入和自然调度验收'])
