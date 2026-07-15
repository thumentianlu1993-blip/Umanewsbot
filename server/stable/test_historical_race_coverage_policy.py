from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "runtime" / "tools"
BUILD_TOOL = TOOLS / "build_historical_race_coverage_policy.py"
VERIFY_TOOL = TOOLS / "verify_historical_race_coverage_policy.py"
POLICY_CONFIG = ROOT / "runtime" / "policies" / "historical_race_coverage_policy.v1.json"
POLICY_DOC = Path(__file__).resolve().parent / "fixtures" / "historical_race_coverage_policy" / "policy.md"

TRUSTED_TEST_SOURCES = {
    "japan": ("jra", "https://www.jra.go.jp/race"),
    "hong_kong": ("hkjc", "https://racing.hkjc.com/race"),
    "united_kingdom": ("bha", "https://www.britishhorseracing.com/race"),
    "france": ("france_galop", "https://www.france-galop.com/race"),
    "united_states": ("equibase", "https://www.equibase.com/race"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path, root: Path) -> dict:
    return {
        "path": str(path.relative_to(root)),
        "sha256": _sha(path),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rebind_output_artifact(root: Path, name: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["artifacts"][name] = _identity(root / name, root)
    _write_json(manifest_path, manifest)


def _rebind_v6_package(v6: Path, package_path: Path) -> None:
    report_path = v6 / "execution_report.json"
    report = _read_json(report_path)
    package_identity = _identity(package_path, v6)
    report["main_descriptors"][0]["package_identity"] = package_identity
    _write_json(report_path, report)
    manifest_path = v6 / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["execution_report_identity"] = _identity(report_path, v6)
    manifest["artifacts"][0] = package_identity
    manifest["artifacts"][2] = _identity(report_path, v6)
    _write_json(manifest_path, manifest)


def _target(target_id: int, region: str, year: int, grade: str, series: str) -> dict:
    return {
        "target_id": target_id,
        "target_sha256": hashlib.sha256(f"target:{target_id}".encode()).hexdigest(),
        "inventory_artifact_sha256": "a" * 64,
        "country_region": region,
        "series_key": series,
        "year": year,
        "grade_text": grade,
        "expectation_status": "held",
        "resolution_status": "pending",
        "work_state": "crawl_pending",
        "original_name": series,
        "racecourse": "Course",
    }


def _complete_record(target: dict, *, barrier_status: str = "complete") -> dict:
    source_identity, source_url = TRUSTED_TEST_SOURCES[target["country_region"]]
    evidence_binding = {
        "target_id": target["target_id"],
        "target_sha256": target["target_sha256"],
        "series_key": target["series_key"],
        "year": target["year"],
        "source_identity": source_identity,
        "url": source_url,
        "snapshot_sha256": "b" * 64,
    }
    record = {
        "target_id": target["target_id"],
        "target_sha256": target["target_sha256"],
        "source_url": source_url,
        "distance_text": "1600m",
        "distance_provenance": {"source": "official", "source_url": source_url},
        "basic_field_evidence": {
            "grade": {**evidence_binding, "value": target["grade_text"]},
            "surface": {**evidence_binding, "value": "turf"},
            "race_type": {**evidence_binding, "value": "flat"},
        },
        "barrier_evidence_status": barrier_status,
        "source_evidence": {
            "url": source_url,
            "captured_at": "2026-07-16T00:00:00Z",
            "source_type": "official_result",
            "snapshot_sha256": "b" * 64,
            "source_identity": source_identity,
        },
        "modules": {
            "runners": {
                "is_complete": True,
                "items": [
                    {"horse_number": "1", "horse_name": "Winner", "barrier": "2"},
                    {"horse_number": "2", "horse_name": "Second", "barrier": "1"},
                ],
            },
            "results": {
                "is_complete": True,
                "items": [
                    {"horse_number": "1", "horse_name": "Winner", "finish_position": 1},
                    {"horse_number": "2", "horse_name": "Second", "finish_position": 2},
                ],
            },
        },
        "winner": {"horse_number": "1", "horse_name": "Winner"},
    }
    if barrier_status == "not_applicable_with_evidence":
        record["basic_field_evidence"]["race_type"]["value"] = "hurdle"
        record["barrier_evidence"] = {
            **evidence_binding,
            "assertion_kind": "barrier_not_applicable",
            "race_type_value": "hurdle",
            "reason": "official race type has no barrier concept",
        }
        for runner in record["modules"]["runners"]["items"]:
            runner.pop("barrier")
    return record


def _strict_absence(kind: str, target: dict) -> dict:
    source_identity, source_url = TRUSTED_TEST_SOURCES[target["country_region"]]
    return {
        "assertion_kind": kind,
        "target_id": target["target_id"],
        "target_sha256": target["target_sha256"],
        "series_key": target["series_key"],
        "year": target["year"],
        "url": source_url,
        "captured_at": "2026-07-16T00:00:00Z",
        "snapshot_sha256": "c" * 64,
        "source_authority": "authority" if source_identity in {"bha", "france_galop", "equibase"} else "official",
        "source_identity": source_identity,
    }


def _permanent_evidence(target: dict) -> dict:
    common = {
        "checked_at": "2026-07-16T00:00:00Z",
        "query_scope": f"{target['series_key']}:{target['year']}",
        "snapshot_sha256": "d" * 64,
    }
    return {
        "target_id": target["target_id"],
        "target_sha256": target["target_sha256"],
        "series_key": target["series_key"],
        "year": target["year"],
        "official_archive": {
            **common,
            "url": "https://www.equibase.com/archive",
            "source_identity": "equibase",
        },
        "independent_source": {
            **common,
            "url": "https://www.horseracingnation.com/archive",
            "source_identity": "horse_racing_nation",
        },
    }


def _fixture(root: Path, targets: list[dict], *, records=None, gaps=None) -> tuple[Path, Path, Path]:
    v9 = root / "v9"
    v6 = root / "v6"
    out = root / "out"
    v9.mkdir()
    v6.mkdir()
    remaining = v9 / "remaining_targets.jsonl"
    _write_jsonl(remaining, targets)
    master = {
        "schema_version": "1.0",
        "inventory_manifest_sha256": "a" * 64,
        "remaining_targets": _identity(remaining, v9),
        "unresolved_target_count": len(targets),
    }
    _write_json(v9 / "master_selection.json", master)
    manifest = {
        "schema_version": "1.0",
        "plan_id": "remaining-test",
        "target_count": len(targets),
        "artifacts": {
            "master_selection.json": _identity(v9 / "master_selection.json", v9),
            "remaining_targets.jsonl": _identity(remaining, v9),
        },
    }
    _write_json(v9 / "manifest.json", manifest)

    package = {
        "artifact_kind": "historical_race_detail_package",
        "record_count": len(records or []),
        "gap_count": len(gaps or []),
        "accounted_count": len(records or []) + len(gaps or []),
        "scope_count": len(records or []) + len(gaps or []),
        "records": records or [],
        "gaps": gaps or [],
    }
    package_path = v6 / "run" / "main-01" / "package-manifest.json"
    _write_json(package_path, package)
    smoke_path = v6 / "smoke" / "smoke-01" / "package-manifest.json"
    _write_json(smoke_path, {**package, "records": [], "gaps": [], "record_count": 0, "gap_count": 0, "accounted_count": 0})
    report = {
        "main_descriptors": [{
            "shard_id": "main-01",
            "target_count": len(records or []) + len(gaps or []),
            "records": len(records or []),
            "gaps": len(gaps or []),
            "package_identity": _identity(package_path, v6),
        }],
        "smoke": [{"shard_id": "smoke-01", "package_identity": _identity(smoke_path, v6)}],
    }
    report_path = v6 / "execution_report.json"
    _write_json(report_path, report)
    v6_manifest = {
        "schema_version": "2.0",
        "plan_id": "detail-test",
        "descriptor_count": 1,
        "smoke_descriptor_count": 1,
        "execution_report_identity": _identity(report_path, v6),
        "artifacts": [_identity(package_path, v6), _identity(smoke_path, v6), _identity(report_path, v6)],
    }
    _write_json(v6 / "manifest.json", v6_manifest)
    return v9, v6, out


def _load_tool(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"missing production tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HistoricalRaceCoveragePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.builder = _load_tool(BUILD_TOOL)
        cls.verifier = _load_tool(VERIFY_TOOL)

    def _build(self, root: Path, targets: list[dict], *, records=None, gaps=None):
        v9, v6, out = _fixture(root, targets, records=records, gaps=gaps)
        result = self.builder.build_coverage(
            v9_root=v9,
            v6_root=v6,
            policy_doc=POLICY_DOC,
            config_path=POLICY_CONFIG,
            output_root=out,
        )
        rows = [json.loads(line) for line in (out / "coverage_ledger.jsonl").read_text().splitlines()]
        return result, rows, out, v9, v6

    def test_time_region_grade_tiers_and_exact_whitelist_are_fail_closed(self):
        targets = [
            _target(1, "united_kingdom", 2024, "G1", "uk-g1"),
            _target(2, "france", 2024, "G2", "fr-g2"),
            _target(3, "united_states", 2025, "G3", "us-new"),
            _target(4, "japan", 2024, "unknown", "jp-listed"),
            _target(5, "hong_kong", 2024, "G3", "hk-g3"),
            _target(6, "united_kingdom", 2024, "G3", "united-kingdom-grand-national-stp"),
            _target(7, "united_kingdom", 2024, "G3", "united-kingdom-grand-national-trial-stp"),
            _target(8, "france", 2024, "Listed", "fr-unknown"),
        ]
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), targets)
        tiers = {row["target_id"]: row["coverage_tier"] for row in rows}
        self.assertEqual(tiers, {1: "historical_hard", 2: "historical_best_effort", 3: "new_formal", 4: "historical_hard", 5: "historical_hard", 6: "historical_hard", 7: "historical_best_effort", 8: "historical_hard"})
        self.assertEqual(next(row for row in rows if row["target_id"] == 6)["whitelist_rule_id"], "uk-grand-national-v1")
        self.assertEqual(next(row for row in rows if row["target_id"] == 8)["classification_reason"], "unknown_grade_fail_closed")

    def test_detail_complete_and_policy_satisfied_are_separate_with_barrier_states(self):
        targets = [_target(1, "united_kingdom", 2024, "G1", "uk-g1"), _target(2, "japan", 2024, "G1", "jp-g1")]
        records = [_complete_record(targets[0]), _complete_record(targets[1], barrier_status="not_applicable_with_evidence")]
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), targets, records=records)
        self.assertTrue(all(row["detail_package_status"] == "complete" for row in rows))
        self.assertTrue(all(row["policy_acceptance_status"] == "satisfied" for row in rows))
        self.assertEqual({row["barrier_evidence_status"] for row in rows}, {"complete", "not_applicable_with_evidence"})

    def test_hard_missing_modules_and_unknown_barrier_are_blocked(self):
        target = _target(1, "united_states", 2024, "G1", "us-g1")
        record = _complete_record(target)
        record.pop("basic_field_evidence")
        record["barrier_evidence_status"] = "unknown"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target], records=[record])
        self.assertEqual(rows[0]["detail_package_status"], "complete")
        self.assertEqual(rows[0]["policy_acceptance_status"], "blocked")
        self.assertIn("basic_field_evidence", rows[0]["hard_blockers"])
        self.assertIn("barrier_evidence_unknown", rows[0]["hard_blockers"])

    def test_cancelled_and_not_held_need_strict_target_bound_evidence(self):
        good = _target(1, "france", 2024, "G1", "fr-g1")
        good["expectation_status"] = "cancelled"
        good["absence_evidence"] = _strict_absence("cancelled", good)
        bad = _target(2, "france", 2024, "G1", "fr-g1-bad")
        bad["expectation_status"] = "not_held"
        bad["absence_evidence"] = {"assertion_kind": "not_held", "url": "https://official.example"}
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [good, bad])
        by_id = {row["target_id"]: row for row in rows}
        self.assertEqual((by_id[1]["detail_package_status"], by_id[1]["policy_acceptance_status"]), ("not_applicable", "satisfied"))
        self.assertEqual(by_id[2]["policy_acceptance_status"], "blocked")

    def test_cancelled_evidence_rejects_non_authoritative_source_and_invalid_snapshot_hash(self):
        target = _target(1, "france", 2024, "G1", "fr-g1")
        target["expectation_status"] = "cancelled"
        target["absence_evidence"] = _strict_absence("cancelled", target)
        target["absence_evidence"]["source_authority"] = "blog"
        target["absence_evidence"]["snapshot_sha256"] = "not-a-sha"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target])
        self.assertEqual(rows[0]["policy_acceptance_status"], "blocked")

    def test_trusted_source_registry_rejects_unregistered_example_identity(self):
        config = _read_json(POLICY_CONFIG)
        self.assertIn("trusted_sources", config)
        target = _target(1, "france", 2024, "G1", "fr-g1")
        target["expectation_status"] = "cancelled"
        target["absence_evidence"] = _strict_absence("cancelled", target)
        target["absence_evidence"]["source_identity"] = "official.example"
        target["absence_evidence"]["url"] = "https://official.example/notice"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target])
        self.assertEqual(rows[0]["accounting_status"], "blocked")

        target["absence_evidence"] = _strict_absence("cancelled", target)
        target["absence_evidence"]["url"] = "https://www.britishhorseracing.com/notice"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target])
        self.assertEqual(rows[0]["accounting_status"], "blocked")

    def test_grade_evidence_value_must_normalize_and_match_target_grade(self):
        target = _target(1, "france", 2024, "Group 1", "fr-g1")
        record = _complete_record(target)
        record["basic_field_evidence"]["grade"]["value"] = "Group 2"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target], records=[record])
        self.assertEqual(rows[0]["accounting_status"], "blocked")
        self.assertIn("grade_evidence_conflict", rows[0]["hard_blockers"])

        variants = (("G1", "Group 1"), ("Group1", "Grade 1"), ("Grade1", "G1"))
        targets = []
        records = []
        for target_id, (target_grade, evidence_grade) in enumerate(variants, 2):
            variant = _target(target_id, "france", 2024, target_grade, f"fr-g1-{target_id}")
            record = _complete_record(variant)
            record["basic_field_evidence"]["grade"]["value"] = evidence_grade
            targets.append(variant)
            records.append(record)
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), targets, records=records)
        self.assertTrue(all(row["accounting_status"] == "satisfied" for row in rows))

    def test_barrier_not_applicable_requires_bound_allowed_jump_type_and_flat_is_blocked(self):
        target = _target(1, "united_kingdom", 2024, "G1", "uk-g1")
        flat = _complete_record(target, barrier_status="not_applicable_with_evidence")
        flat["basic_field_evidence"]["race_type"]["value"] = "flat"
        flat["barrier_evidence"]["race_type_value"] = "flat"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target], records=[flat])
        self.assertEqual(rows[0]["barrier_evidence_status"], "unknown")
        self.assertIn("barrier_evidence_unknown", rows[0]["hard_blockers"])

        unbound = _complete_record(target, barrier_status="not_applicable_with_evidence")
        unbound["barrier_evidence"]["target_id"] = 999
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [target], records=[unbound])
        self.assertEqual(rows[0]["barrier_evidence_status"], "unknown")

    def test_permanent_unavailable_requires_two_independent_sources(self):
        good = _target(1, "united_states", 2024, "G1", "us-g1")
        good["resolution_status"] = "permanently_unavailable"
        good["permanent_unavailable_evidence"] = _permanent_evidence(good)
        bad = _target(2, "united_states", 2024, "G1", "us-g1-bad")
        bad["resolution_status"] = "permanently_unavailable"
        bad["permanent_unavailable_evidence"] = _permanent_evidence(bad)
        bad["permanent_unavailable_evidence"]["official_archive"]["source_identity"] = "official.example"
        bad["permanent_unavailable_evidence"]["official_archive"]["url"] = "https://official.example/archive"
        with TemporaryDirectory() as tmp:
            _, rows, *_ = self._build(Path(tmp), [good, bad])
        by_id = {row["target_id"]: row for row in rows}
        self.assertEqual(by_id[1]["policy_acceptance_status"], "satisfied")
        self.assertEqual(by_id[2]["policy_acceptance_status"], "blocked")

    def test_v9_internal_identity_and_target_identity_conservation(self):
        target = _target(1, "japan", 2024, "G1", "jp-g1")
        with TemporaryDirectory() as tmp:
            result, rows, _, v9, _ = self._build(Path(tmp), [target])
            self.assertEqual((rows[0]["target_id"], rows[0]["target_sha256"]), (target["target_id"], target["target_sha256"]))
            self.assertEqual(result["upstream_inventory_identity_status"], "unverified")
            (v9 / "remaining_targets.jsonl").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(self.builder.CoveragePolicyError, "identity"):
                self.builder.build_coverage(v9_root=v9, v6_root=Path(tmp) / "v6", policy_doc=POLICY_DOC, config_path=POLICY_CONFIG, output_root=Path(tmp) / "out2")

    def test_v6_main_smoke_duplicate_drift_and_record_gap_conflict_are_rejected(self):
        target = _target(1, "japan", 2024, "G1", "jp-g1")
        gap = {"target_id": 1, "target_sha256": target["target_sha256"], "reason_code": "missing"}
        with TemporaryDirectory() as tmp:
            v9, v6, _ = _fixture(Path(tmp), [target], records=[_complete_record(target)], gaps=[gap])
            with self.assertRaisesRegex(self.builder.CoveragePolicyError, "record/gap conflict"):
                self.builder.build_coverage(v9_root=v9, v6_root=v6, policy_doc=POLICY_DOC, config_path=POLICY_CONFIG, output_root=Path(tmp) / "out2")

        for label, second_sha, message in (
            ("duplicate", target["target_sha256"], "duplicate target_id"),
            ("drift", "e" * 64, "id/SHA drift"),
        ):
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                second = _complete_record(target)
                second["target_sha256"] = second_sha
                v9, v6, _ = _fixture(Path(tmp), [target], records=[_complete_record(target), second])
                with self.assertRaisesRegex(self.builder.CoveragePolicyError, message):
                    self.builder.build_coverage(v9_root=v9, v6_root=v6, policy_doc=POLICY_DOC, config_path=POLICY_CONFIG, output_root=Path(tmp) / "out2")

    def test_v6_smoke_package_is_excluded_from_target_status(self):
        target = _target(1, "japan", 2024, "G1", "jp-g1")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            v9, v6, out = _fixture(root, [target])
            smoke_path = v6 / "smoke" / "smoke-01" / "package-manifest.json"
            _write_json(smoke_path, {
                "artifact_kind": "historical_race_detail_package",
                "record_count": 1,
                "gap_count": 0,
                "accounted_count": 1,
                "records": [_complete_record(target)],
                "gaps": [],
            })
            report_path = v6 / "execution_report.json"
            report = _read_json(report_path)
            report["smoke"][0]["package_identity"] = _identity(smoke_path, v6)
            _write_json(report_path, report)
            manifest_path = v6 / "manifest.json"
            manifest = _read_json(manifest_path)
            manifest["execution_report_identity"] = _identity(report_path, v6)
            manifest["artifacts"][1] = _identity(smoke_path, v6)
            manifest["artifacts"][2] = _identity(report_path, v6)
            _write_json(manifest_path, manifest)
            self.builder.build_coverage(v9_root=v9, v6_root=v6, policy_doc=POLICY_DOC, config_path=POLICY_CONFIG, output_root=out)
            row = json.loads((out / "coverage_ledger.jsonl").read_text())
        self.assertEqual(row["detail_package_status"], "pending")
        self.assertEqual(row["policy_acceptance_status"], "blocked")

    def test_v6_stream_keeps_only_compact_status_and_rejects_declared_count_drift(self):
        target = _target(1, "japan", 2024, "G1", "jp-g1")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, v6, _ = _fixture(root, [target], records=[_complete_record(target)])
            statuses, _ = self.builder._load_v6(v6)
            self.assertNotIn("payload", statuses[1])
            report_path = v6 / "execution_report.json"
            report = _read_json(report_path)
            report["main_descriptors"][0]["records"] = 2
            _write_json(report_path, report)
            manifest_path = v6 / "manifest.json"
            manifest = _read_json(manifest_path)
            manifest["execution_report_identity"] = _identity(report_path, v6)
            manifest["artifacts"][2] = _identity(report_path, v6)
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(self.builder.CoveragePolicyError, "package count"):
                self.builder._load_v6(v6)

    def test_v6_package_scalar_counts_must_match_arrays_descriptor_and_report(self):
        target = _target(1, "japan", 2024, "G1", "jp-g1")
        for field in ("record_count", "gap_count", "accounted_count", "scope_count"):
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, v6, _ = _fixture(root, [target], records=[_complete_record(target)])
                package_path = v6 / "run" / "main-01" / "package-manifest.json"
                package = _read_json(package_path)
                package[field] = int(package[field]) + 1
                _write_json(package_path, package)
                _rebind_v6_package(v6, package_path)
                with self.assertRaisesRegex(self.builder.CoveragePolicyError, "package scalar"):
                    self.builder._load_v6(v6)

    def test_remaining_verifier_ignores_best_effort_and_new_but_blocks_hard(self):
        hard = _target(1, "united_kingdom", 2024, "G1", "uk-g1")
        soft = _target(2, "united_kingdom", 2024, "G2", "uk-g2")
        new = _target(3, "united_kingdom", 2025, "G2", "uk-new")
        with TemporaryDirectory() as tmp:
            _, _, out, *_ = self._build(Path(tmp), [hard, soft, new])
            result = self.verifier.verify_coverage(out, phase="remaining_historical")
            self.assertFalse(result["passed"])
            self.assertEqual(result["blocking_target_ids"], [1])
            with self.assertRaisesRegex(self.verifier.CoverageVerificationError, "full_history"):
                self.verifier.verify_coverage(out, phase="full_history")

    def test_verifier_rejects_unknown_status_combinations_and_selection_mismatch(self):
        target = _target(1, "united_kingdom", 2024, "G1", "uk-g1")
        for field in (
            "coverage_tier",
            "detail_status",
            "detail_package_status",
            "accounting_status",
            "barrier_evidence_status",
        ):
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, _, out, *_ = self._build(root, [target], records=[_complete_record(target)])
                ledger_path = out / "coverage_ledger.jsonl"
                row = json.loads(ledger_path.read_text())
                self.assertEqual(row["detail_status"], "complete")
                self.assertEqual(row["accounting_status"], "satisfied")
                row[field] = "invented"
                _write_jsonl(ledger_path, [row])
                _rebind_output_artifact(out, "coverage_ledger.jsonl")
                with self.assertRaisesRegex(self.verifier.CoverageVerificationError, "unknown"):
                    self.verifier.verify_coverage(out, phase="remaining_historical")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, out, *_ = self._build(root, [target], records=[_complete_record(target)])
            ledger_path = out / "coverage_ledger.jsonl"
            row = json.loads(ledger_path.read_text())
            row["detail_status"] = "gap"
            _write_jsonl(ledger_path, [row])
            _rebind_output_artifact(out, "coverage_ledger.jsonl")
            with self.assertRaisesRegex(self.verifier.CoverageVerificationError, "combination"):
                self.verifier.verify_coverage(out, phase="remaining_historical")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, out, *_ = self._build(root, [target], records=[_complete_record(target)])
            selection = out / "historical_hard_selection.jsonl"
            selected = json.loads(selection.read_text())
            selected["target_sha256"] = "f" * 64
            _write_jsonl(selection, [selected])
            _rebind_output_artifact(out, "historical_hard_selection.jsonl")
            with self.assertRaisesRegex(self.verifier.CoverageVerificationError, "selection"):
                self.verifier.verify_coverage(out, phase="remaining_historical")

    def test_summary_manifest_and_selection_counts_are_conserved(self):
        targets = [_target(1, "japan", 2024, "G1", "jp-g1"), _target(2, "france", 2024, "G2", "fr-g2"), _target(3, "united_states", 2025, "G3", "us-new")]
        with TemporaryDirectory() as tmp:
            result, rows, out, *_ = self._build(Path(tmp), targets)
            summary = json.loads((out / "summary.json").read_text())
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(summary["coverage_tier_counts"].values()), 3)
            self.assertEqual(sum(summary["detail_status_counts"].values()), 3)
            self.assertEqual(manifest["target_count"], 3)
            self.assertEqual(result["target_count"], 3)
            for name in ("historical_hard_selection.jsonl", "historical_best_effort_selection.jsonl", "new_formal_selection.jsonl", "priority_shards.json", "gap_review_ledger.jsonl", "coverage_ledger.jsonl"):
                self.assertIn(name, manifest["artifacts"])

    def test_build_cli_canonicalizes_all_relative_paths_without_weakening_escape_gate(self):
        target = _target(1, "japan", 2024, "G1", "jp-g1")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            v9, v6, out = _fixture(root, [target], records=[_complete_record(target)])
            policy_doc = root / "policy.md"
            policy_config = root / "policy.json"
            policy_doc.write_bytes(POLICY_DOC.read_bytes())
            policy_config.write_bytes(POLICY_CONFIG.read_bytes())

            report_path = v6 / "execution_report.json"
            report = _read_json(report_path)
            for section in ("main_descriptors", "smoke"):
                for descriptor in report[section]:
                    identity = descriptor["package_identity"]
                    identity["path"] = str((v6 / identity["path"]).resolve())
            _write_json(report_path, report)
            manifest_path = v6 / "manifest.json"
            manifest = _read_json(manifest_path)
            manifest["execution_report_identity"] = _identity(report_path, v6)
            manifest["artifacts"][2] = _identity(report_path, v6)
            _write_json(manifest_path, manifest)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_TOOL),
                    "--v9-root", "v9",
                    "--v6-root", "v6",
                    "--policy-doc", "policy.md",
                    "--config", "policy.json",
                    "--output-root", "out",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )
            if completed.returncode != 0:
                self.assertFalse(out.exists())
                self.assertEqual(list(root.glob(".out.*")), [])
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            output_manifest = _read_json(out / "manifest.json")
            self.assertTrue(Path(result["output_root"]).is_absolute())
            self.assertTrue(Path(output_manifest["v9_identity"]["manifest"]["path"]).is_absolute())
            self.assertTrue(Path(output_manifest["v6_identity"]["manifest"]["path"]).is_absolute())
            self.assertTrue(Path(output_manifest["policy_document_identity"]["path"]).is_absolute())
            self.assertTrue(Path(output_manifest["policy_config_identity"]["path"]).is_absolute())
            self.assertFalse(Path(output_manifest["v6_identity"]["main_packages"][0]["path"]).is_absolute())

            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            escape = v6 / "escape.json"
            escape.symlink_to(outside)
            with self.assertRaisesRegex(self.builder.CoveragePolicyError, "escapes root"):
                self.builder._resolve_inside(v6.resolve(), "escape.json")

    def test_cli_accepts_only_remaining_historical_phase(self):
        completed = subprocess.run([sys.executable, str(VERIFY_TOOL), "--artifact-root", "/missing", "--phase", "full_history"], text=True, capture_output=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("full_history", completed.stderr)
