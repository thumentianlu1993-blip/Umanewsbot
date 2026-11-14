"""NAR 专题名单的分阶段刷新；未发布页与注释样例不生成参赛马。"""
from datetime import timedelta
import hashlib
import re
from urllib.parse import urlsplit, urljoin
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models
from . import race_pre_race as pre
from .japan_source_discovery import nar_topic_document, nar_topic_card
from .race_data_source_adapters import load_multisource_policy, fetch_source_page, parse_nar_observation, canonical_sha

NAR = 'nar_pre_race_v1'


def enabled():
    return (getattr(settings, 'RACE_DATA_SYNC_NAR_PRE_RACE_ENABLED', False) is True
        and settings.RACE_DATA_SYNC_ENABLED is True and settings.RACE_DATA_SYNC_ALLOW_NETWORK is True
        and 'nar' in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
        and 'japan_nar' in settings.RACE_DATA_SYNC_ENABLED_REGIONS)


def parse_nar_nominations(page, *, event, url):
    path=urlsplit(url)
    match=re.fullmatch(r'/dirtgraderace/(\d{4})/(\d{4})_[^/]+/racecard.html',path.path)
    if (path.scheme!='https' or path.netloc!='www.keiba.go.jp' or path.query or path.fragment
        or not match or match[1]+match[2]!=event.local_date.strftime('%Y%m%d')):
        raise ValueError('nar_topic_identity_mismatch')
    soup=BeautifulSoup(str(page),'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    if event.original_name not in title or str(event.local_date.year)+'年' not in title:
        raise ValueError('nar_topic_title_mismatch')
    items=[]
    for section in soup.select('.sec_nominate'):
        heading=section.find(['h2','h3'])
        selection=heading.get_text(' ',strip=True) if heading else ''
        if not re.search('選定|出走予定|補欠|予備',selection):raise ValueError('nar_selection_unknown')
        for table in section.select('table'):
            rows=table.select('tr')
            if not rows:raise ValueError('nar_nomination_partial')
            headers=[c.get_text(' ',strip=True) for c in rows[0].find_all(['td','th'],recursive=False)]
            if not {'馬名','調教師'}.issubset(headers) or len(headers)!=len(set(headers)):
                raise ValueError('nar_nomination_headers')
            for row in rows[1:]:
                cells=[c.get_text(' ',strip=True) for c in row.find_all(['td','th'],recursive=False)]
                if len(cells)!=len(headers):raise ValueError('nar_nomination_partial')
                fields=dict(zip(headers,cells));name=fields['馬名']
                if not name or re.search('バメイ|●|サンプル',name):raise ValueError('nar_nomination_placeholder')
                def known(value):return '' if value in {'-','－','未定','未発表',''} else value
                weight=known(fields.get('斤量',''))
                if weight and not re.fullmatch(r'\d{2}(?:\.\d)?',weight):raise ValueError('nar_nomination_weight')
                jockey=known(fields.get('予定騎手',fields.get('騎乗予定騎手','')))
                items.append(dict(horse_name=name,horse_number='',barrier='',
                    trainer_name=known(fields['調教師']),jockey_name=jockey,carried_weight=weight,
                    running_status='declared',source_refs={'primary':url,'selection_status':selection,
                        'jockey_stage':'planned','source_fields':fields}))
    if items:
        # 报名包含补欠马，不适用正式出马表人数上限；完整保留各组选定状态。
        if len({r['horse_name'] for r in items})!=len(items):raise ValueError('nar_nomination_roster')
        return dict(stage='registration',items=items)
    schedule=' '.join(n.get_text(' ',strip=True) for n in soup.select('.txt_schedule'))
    if schedule and re.search('発表|公開',schedule):
        return dict(stage='not_published',items=[],schedule=schedule)
    raise ValueError('nar_nomination_not_available')


def _route(event, policy):
    from .race_source_identity import normalize_name
    routes=[r for r in policy.routes if r.provider=='nar' and r.region=='japan_nar'
        and normalize_name(event.racecourse) in {normalize_name(n) for names in r.venue_aliases.values() for n in names}]
    if len(routes)!=1:raise ValueError('nar_route_missing')
    return routes[0]


def complete(claim, *, payload, url, page, route, now):
    from .race_pre_race_refresh import stamp_dynamic_items, material_items
    with transaction.atomic():
        event=models.RaceEvent.objects.select_for_update().get(pk=claim['event_id'])
        if not enabled() or not route.valid(now) or not pre._valid_claim(event,claim,now):return False
        if pre._refs(event).get('pre_race_handoff') or event.runners.exists():
            pre._finish_locked(event,claim,now,outcome_reason='handed_off')
            return False
        if payload['stage']=='not_published':
            state=pre._state(event,NAR);state['publication_schedule']=payload['schedule'];pre._save_state(event,NAR,state)
            pre._finish_locked(event,claim,now,outcome_reason='not_published')
            return True
        latest=event.data_candidates.filter(source_name=NAR,module='runners',status='pending').order_by('-fetched_at','-id').first()
        old=latest.raw_payload.get(NAR,{}) if latest else {}
        if old.get('baseline')==pre.baseline(event) and pre.STAGES.get(old.get('stage'),-1)>pre.STAGES[payload['stage']]:
            pre._finish_locked(event,claim,now,'older_or_incomplete_source');return False
        previous=latest.candidate_payload.get('items',[]) if latest and old.get('baseline')==pre.baseline(event) else []
        items=stamp_dynamic_items(payload['items'],previous,now=now,source_url=url,strict_roster=False,
            observed_at=getattr(page,'observed_at',None),
            roster_limit=len(payload['items']) if payload['stage']=='registration' else 60)
        content=canonical_sha(dict(stage=payload['stage'],items=material_items(items)))
        admitted=settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED and 'participants.horse_name' in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        if old.get('content_sha256')!=content or old.get('baseline')!=pre.baseline(event) or old.get('validated')!=admitted:
            models.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=NAR,source_url=url,
                candidate_payload={**payload,'items':items},raw_payload={NAR:dict(validated=bool(admitted),
                    baseline=pre.baseline(event),stage=payload['stage'],content_sha256=content,
                    raw_sha256=getattr(page,'raw_sha256',hashlib.sha256(str(page).encode()).hexdigest()),
                    route_digest=route.digest)},fetched_at=now)
        pre._finish_locked(event,claim,now)
        return True


