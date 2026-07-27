"""Phase B0.1 internal race-reference source contract tests.

These tests intentionally describe a private, post-race-only observation
pipeline.  They must never be satisfied by reusing the historical candidate
``apply`` path or by registering a Celery task.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase

from stable import models as stable_models
from stable.services.race_live_racecard_sync import normalize_identity_text


SOURCE_CASES = (
    (
        "reference_sporting_life",
        "united_kingdom",
        "sl:859381",
        "https://www.sportinglife.com/racing/results/2025-06-19/royal-ascot/859381/gold-cup-group-1",
        {"race_id": 859381},
    ),
    (
        "reference_zeturf",
        "france",
        "zt:2025-06-29:R1C5",
        "https://www.zeturf.fr/fr/course-du-jour/2025-06-29/R1C5-grand-prix-de-saint-cloud",
        {"local_date": "2025-06-29", "meeting": 1, "race": 5},
    ),
    (
        "reference_horse_racing_nation",
        "united_states",
        "hrn:churchill-downs:2025-09-27:R9",
        "https://entries.horseracingnation.com/entries-results/churchill-downs/2025-09-27",
        {
            "track_slug": "churchill-downs",
            "local_date": "2025-09-27",
            "race": 9,
        },
    ),
)


def _service():
    return importlib.import_module("stable.services.race_reference_sources")


def _safe_http():
    path = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "race_event_safe_http.py"
    spec = importlib.util.spec_from_file_location("race_event_safe_http_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    tools_path = str(path.parent)
    sys.path.insert(0, tools_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _minimal_payload(
    *,
    source_key: str = "reference_sporting_life",
    country_region: str = "united_kingdom",
    provider_event_key: str = "sl:859381",
    horse_name: str = "Reference Runner",
) -> dict:
    return {
        "schema_version": 1,
        "source_key": source_key,
        "country_region": country_region,
        "provider_event_key": provider_event_key,
        "race": {
            "source_race_name": "Reference Cup",
            "source_racecourse": "Ascot",
            "local_date": "2025-06-19",
            "source_start_time": "15:40",
        },
        "runners": [
            {
                "source_runner_key": "runner:1",
                "horse_number": "1",
                "draw": "4",
                "horse_name": horse_name,
                "jockey_name": "Reference Jockey",
                "trainer_name": "Reference Trainer",
                "carried_weight": "9-2",
                "odds_value": "5/2",
                "running_status": "declared",
                "source_reported_finish_position": "1",
                "margin": "",
            }
        ],
        "completeness": {
            "race_identity": "complete",
            "runners": "complete",
            "results": "complete",
            "gap_codes": [],
        },
    }


def _canonical_sha(value: dict) -> str:
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _make_event(**overrides) -> stable_models.RaceEvent:
    values = {
        "year": 2025,
        "slug": "reference-cup-2025",
        "original_name": "Reference Cup",
        "chinese_name": "参考杯",
        "country_region": "united_kingdom",
        "racecourse": "Ascot",
        "grade_text": "G1",
        "normalized_grade": "G1",
        "surface": "turf",
        "status": "finished",
        "priority": "P0",
        "visibility_status": "published",
        "timezone_name": "Europe/London",
        "local_date": date(2025, 6, 19),
    }
    values.update(overrides)
    return stable_models.RaceEvent.objects.create(**values)


def _manifest_for(event: stable_models.RaceEvent, *, source_case=SOURCE_CASES[0]) -> dict:
    source_key, region, provider_key, source_url, _context = source_case
    snapshot = {
        "event_id": event.pk,
        "slug": event.slug,
        "country_region": event.country_region,
        "local_date": event.local_date.isoformat(),
        "timezone_name": event.timezone_name,
        "racecourse": event.racecourse,
        "original_name": event.original_name,
        "normalized_accepted_race_names": [
            normalize_identity_text(event.original_name)
        ],
        "status": event.status,
    }
    return {
        "schema_version": 1,
        "purpose": "internal_reference_post_race",
        "source_key": source_key,
        "reference_schema_version": 1,
        "parser": {
            "name": source_key.removeprefix("reference_"),
            "version": "reference-v1",
        },
        "generated_at": "2026-07-27T00:00:00+00:00",
        "events": [
            {
                **snapshot,
                "provider_event_key": provider_key,
                "source_url": source_url,
                "event_snapshot_sha256": _canonical_sha(snapshot),
            }
        ],
    }


class RaceReferenceSemanticSchemaTests(SimpleTestCase):
    """B32-B34, B50-B51: strict semantic schema and authority downgrade."""

    def test_minimal_payload_normalizes_and_hashes_semantic_facts(self):
        service = _service()
        envelope = service.normalize_reference_payload(_minimal_payload())

        self.assertEqual(envelope["observation_key"], "reference_sporting_life:sl:859381")
        self.assertEqual(len(envelope["payload_sha256"]), 64)
        self.assertEqual(envelope["payload"]["schema_version"], 1)
        self.assertNotIn("source_url", envelope["payload"])
        self.assertEqual(
            hashlib.sha256(envelope["canonical_bytes"]).hexdigest(),
            envelope["payload_sha256"],
        )

    def test_unicode_is_normalized_before_semantic_hash(self):
        service = _service()
        composed = _minimal_payload(horse_name="Café")
        decomposed = _minimal_payload(horse_name="Cafe\u0301")

        self.assertEqual(
            service.normalize_reference_payload(composed)["payload_sha256"],
            service.normalize_reference_payload(decomposed)["payload_sha256"],
        )

    def test_provenance_does_not_change_semantic_payload_hash(self):
        service = _service()
        payload = _minimal_payload()
        first = service.normalize_reference_payload(payload)
        second = service.normalize_reference_payload(json.loads(json.dumps(payload)))
        provenance_a = {
            "source_url": SOURCE_CASES[0][3],
            "final_url": SOURCE_CASES[0][3],
            "source_observed_at": None,
            "fetched_at": "2026-07-27T00:00:00+00:00",
            "parser": {"name": "sporting_life", "version": "reference-v1"},
            "legacy_payload_sha256": "1" * 64,
            "raw_sha256": "2" * 64,
            "source_cache_ref": "raw/1.body",
        }
        provenance_b = {
            **provenance_a,
            "fetched_at": "2026-07-28T00:00:00+00:00",
            "raw_sha256": "3" * 64,
        }

        self.assertEqual(first["payload_sha256"], second["payload_sha256"])
        self.assertNotEqual(
            service.hash_reference_provenance(provenance_a),
            service.hash_reference_provenance(provenance_b),
        )

    def test_legacy_official_fields_are_downgraded_or_discarded(self):
        service = _service()
        legacy = {
            "horse_name": "Reference Runner",
            "official_finish_position": 1,
            "is_confirmed": True,
        }

        normalized = service.normalize_legacy_runner(legacy)

        self.assertEqual(normalized["source_reported_finish_position"], "1")
        self.assertNotIn("official_finish_position", normalized)
        self.assertNotIn("is_confirmed", normalized)

    def test_forbidden_authority_keys_are_rejected_at_any_depth(self):
        service = _service()
        forbidden = (
            "official",
            "is_official",
            "is_confirmed",
            "official_finish_position",
            "result_confirmed_at",
            "authority",
            "publication_status",
            "apply",
        )
        for key in forbidden:
            payload = _minimal_payload()
            payload["runners"][0]["nested"] = {key: True}
            with self.subTest(key=key), self.assertRaises(ValidationError):
                service.normalize_reference_payload(payload)

    def test_extra_fields_floats_and_schema_bounds_are_rejected(self):
        service = _service()
        invalid_payloads = []

        extra = _minimal_payload()
        extra["unexpected"] = "value"
        invalid_payloads.append(extra)

        floating = _minimal_payload()
        floating["runners"][0]["odds_value"] = 2.5
        invalid_payloads.append(floating)

        too_many_runners = _minimal_payload()
        too_many_runners["runners"] = too_many_runners["runners"] * 81
        invalid_payloads.append(too_many_runners)

        too_deep = _minimal_payload()
        nested: dict = {}
        too_deep["runners"][0]["nested"] = nested
        for _ in range(13):
            nested["value"] = {}
            nested = nested["value"]
        invalid_payloads.append(too_deep)

        too_large = _minimal_payload()
        large_runner = {
            key: ("马" * 255 if key in {"source_runner_key", "horse_name", "jockey_name", "trainer_name"} else value)
            for key, value in too_large["runners"][0].items()
        }
        large_runner["carried_weight"] = "马" * 64
        large_runner["odds_value"] = "马" * 64
        large_runner["running_status"] = "马" * 64
        large_runner["margin"] = "马" * 64
        too_large["runners"] = [
            {**large_runner, "source_runner_key": f"{index:03d}-" + large_runner["source_runner_key"][4:]}
            for index in range(80)
        ]
        invalid_payloads.append(too_large)

        for index, payload in enumerate(invalid_payloads):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                service.normalize_reference_payload(payload)

    def test_hrn_result_completeness_cannot_be_promoted_by_legacy_confirmation(self):
        service = _service()
        payload = _minimal_payload(
            source_key="reference_horse_racing_nation",
            country_region="united_states",
            provider_event_key="hrn:churchill-downs:2025-09-27:R9",
        )
        payload["completeness"]["results"] = "complete"
        legacy_metadata = {
            "result_source": "payout_table_plus_also_rans",
            "is_confirmed": True,
        }

        normalized = service.enforce_source_completeness(payload, legacy_metadata=legacy_metadata)

        self.assertEqual(normalized["completeness"]["results"], "partial")
        self.assertNotIn("is_confirmed", json.dumps(normalized))


class RaceReferenceSourceIdentityTests(SimpleTestCase):
    """B32-B34, B39-B40, B54-B55: source-specific strong identity."""

    def test_three_parse_only_modules_expose_side_effect_free_entrypoint(self):
        module_names = (
            "sporting_life",
            "zeturf",
            "horse_racing_nation",
        )
        for module_name in module_names:
            with self.subTest(module_name=module_name):
                parser = importlib.import_module(
                    f"runtime.tools.race_reference_parsers.{module_name}"
                )
                entrypoint = parser.parse_reference_page
                parameters = list(inspect.signature(entrypoint).parameters)
                self.assertEqual(
                    parameters[:3],
                    ["raw_bytes", "source_url", "parser_context"],
                )
                source = inspect.getsource(parser)
                self.assertNotIn("fetch_https(", source)
                self.assertNotIn("requests.", source)
                self.assertNotIn("RaceEvent.objects", source)
                self.assertNotIn("write_text(", source)

    def test_three_stable_parsers_expose_frozen_identity_contract(self):
        expected_names = {
            "sporting_life": "sporting_life",
            "zeturf": "zeturf",
            "horse_racing_nation": "horse_racing_nation",
        }
        for module_name, parser_name in expected_names.items():
            with self.subTest(module_name=module_name):
                parser = importlib.import_module(
                    f"stable.race_reference_parsers.{module_name}"
                )
                self.assertEqual(parser.PARSER_NAME, parser_name)
                self.assertEqual(parser.PARSER_VERSION, "reference-v1")

    def test_three_sources_require_provider_key_and_url_to_agree(self):
        service = _service()
        for source_key, region, provider_key, source_url, expected_context in SOURCE_CASES:
            with self.subTest(source_key=source_key):
                context = service.validate_source_identity(
                    source_key=source_key,
                    country_region=region,
                    provider_event_key=provider_key,
                    source_url=source_url,
                )
                self.assertEqual(context, expected_context)

    def test_hrn_reviewed_racecourse_aliases_are_exact_not_substring_guesses(self):
        service = _service()
        collect = importlib.import_module(
            "stable.management.commands.collect_internal_race_references"
        )
        accepted = (
            ("Belmont", "Belmont Park"),
            ("belmont-park", "Belmont"),
            ("Los Alamitos", "Los Alamitos Race Course"),
            ("los-alamitos", "Los Alamitos Race Course"),
        )
        for page_value, database_value in accepted:
            with self.subTest(page=page_value, database=database_value):
                self.assertTrue(
                    service.reference_racecourse_matches(
                        source_key="reference_horse_racing_nation",
                        page_value=page_value,
                        manifest_value=database_value,
                    )
                )
                match_status, confidence, _evidence = (
                    collect._classify_page_identity(
                        source_key="reference_horse_racing_nation",
                        parsed_race={
                            "source_race_name": "Reference Stakes",
                            "source_racecourse": page_value,
                            "local_date": "2025-09-27",
                        },
                        parsed_completeness={"race_identity": "complete"},
                        manifest_event={
                            "racecourse": database_value,
                            "local_date": "2025-09-27",
                            "normalized_accepted_race_names": [
                                normalize_identity_text("Reference Stakes")
                            ],
                        },
                    )
                )
                self.assertEqual((match_status, confidence), ("matched", 100))

        rejected = (
            ("Belmont at Big A", "Belmont Park"),
            ("Belmont Park West", "Belmont Park"),
            ("Los Alamitos Training Track", "Los Alamitos Race Course"),
        )
        for page_value, database_value in rejected:
            with self.subTest(page=page_value, database=database_value):
                self.assertFalse(
                    service.reference_racecourse_matches(
                        source_key="reference_horse_racing_nation",
                        page_value=page_value,
                        manifest_value=database_value,
                    )
                )

    def test_provider_key_url_mismatch_is_rejected_for_each_source(self):
        service = _service()
        mismatches = (
            (SOURCE_CASES[0], "sl:859382"),
            (SOURCE_CASES[1], "zt:2025-06-29:R1C6"),
            (
                SOURCE_CASES[2],
                "hrn:belmont-park:2025-09-28:R9",
            ),
        )
        for source_case, wrong_key in mismatches:
            source_key, region, _provider_key, source_url, _context = source_case
            with self.subTest(source_key=source_key), self.assertRaises(ValidationError):
                service.validate_source_identity(
                    source_key=source_key,
                    country_region=region,
                    provider_event_key=wrong_key,
                    source_url=source_url,
                )

    def test_wrong_region_host_path_or_scheme_is_rejected(self):
        service = _service()
        source_key, region, provider_key, source_url, _context = SOURCE_CASES[0]
        invalid = (
            {"country_region": "france"},
            {"source_url": source_url.replace("sportinglife.com", "example.com")},
            {"source_url": "https://www.sportinglife.com/racing/racecards/fixture"},
            {"source_url": source_url.replace("https://", "http://")},
        )
        for override in invalid:
            values = {
                "source_key": source_key,
                "country_region": region,
                "provider_event_key": provider_key,
                "source_url": source_url,
                **override,
            }
            with self.subTest(override=override), self.assertRaises(ValidationError):
                service.validate_source_identity(**values)

    def test_name_only_or_multiple_local_candidates_never_auto_match(self):
        service = _service()
        observation = _minimal_payload()
        candidates = [
            {
                "event_id": 1,
                "country_region": "united_kingdom",
                "local_date": "2025-06-19",
                "racecourse": "Ascot",
                "original_name": "Reference Cup",
            },
            {
                "event_id": 2,
                "country_region": "united_kingdom",
                "local_date": "2025-06-19",
                "racecourse": "Ascot",
                "original_name": "Reference Cup",
            },
        ]

        decision = service.match_reference_observation(
            observation,
            candidates=candidates,
            strong_identity_evidence=None,
            classification_version="test-v1",
        )

        self.assertIn(decision["match_status"], {"ambiguous", "unmatched"})
        self.assertIsNone(decision["event_id"])

    def test_hrn_parser_context_selects_exact_race_number(self):
        parser = importlib.import_module(
            "runtime.tools.race_reference_parsers.horse_racing_nation"
        )
        html = b"""
        <h2>Race 8</h2><table class="table-entries"></table>
        <h2>Race 9</h2><table class="table-entries"></table>
        """

        with patch.object(
            parser,
            "_parse_track_day",
            return_value=[
                {"race_no": "8", "runners": [], "results": []},
                {"race_no": "9", "runners": [], "results": []},
            ],
        ):
            parsed = parser.parse_reference_page(
                html,
                SOURCE_CASES[2][3],
                SOURCE_CASES[2][4],
            )

        self.assertEqual(parsed["provider_event_key"], SOURCE_CASES[2][2])

    def test_hrn_zero_or_duplicate_race_number_never_falls_back_to_first(self):
        parser = importlib.import_module(
            "runtime.tools.race_reference_parsers.horse_racing_nation"
        )
        for candidates in (
            [{"race_no": "8", "runners": [], "results": []}],
            [
                {"race_no": "9", "runners": [], "results": []},
                {"race_no": "9", "runners": [], "results": []},
            ],
        ):
            with self.subTest(candidates=candidates), patch.object(
                parser, "_parse_track_day", return_value=candidates
            ), self.assertRaises(RuntimeError):
                parser.parse_reference_page(
                    b"<html></html>",
                    SOURCE_CASES[2][3],
                    SOURCE_CASES[2][4],
                )

    def test_hrn_missing_race_block_never_borrows_next_race_tables(self):
        parser = importlib.import_module(
            "runtime.tools.race_reference_parsers.horse_racing_nation"
        )
        html = b"""
        <html><body>
          <h2>Race 1, 1:00 PM</h2>
          <div class="row">Churchill Downs, September 27, Empty Race One</div>
          <h2>Race 2, 1:30 PM</h2>
          <div class="row">Churchill Downs, September 27, Race Two Stakes</div>
          <table class="table-entries">
            <tr>
              <td></td>
              <td>2</td>
              <td><a href="/horse/race-two-horse">Race Two Horse</a></td>
              <td><p>Race Two Trainer</p><p>Race Two Jockey</p></td>
              <td></td>
              <td>3/1</td>
            </tr>
          </table>
          <table class="table-payouts">
            <tr><th>Runner</th><th>Win</th></tr>
            <tr><td>Race Two Horse</td><td>$8.00</td></tr>
          </table>
        </body></html>
        """
        context = {
            "track_slug": "churchill-downs",
            "local_date": "2025-09-27",
            "race": 1,
        }

        try:
            parsed = parser.parse_reference_page(
                html,
                SOURCE_CASES[2][3],
                context,
            )
        except RuntimeError:
            return

        self.assertEqual(
            parsed["runners"],
            [],
            "Race 1 must not borrow Race 2 entries/payout tables",
        )
        self.assertNotEqual(parsed["completeness"]["runners"], "complete")

    def test_zeturf_page_must_prove_the_exact_meeting_and_race_from_context(self):
        parser = importlib.import_module("runtime.tools.race_reference_parsers.zeturf")
        source_url = SOURCE_CASES[1][3]
        context = SOURCE_CASES[1][4]

        exact_html = f"""
        <html><head>
          <title>29/06/2025 - Saint-Cloud - Grand Prix de Saint-Cloud:</title>
          <link rel="canonical" href="{source_url}">
        </head><body><div data-race-code="R1C5"></div></body></html>
        """.encode()
        parsed = parser.parse_reference_page(exact_html, source_url, context)
        self.assertEqual(parsed["provider_event_key"], SOURCE_CASES[1][2])

        wrong_race_html = exact_html.replace(b"R1C5", b"R1C6")
        with self.assertRaises(RuntimeError):
            parser.parse_reference_page(wrong_race_html, source_url, context)

    def test_zeturf_np_suffix_is_removed_and_marks_runner_withdrawn(self):
        parser = importlib.import_module("runtime.tools.race_reference_parsers.zeturf")
        source_url = SOURCE_CASES[1][3]
        context = SOURCE_CASES[1][4]
        html = f"""
        <html><head>
          <title>29/06/2025 - Saint-Cloud - Grand Prix de Saint-Cloud:</title>
          <link rel="canonical" href="{source_url}">
        </head><body>
          <div data-race-code="R1C5"></div>
          <table class="table-runners"><tbody>
            <tr data-runner>
              <td class="numero">4</td>
              <td class="corde">7</td>
              <td>
                <a class="horse-name" data-runner="horse-4"
                   title="Reference Horse (NP)">Reference Horse</a>
                <span class="second-line">
                  <span class="jockey">Reference Jockey</span>
                  <span>Reference Trainer</span>
                </span>
              </td>
              <td class="weight">57</td>
              <td class="cote">12/1</td>
            </tr>
          </tbody></table>
        </body></html>
        """

        legacy_runners, legacy_results, _metadata = parser.parse_legacy_page(
            html,
            source_url=source_url,
        )
        parsed = parser.parse_reference_page(html.encode(), source_url, context)

        self.assertEqual(legacy_results, [])
        self.assertEqual(legacy_runners[0]["horse_name"], "Reference Horse")
        self.assertEqual(legacy_runners[0]["running_status"], "withdrawn")
        self.assertEqual(
            legacy_runners[0]["source_refs"]["horse_name_raw"],
            "Reference Horse (NP)",
        )
        self.assertEqual(parsed["runners"][0]["horse_name"], "Reference Horse")
        self.assertEqual(parsed["runners"][0]["running_status"], "withdrawn")

    def test_zeturf_country_then_np_suffixes_are_removed_sequentially(self):
        parser = importlib.import_module("runtime.tools.race_reference_parsers.zeturf")
        source_url = SOURCE_CASES[1][3]
        context = SOURCE_CASES[1][4]
        html = f"""
        <html><head>
          <title>29/06/2025 - Saint-Cloud - Grand Prix de Saint-Cloud:</title>
          <link rel="canonical" href="{source_url}">
        </head><body>
          <div data-race-code="R1C5"></div>
          <table class="table-runners"><tbody>
            <tr data-runner>
              <td class="numero">4</td>
              <td class="corde">7</td>
              <td>
                <a class="horse-name" data-runner="horse-4"
                   title="Reference Horse (FR) (NP)">Reference Horse</a>
              </td>
              <td class="weight">57</td>
              <td class="cote">12/1</td>
            </tr>
          </tbody></table>
          <div id="arriveeTab"><table><tbody>
            <tr data-runner>
              <td>1er</td>
              <td>4</td>
              <td>
                <a class="horse-name"
                   title="Reference Horse (FR) (NP)">Reference Horse</a>
              </td>
              <td><a class="jockey">Reference Jockey</a></td>
              <td>12/1</td>
              <td>1L</td>
            </tr>
          </tbody></table></div>
        </body></html>
        """

        legacy_runners, legacy_results, _metadata = parser.parse_legacy_page(
            html,
            source_url=source_url,
        )
        parsed = parser.parse_reference_page(html.encode(), source_url, context)

        self.assertEqual(legacy_runners[0]["horse_name"], "Reference Horse")
        self.assertEqual(legacy_results[0]["horse_name"], "Reference Horse")
        self.assertEqual(legacy_runners[0]["running_status"], "withdrawn")
        self.assertEqual(
            legacy_runners[0]["source_refs"]["horse_name_raw"],
            "Reference Horse (FR) (NP)",
        )
        self.assertEqual(parsed["runners"][0]["horse_name"], "Reference Horse")
        self.assertEqual(parsed["runners"][0]["running_status"], "withdrawn")
        self.assertEqual(
            parsed["runners"][0]["source_reported_finish_position"],
            "1",
        )

    def test_hrn_result_country_suffix_matches_entry_and_keeps_finish_position(self):
        parser = importlib.import_module(
            "runtime.tools.race_reference_parsers.horse_racing_nation"
        )
        html = b"""
        <html><body>
          <h2>Race 9, 5:30 PM</h2>
          <div class="row">Churchill Downs, September 27, Reference Stakes, Purse: $100</div>
          <table class="table-entries">
            <tr>
              <td></td>
              <td>1</td>
              <td><a href="/horse/reference-horse">Reference Horse</a></td>
              <td><p>Reference Trainer</p><p>Reference Jockey</p></td>
              <td></td>
              <td>2/1</td>
            </tr>
          </table>
          <table class="table-payouts">
            <tr><th>Runner</th><th>Win</th></tr>
            <tr><td>Reference Horse (GB)</td><td>$6.00</td></tr>
          </table>
        </body></html>
        """

        parsed = parser.parse_reference_page(
            html,
            SOURCE_CASES[2][3],
            SOURCE_CASES[2][4],
        )

        self.assertEqual(parsed["runners"][0]["horse_name"], "Reference Horse")
        self.assertEqual(
            parsed["runners"][0]["source_reported_finish_position"],
            "1",
        )

    def test_sporting_life_underscore_ride_statuses_map_to_known_statuses(self):
        parser = importlib.import_module(
            "runtime.tools.race_reference_parsers.sporting_life"
        )

        expected = {
            "pulled_up": "pulled_up",
            "non_runner": "withdrawn",
        }
        for source_status, normalized_status in expected.items():
            with self.subTest(source_status=source_status):
                self.assertEqual(
                    parser._runner_status(
                        {
                            "finish_position": None,
                            "ride_status": source_status,
                            "ride_description": "",
                        }
                    ),
                    normalized_status,
                )

    def test_sporting_life_underscore_ride_descriptions_map_to_known_statuses(self):
        parser = importlib.import_module(
            "runtime.tools.race_reference_parsers.sporting_life"
        )

        expected = {
            "pulled_up": "pulled_up",
            "non_runner": "withdrawn",
        }
        for source_description, normalized_status in expected.items():
            with self.subTest(source_description=source_description):
                self.assertEqual(
                    parser._runner_status(
                        {
                            "finish_position": None,
                            "ride_status": "",
                            "ride_description": source_description,
                        }
                    ),
                    normalized_status,
                )


class RaceReferenceHttpContractTests(SimpleTestCase):
    """B46, B48, B55-B56: bounded transport with opt-in MIME policy."""

    HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

    class _Response:
        def __init__(self, body: bytes, *, headers: list[tuple[str, str]], url: str):
            self._body = BytesIO(body)
            self.headers = SimpleNamespace(
                items=lambda: list(headers),
                get_all=lambda name: [
                    value for key, value in headers if key.casefold() == name.casefold()
                ],
            )
            self.status = 200
            self._url = url

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self):
            return self._url

        def read(self, size=-1):
            return self._body.read(size)

    def test_stable_implementation_and_runtime_wrapper_share_one_contract(self):
        repository_root = Path(__file__).resolve().parents[2]
        stable_path = repository_root / "server" / "stable" / "race_event_safe_http.py"
        runtime_path = repository_root / "runtime" / "tools" / "race_event_safe_http.py"

        self.assertTrue(
            stable_path.is_file(),
            "default ./server:/app/server bind mount must contain safe HTTP implementation",
        )
        stable_source = stable_path.read_text(encoding="utf-8")
        runtime_source = runtime_path.read_text(encoding="utf-8")
        self.assertIn("def fetch_https(", stable_source)
        self.assertNotIn(
            "def fetch_https(",
            runtime_source,
            "runtime path must be a compatibility wrapper, not a second implementation",
        )

        stable_http = importlib.import_module("stable.race_event_safe_http")
        runtime_http = importlib.import_module(
            "runtime.tools.race_event_safe_http"
        )
        self.assertIs(runtime_http.SafeHttpError, stable_http.SafeHttpError)
        self.assertIs(runtime_http.fetch_https, stable_http.fetch_https)
        self.assertIs(
            runtime_http.validate_https_url,
            stable_http.validate_https_url,
        )

    def _fetch(self, response):
        module = _safe_http()
        opener = SimpleNamespace(open=lambda _request, timeout: response)
        with patch.object(module, "build_opener", return_value=opener):
            return module.fetch_https(
                SOURCE_CASES[0][3],
                allowed_hosts=("sportinglife.com",),
                allowed_path_pattern=r"^/racing/results/",
                allowed_content_types=self.HTML_CONTENT_TYPES,
                timeout=15,
                max_bytes=4 * 1024 * 1024,
                max_redirects=2,
            )

    def test_default_transport_does_not_globally_force_html_mime(self):
        module = _safe_http()
        for content_type, body in (
            ("application/pdf", b"%PDF-reference"),
            ("application/json", b'{"ok":true}'),
            ("application/xml", b"<ok/>"),
        ):
            response = self._Response(
                body,
                headers=[("Content-Type", content_type)],
                url=SOURCE_CASES[0][3],
            )
            opener = SimpleNamespace(open=lambda _request, timeout: response)
            with self.subTest(content_type=content_type), patch.object(
                module,
                "build_opener",
                return_value=opener,
            ):
                fetched, _metadata = module.fetch_https(
                    SOURCE_CASES[0][3],
                    allowed_hosts=("sportinglife.com",),
                    timeout=15,
                )
                self.assertEqual(fetched, body)

    def test_legacy_default_transport_does_not_cap_large_binary_at_four_mib(self):
        module = _safe_http()
        body = b"%PDF-" + (b"x" * (4 * 1024 * 1024))
        response = self._Response(
            body,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(body))),
            ],
            url=SOURCE_CASES[0][3],
        )
        opener = SimpleNamespace(open=lambda _request, timeout: response)

        with patch.object(module, "build_opener", return_value=opener):
            fetched, _metadata = module.fetch_https(
                SOURCE_CASES[0][3],
                allowed_hosts=("sportinglife.com",),
                timeout=15,
            )

        self.assertEqual(fetched, body)

    def test_legacy_default_redirect_policy_allows_more_than_two_hops(self):
        module = _safe_http()
        handler = module.ValidatingRedirectHandler(("sportinglife.com",))
        request = SimpleNamespace(
            full_url=SOURCE_CASES[0][3],
            headers={},
            unverifiable=False,
            origin_req_host="www.sportinglife.com",
        )
        with patch(
            "urllib.request.HTTPRedirectHandler.redirect_request",
            return_value=request,
        ):
            for _ in range(3):
                redirected = handler.redirect_request(
                    request,
                    None,
                    302,
                    "redirect",
                    {},
                    SOURCE_CASES[0][3],
                )
                self.assertIs(redirected, request)

    def test_html_mime_and_streaming_body_within_limit_are_accepted(self):
        response = self._Response(
            b"<html>ok</html>",
            headers=[
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", "15"),
            ],
            url=SOURCE_CASES[0][3],
        )
        body, metadata = self._fetch(response)
        self.assertEqual(body, b"<html>ok</html>")
        self.assertEqual(metadata["final_url"], SOURCE_CASES[0][3])

    def test_missing_illegal_or_conflicting_mime_is_rejected_before_body_read(self):
        module = _safe_http()

        class NoReadResponse(self._Response):
            def read(self, size=-1):
                raise AssertionError("body must not be read before MIME validation")

        header_sets = (
            [],
            [("Content-Type", "application/json")],
            [
                ("Content-Type", "text/html"),
                ("Content-Type", "application/xhtml+xml"),
            ],
        )
        for headers in header_sets:
            response = NoReadResponse(b"ignored", headers=headers, url=SOURCE_CASES[0][3])
            with self.subTest(headers=headers), self.assertRaises(module.SafeHttpError):
                self._fetch(response)

    def test_content_length_and_actual_stream_both_enforce_four_mib(self):
        module = _safe_http()
        limit = 4 * 1024 * 1024
        responses = (
            self._Response(
                b"small",
                headers=[
                    ("Content-Type", "text/html"),
                    ("Content-Length", str(limit + 1)),
                ],
                url=SOURCE_CASES[0][3],
            ),
            self._Response(
                b"x" * (limit + 1),
                headers=[("Content-Type", "text/html")],
                url=SOURCE_CASES[0][3],
            ),
        )
        for response in responses:
            with self.subTest(headers=response.headers.items()), self.assertRaises(
                module.SafeHttpError
            ):
                self._fetch(response)

    def test_redirect_handler_revalidates_path_and_caps_hops(self):
        module = _safe_http()
        handler = module.ValidatingRedirectHandler(
            ("sportinglife.com",),
            allowed_path_pattern=r"^/racing/results/",
            max_redirects=2,
        )
        request = SimpleNamespace(
            full_url=SOURCE_CASES[0][3],
            headers={},
            unverifiable=False,
            origin_req_host="www.sportinglife.com",
        )
        with self.assertRaises(module.SafeHttpError):
            handler.redirect_request(
                request,
                None,
                302,
                "redirect",
                {},
                "https://www.sportinglife.com/racing/racecards/fixture",
            )

        valid = SOURCE_CASES[0][3]
        with patch("urllib.request.HTTPRedirectHandler.redirect_request", return_value=request):
            handler.redirect_request(request, None, 302, "redirect", {}, valid)
            handler.redirect_request(request, None, 302, "redirect", {}, valid)
            with self.assertRaises(module.SafeHttpError):
                handler.redirect_request(request, None, 302, "redirect", {}, valid)


class RaceReferenceModelAndIsolationTests(TestCase):
    """B35-B47, B52: private persistence and public boundary."""

    def _create_payload_only(self):
        service = _service()
        envelope = service.normalize_reference_payload(_minimal_payload())
        semantic = envelope["payload"]
        return stable_models.RaceReferencePayload.objects.create(
            source_key=semantic["source_key"],
            provider_event_key=semantic["provider_event_key"],
            observation_key=envelope["observation_key"],
            payload_sha256=envelope["payload_sha256"],
            structured_payload=semantic,
        )

    def _record_one_reference(self):
        service = _service()
        event = _make_event()
        manifest = _manifest_for(event)
        service.record_reference_collection(
            manifest=manifest,
            manifest_sha256=_canonical_sha(manifest),
            artifact={
                "artifact_sha256": "c" * 64,
                "observations": [
                    {
                        "payload": _minimal_payload(),
                        "provenance": {
                            "source_url": SOURCE_CASES[0][3],
                            "final_url": SOURCE_CASES[0][3],
                            "source_observed_at": None,
                            "fetched_at": "2026-07-27T00:00:00+00:00",
                            "parser": {
                                "name": "sporting_life",
                                "version": "reference-v1",
                            },
                            "legacy_payload_sha256": "1" * 64,
                            "raw_sha256": "2" * 64,
                            "source_cache_ref": f"raw/{event.pk}.body",
                        },
                        "event_id": event.pk,
                        "match_status": "matched",
                        "match_confidence": 100,
                        "match_evidence": {"provider_event_key": SOURCE_CASES[0][2]},
                        "classification_version": "test-v1",
                    }
                ],
            },
        )
        return (
            stable_models.RaceReferencePayload.objects.get(),
            stable_models.RaceReferenceReceipt.objects.get(),
        )

    def test_persisted_payload_instance_save_is_rejected_but_creation_is_allowed(self):
        payload = self._create_payload_only()
        self.assertIsNotNone(payload.pk)
        changed = json.loads(json.dumps(payload.structured_payload))
        changed["race"]["source_race_name"] = "Mutated Race"
        payload.structured_payload = changed

        with self.assertRaises(ValidationError):
            payload.save(update_fields={"structured_payload"})

        payload.refresh_from_db()
        self.assertEqual(
            payload.structured_payload["race"]["source_race_name"],
            "Reference Cup",
        )

    def test_persisted_payload_instance_delete_is_rejected_but_creation_is_allowed(self):
        payload = self._create_payload_only()
        payload_id = payload.pk

        with self.assertRaises(ValidationError):
            payload.delete()

        self.assertTrue(
            stable_models.RaceReferencePayload.objects.filter(pk=payload_id).exists()
        )

    def test_persisted_payload_queryset_update_is_rejected_and_unchanged(self):
        payload = self._create_payload_only()
        original_provider_key = payload.provider_event_key
        original_structured = json.loads(json.dumps(payload.structured_payload))

        with self.assertRaises(ValidationError):
            stable_models.RaceReferencePayload.objects.filter(
                pk=payload.pk
            ).update(provider_event_key="mutated-provider")

        payload.refresh_from_db()
        self.assertEqual(payload.provider_event_key, original_provider_key)
        self.assertEqual(payload.structured_payload, original_structured)

    def test_persisted_payload_bulk_update_is_rejected_and_unchanged(self):
        payload = self._create_payload_only()
        original_provider_key = payload.provider_event_key
        original_structured = json.loads(json.dumps(payload.structured_payload))
        payload.provider_event_key = "mutated-provider"

        with self.assertRaises(ValidationError):
            stable_models.RaceReferencePayload.objects.bulk_update(
                [payload],
                ["provider_event_key"],
            )

        payload.refresh_from_db()
        self.assertEqual(payload.provider_event_key, original_provider_key)
        self.assertEqual(payload.structured_payload, original_structured)

    def test_persisted_payload_queryset_delete_is_rejected_and_unchanged(self):
        payload = self._create_payload_only()
        payload_id = payload.pk
        original_structured = json.loads(json.dumps(payload.structured_payload))

        with self.assertRaises(ValidationError):
            stable_models.RaceReferencePayload.objects.filter(
                pk=payload_id
            ).delete()

        payload = stable_models.RaceReferencePayload.objects.get(pk=payload_id)
        self.assertEqual(payload.structured_payload, original_structured)

    def test_persisted_receipt_instance_save_is_rejected_but_record_creation_is_allowed(self):
        _payload, receipt = self._record_one_reference()
        self.assertIsNotNone(receipt.pk)
        receipt.match_evidence = {"mutated": True}

        with self.assertRaises(ValidationError):
            receipt.save(update_fields={"match_evidence"})

        receipt.refresh_from_db()
        self.assertEqual(
            receipt.match_evidence,
            {"provider_event_key": SOURCE_CASES[0][2]},
        )

    def test_persisted_receipt_instance_delete_is_rejected_but_record_creation_is_allowed(self):
        _payload, receipt = self._record_one_reference()
        receipt_id = receipt.pk

        with self.assertRaises(ValidationError):
            receipt.delete()

        self.assertTrue(
            stable_models.RaceReferenceReceipt.objects.filter(pk=receipt_id).exists()
        )

    def test_persisted_receipt_queryset_update_is_rejected_and_unchanged(self):
        _payload, receipt = self._record_one_reference()
        original_evidence = json.loads(json.dumps(receipt.match_evidence))
        original_snapshot = json.loads(json.dumps(receipt.event_snapshot))

        with self.assertRaises(ValidationError):
            stable_models.RaceReferenceReceipt.objects.filter(
                pk=receipt.pk
            ).update(match_evidence={"mutated": True})

        receipt.refresh_from_db()
        self.assertEqual(receipt.match_evidence, original_evidence)
        self.assertEqual(receipt.event_snapshot, original_snapshot)

    def test_persisted_receipt_bulk_update_is_rejected_and_unchanged(self):
        _payload, receipt = self._record_one_reference()
        original_evidence = json.loads(json.dumps(receipt.match_evidence))
        original_snapshot = json.loads(json.dumps(receipt.event_snapshot))
        receipt.match_evidence = {"mutated": True}

        with self.assertRaises(ValidationError):
            stable_models.RaceReferenceReceipt.objects.bulk_update(
                [receipt],
                ["match_evidence"],
            )

        receipt.refresh_from_db()
        self.assertEqual(receipt.match_evidence, original_evidence)
        self.assertEqual(receipt.event_snapshot, original_snapshot)

    def test_persisted_receipt_queryset_delete_is_rejected_and_unchanged(self):
        payload, receipt = self._record_one_reference()
        receipt_id = receipt.pk
        payload_id = payload.pk
        original_snapshot = json.loads(json.dumps(receipt.event_snapshot))

        with self.assertRaises(ValidationError):
            stable_models.RaceReferenceReceipt.objects.filter(
                pk=receipt_id
            ).delete()

        receipt = stable_models.RaceReferenceReceipt.objects.get(pk=receipt_id)
        self.assertEqual(receipt.payload_id, payload_id)
        self.assertEqual(receipt.event_snapshot, original_snapshot)

    def test_deleting_event_preserves_matched_receipt_snapshot_via_set_null(self):
        service = _service()
        _payload, receipt = self._record_one_reference()
        event = receipt.event
        self.assertIsNotNone(event)
        receipt_id = receipt.pk
        snapshot = json.loads(json.dumps(receipt.event_snapshot))
        snapshot_sha = receipt.event_snapshot_sha256
        match_status = receipt.match_status

        event.delete()

        receipt = stable_models.RaceReferenceReceipt.objects.get(pk=receipt_id)
        self.assertIsNone(receipt.event_id)
        self.assertEqual(receipt.event_snapshot, snapshot)
        self.assertEqual(receipt.event_snapshot_sha256, snapshot_sha)
        self.assertEqual(receipt.match_status, match_status)

        replacement_event = _make_event(
            slug="replacement-reference-cup-2025",
            original_name="Replacement Reference Cup",
            chinese_name="替代参考杯",
        )
        manifest = _manifest_for(replacement_event)
        with self.assertRaises(ValidationError):
            service.record_reference_collection(
                manifest=manifest,
                manifest_sha256=_canonical_sha(manifest),
                artifact={
                    "artifact_sha256": "9" * 64,
                    "observations": [
                        {
                            "payload": _minimal_payload(),
                            "provenance": {
                                "source_url": SOURCE_CASES[0][3],
                                "final_url": SOURCE_CASES[0][3],
                                "source_observed_at": None,
                                "fetched_at": "2026-07-27T00:00:00+00:00",
                                "parser": manifest["parser"],
                                "legacy_payload_sha256": "1" * 64,
                                "raw_sha256": "2" * 64,
                                "source_cache_ref": (
                                    f"raw/{replacement_event.pk}.body"
                                ),
                            },
                            "event_id": None,
                            "match_status": "matched",
                            "match_confidence": 100,
                            "match_evidence": {
                                "provider_event_key": SOURCE_CASES[0][2],
                            },
                            "classification_version": "test-v1",
                        }
                    ],
                },
            )

        self.assertEqual(
            stable_models.RaceReferenceReceipt.objects.filter(
                match_status="matched"
            ).count(),
            1,
        )

    def test_models_have_append_only_relationships_and_uniqueness(self):
        run_model = getattr(stable_models, "RaceReferenceCollectionRun", None)
        payload_model = getattr(stable_models, "RaceReferencePayload", None)
        receipt_model = getattr(stable_models, "RaceReferenceReceipt", None)
        self.assertIsNotNone(run_model, "RaceReferenceCollectionRun 尚未实现")
        self.assertIsNotNone(payload_model, "RaceReferencePayload 尚未实现")
        self.assertIsNotNone(receipt_model, "RaceReferenceReceipt 尚未实现")

        run_unique = {
            tuple(constraint.fields)
            for constraint in run_model._meta.constraints
            if getattr(constraint, "fields", None)
        }
        payload_unique = {
            tuple(constraint.fields)
            for constraint in payload_model._meta.constraints
            if getattr(constraint, "fields", None)
        }
        receipt_unique = {
            tuple(constraint.fields)
            for constraint in receipt_model._meta.constraints
            if getattr(constraint, "fields", None)
        }
        self.assertIn(("scope_manifest_sha256", "artifact_sha256"), run_unique)
        self.assertIn(
            ("source_key", "observation_key", "payload_sha256"),
            payload_unique,
        )
        self.assertIn(("run", "payload"), receipt_unique)
        self.assertEqual(receipt_model._meta.get_field("run").remote_field.on_delete.__name__, "PROTECT")
        self.assertEqual(
            receipt_model._meta.get_field("payload").remote_field.on_delete.__name__,
            "PROTECT",
        )
        self.assertEqual(
            receipt_model._meta.get_field("event").remote_field.on_delete.__name__,
            "SET_NULL",
        )

    def test_reference_admin_is_read_only_and_has_no_promotion_action(self):
        request = RequestFactory().get("/admin/")
        request.user = SimpleNamespace(has_perm=lambda _perm: True, is_active=True, is_staff=True)
        for model_name in (
            "RaceReferenceCollectionRun",
            "RaceReferencePayload",
            "RaceReferenceReceipt",
        ):
            model = getattr(stable_models, model_name)
            model_admin = admin.site._registry.get(model)
            self.assertIsNotNone(model_admin, f"{model_name} 未注册只读 admin")
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
            actions = model_admin.get_actions(request)
            self.assertFalse(
                any("promot" in name.casefold() or "apply" in name.casefold() for name in actions)
            )

    def test_recording_reference_collection_cannot_mutate_public_or_operational_tables(self):
        service = _service()
        event = _make_event()
        manifest = _manifest_for(event)
        payload = _minimal_payload()
        before = {
            "events": stable_models.RaceEvent.objects.count(),
            "runners": stable_models.RaceEventRunner.objects.count(),
            "results": stable_models.RaceEventResult.objects.count(),
            "candidates": stable_models.RaceEventDataCandidate.objects.count(),
            "revisions": stable_models.RaceEventRevision.objects.count(),
            "articles": stable_models.NewsArticle.objects.count(),
            "qq": stable_models.QQPushDelivery.objects.count(),
            "lifecycle": stable_models.RaceEventLifecycleTransition.objects.count(),
        }

        service.record_reference_collection(
            manifest=manifest,
            manifest_sha256=_canonical_sha(manifest),
            artifact={
                "artifact_sha256": "a" * 64,
                "observations": [
                    {
                        "payload": payload,
                        "provenance": {
                            "source_url": SOURCE_CASES[0][3],
                            "final_url": SOURCE_CASES[0][3],
                            "source_observed_at": None,
                            "fetched_at": "2026-07-27T00:00:00+00:00",
                            "parser": {
                                "name": "sporting_life",
                                "version": "reference-v1",
                            },
                            "legacy_payload_sha256": "1" * 64,
                            "raw_sha256": "2" * 64,
                            "source_cache_ref": f"raw/{event.pk}.body",
                        },
                        "event_id": event.pk,
                        "match_status": "matched",
                        "match_confidence": 100,
                        "match_evidence": {"provider_key": SOURCE_CASES[0][2]},
                        "classification_version": "test-v1",
                    }
                ],
            },
        )

        after = {
            "events": stable_models.RaceEvent.objects.count(),
            "runners": stable_models.RaceEventRunner.objects.count(),
            "results": stable_models.RaceEventResult.objects.count(),
            "candidates": stable_models.RaceEventDataCandidate.objects.count(),
            "revisions": stable_models.RaceEventRevision.objects.count(),
            "articles": stable_models.NewsArticle.objects.count(),
            "qq": stable_models.QQPushDelivery.objects.count(),
            "lifecycle": stable_models.RaceEventLifecycleTransition.objects.count(),
        }
        self.assertEqual(after, before)
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")

    def test_same_payload_across_runs_reuses_payload_and_adds_receipts(self):
        service = _service()
        event = _make_event()
        manifest = _manifest_for(event)
        payload = _minimal_payload()
        provenance = {
            "source_url": SOURCE_CASES[0][3],
            "final_url": SOURCE_CASES[0][3],
            "source_observed_at": None,
            "fetched_at": "2026-07-27T00:00:00+00:00",
            "parser": {"name": "sporting_life", "version": "reference-v1"},
            "legacy_payload_sha256": "1" * 64,
            "raw_sha256": "2" * 64,
            "source_cache_ref": f"raw/{event.pk}.body",
        }
        base_observation = {
            "payload": payload,
            "provenance": provenance,
            "event_id": event.pk,
            "match_status": "matched",
            "match_confidence": 100,
            "match_evidence": {"provider_key": SOURCE_CASES[0][2]},
            "classification_version": "test-v1",
        }

        for index in range(2):
            run_manifest = {**manifest, "generated_at": f"2026-07-{27 + index}T00:00:00+00:00"}
            service.record_reference_collection(
                manifest=run_manifest,
                manifest_sha256=_canonical_sha(run_manifest),
                artifact={
                    "artifact_sha256": f"{index + 1:064x}",
                    "observations": [
                        {
                            **base_observation,
                            "provenance": {
                                **provenance,
                                "fetched_at": f"2026-07-{27 + index}T00:00:00+00:00",
                                "raw_sha256": f"{index + 2:064x}",
                            },
                        }
                    ],
                },
            )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 2)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 1)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 2)

    def test_changed_semantics_append_payload_and_rematch_appends_receipt(self):
        service = _service()
        event = _make_event()
        manifest = _manifest_for(event)
        first_payload = _minimal_payload()
        second_payload = _minimal_payload(horse_name="Changed Runner")
        provenance = {
            "source_url": SOURCE_CASES[0][3],
            "final_url": SOURCE_CASES[0][3],
            "source_observed_at": None,
            "fetched_at": "2026-07-27T00:00:00+00:00",
            "parser": {"name": "sporting_life", "version": "reference-v1"},
            "legacy_payload_sha256": "1" * 64,
            "raw_sha256": "2" * 64,
            "source_cache_ref": f"raw/{event.pk}.body",
        }

        for index, (payload, match_status, event_id) in enumerate(
            (
                (first_payload, "ambiguous", None),
                (first_payload, "matched", event.pk),
                (second_payload, "matched", event.pk),
            ),
            start=1,
        ):
            run_manifest = {**manifest, "generated_at": f"2026-07-{26 + index}T00:00:00+00:00"}
            service.record_reference_collection(
                manifest=run_manifest,
                manifest_sha256=_canonical_sha(run_manifest),
                artifact={
                    "artifact_sha256": f"{index:064x}",
                    "observations": [
                        {
                            "payload": payload,
                            "provenance": {
                                **provenance,
                                "fetched_at": f"2026-07-{26 + index}T00:00:00+00:00",
                                "raw_sha256": f"{index + 3:064x}",
                            },
                            "event_id": event_id,
                            "match_status": match_status,
                            "match_confidence": 100 if event_id else 50,
                            "match_evidence": {"provider_key": SOURCE_CASES[0][2]},
                            "classification_version": f"test-v{index}",
                        }
                    ],
                },
            )

        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 2)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 3)
        first_receipt = stable_models.RaceReferenceReceipt.objects.order_by("recorded_at", "pk").first()
        self.assertEqual(first_receipt.match_status, "ambiguous")
        self.assertIsNone(first_receipt.event_id)

    def test_manifest_db_snapshot_drift_fails_whole_batch(self):
        service = _service()
        event = _make_event()
        manifest = _manifest_for(event)
        event.racecourse = "Changed Course"
        event.save(update_fields={"racecourse"})

        with self.assertRaises(ValidationError):
            service.record_reference_collection(
                manifest=manifest,
                manifest_sha256=_canonical_sha(manifest),
                artifact={"artifact_sha256": "a" * 64, "observations": []},
            )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_source_racecourse_raw_value_is_preserved_after_strong_identity_match(self):
        service = _service()
        event = _make_event(racecourse="Ascot")
        manifest = _manifest_for(event)
        payload = _minimal_payload()
        payload["race"]["source_racecourse"] = "royal-ascot"
        match_evidence = {
            "provider_event_key": SOURCE_CASES[0][2],
            "source_url": SOURCE_CASES[0][3],
            "source_racecourse": "royal-ascot",
            "manifest_racecourse": "Ascot",
            "verified_by": "provider_identity_and_manifest",
        }

        service.record_reference_collection(
            manifest=manifest,
            manifest_sha256=_canonical_sha(manifest),
            artifact={
                "artifact_sha256": "b" * 64,
                "observations": [
                    {
                        "payload": payload,
                        "provenance": {
                            "source_url": SOURCE_CASES[0][3],
                            "final_url": SOURCE_CASES[0][3],
                            "source_observed_at": None,
                            "fetched_at": "2026-07-27T00:00:00+00:00",
                            "parser": {
                                "name": "sporting_life",
                                "version": "reference-v1",
                            },
                            "legacy_payload_sha256": "1" * 64,
                            "raw_sha256": "2" * 64,
                            "source_cache_ref": f"raw/{event.pk}.body",
                        },
                        "event_id": event.pk,
                        "match_status": "matched",
                        "match_confidence": 100,
                        "match_evidence": match_evidence,
                        "classification_version": "test-v1",
                    }
                ],
            },
        )

        stored_payload = stable_models.RaceReferencePayload.objects.get()
        receipt = stable_models.RaceReferenceReceipt.objects.get()
        self.assertEqual(
            stored_payload.structured_payload["race"]["source_racecourse"],
            "royal-ascot",
        )
        self.assertEqual(receipt.match_evidence, match_evidence)
        self.assertEqual(receipt.event_id, event.pk)

    def test_matched_record_revalidates_racecourse_and_rejects_obvious_conflict(self):
        service = _service()
        event = _make_event(racecourse="Ascot")
        manifest = _manifest_for(event)
        payload = _minimal_payload()
        payload["race"]["source_racecourse"] = "Cheltenham"

        with self.assertRaises(ValidationError):
            service.record_reference_collection(
                manifest=manifest,
                manifest_sha256=_canonical_sha(manifest),
                artifact={
                    "artifact_sha256": "e" * 64,
                    "observations": [
                        {
                            "payload": payload,
                            "provenance": {
                                "source_url": SOURCE_CASES[0][3],
                                "final_url": SOURCE_CASES[0][3],
                                "source_observed_at": None,
                                "fetched_at": "2026-07-27T00:00:00+00:00",
                                "parser": {
                                    "name": "sporting_life",
                                    "version": "reference-v1",
                                },
                                "legacy_payload_sha256": "1" * 64,
                                "raw_sha256": "2" * 64,
                                "source_cache_ref": f"raw/{event.pk}.body",
                            },
                            "event_id": event.pk,
                            "match_status": "matched",
                            "match_confidence": 100,
                            "match_evidence": {
                                "provider_event_key": SOURCE_CASES[0][2],
                                "page_racecourse": "Cheltenham",
                            },
                            "classification_version": "test-v1",
                        }
                    ],
                },
            )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_wrong_region_date_or_provider_identity_still_rolls_back_whole_batch(self):
        service = _service()
        event = _make_event(racecourse="Ascot")
        manifest = _manifest_for(event)
        base_payload = _minimal_payload()
        base_observation = {
            "provenance": {
                "source_url": SOURCE_CASES[0][3],
                "final_url": SOURCE_CASES[0][3],
                "source_observed_at": None,
                "fetched_at": "2026-07-27T00:00:00+00:00",
                "parser": {
                    "name": "sporting_life",
                    "version": "reference-v1",
                },
                "legacy_payload_sha256": "1" * 64,
                "raw_sha256": "2" * 64,
                "source_cache_ref": f"raw/{event.pk}.body",
            },
            "event_id": event.pk,
            "match_status": "matched",
            "match_confidence": 100,
            "match_evidence": {"provider_event_key": SOURCE_CASES[0][2]},
            "classification_version": "test-v1",
        }
        invalid_payloads = []
        wrong_region = json.loads(json.dumps(base_payload))
        wrong_region["country_region"] = "france"
        invalid_payloads.append(wrong_region)
        wrong_date = json.loads(json.dumps(base_payload))
        wrong_date["race"]["local_date"] = "2025-06-20"
        invalid_payloads.append(wrong_date)
        wrong_provider = json.loads(json.dumps(base_payload))
        wrong_provider["provider_event_key"] = "sl:859382"
        invalid_payloads.append(wrong_provider)

        for index, payload in enumerate(invalid_payloads, start=1):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                service.record_reference_collection(
                    manifest=manifest,
                    manifest_sha256=_canonical_sha(manifest),
                    artifact={
                        "artifact_sha256": f"{index:064x}",
                        "observations": [{"payload": payload, **base_observation}],
                    },
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_source_only_observation_records_without_event_and_is_counted(self):
        service = _service()
        event = _make_event()
        manifest = _manifest_for(event)
        result = service.record_reference_collection(
            manifest=manifest,
            manifest_sha256=_canonical_sha(manifest),
            artifact={
                "artifact_sha256": "d" * 64,
                "observations": [
                    {
                        "payload": _minimal_payload(),
                        "provenance": {
                            "source_url": SOURCE_CASES[0][3],
                            "final_url": SOURCE_CASES[0][3],
                            "source_observed_at": None,
                            "fetched_at": "2026-07-27T00:00:00+00:00",
                            "parser": {
                                "name": "sporting_life",
                                "version": "reference-v1",
                            },
                            "legacy_payload_sha256": "1" * 64,
                            "raw_sha256": "2" * 64,
                            "source_cache_ref": f"raw/{event.pk}.body",
                        },
                        "event_id": None,
                        "match_status": "source_only",
                        "match_confidence": 0,
                        "match_evidence": {
                            "reason": "source_identity_valid_local_binding_withheld"
                        },
                        "classification_version": "test-v1",
                    }
                ],
            },
        )

        receipt = stable_models.RaceReferenceReceipt.objects.get()
        run = stable_models.RaceReferenceCollectionRun.objects.get()
        summary = service.build_reference_collection_summary(run)
        self.assertEqual(result["receipt_count"], 1)
        self.assertEqual(receipt.match_status, "source_only")
        self.assertIsNone(receipt.event_id)
        self.assertEqual(summary["source_only"], 1)
        self.assertEqual(summary["matched"], 0)
        self.assertEqual(summary["unmatched"], 0)
        self.assertEqual(summary["ambiguous"], 0)


class RaceReferenceCeleryIsolationTests(SimpleTestCase):
    """B47: B0.1 deliberately has no task, queue, Beat entry, or worker."""

    def test_no_reference_task_route_or_beat_registration(self):
        route_text = json.dumps(settings.CELERY_TASK_ROUTES, sort_keys=True)
        beat_text = json.dumps(
            {
                name: entry.get("task", "")
                for name, entry in settings.CELERY_BEAT_SCHEDULE.items()
            },
            sort_keys=True,
        )
        self.assertNotIn("race_reference", route_text.casefold())
        self.assertNotIn("race_reference", beat_text.casefold())

        tasks_module = importlib.import_module("stable.tasks")
        task_names = {
            name
            for name, value in vars(tasks_module).items()
            if callable(value) and "race_reference" in name.casefold()
        }
        self.assertEqual(task_names, set())

    def test_service_does_not_import_publish_live_or_candidate_apply_paths(self):
        service = _service()
        source = inspect.getsource(service)
        forbidden = (
            "apply_data_candidate",
            "save_data_candidate",
            "dispatch_task",
            "enqueue_push",
            "RaceEventRevisionPublication",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)
