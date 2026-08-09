from __future__ import annotations

import csv
import hashlib
import importlib
import json
from dataclasses import replace
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from stable.models import (
    HorseCareerHistoryStatus,
    HorseCareerRecordAuthorityStatus,
    HorseP0Source,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompletionRun,
    HorseProfileDataCandidate,
    HorseProfileModule,
    HorseRaceRecord,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "p0_horse_completion"
REGION_FIXTURES = {
    RacingRegion.JAPAN: "japan.json",
    RacingRegion.HONG_KONG: "hong_kong.json",
    RacingRegion.UNITED_KINGDOM: "united_kingdom.json",
    RacingRegion.FRANCE: "france.json",
    RacingRegion.UNITED_STATES: "united_states.json",
}
REQUIRED_PAYLOAD_FIELDS = {
    "basic_profile",
    "pedigree",
    "race_records",
    "major_wins",
    "aliases",
    "source_evidence",
    "raw_payload",
    "confidence",
    "failure_reason",
}
REVIEWED_CANDIDATE_FIELDNAMES = (
    "sample_region",
    "sample_rank",
    "candidate_key",
    "horse_name",
    "aliases",
    "identity_status",
    "review_status",
    "matched_profile_ids",
    "identity_keys",
    "source_namespace",
    "source_namespaces",
    "source_urls",
    "event_regions",
    "sire_name",
    "dam_name",
    "birth_year",
    "reviewed",
    "review_decision",
    "review_notes",
)
SOURCE_BY_REVIEW_REGION = {
    RacingRegion.JAPAN: "jra",
    RacingRegion.HONG_KONG: "hkjc",
    RacingRegion.UNITED_KINGDOM: "sporting_life",
    RacingRegion.FRANCE: "zeturf",
    RacingRegion.UNITED_STATES: "equibase",
}
WEAK_IDENTITY_REGIONS = {
    RacingRegion.JAPAN,
    RacingRegion.UNITED_STATES,
}


def _target_module():
    return importlib.import_module("stable.services.p0_horse_completion_adapters")


def _request(module, region: str, *, cache_path: Path | None = None, allow_network: bool = False):
    fixture = FIXTURE_ROOT / REGION_FIXTURES[region]
    fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
    source = fixture_payload["source"]
    identity = fixture_payload["identity"]
    return module.P0HorseCompletionRequest(
        candidate_key=f"external:{source['name']}:{source['external_horse_id']}",
        region=region,
        horse_name=identity["horse_name"],
        source_url=source["url"],
        external_horse_id=source["external_horse_id"],
        expected_sire_name=identity["sire_name"],
        expected_dam_name=identity["dam_name"],
        expected_birth_year=identity["birth_year"],
        cache_path=str(cache_path if cache_path is not None else fixture),
        allow_network=allow_network,
        request_interval_seconds=8.0,
        request_budget=2,
        batch_limit=10,
    )


def _write_source_cache(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _minimal_payload(*, candidate_key: str = "external:test:1", failure_reason=None):
    return {
        "schema_version": "p0-horse-completion.v1",
        "candidate_key": candidate_key,
        "region": RacingRegion.JAPAN,
        "horse_name": "Artifact Test Horse",
        "basic_profile": {"country": "JP", "owner_name": "Owner"},
        "pedigree": {"sire": "Sire", "dam": "Dam"},
        "race_records": [
            {
                "race_name": "Artifact Maiden",
                "race_date": "2025-01-01",
                "race_year": 2025,
                "race_date_precision": "exact",
                "racecourse": "Tokyo",
                "distance_text": "1600m",
                "result_status": "won",
                "start_status": "started",
                "event_id": None,
                "result_id": None,
                "source_name": "test_source",
                "source_url": "https://example.test/race/1",
                "source_refs": {
                    "sources": [
                        {
                            "source_name": "test_source",
                            "source_url": "https://example.test/race/1",
                        }
                    ]
                },
            }
        ],
        "major_wins": [{"race_name": "Artifact Maiden"}],
        "aliases": [{"name": "Artifact Test Horse", "language": "en", "is_original": True}],
        "source_evidence": [
            {
                "source_name": "test_source",
                "source_url": "https://example.test/horse/1",
                "external_horse_id": "1",
                "fetched_at": "2026-07-18T00:00:00Z",
            }
        ],
        "raw_payload": {"fixture": True},
        "confidence": 95,
        "failure_reason": failure_reason or [],
        "coverage": {
            "basic_profile": {"complete": True, "missing_fields": []},
            "pedigree": {"complete": True, "missing_fields": []},
            "career_history": {"complete": True, "missing_fields": []},
            "source_evidence": {"complete": True, "missing_fields": []},
        },
        "career_history": {
            "status": "complete",
            "official_or_source_start_count": 1,
            "collected_start_count": 1,
            "gap_count": 0,
            "blocker_reasons": [],
        },
        "module_diff": {
            "basic_profile": {"owner_name": {"before": "", "after": "Owner"}},
            "pedigree": {},
            "race_records": {"create": 1},
            "major_wins": {"create": 1},
        },
    }


def _reviewed_candidate_rows() -> list[dict[str, str]]:
    rows = []
    for region, source_name in SOURCE_BY_REVIEW_REGION.items():
        weak_identity = region in WEAK_IDENTITY_REGIONS
        for rank in range(1, 11):
            source_identity = f"{region}-{rank:02d}"
            candidate_key = (
                f"observation:{region}:event-{rank}:{rank}"
                if weak_identity
                else f"external:{source_name}:{source_identity}"
            )
            rows.append(
                {
                    "sample_region": region,
                    "sample_rank": str(rank),
                    "candidate_key": candidate_key,
                    "horse_name": f"{region.upper()} TEST HORSE {rank:02d}",
                    "aliases": json.dumps(
                        [f"{region.upper()} TEST HORSE {rank:02d}"],
                        ensure_ascii=False,
                    ),
                    "identity_status": (
                        "needs_identity_enrichment"
                        if weak_identity
                        else "strong_external_identity"
                    ),
                    "review_status": (
                        "needs_identity_enrichment"
                        if weak_identity
                        else "ready_for_profile_resolution"
                    ),
                    "matched_profile_ids": "[]",
                    "identity_keys": json.dumps(
                        [] if weak_identity else [f"{source_name}:{source_identity}"]
                    ),
                    "source_namespace": source_name,
                    "source_namespaces": json.dumps([source_name]),
                    "source_urls": json.dumps(
                        [f"https://example.test/{source_name}/horse/{source_identity}"]
                    ),
                    "event_regions": json.dumps([region]),
                    "sire_name": "",
                    "dam_name": "",
                    "birth_year": "",
                    "reviewed": "True",
                    "review_decision": "confirm_batch_inclusion",
                    "review_notes": "测试负责人确认纳入；身份与资料门禁仍独立生效。",
                }
            )
    return rows


def _write_reviewed_candidate_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=REVIEWED_CANDIDATE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class _FailIfCalledSourceClient:
    def __init__(self):
        self.calls = []

    def fetch(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("source client must not be called")


class _CapturingSourceClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def fetch(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.payload


class P0HorseCompletionAdapterContractTests(SimpleTestCase):
    def test_five_region_cached_fixtures_share_one_payload_contract(self):
        module = _target_module()
        self.assertTrue(set(REGION_FIXTURES) < set(module.REGION_ADAPTERS))

        key_sets = []
        for region in REGION_FIXTURES:
            with self.subTest(region=region):
                client = _FailIfCalledSourceClient()
                payload = module.run_p0_horse_completion_adapter(
                    _request(module, region),
                    source_client=client,
                )
                key_sets.append(set(payload))
                self.assertTrue(REQUIRED_PAYLOAD_FIELDS.issubset(payload))
                self.assertEqual(payload["region"], region)
                self.assertEqual(
                    payload["failure_reason"],
                    (
                        ["incomplete_career_history"]
                        if region == RacingRegion.JAPAN
                        else []
                    ),
                )
                self.assertEqual(client.calls, [])

        self.assertTrue(all(keys == key_sets[0] for keys in key_sets))

    def test_new_regions_accept_only_complete_reviewed_canonical_caches(self):
        module = _target_module()
        source_by_region = {
            RacingRegion.AUSTRALIA: ("racing_australia", "australia_racing_australia_reviewed_cache", "AU"),
            RacingRegion.GERMANY: ("deutscher_galopp", "germany_deutscher_galopp_reviewed_cache", "DE"),
            RacingRegion.MIDDLE_EAST: ("emirates_racing_authority", "middle_east_official_reviewed_cache", "AE"),
        }
        base = json.loads((FIXTURE_ROOT / "united_states.json").read_text(encoding="utf-8"))
        for region, (source_name, adapter_key, country) in source_by_region.items():
            with self.subTest(region=region), TemporaryDirectory() as temporary:
                payload = json.loads(json.dumps(base))
                payload.update({"adapter_key": adapter_key, "region": region})
                payload["source"].update({"name": source_name, "url": f"https://example.test/{source_name}/horse/1"})
                payload["basic_profile"]["country"] = country
                cache = Path(temporary) / "cache.json"
                _write_source_cache(cache, payload)
                request = module.P0HorseCompletionRequest(
                    candidate_key=f"external:{source_name}:us-001", region=region,
                    horse_name=payload["identity"]["horse_name"], source_url=payload["source"]["url"],
                    external_horse_id="us-001", expected_sire_name=payload["identity"]["sire_name"],
                    expected_dam_name=payload["identity"]["dam_name"], expected_birth_year=2020,
                    cache_path=str(cache), allow_network=False,
                )
                result = module.run_p0_horse_completion_adapter(request, source_client=_FailIfCalledSourceClient())
                self.assertEqual(result["region"], region)
                cache.unlink()
                with self.assertRaises(module.P0HorseCompletionNetworkDisabled):
                    module.run_p0_horse_completion_adapter(request, source_client=_FailIfCalledSourceClient())
                network_request = replace(request, allow_network=True)
                injected = _CapturingSourceClient(payload)
                with self.assertRaisesRegex(
                    module.P0HorseCompletionNetworkDisabled,
                    "reviewed canonical cache is required",
                ):
                    module.run_p0_horse_completion_adapter(
                        network_request,
                        source_client=injected,
                    )
                self.assertEqual(injected.calls, [])

    def test_us_cached_payload_must_match_the_expected_four_field_identity(self):
        module = _target_module()
        request = replace(
            _request(module, RacingRegion.UNITED_STATES),
            expected_birth_year=2019,
        )

        with self.assertRaisesRegex(
            module.P0HorseCompletionSourceError,
            "identity_mismatch: source payload birth_year",
        ):
            module.run_p0_horse_completion_adapter(
                request,
                source_client=_FailIfCalledSourceClient(),
            )

    def test_non_us_cache_must_bind_source_name_or_alias_to_requested_horse(self):
        module = _target_module()
        fixture = json.loads(
            (FIXTURE_ROOT / "japan.json").read_text(encoding="utf-8")
        )
        fixture["identity"]["horse_name"] = "A DIFFERENT HORSE"
        fixture["aliases"] = [
            {
                "name": "A DIFFERENT HORSE",
                "language": "en",
                "is_original": True,
            }
        ]
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "mismatched-japan.json"
            _write_source_cache(cache_path, fixture)
            request = replace(
                _request(module, RacingRegion.JAPAN, cache_path=cache_path),
                horse_name="FOREVER TEST",
                expected_sire_name="",
                expected_dam_name="",
                expected_birth_year=None,
            )

            with self.assertRaisesRegex(
                module.P0HorseCompletionSourceError,
                "identity_mismatch: source payload horse_name",
            ):
                module.run_p0_horse_completion_adapter(
                    request,
                    source_client=_FailIfCalledSourceClient(),
                )

    def test_us_cache_cannot_fill_missing_source_horse_name_from_request(self):
        module = _target_module()
        fixture = json.loads(
            (FIXTURE_ROOT / "united_states.json").read_text(encoding="utf-8")
        )
        fixture["identity"]["horse_name"] = ""
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "missing-us-name.json"
            _write_source_cache(cache_path, fixture)
            request = _request(
                module,
                RacingRegion.UNITED_STATES,
                cache_path=cache_path,
            )

            with self.assertRaisesRegex(
                module.P0HorseCompletionSourceError,
                "identity_incomplete: source payload horse_name",
            ):
                module.run_p0_horse_completion_adapter(
                    request,
                    source_client=_FailIfCalledSourceClient(),
                )

    def test_aliases_keep_original_and_multilingual_forms_without_duplicates(self):
        module = _target_module()
        payload = module.run_p0_horse_completion_adapter(
            _request(module, RacingRegion.JAPAN),
            source_client=_FailIfCalledSourceClient(),
        )

        names = [alias["name"] for alias in payload["aliases"]]
        self.assertEqual(names[0], "FOREVER TEST")
        self.assertEqual(sum(name.casefold() == "forever test" for name in names), 1)
        self.assertIn("フォーエバーテスト", names)
        self.assertIn("青春測試", names)

    def test_missing_identity_source_url_or_raw_payload_fails_closed(self):
        module = _target_module()
        valid = module.run_p0_horse_completion_adapter(
            _request(module, RacingRegion.JAPAN),
            source_client=_FailIfCalledSourceClient(),
        )
        cases = {
            "missing_identity": {
                **valid,
                "external_horse_id": "",
                "identity": {"horse_name": "", "sire_name": "", "dam_name": "", "birth_year": None},
            },
            "missing_source_url": {**valid, "source_evidence": []},
            "missing_raw_payload": {**valid, "raw_payload": {}},
        }

        for reason, payload in cases.items():
            with self.subTest(reason=reason):
                checked = module.validate_p0_horse_completion_payload(payload)
                self.assertIn(reason, checked["failure_reason"])
                self.assertLess(checked["confidence"], 80)

    def test_coverage_keeps_basic_pedigree_career_and_evidence_independent(self):
        module = _target_module()
        payload = module.run_p0_horse_completion_adapter(
            _request(module, RacingRegion.FRANCE),
            source_client=_FailIfCalledSourceClient(),
        )

        self.assertEqual(
            set(payload["coverage"]),
            {"basic_profile", "pedigree", "career_history", "source_evidence"},
        )
        self.assertTrue(all(group["complete"] for group in payload["coverage"].values()))

    def test_same_provider_external_id_conflict_is_rejected(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.FRANCE]).read_text(
                encoding="utf-8"
            )
        )
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "france.json"
            _write_source_cache(cache_path, source_payload)
            request = module.P0HorseCompletionRequest(
                candidate_key="external:geny:geny-candidate-001",
                region=RacingRegion.FRANCE,
                horse_name=source_payload["identity"]["horse_name"],
                source_url="https://example.test/geny/cheval/geny-candidate-001",
                external_horse_id="geny-candidate-001",
                cache_path=str(cache_path),
                allow_network=False,
            )

            with self.assertRaises(module.P0HorseCompletionSourceError):
                module.run_p0_horse_completion_adapter(
                    request,
                    source_client=_FailIfCalledSourceClient(),
                )

    def test_same_provider_id_conflict_is_rejected_case_insensitively(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.FRANCE]).read_text(
                encoding="utf-8"
            )
        )
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "france.json"
            _write_source_cache(cache_path, source_payload)
            request = module.P0HorseCompletionRequest(
                candidate_key="external:GENY:case-candidate-001",
                candidate_source_name="GENY",
                region=RacingRegion.FRANCE,
                horse_name=source_payload["identity"]["horse_name"],
                source_url=(
                    "https://example.test/geny/cheval/case-candidate-001"
                ),
                external_horse_id="case-candidate-001",
                cache_path=str(cache_path),
                allow_network=False,
            )

            with self.assertRaisesRegex(
                module.P0HorseCompletionSourceError,
                "external horse ID conflicts",
            ):
                module.run_p0_horse_completion_adapter(
                    request,
                    source_client=_FailIfCalledSourceClient(),
                )

    def test_cross_provider_external_ids_are_preserved_without_direct_comparison(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.FRANCE]).read_text(
                encoding="utf-8"
            )
        )
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "france.json"
            _write_source_cache(cache_path, source_payload)
            request = module.P0HorseCompletionRequest(
                candidate_key="external:zeturf:zeturf-candidate-001",
                region=RacingRegion.FRANCE,
                horse_name=source_payload["identity"]["horse_name"],
                source_url="https://example.test/zeturf/cheval/zeturf-candidate-001",
                external_horse_id="zeturf-candidate-001",
                expected_sire_name=source_payload["identity"]["sire_name"],
                expected_dam_name=source_payload["identity"]["dam_name"],
                expected_birth_year=source_payload["identity"]["birth_year"],
                cache_path=str(cache_path),
                allow_network=False,
            )

            payload = module.run_p0_horse_completion_adapter(
                request,
                source_client=_FailIfCalledSourceClient(),
            )

        self.assertEqual(payload["failure_reason"], [])
        self.assertEqual(
            set(payload["identity_keys"]),
            {"zeturf:zeturf-candidate-001", "geny:fr-001"},
        )
        self.assertEqual(
            {
                (row["source_name"], row["external_horse_id"])
                for row in payload["source_evidence"]
            },
            {
                ("zeturf", "zeturf-candidate-001"),
                ("geny", "fr-001"),
            },
        )

    def test_cross_provider_cache_cannot_match_on_horse_name_alone(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.FRANCE]).read_text(
                encoding="utf-8"
            )
        )
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "france.json"
            _write_source_cache(cache_path, source_payload)
            request = module.P0HorseCompletionRequest(
                candidate_key="external:zeturf:zeturf-candidate-name-only",
                region=RacingRegion.FRANCE,
                horse_name=source_payload["identity"]["horse_name"],
                source_url=(
                    "https://example.test/zeturf/cheval/"
                    "zeturf-candidate-name-only"
                ),
                external_horse_id="zeturf-candidate-name-only",
                cache_path=str(cache_path),
                allow_network=False,
            )

            with self.assertRaisesRegex(
                module.P0HorseCompletionSourceError,
                "identity_incomplete: expected horse_name, sire_name, dam_name",
            ):
                module.run_p0_horse_completion_adapter(
                    request,
                    source_client=_FailIfCalledSourceClient(),
                )

    def test_same_provider_without_candidate_external_id_requires_full_identity(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.FRANCE]).read_text(
                encoding="utf-8"
            )
        )
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "france.json"
            _write_source_cache(cache_path, source_payload)
            request = module.P0HorseCompletionRequest(
                candidate_key="observation:france:event-1:1",
                candidate_source_name="geny",
                region=RacingRegion.FRANCE,
                horse_name=source_payload["identity"]["horse_name"],
                source_url="https://example.test/geny/search",
                external_horse_id="",
                cache_path=str(cache_path),
                allow_network=False,
            )

            with self.assertRaisesRegex(
                module.P0HorseCompletionSourceError,
                "identity_incomplete: expected horse_name, sire_name, dam_name",
            ):
                module.run_p0_horse_completion_adapter(
                    request,
                    source_client=_FailIfCalledSourceClient(),
                )

    def test_explicit_candidate_source_cannot_conflict_with_external_key(self):
        module = _target_module()
        request = replace(
            _request(module, RacingRegion.FRANCE),
            candidate_source_name="zeturf",
        )

        with self.assertRaisesRegex(
            module.P0HorseCompletionSourceError,
            "candidate source namespace conflicts with candidate key",
        ):
            module.run_p0_horse_completion_adapter(
                request,
                source_client=_FailIfCalledSourceClient(),
            )

    def test_cross_provider_missing_target_id_never_borrows_candidate_id(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.FRANCE]).read_text(
                encoding="utf-8"
            )
        )
        source_payload["source"]["external_horse_id"] = ""

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete_cache = root / "complete.json"
            _write_source_cache(complete_cache, source_payload)
            request = module.P0HorseCompletionRequest(
                candidate_key="external:zeturf:zeturf-candidate-002",
                region=RacingRegion.FRANCE,
                horse_name=source_payload["identity"]["horse_name"],
                source_url="https://example.test/zeturf/cheval/zeturf-candidate-002",
                external_horse_id="zeturf-candidate-002",
                expected_sire_name=source_payload["identity"]["sire_name"],
                expected_dam_name=source_payload["identity"]["dam_name"],
                expected_birth_year=source_payload["identity"]["birth_year"],
                cache_path=str(complete_cache),
                allow_network=False,
            )

            complete_identity = module.run_p0_horse_completion_adapter(
                request,
                source_client=_FailIfCalledSourceClient(),
            )

            incomplete_source_payload = json.loads(json.dumps(source_payload))
            incomplete_source_payload["identity"].update(
                {"sire_name": "", "dam_name": "", "birth_year": None}
            )
            incomplete_cache = root / "incomplete.json"
            _write_source_cache(incomplete_cache, incomplete_source_payload)
            incomplete_request = module.P0HorseCompletionRequest(
                **{
                    **request.__dict__,
                    "cache_path": str(incomplete_cache),
                }
            )
            with self.assertRaisesRegex(
                module.P0HorseCompletionSourceError,
                "identity_incomplete: source payload sire_name",
            ):
                module.run_p0_horse_completion_adapter(
                    incomplete_request,
                    source_client=_FailIfCalledSourceClient(),
                )

        self.assertEqual(complete_identity["failure_reason"], [])
        self.assertEqual(
            complete_identity["identity_keys"],
            ["zeturf:zeturf-candidate-002"],
        )
        complete_evidence = {
            row["source_name"]: row["external_horse_id"]
            for row in complete_identity["source_evidence"]
        }
        self.assertEqual(complete_evidence["zeturf"], "zeturf-candidate-002")
        self.assertEqual(complete_evidence["geny"], "")

    def test_network_disabled_without_cache_rejects_before_source_client_call(self):
        module = _target_module()
        client = _FailIfCalledSourceClient()
        with TemporaryDirectory() as tmp:
            request = _request(
                module,
                RacingRegion.UNITED_STATES,
                cache_path=Path(tmp) / "missing.json",
                allow_network=False,
            )
            with self.assertRaises(module.P0HorseCompletionNetworkDisabled):
                module.run_p0_horse_completion_adapter(request, source_client=client)

        self.assertEqual(client.calls, [])

    def test_network_controls_are_forwarded_to_the_controlled_source_client(self):
        module = _target_module()
        source_payload = json.loads(
            (FIXTURE_ROOT / REGION_FIXTURES[RacingRegion.UNITED_STATES]).read_text(encoding="utf-8")
        )
        client = _CapturingSourceClient(source_payload)
        with TemporaryDirectory() as tmp:
            request = _request(
                module,
                RacingRegion.UNITED_STATES,
                cache_path=Path(tmp) / "missing.json",
                allow_network=True,
            )
            payload = module.run_p0_horse_completion_adapter(request, source_client=client)

        self.assertEqual(payload["failure_reason"], [])
        self.assertEqual(len(client.calls), 1)
        args, kwargs = client.calls[0]
        forwarded = next(
            (
                value
                for value in (*args, *kwargs.values())
                if isinstance(value, module.P0HorseCompletionRequest)
            ),
            None,
        )
        self.assertIsNotNone(forwarded)
        self.assertTrue(forwarded.allow_network)
        self.assertEqual(forwarded.request_interval_seconds, 8.0)
        self.assertEqual(forwarded.request_budget, 2)
        self.assertEqual(forwarded.batch_limit, 10)


