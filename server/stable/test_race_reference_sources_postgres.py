"""PostgreSQL-only concurrency evidence for Phase B0.1 reference recording."""

from __future__ import annotations

import hashlib
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from django.db import connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from stable import models as stable_models
from stable.services.race_live_racecard_sync import normalize_identity_text


def _canonical_sha(value: dict) -> str:
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


@skipUnlessDBFeature("has_select_for_update")
class RaceReferenceRecordConcurrencyTests(TransactionTestCase):
    """B41/B53: advisory lock + unique constraints preserve one logical write."""

    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL advisory-lock semantics")
        self.event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-cup-2025",
            original_name="Reference Cup",
            chinese_name="参考杯",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 19),
        )
        snapshot = {
            "event_id": self.event.pk,
            "slug": self.event.slug,
            "country_region": self.event.country_region,
            "local_date": self.event.local_date.isoformat(),
            "timezone_name": self.event.timezone_name,
            "racecourse": self.event.racecourse,
            "original_name": self.event.original_name,
            "normalized_accepted_race_names": [
                normalize_identity_text(self.event.original_name)
            ],
            "status": self.event.status,
        }
        self.manifest = {
            "schema_version": 1,
            "purpose": "internal_reference_post_race",
            "source_key": "reference_sporting_life",
            "reference_schema_version": 1,
            "parser": {"name": "sporting_life", "version": "reference-v1"},
            "generated_at": "2026-07-27T00:00:00+00:00",
            "events": [
                {
                    **snapshot,
                    "provider_event_key": "sl:859381",
                    "source_url": (
                        "https://www.sportinglife.com/racing/results/"
                        "2025-06-19/royal-ascot/859381/gold-cup-group-1"
                    ),
                    "event_snapshot_sha256": _canonical_sha(snapshot),
                }
            ],
        }
        self.payload = {
            "schema_version": 1,
            "source_key": "reference_sporting_life",
            "country_region": "united_kingdom",
            "provider_event_key": "sl:859381",
            "race": {
                "source_race_name": "Reference Cup",
                "source_racecourse": "Ascot",
                "local_date": "2025-06-19",
                "source_start_time": "15:40",
            },
            "runners": [],
            "completeness": {
                "race_identity": "complete",
                "runners": "complete",
                "results": "complete",
                "gap_codes": [],
            },
        }
        source_url = self.manifest["events"][0]["source_url"]
        self.artifact = {
            "artifact_sha256": "a" * 64,
            "observations": [
                {
                    "payload": self.payload,
                    "provenance": {
                        "source_url": source_url,
                        "final_url": source_url,
                        "source_observed_at": None,
                        "fetched_at": "2026-07-27T00:00:00+00:00",
                        "parser": {
                            "name": "sporting_life",
                            "version": "reference-v1",
                        },
                        "legacy_payload_sha256": "1" * 64,
                        "raw_sha256": "2" * 64,
                        "source_cache_ref": f"raw/{self.event.pk}.body",
                    },
                    "event_id": self.event.pk,
                    "match_status": "matched",
                    "match_confidence": 100,
                    "match_evidence": {"provider_key": "sl:859381"},
                    "classification_version": "test-v1",
                }
            ],
        }

    def _record(self):
        connections.close_all()
        try:
            service = importlib.import_module("stable.services.race_reference_sources")
            result = service.record_reference_collection(
                manifest=self.manifest,
                manifest_sha256=_canonical_sha(self.manifest),
                artifact=self.artifact,
            )
            return result["replayed"]
        finally:
            connections.close_all()

    def test_same_manifest_artifact_concurrent_record_has_one_run_and_one_receipt(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._record) for _ in range(2)]
            replayed = [future.result(timeout=20) for future in futures]

        self.assertEqual(sorted(replayed), [False, True])
        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 1)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 1)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 1)

    def test_late_transaction_failure_rolls_back_run_payload_and_receipt(self):
        service = importlib.import_module("stable.services.race_reference_sources")
        with self.assertRaises(RuntimeError):
            service.record_reference_collection(
                manifest=self.manifest,
                manifest_sha256=_canonical_sha(self.manifest),
                artifact=self.artifact,
                fail_after_receipt_for_test=True,
            )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)
