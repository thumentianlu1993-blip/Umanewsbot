"""PostgreSQL concurrency contracts for race-data sync slice A."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, datetime, timedelta, timezone as dt_timezone
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import override_settings
from django.test import TransactionTestCase

from stable import models
from stable.services import race_events
from stable.services import race_data_sync_pipeline as pipeline


NOW = datetime(2026, 8, 2, 4, 0, tzinfo=dt_timezone.utc)
ALLOWED_FIELDS = (
    "local_start_time",
    "off_time",
    "participants.draw",
    "participants.horse_name",
    "participants.jockey_name",
    "participants.number",
    "participants.status",
    "status",
    "timezone_name",
)


@skipUnless(
    connection.vendor == "postgresql",
    "requires PostgreSQL row-lock semantics",
)
@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
    RACE_DATA_SYNC_ENABLED_FIELDS=ALLOWED_FIELDS,
)
class RaceDataSyncPipelineAPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="pg-race-data-sync-a",
            original_name="PostgreSQL Race Data Sync A",
            chinese_name="PostgreSQL 赛事资料同步 A",
            country_region=models.RacingRegion.HONG_KONG,
            racecourse="Sha Tin",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=datetime(
                2026, 8, 2, 7, 0, tzinfo=dt_timezone.utc
            ),
            timezone_name="Asia/Hong_Kong",
            local_date=date(2026, 8, 2),
            local_start_time=datetime(2026, 8, 2, 15, 0).time(),
            status=models.RaceEventStatus.SCHEDULED,
        )
        self.tra = self._source("the_racing_api")

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def _source(self, source_key: str):
        return models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key=source_key,
            external_race_id="hk-pg-2026-08-02-01",
            host=f"{source_key}.example.invalid",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
        )

    @staticmethod
    def _payload(*, jockey: str, race_status: str = "racecard"):
        payload = {
            "schema_version": 1,
            "external_race_id": "hk-pg-2026-08-02-01",
            "off_time": "2026-08-02T15:10:00+08:00",
            "region": "hong_kong",
            "course": "Sha Tin",
            "race_name": "PostgreSQL Race Data Sync A",
            "race_status": race_status,
            "participants": [
                {
                    "external_runner_id": "horse-pg-1",
                    "horse_name": "PostgreSQL Alpha",
                    "number": "1",
                    "draw": "3",
                    "jockey_name": jockey,
                    "status": models.RaceRunnerStatus.DECLARED,
                }
            ],
        }
        if race_status in {
            models.RaceEventStatus.CANCELLED,
            models.RaceEventStatus.POSTPONED,
        }:
            payload.update(
                {
                    "local_start_time": "15:10:00",
                    "timezone_name": "Asia/Macau",
                }
            )
        return payload

    def _observation(
        self,
        source,
        *,
        jockey: str,
        nonce: int,
        race_status: str = "racecard",
        source_updated_at: datetime | None = None,
    ):
        roster = pipeline.build_race_data_provider_roster()
        roster_entry = next(
            entry for entry in roster.entries if entry.provider == source.source_key
        )
        decision = race_events.record_race_result_observation(
            source_identity_id=source.pk,
            observed_at=NOW + timedelta(seconds=nonce),
            source_updated_at=(
                source_updated_at
                if source_updated_at is not None
                else NOW + timedelta(seconds=nonce)
            ),
            parser_version="pg-racecard-v1",
            raw_sha256=f"{nonce:x}".rjust(64, "a"),
            result_phase=models.RaceResultPhase.RACECARD,
            normalized_payload=self._payload(
                jockey=jockey,
                race_status=race_status,
            ),
            field_provenance={
                "provider": source.source_key,
                "region": "hong_kong",
                "source_class": roster_entry.source_class,
                "registry_digest": roster.registry_digest,
                "contract_version": roster_entry.contract_version,
                "contract_digest": roster_entry.contract_digest,
                "automation_allowed": True,
                "allowed_fields": ALLOWED_FIELDS,
            },
            parse_warnings=[],
            permission_classification="trusted_automation",
        )
        self.assertTrue(decision.recorded, decision.reason)
        return decision.observation

    def _run_concurrently(self, observations):
        barrier = Barrier(len(observations))

        def worker(observation_id):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return pipeline.reconcile_racecard_observation(
                    observation_id=observation_id,
                    expected_event_id=self.event.pk,
                    allow_schedule_apply=False,
                    task_id=f"pg-task-{observation_id}",
                    run_id=f"pg-run-{observation_id}",
                )
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=len(observations)) as executor:
            futures = [
                executor.submit(worker, observation.pk)
                for observation in observations
            ]
            try:
                results = [future.result(timeout=20) for future in futures]
            except TimeoutError as exc:
                self.fail("concurrent reconciliation deadlocked")
        close_old_connections()
        return results

    def test_same_observation_concurrent_delivery_writes_one_ledger_set(self):
        observation = self._observation(
            self.tra,
            jockey="TRA Jockey",
            nonce=1,
        )

        results = self._run_concurrently((observation, observation))

        self.assertEqual(
            sorted(result.status for result in results),
            ["applied", "replayed"],
        )
        self.assertEqual(
            models.RaceEventRunner.objects.filter(event=self.event).count(),
            1,
        )
        changes = models.RaceEventFieldChange.objects.filter(
            observation=observation,
            operation_mode="slice_a",
        )
        self.assertEqual(changes.count(), 5)
        self.assertEqual(
            changes.values("subject_type", "subject_key", "field_name").distinct().count(),
            5,
        )
        self.assertEqual(
            set(changes.values_list("field_name", flat=True)),
            {
                "horse_name",
                "horse_number",
                "barrier",
                "jockey_name",
                "running_status",
            },
        )
        schedule_changes = models.RaceEventFieldChange.objects.filter(
            observation=observation,
            operation_mode="slice_c",
        )
        self.assertEqual(schedule_changes.count(), 3)
        self.assertFalse(schedule_changes.filter(applied=True).exists())

    def test_same_source_equal_watermark_conflict_has_one_stable_winner(self):
        first_observation = self._observation(
            self.tra,
            jockey="TRA First Jockey",
            nonce=1,
            source_updated_at=NOW,
        )
        second_observation = self._observation(
            self.tra,
            jockey="TRA Second Jockey",
            nonce=2,
            source_updated_at=NOW,
        )

        results = self._run_concurrently(
            (first_observation, second_observation)
        )

        self.assertEqual(
            sorted(result.status for result in results),
            ["applied", "replayed"],
        )
        runners = models.RaceEventRunner.objects.filter(event=self.event)
        self.assertEqual(runners.count(), 1)
        self.assertIn(
            runners.get().jockey_name,
            {"TRA First Jockey", "TRA Second Jockey"},
        )
        jockey_changes = models.RaceEventFieldChange.objects.filter(
            event=self.event,
            subject_key="horse-pg-1",
            field_name="jockey_name",
        )
        self.assertEqual(jockey_changes.count(), 2)
        self.assertEqual(
            sorted(jockey_changes.values_list("decision", flat=True)),
            ["applied", "rejected"],
        )

    def test_schedule_candidates_concurrent_are_idempotent_and_never_apply(self):
        original = {
            "race_datetime": self.event.race_datetime,
            "local_start_time": self.event.local_start_time,
            "timezone_name": self.event.timezone_name,
            "status": self.event.status,
        }
        postponed = self._observation(
            self.tra,
            jockey="TRA Jockey",
            nonce=1,
            race_status=models.RaceEventStatus.POSTPONED,
        )
        cancelled = self._observation(
            self.tra,
            jockey="TRA Jockey",
            nonce=2,
            race_status=models.RaceEventStatus.CANCELLED,
        )

        results = self._run_concurrently((postponed, cancelled))

        self.assertEqual(
            sorted(result.status for result in results),
            ["applied", "replayed"],
        )
        self.event.refresh_from_db()
        self.assertEqual(
            {
                "race_datetime": self.event.race_datetime,
                "local_start_time": self.event.local_start_time,
                "timezone_name": self.event.timezone_name,
                "status": self.event.status,
            },
            original,
        )
        for observation in (postponed, cancelled):
            with self.subTest(observation=observation.pk):
                schedule_changes = models.RaceEventFieldChange.objects.filter(
                    observation=observation,
                    subject_type=models.RaceEventFieldSubjectType.EVENT,
                    operation_mode="slice_c",
                )
                self.assertEqual(schedule_changes.count(), 5)
                self.assertEqual(
                    set(schedule_changes.values_list("field_name", flat=True)),
                    {
                        "race_datetime",
                        "local_date",
                        "local_start_time",
                        "timezone_name",
                        "status",
                    },
                )
                self.assertFalse(schedule_changes.filter(applied=True).exists())
                self.assertEqual(
                    set(schedule_changes.values_list("decision", flat=True)),
                    {"rejected"},
                )


@skipUnless(
    connection.vendor == "postgresql",
    "requires PostgreSQL row-lock semantics",
)
class RaceDataRawCleanupPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "root"
        self.root.mkdir()
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="pg-race-data-cleanup",
            original_name="PG Cleanup",
            chinese_name="PG 清理",
            country_region=models.RacingRegion.HONG_KONG,
            racecourse="Sha Tin",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            local_date=date(2026, 8, 2),
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="pg-cleanup",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            automation_allowed=True,
        )
        self.counter = 0

    def _observation(self, *, path: Path, hold=False, age_seconds=10):
        self.counter += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raw", encoding="utf-8")
        digit = f"{self.counter:x}"[-1]
        normalized_digit = "0123456789abcdef"[(self.counter + 7) % 16]
        return models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=NOW,
            parser_version="pg-cleanup-v1",
            raw_sha256=digit * 64,
            normalized_sha256=normalized_digit * 64,
            result_phase=models.RaceResultPhase.RACECARD,
            normalized_payload={"nonce": self.counter},
            field_provenance={"raw_hold": hold},
            raw_artifact_path=str(path),
            raw_size_bytes=path.stat().st_size,
            retention_until=NOW - timedelta(seconds=age_seconds),
            permission_classification="trusted_automation",
        )

    def test_two_cleanup_workers_claim_one_raw_artifact_once(self):
        observation = self._observation(path=self.root / "once.json")
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return pipeline.cleanup_expired_race_data_raw_payloads(
                    now=NOW,
                    batch_size=10,
                )
            finally:
                connections["default"].close()

        with override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(worker) for _ in range(2)]
                results = [future.result(timeout=20) for future in futures]

        observation.refresh_from_db()
        self.assertEqual(sum(result.cleaned for result in results), 1)
        self.assertEqual(observation.raw_artifact_path, "")
        self.assertFalse((self.root / "once.json").exists())

    def test_held_rows_at_batch_front_do_not_starve_later_cleanup(self):
        self._observation(path=self.root / "held-1.json", hold=True, age_seconds=30)
        self._observation(path=self.root / "held-2.json", hold=True, age_seconds=20)
        cleanable = self._observation(
            path=self.root / "cleanable.json",
            hold=False,
            age_seconds=10,
        )

        with override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)):
            result = pipeline.cleanup_expired_race_data_raw_payloads(
                now=NOW,
                batch_size=2,
            )

        cleanable.refresh_from_db()
        self.assertEqual(result.held, 2)
        self.assertEqual(result.cleaned, 1)
        self.assertEqual(cleanable.raw_artifact_path, "")

    def test_more_than_fixed_scan_cap_held_rows_do_not_starve_cleanable(self):
        held_count = 10_001
        models.RaceResultObservation.objects.bulk_create(
            [
                models.RaceResultObservation(
                    source_identity=self.source,
                    observed_at=NOW - timedelta(days=1),
                    parser_version="pg-cleanup-v1",
                    raw_sha256=f"{index + held_count:064x}",
                    normalized_sha256=f"{index:064x}",
                    result_phase=models.RaceResultPhase.RACECARD,
                    normalized_payload={"held_nonce": index},
                    field_provenance={"raw_hold": True},
                    raw_artifact_path=str(self.root / f"held-bulk-{index}.json"),
                    raw_size_bytes=3,
                    retention_until=NOW - timedelta(days=1),
                    permission_classification="trusted_automation",
                )
                for index in range(held_count)
            ],
            batch_size=1_000,
        )
        cleanable = self._observation(
            path=self.root / "cleanable-after-fixed-cap.json",
            hold=False,
            age_seconds=10,
        )

        with override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)):
            result = pipeline.cleanup_expired_race_data_raw_payloads(
                now=NOW,
                batch_size=1_000,
            )

        cleanable.refresh_from_db()
        self.assertEqual(result.cleaned, 1)
        self.assertEqual(cleanable.raw_artifact_path, "")
        self.assertFalse((self.root / "cleanable-after-fixed-cap.json").exists())

    def test_cleanup_rechecks_hold_path_and_retention_after_candidate_read(self):
        original_path = self.root / "drift-original.json"
        replacement_path = self.root / "drift-replacement.json"
        observation = self._observation(path=original_path)
        replacement_path.write_text("replacement", encoding="utf-8")
        entered = Event()
        release = Event()
        real_resolve = Path.resolve

        def blocking_resolve(path, strict=False):
            resolved = real_resolve(path, strict=strict)
            if path == original_path:
                entered.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("cleanup recheck barrier timed out")
            return resolved

        def cleaner():
            close_old_connections()
            try:
                with override_settings(
                    RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)
                ):
                    return pipeline.cleanup_expired_race_data_raw_payloads(
                        now=NOW,
                        batch_size=10,
                    )
            finally:
                connections["default"].close()

        with patch.object(
            pipeline.Path,
            "resolve",
            autospec=True,
            side_effect=blocking_resolve,
        ):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(cleaner)
                self.assertTrue(entered.wait(timeout=10))
                models.RaceResultObservation.objects.filter(
                    pk=observation.pk
                ).update(
                    field_provenance={"raw_hold": True},
                    raw_artifact_path=str(replacement_path),
                    raw_size_bytes=replacement_path.stat().st_size,
                    retention_until=NOW + timedelta(days=1),
                )
                release.set()
                result = future.result(timeout=20)

        observation.refresh_from_db()
        self.assertEqual(result.cleaned, 0)
        self.assertGreaterEqual(result.skipped + result.held, 1)
        self.assertTrue(original_path.exists())
        self.assertTrue(replacement_path.exists())
        self.assertEqual(observation.raw_artifact_path, str(replacement_path))
        self.assertEqual(observation.field_provenance, {"raw_hold": True})
        self.assertGreater(observation.retention_until, NOW)

    def test_ancestor_symlink_swap_after_validation_cannot_delete_outside_file(self):
        ancestor = self.root / "ancestor"
        inside_path = ancestor / "same-name.json"
        observation = self._observation(path=inside_path)
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        outside_path = outside / "same-name.json"
        outside_path.write_text("outside", encoding="utf-8")
        backup = self.root / "ancestor-backup"
        real_unlink = os.unlink

        def swap_then_unlink(path, *args, **kwargs):
            ancestor.rename(backup)
            ancestor.symlink_to(outside, target_is_directory=True)
            real_unlink(path, *args, **kwargs)

        try:
            with override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)):
                with patch.object(pipeline.os, "unlink", side_effect=swap_then_unlink):
                    result = pipeline.cleanup_expired_race_data_raw_payloads(
                        now=NOW,
                        batch_size=10,
                    )
            observation.refresh_from_db()
            self.assertEqual(result.cleaned, 0)
            self.assertGreaterEqual(result.skipped, 1)
            self.assertEqual(outside_path.read_text(encoding="utf-8"), "outside")
            self.assertEqual(observation.raw_artifact_path, str(inside_path))
        finally:
            if ancestor.is_symlink():
                ancestor.unlink()
            if backup.exists():
                shutil.move(str(backup), str(ancestor))


@skipUnless(
    connection.vendor == "postgresql",
    "requires PostgreSQL trigger semantics",
)
class RaceEventFieldChangePostgresImmutableLedgerTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="pg-field-change-immutable",
            original_name="PG Immutable",
            chinese_name="PG 不可变",
            country_region=models.RacingRegion.HONG_KONG,
            racecourse="Sha Tin",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            local_date=date(2026, 8, 2),
        )
        self.change = models.RaceEventFieldChange.objects.create(
            event=self.event,
            subject_type=models.RaceEventFieldSubjectType.EVENT,
            subject_key=str(self.event.pk),
            field_name="racecourse",
            old_value="Old",
            new_value="New",
            decision="applied",
            applied=True,
        )

    def test_queryset_update_and_delete_are_rejected_by_database_trigger(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.RaceEventFieldChange.objects.filter(pk=self.change.pk).update(
                    new_value="Tampered"
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.RaceEventFieldChange.objects.filter(pk=self.change.pk).delete()
        self.assertTrue(
            models.RaceEventFieldChange.objects.filter(pk=self.change.pk).exists()
        )

    def test_model_save_and_delete_are_rejected_by_database_trigger(self):
        self.change.new_value = "Model Tamper"
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.change.save(update_fields=("new_value", "updated_at"))
        self.change.refresh_from_db()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.change.delete()
        self.assertTrue(
            models.RaceEventFieldChange.objects.filter(pk=self.change.pk).exists()
        )

    def test_native_sql_update_and_delete_are_rejected_by_database_trigger(self):
        table = models.RaceEventFieldChange._meta.db_table
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f'UPDATE "{table}" SET "decision" = %s WHERE "id" = %s',
                    ["rejected", self.change.pk],
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f'DELETE FROM "{table}" WHERE "id" = %s',
                    [self.change.pk],
                )
        self.assertTrue(
            models.RaceEventFieldChange.objects.filter(pk=self.change.pk).exists()
        )
