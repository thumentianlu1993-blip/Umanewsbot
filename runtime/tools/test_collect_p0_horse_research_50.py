import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase

from runtime.tools.collect_p0_horse_research_50 import (
    BASIC_PROFILE_EVIDENCE,
    CAREER_RECORD_EVIDENCE,
    CAREER_RESULT_EVIDENCE,
    apply_basic_profile_verifications,
    apply_career_record_verifications,
    apply_career_result_verifications,
    apply_us_equibase_profile_verifications,
    deduplicate_us_visible_records,
    finalize_career_collection_status,
    from_japan_candidate,
    japan_candidates,
    parse_basic_profile_verifications,
    parse_career_record_verifications,
    parse_hrn_profile,
    parse_us_equibase_profile_verifications,
    summarize_field_status,
    load_career_result_verifications,
    load_us_equibase_profile_verifications,
    validate_us_equibase_profile_verification,
)
from runtime.tools.apply_p0_horse_manual_source_evidence import (
    DEFAULT_GAP_SNAPSHOT,
    TOOL_VERSION,
    apply_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
CAPTURED_RESEARCH_50 = (
    ROOT
    / "runtime/horse_profile_completion/research-50-parsed-20260718"
    / "p0_horse_research_50.json"
)
FINAL_ENRICHED_RESEARCH_50 = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719"
    / "p0_horse_research_50_enriched.json"
)


class JapanOfflineRebuildTests(SimpleTestCase):
    def test_all_ten_authorized_japan_candidates_rebuild_with_reconciled_counts(self):
        candidates = japan_candidates()

        rebuilt = [
            from_japan_candidate(candidate)
            for candidate in candidates.values()
        ]

        self.assertEqual(len(rebuilt), 10)
        for payload in rebuilt:
            with self.subTest(
                horse=payload["identity"].get("horse_name")
            ):
                career = payload["career"]
                self.assertIsInstance(career["source_start_count"], int)
                self.assertEqual(
                    career["collected_start_count"],
                    career["source_start_count"],
                )
                self.assertEqual(career["missing_start_count"], 0)
                self.assertEqual(career["excess_start_count"], 0)
                self.assertEqual(career["gap_count"], 0)
                self.assertEqual(
                    career["career_record_count"],
                    len(career["records"]),
                )


