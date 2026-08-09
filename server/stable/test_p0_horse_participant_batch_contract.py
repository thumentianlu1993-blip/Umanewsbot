from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from stable.services import p0_horse_completion_adapters as adapters


FIELDS = (
    "sample_region",
    "sample_rank",
    "candidate_key",
    "horse_name",
    "aliases",
    "identity_status",
    "review_status",
    "mapping_disposition",
    "matched_profile_ids",
    "identity_keys",
    "source_namespace",
    "source_namespaces",
    "source_urls",
    "event_regions",
    "actual_start_evidence_count",
    "sire_name",
    "dam_name",
    "birth_year",
    "reviewed",
    "review_decision",
    "review_notes",
)


def _candidate(key: str) -> dict:
    return {
        "candidate_key": key,
        "horse_name": key.upper(),
        "aliases": [key.upper()],
        "identity_status": "needs_identity_enrichment",
        "review_status": "needs_identity_enrichment",
        "mapping_disposition": "blocked",
        "matched_profile_ids": [],
        "identity_keys": [],
        "source_namespace": "jra",
        "source_namespaces": ["jra"],
        "source_urls": [f"https://example.test/japan/{key}"],
        "event_regions": ["japan"],
        "actual_start_evidence_count": 1,
        "sire_name": "",
        "dam_name": "",
        "birth_year": None,
    }


def _csv_row(candidate: dict, rank: int) -> dict:
    row = {
        **candidate,
        "sample_region": "japan",
        "sample_rank": rank,
        "reviewed": "True",
        "review_decision": "confirm_batch_inclusion",
        "review_notes": "scope approved; identity remains provider-gated",
    }
    for field in (
        "aliases",
        "matched_profile_ids",
        "identity_keys",
        "source_namespaces",
        "source_urls",
        "event_regions",
    ):
        row[field] = json.dumps(row[field], ensure_ascii=False, sort_keys=True)
    row["birth_year"] = ""
    return row


