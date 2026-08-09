from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.research import build_official_graded_race_manifest as builder
from runtime.research import collect_official_graded_race_results as runner


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

    def test_australia_review_can_bind_two_races_to_one_meeting_page(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            fields=["country_region","country","year","series_key","canonical_name_original","source_race_name","grade_text","racecourse","distance_text","surface","expectation_status","raw_source_url"]
            rows=[
                {"country_region":"australia","country":"australia","year":"2025","series_key":"au-one","canonical_name_original":"KINDERGARTEN STAKES","source_race_name":"WIDDEN KINDERGARTEN STAKES","grade_text":"G3","racecourse":"Royal Randwick","distance_text":"1100","surface":"turf","expectation_status":"held","raw_source_url":"https://racingaustralia.horse/2025"},
                {"country_region":"australia","country":"australia","year":"2025","series_key":"au-two","canonical_name_original":"ADRIAN KNOX STAKES","source_race_name":"TAB ADRIAN KNOX STAKES","grade_text":"G3","racecourse":"Royal Randwick","distance_text":"2000","surface":"turf","expectation_status":"held","raw_source_url":"https://racingaustralia.horse/2025"},
            ]
            catalog=root/"australia.csv"
            with catalog.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            review=builder.prepare_review([catalog],year=2025)
            review.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"})
            url="https://www.racingaustralia.horse/FreeFields/Results.aspx?Key=2025Apr05%2CNSW%2CRoyal+Randwick"
            for item in review["items"]:
                item.update({"disposition":"collect","result_url":url,"local_date":"2025-04-05"})
            reviewed=root/"reviewed.json"; reviewed.write_bytes(builder.canonical_json_bytes(review))
            manifest,_,_=builder.compile_review([catalog],year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))
        self.assertEqual(len(manifest["races"]),2)
        self.assertEqual({race["source_race_name"] for race in manifest["races"]},{"WIDDEN KINDERGARTEN STAKES","TAB ADRIAN KNOX STAKES"})

    def test_australia_punctuation_equivalent_selectors_are_duplicates(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            fields=["country_region","country","year","series_key","canonical_name_original","source_race_name","grade_text","racecourse","distance_text","surface","expectation_status","raw_source_url"]
            rows=[]
            for key,name in (("au-one","C.F. ORR STAKES"),("au-two","cf orr stakes")):
                rows.append({"country_region":"australia","country":"australia","year":"2025","series_key":key,"canonical_name_original":name,"source_race_name":name,"grade_text":"G1","racecourse":"Caulfield","distance_text":"1400","surface":"turf","expectation_status":"held","raw_source_url":"https://racingaustralia.horse/2025"})
            catalog=root/"australia.csv"
            with catalog.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            review=builder.prepare_review([catalog],year=2025)
            review.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"})
            url="https://www.racingaustralia.horse/FreeFields/Results.aspx?Key=2025Feb08%2CVIC%2CCaulfield"
            for item in review["items"]:
                item.update({"disposition":"collect","result_url":url,"local_date":"2025-02-08"})
            reviewed=root/"reviewed.json"; reviewed.write_bytes(builder.canonical_json_bytes(review))
            with self.assertRaisesRegex(builder.ManifestBuildError,"duplicates provider/result_url"):
                builder.compile_review([catalog],year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

    def test_official_distance_override_requires_provider_evidence_and_is_preserved(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root)
            review=builder.prepare_review(catalogs,year=2025)
            review.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"})
            for item in review["items"]:
                if item["provider"] == "qa_qrec":
                    item.update({
                        "disposition":"collect",
                        "result_url":"https://qrec.gov.qa/race-calendar?racedate=2025-02-15&meetid=10270&raceid=25612&tab=Results",
                        "local_date":"2025-02-15",
                        "actual_distance":"2300",
                        "distance_override_reason":builder.DISTANCE_OVERRIDE_REASON,
                        "distance_override_evidence_url":"https://qrec.gov.qa/race-calendar?racedate=2025-02-15&meetid=10270&raceid=25612&tab=Results",
                    })
                else:
                    item.update({
                        "disposition":"evidence_gap",
                        "gap_reason":"stable_public_result_unavailable",
                        "evidence_url":"https://www.deutscher-galopp.de/2025/results",
                    })
            reviewed=root/"reviewed.json"; reviewed.write_bytes(builder.canonical_json_bytes(review))
            manifest,_,_=builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))
            race=manifest["races"][0]
            self.assertEqual((race["distance"],race["catalog_distance"]),("2300","2000"))
            self.assertEqual(race["distance_override_reason"],builder.DISTANCE_OVERRIDE_REASON)

            payload=json.loads(reviewed.read_text()); qatar=next(item for item in payload["items"] if item["provider"]=="qa_qrec")
            qatar["distance_override_evidence_url"]="https://www.deutscher-galopp.de/2025/results"
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(ValueError,"outside allowlist"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

    def test_australia_override_selector_is_consistent_with_runner(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            fields=["country_region","country","year","series_key","canonical_name_original","source_race_name","grade_text","racecourse","distance_text","surface","expectation_status","raw_source_url"]
            rows=[]
            for key,name,distance in (("au-one","Race One","1100"),("au-two","Race Two","1200")):
                rows.append({"country_region":"australia","country":"australia","year":"2025","series_key":key,"canonical_name_original":name,"source_race_name":"SHARED STAKES","grade_text":"G3","racecourse":"Caulfield","distance_text":distance,"surface":"turf","expectation_status":"held","raw_source_url":"https://racingaustralia.horse/2025"})
            catalog=root/"australia.csv"
            with catalog.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            review=builder.prepare_review([catalog],year=2025)
            review.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"})
            url="https://www.racingaustralia.horse/FreeFields/Results.aspx?Key=2025Feb08%2CVIC%2CCaulfield"
            for item in review["items"]:
                item.update({"disposition":"collect","result_url":url,"local_date":"2025-02-08","actual_distance":"1300","distance_override_reason":builder.DISTANCE_OVERRIDE_REASON,"distance_override_evidence_url":url})
            reviewed=root/"reviewed.json"; reviewed.write_bytes(builder.canonical_json_bytes(review))
            with self.assertRaisesRegex(builder.ManifestBuildError,"duplicates provider/result_url"):
                builder.compile_review([catalog],year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

            rows[1]["distance_text"]="1100"
            with catalog.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            payload=builder.prepare_review([catalog],year=2025)
            payload.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"})
            for item,actual_distance in zip(payload["items"],("1300","1400"),strict=True):
                item.update({"disposition":"collect","result_url":url,"local_date":"2025-02-08","actual_distance":actual_distance,"distance_override_reason":builder.DISTANCE_OVERRIDE_REASON,"distance_override_evidence_url":url})
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            manifest,_,_=builder.compile_review([catalog],year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))
            manifest_path=root/"manifest.json"; manifest_path.write_bytes(builder.canonical_json_bytes(manifest))
            normalized,_=runner.load_manifest(manifest_path,expected_sha256=builder.sha256_file(manifest_path))
            self.assertEqual({race["distance"] for race in normalized["races"]},{"1300","1400"})

    def test_override_fields_are_rejected_for_gap_and_not_held(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); catalogs=self.catalogs(root); reviewed=self.reviewed(root,catalogs)
            payload=json.loads(reviewed.read_text()); gap=next(item for item in payload["items"] if item["disposition"]=="evidence_gap")
            gap["actual_distance"]="2300"
            reviewed.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(builder.ManifestBuildError,"must not carry collection fields"):
                builder.compile_review(catalogs,year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))

            fields=["country_region","country","year","series_key","canonical_name_original","grade_text","racecourse","distance_text","surface","expectation_status","raw_source_url"]
            catalog=root/"not-held.csv"
            with catalog.open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerow({"country_region":"germany","country":"germany","year":"2025","series_key":"not-held","canonical_name_original":"Not Held","grade_text":"G3","racecourse":"Cologne","distance_text":"2000","surface":"turf","expectation_status":"not_held","raw_source_url":"https://www.tjcis.com/2025.pdf"})
            review=builder.prepare_review([catalog],year=2025); review.update({"reviewed_by":"reviewer","reviewed_at":"2026-08-09T00:00:00Z"}); review["items"][0]["distance_override_reason"]=builder.DISTANCE_OVERRIDE_REASON
            reviewed.write_bytes(builder.canonical_json_bytes(review))
            with self.assertRaisesRegex(builder.ManifestBuildError,"not-held race mapping is invalid"):
                builder.compile_review([catalog],year=2025,reviewed_path=reviewed,expected_sha256=builder.sha256_file(reviewed))


if __name__ == "__main__": unittest.main()