class BasicProfileResearchEvidenceTests(SimpleTestCase):
    def _document(self):
        return {
            "schema_version": "p0-horse-basic-profile-evidence.v1",
            "batch_id": "basic-profile-source-research-20260719",
            "verified_at": "2026-07-19T09:14:00Z",
            "verification_method": "manual_web_source_review",
            "horses": [
                {
                    "horse_name": "LOSANGE BLEU",
                    "region": "france",
                    "expected_source_name": "sporting_life",
                    "expected_external_horse_id": "1055320",
                    "expected_sire": "Martaline",
                    "expected_dam": "Sweet Valrose",
                    "expected_birth_year": 2019,
                    "fields": [
                        {
                            "field_name": "country",
                            "canonical_value": "FR",
                            "direct_raw_value": "FR",
                            "source_name": "france_sire",
                            "source_url": (
                                "https://www.france-sire.com/"
                                "cheval-423022-losange_bleu.php"
                            ),
                            "normalization_rule": (
                                "source country code retained"
                            ),
                            "evidence_note": (
                                "Source profile identifies the horse as FR."
                            ),
                        },
                        {
                            "field_name": "breeder_name",
                            "canonical_value": (
                                "Ecurie Madame Patrick Papot"
                            ),
                            "direct_raw_value": (
                                "Ecurie Madame Patrick Papot"
                            ),
                            "source_name": "france_sire",
                            "source_url": (
                                "https://www.france-sire.com/"
                                "cheval-423022-losange_bleu.php"
                            ),
                            "normalization_rule": "trim source text",
                            "evidence_note": (
                                "Source profile lists the breeder."
                            ),
                        },
                    ],
                }
            ],
        }

    def _horse(self):
        return {
            "region": "france",
            "candidate": {"horse_name": "LOSANGE BLEU"},
            "identity": {
                "horse_name": "Losange Bleu",
                "sire_name": "Martaline",
                "dam_name": "Sweet Valrose",
                "birth_year": 2019,
            },
            "source": {
                "name": "sporting_life",
                "external_horse_id": "1055320",
            },
            "basic_profile": {"country": "", "breeder_name": ""},
            "pedigree": {},
            "career": {"records": []},
            "field_status": {},
            "source_evidence": [],
            "raw_payload": {},
        }

    def test_parser_flattens_fields_and_requires_audited_identity(self):
        document = self._document()
        rows = parse_basic_profile_verifications(
            json.dumps(document).encode()
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["batch_id"], document["batch_id"])
        self.assertEqual(rows[1]["expected_birth_year"], 2019)

        document["horses"][0]["expected_sire"] = ""
        with self.assertRaisesRegex(ValueError, "requires expected_sire"):
            parse_basic_profile_verifications(
                json.dumps(document).encode()
            )

    def test_parser_rejects_duplicate_fields_and_birth_year_drift(self):
        document = self._document()
        document["horses"][0]["fields"].append(
            dict(document["horses"][0]["fields"][0])
        )
        with self.assertRaisesRegex(ValueError, "duplicate basic profile"):
            parse_basic_profile_verifications(
                json.dumps(document).encode()
            )

    def test_parser_rejects_unusable_primary_and_corroborating_urls(self):
        primary = self._document()
        primary["horses"][0]["fields"][0]["source_url"] = (
            "https://bad host.example/profile"
        )
        with self.assertRaisesRegex(ValueError, "invalid source_url"):
            parse_basic_profile_verifications(json.dumps(primary).encode())

        corroborating = self._document()
        corroborating["horses"][0]["fields"][0][
            "corroborating_source_urls"
        ] = ["https://example.com:not-a-port/evidence"]
        with self.assertRaisesRegex(
            ValueError,
            "invalid corroborating_source_urls",
        ):
            parse_basic_profile_verifications(
                json.dumps(corroborating).encode()
            )

        document = self._document()
        document["horses"][0]["fields"][0] = {
            **document["horses"][0]["fields"][0],
            "field_name": "birth_date",
            "canonical_value": "2020-02-14",
        }
        with self.assertRaisesRegex(ValueError, "expected_birth_year"):
            parse_basic_profile_verifications(
                json.dumps(document).encode()
            )

    def test_application_fills_only_empty_targets_and_keeps_field_evidence(self):
        rows = parse_basic_profile_verifications(
            json.dumps(self._document()).encode()
        )
        data = {"horses": [self._horse()]}

        applied_count = apply_basic_profile_verifications(data, rows)

        horse = data["horses"][0]
        self.assertEqual(applied_count, 2)
        self.assertEqual(horse["basic_profile"]["country"], "FR")
        self.assertEqual(
            horse["basic_profile"]["breeder_name"],
            "Ecurie Madame Patrick Papot",
        )
        self.assertEqual(
            horse["field_status"]["missing_basic_profile_fields"],
            [
                "sex",
                "color",
                "birth_date",
                "owner_name",
                "trainer_name",
            ],
        )
        self.assertEqual(
            {
                row["field_name"]
                for row in horse["basic_profile_field_evidence"]
            },
            {"country", "breeder_name"},
        )
        self.assertTrue(
            all(
                row["status"] == "manual_source_verified"
                for row in horse["basic_profile_field_evidence"]
            )
        )

    def test_application_rejects_identity_and_populated_target_conflicts(self):
        rows = parse_basic_profile_verifications(
            json.dumps(self._document()).encode()
        )
        wrong_identity = self._horse()
        wrong_identity["identity"]["dam_name"] = "Another Dam"
        with self.assertRaisesRegex(ValueError, "expected_dam mismatch"):
            apply_basic_profile_verifications(
                {"horses": [wrong_identity]},
                rows,
            )

        conflicting_target = self._horse()
        conflicting_target["basic_profile"]["country"] = "IRE"
        with self.assertRaisesRegex(ValueError, "conflicts with collected"):
            apply_basic_profile_verifications(
                {"horses": [conflicting_target]},
                rows,
            )

        missing_birth_year = self._horse()
        missing_birth_year["identity"]["birth_year"] = None
        with self.assertRaisesRegex(
            ValueError,
            "expected_birth_year mismatch",
        ):
            apply_basic_profile_verifications(
                {"horses": [missing_birth_year]},
                rows,
            )

    def test_same_region_same_name_uses_source_identity(self):
        document = self._document()
        second = json.loads(json.dumps(document["horses"][0]))
        second["expected_source_name"] = "france_galop"
        second["expected_external_horse_id"] = "fg-999"
        second["expected_sire"] = "Another Sire"
        second["expected_dam"] = "Another Dam"
        second["expected_birth_year"] = 2020
        document["horses"].append(second)
        rows = parse_basic_profile_verifications(
            json.dumps(document).encode()
        )
        first_horse = self._horse()
        second_horse = self._horse()
        second_horse["source"] = {
            "name": "france_galop",
            "external_horse_id": "fg-999",
        }
        second_horse["identity"] = {
            "horse_name": "LOSANGE BLEU",
            "sire_name": "Another Sire",
            "dam_name": "Another Dam",
            "birth_year": 2020,
        }

        applied = apply_basic_profile_verifications(
            {"horses": [first_horse, second_horse]},
            rows,
        )

        self.assertEqual(applied, 4)
        self.assertEqual(first_horse["basic_profile"]["country"], "FR")
        self.assertEqual(second_horse["basic_profile"]["country"], "FR")

    def test_captured_evidence_contains_all_60_review_fields(self):
        rows = parse_basic_profile_verifications(
            BASIC_PROFILE_EVIDENCE.read_bytes()
        )

        self.assertEqual(len(rows), 60)
        self.assertEqual(
            {
                (row["region"], row["field_name"])
                for row in rows
            },
            {
                ("france", "country"),
                ("france", "breeder_name"),
                ("united_kingdom", "country"),
                ("united_kingdom", "breeder_name"),
                ("hong_kong", "birth_date"),
                ("hong_kong", "breeder_name"),
            },
        )


