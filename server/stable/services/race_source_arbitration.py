"""Result-only pure selection. Supplied verdicts are assertions, not authentication."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re


@dataclass(frozen=True)
class ResultField:
    name: str
    value: str
    evidence_ref: str


@dataclass(frozen=True)
class FreshnessVerdict:
    state: str  # fresh/stale/unknown
    rule_ref: str | None
    observation_ref: str
    version_ref: str
    assessed_at: datetime | None
    valid_until: datetime | None
    result_sha256: str | None = None


@dataclass(frozen=True)
class Observation:
    observation_ref: str
    version_ref: str
    event_key: str
    generation: int
    provider_key: str
    origin_group: str
    priority: int  # Existing caller-mapped 100/200/300; no new source class.
    admission: str  # allowed/blocked/unknown
    health: str  # healthy/failed/unknown
    identity: str  # matched/conflict/unknown
    maturity: str  # predicted/confirmed/corrected/unknown
    qualified: bool
    complete: bool
    revoked: bool
    content_at: datetime | None
    freshness: FreshnessVerdict
    fields: tuple[ResultField, ...]


@dataclass(frozen=True)
class Arbitration:
    action: str
    reason: str
    retained_version_ref: str | None
    selected_observation_ref: str | None = None
    selected_version_ref: str | None = None
    result_sha256: str | None = None
    field_refs: tuple[tuple[str, str], ...] = ()
    rejected: tuple[tuple[str, str], ...] = ()
    evidence_needed: tuple[str, ...] = ()
    blocked_capability: str | None = None
    authenticated: bool = False
    publication_authorized: bool = False


def _text(value, limit=256, *, empty=False):
    if type(value) is not str or (not empty and not value) or len(value)>limit:
        raise ValueError('text_contract')
    size=len(value.encode('utf-8'))
    if size>limit: raise ValueError('text_contract')
    return size


def _time(value, optional=False):
    if value is None and optional: return None
    # Fixed-offset aware values only: arbitrary tzinfo callbacks are not a pure DTO.
    if type(value) is not datetime or type(value.tzinfo) is not timezone:
        raise ValueError('aware_fixed_offset_time_required')
    try:
        return value.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError('time_outside_UTC_range') from None


def _fields(fields):
    if type(fields) is not tuple or len(fields)>128: raise ValueError('field_limit')
    seen=set();total=0
    for f in fields:
        if type(f) is not ResultField: raise ValueError('field_contract')
        total+=_text(f.name,128)+_text(f.value,4096,empty=True)+_text(f.evidence_ref)
        if f.name in seen: raise ValueError('field_contract')
        seen.add(f.name)
    return total


def _result_sha(o):
    values=sorted((f.name,f.value) for f in o.fields)
    raw=json.dumps(values,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _validate(o):
    if type(o) is not Observation or type(o.freshness) is not FreshnessVerdict:
        raise ValueError('observation_contract')
    size=sum(_text(getattr(o,k)) for k in ('observation_ref','version_ref','event_key','provider_key','origin_group'))
    if type(o.generation) is not int or o.generation<0 or type(o.priority) is not int or o.priority not in (100,200,300):
        raise ValueError('generation_priority_contract')
    for k,values in [('admission',('allowed','blocked','unknown')),('health',('healthy','failed','unknown')),
                     ('identity',('matched','conflict','unknown')),('maturity',('predicted','confirmed','corrected','unknown'))]:
        if type(getattr(o,k)) is not str or getattr(o,k) not in values: raise ValueError('enum_contract')
    for k in ('qualified','complete','revoked'):
        if type(getattr(o,k)) is not bool: raise ValueError('bool_contract')
    _time(o.content_at,True);v=o.freshness
    if type(v.state) is not str or v.state not in ('fresh','stale','unknown'): raise ValueError('freshness_contract')
    size+=_text(v.observation_ref)+_text(v.version_ref)
    if v.rule_ref is not None: size+=_text(v.rule_ref)
    if v.result_sha256 is not None:
        if type(v.result_sha256) is not str or re.fullmatch('[0-9a-f]{64}',v.result_sha256) is None:
            raise ValueError('digest_contract')
        size+=64
    _time(v.assessed_at,True);_time(v.valid_until,True)
    return size+_fields(o.fields)


def _signature(o):
    v=o.freshness
    stamp=lambda d:_time(d,True).isoformat() if d is not None else None
    return (o.version_ref,o.event_key,o.generation,o.provider_key,o.origin_group,o.priority,
            o.admission,o.health,o.identity,o.maturity,o.qualified,o.complete,o.revoked,
            stamp(o.content_at),v.state,v.rule_ref,v.observation_ref,v.version_ref,
            stamp(v.assessed_at),stamp(v.valid_until),v.result_sha256,
            tuple(sorted((f.name,f.value,f.evidence_ref) for f in o.fields)))


def _eligibility(o,event,generation,now,expected):
    if o.event_key!=event or o.generation!=generation: return 'target_generation_mismatch'
    if o.revoked: return 'revoked'
    if o.identity!='matched': return 'identity_unqualified'
    if o.admission!='allowed': return 'source_not_admitted'
    if o.health!='healthy': return 'source_health_unknown_or_failed'
    if not o.qualified or not o.complete: return 'result_unqualified_or_partial'
    if o.maturity not in ('confirmed','corrected'): return 'maturity_downgrade'
    if {f.name for f in o.fields}!=expected or any(not f.value for f in o.fields): return 'field_coverage_missing'
    content=_time(o.content_at,True);v=o.freshness
    if content is None: return 'content_time_missing'
    if content>now: return 'content_time_future'
    if v.rule_ref is None or v.state=='unknown': return 'freshness_rule_or_verdict_missing'
    if v.observation_ref!=o.observation_ref or v.version_ref!=o.version_ref or v.result_sha256!=_result_sha(o):
        return 'freshness_binding_mismatch'
    assessed=_time(v.assessed_at,True);until=_time(v.valid_until,True)
    if assessed is None or until is None or not content<=assessed<=now<until:
        return 'freshness_time_invalid'
    return 'fresh' if v.state=='fresh' else 'stale'


def arbitrate_result_sources(*, event_key, generation, as_of, expected_fields,
                             current, candidates, manual_locked=False):
    """Suggestions only. No TTL calculation, authority certification or writer call."""
    _text(event_key);now=_time(as_of)
    if type(generation) is not int or generation<0 or type(manual_locked) is not bool: raise ValueError('request_contract')
    if type(expected_fields) is not tuple or not 1<=len(expected_fields)<=128: raise ValueError('expected_fields_contract')
    for key in expected_fields: _text(key,128)
    expected=set(expected_fields)
    if len(expected)!=len(expected_fields): raise ValueError('duplicate_expected_field')
    if type(candidates) is not tuple or len(candidates)>256: raise ValueError('candidate_limit')
    total=0;unique={}
    for o in ((current,) if current is not None else ())+candidates:
        total+=_validate(o)
        if total>1024*1024: raise ValueError('total_input_text_limit')
        if o.observation_ref in unique and _signature(unique[o.observation_ref])!=_signature(o):
            raise ValueError('observation_ref_conflict')
        unique.setdefault(o.observation_ref,o)
    retained=current.version_ref if current is not None and current.event_key==event_key and current.generation==generation else None
    states={ref:_eligibility(o,event_key,generation,now,expected) for ref,o in unique.items()}
    rejected=tuple(sorted((ref,s) for ref,s in states.items() if s!='fresh'))
    needed=tuple(ref for ref,_ in rejected)
    if current is not None and retained is None:
        return Arbitration('NEEDS_EVIDENCE','current_target_mismatch',None,rejected=rejected,evidence_needed=needed,blocked_capability='result')
    if manual_locked:
        return Arbitration('KEEP','manual_lock',retained,rejected=rejected,evidence_needed=needed)
    if current is not None and states[current.observation_ref] not in ('fresh','stale'):
        return Arbitration('NEEDS_EVIDENCE','current_evidence_unknown',retained,rejected=rejected,evidence_needed=needed,blocked_capability='result')
    fresh=[o for ref,o in unique.items() if states[ref]=='fresh']
    if not fresh:
        return Arbitration('NEEDS_EVIDENCE','no_fresh_qualified_result',retained,rejected=rejected,evidence_needed=needed,blocked_capability='result')
    if len({_result_sha(o) for o in fresh})>1:
        origins={}
        for o in fresh: origins.setdefault(o.origin_group,set()).add(_result_sha(o))
        reason='same_origin_result_conflict' if any(len(v)>1 for v in origins.values()) else 'independent_result_conflict'
        return Arbitration('CONFLICT',reason,retained,rejected=rejected,evidence_needed=tuple(sorted(o.observation_ref for o in fresh)),blocked_capability='result')
    if current is not None and states[current.observation_ref]=='fresh':
        return Arbitration('KEEP','valid_current_result',retained,rejected=rejected,evidence_needed=needed)
    # Payload conflicts were resolved to a gap above, never by rank or arrival order.
    fresh.sort(key=lambda o:(o.provider_key,o.observation_ref,o.version_ref))
    fresh.sort(key=lambda o:_time(o.content_at),reverse=True)  # Exact microseconds, no float epoch.
    fresh.sort(key=lambda o:o.priority,reverse=True)
    chosen=fresh[0]
    return Arbitration('SELECT_BACKUP' if current else 'SELECT_CANDIDATE',
                       'old_primary_stale' if current else 'qualified_result_available',retained,
                       chosen.observation_ref,chosen.version_ref,_result_sha(chosen),
                       tuple(sorted((f.name,f.evidence_ref) for f in chosen.fields)),rejected,needed)
