"""B254 synthetic schema controls；源自 B249 原 schema，不借历史运行 PASS。

无 mock；先以未改 core.verify_results/digest 建立真实正向基线，再注入单项负例。
测试不读取历史包，不导入旧22测试或业务；本次源码卡不执行。
"""
import copy
import unittest

from tools.test_impact import core
from tools.test_impact import full_composition_evidence as evidence

NATIVE_IDS = ['stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity']


def fixture():
    plan = dict(source='git', mode='targeted', test_sha='a' * 40, test_tree='b' * 40,
                base_sha='c' * 40, head_sha='d' * 40, run_id='254001', run_attempt=1,
                image_id='sha256:' + 'e' * 64, parent_full_digest='f' * 64,
                catalog_digest='1' * 64, rules_digest='2' * 64,
                control_manifest_digest='3' * 64, image_supply_policy_digest='4' * 64,
                capability_subject_pins_digest='5' * 64, lifecycle_policy_digest='6' * 64,
                labels=list(NATIVE_IDS), count=3, aliases=[], allowed_skips={},
                fixture_inputs=dict(id='b243-remaining3-fixture-bound-v1',
                    manifest_sha256='3a068de66eea198421897895dce1f00d33772d903a391757e65898bf896ca4a4',
                    source_sha='a' * 40, source_tree='b' * 40),
                batches=[dict(key='batch-000', profile='django', ids=list(NATIVE_IDS))])
    child = dict(role='cache_remaining3', plan=plan, plan_digest=core.digest(plan))
    report = dict(key='batch-000', profile='django', plan_digest=core.digest(plan),
                  run_id=plan['run_id'], run_attempt=1, test_tree=plan['test_tree'],
                  executed=list(NATIVE_IDS), failures=[], errors=[], skips=[], expected_failures=[],
                  unexpected_successes=[], lifecycle='complete', exit_code=0,
                  python='SYNTHETIC_SCHEMA_CONTROL', os='SYNTHETIC_SCHEMA_CONTROL',
                  isolation={}, postgresql='SYNTHETIC_SCHEMA_CONTROL',
                  django='SYNTHETIC_SCHEMA_CONTROL', seconds=0.0)
    return dict(expected_child=copy.deepcopy(child), child=child,
                reports=[dict(role=child['role'], child_plan_digest=child['plan_digest'], report=report)])


def rebind(case):
    """只在明确生成新合法 expected spec 的测试控制中使用，不修饰负例报告。"""
    child = case['child']
    child['plan_digest'] = core.digest(child['plan'])
    case['expected_child'] = copy.deepcopy(child)
    for envelope in case['reports']:
        envelope['role'] = child['role']
        envelope['child_plan_digest'] = child['plan_digest']
        envelope['report']['plan_digest'] = child['plan_digest']


