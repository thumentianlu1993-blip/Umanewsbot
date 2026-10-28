"""地区接入回归；真实裁剪样本与合成异常严格区分，测试无网络。"""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import json
from bs4 import BeautifulSoup
from django.test import SimpleTestCase
from stable.test_race_multisource_regions import route_for, NOW
from stable.services import race_data_source_adapters as adapters

ROOT = Path(__file__).parent
FIX = ROOT / "tests/fixtures/regional_lifecycle"
ME = ROOT / "fixtures/middle_east"


def route(provider):
    args = {
        "racing_australia": (
            "australia",
            "australia",
            "Australia/Melbourne",
            "ra:VIC:The Valley",
            ["The Valley"],
            "racingaustralia.horse",
            "/FreeFields/",
        ),
        "era": (
            "united_arab_emirates",
            "united_arab_emirates",
            "Asia/Dubai",
            "era:meydan",
            ["Meydan"],
            "emiratesracing.com",
            "/ajax/",
        ),
        "jcsa": (
            "saudi_arabia",
            "saudi_arabia",
            "Asia/Riyadh",
            "jcsa:riyadh",
            ["King Abdulaziz Racetrack"],
            "jcsa.sa",
            "/api/meeting-info/",
        ),
        "galopp_statistik": (
            "germany",
            "germany",
            "Europe/Berlin",
            "de:baden",
            ["Baden-Baden"],
            "www.galopp-statistik.de",
            "/DisplayErgebnis.php",
        ),
    }[provider]
    return route_for(provider, *args)


