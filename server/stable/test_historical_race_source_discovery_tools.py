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
    def test_jra_schedule_accepts_legacy_plain_text_race_name(self):
        body = b"""
        <table>
          <tr><th colspan="7"><div><span>Jan. 24</span> KYOTO HIMBA STAKES</div></th></tr>
          <tr>
            <td>G3</td><td>KYOTO</td><td>1,600/Turf</td><td>4yo&amp;up</td><td>40,000,000</td>
            <td><a href="javascript:doSubmit('2015','0124','08','01','08','11','7')">Result</a></td>
            <td></td>
          </tr>
        </table>
        """

        rows = self.tool.parse_jra_english_schedule(body, year=2015)

        self.assertEqual(
            rows,
            [
                {
                    "race_name": "KYOTO HIMBA STAKES",
                    "race_key": "KYOTOHIMBAS",
                    "local_date": "2015-01-24",
                    "racecourse": "KYOTO",
                    "distance": "1,600/Turf",
                }
            ],
        )

    def test_jra_schedule_accepts_compact_legacy_column_layout(self):
        body = b"""
        <table>
          <tr><th colspan="3"><div><span>Jan. 29</span> Negishi Stakes (GIII)</div></th></tr>
          <tr>
            <td>Tokyo</td><td>4yo &amp; up/D1400m</td>
            <td><a href="javascript:doSubmit('2005','0129','05','01','01','11','7')">Result</a></td>
          </tr>
        </table>
        """

        rows = self.tool.parse_jra_english_schedule(body, year=2005)

        self.assertEqual(rows[0]["race_name"], "Negishi Stakes (GIII)")
        self.assertEqual(rows[0]["local_date"], "2005-01-29")
        self.assertEqual(rows[0]["racecourse"], "Tokyo")
        self.assertEqual(rows[0]["distance"], "4yo & up/D1400m")

    def test_jra_history_accepts_legacy_headers_and_slash_date(self):
        body = """
        <table>
          <tr><th>月/日</th><th>レース名</th><th>場</th><th>結果</th></tr>
          <tr><td>1/24（土）</td><td>京都牝馬Ｓ</td><td>京都</td><td><a href="007.html">結果</a></td></tr>
        </table>
        <table>
          <tr><th>月/日</th><th>レース名</th><th>場</th><th>結果</th></tr>
          <tr><td>1/25（日）</td><td>アメリカＪＣＣ</td><td>中山</td><td><a href="008.html">結果</a></td></tr>
        </table>
        """.encode("cp932")

        rows = self.tool.parse_jra_history_records(body, year=2015)

        self.assertEqual(rows[0]["local_date"], "2015-01-24")
        self.assertEqual(rows[0]["race_name"], "京都牝馬Ｓ")
        self.assertEqual(rows[0]["racecourse"], "KYOTO")
        self.assertEqual(
            rows[0]["result_url"],
            "https://www.jra.go.jp/datafile/seiseki/replay/2015/007.html",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["local_date"], "2015-01-25")

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
            "3m": 3 * 1760,
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

        self.assertEqual(
            self.tool._distance_measurement("1600m", "united_states"),
            ("metric", 1600.0),
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

    def test_jra_official_aliases_cover_ledger_abbreviations_and_jump_names(self):
        history = """
        <table><tr><th>月日</th><th>レース名</th><th>競馬場</th><th>結果</th></tr>
          <tr><td>6月24日 土曜</td><td>J・GⅢ 東京ジャンプS</td><td>東京</td><td><a href="/datafile/seiseki/replay/2023/057.html">result</a></td></tr>
          <tr><td>8月20日 日曜</td><td>GⅢ 北九州記念</td><td>小倉</td><td><a href="/datafile/seiseki/replay/2023/072.html">result</a></td></tr>
          <tr><td>8月26日 土曜</td><td>J・GⅢ 小倉サマージャンプ</td><td>小倉</td><td><a href="/datafile/seiseki/replay/2023/074.html">result</a></td></tr>
          <tr><td>9月17日 日曜</td><td>GⅡ ローズS</td><td>阪神</td><td><a href="/datafile/seiseki/replay/2023/084.html">result</a></td></tr>
          <tr><td>10月15日 日曜</td><td>J・GⅡ 東京ハイジャンプ</td><td>東京</td><td><a href="/datafile/seiseki/replay/2023/093.html">result</a></td></tr>
          <tr><td>10月28日 土曜</td><td>GⅡ スワンS</td><td>京都</td><td><a href="/datafile/seiseki/replay/2023/096.html">result</a></td></tr>
          <tr><td>11月11日 土曜</td><td>GⅡ デイリー杯2歳S</td><td>京都</td><td><a href="/datafile/seiseki/replay/2023/103.html">result</a></td></tr>
          <tr><td>11月11日 土曜</td><td>J・GⅢ 京都ジャンプS</td><td>京都</td><td><a href="/datafile/seiseki/replay/2023/104.html">result</a></td></tr>
        </table>
        """
        schedule = b"""
        <table><tr><th colspan='7'><span>Nov. 11</span><a>DAILY HAI NISAI STAKES</a></th></tr>
        <tr><td>G2</td><td>KYOTO</td><td>1600/Turf</td><td></td><td></td>
        <td><a href="javascript:doSubmit('2023','1111','08','03','04','11','7')">o</a></td></tr></table>
        """
        expected = {
            "japan-tokyo-jump": "Tokyo Jump S",
            "japan-tv-nishi-nippon-corporation-sho-kitakyushu-kinen": "TV Nishinippon Corp. Sho Kitakyushu Kinen",
            "japan-kokura-summer-jump": "Kokura Summer Jump",
            "japan-kansai-television-co-ltd-sho-rose": "Kansai Television Co. Ltd. Sho Rose S",
            "japan-tokyo-high-jump": "Tokyo High-Jump",
            "japan-mbs-sho-swan": "MBS Sho Swan S",
            "japan-daily-hai-nisai": "Daily Hai Nisai S",
        }
        targets = [
            {
                "series_key": series_key,
                "year": 2023,
                "country_region": "japan",
                "original_name": original_name,
                "racecourse": "",
                "distance_text": "1600m",
            }
            for series_key, original_name in expected.items()
        ]

        result = self.tool.build_jra_provider_rows(
            targets=targets,
            year=2023,
            english_schedule_body=schedule,
            history_body=history.encode("cp932"),
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual({row["series_key"] for row in result["rows"]}, set(expected))

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

    def test_toba_accepts_legacy_race_number_with_trailing_equals(self):
        body = """
        <table>
          <tr>
            <th>Track</th><th>Date</th><th>Division</th><th>Stake</th><th>Gr</th>
            <th>Age</th><th>Sex</th><th>Dis</th><th>Sur</th><th>Field</th>
            <th>Total Purse</th><th>Winner</th>
          </tr>
          <tr>
            <td>DMR</td><td>3-Sep</td><td>2YO</td>
            <td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9=&amp;BorP=P&amp;TID=DMR&amp;CTRY=USA&amp;DT=09/03/2018&amp;DAY=D&amp;STYLE=EQB">DEL MAR FUTURITY</a></td>
            <td>1</td><td>2</td><td></td><td>7</td><td>D</td><td>6</td>
            <td>$300,345</td><td>Game Winner</td>
          </tr>
        </table>
        """
        target = {
            "series_key": "united-states-del-mar-futurity",
            "year": 2018,
            "country_region": "united_states",
            "original_name": "Del Mar Futurity",
            "racecourse": "Del Mar",
            "distance_text": "7",
        }

        result = self.tool.build_toba_provider_rows(targets=[target], year=2018, body=body)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["rows"][0]["local_date"], "2018-09-03")
        self.assertEqual(
            result["rows"][0]["urls"]["result_url"]["url"],
            "https://www.equibase.com/yearbook/Result.cfm?cy=USA&de=D&rd=2018-09-03&rn=9&tk=DMR",
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

    def test_toba_does_not_treat_similar_wrong_track_name_as_unreviewed_relocation(self):
        body = """
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
          <tr><td>WEST VIRGINIA DERBY</td><td>MNR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=8&amp;TID=MNR&amp;DT=8/3/2025">Alpha</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": "united-states-virginia-derby",
                "year": 2025,
                "country_region": "united_states",
                "original_name": "Virginia Derby",
                "racecourse": "Colonial Downs",
                "distance_text": "9",
            },
            {
                "series_key": "united-states-west-virginia-derby",
                "year": 2025,
                "country_region": "united_states",
                "original_name": "West Virginia Derby",
                "racecourse": "Mountaineer Park",
                "distance_text": "9",
            },
        ]

        result = self.tool.build_toba_provider_rows(targets=targets, year=2025, body=body)

        self.assertEqual(
            [row["series_key"] for row in result["rows"]],
            ["united-states-west-virginia-derby"],
        )
        self.assertEqual(
            [(issue["series_key"], issue["code"]) for issue in result["issues"]],
            [("united-states-virginia-derby", "source_match_not_unique")],
        )

    def test_toba_track_codes_cover_batch_006_flat_racecourses(self):
        expected = {
            "charles town": {"CT"},
            "delaware park": {"DEL"},
            "ellis park": {"ELP"},
            "fair grounds": {"FG"},
            "kentucky downs": {"KD"},
            "laurel park": {"LRL"},
            "lone star park": {"LS"},
            "los alamitos": {"LRC"},
            "monmouth park": {"MTH"},
            "mountaineer park": {"MNR"},
            "parx racing": {"PRX"},
            "penn national": {"PEN"},
            "pimlico": {"PIM"},
            "prairie meadows": {"PRM"},
            "presque isle downs": {"PID"},
            "remington park": {"RP"},
            "tampa bay downs": {"TAM"},
            "thistledown": {"TDN"},
        }

        self.assertEqual(
            {name: self.tool.TRACK_CODES.get(name) for name in expected},
            expected,
        )
        self.assertNotIn("percy warner", self.tool.TRACK_CODES)
        self.assertEqual(self.tool.TRACK_CODES["aqueduct"], {"AQU", "BAQ"})
        self.assertEqual(self.tool.TRACK_CODES["belmont at aqueduct"], {"AQU", "BAQ"})
        self.assertEqual(
            self.tool.TOBA_REVIEWED_RELOCATIONS,
            {
                "united-states-belmont-derby-invitational",
                "united-states-pennine-ridge",
                "united-states-soaring-softly",
                "united-states-victory-ride",
                "united-states-wonder-again",
            },
        )

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

    def test_toba_short_core_name_does_not_absorb_distinct_longer_race(self):
        body = """
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
          <tr><td>AMERICAN PHAROAH S.</td><td>SA</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=1&amp;TID=SA&amp;DT=9/28/2024">A</a></td></tr>
          <tr><td>BELMONT GOLD CUP S.</td><td>SAR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=2&amp;TID=SAR&amp;DT=6/6/2024">B</a></td></tr>
          <tr><td>TAMPA BAY DERBY</td><td>TAM</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=3&amp;TID=TAM&amp;DT=3/9/2024">C</a></td></tr>
          <tr><td>IROQUOIS S.</td><td>CD</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=4&amp;TID=CD&amp;DT=9/14/2024">D</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": series_key,
                "year": 2024,
                "country_region": "united_states",
                "original_name": original_name,
                "racecourse": racecourse,
                "distance_text": "8",
            }
            for series_key, original_name, racecourse in [
                ("united-states-american", "American S", "Santa Anita Park"),
                ("united-states-belmont", "Belmont S", "Saratoga"),
                ("united-states-tampa-bay", "Tampa Bay S", "Tampa Bay Downs"),
                ("united-states-calvin-houghland-iroquois-hurdle", "Calvin Houghland Iroquois Hurdle", "Churchill Downs"),
            ]
        ]

        result = self.tool.build_toba_provider_rows(targets=targets, year=2024, body=body)

        self.assertEqual(result["rows"], [])
        self.assertEqual(
            [issue["code"] for issue in result["issues"]],
            ["source_match_not_unique"] * 4,
        )

    def test_toba_uses_official_former_names_and_ignores_changed_presenting_sponsor(self):
        body = """
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
          <tr><td>CALIFORNIA CROWN S. PRESENTED BY SIRDAVIS AMERICAN WHISKY</td><td>SA</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=1&amp;TID=SA&amp;DT=9/28/2024">A</a></td></tr>
          <tr><td>OAK LEAF S. PRESENTED BY OAK TREE (formerly CHANDELIER S.)</td><td>SA</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=2&amp;TID=SA&amp;DT=10/5/2024">B</a></td></tr>
          <tr><td>MONROVIA S. PRESENTED BY DON JULIO</td><td>SA</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=3&amp;TID=SA&amp;DT=4/5/2024">C</a></td></tr>
          <tr><td>PRINCESS ROONEY S.</td><td>GP</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=4&amp;TID=GP&amp;DT=9/20/2024">D</a></td></tr>
          <tr><td>ELITE POWER S. (formerly RUNHAPPY S.)</td><td>BAQ</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=5&amp;TID=BAQ&amp;DT=12/6/2024">E</a></td></tr>
          <tr><td>JOHN C. HARRIS S. (formerly UNZIP ME S.)</td><td>SA</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=6&amp;TID=SA&amp;DT=9/27/2024">F</a></td></tr>
          <tr><td>OLD DOMINION DERBY (formerly VIRGINIA DERBY)</td><td>CNL</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=7&amp;TID=CNL&amp;DT=9/6/2024">G</a></td></tr>
        </table>
        """
        targets = [
            {
                "series_key": series_key,
                "year": 2024,
                "country_region": "united_states",
                "original_name": original_name,
                "racecourse": racecourse,
                "distance_text": "8",
            }
            for series_key, original_name, racecourse in [
                ("united-states-awesome-again", "Awesome Again S", "Santa Anita Park"),
                ("united-states-chandelier", "Chandelier S", "Santa Anita Park"),
                ("united-states-monrovia-s-presented-by-ketel-one", "Monrovia S. Presented by Ketel One", "Santa Anita Park"),
                ("united-states-princess-rooney-invitational", "Princess Rooney Invitational S", "Gulfstream Park"),
                ("united-states-runhappy", "Runhappy S", "Belmont at Aqueduct"),
                ("united-states-unzip-me", "Unzip Me S", "Santa Anita Park"),
                ("united-states-virginia-derby", "Virginia Derby", "Colonial Downs"),
            ]
        ]

        result = self.tool.build_toba_provider_rows(targets=targets, year=2024, body=body)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["series_key"] for row in result["rows"]},
            {target["series_key"] for target in targets},
        )

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

    def test_hkjc_2015_pattern_book_inherits_omitted_chronological_dates(self):
        text = """
        List of Group Races in 2015/2016
        Date Race Name Group Prize Money Distance (Metres) Qualifications Weights Priority To Run
        1 Jan 2016 Bauhinia Sprint Trophy HKG3 $3,000,000 1000 90+ Handicap Ratings
        Chinese Club Challenge Cup HKG3 $3,000,000 1400 95+ Handicap Ratings
        6 Jan 2016 January Cup HKG3 $3,000,000 1800 90+ Handicap Ratings
        """

        rows = self.tool.parse_hkjc_pattern_schedule_text(text, edition_year=2016)

        self.assertEqual(
            [(row["local_date"], row["race_name"], row["normalized_grade"], row["distance_text"]) for row in rows],
            [
                ("2016-01-01", "Bauhinia Sprint Trophy", "G3", "1000m"),
                ("2016-01-01", "Chinese Club Challenge Cup", "G3", "1400m"),
                ("2016-01-06", "January Cup", "G3", "1800m"),
            ],
        )
        self.assertEqual(rows[-1]["racecourse"], "Happy Valley")

    def test_hkjc_2016_pattern_book_inherits_course_and_distance_groups(self):
        text = """
        COURSE RECORDS
        Distance Course - Surface Horse Trained Record Date Record Time Black Type Races for 2016/2017 Season Group Race Prize Money Ref. Page
        1800 Sha Tin - TURF Helene Paragon HK 19 Jun 2016 1.45.83 Sa Sa Ladies’ Purse G3 06/11/16 3,000,000 14
        Centenary Vase G3 05/02/17 3,000,000 27
        Happy Valley - TURF Art Trader HK 01 Nov 2005 1.48.20 January Cup G3 04/01/17 3,000,000 23
        2000 Sha Tin - TURF Jim And Tonic FR 18 Apr 1999 2.00.10 LONGINES Jockey Club Cup G2 20/11/16 4,000,000 15
        Hong Kong Classic Cup 4yo 19/02/17 10,000,000 43
        """

        rows = self.tool.parse_hkjc_pattern_schedule_text(text, edition_year=2017)

        self.assertEqual(
            [(row["local_date"], row["racecourse"], row["race_name"], row["normalized_grade"], row["distance_text"]) for row in rows],
            [
                ("2016-11-06", "Sha Tin", "Sa Sa Ladies’ Purse", "G3", "1800m"),
                ("2017-02-05", "Sha Tin", "Centenary Vase", "G3", "1800m"),
                ("2017-01-04", "Happy Valley", "January Cup", "G3", "1800m"),
                ("2016-11-20", "Sha Tin", "LONGINES Jockey Club Cup", "G2", "2000m"),
                ("2017-02-19", "Sha Tin", "Hong Kong Classic Cup", "", "2000m"),
            ],
        )
        self.assertEqual({row["edition_year"] for row in rows}, {2017})

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

    def test_hkjc_result_url_resolver_uses_distance_before_name_and_original_alias(self):
        matches = [
            {
                "target_id": 21,
                "series_key": "hong-kong-chinese-club-challenge-cup",
                "edition_year": 2017,
                "local_date": "2017-01-01",
                "racecourse": "Sha Tin",
                "race_name": "Pocket Money HK 22 Apr 2007 Chinese Club Challenge Cup",
                "race_names": [
                    "Pocket Money HK 22 Apr 2007 Chinese Club Challenge Cup",
                    "Chinese Club Challenge Cup (H)",
                ],
                "normalized_grade": "G3",
                "distance_text": "1400m",
            },
            {
                "target_id": 22,
                "series_key": "hong-kong-jockey-club-cup",
                "edition_year": 2017,
                "local_date": "2017-11-19",
                "racecourse": "Sha Tin",
                "race_name": "BOCHK Jockey Club Cup",
                "race_names": ["BOCHK Jockey Club Cup", "Jockey Club Cup [LONGINES]"],
                "normalized_grade": "G2",
                "distance_text": "2000m",
            },
            {
                "target_id": 23,
                "series_key": "hong-kong-jockey-club-sprint",
                "edition_year": 2017,
                "local_date": "2017-11-19",
                "racecourse": "Sha Tin",
                "race_name": "BOCHK Jockey Club Sprint",
                "race_names": [
                    "BOCHK Jockey Club Sprint",
                    "Jockey Club Sprint [BOCHK Wealth Management]",
                ],
                "normalized_grade": "G2",
                "distance_text": "1200m",
            },
        ]
        result_pages = {
            ("2017-01-01", "ST"): [{
                "race_no": "8",
                "race_name": "THE CHINESE CLUB CHALLENGE CUP (HANDICAP)",
                "normalized_grade": "G3",
                "distance_text": "1400m",
            }],
            ("2017-11-19", "ST"): [
                {
                    "race_no": "6",
                    "race_name": "THE BOCHK JOCKEY CLUB CUP",
                    "normalized_grade": "G2",
                    "distance_text": "2000m",
                },
                {
                    "race_no": "7",
                    "race_name": "THE BOCHK WEALTH MANAGEMENT JOCKEY CLUB SPRINT",
                    "normalized_grade": "G2",
                    "distance_text": "1200m",
                },
            ],
        }

        result = self.tool.resolve_hkjc_result_urls(matches, result_pages)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            [(row["target_id"], row["result_race_no"]) for row in result["matches"]],
            [(21, "8"), (22, "6"), (23, "7")],
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

    def test_bha_flat_book_accepts_spaced_multiword_course_names(self):
        text = """
        May 4 NEWMARKET QIPCO 2000 GUINEAS (P1.C.F.) 8F 3CF 46
        ” 31 EPSOM DOWNS CORONATION CUP (P1.) 12F+ 4+ 67
        ” 23 SANDOWN PARK RACEHORSE LOTTO BRIGADIER GERARD (P3.) 10F 4+ 61
        Feb. 24 SOUTHWELL BETUK WINTER DERBY (P3.) 11F+ 4+ 30
        """

        rows = self.tool.parse_bha_flat_schedule_text(text, year=2024)

        self.assertEqual(
            [(row["local_date"], row["racecourse"], row["race_name"]) for row in rows],
            [
                ("2024-05-04", "Newmarket", "QIPCO 2000 GUINEAS"),
                ("2024-05-31", "Epsom Downs", "CORONATION CUP"),
                ("2024-05-23", "Sandown Park", "RACEHORSE LOTTO BRIGADIER GERARD"),
                ("2024-02-24", "Southwell", "BETUK WINTER DERBY"),
            ],
        )

    def test_bha_flat_book_prefers_explicit_race_date_over_derived_index_month(self):
        text = """
        June 12 NEWMARKET TATTERSALLS FALMOUTH (P1.F.) 8F 3+F 92
        Mar. 5 NEWMARKET July 12 TATTERSALLS FALMOUTH (P1.F.) 8F 3 F 92
        June 31 GOODWOOD JAEGER-LECOULTRE MOLECOMB (P3.) 5F 2 111
        """

        rows = self.tool.parse_bha_flat_schedule_text(text, year=2024)

        self.assertEqual(
            [(row["local_date"], row["race_name"]) for row in rows],
            [("2024-07-12", "TATTERSALLS FALMOUTH")],
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

    def test_bha_jump_book_supports_batch_006_regional_courses(self):
        rows = self.tool.parse_bha_jump_schedule_text(
            "\n".join(
                [
                    "Apr.12 Ayr CoralScottishGrandNationalH'CapChase 4m Prem 200,000",
                    "Dec.27 Chepstow CoralWelshGrandNationalH'CapChase 3m61/2f Prem 150,000",
                    "Nov. 8 Exeter BetwayHaldonGoldCupH'CapChase 2m11/2f 2 100,000",
                    "Feb.23 FontwellPark NationalSpiritHurdle 2m3f 2 60,000",
                    "Jul.19 MarketRasen UnibetSummerPlateH'CapChase 2m53/4f Prem 100,000",
                    "Mar.16 Uttoxeter MidlandsGrandNationalH'CapChase 4m2f Prem 150,000",
                    "Aug.24 Windsor WeatherbysWinterHill 1m2f 3 80,000",
                ]
            ),
            season_start_year=2024,
        )

        self.assertEqual(
            [row["racecourse"] for row in rows],
            ["Ayr", "Chepstow", "Exeter", "Fontwell", "Market Rasen", "Uttoxeter", "Windsor"],
        )

    def test_bha_jump_book_accepts_dotless_month_wrapped_name_and_plus_distance(self):
        rows = self.tool.parse_bha_jump_schedule_text(
            "\n".join(
                [
                    "July20 MarketRasen UnibetSummerPlateH’CapChase 2m51/2f Prem 100,000",
                    "Feb.15 Ascot InjuredJockeysFundAmbassadorsProgramme",
                    "SwinleyH’CapChase 3m Prem 100,000",
                    "Nov.23 Ascot NirvanaSpa1965Chase 2m5f+ 2 80,000",
                ]
            ),
            season_start_year=2024,
        )

        self.assertEqual(
            [
                (row["local_date"], row["racecourse"], row["race_name"], row["distance_text"])
                for row in rows
            ],
            [
                ("2024-07-20", "Market Rasen", "UNIBETSUMMERPLATEHANDICAPCHASE", "2m51/2f"),
                ("2025-02-15", "Ascot", "INJUREDJOCKEYSFUNDAMBASSADORSPROGRAMMESWINLEYHANDICAPCHASE", "3m"),
                ("2024-11-23", "Ascot", "NIRVANASPA1965CHASE", "2m5f+"),
            ],
        )

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

    def test_france_galop_flat_program_extracts_only_aqps_index_rows(self):
        text = """
        Index
        A.Q.P.S.
        valeur ne el. 1 800 a
        date hip. age sexe titre du prix Information - 1 800 + 2 200
        totale Fr 2 200
        1-09 Craon 37 000 3 ans R. DE GENNES 2 400
        8-09 Moulins 37 000 3 ans F Y. D'ARMAILLE 2 400
        Anglo-Arabes
        1-09 Craon 42 000 3 ans P. ESSAI 2 200
        """

        rows = self.tool.parse_france_galop_flat_program_text(text, year=2024)

        self.assertEqual(
            rows,
            [
                {
                    "local_date": "2024-09-01",
                    "racecourse": "Craon",
                    "race_name": "R. DE GENNES",
                    "normalized_grade": "",
                    "distance_text": "2400m",
                },
                {
                    "local_date": "2024-09-08",
                    "racecourse": "Moulins",
                    "race_name": "Y. D'ARMAILLE",
                    "normalized_grade": "",
                    "distance_text": "2400m",
                },
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

    def test_france_galop_obstacle_cross_year_window_keeps_target_natural_year(self):
        text = """
        31-12 Auteuil 125 000 4 & + F LAST YEAR Groupe III 3 600
        7-01 Cagnes-sur-Mer 154 000 5 & + THIS YEAR Groupe III 4 600
        """

        rows = self.tool.parse_france_galop_obstacle_schedule_text(
            text,
            year=2024,
            date_start="2023-12-03",
            date_end="2024-02-18",
        )

        self.assertEqual(
            rows,
            [
                {
                    "local_date": "2024-01-07",
                    "racecourse": "Cagnes-sur-Mer",
                    "race_name": "THIS YEAR",
                    "normalized_grade": "G3",
                    "distance_text": "4600m",
                }
            ],
        )

    def test_france_galop_obstacle_group_summary_preserves_column_identity(self):
        text = """
                             PROGRAMME  NATIONAL - GROUPES
                              Haies                    Steeple-Chase
                   3 ans      4 ans      5 et +      4 ans      5 et +
                                                               GD PX DE NICE
         Janvier                                               08/01 (Cagnes)
                                                                [G3]4600 4
                                                               GD PX DE PAU
                                                                05/02 (Pau)
                                                               [G3] 5300 24
                            QUESTARABAD  LA BARKA               LES DRAGS
         Juin              10/06 (Auteuil) 10/06 (Auteuil)    10/06 (Auteuil)
                             [G3] 3900 6 [G2] 4300 9           [G2] 4400 46
                                         TREDERN
                                       17/06 (Auteuil)
                                       [G3] [F] [4-5 ans]
                                         3600 5
        """

        rows = self.tool.parse_france_galop_obstacle_group_summary_text(
            text, year=2023
        )

        self.assertEqual(
            [
                row
                for row in rows
                if row["race_name"]
                in {"GD PX DE NICE", "GD PX DE PAU", "LES DRAGS", "TREDERN"}
            ],
            [
                {
                    "local_date": "2023-01-08",
                    "racecourse": "Cagnes",
                    "race_name": "GD PX DE NICE",
                    "normalized_grade": "G3",
                    "distance_text": "4600m",
                },
                {
                    "local_date": "2023-02-05",
                    "racecourse": "Pau",
                    "race_name": "GD PX DE PAU",
                    "normalized_grade": "G3",
                    "distance_text": "5300m",
                },
                {
                    "local_date": "2023-06-10",
                    "racecourse": "Auteuil",
                    "race_name": "LES DRAGS",
                    "normalized_grade": "G2",
                    "distance_text": "4400m",
                },
                {
                    "local_date": "2023-06-17",
                    "racecourse": "Auteuil",
                    "race_name": "TREDERN",
                    "normalized_grade": "G3",
                    "distance_text": "3600m",
                },
            ],
        )

        targets = [
            {
                "target_id": 61,
                "series_key": "france-grand-prix-de-la-ville-de-nice-bernard-secly-stp",
                "year": 2023,
                "country_region": "france",
                "original_name": "Grand Prix de la Ville de Nice (Bernard Secly) Stp",
                "racecourse": "Cagnes-sur-Mer",
                "distance_text": "4600",
                "normalized_grade": "G3",
            },
            {
                "target_id": 62,
                "series_key": "france-grand-prix-de-pau-stp",
                "year": 2023,
                "country_region": "france",
                "original_name": "Grand Prix de Pau Stp",
                "racecourse": "Pau",
                "distance_text": "5300",
                "normalized_grade": "G3",
            },
            {
                "target_id": 63,
                "series_key": "france-drags-des-stp",
                "year": 2023,
                "country_region": "france",
                "original_name": "Drags (des) Stp",
                "racecourse": "Auteuil",
                "distance_text": "4400",
                "normalized_grade": "G2",
            },
            {
                "target_id": 64,
                "series_key": "france-christian-de-tredern-hurdle",
                "year": 2023,
                "country_region": "france",
                "original_name": "Christian de Tredern Hurdle",
                "racecourse": "Auteuil",
                "distance_text": "3600",
                "normalized_grade": "G3",
            },
        ]
        result = self.tool.match_official_schedule_targets(
            targets,
            [{**row, "edition_year": 2023} for row in rows],
        )

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"] for row in result["matches"]},
            {61, 62, 63, 64},
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

    def test_official_schedule_match_prefers_detailed_source_over_equal_summary_match(self):
        target = {
            "target_id": 65,
            "series_key": "france-alain-du-breil-hurdle",
            "year": 2023,
            "country_region": "france",
            "original_name": "Alain du Breil Hurdle",
            "racecourse": "Auteuil",
            "distance_text": "3900",
            "normalized_grade": "G1",
        }
        schedule = [
            {
                "edition_year": 2023,
                "local_date": "2023-05-21",
                "racecourse": "Auteuil",
                "race_name": "ALAIN DU BREIL",
                "normalized_grade": "G1",
                "distance_text": "3900m",
                "calendar_source_parser": "france_obstacle_summary",
            },
            {
                "edition_year": 2023,
                "local_date": "2023-05-21",
                "racecourse": "Auteuil",
                "race_name": "ALAIN DU BREIL",
                "normalized_grade": "G1",
                "distance_text": "3900m",
                "calendar_source_parser": "france_obstacle",
            },
            {
                "edition_year": 2023,
                "local_date": "2023-05-22",
                "racecourse": "Auteuil",
                "race_name": "ALAIN DU BREIL",
                "normalized_grade": "G1",
                "distance_text": "3900m",
                "calendar_source_parser": "france_obstacle_summary",
            },
        ]

        result = self.tool.match_official_schedule_targets([target], schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2023-05-21")

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

    def test_official_schedule_match_prefers_compatible_distance_before_name_score(self):
        target = {
            "target_id": 8,
            "series_key": "hong-kong-hong-kong-champions-chater-cup",
            "year": 2016,
            "country_region": "hong_kong",
            "original_name": "Hong Kong Champions & Chater Cup [Standard Chartered]",
            "racecourse": "Sha Tin",
            "distance_text": "2400",
            "normalized_grade": "G1",
        }
        schedule = [
            {
                "edition_year": 2016,
                "local_date": "2016-02-21",
                "racecourse": "Sha Tin",
                "race_name": "Hong Kong Classic Cup",
                "normalized_grade": "G1",
                "distance_text": "1800m",
            },
            {
                "edition_year": 2016,
                "local_date": "2016-05-22",
                "racecourse": "Sha Tin",
                "race_name": "Standard Chartered Champions & Chater Cup",
                "normalized_grade": "G1",
                "distance_text": "2400m",
            },
        ]

        result = self.tool.match_official_schedule_targets([target], schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["local_date"], "2016-05-22")

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

    def test_official_schedule_match_uses_reviewed_uk_registered_names(self):
        cases = [
            (21, "GBR_BRISTOL_NOVICES_HURDLE", "Bristol Novices' Hurdle", "Cheltenham", "3", "G2", "ALBERT BARTLETT BRISTOL NOV. HURDLE", "2024-12-14"),
            (22, "GBR_CHELTENHAM_DECEMBER_3M2F_HANDICAP_CHASE", "[Sponsor] H. Stp", "Cheltenham", "3.25", "G3", "SOUTHAM HANDICAP CHASE", "2024-12-13"),
            (23, "GBR_CHELTENHAM_PADDY_POWER_GOLD_CUP", "[Sponsor] Gold Cup H. Stp", "Cheltenham", "2.5", "G3", "PADDY POWER GOLD CUP HANDICAP CHASE", "2024-11-16"),
            (24, "united-kingdom-champion-s-british-champion-middle-distance", "Champion S.", "Ascot", "10", "G1", "QIPCO CHAMPION", "2024-10-19"),
            (25, "united-kingdom-game-spirit-stp", "Game Spirit Stp.", "Newbury", "2", "G2", "BETFAIR EXCHANGE GAME SPIRIT CHASE", "2024-02-10"),
            (26, "united-kingdom-fillies-juvenile-hurdle", "Fillies' Juvenile H. Hurdle", "Cheltenham", "2", "G3", "SAFRAN LANDING SYSTEMS JUVENILE HANDICAP HURDLE", "2024-04-18"),
            (27, "united-kingdom-joel", "Joel S.", "Newmarket", "8", "G2", "AL BASTI EQUIWORLD, DUBAI JOEL", "2024-09-27"),
            (28, "united-kingdom-july", "July S.", "Newmarket", "6", "G2", "KINGDOM OF BAHRAIN JULY", "2024-07-11"),
            (29, "united-kingdom-silver-cup-stp", "Silver Cup H. Stp.", "Ascot", "3", "G3", "HOWDEN SILVER CUP HANDICAP CHASE", "2025-12-20"),
            (30, "united-kingdom-swinley-stp", "Swinley H. Stp.", "Ascot", "3", "G3", "BETFAIR SWINLEY HANDICAP CHASE", "2025-02-15"),
            (31, "united-kingdom-summer-plate-stp", "Summer Plate H. Stp.", "Market Rasen", "2.75", "G3", "UNIBET SUMMER PLATE HANDICAP CHASE", "2025-07-19"),
            (32, "united-kingdom-1965-stp", "1965 Stp.", "Ascot", "2.5", "G2", "NIRVANA SPA 1965 CHASE", "2024-11-23"),
            (33, "GBR_CHELTENHAM_NOVEMBER_LONG_DISTANCE_HANDICAP_CHASE", "[Jewson] H. Stp.", "Cheltenham", "3.5", "G3", "PRESTBURY HANDICAP CHASE", "2024-11-17"),
        ]
        targets = [
            {
                "target_id": target_id,
                "series_key": series_key,
                "year": int(local_date[:4]),
                "country_region": "united_kingdom",
                "original_name": original_name,
                "racecourse": racecourse,
                "distance_text": distance,
                "normalized_grade": grade,
            }
            for target_id, series_key, original_name, racecourse, distance, grade, _source_name, local_date in cases
        ]
        schedule = [
            {
                "local_date": local_date,
                "racecourse": racecourse,
                "race_name": source_name,
                "normalized_grade": grade,
                "distance_text": distance,
            }
            for _target_id, _series_key, _original_name, racecourse, distance, grade, source_name, local_date in cases
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"] for row in result["matches"]},
            {case[0] for case in cases},
        )

    def test_official_schedule_match_uses_france_galop_registered_abbreviations(self):
        cases = [
            (41, "france-la-coupe", "La Coupe", "LA COUPE", "2024-06-09", "G3"),
            (42, "france-la-coupe-de-maisons-laffitte", "La Coupe de Maisons-Laffitte", "LA COUPE DE M-L", "2024-09-08", "G3"),
            (43, "france-paris-g-p-de", "Paris (G.P. de)", "F GD PRIX PARIS", "2024-07-13", "G1"),
            (44, "france-vichy-g-p-de", "Vichy (G.P. de)", "GRAND PX VICHY", "2024-07-17", "G3"),
            (45, "france-renaud-du-vivier-hurdle", "Renaud du Vivier Hurdle", "RENAUD DU VIVIER (GRANDE COURSE DE HAIES DES 4 ANS)", "2024-11-24", "G1"),
        ]
        targets = [
            {
                "target_id": target_id,
                "series_key": series_key,
                "year": 2024,
                "country_region": "france",
                "original_name": original_name,
                "racecourse": "Auteuil" if target_id == 45 else ("Vichy" if target_id == 44 else "ParisLongchamp"),
                "distance_text": "3900" if target_id == 45 else ("2400" if target_id == 43 else "2000"),
                "normalized_grade": grade,
            }
            for target_id, series_key, original_name, _source_name, _date, grade in cases
        ]
        schedule = [
            {
                "edition_year": 2024,
                "local_date": local_date,
                "racecourse": "Auteuil" if target_id == 45 else ("Vichy" if target_id == 44 else "ParisLongchamp"),
                "race_name": source_name,
                "normalized_grade": grade,
                "distance_text": "" if target_id == 45 else ("2400m" if target_id == 43 else "2000m"),
            }
            for target_id, _series_key, _original_name, source_name, local_date, grade in cases
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"] for row in result["matches"]},
            {case[0] for case in cases},
        )

    def test_official_schedule_match_uses_france_galop_sponsored_obstacle_names(self):
        targets = [
            {
                "target_id": 46,
                "series_key": "france-grand-prix-de-pau-stp",
                "year": 2024,
                "country_region": "france",
                "original_name": "Grand Prix de Pau Stp",
                "racecourse": "Pau",
                "distance_text": "5300",
                "normalized_grade": "G3",
            },
            {
                "target_id": 47,
                "series_key": "france-magalen-bryant-bournosienne-hurdle",
                "year": 2024,
                "country_region": "france",
                "original_name": "Magalen Bryant (Bournosienne) Hurdle",
                "racecourse": "Auteuil",
                "distance_text": "3600",
                "normalized_grade": "G2",
            },
        ]
        schedule = [
            {
                "edition_year": 2024,
                "local_date": "2024-02-04",
                "racecourse": "Pau",
                "race_name": "ANDRE LABARRERE",
                "normalized_grade": "G3",
                "distance_text": "5300m",
            },
            {
                "edition_year": 2024,
                "local_date": "2024-11-16",
                "racecourse": "Auteuil",
                "race_name": "HARAS D'ETREHAM MAGALEN BRYANT",
                "normalized_grade": "G2",
                "distance_text": "3600m",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"] for row in result["matches"]},
            {46, 47},
        )

    def test_official_schedule_match_uses_france_galop_aqps_program_abbreviations(self):
        cases = [
            (48, "france-jacques-de-vienne", "Jacques de Vienne(R)", "J. DE VIENNE", "Fontainebleau", "2600"),
            (49, "france-richard-de-gennes", "Richard de Gennes(R)", "R. DE GENNES", "Craon", "2400"),
            (50, "france-yves-d-armaille", "Yves d'Armaille(R)", "Y. D'ARMAILLE", "Moulins", "2400"),
            (51, "france-tremblay", "Tremblay(R)", "DU TREMBLAY", "Lyon-Parilly", "2400"),
            (52, "france-craon", "Craon(R)", "DE CRAON", "ParisLongchamp", "2400"),
            (53, "france-bourbonnais", "Bourbonnais(R)", "DU BOURBONNAIS", "Saint-Cloud", "2500"),
        ]
        targets = [
            {
                "target_id": target_id,
                "series_key": series_key,
                "year": 2024,
                "country_region": "france",
                "original_name": original_name,
                "racecourse": course,
                "distance_text": distance,
            }
            for target_id, series_key, original_name, _source_name, course, distance in cases
        ]
        schedule = [
            {
                "edition_year": 2024,
                "local_date": f"2024-09-{target_id - 40:02d}",
                "racecourse": "Fontainebleau Galop" if target_id == 48 else course,
                "race_name": source_name,
                "normalized_grade": "",
                "distance_text": f"{distance}m",
            }
            for target_id, _series_key, _original_name, source_name, course, distance in cases
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"] for row in result["matches"]},
            {case[0] for case in cases},
        )

    def test_official_schedule_match_merges_duplicate_book_rows_and_keeps_distance(self):
        targets = [{
            "target_id": 19,
            "series_key": "united-kingdom-brigadier-gerard",
            "year": 2024,
            "country_region": "united_kingdom",
            "original_name": "Brigadier Gerard S. [Racehorse Lotto]",
            "racecourse": "Sandown",
            "distance_text": "10",
            "normalized_grade": "G3",
        }]
        schedule = [
            {
                "edition_year": 2024,
                "local_date": "2024-05-23",
                "racecourse": "Sandown Park",
                "race_name": "RACEHORSE LOTTO BRIGADIER GERARD",
                "normalized_grade": "G3",
                "distance_text": "",
            },
            {
                "edition_year": 2024,
                "local_date": "2024-05-23",
                "racecourse": "Sandown Park",
                "race_name": "RACEHORSE LOTTO BRIGADIER GERARD",
                "normalized_grade": "G3",
                "distance_text": "10f",
            },
            {
                "edition_year": 2024,
                "local_date": "2024-10-23",
                "racecourse": "Sandown Park",
                "race_name": "RACEHORSE LOTTO BRIGADIER GERARD",
                "normalized_grade": "G3",
                "distance_text": "",
            },
        ]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["matches"][0]["distance_text"], "10f")

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

    def test_official_schedule_match_retains_unique_high_confidence_source_user(self):
        targets = [
            {
                "target_id": 13,
                "series_key": "hong-kong-national-day-cup",
                "year": 2010,
                "country_region": "hong_kong",
                "original_name": "National Day Cup(H)",
                "racecourse": "Sha Tin",
                "distance_text": "1400",
                "normalized_grade": "G3",
            },
            {
                "target_id": 14,
                "series_key": "hong-kong-stewards-cup",
                "year": 2010,
                "country_region": "hong_kong",
                "original_name": "Stewards' Cup",
                "racecourse": "Sha Tin",
                "distance_text": "1600",
                "normalized_grade": "G1",
            },
        ]
        schedule = [{
            "edition_year": 2010,
            "local_date": "2010-10-01",
            "racecourse": "Sha Tin",
            "race_name": "National Day Cup",
            "normalized_grade": "G3",
            "distance_text": "1400m",
        }]

        result = self.tool.match_official_schedule_targets(targets, schedule)

        self.assertEqual([match["target_id"] for match in result["matches"]], [13])
        self.assertEqual(
            [(issue["target_id"], issue["code"]) for issue in result["issues"]],
            [(14, "official_schedule_source_reused")],
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
