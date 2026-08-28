from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import hashlib
import json
from unittest.mock import patch

from django.test import TestCase

from stable import models
from stable.services import race_data_sync_control
from stable.services.race_data_sync_results import (
    apply_data_sync_result_observation,
)


NOW = datetime(2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc)


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RaceDataSyncResultApplicationTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-result",
            original_name="Data Sync Result",
            chinese_name="自动赛果",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW - timedelta(minutes=10),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
        )
        self.source = self._source(
            "the_racing_api", "licensed_api", "api-result"
        )

    def _source(self, source_key, source_class, external_id):
        return models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key=source_key,
            region_code="japan_jra",
            identity_namespace=f"{source_key}-race-v1",
            external_race_id=external_id,
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            identity_fields={"source_class": source_class},
        )

    def _observation(self, source, source_class, rows, *, observed_at=NOW):
        payload = {
            "external_race_id": source.external_race_id,
            "off_time": self.event.race_datetime.isoformat(),
            "region": "japan_jra",
            "course": "Tokyo",
            "race_name": "Data Sync Result",
            "race_status": "complete",
            "participants": rows,
        }
        return models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=observed_at,
            source_updated_at=observed_at,
            parser_version="test-v1",
            raw_sha256=_sha(payload),
            normalized_sha256=_sha(payload),
            result_phase=models.RaceResultPhase.OFFICIAL,
            normalized_payload=payload,
            field_provenance={
                "provider": source.source_key,
                "source_class": source_class,
                "automation_allowed": True,
            },
        )

    def _claim_guard(
        self,
        *,
        expires_at=NOW + timedelta(minutes=4),
        data_kind=models.RaceDataSyncDataKind.RESULT,
    ):
        entry_sha256 = "a" * 64
        route_digest = "b" * 64
        tracking = self.event.live_tracking
        tracking.claim_generation = 1
        tracking.active_attempt_token = "result-claim-1"
        tracking.claim_expires_at = expires_at
        tracking.save(
            update_fields=(
                "claim_generation",
                "active_attempt_token",
                "claim_expires_at",
            )
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=self.source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="c" * 64,
            route_digest=route_digest,
            event_snapshot_sha256="d" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="e" * 64,
            entry_sha256=entry_sha256,
            effective_at=NOW,
        )
        models.RaceEventLiveProviderCheckpoint.objects.create(
            tracking=tracking,
            source_key=self.source.source_key,
            data_kind=data_kind,
            next_poll_at=NOW,
            lock_version=0,
        )
        checkpoint_plan = (
            {
                "source_key": self.source.source_key,
                "data_kind": data_kind,
                "lock_version": 0,
            },
        )
        plan_sha256 = race_data_sync_control._claim_plan_sha256(
            event_id=self.event.pk,
            enrollment_generation=1,
            owner_generation=1,
            claim_generation=1,
            attempt_token="result-claim-1",
            enrollment_entry_sha256=entry_sha256,
            route_digest=route_digest,
            checkpoint_plan=checkpoint_plan,
        )
        return race_data_sync_control.RaceDataSyncClaim(
            event_id=self.event.pk,
            enrollment_generation=1,
            owner_generation=1,
            claim_generation=1,
            attempt_token="result-claim-1",
            enrollment_entry_sha256=entry_sha256,
            route_digest=route_digest,
            checkpoint_plan=checkpoint_plan,
            plan_sha256=plan_sha256,
        )

    @staticmethod
    def _rows(first_name="Alpha", first_position=1):
        return [
            {
                "external_runner_id": "horse-1",
                "horse_name": first_name,
                "reported_finish_position": first_position,
                "status": models.RaceEventRevisionItemStatus.FINISHED,
                "number": "1",
            },
            {
                "external_runner_id": "horse-2",
                "horse_name": "Beta",
                "reported_finish_position": 2,
                "status": models.RaceEventRevisionItemStatus.FINISHED,
                "number": "2",
            },
        ]

    def test_complete_result_projects_and_finishes_event_without_human_review(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(decision.action, "applied")
        self.assertTrue(decision.projected)
        self.event.refresh_from_db()
        self.control.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(self.event.result_confirmed_at, NOW)
        self.assertEqual(
            self.control.current_result_revision_id,
            decision.revision_id,
        )
        results = list(self.event.results.order_by("finish_position"))
        self.assertEqual([row.finish_position for row in results], [1, 2])
        self.assertEqual([row.reported_finish_position for row in results], [1, 2])
        self.assertTrue(all(row.is_confirmed for row in results))
        self.assertEqual(
            models.RaceEventLifecycleTransition.objects.get().reason_code,
            "data_sync_complete_result",
        )

    def test_superseded_claim_cannot_project_result_before_completion_cas(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        guard = self._claim_guard()
        tracking = self.event.live_tracking
        tracking.claim_generation = 2
        tracking.active_attempt_token = "result-claim-2"
        tracking.save(
            update_fields=("claim_generation", "active_attempt_token")
        )

        with patch("stable.services.race_data_sync_results.timezone.now", return_value=NOW):
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW,
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=guard,
            )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_cas_stale")
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_expired_claim_cannot_project_result(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        guard = self._claim_guard(expires_at=NOW)

        with patch("stable.services.race_data_sync_results.timezone.now", return_value=NOW):
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW,
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=guard,
            )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_expired")
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_claim_for_another_data_kind_cannot_project_result(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        guard = self._claim_guard(data_kind=models.RaceDataSyncDataKind.RACECARD)

        with patch("stable.services.race_data_sync_results.timezone.now", return_value=NOW):
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW,
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=guard,
            )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_plan_drift")
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_dead_heat_keeps_duplicate_reported_positions_with_unique_internal_order(self):
        rows = self._rows(first_position=1)
        rows[1]["reported_finish_position"] = 1
        observation = self._observation(self.source, "licensed_api", rows)
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(decision.action, "applied")
        results = list(self.event.results.order_by("finish_position"))
        self.assertEqual([row.finish_position for row in results], [1, 2])
        self.assertEqual([row.reported_finish_position for row in results], [1, 1])

    def test_lower_priority_result_is_recorded_but_does_not_replace_api(self):
        api = self._observation(self.source, "licensed_api", self._rows())
        first = apply_data_sync_result_observation(
            observation_id=api.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        official_source = self._source(
            "jra", "official_operator", "official-result"
        )
        official = self._observation(
            official_source,
            "official_operator",
            self._rows(first_name="Official Alpha"),
            observed_at=NOW + timedelta(minutes=1),
        )
        second = apply_data_sync_result_observation(
            observation_id=official.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1),
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(second.action, "recorded")
        self.assertFalse(second.projected)
        self.control.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, first.revision_id)
        self.assertEqual(self.event.results.get(finish_position=1).horse_name, "Alpha")

    def test_same_source_correction_requires_flag_then_replaces_current(self):
        first_observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        apply_data_sync_result_observation(
            observation_id=first_observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        correction = self._observation(
            self.source,
            "licensed_api",
            self._rows(first_name="Corrected Alpha"),
            observed_at=NOW + timedelta(minutes=2),
        )
        blocked = apply_data_sync_result_observation(
            observation_id=correction.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=2),
            project_current=True,
            correction_apply_enabled=False,
        )
        self.assertEqual(blocked.reason_code, "correction_apply_disabled")
        applied = apply_data_sync_result_observation(
            observation_id=correction.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=2),
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(applied.action, "applied")
        self.assertEqual(
            self.event.results.get(finish_position=1).horse_name,
            "Corrected Alpha",
        )
