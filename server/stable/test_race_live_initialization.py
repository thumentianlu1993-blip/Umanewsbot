from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from stable import models as stable_models


class RaceLiveInitializationCommandTests(TestCase):
    NOW = datetime(2026, 7, 20, 5, 0, tzinfo=dt_timezone.utc)
    APPROVED_COMMIT = "c" * 40
    REGISTRY_DIGEST = "a" * 64
    COVERAGE_DIGEST = "b" * 64
    TERMS_EVIDENCE_DIGEST = "d" * 64

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.event = self._event("race-live-init-1", "Initialization Stakes")

    def _event(self, slug: str, original_name: str):
        return stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=original_name,
            chinese_name="准实时初始化锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
            race_datetime=self.NOW + timedelta(hours=1),
        )

    def _event_entry(self, event, *, suffix: str = "1"):
        event.refresh_from_db()
        return {
            "event_id": event.pk,
            "expected_event_updated_at": event.updated_at.isoformat(),
            "year": event.year,
            "slug": event.slug,
            "original_name": event.original_name,
            "country_region": event.country_region,
            "racecourse": event.racecourse,
            "grade_text": event.grade_text,
            "race_datetime": event.race_datetime.isoformat(),
            "external_race_id": f"tra-race-{suffix}",
            "tracking_state": "racecard_ready",
            "next_poll_at": (self.NOW + timedelta(minutes=30)).isoformat(),
            "participants": [
                {
                    "stable_key": f"runner-{suffix}-1",
                    "canonical_name": f"Runner {suffix} Alpha",
                    "country_region": stable_models.RacingRegion.JAPAN,
                    "external_runner_id": f"tra-runner-{suffix}-1",
                    "horse_number": "1",
                    "status": "declared",
                },
                {
                    "stable_key": f"runner-{suffix}-2",
                    "canonical_name": f"Runner {suffix} Beta",
                    "country_region": stable_models.RacingRegion.JAPAN,
                    "external_runner_id": f"tra-runner-{suffix}-2",
                    "horse_number": "2",
                    "status": "declared",
                },
            ],
        }

    def _manifest(self, *, events=None):
        return {
            "schema_version": 1,
            "approved_commit": self.APPROVED_COMMIT,
            "generated_at": self.NOW.isoformat(),
            "registry_digest": self.REGISTRY_DIGEST,
            "coverage_proof_digest": self.COVERAGE_DIGEST,
            "terms_evidence_sha256": self.TERMS_EVIDENCE_DIGEST,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "policy_valid_until": (self.NOW + timedelta(days=30)).isoformat(),
            "official_verification_route": "jra_result_verification",
            "official_verification_route_version": "jra-v1",
            "official_verification_valid_until": (
                self.NOW + timedelta(days=30)
            ).isoformat(),
            "events": events or [self._event_entry(self.event)],
        }

    def _write_manifest(self, payload):
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _call(self, path, digest, *extra):
        stdout = StringIO()
        with patch(
            "stable.services.race_live_initialization.timezone.now",
            return_value=self.NOW,
        ):
            call_command(
                "initialize_race_live_events",
                "--manifest",
                str(path),
                "--expected-manifest-sha256",
                digest,
                "--expected-approved-commit",
                self.APPROVED_COMMIT,
                *extra,
                stdout=stdout,
            )
        return json.loads(stdout.getvalue())

    def _assert_no_initialized_rows(self):
        for model in (
            stable_models.RaceEventProjectionControl,
            stable_models.RaceEventLiveTracking,
            stable_models.RaceLiveHostBudget,
            stable_models.RaceResultSourceIdentity,
            stable_models.RaceLivePublicationPolicy,
            stable_models.RaceLiveEventPublicationAllowlist,
            stable_models.RaceEventParticipant,
            stable_models.RaceEventParticipantSourceIdentity,
            stable_models.RaceEventRevision,
            stable_models.RaceEventRevisionItem,
            stable_models.OperationLog,
        ):
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_default_dry_run_validates_exact_manifest_and_writes_nothing(self):
        path, digest = self._write_manifest(self._manifest())

        result = self._call(path, digest)

        self.assertEqual(result["mode"], "dry_run")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["manifest_sha256"], digest)
        self.assertEqual(result["event_ids"], [self.event.pk])
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["participant_count"], 2)
        self._assert_no_initialized_rows()

    def test_apply_requires_confirmation_creates_shadow_baseline_and_verify_passes(self):
        path, digest = self._write_manifest(self._manifest())

        with self.assertRaises(CommandError):
            self._call(path, digest, "--apply")
        self._assert_no_initialized_rows()

        applied = self._call(path, digest, "--apply", "--confirm-apply")
        self.assertEqual(applied["mode"], "apply")
        self.assertIs(applied["ok"], True)

        control = stable_models.RaceEventProjectionControl.objects.get(
            event=self.event
        )
        self.assertEqual(
            control.write_owner,
            stable_models.RaceEventProjectionWriteOwner.LIVE,
        )
        self.assertEqual(control.owner_generation, 1)
        self.assertEqual(control.owner_manifest_sha256, digest)
        self.assertEqual(control.next_racecard_revision_no, 2)
        self.assertEqual(
            control.current_racecard_revision_id,
            control.last_known_good_racecard_revision_id,
        )
        self.assertIsNone(control.current_result_revision_id)

        tracking = stable_models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertTrue(tracking.tracking_enabled)
        self.assertEqual(
            tracking.state,
            stable_models.RaceEventLiveState.RACECARD_READY,
        )
        self.assertEqual(tracking.active_attempt_token, "")
        self.assertEqual(tracking.claim_generation, 0)
        self.assertIn(digest, tracking.selection_reason)

        source = stable_models.RaceResultSourceIdentity.objects.get(event=self.event)
        self.assertEqual(source.source_key, "the_racing_api")
        self.assertEqual(
            source.result_authority,
            stable_models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        self.assertEqual(
            source.review_status,
            stable_models.RaceLiveReviewStatus.APPROVED,
        )
        self.assertEqual(
            source.terms_status,
            stable_models.RaceSourceTermsStatus.APPROVED,
        )
        self.assertTrue(source.automation_allowed)
        self.assertFalse(source.proof_network_allowed)
        self.assertEqual(source.registry_digest, self.REGISTRY_DIGEST)

        self.assertEqual(stable_models.RaceEventParticipant.objects.count(), 2)
        self.assertEqual(
            stable_models.RaceEventParticipantSourceIdentity.objects.count(),
            2,
        )
        racecard = stable_models.RaceEventRevision.objects.get()
        self.assertEqual(racecard.kind, stable_models.RaceEventRevisionKind.RACECARD)
        self.assertEqual(racecard.phase, stable_models.RaceResultPhase.RACECARD)
        self.assertEqual(
            racecard.source_authority,
            stable_models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        self.assertIsNone(racecard.published_at)
        self.assertEqual(racecard.items.count(), 2)

        policies = stable_models.RaceLivePublicationPolicy.objects.all()
        self.assertEqual(policies.count(), 4)
        self.assertEqual(
            set(policies.values_list("mode", flat=True)),
            {stable_models.RaceLivePublicationMode.SHADOW},
        )
        allowlist = stable_models.RaceLiveEventPublicationAllowlist.objects.get()
        self.assertTrue(allowlist.enabled)
        self.assertEqual(
            allowlist.max_mode,
            stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        )
        self.assertEqual(
            stable_models.RaceLiveHostBudget.objects.get().min_interval_ms,
            1050,
        )
        self.assertEqual(
            stable_models.OperationLog.objects.filter(
                action_type="race_live_event_initialized",
                target_id=str(self.event.pk),
            ).count(),
            1,
        )
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.assertEqual(
            stable_models.RaceEventRevisionPublication.objects.count(),
            0,
        )

        verified = self._call(path, digest, "--verify")
        self.assertEqual(verified["mode"], "verify")
        self.assertIs(verified["ok"], True)
        self.assertEqual(verified["error_count"], 0)

    def test_digest_commit_and_event_baseline_drift_fail_before_writes(self):
        path, digest = self._write_manifest(self._manifest())

        with self.assertRaises(CommandError):
            self._call(path, "0" * 64)
        self._assert_no_initialized_rows()

        with self.assertRaises(CommandError):
            with patch(
                "stable.services.race_live_initialization.timezone.now",
                return_value=self.NOW,
            ):
                call_command(
                    "initialize_race_live_events",
                    "--manifest",
                    str(path),
                    "--expected-manifest-sha256",
                    digest,
                    "--expected-approved-commit",
                    "e" * 40,
                )
        self._assert_no_initialized_rows()

        self.event.notes = "baseline drift"
        self.event.save(update_fields=("notes", "updated_at"))
        with self.assertRaises(CommandError):
            self._call(path, digest, "--apply", "--confirm-apply")
        self._assert_no_initialized_rows()

    def test_unknown_keys_and_duplicate_participant_identities_fail_closed(self):
        manifest = self._manifest()
        manifest["unexpected"] = True
        path, digest = self._write_manifest(manifest)
        with self.assertRaises(CommandError):
            self._call(path, digest)
        self._assert_no_initialized_rows()

        manifest = self._manifest()
        manifest["events"][0]["participants"][1]["external_runner_id"] = (
            manifest["events"][0]["participants"][0]["external_runner_id"]
        )
        path, digest = self._write_manifest(manifest)
        with self.assertRaises(CommandError):
            self._call(path, digest)
        self._assert_no_initialized_rows()

    def test_future_manifest_and_manual_projection_locks_fail_closed(self):
        future = self._manifest()
        future["generated_at"] = (self.NOW + timedelta(days=1)).isoformat()
        future["policy_valid_until"] = (
            self.NOW + timedelta(days=31)
        ).isoformat()
        future["official_verification_valid_until"] = (
            self.NOW + timedelta(days=31)
        ).isoformat()
        path, digest = self._write_manifest(future)
        with self.assertRaises(CommandError):
            self._call(path, digest)
        self._assert_no_initialized_rows()

        self.event.manual_lock_flags = {"runners": True}
        self.event.save(update_fields=("manual_lock_flags", "updated_at"))
        path, digest = self._write_manifest(self._manifest())
        with self.assertRaises(CommandError):
            self._call(path, digest)
        self._assert_no_initialized_rows()

    def test_multi_event_apply_is_atomic_and_exact_replay_is_idempotent(self):
        second = self._event("race-live-init-2", "Second Initialization Stakes")
        events = [
            self._event_entry(self.event),
            self._event_entry(second, suffix="2"),
        ]
        path, digest = self._write_manifest(self._manifest(events=events))
        stable_models.RaceEventProjectionControl.objects.create(event=second)

        with self.assertRaises(CommandError):
            self._call(path, digest, "--apply", "--confirm-apply")
        self.assertFalse(
            stable_models.RaceEventProjectionControl.objects.filter(
                event=self.event
            ).exists()
        )
        self.assertEqual(stable_models.RaceEventLiveTracking.objects.count(), 0)
        self.assertEqual(stable_models.RaceLivePublicationPolicy.objects.count(), 0)
        self.assertEqual(stable_models.OperationLog.objects.count(), 0)

        stable_models.RaceEventProjectionControl.objects.filter(event=second).delete()
        first = self._call(path, digest, "--apply", "--confirm-apply")
        before = {
            model.__name__: model.objects.count()
            for model in (
                stable_models.RaceEventProjectionControl,
                stable_models.RaceEventLiveTracking,
                stable_models.RaceResultSourceIdentity,
                stable_models.RaceEventParticipant,
                stable_models.RaceEventRevision,
                stable_models.RaceEventRevisionItem,
                stable_models.OperationLog,
            )
        }
        replay = self._call(path, digest, "--apply", "--confirm-apply")
        after = {
            model.__name__: model.objects.count()
            for model in (
                stable_models.RaceEventProjectionControl,
                stable_models.RaceEventLiveTracking,
                stable_models.RaceResultSourceIdentity,
                stable_models.RaceEventParticipant,
                stable_models.RaceEventRevision,
                stable_models.RaceEventRevisionItem,
                stable_models.OperationLog,
            )
        }

        self.assertTrue(first["ok"])
        self.assertTrue(replay["ok"])
        self.assertEqual(replay["replayed_event_count"], 2)
        self.assertEqual(after, before)
