import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("audit_graded_horse_artifact.py")
SPEC = importlib.util.spec_from_file_location("audit_graded_horse_artifact", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


class ArtifactAuditTests(unittest.TestCase):
    def write_csv(self, path, fieldnames, rows):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def make_artifact(self, root):
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        participants = [
            {"region": "united_kingdom", "race_url": "https://example.test/races/race-a/"},
            {"region": "united_kingdom", "race_url": "https://example.test/races/race-a/"},
            {"region": "france", "race_url": "https://example.test/races/race-b/"},
        ]
        self.write_csv(root / "race_participants_2025.csv", participants[0], participants)
        horses = [
            {
                "horse_key": "one",
                "regions": "united_kingdom",
                "profile_resolution_state": "not_found",
                "required_english_status": "missing",
            },
            {
                "horse_key": "two",
                "regions": "france",
                "profile_resolution_state": "resolved",
                "required_english_status": "complete",
            },
        ]
        self.write_csv(root / "horse_names_2025.csv", horses[0], horses)
        self.write_csv(root / "horse_name_review_queue_2025.csv", horses[0], horses[:1])
        errors = [
            {"stage": "horse_name", "error_code": "missing_required_english"},
            {"stage": "profile_identity", "error_code": "profile_not_found"},
        ]
        (root / "errors.json").write_text(json.dumps(errors), encoding="utf-8")
        manifest = [
            {"region": "united_kingdom", "url": "https://example.test/races/race-a/"},
            {"region": "france", "url": "https://example.test/races/race-b/"},
        ]
        (root / "source_manifest.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
        )
        summary = {
            "year": 2025,
            "outcome": "partial",
            "counts": {
                "errors": 2,
                "included_participant_rows": 3,
                "included_races": 2,
                "unique_horses": 2,
                "profile_ambiguous": 0,
                "profile_not_found": 1,
                "profile_resolved": 1,
                "profile_unresolved": 0,
                "required_english_complete": 1,
                "required_english_missing": 1,
            },
        }
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def test_reports_reproducible_gap_census_and_production_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            snapshot = root.parent / f"{root.name}-production.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "events": [
                            {"slug": "race-a"},
                            {"slug": "race-b"},
                            {"slug": "race-c"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            try:
                result = audit.audit_artifact(root, year=2025, production_snapshot=snapshot)
            finally:
                snapshot.unlink()

        self.assertEqual(result["participants"]["rows_by_region"], {"france": 1, "united_kingdom": 2})
        self.assertEqual(result["participants"]["races_by_region"], {"france": 1, "united_kingdom": 1})
        self.assertEqual(result["errors"]["by_stage"], {"horse_name": 1, "profile_identity": 1})
        self.assertEqual(result["production_diff"], {"artifact_only": [], "production_only": ["race-c"], "shared": 2})

    def test_rejects_unknown_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            (root / "unexpected.txt").write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(audit.AuditError, "unexpected"):
                audit.audit_artifact(root, year=2025)

    def test_rejects_summary_count_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            summary["counts"]["unique_horses"] = 3
            (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(audit.AuditError, "summary count mismatch"):
                audit.audit_artifact(root, year=2025)

    def test_expected_digest_manifest_is_exact_and_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_artifact(root)
            digests = audit.verify_file_set(root, 2025)
            manifest = root.parent / f"{root.name}-digests.json"
            manifest.write_text(json.dumps(digests), encoding="utf-8")
            try:
                audit.audit_artifact(root, year=2025, expected_digests=manifest)
                digests["summary.json"] = "0" * 64
                manifest.write_text(json.dumps(digests), encoding="utf-8")
                with self.assertRaisesRegex(audit.AuditError, "digest mismatch"):
                    audit.audit_artifact(root, year=2025, expected_digests=manifest)
            finally:
                manifest.unlink()

    def test_race_identity_preserves_and_canonicalizes_query(self):
        first = audit.race_identity({"race_url": "HTTPS://Example.Test/rennen.php?race=1&date=2025-06-01#result"})
        same = audit.race_identity({"race_url": "https://example.test/rennen.php?date=2025-06-01&race=1"})
        second = audit.race_identity({"race_url": "https://example.test/rennen.php?date=2025-06-01&race=2"})
        self.assertEqual(first, same)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
