"""多地区离线合同；标注为 synthetic 的变体不作为生产抓取/条款 proof。"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from stable import models
from stable.test_race_multisource_identity import NOW, policy_payload
from stable.services.race_data_source_adapters import (
    parse_multisource_policy,
    parse_reference_observation,
    parse_nar_observation,
    parse_hkjc_observation,
    discover_source_url,
)
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_source_identity import identity_key

ROOT = Path(__file__).parent


def route_for(provider, region, country, zone, venue, names, host, prefix, kinds=()):
    data = policy_payload(provider, region, kinds=kinds)
    data["routes"][0].update(
        country_region=country,
        operator={"japan_nar": "nar", "hong_kong": "hkjc"}.get(region, region),
        source_class=(
            "licensed_api"
            if provider == "the_racing_api"
            else (
                "official_operator"
                if provider in ("jra", "nar", "hkjc", "official")
                else "trusted_publisher"
            )
        ),
        timezone=zone,
        venue_aliases={venue: names},
        allowed_hosts=[host],
        allowed_path_prefixes=[prefix],
    )
    return parse_multisource_policy(data, now=NOW).routes[0]


class RegionAdapterTests(TestCase):
    def test_real_sporting_cards_uk_us_and_synthetic_ireland_independent_route(self):
        from stable.race_reference_parsers.sporting_life import _next_data
        import json

        for file, region, country, zone, course, day, url in [
            (
                "sl-969.html",
                "united_kingdom",
                "united_kingdom",
                "Europe/London",
                "Ayr",
                date(2026, 9, 19),
                "https://www.sportinglife.com/racing/racecards/2026-09-19/ayr/racecard/939242/firth-of-clyde",
            ),
            (
                "sl-491.html",
                "united_states",
                "united_states",
                "America/New_York",
                "Belmont Park",
                date(2026, 9, 18),
                "https://www.sportinglife.com/racing/racecards/2026-09-18/belmont-at-the-big-a/racecard/939192/jockey-club-gold-cup",
            ),
            (
                "sl-969.html",
                "ireland",
                "other",
                "Europe/Dublin",
                "Curragh",
                date(2026, 9, 19),
                "https://www.sportinglife.com/racing/racecards/2026-09-19/curragh/racecard/939242/contract-example",
            ),
        ]:
            with self.subTest(region=region):
                page = (ROOT / "tests/fixtures/pre_race_refresh" / file).read_text()
                data = _next_data(page)
                summary = data["props"]["pageProps"]["race"]["race_summary"]
                if region == "ireland":
                    summary["course_name"] = "Curragh"
                    page = (
                        '<html><body><script id="__NEXT_DATA__">'
                        + json.dumps(data)
                        + "</script></body></html>"
                    )
                if region == "united_states":
                    url = url.replace(
                        "939192", str(summary["race_summary_reference"]["id"])
                    )
                route = route_for(
                    "sporting_life",
                    region,
                    country,
                    zone,
                    course,
                    [course],
                    "www.sportinglife.com",
                    "/racing/",
                )
                event = SimpleNamespace(
                    local_date=day, timezone_name=zone, race_datetime=None
                )
                value = parse_reference_observation(
                    page, url=url, route=route, now=NOW, event=event
                )
                self.assertEqual(value["region"], region)
                self.assertTrue(value["roster"])
                self.assertEqual(value["result_phase"], "")
                self.assertTrue(value["roster_complete"])

    def test_real_zeturf_gallop_and_synthetic_trot_exclusion(self):
        route = route_for(
            "zeturf",
            "france",
            "france",
            "Europe/Paris",
            "chantilly",
            ["Chantilly"],
            "www.zeturf.fr",
            "/fr/course-du-jour/",
        )
        page = (ROOT / "tests/fixtures/pre_race_refresh/zt-770.html").read_text()
        url = "https://www.zeturf.fr/fr/course-du-jour/2026-09-19/R1C3-chantilly-prix-eclipse"
        with self.assertRaisesRegex(RuntimeError, "uniquely prove"):
            parse_reference_observation(page, url=url, route=route, now=NOW)
        # 缩减旧 fixture 未保留 canonical；此行是标注过的合同变体，不是原站实测。
        page = page.replace("<head>", '<head><link rel="canonical" href="' + url + '">')
        value = parse_reference_observation(page, url=url, route=route, now=NOW)
        self.assertEqual((value["meeting_session"], value["race_number"]), ("1", "3"))
        self.assertEqual(value["result_phase"], "")
        with self.assertRaisesMessage(ValueError, "unsupported_race_type"):
            parse_reference_observation(
                page.replace("<title>", "<title>Trot attelé "),
                url=url,
                route=route,
                now=NOW,
            )

    def test_nar_real_roster_plus_synthetic_title_does_not_use_jra_operator(self):
        route = route_for(
            "nar",
            "japan_nar",
            "japan",
            "Asia/Tokyo",
            "nar:22",
            ["金沢", "金 沢", "金泽"],
            "www.keiba.go.jp",
            "/KeibaWeb/",
        )
        page = (
            (ROOT / "tests/fixtures/pre_race_refresh/nar.html")
            .read_text()
            .replace("<body>", "<body><h2>白山大賞典</h2>")
        )
        url = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11"
        value = parse_nar_observation(page, url=url, route=route, now=NOW)
        self.assertEqual(len(value["roster"]), 12)
        self.assertEqual(value["external_race_id"], "nar:2026-09-22:22:11")
        with self.assertRaisesMessage(ValueError, "nar_course_code_mismatch"):
            parse_nar_observation(
                page, url=url.replace("Code=22", "Code=20"), route=route, now=NOW
            )

    def test_hkjc_fixture_plus_synthetic_date_header(self):
        route = route_for(
            "hkjc",
            "hong_kong",
            "hong_kong",
            "Asia/Hong_Kong",
            "hkjc:HV",
            ["Happy Valley", "跑馬地", "跑马地"],
            "racing.hkjc.com",
            "/racing/",
        )
        page = (
            (ROOT / "fixtures/hkjc/html/localresults-race-sample.html")
            .read_text()
            .replace("<body>", "<body><p>2026/06/21</p>")
        )
        value = parse_hkjc_observation(
            page,
            url="https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx?RaceDate=2026/06/21&Racecourse=HV&RaceNo=1",
            route=route,
            now=NOW,
        )
        self.assertEqual(value["external_race_id"], "HK20260621HV01")
        self.assertEqual(value["race_number"], "1")
        self.assertTrue(value["roster"])

    def test_discovery_names_only_select_request_never_identity(self):

        payload = policy_payload()
        payload["routes"][0]["discovery_urls"] = [
            "https://www.jra.go.jp/JRADB/index.html"
        ]
        route = parse_multisource_policy(payload, now=NOW).routes[0]
        event = SimpleNamespace(
            original_name="オールカマー",
            chinese_name="",
            source_refs={},
            local_date=date(2026, 9, 20),
        )
        fetch = lambda *a, **kw: '<a href="/JRADB/real-detail.html">オールカマー</a>'
        self.assertEqual(
            discover_source_url(event=event, route=route, now=NOW, fetcher=fetch),
            "https://www.jra.go.jp/JRADB/real-detail.html",
        )
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())


@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("official", "the_racing_api"),
)
class SevenBucketDedupTests(TestCase):
    def setUp(self):
        clock=patch("django.utils.timezone.now",return_value=NOW)
        clock.start();self.addCleanup(clock.stop)

    def test_all_buckets_both_arrival_orders_cross_language_one_event_owner(self):
        buckets = [
            ("japan_jra", "japan", "Asia/Tokyo"),
            ("japan_nar", "japan", "Asia/Tokyo"),
            ("hong_kong", "hong_kong", "Asia/Hong_Kong"),
            ("united_kingdom", "united_kingdom", "Europe/London"),
            ("ireland", "other", "Europe/Dublin"),
            ("france", "france", "Europe/Paris"),
            ("united_states", "united_states", "America/New_York"),
        ]
        for region, country, zone in buckets:
            for order in [
                ("official", "the_racing_api"),
                ("the_racing_api", "official"),
            ]:
                with self.subTest(region=region, order=order), override_settings(
                    RACE_DATA_SYNC_ENABLED_REGIONS=(region,)
                ):
                    event = models.RaceEvent.objects.create(
                        year=2026,
                        slug=region + "-" + order[0],
                        original_name="原名",
                        country_region=country,
                        racecourse=region,
                        local_date=date(2026, 9, 20),
                        timezone_name=zone,
                        visibility_status="published",
                    )
                    payload = policy_payload()
                    payload["routes"] = []
                    for provider in order:
                        route = route_for(
                            provider,
                            region,
                            country,
                            zone,
                            region,
                            [region],
                            "www.example.com",
                            "/races/",
                        )
                        payload["routes"].append(route.payload)
                    policy = parse_multisource_policy(payload, now=NOW)
                    value = dict(
                        region=region,
                        operator=region,
                        venue_key=region,
                        local_date="2026-09-20",
                        timezone=zone,
                        meeting_session=order[0],
                        race_number="1",
                        raw_names=["原名"],
                        fetched_at=NOW.isoformat(),
                        raw_sha256="d" * 64,
                        parser_version="test-v1",
                    )
                    models.RaceEventIdentityKey.objects.create(
                        event=event,
                        **identity_key(value),
                        evidence={"fixture": "synthetic reviewed key"},
                        matcher_version="v2"
                    )
                    for index, provider in enumerate(order):
                        observation = {
                            **value,
                            "provider": provider,
                            "operator": policy.routes[index].operator,
                            "identity_namespace": provider + "-race-v1",
                            "external_race_id": event.slug,
                            "canonical_url": "https://www.example.com/races/"
                            + event.slug,
                            "raw_names": ["完全不同语种" if index else "原名"],
                        }
                        # NAR/HKJC canonical operator is shared by all providers.
                        if index == 0 and observation["operator"] != value["operator"]:
                            models.RaceEventIdentityKey.objects.filter(
                                event=event
                            ).delete()
                            models.RaceEventIdentityKey.objects.create(
                                event=event,
                                **identity_key(observation),
                                evidence={"fixture": "synthetic reviewed key"},
                                matcher_version="v2"
                            )
                        decision = attach_multisource_observation(
                            observation, policy=policy, now=NOW
                        )
                        self.assertEqual(
                            decision.action,
                            "acquired" if index == 0 else "attached",
                            decision,
                        )
                    self.assertEqual(
                        event.race_data_sync_enrollment.source_bindings.count(), 2
                    )
                    self.assertEqual(event.projection_control.owner_generation, 1)


class TraBindingAdapterTests(TestCase):
    @override_settings(
        RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ALLOW_NETWORK=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
        RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    )
    def test_free_card_transport_initializes_host_budget_without_network(self):
        import json
        from stable.services.race_data_source_adapters import fetch_tra_observation

        registry = json.loads(
            (
                ROOT.parents[1]
                / "runtime/policies/race_live/source_registry_the_racing_api_free.json"
            ).read_text()
        )
        route = route_for(
            "the_racing_api",
            "japan_jra",
            "japan",
            "Asia/Tokyo",
            "nakayama",
            ["Nakayama"],
            "api.theracingapi.com",
            "/v1/",
            kinds=("racecard",),
        )
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="tra-adapter",
            original_name="All Comers",
            racecourse="Nakayama",
            country_region="japan",
            local_date=date(2026, 9, 20),
            timezone_name="Asia/Tokyo",
        )
        body = {
            "racecards": [
                {
                    "race_id": "race_1",
                    "race_name": "All Comers",
                    "off_dt": "2026-09-20T06:45:00Z",
                    "region": "jpn",
                    "course": "Nakayama",
                    "runners": [
                        {
                            "horse_id": "hrs_1",
                            "horse": "Horse",
                            "number": "1",
                            "jockey": "Jockey",
                        }
                    ],
                }
            ]
        }

        def cache(**kw):
            return kw["fetcher"]()[0], "e" * 64

        with patch(
            "stable.services.race_live_source_proof.read_the_racing_api_automation_registry",
            return_value=(registry, route.proof_digest),
        ), patch(
            "stable.services.race_live_source_proof._read_secret",
            return_value=("test-only", "test-only"),
        ), patch(
            "stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot",
            side_effect=cache,
        ), patch(
            "stable.services.race_data_sync_providers._fetch_json",
            return_value=(body, "d" * 64),
        ) as transport, patch(
            "django.utils.timezone.now", return_value=NOW
        ):
            value = fetch_tra_observation(
                event=event, route=route, now=NOW, kind="racecard"
            )
        self.assertEqual(value["external_race_id"], "race_1")
        self.assertFalse(value["roster"][0]["status_reported"])
        self.assertEqual(transport.call_count, 1)
        self.assertGreaterEqual(
            models.RaceLiveHostBudget.objects.get(
                host="api.theracingapi.com"
            ).min_interval_ms,
            2000,
        )