class RegionalParserTests(SimpleTestCase):
    def parse(self, provider, page, url, **context):
        return adapters.parse_regional_observation(
            page, url=url, route=route(provider), now=NOW, context=context
        )

    def test_australia_result_full_roster_includes_scratch(self):
        value = self.parse(
            "racing_australia",
            (
                ROOT / "fixtures/australia/ra_results_2025-10-25_thevalley.html"
            ).read_text(),
            "https://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct25,VIC,The%20Valley",
            race_number="10",
        )
        self.assertEqual(len(value["roster"]), 9)
        self.assertEqual(value["roster"][-1]["status"], "scratched")
        self.assertEqual(value["local_date"], "2025-10-25")
        self.assertEqual(value["result_phase"], "official")
        self.assertFalse(value["roster_complete"])  # 独立名单核验由 fetch 层完成
        self.assertEqual(value["off_time"], "2025-10-25T17:40:00+11:00")

    def test_australia_wrong_date_or_no_race_cannot_select_by_name(self):
        page = (
            ROOT / "fixtures/australia/ra_results_2025-10-25_thevalley.html"
        ).read_text()
        for url, ctx in [
            (
                "https://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct24,VIC,The%20Valley",
                {"race_number": "10"},
            ),
            (
                "https://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct25,VIC,The%20Valley",
                {},
            ),
        ]:
            with self.assertRaises(ValueError):
                self.parse("racing_australia", page, url, **ctx)

    def test_era_result_selects_exact_race_and_rejects_arabian(self):
        page = (
            ME / "era_ajax_racecard-results-all_2026-03-28_races8_9.html"
        ).read_text()
        value = self.parse(
            "era",
            page,
            "https://emiratesracing.com/ajax/racecard-results-all?date=2026-03-28",
            race_number="9",
        )
        self.assertEqual(
            value["raw_names"], ["Dubai World Cup Sponsored by Emirates Airline"]
        )
        self.assertEqual(value["roster"][0]["horse_name"], "MAGNITUDE")
        self.assertEqual(value["off_time"], "2026-03-28T20:45:00+04:00")
        with self.assertRaisesRegex(ValueError, "race_type"):
            self.parse(
                "era",
                page.replace("Thoroughbred", "Purebred Arabian"),
                "https://emiratesracing.com/ajax/racecard-results-all?date=2026-03-28",
                race_number="9",
            )

    def test_era_parallel_winners_kept_not_renumbered(self):
        page = (
            ME / "era_ajax_racecard-results-all_2026-02-28_r3_deadheat.html"
        ).read_text()
        # 旧裁剪样本缺少场头日期/马场，以下补充仅是合成边界用例。
        page = page.replace(
            "<h2 ",
            '<img src="/tracks/meydan-1200.png"><a href="/racecard/2026-02-28/3/results/pdf">Results</a><h2 ',
            1,
        )
        value = self.parse(
            "era",
            page,
            "https://emiratesracing.com/ajax/racecard-results-all?date=2026-02-28",
            race_number="3",
        )
        self.assertGreaterEqual(
            sum(r["status"] == "dead_heat" for r in value["roster"]), 2
        )

    def test_jcsa_missing_card_numbers_and_identity_fail_closed(self):
        page = (
            ME / "jcsa_api_meeting-info_en_20260214_9_Results_True.html"
        ).read_text()
        url = "https://jcsa.sa/api/meeting-info/en/20260214/9/Results/True"
        with self.assertRaisesRegex(ValueError, "context"):
            self.parse("jcsa", page, url)
        value = self.parse(
            "jcsa",
            page,
            url,
            local_date="2026-02-14",
            race_number="9",
            racecourse="King Abdulaziz Racetrack",
            raw_names=["Saudi Cup (G1)"],
        )
        self.assertEqual(len(value["roster"]), 14)
        self.assertFalse(value["roster_complete"])
        self.assertTrue(all(not r["number"] for r in value["roster"]))
        self.assertEqual(value["roster"][-1]["status"], "unknown")
        self.assertEqual(value["result_phase"], "")

    def test_german_result_does_not_use_draw_as_horse_number(self):
        value = self.parse(
            "galopp_statistik",
            (FIX / "galopp-de.html").read_text(),
            "https://www.galopp-statistik.de/DisplayErgebnis.php?id=14273",
        )
        self.assertEqual(value["local_date"], "2026-06-07")
        self.assertEqual(value["race_number"], "7")
        self.assertEqual(value["roster"][0]["barrier"], "5")
        self.assertEqual(value["roster"][0]["number"], "")
        self.assertFalse(value["roster_complete"])
        self.assertEqual(value["result_phase"], "official")

    def test_german_unknown_finish_fails_instead_of_dropping_horse(self):
        page = (FIX / "galopp-de.html").read_text()
        soup = BeautifulSoup(page, "html.parser")
        soup.select_one(".place").string = "???"
        with self.assertRaisesRegex(ValueError, "status"):
            self.parse(
                "galopp_statistik",
                str(soup),
                "https://www.galopp-statistik.de/DisplayErgebnis.php?id=14273",
            )

    def test_unsupported_and_expired_routes_fail_before_parsing(self):
        from dataclasses import replace

        r = route("era")
        r = replace(
            r,
            payload={
                **r.payload,
                "valid_until": (NOW - timedelta(seconds=1)).isoformat(),
            },
        )
        with self.assertRaises(ValueError):
            adapters.parse_regional_observation(
                "", url="https://emiratesracing.com/ajax/x", route=r, now=NOW
            )

    def test_sporting_real_uk_ireland_result_time_is_utc(self):
        for file, region, country, zone, course, rid, slug, hour in [
            (
                "sl-gb",
                "united_kingdom",
                "united_kingdom",
                "Europe/London",
                "Southwell",
                942396,
                "get-raceday-ready-handicap",
                "16:00",
            ),
            (
                "sl-ie",
                "ireland",
                "other",
                "Europe/Dublin",
                "Thurles",
                942856,
                "irish-stallion-farms-ebf-fillies-maiden",
                "12:16",
            ),
        ]:
            with self.subTest(region=region):
                r = route_for(
                    "sporting_life",
                    region,
                    country,
                    zone,
                    course,
                    [course],
                    "www.sportinglife.com",
                    "/racing/",
                )
                value = adapters.parse_reference_observation(
                    (FIX / (file + ".html")).read_text(),
                    url=f"https://www.sportinglife.com/racing/results/2026-10-08/{course.lower()}/{rid}/{slug}",
                    route=r,
                    now=NOW,
                )
                self.assertEqual(value["off_time"], f"2026-10-08T{hour}:00+00:00")
                self.assertTrue(
                    all(
                        x["field_provenance"].get("raw_sha256") for x in value["roster"]
                    )
                )
                self.assertEqual(value["result_phase"], "official")

    def test_france_public_mobile_header_proves_race_identity(self):
        r = route_for(
            "zeturf",
            "france",
            "france",
            "Europe/Paris",
            "chantilly",
            ["Chantilly"],
            "www.zeturf.fr",
            "/fr/course-du-jour/",
        )
        url = "https://www.zeturf.fr/fr/course-du-jour/2026-09-19/R1C3-chantilly-prix-eclipse-tattersalls-fonds-europeen-de-l-elevage"
        page = (FIX / "zt-fr.html").read_text()
        value = adapters.parse_reference_observation(page, url=url, route=r, now=NOW)
        self.assertEqual(value["result_phase"], "official")
        self.assertEqual(len(value["roster"]), 7)
        with self.assertRaises((ValueError, RuntimeError)):
            adapters.parse_reference_observation(
                page.replace("R1C3", "R1C4"), url=url, route=r, now=NOW
            )

    def test_new_providers_dispatch_through_bound_fetch(self):
        from unittest.mock import Mock, patch

        r = route_for(
            "racing_australia",
            "australia",
            "australia",
            "Australia/Sydney",
            "ra:NSW:Kembla Grange",
            ["Kembla Grange"],
            "www.racingaustralia.horse",
            "/FreeFields/",
        )
        for kind in ("Acceptances", "Results"):
            url = f"https://www.racingaustralia.horse/FreeFields/{kind}.aspx?Key=2026Jul25,NSW,Kembla%20Grange"
            source = SimpleNamespace(
                canonical_url=url,
                identity_fields={"multisource_v2": {"race_number": "1"}},
            )
            event = Mock()
            event.source_identities.filter.return_value.first.return_value = source
            event.runners.exists.return_value = False
            calls = []

            def fetch(url, **kwargs):
                calls.append(url)
                return (
                    FIX / ("au-card.html" if "Acceptances" in url else "au-result.html")
                ).read_text()

            with patch(
                "stable.services.race_source_identity.seed_evidence", return_value=None
            ):
                value = adapters.fetch_bound_observation(
                    event=event, route=r, now=NOW, fetcher=fetch
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(
                value["external_race_id"], "ra:NSW:Kembla Grange:2026-07-25:1"
            )
            self.assertTrue(value["roster_complete"])
            self.assertEqual(
                sum(r["status"] == "scratched" for r in value["roster"]), 4
            )

    def test_sporting_explicit_declared_card_sets_maturity_but_dormant_does_not(self):
        from datetime import date
        from stable.race_reference_parsers.sporting_life import _next_data

        data = _next_data(
            (ROOT / "tests/fixtures/pre_race_refresh/sl-969.html").read_text()
        )
        r = route_for(
            "sporting_life",
            "united_kingdom",
            "united_kingdom",
            "Europe/London",
            "Ayr",
            ["Ayr"],
            "www.sportinglife.com",
            "/racing/",
        )
        for stage, expected in [("DECLARED", "confirmed"), ("DORMANT", "predicted")]:
            data["props"]["pageProps"]["race"]["race_summary"]["race_stage"] = stage
            page = (
                '<html><body><script id="__NEXT_DATA__">'
                + json.dumps(data)
                + "</script></body></html>"
            )
            value = adapters.parse_reference_observation(
                page,
                url="https://www.sportinglife.com/racing/racecards/2026-09-19/ayr/racecard/939242/firth-of-clyde",
                route=r,
                now=NOW,
                event=SimpleNamespace(local_date=date(2026, 9, 19), race_datetime=None),
            )
            self.assertEqual(value["declaration_status"], expected)

    def test_full_result_with_a_deleted_row_does_not_remain_complete(self):
        from stable.race_reference_parsers.sporting_life import _next_data

        data = _next_data((FIX / "sl-gb.html").read_text())
        data["props"]["pageProps"]["race"]["rides"].pop()
        page = (
            '<html><body><script id="__NEXT_DATA__">'
            + json.dumps(data)
            + "</script></body></html>"
        )
        r = route_for(
            "sporting_life",
            "united_kingdom",
            "united_kingdom",
            "Europe/London",
            "Southwell",
            ["Southwell"],
            "www.sportinglife.com",
            "/racing/",
        )
        value = adapters.parse_reference_observation(
            page,
            url="https://www.sportinglife.com/racing/results/2026-10-08/southwell/942396/get-raceday-ready-handicap",
            route=r,
            now=NOW,
        )
        self.assertFalse(value["roster_complete"])
        self.assertEqual(value["result_phase"], "")

    def test_saudi_declared_roster_has_stable_ids_numbers_and_explicit_nr(self):
        value = self.parse(
            "jcsa",
            (FIX / "sa-declared.html").read_text(),
            "https://jcsa.sa/api/meeting-info/en/20260214/9/Declared/True",
            local_date="2026-02-14",
            race_number="9",
            racecourse="King Abdulaziz Racetrack",
            raw_names=["Saudi Cup (G1)"],
        )
        self.assertEqual(value["declaration_status"], "confirmed")
        self.assertTrue(value["roster_complete"])
        withdrawn = next(r for r in value["roster"] if r["number"] == "10")
        self.assertEqual(withdrawn["external_runner_id"], "/en/horses/H-74085")
        self.assertEqual(withdrawn["status"], "withdrawn")
        self.assertEqual(withdrawn["barrier"], "")

    def test_saudi_exact_same_source_join_resolves_missing_status(self):
        from stable.services.race_regional_sources import merge_jcsa_rosters

        ctx = dict(
            local_date="2026-02-14",
            race_number="9",
            racecourse="King Abdulaziz Racetrack",
            raw_names=["Saudi Cup (G1)"],
        )
        card = self.parse(
            "jcsa",
            (FIX / "sa-declared.html").read_text(),
            "https://jcsa.sa/api/meeting-info/en/20260214/9/Declared/True",
            **ctx,
        )
        result = self.parse(
            "jcsa",
            (ME / "jcsa_api_meeting-info_en_20260214_9_Results_True.html").read_text(),
            "https://jcsa.sa/api/meeting-info/en/20260214/9/Results/True",
            **ctx,
        )
        value = merge_jcsa_rosters(result, card)
        self.assertEqual(value["result_phase"], "official")
        self.assertTrue(value["roster_complete"])
        self.assertEqual(value["roster"][-1]["number"], "10")
        self.assertEqual(value["roster"][-1]["status"], "withdrawn")
        self.assertEqual(
            sum(r["reported_finish_position"] is not None for r in value["roster"]), 13
        )
        self.assertEqual(value["roster_evidence"]["raw_sha256"], card["raw_sha256"])
        self.assertEqual(
            value["roster"][-1]["field_provenance"]["status"]["raw_sha256"],
            card["raw_sha256"],
        )

    def test_saudi_join_rejects_different_event_missing_id_or_finished_nr(self):
        from copy import deepcopy
        from stable.services.race_regional_sources import merge_jcsa_rosters

        ctx = dict(
            local_date="2026-02-14",
            race_number="9",
            racecourse="King Abdulaziz Racetrack",
            raw_names=["Saudi Cup (G1)"],
        )
        card = self.parse(
            "jcsa",
            (FIX / "sa-declared.html").read_text(),
            "https://jcsa.sa/api/meeting-info/en/20260214/9/Declared/True",
            **ctx,
        )
        result = self.parse(
            "jcsa",
            (ME / "jcsa_api_meeting-info_en_20260214_9_Results_True.html").read_text(),
            "https://jcsa.sa/api/meeting-info/en/20260214/9/Results/True",
            **ctx,
        )
        for mutation in ("date", "missing", "contradiction", "name"):
            other = deepcopy(card)
            if mutation == "date":
                other["local_date"] = "2026-02-13"
            elif mutation == "missing":
                other["roster"].pop()
            elif mutation == "name":
                other["roster"][0]["horse_name"] = "Wrong Horse"
            else:
                other["roster"][0]["status"] = "withdrawn"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                merge_jcsa_rosters(result, other)

    def test_saudi_bound_fetch_joins_public_declared_endpoint(self):
        from unittest.mock import Mock, patch

        r = route("jcsa")
        url = "https://jcsa.sa/api/meeting-info/en/20260214/9/Results/True"
        source = SimpleNamespace(
            canonical_url=url,
            identity_fields={
                "multisource_v2": dict(
                    local_date="2026-02-14",
                    race_number="9",
                    venue_key="jcsa:riyadh",
                    raw_names=["Saudi Cup (G1)"],
                )
            },
        )
        event = Mock()
        event.source_identities.filter.return_value.first.return_value = source
        event.runners.exists.return_value = False
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            return (
                (FIX / "sa-declared.html").read_text()
                if "/Declared/" in url
                else (
                    ME / "jcsa_api_meeting-info_en_20260214_9_Results_True.html"
                ).read_text()
            )

        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ):
            value = adapters.fetch_bound_observation(
                event=event, route=r, now=NOW, fetcher=fetch
            )
        self.assertEqual(calls, [url, url.replace("/Results/", "/Declared/")])
        self.assertTrue(value["roster_complete"])
        self.assertEqual(value["result_phase"], "official")
        self.assertEqual(value["roster"][-1]["status"], "withdrawn")


