"""英国 TRA Pro 取数编排；只有批准的多源 route 能触发运行时请求。"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from .uk_sources import PARSER_VERSION, name_key, parse_card, parse_result, parse_preview, supplement_numbers

BASE='https://api.theracingapi.com'


def api_url(kind,*,race_id=None,day=None,start=None,end=None,skip=0):
    if kind in {'card','result'}:
        if not isinstance(race_id,str) or not re.fullmatch(r'rac_\d+',race_id):raise ValueError('uk_race_id')
        return BASE+('/v1/racecards/'+race_id+'/pro' if kind=='card' else '/v1/results/'+race_id)
    if type(skip) is not int or not 0<=skip<=180:raise ValueError('uk_pagination_limit')
    query={'region_codes':'gb','limit':20,'skip':skip}
    if kind=='cards':query['date']=date.fromisoformat(str(day)).isoformat();path='/v1/racecards/pro'
    elif kind=='big':
        first=date.fromisoformat(str(start));last=date.fromisoformat(str(end))
        if not 0<=(last-first).days<=60:raise ValueError('uk_date_window')
        query.update(start_date=first.isoformat(),end_date=last.isoformat());path='/v1/racecards/big-races'
    else:raise ValueError('uk_endpoint')
    return BASE+path+'?'+urlencode(query)


def _runtime_json(url,*,route,now):
    import time
    from django.conf import settings
    from django.utils import timezone as django_timezone
    from .race_data_source_adapters import canonical_sha
    from .race_data_sync_providers import _fetch_json,_get_or_fetch_shared_snapshot,_ProviderSyncError
    from .race_live_source_proof import _read_secret,the_racing_api_transport
    from .race_events import ensure_race_live_host_budget_floor
    def enabled():
        return (route.valid(django_timezone.now()) and settings.RACE_DATA_SYNC_ENABLED
            and settings.RACE_DATA_SYNC_ALLOW_NETWORK
            and (settings.RACE_DATA_MULTISOURCE_APPLY_ENABLED or settings.RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED)
            and route.provider in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
            and route.region in settings.RACE_DATA_SYNC_ENABLED_REGIONS)
    if not enabled():raise ValueError('network_disabled')
    def fetch():
        if not enabled():raise ValueError('network_disabled')
        username,password=_read_secret(settings.RACE_LIVE_TRA_SECRET_ENV_FILE)
        ensure_race_live_host_budget_floor(host='api.theracingapi.com',minimum_interval_ms=2000)
        body,sha=_fetch_json(transport=the_racing_api_transport,endpoint_name='uk_paid',url=url,
            username=username,password=password,now=django_timezone.now(),clock=django_timezone.now,
            sleeper=time.sleep,allow_not_found=True)
        return {'response':body,'raw_sha256':sha,'fetched_at':django_timezone.now().isoformat()},1,1
    try:
        cached,_=_get_or_fetch_shared_snapshot(provider=route.provider,region=route.region,
            scope_key='uk-paid:'+canonical_sha(url),data_kind='result' if '/results/' in url else 'racecard',
            registry_digest=route.digest,run_id=canonical_sha({'url':url,'now':now.isoformat()}),
            now=now,proposed_requests=1,clock=django_timezone.now,sleeper=time.sleep,fetcher=fetch,waiter_max_polls=0)
    except _ProviderSyncError as exc:raise ValueError(exc.reason_code) from None
    return cached


def _request(url,*,route,now,fetcher):
    if (route.provider!='the_racing_api' or route.region!='united_kingdom'
            or route.parser_version!=PARSER_VERSION or route.source_class!='licensed_api'
            or not route.valid(now) or not route.permits_url(url)):
        raise ValueError('uk_route_rejected')
    if fetcher is None:
        value=_runtime_json(url,route=route,now=now)
        return value['response'],dict(url=url,sha256=value['raw_sha256'],fetched_at=value['fetched_at'])
    raw=fetcher(url,route=route,now=now)
    encoded=raw if isinstance(raw,bytes) else raw.encode() if isinstance(raw,str) else json.dumps(raw,sort_keys=True).encode()
    payload=json.loads(encoded)
    if not isinstance(payload,dict):raise ValueError('uk_response_schema')
    return payload,dict(url=url,sha256=getattr(raw,'raw_sha256',hashlib.sha256(encoded).hexdigest()),
        fetched_at=(getattr(raw,'observed_at',None) or now).isoformat())


def _collection(kind,*,route,now,fetcher,**kwargs):
    rows=[];documents=[];total=None
    for skip in range(0,200,20):
        url=api_url(kind,skip=skip,**kwargs);data,doc=_request(url,route=route,now=now,fetcher=fetcher);documents.append(doc)
        page=data.get('racecards');count=data.get('total')
        if (not isinstance(page,list) or type(count) is not int or not 0<=count<=200 or len(page)>20
                or total is not None and total!=count):raise ValueError('uk_pagination_contract')
        total=count;rows.extend(dict(row,_uk_source_document_url=url) for row in page)
        if len(rows)==total:
            ids=[x.get('race_id') for x in rows if isinstance(x,dict)]
            if len(ids)!=len(rows) or len(set(ids))!=len(ids):raise ValueError('uk_pagination_duplicate')
            return rows,documents
        if len(rows)>total or len(page)<20:raise ValueError('uk_pagination_incomplete')
    raise ValueError('uk_pagination_limit')


def _venue(course,route):
    keys=[k for k,aliases in route.venue_aliases.items() if course in aliases]
    if len(keys)!=1:raise ValueError('uk_venue_unreviewed')
    return keys[0]


def _select_card(event,*,route,now,fetcher):
    target=(event.source_refs or {}).get('uk_target_v1',{})
    source=event.source_identities.filter(source_key=route.provider,region_code=route.region,
        identity_namespace=route.identity_namespace).first()
    race_id=source.external_race_id if source else target.get('external_race_id')
    if race_id:
        value,document=_request(api_url('card',race_id=race_id),route=route,now=now,fetcher=fetcher)
        if value.get('_not_found'):raise ValueError('uk_bound_card_not_found')
        if value.get('race_id')!=race_id:raise ValueError('uk_bound_id_changed')
        return value,[document]
    today=now.astimezone(ZoneInfo('Europe/London')).date();offset=(event.local_date-today).days
    if 0<=offset<=7:
        choices,documents=_collection('cards',day=event.local_date,route=route,now=now,fetcher=fetcher)
    elif 7<offset<=60:
        choices,documents=_collection('big',start=today,end=today+timedelta(days=60),route=route,now=now,fetcher=fetcher)
    else:raise ValueError('awaiting_source_window')
    terms=target.get('name_keys') or [name_key(event.original_name)]
    if not terms or any(not isinstance(t,str) or len(t)<4 or t!=name_key(t) for t in terms):raise ValueError('uk_name_key')
    venue=_venue(event.racecourse,route)
    def matches(row):
        if row.get('region')!='GB' or row.get('date')!=event.local_date.isoformat():return False
        if row.get('course') not in route.venue_aliases[venue]:return False
        return any(term in name_key(row.get('race_name','')) for term in terms)
    found=[row for row in choices if matches(row)]
    if not found and 0<=offset<=7:
        choices,extra=_collection('big',start=today,end=today+timedelta(days=60),route=route,now=now,fetcher=fetcher)
        documents.extend(extra);found=[row for row in choices if matches(row)]
    if len(found)>1:raise ValueError('uk_discovery_ambiguous')
    return (found[0] if found else None),documents


def _sl_numbers(value,*,route,now,fetcher):
    from html import unescape
    if fetcher is None:
        from .race_data_source_adapters import fetch_source_page
        fetch=fetch_source_page
    else:fetch=fetcher
    def load(url):
        if not route.permits_url(url):raise ValueError('uk_supplement_url')
        raw=fetch(url,route=route,now=now)
        text=raw.decode() if isinstance(raw,bytes) else str(raw)
        match=re.search(r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>',text,re.S)
        if not match:raise ValueError('uk_sl_document')
        data=json.loads(match[1])['props']['pageProps']
        sha=getattr(raw,'raw_sha256',hashlib.sha256(text.encode()).hexdigest())
        return text,data,dict(url=url,sha256=sha,fetched_at=(getattr(raw,'observed_at',None) or now).isoformat())
    url='https://www.sportinglife.com/racing/results/'+value['local_date']
    text,index,index_doc=load(url)
    utc=datetime.fromisoformat(value['off_time']).astimezone(timezone.utc)
    candidates=[race for meeting in index['meetings'] for race in meeting['races']
        if race['date']==value['local_date'] and race['course_name']==value['course'].removesuffix(' (AW)')
        and race['time']==utc.strftime('%H:%M')]
    if len(candidates)!=1:raise ValueError('uk_sl_race_ambiguous')
    race_id=str(candidates[0]['race_summary_reference']['id'])
    links={unescape(x).split('#',1)[0] for x in re.findall(r'href="(/racing/results/[^"?]+)"',text)
        if '/'+race_id+'/' in x and x.startswith('/racing/results/'+value['local_date']+'/')}
    if len(links)!=1:raise ValueError('uk_sl_link_ambiguous')
    _,page,doc=load('https://www.sportinglife.com'+links.pop())
    return supplement_numbers(value,page['race'],source=doc),[index_doc,doc]


def _retained_numbers(value,*,event,route):
    if not value.get('gaps'):return value
    source=event.source_identities.filter(source_key=route.provider,region_code=route.region,
        identity_namespace=route.identity_namespace).first()
    old=(source.identity_fields or {}).get('multisource_v2',{}) if source else {}
    if any(old.get(k)!=value.get(k) for k in ('external_race_id','local_date')):return value
    previous={r['external_runner_id']:r for r in old.get('roster',[])}
    used={r['number'] for r in value['roster'] if r['number']}
    for row in value['roster']:
        prior=previous.get(row['external_runner_id'],{})
        number=prior.get('number','')
        if (row['number'] or row['status']!='non_runner' or not number.isdigit() or int(number)<=0
                or number in used or name_key(prior.get('horse_name',''))!=name_key(row['horse_name'])):continue
        row['number']=number;used.add(number)
        row['field_provenance']['number_source']={k:old[k] for k in ('canonical_url','raw_sha256','fetched_at')}
    value['gaps']=['non_runner_number_missing:'+r['external_runner_id'] for r in value['roster'] if not r['number']]
    return value


def fetch_payload(*,event,route,now,fetcher=None):
    if (event.country_region!='united_kingdom' or route.timezone!='Europe/London'
            or event.local_date is None):raise ValueError('uk_event_scope')
    raw,documents=_select_card(event,route=route,now=now,fetcher=fetcher)
    if raw is None:return dict(stage='not_published',roster=[],source_documents=documents)
    if raw.get('date')!=event.local_date.isoformat() or _venue(raw.get('course'),route)!=_venue(event.racecourse,route):
        raise ValueError('uk_event_identity')
    value=parse_preview(raw)
    if raw.get('race_status')=='result':
        body,doc=_request(api_url('result',race_id=raw['race_id']),route=route,now=now,fetcher=fetcher)
        if body.get('_not_found'):raise ValueError('uk_result_not_published')
        value=parse_result(body,card=raw);documents.append(doc)
        if value['gaps']:
            value,supplement=_sl_numbers(value,route=route,now=now,fetcher=fetcher);documents.extend(supplement)
    if raw.get('race_status')=='declared':value=_retained_numbers(value,event=event,route=route)
    return dict(value,source_documents=documents,primary_source_url=(api_url('result',race_id=raw['race_id']) if raw.get('race_status')=='result' else raw.get('_uk_source_document_url',documents[0]['url'])))
