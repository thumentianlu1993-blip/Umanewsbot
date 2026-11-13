"""空表历史赛事的取消修正、完整名单导入和精确恢复。"""
import hashlib
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from stable import models as m


class HistoricalEmptyRaceRepairTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'manifest.json'
        self.event = m.RaceEvent.objects.create(year=2024, local_date=date(2024, 10, 24),
            slug='empty-history', original_name='Montgomery', country_region='france',
            status='finished', visibility_status='draft')

    def manifest(self, cancel=False):
        from stable.services.historical_empty_race_repair import event_snapshot
        e = self.event
        if cancel:
            e.country_region = 'united_kingdom'
            e.save()
        runner = {'horse_number':'1', 'horse_name':'Horse', 'sort_order':1,
                  'running_status':'finished', 'source_refs':{'primary':'https://www.sportinglife.com/racing/results/example'}}
        result = {k:v for k,v in runner.items() if k != 'sort_order'}
        result.update(finish_position=1, official_finish_position=1)
        return {'schema_version':1, 'action':'repair_historical_empty_races', 'events':[{
            'id':e.pk, 'before':event_snapshot(e), 'mode':'cancel' if cancel else 'fill',
            'sources':[{'url':'https://www.sportinglife.com/racing/results/example','sha256':'1'*64}],
            'runners':[] if cancel else [runner], 'results':[] if cancel else [result],
            'targets':[]}]}

    def execute(self, data, mode='dry-run'):
        from stable.services.historical_empty_race_repair import execute
        raw=json.dumps(data).encode();self.path.write_bytes(raw)
        return execute(self.path, hashlib.sha256(raw).hexdigest(), mode=mode)

    def test_fill_dry_run_replay_restore(self):
        data=self.manifest()
        self.execute(data)
        self.assertFalse(self.event.results.exists())
        self.execute(data,'apply')
        self.event.refresh_from_db()
        self.assertEqual(self.event.visibility_status,'published')
        self.assertEqual(self.event.results.count(),1)
        self.assertTrue(self.execute(data,'apply')['replay'])
        self.execute(data,'restore')
        self.event.refresh_from_db()
        self.assertEqual(self.event.visibility_status,'draft')
        self.assertFalse(self.event.results.exists())
        self.assertFalse(self.event.runners.exists())
        self.assertTrue(self.execute(data,'restore')['replay'])

    def test_cancel_preserves_draft_and_no_roster(self):
        data=self.manifest(cancel=True)
        self.execute(data,'apply');self.event.refresh_from_db()
        self.assertEqual(self.event.status,'cancelled')
        self.assertEqual(self.event.visibility_status,'draft')
        self.assertFalse(self.event.results.exists())
        self.execute(data,'restore');self.event.refresh_from_db()
        self.assertEqual(self.event.status,'finished')

    def test_no_overwrite_existing_rows_or_manual_locks(self):
        data=self.manifest()
        row=m.RaceEventResult.objects.create(event=self.event,horse_name='New',finish_position=1)
        with self.assertRaisesRegex(ValueError,'not_empty'):self.execute(data,'apply')
        row.delete()
        self.event.manual_lock_flags={'results':True};self.event.save()
        with self.assertRaisesRegex(ValueError,'manual_lock'):self.execute(data,'apply')

    def test_live_owner_and_new_enrollment_blocked(self):
        data=self.manifest()
        m.RaceEventProjectionControl.objects.create(event=self.event,write_owner='live')
        with self.assertRaisesRegex(ValueError,'owner'):self.execute(data,'apply')

    def test_restore_rejects_changed_rows_and_career_references(self):
        data=self.manifest();self.execute(data,'apply')
        row=self.event.results.get();row.jockey_name='Later';row.save()
        with self.assertRaisesRegex(ValueError,'after_drift'):self.execute(data,'restore')
        self.assertEqual(self.event.results.count(),1)

    def test_bad_roster_and_digest_rejected(self):
        from stable.services.historical_empty_race_repair import execute
        data=self.manifest();data['events'][0]['results'][0]['horse_name']='Wrong'
        with self.assertRaisesRegex(ValueError,'roster'):self.execute(data,'apply')
        with self.assertRaisesRegex(ValueError,'digest'):execute(self.path,'0'*64)

    def test_restore_preserves_later_p0_source_links(self):
        data=self.manifest();self.execute(data,'apply')
        term=m.TermEntry.objects.create(term_type='horse',source_ja='Horse',target_zh='Horse')
        profile=m.HorseProfile.objects.create(primary_term=term,original_name='Horse')
        for field,row in [('race_result',self.event.results.get()),('race_runner',self.event.runners.get())]:
            with self.subTest(field=field):
                source=m.HorseP0Source.objects.create(profile=profile,source_type='manual',**{field:row})
                with self.assertRaisesRegex(ValueError,'source_reference'):self.execute(data,'restore')
                source.refresh_from_db();self.assertEqual(getattr(source,field+'_id'),row.pk)
                source.delete()
