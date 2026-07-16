from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from stable.test_historical_race_detail_runner_v2_contract import _load_tool, _load_v2


INVENTORY_SHA256 = "f" * 64


def _source_url(target_id: str) -> str:
    return f"https://www.zeturf.fr/fr/course-du-jour/2024-01-01/R1C1-target-{target_id}"


def _candidate(
    target_id: str,
    *,
    result_count: int,
    distance_text: str = "1600m",
    source_url: str | None = None,
) -> dict:
    source_url = source_url or _source_url(target_id)
    runners = [
        {
            "horse_number": str(index),
            "horse_name": f"Runner {target_id}-{index}",
            "source_refs": {"primary": source_url},
        }
        for index in range(1, 10)
    ]
    results = [
        {
            "finish_position": index,
            "horse_number": str(index),
            "horse_name": f"Runner {target_id}-{index}",
            "source_refs": {"primary": source_url},
        }
        for index in range(1, result_count + 1)
    ]
    return {
        "year": 2024,
        "slug": f"france-target-{target_id}",
        "source_name": "zeturf",
        "source_url": source_url,
        "modules": {
            "runners": {"is_complete": True, "items": runners},
            "results": {"is_complete": True, "items": results},
        },
        "metadata": {"distance_text": distance_text},
    }


def _write_fixture(
    root: Path,
    *,
    candidate_result_counts: dict[str, int],
    parse_gap_targets: tuple[str, ...] = (),
    candidate_distances: dict[str, str] | None = None,
    candidate_source_urls: dict[str, str] | None = None,
) -> tuple[dict, dict, Path]:
    candidate_distances = candidate_distances or {}
    candidate_source_urls = candidate_source_urls or {}
    target_ids = [*candidate_result_counts, *parse_gap_targets]
    target_sha_by_id = {
        target_id: f"{index:x}" * 64 for index, target_id in enumerate(target_ids, start=1)
    }
    events_path = root / "events.csv"
    fieldnames = [
        "target_id",
        "target_sha256",
        "inventory_artifact_sha256",
        "year",
        "slug",
        "date",
        "course",
        "distance_text",
        "source_refs",
    ]
    with events_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for target_id in target_ids:
            source_url = _source_url(target_id)
            writer.writerow(
                {
                    "target_id": target_id,
                    "target_sha256": target_sha_by_id[target_id],
                    "inventory_artifact_sha256": INVENTORY_SHA256,
                    "year": 2024,
                    "slug": f"france-target-{target_id}",
                    "date": "2024-01-01",
                    "course": "ParisLongchamp",
                    "distance_text": "1600m",
                    "source_refs": json.dumps(
                        {
                            "detail_discovery": {
                                "urls": {
                                    "result_url": {
                                        "url": source_url,
                                        "source_provider": "zeturf",
                                    }
                                }
                            }
                        },
                        separators=(",", ":"),
                    ),
                }
            )

    requests = [
        {
            "target_id": target_id,
            "target_sha256": target_sha_by_id[target_id],
            "region": "france",
            "source_provider": "zeturf",
            "source_name": "zeturf",
            "source_url": _source_url(target_id),
        }
        for target_id in target_ids
    ]
    source_fragment_path = root / "source-fragment.json"
    source_fragment_path.write_text(
        json.dumps({"schema_version": "2.0", "requests": requests}),
        encoding="utf-8",
    )

    candidate_path = root / "parsed-candidates.jsonl"
    candidate_path.write_text(
        "".join(
            json.dumps(
                _candidate(
                    target_id,
                    result_count=result_count,
                    distance_text=candidate_distances.get(target_id, "1600m"),
                    source_url=candidate_source_urls.get(target_id),
                )
            )
            + "\n"
            for target_id, result_count in candidate_result_counts.items()
        ),
        encoding="utf-8",
    )
    parse_gap_path = root / "parse-gaps.json"
    parse_gap_path.write_text(
        json.dumps(
            [
                {
                    "target_id": target_id,
                    "reason": "parse_failed",
                    "source_url": _source_url(target_id),
                    "error": "zeturf offline detail output is incomplete",
                }
                for target_id in parse_gap_targets
            ]
        ),
        encoding="utf-8",
    )

    cache_root = root / "source-cache"
    cache_root.mkdir()
    files = {}
    for target_id, result_count in candidate_result_counts.items():
        if result_count != 9:
            continue
        source = cache_root / f"{target_id}.html"
        source.write_bytes(f"verified source {target_id}".encode())
        files[source.name] = {
            "path": source.name,
            "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_url": _source_url(target_id),
        }
    cache_manifest = cache_root / "source_cache_manifest.json"
    cache_manifest.write_text(
        json.dumps({"schema_version": "1.0", "files": files}),
        encoding="utf-8",
    )

    descriptor = {
        "region": "france",
        "adapter_inputs": {
            "events_csv": str(events_path),
            "source_fragment": str(source_fragment_path),
        },
        "targets": [
            {"target_id": target_id, "target_sha256": target_sha_by_id[target_id]}
            for target_id in target_ids
        ],
        "identities": [],
    }
    parse_artifact = {
        "candidate_jsonl": str(candidate_path),
        "parse_gap_json": str(parse_gap_path),
        "candidate_count": len(candidate_result_counts),
    }
    return descriptor, parse_artifact, cache_manifest


