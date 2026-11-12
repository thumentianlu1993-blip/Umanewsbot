"""美国发布前清单、赛前资料及障碍结果的有界采集。"""
from datetime import date, datetime, timedelta
from io import BytesIO
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs, urlencode, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import pdfplumber

from .us_source_collection import SourceStore, allowed_url, nsa_directory, NSA_INDEX
from .us_flat_collection import flat_url_allowed, drf_directory, DRF_INDEX, FlatSourceStore
from .us_nsa_sources import parse_conditions, parse_results
from .us_prerace_documents import (parse_overnight,parse_stakes_nominations,parse_sporting_card,
    parse_nyra_card,confirm_del_mar_roster,final_result_roster,parse_usracing_prerace)
from .us_steeplechase_results import merge_steeplechase, resolve_prior_card_scratches

NSA_CODES={'Saratoga':'SAR','Colonial Downs':'CNL','Foxfield':'FX','Far Hills':'FH',
           'International Gold Cup':'GRM','Montpelier':'MTP','Camden':'CAM'}


def prerelease_url_allowed(url):
    if allowed_url(url) or flat_url_allowed(url):
        return True
    p=urlsplit(url)
    if p.scheme!='https' or p.netloc!=p.hostname or p.fragment:
        return False
    if p.hostname=='nationalsteeplechase.com' and p.path=='/wp-json/wp/v2/media':
        q=parse_qs(p.query)
        return (set(q)=={'search','after','before','per_page'} and q['per_page']==['30']
            and all(len(v)==1 for v in q.values())
            and bool(re.fullmatch(r'[A-Za-z -]{2,40}',q['search'][0]))
            and all(re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00',q[k][0]) for k in ['after','before']))
    if p.hostname=='www.nyra.com' and p.path in {'/belmont/racing/entries/','/saratoga/racing/entries/'}:
        q=parse_qs(p.query)
        return (set(q)=={'day','race'} and all(len(v)==1 for v in q.values())
                and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',q['day'][0]))
                and bool(re.fullmatch(r'[1-9]\d?',q['race'][0])))
    if p.query:
        return False
    patterns={
        'www.dmtc.com':r'/data/pdf/racing/entries/\d{8}\.pdf',
        'www.churchilldowns.com':r'/overnights/',
        'www.kentuckyderby.com':r'/wp-content/uploads/sites/3/\d{4}/\d{2}/[A-Za-z0-9_.-]+\.pdf',
        'www.keeneland.com':r'(?:/racing/horsemen/stakes-schedule|/files/[a-zA-Z0-9_.-]+\.pdf)',
        'www.sportinglife.com':r'/racing/racecards(?:/(?:tomorrow|\d{4}-\d{2}-\d{2}(?:/[a-z0-9-]+/racecard/\d+/[a-z0-9-]+)?))?',
        'usracing.com':r'/(?:graded-stakes-schedule|[a-z0-9-]+-stakes)',
    }
    return bool(re.fullmatch(patterns.get(p.hostname,r'(?!)'),p.path))


class PrereleaseStore(FlatSourceStore):
    url_allowed=staticmethod(prerelease_url_allowed)


def _prerace_name(value):
    # 仅标题修饰词/标点，冠名、Presented by等身份词完整保留。
    from .us_flat_results import key
    value=re.sub(r'^The\s+','',value,flags=re.I)
    value=re.sub(r'\b(?:Stakes|S\.)\s*','',value,flags=re.I)
    return key(value)


def usracing_directory(raw, targets):
    """只使用公开目录实际链接；不以赛名拼造网址或猜测未发布页。"""
    soup=BeautifulSoup(raw,'lxml');found={}
    for target in targets:
        urls={urljoin('https://usracing.com/',a['href']) for a in soup.select('a[href]')
              if _prerace_name(a.get_text(' ',strip=True))==_prerace_name(target['race_name'])
              and prerelease_url_allowed(urljoin('https://usracing.com/',a['href']))}
        if len(urls)>1:raise ValueError('us_usracing_directory_ambiguous')
        if urls:found[target['candidate_key']]=urls.pop()
    return found


def sporting_card_directory(raw, *, start, end, targets=()):
    from .us_flat_results import next_data,VENUES
    rows=[]
    for meeting in next_data(raw)['meetings']:
        course=meeting['meeting_summary']['course']
        if course['country']['long_name']!='United States':continue
        codes=[k for k,v in VENUES.items() if v[0]==course['name']]
        if not codes:continue
        # BAQ与AQU是同一实体赛场的不同来源meeting代码；由目标目录决定。
        if len(codes)>1:
            codes=[c for c in codes if any(t['venue']==c for t in targets)]
        if len(codes)!=1:continue
        code=codes[0]
        for race in meeting['races']:
            day=datetime.fromisoformat(race['date']+'T'+race['time']).replace(tzinfo=ZoneInfo('Europe/London')).astimezone(ZoneInfo(VENUES[code][2])).date()
            if not start<=day<=end:continue
            number=re.match(r'Race (\d+) - (.+)',race['name'])
            if not number:raise ValueError('us_card_directory_number')
            rid=race['race_summary_reference']['id']
            # 客户端目录没有SSR链接；使用目录明示的meeting date、course、race id和name。
            slug=lambda x:re.sub(r'[^a-z0-9]+','-',x.lower()).strip('-')
            meeting_day=meeting['meeting_summary']['date']
            url=f"https://www.sportinglife.com/racing/racecards/{meeting_day}/{slug(course['name'])}/racecard/{rid}/{slug(race['name'])}"
            if not prerelease_url_allowed(url):raise ValueError('us_card_directory_url')
            name=re.sub(r' - Grade [123]$','',number[2])
            rows.append(dict(track=code,date=day.isoformat(),race_number=int(number[1]),race_name=name,url=url))
    return rows


def _prior_card(store, *, entry_url, identity, merged):
    # 只在缺失退赛编号时查该赛场前一个月的公开文件目录，最多30条。
    keyword={'FX':'Foxfield','GRM':'Gold Cup'}.get(identity['track'])
    if not keyword:
        return merged
    day=date.fromisoformat(identity['date'])
    query=urlencode(dict(search=keyword,after=(day-timedelta(days=35)).isoformat()+'T00:00:00',
                         before=day.isoformat()+'T00:00:00',per_page=30))
    media=store.get('https://nationalsteeplechase.com/wp-json/wp/v2/media?'+query)
    rows=json.loads(media['body'])
    if not isinstance(rows,list) or len(rows)>=30:
        raise ValueError('us_nsa_media_truncated')
    current=[r for r in rows if r.get('source_url')==entry_url]
    if len(current)!=1:
        raise ValueError('us_nsa_media_current_missing')
    options=[r for r in rows if r.get('date','')<current[0]['date'] and 'overnight' in r.get('source_url','').lower()]
    for option in sorted(options,key=lambda r:r['date'],reverse=True):
        url=option['source_url']
        if not allowed_url(url):
            raise ValueError('us_nsa_media_url')
        doc=store.get(url)
        try:
            prior=parse_overnight(doc['body'],local_date=identity['date'],venue=identity['track'],race_number=identity['race_number'],source_url=url)
            result=resolve_prior_card_scratches(merged,prior)
        except ValueError:
            store.reject(doc)
            continue
        store.accept(doc);store.accept(media)
        result['sources']['prior_overnight']=dict(url=url,sha256=doc['sha256'],fetched_at=doc['fetched_at'],source_published_at=option['date'])
        result['sources']['revision_directory']=dict(url=media['url'],sha256=media['sha256'],fetched_at=media['fetched_at'])
        return result
    store.accept(media)
    return merged


def collect_nsa(store, *, start, end):
    if not isinstance(start,date) or not isinstance(end,date) or not start<=end or (end-start).days>366:
        raise ValueError('us_date_window')
    index=store.get(NSA_INDEX)
    listing=nsa_directory(index['body'],start=start,end=end)
    store.accept(index)
    chart_index=store.get(DRF_INDEX);charts=drf_directory(chart_index['body']);store.accept(chart_index)
    targets={};errors=[];results=[]
    for url in listing['books']:
        doc=store.get(url)
        parsed=parse_conditions(doc['body'],url=url);store.accept(doc)
        for r in parsed['items']:
            if start.isoformat()<=r['local_date']<=end.isoformat():targets[r['candidate_key']]=r
    for meeting in listing['meetings']:
        if 'results' not in meeting['links']:
            continue
        url=meeting['links']['results']
        doc=store.get(url)
        try:
            parsed=parse_results(doc['body'],url=url,graded_only=True)
            if any(r['local_date']!=meeting['local_date'] for r in parsed['items']):
                raise ValueError('us_nsa_directory_date_mismatch')
        except ValueError as exc:
            store.reject(doc);errors.append(dict(url=url,reason=str(exc)));continue
        store.accept(doc)
        for race in parsed['items']:
            earlier=targets.get(race['candidate_key'])
            if earlier and earlier['grade']!=race['grade']:
                race['grade_resolution']=dict(earlier_book_grade=earlier['grade'],official_result_grade=race['grade'],source=url,sha256=doc['sha256'])
            targets[race['candidate_key']]=race
            entry_url=meeting['links'].get('entries')
            if not entry_url:
                errors.append(dict(url=url,reason='us_nsa_entries_missing'));continue
            try:
                code=NSA_CODES[race['venue']]
                found=[x for x in charts if x['date']==race['local_date'] and x['track']==code and str(x['race_number'])==race['race_number']]
                if len(found)!=1:
                    raise ValueError('us_nsa_chart_identity')
                identity=found[0];chart=store.get(identity['url']);entry=store.get(entry_url)
                card=parse_overnight(entry['body'],local_date=identity['date'],venue=code,race_number=identity['race_number'],source_url=entry_url)
                merged=merge_steeplechase(chart['body'],identity,race,card)
                merged['candidate_key']=race['candidate_key']
                merged['sources']={kind:dict(url=d['url'],sha256=d['sha256'],fetched_at=d['fetched_at']) for kind,d in [('official_result',doc),('overnight',entry),('chart',chart)]}
                if 'scratch_program_number_missing' in merged['gaps']:
                    merged=_prior_card(store,entry_url=entry_url,identity=identity,merged=merged)
                if race.get('grade_resolution'):merged['grade_resolution']=race['grade_resolution']
                store.accept(chart);store.accept(entry);results.append(merged)
                if merged['gaps']:errors.append(dict(url=url,reason='us_nsa_fields_incomplete',gaps=merged['gaps']))
            except (ValueError,KeyError) as exc:
                errors.append(dict(url=url,reason=str(exc)))
    completed={r['candidate_key'] for r in results}
    for key,target in targets.items():
        if date.fromisoformat(target['local_date'])<=store.now.date() and key not in completed:
            errors.append(dict(candidate_key=key,reason='us_nsa_expected_result_missing'))
    pending=[t for t in targets.values() if date.fromisoformat(t['local_date'])>store.now.date()]
    return dict(targets=list(targets.values()),results=results,pending=pending,errors=errors,
        source_counts=dict(targets=len(targets),results=len(results),runners=sum(r['runner_count'] for r in results)))


def _source(doc):
    return {k:doc[k] for k in ('url','sha256','fetched_at')}


def churchill_target_card(raw,target):
    """按PDF中场次标题匹配目标；不能只凭文件日期挂接整份overnight。"""
    with pdfplumber.open(BytesIO(raw)) as pdf:
        lines=[line['text'] for page in pdf.pages for line in page.extract_text_lines(x_tolerance=1.5)]
    matches=[]
    for i,line in enumerate(lines[:-1]):
        number=re.match(r'^(\d+)(?:st|nd|rd|th) RACE\.',line,re.I)
        if not number:continue
        title=re.sub(r'\s*\(Grade [IVX123]+\).*$', '',lines[i+1],flags=re.I)
        if _prerace_name(title)==_prerace_name(target['race_name']):matches.append(int(number[1]))
    if len(matches)!=1 or (target.get('source_race_id') and str(matches[0])!=str(target['source_race_id'])):
        raise ValueError('us_churchill_overnight_identity')
    value=parse_overnight(raw,local_date=target['local_date'],venue='CD',race_number=matches[0])
    value['race_name']=target['race_name']
    value['gaps']=[str(r['entry_number'])+':jockey_name' for r in value['runners'] if not r['jockey_name']]
    value['gaps']+=['age_not_provided','post_position_not_provided']
    value['fields_complete']=False
    value['final_card']=False
    return value


def nsa_target_card(raw,target,*,source_url=''):
    """条件册编号只核对C编号；实际场次由同名正式overnight标题取得。"""
    with pdfplumber.open(BytesIO(raw)) as pdf:
        lines=[line['text'] for page in pdf.pages for line in page.extract_text_lines(x_tolerance=1.5)]
    matches=[]
    for i,line in enumerate(lines[:-1]):
        match=re.match(r'^(\d+)(?:st|nd|rd|th) Race\. \(C(X?\d+)\)',line,re.I)
        if not match:continue
        title=re.sub(r'^Purse \$[\d,]+(?: Guaranteed)?\s*','',lines[i+1],flags=re.I)
        title=re.split(r'\s*\(Grade |\s+\d+(?:[ /]\d+)* Miles?',title,flags=re.I)[0]
        if _prerace_name(title)!=_prerace_name(target['race_name']):continue
        book=str(target.get('book_race_id') or target.get('source_race_id') or '').split(':')[0]
        if book and book!=match[2]:raise ValueError('us_nsa_book_identity')
        matches.append(int(match[1]))
    if len(matches)!=1:raise ValueError('us_nsa_overnight_identity')
    value=parse_overnight(raw,local_date=target['local_date'],venue=target['venue'],race_number=matches[0],source_url=source_url)
    value['race_name']=target['race_name']
    return value


def nsa_preview(store, target):
    day=date.fromisoformat(target['local_date'])
    doc=store.get(NSA_INDEX);listing=nsa_directory(doc['body'],start=day,end=day)
    names={'FH':'far hills','FX':'foxfield','MTP':'montpelier','GRM':'international gold cup',
        'CNL':'colonial downs','SAR':'saratoga','CAM':'colonial cup'}
    token=names.get(target['venue'])
    if not token:raise ValueError('us_nsa_venue_unknown')
    meetings=[m for m in listing['meetings'] if token in m['meeting'].lower()]
    if len(meetings)!=1:raise ValueError('us_nsa_meeting_missing_or_ambiguous')
    store.accept(doc)
    url=meetings[0]['links'].get('entries')
    if not url:return None
    card=store.get(url)
    value=nsa_target_card(card['body'],target,source_url=url)
    store.accept(card)
    return dict(kind='card',venue=target['venue'],data=value,source=_source(card),directory_source=_source(doc))


def collect_prerace(store, *, start, end, flat_report, target_keys=None):
    """已赛用完整最终名单；待赛保留已发布资料及尚未核实的覆盖缺口。"""
    from .us_flat_collection import SL_INDEX
    from .us_flat_results import VENUES
    from .us_racing_sources import parse_toba_calendar,parse_del_mar_card,parse_del_mar_nominations,name_key
    from .us_source_collection import DEL_MAR_NOMS,del_mar_nominations_directory
    if not isinstance(start,date) or not isinstance(end,date) or not start<=end or (end-start).days>366:
        raise ValueError('us_date_window')
    if flat_report['start']!=start.isoformat() or flat_report['end']!=end.isoformat():
        raise ValueError('us_prerace_report_window')
    from .us_race_inventory import calendar_window_rows
    documents=[];errors=[];targets=[];directories=[]
    def read(url,parser):
        doc=store.get(url)
        try:value=parser(doc['body'])
        except (ValueError,KeyError,TypeError):
            store.reject(doc);raise
        store.accept(doc)
        return value,doc
    for year in range(start.year,end.year+1):
        url=f'https://toba.org/graded-stakes/{year}-races/'
        value,_=read(url,lambda raw:parse_toba_calendar(raw,url=url))
        targets.extend(calendar_window_rows(value,start=start.isoformat(),end=end.isoformat()))
    if target_keys is not None:
        targets=[t for t in targets if t['candidate_key'] in target_keys]
    results={x['candidate_key']:x for x in flat_report['results']}
    if len(results)!=len(flat_report['results']):
        raise ValueError('us_prerace_duplicate_result')
    supplement_urls={x['sha256']:x['url'] for x in flat_report['sources']}
    future_targets=[t for t in targets if t['candidate_key'] not in results]
    def append(doc,value,kind,venue):
        row=dict(kind=kind,venue=venue,data=value,source=_source(doc));documents.append(row);return len(documents)-1
    # 当前官方目录上的报名；只取目录明确发布的PDF。
    nominations=[]
    if any(t['venue']=='DMR' for t in future_targets):
        try:
            index=store.get(DEL_MAR_NOMS)
            listing=del_mar_nominations_directory(index['body'],year=datetime.fromisoformat(index['fetched_at']).astimezone(ZoneInfo('America/Los_Angeles')).year,start=start,end=end)
            store.accept(index);directories.append(_source(index))
            for item in listing:
                if not any(t['venue']=='DMR' and t['local_date']==item['local_date'].isoformat()
                           and _prerace_name(t['race_name'])==_prerace_name(item['race_name']) for t in future_targets):continue
                obj=SimpleNamespace(local_date=item['local_date'],original_name=item['race_name'],chinese_name='',racecourse='Del Mar',timezone_name='America/Los_Angeles')
                value,doc=read(item['url'],lambda raw:parse_del_mar_nominations(raw,url=item['url'],event=obj))
                value['directory_source']=_source(index)
                nominations.append(append(doc,value,'nominations','DMR'))
        except (ValueError,KeyError,TypeError,OSError) as exc:errors.append(dict(source=DEL_MAR_NOMS,reason=str(exc)))
    usracing='https://usracing.com/graded-stakes-schedule';public_links={}
    if future_targets:
        try:
            index=store.get(usracing);public_links=usracing_directory(index['body'],future_targets)
            store.accept(index);public_index=index;directories.append(_source(index))
        except (ValueError,KeyError,TypeError,OSError) as exc:errors.append(dict(source=usracing,reason=str(exc)))
    keeneland='https://www.keeneland.com/racing/horsemen/stakes-schedule'
    if any(t['venue']=='KEE' for t in future_targets):
        try:
            index=store.get(keeneland);soup=BeautifulSoup(index['body'],'lxml')
            links=sorted({urljoin(keeneland,a['href']) for a in soup.select('a[href]') if a.get_text(strip=True)=='Nominations' and a['href'].endswith('.pdf')})
            if not links:raise ValueError('us_keeneland_nomination_directory')
            store.accept(index);directories.append(_source(index))
            for url in links:
                try:
                    doc=store.get(url)
                    with pdfplumber.open(BytesIO(doc['body'])) as pdf:
                        content='\n'.join(line['text'] for line in pdf.pages[0].extract_text_lines(x_tolerance=.3))
                    match=re.search(r'TO BE RUN ([A-Z]+, [A-Z]+ \d{1,2}, \d{4})',content)
                    if not match:raise ValueError('us_nomination_date_missing')
                    day=datetime.strptime(match[1].title(),'%A, %B %d, %Y').date()
                    if not start<=day<=end:continue
                    title=next(x for x in content.splitlines() if not re.fullmatch(r'\d+(?:st|nd|rd|th) Running Of',x))
                    value=parse_stakes_nominations(doc['body'],local_date=day.isoformat(),race_name=title)
                    store.accept(doc);value['directory_source']=_source(index)
                    nominations.append(append(doc,value,'nominations','KEE'))
                except (ValueError,KeyError,TypeError,OSError) as exc:errors.append(dict(source=url,reason=str(exc)))
        except (ValueError,KeyError,TypeError,OSError) as exc:errors.append(dict(source=keeneland,reason=str(exc)))
    live=[]
    current_url='https://www.sportinglife.com/racing/racecards'+('/'+start.isoformat() if target_keys is not None and start==end else '')
    if future_targets:
        try:
            live,live_doc=read(current_url,lambda raw:sporting_card_directory(raw,start=start,end=end,targets=future_targets))
            directories.append(_source(live_doc))
        except (ValueError,KeyError,TypeError,OSError) as exc:errors.append(dict(source=current_url,reason=str(exc)))
    churchill={};churchill_index='https://www.churchilldowns.com/overnights/'
    if any(t['venue']=='CD' for t in future_targets):
        try:
            cd_doc=store.get(churchill_index)
            for a in BeautifulSoup(cd_doc['body'],'lxml').select('a[href]'):
                label=a.get_text(strip=True);url=urljoin(churchill_index,a['href'])
                year=re.search(r'/uploads/sites/3/(\d{4})/',url)
                if not re.fullmatch(r'\d{1,2}/\d{1,2}',label) or not year or not url.lower().endswith('.pdf'):continue
                day=datetime.strptime(year[1]+'/'+label,'%Y/%m/%d').date()
                if start<=day<=end:churchill.setdefault(day.isoformat(),set()).add(url)
            store.accept(cd_doc);directories.append(_source(cd_doc))
        except (ValueError,KeyError,TypeError,OSError) as exc:errors.append(dict(source=churchill_index,reason=str(exc)))
    rows=[]
    for target in targets:
        venue=target['venue'];day=target['local_date'];attached=[];issues=[]
        if target.get('source_conflict'):
            rows.append(dict(candidate_key=target['candidate_key'],venue=venue,local_date=day,
                race_name=target['race_name'],documents=[],nomination_status='unverified',card_status='unverified',
                conflict_evidence=target['source_conflict'],errors=[dict(reason='us_calendar_source_conflict')]))
            continue
        result=results.get(target['candidate_key'])
        if result:
            try:
                value=final_result_roster(result,target)
                sources={}
                for kind,digest in result['sources'].items():
                    doc=store.get(supplement_urls[digest])
                    if doc['sha256']!=digest:raise ValueError('us_final_roster_source_changed')
                    sources[kind]=_source(doc)
                documents.append(dict(kind='final_roster',venue=venue,data=value,sources=sources))
                attached.append(len(documents)-1)
            except (ValueError,KeyError,TypeError,OSError) as exc:
                issues.append(dict(reason=str(exc)))
            rows.append(dict(candidate_key=target['candidate_key'],venue=venue,local_date=day,
                race_name=target['race_name'],documents=attached,nomination_status='not_required_completed',
                card_status='final_roster_available' if attached else 'unverified',errors=issues))
            continue
        for i in nominations:
            nom=documents[i]
            if nom['venue']==venue and nom['data']['local_date']==day and _prerace_name(nom['data']['race_name'])==_prerace_name(target['race_name']):attached.append(i)
        matches=[r for r in live if r['track']==venue and r['date']==day and _prerace_name(r['race_name'])==_prerace_name(target['race_name'])
                 and (not target.get('source_race_id') or str(r['race_number'])==str(target['source_race_id']))]
        if len(matches)>1:
            issues.append(dict(source=current_url,reason='us_current_card_ambiguous'))
        elif matches:
            try:
                identity=matches[0];value,doc=read(identity['url'],lambda raw:parse_sporting_card(raw,identity))
                value['directory_source']=_source(live_doc);attached.append(append(doc,value,'card',venue))
            except (ValueError,KeyError,TypeError,OSError) as exc:issues.append(dict(source=matches[0]['url'],reason=str(exc)))
        if venue=='CD' and day in churchill:
            urls=churchill[day]
            if len(urls)!=1:
                issues.append(dict(source=churchill_index,reason='us_churchill_overnight_ambiguous'))
            else:
                url=next(iter(urls))
                try:
                    value,doc=read(url,lambda raw:churchill_target_card(raw,target))
                    value['directory_source']=_source(cd_doc)
                    attached.append(append(doc,value,'card',venue))
                except (ValueError,KeyError,TypeError,OSError) as exc:issues.append(dict(source=url,reason=str(exc)))
        # Del Mar直供HTML和独立overnight共同证明名单，保留final/provisional。
        if venue=='DMR' and day<=(store.now+timedelta(days=14)).date().isoformat():
            url='https://www.dmtc.com/racing/entries/'+day
            try:
                obj=SimpleNamespace(local_date=date.fromisoformat(day),original_name=target['race_name'],chinese_name='',racecourse='Del Mar',timezone_name='America/Los_Angeles')
                value,doc=read(url,lambda raw:parse_del_mar_card(raw,url=url,event=obj))
                if value['source_stage']!='not_published':
                    soup=BeautifulSoup(doc['body'],'lxml');path='/data/pdf/racing/entries/'+day.replace('-','')+'.pdf'
                    links={urljoin(url,a['href']) for a in soup.select('a[href]') if urlsplit(urljoin(url,a['href'])).path==path}
                    if len(links)!=1:raise ValueError('us_delmar_overnight_link')
                    overnight,other=read(links.pop(),lambda raw:parse_overnight(raw,local_date=day,venue=venue,race_number=int(value['race_number'])))
                    value=confirm_del_mar_roster(value,overnight);value['roster_source']=_source(other)
                attached.append(append(doc,value,'card',venue))
            except (ValueError,KeyError,TypeError,OSError) as exc:issues.append(dict(source=url,reason=str(exc)))
        kinds={documents[i]['kind'] for i in attached}
        if target['candidate_key'] in public_links:
            url=public_links[target['candidate_key']]
            try:
                value,doc=read(url,lambda raw:parse_usracing_prerace(raw,target))
                value['directory_source']=_source(public_index)
                attached.append(append(doc,value,'preliminary_field',venue))
            except (ValueError,KeyError,TypeError,OSError) as exc:issues.append(dict(source=url,reason=str(exc)))
        stages={documents[i]['data']['source_stage'] for i in attached}
        cards=[documents[i] for i in attached if documents[i]['kind']=='card'
               and documents[i]['data']['source_stage'] not in {'not_published','declared_overnight'}]
        gaps=[dict(source=c['source']['url'],gaps=c['data'].get('gaps',[])) for c in cards
              if c['data'].get('gaps') or c['data'].get('fields_complete') is False]
        if gaps and not any(not c['data'].get('gaps') and c['data'].get('fields_complete') is not False for c in cards):
            issues.append(dict(reason='us_card_fields_incomplete',evidence=gaps))
        # 当地赛日仍可能处于赛前；赛后卡的显式阶段、或已过去的当地日期才要求最终名单。
        past_day=day<store.now.astimezone(ZoneInfo(VENUES[venue][2])).date().isoformat()
        if past_day or 'historical_card' in stages:issues.append(dict(reason='us_expected_final_roster_missing'))
        rows.append(dict(candidate_key=target['candidate_key'],venue=venue,local_date=day,race_name=target['race_name'],documents=attached,
            nomination_status='available' if 'nominations' in kinds else 'no_admitted_document_in_checked_sources',
            preliminary_status='available' if 'preliminary_field' in stages else 'no_admitted_document_in_checked_sources',
            card_status='available' if any(documents[i]['kind']=='card' and documents[i]['data']['source_stage'] not in {'not_published','declared_overnight'} for i in attached)
                else 'provisional_available' if 'declared_overnight' in stages
                else 'not_published' if 'not_published' in stages else 'awaiting_publication',
            observation_status='check_failed' if issues else 'published_preliminary' if 'preliminary_field' in stages
                else 'published_document' if any(s!='not_published' for s in stages)
                else 'scheduled_no_admitted_document',errors=issues))
    return dict(targets=rows,documents=documents,checked_directories=directories,errors=errors,
        source_policy=dict(excluded=['equibase.com','*.equibase.com'],excluded_only_information='unavailable_for_project'),
        counts=dict(targets=len(rows),nominations=sum(r['nomination_status']=='available' for r in rows),cards=sum(r['card_status']=='available' for r in rows),
            final_rosters=sum(r['card_status']=='final_roster_available' for r in rows),
            preliminary_lists=sum(r.get('preliminary_status')=='available' for r in rows),
            awaiting_final_cards=sum(r['card_status'] in {'not_published','awaiting_publication','provisional_available'} for r in rows)),
        acceptance='coverage_gaps' if errors or any(r['card_status']=='unverified' or r['errors'] for r in rows) else 'observable_sources_passed_with_pending',
        production_ready=False)
