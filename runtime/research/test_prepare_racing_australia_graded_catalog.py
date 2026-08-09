from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.tools import prepare_racing_australia_graded_catalog as catalog


def page(*rows: list[str]) -> str:
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    ) + "</table>"


class RacingAustraliaCatalogTests(unittest.TestCase):
    def test_season_identity_must_bracket_calendar_year(self):
        sources=[
            ("https://racingaustralia.horse/arb/Group_ListedRaceDates/2024-2025.aspx",Path("/artifact/source/australia/first.html")),
            ("https://racingaustralia.horse/arb/Group_ListedRaceDates/2025-2026.aspx",Path("/artifact/source/australia/second.html")),
        ]
        catalog.validate_adjacent_seasons(sources,year=2025)
        with self.assertRaisesRegex(catalog.CatalogError,"adjacent"):
            catalog.validate_adjacent_seasons(sources[:1],year=2025)
        duplicate_names=[(sources[0][0],Path("/artifact/source/australia/same.html")),(sources[1][0],Path("/artifact/source/australia/same.html"))]
        with self.assertRaisesRegex(catalog.CatalogError,"basenames"):
            catalog.validate_adjacent_seasons(duplicate_names,year=2025)

    def test_two_seasons_are_filtered_to_one_calendar_year(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.html"
            second = root / "second.html"
            first.write_text(
                page(
                    ["08-Feb-25", "393", "1", "G1", "VIC", "MRC", "CAUL", "C.F. ORR STAKES", "1400", "$1", "O", "O", "WFA", "C.F. ORR STAKES"],
                    ["08-Feb-24", "393", "1", "G1", "VIC", "MRC", "CAUL", "OLD", "1400", "$1", "O", "O", "WFA", "OLD"],
                ),
                encoding="utf-8",
            )
            second.write_text(
                page(
                    ["15/Nov/2025", "393", "1", "G1", "VIC", "MRC", "Caulfield", "SPONSOR C.F. ORR STAKES", "1,400", "$1", "O", "O", "WFA", "C.F. ORR STAKES"],
                    ["15-Nov-25", "999", "4", "LR", "VIC", "MRC", "Caulfield", "LISTED", "1200", "$1", "O", "O", "WFA", "LISTED"],
                ),
                encoding="utf-8",
            )

            rows = catalog.parse_rows("https://racingaustralia.horse/first.aspx", first, year=2025)
            rows += catalog.parse_rows("https://racingaustralia.horse/second.aspx", second, year=2025)

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["local_date"] for row in rows], ["2025-02-08", "2025-11-15"])
        self.assertEqual(rows[0]["racecourse"], "Caulfield")
        self.assertEqual(rows[0]["source_state"], "VIC")
        self.assertEqual(rows[0]["raw_source_cache_path"], "source/australia/first.html")
        self.assertNotEqual(rows[0]["series_key"], rows[1]["series_key"])
        self.assertEqual(rows[1]["source_race_name"], "SPONSOR C.F. ORR STAKES")

    def test_invalid_state_identity_fails_closed(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/"source.html"
            path.write_text(page(["08-Feb-25","393","1","G1","","MRC","CAUL","C.F. ORR STAKES","1400","$1","O","O","WFA","C.F. ORR STAKES"]),encoding="utf-8")
            with self.assertRaisesRegex(catalog.CatalogError,"state identity"):
                catalog.parse_rows("https://racingaustralia.horse/2024-2025.aspx",path,year=2025)


if __name__ == "__main__":
    unittest.main()
