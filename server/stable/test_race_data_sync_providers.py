from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from stable import models
from stable.services import race_data_sync_control, race_data_sync_providers
from stable.services.race_data_sync_pipeline import (
    _ROSTER_ALLOWED_FIELDS,
    build_race_data_provider_roster,
    reserve_race_data_transport_capacity,
    resolve_race_data_provider_route,
)
from stable.services.race_data_sync_providers import (
    _fair_discovery_bucket_order,
    discover_the_racing_api_source_identities,
    run_persisted_official_result_data_sync,
    run_reference_result_data_sync,
    run_result_fallback_chain,
    run_the_racing_api_data_sync,
)
from stable.services.race_live_source_proof import RaceLiveProofHttpResponse
from stable.services.race_event_lifecycle_enrollment import _schedule_hash


NOW = datetime(2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc)
SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[2]
REFERENCE_SHA = "740a93774927765f9c848cc97e4b87b78ab36d473c4c3e2e644d56a6f856cff2"
REGISTRY_ROOT = "b" * 64
REGISTRY_MEMBERSHIP = "c" * 64
REGISTRY_ACTIVATION = "d" * 64
REGISTRY_ENTRY = "e" * 64
LIFECYCLE_ENROLLMENT = "f" * 64


def _authorize_lifecycle(event: models.RaceEvent) -> None:
    event.visibility_status = models.RaceEventVisibility.PUBLISHED
    event.save(update_fields=("visibility_status", "updated_at"))
    models.RaceEventLifecycleControl.objects.create(
        event=event,
        mode=models.RaceEventLifecycleMode.ENFORCE,
        schedule_generation=1,
        enrollment_manifest_sha256=LIFECYCLE_ENROLLMENT,
        manifest_data={
            "enforce_registry": {
                "root_sha256": REGISTRY_ROOT,
                "membership_sha256": REGISTRY_MEMBERSHIP,
                "entry_sha256": REGISTRY_ENTRY,
                "activation_state": "active",
                "activation_id": REGISTRY_ACTIVATION,
            }
        },
    )
    registry = models.RaceEventLifecycleEnforceRegistry.objects.create(
        root_sha256=REGISTRY_ROOT,
        generation=1,
        membership_sha256=REGISTRY_MEMBERSHIP,
        member_count=1,
        state="active",
        is_active=True,
        activation_id=REGISTRY_ACTIVATION,
        approved_commit="1" * 40,
        selector_scope={},
        scope_sha256="2" * 64,
        census_cutoff=NOW - timedelta(days=1),
        apply_expires_at=NOW + timedelta(days=1),
        runtime_valid_until=NOW + timedelta(days=35),
        activated_at=NOW,
    )
    models.RaceEventLifecycleEnforceMembership.objects.create(
        registry=registry,
        event=event,
        state="active",
        entry_sha256=REGISTRY_ENTRY,
        source_enrollment_sha256=LIFECYCLE_ENROLLMENT,
        schedule_generation=1,
        schedule_hash=_schedule_hash(event),
        country_region=event.country_region,
        timezone_name=event.timezone_name,
        frozen_snapshot={},
    )


class ProviderIdentityDiscoveryFairnessTests(TestCase):
    def test_hourly_budget_rotates_across_all_region_day_buckets(self):
        buckets = {
            ("france", "today"): [],
            ("hong_kong", "today"): [],
            ("japan", "today"): [],
            ("united_kingdom", "tomorrow"): [],
        }

        first = _fair_discovery_bucket_order(buckets=buckets, now=NOW)
        second = _fair_discovery_bucket_order(
            buckets=buckets,
            now=NOW + timedelta(hours=1),
        )

        self.assertEqual({key for key, _items in first}, set(buckets))
        self.assertEqual(second, (*first[1:], first[0]))


