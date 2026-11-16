"""已采集但未挂接的年度目录，以及误标取消的空表赛果修复。"""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date
from django.test import TestCase
from stable import models as m


class HistoricalTargetReconciliationTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'source.txt').write_text('Reviewed full result and event identity')
        self.series = m.RaceSeries.objects.create(key='tokyo-city', country_region='united_states', canonical_name_original='Tokyo City Cup')
        self.target = m.HistoricalRaceEventTarget.objects.create(race_series=self.series, year=2025, country_region='united_states',original_name='Tokyo City Cup',racecourse='Santa Anita Park')
        self.event = m.RaceEvent.objects.create(year=2025,slug='tokyo-city-2025',original_name='Tokyo City Cup',country_region='united_states',racecourse='Santa Anita Park',status='cancelled',visibility_status='draft')

    def manifest(self, action='recover_results'):
        from stable.services.historical_target_reconciliation import event_snapshot, target_snapshot, series_snapshot, row_snapshot
        runner = dict(horse_number='4',horse_name='Privman',sort_order=1,running_status='finished',source_refs={})
        result = dict(horse_number='4',horse_name='Privman',finish_position=1,official_finish_position=1,running_status='finished',is_confirmed=True,source_refs={})
        return dict(schema_version=1,action='reconcile_historical_targets',entries=[dict(
            target_id=self.target.pk,event_id=self.event.pk,action=action,
            target_before=target_snapshot(self.target),event_before=event_snapshot(self.event),series_before=series_snapshot(self.series),
            rows_before=row_snapshot(self.event.pk),reason='来源身份与年度核对完成',
            sources=[dict(path='source.txt',sha256=hashlib.sha256((self.root/'source.txt').read_bytes()).hexdigest(),url='https://www.sportinglife.com/racing/results/2025-10-25/santa-anita/886826/race-2-tokyo-city-cup-stakes')],
            event_patch=dict(local_date='2025-10-25',grade_text='无分级',normalized_grade='',timezone_name='America/Los_Angeles',distance_text='1m') if action=='recover_results' else {},
            source_patch={'primary':'https://www.sportinglife.com/racing/results/2025-10-25/santa-anita/886826/race-2-tokyo-city-cup-stakes'},
            runners=[runner] if action=='recover_results' else [],results=[result] if action=='recover_results' else [],
            expected_runners=1 if action=='recover_results' else self.event.runners.count(),
            nonstarters=[], expected_starters=1 if action=='recover_results' else self.event.results.count())])

    def execute(self, data, mode='dry-run'):
        from stable.services.historical_target_reconciliation import execute
        path=self.root/'manifest.json';raw=json.dumps(data).encode();path.write_bytes(raw)
        return execute(path,hashlib.sha256(raw).hexdigest(),mode=mode)

    def test_recover_dry_run_apply_replay_and_restore(self):
        data=self.manifest();self.execute(data)
        self.assertFalse(self.event.results.exists())
        self.execute(data,'apply');self.event.refresh_from_db();self.target.refresh_from_db()
        self.assertEqual(self.event.status,'finished');self.assertEqual(self.event.visibility_status,'published')
        self.assertEqual(self.target.event_id,self.event.pk);self.assertEqual(self.target.resolution_status,'imported')
        self.assertEqual(self.target.grade_text,'无分级');self.assertEqual(self.event.local_date,date(2025,10,25))
        self.assertTrue(self.execute(data,'apply')['replay'])
        self.execute(data,'restore');self.event.refresh_from_db();self.target.refresh_from_db()
        self.assertEqual(self.event.status,'cancelled');self.assertIsNone(self.target.event_id)
        self.assertFalse(self.event.results.exists());self.assertTrue(self.execute(data,'restore')['replay'])
        with self.assertRaisesRegex(ValueError,'restored'):self.execute(data,'apply')

    def test_attach_existing_rows_without_reinserting_or_overwriting(self):
        self.event.status='finished';self.event.visibility_status='published';self.event.local_date=date(2025,9,12);self.event.save()
        runner=m.RaceEventRunner.objects.create(event=self.event,horse_name='Existing')
        row=m.RaceEventResult.objects.create(event=self.event,horse_name='Existing',finish_position=1,official_finish_position=1)
        data=self.manifest('attach_results');self.execute(data,'apply')
        self.target.refresh_from_db();self.assertEqual(self.target.event_id,self.event.pk)
        self.assertEqual(list(self.event.results.values_list('id',flat=True)),[row.pk])
        self.execute(data,'restore');row.refresh_from_db();runner.refresh_from_db()

    def test_cancelled_and_not_held_keep_no_results_and_draft(self):
        for action in ['cancelled','not_held']:
            with self.subTest(action=action):
                data=self.manifest(action);self.execute(data,'apply');self.target.refresh_from_db();self.event.refresh_from_db()
                self.assertEqual(self.target.expectation_status,action)
                self.assertEqual(self.target.event_id,self.event.pk if action=='cancelled' else None)
                self.assertEqual(self.event.visibility_status,'draft');self.assertFalse(self.event.results.exists())
                self.execute(data,'restore');self.target.refresh_from_db();self.event.refresh_from_db()

    def test_wrong_region_year_series_and_existing_binding_rejected(self):
        data=self.manifest()
        self.event.country_region='france';self.event.save()
        with self.assertRaisesRegex(ValueError,'identity|cas'):self.execute(data,'apply')
        self.event.country_region='united_states';self.event.save()
        other=m.RaceSeries.objects.create(key='other',country_region='united_states',canonical_name_original='Other')
        self.event.race_series=other;self.event.save()
        data=self.manifest()
        with self.assertRaisesRegex(ValueError,'series'):self.execute(data,'apply')

    def test_manual_lock_live_owner_and_source_digest_are_not_bypassed(self):
        data=self.manifest();self.event.manual_lock_flags={'results':True};self.event.save()
        with self.assertRaisesRegex(ValueError,'manual_lock'):self.execute(data,'apply')
        self.event.manual_lock_flags={};self.event.save()
        m.RaceEventProjectionControl.objects.create(event=self.event,write_owner='data_sync')
        with self.assertRaisesRegex(ValueError,'owner'):self.execute(data,'apply')
        m.RaceEventProjectionControl.objects.all().delete()
        (self.root/'source.txt').write_text('Changed evidence')
        with self.assertRaisesRegex(ValueError,'source_digest'):self.execute(data,'apply')

    def test_roster_mismatch_and_unapproved_patch_rejected(self):
        data=self.manifest();data['entries'][0]['results'][0]['horse_name']='Different'
        with self.assertRaisesRegex(ValueError,'roster'):self.execute(data,'apply')
        data=self.manifest();data['entries'][0]['event_patch']['year']=2026
        with self.assertRaisesRegex(ValueError,'patch'):self.execute(data,'apply')
        data=self.manifest();data['entries'][0]['expected_starters']=2
        with self.assertRaisesRegex(ValueError,'count'):self.execute(data,'apply')

    def test_after_drift_and_new_result_reference_stop_restore(self):
        data=self.manifest();self.execute(data,'apply');row=self.event.results.get()
        row.jockey_name='Later';row.save()
        with self.assertRaisesRegex(ValueError,'after_drift'):self.execute(data,'restore')
        row.jockey_name='';row.save()
        term=m.TermEntry.objects.create(term_type='horse',source_ja='Privman',target_zh='Privman')
        profile=m.HorseProfile.objects.create(primary_term=term,original_name='Privman')
        source=m.HorseP0Source.objects.create(profile=profile,source_type='manual',race_result=row)
        with self.assertRaisesRegex(ValueError,'source_reference'):self.execute(data,'restore')
        source.refresh_from_db();self.assertEqual(source.race_result_id,row.pk)

    def test_field_authority_lock_blocks_apply_and_restore(self):
        data = self.manifest()
        lock = m.RaceEventFieldAuthority.objects.create(event=self.event, field_name='grade_text', manual_lock=True)
        with self.assertRaisesRegex(ValueError, 'manual_lock'):
            self.execute(data, 'apply')
        lock.delete()
        self.execute(data, 'apply')
        m.RaceEventFieldAuthority.objects.create(event=self.event, field_name='results', manual_lock=True)
        with self.assertRaisesRegex(ValueError, 'manual_lock'):
            self.execute(data, 'restore')

    def test_incomplete_existing_roster_does_not_close_target(self):
        self.event.status = 'finished'
        self.event.visibility_status = 'published'
        self.event.local_date = date(2025, 9, 12)
        self.event.save()
        m.RaceEventResult.objects.create(event=self.event, horse_name='Winner', finish_position=1, official_finish_position=1)
        data = self.manifest('attach_results')
        data['entries'][0]['expected_starters'] = 4
        with self.assertRaisesRegex(ValueError, 'existing_roster'):
            self.execute(data, 'apply')
        self.target.refresh_from_db()
        self.assertIsNone(self.target.event_id)

    def test_batch_write_failure_rolls_back_earlier_events(self):
        from unittest.mock import patch
        from stable.services.historical_target_reconciliation import event_snapshot, target_snapshot, _set_fields
        first_event, first_target = self.event, self.target
        data = self.manifest()
        self.series = m.RaceSeries.objects.create(key='second', country_region='united_states', canonical_name_original='Second')
        self.event = m.RaceEvent.objects.create(year=2025, slug='second', country_region='united_states', status='cancelled', visibility_status='draft')
        self.target = m.HistoricalRaceEventTarget.objects.create(race_series=self.series, year=2025, country_region='united_states', original_name='Second')
        data['entries'].extend(self.manifest()['entries'])
        before = event_snapshot(first_event), target_snapshot(first_target)
        def fail_second(obj, values):
            if isinstance(obj, m.RaceEvent) and obj.pk == self.event.pk:
                raise ValueError('injected_write_failure')
            return _set_fields(obj, values)
        with patch('stable.services.historical_target_reconciliation._set_fields', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, 'injected_write_failure'):
                self.execute(data, 'apply')
        first_event.refresh_from_db(); first_target.refresh_from_db()
        self.assertEqual(before, (event_snapshot(first_event), target_snapshot(first_target)))
        self.assertFalse(m.RaceEventResult.objects.exists())
        self.assertFalse(m.OperationLog.objects.filter(action_type='reconcile_historical_targets').exists())

    def test_existing_binding_and_year_drift_rejected(self):
        data = self.manifest()
        other = m.HistoricalRaceEventTarget.objects.create(race_series=self.series, year=2026, country_region='united_states', original_name='Other', event=self.event)
        with self.assertRaisesRegex(ValueError, 'existing_target_binding'):
            self.execute(data, 'apply')
        other.delete()
        data['entries'][0]['event_before']['year'] = 2026
        with self.assertRaisesRegex(ValueError, 'identity_scope'):
            self.execute(data, 'apply')

    def test_command_uses_the_bound_manifest(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        data = self.manifest()
        self.execute(data)
        path = self.root / 'manifest.json'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out = StringIO()
        call_command('reconcile_historical_targets', manifest=str(path), sha256=digest, stdout=out)
        self.assertEqual(json.loads(out.getvalue())['mode'], 'dry-run')
        with self.assertRaises(CommandError):
            call_command('reconcile_historical_targets', manifest=str(path), sha256='0'*64)

    def test_pulled_up_and_fell_are_not_nonstarters(self):
        self.event.status='finished';self.event.visibility_status='published';self.event.local_date=date(2025,5,3);self.event.save()
        m.RaceEventRunner.objects.create(event=self.event,horse_name='Winner')
        m.RaceEventResult.objects.create(event=self.event,horse_name='Winner',finish_position=1,official_finish_position=1)
        for marker in ['PU','F']:
            runner=m.RaceEventRunner.objects.create(event=self.event,horse_name='Nonfinisher',source_refs={'official_order_text':marker})
            data=self.manifest('attach_results');data['entries'][0]['nonstarters']=[['','Nonfinisher']]
            with self.assertRaisesRegex(ValueError,'nonstarter'):
                self.execute(data,'apply')
            runner.delete()

    def test_complete_missing_nonfinishers_preserves_existing_and_restores(self):
        from stable.services.historical_target_reconciliation import row_snapshot
        self.event.status='finished';self.event.visibility_status='published';self.event.local_date=date(2025,5,3);self.event.save()
        m.RaceEventRunner.objects.create(event=self.event,horse_name='Winner')
        original=m.RaceEventResult.objects.create(event=self.event,horse_name='Winner',finish_position=1,official_finish_position=1)
        runner=m.RaceEventRunner.objects.create(event=self.event,horse_name='Nonfinisher',running_status='unknown',source_refs={'official_order_text':'PU'})
        data=self.manifest('complete_results');entry=data['entries'][0]
        entry['results']=[dict(horse_number='',horse_name='Nonfinisher',finish_position=2,official_finish_position=None,running_status='pulled_up',is_confirmed=True,source_refs={'official_order_text':'PU'})]
        entry['runner_statuses']=[dict(id=runner.pk,running_status='pulled_up')]
        entry['expected_starters']=2
        before=row_snapshot(self.event.pk)
        self.execute(data,'apply');self.assertTrue(self.execute(data,'apply')['replay'])
        original.refresh_from_db();runner.refresh_from_db()
        self.assertEqual(runner.running_status,'pulled_up');self.assertEqual(self.event.results.count(),2)
        self.assertEqual(row_snapshot(self.event.pk)['results'][0],before['results'][0])
        self.execute(data,'restore');self.assertEqual(row_snapshot(self.event.pk),before)
