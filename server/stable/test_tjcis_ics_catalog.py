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
            "Not French G1 .... 80,000 .... 3up .... 2000 T .... Cologne\nPt I—GERMANY",
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual([row["original_name"] for row in rows], ["Prix Exemple"])

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

    def test_synthetic_surface_and_same_name_collisions_are_not_silently_collapsed(self):
        pages = [
            "Example S. G3 .... 100,000 .... 3up .... 8 AWT .... Golden Gate\n"
            "Example S. G3 .... 100,000 .... 3up .... 8 D .... Belmont Park\n"
            "Pt I—UNITED STATES OF AMERICA"
        ]

        rows = self.module.parse_ics_pages(pages, year=2016)

        self.assertEqual({row["surface"] for row in rows}, {"synthetic", "dirt"})
        self.assertEqual(len({row["series_key"] for row in rows}), 2)
        self.assertTrue(all(row["series_key"].startswith("united-states-example-s-") for row in rows))

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

    def test_combined_currency_header_is_removed_from_first_race_name(self):
        page = (
            "HONG KONG (HK Dollars) (Meters & Surface) Bauhinia Sprint Trophy G3 "
            ".... 10,000,000 .... 3up .... 1000 T .... Sha Tin\nPt II—HONG KONG"
        )

        rows = self.module.parse_ics_pages([page], year=2016)

        self.assertEqual(rows[0]["original_name"], "Bauhinia Sprint Trophy")

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
            {"original_name": "Normal Stakes"},
        ]

        suspicious = self.module._suspicious_catalog_names(rows)

        self.assertEqual(len(suspicious), 2)

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
