"""日本官方列表的确定性导航；只返回页面中实际存在的赛事链接。"""
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup


def unique(values):
    values=set(values)
    if len(values)!=1:
        raise ValueError('source_discovery_ambiguous' if values else 'not_published')
    return values.pop()


def jra_annual_result(page, *, url, event):
    from stable.services.race_pre_race import normalize_jra_race_name
    year=re.search(r'/replay/(\d{4})/jyusyo.html$',urlsplit(url).path)
    if not year or int(year[1])!=event.local_date.year:
        raise ValueError('jra_calendar_year_mismatch')
    names={normalize_jra_race_name(n) for n in (event.original_name,event.chinese_name) if n}
    matches=[]
    for row in BeautifulSoup(str(page),'html.parser').select('tr'):
        day,name,venue=(row.select_one('td.'+c) for c in ('date','race','place'))
        if day is None or name is None or venue is None:continue
        md=re.match(r'(\d+)月(\d+)日',day.get_text(strip=True))
        if not md or tuple(map(int,md.groups()))!=(event.local_date.month,event.local_date.day):continue
        for grade in name.select('.grade_icon'):grade.decompose()
        if normalize_jra_race_name(name.get_text(strip=True)) not in names or venue.get_text(strip=True)!=event.racecourse:continue
        matches.extend(urljoin(url,a['href']) for a in row.select('td.result a[href]'))
    return unique(matches)


def nar_topic_card(page, *, url, event):
    targets=[]
    for a in BeautifulSoup(str(page),'html.parser').select('a[href]'):
        target=urljoin(url,a['href']);p=urlsplit(target)
        q=parse_qs(p.query)
        if p.hostname=='www.keiba.go.jp' and p.path=='/KeibaWeb/TodayRaceInfo/DebaTable' and q.get('k_raceDate')==[event.local_date.strftime('%Y/%m/%d')]:
            targets.append(target)
    return unique(targets)


def discover_japan_url(*, event, route, now, fetcher):
    refs=event.source_refs if isinstance(event.source_refs,dict) else {}
    if route.provider=='jra':
        url=refs.get('primary','')
        if not re.search(r'/replay/\d{4}/jyusyo.html$',urlsplit(url).path):return None
        if not route.permits_url(url):raise ValueError('source_url_rejected')
        return jra_annual_result(fetcher(url,route=route,now=now),url=url,event=event)
    if route.provider!='nar':return None
    if any(urlsplit(refs.get(key,'')).path in {'/KeibaWeb/TodayRaceInfo/RaceList','/KeibaWeb/TodayRaceInfo/DebaTable'} for key in ('primary','detail')):
        from .nar_pre_race import fetch_nar_pre_race
        url,_,_=fetch_nar_pre_race(event=event,route=route,now=now,fetcher=fetcher)
        return url
    url=refs.get('detail','')
    if not re.fullmatch(r'/dirtgraderace/\d{4}/[^/]+/(?:introduction|racecard).html',urlsplit(url).path):return None
    if not route.permits_url(url):raise ValueError('source_url_rejected')
    url,page = nar_topic_document(event=event, route=route, now=now, fetcher=fetcher)
    return nar_topic_card(page,url=url,event=event)


def nar_topic_document(*, event, route, now, fetcher):
    refs=event.source_refs if isinstance(event.source_refs,dict) else {}
    url=refs.get("detail", "")
    path=urlsplit(url).path
    match=re.fullmatch(r'/dirtgraderace/(\d{4})/(\d{4})_[^/]+/(?:introduction|racecard).html',path)
    if not match or (match[1]+match[2])!=event.local_date.strftime('%Y%m%d') or not route.permits_url(url):
        raise ValueError('nar_topic_identity_mismatch')
    page=fetcher(url,route=route,now=now)
    if path.endswith('/introduction.html'):
        target_path=path.rsplit('/',1)[0]+'/racecard.html'
        soup=BeautifulSoup(str(page),'html.parser')
        links=[urljoin(url,a['href']) for a in soup.select('a[href]')
               if urlsplit(urljoin(url,a['href'])).path==target_path and route.permits_url(urljoin(url,a['href']))]
        if not links:
            # 官方将共用导航片段载入原页面；相对href仍以原页面为基址。
            nav=re.search(r'\$\([\"\']#common_navigation[\"\']\)\.load\([\"\'](common/navigation.html)[\"\']\)',str(page))
            if nav:
                nav_url=urljoin(url,nav[1])
                if not route.permits_url(nav_url):raise ValueError('source_url_rejected')
                fragment=fetcher(nav_url,route=route,now=now)
                links=[urljoin(url,a['href']) for a in BeautifulSoup(str(fragment),'html.parser').select('a[href]')
                       if urlsplit(urljoin(url,a['href'])).path==target_path and route.permits_url(urljoin(url,a['href']))]
        url=unique(links);page=fetcher(url,route=route,now=now)
    return url,page


def historical_roster(event, observation):
    """固定发布包中独立核验的日本历史名单；缺少合同则不给完整性背书。"""
    import hashlib
    import json
    from pathlib import Path
    from django.conf import settings
    from .race_source_identity import event_snapshot
    path=getattr(settings,'RACE_DATA_SYNC_JAPAN_HISTORICAL_ROSTER_FILE','')
    if not path or observation.get('provider')!='jra':return None
    target=Path(path)
    if not target.is_absolute() or target.is_symlink() or target.stat().st_size>1024*1024:
        raise ValueError('historical_roster_path')
    raw=target.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=getattr(settings,'RACE_DATA_SYNC_JAPAN_HISTORICAL_ROSTER_SHA256',''):
        raise ValueError('historical_roster_digest')
    manifest=json.loads(raw)
    if manifest.get('schema_version')!=1 or not isinstance(manifest.get('items'),list):
        raise ValueError('historical_roster_schema')
    matches=[r for r in manifest['items'] if r.get('event_id')==event.pk]
    if not matches:return None
    if len(matches)!=1:raise ValueError('historical_roster_duplicate')
    item=matches[0]
    if (item.get('event_snapshot_sha256')!=event_snapshot(event)
        or any(item.get(k)!=observation.get(k) for k in ('provider','external_race_id','local_date'))):
        raise ValueError('historical_roster_identity_drift')
    source=urlsplit(item.get('source_url',''))
    if (source.scheme!='https' or source.hostname!='race.netkeiba.com' or source.path!='/race/result.html'
        or source.username or source.password or source.port not in (None,443)
        or not re.fullmatch('[0-9a-f]{64}',item.get('source_sha256',''))):
        raise ValueError('historical_roster_evidence')
    rows=item.get('roster')
    if (not isinstance(rows,list) or not 1<=len(rows)<=30 or
        any(not isinstance(r,list) or len(r)!=2 or not all(isinstance(s,str) and s for s in r) or not r[0].isdigit() for r in rows)
        or len({r[0] for r in rows})!=len(rows)):
        raise ValueError('historical_roster_invalid')
    return item
