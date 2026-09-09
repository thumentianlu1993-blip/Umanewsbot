from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable import models
from stable.services.race_data_sync_pipeline import resolve_race_data_provider_route
from stable.services.race_data_sync_providers import (
    discover_the_racing_api_source_identities,
)
from stable.services.race_live_source_proof import RaceLiveProofHttpResponse
from stable.test_race_data_sync_providers import (
    _ROSTER_ALLOWED_FIELDS,
    NOW,
    REGISTRY_ACTIVATION,
    REGISTRY_MEMBERSHIP,
    REGISTRY_ROOT,
    ROOT,
    SHA,
)


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
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
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(REGISTRY_MEMBERSHIP),
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class TheRacingApiIdentityDiscoveryConservationTests(TestCase):
    def setUp(self):
        capacity = patch("stable.services.race_data_sync_pipeline.inspect_race_data_artifact_capacity",
                         return_value=(0, 1024 * 1024 * 1024))
        capacity.start()
        self.addCleanup(capacity.stop)
        self.registry = json.loads(
            (
                ROOT
                / "docs/changes/realtime-race-results/source_registry_the_racing_api_free.json"
            ).read_text(encoding="utf-8")
        )
        self.route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            data_kinds=("race_time", "racecard", "result"),
        )
        self.assertIsNotNone(self.route)

    def _event(self, *, slug: str, local_date: date, locked: bool = False, **kwargs):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=kwargs.get("country_region", models.RacingRegion.JAPAN),
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name=kwargs.get("timezone_name", "Asia/Tokyo"),
            local_date=local_date,
            status=kwargs.get("status", models.RaceEventStatus.SCHEDULED),
            visibility_status=kwargs.get(
                "visibility_status", models.RaceEventVisibility.PUBLISHED
            ),
        )
        if locked:
            event.manual_lock_flags = {"race_datetime": True}
            event.save(update_fields=("manual_lock_flags",))
        return event

    def _valid_identity(self, event):
        return models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id=f"jp-{event.pk}",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url="https://api.theracingapi.com/terms",
            evidence_sha256="0" * 64,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.route.registry_digest,
        )

    def _discover(self, transport=None):
        calls = []

        def _transport(**kwargs):
            calls.append(kwargs)
            return RaceLiveProofHttpResponse(
                status_code=200,
                content_type="application/json",
                body=json.dumps({"racecards": []}).encode(),
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
                transport=transport or _transport,
                clock=lambda: NOW,
                sleeper=lambda seconds: None,
            )
        return outcome, calls

    def _assert_conserved(self, outcome):
        accounted = (
            outcome.already_valid_count
            + outcome.awaiting_source_window_count
            + outcome.deferred_event_count
            + outcome.created_source_count
            + outcome.adopted_source_count
            + outcome.ambiguous_event_count
            + outcome.unmatched_event_count
            + outcome.rejected_event_count
        )
        self.assertEqual(outcome.candidate_event_count, accounted, outcome)

    def test_far_future_event_waits_for_source_window(self):
        self._event(slug="discovery-far", local_date=date(2026, 9, 3))

        outcome, calls = self._discover()

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.awaiting_source_window_count, 1, outcome)
        self.assertEqual(outcome.unmatched_event_count, 0, outcome)
        self.assertEqual(outcome.candidate_event_count, 1, outcome)
        self.assertEqual(len(calls), 0)
        self._assert_conserved(outcome)

    def test_already_valid_identity_is_counted_without_request(self):
        event = self._event(slug="discovery-valid", local_date=date(2026, 8, 28))
        self._valid_identity(event)

        outcome, calls = self._discover()

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.already_valid_count, 1, outcome)
        self.assertEqual(outcome.candidate_event_count, 1, outcome)
        self.assertEqual(len(calls), 0)
        self._assert_conserved(outcome)

    def test_locked_and_out_of_scope_events_are_rejected(self):
        self._event(slug="discovery-locked", local_date=date(2026, 8, 28), locked=True)
        self._event(
            slug="discovery-france",
            local_date=date(2026, 8, 28),
            country_region=models.RacingRegion.FRANCE,
            timezone_name="Europe/Paris",
        )

        outcome, calls = self._discover()

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.rejected_event_count, 2, outcome)
        self.assertEqual(outcome.candidate_event_count, 2, outcome)
        self.assertEqual(len(calls), 0)
        self._assert_conserved(outcome)

    def test_in_window_unmatched_event_is_conserved(self):
        self._event(slug="discovery-unmatched", local_date=date(2026, 8, 28))
        self._event(slug="discovery-far-too", local_date=date(2026, 9, 10))

        outcome, calls = self._discover()

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.unmatched_event_count, 1, outcome)
        self.assertEqual(outcome.awaiting_source_window_count, 1, outcome)
        self.assertEqual(outcome.candidate_event_count, 2, outcome)
        self.assertEqual(len(calls), 1)
        self._assert_conserved(outcome)

    def test_budget_deferred_events_are_counted(self):
        self._event(slug="discovery-today", local_date=date(2026, 8, 28))
        self._event(slug="discovery-tomorrow", local_date=date(2026, 8, 29))
        limited_route = dataclasses.replace(self.route, request_budget=1)

        with patch(
            "stable.services.race_data_sync_providers.resolve_race_data_provider_route",
            return_value=limited_route,
        ):
            outcome, _calls = self._discover()

        self.assertTrue(outcome.success, outcome.reason_code)
        self.assertEqual(outcome.request_count, 1, outcome)
        self.assertEqual(outcome.deferred_event_count, 1, outcome)
        self.assertEqual(outcome.candidate_event_count, 2, outcome)
        self._assert_conserved(outcome)

    def _racecard_transport(self, rows):
        body = json.dumps({"racecards": rows, "ignored_secret": "never-log-this"}).encode()
        calls = []

        def transport(**kwargs):
            calls.append(kwargs)
            return RaceLiveProofHttpResponse(status_code=200, content_type="application/json", body=body, elapsed_ms=5)

        return transport, calls, hashlib.sha256(body).hexdigest()

    def _race(self, name, **overrides):
        return {"race_id": "race-one", "off_dt": "2026-08-28T09:30:00Z", "region": "jpn",
                "course": "Tokyo", "race_name": name, "race_status": "scheduled",
                "runners": [{"horse_id": "horse-one", "horse": "Alpha", "number": "1"}], **overrides}

    def test_diagnostics_distinguish_empty_region_date_course_and_name_mismatch(self):
        event = self._event(slug="match-cup", local_date=date(2026, 8, 28))
        scenarios = [([], "response_empty"),
            ([self._race(event.original_name, region="usa")], "region_not_found"),
            ([self._race(event.original_name, off_dt="2026-08-29T09:30:00Z")], "local_date_not_found"),
            ([self._race(event.original_name, course="Kyoto")], "course_not_found"),
            ([self._race("Other Cup")], "race_name_not_found")]
        for rows, reason in scenarios:
            with self.subTest(reason=reason):
                models.RaceLiveHostBudget.objects.all().delete()
                transport, calls, sha = self._racecard_transport(rows)
                outcome, _ = self._discover(transport)
                self.assertTrue(outcome.success, outcome)
                self.assertEqual(len(calls), 1)
                self.assertEqual(outcome.unmatched_event_count, 1)
                self._assert_conserved(outcome)
                bucket = outcome.diagnostic_buckets[0]
                self.assertEqual((bucket["region"], bucket["day"]), ("japan", "today"))
                self.assertEqual(bucket["response_sha256"], sha)
                self.assertEqual(bucket["response_race_count"], len(rows))
                self.assertEqual(bucket["match_reason_counts"], {reason: 1})
                self.assertEqual(bucket["unmatched_events"][0]["event_id"], event.pk)
                self.assertEqual(bucket["unmatched_events"][0]["reason"], reason)
                self.assertNotIn("never-log-this", json.dumps(dataclasses.asdict(outcome)))
                self.assertFalse(event.source_identities.exists())

    def test_diagnostics_keep_unique_match_and_ambiguous_rejection(self):
        event = self._event(slug="unique-cup", local_date=date(2026, 8, 28))
        transport, calls, _ = self._racecard_transport([self._race(event.original_name)])
        outcome, _ = self._discover(transport)
        self.assertEqual(outcome.created_source_count, 1, outcome)
        self.assertEqual(outcome.diagnostic_buckets[0]["match_reason_counts"], {"matched": 1})
        self.assertEqual(outcome.diagnostic_buckets[0]["unmatched_events"], [])
        self.assertEqual(len(calls), 1)
        self._assert_conserved(outcome)
        event.source_identities.all().delete()
        models.RaceLiveHostBudget.objects.all().delete()
        transport, calls, _ = self._racecard_transport([
            self._race(event.original_name), self._race(event.original_name, race_id="race-two")])
        outcome, _ = self._discover(transport)
        self.assertEqual(outcome.ambiguous_event_count, 1, outcome)
        self.assertEqual(outcome.diagnostic_buckets[0]["unmatched_events"][0]["reason"], "racecard_ambiguous")
        self.assertEqual(outcome.diagnostic_buckets[0]["unmatched_events"][0]["match_counts"]["name"], 2)
        self.assertFalse(event.source_identities.exists())
        self.assertEqual(len(calls), 1)
        self._assert_conserved(outcome)

    def test_diagnostic_samples_are_bounded_without_losing_counts(self):
        for i in range(53):
            self._event(slug=f"unmatched-{i}", local_date=date(2026, 8, 28))
        outcome, calls = self._discover()
        bucket = outcome.diagnostic_buckets[0]
        self.assertEqual(len(bucket["unmatched_events"]), 50)
        self.assertEqual(bucket["omitted_event_count"], 3)
        self.assertEqual(bucket["match_reason_counts"], {"response_empty": 53})
        self.assertEqual(outcome.unmatched_event_count, 53)
        self.assertEqual(len(calls), 1)
        self._assert_conserved(outcome)

    def test_completed_bucket_diagnostics_survive_later_provider_failure(self):
        self._event(slug="first-day", local_date=date(2026, 8, 28))
        self._event(slug="second-day", local_date=date(2026, 8, 29))
        requests = []

        def transport(**kwargs):
            requests.append(kwargs)
            return RaceLiveProofHttpResponse(status_code=200 if len(requests) == 1 else 503,
                content_type="application/json", body=b'{"racecards": []}', elapsed_ms=5)

        outcome, _ = self._discover(transport)
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.reason_code, "provider_response_invalid")
        self.assertEqual(len(requests), 2)
        self.assertEqual(outcome.unmatched_event_count, 1)
        self.assertEqual(outcome.deferred_event_count, 1)
        self.assertEqual(len(outcome.diagnostic_buckets), 1)
        self.assertEqual(outcome.diagnostic_buckets[0]["match_reason_counts"], {"response_empty": 1})
        self._assert_conserved(outcome)
