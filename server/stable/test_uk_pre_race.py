"""英国早期报名不冒充正式出马表，正式名单接入来源绑定。"""
from datetime import timedelta
from django.test import TestCase,override_settings
from stable import test_uk_workflow as workflow
NOW=workflow.NOW
from stable.services import race_pre_race as pre
from stable.services.uk_pre_race import UK,complete,public_uk_preview,route_for
from stable.services.uk_collection import fetch_payload

@override_settings(**{**workflow.UKWorkflowTests._overridden_settings,
    "RACE_DATA_SYNC_UK_PRE_RACE_ENABLED":True,"RACE_DATA_SYNC_RACECARD_APPLY_ENABLED":True,
    "RACE_DATA_SYNC_ENABLED_FIELDS":("participants.horse_name",)})
class UKPreRaceTests(TestCase):
    fetch=workflow.UKWorkflowTests.fetch
    def setUp(self):
        workflow.UKWorkflowTests.setUp(self)
        self.source.delete()
        self.event.race_datetime=NOW+timedelta(hours=2)
        self.event.save()

    def test_entry_then_final_identity_and_cutoff(self):
        self.card.update(race_status='entry',field_size='2')
        payload=fetch_payload(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        claim=pre.claim_pre_race(event_id=self.event.pk,source=UK,now=NOW)
        self.assertTrue(complete(claim,payload=payload,route=self.route,now=NOW))
        self.event.refresh_from_db()
        preview=public_uk_preview(self.event,now=NOW)
        self.assertEqual(preview['label'],'报名名单')
        self.assertFalse(self.event.runners.exists())
        self.assertFalse(self.event.source_identities.exists())
        self.assertTrue(all(not r.horse_number for r in preview['rows']))
        self.assertIsNone(public_uk_preview(self.event,now=self.event.race_datetime-timedelta(minutes=29)))
        self.card.update(race_status='declared')
        later=NOW+timedelta(minutes=11)
        claim=pre.claim_pre_race(event_id=self.event.pk,source=UK,now=later)
        payload=fetch_payload(event=self.event,route=self.route,now=later,fetcher=self.fetch)
        self.assertTrue(complete(claim,payload=payload,route=self.route,now=later))
        self.assertEqual(self.event.source_identities.get().external_race_id,'rac_123')

    @override_settings(RACE_DATA_SYNC_ENABLED_DATA_KINDS=('race_time','racecard','result'),
        RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_FIELDS=('off_time','local_start_time','timezone_name','participants.horse_name',
            'participants.number','participants.draw','participants.jockey_name','participants.trainer_name',
            'participants.carried_weight','participants.status','participants.odds','uk_basic.metadata'))
    def test_final_card_discovery_claim_and_public_writer(self):
        from copy import deepcopy
        from unittest.mock import patch
        from stable.services.race_data_source_adapters import parse_multisource_policy,run_multisource_claim
        from stable.services.race_data_sync_control import claim_due_enrollments
        from stable.services.uk_pre_race import discover_uk_pre_race
        from stable.services.race_information_display import row_fields
        data=deepcopy(self.policy.payload);data['routes'][0]['capabilities']=['race_time','racecard','result']
        earlier=NOW-timedelta(hours=3);policy=parse_multisource_policy(data,now=earlier)
        self.card['race_status']='declared'
        self.card['runners'][0]['odds']=[{'bookmaker':'Bet365','decimal':'4.25'}]
        with patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=policy),patch('django.utils.timezone.now',return_value=earlier):
            report=discover_uk_pre_race(now=earlier,policy=policy,fetcher=self.fetch,clock=lambda:earlier)
            self.assertEqual(report,{'checked':1,'errors':[]})
            claims=claim_due_enrollments(now=earlier,batch_size=20,ttl_seconds=240,enabled_providers=('the_racing_api',),
                enabled_regions=('united_kingdom',),enabled_data_kinds=('race_time','racecard'))
            self.assertEqual(len(claims),1)
            outcome=run_multisource_claim(claim=claims[0],now=earlier,fetcher=self.fetch)
            self.assertTrue(outcome['processed'],outcome)
            runner=self.event.runners.get(external_runner_id='hrs_1')
            self.assertEqual(runner.odds_value,'4.25')
            self.assertIn('Bet365',row_fields(runner)['odds'].text)
            later=earlier+timedelta(minutes=11)
            self.card['runners'][0]['odds'][0]['decimal']='5.00'
            self.card['going']='Heavy'
            self.card['distance']='2m'
            with patch('django.utils.timezone.now',return_value=later):
                claims=claim_due_enrollments(now=later,batch_size=20,ttl_seconds=240,enabled_providers=('the_racing_api',),
                    enabled_regions=('united_kingdom',),enabled_data_kinds=('race_time','racecard'))
                self.assertEqual(len(claims),1)
                outcome=run_multisource_claim(claim=claims[0],now=later,fetcher=self.fetch)
                self.assertTrue(outcome['processed'],outcome)
            self.event.refresh_from_db()
            self.assertEqual(self.event.runners.get(external_runner_id='hrs_1').odds_value,'5.00')
            self.assertEqual(self.event.going_text,'Heavy')
            self.assertEqual(self.event.distance_text,'2m')
            # 已发布报价随后退赛，必须在状态写入后隐藏报价；手动锁定的历史值保留。
            later+=timedelta(minutes=11)
            self.card['runners'][0]['number']='NR';self.card['field_size']='1'
            runner=self.event.runners.get(external_runner_id='hrs_1')
            runner.manual_lock_flags={'odds_value':True};runner.save()
            with patch('django.utils.timezone.now',return_value=later):
                claims=claim_due_enrollments(now=later,batch_size=20,ttl_seconds=240,enabled_providers=('the_racing_api',),
                    enabled_regions=('united_kingdom',),enabled_data_kinds=('race_time','racecard'))
                self.assertEqual(len(claims),1)
                outcome=run_multisource_claim(claim=claims[0],now=later,fetcher=self.fetch)
                self.assertTrue(outcome['processed'],outcome)
            runner.refresh_from_db()
            self.assertEqual(runner.running_status,'scratched')
            self.assertEqual(runner.odds_value,'5.00')
            self.assertEqual(row_fields(runner)['odds'].state,'missing')

        self.assertEqual(self.event.runners.count(),2)
        self.assertIn('磅',row_fields(self.event.runners.first())['weight'].text)
        self.event.refresh_from_db();self.assertEqual(self.event.race_datetime.isoformat(),self.card['off_dt'])

    def test_disabled_claim(self):
        with override_settings(RACE_DATA_SYNC_UK_PRE_RACE_ENABLED=False):
            self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source=UK,now=NOW))
