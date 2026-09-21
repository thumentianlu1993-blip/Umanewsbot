from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase, override_settings
from stable import models
from stable import test_race_multisource_identity as fixtures
from stable.services.race_data_source_adapters import parse_multisource_policy
from stable.services.race_data_sync_enrollment import attach_multisource_observation


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row locks")
@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra", "alternate"),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
)
class MultisourceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        fixtures.IdentityTests.setUp(self)
        fixtures.IdentityTests.anchor(self)
        payload = fixtures.policy_payload()
        payload["routes"] += fixtures.policy_payload("alternate")["routes"]
        self.policy = parse_multisource_policy(payload, now=fixtures.NOW)

    def run_pair(self, providers):
        barrier = Barrier(2)

        def run(provider):
            close_old_connections()
            try:
                with connections["default"].cursor() as c:
                    c.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=10)
                return attach_multisource_observation(
                    fixtures.observation(provider), policy=self.policy, now=fixtures.NOW
                )
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, p) for p in providers]
            return [f.result(timeout=20) for f in futures]

    def test_different_sources_compete_for_missing_lifecycle(self):
        result = self.run_pair(("jra", "alternate"))
        self.assertEqual(
            sorted(r.action for r in result), ["acquired", "attached"], result
        )
        self.assertEqual(models.RaceDataSyncEnrollment.objects.count(), 1)
        self.assertEqual(models.RaceDataSyncSourceBinding.objects.count(), 2)
        self.assertEqual(models.RaceEventLifecycleControl.objects.count(), 1)
        self.assertEqual(
            models.RaceEventProjectionControl.objects.get(
                event=self.event
            ).owner_generation,
            1,
        )

    def test_same_source_retries_are_idempotent(self):
        result = self.run_pair(("jra", "jra"))
        self.assertEqual(
            sorted(r.action for r in result), ["acquired", "replay"], result
        )
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), 1)
        self.assertEqual(models.RaceDataSyncSourceBinding.objects.count(), 1)

    @override_settings(RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",))
    def test_two_workers_only_one_parent_claim(self):
        from unittest.mock import patch
        from stable.services.race_data_sync_control import claim_due_enrollments

        self.assertEqual(
            attach_multisource_observation(
                fixtures.observation(), policy=self.policy, now=fixtures.NOW
            ).action,
            "acquired",
        )
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                with connections["default"].cursor() as c:
                    c.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=10)
                return claim_due_enrollments(
                    now=fixtures.NOW,
                    batch_size=20,
                    ttl_seconds=240,
                    enabled_providers=("jra",),
                    enabled_regions=("japan_jra",),
                    enabled_data_kinds=("result",),
                )
            finally:
                connections["default"].close()

        with patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=self.policy,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            claims = [
                claim for future in futures for claim in future.result(timeout=20)
            ]
        self.assertEqual(len(claims), 1)
        self.assertEqual(
            models.RaceEventLiveTracking.objects.get(
                event=self.event
            ).active_attempt_token,
            claims[0].attempt_token,
        )
