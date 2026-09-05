from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable import models
from stable.services import race_data_sync_enrollment
from stable.test_race_data_sync_policy_v2 import (
    _policy_v2,
    _route,
    two_provider_roster,
)
from stable.test_race_data_sync_r0 import NOW, SHA_A, create_event


class EnrollmentLifecycleWiringTests(TestCase):
    def setUp(self):
        self.roster, self.bindings = two_provider_roster()
        self.roster_patcher = patch(
            "stable.services.race_data_sync_pipeline.build_race_data_provider_roster",
            return_value=self.roster,
        )
        self.roster_patcher.start()
        self.addCleanup(self.roster_patcher.stop)
        self.event = create_event(slug="wiring-event")
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="jra",
            region_code="japan",
            identity_namespace="jra-race-v1",
            external_race_id=f"jra-{self.event.pk}",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://jra.example.test/reviewed-proof",
            evidence_sha256=SHA_A,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.roster.registry_digest,
        )
        self.policy = _policy_v2(
            routes=[_route(digest=self.bindings["jra"].route_digest, order=1)]
        )

    def _apply(self, *, allow_runtime_open: bool = False):
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self.policy,
            cutoff=NOW,
            horizon_days=30,
        )
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(self.event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=manifest.as_dict(),
            expected_manifest_sha256=manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW,
            allow_runtime_open=allow_runtime_open,
        )
        return manifest

    @override_settings(RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True)
    def test_apply_with_lifecycle_apply_enabled_establishes_enforce_control(self):
        manifest = self._apply(allow_runtime_open=True)

        control = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.assertEqual(control.mode, models.RaceEventLifecycleMode.ENFORCE)
        self.assertEqual(
            control.enrollment_manifest_sha256, manifest.manifest_sha256
        )
        evidence = control.manifest_data["race_data_sync"]
        from stable.services.race_data_sync_enrollment import parse_standing_policy

        self.assertEqual(
            evidence["standing_policy_digest"],
            parse_standing_policy(self.policy).digest,
        )
        self.assertEqual(evidence["manifest_sha256"], manifest.manifest_sha256)
        self.assertEqual(
            evidence["entry_sha256"],
            manifest.as_dict()["entries"][0]["entry_sha256"],
        )
        self.assertEqual(evidence["owner_generation"], 1)
        self.assertIsNotNone(control.next_refresh_at)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.SCHEDULED)

    @override_settings(RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=False)
    def test_apply_with_lifecycle_apply_disabled_keeps_control_off(self):
        manifest = self._apply()

        control = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.assertEqual(control.mode, models.RaceEventLifecycleMode.OFF)
        evidence = control.manifest_data["race_data_sync"]
        from stable.services.race_data_sync_enrollment import parse_standing_policy

        self.assertEqual(
            evidence["standing_policy_digest"],
            parse_standing_policy(self.policy).digest,
        )
        self.assertEqual(evidence["manifest_sha256"], manifest.manifest_sha256)

    @override_settings(RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True)
    def test_existing_manual_pause_is_not_cleared(self):
        models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.OFF,
            manual_pause_reason="operator hold",
        )

        self._apply(allow_runtime_open=True)

        control = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.assertEqual(control.manual_pause_reason, "operator hold")
        self.assertNotEqual(control.mode, models.RaceEventLifecycleMode.ENFORCE)
