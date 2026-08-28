from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable import models
from stable.services.race_data_sync_pipeline import (
    _ROSTER_ALLOWED_FIELDS,
    resolve_race_data_provider_route,
)
from stable.services.race_data_sync_providers import (
    discover_the_racing_api_source_identities,
    run_persisted_official_result_data_sync,
    run_reference_result_data_sync,
    run_result_fallback_chain,
    run_the_racing_api_data_sync,
)
from stable.services.race_live_source_proof import RaceLiveProofHttpResponse


NOW = datetime(2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc)
SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[2]
REFERENCE_SHA = "740a93774927765f9c848cc97e4b87b78ab36d473c4c3e2e644d56a6f856cff2"


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
)
class TheRacingApiDataSyncAdapterTests(TestCase):
    def setUp(self):
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
        models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
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
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(self.event.runners.count(), 2)
        self.assertEqual(self.event.results.count(), 2)
        self.assertEqual(self.event.results.get(finish_position=1).horse_name, "Alpha")
        self.assertEqual(
            set(outcome.observation_hashes),
            {"race_time", "racecard", "result"},
        )

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
        self.assertEqual(outcome.created_source_count, 1, outcome)
        source = models.RaceResultSourceIdentity.objects.get(event=event)
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
        self.assertEqual(self.event.results.count(), 2)

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
