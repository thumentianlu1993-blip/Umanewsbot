"""马会赛前分阶段候选；沿用既有租约、调度与公开字段规则。"""
from datetime import timedelta
import hashlib
from urllib.parse import urljoin, urlsplit, urlencode
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models
from . import race_pre_race as pre
from .hkjc_sources import event_names, race_name, parse_card, parse_entries, parse_nominations, text
from .race_data_source_adapters import load_multisource_policy, fetch_source_page, canonical_sha

HKJC='hkjc_pre_race_v1'


def enabled():
    return (getattr(settings,'RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED',False) is True
        and settings.RACE_DATA_SYNC_ENABLED is True and settings.RACE_DATA_SYNC_ALLOW_NETWORK is True
        and 'hkjc' in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
        and 'hong_kong' in settings.RACE_DATA_SYNC_ENABLED_REGIONS)


def _route(event,policy):
    routes=[r for r in policy.routes if r.provider=='hkjc' and r.region=='hong_kong'
        and event.racecourse in {n for names in r.venue_aliases.values() for n in names}]
    if len(routes)!=1:raise ValueError('hkjc_route_missing')
    return routes[0]


def complete(claim, *, payload, url, page, route, now):
    from .race_pre_race_refresh import stamp_dynamic_items, material_items
    with transaction.atomic():
        event=models.RaceEvent.objects.select_for_update().get(pk=claim['event_id'])
        if claim.get('source') != HKJC or not enabled() or not route.valid(now) or not pre._valid_claim(event,claim,now):return False
        if (any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists()
            or (getattr(event, 'projection_control', None) and event.projection_control.write_owner not in {'unmanaged','data_sync'})):
            pre._finish_locked(event,claim,now,outcome_reason='manual_or_owner_lock');return False
        if pre._refs(event).get('pre_race_handoff') or event.runners.exists():
            pre._finish_locked(event,claim,now,outcome_reason='handed_off')
            return False
        if payload['stage']=='not_published':
            state=pre._state(event,HKJC);state['publication_schedule']=payload['schedule'];pre._save_state(event,HKJC,state)
            pre._finish_locked(event,claim,now,outcome_reason='not_published')
            return True
        latest=event.data_candidates.filter(source_name=HKJC,module='runners',status='pending').order_by('-fetched_at','-id').first()
        old=latest.raw_payload.get(HKJC,{}) if latest else {}
        if old.get('baseline')==pre.baseline(event) and pre.STAGES.get(old.get('stage'),-1)>pre.STAGES[payload['stage']]:
            pre._finish_locked(event,claim,now,'older_or_incomplete_source');return False
        if (old.get('baseline')==pre.baseline(event) and old.get('as_of') and payload.get('as_of')
            and old['as_of'] > payload['as_of'] and old.get('stage')==payload['stage']):
            pre._finish_locked(event,claim,now,'older_source');return False
        previous=latest.candidate_payload.get('items',[]) if latest and old.get('baseline')==pre.baseline(event) else []
        items=stamp_dynamic_items(payload['items'],previous,now=now,source_url=url,strict_roster=False,
            observed_at=getattr(page,'observed_at',None),roster_limit=500 if payload['stage']=='registration' else 60)
        content=canonical_sha(dict(stage=payload['stage'],items=material_items(items)))
        admitted=settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED and 'participants.horse_name' in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        if old.get('content_sha256')!=content or old.get('baseline')!=pre.baseline(event) or old.get('validated')!=admitted:
            models.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=HKJC,source_url=url,
                candidate_payload={**payload,'items':items},raw_payload={HKJC:dict(validated=bool(admitted),
                    baseline=pre.baseline(event),stage=payload['stage'],content_sha256=content,
                    raw_sha256=getattr(page,'raw_sha256',hashlib.sha256(str(page).encode()).hexdigest()),
                    route_digest=route.digest,as_of=payload.get('as_of',''))},fetched_at=now)
        pre._finish_locked(event,claim,now)
        return True


