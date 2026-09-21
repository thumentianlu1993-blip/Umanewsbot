from stable import test_race_multisource_identity as fixtures
from datetime import timedelta
from unittest.mock import patch
from django.db import transaction
from django.test import override_settings, TestCase
from stable import models
from stable.test_race_multisource_identity import (
    NOW,
    observation,
    policy_payload,
)
from stable.services.race_data_source_adapters import parse_multisource_policy
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import (
    claim_due_enrollments,
    lock_and_validate_race_data_sync_claim_for_apply,
)


@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra", "alternate"),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
)
class MultisourceClaimTests(TestCase):
    def setUp(self):
        fixtures.IdentityTests.setUp(self)
        fixtures.IdentityTests.anchor(self)
        payload = policy_payload()
        payload["routes"] += policy_payload("alternate")["routes"]
        self.policy = parse_multisource_policy(payload, now=NOW)
        self.loader = patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=self.policy,
        )
        self.loader.start()
        self.addCleanup(self.loader.stop)
        attach_multisource_observation(observation(), policy=self.policy, now=NOW)

    # Inherited identity tests use a different fixture; only execute the contract methods here.
    def claim(self):
        return claim_due_enrollments(
            now=NOW,
            batch_size=20,
            ttl_seconds=240,
            enabled_providers=("jra", "alternate"),
            enabled_regions=("japan_jra",),
            enabled_data_kinds=("result",),
        )

    def test_single_claim_and_attach_invalidates_old_worker(self):
        claims = self.claim()
        self.assertEqual(len(claims), 1)
        self.assertEqual(len(self.claim()), 0)
        self.assertEqual(
            attach_multisource_observation(
                observation("alternate"), policy=self.policy, now=NOW
            ).action,
            "attached",
        )
        with transaction.atomic():
            result, locked = lock_and_validate_race_data_sync_claim_for_apply(
                claim=claims[0], now=NOW
            )
        self.assertIsNone(locked)
        self.assertIn(result.reason_code, ("claim_cas_stale", "claim_plan_drift"))

    def test_claim_contains_exact_binding_authority(self):
        claim = self.claim()[0]
        authority = claim.checkpoint_plan[0]["authority"]
        self.assertEqual(authority["authority_version"], 2)
        self.assertEqual(authority["source_set_generation"], 1)
        with transaction.atomic():
            result, locked = lock_and_validate_race_data_sync_claim_for_apply(
                claim=claim, now=NOW
            )
        self.assertEqual(result.action, "valid")
        self.assertIsNotNone(locked)

    def test_lifecycle_switch_closes_existing_enforce(self):
        from stable.services.race_data_sync_admission import (
            validate_data_sync_lifecycle_admission,
        )

        with override_settings(RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=False):
            self.assertFalse(
                validate_data_sync_lifecycle_admission(
                    event_id=self.event.pk, now=NOW
                ).admitted
            )

    def test_disabled_source_attach_is_zero_write(self):
        before = models.RaceResultSourceIdentity.objects.count()
        with override_settings(RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra",)):
            self.assertEqual(
                attach_multisource_observation(
                    observation("alternate"), policy=self.policy, now=NOW
                ).reason_code,
                "binding_runtime_disabled",
            )
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), before)

    def test_unselected_checkpoint_does_not_leave_parent_due(self):
        from stable.services.race_data_sync_control import finish_multisource_claim

        attach_multisource_observation(
            observation("alternate"), policy=self.policy, now=NOW
        )
        claim = self.claim()[0]
        self.assertEqual(
            finish_multisource_claim(claim=claim, now=NOW, success=True).action,
            "complete",
        )
        track = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertGreater(track.next_poll_at, NOW)

    def test_result_timeout_fallback_is_authorized_then_sticky(self):
        from stable.services.race_data_sync_control import finish_multisource_claim

        attach_multisource_observation(
            observation("alternate"), policy=self.policy, now=NOW
        )
        claim = self.claim()[0]
        finish_multisource_claim(
            claim=claim, now=NOW, success=False, reason_code="http_403"
        )
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        alternate = enrollment.source_set_manifest["alternate"]["result"]["binding_id"]
        next_claim = self.claim()[0]
        self.assertEqual(
            next_claim.checkpoint_plan[0]["authority"]["binding_id"], alternate
        )
        finish_multisource_claim(claim=next_claim, now=NOW, success=True)
        enrollment.refresh_from_db()
        self.assertEqual(
            enrollment.source_set_manifest["selected"]["result"], alternate
        )

    def test_date_only_result_polls_without_fabricated_time(self):
        from stable.services.race_data_sync_control import (
            calculate_multisource_next_poll,
        )

        self.assertEqual(
            calculate_multisource_next_poll(event=self.event, kind="result", now=NOW),
            NOW + timedelta(minutes=30),
        )
        later = NOW + timedelta(days=1)
        self.assertEqual(
            calculate_multisource_next_poll(event=self.event, kind="result", now=later),
            later + timedelta(hours=6),
        )
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)

    def test_blocked_source_is_not_reselected_after_attach(self):
        source = models.RaceResultSourceIdentity.objects.get(source_key="jra")
        source.terms_status = "blocked"
        source.save(update_fields=("terms_status",))
        decision = attach_multisource_observation(
            observation("alternate"), policy=self.policy, now=NOW
        )
        self.assertEqual(decision.action, "attached", decision)
        claim = self.claim()[0]
        self.assertEqual(claim.checkpoint_plan[0]["source_key"], "alternate")
