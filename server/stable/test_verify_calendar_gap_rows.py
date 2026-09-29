from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "verify_calendar_gap_rows.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("verify_calendar_gap_rows_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


REVIEW_HEADER = [
    "kind", "region", "ics_year", "ics_series_key", "ics_name", "ics_grade", "ics_racecourse",
    "production_id", "production_name", "production_year", "production_status",
    "production_result_count", "match_type", "issue",
]
PROD_HEADER = [
    "id", "year", "slug", "series_key", "original_name", "chinese_name", "country_region",
    "racecourse", "grade_text", "normalized_grade", "local_date", "status", "visibility_status", "result_count",
]


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


class VerifyCalendarGapRowsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def _run(self, root: Path, missing: list[dict], events: list[dict], aliases: list[dict] | None = None):
        review = _write_csv(
            root / "review.csv",
            REVIEW_HEADER,
            [
                {
                    "kind": "production_event", "region": row["region"], "ics_year": "2025",
                    "ics_series_key": row.get("series_key", ""), "ics_name": row["ics_name"],
                    "ics_grade": row.get("ics_grade", "G3"), "ics_racecourse": row.get("ics_racecourse", ""),
                    "production_id": "", "production_name": "", "production_year": "",
                    "production_status": "", "production_result_count": "", "match_type": "",
                    "issue": "missing_in_production",
                }
                for row in missing
            ],
        )
        prod = _write_csv(root / "prod.csv", PROD_HEADER, events)
        alias_path = None
        if aliases is not None:
            alias_path = _write_csv(root / "aliases.csv", ["event_id", "text", "source_language", "alias_type"], aliases)
        return self.module.verify_gaps(
            review_csv=review, production_csv=prod, aliases_csv=alias_path, ics_year="2025"
        )

    def test_truly_missing_when_no_candidate(self):
        with TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                missing=[{"region": "united_states", "ics_name": "Remsen S", "ics_racecourse": "Aqueduct"}],
                events=[],
            )
            self.assertEqual(result["counts"]["truly_missing"], 1)
            self.assertEqual(result["rows"][0]["classification"], "truly_missing")

    def test_exists_same_year_when_name_and_course_match(self):
        with TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                missing=[{"region": "united_states", "ics_name": "Bayakoa S", "ics_racecourse": "Del Mar"}],
                events=[
                    {
                        "id": "1091", "year": "2025", "slug": "x", "series_key": "",
                        "original_name": "BAYAKOA S.", "chinese_name": "", "country_region": "united_states",
                        "racecourse": "Del Mar", "grade_text": "G3", "normalized_grade": "G3",
                        "local_date": "2025-11-30", "status": "finished", "visibility_status": "published",
                        "result_count": "8",
                    }
                ],
            )
            self.assertEqual(result["counts"]["exists_same_year"], 1)
            self.assertEqual(result["rows"][0]["production_event_id"], "1091")

    def test_name_match_via_alias(self):
        with TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                missing=[{"region": "hong_kong", "ics_name": "Hong Kong Cup [LONGINES]", "ics_racecourse": "Sha Tin"}],
                events=[
                    {
                        "id": "1221", "year": "2025", "slug": "x", "series_key": "",
                        "original_name": "Hong Kong Cup", "chinese_name": "香港杯", "country_region": "hong_kong",
                        "racecourse": "Sha Tin", "grade_text": "G1", "normalized_grade": "G1",
                        "local_date": "2025-12-14", "status": "finished", "visibility_status": "published",
                        "result_count": "7",
                    }
                ],
                aliases=[{"event_id": "1221", "text": "Hong Kong Cup [LONGINES]", "source_language": "en", "alias_type": "alias"}],
            )
            self.assertEqual(result["counts"]["exists_same_year"], 1)

    def test_name_match_but_different_course_is_review(self):
        with TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                missing=[{"region": "united_states", "ics_name": "Bayakoa S", "ics_racecourse": "Del Mar"}],
                events=[
                    {
                        "id": "1095", "year": "2025", "slug": "x", "series_key": "",
                        "original_name": "Bayakoa S", "chinese_name": "", "country_region": "united_states",
                        "racecourse": "Oaklawn Park", "grade_text": "G3", "normalized_grade": "G3",
                        "local_date": "2025-02-08", "status": "finished", "visibility_status": "published",
                        "result_count": "8",
                    }
                ],
            )
            self.assertEqual(result["counts"]["exists_different_course"], 1)

    def test_wrong_year_does_not_count_as_match(self):
        with TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                missing=[{"region": "united_states", "ics_name": "Remsen S", "ics_racecourse": "Aqueduct"}],
                events=[
                    {
                        "id": "574", "year": "2026", "slug": "x", "series_key": "",
                        "original_name": "Remsen S", "chinese_name": "", "country_region": "united_states",
                        "racecourse": "Aqueduct", "grade_text": "G2", "normalized_grade": "G2",
                        "local_date": "2026-12-05", "status": "scheduled", "visibility_status": "published",
                        "result_count": "0",
                    }
                ],
            )
            self.assertEqual(result["counts"]["truly_missing"], 1)

    def test_generic_handicap_name_matches_via_sponsor(self):
        # "[Betfair Exchange] H. Stp" 这类名称主体过泛，身份靠冠名部分区分
        self.assertEqual(self.module._normalize("[Betfair Exchange] H. Stp"), "hstpbetfairexchange")
        self.assertEqual(self.module._normalize("Gold Cup H. Stp.[bet365]"), "goldcup")
        with TemporaryDirectory() as tmp:
            result = self._run(
                Path(tmp),
                missing=[{"region": "united_kingdom", "ics_name": "[Betfair Exchange] H. Stp", "ics_racecourse": "Cheltenham"}],
                events=[
                    {
                        "id": "1246", "year": "2025", "slug": "x", "series_key": "",
                        "original_name": "[Betfair Exchange] H. Stp", "chinese_name": "",
                        "country_region": "united_kingdom", "racecourse": "Cheltenham",
                        "grade_text": "G3", "normalized_grade": "G3",
                        "local_date": "2025-01-25", "status": "finished", "visibility_status": "published",
                        "result_count": "10",
                    }
                ],
            )
            self.assertEqual(result["counts"]["exists_same_year"], 1)
            self.assertEqual(result["rows"][0]["production_event_id"], "1246")
