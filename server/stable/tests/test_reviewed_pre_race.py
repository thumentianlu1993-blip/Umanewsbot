import copy
import json
from datetime import date, datetime, timezone as tz
from django.test import TestCase, override_settings
from stable import models as m
from stable.services import race_pre_race as pre

NOW=datetime(2026,9,18,4,tzinfo=tz.utc)
FLAGS=dict(RACE_DATA_SYNC_ENABLED=True,RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
 RACE_DATA_SYNC_ENABLED_FIELDS=('participants.horse_name','participants.number','participants.draw','participants.jockey_name','participants.trainer_name','participants.carried_weight'))

@override_settings(**FLAGS)
class ReviewedPreviewTests(TestCase):
 def setUp(self):
  self.event=m.RaceEvent.objects.create(year=2026,slug='reviewed',original_name='Firth Of Clyde',country_region='united_kingdom',racecourse='Ayr',local_date=date(2026,9,19),timezone_name='Europe/London',visibility_status='published')
  self.items=[dict(horse_name='Horse',horse_number='1',barrier='2',trainer_name='Trainer',jockey_name='Jockey',carried_weight='57kg',sort_order=1,running_status='declared',source_refs={'horse_id':'123'})]
  import hashlib
  sha=hashlib.sha256(json.dumps(self.items,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
  self.c=m.RaceEventDataCandidate.objects.create(event=self.event,module='runners',source_name='reviewed_pre_race_v1',source_url='https://www.sportinglife.com/racing/racecards/2026-09-19/ayr/racecard/123/test',candidate_payload={'items':self.items},raw_payload={'reviewed_pre_race_v1':{'validated':True,'baseline':pre.baseline(self.event),'authority':'human_reviewed_reference','stage':'numbered','row_count':1,'items_sha256':sha,'source_sha256':'a'*64,'manifest_sha256':'b'*64}},fetched_at=NOW)
 def preview(self,now=NOW):return pre.public_reviewed_preview(self.event,now=now)
 def test_reference_preview_never_creates_canonical_or_results(self):
  p=self.preview();self.assertEqual(p['rows'][0].horse_number,'1');self.assertIn('人工核验',p['label'])
  self.assertFalse(self.event.runners.exists());self.assertFalse(self.event.results.exists())
 def test_actual_public_view_and_tra_handoff_no_duplicate(self):
  from unittest.mock import patch
  with patch('stable.views.timezone.now',return_value=NOW):
   response=self.client.get('/races/2026/reviewed/');self.assertContains(response,'人工核验');self.assertContains(response,'Horse')
  # Canonical TRA IDs are unrelated; a complete TRA card suppresses this whole candidate.
  m.RaceEventRunner.objects.create(event=self.event,horse_name='TRA horse',external_runner_id='hrs_different',horse_number='1')
  self.assertIsNone(self.preview());self.assertEqual(self.event.runners.count(),1)
  self.event.runners.all().delete();self.event.source_refs={'pre_race_handoff':{'revision_id':1}}
  self.assertIsNone(self.preview())
 def test_expired_window_changed_identity_and_locks_reject(self):
  self.assertIsNone(self.preview(datetime(2026,9,20,tzinfo=tz.utc)))
  self.event.manual_lock_flags={'runners':True};self.assertIsNone(self.preview());self.event.manual_lock_flags={}
  self.event.racecourse='Other';self.assertIsNone(self.preview());self.event.racecourse='Ayr'
  m.RaceEventFieldAuthority.objects.create(event=self.event,subject_type='event',field_name='runners',manual_lock=True)
  self.assertIsNone(self.preview())
 def test_unreviewed_partial_tampered_host_or_unpublished_reject(self):
  original=copy.deepcopy(self.c.raw_payload)
  for key,value in [('validated',False),('row_count',2),('stage','unknown'),('authority','official')]:
   self.c.raw_payload=copy.deepcopy(original);self.c.raw_payload['reviewed_pre_race_v1'][key]=value;self.c.save();self.assertIsNone(self.preview())
  self.c.raw_payload=original;self.c.source_url='https://evil.test/card';self.c.save();self.assertIsNone(self.preview())
  self.c.source_url='https://www.sportinglife.com/racing/racecards/2026-09-19/ayr/racecard/123/test';self.c.candidate_payload['items'][0]['horse_name']='tampered';self.c.save();self.assertIsNone(self.preview())
 def test_withdrawn_reference_status_visible_on_real_page(self):
  from unittest.mock import patch
  import hashlib
  self.c.candidate_payload['items'][0]['running_status']='withdrawn'
  self.c.raw_payload['reviewed_pre_race_v1']['items_sha256']=hashlib.sha256(json.dumps(self.c.candidate_payload['items'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();self.c.save()
  for normalized, label in [(False, '退出'), (True, '取消出走')]:
   with override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=normalized), patch('stable.views.timezone.now',return_value=NOW):
    self.assertContains(self.client.get('/races/2026/reviewed/'),label)
 def test_generic_apply_rejects_preview_only_candidate_even_if_source_renamed(self):
  from stable.services.race_events import apply_data_candidate
  for name in ['reviewed_pre_race_v1','renamed']:
   self.c.source_name=name;self.c.save()
   with self.assertRaisesRegex(ValueError,'reviewed_pre_race_candidate_requires_controlled_path'):apply_data_candidate(self.c)
   self.assertFalse(self.event.runners.exists());self.c.refresh_from_db();self.assertEqual(self.c.status,'pending')
 def test_application_disabled_or_manual_owner_reject(self):
  with override_settings(RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False):self.assertIsNone(self.preview())
  m.RaceEventProjectionControl.objects.create(event=self.event,write_owner='manual_paused');self.assertIsNone(self.preview())


class UpcomingBackfillTests(TestCase):
 def setUp(self):
  import importlib.util,tempfile
  from pathlib import Path
  from django.conf import settings
  from unittest.mock import patch
  clock=patch('django.utils.timezone.now',return_value=NOW);clock.start();self.addCleanup(clock.stop)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  path=Path(settings.BASE_DIR).parent/'scripts/backfill_reviewed_pre_race.py'
  spec=importlib.util.spec_from_file_location('upcoming',path);self.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.s)
  self.event=m.RaceEvent.objects.create(year=2026,slug='upcoming',original_name='Masters',country_region='united_states',racecourse='Presque Isle Downs',local_date=date(2026,9,18),timezone_name='America/New_York',visibility_status='published')
 def package(self):
  from django.utils import timezone
  raw=b'officially cached racecard';(self.root/'source.html').write_bytes(raw)
  before=self.s.snapshot(self.event.pk)
  entry=dict(event_id=self.event.pk,before=before,before_sha256=self.s.digest(before),source=dict(provider='sporting_life',url='https://www.sportinglife.com/racing/racecards/2026-09-18/test/racecard/1/test',path='source.html',sha256=self.s.bytes_sha(raw),fetched_at=timezone.now().isoformat(),title='Masters'),off_time='2026-09-19T00:36:00+00:00',time_evidence={'kind':'jsonld_startDate','raw':'2026-09-19T00:36:00.000Z'},stage='numbered',items=[dict(sort_order=1,horse_name='Horse',horse_number='1',barrier='1',jockey_name='Jockey',trainer_name='',carried_weight='',running_status='declared',source_refs={'horse_id':'123'})])
  return dict(schema_version=1,reviewer='test',events=[entry])
 def run_package(self,p,apply=True,hook=None):
  raw=json.dumps(p,sort_keys=True,ensure_ascii=False,default=str).encode();path=self.root/'manifest.json';path.write_bytes(raw)
  return self.s.execute(path,self.s.bytes_sha(raw),apply=apply,fault_hook=hook)['events'][0]
 def test_empty_only_timezone_preservation_and_idempotence(self):
  p=self.package();self.assertEqual(self.run_package(p,False)['status'],'dry_run');self.event.refresh_from_db();self.assertIsNone(self.event.race_datetime)
  self.assertEqual(self.run_package(p)['status'],'applied');self.event.refresh_from_db();self.assertEqual(str(self.event.local_start_time),'20:36:00');self.assertEqual(self.event.local_date,date(2026,9,18));self.assertEqual(self.event.timezone_name,'America/New_York')
  self.assertFalse(self.event.runners.exists());self.assertFalse(self.event.results.exists());self.assertEqual(self.event.data_candidates.count(),1);self.assertEqual(self.run_package(p)['status'],'already_applied')
 def test_wrong_timezone_missing_time_evidence_partial_or_duplicate_blocks(self):
  for change in [lambda e:e.update(off_time='2026-09-19T00:36:00'),lambda e:e.update(off_time='2026-09-20T00:36:00+00:00'),lambda e:e.update(time_evidence={}),lambda e:e['items'].append(copy.deepcopy(e['items'][0])),lambda e:e['items'][0].update(running_status='unknown')]:
   p=self.package();change(p['events'][0]);self.assertEqual(self.run_package(p)['status'],'blocked')
 def test_owner_manual_lock_existing_time_and_full_before_drift_block(self):
  p=self.package();self.event.source_refs={'new':'state'};self.event.save();self.assertEqual(self.run_package(p)['status'],'blocked')
  m.RaceEventProjectionControl.objects.create(event=self.event,write_owner='data_sync');self.assertEqual(self.run_package(self.package())['status'],'blocked')
  self.event.projection_control.delete();self.event.manual_lock_flags={'runners':True};self.event.save();self.assertEqual(self.run_package(self.package())['status'],'blocked')
 def test_midwrite_failure_rolls_back_both_time_and_candidate(self):
  called=[]
  def fail(**kw):called.append(kw);raise RuntimeError('injected')
  self.assertEqual(self.run_package(self.package(),hook=fail)['status'],'blocked');self.event.refresh_from_db();self.assertIsNone(self.event.race_datetime);self.assertFalse(self.event.data_candidates.exists());self.assertEqual(len(called),1)

 def test_server_local_before_file_sha_and_path_boundaries(self):
  p=self.package();e=p['events'][0];before=e.pop('before');(self.root/'before.json').write_text(json.dumps(before,default=str));e['before_path']='before.json'
  self.assertEqual(self.run_package(p,False)['status'],'dry_run')
  e['before_sha256']='0'*64;self.assertEqual(self.run_package(p)['status'],'blocked')
  e['before_path']='../outside.json';self.assertEqual(self.run_package(p)['status'],'blocked')

class NarReviewedBackfillTests(UpcomingBackfillTests):
 def nar_package(self):
  self.event.country_region='japan';self.event.racecourse='金泽';self.event.original_name='白山大賞典';self.event.local_date=date(2026,9,22);self.event.timezone_name='Asia/Tokyo';self.event.save()
  p=self.package();e=p['events'][0]
  raw='<html><body><p>2026年9月22日（火）　金　沢　第11競走　18:00発走</p></body></html>'.encode()
  (self.root/'source.html').write_bytes(raw)
  e['source'].update(provider='nar',url='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11',sha256=self.s.bytes_sha(raw))
  e.update(off_time='2026-09-22T18:00:00+09:00',time_evidence={'kind':'nar_race_header','raw':'2026年9月22日（火）　金　沢　第11競走　18:00発走'})
  return p
 def test_official_nar_time_candidate_and_replay(self):
  p=self.nar_package();self.assertEqual(self.run_package(p)['status'],'applied');self.event.refresh_from_db()
  self.assertEqual(str(self.event.local_start_time),'18:00:00');self.assertFalse(self.event.runners.exists())
  candidate=self.event.data_candidates.get();self.assertEqual(candidate.raw_payload['reviewed_pre_race_v1']['authority'],'human_reviewed_official')
  with override_settings(**FLAGS):self.assertIn('官方资料',pre.public_reviewed_preview(self.event,now=NOW)['label'])
  self.assertEqual(self.run_package(p)['status'],'already_applied')
 def test_nar_header_mismatch_or_foreign_timezone_reject(self):
  for change in [lambda e:e.update(off_time='2026-09-22T17:00:00+09:00'),lambda e:e['time_evidence'].update(raw='2026年9月22日（火）　金　沢　第11競走　17:00発走'),lambda e:e['source'].update(url=e['source']['url'].replace('k_raceNo=11','k_raceNo=10')),lambda e:e['before']['event'].update(timezone_name='America/New_York')]:
   p=self.nar_package();change(p['events'][0]);self.assertEqual(self.run_package(p)['status'],'blocked')
 def test_official_authority_cannot_be_asserted_by_reference_host(self):
  p=self.nar_package();self.assertEqual(self.run_package(p)['status'],'applied');c=self.event.data_candidates.get();c.source_url='https://www.racingpost.com/racecards/123/';c.save()
  with override_settings(**FLAGS):self.assertIsNone(pre.public_reviewed_preview(self.event,now=NOW))
