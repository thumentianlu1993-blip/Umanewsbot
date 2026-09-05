from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable import models
from stable.services import race_data_sync_lifecycle
from stable.services.race_data_sync_pipeline import resolve_race_data_provider_route
from stable.test_race_data_sync_policy_v2 import _policy_v2, _route
from stable.test_race_data_sync_providers import (
    _ROSTER_ALLOWED_FIELDS,
    REGISTRY_ACTIVATION,
    REGISTRY_MEMBERSHIP,
    REGISTRY_ROOT,
    ROOT,
    SHA,
)


NOW = datetime(2026, 8, 28, 4, 0, tzinfo=dt_timezone.utc)


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
class DataSyncLifecycleAdvanceTests(TestCase):
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
        self.policy_patcher = patch(
            "stable.services.race_data_sync_admission.load_standing_policy_file",
            return_value=self.policy,
        )
        self.policy_patcher.start()
        self.addCleanup(self.policy_patcher.stop)

    def _make_event(self, *, slug: str, race_datetime, status: str = models.RaceEventStatus.SCHEDULED):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=race_datetime,
            timezone_name="Asia/Tokyo",
            local_date=race_datetime.date(),
            status=status,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
            owner_manifest_sha256="d" * 64,
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id=f"jp-{slug}",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/terms",
            evidence_sha256="0" * 64,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=event,
            source_identity=source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest=self.policy_digest,
            route_digest=self.route.route_digest,
            event_snapshot_sha256="b" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="e" * 64,
            effective_at=NOW - timedelta(days=1),
        )
        return event

    def _control(self, event, *, mode=models.RaceEventLifecycleMode.ENFORCE, pause=""):
        return models.RaceEventLifecycleControl.objects.create(
            event=event,
            mode=mode,
            schedule_generation=1,
            next_refresh_at=NOW - timedelta(minutes=1),
            manual_pause_reason=pause,
            enrollment_manifest_sha256="d" * 64,
            manifest_data={
                "race_data_sync": {
                    "standing_policy_digest": self.policy_digest,
                    "manifest_sha256": "d" * 64,
                    "entry_sha256": "e" * 64,
                    "owner_generation": 1,
                }
            },
        )

    def test_advance_transitions_data_sync_event_without_legacy_membership(self):
        event = self._make_event(slug="advance-running", race_datetime=NOW - timedelta(minutes=1))
        self._control(event)

        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(now=NOW)

        self.assertEqual(stats["error"], 0, stats)
        self.assertEqual(stats["transitioned"], 1, stats)
        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.RUNNING)

    def test_advance_finishes_data_sync_event_after_t_plus_30(self):
        event = self._make_event(
            slug="advance-finish",
            race_datetime=NOW - timedelta(minutes=31),
            status=models.RaceEventStatus.RUNNING,
        )
        self._control(event)

        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(now=NOW)

        self.assertEqual(stats["error"], 0, stats)
        self.assertEqual(stats["transitioned"], 1, stats)
        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.FINISHED)

    def test_advance_late_admission_finishes_scheduled_event_without_fake_running(self):
        event = self._make_event(
            slug="advance-late",
            race_datetime=NOW - timedelta(minutes=45),
        )
        self._control(event)

        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(now=NOW)

        self.assertEqual(stats["error"], 0, stats)
        self.assertEqual(stats["transitioned"], 1, stats)
        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.FINISHED)
        transitions = models.RaceEventLifecycleTransition.objects.filter(
            event=event
        )
        self.assertEqual(transitions.count(), 1)
        self.assertNotEqual(
            transitions.first().to_status, models.RaceEventStatus.RUNNING
        )

    def test_advance_respects_manual_pause(self):
        event = self._make_event(slug="advance-paused", race_datetime=NOW - timedelta(minutes=1))
        self._control(event, pause="operator hold")

        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(now=NOW)

        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.SCHEDULED)
        self.assertEqual(stats["transitioned"], 0, stats)

    def test_advance_rejects_control_without_policy_evidence(self):
        event = self._make_event(slug="advance-drift", race_datetime=NOW - timedelta(minutes=1))
        control = self._control(event)
        control.manifest_data = {"race_data_sync": {"standing_policy_digest": "9" * 64}}
        control.save(update_fields=("manifest_data",))

        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(now=NOW)

        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.SCHEDULED)
        self.assertEqual(stats["transitioned"], 0, stats)
        self.assertEqual(stats["error"], 1, stats)


class DataSyncLifecycleReconciliationTests(DataSyncLifecycleAdvanceTests):
    def test_reconciliation_enforces_enrolled_event(self):
        event = self._make_event(
            slug="reconcile-enforce", race_datetime=NOW + timedelta(days=1)
        )
        self._control(event, mode=models.RaceEventLifecycleMode.OFF)

        stats = race_data_sync_lifecycle.reconcile_data_sync_lifecycle_admission(
            now=NOW, standing_policy=self.policy
        )

        self.assertEqual(stats["error"], 0, stats)
        self.assertEqual(stats["enforced"], 1, stats)
        control = models.RaceEventLifecycleControl.objects.get(event=event)
        self.assertEqual(control.mode, models.RaceEventLifecycleMode.ENFORCE)
        self.assertIsNotNone(control.next_refresh_at)

    def test_reconciliation_skips_manual_pause(self):
        event = self._make_event(
            slug="reconcile-paused", race_datetime=NOW + timedelta(days=1)
        )
        self._control(event, mode=models.RaceEventLifecycleMode.OFF, pause="hold")

        stats = race_data_sync_lifecycle.reconcile_data_sync_lifecycle_admission(
            now=NOW, standing_policy=self.policy
        )

        self.assertEqual(stats["enforced"], 0, stats)
        self.assertEqual(stats["skipped"], 1, stats)
        control = models.RaceEventLifecycleControl.objects.get(event=event)
        self.assertEqual(control.mode, models.RaceEventLifecycleMode.OFF)

    def test_reconciliation_is_bounded(self):
        for index in range(21):
            event = self._make_event(
                slug=f"reconcile-batch-{index:02d}",
                race_datetime=NOW + timedelta(days=1),
            )
            self._control(event, mode=models.RaceEventLifecycleMode.OFF)

        stats = race_data_sync_lifecycle.reconcile_data_sync_lifecycle_admission(
            now=NOW, standing_policy=self.policy
        )

        self.assertEqual(stats["selected"], 20, stats)