class HistoricalRaceDetailRunnerV2ValidationGapTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = _load_v2()
        cls.adapters = _load_tool("historical_race_detail_adapters.py")

    def test_uk_imperial_distance_rounding_keeps_event_text_and_provenance(self):
        cases = (
            ("2m4f", "2m 4f 0y"),
            ("3m", "2m 7f 213y"),
            ("2m4f", "2m 3f 200y"),
            ("3m1/2f", "3m 97y"),
            ("2m5f+", "2m 5f 26y"),
            ("2m1f", "2m 179y"),
            ("2m", "1m 7f 110y"),
        )
        source_url = "https://www.sportinglife.com/racing/results/fixture"
        for event_distance, parsed_distance in cases:
            with self.subTest(
                event_distance=event_distance,
                parsed_distance=parsed_distance,
            ):
                distance, provenance = self.runner._distance_for_validation(
                    {
                        "country_region": "united_kingdom",
                        "distance_text": event_distance,
                    },
                    {
                        "metadata": {"distance_text": parsed_distance},
                        "source_url": source_url,
                    },
                )

                self.assertEqual(distance, event_distance)
                self.assertEqual(
                    provenance,
                    {
                        "source": "event_csv.distance_text",
                        "original_text": event_distance,
                        "source_url": source_url,
                    },
                )

    def test_uk_imperial_distance_semantic_conflicts_remain_rejected(self):
        cases = (
            ("2m", "2m 2f"),
            ("5f", "2m 5f"),
        )
        for event_distance, parsed_distance in cases:
            with self.subTest(
                event_distance=event_distance,
                parsed_distance=parsed_distance,
            ), self.assertRaisesRegex(
                self.runner.RunnerV2Error,
                "event and parsed metadata distance conflict",
            ):
                self.runner._distance_for_validation(
                    {
                        "country_region": "united_kingdom",
                        "distance_text": event_distance,
                    },
                    {
                        "metadata": {"distance_text": parsed_distance},
                        "source_url": (
                            "https://www.sportinglife.com/racing/results/fixture"
                        ),
                    },
                )

    def test_mixed_shard_yields_one_validated_candidate_and_one_validation_gap(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, parsed, _cache_manifest = _write_fixture(
                root,
                candidate_result_counts={"48497": 9, "48498": 7},
            )

            result = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=root,
            )
            validated = self.adapters.read_candidates(Path(result["validated_candidate_jsonl"]))
            gaps = json.loads(Path(result["validation_gap_json"]).read_text(encoding="utf-8"))

        self.assertEqual(result["validated_count"], 1)
        self.assertEqual(result["validation_gap_count"], 1)
        self.assertEqual(validated[0]["target_id"], "48497")
        self.assertEqual(gaps[0]["target_id"], "48498")
        self.assertEqual(gaps[0]["target_sha256"], "2" * 64)
        self.assertEqual(gaps[0]["reason_code"], "source_result_truncated")
        self.assertEqual(gaps[0]["source_url"], _source_url("48498"))
        self.assertEqual(gaps[0]["error"]["type"], "RunnerV2Error")
        self.assertEqual(len(gaps[0]["error_identity"]["sha256"]), 64)
        self.assertIn("candidate", gaps[0]["evidence_identities"])

    def test_distance_conflict_is_a_candidate_gap_and_does_not_abort_mixed_shard(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, parsed, _cache_manifest = _write_fixture(
                root,
                candidate_result_counts={"48497": 9, "48498": 9},
                candidate_distances={"48498": "1800m"},
            )

            result = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=root,
            )
            validated = self.adapters.read_candidates(Path(result["validated_candidate_jsonl"]))
            gaps = json.loads(Path(result["validation_gap_json"]).read_text(encoding="utf-8"))

        self.assertEqual(result["validated_count"], 1)
        self.assertEqual(result["validation_gap_count"], 1)
        self.assertEqual(validated[0]["target_id"], "48497")
        self.assertEqual(gaps[0]["target_id"], "48498")
        self.assertEqual(gaps[0]["reason_code"], "validation_failed")
        self.assertEqual(gaps[0]["error"]["message"], "event and parsed metadata distance conflict")

    def test_duplicate_source_url_is_a_candidate_gap_and_does_not_abort_mixed_shard(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, parsed, _cache_manifest = _write_fixture(
                root,
                candidate_result_counts={"48497": 9, "48498": 9},
                candidate_source_urls={"48498": _source_url("48497")},
            )

            result = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=root,
            )
            validated = self.adapters.read_candidates(Path(result["validated_candidate_jsonl"]))
            gaps = json.loads(Path(result["validation_gap_json"]).read_text(encoding="utf-8"))

        self.assertEqual(result["validated_count"], 1)
        self.assertEqual(result["validation_gap_count"], 1)
        self.assertEqual(validated[0]["target_id"], "48497")
        self.assertEqual(gaps[0]["target_id"], "48498")
        self.assertEqual(gaps[0]["reason_code"], "validation_failed")
        self.assertEqual(gaps[0]["source_url"], _source_url("48497"))
        self.assertEqual(gaps[0]["error"]["message"], "source URL is reused by more than one target")

    def test_all_gap_shard_validates_successfully_with_zero_validated_candidates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, parsed, _cache_manifest = _write_fixture(
                root,
                candidate_result_counts={"48498": 7, "48499": 6},
            )

            result = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=root,
            )
            validated_body = Path(result["validated_candidate_jsonl"]).read_text(encoding="utf-8")
            gaps = json.loads(Path(result["validation_gap_json"]).read_text(encoding="utf-8"))

        self.assertEqual(result["validated_count"], 0)
        self.assertEqual(result["validation_gap_count"], 2)
        self.assertEqual(validated_body, "")
        self.assertEqual({gap["reason_code"] for gap in gaps}, {"source_result_truncated"})

    def test_package_merges_parse_and_validation_gaps_and_conserves_scope(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, parsed, cache_manifest = _write_fixture(
                root,
                candidate_result_counts={"48497": 9, "48498": 7},
                parse_gap_targets=("48500",),
            )
            validated = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=root,
            )

            result = self.adapters.package_validated_sources(
                descriptor,
                candidate_jsonl=Path(validated["validated_candidate_jsonl"]),
                cache_manifest=cache_manifest,
                parse_gap_json=Path(validated["parse_gap_json"]),
                validation_gap_json=Path(validated["validation_gap_json"]),
                run_root=root,
            )
            manifest = json.loads(Path(result["package_manifest"]).read_text(encoding="utf-8"))

        self.assertEqual(result["scope_count"], 3)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["gap_count"], 2)
        self.assertEqual(result["accounted_count"], 3)
        self.assertEqual({record["target_id"] for record in manifest["records"]}, {48497})
        self.assertEqual({gap["target_id"] for gap in manifest["gaps"]}, {48498, 48500})
        self.assertEqual(
            {gap["reason_code"] for gap in manifest["gaps"]},
            {"source_result_truncated", "parse_failed"},
        )
        self.assertTrue(all(gap["target_sha256"] for gap in manifest["gaps"]))
        self.assertTrue(all(gap["source_url"] for gap in manifest["gaps"]))
        self.assertTrue(all(gap["error_identity"]["sha256"] for gap in manifest["gaps"]))
        self.assertTrue(all(gap["evidence_identities"] for gap in manifest["gaps"]))
        self.assertNotIn("source_exhausted", {gap["reason_code"] for gap in manifest["gaps"]})

    def test_all_gap_package_writes_zero_records_and_full_gap_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, parsed, cache_manifest = _write_fixture(
                root,
                candidate_result_counts={"48498": 7, "48499": 6},
            )
            validated = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=root,
            )

            result = self.adapters.package_validated_sources(
                descriptor,
                candidate_jsonl=Path(validated["validated_candidate_jsonl"]),
                cache_manifest=cache_manifest,
                parse_gap_json=Path(validated["parse_gap_json"]),
                validation_gap_json=Path(validated["validation_gap_json"]),
                run_root=root,
            )
            manifest = json.loads(Path(result["package_manifest"]).read_text(encoding="utf-8"))

        self.assertEqual(result["scope_count"], 2)
        self.assertEqual(result["record_count"], 0)
        self.assertEqual(result["gap_count"], 2)
        self.assertEqual(result["accounted_count"], 2)
        self.assertEqual(manifest["records"], [])
        self.assertEqual(len(manifest["gaps"]), 2)
