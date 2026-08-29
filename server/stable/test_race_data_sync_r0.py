from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from stable import models
from stable.services import (
    race_data_sync_control,
    race_data_sync_enrollment,
    race_events,
)


NOW = datetime(2026, 8, 20, 4, 0, tzinfo=dt_timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
ROOT = Path(__file__).resolve().parents[2]


def audited_test_roster():
    from stable.services import race_data_sync_pipeline as pipeline

    entry = pipeline.RaceDataProviderRosterEntry(
        provider="jra",
        regions=("japan",),
        enabled_regions=("japan",),
        source_class="official_operator",
        adapter_status="implemented",
        transport_enabled=True,
        apply_enabled=True,
        contract_version="race-data-v2",
        contract_digest=SHA_A,
        allowed_fields=("off_time",),
        identity_namespaces=("jra-race-v1",),
        data_kinds=tuple(models.RaceDataSyncDataKind.values),
        enabled_data_kinds=tuple(models.RaceDataSyncDataKind.values),
        terminal_markers=("OFFICIAL",),
        allowed_hosts=("jra.example.test",),
        allowed_path_prefixes=("/race/",),
        request_budget=20,
        minimum_interval_seconds=2,
        automation_allowed=True,
        proof_digest=SHA_C,
    )
    registry_digest = pipeline._provider_roster_digest(
        schema_version=2,
        entries=(entry,),
    )
    roster = pipeline.RaceDataProviderRoster(
        schema_version=2,
        registry_digest=registry_digest,
        entries=(entry,),
    )
    binding = pipeline.resolve_race_data_provider_route
    with patch.object(pipeline, "build_race_data_provider_roster", return_value=roster):
        resolved = binding(
            provider="jra",
            region="japan",
            identity_namespace="jra-race-v1",
            data_kinds=models.RaceDataSyncDataKind.values,
        )
    assert resolved is not None
    return roster, resolved


def create_event(*, slug: str, region: str = models.RacingRegion.JAPAN):
    timezone_name = "Asia/Tokyo" if region == models.RacingRegion.JAPAN else "Europe/Paris"
    return models.RaceEvent.objects.create(
        year=2026,
        slug=slug,
        original_name=slug,
        chinese_name=slug,
        country_region=region,
        racecourse="Tokyo" if region == models.RacingRegion.JAPAN else "ParisLongchamp",
        grade_text="G1",
        normalized_grade=models.RaceGrade.G1,
        surface=models.RaceEventSurface.TURF,
        race_datetime=NOW + timedelta(days=1),
        timezone_name=timezone_name,
        local_date=date(2026, 8, 21),
        local_start_time=datetime(2026, 8, 21, 13, 0).time(),
        status=models.RaceEventStatus.SCHEDULED,
        visibility_status=models.RaceEventVisibility.PUBLISHED,
    )


class RaceDataSyncR0ModelContractTests(TestCase):
    def test_data_sync_is_a_distinct_projection_owner(self):
        self.assertEqual(models.RaceEventProjectionWriteOwner.DATA_SYNC, "data_sync")
        self.assertNotEqual(
            models.RaceEventProjectionWriteOwner.DATA_SYNC,
            models.RaceEventProjectionWriteOwner.LIVE,
        )

    def test_source_identity_is_unique_inside_region_and_namespace(self):
        event_jp = create_event(slug="identity-japan")
        event_fr = create_event(slug="identity-france", region=models.RacingRegion.FRANCE)
        first = models.RaceResultSourceIdentity.objects.create(
            event=event_jp,
            source_key="trusted",
            region_code="japan",
            identity_namespace="trusted-race-v1",
            external_race_id="same-external-id",
        )
        second = models.RaceResultSourceIdentity.objects.create(
            event=event_fr,
            source_key="trusted",
            region_code="france",
            identity_namespace="trusted-race-v1",
            external_race_id="same-external-id",
        )
        self.assertNotEqual(first.pk, second.pk)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.RaceResultSourceIdentity.objects.create(
                    event=create_event(slug="identity-japan-duplicate"),
                    source_key="trusted",
                    region_code="japan",
                    identity_namespace="trusted-race-v1",
                    external_race_id="same-external-id",
                )

    def test_checkpoint_and_snapshot_lease_uniqueness(self):
        event = create_event(slug="checkpoint-unique")
        tracking = models.RaceEventLiveTracking.objects.create(event=event)
        models.RaceEventLiveProviderCheckpoint.objects.create(
            tracking=tracking,
            source_key="jra",
            data_kind=models.RaceDataSyncDataKind.RACECARD,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.RaceEventLiveProviderCheckpoint.objects.create(
                    tracking=tracking,
                    source_key="jra",
                    data_kind=models.RaceDataSyncDataKind.RACECARD,
                )

        models.RaceDataSnapshotLease.objects.create(
            cache_key="jra:japan:2026-08-21",
            owner_token="owner-a",
            lease_expires_at=NOW + timedelta(minutes=1),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.RaceDataSnapshotLease.objects.create(
                    cache_key="jra:japan:2026-08-21",
                    owner_token="owner-b",
                    lease_expires_at=NOW + timedelta(minutes=1),
                )


class RaceDataSyncR0MigrationAdoptionTests(TransactionTestCase):
    migrate_from = [("stable", "0073_lifecycle_enforce_registry")]
    migrate_to = [("stable", "0074_race_data_sync_r0_control_plane")]
    migrate_latest = [("stable", "0075_race_data_source_priority_and_reported_position")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        RaceEvent = apps.get_model("stable", "RaceEvent")
        SourceIdentity = apps.get_model("stable", "RaceResultSourceIdentity")
        event = RaceEvent.objects.create(
            year=2026,
            edition_year=2026,
            slug="migration-adopt-source-scope",
            series_key="migration-adopt-source-scope",
            original_name="Migration Adopt Source Scope",
            chinese_name="迁移来源范围",
            country_region="japan",
            racecourse="Tokyo",
            grade_text="G1",
            surface="turf",
            local_date=date(2026, 8, 21),
            status="scheduled",
            visibility_status="published",
        )
        self.adopted_id = SourceIdentity.objects.create(
            event=event,
            source_key="jra",
            external_race_id="adopted",
            identity_fields={
                "region": "japan",
                "identity_namespace": "jra-race-v1",
            },
            automation_allowed=True,
        ).pk
        self.review_id = SourceIdentity.objects.create(
            event=event,
            source_key="trusted_reference",
            external_race_id="review-required",
            identity_fields={},
            automation_allowed=True,
        ).pk
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_latest)
        super().tearDown()

    def test_only_deterministic_scope_is_adopted(self):
        SourceIdentity = self.apps.get_model("stable", "RaceResultSourceIdentity")
        adopted = SourceIdentity.objects.get(pk=self.adopted_id)
        review = SourceIdentity.objects.get(pk=self.review_id)

        self.assertEqual(adopted.region_code, "japan")
        self.assertEqual(adopted.identity_namespace, "jra-race-v1")
        self.assertTrue(adopted.automation_allowed)
        self.assertEqual(review.region_code, "")
        self.assertEqual(review.identity_namespace, "")
        self.assertFalse(review.automation_allowed)
        self.assertEqual(
            review.identity_fields["race_data_sync_adoption"],
            "review_required",
        )


class RaceDataSourcePriorityMigrationTests(TransactionTestCase):
    migrate_from = [("stable", "0074_race_data_sync_r0_control_plane")]
    migrate_to = [("stable", "0075_race_data_source_priority_and_reported_position")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        RaceEvent = old_apps.get_model("stable", "RaceEvent")
        RaceEventResult = old_apps.get_model("stable", "RaceEventResult")
        event = RaceEvent.objects.create(
            year=2026,
            edition_year=2026,
            slug="migration-reported-position",
            series_key="migration-reported-position",
            original_name="Migration Reported Position",
            chinese_name="迁移对外名次",
            country_region="japan",
            racecourse="Tokyo",
            grade_text="G1",
            surface="turf",
            local_date=date(2026, 8, 21),
            status="finished",
            visibility_status="published",
        )
        self.unknown_id = RaceEventResult.objects.create(
            event=event,
            finish_position=7,
            official_finish_position=None,
            horse_name="Unknown Finish",
        ).pk
        self.official_id = RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            official_finish_position=3,
            horse_name="Official Third",
        ).pk
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.migrate_to)
        super().tearDown()

    def test_unknown_reported_position_is_not_fabricated_from_internal_order(self):
        RaceEventResult = self.apps.get_model("stable", "RaceEventResult")
        unknown = RaceEventResult.objects.get(pk=self.unknown_id)
        official = RaceEventResult.objects.get(pk=self.official_id)

        self.assertIsNone(unknown.reported_finish_position)
        self.assertEqual(official.reported_finish_position, 3)


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan",),
    RACE_DATA_SYNC_ENABLED_FIELDS=("off_time",),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard"),
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=False,
    RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False,
    RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=False,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=False,
)
class RaceDataSyncR0FlagContractTests(SimpleTestCase):
    def test_extended_flags_preserve_slice_a_namespace(self):
        from stable.services.race_data_sync_pipeline import RaceDataSyncFlags

        flags = RaceDataSyncFlags.from_settings()
        self.assertTrue(flags.scheduler_enabled)
        self.assertFalse(flags.allow_network)
        self.assertTrue(flags.allows_data_kind("racecard"))
        self.assertFalse(flags.allows_data_kind("result"))
        self.assertTrue(flags.apply_enabled_for("racecard"))
        self.assertFalse(flags.apply_enabled_for("race_time"))
        self.assertFalse(flags.apply_enabled_for("result"))

    def test_celery_route_and_beat_schedule_are_isolated(self):
        from app import settings as app_settings

        self.assertEqual(
            app_settings.CELERY_TASK_ROUTES[
                "stable.tasks.sync_race_event_provider_task"
            ],
            {"queue": "race_sync_v2"},
        )
        self.assertEqual(
            app_settings.CELERY_TASK_ROUTES[
                "stable.tasks.discover_future_race_data_sync_task"
            ],
            {"queue": "race_sync_v2"},
        )
        schedule = app_settings.build_race_data_sync_beat_schedule(
            scheduler_enabled=True,
            future_discovery_enabled=True,
            lifecycle_apply_enabled=True,
        )
        self.assertEqual(
            schedule["select-due-race-data-sync"]["options"]["queue"],
            "celery",
        )
        self.assertEqual(
            schedule["discover-future-race-data-sync"]["options"]["queue"],
            "race_sync_v2",
        )
        self.assertEqual(
            schedule["advance-race-data-sync-lifecycle"]["options"]["queue"],
            "celery",
        )
        self.assertEqual(
            schedule["monitor-race-data-sync-result-slo"]["options"]["queue"],
            "celery",
        )
        self.assertEqual(
            schedule["cleanup-race-data-sync-artifacts"]["options"]["queue"],
            "race_sync_v2",
        )
        self.assertEqual(
            app_settings.CELERY_TASK_ROUTES[
                "stable.tasks.cleanup_race_data_sync_artifacts_task"
            ],
            {"queue": "race_sync_v2"},
        )

    def test_slice_a_roster_v2_exposes_identity_and_data_kind_contract(self):
        from stable.services.race_data_sync_pipeline import (
            build_race_data_provider_roster,
        )

        roster = build_race_data_provider_roster()
        self.assertEqual(roster.schema_version, 2)
        for entry in roster.entries:
            with self.subTest(provider=entry.provider):
                self.assertTrue(entry.identity_namespaces)
                expected_kinds = (
                    {"result"}
                    if entry.provider
                    in {"sporting_life", "zeturf", "horse_racing_nation"}
                    else {"race_time", "racecard", "result"}
                )
                self.assertEqual(set(entry.data_kinds), expected_kinds)
                if entry.adapter_status == "implemented" and entry.proof_digest:
                    self.assertRegex(entry.proof_digest, r"\A[0-9a-f]{64}\Z")

                else:
                    self.assertIn(entry.proof_digest, {"", entry.contract_digest})
        self.assertIsNone(
            roster.resolve_route(
                provider="jra",
                region="japan_jra",
                identity_namespace="jra-race-v1",
                data_kind="result",
            )
        )
        self.assertIsNone(
            roster.resolve_route(
                provider="the_racing_api",
                region="france",
                identity_namespace="the_racing_api-race-v1",
                data_kind="racecard",
            ),
            "a route without audited host/path/budget must stay ineligible",
        )

    @override_settings(
        RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
        RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
        RACE_DATA_RAW_CLEANUP_MAX_BYTES=64,
    )
    def test_cleanup_task_shares_one_byte_budget_across_artifact_classes(self):
        from stable.tasks import cleanup_race_data_sync_artifacts_task

        raw_outcome = SimpleNamespace(
            cleaned=2,
            cleaned_bytes=40,
            held=0,
            skipped=0,
        )
        snapshot_outcome = SimpleNamespace(
            cleaned=1,
            cleaned_bytes=24,
            skipped=0,
        )
        with (
            patch(
                "stable.services.race_data_sync_pipeline.cleanup_expired_race_data_raw_payloads",
                return_value=raw_outcome,
            ) as cleanup_raw,
            patch(
                "stable.services.race_data_sync_providers.cleanup_expired_shared_snapshots",
                return_value=snapshot_outcome,
            ) as cleanup_snapshots,
        ):
            result = cleanup_race_data_sync_artifacts_task()

        self.assertEqual(result["raw_cleaned_bytes"], 40)
        self.assertEqual(result["snapshot_cleaned_bytes"], 24)
        self.assertEqual(cleanup_raw.call_args.kwargs["max_bytes"], 64)
        self.assertEqual(cleanup_snapshots.call_args.kwargs["max_bytes"], 24)


class RaceDataSyncEnrollmentControlTests(TestCase):
    def setUp(self):
        self.roster, self.route = audited_test_roster()
        self.roster_patcher = patch(
            "stable.services.race_data_sync_pipeline.build_race_data_provider_roster",
            return_value=self.roster,
        )
        self.roster_patcher.start()
        self.addCleanup(self.roster_patcher.stop)
        self.event = create_event(slug="r0-enrollment")
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="jra",
            region_code="japan",
            identity_namespace="jra-race-v1",
            external_race_id="20260821-tokyo-11",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://jra.example.test/reviewed-proof",
            evidence_sha256=SHA_A,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )

    def _acquire(self):
        return race_data_sync_control.acquire_enrollment(
            event_id=self.event.pk,
            source_identity_id=self.source.pk,
            standing_policy_digest=SHA_A,
            route_digest=self.route.route_digest,
            event_snapshot_sha256=SHA_C,
            manifest_sha256=SHA_D,
            entry_sha256=SHA_A,
            expected_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
            expected_owner_generation=0,
            data_kinds=("race_time", "racecard", "result"),
            now=NOW,
        )

    def test_acquire_replay_and_disenroll_owner_cas(self):
        acquired = self._acquire()
        self.assertEqual(acquired.action, "acquired")
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.write_owner,
            models.RaceEventProjectionWriteOwner.DATA_SYNC,
        )
        self.assertEqual(self.control.owner_generation, 1)
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        self.assertEqual(enrollment.state, models.RaceDataSyncEnrollmentState.ENROLLED)
        self.assertEqual(enrollment.enrollment_generation, 1)
        self.assertEqual(
            set(enrollment.event.live_tracking.provider_checkpoints.values_list("data_kind", flat=True)),
            {"race_time", "racecard", "result"},
        )

        replay = race_data_sync_control.acquire_enrollment(
            event_id=self.event.pk,
            source_identity_id=self.source.pk,
            standing_policy_digest=SHA_A,
            route_digest=self.route.route_digest,
            event_snapshot_sha256=SHA_C,
            manifest_sha256=SHA_D,
            entry_sha256=SHA_A,
            expected_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            expected_owner_generation=1,
            data_kinds=("race_time", "racecard", "result"),
            now=NOW,
        )
        self.assertEqual(replay.action, "replay")

        released = race_data_sync_control.disenroll(
            event_id=self.event.pk,
            expected_manifest_sha256=SHA_D,
            expected_owner_generation=1,
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(released.action, "released")
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.write_owner,
            models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        self.assertEqual(self.control.owner_generation, 2)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.state, models.RaceDataSyncEnrollmentState.RETIRED)
        self.assertFalse(enrollment.event.live_tracking.tracking_enabled)

    def test_acquire_preserves_existing_shadow_mode_and_manual_pause(self):
        lifecycle = models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.SHADOW,
            next_refresh_at=NOW + timedelta(hours=1),
            schedule_generation=7,
            manual_pause_reason="operator pause",
            enrollment_manifest_sha256=SHA_C,
            manifest_data={"existing": True},
        )

        acquired = self._acquire()

        self.assertEqual(acquired.action, "acquired")
        lifecycle.refresh_from_db()
        self.assertEqual(lifecycle.mode, models.RaceEventLifecycleMode.SHADOW)
        self.assertEqual(lifecycle.next_refresh_at, NOW + timedelta(hours=1))
        self.assertEqual(lifecycle.schedule_generation, 7)
        self.assertEqual(lifecycle.manual_pause_reason, "operator pause")
        self.assertEqual(lifecycle.enrollment_manifest_sha256, SHA_C)
        self.assertTrue(lifecycle.manifest_data["existing"])
        self.assertEqual(
            lifecycle.manifest_data["race_data_sync"]["manifest_sha256"],
            SHA_D,
        )

        released = race_data_sync_control.disenroll(
            event_id=self.event.pk,
            expected_manifest_sha256=SHA_D,
            expected_owner_generation=1,
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(released.action, "released")
        lifecycle.refresh_from_db()
        self.assertEqual(lifecycle.mode, models.RaceEventLifecycleMode.SHADOW)
        self.assertEqual(lifecycle.enrollment_manifest_sha256, SHA_C)
        self.assertTrue(lifecycle.manifest_data["existing"])
        self.assertNotIn("race_data_sync", lifecycle.manifest_data)

    def test_acquire_creates_missing_lifecycle_control_closed(self):
        acquired = self._acquire()

        self.assertEqual(acquired.action, "acquired")
        lifecycle = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.assertEqual(lifecycle.mode, models.RaceEventLifecycleMode.OFF)
        self.assertIsNone(lifecycle.next_refresh_at)

    def test_legacy_owner_and_stale_generation_fail_closed(self):
        self.control.write_owner = models.RaceEventProjectionWriteOwner.LIVE
        self.control.owner_generation = 4
        self.control.save(update_fields=("write_owner", "owner_generation"))
        result = self._acquire()
        self.assertEqual(result.action, "rejected")
        self.assertEqual(result.reason_code, "writer_owner_conflict")
        self.assertFalse(models.RaceDataSyncEnrollment.objects.exists())

        self.control.write_owner = models.RaceEventProjectionWriteOwner.UNMANAGED
        self.control.save(update_fields=("write_owner",))
        stale = self._acquire()
        self.assertEqual(stale.reason_code, "owner_cas_stale")
        self.assertFalse(models.RaceDataSyncEnrollment.objects.exists())

    def test_failed_provider_task_releases_exact_parent_claim(self):
        self._acquire()
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]

        from stable.tasks import sync_race_event_provider_task

        with (
            override_settings(
                RACE_DATA_SYNC_ENABLED=True,
                RACE_DATA_SYNC_ALLOW_NETWORK=False,
            ),
            patch("stable.tasks.timezone.now", return_value=NOW + timedelta(seconds=1)),
        ):
            result = sync_race_event_provider_task(
                event_id=claim.event_id,
                expected_enrollment_generation=claim.enrollment_generation,
                expected_owner_generation=claim.owner_generation,
                expected_claim_generation=claim.claim_generation,
                attempt_token=claim.attempt_token,
                data_kinds=claim.data_kinds,
                checkpoint_plan=claim.checkpoint_plan,
                expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
                expected_plan_sha256=claim.plan_sha256,
            )

        self.assertEqual(result["reason"], "network_disabled")
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, "")
        self.assertIsNone(tracking.claim_expires_at)
        self.assertEqual(
            set(
                tracking.provider_checkpoints.values_list(
                    "consecutive_failures", flat=True
                )
            ),
            {1},
        )
        self.assertEqual(
            tracking.next_poll_at,
            NOW + timedelta(minutes=5, seconds=1),
        )

    def test_invalid_capacity_configuration_blocks_before_provider_execution(self):
        self._acquire()
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("racecard",),
        )[0]
        from stable.tasks import sync_race_event_provider_task

        with (
            override_settings(
                RACE_DATA_SYNC_ENABLED=True,
                RACE_DATA_SYNC_ALLOW_NETWORK=True,
                RACE_DATA_RAW_MAX_COMPRESSED_BYTES=0,
                RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=0,
                RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=0,
                RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=0,
                RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=0,
                RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=0,
                RACE_DATA_RAW_MIN_FREE_DISK_BYTES=0,
                RACE_DATA_RAW_CLEANUP_MAX_ROWS=0,
                RACE_DATA_RAW_CLEANUP_MAX_BYTES=0,
                RACE_DATA_RAW_HOLD_ALERT_BYTES=0,
            ),
            patch("stable.tasks.timezone.now", return_value=NOW + timedelta(seconds=1)),
        ):
            result = sync_race_event_provider_task(
                event_id=claim.event_id,
                expected_enrollment_generation=claim.enrollment_generation,
                expected_owner_generation=claim.owner_generation,
                expected_claim_generation=claim.claim_generation,
                attempt_token=claim.attempt_token,
                data_kinds=claim.data_kinds,
                checkpoint_plan=claim.checkpoint_plan,
                expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
                expected_plan_sha256=claim.plan_sha256,
            )
        self.assertEqual(result["reason"], "artifact_capacity_config_invalid")
        self.assertEqual(result["claim_action"], "failed")

    def test_claim_freezes_checkpoint_versions_route_and_plan_digest(self):
        self._acquire()
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]

        self.assertEqual(claim.enrollment_entry_sha256, SHA_A)
        self.assertEqual(claim.route_digest, self.route.route_digest)
        self.assertRegex(claim.plan_sha256, r"\A[0-9a-f]{64}\Z")
        self.assertEqual(
            claim.checkpoint_plan,
            (
                {"source_key": "jra", "data_kind": "race_time", "lock_version": 0},
                {"source_key": "jra", "data_kind": "racecard", "lock_version": 0},
                {"source_key": "jra", "data_kind": "result", "lock_version": 0},
            ),
        )

        checkpoint = models.RaceEventLiveProviderCheckpoint.objects.get(
            tracking__event=self.event,
            data_kind=models.RaceDataSyncDataKind.RESULT,
        )
        checkpoint.lock_version += 1
        checkpoint.save(update_fields=("lock_version",))
        decision = race_data_sync_control.fail_race_data_sync_claim(
            event_id=claim.event_id,
            expected_enrollment_generation=claim.enrollment_generation,
            expected_owner_generation=claim.owner_generation,
            expected_claim_generation=claim.claim_generation,
            attempt_token=claim.attempt_token,
            data_kinds=claim.data_kinds,
            checkpoint_plan=claim.checkpoint_plan,
            expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
            expected_plan_sha256=claim.plan_sha256,
            reason_code="fixture_failure",
            retry_at=NOW + timedelta(minutes=5),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(decision.reason_code, "checkpoint_cas_stale")
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, claim.attempt_token)

    def test_successful_claim_schedules_dynamic_successors_and_releases_parent(self):
        self._acquire()
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]
        decision = race_data_sync_control.complete_race_data_sync_claim(
            event_id=claim.event_id,
            expected_enrollment_generation=claim.enrollment_generation,
            expected_owner_generation=claim.owner_generation,
            expected_claim_generation=claim.claim_generation,
            attempt_token=claim.attempt_token,
            checkpoint_plan=claim.checkpoint_plan,
            expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
            expected_plan_sha256=claim.plan_sha256,
            observation_hashes={"racecard": SHA_B},
            source_updated_at_by_kind={"racecard": NOW},
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(decision.action, "complete")
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, "")
        self.assertIsNone(tracking.claim_expires_at)
        checkpoints = {
            checkpoint.data_kind: checkpoint
            for checkpoint in tracking.provider_checkpoints.all()
        }
        self.assertEqual(
            checkpoints["racecard"].next_poll_at,
            NOW + timedelta(hours=1, seconds=1),
        )
        self.assertEqual(checkpoints["racecard"].last_observation_hash, SHA_B)
        self.assertEqual(checkpoints["racecard"].consecutive_failures, 0)
        self.assertEqual(
            checkpoints["result"].next_poll_at,
            self.event.race_datetime + timedelta(minutes=3),
        )
        self.assertEqual(tracking.next_poll_at, NOW + timedelta(hours=1, seconds=1))

    def test_postponed_claim_does_not_keep_polling_obsolete_result_time(self):
        self._acquire()
        self.event.status = models.RaceEventStatus.POSTPONED
        self.event.save(update_fields=("status", "updated_at"))
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]

        decision = race_data_sync_control.complete_race_data_sync_claim(
            event_id=claim.event_id,
            expected_enrollment_generation=claim.enrollment_generation,
            expected_owner_generation=claim.owner_generation,
            expected_claim_generation=claim.claim_generation,
            attempt_token=claim.attempt_token,
            checkpoint_plan=claim.checkpoint_plan,
            expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
            expected_plan_sha256=claim.plan_sha256,
            now=NOW + timedelta(seconds=1),
        )

        self.assertEqual(decision.action, "complete")
        checkpoints = {
            checkpoint.data_kind: checkpoint.next_poll_at
            for checkpoint in models.RaceEventLiveProviderCheckpoint.objects.filter(
                tracking__event=self.event
            )
        }
        self.assertEqual(
            checkpoints[models.RaceDataSyncDataKind.RACE_TIME],
            NOW + timedelta(hours=12, seconds=1),
        )
        self.assertEqual(
            checkpoints[models.RaceDataSyncDataKind.RACECARD],
            NOW + timedelta(hours=12, seconds=1),
        )
        self.assertIsNone(checkpoints[models.RaceDataSyncDataKind.RESULT])

    def test_stale_provider_task_cannot_release_newer_claim(self):
        self._acquire()
        first = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]
        second = race_data_sync_control.claim_due_enrollments(
            now=NOW + timedelta(seconds=61),
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]

        decision = race_data_sync_control.fail_race_data_sync_claim(
            event_id=first.event_id,
            expected_enrollment_generation=first.enrollment_generation,
            expected_owner_generation=first.owner_generation,
            expected_claim_generation=first.claim_generation,
            attempt_token=first.attempt_token,
            data_kinds=first.data_kinds,
            reason_code="stale-attempt",
            retry_at=NOW + timedelta(minutes=5),
            now=NOW + timedelta(seconds=62),
        )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_cas_stale")
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, second.attempt_token)

    def test_expired_provider_task_cannot_complete_or_release_claim(self):
        self._acquire()
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("race_time", "racecard", "result"),
        )[0]

        completed = race_data_sync_control.complete_race_data_sync_claim(
            event_id=claim.event_id,
            expected_enrollment_generation=claim.enrollment_generation,
            expected_owner_generation=claim.owner_generation,
            expected_claim_generation=claim.claim_generation,
            attempt_token=claim.attempt_token,
            checkpoint_plan=claim.checkpoint_plan,
            expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
            expected_plan_sha256=claim.plan_sha256,
            now=NOW + timedelta(seconds=60),
        )
        failed = race_data_sync_control.fail_race_data_sync_claim(
            event_id=claim.event_id,
            expected_enrollment_generation=claim.enrollment_generation,
            expected_owner_generation=claim.owner_generation,
            expected_claim_generation=claim.claim_generation,
            attempt_token=claim.attempt_token,
            data_kinds=claim.data_kinds,
            checkpoint_plan=claim.checkpoint_plan,
            expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
            expected_plan_sha256=claim.plan_sha256,
            reason_code="late-worker",
            retry_at=NOW + timedelta(minutes=5),
            now=NOW + timedelta(seconds=60),
        )

        self.assertEqual(completed.reason_code, "claim_expired")
        self.assertEqual(failed.reason_code, "claim_expired")
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, claim.attempt_token)
        self.assertEqual(
            set(
                tracking.provider_checkpoints.values_list(
                    "consecutive_failures", flat=True
                )
            ),
            {0},
        )

    def test_direct_admission_rejects_expired_or_route_drifted_source(self):
        self.source.proof_network_allowed = False
        self.source.save(update_fields=("proof_network_allowed",))
        unproved = self._acquire()
        self.assertEqual(unproved.reason_code, "source_identity_not_admitted")

        self.source.proof_network_allowed = True
        self.source.valid_until = NOW
        self.source.save(update_fields=("proof_network_allowed", "valid_until"))
        expired = self._acquire()
        self.assertEqual(expired.reason_code, "source_identity_expired")

        self.source.valid_until = NOW + timedelta(days=1)
        self.source.registry_digest = SHA_C
        self.source.save(update_fields=("valid_until", "registry_digest"))
        drifted = self._acquire()
        self.assertEqual(drifted.reason_code, "source_route_drift")

    def test_control_acquire_rejects_unavailable_current_roster_route(self):
        with patch(
            "stable.services.race_data_sync_pipeline.resolve_race_data_provider_route",
            return_value=None,
        ):
            decision = self._acquire()
        self.assertEqual(decision.reason_code, "provider_route_unavailable")
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.write_owner,
            models.RaceEventProjectionWriteOwner.UNMANAGED,
        )

    def test_claim_truth_table_filters_provider_region_and_data_kind(self):
        self._acquire()
        self.assertEqual(
            race_data_sync_control.claim_due_enrollments(
                now=NOW,
                batch_size=10,
                ttl_seconds=60,
                enabled_providers=("other",),
                enabled_regions=("japan",),
                enabled_data_kinds=("racecard",),
            ),
            (),
        )
        self.assertEqual(
            race_data_sync_control.claim_due_enrollments(
                now=NOW,
                batch_size=10,
                ttl_seconds=60,
                enabled_providers=("jra",),
                enabled_regions=("france",),
                enabled_data_kinds=("racecard",),
            ),
            (),
        )
        claim = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("racecard",),
        )[0]
        self.assertEqual(claim.data_kinds, ("racecard",))

    def test_disabled_due_checkpoint_cannot_starve_enabled_due_event(self):
        self._acquire()
        first_tracking = self.event.live_tracking
        first_tracking.provider_checkpoints.filter(
            data_kind=models.RaceDataSyncDataKind.RACECARD
        ).update(next_poll_at=NOW + timedelta(hours=1))

        second_event = create_event(slug="r0-enabled-due-second")
        models.RaceEventProjectionControl.objects.create(
            event=second_event,
            write_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        second_source = models.RaceResultSourceIdentity.objects.create(
            event=second_event,
            source_key="jra",
            region_code="japan",
            identity_namespace="jra-race-v1",
            external_race_id="20260821-tokyo-12",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://jra.example.test/reviewed-proof",
            evidence_sha256=SHA_A,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )
        acquired = race_data_sync_control.acquire_enrollment(
            event_id=second_event.pk,
            source_identity_id=second_source.pk,
            standing_policy_digest=SHA_A,
            route_digest=self.route.route_digest,
            event_snapshot_sha256=SHA_C,
            manifest_sha256=SHA_D,
            entry_sha256=SHA_B,
            expected_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
            expected_owner_generation=0,
            data_kinds=("race_time", "racecard", "result"),
            now=NOW,
        )
        self.assertEqual(acquired.action, "acquired")

        claims = race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=1,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("racecard",),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].event_id, second_event.pk)
        self.assertEqual(claims[0].data_kinds, ("racecard",))

    def test_reviewed_legacy_transfer_requires_closed_drained_baseline(self):
        self.control.write_owner = models.RaceEventProjectionWriteOwner.LIVE
        self.control.owner_generation = 7
        self.control.owner_manifest_sha256 = SHA_C
        self.control.save(
            update_fields=(
                "write_owner",
                "owner_generation",
                "owner_manifest_sha256",
            )
        )
        tracking = models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=False,
        )
        legacy_other_source_checkpoint = (
            models.RaceEventLiveProviderCheckpoint.objects.create(
                tracking=tracking,
                source_key="legacy-other-source",
                data_kind=models.RaceDataSyncDataKind.RESULT,
                next_poll_at=NOW,
            )
        )
        baseline = race_data_sync_control.build_legacy_transfer_baseline(
            event_id=self.event.pk
        )
        receipt = {
            "schema_version": 1,
            "captured_at": (NOW - timedelta(minutes=2)).isoformat(),
            "legacy_runtime": {
                "scheduler_enabled": False,
                "monitor_enabled": False,
                "allow_network": False,
                "racecard_apply_enabled": False,
                "result_apply_enabled": False,
            },
            "queues": {
                "race_live": {
                    "drained": True,
                    "message_count": 0,
                    "active_claim_count": 0,
                },
                "race_sync_v2": {
                    "drained": True,
                    "message_count": 0,
                    "active_claim_count": 0,
                },
            },
        }
        forged = json.loads(json.dumps(receipt))
        forged["legacy_runtime"]["scheduler_enabled"] = "false"
        with self.assertRaisesMessage(ValueError, "runtime is not closed"):
            race_data_sync_control.build_legacy_transfer_manifest(
                event_id=self.event.pk,
                source_identity_id=self.source.pk,
                standing_policy_digest=SHA_A,
                route_digest=self.route.route_digest,
                event_snapshot_sha256=SHA_C,
                expected_live_manifest_sha256=SHA_C,
                expected_owner_generation=7,
                expected_projection_baseline_sha256=baseline,
                data_kinds=("racecard",),
                candidate_commit="1" * 40,
                created_at=NOW,
                apply_expires_at=NOW + timedelta(minutes=30),
                runtime_receipt=forged,
            )

        manifest = race_data_sync_control.build_legacy_transfer_manifest(
            event_id=self.event.pk,
            source_identity_id=self.source.pk,
            standing_policy_digest=SHA_A,
            route_digest=self.route.route_digest,
            event_snapshot_sha256=SHA_C,
            expected_live_manifest_sha256=SHA_C,
            expected_owner_generation=7,
            expected_projection_baseline_sha256=baseline,
            data_kinds=("racecard",),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(minutes=30),
            runtime_receipt=receipt,
        )
        stale_receipt = json.loads(json.dumps(receipt))
        stale_receipt["captured_at"] = (NOW - timedelta(minutes=16)).isoformat()
        with self.assertRaisesMessage(ValueError, "runtime receipt is stale"):
            race_data_sync_control.build_legacy_transfer_manifest(
                event_id=self.event.pk,
                source_identity_id=self.source.pk,
                standing_policy_digest=SHA_A,
                route_digest=self.route.route_digest,
                event_snapshot_sha256=SHA_C,
                expected_live_manifest_sha256=SHA_C,
                expected_owner_generation=7,
                expected_projection_baseline_sha256=baseline,
                data_kinds=("racecard",),
                candidate_commit="1" * 40,
                created_at=NOW,
                apply_expires_at=NOW + timedelta(minutes=30),
                runtime_receipt=stale_receipt,
            )
        canonical = lambda value: json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_raw = canonical(manifest)
        receipt_raw = canonical(receipt)
        manifest_raw_sha256 = hashlib.sha256(manifest_raw).hexdigest()
        receipt_raw_sha256 = hashlib.sha256(receipt_raw).hexdigest()
        approval = race_data_sync_control.build_legacy_transfer_approval(
            event_id=self.event.pk,
            candidate_commit="1" * 40,
            transfer_manifest_raw_sha256=manifest_raw_sha256,
            transfer_manifest_sha256=manifest["manifest_sha256"],
            runtime_receipt_raw_sha256=receipt_raw_sha256,
            runtime_receipt_sha256=manifest["runtime_receipt_sha256"],
            approved_by="reviewer@example.test",
            approved_at=NOW + timedelta(minutes=1),
            apply_expires_at=NOW + timedelta(minutes=30),
        )
        approval_raw = canonical(approval)
        approval_raw_sha256 = hashlib.sha256(approval_raw).hexdigest()
        preapproval = race_data_sync_control.build_legacy_transfer_approval(
            event_id=self.event.pk,
            candidate_commit="1" * 40,
            transfer_manifest_raw_sha256=manifest_raw_sha256,
            transfer_manifest_sha256=manifest["manifest_sha256"],
            runtime_receipt_raw_sha256=receipt_raw_sha256,
            runtime_receipt_sha256=manifest["runtime_receipt_sha256"],
            approved_by="reviewer@example.test",
            approved_at=NOW - timedelta(minutes=1),
            apply_expires_at=NOW + timedelta(minutes=30),
        )
        preapproval_raw = canonical(preapproval)
        preapproval_raw_sha256 = hashlib.sha256(preapproval_raw).hexdigest()
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "transfer.json"
            receipt_path = Path(tmp) / "runtime-receipt.json"
            approval_path = Path(tmp) / "approval.json"
            preapproval_path = Path(tmp) / "preapproval.json"
            manifest_path.write_bytes(manifest_raw)
            receipt_path.write_bytes(receipt_raw)
            approval_path.write_bytes(approval_raw)
            preapproval_path.write_bytes(preapproval_raw)

            with override_settings(
                RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256=SHA_D,
                RACE_LIVE_RUNNER_MODE="disabled",
            ):
                with self.assertRaisesMessage(
                    ValueError, "not the configured trust root"
                ):
                    race_data_sync_control.transfer_legacy_enrollment(
                        event_id=self.event.pk,
                        transfer_manifest_path=manifest_path,
                        runtime_receipt_path=receipt_path,
                        approval_path=approval_path,
                        current_commit="1" * 40,
                        now=NOW + timedelta(minutes=2),
                    )
            self.control.refresh_from_db()
            tracking.refresh_from_db()
            self.assertEqual(
                self.control.write_owner,
                models.RaceEventProjectionWriteOwner.LIVE,
            )
            self.assertFalse(tracking.tracking_enabled)

            with override_settings(
                RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256=(
                    approval_raw_sha256
                ),
                RACE_LIVE_RUNNER_MODE="disabled",
                RACE_DATA_SYNC_ENABLED=True,
            ):
                with self.assertRaisesMessage(
                    ValueError, "runtime is currently enabled"
                ):
                    race_data_sync_control.transfer_legacy_enrollment(
                        event_id=self.event.pk,
                        transfer_manifest_path=manifest_path,
                        runtime_receipt_path=receipt_path,
                        approval_path=approval_path,
                        current_commit="1" * 40,
                        now=NOW + timedelta(minutes=2),
                    )

            with override_settings(
                RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256=(
                    preapproval_raw_sha256
                ),
                RACE_LIVE_RUNNER_MODE="disabled",
            ):
                with self.assertRaisesMessage(
                    ValueError, "manifest is outside its apply window"
                ):
                    race_data_sync_control.transfer_legacy_enrollment(
                        event_id=self.event.pk,
                        transfer_manifest_path=manifest_path,
                        runtime_receipt_path=receipt_path,
                        approval_path=preapproval_path,
                        current_commit="1" * 40,
                        now=NOW + timedelta(minutes=2),
                    )

            with override_settings(
                RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256=(
                    approval_raw_sha256
                ),
                RACE_LIVE_RUNNER_MODE="disabled",
            ):
                transferred = race_data_sync_control.transfer_legacy_enrollment(
                    event_id=self.event.pk,
                    transfer_manifest_path=manifest_path,
                    runtime_receipt_path=receipt_path,
                    approval_path=approval_path,
                    current_commit="1" * 40,
                    now=NOW + timedelta(minutes=2),
                )
        self.assertEqual(transferred.action, "transferred")
        self.control.refresh_from_db()
        tracking.refresh_from_db()
        self.assertEqual(
            self.control.write_owner,
            models.RaceEventProjectionWriteOwner.DATA_SYNC,
        )
        self.assertEqual(self.control.owner_generation, 8)
        self.assertTrue(tracking.tracking_enabled)
        legacy_other_source_checkpoint.refresh_from_db()
        self.assertIsNone(legacy_other_source_checkpoint.next_poll_at)