def fetch_nar_pre_race(*, event, route, now, fetcher):
    from .race_source_identity import normalize_name
    from .japan_source_discovery import unique
    refs=pre._refs(event)
    direct=[refs.get(k,'') for k in ('detail','primary')
            if urlsplit(refs.get(k,'')).path in {
                '/KeibaWeb/TodayRaceInfo/DebaTable','/KeibaWeb/TodayRaceInfo/RaceList'}]
    if direct:
        cards=[u for u in direct if urlsplit(u).path.endswith('/DebaTable')]
        url=unique(cards or direct)
        if not route.permits_url(url):raise ValueError('source_url_rejected')
        page=fetcher(url,route=route,now=now)
        if urlsplit(url).path.endswith('/RaceList'):
            names={normalize_name(n) for n in (event.original_name,event.chinese_name,
                *event.aliases.values_list('text',flat=True)) if n}
            links=[]
            for a in BeautifulSoup(str(page),'html.parser').select('a[href]'):
                target=urljoin(url,a['href'])
                if urlsplit(target).path.endswith('/DebaTable') and normalize_name(re.split(r'Jpn[I123]+|G[I123]+', a.get_text(' ',strip=True), maxsplit=1)[0]) in names:
                    links.append(target)
            url=unique(links)
            if not route.permits_url(url):raise ValueError('source_url_rejected')
            page=fetcher(url,route=route,now=now)
    else:
        url,page=nar_topic_document(event=event,route=route,now=now,fetcher=fetcher)
        try:card=nar_topic_card(page,url=url,event=event)
        except ValueError as exc:
            if str(exc)!='not_published':raise
            return url,page,parse_nar_nominations(page,event=event,url=url)
        if not route.permits_url(card):raise ValueError('source_url_rejected')
        url=card;page=fetcher(url,route=route,now=now)
    obs=parse_nar_observation(page,url=url,route=route,now=now)
    names={normalize_name(n) for n in (event.original_name,event.chinese_name,
        *event.aliases.values_list('text',flat=True)) if n}
    venues={normalize_name(n) for n in route.venue_aliases.get(obs['venue_key'],[])}
    if (obs['local_date']!=event.local_date.isoformat() or normalize_name(event.racecourse) not in venues
        or not names.intersection(normalize_name(n) for n in obs['raw_names']) or obs.get('result_phase')):
        raise ValueError('nar_pre_race_identity_mismatch')
    payload=dict(stage='numbered',off_time=obs.get('off_time'),items=[dict(horse_name=r['horse_name'],
        horse_number=r['number'],barrier=r['barrier'],trainer_name=r['trainer_name'],jockey_name=r['jockey_name'],
        carried_weight=r['carried_weight'],running_status=r['status']) for r in obs['roster']])
    return url,page,payload


