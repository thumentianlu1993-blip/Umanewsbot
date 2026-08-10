from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from stable.services.p0_horse_completion_batch import (
    P0HorseBatchError,
    load_batch_manifest,
    read_approvals_ledger,
)
from stable.services.p0_horse_participant_release import (
    prepare_participant_release_bridge,
)


def _write_json(path: Path, payload: object) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(data)
    return data


def _completed(candidate_key: str, *, verified_at: str, occurrence_url: str) -> dict:
    race = {
        "external_race_id": "race-1",
        "race_name": "Test Stakes",
        "race_date": "2025-01-01",
        "result_status": "won",
        "source_fetched_at": verified_at,
    }
    return {
        "schema_version": "p0-horse-completion.v1",
        "candidate_key": candidate_key,
        "region": "japan",
        "horse_name": "テストホース",
        "external_horse_id": "provider-1",
        "identity": {
            "horse_name": "テストホース",
            "sire_name": "父",
            "dam_name": "母",
            "birth_year": 2022,
            "source_name": "jbis",
            "external_horse_id": "provider-1",
        },
        "failure_reason": [],
        "confidence": 100,
        "basic_profile": {"sex": "牡"},
        "pedigree": {"sire": "父", "dam": "母"},
        "race_records": [race],
        "career_history": {
            "status": "complete",
            "official_or_source_start_count": 1,
            "official_start_count_verified_at": verified_at,
        },
        "source_evidence": [
            {
                "evidence_role": "completion_source",
                "source_name": "jbis",
                "external_horse_id": "provider-1",
                "source_url": "https://example.test/horse/provider-1",
                "fetched_at": verified_at,
            },
            {
                "evidence_role": "reviewed_candidate",
                "source_name": "jra",
                "source_url": occurrence_url,
                "fetched_at": "",
            },
        ],
        "raw_payload": {
            "source": {"fetched_at": verified_at},
            "career": {"official_start_count_verified_at": verified_at},
        },
    }


def _blocked(candidate_key: str) -> dict:
    return {
        "schema_version": "p0-horse-completion.v1",
        "candidate_key": candidate_key,
        "region": "japan",
        "horse_name": "阻断马",
        "failure_reason": ["identity_enrichment_required"],
    }


