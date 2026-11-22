from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from stable import models
from stable.services import race_pre_race as pre
from stable.services.us_pre_race import US, complete, public_us_preview

NOW=datetime(2026,11,7,14,tzinfo=timezone.utc)


@override_settings(RACE_DATA_SYNC_US_PRE_RACE_ENABLED=True,RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=True,RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=('us_racing',),RACE_DATA_SYNC_ENABLED_REGIONS=('united_states',),
    RACE_DATA_SYNC_ENABLED_FIELDS=('participants.horse_name','participants.jockey_name','participants.trainer_name','participants.carried_weight'))
class USPreRaceTests(TestCase):
    def setUp(self):
        self.event=models.RaceEvent.objects.create(year=2026,slug='us-preview',original_name='Test Stakes',
            chinese_name='测试赛',country_region='united_states',racecourse='Churchill Downs',
            visibility_status='published',local_date=date(2026,11,7),timezone_name='America/New_York',priority='P1')
        from types import SimpleNamespace
        self.route=SimpleNamespace(valid=lambda t:True,permits_url=lambda u:True,digest='a'*64)
        self.payload=dict(stage='nominations',items=[dict(horse_name='A Horse',horse_number='',barrier='',jockey_name='',
            trainer_name='A Trainer',carried_weight='',running_status='nominated')],
            source=dict(url='https://www.dmtc.com/racing/entries/2026-11-07',sha256='b'*64,fetched_at=NOW.isoformat()))

    @override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=('participants.horse_name','us_basic.prize'))
    def test_verified_future_purse_applies_without_promoting_missing_card(self):
        from decimal import Decimal
        target=dict(venue='CD',local_date='2026-11-07',race_name='Test Stakes',candidate_key='test')
        self.event.source_refs={'us_target_v1':target};self.event.save()
        claim=pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW)
        schedule={**target,'prize_amount':'300000','prize_currency':'USD','prize_stage':'announced',
            'source_class':'official','source':dict(url='https://www.churchilldowns.com/overnights/',sha256='a'*64,fetched_at=NOW.isoformat())}
        payload=dict(stage='coverage_unverified',items=[],source={},schedule=schedule)
        self.assertTrue(complete(claim,payload=payload,route=self.route,now=NOW))
        self.event.refresh_from_db()
        self.assertEqual(self.event.prize_amount,Decimal('300000'))
        self.assertEqual(self.event.prize_currency,'USD')
        self.assertEqual(self.event.source_refs['us_pre_race_schedule']['prize_stage'],'announced')
        self.assertFalse(self.event.data_candidates.exists())
        self.assertEqual(pre._state(self.event,US)['reason'],'coverage_unverified')

    def test_nsa_unpublished_directory_is_evidence_not_a_transport_failure(self):
        from stable.services.us_pre_race import fetch_preview
        from stable.test_us_prerelease import FIX
        target=dict(venue='CAM',local_date='2026-11-22',race_name='COLONIAL CUP',candidate_key='colonial',provider='nsa')
        self.event.local_date=date(2026,11,22);self.event.source_refs={'us_target_v1':target};self.event.save()
        raw=(FIX/'nsa-directory-colonial-pending.html').read_bytes()
        payload=fetch_preview(self.event,route=self.route,now=NOW,fetcher=lambda url,**kw:raw)
        self.assertEqual(payload['stage'],'not_published')
        self.assertEqual(payload['items'],[])
        self.assertEqual(payload['source']['url'],'https://nationalsteeplechase.com/racing/')
        claim=pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW)
        self.assertTrue(complete(claim,payload=payload,route=self.route,now=NOW))
        self.event.refresh_from_db()
        self.assertEqual(self.event.source_refs['us_pre_race_checks']['source']['sha256'],payload['source']['sha256'])
        self.assertFalse(self.event.data_candidates.exists())

    def test_prospective_candidate_has_public_status(self):
        from stable.services.race_information_display import row_fields
        self.payload['stage'] = 'preliminary_field'
        self.payload['items'][0]['running_status'] = 'prospective'
        claim = pre.claim_pre_race(event_id=self.event.pk, source=US, now=NOW)
        self.assertTrue(complete(claim, payload=self.payload, route=self.route, now=NOW))
        self.event.refresh_from_db()
        with override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=('participants.horse_name', 'participants.status')):
            preview = public_us_preview(self.event, now=NOW)
        row = preview['rows'][0]
        self.assertEqual(row.get_running_status_display(), '预想参赛')
        self.assertEqual(row_fields(row)['status'].text, '预想参赛')

    def test_colonial_directory_to_preview_preserves_provisional_stage(self):
        from stable.services.us_pre_race import fetch_preview
        from stable.test_us_prerelease import FIX
        target=dict(venue='CAM',local_date='2026-11-22',race_name='COLONIAL CUP',
                    candidate_key='colonial',provider='nsa',source_race_id='138')
        self.event.local_date=date(2026,11,22)
        self.event.source_refs={'us_target_v1':target};self.event.save()
        def fetch(url,**kw):
            filename='nsa-colonial-directory-20261122.html' if url.endswith('/racing/') else 'nsa-colonial-overnight-20261122.pdf'
            return (FIX/filename).read_bytes()
        payload=fetch_preview(self.event,route=self.route,now=NOW,fetcher=fetch)
        self.assertEqual((payload['stage'],len(payload['items'])),('declared_overnight',9))
        self.assertFalse(payload['final_card'])
        self.assertTrue(all(not r['horse_number'] for r in payload['items']))
        claim=pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW)
        self.assertTrue(complete(claim,payload=payload,route=self.route,now=NOW))
        self.event.refresh_from_db()
        self.assertEqual(self.event.data_candidates.count(),1)
        self.assertFalse(self.event.runners.exists())
        self.assertFalse(self.event.source_identities.exists())
        self.assertEqual(public_us_preview(self.event,now=NOW)['label'],'临时出马资料')

    def test_unverified_coverage_records_reason_without_publishing_candidate(self):
        claim = pre.claim_pre_race(event_id=self.event.pk, source=US, now=NOW)
        self.assertTrue(complete(claim, payload=dict(stage='coverage_unverified', items=[], source={}), route=self.route, now=NOW))
        self.event.refresh_from_db()
        self.assertEqual(pre._state(self.event, US)['reason'], 'coverage_unverified')
        self.assertFalse(self.event.data_candidates.exists())
        self.assertIsNone(public_us_preview(self.event, now=NOW))

    def test_lease_candidate_preview_and_next_five_minute_claim(self):
        claim=pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW)
        self.assertIsNotNone(claim)
        self.assertTrue(complete(claim,payload=self.payload,route=self.route,now=NOW))
        self.event.refresh_from_db()
        preview=public_us_preview(self.event,now=NOW)
        self.assertEqual(preview['label'],'报名名单')
        self.assertEqual(preview['rows'][0].horse_name,'A Horse')
        self.assertFalse(self.event.runners.exists())
        self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW+timedelta(minutes=4)))
        self.assertIsNotNone(pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW+timedelta(minutes=5)))

    def test_manual_lock_blocks_candidate_and_disabled_switch_blocks_claim(self):
        claim=pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW)
        self.event.manual_lock_flags={'runners':True};self.event.save()
        self.assertFalse(complete(claim,payload=self.payload,route=self.route,now=NOW))
        self.assertFalse(self.event.data_candidates.exists())
        with override_settings(RACE_DATA_SYNC_US_PRE_RACE_ENABLED=False):
            self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW))

    def test_public_preview_respects_shared_display_gates(self):
        claim=pre.claim_pre_race(event_id=self.event.pk,source=US,now=NOW)
        self.assertTrue(complete(claim,payload=self.payload,route=self.route,now=NOW))
        self.event.refresh_from_db()
        for config in [dict(RACE_DATA_SYNC_ENABLED=False),dict(RACE_DATA_SYNC_ENABLED_FIELDS=()),
                       dict(RACE_DATA_SYNC_ENABLED_PROVIDERS=()),dict(RACE_DATA_SYNC_ENABLED_REGIONS=())]:
            with self.subTest(config=config),override_settings(**config):
                self.assertIsNone(public_us_preview(self.event,now=NOW))

    def test_existing_final_card_enrollment_replay_is_successful(self):
        from types import SimpleNamespace
        from stable.services.us_pre_race import discover_us_pre_race
        payload={**self.payload,'final_card':True}
        with patch('stable.services.us_pre_race.route_for',return_value=self.route),patch('stable.services.us_pre_race.fetch_preview',return_value=payload),patch('stable.services.us_pre_race.complete',return_value=True),patch('stable.services.us_pre_race.card_observation',return_value={}),patch('stable.services.race_data_sync_enrollment.attach_multisource_observation',return_value=SimpleNamespace(action='replay',reason_code='')):
            result=discover_us_pre_race(now=NOW,policy=SimpleNamespace(valid=lambda now:True),clock=lambda:NOW)
        self.assertEqual(result,{'checked':1,'errors':[]})


