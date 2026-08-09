from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.research.build_p0_participant_completion_batches import (
    ParticipantBatchBuildError,
    build_participant_completion_batches,
)


def _candidate(
    key: str,
    *,
    region: str,
    actual_starts: int = 1,
    review_status: str = "needs_identity_enrichment",
    source_urls: list[str] | None = None,
) -> dict:
    return {
        "candidate_key": key,
        "horse_name": key.upper(),
        "aliases": [key.upper()],
        "identity_status": review_status,
        "review_status": review_status,
        "mapping_disposition": "blocked",
        "matched_profile_ids": [],
        "identity_keys": [],
        "source_namespace": "hkjc" if region == "hong_kong" else "jra",
        "source_namespaces": ["hkjc" if region == "hong_kong" else "jra"],
        "source_urls": source_urls
        if source_urls is not None
        else [f"https://example.test/{region}/{key}"],
        "event_regions": [region],
        "actual_start_evidence_count": actual_starts,
        "sire_name": "",
        "dam_name": "",
        "birth_year": None,
    }


class ParticipantCompletionBatchBuilderTests(unittest.TestCase):
    def test_builds_stable_single_region_source_bound_batches_and_exclusions(self):
        artifact = {
            "artifact_type": "p0_horse_participant_candidates",
            "schema_version": "p0-horse-participant-candidates.v2",
            "generated_at": "2026-08-09T12:00:00Z",
            "read_only": True,
            "year": 2025,
            "actual_starts_only": True,
            "candidates": [
                _candidate("j-2", region="japan"),
                _candidate("j-1", region="japan"),
                _candidate("j-3", region="japan"),
                _candidate("hk-1", region="hong_kong"),
                _candidate("nonstart", region="japan", actual_starts=0),
                _candidate(
                    "conflict",
                    region="japan",
                    review_status="identity_conflict",
                ),
                _candidate("missing-url", region="japan", source_urls=[]),
                {
                    **_candidate("cross-region", region="japan"),
                    "event_regions": ["japan", "hong_kong"],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "p0_participant_candidates.json"
            source.write_text(
                json.dumps(artifact, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            source_bytes = source.read_bytes()
            source_manifest = root / "manifest.json"
            source_manifest.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_participant_candidate_manifest",
                        "schema_version": "1.1",
                        "read_only": True,
                        "files": {
                            "candidates": {
                                "path": source.name,
                                "size_bytes": len(source_bytes),
                                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                            }
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            first = root / "first"
            second = root / "second"
            first_summary = build_participant_completion_batches(
                source_artifact=source,
                source_manifest=source_manifest,
                output_dir=first,
                regions=("japan", "hong_kong"),
                max_rows_per_batch=2,
                decision_reference="user-approved-five-region-20260809",
            )
            second_summary = build_participant_completion_batches(
                source_artifact=source,
                source_manifest=source_manifest,
                output_dir=second,
                regions=("japan", "hong_kong"),
                max_rows_per_batch=2,
                decision_reference="user-approved-five-region-20260809",
            )

            self.assertEqual(first_summary["candidate_count"], 4)
            self.assertEqual(first_summary["batch_count"], 3)
            self.assertEqual(first_summary["excluded_count"], 4)
            self.assertEqual(
                [row["region"] for row in first_summary["batches"]],
                ["japan", "japan", "hong_kong"],
            )
            for left, right in zip(
                first_summary["batches"], second_summary["batches"], strict=True
            ):
                left_manifest = first / left["path"] / "review_manifest.json"
                right_manifest = second / right["path"] / "review_manifest.json"
                self.assertEqual(
                    hashlib.sha256(left_manifest.read_bytes()).hexdigest(),
                    hashlib.sha256(right_manifest.read_bytes()).hexdigest(),
                )
            first_batch = first / first_summary["batches"][0]["path"]
            with (first_batch / "reviewed_candidates.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["candidate_key"] for row in rows], ["j-1", "j-2"])
            self.assertEqual([row["sample_rank"] for row in rows], ["1", "2"])
            manifest = json.loads(
                (first_batch / "review_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["batch_contract"]["region_counts"], {"japan": 2})
            self.assertEqual(
                manifest["batch_contract"]["source_candidate_artifact"]["sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["batch_contract"]["source_candidate_manifest"]["sha256"],
                hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
            )
            batch_index = json.loads(
                (first / "batch_index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(batch_index["candidate_count"], 4)
            self.assertEqual(batch_index["batch_count"], 3)
            self.assertEqual(
                batch_index["batches"][0]["candidate_keys"], ["j-1", "j-2"]
            )

    def test_rejects_non_actual_start_source_and_nonempty_output(self):
        artifact = {
            "artifact_type": "p0_horse_participant_candidates",
            "schema_version": "p0-horse-participant-candidates.v2",
            "generated_at": "2026-08-09T12:00:00Z",
            "read_only": True,
            "year": 2025,
            "actual_starts_only": False,
            "candidates": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.json"
            source.write_text(json.dumps(artifact), encoding="utf-8")
            source_bytes = source.read_bytes()
            source_manifest = root / "manifest.json"
            source_manifest.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_participant_candidate_manifest",
                        "read_only": True,
                        "files": {
                            "candidates": {
                                "path": source.name,
                                "size_bytes": len(source_bytes),
                                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ParticipantBatchBuildError, "actual_starts_only"
            ):
                build_participant_completion_batches(
                    source_artifact=source,
                    source_manifest=source_manifest,
                    output_dir=root / "output",
                    regions=("japan",),
                    max_rows_per_batch=10,
                    decision_reference="approved",
                )
            output = root / "nonempty"
            output.mkdir()
            (output / "keep").write_text("x", encoding="utf-8")
            artifact["actual_starts_only"] = True
            source.write_text(json.dumps(artifact), encoding="utf-8")
            source_bytes = source.read_bytes()
            source_manifest.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_participant_candidate_manifest",
                        "read_only": True,
                        "files": {
                            "candidates": {
                                "path": source.name,
                                "size_bytes": len(source_bytes),
                                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ParticipantBatchBuildError, "not empty"):
                build_participant_completion_batches(
                    source_artifact=source,
                    source_manifest=source_manifest,
                    output_dir=output,
                    regions=("japan",),
                    max_rows_per_batch=10,
                    decision_reference="approved",
                )


if __name__ == "__main__":
    unittest.main()
