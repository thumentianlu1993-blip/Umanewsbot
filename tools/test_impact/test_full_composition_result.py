"""B256 合成六角色机制 oracle；不是实际 full/native 执行或能力资格。

独立 fixture；不导入/重跑旧43方法，不 mock 已批准三个真实接口或 core。
先以旧 derive/结构检查/child core 建立合法基线，再逐项篡改。
"""
import copy
import unittest

from tools.test_impact import core
from tools.test_impact import full_composition as composition
from tools.test_impact import full_composition_evidence as evidence
from tools.test_impact import full_composition_result as result_module

SPECIAL_IDS = {'cache_primary3': ('stable.test_historical_race_detail_direct_urls.HistoricalRaceDetailDirectUrlTests.test_sporting_life_real_cache_preserves_structured_non_finish_statuses', 'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_jra_2005_legacy_page_preserves_distance_unit', 'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_equibase_yearbook_result_preserves_distance_unit'), 'cache_secondary2': ('stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_package_rejects_raw_candidate_without_validation_evidence'), 'cache_remaining3': ('stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity'), 'image_singleton': ('stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file',), 'root_singleton': ('stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace',)}


def fixture(*, ordinary=True, allowed_skip=False, added=False):
    ids = [ident for group in SPECIAL_IDS.values() for ident in group]
    if ordinary:
        ids += ['example.tests.Ordinary.test_alpha', 'example.tests.Ordinary.test_beta']
    if added:
        ids.append('example.tests.Added.test_gamma')
    ids = sorted(ids)
    labels = sorted({ident.rsplit('.', 2)[0] for ident in ids})
    catalog = dict(schema_version=1, domains={'core': list(labels)},
                   profiles={label: 'django' for label in labels}, dedicated_batch_modules=[], allowed_skips={})
    if allowed_skip:
        catalog['allowed_skips'] = {'example.tests.Ordinary.test_alpha':
            dict(profile='django', reason='synthetic-control', review_by='9999-12-31')}
    rules = {'schema_version': 1, 'synthetic_control': True}
    identity = dict(base_sha='a' * 40, head_sha='b' * 40, test_sha='c' * 40, test_tree='d' * 40,
                    run_id='256001', run_attempt=1, image_id='sha256:' + 'e' * 64,
                    catalog_digest=core.digest(catalog), rules_digest=core.digest(rules),
                    control_manifest_digest='1' * 64, image_supply_policy_digest='2' * 64,
                    capability_subject_pins_digest='3' * 64, lifecycle_policy_digest='4' * 64)
    c0 = dict(mode='full', identity=copy.deepcopy(identity), labels=list(labels),
              batches=core.shard_tests([dict(id=i, profile='django') for i in ids]), count=len(ids),
              aliases=[], collection_skips=[], producer=dict(kind='candidate', invocation_id='synthetic-c0', raw_sha256='5' * 64))
    c1 = copy.deepcopy(c0)
    c1['producer'] = dict(kind='candidate-external', invocation_id='synthetic-c1', raw_sha256='6' * 64)
    context = dict(identity=identity, catalog=catalog, rules=rules, protected_native_ids=list(ids))
    parent = composition.compile_parent(candidate=c0, independent=c1, **context)
    children = composition.derive_children(parent, **context)
    reports = []
    for child in children:
        plan = child['plan']
        for batch in plan['batches']:
            report = dict(key=batch['key'], profile=batch['profile'], plan_digest=core.digest(plan),
                          run_id=plan['run_id'], run_attempt=plan['run_attempt'], test_tree=plan['test_tree'],
                          executed=list(batch['ids']), failures=[], errors=[], skips=[], expected_failures=[],
                          unexpected_successes=[], lifecycle='complete', exit_code=0)
            reports.append(dict(role=child['role'], child_plan_digest=child['plan_digest'], report=report))
    # 仅旧结构接口的 synthetic 输入，绝不冒实际 root/image READY 或独立采集认证。
    capabilities = [dict(role=role, status='READY') for role in ('image_singleton', 'root_singleton')]
    return dict(parent=parent, children=children, reports=reports, capabilities=capabilities, **context)


