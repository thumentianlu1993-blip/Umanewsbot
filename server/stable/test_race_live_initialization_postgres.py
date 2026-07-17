from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from stable import models
from stable.services.race_live_initialization import (
    apply_race_live_initialization,
    load_race_live_initialization_manifest,
)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class RaceLiveInitializationPostgresTests(TransactionTestCase):
    reset_sequences = True
    NOW = datetime(2026, 7, 20, 5, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="pg-race-live-init",
            original_name="PostgreSQL Initialization Stakes",
            chinese_name="PostgreSQL 初始化锦标",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            race_datetime=self.NOW + timedelta(hours=1),
        )
        self.event.refresh_from_db()
        payload = {
            "schema_version": 1,
            "approved_commit": "c" * 40,
            "generated_at": self.NOW.isoformat(),
            "registry_digest": "a" * 64,
            "coverage_proof_digest": "b" * 64,
            "terms_evidence_sha256": "d" * 64,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "policy_valid_until": (self.NOW + timedelta(days=30)).isoformat(),
            "official_verification_route": "jra_result_verification",
            "official_verification_route_version": "jra-v1",
            "official_verification_valid_until": (
                self.NOW + timedelta(days=30)
            ).isoformat(),
            "events": [
                {
                    "event_id": self.event.pk,
                    "expected_event_updated_at": self.event.updated_at.isoformat(),
                    "year": self.event.year,
                    "slug": self.event.slug,
                    "original_name": self.event.original_name,
                    "country_region": self.event.country_region,
                    "racecourse": self.event.racecourse,
                    "grade_text": self.event.grade_text,
                    "race_datetime": self.event.race_datetime.isoformat(),
                    "external_race_id": "pg-tra-race-1",
                    "tracking_state": "racecard_ready",
                    "next_poll_at": (self.NOW + timedelta(minutes=30)).isoformat(),
                    "participants": [
                        {
                            "stable_key": "pg-runner-1",
                            "canonical_name": "PostgreSQL Runner",
                            "country_region": models.RacingRegion.JAPAN,
                            "external_runner_id": "pg-tra-runner-1",
                            "horse_number": "1",
                            "status": "declared",
                        }
                    ],
                }
            ],
        }
        path = Path(self.temporary.name) / "manifest.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = load_race_live_initialization_manifest(
            manifest_path=path,
            expected_manifest_sha256=digest,
            expected_approved_commit="c" * 40,
            now=self.NOW,
        )

    def test_two_concurrent_applies_serialize_to_one_write_and_one_replay(self):
        barrier = Barrier(2)

        def apply_once():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return apply_race_live_initialization(self.manifest)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                future.result(timeout=15)
                for future in (pool.submit(apply_once), pool.submit(apply_once))
            ]

        self.assertEqual(
            sorted(result["replayed_event_count"] for result in outcomes),
            [0, 1],
        )
        self.assertEqual(
            models.RaceEventProjectionControl.objects.filter(
                event=self.event
            ).count(),
            1,
        )
        self.assertEqual(
            models.RaceEventRevision.objects.filter(event=self.event).count(),
            1,
        )
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_event_initialized",
                target_id=str(self.event.pk),
            ).count(),
            1,
        )