class ParticipantReleaseBridgeTests(SimpleTestCase):
    def _fixture(self, root: Path) -> dict[str, Path]:
        rows = [
            _completed(
                "observation:event:1:number:1",
                verified_at="2026-08-09T01:00:00Z",
                occurrence_url="https://example.test/race/1",
            ),
            _completed(
                "observation:event:2:number:3",
                verified_at="2026-08-09T02:00:00Z",
                occurrence_url="https://example.test/race/2",
            ),
            _blocked("observation:event:3:number:5"),
        ]
        candidates = root / "p0_horse_completion_candidates.jsonl"
        candidate_bytes = b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
            for row in rows
        )
        candidates.write_bytes(candidate_bytes)
        index = root / "batch_index.json"
        index_payload = {
            "artifact_type": "p0_horse_participant_completion_batch_plan",
            "schema_version": "p0-horse-participant-review-batch.v2",
            "batch_count": 1,
            "candidate_count": 3,
            "decision_reference": "approved-participant-scope",
            "batches": [
                {
                    "path": "batch-0001-japan-0001",
                    "ordinal": 1,
                    "region": "japan",
                    "row_count": 3,
                    "candidate_keys": [row["candidate_key"] for row in rows],
                }
            ],
        }
        index_bytes = _write_json(index, index_payload)
        index_sha = hashlib.sha256(index_bytes).hexdigest()
        review_sha = "a" * 64
        completion = root / "p0_horse_completion_batch_manifest.json"
        completion_payload = {
            "artifact_type": "p0_horse_completion_batch_manifest",
            "schema_version": "p0-horse-completion-batch-manifest.v1",
            "read_only": True,
            "database_writes": 0,
            "generated_at": "2026-08-09T02:00:00Z",
            "files": {
                candidates.name: {
                    "path": candidates.name,
                    "size_bytes": len(candidate_bytes),
                    "sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                }
            },
            "review_manifest_input": {
                "sha256": review_sha,
                "batch_contract": {
                    "batch_membership": {
                        "path": "batch-0001-japan-0001",
                        "ordinal": 1,
                        "index_sha256": index_sha,
                    }
                },
            },
            "summary": {
                "processed_count": 3,
                "complete_candidate_count": 2,
                "blocked_count": 1,
            },
        }
        completion_bytes = _write_json(completion, completion_payload)
        ledger = root / "execution-ledger.json"
        _write_json(
            ledger,
            {
                "artifact_type": "p0_horse_participant_execution_ledger",
                "schema_version": "p0-horse-participant-execution-ledger.v1",
                "batch_index_sha256": index_sha,
                "batch_count": 1,
                "candidate_count": 3,
                "completed": [],
                "active": {
                    "path": "batch-0001-japan-0001",
                    "ordinal": 1,
                    "phase": "prepared",
                    "review_manifest_sha256": review_sha,
                    "completion_manifest_sha256": hashlib.sha256(
                        completion_bytes
                    ).hexdigest(),
                },
            },
        )
        return {
            "index": index,
            "ledger": ledger,
            "completion": completion,
            "candidates": candidates,
        }

    def _prepare(self, root: Path, paths: dict[str, Path]):
        return prepare_participant_release_bridge(
            batch_index_path=paths["index"],
            execution_ledger_path=paths["ledger"],
            completion_manifest_path=paths["completion"],
            candidates_path=paths["candidates"],
            output_dir=root / "bridge",
        )

    def test_deduplicates_provider_identity_and_preserves_occurrences(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._prepare(root, self._fixture(root))
            bridge = root / "bridge"
            combined = [
                json.loads(line)
                for line in (bridge / "artifact/combined_candidates.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            binding = json.loads(
                (bridge / "artifact/participant_source_binding.json").read_text(
                    encoding="utf-8"
                )
            )
            manifest = load_batch_manifest(bridge / "batch_manifest.json")
            ledger = read_approvals_ledger(bridge)

        self.assertEqual(result["occurrence_count"], 3)
        self.assertEqual(result["unique_identity_count"], 1)
        self.assertEqual(result["deduplicated_occurrence_count"], 1)
        self.assertEqual(result["blocked_occurrence_count"], 1)
        self.assertEqual(result["module_review_status"], "pending")
        self.assertEqual(result["database_writes"], 0)
        self.assertEqual(len(combined), 1)
        self.assertEqual(
            combined[0]["candidate_key"], "observation:event:2:number:3"
        )
        self.assertEqual(len(combined[0]["participant_occurrence_keys"]), 2)
        self.assertEqual(binding["result"]["unique_identity_count"], 1)
        self.assertEqual(
            len(binding["result"]["occurrences"][0]["occurrence_evidence"]), 2
        )
        self.assertEqual(len(binding["result"]["blocked"]), 1)
        self.assertEqual(manifest["status"], "approved")
        self.assertEqual(manifest["region_counts"], {"japan": 1})
        self.assertEqual([entry["event"] for entry in ledger], ["batch_approved"])

    def test_rejects_semantic_conflict_inside_provider_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._fixture(root)
            rows = [json.loads(line) for line in paths["candidates"].read_text().splitlines()]
            rows[1]["pedigree"]["sire"] = "不同父系"
            candidate_bytes = b"".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                for row in rows
            )
            paths["candidates"].write_bytes(candidate_bytes)
            completion = json.loads(paths["completion"].read_text())
            completion["files"][paths["candidates"].name].update(
                size_bytes=len(candidate_bytes),
                sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            )
            completion_bytes = _write_json(paths["completion"], completion)
            ledger = json.loads(paths["ledger"].read_text())
            ledger["active"]["completion_manifest_sha256"] = hashlib.sha256(
                completion_bytes
            ).hexdigest()
            _write_json(paths["ledger"], ledger)
            with self.assertRaisesRegex(P0HorseBatchError, "conflicting participant"):
                self._prepare(root, paths)

    def test_rejects_completion_or_ledger_binding_drift(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._fixture(root)
            ledger = json.loads(paths["ledger"].read_text())
            ledger["active"]["completion_manifest_sha256"] = "f" * 64
            _write_json(paths["ledger"], ledger)
            with self.assertRaisesRegex(P0HorseBatchError, "active prepared batch"):
                self._prepare(root, paths)

    def test_rejects_non_sha_active_review_approval(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._fixture(root)
            completion = json.loads(paths["completion"].read_text())
            completion["review_manifest_input"]["sha256"] = "not-a-sha"
            completion_bytes = _write_json(paths["completion"], completion)
            ledger = json.loads(paths["ledger"].read_text())
            ledger["active"].update(
                review_manifest_sha256="not-a-sha",
                completion_manifest_sha256=hashlib.sha256(
                    completion_bytes
                ).hexdigest(),
            )
            _write_json(paths["ledger"], ledger)
            with self.assertRaisesRegex(P0HorseBatchError, "active prepared batch"):
                self._prepare(root, paths)

    def test_rejects_unsupported_contract_schema_versions(self):
        mutations = (
            ("index", lambda payload: payload.update(schema_version="future.v9")),
            (
                "completion",
                lambda payload: payload.update(schema_version="future.v9"),
            ),
            (
                "candidates",
                lambda payload: payload.update(schema_version="future.v9"),
            ),
        )
        for target, mutate in mutations:
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = self._fixture(root)
                if target == "index":
                    payload = json.loads(paths["index"].read_text())
                    mutate(payload)
                    index_bytes = _write_json(paths["index"], payload)
                    index_sha = hashlib.sha256(index_bytes).hexdigest()
                    completion = json.loads(paths["completion"].read_text())
                    completion["review_manifest_input"]["batch_contract"][
                        "batch_membership"
                    ]["index_sha256"] = index_sha
                    completion_bytes = _write_json(paths["completion"], completion)
                    ledger = json.loads(paths["ledger"].read_text())
                    ledger["batch_index_sha256"] = index_sha
                    ledger["active"]["completion_manifest_sha256"] = hashlib.sha256(
                        completion_bytes
                    ).hexdigest()
                    _write_json(paths["ledger"], ledger)
                elif target == "completion":
                    payload = json.loads(paths["completion"].read_text())
                    mutate(payload)
                    completion_bytes = _write_json(paths["completion"], payload)
                    ledger = json.loads(paths["ledger"].read_text())
                    ledger["active"]["completion_manifest_sha256"] = hashlib.sha256(
                        completion_bytes
                    ).hexdigest()
                    _write_json(paths["ledger"], ledger)
                else:
                    rows = [
                        json.loads(line)
                        for line in paths["candidates"].read_text().splitlines()
                    ]
                    mutate(rows[0])
                    candidate_bytes = b"".join(
                        json.dumps(row, ensure_ascii=False, sort_keys=True).encode(
                            "utf-8"
                        )
                        + b"\n"
                        for row in rows
                    )
                    paths["candidates"].write_bytes(candidate_bytes)
                    completion = json.loads(paths["completion"].read_text())
                    completion["files"][paths["candidates"].name].update(
                        size_bytes=len(candidate_bytes),
                        sha256=hashlib.sha256(candidate_bytes).hexdigest(),
                    )
                    completion_bytes = _write_json(paths["completion"], completion)
                    ledger = json.loads(paths["ledger"].read_text())
                    ledger["active"]["completion_manifest_sha256"] = hashlib.sha256(
                        completion_bytes
                    ).hexdigest()
                    _write_json(paths["ledger"], ledger)
                with self.assertRaises(P0HorseBatchError):
                    self._prepare(root, paths)

    def test_rejects_candidate_bytes_not_bound_by_completion_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._fixture(root)
            rows = paths["candidates"].read_bytes()
            paths["candidates"].write_bytes(rows + b"\n")
            with self.assertRaisesRegex(P0HorseBatchError, "do not bind"):
                self._prepare(root, paths)

    def test_rejects_existing_output_instead_of_overwriting(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._fixture(root)
            self._prepare(root, paths)
            with self.assertRaisesRegex(P0HorseBatchError, "already exists"):
                self._prepare(root, paths)

    def test_accepts_active_batch_after_verified_prefix(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._fixture(root)
            index = json.loads(paths["index"].read_text())
            current = index["batches"][0]
            current.update(path="batch-0002-japan-0002", ordinal=2)
            index["batches"] = [
                {
                    "path": "batch-0001-japan-0001",
                    "ordinal": 1,
                    "region": "japan",
                    "row_count": 1,
                    "candidate_keys": ["prior"],
                },
                current,
            ]
            index["batch_count"] = 2
            index["candidate_count"] = 4
            index_bytes = _write_json(paths["index"], index)
            index_sha = hashlib.sha256(index_bytes).hexdigest()
            completion = json.loads(paths["completion"].read_text())
            membership = completion["review_manifest_input"]["batch_contract"][
                "batch_membership"
            ]
            membership.update(
                path="batch-0002-japan-0002", ordinal=2, index_sha256=index_sha
            )
            completion_bytes = _write_json(paths["completion"], completion)
            ledger = json.loads(paths["ledger"].read_text())
            ledger.update(
                batch_index_sha256=index_sha,
                batch_count=2,
                candidate_count=4,
                completed=[
                    {
                        "path": "batch-0001-japan-0001",
                        "ordinal": 1,
                        "review_manifest_sha256": "1" * 64,
                        "completion_manifest_sha256": "2" * 64,
                        "release_evidence_sha256": "3" * 64,
                        "apply_evidence_sha256": "4" * 64,
                        "verifier_evidence_sha256": "5" * 64,
                    }
                ],
            )
            ledger["active"].update(
                path="batch-0002-japan-0002",
                ordinal=2,
                completion_manifest_sha256=hashlib.sha256(
                    completion_bytes
                ).hexdigest(),
            )
            _write_json(paths["ledger"], ledger)
            result = self._prepare(root, paths)

        self.assertEqual(result["occurrence_count"], 3)
        self.assertEqual(result["unique_identity_count"], 1)
