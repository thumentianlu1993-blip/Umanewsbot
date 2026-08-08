from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.research import build_official_graded_race_manifest as builder


class OfficialManifestBuilderTests(unittest.TestCase):
    def catalogs(self, root: Path):
        fields = ["country_region", "country", "year", "series_key", "canonical_name_original", "grade_text", "racecourse", "distance_text", "surface", "expectation_status", "raw_source_url"]
        rows = [
            {"country_region":"germany","country":"germany","year":"2025","series_key":"de-one","canonical_name_original":"Preis One","grade_text":"G1","racecourse":"Cologne","distance_text":"2000","surface":"turf","expectation_status":"held","raw_source_url":"https://www.tjcis.com/2025.pdf"},
            {"country_region":"middle_east","country":"qatar","year":"2025","series_key":"qa-two","canonical_name_original":"Qatar Two","grade_text":"G1","racecourse":"Al Rayyan","distance_text":"2000","surface":"turf","expectation_status":"held","raw_source_url":"https://www.tjcis.com/2025.pdf"},
        ]
        path=root/"catalog.csv"
        with path.open("w",encoding="utf-8",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        return [path]

    def reviewed(self, root: Path, catalogs: list[Path]):
        review=builder.prepare_review(catalogs,year=2025)
        review["reviewed_by"]="reviewer"; review["reviewed_at"]="2026-08-09T00:00:00Z"
        by_provider={item["provider"]:item for item in review["items"]}
        by_provider["de_deutscher_galopp"].update({"disposition":"collect","result_url":"https://www.deutscher-galopp.de/gr/renntage/rennen.php?datum=2025-06-01","local_date":"2025-06-01"})
        by_provider["qa_qrec"].update({"disposition":"evidence_gap","gap_reason":"stable_public_result_unavailable","evidence_url":"https://www.qrec.gov.qa/2025/results","review_notes":"No stable public result URL"})
        path=root/"reviewed.json"; path.write_bytes(builder.canonical_json_bytes(review))
        return path

    def test_compile_conserves_collect_and_gap(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root); reviewed=self.reviewed(root,catalogs)
            manifest,gaps,summary=builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))
        self.assertEqual((summary["catalog_count"],summary["collect_count"],summary["gap_count"]),(2,1,1))
        self.assertEqual(manifest["races"][0]["provider"],"de_deutscher_galopp")
        self.assertEqual(gaps["gaps"][0]["country"],"qatar")
        self.assertEqual(manifest["reviewed_mapping_sha256"],summary["reviewed_mapping_sha256"])
        self.assertEqual(summary["official_result_manifest_sha256"],builder.sha256_bytes(builder.canonical_json_bytes(manifest)))
        self.assertEqual(summary["official_result_gaps_sha256"],builder.sha256_bytes(builder.canonical_json_bytes(gaps)))

    def test_missing_or_drifted_mapping_fails_closed(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root); reviewed=self.reviewed(root,catalogs)
            payload=json.loads(reviewed.read_text()); payload["items"].pop(); reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(builder.ManifestBuildError,"cover the catalog exactly"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

    def test_review_sha_is_required(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root); reviewed=self.reviewed(root,catalogs)
            with self.assertRaisesRegex(builder.ManifestBuildError,"SHA-256 mismatch"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256="0"*64)

    def test_review_timestamp_and_gap_collection_fields_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root); reviewed=self.reviewed(root,catalogs)
            payload=json.loads(reviewed.read_text()); payload["reviewed_at"]="2026-08-09T00:00:00"
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(builder.ManifestBuildError,"timezone-aware"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

            payload["reviewed_at"]="2026-08-09T00:00:00Z"
            gap=next(item for item in payload["items"] if item["disposition"]=="evidence_gap")
            gap["result_url"]="https://www.qrec.gov.qa/2025/results"
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(builder.ManifestBuildError,"must not carry collection fields"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

    def test_duplicate_canonical_url_and_cross_provider_gap_evidence_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root); reviewed=self.reviewed(root,catalogs)
            payload=json.loads(reviewed.read_text())
            qatar=next(item for item in payload["items"] if item["provider"]=="qa_qrec")
            qatar["evidence_url"]="https://www.deutscher-galopp.de/2025/results"
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(builder.ManifestBuildError,"controlled reason"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

            catalog=catalogs[0]
            with catalog.open("a",encoding="utf-8",newline="") as handle:
                writer=csv.writer(handle)
                writer.writerow(["germany","germany","2025","de-three","Preis Three","G2","Cologne","1600","turf","held","https://www.tjcis.com/2025.pdf"])
            payload=builder.prepare_review(catalogs,year=2025)
            payload.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"})
            for item in payload["items"]:
                if item["provider"]=="de_deutscher_galopp":
                    item.update({"disposition":"collect","result_url":"https://www.deutscher-galopp.de/2025/result?a=1&b=2","local_date":"2025-06-01"})
                    if item["series_key"]=="de-three":
                        item["result_url"]="https://www.deutscher-galopp.de/2025/result?b=2&a=1"
                else:
                    item.update({"disposition":"evidence_gap","gap_reason":"stable_public_result_unavailable","evidence_url":"https://www.qrec.gov.qa/2025/results"})
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(builder.ManifestBuildError,"duplicates provider/result_url"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))


if __name__ == "__main__": unittest.main()
