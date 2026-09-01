#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("audit_france_galop_bulletin_occurrences.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("audit_france_galop_bulletins", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_horse_export():
    path = Path(__file__).with_name("racing_api_horse_export.py")
    spec = importlib.util.spec_from_file_location("racing_api_horse_export_for_fg", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def occurrence(*, target_key: str = "france:2026:france-bango:flat") -> dict:
    return {
        "target_key": target_key,
        "occurrence_key": "france:2026-03-24:france_galop:825:249",
        "anchor_horse_name": "Winner Horse (FR)",
        "local_date": "2026-03-24",
        "race_name": "PRIX BANGO",
        "racecourse": "Saint Cloud",
        "normalized_grade": "G3",
        "source_evidence": {
            "source_url": "https://www.france-galop.com/sites/default/files/2026-04/26plat06.pdf",
            "sha256": "a" * 64,
        },
        "starters": [
            {
                "horse_name": "Winner Horse (FR)",
                "finish_position": 1,
            },
            {"horse_name": "Second Horse", "finish_position": 2},
        ],
    }


def target(*, target_key: str = "france:2026:france-bango:flat") -> dict:
    return {
        "target_key": target_key,
        "year": 2026,
        "country_region": "france",
        "discipline": "flat",
        "canonical_name_original": "Bango",
        "original_name": "Bango (R)",
        "racecourse": "Saint-Cloud",
        "grade_text": "G3",
    }


class FranceGalopBulletinAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()
        cls.horse_export = load_horse_export()

    def test_winner_anchor_seed_matches_existing_targeted_export_contract(self):
        row = self.module.build_targeted_seed_proposals(
            [occurrence()],
            targets_by_key={"france:2026:france-bango:flat": target()},
        )[0]

        self.assertEqual(row["schema_version"], "targeted-horse-seed.v2")
        self.assertEqual(row["name"], "Winner Horse")
        self.assertEqual(row["country_suffix"], "FR")
        self.assertEqual(row["expected_finish_position"], "1")
        self.assertEqual(row["source_authority"], "organizer_official")
        self.assertTrue(row["allow_profile_only_if_target_missing"])
        self.assertEqual(
            row["target"]["target_key"], "france:2026:france-bango:flat"
        )
        self.assertIn("PRIX BANGO", row["target"]["race_name_aliases"])
        self.assertIn("Saint Cloud", row["target"]["racecourse_aliases"])

    def test_seed_generation_requires_one_winner_in_source_occurrence(self):
        row = occurrence()
        row["starters"][0]["finish_position"] = None

        with self.assertRaisesRegex(ValueError, "exactly one winner"):
            self.module.build_targeted_seed_proposals(
                [row], targets_by_key={row["target_key"]: target()}
            )

    def test_duplicate_target_occurrence_is_rejected(self):
        row = occurrence()

        with self.assertRaisesRegex(ValueError, "missing or duplicated"):
            self.module.build_targeted_seed_proposals(
                [row, dict(row)], targets_by_key={row["target_key"]: target()}
            )

    def test_seed_uses_per_horse_results_not_twelve_month_bulk_endpoint(self):
        seed = self.module.build_targeted_seed_proposals(
            [occurrence()],
            targets_by_key={"france:2026:france-bango:flat": target()},
        )[0]

        class FakeClient:
            def __init__(self):
                self.urls = []

            def request_json(self, url, *, allow_not_found=False):
                self.urls.append(url)
                if "/horses/search?" in url:
                    return {
                        "search_results": [
                            {"id": "hrs_louisa", "name": "Winner Horse (FR)"}
                        ]
                    }
                if url.endswith("/pro"):
                    return {
                        "id": "hrs_louisa",
                        "name": "Winner Horse (FR)",
                        "dob": "2021-03-01",
                        "sex": "mare",
                        "sex_code": "M",
                    }
                return {
                    "results": [
                        {
                            "race_id": "rac_bango_2026",
                            "date": "2026-03-24",
                            "region": "FR",
                            "course": "Saint-Cloud",
                            "course_id": "crs_saint_cloud",
                            "race_name": "PRIX BANGO",
                            "type": "Flat",
                            "pattern": "G3",
                            "runners": [
                                {
                                    "horse_id": "hrs_louisa",
                                    "horse": "Winner Horse (FR)",
                                    "position": "1",
                                },
                                {
                                    "horse_id": "hrs_second",
                                    "horse": "Second Horse (FR)",
                                    "position": "2",
                                },
                                {
                                    "horse_id": "hrs_withdrawn",
                                    "horse": "Withdrawn Horse (FR)",
                                    "position": "NR",
                                },
                            ],
                        }
                    ],
                    "total": 1,
                    "limit": 100,
                    "skip": 0,
                    "query": [],
                }

        client = FakeClient()
        exported = self.horse_export.run_targeted_seed(
            seed,
            client=client,
            max_search_candidates=2,
            max_results_pages_per_horse=2,
            max_parent_profiles=0,
        )

        self.assertEqual(exported["horse_id"], "hrs_louisa")
        self.assertEqual(len(exported["target_race"]["actual_starters"]), 2)
        self.assertTrue(any("/horses/hrs_louisa/results?" in url for url in client.urls))
        self.assertFalse(any("/v1/results?" in url for url in client.urls))


if __name__ == "__main__":
    unittest.main()
