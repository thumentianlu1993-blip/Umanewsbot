"""地区 producer → claim → writer → epoch reader 的隔离回放。

身份审核、历史正式名单及容量是明确的合成前置；HTML 是裁剪公开样本。
此文件证明接线，不把合成前置转换为生产权限或真实时效结论。
"""
from stable.test_race_lifecycle_capacity import synthetic_capacity

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from django.test import TestCase, override_settings
from stable import models
from stable.test_race_regional_lifecycle import FIX, route, route_for, NOW
from stable.services import race_data_source_adapters as adapters
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import claim_due_enrollments
from stable.services.race_lifecycle_projection import public_modules


def cases():
    yield route(
        "galopp_statistik"
    ), "/RennenDetails.php?Datum=2026-10-18&Nummer=4&Ort=Bad", "de-card", {}, "2026-10-18", 13
    yield route(
        "era"
    ), "/racecard/2026-03-28/9/declarations", "ae-page", {}, "2026-03-28", 9
    yield route_for(
        "racing_australia",
        "australia",
        "australia",
        "Australia/Sydney",
        "ra:NSW:Kembla Grange",
        ["Kembla Grange"],
        "www.racingaustralia.horse",
        "/FreeFields/",
    ), "/FreeFields/Acceptances.aspx?Key=2026Jul25,NSW,Kembla%20Grange", "au-card", {
        "race_number": "1"
    }, "2026-07-25", 11
    yield route_for(
        "nar",
        "japan_nar",
        "japan",
        "Asia/Tokyo",
        "nar:22",
        ["金沢", "金 沢"],
        "www.keiba.go.jp",
        "/KeibaWeb/",
    ), "/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11", "nar-card", {}, "2026-09-22", 12
    yield route_for(
        "hkjc",
        "hong_kong",
        "hong_kong",
        "Asia/Hong_Kong",
        "hkjc:ST",
        ["Sha Tin"],
        "racing.hkjc.com",
        "/en-us/local/information/",
    ), "/en-us/local/information/racecard?racedate=2026/10/25&Racecourse=ST&RaceNo=1", "hk-card-unavailable", {}, "2026-10-25", 11
    yield route_for(
        "zeturf",
        "france",
        "france",
        "Europe/Paris",
        "chantilly",
        ["Chantilly"],
        "www.zeturf.fr",
        "/fr/course-du-jour/",
    ), "/fr/course-du-jour/2026-09-19/R1C3-chantilly-prix-eclipse", "zt-fr", {}, "2026-09-19", 7
    for country, region, zone, venue, file, path, count in [
        (
            "united_kingdom",
            "united_kingdom",
            "Europe/London",
            "Southwell",
            "sl-gb",
            "2026-10-08/southwell/942396/get-raceday-ready-handicap",
            12,
        ),
        (
            "other",
            "ireland",
            "Europe/Dublin",
            "Thurles",
            "sl-ie",
            "2026-10-08/thurles/942856/irish-stallion-farms-ebf-fillies-maiden",
            10,
        ),
        (
            "united_states",
            "united_states",
            "America/New_York",
            "Belmont Park",
            "sl-us",
            "2026-09-18/belmont-park/939662/race-5-jockey-club-gold-cup-stakes-grade-1",
            7,
        ),
    ]:
        yield route_for(
            "sporting_life",
            region,
            country,
            zone,
            venue,
            [venue],
            "www.sportinglife.com",
            "/racing/",
        ), "/racing/results/" + path, file, {}, path[:10], count


