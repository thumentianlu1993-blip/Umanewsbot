from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from stable import models
from stable.services import race_data_sync_enrollment
from stable.test_race_data_sync_r0 import NOW, SHA_A, SHA_C, create_event


def two_provider_roster():
    from stable.services import race_data_sync_pipeline as pipeline

    def _entry(provider: str, namespace: str, host: str):
        return pipeline.RaceDataProviderRosterEntry(
            provider=provider,
            regions=("japan",),
            enabled_regions=("japan",),
            source_class="official_operator",
            adapter_status="implemented",
            transport_enabled=True,
            apply_enabled=True,
            contract_version="race-data-v2",
            contract_digest=SHA_A,
            allowed_fields=("off_time",),
            identity_namespaces=(namespace,),
            data_kinds=tuple(models.RaceDataSyncDataKind.values),
            enabled_data_kinds=tuple(models.RaceDataSyncDataKind.values),
            terminal_markers=("OFFICIAL",),
            allowed_hosts=(host,),
            allowed_path_prefixes=("/v1/",),
            request_budget=20,
            minimum_interval_seconds=2,
            automation_allowed=True,
            proof_digest=SHA_C,
        )

    entries = (
        _entry("jra", "jra-race-v1", "jra.example.test"),
        _entry("nar", "nar-race-v1", "nar.example.test"),
    )
    registry_digest = pipeline._provider_roster_digest(schema_version=2, entries=entries)
    roster = pipeline.RaceDataProviderRoster(
        schema_version=2,
        registry_digest=registry_digest,
        entries=entries,
    )
    bindings = {}
    with patch.object(pipeline, "build_race_data_provider_roster", return_value=roster):
        for provider, namespace in (("jra", "jra-race-v1"), ("nar", "nar-race-v1")):
            resolved = pipeline.resolve_race_data_provider_route(
                provider=provider,
                region="japan",
                identity_namespace=namespace,
                data_kinds=models.RaceDataSyncDataKind.values,
            )
            assert resolved is not None
            bindings[provider] = resolved
    return roster, bindings


def _route(
    *,
    provider: str = "jra",
    namespace: str = "jra-race-v1",
    digest: str = SHA_A,
    eligible: bool = True,
    order: int = 1,
    kinds: list[str] | None = None,
    region: str = models.RacingRegion.JAPAN,
    region_code: str = "japan",
) -> dict:
    return {
        "country_region": region,
        "provider": provider,
        "region_code": region_code,
        "identity_namespace": namespace,
        "route_digest": digest,
        "data_kinds": kinds if kinds is not None else ["race_time", "racecard", "result"],
        "enrollment_eligible": eligible,
        "tiebreak_order": order,
    }


