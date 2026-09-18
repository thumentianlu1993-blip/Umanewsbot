"""已绑定完整赛卡的持续刷新；候选只读公开，不争用正式卡写权。"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import re
import unicodedata
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models
from . import race_pre_race as pre

WITHDRAWN = {'scratched','withdrawn','non_runner'}
HOSTS = pre.REVIEWED_HOSTS | {'www.nyra.com'}


def refresh_enabled():
    return (getattr(settings,'RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED',False) is True
        and settings.RACE_DATA_SYNC_ENABLED is True and settings.RACE_DATA_SYNC_ALLOW_NETWORK is True)


def refresh_interval(event, now):
    try: days=(event.local_date-now.astimezone(ZoneInfo(event.timezone_name)).date()).days
    except (ValueError,TypeError,KeyError): return timedelta(minutes=10)
    return timedelta(hours=3 if days>=2 else 1) if days else timedelta(minutes=10)


def _name(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC',str(value)).casefold())


def _key(row):
    return (str(row.get('horse_number') or ''), _name(row.get('horse_name','')))


def _source_id(row, default_url=''):
    refs = row.get('source_refs') or {}
    horse_id = str(refs.get('horse_id') or '')
    host = urlsplit(refs.get('primary') or default_url).hostname
    return (host, horse_id) if host and horse_id else None


def material_items(items):
    """Observation timestamps can change without a new price or roster change."""
    clocks = {'odds_observed_at','status_observed_at','odds_source_at','status_source_at'}
    return [{k:v for k,v in row.items() if k not in clocks} for row in items]


def _valid_odds(value, fmt):
    from .race_field_normalization import parse_display_odds
    if fmt == 'fractional' and re.fullmatch(r'0+(?:\.0+)?/\d+', str(value).strip()):
        return False
    return bool(value) and parse_display_odds(str(value),odds_format=fmt).state=='normalized'


def stamp_dynamic_items(items, previous, *, now, source_url, strict_roster=True, observed_at=None):
    """完整身份匹配；仅实际观测到有效字段才推进赔率时间。"""
    if not isinstance(items,list) or not 0<len(items)<=60 or not all(isinstance(r,dict) and r.get('horse_name') for r in items):
        raise ValueError('refresh_invalid_roster')
    keys=[_key(r) for r in items]
    if len(set(keys))!=len(keys): raise ValueError('refresh_duplicate_identity')
    numbers=[str(r.get('horse_number') or '') for r in items]
    if any(numbers) and (not all(numbers) or len(set(numbers))!=len(numbers)):raise ValueError('refresh_duplicate_numbers')
    old_by_key={_key(r):r for r in previous}
    old_by_id={_source_id(r):r for r in previous if _source_id(r)}
    source_ids=[_source_id(r,source_url) for r in items if _source_id(r,source_url)]
    if len(source_ids)!=len(set(source_ids)):
        raise ValueError('refresh_duplicate_source_id')
    matches=[]
    for row in items:
        identity=_source_id(row,source_url)
        old=old_by_id.get(identity) or old_by_key.get(_key(row),{})
        old_identity=_source_id(old)
        if old and identity and old_identity and identity[0]==old_identity[0] and identity!=old_identity:
            raise ValueError('refresh_source_id_changed')
        if old and old.get('horse_number') and row.get('horse_number') and str(old['horse_number'])!=str(row['horse_number']):
            raise ValueError('refresh_source_number_changed')
        matches.append(old)
    if previous and (strict_roster or all(r.get('horse_number') for r in previous)):
        if any(not r for r in matches) or {_key(r) for r in matches}!=set(old_by_key):
            raise ValueError('refresh_roster_identity_changed')
    result=[]
    for index,row in enumerate(items,1):
        row=deepcopy(row);old=matches[index-1]
        status=row.get('running_status') or old.get('running_status') or 'declared'
        if status not in WITHDRAWN|{'declared','reinstated'}:raise ValueError('refresh_unknown_status')
        status_time=pre._dt(row.get('status_source_at'))
        if old.get('running_status') in WITHDRAWN and status not in WITHDRAWN:
            previous_time=pre._dt(old.get('status_observed_at'))
            if status!='reinstated' or not status_time or not previous_time or not previous_time<status_time<=now:
                status=old['running_status']
        row['running_status']=status
        row['status_observed_at']=(status_time or now).isoformat() if status!=old.get('running_status') else old.get('status_observed_at',now.isoformat())
        fmt=row.get('odds_format','')
        observed=pre._dt(row.get('odds_source_at')) if row.get('odds_source_at') else (observed_at or now)
        price_valid=(_valid_odds(row.get('odds_value'),fmt) and row.get('odds_kind') in {'current','morning_line','forecast'} and observed and observed<=now)
        old_observed=pre._dt(old.get('odds_observed_at'))
        if price_valid and (not old_observed or observed>=old_observed):
            row['odds_observed_at']=observed.isoformat()
        else:
            same_source = (old.get('source_refs') or {}).get('primary', source_url) == source_url
            for key in ('odds_value','odds_kind','odds_format','odds_observed_at','odds_source_at','popularity'):
                row[key]=old.get(key,'') if same_source else ''
        if not str(row.get('popularity','')).isdigit() or int(row.get('popularity') or 0)<=0:row['popularity']=''
        row['sort_order']=index
        row['source_refs']={**(row.get('source_refs') or {}),'primary':source_url,
            'field_units':{**(row.get('source_refs',{}).get('field_units') or {}),'odds_value':row.get('odds_format','')}}
        result.append(row)
    return result


def dynamic_rows(event, items, *, now):
    admitted=set(settings.RACE_DATA_SYNC_ENABLED_FIELDS);rows=[]
    for item in items:
        fields={k: item.get(k,'') if v in admitted else '' for k,v in pre.PUBLIC_FIELDS.items()}
        observed=pre._dt(item.get('odds_observed_at'))
        fresh=observed and observed<=now and now-observed<=refresh_interval(event,now)+timedelta(minutes=10)
        if not fresh or item.get('running_status') in WITHDRAWN:
            fields.update(odds_value='',popularity='')
        status=fields.get('running_status')
        label={'declared':'已出走登记','reinstated':'恢复出走','scratched':'退赛','withdrawn':'退赛','non_runner':'退赛'}.get(status,'—')
        rows.append(SimpleNamespace(**fields,sort_order=item.get('sort_order',0),pk=item.get('sort_order',0),
            source_refs=item.get('source_refs',{}),odds_kind_label={'current':'即时','morning_line':'晨间','forecast':'预测'}.get(item.get('odds_kind'),'') if fields['odds_value'] else '',
            get_running_status_display=lambda label=label:label))
    return rows


def validate_bound_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443) or p.fragment:
        raise ValueError('refresh_source_url_rejected')
    patterns={
        'www.sportinglife.com':r'/racing/racecards/\d{4}-\d{2}-\d{2}/[a-z0-9-]+/racecard/[1-9]\d*/[a-z0-9-]+/?',
        'www.zeturf.fr':r'/fr/course-du-jour/\d{4}-\d{2}-\d{2}/R[1-9]\d*C[1-9]\d*-[a-z0-9-]+/?',
        'www.racingpost.com':r'/racecards/[1-9]\d*/[a-z0-9-]+/\d{4}-\d{2}-\d{2}/[1-9]\d*/?',
    }
    if p.hostname in patterns:
        if not re.fullmatch(patterns[p.hostname],p.path) or p.query:raise ValueError('refresh_source_path_rejected')
    elif p.hostname=='www.nyra.com':
        q=parse_qs(p.query)
        if p.path!='/belmont/racing/entries/' or set(q)!={'day','limit','race'} or q['limit']!=['entries'] or len(q['day'])!=1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',q['day'][0]) or len(q['race'])!=1 or not re.fullmatch(r'[1-9]\d?',q['race'][0]):raise ValueError('refresh_source_path_rejected')
    else:
        q=parse_qs(p.query)
        if p.path!='/KeibaWeb/TodayRaceInfo/DebaTable' or set(q)!={'k_babaCode','k_raceDate','k_raceNo'} or any(len(v)!=1 for v in q.values()) or not re.fullmatch(r'\d{4}/\d{2}/\d{2}',q['k_raceDate'][0]) or not q['k_babaCode'][0].isdigit() or not q['k_raceNo'][0].isdigit():raise ValueError('refresh_source_path_rejected')
    return p


def _eligible(event,now):
    control=getattr(event,'projection_control',None)
    enrollment=getattr(event,'race_data_sync_enrollment',None)
    region='japan_nar' if event.country_region=='japan' else event.country_region
    return (pre.in_window(event,now) and region in settings.RACE_DATA_SYNC_ENABLED_REGIONS
        and not pre._refs(event).get('pre_race_handoff') and not event.runners.exists()
        and (not control or control.write_owner=='unmanaged') and (not enrollment or enrollment.state!='enrolled')
        and not any((event.manual_lock_flags or {}).values()) and not event.field_authorities.filter(manual_lock=True).exists()
        and not models.RaceEventLifecycleControl.objects.filter(event=event).exists())


def _reviewed(event):
    candidate=event.data_candidates.filter(source_name=pre.REVIEWED_PRE_RACE,module='runners',status='pending',
        raw_payload__reviewed_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:return None
    meta=candidate.raw_payload[pre.REVIEWED_PRE_RACE]
    items=candidate.candidate_payload.get('items',[])
    if (meta.get('baseline')!=pre.baseline(event) or meta.get('stage')!='numbered' or meta.get('authority') not in {'human_reviewed_reference','human_reviewed_official'}
        or not items or meta.get('row_count')!=len(items) or _digest(items)!=meta.get('items_sha256')):return None
    return candidate


def binding_for(event):
    candidate=_reviewed(event)
    if not candidate:return None
    binding=pre._refs(event).get('pre_race_refresh_binding')
    if binding:
        if binding.get('baseline')!=pre.baseline(event) or binding.get('reviewed_candidate_id')!=candidate.pk:return None
        url=binding.get('url','')
    else:
        url=candidate.source_url
    validate_bound_url(url)
    return {'url':url,'reviewed_candidate_id':candidate.pk,'baseline':pre.baseline(event)}


def _digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _snapshot_valid(candidate, event):
    meta = candidate.raw_payload.get(pre.REFRESH, {})
    binding = meta.get('binding') or {}
    items = candidate.candidate_payload.get('items', [])
    try:
        validate_bound_url(candidate.source_url)
    except ValueError:
        return False
    return (meta.get('baseline') == pre.baseline(event)
        and binding.get('baseline') == pre.baseline(event)
        and binding.get('url') == candidate.source_url
        and meta.get('authority') == 'automatic_parsed'
        and meta.get('stage') == 'numbered' and bool(items)
        and meta.get('row_count') == len(items) and meta.get('items_sha256') == _digest(items))


def complete_refresh(claim,*,html,url,now):
    if not refresh_enabled():
        pre.cancel_pre_race_claim(claim)
        return False
    from .race_pre_race_sources import parse_bound_card
    with transaction.atomic():
        models.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=claim['event_id']).first()
        event=models.RaceEvent.objects.select_for_update().get(pk=claim['event_id'])
        if not pre._valid_claim(event,claim,now) or not refresh_enabled() or not _eligible(event,now):return False
        binding=binding_for(event)
        if not binding or binding!=claim.get('binding') or binding['url']!=url:return False
        original=_reviewed(event)
        previous=event.data_candidates.filter(source_name=pre.REFRESH,module='runners',status='pending').order_by('-fetched_at','-id').first()
        if previous and previous.raw_payload.get(pre.REFRESH,{}).get('baseline') != pre.baseline(event):
            previous = None
        if previous and (previous.fetched_at>now or not _snapshot_valid(previous,event)):
            raise ValueError('refresh_snapshot_or_clock_invalid')
        payload=parse_bound_card(html,event=event,url=url)
        # A bound identity never silently replaces a different set of starters.
        items=stamp_dynamic_items(payload['items'],(previous or original).candidate_payload['items'],now=now,source_url=url,observed_at=getattr(html,'observed_at',None))
        admitted=settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED and 'participants.horse_name' in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        meta=dict(validated=bool(admitted),baseline=pre.baseline(event),binding=binding,stage='numbered',authority='automatic_parsed',
            row_count=len(items),items_sha256=_digest(items),source_sha256=getattr(html,'raw_sha256',hashlib.sha256(html.encode()).hexdigest()))
        if not refresh_enabled():return False
        if not previous or previous.candidate_payload.get('items')!=items or previous.raw_payload[pre.REFRESH].get('validated')!=bool(admitted):
            models.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=pre.REFRESH,source_url=url,
                candidate_payload={'items':items},raw_payload={pre.REFRESH:meta},fetched_at=now)
            if not previous or material_items(previous.candidate_payload['items'])!=material_items(items) or previous.source_url!=url:
                state=pre._state(event,pre.REFRESH);state['last_changed_at']=now.isoformat();pre._save_state(event,pre.REFRESH,state)
        pre._finish_locked(event,claim,now)
        return True


def public_refresh_preview(event,*,now):
    # Read the last valid card while a newly managed event waits for its formal card.
    # A source-binding edit changes future writes, not the identity of this snapshot.
    control = getattr(event,'projection_control',None)
    region = 'japan_nar' if event.country_region == 'japan' else event.country_region
    if (not settings.RACE_DATA_SYNC_ENABLED or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED
        or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        or region not in settings.RACE_DATA_SYNC_ENABLED_REGIONS or not pre.in_window(event,now)
        or pre._refs(event).get('pre_race_handoff') or event.runners.exists()
        or any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists()
        or (control and control.write_owner not in {'unmanaged','data_sync'})):return None
    candidate=event.data_candidates.filter(source_name=pre.REFRESH,module='runners',status='pending',raw_payload__pre_race_refresh_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:return None
    if candidate.fetched_at>now or not _snapshot_valid(candidate,event):return None
    return pre.preview_payload(event,candidate,'numbered',now=now)


def fetch_bound_html(url,*,now,region):
    host=validate_bound_url(url).hostname
    provider={'www.nyra.com':'nyra','www.sportinglife.com':'sporting_life',
        'www.zeturf.fr':'zeturf','www.racingpost.com':'racing_post','www.keiba.go.jp':'nar'}[host]
    return pre._fetch_bounded_html(url,now=now,provider=provider,region=region,validator=validate_bound_url,enabled=refresh_enabled)


def discover_bound_pre_race(*,now,fetcher=None,clock=timezone.now):
    if not refresh_enabled():return {'checked':0,'reason':'disabled'}
    fetcher=fetcher or fetch_bound_html;checked=attempted=0
    events=models.RaceEvent.objects.filter(visibility_status='published',status='scheduled',
        local_date__gte=now.date()-timedelta(days=1),local_date__lte=now.date()+timedelta(days=5),
        data_candidates__source_name=pre.REVIEWED_PRE_RACE).distinct()
    events=sorted((e for e in events if _eligible(e,now)),key=lambda e:(pre._state(e,pre.REFRESH).get('next_poll_at') or '',e.pk))
    for event in events:
        if attempted>=settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE:break
        claim=pre.claim_pre_race(event_id=event.pk,source=pre.REFRESH,now=clock())
        if not claim:continue
        attempted+=1
        try:
            claim['binding']=binding_for(event)
            if not claim['binding']:raise ValueError('refresh_source_binding_missing')
            url=claim['binding']['url']
            region='japan_nar' if event.country_region=='japan' else event.country_region
            html=fetcher(url,now=clock(),region=region)
            if complete_refresh(claim,html=html,url=url,now=clock()):checked+=1
            else:pre.finish_pre_race(claim,now=clock(),reason='refresh_commit_not_admitted')
        except (ValueError,OSError) as exc:
            # Parser diagnostics are bounded codes, never arbitrary HTML or response data.
            reason=str(exc) if re.fullmatch(r'[a-z0-9_]{1,80}',str(exc)) else 'refresh_source_parse_failed'
            pre.finish_pre_race(claim,now=clock(),reason=reason,retry_after=getattr(exc,'retry_after',None))
    return {'checked':checked,'attempted':attempted}
