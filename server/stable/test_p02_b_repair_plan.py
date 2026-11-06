"""B库修复计划绑定：合成输入，不连接数据库。"""
import copy
import json
import unittest
from stable.test_duplicate_repair_rehearsal import fixture
from stable.services.p02_b_repair_plan import prepare, verify


def inputs():
    return dict(before=fixture(), news_keep_ids=[10], rejected_keep_ids=[20],
                source_identity={'system_identifier': '123', 'database_oid': '100', 'database': 'horse_news'},
                target_identity={'system_identifier': '123', 'database_oid': '101', 'database': 'horse_news_p02_b'},
                backup_sha256='a'*64, candidate_commit='b'*40,
                catalog_sha256='c'*64, foreign_keys_sha256='d'*64,
                observed_at='2026-11-06T07:00:00+00:00')


class BoundRepairPlanTests(unittest.TestCase):
    def test_roundtrip_is_pure_and_reproducible(self):
        args=inputs(); before=copy.deepcopy(args); plan=prepare(**args)
        self.assertEqual(args,before)
        self.assertEqual(plan,prepare(**args))
        verify(json.loads(json.dumps(plan)),expected_sha256=plan['sha256'])
        self.assertEqual(plan['state'],'prepared_not_authorized')

    def test_rejects_a_as_target_even_with_alias(self):
        for field in ('database','database_oid'):
            args=inputs(); args['target_identity'][field]=args['source_identity'][field]
            with self.assertRaises(ValueError): prepare(**args)

    def test_rejects_invalid_bindings(self):
        for field,value in [('backup_sha256',''),('candidate_commit','main'),('observed_at','2026-11-06'),('foreign_keys_sha256','x'*64)]:
            args=inputs(); args[field]=value
            with self.assertRaises(ValueError): prepare(**args)

    def test_rejects_changed_envelope(self):
        plan=prepare(**inputs()); expected=plan['sha256']; plan['backup_sha256']='e'*64
        with self.assertRaises(ValueError): verify(plan,expected_sha256=expected)

    def test_rederives_plan_even_with_recomputed_digest(self):
        from stable.services.duplicate_repair_rehearsal import digest
        plan=prepare(**inputs()); plan['repair']['after']['stable_newsarticle'][0]['body_zh']='altered'
        plan['sha256']=digest({k:v for k,v in plan.items() if k!='sha256'})
        with self.assertRaises(ValueError): verify(plan,expected_sha256=plan['sha256'])