def fetch_hkjc_pre_race(*,event,route,now,fetcher):
    from .hkjc_sources import discover_card, course_code
    def get(url):
        if not route.permits_url(url):raise ValueError('source_url_rejected')
        return fetcher(url,route=route,now=now)
    card=discover_card(event=event,route=route,now=now,fetcher=fetcher)
    if card:
        url,page,obs=card
        return url,page,dict(stage='numbered',off_time=obs.get('off_time'),items=[dict(
            horse_name=r['horse_name'],horse_number=r['number'],barrier=r['barrier'],
            trainer_name=r['trainer_name'],jockey_name=r['jockey_name'],carried_weight=r['carried_weight'],
            running_status=r['status'],source_refs={'primary':url}) for r in obs['roster']])
    url='https://racing.hkjc.com/en-us/local/information/entries?'+urlencode(dict(
        racedate=event.local_date.strftime('%Y/%m/%d'),Racecourse=course_code(event,route),View='All'))
    page=get(url)
    try:return url,page,parse_entries(page,event=event,url=url)
    except ValueError as exc:
        if str(exc)!='not_published':raise
    # 官方国际赛站点作为策略审核入口；先读页上链接，再验证具体比赛标题及日期。
    candidates=[]
    for index in route.payload.get('discovery_urls',[]):
        if urlsplit(index).hostname!='campaigns.hkjc.com':continue
        index_page=get(index)
        links={urljoin(index,a['href']) for a in BeautifulSoup(str(index_page),'html.parser').select('a[href]')
               if urlsplit(urljoin(index,a['href'])).path.endswith('-racing-info')}
        if index.endswith('-racing-info'):links.add(index)
        if len(links)>12:raise ValueError('hkjc_campaign_links_ambiguous')
        for target in sorted(links):
            candidate_page=index_page if target==index else get(target)
            headings={race_name(text(h)) for h in BeautifulSoup(str(candidate_page),'html.parser').select('h1')}
            if headings.intersection(event_names(event)):
                candidates.append((target,candidate_page,parse_nominations(candidate_page,event=event,url=target)))
    unique={u:(u,p,v) for u,p,v in candidates}
    if len(unique)>1:raise ValueError('hkjc_nomination_ambiguous')
    if unique:return next(iter(unique.values()))
    return url,page,dict(stage='not_published',items=[],schedule='官方当前入口尚无该场完整名单')


def discover_hkjc_pre_race(*,now,policy=None,fetcher=None,clock=timezone.now):
    if not enabled():return {'checked':0,'reason':'disabled'}
    policy=policy or load_multisource_policy(now=now)
    if not policy.valid(now):raise ValueError('hkjc_policy_expired')
    fetcher=fetcher or fetch_source_page
    cache={}
    def cached(url,**kwargs):
        if url not in cache:cache[url]=fetcher(url,**kwargs)
        return cache[url]
    events=models.RaceEvent.objects.filter(country_region='hong_kong',visibility_status='published',
        status='scheduled',local_date__range=(now.date()-timedelta(days=1),now.date()+timedelta(days=61)),runners__isnull=True)
    events=sorted((e for e in events if pre.in_window(e,now) and not pre._refs(e).get('pre_race_handoff')),
        key=lambda e:(pre._state(e,HKJC).get('next_poll_at') or '',e.pk))
    checked=attempted=0
    for event in events:
        if attempted>=settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE:break
        claim=pre.claim_pre_race(event_id=event.pk,source=HKJC,now=clock())
        if not claim:continue
        attempted+=1
        try:
            route=_route(event,policy)
            url,page,payload=fetch_hkjc_pre_race(event=event,route=route,now=clock(),fetcher=cached)
            checked+=bool(complete(claim,payload=payload,url=url,page=page,route=route,now=clock()))
        except (ValueError,OSError) as exc:
            pre.finish_pre_race(claim,now=clock(),reason=str(exc)[:64],retry_after=getattr(exc,'retry_after',None))
    return dict(checked=checked,attempted=attempted)


def public_hkjc_preview(event,*,now):
    if (event.country_region!='hong_kong' or event.status!='scheduled'
        or not getattr(settings,'RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED',False)
        or not settings.RACE_DATA_SYNC_ENABLED or 'hong_kong' not in settings.RACE_DATA_SYNC_ENABLED_REGIONS
        or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        or not pre.preview_window(event,now) or event.runners.exists() or pre._refs(event).get('pre_race_handoff')
        or any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists()):return None
    control=getattr(event,'projection_control',None)
    if control and control.write_owner not in {'unmanaged','data_sync'}:return None
    candidate=event.data_candidates.filter(source_name=HKJC,module='runners',status='pending',
        raw_payload__hkjc_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:return None
    meta=candidate.raw_payload[HKJC]
    if meta.get('baseline')!=pre.baseline(event) or meta.get('stage') not in pre.STAGES:return None
    result=pre.preview_payload(event,candidate,meta['stage'],now=now)
    for row in result['rows']:
        row.source_refs={**row.source_refs,'field_units':{**row.source_refs.get('field_units',{}),'carried_weight':'lb'}}
        if row.source_refs.get('selection_status')=='reserve':row.get_running_status_display=lambda:'候补'
    return result
