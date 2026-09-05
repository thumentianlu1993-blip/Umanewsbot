from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable import models
from stable.services import race_data_sync_admission
from stable.services.race_data_sync_pipeline import resolve_race_data_provider_route
from stable.test_race_data_sync_policy_v2 import _policy_v2, _route
from stable.test_race_data_sync_providers import (
    _ROSTER_ALLOWED_FIELDS,
    NOW,
    REGISTRY_ACTIVATION,
    REGISTRY_ENTRY,
    REGISTRY_MEMBERSHIP,
    REGISTRY_ROOT,
    ROOT,
    SHA,
)


LIFECYCLE_ENROLLMENT = "f" * 64


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
    RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_LIVE_TRA_REGISTRY_SHA256=SHA,
    RACE_LIVE_TRA_REGISTRY_FILE="/not/read/in/test.json",
    RACE_LIVE_TRA_SECRET_ENV_FILE="/not/read/in/test.env",
    RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2 * 1024 * 1024,
    RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
    RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1024 * 1024 * 1024,
    RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=1000,
    RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=1024 * 1024 * 1024,
    RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=512 * 1024 * 1024,
    RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
    RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
    RACE_DATA_RAW_CLEANUP_MAX_BYTES=64 * 1024 * 1024,
    RACE_DATA_RAW_HOLD_ALERT_BYTES=256 * 1024 * 1024,
    RACE_DATA_RAW_ARTIFACT_ROOTS=(str(ROOT / "runtime"),),
    RACE_EVENT_LIFECYCLE_ENABLED=True,
    RACE_EVENT_LIFECYCLE_MODE="enforce",
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=REGISTRY_ROOT,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=REGISTRY_MEMBERSHIP,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class DataSyncLifecycleAdmissionTests(TestCase):
    def setUp(self):
        self.route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            data_kinds=("race_time", "racecard", "result"),
        )
        self.assertIsNotNone(self.route)
        self.policy = _policy_v2(
            routes=[
                _route(
                    provider="the_racing_api",
                    namespace="the_racing_api-race-v1",
                    digest=self.route.route_digest,
                    region_code="japan_jra",
                    order=1,
                )
            ]
        )
        from stable.services.race_data_sync_enrollment import parse_standing_policy

        self.policy_digest = parse_standing_policy(self.policy).digest
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="admission-event",
            original_name="Admission Cup",
            chinese_name="准入杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW + timedelta(days=1),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 29),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        self.projection = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=3,
            owner_manifest_sha256="d" * 64,
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="jp-admission-1",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/terms",
            evidence_sha256="0" * 64,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )
        self.enrollment = models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=self.source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest=self.policy_digest,
            route_digest=self.route.route_digest,
            event_snapshot_sha256="b" * 64,
            projection_owner_generation=3,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="e" * 64,
            effective_at=NOW - timedelta(days=1),
        )
        self.control = models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.ENFORCE,
            schedule_generation=1,
            enrollment_manifest_sha256="d" * 64,
            manifest_data={
                "race_data_sync": {
                    "standing_policy_digest": self.policy_digest,
                    "manifest_sha256": "d" * 64,
                    "entry_sha256": "e" * 64,
                    "owner_generation": 3,
                }
            },
        )

    def _validate(self, **kwargs):
        return race_data_sync_admission.validate_data_sync_lifecycle_admission(
            event_id=self.event.pk,
            now=NOW,
            standing_policy=self.policy,
            **kwargs,
        )

    def test_valid_data_sync_enrollment_is_admitted(self):
        decision = self._validate()

        self.assertTrue(decision.admitted, decision.reason_code)
        self.assertEqual(decision.authority, "data_sync")
        self.assertEqual(decision.enrollment.pk, self.enrollment.pk)
        self.assertEqual(decision.source.pk, self.source.pk)

    @override_settings(RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=False)
    def test_lifecycle_apply_flag_off_is_rejected(self):
        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "lifecycle_apply_disabled")

    def test_event_not_published_is_rejected(self):
        self.event.visibility_status = models.RaceEventVisibility.DRAFT
        self.event.save(update_fields=("visibility_status",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "event_not_published")

    def test_manual_lock_is_rejected(self):
        self.event.manual_lock_flags = {"race_datetime": True}
        self.event.save(update_fields=("manual_lock_flags",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "manual_lock_present")

    def test_status_outside_continuation_is_rejected(self):
        self.event.status = models.RaceEventStatus.CANCELLED
        self.event.save(update_fields=("status",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "continuation_status_not_allowed")

    def test_writer_owner_conflict_is_rejected(self):
        self.projection.write_owner = models.RaceEventProjectionWriteOwner.LIVE
        self.projection.save(update_fields=("write_owner",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "writer_owner_conflict")

    def test_policy_digest_drift_is_rejected(self):
        self.enrollment.standing_policy_digest = "9" * 64
        self.enrollment.save(update_fields=("standing_policy_digest",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "enrollment_policy_drift")

    def test_owner_generation_drift_is_rejected(self):
        self.projection.owner_generation = 4
        self.projection.save(update_fields=("owner_generation",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "enrollment_owner_generation_drift")

    def test_source_not_admitted_is_rejected(self):
        self.source.valid_until = NOW - timedelta(days=1)
        self.source.save(update_fields=("valid_until",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertNotEqual(decision.reason_code, "")

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra", "japan_nar"))
    def test_second_admitted_eligible_route_is_grant_conflict(self):
        jra_route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            data_kinds=("race_time", "racecard", "result"),
        )
        nar_route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region="japan_nar",
            identity_namespace="the_racing_api-race-v1",
            data_kinds=("race_time", "racecard", "result"),
        )
        if jra_route is None or nar_route is None:
            self.skipTest("japan_nar route is not available in this roster")
        self.source.registry_digest = jra_route.registry_digest
        self.source.save(update_fields=("registry_digest",))
        self.enrollment.route_digest = jra_route.route_digest
        self.enrollment.save(update_fields=("route_digest",))
        second = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="japan_nar",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="jp-admission-2",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/terms",
            evidence_sha256="0" * 64,
            valid_until=NOW + timedelta(days=30),
            registry_digest=jra_route.registry_digest,
        )
        policy = _policy_v2(
            routes=[
                _route(
                    provider="the_racing_api",
                    namespace="the_racing_api-race-v1",
                    digest=jra_route.route_digest,
                    region_code="japan_jra",
                    order=1,
                ),
                _route(
                    provider="the_racing_api",
                    namespace="the_racing_api-race-v1",
                    digest=nar_route.route_digest,
                    region_code="japan_nar",
                    order=2,
                ),
            ]
        )
        from stable.services.race_data_sync_enrollment import parse_standing_policy

        new_digest = parse_standing_policy(policy).digest
        self.enrollment.standing_policy_digest = new_digest
        self.enrollment.save(update_fields=("standing_policy_digest",))
        self.control.manifest_data = {
            "race_data_sync": {
                "standing_policy_digest": new_digest,
                "manifest_sha256": "d" * 64,
                "entry_sha256": "e" * 64,
                "owner_generation": 3,
            }
        }
        self.control.save(update_fields=("manifest_data",))

        decision = race_data_sync_admission.validate_data_sync_lifecycle_admission(
            event_id=self.event.pk,
            now=NOW,
            standing_policy=policy,
        )

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "enrollment_grant_conflict")
        second.delete()

    def test_manual_pause_is_rejected(self):
        self.control.manual_pause_reason = "operator hold"
        self.control.save(update_fields=("manual_pause_reason",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "manual_pause_present")

    def test_lifecycle_control_off_is_rejected(self):
        self.control.mode = models.RaceEventLifecycleMode.OFF
        self.control.save(update_fields=("mode",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "lifecycle_control_off")

    def test_lifecycle_evidence_drift_is_rejected(self):
        self.control.manifest_data = {"race_data_sync": {"standing_policy_digest": "9" * 64}}
        self.control.save(update_fields=("manifest_data",))

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "lifecycle_evidence_drift")

    def test_active_legacy_membership_is_authority_conflict(self):
        registry = models.RaceEventLifecycleEnforceRegistry.objects.create(
            root_sha256=REGISTRY_ROOT,
            generation=1,
            membership_sha256=REGISTRY_MEMBERSHIP,
            member_count=1,
            state="active",
            is_active=True,
            activation_id=REGISTRY_ACTIVATION,
            approved_commit="1" * 40,
            selector_scope={},
            scope_sha256="2" * 64,
            census_cutoff=NOW - timedelta(days=1),
            apply_expires_at=NOW + timedelta(days=1),
            runtime_valid_until=NOW + timedelta(days=35),
            activated_at=NOW,
        )
        models.RaceEventLifecycleEnforceMembership.objects.create(
            registry=registry,
            event=self.event,
            state="active",
            entry_sha256=REGISTRY_ENTRY,
            source_enrollment_sha256=LIFECYCLE_ENROLLMENT,
            schedule_generation=1,
            schedule_hash="0" * 64,
            country_region=self.event.country_region,
            timezone_name=self.event.timezone_name,
            frozen_snapshot={},
        )

        decision = self._validate()

        self.assertFalse(decision.admitted)
        self.assertEqual(decision.reason_code, "lifecycle_authority_conflict")

    def test_finished_event_with_legacy_membership_is_not_dual(self):
        registry = models.RaceEventLifecycleEnforceRegistry.objects.create(
            root_sha256=REGISTRY_ROOT,
            generation=1,
            membership_sha256=REGISTRY_MEMBERSHIP,
            member_count=1,
            state="active",
            is_active=True,
            activation_id=REGISTRY_ACTIVATION,
            approved_commit="1" * 40,
            selector_scope={},
            scope_sha256="2" * 64,
            census_cutoff=NOW - timedelta(days=1),
            apply_expires_at=NOW + timedelta(days=1),
            runtime_valid_until=NOW + timedelta(days=35),
            activated_at=NOW,
        )
        models.RaceEventLifecycleEnforceMembership.objects.create(
            registry=registry,
            event=self.event,
            state="active",
            entry_sha256=REGISTRY_ENTRY,
            source_enrollment_sha256=LIFECYCLE_ENROLLMENT,
            schedule_generation=1,
            schedule_hash="0" * 64,
            country_region=self.event.country_region,
            timezone_name=self.event.timezone_name,
            frozen_snapshot={},
        )
        self.event.status = models.RaceEventStatus.FINISHED
        self.event.save(update_fields=("status",))

        decision = self._validate()

        self.assertNotEqual(decision.reason_code, "lifecycle_authority_conflict")