def _policy_v2(*, routes: list[dict] | None = None, **overrides) -> dict:
    value = {
        "schema_version": 2,
        "policy_id": "japan-fcfs-reviewed",
        "approved_by": "local-test-reviewer",
        "approved_at": NOW.isoformat(),
        "valid_from": (NOW - timedelta(days=1)).isoformat(),
        "valid_until": (NOW + timedelta(days=30)).isoformat(),
        "routes": routes if routes is not None else [_route()],
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
    value.update(overrides)
    return value


class StandingPolicyV2ParserTests(SimpleTestCase):
    def test_v2_policy_parses_fcfs_route_fields(self):
        policy = race_data_sync_enrollment.parse_standing_policy(_policy_v2())

        self.assertEqual(
            policy.new_enrollment_statuses,
            (models.RaceEventStatus.POSTPONED, models.RaceEventStatus.SCHEDULED),
        )
        self.assertEqual(
            policy.continuation_statuses,
            (
                models.RaceEventStatus.FINISHED,
                models.RaceEventStatus.POSTPONED,
                models.RaceEventStatus.RUNNING,
                models.RaceEventStatus.SCHEDULED,
            ),
        )
        route = policy.routes[0]
        self.assertTrue(route.enrollment_eligible)
        self.assertEqual(route.tiebreak_order, 1)

    def test_v1_policy_is_rejected_loudly(self):
        v1 = _policy_v2()
        v1["schema_version"] = 1
        v1["event_statuses"] = v1.pop("new_enrollment_statuses")
        del v1["continuation_statuses"]
        for route in v1["routes"]:
            del route["enrollment_eligible"]
            del route["tiebreak_order"]

        with self.assertRaises(ValueError):
            race_data_sync_enrollment.parse_standing_policy(v1)

    def test_result_only_route_cannot_be_enrollment_eligible(self):
        routes = [
            _route(kinds=["result"], eligible=True),
            _route(provider="nar", namespace="nar-race-v1", digest="b" * 64, order=2),
        ]
        with self.assertRaises(ValueError):
            race_data_sync_enrollment.parse_standing_policy(_policy_v2(routes=routes))

    def test_tiebreak_order_must_be_unique_within_region(self):
        routes = [
            _route(order=1),
            _route(provider="nar", namespace="nar-race-v1", digest="b" * 64, order=1),
        ]
        with self.assertRaises(ValueError):
            race_data_sync_enrollment.parse_standing_policy(_policy_v2(routes=routes))

    def test_tiebreak_order_must_be_a_positive_integer(self):
        for bad in (0, -1, True, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    race_data_sync_enrollment.parse_standing_policy(
                        _policy_v2(routes=[_route(order=bad)])
                    )

    def test_status_groups_are_required(self):
        value = _policy_v2()
        del value["continuation_statuses"]
        with self.assertRaises(ValueError):
            race_data_sync_enrollment.parse_standing_policy(value)


class RaceDataSyncCensusFcfsTests(TestCase):
    def setUp(self):
        self.roster, self.bindings = two_provider_roster()
        self.roster_patcher = patch(
            "stable.services.race_data_sync_pipeline.build_race_data_provider_roster",
            return_value=self.roster,
        )
        self.roster_patcher.start()
        self.addCleanup(self.roster_patcher.stop)

    def _policy(self, *, routes: list[dict] | None = None, **overrides) -> dict:
        if routes is None:
            routes = [
                _route(digest=self.bindings["jra"].route_digest, order=1),
                _route(
                    provider="nar",
                    namespace="nar-race-v1",
                    digest=self.bindings["nar"].route_digest,
                    order=2,
                ),
            ]
        return _policy_v2(routes=routes, **overrides)

    def _identity(self, event, *, provider: str = "jra", namespace: str = "jra-race-v1"):
        return models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key=provider,
            region_code="japan",
            identity_namespace=namespace,
            external_race_id=f"{provider}-{event.pk}",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=True,
            evidence_url=f"https://{provider}.example.test/reviewed-proof",
            evidence_sha256=SHA_A,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.roster.registry_digest,
        )

    def _census(self, policy: dict):
        return race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=policy,
            cutoff=NOW,
            horizon_days=30,
        )

    def test_multiple_eligible_routes_without_identity_do_not_produce_ambiguity(self):
        create_event(slug="fcfs-no-identity")

        census = self._census(self._policy())
        entry = census.entries[0]

        self.assertEqual(entry.classification, "blocked")
        self.assertEqual(entry.reason_code, "source_identity_missing")
        self.assertEqual(entry.provider, "jra")
        self.assertNotEqual(entry.reason_code, "standing_policy_route_ambiguous")

    def test_existing_identity_on_later_tiebreak_route_wins_by_stickiness(self):
        event = create_event(slug="fcfs-sticky")
        identity = self._identity(event, provider="nar", namespace="nar-race-v1")

        census = self._census(self._policy())
        entry = census.entries[0]

        self.assertEqual(entry.classification, "eligible")
        self.assertEqual(entry.provider, "nar")
        self.assertEqual(entry.source_identity_id, identity.pk)

    def test_result_only_route_is_never_an_enrollment_candidate(self):
        event = create_event(slug="fcfs-result-only")
        self._identity(event, provider="nar", namespace="nar-race-v1")
        policy = self._policy(
            routes=[
                _route(digest=self.bindings["jra"].route_digest, order=1),
                _route(
                    provider="nar",
                    namespace="nar-race-v1",
                    digest=self.bindings["nar"].route_digest,
                    eligible=False,
                    order=2,
                    kinds=["result"],
                ),
            ]
        )

        census = self._census(policy)
        entry = census.entries[0]

        self.assertEqual(entry.classification, "blocked")
        self.assertEqual(entry.reason_code, "source_identity_missing")
        self.assertEqual(entry.provider, "jra")

    def test_region_without_eligible_route_is_trusted_route_missing(self):
        create_event(slug="fcfs-no-eligible-route")
        policy = self._policy(
            routes=[
                _route(
                    provider="nar",
                    namespace="nar-race-v1",
                    digest=self.bindings["nar"].route_digest,
                    eligible=False,
                    order=1,
                    kinds=["result"],
                )
            ]
        )

        census = self._census(policy)

        self.assertEqual(census.entries[0].classification, "blocked")
        self.assertEqual(census.entries[0].reason_code, "trusted_route_missing")

    def _enroll(self, event) -> None:
        census = self._census(self._policy())
        manifest = race_data_sync_enrollment.build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=(event.pk,),
            candidate_commit="1" * 40,
            created_at=NOW,
            apply_expires_at=NOW + timedelta(hours=1),
        )
        race_data_sync_enrollment.apply_race_data_enrollment_manifest(
            manifest=manifest.as_dict(),
            expected_manifest_sha256=manifest.manifest_sha256,
            current_commit="1" * 40,
            now=NOW,
        )

    def test_enrolled_event_uses_continuation_statuses(self):
        event = create_event(slug="fcfs-enrolled-running")
        self._identity(event)
        self._enroll(event)
        event.status = models.RaceEventStatus.RUNNING
        event.save(update_fields=("status",))

        census = self._census(self._policy())

        self.assertEqual(census.entries[0].classification, "enrolled")

    def test_not_enrolled_running_event_uses_new_enrollment_statuses(self):
        event = create_event(slug="fcfs-running-not-enrolled")
        self._identity(event)
        event.status = models.RaceEventStatus.RUNNING
        event.save(update_fields=("status",))

        census = self._census(self._policy())

        self.assertEqual(census.entries[0].classification, "blocked")
        self.assertEqual(census.entries[0].reason_code, "event_status_not_allowed")

    def test_enrolled_event_outside_continuation_statuses_is_blocked(self):
        event = create_event(slug="fcfs-enrolled-cancelled")
        self._identity(event)
        self._enroll(event)
        event.status = models.RaceEventStatus.CANCELLED
        event.save(update_fields=("status",))

        census = self._census(self._policy())

        self.assertEqual(census.entries[0].classification, "blocked")
        self.assertEqual(census.entries[0].reason_code, "continuation_status_not_allowed")

    def test_two_sticky_identities_grant_by_tiebreak_order(self):
        event = create_event(slug="fcfs-two-sticky")
        jra_identity = self._identity(event, provider="jra", namespace="jra-race-v1")
        self._identity(event, provider="nar", namespace="nar-race-v1")

        census = self._census(self._policy())
        entry = census.entries[0]

        self.assertEqual(entry.classification, "eligible")
        self.assertEqual(entry.provider, "jra")
        self.assertEqual(entry.source_identity_id, jra_identity.pk)

    def test_far_future_event_is_awaiting_source_window(self):
        from datetime import date

        event = create_event(slug="fcfs-far-future")
        event.race_datetime = NOW + timedelta(days=10)
        event.local_date = date(2026, 8, 30)
        event.save(update_fields=("race_datetime", "local_date"))

        census = self._census(self._policy())
        entry = census.entries[0]

        self.assertEqual(entry.classification, "awaiting_source_window")
        self.assertEqual(entry.reason_code, "")

    def test_in_window_missing_identity_is_blocked_not_awaiting(self):
        create_event(slug="fcfs-in-window-missing")

        census = self._census(self._policy())
        entry = census.entries[0]

        self.assertEqual(entry.classification, "blocked")
        self.assertEqual(entry.reason_code, "source_identity_missing")
