"""英国固定来源身份到公开页的完整路径；离线原件和独立本地数据库。"""
import json
from datetime import date,datetime,timezone
from unittest.mock import patch
from django.test import TestCase,override_settings
from stable import models
from stable import test_race_multisource_jra as workflow
from stable.test_race_multisource_identity import policy_payload
from stable.test_uk_sources import card,result
from stable.services.race_data_source_adapters import parse_multisource_policy,fetch_bound_observation,run_multisource_claim
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import claim_multisource_events
NOW=datetime(2026,10,30,16,tzinfo=timezone.utc)


@override_settings(**{**workflow.JraColdStartTests._overridden_settings,
    'RACE_DATA_SYNC_ENABLED_PROVIDERS':('the_racing_api',),
    'RACE_DATA_SYNC_ENABLED_REGIONS':('united_kingdom',),
    'RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED':True,
    'RACE_DATA_SYNC_ENABLED_FIELDS':('uk_basic.metadata',)})
class UKWorkflowTests(TestCase):
    def setUp(self):
        data=policy_payload('the_racing_api','united_kingdom')
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(country_region='united_kingdom',operator='TRA',timezone='Europe/London',
            source_class='licensed_api',venue_aliases={'newmarket':['Newmarket']},parser_version='uk-tra-paid-v1',
            allowed_hosts=['api.theracingapi.com','www.sportinglife.com'],allowed_path_prefixes=['/v1/','/racing/'],
            valid_from=data['valid_from'],valid_until=data['valid_until'])
        self.policy=parse_multisource_policy(data,now=NOW);self.route=self.policy.routes[0]
        self.event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='uk-example-2026',
            original_name='Example Stakes',country_region='united_kingdom',racecourse='Newmarket',
            local_date=date(2026,10,30),timezone_name='Europe/London',visibility_status='published',
            source_refs={'uk_target_v1':{'external_race_id':'rac_123','name_keys':['examplestakes']}})
        self.card=card();self.card['runners'].pop();self.result=result();self.result['non_runners']=''
        for name,value in [('stable.services.race_data_source_adapters.load_multisource_policy',self.policy),('django.utils.timezone.now',NOW)]:
            p=patch(name,return_value=value);p.start();self.addCleanup(p.stop)
        self.source=models.RaceResultSourceIdentity.objects.create(event=self.event,source_key='the_racing_api',
            region_code='united_kingdom',identity_namespace=self.route.identity_namespace,external_race_id='rac_123',
            canonical_url='https://api.theracingapi.com/v1/racecards/rac_123/pro',review_status='approved',
            terms_status='approved',automation_allowed=True,proof_network_allowed=True,
            valid_until=datetime(2028,1,1,tzinfo=timezone.utc),registry_digest=self.route.digest)

    def fetch(self,url,**kwargs):
        return json.dumps(self.result if '/results/' in url else self.card)

    def publish(self):
        value=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        self.assertTrue(value['roster_complete'])
        decision=attach_multisource_observation(value,policy=self.policy,now=NOW)
        self.assertIn(decision.action,{'acquired','attached','replay'},decision)
        claims=claim_multisource_events(event_ids=[self.event.pk],now=NOW,historical=True)
        self.assertEqual(len(claims),1)
        outcome=run_multisource_claim(claim=claims[0],now=NOW,fetcher=self.fetch)
        self.assertTrue(outcome['processed'],outcome)

    def test_full_result_public_fields_and_idempotence(self):
        from stable.services.race_information_display import row_fields
        self.publish();self.event.refresh_from_db()
        self.assertEqual(self.event.status,'finished')
        self.assertEqual(self.event.distance_text,'1m4f')
        self.assertEqual(self.event.source_refs['uk_race_metadata']['winner_prize_amount'],'42532')
        from stable.services.race_information_display import event_fields
        self.assertIn('冠军奖金',event_fields(self.event)['prize'].text)
        self.assertEqual(self.event.results.count(),2)
        winner=self.event.results.get(reported_finish_position=1)
        self.assertEqual(winner.odds_value,'3.00')
        self.assertIn('磅',row_fields(winner)['weight'].text)
        self.assertEqual(winner.source_refs['field_units']['odds_value'],'decimal')
        self.assertEqual(winner.finish_time,'2:35.89')
        count=self.event.revisions.count()
        self.publish();self.assertEqual(self.event.revisions.count(),count)

    def test_request_completion_time_is_validated_after_fetch(self):
        from datetime import timedelta
        later=NOW+timedelta(seconds=1)
        original=self.fetch
        class Response(str):
            observed_at=later
        self.fetch=lambda *a,**kw:Response(original(*a,**kw))
        with patch('django.utils.timezone.now',return_value=later):
            self.publish()
        self.assertEqual(self.event.results.count(),2)

    @override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=())
    def test_empty_field_permission_blocks_metadata(self):
        from stable.services.uk_basic_fields import apply_metadata_locked
        value=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        before=dict(self.event.source_refs)
        apply_metadata_locked(event=self.event,metadata=value['uk_race_metadata'],route=self.route,now=NOW)
        self.event.refresh_from_db()
        self.assertEqual(self.event.distance_text,'')
        self.assertEqual(self.event.source_refs,before)

    def test_manual_going_lock_is_not_bypassed_by_raw_metadata(self):
        from stable.services.uk_basic_fields import apply_metadata_locked
        from stable.services.race_information_display import event_fields
        self.event.going_text='Good';self.event.save()
        models.RaceEventFieldAuthority.objects.create(event=self.event,subject_type='event',subject_key=str(self.event.pk),
            field_name='going_text',manual_lock=True,source_key='the_racing_api',source_class='licensed_api')
        value=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        value['uk_race_metadata']['going_text']='Heavy'
        apply_metadata_locked(event=self.event,metadata=value['uk_race_metadata'],route=self.route,now=NOW)
        self.event.refresh_from_db()
        self.assertEqual(self.event.going_text,'Good')
        self.assertIn('Good',event_fields(self.event)['going'].text)
        self.assertNotIn('Heavy',event_fields(self.event)['going'].text)

    def test_uk_hurdle_type_remains_public_on_turf(self):
        from stable.services.race_information_display import event_fields
        self.event.surface='Turf';self.event.normalized_race_type='hurdle'
        field=event_fields(self.event)['race_type']
        self.assertEqual(field.state,'normalized')
        self.assertTrue(field.text)

    def test_incomplete_result_does_not_create_public_rows(self):
        self.result['runners'].pop()
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(self.event.results.exists())
