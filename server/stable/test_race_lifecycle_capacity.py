"""来源缺口和全部追踪库存容量，合成额度不等于真实来源证明。"""
from django.test import SimpleTestCase
from stable.services import race_lifecycle_projection as service


def synthetic_capacity(*, targets=None, proofs=None, budgets=None):
    """仅为隔离回放提供显式合成证明，不用于生产manifest。"""
    from copy import deepcopy
    targets = deepcopy(targets if targets is not None else [
        dict(key='canonical:1', region='japan_jra', key_race=True)])
    proofs = deepcopy(proofs if proofs is not None else [
        dict(region='japan_jra', provider='jra', host='www.jra.go.jp',
             requests_per_fetch=3)])
    for proof in proofs:
        for name in ('identity', 'confirmed_card', 'complete_result', 'correction',
                     'schedule', 'withdrawal', 'automated_use_permitted',
                     'request_costs_verified', 'quota_verified', 'runtime_verified'):
            proof.setdefault(name, True)
        for name in ('evidence_refs', 'cost_evidence_refs', 'use_evidence_refs', 'quota_evidence_refs'):
            proof.setdefault(name, ['synthetic:offline-only'])
        proof.setdefault('discovery', 'full')
        proof.setdefault('target_keys', [t['key'] for t in targets if t['region'] == proof['region']])
        proof.setdefault('extra_requests_per_hour', 0)
    return dict(targets=targets, proofs=proofs,
        budgets=deepcopy(budgets if budgets is not None else {'www.jra.go.jp': 1000}),
        inventory=dict(verified=True, evidence_refs=['synthetic:offline-only'],
            target_keys=[t['key'] for t in targets],
            other_requests_per_hour={p['host']: 0 for p in proofs}))


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
        report = report_fn(**synthetic_capacity(targets=targets, proofs=[proof], budgets={"sample.invalid": 1000}))
        self.assertGreater(report["hosts"]["sample.invalid"]["required_per_hour"], 1200)
        self.assertFalse(report["hosts"]["sample.invalid"]["capacity_ok"])
        self.assertEqual(report["ready"], 0)

    def test_capacity_proof_must_match_actual_selected_source(self):
        from types import SimpleNamespace
        function = getattr(service, 'capacity_allows_source', None)
        self.assertTrue(callable(function), '容量证明尚未绑定实际请求来源')
        event = SimpleNamespace(pk=1, normalized_grade='G1', source_refs={})
        source = SimpleNamespace(source_key='jra', region_code='japan_jra', canonical_url='https://www.jra.go.jp/JRADB/accessS.html')
        manifest = synthetic_capacity(targets=[dict(key='canonical:1', region='japan_jra', key_race=True)],
            proofs=[dict(region='japan_jra', provider='other', host='other.invalid', runtime_verified=True, identity=True, confirmed_card=True, complete_result=True, correction=True, evidence_refs=['synthetic'], discovery='full', requests_per_fetch=2)], budgets={'www.jra.go.jp': 1000, 'other.invalid':1000})
        self.assertFalse(function(manifest, event=event, source=source))
        manifest['proofs'][0].update(provider='jra', host='www.jra.go.jp')
        manifest['inventory']['other_requests_per_hour']['www.jra.go.jp'] = 0
        self.assertTrue(function(manifest, event=event, source=source))
        manifest['targets'][0]['key_race'] = False
        self.assertFalse(function(manifest, event=event, source=source))

    def test_old_275_quota_rejects_six_rechecks_but_283_accepts(self):
        manifest = synthetic_capacity(budgets={'www.jra.go.jp': 275})
        report = service.source_capacity_report(**manifest)
        self.assertEqual(report['hosts']['www.jra.go.jp']['base_per_hour'], 198)
        self.assertEqual(report['hosts']['www.jra.go.jp']['required_per_hour'], 283)
        self.assertEqual(report['ready'], 0)
        manifest['budgets']['www.jra.go.jp'] = 283
        self.assertEqual(service.source_capacity_report(**manifest)['ready'], 1)

    def test_legacy_numeric_estimate_is_not_four_rechecks(self):
        manifest = synthetic_capacity()
        manifest.pop('inventory')
        report = service.source_capacity_report(**manifest)
        self.assertEqual(report['hosts']['www.jra.go.jp']['base_per_hour'], 198)

    def test_shared_host_adds_targets_backups_retries_and_other_consumers(self):
        manifest = synthetic_capacity(
            targets=[dict(key='canonical:1', region='japan_jra', key_race=True),
                     dict(key='canonical:2', region='japan_jra', key_race=False)],
            proofs=[dict(region='japan_jra',provider=p,host='www.jra.go.jp',
                         requests_per_fetch=2,extra_requests_per_hour=7) for p in ('jra','backup')],
            budgets={'www.jra.go.jp': 700})
        manifest['inventory']['other_requests_per_hour']['www.jra.go.jp'] = 21
        report = service.source_capacity_report(**manifest)
        self.assertEqual(report['hosts']['www.jra.go.jp']['base_per_hour'], 457)
        self.assertEqual(report['hosts']['www.jra.go.jp']['required_per_hour'], 653)
        self.assertEqual(report['ready'], 2)

    def test_missing_inventory_or_target_omission_cannot_be_ready(self):
        for change in ('missing', 'unverified', 'omitted', 'extra', 'duplicate', 'evidence'):
            with self.subTest(change=change):
                manifest = synthetic_capacity()
                if change == 'missing': manifest.pop('inventory')
                elif change == 'unverified': manifest['inventory']['verified'] = False
                elif change == 'omitted': manifest['inventory']['target_keys'] = []
                elif change == 'extra': manifest['inventory']['target_keys'].append('unmatched:pending')
                elif change == 'duplicate': manifest['inventory']['target_keys'] *= 2
                else: manifest['inventory']['evidence_refs'] = []
                self.assertEqual(service.source_capacity_report(**manifest)['ready'], 0)

    def test_unproven_permissions_costs_quota_or_capability_block(self):
        for name in ('schedule','withdrawal','automated_use_permitted','request_costs_verified',
                     'quota_verified','runtime_verified','cost_evidence_refs','use_evidence_refs',
                     'quota_evidence_refs','target_keys','extra_requests_per_hour'):
            with self.subTest(name=name):
                manifest = synthetic_capacity()
                manifest['proofs'][0].pop(name)
                self.assertEqual(service.source_capacity_report(**manifest)['ready'], 0)

    def test_other_host_load_missing_is_not_zero(self):
        manifest = synthetic_capacity()
        manifest['inventory']['other_requests_per_hour'] = {}
        self.assertEqual(service.source_capacity_report(**manifest)['ready'], 0)

    def test_unmatched_target_stays_in_denominator(self):
        manifest = synthetic_capacity()
        manifest['targets'].append(dict(key='unmatched:60871',region='united_kingdom',key_race=False))
        manifest['inventory']['target_keys'].append('unmatched:60871')
        report = service.source_capacity_report(**manifest)
        self.assertEqual(report['targets'], 2)
        self.assertIn('unmatched:60871', report['gaps'])

    def test_current_provider_cannot_borrow_a_valid_proof(self):
        from types import SimpleNamespace
        manifest = synthetic_capacity()
        invalid = dict(manifest['proofs'][0],provider='bad',confirmed_card=False)
        manifest['proofs'].append(invalid)
        source = SimpleNamespace(source_key='bad',region_code='japan_jra',canonical_url='https://www.jra.go.jp/card')
        event = SimpleNamespace(pk=1,normalized_grade='G1',source_refs={})
        self.assertFalse(service.capacity_allows_source(manifest,event=event,source=source))
        manifest['proofs'][1]['confirmed_card'] = True
        manifest['proofs'][1]['target_keys'] = ['canonical:2']
        self.assertFalse(service.capacity_allows_source(manifest,event=event,source=source))

    def test_current_source_rejects_when_another_target_is_blocked(self):
        from types import SimpleNamespace
        manifest = synthetic_capacity()
        manifest['targets'].append(dict(key='unmatched:60871',region='united_kingdom',key_race=False))
        manifest['inventory']['target_keys'].append('unmatched:60871')
        source = SimpleNamespace(source_key='jra',region_code='japan_jra',canonical_url='https://www.jra.go.jp/card')
        event = SimpleNamespace(pk=1,normalized_grade='G1',source_refs={})
        self.assertFalse(service.capacity_allows_source(manifest,event=event,source=source))

    def test_wrong_numeric_types_and_unknown_priority_reject(self):
        for value in (True,-1,1.5,'1'):
            with self.subTest(value=value):
                manifest=synthetic_capacity()
                manifest['proofs'][0]['extra_requests_per_hour']=value
                with self.assertRaises(ValueError):service.source_capacity_report(**manifest)
        manifest=synthetic_capacity()
        manifest['targets'][0]['key_race']=None
        with self.assertRaises(ValueError):service.source_capacity_report(**manifest)

    def test_missing_event_grade_cannot_use_regular_budget(self):
        from types import SimpleNamespace
        manifest=synthetic_capacity()
        manifest['targets'][0]['key_race']=False
        event=SimpleNamespace(pk=1,normalized_grade='',source_refs={})
        source=SimpleNamespace(source_key='jra',region_code='japan_jra',canonical_url='https://www.jra.go.jp/card')
        self.assertFalse(service.capacity_allows_source(manifest,event=event,source=source))
        manifest['targets'][0]['key_race']=True
        self.assertTrue(service.capacity_allows_source(manifest,event=event,source=source))

    def test_file_manifest_preserves_inventory_and_rejects_old_shape(self):
        import hashlib,json,tempfile
        from pathlib import Path
        from datetime import datetime,timezone,timedelta
        from django.test import override_settings
        now=datetime(2026,10,29,tzinfo=timezone.utc)
        manifest=synthetic_capacity()
        manifest.update(valid_from=now.isoformat(),valid_until=(now+timedelta(hours=1)).isoformat())
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'capacity.json'
            for complete in (True,False):
                if not complete:manifest.pop('inventory')
                raw=json.dumps(manifest).encode();p.write_bytes(raw)
                with override_settings(RACE_LIFECYCLE_CAPACITY_FILE=str(p),RACE_LIFECYCLE_CAPACITY_SHA256=hashlib.sha256(raw).hexdigest(),RACE_LIFECYCLE_V2_EVENT_IDS=(1,)):
                    if complete:self.assertEqual(service.capacity_manifest(now=now)['inventory'],manifest['inventory'])
                    else:
                        with self.assertRaisesMessage(ValueError,'capacity_not_ready'):service.capacity_manifest(now=now)
                from io import StringIO
                from django.core.management import call_command
                output=StringIO()
                call_command('report_race_lifecycle_capacity',manifest=str(p),sha256=hashlib.sha256(raw).hexdigest(),stdout=output)
                self.assertEqual(json.loads(output.getvalue())['ready'],int(complete))