from django.test import TestCase, override_settings


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
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jcsa",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("saudi_arabia",),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",),
)
class SaudiPipelineTests(TestCase):
    def setUp(self):
        from unittest.mock import patch
        from stable import models
        from stable.services.race_source_identity import identity_key
        from stable.services.race_data_sync_enrollment import (
            attach_multisource_observation,
        )

        self.now = NOW.replace(month=2, day=14, hour=18)
        p = route("jcsa").payload.copy()
        p.update(
            capabilities=["result"],
            source_class="official_operator",
            valid_from=(self.now - timedelta(days=1)).isoformat(),
            valid_until=(self.now + timedelta(days=30)).isoformat(),
        )
        self.policy = adapters.parse_multisource_policy(
            dict(
                schema_version=3,
                policy_id="sa-test",
                valid_from=p["valid_from"],
                valid_until=p["valid_until"],
                routes=[p],
            ),
            now=self.now,
        )
        self.route = self.policy.routes[0]
        for name, value in [
            ("django.utils.timezone.now", self.now),
            (
                "stable.services.race_data_source_adapters.load_multisource_policy",
                self.policy,
            ),
        ]:
            mock = patch(name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.ctx = dict(
            local_date="2026-02-14",
            race_number="9",
            racecourse="King Abdulaziz Racetrack",
            raw_names=["Saudi Cup (G1)"],
        )
        self.card = (FIX / "sa-declared.html").read_text()
        self.result = (
            ME / "jcsa_api_meeting-info_en_20260214_9_Results_True.html"
        ).read_text()
        card = adapters.parse_regional_observation(
            self.card,
            url="https://jcsa.sa/api/meeting-info/en/20260214/9/Declared/True",
            route=self.route,
            now=self.now,
            context=self.ctx,
        )
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="saudi-cup",
            original_name="Saudi Cup (G1)",
            country_region="saudi_arabia",
            racecourse=self.ctx["racecourse"],
            local_date=self.now.date(),
            timezone_name="Asia/Riyadh",
            visibility_status="published",
            status="scheduled",
        )
        # 模拟已由人工审核/来源身份流程核验的赛事键，不能用名称自动生成正式身份。
        models.RaceEventIdentityKey.objects.create(
            event=self.event,
            **identity_key(card),
            evidence={"raw_sha256": card["raw_sha256"]},
            matcher_version="v2",
        )
        decision = attach_multisource_observation(
            card, policy=self.policy, now=self.now
        )
        self.assertEqual(decision.action, "acquired", decision)
        self.calls = []
        config = override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,))
        config.enable()
        self.addCleanup(config.disable)
        capacity = dict(
            targets=[
                dict(
                    key=f"canonical:{self.event.pk}",
                    region="saudi_arabia",
                    key_race=True,
                )
            ],
            proofs=[
                dict(
                    region="saudi_arabia",
                    provider="jcsa",
                    host="jcsa.sa",
                    runtime_verified=True,
                    identity=True,
                    confirmed_card=True,
                    complete_result=True,
                    correction=True,
                    evidence_refs=["synthetic-only"],
                    discovery="full",
                    requests_per_fetch=2,
                )
            ],
            budgets={"jcsa.sa": 1000},
        )
        mock = patch(
            "stable.services.race_lifecycle_projection.capacity_manifest",
            return_value=capacity,
        )
        mock.start()
        self.addCleanup(mock.stop)

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        return self.card if "/Declared/" in url else self.result

    def run_claim(self):
        from stable.services.race_data_sync_control import claim_due_enrollments

        claims = claim_due_enrollments(
            now=self.now,
            batch_size=20,
            ttl_seconds=240,
            enabled_providers=("jcsa",),
            enabled_regions=("saudi_arabia",),
            enabled_data_kinds=("result",),
        )
        self.assertEqual(len(claims), 1)
        return adapters.run_multisource_claim(
            claim=claims[0], now=self.now, fetcher=self.fetch
        )

    def test_bound_declared_source_publishes_complete_result_with_nr(self):
        from stable import models

        result = self.run_claim()
        self.assertTrue(result["processed"], result)
        self.event.refresh_from_db()
        self.assertEqual(
            (self.event.status, self.event.runners.count(), self.event.results.count()),
            ("finished", 14, 14),
        )
        self.assertEqual(
            self.event.results.filter(official_finish_position__isnull=False).count(),
            13,
        )
        self.assertEqual(
            self.event.results.get(horse_number="10").official_finish_position, None
        )
        self.assertIsNotNone(self.event.result_confirmed_at)
        self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 1)
        self.assertEqual(len(self.calls), 2)
        from stable.services.race_lifecycle_projection import public_modules

        state = models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual(state.result_maturity, "confirmed")
        self.assertEqual(len(public_modules(self.event.pk, now=self.now)["result"]), 14)

    def test_missing_declared_row_cannot_publish(self):
        from stable import models

        soup = BeautifulSoup(self.card, "html.parser")
        soup.select("tr.meeting-info-horse-item")[-1].decompose()
        self.card = str(soup)
        result = self.run_claim()
        self.assertFalse(result["processed"], result)
        self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 0)
        self.assertEqual(self.event.results.count(), 0)


