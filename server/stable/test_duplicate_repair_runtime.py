"""本地演练执行边界与计划完整性测试；不访问Docker或数据库。"""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from stable.test_duplicate_repair_rehearsal import fixture

spec = importlib.util.spec_from_file_location('duplicate_runtime_test', Path(__file__).resolve().parents[2] / 'deploy/rehearse_duplicate_repair.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeGuardTests(unittest.TestCase):
    def test_non_rehearsal_container_rejected_before_access(self):
        with self.assertRaisesRegex(ValueError, 'isolated repair name'):
            runtime.LocalCopy('production-db', Path('/tmp'))

    def test_container_with_network_or_bind_mount_rejected(self):
        base = dict(HostConfig=dict(NetworkMode='none', PortBindings={}), Mounts=[],
                    Config=dict(Labels={'io.umanews.rehearsal': runtime.LABEL}),
                    State=dict(Running=True), Id='test', Image='test')
        for change in ['network', 'mount', 'label', 'stopped', 'port']:
            obj = copy.deepcopy(base)
            if change == 'network': obj['HostConfig']['NetworkMode'] = 'bridge'
            if change == 'mount': obj['Mounts'] = [{'Type': 'bind'}]
            if change == 'label': obj['Config']['Labels'] = {}
            if change == 'stopped': obj['State']['Running'] = False
            if change == 'port': obj['HostConfig']['PortBindings'] = {'5432/tcp': [{}]}
            instance = object.__new__(runtime.LocalCopy); instance.name = 'test'
            with patch.object(instance, 'run', return_value=json.dumps([obj])):
                with self.subTest(change=change), self.assertRaises(ValueError): instance.verify()

    def test_unreviewed_catalog_image_rejected(self):
        instance = object.__new__(runtime.LocalCopy)
        with patch.object(instance, 'run', return_value=json.dumps([{'Config': {'Labels': {}}}])) as call:
            with self.assertRaisesRegex(ValueError, 'reviewed candidate'):
                instance.reviewed_schema('unreviewed')
        call.assert_called_once()

    def test_foreign_key_checks_complete_before_ddl(self):
        before = fixture(); plan = runtime.build_plan(before, {10}, {20})
        plan.update(before=before, scopes={t: 'true' for t in before})
        sql = runtime.make_sql(plan, 'a' * 64)
        self.assertLess(sql.index('SET CONSTRAINTS ALL IMMEDIATE'), sql.index('ALTER TABLE'))
        self.assertLess(sql.index('LOCK TABLE'), sql.index('DELETE FROM'))

    def test_modified_after_image_rejected(self):
        before = fixture(); plan = runtime.build_plan(before, {10}, {20})
        plan.update(before=before, observed_at=None)
        plan = json.loads(json.dumps(plan))
        with patch.object(runtime, 'KEEP_NEWS', {10}), patch.object(runtime, 'build_plan', wraps=runtime.build_plan) as build:
            # Use the fixture's rejected anchor while retaining the production validator's fixed policy.
            result = runtime.build_plan(before, {10}, {20})
            build.side_effect = None; build.return_value = result
            plan['after']['stable_newsarticle'][0]['body_zh'] = 'tampered'
            with self.assertRaisesRegex(ValueError, 'plan derivation differs: after'):
                runtime.validate_plan(plan)


if __name__ == '__main__': unittest.main()
