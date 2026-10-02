"""交付不可仅凭同名绿色job或旧run的结果。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from scripts.verify_delivery_test_evidence import verify_jobs, verify_protection, compare_collection, verify_mode
from scripts.decide_full_regression import should_run


class DeliveryTests(unittest.TestCase):
    def jobs(self):
        return [{'id':1,'name':'tests','conclusion':'success','steps':[{'name':n,'conclusion':'success'} for n in
                 ['checkout-test-tree','static-contracts','generate-plan','execute-isolated-plan','verify-execution','upload-evidence']]},
                {'id':2,'name':'test-plan-gate','conclusion':'success','steps':[{'name':'require-complete-plan','conclusion':'success'}]}]

    def test_same_name_success_without_verification_is_rejected(self):
        jobs=self.jobs();jobs[0]['steps']=jobs[0]['steps'][:-2]
        with self.assertRaisesRegex(ValueError,'step'):verify_jobs(jobs)

    def test_cancelled_and_old_attempt_jobs_are_not_accepted(self):
        jobs=self.jobs();jobs[0]['conclusion']='cancelled'
        with self.assertRaises(ValueError):verify_jobs(jobs)
        with self.assertRaises(ValueError):verify_jobs(self.jobs()+self.jobs())

    def test_complete_steps_accepted(self):verify_jobs(self.jobs())

    def test_strict_and_admin_enforcement_required(self):
        valid={'required_status_checks':{'strict':True,'contexts':['test-plan-gate']},'enforce_admins':{'enabled':True}}
        verify_protection(valid)
        valid['enforce_admins']['enabled']=False
        with self.assertRaises(ValueError):verify_protection(valid)

    def test_bootstrap_requires_actual_prefixed_check_without_weakening_normal_pr(self):
        bootstrap='impact-validation / test-plan-gate'
        valid={'required_status_checks':{'strict':True,'contexts':[bootstrap]},'enforce_admins':{'enabled':True}}
        verify_protection(valid, bootstrap)
        with self.assertRaises(ValueError):verify_protection(valid)
        valid['required_status_checks']['contexts']=['test-plan-gate']
        with self.assertRaises(ValueError):verify_protection(valid, bootstrap)

    def test_nightly_failed_same_sha_retries_weekly_unchanged_runs(self):
        now=datetime.now(timezone.utc)
        latest={'tested_sha':'a','conclusion':'success','updated_at':now.isoformat()}
        self.assertFalse(should_run('a',latest,now))
        self.assertTrue(should_run('b',latest,now))
        latest['head_sha']='b'
        self.assertTrue(should_run('b',latest,now), 'workflow ref must not replace tested SHA')
        latest['conclusion']='failure';self.assertTrue(should_run('a',latest,now))
        latest['conclusion']='success';self.assertTrue(should_run('a',latest,now+timedelta(days=7)))


class CollectionEvidenceTests(unittest.TestCase):
    def test_empty_self_consistent_evidence_is_rejected(self):
        plan={'batches':[],'count':0}
        collected={'batches':[{'key':'batch-000','profile':'python','ids':['m.C.test_x']}],'count':1}
        with self.assertRaisesRegex(ValueError,'collection'):
            compare_collection(plan,collected)


class ScopeEvidenceTests(unittest.TestCase):
    def test_targeted_cannot_claim_documentation_to_skip_collection(self):
        with self.assertRaisesRegex(ValueError,'mode'):
            verify_mode('targeted','docs-only')


class BootstrapTests(unittest.TestCase):
    def test_manual_calibration_cannot_substitute_pr_delivery(self):
        from scripts.verify_delivery_test_evidence import authorize_run
        run={'event':'workflow_dispatch','path':'.github/workflows/release_0078_contract.yml'}
        plan={'bootstrap':True,'head_sha':'head','test_sha':'head'};review={'commit':'head'}
        with self.assertRaisesRegex(ValueError,'pull_request'):
            authorize_run(run,plan,review,False,'head','merge')
        for has_catalog,approval in [(True,review),(False,None),(False,{'commit':'other'})]:
            with self.assertRaises(ValueError):authorize_run(run,plan,approval,has_catalog,'head','merge')

    def test_ordinary_pr_still_requires_exact_merge_identity(self):
        from scripts.verify_delivery_test_evidence import authorize_run
        for has_catalog in (False, True):
            self.assertEqual(authorize_run(
                {'event':'pull_request','path':'.github/workflows/affected_tests.yml'},
                {'test_sha':'merge'}, {'commit':'head'}, has_catalog, 'head', 'merge'), '')
        with self.assertRaises(ValueError):
            authorize_run({'event':'pull_request','path':'.github/workflows/affected_tests.yml'},
                          {'test_sha':'head'},None,True,'head','merge')


class WorkflowIdentityTests(unittest.TestCase):
    def test_all_pr_source_bindings_use_event_merge_not_cached_payload(self):
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/affected_tests.yml'
        bindings = re.findall(r'^\s*(?:ref|TEST_SHA): \$\{\{ (.+) \}\}$', workflow.read_text().split('      - name: collect-catalog-without-running', 1)[0], re.M)
        self.assertEqual(len(bindings), 3)  # checkout、静态检查、计划必须绑定同一个事件。
        for event, cached_merge, expected in (
            ('pull_request', 'stale-merge-for-previous-head', 'current-event-merge'),
            ('pull_request', None, 'current-event-merge'),
            ('pull_request', 'current-event-merge', 'current-event-merge'),
            ('workflow_dispatch', None, 'explicit-candidate'),
            ('schedule', None, 'explicit-candidate'),
        ):
            context = {
                'github': SimpleNamespace(event_name=event, sha='current-event-merge',
                    event=SimpleNamespace(pull_request=SimpleNamespace(merge_commit_sha=cached_merge))),
                'inputs': SimpleNamespace(candidate_sha='explicit-candidate'),
            }
            for expression in bindings:
                with self.subTest(event=event, cached_merge=cached_merge, expression=expression):
                    actual = eval(expression.replace('&&', 'and').replace('||', 'or'), {'__builtins__': {}}, context)
                    self.assertEqual(actual, expected)
