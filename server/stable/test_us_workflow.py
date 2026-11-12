from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.conf import settings
from stable import models
from stable import test_race_multisource_jra as workflow
from stable.test_race_multisource_identity import policy_payload
from stable.test_us_flat_results import TARGETS, FIXTURES
from stable.services.race_data_source_adapters import parse_multisource_policy, fetch_bound_observation, run_multisource_claim
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import claim_multisource_events
from stable.services.race_source_identity import identity_key

NOW=datetime(2026,11,11,12,tzinfo=timezone.utc)


@override_settings(**{**workflow.JraColdStartTests._overridden_settings,
    'RACE_DATA_SYNC_ENABLED_PROVIDERS':('us_racing',), 'RACE_DATA_SYNC_ENABLED_REGIONS':('united_states',),
    'RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED':True,
    'RACE_DATA_SYNC_ENABLED_FIELDS':(*settings.RACE_DATA_SYNC_ENABLED_FIELDS,'us_basic.prize','us_basic.distance','us_basic.eligibility','us_basic.race_metadata','off_time','local_start_time','timezone_name')})
class USWorkflowTests(TestCase):
    def setUp(self):
        self.target=next(t for t in TARGETS if t['drf']['url'].endswith('CD2026110708.pdf'))
        from stable.services.us_flat_collection import DRF_INDEX, SL_INDEX
        self.docs={DRF_INDEX:(FIXTURES/'drf-index.html').read_bytes(), SL_INDEX+'2026-11-07':(FIXTURES/'sl-day.html').read_bytes(),
            self.target['drf']['url']:(FIXTURES/'CD2026110708.pdf').read_bytes(),
            self.target['sporting_life'][0]['url']:(FIXTURES/'CD2026110708.html').read_bytes(),
            'https://toba.org/graded-stakes/2026-races/':(FIXTURES.parent/'us_automation/toba.html').read_bytes()}
        data=policy_payload('us_racing','united_states')
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(country_region='united_states',operator='us',timezone='America/New_York',
            venue_aliases={'CD':['Churchill Downs','Churchill']}, source_class='trusted_publisher',
            allowed_hosts=['www1.drf.com','toba.org','www.sportinglife.com'],allowed_path_prefixes=['/StakesResults/','/displayChart.do','/graded-stakes/','/racing/'],
            valid_from=data['valid_from'],valid_until=data['valid_until'])
        self.policy=parse_multisource_policy(data,now=NOW)
        self.route=self.policy.routes[0]
        self.event=models.RaceEvent.objects.create(year=2026,slug='river-city-us',original_name='River City',chinese_name='河城锦标',
            country_region='united_states',racecourse='Churchill Downs',local_date=date(2026,11,7),timezone_name='America/New_York',
            visibility_status='published',source_refs={'us_target_v1':self.target['toba']})
        for name,value in [('stable.services.race_data_source_adapters.load_multisource_policy',self.policy),('django.utils.timezone.now',NOW)]:
            p=patch(name,return_value=value);p.start();self.addCleanup(p.stop)
        self.value=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        models.RaceEventIdentityKey.objects.create(event=self.event,**identity_key(self.value))

    def fetch(self,url,**kw):
        return self.docs[url]

    def publish(self):
        decision=attach_multisource_observation(self.value,policy=self.policy,now=NOW)
        self.assertIn(decision.action,{'acquired','attached'},decision)
        claims=claim_multisource_events(event_ids=[self.event.pk],now=NOW,historical=True)
        self.assertEqual(len(claims),1)
        result=run_multisource_claim(claim=claims[0],now=NOW,fetcher=self.fetch)
        self.assertTrue(result['processed'],result)

    def test_no_prior_card_complete_final_roster_publishes_and_replays(self):
        from stable.services.race_information_display import row_fields
        self.assertFalse(self.event.runners.exists())
        self.assertTrue(self.value['roster_complete'])
        self.publish()
        self.event.refresh_from_db()
        self.assertEqual(self.event.status,'finished')
        self.assertEqual(str(self.event.prize_amount),'300000.00')
        self.assertEqual(self.event.eligibility_text,'3yo+')
        self.assertEqual(self.event.source_refs['us_race_metadata']['winning_time'],'1:47.20')
        self.assertEqual(self.event.results.count(),8)
        self.assertEqual(self.event.runners.count(),8)
        winner=self.event.results.get(reported_finish_position=1)
        self.assertEqual(row_fields(winner)['odds'].text,'4.06（美国净赔率）')
        self.assertIn('磅',row_fields(winner)['weight'].text)
        response=self.client.get(self.event.public_path)
        self.assertContains(response,'参赛记录（赛果来源）')
        self.assertContains(response,'距前一匹冲线马')
        self.assertContains(response,'300000美元')
        self.assertContains(response,'比赛用时')
        self.assertContains(response,'1分47.20秒')
        self.assertContains(response,'分段累计用时')
        self.assertContains(response,'1分34.56秒')
        self.assertContains(response,'快地（firm）')
        revisions=models.RaceEventRevision.objects.filter(event=self.event).count()
        claims=claim_multisource_events(event_ids=[self.event.pk],now=NOW,historical=True)
        self.assertEqual(len(claims),1)
        outcome=run_multisource_claim(claim=claims[0],now=NOW,fetcher=self.fetch)
        self.assertTrue(outcome['processed'],outcome)
        self.assertEqual(models.RaceEventRevision.objects.filter(event=self.event).count(),revisions)
        self.assertEqual(self.event.results.count(),8)

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True)
    def test_result_only_projects_actual_clock_with_authority_and_audit(self):
        self.event.race_datetime=datetime.fromisoformat(self.value['us_race_metadata']['scheduled_off_time'])
        self.event.save()
        self.publish();self.event.refresh_from_db()
        actual=datetime.fromisoformat(self.value['off_time'])
        self.assertEqual(self.event.race_datetime,actual)
        self.assertEqual(self.event.local_start_time,actual.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).time())
        for field in ('race_datetime','local_start_time','timezone_name'):
            authority=self.event.field_authorities.get(field_name=field)
            self.assertEqual(authority.source_key,'us_racing')
        self.assertTrue(self.event.field_changes.filter(field_name='race_datetime',applied=True).exists())
        from stable.services.race_information_display import event_fields
        self.assertEqual(event_fields(self.event)['time'].state,'normalized')

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True)
    def test_result_only_fills_missing_clock(self):
        self.publish();self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime,datetime.fromisoformat(self.value['off_time']))

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True)
    def test_actual_clock_keeps_manual_authority(self):
        planned=datetime.fromisoformat(self.value['us_race_metadata']['scheduled_off_time'])
        self.event.race_datetime=planned;self.event.save()
        authority=models.RaceEventFieldAuthority.objects.create(event=self.event,subject_type='event',subject_key=str(self.event.pk),
            field_name='race_datetime',manual_lock=True,value_sha256='a'*64)
        self.publish();self.event.refresh_from_db();authority.refresh_from_db()
        self.assertEqual(self.event.status,'finished')
        self.assertEqual(self.event.race_datetime,planned)
        self.assertEqual(authority.value_sha256,'a'*64)
        self.assertFalse(self.event.field_changes.filter(field_name='race_datetime').exists())

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,RACE_DATA_SYNC_ENABLED_FIELDS=('us_basic.race_metadata',))
    def test_disabled_time_fields_do_not_project_actual_clock(self):
        self.publish();self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False)
    def test_disabled_clock_projection_preserves_missing_value(self):
        self.publish();self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True)
    def test_missing_actual_clock_preserves_planned_value(self):
        from copy import deepcopy
        value=deepcopy(self.value);value['off_time']='';value['us_race_metadata']['off_time']=''
        planned=datetime.fromisoformat(value['us_race_metadata']['scheduled_off_time'])
        self.event.race_datetime=planned;self.event.save()
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):self.publish()
        self.event.refresh_from_db();self.assertEqual(self.event.race_datetime,planned)

    def test_announced_official_prize_yields_to_actual_result(self):
        from stable.services.us_stakes_schedule import apply_schedule_locked
        from django.db import transaction
        from types import SimpleNamespace
        target=self.event.source_refs['us_target_v1']
        schedule={**target,'prize_amount':'250000','prize_currency':'USD','prize_stage':'announced',
            'source_class':'official_operator','source':dict(url='https://www.churchilldowns.com/overnights/',sha256='a'*64,fetched_at=NOW.isoformat())}
        with transaction.atomic():apply_schedule_locked(self.event,schedule,route=SimpleNamespace(permits_url=lambda u:True),now=NOW)
        self.assertEqual(str(self.event.prize_amount),'250000')
        self.publish();self.event.refresh_from_db()
        self.assertEqual(str(self.event.prize_amount),'300000.00')
        for name in ['prize_amount','prize_currency']:
            self.assertEqual(self.event.field_authorities.get(field_name=name).source_key,'us_racing')
        self.assertEqual(self.event.source_refs['us_pre_race_schedule']['prize_stage'],'superseded_by_result')

    def test_manual_surface_lock_survives_result_enrollment_and_public_read(self):
        self.event.surface='dirt';self.event.manual_lock_flags={'surface':True};self.event.save()
        self.publish();self.event.refresh_from_db()
        self.assertEqual(self.event.surface,'dirt')
        from stable.services.race_information_display import event_fields
        self.assertEqual(event_fields(self.event)['surface'].text,'泥地')
        self.assertEqual(self.event.manual_lock_flags,{'surface':True})
        self.assertContains(self.client.get(self.event.public_path),'参赛记录（赛果来源）')
        self.event.manual_lock_flags={'results':True};self.event.save()
        self.assertNotContains(self.client.get(self.event.public_path),'id="results"')
        self.assertFalse(claim_multisource_events(event_ids=[self.event.pk],now=NOW,historical=True))

    def test_completed_fetch_uses_completion_clock_without_rewriting_source_clock(self):
        from datetime import timedelta
        from stable.services.race_pre_race import SourceBytes
        fetched=NOW+timedelta(seconds=65)
        def fetch(url,**kw):return SourceBytes(self.docs[url],observed_at=fetched)
        with patch('django.utils.timezone.now',return_value=NOW+timedelta(seconds=70)):
            value=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=fetch)
        self.assertEqual(value['fetched_at'],fetched.isoformat())

    def test_stale_live_observation_cannot_self_authorize_archive_replay(self):
        from copy import deepcopy
        from datetime import timedelta
        from stable.services.race_source_identity import resolve_observation
        value=deepcopy(self.value);value['fetched_at']=(NOW-timedelta(hours=48)).isoformat()
        value['archive_replay']={'manifest_sha256':'a'*64}
        match=resolve_observation(value,route=self.route,now=NOW)
        self.assertEqual(match.reason,'observation_stale')
        decision=attach_multisource_observation(value,policy=self.policy,now=NOW)
        self.assertEqual(decision.reason_code,'observation_stale')
        self.assertFalse(models.RaceDataSyncEnrollment.objects.filter(event=self.event).exists())

    def test_archive_receipt_binds_exact_result_and_retains_time_policy_guards(self):
        from copy import deepcopy
        from datetime import timedelta
        from stable.services.race_source_identity import ArchivedResultReceipt,resolve_observation
        from stable.services.race_data_source_adapters import canonical_sha,SourceRoute
        value=deepcopy(self.value);value['fetched_at']=(NOW-timedelta(hours=48)).isoformat()
        receipt=ArchivedResultReceipt('a'*64,canonical_sha(value))
        match=resolve_observation(value,route=self.route,now=NOW,archive_receipt=receipt)
        self.assertEqual((match.status,match.event_id),('exact',self.event.pk))
        self.assertEqual(match.evidence['archive_replay']['source_fetched_at'],value['fetched_at'])
        altered=deepcopy(value);altered['roster'][0]['horse_name']='Different horse'
        self.assertEqual(resolve_observation(altered,route=self.route,now=NOW,archive_receipt=receipt).reason,'archive_observation_mismatch')
        future=deepcopy(value);future['fetched_at']=(NOW+timedelta(hours=1)).isoformat()
        future_receipt=ArchivedResultReceipt('a'*64,canonical_sha(future))
        self.assertEqual(resolve_observation(future,route=self.route,now=NOW,archive_receipt=future_receipt).reason,'observation_stale')
        expired=SourceRoute({**self.route.payload,'valid_until':(NOW-timedelta(days=1)).isoformat()},self.route.digest)
        self.assertEqual(resolve_observation(value,route=expired,now=NOW,archive_receipt=receipt).reason,'observation_route_invalid')
        self.assertEqual(resolve_observation(value,route=self.route,now=NOW,archive_receipt={'manifest_sha256':'a'*64}).reason,'archive_receipt_invalid')
        card=deepcopy(value);card['result_phase']=''
        self.assertEqual(resolve_observation(card,route=self.route,now=NOW,archive_receipt=ArchivedResultReceipt('a'*64,canonical_sha(card))).reason,'archive_observation_mismatch')
        # 显式回放结束后，默认实时入口仍拒绝同一陈旧来源。
        self.assertEqual(resolve_observation(value,route=self.route,now=NOW).reason,'observation_stale')

    def check_correction(self, explicit):
        from copy import deepcopy
        from datetime import timedelta
        self.publish()
        control=models.RaceEventProjectionControl.objects.get(event=self.event)
        original=control.current_result_revision_id
        value=deepcopy(self.value)
        value['roster'][1]['margin']='3/4'
        value['result_phase']='corrected' if explicit else 'official'
        value['raw_sha256']='f'*64
        later=NOW+timedelta(hours=6,minutes=1)
        value['fetched_at']=later.isoformat()
        with patch('django.utils.timezone.now',return_value=later), patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
            claim=claim_multisource_events(event_ids=[self.event.pk],now=later,historical=True)[0]
            outcome=run_multisource_claim(claim=claim,now=later,fetcher=self.fetch)
        control.refresh_from_db()
        self.assertEqual(outcome['processed'],explicit,outcome)
        self.assertEqual(control.current_result_revision_id!=original,explicit)
        if explicit:
            self.assertTrue(self.event.results.filter(margin='3/4').exists())

    def test_explicit_correction_publishes_new_revision(self):
        self.check_correction(True)

    def test_changed_official_result_without_marker_keeps_current(self):
        self.check_correction(False)

