from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime/tools/discover_historical_race_band_sources.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("historical_race_band_source_discovery", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HistoricalRaceSourceDiscoveryToolTests(SimpleTestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_distance_evidence_adds_explicit_uk_units_and_expands_compact_notation(self):
        cases = {
            "12": "12f",
            "2.5": "2.5m",
            "1m71/2f": "1m 7 1/2f",
            "3m1/2f": "3m 1/2f",
            "2m4f": "2m 4f",
            "3m149y": "3m 149y",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    self.tool._distance_with_unit(
                        {"distance_text": raw, "country_region": "united_kingdom"}
                    ),
                    expected,
                )

    def test_distance_matching_parses_compact_half_furlongs_without_tenfold_error(self):
        cases = {
            "1m71/2f": 1760 + (7.5 * 220),
            "3m1/2f": (3 * 1760) + (0.5 * 220),
            "2m4f": (2 * 1760) + (4 * 220),
        }

        for raw, expected_yards in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    self.tool._distance_measurement(raw, "united_kingdom"),
                    ("imperial", expected_yards),
                )

    def test_jra_schedule_maps_english_name_to_official_static_result(self):
        schedule = b"""
        <ul><li id="Jan"><table>
          <tr><th colspan="7"><div><span>Jan. 26</span><a>AMERICAN JOCKEY CLUB CUP</a></div></th></tr>
          <tr><td>G2</td><td>NAKAYAMA</td><td>2,200/Turf</td><td>4yo&amp;up</td><td>62000000</td>
              <td><a href="javascript:doSubmit('2025','0126','06','01','09','11','7')">o</a></td></tr>
          <tr><th colspan="7"><div><span>Mar. 23</span><a>AICHI HAI</a></div></th></tr>
          <tr><td>G3</td><td>CHUKYO</td><td>1,400/Turf</td><td>4yo&amp;up</td><td>38000000</td>
              <td><a href="javascript:doSubmit('2025','0323','07','02','04','11','7')">o</a></td></tr>
        </table></li></ul>
        """
        history = """
        <table><tr><th>月日</th><th>レース名</th><th>競馬場</th><th>結果</th></tr>
          <tr><td>1月26日 日曜</td><td>AJCC</td><td>中山</td><td><a href="/datafile/seiseki/replay/2025/010.html">result</a></td></tr>
          <tr><td>3月23日 日曜</td><td>愛知杯</td><td>中京</td><td><a href="/datafile/seiseki/replay/2025/033.html">result</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": "japan-aichi-hai",
                "year": 2025,
                "country_region": "japan",
                "original_name": "Aichi Hai",
                "racecourse": "Chukyo",
                "distance_text": "1400m",
            }
        ]

        result = self.tool.build_jra_provider_rows(
            targets=targets,
            year=2025,
            english_schedule_body=schedule,
            history_body=history.encode("cp932"),
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            result["rows"],
            [
                {
                    "adapter_key": "jra",
                    "series_key": "japan-aichi-hai",
                    "edition_year": 2025,
                    "local_date": "2025-03-23",
                    "distance_text": "1400m",
                    "urls": {
                        "result_url": {
                            "url": "https://www.jra.go.jp/datafile/seiseki/replay/2025/033.html",
                            "source_provider": "jra",
                            "source_authority": "official",
                            "redirect_chain": [],
                        }
                    },
                }
            ],
        )

    def test_jra_alignment_mismatch_fails_closed(self):
        result = self.tool.build_jra_provider_rows(
                targets=[{
                    "series_key": "japan-race",
                    "year": 2025,
                    "country_region": "japan",
                    "original_name": "Race",
                    "racecourse": "Track",
                    "distance_text": "1000m",
                }],
                year=2025,
                english_schedule_body=b"""
                <table><tr><th colspan='7'><span>Jan. 1</span><a>RACE</a></th></tr>
                <tr><td>G1</td><td>TRACK</td><td>1000/Turf</td><td></td><td></td>
                <td><a href=\"javascript:doSubmit('2025','0101','01','01','01','11','7')\">o</a></td></tr></table>
                """,
                history_body=b"",
            )
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["issues"][0]["code"], "source_result_not_unique")

    def test_jra_official_aliases_cover_2025_jump_and_sponsored_names(self):
        history = """
        <table><tr><th>月日</th><th>レース名</th><th>競馬場</th><th>結果</th></tr>
          <tr><td>2月15日 土曜</td><td>J・GⅢ 小倉ジャンプS</td><td>小倉</td><td><a href="/datafile/seiseki/replay/2025/015.html">result</a></td></tr>
          <tr><td>3月8日 土曜</td><td>GⅢ 中山牝馬S</td><td>中山</td><td><a href="/datafile/seiseki/replay/2025/024.html">result</a></td></tr>
          <tr><td>5月17日 土曜</td><td>J・GⅡ 京都ハイジャンプ</td><td>京都</td><td><a href="/datafile/seiseki/replay/2025/050.html">result</a></td></tr>
          <tr><td>8月16日 土曜</td><td>J・GⅢ 新潟ジャンプS</td><td>新潟</td><td><a href="/datafile/seiseki/replay/2025/072.html">result</a></td></tr>
          <tr><td>11月8日 土曜</td><td>J・GⅢ 京都ジャンプS</td><td>京都</td><td><a href="/datafile/seiseki/replay/2025/100.html">result</a></td></tr>
        </table>
        """
        expected = {
            "japan-kokura-jump": ("Kokura Jump S", "Kokura", "2025-02-15"),
            "japan-laurel-racecourse-sho-nakayama-himba": (
                "Laurel Racecourse Sho Nakayama Himba S",
                "Nakayama",
                "2025-03-08",
            ),
            "japan-kyoto-high-jump": ("Kyoto High-Jump", "Kyoto", "2025-05-17"),
            "japan-niigata-jump": ("Niigata Jump S", "Niigata", "2025-08-16"),
            "japan-kyoto-jump": ("Kyoto Jump S", "Kyoto", "2025-11-08"),
        }
        targets = [
            {
                "series_key": series_key,
                "year": 2025,
                "country_region": "japan",
                "original_name": original_name,
                "racecourse": racecourse,
                "distance_text": "3000m",
            }
            for series_key, (original_name, racecourse, _local_date) in expected.items()
        ]

        result = self.tool.build_jra_provider_rows(
            targets=targets,
            year=2025,
            english_schedule_body=b"",
            history_body=history.encode("cp932"),
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["series_key"]: row["local_date"] for row in result["rows"]},
            {series_key: values[2] for series_key, values in expected.items()},
        )

    def test_toba_same_name_is_disambiguated_by_track(self):
        body = """
        <table><tr><th>Stake</th><th>Gr</th><th>Track</th><th>Winner</th></tr>
          <tr><td>BAYAKOA S.</td><td>3</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=8&amp;BorP=P&amp;TID=DMR&amp;CTRY=USA&amp;DT=12/13/2025&amp;DAY=D&amp;STYLE=EQB">Alpha</a></td></tr>
          <tr><td>BAYAKOA S.</td><td>3</td><td>OP</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;BorP=P&amp;TID=OP&amp;CTRY=USA&amp;DT=2/8/2025&amp;DAY=D&amp;STYLE=EQB">Beta</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": "USA_CALIFORNIA_BAYAKOA_STAKES",
                "year": 2025,
                "country_region": "united_states",
                "original_name": "Bayakoa S",
                "racecourse": "Del Mar",
                "distance_text": "8.5",
            },
            {
                "series_key": "USA_OAKLAWN_BAYAKOA_STAKES",
                "year": 2025,
                "country_region": "united_states",
                "original_name": "Bayakoa S",
                "racecourse": "Oaklawn Park",
                "distance_text": "8.5f",
            },
        ]

        result = self.tool.build_toba_provider_rows(targets=targets, year=2025, body=body)

        self.assertEqual(result["issues"], [])
        self.assertEqual([row["local_date"] for row in result["rows"]], ["2025-12-13", "2025-02-08"])
        self.assertEqual(result["rows"][0]["distance_text"], "8.5f")
        self.assertEqual(
            [row["urls"]["result_url"]["url"] for row in result["rows"]],
            [
                "https://www.equibase.com/yearbook/Result.cfm?cy=USA&de=D&rd=2025-12-13&rn=8&tk=DMR",
                "https://www.equibase.com/yearbook/Result.cfm?cy=USA&de=D&rd=2025-02-08&rn=9&tk=OP",
            ],
        )

    def test_toba_ambiguous_or_missing_track_is_reported_without_guessing(self):
        body = """
        <table><tr><th>Stake</th><th>Gr</th><th>Track</th><th>Winner</th></tr>
          <tr><td>BAYAKOA S.</td><td>3</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=8&amp;TID=DMR&amp;DT=12/13/2025">Alpha</a></td></tr>
          <tr><td>BAYAKOA S.</td><td>3</td><td>OP</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=OP&amp;DT=2/8/2025">Beta</a></td></tr>
        </table>
        """
        target = {
            "series_key": "united-states-bayakoa",
            "year": 2025,
            "country_region": "united_states",
            "original_name": "Bayakoa S",
            "racecourse": "Unknown",
            "distance_text": "8.5f",
        }

        result = self.tool.build_toba_provider_rows(targets=[target], year=2025, body=body)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["issues"][0]["code"], "source_match_not_unique")

    def test_toba_not_run_row_is_reported_as_explicit_review_evidence(self):
        body = """
        <table><tr><th>Track</th><th>Date</th><th>Stake</th><th>Winner</th></tr>
          <tr><td>BAQ</td><td>not run</td><td>BROOKLYN S.</td><td></td></tr>
        </table>
        """
        target = {
            "series_key": "united-states-brooklyn",
            "year": 2025,
            "country_region": "united_states",
            "original_name": "Brooklyn S",
            "racecourse": "Belmont at Aqueduct",
            "distance_text": "11",
        }

        result = self.tool.build_toba_provider_rows(targets=[target], year=2025, body=body)

        self.assertEqual(result["rows"], [])
        self.assertEqual(
            result["issues"],
            [
                {
                    "series_key": "united-states-brooklyn",
                    "edition_year": 2025,
                    "code": "source_reports_not_run",
                    "source_name": "BROOKLYN S.",
                    "source_track": "BAQ",
                    "source_status": "not run",
                }
            ],
        )

    def test_toba_accepts_unique_name_when_annual_race_was_relocated(self):
        body = """
        <table><tr><th>Stake</th><th>Gr</th><th>Track</th><th>Winner</th></tr>
          <tr><td>BELMONT DERBY INVITATIONAL S.</td><td>1</td><td>SAR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=SAR&amp;DT=7/4/2025">Alpha</a></td></tr>
        </table>
        """
        target = {
            "series_key": "united-states-belmont-derby-invitational",
            "year": 2025,
            "country_region": "united_states",
            "original_name": "Belmont Derby Invitational S",
            "racecourse": "Belmont at Aqueduct",
            "distance_text": "9f",
        }

        result = self.tool.build_toba_provider_rows(targets=[target], year=2025, body=body)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["rows"][0]["local_date"], "2025-07-04")

    def test_toba_core_name_qualifiers_disambiguate_breeders_cup_juvenile(self):
        body = """
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
          <tr><td>FANDUEL BREEDERS' CUP JUVENILE PRESENTED BY THOROUGHBRED AFTERCARE ALLIANCE</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=DMR&amp;DT=10/31/2025">Alpha</a></td></tr>
          <tr><td>BREEDERS' CUP JUVENILE TURF</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=10&amp;TID=DMR&amp;DT=10/31/2025">Beta</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": "united-states-breeders-cup-juvenile",
                "year": 2025,
                "country_region": "united_states",
                "original_name": "Breeders' Cup Juvenile [FanDuel]",
                "racecourse": "Del Mar",
                "distance_text": "8.5",
            },
            {
                "series_key": "united-states-breeders-cup-juvenile-turf",
                "year": 2025,
                "country_region": "united_states",
                "original_name": "Breeders' Cup Juvenile Turf",
                "racecourse": "Del Mar",
                "distance_text": "8",
            },
        ]

        result = self.tool.build_toba_provider_rows(targets=targets, year=2025, body=body)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            [row["urls"]["result_url"]["url"] for row in result["rows"]],
            [
                "https://www.equibase.com/yearbook/Result.cfm?cy=USA&de=D&rd=2025-10-31&rn=9&tk=DMR",
                "https://www.equibase.com/yearbook/Result.cfm?cy=USA&de=D&rd=2025-10-31&rn=10&tk=DMR",
            ],
        )

    def test_toba_duplicate_result_url_fails_closed_for_both_targets(self):
        body = """
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
          <tr><td>ALPHA S.</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=DMR&amp;DT=10/31/2025">Alpha</a></td></tr>
          <tr><td>BETA S.</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=DMR&amp;DT=10/31/2025">Beta</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": f"united-states-{name.lower()}",
                "year": 2025,
                "country_region": "united_states",
                "original_name": f"{name} S",
                "racecourse": "Del Mar",
                "distance_text": "8",
            }
            for name in ("Alpha", "Beta")
        ]

        result = self.tool.build_toba_provider_rows(targets=targets, year=2025, body=body)

        self.assertEqual(result["rows"], [])
        self.assertEqual(
            [issue["code"] for issue in result["issues"]],
            ["duplicate_source_url", "duplicate_source_url"],
        )

    def test_toba_core_qualifiers_do_not_match_substrings_in_sponsor_names(self):
        body = """
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
          <tr><td>TURFWAY ALPHA S.</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=DMR&amp;DT=10/31/2025">Alpha</a></td></tr>
        </table>
        """
        target = {
            "series_key": "united-states-alpha",
            "year": 2025,
            "country_region": "united_states",
            "original_name": "Alpha S",
            "racecourse": "Del Mar",
            "distance_text": "8",
        }

        result = self.tool.build_toba_provider_rows(targets=[target], year=2025, body=body)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["rows"][0]["series_key"], "united-states-alpha")

    def test_hkjc_pattern_book_schedule_preserves_cross_calendar_season_dates(self):
        text = """
        22/09/24 Celebration Cup G3 4,200,000 3yo+ 1400 26/08/24 16/09/24 N/A N/A 10
        01/01/25 Bauhinia Sprint Trophy G3 4,200,000 3yo+ 1000 02/12/24 27/12/24 N/A N/A 23
        APR 27/04/25 FWD Champions Mile G1 24,000,000 3yo+ 1600 17/03/25 17/03/25 07/04/25 07/04/25 33
        """

        rows = self.tool.parse_hkjc_pattern_schedule_text(text, edition_year=2025)

        self.assertEqual(
            [(row["local_date"], row["race_name"], row["distance_text"]) for row in rows],
            [
                ("2024-09-22", "Celebration Cup", "1400m"),
                ("2025-01-01", "Bauhinia Sprint Trophy", "1000m"),
                ("2025-04-27", "FWD Champions Mile", "1600m"),
            ],
        )
        self.assertEqual({row["edition_year"] for row in rows}, {2025})

    def test_hkjc_pattern_book_excludes_prior_season_history_rows(self):
        text = """
        23/01/22 Centenary Sprint Cup G1 12,000,000 3yo+ 1200 01/12/21 17/01/22 N/A N/A 21
        24/01/21 Centenary Sprint Cup G1 12,000,000 3yo+ 1200 01/12/20 18/01/21 N/A N/A 21
        """

        rows = self.tool.parse_hkjc_pattern_schedule_text(text, edition_year=2022)

        self.assertEqual([row["local_date"] for row in rows], ["2022-01-23"])

    def test_hkjc_pattern_book_assigns_january_cup_to_happy_valley(self):
        rows = self.tool.parse_hkjc_pattern_schedule_text(
            "08/01/25 January Cup G3 4,200,000 3yo+ 1800 09/12/24 02/01/25 N/A N/A 24",
            edition_year=2025,
        )

        self.assertEqual(rows[0]["racecourse"], "Happy Valley")

    def test_hkjc_pattern_book_assigns_parenthesized_january_cup_to_happy_valley(self):
        rows = self.tool.parse_hkjc_pattern_schedule_text(
            "11/01/23 January Cup (H) G3 3,900,000 3yo+ 1800 12/12/22 05/01/23 N/A N/A 24",
            edition_year=2023,
        )

        self.assertEqual(rows[0]["racecourse"], "Happy Valley")

    def test_hkjc_pattern_book_accepts_non_three_year_old_age_conditions(self):
        rows = self.tool.parse_hkjc_pattern_schedule_text(
            "\n".join(
                [
                    "19/01/25 Centenary Sprint Cup G1 13,000,000 4yo+ 1200 09/12/24 13/01/25 N/A N/A 21",
                    "28/09/24 Juvenile Sprint G3 4,200,000 2yo 1000 01/09/24 20/09/24 N/A N/A 3",
                ]
            ),
            edition_year=2025,
        )

        self.assertEqual(
            [(row["race_name"], row["distance_text"]) for row in rows],
            [("Centenary Sprint Cup", "1200m"), ("Juvenile Sprint", "1000m")],
        )

    def test_hkjc_results_all_parser_extracts_direct_race_identity(self):
        html = """
        <div class="race_result">
          <div class="f_fs13 margin_top15">
            <div class="bg_blue color_w f_fs13 font_wb">Race 7</div>
            <div>Group Three - 1400M - TURF - &quot;B+2&quot; Course - THE CELEBRATION CUP (HANDICAP)</div>
            <table class="result"><tr><td>fixture</td></tr></table>
          </div>
        </div>
        """

        rows = self.tool.parse_hkjc_results_all_schedule(html)

        self.assertEqual(
            rows,
            [{
                "race_no": "7",
                "race_name": "THE CELEBRATION CUP (HANDICAP)",
                "normalized_grade": "G3",
                "distance_text": "1400m",
            }],
        )

    def test_hkjc_result_url_resolver_is_one_to_one(self):
        matches = [
            {
                "target_id": 19,
                "series_key": "hong-kong-celebration-cup",
                "edition_year": 2025,
                "local_date": "2024-09-22",
                "racecourse": "Sha Tin",
                "race_name": "Celebration Cup",
                "normalized_grade": "G3",
                "distance_text": "1400m",
            },
            {
                "target_id": 20,
                "series_key": "hong-kong-national-day-cup",
                "edition_year": 2025,
                "local_date": "2024-10-01",
                "racecourse": "Sha Tin",
                "race_name": "National Day Cup",
                "normalized_grade": "G3",
                "distance_text": "1000m",
            },
        ]
        result_pages = {
            ("2024-09-22", "ST"): [{
                "race_no": "7",
                "race_name": "THE CELEBRATION CUP (HANDICAP)",
                "normalized_grade": "G3",
                "distance_text": "1400m",
            }],
            ("2024-10-01", "ST"): [{
                "race_no": "8",
                "race_name": "THE NATIONAL DAY CUP (HANDICAP)",
                "normalized_grade": "G3",
                "distance_text": "1000m",
            }],
        }

        result = self.tool.resolve_hkjc_result_urls(matches, result_pages)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            [row["source_url"] for row in result["matches"]],
            [
                "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2024/09/22&Racecourse=ST&RaceNo=7",
                "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2024/10/01&Racecourse=ST&RaceNo=8",
            ],
        )

    def test_bha_flat_book_uses_race_date_not_closing_date(self):
        text = """
        Apr. 8 EPSOMDOWNS June 6 CORONATIONCUP(P1.C.F.) 12F+ 4+ 68
        ” 12 NEWBURY May 17 SKYSPORTSRACINGASTONPARK(P3.) 12F 4+ 58
        July 1 GOODWOOD Aug. 24 WILLIAMHILLCELEBRATIONMILE(P2.) 8F 3+ 125
        """

        rows = self.tool.parse_bha_flat_schedule_text(text, year=2025)

        self.assertEqual(
            [(row["local_date"], row["racecourse"], row["race_name"]) for row in rows],
            [
                ("2025-06-06", "Epsom Downs", "CORONATION CUP"),
                ("2025-05-17", "Newbury", "SKY SPORTS RACING ASTON PARK"),
                ("2025-08-24", "Goodwood", "WILLIAM HILL CELEBRATION MILE"),
            ],
        )

    def test_bha_flat_book_supports_all_batch_002_racecourses(self):
        text = """
        ” 5 DONCASTER Sept. 13 BETFREDCHAMPAGNE(P2.C.G.) 7F+ 2CG 136
        ” 5 LINGFIELDPARK May 10 BETFREDCHARTWELL(P3.F.) 7F+ 3+F 50
        ” 5 CHESTER May 7 BoodlesChesterVase(P3.C.G.) 12F+ 3CG 43
        ” 5 NEWCASTLE June 28 PertempsNetworkChipchase(P3.) 6F 3+ 85
        ” 5 SALISBURY Sept. 4 IRE-IncentiveDickPoole(P3.F.) 6F 2F 132
        """

        rows = self.tool.parse_bha_flat_schedule_text(text, year=2025)

        self.assertEqual(
            [(row["local_date"], row["racecourse"]) for row in rows],
            [
                ("2025-09-13", "Doncaster"),
                ("2025-05-10", "Lingfield"),
                ("2025-05-07", "Chester"),
                ("2025-06-28", "Newcastle"),
                ("2025-09-04", "Salisbury"),
            ],
        )

    def test_bha_flat_book_joins_wrapped_race_names(self):
        text = """
        ” 5 LINGFIELDPARK May 10 IRE-INCENTIVE,ITPAYSTOBUYIRISH
                         CHARTWELL(P3.F.) 7F 3+F 52
        ” 23 NEWCASTLE June 28 JENNINGSBETNUNSTREETNEWCASTLE
                         OPENNOWCHIPCHASE(P3.) 6F 3+ 87
        ” 29 SALISBURY Sept. 4 IRE-INCENTIVE,ITPAYSTOBUYIRISH
                         DICKPOOLE(P3.F.) 6F 2F 129
        ” 4 NEWMARKET Oct. 10 NEWMARKETACADEMYGODOLPHIN
                         BEACONPROJECTCORNWALLIS(P3.) 5F 2 154
        """

        rows = self.tool.parse_bha_flat_schedule_text(text, year=2025)

        self.assertEqual(
            [(row["racecourse"], row["race_name"]) for row in rows],
            [
                ("Lingfield", "IRE-INCENTIVE,ITPAYSTOBUYIRISHCHARTWELL"),
                ("Newcastle", "JENNINGSBETNUNSTREETNEWCASTLEOPENNOWCHIPCHASE"),
                ("Salisbury", "IRE-INCENTIVE,ITPAYSTOBUYIRISHDICKPOOLE"),
                ("Newmarket", "NEWMARKETACADEMYGODOLPHINBEACONPROJECTCORNWALLIS"),
            ],
        )

    def test_bha_jump_book_resolves_season_year_boundary(self):
        text = """
        Nov. 2 Ascot SodexoLive!GoldCupH’Cap 4+ Prem 27
        Mar.11 Cheltenham UltimaH’Cap(3m1f) 5+ Prem 93
        Apr.26 SandownPark Bet365Celebration(1m71/2f) 5+ 1 118
        """

        rows = self.tool.parse_bha_jump_schedule_text(text, season_start_year=2024)

        self.assertEqual(
            [(row["local_date"], row["racecourse"], row["race_name"]) for row in rows],
            [
                ("2024-11-02", "Ascot", "SODEXO LIVE GOLD CUP HANDICAP"),
                ("2025-03-11", "Cheltenham", "ULTIMA HANDICAP"),
                ("2025-04-26", "Sandown Park", "BET365 CELEBRATION"),
            ],
        )

    def test_bha_jump_book_keeps_distance_from_detail_rows(self):
        rows = self.tool.parse_bha_jump_schedule_text(
            "\n".join(
                [
                    "Apr. 4 Aintree WilliamHillH’CapHurdle 2m4f Prem 75,000",
                    "Apr. 5 Aintree WilliamHillH’CapHurdle 3m1/2f Prem 75,000",
                ]
            ),
            season_start_year=2024,
        )

        self.assertEqual(
            [(row["local_date"], row["distance_text"]) for row in rows],
            [("2025-04-04", "2m4f"), ("2025-04-05", "3m1/2f")],
        )

    def test_bha_jump_book_supports_warwick(self):
        rows = self.tool.parse_bha_jump_schedule_text(
            "Jan.11 Warwick WigleyGroupClassicH'CapChase 3m5f Prem 100,000",
            season_start_year=2024,
        )

        self.assertEqual(rows[0]["local_date"], "2025-01-11")
        self.assertEqual(rows[0]["racecourse"], "Warwick")

    def test_bha_jump_detail_distance_disambiguates_same_name(self):
        targets = [
            {
                "target_id": 2,
                "series_key": "GBR_AINTREE_ORRELL_PARK_HANDICAP_HURDLE",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "[William Hill] H. Hurdle",
                "racecourse": "Aintree",
                "distance_text": "2.5",
            },
            {
                "target_id": 3,
                "series_key": "GBR_AINTREE_BRIDLE_ROAD_HANDICAP_HURDLE",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "[William Hill] H. Hurdle",
                "racecourse": "Aintree",
                "distance_text": "3",
            },
        ]
        schedule = self.tool.parse_bha_jump_schedule_text(
            "\n".join(
                [
                    "Apr. 4 Aintree WilliamHillH’CapHurdle 2m4f Prem 75,000",
                    "Apr. 5 Aintree WilliamHillH’CapHurdle 3m1/2f Prem 75,000",
                ]
            ),
            season_start_year=2024,
        )

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"]: row["local_date"] for row in result["matches"]},
            {2: "2025-04-04", 3: "2025-04-05"},
        )

    def test_france_galop_group_index_extracts_date_course_name_and_distance(self):
        text = """
        5-10 ParisLongchamp 350 000 2 & + ABBAYE LONGCHAM Groupe I 1 000
        15-06 Chantilly 1,0 M 3 ans F DIANE Groupe I 2 100
        20-07 Chantilly 80 000 3 ans F CHLOE Groupe III 1 800
        """

        rows = self.tool.parse_france_galop_flat_schedule_text(text, year=2025)

        self.assertEqual(
            [(row["local_date"], row["racecourse"], row["race_name"], row["distance_text"]) for row in rows],
            [
                ("2025-10-05", "ParisLongchamp", "ABBAYE LONGCHAM", "1000m"),
                ("2025-06-15", "Chantilly", "DIANE", "2100m"),
                ("2025-07-20", "Chantilly", "CHLOE", "1800m"),
            ],
        )

    def test_france_galop_obstacle_index_extracts_group_races(self):
        text = """
        18-05 Auteuil 135 000 3 ans M H AGUADO Groupe III 3 500
        18-05 Auteuil 278 000 4 ans ALAIN DU BREIL Groupe I 3 900
        7-12 Auteuil 125 000 4 & + F ANDRE MICHEL Groupe III 3 600
        """

        rows = self.tool.parse_france_galop_obstacle_schedule_text(text, year=2025)

        self.assertEqual(
            [
                (row["local_date"], row["racecourse"], row["race_name"], row["normalized_grade"], row["distance_text"])
                for row in rows
            ],
            [
                ("2025-05-18", "Auteuil", "AGUADO", "G3", "3500m"),
                ("2025-05-18", "Auteuil", "ALAIN DU BREIL", "G1", "3900m"),
                ("2025-12-07", "Auteuil", "ANDRE MICHEL", "G3", "3600m"),
            ],
        )

    def test_france_galop_obstacle_index_uses_alphabetical_fallback(self):
        text = """
        CHRISTIAN DE TREDERN. . . . . . . . . . . . . . . . . . .27 mai AUTEUIL 133 169
        """

        rows = self.tool.parse_france_galop_obstacle_schedule_text(text, year=2025)

        self.assertEqual(
            rows,
            [
                {
                    "local_date": "2025-05-27",
                    "racecourse": "Auteuil",
                    "race_name": "CHRISTIAN DE TREDERN",
                    "normalized_grade": "",
                    "distance_text": "",
                }
            ],
        )

    def test_official_schedule_match_uses_hong_kong_season_edition_year(self):
        targets = [{
            "target_id": 1,
            "series_key": "hong-kong-hong-kong-cup",
            "year": 2025,
            "country_region": "hong_kong",
            "original_name": "Hong Kong Cup [LONGINES]",
            "racecourse": "Sha Tin",
            "distance_text": "2000",
        }]
        schedule = [{
            "edition_year": 2025,
            "local_date": "2024-12-08",
            "racecourse": "Sha Tin",
            "race_name": "LONGINES Hong Kong Cup",
            "normalized_grade": "G1",
            "distance_text": "2000m",
        }]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2024-12-08")
        self.assertEqual(result["matches"][0]["target_id"], 1)

    def test_official_schedule_match_deduplicates_apostrophe_variants(self):
        target = {
            "target_id": 21,
            "series_key": "hong-kong-chairman-s-trophy",
            "year": 2022,
            "country_region": "hong_kong",
            "original_name": "Chairman's Trophy",
            "racecourse": "Sha Tin",
            "distance_text": "1600m",
            "normalized_grade": "G2",
        }
        schedule = [
            {
                "edition_year": 2022,
                "local_date": "2022-04-03",
                "racecourse": "Sha Tin",
                "race_name": race_name,
                "normalized_grade": "G2",
                "distance_text": "1600m",
            }
            for race_name in ("Chairman's Trophy", "Chairman’s Trophy")
        ]

        result = self.tool.match_official_schedule_targets([target], schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(len(result["matches"]), 1)

    def test_official_schedule_match_disambiguates_same_name_by_distance(self):
        targets = [
            {
                "target_id": 2,
                "series_key": "GBR_AINTREE_ORRELL_PARK_HANDICAP_HURDLE",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "[William Hill] H. Hurdle",
                "racecourse": "Aintree",
                "distance_text": "2.5",
            },
            {
                "target_id": 3,
                "series_key": "GBR_AINTREE_BRIDLE_ROAD_HANDICAP_HURDLE",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "[William Hill] H. Hurdle",
                "racecourse": "Aintree",
                "distance_text": "3",
            },
        ]
        schedule = [
            {
                "local_date": "2025-04-04",
                "racecourse": "Aintree",
                "race_name": "William Hill Handicap Hurdle",
                "normalized_grade": "G3",
                "distance_text": "2m4f",
            },
            {
                "local_date": "2025-04-05",
                "racecourse": "Aintree",
                "race_name": "William Hill Top Price Guarantee Handicap Hurdle",
                "normalized_grade": "G3",
                "distance_text": "3m149y",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"]: row["local_date"] for row in result["matches"]},
            {2: "2025-04-04", 3: "2025-04-05"},
        )

    def test_official_schedule_match_accepts_bha_course_alias_but_not_name_only_guess(self):
        targets = [{
            "target_id": 4,
            "series_key": "GBR_EPSOM_CORONATION_CUP_STAKES",
            "year": 2025,
            "country_region": "united_kingdom",
            "original_name": "Coronation Cup S. [Holland Cooper]",
            "racecourse": "Epsom",
            "distance_text": "12f",
        }]
        schedule = [
            {
                "local_date": "2025-06-06",
                "racecourse": "Epsom Downs",
                "race_name": "CORONATION CUP",
                "normalized_grade": "G1",
                "distance_text": "12f",
            },
            {
                "local_date": "2025-06-20",
                "racecourse": "Ascot",
                "race_name": "CORONATION",
                "normalized_grade": "G1",
                "distance_text": "8f",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2025-06-06")

    def test_official_schedule_match_uses_series_scoped_sponsor_order_aliases(self):
        targets = [
            {
                "target_id": 5,
                "series_key": "united-kingdom-acomb",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "Acomb S. [Tattersalls]",
                "racecourse": "York",
                "distance_text": "7",
            },
            {
                "target_id": 6,
                "series_key": "united-kingdom-ascot-hurdle",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "Ascot Hurdle[Howden]",
                "racecourse": "Ascot",
                "distance_text": "2.5",
            },
        ]
        schedule = [
            {
                "local_date": "2025-08-20",
                "racecourse": "York",
                "race_name": "TATTERSALLS ACOMB",
                "normalized_grade": "G3",
                "distance_text": "7f",
            },
            {
                "local_date": "2025-11-22",
                "racecourse": "Ascot",
                "race_name": "HOWDEN ASCOT HURDLE",
                "normalized_grade": "G2",
                "distance_text": "2m3f",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual({row["target_id"] for row in result["matches"]}, {5, 6})

    def test_official_schedule_match_rejects_low_similarity_same_meeting_guess(self):
        targets = [{
            "target_id": 7,
            "series_key": "france-craon",
            "year": 2025,
            "country_region": "france",
            "original_name": "Craon(R)",
            "racecourse": "ParisLongchamp",
            "distance_text": "2400",
            "normalized_grade": "G1",
        }]
        schedule = [{
            "local_date": "2025-10-05",
            "racecourse": "ParisLongchamp",
            "race_name": "F ARC DE TRIOMPHE",
            "normalized_grade": "G1",
            "distance_text": "2400m",
        }]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["matches"], [])
        self.assertEqual(result["issues"][0]["code"], "official_schedule_match_missing")

    def test_official_schedule_match_uses_grade_to_select_relocated_series(self):
        targets = [{
            "target_id": 8,
            "series_key": "france-compiegne-de-hurdle",
            "year": 2025,
            "country_region": "france",
            "original_name": "Compiegne (de) Hurdle",
            "racecourse": "Compiegne",
            "distance_text": "4100",
            "normalized_grade": "G3",
        }]
        schedule = [
            {
                "local_date": "2025-09-27",
                "racecourse": "Auteuil",
                "race_name": "DE COMPIEGNE",
                "normalized_grade": "G3",
                "distance_text": "3900m",
            },
            {
                "local_date": "2025-10-25",
                "racecourse": "Compiegne",
                "race_name": "COMPIEGNE",
                "normalized_grade": "G2",
                "distance_text": "4100m",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2025-09-27")
        self.assertEqual(result["matches"][0]["racecourse"], "Auteuil")

    def test_official_schedule_match_prefers_matching_grade_before_name_score(self):
        target = {
            "target_id": 22,
            "series_key": "united-kingdom-darley",
            "year": 2025,
            "country_region": "united_kingdom",
            "original_name": "Darley S",
            "racecourse": "Newmarket",
            "distance_text": "9f",
            "normalized_grade": "G3",
        }
        schedule = [
            {
                "local_date": "2025-10-11",
                "racecourse": "Newmarket",
                "race_name": "DARLEY DEWHURST",
                "normalized_grade": "G1",
                "distance_text": "7f",
            },
            {
                "local_date": "2025-10-11",
                "racecourse": "Newmarket",
                "race_name": "SPACE BLUES DARLEY",
                "normalized_grade": "G3",
                "distance_text": "9f",
            },
        ]

        result = self.tool.match_official_schedule_targets([target], schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["race_name"], "SPACE BLUES DARLEY")

    def test_official_schedule_match_uses_classic_novices_sponsor_alias(self):
        target = {
            "target_id": 23,
            "series_key": "united-kingdom-classic-novices-hurdle",
            "year": 2025,
            "country_region": "united_kingdom",
            "original_name": "Classic Novices Hurdle [AIS]",
            "racecourse": "Cheltenham",
            "distance_text": "2m4f",
            "normalized_grade": "G2",
        }
        schedule = [{
            "local_date": "2025-01-25",
            "racecourse": "Cheltenham",
            "race_name": "SSS SUPER ALLOYS NOVICES HURDLE",
            "normalized_grade": "G2",
            "distance_text": "2m4f",
        }]

        result = self.tool.match_official_schedule_targets([target], schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2025-01-25")

    def test_official_schedule_match_accepts_unique_named_distance_change(self):
        targets = [{
            "target_id": 9,
            "series_key": "france-carmarthen-hurdle",
            "year": 2025,
            "country_region": "france",
            "original_name": "Carmarthen Hurdle",
            "racecourse": "Auteuil",
            "distance_text": "3900",
            "normalized_grade": "G3",
        }]
        schedule = [{
            "local_date": "2025-10-18",
            "racecourse": "Auteuil",
            "race_name": "CARMARTHEN",
            "normalized_grade": "G3",
            "distance_text": "4300m",
        }]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2025-10-18")

    def test_official_schedule_match_uses_exact_short_name_alias(self):
        targets = [{
            "target_id": 10,
            "series_key": "france-d-indy-hurdle",
            "year": 2025,
            "country_region": "france",
            "original_name": "d'Indy Hurdle",
            "racecourse": "Auteuil",
            "distance_text": "3600",
            "normalized_grade": "G3",
        }]
        schedule = [
            {
                "local_date": "2025-03-02",
                "racecourse": "Auteuil",
                "race_name": "D’INDY",
                "normalized_grade": "G3",
                "distance_text": "3600m",
            },
            {
                "local_date": "2025-10-12",
                "racecourse": "Auteuil",
                "race_name": "ANDRE ADELE",
                "normalized_grade": "G3",
                "distance_text": "3600m",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2025-03-02")

    def test_official_schedule_match_strips_region_prefix_from_series_key(self):
        targets = [{
            "target_id": 12,
            "series_key": "hong-kong-chairman-s-sprint-prize",
            "year": 2025,
            "country_region": "hong_kong",
            "original_name": "Chairman's Sprint Prize [FWD]",
            "racecourse": "Sha Tin",
            "distance_text": "1200",
            "normalized_grade": "G1",
        }]
        schedule = [{
            "edition_year": 2025,
            "local_date": "2025-04-27",
            "racecourse": "Sha Tin",
            "race_name": "FWD Chairman's Sprint Prize",
            "normalized_grade": "G1",
            "distance_text": "1200m",
        }]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2025-04-27")

    def test_official_schedule_match_prefers_sponsored_core_name_over_similar_race(self):
        targets = [{
            "target_id": 15,
            "series_key": "hong-kong-jockey-club-mile",
            "year": 2025,
            "country_region": "hong_kong",
            "original_name": "Jockey Club Mile [BOCHK Private Wealth]",
            "racecourse": "Sha Tin",
            "distance_text": "1600",
            "normalized_grade": "G2",
        }]
        schedule = [
            {
                "edition_year": 2025,
                "local_date": "2024-11-17",
                "racecourse": "Sha Tin",
                "race_name": "BOCHK Jockey Club Cup",
                "normalized_grade": "G2",
                "distance_text": "2000m",
            },
            {
                "edition_year": 2025,
                "local_date": "2024-11-17",
                "racecourse": "Sha Tin",
                "race_name": "BOCHK Private Wealth Jockey Club Mile",
                "normalized_grade": "G2",
                "distance_text": "1600m",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["race_name"], "BOCHK Private Wealth Jockey Club Mile")

    def test_official_schedule_match_uses_reviewed_regional_abbreviations(self):
        targets = [
            {
                "target_id": 16,
                "series_key": "hong-kong-queen-elizabeth-ii-cup",
                "year": 2025,
                "country_region": "hong_kong",
                "original_name": "Queen Elizabeth II Cup [FWD]",
                "racecourse": "Sha Tin",
                "distance_text": "2000",
                "normalized_grade": "G1",
            },
            {
                "target_id": 17,
                "series_key": "united-kingdom-1965-stp",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "1965 Stp.[Copybet]",
                "racecourse": "Ascot",
                "distance_text": "2.5",
                "normalized_grade": "G2",
            },
            {
                "target_id": 18,
                "series_key": "united-kingdom-aintree-champion-nhf-race",
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "Aintree Champion NHF Race [Weatherbysnhstallions.co.uk]",
                "racecourse": "Aintree",
                "distance_text": "2",
                "normalized_grade": "G2",
            },
        ]
        schedule = [
            {
                "edition_year": 2025,
                "local_date": "2025-04-27",
                "racecourse": "Sha Tin",
                "race_name": "FWD QEII Cup",
                "normalized_grade": "G1",
                "distance_text": "2000m",
            },
            {
                "local_date": "2025-12-19",
                "racecourse": "Ascot",
                "race_name": "Copybet 1965 Chase",
                "normalized_grade": "G2",
                "distance_text": "2m5f",
            },
            {
                "local_date": "2025-04-05",
                "racecourse": "Aintree",
                "race_name": "Weatherbys nhstallions.co.uk Standard Open NH Flat Race",
                "normalized_grade": "G2",
                "distance_text": "2m1f",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual({row["target_id"] for row in result["matches"]}, {16, 17, 18})

    def test_official_schedule_match_rejects_reused_source_row(self):
        targets = [
            {
                "target_id": target_id,
                "series_key": series_key,
                "year": 2025,
                "country_region": "united_kingdom",
                "original_name": "[Sponsor] H. Stp",
                "racecourse": "Cheltenham",
                "distance_text": "3",
                "normalized_grade": "G3",
            }
            for target_id, series_key in [(13, "series-one"), (14, "series-two")]
        ]
        schedule = [{
            "local_date": "2025-03-11",
            "racecourse": "Cheltenham",
            "race_name": "SPONSOR HANDICAP CHASE",
            "normalized_grade": "G3",
            "distance_text": "3m1f",
        }]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["matches"], [])
        self.assertEqual(
            [(issue["target_id"], issue["code"]) for issue in result["issues"]],
            [(13, "official_schedule_source_reused"), (14, "official_schedule_source_reused")],
        )

    def test_manual_calendar_evidence_closes_only_its_exact_target(self):
        targets = [{
            "target_id": 11,
            "target_sha256": "a" * 64,
            "artifact_sha256": "b" * 64,
            "series_key": "france-bango",
            "year": 2025,
            "country_region": "france",
            "original_name": "Bango(R)",
            "chinese_name": "",
            "racecourse": "Saint-Cloud",
            "grade_text": "G3",
            "normalized_grade": "G3",
            "surface": "jumps",
            "distance_text": "2500",
            "source_refs": {"preserve": True},
        }]
        result = self.tool.merge_manual_calendar_evidence(
            targets,
            {"matches": [], "issues": [{"target_id": 11, "code": "official_schedule_match_missing"}]},
            [{
                "target_id": 11,
                "series_key": "france-bango",
                "edition_year": 2025,
                "local_date": "2025-03-29",
                "racecourse": "Saint-Cloud",
                "race_name": "Prix Bango",
                "normalized_grade": "G3",
                "distance_text": "2500m",
                "annual_surface": "turf",
                "annual_discipline": "flat",
                "source_url": "https://www.zeturf.fr/fr/course-du-jour/2025-03-29/R1C8-saint-cloud-prix-bango",
                "source_provider": "zeturf",
                "source_authority": "third_party_high_access",
            }],
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["target_id"], 11)

        with self.assertRaisesRegex(ValueError, "manual evidence identity mismatch"):
            self.tool.merge_manual_calendar_evidence(
                targets,
                {"matches": [], "issues": []},
                [{"target_id": 11, "series_key": "france-other", "edition_year": 2025}],
            )

    def test_calendar_event_input_uses_annual_facts_and_direct_result_url(self):
        target = {
            "target_id": 11,
            "target_sha256": "a" * 64,
            "artifact_sha256": "b" * 64,
            "series_key": "france-bango",
            "year": 2025,
            "country_region": "france",
            "original_name": "Bango(R)",
            "chinese_name": "",
            "racecourse": "Saint-Cloud",
            "grade_text": "G3",
            "normalized_grade": "G3",
            "surface": "jumps",
            "distance_text": "2500",
            "source_refs": {"preserve": True},
        }
        match = {
            "target_id": 11,
            "series_key": "france-bango",
            "edition_year": 2025,
            "local_date": "2025-03-29",
            "racecourse": "Saint-Cloud",
            "race_name": "Prix Bango",
            "normalized_grade": "G3",
            "distance_text": "2500m",
            "annual_surface": "turf",
            "annual_discipline": "flat",
            "source_url": "https://www.zeturf.fr/fr/course-du-jour/2025-03-29/R1C8-saint-cloud-prix-bango",
            "source_provider": "zeturf",
            "source_authority": "third_party_high_access",
        }

        rows = self.tool.build_calendar_event_input_rows([target], [match])

        self.assertEqual(rows[0]["slug"], "france-bango-2025")
        self.assertEqual(rows[0]["surface"], "turf")
        self.assertEqual(rows[0]["distance_text"], "2500m")
        source_refs = rows[0]["source_refs"]
        self.assertTrue(source_refs["preserve"])
        self.assertEqual(source_refs["calendar_discovery"]["annual_discipline"], "flat")
        self.assertEqual(
            source_refs["detail_discovery"]["urls"]["result_url"]["source_provider"],
            "zeturf",
        )

        with TemporaryDirectory() as tmp:
            files = self.tool.write_calendar_event_inputs(rows, Path(tmp))
            self.assertEqual(set(files), {"france"})
            self.assertIn("france-bango-2025", Path(files["france"]).read_text(encoding="utf-8-sig"))
