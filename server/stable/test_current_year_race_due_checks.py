import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime/tools/classify_current_year_race_due_checks.py"
)
SPEC = importlib.util.spec_from_file_location("classify_current_year_race_due_checks", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.path.insert(0, str(MODULE_PATH.parent))
try:
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.pop(0)


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def target(target_id, *, series_key=None, region="france"):
    return {
        "target_id": target_id,
        "year": 2026,
        "series_key": series_key or f"series-{target_id}",
        "country_region": region,
        "target_sha256": f"{target_id}" * 64,
        "inventory_artifact_sha256": "a" * 64,
    }


def selection_payload(targets):
    return {"schema_version": "1.0", "targets": targets}


def pipeline_inputs(root, *, selection, date_matches, gaps):
    catalog = root / "source_catalog.json"
    catalog.write_text(json.dumps({"schema_version": "1.0", "sources": []}))
    request_manifest = root / "request_manifest.json"
    request_manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "selection": MODULE.identity(selection, root=root),
                "source_catalog": MODULE.identity(catalog, root=root),
            }
        )
    )
    parse_manifest = root / "parse_manifest.json"
    parse_manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "selection": MODULE.identity(selection, root=root),
                "source_catalog": MODULE.identity(catalog, root=root),
                "request_manifest": MODULE.identity(request_manifest, root=root),
                "artifacts": {
                    "date_matches": MODULE.identity(date_matches, root=root),
                    "gaps": MODULE.identity(gaps, root=root),
                },
            }
        )
    )
    return {
        "source_catalog_path": catalog,
        "request_manifest_path": request_manifest,
        "parse_manifest_path": parse_manifest,
    }