class RegionalBoundaryTests(SimpleTestCase):
    def test_duplicate_or_zero_number_is_not_final_card(self):
        r = route("jcsa")
        url = "https://jcsa.sa/api/meeting-info/en/20260214/9/Declared/True"
        for cloth in ("0 (1)", "10 (1)"):
            soup = BeautifulSoup((FIX / "sa-declared.html").read_text(), "html.parser")
            soup.select_one("tr.meeting-info-horse-item td").string = cloth
            with self.subTest(cloth=cloth), self.assertRaises(ValueError):
                adapters.parse_regional_observation(
                    str(soup),
                    url=url,
                    route=r,
                    now=NOW,
                    context=dict(
                        local_date="2026-02-14",
                        race_number="9",
                        racecourse="King Abdulaziz Racetrack",
                        raw_names=["Saudi Cup (G1)"],
                    ),
                )

    def test_result_page_date_cannot_disagree_with_url(self):
        r = route_for(
            "sporting_life",
            "united_kingdom",
            "united_kingdom",
            "Europe/London",
            "Southwell",
            ["Southwell"],
            "www.sportinglife.com",
            "/racing/",
        )
        with self.assertRaises(ValueError):
            adapters.parse_reference_observation(
                (FIX / "sl-gb.html").read_text(),
                url="https://www.sportinglife.com/racing/results/2026-10-09/southwell/942396/get-raceday-ready-handicap",
                route=r,
                now=NOW,
            )

    def test_german_card_excludes_history_rows_and_checks_header(self):
        from dataclasses import replace

        r = route("galopp_statistik")
        r = replace(
            r, payload={**r.payload, "allowed_path_prefixes": ["/RennenDetails.php"]}
        )
        url = "https://www.galopp-statistik.de/RennenDetails.php?Datum=2026-10-18&Nummer=4&Ort=Bad"
        page = (FIX / "de-card.html").read_text()
        value = adapters.parse_regional_observation(page, url=url, route=r, now=NOW)
        self.assertEqual(value["local_date"], "2026-10-18")
        self.assertEqual(value["race_number"], "4")
        self.assertEqual(len(value["roster"]), 13)
        self.assertEqual(value["roster"][0]["number"], "1")
        self.assertEqual(value["roster"][0]["barrier"], "12")
        self.assertEqual(value["result_phase"], "")
        self.assertEqual(value["declaration_status"], "unknown")
        with self.assertRaises(ValueError):
            adapters.parse_regional_observation(
                page, url=url.replace("Nummer=4", "Nummer=3"), route=r, now=NOW
            )

    def test_german_decode_only_ignores_invalid_bytes_inside_comments(self):
        from stable.services.race_regional_sources import decode_public_html

        raw = b"<html><!-- old \xff --><body>Rennen</body></html>"
        self.assertIn(
            "Rennen",
            decode_public_html(raw, encoding="utf-8", provider="galopp_statistik"),
        )
        with self.assertRaises(UnicodeDecodeError):
            decode_public_html(
                b"<html>\xff</html>", encoding="utf-8", provider="galopp_statistik"
            )
        with self.assertRaises(UnicodeDecodeError):
            decode_public_html(raw, encoding="utf-8", provider="jcsa")

    def test_german_card_link_joins_exact_full_result_without_inventing_numbers(self):
        from dataclasses import replace
        from unittest.mock import Mock, patch

        r = route("galopp_statistik")
        r = replace(
            r,
            payload={
                **r.payload,
                "allowed_path_prefixes": ["/RennenDetails.php", "/DisplayErgebnis.php"],
            },
        )
        url = "https://www.galopp-statistik.de/RennenDetails.php?Datum=2026-10-18&Nummer=4&Ort=Bad"
        source = SimpleNamespace(
            canonical_url=url, identity_fields={"multisource_v2": {}}
        )
        event = Mock()
        event.source_identities.filter.return_value.first.return_value = source
        event.runners.exists.return_value = False
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            return (
                FIX
                / (
                    "de-card.html"
                    if "/RennenDetails.php" in url
                    else "de-paired-result.html"
                )
            ).read_text()

        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ):
            value = adapters.fetch_bound_observation(
                event=event, route=r, now=NOW, fetcher=fetch
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(value["result_phase"], "official")
        self.assertTrue(value["roster_complete"])
        self.assertEqual(len(value["roster"]), 13)
        self.assertEqual(value["roster"][0]["number"], "3")
        self.assertEqual(value["roster"][-1]["number"], "7")
        self.assertEqual(value["roster"][-1]["status"], "withdrawn")
        self.assertIn("number", value["roster"][0]["field_provenance"])


class FurtherRegionTests(SimpleTestCase):
    def test_hong_kong_current_public_card_has_final_maturity_and_local_time(self):
        r = route_for(
            "hkjc",
            "hong_kong",
            "hong_kong",
            "Asia/Hong_Kong",
            "hkjc:ST",
            ["Sha Tin"],
            "racing.hkjc.com",
            "/en-us/local/information/",
        )
        url = "https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/10/28&Racecourse=ST&RaceNo=1"
        value = adapters.parse_hkjc_observation(
            (FIX / "hk-card.html").read_text(), url=url, route=r, now=NOW
        )
        self.assertEqual(value["external_race_id"], "HK20261028ST01")
        self.assertEqual(value["declaration_status"], "confirmed")
        self.assertEqual(value["off_time"], "2026-10-28T18:45:00+08:00")
        self.assertEqual(len(value["roster"]), 11)
        self.assertEqual(value["roster"][0]["barrier"], "10")
        self.assertEqual(value["roster"][0]["external_runner_id"], "HK_2025_L073")
        with self.assertRaises(ValueError):
            adapters.parse_hkjc_observation(
                (FIX / "hk-card.html").read_text(),
                url=url.replace("RaceNo=1", "RaceNo=2"),
                route=r,
                now=NOW,
            )

    def test_australia_acceptances_explicit_scratched_and_final_fields(self):
        r = route_for(
            "racing_australia",
            "australia",
            "australia",
            "Australia/Sydney",
            "ra:NSW:Kembla Grange",
            ["Kembla Grange"],
            "www.racingaustralia.horse",
            "/FreeFields/",
        )
        value = adapters.parse_regional_observation(
            (FIX / "au-card.html").read_text(),
            url="https://www.racingaustralia.horse/FreeFields/Acceptances.aspx?Key=2026Jul25,NSW,Kembla%20Grange",
            route=r,
            now=NOW,
            context={"race_number": "1"},
        )
        self.assertEqual(value["declaration_status"], "confirmed")
        self.assertTrue(value["roster_complete"])
        self.assertEqual(len(value["roster"]), 11)
        self.assertEqual(sum(r["status"] == "scratched" for r in value["roster"]), 4)
        self.assertEqual(value["off_time"], "2026-07-25T12:14:00+10:00")

    def test_us_full_result_is_not_replaced_by_payout_summary(self):
        r = route_for(
            "sporting_life",
            "united_states",
            "united_states",
            "America/New_York",
            "belmont",
            ["Belmont Park"],
            "www.sportinglife.com",
            "/racing/",
        )
        value = adapters.parse_reference_observation(
            (FIX / "sl-us.html").read_text(),
            url="https://www.sportinglife.com/racing/results/2026-09-18/belmont-park/939662/race-5-jockey-club-gold-cup-stakes-grade-1",
            route=r,
            now=NOW,
        )
        self.assertEqual(value["result_phase"], "official")
        self.assertEqual(len(value["roster"]), 7)
        self.assertEqual(sum(r["status"] == "withdrawn" for r in value["roster"]), 3)
        self.assertEqual(value["off_time"], "2026-09-18T20:14:00+00:00")

    def test_nar_real_final_card_and_title_provenance(self):
        r = route_for(
            "nar",
            "japan_nar",
            "japan",
            "Asia/Tokyo",
            "nar:22",
            ["金沢", "金 沢"],
            "www.keiba.go.jp",
            "/KeibaWeb/",
        )
        url = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11"
        value = adapters.parse_nar_observation(
            (FIX / "nar-card.html").read_text(), url=url, route=r, now=NOW
        )
        self.assertEqual(value["declaration_status"], "confirmed")
        self.assertIn("白山大賞典", value["raw_names"][0])
        self.assertEqual(len(value["roster"]), 12)
        self.assertTrue(value["roster"][0]["field_provenance"]["raw_sha256"])

    def test_era_official_full_page_and_public_ajax_card_have_shared_identity(self):
        from dataclasses import replace
        from unittest.mock import Mock, patch

        r = route("era")
        r = replace(
            r, payload={**r.payload, "allowed_path_prefixes": ["/racecard/", "/ajax/"]}
        )
        source = SimpleNamespace(
            canonical_url="https://emiratesracing.com/racecard/2026-03-28/9/declarations",
            identity_fields={"multisource_v2": {}},
        )
        event = Mock()
        event.source_identities.filter.return_value.first.return_value = source
        event.runners.exists.return_value = False
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            return (
                FIX / ("ae-page.html" if "/racecard/" in url else "ae-card.html")
            ).read_text()

        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ):
            value = adapters.fetch_bound_observation(
                event=event, route=r, now=NOW, fetcher=fetch, kind="racecard"
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(value["declaration_status"], "confirmed")
        self.assertEqual(len(value["roster"]), 9)
        self.assertEqual(value["off_time"], "2026-03-28T20:45:00+04:00")
        self.assertEqual(value["roster"][0]["number"], "1")

    def test_current_hong_kong_result_ignores_incident_table_and_calendar_options(self):
        r = route_for(
            "hkjc",
            "hong_kong",
            "hong_kong",
            "Asia/Hong_Kong",
            "hkjc:ST",
            ["Sha Tin"],
            "racing.hkjc.com",
            "/en-us/local/information/",
        )
        url = "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/10/25&Racecourse=ST&RaceNo=1"
        page = (FIX / "hk-result.html").read_text()
        value = adapters.parse_hkjc_observation(page, url=url, route=r, now=NOW)
        self.assertEqual(len(value["roster"]), 11)
        self.assertEqual(value["result_phase"], "official")
        with self.assertRaises(ValueError):
            adapters.parse_hkjc_observation(
                page, url=url.replace("2026/10/25", "2026/10/28"), route=r, now=NOW
            )

    def test_era_and_nar_results_follow_bound_pages_and_verify_independent_rosters(
        self,
    ):
        from dataclasses import replace
        from unittest.mock import Mock, patch

        era = route("era")
        era = replace(
            era,
            payload={**era.payload, "allowed_path_prefixes": ["/racecard/", "/ajax/"]},
        )
        nar = route_for(
            "nar",
            "japan_nar",
            "japan",
            "Asia/Tokyo",
            "nar:22",
            ["金沢", "金 沢"],
            "www.keiba.go.jp",
            "/KeibaWeb/",
        )
        for r, url, count, rows in [
            (
                era,
                "https://emiratesracing.com/racecard/2026-03-28/9/declarations",
                3,
                9,
            ),
            (
                nar,
                "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11",
                2,
                12,
            ),
        ]:
            with self.subTest(provider=r.provider):
                source = SimpleNamespace(
                    canonical_url=url, identity_fields={"multisource_v2": {}}
                )
                event = Mock()
                event.source_identities.filter.return_value.first.return_value = source
                event.runners.exists.return_value = False
                calls = []

                def fetch(target, **kwargs):
                    calls.append(target)
                    filename = (
                        (
                            "ae-page"
                            if "/racecard/" in target
                            else (
                                "ae-result"
                                if "racecard-results" in target
                                else "ae-card"
                            )
                        )
                        if r.provider == "era"
                        else ("nar-card" if "DebaTable" in target else "nar-result")
                    )
                    return (FIX / (filename + ".html")).read_text()

                with patch(
                    "stable.services.race_source_identity.seed_evidence",
                    return_value=None,
                ):
                    value = adapters.fetch_bound_observation(
                        event=event, route=r, now=NOW, fetcher=fetch
                    )
                self.assertEqual(len(calls), count)
                self.assertEqual(len(value["roster"]), rows)
                self.assertTrue(value["roster_complete"])
                self.assertEqual(value["result_phase"], "official")

    def test_france_structured_timestamp_uses_paris_local_race_date(self):
        r = route_for(
            "zeturf",
            "france",
            "france",
            "Europe/Paris",
            "chantilly",
            ["Chantilly"],
            "www.zeturf.fr",
            "/fr/course-du-jour/",
        )
        url = "https://www.zeturf.fr/fr/course-du-jour/2026-09-19/R1C3-chantilly-prix-eclipse"
        value = adapters.parse_reference_observation(
            (FIX / "zt-fr.html").read_text(), url=url, route=r, now=NOW
        )
        self.assertEqual(value["off_time"], "2026-09-19T12:37:00+00:00")

    def test_saudi_race_time_uses_fresh_public_page_and_rejects_wrong_day(self):
        from dataclasses import replace
        from unittest.mock import Mock, patch

        r = route("jcsa")
        r = replace(
            r,
            payload={
                **r.payload,
                "capabilities": ["race_time", "racecard"],
                "allowed_path_prefixes": ["/api/meeting-info/", "/en/races/"],
            },
        )
        source = SimpleNamespace(
            canonical_url="https://jcsa.sa/api/meeting-info/en/20260214/9/Declared/True",
            identity_fields={
                "multisource_v2": dict(
                    local_date="2026-02-14",
                    race_number="9",
                    venue_key="jcsa:riyadh",
                    raw_names=["Saudi Cup (G1)"],
                )
            },
        )
        event = Mock()
        event.source_identities.filter.return_value.first.return_value = source
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            return (
                FIX
                / ("sa-race-page.html" if "/en/races/" in url else "sa-declared.html")
            ).read_text()

        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ):
            value = adapters.fetch_bound_observation(
                event=event, route=r, now=NOW, fetcher=fetch, kind="racecard"
            )
        self.assertEqual(value["off_time"], "2026-02-14T20:40:00+03:00")
        self.assertEqual(len(calls), 2)
        from stable.services.race_regional_sources import enrich_jcsa_metadata

        with self.assertRaises(ValueError):
            enrich_jcsa_metadata(
                value,
                (FIX / "sa-race-page.html")
                .read_text()
                .replace("14th February", "15th February"),
                url=calls[-1],
                route=r,
            )

    def test_hong_kong_result_poll_moves_to_bound_result_and_rejects_other_day(self):
        from unittest.mock import Mock, patch

        r = route_for(
            "hkjc",
            "hong_kong",
            "hong_kong",
            "Asia/Hong_Kong",
            "hkjc:ST",
            ["Sha Tin"],
            "racing.hkjc.com",
            "/en-us/local/information/",
        )
        source = SimpleNamespace(
            canonical_url="https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/10/28&Racecourse=ST&RaceNo=1",
            identity_fields={"multisource_v2": {}},
        )
        event = Mock()
        event.source_identities.filter.return_value.first.return_value = source
        event.runners.exists.return_value = False
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            return (
                FIX / ("hk-result.html" if "/localresults?" in url else "hk-card.html")
            ).read_text()

        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ), self.assertRaises(ValueError):
            adapters.fetch_bound_observation(
                event=event, route=r, now=NOW, fetcher=fetch
            )
        self.assertEqual(len(calls), 2)
        self.assertIn("racedate=2026/10/28", calls[-1])