def trusted_context(case):
    return {k: case[k] for k in ('identity', 'catalog', 'rules', 'protected_native_ids')}


class ParentCoreResultTests(unittest.TestCase):
    def assertBaseline(self, case):
        expected = composition.derive_children(case['parent'], **trusted_context(case))
        for spec in expected:
            child = next(c for c in case['children'] if c['role'] == spec['role'])
            raw = [e for e in case['reports'] if e['role'] == spec['role']]
            checked = evidence.verify_child_evidence(spec, child, raw)
            self.assertEqual(checked['status'], 'CHILD_EVIDENCE_VALID_GATE_NOT_READY')
        self.assertEqual(composition.check_execution_structure(**case)['status'], 'STRUCTURE_VALID_GATE_NOT_READY')
        checked = result_module.verify_parent_result(**case)
        self.assertEqual(checked['status'], 'PARENT_MECHANISM_VALID_GATE_NOT_READY')
        self.assertEqual(checked['count'], len(case['protected_native_ids']))
        return checked

    def test_six_real_child_core_results_and_full_E_remain_mechanism_only(self):
        case = fixture(); before = copy.deepcopy(case)
        checked = self.assertBaseline(case)
        self.assertEqual(case, before)
        self.assertEqual(checked['count'], 12)
        self.assertEqual(checked['parent_full_digest'], core.digest(case['parent']))
        self.assertEqual([c['role'] for c in checked['child_results']], list(composition.ROLES))
        self.assertEqual([c['count'] for c in checked['child_results']], [2, 3, 2, 3, 1, 1])
        self.assertEqual(sum(c['core_result']['count'] for c in checked['child_results']), 12)
        self.assertEqual(checked['structure_result'], dict(status='STRUCTURE_VALID_GATE_NOT_READY', count=12, skipped_count=0))
        self.assertEqual(checked['lifecycle_policy'], 'class-lifecycle-per-route-v1')
        self.assertTrue(all(c['core_result']['mode'] == 'targeted' for c in checked['child_results']))
        self.assertNotIn('full_complete', checked)
        self.assertNotIn('passed', checked)

    def test_same_batch000_different_role_is_not_flattened(self):
        case = fixture(); checked = self.assertBaseline(case)
        self.assertEqual({e['report']['key'] for e in case['reports']}, {'batch-000'})
        namespaces = [r['namespace'] for c in checked['child_results'] for r in c['reports']]
        self.assertEqual(len(namespaces), 6)
        self.assertEqual(len(set(namespaces)), 6)

    def test_ordinary_empty_still_has_derived_child_and_zero_core_count(self):
        case = fixture(ordinary=False); checked = self.assertBaseline(case)
        self.assertEqual(checked['count'], 10)
        self.assertEqual(len(case['children']), 6)
        self.assertEqual(len(case['reports']), 5)
        ordinary = checked['child_results'][0]
        self.assertEqual(ordinary['role'], 'ordinary')
        self.assertEqual(ordinary['core_result']['count'], 0)
        self.assertEqual(ordinary['reports'], [])
        case['children'].pop(0)
        with self.assertRaises(result_module.ParentEvidenceRejected): result_module.verify_parent_result(**case)

    def test_fresh_E_legitimate_addition_increases_count(self):
        case = fixture(added=True); checked = self.assertBaseline(case)
        self.assertEqual(checked['count'], 13)
        self.assertEqual(checked['child_results'][0]['count'], 3)

    def test_children_or_report_input_order_does_not_change_role_ownership(self):
        case = fixture(); baseline = self.assertBaseline(case)
        case['children'].reverse(); case['reports'].reverse()
        checked = result_module.verify_parent_result(**case)
        self.assertEqual([c['role'] for c in checked['child_results']], [c['role'] for c in baseline['child_results']])
        self.assertEqual(checked['count'], 12)
        self.assertEqual(checked['parent_full_digest'], baseline['parent_full_digest'])

    def test_missing_duplicate_extra_and_unknown_child_roles_are_rejected(self):
        for mutation in ('missing', 'duplicate', 'extra', 'unknown'):
            case = fixture(); self.assertBaseline(case)
            if mutation == 'missing': case['children'].pop()
            elif mutation == 'duplicate': case['children'][-1] = copy.deepcopy(case['children'][0])
            elif mutation == 'extra': case['children'].append(copy.deepcopy(case['children'][0]))
            else: case['children'][-1]['role'] = 'unknown'
            with self.subTest(mutation=mutation), self.assertRaises(result_module.ParentEvidenceRejected):
                result_module.verify_parent_result(**case)

    def test_missing_duplicate_extra_known_role_reports_reach_actual_core(self):
        for mutation in ('missing', 'duplicate', 'extra'):
            case = fixture(); self.assertBaseline(case)
            if mutation == 'missing': case['reports'].pop(0)
            else:
                extra = copy.deepcopy(case['reports'][0])
                if mutation == 'extra': extra['report']['key'] = 'batch-999'
                case['reports'].append(extra)
            with self.subTest(mutation=mutation), self.assertRaises(evidence.CoreEvidenceRejected) as raised:
                result_module.verify_parent_result(**case)
            self.assertIs(type(raised.exception.__cause__), ValueError)
            self.assertEqual(str(raised.exception.__cause__), 'missing/duplicate/unexpected batch')

    def test_unknown_report_role_and_summary_cannot_be_discarded(self):
        for mutation in ('unknown-role', 'summary', 'bool'):
            case = fixture(); self.assertBaseline(case)
            if mutation == 'unknown-role': case['reports'][0]['role'] = 'unknown'
            elif mutation == 'summary': case['reports'] = [{'core_passed': True}]
            else: case['reports'] = True
            with self.subTest(mutation=mutation), self.assertRaises(result_module.ParentEvidenceRejected):
                result_module.verify_parent_result(**case)

    def test_cross_child_role_swap_keeps_reports_but_fails_child_digest_binding(self):
        case = fixture(); self.assertBaseline(case)
        first, second = case['reports'][:2]
        first['role'], second['role'] = second['role'], first['role']
        with self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'report namespace identity mismatch'):
            result_module.verify_parent_result(**case)

    def test_envelope_wrong_digest_and_namespace_escape_are_rejected(self):
        for mutation in ('digest', 'path'):
            case = fixture(); self.assertBaseline(case)
            if mutation == 'digest': case['reports'][0]['child_plan_digest'] = '0' * 64
            else: case['reports'][0]['report']['key'] = '../batch-000'
            with self.subTest(mutation=mutation), self.assertRaises(evidence.BindingEvidenceRejected):
                result_module.verify_parent_result(**case)

    def test_self_rehashed_child_cannot_override_derived_source_image_control(self):
        for field in ('test_sha', 'test_tree', 'run_attempt', 'image_id', 'control_manifest_digest', 'parent_full_digest'):
            case = fixture(); self.assertBaseline(case); child = case['children'][0]
            value = child['plan'][field]; child['plan'][field] = value + 1 if type(value) is int else value + '0'
            child['plan_digest'] = core.digest(child['plan'])
            envelope = case['reports'][0]
            envelope['child_plan_digest'] = child['plan_digest']; envelope['report']['plan_digest'] = child['plan_digest']
            with self.subTest(field=field), self.assertRaisesRegex(evidence.BindingEvidenceRejected, 'trusted child mismatch'):
                result_module.verify_parent_result(**case)

    def test_parent_count_specs_and_E_tampering_rejected_by_trusted_rederive(self):
        for field, value in [('count', 11), ('universe', []), ('child_specs', [])]:
            case = fixture(); self.assertBaseline(case); case['parent'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'parent spec mismatch'):
                result_module.verify_parent_result(**case)

    def test_two_candidate_collect_subsets_do_not_shrink_trusted_catalog(self):
        case = fixture(); self.assertBaseline(case); trusted = copy.deepcopy(trusted_context(case))
        for collect in case['parent']['collections'].values(): collect['labels'].pop()
        self.assertEqual(trusted_context(case), trusted)
        with self.assertRaisesRegex(ValueError, 'not complete sorted catalog labels'):
            result_module.verify_parent_result(**case)

    def test_missing_independent_collect_cannot_be_ready_boolean(self):
        for value in (None, True, {'independent_verified': True}):
            case = fixture(); self.assertBaseline(case); case['parent']['collections']['independent'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'collection exact fields required'):
                result_module.verify_parent_result(**case)

    def test_trusted_protected_ID_requirement_cannot_be_dropped_by_candidate(self):
        case = fixture(); self.assertBaseline(case)
        case['protected_native_ids'].append('example.tests.Missing.test_protected')
        with self.assertRaisesRegex(ValueError, 'protected native ID removed'):
            result_module.verify_parent_result(**case)

    def test_raw_wrong_digest_identity_execution_and_outcomes_retain_core_cause(self):
        for field, value, message in (
            ('plan_digest', '0' * 64, 'plan/profile mismatch'),
            ('run_attempt', 2, 'identity mismatch: run_attempt'),
            ('executed', [], 'execution set mismatch'),
            ('executed', ['unknown.C.test_extra'], 'execution set mismatch'),
            ('errors', [dict(id='synthetic', traceback='synthetic')], 'failed test or lifecycle')):
            case = fixture(); self.assertBaseline(case); case['reports'][0]['report'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(evidence.CoreEvidenceRejected) as raised:
                result_module.verify_parent_result(**case)
            self.assertEqual(str(raised.exception.__cause__), message)
        case = fixture(); self.assertBaseline(case)
        case['reports'][0]['report']['executed'].append(case['reports'][0]['report']['executed'][0])
        with self.assertRaises(evidence.CoreEvidenceRejected) as raised: result_module.verify_parent_result(**case)
        self.assertEqual(str(raised.exception.__cause__), 'execution set mismatch')

    def test_unallowed_skip_reaches_core_and_allowed_skip_still_rejected(self):
        for allowed in (False, True):
            case = fixture(allowed_skip=allowed); self.assertBaseline(case)
            case['reports'][0]['report']['skips'] = [dict(id='example.tests.Ordinary.test_alpha', reason='synthetic-control')]
            if allowed:
                with self.assertRaisesRegex(evidence.IncompleteChildEvidence, 'zero actual skips required'):
                    result_module.verify_parent_result(**case)
            else:
                with self.assertRaises(evidence.CoreEvidenceRejected) as raised: result_module.verify_parent_result(**case)
                self.assertEqual(str(raised.exception.__cause__), 'unexpected/expired skip')

    def test_blocked_missing_or_boolean_capability_inputs_are_not_filled_in(self):
        for value in ([], [dict(role='image_singleton', status='BLOCKED'), dict(role='root_singleton', status='READY')]):
            case = fixture(); self.assertBaseline(case); case['capabilities'] = value
            with self.subTest(value=value), self.assertRaises(composition.NotReady): result_module.verify_parent_result(**case)
        case = fixture(); self.assertBaseline(case); case['capabilities'] = True
        with self.assertRaisesRegex(ValueError, 'capabilities list required'): result_module.verify_parent_result(**case)

    def test_candidate_expected_children_are_not_a_public_trust_parameter(self):
        case = fixture(); self.assertBaseline(case)
        with self.assertRaises(TypeError): result_module.verify_parent_result(**case, expected_children=case['children'])

    def test_formal_gate_stays_not_ready_even_for_valid_mechanism_result(self):
        case = fixture(); checked = self.assertBaseline(case)
        with self.assertRaises(evidence.FormalGateNotReady): result_module.formal_gate(checked)
        with self.assertRaises(evidence.FormalGateNotReady): result_module.formal_gate(independent_verified=True, ready=True)


if __name__ == '__main__':
    unittest.main()