class P0HorseCompletionCareerPayloadTests(SimpleTestCase):
    def test_explicit_nonstart_is_not_overridden_by_unknown_result(self):
        module = _target_module()

        counts = module.summarize_p0_horse_race_record_counts(
            [
                {
                    "race_name": "Entry-only race",
                    "race_date": "2017-12-09",
                    "racecourse": "Chepstow",
                    "distance_text": "2m 3f 100y",
                    "result_status": "unknown",
                    "start_status": "did_not_start",
                    "source_name": "manual_result_review",
                    "source_url": "https://example.test/result",
                }
            ]
        )

        self.assertEqual(counts["actual_start_count"], 0)
        self.assertEqual(counts["nonstarter_count"], 1)
        self.assertEqual(counts["unconfirmed_count"], 0)

    def test_source_statuses_map_without_losing_actual_start_semantics(self):
        module = _target_module()
        expected = {
            RacingRegion.JAPAN: ["won", "placed", "unplaced", "withdrawn"],
            RacingRegion.HONG_KONG: ["did_not_finish", "withdrawn"],
            RacingRegion.UNITED_KINGDOM: ["did_not_finish", "disqualified", "scratched"],
            RacingRegion.FRANCE: ["won", "did_not_finish"],
            RacingRegion.UNITED_STATES: ["unplaced", "scratched"],
        }
        for region, statuses in expected.items():
            with self.subTest(region=region):
                payload = module.run_p0_horse_completion_adapter(
                    _request(module, region),
                    source_client=_FailIfCalledSourceClient(),
                )
                self.assertEqual(
                    [record["result_status"] for record in payload["race_records"]],
                    statuses,
                )
                self.assertEqual(
                    payload["career_history"]["status"],
                    "partial" if region == RacingRegion.JAPAN else "complete",
                )
                self.assertEqual(
                    payload["career_history"]["official_or_source_start_count"],
                    payload["career_history"]["collected_start_count"],
                )

    def test_year_only_date_keeps_year_precision_without_inventing_month_or_day(self):
        module = _target_module()
        payload = module.run_p0_horse_completion_adapter(
            _request(module, RacingRegion.JAPAN),
            source_client=_FailIfCalledSourceClient(),
        )
        record = payload["race_records"][0]

        self.assertEqual(record["race_year"], 2023)
        self.assertIsNone(record["race_date"])
        self.assertEqual(record["race_date_precision"], "year")
        self.assertEqual(payload["career_history"]["status"], "partial")
        self.assertIn(
            "race_record_core_evidence_missing",
            payload["career_history"]["blocker_reasons"],
        )

    def test_overseas_duplicate_merges_once_and_preserves_both_sources(self):
        module = _target_module()
        records = [
            {
                "horse_identity_key": "profile:42",
                "race_name": "International Test Cup",
                "race_date": "2025-10-05",
                "racecourse": "Longchamp",
                "race_number": "5",
                "distance_text": "2400m",
                "finish": "2",
                "is_overseas": True,
                "source_name": "sporting_life",
                "source_url": "https://example.test/sl/international-test-cup",
                "external_race_id": "sl-100",
            },
            {
                "horse_identity_key": "profile:42",
                "race_name": "International Test Cup",
                "race_date": "2025-10-05",
                "racecourse": "Longchamp",
                "race_number": "5",
                "distance_text": "1m4f",
                "finish": "2",
                "is_overseas": True,
                "source_name": "france_galop",
                "source_url": "https://example.test/fg/international-test-cup",
                "external_race_id": "fg-900",
            },
        ]

        normalized = module.normalize_p0_horse_race_records(records, source_start_count=1)

        self.assertEqual(len(normalized["race_records"]), 1)
        sources = normalized["race_records"][0]["source_refs"]["sources"]
        self.assertEqual({source["source_name"] for source in sources}, {"sporting_life", "france_galop"})
        self.assertEqual(normalized["career_history"]["deduplicated_source_record_count"], 1)
        self.assertEqual(normalized["career_history"]["overseas_start_count"], 1)

    def test_formal_result_overrides_unknown_when_strong_race_key_matches(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": "profile:42",
                    "race_name": "Identity Stakes",
                    "race_date": "2025-10-05",
                    "racecourse": "Longchamp",
                    "race_number": "5",
                    "distance_text": "2400m",
                    "finish": "N/A",
                    "result_status": "unknown",
                    "source_name": "secondary",
                    "source_url": "https://example.test/secondary/identity-stakes",
                    "field_evidence": [
                        {
                            "field_name": "result",
                            "direct_raw": {
                                "value": "N/A",
                                "status": "observed",
                                "source_name": "secondary",
                                "source_url": (
                                    "https://example.test/secondary/"
                                    "identity-stakes"
                                ),
                            },
                            "canonical_raw": {
                                "value": None,
                                "status": "not_collected",
                            },
                            "normalized": {
                                "value": "unknown",
                                "status": "blocked",
                            },
                        }
                    ],
                },
                {
                    "horse_identity_key": "profile:42",
                    "race_name": "Identity Stakes",
                    "race_date": "2025-10-05",
                    "racecourse": "Longchamp",
                    "race_number": "5",
                    "distance_text": "2400m",
                    "finish": "3",
                    "result_status": "placed",
                    "source_name": "official",
                    "source_url": "https://example.test/official/identity-stakes",
                    "field_evidence": [
                        {
                            "field_name": "result",
                            "direct_raw": {
                                "value": "3",
                                "status": "observed",
                                "source_name": "official",
                            },
                            "canonical_raw": {
                                "value": "3",
                                "status": "observed",
                                "source_name": "official",
                                "source_url": (
                                    "https://example.test/official/"
                                    "identity-stakes"
                                ),
                            },
                            "normalized": {
                                "value": "placed",
                                "status": "mapped",
                                "source_name": "umanews",
                                "conversion_rule": "official_finish_position_v1",
                            },
                        }
                    ],
                },
            ],
            source_start_count=1,
            official_start_count_source="official",
            official_start_count_source_url=(
                "https://example.test/official/identity-stakes"
            ),
            official_start_count_verified_at="2026-07-19T00:00:00+00:00",
            record_authority_status="source_records_verified",
        )

        self.assertEqual(len(normalized["race_records"]), 1)
        record = normalized["race_records"][0]
        self.assertEqual(record["result_status"], "placed")
        self.assertEqual(record["finish_position"], "3")
        self.assertEqual(record["start_status"], "started")
        result_evidence = next(
            item
            for item in record["field_evidence"]
            if item["field_name"] == "result"
        )
        self.assertEqual(result_evidence["direct_raw"]["value"], "N/A")
        self.assertEqual(result_evidence["canonical_raw"]["value"], "3")
        self.assertEqual(
            result_evidence["canonical_raw"]["source_name"],
            "official",
        )
        self.assertEqual(result_evidence["normalized"]["value"], "placed")
        self.assertEqual(result_evidence["normalized"]["status"], "mapped")
        self.assertEqual(
            {source["source_name"] for source in record["source_refs"]["sources"]},
            {"secondary", "official"},
        )
        self.assertEqual(normalized["career_history"]["collected_start_count"], 1)
        self.assertEqual(normalized["career_history"]["gap_count"], 0)

    def test_count_only_official_verification_keeps_zero_gap_but_blocks_complete_status(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": "equibase:11138947",
                    "race_date": "2025-08-31",
                    "race_name": "Del Mar Futurity",
                    "racecourse": "Del Mar",
                    "distance_text": "7f",
                    "finish": "5",
                    "source_name": "hrn",
                    "source_url": "https://www.horseracingnation.com/horse/Bullard",
                }
            ],
            source_start_count=1,
            official_start_count_source="equibase",
            official_start_count_source_url=(
                "https://www.equibase.com/profiles/Results.cfm"
                "?type=Horse&refno=11138947&registry=T"
            ),
            official_start_count_verified_at="2026-07-19T00:00:00+00:00",
            record_authority_status="count_aligned_records_unverified",
        )

        history = normalized["career_history"]
        self.assertEqual(history["official_or_source_start_count"], 1)
        self.assertEqual(history["collected_start_count"], 1)
        self.assertEqual(history["gap_count"], 0)
        self.assertEqual(history["status"], "partial")
        self.assertEqual(history["official_start_count_source"], "equibase")
        self.assertEqual(
            history["record_authority_status"],
            "count_aligned_records_unverified",
        )
        self.assertIn(
            "official_count_aligned_per_record_authority_pending:equibase",
            history["blocker_reasons"],
        )

    def test_source_total_without_provenance_cannot_complete_career(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": "profile:42",
                    "race_date": "2025-08-31",
                    "race_name": "Evidence Stakes",
                    "racecourse": "Test Course",
                    "distance_text": "1600m",
                    "finish": "1",
                    "source_name": "official",
                    "source_url": "https://example.test/race/evidence-stakes",
                }
            ],
            source_start_count=1,
            record_authority_status="source_records_verified",
        )

        history = normalized["career_history"]
        self.assertEqual(history["status"], "partial")
        self.assertEqual(history["gap_count"], 0)
        self.assertCountEqual(
            history["blocker_reasons"],
            [
                "official_start_count_source_missing",
                "official_start_count_source_url_missing",
                "official_start_count_verified_at_missing",
            ],
        )

    def test_unknown_or_invalid_record_authority_cannot_complete(self):
        module = _target_module()
        records = [
            {
                "horse_identity_key": "profile:42",
                "race_date": "2025-08-31",
                "race_name": "Authority Test",
                "racecourse": "Tokyo",
                "distance_text": "1600m",
                "finish": "1",
                "source_name": "jbis",
                "source_url": "https://example.test/jbis/authority-test",
            }
        ]

        unknown = module.normalize_p0_horse_race_records(
            records,
            source_start_count=1,
        )

        self.assertEqual(unknown["career_history"]["status"], "partial")
        self.assertIn(
            "per_record_authority_unknown",
            unknown["career_history"]["blocker_reasons"],
        )
        with self.assertRaisesRegex(
            module.P0HorseCompletionSourceError,
            "record authority status",
        ):
            module.normalize_p0_horse_race_records(
                records,
                source_start_count=1,
                record_authority_status="source_records_verfied",
            )

    def test_record_count_summary_excludes_nonstarters_and_counts_abnormal_overseas(self):
        module = _target_module()
        counts = module.summarize_p0_horse_race_record_counts(
            [
                {"finish": "1"},
                {"finish": "WV"},
                {
                    "result_status": "did_not_finish",
                    "is_overseas": True,
                },
                {"result_status": "unknown"},
            ]
        )

        self.assertEqual(
            counts,
            {
                "actual_start_count": 2,
                "nonstarter_count": 1,
                "unconfirmed_count": 1,
                "abnormal_official_status_count": 1,
                "overseas_start_count": 1,
            },
        )

    def test_year_only_weak_evidence_does_not_cross_source_merge(self):
        module = _target_module()
        records = [
            {
                "horse_identity_key": "profile:42",
                "race_name": "Annual Test",
                "race_date": "2024",
                "racecourse": "",
                "race_number": "",
                "distance_text": "",
                "finish": "4",
                "source_name": source,
                "source_url": f"https://example.test/{source}/annual-test",
            }
            for source in ("source_a", "source_b")
        ]

        normalized = module.normalize_p0_horse_race_records(records, source_start_count=2)

        self.assertEqual(len(normalized["race_records"]), 2)
        self.assertEqual(normalized["career_history"]["deduplicated_source_record_count"], 0)

    def test_unlinked_ordinary_races_stay_unlinked_and_count_mismatch_blocks_completion(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": "profile:42",
                    "race_name": "Ordinary Allowance",
                    "race_date": "2025-02-01",
                    "racecourse": "Tokyo",
                    "race_number": "7",
                    "distance_text": "1600m",
                    "finish": "3",
                    "source_name": "jbis",
                    "source_url": "https://example.test/jbis/ordinary-allowance",
                }
            ],
            source_start_count=2,
        )

        record = normalized["race_records"][0]
        self.assertIsNone(record["event_id"])
        self.assertIsNone(record["result_id"])
        self.assertEqual(normalized["career_history"]["status"], "partial")
        self.assertEqual(normalized["career_history"]["gap_count"], 1)
        self.assertIn("source_start_count_mismatch", normalized["career_history"]["blocker_reasons"])

    def test_excess_actual_starts_are_a_nonzero_count_mismatch(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": "profile:42",
                    "race_name": f"Duplicate Guard {day}",
                    "race_date": f"2025-02-0{day}",
                    "racecourse": "Tokyo",
                    "race_number": str(day),
                    "distance_text": "1600m",
                    "finish": "4",
                    "source_name": "jbis",
                    "source_url": f"https://example.test/jbis/duplicate-guard/{day}",
                }
                for day in (1, 2)
            ],
            source_start_count=1,
        )

        history = normalized["career_history"]
        self.assertEqual(history["collected_start_count"], 2)
        self.assertEqual(history["gap_count"], 1)
        self.assertEqual(history["missing_start_count"], 0)
        self.assertEqual(history["excess_start_count"], 1)
        self.assertEqual(history["start_count_delta"], 1)
        self.assertEqual(history["status"], "partial")
        self.assertIn(
            "source_start_count_exceeded:1",
            history["blocker_reasons"],
        )


