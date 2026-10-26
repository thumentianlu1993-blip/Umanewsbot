"""B251 纯结构 oracle；未接入正式 gate，真实执行须另卡授权。

每个负例针对集合遗漏、身份互串或摘要/能力旁路；不调用应用、进程或网络。
fixture 的标准分批与摘要使用未修改的 core 作为兼容性参考。
"""
import copy
import unittest

from tools.test_impact.core import digest, shard_tests
from tools.test_impact import full_composition as fc

SPECIAL = {'cache_primary3': ['stable.test_historical_race_detail_direct_urls.HistoricalRaceDetailDirectUrlTests.test_sporting_life_real_cache_preserves_structured_non_finish_statuses', 'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_jra_2005_legacy_page_preserves_distance_unit', 'stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_equibase_yearbook_result_preserves_distance_unit'], 'cache_secondary2': ['stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_package_rejects_raw_candidate_without_validation_evidence'], 'cache_remaining3': ['stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units', 'stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity'], 'image_singleton': ['stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file'], 'root_singleton': ['stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace']}


def fixture():
    identity = {k: c * n for k, c, n in (
        ('base_sha', 'a', 40), ('head_sha', 'b', 40),
        ('test_sha', 'c', 40), ('test_tree', 'd', 40),
        ('catalog_digest', 'e', 64), ('rules_digest', 'f', 64),
        ('control_manifest_digest', '1', 64), ('image_supply_policy_digest', '2', 64),
        ('capability_subject_pins_digest', '3', 64), ('lifecycle_policy_digest', '4', 64))}
    identity.update(run_id='9001', run_attempt=1, image_id='sha256:' + '5' * 64)
    ids = sorted([i for group in SPECIAL.values() for i in group] + [
        'example.tests.Ordinary.test_alpha', 'example.tests.Ordinary.test_beta',
        'stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_other'])
    labels = sorted({i.rsplit('.', 2)[0] for i in ids})
    catalog = dict(schema_version=1, domains={'core': labels, 'overlap': [labels[0]]},
                   profiles={label: 'django' for label in labels},
                   dedicated_batch_modules=[], allowed_skips={})
    rules = {'schema_version': 1, 'high_risk': ['tools/test_impact/*']}
    identity['catalog_digest'], identity['rules_digest'] = digest(catalog), digest(rules)
    records = [dict(id=i, profile='django', dedicated_batch=False) for i in ids]
    collect = dict(mode='full', identity=copy.deepcopy(identity), labels=list(labels),
                   batches=shard_tests(records), count=len(ids), aliases=[], collection_skips=[],
                   producer=dict(kind='candidate', invocation_id='collect-c0', raw_sha256='6' * 64))
    independent = copy.deepcopy(collect)
    independent['producer'] = dict(kind='candidate-external', invocation_id='collect-c1', raw_sha256='7' * 64)
    return dict(identity=identity, catalog=catalog, rules=rules, candidate=collect,
                independent=independent, protected_native_ids=ids)


def compile_case(case=None):
    return fc.compile_parent(**(fixture() if case is None else case))


def context(case):
    return {k: case[k] for k in ('identity', 'catalog', 'rules', 'protected_native_ids')}


def execution(case):
    parent = compile_case(case)
    children = fc.derive_children(parent, **context(case))
    reports = []
    for child in children:
        plan = child['plan']
        for batch in plan['batches']:
            report = dict(key=batch['key'], profile=batch['profile'], plan_digest=digest(plan),
                          **{k: plan[k] for k in ('run_id', 'run_attempt', 'test_tree')},
                          executed=list(batch['ids']), failures=[], errors=[], skips=[],
                          expected_failures=[], unexpected_successes=[], lifecycle='complete', exit_code=0)
            reports.append(dict(role=child['role'], child_plan_digest=child['plan_digest'], report=report))
    capabilities = [dict(role=role, status='READY') for role in ('image_singleton', 'root_singleton')]
    return dict(parent=parent, children=children, reports=reports, capabilities=capabilities, **context(case))