@override_settings(**USWorkflowTests._overridden_settings)
class USNSAWorkflowTests(TestCase):
    def test_early_withdrawals_have_stable_identity_without_final_number(self):
        import hashlib,json
        from stable.test_us_prerelease import USSteeplechaseTests, FIX
        from stable.services.us_prerace_documents import parse_overnight
        from stable.services.us_steeplechase_results import resolve_prior_card_scratches
        from stable.services.us_race_source import source_observation
        fixture=USSteeplechaseTests();case=fixture.CASES[2]
        result=fixture.bundle(case)
        prior_name='nsa-extra-Revised-Foxfield-Overnight-Monday-.pdf'
        prior=parse_overnight((FIX/prior_name).read_bytes(),local_date='2026-10-04',venue='FX',race_number=6)
        result=resolve_prior_card_scratches(result,prior)
        provenance={x['file']:x for x in json.loads((FIX/'provenance.json').read_text())}
        sources={kind:dict(url=provenance[name]['url'],sha256=hashlib.sha256((FIX/name).read_bytes()).hexdigest(),
            fetched_at=NOW.isoformat()) for kind,name in [('chart',case[0]),('overnight',case[1]),('official_result',case[2]),('prior_overnight',prior_name)]}
        data=policy_payload('us_racing','united_states')
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(country_region='united_states',operator='us',timezone='America/New_York',venue_aliases={'FX':['Foxfield']},
            source_class='trusted_publisher',allowed_hosts=['www1.drf.com','nationalsteeplechase.com'],
            allowed_path_prefixes=['/displayChart.do','/wp-content/'],valid_from=data['valid_from'],valid_until=data['valid_until'])
        policy=parse_multisource_policy(data,now=NOW)
        target=dict(venue='FX',local_date='2026-10-04',source_race_id='6',race_name=result['race_name'])
        value=source_observation(result,target=target,sources=sources,route=policy.routes[0],now=NOW)
        event=models.RaceEvent.objects.create(year=2026,slug='foxfield-us',original_name=result['race_name'],
            country_region='united_states',racecourse='Foxfield',local_date=date(2026,10,4),timezone_name='America/New_York',
            visibility_status='published')
        models.RaceEventIdentityKey.objects.create(event=event,**identity_key(value))
        with patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=policy), patch('django.utils.timezone.now',return_value=NOW), patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
            decision=attach_multisource_observation(value,policy=policy,now=NOW)
            self.assertEqual(decision.action,'acquired',decision)
            for _ in range(2):
                claim=claim_multisource_events(event_ids=[event.pk],now=NOW,historical=True)[0]
                outcome=run_multisource_claim(claim=claim,now=NOW,fetcher=lambda *a,**k:None)
                self.assertTrue(outcome['processed'],outcome)
        event.refresh_from_db()
        self.assertEqual(event.status,'finished')
        self.assertEqual(event.results.count(),11)
        self.assertEqual(event.runners.filter(horse_number='').count(),2)
        self.assertEqual(event.results.filter(horse_number='').count(),2)
        self.assertEqual(event.results.filter(running_status='scratched').count(),2)
        self.assertEqual(event.results.get(reported_finish_position=1).horse_name,'LYDFORD (GB)')