class CareerRecordResearchEvidenceTests(SimpleTestCase):
    def test_captured_rows_fill_fort_george_count_without_claiming_official_rows(self):
        data = json.loads(CAPTURED_RESEARCH_50.read_text(encoding="utf-8"))
        equibase = load_us_equibase_profile_verifications(
            ROOT
            / "runtime/horse_profile_completion/"
            "manual-source-evidence-20260719/"
            "equibase_profile_evidence.json"
        )
        apply_us_equibase_profile_verifications(data, equibase)
        rows = parse_career_record_verifications(
            CAREER_RECORD_EVIDENCE.read_bytes()
        )

        applied_count = apply_career_record_verifications(data, rows)

        fort_george = next(
            horse
            for horse in data["horses"]
            if horse["candidate"]["horse_name"] == "Fort George"
        )
        self.assertEqual(applied_count, 7)
        self.assertEqual(len(fort_george["career"]["records"]), 13)
        self.assertEqual(fort_george["career"]["collected_start_count"], 13)
        self.assertEqual(fort_george["career"]["gap_count"], 0)
        self.assertEqual(
            fort_george["career"]["record_authority_status"],
            "count_aligned_records_unverified",
        )
        self.assertEqual(
            fort_george["career"]["career_collection_status"],
            "count_aligned_per_record_officiality_pending",
        )
        self.assertTrue(fort_george["field_status"]["career_count_matches"])
        inserted = [
            record
            for record in fort_george["career"]["records"]
            if record["external_race_id"].startswith(
                ("sporting_life:", "racing_post:")
            )
        ]
        self.assertEqual(len(inserted), 7)
        self.assertEqual(
            {record["race_date"] for record in inserted},
            {
                "2025-08-16",
                "2025-07-31",
                "2025-05-23",
                "2025-05-02",
                "2024-12-03",
                "2024-11-07",
                "2024-10-14",
            },
        )

    def test_parser_and_application_reject_duplicate_or_conflicting_rows(self):
        rows = parse_career_record_verifications(
            CAREER_RECORD_EVIDENCE.read_bytes()
        )
        duplicate_rows = json.loads(
            CAREER_RECORD_EVIDENCE.read_text(encoding="utf-8")
        )
        duplicate_rows.append(dict(duplicate_rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate career record"):
            parse_career_record_verifications(
                json.dumps(duplicate_rows).encode()
            )

        horse = {
            "region": "united_states",
            "candidate": {"horse_name": "Fort George"},
            "identity": {
                "horse_name": "Fort George",
                "sire_name": "Territories (IRE)",
                "dam_name": "Dusty Red (GB)",
                "birth_year": 2022,
            },
            "source": {
                "name": "equibase+hrn",
                "external_horse_id": "11201225",
            },
            "basic_profile": {},
            "pedigree": {},
            "career": {
                "official_or_source_start_count": 1,
                "source_start_count": 1,
                "source_start_count_quality": "official_verified",
                "records": [
                    {
                        "external_race_id": rows[0]["external_race_id"],
                        "external_result_id": "wrong-result-id",
                        "race_date": rows[0]["race_date"],
                        "race_name": rows[0]["race_name"],
                        "racecourse": rows[0]["racecourse"],
                        "finish": "5",
                        "source_url": rows[0]["source_url"],
                    }
                ],
            },
            "source_evidence": [],
            "raw_payload": {},
        }
        with self.assertRaisesRegex(ValueError, "conflicts with an existing"):
            apply_career_record_verifications(
                {"horses": [horse]},
                [rows[0]],
            )

    def test_fallback_evidence_deduplication_keeps_horse_identity(self):
        first = {
            "horse_name": "Shared Name",
            "region": "united_states",
            "expected_source_name": "",
            "expected_external_horse_id": "",
            "expected_sire": "First Sire",
            "expected_dam": "First Dam",
            "expected_birth_year": 2020,
            "external_race_id": "shared-race",
            "external_result_id": "shared-result",
            "race_date": "2025-01-01",
            "race_name": "Shared Race",
            "racecourse": "Shared Track",
            "finish_position": 1,
            "distance_text": "1m",
            "race_classification": "Listed",
            "surface": "Turf",
            "going": "Good",
            "source_name": "manual_source",
            "source_url": "https://example.test/result/first",
            "verified_at": "2026-07-19T12:00:00+08:00",
            "verification_method": "manual_result_page_review",
            "evidence_note": "First horse evidence.",
        }
        second = {
            **first,
            "expected_sire": "Second Sire",
            "expected_dam": "Second Dam",
            "expected_birth_year": 2021,
            "source_url": "https://example.test/result/second",
            "evidence_note": "Second horse evidence.",
        }

        parsed = parse_career_record_verifications(
            json.dumps([first, second]).encode()
        )

        self.assertEqual(len(parsed), 2)


class HRNResearchIdentityTests(SimpleTestCase):
    class _Transport:
        def __init__(self, html: str):
            self.html = html

        def get(self, url: str, **kwargs):
            return SimpleNamespace(
                text=self.html,
                url=url,
                raise_for_status=lambda: None,
            )

    def test_same_name_and_parents_with_different_birth_year_is_rejected(self):
        html = """
        <html><body>
          <h1>Shared Name</h1>
          <div class="horse-stats">
            <div><strong>Foaled:</strong> 2020-02-03</div>
            <div><strong>Sire:</strong> Shared Sire</div>
            <div><strong>Dam:</strong> Shared Dam</div>
          </div>
        </body></html>
        """
        row = {
            "horse_name": "Shared Name",
        }
        equibase = {
            "horse_name": "Shared Name",
            "external_horse_id": "equibase-1",
            "sire": "Shared Sire",
            "dam": "Shared Dam",
            "birth_date": "2021-02-03",
        }

        with self.assertRaisesRegex(ValueError, "HRN birth_year mismatch"):
            parse_hrn_profile(
                row,
                self._Transport(html),
                equibase,
            )


class FinalizeCareerCollectionStatusTests(SimpleTestCase):
    def test_official_count_reference_controls_count_match(self):
        horse = {
            "basic_profile": {
                field: "value"
                for field in (
                    "country",
                    "sex",
                    "color",
                    "birth_date",
                    "owner_name",
                    "trainer_name",
                    "breeder_name",
                )
            },
            "pedigree": {
                field: "value"
                for field in (
                    "sire",
                    "dam",
                    "sire_sire",
                    "sire_dam",
                    "dam_sire",
                    "dam_dam",
                )
            },
            "career": {
                "source_start_count": 5,
                "source_start_count_quality": "source_declared",
                "official_or_source_start_count": 6,
                "record_authority_status": "source_records_verified",
                "records": [
                    {
                        "result_status": "unplaced",
                        "start_status": "started",
                    }
                    for _index in range(5)
                ],
            },
        }

        status = summarize_field_status(horse)
        horse["field_status"] = status
        finalize_career_collection_status(horse, status)

        self.assertFalse(status["career_count_matches"])
        self.assertEqual(status["career_missing_start_count"], 1)
        self.assertEqual(
            horse["career"]["career_collection_status"],
            "count_mismatch",
        )

    def test_matching_final_counts_clear_an_early_count_mismatch(self):
        payload = {
            "career": {
                "source_start_count": 32,
                "source_start_count_quality": "source_declared",
                "record_authority_status": "source_records_verified",
                "career_collection_status": "count_mismatch",
            }
        }

        finalize_career_collection_status(
            payload,
            {
                "career_count_matches": True,
                "unknown_record_count": 0,
            },
        )

        self.assertEqual(
            payload["career"]["career_collection_status"],
            "complete",
        )

    def test_matching_counts_with_unknown_results_stay_semantically_partial(self):
        payload = {
            "career": {
                "source_start_count": 50,
                "source_start_count_quality": "source_declared",
                "record_authority_status": "source_records_verified",
                "career_collection_status": "count_mismatch",
            }
        }

        finalize_career_collection_status(
            payload,
            {
                "career_count_matches": True,
                "unknown_record_count": 2,
            },
        )

        self.assertEqual(
            payload["career"]["career_collection_status"],
            "count_complete_result_semantics_partial",
        )

    def test_count_only_official_verification_keeps_authority_pending_status(self):
        payload = {
            "career": {
                "source_start_count": 10,
                "source_start_count_quality": "official_verified",
                "record_authority_status": (
                    "count_aligned_records_unverified"
                ),
                "career_collection_status": (
                    "count_aligned_per_record_officiality_pending"
                ),
            }
        }

        finalize_career_collection_status(
            payload,
            {
                "career_count_matches": True,
                "unknown_record_count": 0,
            },
        )

        self.assertEqual(
            payload["career"]["career_collection_status"],
            "count_aligned_per_record_officiality_pending",
        )

    def test_only_verified_record_authority_can_complete(self):
        cases = {
            "source_blocked": "source_blocked",
            "unknown": "record_authority_pending",
            "": "record_authority_pending",
            "unsupported": "record_authority_invalid",
        }
        for authority, expected_status in cases.items():
            with self.subTest(authority=authority):
                payload = {
                    "career": {
                        "source_start_count": 10,
                        "source_start_count_quality": "source_declared",
                        "record_authority_status": authority,
                        "career_collection_status": "complete",
                    }
                }

                finalize_career_collection_status(
                    payload,
                    {
                        "career_count_matches": True,
                        "unknown_record_count": 0,
                    },
                )

                self.assertEqual(
                    payload["career"]["career_collection_status"],
                    expected_status,
                )


class UnitedStatesResearchEvidenceTests(SimpleTestCase):
    def test_equibase_profile_evidence_keys_same_name_by_external_id(self):
        rows = json.loads(
            (
                ROOT
                / "runtime/horse_profile_completion/"
                "manual-source-evidence-20260719/"
                "equibase_profile_evidence.json"
            ).read_text(encoding="utf-8")
        )
        first = dict(rows[0])
        second = dict(rows[0])
        second["expected_external_horse_id"] = "99999999"
        second["source_url"] = second["source_url"].replace(
            first["expected_external_horse_id"],
            second["expected_external_horse_id"],
        )

        parsed = parse_us_equibase_profile_verifications(
            json.dumps([first, second]).encode()
        )

        self.assertEqual(
            set(parsed),
            {
                (
                    "source",
                    "equibase",
                    first["expected_external_horse_id"],
                ),
                ("source", "equibase", "99999999"),
            },
        )

    def test_duplicate_profile_and_race_rows_merge_without_losing_sources(self):
        records = [
            {
                "external_race_id": "",
                "race_date": "2026-07-11",
                "race_name": "Bowling Green S. Presented by Emerald Ecovations",
                "racecourse": "Saratoga",
                "finish": "5",
                "distance_text": "1 3/8 m",
                "source_url": "https://www.horseracingnation.com/horse/Carsons_Run",
            },
            {
                "external_race_id": "2026_Bowling_Green",
                "race_date": "2026-07-11",
                "race_name": "2026 Bowling Green (G2)",
                "racecourse": "Saratoga",
                "finish": "5",
                "distance_text": "1 3/8 M",
                "source_url": (
                    "https://www.horseracingnation.com/race/"
                    "2026_Bowling_Green"
                ),
            },
        ]

        deduplicated, duplicate_count = deduplicate_us_visible_records(records)

        self.assertEqual(duplicate_count, 1)
        self.assertEqual(len(deduplicated), 1)
        self.assertEqual(
            deduplicated[0]["external_race_id"],
            "2026_Bowling_Green",
        )
        self.assertEqual(
            deduplicated[0]["source_urls"],
            [
                "https://www.horseracingnation.com/horse/Carsons_Run",
                (
                    "https://www.horseracingnation.com/race/"
                    "2026_Bowling_Green"
                ),
            ],
        )
        self.assertEqual(
            deduplicated[0]["source_record_names"],
            [
                "Bowling Green S. Presented by Emerald Ecovations",
                "2026 Bowling Green (G2)",
            ],
        )

        replayed, replay_duplicate_count = deduplicate_us_visible_records(
            deduplicated
        )

        self.assertEqual(replay_duplicate_count, 0)
        self.assertEqual(replayed, deduplicated)

    def test_manual_equibase_evidence_requires_complete_audit_metadata(self):
        row = {
            "horse_name": "Carson's Run",
            "expected_external_horse_id": "10933637",
            "expected_sire": "Cupid",
            "expected_dam": "Hot N Hectic",
            "expected_birth_date": "2021-01-24",
            "official_start_count": 15,
            "color_raw": "CH",
            "color_normalized": "chestnut",
            "source_url": (
                "https://www.equibase.com/profiles/Results.cfm"
                "?type=Horse&refno=10933637&registry=T"
            ),
            "source_as_of": "2026-07-19",
            "verified_at": "2026-07-19T12:00:00+08:00",
            "verification_method": "manual_profile_career_statistics",
            "evidence_note": "Career Starts and profile color checked manually.",
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps([row]), encoding="utf-8")

            loaded = load_us_equibase_profile_verifications(path)

        self.assertEqual(
            loaded[("source", "equibase", "10933637")],
            row,
        )

        for missing_key in (
            "expected_external_horse_id",
            "expected_sire",
            "expected_dam",
            "expected_birth_date",
            "source_url",
            "verified_at",
            "verification_method",
            "evidence_note",
        ):
            invalid = dict(row)
            invalid[missing_key] = ""
            with TemporaryDirectory() as directory:
                path = Path(directory) / "evidence.json"
                path.write_text(json.dumps([invalid]), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, missing_key):
                    load_us_equibase_profile_verifications(path)

    def test_deduplicated_source_evidence_requires_original_record_name(self):
        evidence_path = (
            ROOT
            / "runtime/horse_profile_completion/"
            "manual-source-evidence-20260719/"
            "equibase_profile_evidence.json"
        )
        rows = json.loads(evidence_path.read_text(encoding="utf-8"))
        del rows[1]["deduplicated_record_source_evidence"][
            "additional_source_record_name"
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "additional_source_record_name",
            ):
                load_us_equibase_profile_verifications(path)

    def test_manual_equibase_evidence_fails_closed_on_identity_mismatch(self):
        verification = {
            "horse_name": "Carson's Run",
            "expected_external_horse_id": "10933637",
            "expected_sire": "Cupid",
            "expected_dam": "Hot N Hectic",
            "expected_birth_date": "2021-01-24",
        }
        equibase_identity = {
            "external_horse_id": "10933637",
            "sire": "Cupid",
            "dam": "Another Dam",
            "birth_date": "2021-01-24",
        }

        with self.assertRaisesRegex(ValueError, "expected_dam"):
            validate_us_equibase_profile_verification(
                verification,
                equibase_identity,
            )

    def test_manual_equibase_evidence_updates_profile_and_reconciles_career(self):
        verification = {
            "horse_name": "Carson's Run",
            "expected_external_horse_id": "10933637",
            "expected_sire": "Cupid",
            "expected_dam": "Hot N Hectic",
            "expected_birth_date": "2021-01-24",
            "official_start_count": 1,
            "color_raw": "CH",
            "color_normalized": "chestnut",
            "source_url": (
                "https://www.equibase.com/profiles/Results.cfm"
                "?type=Horse&refno=10933637&registry=T"
            ),
            "source_as_of": "2026-07-19",
            "verified_at": "2026-07-19T12:00:00+08:00",
            "verification_method": "manual_profile_career_statistics",
            "evidence_note": "Career Starts and profile color checked manually.",
        }
        data = {
            "horses": [
                {
                    "region": "united_states",
                    "candidate": {"horse_name": "Carson's Run"},
                    "source": {"external_horse_id": "10933637"},
                    "identity": {
                        "horse_name": "Carson's Run",
                        "sire_name": "Cupid",
                        "dam_name": "Hot N Hectic",
                        "birth_year": 2021,
                    },
                    "basic_profile": {
                        "country": "KY",
                        "sex": "H",
                        "color": "",
                        "birth_date": "2021-01-24",
                        "owner_name": "Owner",
                        "trainer_name": "Trainer",
                        "breeder_name": "Breeder",
                    },
                    "pedigree": {
                        "sire": "Cupid",
                        "dam": "Hot N Hectic",
                        "sire_sire": "Tapit",
                        "sire_dam": "Pretty 'n Smart",
                        "dam_sire": "Henny Hughes",
                        "dam_dam": "Wicked Wish",
                    },
                    "career": {
                        "records": [
                            {
                                "external_race_id": "",
                                "race_date": "2026-07-11",
                                "race_name": "Bowling Green S.",
                                "racecourse": "Saratoga",
                                "finish": "5",
                                "distance_text": "1 3/8 m",
                                "source_url": (
                                    "https://www.horseracingnation.com/horse/"
                                    "Carsons_Run"
                                ),
                            },
                            {
                                "external_race_id": "2026_Bowling_Green",
                                "race_date": "2026-07-11",
                                "race_name": "2026 Bowling Green (G2)",
                                "racecourse": "Saratoga",
                                "finish": "5",
                                "distance_text": "1 3/8 M",
                                "source_url": (
                                    "https://www.horseracingnation.com/race/"
                                    "2026_Bowling_Green"
                                ),
                            },
                        ]
                    },
                    "source_evidence": [],
                    "raw_payload": {},
                }
            ]
        }

        applied_count = apply_us_equibase_profile_verifications(
            data,
            {("source", "equibase", "10933637"): verification},
        )

        self.assertEqual(applied_count, 1)
        horse = data["horses"][0]
        self.assertEqual(horse["basic_profile"]["color"], "chestnut")
        self.assertEqual(len(horse["career"]["records"]), 1)
        self.assertEqual(horse["career"]["visible_source_record_count"], 2)
        self.assertEqual(horse["career"]["deduplicated_record_count"], 1)
        self.assertEqual(horse["career"]["gap_count"], 0)
        self.assertEqual(
            horse["career"]["record_authority_status"],
            "count_aligned_records_unverified",
        )
        self.assertEqual(horse["field_status"]["career_gap_count"], 0)
        self.assertNotIn(
            "color",
            horse["field_status"]["missing_basic_profile_fields"],
        )


class CareerResultResearchEvidenceTests(SimpleTestCase):
    def _verification(self, **overrides):
        verification = {
            "horse_name": "Example Horse",
            "expected_source_name": "sporting_life",
            "expected_external_horse_id": "horse-1",
            "expected_sire": "Example Sire",
            "expected_dam": "Example Dam",
            "expected_birth_year": 2018,
            "race_date": "2024-01-01",
            "expected_external_race_id": "race-1",
            "expected_external_result_id": "result-1",
            "expected_race_name": "Example Stakes",
            "canonical_value": "3",
            "normalized_result_status": "placed",
            "normalized_start_status": "started",
            "source_name": "official_example",
            "source_url": "https://example.test/official-result",
            "verified_at": "2026-07-19T12:00:00+08:00",
            "verification_method": "manual_official_result_review",
            "conversion_rule": "official_finish_position_v1",
            "evidence_note": "Official result checked manually.",
        }
        verification.update(overrides)
        return verification

    def _horse(self):
        return {
            "region": "united_kingdom",
            "candidate": {"horse_name": "Example Horse"},
            "source": {
                "name": "sporting_life",
                "external_horse_id": "horse-1",
            },
            "identity": {
                "horse_name": "Example Horse",
                "sire_name": "Example Sire",
                "dam_name": "Example Dam",
                "birth_year": 2018,
            },
            "basic_profile": {
                "country": "GB",
                "sex": "g",
                "color": "b",
                "birth_date": "2018-01-01",
                "owner_name": "Owner",
                "trainer_name": "Trainer",
                "breeder_name": "Breeder",
            },
            "pedigree": {
                "sire": "Example Sire",
                "dam": "Example Dam",
                "sire_sire": "Sire Sire",
                "sire_dam": "Sire Dam",
                "dam_sire": "Dam Sire",
                "dam_dam": "Dam Dam",
            },
            "career": {
                "source_start_count": 2,
                "source_start_count_quality": "source_declared",
                "record_authority_status": "source_records_verified",
                "records": [
                    {
                        "external_race_id": "race-1",
                        "external_result_id": "result-1",
                        "race_date": "2024-01-01",
                        "race_name": "Example Stakes",
                        "racecourse": "Example",
                        "finish": "N/A",
                        "result_status": "unknown",
                        "start_status": "unconfirmed",
                        "result_evidence_status": (
                            "requires_authoritative_supplement"
                        ),
                        "source_url": "https://example.test/profile",
                    },
                    {
                        "external_race_id": "race-2",
                        "external_result_id": "result-2",
                        "race_date": "2023-12-01",
                        "race_name": "Entry Only Race",
                        "racecourse": "Example",
                        "finish": "N/A",
                        "result_status": "unknown",
                        "start_status": "unconfirmed",
                        "result_evidence_status": (
                            "requires_authoritative_supplement"
                        ),
                        "source_url": "https://example.test/profile",
                    },
                ],
            },
            "aliases": [
                {
                    "name": "Example Horse",
                    "language": "en",
                    "is_original": True,
                }
            ],
            "source_evidence": [],
            "raw_payload": {},
        }

    def test_manual_result_evidence_requires_complete_audit_metadata(self):
        row = self._verification()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps([row]), encoding="utf-8")
            loaded = load_career_result_verifications(path)

        self.assertEqual(loaded, [row])

        for missing_key in (
            "expected_source_name",
            "expected_external_horse_id",
            "expected_sire",
            "expected_dam",
            "expected_race_name",
            "source_url",
            "verified_at",
            "verification_method",
            "conversion_rule",
            "evidence_note",
        ):
            invalid = dict(row)
            invalid[missing_key] = ""
            with TemporaryDirectory() as directory:
                path = Path(directory) / "evidence.json"
                path.write_text(json.dumps([invalid]), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, missing_key):
                    load_career_result_verifications(path)

    def test_manual_result_evidence_fails_closed_on_identity_mismatch(self):
        horse = self._horse()
        horse["identity"]["dam_name"] = "Another Dam"

        with self.assertRaisesRegex(ValueError, "expected_dam"):
            apply_career_result_verifications(
                {"horses": [horse]},
                [self._verification()],
            )

    def test_manual_result_evidence_must_match_exactly_one_record(self):
        with self.assertRaisesRegex(ValueError, "matched 0"):
            apply_career_result_verifications(
                {"horses": [self._horse()]},
                [self._verification(expected_external_result_id="missing")],
            )

    def test_manual_result_and_nonstart_evidence_reconcile_actual_starts(self):
        data = {"horses": [self._horse()]}
        verifications = [
            self._verification(
                official_or_source_start_count=1,
                count_source_url="https://example.test/career-count",
            ),
            self._verification(
                race_date="2023-12-01",
                expected_external_race_id="race-2",
                expected_external_result_id="result-2",
                expected_race_name="Entry Only Race",
                canonical_value="",
                participation_status_value="not_in_final_field",
                normalized_result_status="unknown",
                normalized_start_status="did_not_start",
                official_or_source_start_count=1,
                count_source_url="https://example.test/career-count",
            ),
        ]

        applied_count = apply_career_result_verifications(
            data,
            verifications,
        )

        self.assertEqual(applied_count, 2)
        horse = data["horses"][0]
        self.assertEqual(horse["career"]["visible_source_record_count"], 2)
        self.assertEqual(horse["career"]["collected_start_count"], 1)
        self.assertEqual(horse["career"]["nonstarter_count"], 1)
        self.assertEqual(horse["career"]["result_semantics_pending_count"], 0)
        self.assertEqual(horse["career"]["source_start_count"], 1)
        self.assertEqual(
            horse["career"]["source_start_count_quality"],
            "source_reconciled",
        )
        self.assertEqual(horse["career"]["gap_count"], 0)
        self.assertEqual(
            horse["career"]["career_collection_status"],
            "complete",
        )
        self.assertEqual(horse["field_status"]["unknown_record_count"], 0)
        nonstart_record = horse["career"]["records"][1]
        result_evidence = next(
            item
            for item in nonstart_record["field_evidence"]
            if item["field_name"] == "result"
        )
        for layer_name in ("canonical_raw", "normalized"):
            self.assertIsNone(result_evidence[layer_name]["value"])
            self.assertEqual(
                result_evidence[layer_name]["status"],
                "not_applicable",
            )

    def test_captured_nine_result_reviews_keep_verified_real_outcomes(self):
        data = json.loads(CAPTURED_RESEARCH_50.read_text(encoding="utf-8"))
        verifications = load_career_result_verifications(
            CAREER_RESULT_EVIDENCE
        )
        apply_us_equibase_profile_verifications(
            data,
            load_us_equibase_profile_verifications(
                ROOT
                / "runtime/horse_profile_completion/"
                "manual-source-evidence-20260719/"
                "equibase_profile_evidence.json"
            ),
        )

        applied_count = apply_career_result_verifications(
            data,
            verifications,
        )

        self.assertEqual(applied_count, 9)
        reviewed_records = {}
        reviewed_horses = {}
        for horse in data["horses"]:
            horse_name = horse["candidate"]["horse_name"]
            reviewed_horses[horse_name] = horse
            for record in horse["career"]["records"]:
                if record.get("result_verification_method"):
                    reviewed_records[(horse_name, record["race_date"])] = (
                        record
                    )

        expected_outcomes = {
            ("KENTUCKY WOOD", "2026-05-30"): (
                "arr",
                "did_not_finish",
                "started",
            ),
            ("Brando", "2018-08-05"): ("8", "unplaced", "started"),
            ("Brando", "2017-10-01"): ("7", "unplaced", "started"),
            ("Paisley Park", "2017-12-09"): (
                "",
                "unknown",
                "did_not_start",
                "not_in_final_field",
            ),
            ("Paisley Park", "2017-12-06"): (
                "",
                "unknown",
                "did_not_start",
                "not_in_final_field",
            ),
            ("Gabrial", "2018-02-05"): ("3", "placed", "started"),
            ("Gabrial", "2017-01-05"): ("9", "unplaced", "started"),
            ("Gabrial", "2016-03-26"): ("11", "unplaced", "started"),
            ("The New One", "2012-02-11"): (
                "",
                "unknown",
                "did_not_start",
                "meeting_abandoned",
            ),
        }
        self.assertEqual(set(reviewed_records), set(expected_outcomes))
        for key, expected in expected_outcomes.items():
            record = reviewed_records[key]
            self.assertEqual(
                (
                    record["finish"],
                    record["result_status"],
                    record["start_status"],
                    record.get("participation_status", ""),
                ),
                expected
                if len(expected) == 4
                else (*expected, ""),
            )
            expected_evidence_status = (
                "not_applicable_nonstart_verified"
                if record["start_status"] == "did_not_start"
                else "canonical_verified"
            )
            self.assertEqual(
                record["result_evidence_status"],
                expected_evidence_status,
            )

        paisley = reviewed_horses["Paisley Park"]
        self.assertEqual(paisley["career"]["visible_source_record_count"], 33)
        self.assertEqual(paisley["career"]["collected_start_count"], 31)
        self.assertEqual(paisley["career"]["nonstarter_count"], 2)
        self.assertEqual(paisley["field_status"]["unknown_record_count"], 0)

        the_new_one = reviewed_horses["The New One"]
        self.assertEqual(
            the_new_one["career"]["visible_source_record_count"],
            41,
        )
        self.assertEqual(the_new_one["career"]["collected_start_count"], 40)
        self.assertEqual(the_new_one["career"]["nonstarter_count"], 1)
        self.assertEqual(
            the_new_one["field_status"]["unknown_record_count"],
            0,
        )

        us_multisource_records = [
            (horse["candidate"]["horse_name"], record)
            for horse in data["horses"]
            if horse["region"] == "united_states"
            for record in horse["career"]["records"]
            if len(record.get("source_urls") or []) > 1
        ]
        self.assertEqual(len(us_multisource_records), 6)
        expected_profile_record_names = {
            "Carson's Run": (
                "Bowling Green S. Presented by Emerald Ecovations"
            ),
            "Desvio": "Bowling Green S. Presented by Emerald Ecovations",
            "Heroic Move": "2026 Cornhusker Handicap (G3)",
            "In Our Time": "Caress S.",
            "Minaret Station": (
                "Bowling Green S. Presented by Emerald Ecovations"
            ),
            "Movin' On Up": "Caress S.",
        }
        for horse_name, record in us_multisource_records:
            self.assertIn(
                expected_profile_record_names[horse_name],
                record["source_record_names"],
            )

        for horse_name in ("Paisley Park", "The New One"):
            horse = reviewed_horses[horse_name]
            participation_evidence = [
                evidence
                for evidence in horse["source_evidence"]
                if evidence.get("evidence_role")
                == "canonical_career_participation_review"
            ]
            self.assertTrue(participation_evidence)
            for record in horse["career"]["records"]:
                if record.get("start_status") != "did_not_start":
                    continue
                result_evidence = next(
                    item
                    for item in record["field_evidence"]
                    if item["field_name"] == "result"
                )
                self.assertIsNone(
                    result_evidence["canonical_raw"]["value"]
                )
                self.assertEqual(
                    result_evidence["canonical_raw"]["status"],
                    "not_applicable",
                )

    def test_manual_evidence_output_binds_all_input_hashes(self):
        applied_at = "2026-07-19T16:00:00+08:00"
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            output_path = directory_path / "output.json"
            gap_snapshot_path = directory_path / "gap-snapshot.json"
            post_gap_snapshot_path = (
                directory_path / "post-gap-snapshot.json"
            )
            gap_snapshot_path.write_bytes(
                DEFAULT_GAP_SNAPSHOT.read_bytes()
            )
            summary = apply_evidence(
                input_path=FINAL_ENRICHED_RESEARCH_50,
                output_path=output_path,
                equibase_evidence_path=(
                    ROOT
                    / "runtime/horse_profile_completion/"
                    "manual-source-evidence-20260719/"
                    "equibase_profile_evidence.json"
                ),
                career_result_evidence_path=CAREER_RESULT_EVIDENCE,
                gap_snapshot_path=gap_snapshot_path,
                post_gap_snapshot_path=post_gap_snapshot_path,
                applied_at=applied_at,
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))

        manifest = output["manual_evidence_application"]
        self.assertEqual(manifest["tool_version"], TOOL_VERSION)
        self.assertEqual(manifest["applied_at"], applied_at)
        self.assertEqual(
            manifest["inputs"]["input"]["sha256"],
            hashlib.sha256(
                FINAL_ENRICHED_RESEARCH_50.read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            manifest["equibase_profile_verification_count"],
            10,
        )
        self.assertEqual(manifest["basic_profile_verification_count"], 60)
        self.assertEqual(manifest["basic_profile_verified_target_count"], 60)
        self.assertEqual(manifest["basic_profile_applied_count"], 0)
        self.assertEqual(manifest["career_result_verification_count"], 9)
        self.assertEqual(manifest["career_record_verification_count"], 7)
        self.assertEqual(manifest["career_record_applied_count"], 0)
        self.assertEqual(
            manifest["inputs"][
                "basic_profile_pre_application_gap_snapshot"
            ]["missing_count"],
            60,
        )
        self.assertEqual(
            manifest["inputs"][
                "basic_profile_post_application_gap_snapshot"
            ]["missing_count"],
            0,
        )
        post_snapshot_binding = manifest["inputs"][
            "basic_profile_post_application_gap_snapshot"
        ]
        self.assertNotIn("input_sha256", post_snapshot_binding)
        self.assertEqual(
            post_snapshot_binding["hash_scope"],
            (
                "canonical_business_payload_without_"
                "manual_application_metadata"
            ),
        )
        self.assertRegex(
            post_snapshot_binding["business_payload_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            manifest["parent_input_sha256"],
            hashlib.sha256(
                FINAL_ENRICHED_RESEARCH_50.read_bytes()
            ).hexdigest(),
        )
        required_career_counts = {
            "collected_start_count",
            "missing_start_count",
            "excess_start_count",
            "start_count_delta",
            "gap_count",
            "nonstarter_count",
            "abnormal_official_status_count",
            "overseas_start_count",
        }
        self.assertTrue(
            all(
                required_career_counts <= set(horse["career"])
                for horse in output["horses"]
            )
        )
        self.assertEqual(
            sum(
                horse["career"]["collected_start_count"]
                for horse in output["horses"]
            ),
            1432,
        )
        self.assertEqual(
            summary["manual_evidence_application_id"],
            manifest["application_id"],
        )

    def test_manual_evidence_application_reads_each_hashed_input_once(self):
        class SingleReadPath:
            def __init__(self, path):
                self.path = path
                self.read_count = 0

            def read_bytes(self):
                self.read_count += 1
                if self.read_count > 1:
                    raise AssertionError(f"{self.path} read more than once")
                return self.path.read_bytes()

            def __str__(self):
                return str(self.path)

        input_path = SingleReadPath(FINAL_ENRICHED_RESEARCH_50)
        equibase_path = SingleReadPath(
            ROOT
            / "runtime/horse_profile_completion/"
            "manual-source-evidence-20260719/"
            "equibase_profile_evidence.json"
        )
        career_path = SingleReadPath(CAREER_RESULT_EVIDENCE)
        basic_profile_path = SingleReadPath(BASIC_PROFILE_EVIDENCE)
        career_record_path = SingleReadPath(CAREER_RECORD_EVIDENCE)
        with TemporaryDirectory() as directory:
            apply_evidence(
                input_path=input_path,
                output_path=Path(directory) / "output.json",
                equibase_evidence_path=equibase_path,
                career_result_evidence_path=career_path,
                basic_profile_evidence_path=basic_profile_path,
                career_record_evidence_path=career_record_path,
                applied_at="2026-07-19T16:00:00+08:00",
            )

        self.assertEqual(input_path.read_count, 1)
        self.assertEqual(equibase_path.read_count, 1)
        self.assertEqual(career_path.read_count, 1)
        self.assertEqual(basic_profile_path.read_count, 1)
        self.assertEqual(career_record_path.read_count, 1)

    def test_manual_evidence_application_does_not_overwrite_gap_snapshot(self):
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            first_output_path = directory_path / "first-output.json"
            second_output_path = directory_path / "second-output.json"
            gap_snapshot_path = directory_path / "gap-snapshot.json"
            gap_snapshot_path.write_bytes(
                DEFAULT_GAP_SNAPSHOT.read_bytes()
            )
            evidence_path = (
                ROOT
                / "runtime/horse_profile_completion/"
                "manual-source-evidence-20260719/"
                "equibase_profile_evidence.json"
            )
            apply_evidence(
                input_path=FINAL_ENRICHED_RESEARCH_50,
                output_path=first_output_path,
                equibase_evidence_path=evidence_path,
                career_result_evidence_path=CAREER_RESULT_EVIDENCE,
                gap_snapshot_path=gap_snapshot_path,
                applied_at="2026-07-19T16:00:00+08:00",
            )
            frozen_bytes = gap_snapshot_path.read_bytes()
            frozen_snapshot = json.loads(frozen_bytes.decode("utf-8"))
            self.assertEqual(frozen_snapshot["missing_count"], 60)

            apply_evidence(
                input_path=first_output_path,
                output_path=second_output_path,
                equibase_evidence_path=evidence_path,
                career_result_evidence_path=CAREER_RESULT_EVIDENCE,
                gap_snapshot_path=gap_snapshot_path,
                applied_at="2026-07-19T16:05:00+08:00",
            )

            self.assertEqual(gap_snapshot_path.read_bytes(), frozen_bytes)
            second_output = json.loads(
                second_output_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                second_output["manual_evidence_application"]["inputs"][
                    "basic_profile_pre_application_gap_snapshot"
                ]["missing_count"],
                60,
            )
            self.assertGreaterEqual(
                len(
                    second_output[
                        "manual_evidence_application_history"
                    ]
                ),
                1,
            )

    def test_manual_evidence_rejects_tampered_frozen_gap_snapshot(self):
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            gap_snapshot_path = directory_path / "gap-snapshot.json"
            snapshot = json.loads(
                DEFAULT_GAP_SNAPSHOT.read_text(encoding="utf-8")
            )
            snapshot["rows"][0]["proposed_value"] = "TAMPERED"
            gap_snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "trusted SHA-256",
            ):
                apply_evidence(
                    input_path=FINAL_ENRICHED_RESEARCH_50,
                    output_path=directory_path / "output.json",
                    equibase_evidence_path=(
                        ROOT
                        / "runtime/horse_profile_completion/"
                        "manual-source-evidence-20260719/"
                        "equibase_profile_evidence.json"
                    ),
                    career_result_evidence_path=CAREER_RESULT_EVIDENCE,
                    gap_snapshot_path=gap_snapshot_path,
                    applied_at="2026-07-19T16:10:00+08:00",
                )
