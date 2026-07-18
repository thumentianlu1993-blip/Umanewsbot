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
    RaceLiveInitializationError,
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


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class RaceLiveInitializationV2PostgresTests(TransactionTestCase):
    reset_sequences = True
    NOW = datetime(2026, 7, 18, 10, 0, tzinfo=dt_timezone.utc)
    OFF_TIME = datetime(2026, 7, 18, 13, 40, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="pg-v2-race-live-init",
            original_name="PostgreSQL V2 Initialization Stakes",
            chinese_name="PostgreSQL V2 初始化锦标",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            timezone_name="Europe/London",
            local_date=self.OFF_TIME.date(),
        )
        self.event.refresh_from_db()

    def _loaded_manifest(self, *, dirname: str, external_race_id: str):
        artifact = self.root / dirname
        artifact.mkdir()
        requests = b'{"endpoint_name":"racecards_sync_today","status":200}\n'
        report = json.dumps(
            {"blockers": [], "manifest_variant": dirname},
            sort_keys=True,
        ).encode("utf-8")
        (artifact / "requests.jsonl").write_bytes(requests)
        (artifact / "report.json").write_bytes(report)
        next_poll_at = self.NOW + timedelta(hours=1)
        payload = {
            "schema_version": 2,
            "approved_commit": "c" * 40,
            "generated_at": self.NOW.isoformat(),
            "registry_digest": "a" * 64,
            "registry_valid_until": (self.NOW + timedelta(days=21)).isoformat(),
            "coverage_proof_digest": "b" * 64,
            "terms_evidence_sha256": "d" * 64,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "policy_valid_until": (self.NOW + timedelta(days=20)).isoformat(),
            "requests_sha256": hashlib.sha256(requests).hexdigest(),
            "report_sha256": hashlib.sha256(report).hexdigest(),
            "official_verification_route": "bha_manual_verification",
            "official_verification_route_version": "bha-manual-v1",
            "official_verification_evidence_sha256": "e" * 64,
            "official_verification_valid_until": (
                self.NOW + timedelta(days=20)
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
                    "race_datetime": self.OFF_TIME.isoformat(),
                    "external_race_id": external_race_id,
                    "tracking_state": "racecard_ready",
                    "next_poll_at": next_poll_at.isoformat(),
                    "expected_race_datetime_before": None,
                    "expected_local_start_time_before": None,
                    "expected_status": "scheduled",
                    "expected_local_date": self.OFF_TIME.date().isoformat(),
                    "expected_timezone_name": "Europe/London",
                    "local_date": self.OFF_TIME.date().isoformat(),
                    "source_off_dt": self.OFF_TIME.isoformat(),
                    "source_response_sha256": "f" * 64,
                    "participants": [
                        {
                            "stable_key": (
                                "tra:" + hashlib.sha256(b"pg-v2-horse").hexdigest()
                            ),
                            "canonical_name": "PostgreSQL V2 Runner",
                            "country_region": "",
                            "external_runner_id": "pg-v2-horse",
                            "horse_number": "1",
                            "status": "declared",
                            "barrier": "2",
                            "jockey_name": "PostgreSQL V2 Jockey",
                            "jockey_id": "pg-v2-jockey",
                        }
                    ],
                }
            ],
        }
        path = artifact / "manifest.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return load_race_live_initialization_manifest(
            manifest_path=path,
            expected_manifest_sha256=digest,
            expected_approved_commit="c" * 40,
            now=self.NOW,
        )

    def test_competing_v2_manifests_serialize_to_one_atomic_winner(self):
        manifests = (
            self._loaded_manifest(
                dirname="manifest-a",
                external_race_id="pg-v2-race-a",
            ),
            self._loaded_manifest(
                dirname="manifest-b",
                external_race_id="pg-v2-race-b",
            ),
        )
        barrier = Barrier(2)

        def apply_once(manifest):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    result = apply_race_live_initialization(manifest)
                except RaceLiveInitializationError:
                    return "rejected"
                return "applied" if result["replayed_event_count"] == 0 else "replayed"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                future.result(timeout=15)
                for future in (
                    pool.submit(apply_once, manifests[0]),
                    pool.submit(apply_once, manifests[1]),
                )
            ]

        self.assertEqual(sorted(outcomes), ["applied", "rejected"])
        self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime, self.OFF_TIME)
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
