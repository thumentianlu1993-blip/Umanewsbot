from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless

from django.db import (
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TransactionTestCase, override_settings

from stable import models
from stable.services import race_events
from stable.services.race_live_initialization import (
    RaceLiveInitializationError,
    apply_race_live_initialization,
    load_race_live_initialization_manifest,
    verify_race_live_initialization,
)
from stable.services import race_live_racecard_sync
from stable import test_race_live_gate_remediation as gate_tests
from stable import test_race_live_multiregion_pipeline as multiregion_tests


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class CoupledRunnerInitializationPostgresRemediationTests(
    TransactionTestCase
):
    reset_sequences = True
    NOW = datetime(2026, 7, 20, 5, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="pg-coupled-runner-remediation",
            original_name="PostgreSQL Coupled Runner Remediation",
            chinese_name="PostgreSQL 并列号码修复测试",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=self.NOW + timedelta(hours=1),
        )
        self.event.refresh_from_db()

    def _manifest(self):
        payload = {
            "schema_version": 1,
            "approved_commit": "c" * 40,
            "generated_at": self.NOW.isoformat(),
            "registry_digest": "a" * 64,
            "coverage_proof_digest": "b" * 64,
            "terms_evidence_sha256": "d" * 64,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "policy_valid_until": (
                self.NOW + timedelta(days=30)
            ).isoformat(),
            "official_verification_route": "jra_result_verification",
            "official_verification_route_version": "jra-v1",
            "official_verification_valid_until": (
                self.NOW + timedelta(days=30)
            ).isoformat(),
            "events": [
                {
                    "event_id": self.event.pk,
                    "expected_event_updated_at": (
                        self.event.updated_at.isoformat()
                    ),
                    "year": self.event.year,
                    "slug": self.event.slug,
                    "original_name": self.event.original_name,
                    "country_region": self.event.country_region,
                    "racecourse": self.event.racecourse,
                    "grade_text": self.event.grade_text,
                    "race_datetime": self.event.race_datetime.isoformat(),
                    "external_race_id": "pg-coupled-tra-race",
                    "tracking_state": "racecard_ready",
                    "next_poll_at": (
                        self.NOW + timedelta(minutes=30)
                    ).isoformat(),
                    "participants": [
                        {
                            "stable_key": "pg-coupled-alpha",
                            "canonical_name": "PostgreSQL Coupled Alpha",
                            "country_region": models.RacingRegion.JAPAN,
                            "external_runner_id": "pg-coupled-alpha-id",
                            "horse_number": "1",
                            "status": "declared",
                        },
                        {
                            "stable_key": "pg-coupled-beta",
                            "canonical_name": "PostgreSQL Coupled Beta",
                            "country_region": models.RacingRegion.JAPAN,
                            "external_runner_id": "pg-coupled-beta-id",
                            "horse_number": "1",
                            "status": "declared",
                        },
                    ],
                }
            ],
        }
        path = Path(self.temporary.name) / "manifest.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return load_race_live_initialization_manifest(
            manifest_path=path,
            expected_manifest_sha256=digest,
            expected_approved_commit="c" * 40,
            now=self.NOW,
        )

    def test_initializer_persists_all_coupled_identity_and_legacy_rows(self):
        field_names = {
            field.name for field in models.RaceEventRunner._meta.fields
        }
        self.assertIn(
            "external_runner_id",
            field_names,
            "initializer coupled landing 需要 legacy external identity 列",
        )

        result = apply_race_live_initialization(self._manifest())

        self.assertEqual(result["event_count"], 1)
        self.assertEqual(
            models.RaceEventParticipant.objects.filter(
                event=self.event
            ).count(),
            2,
        )
        self.assertEqual(
            models.RaceEventParticipantSourceIdentity.objects.filter(
                participant__event=self.event
            ).count(),
            2,
        )
        revision = models.RaceEventRevision.objects.get(
            event=self.event,
            kind=models.RaceEventRevisionKind.RACECARD,
        )
        self.assertEqual(revision.items.count(), 2)
        self.assertEqual(
            list(
                models.RaceEventRunner.objects.filter(event=self.event)
                .order_by("sort_order")
                .values_list(
                    "external_runner_id",
                    "horse_number",
                    "horse_name",
                )
            ),
            [
                (
                    "pg-coupled-alpha-id",
                    "1",
                    "PostgreSQL Coupled Alpha",
                ),
                (
                    "pg-coupled-beta-id",
                    "1",
                    "PostgreSQL Coupled Beta",
                ),
            ],
        )

    def test_initializer_rejects_preexisting_legacy_runner_without_duplication(self):
        existing = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="preexisting-runner",
            sort_order=1,
            horse_number="9",
            horse_name="Preexisting Runner",
            source_refs={
                "source_key": "legacy_import",
                "external_runner_id": "preexisting-runner",
            },
        )
        before = list(
            models.RaceEventRunner.objects.filter(event=self.event)
            .order_by("id")
            .values()
        )

        with self.assertRaises(RaceLiveInitializationError):
            apply_race_live_initialization(self._manifest())

        self.assertEqual(
            list(
                models.RaceEventRunner.objects.filter(event=self.event)
                .order_by("id")
                .values()
            ),
            before,
        )
        existing.refresh_from_db()
        self.assertEqual(existing.external_runner_id, "preexisting-runner")
        self.assertFalse(
            models.RaceEventProjectionControl.objects.filter(
                event=self.event
            ).exists()
        )
        self.assertFalse(
            models.RaceEventParticipant.objects.filter(
                event=self.event
            ).exists()
        )
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_event_initialized",
                target_id=str(self.event.pk),
            ).exists()
        )

    def test_verify_rejects_deleted_legacy_runner(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.filter(
            event=self.event,
            external_runner_id="pg-coupled-alpha-id",
        ).delete()

        verification = verify_race_live_initialization(manifest)

        self.assertFalse(verification["ok"])
        self.assertTrue(
            any(
                "legacy_runner" in error
                for error in verification["errors"]
            ),
            verification["errors"],
        )

    def test_verify_rejects_extra_legacy_runner(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="pg-coupled-extra-id",
            sort_order=3,
            horse_number="3",
            horse_name="PostgreSQL Coupled Extra",
            source_refs={
                "source_key": "the_racing_api",
                "external_runner_id": "pg-coupled-extra-id",
            },
        )

        verification = verify_race_live_initialization(manifest)

        self.assertFalse(verification["ok"])
        self.assertTrue(
            any(
                "legacy_runner" in error
                for error in verification["errors"]
            ),
            verification["errors"],
        )

    def test_verify_rejects_tampered_legacy_runner_identity_number_and_name(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.filter(
            event=self.event,
            external_runner_id="pg-coupled-alpha-id",
        ).update(external_runner_id="pg-coupled-tampered-id")
        models.RaceEventRunner.objects.filter(
            event=self.event,
            external_runner_id="pg-coupled-beta-id",
        ).update(
            horse_number="99",
            horse_name="Tampered Coupled Runner",
        )

        verification = verify_race_live_initialization(manifest)

        self.assertFalse(verification["ok"])
        self.assertTrue(
            any(
                "legacy_runner" in error
                for error in verification["errors"]
            ),
            verification["errors"],
        )

    def test_replay_rejects_tampered_legacy_runner_external_id(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.filter(
            event=self.event,
            external_runner_id="pg-coupled-alpha-id",
        ).update(external_runner_id="pg-coupled-tampered-id")

        with self.assertRaises(RaceLiveInitializationError):
            apply_race_live_initialization(manifest)

    def test_replay_rejects_tampered_legacy_runner_number_and_name(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.filter(
            event=self.event,
            external_runner_id="pg-coupled-beta-id",
        ).update(
            horse_number="99",
            horse_name="Tampered Coupled Runner",
        )

        with self.assertRaises(RaceLiveInitializationError):
            apply_race_live_initialization(manifest)

    def test_replay_rejects_deleted_legacy_runner(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.filter(
            event=self.event,
            external_runner_id="pg-coupled-alpha-id",
        ).delete()

        with self.assertRaises(RaceLiveInitializationError):
            apply_race_live_initialization(manifest)

    def test_replay_rejects_extra_legacy_runner(self):
        manifest = self._manifest()
        apply_race_live_initialization(manifest)
        models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="pg-coupled-extra-id",
            sort_order=3,
            horse_number="3",
            horse_name="PostgreSQL Coupled Extra",
            source_refs={
                "source_key": "the_racing_api",
                "external_runner_id": "pg-coupled-extra-id",
            },
        )

        with self.assertRaises(RaceLiveInitializationError):
            apply_race_live_initialization(manifest)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class CoupledRunnerRefreshPostgresRemediationTests(TransactionTestCase):
    reset_sequences = True
    NOW = multiregion_tests.RaceLiveRacecardRefreshBehaviorTests.NOW
    setUp = multiregion_tests.RaceLiveRacecardRefreshBehaviorTests.setUp

    def test_refresh_persists_both_shared_number_legacy_rows_by_external_id(self):
        field_names = {
            field.name for field in models.RaceEventRunner._meta.fields
        }
        self.assertIn(
            "external_runner_id",
            field_names,
            "racecard refresh 需要 legacy external identity 列",
        )

        decision = race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="b" * 64,
            normalized_racecard={
                "external_race_id": "fr-refresh-1",
                "off_time": "2026-07-20T13:05:00+00:00",
                "region": "FR",
                "course": "ParisLongchamp",
                "race_name": "France Racecard Refresh",
                "race_status": "Racecard",
                "participants": (
                    {
                        "external_runner_id": "runner-1",
                        "horse_name": "Alpha",
                        "number": "1",
                        "draw": "3",
                        "jockey_name": "Alpha Jockey",
                        "status": "declared",
                    },
                    {
                        "external_runner_id": "runner-2",
                        "horse_name": "Beta",
                        "number": "1",
                        "draw": "5",
                        "jockey_name": "Beta Jockey",
                        "status": "declared",
                    },
                ),
            },
        )

        self.assertTrue(decision.applied, decision.reason)
        self.assertEqual(
            models.RaceEventParticipant.objects.filter(
                event=self.event
            ).count(),
            2,
        )
        self.assertEqual(
            models.RaceEventParticipantSourceIdentity.objects.filter(
                participant__event=self.event
            ).count(),
            2,
        )
        current = models.RaceEventProjectionControl.objects.get(
            event=self.event
        ).current_racecard_revision
        self.assertEqual(current.items.count(), 2)
        self.assertEqual(
            list(
                models.RaceEventRunner.objects.filter(event=self.event)
                .order_by("sort_order")
                .values_list(
                    "external_runner_id",
                    "horse_number",
                    "horse_name",
                )
            ),
            [
                ("runner-1", "1", "Alpha"),
                ("runner-2", "1", "Beta"),
            ],
        )


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
@override_settings(
    RACE_LIVE_SCHEDULER_ENABLED=False,
    RACE_LIVE_MONITOR_ENABLED=False,
    RACE_LIVE_ENABLED_REGIONS=(),
)
class RollbackMaintenancePostgresRemediationTests(TransactionTestCase):
    reset_sequences = True
    NOW = gate_tests.RollbackGateBehaviorRemediationTests.NOW
    IMAGE_ID = gate_tests.RollbackGateBehaviorRemediationTests.IMAGE_ID
    ENV_DIGEST = gate_tests.RollbackGateBehaviorRemediationTests.ENV_DIGEST
    APPROVED_COMMIT = (
        gate_tests.RollbackGateBehaviorRemediationTests.APPROVED_COMMIT
    )
    REGISTRY_DIGEST = (
        gate_tests.RollbackGateBehaviorRemediationTests.REGISTRY_DIGEST
    )
    COVERAGE_DIGEST = (
        gate_tests.RollbackGateBehaviorRemediationTests.COVERAGE_DIGEST
    )

    def setUp(self):
        with transaction.atomic():
            gate_tests.RollbackGateBehaviorRemediationTests.setUp(self)

    _builder = gate_tests.RollbackGateBehaviorRemediationTests._builder
    _transition = gate_tests.RollbackGateBehaviorRemediationTests._transition
    _bundle = gate_tests.RollbackGateBehaviorRemediationTests._bundle
    _manifest_digest = staticmethod(
        gate_tests.RollbackGateBehaviorRemediationTests._manifest_digest
    )
    _transition_kwargs = (
        gate_tests.RollbackGateBehaviorRemediationTests._transition_kwargs
    )
    _policy_state = gate_tests.RollbackGateBehaviorRemediationTests._policy_state

    def _restore_kwargs_for_manifest(self, manifest):
        kwargs = {
            "event_id": self.event.pk,
            "planned_policy_snapshot": manifest[
                "planned_policy_snapshot"
            ],
            "expected_provisional_revision_id": manifest[
                "expected_provisional_revision_id"
            ],
            "expected_allowlist_version": manifest[
                "expected_allowlist_version"
            ],
            "expected_publication_id": manifest[
                "expected_publication_id"
            ],
            "expected_manifest_sha256": self._manifest_digest(manifest),
            "expected_tracking_lock_version": manifest[
                "expected_tracking_lock_version"
            ],
            "now": self.NOW,
        }
        if "expected_current_revision_id" in inspect.signature(
            race_events.restore_race_live_provisional_policies
        ).parameters:
            kwargs["expected_current_revision_id"] = manifest[
                "expected_current_revision_id"
            ]
        return kwargs

    def test_direct_and_due_claims_cannot_cross_atomic_maintenance(self):
        manifest = self._bundle()["manifest"]
        barrier = Barrier(3)

        def enter_maintenance():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return self._transition()(
                    **self._transition_kwargs(manifest, apply=True)
                )
            finally:
                connections.close_all()

        def direct_claim():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return race_events.claim_race_event_live_tracking(
                    event_id=self.event.pk,
                    expected_owner_generation=self.control.owner_generation,
                    now=self.NOW,
                    ttl_seconds=120,
                )
            finally:
                connections.close_all()

        def due_claim():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return race_events.claim_due_race_event_live_tracking(
                    now=self.NOW,
                    batch_size=10,
                    ttl_seconds=120,
                    enabled_regions=(models.RacingRegion.FRANCE,),
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as pool:
            maintenance_future = pool.submit(enter_maintenance)
            direct_future = pool.submit(direct_claim)
            due_future = pool.submit(due_claim)
            maintenance = maintenance_future.result(timeout=15)
            direct = direct_future.result(timeout=15)
            due = due_future.result(timeout=15)

        self.assertEqual(maintenance["reason"], "maintenance_applied")
        self.assertFalse(direct.claimed)
        self.assertEqual(due, ())
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertIsNone(self.tracking.claim_expires_at)
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode",
                    "version",
                )
            ),
            {(models.RaceLivePublicationMode.OFF, 11)},
        )

    def test_three_stage_restore_replay_and_event_before_coarse(self):
        manifest = self._bundle()["manifest"]
        maintenance = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertEqual(maintenance["reason"], "maintenance_applied")
        restore_kwargs = self._restore_kwargs_for_manifest(manifest)

        out_of_order = race_events.restore_race_live_provisional_policies(
            phase="event",
            **restore_kwargs,
        )
        self.assertFalse(out_of_order.allowed)
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode",
                    "version",
                )
            ),
            {(models.RaceLivePublicationMode.OFF, 11)},
        )

        coarse = race_events.restore_race_live_provisional_policies(
            phase="coarse",
            **restore_kwargs,
        )
        self.assertTrue(coarse.allowed, coarse.reason)
        event_key = (
            f"{models.RaceLivePublicationScopeType.EVENT}:"
            f"{self.event.pk}"
        )
        states = {
            f"{row.scope_type}:{row.scope_key}": (row.mode, row.version)
            for row in models.RaceLivePublicationPolicy.objects.all()
        }
        self.assertEqual(
            states[event_key],
            (models.RaceLivePublicationMode.OFF, 11),
        )
        self.assertEqual(
            {
                state
                for key, state in states.items()
                if key != event_key
            },
            {(models.RaceLivePublicationMode.PROVISIONAL_PUBLIC, 12)},
        )
        validation = race_events.validate_race_live_provisional_rollback_target(
            event_id=self.event.pk,
            now=self.NOW,
            expected_provisional_revision_id=self.provisional.pk,
            planned_policy_snapshot=manifest[
                "planned_policy_snapshot"
            ],
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
        )
        self.assertTrue(validation.allowed, validation.reason)

        before_replay = self._policy_state()
        replay = race_events.restore_race_live_provisional_policies(
            phase="coarse",
            **restore_kwargs,
        )
        self.assertTrue(replay.allowed, replay.reason)
        self.assertEqual(self._policy_state(), before_replay)

        event_restore = race_events.restore_race_live_provisional_policies(
            phase="event",
            **restore_kwargs,
        )
        self.assertTrue(event_restore.allowed, event_restore.reason)
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode",
                    "version",
                )
            ),
            {
                (
                    models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                    12,
                )
            },
        )
        before_replay = self._policy_state()
        replay = race_events.restore_race_live_provisional_policies(
            phase="event",
            **restore_kwargs,
        )
        self.assertTrue(replay.allowed, replay.reason)
        self.assertEqual(self._policy_state(), before_replay)

    def test_coarse_restore_rejects_current_pointer_drift_zero_write(self):
        manifest = self._bundle()["manifest"]
        maintenance = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertEqual(maintenance["reason"], "maintenance_applied")
        self.control.refresh_from_db()
        self.control.current_result_revision = None
        self.control.save(
            update_fields=(
                "current_result_revision",
                "updated_at",
            )
        )
        before = self._policy_state()

        decision = race_events.restore_race_live_provisional_policies(
            phase="coarse",
            **self._restore_kwargs_for_manifest(manifest),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("current", decision.reason)
        self.assertEqual(self._policy_state(), before)

    def test_event_restore_rejects_current_pointer_drift_after_coarse(self):
        manifest = self._bundle()["manifest"]
        maintenance = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertEqual(maintenance["reason"], "maintenance_applied")
        restore_kwargs = self._restore_kwargs_for_manifest(manifest)
        coarse = race_events.restore_race_live_provisional_policies(
            phase="coarse",
            **restore_kwargs,
        )
        self.assertTrue(coarse.allowed, coarse.reason)
        self.control.refresh_from_db()
        self.control.current_result_revision = None
        self.control.save(
            update_fields=(
                "current_result_revision",
                "updated_at",
            )
        )
        before = self._policy_state()

        decision = race_events.restore_race_live_provisional_policies(
            phase="event",
            **self._restore_kwargs_for_manifest(manifest),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("current", decision.reason)
        self.assertEqual(self._policy_state(), before)