def discover_nar_pre_race(*, now, policy=None, fetcher=None, clock=timezone.now):
    if not enabled():return {'checked':0,'reason':'disabled'}
    policy=policy or load_multisource_policy(now=now)
    if not policy.valid(now):raise ValueError('nar_policy_expired')
    fetcher=fetcher or fetch_source_page
    cache={}
    def cached(url,**kwargs):
        if url not in cache:cache[url]=fetcher(url,**kwargs)
        return cache[url]
    events=models.RaceEvent.objects.filter(country_region='japan',visibility_status='published',status='scheduled',
        local_date__range=(now.date()-timedelta(days=1),now.date()+timedelta(days=32))).exclude(racecourse__in=pre.JRA_COURSES).filter(runners__isnull=True)
    events=sorted((e for e in events if pre.in_window(e,now) and not pre._refs(e).get('pre_race_handoff')),key=lambda e:(pre._state(e,NAR).get('next_poll_at') or '',e.pk))
    attempted=checked=0
    for event in events:
        if attempted>=settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE:break
        claim=pre.claim_pre_race(event_id=event.pk,source=NAR,now=clock())
        if not claim:continue
        attempted+=1
        try:
            route=_route(event,policy)
            url,page,payload=fetch_nar_pre_race(event=event,route=route,now=clock(),fetcher=cached)
            checked+=bool(complete(claim,payload=payload,url=url,page=page,route=route,now=clock()))
        except (ValueError,OSError) as exc:
            pre.finish_pre_race(claim,now=clock(),reason=str(exc)[:64],retry_after=getattr(exc,'retry_after',None))
    return dict(checked=checked,attempted=attempted)


def public_nar_preview(event, *, now):
    if (not settings.RACE_DATA_SYNC_ENABLED or 'japan_nar' not in settings.RACE_DATA_SYNC_ENABLED_REGIONS
        or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        or not pre.preview_window(event,now) or event.runners.exists() or pre._refs(event).get('pre_race_handoff')
        or any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists()):return None
    control=getattr(event,'projection_control',None)
    if control and control.write_owner not in {'unmanaged','data_sync'}:return None
    candidate=event.data_candidates.filter(source_name=NAR,module='runners',status='pending',
        raw_payload__nar_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:return None
    meta=candidate.raw_payload[NAR]
    if meta.get('baseline')!=pre.baseline(event) or meta.get('stage') not in pre.STAGES:return None
    result=pre.preview_payload(event,candidate,meta['stage'],now=now)
    if meta['stage']=='registration':
        result['label']='预计参赛名单（骑手为预定）'
        for row in result['rows']:
            selection=(row.source_refs or {}).get('selection_status','')
            row.public_nar_selection_status='候补' if re.search('補欠|予備',selection) else '选定'
            row.get_running_status_display=lambda label=row.public_nar_selection_status:label
    return result
