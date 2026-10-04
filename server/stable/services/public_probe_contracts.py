"""O03 的来源无关纯合同；不访问 ORM、网络、时钟或投递渠道。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime

from stable.services import content_contracts as f01


@dataclass(frozen=True)
class ProbeDocument:
    wire_json: str

    def __post_init__(self):
        f01._require(type(self.wire_json) is str, 'wire_string')
        object.__setattr__(self, 'wire_json', f01._encode(f01._read(self.wire_json)))

    def to_dict(self):
        return json.loads(self.wire_json)

    def to_json(self):
        return self.wire_json


def _document(value):
    return ProbeDocument(f01._encode(value))


def _bool(value):
    f01._require(type(value) is bool, 'boolean_value')


def _stamp(value):
    f01._time(value)
    return datetime.fromisoformat(value)


def _anchor(raw):
    value = f01._read(raw)
    f01._object(value, 'scope_ref candidate_sha expectation_sha input_version entity')
    f01._text(value['scope_ref'])
    for key in ('candidate_sha', 'expectation_sha'):
        f01._hash(value[key])
    f01._version(value['input_version'])
    original = f01._read(value['entity'])
    f01._entity(value['entity'])
    f01._require(value['entity'] == original, 'noncanonical_entity')
    return value


def _bind(value, anchor):
    for key in ('scope_ref', 'candidate_sha', 'expectation_sha'):
        f01._require(value[key] == anchor[key], 'probe_anchor_binding')


def _optional_hash(value):
    if value is not None:
        f01._hash(value)


def _batch(value):
    value = f01._read(value)
    f01._require(type(value) is list and len(value) <= 256, 'batch_limit')
    return value


def compare_public(expected, receipt, *, anchor, as_of):
    """比较显式 fake 规范摘要；保留时段，不分类端到端 SLA。"""
    a = _anchor(anchor)
    now = _stamp(as_of)
    e = f01._read(expected)
    f01._object(e, 'schema_version scope_ref candidate_sha input_version entity capability surface_ref audience_ref generation revision_ref permission_version content_digest visibility')
    f01._require(e['schema_version'] == 'o03.expected.v1', 'probe_schema')
    f01._version(e['input_version'])
    original = f01._read(e['entity'])
    f01._entity(e['entity'])
    f01._require(original == e['entity'], 'noncanonical_entity')
    f01._enum(e['capability'], f01.CAPABILITIES)
    for key in ('scope_ref', 'surface_ref', 'audience_ref', 'generation'):
        f01._text(e[key])
    f01._hash(e['candidate_sha'])
    for key in ('revision_ref', 'permission_version'):
        f01._text(e[key], nullable=True)
    _optional_hash(e['content_digest'])
    f01._enum(e['visibility'], ('visible', 'withdrawn'))
    f01._require(f01._sha(e) == a['expectation_sha'], 'expectation_digest')
    for key in ('scope_ref', 'candidate_sha', 'input_version', 'entity'):
        f01._require(e[key] == a[key], 'expected_anchor_binding')

    r = f01._read(receipt)
    f01._object(r, 'schema_version scope_ref candidate_sha expectation_sha input_version entity capability surface_ref audience_ref generation receipt_id request_started_at response_completed_at clock_error_ms status complete conflict denial_verified marker body_digest')
    f01._require(r['schema_version'] == 'o03.read.v1', 'probe_schema')
    _bind(r, a)
    f01._version(r['input_version'])
    original = f01._read(r['entity'])
    f01._entity(r['entity'])
    f01._require(original == r['entity'], 'noncanonical_entity')
    for key in ('input_version', 'entity', 'capability', 'surface_ref', 'audience_ref', 'generation'):
        f01._require(r[key] == e[key], 'receipt_expected_binding')
    f01._text(r['receipt_id'])
    start, end = _stamp(r['request_started_at']), _stamp(r['response_completed_at'])
    f01._require(start <= end <= now, 'receipt_time_order')
    f01._count(r['clock_error_ms'], nullable=True)
    f01._require(type(r['status']) is int and 100 <= r['status'] <= 599, 'http_status')
    for key in ('complete', 'conflict', 'denial_verified'):
        _bool(r[key])
    _optional_hash(r['body_digest'])
    marker = r['marker']
    if marker is not None:
        f01._object(marker, 'revision_ref permission_version content_digest')
        for key in ('revision_ref', 'permission_version'):
            f01._text(marker[key], nullable=True)
        _optional_hash(marker['content_digest'])

    reason, status = 'missing_evidence', 'visibility_unverified'
    common = (r['complete'] and not r['conflict'] and r['clock_error_ms'] is not None
              and e['entity']['identity_state'] == 'verified' and e['entity']['canonical_id'] is not None
              and marker is not None and e['permission_version'] is not None)
    if common and e['visibility'] == 'withdrawn':
        if (r['status'] in (403, 404) and r['denial_verified']
                and marker['permission_version'] == e['permission_version']
                and marker['revision_ref'] is None and marker['content_digest'] is None
                and r['body_digest'] is None):
            status, reason = 'withdrawal_verified', 'expected_denial'
        else:
            reason = 'withdrawal_not_verified'
    elif common and e['visibility'] == 'visible':
        if (r['status'] == 200 and not r['denial_verified']
                and e['revision_ref'] is not None and e['content_digest'] is not None
                and marker == {key: e[key] for key in ('revision_ref', 'permission_version', 'content_digest')}
                and r['body_digest'] == e['content_digest']):
            status, reason = 'public_read_verified', 'matching_normalized_content'
        else:
            reason = 'content_or_response_mismatch'
    return _document(dict(status=status, reason=reason,
        public_read_verified=status == 'public_read_verified',
        withdrawal_verified=status == 'withdrawal_verified', sla='unverified',
        request_interval=[r['request_started_at'], r['response_completed_at']],
        clock_error_ms=r['clock_error_ms'], receipt_id=r['receipt_id'],
        expectation_sha=a['expectation_sha']))


def _ordered_unique(values, *, id_key, time_key, anchor, as_of):
    seen, last, result = {}, None, []
    for value in values:
        _bind(value, anchor)
        f01._text(value[id_key])
        stamp = _stamp(value[time_key])
        f01._require(stamp <= as_of, 'future_receipt')
        identity, digest = value[id_key], f01._sha(value)
        if identity in seen:
            f01._require(seen[identity] == digest, 'receipt_id_conflict')
            continue
        key = (stamp, identity)
        f01._require(last is None or key > last, 'receipt_order')
        seen[identity], last = digest, key
        result.append(value)
    return result


def _microseconds(left, right):
    delta = left - right
    return ((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds)


def evaluate_cycles(policy, receipts, *, anchor, as_of):
    """以显式半开槽核验完成；不把活性等同业务健康或宿主覆盖。"""
    a, now = _anchor(anchor), _stamp(as_of)
    p = f01._read(policy)
    f01._object(p, 'schema_version scope_ref candidate_sha expectation_sha epoch epoch_started_at period_ms consecutive_misses clock_error_ms host_watchdog_bound')
    f01._require(p['schema_version'] == 'o03.cycles.v1', 'probe_schema')
    _bind(p, a)
    f01._text(p['epoch'])
    epoch_start = _stamp(p['epoch_started_at'])
    f01._require(epoch_start <= now, 'epoch_future')
    for key in ('period_ms', 'consecutive_misses'):
        f01._count(p[key])
        f01._require(p[key] > 0, 'positive_value')
    f01._count(p['clock_error_ms'], nullable=True)
    _bool(p['host_watchdog_bound'])
    rows = _batch(receipts)
    for r in rows:
        f01._object(r, 'receipt_id scope_ref candidate_sha expectation_sha epoch started_at completed_at coverage_complete all_healthy')
        f01._require(r['epoch'] == p['epoch'], 'epoch_mismatch')
        start = _stamp(r['started_at'])
        f01._require(epoch_start <= start, 'receipt_before_epoch')
        if r['completed_at'] is not None:
            end = _stamp(r['completed_at'])
            f01._require(start <= end <= now, 'receipt_time_order')
        _bool(r['coverage_complete'])
        if r['all_healthy'] is not None:
            _bool(r['all_healthy'])
    rows = _ordered_unique(rows, id_key='receipt_id', time_key='started_at', anchor=a, as_of=now)
    output = dict(cycle_status='unknown', business_status='unknown', closed_slots=None,
                  consecutive_missing=None, host_status='host_bound' if p['host_watchdog_bound'] else 'host_unverified')
    if p['clock_error_ms'] is None:
        return _document(output)
    period, error = p['period_ms'] * 1000, p['clock_error_ms'] * 1000
    closed = max(0, (_microseconds(now, epoch_start) - error) // period)
    proven = {}
    for r in rows:
        if r['completed_at'] is None or not r['coverage_complete']:
            continue
        slot = _microseconds(_stamp(r['started_at']), epoch_start) // period
        end = _microseconds(_stamp(r['completed_at']), epoch_start)
        if end - error >= slot * period and end + error < (slot + 1) * period:
            f01._require(slot not in proven, 'cycle_slot_conflict')
            proven[slot] = r
    last_proven = max((slot for slot in proven if slot < closed), default=-1)
    missing = closed - last_proven - 1
    output.update(closed_slots=closed, consecutive_missing=missing)
    if not closed:
        output['cycle_status'] = 'not_evaluable'
    elif missing >= p['consecutive_misses']:
        output['cycle_status'] = 'stalled'
    elif missing:
        output['cycle_status'] = 'gap'
    else:
        output['cycle_status'] = 'fresh'
        healthy = proven[closed - 1]['all_healthy']
        output['business_status'] = 'unknown' if healthy is None else ('healthy' if healthy else 'unhealthy')
    return _document(output)


def reconcile_episodes(events, *, anchor, as_of):
    """从有限有序历史重放纯事件建议；无持久化或通知投递。"""
    a, now = _anchor(anchor), _stamp(as_of)
    rows = _batch(events)
    for event in rows:
        f01._object(event, 'event_id scope_ref candidate_sha expectation_sha recorded_at generation supersedes_generation required_reasons checks')
        f01._text(event['generation'])
        f01._text(event['supersedes_generation'], nullable=True)
        reasons = event['required_reasons']
        f01._require(type(reasons) is list and bool(reasons), 'required_reasons')
        f01._require(reasons == f01._strings(reasons), 'noncanonical_reasons')
        f01._require(type(event['checks']) is dict and set(event['checks']) == set(reasons), 'check_fields')
        for check in event['checks'].values():
            f01._enum(check, ('healthy', 'unhealthy', 'unknown'))
    rows = _ordered_unique(rows, id_key='event_id', time_key='recorded_at', anchor=a, as_of=now)
    generations, current, required, episode = set(), None, None, None
    history, transitions = [], []
    for event in rows:
        generation = event['generation']
        if generation != current:
            if current is None:
                f01._require(event['supersedes_generation'] is None, 'initial_generation_predecessor')
            else:
                f01._require(generation not in generations and event['supersedes_generation'] == current,
                             'generation_successor')
                if episode is not None and episode['status'] == 'open':
                    episode['superseded_by'] = generation
            generations.add(generation)
            current, required, episode = generation, event['required_reasons'], None
        else:
            f01._require(event['supersedes_generation'] is None, 'duplicate_generation_predecessor')
            f01._require(event['required_reasons'] == required, 'generation_reason_change')
        previous = episode['reasons'] if episode is not None and episode['status'] == 'open' else {}
        issues = {}
        for reason, check in event['checks'].items():
            if check != 'healthy':
                issues[reason] = previous.get(reason, 'unknown') if check == 'unknown' else 'unhealthy'
        kind = None
        if issues and (episode is None or episode['status'] == 'resolved'):
            episode = dict(generation=generation,
                episode_number=1 + sum(item['generation'] == generation for item in history),
                status='open', reasons=issues, opened_at=event['recorded_at'],
                updated_at=event['recorded_at'], resolved_at=None, superseded_by=None)
            history.append(episode)
            kind = 'OPEN'
        elif issues and previous != issues:
            episode.update(reasons=issues, updated_at=event['recorded_at'])
            kind = 'CHANGED'
        elif not issues and episode is not None and episode['status'] == 'open':
            # 每一个 required reason 均明确 healthy；unknown 不会走到此处。
            episode.update(status='resolved', reasons={}, updated_at=event['recorded_at'],
                           resolved_at=event['recorded_at'])
            kind = 'RESOLVED'
        if kind is not None:
            transitions.append(dict(kind=kind, event_id=event['event_id'], generation=generation,
                episode_number=episode['episode_number'], recorded_at=event['recorded_at'],
                reasons=f01._read(episode['reasons'])))
    return _document(dict(current_generation=current, episodes=history, transitions=transitions,
                          delivery_status='not_attempted'))


def check_budget(budget, usage):
    """注入 fixture 上限的纯预算比较；没有生产默认值。"""
    b, rows = f01._read(budget), _batch(usage)
    f01._object(b, 'targets period_ms request_timeout_ms overhead_ms request_cap wire_cap decoded_cap cycle_cap')
    for key, value in b.items():
        f01._count(value)
        if key != 'overhead_ms':
            f01._require(value > 0, 'positive_value')
    reasons, cycle_bytes = set(), 0
    for row in rows:
        f01._object(row, 'request_bytes wire_bytes decoded_bytes')
        for measure, cap in (('request_bytes', 'request_cap'), ('wire_bytes', 'wire_cap'), ('decoded_bytes', 'decoded_cap')):
            f01._count(row[measure])
            cycle_bytes += row[measure]
            if row[measure] > b[cap]:
                reasons.add(measure + '_exceeded')
    required = b['targets'] * b['request_timeout_ms'] + b['overhead_ms']
    if required > b['period_ms']:
        reasons.add('time_budget_exceeded')
    if cycle_bytes > b['cycle_cap']:
        reasons.add('cycle_bytes_exceeded')
    if len(rows) < b['targets']:
        reasons.add('coverage_unknown')
    if len(rows) > b['targets']:
        reasons.add('count_conflict')
    status = 'budget_verified' if not reasons else (
        'coverage_unknown' if reasons == {'coverage_unknown'} else 'budget_exceeded')
    return _document(dict(status=status, reasons=sorted(reasons), coverage_complete=len(rows) == b['targets'],
        expected_targets=b['targets'], observed_targets=len(rows), time_required_ms=required,
        cycle_bytes=cycle_bytes, configuration_status='fixture_only'))