class P0HorseCompletionArtifactTests(TestCase):
    def test_artifact_writer_outputs_hash_bound_review_material_without_database_writes(self):
        module = _target_module()
        payloads = [
            _minimal_payload(),
            _minimal_payload(
                candidate_key="external:test:2",
                failure_reason=["ambiguous_match"],
            ),
        ]
        models = (HorseProfile, HorseP0Source, HorseProfileDataCandidate, HorseRaceRecord)
        before = {model: model.objects.count() for model in models}

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "artifact"
            manifest = module.write_p0_horse_completion_artifacts(
                payloads,
                output,
                reviewed_input_sha256="a" * 64,
                generated_at="2026-07-18T00:00:00Z",
            )
            expected_files = {
                "p0_horse_completion_candidates.jsonl",
                "p0_horse_completion_review.csv",
                "p0_horse_completion_failures_and_conflicts.jsonl",
                "p0_horse_completion_module_diff.jsonl",
                "source_evidence_manifest.json",
                "summary.json",
            }
            self.assertEqual(set(manifest["files"]), expected_files)
            self.assertEqual(manifest["reviewed_input_sha256"], "a" * 64)
            for filename in expected_files:
                path = output / filename
                self.assertTrue(path.is_file())
                self.assertEqual(
                    manifest["files"][filename]["sha256"],
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            review_rows = list(
                csv.DictReader(
                    (output / "p0_horse_completion_review.csv").open(
                        encoding="utf-8",
                        newline="",
                    )
                )
            )
            self.assertEqual(len(review_rows), 2)
            self.assertTrue(
                {
                    "basic_profile_decision",
                    "pedigree_decision",
                    "race_records_decision",
                    "major_wins_decision",
                    "reviewer_id",
                    "reviewed_at",
                }.issubset(review_rows[0])
            )
            evidence = json.loads((output / "source_evidence_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("https://example.test/horse/1", json.dumps(evidence))

        after = {model: model.objects.count() for model in models}
        self.assertEqual(after, before)

    def test_same_input_has_stable_file_hashes_and_nonempty_target_is_rejected(self):
        module = _target_module()
        payloads = [_minimal_payload()]
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            first_manifest = module.write_p0_horse_completion_artifacts(
                payloads,
                first,
                reviewed_input_sha256="b" * 64,
                generated_at="2026-07-18T00:00:00Z",
            )
            second_manifest = module.write_p0_horse_completion_artifacts(
                payloads,
                second,
                reviewed_input_sha256="b" * 64,
                generated_at="2026-07-18T00:00:00Z",
            )
            first_hashes = {name: item["sha256"] for name, item in first_manifest["files"].items()}
            second_hashes = {name: item["sha256"] for name, item in second_manifest["files"].items()}
            self.assertEqual(first_hashes, second_hashes)

            with self.assertRaisesMessage(ValueError, "not empty"):
                module.write_p0_horse_completion_artifacts(
                    payloads,
                    first,
                    reviewed_input_sha256="b" * 64,
                    generated_at="2026-07-18T00:00:00Z",
                )


class P0HorseReviewedCandidateBatchTests(TestCase):
    def test_reviewed_candidate_loader_parses_the_captured_hashed_snapshot(self):
        module = _target_module()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviewed.csv"
            _write_reviewed_candidate_csv(
                path,
                _reviewed_candidate_rows(),
            )
            captured_bytes = path.read_bytes()
            path.write_text("tampered after hash\n", encoding="utf-8")

            loaded = module.load_reviewed_p0_horse_candidates(
                path,
                captured_bytes=captured_bytes,
            )

        self.assertEqual(len(loaded), 50)

    def test_reviewed_candidate_csv_requires_exact_five_by_ten_unique_confirmed_rows(self):
        module = _target_module()
        valid_rows = _reviewed_candidate_rows()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_path = root / "valid.csv"
            _write_reviewed_candidate_csv(valid_path, valid_rows)

            loaded = module.load_reviewed_p0_horse_candidates(valid_path)

            self.assertEqual(len(loaded), 50)
            self.assertEqual(
                {
                    region: sum(row["sample_region"] == region for row in loaded)
                    for region in SOURCE_BY_REVIEW_REGION
                },
                {region: 10 for region in SOURCE_BY_REVIEW_REGION},
            )
            self.assertEqual(
                len({row["candidate_key"] for row in loaded}),
                50,
            )
            self.assertTrue(all(row["reviewed"] is True for row in loaded))
            self.assertTrue(
                all(
                    row["review_decision"] == "confirm_batch_inclusion"
                    for row in loaded
                )
            )

            invalid_batches = {
                "region_count": valid_rows[:-1],
                "duplicate_candidate_key": [
                    {
                        **row,
                        "candidate_key": (
                            valid_rows[0]["candidate_key"]
                            if index == 1
                            else row["candidate_key"]
                        ),
                    }
                    for index, row in enumerate(valid_rows)
                ],
                "not_reviewed": [
                    {**row, "reviewed": "False"} if index == 0 else row
                    for index, row in enumerate(valid_rows)
                ],
                "wrong_decision": [
                    {**row, "review_decision": "identity_enrichment_required"}
                    if index == 0
                    else row
                    for index, row in enumerate(valid_rows)
                ],
            }
            for label, rows in invalid_batches.items():
                with self.subTest(label=label):
                    invalid_path = root / f"{label}.csv"
                    _write_reviewed_candidate_csv(invalid_path, rows)
                    with self.assertRaises(module.P0HorseCompletionBatchError):
                        module.load_reviewed_p0_horse_candidates(invalid_path)

    def test_cache_path_is_a_stable_safe_hash_of_candidate_key(self):
        module = _target_module()
        candidate_key = "external:equibase:horse/with unsafe path"
        with TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            first = module.p0_horse_completion_cache_path(
                cache_root,
                candidate_key,
            )
            second = module.p0_horse_completion_cache_path(
                cache_root,
                candidate_key,
            )
            other = module.p0_horse_completion_cache_path(
                cache_root,
                f"{candidate_key}:other",
            )

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(first.parent, cache_root)
        self.assertEqual(
            first.name,
            f"{hashlib.sha256(candidate_key.encode('utf-8')).hexdigest()}.json",
        )

    def test_network_disabled_cache_misses_become_per_horse_blockers_and_batch_continues(self):
        module = _target_module()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(reviewed_csv, _reviewed_candidate_rows())

            module.run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=reviewed_csv,
                cache_dir=root / "empty-cache",
                output_dir=output_dir,
                allow_network=False,
                generated_at="2026-07-18T00:00:00Z",
            )

            payloads = [
                json.loads(line)
                for line in (
                    output_dir / "p0_horse_completion_candidates.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(payloads), 50)
        self.assertTrue(
            all(
                "network_disabled_cache_missing" in row["failure_reason"]
                for row in payloads
            )
        )
        weak_identity_rows = [
            row
            for row in payloads
            if row["region"] in WEAK_IDENTITY_REGIONS
        ]
        self.assertEqual(len(weak_identity_rows), 20)
        self.assertTrue(
            all(
                "identity_enrichment_required" in row["failure_reason"]
                for row in weak_identity_rows
            )
        )
        self.assertTrue(
            all(
                row.get("retrieval", {}).get("network_request_count") == 0
                for row in payloads
            )
        )

    def test_fifty_row_dry_run_persists_overall_manifest_without_database_writes(self):
        module = _target_module()
        models = (
            HorseProfile,
            HorseProfileCompletionRun,
            HorseP0Source,
            HorseProfileDataCandidate,
            HorseRaceRecord,
        )
        before = {model: model.objects.count() for model in models}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(reviewed_csv, _reviewed_candidate_rows())

            manifest = module.run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=reviewed_csv,
                cache_dir=root / "empty-cache",
                output_dir=output_dir,
                allow_network=False,
                generated_at="2026-07-18T00:00:00Z",
            )

            manifest_path = (
                output_dir / "p0_horse_completion_batch_manifest.json"
            )
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                manifest,
            )
            self.assertEqual(manifest["summary"]["processed_count"], 50)
            self.assertEqual(
                {
                    region: stats["processed_count"]
                    for region, stats in manifest["summary"]["regions"].items()
                },
                {region: 10 for region in SOURCE_BY_REVIEW_REGION},
            )
            self.assertEqual(manifest["summary"]["network_request_count"], 0)

        after = {model: model.objects.count() for model in models}
        self.assertEqual(after, before)

    def test_complete_horse_profiles_has_explicit_reviewed_candidate_dry_run_entry(self):
        rows = _reviewed_candidate_rows()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            cache_dir = root / "cache"
            _write_reviewed_candidate_csv(reviewed_csv, rows)

            with (
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "run_reviewed_p0_horse_completion_batch",
                    create=True,
                ) as run_batch,
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "plan_profile_completion",
                ) as legacy_plan,
            ):
                run_batch.return_value = {
                    "read_only": True,
                    "summary": {"processed_count": 50},
                }
                call_command(
                    "complete_horse_profiles",
                    "--dry-run",
                    "--p0-reviewed-candidates",
                    str(reviewed_csv),
                    "--cache-dir",
                    str(cache_dir),
                    "--output-dir",
                    str(output_dir),
                    stdout=StringIO(),
                )

        legacy_plan.assert_not_called()
        run_batch.assert_called_once()
        kwargs = run_batch.call_args.kwargs
        self.assertEqual(Path(kwargs["reviewed_candidates_csv"]), reviewed_csv)
        self.assertEqual(Path(kwargs["cache_dir"]), cache_dir)
        self.assertEqual(Path(kwargs["output_dir"]), output_dir)
        self.assertIs(kwargs["allow_network"], False)


