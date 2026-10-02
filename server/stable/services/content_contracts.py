"""F01 immutable DTOs and strict serializers, with no ORM/network/clock access.

Validation proves shape and version binding only, never permission to fetch,
write or publish. Keep existing runtime authorization and CAS at the writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
import re

MAX_WIRE_BYTES = 1_048_576
MAX_DEPTH = 64
MAX_NODES = 100_000
INPUT_SCOPE = ('entity', 'evidence', 'materials', 'policy_ref', 'protection')
CAPABILITIES = frozenset(('identity', 'schedule', 'roster', 'withdrawal', 'result', 'correction', 'profile', 'career', 'name', 'relationship'))
MATURITIES = frozenset(('unknown', 'predicted', 'provisional', 'confirmed', 'corrected'))
FACT_PHASES = frozenset(('unknown', 'scheduled', 'running', 'finished', 'postponed', 'cancelled'))
CLOCK_HINTS = frozenset(('unknown', 'before_start', 'start_time_reached', 'result_deadline_reached', 'local_day_elapsed'))
ACTIONS = frozenset(('wait', 'discover_identity', 'refresh_schedule', 'refresh_roster', 'fetch_result', 'check_correction', 'reconcile_publication', 'operator_review'))
RUNNER_STATES = frozenset(('declared', 'running', 'scratched', 'withdrawn', 'reinstated', 'non_runner', 'unknown', 'finished', 'dead_heat', 'disqualified', 'did_not_finish', 'pulled_up', 'unseated_rider', 'fell', 'refused'))
DATA_FIELDS = {
    'identity': frozenset(('original_name', 'name_kind', 'namespace', 'external_id', 'birth_year', 'candidates')),
    'schedule': frozenset(('local_date', 'timezone_name', 'race_datetime', 'date_precision')),
    'roster': frozenset(('participants',)),
    'withdrawal': frozenset(('participants',)),
    'result': frozenset(('participants',)),
    'correction': frozenset(('participants',)),
    'profile': frozenset(('original_name', 'sex', 'birth_date', 'country', 'color', 'owner_name', 'trainer_name', 'breeder_name')),
    'career': frozenset(('horse_ref', 'official_or_source_start_count', 'collected_start_count', 'known_zero_control')),
    'name': frozenset(('original_name', 'display_name', 'name_kind', 'horse_ref')),
    'relationship': frozenset(('source_ref', 'target_ref', 'relation_type')),
}


class ContractError(ValueError):
    """Stable codes only, without source payloads or private field values."""


def _require(condition, code):
    if not condition:
        raise ContractError(code)


def _object(value, names):
    _require(type(value) is dict and set(value) == set(names.split()), 'object_fields')


def _text(value, *, nullable=False, empty=False):
    if nullable and value is None:
        return
    _require(type(value) is str and (empty or bool(value)), 'string_value')


def _enum(value, choices):
    _require(type(value) is str and value in choices, 'enum_value')


def _count(value, *, nullable=False):
    _require((nullable and value is None) or (type(value) is int and 0 <= value <= 2**63 - 1), 'integer_value')


def _time(value, *, nullable=False):
    if nullable and value is None:
        return
    _require(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value) is not None, 'utc_timestamp')
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ContractError('utc_timestamp') from None


def _hash(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'sha256_value')


def _strings(value):
    _require(type(value) is list, 'array_value')
    for item in value:
        _text(item)
    _require(len(value) == len(set(value)), 'duplicate_reference')
    return sorted(value)


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_encode(value).encode('utf-8')).hexdigest()


def _json_guard(value):
    # Check before deepcopy/serialization: reject custom containers/hooks/cycles.
    stack = [(value, 0, False)]
    active = set()
    count = 0
    while stack:
        item, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, 'document_limit')
        kind = type(item)
        _require(kind in (dict, list, str, int, float, bool, type(None)), 'json_type')
        if kind is float:
            _require(math.isfinite(item), 'nonfinite_value')
        if kind in (dict, list):
            _require(id(item) not in active, 'cyclic_document')
            active.add(id(item))
            stack.append((item, depth, True))
            if kind is dict:
                _require(all(type(k) is str for k in item), 'object_key')
                stack.extend((v, depth + 1, False) for v in item.values())
            else:
                stack.extend((v, depth + 1, False) for v in item)


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _read(value):
    try:
        if type(value) is str:
            _require(len(value.encode('utf-8')) <= MAX_WIRE_BYTES, 'document_limit')
            value = json.loads(value, object_pairs_hook=_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ContractError('nonfinite_value')))
        _json_guard(value)
        wire = _encode(value)
        _require(len(wire.encode('utf-8')) <= MAX_WIRE_BYTES, 'document_limit')
        return json.loads(wire)
    except ContractError:
        raise
    except (ValueError, RecursionError, UnicodeError, OverflowError):
        raise ContractError('invalid_json') from None


def _entity(value, *, public=False):
    _object(value, 'kind canonical_id source_refs identity_state candidate_ids evidence_refs')
    _enum(value['kind'], ('article', 'race_event', 'horse'))
    _enum(value['identity_state'], ('verified', 'ambiguous', 'unresolved', 'revoked'))
    _text(value['canonical_id'], nullable=True)
    _require(type(value['source_refs']) is list, 'array_value')
    for ref in value['source_refs']:
        _object(ref, 'source namespace external_id')
        for text in ref.values():
            _text(text)
    value['source_refs'].sort(key=lambda r: (r['source'], r['namespace'], r['external_id']))
    _require(len({_sha(r) for r in value['source_refs']}) == len(value['source_refs']), 'duplicate_source_ref')
    for key in ('candidate_ids', 'evidence_refs'):
        value[key] = _strings(value[key])
    if value['identity_state'] == 'ambiguous':
        _require(value['canonical_id'] is None, 'ambiguous_canonical')
    if value['identity_state'] == 'verified':
        _require(value['canonical_id'] is not None or len(value['source_refs']) == 1, 'identity_missing')
    if public:
        _require(not value['source_refs'] and not value['candidate_ids'] and not value['evidence_refs'], 'private_identity_refs')


def _protection(value, *, derive=False):
    keys = 'paused fields modules reason actor_ref changed_at'
    _object(value, keys if derive and 'protection_sha256' not in value else keys + ' protection_sha256')
    _require(type(value['paused']) is bool, 'boolean_value')
    for key in ('fields', 'modules'):
        value[key] = _strings(value[key])
    _text(value['reason'], empty=True)
    _text(value['actor_ref'], nullable=True)
    _time(value['changed_at'], nullable=True)
    digest = _sha({k: value[k] for k in keys.split()})
    if not derive:
        _hash(value['protection_sha256'])
        _require(value['protection_sha256'] == digest, 'protection_digest')
    value['protection_sha256'] = digest


def _evidence(value):
    _object(value, 'evidence_id provider_key source_class independence_key capability artifact_sha256 locator observed_at source_time contract_ref')
    for key in ('evidence_id', 'provider_key', 'independence_key', 'locator'):
        _text(value[key])
    _enum(value['source_class'], ('licensed_api', 'official_operator', 'trusted_publisher', 'community', 'manual_supplement'))
    _enum(value['capability'], CAPABILITIES)
    _hash(value['artifact_sha256'])
    _time(value['observed_at'])
    stamp = value['source_time']
    _object(stamp, 'precision published_at last_absent_at first_seen_at')
    _enum(stamp['precision'], ('exact', 'interval', 'unknown'))
    for key in ('published_at', 'last_absent_at', 'first_seen_at'):
        _time(stamp[key], nullable=True)
    if stamp['precision'] == 'exact':
        _require(stamp['published_at'] is not None, 'source_time_missing')
    if stamp['precision'] == 'interval':
        _require(stamp['last_absent_at'] is not None and stamp['first_seen_at'] is not None, 'source_interval_missing')
        _require(datetime.fromisoformat(stamp['last_absent_at']) <= datetime.fromisoformat(stamp['first_seen_at']), 'source_interval_order')
    contract = value['contract_ref']
    _object(contract, 'route_digest contract_digest proof_digest valid_until revoked')
    for key in ('route_digest', 'contract_digest', 'proof_digest'):
        _hash(contract[key])
    _time(contract['valid_until'])
    _require(type(contract['revoked']) is bool, 'boolean_value')


def _data(value, capability):
    _require(type(value) is dict and not set(value) - DATA_FIELDS[capability], 'material_data_fields')
    for key, item in value.items():
        if key == 'participants':
            _require(type(item) is list, 'array_value')
            for participant in item:
                _object(participant, 'stable_key horse_ref status')
                _text(participant['stable_key'])
                _text(participant['horse_ref'], nullable=True)
                _enum(participant['status'], RUNNER_STATES)
            _require(len({p['stable_key'] for p in item}) == len(item), 'duplicate_participant')
        elif key == 'candidates':
            _require(type(item) is list, 'array_value')
            for candidate in item:
                _object(candidate, 'id birth_year sire')
                _text(candidate['id']); _count(candidate['birth_year']); _text(candidate['sire'])
        elif key == 'known_zero_control':
            _object(item, 'horse_ref official_or_source_start_count validation')
            _text(item['horse_ref']); _count(item['official_or_source_start_count'], nullable=True)
            _enum(item['validation'], ('pending', 'passed', 'conflict', 'rejected'))
        elif key in ('official_or_source_start_count', 'collected_start_count', 'birth_year'):
            _count(item, nullable=key == 'official_or_source_start_count')
        elif key == 'race_datetime':
            _time(item, nullable=True)
        elif key in ('local_date', 'birth_date'):
            if item is None and key == 'birth_date':
                continue
            _text(item)
            try:
                _require(date.fromisoformat(item).isoformat() == item, 'calendar_date')
            except ValueError:
                raise ContractError('calendar_date') from None
        elif key == 'date_precision':
            _enum(item, ('exact', 'date_only', 'month', 'year', 'unknown'))
        elif key == 'name_kind':
            _enum(item, ('registered', 'official_latin', 'hk_assigned', 'pre_import', 'translation', 'source_display'))
        else:
            _text(item, nullable=True)
    if capability == 'roster':
        _require('participants' in value, 'roster_missing')


def _snapshot(raw, *, derive=False):
    value = _read(raw)
    _object(value, 'entity materials evidence protection policy_ref')
    _entity(value['entity'])
    _text(value['policy_ref'])
    _protection(value['protection'], derive=derive)
    _require(type(value['evidence']) is list and type(value['materials']) is list, 'array_value')
    for evidence in value['evidence']:
        _evidence(evidence)
    value['evidence'].sort(key=lambda e: e['evidence_id'])
    refs = {e['evidence_id'] for e in value['evidence']}
    _require(len(refs) == len(value['evidence']), 'duplicate_evidence')
    _require(set(value['entity']['evidence_refs']) <= refs, 'evidence_reference')
    for material in value['materials']:
        _object(material, 'capability maturity completeness validation revision_ref supersedes_ref evidence_refs data')
        _enum(material['capability'], CAPABILITIES)
        _enum(material['maturity'], MATURITIES)
        _enum(material['completeness'], ('unknown', 'partial', 'complete'))
        _enum(material['validation'], ('pending', 'passed', 'conflict', 'rejected'))
        _text(material['revision_ref'], nullable=True); _text(material['supersedes_ref'], nullable=True)
        material['evidence_refs'] = _strings(material['evidence_refs'])
        _require(set(material['evidence_refs']) <= refs, 'evidence_reference')
        _data(material['data'], material['capability'])
        if material['maturity'] == 'corrected':
            _require(material['supersedes_ref'] is not None and material['evidence_refs'], 'correction_evidence')
    value['materials'].sort(key=lambda m: (m['capability'], m['revision_ref'] or '', _sha(m)))
    return value


def _version(value):
    _object(value, 'schema_version scope content_sha256 generations')
    _require(value['schema_version'] == 'f01.input.v1', 'input_schema')
    _require(value['scope'] == _strings(value['scope']) == list(INPUT_SCOPE), 'input_scope')
    _hash(value['content_sha256'])
    _object(value['generations'], 'owner schedule enrollment source_set')
    for generation in value['generations'].values():
        _count(generation, nullable=True)


def _validate_input(value):
    _object(value, 'schema_version evaluated_at policy_ref input_version snapshot')
    _require(value['schema_version'] == 'f01.v1', 'schema_version')
    _time(value['evaluated_at']); _text(value['policy_ref'])
    _version(value['input_version'])
    snapshot = _snapshot(value['snapshot'])
    _require(snapshot == value['snapshot'], 'noncanonical_snapshot')
    _require(value['policy_ref'] == snapshot['policy_ref'], 'policy_binding')
    _require(value['input_version']['content_sha256'] == _sha(snapshot), 'content_digest')


def _public(value):
    _object(value, 'entity_ref public_version material_state fact_phase clock_hint updated_at completeness gaps')
    original = _read(value['entity_ref']); _entity(value['entity_ref'], public=True)
    _require(value['entity_ref'] == original, 'noncanonical_entity')
    _text(value['public_version']); _enum(value['material_state'], MATURITIES)
    _enum(value['fact_phase'], FACT_PHASES); _enum(value['clock_hint'], CLOCK_HINTS)
    _time(value['updated_at']); _enum(value['completeness'], ('unknown', 'partial', 'complete'))
    _require(value['gaps'] == _strings(value['gaps']), 'noncanonical_gaps')


def _validate_decision(value):
    _object(value, 'schema_version decision_version input_version input_fingerprint evaluated_at entity policy_ref fact_phase fact_evidence_refs clock_hint material_state execution_state actions next_action_id next_due_at next_review_at next_review_reason blockers public_summary')
    _require(value['schema_version'] == 'f01.v1', 'schema_version')
    _text(value['decision_version']); _text(value['policy_ref']); _time(value['evaluated_at'])
    _version(value['input_version']); _hash(value['input_fingerprint'])
    entity = _read(value['entity']); _entity(entity)
    _require(entity == value['entity'], 'noncanonical_entity')
    _enum(value['fact_phase'], FACT_PHASES); _enum(value['clock_hint'], CLOCK_HINTS)
    _enum(value['material_state'], MATURITIES)
    _enum(value['execution_state'], ('unobserved', 'planned', 'queued', 'running', 'succeeded', 'failed', 'stale'))
    _require(value['fact_evidence_refs'] == _strings(value['fact_evidence_refs']), 'noncanonical_refs')
    for key in ('next_due_at', 'next_review_at'):
        _time(value[key], nullable=True)
    _text(value['next_action_id'], nullable=True); _text(value['next_review_reason'], nullable=True)
    _require(type(value['actions']) is list and type(value['blockers']) is list, 'array_value')
    for action in value['actions']:
        _object(action, 'action_id kind capability source_binding_ref not_before deadline reason_code expected_input_version expected_generations')
        _text(action['action_id']); _enum(action['kind'], ACTIONS); _enum(action['capability'], CAPABILITIES)
        _text(action['source_binding_ref'], nullable=True); _text(action['reason_code'])
        _time(action['not_before']); _time(action['deadline'], nullable=True)
        _require(action['expected_input_version'] == value['input_version'] and action['expected_generations'] == value['input_version']['generations'], 'action_version_binding')
    ids = [a['action_id'] for a in value['actions']]
    _require(len(ids) == len(set(ids)), 'duplicate_action')
    if value['next_action_id'] is None:
        _require(value['next_due_at'] is None, 'next_action_binding')
    else:
        _require(value['next_action_id'] in ids, 'next_action_binding')
        action = next(a for a in value['actions'] if a['action_id'] == value['next_action_id'])
        _require(value['next_due_at'] == action['not_before'], 'next_action_binding')
    for blocker in value['blockers']:
        _object(blocker, 'code capability field_paths severity root_cause_key evidence_refs retryability next_review_at')
        _text(blocker['code']); _text(blocker['root_cause_key']); _enum(blocker['capability'], CAPABILITIES)
        _enum(blocker['severity'], ('info', 'warning', 'blocking'))
        _enum(blocker['retryability'], ('retryable', 'operator_required', 'not_retryable'))
        _time(blocker['next_review_at'], nullable=True)
        for key in ('field_paths', 'evidence_refs'):
            _require(blocker[key] == _strings(blocker[key]), 'noncanonical_refs')
    if value['public_summary'] is not None:
        _public(value['public_summary'])
        public_entity = value['public_summary']['entity_ref']
        _require(public_entity['kind'] == value['entity']['kind'] and
                 public_entity['canonical_id'] == value['entity']['canonical_id'], 'public_entity_binding')


@dataclass(frozen=True)
class LoaderInput:
    wire_json: str

    def __post_init__(self):
        _require(type(self.wire_json) is str, 'wire_string')
        raw = _read(self.wire_json); _validate_input(raw)
        object.__setattr__(self, 'wire_json', _encode(raw))

    def to_dict(self):
        return json.loads(self.wire_json)

    def to_json(self):
        return self.wire_json


@dataclass(frozen=True)
class DecisionOutput:
    wire_json: str

    def __post_init__(self):
        _require(type(self.wire_json) is str, 'wire_string')
        raw = _read(self.wire_json); _validate_decision(raw)
        object.__setattr__(self, 'wire_json', _encode(raw))

    def to_dict(self):
        return json.loads(self.wire_json)

    def to_json(self):
        return self.wire_json


@dataclass(frozen=True)
class PublicSummary:
    wire_json: str

    def __post_init__(self):
        _require(type(self.wire_json) is str, 'wire_string')
        raw = _read(self.wire_json); _public(raw)
        object.__setattr__(self, 'wire_json', _encode(raw))

    def to_dict(self):
        return json.loads(self.wire_json)

    def to_json(self):
        return self.wire_json


def parse_input(value) -> LoaderInput:
    return LoaderInput(_encode(_read(value)))


def build_input(snapshot, *, evaluated_at, policy_ref, generations, scope=INPUT_SCOPE) -> LoaderInput:
    """Producer boundary: derive digests; parsers never repair incoming wire."""
    normalized = _snapshot(snapshot, derive=True)
    value = dict(schema_version='f01.v1', evaluated_at=evaluated_at, policy_ref=policy_ref,
        snapshot=normalized, input_version=dict(schema_version='f01.input.v1',
        scope=_strings(list(scope)), content_sha256=_sha(normalized), generations=generations))
    return parse_input(value)


def parse_decision(value, *, input_document: LoaderInput) -> DecisionOutput:
    _require(type(input_document) is LoaderInput, 'input_document_type')
    document = DecisionOutput(_encode(_read(value)))
    raw, inp = document.to_dict(), input_document.to_dict()
    _require(raw['input_version'] == inp['input_version'] and raw['input_fingerprint'] == _sha(inp), 'decision_input_binding')
    _require(raw['entity'] == inp['snapshot']['entity'] and raw['policy_ref'] == inp['policy_ref']
             and raw['evaluated_at'] == inp['evaluated_at'], 'decision_input_binding')
    refs = {e['evidence_id'] for e in inp['snapshot']['evidence']}
    for references in [raw['fact_evidence_refs']] + [b['evidence_refs'] for b in raw['blockers']]:
        _require(set(references) <= refs, 'evidence_reference')
    return document


def parse_public_summary(value) -> PublicSummary:
    """Shape check only. Caller must first validate actual publication authority."""
    return PublicSummary(_encode(_read(value)))
