"""R01 pure contracts, pinned to F01: no ORM, I/O or implicit clock.

Caller supplied digests/receipts bind inputs, not their real-world truth. Missing
origins, scope or external probe coverage cannot be inferred from this report.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from stable.services import content_contracts as f01

ContractError = f01.ContractError
MAX_TARGETS = 1000
MAX_RECORDS = 5000


def require(condition, code):
    if not condition:
        raise ContractError(code)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()), 'r01_fields')


def text(value, nullable=False):
    require((nullable and value is None) or (type(value) is str and 0 < len(value) <= 4096), 'r01_text')


def boolean(value):
    require(type(value) is bool, 'r01_boolean')


def strings(value, empty=True):
    require(type(value) is list and len(value) <= MAX_RECORDS, 'r01_list')
    for item in value:
        text(item)
    require(len(set(value)) == len(value) and (empty or bool(value)), 'r01_references')


def stamp(value, nullable=False):
    # F01 owns UTC precision/shape. Reuse its pinned validator, never local now.
    f01._time(value, nullable=nullable)
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value is not None else None


def interval(value):
    fields(value, 'start end')
    start, end = stamp(value['start']), stamp(value['end'])
    require(start < end, 'r01_interval')
    return start, end


def entity_key(entity):
    if entity['identity_state'] == 'verified':
        if entity['canonical_id'] is not None:
            return 'canonical:' + entity['canonical_id']
        return 'source:' + f01._sha(entity['source_refs'][0])
    return 'unknown:' + f01._sha(entity)


def _validate_report(value, expected_scope, expected_candidate, expected_coverage):
    fields(value, 'scope window as_of records coverage effective_intervals')
    f01._hash(expected_scope); f01._hash(expected_candidate); f01._hash(expected_coverage)
    scope = value['scope']
    fields(scope, 'schema_version scope_ref candidate_sha256 targets aliases complete_denominator')
    require(scope['schema_version'] == 'r01.scope.v1', 'r01_schema')
    text(scope['scope_ref']); boolean(scope['complete_denominator'])
    require(f01._sha(scope) == expected_scope, 'r01_scope_binding')
    require(scope['candidate_sha256'] == expected_candidate, 'r01_candidate_binding')
    fields(value['window'], 'id start end'); text(value['window']['id'])
    interval({k: value['window'][k] for k in ('start', 'end')})
    as_of = stamp(value['as_of'])
    require(type(scope['targets']) is list and len(scope['targets']) <= MAX_TARGETS, 'r01_targets_limit')
    targets = {}
    for target in scope['targets']:
        fields(target, 'key event_id region material_availability required_intervals audit_fields versions current_input_version')
        text(target['key']); text(target['region'], nullable=True)
        require(target['material_availability'] in ('available', 'missing', 'unknown'), 'r01_material_availability')
        event_id = target['event_id']
        require(event_id is None or (type(event_id) is int and 0 < event_id <= 2**63-1), 'r01_event_id')
        require(target['key'] not in targets, 'r01_duplicate_target')
        strings(target['audit_fields'], empty=False)
        require(type(target['required_intervals']) is list and len(target['required_intervals']) <= MAX_TARGETS, 'r01_required_intervals')
        for period in target['required_intervals']:
            interval(period)
        require(type(target['versions']) is list and 0 < len(target['versions']) <= 100, 'r01_versions')
        versions = []
        for raw in target['versions']:
            document = f01.parse_input(raw).to_dict()
            entity = document['snapshot']['entity']
            require(entity['kind'] == 'race_event' and entity_key(entity) == target['key'], 'r01_entity_binding')
            require(event_id is None or entity['canonical_id'] == str(event_id), 'r01_event_binding')
            versions.append(document['input_version'])
        require(len({f01._encode(v) for v in versions}) == len(versions), 'r01_duplicate_version')
        require(target['current_input_version'] in versions, 'r01_current_version')
        targets[target['key']] = target
    require(type(scope['aliases']) is list and len(scope['aliases']) <= MAX_TARGETS, 'r01_aliases')
    aliases = {}
    for alias in scope['aliases']:
        fields(alias, 'alias target evidence_refs'); text(alias['alias']); text(alias['target']); strings(alias['evidence_refs'], empty=False)
        require(alias['alias'] in targets and alias['target'] in targets and alias['alias'] != alias['target'], 'r01_alias_target')
        require(alias['alias'] not in aliases, 'r01_duplicate_alias')
        # Never auto-match entity names or collapse unresolved identity candidates.
        require(not alias['alias'].startswith('unknown:') and not alias['target'].startswith('unknown:'), 'r01_alias_identity_unknown')
        aliases[alias['alias']] = alias['target']
    for key in aliases:
        seen = set()
        while key in aliases:
            require(key not in seen, 'r01_alias_cycle')
            seen.add(key); key = aliases[key]
    coverage = value['coverage']
    fields(coverage, 'scope_sha256 expected_record_ids proof_ref complete gaps window as_of')
    require(f01._sha(coverage) == expected_coverage, 'r01_coverage_binding')
    require(coverage['window'] == value['window'] and coverage['as_of'] == value['as_of'], 'r01_coverage_cutoff')
    require(coverage['scope_sha256'] == expected_scope, 'r01_coverage_scope')
    boolean(coverage['complete']); strings(coverage['expected_record_ids']); strings(coverage['gaps'])
    text(coverage['proof_ref'], nullable=True)
    if coverage['complete']:
        require(coverage['proof_ref'] is not None and not coverage['gaps'], 'r01_coverage_proof')
    require(type(value['records']) is list and len(value['records']) <= MAX_RECORDS, 'r01_records_limit')
    records = {}
    for row in value['records']:
        fields(row, 'record_id target_key input_version occurred_at recorded_at kind reason_code evidence_refs payload')
        text(row['record_id']); text(row['reason_code']); strings(row['evidence_refs'], empty=False)
        require(type(row['target_key']) is str and row['target_key'] in targets, 'r01_record_target')
        target = targets[row['target_key']]
        require(row['input_version'] in [v['input_version'] for v in target['versions']], 'r01_record_version')
        occurred = stamp(row['occurred_at'], nullable=True)
        recorded = stamp(row['recorded_at'])
        require(recorded <= as_of and (occurred is None or occurred <= recorded), 'r01_receipt_time')
        require(occurred is None or occurred <= as_of, 'r01_future_receipt')
        require(row['kind'] in ('audit', 'transport', 'deadline', 'repair'), 'r01_record_kind')
        payload = row['payload']
        if row['kind'] == 'audit':
            fields(payload, 'rule_version auditor_ref checked_fields error_fields complete severe')
            text(payload['rule_version']); text(payload['auditor_ref'])
            strings(payload['checked_fields']); strings(payload['error_fields'])
            boolean(payload['complete']); boolean(payload['severe'])
            require(set(payload['error_fields']) <= set(payload['checked_fields']) <= set(target['audit_fields']), 'r01_audit_fields')
            require(not payload['complete'] or set(payload['checked_fields']) == set(target['audit_fields']), 'r01_audit_incomplete')
            require(not payload['severe'] or bool(payload['error_fields']), 'r01_severe_without_error')
        elif row['kind'] == 'deadline':
            fields(payload, 'deadline_at stage'); stamp(payload['deadline_at']); text(payload['stage'])
            require(occurred is None or stamp(payload['deadline_at']) <= occurred, 'r01_deadline_order')
        elif row['kind'] == 'repair':
            fields(payload, 'resolves resolved_versions resolved_fields'); strings(payload['resolves'], empty=False)
            require(type(payload['resolved_versions']) is dict and type(payload['resolved_fields']) is dict and
                    set(payload['resolved_versions']) == set(payload['resolves']) == set(payload['resolved_fields']), 'r01_repair_shape')
        else:
            fields(payload, '')
        if row['record_id'] in records:
            require(records[row['record_id']] == row, 'r01_duplicate_receipt_conflict')
        records[row['record_id']] = row
    for row in records.values():
        if row['kind'] == 'repair':
            for ref in row['payload']['resolves']:
                require(ref in records, 'r01_repair_reference')
                old = records[ref]
                require(old['kind'] != 'repair' and old['target_key'] == row['target_key'], 'r01_repair_binding')
                require(row['payload']['resolved_versions'][ref] == old['input_version'], 'r01_repair_version')
                resolved_fields = row['payload']['resolved_fields'][ref]
                strings(resolved_fields, empty=old['kind'] != 'audit')
                if old['kind'] == 'audit':
                    require(bool(old['payload']['error_fields']) and set(resolved_fields) <= set(old['payload']['error_fields']), 'r01_repair_error_fields')
                else:
                    require(not resolved_fields, 'r01_repair_error_fields')
                # Unknown occurrence is never invented. An explicit version-bound
                # repair can still prove resolution at its own known time.
                require(row['occurred_at'] is not None and (old['occurred_at'] is None or
                        stamp(old['occurred_at']) <= stamp(row['occurred_at'])) and
                        stamp(old['recorded_at']) <= stamp(row['recorded_at']), 'r01_repair_order')
    expected = set(coverage['expected_record_ids'])
    require(set(records) <= expected, 'r01_origin_unexpected')
    require(not coverage['complete'] or set(records) == expected, 'r01_origin_missing')
    require(type(value['effective_intervals']) is list and len(value['effective_intervals']) <= MAX_RECORDS, 'r01_effective_limit')
    for period in value['effective_intervals']:
        fields(period, 'start end candidate_sha256 proof_ref')
        interval({k: period[k] for k in ('start', 'end')})
        require(period['candidate_sha256'] == expected_candidate, 'r01_effective_candidate')
        text(period['proof_ref'])


@dataclass(frozen=True)
class ReportInput:
    wire_json: str
    expected_scope_sha256: str
    expected_candidate_sha256: str
    expected_coverage_sha256: str

    def __post_init__(self):
        value = f01._read(self.wire_json)
        _validate_report(value, self.expected_scope_sha256, self.expected_candidate_sha256, self.expected_coverage_sha256)
        object.__setattr__(self, 'wire_json', f01._encode(value))

    def to_dict(self):
        return json.loads(self.wire_json)


def parse_report(value, *, expected_scope_sha256, expected_candidate_sha256, expected_coverage_sha256):
    return ReportInput(f01._encode(f01._read(value)), expected_scope_sha256, expected_candidate_sha256, expected_coverage_sha256)


def _microseconds(delta):
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _union_duration(periods, start, end):
    if end <= start:
        return 0
    clipped = sorted((max(a, start), min(b, end)) for a, b in periods if a < end and b > start)
    merged = []
    for a, b in clipped:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return sum(_microseconds(b - a) for a, b in merged)


def summarize(document):
    require(type(document) is ReportInput, 'r01_report_type')
    value = document.to_dict()
    window = value['window']; start, end = stamp(window['start']), stamp(window['end'])
    as_of = stamp(value['as_of']); cutoff = min(end, as_of)
    scope = value['scope']; aliases = {a['alias']: a['target'] for a in scope['aliases']}

    def canonical(key):
        while key in aliases:
            key = aliases[key]
        return key

    targets = {}
    for target in scope['targets']:
        targets.setdefault(canonical(target['key']), []).append(target)
    required = {key for key, group in targets.items() if any(
        stamp(period['start']) < cutoff and stamp(period['end']) > start
        for target in group for period in target['required_intervals'])}
    records = {r['record_id']: r for r in value['records']}
    in_window = []
    unknown_time = []
    for row in records.values():
        occurred = stamp(row['occurred_at'], nullable=True)
        if occurred is None:
            unknown_time.append(row['record_id'])
        elif start <= occurred < end and occurred <= as_of:
            in_window.append(row)
    audited, partial, information_errors, severe, transport, stalled = (set() for _ in range(6))
    for row in in_window:
        key = canonical(row['target_key']); payload = row['payload']
        if row['kind'] == 'audit':
            (audited if payload['complete'] else partial).add(key)
            if payload['complete'] and payload['error_fields']:
                information_errors.add(key)
            if payload['severe']:
                severe.add(key)
        elif row['kind'] == 'transport':
            transport.add(key)
        # Deadline attribution uses the obligation clock, not receipt arrival.
    # A received, known-time violation may arrive after the window ended.
    for row in records.values():
        if (row['kind'] == 'deadline' and row['occurred_at'] is not None and
                start <= stamp(row['payload']['deadline_at']) < end and canonical(row['target_key']) in required):
            stalled.add(canonical(row['target_key']))
    availability = {}
    regions = {}
    for key, group in targets.items():
        states = {t['material_availability'] for t in group}
        availability[key] = next(iter(states)) if len(states) == 1 else 'unknown'
        region_set = {t['region'] for t in group}
        region = next(iter(region_set)) if len(region_set) == 1 else None
        regions.setdefault(region or 'unknown', []).append(key)
    # Partial repairs close only their referenced fields/version. Keep the
    # earliest time at which all errors in the original receipt were resolved.
    repaired_at = {}
    remaining = {r['record_id']: set(r['payload']['error_fields']) if r['kind'] == 'audit' else set()
                 for r in records.values() if r['kind'] != 'repair'}
    repairs = sorted((r for r in records.values() if r['kind'] == 'repair'),
                     key=lambda r: (stamp(r['occurred_at']), r['record_id']))
    for row in repairs:
        for ref in row['payload']['resolves']:
            remaining[ref].difference_update(row['payload']['resolved_fields'][ref])
            if not remaining[ref] and ref not in repaired_at:
                repaired_at[ref] = stamp(row['occurred_at'])
    historical_severe = [r for r in records.values() if r['kind'] == 'audit' and r['payload']['severe']]
    open_severe = [r for r in historical_severe if r['record_id'] not in repaired_at]
    open_severe_targets = {canonical(r['target_key']) for r in open_severe}
    historical_severe_targets = {canonical(r['target_key']) for r in historical_severe}
    carryover = []
    for row in records.values():
        occurred = stamp(row['occurred_at'], nullable=True)
        issue = row['kind'] in ('transport', 'deadline') or (row['kind'] == 'audit' and row['payload']['error_fields'])
        basis = stamp(row['payload']['deadline_at']) if row['kind'] == 'deadline' and occurred is not None else occurred
        if issue and basis is not None and basis < start and repaired_at.get(row['record_id'], start) >= start:
            carryover.append(row['record_id'])
    effective = _union_duration([(stamp(p['start']), stamp(p['end'])) for p in value['effective_intervals']], start, cutoff)
    planned = _microseconds(end - start)
    elapsed = max(0, _microseconds(cutoff - start))
    coverage = value['coverage']
    missing_origins = sorted(set(coverage['expected_record_ids']) - set(records))
    record_complete = coverage['complete'] and not coverage['gaps'] and not missing_origins and not unknown_time
    return dict(window_id=window['id'], start=window['start'], end=window['end'], as_of=value['as_of'],
        candidate_sha256=scope['candidate_sha256'], scope_sha256=document.expected_scope_sha256, coverage_sha256=document.expected_coverage_sha256,
        targets=len(targets), required_targets=len(required), audited=len(audited),
        information_error_targets=len(information_errors), information_error_rate=len(information_errors)/len(audited) if audited else None,
        stalled_targets=len(stalled), stalled_rate=len(stalled)/len(required) if required else None,
        partial_audit_targets=len(partial-audited), unreviewed_targets=len(set(targets)-audited-partial),
        available_targets=sum(s == 'available' for s in availability.values()),
        missing_material_targets=sum(s == 'missing' for s in availability.values()),
        material_unknown_targets=sum(s == 'unknown' for s in availability.values()),
        information_audit_coverage=len(audited)/len(targets) if targets else None,
        material_coverage=sum(s == 'available' for s in availability.values())/len(targets) if targets else None,
        transport_failed_targets=len(transport), severe_error_targets=len(open_severe_targets), blocking=bool(open_severe_targets),
        open_severe_error_targets=len(open_severe_targets), open_severe_record_ids=sorted(r['record_id'] for r in open_severe),
        window_severe_error_targets=len(severe), historical_severe_error_targets=len(historical_severe_targets),
        region_counts={region: len(keys) for region, keys in sorted(regions.items())},
        unresolved_target_count=sum(key.startswith('unknown:') for key in targets),
        complete_denominator=scope['complete_denominator'] and not any(k.startswith('unknown:') for k in targets), record_coverage_complete=record_complete,
        coverage_gaps=coverage['gaps'], missing_origin_ids=missing_origins, unknown_time_record_ids=sorted(unknown_time),
        history=sorted(records.values(), key=lambda r: r['record_id']), carryover_record_ids=sorted(carryover),
        effective_microseconds=effective, planned_microseconds=planned, elapsed_microseconds=elapsed,
        full_window_evidence=as_of >= end and effective == planned,
        measurement_complete=bool(targets) and scope['complete_denominator'] and record_complete and
            not any(k.startswith('unknown:') for k in targets) and all(s == 'available' for s in availability.values()) and
            len(audited) == len(targets) and as_of >= end and effective == planned)




def _validate_latency(value, expected_context):
    fields(value, 'context probe'); f01._hash(expected_context)
    context = value['context']
    fields(context, 'candidate_sha256 target_key capability document source_evidence_id material_content_sha256 public_version permission_version threshold_seconds source_clock_trusted as_of')
    require(f01._sha(context) == expected_context, 'r01_latency_context')
    f01._hash(context['candidate_sha256']); f01._hash(context['material_content_sha256'])
    text(context['public_version']); text(context['permission_version']); text(context['source_evidence_id'])
    require(type(context['threshold_seconds']) is int and context['threshold_seconds'] in (300, 600), 'r01_threshold')
    boolean(context['source_clock_trusted']); as_of = stamp(context['as_of'])
    document = f01.parse_input(context['document']).to_dict()
    entity = document['snapshot']['entity']
    require(entity['kind'] == 'race_event' and entity_key(entity) == context['target_key'] and entity['identity_state'] == 'verified', 'r01_latency_target')
    evidence = [e for e in document['snapshot']['evidence'] if e['evidence_id'] == context['source_evidence_id']]
    require(len(evidence) == 1, 'r01_latency_source')
    require(type(context['capability']) is str and context['capability'] in f01.CAPABILITIES and evidence[0]['capability'] == context['capability'], 'r01_latency_capability')
    probe = value['probe']
    if probe is None:
        return
    fields(probe, 'external target_key input_version material_content_sha256 public_version permission_version first_visible_at last_not_visible_at stable_interval evidence_refs clock_trusted')
    boolean(probe['external']); boolean(probe['stable_interval']); boolean(probe['clock_trusted'])
    strings(probe['evidence_refs'], empty=False)
    require(stamp(probe['first_visible_at']) <= as_of, 'r01_future_probe')
    absent = stamp(probe['last_not_visible_at'], nullable=True)
    require(absent is None or absent <= as_of, 'r01_future_probe')
    require(probe['input_version'] == document['input_version'], 'r01_probe_input_version')
    require(all(probe[k] == context[k] for k in ('target_key', 'material_content_sha256', 'public_version', 'permission_version')), 'r01_probe_version')


@dataclass(frozen=True)
class LatencyInput:
    wire_json: str
    expected_context_sha256: str

    def __post_init__(self):
        value = f01._read(self.wire_json)
        _validate_latency(value, self.expected_context_sha256)
        object.__setattr__(self, 'wire_json', f01._encode(value))

    def to_dict(self):
        return json.loads(self.wire_json)


def parse_latency(value, *, expected_context_sha256):
    return LatencyInput(f01._encode(f01._read(value)), expected_context_sha256)


@dataclass(frozen=True)
class LatencyBounds:
    lower_microseconds: int
    upper_microseconds: int
    lower_open: bool
    upper_open: bool
    upper_bound_only: bool

    def __post_init__(self):
        require(type(self.lower_microseconds) is int and type(self.upper_microseconds) is int and
                0 <= self.lower_microseconds <= self.upper_microseconds, 'r01_latency_bounds')
        for flag in (self.lower_open, self.upper_open, self.upper_bound_only):
            boolean(flag)
        require(self.lower_microseconds != self.upper_microseconds or not (self.lower_open or self.upper_open), 'r01_empty_bounds')


def classify_bounds(bounds, threshold_seconds):
    require(type(bounds) is LatencyBounds, 'r01_bounds_type')
    require(type(threshold_seconds) is int and threshold_seconds in (300, 600), 'r01_threshold')
    threshold = threshold_seconds * 1000000
    if bounds.upper_microseconds <= threshold:
        return 'proven_met'
    if not bounds.upper_bound_only and (bounds.lower_microseconds > threshold or
            (bounds.lower_microseconds == threshold and bounds.lower_open)):
        return 'proven_late'
    return 'indeterminate'


def evaluate_latency(document):
    require(type(document) is LatencyInput, 'r01_latency_type')
    value = document.to_dict(); context, probe = value['context'], value['probe']
    source = next(e['source_time'] for e in context['document']['snapshot']['evidence']
                  if e['evidence_id'] == context['source_evidence_id'])
    result = dict(status='', source_precision=source['precision'], threshold_seconds=context['threshold_seconds'],
                  lower_microseconds=None, upper_microseconds=None, lower_open=None, upper_open=None, upper_bound_only=None)
    if probe is None or not probe['external']:
        result['status'] = 'visibility_unverified'; return result
    if source['precision'] == 'unknown':
        result['status'] = 'source_time_unknown'; return result
    if not context['source_clock_trusted'] or not probe['clock_trusted']:
        result['status'] = 'clock_unknown'; return result
    if source['precision'] == 'exact':
        a = b = stamp(source['published_at']); source_open = False
    else:
        a, b = stamp(source['last_absent_at']), stamp(source['first_seen_at']); source_open = True
        if a >= b:
            result['status'] = 'clock_anomaly'; return result
    visible = stamp(probe['first_visible_at'])
    absent = stamp(probe['last_not_visible_at'], nullable=True)
    if absent is not None and absent >= visible:
        result['status'] = 'clock_anomaly'; return result
    upper_only = absent is None or not probe['stable_interval']
    lower = _microseconds((visible if upper_only else absent) - b)
    upper = _microseconds(visible - a)
    lower_open = not upper_only
    upper_open = source_open
    if lower < 0 or upper < lower or (lower == upper and (lower_open or upper_open)):
        result['status'] = 'clock_anomaly'; return result
    bounds = LatencyBounds(lower, upper, lower_open, upper_open, upper_only)
    result.update(status=classify_bounds(bounds, context['threshold_seconds']), lower_microseconds=lower,
                  upper_microseconds=upper, lower_open=lower_open, upper_open=upper_open, upper_bound_only=upper_only)
    return result
