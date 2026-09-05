from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
import json
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from stable import models
from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS


ROOT = Path(__file__).resolve().parents[2]


class RaceDataSyncAuditCommandTests(TestCase):
    @override_settings(
        RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE="",
        RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256="",
    )
    def test_audit_is_machine_readable_and_zero_write(self):
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command(
                "audit_race_data_sync",
                cutoff=datetime(
                    2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc
                ).isoformat(),
                stdout=output,
            )
        report = json.loads(output.getvalue())
        self.assertFalse(report["would_write"])
        self.assertEqual(report["standing_policy"]["status"], "not_configured")
        self.assertEqual(report["capacity"]["status"], "invalid")
        self.assertEqual(report["configuration_status"], "blocked")
        mutating = (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "REPLACE ",
            "ALTER ",
            "CREATE ",
            "DROP ",
        )
        self.assertFalse(
            [
                query["sql"]
                for query in queries.captured_queries
                if query["sql"].lstrip().upper().startswith(mutating)
            ]
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
        RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
        RACE_DATA_SYNC_ENABLED_FIELDS=("off_time",),
        RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
        RACE_LIVE_TRA_REGISTRY_SHA256="a" * 64,
    )
    def test_standing_policy_renderer_outputs_current_route_without_writes(self):
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command(
                "render_race_data_sync_standing_policy",
                policy_id="global-v1",
                approved_by="user-objective-2026-08-28",
                approved_at="2026-08-28T00:00:00+00:00",
                valid_from="2026-08-28T00:00:00+00:00",
                valid_until="2027-08-28T00:00:00+00:00",
                stdout=output,
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["policy_id"], "global-v1")
        self.assertEqual(payload["routes"][0]["provider"], "the_racing_api")
        self.assertEqual(payload["routes"][0]["region_code"], "japan_jra")
        self.assertFalse(queries.captured_queries)

    def test_closed_runtime_with_frozen_configuration_is_ready(self):
        with tempfile.TemporaryDirectory() as artifact_root, self.settings(
            RACE_DATA_SYNC_ENABLED=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=(
                "the_racing_api",
                "sporting_life",
                "zeturf",
                "horse_racing_nation",
            ),
            RACE_DATA_SYNC_ENABLED_REGIONS=(
                "france",
                "hong_kong",
                "ireland",
                "japan_jra",
                "japan_nar",
                "united_kingdom",
                "united_states",
            ),
            RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
            RACE_DATA_SYNC_ENABLED_DATA_KINDS=(
                "race_time",
                "racecard",
                "result",
            ),
            RACE_LIVE_TRA_REGISTRY_SHA256=(
                "3bac3b644c631ed165b8430343822b2c70c5a88c5036b63dcb557c83c0e0a6da"
            ),
            RACE_DATA_SYNC_REFERENCE_REGISTRY_SHA256=(
                "740a93774927765f9c848cc97e4b87b78ab36d473c4c3e2e644d56a6f856cff2"
            ),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE=str(
                ROOT / "runtime/policies/race_data_sync/standing_policy.json"
            ),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=(
                "4e000fd7510c076eb798345ff1d9dd5cded8043477dd2d55613cecebead31a07"
            ),
            RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2 * 1024 * 1024,
            RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1024 * 1024 * 1024,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=192,
            RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=512 * 1024 * 1024,
            RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=256 * 1024 * 1024,
            RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
            RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
            RACE_DATA_RAW_CLEANUP_MAX_BYTES=64 * 1024 * 1024,
            RACE_DATA_RAW_HOLD_ALERT_BYTES=256 * 1024 * 1024,
            RACE_DATA_RAW_ARTIFACT_ROOTS=(artifact_root,),
        ):
            output = StringIO()
            call_command(
                "audit_race_data_sync",
                cutoff="2026-08-28T08:00:00+00:00",
                stdout=output,
            )

        report = json.loads(output.getvalue())
        self.assertFalse(report["runtime"]["enabled"])
        self.assertEqual(report["capacity"]["status"], "valid")
        self.assertEqual(report["standing_policy"]["route_drift"], [])
        self.assertEqual(report["configuration_status"], "ready")


