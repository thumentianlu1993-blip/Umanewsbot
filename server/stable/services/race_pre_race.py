"""Bounded pre-race discovery and official JRA preview; never creates runners."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import hashlib
import json
import re
import secrets
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit, parse_qs
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable import models
from .race_data_sync_policy import calculate_next_poll_at

JRA = 'jra_pre_race_v1'
TRA = 'tra_identity'
REFRESH = 'pre_race_refresh_v1'
INDEX_URL = 'https://www.jra.go.jp/keiba/thisweek/'
CARD_INDEX_URL = 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dli00/F3'
REGISTRATION_INDEX_URL = 'https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03trl00/29'
SOURCE_DIGEST = hashlib.sha256(b'jra-pre-race-v1:https://www.jra.go.jp:official-preview-only').hexdigest()
STAGES = {'registration': 0, 'declared': 1, 'numbered': 2}
JRA_COURSES = frozenset(('札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉'))
PUBLIC_FIELDS = {'horse_name':'participants.horse_name', 'horse_number':'participants.number',
    'barrier':'participants.draw', 'trainer_name':'participants.trainer_name',
    'jockey_name':'participants.jockey_name', 'carried_weight':'participants.carried_weight',
    'odds_value':'participants.odds', 'popularity':'participants.popularity', 'running_status':'participants.status'}
LABELS = {'registration': '报名名单', 'declared': '参赛名单，马号待公布', 'numbered': '出马表'}


def _iso(value):
    return value.isoformat() if value is not None else None


def _dt(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if timezone.is_aware(parsed) else None
    except (TypeError, ValueError):
        return None


def baseline(event):
    return {'event_id': event.pk, 'date': _iso(event.local_date), 'name': event.original_name,
            'course': event.racecourse, 'timezone': event.timezone_name}


def jra_enabled(*, network=False):
    return (getattr(settings, 'RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED', False) is True
        and settings.RACE_DATA_SYNC_ENABLED is True
        and bool({'japan', 'japan_jra'} & set(settings.RACE_DATA_SYNC_ENABLED_REGIONS))
        and (not network or settings.RACE_DATA_SYNC_ALLOW_NETWORK is True))


def in_window(event, now):
    if event.visibility_status != 'published' or event.status != 'scheduled' or not event.local_date:
        return False
    try:
        today = now.astimezone(ZoneInfo(event.timezone_name)).date()
    except (ValueError, KeyError):
        return False
    return (0 <= (event.local_date-today).days <= pre_race_days(event)
        and (event.race_datetime is None or now < event.race_datetime+timedelta(minutes=5)))


def preview_window(event,now):
    if not getattr(settings,'RACE_DATA_MULTISOURCE_APPLY_ENABLED',False):return in_window(event,now)
    if event.visibility_status!='published' or event.status in ('cancelled','postponed') or not event.local_date:return False
    try:return (event.local_date-now.astimezone(ZoneInfo(event.timezone_name)).date()).days<=pre_race_days(event)
    except (ValueError,KeyError):return False


def pre_race_days(event):
    if event.country_region == 'japan':
        return max(0, min(31, getattr(settings, 'RACE_DATA_SYNC_JAPAN_PRE_RACE_DAYS', 4)))
    if event.country_region == 'hong_kong' and getattr(settings, 'RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED', False):
        return max(0, min(60, getattr(settings, 'RACE_DATA_SYNC_HKJC_PRE_RACE_DAYS', 45)))
    return 4


def _refs(event):
    return dict(event.source_refs) if isinstance(event.source_refs, dict) else {}


def _state(event, source):
    checks = _refs(event).get('pre_race_checks', {})
    value = checks.get(source, {}) if isinstance(checks, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _save_state(event, source, state):
    refs = _refs(event)
    checks = dict(refs.get('pre_race_checks') or {})
    checks[source] = state
    refs['pre_race_checks'] = checks
    event.source_refs = refs
    event.save(update_fields=['source_refs', 'updated_at'])


def claim_pre_race(*, event_id, source, now):
    if source not in {JRA, TRA, REFRESH, 'nar_pre_race_v1', 'hkjc_pre_race_v1'} or timezone.is_naive(now):
        raise ValueError('invalid_pre_race_claim')
    if source == JRA and not jra_enabled(network=True):
        return None
    if source == 'nar_pre_race_v1':
        from .nar_pre_race import enabled
        if not enabled(): return None
    if source == 'hkjc_pre_race_v1':
        from .hkjc_pre_race import enabled
        if not enabled(): return None
    if source == REFRESH:
        from .race_pre_race_refresh import refresh_enabled
        if not refresh_enabled(): return None
    with transaction.atomic():
        event = models.RaceEvent.objects.select_for_update().get(pk=event_id)
        if not in_window(event, now) or (source == JRA and (
            event.country_region != 'japan' or event.racecourse not in JRA_COURSES or
            _refs(event).get('pre_race_handoff'))):
            return None
        if source == 'nar_pre_race_v1' and (event.country_region != 'japan' or event.racecourse in JRA_COURSES or _refs(event).get('pre_race_handoff') or event.runners.exists()):
            return None
        if source == 'hkjc_pre_race_v1' and (event.country_region != 'hong_kong' or _refs(event).get('pre_race_handoff') or event.runners.exists()):
            return None
        state = _state(event, source)
        lease = _dt(state.get('lease_until'))
        due = _dt(state.get('next_poll_at'))
        if lease and lease > now:
            return None
        if state.get('baseline') == baseline(event) and due and due > now:
            return None
        token = secrets.token_hex(16)
        state.update(lease_token=token, lease_until=_iso(now+timedelta(seconds=120)),
                     last_attempt_at=_iso(now), baseline=baseline(event))
        _save_state(event, source, state)
        return {'event_id': event.pk, 'source': source, 'token': token, 'baseline': baseline(event)}


def _valid_claim(event, claim, now):
    state = _state(event, claim['source'])
    expires = _dt(state.get('lease_until'))
    return (state.get('lease_token') == claim['token'] and expires and expires > now
            and baseline(event) == claim['baseline'] and in_window(event, now))


def _finish_locked(event, claim, now, reason='', retry_after=None, outcome_reason=''):
    state = _state(event, claim['source'])
    # Existing Beat slots are 7/17/27/37/47/57. Worker or prior-source delay must
    # not move the next due beyond the following slot.
    def slot(value):
        return value.replace(second=0, microsecond=0)-timedelta(minutes=(value.minute-7)%10)
    anchor = slot(_dt(state.get('last_attempt_at')) or now)
    due = calculate_next_poll_at(data_kind='racecard', now=anchor, race_datetime=event.race_datetime,
                                local_date=event.local_date, timezone_name=event.timezone_name)
    if (pre_race_days(event) > 4 and event.local_date and
        (event.local_date-now.astimezone(ZoneInfo(event.timezone_name)).date()).days > 4):
        due = min(due or now+timedelta(hours=3), now+timedelta(hours=3))
    if due is not None and due <= now:
        due = calculate_next_poll_at(data_kind='racecard', now=now,
            race_datetime=event.race_datetime, local_date=event.local_date, timezone_name=event.timezone_name)
        if due is not None and slot(due)>now:
            due=slot(due)
    if reason:
        failures = min(int(state.get('failures', 0))+1, 8)
        due = max(now+timedelta(minutes=min(180, 5 * 2**(failures-1))), retry_after or now)
        state['failures'] = failures
    else:
        state.update(last_success_at=_iso(now), last_checked_at=_iso(now), failures=0)
    state.update(next_poll_at=_iso(due), lease_token='', lease_until=None, reason=reason or outcome_reason)
    _save_state(event, claim['source'], state)


def finish_pre_race(claim, *, now, reason='', retry_after=None, outcome_reason=''):
    with transaction.atomic():
        event = models.RaceEvent.objects.select_for_update().get(pk=claim['event_id'])
        if not _valid_claim(event, claim, now):
            return False
        _finish_locked(event, claim, now, reason, retry_after, outcome_reason)
        return True


def validate_url(url, *, index=False):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'www.jra.go.jp' or parsed.fragment:
        raise ValueError('jra_pre_race_url_rejected')
    if index and url in {INDEX_URL, CARD_INDEX_URL, REGISTRATION_INDEX_URL}:
        return
    if index and parsed.path == '/JRADB/accessD.html' and re.fullmatch(
            r'CNAME=pw01drl(?:00|10)\d{18}/[0-9A-F]{2}', parsed.query):
        return
    query = parse_qs(parsed.query)
    patterns = {'/JRADB/accessD.html': r'pw01dde(?:01|10)\d{20}/[0-9A-F]{2}',
                '/JRADB/accessT.html': r'pw03tde00\d{16}/[0-9A-F]{2}'}
    if (parsed.path not in patterns or set(query) != {'CNAME'} or len(query['CNAME']) != 1
        or not re.fullmatch(patterns[parsed.path], query['CNAME'][0])):
        raise ValueError('jra_pre_race_url_rejected')


def _text(node):
    return node.get_text(' ', strip=True) if node else ''


_JRA_GRADE_PREFIX = re.compile(r'^(?:(?:J・)?G|Jpn)[ⅠⅡⅢ]')
_JRA_LONG_SUFFIXES = (('ステークス', 'S'), ('カップ', 'C'), ('トロフィー', 'T'), ('フィリーズ', 'F'))


def normalize_jra_race_name(name):
    """JRA 官方名称的确定性归一：去空白与等级前缀，长后缀ステークス/カップ/トロフィー/フィリーズ转为 S/C/T/F。"""
    value = re.sub(r'\s+', '', name or '')
    value = _JRA_GRADE_PREFIX.sub('', value)
    value = re.sub(r'[（(\[［](?:混合|国際|指定|特指|牝|見習騎手)[）)\]］]', '', value)
    for long, short in _JRA_LONG_SUFFIXES:
        if value.endswith(long) and len(value) > len(long):
            value = value[:-len(long)] + short
            break
    return value


def jra_document_links(html, *, base_url=INDEX_URL):
    """从href或官网doAction提取真实参数，不生成或猜测校验后缀。"""
    from urllib.parse import urlencode
    soup = BeautifulSoup(str(html), 'html.parser')
    for anchor in soup.select('a'):
        action = re.search(r"doAction\(\s*['\"](/JRADB/access[DST]\.html)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
                           anchor.get('onclick', ''))
        if action:
            target = urljoin(base_url, action[1]) + '?' + urlencode({'CNAME': action[2]}, safe='/')
        else:
            target = urljoin(base_url, anchor.get('href', ''))
        yield anchor, target


def jra_pre_race_links(html, *, event):
    from .race_data_source_adapters import jra_cname_identity, _JRA_VENUE_CODES
    names = {normalize_jra_race_name(n) for n in (event.original_name, event.chinese_name,
             *event.aliases.values_list('text', flat=True)) if n}
    candidates, exact, exact_times = [], [], {}
    for anchor, url in jra_document_links(html):
        try:
            validate_url(url)
            if urlsplit(url).path.endswith('accessT.html'):
                match = re.fullmatch(r'pw03tde00(\d{2})\d{6}(\d{8})/[0-9A-F]{2}', parse_qs(urlsplit(url).query)['CNAME'][0])
                venue, day = _JRA_VENUE_CODES.get(match[1]), match[2]
            else:
                match = jra_cname_identity(url)
                venue, day = _JRA_VENUE_CODES.get(match[2]), match[7]
        except (ValueError, KeyError, TypeError):
            continue
        if venue != event.racecourse or day != event.local_date.strftime('%Y%m%d'):
            continue
        if url not in candidates:
            candidates.append(url)
        label = ''.join(str(n) for n in anchor.contents if isinstance(n, str)).strip()
        row = anchor.find_parent('tr')
        row_name = row.select_one('.race_name .stakes') or row.select_one('.race_name') if row else None
        if row_name is not None:
            label = row_name.get_text(' ', strip=True)
        if normalize_jra_race_name(label) in names and url not in exact:
            exact.append(url)
            clock = re.search(r'(\d{1,2})時(\d{1,2})分', _text(row.select_one('.time'))) if row else None
            if clock:
                exact_times[url] = time(*map(int, clock.groups()))
    if len(exact) > 1:
        known_time = getattr(event, 'local_start_time', None)
        if known_time is None and getattr(event, 'race_datetime', None):
            known_time = event.race_datetime.astimezone(ZoneInfo('Asia/Tokyo')).time()
        if known_time is not None:
            matched = [u for u in exact if exact_times.get(u) == known_time]
            if len(matched) == 1:
                return matched
        raise ValueError('jra_race_identity_ambiguous')
    return exact or candidates


def parse_jra_card(html, *, event, url):
    validate_url(url)
    lowered = html.lower().strip()
    if (not lowered.endswith('</html>') or '</body>' not in lowered or
        any(len(re.findall(r'<'+tag+r'(?:\s|>)', lowered)) != lowered.count('</'+tag+'>')
            for tag in ('table', 'tbody', 'tr'))):
        raise ValueError('jra_pre_race_document_truncated')
    soup = BeautifulSoup(html, 'html.parser')
    headers = soup.select('.race_header')
    if len(headers) != 1:
        raise ValueError('jra_pre_race_header_invalid')
    header = headers[0]
    day_text = _text(header.select_one('.date'))
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', day_text)
    title = _text(header.select_one('.race_name'))
    names = {normalize_jra_race_name(name)
             for name in {event.original_name, event.chinese_name, *event.aliases.values_list('text', flat=True)}} - {''}
    if not match or datetime(*map(int, match.groups())).date() != event.local_date or normalize_jra_race_name(title) not in names:
        raise ValueError('jra_pre_race_identity_mismatch')
    # Match the course as its own meeting component, not an arbitrary substring.
    course = re.search(r'\d+回(.+?)\d+日', day_text)
    if not course or course.group(1).strip() != event.racecourse:
        raise ValueError('jra_pre_race_course_mismatch')
    if urlsplit(url).path == '/JRADB/accessT.html':
        return _parse_jra_registration(soup, header=header, event=event, url=url)
    start = re.search(r'(\d{1,2})時(\d{1,2})分', _text(header.select_one('.time')))
    if not start:
        raise ValueError('jra_pre_race_time_missing')
    off_time = datetime.combine(event.local_date, time(*map(int,start.groups())), ZoneInfo('Asia/Tokyo'))
    table = header.find_parent('table')
    if table is None:
        raise ValueError('jra_pre_race_table_missing')
    rows=[]
    for row in table.select('tbody > tr'):
        cells = row.find_all(['td','th'], recursive=False)
        if not cells:
            continue
        name = _text(row.select_one('td.horse .name'))
        if not name:
            raise ValueError('jra_pre_race_partial_row')
        number = _text(row.select_one('td.num'))
        barrier = _text(row.select_one('td.waku'))
        if barrier == '0': barrier = ''
        if number and not number.isdigit():
            raise ValueError('jra_pre_race_number_invalid')
        rows.append({'horse_name': name, 'horse_number': number, 'barrier': barrier,
            'trainer_name': _text(row.select_one('td.horse .trainer')),
            'jockey_name': _text(row.select_one('td.jockey .jockey')),
            'carried_weight': _text(row.select_one('td.jockey .weight')), 'sort_order': len(rows)+1,
            'source_refs': {'primary': url, 'field_units': {'carried_weight': 'kg'}},
            'running_status': 'scratched' if re.search(r'取消|除外', ' '.join(_text(n) for n in row.select('td.status, td.odds, td.horse .name'))) else 'declared',
            'odds_value': _text(row.select_one('td.odds .odds')),
            'popularity': _text(row.select_one('td.odds .rank')).strip('()（）人気'),
            'odds_kind': 'current', 'odds_format': 'decimal'})
    if not rows or len(rows) > 30 or len({r['horse_name'] for r in rows}) != len(rows):
        raise ValueError('jra_pre_race_roster_invalid')
    numbers=[r['horse_number'] for r in rows if r['horse_number']]
    if numbers and (len(numbers) != len(rows) or len(set(numbers)) != len(numbers)):
        raise ValueError('jra_pre_race_partial_numbers')
    page_title=' '.join(_text(n) for n in soup.select('h1'))
    if '特別登録' in page_title:
        stage='registration'
    elif '出馬表' in page_title:
        stage='numbered' if numbers else 'declared'
    else:
        raise ValueError('jra_pre_race_stage_unknown')
    return {'items': rows, 'stage': stage, 'off_time': off_time.isoformat()}


def _parse_jra_registration(soup, *, header, event, url):
    """特别登录是独立页面合同：没有赛时、马号或闸位，不能生成最终出走名单。"""
    from .race_data_source_adapters import _JRA_VENUE_CODES
    cname = parse_qs(urlsplit(url).query)['CNAME'][0]
    identity = re.fullmatch(r'pw03tde00(\d{2})(\d{2})(\d{2})(\d{2})(\d{8})/[0-9A-F]{2}', cname)
    meeting = re.search(r'(\d+)回(.+?)(\d+)日', _text(header.select_one('.date')))
    if (not identity or not meeting or identity[5] != event.local_date.strftime('%Y%m%d')
        or _JRA_VENUE_CODES.get(identity[1]) != event.racecourse
        or int(identity[2]) != int(meeting[1]) or int(identity[3]) != int(meeting[3])):
        raise ValueError('jra_pre_race_url_identity_mismatch')
    entry = soup.select_one('#stakes_race_entry')
    count = re.search(r'第\d+回特別登録\s*(\d+)頭', _text(entry))
    if entry is None or not count or not 0 < int(count[1]) <= 60:
        raise ValueError('jra_registration_count_missing')
    rows = []
    registered_count = 0
    for tr in entry.select('.horse_list_area table tbody > tr'):
        category = _text(tr.find_parent('table').select_one('caption .main'))
        if not re.fullmatch(r'(登録馬名|地方馬・外国馬)\d+', category):
            raise ValueError('jra_registration_category_unknown')
        if category.startswith('登録馬名'):
            registered_count += 1
        name, weight = _text(tr.select_one('td.horse')), _text(tr.select_one('td.weight'))
        if not name or not re.fullmatch(r'\d{2}(?:\.\d)?', weight):
            raise ValueError('jra_registration_partial_row')
        rows.append(dict(horse_name=name, carried_weight=weight, sort_order=len(rows)+1,
                         horse_number='', barrier='', trainer_name='', jockey_name='',
                         running_status='declared', source_refs={'registration_category': category, 'primary': url, 'field_units': {'carried_weight': 'kg'}}))
    if registered_count != int(count[1]) or len({r['horse_name'] for r in rows}) != len(rows):
        raise ValueError('jra_registration_roster_incomplete')
    return {'items': rows, 'stage': 'registration', 'off_time': None}


def cancel_pre_race_claim(claim):
    """Invalidate a stopped in-flight writer; enabling again cannot revive its lease."""
    with transaction.atomic():
        event = models.RaceEvent.objects.select_for_update().get(pk=claim['event_id'])
        state = _state(event, claim['source'])
        if state.get('lease_token') == claim['token']:
            state.update(lease_token='', lease_until=None, reason='refresh_disabled')
            _save_state(event, claim['source'], state)


def complete_jra(claim, *, html, url, now):
    if not jra_enabled(network=True):
        cancel_pre_race_claim(claim)
        return False
    with transaction.atomic():
        models.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=claim['event_id']).first()
        event = models.RaceEvent.objects.select_for_update().get(pk=claim['event_id'])
        if not _valid_claim(event, claim, now) or not jra_enabled(network=True): return False
        if _refs(event).get('pre_race_handoff'): return False
        payload = parse_jra_card(html, event=event, url=url)
        sha=getattr(html, 'raw_sha256', hashlib.sha256(html.encode()).hexdigest())
        latest=event.data_candidates.filter(source_name=JRA, module='runners').order_by('-fetched_at','-id').first()
        old = (latest.raw_payload or {}).get(JRA,{}) if latest else {}
        if old.get('baseline') == baseline(event) and (STAGES.get(old.get('stage'),-1) > STAGES[payload['stage']] or
                (latest and latest.fetched_at > now)):
            _finish_locked(event,claim,now,'older_or_incomplete_source')
            return False
        from .race_pre_race_refresh import stamp_dynamic_items, material_items
        previous=event.data_candidates.filter(source_name=JRA,module='runners',status='pending',
            raw_payload__jra_pre_race_v1__baseline=baseline(event)).order_by('-fetched_at','-id').first()
        payload['items']=stamp_dynamic_items(payload['items'], previous.candidate_payload.get('items',[]) if previous else [], now=now, source_url=url, strict_roster=False, observed_at=getattr(html,'observed_at',None))
        content_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        display_admitted = (settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED is True and
                            'participants.horse_name' in settings.RACE_DATA_SYNC_ENABLED_FIELDS)
        if (old.get('content_sha256') != content_hash or old.get('baseline') != baseline(event) or
            (display_admitted and old.get('validated') is not True)):
            meta={'validated': display_admitted,
                'baseline': baseline(event), 'raw_sha256': sha, 'content_sha256': content_hash,
                'stage': payload['stage'], 'fetched_at': _iso(now)}
            models.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=JRA,source_url=url,
                candidate_payload=payload,raw_payload={JRA:meta},fetched_at=now)
            if not previous or material_items(previous.candidate_payload.get('items',[]))!=material_items(payload['items']):
                state=_state(event,JRA);state['last_changed_at']=_iso(now);_save_state(event,JRA,state)
        control=models.RaceEventProjectionControl.objects.select_for_update().filter(event=event).first()
        locks=event.manual_lock_flags or {}
        refs=_refs(event)
        old_time=refs.get('jra_pre_race_time',{})
        permitted=(not control or control.write_owner == 'unmanaged') and not (
            event.race_data_sync_enrollment.state == 'enrolled' if hasattr(event,'race_data_sync_enrollment') else False)
        permitted=permitted and not models.RaceEventLifecycleControl.objects.filter(event=event).exists()
        fields={'race_datetime','local_start_time','timezone_name','basic','race_time'}
        permitted=permitted and not any(locks.get(k) for k in fields)
        permitted=permitted and not event.field_authorities.filter(
            subject_type='event', field_name__in=fields, manual_lock=True).exists()
        admitted=set(settings.RACE_DATA_SYNC_ENABLED_FIELDS)
        permitted=permitted and {'off_time','local_start_time','timezone_name'}.issubset(admitted)
        if payload.get('off_time') and settings.RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED and permitted and (
            (event.race_datetime is None and event.local_start_time is None) or (
                old_time.get('baseline') == baseline(event) and
                _dt(old_time.get('value')) == event.race_datetime and
                old_time.get('local_start_time') == _iso(event.local_start_time))):
            off_time=datetime.fromisoformat(payload['off_time'])
            if event.race_datetime != off_time:
                before=_iso(event.race_datetime)
                event.race_datetime=off_time
                event.local_start_time=off_time.time()
                event.timezone_name='Asia/Tokyo'
                refs['jra_pre_race_time']={'value':_iso(off_time), 'source_url':url,'raw_sha256':sha,
                    'baseline':baseline(event), 'local_start_time':_iso(event.local_start_time)}
                event.source_refs=refs
                event.save(update_fields=['race_datetime','local_start_time','timezone_name','source_refs','updated_at'])
                models.RaceEventDataCandidate.objects.create(event=event,module='basic',source_name=JRA,source_url=url,
                    candidate_payload={'race_datetime':_iso(off_time)},raw_payload={JRA:{'before':before,'raw_sha256':sha}},fetched_at=now)
        refs = _refs(event)
        refs['jra_pre_race_url'] = url
        refs['jra_pre_race_binding'] = {'url':url, 'baseline':baseline(event)}
        event.source_refs = refs
        event.save(update_fields=['source_refs', 'updated_at'])
        _finish_locked(event,claim,now)
        return True


def public_jra_preview(event, *, now):
    if (not settings.RACE_DATA_SYNC_ENABLED or not bool({'japan', 'japan_jra'} & set(settings.RACE_DATA_SYNC_ENABLED_REGIONS)) or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED or
        'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS or not preview_window(event,now)): return None
    refs=_refs(event)
    if (refs.get('pre_race_handoff') or any((event.manual_lock_flags or {}).values()) or event.runners.exists()
        or event.field_authorities.filter(manual_lock=True).exists()): return None
    control=getattr(event,'projection_control',None)
    if control and control.write_owner not in {'unmanaged','data_sync'}: return None
    candidate=event.data_candidates.filter(source_name=JRA,module='runners',status='pending',
        raw_payload__jra_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate: return None
    meta=candidate.raw_payload[JRA]
    if meta.get('baseline') != baseline(event) or meta.get('stage') not in STAGES: return None
    try: validate_url(candidate.source_url)
    except ValueError: return None
    return preview_payload(event, candidate, meta['stage'], now=now)


class JraPage(str):
    def __new__(cls, html, raw_sha256, observed_at=None):
        page = super().__new__(cls, html)
        page.raw_sha256 = raw_sha256
        page.observed_at = observed_at
        return page


class JraFetchError(ValueError):
    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.retry_after = retry_after


def fetch_jra_html(url, *, now):
    return _fetch_bounded_html(url, now=now, provider=JRA, region='japan_jra',
        validator=lambda url: validate_url(url, index=True), enabled=lambda: jra_enabled(network=True))


def _reserve_pre_race_request(host):
    """有界等待共享配额；提前唤醒后仍须重新领取，不绕过主机预算。"""
    import time
    from .race_events import reserve_race_live_host_request
    deadline = time.monotonic() + 3
    for _ in range(8):
        reservation = reserve_race_live_host_request(host=host, now=timezone.now())
        if reservation.reserved:
            return reservation
        remaining = deadline - time.monotonic()
        delay = max(0.01, (reservation.next_allowed_at - timezone.now()).total_seconds()) if reservation.next_allowed_at else 0.01
        if reservation.reason != 'rate_limited' or delay > remaining:
            break
        time.sleep(delay)
    raise JraFetchError('jra_host_' + reservation.reason, reservation.next_allowed_at)


def _fetch_bounded_html(url, *, now, provider, region, validator, enabled):
    """Bounded official HTTP, shared snapshot lease and existing host budget."""
    import requests
    import time as clock
    from email.utils import parsedate_to_datetime
    from .race_data_sync_providers import _get_or_fetch_shared_snapshot, _ProviderSyncError
    from .race_events import (ensure_race_live_host_budget_floor, reserve_race_live_host_request,
                              record_race_live_host_outcome)
    validator(url)
    if not enabled():
        raise JraFetchError('jra_pre_race_disabled')
    failure = None
    browser = bool(getattr(settings, 'JRA_BROWSER_URL', '') and urlsplit(url).hostname == 'www.jra.go.jp')
    document_budget = 2 if browser and urlsplit(url).path.startswith('/JRADB/') else 1

    def fetch():
        nonlocal failure
        host = urlsplit(url).hostname
        ensure_race_live_host_budget_floor(host=host, minimum_interval_ms=2000)
        try:
            for _ in range(document_budget):
                reservation = _reserve_pre_race_request(host)
        except JraFetchError as exc:
            failure = exc
            raise
        started, success, retry_after = clock.monotonic(), False, None
        try:
            if not enabled():
                raise JraFetchError('jra_pre_race_disabled')
            if browser:
                from .jra_browser_transport import fetch_browser_document
                try:
                    payload = fetch_browser_document(url)
                except ValueError as exc:
                    raise JraFetchError(str(exc)) from exc
                if not enabled():
                    raise JraFetchError('jra_pre_race_disabled')
                success = True
                return payload, document_budget, 1
            with requests.get(url, timeout=(5, 15), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    value = response.headers.get('Retry-After', '')
                    try:
                        retry_after = (timezone.now()+timedelta(seconds=max(0, int(value)))
                                       if value.isdigit() else parsedate_to_datetime(value))
                        if timezone.is_naive(retry_after): retry_after = None
                    except (ValueError, TypeError, OverflowError):
                        pass
                    raise JraFetchError('jra_http_'+str(response.status_code), retry_after)
                if 'text/html' not in response.headers.get('Content-Type', '').lower():
                    raise JraFetchError('jra_content_type_rejected')
                body = bytearray()
                for chunk in response.iter_content(16384):
                    body.extend(chunk)
                    if len(body) > 2*1024*1024 or clock.monotonic()-started > 20:
                        raise JraFetchError('jra_response_limit')
                raw = bytes(body)
                declared = re.search(br'charset\s*=\s*[\"\']?([A-Za-z0-9_-]+)', raw[:2048], re.I)
                encoding = declared.group(1).decode('ascii').lower() if declared else 'utf-8'
                encodings = {'utf-8':'utf-8', 'utf8':'utf-8', 'shift_jis':'cp932',
                             'shift-jis':'cp932', 'sjis':'cp932', 'cp932':'cp932'}
                if encoding not in encodings: raise JraFetchError('jra_encoding_rejected')
                html = raw.decode(encodings[encoding])
                success = True
                return {'html': html, 'raw_sha256':hashlib.sha256(raw).hexdigest(), 'observed_at':timezone.now().isoformat()}, 1, 1
        except (requests.RequestException, UnicodeError) as exc:
            failure = JraFetchError('jra_transport_failed')
            raise failure from exc
        except JraFetchError as exc:
            failure = exc
            raise
        finally:
            record_race_live_host_outcome(host=host, now=timezone.now(), success=success,
                error_code='' if success else 'jra_fetch_failed', circuit_threshold=3,
                circuit_seconds=300, expected_reservation_version=reservation.reservation_version)
            if retry_after:
                with transaction.atomic():
                    budget = models.RaceLiveHostBudget.objects.select_for_update().get(host=host)
                    budget.next_allowed_at = max(budget.next_allowed_at or retry_after, retry_after)
                    budget.save(update_fields=['next_allowed_at'])
    try:
        # Snapshot scopes are limited to 128 characters; keep existing short keys stable.
        scope_key = url if len(url) <= 128 else 'html:' + hashlib.sha256(url.encode()).hexdigest()
        payload, _ = _get_or_fetch_shared_snapshot(provider=provider, region=region,
            scope_key=scope_key, data_kind='racecard', registry_digest=hashlib.sha256((provider+url).encode()).hexdigest(),
            run_id=secrets.token_hex(16), now=now, proposed_requests=document_budget,
            clock=timezone.now, sleeper=clock.sleep, fetcher=fetch, waiter_max_polls=0)
    except _ProviderSyncError as exc:
        raise failure or JraFetchError(exc.reason_code) from exc
    return JraPage(payload['html'], payload['raw_sha256'], _dt(payload.get('observed_at')))


def discover_jra_pre_race(*, now, fetcher=None, clock=timezone.now):
    if not jra_enabled(network=True): return {'checked':0,'reason':'disabled'}
    fetcher=fetcher or fetch_jra_html
    events=models.RaceEvent.objects.filter(visibility_status='published',status='scheduled',country_region='japan',
        racecourse__in=JRA_COURSES, local_date__gte=now.date()-timedelta(days=1),
        local_date__lte=now.date()+timedelta(days=max(5, min(32, getattr(settings, 'RACE_DATA_SYNC_JAPAN_PRE_RACE_DAYS', 4)+1))))
    events=sorted((e for e in events if in_window(e,now) and not _refs(e).get('pre_race_handoff')),
                  key=lambda e: (_state(e,JRA).get('next_poll_at') or '',e.pk))
    checked=0
    cache={}
    attempted = 0
    for event in events:
        if attempted >= settings.RACE_DATA_SYNC_FUTURE_BATCH_SIZE: break
        started = clock()
        claim=claim_pre_race(event_id=event.pk,source=JRA,now=started)
        if not claim: continue
        attempted += 1
        try:
            refs = _refs(event)
            binding = refs.get('jra_pre_race_binding')
            url = binding.get('url', '') if binding and binding.get('baseline') == baseline(event) else (
                '' if binding else refs.get('jra_pre_race_url', ''))
            if getattr(settings, 'JRA_BROWSER_URL', ''):
                # 每轮优先正式卡，避免绑定报名URL后永远读不到下一阶段。
                urls = []
                for index in (CARD_INDEX_URL, REGISTRATION_INDEX_URL):
                    if index not in cache:
                        cache[index] = fetcher(index, now=clock())
                    urls = jra_pre_race_links(cache[index], event=event)
                    if not urls and index == CARD_INDEX_URL:
                        for meeting in jra_meeting_links(cache[index], event=event):
                            if meeting not in cache:
                                cache[meeting] = fetcher(meeting, now=clock())
                            urls.extend(jra_pre_race_links(cache[meeting], event=event))
                    if urls:
                        break
                if not urls:
                    raise ValueError('jra_not_published')
            elif url:
                urls=[url]
            else:
                if INDEX_URL not in cache: cache[INDEX_URL]=fetcher(INDEX_URL,now=clock())
                soup=BeautifulSoup(cache[INDEX_URL],'html.parser')
                urls=[]
                for a in soup.select('a[href]'):
                    link=urljoin(INDEX_URL,a['href'])
                    if event.local_date.strftime('%Y%m%d')+'/' in link:
                        try: validate_url(link)
                        except ValueError: continue
                        if link not in urls: urls.append(link)
                if not urls: raise ValueError('jra_race_url_not_found')
            matches=[]
            if len(urls) > 4: raise ValueError('jra_race_url_budget_exceeded')
            for link in urls:
                if (clock()-started).total_seconds() >= 50: raise ValueError('jra_work_deadline')
                if link not in cache: cache[link]=fetcher(link,now=clock())
                try: parse_jra_card(cache[link],event=event,url=link)
                except ValueError: continue
                matches.append(link)
            if not matches: raise ValueError('jra_race_identity_no_match')
            if len(matches) > 1: raise ValueError('jra_race_identity_ambiguous')
            completed=clock()
            if (completed-started).total_seconds() > 90: raise ValueError("jra_work_deadline")
            if complete_jra(claim,html=cache[matches[0]],url=matches[0],now=completed): checked+=1
        except (ValueError, OSError) as exc:
            if str(exc) == 'jra_not_published':
                finish_pre_race(claim,now=clock(),outcome_reason='not_published')
            else:
                finish_pre_race(claim,now=clock(),reason=str(exc)[:64], retry_after=getattr(exc,"retry_after",None))
    return {'checked':checked, 'attempted':attempted}


REVIEWED_PRE_RACE = 'reviewed_pre_race_v1'
REVIEWED_HOSTS = frozenset({'www.sportinglife.com', 'www.zeturf.fr', 'www.racingpost.com', 'www.keiba.go.jp'})


def public_reviewed_preview(event, *, now):
    """仅展示已人工核验的整份参考卡；正式卡接管后永不恢复。"""
    # Once an automatic full snapshot supersedes this card, a read gate must
    # never resurrect the older manual roster (including its pre-scratch state).
    if event.data_candidates.filter(source_name=REFRESH,module='runners',status='pending',
        raw_payload__pre_race_refresh_v1__validated=True,
        raw_payload__pre_race_refresh_v1__baseline=baseline(event)).exists():
        return None
    if (not settings.RACE_DATA_SYNC_ENABLED or not settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED
        or 'participants.horse_name' not in settings.RACE_DATA_SYNC_ENABLED_FIELDS
        or not preview_window(event, now) or _refs(event).get('pre_race_handoff') or event.runners.exists()
        or any((event.manual_lock_flags or {}).values())
        or event.field_authorities.filter(manual_lock=True).exists()):
        return None
    control = getattr(event, 'projection_control', None)
    if control and control.write_owner not in {'unmanaged', 'data_sync'}:
        return None
    candidate = event.data_candidates.filter(source_name=REVIEWED_PRE_RACE, module='runners',
        status='pending', raw_payload__reviewed_pre_race_v1__validated=True).order_by('-fetched_at','-id').first()
    if not candidate:
        return None
    meta = candidate.raw_payload.get(REVIEWED_PRE_RACE, {})
    items = candidate.candidate_payload.get('items', [])
    if (meta.get('baseline') != baseline(event) or meta.get('stage') not in STAGES
        or meta.get('authority') not in {'human_reviewed_reference', 'human_reviewed_official'}
        or not isinstance(items, list) or not 0 < len(items) <= 60 or meta.get('row_count') != len(items)
        or hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest() != meta.get('items_sha256')):
        return None
    try:
        url = urlsplit(candidate.source_url)
        if (url.scheme != 'https' or url.hostname not in REVIEWED_HOSTS or url.username or url.password
            or url.port not in {None, 443}):
            return None
        if ((url.hostname == 'www.keiba.go.jp') != (meta['authority'] == 'human_reviewed_official')):
            return None
        if not all(isinstance(row, dict) and row.get('horse_name') and
                   row.get('running_status') in {'declared','withdrawn','non_runner'} for row in items):
            return None
        if meta['stage'] == 'numbered' and (not all(row.get('horse_number') for row in items)
            or len({row['horse_number'] for row in items}) != len(items)):
            return None
    except (ValueError, TypeError):
        return None
    return preview_payload(event, candidate, meta['stage'], now=now)


def preview_payload(event, candidate, stage, *, now):
    from .race_pre_race_refresh import dynamic_rows, refresh_interval
    rows = dynamic_rows(event, candidate.candidate_payload.get('items', []), now=now)
    if candidate.source_name == JRA:
        for row in rows:
            row.source_refs = {**row.source_refs, 'field_units': {
                **row.source_refs.get('field_units', {}), 'carried_weight': 'kg'}}
    checked = _dt(_state(event, candidate.source_name).get('last_checked_at')) or candidate.fetched_at
    state = _state(event, candidate.source_name)
    return {'rows': rows, 'label': LABELS[stage], 'checked_at': checked,
            'stale': bool(state.get('reason')) or now-checked > refresh_interval(event, now)+timedelta(minutes=10)}


def jra_meeting_links(html, *, event):
    """普通竞走与重赏共用官方会场索引，不限已知重赏列表。"""
    from .race_data_source_adapters import _JRA_VENUE_CODES
    links=[]
    for _, url in jra_document_links(html):
        values=parse_qs(urlsplit(url).query).get('CNAME',[])
        match=re.fullmatch(r'pw01drl(?:00|10)(\d{2})\d{8}(\d{8})/[0-9A-F]{2}',values[0]) if len(values)==1 else None
        if match and _JRA_VENUE_CODES.get(match[1])==event.racecourse and match[2]==event.local_date.strftime('%Y%m%d'):
            validate_url(url,index=True)
            if url not in links:links.append(url)
    if len(links)>1:raise ValueError('jra_meeting_ambiguous')
    return links
