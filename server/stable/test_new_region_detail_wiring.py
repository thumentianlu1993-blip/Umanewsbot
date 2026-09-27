"""新四地区详情 provider 接线契约测试。

覆盖阶段 2-B 接线：
- REGION_SOURCES / PROVIDER_ALIASES / DEFAULT_SOURCE_NAMES / SOURCE_PROVIDERS 注册
- _provider_for_request 的地区限定（含 ireland 原始 irishracing 归属修复）
- _parse_cached_request 六个新 provider 的真实 fixture 分派解析
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_new_region_wiring_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class AdapterSpecRegistrationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.adapters = _load("historical_race_detail_adapters.py")

    def test_new_region_adapter_specs_cover_all_stages(self):
        expectations = {
            "australia": {"racing_australia", "just_horse_racing"},
            "germany": {"deutscher_galopp"},
            "middle_east": {"era", "jcsa"},
            "ireland": {"irishracing", "hri_ras"},
        }
        for region, sources in expectations.items():
            for stage in ("discover", "cache", "parse", "validate", "package"):
                with self.subTest(region=region, stage=stage):
                    spec = self.adapters.get_adapter_spec(region, stage)
                    self.assertEqual(spec["region"], region)
                    self.assertEqual(spec["stage"], stage)
                    self.assertEqual(set(spec["sources"]), sources)

    def test_existing_region_specs_unchanged(self):
        self.assertEqual(
            set(self.adapters.get_adapter_spec("japan", "parse")["sources"]),
            {"jra", "netkeiba"},
        )
        self.assertEqual(
            set(self.adapters.get_adapter_spec("united_kingdom", "discover")["sources"]),
            {"racing_post", "sporting_life", "irishracing"},
        )


class ProviderRegistryTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.adapters = _load("historical_race_detail_adapters.py")
        cls.packager = _load("package_historical_race_detail_candidates.py")

    def test_provider_aliases_registered(self):
        for provider in (
            "deutscher_galopp",
            "hri_ras",
            "racing_australia",
            "just_horse_racing",
            "era",
            "jcsa",
            "ireland_irishracing",
        ):
            with self.subTest(provider=provider):
                self.assertIn(provider, self.adapters.PROVIDER_ALIASES)
                self.assertIn(provider, self.adapters.DEFAULT_SOURCE_NAMES)
                self.assertIn(provider, self.adapters.supported_parse_providers())

    def test_default_source_names(self):
        self.assertEqual(
            self.adapters.DEFAULT_SOURCE_NAMES["deutscher_galopp"], "deutscher_galopp_result"
        )
        self.assertEqual(self.adapters.DEFAULT_SOURCE_NAMES["hri_ras"], "hri_ras_result")
        self.assertEqual(
            self.adapters.DEFAULT_SOURCE_NAMES["racing_australia"], "racing_australia_results"
        )
        self.assertEqual(
            self.adapters.DEFAULT_SOURCE_NAMES["just_horse_racing"], "just_horse_racing_results"
        )
        self.assertEqual(self.adapters.DEFAULT_SOURCE_NAMES["era"], "era_racecard_results")
        self.assertEqual(self.adapters.DEFAULT_SOURCE_NAMES["jcsa"], "jcsa_meeting_results")

    def test_package_source_providers_registered(self):
        expectations = {
            "deutscher_galopp_result": "deutscher_galopp",
            "hri_ras_result": "hri_ras",
            "racing_australia_results": "racing_australia",
            "just_horse_racing_results": "just_horse_racing",
            "era_racecard_results": "era",
            "jcsa_meeting_results": "jcsa",
            "ireland_irishracing": "ireland_irishracing",
        }
        for source_name, provider in expectations.items():
            with self.subTest(source_name=source_name):
                self.assertEqual(self.packager.SOURCE_PROVIDERS.get(source_name), provider)


class ProviderForRequestTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.adapters = _load("historical_race_detail_adapters.py")

    def test_ireland_raw_irishracing_maps_to_ireland_provider(self):
        provider = self.adapters._provider_for_request(
            {"source_provider": "irishracing"}, region="ireland"
        )
        self.assertEqual(provider, "ireland_irishracing")

    def test_existing_irishracing_region_mapping_unchanged(self):
        self.assertEqual(
            self.adapters._provider_for_request({"source_provider": "irishracing"}, region="united_kingdom"),
            "uk_irishracing",
        )
        self.assertEqual(
            self.adapters._provider_for_request({"source_provider": "irishracing"}, region="france"),
            "france_irishracing",
        )

    def test_new_providers_pass_through(self):
        for provider in (
            "deutscher_galopp",
            "hri_ras",
            "racing_australia",
            "just_horse_racing",
            "era",
            "jcsa",
            "ireland_irishracing",
        ):
            with self.subTest(provider=provider):
                self.assertEqual(
                    self.adapters._provider_for_request(
                        {"source_provider": provider},
                        region="middle_east" if provider in {"era", "jcsa"} else "germany",
                    ),
                    provider,
                )

    def test_unknown_provider_rejected(self):
        with self.assertRaises(self.adapters.DetailAdapterError):
            self.adapters._provider_for_request(
                {"source_provider": "attacker_source"}, region="germany"
            )


class ParseDispatchTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.adapters = _load("historical_race_detail_adapters.py")

    def _dispatch(self, *, provider, source_url, fixture, region, race_number=None):
        request = {"source_provider": provider, "source_url": source_url}
        if race_number is not None:
            request["race_number"] = race_number
        event = {
            "year": "2025",
            "slug": "fixture-race-2025",
            "original_name": "fixture race",
            "racecourse": "",
            "local_date": "",
        }
        return self.adapters._parse_cached_request(
            request,
            event=event,
            region=region,
            source_path=FIXTURES / fixture,
        )

    def test_deutscher_galopp_dispatch(self):
        runners, results, metadata, source_name = self._dispatch(
            provider="deutscher_galopp",
            source_url="https://www.deutscher-galopp.de/gr/renntage/rennen.php?id=1356402&d=20250907&s=R",
            fixture="deutscher_galopp/dg_20250907_baden-baden_r8_gpb.html",
            region="germany",
        )
        self.assertEqual(source_name, "deutscher_galopp_result")
        self.assertEqual(len(runners), 8)
        self.assertEqual(len(results), 6)
        self.assertEqual(results[0]["horse_name"], "Goliath")
        self.assertEqual(results[0]["jockey_name"], "Clement Lecoeuvre")
        self.assertEqual(metadata["race_time"], "2:29,02")

    def test_hri_ras_dispatch(self):
        runners, results, metadata, source_name = self._dispatch(
            provider="hri_ras",
            source_url="https://www.hri-ras.ie/results/race-result/?date=2025-06-29&race=1610&venue=CU",
            fixture="hri/hri_result_2025-06-29_curragh_r1610_irish_derby.html",
            region="ireland",
        )
        self.assertEqual(source_name, "hri_ras_result")
        self.assertEqual(len(runners), 10)
        self.assertEqual(len(results), 10)
        self.assertEqual(results[0]["horse_name"], "Lambourn")
        self.assertEqual(results[0]["jockey_name"], "R.L. Moore")

    def test_racing_australia_dispatch_with_race_number(self):
        runners, results, metadata, source_name = self._dispatch(
            provider="racing_australia",
            source_url="https://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct25,VIC,The%20Valley",
            fixture="australia/ra_results_2025-10-25_thevalley.html",
            region="australia",
            race_number="10",
        )
        self.assertEqual(source_name, "racing_australia_results")
        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 8)
        self.assertEqual(results[0]["horse_name"], "VIA SISTINA")
        self.assertEqual(results[0]["trainer_name"], "Chris Waller")

    def test_just_horse_racing_dispatch(self):
        runners, results, metadata, source_name = self._dispatch(
            provider="just_horse_racing",
            source_url="https://justhorseracing.com.au/fields-results/results/cox-plate-results-2025/868422",
            fixture="australia/justhorseracing_cox_plate_2025_results.html",
            region="australia",
        )
        self.assertEqual(source_name, "just_horse_racing_results")
        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 8)
        self.assertEqual(results[0]["horse_name"], "VIA SISTINA")

    def test_era_dispatch_with_race_number(self):
        runners, results, metadata, source_name = self._dispatch(
            provider="era",
            source_url="https://emiratesracing.com/ajax/racecard-results?date=2026-03-28&race=9",
            fixture="middle_east/era_ajax_racecard-results_2026-03-28_r9.html",
            region="middle_east",
            race_number="9",
        )
        self.assertEqual(source_name, "era_racecard_results")
        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 9)
        self.assertEqual(results[0]["horse_name"], "MAGNITUDE")
        self.assertEqual(results[1]["horse_name"], "FOREVER YOUNG")

    def test_era_dispatch_without_race_number_fails_closed(self):
        with self.assertRaises(self.adapters.DetailAdapterError):
            self._dispatch(
                provider="era",
                source_url="https://emiratesracing.com/ajax/racecard-results?date=2026-03-28&race=9",
                fixture="middle_east/era_ajax_racecard-results_2026-03-28_r9.html",
                region="middle_east",
            )

    def test_jcsa_dispatch(self):
        runners, results, metadata, source_name = self._dispatch(
            provider="jcsa",
            source_url="https://jcsa.sa/api/meeting-info/en/20260214/9/Results/True",
            fixture="middle_east/jcsa_api_meeting-info_en_20260214_9_Results_True.html",
            region="middle_east",
        )
        self.assertEqual(source_name, "jcsa_meeting_results")
        self.assertEqual(len(runners), 14)
        self.assertEqual(len(results), 13)
        self.assertEqual(results[0]["horse_name"], "Forever Young")
        self.assertEqual(results[0]["jockey_name"], "Ryusei Sakai")
        self.assertEqual(results[0]["odds_value"], "")

    def test_ireland_irishracing_dispatch_routes_to_irishracing_parser(self):
        runner = {"horse_number": "1", "horse_name": "Fixture Horse", "sort_order": 1}
        result = {**runner, "finish_position": 1}
        with patch.object(
            self.adapters, "parse_irishracing_detail", return_value=([runner], [result], {})
        ) as parser:
            self._dispatch(
                provider="ireland_irishracing",
                source_url="https://www.irishracing.com/raceresults/Sun-29th-Jun-2025/Curragh/1610",
                fixture="hri/hri_result_2025-06-29_curragh_r1610_irish_derby.html",
                region="ireland",
            )
        parser.assert_called_once()
