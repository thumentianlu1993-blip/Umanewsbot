from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("prepare_hri_graded_winner_candidates.py")
SPEC = importlib.util.spec_from_file_location("prepare_hri_graded_winners", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


HTML = b"""
<p class="h3 text-primary"><a>Leopardstown</a></p>
<div class="race-result-item">
  <h2><a href="/results/race-result/?date=2025-02-01&race=1315&venue=LP">
    The Nathaniel Lacy &amp; Partners Solicitors Novice Hurdle (Grade 1)
  </a></h2>
  <table><tbody>
    <tr><td><strong>1st</strong></td><td></td><td>1</td><td>Final Demand (IRE)</td></tr>
    <tr><td><strong>2nd</strong></td><td>12 L</td><td>10</td><td>Wingmen</td></tr>
  </tbody></table>
</div>
"""


class HriOfficialWinnerTests(unittest.TestCase):
    def result(self, race_name, *, result_url):
        return {
            "edition_year": 2025,
            "normalized_grade": "G3",
            "racecourse": "Naas",
            "race_name": race_name,
            "result_url": result_url,
        }

    def target(self, key, name):
        return {
            "target_key": key,
            "series_key": key,
            "year": 2025,
            "country_region": "ireland",
            "grade_text": "G3",
            "racecourse": "Naas",
            "canonical_name_original": name,
            "original_name": name,
            "discipline": "jumps",
        }

    def test_parses_organizer_official_graded_winner(self):
        rows = MODULE.parse_date_page(
            HTML,
            local_date="2025-02-01",
            source_evidence={
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalized_grade"], "G1")
        self.assertEqual(rows[0]["racecourse"], "Leopardstown")
        self.assertEqual(rows[0]["winner"]["horse_name"], "Final Demand")
        self.assertEqual(rows[0]["winner"]["country_suffix"], "IRE")

    def test_venue_code_prevents_multi_meeting_heading_misattribution(self):
        multi_meeting = HTML.replace(
            b'<p class="h3 text-primary"><a>Leopardstown</a></p>',
            b'<div class="inner"><p class="h3"><a>Leopardstown</a></p>'
            b'<p class="h3"><a>Limerick</a></p></div>',
        )

        rows = MODULE.parse_date_page(
            multi_meeting,
            local_date="2025-02-01",
            source_evidence={"source_url": "https://www.hri.ie/results", "sha256": "a" * 64},
            venue_course_map={"LP": "Leopardstown", "LM": "Limerick"},
        )

        self.assertEqual(rows[0]["racecourse"], "Leopardstown")

    def test_venue_map_is_inferred_only_from_unambiguous_single_meeting_pages(self):
        limerick = HTML.replace(b"Leopardstown", b"Limerick").replace(
            b"venue=LP", b"venue=LM"
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            leopardstown_path = root / "leopardstown.html"
            limerick_path = root / "limerick.html"
            leopardstown_path.write_bytes(HTML)
            limerick_path.write_bytes(limerick)

            venue_map = MODULE.infer_venue_course_map(
                [leopardstown_path, limerick_path]
            )

        self.assertEqual(
            venue_map,
            {"LM": "Limerick", "LP": "Leopardstown"},
        )

    def test_global_assignment_prefers_explicit_race_over_generic_collision(self):
        results = [
            self.result(
                "The Michael Purcell Memorial Novice Hurdle (Grade 3)",
                result_url="https://www.hri.ie/results?race=1",
            ),
            self.result(
                "The Bar One Racing Kingsfurze Novice Hurdle (Grade 3)",
                result_url="https://www.hri.ie/results?race=2",
            ),
        ]
        targets = [
            self.target(
                "ireland:2025:ireland-kingsfurze-novice-hurdle:jumps",
                "Kingsfurze Novice Hurdle",
            )
        ]

        matched, unmatched = MODULE.assign_targets_globally(results, targets)

        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][0]["result_url"], results[1]["result_url"])
        self.assertEqual(len(unmatched), 1)

    def test_global_assignment_holds_exact_five_point_group_margin(self):
        results = [
            self.result(
                "Ballylinch Stud Priory Belle 1000 Guineas Trial (Group 3)",
                result_url="https://www.hri.ie/results?race=1",
            ),
            self.result(
                "Irish 1000 Guineas Trial (Group 3)",
                result_url="https://www.hri.ie/results?race=2",
            ),
        ]
        targets = [
            self.target(
                "ireland:2025:derrinstown:flat",
                "Derrinstown Stud 1000 Guineas Trial",
            ),
            self.target(
                "ireland:2025:leopardstown:flat",
                "Leopardstown 1000 Guineas Trial",
            ),
        ]

        matched, unmatched = MODULE.assign_targets_globally(results, targets)

        self.assertEqual(matched, [])
        self.assertEqual(len(unmatched), 2)

    def test_global_assignment_resolves_distinct_sponsor_aliases(self):
        results = [
            self.result(
                "The KPMG Champion Novice Hurdle (Grade 3)",
                result_url="https://www.hri.ie/results?race=1",
            ),
            self.result(
                "The Alanna Homes Champion Novice Hurdle (Grade 3)",
                result_url="https://www.hri.ie/results?race=2",
            ),
        ]
        champion = self.target(
            "ireland:2025:champion:jumps", "Champion Novice Hurdle"
        )
        champion["original_name"] = "Champion Novice Hurdle[KPMG]"
        tickell = self.target(
            "ireland:2025:tickell:jumps", "Tickell Novice Hurdle"
        )
        tickell["original_name"] = "Tickell Novice Hurdle[Alanna Homes]"

        matched, unmatched = MODULE.assign_targets_globally(
            results, [champion, tickell]
        )

        self.assertEqual(len(matched), 2)
        self.assertEqual(unmatched, [])
        by_result = {
            result["result_url"]: target["target_key"]
            for result, target, _diagnostics in matched
        }
        self.assertEqual(
            by_result[results[0]["result_url"]], champion["target_key"]
        )
        self.assertEqual(by_result[results[1]["result_url"]], tickell["target_key"])

    def test_global_assignment_holds_an_equal_score_ambiguity(self):
        result = self.result(
            "Example Novice Hurdle (Grade 3)",
            result_url="https://www.hri.ie/results?race=1",
        )
        targets = [
            self.target("ireland:2025:example-a:jumps", "Example Novice Hurdle"),
            self.target("ireland:2025:example-b:jumps", "Example Novice Hurdle"),
        ]

        matched, unmatched = MODULE.assign_targets_globally([result], targets)

        self.assertEqual(matched, [])
        self.assertEqual(len(unmatched), 1)

    def test_global_assignment_keeps_independent_clear_edge(self):
        results = [
            self.result(
                "The Clear Identity Stakes (Grade 3)",
                result_url="https://www.hri.ie/results?race=clear",
            ),
            self.result(
                "Example Novice Hurdle (Grade 3)",
                result_url="https://www.hri.ie/results?race=ambiguous",
            ),
        ]
        targets = [
            self.target("ireland:2025:clear:jumps", "Clear Identity Stakes"),
            self.target("ireland:2025:example-a:jumps", "Example Novice Hurdle"),
            self.target("ireland:2025:example-b:jumps", "Example Novice Hurdle"),
        ]

        matched, unmatched = MODULE.assign_targets_globally(results, targets)

        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][0]["result_url"], results[0]["result_url"])
        self.assertEqual(len(unmatched), 1)

    def test_matches_sponsored_hri_title_to_registered_target(self):
        result = MODULE.parse_date_page(
            HTML,
            local_date="2025-02-01",
            source_evidence={
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        )[0]
        target = {
            "target_key": "ireland:2025:ireland-golden-cygnet-novice-hurdle:jumps",
            "series_key": "ireland-golden-cygnet-novice-hurdle",
            "year": 2025,
            "country_region": "ireland",
            "grade_text": "G1",
            "racecourse": "Leopardstown",
            "canonical_name_original": "Golden Cygnet Novice Hurdle",
            "original_name": "Golden Cygnet Novice Hurdle [Nathaniel Lacy & Partners]",
        }

        matched, diagnostics = MODULE.match_target(result, [target])

        self.assertEqual(matched["target_key"], target["target_key"])
        self.assertGreaterEqual(diagnostics[0]["overlap"], 4)

    def test_rejects_same_grade_and_name_at_wrong_course(self):
        result = MODULE.parse_date_page(
            HTML,
            local_date="2025-02-01",
            source_evidence={
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        )[0]
        target = {
            "target_key": "ireland:2025:wrong:jumps",
            "year": 2025,
            "country_region": "ireland",
            "grade_text": "G1",
            "racecourse": "Fairyhouse",
            "canonical_name_original": "Nathaniel Lacy Novice Hurdle",
            "original_name": "Nathaniel Lacy Novice Hurdle",
        }

        matched, diagnostics = MODULE.match_target(result, [target])

        self.assertIsNone(matched)
        self.assertEqual(diagnostics, [])

    def test_records_retryable_unavailable_date_without_treating_it_as_no_race(self):
        target_identity = {
            "root": "/frozen/targets",
            "manifest_sha256": "a" * 64,
        }
        args = type(
            "Args",
            (),
            {
                "output_dir": None,
                "start_date": "2021-01-04",
                "end_date": "2021-01-04",
                "max_requests": 1,
                "target_root": Path("/frozen/targets"),
                "allow_network": True,
                "timeout_seconds": 30,
                "request_interval_seconds": 1.25,
            },
        )()
        with TemporaryDirectory() as temporary:
            args.output_dir = temporary
            with (
                patch.object(MODULE, "load_target_artifact", return_value=([], target_identity)),
                patch.object(
                    MODULE,
                    "_download",
                    side_effect=HTTPError("https://www.hri.ie/results", 500, "error", {}, None),
                ),
                patch.object(MODULE, "sha256_path", return_value="b" * 64),
            ):
                manifest = MODULE.prepare(args)

            self.assertEqual(manifest["counts"]["date_pages_unavailable"], 1)
            row = (Path(temporary) / "hri-result-date-fetch-errors.jsonl").read_text()
            self.assertIn("source_unavailable_not_evidence_of_no_race", row)
            evidence = (
                Path(temporary)
                / "sources"
                / "hri-results-2021-01-04.fetch-error.json"
            )
            self.assertTrue(evidence.is_file())

    def test_replay_uses_persistent_fetch_error_without_another_request(self):
        target_identity = {
            "root": "/frozen/targets",
            "manifest_sha256": "a" * 64,
        }
        args = type(
            "Args",
            (),
            {
                "output_dir": None,
                "start_date": "2021-01-04",
                "end_date": "2021-01-04",
                "max_requests": 1,
                "target_root": Path("/frozen/targets"),
                "allow_network": True,
                "timeout_seconds": 30,
                "request_interval_seconds": 1.25,
            },
        )()
        with TemporaryDirectory() as temporary:
            args.output_dir = temporary
            source_dir = Path(temporary) / "sources"
            source_dir.mkdir()
            MODULE._write_fetch_error(
                MODULE._fetch_error_path(source_dir, MODULE.date(2021, 1, 4)),
                local_date="2021-01-04",
                source_url="https://www.hri.ie/results?date=2021-01-04",
                http_status=500,
                reason="error",
            )
            with (
                patch.object(MODULE, "load_target_artifact", return_value=([], target_identity)),
                patch.object(MODULE, "_download") as download,
                patch.object(MODULE, "sha256_path", return_value="b" * 64),
            ):
                manifest = MODULE.prepare(args)

            download.assert_not_called()
            self.assertEqual(manifest["counts"]["date_pages_unavailable"], 1)


if __name__ == "__main__":
    unittest.main()
