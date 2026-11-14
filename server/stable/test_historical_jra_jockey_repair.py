"""历史空骑手修复的原子性、重放与回滚边界。"""
import hashlib
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase
from stable import models as m


class HistoricalJraJockeyRepairTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'manifest.json'
        self.event = m.RaceEvent.objects.create(year=2018, slug='jra-jockey-repair',
            original_name='Sirius', country_region='japan', local_date=date(2018,9,29),
            status='finished', visibility_status='published')
        self.url = 'https://www.jra.go.jp/datafile/seiseki/replay/2018/088.html'
        self.source_sha = '1' * 64
        self.refs = {'primary':self.url, 'source_cache_identity':{'sha256':self.source_sha}}
        self.result = m.RaceEventResult.objects.create(event=self.event, horse_number='3', horse_name='Horse',
            finish_position=1, source_refs=self.refs)
        self.runner = m.RaceEventRunner.objects.create(event=self.event, horse_number='3', horse_name='Horse',
            sort_order=1, source_refs=self.refs)

    def manifest(self):
        e=self.event
        return {'schema_version':1, 'action':'repair_historical_jra_jockeys',
            'events':[{'id':e.pk,'year':2018,'local_date':'2018-09-29','original_name':'Sirius','slug':e.slug}],
            'items':[{'model':kind,'id':row.pk,'event_id':e.pk,'horse_number':'3','horse_name':'Horse',
                'before':{'jockey_name':''},'after':{'jockey_name':'和田竜二'},
                'source_url':self.url,'source_sha256':self.source_sha}
                for kind,row in [('RaceEventResult',self.result),('RaceEventRunner',self.runner)]]}

    def run_repair(self, manifest=None, mode='dry-run'):
        from stable.services.historical_jra_jockey_repair import execute
        raw=json.dumps(manifest or self.manifest(),ensure_ascii=False).encode()
        self.path.write_bytes(raw)
        return execute(self.path, hashlib.sha256(raw).hexdigest(), mode=mode)

    def test_dry_run_apply_replay_and_restore_preserve_other_fields(self):
        self.run_repair()
        self.result.refresh_from_db();self.assertEqual(self.result.jockey_name,'')
        self.assertFalse(m.OperationLog.objects.filter(action_type='repair_historical_jra_jockeys').exists())
        self.run_repair(mode='apply')
        self.result.refresh_from_db();self.assertEqual(self.result.jockey_name,'和田竜二')
        self.assertEqual(self.result.source_refs['primary'],self.url)
        self.assertTrue(self.run_repair(mode='apply')['replay'])
        m.RaceEventResult.objects.filter(pk=self.result.pk).update(trainer_name='Later trainer')
        self.run_repair(mode='restore');self.result.refresh_from_db()
        self.assertEqual(self.result.jockey_name,'');self.assertEqual(self.result.trainer_name,'Later trainer')
        self.assertEqual(self.result.source_refs,self.refs)
        self.assertTrue(self.run_repair(mode='restore')['replay'])

    def test_second_row_drift_rolls_back_whole_package(self):
        m.RaceEventRunner.objects.filter(pk=self.runner.pk).update(jockey_name='Newer name')
        with self.assertRaisesRegex(ValueError,'row_cas'):self.run_repair(mode='apply')
        self.result.refresh_from_db();self.assertEqual(self.result.jockey_name,'')
        self.assertFalse(m.OperationLog.objects.filter(action_type='repair_historical_jra_jockeys').exists())

    def test_source_drift_is_rejected(self):
        m.RaceEventResult.objects.filter(pk=self.result.pk).update(source_refs={'primary':self.url})
        with self.assertRaisesRegex(ValueError,'source_identity'):self.run_repair(mode='apply')

    def test_current_projection_owner_is_rejected(self):
        m.RaceEventProjectionControl.objects.create(event=self.event,write_owner='live')
        with self.assertRaisesRegex(ValueError,'projection_owner'):self.run_repair(mode='apply')

    def test_manual_row_lock_and_event_lock_are_respected(self):
        self.runner.manual_lock_flags={'jockey_name':True};self.runner.save()
        with self.assertRaisesRegex(ValueError,'manual_lock'):self.run_repair(mode='apply')
        self.runner.manual_lock_flags={};self.runner.save()
        self.event.manual_lock_flags={'results':True};self.event.save()
        with self.assertRaisesRegex(ValueError,'manual_lock'):self.run_repair(mode='apply')

    def test_after_image_drift_blocks_restore_without_overwrite(self):
        self.run_repair(mode='apply')
        m.RaceEventResult.objects.filter(pk=self.result.pk).update(jockey_name='Newer name')
        with self.assertRaisesRegex(ValueError,'row_cas'):self.run_repair(mode='restore')
        self.runner.refresh_from_db();self.assertEqual(self.runner.jockey_name,'和田竜二')

    def test_manifest_only_allows_empty_jockey_fill(self):
        data=self.manifest();data['items'][0]['before']['jockey_name']='Existing'
        with self.assertRaisesRegex(ValueError,'fill_only'):self.run_repair(data,mode='apply')
        data=self.manifest();data['items'][0]['after']['trainer_name']='Out of scope'
        with self.assertRaisesRegex(ValueError,'fill_only'):self.run_repair(data,mode='apply')

    def test_hash_duplicate_and_out_of_period_are_rejected(self):
        from stable.services.historical_jra_jockey_repair import execute
        self.path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest_digest'):execute(self.path,'0'*64)
        data=self.manifest();data['items'].append(data['items'][0])
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_repair(data)
        self.event=m.RaceEvent.objects.create(year=2026,slug='outside-history-cutoff',
            local_date=date(2026,9,1),original_name='Sirius',country_region='japan',status='finished')
        with self.assertRaisesRegex(ValueError,'event_scope'):self.run_repair()

    def test_v2_fills_only_blank_source_backed_fields_and_restores(self):
        data=self.manifest();data['schema_version']=2
        data['action']='repair_historical_jra_fields'
        data['items']=data['items'][:1]
        item=data['items'][0]
        item['finish_position']=1
        item['source_refs_sha256']=hashlib.sha256(json.dumps(self.refs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        item['before']={'jockey_name':'','trainer_name':'','carried_weight':''}
        item['after']={'jockey_name':'和田竜二','trainer_name':'Trainer','carried_weight':'57.0'}
        self.run_repair(data,mode='apply');self.result.refresh_from_db()
        self.assertEqual((self.result.trainer_name,self.result.carried_weight),('Trainer','57.0'))
        self.assertTrue(self.run_repair(data,mode='apply')['replay'])
        self.run_repair(data,mode='restore');self.result.refresh_from_db()
        self.assertEqual(self.result.trainer_name,'');self.assertEqual(self.result.source_refs,self.refs)

    def test_v2_provenance_and_nonblank_fields_fail_closed(self):
        data=self.manifest();data.update(schema_version=2,action='repair_historical_jra_fields')
        data['items']=data['items'][:1];item=data['items'][0]
        item['finish_position']=1
        item['source_refs_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source_identity'):self.run_repair(data,mode='apply')
        item['source_refs_sha256']=hashlib.sha256(json.dumps(self.refs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        item['before']['jockey_name']='existing'
        with self.assertRaisesRegex(ValueError,'fill_only'):self.run_repair(data,mode='apply')

    def test_v2_missing_nonfinisher_is_idempotent_and_restorable(self):
        data=self.manifest();data.update(schema_version=2,action='repair_historical_jra_fields')
        data['items']=data['items'][:1];item=data['items'][0];item['finish_position']=1
        item['source_refs_sha256']=hashlib.sha256(json.dumps(self.refs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        data['extra_results']=[{'event_id':self.event.pk,'before_result_ids':[self.result.pk],
            'row':{'finish_position':2,'official_finish_position':None,'horse_number':'9','horse_name':'Nonfinisher',
                'running_status':'pulled_up','source_refs':{'primary':self.url}}}]
        self.run_repair(data,mode='apply')
        extra=self.event.results.get(horse_number='9')
        self.assertIsNone(extra.official_finish_position)
        self.assertTrue(self.run_repair(data,mode='apply')['replay'])
        extra.trainer_name='Later';extra.save()
        with self.assertRaisesRegex(ValueError,'extra_after_drift'):self.run_repair(data,mode='restore')
        extra.trainer_name='';extra.save()
        self.run_repair(data,mode='restore')
        self.assertEqual(self.event.results.count(),1)
        self.assertTrue(self.run_repair(data,mode='restore')['replay'])