class USBoundPreviewGapTests(SimpleTestCase):
    def test_retained_card_refreshes_after_rolling_index_moves_to_tomorrow(self):
        from types import SimpleNamespace
        from stable.services.us_pre_race import fetch_preview
        from stable.test_us_prerelease import FIX
        url='https://www.sportinglife.com/racing/racecards/2026-11-21/belmont-park/racecard/950364/race-9-pebbles-stakes-grade-3'
        target=dict(provider='toba',local_date='2026-11-21',venue='BEL',race_name='PEBBLES S.',candidate_key='pebbles')
        event=SimpleNamespace(local_date=date(2026,11,21),source_refs={'us_target_v1':target,
            'us_pre_race_checks':{'stage':'declared_card','source':{'url':url}}})
        route=SimpleNamespace(permits_url=lambda u:True)
        raw=(FIX/'pebbles-card-20261121.html').read_bytes();calls=[]
        def fetch(u,**kw):calls.append(u);return raw
        with patch('stable.services.us_prerelease_collection.collect_prerace') as collect:
            value=fetch_preview(event,route=route,now=NOW,fetcher=fetch)
        collect.assert_not_called()
        self.assertEqual(calls,[url])
        self.assertEqual((value['stage'],len(value['items'])),('declared_card',10))
        self.assertTrue(value['final_card'])
        for bad in [raw.replace(b'950364',b'950365'),raw.replace(b'Pebbles Stakes',b'Other Stakes'),
                    raw.replace(b'Belmont Park',b'Churchill Downs'),raw.replace(b'2026-11-21',b'2026-11-20'),
                    raw.replace(b'race_summary_reference',b'missing_summary_reference')]:
            with self.subTest(bad=bad[:50]),self.assertRaises(ValueError):
                fetch_preview(event,route=route,now=NOW,fetcher=lambda u,**kw:bad)

    def test_retained_card_uses_local_date_for_us_evening_race(self):
        from types import SimpleNamespace
        from stable.services.us_pre_race import retained_card_preview
        from stable.test_us_prerelease import FIX
        raw=(FIX/'sl-remington-livecard.html').read_bytes()
        url='https://www.sportinglife.com/racing/racecards/2026-11-11/remington-park/racecard/948649/race-1-claiming'
        event=SimpleNamespace(source_refs={'us_pre_race_checks':{'stage':'declared_card','source':{'url':url}}})
        store=SimpleNamespace(get=lambda u:dict(body=raw,url=u,sha256='a'*64,fetched_at=NOW.isoformat()))
        target=dict(venue='RP',local_date='2026-11-11',race_name='Claiming',source_race_id='1')
        value=retained_card_preview(event,target=target,store=store)
        self.assertEqual((value['local_date'],value['off_time']),('2026-11-11','2026-11-11T18:30:00-06:00'))
        self.assertTrue(value['final_card'])
        with self.assertRaises(ValueError):
            retained_card_preview(event,target={**target,'local_date':'2026-11-12'},store=store)

    def test_retained_card_rejects_target_race_number_conflict(self):
        from types import SimpleNamespace
        from stable.services.us_pre_race import retained_card_preview
        from stable.test_us_prerelease import FIX
        raw=(FIX/'pebbles-card-20261121.html').read_bytes()
        url='https://www.sportinglife.com/racing/racecards/2026-11-21/belmont-park/racecard/950364/race-9-pebbles-stakes-grade-3'
        event=SimpleNamespace(source_refs={'us_pre_race_checks':{'stage':'declared_card','source':{'url':url}}})
        store=SimpleNamespace(get=lambda u:dict(body=raw,url=u,sha256='a'*64,fetched_at=NOW.isoformat()))
        target=dict(venue='BEL',local_date='2026-11-21',race_name='PEBBLES S.',source_race_id='8')
        with self.assertRaisesMessage(ValueError,'us_retained_card_identity'):
            retained_card_preview(event,target=target,store=store)