class FullCompositionTests(unittest.TestCase):
    def test_six_exact_routes_with_fresh_nonhistorical_count(self):
        case = fixture()
        original = copy.deepcopy(case)
        parent = compile_case(case)
        self.assertEqual(case, original)
        self.assertEqual(parent['count'], 13)
        self.assertEqual(parent['selection_labels'], case['candidate']['labels'])
        routes = {s['role']: s['plan'] for s in parent['child_specs']}
        self.assertEqual(set(routes), {'ordinary', *SPECIAL})
        for role, ids in SPECIAL.items():
            actual = [i for b in routes[role]['batches'] for i in b['ids']]
            self.assertEqual(sorted(actual), sorted(ids))
            self.assertEqual(routes[role]['count'], len(ids))
            self.assertEqual(routes[role]['mode'], 'targeted')
        self.assertEqual(routes['ordinary']['count'], 3)
        self.assertEqual(parent['lifecycle_policy'], 'class-lifecycle-per-route-v1')
        self.assertEqual(routes['root_singleton']['batches'][0]['profile'], 'django')
        self.assertIn('stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_other',
                      routes['ordinary']['labels'])

    def test_expanded_ordinary_route_uses_fresh_count_and_other_original_profiles(self):
        case = fixture()
        case['catalog']['profiles']['example.tests'] = 'release-postgres'
        case['catalog']['dedicated_batch_modules'] = ['example.tests']
        case['identity']['catalog_digest'] = digest(case['catalog'])
        for key in ('candidate', 'independent'):
            collect = case[key]
            collect['identity'] = copy.deepcopy(case['identity'])
            ids = [i for b in collect['batches'] for i in b['ids']]
            ids += ['example.tests.C%03d.test_x' % n for n in range(401)]
            collect['batches'] = shard_tests([dict(id=i,
                profile='release-postgres' if i.startswith('example.tests.') else 'django',
                dedicated_batch=i.startswith('example.tests.')) for i in ids])
            collect['count'] = len(ids)
        parent = compile_case(case)
        self.assertEqual(parent['count'], 414)
        ordinary = parent['child_specs'][0]['plan']
        self.assertEqual(ordinary['mode'], 'expanded')
        self.assertEqual(ordinary['count'], 404)
        profiles = {b['profile'] for b in ordinary['batches']}
        self.assertEqual(profiles, {'django', 'release-postgres'})

    def test_resource_quartets_keep_exact_ids_manifests_and_source(self):
        case = fixture()
        plans = {s['role']: s['plan'] for s in compile_case(case)['child_specs']}
        expected = {
            'cache_primary3': ('b239-primary3-v1', 'b169ea447a8f6dbc00bb5123df24fe9de50d5da25652eb0329ba5698b5d1ebf9'),
            'cache_secondary2': ('b243-secondary2-v1', 'd564676417d45ed1b49dc08d4877cbde555b537939477f5c11fb070055052e93'),
            'cache_remaining3': ('b243-remaining3-fixture-bound-v1', '3a068de66eea198421897895dce1f00d33772d903a391757e65898bf896ca4a4')}
        for role, (resource, manifest) in expected.items():
            self.assertEqual(plans[role]['fixture_inputs'], dict(id=resource, manifest_sha256=manifest,
                source_sha=case['identity']['test_sha'], source_tree=case['identity']['test_tree']))
        self.assertNotIn('fixture_inputs', plans['ordinary'])
        self.assertNotIn('fixture_inputs', plans['root_singleton'])

    def test_boolean_count_and_wrong_catalog_or_rules_digest_are_rejected(self):
        for mutation in ('count', 'catalog', 'rules'):
            case = fixture()
            if mutation == 'count':
                for key in ('candidate', 'independent'): case[key]['count'] = True
            else: case[mutation]['unexpected'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): compile_case(case)

    def test_child_digest_is_own_unchanged_core_digest_without_cycle(self):
        case = fixture()
        parent = compile_case(case)
        for child, spec in zip(fc.derive_children(parent, **context(case)), parent['child_specs']):
            self.assertNotIn('plan_digest', spec)
            self.assertNotIn('parent_full_digest', spec['plan'])
            self.assertEqual(child['plan']['parent_full_digest'], digest(parent))
            self.assertEqual(child['plan_digest'], digest(child['plan']))
            self.assertNotEqual(child['plan_digest'], digest(parent))
            expected = copy.deepcopy(spec['plan'])
            expected['parent_full_digest'] = digest(parent)
            self.assertEqual(child['plan'], expected)

    def test_standard_route_batches_match_original_class_sharder(self):
        case = fixture()
        for child in fc.derive_children(compile_case(case), **context(case)):
            plan = child['plan']
            self.assertEqual(plan['batches'], shard_tests([
                dict(id=i, profile='django', dedicated_batch=False) for i in plan['labels']]))

    def test_execution_structure_never_claims_formal_pass(self):
        args = execution(fixture())
        self.assertEqual(fc.check_execution_structure(**args), {
            'status': 'STRUCTURE_VALID_GATE_NOT_READY', 'count': 13, 'skipped_count': 0})
        with self.assertRaises(fc.NotReady):
            fc.formal_gate(**args)
        with self.assertRaises(fc.NotReady):
            fc.formal_gate(independent_verified=True, capabilities_verified=True)

    def test_same_named_batch_in_different_role_has_distinct_namespace(self):
        a = fc.batch_namespace('ordinary', 'a' * 64, 'batch-000')
        b = fc.batch_namespace('root_singleton', 'b' * 64, 'batch-000')
        self.assertEqual(a, 'roles/ordinary/' + 'a' * 64 + '/batch-000.json')
        self.assertNotEqual(a, b)
        for role, sha, key in [('other', 'a' * 64, 'batch-000'),
                               ('ordinary', '../x', 'batch-000'),
                               ('ordinary', 'a' * 64, '../batch-000'),
                               ('ordinary', 'a' * 64, 'batch-000.json')]:
            with self.subTest(role=role, sha=sha, key=key), self.assertRaises(ValueError):
                fc.batch_namespace(role, sha, key)

    def test_missing_or_boolean_independent_receipt_is_rejected(self):
        for value in (None, True, {'independent': True}):
            case = fixture(); case['independent'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_case(case)

    def test_same_invocation_or_candidate_origin_cannot_be_independent(self):
        for field, value in [('invocation_id', 'collect-c0'), ('kind', 'candidate')]:
            case = fixture(); case['independent']['producer'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): compile_case(case)

    def test_matching_candidate_subsets_are_not_full_labels(self):
        case = fixture()
        self.assertIsNot(case['candidate']['labels'], case['catalog']['domains']['core'])
        self.assertIsNot(case['independent']['labels'], case['catalog']['domains']['core'])
        self.assertIsNot(case['candidate']['labels'], case['independent']['labels'])
        trusted = copy.deepcopy(context(case))
        self.assertEqual(compile_case(case)['count'], 13)
        for collect in (case['candidate'], case['independent']): collect['labels'].pop()
        self.assertEqual(context(case), trusted)
        self.assertEqual(case['identity']['catalog_digest'], digest(case['catalog']))
        with self.assertRaisesRegex(ValueError, r'\Afull composition: not complete sorted catalog labels\Z'):
            compile_case(case)

    def test_source_run_attempt_image_and_control_identity_cannot_mix(self):
        for field in fixture()['identity']:
            case = fixture(); old = case['independent']['identity'][field]
            case['independent']['identity'][field] = old + 1 if type(old) is int else old + '0'
            with self.subTest(field=field), self.assertRaises(ValueError): compile_case(case)

    def test_count_missing_extra_duplicate_unknown_profile_and_batch_collision(self):
        for mutation in ('count', 'missing', 'extra', 'duplicate', 'profile', 'key'):
            case = fixture()
            if mutation == 'key':
                # 原 sharder 的合法 dedicated-class 前件，不手造第二个 batch。
                case['catalog']['dedicated_batch_modules'] = ['example.tests']
                case['identity']['catalog_digest'] = digest(case['catalog'])
                for collect in (case['candidate'], case['independent']):
                    records = [dict(id=ident, profile=batch['profile'],
                                    dedicated_batch=ident.startswith('example.tests.'))
                               for batch in collect['batches'] for ident in batch['ids']]
                    collect['batches'] = shard_tests(records)
                    collect['identity'] = copy.deepcopy(case['identity'])
                    self.assertGreaterEqual(len(collect['batches']), 2)
                self.assertEqual(compile_case(case)['count'], 13)
            for collect in (case['candidate'], case['independent']):
                batch = collect['batches'][0]
                if mutation == 'count': collect['count'] += 1
                elif mutation == 'missing': batch['ids'].pop()
                elif mutation == 'extra': batch['ids'].append('unknown.C.test_unowned')
                elif mutation == 'duplicate': batch['ids'].append(batch['ids'][0])
                elif mutation == 'profile': batch['profile'] = 'other'
                else: collect['batches'][1]['key'] = batch['key']
            rejection = (self.assertRaisesRegex(ValueError, r'\Afull composition: invalid/duplicate batch key\Z')
                         if mutation == 'key' else self.assertRaises(ValueError))
            with self.subTest(mutation=mutation), rejection: compile_case(case)

    def test_protected_id_deletion_even_when_count_and_batches_are_self_consistent(self):
        case = fixture()
        removed = 'example.tests.Ordinary.test_alpha'
        for collect in (case['candidate'], case['independent']):
            batch = next(b for b in collect['batches'] if removed in b['ids'])
            batch['ids'].remove(removed); collect['count'] -= 1
        with self.assertRaises(ValueError): compile_case(case)

    def test_unknown_and_duplicate_alias_are_rejected(self):
        for aliases in ([dict(id='unknown.C.test_a', label='example.tests')],
                        [dict(id='example.tests.Ordinary.test_alpha', label='not.selected')],
                        [dict(id='example.tests.Ordinary.test_alpha', label='example.tests')] * 2):
            case = fixture()
            for collect in (case['candidate'], case['independent']): collect['aliases'] = aliases
            with self.subTest(aliases=aliases), self.assertRaises(ValueError): compile_case(case)

    def test_parent_cannot_change_specs_universe_count_or_lifecycle_after_freeze(self):
        case = fixture()
        for field, value in [('count', 12), ('universe', []), ('lifecycle_policy', 'same-global-lifecycle'),
                             ('child_specs', []), ('child_digests', ['a' * 64])]:
            parent = compile_case(case); parent[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                fc.derive_children(parent, **context(case))

    def test_expired_skip_policies_are_preserved_but_actual_skip_is_forbidden(self):
        case = fixture()
        case['catalog']['allowed_skips'] = {'example.tests.Ordinary.test_alpha': {
            'profile': 'django', 'reason': 'legacy', 'review_by': '2026-10-16'}}
        case['identity']['catalog_digest'] = digest(case['catalog'])
        for key in ('candidate', 'independent'): case[key]['identity'] = copy.deepcopy(case['identity'])
        parent = compile_case(case)
        self.assertEqual(parent['allowed_skips'], case['catalog']['allowed_skips'])
        args = execution(case)
        args['reports'][0]['report']['skips'] = [dict(id='example.tests.Ordinary.test_alpha', reason='legacy')]
        with self.assertRaises(ValueError): fc.check_execution_structure(**args)

    def test_execution_rejects_missing_duplicate_extra_role_or_report(self):
        for mutation in ('missing-child', 'duplicate-child', 'unknown-role', 'missing-report', 'duplicate-report'):
            args = execution(fixture())
            if mutation == 'missing-child': args['children'].pop()
            elif mutation == 'duplicate-child': args['children'].append(copy.deepcopy(args['children'][0]))
            elif mutation == 'unknown-role': args['children'][0]['role'] = 'unknown'
            elif mutation == 'missing-report': args['reports'].pop()
            else: args['reports'].append(copy.deepcopy(args['reports'][0]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): fc.check_execution_structure(**args)

    def test_execution_rejects_raw_identity_digest_profile_or_lifecycle_mix(self):
        for field, value in [('plan_digest', '0' * 64), ('run_attempt', 2), ('run_id', '9002'),
                             ('test_tree', 'e' * 40), ('profile', 'other'), ('lifecycle', 'unknown'),
                             ('exit_code', 1), ('exit_code', False)]:
            args = execution(fixture()); args['reports'][0]['report'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                fc.check_execution_structure(**args)

    def test_execution_rejects_any_nonempty_outcome_or_wrong_multiset(self):
        for field in ('failures', 'errors', 'expected_failures', 'unexpected_successes', 'skips', 'executed'):
            args = execution(fixture()); report = args['reports'][0]['report']
            report[field].append(report['executed'][0])
            with self.subTest(field=field), self.assertRaises(ValueError): fc.check_execution_structure(**args)
        for change in ('missing', 'extra'):
            args = execution(fixture()); ids = args['reports'][0]['report']['executed']
            if change == 'missing': ids.pop()
            else: ids.append('unknown.C.test_a')
            with self.subTest(change=change), self.assertRaises(ValueError): fc.check_execution_structure(**args)

    def test_cross_role_digest_and_child_plan_mutation_are_rejected(self):
        for mutation in ('report-role', 'child-digest', 'child-plan'):
            args = execution(fixture())
            if mutation == 'report-role': args['reports'][0]['role'] = 'root_singleton'
            elif mutation == 'child-digest': args['children'][0]['plan_digest'] = '0' * 64
            else: args['children'][0]['plan']['mode'] = 'full'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): fc.check_execution_structure(**args)

    def test_blocked_or_missing_capabilities_fail_closed(self):
        for value in ([], [dict(role='image_singleton', status='READY')],
                      [dict(role='image_singleton', status='BLOCKED'), dict(role='root_singleton', status='READY')],
                      [dict(role='image_singleton', status='READY'), dict(role='root_singleton', status='NOT_READY')]):
            args = execution(fixture()); args['capabilities'] = value
            with self.subTest(value=value), self.assertRaises(fc.NotReady): fc.check_execution_structure(**args)
        args = execution(fixture()); args['capabilities'].append(dict(role='ordinary', status='READY'))
        with self.assertRaises(ValueError): fc.check_execution_structure(**args)


if __name__ == '__main__':
    unittest.main()
