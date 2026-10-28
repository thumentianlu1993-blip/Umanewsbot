"""严格 R01 报告从持久 receipt 回读，缺口不可抹除。"""
from django.test import TestCase
from stable import models
from stable.services import race_lifecycle_projection as projection
from stable import test_race_timeliness_contracts as fixture


class LifecycleMetricsTests(TestCase):
    def test_report_survives_restart_and_duplicate_import(self):
        from importlib import import_module
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('stable.services.race_lifecycle_metrics'), '缺少持久 R01 adapter')
        service = import_module('stable.services.race_lifecycle_metrics')
        value = fixture.report()
        fixture.audit(value, 0, errors=['identity'])
        expected = dict(expected_scope_sha256=fixture.digest(value['scope']), expected_candidate_sha256=fixture.CANDIDATE,
                        expected_coverage_sha256=fixture.digest(value['coverage']))
        receipt = service.persist_report(value, **expected)
        service.persist_report(value, **expected)
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='report').count(), 1)
        self.assertEqual(service.read_report(receipt.idempotency_key), fixture.core.summarize(fixture.parse(value)))

    def test_missing_source_and_unknown_audit_do_not_become_success(self):
        from importlib import import_module
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('stable.services.race_lifecycle_metrics'), '缺少持久 R01 adapter')
        service = import_module('stable.services.race_lifecycle_metrics')
        value = fixture.report()
        expected = dict(expected_scope_sha256=fixture.digest(value['scope']), expected_candidate_sha256=fixture.CANDIDATE,
                        expected_coverage_sha256=fixture.digest(value['coverage']))
        receipt = service.persist_report(value, **expected)
        report = service.read_report(receipt.idempotency_key)
        self.assertEqual(report, fixture.core.summarize(fixture.parse(value)))
        self.assertIn('unknown', str(report).lower())

    def test_missing_canonical_target_keeps_deadline_in_denominator(self):
        from stable.services import race_lifecycle_metrics as service
        from stable.services.race_data_source_adapters import aware, canonical_sha
        from stable.services.race_lifecycle_projection import record_due_deadlines
        value = fixture.report()
        manifest = dict(scope=value['scope'], window=value['window'], obligations=[dict(
            target_key='canonical:6', module='result', deadline_at=fixture.timestamp(60), evidence_refs=['synthetic:scope'])])
        register = getattr(service, 'register_scope', None)
        self.assertTrue(callable(register), '无 canonical 的缺源目标尚无持久义务')
        register(manifest, expected_sha256=canonical_sha(manifest), now=aware(fixture.START))
        self.assertEqual(record_due_deadlines(now=aware(fixture.timestamp(59))), 0)
        self.assertEqual(record_due_deadlines(now=aware(fixture.timestamp(60))), 1)
        self.assertEqual(record_due_deadlines(now=aware(fixture.timestamp(61))), 0)
        report = service.assemble_report(scope=value['scope'], window=value['window'], as_of=aware(fixture.END))
        counts = service.business_counts(report)
        self.assertEqual((counts['N'], counts['L']), (10, 1))
        self.assertFalse(counts['accepted'])
