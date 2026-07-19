import json
from pathlib import Path

from django.test import SimpleTestCase

from runtime.tools.research_p0_horse_pedigree import (
    NetkeibaParentResearchClient,
    apply_manual_evidence,
    apply_parent_evidence,
    finalize_automatic_unresolved_queries,
    normalized_name,
    parse_search_candidates,
    select_parent_candidate,
)
from runtime.tools.apply_p0_horse_parent_identity_review import (
    LEGACY_METHOD,
    REVIEWED_METHOD,
    apply_manifest,
    prepare_manifest,
)


SEARCH_HTML = """
<ul class="BreederList CommonList_01">
  <li>
    <a href="https://en.netkeiba.com/db/horse/parent-wrong/">
      <div class="DataBox_01">
        <h2>Shared Dam</h2>
        <p>M 2010</p>
        <p>Sire: Wrong Sire</p>
        <p>Dam: Wrong Granddam</p>
      </div>
    </a>
  </li>
  <li>
    <a href="https://en.netkeiba.com/db/horse/parent-right/">
      <div class="DataBox_01">
        <h2>Shared Dam</h2>
        <p>M 2002</p>
        <p>Sire: Known Damsire</p>
        <p>Dam: Correct Granddam</p>
      </div>
    </a>
  </li>
</ul>
"""


