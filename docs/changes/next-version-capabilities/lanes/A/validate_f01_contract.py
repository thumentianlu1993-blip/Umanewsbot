"""离线文档样例校验器；不供业务 import，不执行 writer/ORM/网络。"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def fields(value, names):
    require(type(value) is dict, 'object_required')
    require(set(value) == set(names.split()), 'required_or_unknown_field')


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def ordered(values):
    require(type(values) is list and all(type(v) is str for v in values), 'string_list_required')
    require(len(values) == len(set(values)), 'duplicate_unordered_member')
    return sorted(values)


def protection_digest(value):
    return sha({k: value[k] for k in ('paused', 'fields', 'modules', 'reason', 'actor_ref', 'changed_at')})


def normalize_entity(value):
    fields(value, 'kind canonical_id source_refs identity_state candidate_ids evidence_refs')
    require(value['kind'] in ('article', 'race_event', 'horse'), 'entity_kind')
    require(value['identity_state'] in ('verified', 'ambiguous', 'unresolved', 'revoked'), 'identity_state')
    require(value['canonical_id'] is None or type(value['canonical_id']) is str, 'canonical_id_type')
    for ref in value['source_refs']:
        fields(ref, 'source namespace external_id')
        require(all(type(v) is str and v for v in ref.values()), 'source_ref_value')
    value['source_refs'].sort(key=lambda r: (r['source'], r['namespace'], r['external_id']))
    require(len({sha(r) for r in value['source_refs']}) == len(value['source_refs']), 'duplicate_source_ref')
    for key in ('candidate_ids', 'evidence_refs'):
        value[key] = ordered(value[key])
    require(value['identity_state'] != 'ambiguous' or value['canonical_id'] is None, 'ambiguous_canonical')
    require(value['identity_state'] != 'verified' or value['canonical_id'] is not None
            or len(value['source_refs']) == 1, 'verified_identity_missing')


def normalize_snapshot(raw):
    value = copy.deepcopy(raw)
    fields(value, 'entity materials evidence protection policy_ref')
    normalize_entity(value['entity'])
    protection = value['protection']
    fields(protection, 'paused fields modules reason actor_ref changed_at protection_sha256')
    require(type(protection['paused']) is bool, 'paused_type')
    for key in ('fields', 'modules'):
        protection[key] = ordered(protection[key])
    require(protection['protection_sha256'] == protection_digest(protection), 'protection_digest_mismatch')
    for evidence in value['evidence']:
        fields(evidence, 'evidence_id provider_key source_class independence_key capability artifact_sha256 locator observed_at source_time contract_ref')
        require(evidence['source_class'] in ('licensed_api', 'official_operator', 'trusted_publisher', 'community', 'manual_supplement'), 'source_class')
        fields(evidence['source_time'], 'precision published_at last_absent_at first_seen_at')
        require(evidence['source_time']['precision'] in ('exact', 'interval', 'unknown'), 'source_time_precision')
        fields(evidence['contract_ref'], 'route_digest contract_digest proof_digest valid_until revoked')
        require(type(evidence['contract_ref']['revoked']) is bool, 'revoked_type')
    value['evidence'].sort(key=lambda e: e['evidence_id'])
    refs = {e['evidence_id'] for e in value['evidence']}
    require(len(refs) == len(value['evidence']), 'duplicate_evidence_id')
    require(set(value['entity']['evidence_refs']) <= refs, 'entity_evidence_missing')
    for material in value['materials']:
        fields(material, 'capability maturity completeness validation revision_ref supersedes_ref evidence_refs data')
        require(material['capability'] in ('identity', 'schedule', 'roster', 'withdrawal', 'result', 'correction', 'profile', 'career', 'name', 'relationship'), 'capability')
        require(material['maturity'] in ('unknown', 'predicted', 'provisional', 'confirmed', 'corrected'), 'maturity')
        require(material['completeness'] in ('unknown', 'partial', 'complete'), 'completeness')
        require(material['validation'] in ('pending', 'passed', 'conflict', 'rejected'), 'validation')
        material['evidence_refs'] = ordered(material['evidence_refs'])
        require(set(material['evidence_refs']) <= refs, 'material_evidence_missing')
    # materials 是候选集合；data.participants 是有业务顺序的名单，绝不排序。
    value['materials'].sort(key=lambda m: (m['capability'], m['revision_ref'] or '', sha(m)))
    return value


def validate_version(version):
    fields(version, 'schema_version scope content_sha256 generations')
    require(version['schema_version'] == 'f01.input.v1', 'input_schema')
    require(version['scope'] == ordered(version['scope']), 'noncanonical_scope')
    require(version['scope'] == ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'fixture_dependency_scope')
    fields(version['generations'], 'owner schedule enrollment source_set')
    require(all(v is None or (type(v) is int and v >= 0) for v in version['generations'].values()), 'generation_type')


def validate_case(case):
    fields(case, 'case_id label input expected output')
    inp, out = case['input'], case['output']
    fields(inp, 'schema_version evaluated_at policy_ref input_version snapshot')
    require(inp['schema_version'] == 'f01.v1', 'envelope_schema')
    validate_version(inp['input_version'])
    snapshot = normalize_snapshot(inp['snapshot'])
    require(snapshot == inp['snapshot'], 'noncanonical_snapshot')
    require(inp['input_version']['content_sha256'] == sha(snapshot), 'content_digest_mismatch')
    require(inp['policy_ref'] == snapshot['policy_ref'], 'policy_ref_mismatch')
    fields(out, 'schema_version decision_version input_version input_fingerprint evaluated_at entity fact_phase fact_evidence_refs clock_hint material_state execution_state actions next_action_id next_due_at next_review_at next_review_reason blockers public_summary policy_ref')
    normalized_entity = copy.deepcopy(out['entity'])
    normalize_entity(normalized_entity)
    require(normalized_entity == out['entity'] == snapshot['entity'], 'output_entity_mismatch')
    require(out['schema_version'] == inp['schema_version'] and out['input_version'] == inp['input_version'], 'output_version_mismatch')
    require(out['policy_ref'] == inp['policy_ref'] and out['evaluated_at'] == inp['evaluated_at'], 'output_envelope_mismatch')
    require(out['input_fingerprint'] == sha(inp), 'fingerprint_mismatch')
    require(out['fact_phase'] in ('unknown', 'scheduled', 'running', 'finished', 'postponed', 'cancelled'), 'fact_phase')
    require(out['clock_hint'] in ('unknown', 'before_start', 'start_time_reached', 'result_deadline_reached', 'local_day_elapsed'), 'clock_hint')
    require(out['execution_state'] in ('unobserved', 'planned', 'queued', 'running', 'succeeded', 'failed', 'stale'), 'execution_state')
    for action in out['actions']:
        fields(action, 'action_id kind capability source_binding_ref not_before deadline reason_code expected_input_version expected_generations')
        require(action['kind'] in ('wait', 'discover_identity', 'refresh_schedule', 'refresh_roster', 'fetch_result', 'check_correction', 'reconcile_publication', 'operator_review'), 'action_kind')
        require(action['expected_input_version'] == inp['input_version'] and action['expected_generations'] == inp['input_version']['generations'], 'action_version_mismatch')
    action_ids = [a['action_id'] for a in out['actions']]
    require(len(action_ids) == len(set(action_ids)), 'duplicate_action_id')
    if out['next_action_id'] is None:
        require(out['next_due_at'] is None, 'null_action_due')
    else:
        require(out['next_action_id'] in action_ids, 'next_action_missing')
        selected = next(a for a in out['actions'] if a['action_id'] == out['next_action_id'])
        require(out['next_due_at'] == selected['not_before'], 'next_due_mismatch')
    refs = {e['evidence_id'] for e in snapshot['evidence']}
    require(set(out['fact_evidence_refs']) <= refs, 'fact_evidence_missing')
    for blocker in out['blockers']:
        fields(blocker, 'code capability field_paths severity root_cause_key evidence_refs retryability next_review_at')
        require(set(blocker['evidence_refs']) <= refs, 'blocker_evidence_missing')
    require(out['public_summary'] is None, 'fixture_has_no_public_validator')


def rejected(case, mutate):
    candidate = copy.deepcopy(case)
    mutate(candidate)
    try:
        validate_case(candidate)
    except ValueError as exc:
        return str(exc)
    raise AssertionError('invalid fixture accepted')


def run():
    path = ROOT / 'F01-contract-examples.json'
    data = json.loads(path.read_text())
    require(len(data['cases']) == 4, 'four_cases_required')
    for case in data['cases']:
        validate_case(case)
    same = data['cases'][1]
    negatives = {
        'missing_output_source': rejected(same, lambda c: c['output']['entity']['source_refs'][0].pop('source')),
        'missing_input_source': rejected(same, lambda c: c['input']['snapshot']['entity']['source_refs'][0].pop('source')),
        'tampered_protection': rejected(data['cases'][3], lambda c: c['input']['snapshot']['protection'].update(paused=True)),
        'missing_protection_digest': rejected(same, lambda c: c['input']['snapshot']['protection'].pop('protection_sha256')),
        'noncanonical_scope': rejected(same, lambda c: c['input']['input_version']['scope'].reverse()),
    }
    # producer 规范化无序集合后摘要不变；严格 wire 不接受非规范序列。
    for case in data['cases']:
        original = case['input']['snapshot']
        reordered = copy.deepcopy(original)
        for key in ('source_refs', 'candidate_ids', 'evidence_refs'):
            reordered['entity'][key].reverse()
        reordered['evidence'].reverse()
        reordered['materials'].reverse()
        for material in reordered['materials']:
            material['evidence_refs'].reverse()
        for key in ('fields', 'modules'):
            reordered['protection'][key].reverse()
        require(sha(normalize_snapshot(reordered)) == sha(original), 'unordered_version_changed')
    roster = copy.deepcopy(data['cases'][2]['input']['snapshot'])
    before = sha(normalize_snapshot(roster))
    confirmed = next(m for m in roster['materials'] if m['maturity'] == 'confirmed')
    confirmed['data']['participants'].reverse()
    require(sha(normalize_snapshot(roster)) != before, 'business_order_version_unchanged')
    return dict(status='pass',scope='offline_document_contract_only',positive_cases=4,
                negative_cases=negatives,unordered_permutation_cases=4,business_roster_order_change='digest_changed')


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