class RaceDataSnapshotLeaseControlTests(TestCase):
    def _args(self, **overrides):
        values = {
            "provider": "jra",
            "region": "japan",
            "scope_key": "2026-08-21",
            "data_kind": "racecard",
            "registry_digest": SHA_B,
        }
        values.update(overrides)
        return values

    def _manifest(self, *, artifact_sha256=SHA_A, **overrides):
        args = self._args(**overrides)
        return {
            "schema_version": 1,
            "complete": True,
            "cache_key": race_data_sync_control.build_snapshot_cache_key(**args),
            "artifact_sha256": artifact_sha256,
            "registry_digest": args["registry_digest"],
            "fetched_at": NOW.isoformat(),
            "page_count": 1,
            "item_count": 12,
        }

    def test_claim_busy_expired_takeover_and_publish(self):
        first = race_data_sync_control.claim_snapshot_lease(
            **self._args(),
            owner_token="owner-a",
            now=NOW,
            ttl_seconds=60,
        )
        self.assertEqual(first.action, "acquired")
        busy = race_data_sync_control.claim_snapshot_lease(
            **self._args(),
            owner_token="owner-b",
            now=NOW + timedelta(seconds=30),
            ttl_seconds=60,
        )
        self.assertEqual(busy.action, "busy")
        takeover = race_data_sync_control.claim_snapshot_lease(
            **self._args(),
            owner_token="owner-b",
            now=NOW + timedelta(seconds=61),
            ttl_seconds=60,
        )
        self.assertEqual(takeover.action, "taken_over")
        self.assertEqual(takeover.generation, 2)

        stale = race_data_sync_control.publish_snapshot(
            **self._args(),
            owner_token="owner-a",
            expected_generation=1,
            artifact_sha256=SHA_A,
            manifest=self._manifest(),
            now=NOW + timedelta(seconds=62),
        )
        self.assertEqual(stale.action, "rejected")
        published = race_data_sync_control.publish_snapshot(
            **self._args(),
            owner_token="owner-b",
            expected_generation=2,
            artifact_sha256=SHA_A,
            manifest=self._manifest(),
            now=NOW + timedelta(seconds=62),
        )
        self.assertEqual(published.action, "published")
        lease = models.RaceDataSnapshotLease.objects.get()
        self.assertEqual(lease.state, models.RaceDataSnapshotLeaseState.COMPLETE)
        self.assertEqual(lease.artifact_sha256, SHA_A)
        self.assertEqual(
            race_data_sync_control.claim_snapshot_lease(
                **self._args(),
                owner_token="owner-c",
                now=NOW + timedelta(seconds=211),
                ttl_seconds=60,
            ).action,
            "complete",
        )
        refreshed = race_data_sync_control.claim_snapshot_lease(
            **self._args(),
            owner_token="owner-c",
            now=NOW + timedelta(seconds=212),
            ttl_seconds=60,
        )
        self.assertEqual(refreshed.action, "taken_over")
        lease.refresh_from_db()
        self.assertEqual(
            lease.manifest_data["previous_artifact_sha256"],
            SHA_A,
        )
        self.assertEqual(
            lease.manifest_data["previous_manifest"]["artifact_sha256"],
            SHA_A,
        )

    def test_stale_owner_artifact_cannot_overwrite_published_generation(self):
        from stable.services.race_data_sync_providers import (
            _read_snapshot_artifact,
            _write_snapshot_artifact,
        )

        with TemporaryDirectory() as temporary_directory, self.settings(
            RACE_DATA_RAW_ARTIFACT_ROOTS=(temporary_directory,),
            RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
        ):
            cache_key = race_data_sync_control.build_snapshot_cache_key(
                **self._args(scope_key="immutable-generation")
            )
            first = race_data_sync_control.claim_snapshot_lease(
                **self._args(scope_key="immutable-generation"),
                owner_token="owner-a",
                now=NOW,
                ttl_seconds=60,
            )
            takeover = race_data_sync_control.claim_snapshot_lease(
                **self._args(scope_key="immutable-generation"),
                owner_token="owner-b",
                now=NOW + timedelta(seconds=61),
                ttl_seconds=60,
            )
            current_payload = {"racecards": [{"race_id": "current"}]}
            current_path, current_sha = _write_snapshot_artifact(
                cache_key=cache_key,
                owner_token="owner-b",
                payload=current_payload,
            )
            current_manifest = self._manifest(
                scope_key="immutable-generation",
                artifact_sha256=current_sha,
            )
            published = race_data_sync_control.publish_snapshot(
                **self._args(scope_key="immutable-generation"),
                owner_token="owner-b",
                expected_generation=takeover.generation,
                artifact_sha256=current_sha,
                manifest=current_manifest,
                now=NOW + timedelta(seconds=62),
            )
            self.assertEqual(published.action, "published")

            stale_path, stale_sha = _write_snapshot_artifact(
                cache_key=cache_key,
                owner_token="owner-a",
                payload={"racecards": [{"race_id": "stale"}]},
            )
            stale_publish = race_data_sync_control.publish_snapshot(
                **self._args(scope_key="immutable-generation"),
                owner_token="owner-a",
                expected_generation=first.generation,
                artifact_sha256=stale_sha,
                manifest=self._manifest(
                    scope_key="immutable-generation",
                    artifact_sha256=stale_sha,
                ),
                now=NOW + timedelta(seconds=63),
            )

            self.assertEqual(stale_publish.action, "rejected")
            self.assertNotEqual(current_path, stale_path)
            payload, artifact_sha = _read_snapshot_artifact(
                manifest=current_manifest
            )
            self.assertEqual(payload, current_payload)
            self.assertEqual(artifact_sha, current_sha)

    def test_successful_snapshot_refresh_retires_previous_artifact(self):
        from stable.services.race_data_sync_providers import (
            _delete_unreferenced_snapshot_artifact,
            _write_snapshot_artifact,
        )

        with TemporaryDirectory() as temporary_directory, self.settings(
            RACE_DATA_RAW_ARTIFACT_ROOTS=(temporary_directory,),
            RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
        ):
            args = self._args(scope_key="refresh-retirement")
            cache_key = race_data_sync_control.build_snapshot_cache_key(**args)
            old_path, old_sha = _write_snapshot_artifact(
                cache_key=cache_key,
                owner_token="old-owner",
                payload={"racecards": [{"race_id": "old"}]},
            )
            first = race_data_sync_control.claim_snapshot_lease(
                **args,
                owner_token="old-owner",
                now=NOW,
                ttl_seconds=60,
            )
            self.assertEqual(
                race_data_sync_control.publish_snapshot(
                    **args,
                    owner_token="old-owner",
                    expected_generation=first.generation,
                    artifact_sha256=old_sha,
                    manifest=self._manifest(
                        artifact_sha256=old_sha,
                        scope_key="refresh-retirement",
                    ),
                    now=NOW + timedelta(seconds=1),
                ).action,
                "published",
            )
            takeover = race_data_sync_control.claim_snapshot_lease(
                **args,
                owner_token="new-owner",
                now=NOW + timedelta(seconds=152),
                ttl_seconds=60,
            )
            self.assertEqual(takeover.action, "taken_over")
            new_path, new_sha = _write_snapshot_artifact(
                cache_key=cache_key,
                owner_token="new-owner",
                payload={"racecards": [{"race_id": "new"}]},
            )
            self.assertEqual(
                race_data_sync_control.publish_snapshot(
                    **args,
                    owner_token="new-owner",
                    expected_generation=takeover.generation,
                    artifact_sha256=new_sha,
                    manifest=self._manifest(
                        artifact_sha256=new_sha,
                        scope_key="refresh-retirement",
                    ),
                    now=NOW + timedelta(seconds=153),
                ).action,
                "published",
            )
            _delete_unreferenced_snapshot_artifact(
                cache_key=cache_key,
                artifact_sha256=old_sha,
            )

            self.assertFalse(old_path.exists())
            self.assertTrue(new_path.exists())

    def test_corrupt_complete_and_failed_retry_after_are_fail_closed(self):
        acquired = race_data_sync_control.claim_snapshot_lease(
            **self._args(data_kind="result"),
            owner_token="owner-a",
            now=NOW,
            ttl_seconds=60,
        )
        failed = race_data_sync_control.fail_snapshot_lease(
            **self._args(data_kind="result"),
            owner_token="owner-a",
            expected_generation=acquired.generation,
            error_code="pagination_failed",
            retry_after=NOW + timedelta(minutes=5),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(failed.action, "failed")
        self.assertEqual(
            race_data_sync_control.claim_snapshot_lease(
                **self._args(data_kind="result"),
                owner_token="owner-b",
                now=NOW + timedelta(minutes=4),
                ttl_seconds=60,
            ).reason_code,
            "retry_after",
        )
        self.assertEqual(
            race_data_sync_control.claim_snapshot_lease(
                **self._args(data_kind="result"),
                owner_token="owner-b",
                now=NOW + timedelta(minutes=5),
                ttl_seconds=60,
            ).action,
            "taken_over",
        )

        claimed = race_data_sync_control.claim_snapshot_lease(
            **self._args(scope_key="2026-08-22"),
            owner_token="owner-c",
            now=NOW,
            ttl_seconds=60,
        )
        race_data_sync_control.publish_snapshot(
            **self._args(scope_key="2026-08-22"),
            owner_token="owner-c",
            expected_generation=claimed.generation,
            artifact_sha256=SHA_A,
            manifest=self._manifest(scope_key="2026-08-22"),
            now=NOW + timedelta(seconds=1),
        )
        models.RaceDataSnapshotLease.objects.filter(
            cache_key=race_data_sync_control.build_snapshot_cache_key(
                **self._args(scope_key="2026-08-22")
            )
        ).update(manifest_data={"complete": True})
        self.assertEqual(
            race_data_sync_control.claim_snapshot_lease(
                **self._args(scope_key="2026-08-22"),
                owner_token="owner-d",
                now=NOW + timedelta(seconds=2),
                ttl_seconds=60,
            ).action,
            "taken_over",
        )

    def test_snapshot_publish_and_failure_require_an_unexpired_owner_lease(self):
        publish_before = race_data_sync_control.claim_snapshot_lease(
            **self._args(scope_key="publish-before"),
            owner_token="publish-before-owner",
            now=NOW,
            ttl_seconds=60,
        )
        self.assertEqual(
            race_data_sync_control.publish_snapshot(
                **self._args(scope_key="publish-before"),
                owner_token="publish-before-owner",
                expected_generation=publish_before.generation,
                artifact_sha256=SHA_A,
                manifest=self._manifest(scope_key="publish-before"),
                now=NOW + timedelta(seconds=59),
            ).action,
            "published",
        )

        publish_at_expiry = race_data_sync_control.claim_snapshot_lease(
            **self._args(scope_key="publish-at-expiry"),
            owner_token="publish-expired-owner",
            now=NOW,
            ttl_seconds=60,
        )
        rejected_publish = race_data_sync_control.publish_snapshot(
            **self._args(scope_key="publish-at-expiry"),
            owner_token="publish-expired-owner",
            expected_generation=publish_at_expiry.generation,
            artifact_sha256=SHA_A,
            manifest=self._manifest(scope_key="publish-at-expiry"),
            now=NOW + timedelta(seconds=60),
        )
        self.assertEqual(
            (rejected_publish.action, rejected_publish.reason_code),
            ("rejected", "lease_cas_stale"),
        )

        fail_before = race_data_sync_control.claim_snapshot_lease(
            **self._args(scope_key="fail-before"),
            owner_token="fail-before-owner",
            now=NOW,
            ttl_seconds=60,
        )
        self.assertEqual(
            race_data_sync_control.fail_snapshot_lease(
                **self._args(scope_key="fail-before"),
                owner_token="fail-before-owner",
                expected_generation=fail_before.generation,
                error_code="provider_failed",
                retry_after=NOW + timedelta(minutes=5),
                now=NOW + timedelta(seconds=59),
            ).action,
            "failed",
        )

        fail_at_expiry = race_data_sync_control.claim_snapshot_lease(
            **self._args(scope_key="fail-at-expiry"),
            owner_token="fail-expired-owner",
            now=NOW,
            ttl_seconds=60,
        )
        rejected_failure = race_data_sync_control.fail_snapshot_lease(
            **self._args(scope_key="fail-at-expiry"),
            owner_token="fail-expired-owner",
            expected_generation=fail_at_expiry.generation,
            error_code="provider_failed",
            retry_after=NOW + timedelta(minutes=5),
            now=NOW + timedelta(seconds=60),
        )
        self.assertEqual(
            (rejected_failure.action, rejected_failure.reason_code),
            ("rejected", "lease_cas_stale"),
        )
        for scope_key in ("publish-at-expiry", "fail-at-expiry"):
            lease = models.RaceDataSnapshotLease.objects.get(
                cache_key=race_data_sync_control.build_snapshot_cache_key(
                    **self._args(scope_key=scope_key)
                )
            )
            self.assertEqual(lease.state, models.RaceDataSnapshotLeaseState.CLAIMED)
            self.assertTrue(lease.owner_token)

    def test_cleanup_removes_only_expired_valid_complete_snapshot(self):
        from stable.services.race_data_sync_providers import (
            cleanup_expired_shared_snapshots,
        )

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_root = root / "snapshots"
            snapshot_root.mkdir(mode=0o700)
            payload = {"racecards": [{"race_id": "expired"}]}
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            artifact_sha256 = hashlib.sha256(encoded).hexdigest()
            expired_key = "jra:japan:expired:racecard:" + SHA_B
            expired_path = snapshot_root / (
                hashlib.sha256(expired_key.encode()).hexdigest()
                + f"-{artifact_sha256}.json"
            )
            expired_path.write_bytes(encoded)
            expired_path.chmod(0o600)
            expired = models.RaceDataSnapshotLease.objects.create(
                cache_key=expired_key,
                state=models.RaceDataSnapshotLeaseState.COMPLETE,
                owner_token="",
                lease_expires_at=NOW - timedelta(days=8),
                artifact_sha256=artifact_sha256,
                manifest_data={
                    "schema_version": 1,
                    "complete": True,
                    "cache_key": expired_key,
                    "artifact_sha256": artifact_sha256,
                    "registry_digest": SHA_B,
                    "fetched_at": (NOW - timedelta(days=8)).isoformat(),
                    "page_count": 1,
                    "item_count": 1,
                },
            )
            malformed = models.RaceDataSnapshotLease.objects.create(
                cache_key="jra:japan:malformed:racecard:" + SHA_B,
                state=models.RaceDataSnapshotLeaseState.COMPLETE,
                owner_token="",
                lease_expires_at=NOW - timedelta(days=8),
                artifact_sha256=SHA_A,
                manifest_data={"complete": True},
            )
            recent = models.RaceDataSnapshotLease.objects.create(
                cache_key="jra:japan:recent:racecard:" + SHA_B,
                state=models.RaceDataSnapshotLeaseState.COMPLETE,
                owner_token="",
                lease_expires_at=NOW - timedelta(days=6),
                artifact_sha256=SHA_A,
                manifest_data={"complete": True},
            )
            models.RaceDataSnapshotLease.objects.filter(pk=expired.pk).update(
                updated_at=NOW - timedelta(days=8)
            )
            models.RaceDataSnapshotLease.objects.filter(pk=malformed.pk).update(
                updated_at=NOW - timedelta(days=8)
            )
            models.RaceDataSnapshotLease.objects.filter(pk=recent.pk).update(
                updated_at=NOW - timedelta(days=6)
            )

            with self.settings(
                RACE_DATA_RAW_ARTIFACT_ROOTS=(str(root),),
                RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
                RACE_DATA_SNAPSHOT_RETENTION_SECONDS=7 * 24 * 3600,
            ):
                bounded = cleanup_expired_shared_snapshots(
                    now=NOW,
                    batch_size=100,
                    max_bytes=len(encoded) - 1,
                )
                self.assertEqual(bounded.cleaned, 0)
                self.assertEqual(bounded.cleaned_bytes, 0)
                self.assertTrue(expired_path.exists())
                outcome = cleanup_expired_shared_snapshots(
                    now=NOW,
                    batch_size=100,
                    max_bytes=len(encoded),
                )

            self.assertEqual(outcome.cleaned, 1)
            self.assertEqual(outcome.cleaned_bytes, len(encoded))
            self.assertEqual(outcome.skipped, 1)
            self.assertFalse(expired_path.exists())
            self.assertFalse(
                models.RaceDataSnapshotLease.objects.filter(pk=expired.pk).exists()
            )
            self.assertTrue(
                models.RaceDataSnapshotLease.objects.filter(pk=malformed.pk).exists()
            )
            self.assertTrue(
                models.RaceDataSnapshotLease.objects.filter(pk=recent.pk).exists()
            )

    def test_data_sync_reuses_shared_host_budget_with_route_interval_floor(self):
        budget = models.RaceLiveHostBudget.objects.create(
            host="race-data.example.test",
            min_interval_ms=1_050,
            next_allowed_at=NOW + timedelta(milliseconds=1_050),
            lock_version=7,
        )
        tightened = race_events.ensure_race_live_host_budget_floor(
            host=budget.host,
            minimum_interval_ms=2_000,
        )
        self.assertEqual(tightened.min_interval_ms, 2_000)
        self.assertEqual(
            tightened.next_allowed_at,
            NOW + timedelta(milliseconds=2_000),
        )
        self.assertEqual(tightened.lock_version, 7)

        reused = race_events.ensure_race_live_host_budget_floor(
            host=budget.host,
            minimum_interval_ms=1_050,
        )
        self.assertEqual(reused.min_interval_ms, 2_000)
        self.assertEqual(
            reused.next_allowed_at,
            NOW + timedelta(milliseconds=2_000),
        )

        budget.next_allowed_at = None
        budget.save(update_fields=("next_allowed_at",))
        first = race_data_sync_control.reserve_race_data_host_request(
            host=budget.host,
            minimum_interval_seconds=2,
            now=NOW,
        )
        self.assertTrue(first.reserved)
        blocked = race_data_sync_control.reserve_race_data_host_request(
            host=budget.host,
            minimum_interval_seconds=2,
            now=NOW,
        )
        self.assertFalse(blocked.reserved)
        self.assertEqual(blocked.reason, "rate_limited")

        budget.next_allowed_at = None
        budget.min_interval_ms = 1_000
        budget.save(update_fields=("next_allowed_at", "min_interval_ms"))
        unsafe = race_data_sync_control.reserve_race_data_host_request(
            host=budget.host,
            minimum_interval_seconds=2,
            now=NOW,
        )
        self.assertFalse(unsafe.reserved)
        self.assertEqual(unsafe.reason, "budget_interval_too_low")


class RaceDataSyncCensusManifestTests(TestCase):
    def setUp(self):
        self.roster, self.route = audited_test_roster()
        self.roster_patcher = patch(
            "stable.services.race_data_sync_pipeline.build_race_data_provider_roster",
            return_value=self.roster,
        )
        self.roster_patcher.start()
        self.addCleanup(self.roster_patcher.stop)

    def _policy(self, *, valid_until: datetime | None = None) -> dict:
        return {
            "schema_version": 1,
            "policy_id": "japan-r0-reviewed",
            "approved_by": "local-test-reviewer",
            "approved_at": NOW.isoformat(),
            "valid_from": (NOW - timedelta(days=1)).isoformat(),
            "valid_until": (valid_until or NOW + timedelta(days=30)).isoformat(),
            "routes": [
                {
                    "country_region": models.RacingRegion.JAPAN,
                    "provider": "jra",
                    "region_code": "japan",
                    "identity_namespace": "jra-race-v1",
                    "route_digest": self.route.route_digest,
                    "data_kinds": ["race_time", "racecard", "result"],
                }
            ],
            "visibility_statuses": [models.RaceEventVisibility.PUBLISHED],
            "event_statuses": [models.RaceEventStatus.SCHEDULED],
        }

    def _identity(self, event, *, automation_allowed: bool = True):
        return models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="jra",
            region_code="japan",
            identity_namespace="jra-race-v1",
            external_race_id=f"jra-{event.pk}",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=automation_allowed,
            proof_network_allowed=True,
            evidence_url="https://jra.example.test/reviewed-proof",
            evidence_sha256=SHA_A,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )

    def test_census_accounts_for_exact_99_event_snapshot(self):
        for number in range(99):
            event = create_event(slug=f"census-{number:03d}")
            self._identity(event)

        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(),
            cutoff=NOW,
            horizon_days=30,
        )

        self.assertEqual(census.total, 99)
        self.assertEqual(len(census.entries), 99)
        self.assertEqual(census.classification_counts, {"eligible": 99})
        self.assertEqual(len({entry.event_id for entry in census.entries}), 99)
        self.assertRegex(census.census_sha256, r"\A[0-9a-f]{64}\Z")

    def test_census_keeps_owner_identity_and_manual_lock_blockers_explicit(self):
        eligible = create_event(slug="census-eligible")
        self._identity(eligible)
        missing_identity = create_event(slug="census-missing-identity")
        owner_conflict = create_event(slug="census-owner-conflict")
        self._identity(owner_conflict)
        models.RaceEventProjectionControl.objects.create(
            event=owner_conflict,
            write_owner=models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=2,
        )
        locked = create_event(slug="census-manual-lock")
        locked.manual_lock_flags = {"race_datetime": True}
        locked.save(update_fields=("manual_lock_flags",))
        self._identity(locked)

        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(),
            cutoff=NOW,
            horizon_days=30,
        )
        by_slug = {entry.slug: entry for entry in census.entries}

        self.assertEqual(by_slug[eligible.slug].classification, "eligible")
        self.assertEqual(
            by_slug[missing_identity.slug].reason_code,
            "source_identity_missing",
        )
        self.assertEqual(
            by_slug[owner_conflict.slug].reason_code,
            "writer_owner_conflict",
        )
        self.assertEqual(by_slug[locked.slug].reason_code, "manual_lock_present")
        self.assertEqual(sum(census.classification_counts.values()), 4)

    def test_census_selects_the_only_admitted_route_from_multiple_policy_routes(self):
        event = create_event(slug="census-route-ambiguous")
        self._identity(event)
        policy = self._policy()
        policy["routes"].append(
            {
                "country_region": models.RacingRegion.JAPAN,
                "provider": "nar",
                "region_code": "japan",
                "identity_namespace": "nar-race-v1",
                "route_digest": SHA_C,
                "data_kinds": ["racecard"],
            }
        )
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=policy,
            cutoff=NOW,
            horizon_days=30,
        )
        self.assertEqual(census.entries[0].classification, "eligible")
        self.assertEqual(census.entries[0].provider, "jra")
        self.assertEqual(census.entries[0].source_identity_id, event.source_identities.get().pk)

    def test_census_includes_future_event_on_western_local_cutoff_date(self):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="census-western-local-date",
            original_name="Western Local Date Cup",
            chinese_name="西部时区杯",
            country_region=models.RacingRegion.UNITED_STATES,
            racecourse="Del Mar",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=None,
            timezone_name="America/Los_Angeles",
            local_date=date(2026, 8, 19),
            local_start_time=datetime(2026, 8, 19, 22, 0).time(),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        policy = self._policy()
        policy["routes"].append(
            {
                "country_region": models.RacingRegion.UNITED_STATES,
                "provider": "equibase",
                "region_code": "united_states",
                "identity_namespace": "equibase-race-v1",
                "route_digest": SHA_A,
                "data_kinds": ["race_time", "racecard", "result"],
            }
        )

        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=policy,
            cutoff=NOW,
            horizon_days=30,
        )

        self.assertIn(event.pk, {entry.event_id for entry in census.entries})

    def test_future_discovery_builds_bounded_proposal_without_writes(self):
        for number in range(25):
            event = create_event(slug=f"future-proposal-{number:02d}")
            self._identity(event)
        proposal = race_data_sync_enrollment.build_future_race_data_enrollment_proposal(
            standing_policy=self._policy(),
            cutoff=NOW,
            horizon_days=30,
            max_events=20,
            candidate_commit="1" * 40,
            apply_expires_at=NOW + timedelta(minutes=15),
        )
        self.assertEqual(proposal.census.total, 25)
        self.assertEqual(len(proposal.selected_event_ids), 20)
        self.assertEqual(
            proposal.selected_event_ids,
            tuple(sorted(proposal.selected_event_ids)),
        )
        self.assertIsNotNone(proposal.manifest)
        self.assertEqual(len(proposal.manifest.payload["entries"]), 20)
        self.assertFalse(models.RaceDataSyncEnrollment.objects.exists())

    def test_hourly_future_discovery_loads_exact_policy_and_auto_enrolls(self):
        event = create_event(slug="future-hourly-task")
        self._identity(event)
        raw = json.dumps(
            self._policy(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "standing-policy.json"
            policy_path.write_bytes(raw)
            with (
                override_settings(
                    RACE_DATA_SYNC_ENABLED=True,
                    RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED=True,
                    RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE=str(policy_path),
                    RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=hashlib.sha256(raw).hexdigest(),
                    RACE_DATA_SYNC_FUTURE_HORIZON_DAYS=30,
                    RACE_DATA_SYNC_FUTURE_BATCH_SIZE=20,
                    RACE_DATA_SYNC_FUTURE_MANIFEST_TTL_SECONDS=900,
                    UMANEWS_RELEASE_COMMIT="1" * 40,
                ),
                patch("stable.tasks.timezone.now", return_value=NOW),
            ):
                from stable.tasks import discover_future_race_data_sync_task

                result = discover_future_race_data_sync_task()
        self.assertEqual(result["status"], "enrollment_applied")
        self.assertEqual(result["selected_event_ids"], (event.pk,))
        self.assertEqual(result["decision_counts"], {"acquired": 1})
        self.assertRegex(result["census_sha256"], r"\A[0-9a-f]{64}\Z")
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=event)
        self.assertEqual(enrollment.state, models.RaceDataSyncEnrollmentState.ENROLLED)
        self.assertEqual(
            models.RaceEventProjectionControl.objects.get(event=event).write_owner,
            models.RaceEventProjectionWriteOwner.DATA_SYNC,
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
        RACE_DATA_SYNC_ALLOW_NETWORK=False,
        RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=False,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=False,
    )
    def test_exact_manifest_applies_and_successor_rotates_owner_generation(self):
        event = create_event(slug="manifest-apply")
        self._identity(event)
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(),
            cutoff=NOW,
            horizon_days=30,
        )
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        applied = race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=manifest.as_dict(),
            expected_manifest_sha256=manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW,
        )
        self.assertEqual(applied[0].action, "acquired")
        control_before = models.RaceEventProjectionControl.objects.get(event=event)
        enrollment_before = models.RaceDataSyncEnrollment.objects.get(event=event)
        tracking_before = models.RaceEventLiveTracking.objects.get(event=event)
        event.status = models.RaceEventStatus.FINISHED
        event.save(update_fields=("status",))
        source = event.source_identities.get()
        original_external_race_id = source.external_race_id
        source.external_race_id = f"{source.external_race_id}-drift"
        source.save(update_fields=("external_race_id",))
        replayed = race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=manifest.as_dict(),
            expected_manifest_sha256=manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(replayed[0].action, "replay")
        control_before.refresh_from_db()
        enrollment_before.refresh_from_db()
        tracking_before.refresh_from_db()
        self.assertEqual(control_before.owner_generation, 1)
        self.assertEqual(enrollment_before.enrollment_generation, 1)
        self.assertEqual(tracking_before.claim_generation, 1)

        non_exact = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW + timedelta(seconds=2),
            apply_expires_at=NOW + timedelta(hours=1),
        )
        rejected = race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=non_exact.as_dict(),
            expected_manifest_sha256=non_exact.manifest_sha256,
            current_commit="1" * 40,
            now=NOW + timedelta(seconds=2),
        )
        self.assertEqual(rejected[0].reason_code, "event_snapshot_drift")
        control_before.refresh_from_db()
        enrollment_before.refresh_from_db()
        self.assertEqual(control_before.owner_generation, 1)
        self.assertEqual(enrollment_before.enrollment_generation, 1)

        event.status = models.RaceEventStatus.SCHEDULED
        event.save(update_fields=("status",))
        source.external_race_id = original_external_race_id
        source.save(update_fields=("external_race_id",))

        successor = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=race_data_sync_enrollment.build_race_data_enrollment_census(
                standing_policy=self._policy(),
                cutoff=NOW + timedelta(minutes=1),
                horizon_days=30,
            ),
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW + timedelta(minutes=1),
            apply_expires_at=NOW + timedelta(hours=1),
        )
        rotated = race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=successor.as_dict(),
            expected_manifest_sha256=successor.manifest_sha256,
            current_commit="1" * 40,
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(rotated[0].action, "rotated")
        control = models.RaceEventProjectionControl.objects.get(event=event)
        self.assertEqual(control.owner_generation, 2)

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
        RACE_DATA_SYNC_ALLOW_NETWORK=False,
        RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=False,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=False,
    )
    def test_manifest_route_becoming_unavailable_is_zero_write(self):
        event = create_event(slug="manifest-route-unavailable")
        self._identity(event)
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(), cutoff=NOW, horizon_days=30
        )
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        with patch.object(
            race_data_sync_enrollment,
            "resolve_race_data_provider_route",
            return_value=None,
        ):
            decisions = race_data_sync_enrollment.apply_race_data_enrollment_manifest(
                manifest=manifest.as_dict(),
                expected_manifest_sha256=manifest.manifest_sha256,
                current_commit="1" * 40,
                now=NOW,
            )
        self.assertEqual(decisions[0].reason_code, "provider_route_drift")
        self.assertFalse(
            models.RaceDataSyncEnrollment.objects.filter(event=event).exists()
        )
        self.assertFalse(
            models.RaceEventProjectionControl.objects.filter(event=event).exists()
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
        RACE_DATA_SYNC_ALLOW_NETWORK=False,
        RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=False,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=False,
    )
    def test_expired_manifest_is_rejected_before_event_write(self):
        event = create_event(slug="manifest-expired")
        self._identity(event)
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(),
            cutoff=NOW,
            horizon_days=30,
        )
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(minutes=5),
        )
        with self.assertRaisesMessage(ValueError, "manifest has expired"):
            race_data_sync_enrollment.apply_race_data_enrollment_manifest(
                manifest=manifest.as_dict(),
                expected_manifest_sha256=manifest.manifest_sha256,
                current_commit="1" * 40,
                now=NOW + timedelta(minutes=6),
            )
        self.assertFalse(
            models.RaceDataSyncEnrollment.objects.filter(event=event).exists()
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
        RACE_DATA_SYNC_ALLOW_NETWORK=False,
        RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=False,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=False,
    )
    def test_reverse_manifest_releases_owner_without_deleting_evidence(self):
        event = create_event(slug="reverse-manifest")
        source = self._identity(event)
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(), cutoff=NOW, horizon_days=30
        )
        enrollment_manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=enrollment_manifest.as_dict(),
            expected_manifest_sha256=enrollment_manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW,
        )
        enrolled_census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(),
            cutoff=NOW + timedelta(minutes=1),
            horizon_days=30,
        )
        reverse = race_data_sync_enrollment.build_race_data_disenrollment_manifest(
            census=enrolled_census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW + timedelta(minutes=1),
            apply_expires_at=NOW + timedelta(hours=1),
        )
        decisions = race_data_sync_enrollment.apply_race_data_disenrollment_manifest(
            manifest=reverse.as_dict(),
            expected_manifest_sha256=reverse.manifest_sha256,
            current_commit="1" * 40,
            now=NOW + timedelta(minutes=2),
        )
        self.assertEqual(decisions[0].action, "released")
        control = models.RaceEventProjectionControl.objects.get(event=event)
        tracking = models.RaceEventLiveTracking.objects.get(event=event)
        self.assertEqual(
            control.write_owner, models.RaceEventProjectionWriteOwner.UNMANAGED
        )
        self.assertFalse(tracking.tracking_enabled)
        self.assertTrue(
            tracking.provider_checkpoints.filter(next_poll_at__isnull=True).exists()
        )
        self.assertTrue(models.RaceResultSourceIdentity.objects.filter(pk=source.pk).exists())

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
        RACE_DATA_SYNC_ALLOW_NETWORK=False,
        RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=False,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=False,
    )
    def test_reverse_manifest_rejects_current_baseline_drift(self):
        event = create_event(slug="reverse-manifest-drift")
        self._identity(event)
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(), cutoff=NOW, horizon_days=30
        )
        enrollment_manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=enrollment_manifest.as_dict(),
            expected_manifest_sha256=enrollment_manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW,
        )
        enrolled_census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self._policy(),
            cutoff=NOW + timedelta(minutes=1),
            horizon_days=30,
        )
        reverse = race_data_sync_enrollment.build_race_data_disenrollment_manifest(
            census=enrolled_census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW + timedelta(minutes=1),
            apply_expires_at=NOW + timedelta(hours=1),
        )
        event.status = models.RaceEventStatus.CANCELLED
        event.save(update_fields=("status",))

        decisions = race_data_sync_enrollment.apply_race_data_disenrollment_manifest(
            manifest=reverse.as_dict(),
            expected_manifest_sha256=reverse.manifest_sha256,
            current_commit="1" * 40,
            now=NOW + timedelta(minutes=2),
        )
        self.assertEqual(decisions[0].reason_code, "event_snapshot_drift")
        control = models.RaceEventProjectionControl.objects.get(event=event)
        self.assertEqual(
            control.write_owner, models.RaceEventProjectionWriteOwner.DATA_SYNC
        )

    @override_settings(RACE_DATA_SYNC_ENABLED=True)
    def test_manifest_apply_refuses_when_any_runtime_switch_is_on(self):
        with self.assertRaisesMessage(ValueError, "all race-data runtime switches"):
            race_data_sync_enrollment.apply_race_data_enrollment_manifest(
                manifest={},
                expected_manifest_sha256=SHA_A,
                current_commit="1" * 40,
                now=NOW,
            )


