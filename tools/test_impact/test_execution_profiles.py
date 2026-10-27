"""专用环境的精确准入；不以模拟证据替代真实 native 执行。"""
import copy
import json
import unittest
from pathlib import Path
from tools.test_impact import execution_profiles as profiles
from tools.test_impact import pg_lifecycle as pg
from tools.test_impact.test_pg_lifecycle import plan_fixture


class ExecutionProfileTests(unittest.TestCase):
    def test_root_receipt_requires_numeric_root_uid_and_gid(self):
        from tools.test_impact.test_pg_lifecycle import synthetic_receipt
        plan = plan_fixture()
        plan['batches'][0].update(profile=profiles.ROOT_PROFILE,ids=[profiles.ROOT_ID])
        request = pg.make_request(plan,'run','batch-000',profiles.ROOT_PROFILE,'a'*32)
        raw = json.dumps({'exit_code':0}).encode()
        receipt = synthetic_receipt(request,raw)
        receipt.update(uid=0,gid=0)
        pg.validate_receipt(receipt,request,raw)
        for uid,gid in ((False,False),(0,False),(10001,10001)):
            bad = {**receipt,'uid':uid,'gid':gid}
            with self.subTest(uid=uid,gid=gid), self.assertRaises(ValueError):
                pg.validate_receipt(bad,request,raw)

    def test_all_original_exact_resource_apis_remain_callable(self):
        from tools.test_impact.fixture_inputs import fixture_environment
        source = Path(__file__).resolve().parents[2]
        for module in profiles.CACHE_PROFILES.values():
            ids = list(module.NATIVE_IDS)
            plan = dict(source='git', mode='targeted', test_sha='a'*40, test_tree='b'*40,
                        labels=ids, count=len(ids), batches=[dict(key='batch-000', profile='django', ids=ids)],
                        fixture_inputs=dict(id=module.RESOURCE_ID, manifest_sha256=module.MANIFEST_SHA256,
                                            source_sha='a'*40, source_tree='b'*40))
            with self.subTest(resource=module.RESOURCE_ID):
                env = fixture_environment(plan, plan, 'a'*40, 'django', source_root=source)
                self.assertTrue(env)
                self.assertTrue(all(Path(value).is_dir() for value in env.values()))

    def test_privilege_boundary_rejects_normal_root_extra_and_missing_caps(self):
        profiles.validate_privilege('django', 10001, 10001, 0)
        profiles.validate_privilege(profiles.ROOT_PROFILE, 0, 0, 0xe0)
        for args in (('django', 0, 0, 0xe0), ('django', 10001, 10001, 1),
                     (profiles.ROOT_PROFILE, 0, 0, 0), (profiles.ROOT_PROFILE, 0, 0, 0x1e0),
                     (profiles.ROOT_PROFILE, 0, 10001, 0xe0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                profiles.validate_privilege(*args)

    def test_exact_native_wins_module_and_sibling_stays_default(self):
        catalog = {'stable.test_race_live_gate_remediation': 'django',
                   profiles.ROOT_ID: profiles.ROOT_PROFILE}
        self.assertEqual(profiles.resolve_profile(profiles.ROOT_ID, catalog), profiles.ROOT_PROFILE)
        self.assertEqual(profiles.resolve_profile(profiles.ROOT_ID + '_other', catalog), 'django')

    def test_root_request_accepts_only_original_single_native(self):
        plan = plan_fixture()
        plan['batches'][0].update(profile=profiles.ROOT_PROFILE, ids=[profiles.ROOT_ID])
        self.assertEqual(pg.make_request(plan, 'run', 'batch-000', profiles.ROOT_PROFILE, 'a'*32)['profile'], profiles.ROOT_PROFILE)
        for ids in ([], [profiles.ROOT_ID, 'other.C.test_a'], ['other.C.test_a'], [profiles.ROOT_ID]*2):
            changed = copy.deepcopy(plan)
            changed['batches'][0]['ids'] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                pg.make_request(changed, 'run', 'batch-000', profiles.ROOT_PROFILE, 'a'*32)

    def test_cache_groups_are_exact_disjoint_and_reject_mixed_ids(self):
        all_ids = []
        for profile, module in profiles.CACHE_PROFILES.items():
            ids = list(module.NATIVE_IDS)
            all_ids.extend(ids)
            profiles.validate_batch({'profile': profile, 'ids': ids})
            profiles.validate_batch({'profile': profile, 'ids': ids[:1]})
            for invalid in ([], ids*2, ids+['other.C.test_a']):
                with self.assertRaises(ValueError):
                    profiles.validate_batch({'profile': profile, 'ids': invalid})
        self.assertEqual(len(all_ids), 8)
        self.assertEqual(len(set(all_ids)), 8)
