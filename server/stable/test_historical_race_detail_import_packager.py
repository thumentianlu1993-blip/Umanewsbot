from __future__ import annotations

import csv
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime/tools/package_historical_race_detail_import_candidates.py"
)


def load_tool():
    tools_path = str(TOOL_PATH.parent)
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)
    spec = importlib.util.spec_from_file_location("historical_detail_import_packager", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def identity(path: Path, *, relative_to: Path | None = None) -> dict:
    raw = path.read_bytes()
    rendered_path = path.relative_to(relative_to).as_posix() if relative_to else str(path)
    return {
        "path": rendered_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(canonical_bytes(row) for row in rows))


class ArtifactBuilder:
    source_plan_sha = "a" * 64
    approved_inventory_sha = "b" * 64
    cutoff = "2026-07-15"

    def __init__(self, root: Path):
        self.root = root
        self.v6 = root / "detail-v6"
        self.v9 = root / "remaining-v9"
        self.due = root / "due"
        self.records: list[dict] = []
        self.gaps: list[dict] = []
        self.targets: list[dict] = []
        self.due_rows: list[dict] = []
        self.request_rows: list[dict] = []
        self.omitted_package_target_ids: set[int] = set()

    def add_record(
        self,
        target_id: int,
        year: int,
        *,
        trace_calendar: bool = True,
        detail_url_has_date: bool = False,
        fragment_local_date: str | None = None,
        recovery_candidate_has_date: bool = False,
        primary_cache_matches: bool = True,
        ambiguous_primary_cache: bool = False,
    ) -> dict:
        target_sha = f"{target_id:064x}"
        local_date = "2026-01-02" if year == 2026 else "2024-01-02"
        if detail_url_has_date:
            source_url = f"https://results.example.test/racing/results/{local_date}/{target_id}"
        else:
            source_url = f"https://results.example.test/races/{target_id}"
        calendar_url = source_url if trace_calendar else f"https://calendar.example.test/{year}.pdf"
        cache_raw = f"race-{target_id}".encode()
        cache_name = f"{target_id:064x}.html"
        cache_identity = {
            "path": cache_name,
            "sha256": hashlib.sha256(cache_raw).hexdigest(),
            "size": len(cache_raw),
            "source_url": (
                source_url
                if primary_cache_matches
                else f"https://results.example.test/other/{target_id}"
            ),
            "cached_at": "2026-07-16T00:00:00Z",
            "protected_by": ["test-fixture"],
        }
        modules = {
            "runners": {
                "is_complete": True,
                "items": [{"horse_name": f"Horse {target_id}", "horse_number": "1"}],
                "source_cache_identity": cache_identity,
            },
            "results": {
                "is_complete": True,
                "items": [
                    {
                        "horse_name": f"Horse {target_id}",
                        "horse_number": "1",
                        "finish_position": 1,
                    }
                ],
                "source_cache_identity": cache_identity,
            },
        }
        record = {
            "target_id": target_id,
            "target_sha256": target_sha,
            "inventory_artifact_sha256": self.source_plan_sha,
            "source_name": "official_result",
            "source_url": source_url,
            "distance_text": "1600m",
            "distance_provenance": {
                "source": "parsed.metadata.distance_text",
                "source_url": source_url,
                "original_text": "1600m",
            },
            "modules": modules,
            "_cache_raw": cache_raw,
            "_calendar_url": calendar_url,
            "_fragment_local_date": fragment_local_date or local_date,
            "_recovery_candidate_has_date": recovery_candidate_has_date,
            "_extra_caches": [],
        }
        if ambiguous_primary_cache:
            extra_raw = f"race-{target_id}-duplicate".encode()
            extra_identity = {
                "path": f"{target_id:064x}-duplicate.html",
                "sha256": hashlib.sha256(extra_raw).hexdigest(),
                "size": len(extra_raw),
                "source_url": source_url,
                "cached_at": "2026-07-16T00:00:01Z",
                "protected_by": ["test-fixture"],
            }
            record["modules"]["metadata"] = {
                "source_cache_identity": extra_identity,
            }
            record["_extra_caches"].append((extra_identity, extra_raw))
        self.records.append(record)
        self.targets.append(
            {
                "target_id": target_id,
                "target_sha256": target_sha,
                "inventory_artifact_sha256": self.approved_inventory_sha,
                "year": year,
                "series_key": f"series-{target_id}",
                "country_region": "japan",
                "original_name": f"Race {target_id}",
                "chinese_name": "测试赛",
                "racecourse": "Tokyo",
                "grade_text": "G1",
                "expectation_status": "held",
                "resolution_status": "pending",
                "work_state": "current_year_due_check" if year == 2026 else "crawl",
            }
        )
        if year == 2026:
            self.due_rows.append(
                {
                    "target_id": target_id,
                    "target_sha256": target_sha,
                    "year": "2026",
                    "region": "japan",
                    "country_region": "japan",
                    "local_date": "2026-01-02",
                    "status": "finished",
                    "source_refs": json.dumps(
                        {
                            "calendar_discovery": {
                                "calendar_source_provider": "official_calendar",
                                "calendar_source_url": calendar_url,
                            }
                        },
                        sort_keys=True,
                    ),
                }
            )
        return record

    def add_gap(self, target_id: int, year: int) -> dict:
        target_sha = f"{target_id:064x}"
        gap = {
            "target_id": target_id,
            "target_sha256": target_sha,
            "inventory_artifact_sha256": self.source_plan_sha,
            "reason_code": "source_package_gap",
        }
        self.gaps.append(gap)
        self.targets.append(
            {
                "target_id": target_id,
                "target_sha256": target_sha,
                "inventory_artifact_sha256": self.approved_inventory_sha,
                "year": year,
                "series_key": f"series-{target_id}",
                "country_region": "japan",
                "original_name": f"Race {target_id}",
                "chinese_name": "测试赛",
                "racecourse": "Tokyo",
                "grade_text": "G1",
                "expectation_status": "held",
                "resolution_status": "pending",
                "work_state": "current_year_due_check" if year == 2026 else "crawl",
            }
        )
        return gap

    def build(self, *, package_count: int = 39, include_smoke: bool = True) -> None:
        grouped_records: list[list[dict]] = [[] for _ in range(package_count)]
        grouped_gaps: list[list[dict]] = [[] for _ in range(package_count)]
        package_records = [
            row for row in self.records if row["target_id"] not in self.omitted_package_target_ids
        ]
        package_gaps = [
            row for row in self.gaps if row["target_id"] not in self.omitted_package_target_ids
        ]
        for index, record in enumerate(package_records):
            grouped_records[index % package_count].append(record)
        for index, gap in enumerate(package_gaps, start=len(package_records)):
            grouped_gaps[index % package_count].append(gap)

        for index, (records, gaps) in enumerate(
            zip(grouped_records, grouped_gaps, strict=True), start=1
        ):
            self._write_package(f"japan-2024-official-{index:02d}", records, gaps)

        if include_smoke:
            smoke = self.v6 / "smoke/run/japan-smoke/package-manifest.json"
            write_json(
                smoke,
                {
                    "artifact_kind": "historical_race_detail_package",
                    "schema_version": "2.0",
                    "scope_count": 0,
                    "accounted_count": 0,
                    "record_count": 0,
                    "gap_count": 0,
                    "records": [],
                    "gaps": [],
                },
            )

        request_log = self.v6 / "carry_forward/source_host_audit/results.example.test.requests.jsonl"
        write_jsonl(request_log, self.request_rows)
        self._write_v6_manifest(smoke_count=1 if include_smoke else 0)
        self._write_v9()
        self._write_due()

    def _write_package(
        self,
        shard_id: str,
        package_records: list[dict],
        package_gaps: list[dict],
    ) -> None:
        run_dir = self.v6 / "run" / shard_id
        cache_dir = run_dir / "source-cache"
        source_requests = []
        staged_rows = []
        clean_records = []
        cache_files: dict[str, dict] = {}
        if not package_records and not package_gaps:
            self.request_rows.append(
                {
                    "host": "results.example.test",
                    "shard_id": shard_id,
                    "url": f"https://results.example.test/audit/{shard_id}",
                }
            )
        for record in package_records:
            year = next(row["year"] for row in self.targets if row["target_id"] == record["target_id"])
            cache_raw = record["_cache_raw"]
            cache_identity = record["modules"]["results"]["source_cache_identity"]
            cache_path = cache_dir / cache_identity["path"]
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(cache_raw)
            cache_files[cache_identity["path"]] = cache_identity
            for extra_identity, extra_raw in record["_extra_caches"]:
                extra_path = cache_dir / extra_identity["path"]
                extra_path.write_bytes(extra_raw)
                cache_files[extra_identity["path"]] = extra_identity
            recovery_evidence = []
            if record["_recovery_candidate_has_date"]:
                recovery_path = self.v6 / "recovery" / f"{record['target_id']}.jsonl"
                write_jsonl(
                    recovery_path,
                    [
                        {
                            "target_id": record["target_id"],
                            "local_date": record["_fragment_local_date"],
                        }
                    ],
                )
                recovery_identity = identity(recovery_path)
                recovery_identity["kind"] = "validated_candidate_jsonl"
                recovery_evidence.append(recovery_identity)
            source_requests.append(
                {
                    "target_id": str(record["target_id"]),
                    "target_sha256": record["target_sha256"],
                    "year": year,
                    "local_date": record["_fragment_local_date"],
                    "source_name": record["source_name"],
                    "source_provider": "official_provider",
                    "source_url": record["source_url"],
                    "evidence_source_url": record["source_url"],
                    "fixture_identity": {
                        "path": str(cache_path),
                        "sha256": cache_identity["sha256"],
                        "size": cache_identity["size"],
                    },
                    "recovery_evidence": recovery_evidence,
                }
            )
            source_refs = {
                "calendar_discovery": {
                    "edition_year": year,
                    "local_date": "2026-01-02" if year == 2026 else "2024-01-02",
                    "source_provider": "official_calendar",
                    "source_url": record["_calendar_url"],
                },
                "detail_discovery": {
                    "source_provider": "official_provider",
                    "source_url": record["source_url"],
                },
            }
            staged_rows.append(
                {
                    "target_id": record["target_id"],
                    "target_sha256": record["target_sha256"],
                    "inventory_artifact_sha256": self.source_plan_sha,
                    "year": year,
                    "slug": f"race-{record['target_id']}-{year}",
                    "original_name": f"Race {record['target_id']}",
                    "chinese_name": "测试赛",
                    "country_region": "japan",
                    "racecourse": "Tokyo",
                    "grade_text": "G1",
                    "normalized_grade": "G1",
                    "surface": "turf",
                    "distance_text": "1600m",
                    "status": "finished",
                    "local_date": "2026-01-02" if year == 2026 else "2024-01-02",
                    "source_refs": json.dumps(source_refs, ensure_ascii=False, sort_keys=True),
                }
            )
            self.request_rows.append(
                {
                    "host": "results.example.test",
                    "shard_id": shard_id,
                    "url": record["source_url"],
                }
            )
            clean_records.append({key: value for key, value in record.items() if not key.startswith("_")})

        for gap in package_gaps:
            target_id = gap["target_id"]
            year = next(row["year"] for row in self.targets if row["target_id"] == target_id)
            source_url = f"https://results.example.test/gaps/{target_id}"
            source_requests.append(
                {
                    "target_id": str(target_id),
                    "target_sha256": gap["target_sha256"],
                    "year": year,
                    "local_date": "2026-01-02" if year == 2026 else "2024-01-02",
                    "source_name": "official_result",
                    "source_provider": "official_provider",
                    "source_url": source_url,
                    "evidence_source_url": source_url,
                    "recovery_evidence": [],
                }
            )
            staged_rows.append(
                {
                    "target_id": target_id,
                    "target_sha256": gap["target_sha256"],
                    "inventory_artifact_sha256": self.source_plan_sha,
                    "year": year,
                    "slug": f"race-{target_id}-{year}",
                    "original_name": f"Race {target_id}",
                    "chinese_name": "测试赛",
                    "country_region": "japan",
                    "racecourse": "Tokyo",
                    "grade_text": "G1",
                    "normalized_grade": "G1",
                    "surface": "turf",
                    "distance_text": "1600m",
                    "status": "finished",
                    "local_date": "2026-01-02" if year == 2026 else "2024-01-02",
                    "source_refs": json.dumps(
                        {
                            "calendar_discovery": {
                                "edition_year": year,
                                "local_date": (
                                    "2026-01-02" if year == 2026 else "2024-01-02"
                                ),
                                "source_provider": "official_calendar",
                                "source_url": source_url,
                            },
                            "detail_discovery": {
                                "source_provider": "official_provider",
                                "source_url": source_url,
                            },
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
            self.request_rows.append(
                {
                    "host": "results.example.test",
                    "shard_id": shard_id,
                    "url": source_url,
                }
            )

        cache_manifest = cache_dir / "source_cache_manifest.json"
        write_json(
            cache_manifest,
            {
                "schema_version": "1.0",
                "root": str(cache_dir),
                "total_bytes": sum(row["size"] for row in cache_files.values()),
                "updated_at": "2026-07-16T00:00:00Z",
                "files": cache_files,
            },
        )
        staged_path = run_dir / "staged-events.csv"
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "target_id", "target_sha256", "inventory_artifact_sha256", "year", "slug",
            "original_name", "chinese_name", "country_region", "racecourse", "grade_text",
            "normalized_grade", "surface", "distance_text", "status", "local_date", "source_refs",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(staged_rows)
        staged_path.write_text(stream.getvalue(), encoding="utf-8")
        candidates_path = run_dir / "validated-candidates.jsonl"
        write_jsonl(candidates_path, clean_records)
        fragment_path = self.v6 / "source_fragments" / f"{shard_id}.json"
        write_json(
            fragment_path,
            {
                "artifact_kind": "historical_race_detail_source_fragment",
                "schema_version": "1.0",
                "plan_id": "detail-crawl-1998-2026-v6",
                "shard_id": shard_id,
                "region": "japan",
                "target_count": len(source_requests),
                "requests": source_requests,
            },
        )
        package_path = run_dir / "package-manifest.json"
        write_json(
            package_path,
            {
                "artifact_kind": "historical_race_detail_package",
                "schema_version": "2.0",
                "scope_count": len(clean_records) + len(package_gaps),
                "accounted_count": len(clean_records) + len(package_gaps),
                "record_count": len(clean_records),
                "gap_count": len(package_gaps),
                "source_cache_manifest_identity": identity(cache_manifest),
                "staged_event_identity": identity(staged_path),
                "candidate_identity": identity(candidates_path),
                "records": clean_records,
                "gaps": package_gaps,
            },
        )

    def _write_v6_manifest(self, *, smoke_count: int) -> None:
        artifacts = []
        for path in sorted(self.v6.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                artifacts.append(identity(path, relative_to=self.v6))
        write_json(
            self.v6 / "manifest.json",
            {
                "artifact_kind": "canonical_immutable_detail_crawl_plan_manifest",
                "schema_version": "2.0",
                "plan_id": "detail-crawl-1998-2026-v6",
                "scope_count": len(self.records) + len(self.gaps),
                "actionable_count": len(self.records) + len(self.gaps),
                "pending_count": 0,
                "descriptor_count": 39,
                "smoke_descriptor_count": smoke_count,
                "artifact_count": len(artifacts),
                "artifacts": artifacts,
            },
        )

    def _write_v9(self) -> None:
        remaining = self.v9 / "remaining_targets.jsonl"
        write_jsonl(remaining, sorted(self.targets, key=lambda row: row["target_id"]))
        artifact = identity(remaining, relative_to=self.v9)
        write_json(
            self.v9 / "manifest.json",
            {
                "schema_version": "1.0",
                "plan_id": "remaining-1998-2026-v9",
                "target_count": len(self.targets),
                "artifact_count": 1,
                "artifacts": {"remaining_targets.jsonl": artifact},
            },
        )

    def _write_due(self) -> None:
        due_events = self.due / "unified_due_events.jsonl"
        due_gaps = self.due / "unified_due_gaps.jsonl"
        not_due = self.due / "unified_not_due.jsonl"
        write_jsonl(due_events, sorted(self.due_rows, key=lambda row: row["target_id"]))
        write_jsonl(due_gaps, [])
        write_jsonl(not_due, [])
        artifacts = {
            path.name: identity(path)
            for path in (due_events, due_gaps, not_due)
        }
        write_json(
            self.due / "manifest.json",
            {
                "artifact_kind": "current_year_due_classification_aggregate",
                "schema_version": "1.0",
                "plan_id": "current-year-due-check-20260715",
                "cutoff_date": self.cutoff,
                "target_count": len(self.due_rows),
                "artifacts": artifacts,
                "shards": [],
                "validations": {"required_identity_chain_verified": True},
            },
        )


class HistoricalRaceDetailImportPackagerTests(TestCase):
    def setUp(self):
        self.tool = load_tool()

    def build_bundle(self, builder: ArtifactBuilder, output: Path, **kwargs):
        target_years = {row["target_id"]: int(row["year"]) for row in builder.targets}
        expected_historical_record_count = kwargs.pop("expected_historical_record_count")
        expected_new_record_count = kwargs.pop("expected_new_record_count")
        expected_historical_gap_count = kwargs.pop(
            "expected_historical_gap_count",
            sum(1 for row in builder.gaps if target_years[row["target_id"]] <= 2024),
        )
        expected_new_gap_count = kwargs.pop(
            "expected_new_gap_count",
            sum(1 for row in builder.gaps if target_years[row["target_id"]] > 2024),
        )
        chunk_size = kwargs.get("chunk_size", 250)
        expected_runner_count = sum(
            len(row["modules"]["runners"]["items"]) for row in builder.records
        )
        expected_result_count = sum(
            len(row["modules"]["results"]["items"]) for row in builder.records
        )
        return self.tool.package_source_bundle(
            builder.v6,
            builder.v9,
            builder.due,
            output,
            expected_package_count=39,
            expected_scope_count=kwargs.pop(
                "expected_scope_count", len(builder.records) + len(builder.gaps)
            ),
            expected_input_record_count=kwargs.pop(
                "expected_input_record_count", len(builder.records)
            ),
            expected_input_gap_count=kwargs.pop(
                "expected_input_gap_count", len(builder.gaps)
            ),
            expected_historical_record_count=expected_historical_record_count,
            expected_historical_gap_count=expected_historical_gap_count,
            expected_historical_chunk_count=kwargs.pop(
                "expected_historical_chunk_count",
                (expected_historical_record_count + chunk_size - 1) // chunk_size,
            ),
            expected_new_record_count=expected_new_record_count,
            expected_new_gap_count=expected_new_gap_count,
            expected_new_chunk_count=kwargs.pop(
                "expected_new_chunk_count",
                (expected_new_record_count + chunk_size - 1) // chunk_size,
            ),
            expected_runner_count=kwargs.pop(
                "expected_runner_count", expected_runner_count
            ),
            expected_result_count=kwargs.pop(
                "expected_result_count", expected_result_count
            ),
            **kwargs,
        )

    def test_formal_defaults_lock_the_approved_v6_contract(self):
        parameters = inspect.signature(self.tool.package_source_bundle).parameters
        expected_defaults = {
            "expected_package_count": 39,
            "expected_scope_count": 4930,
            "expected_input_record_count": 4652,
            "expected_input_gap_count": 278,
            "expected_historical_record_count": 4351,
            "expected_historical_gap_count": 214,
            "expected_historical_chunk_count": 18,
            "expected_new_record_count": 301,
            "expected_new_gap_count": 64,
            "expected_new_chunk_count": 2,
            "expected_runner_count": 51191,
            "expected_result_count": 48413,
        }
        self.assertEqual(
            {name: parameters[name].default for name in expected_defaults},
            expected_defaults,
        )

    def test_builds_deterministic_layered_chunks_and_pending_approvals(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            for target_id in range(1, 252):
                builder.add_record(target_id, 2024)
            builder.add_record(1000, 2026)
            builder.build()

            output_a = root / "bundle-a"
            output_b = root / "bundle-b"
            result = self.build_bundle(
                builder,
                output_a,
                expected_historical_record_count=251,
                expected_new_record_count=1,
            )
            self.build_bundle(
                builder,
                output_b,
                expected_historical_record_count=251,
                expected_new_record_count=1,
            )

            manifest = json.loads((output_a / "manifest.json").read_text())
            bundle_identity = json.loads((output_a / "bundle-identity.json").read_text())
            package_index = json.loads((output_a / "package-index.json").read_text())
            evidence_index = json.loads((output_a / "evidence-index.json").read_text())
            historical = manifest["layers"]["historical_through_2024"]
            current = manifest["layers"]["current_year_due"]

            self.assertEqual(result["record_count"], 252)
            self.assertEqual(result["gap_count"], 0)
            self.assertEqual(historical["record_count"], 251)
            self.assertEqual(historical["chunk_count"], 2)
            self.assertEqual(current["record_count"], 1)
            self.assertEqual(current["chunk_count"], 1)
            self.assertEqual(package_index["package_count"], 39)
            self.assertEqual(package_index["excluded_smoke_package_count"], 1)
            self.assertEqual(len(evidence_index["packages"]), 39)
            self.assertTrue(
                all(row["request_evidence_identities"] for row in evidence_index["packages"])
            )
            self.assertEqual(manifest["approved_inventory_artifact_sha256"], "b" * 64)
            self.assertEqual(manifest["source_plan_artifact_sha256"], "a" * 64)
            self.assertEqual(manifest["current_year_due"]["cutoff_date"], "2026-07-15")
            self.assertEqual(manifest["current_year_due"]["input_record_count"], 1)
            self.assertEqual(manifest["current_year_due"]["due_record_count"], 1)
            self.assertEqual(
                manifest["current_year_due"]["not_due_or_pending_record_count"], 0
            )
            self.assertEqual(
                manifest["validated_counts"],
                {
                    "package_count": 39,
                    "scope_count": 252,
                    "input_record_count": 252,
                    "input_gap_count": 0,
                    "historical_record_count": 251,
                    "historical_gap_count": 0,
                    "historical_chunk_count": 2,
                    "current_year_due_record_count": 1,
                    "current_year_due_gap_count": 0,
                    "current_year_due_chunk_count": 1,
                    "runner_count": 252,
                    "result_count": 252,
                },
            )
            self.assertTrue(all(manifest["validations"].values()))
            self.assertEqual(bundle_identity["manifest"]["sha256"], hashlib.sha256((output_a / "manifest.json").read_bytes()).hexdigest())

            chunk_paths = [row["path"] for row in historical["chunks"]]
            first_chunk = [json.loads(line) for line in (output_a / chunk_paths[0]).read_text().splitlines()]
            second_chunk = [json.loads(line) for line in (output_a / chunk_paths[1]).read_text().splitlines()]
            self.assertEqual(len(first_chunk), 250)
            self.assertEqual(len(second_chunk), 1)
            self.assertEqual(first_chunk[0]["pending_target"]["target_id"], 1)
            self.assertEqual(first_chunk[0]["source_plan_artifact_sha256"], "a" * 64)
            self.assertEqual(first_chunk[0]["approved_inventory_artifact_sha256"], "b" * 64)
            self.assertIn("package_identity", first_chunk[0])
            self.assertIn("cache_identities", first_chunk[0])
            self.assertIn("calendar_evidence", first_chunk[0])
            approved_source = first_chunk[0]["approved_source_cache_identity"]
            chunk_root = (output_a / historical["chunks"][0]["manifest"]["path"]).parent
            source_path = chunk_root / approved_source["path"]
            self.assertTrue(source_path.is_file())
            self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), approved_source["sha256"])
            chunk_manifest = json.loads(
                (output_a / historical["chunks"][0]["manifest"]["path"]).read_text()
            )
            self.assertEqual(len(chunk_manifest["artifacts"]), 251)
            self.assertEqual(chunk_manifest["artifacts"][0]["path"], "candidates.jsonl")

            approvals = bundle_identity["approval_templates"]
            self.assertEqual(len(approvals), 3)
            for approval_identity in approvals:
                approval = json.loads((output_a / approval_identity["path"]).read_text())
                self.assertEqual(approval["status"], "pending")
                self.assertIsNone(approval["approved_by"])
                self.assertIsNone(approval["approved_at"])
                self.assertEqual(approval["bundle_manifest_sha256"], bundle_identity["manifest"]["sha256"])
                self.assertEqual(len(approval["target_ids"]), approval["target_count"])

            files_a = {path.relative_to(output_a): path.read_bytes() for path in output_a.rglob("*") if path.is_file()}
            files_b = {path.relative_to(output_b): path.read_bytes() for path in output_b.rglob("*") if path.is_file()}
            self.assertEqual(files_a, files_b)

    def test_preserves_approved_package_gap_without_reclassification(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(2000, 2024)
            builder.add_gap(2001, 2024)
            builder.build()

            output = root / "bundle"
            manifest = self.build_bundle(
                builder,
                output,
                expected_historical_record_count=1,
                expected_new_record_count=0,
            )
            gaps = [
                json.loads(line)
                for line in (output / "gaps.jsonl").read_text().splitlines()
            ]

            self.assertEqual(manifest["scope_count"], 2)
            self.assertEqual(manifest["record_count"], 1)
            self.assertEqual(manifest["gap_count"], 1)
            self.assertEqual(manifest["layers"]["historical_through_2024"]["gap_count"], 1)
            self.assertEqual(gaps[0]["target_id"], 2001)
            self.assertEqual(gaps[0]["reason_code"], "source_package_gap")
            self.assertTrue(all(manifest["validations"].values()))

    def test_rejects_record_when_calendar_evidence_gate_would_create_a_gap(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(10, 2024, trace_calendar=False)
            builder.build()

            output = root / "bundle"
            with self.assertRaisesRegex(
                self.tool.SourceBundlePackagingError,
                "final .*record/gap",
            ):
                self.build_bundle(
                    builder,
                    output,
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )
            self.assertFalse(output.exists())

    def test_uses_verified_detail_source_date_only_when_date_evidence_matches(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(
                11,
                2024,
                trace_calendar=False,
                detail_url_has_date=True,
            )
            builder.add_record(
                12,
                2024,
                trace_calendar=False,
                recovery_candidate_has_date=True,
            )
            builder.build()

            output = root / "bundle"
            result = self.build_bundle(
                builder,
                output,
                expected_historical_record_count=2,
                expected_new_record_count=0,
            )
            records = []
            for chunk in result["layers"]["historical_through_2024"]["chunks"]:
                records.extend(
                    json.loads(line)
                    for line in (output / chunk["path"]).read_text().splitlines()
                )
            self.assertEqual([row["pending_target"]["target_id"] for row in records], [11, 12])
            for row in records:
                evidence = row["calendar_evidence"]
                self.assertEqual(evidence["kind"], "verified_detail_source_date")
                self.assertEqual(evidence["local_date"], "2024-01-02")
                self.assertIn("calendar_url", evidence)
                self.assertIn("detail_url", evidence)
                self.assertIn("fixture_identity", evidence)
                self.assertTrue(evidence["cache_identities"])
                self.assertIn("recovery_identities", evidence)
            self.assertEqual(result["record_count"], 2)
            self.assertEqual(result["gap_count"], 0)

    def test_rejects_2026_due_record_when_gate_would_downgrade_it_to_gap(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(20, 2026)
            builder.due_rows[0]["status"] = "scheduled"
            builder.build()

            output = root / "bundle"
            with self.assertRaisesRegex(
                self.tool.SourceBundlePackagingError,
                "final .*record/gap",
            ):
                self.build_bundle(
                    builder,
                    output,
                    expected_historical_record_count=0,
                    expected_new_record_count=1,
                )
            self.assertFalse(output.exists())

    def test_rejects_missing_package_gap_target_from_formal_scope(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(21, 2024)
            builder.add_gap(22, 2024)
            builder.omitted_package_target_ids.add(22)
            builder.build()

            with self.assertRaisesRegex(
                self.tool.SourceBundlePackagingError,
                "formal package scope",
            ):
                self.build_bundle(
                    builder,
                    root / "bundle",
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )

    def test_rejects_final_historical_layer_record_gap_deviation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(23, 2024)
            builder.add_record(24, 2024, trace_calendar=False)
            builder.build()

            with self.assertRaisesRegex(
                self.tool.SourceBundlePackagingError,
                "final historical .*record/gap",
            ):
                self.build_bundle(
                    builder,
                    root / "bundle",
                    expected_historical_record_count=2,
                    expected_new_record_count=0,
                )

    def test_rejects_cache_tampering_and_does_not_publish_partial_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(30, 2024)
            builder.build()
            cache_path = next((builder.v6 / "run").glob("*/source-cache/*.html"))
            cache_path.write_bytes(b"tampered")
            output = root / "bundle"

            with self.assertRaisesRegex(self.tool.SourceBundlePackagingError, "identity mismatch"):
                self.build_bundle(
                    builder,
                    output,
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )
            self.assertFalse(output.exists())

    def test_bundle_verifier_rejects_copied_source_tampering(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(31, 2024)
            builder.build()
            output = root / "bundle"
            self.build_bundle(
                builder,
                output,
                expected_historical_record_count=1,
                expected_new_record_count=0,
            )
            manifest = json.loads((output / "manifest.json").read_text())
            chunk = manifest["layers"]["historical_through_2024"]["chunks"][0]
            row = json.loads((output / chunk["path"]).read_text().splitlines()[0])
            chunk_root = (output / chunk["manifest"]["path"]).parent
            (chunk_root / row["approved_source_cache_identity"]["path"]).write_bytes(b"tampered")

            with self.assertRaisesRegex(self.tool.SourceBundlePackagingError, "identity mismatch"):
                self.tool.verify_source_bundle(output)

    def test_rejects_when_primary_source_cache_gate_would_create_gaps(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(32, 2024, primary_cache_matches=False)
            builder.add_record(33, 2024, ambiguous_primary_cache=True)
            builder.build()
            output = root / "bundle"
            with self.assertRaisesRegex(
                self.tool.SourceBundlePackagingError,
                "final .*record/gap",
            ):
                self.build_bundle(
                    builder,
                    output,
                    expected_historical_record_count=2,
                    expected_new_record_count=0,
                )
            self.assertFalse(output.exists())

    def test_rejects_symlinked_source_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(34, 2024)
            builder.build()
            cache_path = next((builder.v6 / "run").glob("*/source-cache/*.html"))
            raw = cache_path.read_bytes()
            real_path = cache_path.with_name("real-source.html")
            real_path.write_bytes(raw)
            cache_path.unlink()
            cache_path.symlink_to(real_path.name)
            builder._write_v6_manifest(smoke_count=1)

            with self.assertRaisesRegex(self.tool.SourceBundlePackagingError, "symlink"):
                self.build_bundle(
                    builder,
                    root / "bundle",
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )

    def test_rejects_v6_v9_pending_sha_mismatch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(40, 2024)
            builder.targets[0]["target_sha256"] = "f" * 64
            builder.build()

            with self.assertRaisesRegex(self.tool.SourceBundlePackagingError, "pending target SHA"):
                self.build_bundle(
                    builder,
                    root / "bundle",
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )

    def test_rejects_wrong_run_package_count_and_path_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            builder = ArtifactBuilder(root)
            builder.add_record(50, 2024)
            builder.build(package_count=38)
            with self.assertRaisesRegex(self.tool.SourceBundlePackagingError, "exactly 39"):
                self.build_bundle(
                    builder,
                    root / "bundle-count",
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )

            builder = ArtifactBuilder(root / "escape")
            builder.add_record(60, 2024)
            builder.build()
            package_path = next((builder.v6 / "run").glob("*/package-manifest.json"))
            package = json.loads(package_path.read_text())
            package["staged_event_identity"]["path"] = "../../../../outside.csv"
            write_json(package_path, package)
            builder._write_v6_manifest(smoke_count=1)
            with self.assertRaisesRegex(self.tool.SourceBundlePackagingError, "escapes allowed roots"):
                self.build_bundle(
                    builder,
                    root / "bundle-escape",
                    expected_historical_record_count=1,
                    expected_new_record_count=0,
                )
