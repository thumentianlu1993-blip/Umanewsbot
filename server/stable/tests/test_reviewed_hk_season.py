"""固定香港2026/27导入：离线源、跨年、公网和事务回归。"""
import copy
import importlib.util
import json
from datetime import date, time
from pathlib import Path
from django.test import TestCase, override_settings
from django.db import connection
from stable import models as m

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('hk_season', ROOT / 'scripts/import_reviewed_hk_season.py')
hk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hk)
FIXTURES = Path(__file__).parent / 'fixtures/hk_season_2627'


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class HKSeasonTests(TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'docs/changes/import-hk-season-20260918/manifest.json').read_text())
        for source in self.manifest['sources'].values():
            source['sha256'] = hk.bytes_sha(FIXTURES / source['file'])
        for row in self.manifest['events']:
            s = row['series']
            if s['id']:
                m.RaceSeries.objects.create(id=s['id'], key=s['key'], country_region='hong_kong',
                    canonical_name_original=s['canonical_name_original'], chinese_name=s['chinese_name'])
        row = self.manifest['events'][9]
        self.existing = m.RaceEvent.objects.create(id=2, year=2026, edition_year=2026,
            slug='preserve-hong-kong-cup', race_series_id=5980, original_name='Existing cup',
            chinese_name='香港杯', country_region='hong_kong', racecourse='Sha Tin',
            grade_text='G1', normalized_grade='G1', surface='turf', local_date=date.fromisoformat(row['date']),
            local_start_time=time(16, 40), visibility_status='published', notes='must preserve')
        with connection.cursor() as cursor:
            cursor.execute("SELECT setval(pg_get_serial_sequence('stable_raceevent', 'id'), 100)")
        self.before = hk.event_snapshot(2)
        self.manifest['existing_sha256'] = hk.digest(self.before)

    def run_batch(self, apply=False, manifest=None, fault_hook=None):
        manifest = manifest or self.manifest
        return hk.run(manifest, FIXTURES, expected_sha=hk.digest(manifest), apply=apply,
                      today='2026-09-18', fault_hook=fault_hook)

    def test_dates_and_dry_run_have_no_writes(self):
        result = self.run_batch()
        self.assertEqual(result['create_count'], 34)
        self.assertEqual(m.RaceEvent.objects.count(), 1)
        self.assertEqual(m.RaceSeries.objects.count(), 34)
        self.assertFalse(m.OperationLog.objects.filter(action_type=hk.ACTION).exists())
        rows = hk.validate(self.manifest, FIXTURES, '2026-09-18')
        self.assertEqual(rows[0]['local_date'].isoformat(), '2026-09-06')
        self.assertEqual(rows[13]['year'], 2027)
        self.assertIsNone(rows[13]['race_datetime'])
        self.assertEqual(rows[18]['normalized_grade'], 'OTHER')
        self.assertEqual(rows[18]['grade_text'], '4YO')
        self.assertEqual(rows[15]['racecourse'], 'Happy Valley')
        self.assertTrue(all(x['timezone_name'] == 'Asia/Hong_Kong' for x in rows))

    def test_apply_complete_and_replay_preserves_existing(self):
        result = self.run_batch(apply=True)
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(m.RaceEvent.objects.count(), 35)
        self.assertEqual(m.RaceEvent.objects.filter(year=2026).count(), 13)
        self.assertEqual(m.RaceEvent.objects.filter(year=2027).count(), 22)
        self.assertEqual(hk.event_snapshot(2), self.before)
        event = m.RaceEvent.objects.get(series_key='hong-kong-hksar-chief-executives-cup')
        self.assertEqual(event.status, 'finished')
        self.assertEqual(str(event.local_start_time), '13:30:00')
        self.assertEqual(event.results.filter(is_confirmed=True).count(), 6)
        self.assertEqual(event.runners.count(), 6)
        self.assertEqual(event.results.get(finish_position=1).horse_name, '嘉应高升')
        self.assertIsNotNone(event.result_confirmed_at)
        self.assertEqual(self.run_batch(apply=True)['status'], 'already_applied')
        self.assertEqual(m.RaceEvent.objects.count(), 35)
        response = self.client.get(event.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '嘉应高升')
        self.assertContains(response, '已完赛')
        self.assertContains(response, 'state-finished')
        self.assertEqual(len(response.context['results']), 6)
        future = m.RaceEvent.objects.get(series_key='hong-kong-hong-kong-classic-mile')
        self.assertContains(self.client.get(future.get_absolute_url()), '开赛时间待补')

    def test_full_transaction_rollback(self):
        def fail(**kwargs):
            if kwargs['index'] == 5:
                raise RuntimeError('injected')
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.run_batch(apply=True, fault_hook=fail)
        self.assertEqual(m.RaceEvent.objects.count(), 1)
        self.assertEqual(m.RaceEventResult.objects.count(), 0)
        self.assertFalse(m.RaceSeries.objects.filter(key=self.manifest['events'][0]['series']['key']).exists())
        self.assertFalse(m.OperationLog.objects.filter(action_type=hk.ACTION).exists())

    def test_existing_and_series_drift_rejected(self):
        m.RaceEvent.objects.filter(pk=2).update(notes='changed')
        with self.assertRaises(ValueError): self.run_batch(apply=True)
        self.assertEqual(m.RaceEvent.objects.count(), 1)
        self.manifest['existing_sha256'] = hk.digest(hk.event_snapshot(2))
        m.RaceSeries.objects.filter(pk=5964).update(key='unexpected')
        with self.assertRaises(ValueError): self.run_batch(apply=True)

    def test_duplicate_on_another_series_rejected(self):
        row = self.manifest['events'][1]
        m.RaceEvent.objects.create(year=2026, slug='other-duplicate', original_name=row['name_en'],
            chinese_name=row['name_zh'], country_region='hong_kong', racecourse='Sha Tin',
            grade_text='G3', surface='turf', local_date=date.fromisoformat(row['date']))
        with self.assertRaises(ValueError): self.run_batch(apply=True)
        self.assertEqual(m.RaceEvent.objects.count(), 2)

    def test_replay_drift_rejected(self):
        self.run_batch(apply=True)
        m.RaceEventResult.objects.filter(finish_position=1).update(horse_name='wrong')
        with self.assertRaises(ValueError): self.run_batch(apply=True)

    def test_invalid_source_scope_result_and_time_rejected(self):
        changes = [
            lambda x: x['events'].pop(),
            lambda x: x['sources']['en'].update(sha256='0'*64),
            lambda x: x['events'][0].update(date='2026-09-05'),
            lambda x: x['events'][1].update(name_zh_hant='wrong'),
            lambda x: x['events'][18].update(grade='G1'),
            lambda x: x['results'].pop(),
            lambda x: x['results'][0].update(horse_code='X000'),
            lambda x: x.update(completed_start='2026-09-06T00:00:00+08:00'),
        ]
        for change in changes:
            manifest = copy.deepcopy(self.manifest); change(manifest)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_batch(apply=True, manifest=manifest)
        self.assertEqual(m.RaceEvent.objects.count(), 1)
        with self.assertRaises(ValueError):
            hk.validate(self.manifest, FIXTURES, '2026-09-28')

    def test_wrong_manifest_digest_rejected(self):
        with self.assertRaises(ValueError):
            hk.run(self.manifest, FIXTURES, expected_sha='0'*64, apply=True, today='2026-09-18')

    def test_maintenance_gate_blocks_without_partial_rows(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from stable.services.historical_race_calendar_admission import HistoricalCalendarWriteBlocked
        actor = get_user_model().objects.create(username='hk-test-maintenance')
        m.HistoricalRaceCalendarMaintenanceGate.objects.create(manifest_sha256='a'*64,
            action_scope_sha256='b'*64, actor=actor, entered_at=timezone.now())
        with self.assertRaises(HistoricalCalendarWriteBlocked): self.run_batch(apply=True)
        self.assertEqual(m.RaceEvent.objects.count(), 1)


from django.test import SimpleTestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory


class HKProductionWindowTests(SimpleTestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('hk_host', ROOT / 'scripts/run_reviewed_hk_season.py')
        self.host = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.host)

    def test_uncertain_apply_retains_exclusion_lock(self):
        with TemporaryDirectory() as tmp, patch.object(self.host, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'docker connection lost'):
                with self.host.held_deployment_lock('lock', {}, Path(tmp)) as state:
                    state['uncertain'] = True
                    raise RuntimeError('docker connection lost')
            self.assertEqual([c.args[0] for c in command.call_args_list], [['lock', 'acquire']])
            self.assertTrue((Path(tmp) / 'operation-uncertain.json').exists())

    def test_pre_apply_failure_and_confirmed_completion_release_lock(self):
        for started in [False, True]:
            with TemporaryDirectory() as tmp, patch.object(self.host, 'run') as command:
                try:
                    with self.host.held_deployment_lock('lock', {}, Path(tmp)) as state:
                        if not started: raise RuntimeError('preflight failed')
                        state['uncertain'] = True
                        state['uncertain'] = False
                except RuntimeError: pass
                self.assertEqual([c.args[0] for c in command.call_args_list], [['lock', 'acquire'], ['lock', 'release']])

    def test_healthcheck_unhealthy_and_starting_rejected(self):
        for health in ['unhealthy', 'starting']:
            with self.assertRaises(RuntimeError):
                self.host.require_healthy([{'State': {'Running': True, 'OOMKilled': False, 'Health': {'Status': health}}}])
        self.host.require_healthy([{'State': {'Running': True, 'OOMKilled': False}},
            {'State': {'Running': True, 'OOMKilled': False, 'Health': {'Status': 'healthy'}}}])