class P0HorseCompletionModuleReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="p0-completion-reviewer",
            password="unused",
        )
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Review Test Horse",
            target_zh="审核测试马",
            racing_region=RacingRegion.UNITED_KINGDOM,
            is_active=True,
        )
        self.profile = HorseProfile.objects.create(
            primary_term=term,
            original_name="Review Test Horse",
            display_name_zh="审核测试马",
            racing_region=RacingRegion.UNITED_KINGDOM,
            owner_name="Original Owner",
            trainer_name="Original Trainer",
            manual_lock_flags={"owner_name": True},
        )

    def _row(self, *, status: str, confidence: int = 100):
        return {
            "profile_id": self.profile.id,
            "reviewed": True,
            "source_name": "sporting_life",
            "source_url": "https://example.test/sporting-life/horse/review-test",
            "confidence": confidence,
            "profile_payload": {
                "owner_name": "Candidate Owner",
                "trainer_name": "Candidate Trainer",
            },
            "module_reviews": {
                "profile": {
                    "status": status,
                    "confidence": confidence,
                    "reason": f"profile marked {status}",
                }
            },
            "raw_payload": {"source": "fixture", "status": status},
        }

    def _apply(self, row: dict):
        return apply_reviewed_completion_artifact(
            {
                "reviewed": True,
                "reviewer_id": self.user.id,
                "rows": [row],
            },
            commit=True,
        )

    def test_apply_records_diff_reviewer_time_raw_payload_and_manual_lock_skip(self):
        row = self._row(status="approved")
        summary = self._apply(row)
        self.profile.refresh_from_db()
        audit = HorseProfileDataCandidate.objects.get(
            profile=self.profile,
            module=HorseProfileModule.PROFILE,
            status=HorseProfileCandidateStatus.APPLIED,
        )

        self.assertEqual(self.profile.owner_name, "Original Owner")
        self.assertEqual(self.profile.trainer_name, "Candidate Trainer")
        self.assertEqual(summary["manual_lock_skipped"], 1)
        self.assertEqual(audit.applied_by, self.user)
        self.assertIsNotNone(audit.applied_at)
        self.assertEqual(audit.raw_payload, row)
        self.assertEqual(
            audit.diff_payload["trainer_name"],
            {"before": "Original Trainer", "after": "Candidate Trainer"},
        )

    def test_reviewed_career_without_explicit_authority_applies_as_unknown(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": f"profile:{self.profile.id}",
                    "race_name": "Ordinary Chase",
                    "race_date": "2025-01-02",
                    "racecourse": "Kempton",
                    "distance_text": "2m",
                    "finish": "4",
                    "source_name": "sporting_life",
                    "source_url": "https://example.test/race/ordinary-chase",
                }
            ],
            source_start_count=1,
        )
        row = self._row(status="unreviewed")
        row.update(
            {
                "race_records_payload": normalized["race_records"],
                "career_history": normalized["career_history"],
                "module_reviews": {
                    "race_records": {
                        "status": "approved",
                        "confidence": 100,
                        "reason": "career reviewed",
                    }
                },
            }
        )

        summary = self._apply(row)
        self.profile.refresh_from_db()

        self.assertEqual(
            normalized["career_history"]["record_authority_status"],
            "unknown",
        )
        self.assertEqual(summary["race_records_created"], 1)
        self.assertEqual(
            HorseRaceRecord.objects.get(
                horse_profile=self.profile
            ).result_status,
            "unplaced",
        )
        self.assertEqual(
            self.profile.career_record_authority_status,
            "unknown",
        )
        self.assertEqual(self.profile.collected_start_count, 1)

    def test_year_precision_remains_partial_before_and_after_reviewed_apply(self):
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": f"profile:{self.profile.id}",
                    "race_name": "Year-only Chase",
                    "race_date": "2024",
                    "racecourse": "Kempton",
                    "distance_text": "2m",
                    "finish": "4",
                    "source_name": "sporting_life",
                    "source_url": "https://example.test/race/year-only-chase",
                }
            ],
            source_start_count=1,
            official_start_count_source="sporting_life",
            official_start_count_source_url=(
                "https://example.test/horse/review-test"
            ),
            official_start_count_verified_at="2026-07-19T00:00:00+00:00",
            record_authority_status="source_records_verified",
        )
        self.assertEqual(normalized["career_history"]["status"], "partial")

        row = self._row(status="unreviewed")
        row.update(
            {
                "race_records_payload": normalized["race_records"],
                "career_history": normalized["career_history"],
                "module_reviews": {
                    "race_records": {
                        "status": "approved",
                        "confidence": 100,
                        "reason": "year precision retained for review",
                    }
                },
            }
        )
        self._apply(row)
        self.profile.refresh_from_db()
        record = HorseRaceRecord.objects.get(horse_profile=self.profile)

        self.assertEqual(record.race_date_precision, "year")
        self.assertIsNone(record.race_date)
        self.assertEqual(
            self.profile.career_history_status,
            HorseCareerHistoryStatus.PARTIAL,
        )

    def test_reviewed_career_omission_clears_stale_verified_authority(self):
        self.profile.career_record_authority_status = (
            HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED
        )
        self.profile.save(
            update_fields=["career_record_authority_status"]
        )
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": f"profile:{self.profile.id}",
                    "race_name": "Replacement Ordinary Chase",
                    "race_date": "2025-01-03",
                    "racecourse": "Kempton",
                    "distance_text": "2m",
                    "finish": "5",
                    "source_name": "sporting_life",
                    "source_url": (
                        "https://example.test/race/replacement-chase"
                    ),
                }
            ],
            source_start_count=1,
        )
        career_history = dict(normalized["career_history"])
        career_history.pop("record_authority_status")
        row = self._row(status="unreviewed")
        row.update(
            {
                "race_records_payload": normalized["race_records"],
                "career_history": career_history,
                "module_reviews": {
                    "race_records": {
                        "status": "approved",
                        "confidence": 100,
                        "reason": "replacement career reviewed",
                    }
                },
            }
        )

        self._apply(row)
        self.profile.refresh_from_db()

        self.assertEqual(
            self.profile.career_record_authority_status,
            HorseCareerRecordAuthorityStatus.UNKNOWN,
        )
        self.assertNotEqual(
            self.profile.career_history_status,
            HorseCareerHistoryStatus.COMPLETE,
        )

    def test_invalid_artifact_urls_and_birth_date_do_not_write(self):
        invalid_profile_url = self._row(status="approved")
        invalid_profile_url["source_url"] = (
            "https://bad host.example/profile"
        )
        summary = self._apply(invalid_profile_url)
        self.profile.refresh_from_db()
        self.assertEqual(summary["skipped_missing_source_url"], 1)
        self.assertEqual(self.profile.trainer_name, "Original Trainer")

        self.profile.birth_date = date(2020, 1, 2)
        self.profile.save(update_fields=["birth_date"])
        invalid_birth_date = self._row(status="approved")
        invalid_birth_date["profile_payload"] = {
            "birth_date": "not-a-date",
        }
        summary = self._apply(invalid_birth_date)
        self.profile.refresh_from_db()
        self.assertEqual(summary["skipped_conflict_modules"], 1)
        self.assertEqual(self.profile.birth_date, date(2020, 1, 2))

        invalid_race_url = self._row(status="unreviewed")
        invalid_race_url.update(
            {
                "race_records_payload": [
                    {
                        "race_name": "Invalid URL Chase",
                        "race_date": "2025-01-04",
                        "racecourse": "Kempton",
                        "finish_position": "4",
                        "result_status": "unplaced",
                        "start_status": "started",
                        "source_name": "sporting_life",
                        "source_url": (
                            "https://example.com:not-a-port/race"
                        ),
                    }
                ],
                "career_history": {},
                "module_reviews": {
                    "race_records": {
                        "status": "approved",
                        "confidence": 100,
                        "reason": "invalid URL must not write",
                    }
                },
            }
        )
        summary = self._apply(invalid_race_url)
        self.assertEqual(summary["skipped_missing_source_url"], 1)
        self.assertFalse(
            HorseRaceRecord.objects.filter(
                horse_profile=self.profile,
                race_name="Invalid URL Chase",
            ).exists()
        )

    def test_new_count_without_complete_evidence_clears_stale_group(self):
        self.profile.official_or_source_start_count = 9
        self.profile.official_start_count_source = "old_official"
        self.profile.official_start_count_source_url = (
            "https://example.test/old/count"
        )
        self.profile.official_start_count_verified_at = timezone.now()
        self.profile.career_record_authority_status = (
            HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED
        )
        self.profile.save()
        module = _target_module()
        normalized = module.normalize_p0_horse_race_records(
            [
                {
                    "horse_identity_key": f"profile:{self.profile.id}",
                    "race_name": "New Count Chase",
                    "race_date": "2025-01-05",
                    "racecourse": "Kempton",
                    "finish": "4",
                    "source_name": "sporting_life",
                    "source_url": "https://example.test/race/new-count",
                }
            ],
            source_start_count=1,
            official_start_count_source="sporting_life",
            official_start_count_source_url=(
                "https://example.test/horse/new-count"
            ),
            official_start_count_verified_at="2026-07-19T00:00:00+00:00",
            record_authority_status="source_records_verified",
        )
        incomplete_evidence = dict(normalized["career_history"])
        incomplete_evidence.pop("official_start_count_source_url")
        row = self._row(status="unreviewed")
        row.update(
            {
                "race_records_payload": normalized["race_records"],
                "career_history": incomplete_evidence,
                "module_reviews": {
                    "race_records": {
                        "status": "approved",
                        "confidence": 100,
                        "reason": "new count evidence is incomplete",
                    }
                },
            }
        )

        self._apply(row)
        self.profile.refresh_from_db()

        self.assertIsNone(self.profile.official_or_source_start_count)
        self.assertEqual(self.profile.official_start_count_source, "")
        self.assertEqual(self.profile.official_start_count_source_url, "")
        self.assertIsNone(
            self.profile.official_start_count_verified_at
        )
        self.assertEqual(
            self.profile.career_history_status,
            HorseCareerHistoryStatus.PARTIAL,
        )

    def test_ignore_records_auditable_decision_without_changing_master_data(self):
        row = self._row(status="ignore")
        summary = self._apply(row)
        self.profile.refresh_from_db()
        audit = HorseProfileDataCandidate.objects.get(
            profile=self.profile,
            module=HorseProfileModule.PROFILE,
            status=HorseProfileCandidateStatus.IGNORED,
        )

        self.assertEqual(self.profile.owner_name, "Original Owner")
        self.assertEqual(self.profile.trainer_name, "Original Trainer")
        self.assertEqual(summary["ignored_modules"], 1)
        self.assertEqual(audit.applied_by, self.user)
        self.assertIsNotNone(audit.applied_at)
        self.assertEqual(audit.raw_payload, row)

    def test_conflict_keeps_raw_payload_and_never_changes_master_data(self):
        row = self._row(status="conflict")
        summary = self._apply(row)
        self.profile.refresh_from_db()
        audit = HorseProfileDataCandidate.objects.get(
            profile=self.profile,
            module=HorseProfileModule.PROFILE,
            status=HorseProfileCandidateStatus.CONFLICT,
        )

        self.assertEqual(self.profile.owner_name, "Original Owner")
        self.assertEqual(self.profile.trainer_name, "Original Trainer")
        self.assertEqual(summary["skipped_conflict_modules"], 1)
        self.assertEqual(audit.raw_payload, row)
        self.assertFalse(HorseRaceRecord.objects.filter(horse_profile=self.profile).exists())

    def test_low_confidence_approved_module_is_blocked(self):
        summary = self._apply(self._row(status="approved", confidence=10))
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.owner_name, "Original Owner")
        self.assertEqual(self.profile.trainer_name, "Original Trainer")
        self.assertEqual(summary["skipped_low_confidence_modules"], 1)
        self.assertFalse(
            HorseProfileDataCandidate.objects.filter(
                profile=self.profile,
                status=HorseProfileCandidateStatus.APPLIED,
            ).exists()
        )