class ParticipantBatchContractTests(SimpleTestCase):
    def _fixture(self, root: Path, *, source_rows: list[dict] | None = None):
        root.mkdir(parents=True, exist_ok=True)
        candidates = source_rows or [_candidate("j-1"), _candidate("j-2")]
        source = root / "source.json"
        source.write_text(
            json.dumps(
                {
                    "artifact_type": "p0_horse_participant_candidates",
                    "schema_version": "p0-horse-participant-candidates.v2",
                    "read_only": True,
                    "year": 2025,
                    "actual_starts_only": True,
                    "candidates": candidates,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        csv_path = root / "reviewed.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for rank, candidate in enumerate(candidates, start=1):
                writer.writerow(_csv_row(candidate, rank))
        csv_bytes = csv_path.read_bytes()
        source_bytes = source.read_bytes()
        source_manifest = root / "source-manifest.json"
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
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        source_manifest_bytes = source_manifest.read_bytes()
        batch_index = root / "batch-index.json"
        batch_index.write_text(
            json.dumps(
                {
                    "artifact_type": "p0_horse_participant_completion_batch_plan",
                    "schema_version": "p0-horse-participant-review-batch.v2",
                    "year": 2025,
                    "decision_reference": "user-approved-five-region-20260809",
                    "source_candidate_artifact_sha256": hashlib.sha256(
                        source_bytes
                    ).hexdigest(),
                    "source_candidate_manifest_sha256": hashlib.sha256(
                        source_manifest_bytes
                    ).hexdigest(),
                    "candidate_count": len(candidates),
                    "batch_count": 1,
                    "batches": [
                        {
                            "path": root.name,
                            "ordinal": 1,
                            "region": "japan",
                            "row_count": len(candidates),
                            "candidate_keys": [
                                candidate["candidate_key"] for candidate in candidates
                            ],
                            "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
                        }
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        batch_index_bytes = batch_index.read_bytes()
        manifest = {
            "artifact_type": "p0_horse_candidate_review_manifest",
            "decision": "confirm_batch_inclusion",
            "decision_reference": "user-approved-five-region-20260809",
            "row_count": len(candidates),
            "files": {
                csv_path.name: {
                    "path": csv_path.name,
                    "size": len(csv_bytes),
                    "sha256": hashlib.sha256(csv_bytes).hexdigest(),
                }
            },
            "batch_contract": {
                "schema_version": "p0-horse-participant-review-batch.v2",
                "year": 2025,
                "actual_starts_only": True,
                "max_rows_per_region": 100,
                "region_counts": {"japan": len(candidates)},
                "batch_membership": {
                    "path": root.name,
                    "ordinal": 1,
                    "batch_count": 1,
                    "index_path": batch_index.name,
                    "index_size": len(batch_index_bytes),
                    "index_sha256": hashlib.sha256(batch_index_bytes).hexdigest(),
                },
                "source_candidate_artifact": {
                    "path": source.name,
                    "size": len(source_bytes),
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                },
                "source_candidate_manifest": {
                    "path": source_manifest.name,
                    "size": len(source_manifest_bytes),
                    "sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
                },
            },
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return source, csv_path, manifest_path

    def test_v2_contract_accepts_bounded_single_region_batch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, csv_path, manifest_path = self._fixture(root)
            output = root / "output"
            result = adapters.run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=csv_path,
                review_manifest_path=manifest_path,
                cache_dir=root / "cache",
                output_dir=output,
                allow_network=False,
                generated_at="2026-08-09T12:00:00Z",
            )
        self.assertEqual(result["summary"]["processed_count"], 2)
        self.assertEqual(
            result["review_manifest_input"]["batch_contract"]["region_counts"],
            {"japan": 2},
        )

    def test_v2_contract_allows_ancestor_symlink_but_pins_batch_root_dirfd(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            alias = root / "ancestor-alias"
            alias.symlink_to(real_parent, target_is_directory=True)
            batch = alias / "artifact" / "batch-0001-japan-0001"
            _, csv_path, manifest_path = self._fixture(batch)
            result = adapters.run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=csv_path,
                review_manifest_path=manifest_path,
                cache_dir=root / "cache",
                output_dir=root / "output",
                allow_network=False,
            )
        self.assertEqual(result["summary"]["processed_count"], 2)

    def test_v2_contract_rejects_source_drift_and_row_drift(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, csv_path, manifest_path = self._fixture(root)
            source_data = bytearray(source.read_bytes())
            source_data[-2] = ord(" ")
            source.write_bytes(source_data)
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "source candidate artifact SHA-256",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache-a",
                    output_dir=root / "output-a",
                    allow_network=False,
                )

            source, csv_path, manifest_path = self._fixture(root / "fresh")
            rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline="")))
            rows[0]["horse_name"] = "TAMPERED"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            data = csv_path.read_bytes()
            manifest["files"][csv_path.name].update(
                size=len(data), sha256=hashlib.sha256(data).hexdigest()
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "global index entry|does not match source candidate artifact",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache-b",
                    output_dir=root / "output-b",
                    allow_network=False,
                )

    def test_v2_contract_rejects_symlinked_intermediate_source_directory(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact"
            batch = artifact / "batch-0001-japan-0001"
            source, csv_path, manifest_path = self._fixture(batch)
            outside = root / "outside"
            outside.mkdir()
            outside_source = outside / source.name
            source.replace(outside_source)
            (artifact / "linked-source").symlink_to(outside, target_is_directory=True)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["batch_contract"]["source_candidate_artifact"]["path"] = (
                "../linked-source/source.json"
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "parent must be a regular non-symlink directory|is unreadable",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    allow_network=False,
                )

    def test_v2_contract_rejects_symlinked_source_artifact(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, csv_path, manifest_path = self._fixture(root)
            real_source = root / "real-source.json"
            source.replace(real_source)
            source.symlink_to(real_source)
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "regular non-symlink file|is unreadable",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    allow_network=False,
                )

    def test_v2_contract_rejects_source_manifest_drift_and_binding_mismatch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, csv_path, manifest_path = self._fixture(root)
            source_manifest = root / "source-manifest.json"
            source_manifest_data = bytearray(source_manifest.read_bytes())
            source_manifest_data[-1] = ord(" ")
            source_manifest.write_bytes(source_manifest_data)
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "source candidate manifest SHA-256",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache-a",
                    output_dir=root / "output-a",
                    allow_network=False,
                )

            _, csv_path, manifest_path = self._fixture(root / "fresh")
            source_manifest = root / "fresh" / "source-manifest.json"
            source_manifest_payload = json.loads(
                source_manifest.read_text(encoding="utf-8")
            )
            source_manifest_payload["files"]["candidates"]["sha256"] = "0" * 64
            source_manifest.write_text(
                json.dumps(
                    source_manifest_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_manifest_bytes = source_manifest.read_bytes()
            manifest["batch_contract"]["source_candidate_manifest"].update(
                size=len(source_manifest_bytes),
                sha256=hashlib.sha256(source_manifest_bytes).hexdigest(),
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "does not bind the source artifact",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache-b",
                    output_dir=root / "output-b",
                    allow_network=False,
                )

    def test_v2_contract_rejects_symlinked_source_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, csv_path, manifest_path = self._fixture(root)
            source_manifest = root / "source-manifest.json"
            real_manifest = root / "real-source-manifest.json"
            source_manifest.replace(real_manifest)
            source_manifest.symlink_to(real_manifest)
            with self.assertRaisesRegex(
                adapters.P0HorseCompletionBatchError,
                "regular non-symlink file|is unreadable",
            ):
                adapters.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=csv_path,
                    review_manifest_path=manifest_path,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    allow_network=False,
                )