class CurrentYearRaceDueCheckTests(SimpleTestCase):
    def test_rejects_duplicate_target_ids_in_each_input(self):
        cases = {
            "selection": {
                "targets": [target(1), target(1, series_key="other-series")],
                "date_matches": [{"target_id": 1, "local_date": "2026-01-01"}],
                "gaps": [],
            },
            "date matches": {
                "targets": [target(1)],
                "date_matches": [
                    {"target_id": 1, "local_date": "2026-01-01"},
                    {"target_id": 1, "local_date": "2026-01-01"},
                ],
                "gaps": [],
            },
            "gaps": {
                "targets": [target(1)],
                "date_matches": [],
                "gaps": [
                    {"target_id": 1, "reason_code": "missing"},
                    {"target_id": 1, "reason_code": "missing"},
                ],
            },
        }
        for label, fixture in cases.items():
            with self.subTest(label=label), TemporaryDirectory() as temporary:
                root = Path(temporary)
                selection = root / "selection.json"
                selection.write_text(json.dumps(selection_payload(fixture["targets"])))
                date_matches = root / "date_matches.jsonl"
                gaps = root / "gaps.jsonl"
                write_jsonl(date_matches, fixture["date_matches"])
                write_jsonl(gaps, fixture["gaps"])
                inputs = pipeline_inputs(
                    root,
                    selection=selection,
                    date_matches=date_matches,
                    gaps=gaps,
                )

                with self.assertRaisesRegex(MODULE.DueCheckError, f"duplicate {label}"):
                    MODULE.classify_due_checks(
                        selection_path=selection,
                        **inputs,
                        date_matches_path=date_matches,
                        gaps_path=gaps,
                        cutoff=MODULE.date(2026, 7, 15),
                        output_dir=root / "classified",
                    )

    def test_date_matches_are_partitioned_and_only_due_events_are_applyable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.json"
            selection.write_text(
                json.dumps(
                    selection_payload([target(1), target(2), target(3)])
                )
            )
            date_matches = root / "date_matches.jsonl"
            write_jsonl(
                date_matches,
                [
                    {
                        "target_id": 1,
                        "local_date": "2026-07-15",
                        "country_region": "france",
                        "status": "finished",
                        "source_refs": {},
                    },
                    {
                        "target_id": 2,
                        "local_date": "2026-07-16",
                        "country_region": "france",
                        "status": "finished",
                        "source_refs": {},
                    },
                ],
            )
            gaps = root / "gaps.jsonl"
            write_jsonl(gaps, [{"target_id": 3, "reason_code": "source_match_not_unique"}])
            output = root / "classified"
            inputs = pipeline_inputs(
                root,
                selection=selection,
                date_matches=date_matches,
                gaps=gaps,
            )

            summary = MODULE.classify_due_checks(
                selection_path=selection,
                **inputs,
                date_matches_path=date_matches,
                gaps_path=gaps,
                cutoff=MODULE.date(2026, 7, 15),
                output_dir=output,
            )

            self.assertEqual(summary["due_event_count"], 1)
            self.assertEqual(summary["not_due_count"], 1)
            self.assertEqual(summary["due_check_pending_count"], 1)
            self.assertEqual(json.loads((output / "not_due.jsonl").read_text())["target_id"], 2)
            pending = json.loads((output / "due_gaps.jsonl").read_text())
            due_events = list(
                __import__("csv").DictReader(
                    (output / "events_france.csv").open(encoding="utf-8-sig")
                )
            )
            manifest = json.loads((output / "manifest.json").read_text())
            descriptor = json.loads((output / "apply_descriptor.json").read_text())
            self.assertEqual(pending["original_reason_code"], "source_match_not_unique")
            self.assertEqual([row["target_id"] for row in due_events], ["1"])
            self.assertEqual(
                set(manifest["apply_artifacts"]), {"events_france"}
            )
            self.assertEqual(
                set(descriptor["apply_artifacts"]), {"events_france"}
            )
            self.assertNotIn("date_matches", descriptor)
            self.assertNotIn("raw_events", descriptor)

    def test_unmatched_hong_kong_target_without_official_date_stays_pending(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.json"
            selection.write_text(
                json.dumps(selection_payload([target(1, region="hong_kong")]))
            )
            date_matches = root / "date_matches.jsonl"
            gaps = root / "gaps.jsonl"
            write_jsonl(date_matches, [])
            write_jsonl(
                gaps,
                [
                    {
                        "target_id": 1,
                        "reason_code": "official_schedule_match_missing",
                    }
                ],
            )
            output = root / "classified"
            inputs = pipeline_inputs(
                root,
                selection=selection,
                date_matches=date_matches,
                gaps=gaps,
            )

            summary = MODULE.classify_due_checks(
                selection_path=selection,
                **inputs,
                date_matches_path=date_matches,
                gaps_path=gaps,
                cutoff=MODULE.date(2026, 7, 15),
                output_dir=output,
            )
            pending = json.loads((output / "due_gaps.jsonl").read_text())

        self.assertEqual(summary["not_due_count"], 0)
        self.assertEqual(summary["due_check_pending_count"], 1)
        self.assertEqual(pending["due_state"], "due_check_pending")

    def test_requires_full_non_overlapping_accounting(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.json"
            selection.write_text(json.dumps(selection_payload([target(1)])))
            date_matches = root / "date_matches.jsonl"
            gaps = root / "gaps.jsonl"
            write_jsonl(date_matches, [{"target_id": 1, "local_date": "2026-01-01"}])
            write_jsonl(gaps, [{"target_id": 1, "reason_code": "conflict"}])
            inputs = pipeline_inputs(
                root,
                selection=selection,
                date_matches=date_matches,
                gaps=gaps,
            )

            with self.assertRaisesRegex(MODULE.DueCheckError, "overlap"):
                MODULE.classify_due_checks(
                    selection_path=selection,
                    **inputs,
                    date_matches_path=date_matches,
                    gaps_path=gaps,
                    cutoff=MODULE.date(2026, 7, 15),
                    output_dir=root / "classified",
                )
