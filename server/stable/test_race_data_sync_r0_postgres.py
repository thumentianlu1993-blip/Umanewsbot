"""PostgreSQL concurrency gates for the race-data R0 control plane."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, current_thread
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from stable import models
from stable.services import (
    race_data_sync_control,
    race_data_sync_enrollment,
    race_data_sync_results,
)
from stable.test_race_data_sync_r0 import audited_test_roster


NOW = datetime(2026, 8, 20, 4, 0, tzinfo=dt_timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row-lock semantics")
class RaceDataSyncR0PostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.roster, self.route = audited_test_roster()
        self.roster_patcher = patch(
            "stable.services.race_data_sync_pipeline.build_race_data_provider_roster",
            return_value=self.roster,
        )
        self.roster_patcher.start()
        self.addCleanup(self.roster_patcher.stop)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="race-data-r0-pg",
            original_name="Race data R0 PostgreSQL",
            chinese_name="赛事数据 R0 PostgreSQL",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW + timedelta(days=1),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 21),
            local_start_time=datetime(2026, 8, 21, 13, 0).time(),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="jra",
            region_code="japan",
            identity_namespace="jra-race-v1",
            external_race_id="20260821-tokyo-11-pg",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://jra.example.test/reviewed-proof",
            evidence_sha256=SHA_A,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )

    def tearDown(self):
        connections.close_all()
        super().tearDown()

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
            data_kinds=("racecard", "result"),
            now=NOW,
        )

    @staticmethod
    def _run_two(callable_):
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return callable_()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            try:
                return tuple(future.result(timeout=20) for future in futures)
            except TimeoutError as exc:  # pragma: no cover - evidence failure path
                raise AssertionError("R0 PostgreSQL control operation deadlocked") from exc

    @staticmethod
    def _run_pair(left, right):
        barrier = Barrier(2)

        def worker(callable_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return callable_()
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, left), executor.submit(worker, right)]
            try:
                return tuple(future.result(timeout=20) for future in futures)
            except TimeoutError as exc:  # pragma: no cover - evidence failure path
                raise AssertionError("R0 cross-path operation deadlocked") from exc

    def _claim(self):
        self.assertEqual(self._acquire().action, "acquired")
        return race_data_sync_control.claim_due_enrollments(
            now=NOW,
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("racecard", "result"),
        )[0]

    def _standing_policy(self):
        return {
            "schema_version": 1,
            "policy_id": "japan-r0-pg-reviewed",
            "approved_by": "postgres-concurrency-reviewer",
            "approved_at": NOW.isoformat(),
            "valid_from": (NOW - timedelta(days=1)).isoformat(),
            "valid_until": (NOW + timedelta(days=30)).isoformat(),
            "routes": [
                {
                    "country_region": models.RacingRegion.JAPAN,
                    "provider": "jra",
                    "region_code": "japan",
                    "identity_namespace": "jra-race-v1",
                    "route_digest": self.route.route_digest,
                    "data_kinds": ["racecard", "result"],
                }
            ],
            "visibility_statuses": [models.RaceEventVisibility.PUBLISHED],
            "event_statuses": [models.RaceEventStatus.SCHEDULED],
        }

    def _reviewed_manifest(self, *, reverse: bool = False):
        standing_policy = self._standing_policy()
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        models.RaceEventLiveProviderCheckpoint.objects.get_or_create(
            tracking=tracking,
            source_key="legacy-other-source",
            data_kind=models.RaceDataSyncDataKind.RACECARD,
            defaults={"next_poll_at": NOW},
        )
        models.RaceDataSyncEnrollment.objects.filter(event=self.event).update(
            standing_policy_digest=(
                race_data_sync_enrollment.parse_standing_policy(
                    standing_policy
                ).digest
            )
        )
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=standing_policy,
            cutoff=NOW + timedelta(seconds=1),
            horizon_days=30,
        )
        builder = (
            race_data_sync_enrollment.build_race_data_disenrollment_manifest
            if reverse
            else race_data_sync_enrollment.build_race_data_enrollment_manifest
        )
        return builder(
            census=census,
            selected_event_ids=(self.event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW + timedelta(seconds=1),
            apply_expires_at=NOW + timedelta(minutes=10),
        )

    @staticmethod
    def _fail_claim(claim, *, abort: bool = False):
        def fail():
            def apply_failure():
                return race_data_sync_control.fail_race_data_sync_claim(
                    event_id=claim.event_id,
                    expected_enrollment_generation=claim.enrollment_generation,
                    expected_owner_generation=claim.owner_generation,
                    expected_claim_generation=claim.claim_generation,
                    attempt_token=claim.attempt_token,
                    data_kinds=claim.data_kinds,
                    reason_code="provider_failed",
                    retry_at=NOW + timedelta(minutes=5),
                    now=NOW + timedelta(seconds=1),
                    checkpoint_plan=claim.checkpoint_plan,
                    expected_enrollment_entry_sha256=(
                        claim.enrollment_entry_sha256
                    ),
                    expected_plan_sha256=claim.plan_sha256,
                )

            if not abort:
                return apply_failure()
            try:
                with transaction.atomic():
                    decision = apply_failure()
                    if decision.action != "failed":
                        return decision
                    raise RuntimeError("force transaction rollback")
            except RuntimeError:
                return "rolled_back"

        return fail

    def test_concurrent_enrollment_acquire_has_one_owner_transition(self):
        results = self._run_two(self._acquire)
        self.assertEqual(
            sorted(result.action for result in results),
            ["acquired", "rejected"],
        )
        rejected = next(result for result in results if result.action == "rejected")
        self.assertEqual(rejected.reason_code, "owner_cas_stale")
        control = models.RaceEventProjectionControl.objects.get(event=self.event)
        self.assertEqual(control.owner_generation, 1)
        self.assertEqual(
            models.RaceDataSyncEnrollment.objects.filter(event=self.event).count(),
            1,
        )

    def test_concurrent_selectors_create_one_effective_parent_claim(self):
        self.assertEqual(self._acquire().action, "acquired")

        def claim():
            return race_data_sync_control.claim_due_enrollments(
                now=NOW,
                batch_size=10,
                ttl_seconds=60,
                enabled_providers=("jra",),
                enabled_regions=("japan",),
                enabled_data_kinds=("racecard", "result"),
            )

        results = self._run_two(claim)
        self.assertEqual(sum(len(result) for result in results), 1)
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertTrue(tracking.active_attempt_token)
        self.assertEqual(tracking.claim_generation, 2)

    def test_superseded_claim_cannot_project_result_on_postgres(self):
        self.event.race_datetime = NOW - timedelta(minutes=10)
        self.event.local_date = date(2026, 8, 20)
        self.event.status = models.RaceEventStatus.RUNNING
        self.event.save(
            update_fields=("race_datetime", "local_date", "status", "updated_at")
        )
        first = self._claim()
        second = race_data_sync_control.claim_due_enrollments(
            now=NOW + timedelta(seconds=61),
            batch_size=10,
            ttl_seconds=60,
            enabled_providers=("jra",),
            enabled_regions=("japan",),
            enabled_data_kinds=("racecard", "result"),
        )[0]
        self.assertNotEqual(first.attempt_token, second.attempt_token)
        self.assertIn(models.RaceDataSyncDataKind.RESULT, first.data_kinds)
        payload = {
            "external_race_id": self.source.external_race_id,
            "off_time": self.event.race_datetime.isoformat(),
            "region": "japan",
            "course": "Tokyo",
            "race_name": self.event.original_name,
            "race_status": "complete",
            "participants": [
                {
                    "external_runner_id": "runner-pg-1",
                    "horse_name": "PostgreSQL Winner",
                    "reported_finish_position": 1,
                    "status": models.RaceEventRevisionItemStatus.FINISHED,
                    "number": "1",
                }
            ],
        }
        observation = models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=NOW + timedelta(seconds=62),
            source_updated_at=NOW + timedelta(seconds=62),
            parser_version="pg-claim-guard-v1",
            raw_sha256=hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
            normalized_sha256=hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
            result_phase=models.RaceResultPhase.OFFICIAL,
            normalized_payload=payload,
            field_provenance={
                "provider": self.source.source_key,
                "source_class": "official_operator",
                "automation_allowed": True,
            },
        )

        with patch(
            "stable.services.race_data_sync_results.timezone.now",
            return_value=NOW + timedelta(seconds=62),
        ):
            decision = race_data_sync_results.apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW + timedelta(seconds=62),
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=first,
            )

        self.assertEqual(decision.reason_code, "claim_cas_stale")
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_failure_and_rotation_follow_one_lock_order_without_deadlock(self):
        claim = self._claim()

        def fail():
            return race_data_sync_control.fail_race_data_sync_claim(
                event_id=claim.event_id,
                expected_enrollment_generation=claim.enrollment_generation,
                expected_owner_generation=claim.owner_generation,
                expected_claim_generation=claim.claim_generation,
                attempt_token=claim.attempt_token,
                data_kinds=claim.data_kinds,
                reason_code="provider_failed",
                retry_at=NOW + timedelta(minutes=5),
                now=NOW + timedelta(seconds=1),
                checkpoint_plan=claim.checkpoint_plan,
                expected_enrollment_entry_sha256=claim.enrollment_entry_sha256,
                expected_plan_sha256=claim.plan_sha256,
            )

        def rotate():
            return race_data_sync_control.rotate_enrollment(
                event_id=self.event.pk,
                source_identity_id=self.source.pk,
                standing_policy_digest=SHA_A,
                route_digest=self.route.route_digest,
                event_snapshot_sha256=SHA_C,
                successor_manifest_sha256=SHA_C,
                successor_entry_sha256=SHA_A,
                expected_manifest_sha256=SHA_D,
                expected_owner_generation=1,
                data_kinds=("racecard", "result"),
                now=NOW + timedelta(seconds=1),
            )

        results = self._run_pair(fail, rotate)
        self.assertIn("failed", {result.action for result in results})
        self.assertTrue(
            {result.action for result in results}.intersection({"rotated", "rejected"})
        )
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, "")

    def test_failure_and_disenroll_follow_one_lock_order_without_deadlock(self):
        claim = self._claim()

        def fail():
            return race_data_sync_control.fail_race_data_sync_claim(
                event_id=claim.event_id,
                expected_enrollment_generation=claim.enrollment_generation,
                expected_owner_generation=claim.owner_generation,
                expected_claim_generation=claim.claim_generation,
                attempt_token=claim.attempt_token,
                data_kinds=claim.data_kinds,
                reason_code="provider_failed",
                retry_at=NOW + timedelta(minutes=5),
                now=NOW + timedelta(seconds=1),
            )

        def disenroll():
            return race_data_sync_control.disenroll(
                event_id=self.event.pk,
                expected_manifest_sha256=SHA_D,
                expected_owner_generation=1,
                now=NOW + timedelta(seconds=1),
            )

        results = self._run_pair(fail, disenroll)
        self.assertIn("failed", {result.action for result in results})
        self.assertTrue(
            {result.action for result in results}.intersection({"released", "rejected"})
        )
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, "")

    def test_failure_abort_and_rotation_have_no_deadlock_or_partial_failure_write(self):
        claim = self._claim()

        def fail_then_abort():
            try:
                with transaction.atomic():
                    decision = race_data_sync_control.fail_race_data_sync_claim(
                        event_id=claim.event_id,
                        expected_enrollment_generation=claim.enrollment_generation,
                        expected_owner_generation=claim.owner_generation,
                        expected_claim_generation=claim.claim_generation,
                        attempt_token=claim.attempt_token,
                        data_kinds=claim.data_kinds,
                        reason_code="provider_failed",
                        retry_at=NOW + timedelta(minutes=5),
                        now=NOW + timedelta(seconds=1),
                        checkpoint_plan=claim.checkpoint_plan,
                        expected_enrollment_entry_sha256=(
                            claim.enrollment_entry_sha256
                        ),
                        expected_plan_sha256=claim.plan_sha256,
                    )
                    self.assertEqual(decision.action, "failed")
                    raise RuntimeError("force transaction rollback")
            except RuntimeError:
                return "rolled_back"

        def rotate():
            return race_data_sync_control.rotate_enrollment(
                event_id=self.event.pk,
                source_identity_id=self.source.pk,
                standing_policy_digest=SHA_A,
                route_digest=self.route.route_digest,
                event_snapshot_sha256=SHA_C,
                successor_manifest_sha256=SHA_C,
                successor_entry_sha256=SHA_A,
                expected_manifest_sha256=SHA_D,
                expected_owner_generation=1,
                data_kinds=("racecard", "result"),
                now=NOW + timedelta(seconds=1),
            )

        failed, rotated = self._run_pair(fail_then_abort, rotate)
        self.assertEqual(failed, "rolled_back")
        self.assertIn(rotated.action, {"rotated", "rejected"})
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        checkpoint = models.RaceEventLiveProviderCheckpoint.objects.get(
            tracking=tracking,
            data_kind=models.RaceDataSyncDataKind.RACECARD,
        )
        if rotated.action == "rotated":
            self.assertEqual(tracking.active_attempt_token, "")
        else:
            self.assertEqual(rotated.reason_code, "active_claim_exists")
            self.assertEqual(tracking.active_attempt_token, claim.attempt_token)
        self.assertEqual(tracking.consecutive_failures, 0)
        self.assertEqual(checkpoint.consecutive_failures, 0)
        self.assertEqual(checkpoint.circuit_reason, "")

    def test_failure_and_manifest_rotation_share_checkpoint_before_source_order(self):
        claim = self._claim()
        successor = self._reviewed_manifest()

        def apply_manifest():
            return race_data_sync_enrollment.apply_race_data_enrollment_manifest(
                manifest=successor.as_dict(),
                expected_manifest_sha256=successor.manifest_sha256,
                current_commit="1" * 40,
                now=NOW + timedelta(seconds=1),
            )[0]

        failed, applied = self._run_pair(self._fail_claim(claim), apply_manifest)
        self.assertEqual(failed.action, "failed")
        self.assertIn(applied.action, {"rotated", "rejected"})
        if applied.action == "rejected":
            self.assertEqual(applied.reason_code, "active_claim_exists")

    def test_failure_and_manifest_reverse_share_checkpoint_before_source_order(self):
        claim = self._claim()
        reverse = self._reviewed_manifest(reverse=True)

        def apply_manifest():
            return race_data_sync_enrollment.apply_race_data_disenrollment_manifest(
                manifest=reverse.as_dict(),
                expected_manifest_sha256=reverse.manifest_sha256,
                current_commit="1" * 40,
                now=NOW + timedelta(seconds=1),
            )[0]

        failed, applied = self._run_pair(self._fail_claim(claim), apply_manifest)
        self.assertEqual(failed.action, "failed")
        self.assertIn(applied.action, {"released", "rejected"})
        if applied.action == "rejected":
            self.assertEqual(applied.reason_code, "active_claim_exists")

    def test_aborted_failure_and_manifest_rotation_leave_no_partial_failure_write(self):
        claim = self._claim()
        successor = self._reviewed_manifest()

        def apply_manifest():
            return race_data_sync_enrollment.apply_race_data_enrollment_manifest(
                manifest=successor.as_dict(),
                expected_manifest_sha256=successor.manifest_sha256,
                current_commit="1" * 40,
                now=NOW + timedelta(seconds=1),
            )[0]

        failed, applied = self._run_pair(
            self._fail_claim(claim, abort=True), apply_manifest
        )
        self.assertEqual(failed, "rolled_back")
        self.assertIn(applied.action, {"rotated", "rejected"})
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        checkpoints = models.RaceEventLiveProviderCheckpoint.objects.filter(
            tracking=tracking
        )
        self.assertEqual(tracking.consecutive_failures, 0)
        self.assertFalse(checkpoints.exclude(consecutive_failures=0).exists())
        self.assertFalse(checkpoints.exclude(circuit_reason="").exists())

    def test_initial_manifest_acquire_creates_optional_rows_before_source_and_aborts_cleanly(self):
        models.RaceEventProjectionControl.objects.filter(event=self.event).delete()
        standing_policy = self._standing_policy()
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=standing_policy,
            cutoff=NOW,
            horizon_days=30,
        )
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(self.event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(minutes=10),
        )
        sql_log = []

        def apply_then_abort():
            def capture(execute, sql, params, many, context):
                sql_log.append(sql)
                return execute(sql, params, many, context)

            try:
                with transaction.atomic(), connection.execute_wrapper(capture):
                    decision = (
                        race_data_sync_enrollment.apply_race_data_enrollment_manifest(
                            manifest=manifest.as_dict(),
                            expected_manifest_sha256=manifest.manifest_sha256,
                            current_commit="1" * 40,
                            now=NOW,
                        )[0]
                    )
                    self.assertEqual(decision.action, "acquired")
                    raise RuntimeError("force initial acquire rollback")
            except RuntimeError:
                return "rolled_back"

        def lock_source():
            with transaction.atomic():
                models.RaceResultSourceIdentity.objects.select_for_update().get(
                    pk=self.source.pk
                )
            return "locked"

        acquired, contender = self._run_pair(apply_then_abort, lock_source)
        self.assertEqual((acquired, contender), ("rolled_back", "locked"))

        normalized_sql = [statement.lower() for statement in sql_log]

        def first_index(fragment, *, require_for_update=False):
            return next(
                index
                for index, statement in enumerate(normalized_sql)
                if fragment in statement
                and (not require_for_update or "for update" in statement)
            )

        control_insert = first_index(
            'insert into "stable_raceeventprojectioncontrol"'
        )
        tracking_insert = first_index('insert into "stable_raceeventlivetracking"')
        source_lock = first_index(
            'from "stable_raceresultsourceidentity"', require_for_update=True
        )
        self.assertLess(control_insert, tracking_insert)
        self.assertLess(tracking_insert, source_lock)
        self.assertFalse(
            models.RaceEventProjectionControl.objects.filter(event=self.event).exists()
        )
        self.assertFalse(
            models.RaceEventLiveTracking.objects.filter(event=self.event).exists()
        )
        self.assertFalse(
            models.RaceDataSyncEnrollment.objects.filter(event=self.event).exists()
        )
        self.assertFalse(
            models.RaceEventLiveProviderCheckpoint.objects.filter(
                tracking__event=self.event
            ).exists()
        )

    def test_aborted_legacy_transfer_locks_all_source_checkpoints_before_source(self):
        control = models.RaceEventProjectionControl.objects.get(event=self.event)
        control.write_owner = models.RaceEventProjectionWriteOwner.LIVE
        control.owner_generation = 7
        control.owner_manifest_sha256 = SHA_C
        control.save(
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
        jra_checkpoint = models.RaceEventLiveProviderCheckpoint.objects.create(
            tracking=tracking,
            source_key="jra",
            data_kind=models.RaceDataSyncDataKind.RACECARD,
            next_poll_at=NOW,
        )
        other_checkpoint = models.RaceEventLiveProviderCheckpoint.objects.create(
            tracking=tracking,
            source_key="legacy-other-source",
            data_kind=models.RaceDataSyncDataKind.RESULT,
            next_poll_at=NOW,
        )
        baseline = race_data_sync_control.build_legacy_transfer_baseline(
            event_id=self.event.pk
        )
        receipt = {
            "schema_version": 1,
            "captured_at": NOW.isoformat(),
            "legacy_runtime": {
                "scheduler_enabled": False,
                "monitor_enabled": False,
                "allow_network": False,
                "racecard_apply_enabled": False,
                "result_apply_enabled": False,
            },
            "queues": {
                queue: {
                    "drained": True,
                    "message_count": 0,
                    "active_claim_count": 0,
                }
                for queue in ("race_live", "race_sync_v2")
            },
        }
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

        def canonical(value):
            return json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        manifest_raw = canonical(manifest)
        receipt_raw = canonical(receipt)
        approval = race_data_sync_control.build_legacy_transfer_approval(
            event_id=self.event.pk,
            candidate_commit="1" * 40,
            transfer_manifest_raw_sha256=hashlib.sha256(manifest_raw).hexdigest(),
            transfer_manifest_sha256=manifest["manifest_sha256"],
            runtime_receipt_raw_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            runtime_receipt_sha256=manifest["runtime_receipt_sha256"],
            approved_by="postgres-lock-reviewer",
            approved_at=NOW + timedelta(minutes=1),
            apply_expires_at=NOW + timedelta(minutes=30),
        )
        approval_raw = canonical(approval)
        approval_raw_sha256 = hashlib.sha256(approval_raw).hexdigest()

        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "transfer.json"
            receipt_path = Path(tmp) / "receipt.json"
            approval_path = Path(tmp) / "approval.json"
            manifest_path.write_bytes(manifest_raw)
            receipt_path.write_bytes(receipt_raw)
            approval_path.write_bytes(approval_raw)

            def transfer_then_abort():
                try:
                    with transaction.atomic():
                        decision = race_data_sync_control.transfer_legacy_enrollment(
                            event_id=self.event.pk,
                            transfer_manifest_path=manifest_path,
                            runtime_receipt_path=receipt_path,
                            approval_path=approval_path,
                            current_commit="1" * 40,
                            now=NOW + timedelta(minutes=2),
                        )
                        self.assertEqual(decision.action, "transferred")
                        raise RuntimeError("force transfer rollback")
                except RuntimeError:
                    return "rolled_back"

            def checkpoint_then_source():
                with transaction.atomic():
                    models.RaceEventLiveProviderCheckpoint.objects.select_for_update().get(
                        pk=other_checkpoint.pk
                    )
                    models.RaceResultSourceIdentity.objects.select_for_update().get(
                        pk=self.source.pk
                    )
                return "locked"

            with override_settings(
                RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256=(
                    approval_raw_sha256
                ),
                RACE_LIVE_RUNNER_MODE="disabled",
            ):
                transferred, contender = self._run_pair(
                    transfer_then_abort, checkpoint_then_source
                )

        self.assertEqual((transferred, contender), ("rolled_back", "locked"))
        control.refresh_from_db()
        jra_checkpoint.refresh_from_db()
        other_checkpoint.refresh_from_db()
        self.assertEqual(control.write_owner, models.RaceEventProjectionWriteOwner.LIVE)
        self.assertEqual(jra_checkpoint.next_poll_at, NOW)
        self.assertEqual(other_checkpoint.next_poll_at, NOW)

    def test_concurrent_snapshot_claim_has_one_owner(self):
        results = self._run_two(
            lambda: race_data_sync_control.claim_snapshot_lease(
                provider="jra",
                region="japan",
                scope_key="2026-08-21",
                data_kind="racecard",
                registry_digest=SHA_B,
                owner_token=current_thread().name,
                now=NOW,
                ttl_seconds=60,
            )
        )
        self.assertEqual(
            sorted(result.action for result in results),
            ["acquired", "busy"],
        )
        self.assertEqual(models.RaceDataSnapshotLease.objects.count(), 1)

    def test_concurrent_host_budget_reservations_allow_one_request(self):
        models.RaceLiveHostBudget.objects.create(
            host="race-data-pg.example.test",
            min_interval_ms=1_000,
        )
        results = self._run_two(
            lambda: race_data_sync_control.reserve_race_data_host_request(
                host="race-data-pg.example.test",
                minimum_interval_seconds=1,
                now=NOW,
            )
        )
        self.assertEqual(
            sorted((decision.reserved, decision.reason) for decision in results),
            [(False, "rate_limited"), (True, "reserved")],
        )
