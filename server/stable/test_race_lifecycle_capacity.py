"""来源缺口和全部追踪库存容量，合成额度不等于真实来源证明。"""
from django.test import SimpleTestCase
from stable.services import race_lifecycle_projection as service


class LifecycleCapacityTests(SimpleTestCase):
    def test_missing_sources_remain_in_region_denominator(self):
        report_fn = getattr(service, "source_capacity_report", None)
        self.assertTrue(callable(report_fn), "缺少逐区能力/容量报告")
        report = report_fn(targets=[{"key": "missing:jp", "region": "japan_jra", "key_race": True}], proofs=[], budgets={})
        self.assertEqual(report["targets"], 1)
        self.assertEqual(report["ready"], 0)
        self.assertIn("missing:jp", report["gaps"])

    def test_capacity_counts_all_tracked_races_and_reserves_thirty_percent(self):
        report_fn = getattr(service, "source_capacity_report", None)
        self.assertTrue(callable(report_fn), "缺少全部追踪库存容量检查")
        targets = [{"key": str(i), "region": "japan_jra", "key_race": True} for i in range(10)]
        proof = {"region": "japan_jra", "host": "sample.invalid", "provider": "fixture", "evidence_refs": ["synthetic:fixture"],
                 "identity": True, "confirmed_card": True, "complete_result": True, "correction": True,
                 "discovery": "full", "requests_per_fetch": 2, "runtime_verified": False}
        report = report_fn(targets=targets, proofs=[proof], budgets={"sample.invalid": 1000})
        self.assertGreater(report["hosts"]["sample.invalid"]["required_per_hour"], 1200)
        self.assertFalse(report["hosts"]["sample.invalid"]["capacity_ok"])
        self.assertEqual(report["ready"], 0)

    def test_capacity_proof_must_match_actual_selected_source(self):
        from types import SimpleNamespace
        function = getattr(service, 'capacity_allows_source', None)
        self.assertTrue(callable(function), '容量证明尚未绑定实际请求来源')
        event = SimpleNamespace(pk=1, normalized_grade='G1', source_refs={})
        source = SimpleNamespace(source_key='jra', region_code='japan_jra', canonical_url='https://www.jra.go.jp/JRADB/accessS.html')
        manifest = dict(targets=[dict(key='canonical:1', region='japan_jra', key_race=True)],
            proofs=[dict(region='japan_jra', provider='other', host='other.invalid', runtime_verified=True, identity=True, confirmed_card=True, complete_result=True, correction=True, evidence_refs=['synthetic'], discovery='full', requests_per_fetch=2)], budgets={'www.jra.go.jp': 1000, 'other.invalid':1000})
        self.assertFalse(function(manifest, event=event, source=source))
        manifest['proofs'][0].update(provider='jra', host='www.jra.go.jp')
        self.assertTrue(function(manifest, event=event, source=source))
        manifest['targets'][0]['key_race'] = False
        self.assertFalse(function(manifest, event=event, source=source))
