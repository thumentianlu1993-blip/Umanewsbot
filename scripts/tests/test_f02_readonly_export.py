"""F02 合成离线样例；禁止访问真实数据库/网络。"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from scripts import f02_readonly_export as export


def sample_snapshot():
    return {
        "observation": {"observed_at": "2026-10-03T00:00:00+00:00", "start": "2026-09-05T00:00:00+00:00",
                        "read_only": "on", "isolation": "repeatable read", "release_sha": "a" * 40},
        "counts": {"cohort": 2, "sources": 1, "crawl_jobs": 1, "windows": 1, "decisions": 0, "homepage_exposures": 0},
        "region_counts": {"japan": 2},
        "cohort": [
            {"id": 1, "racing_region": "japan", "workflow_status": "translation_failed", "translation_status": "failed",
             "has_original_html": False, "empty_body": True, "input_sha256": "b" * 64,
             "body_ja_raw": "PRIVATE ARTICLE", "editor_notes": "SECRET"},
            {"id": 2, "racing_region": "japan", "workflow_status": "pending_review", "translation_status": "translated",
             "has_original_html": True, "empty_body": False, "input_sha256": "c" * 64},
        ],
        "sources": [{"id": 3, "racing_region": "japan", "source_site": "jra"}],
        "crawl_jobs": [{"id": 4, "source_id": None, "status": "failed", "error_message": "PASSWORD"}],
        "windows": [{"id": 5, "kind": "publish", "status": "succeeded"}],
        "decisions": [], "homepage_exposures": [],
        "aggregates": [{"racing_region": "japan", "workflow_status": "translation_failed", "article_count": 1},
                       {"racing_region": "japan", "workflow_status": "pending_review", "article_count": 1}],
    }


class MetadataTests(unittest.TestCase):
    def test_failed_unpublished_and_unknown_crawl_retained_without_raw_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            receipt = export.publish_metadata(sample_snapshot(), root, "synthetic-001")
            self.assertTrue(receipt["complete"])
            directory = root / "synthetic-001"
            rows = [json.loads(x) for x in (directory / "cohort_metadata.jsonl").read_text().splitlines()]
            self.assertEqual([r["workflow_status"] for r in rows], ["translation_failed", "pending_review"])
            all_text = "".join(f.read_text() for f in directory.iterdir())
            for secret in ["PRIVATE ARTICLE", "SECRET", "PASSWORD"]:
                self.assertNotIn(secret, all_text)
            crawl = json.loads((directory / "crawl_jobs.jsonl").read_text())
            self.assertIsNone(crawl["source_id"])
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            manifest = json.loads((directory / "manifest.json").read_text())
            for name, digest in manifest["files"].items():
                file = directory / name
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), digest)

    def test_budget_duplicate_unsafe_transaction_and_partial_count_rejected(self):
        mutations = [lambda s: s["counts"].update(cohort=10001),
                     lambda s: s["cohort"][1].update(id=1),
                     lambda s: s["observation"].update(read_only="off"),
                     lambda s: s["counts"].update(cohort=3),
                     lambda s: s["region_counts"].update(japan=1),
                     lambda s: s["aggregates"][0].update(article_count=0)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve() / "runtime/next_version/F02"
                snapshot = sample_snapshot()
                mutate(snapshot)
                with self.assertRaises(export.ExportError):
                    export.publish_metadata(snapshot, root, "bad")
                self.assertFalse(root.exists())

    def test_existing_directory_and_symlink_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            export.publish_metadata(sample_snapshot(), root, "once")
            prior = (root / "once/manifest.json").read_bytes()
            with self.assertRaises(export.ExportError):
                export.publish_metadata(sample_snapshot(), root, "once")
            self.assertEqual((root / "once/manifest.json").read_bytes(), prior)
            link = Path(tmp).resolve() / "link"
            link.symlink_to(root.parent.parent, target_is_directory=True)
            with self.assertRaises(export.ExportError):
                export.publish_metadata(sample_snapshot(), link / "next_version/F02", "other")

    def test_file_write_failure_does_not_publish_complete_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            with patch.object(export.os, "fsync", side_effect=OSError("PRIVATE database detail")):
                with self.assertRaises(OSError):
                    export.publish_metadata(sample_snapshot(), root, "partial")
            self.assertFalse((root / "partial").exists())

    def test_each_budget_accepts_equality_and_rejects_one_more(self):
        for dataset in export.LIMITS:
            for limit in [1, 0]:
                with self.subTest(dataset=dataset, limit=limit), tempfile.TemporaryDirectory() as tmp:
                    snapshot = sample_snapshot()
                    # Keep first row (cohort has two) and update all related exact denominators.
                    snapshot[dataset] = snapshot[dataset][:1]
                    if not snapshot[dataset]:
                        snapshot[dataset] = [{"id": 8}]
                    snapshot["counts"][dataset] = len(snapshot[dataset])
                    if dataset == "cohort":
                        snapshot["region_counts"] = {"japan": 1}
                        snapshot["aggregates"] = snapshot["aggregates"][:1]
                    root = Path(tmp).resolve() / "runtime/next_version/F02"
                    limits = dict(export.LIMITS, **{dataset: limit})
                    with patch.object(export, "LIMITS", limits):
                        if limit == 1:
                            export.publish_metadata(snapshot, root, "equal")
                        else:
                            with self.assertRaises(export.ExportError):
                                export.publish_metadata(snapshot, root, "overflow")


class RedactionTests(unittest.TestCase):
    def test_sensitive_html_removed_with_legitimate_paragraph_order_retained(self):
        raw = '<p>First</p><script>TOKEN</script><form><input value="PASSWORD"></form><div class="account">COOKIE</div><p>Last</p>'
        clean = export.redact_html(raw)
        self.assertIn("First", clean)
        self.assertIn("Last", clean)
        self.assertLess(clean.index("First"), clean.index("Last"))
        for secret in ["TOKEN", "PASSWORD", "COOKIE"]:
            self.assertNotIn(secret, clean)

    def test_nested_sensitive_blocks_attributes_and_text_credentials(self):
        raw = '<section><p>Kept</p><form><div><p>PRIVATE</p></div></form><p onclick="SECRET">Final</p></section>'
        clean = export.redact_html(raw)
        self.assertIn("Kept", clean)
        self.assertIn("Final", clean)
        self.assertNotIn("PRIVATE", clean)
        self.assertNotIn("SECRET", clean)
        clean = export.redact_text('mail me@example.test token=SECRET https://u:p@example.test/a?q=TOKEN#FRAGMENT')
        for secret in ["me@example.test", "SECRET", "TOKEN", "FRAGMENT", "u:p"]:
            self.assertNotIn(secret, clean)


def sample_content():
    row = {"id": 7, "title_ja": "Synthetic First", "body_ja_raw": "Synthetic First\nLast",
           "body_ja_normalized": "Synthetic First\nLast", "original_content_html": '<p>First</p><script>TOKEN</script><p>Last</p>',
           "source_url": "https://USER:PASSWORD@example.test/news?token=SECRET#COOKIE",
           "updated_at": "2026-10-03T00:00:00+00:00", "title_zh": "合成标题", "body_zh": "合成正文"}
    sha = hashlib.sha256((row["title_ja"] + "\n" + row["body_ja_normalized"]).encode()).hexdigest()
    selection = {"custodian": "R", "source_observation_id": "synthetic-metadata", "release_sha": "a" * 40,
                 "samples": [{"id": 7, "input_sha256": sha, "updated_at": row["updated_at"]}]}
    return row, selection


class ContentTests(unittest.TestCase):
    def test_content_only_to_R_files_stdout_receipt_has_no_text(self):
        row, selection = sample_content()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            receipt = export.publish_content([row], selection, root, "sealed")
            self.assertNotIn("Synthetic First", json.dumps(receipt))
            saved = json.loads((root / "sealed/content.jsonl").read_text())
            self.assertEqual(saved["source_url"], "https://example.test/news")
            self.assertNotIn("TOKEN", saved["original_content_html"])
            self.assertEqual(saved["human_verification_status"], "not_reviewed")
            self.assertNotEqual(saved["raw_content_sha256"], saved["redacted_content_sha256"])

    def test_wrong_custodian_drift_missing_and_over_budget_fail_closed(self):
        for mode in ["B", "drift", "missing", "size", "duplicates"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                row, selection = sample_content()
                if mode == "B": selection["custodian"] = "B"
                if mode == "drift": row["updated_at"] = "2026-10-04T00:00:00+00:00"
                if mode == "size": row["original_content_html"] = "x" * (512 * 1024 + 1)
                if mode == "duplicates": selection["samples"] *= 2
                root = Path(tmp).resolve() / "runtime/next_version/F02"
                with self.assertRaises(export.ExportError):
                    export.publish_content([] if mode == "missing" else [row], selection, root, "bad")
                self.assertFalse(root.exists())

    def test_selection_size_and_total_budget_and_body_hash_drift(self):
        for mode in ["count", "total", "hash"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                row, selection = sample_content()
                if mode == "count": selection["samples"] *= 151
                if mode == "hash": row["body_ja_normalized"] = "different"
                if mode == "total":
                    rows = [dict(row, id=i, original_content_html="x" * (250 * 1024)) for i in range(1, 151)]
                    selection["samples"] = [dict(selection["samples"][0], id=i) for i in range(1, 151)]
                else:
                    rows = [row]
                root = Path(tmp).resolve() / "runtime/next_version/F02"
                with self.assertRaises(export.ExportError):
                    export.publish_content(rows, selection, root, "bad")
                self.assertFalse(root.exists())


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []

    def execute(self, sql, params=None):
        self.connection.queries.append((sql, params))
        if "/* observation */" in sql:
            self.result = [sample_snapshot()["observation"]]
        elif "/* schema */" in sql:
            self.result = synthetic_schema()
            if self.connection.missing_schema:
                self.result.pop()
        elif "/* region_counts */" in sql:
            self.result = [{"racing_region": "japan", "n": 2}]
        elif "/* counts */" in sql:
            self.result = [sample_snapshot()["counts"]]
        elif "/* content_sizes */" in sql:
            self.result = [{"id": 7, "content_bytes": 1024}]
        elif "/* selected_content */" in sql:
            self.result = [sample_content()[0]]
        else:
            for key in (*export.LIMITS, "aggregates"):
                if "/* " + key + " */" in sql:
                    self.result = sample_snapshot()[key]
                    return
            self.result = []

    def fetchmany(self, n):
        if self.connection.timeout:
            raise TimeoutError("PRIVATE DSN=secret")
        return self.result[:n]

    def close(self):
        pass


class FakeConnection:
    def __init__(self, missing_schema=False, timeout=False):
        self.queries = []
        self.rollbacks = 0
        self.missing_schema = missing_schema
        self.timeout = timeout

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def synthetic_schema():
    return [{"table_name": table, "column_name": col} for table in sorted(export.REQUIRED_SCHEMA)
            for col in sorted(export.REQUIRED_SCHEMA[table])]


class DatabaseContractTests(unittest.TestCase):
    def test_readonly_snapshot_timeout_and_schema_before_business_queries(self):
        connection = FakeConnection()
        snapshot = export.collect_metadata(connection, "a" * 40, "d" * 64)
        sql = [q[0] for q in connection.queries]
        self.assertTrue(sql[0].startswith("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        self.assertTrue(any("statement_timeout" in q and "15s" in q for q in sql))
        self.assertTrue(any("lock_timeout" in q and "1s" in q for q in sql))
        schema_index = next(i for i, q in enumerate(sql) if "/* schema */" in q)
        counts_index = next(i for i, q in enumerate(sql) if "/* counts */" in q)
        self.assertLess(schema_index, counts_index)
        self.assertTrue(all("SELECT *" not in q for q in sql))
        self.assertEqual(snapshot["counts"]["cohort"], 2)
        self.assertEqual(connection.rollbacks, 1)

    def test_missing_schema_or_database_timeout_never_continues_to_details(self):
        for connection in [FakeConnection(missing_schema=True), FakeConnection(timeout=True)]:
            with self.subTest(connection=connection), self.assertRaises(export.ExportError):
                export.collect_metadata(connection, "a" * 40, "d" * 64)
            self.assertEqual(connection.rollbacks, 1)
            self.assertFalse(any("/* cohort */" in q[0] for q in connection.queries))

    def test_content_sizes_precede_raw_query_and_ids_are_parameters(self):
        _, selection = sample_content()
        selection["source_schema_sha256"] = export.digest(export.encoded(synthetic_schema()))
        connection = FakeConnection()
        rows = export.collect_content(connection, selection)
        self.assertEqual([r["id"] for r in rows], [7])
        sizes = next(i for i, (sql, _) in enumerate(connection.queries) if "/* content_sizes */" in sql)
        raw = next(i for i, (sql, _) in enumerate(connection.queries) if "/* selected_content */" in sql)
        self.assertLess(sizes, raw)
        self.assertEqual(connection.queries[raw][1], ([7],))
        self.assertNotIn("id=7", connection.queries[raw][0])
        selection["source_schema_sha256"] = "f" * 64
        connection = FakeConnection()
        with self.assertRaises(export.ExportError):
            export.collect_content(connection, selection)
        self.assertFalse(any("/* selected_content */" in sql for sql, _ in connection.queries))


class CommandTests(unittest.TestCase):
    def test_wrong_script_or_resident_binding_stops_before_connection_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            marker = Path(tmp) / "marker"
            marker.write_text("b" * 40)
            output = StringIO()
            with redirect_stdout(output), patch.object(export, "connect_database") as connect:
                result = export.main(["--mode", "metadata", "--output-root", str(root), "--observation-id", "bound",
                                      "--expected-release-sha", "a" * 40, "--resident-marker", str(marker),
                                      "--expected-script-sha256", "c" * 64])
            self.assertEqual(result, 1)
            connect.assert_not_called()
            self.assertFalse(root.exists())
            self.assertNotIn("PASSWORD", output.getvalue())

    def test_default_plan_mode_is_offline_and_only_outputs_hash_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            output = StringIO()
            with redirect_stdout(output), patch.object(export, "connect_database") as connect:
                result = export.main(["--output-root", str(root), "--observation-id", "plan"])
            self.assertEqual(result, 0)
            connect.assert_not_called()
            receipt = json.loads(output.getvalue())
            self.assertEqual(receipt["kind"], "plan")
            self.assertIn("manifest_sha256", receipt)

    def test_bound_live_metadata_with_fake_returns_counts_not_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "runtime/next_version/F02"
            marker = Path(tmp) / "marker"
            marker.write_text("a" * 40)
            script_sha = hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest()
            output = StringIO()
            with redirect_stdout(output), patch.object(export, "connect_database", return_value=FakeConnection()):
                result = export.main(["--mode", "metadata", "--output-root", str(root), "--observation-id", "bound",
                                      "--expected-release-sha", "a" * 40, "--resident-marker", str(marker),
                                      "--expected-script-sha256", script_sha])
            self.assertEqual(result, 0)
            self.assertNotIn("PRIVATE", output.getvalue())
            self.assertNotIn("SECRET", output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["counts"]["cohort"], 2)

    def test_selection_requires_private_file_exact_hash_and_source_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "selection.json"
            _, selection = sample_content()
            selection.update(source_schema_sha256="d" * 64, source_metadata_manifest_sha256="e" * 64)
            path.write_bytes(export.encoded(selection))
            path.chmod(0o600)
            sha = export.digest(path.read_bytes())
            self.assertEqual(export.bound_selection(path, sha, "a" * 40)["custodian"], "R")
            with self.assertRaises(export.ExportError):
                export.bound_selection(path, "f" * 64, "a" * 40)
            path.chmod(0o644)
            with self.assertRaises(export.ExportError):
                export.bound_selection(path, sha, "a" * 40)


if __name__ == "__main__":
    unittest.main()
