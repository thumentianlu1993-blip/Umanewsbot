"""法国赛前时间与正式claim的PostgreSQL锁/租约回归。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from types import SimpleNamespace

from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase, override_settings
from stable import models
from stable import test_france_automation as france_tests
ROOT = france_tests.ROOT

AT = datetime(2026,11,1,10,tzinfo=timezone.utc)
FLAGS = {**france_tests.FranceResultWorkflowTests._overridden_settings,
    'RACE_DATA_SYNC_FRANCE_PRE_RACE_ENABLED': True,
    'RACE_DATA_SYNC_ENABLED_PROVIDERS': ('france_galop','geny'),
    'RACE_DATA_SYNC_ENABLED_DATA_KINDS': ('race_time','racecard'),
    'RACE_DATA_SYNC_ENABLED_FIELDS': ('off_time','local_start_time','timezone_name','participants.horse_name'),
    'RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED': True, 'RACE_DATA_SYNC_ALLOW_NETWORK': True}


@skipUnless(connection.vendor=='postgresql', 'requires PostgreSQL row locks')
@override_settings(**FLAGS)
class FranceTimeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        france_tests.FranceResultWorkflowTests.setUp(self)
        from stable.services.race_data_source_adapters import parse_multisource_policy
        import copy
        payload=copy.deepcopy(self.policy.payload)
        payload['routes'][0]['capabilities']=['race_time','racecard']
        self.policy=parse_multisource_policy(payload,now=AT)
        for target,value in [('django.utils.timezone.now',AT),('stable.services.race_data_source_adapters.load_multisource_policy',self.policy)]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)
        self.route=self.policy.routes[0]
        from stable.services.france_sources import parse_geny_observation
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        value=parse_geny_observation((ROOT/'avenir-card.html').read_text(),url=self.base+'partants-pronostics',route=self.route,now=AT)
        self.assertEqual(attach_multisource_observation(value,policy=self.policy,now=AT).action,'acquired')
        models.RaceEventLiveTracking.objects.filter(event=self.event).update(next_poll_at=AT)
        models.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event=self.event).update(next_poll_at=AT)

    def pre_claim(self):
        from stable.services.race_pre_race import claim_pre_race
        claim=claim_pre_race(event_id=self.event.pk,source='france_pre_race_v1',now=AT)
        self.assertIsNotNone(claim)
        return claim

    def complete(self, claim):
        from stable.services.france_pre_race import complete
        return complete(claim,payload=dict(local_date='2026-11-02',race_name="Prix de l'Avenir",venue='Nantes',
            stage='not_published',schedule=[],items=[],off_time='2026-11-02T15:59:00+01:00'),
            url=self.base+'partants-pronostics',page=SimpleNamespace(observed_at=AT,raw_sha256='a'*64),route=self.route,now=AT)

    def formal_claim(self):
        from stable.services.race_data_sync_control import claim_due_enrollments
        return claim_due_enrollments(now=AT,batch_size=1,ttl_seconds=240,
            enabled_providers=('geny',),enabled_regions=('france',),enabled_data_kinds=('race_time','racecard'))

    def test_enrolled_time_updates_before_roster_with_public_cache_invalidation(self):
        with patch('stable.services.race_data_sync_pipeline.invalidate_public_race_cache') as clear:
            self.assertTrue(self.complete(self.pre_claim()))
            self.assertEqual(clear.call_count,1)
        self.event.refresh_from_db()
        self.assertEqual(str(self.event.local_start_time),'15:59:00')
        self.assertFalse(self.event.runners.exists())
        self.assertEqual(self.event.live_tracking.active_attempt_token,'')

    def test_formal_claim_is_not_stolen_by_pre_race_completion(self):
        claim=self.pre_claim()
        formal=self.formal_claim()
        self.assertEqual(len(formal),1)
        self.assertFalse(self.complete(claim))
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)
        self.assertEqual(self.event.live_tracking.active_attempt_token,formal[0].attempt_token)

    def test_concurrent_formal_claim_and_pre_completion_have_one_writer_without_deadlock(self):
        claim=self.pre_claim();barrier=Barrier(2)
        def run(fn):
            close_old_connections()
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=10)
                return fn()
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(run,lambda:self.complete(claim));b=pool.submit(run,self.formal_claim)
            completed,formal=a.result(timeout=20),b.result(timeout=20)
        self.event.refresh_from_db()
        if completed:
            self.assertEqual(str(self.event.local_start_time),'15:59:00')
            self.assertFalse(formal)
        else:
            self.assertEqual(len(formal),1)
            self.assertIsNone(self.event.race_datetime)
            self.assertEqual(self.event.live_tracking.active_attempt_token,formal[0].attempt_token)

    def test_generation_release_and_expired_claims_fail_closed(self):
        claim=self.pre_claim()
        with override_settings(UMANEWS_RELEASE_COMMIT='f'*40):
            self.assertFalse(self.complete(claim))
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)