@override_settings(**{**USWorkflowTests._overridden_settings,
    'RACE_DATA_SYNC_ENABLED_DATA_KINDS':('race_time','racecard'),'RACE_DATA_SYNC_US_PRE_RACE_ENABLED':True,
    'RACE_DATA_SYNC_RACECARD_APPLY_ENABLED':True,'RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED':True,
    'RACE_DATA_SYNC_ENABLED_FIELDS':('off_time','local_start_time','timezone_name','participants.horse_name','participants.number','participants.draw','participants.jockey_name','participants.trainer_name','participants.carried_weight','participants.odds','participants.status')})
class USCardWorkflowTests(TestCase):
    def test_current_card_preserves_weight_and_fractional_odds_contract(self):
        import json,hashlib
        from stable.test_us_prerelease import FIX
        from stable.services.us_pre_race import preview_document,card_observation
        from stable.services.us_prerace_documents import parse_sporting_card
        from stable.services.race_information_display import row_fields
        filename='sl-churchill-livecard.html';raw=(FIX/filename).read_bytes()
        meta=next(x for x in json.loads((FIX/'provenance.json').read_text()) if x['file']==filename)
        card=parse_sporting_card(raw,dict(track='CD',date='2026-11-11',race_number=1))
        doc=dict(data=card,source=dict(url=meta['url'],sha256=hashlib.sha256(raw).hexdigest(),fetched_at=NOW.isoformat()))
        target=dict(venue='CD',local_date='2026-11-11',race_name=card['race_name'])
        data=policy_payload('us_racing','united_states',kinds=('race_time','racecard'))
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(country_region='united_states',operator='us',timezone='America/New_York',
            venue_aliases={'CD':['Churchill Downs']},source_class='trusted_publisher',
            allowed_hosts=['www.sportinglife.com'],allowed_path_prefixes=['/racing/'],
            valid_from=data['valid_from'],valid_until=data['valid_until'])
        policy=parse_multisource_policy(data,now=NOW)
        preview=preview_document(doc,target=target)
        self.assertEqual(preview['items'][0]['odds_value'],'12/1')
        value=card_observation(preview,route=policy.routes[0])
        event=models.RaceEvent.objects.create(year=2026,slug='us-current-card',original_name=card['race_name'],
            country_region='united_states',racecourse='Churchill Downs',local_date=date(2026,11,11),timezone_name='America/New_York',visibility_status='published')
        event.source_refs={'us_target_v1':{**target,'candidate_key':'fixture-current-card'}};event.save()
        from stable.services import race_pre_race as pre
        from stable.services.us_pre_race import complete,US
        with patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=policy),patch('django.utils.timezone.now',return_value=NOW),patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
            from datetime import timedelta
            from copy import deepcopy
            earlier=NOW-timedelta(minutes=10)
            nominated=deepcopy(preview);nominated.update(stage='nominations',final_card=False)
            nominated['source']['fetched_at']=earlier.isoformat()
            for row in nominated['items']:
                row.update(horse_number='',running_status='nominated')
            first=pre.claim_pre_race(event_id=event.pk,source=US,now=earlier)
            self.assertTrue(complete(first,payload=nominated,route=policy.routes[0],now=earlier))
            claim=pre.claim_pre_race(event_id=event.pk,source=US,now=NOW)
            self.assertTrue(complete(claim,payload=preview,route=policy.routes[0],now=NOW))
            decision=attach_multisource_observation(value,policy=policy,now=NOW)
            self.assertEqual(decision.action,'acquired',decision)
            from stable.services.race_data_sync_control import claim_due_enrollments
            claims=claim_due_enrollments(now=NOW,batch_size=20,ttl_seconds=240,enabled_providers=('us_racing',),
                enabled_regions=('united_states',),enabled_data_kinds=('race_time','racecard'))
            self.assertEqual(len(claims),1)
            outcome=run_multisource_claim(claim=claims[0],now=NOW,fetcher=lambda *a,**k:None)
            self.assertTrue(outcome['processed'],outcome)
        row=event.runners.get(horse_name='Street Painter')
        self.assertEqual(row.odds_value,'12/1')
        self.assertEqual(row_fields(row)['odds'].state,'normalized')
        self.assertIn('磅',row_fields(row)['weight'].text)
        event.refresh_from_db()
        self.assertEqual(event.race_datetime.isoformat(),'2026-11-11T18:00:00+00:00')
