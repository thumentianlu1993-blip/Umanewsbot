from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Barrier
from unittest import skipUnless

from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from stable import models
from stable.services import race_events


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class RaceLivePostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    NOW = datetime(2026, 7, 20, 14, 0, tzinfo=dt_timezone.utc)

    def _event(self, slug):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
        )

    def test_due_selector_skips_a_row_locked_by_another_scheduler(self):
        first = self._event("pg-selector-first")
        second = self._event("pg-selector-second")
        for event in (first, second):
            models.RaceEventProjectionControl.objects.create(
                event=event,
                write_owner=models.RaceEventProjectionWriteOwner.LIVE,
                owner_generation=1,
            )
            models.RaceEventLiveTracking.objects.create(
                event=event,
                tracking_enabled=True,
                next_poll_at=self.NOW,
            )

        def claim_one():
            close_old_connections()
            try:
                return race_events.claim_due_race_event_live_tracking(
                    now=self.NOW,
                    batch_size=1,
                    ttl_seconds=120,
                )
            finally:
                connections.close_all()

        with transaction.atomic():
            models.RaceEventLiveTracking.objects.select_for_update().get(event=first)
            with ThreadPoolExecutor(max_workers=1) as pool:
                claims = pool.submit(claim_one).result(timeout=10)

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].event_id, second.pk)
        first.live_tracking.refresh_from_db()
        second.live_tracking.refresh_from_db()
        self.assertEqual(first.live_tracking.active_attempt_token, "")
        self.assertNotEqual(second.live_tracking.active_attempt_token, "")

    def test_host_budget_serializes_two_simultaneous_reservations(self):
        models.RaceLiveHostBudget.objects.create(
            host="pg-source.example.test",
            min_interval_ms=1000,
        )
        barrier = Barrier(2)

        def reserve():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return race_events.reserve_race_live_host_request(
                    host="pg-source.example.test",
                    now=self.NOW,
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = [future.result(timeout=10) for future in (pool.submit(reserve), pool.submit(reserve))]

        self.assertEqual(sum(decision.reserved for decision in decisions), 1)
        self.assertEqual(
            sorted(decision.reason for decision in decisions),
            ["rate_limited", "reserved"],
        )
        budget = models.RaceLiveHostBudget.objects.get(host="pg-source.example.test")
        self.assertEqual(budget.lock_version, 1)

    def test_two_workers_can_only_create_one_revision_for_the_same_claim(self):
        event = self._event("pg-revision-contention")
        models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=4,
        )
        models.RaceEventLiveTracking.objects.create(
            event=event,
            state=models.RaceEventLiveState.AWAITING_RESULT,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=2,
            active_attempt_token="pg-claim-token",
            claim_expires_at=self.NOW + timedelta(minutes=2),
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="pg_fixture",
            external_race_id="pg-race-1",
        )
        participant = models.RaceEventParticipant.objects.create(
            event=event,
            stable_key="horse-1",
            canonical_name="Postgres Horse",
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant,
            source_identity=source,
            external_runner_id="runner-1",
        )
        payload = {
            "external_race_id": "pg-race-1",
            "participants": [
                {
                    "external_runner_id": "runner-1",
                    "official_finish_position": 1,
                    "status": "finished",
                    "number": "1",
                }
            ],
        }
        observation = models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=self.NOW,
            parser_version="pg-fixture-v1",
            raw_sha256="a" * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=payload
            ),
            result_phase=models.RaceResultPhase.PROVISIONAL,
            normalized_payload=payload,
        )
        barrier = Barrier(2)

        def apply_once():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return race_events.apply_race_result_observation_revision(
                    observation_id=observation.pk,
                    expected_owner_generation=4,
                    expected_claim_generation=2,
                    attempt_token="pg-claim-token",
                    now=self.NOW + timedelta(seconds=10),
                    source_authority="supplemental",
                    official_marker=False,
                    identity_valid=True,
                    payload_complete=True,
                    manual_lock_conflict=False,
                    project_current=False,
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = [future.result(timeout=10) for future in (pool.submit(apply_once), pool.submit(apply_once))]

        self.assertEqual(
            sorted(decision.action for decision in decisions),
            ["apply", "replay"],
            [(decision.action, decision.reason) for decision in decisions],
        )
        self.assertEqual(models.RaceEventRevision.objects.filter(event=event).count(), 1)
        control = models.RaceEventProjectionControl.objects.get(event=event)
        self.assertEqual(control.next_result_revision_no, 2)

    def test_deferred_guards_reject_cross_event_kind_and_forward_revision_links(self):
        first = self._event("pg-constraint-first")
        second = self._event("pg-constraint-second")
        control = models.RaceEventProjectionControl.objects.create(event=first)
        first_result = models.RaceEventRevision.objects.create(
            event=first,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256="1" * 64,
        )
        second_result = models.RaceEventRevision.objects.create(
            event=second,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256="2" * 64,
        )
        first_racecard = models.RaceEventRevision.objects.create(
            event=first,
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256="3" * 64,
        )
        future_result = models.RaceEventRevision.objects.create(
            event=first,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=2,
            phase=models.RaceResultPhase.OFFICIAL,
            content_sha256="4" * 64,
        )

        for invalid_revision in (second_result, first_racecard):
            with self.subTest(pointer_revision=invalid_revision.pk):
                with self.assertRaises(DatabaseError):
                    with transaction.atomic():
                        models.RaceEventProjectionControl.objects.filter(pk=control.pk).update(
                            current_result_revision=invalid_revision
                        )
                        with connection.cursor() as cursor:
                            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                models.RaceEventProjectionControl.objects.filter(pk=control.pk).update(
                    next_result_revision_no=2,
                    current_result_revision=future_result,
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        for invalid_supersedes in (second_result, first_racecard, future_result):
            with self.subTest(supersedes=invalid_supersedes.pk):
                with self.assertRaises(DatabaseError):
                    with transaction.atomic():
                        models.RaceEventRevision.objects.filter(pk=first_result.pk).update(
                            supersedes=invalid_supersedes
                        )
                        with connection.cursor() as cursor:
                            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
