from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from stable import models
from stable.services import race_events
from stable.services import race_live_initialization as initialization


class RaceLiveInitializationV2Tests(TestCase):
    NOW = datetime(2026, 7, 18, 10, 0, tzinfo=dt_timezone.utc)
    OFF_TIME = datetime(2026, 7, 18, 13, 40, tzinfo=dt_timezone.utc)
    APPROVED_COMMIT = "c" * 40
    REGISTRY_DIGEST = "a" * 64
    COVERAGE_DIGEST = "b" * 64
    TERMS_DIGEST = "d" * 64
    OFFICIAL_EVIDENCE_DIGEST = "e" * 64
    SOURCE_RESPONSE_DIGEST = "f" * 64

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.event = self._event("v2-race-live-init")

    def _event(self, slug, **overrides):
        values = {
            "year": 2026,
            "slug": slug,
            "original_name": "V2 Initialization Stakes",
            "chinese_name": "V2 准实时初始化锦标",
            "country_region": models.RacingRegion.UNITED_KINGDOM,
            "racecourse": "Ascot",
            "grade_text": "G1",
            "surface": models.RaceEventSurface.TURF,
            "race_datetime": None,
            "timezone_name": "Europe/London",
            "local_date": date(2026, 7, 18),
            "local_start_time": None,
            "status": models.RaceEventStatus.SCHEDULED,
        }
        values.update(overrides)
        return models.RaceEvent.objects.create(**values)

    def _event_entry(
        self,
        event=None,
        *,
        suffix="1",
        source_off_dt=None,
        generated_at=None,
    ):
        event = event or self.event
        event.refresh_from_db()
        generated_at = generated_at or self.NOW
        source_off_dt = source_off_dt or self.OFF_TIME.isoformat()
        off_time = datetime.fromisoformat(source_off_dt.replace("Z", "+00:00"))
        tracking_state = (
            models.RaceEventLiveState.RACECARD_READY
            if generated_at < off_time
            else models.RaceEventLiveState.AWAITING_RESULT
        )
        next_poll_at = (
            race_events.calculate_race_live_next_poll_at(
                off_time=off_time,
                now=generated_at,
                state=tracking_state,
            )
            if generated_at < off_time
            else generated_at
        )
        return {
            "event_id": event.pk,
            "expected_event_updated_at": event.updated_at.isoformat(),
            "year": event.year,
            "slug": event.slug,
            "original_name": event.original_name,
            "country_region": event.country_region,
            "racecourse": event.racecourse,
            "grade_text": event.grade_text,
            "race_datetime": source_off_dt,
            "external_race_id": f"tra-v2-race-{suffix}",
            "tracking_state": tracking_state,
            "next_poll_at": next_poll_at.isoformat(),
            "expected_race_datetime_before": (
                event.race_datetime.isoformat()
                if event.race_datetime is not None
                else None
            ),
            "expected_local_start_time_before": (
                event.local_start_time.isoformat()
                if event.local_start_time is not None
                else None
            ),
            "expected_status": models.RaceEventStatus.SCHEDULED,
            "expected_local_date": event.local_date.isoformat(),
            "expected_timezone_name": "Europe/London",
            "local_date": event.local_date.isoformat(),
            "source_off_dt": source_off_dt,
            "source_response_sha256": self.SOURCE_RESPONSE_DIGEST,
            "participants": [
                {
                    "stable_key": (
                        "tra:" + hashlib.sha256(f"horse-{suffix}-1".encode()).hexdigest()
                    ),
                    "canonical_name": f"V2 Runner {suffix} Alpha",
                    "country_region": "",
                    "external_runner_id": f"horse-{suffix}-1",
                    "horse_number": "1",
                    "status": models.RaceEventRevisionItemStatus.DECLARED,
                    "barrier": "4",
                    "jockey_name": "V2 Jockey Alpha",
                    "jockey_id": f"jockey-{suffix}-1",
                },
                {
                    "stable_key": (
                        "tra:" + hashlib.sha256(f"horse-{suffix}-2".encode()).hexdigest()
                    ),
                    "canonical_name": f"V2 Runner {suffix} Beta",
                    "country_region": "",
                    "external_runner_id": f"horse-{suffix}-2",
                    "horse_number": "2",
                    "status": models.RaceEventRevisionItemStatus.DECLARED,
                    "barrier": "",
                    "jockey_name": "",
                    "jockey_id": "",
                },
            ],
        }

    def _manifest(self, *, events=None, generated_at=None, **overrides):
        generated_at = generated_at or self.NOW
        payload = {
            "schema_version": 2,
            "approved_commit": self.APPROVED_COMMIT,
            "generated_at": generated_at.isoformat(),
            "registry_digest": self.REGISTRY_DIGEST,
            "registry_valid_until": (
                self.NOW + timedelta(days=21)
            ).isoformat(),
            "coverage_proof_digest": self.COVERAGE_DIGEST,
            "terms_evidence_sha256": self.TERMS_DIGEST,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "policy_valid_until": (self.NOW + timedelta(days=20)).isoformat(),
            "requests_sha256": "",
            "report_sha256": "",
            "official_verification_route": "bha_manual_verification",
            "official_verification_route_version": "bha-manual-v1",
            "official_verification_evidence_sha256": (
                self.OFFICIAL_EVIDENCE_DIGEST
            ),
            "official_verification_valid_until": (
                self.NOW + timedelta(days=20)
            ).isoformat(),
            "events": events or [self._event_entry(generated_at=generated_at)],
        }
        payload.update(overrides)
        return payload

    def _write_artifact(
        self,
        payload,
        *,
        dirname="artifact",
        requests=b'{"endpoint_name":"racecards_sync_today","status":200}\n',
        report=b'{"blockers":[],"matched_event_count":1}\n',
    ):
        artifact = self.root / dirname
        artifact.mkdir()
        requests_path = artifact / "requests.jsonl"
        report_path = artifact / "report.json"
        requests_path.write_bytes(requests)
        report_path.write_bytes(report)
        requests_path.chmod(0o600)
        report_path.chmod(0o600)
        payload["requests_sha256"] = hashlib.sha256(requests).hexdigest()
        payload["report_sha256"] = hashlib.sha256(report).hexdigest()
        manifest_path = artifact / "manifest.json"
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        return artifact, manifest_path, digest

    def _load(self, manifest_path, digest, *, now=None):
        return initialization.load_race_live_initialization_manifest(
            manifest_path=manifest_path,
            expected_manifest_sha256=digest,
            expected_approved_commit=self.APPROVED_COMMIT,
            now=now or self.NOW,
        )

    def _assert_no_event_initialization(self, event=None):
        event = event or self.event
        self.assertIsNone(
            models.RaceEvent.objects.values_list(
                "race_datetime", flat=True
            ).get(pk=event.pk)
        )
        for model, lookup in (
            (models.RaceEventProjectionControl, {"event": event}),
            (models.RaceEventLiveTracking, {"event": event}),
            (models.RaceResultSourceIdentity, {"event": event}),
            (models.RaceLiveEventPublicationAllowlist, {"event": event}),
            (models.RaceEventParticipant, {"event": event}),
            (models.RaceEventRevision, {"event": event}),
        ):
            self.assertFalse(model.objects.filter(**lookup).exists(), model.__name__)

    def test_v2_loader_binds_companions_and_rejects_schema_or_time_drift(self):
        artifact, path, digest = self._write_artifact(self._manifest())

        loaded = self._load(path, digest)

        self.assertEqual(loaded.payload["schema_version"], 2)
        self.assertEqual(loaded.payload["requests_sha256"], hashlib.sha256(
            (artifact / "requests.jsonl").read_bytes()
        ).hexdigest())

        invalid_payloads = []
        unknown = self._manifest()
        unknown["unknown"] = True
        invalid_payloads.append(("unknown_key", unknown))
        missing = self._manifest()
        missing.pop("official_verification_evidence_sha256")
        invalid_payloads.append(("missing_key", missing))
        wrong_timezone = self._manifest()
        wrong_timezone["events"][0]["expected_timezone_name"] = "Asia/Tokyo"
        invalid_payloads.append(("wrong_timezone", wrong_timezone))
        naive = self._manifest()
        naive["events"][0]["source_off_dt"] = "2026-07-18T14:40:00"
        naive["events"][0]["race_datetime"] = "2026-07-18T14:40:00"
        invalid_payloads.append(("naive_source_time", naive))
        wrong_date = self._manifest()
        wrong_date["events"][0]["local_date"] = "2026-07-19"
        invalid_payloads.append(("wrong_local_date", wrong_date))
        invalid_policy = self._manifest(
            policy_valid_until=(self.NOW + timedelta(days=22)).isoformat()
        )
        invalid_payloads.append(("policy_after_registry", invalid_policy))
        wrong_country = self._manifest()
        wrong_country["events"][0]["participants"][0]["country_region"] = (
            models.RacingRegion.UNITED_KINGDOM
        )
        invalid_payloads.append(("participant_country_faked", wrong_country))

        for index, (label, payload) in enumerate(invalid_payloads):
            with self.subTest(case=label):
                _, invalid_path, invalid_digest = self._write_artifact(
                    payload,
                    dirname=f"invalid-{index}",
                )
                with self.assertRaises(
                    initialization.RaceLiveInitializationError
                ):
                    self._load(invalid_path, invalid_digest)

    def test_v2_loader_rejects_isolated_missing_changed_or_symlink_companion(self):
        artifact, path, digest = self._write_artifact(self._manifest())
        self._load(path, digest)
        (artifact / "report.json").write_bytes(b'{"blockers":["changed"]}\n')
        with self.assertRaises(initialization.RaceLiveInitializationError):
            self._load(path, digest)

        isolated = self.root / "isolated"
        isolated.mkdir()
        isolated_manifest = isolated / "manifest.json"
        isolated_manifest.write_bytes(path.read_bytes())
        isolated_digest = hashlib.sha256(isolated_manifest.read_bytes()).hexdigest()
        with self.assertRaises(initialization.RaceLiveInitializationError):
            self._load(isolated_manifest, isolated_digest)

        symlink_payload = self._manifest()
        symlink_artifact = self.root / "symlink-artifact"
        symlink_artifact.mkdir()
        real_requests = self.root / "real-requests.jsonl"
        real_requests.write_bytes(b"{}\n")
        (symlink_artifact / "requests.jsonl").symlink_to(real_requests)
        report = symlink_artifact / "report.json"
        report.write_bytes(b"{}\n")
        symlink_payload["requests_sha256"] = hashlib.sha256(
            real_requests.read_bytes()
        ).hexdigest()
        symlink_payload["report_sha256"] = hashlib.sha256(
            report.read_bytes()
        ).hexdigest()
        symlink_manifest = symlink_artifact / "manifest.json"
        symlink_manifest.write_text(
            json.dumps(symlink_payload, sort_keys=True),
            encoding="utf-8",
        )
        symlink_digest = hashlib.sha256(symlink_manifest.read_bytes()).hexdigest()
        with self.assertRaises(initialization.RaceLiveInitializationError):
            self._load(symlink_manifest, symlink_digest)

    def test_v2_dry_run_is_read_only_and_apply_atomically_sets_time_and_fields(self):
        models.RaceLiveHostBudget.objects.create(
            host="api.theracingapi.com",
            min_interval_ms=2000,
            next_allowed_at=self.NOW + timedelta(seconds=1),
            consecutive_failures=2,
            last_error_code="timeout",
            lock_version=7,
        )
        _, path, digest = self._write_artifact(self._manifest())
        loaded = self._load(path, digest)

        dry_run = initialization.dry_run_race_live_initialization(loaded)

        self.assertTrue(dry_run["ok"])
        self._assert_no_event_initialization()
        self.assertEqual(models.RaceLivePublicationPolicy.objects.count(), 0)

        applied = initialization.apply_race_live_initialization(loaded)

        self.assertTrue(applied["ok"])
        self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime, self.OFF_TIME)
        self.assertEqual(self.event.local_start_time.isoformat(), "14:40:00")
        self.assertEqual(self.event.timezone_name, "Europe/London")
        self.assertEqual(self.event.local_date, date(2026, 7, 18))
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(
            tracking.state,
            models.RaceEventLiveState.RACECARD_READY,
        )
        self.assertEqual(
            tracking.next_poll_at,
            race_events.calculate_race_live_next_poll_at(
                off_time=self.OFF_TIME,
                now=self.NOW,
                state=models.RaceEventLiveState.RACECARD_READY,
            ),
        )
        participants = list(
            models.RaceEventParticipant.objects.filter(event=self.event).order_by(
                "stable_key"
            )
        )
        self.assertTrue(all(row.country_region == "" for row in participants))
        item = models.RaceEventRevisionItem.objects.get(
            revision__event=self.event,
            horse_number="1",
        )
        self.assertEqual(item.barrier, "4")
        self.assertEqual(item.jockey_name, "V2 Jockey Alpha")
        self.assertEqual(item.field_provenance["jockey_id"], "jockey-1-1")
        budget = models.RaceLiveHostBudget.objects.get(
            host="api.theracingapi.com"
        )
        self.assertEqual(budget.min_interval_ms, 2000)
        self.assertEqual(budget.lock_version, 7)
        self.assertEqual(budget.consecutive_failures, 2)

        verified = initialization.verify_race_live_initialization(loaded)
        self.assertTrue(verified["ok"], verified["errors"])

    def test_v2_post_off_initializes_awaiting_and_is_immediately_due(self):
        generated_at = self.NOW
        source_off_dt = (self.NOW - timedelta(minutes=2)).isoformat()
        payload = self._manifest(
            generated_at=generated_at,
            events=[
                self._event_entry(
                    source_off_dt=source_off_dt,
                    generated_at=generated_at,
                )
            ],
        )
        _, path, digest = self._write_artifact(payload)
        loaded = self._load(path, digest)

        initialization.apply_race_live_initialization(loaded)

        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(
            tracking.state,
            models.RaceEventLiveState.AWAITING_RESULT,
        )
        self.assertEqual(tracking.next_poll_at, generated_at)

    def test_v2_field_cas_blocks_queryset_update_without_relying_on_updated_at(self):
        _, path, digest = self._write_artifact(self._manifest())
        loaded = self._load(path, digest)
        models.RaceEvent.objects.filter(pk=self.event.pk).update(
            status=models.RaceEventStatus.CANCELLED,
        )

        with self.assertRaises(initialization.RaceLiveInitializationError):
            initialization.apply_race_live_initialization(loaded)

        self._assert_no_event_initialization()

    def test_v2_late_external_identity_conflict_rolls_back_time_and_every_live_row(self):
        other = self._event(
            "v2-race-live-other",
            original_name="Other V2 Initialization Stakes",
        )
        models.RaceResultSourceIdentity.objects.create(
            event=other,
            source_key="the_racing_api",
            external_race_id="tra-v2-race-1",
        )
        _, path, digest = self._write_artifact(self._manifest())
        loaded = self._load(path, digest)

        with self.assertRaises(initialization.RaceLiveInitializationError):
            initialization.apply_race_live_initialization(loaded)

        self._assert_no_event_initialization()
        self.assertEqual(models.RaceLivePublicationPolicy.objects.count(), 0)
        self.assertEqual(models.RaceLiveHostBudget.objects.count(), 0)

    def test_v2_exact_replay_is_idempotent_but_different_manifest_never_replays(self):
        _, path, digest = self._write_artifact(self._manifest())
        loaded = self._load(path, digest)
        initialization.apply_race_live_initialization(loaded)
        before = {
            model.__name__: model.objects.count()
            for model in (
                models.RaceEventProjectionControl,
                models.RaceEventLiveTracking,
                models.RaceResultSourceIdentity,
                models.RaceEventParticipant,
                models.RaceEventRevision,
                models.RaceEventRevisionItem,
                models.OperationLog,
            )
        }

        replay = initialization.apply_race_live_initialization(loaded)

        self.assertEqual(replay["replayed_event_count"], 1)
        after = {
            model.__name__: model.objects.count()
            for model in (
                models.RaceEventProjectionControl,
                models.RaceEventLiveTracking,
                models.RaceResultSourceIdentity,
                models.RaceEventParticipant,
                models.RaceEventRevision,
                models.RaceEventRevisionItem,
                models.OperationLog,
            )
        }
        self.assertEqual(after, before)

        changed = self._manifest()
        _, changed_path, changed_digest = self._write_artifact(
            changed,
            dirname="changed-artifact",
            report=b'{"blockers":[],"matched_event_count":1,"revision":2}\n',
        )
        changed_loaded = self._load(changed_path, changed_digest)
        with self.assertRaises(initialization.RaceLiveInitializationError):
            initialization.apply_race_live_initialization(changed_loaded)
        self.assertEqual(
            {
                model.__name__: model.objects.count()
                for model in (
                    models.RaceEventProjectionControl,
                    models.RaceEventLiveTracking,
                    models.RaceResultSourceIdentity,
                    models.RaceEventParticipant,
                    models.RaceEventRevision,
                    models.RaceEventRevisionItem,
                    models.OperationLog,
                )
            },
            before,
        )

    def test_public_shared_caps_are_reused_but_second_event_stays_explicit_shadow(self):
        _, first_path, first_digest = self._write_artifact(self._manifest())
        first = self._load(first_path, first_digest)
        initialization.apply_race_live_initialization(first)
        models.RaceLivePublicationPolicy.objects.exclude(
            scope_type=models.RaceLivePublicationScopeType.EVENT
        ).update(
            mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            version=2,
        )
        second_event = self._event(
            "v2-race-live-second",
            original_name="Second V2 Initialization Stakes",
        )
        second_manifest = self._manifest(
            events=[
                self._event_entry(
                    second_event,
                    suffix="2",
                    generated_at=self.NOW,
                )
            ]
        )
        _, second_path, second_digest = self._write_artifact(
            second_manifest,
            dirname="second-artifact",
        )
        second = self._load(second_path, second_digest)

        self.assertTrue(initialization.dry_run_race_live_initialization(second)["ok"])
        applied = initialization.apply_race_live_initialization(second)

        self.assertTrue(applied["ok"])
        shared = models.RaceLivePublicationPolicy.objects.exclude(
            scope_type=models.RaceLivePublicationScopeType.EVENT
        )
        self.assertEqual(
            set(shared.values_list("mode", "version")),
            {(models.RaceLivePublicationMode.PROVISIONAL_PUBLIC, 2)},
        )
        event_policy = models.RaceLivePublicationPolicy.objects.get(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(second_event.pk),
        )
        self.assertEqual(event_policy.mode, models.RaceLivePublicationMode.SHADOW)
        self.assertEqual(event_policy.version, 1)
        source = models.RaceResultSourceIdentity.objects.get(event=second_event)
        decision = race_events.resolve_race_live_publication_policy(
            event_id=second_event.pk,
            source_identity_id=source.pk,
            now=self.NOW,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "shadow_only")

    def test_existing_non_shadow_event_policy_blocks_fresh_initialization(self):
        _, first_path, first_digest = self._write_artifact(self._manifest())
        initialization.apply_race_live_initialization(
            self._load(first_path, first_digest)
        )
        models.RaceLivePublicationPolicy.objects.exclude(
            scope_type=models.RaceLivePublicationScopeType.EVENT
        ).update(
            mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            version=2,
        )
        second_event = self._event(
            "v2-race-live-conflicting-event-policy",
            original_name="Conflicting Event Policy Stakes",
        )
        models.RaceLivePublicationPolicy.objects.create(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(second_event.pk),
            mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            version=2,
            registry_digest=self.REGISTRY_DIGEST,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            valid_until=self.NOW + timedelta(days=20),
        )
        second_manifest = self._manifest(
            events=[
                self._event_entry(
                    second_event,
                    suffix="conflict",
                    generated_at=self.NOW,
                )
            ]
        )
        _, second_path, second_digest = self._write_artifact(
            second_manifest,
            dirname="conflicting-event-policy-artifact",
        )

        with self.assertRaises(initialization.RaceLiveInitializationError):
            initialization.dry_run_race_live_initialization(
                self._load(second_path, second_digest)
            )

        self.assertFalse(
            models.RaceEventProjectionControl.objects.filter(
                event=second_event
            ).exists()
        )