class NativeReviewRegressionTests(SimpleTestCase):
    def hk_fetch(self, *, roster=True, card=None):
        from unittest.mock import Mock, patch

        r = route_for(
            "hkjc",
            "hong_kong",
            "hong_kong",
            "Asia/Hong_Kong",
            "hkjc:ST",
            ["Sha Tin"],
            "racing.hkjc.com",
            "/en-us/local/information/",
        )
        url = "https://racing.hkjc.com/en-us/local/information/racecard?RaceDate=2026/10/25&Racecourse=ST&RaceNo=1"
        result_page = (FIX / "hk-result.html").read_text()
        result = adapters.parse_hkjc_observation(
            result_page,
            url=url.replace("/racecard?", "/localresults?"),
            route=r,
            now=NOW,
        )
        event = Mock()
        event.source_identities.filter.return_value.first.return_value = (
            SimpleNamespace(canonical_url=url, identity_fields={"multisource_v2": {}})
        )
        # 已入库名单为合成前置；No information 和结果页均为真实独立裁剪样本。
        event.runners.exists.return_value = roster
        event.runners.all.return_value = (
            [
                SimpleNamespace(horse_number=x["number"], horse_name=x["horse_name"])
                for x in result["roster"]
            ]
            if roster
            else []
        )
        calls = []

        def fetch(target, **kwargs):
            calls.append(target)
            return (
                result_page
                if "/localresults?" in target
                else (
                    card
                    if card is not None
                    else (FIX / "hk-card-unavailable.html").read_text()
                )
            )

        with patch(
            "stable.services.race_source_identity.seed_evidence", return_value=None
        ):
            value = adapters.fetch_bound_observation(
                event=event, route=r, now=NOW, fetcher=fetch
            )
        return value, calls

    def test_historical_hk_card_unavailable_uses_existing_roster(self):
        value, calls = self.hk_fetch()
        self.assertEqual(len(calls), 2)
        self.assertIn("RaceDate=2026/10/25", calls[-1])
        self.assertEqual(value["result_phase"], "official")
        self.assertTrue(value["roster_complete"])
        self.assertEqual(len(value["roster"]), 11)

    def test_historical_hk_card_unavailable_cannot_prove_missing_roster(self):
        value, _ = self.hk_fetch(roster=False)
        self.assertFalse(value["roster_complete"])
        self.assertNotIn("roster_evidence", value)

    def test_hk_card_identity_error_or_unrecognized_empty_response_is_not_fallback(
        self,
    ):
        for card in (
            (FIX / "hk-card.html").read_text(),
            "<html>temporary error</html>",
        ):
            with self.subTest(card=card[:30]), self.assertRaises(ValueError):
                self.hk_fetch(card=card)

    def us_page(self, date):
        soup = BeautifulSoup((FIX / "sl-us.html").read_text(), "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        data = json.loads(script.string)
        summary = data["props"]["pageProps"]["race"]["race_summary"]
        # 合成 UTC 午夜边界，基于既有 Sporting Life UTC 合同。
        summary.update(date=date, time="00:30")
        script.string = json.dumps(data)
        return str(soup)

    def us_parse(self, page):
        r = route_for(
            "sporting_life",
            "united_states",
            "united_states",
            "America/New_York",
            "Belmont Park",
            ["Belmont Park"],
            "www.sportinglife.com",
            "/racing/",
        )
        return adapters.parse_reference_observation(
            page,
            url="https://www.sportinglife.com/racing/results/2026-09-18/belmont-park/939662/race-5-jockey-club-gold-cup-stakes-grade-1",
            route=r,
            now=NOW,
        )

    def test_sporting_us_utc_next_day_is_same_local_meeting_day(self):
        value = self.us_parse(self.us_page("2026-09-19"))
        self.assertEqual(value["local_date"], "2026-09-18")
        self.assertEqual(value["off_time"], "2026-09-19T00:30:00+00:00")

    def test_sporting_us_matching_utc_date_cannot_hide_wrong_local_day(self):
        with self.assertRaisesRegex(ValueError, "sporting_date_mismatch"):
            self.us_parse(self.us_page("2026-09-18"))


class PairedResultGuardTests(SimpleTestCase):
    def australia(self, page, kind):
        r = route_for(
            "racing_australia",
            "australia",
            "australia",
            "Australia/Sydney",
            "ra:NSW:Kembla Grange",
            ["Kembla Grange"],
            "www.racingaustralia.horse",
            "/FreeFields/",
        )
        return adapters.parse_regional_observation(
            page,
            url=f"https://www.racingaustralia.horse/FreeFields/{kind}.aspx?Key=2026Jul25,NSW,Kembla%20Grange",
            route=r,
            now=NOW,
            context={"race_number": "1"},
        )

    def test_blank_finish_without_explicit_scratched_marker_is_unknown(self):
        soup = BeautifulSoup((FIX / "au-result.html").read_text(), "html.parser")
        tr = next(
            tr
            for tr in soup.select("table.race-strip-fields tr")
            if len(tr.find_all("td", recursive=False)) > 1
            and tr.find_all("td", recursive=False)[1].get_text(strip=True) == "7"
        )
        self.assertNotIn("Scratched", tr.get("class", []))
        tr.find_all("td", recursive=False)[1].string = ""
        with self.assertRaisesRegex(ValueError, "status"):
            self.australia(str(soup), "Results")

    def test_declared_scratch_cannot_be_joined_to_a_finished_horse(self):
        from stable.services.race_regional_sources import merge_numbered_rosters

        card = self.australia((FIX / "au-card.html").read_text(), "Acceptances")
        result = self.australia((FIX / "au-result.html").read_text(), "Results")
        winner = result["roster"][0]["external_runner_id"]
        next(r for r in card["roster"] if r["external_runner_id"] == winner)[
            "status"
        ] = "scratched"
        with self.assertRaisesRegex(ValueError, "status_conflict"):
            merge_numbered_rosters(result, card)
