#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("prepare_france_galop_bulletin_occurrences.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("france_galop_bulletins", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BANGO_TEXT = """
SAINT-CLOUD
mardi 24 mars 2026
825 249 PRIX BANGO 2 500 m
(Groupe III AQPS - AQPS, inscrits au stud-book)
32 000 c (16 000, 6 400, 4 800, 3 200, 1 600)
Parcours n° 9 : Plat, Dist. 2 500 m env.
Louisa Banbou, f, b, 5 ans, par Silverwave et Vestale 1
Banbou [Apsis (GB)], 66 k, h, Mme E. Banchereau
275 Madrinha Rosa, f, b, 4 ans, par Racinger et Celine Collonges 2
612 2 Mourir D’Envie, h, 4 ans, 64 k, h, Mme L. Moal –
3 partants ; 14 eng. ; 4 part def. – Total des entrées : 1 011 a
Certif. vétérinaire : L’Or Monseignor
"""

PENELOPE_TEXT = """
SAINT-CLOUD
mardi 6 avril 2021
976 259 PRIX PENELOPE 2 100 m
(Groupe III - Femelles)
Parcours n° 7 : Plat, Dist. 2 100 m env.
Philomene (IRE), 3 ans, par Dubawi IRE et Prudenzia 1
(IRE), 57 k, Godolphin SNC (M. Barzalona), A. Fabre (s) –
Incarville, 3 ans, par Wootton Bassett GB et Ilhabela 2
(IRE), 57 k, G. Augustin-Normand (C. Soumillon), D. Smaga –
601 1 Anasia (GB), 3 ans, par Intello (GER) et Sosia (GER), 3
601 4 Stormy Pouss, 3 ans, par Stormy River et Poussette, 4
482 1 Divertissement IRE, 3 ans, par Shalaa IRE et Truth (IRE), 5
5 partants ; 17 eng. ; 5 part def. – Total des entrées : 2 336 a
"""


def target(**overrides):
    row = {
        "target_key": "france:2026:france-bango:flat",
        "series_key": "france-bango",
        "year": 2026,
        "country_region": "france",
        "discipline": "flat",
        "surface": "turf",
        "grade_text": "G3",
        "canonical_name_original": "Bango",
        "original_name": "Bango (R)",
        "racecourse": "Saint-Cloud",
        "distance_text": "2500",
        "source_scope": "international_cataloguing_standards_aqps",
    }
    row.update(overrides)
    return row


class FranceGalopBulletinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def test_index_uses_linked_regular_pdfs_and_never_guesses(self):
        html = """
        <a href="/sites/default/files/2026-04/26plat06.pdf">N°6</a>
        <a href="https://www.france-galop.com/sites/default/files/2026-05/26plat07_0.pdf">N°7</a>
        <a href="/sites/default/files/2026-05/26plat07_0.pdf">duplicate</a>
        <a href="/sites/default/files/2026-03/26plat03bis.pdf">code update</a>
        <a href="/sites/default/files/2026-04/26obst06.pdf">obstacle</a>
        <a href="/sites/default/files/2025-04/25plat06.pdf">prior year</a>
        <a href="http://www.france-galop.com/sites/default/files/2026-06/26plat08.pdf">http</a>
        """

        rows = self.module.discover_bulletin_urls(html, year=2026, discipline="flat")

        self.assertEqual([row["issue"] for row in rows], [6, 7, 8])
        self.assertEqual(rows[1]["filename"], "26plat07_0.pdf")
        self.assertEqual(rows[2]["url"].split(":", 1)[0], "https")

    def test_index_accepts_linked_four_digit_year_and_numeric_revision_suffix(self):
        html = """
        <a href="/sites/default/files/2024-02/2024plat01.pdf">N°1</a>
        <a href="/sites/default/files/2022-07/22plat11_0_1.pdf">N°11</a>
        <a href="/sites/default/files/2023-09/23plat_17_0.pdf">N°17</a>
        """

        self.assertEqual(
            [
                row["filename"]
                for row in self.module.discover_bulletin_urls(
                    html, year=2024, discipline="flat"
                )
            ],
            ["2024plat01.pdf"],
        )
        self.assertEqual(
            self.module.discover_bulletin_urls(
                html, year=2022, discipline="flat"
            )[0]["issue"],
            11,
        )
        self.assertEqual(
            self.module.discover_bulletin_urls(
                html, year=2023, discipline="flat"
            )[0]["issue"],
            17,
        )

    def test_result_parser_keeps_dash_starter_and_excludes_veterinary_nonstarter(self):
        parsed = self.module.parse_targeted_results(
            [{"page_number": 77, "column": "right", "text": BANGO_TEXT}],
            targets=[target()],
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["local_date"], "2026-03-24")
        self.assertEqual(parsed[0]["actual_starter_count"], 3)
        self.assertEqual(parsed[0]["winner"]["horse_name"], "Louisa Banbou")
        self.assertEqual(parsed[0]["starters"][2]["horse_name"], "Mourir D’Envie")
        self.assertIsNone(parsed[0]["starters"][2]["finish_position"])
        self.assertEqual(parsed[0]["starters"][2]["finish_status"], "–")
        self.assertNotIn(
            "L’Or Monseignor", [row["horse_name"] for row in parsed[0]["starters"]]
        )

    def test_result_parser_accepts_obstacle_discipline_before_groupe(self):
        obstacle_text = BANGO_TEXT.replace(
            "(Groupe III AQPS - AQPS, inscrits au stud-book)",
            "(Steeple-Chase - Groupe III)",
        )
        parsed = self.module.parse_targeted_results(
            [{"page_number": 77, "column": "right", "text": obstacle_text}],
            targets=[target(discipline="jumps")],
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["normalized_grade"], "G3")

    def test_result_parser_accepts_older_age_only_flat_starter_rows(self):
        parsed = self.module.parse_targeted_results(
            [{"page_number": 12, "column": "right", "text": PENELOPE_TEXT}],
            targets=[
                target(
                    target_key="france:2021:france-penelope:flat",
                    series_key="france-penelope",
                    year=2021,
                    canonical_name_original="Penelope",
                    original_name="Prix Penelope",
                    distance_text="2100",
                )
            ],
        )

        self.assertEqual(parsed[0]["actual_starter_count"], 5)
        self.assertEqual(parsed[0]["winner"]["horse_name"], "Philomene (IRE)")
        self.assertEqual(parsed[0]["winner"]["sex_code"], "")
        self.assertEqual(parsed[0]["starters"][-1]["horse_name"], "Divertissement IRE")

    def test_result_parser_fails_closed_when_partants_count_does_not_conserve(self):
        drifted = BANGO_TEXT.replace("3 partants", "4 partants")

        with self.assertRaisesRegex(ValueError, "starter conservation failed"):
            self.module.parse_targeted_results(
                [{"page_number": 77, "column": "right", "text": drifted}],
                targets=[target()],
            )

    def test_exact_race_name_wins_over_a_longer_subset_target(self):
        parsed = self.module.parse_targeted_results(
            [{"page_number": 77, "column": "right", "text": BANGO_TEXT}],
            targets=[
                target(),
                target(
                    target_key="france:2026:france-bango-extension:flat",
                    series_key="france-bango-extension",
                    canonical_name_original="Bango Extension",
                ),
            ],
        )

        self.assertEqual(parsed[0]["target_key"], "france:2026:france-bango:flat")

    def test_official_result_course_can_override_series_default_without_losing_both_values(self):
        other_course_anchor = target(
            target_key="france:2026:france-other:flat",
            series_key="france-other",
            canonical_name_original="Other",
            racecourse="Saint-Cloud",
        )
        parsed = self.module.parse_targeted_results(
            [{"page_number": 77, "column": "right", "text": BANGO_TEXT}],
            targets=[target(racecourse="Fontainebleau"), other_course_anchor],
        )

        self.assertEqual(parsed[0]["racecourse"], "Saint-Cloud")
        self.assertEqual(parsed[0]["target_racecourse"], "Fontainebleau")
        self.assertEqual(
            parsed[0]["racecourse_relation"],
            "official_result_overrides_target_default",
        )

    def test_course_variant_uses_official_source_punctuation_deterministically(self):
        other_variant = target(
            target_key="france:2026:france-other:flat",
            series_key="france-other",
            canonical_name_original="Other",
            racecourse="Saint Cloud",
        )

        parsed = self.module.parse_targeted_results(
            [{"page_number": 77, "column": "right", "text": BANGO_TEXT}],
            targets=[other_variant, target(racecourse="Saint-Cloud")],
        )

        self.assertEqual(parsed[0]["racecourse"], "Saint-Cloud")

    def test_country_suffix_is_removed_only_for_search_variant(self):
        parsed = self.module._parse_starter_line(
            "123 4 Example Horse (IRE), f, 4 ans, 57 k 1", source_order=1
        )

        self.assertEqual(parsed["horse_name"], "Example Horse (IRE)")
        self.assertEqual(parsed["horse_name_search"], "Example Horse")

    def test_four_digit_form_prefix_is_not_part_of_horse_name(self):
        parsed = self.module._parse_starter_line(
            "1571 3 Mabriska, f, 4 ans, 62 k 1", source_order=1
        )

        self.assertEqual(parsed["horse_name"], "Mabriska")

    def test_wrapped_weight_owner_line_is_not_parsed_as_horse_named_k(self):
        self.assertIsNone(
            self.module._parse_starter_line(
                "57 k, h, Gousserie Racing (M. Barzalona), R. Fradet (s) –",
                source_order=2,
            )
        )
        self.assertIsNone(
            self.module._parse_starter_line(
                "(691/2 k), h, F&O Hinderze Racing (C. Lefèbvre),",
                source_order=2,
            )
        )
        self.assertIsNone(
            self.module._parse_starter_line(
                "57 k (571/2 k), h, Wertheimer & Frere, C. Ferland (s) –",
                source_order=2,
            )
        )

    def test_persistent_404_evidence_is_reusable_without_another_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "26plat05.pdf.fetch-error.json"
            url = "https://www.france-galop.com/sites/default/files/2026-04/26plat05.pdf"
            written = self.module._write_persistent_fetch_error(
                path, source_url=url, http_status=404, reason="Not Found"
            )
            loaded = self.module._load_persistent_fetch_error(path, source_url=url)

        self.assertEqual(loaded, written)
        self.assertEqual(loaded["http_status"], 404)

    def test_only_page_header_or_standalone_meeting_date_changes_context(self):
        self.assertEqual(
            self.module._date_context_from_line("mardi 24 mars 2026").isoformat(),
            "2026-03-24",
        )
        self.assertEqual(
            self.module._date_context_from_line("–––– 25 mars 2026 ––––").isoformat(),
            "2026-03-25",
        )
        self.assertIsNone(
            self.module._date_context_from_line(
                "Les chevaux ayant depuis le 1er juillet 2025 inclus gagné un Groupe"
            )
        )
        self.assertIsNone(self.module._date_context_from_line("31 février 2026"))

    def test_verified_pdf_and_persistent_404_can_be_reused_without_network(self):
        index_html = """
        <a href="/sites/default/files/2026-04/26plat06.pdf">N°6</a>
        <a href="/sites/default/files/2026-05/26plat07.pdf">N°7</a>
        """
        url6 = "https://www.france-galop.com/sites/default/files/2026-04/26plat06.pdf"
        url7 = "https://www.france-galop.com/sites/default/files/2026-05/26plat07.pdf"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "destination"
            self.module.write_source_cache(
                source / "bulletin-index.html",
                index_html.encode(),
                source_url=self.module.INDEX_URL,
            )
            self.module.write_source_cache(
                source / "26plat06.pdf", b"frozen-pdf", source_url=url6
            )
            self.module._write_persistent_fetch_error(
                source / "26plat07.pdf.fetch-error.json",
                source_url=url7,
                http_status=404,
                reason="Not Found",
            )

            self.module._reuse_frozen_sources(
                reuse_source_dir=source,
                destination_source_dir=destination,
                year=2026,
                discipline="flat",
            )

            self.assertEqual((destination / "26plat06.pdf").read_bytes(), b"frozen-pdf")
            self.assertEqual(
                self.module._load_persistent_fetch_error(
                    destination / "26plat07.pdf.fetch-error.json", source_url=url7
                )["http_status"],
                404,
            )


if __name__ == "__main__":
    unittest.main()
