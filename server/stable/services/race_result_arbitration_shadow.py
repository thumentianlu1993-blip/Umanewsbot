"""Caller-shaped ordinary snapshot mapper; no hook, ORM, source or authentication."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from .race_source_arbitration import (
    Arbitration, Observation, FreshnessVerdict, ResultField, arbitrate_result_sources,
)

TOP={'schema_version','event_key','schedule_generation','as_of','expected_runner_ids','manual_locked','current','candidate','legacy'}
PACKAGE={'observation_ref','version_ref','event_key','captured_schedule_generation','provider_key','source_priority',
         'http_status','error_code','content_clock','transport_clocks','assessments','freshness','rows'}
CLOCKS={'observed_at','fetched_at','recorded_at','watermark_at','permission_valid_until','poll_due_at'}
ASSESS={'admission','health','identity','revoked','rows_normalized','strong_identity_matched','terminal_marker',
        'roster_mapping_complete','result_phase','correction_marker','origin_group','freshness_producer_ref'}
ROW={'runner_id','reported_finish_position','status','finish_time','margin','barrier','carried_weight',
     'horse_name','jockey_name','trainer_name','evidence_ref'}
FRESH={'state','rule_ref','observation_ref','version_ref','assessed_at','valid_until','result_sha256'}
FACTS=('reported_finish_position','status','finish_time','margin','barrier','carried_weight')
NAMES=('horse_name','jockey_name','trainer_name')
TERMINAL={'finished','dead_heat','scratched','withdrawn','non_runner','disqualified','did_not_finish',
          'pulled_up','unseated_rider','fell','refused'}


@dataclass(frozen=True)
class ShadowResult:
    action: str
    reason: str
    gaps: tuple[str, ...] = ()
    compare_names: bool | None = None
    content_times: tuple[tuple[str, str | None], ...] = ()
    recommendation: Arbitration | None = None
    legacy_snapshot_sha256: str | None = None
    apply: bool = False
    publication: bool = False
    execution: bool = False
    authenticated: bool = False


def _shape(obj, fields):
    if type(obj) is not dict or set(obj)!=fields: raise ValueError('shape')


def _tree(obj, depth=0, active=None, count=None):
    active=set() if active is None else active
    count=[0,0] if count is None else count
    count[0]+=1
    if depth>8 or count[0]>20000: raise ValueError('size')
    if type(obj) is str:
        if len(obj)>4096: raise ValueError('size')
        count[1]+=len(obj.encode('utf-8'))
        if count[1]>1024*1024: raise ValueError('size')
    elif type(obj) is int:
        if obj.bit_length()>63: raise ValueError('integer')
    elif obj is None or type(obj) is bool: pass
    elif type(obj) in (dict,list):
        if id(obj) in active: raise ValueError('cycle')
        active.add(id(obj))
        try:
            if type(obj) is dict:
                for k,v in obj.items():
                    if type(k) is not str: raise ValueError('key')
                    _tree(k,depth+1,active,count);_tree(v,depth+1,active,count)
            else:
                for v in obj:_tree(v,depth+1,active,count)
        finally: active.remove(id(obj))
    else: raise ValueError('not_plain')


def _ref(v, nullable=False):
    if v is None and nullable:return
    if type(v) is not str or not v or len(v.encode('utf-8'))>256:raise ValueError('reference')


def _int(v, nullable=False):
    if v is None and nullable:return
    if type(v) is not int or v<0:raise ValueError('integer')


def _time(v, nullable=False):
    if v is None and nullable:return None
    if type(v) is not str or len(v)>64:raise ValueError('time')
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError('time')
        return d.astimezone(timezone.utc)
    except (ValueError,OverflowError):raise ValueError('time') from None


def _bool(v, nullable=False):
    if v is None and nullable:return
    if type(v) is not bool:raise ValueError('bool')


def _package(p):
    _shape(p,PACKAGE)
    for k in ('observation_ref','version_ref','event_key','provider_key'):_ref(p[k])
    _int(p['captured_schedule_generation'],True);_int(p['source_priority'],True);_int(p['http_status'],True)
    if p['error_code'] is not None and type(p['error_code']) is not str:raise ValueError('error_code')
    _shape(p['content_clock'],{'content_at','basis_ref'})
    _time(p['content_clock']['content_at'],True);_ref(p['content_clock']['basis_ref'],True)
    _shape(p['transport_clocks'],CLOCKS)
    for v in p['transport_clocks'].values():_time(v,True)
    a=p['assessments'];_shape(a,ASSESS)
    for k,choices in [('admission',('allowed','blocked','unknown')),('health',('healthy','failed','unknown')),
                      ('identity',('matched','conflict','unknown')),('result_phase',('official','corrected','provisional','unknown'))]:
        if a[k] is not None and (type(a[k]) is not str or a[k] not in choices):raise ValueError('enum')
    for k in ('revoked','rows_normalized','strong_identity_matched','terminal_marker','roster_mapping_complete','correction_marker'):_bool(a[k],True)
    _ref(a['origin_group'],True);_ref(a['freshness_producer_ref'],True)
    f=p['freshness']
    if f is not None:
        _shape(f,FRESH)
        if f['state'] not in ('fresh','stale','unknown'):raise ValueError('state')
        for k in ('rule_ref','observation_ref','version_ref','result_sha256'):_ref(f[k],True)
        _time(f['assessed_at'],True);_time(f['valid_until'],True)
    if type(p['rows']) is not list or len(p['rows'])>128:raise ValueError('row_limit')
    for r in p['rows']:
        _shape(r,ROW);_int(r['runner_id'],True);_int(r['reported_finish_position'],True);_ref(r['evidence_ref'])
        for k in ('status',)+NAMES:
            if type(r[k]) is not str:raise ValueError('row_text')
        for k in ('finish_time','margin','barrier','carried_weight'):
            if r[k] is not None and type(r[k]) is not str:raise ValueError('row_scalar')


def _gaps(p, label, s):
    gaps=set();a=p['assessments'];clock=p['content_clock'];f=p['freshness']
    add=lambda reason:gaps.add(label+'.'+reason)
    if p['event_key']!=s['event_key']:add('event_mismatch')
    if p['captured_schedule_generation'] is None:add('capture_generation_missing')
    elif p['captured_schedule_generation']!=s['schedule_generation']:add('capture_generation_mismatch')
    if p['source_priority'] not in (100,200,300):add('source_priority_missing')
    if clock['content_at'] is None or clock['basis_ref'] is None:add('content_clock_missing')
    for k,value in [('admission','allowed'),('health','healthy'),('identity','matched')]:
        if a[k]!=value:add(k+'_unproven')
    if a['revoked'] is not False:add('revocation_unproven')
    for k in ('rows_normalized','strong_identity_matched','terminal_marker','roster_mapping_complete'):
        if a[k] is not True:add(k+'_unproven')
    if a['result_phase'] not in ('official','corrected'):add('terminal_phase_missing')
    if a['result_phase']=='corrected' and a['correction_marker'] is None:add('correction_name_condition_missing')
    if a['origin_group'] is None:add('origin_missing')
    if a['freshness_producer_ref'] is None:add('freshness_producer_missing')
    if f is None:add('freshness_missing')
    elif (f['state']=='unknown' or any(f[k] is None for k in FRESH-{'state'})):add('freshness_missing')
    ids=[r['runner_id'] for r in p['rows']]
    if any(v is None or v==0 for v in ids):add('runner_unpersisted')
    if len(set(ids))!=len(ids) or set(ids)!=set(s['expected_runner_ids']):add('runner_coverage_mismatch')
    pointers=[]
    prefix=re.escape(p['observation_ref'])+r'/normalized_payload/participants/(0|[1-9][0-9]*)\Z'
    for r in p['rows']:
        match=re.fullmatch(prefix,r['evidence_ref'])
        if match is None:add('field_pointer_mismatch')
        else:pointers.append(int(match[1]))
        position=r['reported_finish_position']
        if (r['status'] not in TERMINAL or (r['status'] in ('finished','dead_heat'))!=(position is not None)
                or position is not None and not 1<=position<=100):add('normalized_row_assertion_inconsistent')
    # Match fixed-main normalized ranking semantics without changing any row.
    positions=[r['reported_finish_position'] for r in p['rows'] if r['reported_finish_position'] is not None]
    counts={}
    for position in positions:counts[position]=counts.get(position,0)+1
    legal=bool(positions);ranked_count=0
    for position,count in sorted(counts.items()):
        if position!=ranked_count+1:legal=False
        ranked_count+=count
    for r in p['rows']:
        position=r['reported_finish_position']
        if position is not None and r['status']!=('dead_heat' if counts[position]>1 else 'finished'):legal=False
    if not legal:add('normalized_ranking_inconsistent')
    if len(pointers)!=len(p['rows']) or set(pointers)!=set(range(len(p['rows']))):add('field_pointer_coverage_mismatch')
    return gaps


def _observation(p, compare):
    fields=[]
    for row in p['rows']:
        value={k:row[k] for k in FACTS+(NAMES if compare else ())}
        encoded=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        if len(encoded.encode('utf-8'))>4096:raise ValueError('field_size')
        fields.append(ResultField('runner:'+str(row['runner_id']),encoded,row['evidence_ref']))
    f=p['freshness'];a=p['assessments']
    verdict=FreshnessVerdict(f['state'],f['rule_ref'],f['observation_ref'],f['version_ref'],
                            _time(f['assessed_at']),_time(f['valid_until']),f['result_sha256'])
    return Observation(p['observation_ref'],p['version_ref'],p['event_key'],p['captured_schedule_generation'],
                       p['provider_key'],a['origin_group'],p['source_priority'],a['admission'],a['health'],a['identity'],
                       'confirmed' if a['result_phase']=='official' else 'corrected',True,True,a['revoked'],
                       _time(p['content_clock']['content_at']),verdict,tuple(fields))


def map_result_arbitration_shadow(snapshot):
    """Shape/diagnostic mapper only. All supplied validation projections are asserted."""
    compare=None;times=();legacy_hash=None
    try:
        _tree(snapshot);_shape(snapshot,TOP)
        if snapshot['schema_version']!='r04-shadow-input.v1':raise ValueError('schema')
        _ref(snapshot['event_key']);_int(snapshot['schedule_generation'],True);now=_time(snapshot['as_of']);_bool(snapshot['manual_locked'])
        ids=snapshot['expected_runner_ids']
        if type(ids) is not list or not 1<=len(ids)<=128:raise ValueError('expected_limit')
        for v in ids:_int(v,True)
        _shape(snapshot['legacy'],{'apply','reason_code','project_current','correction_apply_enabled'})
        for k in ('apply','project_current','correction_apply_enabled'):_bool(snapshot['legacy'][k])
        _ref(snapshot['legacy']['reason_code'])
        legacy_hash=hashlib.sha256(json.dumps(snapshot['legacy'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        current=snapshot['current'];candidate=snapshot['candidate'];_package(candidate)
        if current is not None:_package(current)
        a=candidate['assessments']
        compare=bool(current and current['provider_key']==candidate['provider_key']) or (a['result_phase']=='corrected' and a['correction_marker'] is True)
        packages=[('current',current),('candidate',candidate)]
        times=tuple((label,_time(p['content_clock']['content_at']).isoformat() if p and p['content_clock']['content_at'] is not None and p['content_clock']['basis_ref'] is not None else None) for label,p in packages)
        gaps=set()
        if snapshot['schedule_generation'] is None:gaps.add('target.schedule_generation_missing')
        if any(v is None or v==0 for v in ids) or len(set(ids))!=len(ids):gaps.add('target.runner_keys_unpersisted_or_duplicate')
        for label,p in packages:
            if p is not None:gaps.update(_gaps(p,label,snapshot))
        if gaps:return ShadowResult('NEEDS_EVIDENCE','snapshot_evidence_missing',tuple(sorted(gaps)),compare,times,legacy_snapshot_sha256=legacy_hash)
        result=arbitrate_result_sources(event_key=snapshot['event_key'],generation=snapshot['schedule_generation'],as_of=now,
                                       expected_fields=tuple('runner:'+str(v) for v in sorted(ids)),
                                       current=_observation(current,compare) if current else None,
                                       candidates=(_observation(candidate,compare),),manual_locked=snapshot['manual_locked'])
        # A malformed or unqualified asserted verdict is not a usable shadow SELECT.
        if result.action=='NEEDS_EVIDENCE':
            return ShadowResult('NEEDS_EVIDENCE',result.reason,('core.evidence_missing',),compare,times,legacy_snapshot_sha256=legacy_hash)
        return ShadowResult(result.action,result.reason,(),compare,times,result,legacy_hash)
    except (ValueError,TypeError,OverflowError,RecursionError):
        return ShadowResult('NEEDS_EVIDENCE','invalid_snapshot',('snapshot.contract',),compare,times,legacy_snapshot_sha256=legacy_hash)
