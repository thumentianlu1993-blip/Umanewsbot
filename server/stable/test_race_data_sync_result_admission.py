from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from stable import models
from stable.services import race_events
from stable.services.race_data_sync_enrollment import parse_standing_policy
from stable.services.race_data_sync_pipeline import (
    _ROSTER_ALLOWED_FIELDS,
    build_race_data_provider_roster,
    resolve_race_data_provider_route,
)
from stable.services.race_data_sync_results import (
    apply_data_sync_result_observation,
)
from stable.test_race_data_sync_providers import (
    NOW,
    REGISTRY_ACTIVATION,
    REGISTRY_ENTRY,
    REGISTRY_MEMBERSHIP,
    REGISTRY_ROOT,
    SHA,
)


def _sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@override_settings(
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api", "jra"),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_LIVE_TRA_REGISTRY_SHA256=SHA,
    RACE_EVENT_LIFECYCLE_ENABLED=True,
    RACE_EVENT_LIFECYCLE_MODE="enforce",
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=REGISTRY_ROOT,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(
        REGISTRY_MEMBERSHIP
    ),
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class DataSyncResultAdmissionTests(TestCase):
    def setUp(self):
        self._policy_directory = TemporaryDirectory()
        self.addCleanup(self._policy_directory.cleanup)
        self.roster = build_race_data_provider_roster(configuration_only=True)
        route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            data_kinds=("race_time", "racecard", "result"),
        )
        self.assertIsNotNone(route)
        policy = {
            "schema_version": 2,
            "policy_id": "test-data-sync-standing-policy-v2",
            "approved_by": "test-reviewer",
            "approved_at": NOW.isoformat(),
            "valid_from": (NOW - timedelta(days=1)).isoformat(),
            "valid_until": (NOW + timedelta(days=30)).isoformat(),
            "routes": [
                {
                    "country_region": models.RacingRegion.JAPAN,
                    "provider": "the_racing_api",
                    "region_code": "japan_jra",
                    "identity_namespace": "the_racing_api-race-v1",
                    "route_digest": route.route_digest,
                    "data_kinds": ["race_time", "racecard", "result"],
                    "enrollment_eligible": True,
                    "tiebreak_order": 1,
                }
            ],
            "visibility_statuses": [models.RaceEventVisibility.PUBLISHED],
            "new_enrollment_statuses": [
                models.RaceEventStatus.POSTPONED,
                models.RaceEventStatus.SCHEDULED,
            ],
            "continuation_statuses": [
                models.RaceEventStatus.FINISHED,
                models.RaceEventStatus.POSTPONED,
                models.RaceEventStatus.RUNNING,
                models.RaceEventStatus.SCHEDULED,
            ],
        }
        raw = json.dumps(policy, indent=2).encode()
        policy_path = Path(self._policy_directory.name) / "standing_policy.json"
        policy_path.write_bytes(raw)
        self.admission_policy_digest = parse_standing_policy(policy).digest
        policy_override = override_settings(
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE=str(policy_path),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=(
                hashlib.sha256(raw).hexdigest()
            ),
        )
        policy_override.enable()
        self.addCleanup(policy_override.disable)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-result-admission",
            original_name="Data Sync Result Admission",
            chinese_name="自动赛果准入",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW - timedelta(minutes=10),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
            owner_manifest_sha256="e" * 64,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
        )
        self.lifecycle = models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.ENFORCE,
            schedule_generation=1,
            enrollment_manifest_sha256="e" * 64,
            manifest_data={
                "race_data_sync": {
                    "standing_policy_digest": self.admission_policy_digest,
                    "manifest_sha256": "e" * 64,
                    "entry_sha256": "a" * 64,
                    "owner_generation": 1,
                }
            },
        )
        self.source = self._source("the_racing_api", "licensed_api", "api-result")
        self.enrollment = models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=self.source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest=self.admission_policy_digest,
            route_digest=route.route_digest,
            event_snapshot_sha256="d" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="e" * 64,
            entry_sha256="a" * 64,
            effective_at=NOW - timedelta(days=1),
        )
        for runner_id, name, number in (
            ("horse-1", "Alpha", "1"),
            ("horse-2", "Beta", "2"),
        ):
            models.RaceEventRunner.objects.create(
                event=self.event,
                external_runner_id=runner_id,
                horse_name=name,
                horse_number=number,
                source_refs={self.source.source_key: runner_id},
            )

    def _source(self, source_key, source_class, external_id):
        source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key=source_key,
            region_code="japan_jra",
            identity_namespace=f"{source_key}-race-v1",
            external_race_id=external_id,
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/v1/results/api-result",
            evidence_sha256="a" * 64,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.roster.registry_digest,
            identity_fields={"source_class": source_class},
        )
        return source

    def _rows(self, first_name="Alpha", first_position=1):
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

    def _observation(
        self,
        source,
        source_class,
        rows,
        *,
        observed_at=NOW,
        race_status="complete",
        result_phase=models.RaceResultPhase.OFFICIAL,
        provenance_overrides=None,
    ):
        payload = {
            "external_race_id": source.external_race_id,
            "off_time": self.event.race_datetime.isoformat(),
            "region": "japan_jra",
            "course": "Tokyo",
            "race_name": "Data Sync Result Admission",
            "race_status": race_status,
            "participants": rows,
        }
        field_provenance = {
            "provider": source.source_key,
            "region": source.region_code,
            "source_class": source_class,
            "registry_digest": self.roster.registry_digest,
            "contract_version": next(
                entry.contract_version
                for entry in self.roster.entries
                if entry.provider == source.source_key
            ),
            "contract_digest": next(
                entry.contract_digest
                for entry in self.roster.entries
                if entry.provider == source.source_key
            ),
            "automation_allowed": True,
        }
        field_provenance.update(provenance_overrides or {})
        return models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=observed_at,
            source_updated_at=observed_at,
            parser_version="test-v1",
            raw_sha256=_sha(payload),
            normalized_sha256=_sha(payload),
            result_phase=result_phase,
            normalized_payload=payload,
            field_provenance=field_provenance,
        )

    def test_result_projects_through_data_sync_admission(self):
        observation = self._observation(self.source, "licensed_api", self._rows())

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
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(self.event.results.count(), 2)

    def test_result_shadow_only_when_admission_evidence_drifts(self):
        self.lifecycle.manifest_data = {
            "race_data_sync": {"standing_policy_digest": "9" * 64}
        }
        self.lifecycle.save(update_fields=("manifest_data",))
        observation = self._observation(self.source, "licensed_api", self._rows())

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertFalse(decision.projected)
        revision = models.RaceEventRevision.objects.get(pk=decision.revision_id)
        self.assertIsNone(revision.published_at)
        self.assertEqual(revision.decision_reason, "lifecycle_evidence_drift")
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)

    def test_result_rejected_on_dual_authority(self):
        registry = models.RaceEventLifecycleEnforceRegistry.objects.create(
            root_sha256=REGISTRY_ROOT,
            generation=1,
            membership_sha256=REGISTRY_MEMBERSHIP,
            member_count=1,
            state="active",
            is_active=True,
            activation_id=REGISTRY_ACTIVATION,
            approved_commit="6" * 40,
            selector_scope={},
            scope_sha256="7" * 64,
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
            source_enrollment_sha256="f" * 64,
            schedule_generation=1,
            schedule_hash="0" * 64,
            country_region=self.event.country_region,
            timezone_name=self.event.timezone_name,
            frozen_snapshot={},
        )
        observation = self._observation(self.source, "licensed_api", self._rows())

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "lifecycle_authority_conflict")
        self.assertEqual(models.RaceEventRevision.objects.count(), 0)

    def test_public_read_visible_through_data_sync_admission(self):
        observation = self._observation(self.source, "licensed_api", self._rows())
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected, applied)

        detail = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=NOW + timedelta(seconds=1),
        )

        self.assertTrue(detail.visible, detail.reason)
        self.assertEqual(detail.reason, "data_sync_public_read_allowed")

    def test_public_read_rejected_when_admission_evidence_drifts(self):
        observation = self._observation(self.source, "licensed_api", self._rows())
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected, applied)
        self.lifecycle.manifest_data = {
            "race_data_sync": {"standing_policy_digest": "9" * 64}
        }
        self.lifecycle.save(update_fields=("manifest_data",))

        detail = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=NOW + timedelta(seconds=1),
        )

        self.assertFalse(detail.visible)
