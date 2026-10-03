"""小型 fixture 验证选测策略，不运行真实 stable 全量。"""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.test_impact import core

RULES = {
    'schema_version': 1,
    'docs': ['docs/**/*.md', 'README.md'],
    'high_risk': ['server/stable/models.py', 'requirements*.txt', 'tools/test_impact/**'],
    'paths': {'server/stable/templates/horse.html': ['horse'], 'server/stable/parser.py': ['parser']},
    'symbols': {'server/stable/views.py': {'horse_page': ['horse'], 'news_page': ['news']}},
}
CATALOG = {
    'schema_version': 1,
    'domains': {'core': ['stable.test_core'], 'horse': ['stable.test_horse'],
                'news': ['stable.test_news'], 'parser': ['stable.test_parser'],
                'results': ['stable.test_results'], 'release': ['stable.test_release']},
    'dependencies': {'parser': ['results']},
    'tests': {'server/stable/test_horse.py': {'label': 'stable.test_horse', 'domains': ['horse']}},
}


def change(path, before='', after=''):
    return {'path': path, 'before': before, 'after': after}


class SelectionTests(unittest.TestCase):
    def select(self, *changes):
        return core.select_changes(list(changes), RULES, CATALOG)

    def test_documentation_needs_no_business_tests(self):
        p = self.select(change('docs/guide/readme.md'))
        self.assertEqual(p['mode'], 'docs-only')
        self.assertEqual(p['labels'], [])

    def test_horse_template_is_targeted_with_core(self):
        p = self.select(change('server/stable/templates/horse.html'))
        self.assertEqual(p['mode'], 'targeted')
        self.assertEqual(p['labels'], ['stable.test_core', 'stable.test_horse'])

    def test_parser_includes_downstream(self):
        p = self.select(change('server/stable/parser.py'))
        self.assertEqual(p['labels'], ['stable.test_core', 'stable.test_parser', 'stable.test_results'])

    def test_unknown_path_is_error_not_full_or_empty(self):
        with self.assertRaisesRegex(ValueError, 'unmapped'):
            self.select(change('server/stable/new_service.py'))

    def test_data_file_is_not_documentation(self):
        with self.assertRaisesRegex(ValueError, 'unmapped'):
            self.select(change('docs/policy.json'))

    def test_shared_model_is_full(self):
        p = self.select(change('server/stable/models.py'))
        self.assertEqual(p['mode'], 'full')
        self.assertIn('stable.test_release', p['labels'])

    def test_changed_test_selects_its_domain(self):
        p = self.select(change('server/stable/test_horse.py'))
        self.assertEqual(p['labels'], ['stable.test_core', 'stable.test_horse'])

    def test_one_view_function_is_targeted(self):
        old = 'def horse_page():\n return 1\ndef news_page():\n return 2\n'
        new = old.replace('return 1', 'return 3')
        self.assertEqual(self.select(change('server/stable/views.py', old, new))['labels'],
                         ['stable.test_core', 'stable.test_horse'])

    def test_module_initialization_expands_registered_domains(self):
        old = 'X = 1\ndef horse_page():\n return X\n'
        p = self.select(change('server/stable/views.py', old, old.replace('X = 1', 'X = 2')))
        self.assertEqual(p['labels'], ['stable.test_core', 'stable.test_horse', 'stable.test_news'])

    def test_new_unmapped_function_fails(self):
        with self.assertRaisesRegex(ValueError, 'unmapped'):
            self.select(change('server/stable/views.py', '', 'def other():\n return 1\n'))

    def test_decorator_and_default_value_are_changes(self):
        for old,new in [('def horse_page(x=1):\n return x\n','def horse_page(x=2):\n return x\n'),
                        ('@old\ndef horse_page():\n pass\n','@new\ndef horse_page():\n pass\n')]:
            self.assertIn('horse', self.select(change('server/stable/views.py',old,new))['domains'])

    def test_empty_diff_does_not_forge_success(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.select()




class EvidenceTests(unittest.TestCase):
    def fixture(self):
        plan={'mode':'targeted','batches':[{'key':'batch-000','profile':'django','ids':['m.C.test_x']}],
              'run_id':'100','run_attempt':'1','test_tree':'tree','allowed_skips':{}}
        report={'key':'batch-000','profile':'django','executed':['m.C.test_x'],'plan_digest':core.digest(plan),
                'run_id':'100','run_attempt':'1','test_tree':'tree','exit_code':0,'lifecycle':'complete',
                'failures':[],'errors':[],'skips':[],'unexpected_successes':[],'expected_failures':[]}
        return plan,report

    def test_valid_batch(self):
        plan,report=self.fixture();self.assertEqual(core.verify_results(plan,[report])['count'],1)

    def test_missing_duplicate_batch_fail(self):
        p,r=self.fixture()
        for reports in ([],[r,r]):
            with self.assertRaises(ValueError):core.verify_results(p,reports)

    def test_stale_identity_failed_teardown_and_skips_fail(self):
        for key,value in [('run_attempt','2'),('test_tree','other'),('lifecycle','incomplete'),('exit_code',1),
                          ('skips',[{'id':'m.C.test_x','reason':'PG missing'}]),('executed',[]),
                          ('executed',['m.C.test_x','m.C.test_x']),('expected_failures',['m.C.test_x'])]:
            p,r=self.fixture();r[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):core.verify_results(p,[r])

    def test_class_boundaries_preserved(self):
        tests=[{'id':f'm.{c}.test_{i:03}','profile':'django'} for c in ('A','B','C') for i in range(90)]
        batches=core.shard_tests(tests)
        self.assertEqual([len(b['ids']) for b in batches],[180,90])
        with self.assertRaisesRegex(ValueError,'exceeds'):
            core.shard_tests([{'id':f'm.C.test_{i}','profile':'django'} for i in range(201)])

    def test_human_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            core.shard_tests([{'id':'m.C.test_x','profile':'django'}]*2)

    def test_expensive_migration_classes_get_separate_batches(self):
        tests=[{'id':f'm.{cls}.test_{i}','profile':'django','dedicated_batch':cls=='B'}
               for cls in ('A','B','C') for i in range(2)]
        batches=core.shard_tests(tests)
        self.assertEqual([len(b['ids']) for b in batches],[2,2,2])
        self.assertEqual({i for b in batches for i in b['ids']},{t['id'] for t in tests})

    def test_rule_downgrade_retains_old_requirements(self):
        old={'mode':'full','domains':['old'],'labels':['m.old'],'reasons':[]}
        new={'mode':'docs-only','domains':[],'labels':[],'reasons':[]}
        self.assertEqual(core.union_selection(old,new)['labels'],['m.old'])
        self.assertEqual(core.union_selection(old,new)['mode'],'full')





class RealMappingTests(unittest.TestCase):
    def select_path(self,path):
        import json
        rules=json.loads((ROOT/'tools/test_impact/rules.json').read_text())
        catalog=json.loads((ROOT/'tools/test_impact/catalog.json').read_text())
        return core.select_changes([change(path)],rules,catalog)

    def test_result_write_selects_public_read_and_repair_contracts(self):
        labels=self.select_path('server/stable/services/race_data_sync_results.py')['labels']
        self.assertIn('stable.test_race_data_sync_chain_e2e',labels)
        self.assertIn('stable.test_race_data_sync_repair',labels)

    def test_publish_service_selects_frozen_exclusion_batch_contract(self):
        labels=self.select_path('server/stable/services/horse_profile_publish.py')['labels']
        self.assertIn('stable.test_p0_horse_completion_batch.P0HorseBatchAutoPublishTests',labels)

    def test_shared_fixture_is_high_risk(self):
        for path in ('server/stable/test_migration_database_helpers.py','server/stable/tests/__init__.py'):
            self.assertEqual(self.select_path(path)['mode'],'full')

    def test_historical_runner_selects_recovery_phase_permissions(self):
        labels=self.select_path('server/stable/services/historical_batch_runner.py')['labels']
        self.assertIn('stable.test_race_result_recovery_integration.RaceResultRecoveryCoverageAndRunnerIntegrationTests.test_recovery_commands_have_disjoint_runner_phase_classification',labels)

    def test_collector_selects_hurdles_and_integrity_contracts(self):
        labels=self.select_path('runtime/research/collect_graded_race_participants.py')['labels']
        for module in ('test_collect_graded_race_participants_hurdles','test_collect_graded_race_participants_integrity_contract'):
            self.assertIn('runtime.research.'+module,labels)

    def test_timeliness_core_and_tests_select_pure_contract_regressions(self):
        import json
        catalog=json.loads((ROOT/'tools/test_impact/catalog.json').read_text())
        for path in ('server/stable/services/race_timeliness_contracts.py',
                     'server/stable/test_race_timeliness_contracts.py'):
            with self.subTest(path=path):
                selection=self.select_path(path)
                self.assertEqual(selection['mode'],'targeted')
                self.assertIn('stable.test_race_timeliness_contracts',selection['labels'])
                self.assertIn('stable.test_content_contracts',selection['labels'])
        self.assertEqual(catalog['profiles']['stable.test_race_timeliness_contracts'],'python')

    def test_f01_changes_include_timeliness_downstream(self):
        for path in ('server/stable/services/content_contracts.py',
                     'docs/changes/next-version-capabilities/lanes/A/F01-contract-examples.json'):
            with self.subTest(path=path):
                selection=self.select_path(path)
                self.assertEqual(selection['mode'],'targeted')
                self.assertIn('stable.test_race_timeliness_contracts',selection['labels'])
                self.assertIn('stable.test_content_contracts',selection['labels'])

if __name__ == "__main__": unittest.main()
