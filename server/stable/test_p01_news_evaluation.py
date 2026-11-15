"""真实输入与人工标注不能由 DOM fixture 或自评替代。"""
from tempfile import TemporaryDirectory
from pathlib import Path
from django.test import SimpleTestCase
from stable.services.news_evaluation import inventory_files, validate_gold, evaluation_package


class EvaluationManifestTests(SimpleTestCase):
    def test_cached_fixture_is_not_automatically_real_gold(self):
        with TemporaryDirectory() as root:
            Path(root, "fixture.html").write_text("<p>合成新闻</p>")
            inventory = inventory_files(root, [{"path": "fixture.html", "region": "japan", "origin": "synthetic_fixture"}])
        self.assertFalse(inventory["files"][0]["eligible_for_gold"])
        self.assertEqual(inventory["real_provenance_count"], 0)
        self.assertFalse(evaluation_package(inventory["files"], [])["package_ready"])

    def test_missing_gold_and_model_prices_are_explicitly_incomplete(self):
        with TemporaryDirectory() as root:
            result = validate_gold([], root=root)
        self.assertFalse(result["valid"])
        self.assertIn("requires_100_samples", result["errors"])
        package = evaluation_package([], [])
        self.assertEqual(package["status"], "NOT_RUN")
        self.assertEqual(package["external_calls_executed"], 0)

    def test_same_cached_content_cannot_fill_gold_with_different_ids(self):
        import hashlib
        from stable.services.news_pipeline import REGIONS
        with TemporaryDirectory() as root:
            raw = b"one real cached source"
            Path(root, "source.html").write_bytes(raw)
            rows = [{"id": str(i), "path": "source.html", "sha256": hashlib.sha256(raw).hexdigest(),
                "region": region, "split": "holdout" if j < 5 else "development", "event_key": str(i),
                "origin": "cached_real", "provenance": "cached source", "source_url": "https://example.invalid/story",
                "annotation_origin": "human", "annotator": "reviewer", "annotations": {
                    "body_blocks": ["body"], "entities": [], "facts": [], "editorial": {"priority": "regional"}}}
                for i, (region, j) in enumerate((r, j) for r in REGIONS for j in range(20))]
            result = validate_gold(rows, root=root)
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate_source" in error for error in result["errors"]))
