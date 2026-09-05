from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
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
class StalledEventRepairTests(TestCase):
    def setUp(self):
        self._artifact_directory = TemporaryDirectory()
        self.addCleanup(self._artifact_directory.cleanup)
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
        policy_path = Path(self._artifact_directory.name) / "standing_policy.json"
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
            slug="stalled-repair",
            original_name="Stalled Repair Cup",
            chinese_name="停滞修复杯",
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
            mode=models.RaceEventLifecycleMode.OFF,
            schedule_generation=1,
            manifest_data={},
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="api-result",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/v1/results/api-result",
            evidence_sha256="a" * 64,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.roster.registry_digest,
            identity_fields={"source_class": "licensed_api"},
        )
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
        payload = {
            "external_race_id": self.source.external_race_id,
            "off_time": self.event.race_datetime.isoformat(),
            "region": "japan_jra",
            "course": "Tokyo",
            "race_name": "Stalled Repair Cup",
            "race_status": "complete",
            "participants": [
                {
                    "external_runner_id": "horse-1",
                    "horse_name": "Alpha",
                    "reported_finish_position": 1,
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
            ],
        }
        self.observation = models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=NOW,
            source_updated_at=NOW,
            parser_version="test-v1",
            raw_sha256=_sha(payload),
            normalized_sha256=_sha(payload),
            result_phase=models.RaceResultPhase.OFFICIAL,
            normalized_payload=payload,
            field_provenance={
                "provider": self.source.source_key,
                "region": self.source.region_code,
                "source_class": "licensed_api",
                "registry_digest": self.roster.registry_digest,
                "contract_version": next(
                    entry.contract_version
                    for entry in self.roster.entries
                    if entry.provider == self.source.source_key
                ),
                "contract_digest": next(
                    entry.contract_digest
                    for entry in self.roster.entries
                    if entry.provider == self.source.source_key
                ),
                "automation_allowed": True,
            },
        )
        shadow = apply_data_sync_result_observation(
            observation_id=self.observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=False,
            correction_apply_enabled=True,
        )
        self.assertEqual(shadow.action, "recorded")
        self.revision_id = shadow.revision_id
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)

    def _dry_run(self):
        output = StringIO()
        call_command(
            "repair_data_sync_stalled_events",
            "--as-of",
            NOW.isoformat(),
            stdout=output,
        )
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "dry_run")
        return report

    def test_dry_run_reports_candidate_without_writes(self):
        report = self._dry_run()

        self.assertEqual(report["writes"], 0)
        self.assertRegex(report["candidate_sha256"], r"\A[0-9a-f]{64}\Z")
        self.assertEqual(len(report["entries"]), 1)
        entry = report["entries"][0]
        self.assertEqual(entry["event_id"], self.event.pk)
        self.assertTrue(entry["repairable"], entry)
        self.assertEqual(entry["revision_id"], self.revision_id)
        self.assertTrue(Path(report["candidate_file"]).exists())
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)
        self.assertEqual(
            models.RaceEventLifecycleControl.objects.get(event=self.event).mode,
            models.RaceEventLifecycleMode.OFF,
        )

    def test_apply_repairs_stalled_event(self):
        models.RaceLiveAlertIncident.objects.create(
            alert_type=models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
            scope_type="data_sync_event",
            scope_key=str(self.event.pk),
            dedupe_key="repair-stalled-1",
            status=models.RaceLiveAlertIncidentStatus.OPEN,
        )
        report = self._dry_run()

        output = StringIO()
        call_command(
            "repair_data_sync_stalled_events",
            "--apply",
            "--as-of",
            NOW.isoformat(),
            "--candidate-file",
            report["candidate_file"],
            "--expected-sha256",
            report["candidate_sha256"],
            stdout=output,
        )
        applied_report = json.loads(output.getvalue())

        self.assertEqual(applied_report["applied_count"], 1, applied_report)
        self.assertEqual(applied_report["rejected_count"], 0, applied_report)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertIsNotNone(self.event.result_confirmed_at)
        revision = models.RaceEventRevision.objects.get(pk=self.revision_id)
        self.assertIsNotNone(revision.published_at)
        self.assertTrue(
            models.RaceEventRevisionPublication.objects.filter(
                revision_id=self.revision_id
            ).exists()
        )
        self.assertEqual(self.event.results.count(), 2)
        self.assertTrue(
            models.OperationLog.objects.filter(
                action_type="race_data_sync_stalled_repair",
                target_id=str(self.event.pk),
            ).exists()
        )
        incident = models.RaceLiveAlertIncident.objects.get(
            scope_key=str(self.event.pk)
        )
        self.assertEqual(
            incident.status, models.RaceLiveAlertIncidentStatus.RESOLVED
        )
        public = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=timezone_now(),
        )
        self.assertTrue(public.visible, public.reason)

    def test_apply_rejects_sha_mismatch(self):
        report = self._dry_run()

        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command(
                "repair_data_sync_stalled_events",
                "--apply",
                "--as-of",
                NOW.isoformat(),
                "--candidate-file",
                report["candidate_file"],
                "--expected-sha256",
                "0" * 64,
                stdout=StringIO(),
            )
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)

    def test_apply_rejects_entry_closed_since_dry_run(self):
        report = self._dry_run()
        models.RaceEventRevision.objects.filter(pk=self.revision_id).update(
            published_at=NOW
        )

        output = StringIO()
        call_command(
            "repair_data_sync_stalled_events",
            "--apply",
            "--as-of",
            NOW.isoformat(),
            "--candidate-file",
            report["candidate_file"],
            "--expected-sha256",
            report["candidate_sha256"],
            stdout=output,
        )
        applied_report = json.loads(output.getvalue())

        self.assertEqual(applied_report["applied_count"], 0, applied_report)
        self.assertEqual(applied_report["rejected_count"], 1, applied_report)
        self.assertEqual(
            applied_report["results"][0]["reason"],
            "no_unpublished_terminal_revision",
        )

    def test_manual_lock_event_is_not_repaired(self):
        self.event.manual_lock_flags = {"race_datetime": True}
        self.event.save(update_fields=("manual_lock_flags",))

        report = self._dry_run()

        self.assertEqual(len(report["entries"]), 1)
        entry = report["entries"][0]
        self.assertFalse(entry["repairable"], entry)
        self.assertEqual(entry["reason_code"], "manual_lock_present")
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)


def timezone_now():
    from django.utils import timezone

    return timezone.now()