class ChildCoreEvidenceTests(unittest.TestCase):
    def assertBaseline(self, case):
        result = core.verify_results(case['child']['plan'], [e['report'] for e in case['reports']])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['count'], case['child']['plan']['count'])
        self.assertEqual(result['skipped_count'], 0)
        checked = evidence.verify_child_evidence(**case)
        self.assertEqual(checked['status'], 'CHILD_EVIDENCE_VALID_GATE_NOT_READY')
        return checked

    def assertCoreRejected(self, case, message):
        with self.assertRaisesRegex(evidence.CoreEvidenceRejected, 'original core rejected') as raised:
            evidence.verify_child_evidence(**case)
        self.assertIs(type(raised.exception.__cause__), ValueError)
        self.assertEqual(str(raised.exception.__cause__), message)

    def test_real_core_positive_baseline_preserves_inputs_and_own_digest(self):
        case = fixture(); original = copy.deepcopy(case)
        result = self.assertBaseline(case)
        self.assertEqual(case, original)
        self.assertEqual(result['role'], 'cache_remaining3')
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['child_plan_digest'], core.digest(case['child']['plan']))
        self.assertEqual(result['parent_full_digest'], 'f' * 64)
        self.assertEqual(result['core_result']['mode'], 'targeted')
        self.assertEqual(result['core_result']['skipped_count'], 0)
        self.assertEqual(result['core_result']['plan_digest'], case['child']['plan_digest'])
        self.assertEqual(result['reports'], [dict(
            namespace='roles/cache_remaining3/' + case['child']['plan_digest'] + '/batch-000.json',
            canonical_report_digest=core.digest(case['reports'][0]['report']))])

    def test_missing_duplicate_and_extra_raw_reports_reach_original_core(self):
        for variant in ('missing', 'duplicate', 'extra'):
            case = fixture(); self.assertBaseline(case)
            if variant == 'missing': case['reports'].clear()
            else:
                extra = copy.deepcopy(case['reports'][0])
                if variant == 'extra': extra['report']['key'] = 'batch-999'
                case['reports'].append(extra)
            with self.subTest(variant=variant):
                self.assertCoreRejected(case, 'missing/duplicate/unexpected batch')

    def test_raw_plan_digest_and_profile_rejections_come_from_core(self):
        for field, value in [('plan_digest', '0' * 64), ('profile', 'python')]:
            case = fixture(); self.assertBaseline(case)
            case['reports'][0]['report'][field] = value
            with self.subTest(field=field): self.assertCoreRejected(case, 'plan/profile mismatch')

    def test_raw_source_tree_run_and_attempt_rejections_come_from_core(self):
        for field, value in [('test_tree', '0' * 40), ('run_id', '254002'), ('run_attempt', 2)]:
            case = fixture(); self.assertBaseline(case)
            case['reports'][0]['report'][field] = value
            with self.subTest(field=field): self.assertCoreRejected(case, 'identity mismatch: ' + field)

    def test_raw_missing_extra_and_duplicate_executed_ids_reach_core(self):
        for variant in ('missing', 'extra', 'duplicate'):
            case = fixture(); self.assertBaseline(case)
            ids = case['reports'][0]['report']['executed']
            if variant == 'missing': ids.pop()
            else: ids.append('unknown.C.test_extra' if variant == 'extra' else ids[0])
            with self.subTest(variant=variant): self.assertCoreRejected(case, 'execution set mismatch')

    def test_error_outcomes_and_lifecycle_fail_in_original_core(self):
        for field, value in [('failures', [dict(id=NATIVE_IDS[0], traceback='synthetic')]),
                             ('errors', [dict(id=NATIVE_IDS[0], traceback='synthetic')]),
                             ('expected_failures', [NATIVE_IDS[0]]), ('unexpected_successes', [NATIVE_IDS[0]]),
                             ('exit_code', 1), ('lifecycle', 'incomplete')]:
            case = fixture(); self.assertBaseline(case)
            case['reports'][0]['report'][field] = value
            with self.subTest(field=field): self.assertCoreRejected(case, 'failed test or lifecycle')

    def test_unallowed_and_expired_skip_keep_original_core_policy(self):
        for variant in ('unallowed', 'expired'):
            case = fixture()
            if variant == 'expired':
                case['child']['plan']['allowed_skips'] = {NATIVE_IDS[0]:
                    dict(profile='django', reason='synthetic', review_by='0001-01-01')}
                rebind(case)
            self.assertBaseline(case)
            case['reports'][0]['report']['skips'] = [dict(id=NATIVE_IDS[0], reason='synthetic')]
            with self.subTest(variant=variant): self.assertCoreRejected(case, 'unexpected/expired skip')

    def test_core_accepted_control_skip_still_cannot_be_zero_skip_child_evidence(self):
        case = fixture()
        # 只在 synthetic 控制输入中构造可接受 policy，不改真实日期/policy或 clock。
        case['child']['plan']['allowed_skips'] = {NATIVE_IDS[0]:
            dict(profile='django', reason='synthetic', review_by='9999-12-31')}
        rebind(case); self.assertBaseline(case)
        case['reports'][0]['report']['skips'] = [dict(id=NATIVE_IDS[0], reason='synthetic')]
        accepted = core.verify_results(case['child']['plan'], [case['reports'][0]['report']])
        self.assertEqual(accepted['status'], 'passed')
        self.assertEqual(accepted['skipped_count'], 1)
        with self.assertRaisesRegex(evidence.IncompleteChildEvidence, 'zero actual skips required'):
            evidence.verify_child_evidence(**case)

    def test_child_source_run_image_control_and_parent_cannot_mix_even_with_rehashed_digest(self):
        fields = ('test_sha', 'test_tree', 'run_id', 'run_attempt', 'image_id',
                  'catalog_digest', 'rules_digest', 'control_manifest_digest',
                  'image_supply_policy_digest', 'capability_subject_pins_digest',
                  'lifecycle_policy_digest', 'parent_full_digest', 'base_sha', 'head_sha')
        for field in fields:
            case = fixture(); self.assertBaseline(case)
            old = case['child']['plan'][field]
            case['child']['plan'][field] = old + 1 if type(old) is int else old + '0'
            case['child']['plan_digest'] = core.digest(case['child']['plan'])
            with self.subTest(field=field), self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'trusted child mismatch'):
                evidence.verify_child_evidence(**case)

    def test_child_resource_identity_cannot_be_replaced(self):
        case = fixture(); self.assertBaseline(case)
        case['child']['plan']['fixture_inputs']['id'] = 'other-resource'
        case['child']['plan_digest'] = core.digest(case['child']['plan'])
        with self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'trusted child mismatch'):
            evidence.verify_child_evidence(**case)

    def test_mixed_role_or_envelope_child_digest_is_not_a_core_success(self):
        for field, value in [('role', 'ordinary'), ('child_plan_digest', '0' * 64)]:
            case = fixture(); self.assertBaseline(case)
            case['reports'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'report namespace identity mismatch'):
                evidence.verify_child_evidence(**case)

    def test_candidate_own_digest_or_role_cannot_override_trusted_spec(self):
        for field, value in [('plan_digest', '0' * 64), ('role', 'root_singleton')]:
            case = fixture(); self.assertBaseline(case); case['child'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'trusted child mismatch'):
                evidence.verify_child_evidence(**case)

    def test_bool_readiness_or_summary_cannot_replace_raw_reports(self):
        for value in (True, {'passed': True}, [{'passed': True}]):
            case = fixture(); self.assertBaseline(case); case['reports'] = value
            with self.subTest(value=value), self.assertRaises(evidence.BindingEvidenceRejected):
                evidence.verify_child_evidence(**case)

    def test_raw_report_unknown_or_missing_fields_are_schema_errors(self):
        for variant in ('extra', 'missing'):
            case = fixture(); self.assertBaseline(case)
            report = case['reports'][0]['report']
            if variant == 'extra': report['passed'] = True
            else: report.pop('executed')
            with self.subTest(variant=variant), self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'raw report fields'):
                evidence.verify_child_evidence(**case)

    def test_boolean_numeric_and_nonlist_raw_fields_are_not_silently_core_equal(self):
        for field, value in [('run_attempt', True), ('exit_code', False), ('skips', False), ('executed', tuple(NATIVE_IDS))]:
            case = fixture(); self.assertBaseline(case); case['reports'][0]['report'][field] = value
            with self.subTest(field=field), self.assertRaises(evidence.BindingEvidenceRejected):
                evidence.verify_child_evidence(**case)

    def test_duplicate_plan_batch_or_count_drift_is_rejected_before_core_dict_collapse(self):
        for variant in ('duplicate-key', 'count', 'duplicate-id'):
            case = fixture(); self.assertBaseline(case); plan = case['child']['plan']
            if variant == 'duplicate-key': plan['batches'].append(copy.deepcopy(plan['batches'][0]))
            elif variant == 'duplicate-id': plan['batches'][0]['ids'].append(NATIVE_IDS[0])
            else: plan['count'] += 1
            rebind(case)
            with self.subTest(variant=variant), self.assertRaises(evidence.BindingEvidenceRejected):
                evidence.verify_child_evidence(**case)

    def test_same_batch_key_in_distinct_child_role_is_namespaced_without_full_aggregation(self):
        first = fixture(); first_result = self.assertBaseline(first)
        other = fixture(); plan = other['child']['plan']
        other['child']['role'] = 'ordinary'; plan.pop('fixture_inputs')
        plan['labels'] = ['example.tests.C.test_alpha']; plan['count'] = 1
        plan['batches'] = [dict(key='batch-000', profile='django', ids=list(plan['labels']))]
        other['reports'][0]['report']['executed'] = list(plan['labels']); rebind(other)
        second_result = self.assertBaseline(other)
        self.assertNotEqual(first_result['reports'][0]['namespace'], second_result['reports'][0]['namespace'])
        self.assertEqual(second_result['count'], 1)
        self.assertNotIn('full_complete', first_result)
        self.assertNotIn('full_complete', second_result)

    def test_namespace_paths_and_unknown_roles_are_rejected(self):
        case = fixture(); self.assertBaseline(case)
        case['reports'][0]['report']['key'] = '../batch-000'
        with self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'raw batch key'):
            evidence.verify_child_evidence(**case)
        case = fixture(); self.assertBaseline(case)
        case['expected_child']['role'] = 'unknown'
        with self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'trusted role'):
            evidence.verify_child_evidence(**case)

    def test_ordinary_empty_child_is_zero_evidence_count_never_full(self):
        case = fixture(); self.assertBaseline(case)
        plan = case['child']['plan']; case['child']['role'] = 'ordinary'; plan.pop('fixture_inputs')
        plan.update(labels=[], batches=[], count=0); case['reports'] = []; rebind(case)
        result = self.assertBaseline(case)
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['reports'], [])
        self.assertEqual(result['status'], 'CHILD_EVIDENCE_VALID_GATE_NOT_READY')

    def test_expanded_semantics_are_preserved_in_original_core_result(self):
        case = fixture(); self.assertBaseline(case)
        case['child']['role'] = 'ordinary'; plan = case['child']['plan']; plan.pop('fixture_inputs')
        ids = ['example.tests.C%03d.test_x' % n for n in range(401)]
        plan.update(mode='expanded', labels=ids, count=401,
                    batches=core.shard_tests([dict(id=i, profile='django') for i in ids]))
        template = copy.deepcopy(case['reports'][0]['report'])
        case['reports'] = []
        for batch in plan['batches']:
            report = copy.deepcopy(template)
            report.update(key=batch['key'], profile=batch['profile'], executed=list(batch['ids']))
            case['reports'].append(dict(role='ordinary', child_plan_digest='', report=report))
        rebind(case)
        result = self.assertBaseline(case)
        self.assertEqual(result['core_result']['mode'], 'expanded')
        self.assertEqual(result['count'], 401)
        case['child']['plan']['mode'] = 'full'; rebind(case)
        with self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'child mode'):
            evidence.verify_child_evidence(**case)

    def test_formal_gate_always_not_ready_even_with_well_shaped_forged_controls(self):
        case = fixture(); result = self.assertBaseline(case)
        for value in (result, {'independent_verified': True, 'root': 'READY', 'image': 'READY'}):
            with self.subTest(value=value), self.assertRaises(evidence.FormalGateNotReady):
                evidence.formal_gate(value)


if __name__ == '__main__':
    unittest.main()
