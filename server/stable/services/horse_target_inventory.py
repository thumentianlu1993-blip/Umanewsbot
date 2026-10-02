"""Pure H01 planner over explicit, trusted producer snapshots.

Does not query ORM, create identities, infer permissions, or publish anything.
Keys are horse identities supplied by the producer, never race-local runner IDs.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import re

REGIONS = ('japan','hong_kong','united_kingdom','ireland','france','united_states','australia','germany','middle_east')
FIELDS = {
    'events': 'key region local_date date_precision grade grade_verified hk_local_g1 current_racecard current_result known_roster_count',
    'participations': 'ref event_key participant_key horse_key revision_ref kind status start_evidence birth_year',
    'identities': 'horse_key profile_id status evidence_sha verified_at',
    'layers': 'target_key cache staging profile_exists public_state starts incomplete_modules',
    'news': 'horse_key profile_id published_date confirmed',
    'seasons': 'region start end evidence_sha version',
}
TOP = set(FIELDS) | {'schema_version','as_of','snapshot_at','input_complete','policy_sha','jg1_scope'}


def _fail(code):
    raise ValueError(code)


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _key(value, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value):
        _fail('invalid_key')


def _int(value, nullable=False, minimum=0):
    if value is None and nullable:
        return
    if type(value) is not int or not minimum <= value <= 10**12:
        _fail('invalid_integer')


def _date(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        _fail('invalid_date')
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail('invalid_date')


def _time(value, nullable=False):
    if value is None and nullable:
        return
    try:
        if type(value) is not str:
            _fail('invalid_time')
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            _fail('invalid_time')
        return parsed
    except (ValueError, TypeError):
        _fail('invalid_time')


def _digest(value, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        _fail('invalid_digest')


def _bool(value, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not bool:
        _fail('invalid_boolean')


def _plain(value, depth=0, budget=None):
    if budget is None:
        budget=[100000]
    budget[0]-=1
    if budget[0]<0 or depth>64:
        _fail('input_structure_limit')
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            _fail('input_structure')
        for item in value.values():
            _plain(item,depth+1,budget)
    elif type(value) is list:
        for item in value:
            _plain(item,depth+1,budget)
    elif value is not None and type(value) not in (str,int,bool):
        _fail('input_structure')


def _validate(payload):
    if type(payload) is not dict or set(payload)!=TOP:
        _fail('input_schema')
    _plain(payload)
    try:
        encoded=json.dumps(payload,allow_nan=False)
        if len(encoded.encode())>2*1024*1024:
            _fail('input_size')
    except (TypeError, ValueError, RecursionError):
        _fail('input_serialization')
    p=deepcopy(payload)
    if type(p['schema_version']) is not int or p['schema_version']!=1 or p['jg1_scope']!='unresolved':
        _fail('schema_or_pending_scope')
    _date(p['as_of']);_time(p['snapshot_at']);_bool(p['input_complete']);_digest(p['policy_sha'])
    for name,fields in FIELDS.items():
        if type(p[name]) is not list or len(p[name])>20000:
            _fail('collection_limit')
        for item in p[name]:
            if type(item) is not dict or set(item)!=set(fields.split()):
                _fail('row_schema')
    for e in p['events']:
        _key(e['key']);_date(e['local_date'],True);_key(e['current_racecard'],True);_key(e['current_result'],True)
        _int(e['known_roster_count'],True);_bool(e['grade_verified']);_bool(e['hk_local_g1'])
        if e['region'] not in REGIONS or e['date_precision'] not in ('exact','month','year','unknown') or e['grade'] not in ('G1','G2','G3','JG1','JG2','JG3','JPN1','JPN2','JPN3','LOCAL_GRADE','OTHER','UNKNOWN'):
            _fail('event_enum')
        if e['date_precision']=='exact' and e['local_date'] is None:
            _fail('exact_date_missing')
    events={e['key'] for e in p['events']}
    for r in p['participations']:
        for k in ('ref','event_key','participant_key'):_key(r[k])
        _key(r['horse_key'],True);_key(r['revision_ref'],True);_int(r['birth_year'],True);_bool(r['start_evidence'],True)
        if r['event_key'] not in events or r['kind'] not in ('legacy','racecard','result') or (r['kind']=='legacy') != (r['revision_ref'] is None):
            _fail('participation_reference')
        if r['status'] not in ('finished','dead_heat','did_not_finish','disqualified','fell','pulled_up','unseated_rider','refused','scratched','withdrawn','non_runner','declared','running','unknown','reinstated'):
            _fail('start_status')
        if r['start_evidence'] is True and r['status'] in ('scratched','withdrawn','non_runner','declared'):
            _fail('start_contradiction')
    for i in p['identities']:
        _key(i['horse_key']);_int(i['profile_id'],minimum=1);_digest(i['evidence_sha'],True);_time(i['verified_at'],True)
        if i['status'] not in ('verified','observed','rejected','retired'):
            _fail('identity_status')
        if i['status']=='verified' and (i['evidence_sha'] is None or i['verified_at'] is None or _time(i['verified_at'])>_time(p['snapshot_at'])):
            _fail('verified_evidence_missing')
    for layer in p['layers']:
        _key(layer['target_key']);_bool(layer['profile_exists'],True);_int(layer['starts'],True);_int(layer['incomplete_modules'],True)
        if layer['cache'] not in ('present','missing','unknown') or layer['staging'] not in ('matched','unmatched','ambiguous','unknown') or layer['public_state'] not in ('visible','unpublished','hidden','blocked','unknown'):
            _fail('layer_status')
        if layer['public_state']=='visible' and layer['profile_exists'] is not True:
            _fail('public_without_profile')
    for n in p['news']:
        _key(n['horse_key'],True);_int(n['profile_id'],True,1);_date(n['published_date']);_bool(n['confirmed'])
        if n['horse_key'] is None and n['profile_id'] is None:_fail('news_identity_missing')
    for s in p['seasons']:
        _date(s['start']);_date(s['end']);_digest(s['evidence_sha'],True);_key(s['version'],True)
        if s['region'] not in REGIONS or s['start']>s['end']:_fail('season_range')
    for name,key in [('events','key'),('participations','ref'),('layers','target_key'),('seasons','region')]:
        if len({r[key] for r in p[name]})!=len(p[name]):_fail('duplicate_reference')
    # All top-level collections are sets of observations, not presentation order.
    for name in FIELDS:p[name].sort(key=lambda item:json.dumps(item,sort_keys=True))
    return p


def plan_inventory(payload):
    p=_validate(payload);as_of=_date(p['as_of']);events={e['key']:e for e in p['events']}
    identities={};gaps={'jg1_unresolved'};targets={};unknown_rosters=0
    if not p['input_complete']:gaps.add('input_incomplete')
    identity_rows={}
    for i in p['identities']:identity_rows.setdefault(i['horse_key'],[]).append(i)
    for key, values in identity_rows.items():
        if any(i['status']!='verified' for i in values):
            if any(i['status']=='verified' for i in values):gaps.add('identity_status_conflict')
            continue
        identities[key]={i['profile_id'] for i in values}
    rows_by_event={}
    for row in p['participations']:rows_by_event.setdefault(row['event_key'],[]).append(row)
    rows_by_ref={row['ref']:row for row in p['participations']}
    def target(horse_key,event_key=None,participant_key=None,profile_id=None):
        matches=identities.get(horse_key,set())
        if len(matches)>1:gaps.add('identity_conflict')
        resolved=len(matches)==1 or (profile_id is not None and not matches)
        pid=next(iter(matches)) if len(matches)==1 else profile_id if not matches else None
        key='profile:'+str(pid) if resolved else 'source:'+horse_key if horse_key else 'participation:'+event_key+':'+participant_key
        t=targets.setdefault(key,dict(key=key,resolved=resolved,memberships=set(),regions=set(),refs=set(),reasons=set(),last_start=None))
        if not resolved:gaps.add('identity_unresolved')
        return t
    for e in p['events']:
        all_rows=rows_by_event.get(e['key'],[])
        pointer=e['current_result'] or e['current_racecard']
        if pointer:
            rows=[r for r in all_rows if r['revision_ref']==pointer and r['kind']==('result' if e['current_result'] else 'racecard')]
            pending=not rows
        else:
            pending=any(r['revision_ref'] is not None for r in all_rows)
            rows=all_rows if pending else [r for r in all_rows if r['kind']=='legacy']
        if pending:gaps.add('revision_unresolved');rows=all_rows
        size=len({r['participant_key'] for r in rows})
        if e['known_roster_count'] is None:unknown_rosters+=1;gaps.add('roster_unknown')
        elif size!=e['known_roster_count']:gaps.add('roster_missing')
        day=_date(e['local_date'],True)
        if day is None or e['date_precision']!='exact':gaps.add('date_unconfirmed')
        if not e['grade_verified']:gaps.add('grade_unconfirmed')
        participants={}
        for row in rows:
            keys=identities.get(row['horse_key'],set())
            canonical='profile:'+str(next(iter(keys))) if len(keys)==1 else row['horse_key'] or row['ref']
            participants.setdefault(row['participant_key'],set()).add(canonical)
        conflicts={key for key,values in participants.items() if len(values)>1}
        if conflicts:gaps.add('participation_conflict')
        for r in rows:
            row_pending=pending or r['participant_key'] in conflicts
            memberships=set();reasons=set()
            if day is None or e['date_precision']!='exact':memberships.add('candidate')
            if row_pending:memberships.add('candidate')
            elif day and e['date_precision']=='exact':
                if date(2023,10,3)<=day<=date(2026,10,3) and day<=as_of:
                    if r['start_evidence'] is True:memberships.add('recent')
                    elif r['start_evidence'] is None:memberships.add('start_pending');gaps.add('start_unconfirmed')
                if date(2020,1,1)<=day<=as_of and e['grade_verified']:
                    if e['grade'] in ('G1','JPN1') or (e['region']=='hong_kong' and e['hk_local_g1']):memberships.add('historical')
                    elif e['grade']=='JG1':memberships.add('historical_pending')
                if as_of<=day<=as_of+timedelta(days=30):reasons.add('today' if day==as_of else 'future_30d')
            if not memberships and not reasons:continue
            t=target(r['horse_key'],e['key'],r['participant_key']);t['memberships'].update(memberships);t['reasons'].update(reasons);t['regions'].add(e['region']);t['refs'].add(r['ref'])
            if r['start_evidence'] is True and not row_pending and day and e['date_precision']=='exact' and day<=as_of:t['last_start']=max(t['last_start'] or day.isoformat(),day.isoformat())
    for n in p['news']:
        if n['confirmed'] and as_of-timedelta(days=90)<=_date(n['published_date'])<=as_of:
            t=target(n['horse_key'],profile_id=n['profile_id']);t['reasons'].add('recent_news')
    seasons={s['region']:s for s in p['seasons'] if s['evidence_sha'] and s['version'] and s['start']<=as_of.isoformat()<=s['end']}
    layers={s['target_key']:s for s in p['layers']}
    result=[]
    for t in targets.values():
        for region in t['regions']:
            s=seasons.get(region)
            if s and any(s['start']<=events[rows_by_ref[ref]['event_key']]['local_date']<=s['end'] for ref in t['refs'] if events[rows_by_ref[ref]['event_key']]['region']==region and events[rows_by_ref[ref]['event_key']]['local_date']):t['reasons'].add('current_season')
        t['layers']=deepcopy(layers.get(t['key'],dict(target_key=t['key'],cache='unknown',staging='unknown',profile_exists=None,public_state='unknown',starts=None,incomplete_modules=None)))
        for k in ('memberships','regions','refs','reasons'):t[k]=sorted(t[k])
        result.append(t)
    def priority(t):
        reasons=t['reasons'];layer=t['layers']
        return (0 if 'today' in reasons or 'future_30d' in reasons else 1,0 if 'current_season' in reasons else 1,0 if 'recent_news' in reasons else 1,-date.fromisoformat(t['last_start']).toordinal() if t['last_start'] else 0,-(layer['incomplete_modules'] or 0),t['key'])
    result.sort(key=priority)
    counts=dict(identity_conflict_groups=sum(len(values)>1 for values in identities.values()),raw_participations=len(p['participations']),unknown_roster_events=unknown_rosters,resolved_targets=sum(t['resolved'] for t in result),unresolved_targets=sum(not t['resolved'] for t in result),future_targets=sum('future_30d' in t['reasons'] for t in result),public_visible_targets=sum(t['layers']['public_state']=='visible' for t in result),cache_present_targets=sum(t['layers']['cache']=='present' for t in result),staging_matched_targets=sum(t['layers']['staging']=='matched' for t in result),profile_exists_targets=sum(t['layers']['profile_exists'] is True for t in result))
    for membership in ('recent','historical','historical_pending'):counts[membership+'_targets']=sum(membership in t['memberships'] for t in result)
    out=dict(schema_version=1,as_of=p['as_of'],snapshot_at=p['snapshot_at'],policy_sha=p['policy_sha'],input_sha256=_sha(p),targets=result,counts=counts,gaps=sorted(gaps),complete=False,historical_complete=False)
    out['content_sha256']=_sha(out)
    return out


def compare_snapshots(previous, current):
    for snapshot in (previous,current):
        if type(snapshot) is not dict or 'content_sha256' not in snapshot:
            _fail('snapshot_schema')
        body={k:v for k,v in snapshot.items() if k!='content_sha256'}
        if _sha(body)!=snapshot['content_sha256']:
            _fail('snapshot_digest')
    old={t['key']:t for t in previous['targets']};new={t['key']:t for t in current['targets']}
    return dict(previous_sha=previous['content_sha256'],current_sha=current['content_sha256'],added=sorted(new.keys()-old.keys()),removed=sorted(old.keys()-new.keys()),reclassified=sorted(k for k in old.keys()&new.keys() if old[k]!=new[k]))