@override_settings(
    RACE_LIFECYCLE_V2_WRITE_ENABLED=True,
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",),
)
class RegionalPipelineTests(TestCase):
    def test_all_new_region_producers_reach_public_epoch_with_reviewed_identity(self):
        for original, path, fixture, context, day, count in cases():
            with self.subTest(provider=original.provider, region=original.region):
                self.check_case(original, path, fixture, context, day, count)

    def check_case(self, original, path, fixture, context, day, count):
        now = datetime.fromisoformat(day + "T23:00:00").replace(
            tzinfo=ZoneInfo(original.timezone)
        )
        data = dict(original.payload)
        data.update(
            capabilities=["result"],
            valid_from=(now - timedelta(days=1)).isoformat(),
            valid_until=(now + timedelta(days=2)).isoformat(),
        )
        if original.provider == "era":
            data["allowed_path_prefixes"] = ["/racecard/", "/ajax/"]
            data["source_class"] = "official_operator"
        if original.provider == "galopp_statistik":
            data["allowed_path_prefixes"] = [
                "/RennenDetails.php",
                "/DisplayErgebnis.php",
            ]
        if original.provider == "racing_australia":
            data["source_class"] = "official_operator"
        policy = adapters.parse_multisource_policy(
            dict(
                schema_version=3,
                policy_id="region-replay",
                valid_from=data["valid_from"],
                valid_until=data["valid_until"],
                routes=[data],
            ),
            now=now,
        )
        r = policy.routes[0]
        host = r.payload["allowed_hosts"][0]
        url = "https://" + host + path

        def fetch(target, **kwargs):
            name = fixture
            if r.provider == "era" and "/ajax/" in target:
                name = "ae-result" if "results" in target else "ae-card"
            elif r.provider == "galopp_statistik" and "DisplayErgebnis" in target:
                name = "de-paired-result"
            elif r.provider == "racing_australia" and "Results.aspx" in target:
                name = "au-result"
            elif r.provider == "nar" and "RaceMarkTable" in target:
                name = "nar-result"
            elif r.provider == "hkjc" and "/localresults?" in target:
                name = "hk-result"
            return (FIX / (name + ".html")).read_text()

        fake = Mock()
        fake.source_identities.filter.return_value.first.return_value = SimpleNamespace(
            canonical_url=url, identity_fields={"multisource_v2": context}
        )
        fake.runners.exists.return_value = False
        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ):
            value = adapters.fetch_bound_observation(
                event=fake, route=r, now=now, fetcher=fetch
            )
        with patch("django.utils.timezone.now", return_value=now), patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=policy,
        ), override_settings(
            RACE_DATA_SYNC_ENABLED_PROVIDERS=(r.provider,),
            RACE_DATA_SYNC_ENABLED_REGIONS=(r.region,),
        ):
            event = models.RaceEvent.objects.create(
                year=now.year,
                slug="region-" + r.region,
                original_name=value["raw_names"][0],
                country_region=r.country_region,
                racecourse=r.venue_aliases[value["venue_key"]][0],
                local_date=datetime.fromisoformat(day).date(),
                timezone_name=r.timezone,
                visibility_status="published",
                status="scheduled",
            )
            source_value = {**value, "canonical_url": url}
            models.RaceResultSourceIdentity.objects.create(
                event=event,
                source_key=r.provider,
                region_code=r.region,
                identity_namespace=r.identity_namespace,
                external_race_id=value["external_race_id"],
                canonical_url=url,
                host=host,
                identity_fields={"multisource_v2": source_value},
                review_status="approved",
                terms_status="approved",
                automation_allowed=True,
                proof_network_allowed=True,
                reviewed_at=now,
                evidence_url=url,
                evidence_sha256=value["raw_sha256"],
                valid_until=now + timedelta(days=2),
                registry_digest=r.digest,
                result_authority=(
                    "official"
                    if r.source_class == "official_operator"
                    else "supplemental"
                ),
            )
            if not value.get("roster_complete"):
                # 仅模拟此前已经审核和入库的名单；不声称这些行来自第二份真实赛前抓取。
                models.RaceEventRunner.objects.bulk_create(
                    [
                        models.RaceEventRunner(
                            event=event,
                            horse_number=x["number"],
                            horse_name=x["horse_name"],
                            sort_order=i + 1,
                        )
                        for i, x in enumerate(value["roster"])
                    ]
                )
            decision = attach_multisource_observation(value, policy=policy, now=now)
            self.assertEqual(decision.action, "acquired", decision)
            capacity = synthetic_capacity(
                targets=[
                    dict(key=f"canonical:{event.pk}", region=r.region, key_race=True)
                ],
                proofs=[
                    dict(
                        region=r.region,
                        provider=r.provider,
                        host=host,
                        runtime_verified=True,
                        identity=True,
                        confirmed_card=True,
                        complete_result=True,
                        correction=True,
                        evidence_refs=["synthetic-only"],
                        discovery="full",
                        requests_per_fetch=3,
                    )
                ],
                budgets={host: 1000},
            )
            with override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(event.pk,)), patch(
                "stable.services.race_lifecycle_projection.capacity_manifest",
                return_value=capacity,
            ):
                claims = claim_due_enrollments(
                    now=now,
                    batch_size=20,
                    ttl_seconds=240,
                    enabled_providers=(r.provider,),
                    enabled_regions=(r.region,),
                    enabled_data_kinds=("result",),
                )
                self.assertEqual(len(claims), 1)
                result = adapters.run_multisource_claim(
                    claim=claims[0], now=now, fetcher=fetch
                )
                self.assertTrue(result["processed"], result)
                state = models.RaceLifecyclePublicState.objects.get(event=event)
                self.assertEqual(state.result_maturity, "confirmed")
                self.assertEqual(
                    len(public_modules(event.pk, now=now)["result"]), count
                )
