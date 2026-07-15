from __future__ import annotations

import copy
import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "runtime" / "tools"
CACHE_RUN_ROOT_VALUE = os.environ.get("HISTORICAL_DETAIL_DISTANCE_CACHE_RUN_ROOT", "")
CACHE_RUN_ROOT = Path(CACHE_RUN_ROOT_VALUE) if CACHE_RUN_ROOT_VALUE else None
SMOKE_ROOT = CACHE_RUN_ROOT.parent if CACHE_RUN_ROOT is not None else None


def _load(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_package_identity_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _descriptor(smoke_name: str) -> dict:
    assert SMOKE_ROOT is not None
    return json.loads(
        (SMOKE_ROOT / "descriptors" / f"{smoke_name}.json").read_text(encoding="utf-8")
    )


def _cache_manifest(smoke_name: str) -> Path:
    assert CACHE_RUN_ROOT is not None
    return CACHE_RUN_ROOT / smoke_name / "source-cache" / "source_cache_manifest.json"


@skipUnless(CACHE_RUN_ROOT is not None, "real cache root not configured")
class HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = _load("historical_race_detail_runner_v2.py")
        cls.adapters = _load("historical_race_detail_adapters.py")

    def _parse_real_smoke(self, smoke_name: str, run_root: Path) -> tuple[dict, dict]:
        descriptor = _descriptor(smoke_name)
        parsed = self.adapters.parse_cached_sources(
            descriptor,
            cache_artifact={"source_cache_manifest": str(_cache_manifest(smoke_name))},
            run_root=run_root,
        )
        self.assertEqual(parsed["candidate_count"], 1)
        return descriptor, parsed

    def test_empty_event_distance_uses_real_parsed_metadata_with_original_units(self):
        cases = (
            ("smoke-japan-50556", "1600\uff4d"),
            ("smoke-united_kingdom-56980", "2m 4f 0y"),
            ("smoke-united_states-70844", "One Mile"),
        )
        for smoke_name, expected_distance in cases:
            with self.subTest(smoke_name=smoke_name), TemporaryDirectory() as tmp:
                run_root = Path(tmp)
                descriptor, parsed = self._parse_real_smoke(smoke_name, run_root)

                result = self.runner._validate_parsed_stage(
                    descriptor,
                    parse_artifact=parsed,
                    run_root=run_root,
                )
                validated = self.adapters.read_candidates(Path(result["validated_candidate_jsonl"]))
                event = validated[0]["validation"]["event"]

                self.assertEqual(event["distance"], expected_distance)
                self.assertEqual(
                    event["distance_provenance"],
                    {
                        "source": "parsed.metadata.distance_text",
                        "original_text": expected_distance,
                        "source_url": validated[0]["source_url"],
                    },
                )
                package_result = self.adapters.package_validated_sources(
                    descriptor,
                    candidate_jsonl=Path(result["validated_candidate_jsonl"]),
                    cache_manifest=_cache_manifest(smoke_name),
                    run_root=run_root,
                )
                package = json.loads(
                    Path(package_result["package_manifest"]).read_text(encoding="utf-8")
                )
                self.assertEqual(package_result["record_count"], 1)
                self.assertEqual(package_result["gap_count"], 0)
                self.assertEqual(package["records"][0]["distance_text"], expected_distance)
                self.assertEqual(
                    package["records"][0]["distance_provenance"],
                    event["distance_provenance"],
                )

    def test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap(self):
        with TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            descriptor, parsed = self._parse_real_smoke("smoke-japan-50556", run_root)
            source_events = Path(descriptor["adapter_inputs"]["events_csv"])
            conflicting_events = run_root / "conflicting-events.csv"
            with source_events.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                rows = list(reader)
                fieldnames = list(reader.fieldnames or [])
            rows[0]["distance_text"] = "1800m"
            with conflicting_events.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            descriptor = copy.deepcopy(descriptor)
            descriptor["adapter_inputs"]["events_csv"] = str(conflicting_events)

            result = self.runner._validate_parsed_stage(
                descriptor,
                parse_artifact=parsed,
                run_root=run_root,
            )
            validated = self.adapters.read_candidates(Path(result["validated_candidate_jsonl"]))
            gaps = json.loads(Path(result["validation_gap_json"]).read_text(encoding="utf-8"))

        self.assertEqual(result["validated_count"], 0)
        self.assertEqual(result["validation_gap_count"], 1)
        self.assertEqual(validated, [])
        self.assertEqual(gaps[0]["target_id"], rows[0]["target_id"])
        self.assertEqual(gaps[0]["target_sha256"], rows[0]["target_sha256"])
        self.assertEqual(gaps[0]["reason_code"], "validation_failed")
        self.assertEqual(
            gaps[0]["error"],
            {
                "type": "RunnerV2Error",
                "message": "event and parsed metadata distance conflict",
            },
        )
        self.assertEqual(len(gaps[0]["error_identity"]["sha256"]), 64)
        self.assertEqual(
            set(gaps[0]["evidence_identities"]),
            {"candidate", "candidate_artifact", "events_csv"},
        )

    def test_hk_real_validated_candidate_packages_with_plan_inventory_identity(self):
        descriptor = _descriptor("smoke-hong_kong-49451")
        candidate = CACHE_RUN_ROOT / "smoke-hong_kong-49451" / "validated-candidates.jsonl"
        plan_identity = next(
            identity for identity in descriptor["identities"] if identity["role"] == "plan"
        )
        original_event_path = Path(descriptor["adapter_inputs"]["events_csv"])
        with original_event_path.open(encoding="utf-8-sig", newline="") as handle:
            original_event = next(csv.DictReader(handle))

        with TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            result = self.adapters.package_validated_sources(
                descriptor,
                candidate_jsonl=candidate,
                cache_manifest=_cache_manifest("smoke-hong_kong-49451"),
                run_root=run_root,
            )
            manifest = json.loads(Path(result["package_manifest"]).read_text(encoding="utf-8"))
            staged_path = Path(result["staged_event_csv"])
            with staged_path.open(encoding="utf-8-sig", newline="") as handle:
                staged_event = next(csv.DictReader(handle))

        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["gap_count"], 0)
        self.assertEqual(staged_event["target_sha256"], original_event["target_sha256"])
        self.assertEqual(staged_event["inventory_artifact_sha256"], plan_identity["sha256"])
        original_refs = json.loads(original_event["source_refs"])
        staged_refs = json.loads(staged_event["source_refs"])
        self.assertEqual(staged_refs["calendar_discovery"], original_refs["calendar_discovery"])
        self.assertEqual(
            staged_refs["detail_discovery"]["urls"]["result_url"],
            {
                "source_provider": "hkjc",
                "url": manifest["records"][0]["source_url"],
            },
        )
        self.assertEqual(manifest["staged_event_identity"]["path"], str(staged_path))
        self.assertEqual(manifest["records"][0]["target_sha256"], original_event["target_sha256"])
        self.assertEqual(
            manifest["records"][0]["inventory_artifact_sha256"], plan_identity["sha256"]
        )
        self.assertEqual(
            manifest["records"][0]["distance_provenance"],
            {
                "source": "event_csv.distance_text",
                "original_text": "1000m",
                "source_url": manifest["records"][0]["source_url"],
            },
        )

    def test_hk_package_rejects_raw_candidate_without_validation_evidence(self):
        descriptor = _descriptor("smoke-hong_kong-49451")
        validated_path = CACHE_RUN_ROOT / "smoke-hong_kong-49451" / "validated-candidates.jsonl"
        candidate = self.adapters.read_candidates(validated_path)[0]
        candidate.pop("validation")
        with TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            raw_path = run_root / "raw-candidates.jsonl"
            raw_path.write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(
                self.adapters.DetailAdapterError,
                "package candidate was not validated",
            ):
                self.adapters.package_validated_sources(
                    descriptor,
                    candidate_jsonl=raw_path,
                    cache_manifest=_cache_manifest("smoke-hong_kong-49451"),
                    run_root=run_root,
                )
