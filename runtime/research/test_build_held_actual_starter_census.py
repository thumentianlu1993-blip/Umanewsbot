#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_held_actual_starter_census.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("held_actual_starter_census", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HeldActualStarterCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def source_occurrence(
        self,
        root: Path,
        *,
        provider: str,
        url: str,
        payload: bytes,
        target_key: str = "united_kingdom:2014:united-kingdom-test:jumps",
        occurrence_key: str = "united_kingdom:2014-04-03:test:1",
        local_date: str = "2014-04-03",
    ) -> dict:
        path = root / f"{provider}.source"
        path.write_bytes(payload)
        return {
            "target_key": target_key,
            "occurrence_key": occurrence_key,
            "series_key": target_key.split(":")[2],
            "edition_year": int(target_key.split(":")[1]),
            "country_region": target_key.split(":")[0],
            "discipline": target_key.split(":")[-1],
            "normalized_grade": "G1",
            "local_date": local_date,
            "race_name": "Test Race",
            "racecourse": "Test Course",
            "calendar_source_url": url,
            "anchor_horse_name": "Winner",
            "actual_starter_names": ["Winner"],
            "source_evidence": {
                "source_provider": provider,
                "source_authority": (
                    "organizer_official" if provider == "france_galop" else "human_reviewed_reference"
                ),
                "source_url": url,
                "cache_path": str(path),
                "sha256": self.module.sha256_path(path),
                "size": path.stat().st_size,
            },
        }

    def test_sporting_life_nonfinishers_are_actual_and_withdrawals_are_excluded(self):
        payload = {
            "props": {
                "pageProps": {
                    "race": {
                        "race_summary": {
                            "name": "Test Race",
                            "race_summary_reference": {"id": 123},
                            "race_stage": "RESULT",
                        },
                        "rides": [
                            {
                                "horse": {"name": "Winner", "horse_reference": {"id": 1}},
                                "finish_position": 1,
                                "cloth_number": 1,
                                "ride_status": "RUNNER",
                            },
                            {
                                "horse": {"name": "Pulled Up", "horse_reference": {"id": 2}},
                                "cloth_number": 2,
                                "ride_description": "pulled up before the last",
                            },
                            {
                                "horse": {"name": "Non Runner", "horse_reference": {"id": 3}},
                                "cloth_number": 3,
                                "ride_status": "NON_RUNNER",
                            },
                        ],
                    }
                }
            }
        }
        raw = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        ).encode()
        with tempfile.TemporaryDirectory() as temporary:
            occurrence = self.source_occurrence(
                Path(temporary),
                provider="sporting_life",
                url="https://www.sportinglife.com/racing/results/2014-04-03/test/123/test-race",
                payload=raw,
            )
            runners, withdrawn, _parser, _source = self.module._parse_reference_occurrence(
                occurrence,
                provider="sporting_life",
            )
        self.assertEqual({row["horse_name"] for row in runners}, {"Winner", "Pulled Up"})
        self.assertEqual(withdrawn, 1)
        self.assertEqual(
            {row["running_status"] for row in runners},
            {"declared", "pulled_up"},
        )

    def test_zeturf_unplaced_runner_is_actual_and_np_is_excluded(self):
        raw = b"""
        <html><head><title>03/04/2014 - Auteuil - Test Race:</title></head><body>
          <table class="table-runners"><tbody>
            <tr data-runner><td class="numero">1</td><td><a class="horse-name" data-runner="h1">Winner</a></td></tr>
            <tr data-runner><td class="numero">2</td><td><a class="horse-name" data-runner="h2">Unplaced</a></td></tr>
            <tr data-runner><td class="numero">3</td><td><a class="horse-name non-partant" data-runner="h3">Withdrawn</a></td></tr>
          </tbody></table>
          <div id="arriveeTab"><table><tbody>
            <tr data-runner><td>1er</td><td>1</td><td><span class="horse-name">Winner</span></td><td></td><td>2/1</td><td>-</td></tr>
          </tbody></table></div>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as temporary:
            occurrence = self.source_occurrence(
                Path(temporary),
                provider="zeturf",
                url="https://www.zeturf.fr/fr/course-du-jour/2014-04-03/R1C2-auteuil-test",
                payload=raw,
            )
            runners, withdrawn, parser, _source = self.module._parse_reference_occurrence(
                occurrence,
                provider="zeturf",
            )
        self.assertEqual({row["horse_name"] for row in runners}, {"Winner", "Unplaced"})
        self.assertEqual(withdrawn, 1)
        self.assertIn("reviewed-url-legacy-payload", parser)

    def test_unknown_semantic_status_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsupported semantic runner status"):
            self.module._filter_semantic_runners(
                [
                    {
                        "source_runner_key": "runner:1:Horse",
                        "horse_name": "Horse",
                        "running_status": "unknown",
                    }
                ]
            )

    def test_france_official_unclassified_finish_is_still_an_actual_starter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occurrence = self.source_occurrence(
                root,
                provider="france_galop",
                url="https://www.france-galop.com/result.pdf",
                payload=b"official result",
                target_key="france:2026:france-test:jumps",
                occurrence_key="france:2026-04-03:test:1",
                local_date="2026-04-03",
            )
            occurrence["country_region"] = "france"
            occurrence["starters"] = [
                {
                    "horse_name": "Winner",
                    "finish_position": 1,
                    "finish_status": "1",
                    "source_order": 1,
                },
                {
                    "horse_name": "Unknown Nonfinish",
                    "finish_position": None,
                    "finish_status": "unknown",
                    "raw_first_line": "Unknown Nonfinish tb\u00e9",
                    "source_order": 2,
                },
                {
                    "horse_name": "Dash Status",
                    "finish_position": None,
                    "finish_status": "\u2013",
                    "source_order": 3,
                },
            ]
            occurrence["actual_starter_count"] = 3
            runners, withdrawn, _parser, _source = self.module._france_starters(occurrence)
        self.assertEqual(withdrawn, 0)
        self.assertEqual([row["running_status"] for row in runners], ["finished", "fell", "actual_starter_result_unclassified"])

    def test_same_name_in_different_occurrences_is_never_merged(self):
        source = {
            "provider": "france_galop",
            "authority": "organizer_official",
            "url": "https://www.france-galop.com/result.pdf",
            "payload_sha256": "a" * 64,
        }
        runner = {
            "source_runner_key": "france_galop_order:1",
            "horse_name": "Repeated Name",
            "running_status": "finished",
            "source_reported_finish_position": "1",
        }
        base = {
            "target_key": "france:2026:france-one:flat",
            "occurrence_key": "france:2026-01-01:one",
            "series_key": "france-one",
            "edition_year": 2026,
            "country_region": "france",
            "discipline": "flat",
            "normalized_grade": "G1",
            "local_date": "2026-01-01",
            "race_name": "One",
            "racecourse": "A",
        }
        other = dict(base)
        other.update(
            {
                "target_key": "france:2026:france-two:flat",
                "occurrence_key": "france:2026-01-02:two",
                "series_key": "france-two",
                "local_date": "2026-01-02",
                "race_name": "Two",
            }
        )
        first = self.module._starter_row(base, runner, source=source, source_order=1)
        second = self.module._starter_row(other, runner, source=source, source_order=1)
        self.assertNotEqual(first["starter_occurrence_key"], second["starter_occurrence_key"])
        self.assertIsNone(first["provider_horse_id"])
        self.assertIsNone(second["provider_horse_id"])

    def test_source_payload_drift_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occurrence = self.source_occurrence(
                root,
                provider="france_galop",
                url="https://www.france-galop.com/result.pdf",
                payload=b"original",
            )
            Path(occurrence["source_evidence"]["cache_path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "payload identity drift"):
                self.module._safe_source(occurrence, provider="france_galop")

    def test_wayback_occurrence_must_match_approval_byte_for_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occurrence = self.source_occurrence(
                root,
                provider="sky_sports",
                url="https://web.archive.org/web/2019id_/https://www.skysports.com/racing/results/full-result/1/test",
                payload=b"archived result",
            )
            occurrence["source_evidence"].pop("source_provider")
            occurrence["source_evidence"].pop("source_authority")
            approved = dict(occurrence)
            approved["race_name"] = "Different"
            with self.assertRaisesRegex(ValueError, "exact approved occurrence"):
                self.module._wayback_starters(
                    occurrence,
                    approved_occurrence=approved,
                    approved_starters=[],
                )


if __name__ == "__main__":
    unittest.main()
