from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_graded_winner_targeted_seeds.py")
SPEC = importlib.util.spec_from_file_location("graded_winner_targeted_seeds", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GradedWinnerTargetedSeedsTests(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(MODULE.canonical_json(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def target(self, key: str, *, region: str, series: str, year: int) -> dict:
        return {
            "schema_version": "graded-horse-target-ledger.v1",
            "target_key": key,
            "country_region": region,
            "country": region,
            "series_key": series,
            "year": year,
            "original_name": series,
            "canonical_name_original": series,
            "racecourse": "Course",
            "grade_text": "G1",
            "discipline": "flat",
            "local_date": "",
        }

    def fixture(self, root: Path) -> tuple[Path, str, Path, dict[str, str]]:
        target_path = root / "targets.jsonl"
        targets = [
            self.target(
                "united_states:2020:united-states-split:flat",
                region="united_states",
                series="united-states-split",
                year=2020,
            ),
            self.target(
                "france:2020:france-known:flat",
                region="france",
                series="france-known",
                year=2020,
            ),
            self.target(
                "ireland:2020:ireland-missing:flat",
                region="ireland",
                series="ireland-missing",
                year=2020,
            ),
        ]
        self.write_jsonl(target_path, targets)

        toba_path = root / "toba.jsonl"
        toba_rows = []
        for suffix, winner in (("a", "Winner A"), ("b", "Winner B")):
            toba_rows.append(
                {
                    "adapter_key": "toba",
                    "calendar_source_provider": "toba",
                    "calendar_source_url": "https://toba.example/history/",
                    "target_key": targets[0]["target_key"],
                    "occurrence_key": f"split-{suffix}",
                    "anchor_horse_name": winner,
                    "local_date": "2020-05-01",
                    "race_name": "Split Stakes",
                    "racecourse": "AAA",
                }
            )
        self.write_jsonl(toba_path, toba_rows)

        history_path = root / "france-history.jsonl"
        self.write_jsonl(
            history_path,
            [
                {
                    "slug": "france-known",
                    "source_url": "https://en.wikipedia.org/wiki/Known",
                    "modules": {
                        "history_winners": {
                            "items": [{"winner_year": 2020, "horse_name": "Known Winner"}]
                        }
                    },
                }
            ],
        )

        plan_root = root / "plan"
        plan_root.mkdir()
        events_path = plan_root / "events.csv"
        with events_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "year",
                    "slug",
                    "series_key",
                    "original_name",
                    "target_count",
                    "target_years",
                    "country_region",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "year": 2020,
                    "slug": "ireland-missing",
                    "series_key": "ireland-missing",
                    "original_name": "Missing",
                    "target_count": 1,
                    "target_years": "2020",
                    "country_region": "ireland",
                }
            )
        manifest = {
            "schema_version": "graded-winner-source-events.v1",
            "status": "PREPARED_NOT_APPROVED",
            "network_requests": 0,
            "database_writes": 0,
            "counts": {"target_occurrences_2005_2025": 3},
            "target_ledger": {
                "path": str(target_path),
                "sha256": MODULE.sha256_path(target_path),
            },
            "toba_bindings": {
                "path": str(toba_path),
                "sha256": MODULE.sha256_path(toba_path),
            },
            "frozen_histories": [
                {
                    "region": "france",
                    "path": str(history_path),
                    "sha256": MODULE.sha256_path(history_path),
                }
            ],
            "outputs": {
                "events.csv": {
                    "path": "events.csv",
                    "sha256": MODULE.sha256_path(events_path),
                }
            },
        }
        plan_manifest = plan_root / "event-manifest.json"
        self.write_json(plan_manifest, manifest)
        plan_sha = MODULE.sha256_path(plan_manifest)
        (plan_root / "PREPARED").write_text(plan_sha + "\n", encoding="ascii")

        capture = root / "capture"
        output = capture / "output"
        sources = output / "sources"
        sources.mkdir(parents=True)
        candidates = output / "france_wikipedia_history_winner_candidates_2026.jsonl"
        candidates.write_text("", encoding="utf-8")
        summary = output / "summary.json"
        self.write_json(
            summary,
            {
                "source": "wikipedia_winners_table",
                "events_requested": 1,
                "events": 0,
                "events_without_history": 1,
                "errors": [],
            },
        )
        review = output / "france_wikipedia_history_winner_review_2026.csv"
        review.write_text("slug\n", encoding="utf-8")
        unmatched = output / "france_wikipedia_history_winner_unmatched_2026.csv"
        unmatched.write_text("slug\nireland-missing\n", encoding="utf-8")
        budget = capture / "request-budget.json"
        self.write_json(
            budget,
            {
                "status": "active",
                "request_count": 1,
                "max_requests": 2,
                "request_interval_seconds": 1.0,
                "requests": [{"method": "GET"}],
            },
        )
        source_manifest = sources / "source_cache_manifest.json"
        self.write_json(source_manifest, {"schema_version": "1.0", "files": {}})
        hashes = {
            "candidates": MODULE.sha256_path(candidates),
            "summary": MODULE.sha256_path(summary),
            "review": MODULE.sha256_path(review),
            "unmatched": MODULE.sha256_path(unmatched),
            "budget": MODULE.sha256_path(budget),
            "sources": MODULE.sha256_path(source_manifest),
        }
        return plan_root, plan_sha, capture, hashes

    def test_preserves_physical_divisions_and_records_missing_anchor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, plan_sha, capture, hashes = self.fixture(root)
            output = root / "artifact"
            result = MODULE.build(
                event_plan_root=plan,
                expected_event_manifest_sha256=plan_sha,
                capture_root=capture,
                capture_hashes=hashes,
                output_dir=output,
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["coverage_status"], "complete_with_gaps")
            self.assertEqual(result["counts"]["target_occurrences"], 3)
            self.assertEqual(result["counts"]["covered_target_occurrences"], 2)
            self.assertEqual(result["counts"]["physical_winner_seeds"], 3)
            self.assertEqual(result["counts"]["duplicate_physical_occurrence_seeds"], 1)
            self.assertEqual(result["counts"]["semantic_gaps"], 1)
            seeds = MODULE._jsonl(output / "targeted-horse-seeds.jsonl", label="seeds")
            self.assertEqual({row["name"] for row in seeds}, {"Winner A", "Winner B", "Known Winner"})
            self.assertTrue(all(row["allow_profile_only_if_target_missing"] for row in seeds))
            self.assertEqual(
                (output / "COMPLETE").read_text().strip(),
                MODULE.sha256_path(output / "seed-ledger-manifest.json"),
            )

    def test_rejects_capture_hash_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, plan_sha, capture, hashes = self.fixture(root)
            hashes["summary"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "capture summary SHA-256 mismatch"):
                MODULE.build(
                    event_plan_root=plan,
                    expected_event_manifest_sha256=plan_sha,
                    capture_root=capture,
                    capture_hashes=hashes,
                    output_dir=root / "artifact",
                )


if __name__ == "__main__":
    unittest.main()
