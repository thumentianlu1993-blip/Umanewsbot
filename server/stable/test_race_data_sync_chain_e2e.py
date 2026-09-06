from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from stable import models
from stable.services import race_data_sync_enrollment, race_data_sync_lifecycle, race_events
from stable.services.race_data_sync_enrollment import parse_standing_policy
from stable.services.race_data_sync_pipeline import (
    _ROSTER_ALLOWED_FIELDS,
    resolve_race_data_provider_route,
)
from stable.services.race_data_sync_providers import (
    discover_the_racing_api_source_identities,
)
from stable.services.race_data_sync_results import (
    apply_data_sync_result_observation,
)
from stable.services.race_live_source_proof import RaceLiveProofHttpResponse
from stable.test_race_data_sync_policy_v2 import _policy_v2, _route
from stable.test_race_data_sync_providers import (
    NOW,
    REGISTRY_ACTIVATION,
    REGISTRY_MEMBERSHIP,
    REGISTRY_ROOT,
    ROOT,
    SHA,
)


def _sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
    RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED=True,
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
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(
        REGISTRY_MEMBERSHIP
    ),
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class RaceDataSyncChainE2ETests(TestCase):
    """Walk one event through the whole chain exactly as production would."""

    def setUp(self):
        self._dirs = TemporaryDirectory()
        self.addCleanup(self._dirs.cleanup)
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
        self.policy_digest = parse_standing_policy(self.policy).digest
        raw = json.dumps(self.policy, indent=2).encode()
        policy_path = Path(self._dirs.name) / "standing_policy.json"
        policy_path.write_bytes(raw)
        policy_override = override_settings(
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE=str(policy_path),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=(
                hashlib.sha256(raw).hexdigest()
            ),
        )
        policy_override.enable()
        self.addCleanup(policy_override.disable)
        self.registry = json.loads(
            (
                ROOT
                / "docs/changes/realtime-race-results/source_registry_the_racing_api_free.json"
            ).read_text(encoding="utf-8")
        )
        self.race_datetime = datetime(2026, 8, 29, 6, 0, tzinfo=dt_timezone.utc)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="chain-e2e",
            original_name="Chain Cup",
            chinese_name="链路杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=self.race_datetime,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 29),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )

    def _census_entry(self):
        census = race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=self.policy,
            cutoff=NOW,
            horizon_days=30,
        )
        self.assertEqual(census.total, 1)
        return census, census.entries[0]

    def test_full_chain_from_discovery_to_public_read(self):
        # 1. census: no identity yet -> blocked, waiting for identity
        census, entry = self._census_entry()
        self.assertEqual(entry.classification, "blocked")
        self.assertEqual(entry.reason_code, "source_identity_missing")

        # 2. identity discovery through the stubbed provider
        payload = {
            "racecards": [
                {
                    "race_id": "chain-1",
                    "off_dt": self.race_datetime.isoformat(),
                    "region": "jpn",
                    "course": "Tokyo",
                    "race_name": "Chain Cup",
                    "race_status": "scheduled",
                    "runners": [
                        {"horse_id": "horse-1", "horse": "Alpha", "number": "1"},
                        {"horse_id": "horse-2", "horse": "Beta", "number": "2"},
                    ],
                }
            ]
        }

        def transport(**kwargs):
            return RaceLiveProofHttpResponse(
                status_code=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
                elapsed_ms=5,
            )

        with (
            patch(
                "stable.services.race_data_sync_providers.read_the_racing_api_automation_registry",
                return_value=(self.registry, SHA),
            ),
            patch(
                "stable.services.race_data_sync_providers._read_secret",
                return_value=("user", "secret"),
            ),
        ):
            outcome = discover_the_racing_api_source_identities(
                now=NOW,
                transport=transport,
                clock=lambda: NOW,
                sleeper=lambda seconds: None,
            )
        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.created_source_count + outcome.adopted_source_count, 1)
        self.assertEqual(outcome.candidate_event_count, 1)

        # 3. census again -> eligible; proposal -> manifest -> apply
        census, entry = self._census_entry()
        self.assertEqual(entry.classification, "eligible")
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(self.event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        decisions = race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=manifest.as_dict(),
            expected_manifest_sha256=manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW,
            allow_runtime_open=True,
        )
        self.assertEqual([decision.action for decision in decisions], ["acquired"])
        control = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.assertEqual(control.mode, models.RaceEventLifecycleMode.ENFORCE)
        self.assertEqual(
            control.manifest_data["race_data_sync"]["standing_policy_digest"],
            self.policy_digest,
        )
        self.assertIsNotNone(control.next_refresh_at)

        # 4. lifecycle advance through the natural time path
        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(
            now=self.race_datetime + timedelta(minutes=1)
        )
        self.assertEqual(stats["transitioned"], 1, stats)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)

        stats = race_data_sync_lifecycle.advance_due_data_sync_lifecycle(
            now=self.race_datetime + timedelta(minutes=31)
        )
        self.assertEqual(stats["transitioned"], 1, stats)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)

        # 出马表写入在单元套件中单独覆盖；此处直接给出出马状态。
        source = models.RaceResultSourceIdentity.objects.get(event=self.event)
        source.proof_network_allowed = True
        source.evidence_url = "https://api.theracingapi.com/v1/results/chain-1"
        source.evidence_sha256 = "0" * 64
        source.save(
            update_fields=(
                "proof_network_allowed",
                "evidence_url",
                "evidence_sha256",
                "updated_at",
            )
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
                source_refs={source.source_key: runner_id},
            )

        # 5. official result observation -> projection -> publication
        result_payload = {
            "external_race_id": source.external_race_id,
            "off_time": self.race_datetime.isoformat(),
            "region": "japan_jra",
            "course": "Tokyo",
            "race_name": "Chain Cup",
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
        observation = models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=self.race_datetime + timedelta(minutes=40),
            source_updated_at=self.race_datetime + timedelta(minutes=40),
            parser_version="test-v1",
            raw_sha256=_sha(result_payload),
            normalized_sha256=_sha(result_payload),
            result_phase=models.RaceResultPhase.OFFICIAL,
            normalized_payload=result_payload,
            field_provenance={
                "provider": source.source_key,
                "region": source.region_code,
                "source_class": "licensed_api",
                "registry_digest": self.route.registry_digest,
                "contract_version": self.route.entry.contract_version,
                "contract_digest": self.route.entry.contract_digest,
                "automation_allowed": True,
            },
        )
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=self.race_datetime + timedelta(minutes=45),
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(decision.projected, decision)
        self.assertEqual(self.event.results.count(), 2)
        self.assertTrue(
            models.RaceEventRevisionPublication.objects.filter(
                revision_id=decision.revision_id
            ).exists()
        )

        # 6. public read visible through the same admission chain
        public = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=self.race_datetime + timedelta(minutes=50),
        )
        self.assertTrue(public.visible, public.reason)

        # 7. read-only audit agrees: enrolled, no stalled, no dual authority
        audit_output = StringIO()
        call_command(
            "audit_race_data_sync",
            cutoff=(self.race_datetime + timedelta(hours=1)).isoformat(),
            stdout=audit_output,
        )
        report = json.loads(audit_output.getvalue())
        self.assertFalse(report["would_write"])
        self.assertGreaterEqual(
            report["lifecycle"]["data_sync_evidence_controls"], 1
        )
        self.assertEqual(report["lifecycle"]["dual_authority_conflicts"], [])
        self.assertNotIn(
            self.event.pk,
            report["stalled"]["unpublished_terminal_revision_event_ids"],
        )