@override_settings(RACE_DATA_SYNC_SCHEDULER_ENABLED=False)
class RaceDataSyncSelectorFailClosedTests(SimpleTestCase):
    def test_disabled_selector_does_not_touch_database_service(self):
        from stable.tasks import select_due_race_data_sync_task

        with patch(
            "stable.services.race_data_sync_control.claim_due_enrollments"
        ) as claim:
            result = select_due_race_data_sync_task()
        self.assertEqual(
            result,
            {"enabled": False, "claimed": 0, "dispatched": 0},
        )
        claim.assert_not_called()

    @override_settings(RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED=False)
    def test_disabled_future_discovery_does_not_load_policy_or_query_database(self):
        from stable.tasks import discover_future_race_data_sync_task

        with patch(
            "stable.services.race_data_sync_enrollment.load_standing_policy_file"
        ) as loader:
            result = discover_future_race_data_sync_task()
        self.assertEqual(result, {"enabled": False, "status": "disabled"})
        loader.assert_not_called()

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED=True,
    )
    def test_future_discovery_subswitch_cannot_bypass_disabled_master(self):
        from stable.tasks import discover_future_race_data_sync_task

        with patch(
            "stable.services.race_data_sync_enrollment.load_standing_policy_file"
        ) as loader:
            result = discover_future_race_data_sync_task()

        self.assertEqual(result, {"enabled": False, "status": "disabled"})
        loader.assert_not_called()

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    )
    def test_cleanup_scheduler_cannot_bypass_disabled_master(self):
        from stable.tasks import cleanup_race_data_sync_artifacts_task

        with patch(
            "stable.services.race_data_sync_pipeline.cleanup_expired_race_data_raw_payloads"
        ) as cleanup:
            result = cleanup_race_data_sync_artifacts_task()

        self.assertEqual(result, {"enabled": False, "status": "disabled"})
        cleanup.assert_not_called()

    @override_settings(
        RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=(),
        RACE_DATA_SYNC_ENABLED_REGIONS=("japan",),
        RACE_DATA_SYNC_ENABLED_DATA_KINDS=("racecard",),
    )
    def test_empty_admission_scope_does_not_touch_database_service(self):
        from stable.tasks import select_due_race_data_sync_task

        with patch(
            "stable.services.race_data_sync_control.claim_due_enrollments"
        ) as claim:
            result = select_due_race_data_sync_task()
        self.assertEqual(result["reason"], "admission_scope_empty")
        self.assertEqual(result["claimed"], 0)
        claim.assert_not_called()