class RaceDataSyncAuditLifecycleSectionsTests(TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc)
        self.stalled = self._event("audit-stalled", local_day=27, status="running")
        self._enroll(self.stalled)
        source = models.RaceResultSourceIdentity.objects.get(event=self.stalled)
        observation = models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=self.cutoff,
            source_updated_at=self.cutoff,
            parser_version="test-v1",
            raw_sha256="0" * 64,
            normalized_sha256="0" * 64,
            result_phase=models.RaceResultPhase.OFFICIAL,
            normalized_payload={},
            field_provenance={},
        )
        models.RaceEventRevision.objects.create(
            event=self.stalled,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.OFFICIAL,
            content_sha256="0" * 64,
            primary_observation=observation,
        )
        models.RaceLiveAlertIncident.objects.create(
            alert_type=models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
            scope_type="data_sync_event",
            scope_key=str(self.stalled.pk),
            dedupe_key="audit-stalled-1",
            status=models.RaceLiveAlertIncidentStatus.OPEN,
        )
        self.due = self._event(
            "audit-due", local_day=28, status="scheduled", race_dt_hours=2
        )
        self._enroll(self.due)
        self.dual = self._event("audit-dual", local_day=28, status="scheduled")
        self._enroll(self.dual)
        models.RaceEventLifecycleControl.objects.create(
            event=self.dual,
            mode=models.RaceEventLifecycleMode.ENFORCE,
            schedule_generation=1,
            manifest_data={"race_data_sync": {"manifest_sha256": "e" * 64}},
        )
        registry = models.RaceEventLifecycleEnforceRegistry.objects.create(
            root_sha256="b" * 64,
            generation=1,
            membership_sha256="c" * 64,
            member_count=1,
            state="active",
            is_active=True,
            activation_id="d" * 64,
            approved_commit="1" * 40,
            selector_scope={},
            scope_sha256="2" * 64,
            census_cutoff=self.cutoff - timedelta(days=1),
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
            activated_at=self.cutoff,
        )
        models.RaceEventLifecycleEnforceMembership.objects.create(
            registry=registry,
            event=self.dual,
            state="active",
            entry_sha256="e" * 64,
            source_enrollment_sha256="f" * 64,
            schedule_generation=1,
            schedule_hash="0" * 64,
            country_region=self.dual.country_region,
            timezone_name=self.dual.timezone_name,
            frozen_snapshot={},
        )

    def _event(self, slug, *, local_day, status, race_dt_hours=None):
        from datetime import date

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
            race_datetime=(
                self.cutoff - timedelta(hours=race_dt_hours)
                if race_dt_hours is not None
                else self.cutoff + timedelta(days=1)
            ),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, local_day),
            status=status,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        return event

    def _enroll(self, event):
        source = models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id=f"jp-{event.pk}",
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=event,
            source_identity=source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="a" * 64,
            route_digest="b" * 64,
            event_snapshot_sha256="c" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="e" * 64,
        )
        models.RaceEventLiveTracking.objects.create(
            event=event,
            tracking_enabled=True,
        )

    @override_settings(
        RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE="",
        RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256="",
    )
    def test_audit_reports_lifecycle_and_stalled_sections(self):
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command(
                "audit_race_data_sync",
                cutoff=self.cutoff.isoformat(),
                stdout=output,
            )
        report = json.loads(output.getvalue())

        self.assertEqual(
            report["lifecycle"]["dual_authority_conflicts"], [self.dual.pk]
        )
        self.assertIn(self.due.pk, report["lifecycle"]["due_not_transitioned"])
        self.assertEqual(
            report["stalled"]["unpublished_terminal_revision_event_ids"],
            [self.stalled.pk],
        )
        self.assertEqual(report["stalled"]["open_incident_count"], 1)
        self.assertEqual(
            report["stalled"]["open_incident_event_ids"], [self.stalled.pk]
        )
        self.assertFalse(report["would_write"])
        mutating = ("INSERT ", "UPDATE ", "DELETE ", "REPLACE ", "ALTER ")
        self.assertFalse(
            [
                query["sql"]
                for query in queries.captured_queries
                if query["sql"].lstrip().upper().startswith(mutating)
            ]
        )
