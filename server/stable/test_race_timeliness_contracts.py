"""R01 pure unittest; no Django setup, DB, queues or external calls."""
import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from stable.services import content_contracts as f01
from stable.services import race_timeliness_contracts as core

CANDIDATE = 'a' * 64
START = '2026-10-23T08:00:00Z'
END = '2026-10-30T08:00:00Z'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def timestamp(seconds=0):
    return (datetime(2026, 10, 23, 8, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')


def loader(number, source_time=None):
    evidence = []
    if source_time is not None:
        evidence = [dict(evidence_id='source-1', provider_key='fixture', source_class='official_operator', independence_key='fixture', capability='result', artifact_sha256='b'*64, locator='fixture:1', observed_at=timestamp(100), source_time=source_time, contract_ref=dict(route_digest='c'*64, contract_digest='d'*64, proof_digest='e'*64, valid_until=END, revoked=False))]
    snapshot = dict(entity=dict(kind='race_event', canonical_id=str(number), identity_state='verified', source_refs=[], candidate_ids=[], evidence_refs=[]), materials=[], evidence=evidence, protection=dict(paused=False, fields=[], modules=[], reason='', actor_ref=None, changed_at=None), policy_ref='fixture-policy')
    return f01.build_input(snapshot, evaluated_at=START, policy_ref='fixture-policy', generations=dict(owner=None, schedule=None, enrollment=None, source_set=None)).to_dict()


def report():
    targets = []
    for n in range(10):
        version = loader(n)
        targets.append(dict(key=f'canonical:{n}', event_id=1 if n == 1 else None, region='fixture-region', material_availability='available' if n < 4 else 'unknown' if n < 6 else 'missing', required_intervals=[dict(start=START, end=END)], audit_fields=['identity', 'roster'], versions=[version], current_input_version=version['input_version']))
    scope = dict(schema_version='r01.scope.v1', scope_ref='fixture-scope', candidate_sha256=CANDIDATE, targets=targets, aliases=[], complete_denominator=True)
    return dict(scope=scope, window=dict(id='O06', start=START, end=END), as_of=END, records=[], coverage=dict(scope_sha256=digest(scope), expected_record_ids=[], proof_ref='fixture-origin-check', complete=True, gaps=[], window=dict(id='O06', start=START, end=END), as_of=END), effective_intervals=[dict(start=START, end=END, candidate_sha256=CANDIDATE, proof_ref='fixture-enabled-and-health')])


def event(value, target, kind, payload, *, seconds=60, record_id=None):
    if kind == 'repair' and set(payload) == {'resolves'}:
        originals = {r['record_id']: r for r in value['records']}
        payload = dict(payload, resolved_versions={ref: copy.deepcopy(originals[ref]['input_version']) for ref in payload['resolves']}, resolved_fields={ref: list(originals[ref]['payload']['error_fields']) if originals[ref]['kind'] == 'audit' else [] for ref in payload['resolves']})
    entry = dict(record_id=record_id or f'{kind}-{len(value["records"])}', target_key=f'canonical:{target}', input_version=copy.deepcopy(value['scope']['targets'][target]['current_input_version']), occurred_at=timestamp(seconds) if seconds is not None else None, recorded_at=timestamp(seconds if seconds is not None else 0), kind=kind, reason_code='fixture-cause', evidence_refs=['fixture-receipt'], payload=payload)
    value['records'].append(entry)
    value['coverage']['expected_record_ids'].append(entry['record_id'])
    return entry


def audit(value, target, *, errors=(), complete=True, checked=('identity', 'roster'), severe=False, seconds=60):
    return event(value, target, 'audit', dict(rule_version='audit.v1', auditor_ref='fixture-auditor', checked_fields=list(checked), error_fields=list(errors), complete=complete, severe=severe), seconds=seconds)


def parse(value):
    return core.parse_report(value, expected_scope_sha256=digest(value['scope']), expected_candidate_sha256=CANDIDATE, expected_coverage_sha256=digest(value.get('coverage', {})))


class InputContractTests(unittest.TestCase):
    def test_immutable_nullable_event_targets_without_attempt_or_source(self):
        value = report(); document = parse(value)
        value['scope']['targets'].clear()
        self.assertEqual(len(document.to_dict()['scope']['targets']), 10)
        detached = document.to_dict(); detached['records'].append('tampered')
        self.assertEqual(document.to_dict()['records'], [])
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            document.wire_json = '{}'

    def test_scope_and_candidate_anchor_reject_tampering(self):
        value = report(); expected = digest(value['scope']); value['scope']['targets'].pop()
        with self.assertRaises(core.ContractError):
            core.parse_report(value, expected_scope_sha256=expected, expected_candidate_sha256=CANDIDATE, expected_coverage_sha256=digest(value.get('coverage', {})))
        value = report(); value['scope']['candidate_sha256'] = 'f'*64; value['coverage']['scope_sha256'] = digest(value['scope'])
        with self.assertRaises(core.ContractError): parse(value)

    def test_missing_unknown_fields_and_untrusted_types_rejected(self):
        for mutate in (lambda v: v.pop('coverage'), lambda v: v.update(secret='private'), lambda v: v.update(as_of='2026-10-30T08:00:00'), lambda v: v['scope']['targets'][0].update(event_id=True), lambda v: v['scope']['targets'][0].update(versions=[])):
            value = report(); mutate(value)
            with self.subTest(mutation=mutate), self.assertRaises(core.ContractError): parse(value)

    def test_version_and_complete_audit_bindings_rejected(self):
        mutations = (lambda r: r['input_version'].update(content_sha256='f'*64), lambda r: r['payload'].update(checked_fields=['identity']), lambda r: r['payload'].update(error_fields=['unreviewed']), lambda r: r.update(evidence_refs=[]))
        for mutate in mutations:
            value = report(); row = audit(value, 0); mutate(row)
            with self.subTest(mutation=mutate), self.assertRaises(core.ContractError): parse(value)

    def test_coverage_cannot_claim_complete_when_expected_origin_missing(self):
        value = report(); value['coverage']['expected_record_ids'] = ['lost-origin']
        with self.assertRaises(core.ContractError): parse(value)
        value['coverage']['complete'] = False; value['coverage']['gaps'] = ['lost-origin']
        self.assertFalse(parse(value).to_dict()['coverage']['complete'])

    def test_alias_requires_explicit_evidence_and_no_cycles(self):
        value = report(); value['scope']['aliases'] = [dict(alias='canonical:1', target='canonical:0', evidence_refs=[])]
        value['coverage']['scope_sha256'] = digest(value['scope'])
        with self.assertRaises(core.ContractError): parse(value)
        value['scope']['aliases'][0]['evidence_refs'] = ['strong-identity-map']
        value['scope']['aliases'].append(dict(alias='canonical:0', target='canonical:1', evidence_refs=['map']))
        value['coverage']['scope_sha256'] = digest(value['scope'])
        with self.assertRaises(core.ContractError): parse(value)

    def test_future_receipt_and_invalid_effective_window_rejected(self):
        value = report(); audit(value, 0, seconds=168*3600+1)
        with self.assertRaises(core.ContractError): parse(value)
        value = report(); value['effective_intervals'][0]['end'] = START
        with self.assertRaises(core.ContractError): parse(value)


class SummaryTests(unittest.TestCase):
    def test_ten_targets_four_audits_one_error_and_transport_separate(self):
        value = report()
        for n in range(4): audit(value, n, errors=['identity'] if n == 0 else [])
        for n in (4, 5): audit(value, n, complete=False, checked=['identity'])
        event(value, 6, 'transport', {})
        event(value, 7, 'deadline', dict(deadline_at=timestamp(20), stage='roster'))
        result = core.summarize(parse(value))
        self.assertEqual((result['targets'], result['audited'], result['information_error_targets']), (10, 4, 1))
        self.assertEqual((result['available_targets'], result['missing_material_targets'], result['material_unknown_targets']), (4, 4, 2))
        self.assertEqual(result['information_error_rate'], 0.25)
        self.assertEqual((result['required_targets'], result['stalled_targets'], result['stalled_rate']), (10, 1, 0.1))
        self.assertEqual((result['partial_audit_targets'], result['unreviewed_targets'], result['transport_failed_targets']), (2, 4, 1))

    def test_repair_and_many_causes_keep_history_one_target(self):
        value = report(); wrong = audit(value, 0, errors=['identity']); audit(value, 0, errors=['roster'])
        event(value, 0, 'repair', dict(resolves=[wrong['record_id']]), seconds=120)
        audit(value, 0, seconds=180)
        result = core.summarize(parse(value))
        self.assertEqual(result['information_error_targets'], 1)
        self.assertEqual(len(result['history']), 4)
        self.assertEqual(result['audited'], 1)

    def test_partial_severe_unknown_scope_and_coverage_are_not_pass(self):
        value = report(); audit(value, 0, complete=False, checked=['identity'], errors=['identity'], severe=True)
        value['scope']['complete_denominator'] = False; value['coverage']['scope_sha256'] = digest(value['scope'])
        value['coverage']['complete'] = False; value['coverage']['gaps'] = ['ephemeral-history-unknown']
        result = core.summarize(parse(value))
        self.assertIsNone(result['information_error_rate']); self.assertEqual(result['severe_error_targets'], 1)
        self.assertFalse(result['measurement_complete']); self.assertTrue(result['blocking']); self.assertEqual(result['coverage_gaps'], ['ephemeral-history-unknown'])

    def test_half_open_deadline_end_and_carryover(self):
        value = report(); old = event(value, 0, 'deadline', dict(deadline_at=timestamp(-10), stage='result'), seconds=-5)
        event(value, 1, 'deadline', dict(deadline_at=END, stage='result'), seconds=168*3600)
        result = core.summarize(parse(value))
        self.assertEqual(result['stalled_targets'], 0)
        self.assertEqual(result['carryover_record_ids'], [old['record_id']])

    def test_explicit_alias_only_and_effective_intervals_union(self):
        value = report(); value['scope']['aliases'] = [dict(alias='canonical:1', target='canonical:0', evidence_refs=['strong-map'])]
        value['coverage']['scope_sha256'] = digest(value['scope'])
        value['effective_intervals'].append(copy.deepcopy(value['effective_intervals'][0]))
        result = core.summarize(parse(value))
        self.assertEqual(result['targets'], 9); self.assertEqual(result['effective_microseconds'], 168*3600*1000000)
        value['window'] = dict(id='O08', start='2026-10-28T08:00:00Z', end=END)
        value['coverage']['window'] = copy.deepcopy(value['window'])
        self.assertEqual(core.summarize(parse(value))['effective_microseconds'], 48*3600*1000000)
        value['effective_intervals'] = []
        self.assertEqual(core.summarize(parse(value))['effective_microseconds'], 0)

    def test_no_origin_guarantee_is_inferred_and_empty_denominator_null(self):
        value = report(); value['coverage']['proof_ref'] = None; value['coverage']['complete'] = False
        self.assertFalse(core.summarize(parse(value))['measurement_complete'])
        value = report(); value['scope']['targets'] = []; value['coverage']['scope_sha256'] = digest(value['scope'])
        result = core.summarize(parse(value)); self.assertIsNone(result['information_error_rate']); self.assertIsNone(result['stalled_rate'])


def latency(*, source='interval', threshold=300, last_absent=0, first_seen=60, last_not_visible=360, first_visible=420, stable=True):
    source_time = dict(precision=source, published_at=timestamp(0) if source == 'exact' else None, last_absent_at=timestamp(last_absent) if source == 'interval' else None, first_seen_at=timestamp(first_seen) if source == 'interval' else None)
    document = loader(0, source_time)
    context = dict(candidate_sha256=CANDIDATE, target_key='canonical:0', capability='result', document=document, source_evidence_id='source-1', material_content_sha256='f'*64, public_version='revision-1', permission_version='authority-1', threshold_seconds=threshold, source_clock_trusted=True, as_of=END)
    probe = dict(external=True, target_key='canonical:0', input_version=document['input_version'], material_content_sha256='f'*64, public_version='revision-1', permission_version='authority-1', first_visible_at=timestamp(first_visible), last_not_visible_at=timestamp(last_not_visible) if last_not_visible is not None else None, stable_interval=stable, evidence_refs=['external-version-clock-receipt'], clock_trusted=True)
    return dict(context=context, probe=probe)


def evaluate(value):
    return core.evaluate_latency(core.parse_latency(value, expected_context_sha256=digest(value['context'])))


class LatencyTests(unittest.TestCase):
    def test_double_open_lower_equal_threshold_proves_late(self):
        result = evaluate(latency())  # (360-60,420-0) = (300,420)
        self.assertEqual(result['status'], 'proven_late')
        self.assertEqual((result['lower_microseconds'], result['upper_microseconds']), (300000000, 420000000))
        self.assertTrue(result['lower_open']); self.assertTrue(result['upper_open'])

    def test_closed_lower_threshold_and_upper_equality(self):
        self.assertEqual(core.classify_bounds(core.LatencyBounds(300000000, 420000000, False, True, False), 300), 'indeterminate')
        self.assertEqual(core.classify_bounds(core.LatencyBounds(300000000, 420000000, True, True, False), 300), 'proven_late')
        self.assertEqual(core.classify_bounds(core.LatencyBounds(300000000, 300000000, False, False, False), 300), 'proven_met')
        self.assertEqual(evaluate(latency(threshold=600, last_not_visible=500, first_visible=600))['status'], 'proven_met')
        self.assertEqual(evaluate(latency(source='exact', first_visible=300, last_not_visible=200))['status'], 'proven_met')

    def test_first_success_late_is_only_upper_and_not_proven_late(self):
        result = evaluate(latency(source='exact', first_visible=900, last_not_visible=None))
        self.assertEqual(result['status'], 'indeterminate'); self.assertTrue(result['upper_bound_only'])
        self.assertEqual(evaluate(latency(source='exact', first_visible=300, last_not_visible=None))['status'], 'proven_met')

    def test_interval_crossing_threshold_indeterminate(self):
        self.assertEqual(evaluate(latency(last_not_visible=350, first_visible=420))['status'], 'indeterminate')

    def test_no_external_probe_and_unknown_source_clock_are_not_pass(self):
        value = latency(); value['probe'] = None
        self.assertEqual(evaluate(value)['status'], 'visibility_unverified')
        value = latency(); value['probe']['external'] = False
        self.assertEqual(evaluate(value)['status'], 'visibility_unverified')
        self.assertEqual(evaluate(latency(source='unknown'))['status'], 'source_time_unknown')
        value = latency(); value['context']['source_clock_trusted'] = False
        self.assertEqual(evaluate(value)['status'], 'clock_unknown')
        value = latency(); value['probe']['clock_trusted'] = False
        self.assertEqual(evaluate(value)['status'], 'clock_unknown')

    def test_empty_contradictory_or_negative_intervals_never_clamp(self):
        for value in (latency(last_absent=60, first_seen=60), latency(last_not_visible=420, first_visible=420), latency(last_not_visible=430, first_visible=420), latency(source='exact', last_not_visible=-20, first_visible=-10)):
            self.assertEqual(evaluate(value)['status'], 'clock_anomaly')
        with self.assertRaises(core.ContractError): core.LatencyBounds(1, 0, False, False, False)

    def test_tampered_context_version_permission_or_timezone_rejected(self):
        value = latency(); expected = digest(value['context']); value['context']['candidate_sha256'] = 'b'*64
        with self.assertRaises(core.ContractError): core.parse_latency(value, expected_context_sha256=expected)
        for field, wrong in (('public_version', 'old'), ('permission_version', 'old'), ('input_version', {}), ('material_content_sha256', 'a'*64), ('first_visible_at', '2026-10-23T08:07:00')):
            value = latency(); value['probe'][field] = wrong
            with self.subTest(field=field), self.assertRaises(core.ContractError): evaluate(value)

    def test_latency_input_is_immutable(self):
        value = latency(); doc = core.parse_latency(value, expected_context_sha256=digest(value['context']))
        value['probe']['external'] = False
        self.assertTrue(doc.to_dict()['probe']['external'])
        with self.assertRaises((FrozenInstanceError, AttributeError)): doc.wire_json = '{}'


class HardeningTests(unittest.TestCase):
    def test_alias_values_and_bounds_reject_malformed_without_type_leaks(self):
        value = report(); value['scope']['aliases'] = [dict(alias=[], target='canonical:0', evidence_refs=['map'])]
        value['coverage']['scope_sha256'] = digest(value['scope'])
        with self.assertRaises(core.ContractError): parse(value)

    def test_unknown_occurrence_cannot_assert_full_information_error_rate(self):
        value = report(); audit(value, 0, errors=['identity'], seconds=None)
        result = core.summarize(parse(value))
        self.assertIsNone(result['information_error_rate']); self.assertFalse(result['measurement_complete'])
        self.assertEqual(len(result['unknown_time_record_ids']), 1)

    def test_duplicate_receipt_idempotent_but_changed_body_rejected(self):
        value = report(); row = audit(value, 0, errors=['identity']); value['records'].append(copy.deepcopy(row))
        result = core.summarize(parse(value)); self.assertEqual(len(result['history']), 1); self.assertEqual(result['information_error_targets'], 1)
        value['records'][-1]['reason_code'] = 'other'
        with self.assertRaises(core.ContractError): parse(value)

    def test_explicit_limits_reject_oversized_collections(self):
        for collection, count in (('records', core.MAX_RECORDS+1), ('targets', core.MAX_TARGETS+1)):
            value = report()
            if collection == 'targets': value['scope']['targets'] = [{}] * count; value['coverage']['scope_sha256'] = digest(value['scope'])
            else: value['records'] = [{}] * count
            with self.subTest(collection=collection), self.assertRaises(core.ContractError): parse(value)

    def test_as_of_never_fills_planned_duration(self):
        value = report(); value['as_of'] = timestamp(3600); value['coverage']['as_of'] = value['as_of']
        result = core.summarize(parse(value))
        self.assertEqual(result['effective_microseconds'], 3600*1000000); self.assertFalse(result['full_window_evidence'])
        self.assertEqual(result['planned_microseconds'], 168*3600*1000000)

    def test_latency_evidence_capability_cannot_be_repurposed(self):
        value = latency()
        raw = value['context']['document']
        snapshot = copy.deepcopy(raw['snapshot']); snapshot['evidence'][0]['capability'] = 'identity'
        value['context']['document'] = f01.build_input(snapshot, evaluated_at=raw['evaluated_at'], policy_ref=raw['policy_ref'], generations=raw['input_version']['generations']).to_dict()
        value['probe']['input_version'] = value['context']['document']['input_version']
        with self.assertRaises(core.ContractError): evaluate(value)


class SnapshotBoundaryTests(unittest.TestCase):
    def test_unresolved_entity_kept_but_cannot_claim_strong_denominator(self):
        value = report(); target = value['scope']['targets'][0]
        old = target['versions'][0]; snapshot = copy.deepcopy(old['snapshot'])
        snapshot['entity'].update(canonical_id=None, identity_state='unresolved')
        document = f01.build_input(snapshot, evaluated_at=START, policy_ref=old['policy_ref'], generations=old['input_version']['generations']).to_dict()
        target.update(key='unknown:'+digest(snapshot['entity']), versions=[document], current_input_version=document['input_version'])
        value['coverage']['scope_sha256'] = digest(value['scope'])
        result = core.summarize(parse(value))
        self.assertEqual(result['targets'], 10); self.assertEqual(result['unresolved_target_count'], 1)
        self.assertFalse(result['complete_denominator'])

    def test_external_receipt_after_explicit_as_of_rejected(self):
        value = latency(); value['context']['as_of'] = timestamp(300)
        with self.assertRaises(core.ContractError): evaluate(value)
        value['context']['as_of'] = timestamp(500)
        self.assertEqual(evaluate(value)['status'], 'proven_late')


class CoverageAnchorTests(unittest.TestCase):
    def test_expected_origin_proof_cannot_be_silently_shrunk(self):
        value = report(); value['coverage'].update(expected_record_ids=['lost-origin'], complete=False, gaps=['lost-origin'])
        expected = digest(value['coverage'])
        value['coverage'].update(expected_record_ids=[], complete=True, gaps=[])
        with self.assertRaises(core.ContractError):
            core.parse_report(value, expected_scope_sha256=digest(value['scope']), expected_candidate_sha256=CANDIDATE, expected_coverage_sha256=expected)


class ReviewDeadlineTests(unittest.TestCase):
    def test_R_A013_01_late_receipt_belongs_to_deadline_window(self):
        value = report(); value['as_of'] = timestamp(168*3600+60); value['coverage']['as_of'] = value['as_of']
        row = event(value, 0, 'deadline', dict(deadline_at=timestamp(168*3600-1), stage='result'), seconds=168*3600+1)
        result = core.summarize(parse(value))
        self.assertEqual((result['required_targets'], result['stalled_targets']), (10, 1))
        self.assertEqual(result['history'][0]['occurred_at'], row['occurred_at'])
        self.assertTrue(result['record_coverage_complete'])


class ReviewSevereTests(unittest.TestCase):
    def test_R_A013_02_pre_window_unrepaired_severe_remains_blocking(self):
        value = report(); row = audit(value, 0, complete=False, checked=['identity'], errors=['identity'], severe=True, seconds=-1)
        result = core.summarize(parse(value))
        self.assertEqual(result['audited'], 0); self.assertIsNone(result['information_error_rate'])
        self.assertEqual(result['carryover_record_ids'], [row['record_id']])
        self.assertEqual(result['severe_error_targets'], 1); self.assertTrue(result['blocking'])


class ReviewRepairBoundaryTests(unittest.TestCase):
    def test_deadline_microseconds_and_repair_keep_historical_stall(self):
        value = report(); value['as_of'] = timestamp(168*3600+60); value['coverage']['as_of'] = value['as_of']
        row = event(value, 0, 'deadline', dict(deadline_at=timestamp(168*3600-0.000001), stage='result'), seconds=168*3600+0.000001)
        event(value, 0, 'repair', dict(resolves=[row['record_id']]), seconds=168*3600+2)
        result = core.summarize(parse(value)); self.assertEqual(result['stalled_targets'], 1)
        self.assertEqual(result['history'][0]['payload']['deadline_at'], row['payload']['deadline_at'])

    def test_deadline_end_only_next_window_and_late_old_is_carryover(self):
        value = report(); value['as_of'] = timestamp(168*3600+60); value['coverage']['as_of'] = value['as_of']
        old = event(value, 0, 'deadline', dict(deadline_at=timestamp(168*3600-1), stage='result'), seconds=168*3600+1)
        event(value, 1, 'deadline', dict(deadline_at=END, stage='result'), seconds=168*3600+1)
        self.assertEqual(core.summarize(parse(value))['stalled_targets'], 1)
        value['window'] = dict(id='next', start=END, end=timestamp(168*3600+3600)); value['coverage']['window'] = copy.deepcopy(value['window'])
        for target in value['scope']['targets']: target['required_intervals'][0]['end'] = value['window']['end']
        value['coverage']['scope_sha256'] = digest(value['scope'])
        result = core.summarize(parse(value)); self.assertEqual(result['stalled_targets'], 1)
        self.assertIn(old['record_id'], result['carryover_record_ids'])

    def test_missing_unknown_and_future_deadline_evidence_never_invented(self):
        value = report(); value['coverage'].update(expected_record_ids=['not-received'], complete=False, gaps=['not-received'])
        self.assertEqual(core.summarize(parse(value))['stalled_targets'], 0)
        value = report(); event(value, 0, 'deadline', dict(deadline_at=timestamp(168*3600-1), stage='result'), seconds=None)
        self.assertEqual(core.summarize(parse(value))['stalled_targets'], 0)
        value = report(); event(value, 0, 'deadline', dict(deadline_at=timestamp(168*3600-1), stage='result'), seconds=168*3600+1)
        with self.assertRaises(core.ContractError): parse(value)

    def test_pre_window_fixed_severe_closes_only_current_block(self):
        value = report(); row = audit(value, 0, complete=False, checked=['identity'], errors=['identity'], severe=True, seconds=-10)
        event(value, 0, 'repair', dict(resolves=[row['record_id']]), seconds=-1)
        result = core.summarize(parse(value)); self.assertFalse(result['blocking'])
        self.assertEqual(result['severe_error_targets'], 0); self.assertEqual(result['historical_severe_error_targets'], 1)
        self.assertEqual(result['carryover_record_ids'], [])

    def test_in_window_repair_preserves_error_rate_and_discovery(self):
        value = report(); row = audit(value, 0, errors=['identity'], severe=True)
        event(value, 0, 'repair', dict(resolves=[row['record_id']]), seconds=120)
        result = core.summarize(parse(value)); self.assertFalse(result['blocking'])
        self.assertEqual(result['information_error_rate'], 1.0)
        self.assertEqual(result['window_severe_error_targets'], 1); self.assertEqual(result['historical_severe_error_targets'], 1)

    def test_fix_one_error_cannot_close_other_same_target_and_plain_audit_not_fix(self):
        value = report(); row = audit(value, 0, errors=['identity'], severe=True)
        other = audit(value, 0, errors=['roster'], severe=True)
        event(value, 0, 'repair', dict(resolves=[row['record_id']]), seconds=120); audit(value, 0, seconds=180)
        result = core.summarize(parse(value)); self.assertTrue(result['blocking'])
        self.assertEqual(result['open_severe_record_ids'], [other['record_id']])

    def test_unknown_time_severe_stays_open_until_explicit_known_time_repair(self):
        value = report(); row = audit(value, 0, complete=False, checked=['identity'], errors=['identity'], severe=True, seconds=None)
        self.assertTrue(core.summarize(parse(value))['blocking'])
        event(value, 0, 'repair', dict(resolves=[row['record_id']]), seconds=120)
        result = core.summarize(parse(value)); self.assertFalse(result['blocking'])
        self.assertEqual(result['historical_severe_error_targets'], 1); self.assertIsNone(result['information_error_rate'])
        self.assertFalse(result['record_coverage_complete'])

    def test_pre_window_error_repaired_in_window_does_not_erase_carryover(self):
        value = report(); row = audit(value, 0, complete=False, checked=['identity'], errors=['identity'], severe=True, seconds=-1)
        event(value, 0, 'repair', dict(resolves=[row['record_id']]), seconds=120)
        result = core.summarize(parse(value)); self.assertFalse(result['blocking'])
        self.assertIn(row['record_id'], result['carryover_record_ids'])
        self.assertEqual(result['audited'], 0)


class ReviewRepairBindingTests(unittest.TestCase):
    def test_repair_wrong_version_fields_or_effective_time_rejected(self):
        for mutate in (
            lambda r, old: r['payload']['resolved_versions'][old['record_id']].update(content_sha256='f'*64),
            lambda r, old: r['payload']['resolved_fields'].update({old['record_id']: ['not-the-error']}),
            lambda r, old: r.update(occurred_at=None),
            lambda r, old: r.update(occurred_at=timestamp(1)),
        ):
            value = report(); old = audit(value, 0, errors=['identity'], severe=True)
            repair = event(value, 0, 'repair', dict(resolves=[old['record_id']]), seconds=120); mutate(repair, old)
            with self.subTest(mutation=mutate), self.assertRaises(core.ContractError): parse(value)

    def test_partial_field_resolution_stays_blocked_until_all_repaired(self):
        value = report(); old = audit(value, 0, errors=['identity', 'roster'], severe=True)
        first = event(value, 0, 'repair', dict(resolves=[old['record_id']]), seconds=100)
        first['payload']['resolved_fields'][old['record_id']] = ['identity']
        self.assertTrue(core.summarize(parse(value))['blocking'])
        second = event(value, 0, 'repair', dict(resolves=[old['record_id']]), seconds=120)
        second['payload']['resolved_fields'][old['record_id']] = ['roster']
        result = core.summarize(parse(value)); self.assertFalse(result['blocking'])
        self.assertEqual(result['information_error_rate'], 1.0); self.assertEqual(len(result['history']), 3)

    def test_clean_audit_and_wrong_target_cannot_be_repair_origins(self):
        value = report(); old = audit(value, 0)
        event(value, 0, 'repair', dict(resolves=[old['record_id']]), seconds=120)
        with self.assertRaises(core.ContractError): parse(value)
        value = report(); old = audit(value, 0, errors=['identity'], severe=True)
        event(value, 1, 'repair', dict(resolves=[old['record_id']]), seconds=120)
        with self.assertRaises(core.ContractError): parse(value)


class ReviewReceiptTimeTests(unittest.TestCase):
    def test_late_recording_not_available_at_prior_as_of(self):
        value = report(); row = event(value, 0, 'deadline', dict(deadline_at=timestamp(168*3600-2), stage='result'), seconds=168*3600-1)
        row['recorded_at'] = timestamp(168*3600+1)
        with self.assertRaises(core.ContractError): parse(value)
        value['as_of'] = timestamp(168*3600+60); value['coverage']['as_of'] = value['as_of']
        result = core.summarize(parse(value)); self.assertEqual(result['stalled_targets'], 1)
        self.assertEqual(result['history'][0]['recorded_at'], row['recorded_at'])