class RaceDataSyncWorkerReleaseContractTests(SimpleTestCase):
    def test_dedicated_worker_is_queue_isolated_and_resource_bounded(self):
        start_script = (ROOT / "deploy/docker/start-race-data-sync-worker.sh").read_text()
        self.assertIn('--queues="race_sync_v2"', start_script)
        self.assertIn("--prefetch-multiplier=1", start_script)
        self.assertIn("CELERY_RACE_DATA_SYNC_WORKER_CONCURRENCY", start_script)
        self.assertIn("CELERY_RACE_DATA_SYNC_WORKER_MAX_TASKS_PER_CHILD", start_script)
        self.assertIn("CELERY_RACE_DATA_SYNC_WORKER_MAX_MEMORY_PER_CHILD", start_script)
        self.assertNotIn('race_live,', start_script)

        for compose_name in (
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "docker-compose.prod.lowcost.yml",
        ):
            compose = (ROOT / compose_name).read_text()
            self.assertIn("race_sync_v2_worker:", compose, compose_name)
            self.assertIn(
                "/app/deploy/docker/start-race-data-sync-worker.sh",
                compose,
                compose_name,
            )
        for compose_name in (
            "docker-compose.prod.yml",
            "docker-compose.prod.lowcost.yml",
        ):
            compose = (ROOT / compose_name).read_text()
            self.assertIn("RACE_DATA_SYNC_WORKER_CPUS", compose, compose_name)
            self.assertIn("RACE_DATA_SYNC_WORKER_MEMORY_LIMIT", compose, compose_name)
            service = re.search(
                r"(?ms)^  race_sync_v2_worker:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
                compose,
            )
            self.assertIsNotNone(service, compose_name)
            self.assertNotIn(
                "/app/server/media",
                service.group(0),
                f"{compose_name} must not mount public media into provider worker",
            )

    def test_all_new_flags_default_off_in_example_environment(self):
        example = (ROOT / ".env.example").read_text()
        for assignment in (
            "RACE_DATA_SYNC_ENABLED=false",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED=false",
            "RACE_DATA_SYNC_ALLOW_NETWORK=false",
            "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=false",
            "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=false",
            "RACE_DATA_SYNC_RESULT_APPLY_ENABLED=false",
            "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=false",
            "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=false",
            "RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED=false",
        ):
            self.assertIn(assignment, example)

    def test_capacity_limits_are_explicit_and_fail_closed(self):
        from stable.services.race_data_sync_pipeline import RaceDataSyncCapacityLimits

        with override_settings(
            RACE_DATA_RAW_MAX_COMPRESSED_BYTES=0,
            RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=0,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=0,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=0,
            RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=0,
            RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=0,
            RACE_DATA_RAW_MIN_FREE_DISK_BYTES=0,
            RACE_DATA_RAW_CLEANUP_MAX_ROWS=0,
            RACE_DATA_RAW_CLEANUP_MAX_BYTES=0,
            RACE_DATA_RAW_HOLD_ALERT_BYTES=0,
        ):
            with self.assertRaisesMessage(ValueError, "must be positive"):
                RaceDataSyncCapacityLimits.from_settings()
        capacity_keys = (
            "RACE_DATA_RAW_MAX_COMPRESSED_BYTES",
            "RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES",
            "RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES",
            "RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS",
            "RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES",
            "RACE_DATA_RAW_ROOT_LOW_WATER_BYTES",
            "RACE_DATA_RAW_MIN_FREE_DISK_BYTES",
            "RACE_DATA_RAW_CLEANUP_MAX_ROWS",
            "RACE_DATA_RAW_CLEANUP_MAX_BYTES",
            "RACE_DATA_RAW_HOLD_ALERT_BYTES",
        )
        example = (ROOT / ".env.example").read_text()
        for key in capacity_keys:
            self.assertIn(f"{key}=0", example)

        with override_settings(
            RACE_DATA_RAW_MAX_COMPRESSED_BYTES=100,
            RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=200,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1_000,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=10,
            RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=10_000,
            RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=8_000,
            RACE_DATA_RAW_MIN_FREE_DISK_BYTES=5_000,
            RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
            RACE_DATA_RAW_CLEANUP_MAX_BYTES=1_000,
            RACE_DATA_RAW_HOLD_ALERT_BYTES=500,
        ):
            limits = RaceDataSyncCapacityLimits.from_settings()
        self.assertGreater(limits.raw_max_uncompressed_bytes, 0)
        self.assertGreaterEqual(
            limits.raw_max_uncompressed_bytes,
            limits.raw_max_compressed_bytes,
        )
        self.assertGreater(limits.artifact_high_water_bytes, limits.artifact_low_water_bytes)
        self.assertGreater(limits.min_free_disk_bytes, 0)

    def test_invalid_capacity_environment_does_not_break_django_import(self):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "app.settings",
                "SECRET_KEY": "test",
                "DB_ENGINE": "sqlite",
                "RACE_DATA_RAW_MAX_COMPRESSED_BYTES": "not-a-number",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from app import settings; "
                    "print(settings.RACE_DATA_RAW_MAX_COMPRESSED_BYTES)"
                ),
            ],
            cwd=ROOT / "server",
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "None")

    def test_capacity_admission_blocks_before_transport_and_recovers_below_low_water(self):
        from stable.services.race_data_sync_pipeline import (
            RaceDataSyncCapacityLimits,
            evaluate_race_data_capacity,
        )

        limits = RaceDataSyncCapacityLimits(
            raw_max_compressed_bytes=100,
            raw_max_uncompressed_bytes=200,
            provider_region_daily_bytes=1_000,
            provider_region_daily_requests=10,
            artifact_high_water_bytes=10_000,
            artifact_low_water_bytes=8_000,
            min_free_disk_bytes=5_000,
            cleanup_max_rows=100,
            cleanup_max_bytes=1_000,
            hold_alert_bytes=500,
        )
        base = {
            "limits": limits,
            "proposed_compressed_bytes": 100,
            "proposed_uncompressed_bytes": 200,
            "provider_region_daily_bytes": 0,
            "provider_region_daily_requests": 0,
            "artifact_root_bytes": 7_000,
            "free_disk_bytes": 6_000,
            "hold_bytes": 0,
            "capacity_circuit_open": False,
            "cleanup_failed": False,
        }
        self.assertTrue(evaluate_race_data_capacity(**base).allowed)
        for updates, reason in (
            ({"proposed_compressed_bytes": 101}, "artifact_payload_compressed_too_large"),
            ({"artifact_root_bytes": 9_950}, "artifact_root_high_water"),
            ({"free_disk_bytes": 5_050}, "artifact_min_free_disk"),
            ({"hold_bytes": 500}, "artifact_capacity_hold_exceeded"),
            ({"cleanup_failed": True}, "artifact_capacity_cleanup_failed"),
            (
                {"capacity_circuit_open": True, "artifact_root_bytes": 8_001},
                "artifact_capacity_circuit_open",
            ),
        ):
            with self.subTest(reason=reason):
                decision = evaluate_race_data_capacity(**{**base, **updates})
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason_code, reason)
        recovered = evaluate_race_data_capacity(
            **{
                **base,
                "capacity_circuit_open": True,
                "artifact_root_bytes": 8_000,
            }
        )
        self.assertTrue(recovered.allowed)

    def test_release_entrypoints_account_for_new_worker(self):
        for relative_path in (
            "deploy/run_application_release.sh",
            "deploy/manual_release.sh",
            "deploy/resume_stopped_release.sh",
            "deploy/rollback_pre_single_owner.sh",
        ):
            script = (ROOT / relative_path).read_text()
            self.assertIn("race_sync_v2_worker", script, relative_path)