class PedigreeResearchTests(SimpleTestCase):
    @staticmethod
    def _birth_year_evidence_bytes(rows):
        return (
            json.dumps(
                {
                    "schema_version": "p0-horse-parent-birth-year-evidence.v1",
                    "review_status": "approved",
                    "reviewed_by": "project_owner",
                    "review_reference": "codex-thread:test",
                    "review_recorded_at": "2026-07-20T00:00:00Z",
                    "row_count": len(rows),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")

    @staticmethod
    def _birth_year_row(
        *,
        external_id,
        parent_name,
        sire_name,
        dam_name,
        birth_year=1990,
    ):
        source_url = (
            f"https://en.netkeiba.com/db/horse/{external_id}/"
        )
        return {
            "legacy_parent_source_name": "netkeiba_en",
            "legacy_parent_external_horse_id": external_id,
            "legacy_parent_source_url": source_url,
            "parent_source_name": "netkeiba_en",
            "parent_external_horse_id": external_id,
            "parent_source_url": source_url,
            "parent_name": parent_name,
            "parent_sire_name": sire_name,
            "parent_dam_name": dam_name,
            "parent_birth_year": birth_year,
            "birth_year_evidence_source_name": "netkeiba_en",
            "birth_year_evidence_source_url": source_url,
            "birth_year_verification_method": (
                "direct_or_related_profile_manual_year_review"
            ),
            "birth_year_evidence_note": "Birth year manually reviewed.",
            "correction_reason": "",
        }

    def test_unicode_name_normalization_keeps_distinct_horse_names(self):
        self.assertNotEqual(
            normalized_name("シンボリルドルフ"),
            normalized_name("ディープインパクト"),
        )
        candidate, reason = select_parent_candidate(
            [
                {
                    "name": "ディープインパクト",
                    "sire": "サンデーサイレンス",
                    "dam": "ウインドインハーヘア",
                }
            ],
            parent_name="シンボリルドルフ",
        )
        self.assertIsNone(candidate)
        self.assertEqual(reason, "no_identity_matched_candidate")

    def test_parent_client_rejects_empty_normalized_cache_key(self):
        client = NetkeibaParentResearchClient(request_interval_seconds=0)

        with self.assertRaisesMessage(ValueError, "empty cache key"):
            client.search("!!!")

    def test_search_parser_retains_parent_identity_and_profile_url(self):
        candidates = parse_search_candidates(SEARCH_HTML)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[1]["name"], "Shared Dam")
        self.assertEqual(candidates[1]["sire"], "Known Damsire")
        self.assertEqual(candidates[1]["dam"], "Correct Granddam")
        self.assertEqual(candidates[1]["birth_year"], "2002")
        self.assertEqual(candidates[1]["horse_id"], "parent-right")
        self.assertEqual(
            candidates[1]["profile_url"],
            "https://en.netkeiba.com/db/horse/parent-right/",
        )

    def test_unique_name_without_strong_parent_identity_stays_unresolved(self):
        candidate, reason = select_parent_candidate(
            [
                {
                    "horse_id": "parent-only",
                    "name": "Unique Parent",
                    "sire": "Known Grandsire",
                    "dam": "Known Granddam",
                    "birth_year": "2002",
                    "profile_url": (
                        "https://en.netkeiba.com/db/horse/parent-only/"
                    ),
                }
            ],
            parent_name="Unique Parent",
        )

        self.assertIsNone(candidate)
        self.assertEqual(reason, "insufficient_parent_identity_evidence")

    def test_parent_external_id_is_opaque_and_requires_complete_source_identity(self):
        candidates = [
            {
                "horse_id": "AB-12",
                "name": "Shared Parent",
                "sire": "Known Grandsire",
                "dam": "Known Granddam",
                "birth_year": "2002",
                "profile_url": "https://en.netkeiba.com/db/horse/AB-12/",
            }
        ]

        candidate, reason = select_parent_candidate(
            candidates,
            parent_name="Shared Parent",
            expected_external_id="AB-12",
        )
        mismatched, mismatch_reason = select_parent_candidate(
            candidates,
            parent_name="Shared Parent",
            expected_external_id="ab12",
        )
        padded, padded_reason = select_parent_candidate(
            candidates,
            parent_name="Shared Parent",
            expected_external_id=" AB-12 ",
        )

        self.assertEqual(reason, "")
        self.assertEqual(candidate["horse_id"], "AB-12")
        self.assertEqual(
            candidate["identity_verification_method"],
            "parent_source_external_id_match",
        )
        self.assertIsNone(mismatched)
        self.assertEqual(mismatch_reason, "no_identity_matched_candidate")
        self.assertIsNone(padded)
        self.assertEqual(padded_reason, "no_identity_matched_candidate")

    def test_parent_candidate_rejects_noncanonical_netkeiba_profile_urls(self):
        invalid_urls = (
            "http://en.netkeiba.com/db/horse/AB-12/",
            "https://example.com/db/horse/AB-12/",
            "https://user:pass@en.netkeiba.com/db/horse/AB-12/",
            "https://en.netkeiba.com:443/db/horse/AB-12/",
            "https://en.netkeiba.com/db/horse/AB-12/?source=search",
            "https://en.netkeiba.com/db/horse/AB-12/#profile",
            "https://en.netkeiba.com/db/horse/AB-12",
            "https://en.netkeiba.com/other/db/horse/AB-12/",
            "https://en.netkeiba.com/db/horse/AB-12/extra/",
        )
        for profile_url in invalid_urls:
            with self.subTest(profile_url=profile_url):
                candidate, reason = select_parent_candidate(
                    [
                        {
                            "horse_id": "AB-12",
                            "name": "Shared Parent",
                            "sire": "Known Sire",
                            "dam": "Known Dam",
                            "birth_year": "2002",
                            "profile_url": profile_url,
                        }
                    ],
                    parent_name="Shared Parent",
                    expected_external_id="AB-12",
                )
                self.assertIsNone(candidate)
                self.assertEqual(
                    reason,
                    "incomplete_parent_source_identity",
                )

    def test_dam_selection_uses_known_damsire_to_reject_same_name_horse(self):
        candidate, reason = select_parent_candidate(
            parse_search_candidates(SEARCH_HTML),
            parent_name="Shared Dam",
            expected_sire="Known Damsire",
        )

        self.assertEqual(reason, "")
        self.assertEqual(candidate["dam"], "Correct Granddam")

    def test_parent_evidence_fills_only_missing_fields_and_keeps_source(self):
        horse = {
            "pedigree": {
                "sire": "Test Sire",
                "dam": "Test Dam",
                "dam_sire": "Known Damsire",
            }
        }

        evidence = apply_parent_evidence(
            horse,
            role="dam",
            candidate={
                "name": "Test Dam",
                "horse_id": "test-dam",
                "sire": "Known Damsire",
                "dam": "Correct Granddam",
                "birth_year": "2002",
                "profile_url": "https://en.netkeiba.com/db/horse/test-dam/",
                "identity_verification_method": (
                    "parent_complete_identity_and_known_sire_match"
                ),
            },
            verified_at="2026-07-19T00:00:00+00:00",
        )

        self.assertEqual(horse["pedigree"]["dam_sire"], "Known Damsire")
        self.assertEqual(horse["pedigree"]["dam_dam"], "Correct Granddam")
        self.assertEqual(evidence[-1]["status"], "verified_secondary_source")
        self.assertEqual(
            evidence[-1]["verification_method"],
            "parent_complete_identity_and_known_sire_match",
        )
        self.assertEqual(evidence[-1]["source_external_horse_id"], "test-dam")

    def test_manual_evidence_requires_identity_corroboration(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Shared Dam",
                        "dam_sire": "Known Damsire",
                    },
                    "field_status": {
                        "missing_pedigree_fields": ["dam_dam"],
                    },
                }
            ]
        }

        with self.assertRaisesMessage(ValueError, "identity mismatch"):
            apply_manual_evidence(
                data,
                [
                    {
                        "region": "france",
                        "horse_name": "Target Horse",
                        "expected_identity_key": (
                            "Target Horse | Target Sire | Shared Dam | 2020"
                        ),
                        "expected_sire": "Target Sire",
                        "expected_dam": "Shared Dam",
                        "expected_dam_sire": "Wrong Damsire",
                        "field_name": "dam_dam",
                        "value": "Wrong Granddam",
                    }
                ],
            )

    def test_manual_evidence_fills_missing_value_and_refreshes_status(self):
        data = {
            "horses": [
                {
                    "region": "united_states",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                        "sire_sire": "Target Grandsire",
                        "sire_dam": "Target Granddam",
                        "dam_sire": "Known Damsire",
                    },
                    "field_status": {
                        "missing_pedigree_fields": ["dam_dam"],
                    },
                }
            ]
        }

        filled_count, applied = apply_manual_evidence(
            data,
            [
                {
                    "region": "united_states",
                    "horse_name": "Target Horse",
                    "expected_identity_key": (
                        "Target Horse | Target Sire | Target Dam | 2020"
                    ),
                    "expected_sire": "Target Sire",
                    "expected_dam": "Target Dam",
                    "expected_dam_sire": "Known Damsire",
                    "field_name": "dam_dam",
                    "value": "Verified Granddam",
                    "source_name": "manual_source",
                    "source_url": "https://example.com/pedigree",
                    "verified_at": "2026-07-19T00:00:00Z",
                    "verification_method": "manual_parent_pedigree_review",
                    "evidence_note": "父母身份和字段值已人工交叉核验。",
                }
            ],
        )

        horse = data["horses"][0]
        self.assertEqual(filled_count, 1)
        self.assertEqual(horse["pedigree"]["dam_dam"], "Verified Granddam")
        self.assertEqual(horse["field_status"]["missing_pedigree_fields"], [])
        self.assertEqual(applied[0]["source_name"], "manual_source")

    def test_manual_evidence_ignores_unrelated_horses_without_identity_name(self):
        data = {
            "horses": [
                {
                    "region": "japan",
                    "identity": {},
                    "candidate": {"horse_name": "馬名一"},
                    "pedigree": {},
                },
                {
                    "region": "japan",
                    "identity": {},
                    "candidate": {"horse_name": "馬名二"},
                    "pedigree": {},
                },
                {
                    "region": "france",
                    "identity": {"horse_name": "Target Horse"},
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                        "sire_sire": "Target Grandsire",
                        "sire_dam": "Target Granddam",
                        "dam_sire": "Known Damsire",
                    },
                    "field_status": {
                        "missing_pedigree_fields": ["dam_dam"],
                    },
                    "basic_profile": {"birth_date": "2020-01-01"},
                },
            ]
        }

        filled_count, _ = apply_manual_evidence(
            data,
            [
                {
                    "region": "france",
                    "horse_name": "Target Horse",
                    "expected_identity_key": (
                        "Target Horse | Target Sire | Target Dam | 2020"
                    ),
                    "expected_sire": "Target Sire",
                    "expected_dam": "Target Dam",
                    "expected_dam_sire": "Known Damsire",
                    "field_name": "dam_dam",
                    "value": "Verified Granddam",
                    "source_name": "manual_source",
                    "source_url": "https://example.com/pedigree",
                    "verified_at": "2026-07-19T00:00:00Z",
                    "verification_method": "manual_parent_pedigree_review",
                    "evidence_note": "父母身份和字段值已人工交叉核验。",
                }
            ],
        )

        self.assertEqual(filled_count, 1)

    def test_manual_evidence_identity_ignores_region_and_prefers_source_id(self):
        def horse(region, source_id):
            return {
                "region": region,
                "source": {
                    "name": "sporting_life",
                    "external_horse_id": source_id,
                },
                "identity": {
                    "horse_name": "Shared Horse",
                    "birth_year": 2020,
                },
                "pedigree": {
                    "sire": "Shared Sire",
                    "dam": "Shared Dam",
                },
                "field_status": {
                    "missing_pedigree_fields": ["sire_sire"],
                },
            }

        first = horse("france", "horse-a")
        second = horse("united_kingdom", "horse-b")
        filled_count, _ = apply_manual_evidence(
            {"horses": [first, second]},
            [
                {
                    "region": "united_states",
                    "horse_name": "Shared Horse",
                    "expected_source_name": "sporting_life",
                    "expected_external_horse_id": "horse-b",
                    "expected_identity_key": (
                        "Shared Horse | Shared Sire | Shared Dam | 2020"
                    ),
                    "expected_sire": "Shared Sire",
                    "field_name": "sire_sire",
                    "value": "Verified Grandsire",
                    "source_name": "manual_source",
                    "source_url": "https://example.com/pedigree",
                    "verified_at": "2026-07-19T00:00:00Z",
                    "verification_method": "manual_parent_pedigree_review",
                    "evidence_note": "Source ID and parent identity verified.",
                }
            ],
        )

        self.assertEqual(filled_count, 1)
        self.assertNotIn("sire_sire", first["pedigree"])
        self.assertEqual(
            second["pedigree"]["sire_sire"],
            "Verified Grandsire",
        )

    def test_manual_evidence_source_id_is_opaque(self):
        def horse(source_id):
            return {
                "region": "united_states",
                "source": {
                    "name": "official",
                    "external_horse_id": source_id,
                },
                "identity": {
                    "horse_name": "Shared Horse",
                    "birth_year": 2020,
                },
                "pedigree": {
                    "sire": "Shared Sire",
                    "dam": "Shared Dam",
                },
                "field_status": {
                    "missing_pedigree_fields": ["sire_sire"],
                },
            }

        first = horse("AB-12")
        second = horse("ab12")
        filled_count, _ = apply_manual_evidence(
            {"horses": [first, second]},
            [
                {
                    "region": "united_states",
                    "horse_name": "Shared Horse",
                    "expected_source_name": "OFFICIAL",
                    "expected_external_horse_id": "AB-12",
                    "expected_identity_key": (
                        "Shared Horse | Shared Sire | Shared Dam | 2020"
                    ),
                    "expected_sire": "Shared Sire",
                    "field_name": "sire_sire",
                    "value": "Verified Grandsire",
                    "source_name": "manual_source",
                    "source_url": "https://example.com/pedigree",
                    "verified_at": "2026-07-19T00:00:00Z",
                    "verification_method": "manual_parent_pedigree_review",
                    "evidence_note": "Opaque provider ID verified.",
                }
            ],
        )

        self.assertEqual(filled_count, 1)
        self.assertEqual(first["pedigree"]["sire_sire"], "Verified Grandsire")
        self.assertNotIn("sire_sire", second["pedigree"])

    def test_manual_evidence_rejects_missing_four_part_identity(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                    },
                }
            ]
        }

        with self.assertRaisesMessage(ValueError, "expected_identity_key"):
            apply_manual_evidence(
                data,
                [
                    {
                        "region": "france",
                        "horse_name": "Target Horse",
                        "field_name": "dam_dam",
                        "value": "Verified Granddam",
                    }
                ],
            )

    def test_manual_dam_evidence_requires_known_damsire(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Shared Dam",
                        "dam_sire": "Known Damsire",
                    },
                }
            ]
        }

        with self.assertRaisesMessage(ValueError, "expected_dam_sire"):
            apply_manual_evidence(
                data,
                [
                    {
                        "region": "france",
                        "horse_name": "Target Horse",
                        "expected_identity_key": (
                            "Target Horse | Target Sire | Shared Dam | 2020"
                        ),
                        "expected_dam": "Shared Dam",
                        "field_name": "dam_dam",
                        "value": "Verified Granddam",
                        "source_name": "manual_source",
                        "source_url": "https://example.com/pedigree",
                        "verified_at": "2026-07-19T00:00:00Z",
                        "verification_method": "manual_parent_pedigree_review",
                        "evidence_note": "父母身份和字段值已人工交叉核验。",
                    }
                ],
            )

    def test_manual_sire_evidence_requires_expected_sire(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                    },
                }
            ]
        }

        with self.assertRaisesMessage(ValueError, "expected_sire"):
            apply_manual_evidence(
                data,
                [
                    {
                        "region": "france",
                        "horse_name": "Target Horse",
                        "expected_identity_key": (
                            "Target Horse | Target Sire | Target Dam | 2020"
                        ),
                        "field_name": "sire_sire",
                        "value": "Verified Grandsire",
                        "source_name": "manual_source",
                        "source_url": "https://example.com/pedigree",
                        "verified_at": "2026-07-19T00:00:00Z",
                        "verification_method": "manual_parent_pedigree_review",
                        "evidence_note": "父母身份和字段值已人工交叉核验。",
                    }
                ],
            )

    def test_manual_evidence_requires_complete_audit_metadata(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                    },
                }
            ]
        }
        complete_row = {
            "region": "france",
            "horse_name": "Target Horse",
            "expected_identity_key": (
                "Target Horse | Target Sire | Target Dam | 2020"
            ),
            "expected_sire": "Target Sire",
            "field_name": "sire_sire",
            "value": "Verified Grandsire",
            "source_name": "manual_source",
            "source_url": "https://example.com/pedigree",
            "verified_at": "2026-07-19T00:00:00Z",
            "verification_method": "manual_parent_pedigree_review",
            "evidence_note": "父马身份和字段值已人工交叉核验。",
        }

        for missing_key in (
            "source_name",
            "source_url",
            "verified_at",
            "verification_method",
            "evidence_note",
        ):
            with self.subTest(missing_key=missing_key):
                row = complete_row | {missing_key: ""}
                with self.assertRaisesMessage(ValueError, missing_key):
                    apply_manual_evidence(data, [row])

    def test_manual_evidence_rejects_invalid_url_and_unzoned_time(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                    },
                }
            ]
        }
        complete_row = {
            "region": "france",
            "horse_name": "Target Horse",
            "expected_identity_key": (
                "Target Horse | Target Sire | Target Dam | 2020"
            ),
            "expected_sire": "Target Sire",
            "field_name": "sire_sire",
            "value": "Verified Grandsire",
            "source_name": "manual_source",
            "source_url": "https://example.com/pedigree",
            "verified_at": "2026-07-19T00:00:00Z",
            "verification_method": "manual_parent_pedigree_review",
            "evidence_note": "父马身份和字段值已人工交叉核验。",
        }

        for invalid_url in (
            "not-a-url",
            "https://bad host.example/pedigree",
            "https://example.com:not-a-port/pedigree",
        ):
            with self.subTest(url=invalid_url):
                with self.assertRaisesMessage(ValueError, "source_url"):
                    apply_manual_evidence(
                        data,
                        [complete_row | {"source_url": invalid_url}],
                    )
        with self.assertRaisesMessage(ValueError, "verified_at"):
            apply_manual_evidence(
                data,
                [complete_row | {"verified_at": "2026-07-19T00:00:00"}],
            )

    def test_manual_evidence_rejects_non_string_audit_metadata(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                    },
                }
            ]
        }
        complete_row = {
            "region": "france",
            "horse_name": "Target Horse",
            "expected_identity_key": (
                "Target Horse | Target Sire | Target Dam | 2020"
            ),
            "expected_sire": "Target Sire",
            "field_name": "sire_sire",
            "value": "Verified Grandsire",
            "source_name": "manual_source",
            "source_url": "https://example.com/pedigree",
            "verified_at": "2026-07-19T00:00:00Z",
            "verification_method": "manual_parent_pedigree_review",
            "evidence_note": "父马身份和字段值已人工交叉核验。",
        }

        invalid_values = {
            "source_name": 123,
            "source_url": [],
            "verified_at": {"timestamp": "2026-07-19T00:00:00Z"},
            "verification_method": {"method": "manual"},
            "evidence_note": ["reviewed"],
        }
        for audit_key, invalid_value in invalid_values.items():
            with self.subTest(audit_key=audit_key):
                with self.assertRaisesMessage(ValueError, audit_key):
                    apply_manual_evidence(
                        data,
                        [complete_row | {audit_key: invalid_value}],
                    )

    def test_unresolved_disposition_is_calculated_per_parent_role(self):
        horse = {
            "region": "france",
            "candidate": {"horse_name": "Target Horse"},
            "identity": {
                "horse_name": "Target Horse",
                "birth_year": 2020,
            },
            "pedigree": {
                "sire": "Target Sire",
                "dam": "Target Dam",
                "sire_sire": "Target Grandsire",
                "dam_sire": "Known Damsire",
            },
            "field_status": {
                "missing_pedigree_fields": ["sire_dam", "dam_dam"],
            },
        }
        queries = [
            {
                "region": "france",
                "horse_name": "Target Horse",
                "identity_key": "Target Horse | Target Sire | Target Dam | 2020",
                "parent_role": "sire",
                "target_fields": ["sire_sire"],
            },
            {
                "region": "france",
                "horse_name": "Target Horse",
                "identity_key": "Target Horse | Target Sire | Target Dam | 2020",
                "parent_role": "dam",
                "target_fields": ["dam_dam"],
            },
        ]

        finalize_automatic_unresolved_queries({"horses": [horse]}, queries)

        self.assertEqual(queries[0]["final_disposition"], "resolved_by_manual_evidence")
        self.assertEqual(queries[0]["final_missing_fields"], [])
        self.assertEqual(queries[1]["final_disposition"], "still_missing")
        self.assertEqual(queries[1]["final_missing_fields"], ["dam_dam"])

    def test_unresolved_disposition_rejects_invalid_query_shape(self):
        data = {
            "horses": [
                {
                    "region": "france",
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                    },
                }
            ]
        }
        base_query = {
            "region": "france",
            "horse_name": "Target Horse",
            "identity_key": "Target Horse | Target Sire | Target Dam | 2020",
            "parent_role": "sire",
            "target_fields": ["sire_sire"],
        }

        for invalid_query in (
            base_query | {"parent_role": "unknown"},
            base_query | {"target_fields": []},
            base_query | {"target_fields": ["dam_dam"]},
        ):
            with self.subTest(invalid_query=invalid_query):
                with self.assertRaisesMessage(ValueError, "automatic unresolved query"):
                    finalize_automatic_unresolved_queries(data, [invalid_query])

    def test_reviewed_parent_identity_manifest_binds_exact_input_and_source_ids(self):
        data = {
            "horses": [
                {
                    "region": "united_states",
                    "source": {
                        "name": "official",
                        "external_horse_id": "AB-12",
                    },
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                        "sire_sire": "Target Grandsire",
                        "sire_dam": "Target Granddam",
                        "dam_sire": "Known Damsire",
                        "dam_dam": "Known Damdam",
                    },
                    "pedigree_field_evidence": [
                        {
                            "field_name": "sire_sire",
                            "value": "Target Grandsire",
                            "status": "verified_secondary_source",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                        {
                            "field_name": "sire_dam",
                            "value": "Target Granddam",
                            "status": "verified_secondary_source",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                        {
                            "field_name": "dam_sire",
                            "value": "Known Damsire",
                            "status": "verified_secondary_source",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-2/"
                            ),
                            "verification_method": (
                                "exact_parent_name_and_known_sire_match"
                            ),
                        },
                        {
                            "field_name": "dam_dam",
                            "value": "Known Damdam",
                            "status": "verified_secondary_source",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-2/"
                            ),
                            "verification_method": (
                                "exact_parent_name_and_known_sire_match"
                            ),
                        },
                    ],
                }
            ]
        }
        input_bytes = (
            json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        birth_year_evidence_bytes = self._birth_year_evidence_bytes(
            [
                self._birth_year_row(
                    external_id="PARENT-1",
                    parent_name="Target Sire",
                    sire_name="Target Grandsire",
                    dam_name="Target Granddam",
                ),
                self._birth_year_row(
                    external_id="PARENT-2",
                    parent_name="Target Dam",
                    sire_name="Known Damsire",
                    dam_name="Known Damdam",
                ),
            ]
        )
        manifest = prepare_manifest(
            input_bytes,
            birth_year_evidence_bytes,
            reviewed_by="project_owner",
            review_reference="codex-thread:test",
            review_recorded_at="2026-07-19T12:00:00Z",
        )
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")

        output = json.loads(
            apply_manifest(
                input_bytes,
                manifest_bytes,
                birth_year_evidence_bytes,
            )
        )
        evidence = output["horses"][0]["pedigree_field_evidence"][0]

        self.assertEqual(evidence["verification_method"], REVIEWED_METHOD)
        self.assertEqual(evidence["source_external_horse_id"], "PARENT-1")
        self.assertEqual(evidence["source_identity"]["birth_year"], 1990)
        self.assertEqual(manifest["rows"][0]["parent_birth_year"], 1990)
        self.assertEqual(
            manifest["rows"][0]["parent_birth_year_evidence_source_name"],
            "netkeiba_en",
        )
        self.assertEqual(
            manifest["rows"][0]["parent_birth_year_verification_method"],
            "direct_or_related_profile_manual_year_review",
        )
        self.assertEqual(
            output["parent_identity_review_application"]["row_count"],
            4,
        )
        self.assertEqual(
            output["parent_identity_review_application"][
                "filled_field_review_count"
            ],
            3,
        )
        self.assertEqual(
            evidence["source_identity"],
            {
                "horse_name": "Target Sire",
                "sire_name": "Target Grandsire",
                "dam_name": "Target Granddam",
                "birth_year": 1990,
            },
        )

        mismatched = json.loads(manifest_bytes)
        mismatched["rows"][0]["target_external_horse_id"] = "ab12"
        mismatched_bytes = (
            json.dumps(mismatched, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        with self.assertRaisesMessage(ValueError, "do not exactly match"):
            apply_manifest(
                input_bytes,
                mismatched_bytes,
                birth_year_evidence_bytes,
            )

        drifted_evidence = json.loads(birth_year_evidence_bytes)
        drifted_evidence["rows"][0]["parent_birth_year"] = 1989
        drifted_evidence_bytes = (
            json.dumps(drifted_evidence) + "\n"
        ).encode()
        with self.assertRaisesMessage(
            ValueError,
            "birth-year evidence SHA-256",
        ):
            apply_manifest(
                input_bytes,
                manifest_bytes,
                drifted_evidence_bytes,
            )

    def test_parent_birth_year_evidence_requires_exact_coverage_and_valid_years(self):
        data = {
            "horses": [
                {
                    "source": {
                        "name": "official",
                        "external_horse_id": "horse-1",
                    },
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                        "sire_sire": "Target Grandsire",
                        "sire_dam": "Target Granddam",
                    },
                    "pedigree_field_evidence": [
                        {
                            "field_name": "sire_sire",
                            "value": "Target Grandsire",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                        {
                            "field_name": "sire_dam",
                            "value": "Target Granddam",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                    ],
                }
            ]
        }
        input_bytes = (json.dumps(data) + "\n").encode()
        valid_row = self._birth_year_row(
            external_id="PARENT-1",
            parent_name="Target Sire",
            sire_name="Target Grandsire",
            dam_name="Target Granddam",
        )

        with self.assertRaisesMessage(ValueError, "exactly cover"):
            prepare_manifest(
                input_bytes,
                self._birth_year_evidence_bytes([]),
                reviewed_by="project_owner",
                review_reference="codex-thread:test",
                review_recorded_at="2026-07-20T00:00:00Z",
            )

        for invalid_year in ("1990", 1799, 2020, 9999):
            with self.subTest(parent_birth_year=invalid_year):
                invalid_row = valid_row | {
                    "parent_birth_year": invalid_year,
                }
                with self.assertRaisesMessage(ValueError, "parent_birth_year"):
                    prepare_manifest(
                        input_bytes,
                        self._birth_year_evidence_bytes([invalid_row]),
                        reviewed_by="project_owner",
                        review_reference="codex-thread:test",
                        review_recorded_at="2026-07-20T00:00:00Z",
                    )

    def test_parent_identity_is_globally_consistent_across_target_horses(self):
        horses = []
        for target_id, parent_name in (
            ("horse-1", "Target Sire"),
            ("horse-2", "Different Same-ID Sire"),
        ):
            horses.append(
                {
                    "source": {
                        "name": "official",
                        "external_horse_id": target_id,
                    },
                    "identity": {
                        "horse_name": f"Target {target_id}",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": parent_name,
                        "dam": f"Dam {target_id}",
                        "sire_sire": "Target Grandsire",
                        "sire_dam": "Target Granddam",
                    },
                    "pedigree_field_evidence": [
                        {
                            "field_name": field_name,
                            "value": value,
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/PARENT-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        }
                        for field_name, value in (
                            ("sire_sire", "Target Grandsire"),
                            ("sire_dam", "Target Granddam"),
                        )
                    ],
                }
            )
        input_bytes = (
            json.dumps({"horses": horses}) + "\n"
        ).encode()
        evidence_bytes = self._birth_year_evidence_bytes(
            [
                self._birth_year_row(
                    external_id="PARENT-1",
                    parent_name="Target Sire",
                    sire_name="Target Grandsire",
                    dam_name="Target Granddam",
                )
            ]
        )

        with self.assertRaisesMessage(ValueError, "globally inconsistent"):
            prepare_manifest(
                input_bytes,
                evidence_bytes,
                reviewed_by="project_owner",
                review_reference="codex-thread:test",
                review_recorded_at="2026-07-20T00:00:00Z",
            )

    def test_balko_reviewed_correction_replaces_only_v2_parent_identity(self):
        data = {
            "horses": [
                {
                    "source": {
                        "name": "sporting_life",
                        "external_horse_id": "1137721",
                    },
                    "identity": {
                        "horse_name": "Kentucky Wood",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Balko",
                        "dam": "Carrieriste",
                        "sire_sire": "Omar Khayyam",
                        "sire_dam": "Rahu",
                    },
                    "pedigree_field_evidence": [
                        {
                            "field_name": "sire_sire",
                            "value": "Omar Khayyam",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/000a02bd3f/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                        {
                            "field_name": "sire_dam",
                            "value": "Rahu",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/000a02bd3f/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                    ],
                }
            ]
        }
        input_bytes = (
            json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        correction_reason = (
            "Legacy Netkeiba ID 000a02bd3f identifies a different "
            "1925 namesake."
        )
        birth_year_evidence_bytes = self._birth_year_evidence_bytes(
            [
                {
                    "legacy_parent_source_name": "netkeiba_en",
                    "legacy_parent_external_horse_id": "000a02bd3f",
                    "legacy_parent_source_url": (
                        "https://en.netkeiba.com/db/horse/000a02bd3f/"
                    ),
                    "parent_source_name": "racing_post",
                    "parent_external_horse_id": "595446",
                    "parent_source_url": (
                        "https://www.racingpost.com/profile/horse/"
                        "595446/balko"
                    ),
                    "parent_name": "Balko",
                    "parent_sire_name": "Pistolet Bleu",
                    "parent_dam_name": "Ella Royale",
                    "parent_birth_year": 2001,
                    "birth_year_evidence_source_name": "racing_post",
                    "birth_year_evidence_source_url": (
                        "https://www.racingpost.com/profile/horse/"
                        "595446/balko"
                    ),
                    "birth_year_verification_method": (
                        "direct_profile_manual_year_and_parent_review"
                    ),
                    "birth_year_evidence_note": (
                        "Profile explicitly shows 01Jan01 and parents."
                    ),
                    "correction_reason": correction_reason,
                }
            ]
        )
        manifest = prepare_manifest(
            input_bytes,
            birth_year_evidence_bytes,
            reviewed_by="project_owner",
            review_reference="codex-thread:test",
            review_recorded_at="2026-07-20T00:00:00Z",
        )
        output = json.loads(
            apply_manifest(
                input_bytes,
                (json.dumps(manifest) + "\n").encode(),
                birth_year_evidence_bytes,
            )
        )
        horse = output["horses"][0]
        evidence = horse["pedigree_field_evidence"][0]

        self.assertEqual(data["horses"][0]["pedigree"]["sire_sire"], "Omar Khayyam")
        self.assertEqual(horse["pedigree"]["sire_sire"], "Pistolet Bleu")
        self.assertEqual(horse["pedigree"]["sire_dam"], "Ella Royale")
        self.assertEqual(evidence["value"], "Pistolet Bleu")
        self.assertEqual(evidence["source_name"], "racing_post")
        self.assertEqual(evidence["source_external_horse_id"], "595446")
        self.assertEqual(evidence["source_identity"]["birth_year"], 2001)
        self.assertEqual(evidence["legacy_value"], "Omar Khayyam")
        self.assertEqual(evidence["legacy_source_name"], "netkeiba_en")
        self.assertEqual(
            evidence["legacy_source_external_horse_id"],
            "000a02bd3f",
        )
        self.assertEqual(
            evidence["identity_correction"]["reason"],
            correction_reason,
        )

    def test_frozen_birth_year_artifact_deterministically_rebuilds_real_v2(self):
        root = Path(__file__).resolve().parents[2]
        artifact_dir = (
            root
            / "runtime/horse_profile_completion/pedigree-research-20260719"
        )
        input_bytes = (
            artifact_dir / "p0_horse_research_50_enriched.json"
        ).read_bytes()
        birth_year_evidence_bytes = (
            artifact_dir / "reviewed_parent_birth_year_evidence.json"
        ).read_bytes()
        birth_year_artifact = json.loads(birth_year_evidence_bytes)
        persisted_manifest_bytes = (
            artifact_dir / "reviewed_parent_identity_evidence.json"
        ).read_bytes()
        persisted_manifest = json.loads(persisted_manifest_bytes)
        self.assertEqual(
            birth_year_artifact["reviewed_by"],
            "codex_manual_source_review",
        )
        self.assertEqual(
            birth_year_artifact["review_reference"],
            "codex-task:p0-parent-birth-year-research-20260719",
        )
        self.assertTrue(
            all(
                row["birth_year_evidence_note"].startswith(
                    "Manually reviewed"
                )
                and "User-provided" not in row["birth_year_evidence_note"]
                for row in birth_year_artifact["rows"]
            )
        )
        self.assertEqual(persisted_manifest["reviewed_by"], "project_owner")
        self.assertEqual(
            persisted_manifest["review_reference"],
            "codex-task:p0-horse-parent-identity-review-20260719",
        )
        self.assertEqual(
            persisted_manifest["parent_birth_year_evidence"]["reviewed_by"],
            "codex_manual_source_review",
        )
        self.assertEqual(
            persisted_manifest["parent_birth_year_evidence"][
                "review_reference"
            ],
            "codex-task:p0-parent-birth-year-research-20260719",
        )
        rebuilt_manifest = prepare_manifest(
            input_bytes,
            birth_year_evidence_bytes,
            reviewed_by=persisted_manifest["reviewed_by"],
            review_reference=persisted_manifest["review_reference"],
            review_recorded_at=persisted_manifest["review_recorded_at"],
        )
        rebuilt_manifest_bytes = (
            json.dumps(
                rebuilt_manifest,
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode()
        rebuilt_output = apply_manifest(
            input_bytes,
            rebuilt_manifest_bytes,
            birth_year_evidence_bytes,
        )

        self.assertEqual(rebuilt_manifest_bytes, persisted_manifest_bytes)
        self.assertEqual(
            rebuilt_output,
            (
                artifact_dir / "p0_horse_research_50_enriched_v2.json"
            ).read_bytes(),
        )
        self.assertEqual(rebuilt_manifest["row_count"], 116)
        self.assertEqual(
            rebuilt_manifest["parent_birth_year_evidence"]["row_count"],
            55,
        )

        output = json.loads(rebuilt_output)
        reviewed_evidence = [
            (horse, evidence)
            for horse in output["horses"]
            for evidence in horse.get("pedigree_field_evidence", [])
            if evidence.get("verification_method") == REVIEWED_METHOD
        ]
        self.assertEqual(len(reviewed_evidence), 116)
        for horse, evidence in reviewed_evidence:
            parent_birth_year = evidence["source_identity"]["birth_year"]
            self.assertIs(type(parent_birth_year), int)
            self.assertGreaterEqual(parent_birth_year, 1800)
            self.assertLess(
                parent_birth_year,
                horse["identity"]["birth_year"],
            )

        kentucky_wood = next(
            horse
            for horse in output["horses"]
            if horse["identity"]["horse_name"] == "Kentucky Wood"
        )
        self.assertEqual(
            kentucky_wood["pedigree"]["sire_sire"],
            "Pistolet Bleu",
        )
        self.assertEqual(
            kentucky_wood["pedigree"]["sire_dam"],
            "Ella Royale",
        )
        self.assertNotIn(
            "000a02bd3f",
            {
                evidence.get("source_external_horse_id")
                for evidence in kentucky_wood["pedigree_field_evidence"]
            },
        )

        guajira_evidence = [
            evidence
            for horse, evidence in reviewed_evidence
            if horse["identity"]["horse_name"] == "Gabrial"
            and evidence["field_name"] in {"dam_sire", "dam_dam"}
        ]
        self.assertEqual(len(guajira_evidence), 2)
        self.assertEqual(
            {item["source_identity"]["birth_year"] for item in guajira_evidence},
            {2003},
        )

    def test_reviewed_parent_identity_manifest_rejects_input_drift(self):
        data = {
            "horses": [
                {
                    "source": {
                        "name": "official",
                        "external_horse_id": "horse-1",
                    },
                    "identity": {
                        "horse_name": "Target Horse",
                        "birth_year": 2020,
                    },
                    "pedigree": {
                        "sire": "Target Sire",
                        "dam": "Target Dam",
                        "sire_sire": "Target Grandsire",
                        "sire_dam": "Target Granddam",
                    },
                    "pedigree_field_evidence": [
                        {
                            "field_name": "sire_sire",
                            "value": "Target Grandsire",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/parent-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                        {
                            "field_name": "sire_dam",
                            "value": "Target Granddam",
                            "source_name": "netkeiba_en",
                            "source_url": (
                                "https://en.netkeiba.com/db/horse/parent-1/"
                            ),
                            "verification_method": LEGACY_METHOD,
                        },
                    ],
                }
            ]
        }
        input_bytes = (json.dumps(data) + "\n").encode()
        birth_year_evidence_bytes = self._birth_year_evidence_bytes(
            [
                self._birth_year_row(
                    external_id="parent-1",
                    parent_name="Target Sire",
                    sire_name="Target Grandsire",
                    dam_name="Target Granddam",
                )
            ]
        )
        manifest = prepare_manifest(
            input_bytes,
            birth_year_evidence_bytes,
            reviewed_by="project_owner",
            review_reference="codex-thread:test",
            review_recorded_at="2026-07-19T12:00:00Z",
        )
        manifest_bytes = (json.dumps(manifest) + "\n").encode()
        drifted_bytes = input_bytes.replace(b"Target Horse", b"Other Horse")

        with self.assertRaisesMessage(ValueError, "SHA-256"):
            apply_manifest(
                drifted_bytes,
                manifest_bytes,
                birth_year_evidence_bytes,
            )
