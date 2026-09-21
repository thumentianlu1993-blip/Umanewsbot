from datetime import date, datetime, timedelta, timezone
from django.test import TestCase, override_settings
from stable import models
from stable.services.race_source_identity import (
    identity_key,
    resolve_observation,
)
from stable.services.race_data_source_adapters import (
    parse_multisource_policy,
)
from stable.services.race_data_sync_enrollment import attach_multisource_observation

NOW = datetime(2026, 9, 20, 7, tzinfo=timezone.utc)


def policy_payload(provider="jra", region="japan_jra", kinds=("result",)):
    route = dict(
        provider=provider,
        region=region,
        country_region="japan",
        identity_namespace=provider + "-race-v1",
        operator="jra",
        source_class="official_operator",
        capabilities=list(kinds),
        allowed_hosts=["www.jra.go.jp"],
        allowed_path_prefixes=["/JRADB/"],
        parser_version="test-v1",
        contract_digest="a" * 64,
        proof_digest="b" * 64,
        terms_sha256="c" * 64,
        automation_allowed=True,
        proof_network_allowed=True,
        valid_from=(NOW - timedelta(days=1)).isoformat(),
        valid_until=(NOW + timedelta(days=30)).isoformat(),
        tiebreak_order=10,
        venue_aliases={"nakayama": ["Nakayama", "中山"]},
        timezone="Asia/Tokyo",
    )
    return dict(
        schema_version=3,
        policy_id="test",
        valid_from=route["valid_from"],
        valid_until=route["valid_until"],
        routes=[route],
    )


def observation(provider="jra", **overrides):
    value = dict(
        provider=provider,
        region="japan_jra",
        identity_namespace=provider + "-race-v1",
        external_race_id="20260920-11",
        canonical_url="https://www.jra.go.jp/JRADB/accessS.html",
        fetched_at=NOW.isoformat(),
        raw_sha256="d" * 64,
        parser_version="test-v1",
        operator="jra",
        venue_key="nakayama",
        local_date="2026-09-20",
        timezone="Asia/Tokyo",
        meeting_session="single",
        race_number="11",
        raw_names=["オールカマー"],
    )
    return {**value, **overrides}


@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra", "alternate"),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
)
class IdentityTests(TestCase):
    def setUp(self):
        from unittest.mock import patch

        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="all-comers",
            original_name="オールカマー",
            chinese_name="产经赏All Comers",
            country_region="japan",
            racecourse="中山",
            local_date=date(2026, 9, 20),
            timezone_name="Asia/Tokyo",
            visibility_status="published",
            status="scheduled",
        )
        self.policy = parse_multisource_policy(policy_payload(), now=NOW)
        self.route = self.policy.routes[0]

    def anchor(self):
        key = identity_key(observation())
        return models.RaceEventIdentityKey.objects.create(
            event=self.event,
            **key,
            evidence={"raw_sha256": "d" * 64},
            matcher_version="v2"
        )

    def test_names_alone_never_authorize(self):
        match = resolve_observation(observation(), route=self.route, now=NOW)
        self.assertEqual(match.status, "review_required")
        self.assertIsNone(match.event_id)
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), 0)

    def test_cross_language_strong_anchor(self):
        self.anchor()
        for name in ["Sankei Sho All Comers", "All Comer", "产经赏All Comers"]:
            match = resolve_observation(
                observation(raw_names=[name]), route=self.route, now=NOW
            )
            self.assertEqual((match.status, match.event_id), ("exact", self.event.pk))

    def test_context_date_and_operator_are_not_names(self):
        self.anchor()
        for change in (
            {"local_date": "2026-09-21"},
            {"race_number": "10"},
            {"operator": "nar"},
        ):
            self.assertNotEqual(
                resolve_observation(
                    observation(**change), route=self.route, now=NOW
                ).status,
                "exact",
            )

    def test_source_and_occurrence_disagreement(self):
        self.anchor()
        other = models.RaceEvent.objects.create(
            year=2026,
            slug="other",
            original_name="other",
            country_region="japan",
            racecourse="中山",
            local_date=date(2026, 9, 20),
            timezone_name="Asia/Tokyo",
        )
        models.RaceResultSourceIdentity.objects.create(
            event=other,
            source_key="jra",
            region_code="japan_jra",
            identity_namespace="jra-race-v1",
            external_race_id="20260920-11",
        )
        self.assertEqual(
            resolve_observation(observation(), route=self.route, now=NOW).status,
            "conflict",
        )

    def test_key_missing_session_is_not_guessed(self):
        self.assertIsNone(identity_key(observation(meeting_session="")))

    def test_route_digest_local_not_registry_wide(self):
        payload = policy_payload()
        old = parse_multisource_policy(payload, now=NOW).routes[0].digest
        payload["routes"] += policy_payload("other")["routes"]
        self.assertEqual(
            parse_multisource_policy(payload, now=NOW).routes[0].digest, old
        )

    def test_result_only_enrollment_replay_and_attach(self):
        self.anchor()
        first = attach_multisource_observation(
            observation(), policy=self.policy, now=NOW
        )
        self.assertEqual(first.action, "acquired")
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        self.assertEqual(enrollment.authority_version, 2)
        owner = models.RaceEventProjectionControl.objects.get(
            event=self.event
        ).owner_generation
        generation = enrollment.source_set_generation
        self.assertEqual(
            attach_multisource_observation(
                observation(), policy=self.policy, now=NOW
            ).action,
            "replay",
        )
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.source_set_generation, generation)
        payload = policy_payload()
        payload["routes"] += policy_payload("alternate")["routes"]
        policy = parse_multisource_policy(payload, now=NOW)
        # New policy is an explicit contract change, not silently adopted.
        decision = attach_multisource_observation(
            observation("alternate"), policy=policy, now=NOW
        )
        self.assertEqual(decision.reason_code, "enrollment_policy_drift")
        self.assertEqual(models.RaceDataSyncEnrollment.objects.count(), 1)
        self.assertEqual(
            models.RaceEventProjectionControl.objects.get(
                event=self.event
            ).owner_generation,
            owner,
        )

    def test_identity_only_does_not_create_checkpoint(self):
        self.anchor()
        policy = parse_multisource_policy(policy_payload(kinds=()), now=NOW)
        self.assertEqual(
            attach_multisource_observation(
                observation(), policy=policy, now=NOW
            ).action,
            "acquired",
        )
        self.assertEqual(models.RaceEventLiveProviderCheckpoint.objects.count(), 0)

    def test_manual_lock_no_partial_writes(self):
        self.anchor()
        self.event.manual_lock_flags = {"race_datetime": True}
        self.event.save()
        self.assertEqual(
            attach_multisource_observation(
                observation(), policy=self.policy, now=NOW
            ).action,
            "rejected",
        )
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), 0)
        self.assertEqual(models.RaceDataSyncEnrollment.objects.count(), 0)

    def test_jra_actual_result_identity_and_full_roster(self):
        from pathlib import Path
        from stable.services.race_data_source_adapters import parse_jra_observation

        page = (
            Path(__file__).parent
            / "fixtures/jra_pre_race/all_comers_official_result.html"
        ).read_text()
        value = parse_jra_observation(
            page,
            url="https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604061120260920/92",
            route=self.route,
            now=NOW,
        )
        self.assertEqual(value["race_number"], "11")
        self.assertEqual(len(value["roster"]), 13)
        self.assertEqual(value["roster"][0]["number"], "8")
        self.assertEqual(value["result_phase"], "official")
