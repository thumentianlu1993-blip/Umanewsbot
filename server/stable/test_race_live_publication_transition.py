from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from stable import models
from stable.services import race_events
from stable.services.race_live_publication_transition import (
    LoadedRaceLivePublicationTransition,
    RaceLivePublicationTransitionError,
    _canonical_bytes,
    apply_race_live_publication_transition,
    build_race_live_publication_transition_bundle,
    dry_run_race_live_publication_transition,
    load_race_live_publication_transition_manifest,
    prepare_race_live_publication_transition_bundle,
    verify_race_live_publication_transition,
)


class RaceLivePublicationTransitionTests(TestCase):
    NOW = datetime(2026, 7, 20, 14, 30, tzinfo=dt_timezone.utc)
    APPROVED_COMMIT = "a" * 40
    REGISTRY_DIGEST = "b" * 64
    COVERAGE_DIGEST = "c" * 64

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            id=924,
            year=2026,
            slug="event-924-transition",
            original_name="Event 924 Transition Stakes",
            chinese_name="赛事 924 灰度测试",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Newbury",
            grade_text="G3",
            surface=models.RaceEventSurface.TURF,
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            race_datetime=self.NOW - timedelta(hours=3),
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=1,
            owner_manifest_sha256="d" * 64,
            next_racecard_revision_no=2,
            next_result_revision_no=2,
        )
        self.tracking = models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=models.RaceEventLiveState.PROVISIONAL_RESULT,
            tracking_enabled=True,
            next_poll_at=self.NOW + timedelta(minutes=10),
            last_attempt_at=self.NOW - timedelta(minutes=16),
            last_success_at=self.NOW - timedelta(minutes=15),
            last_observation_hash="e" * 64,
            consecutive_failures=0,
            claim_generation=19,
            source_route_version="the_racing_api-free-v1",
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="rac_event_924",
            canonical_url="https://api.theracingapi.com/v1/results/rac_event_924",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            reviewed_at=self.NOW - timedelta(days=1),
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=self.NOW + timedelta(days=20),
            registry_digest=self.REGISTRY_DIGEST,
        )
        for scope_type, scope_key in (
            (models.RaceLivePublicationScopeType.GLOBAL, "global"),
            (
                models.RaceLivePublicationScopeType.REGION,
                self.event.country_region,
            ),
            (
                models.RaceLivePublicationScopeType.SOURCE,
                self.source.source_key,
            ),
            (models.RaceLivePublicationScopeType.EVENT, str(self.event.pk)),
        ):
            models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=(
                    models.RaceLivePublicationMode.SHADOW
                    if scope_type
                    == models.RaceLivePublicationScopeType.EVENT
                    else models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                ),
                version=1,
                registry_digest=self.REGISTRY_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                valid_until=self.NOW + timedelta(days=20),
            )
        self.allowlist = models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key=self.source.source_key,
            max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            official_verification_route="bha_manual_verification",
            official_verification_route_version="bha-manual-v1",
            official_verification_valid_until=self.NOW + timedelta(days=20),
            enabled=True,
            version=1,
        )
        self.participants = [
            models.RaceEventParticipant.objects.create(
                event=self.event,
                stable_key=f"event-924-runner-{index}",
                canonical_name=name,
                country_region=models.RacingRegion.UNITED_KINGDOM,
                review_status=models.RaceLiveReviewStatus.APPROVED,
            )
            for index, name in enumerate(
                (
                    "Winner",
                    "Runner-up",
                    "Third",
                    "Fourth",
                    "Fifth",
                    "Sixth",
                    "Seventh",
                ),
                start=1,
            )
        ]
        for index, participant in enumerate(self.participants, start=1):
            models.RaceEventParticipantSourceIdentity.objects.create(
                participant=participant,
                source_identity=self.source,
                external_runner_id=f"runner-{index}",
            )
        racecard = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256="f" * 64,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        for index, participant in enumerate(self.participants, start=1):
            models.RaceEventRevisionItem.objects.create(
                revision=racecard,
                participant=participant,
                source_order=index,
                internal_order=index,
                status=models.RaceEventRevisionItemStatus.DECLARED,
                horse_number=str(index),
                barrier=str(index + 2),
                jockey_name=f"Jockey {index}",
                trainer_name=f"Forbidden Trainer {index}",
                carried_weight=f"{120 + index}",
            )
        payload = {
            "external_race_id": self.source.external_race_id,
            "participants": [
                {
                    "external_runner_id": f"runner-{index}",
                    "official_finish_position": index,
                    "status": models.RaceEventRevisionItemStatus.FINISHED,
                }
                for index in range(1, len(self.participants) + 1)
            ],
        }
        normalized_sha = race_events.build_race_live_canonical_sha256(
            normalized_payload=payload
        )
        self.observation = models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW - timedelta(minutes=15),
            parser_version="the_racing_api_free_v1",
            raw_sha256="1" * 64,
            normalized_sha256=normalized_sha,
            result_phase=models.RaceResultPhase.PROVISIONAL,
            normalized_payload=payload,
            permission_classification="licensed_api_automation",
        )
        result = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256=normalized_sha,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            decision_reason="provisional_result_accepted",
            primary_observation=self.observation,
        )
        for index, participant in enumerate(self.participants, start=1):
            models.RaceEventRevisionItem.objects.create(
                revision=result,
                participant=participant,
                source_order=index,
                internal_order=index,
                official_finish_position=index,
                status=models.RaceEventRevisionItemStatus.FINISHED,
                horse_number=str(index),
            )
        self.control.current_racecard_revision = racecard
        self.control.last_known_good_racecard_revision = racecard
        self.control.current_result_revision = result
        self.control.last_known_good_result_revision = result
        self.control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "current_result_revision",
                "last_known_good_result_revision",
                "updated_at",
            )
        )
        self.result_revision = result

    def _bundle(self):
        return build_race_live_publication_transition_bundle(
            event_id=self.event.pk,
            approved_commit=self.APPROVED_COMMIT,
            generated_at=self.NOW,
        )

    def _loaded(self, payload):
        return LoadedRaceLivePublicationTransition(
            path=Path("/not-used"),
            sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
            payload=payload,
        )

    def _provider_snapshot(self):
        return models.RaceEventLiveTracking.objects.values(
            "claim_generation",
            "active_attempt_token",
            "claim_expires_at",
            "last_attempt_at",
            "last_success_at",
            "last_observation_hash",
            "consecutive_failures",
            "stale_at",
        ).get(pk=self.tracking.pk)

    def _create_unrelated_live_event(self):
        event = models.RaceEvent.objects.create(
            id=925,
            year=2026,
            slug="unrelated-event-925",
            original_name="Unrelated Event 925",
            chinese_name="无关赛事 925",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G2",
            surface=models.RaceEventSurface.TURF,
            race_datetime=self.NOW + timedelta(days=1),
        )
        models.RaceEventProjectionControl.objects.create(event=event)
        tracking = models.RaceEventLiveTracking.objects.create(
            event=event,
            state=models.RaceEventLiveState.RACECARD_READY,
            tracking_enabled=True,
            next_poll_at=self.NOW + timedelta(hours=1),
        )
        models.RaceLivePublicationPolicy.objects.create(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event.pk),
            mode=models.RaceLivePublicationMode.SHADOW,
            version=1,
            registry_digest=self.REGISTRY_DIGEST,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            valid_until=self.NOW + timedelta(days=20),
        )
        models.RaceLiveEventPublicationAllowlist.objects.create(
            event=event,
            source_key="the_racing_api",
            max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            official_verification_route="france_galop_manual_verification",
            official_verification_route_version="france-galop-manual-v1",
            official_verification_valid_until=self.NOW + timedelta(days=20),
            enabled=True,
        )
        return event, tracking

    def test_event_promotion_preserves_an_unrelated_live_event(self):
        unrelated_event, unrelated_tracking = (
            self._create_unrelated_live_event()
        )
        before = {
            "tracking": models.RaceEventLiveTracking.objects.values().get(
                pk=unrelated_tracking.pk
            ),
            "allowlist": models.RaceLiveEventPublicationAllowlist.objects.values().get(
                event=unrelated_event
            ),
            "policy": models.RaceLivePublicationPolicy.objects.values().get(
                scope_type=models.RaceLivePublicationScopeType.EVENT,
                scope_key=str(unrelated_event.pk),
            ),
        }
        manifest = self._loaded(self._bundle()["promotion"])

        apply_race_live_publication_transition(manifest, now=self.NOW)

        after = {
            "tracking": models.RaceEventLiveTracking.objects.values().get(
                pk=unrelated_tracking.pk
            ),
            "allowlist": models.RaceLiveEventPublicationAllowlist.objects.values().get(
                event=unrelated_event
            ),
            "policy": models.RaceLivePublicationPolicy.objects.values().get(
                scope_type=models.RaceLivePublicationScopeType.EVENT,
                scope_key=str(unrelated_event.pk),
            ),
        }
        self.assertEqual(after, before)

    def test_unrelated_scope_drift_invalidates_prepared_event_manifest(self):
        _, unrelated_tracking = self._create_unrelated_live_event()
        manifest = self._loaded(self._bundle()["promotion"])
        models.RaceEventLiveTracking.objects.filter(
            pk=unrelated_tracking.pk
        ).update(next_poll_at=self.NOW + timedelta(hours=2))

        with self.assertRaises(RaceLivePublicationTransitionError):
            dry_run_race_live_publication_transition(manifest)

    def test_promotion_uses_persisted_shadow_without_claim_network_or_provider_timing_mutation(self):
        bundle = self._bundle()
        manifest = self._loaded(bundle["promotion"])
        provider_before = self._provider_snapshot()

        dry_run = dry_run_race_live_publication_transition(manifest)
        applied = apply_race_live_publication_transition(
            manifest,
            now=self.NOW,
        )

        self.assertTrue(dry_run["ok"])
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["network_request_count"], 0)
        self.assertEqual(self._provider_snapshot(), provider_before)
        self.tracking.refresh_from_db()
        self.assertFalse(self.tracking.tracking_enabled)
        self.assertIsNone(self.tracking.next_poll_at)
        self.assertEqual(self.tracking.provisional_published_at, self.NOW)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertIsNone(self.event.result_confirmed_at)
        self.result_revision.refresh_from_db()
        self.assertEqual(self.result_revision.published_at, self.NOW)
        policy_states = {
            row.scope_type: (row.mode, row.version)
            for row in models.RaceLivePublicationPolicy.objects.all()
        }
        self.assertEqual(
            policy_states[models.RaceLivePublicationScopeType.EVENT],
            (models.RaceLivePublicationMode.PROVISIONAL_PUBLIC, 2),
        )
        for broad_scope in (
            models.RaceLivePublicationScopeType.GLOBAL,
            models.RaceLivePublicationScopeType.REGION,
            models.RaceLivePublicationScopeType.SOURCE,
        ):
            self.assertEqual(
                policy_states[broad_scope],
                (models.RaceLivePublicationMode.PROVISIONAL_PUBLIC, 1),
            )
        self.allowlist.refresh_from_db()
        self.assertEqual(self.allowlist.version, 2)
        self.assertRegex(
            self.allowlist.official_verification_contract_digest,
            r"^[0-9a-f]{64}$",
        )
        incident = models.RaceLiveOfficialVerificationIncident.objects.get(
            event=self.event
        )
        self.assertEqual(
            incident.official_route_contract_digest,
            self.allowlist.official_verification_contract_digest,
        )
        self.assertEqual(
            incident.manual_verification_due_at,
            self.NOW + timedelta(minutes=15),
        )
        self.assertEqual(
            incident.deadline_at,
            self.event.race_datetime + timedelta(hours=2),
        )
        results = list(
            models.RaceEventResult.objects.filter(event=self.event).order_by(
                "finish_position"
            )
        )
        self.assertEqual(
            [row.horse_name for row in results],
            [
                "Winner",
                "Runner-up",
                "Third",
                "Fourth",
                "Fifth",
                "Sixth",
                "Seventh",
            ],
        )
        self.assertEqual(
            [row.barrier for row in results],
            ["3", "4", "5", "6", "7", "8", "9"],
        )
        self.assertEqual(
            [row.jockey_name for row in results],
            [
                "Jockey 1",
                "Jockey 2",
                "Jockey 3",
                "Jockey 4",
                "Jockey 5",
                "Jockey 6",
                "Jockey 7",
            ],
        )
        self.assertEqual([row.trainer_name for row in results], [""] * 7)
        self.assertEqual([row.carried_weight for row in results], [""] * 7)
        self.assertEqual(results[0].raw_payload, {})
        self.assertEqual(
            set(results[0].source_refs["field_provenance"]),
            {"barrier", "jockey_name"},
        )
        with patch("stable.views.timezone.now", return_value=self.NOW):
            detail = self.client.get(self.event.public_path)
            calendar = self.client.get(
                reverse("public-race-calendar"),
                {"tab": "all"},
            )
        self.assertContains(detail, "暂定赛果")
        self.assertContains(detail, "尚待官方来源复核")
        self.assertContains(detail, "补充来源")
        self.assertContains(detail, "冠军 · 暂定")
        for index, participant in enumerate(self.participants, start=1):
            self.assertContains(detail, participant.canonical_name)
            self.assertContains(detail, f"Jockey {index}")
            self.assertNotContains(detail, f"Forbidden Trainer {index}")
        self.assertNotContains(detail, "正式赛果")
        self.assertNotContains(detail, "更正赛果")
        self.assertContains(calendar, "Winner")
        verification = verify_race_live_publication_transition(
            manifest,
            now=self.NOW,
        )
        self.assertTrue(verification["ok"])
        self.assertEqual(verification["official_incident_status"], "open")
        self.assertTrue(verification["official_incident_overdue"])
        for minute in range(1, 11):
            replay = apply_race_live_publication_transition(
                manifest,
                now=self.NOW + timedelta(minutes=minute),
            )
            self.assertTrue(replay["replayed"])
        self.assertEqual(models.OperationLog.objects.count(), 1)

    def test_failure_rolls_back_policy_allowlist_publication_incident_and_tracking(self):
        manifest = self._loaded(self._bundle()["promotion"])
        provider_before = self._provider_snapshot()
        with patch(
            "stable.services.race_events._publish_race_result_revision",
            side_effect=IntegrityError("injected projection failure"),
        ):
            with self.assertRaises(IntegrityError):
                apply_race_live_publication_transition(
                    manifest,
                    now=self.NOW,
                )
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode", flat=True
                )
            ),
            {
                models.RaceLivePublicationMode.SHADOW,
                models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            },
        )
        self.allowlist.refresh_from_db()
        self.assertEqual(self.allowlist.version, 1)
        self.assertEqual(self.allowlist.official_verification_contract_digest, "")
        self.assertFalse(
            models.RaceEventRevisionPublication.objects.exists()
        )
        self.assertFalse(
            models.RaceLiveOfficialVerificationIncident.objects.exists()
        )
        self.assertEqual(self._provider_snapshot(), provider_before)

    def test_exact_pre_state_binds_event_manual_locks_participant_and_racecard_fallback(self):
        manifest = self._loaded(self._bundle()["promotion"])
        mutations = (
            (
                "event_identity",
                lambda: models.RaceEvent.objects.filter(pk=self.event.pk).update(
                    slug="event-924-drifted"
                ),
            ),
            (
                "manual_result_lock",
                lambda: models.RaceEvent.objects.filter(pk=self.event.pk).update(
                    manual_lock_flags={"results": True}
                ),
            ),
            (
                "owner_manifest",
                lambda: models.RaceEventProjectionControl.objects.filter(
                    pk=self.control.pk
                ).update(owner_manifest_sha256="9" * 64),
            ),
            (
                "observation_parser",
                lambda: models.RaceResultObservation.objects.filter(
                    pk=self.observation.pk
                ).update(parser_version="drifted-parser"),
            ),
            (
                "participant_review",
                lambda: models.RaceEventParticipant.objects.filter(
                    pk=self.participants[0].pk
                ).update(review_status=models.RaceLiveReviewStatus.PENDING),
            ),
            (
                "participant_source_identity",
                lambda: models.RaceEventParticipantSourceIdentity.objects.filter(
                    participant=self.participants[0],
                    source_identity=self.source,
                ).update(external_runner_id="drifted-runner"),
            ),
            (
                "racecard_fallback",
                lambda: models.RaceEventRevisionItem.objects.filter(
                    revision=self.control.current_racecard_revision,
                    participant=self.participants[0],
                ).update(jockey_name="Drifted Jockey"),
            ),
            (
                "source_review",
                lambda: models.RaceResultSourceIdentity.objects.filter(
                    pk=self.source.pk
                ).update(review_status=models.RaceLiveReviewStatus.PENDING),
            ),
            (
                "event_policy",
                lambda: models.RaceLivePublicationPolicy.objects.filter(
                    scope_type=models.RaceLivePublicationScopeType.EVENT,
                    scope_key=str(self.event.pk),
                ).update(version=9),
            ),
            (
                "allowlist",
                lambda: models.RaceLiveEventPublicationAllowlist.objects.filter(
                    pk=self.allowlist.pk
                ).update(enabled=False),
            ),
            (
                "legacy_result",
                lambda: models.RaceEventResult.objects.create(
                    event=self.event,
                    finish_position=1,
                    horse_name="Unexpected Legacy Result",
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), transaction.atomic():
                mutate()
                with self.assertRaises(RaceLivePublicationTransitionError):
                    dry_run_race_live_publication_transition(manifest)
                transaction.set_rollback(True)

        self.assertFalse(models.RaceEventRevisionPublication.objects.exists())

    def test_replay_fails_closed_when_unchanged_or_temporal_post_state_drifts(self):
        manifest = self._loaded(self._bundle()["promotion"])
        apply_race_live_publication_transition(manifest, now=self.NOW)
        self.tracking.refresh_from_db()
        self.tracking.provisional_published_at = self.NOW + timedelta(
            minutes=1
        )
        self.tracking.save(
            update_fields=("provisional_published_at", "updated_at")
        )

        with self.assertRaises(RaceLivePublicationTransitionError):
            apply_race_live_publication_transition(
                manifest,
                now=self.NOW + timedelta(minutes=2),
            )

    def test_cancelled_or_postponed_event_cannot_prepare_promotion(self):
        for status in (
            models.RaceEventStatus.CANCELLED,
            models.RaceEventStatus.POSTPONED,
        ):
            with self.subTest(status=status), transaction.atomic():
                models.RaceEvent.objects.filter(pk=self.event.pk).update(
                    status=status
                )
                with self.assertRaises(RaceLivePublicationTransitionError):
                    self._bundle()
                transaction.set_rollback(True)

    def test_disable_and_restore_only_change_event_policy_and_preserve_audit_facts(self):
        bundle = self._bundle()
        apply_race_live_publication_transition(
            self._loaded(bundle["promotion"]),
            now=self.NOW,
        )
        counts = (
            models.RaceEventRevisionPublication.objects.count(),
            models.RaceEventResult.objects.count(),
            models.RaceLiveOfficialVerificationIncident.objects.count(),
        )

        disable = self._loaded(bundle["disable"])
        self.assertTrue(
            dry_run_race_live_publication_transition(disable)["ok"]
        )
        self.assertTrue(
            apply_race_live_publication_transition(
                disable,
                now=self.NOW + timedelta(minutes=1),
            )["ok"]
        )
        event_policy = models.RaceLivePublicationPolicy.objects.get(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(self.event.pk),
        )
        self.assertEqual(event_policy.mode, models.RaceLivePublicationMode.SHADOW)
        self.assertEqual(event_policy.version, 3)
        self.assertFalse(
            race_events.resolve_race_live_public_read(
                event_id=self.event.pk,
                now=self.NOW + timedelta(minutes=1),
            ).visible
        )
        self.assertEqual(
            (
                models.RaceEventRevisionPublication.objects.count(),
                models.RaceEventResult.objects.count(),
                models.RaceLiveOfficialVerificationIncident.objects.count(),
            ),
            counts,
        )

        restore = self._loaded(bundle["restore"])
        self.assertTrue(
            dry_run_race_live_publication_transition(restore)["ok"]
        )
        self.assertTrue(
            apply_race_live_publication_transition(
                restore,
                now=self.NOW + timedelta(minutes=2),
            )["ok"]
        )
        event_policy.refresh_from_db()
        self.assertEqual(
            event_policy.mode,
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        )
        self.assertEqual(event_policy.version, 4)
        self.assertTrue(
            race_events.resolve_race_live_public_read(
                event_id=self.event.pk,
                now=self.NOW + timedelta(minutes=2),
            ).visible
        )

    def test_prepare_is_exclusive_0700_0600_and_loader_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            result = prepare_race_live_publication_transition_bundle(
                event_id=self.event.pk,
                approved_commit=self.APPROVED_COMMIT,
                run_id="event-924",
                output_root=root,
                generated_at=self.NOW,
            )
            output_dir = Path(result["output_dir"])
            self.assertEqual(output_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                {path.stat().st_mode & 0o777 for path in output_dir.iterdir()},
                {0o600},
            )
            promotion = output_dir / "promotion.manifest.json"
            digest = hashlib.sha256(promotion.read_bytes()).hexdigest()
            loaded = load_race_live_publication_transition_manifest(
                manifest_path=promotion,
                expected_manifest_sha256=digest,
                expected_approved_commit=self.APPROVED_COMMIT,
            )
            self.assertTrue(
                dry_run_race_live_publication_transition(loaded)["ok"]
            )
            os.chmod(promotion, 0o644)
            with self.assertRaises(RaceLivePublicationTransitionError):
                load_race_live_publication_transition_manifest(
                    manifest_path=promotion,
                    expected_manifest_sha256=digest,
                    expected_approved_commit=self.APPROVED_COMMIT,
                )
            os.chmod(promotion, 0o600)
            with self.assertRaises(RaceLivePublicationTransitionError):
                load_race_live_publication_transition_manifest(
                    manifest_path=output_dir,
                    expected_manifest_sha256=digest,
                    expected_approved_commit=self.APPROVED_COMMIT,
                )
            with self.assertRaises(RaceLivePublicationTransitionError):
                prepare_race_live_publication_transition_bundle(
                    event_id=self.event.pk,
                    approved_commit=self.APPROVED_COMMIT,
                    run_id="event-924",
                    output_root=root,
                    generated_at=self.NOW,
                )
            with self.assertRaises(RaceLivePublicationTransitionError):
                prepare_race_live_publication_transition_bundle(
                    event_id=self.event.pk,
                    approved_commit=self.APPROVED_COMMIT,
                    run_id="../invalid-run",
                    output_root=root,
                    generated_at=self.NOW,
                )
            real_root = root / "real-root"
            real_root.mkdir(mode=0o700)
            symlink_root = root / "root-link"
            symlink_root.symlink_to(real_root, target_is_directory=True)
            with self.assertRaises(RaceLivePublicationTransitionError):
                prepare_race_live_publication_transition_bundle(
                    event_id=self.event.pk,
                    approved_commit=self.APPROVED_COMMIT,
                    run_id="symlink-root-rejected",
                    output_root=symlink_root,
                    generated_at=self.NOW,
                )
            symlink = root / "manifest-link.json"
            symlink.symlink_to(promotion)
            with self.assertRaises(RaceLivePublicationTransitionError):
                load_race_live_publication_transition_manifest(
                    manifest_path=symlink,
                    expected_manifest_sha256=digest,
                    expected_approved_commit=self.APPROVED_COMMIT,
                )

    def test_management_command_defaults_to_dry_run_and_apply_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            prepared = prepare_race_live_publication_transition_bundle(
                event_id=self.event.pk,
                approved_commit=self.APPROVED_COMMIT,
                run_id="event-924-command",
                output_root=root,
                generated_at=self.NOW,
            )
            path = Path(prepared["output_dir"]) / "promotion.manifest.json"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stdout = StringIO()
            call_command(
                "transition_race_live_publication",
                "--manifest",
                str(path),
                "--expected-manifest-sha256",
                digest,
                "--expected-approved-commit",
                self.APPROVED_COMMIT,
                stdout=stdout,
            )
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["mode"], "dry_run")
            self.assertFalse(
                models.RaceEventRevisionPublication.objects.exists()
            )
            self.assertNotIn("test-password", stdout.getvalue())
            self.assertNotIn("active_attempt_token", stdout.getvalue())
            with self.assertRaises(CommandError):
                call_command(
                    "transition_race_live_publication",
                    "--manifest",
                    str(path),
                    "--expected-manifest-sha256",
                    digest,
                    "--expected-approved-commit",
                    self.APPROVED_COMMIT,
                    "--apply",
                )
            for conflicting_options in (
                ("--confirm-apply",),
                ("--apply", "--verify"),
            ):
                with self.assertRaises(CommandError):
                    call_command(
                        "transition_race_live_publication",
                        "--manifest",
                        str(path),
                        "--expected-manifest-sha256",
                        digest,
                        "--expected-approved-commit",
                        self.APPROVED_COMMIT,
                        *conflicting_options,
                    )

    def test_manifest_loader_rejects_schema_digest_commit_and_target_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            payload = self._bundle()["promotion"]
            variants = {}

            unknown = deepcopy(payload)
            unknown["unexpected"] = True
            variants["unknown-field"] = unknown

            duplicate_scope = deepcopy(payload)
            duplicate_scope["expected"]["policies"][-1][
                "scope_type"
            ] = models.RaceLivePublicationScopeType.GLOBAL
            duplicate_scope["expected"]["policies"][-1][
                "scope_key"
            ] = "global"
            variants["duplicate-scope"] = duplicate_scope

            naive_time = deepcopy(payload)
            naive_time["generated_at"] = "2026-07-20T14:30:00"
            variants["naive-time"] = naive_time

            target_drift = deepcopy(payload)
            target_drift["target"]["policies"][0]["version"] += 10
            variants["target-drift"] = target_drift

            for label, variant in variants.items():
                with self.subTest(label=label):
                    path = root / f"{label}.json"
                    data = _canonical_bytes(variant) + b"\n"
                    path.write_bytes(data)
                    os.chmod(path, 0o600)
                    with self.assertRaises(
                        RaceLivePublicationTransitionError
                    ):
                        load_race_live_publication_transition_manifest(
                            manifest_path=path,
                            expected_manifest_sha256=hashlib.sha256(
                                data
                            ).hexdigest(),
                            expected_approved_commit=self.APPROVED_COMMIT,
                        )

            valid_path = root / "valid.json"
            valid_data = _canonical_bytes(payload) + b"\n"
            valid_path.write_bytes(valid_data)
            os.chmod(valid_path, 0o600)
            valid_digest = hashlib.sha256(valid_data).hexdigest()
            with self.assertRaises(RaceLivePublicationTransitionError):
                load_race_live_publication_transition_manifest(
                    manifest_path=valid_path,
                    expected_manifest_sha256="0" * 64,
                    expected_approved_commit=self.APPROVED_COMMIT,
                )
            with self.assertRaises(RaceLivePublicationTransitionError):
                load_race_live_publication_transition_manifest(
                    manifest_path=valid_path,
                    expected_manifest_sha256=valid_digest,
                    expected_approved_commit="b" * 40,
                )

    @override_settings(RACE_LIVE_SCHEDULER_ENABLED=True)
    def test_scheduler_blocks_operator_promotion_before_write(self):
        manifest = self._loaded(self._bundle()["promotion"])
        with self.assertRaises(RaceLivePublicationTransitionError):
            apply_race_live_publication_transition(manifest, now=self.NOW)
        self.assertFalse(models.RaceEventRevisionPublication.objects.exists())

    def test_active_claim_blocks_operator_promotion_before_write(self):
        manifest = self._loaded(self._bundle()["promotion"])
        self.tracking.active_attempt_token = "runner-claim"
        self.tracking.claim_expires_at = self.NOW + timedelta(minutes=5)
        self.tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_expires_at",
                "updated_at",
            )
        )

        with self.assertRaises(RaceLivePublicationTransitionError):
            apply_race_live_publication_transition(manifest, now=self.NOW)

        self.assertFalse(models.RaceEventRevisionPublication.objects.exists())
        self.assertFalse(
            models.RaceLiveOfficialVerificationIncident.objects.exists()
        )
