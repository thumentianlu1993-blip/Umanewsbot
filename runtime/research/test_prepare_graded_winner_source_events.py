from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_graded_winner_source_events.py")
SPEC = importlib.util.spec_from_file_location("graded_winner_source_events", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target(region: str, year: int, series: str) -> dict:
    return {
        "schema_version": "graded-horse-target-ledger.v1",
        "target_key": f"{region}:{year}:{series}:flat",
        "country_region": region,
        "series_key": series,
        "year": year,
        "discipline": "flat",
        "canonical_name_original": series.replace("-", " ").title(),
    }


class PrepareGradedWinnerSourceEventsTests(unittest.TestCase):
    def test_subtracts_exact_toba_and_history_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            targets = [
                target("united_states", 2005, "us-a"),
                target("france", 2005, "fr-a"),
                target("france", 2006, "fr-a"),
                target("ireland", 2025, "ire-b"),
            ]
            target_sha = write_jsonl(root / "targets.jsonl", targets)
            toba_sha = write_jsonl(
                root / "toba.jsonl",
                [
                    {
                        "adapter_key": "toba",
                        "country_region": "united_states",
                        "target_key": targets[0]["target_key"],
                        "occurrence_key": "us-a-2005-a",
                        "anchor_horse_name": "US Winner",
                    }
                ],
            )
            history_sha = write_jsonl(
                root / "france.jsonl",
                [
                    {
                        "slug": "fr-a",
                        "modules": {
                            "history_winners": {
                                "items": [{"winner_year": 2005, "horse_name": "FR Winner"}]
                            }
                        },
                    }
                ],
            )
            manifest = MODULE.prepare(
                target_ledger=root / "targets.jsonl",
                expected_target_sha256=target_sha,
                toba_bindings=root / "toba.jsonl",
                expected_toba_sha256=toba_sha,
                history_inputs=[f"france={root / 'france.jsonl'}={history_sha}"],
                output_dir=root / "output",
            )
            self.assertEqual(
                manifest["counts"],
                {
                    "target_occurrences_2005_2025": 4,
                    "covered_by_toba": 1,
                    "covered_by_frozen_history": 1,
                    "uncovered_target_occurrences": 2,
                    "source_events": 2,
                    "by_region": {"france": 1, "ireland": 1},
                },
            )
            events = (root / "output" / "events.csv").read_text(encoding="utf-8")
            self.assertIn("fr-a", events)
            self.assertIn("ire-b", events)
            self.assertNotIn("us-a", events)

    def test_rejects_duplicate_history_winner_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target_sha = write_jsonl(root / "targets.jsonl", [target("france", 2005, "fr-a")])
            toba_sha = write_jsonl(root / "toba.jsonl", [])
            history_sha = write_jsonl(
                root / "history.jsonl",
                [
                    {
                        "slug": "fr-a",
                        "modules": {
                            "history_winners": {
                                "items": [
                                    {"winner_year": 2005, "horse_name": "A"},
                                    {"winner_year": 2005, "horse_name": "B"},
                                ]
                            }
                        },
                    }
                ],
            )
            with self.assertRaisesRegex(ValueError, "winner identity drift"):
                MODULE.prepare(
                    target_ledger=root / "targets.jsonl",
                    expected_target_sha256=target_sha,
                    toba_bindings=root / "toba.jsonl",
                    expected_toba_sha256=toba_sha,
                    history_inputs=[f"france={root / 'history.jsonl'}={history_sha}"],
                    output_dir=root / "output",
                )


if __name__ == "__main__":
    unittest.main()
