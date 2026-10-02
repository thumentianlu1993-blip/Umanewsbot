import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'run_bounded_stable_tests.py'
spec = importlib.util.spec_from_file_location('bounded', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SelectionContractTests(unittest.TestCase):
    def test_empty_selection_rejected(self):
        with self.assertRaises(ValueError):
            module.validate_selection(unittest.TestSuite())

    def test_more_than_200_rejected(self):
        suite = unittest.TestSuite(unittest.FunctionTestCase(lambda: None) for _ in range(201))
        with self.assertRaisesRegex(ValueError, '200'):
            module.validate_selection(suite)

    def test_duplicate_test_id_rejected(self):
        case = unittest.FunctionTestCase(lambda: None)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            module.validate_selection(unittest.TestSuite([case, case]))

    def test_unknown_label_rejected_before_database_setup(self):
        suite = unittest.TestLoader().loadTestsFromName('no_such_test_label')
        with self.assertRaisesRegex(ValueError, 'load'):
            module.validate_selection(suite)

    def test_nested_suite_expands_exactly(self):
        def first(): pass
        def second(): pass
        cases = [unittest.FunctionTestCase(first), unittest.FunctionTestCase(second)]
        suite = unittest.TestSuite([cases[0], unittest.TestSuite([cases[1]])])
        self.assertEqual(module.validate_selection(suite), [c.id() for c in cases])

    def test_inventory_has_50_unique_mapped_failures(self):
        rows = module.read_inventory()
        self.assertEqual(len(rows), 50)
        self.assertEqual(len({r['test'] for r in rows}), 50)
        self.assertEqual(len({r['replacement'] for r in rows}), 50)
        self.assertEqual({r['group'] for r in rows}, set(range(1,22)))

    def test_incomplete_execution_or_skip_cannot_pass(self):
        expected = ['a', 'b']
        self.assertFalse(module.evidence_passes(expected, ['a'], [], [], [], []))
        self.assertFalse(module.evidence_passes(expected, expected, [], [], [('a','skip')], []))
        self.assertFalse(module.evidence_passes(expected, expected, [('b','failure')], [], [], []))
        self.assertTrue(module.evidence_passes(expected, expected, [], [], [], []))

    def test_database_config_rejects_production_looking_destination(self):
        for values in ({'POSTGRES_HOST':'prod.example'}, {'POSTGRES_DB':'horse_news'},
                       {'POSTGRES_USER':'production'}, {'POSTGRES_PORT':'0'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                module.isolated_environment(values)


class RunnerLifecycleTests(unittest.TestCase):
    def test_real_django_builder_rejects_duplicate_labels_and_class_method_overlap(self):
        from django.test.runner import DiscoverRunner
        method = __name__ + '.SelectionContractTests.test_empty_selection_rejected'
        class_label = __name__ + '.SelectionContractTests'
        for labels in ([method, method], [class_label, method]):
            with self.subTest(labels=labels), self.assertRaisesRegex(ValueError, 'duplicate'):
                module.build_validated_suite(labels, DiscoverRunner(verbosity=0).build_suite)
        suite = module.build_validated_suite([method], DiscoverRunner(verbosity=0).build_suite)
        self.assertEqual(module.validate_selection(suite), [method])

    def test_teardown_failure_never_leaves_passed_evidence(self):
        payload = {'passed': False}
        class Runner:
            def run_tests(self, labels):
                payload.update(passed=True, selected=['a'], executed=['a'], failures=[], errors=[],
                               skipped=[], unexpected_successes=[])
                raise RuntimeError('teardown failed')
        with self.assertRaisesRegex(RuntimeError, 'teardown failed'):
            module.run_with_evidence(Runner(), ['a'], payload)
        self.assertFalse(payload['passed'])

    def test_complete_execution_checks_runner_exit_and_actual_results(self):
        for code, failures, skipped, accepted in ((0, [], [], True), (1, [], [], False),
                (0, [('a', 'failure')], [], False), (0, [], [('a', 'skip')], False)):
            payload = {'selected':['a'], 'executed':['a'], 'failures':failures, 'errors':[],
                       'skipped':skipped, 'unexpected_successes':[], 'passed':False}
            class Runner:
                def run_tests(self, labels): return code
            module.run_with_evidence(Runner(), ['a'], payload)
            self.assertEqual(payload['passed'], accepted)


class EvidenceContractTests(unittest.TestCase):
    def test_aggregator_rejects_missing_wrong_sha_skip_failure_and_duplicates(self):
        import copy
        import hashlib
        import json
        from tempfile import TemporaryDirectory
        import unittest.mock
        spec = importlib.util.spec_from_file_location('verify', PATH.parent / 'verify_bounded_stable_evidence.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        batches = json.loads((verifier.PLAN / 'regression_batches.json').read_text())['batches']
        inventory = verifier.PLAN / 'failure_inventory.json'
        sha = 'a' * 40
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for batch, manifest in batches.items():
                folder = root / f'bounded-{batch}'
                folder.mkdir()
                payload = dict(sha=sha, batch=batch, inventory_sha256=hashlib.sha256(inventory.read_bytes()).hexdigest(),
                               diff_sha256=hashlib.sha256(b'').hexdigest(), passed=True,
                               tests_run=len(manifest['expected_ids']), selected=manifest['expected_ids'],
                               executed=manifest['expected_ids'], failures=[], errors=[], skipped=[], unexpected_successes=[])
                (folder / 'result.json').write_text(json.dumps(payload))
            self.assertEqual(verifier.verify(root, sha)['fixed_failure_ids'], 50)
            path = root / 'bounded-1/result.json'
            original = json.loads(path.read_text())
            for key, value in [('sha', 'b' * 40), ('skipped', [['a', 'reason']]), ('errors', [['a','error']]),
                               ('failures', [['a','failure']]), ('executed', original['executed'][:-1]),
                               ('executed', original['executed'] + original['executed'][:1]), ('passed', False)]:
                with self.subTest(key=key):
                    changed = copy.deepcopy(original)
                    changed[key] = value
                    path.write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):
                        verifier.verify(root, sha)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                verifier.verify(root, sha)


if __name__ == '__main__':
    unittest.main()