@override_settings(
    RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2 * 1024 * 1024,
    RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
    RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=16 * 1024 * 1024,
    RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=3,
    RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=1024 * 1024 * 1024,
    RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=512 * 1024 * 1024,
    RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
    RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
    RACE_DATA_RAW_CLEANUP_MAX_BYTES=64 * 1024 * 1024,
    RACE_DATA_RAW_HOLD_ALERT_BYTES=256 * 1024 * 1024,
    RACE_DATA_RAW_ARTIFACT_ROOTS=(str(ROOT / "runtime"),),
)
class RaceDataTransportCapacityTests(TestCase):
    def test_daily_provider_region_reservation_is_atomic_and_bounded(self):
        admitted = reserve_race_data_transport_capacity(
            provider="the_racing_api",
            region_code="japan_jra",
            now=NOW,
            proposed_requests=2,
            max_response_bytes_per_request=1024,
        )
        blocked = reserve_race_data_transport_capacity(
            provider="the_racing_api",
            region_code="japan_jra",
            now=NOW,
            proposed_requests=2,
            max_response_bytes_per_request=1024,
        )

        self.assertTrue(admitted.allowed)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason_code, "artifact_daily_requests_exceeded")
        ledger = models.RaceDataTransportCapacityLedger.objects.get()
        self.assertEqual(ledger.request_count, 2)
        self.assertEqual(ledger.budgeted_response_bytes, 2048)


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
    RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
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
class TheRacingApiDataSyncAdapterTests(TestCase):
    def setUp(self):
        self.artifact_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.artifact_dir.cleanup)
        artifact_override = override_settings(
            RACE_DATA_RAW_ARTIFACT_ROOTS=(self.artifact_dir.name,)
        )
        artifact_override.enable()
        self.addCleanup(artifact_override.disable)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="tra-data-sync",
            original_name="API Cup",
            chinese_name="API杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW - timedelta(minutes=10),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            local_start_time=datetime(2026, 8, 28, 16, 50).time(),
            status=models.RaceEventStatus.RUNNING,
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
            owner_manifest_sha256="d" * 64,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
        )
        _authorize_lifecycle(self.event)
        self.decoy_source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="hong_kong",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="decoy-api-99",
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="jp-api-11",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
        )
        self.route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            data_kinds=("race_time", "racecard", "result"),
        )
        self.assertIsNotNone(self.route)
        self.source.valid_until = NOW + timedelta(days=30)
        self.source.registry_digest = self.route.registry_digest
        self.source.save(
            update_fields=("valid_until", "registry_digest", "updated_at")
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=self.source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="a" * 64,
            route_digest=self.route.route_digest,
            event_snapshot_sha256="b" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="e" * 64,
            effective_at=NOW - timedelta(days=1),
        )
        self.assertLess(self.decoy_source.pk, self.source.pk)
        self.registry = json.loads(
            (
                ROOT
                / "docs/changes/realtime-race-results/source_registry_the_racing_api_free.json"
            ).read_text(encoding="utf-8")
        )

    def _transport(self, **kwargs):
        if kwargs["endpoint_name"].startswith("racecards_sync_"):
            payload = {
                "racecards": [
                    {
                        "race_id": "jp-api-11",
                        "off_dt": (NOW - timedelta(minutes=10)).isoformat(),
                        "region": "jpn",
                        "course": "Tokyo",
                        "race_name": "API Cup",
                        "race_status": "running",
                        "runners": [
                            {
                                "horse_id": "horse-1",
                                "horse": "Alpha",
                                "number": "1",
                                "draw": "2",
                                "jockey": "Jockey A",
                                "jockey_id": "jockey-a",
                            },
                            {
                                "horse_id": "horse-2",
                                "horse": "Beta",
                                "number": "2",
                                "draw": "3",
                                "jockey": "Jockey B",
                                "jockey_id": "jockey-b",
                            },
                        ],
                    }
                ],
                "total": 1,
                "limit": 500,
                "skip": 0,
            }
        else:
            payload = {
                "results": [
                    {
                        "race_id": "jp-api-11",
                        "off_dt": (NOW - timedelta(minutes=10)).isoformat(),
                        "region": "jpn",
                        "course": "Tokyo",
                        "race_name": "API Cup",
                        "race_status": "complete",
                        "runners": [
                            {
                                "horse_id": "horse-1",
                                "horse": "Alpha",
                                "number": "1",
                                "position": "1",
                            },
                            {
                                "horse_id": "horse-2",
                                "horse": "Beta",
                                "number": "2",
                                "position": "2",
                            },
                        ],
                    }
                ],
                "total": 1,
                "limit": 50,
                "skip": 0,
            }
        return RaceLiveProofHttpResponse(
            status_code=200,
            content_type="application/json",
            body=json.dumps(payload).encode(),
            elapsed_ms=5,
        )

    def test_one_provider_run_applies_time_racecard_and_result(self):
        tick = {"value": NOW}

        def clock():
            tick["value"] += timedelta(seconds=2)
            return tick["value"]

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
            outcome = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("race_time", "racecard", "result"),
                route=self.route,
                now=NOW,
                task_id="provider-test",
                run_id="provider-run",
                transport=self._transport,
                clock=clock,
                sleeper=lambda seconds: None,
            )

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(set(outcome.applied_kinds), {"race_time", "racecard", "result"})
        self.event.refresh_from_db()
        self.assertEqual(
            self.event.status,
            models.RaceEventStatus.FINISHED,
            list(
                self.event.revisions.values_list(
                    "phase", "decision_reason", "published_at"
                )
            ),
        )
        self.assertEqual(self.event.runners.count(), 2)
        self.assertEqual(
            self.event.results.count(),
            2,
            list(
                self.event.revisions.values_list(
                    "phase", "decision_reason", "published_at"
                )
            ),
        )
        self.assertEqual(self.event.results.get(finish_position=1).horse_name, "Alpha")
        self.assertEqual(
            self.event.revisions.filter(
                kind=models.RaceEventRevisionKind.RACECARD
            ).count(),
            1,
        )
        self.assertEqual(
            set(outcome.observation_hashes),
            {"race_time", "racecard", "result"},
        )

    def test_today_result_without_terminal_marker_stays_provisional(self):
        tick = {"value": NOW}

        def clock():
            tick["value"] += timedelta(seconds=2)
            return tick["value"]

        def provisional_transport(**kwargs):
            response = self._transport(**kwargs)
            payload = json.loads(response.body)
            if "results" in payload:
                payload["results"][0]["race_status"] = "running"
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
            outcome = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("racecard", "result"),
                route=self.route,
                now=NOW,
                task_id="provider-provisional",
                run_id="run-provisional",
                transport=provisional_transport,
                clock=clock,
                sleeper=lambda seconds: None,
            )

        self.assertTrue(outcome.success, outcome.reason_code)
        result_observation = models.RaceResultObservation.objects.get(
            result_phase=models.RaceResultPhase.PROVISIONAL
        )
        self.assertIsNotNone(result_observation)
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_registered_provider_correction_marker_produces_corrected_phase(self):
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

        def corrected_transport(**kwargs):
            response = self._transport(**kwargs)
            payload = json.loads(response.body)
            payload["results"][0]["race_status"] = "corrected"
            return RaceLiveProofHttpResponse(
                status_code=response.status_code,
                content_type=response.content_type,
                body=json.dumps(payload).encode(),
                elapsed_ms=response.elapsed_ms,
            )

        tick = {"value": NOW}

        def clock():
            tick["value"] += timedelta(seconds=2)
            return tick["value"]

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
            outcome = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("result",),
                route=self.route,
                now=NOW,
                task_id="provider-corrected-result",
                run_id="run-corrected-result",
                transport=corrected_transport,
                clock=clock,
                sleeper=lambda seconds: None,
            )

        self.assertTrue(outcome.success, outcome.reason_code)
        observation = models.RaceResultObservation.objects.get()
        self.assertEqual(
            observation.result_phase, models.RaceResultPhase.CORRECTED
        )
        self.assertTrue(observation.field_provenance["correction_marker"])
        revision = models.RaceEventRevision.objects.get()
        self.assertEqual(revision.phase, models.RaceResultPhase.CORRECTED)
        self.assertIsNotNone(revision.published_at)

    def test_out_of_window_racecard_is_successful_not_found_and_stays_due(self):
        self.event.local_date = date(2026, 9, 15)
        self.event.save(update_fields=("local_date",))
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
            outcome = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("race_time", "racecard"),
                route=self.route,
                now=NOW,
                task_id="provider-test",
                run_id="provider-run",
                transport=self._transport,
                clock=lambda: NOW,
                sleeper=lambda seconds: None,
            )
        self.assertTrue(outcome.success)
        self.assertEqual(set(outcome.not_found_kinds), {"race_time", "racecard"})
        self.assertFalse(models.RaceResultObservation.objects.exists())

    def test_two_events_reuse_one_region_day_racecard_snapshot(self):
        second_event = models.RaceEvent.objects.create(
            year=2026,
            slug="tra-data-sync-second",
            original_name="API Cup Two",
            chinese_name="API杯二",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G2",
            normalized_grade=models.RaceGrade.G2,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW + timedelta(minutes=20),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.SCHEDULED,
        )
        models.RaceEventProjectionControl.objects.create(
            event=second_event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
            owner_manifest_sha256="d" * 64,
        )
        models.RaceEventLiveTracking.objects.create(event=second_event)
        second_source = models.RaceResultSourceIdentity.objects.create(
            event=second_event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="jp-api-22",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=second_event,
            source_identity=second_source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="a" * 64,
            route_digest=self.route.route_digest,
            event_snapshot_sha256="b" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="e" * 64,
            effective_at=NOW - timedelta(days=1),
        )
        calls = []

        def transport(**kwargs):
            calls.append(kwargs["url"])
            payload = {
                "racecards": [
                    {
                        "race_id": race_id,
                        "off_dt": off_time.isoformat(),
                        "region": "jpn",
                        "course": "Tokyo",
                        "race_name": race_name,
                        "race_status": "scheduled",
                        "runners": [
                            {
                                "horse_id": f"{race_id}-horse-1",
                                "horse": "Alpha",
                                "number": "1",
                            }
                        ],
                    }
                    for race_id, off_time, race_name in (
                        ("jp-api-11", self.event.race_datetime, "API Cup"),
                        (
                            second_source.external_race_id,
                            second_event.race_datetime,
                            "API Cup Two",
                        ),
                    )
                ]
            }
            return RaceLiveProofHttpResponse(
                status_code=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
                elapsed_ms=5,
            )

        tick = {"value": NOW}

        def clock():
            tick["value"] += timedelta(seconds=2)
            return tick["value"]

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
            outcomes = [
                run_the_racing_api_data_sync(
                    event_id=event_id,
                    data_kinds=("racecard",),
                    route=self.route,
                    now=NOW,
                    task_id=f"provider-{event_id}",
                    run_id=f"run-{event_id}",
                    transport=transport,
                    clock=clock,
                    sleeper=lambda seconds: None,
                )
                for event_id in (self.event.pk, second_event.pk)
            ]

        self.assertTrue(all(outcome.success for outcome in outcomes), outcomes)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.event.runners.count(), 1)
        self.assertEqual(second_event.runners.count(), 1)

    def test_shared_snapshot_waiter_polls_until_complete_manifest(self):
        self.assertGreater(
            race_data_sync_providers._SNAPSHOT_WAITER_MAX_POLLS
            * (race_data_sync_providers._SNAPSHOT_WAITER_POLL_SECONDS - 0.25),
            race_data_sync_providers._SNAPSHOT_LEASE_TTL_SECONDS,
        )
        lease = MagicMock(manifest_data={"complete": True})
        fetcher = MagicMock()
        sleep_intervals = []
        queryset = MagicMock()
        queryset.first.return_value = lease

        with (
            patch.object(
                race_data_sync_providers,
                "claim_snapshot_lease",
                side_effect=(
                    race_data_sync_control.ControlDecision(
                        "busy", "lease_active", generation=1
                    ),
                    race_data_sync_control.ControlDecision(
                        "complete", generation=1
                    ),
                ),
            ) as claim,
            patch.object(
                models.RaceDataSnapshotLease.objects,
                "filter",
                return_value=queryset,
            ),
            patch.object(
                race_data_sync_providers,
                "_read_snapshot_artifact",
                return_value=({"racecards": []}, "a" * 64),
            ),
        ):
            payload, artifact_sha256 = (
                race_data_sync_providers._get_or_fetch_shared_snapshot(
                    provider="the_racing_api",
                    region="japan_jra",
                    scope_key="2026-08-28:jpn",
                    data_kind=models.RaceDataSyncDataKind.RACECARD,
                    registry_digest="b" * 64,
                    run_id="waiter-run",
                    now=NOW,
                    proposed_requests=1,
                    clock=lambda: NOW + timedelta(seconds=2),
                    sleeper=sleep_intervals.append,
                    fetcher=fetcher,
                )
            )

        self.assertEqual(payload, {"racecards": []})
        self.assertEqual(artifact_sha256, "a" * 64)
        self.assertEqual(claim.call_count, 2)
        self.assertEqual(len(sleep_intervals), 1)
        self.assertNotEqual(sleep_intervals[0], 2.0)
        fetcher.assert_not_called()

    def test_racecard_without_status_preserves_withdrawal_and_nr_is_explicit(self):
        tick = {"value": NOW}

        def clock():
            tick["value"] += timedelta(seconds=2)
            return tick["value"]

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
            first = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("racecard",),
                route=self.route,
                now=NOW,
                task_id="provider-first",
                run_id="run-first",
                transport=self._transport,
                clock=clock,
                sleeper=lambda seconds: None,
            )
            self.assertTrue(first.success, first.reason_code)
            runner = self.event.runners.get(external_runner_id="horse-1")
            runner.running_status = models.RaceRunnerStatus.WITHDRAWN
            runner.save(update_fields=("running_status", "updated_at"))

            def changed_transport(**kwargs):
                response = self._transport(**kwargs)
                payload = json.loads(response.body)
                payload["racecards"][0]["runners"][0]["jockey"] = "Changed"
                return RaceLiveProofHttpResponse(
                    status_code=200,
                    content_type="application/json",
                    body=json.dumps(payload).encode(),
                    elapsed_ms=5,
                )

            second = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("racecard",),
                route=self.route,
                now=NOW + timedelta(minutes=3),
                task_id="provider-second",
                run_id="run-second",
                transport=changed_transport,
                clock=lambda: NOW + timedelta(minutes=3),
                sleeper=lambda seconds: None,
            )

            def non_runner_transport(**kwargs):
                response = changed_transport(**kwargs)
                payload = json.loads(response.body)
                payload["racecards"][0]["runners"][1]["number"] = "NR"
                return RaceLiveProofHttpResponse(
                    status_code=200,
                    content_type="application/json",
                    body=json.dumps(payload).encode(),
                    elapsed_ms=5,
                )

            third = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("racecard",),
                route=self.route,
                now=NOW + timedelta(minutes=6),
                task_id="provider-third",
                run_id="run-third",
                transport=non_runner_transport,
                clock=lambda: NOW + timedelta(minutes=6),
                sleeper=lambda seconds: None,
            )

        self.assertTrue(second.success, second.reason_code)
        self.assertTrue(third.success, third.reason_code)
        runner.refresh_from_db()
        self.assertEqual(runner.running_status, models.RaceRunnerStatus.WITHDRAWN)
        self.assertEqual(
            self.event.runners.get(external_runner_id="horse-2").running_status,
            models.RaceRunnerStatus.NON_RUNNER,
        )

    def test_previous_day_result_uses_exact_race_id_route(self):
        self.event.local_date = date(2026, 8, 27)
        self.event.race_datetime = NOW - timedelta(days=1, minutes=10)
        self.event.save(update_fields=("local_date", "race_datetime", "updated_at"))
        membership = models.RaceEventLifecycleEnforceMembership.objects.get(
            event=self.event
        )
        membership.schedule_hash = _schedule_hash(self.event)
        membership.save(update_fields=("schedule_hash", "updated_at"))
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
        calls = []

        def transport(**kwargs):
            calls.append((kwargs["endpoint_name"], kwargs["url"]))
            payload = {
                "race_id": self.source.external_race_id,
                "off_dt": self.event.race_datetime.isoformat(),
                "region": "jpn",
                "course": "Tokyo",
                "race_name": "API Cup",
                "runners": [
                    {
                        "horse_id": "horse-1",
                        "horse": "Alpha",
                        "number": "1",
                        "position": "1",
                    },
                    {
                        "horse_id": "horse-2",
                        "horse": "Beta",
                        "number": "2",
                        "position": "2",
                    },
                ],
            }
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
            outcome = run_the_racing_api_data_sync(
                event_id=self.event.pk,
                data_kinds=("result",),
                route=self.route,
                now=NOW,
                task_id="provider-exact-result",
                run_id="run-exact-result",
                transport=transport,
                clock=lambda: NOW,
                sleeper=lambda seconds: None,
            )

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(calls[0][0], "result_by_id")
        self.assertIn("/v1/results/jp-api-11", calls[0][1])
        self.assertEqual(self.event.results.count(), 2)

    @override_settings(RACE_DATA_SYNC_ALLOW_NETWORK=True)
    def test_future_event_identity_is_discovered_without_per_race_review(self):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="tra-identity-discovery",
            original_name="Discovery Cup",
            chinese_name="发现杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        legacy_event = models.RaceEvent.objects.create(
            year=2026,
            slug="tra-identity-discovery-legacy-namespace",
            original_name="Legacy Namespace Cup",
            chinese_name="旧命名空间杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.DRAFT,
        )
        models.RaceResultSourceIdentity.objects.create(
            event=legacy_event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-legacy-v0",
            external_race_id="jp-discovery-1",
        )
        stale_source = models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="jp-discovery-1",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/terms",
            evidence_sha256="0" * 64,
            valid_until=NOW,
            registry_digest="0" * 64,
        )

        def transport(**kwargs):
            payload = {
                "racecards": [
                    {
                        "race_id": "jp-discovery-1",
                        "off_dt": datetime(
                            2026, 8, 28, 9, 30, tzinfo=dt_timezone.utc
                        ).isoformat(),
                        "region": "jpn",
                        "course": "Tokyo",
                        "race_name": "Discovery Cup",
                        "race_status": "scheduled",
                        "runners": [
                            {
                                "horse_id": "discovery-horse-1",
                                "horse": "Alpha",
                                "number": "1",
                            }
                        ],
                    }
                ]
            }
            return RaceLiveProofHttpResponse(
                status_code=200,
                content_type="application/json",
                body=json.dumps(payload).encode(),
                elapsed_ms=5,
            )

        tick = {"value": NOW}

        def clock():
            tick["value"] += timedelta(seconds=2)
            return tick["value"]

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
                clock=clock,
                sleeper=lambda seconds: None,
            )

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.created_source_count, 0, outcome)
        self.assertEqual(outcome.adopted_source_count, 1, outcome)
        source = models.RaceResultSourceIdentity.objects.get(event=event)
        self.assertEqual(source.pk, stale_source.pk)
        self.assertEqual(source.external_race_id, "jp-discovery-1")
        self.assertEqual(source.region_code, "japan_jra")
        self.assertEqual(
            source.identity_namespace, "the_racing_api-race-v1"
        )
        self.assertTrue(source.automation_allowed)
        self.assertTrue(source.proof_network_allowed)


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("sporting_life",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("united_kingdom",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",),
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_DATA_SYNC_REFERENCE_REGISTRY_SHA256=REFERENCE_SHA,
    RACE_RESULT_REVIEW_ROUTE_REGISTRY=str(
        ROOT / "runtime/policies/race_result_review/source_routes_v1.json"
    ),
    RACE_EVENT_LIFECYCLE_ENABLED=True,
    RACE_EVENT_LIFECYCLE_MODE="enforce",
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=REGISTRY_ROOT,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(
        REGISTRY_MEMBERSHIP
    ),
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class ReferenceResultDataSyncAdapterTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="reference-data-sync",
            original_name="Reference Cup",
            chinese_name="参考杯",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW - timedelta(minutes=20),
            timezone_name="Europe/London",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
        )
        models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
        )
        _authorize_lifecycle(self.event)
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="sporting_life",
            region_code="united_kingdom",
            identity_namespace="sporting_life-race-v1",
            external_race_id="sl:859381",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
        )
        self.route = resolve_race_data_provider_route(
            provider="sporting_life",
            region="united_kingdom",
            identity_namespace="sporting_life-race-v1",
            data_kinds=("result",),
        )
        self.assertIsNotNone(self.route)
        self.source.proof_network_allowed = True
        self.source.evidence_url = "https://www.sportinglife.com/racing/results/"
        self.source.evidence_sha256 = REFERENCE_SHA
        self.source.valid_until = NOW + timedelta(days=30)
        self.source.registry_digest = self.route.registry_digest
        self.source.save(
            update_fields=(
                "proof_network_allowed",
                "evidence_url",
                "evidence_sha256",
                "valid_until",
                "registry_digest",
            )
        )
        for runner_id, name, number in (
            ("sl-horse-1", "Alpha", "1"),
            ("sl-horse-2", "Beta", "2"),
        ):
            models.RaceEventRunner.objects.create(
                event=self.event,
                external_runner_id=runner_id,
                horse_name=name,
                horse_number=number,
                source_refs={self.source.source_key: runner_id},
            )

    def _receipt(self, *, complete=True):
        semantic = {
            "schema_version": 1,
            "source_key": "reference_sporting_life",
            "country_region": "united_kingdom",
            "provider_event_key": "sl:859381",
            "race": {
                "source_race_name": "Reference Cup",
                "source_racecourse": "Ascot",
                "local_date": "2026-08-28",
                "source_start_time": "09:40",
            },
            "runners": [
                {
                    "source_runner_key": "sl-horse-1",
                    "horse_number": "1",
                    "draw": "2",
                    "horse_name": "Alpha",
                    "jockey_name": "Jockey A",
                    "trainer_name": "Trainer A",
                    "carried_weight": "9-2",
                    "odds_value": "2/1",
                    "running_status": "declared",
                    "source_reported_finish_position": "1",
                    "margin": "",
                },
                {
                    "source_runner_key": "sl-horse-2",
                    "horse_number": "2",
                    "draw": "3",
                    "horse_name": "Beta",
                    "jockey_name": "Jockey B",
                    "trainer_name": "Trainer B",
                    "carried_weight": "9-0",
                    "odds_value": "3/1",
                    "running_status": "declared",
                    "source_reported_finish_position": "1",
                    "margin": "dead heat",
                },
            ],
            "completeness": {
                "race_identity": "complete",
                "runners": "complete",
                "results": "complete" if complete else "partial",
                "gap_codes": [] if complete else ["results_partial"],
            },
        }
        run = models.RaceReferenceCollectionRun.objects.create(
            source_key="reference_sporting_life",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            parser_name="sporting_life",
            parser_version="reference-v1",
            scope_manifest_sha256="1" * 64,
            target_count=1,
            status=models.RaceReferenceCollectionStatus.FINISHED,
            started_at=NOW,
            finished_at=NOW,
            matched_count=1,
            artifact_sha256=("2" if complete else "3") * 64,
        )
        payload = models.RaceReferencePayload.objects.create(
            source_key="reference_sporting_life",
            provider_event_key="sl:859381",
            observation_key="reference_sporting_life:sl:859381",
            payload_sha256=("4" if complete else "5") * 64,
            structured_payload=semantic,
        )
        return models.RaceReferenceReceipt.objects.create(
            run=run,
            payload=payload,
            source_url="https://www.sportinglife.com/racing/results/2026-08-28/ascot/859381/reference-cup",
            final_url="https://www.sportinglife.com/racing/results/2026-08-28/ascot/859381/reference-cup",
            source_observed_at=NOW,
            fetched_at=NOW,
            parser_name="sporting_life",
            parser_version="reference-v1",
            legacy_payload_sha256="6" * 64,
            raw_sha256=("7" if complete else "8") * 64,
            source_cache_ref="test-cache",
            provenance_sha256="9" * 64,
            event=self.event,
            match_status=models.RaceReferenceMatchStatus.MATCHED,
            match_confidence=100,
            match_evidence={"event_id": self.event.pk},
            event_snapshot={"event_id": self.event.pk},
            event_snapshot_sha256="a" * 64,
            classification_version="test-v1",
            is_partial=not complete,
            gap_codes=[] if complete else ["results_partial"],
        )

    def test_complete_reference_receipt_projects_dead_heat_without_review(self):
        receipt = self._receipt()
        outcome = run_reference_result_data_sync(
            event_id=self.event.pk,
            data_kinds=("result",),
            route=self.route,
            now=NOW,
            task_id="reference-test",
            run_id="reference-run",
            collect_if_missing=False,
        )
        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.applied_kinds, ("result",))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(
            list(
                self.event.results.order_by("finish_position").values_list(
                    "reported_finish_position", flat=True
                )
            ),
            [1, 1],
        )
        observation = models.RaceResultObservation.objects.get()
        self.assertEqual(
            observation.field_provenance["reference_receipt_id"], receipt.pk
        )

    def test_reference_result_binds_exact_canonical_roster_bijection(self):
        for runner in self.event.runners.all():
            runner.source_refs = {
                "the_racing_api": f"tra-{runner.horse_number}"
            }
            runner.save(update_fields=("source_refs", "updated_at"))
        self._receipt()

        outcome = run_reference_result_data_sync(
            event_id=self.event.pk,
            data_kinds=("result",),
            route=self.route,
            now=NOW,
            task_id="reference-test",
            run_id="reference-bijection-run",
            collect_if_missing=False,
        )

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.applied_kinds, ("result",))
        self.assertEqual(
            set(
                self.event.runners.values_list(
                    "source_refs__sporting_life", flat=True
                )
            ),
            {"sl-horse-1", "sl-horse-2"},
        )

    def test_partial_reference_receipt_is_not_projected(self):
        self._receipt(complete=False)
        outcome = run_reference_result_data_sync(
            event_id=self.event.pk,
            data_kinds=("result",),
            route=self.route,
            now=NOW,
            task_id="reference-test",
            run_id="reference-run",
            collect_if_missing=False,
        )
        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.not_found_kinds, ("result",))
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_fallback_chain_consumes_admitted_reference_after_api_miss(self):
        self._receipt()
        from stable.services.race_data_sync_control import source_admission_reason

        self.assertEqual(
            source_admission_reason(
                source=self.source,
                route_digest=self.route.route_digest,
                data_kinds=("result",),
                now=NOW,
            ),
            "",
        )
        outcome = run_result_fallback_chain(
            event_id=self.event.pk,
            excluded_providers=("the_racing_api",),
            now=NOW,
            task_id="fallback-test",
            run_id="fallback-run",
        )
        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.applied_kinds, ("result",))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(self.event.results.count(), 2)
        revision = models.RaceEventRevision.objects.get()
        self.assertIsNotNone(revision.published_at)

    @override_settings(
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
        RACE_DATA_SYNC_ENABLED_REGIONS=("united_kingdom",),
    )
    def test_fallback_chain_never_executes_provider_outside_allowlist(self):
        self._receipt()
        with patch(
            "stable.services.race_data_sync_providers.run_reference_result_data_sync"
        ) as execute_reference:
            outcome = run_result_fallback_chain(
                event_id=self.event.pk,
                excluded_providers=("the_racing_api",),
                now=NOW,
                task_id="fallback-test",
                run_id="fallback-run",
            )

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.not_found_kinds, ("result",))
        execute_reference.assert_not_called()

    def test_fallback_creates_identity_from_existing_matched_receipt(self):
        self._receipt()
        self.source.delete()
        outcome = run_result_fallback_chain(
            event_id=self.event.pk,
            excluded_providers=("the_racing_api",),
            now=NOW,
            task_id="fallback-test",
            run_id="fallback-run",
        )
        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.applied_kinds, ("result",))
        source = models.RaceResultSourceIdentity.objects.get(event=self.event)
        self.assertEqual(source.source_key, "sporting_life")
        self.assertEqual(source.external_race_id, "sl:859381")
        self.assertEqual(source.identity_namespace, "sporting_life")
        self.assertTrue(source.automation_allowed)


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("hkjc",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",),
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_EVENT_LIFECYCLE_ENABLED=True,
    RACE_EVENT_LIFECYCLE_MODE="enforce",
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=REGISTRY_ROOT,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(
        REGISTRY_MEMBERSHIP
    ),
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class PersistedOfficialResultBridgeTests(TestCase):
    def test_existing_hkjc_import_projects_before_third_party_fallback(self):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="hkjc-official-bridge",
            original_name="Official Cup",
            chinese_name="官方杯",
            country_region=models.RacingRegion.HONG_KONG,
            racecourse="Sha Tin",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW - timedelta(minutes=20),
            timezone_name="Asia/Hong_Kong",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
        )
        models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
        )
        models.RaceEventLiveTracking.objects.create(event=event)
        _authorize_lifecycle(event)
        source = models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="hkjc",
            region_code="hong_kong",
            identity_namespace="hkjc-race-v1",
            external_race_id="20260828-ST-01",
            canonical_url="https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=NOW + timedelta(days=30),
        )
        source.registry_digest = build_race_data_provider_roster(
            configuration_only=True
        ).registry_digest
        source.save(update_fields=("registry_digest", "updated_at"))
        external = models.ExternalRace.objects.create(
            source=models.ExternalDataSource.HKJC,
            racing_region=models.RacingRegion.HONG_KONG,
            race_id=source.external_race_id,
            race_name="Official Cup",
            race_date=date(2026, 8, 28),
            course="Sha Tin",
            scheduled_start_at=event.race_datetime,
            raw_payload={"source_url": source.canonical_url},
            fetched_at=NOW,
            last_seen_at=NOW,
        )
        for position, name in ((1, "Official Alpha"), (2, "Official Beta")):
            models.ExternalRaceResult.objects.create(
                source=models.ExternalDataSource.HKJC,
                racing_region=models.RacingRegion.HONG_KONG,
                race=external,
                external_race_id=external.race_id,
                result_key=f"horse-{position}",
                horse_id=f"horse-{position}",
                horse_name=name,
                horse_number=str(position),
                finish_position=str(position),
                raw_payload={"finish_position": position},
                fetched_at=NOW,
                last_seen_at=NOW,
            )
            models.RaceEventRunner.objects.create(
                event=event,
                external_runner_id=f"horse-{position}",
                horse_name=name,
                horse_number=str(position),
                source_refs={source.source_key: f"horse-{position}"},
            )

        outcome = run_persisted_official_result_data_sync(
            event_id=event.pk,
            source_identity_id=source.pk,
            now=NOW,
            task_id="official-bridge-test",
            run_id="official-bridge-run",
        )

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.applied_kinds, ("result",))
        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(
            event.results.get(finish_position=1).horse_name,
            "Official Alpha",
        )
        self.assertEqual(
            models.RaceEventRevision.objects.get().source_authority,
            "official_operator",
        )
