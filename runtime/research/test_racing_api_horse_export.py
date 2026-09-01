#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("racing_api_horse_export.py")


def load_tool():
    if not SCRIPT_PATH.is_file():
        raise AssertionError(f"目标入口尚不存在：{SCRIPT_PATH}")
    if str(SCRIPT_PATH.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT_PATH.parent))
    spec = importlib.util.spec_from_file_location("racing_api_horse_export", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载目标入口：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_openapi_fingerprint(module, root: Path, **overrides):
    payload = {
        "fingerprint_generated_at": "2026-08-29T15:33:04+08:00",
        "full_openapi_sha256": module.EXPECTED_OPENAPI_FULL_SHA256,
        "openapi_version": module.EXPECTED_OPENAPI_VERSION,
        "selected_contract": {
            "paths": list(module.EXPECTED_OPENAPI_SELECTED_PATHS),
            "sha256": module.EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
        },
        "selected_schema": {
            "names": list(module.EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES),
            "sha256": module.EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
        },
        "source_url": module.OPENAPI_SOURCE_URL,
    }
    payload.update(overrides)
    path = root / "openapi-fingerprint.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, sha256


def montjeu_profile(**overrides):
    value = {
        "id": "hrs_1024",
        "name": "Montjeu (IRE)",
        "dob": "1996-04-04",
        "sex": "horse",
        "sex_code": "H",
        "colour": "b",
        "colour_code": "B",
        "breeder": "Sir James Goldsmith",
        "sire": "Sadler's Wells (USA)",
        "sire_id": "sir_100",
        "dam": "Floripedes (FR)",
        "dam_id": "dam_200",
        "damsire": "Top Ville (IRE)",
        "damsire_id": "dsi_300",
    }
    value.update(overrides)
    return value


def arc_result(*, runners=None, race_id="rac_arc_1999"):
    return {
        "race_id": race_id,
        "date": "1999-10-03",
        "off_dt": "1999-10-03T15:30:00+02:00",
        "region": "FR",
        "course": "Longchamp (FR)",
        "course_id": "crs_longchamp",
        "off": "3:30",
        "race_name": "Prix de l'Arc de Triomphe",
        "type": "Flat",
        "class": "",
        "pattern": "G1",
        "rating_band": "",
        "age_band": "3yo+",
        "sex_rest": "",
        "dist": "1m4f",
        "dist_y": "2400",
        "dist_m": "2400",
        "dist_f": "12f",
        "going": "Very Soft",
        "surface": "Turf",
        "runners": runners
        or [
            {
                "horse_id": "hrs_1024",
                "horse": "Montjeu (IRE)",
                "position": "1",
                "number": "7",
                "draw": "2",
                "weight": "9-0",
                "weight_lbs": "126",
            },
            {"horse_id": "hrs_2048", "horse": "El Condor Pasa (USA)", "position": "2", "number": "4"},
            {"horse_id": "hrs_4096", "horse": "Crocodile Dundee (IRE)", "position": "NR", "number": "9"},
        ],
    }


class RacingApiHorseExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = load_tool()

    def test_country_suffix_and_parent_ids_are_preserved_and_normalized(self):
        normalized = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")

        self.assertEqual(normalized["raw_name"], "Montjeu (IRE)")
        self.assertEqual(normalized["name"], "Montjeu")
        self.assertEqual(normalized["country_suffix"], "IRE")
        self.assertEqual(normalized["parent_profile_ids"], ["hrs_100", "hrs_200", "hrs_300"])

    def test_reviewed_openapi_fingerprint_is_sha_and_contract_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, sha256 = write_openapi_fingerprint(self.module, root)

            identity = self.module.load_openapi_fingerprint(path, sha256)

            self.assertEqual(identity["sha256"], sha256)
            self.assertEqual(identity["source_url"], self.module.OPENAPI_SOURCE_URL)
            self.assertEqual(
                identity["selected_schema_sha256"],
                self.module.EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.module.load_openapi_fingerprint(path, "0" * 64)

            drifted, drifted_sha = write_openapi_fingerprint(
                self.module,
                root,
                openapi_version="9.9.9",
            )
            with self.assertRaisesRegex(ValueError, "reviewed contract drift"):
                self.module.load_openapi_fingerprint(drifted, drifted_sha)

    def test_openapi_fingerprint_drift_stops_before_budget_or_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, _sha256 = write_openapi_fingerprint(self.module, Path(temporary))
            args = SimpleNamespace(
                allow_network=True,
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
                request_ceiling=4,
                openapi_fingerprint=path,
                approved_openapi_fingerprint_sha256="0" * 64,
            )
            with (
                mock.patch.object(self.module, "parse_args", return_value=args),
                mock.patch.object(self.module, "build_exclusive_account_budget") as budget,
                mock.patch.object(self.module, "RacingApiClient") as client,
                mock.patch.dict(
                    self.module.os.environ,
                    {"RACING_API_HORSE_EXPORT_NETWORK_ENABLED": "true"},
                    clear=True,
                ),
            ):
                result = self.module.main()

            self.assertEqual(result, self.module.SAFE_STOP_EXIT_CODE)
            budget.assert_not_called()
            client.assert_not_called()

    def test_artifact_revalidates_fingerprint_before_first_client_call(self):
        class NoRequestClient:
            request_count = 0
            request_ledger = []

            def request_json(self, *_args, **_kwargs):
                raise AssertionError("fingerprint drift must stop before request")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, sha256 = write_openapi_fingerprint(self.module, root)
            identity = self.module.load_openapi_fingerprint(path, sha256)
            path.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "OpenAPI fingerprint"):
                self.module.run_targeted_seed_artifact(
                    seed_path=root / "unread-seed.json",
                    approved_seed_sha256="0" * 64,
                    output_dir=root / "output",
                    client=NoRequestClient(),
                    max_search_candidates=1,
                    max_results_pages_per_horse=1,
                    max_parent_profiles=0,
                    openapi_fingerprint_identity=identity,
                )

            self.assertFalse((root / "output").exists())

    def test_search_resolution_requires_unique_strong_biodata(self):
        search = {
            "search_results": [
                {"id": "hrs_1024", "name": "Montjeu (IRE)", "sire": "Sadler's Wells (USA)", "dam": "Floripedes (FR)"},
                {"id": "hrs_9999", "name": "Montjeu (IRE)", "sire": "Different Sire", "dam": "Different Dam"},
            ]
        }
        seed = {
            "name": "Montjeu",
            "country_suffix": "IRE",
            "dob": "1996-04-04",
            "sex_code": "H",
            "sire": "Sadler's Wells",
            "dam": "Floripedes",
        }

        selected = self.module.select_search_candidate(
            seed,
            search,
            {
                "hrs_1024": montjeu_profile(),
                "hrs_9999": montjeu_profile(
                    id="hrs_9999",
                    sire="Different Sire",
                    sire_id="sir_9998",
                    dam="Different Dam",
                    dam_id="dam_9997",
                ),
            },
        )

        self.assertEqual(selected, "hrs_1024")

    def test_name_only_seed_never_auto_selects(self):
        with self.assertRaisesRegex(ValueError, "strong identity"):
            self.module.select_search_candidate(
                {"name": "Montjeu"},
                {"search_results": [{"id": "hrs_1024", "name": "Montjeu (IRE)"}]},
                {"hrs_1024": montjeu_profile()},
            )

    def test_reliable_winner_seed_can_resolve_by_unique_target_occurrence(self):
        target = {
            "year": 1999,
            "country_region": "france",
            "local_date": "1999-10-03",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "racecourse": "ParisLongchamp",
            "racecourse_aliases": ["Longchamp"],
            "grade_text": "G1",
            "discipline": "flat",
        }
        seed = {
            "name": "Montjeu",
            "expected_finish_position": "1",
            "source_authority": "official_or_reviewed_industry_result",
            "source_url": "https://example.test/1999-arc-result",
            "source_payload_sha256": "a" * 64,
            "target": target,
        }
        search = {
            "search_results": [
                {"id": "hrs_1024", "name": "Montjeu (IRE)"},
                {"id": "hrs_9999", "name": "Montjeu (USA)"},
            ]
        }

        selected = self.module.select_candidate_by_target_occurrence(
            seed,
            search,
            {
                "hrs_1024": [arc_result()],
                "hrs_9999": [
                    {
                        **arc_result(race_id="rac_other"),
                        "date": "2001-01-01",
                        "race_name": "Other Race",
                    }
                ],
            },
        )

        self.assertEqual(selected, "hrs_1024")

    def test_v2_year_only_target_resolves_only_one_structured_occurrence(self):
        target = {
            "year": 1999,
            "edition_year": 1999,
            "country_region": "france",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "race_name_aliases": ["Arc de Triomphe"],
            "racecourse": "Longchamp",
            "grade_text": "G1",
            "discipline": "flat",
        }
        seed = {
            "schema_version": "targeted-horse-seed.v2",
            "name": "Montjeu",
            "country_suffix": "IRE",
            "expected_finish_position": "1",
            "source_authority": "human_reviewed_reference",
            "source_url": "https://example.test/1999-arc-result",
            "source_payload_sha256": "a" * 64,
            "target": target,
        }
        search = {"search_results": [{"id": "hrs_1024", "name": "Montjeu (IRE)"}]}
        unrelated = {
            **arc_result(race_id="rac_prix_foy_1999"),
            "date": "1999-09-12",
            "race_name": "Prix Foy",
            "pattern": "G2",
        }

        selected = self.module.select_candidate_by_target_occurrence(
            seed,
            search,
            {"hrs_1024": [unrelated, arc_result()]},
        )

        self.assertEqual(selected, "hrs_1024")

    def test_v2_year_only_target_fails_closed_on_two_matching_occurrences(self):
        target = {
            "year": 1999,
            "edition_year": 1999,
            "country_region": "france",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "racecourse": "Longchamp",
            "grade_text": "G1",
            "discipline": "flat",
        }
        seed = {
            "schema_version": "targeted-horse-seed.v2",
            "name": "Montjeu",
            "expected_finish_position": "1",
            "source_authority": "human_reviewed_reference",
            "source_url": "https://example.test/1999-arc-result",
            "source_payload_sha256": "a" * 64,
            "target": target,
        }
        search = {"search_results": [{"id": "hrs_1024", "name": "Montjeu (IRE)"}]}
        duplicate = {
            **arc_result(race_id="rac_arc_1999_duplicate"),
            "date": "1999-10-10",
        }

        with self.assertRaisesRegex(ValueError, "candidate count must be 1, got 0"):
            self.module.select_candidate_by_target_occurrence(
                seed,
                search,
                {"hrs_1024": [arc_result(), duplicate]},
            )

    def test_target_occurrence_matches_provider_qualifiers_and_grand_prix_alias(self):
        target = {
            "year": 2023,
            "country_region": "france",
            "local_date": "2023-07-08",
            "canonical_name_original": "Saint-Cloud (G.P. de)",
            "race_name_aliases": ["Saint-Cloud (G.P. de)"],
            "racecourse": "Saint-Cloud",
            "racecourse_aliases": ["Saint-Cloud"],
            "grade_text": "G1",
            "discipline": "flat",
        }
        race = {
            **arc_result(race_id="rac_saint_cloud_2023"),
            "date": "2023-07-08",
            "region": "FR",
            "course": "Saint-Cloud (FR)",
            "course_id": "crs_saint_cloud",
            "race_name": "Grand Prix de Saint-Cloud (4yo+) (Turf)",
            "type": "Flat",
            "pattern": "Group 1",
        }
        race["runners"][0].update(
            {"horse_id": "hrs_26036913", "horse": "Westover (GB)"}
        )

        self.assertTrue(self.module._race_matches_target(target, race))

        unrelated = {**race, "race_name": "Grand Prix de Paris (3yo) (Turf)"}
        self.assertFalse(self.module._race_matches_target(target, unrelated))

    def test_target_occurrence_accepts_sponsor_prefix_with_structured_identity(self):
        target = {
            "year": 2024,
            "country_region": "ireland",
            "local_date": "2024-09-14",
            "canonical_name_original": "Irish Champion",
            "race_name_aliases": ["Irish Champion Stakes"],
            "racecourse": "Leopardstown",
            "grade_text": "G1",
            "discipline": "flat",
        }
        race = {
            **arc_result(race_id="rac_irish_champion_2024"),
            "date": "2024-09-14",
            "region": "IRE",
            "course": "Leopardstown",
            "course_id": "crs_leopardstown",
            "race_name": "Royal Bahrain Irish Champion Stakes (Group 1)",
            "type": "Flat",
            "pattern": "Group 1",
        }

        self.assertTrue(self.module._race_matches_target(target, race))

    def test_target_occurrence_normalizes_grade_and_group_labels(self):
        target = {
            "year": 2024,
            "country_region": "united_kingdom",
            "local_date": "2024-03-15",
            "canonical_name_original": "Triumph Hurdle",
            "race_name_aliases": ["Triumph Hurdle"],
            "racecourse": "Cheltenham",
            "grade_text": "G1",
            "discipline": "jumps",
        }
        race = {
            **arc_result(race_id="rac_triumph_hurdle_2024"),
            "date": "2024-03-15",
            "region": "GB",
            "course": "Cheltenham",
            "course_id": "crs_cheltenham",
            "race_name": "JCB Triumph Hurdle (Grade 1)",
            "type": "Hurdle",
            "pattern": "Grade 1",
        }

        self.assertTrue(self.module._race_matches_target(target, race))

    def test_pagination_uses_returned_count_and_deduplicates_identical_race(self):
        race = arc_result()
        pages = [
            {"results": [race], "total": 2, "limit": 100, "skip": 0, "query": []},
            {"results": [race], "total": 2, "limit": 100, "skip": 1, "query": []},
        ]

        result = self.module.combine_result_pages(pages)

        self.assertEqual(result["provider_row_count"], 2)
        self.assertEqual([item["race_id"] for item in result["races"]], ["rac_arc_1999"])

    def test_pagination_empty_page_before_total_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "empty page before total"):
            self.module.combine_result_pages(
                [{"results": [], "total": 1, "limit": 100, "skip": 0, "query": []}]
            )

    def test_live_horse_results_stops_before_exceeding_page_ceiling(self):
        class FakeClient:
            calls = 0

            def request_json(self, _url):
                self.calls += 1
                return {"results": [arc_result()], "total": 2, "limit": 100, "skip": 0, "query": []}

        client = FakeClient()
        with self.assertRaisesRegex(ValueError, "page ceiling exceeded"):
            self.module.fetch_all_horse_results(client, horse_id="hrs_1024", max_pages=1)
        self.assertEqual(client.calls, 1)

    def test_same_race_id_with_different_payload_is_revision_conflict(self):
        with self.assertRaisesRegex(ValueError, "race payload conflict"):
            self.module.combine_result_pages(
                [
                    {"results": [arc_result()], "total": 2, "limit": 100, "skip": 0, "query": []},
                    {"results": [arc_result(runners=[{"horse_id": "hrs_1024", "horse": "Montjeu (IRE)", "position": "2", "number": "7"}])], "total": 2, "limit": 100, "skip": 1, "query": []},
                ]
            )

    def test_montjeu_targeted_fixture_recovers_1999_arc_all_actual_starters(self):
        target = {
            "year": 1999,
            "country_region": "france",
            "local_date": "1999-10-03",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "racecourse": "Longchamp",
            "grade_text": "G1",
            "discipline": "flat",
        }

        recovered = self.module.recover_target_race(
            target=target,
            target_horse_id="hrs_1024",
            races=[arc_result()],
        )

        self.assertEqual(recovered["race_id"], "rac_arc_1999")
        self.assertEqual(
            [runner["horse_id"] for runner in recovered["actual_starters"]],
            ["hrs_1024", "hrs_2048"],
        )
        self.assertEqual(recovered["excluded_non_runner_count"], 1)

    def test_unknown_runner_status_blocks_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, "unresolved runner status"):
            self.module.recover_target_race(
                target={
                    "year": 1999,
                    "country_region": "france",
                    "local_date": "1999-10-03",
                    "canonical_name_original": "Prix de l'Arc de Triomphe",
                    "racecourse": "Longchamp",
                    "grade_text": "G1",
                    "discipline": "flat",
                },
                target_horse_id="hrs_1024",
                races=[arc_result(runners=[{"horse_id": "hrs_1024", "horse": "Montjeu (IRE)", "position": "UNKNOWN", "number": "7"}])],
            )

    def test_endpoint_builder_is_fixed_to_allowlisted_host_and_paths(self):
        self.assertEqual(
            self.module.build_endpoint("horse_pro", horse_id="hrs_1024"),
            "https://api.theracingapi.com/v1/horses/hrs_1024/pro",
        )
        self.assertEqual(
            self.module.build_endpoint("horse_results", horse_id="hrs_1024", limit=100, skip=0),
            "https://api.theracingapi.com/v1/horses/hrs_1024/results?limit=100&skip=0",
        )
        self.assertEqual(
            self.module.build_endpoint(
                "bulk_results",
                start_date="2005-01-01",
                end_date="2005-01-01",
                region="FR",
                limit=100,
                skip=0,
            ),
            "https://api.theracingapi.com/v1/results?start_date=2005-01-01&end_date=2005-01-01&region=fr&limit=100&skip=0",
        )
        self.module.validate_endpoint_url(
            "https://api.theracingapi.com/v1/results?start_date=2005-01-01&end_date=2005-01-01&region=fr&limit=100&skip=0"
        )
        with self.assertRaisesRegex(ValueError, "bulk results query"):
            self.module.validate_endpoint_url(
                "https://api.theracingapi.com/v1/results?start_date=2005-01-01&end_date=2005-01-01&region=FR&limit=100&skip=0"
            )
        with self.assertRaisesRegex(ValueError, "invalid horse id"):
            self.module.build_endpoint("horse_pro", horse_id="https://evil.example/x")
        with self.assertRaisesRegex(ValueError, "unknown endpoint kind"):
            self.module.build_endpoint("arbitrary", horse_id="hrs_1024")
        with self.assertRaisesRegex(ValueError, "query"):
            self.module.validate_endpoint_url(
                "https://api.theracingapi.com/v1/results?start_date=2025-01-01&end_date=2025-01-01&region=FR&limit=100&skip=0&evil=1"
            )

    def test_http_client_redacts_basic_auth_and_rejects_redirect(self):
        seen = []

        def redirecting_fetcher(*, url, headers, timeout_seconds, max_body_bytes):
            seen.append(headers)
            return self.module.HttpResponse(
                status=302,
                headers={"location": "https://evil.example/steal"},
                body=b"",
                final_url=url,
            )

        client = self.module.RacingApiClient(
            username="user-secret",
            password="password-secret",
            request_ceiling=1,
            fetcher=redirecting_fetcher,
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
        )

        with self.assertRaisesRegex(self.module.RacingApiHttpError, "redirect"):
            client.request_json(self.module.build_endpoint("horse_pro", horse_id="hrs_1024"))

        self.assertIn("Authorization", seen[0])
        self.assertEqual(
            seen[0]["User-Agent"],
            self.module.CLIENT_USER_AGENT,
        )
        serialized_ledger = repr(client.request_ledger)
        self.assertNotIn("user-secret", serialized_ledger)
        self.assertNotIn("password-secret", serialized_ledger)
        self.assertNotIn(seen[0]["Authorization"], serialized_ledger)

    def test_http_401_is_not_retried_and_429_honors_retry_after(self):
        auth_calls = []

        def auth_fetcher(**kwargs):
            auth_calls.append(kwargs)
            return self.module.HttpResponse(401, {"content-type": "application/json"}, b"{}", kwargs["url"])

        auth_client = self.module.RacingApiClient(
            username="u",
            password="p",
            request_ceiling=3,
            fetcher=auth_fetcher,
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
        )
        with self.assertRaises(self.module.RacingApiAuthError):
            auth_client.request_json(self.module.build_endpoint("horse_pro", horse_id="hrs_1024"))
        self.assertEqual(len(auth_calls), 1)
        self.assertEqual(
            auth_client.request_ledger[0]["auth_failure_category"],
            "credentials_rejected",
        )

        responses = [
            self.module.HttpResponse(429, {"retry-after": "2"}, b"{}", "https://api.theracingapi.com/v1/horses/hrs_1024/pro"),
            self.module.HttpResponse(200, {"content-type": "application/json"}, b'{"id":"hrs_1024"}', "https://api.theracingapi.com/v1/horses/hrs_1024/pro"),
        ]
        sleeps = []
        retry_client = self.module.RacingApiClient(
            username="u",
            password="p",
            request_ceiling=2,
            fetcher=lambda **_kwargs: responses.pop(0),
            sleep=sleeps.append,
            monotonic=mock.Mock(side_effect=[0.0, 0.1, 0.2, 0.3]),
        )
        result = retry_client.request_json(self.module.build_endpoint("horse_pro", horse_id="hrs_1024"))

        self.assertEqual(result, {"id": "hrs_1024"})
        self.assertIn(2.0, sleeps)
        self.assertEqual(retry_client.request_count, 2)

    def test_http_403_classifies_entitlement_without_recording_response_text(self):
        url = self.module.build_endpoint("horse_search", name="Montjeu")
        response_text = "Upgrade your subscription plan to access Horse Search"
        client = self.module.RacingApiClient(
            username="user-secret",
            password="password-secret",
            request_ceiling=1,
            fetcher=lambda **_kwargs: self.module.HttpResponse(
                403,
                {"content-type": "application/json"},
                json.dumps({"detail": response_text}).encode("utf-8"),
                url,
            ),
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
        )

        with self.assertRaisesRegex(
            self.module.RacingApiAuthError,
            "endpoint_not_entitled",
        ):
            client.request_json(url)

        self.assertEqual(
            client.request_ledger[0]["auth_failure_category"],
            "endpoint_not_entitled",
        )
        self.assertNotIn(response_text, repr(client.request_ledger))

    def test_http_403_classifies_edge_client_block_without_recording_response_text(self):
        url = self.module.build_endpoint("horse_search", name="Montjeu")
        response_text = (
            "The site owner has blocked access based on your browser's signature."
        )
        client = self.module.RacingApiClient(
            username="user-secret",
            password="password-secret",
            request_ceiling=1,
            fetcher=lambda **_kwargs: self.module.HttpResponse(
                403,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "detail": response_text,
                        "error_category": "edge_security",
                    }
                ).encode("utf-8"),
                url,
            ),
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
        )

        with self.assertRaisesRegex(
            self.module.RacingApiAuthError,
            "edge_client_blocked",
        ):
            client.request_json(url)

        self.assertEqual(
            client.request_ledger[0]["auth_failure_category"],
            "edge_client_blocked",
        )
        self.assertNotIn(response_text, repr(client.request_ledger))

    def test_http_client_uses_account_budget_for_every_attempt_and_global_defer(self):
        class Reservation:
            request_number = 7
            generation = 11

        class Budget:
            def __init__(self):
                self.reservations = 0
                self.deferrals = []

            def reserve(self):
                self.reservations += 1
                return Reservation()

            def defer(self, seconds, *, reason):
                self.deferrals.append((seconds, reason))

        url = self.module.build_endpoint("horse_pro", horse_id="hrs_1024")
        responses = [
            self.module.HttpResponse(429, {"retry-after": "1.5"}, b"{}", url),
            self.module.HttpResponse(200, {"content-type": "application/json"}, b'{"id":"hrs_1024"}', url),
        ]
        budget = Budget()
        sleeps = []
        client = self.module.RacingApiClient(
            username="u",
            password="p",
            request_ceiling=2,
            fetcher=lambda **_kwargs: responses.pop(0),
            sleep=sleeps.append,
            monotonic=mock.Mock(side_effect=[0.0, 0.1, 0.2, 0.3]),
            min_interval_seconds=0,
            account_budget=budget,
        )

        self.assertEqual(client.request_json(url), {"id": "hrs_1024"})
        self.assertEqual(budget.reservations, 2)
        self.assertEqual(budget.deferrals, [(1.5, "http_429")])
        self.assertEqual(sleeps, [1.5])
        self.assertEqual(client.request_ledger[0]["account_request_number"], 7)
        self.assertEqual(client.request_ledger[0]["account_generation"], 11)

    def test_transport_failure_consumes_attempt_and_is_recorded_without_secrets(self):
        class Reservation:
            request_number = 1
            generation = 1

        class Budget:
            def reserve(self):
                return Reservation()

        url = self.module.build_endpoint("horse_pro", horse_id="hrs_1024")
        client = self.module.RacingApiClient(
            username="very-secret-user",
            password="very-secret-password",
            request_ceiling=1,
            fetcher=lambda **_kwargs: (_ for _ in ()).throw(
                self.module.RacingApiHttpError("transport unavailable")
            ),
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
            min_interval_seconds=0,
            account_budget=Budget(),
        )

        with self.assertRaisesRegex(self.module.RacingApiHttpError, "transport unavailable"):
            client.request_json(url)

        self.assertEqual(client.request_count, 1)
        self.assertEqual(client.request_ledger[0]["error"], "RacingApiHttpError")
        self.assertNotIn("very-secret", repr(client.request_ledger))

    def test_http_body_and_content_type_are_fail_closed(self):
        url = self.module.build_endpoint("horse_pro", horse_id="hrs_1024")
        html_client = self.module.RacingApiClient(
            username="u",
            password="p",
            request_ceiling=1,
            fetcher=lambda **_kwargs: self.module.HttpResponse(200, {"content-type": "text/html"}, b"<html>", url),
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
        )
        with self.assertRaisesRegex(self.module.RacingApiSchemaError, "content-type"):
            html_client.request_json(url)

        large_client = self.module.RacingApiClient(
            username="u",
            password="p",
            request_ceiling=1,
            max_body_bytes=3,
            fetcher=lambda **_kwargs: self.module.HttpResponse(200, {"content-type": "application/json"}, b"{}  ", url),
            sleep=lambda _seconds: None,
            monotonic=mock.Mock(side_effect=[0.0, 0.1]),
        )
        with self.assertRaisesRegex(self.module.RacingApiSchemaError, "body too large"):
            large_client.request_json(url)

    def test_http_json_rejects_duplicate_keys_and_non_finite_constants(self):
        url = self.module.build_endpoint("horse_pro", horse_id="hrs_1024")
        bodies = (
            b'{"id":"hrs_1024","id":"hrs_1024"}',
            b'{"id":NaN}',
        )
        for body in bodies:
            with self.subTest(body=body):
                client = self.module.RacingApiClient(
                    username="u",
                    password="p",
                    request_ceiling=1,
                    fetcher=lambda **_kwargs: self.module.HttpResponse(
                        200,
                        {"content-type": "application/json"},
                        body,
                        url,
                    ),
                    sleep=lambda _seconds: None,
                    monotonic=mock.Mock(side_effect=[0.0, 0.1]),
                )
                with self.assertRaisesRegex(
                    self.module.RacingApiSchemaError,
                    "invalid JSON response",
                ):
                    client.request_json(url)

    def test_reviewed_inputs_reject_non_finite_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fingerprint_path, _fingerprint_sha = write_openapi_fingerprint(
                self.module,
                root,
            )
            fingerprint_bytes = fingerprint_path.read_bytes().replace(
                b'"fingerprint_generated_at": ',
                b'"fingerprint_generated_at": NaN, "discarded": ',
                1,
            )
            fingerprint_path.write_bytes(fingerprint_bytes)
            fingerprint_sha = hashlib.sha256(fingerprint_bytes).hexdigest()
            with self.assertRaisesRegex(
                ValueError,
                "invalid OpenAPI fingerprint JSON",
            ):
                self.module.load_openapi_fingerprint(
                    fingerprint_path,
                    fingerprint_sha,
                )

            seed_path = root / "seed.json"
            seed_path.write_bytes(b'{"schema_version":NaN}\n')
            seed_sha = hashlib.sha256(seed_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "invalid targeted seed JSON"):
                self.module._load_seed(seed_path, seed_sha)

    def test_targeted_occurrence_runner_reuses_candidate_results_and_fetches_profile(self):
        target = {
            "year": 1999,
            "country_region": "france",
            "local_date": "1999-10-03",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "racecourse": "ParisLongchamp",
            "racecourse_aliases": ["Longchamp"],
            "grade_text": "G1",
            "discipline": "flat",
        }
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "proof-1999-arc-winner-montjeu",
            "name": "Montjeu",
            "expected_finish_position": "1",
            "source_authority": "official_operator_archived_result",
            "source_url": "https://example.test/official-result",
            "source_payload_sha256": "a" * 64,
            "target": target,
        }
        search_payload = {
            "search_results": [
                {"id": "hrs_1024", "name": "Montjeu (IRE)"},
                {"id": "hrs_9999", "name": "Montjeu (USA)"},
            ]
        }
        responses = {
            self.module.build_endpoint("horse_search", name="Montjeu"): search_payload,
            self.module.build_endpoint("horse_results", horse_id="hrs_1024", limit=100, skip=0): {
                "results": [arc_result()], "total": 1, "limit": 100, "skip": 0, "query": []
            },
            self.module.build_endpoint("horse_results", horse_id="hrs_9999", limit=100, skip=0): {
                "results": [{**arc_result(race_id="rac_other"), "date": "2001-01-01", "race_name": "Other Race"}],
                "total": 1, "limit": 100, "skip": 0, "query": []
            },
            self.module.build_endpoint("horse_pro", horse_id="hrs_1024"): montjeu_profile(),
        }

        class FakeClient:
            def __init__(self):
                self.calls = []

            def request_json(self, url, *, allow_not_found=False):
                self.calls.append((url, allow_not_found))
                return responses[url]

        client = FakeClient()
        result = self.module.run_targeted_seed(seed, client=client, max_search_candidates=5)

        self.assertEqual(result["horse_id"], "hrs_1024")
        self.assertEqual(result["profile"]["dob"], "1996-04-04")
        self.assertEqual(len(result["target_race"]["actual_starters"]), 2)
        self.assertEqual(result["career"]["provider_row_count"], 1)
        self.assertEqual(len(client.calls), 4)

    def test_reviewed_external_anchor_exports_unique_profile_when_target_is_missing(self):
        seed = {
            "schema_version": "targeted-horse-seed.v2",
            "seed_id": "sample-westover-saint-cloud",
            "name": "Westover",
            "expected_finish_position": "1",
            "allow_profile_only_if_target_missing": True,
            "source_authority": "human_reviewed_reference",
            "source_url": "https://example.test/reviewed-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 2023,
                "country_region": "france",
                "edition_year": 2023,
                "canonical_name_original": "Grand Prix de Saint-Cloud",
                "racecourse": "Saint-Cloud",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }
        unrelated = {
            **arc_result(race_id="rac_coronation_cup_2023"),
            "date": "2023-06-02",
            "region": "GB",
            "course": "Epsom",
            "course_id": "crs_epsom",
            "race_name": "Coronation Cup",
        }
        unrelated["runners"][0].update(
            {"horse_id": "hrs_26036913", "horse": "Westover (GB)"}
        )
        profile_payload = montjeu_profile(
            id="hrs_26036913",
            name="Westover (GB)",
            dob="2019-04-24",
        )
        responses = {
            self.module.build_endpoint("horse_search", name="Westover"): {
                "search_results": [{"id": "hrs_26036913", "name": "Westover (GB)"}]
            },
            self.module.build_endpoint(
                "horse_results", horse_id="hrs_26036913", limit=100, skip=0
            ): {"results": [unrelated], "total": 1, "limit": 100, "skip": 0, "query": []},
            self.module.build_endpoint("horse_pro", horse_id="hrs_26036913"): profile_payload,
        }

        class FakeClient:
            def request_json(self, url, *, allow_not_found=False):
                return responses[url]

        result = self.module.run_targeted_seed(seed, client=FakeClient())

        self.assertEqual(result["horse_id"], "hrs_26036913")
        self.assertEqual(result["identity_mode"], "external_anchor_profile_only")
        self.assertIsNone(result["target_race"])
        self.assertEqual(result["scope_target_races"], [])
        self.assertEqual(result["career_authority"]["status"], "provider_partial")
        self.assertEqual(
            result["target_occurrence"]["status"], "missing_from_provider_results"
        )
        self.assertFalse(
            result["page_field_matrix"]["completeness"]["provider_career_complete"]
        )
        self.assertEqual(
            result["page_field_matrix"]["completeness"][
                "provider_career_complete_basis"
            ],
            "target_occurrence_missing_from_provider_results",
        )

    def test_profile_only_fallback_never_resolves_multiple_exact_name_candidates(self):
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "ambiguous-reviewed-winner",
            "name": "Westover",
            "expected_finish_position": "1",
            "allow_profile_only_if_target_missing": True,
            "source_authority": "human_reviewed_reference",
            "source_url": "https://example.test/reviewed-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 2023,
                "country_region": "france",
                "local_date": "2023-07-08",
                "canonical_name_original": "Grand Prix de Saint-Cloud",
                "racecourse": "Saint-Cloud",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }
        empty_page = {"results": [], "total": 0, "limit": 100, "skip": 0, "query": []}

        class FakeClient:
            def request_json(self, url, *, allow_not_found=False):
                if "/search?" in url:
                    return {
                        "search_results": [
                            {"id": "hrs_26036913", "name": "Westover (GB)"},
                            {"id": "hrs_99999999", "name": "Westover (USA)"},
                        ]
                    }
                if "/results?" in url:
                    return empty_page
                raise AssertionError(url)

        with self.assertRaisesRegex(
            ValueError, "target occurrence candidate count must be 1, got 0"
        ):
            self.module.run_targeted_seed(seed, client=FakeClient())

    def test_profile_only_artifact_completes_with_null_provider_target_summary(self):
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "sample-westover-saint-cloud",
            "name": "Westover",
            "expected_finish_position": "1",
            "allow_profile_only_if_target_missing": True,
            "source_authority": "human_reviewed_reference",
            "source_url": "https://example.test/reviewed-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 2023,
                "country_region": "france",
                "local_date": "2023-07-08",
                "canonical_name_original": "Grand Prix de Saint-Cloud",
                "racecourse": "Saint-Cloud",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }
        profile_payload = montjeu_profile(
            id="hrs_26036913", name="Westover (GB)", dob="2019-04-24"
        )

        class FakeClient:
            request_ceiling = 16

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url, *, allow_not_found=False):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                if "/search?" in url:
                    return {
                        "search_results": [
                            {"id": "hrs_26036913", "name": "Westover (GB)"}
                        ]
                    }
                if "/results?" in url:
                    return {
                        "results": [],
                        "total": 0,
                        "limit": 100,
                        "skip": 0,
                        "query": [],
                    }
                if url.endswith("/pro"):
                    return profile_payload
                raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed_path = root / "seed.json"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            seed_sha = hashlib.sha256(seed_path.read_bytes()).hexdigest()
            fingerprint_path, fingerprint_sha = write_openapi_fingerprint(
                self.module, root
            )
            fingerprint_identity = self.module.load_openapi_fingerprint(
                fingerprint_path, fingerprint_sha
            )
            output = root / "output"

            manifest = self.module.run_targeted_seed_artifact(
                seed_path=seed_path,
                approved_seed_sha256=seed_sha,
                output_dir=output,
                client=FakeClient(),
                max_search_candidates=3,
                max_results_pages_per_horse=3,
                max_parent_profiles=0,
                openapi_fingerprint_identity=fingerprint_identity,
            )
            normalized = json.loads(
                (output / "normalized" / "targeted-horse-export.json").read_text()
            )

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["request_count"], 3)
        self.assertIsNone(manifest["result_summary"]["target_race_id"])
        self.assertEqual(manifest["result_summary"]["target_actual_starters"], 0)
        self.assertEqual(
            manifest["result_summary"]["target_occurrence_status"],
            "missing_from_provider_results",
        )
        self.assertEqual(
            manifest["result_summary"]["career_authority_status"],
            "provider_partial",
        )
        self.assertIsNone(normalized["target_race"])

    def test_profile_only_fallback_rejects_provider_profile_name_drift(self):
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "sample-westover-saint-cloud",
            "name": "Westover",
            "expected_finish_position": "1",
            "allow_profile_only_if_target_missing": True,
            "source_authority": "human_reviewed_reference",
            "source_url": "https://example.test/reviewed-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 2023,
                "country_region": "france",
                "local_date": "2023-07-08",
                "canonical_name_original": "Grand Prix de Saint-Cloud",
                "racecourse": "Saint-Cloud",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }

        class FakeClient:
            def request_json(self, url, *, allow_not_found=False):
                if "/search?" in url:
                    return {
                        "search_results": [
                            {"id": "hrs_26036913", "name": "Westover (GB)"}
                        ]
                    }
                if "/results?" in url:
                    return {
                        "results": [],
                        "total": 0,
                        "limit": 100,
                        "skip": 0,
                        "query": [],
                    }
                if url.endswith("/pro"):
                    return montjeu_profile(
                        id="hrs_26036913", name="Different Horse (GB)"
                    )
                raise AssertionError(url)

        with self.assertRaisesRegex(ValueError, "profile name drift"):
            self.module.run_targeted_seed(seed, client=FakeClient())

    def test_selected_profile_falls_back_to_standard_only_after_pro_404(self):
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "proof-standard-fallback",
            "name": "Montjeu",
            "country_suffix": "IRE",
            "expected_finish_position": "1",
            "source_authority": "official_operator_archived_result",
            "source_url": "https://example.test/official-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 1999,
                "country_region": "france",
                "local_date": "1999-10-03",
                "canonical_name_original": "Prix de l'Arc de Triomphe",
                "racecourse": "Longchamp",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }
        responses = {
            self.module.build_endpoint("horse_search", name="Montjeu"): {
                "search_results": [{"id": "hrs_1024", "name": "Montjeu (IRE)"}]
            },
            self.module.build_endpoint("horse_results", horse_id="hrs_1024", limit=100, skip=0): {
                "results": [arc_result()], "total": 1, "limit": 100, "skip": 0, "query": []
            },
            self.module.build_endpoint("horse_standard", horse_id="hrs_1024"): {
                key: value
                for key, value in montjeu_profile().items()
                if key not in {"dob", "sex", "sex_code", "colour", "colour_code", "breeder"}
            },
        }

        class FakeClient:
            def request_json(self, url, *, allow_not_found=False):
                if url.endswith("/pro") and allow_not_found:
                    return None
                return responses[url]

        result = self.module.run_targeted_seed(seed, client=FakeClient())

        self.assertEqual(result["profile"]["profile_kind"], "standard")
        self.assertEqual(result["profile"]["dob"], "")

    def test_parent_pool_fetches_sire_and_dam_with_standard_fallback(self):
        profile = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")
        sire = montjeu_profile(
            id="hrs_100",
            name="Sadler's Wells (USA)",
            dob="1981-04-11",
            sire="Northern Dancer (CAN)",
            sire_id="sir_101",
            dam="Fairy Bridge (USA)",
            dam_id="dam_102",
        )
        dam = {
            "id": "hrs_200",
            "name": "Floripedes (FR)",
            "sire": "Top Ville (IRE)",
            "sire_id": "sir_300",
            "dam": "Toute Cy (FR)",
            "dam_id": "dam_301",
            "damsire": "Tennyson (FR)",
            "damsire_id": "dsi_302",
        }
        calls = []

        class FakeClient:
            def request_json(self, url, *, allow_not_found=False):
                calls.append((url, allow_not_found))
                if "/hrs_100/pro" in url:
                    return sire
                if "/hrs_200/pro" in url:
                    return None
                if "/hrs_200/standard" in url:
                    return dam
                raise AssertionError(url)

        parents = self.module.fetch_parent_profiles(
            FakeClient(),
            profile=profile,
            max_parent_profiles=2,
        )

        self.assertEqual([row["horse_id"] for row in parents], ["hrs_100", "hrs_200"])
        self.assertEqual(parents[0]["profile_kind"], "pro")
        self.assertEqual(parents[1]["profile_kind"], "standard")
        self.assertEqual(len(calls), 3)

    def test_parent_pool_preserves_missing_pro_dob_as_explicit_gap(self):
        profile = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")
        profile["dam_id"] = ""
        parent_payload = montjeu_profile(
            id="hrs_100",
            name="Sadler's Wells (USA)",
            dob="",
            sire="Northern Dancer (CAN)",
            sire_id="sir_101",
            dam="Fairy Bridge (USA)",
            dam_id="dam_102",
        )

        class FakeClient:
            def request_json(self, url, *, allow_not_found=False):
                if not url.endswith("/horses/hrs_100/pro") or not allow_not_found:
                    raise AssertionError(url)
                return parent_payload

        parents = self.module.fetch_parent_profiles(
            FakeClient(),
            profile=profile,
            max_parent_profiles=2,
        )

        self.assertEqual(len(parents), 1)
        self.assertEqual(parents[0]["horse_id"], "hrs_100")
        self.assertEqual(parents[0]["profile_kind"], "pro")
        self.assertEqual(parents[0]["dob"], "")

        malformed = {**parent_payload, "dob": "unknown"}
        with self.assertRaisesRegex(ValueError, "invalid pro profile dob"):
            self.module.normalize_profile(
                malformed,
                profile_kind="pro",
                allow_missing_pro_dob=True,
            )

    def test_page_field_matrix_maps_two_generation_pedigree_and_career(self):
        profile = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")
        sire = self.module.normalize_profile(
            montjeu_profile(
                id="hrs_100",
                name="Sadler's Wells (USA)",
                dob="1981-04-11",
                sire="Northern Dancer (CAN)",
                sire_id="sir_101",
                dam="Fairy Bridge (USA)",
                dam_id="dam_102",
            ),
            profile_kind="pro",
        )
        dam = self.module.normalize_profile(
            {
                "id": "hrs_200",
                "name": "Floripedes (FR)",
                "sire": "Top Ville (IRE)",
                "sire_id": "sir_300",
                "dam": "Toute Cy (FR)",
                "dam_id": "dam_301",
                "damsire": "Tennyson (FR)",
                "damsire_id": "dsi_302",
            },
            profile_kind="standard",
        )
        second = arc_result(race_id="rac_lupin_1999")
        second.update(
            {
                "date": "1999-05-16",
                "race_name": "Prix Lupin",
                "pattern": "G1",
                "runners": [
                    {
                        "horse_id": "hrs_1024",
                        "horse": "Montjeu (IRE)",
                        "position": "2",
                        "trainer": "John Hammond",
                        "owner": "Michael Tabor",
                    }
                ],
            }
        )
        arc = arc_result()
        arc["runners"][0].update(
            {"trainer": "John Hammond", "owner": "Michael Tabor", "jockey": "Mick Kinane"}
        )
        career = {
            "provider_row_count": 3,
            "unique_race_count": 2,
            "page_count": 1,
            "races": [arc, second],
        }

        matrix = self.module.build_horse_page_field_matrix(
            horse_id="hrs_1024",
            profile=profile,
            parent_profiles=[sire, dam],
            career=career,
        )

        self.assertEqual(matrix["fields"]["sire_sire_text"]["value"], "Northern Dancer (CAN)")
        self.assertEqual(matrix["fields"]["sire_dam_text"]["value"], "Fairy Bridge (USA)")
        self.assertEqual(matrix["fields"]["dam_sire_text"]["value"], "Top Ville (IRE)")
        self.assertEqual(matrix["fields"]["dam_dam_text"]["value"], "Toute Cy (FR)")
        self.assertEqual(matrix["fields"]["trainer_name"]["as_of"], "1999-10-03")
        self.assertEqual(matrix["career"]["stats"], {
            "starts": 2,
            "wins": 1,
            "seconds": 1,
            "thirds": 0,
            "win_rate_percent": 50.0,
        })
        self.assertEqual(
            [row["race_id"] for row in matrix["career"]["major_wins"]],
            ["rac_arc_1999"],
        )
        arc_record = next(
            row
            for row in matrix["career"]["records"]
            if row["race_id"] == "rac_arc_1999"
        )
        self.assertEqual(arc_record["distance_meters"], 2400)
        self.assertEqual(arc_record["going_text"], "Very Soft")
        self.assertEqual(arc_record["eligibility_text"], "3yo+")
        self.assertEqual(arc_record["horse_number"], "7")
        self.assertEqual(arc_record["barrier"], "2")
        self.assertEqual(arc_record["carried_weight"], "9-0")
        self.assertTrue(matrix["completeness"]["page_profile_complete"])
        self.assertTrue(matrix["completeness"]["provider_career_complete"])

    def test_page_field_matrix_marks_damsire_conflict_and_blocks_unresolved_status(self):
        profile = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")
        conflicting_dam = self.module.normalize_profile(
            {
                "id": "hrs_200",
                "name": "Floripedes (FR)",
                "sire": "Different Sire (GB)",
                "sire_id": "sir_999",
                "dam": "Toute Cy (FR)",
                "dam_id": "dam_301",
            },
            profile_kind="standard",
        )
        matrix = self.module.build_horse_page_field_matrix(
            horse_id="hrs_1024",
            profile=profile,
            parent_profiles=[conflicting_dam],
            career={
                "provider_row_count": 1,
                "unique_race_count": 1,
                "page_count": 1,
                "races": [arc_result()],
            },
        )
        self.assertEqual(matrix["fields"]["dam_sire_text"]["status"], "conflict")
        self.assertEqual(
            matrix["fields"]["dam_sire_text"]["candidate_values"],
            ["Top Ville (IRE)", "Different Sire (GB)"],
        )
        self.assertFalse(matrix["completeness"]["page_profile_complete"])

        unresolved = arc_result(
            runners=[
                {
                    "horse_id": "hrs_1024",
                    "horse": "Montjeu (IRE)",
                    "position": "UNKNOWN",
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "unresolved runner status"):
            self.module.build_horse_page_field_matrix(
                horse_id="hrs_1024",
                profile=profile,
                parent_profiles=[],
                career={
                    "provider_row_count": 1,
                    "unique_race_count": 1,
                    "page_count": 1,
                    "races": [unresolved],
                },
            )

    def test_page_field_matrix_excludes_non_runner_from_starts(self):
        profile = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")
        non_runner = arc_result(
            runners=[
                {
                    "horse_id": "hrs_1024",
                    "horse": "Montjeu (IRE)",
                    "position": "NR",
                    "trainer": "John Hammond",
                    "owner": "Michael Tabor",
                }
            ]
        )
        matrix = self.module.build_horse_page_field_matrix(
            horse_id="hrs_1024",
            profile=profile,
            parent_profiles=[],
            career={
                "provider_row_count": 1,
                "unique_race_count": 1,
                "page_count": 1,
                "races": [non_runner],
            },
        )

        self.assertEqual(matrix["career"]["stats"]["starts"], 0)
        self.assertEqual(matrix["career"]["stats"]["win_rate_percent"], 0)
        self.assertEqual(matrix["career"]["records"][0]["participant_status"], "non_runner")

    def test_page_field_matrix_does_not_choose_between_same_day_relationships(self):
        profile = self.module.normalize_profile(montjeu_profile(), profile_kind="pro")
        first = arc_result(race_id="rac_same_day_one")
        first["runners"][0].update({"trainer": "Trainer One", "owner": "Owner One"})
        second = arc_result(race_id="rac_same_day_two")
        second["runners"][0].update({"trainer": "Trainer Two", "owner": "Owner Two"})

        matrix = self.module.build_horse_page_field_matrix(
            horse_id="hrs_1024",
            profile=profile,
            parent_profiles=[],
            career={
                "provider_row_count": 2,
                "unique_race_count": 2,
                "page_count": 1,
                "races": [first, second],
            },
        )

        self.assertEqual(matrix["fields"]["trainer_name"]["status"], "conflict")
        self.assertEqual(
            matrix["fields"]["trainer_name"]["candidate_values"],
            ["Trainer One", "Trainer Two"],
        )
        self.assertEqual(matrix["fields"]["owner_name"]["status"], "conflict")

    def test_targeted_artifact_binds_seed_and_publishes_complete_last(self):
        target = {
            "year": 1999,
            "country_region": "france",
            "local_date": "1999-10-03",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "racecourse": "Longchamp",
            "grade_text": "G1",
            "discipline": "flat",
        }
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "proof-1999-arc-winner-montjeu",
            "name": "Montjeu",
            "country_suffix": "IRE",
            "expected_finish_position": "1",
            "source_authority": "official_operator_archived_result",
            "source_url": "https://example.test/official-result",
            "source_payload_sha256": "a" * 64,
            "target": target,
        }

        class FakeClient:
            request_ceiling = 3

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url, *, allow_not_found=False):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                if "/search?" in url:
                    return {"search_results": [{"id": "hrs_1024", "name": "Montjeu (IRE)"}]}
                if url.endswith("/pro"):
                    return montjeu_profile()
                return {"results": [arc_result()], "total": 1, "limit": 100, "skip": 0, "query": []}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed_path = root / "seed.json"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            seed_sha = hashlib.sha256(seed_path.read_bytes()).hexdigest()
            fingerprint_path, fingerprint_sha = write_openapi_fingerprint(self.module, root)
            fingerprint_identity = self.module.load_openapi_fingerprint(
                fingerprint_path,
                fingerprint_sha,
            )
            output = root / "output"

            manifest = self.module.run_targeted_seed_artifact(
                seed_path=seed_path,
                approved_seed_sha256=seed_sha,
                output_dir=output,
                client=FakeClient(),
                max_search_candidates=3,
                max_parent_profiles=0,
                openapi_fingerprint_identity=fingerprint_identity,
            )

            self.assertEqual(manifest["database_writes"], 0)
            self.assertEqual(manifest["request_count"], 3)
            self.assertEqual(len(manifest["responses"]), 3)
            self.assertTrue((output / "COMPLETE").is_file())
            self.assertEqual(manifest["seed"]["sha256"], seed_sha)
            self.assertEqual(
                manifest["openapi_contract"]["fingerprint"]["sha256"],
                fingerprint_sha,
            )

    def test_targeted_artifact_publishes_redacted_failure_audit(self):
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "proof-1999-arc-winner-montjeu",
            "name": "Montjeu",
            "country_suffix": "IRE",
            "expected_finish_position": "1",
            "source_authority": "official_operator_archived_result",
            "source_url": "https://example.test/official-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 1999,
                "country_region": "france",
                "local_date": "1999-10-03",
                "canonical_name_original": "Prix de l'Arc de Triomphe",
                "racecourse": "Longchamp",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }
        self_module = self.module

        class AuthFailureClient:
            request_ceiling = 16

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url, *, allow_not_found=False):
                self.request_count += 1
                self.request_ledger.append(
                    {
                        "url": url,
                        "status": 403,
                        "response_bytes": 42,
                        "response_sha256": "b" * 64,
                        "auth_failure_category": "endpoint_not_entitled",
                    }
                )
                raise self_module.RacingApiAuthError(
                    "authentication failed with status 403 (endpoint_not_entitled)"
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed_path = root / "seed.json"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            seed_sha = hashlib.sha256(seed_path.read_bytes()).hexdigest()
            fingerprint_path, fingerprint_sha = write_openapi_fingerprint(
                self.module, root
            )
            fingerprint_identity = self.module.load_openapi_fingerprint(
                fingerprint_path,
                fingerprint_sha,
            )
            output = root / "output"

            with self.assertRaises(self.module.RacingApiAuthError):
                self.module.run_targeted_seed_artifact(
                    seed_path=seed_path,
                    approved_seed_sha256=seed_sha,
                    output_dir=output,
                    client=AuthFailureClient(),
                    max_search_candidates=3,
                    max_results_pages_per_horse=3,
                    max_parent_profiles=2,
                    openapi_fingerprint_identity=fingerprint_identity,
                )

            failure = json.loads((output / "run-failure.json").read_text())
            self.assertEqual(failure["database_writes"], 0)
            self.assertEqual(failure["request_count"], 1)
            self.assertEqual(
                failure["failure"]["category"], "endpoint_not_entitled"
            )
            self.assertTrue((output / "FAILED").is_file())
            self.assertFalse((output / "COMPLETE").exists())
            self.assertNotIn("user-secret", repr(failure))
            self.assertNotIn("password-secret", repr(failure))

    def test_targeted_artifact_failure_summarizes_empty_historical_results(self):
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "proof-1999-arc-winner-montjeu",
            "name": "Montjeu",
            "country_suffix": "IRE",
            "expected_finish_position": "1",
            "source_authority": "official_operator_archived_result",
            "source_url": "https://example.test/official-result",
            "source_payload_sha256": "a" * 64,
            "target": {
                "year": 1999,
                "country_region": "france",
                "local_date": "1999-10-03",
                "canonical_name_original": "Prix de l'Arc de Triomphe",
                "racecourse": "Longchamp",
                "grade_text": "G1",
                "discipline": "flat",
            },
        }

        class EmptyHistoricalResultsClient:
            request_ceiling = 13

            def __init__(self):
                self.request_count = 0
                self.request_ledger = []

            def request_json(self, url, *, allow_not_found=False):
                self.request_count += 1
                self.request_ledger.append(
                    {
                        "url": url,
                        "status": 200,
                        "response_bytes": 100,
                        "response_sha256": "b" * 64,
                    }
                )
                if "/horses/search?" in url:
                    return {
                        "search_results": [
                            {"id": "hrs_3521238", "name": "Montjeu (IRE)"}
                        ]
                    }
                if "/hrs_3521238/results?" in url:
                    return {
                        "results": [],
                        "total": 0,
                        "limit": 100,
                        "skip": 0,
                        "query": [],
                    }
                raise AssertionError(url)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed_path = root / "seed.json"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            seed_sha = hashlib.sha256(seed_path.read_bytes()).hexdigest()
            fingerprint_path, fingerprint_sha = write_openapi_fingerprint(
                self.module, root
            )
            fingerprint_identity = self.module.load_openapi_fingerprint(
                fingerprint_path,
                fingerprint_sha,
            )
            output = root / "output"

            with self.assertRaisesRegex(
                ValueError, "target occurrence candidate count must be 1, got 0"
            ):
                self.module.run_targeted_seed_artifact(
                    seed_path=seed_path,
                    approved_seed_sha256=seed_sha,
                    output_dir=output,
                    client=EmptyHistoricalResultsClient(),
                    max_search_candidates=3,
                    max_results_pages_per_horse=2,
                    max_parent_profiles=2,
                    openapi_fingerprint_identity=fingerprint_identity,
                )

            failure = json.loads((output / "run-failure.json").read_text())
            self.assertEqual(failure["failure"]["category"], "semantic_gap")
            self.assertEqual(
                failure["failure"]["gap_code"],
                "target_occurrence_identity_unresolved",
            )
            self.assertEqual(
                failure["failure"]["message"],
                "target occurrence candidate count must be 1, got 0",
            )
            self.assertEqual(failure["response_summaries"][0]["search_result_ids"], ["hrs_3521238"])
            self.assertEqual(
                failure["response_summaries"][1]["result_page"],
                {"returned_count": 0, "total": 0, "limit": 100, "skip": 0},
            )
            self.assertTrue(
                all("payload" not in summary for summary in failure["response_summaries"])
            )


if __name__ == "__main__":
    unittest.main()
