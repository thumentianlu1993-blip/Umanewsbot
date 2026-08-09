from __future__ import annotations

import importlib.util
import csv
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from types import SimpleNamespace

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "prepare_tjcis_ics_catalog.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("prepare_tjcis_ics_catalog_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


LEGACY_PAGES = [
    """
Prix de l'Arc de Triomphe G1  .  .  .  7,000,000  .  .  3up  .  .  2400 T  .  Longchamp
Prix du Cadran G1  .  .  .  1,000,000  .  .  4up  .  .  4000 T  .  Longchamp
Prix du Carrousel (L)  .  .  200,000  .  .  4up  .  .  3000 T  .  Longchamp
Prix de la Porte Maillot  .  .  200,000  .  .  3up  .  .  1400 T  .  Longchamp
Prix du Conseil de Paris G2  .  .  500,000  .  .  3up  .  .  2400 T  .  Longchamp
FRANCE
RACE PURSE AGE/SEX DISTANCE TRACK
Pt I—FRANCE
""",
    """
American Jockey Club Cup G2  .  .  4up  .  .  2200 T  .  Nakayama
Arima Kinen, Grand Prix G1  .  .  3up  .  .  2500 T  .  Nakayama
JAPAN
RACE AGE/SEX DISTANCE TRACK
Pt II—JPN Aic-Han
""",
    """
Champion Hurdle Challenge Trophy G1  .  .  4up  .  .  2.00  .  Cheltenham
King George VI Stp. G1  .  .  5up  .  .  3.00  .  Kempton
GREAT BRITAIN JUMP RACES
Pt IV—GB JUMPS
""",
]


CURRENT_PAGES = [
    """
American Jockey Club Cup
G2 ..............................................134,620,000 ............4up ..............2200 T ................Nakayama
Andromeda S. (L) ............................50,640,000 ............3up ..............2000 T ................Kyoto
Arima Kinen (Grand Prix) G1 ........648,000,000 ............3up ..............2500 T ................Nakayama
JAPAN
RACE PURSE AGE/SEX DISTANCE TRACK
Pt I—JAPAN
""",
    """
HONG KONG
(Racing season September 2015 - July 2016)
Chairman's Sprint Prize G1 ........10,000,000 HK$ ............3up ..............1200 T ................Sha Tin
Hong Kong Classic Cup HK G1 ......10,000,000 ............4yo ..............1800 T ................Sha Tin
Pt I—OTHER
""",
    """
Supreme Novices Hurdle [Sky Bet]
G1 ......................................................120,000 ............4up ..............2 ................Cheltenham
Summer Hurdle H. (L) ......................35,000 ............4up ..............2 ................Market Rasen
Tingle Creek Trophy Stp. [Betfair]
G1 ......................................................150,000 ............4up ..............2 ................Sandown
Pt IV—GREAT BRITAIN JUMPS
""",
]


class TjcisIcsCatalogParserTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def test_legacy_layout_keeps_grades_and_jumps_but_excludes_listed(self):
        rows = self.module.parse_ics_pages(LEGACY_PAGES, year=1998)

        self.assertEqual(len(rows), 7)
        self.assertEqual({row["country_region"] for row in rows}, {"france", "japan", "united_kingdom"})
        self.assertNotIn("Prix du Carrousel", {row["original_name"] for row in rows})
        self.assertIn("Prix du Conseil de Paris", {row["original_name"] for row in rows})
        jump = next(row for row in rows if row["original_name"].startswith("Champion Hurdle"))
        self.assertEqual(jump["discipline"], "jumps")
        self.assertEqual(jump["surface"], "jumps")

    def test_current_layout_joins_wrapped_names_and_assigns_hong_kong_season(self):
        rows = self.module.parse_ics_pages(CURRENT_PAGES, year=2016)

        names = {row["original_name"] for row in rows}
        self.assertIn("American Jockey Club Cup", names)
        self.assertIn("Supreme Novices Hurdle [Sky Bet]", names)
        self.assertNotIn("Andromeda S.", names)
        hong_kong = [row for row in rows if row["country_region"] == "hong_kong"]
        self.assertEqual(len(hong_kong), 2)
        self.assertEqual({row["season_label"] for row in hong_kong}, {"2015/16"})

    def test_region_context_continues_when_repeated_pdf_header_is_not_extractable(self):
        pages = [
            "Ack Ack H. G3 .... 100,000 .... 3up .... 8 D .... Churchill Downs\nPt I—UNITED STATES OF AMERICA",
            "Acorn S. G1 .... 750,000 .... 3yo f .... 8 D .... Belmont Park",
            "Aichi Hai G3 .... 77,000,000 .... 4up f/m .... 2000 T .... Chukyo\nPt I—JAPAN",
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual([row["country_region"] for row in rows], ["united_states", "united_states", "japan"])

    def test_unsupported_country_header_resets_previous_region_context(self):
        pages = [
            "Prix Exemple G3 .... 80,000 .... 3up .... 2000 T .... Chantilly\nPt I—FRANCE",
            "Not French G1 .... 80,000 .... 3up .... 2000 T .... Rome\nPt I—ITALY",
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual([row["original_name"] for row in rows], ["Prix Exemple"])

    def test_extended_regions_and_middle_east_country_are_preserved(self):
        pages = [
            "Example Australian S. G1 .... 1,000,000 .... 3up .... 2000 T .... Randwick\nPt I—AUSTRALIA",
            "Example German Preis G2 .... 70,000 .... 3up .... 2200 T .... Cologne\nPt I—GERMANY",
            "Example UAE S. G3 .... 700,000 .... 4up .... 1800 T .... Meydan\nPt I—UNITED ARAB EMIRATES",
            "Example Bahrain Trophy G2 .... 1,000,000 .... 3up .... 2000 T .... REHC\nPt I—OTHER RACES\nBAHRAIN",
            "Example Saudi Cup G3 .... 1,500,000 .... 4up .... 1800 D .... King Abdulaziz\nPt I—OTHER RACES\nKingdom of SAUDI ARABIA",
        ]

        rows = self.module.parse_ics_pages(pages, year=2025)

        self.assertEqual(
            {row["country_region"] for row in rows},
            {"australia", "germany", "middle_east"},
        )
        self.assertEqual(
            {row["country"] for row in rows if row["country_region"] == "middle_east"},
            {"united_arab_emirates", "bahrain", "saudi_arabia"},
        )

    def test_other_races_page_stops_at_next_country_heading(self):
        page = """
Pt I—OTHER RACES
OTHER RACES
BAHRAIN
Bahrain International Trophy G2 .... 1,000,000 .... 3up .... 2000 T .... REHC
ITALY
Premio Roma G2 .... 250,000 .... 3up .... 2000 T .... Rome
"""

        rows = self.module.parse_ics_pages([page], year=2025)

        self.assertEqual([row["original_name"] for row in rows], ["Bahrain International Trophy"])
        self.assertEqual(rows[0]["country"], "bahrain")

    def test_other_races_multi_country_page_parses_every_section(self):
        heading_layout = """
Pt I—OTHER RACES
BAHRAIN
Bahrain International Trophy G2 .... 1,000,000 .... 3up .... 2000 T .... REHC
Kingdom of SAUDI ARABIA
Saudi Cup G1 .... 20,000,000 .... 4up .... 1800 D .... King Abdulaziz
"""
        footer_layout = """
Bahrain Turf S. G3 .... 500,000 .... 3up .... 1600 T .... REHC
BAHRAIN
Riyadh Cup G2 .... 1,000,000 .... 4up .... 1800 D .... King Abdulaziz
SAUDI ARABIA
Pt I—OTHER RACES
"""

        for page in (heading_layout, footer_layout):
            rows = self.module.parse_ics_pages([page], year=2025)
            self.assertEqual({row["country"] for row in rows}, {"bahrain", "saudi_arabia"})
            self.assertEqual(len(rows), 2)

    def test_part_i_index_resets_previous_supported_country(self):
        pages = [
            "Saudi Cup G1 .... 20,000,000 .... 4up .... 1800 D .... King Abdulaziz\nPt I—OTHER RACES\nKingdom of SAUDI ARABIA",
            "Part I - INDEX\nRACE PAGE RACE PAGE\nAmerican Turf S. G1 .... 1-73\nAndrés S. Torres G3 .... 1-1",
        ]

        rows = self.module.parse_ics_pages(pages, year=2025)

        self.assertEqual([row["original_name"] for row in rows], ["Saudi Cup"])
        self.assertEqual(rows[0]["country"], "saudi_arabia")

    def test_qatar_section_between_unsupported_countries_is_preserved(self):
        page = """
Pt II—OTHER
OTHER RACES
POLAND
Wielka Warszawska (L) .... 100,000 .... 3up .... 2600 T .... Sluzewiec
QATAR
(Racing season October 2024 - May 2025)
Qatar DerbyQA G1 .... US$500,000 .... 3yo .... 2000 T .... Al Rayyan
Qatar Gold TrophyQA G1 .... US$250,000 .... 3up .... 2200 T .... Al Rayyan
SCANDINAVIA
Stockholm Cup International G3 .... 1,000,000 .... 3up .... 2400 T .... Bro Park
SPAIN
Gran Premio de Madrid (L) .... 85,000 .... 3up .... 2500 T .... La Zarzuela
"""

        rows = self.module.parse_ics_pages([page], year=2025)

        self.assertEqual([row["original_name"] for row in rows], ["Qatar Derby", "Qatar Gold Trophy"])
        self.assertEqual({row["country"] for row in rows}, {"qatar"})
        self.assertEqual({row["country_region"] for row in rows}, {"middle_east"})

    def test_parenthesized_grade_does_not_leak_open_paren_into_name(self):
        rows = self.module.parse_ics_pages(
            ["Al Khail Trophy (G3) .... 700,000 .... 4up .... 2810 T .... Meydan\nPt I—UNITED ARAB EMIRATES"],
            year=2025,
        )

        self.assertEqual(rows[0]["original_name"], "Al Khail Trophy")

    def test_pdf_extraction_releases_each_page_cache(self):
        page_one = mock.Mock()
        page_one.extract_text.return_value = "first"
        page_two = mock.Mock()
        page_two.extract_text.return_value = None
        document = mock.MagicMock()
        document.__enter__.return_value.pages = [page_one, page_two]

        with mock.patch.object(self.module.pdfplumber, "open", return_value=document):
            pages = self.module._pdf_pages(Path("book.pdf"))

        self.assertEqual(pages, ["first", ""])
        page_one.close.assert_called_once_with()
        page_two.close.assert_called_once_with()

    def test_blank_section_footer_does_not_join_with_race_name_as_country(self):
        pages = [
            "Acorn S. G1 .... 80,000 .... 3yo f .... 8 D .... Belmont\nPt I—USA",
            "Pt I—\nIndiana General Assembly Distaff S. G3 .... 80,000 .... 3up f/m .... 8 D .... Indiana",
        ]

        rows = self.module.parse_ics_pages(pages, year=2015)

        self.assertEqual(
            [row["original_name"] for row in rows],
            ["Acorn S", "Indiana General Assembly Distaff S"],
        )

    def test_legacy_country_codes_reset_previous_region_context(self):
        pages = [
            "British Race G1 .... 80,000 .... 3up .... 8 T .... Ascot\nPt I—GB",
            "Irish Race G1 .... 80,000 .... 3up .... 8 T .... Curragh\nIRELAND\nPt I—IRE",
            "Italian Race G1 .... 80,000 .... 3up .... 1600 T .... Milan\nITALY\nPt I—ITY",
            "Japan Race G1 .... 80,000 .... 3up .... 1600 T .... Tokyo\nPt II—JPN",
        ]

        rows = self.module.parse_ics_pages(pages, year=1998)

        self.assertEqual(
            [(row["country_region"], row["original_name"]) for row in rows],
            [("united_kingdom", "British Race"), ("japan", "Japan Race")],
        )

    def test_race_range_prefix_is_not_mistaken_for_country_code(self):
        pages = [
            "Acorn S. G1 .... 80,000 .... 3yo f .... 8 D .... Belmont\nPt I—USA",
            "Canadian Turf S. G3 .... 80,000 .... 4up .... 8 T .... Gulfstream\nPt I—Can-Chu",
        ]

        rows = self.module.parse_ics_pages(pages, year=1998)

        self.assertEqual([row["original_name"] for row in rows], ["Acorn S", "Canadian Turf S"])

    def test_legacy_country_code_with_page_range_sets_target_context(self):
        pages = [
            "Prix Exemple G3 .... 80,000 .... 3up .... 2000 T .... Chantilly\nPt I—FR Abb-Cor",
            "Hong Kong Example G1 .... 80,000 .... 3up .... 1600 T .... Sha Tin\nPt II—HK Cha-Que",
        ]

        rows = self.module.parse_ics_pages(pages, year=2005)

        self.assertEqual(
            [(row["country_region"], row["original_name"]) for row in rows],
            [("france", "Prix Exemple"), ("hong_kong", "Hong Kong Example")],
        )

    def test_approximate_distance_and_appendix_boundary_are_handled(self):
        pages = [
            "Beaumont S. G3 .... 250,000 .... 3yo f .... a7 D .... Keeneland\nPt I—UNITED STATES OF AMERICA",
            "APPENDIX - USA\nOld Example G1 .... 100,000 .... 3up .... 8 D .... Belmont Park",
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual([row["original_name"] for row in rows], ["Beaumont S"])
        self.assertEqual(rows[0]["distance_text"], "7")

        suffix_rows = self.module.parse_ics_pages(
            ["Legacy S. G3 .... 100,000 .... 3up .... 12a T .... Newbury\nPt I—GB"],
            year=1998,
        )
        self.assertEqual(suffix_rows[0]["distance_text"], "12")

        appendix_rows = self.module.parse_ics_pages(
            [
                "Valid S. G1 .... 100,000 .... 3up .... 8 T .... Ascot\nPt I—GB\n"
                "Appendix to POST PUBLICATION CHANGES\nOld S. G1 .... 100,000 .... 3up .... 8 T .... Ascot"
            ],
            year=2016,
        )
        self.assertEqual([row["original_name"] for row in appendix_rows], ["Valid S"])

        post_publication_rows = self.module.parse_ics_pages(
            [
                "Pt IV—FRENCH JUMPS\n"
                "Troytown Stp. G3 .... 135,000 .... 5up .... 4400 .... Auteuil\n"
                "** Race additions and changes in red were submitted after publication of the printed book\n"
                "Avenir (R) G3 AQ .... 34,000 .... 3 yo .... 2400 .... Nantes"
            ],
            year=2019,
        )
        self.assertEqual([row["original_name"] for row in post_publication_rows], ["Troytown Stp"])

    def test_spaced_age_notation_is_parsed(self):
        rows = self.module.parse_ics_pages(
            ["Washington Park H. G3 .... 300,000 .... 3 up .... 9.5 .... Arlington Park\nPt I—USA"],
            year=2009,
        )

        self.assertEqual([row["original_name"] for row in rows], ["Washington Park H"])

    def test_legacy_age_range_does_not_drop_wrapped_jump_name(self):
        page = (
            "Champion Bumper Open NHF\n"
            "[Weatherbys] G1 .... 30,000 .... 4-6 .... 2.00 .... Cheltenham\n"
            "Champion Hurdle Challenge Trophy\n"
            "[Smurfit] G1 .... 250,000 .... 4up .... 2.00 .... Cheltenham\n"
            "Pt IV—GB JUMPS"
        )

        rows = self.module.parse_ics_pages([page], year=2000)

        self.assertEqual(
            [row["original_name"] for row in rows],
            ["Champion Bumper Open NHF [Weatherbys]", "Champion Hurdle Challenge Trophy [Smurfit]"],
        )

    def test_short_y_age_clears_ungraded_jump_before_wrapped_graded_race(self):
        page = (
            "UNITED STATES JUMP RACES\n"
            "Alston Cup .... 35,000 .... 3y .... 2-1/16 M .... Charleston\n"
            "A.P. Smithwick Hurdle S.\n"
            "G1 .... 150,000 .... 4up .... 2.06 M .... Saratoga\n"
            "Pt IV—UNITED STATES JUMPS"
        )

        rows = self.module.parse_ics_pages([page], year=2023)

        self.assertEqual([row["original_name"] for row in rows], ["A.P. Smithwick Hurdle S"])

    def test_spaced_dot_columns_clear_ungraded_legacy_jump_rows(self):
        page = (
            "UNITED STATES JUMP RACES\n"
            "Crown Royal S. H. . . . 25,000 . . 4up . . 19 . . Pine Mountain\n"
            "Future Champions Cup . . . 25,000 . . 3yo . . 19 . . Great Meadow\n"
            "Grand National S. G1 . . . 100,000 . . 5up . . 24 . . Far Hills\n"
            "Pt IV—UNITED STATES JUMPS"
        )

        rows = self.module.parse_ics_pages([page], year=1998)

        self.assertEqual([row["original_name"] for row in rows], ["Grand National S"])

    def test_pdf_date_like_age_range_keeps_wrapped_jump_name(self):
        page = (
            "Champion Bumper NHF Race\n"
            "[Weatherbys] G1 .... 30,000 .... 6-Apr .... 2.00 .... Cheltenham\n"
            "Midlands Grand National H. Stp.\n"
            "[Marstons Pedigree] G3 .... 80,000 .... 6up .... 4.25 .... Uttoxeter\n"
            "Pt IV—GB JUMPS"
        )

        rows = self.module.parse_ics_pages([page], year=2002)

        self.assertEqual(
            [row["original_name"] for row in rows],
            ["Champion Bumper NHF Race [Weatherbys]", "Midlands Grand National H. Stp. [Marstons Pedigree]"],
        )

    def test_page_and_section_headers_do_not_attach_to_first_race(self):
        pages = [
            "($=US Dollars) Pt I—USA Ben-Bue\n"
            "Ben Ali S. G3 .... 100,000 .... 4up .... 9 D .... Keeneland",
            "Pt IV—FRENCH JUMPS\nFRENCH JUMP RACES\n"
            "Aguado Hurdle G3 .... 135,000 .... 3yo .... 3500 .... Auteuil",
            "Pt IV—UNITED STATES JUMPS\nUNITED STATES JUMP RACES\n"
            "A.P. Smithwick Hurdle G1 .... 150,000 .... 4up .... 2.06 .... Saratoga",
        ]

        rows = self.module.parse_ics_pages(pages, year=2023)

        self.assertEqual(
            [row["original_name"] for row in rows],
            ["Ben Ali S", "Aguado Hurdle", "A.P. Smithwick Hurdle"],
        )

    def test_aqps_year_heading_does_not_attach_to_first_group_race(self):
        page = (
            "Pt I—FRANCE\n2020 AQPS races:\n"
            "Antoine de Vazeilhes (Criterium du Centre)\n"
            "(R) G3 AQ .... 30,000 .... 3yo .... 2400 T .... Vichy"
        )

        rows = self.module.parse_ics_pages([page], year=2020)

        self.assertEqual(rows[0]["original_name"], "Antoine de Vazeilhes (Criterium du Centre) (R)")
        self.assertEqual(rows[0]["source_scope"], "international_cataloguing_standards_aqps")

    def test_grade_joined_directly_to_comma_separated_purse_is_parsed(self):
        rows = self.module.parse_ics_pages(
            [
                "Poule d'Essai des Pouliches G11,700,000 .... 3yo f .... 1600 T .... Longchamp\n"
                "Pt I—FR"
            ],
            year=2000,
        )

        self.assertEqual(rows[0]["grade_text"], "G1")
        self.assertEqual(rows[0]["original_name"], "Poule d'Essai des Pouliches")

    def test_grade_joined_directly_to_jump_name_is_parsed(self):
        rows = self.module.parse_ics_pages(
            ["Finale Junior Novices HurdleG1 .... 30,000 .... 3yo .... 2.00 .... Chepstow\nPt IV—GB JUMPS"],
            year=2000,
        )

        self.assertEqual([row["original_name"] for row in rows], ["Finale Junior Novices Hurdle"])

    def test_ocr_column_digit_before_grade_is_not_part_of_jump_name(self):
        rows = self.module.parse_ics_pages(
            ["Mildmay Novices Stp. 3G2 .... 75,000 .... 5up .... 3.00 .... Aintree\nPt IV—GB JUMPS"],
            year=2003,
        )

        self.assertEqual([row["original_name"] for row in rows], ["Mildmay Novices Stp"])

    def test_jump_distance_disambiguates_same_name_at_same_course(self):
        rows = self.module.parse_ics_pages(
            [
                "Gold Cup H. Stp.[Sponsor] G3 .... 175,000 .... 4up .... 3.25 .... Newbury\n"
                "Gold Cup H. Stp. G3 .... 53,000 .... 5up .... 2.50 .... Newbury\n"
                "Pt IV—GB JUMPS"
            ],
            year=2009,
        )

        self.assertEqual({row["distance_text"] for row in rows}, {"2.50", "3.25"})
        self.assertEqual(len({row["series_key"] for row in rows}), 2)

    def test_full_sponsored_name_preserves_distinct_same_course_jump_races_for_review(self):
        records = [
            "[Paddy Power] Gold Cup H. Stp G3 .... 150,000 .... 4up .... 2.5 .... Cheltenham",
            "[Racing Post] Gold Cup H. Stp G3 .... 150,000 .... 4up .... 2.5 .... Cheltenham",
        ]
        rows = self.module.parse_ics_pages(["\n".join([*records, "Pt IV—GB JUMPS"])], year=2022)
        reversed_rows = self.module.parse_ics_pages(
            ["\n".join([*reversed(records), "Pt IV—GB JUMPS"])],
            year=2022,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["series_key"] for row in rows}), 2)
        self.assertEqual({row["series_key"] for row in rows}, {row["series_key"] for row in reversed_rows})

    def test_global_disambiguation_applies_ambiguous_identity_to_all_years(self):
        rows = [
            {
                "country_region": "united_kingdom",
                "year": year,
                "series_key": key,
                "original_name": name,
                "racecourse": course,
                "discipline": "jumps",
                "distance_text": distance,
                "surface": "jumps",
            }
            for year, key, name, course, distance in (
                (2020, "united-kingdom-gold-cup-h-stp", "Gold Cup H. Stp. [bet365]", "Sandown", "3.50"),
                (2021, "united-kingdom-gold-cup-h-stp-a", "[Paddy Power] Gold Cup H. Stp", "Cheltenham", "2.5"),
                (2021, "united-kingdom-gold-cup-h-stp-b", "[Racing Post] Gold Cup H. Stp", "Cheltenham", "2.50"),
            )
        ]

        result = self.module._global_disambiguate_ambiguous_series(rows)

        self.assertEqual(len({row["series_key"] for row in result}), 3)
        self.assertIn("sandown-jumps-3-5-jumps", result[0]["series_key"])
        self.assertNotEqual(result[1]["series_key"], result[2]["series_key"])

    def test_synthetic_surface_and_same_name_collisions_are_not_silently_collapsed(self):
        pages = [
            "Example S. G3 .... 100,000 .... 3up .... 8 AWT .... Golden Gate\n"
            "Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Pt I—UNITED STATES OF AMERICA"
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual({row["surface"] for row in rows}, {"synthetic", "dirt"})
        self.assertEqual(len({row["series_key"] for row in rows}), 2)
        self.assertTrue(all(row["series_key"].startswith("united-states-example-") for row in rows))

        no_course_rows = self.module.parse_ics_pages(
            [
                "Lexington S. G3 .... 100,000 .... 3up .... 10 T\n"
                "Lexington S. G2 .... 100,000 .... 3up .... 8.5 D\n"
                "Pt I—USA"
            ],
            year=1998,
        )
        self.assertEqual(len({row["series_key"] for row in no_course_rows}), 2)

    def test_exact_source_duplicate_counts_for_reconciliation_but_yields_one_target(self):
        row = "Laurel Dash S. G3 .... 100,000 .... 3up .... 6 T .... Laurel Race Course"
        page = f"{row}\n{row}\nTotal Graded races: .... 2\nPt I—USA"

        rows = self.module.parse_ics_pages([page], year=1998)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_duplicate_count"], 2)

    def test_declared_graded_total_mismatch_fails_closed(self):
        page = (
            "Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Total Graded races: .... 2\nPt I—UNITED STATES OF AMERICA"
        )

        with self.assertRaisesRegex(self.module.IcsCatalogError, "graded total mismatch"):
            self.module.parse_ics_pages([page], year=2016)

    def test_declared_grade_distribution_mismatch_fails_even_when_total_matches(self):
        page = (
            "Example S. G2 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Number of G1 races: .... 1\nTotal Graded races: .... 1\nPt I—USA"
        )

        with self.assertRaisesRegex(self.module.IcsCatalogError, "graded total mismatch"):
            self.module.parse_ics_pages([page], year=2016)

    def test_approved_mode_records_declared_conflict_without_inventing_rows(self):
        page = (
            "Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Number of G3 races: .... 2\nTotal Graded races: .... 2\nPt I—USA"
        )
        conflicts = []

        rows = self.module.parse_ics_pages([page], year=2016, declared_count_conflicts=conflicts)

        self.assertEqual([row["original_name"] for row in rows], ["Example S"])
        self.assertEqual(
            conflicts,
            [
                {
                    "year": 2016,
                    "region": "united_states",
                    "discipline": "flat",
                    "parsed_total": 1,
                    "declared_total": 2,
                    "parsed_grades": {"G1": 0, "G2": 0, "G3": 1},
                    "declared_grades": {"G3": 2},
                }
            ],
        )

    def test_source_conflict_approval_binds_policy_review_and_unique_keys(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "review.csv"
            review.write_text("year,region\n2016,united_states\n", encoding="utf-8")
            approval_path = root / "approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "approved_by": "owner",
                        "approved_at": "2026-07-12T12:00:00+08:00",
                        "policy": self.module.SOURCE_CONFLICT_POLICY,
                        "review_path": review.name,
                        "review_sha256": self.module._sha256(review),
                        "expected_conflict_keys": ["2016:united_states:flat"],
                        "expected_conflicts_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
            expected_approval_sha = self.module._sha256(approval_path)

            approval, identity = self.module._load_source_conflict_approval(str(approval_path))

        self.assertEqual(approval["approved_by"], "owner")
        self.assertEqual(identity["sha256"], expected_approval_sha)

    def test_identical_repeated_declared_counts_are_not_added_twice(self):
        pages = [
            "Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Number of G3 races: .... 1\nTotal Graded races: .... 1\nPt I—USA",
            "Number of G3 races: .... 1\nTotal Graded races: .... 1\nPt I—USA",
        ]

        rows = self.module.parse_ics_pages(pages, year=2011)

        self.assertEqual([row["original_name"] for row in rows], ["Example S"])

    def test_conflicting_declared_counts_fail_closed(self):
        pages = [
            "Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Total Graded races: .... 1\nPt I—USA",
            "Total Graded races: .... 2\nPt I—USA",
        ]

        with self.assertRaisesRegex(self.module.IcsCatalogError, "official declared count conflict"):
            self.module.parse_ics_pages(pages, year=2011)

    def test_asterisk_catalog_row_becomes_not_held_without_inventing_surface(self):
        page = (
            "Ordinary incomplete race ................ Arlington Intl.\n"
            "*Arlington Million G1 ........................ Arlington Intl.\n"
            "Total Graded races: .... 1\nPt I—USA"
        )

        rows = self.module.parse_ics_pages([page], year=1998)

        self.assertEqual(rows[0]["original_name"], "Arlington Million")
        self.assertEqual(rows[0]["expectation_status"], "not_held")
        self.assertEqual(rows[0]["surface"], "")
        self.assertIn("asterisk_not_held", rows[0]["source_scope"])

    def test_jump_country_headers_do_not_leak_between_regions(self):
        pages = [
            "British Chase G1 .... 100,000 .... 5up .... 3 .... Kempton\nPt IV—GREAT BRITAIN JUMPS",
            "Irish Chase G1 .... 100,000 .... 5up .... 3 .... Leopardstown\nPt IV—IRISH JUMPS",
            "Japan Jump G1 .... 100,000 .... 5up .... 4100 .... Nakayama\nPt IV—JAPANESE JUMPS",
            "US Jump G1 .... 100,000 .... 5up .... 3 .... Belmont\nPt IV—UNITED STATES JUMPS",
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual(
            [(row["country_region"], row["original_name"]) for row in rows],
            [
                ("united_kingdom", "British Chase"),
                ("japan", "Japan Jump"),
                ("united_states", "US Jump"),
            ],
        )

    def test_legacy_ire_jump_header_resets_uk_context(self):
        pages = [
            "British Chase G1 .... 100,000 .... 5up .... 3 .... Kempton\nPt IV—GB JUMPS",
            "Pt IV—IRE Ark-Hat\nIRELAND JUMPRACES\n"
            "Arkle Perpetual Challenge Cup Novice Stp. G2 .... 45,000 .... 5up .... 2.1 .... Leopardstown",
        ]

        rows = self.module.parse_ics_pages(pages, year=2001)

        self.assertEqual([row["original_name"] for row in rows], ["British Chase"])

    def test_jump_country_title_and_index_reset_context(self):
        pages = [
            "British Chase G1 .... 100,000 .... 5up .... 3 .... Kempton\nPt IV—GREAT BRITAIN JUMPS",
            "IRISH JUMP RACES\nIrish Chase G1 .... 100,000 .... 5up .... 3 .... Leopardstown",
            "INDEX\nUnited States Jumps\nRace Page G1 .... 1 .... 5up .... 3 .... 4-1\nPt IV—INDEX",
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual([row["original_name"] for row in rows], ["British Chase"])

    def test_incomplete_listed_row_does_not_attach_to_next_graded_race(self):
        page = (
            "Example Listed Hurdle (L) .... 70,000 .... 4-5yo .... Auteuil\n"
            "Example Chase G2 .... 100,000 .... 5up .... 3 .... Auteuil\n"
            "Pt IV—FRENCH JUMPS"
        )

        rows = self.module.parse_ics_pages([page], year=2016)

        self.assertEqual([row["original_name"] for row in rows], ["Example Chase"])

    def test_ungraded_jump_row_with_age_does_not_attach_to_wrapped_graded_race(self):
        page = (
            "FRENCH JUMP RACES\n($=US Dollars)\n"
            "Aguado Hurdle .... 113,085 .... 3yo .... Auteuil\n"
            "Alain du Breil Course de Haies d'Ete des\n"
            "4 Ans Hurdle G1 .... 188,475 .... 4yo .... Auteuil\n"
            "Pt IV—FR JUMPS"
        )

        rows = self.module.parse_ics_pages([page], year=1999)

        self.assertEqual([row["original_name"] for row in rows], ["Alain du Breil Course de Haies d'Ete des 4 Ans Hurdle"])

    def test_combined_currency_header_is_removed_from_first_race_name(self):
        page = (
            "HONG KONG (HK Dollars) (Meters & Surface) Bauhinia Sprint Trophy G3 "
            ".... 10,000,000 .... 3up .... 1000 T .... Sha Tin\nPt II—HONG KONG"
        )

        rows = self.module.parse_ics_pages([page], year=2016)

        self.assertEqual(rows[0]["original_name"], "Bauhinia Sprint Trophy")

    def test_hong_kong_sar_and_legacy_currency_headers_are_removed(self):
        current = self.module.parse_ics_pages(
            [
                "HONG KONG SAR, China (HK Dollars) (Meters & Surface) Bauhinia Sprint Trophy G3 "
                ".... 10,000,000 .... 3up .... 1000 T .... Sha Tin\nPt I—HONG KONG"
            ],
            year=2022,
        )
        legacy_name = self.module._clean_name(
            "(HK$) ($=US Dollars) (Meters & Surface Type) Bauhinia Sprint Trophy"
        )

        self.assertEqual(current[0]["original_name"], "Bauhinia Sprint Trophy")
        self.assertEqual(legacy_name, "Bauhinia Sprint Trophy")

    def test_short_u_age_clears_ungraded_us_jump_rows(self):
        page = (
            "Pt IV—UNITED STATES JUMPS\n"
            "New Jersey Hunt Cup S .... 50,000 .... 4u .... 3.25 .... Far Hills\n"
            "New York Turf Writers Cup H. G1 .... 150,000 .... 4up .... 2.25 .... Saratoga"
        )

        rows = self.module.parse_ics_pages([page], year=2006)

        self.assertEqual([row["original_name"] for row in rows], ["New York Turf Writers Cup H"])

    def test_missing_age_ungraded_jump_row_clears_before_graded_race(self):
        page = (
            "Pt IV—UNITED STATES JUMPS\n"
            "Joseph M. Rogers S. .... 30,000 .... 2.25 .... Fair Hill\n"
            "Marcellus Frost S. G3 .... 50,000 .... 4up .... 2 .... Percy Warner"
        )

        rows = self.module.parse_ics_pages([page], year=2006)

        self.assertEqual([row["original_name"] for row in rows], ["Marcellus Frost S"])

    def test_hong_kong_part_two_header_with_following_newline_is_detected(self):
        page = (
            "Hong Kong Classic Cup HK G1 .... 10,000,000 .... 4yo .... 1800 T .... Sha Tin\n"
            "Pt II—HONG KONG\nHONG KONG"
        )

        rows = self.module.parse_ics_pages([page], year=2016)

        self.assertEqual([row["original_name"] for row in rows], ["Hong Kong Classic Cup"])

    def test_series_keys_remove_sponsors_and_stay_stable_across_editions(self):
        old = self.module.stable_series_key("united_kingdom", "Tingle Creek Trophy Stp. [Old Sponsor]")
        new = self.module.stable_series_key("united_kingdom", "Tingle Creek Trophy Stp. [Betfair]")

        self.assertEqual(old, new)
        self.assertEqual(new, "united-kingdom-tingle-creek-trophy-stp")
        self.assertEqual(
            self.module.canonical_series_name("Tingle Creek Trophy Stp. [Betfair]"),
            "Tingle Creek Trophy Stp.",
        )

    def test_series_keys_normalize_apostrophe_spacing_camel_case_and_handicap_marker(self):
        self.assertEqual(
            self.module.stable_series_key("france", "Prix d'Aumale"),
            self.module.stable_series_key("france", "Prix d’Aumale"),
        )
        self.assertEqual(
            self.module.stable_series_key("japan", "Jiji PressHai Flower Cup"),
            self.module.stable_series_key("japan", "Jiji Press Hai Flower Cup"),
        )
        self.assertEqual(
            self.module.stable_series_key("hong_kong", "Bauhinia Sprint Trophy (H)"),
            self.module.stable_series_key("hong_kong", "Bauhinia Sprint Trophy"),
        )
        self.assertEqual(
            self.module.canonical_series_name("Bauhinia Sprint Trophy (H)"),
            "Bauhinia Sprint Trophy",
        )
        self.assertEqual(
            self.module.stable_series_key("united_states", "Ancient Title Breeders' Cup H"),
            self.module.stable_series_key("united_states", "Ancient Title Breeders' Cup S"),
        )
        self.assertEqual(
            self.module.stable_series_key("united_states", "Hard Scuffle Steeplechase S. (R)"),
            self.module.stable_series_key("united_states", "Hard Scuffle Steeplechase"),
        )
        self.assertEqual(
            self.module.stable_series_key("united_kingdom", "Haldon Gold Challenge Cup H. Stp."),
            self.module.stable_series_key("united_kingdom", "Haldon Gold Challenge Cup Stp."),
        )

    def test_unknown_or_zero_row_page_fails_closed(self):
        with self.assertRaisesRegex(self.module.IcsCatalogError, "zero graded rows"):
            self.module.parse_ics_pages(["Pt I—JAPAN\nOnly malformed content"], year=2026)

    def test_edition_index_discovers_nonstandard_2000_to_2002_names(self):
        html = """
        <a href="/pdf/icsc00/ICSBook2000.pdf">2000</a>
        <a href="/pdf/icsc01/ICSBook2001.pdf">2001</a>
        <a href="/pdf/icsc02/2002CatStandardsBook.pdf">2002</a>
        <a href="/pdf/icsc03/2003_EntireBook.pdf">2003</a>
        """

        links = self.module.discover_edition_links(html, base_url="https://www.tjcis.com", years=range(2000, 2004))

        self.assertEqual(set(links), {2000, 2001, 2002, 2003})
        self.assertTrue(links[2002].endswith("2002CatStandardsBook.pdf"))

    def test_network_requires_cli_and_both_production_switches(self):
        enabled = {
            "HISTORICAL_RACE_BACKFILL_ENABLED": "true",
            "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK": "true",
        }
        self.module.require_network_gates(allow_network=True, environ=enabled)

        for allow_network, environ in (
            (False, enabled),
            (True, {**enabled, "HISTORICAL_RACE_BACKFILL_ENABLED": "false"}),
            (True, {**enabled, "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK": "false"}),
        ):
            with self.subTest(allow_network=allow_network, environ=environ):
                with self.assertRaises(self.module.IcsCatalogError):
                    self.module.require_network_gates(allow_network=allow_network, environ=environ)

    def test_download_uses_shared_request_budget_and_source_cache(self):
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            destination = Path(tmp) / "source" / "book.pdf"
            budget = mock.Mock()
            cache = mock.Mock(return_value={"path": "source/book.pdf", "sha256": "a" * 64})
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b"%PDF fixture"
            with mock.patch.object(self.module, "before_network_request", budget), mock.patch.object(
                self.module, "write_source_cache", cache
            ), mock.patch.object(self.module.request, "urlopen", return_value=response):
                identity = self.module.download_to_cache(
                    "https://www.tjcis.com/book.pdf", destination, timeout=10
                )

        budget.assert_called_once_with("https://www.tjcis.com/book.pdf")
        cache.assert_called_once_with(destination, b"%PDF fixture", source_url="https://www.tjcis.com/book.pdf")
        self.assertEqual(identity["sha256"], "a" * 64)

    def test_resume_reuses_only_manifest_verified_source_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "book.pdf"
            destination.write_bytes(b"%PDF fixture")
            digest = self.module._sha256(destination)
            (root / "source_cache_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "root": str(root),
                        "files": {
                            "book.pdf": {
                                "path": "book.pdf",
                                "size": destination.stat().st_size,
                                "sha256": digest,
                                "source_url": "https://www.tjcis.com/book.pdf",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(self.module, "before_network_request") as budget:
                identity = self.module.download_to_cache(
                    "https://www.tjcis.com/book.pdf",
                    destination,
                    timeout=10,
                    reuse_existing=True,
                )

        budget.assert_not_called()
        self.assertEqual(identity["sha256"], digest)

    def test_fully_cached_resume_does_not_require_network_switches(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            for name in ("tjcis_past_editions.html", "tjcis_current_editions.html", "tjcis_ics_2016.pdf"):
                (source / name).touch()
            args = SimpleNamespace(
                years=[2016],
                output_dir=str(root),
                resume=True,
                allow_network=False,
                timeout_seconds=10,
                continue_on_year_error=False,
            )
            with mock.patch.object(self.module, "require_network_gates") as gates, mock.patch.object(
                self.module, "download_to_cache", side_effect=self.module.IcsCatalogError("stop after gate check")
            ):
                with self.assertRaisesRegex(self.module.IcsCatalogError, "stop after gate check"):
                    self.module.prepare_catalog(args)

        gates.assert_not_called()

    def test_continue_on_year_error_writes_partial_manifests_without_hiding_gap(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            for name in (
                "tjcis_past_editions.html",
                "tjcis_current_editions.html",
                "tjcis_ics_1999.pdf",
                "tjcis_ics_2000.pdf",
            ):
                (source / name).touch()
            args = SimpleNamespace(
                years=[1999, 2000],
                output_dir=str(root),
                resume=True,
                allow_network=False,
                timeout_seconds=10,
                continue_on_year_error=True,
            )
            identity = {"path": "fixture", "size": 0, "sha256": "a" * 64, "source_url": "https://example.test"}
            successful_rows = [
                {
                    "record_type": "catalog",
                    "country_region": region,
                    "year": 2000,
                    "series_key": f"{region}-example",
                    "canonical_name_original": "Example",
                    "original_name": "Example",
                    "chinese_name": "",
                    "grade_text": "G1",
                    "racecourse": "Example",
                    "local_date": "",
                    "distance_text": "1600",
                    "surface": "turf",
                    "expectation_status": "held",
                    "founded_year": "",
                    "ended_year": "",
                    "series_status": "unknown",
                    "season_label": "1999/00" if region == "hong_kong" else "",
                    "source_scope": "fixture",
                    "discipline": "flat",
                    "source_duplicate_count": 1,
                }
                for region in self.module.REGION_ADAPTERS
            ]
            with mock.patch.object(self.module, "download_to_cache", return_value=identity), mock.patch.object(
                self.module, "discover_edition_links", return_value={1999: "https://example.test/1999.pdf", 2000: "https://example.test/2000.pdf"}
            ), mock.patch.object(self.module, "_pdf_pages", return_value=["fixture"]), mock.patch.object(
                self.module,
                "parse_ics_pages",
                side_effect=[self.module.IcsCatalogError("1999 source conflict"), successful_rows],
            ), mock.patch.dict(
                self.module.MIN_REGION_ROWS,
                {region: 1 for region in self.module.REGION_ADAPTERS},
            ):
                result = self.module.prepare_catalog(args)

            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((root / "manifest_japan.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["successful_years"], [2000])
        self.assertIn("1999", summary["year_errors"])
        self.assertIn("1999", manifest["excluded_year_errors"])

    def test_continue_on_year_error_isolates_missing_region_coverage(self):
        incomplete = [
            {
                "country_region": region,
                "year": 2020,
            }
            for region in self.module.REGION_ADAPTERS
            if region != "hong_kong"
        ]
        missing = self.module._missing_regions(incomplete)

        self.assertEqual(missing, ["hong_kong"])

    def test_region_minimum_guard_catches_truncated_section_without_declared_total(self):
        rows = [
            {"country_region": region}
            for region, minimum in self.module.MIN_REGION_ROWS.items()
            for _ in range(minimum)
        ]
        rows = [
            row
            for index, row in enumerate(rows)
            if not (row["country_region"] == "united_states" and index % 2 == 0)
        ]

        implausible = self.module._implausibly_small_regions(rows)

        self.assertIn("united_states", implausible)
        self.assertNotIn("japan", implausible)

    def test_suspicious_name_guard_rejects_index_and_listed_row_contamination(self):
        rows = [
            {"original_name": "Race Page G1 index material"},
            {"original_name": "Listed Hurdle (L) 70,000 Example Chase"},
            {"original_name": "First S 25,000 4u Far Hills Second Hurdle"},
            {"original_name": "Oka Sho (Japanese 1,000 Guineas)"},
            {"original_name": "Challenger S. [$100,000 Michelob Ultra]"},
            {"original_name": "Normal Stakes"},
        ]

        suspicious = self.module._suspicious_catalog_names(rows)

        self.assertEqual(len(suspicious), 3)

    def test_parsed_rows_write_to_region_csv_with_raw_pdf_provenance(self):
        rows = self.module.parse_ics_pages(
            ["Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\nPt I—UNITED STATES OF AMERICA"],
            year=2016,
        )
        identity = {"path": "tjcis_ics_2016.pdf", "sha256": "a" * 64}
        with TemporaryDirectory() as tmp:
            path = self.module._write_year_region_csv(
                Path(tmp),
                rows,
                year=2016,
                raw_identity=identity,
                raw_url="https://www.tjcis.com/pdf/icsc16/2016_EntireBook.pdf",
            )
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["raw_source_cache_sha256"], "a" * 64)
        self.assertEqual(written[0]["raw_source_cache_path"], "tjcis_ics_2016.pdf")
