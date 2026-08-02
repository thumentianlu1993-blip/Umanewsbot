from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from stable import models as stable_models
from stable import admin as stable_admin
from stable import tasks as stable_tasks
from stable.services import race_events


class RaceLiveModeResolutionTests(SimpleTestCase):
    def _resolve(self, **overrides):
        resolver = getattr(race_events, "resolve_race_live_mode", None)
        self.assertTrue(
            callable(resolver),
            "准实时发布 mode resolver 尚未实现",
        )
        values = {
            "global_mode": "official_public",
            "region_mode": None,
            "source_mode": None,
            "event_mode": None,
            "terms_mode": "official_public",
            "event_allowed": True,
        }
        values.update(overrides)
        return resolver(**values)

    def test_any_explicit_off_is_a_hard_gate_that_event_cannot_raise(self):
        for gate in ("global_mode", "region_mode", "source_mode"):
            with self.subTest(gate=gate):
                self.assertEqual(
                    self._resolve(**{gate: "off", "event_mode": "official_public"}),
                    "off",
                )

    def test_each_configured_layer_can_only_lower_the_effective_mode(self):
        self.assertEqual(
            self._resolve(
                global_mode="official_public",
                region_mode="provisional_public",
                source_mode="official_public",
                event_mode="official_public",
                terms_mode="official_public",
            ),
            "provisional_public",
        )
        self.assertEqual(
            self._resolve(
                global_mode="official_public",
                region_mode="official_public",
                source_mode="official_public",
                event_mode="provisional_public",
                terms_mode="shadow",
            ),
            "shadow",
        )

    def test_missing_children_inherit_but_missing_or_invalid_global_fails_closed(self):
        self.assertEqual(self._resolve(global_mode="shadow"), "shadow")
        self.assertEqual(self._resolve(global_mode=None), "off")
        self.assertEqual(self._resolve(global_mode="unexpected"), "off")
        self.assertEqual(self._resolve(source_mode="unexpected"), "off")

    def test_missing_terms_permission_fails_closed_instead_of_inheriting(self):
        self.assertEqual(
            self._resolve(global_mode="official_public", terms_mode=None),
            "off",
        )

    def test_event_allowlist_can_reject_but_never_raise_mode(self):
        self.assertEqual(
            self._resolve(global_mode="official_public", event_allowed=False),
            "off",
        )
        self.assertEqual(
            self._resolve(global_mode="shadow", event_mode="official_public"),
            "shadow",
        )

    def test_event_allowlist_requires_an_explicit_boolean_true(self):
        resolver = getattr(race_events, "resolve_race_live_mode", None)
        self.assertTrue(callable(resolver))
        self.assertEqual(
            resolver(
                global_mode="official_public",
                terms_mode="official_public",
            ),
            "off",
        )

        for event_allowed in (None, "false", "true", 0, 1):
            with self.subTest(event_allowed=event_allowed):
                self.assertEqual(
                    self._resolve(event_allowed=event_allowed),
                    "off",
                )

        self.assertEqual(self._resolve(event_allowed=True), "official_public")


class RaceLiveStateTransitionTests(SimpleTestCase):
    def _is_allowed(self, current_state, next_state):
        resolver = getattr(
            race_events,
            "is_race_live_state_transition_allowed",
            None,
        )
        self.assertTrue(
            callable(resolver),
            "准实时赛事状态转移纯函数尚未实现",
        )
        return resolver(current_state=current_state, next_state=next_state)

    def test_allows_only_the_approved_forward_transition_graph(self):
        allowed_transitions = {
            ("scheduled", "racecard_ready"),
            ("racecard_ready", "awaiting_result"),
            ("awaiting_result", "provisional_result"),
            ("awaiting_result", "official_result"),
            ("provisional_result", "official_result"),
            ("official_result", "corrected_result"),
            ("corrected_result", "corrected_result"),
        }

        for current_state, next_state in allowed_transitions:
            with self.subTest(current_state=current_state, next_state=next_state):
                self.assertTrue(self._is_allowed(current_state, next_state))

    def test_rejects_skips_backwards_unknown_and_unapproved_self_transitions(self):
        rejected_transitions = {
            ("scheduled", "provisional_result"),
            ("racecard_ready", "official_result"),
            ("official_result", "provisional_result"),
            ("scheduled", "scheduled"),
            ("unknown", "racecard_ready"),
            ("awaiting_result", "unknown"),
            (None, "scheduled"),
        }

        for current_state, next_state in rejected_transitions:
            with self.subTest(current_state=current_state, next_state=next_state):
                self.assertFalse(self._is_allowed(current_state, next_state))


class RaceResultConflictPolicyTests(SimpleTestCase):
    SHA_A = "a" * 64
    SHA_B = "b" * 64

    def _decide(self, **overrides):
        resolver = getattr(race_events, "decide_race_result_revision_action", None)
        self.assertTrue(callable(resolver), "赛果来源 authority/conflict policy 尚未实现")
        values = {
            "current_state": "awaiting_result",
            "current_phase": None,
            "current_content_sha256": "",
            "incoming_phase": "provisional",
            "incoming_content_sha256": self.SHA_A,
            "source_authority": "supplemental",
            "official_marker": False,
            "identity_valid": True,
            "payload_complete": True,
            "manual_lock_conflict": False,
        }
        values.update(overrides)
        return resolver(**values)

    def test_complete_supplemental_result_can_only_create_provisional(self):
        decision = self._decide()
        self.assertEqual(decision.action, "apply")
        self.assertEqual(decision.next_state, "provisional_result")
        self.assertEqual(decision.next_phase, "provisional")
        self.assertIs(decision.conflict, False)

        blocked = self._decide(incoming_phase="official", official_marker=True)
        self.assertEqual(blocked.action, "reject")
        self.assertEqual(blocked.reason, "official_authority_required")

    def test_official_can_confirm_or_replace_provisional_but_not_guess_correction(self):
        decision = self._decide(
            current_state="provisional_result",
            current_phase="provisional",
            current_content_sha256=self.SHA_A,
            incoming_phase="official",
            incoming_content_sha256=self.SHA_B,
            source_authority="official",
            official_marker=True,
        )
        self.assertEqual(decision.action, "apply")
        self.assertEqual(decision.next_state, "official_result")
        self.assertEqual(decision.reason, "official_result_accepted")

        conflict = self._decide(
            current_state="official_result",
            current_phase="official",
            current_content_sha256=self.SHA_A,
            incoming_phase="official",
            incoming_content_sha256=self.SHA_B,
            source_authority="official",
            official_marker=True,
        )
        self.assertEqual(conflict.action, "conflict")
        self.assertEqual(conflict.reason, "official_change_requires_correction")
        self.assertIs(conflict.conflict, True)

    def test_explicit_official_correction_advances_and_exact_replay_is_idempotent(self):
        correction = self._decide(
            current_state="official_result",
            current_phase="official",
            current_content_sha256=self.SHA_A,
            incoming_phase="corrected",
            incoming_content_sha256=self.SHA_B,
            source_authority="official",
            official_marker=True,
        )
        self.assertEqual(correction.action, "apply")
        self.assertEqual(correction.next_state, "corrected_result")
        self.assertEqual(correction.next_phase, "corrected")

        replay = self._decide(
            current_state="corrected_result",
            current_phase="corrected",
            current_content_sha256=self.SHA_B,
            incoming_phase="corrected",
            incoming_content_sha256=self.SHA_B,
            source_authority="official",
            official_marker=True,
        )
        self.assertEqual(replay.action, "replay")
        self.assertEqual(replay.reason, "content_replayed")

    def test_supplemental_disagreement_and_manual_lock_freeze_current_result(self):
        disagreement = self._decide(
            current_state="provisional_result",
            current_phase="provisional",
            current_content_sha256=self.SHA_A,
            incoming_content_sha256=self.SHA_B,
        )
        self.assertEqual(disagreement.action, "conflict")
        self.assertEqual(disagreement.reason, "supplemental_result_conflict")
        self.assertIs(disagreement.conflict, True)
        self.assertIsNone(disagreement.next_state)

        locked = self._decide(manual_lock_conflict=True)
        self.assertEqual(locked.action, "conflict")
        self.assertEqual(locked.reason, "manual_lock_conflict")

    def test_invalid_identity_incomplete_payload_marker_and_transition_fail_closed(self):
        cases = (
            ({"identity_valid": False}, "identity_invalid"),
            ({"payload_complete": False}, "payload_incomplete"),
            (
                {"source_authority": "official", "incoming_phase": "official"},
                "official_marker_required",
            ),
            (
                {
                    "incoming_phase": "corrected",
                    "source_authority": "official",
                    "official_marker": True,
                },
                "correction_requires_official_result",
            ),
            ({"source_authority": "unknown"}, "invalid_source_authority"),
            ({"incoming_content_sha256": "bad"}, "invalid_content_digest"),
        )
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                decision = self._decide(**overrides)
                self.assertEqual(decision.action, "reject")
                self.assertEqual(decision.reason, reason)


class RaceLiveCanonicalHashTests(SimpleTestCase):
    def _hash(self, normalized_payload, **metadata):
        builder = getattr(
            race_events,
            "build_race_live_canonical_sha256",
            None,
        )
        self.assertTrue(
            callable(builder),
            "准实时赛果 canonical hash 纯函数尚未实现",
        )
        return builder(normalized_payload=normalized_payload, **metadata)

    def test_mapping_key_order_does_not_change_the_canonical_hash(self):
        first = {
            "results": [
                {"participant_id": "horse-1", "status": "finished", "position": 1},
                {"participant_id": "horse-2", "status": "dead_heat", "position": 2},
            ],
            "distance_m": 1600,
        }
        reordered = {
            "distance_m": 1600,
            "results": [
                {"position": 1, "status": "finished", "participant_id": "horse-1"},
                {"status": "dead_heat", "participant_id": "horse-2", "position": 2},
            ],
        }

        digest = self._hash(first)
        self.assertEqual(digest, self._hash(reordered))
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_factual_or_internal_order_change_changes_the_hash(self):
        original = {
            "results": [
                {"participant_id": "horse-1", "position": 1},
                {"participant_id": "horse-2", "position": 2},
            ]
        }
        corrected = {
            "results": [
                {"participant_id": "horse-1", "position": 2},
                {"participant_id": "horse-2", "position": 1},
            ]
        }

        self.assertNotEqual(self._hash(original), self._hash(corrected))

    def test_equivalent_json_numbers_have_the_same_hash(self):
        self.assertEqual(
            self._hash({"position": 1, "margin": 0.0}),
            self._hash({"position": 1.0, "margin": -0.0}),
        )

    def test_revision_phase_metadata_does_not_change_content_hash(self):
        payload = {"results": [{"participant_id": "horse-1", "position": 1}]}
        expected = self._hash(payload)

        for result_phase in (
            "racecard",
            "provisional",
            "official",
            "corrected",
            "unknown",
        ):
            with self.subTest(result_phase=result_phase):
                self.assertEqual(
                    expected,
                    self._hash(payload, result_phase=result_phase),
                )

        with self.assertRaises(ValueError):
            self._hash(payload, result_phase="unexpected")

    def test_rejects_non_object_or_non_strict_json_payloads(self):
        invalid_payloads = (
            ["not", "an", "object"],
            {1: "non-string-key"},
            {"margin": float("nan")},
            {"status": {"not-json"}},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises((TypeError, ValueError)):
                    self._hash(payload)


class RaceEventProjectionControlModelTests(TestCase):
    def _model(self):
        model = getattr(stable_models, "RaceEventProjectionControl", None)
        self.assertIsNotNone(
            model,
            "RaceEventProjectionControl 模型尚未实现",
        )
        return model

    def _event(self, slug="projection-control-event"):
        return stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name="Projection Control Stakes",
            chinese_name="投影控制锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )

    def test_event_creation_does_not_implicitly_enable_projection_control(self):
        self._event()

        self.assertEqual(self._model().objects.count(), 0)

    def test_explicit_control_defaults_fail_closed_and_counters_start_at_one(self):
        event = self._event()
        control = self._model().objects.create(event=event)

        self.assertEqual(control.write_owner, "unmanaged")
        self.assertEqual(control.owner_generation, 0)
        self.assertEqual(control.owner_manifest_sha256, "")
        self.assertEqual(control.next_racecard_revision_no, 1)
        self.assertEqual(control.next_result_revision_no, 1)
        self.assertEqual(event.projection_control.pk, control.pk)

    def test_database_rejects_duplicate_event_and_unknown_owner(self):
        event = self._event()
        model = self._model()
        model.objects.create(event=event)

        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(event=event)

        other_event = self._event(slug="projection-control-invalid-owner")
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(event=other_event, write_owner="unexpected")

    def test_database_rejects_zero_revision_counters(self):
        model = self._model()

        for field_name in (
            "next_racecard_revision_no",
            "next_result_revision_no",
        ):
            with self.subTest(field_name=field_name):
                event = self._event(slug=f"projection-control-zero-{field_name}")
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.create(event=event, **{field_name: 0})


class RaceEventLiveTrackingModelTests(TestCase):
    def _model(self):
        model = getattr(stable_models, "RaceEventLiveTracking", None)
        self.assertIsNotNone(model, "RaceEventLiveTracking 模型尚未实现")
        return model

    def _event(self, slug="live-tracking-event"):
        return stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name="Live Tracking Stakes",
            chinese_name="准实时追踪锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )

    def test_event_creation_does_not_implicitly_enable_live_tracking(self):
        self._event()

        self.assertEqual(self._model().objects.count(), 0)

    def test_explicit_tracking_defaults_fail_closed(self):
        event = self._event()
        tracking = self._model().objects.create(event=event)

        self.assertEqual(tracking.state, "scheduled")
        self.assertIs(tracking.tracking_enabled, False)
        self.assertIsNone(tracking.next_poll_at)
        self.assertIsNone(tracking.window_started_at)
        self.assertIsNone(tracking.window_ends_at)
        self.assertIsNone(tracking.last_attempt_at)
        self.assertIsNone(tracking.last_success_at)
        self.assertEqual(tracking.last_observation_hash, "")
        self.assertEqual(tracking.consecutive_failures, 0)
        self.assertEqual(tracking.lock_version, 0)
        self.assertEqual(tracking.claim_generation, 0)
        self.assertEqual(tracking.active_attempt_token, "")
        self.assertIsNone(tracking.claim_expires_at)
        self.assertEqual(tracking.checkpoint_payload, {})
        self.assertEqual(event.live_tracking.pk, tracking.pk)

    def test_database_rejects_duplicate_event_and_unknown_state(self):
        event = self._event()
        model = self._model()
        model.objects.create(event=event)

        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(event=event)

        other_event = self._event(slug="live-tracking-invalid-state")
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(event=other_event, state="unexpected")


class RaceEventProjectionOwnerTransferTests(TestCase):
    def _event(self, slug="projection-owner-transfer"):
        return stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name="Projection Owner Transfer Stakes",
            chinese_name="投影所有权移交锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )

    def _transfer(self, **overrides):
        service = getattr(
            race_events,
            "transfer_race_event_projection_owner",
            None,
        )
        self.assertTrue(callable(service), "ProjectionControl owner transfer 服务尚未实现")
        values = {
            "event_id": self.event.pk,
            "expected_owner": "unmanaged",
            "expected_generation": 0,
            "new_owner": "historical",
            "manifest_sha256": "a" * 64,
        }
        values.update(overrides)
        return service(**values)

    def setUp(self):
        self.event = self._event()
        self.control = stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
        )

    def test_transfer_updates_owner_manifest_and_generation_once(self):
        transferred = self._transfer()

        self.control.refresh_from_db()
        self.assertEqual(transferred.pk, self.control.pk)
        self.assertEqual(self.control.write_owner, "historical")
        self.assertEqual(self.control.owner_generation, 1)
        self.assertEqual(self.control.owner_manifest_sha256, "a" * 64)
        self.assertIsNotNone(self.control.owner_changed_at)

    def test_exact_manifest_replay_is_idempotent(self):
        self._transfer()
        replayed = self._transfer()

        self.control.refresh_from_db()
        self.assertEqual(replayed.owner_generation, 1)
        self.assertEqual(self.control.owner_generation, 1)

    def test_stale_generation_or_different_manifest_fails_closed(self):
        self._transfer()
        conflict = getattr(
            race_events,
            "RaceEventProjectionOwnershipConflict",
            RuntimeError,
        )

        with self.assertRaises(conflict):
            self._transfer(new_owner="live", manifest_sha256="b" * 64)

        self.control.refresh_from_db()
        self.assertEqual(self.control.write_owner, "historical")
        self.assertEqual(self.control.owner_generation, 1)
        self.assertEqual(self.control.owner_manifest_sha256, "a" * 64)

    def test_missing_control_and_invalid_input_never_create_or_mutate_owner(self):
        conflict = getattr(
            race_events,
            "RaceEventProjectionOwnershipConflict",
            RuntimeError,
        )
        missing_event = self._event(slug="projection-owner-missing-control")

        with self.assertRaises(conflict):
            self._transfer(event_id=missing_event.pk)
        with self.assertRaises(ValueError):
            self._transfer(manifest_sha256="not-a-sha")
        with self.assertRaises(ValueError):
            self._transfer(new_owner="unexpected")

        self.control.refresh_from_db()
        self.assertEqual(self.control.write_owner, "unmanaged")
        self.assertEqual(self.control.owner_generation, 0)
        self.assertFalse(
            stable_models.RaceEventProjectionControl.objects.filter(
                event=missing_event,
            ).exists()
        )


class RaceLiveIdentityModelTests(TestCase):
    def _model(self, name):
        model = getattr(stable_models, name, None)
        self.assertIsNotNone(model, f"{name} 模型尚未实现")
        return model

    def _event(self, slug="race-live-identity"):
        return stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name="Race Live Identity Stakes",
            chinese_name="准实时身份锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )

    def _source(self, event, source_key="jra", external_race_id="race-2026-01"):
        return self._model("RaceResultSourceIdentity").objects.create(
            event=event,
            source_key=source_key,
            external_race_id=external_race_id,
        )

    def test_source_identity_defaults_terms_and_automation_fail_closed(self):
        source = self._source(self._event())

        self.assertEqual(source.review_status, "pending")
        self.assertEqual(source.terms_status, "unknown")
        self.assertIs(source.automation_allowed, False)
        self.assertIs(source.proof_network_allowed, False)
        self.assertEqual(source.result_authority, "supplemental")
        self.assertEqual(source.identity_fields, {})
        self.assertEqual(source.evidence_sha256, "")
        self.assertEqual(source.registry_digest, "")

    def test_source_identity_uniqueness_and_status_constraints(self):
        first_event = self._event()
        second_event = self._event(slug="race-live-identity-second")
        source_model = self._model("RaceResultSourceIdentity")
        self._source(first_event)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._source(second_event)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._source(first_event, external_race_id="another-race")
        with self.assertRaises(IntegrityError), transaction.atomic():
            source_model.objects.create(
                event=second_event,
                source_key="nar",
                external_race_id="nar-1",
                review_status="unexpected",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            source_model.objects.create(
                event=second_event,
                source_key="official-but-unreviewed",
                external_race_id="official-1",
                result_authority="official",
                review_status=stable_models.RaceLiveReviewStatus.PENDING,
            )

    def test_the_racing_api_is_database_constrained_to_supplemental_authority(self):
        source_model = self._model("RaceResultSourceIdentity")
        create_event = self._event(slug="race-live-tra-authority-create")

        with self.assertRaises(IntegrityError), transaction.atomic():
            source_model.objects.create(
                event=create_event,
                source_key="the_racing_api",
                external_race_id="tra-official-create",
                result_authority=stable_models.RaceResultSourceAuthority.OFFICIAL,
                review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            )

        update_event = self._event(slug="race-live-tra-authority-update")
        source = self._source(
            update_event,
            source_key="the_racing_api",
            external_race_id="tra-official-update",
        )
        source.review_status = stable_models.RaceLiveReviewStatus.APPROVED
        source.save(update_fields=("review_status", "updated_at"))

        with self.assertRaises(IntegrityError), transaction.atomic():
            source_model.objects.filter(pk=source.pk).update(
                result_authority=stable_models.RaceResultSourceAuthority.OFFICIAL,
            )

    def test_participant_stable_key_is_unique_per_event(self):
        event = self._event()
        participant_model = self._model("RaceEventParticipant")
        participant = participant_model.objects.create(
            event=event,
            stable_key="horse-1",
            canonical_name="Horse One",
        )

        self.assertEqual(participant.review_status, "pending")
        self.assertIsNone(participant.horse_profile_id)
        self.assertIsNone(participant.term_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            participant_model.objects.create(
                event=event,
                stable_key="horse-1",
                canonical_name="Different Horse",
            )

    def test_external_runner_id_is_unique_within_source_race_when_nonempty(self):
        event = self._event()
        source = self._source(event)
        participant_model = self._model("RaceEventParticipant")
        identity_model = self._model("RaceEventParticipantSourceIdentity")
        first = participant_model.objects.create(
            event=event,
            stable_key="horse-1",
            canonical_name="Horse One",
        )
        second = participant_model.objects.create(
            event=event,
            stable_key="horse-2",
            canonical_name="Horse Two",
        )
        identity_model.objects.create(
            participant=first,
            source_identity=source,
            external_runner_id="runner-1",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            identity_model.objects.create(
                participant=second,
                source_identity=source,
                external_runner_id="runner-1",
            )

        identity_model.objects.create(
            participant=second,
            source_identity=source,
            external_runner_id="",
        )


class RaceLivePublicationControlModelTests(TestCase):
    def _model(self, name):
        model = getattr(stable_models, name, None)
        self.assertIsNotNone(model, f"{name} 模型尚未实现")
        return model

    def _event(self, slug="race-live-publication-control"):
        return stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name="Race Live Publication Control Stakes",
            chinese_name="准实时发布控制锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )

    def test_publication_policy_defaults_off_and_scope_is_unique(self):
        policy_model = self._model("RaceLivePublicationPolicy")
        policy = policy_model.objects.create(
            scope_type="global",
            scope_key="global",
        )

        self.assertEqual(policy.mode, "off")
        self.assertEqual(policy.version, 1)
        self.assertEqual(policy.registry_digest, "")
        self.assertEqual(policy.coverage_proof_digest, "")
        self.assertIsNone(policy.valid_until)

        with self.assertRaises(IntegrityError), transaction.atomic():
            policy_model.objects.create(
                scope_type="global",
                scope_key="global",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            policy_model.objects.create(
                scope_type="unexpected",
                scope_key="bad-scope",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            policy_model.objects.create(
                scope_type="source",
                scope_key="the_racing_api",
                mode="unexpected",
            )

    def test_event_allowlist_defaults_disabled_and_is_unique_per_source(self):
        allowlist_model = self._model("RaceLiveEventPublicationAllowlist")
        event = self._event()
        allowlist = allowlist_model.objects.create(
            event=event,
            source_key="the_racing_api",
        )

        self.assertIs(allowlist.enabled, False)
        self.assertEqual(allowlist.max_mode, "off")
        self.assertEqual(allowlist.version, 1)
        self.assertEqual(allowlist.coverage_proof_digest, "")
        self.assertEqual(allowlist.official_verification_route, "")
        self.assertEqual(allowlist.official_verification_route_version, "")
        self.assertIsNone(allowlist.official_verification_valid_until)

        with self.assertRaises(IntegrityError), transaction.atomic():
            allowlist_model.objects.create(
                event=event,
                source_key="the_racing_api",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            allowlist_model.objects.create(
                event=self._event(slug="race-live-publication-invalid"),
                source_key="the_racing_api",
                max_mode="unexpected",
            )


class RaceLivePublicationPolicyResolutionTests(TestCase):
    NOW = datetime(2026, 7, 20, 6, 0, tzinfo=dt_timezone.utc)
    REGISTRY_DIGEST = "a" * 64
    COVERAGE_DIGEST = "b" * 64

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="race-live-publication-policy",
            original_name="Race Live Publication Policy Stakes",
            chinese_name="准实时发布策略锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="tra-policy-race",
            review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            terms_status=stable_models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=self.NOW + timedelta(days=30),
            registry_digest=self.REGISTRY_DIGEST,
        )
        self.allowlist = stable_models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key=self.source.source_key,
            max_mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            official_verification_route="jra_result_verification",
            official_verification_route_version="jra-v1",
            official_verification_contract_digest="c" * 64,
            official_terms_evidence_digest="d" * 64,
            official_verification_valid_until=self.NOW + timedelta(days=30),
            enabled=True,
        )

    def _resolve(self):
        resolver = getattr(
            race_events,
            "resolve_race_live_publication_policy",
            None,
        )
        self.assertTrue(callable(resolver), "持久化 publication policy resolver 尚未实现")
        return resolver(
            event_id=self.event.pk,
            source_identity_id=self.source.pk,
            now=self.NOW,
        )

    def test_missing_global_policy_fails_closed(self):
        decision = self._resolve()

        self.assertIs(decision.allowed, False)
        self.assertEqual(decision.effective_mode, "off")
        self.assertEqual(decision.reason, "global_policy_missing")

    def test_missing_event_policy_fails_closed_even_when_shared_caps_are_public(self):
        for scope_type, scope_key in (
            (stable_models.RaceLivePublicationScopeType.GLOBAL, "global"),
            (
                stable_models.RaceLivePublicationScopeType.REGION,
                self.event.country_region,
            ),
            (
                stable_models.RaceLivePublicationScopeType.SOURCE,
                self.source.source_key,
            ),
        ):
            stable_models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                registry_digest=self.REGISTRY_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                valid_until=self.NOW + timedelta(days=30),
            )

        decision = self._resolve()

        self.assertIs(decision.allowed, False)
        self.assertEqual(decision.effective_mode, "off")
        self.assertEqual(decision.reason, "event_policy_missing")

    def test_caps_terms_digests_allowlist_route_and_expiry_are_all_monotonic_gates(self):
        stable_models.RaceLivePublicationPolicy.objects.create(
            scope_type="global",
            scope_key="global",
            mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            registry_digest=self.REGISTRY_DIGEST,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            valid_until=self.NOW + timedelta(days=30),
        )
        source_policy = stable_models.RaceLivePublicationPolicy.objects.create(
            scope_type="source",
            scope_key=self.source.source_key,
            mode=stable_models.RaceLivePublicationMode.OFF,
            registry_digest=self.REGISTRY_DIGEST,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            valid_until=self.NOW + timedelta(days=30),
        )
        for scope_type, scope_key in (
            ("region", self.event.country_region),
            ("event", str(self.event.pk)),
        ):
            stable_models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                registry_digest=self.REGISTRY_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                valid_until=self.NOW + timedelta(days=30),
            )

        self.assertEqual(self._resolve().reason, "policy_off")

        source_policy.mode = stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        source_policy.registry_digest = "c" * 64
        source_policy.version += 1
        source_policy.save(
            update_fields=("mode", "registry_digest", "version", "updated_at")
        )
        self.assertEqual(self._resolve().reason, "registry_digest_mismatch")

        source_policy.registry_digest = self.REGISTRY_DIGEST
        source_policy.coverage_proof_digest = "d" * 64
        source_policy.version += 1
        source_policy.save(
            update_fields=(
                "registry_digest",
                "coverage_proof_digest",
                "version",
                "updated_at",
            )
        )
        self.assertEqual(self._resolve().reason, "coverage_digest_mismatch")

        source_policy.coverage_proof_digest = self.COVERAGE_DIGEST
        source_policy.valid_until = self.NOW
        source_policy.version += 1
        source_policy.save(
            update_fields=(
                "coverage_proof_digest",
                "valid_until",
                "version",
                "updated_at",
            )
        )
        self.assertEqual(self._resolve().reason, "policy_expired")

        source_policy.valid_until = self.NOW + timedelta(days=30)
        source_policy.version += 1
        source_policy.save(update_fields=("valid_until", "version", "updated_at"))
        decision = self._resolve()
        self.assertIs(decision.allowed, True)
        self.assertEqual(decision.effective_mode, "provisional_public")
        self.assertEqual(decision.reason, "publication_allowed")

        self.allowlist.official_verification_valid_until = self.NOW
        self.allowlist.version += 1
        self.allowlist.save(
            update_fields=(
                "official_verification_valid_until",
                "version",
                "updated_at",
            )
        )
        self.assertEqual(self._resolve().reason, "official_route_expired")


class RaceLiveOfficialVerificationModelTests(TestCase):
    NOW = datetime(2026, 7, 20, 6, 0, tzinfo=dt_timezone.utc)

    def _model(self, name):
        model = getattr(stable_models, name, None)
        self.assertIsNotNone(model, f"{name} 模型尚未实现")
        return model

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="race-live-official-verification",
            original_name="Race Live Official Verification Stakes",
            chinese_name="准实时官方复核锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
            race_datetime=self.NOW,
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="jra",
            external_race_id="jra-official-race",
        )
        payload = {"external_race_id": self.source.external_race_id, "participants": []}
        self.observation = stable_models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW,
            parser_version="jra-v1",
            raw_sha256="a" * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=payload,
            ),
            result_phase=stable_models.RaceResultPhase.OFFICIAL,
            normalized_payload=payload,
        )
        self.revision = stable_models.RaceEventRevision.objects.create(
            event=self.event,
            kind=stable_models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=stable_models.RaceResultPhase.PROVISIONAL,
            content_sha256="b" * 64,
        )

    def test_official_marker_contract_and_evidence_preserve_reviewed_provenance(self):
        contract_model = self._model("RaceLiveOfficialMarkerContract")
        evidence_model = self._model("RaceLiveOfficialMarkerEvidence")
        contract = contract_model.objects.create(
            country_region=stable_models.RacingRegion.JAPAN,
            source_key="jra",
            parser_version="jra-v1",
            allowed_marker_types=["result_status_official", "stewards_amendment"],
            contract_digest="c" * 64,
            valid_until=self.NOW + timedelta(days=30),
        )

        self.assertEqual(contract.review_status, "pending")
        self.assertEqual(contract.version, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            contract_model.objects.create(
                country_region=stable_models.RacingRegion.JAPAN,
                source_key="jra",
                parser_version="jra-v1",
                contract_digest="d" * 64,
            )

        evidence = evidence_model.objects.create(
            observation=self.observation,
            contract=contract,
            marker_type="result_status_official",
            contract_digest=contract.contract_digest,
            parser_version=contract.parser_version,
            raw_sha256="e" * 64,
            source_timestamp=self.NOW,
        )
        self.assertEqual(evidence.contract_digest, "c" * 64)
        self.assertEqual(evidence.marker_type, "result_status_official")
        with self.assertRaises(IntegrityError), transaction.atomic():
            evidence_model.objects.create(
                observation=self.observation,
                contract=contract,
                marker_type="stewards_amendment",
                contract_digest=contract.contract_digest,
                parser_version=contract.parser_version,
                raw_sha256="f" * 64,
            )

    def test_verification_incident_is_unique_per_revision_route_and_defaults_open(self):
        incident_model = self._model("RaceLiveOfficialVerificationIncident")
        incident = incident_model.objects.create(
            event=self.event,
            provisional_revision=self.revision,
            official_route="jra_result_verification",
            official_route_version="jra-v1",
            deadline_at=self.NOW + timedelta(hours=2),
            next_probe_at=self.NOW + timedelta(hours=2),
            opened_at=self.NOW,
        )

        self.assertEqual(incident.status, "open")
        self.assertIsNone(incident.last_probe_at)
        self.assertIsNone(incident.alert_sent_at)
        self.assertIsNone(incident.resolved_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            incident_model.objects.create(
                event=self.event,
                provisional_revision=self.revision,
                official_route="jra_result_verification",
                official_route_version="jra-v1",
                deadline_at=self.NOW + timedelta(hours=2),
                opened_at=self.NOW,
            )

    def test_public_route_contract_and_manual_due_fields_are_persisted(self):
        allowlist_fields = {
            field.name
            for field in stable_models.RaceLiveEventPublicationAllowlist._meta.get_fields()
        }
        incident_fields = {
            field.name
            for field in stable_models.RaceLiveOfficialVerificationIncident._meta.get_fields()
        }

        self.assertIn("official_verification_contract_digest", allowlist_fields)
        self.assertIn("official_terms_evidence_digest", allowlist_fields)
        self.assertIn("official_route_contract_digest", incident_fields)
        self.assertIn("official_terms_evidence_digest", incident_fields)
        self.assertIn("manual_verification_due_at", incident_fields)


class RaceLiveRevisionModelTests(TestCase):
    def _model(self, name):
        model = getattr(stable_models, name, None)
        self.assertIsNotNone(model, f"{name} 模型尚未实现")
        return model

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="race-live-revision",
            original_name="Race Live Revision Stakes",
            chinese_name="准实时修订锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="jra",
            external_race_id="revision-race-1",
        )
        participant_model = stable_models.RaceEventParticipant
        self.first = participant_model.objects.create(
            event=self.event,
            stable_key="horse-1",
            canonical_name="Horse One",
        )
        self.second = participant_model.objects.create(
            event=self.event,
            stable_key="horse-2",
            canonical_name="Horse Two",
        )

    def _observation(self, phase="provisional", sha="a" * 64):
        return self._model("RaceResultObservation").objects.create(
            source_identity=self.source,
            parser_version="parser-v1",
            raw_sha256="b" * 64,
            normalized_sha256=sha,
            result_phase=phase,
            normalized_payload={"results": []},
        )

    def _revision(self, phase="provisional", number=1, sha="c" * 64):
        return self._model("RaceEventRevision").objects.create(
            event=self.event,
            kind="result",
            revision_no=number,
            phase=phase,
            content_sha256=sha,
            primary_observation=self._observation(phase=phase, sha=sha),
        )

    def test_observation_dedupes_same_source_hash_and_phase_only(self):
        observation_model = self._model("RaceResultObservation")
        first = self._observation()

        with self.assertRaises(IntegrityError), transaction.atomic():
            observation_model.objects.create(
                source_identity=self.source,
                parser_version="parser-v2",
                raw_sha256="d" * 64,
                normalized_sha256=first.normalized_sha256,
                result_phase="provisional",
            )

        official = self._observation(phase="official", sha=first.normalized_sha256)
        self.assertNotEqual(first.pk, official.pk)

    def test_revision_uniqueness_includes_phase_and_revision_number(self):
        revision_model = self._model("RaceEventRevision")
        provisional = self._revision()

        with self.assertRaises(IntegrityError), transaction.atomic():
            revision_model.objects.create(
                event=self.event,
                kind="result",
                revision_no=1,
                phase="official",
                content_sha256="d" * 64,
            )

        official = self._revision(phase="official", number=2, sha=provisional.content_sha256)
        self.assertNotEqual(provisional.pk, official.pk)

        with self.assertRaises(IntegrityError), transaction.atomic():
            revision_model.objects.create(
                event=self.event,
                kind="result",
                revision_no=3,
                phase="official",
                content_sha256=provisional.content_sha256,
            )

    def test_revision_and_phase_database_constraints_fail_closed(self):
        revision_model = self._model("RaceEventRevision")

        for values in (
            {"kind": "unexpected", "revision_no": 1, "phase": "official"},
            {"kind": "result", "revision_no": 0, "phase": "official"},
            {"kind": "result", "revision_no": 1, "phase": "unexpected"},
        ):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    revision_model.objects.create(
                        event=self.event,
                        content_sha256="e" * 64,
                        **values,
                    )

    def test_items_allow_dead_heat_position_but_not_duplicate_identity_or_order(self):
        revision = self._revision(phase="official")
        item_model = self._model("RaceEventRevisionItem")
        first_item = item_model.objects.create(
            revision=revision,
            participant=self.first,
            internal_order=1,
            official_finish_position=2,
            status="dead_heat",
        )
        second_item = item_model.objects.create(
            revision=revision,
            participant=self.second,
            internal_order=2,
            official_finish_position=2,
            status="dead_heat",
        )
        self.assertEqual(first_item.official_finish_position, second_item.official_finish_position)

        with self.assertRaises(IntegrityError), transaction.atomic():
            item_model.objects.create(
                revision=revision,
                participant=self.first,
                internal_order=3,
                status="finished",
            )

        third = stable_models.RaceEventParticipant.objects.create(
            event=self.event,
            stable_key="horse-3",
            canonical_name="Horse Three",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            item_model.objects.create(
                revision=revision,
                participant=third,
                internal_order=2,
                status="finished",
            )

    def test_supporting_evidence_link_is_unique_per_revision_observation(self):
        revision = self._revision()
        observation = self._observation(sha="f" * 64)
        link_model = self._model("RaceEventRevisionEvidence")
        link_model.objects.create(revision=revision, observation=observation)

        with self.assertRaises(IntegrityError), transaction.atomic():
            link_model.objects.create(revision=revision, observation=observation)


class RaceEventRevisionAllocatorTests(TestCase):
    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="race-live-allocator",
            original_name="Race Live Allocator Stakes",
            chinese_name="准实时编号锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.control = stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner="live",
            owner_generation=7,
            owner_manifest_sha256="a" * 64,
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="jra",
            external_race_id="allocator-race-1",
        )

    def _observation(self, phase="provisional", source=None, sha="b" * 64):
        return stable_models.RaceResultObservation.objects.create(
            source_identity=source or self.source,
            parser_version="parser-v1",
            raw_sha256="c" * 64,
            normalized_sha256=sha,
            result_phase=phase,
        )

    def _allocate(self, **overrides):
        allocator = getattr(race_events, "allocate_race_event_revision", None)
        self.assertTrue(callable(allocator), "RaceEvent revision allocator 尚未实现")
        values = {
            "event_id": self.event.pk,
            "kind": "result",
            "phase": "provisional",
            "content_sha256": "d" * 64,
            "expected_owner": "live",
            "expected_generation": 7,
        }
        if "primary_observation_id" not in overrides:
            values["primary_observation_id"] = self._observation().pk
        values.update(overrides)
        return allocator(**values)

    def test_projection_control_revision_pointers_default_to_null(self):
        self.control.refresh_from_db()

        for field_name in (
            "current_racecard_revision_id",
            "last_known_good_racecard_revision_id",
            "current_result_revision_id",
            "last_known_good_result_revision_id",
        ):
            self.assertTrue(hasattr(self.control, field_name), f"缺少 {field_name}")
            self.assertIsNone(getattr(self.control, field_name))

    def test_allocator_uses_independent_kind_counter_under_owner_generation(self):
        result = self._allocate()
        racecard_observation = self._observation(
            phase="racecard",
            sha="e" * 64,
        )
        racecard = self._allocate(
            kind="racecard",
            phase="racecard",
            content_sha256="e" * 64,
            primary_observation_id=racecard_observation.pk,
        )

        self.control.refresh_from_db()
        self.assertEqual(result.revision_no, 1)
        self.assertEqual(racecard.revision_no, 1)
        self.assertEqual(self.control.next_result_revision_no, 2)
        self.assertEqual(self.control.next_racecard_revision_no, 2)

    def test_same_phase_and_content_replay_returns_existing_revision(self):
        observation = self._observation()
        first = self._allocate(primary_observation_id=observation.pk)
        replay = self._allocate(primary_observation_id=observation.pk)

        self.control.refresh_from_db()
        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(self.control.next_result_revision_no, 2)
        self.assertEqual(
            stable_models.RaceEventRevision.objects.filter(event=self.event).count(),
            1,
        )

    def test_owner_or_generation_mismatch_fails_without_allocating(self):
        conflict = getattr(
            race_events,
            "RaceEventProjectionOwnershipConflict",
            RuntimeError,
        )
        observation = self._observation()

        for overrides in (
            {"expected_owner": "historical"},
            {"expected_generation": 6},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(conflict):
                    self._allocate(
                        primary_observation_id=observation.pk,
                        **overrides,
                    )

        self.control.refresh_from_db()
        self.assertEqual(self.control.next_result_revision_no, 1)
        self.assertFalse(
            stable_models.RaceEventRevision.objects.filter(event=self.event).exists()
        )

    def test_cross_event_or_phase_mismatched_observation_fails_closed(self):
        other_event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="race-live-allocator-other",
            original_name="Other Allocator Stakes",
            chinese_name="其他编号锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Kyoto",
            grade_text="G2",
            surface=stable_models.RaceEventSurface.TURF,
        )
        other_source = stable_models.RaceResultSourceIdentity.objects.create(
            event=other_event,
            source_key="jra",
            external_race_id="allocator-race-2",
        )
        cross_event = self._observation(source=other_source, sha="f" * 64)
        wrong_phase = self._observation(phase="official", sha="1" * 64)

        for observation in (cross_event, wrong_phase):
            with self.subTest(observation=observation.pk):
                with self.assertRaises(ValueError):
                    self._allocate(primary_observation_id=observation.pk)

        self.control.refresh_from_db()
        self.assertEqual(self.control.next_result_revision_no, 1)


class RaceSourceNetworkPermissionTests(SimpleTestCase):
    def _decide(self, **overrides):
        resolver = getattr(
            race_events,
            "resolve_race_source_network_permission",
            None,
        )
        self.assertTrue(callable(resolver), "source network permission resolver 尚未实现")
        values = {
            "mode": "proof",
            "terms_status": "approved",
            "automation_allowed": False,
            "proof_network_allowed": True,
            "valid_until": datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
            "evidence_sha256": "a" * 64,
            "registry_digest": "b" * 64,
            "expected_registry_digest": "b" * 64,
            "manifest_approved": True,
            "request_budget": 10,
            "historical_handoff_complete": True,
            "now": datetime(2026, 7, 16, tzinfo=dt_timezone.utc),
        }
        values.update(overrides)
        return resolver(**values)

    def test_offline_fixture_mode_is_allowed_without_network_permission(self):
        decision = self._decide(
            mode="offline",
            terms_status="unknown",
            proof_network_allowed=False,
            valid_until=None,
            evidence_sha256="",
            registry_digest="",
            expected_registry_digest="",
            manifest_approved=False,
            request_budget=0,
            historical_handoff_complete=False,
        )

        self.assertIs(decision.allowed, True)
        self.assertEqual(decision.reason, "offline_fixture")

    def test_proof_requires_explicit_permission_manifest_budget_and_handoff(self):
        self.assertIs(self._decide().allowed, True)

        invalid_overrides = (
            {"proof_network_allowed": False},
            {"manifest_approved": False},
            {"request_budget": 0},
            {"request_budget": True},
            {"historical_handoff_complete": False},
        )
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides):
                self.assertIs(self._decide(**overrides).allowed, False)

    def test_shadow_and_production_require_approved_automation(self):
        for mode in ("shadow", "production"):
            with self.subTest(mode=mode):
                self.assertIs(
                    self._decide(
                        mode=mode,
                        automation_allowed=True,
                        proof_network_allowed=False,
                        manifest_approved=False,
                        request_budget=0,
                    ).allowed,
                    True,
                )
                self.assertIs(
                    self._decide(mode=mode, automation_allowed=False).allowed,
                    False,
                )

    def test_all_network_modes_fail_closed_on_terms_expiry_or_digest_drift(self):
        invalid_overrides = (
            {"terms_status": "unknown"},
            {"terms_status": "manual"},
            {"terms_status": "blocked"},
            {"valid_until": None},
            {"valid_until": datetime(2026, 7, 16, tzinfo=dt_timezone.utc)},
            {"evidence_sha256": "not-a-sha"},
            {"registry_digest": "c" * 64},
            {"expected_registry_digest": ""},
        )
        for mode in ("proof", "shadow", "production"):
            for overrides in invalid_overrides:
                with self.subTest(mode=mode, overrides=overrides):
                    self.assertIs(self._decide(mode=mode, **overrides).allowed, False)

    def test_unknown_mode_and_invalid_now_fail_closed(self):
        self.assertIs(self._decide(mode="unexpected").allowed, False)
        self.assertIs(self._decide(now=None).allowed, False)
        self.assertIs(
            self._decide(now=datetime(2026, 7, 16)).allowed,
            False,
        )


class RaceLiveHostBudgetModelTests(TestCase):
    def _model(self):
        model = getattr(stable_models, "RaceLiveHostBudget", None)
        self.assertIsNotNone(model, "RaceLiveHostBudget 模型尚未实现")
        return model

    def test_host_budget_defaults_are_shared_and_fail_closed(self):
        budget = self._model().objects.create(host="api.example.test")

        self.assertEqual(budget.min_interval_ms, 1000)
        self.assertIsNone(budget.next_allowed_at)
        self.assertEqual(budget.consecutive_failures, 0)
        self.assertIsNone(budget.circuit_open_until)
        self.assertEqual(budget.last_error_code, "")
        self.assertEqual(budget.lock_version, 0)

    def test_database_rejects_duplicate_or_empty_host(self):
        model = self._model()
        model.objects.create(host="api.example.test")

        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(host="api.example.test")
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(host="")

    def test_database_rejects_zero_minimum_interval(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._model().objects.create(
                host="zero.example.test",
                min_interval_ms=0,
            )


class RaceLivePollingScheduleTests(SimpleTestCase):
    OFF_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def _calculate(self, *, now, state="scheduled"):
        calculator = getattr(race_events, "calculate_race_live_next_poll_at", None)
        self.assertTrue(callable(calculator), "准实时赛事轮询窗口函数尚未实现")
        return calculator(off_time=self.OFF_TIME, now=now, state=state)

    def test_pre_race_windows_use_bounded_intervals(self):
        cases = (
            (timedelta(hours=-30), self.OFF_TIME - timedelta(hours=24)),
            (timedelta(hours=-12), self.OFF_TIME - timedelta(hours=11)),
            (timedelta(hours=-1), self.OFF_TIME - timedelta(minutes=45)),
            (timedelta(minutes=-20), self.OFF_TIME - timedelta(minutes=15)),
        )
        for offset, expected in cases:
            with self.subTest(offset=offset):
                self.assertEqual(
                    self._calculate(now=self.OFF_TIME + offset),
                    expected,
                )

    def test_awaiting_result_uses_three_minute_polling_after_off_time(self):
        now = self.OFF_TIME + timedelta(minutes=11)
        self.assertEqual(
            self._calculate(now=now, state="awaiting_result"),
            now + timedelta(minutes=3),
        )

    def test_provisional_result_uses_ten_minutes_until_two_hours(self):
        now = self.OFF_TIME + timedelta(minutes=45)
        self.assertEqual(
            self._calculate(now=now, state="provisional_result"),
            now + timedelta(minutes=10),
        )

    def test_late_revision_probes_are_anchored_to_off_time(self):
        cases = (
            (timedelta(hours=3), timedelta(hours=24)),
            (timedelta(hours=25), timedelta(hours=72)),
            (timedelta(hours=73), timedelta(days=7)),
        )
        for offset, expected_probe in cases:
            with self.subTest(offset=offset):
                self.assertEqual(
                    self._calculate(
                        now=self.OFF_TIME + offset,
                        state="official_result",
                    ),
                    self.OFF_TIME + expected_probe,
                )

        self.assertIsNone(
            self._calculate(
                now=self.OFF_TIME + timedelta(days=8),
                state="official_result",
            )
        )

    def test_terminal_correction_and_invalid_inputs_stop_polling(self):
        self.assertIsNone(
            self._calculate(now=self.OFF_TIME, state="corrected_result")
        )
        calculator = getattr(race_events, "calculate_race_live_next_poll_at", None)
        self.assertTrue(callable(calculator))
        self.assertIsNone(
            calculator(
                off_time=self.OFF_TIME.replace(tzinfo=None),
                now=self.OFF_TIME,
                state="scheduled",
            )
        )
        self.assertIsNone(
            calculator(
                off_time=self.OFF_TIME,
                now=self.OFF_TIME.replace(tzinfo=None),
                state="scheduled",
            )
        )
        self.assertIsNone(
            calculator(off_time=self.OFF_TIME, now=self.OFF_TIME, state="unknown")
        )


class RaceEventLiveClaimTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="live-claim-event",
            original_name="Live Claim Stakes",
            chinese_name="准实时领取锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.control = stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner="live",
            owner_generation=3,
            owner_manifest_sha256="a" * 64,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
            next_poll_at=self.NOW,
        )

    def _claim(self, **overrides):
        service = getattr(race_events, "claim_race_event_live_tracking", None)
        self.assertTrue(callable(service), "准实时赛事 claim 服务尚未实现")
        values = {
            "event_id": self.event.pk,
            "expected_owner_generation": 3,
            "now": self.NOW,
            "ttl_seconds": 120,
        }
        values.update(overrides)
        return service(**values)

    def test_due_enabled_live_owner_is_claimed_with_new_generation_and_token(self):
        decision = self._claim()
        self.assertIs(decision.claimed, True)
        self.assertEqual(decision.reason, "claimed")
        self.assertTrue(decision.attempt_token)
        self.assertEqual(decision.claim_generation, 1)

        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, decision.attempt_token)
        self.assertEqual(self.tracking.claim_generation, 1)
        self.assertEqual(
            self.tracking.claim_expires_at,
            self.NOW + timedelta(seconds=120),
        )
        self.assertEqual(self.tracking.last_attempt_at, self.NOW)
        self.assertEqual(self.tracking.lock_version, 1)

    def test_unexpired_claim_is_not_reissued_but_expired_claim_is_reclaimed(self):
        first = self._claim()
        blocked = self._claim(now=self.NOW + timedelta(seconds=30))
        self.assertIs(blocked.claimed, False)
        self.assertEqual(blocked.reason, "claim_active")

        reclaimed = self._claim(now=self.NOW + timedelta(seconds=121))
        self.assertIs(reclaimed.claimed, True)
        self.assertNotEqual(reclaimed.attempt_token, first.attempt_token)
        self.assertEqual(reclaimed.claim_generation, 2)

    def test_nonempty_token_without_expiry_is_corrupt_and_not_reclaimed(self):
        stable_models.RaceEventLiveTracking.objects.filter(pk=self.tracking.pk).update(
            active_attempt_token="corrupt-token",
            claim_generation=4,
            claim_expires_at=None,
        )

        decision = self._claim()

        self.assertIs(decision.claimed, False)
        self.assertEqual(decision.reason, "claim_missing_expiry")
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "corrupt-token")
        self.assertEqual(self.tracking.claim_generation, 4)
        self.assertEqual(self.tracking.lock_version, 0)

    def test_disabled_not_due_or_wrong_owner_generation_fail_closed(self):
        cases = (
            ({"tracking_enabled": False}, {}, "tracking_disabled"),
            (
                {"next_poll_at": self.NOW + timedelta(minutes=1)},
                {},
                "not_due",
            ),
            ({}, {"expected_owner_generation": 2}, "owner_mismatch"),
        )
        for tracking_updates, claim_overrides, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                reset_values = {
                    "tracking_enabled": True,
                    "next_poll_at": self.NOW,
                    "active_attempt_token": "",
                    "claim_expires_at": None,
                }
                reset_values.update(tracking_updates)
                stable_models.RaceEventLiveTracking.objects.filter(
                    pk=self.tracking.pk
                ).update(**reset_values)
                decision = self._claim(**claim_overrides)
                self.assertIs(decision.claimed, False)
                self.assertEqual(decision.reason, expected_reason)

    def test_invalid_inputs_and_missing_rows_do_not_create_tracking(self):
        self.assertEqual(
            self._claim(ttl_seconds=0).reason,
            "invalid_ttl",
        )
        self.assertEqual(
            self._claim(now=self.NOW.replace(tzinfo=None)).reason,
            "invalid_now",
        )
        missing_event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="live-claim-missing-control",
            original_name="Missing Live Claim Stakes",
            chinese_name="缺失领取锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G2",
            surface=stable_models.RaceEventSurface.TURF,
        )
        before = stable_models.RaceEventLiveTracking.objects.count()
        decision = self._claim(event_id=missing_event.pk)
        self.assertIs(decision.claimed, False)
        self.assertEqual(decision.reason, "tracking_missing")
        self.assertEqual(stable_models.RaceEventLiveTracking.objects.count(), before)


class RaceEventLiveDueSelectorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def _tracked_event(
        self,
        slug,
        *,
        next_poll_at=None,
        tracking_enabled=True,
        owner="live",
        owner_generation=1,
    ):
        event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=f"{slug} Stakes",
            chinese_name=f"{slug} 锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        stable_models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=owner,
            owner_generation=owner_generation,
            owner_manifest_sha256="a" * 64 if owner != "unmanaged" else "",
        )
        tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=event,
            tracking_enabled=tracking_enabled,
            next_poll_at=next_poll_at,
        )
        return event, tracking

    def _select(self, **overrides):
        selector = getattr(race_events, "claim_due_race_event_live_tracking", None)
        self.assertTrue(callable(selector), "准实时 due-selector 尚未实现")
        values = {"now": self.NOW, "batch_size": 10, "ttl_seconds": 120}
        values.update(overrides)
        return selector(**values)

    def test_selector_claims_only_due_enabled_live_owned_rows_in_due_order(self):
        due_later, later_tracking = self._tracked_event(
            "due-later", next_poll_at=self.NOW - timedelta(minutes=1)
        )
        due_first, first_tracking = self._tracked_event(
            "due-first", next_poll_at=self.NOW - timedelta(minutes=2)
        )
        self._tracked_event(
            "future", next_poll_at=self.NOW + timedelta(minutes=1)
        )
        self._tracked_event(
            "disabled",
            next_poll_at=self.NOW - timedelta(minutes=3),
            tracking_enabled=False,
        )
        self._tracked_event(
            "historical-owner",
            next_poll_at=self.NOW - timedelta(minutes=4),
            owner="historical",
        )

        claims = self._select()

        self.assertEqual(
            [claim.event_id for claim in claims],
            [due_first.pk, due_later.pk],
        )
        for claim, tracking in (
            (claims[0], first_tracking),
            (claims[1], later_tracking),
        ):
            tracking.refresh_from_db()
            self.assertEqual(claim.owner_generation, 1)
            self.assertEqual(claim.claim_generation, 1)
            self.assertTrue(claim.attempt_token)
            self.assertEqual(tracking.active_attempt_token, claim.attempt_token)
            self.assertEqual(
                tracking.claim_expires_at,
                self.NOW + timedelta(seconds=120),
            )

    def test_batch_cap_and_active_claim_prevent_duplicate_dispatch(self):
        events = [
            self._tracked_event(
                f"batch-{number}",
                next_poll_at=self.NOW - timedelta(minutes=number),
            )[0]
            for number in range(1, 4)
        ]

        first_batch = self._select(batch_size=2)
        self.assertEqual(len(first_batch), 2)
        self.assertEqual(
            [claim.event_id for claim in first_batch],
            [events[2].pk, events[1].pk],
        )

        second_batch = self._select(batch_size=2)
        self.assertEqual([claim.event_id for claim in second_batch], [events[0].pk])
        self.assertEqual(self._select(batch_size=2), ())

    def test_expired_claim_is_reclaimed_and_invalid_inputs_do_not_mutate(self):
        event, tracking = self._tracked_event(
            "expired-batch-claim",
            next_poll_at=self.NOW - timedelta(minutes=1),
        )
        tracking.active_attempt_token = "old-token"
        tracking.claim_generation = 4
        tracking.claim_expires_at = self.NOW
        tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_generation",
                "claim_expires_at",
            )
        )

        for overrides in (
            {"now": self.NOW.replace(tzinfo=None)},
            {"batch_size": 0},
            {"batch_size": 201},
            {"ttl_seconds": 0},
            {"batch_size": True},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self._select(**overrides), ())
        tracking.refresh_from_db()
        self.assertEqual(tracking.active_attempt_token, "old-token")
        self.assertEqual(tracking.claim_generation, 4)

        claims = self._select()
        self.assertEqual([claim.event_id for claim in claims], [event.pk])
        self.assertEqual(claims[0].claim_generation, 5)
        self.assertNotEqual(claims[0].attempt_token, "old-token")

    def test_selector_excludes_nonempty_token_without_expiry(self):
        _, tracking = self._tracked_event(
            "corrupt-batch-claim",
            next_poll_at=self.NOW - timedelta(minutes=1),
        )
        tracking.active_attempt_token = "corrupt-token"
        tracking.claim_generation = 4
        tracking.claim_expires_at = None
        tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_generation",
                "claim_expires_at",
            )
        )

        self.assertEqual(self._select(), ())
        tracking.refresh_from_db()
        self.assertEqual(tracking.active_attempt_token, "corrupt-token")
        self.assertEqual(tracking.claim_generation, 4)


class RaceLiveHostReservationTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.budget = stable_models.RaceLiveHostBudget.objects.create(
            host="api.example.test",
            min_interval_ms=1500,
        )

    def _reserve(self, **overrides):
        service = getattr(race_events, "reserve_race_live_host_request", None)
        self.assertTrue(callable(service), "准实时 host 请求预约服务尚未实现")
        values = {"host": self.budget.host, "now": self.NOW}
        values.update(overrides)
        return service(**values)

    def test_available_host_is_reserved_atomically_for_its_minimum_interval(self):
        decision = self._reserve()
        self.assertIs(decision.reserved, True)
        self.assertEqual(decision.reason, "reserved")
        self.assertEqual(
            decision.next_allowed_at,
            self.NOW + timedelta(milliseconds=1500),
        )

        self.budget.refresh_from_db()
        self.assertEqual(self.budget.next_allowed_at, decision.next_allowed_at)
        self.assertEqual(self.budget.lock_version, 1)
        self.assertEqual(decision.reservation_version, 1)

    def test_next_allowed_time_rate_limits_without_mutation(self):
        blocked_until = self.NOW + timedelta(seconds=10)
        stable_models.RaceLiveHostBudget.objects.filter(pk=self.budget.pk).update(
            next_allowed_at=blocked_until,
            lock_version=4,
        )
        decision = self._reserve()
        self.assertIs(decision.reserved, False)
        self.assertEqual(decision.reason, "rate_limited")
        self.assertEqual(decision.next_allowed_at, blocked_until)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.lock_version, 4)

    def test_open_circuit_takes_precedence_over_rate_limit(self):
        circuit_until = self.NOW + timedelta(minutes=5)
        stable_models.RaceLiveHostBudget.objects.filter(pk=self.budget.pk).update(
            circuit_open_until=circuit_until,
            next_allowed_at=self.NOW + timedelta(seconds=10),
        )
        decision = self._reserve()
        self.assertIs(decision.reserved, False)
        self.assertEqual(decision.reason, "circuit_open")
        self.assertEqual(decision.next_allowed_at, circuit_until)

    def test_missing_budget_and_invalid_inputs_fail_closed_without_creation(self):
        before = stable_models.RaceLiveHostBudget.objects.count()
        self.assertEqual(
            self._reserve(host="missing.example.test").reason,
            "budget_missing",
        )
        self.assertEqual(stable_models.RaceLiveHostBudget.objects.count(), before)
        for host, now, expected_reason in (
            ("", self.NOW, "invalid_host"),
            (" api.example.test", self.NOW, "invalid_host"),
            (self.budget.host, self.NOW.replace(tzinfo=None), "invalid_now"),
        ):
            with self.subTest(host=host, now=now):
                self.assertEqual(
                    self._reserve(host=host, now=now).reason,
                    expected_reason,
                )


class RaceLiveHostOutcomeTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.budget = stable_models.RaceLiveHostBudget.objects.create(
            host="api.example.test",
            min_interval_ms=1000,
        )

    def _record(self, **overrides):
        service = getattr(race_events, "record_race_live_host_outcome", None)
        self.assertTrue(callable(service), "准实时 host outcome 服务尚未实现")
        values = {
            "host": self.budget.host,
            "now": self.NOW,
            "success": False,
            "error_code": "timeout",
            "circuit_threshold": 3,
            "circuit_seconds": 300,
        }
        if "expected_reservation_version" not in overrides:
            self.budget.refresh_from_db()
            values["expected_reservation_version"] = self.budget.lock_version
        values.update(overrides)
        return service(**values)

    def test_failures_increment_and_open_circuit_at_exact_threshold(self):
        first = self._record()
        second = self._record(now=self.NOW + timedelta(seconds=1))
        third = self._record(now=self.NOW + timedelta(seconds=2))

        self.assertEqual(first.reason, "failure_recorded")
        self.assertEqual(first.consecutive_failures, 1)
        self.assertIsNone(first.circuit_open_until)
        self.assertEqual(second.consecutive_failures, 2)
        self.assertEqual(third.reason, "circuit_opened")
        self.assertEqual(third.consecutive_failures, 3)
        self.assertEqual(
            third.circuit_open_until,
            self.NOW + timedelta(seconds=302),
        )

        self.budget.refresh_from_db()
        self.assertEqual(self.budget.consecutive_failures, 3)
        self.assertEqual(self.budget.last_error_code, "timeout")
        self.assertEqual(self.budget.circuit_open_until, third.circuit_open_until)
        self.assertEqual(self.budget.lock_version, 3)

    def test_success_resets_failure_and_circuit_state(self):
        stable_models.RaceLiveHostBudget.objects.filter(pk=self.budget.pk).update(
            consecutive_failures=5,
            last_error_code="http_503",
            circuit_open_until=self.NOW + timedelta(minutes=5),
            lock_version=7,
        )

        decision = self._record(success=True, error_code="")

        self.assertIs(decision.recorded, True)
        self.assertEqual(decision.reason, "success_recorded")
        self.assertEqual(decision.consecutive_failures, 0)
        self.assertIsNone(decision.circuit_open_until)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.consecutive_failures, 0)
        self.assertEqual(self.budget.last_error_code, "")
        self.assertIsNone(self.budget.circuit_open_until)
        self.assertEqual(self.budget.lock_version, 8)

    def test_stale_success_cannot_clear_newer_failures_or_open_circuit(self):
        first_failure = self._record(circuit_threshold=2)
        second_failure = self._record(
            now=self.NOW + timedelta(seconds=1),
            circuit_threshold=2,
        )
        self.assertEqual(first_failure.consecutive_failures, 1)
        self.assertEqual(second_failure.reason, "circuit_opened")

        stale = self._record(
            expected_reservation_version=0,
            now=self.NOW + timedelta(seconds=2),
            success=True,
            error_code="",
            circuit_threshold=2,
        )

        self.assertIs(stale.recorded, False)
        self.assertEqual(stale.reason, "stale_reservation")
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.consecutive_failures, 2)
        self.assertEqual(self.budget.last_error_code, "timeout")
        self.assertEqual(
            self.budget.circuit_open_until,
            self.NOW + timedelta(seconds=301),
        )
        self.assertEqual(self.budget.lock_version, 2)

    def test_missing_budget_and_invalid_inputs_fail_closed_without_mutation(self):
        before = stable_models.RaceLiveHostBudget.objects.count()
        cases = (
            ({"host": "missing.example.test"}, "budget_missing"),
            ({"host": ""}, "invalid_host"),
            ({"now": self.NOW.replace(tzinfo=None)}, "invalid_now"),
            ({"success": "false"}, "invalid_success"),
            ({"success": False, "error_code": ""}, "invalid_error_code"),
            ({"success": True, "error_code": "timeout"}, "invalid_error_code"),
            ({"circuit_threshold": 0}, "invalid_threshold"),
            ({"circuit_seconds": 0}, "invalid_circuit_seconds"),
        )
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                decision = self._record(**overrides)
                self.assertIs(decision.recorded, False)
                self.assertEqual(decision.reason, reason)
        self.assertEqual(stable_models.RaceLiveHostBudget.objects.count(), before)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.lock_version, 0)
        self.assertEqual(self.budget.consecutive_failures, 0)


class RaceLiveCeleryIsolationTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def test_default_settings_keep_scheduler_off_and_omit_selector_schedule(self):
        self.assertIs(settings.RACE_LIVE_SCHEDULER_ENABLED, False)
        self.assertNotIn(
            "select-due-race-live-events",
            settings.CELERY_BEAT_SCHEDULE,
        )

    def test_poll_task_route_remains_on_isolated_queue(self):
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["stable.tasks.poll_race_live_event_task"],
            {"queue": "race_live"},
        )

    @override_settings(RACE_LIVE_SCHEDULER_ENABLED=False)
    @patch("stable.tasks.claim_due_race_event_live_tracking")
    def test_disabled_selector_does_not_claim_or_dispatch(self, claim_due):
        result = stable_tasks.select_due_race_live_events_task.run()

        self.assertEqual(result, {"enabled": False, "claimed": 0, "dispatched": 0})
        claim_due.assert_not_called()

    @override_settings(
        RACE_LIVE_SCHEDULER_ENABLED=True,
        RACE_LIVE_ENABLED_REGIONS=(stable_models.RacingRegion.FRANCE,),
        RACE_LIVE_SELECTOR_BATCH_SIZE=20,
        RACE_LIVE_CLAIM_TTL_SECONDS=120,
    )
    @patch("stable.tasks.poll_race_live_event_task.apply_async")
    @patch("stable.tasks.claim_due_race_event_live_tracking")
    @patch("stable.tasks.timezone.now")
    def test_enabled_selector_dispatches_claims_to_race_live_queue_after_commit(
        self,
        now,
        claim_due,
        apply_async,
    ):
        now.return_value = self.NOW
        claim_due.return_value = (
            race_events.RaceEventLiveBatchClaim(
                event_id=42,
                owner_generation=3,
                claim_generation=7,
                attempt_token="token-42",
            ),
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = stable_tasks.select_due_race_live_events_task.run()

        claim_due.assert_called_once_with(
            now=self.NOW,
            batch_size=20,
            ttl_seconds=120,
            enabled_regions=(stable_models.RacingRegion.FRANCE,),
        )
        apply_async.assert_called_once_with(
            kwargs={
                "event_id": 42,
                "expected_owner_generation": 3,
                "expected_claim_generation": 7,
                "attempt_token": "token-42",
            },
            queue="race_live",
        )
        self.assertEqual(result, {"enabled": True, "claimed": 1, "dispatched": 1})


class RaceLiveWorkerDeploymentContractTests(SimpleTestCase):
    def test_general_and_live_worker_scripts_consume_disjoint_queues(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        general_script = (repo_root / "deploy/docker/start-worker.sh").read_text()
        live_script_path = repo_root / "deploy/docker/start-race-live-worker.sh"

        self.assertIn('CELERY_WORKER_QUEUES:-celery', general_script)
        self.assertIn('--queues="${CELERY_WORKER_QUEUES:-celery}"', general_script)
        self.assertTrue(live_script_path.exists(), "独立 race_live worker 启动脚本尚未实现")
        live_script = live_script_path.read_text()
        self.assertIn('--queues="race_live"', live_script)
        self.assertIn('CELERY_RACE_LIVE_WORKER_CONCURRENCY:-1', live_script)
        self.assertIn('--prefetch-multiplier=1', live_script)
        self.assertIn('CELERY_RACE_LIVE_WORKER_SOFT_TIME_LIMIT:-180', live_script)
        self.assertIn('CELERY_RACE_LIVE_WORKER_TIME_LIMIT:-210', live_script)
        self.assertNotIn('CELERY_WORKER_QUEUES', live_script)

    def test_all_compose_variants_define_a_dedicated_live_worker(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        for filename in (
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "docker-compose.prod.lowcost.yml",
        ):
            with self.subTest(filename=filename):
                compose_text = (repo_root / filename).read_text()
                self.assertIn("  race_live_worker:\n", compose_text)
                self.assertIn(
                    "command: /app/deploy/docker/start-race-live-worker.sh",
                    compose_text,
                )
                self.assertIn("RACE_LIVE_SCHEDULER_ENABLED: ${RACE_LIVE_SCHEDULER_ENABLED:-false}", compose_text)

    def test_production_live_workers_have_explicit_cpu_and_memory_limits(self):
        repo_root = Path(__file__).resolve().parents[2]
        for filename in (
            "docker-compose.prod.yml",
            "docker-compose.prod.lowcost.yml",
        ):
            with self.subTest(filename=filename):
                compose_text = (repo_root / filename).read_text()
                service_tail = compose_text.split("  race_live_worker:\n", 1)[1]
                live_worker_lines = []
                for line in service_tail.splitlines():
                    if line.startswith("  ") and not line.startswith("    "):
                        break
                    live_worker_lines.append(line)
                live_worker = "\n".join(live_worker_lines)
                self.assertIn("\n    cpus:", live_worker)
                self.assertIn("\n    mem_limit:", live_worker)

    def test_live_poll_task_has_bounded_time_limits_and_safe_env_defaults(self):
        from pathlib import Path

        annotation = settings.CELERY_TASK_ANNOTATIONS[
            "stable.tasks.poll_race_live_event_task"
        ]
        self.assertEqual(
            getattr(settings, "RACE_LIVE_RESULTS_FETCH_BUDGET_SECONDS", None),
            165,
        )
        self.assertEqual(settings.RACE_LIVE_CLAIM_TTL_SECONDS, 240)
        self.assertEqual(annotation["soft_time_limit"], 180)
        self.assertEqual(annotation["time_limit"], 210)
        self.assertLess(
            settings.RACE_LIVE_RESULTS_FETCH_BUDGET_SECONDS,
            annotation["soft_time_limit"],
        )
        self.assertLess(annotation["soft_time_limit"], annotation["time_limit"])

        repo_root = Path(__file__).resolve().parents[2]
        env_text = (repo_root / ".env.example").read_text()
        self.assertIn("RACE_LIVE_SCHEDULER_ENABLED=false", env_text)
        self.assertIn(
            "RACE_LIVE_RACECARD_ARTIFACT_ROOT=/run/race-live/racecards",
            env_text,
        )
        self.assertIn("CELERY_RACE_LIVE_WORKER_CONCURRENCY=1", env_text)
        self.assertIn("RACE_LIVE_RESULTS_FETCH_BUDGET_SECONDS=165", env_text)
        self.assertIn("RACE_LIVE_CLAIM_TTL_SECONDS=240", env_text)
        self.assertIn("CELERY_RACE_LIVE_WORKER_SOFT_TIME_LIMIT=180", env_text)
        self.assertIn("CELERY_RACE_LIVE_WORKER_TIME_LIMIT=210", env_text)
        self.assertEqual(
            settings.RACE_LIVE_RACECARD_ARTIFACT_ROOT,
            "/run/race-live/racecards",
        )

    def test_live_worker_image_contains_registry_and_mounts_external_secret_read_only(self):
        repo_root = Path(__file__).resolve().parents[2]
        registry_relative = (
            "docs/changes/realtime-race-results/"
            "source_registry_the_racing_api_free.json"
        )
        registry = repo_root / registry_relative
        self.assertTrue(registry.is_file())
        dockerfile = (repo_root / "Dockerfile").read_text()
        self.assertIn(
            f"COPY {registry_relative} "
            "/app/runtime/policies/race_live/"
            "source_registry_the_racing_api_free.json",
            dockerfile,
        )

        for filename in (
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "docker-compose.prod.lowcost.yml",
        ):
            with self.subTest(filename=filename):
                compose_text = (repo_root / filename).read_text()
                service_tail = compose_text.split("  race_live_worker:\n", 1)[1]
                live_worker_lines = []
                for line in service_tail.splitlines():
                    if line.startswith("  ") and not line.startswith("    "):
                        break
                    live_worker_lines.append(line)
                live_worker = "\n".join(live_worker_lines)
                self.assertIn(
                    "./runtime/secrets:/run/secrets:ro",
                    live_worker,
                )
                self.assertIn(
                    "./runtime/race_live_racecards:/run/race-live/racecards:rw",
                    live_worker,
                )

                for service_name in ("web", "worker", "beat"):
                    marker = f"  {service_name}:\n"
                    self.assertIn(marker, compose_text)
                    service_tail = compose_text.split(marker, 1)[1]
                    service_lines = []
                    for line in service_tail.splitlines():
                        if line.startswith("  ") and not line.startswith("    "):
                            break
                        service_lines.append(line)
                    service_text = "\n".join(service_lines)
                    self.assertNotIn("/run/secrets", service_text)
                    self.assertNotIn("/run/race-live/racecards", service_text)


class RaceLiveOfflineFixtureRunnerTests(TestCase):
    TOKEN = "offline-fixture-claim"

    def setUp(self):
        self.now = timezone.now()
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="offline-fixture-runner-event",
            original_name="Offline Fixture Runner Stakes",
            chinese_name="离线赛果运行锦标",
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=stable_models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=4,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=stable_models.RaceEventLiveState.AWAITING_RESULT,
            tracking_enabled=True,
            next_poll_at=self.now,
            claim_generation=2,
            active_attempt_token=self.TOKEN,
            claim_expires_at=self.now + timedelta(minutes=10),
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="race-safe-1",
        )
        for index, name in enumerate(("Alpha", "Beta"), start=1):
            participant = stable_models.RaceEventParticipant.objects.create(
                event=self.event,
                stable_key=f"runner-{index}",
                canonical_name=name,
                review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            )
            stable_models.RaceEventParticipantSourceIdentity.objects.create(
                participant=participant,
                source_identity=self.source,
                external_runner_id=f"runner-{index}",
            )

    def _fixture(self, *, off_dt=None):
        off_dt = off_dt or (self.now - timedelta(minutes=5)).isoformat()
        payload = {
            "results": [
                {
                    "race_id": "race-safe-1",
                    "off_dt": off_dt,
                    "region": "GB",
                    "course": "Ascot",
                    "race_name": "Offline Fixture Runner Stakes",
                    "race_status": "result",
                    "runners": [
                        {
                            "horse_id": "runner-1",
                            "horse": "Alpha",
                            "number": "1",
                            "position": "1",
                        },
                        {
                            "horse_id": "runner-2",
                            "horse": "Beta",
                            "number": "2",
                            "position": "2",
                        },
                    ],
                }
            ]
        }
        return {
            "metadata": {
                "schema_version": 1,
                "source_key": "the_racing_api",
                "endpoint": "/v1/results/today/free",
                "created_at": "2026-07-20T14:03:00Z",
                "acquisition": "synthetic_from_public_docs",
                "redistribution_allowed": True,
                "payload_sha256": race_events.build_race_live_canonical_sha256(
                    normalized_payload=payload
                ),
            },
            "payload": payload,
        }

    def _run(self):
        return stable_tasks.poll_race_live_event_task.run(
            event_id=self.event.pk,
            expected_owner_generation=4,
            expected_claim_generation=2,
            attempt_token=self.TOKEN,
        )

    def test_unknown_result_status_is_not_reclassified_as_did_not_finish(self):
        runner_service = importlib.import_module("stable.services.race_live_runner")
        normalized = runner_service._normalized_result_payload(
            {
                "external_race_id": "race-safe-1",
                "off_time": self.now.isoformat(),
                "region": "GB",
                "course": "Ascot",
                "race_name": "Offline Fixture Runner Stakes",
                "race_status": "result",
                "participants": [
                    {
                        "external_runner_id": "runner-1",
                        "status": "unknown",
                        "official_finish_position": None,
                        "position_raw": "unexpected",
                        "number": "1",
                    }
                ],
            }
        )

        self.assertEqual(normalized["participants"][0]["status"], "unknown")
        self.assertEqual(
            normalized["participants"][0]["raw_status"],
            "unexpected",
        )

    def test_runner_defaults_disabled_and_never_mutates_the_claim(self):
        self.assertEqual(settings.RACE_LIVE_RUNNER_MODE, "disabled")
        self.assertEqual(settings.RACE_LIVE_OFFLINE_FIXTURE_ROOT, "")
        self.assertEqual(settings.RACE_LIVE_TRA_SECRET_ENV_FILE, "")
        self.assertEqual(settings.RACE_LIVE_TRA_REGISTRY_FILE, "")
        self.assertEqual(settings.RACE_LIVE_TRA_REGISTRY_SHA256, "")
        self.assertFalse(hasattr(settings, "RACE_LIVE_PROJECT_CURRENT"))
        env_text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
        self.assertIn("RACE_LIVE_RUNNER_MODE=disabled", env_text)
        self.assertIn("RACE_LIVE_OFFLINE_FIXTURE_ROOT=", env_text)
        self.assertIn("RACE_LIVE_TRA_SECRET_ENV_FILE=", env_text)
        self.assertIn("RACE_LIVE_TRA_REGISTRY_FILE=", env_text)
        self.assertIn("RACE_LIVE_TRA_REGISTRY_SHA256=", env_text)
        self.assertNotIn("THE_RACING_API_PASSWORD=", env_text)
        self.assertNotIn("RACE_LIVE_PROJECT_CURRENT", env_text)

        import inspect
        from stable.services import race_live_runner

        self.assertNotIn(
            "project_current",
            inspect.signature(race_live_runner.run_race_live_offline_fixture).parameters,
        )

        result = self._run()

        self.assertEqual(
            result,
            {
                "processed": False,
                "reason": "runner_not_configured",
                "event_id": self.event.pk,
            },
        )
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, self.TOKEN)
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 0)

    def test_task_dispatches_explicit_tra_mode_with_fixed_secure_transport(self):
        expected = {
            "processed": False,
            "reason": "the_racing_api_result_not_found",
            "event_id": self.event.pk,
        }
        with self.settings(
            RACE_LIVE_RUNNER_MODE="the_racing_api_free",
            RACE_LIVE_TRA_SECRET_ENV_FILE="/secure/tra.env",
            RACE_LIVE_TRA_REGISTRY_FILE="/app/source-registry.json",
            RACE_LIVE_TRA_REGISTRY_SHA256="a" * 64,
            RACE_LIVE_ENABLED_REGIONS=(
                stable_models.RacingRegion.UNITED_KINGDOM,
            ),
        ), patch(
            "stable.tasks.resolve_race_live_worker_network_admission",
            return_value=race_events.RaceLiveWorkerNetworkAdmissionDecision(
                True,
                "admitted",
            ),
        ) as preflight, patch(
            "stable.services.race_live_runner.run_race_live_the_racing_api_free",
            return_value=expected,
        ) as runner:
            result = self._run()

        self.assertEqual(result, expected)
        preflight.assert_called_once()
        kwargs = runner.call_args.kwargs
        self.assertEqual(kwargs["event_id"], self.event.pk)
        self.assertEqual(kwargs["expected_owner_generation"], 4)
        self.assertEqual(kwargs["expected_claim_generation"], 2)
        self.assertEqual(kwargs["attempt_token"], self.TOKEN)
        self.assertEqual(kwargs["secret_env_file"], "/secure/tra.env")
        self.assertEqual(kwargs["registry_file"], "/app/source-registry.json")
        self.assertEqual(kwargs["expected_registry_sha256"], "a" * 64)
        proof_module = importlib.import_module(
            "stable.services.race_live_source_proof"
        )
        self.assertIs(kwargs["transport"], proof_module.the_racing_api_transport)

    def test_offline_fixture_runs_observation_revision_and_checkpoint_end_to_end(self):
        with TemporaryDirectory() as temporary_root:
            fixture_path = Path(temporary_root) / "the_racing_api" / "race-safe-1.json"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_text(
                json.dumps(self._fixture(), ensure_ascii=False),
                encoding="utf-8",
            )
            expected_raw_sha256 = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
            with self.settings(
                RACE_LIVE_RUNNER_MODE="offline_fixture",
                RACE_LIVE_OFFLINE_FIXTURE_ROOT=temporary_root,
                RACE_LIVE_PROJECT_CURRENT=False,
            ):
                result = self._run()

        self.assertIs(result["processed"], True)
        self.assertEqual(result["reason"], "offline_fixture_applied")
        self.assertEqual(result["action"], "apply")
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 1)
        self.assertEqual(
            stable_models.RaceResultObservation.objects.get().raw_sha256,
            expected_raw_sha256,
        )
        revision = stable_models.RaceEventRevision.objects.get()
        self.assertEqual(result["revision_id"], revision.pk)
        self.assertEqual(revision.phase, "provisional")
        self.assertIsNone(revision.published_at)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertEqual(self.tracking.consecutive_failures, 0)
        self.assertIsNotNone(self.tracking.next_poll_at)
        self.assertGreater(self.tracking.next_poll_at, self.now)
        self.assertEqual(
            self.tracking.checkpoint_payload["fixture_payload_sha256"],
            self._fixture()["metadata"]["payload_sha256"],
        )

    def test_obsolete_projection_setting_cannot_change_shadow_only_runner(self):
        with TemporaryDirectory() as temporary_root:
            fixture_path = Path(temporary_root) / "the_racing_api" / "race-safe-1.json"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_text(
                json.dumps(self._fixture(), ensure_ascii=False),
                encoding="utf-8",
            )
            with self.settings(
                RACE_LIVE_RUNNER_MODE="offline_fixture",
                RACE_LIVE_OFFLINE_FIXTURE_ROOT=temporary_root,
                RACE_LIVE_PROJECT_CURRENT=True,
            ):
                result = self._run()

        self.assertIs(result["processed"], True)
        self.assertEqual(result["reason"], "offline_fixture_applied")
        revision = stable_models.RaceEventRevision.objects.get()
        self.assertIsNone(revision.published_at)
        self.assertEqual(stable_models.RaceEventRevisionPublication.objects.count(), 0)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertEqual(self.tracking.consecutive_failures, 0)

    def test_success_after_the_final_probe_stops_instead_of_polling_forever(self):
        old_off_time = (self.now - timedelta(days=8)).isoformat()
        with TemporaryDirectory() as temporary_root:
            fixture_path = Path(temporary_root) / "the_racing_api" / "race-safe-1.json"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_text(
                json.dumps(self._fixture(off_dt=old_off_time), ensure_ascii=False),
                encoding="utf-8",
            )
            with self.settings(
                RACE_LIVE_RUNNER_MODE="offline_fixture",
                RACE_LIVE_OFFLINE_FIXTURE_ROOT=temporary_root,
                RACE_LIVE_PROJECT_CURRENT=False,
            ):
                result = self._run()

        self.assertIs(result["processed"], True)
        self.tracking.refresh_from_db()
        self.assertIsNone(self.tracking.next_poll_at)
        self.assertEqual(self.tracking.active_attempt_token, "")

    def test_missing_or_unsafe_fixture_fails_closed_and_releases_claim(self):
        for external_race_id, expected_reason in (
            ("race-safe-1", "fixture_missing"),
            ("../escape", "unsafe_fixture_identity"),
        ):
            with self.subTest(external_race_id=external_race_id):
                stable_models.RaceResultSourceIdentity.objects.filter(
                    pk=self.source.pk
                ).update(external_race_id=external_race_id)
                with TemporaryDirectory() as temporary_root, self.settings(
                    RACE_LIVE_RUNNER_MODE="offline_fixture",
                    RACE_LIVE_OFFLINE_FIXTURE_ROOT=temporary_root,
                    RACE_LIVE_PROJECT_CURRENT=False,
                ):
                    result = self._run()

                self.assertIs(result["processed"], False)
                self.assertEqual(result["reason"], expected_reason)
                self.tracking.refresh_from_db()
                self.assertEqual(self.tracking.active_attempt_token, "")
                self.assertEqual(self.tracking.consecutive_failures, 1)
                self.assertIsNotNone(self.tracking.next_poll_at)
                self.assertGreater(self.tracking.next_poll_at, self.now)
                self.assertEqual(stable_models.RaceResultObservation.objects.count(), 0)
                if external_race_id == "race-safe-1":
                    stable_models.RaceEventLiveTracking.objects.filter(
                        pk=self.tracking.pk
                    ).update(
                        active_attempt_token=self.TOKEN,
                        claim_expires_at=self.now + timedelta(minutes=10),
                        consecutive_failures=0,
                    )


class RaceLiveTheRacingApiFreeRunnerTests(TestCase):
    NOW = datetime(2026, 7, 20, 14, 0, tzinfo=dt_timezone.utc)
    TOKEN = "tra-free-claim"
    HOST = "api.theracingapi.com"

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.secret_path = self.root / "the-racing-api.env"
        self.secret_path.write_text(
            "THE_RACING_API_USERNAME=test-user\n"
            "THE_RACING_API_PASSWORD=test-password\n",
            encoding="utf-8",
        )
        self.secret_path.chmod(0o600)
        self.registry_path = self.root / "registry.json"
        self.registry_digest = self._write_registry(automation_allowed=True)

        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="tra-free-live-runner-event",
            original_name="TRA Free Live Runner Stakes",
            chinese_name="TRA Free 实时运行锦标",
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
            race_datetime=self.NOW - timedelta(minutes=5),
        )
        self.control = stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=stable_models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=4,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=stable_models.RaceEventLiveState.AWAITING_RESULT,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=2,
            active_attempt_token=self.TOKEN,
            claim_expires_at=self.NOW + timedelta(minutes=10),
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="race-live-1",
            host=self.HOST,
            review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            terms_status=stable_models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            proof_network_allowed=False,
            evidence_url="https://www.theracingapi.com/terms-of-service",
            evidence_sha256="a" * 64,
            valid_until=self.NOW + timedelta(days=20),
            registry_digest=self.registry_digest,
        )
        self.participants = []
        for index, name in enumerate(("Alpha", "Beta"), start=1):
            participant = stable_models.RaceEventParticipant.objects.create(
                event=self.event,
                stable_key=f"runner-{index}",
                canonical_name=name,
                review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            )
            stable_models.RaceEventParticipantSourceIdentity.objects.create(
                participant=participant,
                source_identity=self.source,
                external_runner_id=f"runner-{index}",
            )
            self.participants.append(participant)
        racecard = stable_models.RaceEventRevision.objects.create(
            event=self.event,
            kind=stable_models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=stable_models.RaceResultPhase.RACECARD,
            content_sha256="9" * 64,
            source_authority=stable_models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        for index, participant in enumerate(self.participants, start=1):
            stable_models.RaceEventRevisionItem.objects.create(
                revision=racecard,
                participant=participant,
                source_order=index,
                internal_order=index,
                status=stable_models.RaceEventRevisionItemStatus.DECLARED,
                horse_number=str(index),
            )
        self.control.current_racecard_revision = racecard
        self.control.last_known_good_racecard_revision = racecard
        self.control.next_racecard_revision_no = 2
        self.control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "next_racecard_revision_no",
                "updated_at",
            )
        )
        stable_models.RaceLivePublicationPolicy.objects.create(
            scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL,
            scope_key="global",
            mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            registry_digest=self.registry_digest,
            coverage_proof_digest="b" * 64,
            valid_until=self.NOW + timedelta(days=20),
        )
        for scope_type, scope_key in (
            (
                stable_models.RaceLivePublicationScopeType.REGION,
                self.event.country_region,
            ),
            (
                stable_models.RaceLivePublicationScopeType.SOURCE,
                self.source.source_key,
            ),
            (
                stable_models.RaceLivePublicationScopeType.EVENT,
                str(self.event.pk),
            ),
        ):
            stable_models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                registry_digest=self.registry_digest,
                coverage_proof_digest="b" * 64,
                valid_until=self.NOW + timedelta(days=20),
            )
        stable_models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key=self.source.source_key,
            max_mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest="b" * 64,
            official_verification_route="bha_result_verification",
            official_verification_route_version="bha-v1",
            official_verification_contract_digest="c" * 64,
            official_terms_evidence_digest="d" * 64,
            official_verification_valid_until=self.NOW + timedelta(days=20),
            enabled=True,
        )
        self.host_budget = stable_models.RaceLiveHostBudget.objects.create(
            host=self.HOST,
            min_interval_ms=1050,
        )

    def _write_registry(self, *, automation_allowed):
        registry = {
            "automation_allowed": automation_allowed,
            "endpoints": [
                {"name": "regions", "path": "/v1/courses/regions"},
                {
                    "name": "racecards_today",
                    "path": "/v1/racecards/free?day=today&limit=500&skip=0",
                },
                {
                    "name": "results_today",
                    "path": "/v1/results/today/free?limit=50&skip=0",
                },
                {
                    "name": "racecards_sync_today",
                    "path": "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
                },
                {
                    "name": "racecards_sync_tomorrow",
                    "path": "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
                },
            ],
            "evidence": {
                "authorization_basis": "user_confirmed_automation_permission",
                "documentation_url": "https://api.theracingapi.com/documentation",
                "terms_url": "https://www.theracingapi.com/terms-of-service",
                "verified_at": (self.NOW - timedelta(days=1)).isoformat(),
            },
            "host": self.HOST,
            "max_requests": 3,
            "proof_network_allowed": False,
            "schema_version": 1,
            "source_key": "the_racing_api",
            "terms_status": "approved",
            "valid_until": (self.NOW + timedelta(days=20)).isoformat(),
        }
        self.registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return hashlib.sha256(self.registry_path.read_bytes()).hexdigest()

    def _write_registry_v2(self):
        registry = {
            "allowed_region_codes": {
                "united_kingdom": "gb",
                "france": "fr",
                "hong_kong": "hk",
                "japan": "jpn",
                "united_states": "usa",
            },
            "automation_allowed": True,
            "evidence": {
                "authorization_basis": "user_confirmed_automation_permission",
                "documentation_url": "https://api.theracingapi.com/documentation",
                "terms_url": "https://www.theracingapi.com/terms-of-service",
                "verified_at": (self.NOW - timedelta(days=1)).isoformat(),
            },
            "host": self.HOST,
            "max_requests": 3,
            "proof_network_allowed": False,
            "route_contracts": {
                "racecards_free": {
                    "day": ["today", "tomorrow"],
                    "limit": [500],
                    "path": "/v1/racecards/free",
                    "skip": [0],
                },
                "results_today_free": {
                    "limit": [50],
                    "path": "/v1/results/today/free",
                    "skip": list(range(0, 500, 50)),
                },
            },
            "schema_version": 2,
            "source_key": "the_racing_api",
            "terms_status": "approved",
            "valid_until": (self.NOW + timedelta(days=20)).isoformat(),
        }
        self.registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return hashlib.sha256(self.registry_path.read_bytes()).hexdigest()

    def _response_payload(self, *, race_id="race-live-1"):
        return {
            "results": [
                {
                    "race_id": race_id,
                    "off_dt": (
                        self.NOW - timedelta(minutes=5)
                    ).isoformat(),
                    "region": "GB",
                    "course": "Ascot",
                    "race_name": "TRA Free Live Runner Stakes",
                    "race_status": "Results",
                    "runners": [
                        {
                            "horse_id": "runner-1",
                            "horse": "Alpha",
                            "number": "1",
                            "position": "1",
                        },
                        {
                            "horse_id": "runner-2",
                            "horse": "Beta",
                            "number": "2",
                            "position": "2",
                        },
                    ],
                }
            ],
            "total": 1,
            "limit": 10,
            "skip": 0,
        }

    def _response(self, payload=None, **overrides):
        response_type = importlib.import_module(
            "stable.services.race_live_source_proof"
        ).RaceLiveProofHttpResponse
        values = {
            "status_code": 200,
            "content_type": "application/json",
            "body": json.dumps(
                payload if payload is not None else self._response_payload()
            ).encode("utf-8"),
            "elapsed_ms": 12,
            "redirect_url": None,
        }
        values.update(overrides)
        return response_type(**values)

    def _full_results_page(self, *, skip, count, include_target=False):
        rows = []
        for index in range(count):
            rows.append(
                self._response_payload(
                    race_id=(
                        "race-live-1"
                        if include_target and index == 0
                        else f"page-{skip}-race-{index}"
                    )
                )["results"][0]
            )
        return rows

    def _configure_v2_results(self):
        self.registry_digest = self._write_registry_v2()
        stable_models.RaceResultSourceIdentity.objects.filter(
            pk=self.source.pk
        ).update(registry_digest=self.registry_digest)
        stable_models.RaceLivePublicationPolicy.objects.update(
            registry_digest=self.registry_digest
        )
        stable_models.RaceLiveHostBudget.objects.filter(
            pk=self.host_budget.pk
        ).update(min_interval_ms=1)

    def _run(self, transport, *, clock=None, sleeper=None):
        module = importlib.import_module("stable.services.race_live_runner")
        service = getattr(
            module,
            "run_race_live_the_racing_api_free",
            None,
        )
        self.assertTrue(
            callable(service),
            "The Racing API Free 自动化 runner 尚未实现",
        )
        kwargs = {
            "event_id": self.event.pk,
            "expected_owner_generation": 4,
            "expected_claim_generation": 2,
            "attempt_token": self.TOKEN,
            "secret_env_file": str(self.secret_path),
            "registry_file": str(self.registry_path),
            "expected_registry_sha256": self.registry_digest,
            "now": self.NOW,
            "transport": transport,
        }
        if clock is not None:
            kwargs["clock"] = clock
        if sleeper is not None:
            kwargs["sleeper"] = sleeper
        return service(
            **kwargs,
        )

    def test_matching_result_is_admitted_and_published_after_one_bounded_request(self):
        calls = []

        def transport(**kwargs):
            calls.append(kwargs)
            return self._response()

        result = self._run(transport)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["endpoint_name"], "results_today")
        self.assertEqual(
            calls[0]["url"],
            "https://api.theracingapi.com/v1/results/today/free?limit=50&skip=0",
        )
        self.assertEqual(calls[0]["timeout_seconds"], 15)
        self.assertEqual(calls[0]["max_response_bytes"], 2 * 1024 * 1024)
        self.assertIs(calls[0]["allow_redirects"], False)
        self.assertIs(result["processed"], True)
        self.assertEqual(result["reason"], "the_racing_api_provisional_published")
        observation = stable_models.RaceResultObservation.objects.get()
        self.assertEqual(observation.permission_classification, "licensed_api_automation")
        revision = stable_models.RaceEventRevision.objects.get(
            kind=stable_models.RaceEventRevisionKind.RESULT
        )
        self.assertEqual(revision.primary_observation_id, observation.pk)
        self.assertEqual(revision.phase, stable_models.RaceResultPhase.PROVISIONAL)
        self.assertEqual(revision.published_at, self.NOW)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 2)
        self.assertEqual(
            stable_models.RaceLiveOfficialVerificationIncident.objects.count(),
            1,
        )
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertEqual(self.tracking.consecutive_failures, 0)
        self.assertEqual(
            self.tracking.checkpoint_payload["status"],
            "provisional_published",
        )
        self.host_budget.refresh_from_db()
        self.assertEqual(self.host_budget.consecutive_failures, 0)
        self.assertEqual(self.host_budget.lock_version, 2)
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {"the-racing-api.env", "registry.json"},
        )

    def test_v2_results_runner_fetches_all_pages_and_uses_region_route(self):
        self.registry_digest = self._write_registry_v2()
        stable_models.RaceResultSourceIdentity.objects.filter(
            pk=self.source.pk
        ).update(registry_digest=self.registry_digest)
        stable_models.RaceLivePublicationPolicy.objects.update(
            registry_digest=self.registry_digest
        )
        stable_models.RaceLiveHostBudget.objects.filter(
            pk=self.host_budget.pk
        ).update(min_interval_ms=1)
        calls = []

        def transport(**kwargs):
            calls.append(kwargs)
            skip = int(kwargs["url"].rsplit("skip=", 1)[1])
            payload = {
                "results": self._full_results_page(
                    skip=skip,
                    count=50 if skip == 0 else 1,
                    include_target=skip == 0,
                ),
                "total": 51,
                "limit": 50,
                "skip": skip,
            }
            return self._response(payload=payload)

        module = importlib.import_module("stable.services.race_live_runner")
        clock_values = iter(
            self.NOW + timedelta(milliseconds=offset)
            for offset in (0, 10, 20, 30, 40)
        )
        result = module.run_race_live_the_racing_api_free(
            event_id=self.event.pk,
            expected_owner_generation=4,
            expected_claim_generation=2,
            attempt_token=self.TOKEN,
            secret_env_file=str(self.secret_path),
            registry_file=str(self.registry_path),
            expected_registry_sha256=self.registry_digest,
            now=self.NOW,
            transport=transport,
            clock=lambda: next(clock_values),
        )

        self.assertIs(result["processed"], True)
        self.assertEqual(
            [call["endpoint_name"] for call in calls],
            ["results_today", "results_today"],
        )
        self.assertEqual(
            [call["url"] for call in calls],
            [
                (
                    "https://api.theracingapi.com/v1/results/today/free"
                    "?limit=50&skip=0"
                ),
                (
                    "https://api.theracingapi.com/v1/results/today/free"
                    "?limit=50&skip=50"
                ),
            ],
        )
        observation = stable_models.RaceResultObservation.objects.get()
        self.assertEqual(
            observation.parser_version,
            "the_racing_api_free_v2",
        )

    def _assert_truncated_results_page_fails_closed(self, *, truncated_skip):
        self.registry_digest = self._write_registry_v2()
        stable_models.RaceResultSourceIdentity.objects.filter(
            pk=self.source.pk
        ).update(registry_digest=self.registry_digest)
        stable_models.RaceLivePublicationPolicy.objects.update(
            registry_digest=self.registry_digest
        )
        stable_models.RaceLiveHostBudget.objects.filter(
            pk=self.host_budget.pk
        ).update(min_interval_ms=1)
        cache_values = {}
        cache_sets = []

        class FakeCache:
            def get(self, key):
                return cache_values.get(key)

            def set(self, key, value, timeout):
                cache_sets.append((key, value, timeout))
                cache_values[key] = value

        def page_results(*, skip, total=101):
            expected_count = min(50, total - skip)
            actual_count = (
                expected_count - 1
                if skip == truncated_skip
                else expected_count
            )
            rows = []
            for index in range(actual_count):
                payload = self._response_payload(
                    race_id=(
                        "race-live-1"
                        if skip == 0 and index == 0
                        else f"page-{skip}-race-{index}"
                    )
                )["results"][0]
                rows.append(payload)
            return rows

        calls = []

        def transport(**kwargs):
            skip = int(kwargs["url"].rsplit("skip=", 1)[1])
            calls.append(skip)
            return self._response(
                payload={
                    "results": page_results(skip=skip),
                    "total": 101,
                    "limit": 50,
                    "skip": skip,
                }
            )

        tick = iter(range(100))
        module = importlib.import_module("stable.services.race_live_runner")
        with patch.object(module, "django_cache", FakeCache()):
            result = self._run(
                transport,
                clock=lambda: self.NOW
                + timedelta(milliseconds=10 * next(tick)),
                sleeper=lambda _seconds: None,
            )

        self.assertFalse(result["processed"])
        self.assertEqual(result["reason"], "results_pagination_incomplete")
        self.assertEqual(
            calls,
            [skip for skip in (0, 50, 100) if skip <= truncated_skip],
        )
        self.assertEqual(cache_sets, [])
        self.control.refresh_from_db()
        self.assertIsNone(self.control.last_known_good_result_revision_id)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.tracking.refresh_from_db()
        self.assertEqual(
            self.tracking.checkpoint_payload["pagination"]["category"],
            "incomplete",
        )
        staged = race_events.stage_race_live_sla_alerts(
            now=self.NOW + timedelta(seconds=1),
            enabled_regions=(
                stable_models.RacingRegion.UNITED_KINGDOM,
            ),
        )
        self.assertEqual(len(staged), 1)
        incident = stable_models.RaceLiveAlertIncident.objects.get(
            pk=staged[0]
        )
        self.assertEqual(
            incident.alert_type,
            stable_models.RaceLiveAlertType.PAGINATION_OVERFLOW,
        )
        self.assertEqual(
            incident.details["pagination_category"],
            "incomplete",
        )

    def test_v2_results_first_page_truncation_fails_closed(self):
        self._assert_truncated_results_page_fails_closed(truncated_skip=0)

    def test_v2_results_middle_page_truncation_fails_closed(self):
        self._assert_truncated_results_page_fails_closed(truncated_skip=50)

    def test_v2_results_last_page_truncation_fails_closed(self):
        self._assert_truncated_results_page_fails_closed(truncated_skip=100)

    def test_v2_results_overflow_checkpoint_stages_pagination_incident(self):
        self._configure_v2_results()
        tick = iter(range(20))

        result = self._run(
            lambda **_kwargs: self._response(
                payload={
                    "results": self._full_results_page(
                        skip=0,
                        count=50,
                        include_target=True,
                    ),
                    "total": 501,
                    "limit": 50,
                    "skip": 0,
                }
            ),
            clock=lambda: self.NOW
            + timedelta(milliseconds=10 * next(tick)),
        )

        self.assertFalse(result["processed"])
        self.assertEqual(result["reason"], "results_pagination_overflow")
        self.tracking.refresh_from_db()
        self.assertEqual(
            self.tracking.checkpoint_payload["pagination"]["category"],
            "overflow",
        )
        staged = race_events.stage_race_live_sla_alerts(
            now=self.NOW + timedelta(seconds=1),
            enabled_regions=(
                stable_models.RacingRegion.UNITED_KINGDOM,
            ),
        )
        self.assertEqual(len(staged), 1)
        incident = stable_models.RaceLiveAlertIncident.objects.get(
            pk=staged[0]
        )
        self.assertEqual(
            incident.alert_type,
            stable_models.RaceLiveAlertType.PAGINATION_OVERFLOW,
        )
        self.assertEqual(incident.details["pagination_category"], "overflow")

    def test_v2_results_metadata_drift_checkpoint_stages_pagination_incident(self):
        self._configure_v2_results()
        calls = []

        def transport(**kwargs):
            skip = int(kwargs["url"].rsplit("skip=", 1)[1])
            calls.append(skip)
            total = 51 if skip == 0 else 52
            count = min(50, total - skip)
            return self._response(
                payload={
                    "results": self._full_results_page(
                        skip=skip,
                        count=count,
                        include_target=skip == 0,
                    ),
                    "total": total,
                    "limit": 50,
                    "skip": skip,
                }
            )

        tick = iter(range(30))
        result = self._run(
            transport,
            clock=lambda: self.NOW
            + timedelta(milliseconds=10 * next(tick)),
        )

        self.assertFalse(result["processed"])
        self.assertEqual(
            result["reason"],
            "results_pagination_metadata_drift",
        )
        self.assertEqual(calls, [0, 50])
        self.tracking.refresh_from_db()
        self.assertEqual(
            self.tracking.checkpoint_payload["pagination"]["category"],
            "metadata_drift",
        )
        staged = race_events.stage_race_live_sla_alerts(
            now=self.NOW + timedelta(seconds=1),
            enabled_regions=(
                stable_models.RacingRegion.UNITED_KINGDOM,
            ),
        )
        self.assertEqual(len(staged), 1)
        incident = stable_models.RaceLiveAlertIncident.objects.get(
            pk=staged[0]
        )
        self.assertEqual(
            incident.alert_type,
            stable_models.RaceLiveAlertType.PAGINATION_OVERFLOW,
        )
        self.assertEqual(
            incident.details["pagination_category"],
            "metadata_drift",
        )

    def test_v2_ordinary_payload_error_does_not_stage_pagination_incident(self):
        self._configure_v2_results()
        tick = iter(range(20))

        result = self._run(
            lambda **_kwargs: self._response(
                payload={
                    "results": [{"race_id": "malformed"}],
                    "total": 1,
                    "limit": 50,
                    "skip": 0,
                }
            ),
            clock=lambda: self.NOW
            + timedelta(milliseconds=10 * next(tick)),
        )

        self.assertEqual(result["reason"], "the_racing_api_payload_invalid")
        self.tracking.refresh_from_db()
        self.assertNotIn("pagination", self.tracking.checkpoint_payload)
        race_events.stage_race_live_sla_alerts(
            now=self.NOW + timedelta(seconds=1),
            enabled_regions=(
                stable_models.RacingRegion.UNITED_KINGDOM,
            ),
        )
        self.assertFalse(
            stable_models.RaceLiveAlertIncident.objects.filter(
                alert_type=(
                    stable_models.RaceLiveAlertType.PAGINATION_OVERFLOW
                )
            ).exists()
        )

    @override_settings(RACE_LIVE_RESULTS_FETCH_BUDGET_SECONDS=165)
    def test_v2_ten_slow_pages_complete_inside_fetch_deadline(self):
        self._configure_v2_results()
        current = [self.NOW]
        calls = []
        cache_sets = []

        class FakeCache:
            def get(self, _key):
                return None

            def set(self, key, value, timeout):
                cache_sets.append((key, value, timeout))

        def transport(**kwargs):
            skip = int(kwargs["url"].rsplit("skip=", 1)[1])
            calls.append((skip, kwargs["timeout_seconds"]))
            current[0] += timedelta(seconds=15)
            return self._response(
                payload={
                    "results": self._full_results_page(
                        skip=skip,
                        count=50,
                        include_target=skip == 0,
                    ),
                    "total": 500,
                    "limit": 50,
                    "skip": skip,
                }
            )

        module = importlib.import_module("stable.services.race_live_runner")
        with patch.object(module, "django_cache", FakeCache()):
            result = self._run(
                transport,
                clock=lambda: current[0],
                sleeper=lambda _seconds: None,
            )

        self.assertTrue(result["processed"], result["reason"])
        self.assertEqual([skip for skip, _timeout in calls], list(range(0, 500, 50)))
        self.assertTrue(all(timeout == 15 for _skip, timeout in calls))
        self.assertEqual(len(cache_sets), 1)

    @override_settings(RACE_LIVE_RESULTS_FETCH_BUDGET_SECONDS=165)
    def test_v2_results_exceeding_deadline_fails_closed_with_remaining_timeout(self):
        self._configure_v2_results()
        current = [self.NOW]
        calls = []
        cache_sets = []

        class FakeCache:
            def get(self, _key):
                return None

            def set(self, key, value, timeout):
                cache_sets.append((key, value, timeout))

        def transport(**kwargs):
            skip = int(kwargs["url"].rsplit("skip=", 1)[1])
            calls.append((skip, kwargs["timeout_seconds"]))
            current[0] += timedelta(seconds=17)
            return self._response(
                payload={
                    "results": self._full_results_page(
                        skip=skip,
                        count=50,
                        include_target=skip == 0,
                    ),
                    "total": 500,
                    "limit": 50,
                    "skip": skip,
                }
            )

        module = importlib.import_module("stable.services.race_live_runner")
        with patch.object(module, "django_cache", FakeCache()):
            result = self._run(
                transport,
                clock=lambda: current[0],
                sleeper=lambda _seconds: None,
            )

        self.assertFalse(result["processed"])
        self.assertEqual(
            result["reason"],
            "results_pagination_deadline_exceeded",
        )
        self.assertEqual([skip for skip, _timeout in calls], list(range(0, 500, 50)))
        self.assertLess(calls[-1][1], 15)
        self.assertGreater(calls[-1][1], 0)
        self.assertEqual(cache_sets, [])
        self.control.refresh_from_db()
        self.assertIsNone(self.control.last_known_good_result_revision_id)
        self.assertEqual(
            self.tracking.__class__.objects.get(
                pk=self.tracking.pk
            ).checkpoint_payload["pagination"]["category"],
            "deadline_exceeded",
        )

    def test_v2_pre_off_runner_refreshes_racecard_through_region_snapshot(self):
        self.registry_digest = self._write_registry_v2()
        stable_models.RaceResultSourceIdentity.objects.filter(
            pk=self.source.pk
        ).update(registry_digest=self.registry_digest)
        stable_models.RaceLivePublicationPolicy.objects.update(
            registry_digest=self.registry_digest
        )
        stable_models.RaceEvent.objects.filter(pk=self.event.pk).update(
            race_datetime=self.NOW + timedelta(hours=1),
            timezone_name="Europe/London",
            local_date=self.NOW.date(),
        )
        stable_models.RaceEventLiveTracking.objects.filter(
            pk=self.tracking.pk
        ).update(state=stable_models.RaceEventLiveState.RACECARD_READY)
        calls = []

        def transport(**kwargs):
            calls.append(kwargs)
            return self._response(
                payload={
                    "racecards": [
                        {
                            "race_id": "race-live-1",
                            "off_dt": (
                                self.NOW + timedelta(hours=1)
                            ).isoformat(),
                            "region": "GB",
                            "course": "Ascot",
                            "race_name": "TRA Free Live Runner Stakes",
                            "race_status": "Racecard",
                            "runners": [
                                {
                                    "horse_id": "runner-1",
                                    "horse": "Alpha",
                                    "number": "1",
                                    "draw": "3",
                                    "jockey": "New Jockey",
                                },
                                {
                                    "horse_id": "runner-2",
                                    "horse": "Beta",
                                    "number": "2",
                                    "draw": "5",
                                    "jockey": "Second Jockey",
                                },
                            ],
                        }
                    ],
                    "total": 1,
                    "limit": 500,
                    "skip": 0,
                }
            )

        clock_values = iter(
            (
                self.NOW + timedelta(milliseconds=10),
                self.NOW + timedelta(milliseconds=20),
            )
        )
        module = importlib.import_module("stable.services.race_live_runner")
        result = module.run_race_live_the_racing_api_free(
            event_id=self.event.pk,
            expected_owner_generation=4,
            expected_claim_generation=2,
            attempt_token=self.TOKEN,
            secret_env_file=str(self.secret_path),
            registry_file=str(self.registry_path),
            expected_registry_sha256=self.registry_digest,
            now=self.NOW,
            transport=transport,
            clock=lambda: next(clock_values),
        )

        self.assertTrue(result["processed"])
        self.assertEqual(result["reason"], "racecard_refreshed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["endpoint_name"],
            "racecards_sync_today",
        )
        self.assertIn("region_codes=gb", calls[0]["url"])
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_racecard_revision.revision_no,
            2,
        )

    def test_shadow_result_is_checkpointed_without_publication_or_failure(self):
        stable_models.RaceLivePublicationPolicy.objects.filter(
            scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL,
            scope_key="global",
        ).update(mode=stable_models.RaceLivePublicationMode.SHADOW)

        result = self._run(lambda **kwargs: self._response())

        self.assertIs(result["processed"], True)
        self.assertEqual(result["reason"], "the_racing_api_shadow_applied")
        revision = stable_models.RaceEventRevision.objects.get(
            kind=stable_models.RaceEventRevisionKind.RESULT
        )
        self.assertIsNone(revision.published_at)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.assertEqual(
            stable_models.RaceEventRevisionPublication.objects.count(),
            0,
        )
        self.assertEqual(
            stable_models.RaceLiveOfficialVerificationIncident.objects.count(),
            0,
        )
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertEqual(self.tracking.consecutive_failures, 0)
        self.assertEqual(
            self.tracking.checkpoint_payload["status"],
            "shadow_applied",
        )

    def test_no_matching_result_retries_without_observation_or_public_mutation(self):
        result = self._run(
            lambda **kwargs: self._response(
                payload=self._response_payload(race_id="another-race")
            )
        )

        self.assertIs(result["processed"], False)
        self.assertEqual(result["reason"], "the_racing_api_result_not_found")
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 0)
        self.assertEqual(
            stable_models.RaceEventRevision.objects.filter(
                kind=stable_models.RaceEventRevisionKind.RESULT
            ).count(),
            0,
        )
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertEqual(self.tracking.consecutive_failures, 0)
        self.assertGreater(self.tracking.next_poll_at, self.NOW)
        self.assertEqual(
            self.tracking.checkpoint_payload["status"],
            "result_not_found",
        )
        self.host_budget.refresh_from_db()
        self.assertEqual(self.host_budget.lock_version, 2)

    def test_automation_denial_fails_before_secret_or_transport_and_public_writes(self):
        self.registry_digest = self._write_registry(automation_allowed=False)
        calls = []

        result = self._run(lambda **kwargs: calls.append(kwargs))

        self.assertIs(result["processed"], False)
        self.assertEqual(result["reason"], "source_registry_rejected")
        self.assertEqual(calls, [])
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 0)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.host_budget.refresh_from_db()
        self.assertEqual(self.host_budget.lock_version, 0)

    def test_http_and_schema_failures_record_host_failure_without_partial_publication(self):
        invalid_responses = (
            self._response(status_code=500),
            self._response(status_code=302, redirect_url="https://example.com/"),
            self._response(content_type="text/html"),
            self._response(body=b"{" + b"x" * (2 * 1024 * 1024)),
            self._response(payload={"results": [{"race_id": "bad"}]}),
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                result = self._run(lambda **kwargs: response)
                self.assertIs(result["processed"], False)
                self.assertIn(
                    result["reason"],
                    {
                        "the_racing_api_http_error",
                        "the_racing_api_redirect_rejected",
                        "the_racing_api_content_type_rejected",
                        "the_racing_api_response_too_large",
                        "the_racing_api_payload_invalid",
                    },
                )
                self.assertEqual(
                    stable_models.RaceResultObservation.objects.count(),
                    0,
                )
                self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
                stable_models.RaceEventLiveTracking.objects.filter(
                    pk=self.tracking.pk
                ).update(
                    active_attempt_token=self.TOKEN,
                    claim_expires_at=self.NOW + timedelta(minutes=10),
                    consecutive_failures=0,
                )
                stable_models.RaceLiveHostBudget.objects.filter(
                    pk=self.host_budget.pk
                ).update(
                    next_allowed_at=None,
                    consecutive_failures=0,
                    circuit_open_until=None,
                    last_error_code="",
                    lock_version=0,
                )

    def test_stale_claim_after_network_never_publishes_but_records_host_outcome(self):
        def transport(**kwargs):
            stable_models.RaceEventLiveTracking.objects.filter(
                pk=self.tracking.pk
            ).update(
                claim_generation=3,
                active_attempt_token="replacement-claim",
                claim_expires_at=self.NOW + timedelta(minutes=10),
            )
            return self._response()

        result = self._run(transport)

        self.assertIs(result["processed"], False)
        self.assertIn("claim_mismatch", result["reason"])
        self.assertEqual(
            stable_models.RaceEventRevision.objects.filter(
                kind=stable_models.RaceEventRevisionKind.RESULT
            ).count(),
            0,
        )
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.host_budget.refresh_from_db()
        self.assertEqual(self.host_budget.lock_version, 2)

    def test_claim_expiring_during_network_never_publishes_with_stale_start_time(self):
        stable_models.RaceEventLiveTracking.objects.filter(
            pk=self.tracking.pk
        ).update(claim_expires_at=self.NOW + timedelta(seconds=1))

        result = self._run(
            lambda **kwargs: self._response(),
            clock=lambda: self.NOW + timedelta(seconds=2),
        )

        self.assertIs(result["processed"], False)
        self.assertIn("claim_expired", result["reason"])
        self.assertEqual(
            stable_models.RaceEventRevision.objects.filter(
                kind=stable_models.RaceEventRevisionKind.RESULT
            ).count(),
            0,
        )
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)
        self.host_budget.refresh_from_db()
        self.assertEqual(self.host_budget.lock_version, 2)

    def test_pre_off_claim_checkpoints_without_http_or_failure_increment(self):
        off_time = self.NOW + timedelta(minutes=12)
        stable_models.RaceEvent.objects.filter(pk=self.event.pk).update(
            race_datetime=off_time,
        )
        stable_models.RaceEventLiveTracking.objects.filter(
            pk=self.tracking.pk
        ).update(
            state=stable_models.RaceEventLiveState.RACECARD_READY,
            consecutive_failures=4,
        )
        calls = []

        with patch(
            "stable.services.race_live_runner.read_the_racing_api_automation_registry",
            return_value=({}, self.registry_digest),
        ):
            result = self._run(lambda **kwargs: calls.append(kwargs))

        self.assertIs(result["processed"], False)
        self.assertEqual(result["reason"], "pre_off_wait")
        self.assertEqual(calls, [])
        self.tracking.refresh_from_db()
        self.assertEqual(
            self.tracking.state,
            stable_models.RaceEventLiveState.RACECARD_READY,
        )
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertIsNone(self.tracking.claim_expires_at)
        self.assertEqual(self.tracking.consecutive_failures, 4)
        self.assertEqual(self.tracking.checkpoint_payload["status"], "pre_off_wait")
        self.assertGreater(self.tracking.next_poll_at, self.NOW)
        self.assertLessEqual(self.tracking.next_poll_at, off_time)
        self.host_budget.refresh_from_db()
        self.assertEqual(self.host_budget.lock_version, 0)

    def test_at_off_claim_is_promoted_before_the_first_results_request(self):
        stable_models.RaceEvent.objects.filter(pk=self.event.pk).update(
            race_datetime=self.NOW,
        )
        stable_models.RaceEventLiveTracking.objects.filter(
            pk=self.tracking.pk
        ).update(state=stable_models.RaceEventLiveState.RACECARD_READY)
        state_seen_by_transport = []

        def transport(**kwargs):
            state_seen_by_transport.append(
                stable_models.RaceEventLiveTracking.objects.values_list(
                    "state", flat=True
                ).get(pk=self.tracking.pk)
            )
            return self._response()

        with patch(
            "stable.services.race_live_runner.read_the_racing_api_automation_registry",
            return_value=({}, self.registry_digest),
        ):
            result = self._run(transport)

        self.assertEqual(
            state_seen_by_transport,
            [stable_models.RaceEventLiveState.AWAITING_RESULT],
        )
        self.assertIs(result["processed"], True)

    def test_stale_owner_cannot_pre_off_checkpoint_promote_or_request(self):
        off_time = self.NOW + timedelta(minutes=5)
        stable_models.RaceEvent.objects.filter(pk=self.event.pk).update(
            race_datetime=off_time,
        )
        stable_models.RaceEventProjectionControl.objects.filter(
            pk=self.control.pk
        ).update(owner_generation=5)
        stable_models.RaceEventLiveTracking.objects.filter(
            pk=self.tracking.pk
        ).update(state=stable_models.RaceEventLiveState.RACECARD_READY)
        before = stable_models.RaceEventLiveTracking.objects.values(
            "state",
            "active_attempt_token",
            "claim_generation",
            "claim_expires_at",
            "next_poll_at",
            "consecutive_failures",
            "checkpoint_payload",
        ).get(pk=self.tracking.pk)
        calls = []

        with patch(
            "stable.services.race_live_runner.read_the_racing_api_automation_registry",
            return_value=({}, self.registry_digest),
        ):
            result = self._run(lambda **kwargs: calls.append(kwargs))

        self.assertIs(result["processed"], False)
        self.assertEqual(calls, [])
        after = stable_models.RaceEventLiveTracking.objects.values(
            "state",
            "active_attempt_token",
            "claim_generation",
            "claim_expires_at",
            "next_poll_at",
            "consecutive_failures",
            "checkpoint_payload",
        ).get(pk=self.tracking.pk)
        self.assertEqual(after, before)


class RaceLiveKillSwitchTests(TestCase):
    NOW = datetime(2026, 7, 20, 14, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="race-live-kill-switch",
            original_name="Race Live Kill Switch Stakes",
            chinese_name="准实时停用锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=stable_models.RaceEventLiveState.AWAITING_RESULT,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=7,
            active_attempt_token="in-flight-token",
            claim_expires_at=self.NOW + timedelta(minutes=2),
            lock_version=11,
        )

    def _disable(self, **overrides):
        service = getattr(race_events, "disable_race_event_live_tracking", None)
        self.assertTrue(callable(service), "赛事级 live kill switch 尚未实现")
        values = {
            "event_id": self.event.pk,
            "expected_lock_version": 11,
            "now": self.NOW + timedelta(seconds=10),
            "disabled_by": None,
        }
        values.update(overrides)
        return service(**values)

    def test_disable_invalidates_inflight_claim_and_writes_audit_log(self):
        decision = self._disable()

        self.assertIs(decision.applied, True)
        self.assertEqual(decision.reason, "tracking_disabled")
        self.tracking.refresh_from_db()
        self.assertIs(self.tracking.tracking_enabled, False)
        self.assertIsNone(self.tracking.next_poll_at)
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertIsNone(self.tracking.claim_expires_at)
        self.assertEqual(self.tracking.claim_generation, 8)
        self.assertEqual(self.tracking.lock_version, 12)
        self.assertEqual(self.tracking.circuit_reason, "manual_kill_switch")
        log = stable_models.OperationLog.objects.get(
            action_type="race_live_tracking_disabled"
        )
        self.assertEqual(log.target_type, "race_event_live_tracking")
        self.assertEqual(log.target_id, str(self.tracking.pk))

    def test_stale_or_repeated_disable_is_idempotent_and_does_not_mutate_again(self):
        stale = self._disable(expected_lock_version=10)
        self.assertIs(stale.applied, False)
        self.assertEqual(stale.reason, "lock_version_mismatch")
        self.tracking.refresh_from_db()
        self.assertIs(self.tracking.tracking_enabled, True)
        self.assertEqual(self.tracking.claim_generation, 7)

        self.assertIs(self._disable().applied, True)
        repeated = self._disable(expected_lock_version=12)
        self.assertIs(repeated.applied, False)
        self.assertEqual(repeated.reason, "already_disabled")
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.claim_generation, 8)
        self.assertEqual(self.tracking.lock_version, 12)
        self.assertEqual(
            stable_models.OperationLog.objects.filter(
                action_type="race_live_tracking_disabled"
            ).count(),
            1,
        )

    def test_admin_action_posts_through_the_cas_service_and_audits_the_operator(self):
        operator = get_user_model().objects.create_superuser(
            username="race-live-operator",
            email="operator@example.test",
            password="not-a-production-secret",
        )
        self.client.force_login(operator)

        response = self.client.post(
            reverse("admin:stable_raceeventlivetracking_changelist"),
            {
                "action": "disable_selected_tracking",
                "_selected_action": [str(self.tracking.pk)],
                "index": "0",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.tracking.refresh_from_db()
        self.assertIs(self.tracking.tracking_enabled, False)
        log = stable_models.OperationLog.objects.get(
            action_type="race_live_tracking_disabled"
        )
        self.assertEqual(log.admin_id, operator.pk)


class RaceLiveAdminSurfaceTests(SimpleTestCase):
    def test_live_models_are_registered_on_read_only_observation_surfaces(self):
        expected_models = (
            stable_models.RaceEventProjectionControl,
            stable_models.RaceLiveHostBudget,
            stable_models.RaceResultSourceIdentity,
            stable_models.RaceEventParticipant,
            stable_models.RaceEventParticipantSourceIdentity,
            stable_models.RaceResultObservation,
            stable_models.RaceEventRevision,
            stable_models.RaceEventRevisionItem,
            stable_models.RaceEventRevisionEvidence,
            stable_models.RaceEventRevisionPublication,
            stable_models.RaceLivePublicationPolicy,
            stable_models.RaceLiveEventPublicationAllowlist,
            stable_models.RaceLiveOfficialMarkerContract,
            stable_models.RaceLiveOfficialMarkerEvidence,
            stable_models.RaceLiveOfficialVerificationIncident,
        )
        for model in expected_models:
            with self.subTest(model=model.__name__):
                model_admin = django_admin.site._registry.get(model)
                self.assertIsNotNone(model_admin, f"{model.__name__} 尚未注册后台")
                self.assertIsInstance(model_admin, stable_admin.RaceLiveReadOnlyAdmin)
                self.assertIs(model_admin.has_add_permission(None), False)
                self.assertIs(model_admin.has_change_permission(None), False)
                self.assertIs(model_admin.has_delete_permission(None), False)

        revision_admin = django_admin.site._registry[stable_models.RaceEventRevision]
        self.assertIn("conflict_status", revision_admin.list_filter)
        self.assertIn("phase", revision_admin.list_filter)

    def test_tracking_admin_is_read_only_except_for_the_cas_kill_switch_action(self):
        tracking_admin = django_admin.site._registry.get(
            stable_models.RaceEventLiveTracking
        )
        self.assertIsNotNone(tracking_admin, "LiveTracking 后台尚未注册")
        self.assertIsInstance(tracking_admin, stable_admin.RaceEventLiveTrackingAdmin)
        self.assertIs(tracking_admin.has_add_permission(None), False)
        self.assertIs(tracking_admin.has_delete_permission(None), False)
        self.assertIn("disable_selected_tracking", tracking_admin.actions)
        self.assertIn("tracking_enabled", tracking_admin.readonly_fields)
        self.assertIn("active_attempt_token", tracking_admin.readonly_fields)
        self.assertIn("checkpoint_payload", tracking_admin.readonly_fields)


class RaceLivePublicStatusTests(TestCase):
    NOW = datetime(2026, 7, 20, 14, 0, tzinfo=dt_timezone.utc)

    def _event_with_revision(self, slug, phase, *, published=True, conflict=False, stale=False):
        event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
            status=stable_models.RaceEventStatus.FINISHED,
            visibility_status=stable_models.RaceEventVisibility.PUBLISHED,
        )
        source = stable_models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key=f"read_fixture_{slug}",
            external_race_id=f"read-race-{slug}",
            review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            result_authority=(
                stable_models.RaceResultSourceAuthority.OFFICIAL
                if phase != "provisional"
                else stable_models.RaceResultSourceAuthority.SUPPLEMENTAL
            ),
            terms_status=(
                stable_models.RaceSourceTermsStatus.MANUAL
                if phase != "provisional"
                else stable_models.RaceSourceTermsStatus.APPROVED
            ),
            automation_allowed=phase == "provisional",
            valid_until=self.NOW + timedelta(days=30),
            evidence_sha256="d" * 64 if phase != "provisional" else "f" * 64,
            registry_digest="e" * 64 if phase != "provisional" else "a" * 64,
        )
        payload = {
            "external_race_id": source.external_race_id,
            "participants": [
                {
                    "external_runner_id": "read-runner-1",
                    "official_finish_position": 1,
                    "status": "finished",
                }
            ],
        }
        observation = stable_models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=self.NOW,
            parser_version="read-fixture-v1",
            raw_sha256=slug[0] * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=payload,
            ),
            result_phase=phase,
            normalized_payload=payload,
        )
        if phase != "provisional":
            marker_contract = (
                stable_models.RaceLiveOfficialMarkerContract.objects.create(
                    country_region=event.country_region,
                    source_key=source.source_key,
                    parser_version="read-fixture-v1",
                    allowed_marker_types=["official_result"],
                    contract_digest="c" * 64,
                    valid_until=self.NOW + timedelta(days=30),
                    review_status=stable_models.RaceLiveReviewStatus.APPROVED,
                )
            )
            stable_models.RaceLiveOfficialMarkerEvidence.objects.create(
                observation=observation,
                contract=marker_contract,
                marker_type="official_result",
                contract_digest="c" * 64,
                parser_version="read-fixture-v1",
                raw_sha256=observation.raw_sha256,
                source_timestamp=self.NOW,
            )
        revision = stable_models.RaceEventRevision.objects.create(
            event=event,
            kind=stable_models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=phase,
            content_sha256=observation.normalized_sha256,
            source_authority=source.result_authority,
            primary_observation=observation,
            published_at=self.NOW if published else None,
            conflict_status=(
                stable_models.RaceEventRevisionConflictStatus.PENDING
                if conflict
                else stable_models.RaceEventRevisionConflictStatus.NONE
            ),
        )
        stable_models.RaceEventProjectionControl.objects.create(
            event=event,
            current_result_revision=revision,
            last_known_good_result_revision=revision,
            next_result_revision_no=2,
        )
        state = {
            "provisional": stable_models.RaceEventLiveState.PROVISIONAL_RESULT,
            "official": stable_models.RaceEventLiveState.OFFICIAL_RESULT,
            "corrected": stable_models.RaceEventLiveState.CORRECTED_RESULT,
        }[phase]
        stable_models.RaceEventLiveTracking.objects.create(
            event=event,
            state=state,
            stale_at=self.NOW - timedelta(minutes=1) if stale else None,
        )
        if published:
            required_mode = (
                stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                if phase == "provisional"
                else stable_models.RaceLivePublicationMode.OFFICIAL_PUBLIC
            )
            global_policy, _ = stable_models.RaceLivePublicationPolicy.objects.get_or_create(
                scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL,
                scope_key="global",
                defaults={
                    "mode": stable_models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
                    "registry_digest": "a" * 64,
                    "coverage_proof_digest": "b" * 64,
                    "valid_until": self.NOW + timedelta(days=30),
                },
            )
            region_policy, _ = stable_models.RaceLivePublicationPolicy.objects.get_or_create(
                scope_type=stable_models.RaceLivePublicationScopeType.REGION,
                scope_key=event.country_region,
                defaults={
                    "mode": stable_models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
                    "registry_digest": "a" * 64,
                    "coverage_proof_digest": "b" * 64,
                    "valid_until": self.NOW + timedelta(days=30),
                },
            )
            policy_source = source
            if phase != "provisional":
                policy_source = (
                    stable_models.RaceResultSourceIdentity.objects.create(
                        event=event,
                        source_key="the_racing_api",
                        external_race_id=f"tra-{slug}",
                        review_status=(
                            stable_models.RaceLiveReviewStatus.APPROVED
                        ),
                        result_authority=(
                            stable_models.RaceResultSourceAuthority.SUPPLEMENTAL
                        ),
                        terms_status=(
                            stable_models.RaceSourceTermsStatus.APPROVED
                        ),
                        automation_allowed=True,
                        valid_until=self.NOW + timedelta(days=30),
                        evidence_sha256="f" * 64,
                        registry_digest="a" * 64,
                    )
                )
            source_policy, _ = stable_models.RaceLivePublicationPolicy.objects.get_or_create(
                scope_type=stable_models.RaceLivePublicationScopeType.SOURCE,
                scope_key=policy_source.source_key,
                defaults={
                    "mode": (
                        required_mode
                        if phase == "provisional"
                        else stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                    ),
                    "registry_digest": "a" * 64,
                    "coverage_proof_digest": "b" * 64,
                    "valid_until": self.NOW + timedelta(days=30),
                },
            )
            event_policy = stable_models.RaceLivePublicationPolicy.objects.create(
                scope_type=stable_models.RaceLivePublicationScopeType.EVENT,
                scope_key=str(event.pk),
                mode=required_mode,
                registry_digest="a" * 64,
                coverage_proof_digest="b" * 64,
                valid_until=self.NOW + timedelta(days=30),
            )
            allowlist = stable_models.RaceLiveEventPublicationAllowlist.objects.create(
                event=event,
                source_key=policy_source.source_key,
                max_mode=(
                    required_mode
                    if phase == "provisional"
                    else stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                ),
                coverage_proof_digest="b" * 64,
                official_verification_route="read_fixture_verification",
                official_verification_route_version="read-v1",
                official_verification_contract_digest="c" * 64,
                official_terms_evidence_digest="d" * 64,
                official_verification_valid_until=self.NOW + timedelta(days=30),
                enabled=True,
            )
            if phase != "provisional":
                stable_models.RaceLiveOfficialPublicationAuthorization.objects.create(
                    event=event,
                    source_key=source.source_key,
                    route="read_fixture_verification",
                    route_version="read-v1",
                    route_registry_digest="e" * 64,
                    contract_digest="c" * 64,
                    terms_evidence_digest="d" * 64,
                    coverage_proof_digest="b" * 64,
                    max_phase=(
                        stable_models.RaceResultPhase.CORRECTED
                        if phase == "corrected"
                        else stable_models.RaceResultPhase.OFFICIAL
                    ),
                    enabled=True,
                    valid_until=self.NOW + timedelta(days=30),
                )
            stable_models.RaceEventRevisionPublication.objects.create(
                revision=revision,
                published_at=self.NOW,
                reason="test_fixture",
                policy_versions=[
                    [policy.scope_type, policy.scope_key, policy.version]
                    for policy in (
                        global_policy,
                        region_policy,
                        source_policy,
                        event_policy,
                    )
                ],
                allowlist_version=allowlist.version,
                registry_digest=(
                    "a" * 64 if phase == "provisional" else "e" * 64
                ),
                coverage_proof_digest="b" * 64,
                authorization_kind=(
                    "provisional_policy"
                    if phase == "provisional"
                    else "official_route"
                ),
                official_authorization_version=(
                    0 if phase == "provisional" else 1
                ),
            )
            stable_models.RaceEventResult.objects.create(
                event=event,
                finish_position=1,
                official_finish_position=1,
                horse_name="Fixture Winner",
                is_confirmed=phase != "provisional",
            )
        return event

    def test_published_provisional_result_is_clearly_labeled_unofficial(self):
        event = self._event_with_revision("p" * 8, "provisional")
        response = self.client.get(reverse("public-race-detail", args=[event.year, event.slug]))

        self.assertContains(response, "暂定赛果")
        self.assertContains(response, "尚待官方来源复核")
        self.assertContains(response, "补充来源")
        self.assertContains(response, "07-20 22:00")
        self.assertContains(response, "冠军 · 暂定")
        self.assertNotContains(response, "赛果已确认")

    def test_official_corrected_conflict_and_stale_labels_are_distinct(self):
        official = self._event_with_revision("o" * 8, "official")
        corrected = self._event_with_revision("c" * 8, "corrected")
        conflict = self._event_with_revision("f" * 8, "official", conflict=True)
        stale = self._event_with_revision("s" * 8, "official", stale=True)

        self.assertContains(self.client.get(official.public_path), "正式赛果")
        self.assertContains(self.client.get(corrected.public_path), "赛果已更正")
        self.assertContains(self.client.get(conflict.public_path), "赛果待复核")
        with patch("stable.views.timezone.now", return_value=self.NOW):
            self.assertContains(self.client.get(stale.public_path), "数据可能已过期")

    def test_safe_authorization_phase_extension_keeps_current_official_visible(self):
        event = self._event_with_revision("a" * 8, "official")
        authorization = (
            stable_models.RaceLiveOfficialPublicationAuthorization.objects.get(
                event=event
            )
        )
        authorization.max_phase = stable_models.RaceResultPhase.CORRECTED
        authorization.version = 2
        authorization.save(
            update_fields=("max_phase", "version", "updated_at")
        )

        decision = race_events.resolve_race_live_public_read(
            event_id=event.pk,
            now=self.NOW,
        )
        bulk_decision = race_events.resolve_race_live_public_reads(
            event_ids=[event.pk],
            now=self.NOW,
        )[event.pk]

        self.assertTrue(decision.visible, decision.reason)
        self.assertEqual(decision.phase, stable_models.RaceResultPhase.OFFICIAL)
        self.assertTrue(bulk_decision.visible, bulk_decision.reason)
        self.assertEqual(bulk_decision, decision)

    def test_official_policy_version_drift_hides_detail_and_bulk_reads(self):
        event = self._event_with_revision("v" * 8, "official")
        event_policy = stable_models.RaceLivePublicationPolicy.objects.get(
            scope_type=stable_models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event.pk),
        )
        event_policy.version += 1
        event_policy.save(update_fields=("version", "updated_at"))

        detail = race_events.resolve_race_live_public_read(
            event_id=event.pk,
            now=self.NOW,
        )
        bulk = race_events.resolve_race_live_public_reads(
            event_ids=[event.pk],
            now=self.NOW,
        )[event.pk]

        self.assertFalse(detail.visible)
        self.assertFalse(bulk.visible)
        self.assertEqual(detail.reason, "official_publication_audit_mismatch")
        self.assertEqual(bulk, detail)

    def test_official_policy_digest_drift_hides_detail_and_bulk_reads(self):
        event = self._event_with_revision("i" * 8, "official")
        event_policy = stable_models.RaceLivePublicationPolicy.objects.get(
            scope_type=stable_models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event.pk),
        )
        event_policy.registry_digest = "8" * 64
        event_policy.save(update_fields=("registry_digest", "updated_at"))

        detail = race_events.resolve_race_live_public_read(
            event_id=event.pk,
            now=self.NOW,
        )
        bulk = race_events.resolve_race_live_public_reads(
            event_ids=[event.pk],
            now=self.NOW,
        )[event.pk]

        self.assertFalse(detail.visible)
        self.assertFalse(bulk.visible)
        self.assertEqual(detail.reason, "policy_registry_digest_mismatch")
        self.assertEqual(bulk, detail)

    def test_official_allowlist_audit_drift_hides_detail_and_bulk_reads(self):
        event = self._event_with_revision("w" * 8, "official")
        allowlist = stable_models.RaceLiveEventPublicationAllowlist.objects.get(
            event=event,
        )
        allowlist.version += 1
        allowlist.save(update_fields=("version", "updated_at"))

        detail = race_events.resolve_race_live_public_read(
            event_id=event.pk,
            now=self.NOW,
        )
        bulk = race_events.resolve_race_live_public_reads(
            event_ids=[event.pk],
            now=self.NOW,
        )[event.pk]

        self.assertFalse(detail.visible)
        self.assertFalse(bulk.visible)
        self.assertEqual(detail.reason, "official_publication_audit_mismatch")
        self.assertEqual(bulk, detail)

    def test_official_route_digest_drift_hides_detail_and_bulk_reads(self):
        event = self._event_with_revision("d" * 8, "official")
        publication = stable_models.RaceEventRevisionPublication.objects.get(
            revision__event=event,
        )
        publication.registry_digest = "9" * 64
        publication.save(update_fields=("registry_digest",))

        detail = race_events.resolve_race_live_public_read(
            event_id=event.pk,
            now=self.NOW,
        )
        bulk = race_events.resolve_race_live_public_reads(
            event_ids=[event.pk],
            now=self.NOW,
        )[event.pk]

        self.assertFalse(detail.visible)
        self.assertFalse(bulk.visible)
        self.assertEqual(detail.reason, "official_publication_audit_mismatch")
        self.assertEqual(bulk, detail)

    def test_shadow_revision_never_leaks_a_public_live_status_badge(self):
        event = self._event_with_revision("h" * 8, "provisional", published=False)
        response = self.client.get(event.public_path)

        self.assertNotContains(response, "暂定赛果")
        self.assertNotContains(response, "补充来源")
        self.assertNotContains(response, "Fixture Winner")
        self.assertIsNone(response.context["live_result_status"])

    def test_any_explicit_policy_off_immediately_hides_and_reopen_restores_live_results(self):
        event = self._event_with_revision("g" * 8, "provisional")
        source_key = event.source_identities.get().source_key
        scopes = (
            (stable_models.RaceLivePublicationScopeType.GLOBAL, "global"),
            (stable_models.RaceLivePublicationScopeType.REGION, event.country_region),
            (stable_models.RaceLivePublicationScopeType.SOURCE, source_key),
            (stable_models.RaceLivePublicationScopeType.EVENT, str(event.pk)),
        )

        with patch("stable.views.timezone.now", return_value=self.NOW):
            baseline = self.client.get(event.public_path)
        self.assertContains(baseline, "暂定赛果")
        self.assertContains(baseline, "Fixture Winner")

        for scope_type, scope_key in scopes:
            with self.subTest(scope_type=scope_type):
                policy = stable_models.RaceLivePublicationPolicy.objects.get(
                    scope_type=scope_type,
                    scope_key=scope_key,
                )
                restored_mode = policy.mode
                policy.mode = stable_models.RaceLivePublicationMode.OFF
                policy.version += 1
                policy.save(update_fields=("mode", "version", "updated_at"))

                with patch("stable.views.timezone.now", return_value=self.NOW):
                    hidden = self.client.get(event.public_path)
                self.assertNotContains(hidden, "暂定赛果")
                self.assertNotContains(hidden, "Fixture Winner")
                self.assertIsNone(hidden.context["live_result_status"])
                self.assertEqual(list(hidden.context["results"]), [])

                policy.mode = restored_mode
                policy.version += 1
                policy.save(update_fields=("mode", "version", "updated_at"))
                with patch("stable.views.timezone.now", return_value=self.NOW):
                    restored = self.client.get(event.public_path)
                self.assertContains(restored, "暂定赛果")
                self.assertContains(restored, "Fixture Winner")

    def test_policy_off_also_hides_materialized_live_results_from_calendar(self):
        event = self._event_with_revision("l" * 8, "provisional")
        # 默认日期窗口改造后默认模式不再展示 local_date=None 赛事；显式补当天日期。
        event.local_date = timezone.localdate()
        event.save(update_fields=["local_date", "updated_at"])
        calendar_url = reverse("public-race-calendar")

        with patch("stable.views.timezone.now", return_value=self.NOW):
            baseline = self.client.get(calendar_url, {"tab": "all"})
        self.assertContains(baseline, "Fixture Winner")

        global_policy = stable_models.RaceLivePublicationPolicy.objects.get(
            scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL,
            scope_key="global",
        )
        global_policy.mode = stable_models.RaceLivePublicationMode.OFF
        global_policy.version += 1
        global_policy.save(update_fields=("mode", "version", "updated_at"))

        with patch("stable.views.timezone.now", return_value=self.NOW):
            hidden = self.client.get(calendar_url, {"tab": "all"})
        self.assertContains(hidden, event.chinese_name)
        self.assertNotContains(hidden, "Fixture Winner")

    def test_missing_event_policy_hides_from_detail_and_bulk_calendar_reads(self):
        event = self._event_with_revision("m" * 8, "provisional")
        # 默认日期窗口改造后默认模式不再展示 local_date=None 赛事；显式补当天日期。
        event.local_date = timezone.localdate()
        event.save(update_fields=["local_date", "updated_at"])
        stable_models.RaceLivePublicationPolicy.objects.filter(
            scope_type=stable_models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event.pk),
        ).delete()

        with patch("stable.views.timezone.now", return_value=self.NOW):
            detail = self.client.get(event.public_path)
            calendar = self.client.get(
                reverse("public-race-calendar"),
                {"tab": "all"},
            )

        self.assertNotContains(detail, "Fixture Winner")
        self.assertNotContains(calendar, "Fixture Winner")

    def test_calendar_live_read_gate_query_count_is_bounded_for_full_page(self):
        events = [
            self._event_with_revision(
                f"calendar-query-{index:02d}",
                "provisional",
            )
            for index in range(40)
        ]
        # 默认日期窗口改造后默认模式不再展示 local_date=None 赛事；显式补当天日期。
        for event in events:
            event.local_date = timezone.localdate()
            event.save(update_fields=["local_date", "updated_at"])

        with patch("stable.views.timezone.now", return_value=self.NOW):
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(
                    reverse("public-race-calendar"),
                    {"tab": "all"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, events[0].chinese_name)
        self.assertContains(response, events[-1].chinese_name)
        # 预算 12 -> 14：默认日期窗口改造获批新增 2 条有界日期聚合查询
        # （docs/changes/fix-race-calendar-default-date-window/design.md）；修改前实测 12 条。
        self.assertLessEqual(
            len(captured),
            14,
            f"赛事日历 live read gate 查询数不应随 40 场赛事线性增长，实际 {len(captured)}",
        )

    def test_calendar_official_read_gate_query_count_is_bounded_for_full_page(self):
        events = [
            self._event_with_revision(
                f"calendar-official-query-{index:02d}",
                "official" if index % 2 == 0 else "corrected",
            )
            for index in range(40)
        ]
        # 默认日期窗口改造后默认模式不再展示 local_date=None 赛事；显式补当天日期。
        for event in events:
            event.local_date = timezone.localdate()
            event.save(update_fields=["local_date", "updated_at"])

        with patch("stable.views.timezone.now", return_value=self.NOW):
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(
                    reverse("public-race-calendar"),
                    {"tab": "all"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, events[0].chinese_name)
        self.assertContains(response, events[-1].chinese_name)
        # 预算 20 -> 22：默认日期窗口改造获批新增 2 条有界日期聚合查询
        # （docs/changes/fix-race-calendar-default-date-window/design.md）；修改前实测 12 条。
        self.assertLessEqual(
            len(captured),
            22,
            "40 场 official/corrected 日历 read gate 必须保持有界查询，"
            f"实际 {len(captured)}",
        )


class TheRacingApiOfflineFixtureContractTests(SimpleTestCase):
    CREATED_AT = "2026-07-16T12:00:00+08:00"

    def _module(self):
        try:
            return importlib.import_module("stable.services.race_live_fixtures")
        except ModuleNotFoundError:
            self.fail("The Racing API 离线 fixture harness 尚未实现")

    def _fixture(self, endpoint, payload, **metadata_overrides):
        metadata = {
            "schema_version": 1,
            "source_key": "the_racing_api",
            "endpoint": endpoint,
            "created_at": self.CREATED_AT,
            "acquisition": "synthetic_from_public_docs",
            "redistribution_allowed": True,
            "payload_sha256": race_events.build_race_live_canonical_sha256(
                normalized_payload=payload
            ),
        }
        metadata.update(metadata_overrides)
        return {"metadata": metadata, "payload": payload}

    def _parse(self, fixture):
        parser = getattr(self._module(), "parse_the_racing_api_offline_fixture", None)
        self.assertTrue(callable(parser), "The Racing API fixture parser 尚未实现")
        return parser(fixture)

    def test_racecard_free_normalizes_only_objective_identity_and_runner_fields(self):
        payload = {
            "racecards": [
                {
                    "race_id": "rac_fixture_1",
                    "off_dt": "2026-07-20T13:50:00+01:00",
                    "region": "GB",
                    "course": "Ascot",
                    "race_name": "Fixture Stakes",
                    "race_status": "",
                    "runners": [
                        {
                            "horse_id": "hrs_fixture_1",
                            "horse": "Fixture Horse",
                            "number": "1",
                            "draw": "4",
                            "jockey": "Fixture Jockey",
                            "jockey_id": "jky_fixture_1",
                            "form": "11111",
                            "ofr": "120",
                        }
                    ],
                }
            ],
            "total": 1,
            "limit": 500,
            "skip": 0,
        }

        parsed = self._parse(self._fixture("/v1/racecards/free", payload))

        self.assertEqual(parsed.source_key, "the_racing_api")
        self.assertEqual(parsed.phase, "racecard")
        self.assertEqual(len(parsed.races), 1)
        race = parsed.races[0]
        self.assertEqual(race["external_race_id"], "rac_fixture_1")
        self.assertEqual(race["off_time"], "2026-07-20T13:50:00+01:00")
        self.assertEqual(
            race["participants"],
            (
                {
                    "external_runner_id": "hrs_fixture_1",
                    "horse_name": "Fixture Horse",
                    "number": "1",
                    "draw": "4",
                    "jockey_name": "Fixture Jockey",
                    "jockey_id": "jky_fixture_1",
                    "status": "declared",
                },
            ),
        )
        self.assertNotIn("form", str(parsed.races))
        self.assertNotIn("ofr", str(parsed.races))

    def test_results_free_stays_provisional_and_rejects_empty_result_overwrite(self):
        payload = {
            "results": [
                {
                    "race_id": "rac_fixture_1",
                    "off_dt": "2026-07-20T13:50:00+01:00",
                    "region": "GB",
                    "course": "Ascot",
                    "race_name": "Fixture Stakes",
                    "race_status": "Results",
                    "runners": [
                        {
                            "horse_id": "hrs_fixture_1",
                            "horse": "Fixture Horse",
                            "number": "1",
                            "position": "1",
                        }
                    ],
                }
            ],
            "total": 1,
            "limit": 50,
            "skip": 0,
        }
        parsed = self._parse(self._fixture("/v1/results/today/free", payload))
        self.assertEqual(parsed.phase, "provisional")
        self.assertEqual(parsed.races[0]["race_status"], "Results")
        self.assertEqual(
            parsed.races[0]["participants"][0],
            {
                "external_runner_id": "hrs_fixture_1",
                "horse_name": "Fixture Horse",
                "number": "1",
                "position_raw": "1",
                "official_finish_position": 1,
                "status": "finished",
            },
        )

        empty = self._fixture(
            "/v1/results/today/free",
            {"results": [], "total": 0, "limit": 50, "skip": 0},
        )
        with self.assertRaisesRegex(ValueError, "empty results"):
            self._parse(empty)

    def test_results_preserve_known_non_finisher_status_codes(self):
        status_codes = {
            "PU": "pulled_up",
            "F": "fell",
            "UR": "unseated_rider",
            "NR": "non_runner",
            "DSQ": "disqualified",
            "REF": "refused",
            "unexpected": "unknown",
        }
        payload = {
            "results": [
                {
                    "race_id": "rac_fixture_statuses",
                    "off_dt": "2026-07-20T13:50:00+01:00",
                    "region": "GB",
                    "course": "Ascot",
                    "race_name": "Fixture Status Stakes",
                    "race_status": "Results",
                    "runners": [
                        {
                            "horse_id": f"horse-{index}",
                            "horse": f"Horse {index}",
                            "number": str(index),
                            "position": source_status,
                        }
                        for index, source_status in enumerate(status_codes, start=1)
                    ],
                }
            ],
            "total": 1,
            "limit": 50,
            "skip": 0,
        }

        parsed = self._parse(self._fixture("/v1/results/today/free", payload))

        participants = parsed.races[0]["participants"]
        self.assertEqual(
            [participant["status"] for participant in participants],
            list(status_codes.values()),
        )
        self.assertTrue(
            all(participant["official_finish_position"] is None for participant in participants)
        )
        self.assertEqual(
            [participant["position_raw"] for participant in participants],
            list(status_codes),
        )

    def test_metadata_digest_permission_and_endpoint_fail_closed(self):
        payload = {"racecards": []}
        invalid = (
            self._fixture(
                "/v1/racecards/free", payload, redistribution_allowed=False
            ),
            self._fixture("/v1/racecards/free", payload, payload_sha256="a" * 64),
            self._fixture("/v1/racecards/basic", payload),
            self._fixture(
                "/v1/racecards/free", payload, created_at="2026-07-16T12:00:00"
            ),
            self._fixture(
                "/v1/racecards/free", payload, acquisition="unlicensed_snapshot"
            ),
        )
        for fixture in invalid:
            with self.subTest(metadata=fixture["metadata"]):
                with self.assertRaises(ValueError):
                    self._parse(fixture)

    def test_missing_identity_or_runner_fields_fail_closed(self):
        base_race = {
            "race_id": "rac_fixture_1",
            "off_dt": "2026-07-20T13:50:00+01:00",
            "region": "GB",
            "course": "Ascot",
            "race_name": "Fixture Stakes",
            "race_status": "",
            "runners": [
                {
                    "horse_id": "hrs_fixture_1",
                    "horse": "Fixture Horse",
                    "number": "1",
                }
            ],
        }
        for missing in ("race_id", "off_dt", "region", "course", "runners"):
            race = dict(base_race)
            race.pop(missing)
            fixture = self._fixture(
                "/v1/racecards/free", {"racecards": [race]}
            )
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError):
                    self._parse(fixture)

        runner_missing_id = dict(base_race)
        runner_missing_id["runners"] = [{"horse": "Fixture Horse", "number": "1"}]
        with self.assertRaises(ValueError):
            self._parse(
                self._fixture(
                    "/v1/racecards/free", {"racecards": [runner_missing_id]}
                )
            )


class TheRacingApiLiveResultsPayloadTests(SimpleTestCase):
    def _parse(self, payload):
        module = importlib.import_module("stable.services.race_live_fixtures")
        parser = getattr(
            module,
            "parse_the_racing_api_live_results_payload",
            None,
        )
        self.assertTrue(
            callable(parser),
            "The Racing API 实时赛果响应 parser 尚未实现",
        )
        return parser(payload)

    def test_live_results_normalize_objective_fields_without_fixture_metadata(self):
        payload = {
            "results": [
                {
                    "race_id": "rac_live_1",
                    "off_dt": "2026-07-20T13:50:00+01:00",
                    "region": "GB",
                    "course": "Ascot",
                    "race_name": "Live Result Stakes",
                    "race_status": "Results",
                    "runners": [
                        {
                            "horse_id": "hrs_live_1",
                            "horse": "Live Winner",
                            "number": "4",
                            "position": "1",
                            "form": "11111",
                            "ofr": "120",
                        }
                    ],
                }
            ],
            "total": 1,
            "limit": 10,
            "skip": 0,
        }

        parsed = self._parse(payload)

        self.assertEqual(parsed.source_key, "the_racing_api")
        self.assertEqual(parsed.endpoint, "/v1/results/today/free")
        self.assertEqual(parsed.phase, "provisional")
        self.assertEqual(
            parsed.payload_sha256,
            race_events.build_race_live_canonical_sha256(
                normalized_payload=payload
            ),
        )
        self.assertEqual(parsed.races[0]["external_race_id"], "rac_live_1")
        self.assertEqual(
            parsed.races[0]["participants"][0],
            {
                "external_runner_id": "hrs_live_1",
                "horse_name": "Live Winner",
                "number": "4",
                "position_raw": "1",
                "official_finish_position": 1,
                "status": "finished",
            },
        )
        self.assertNotIn("form", str(parsed.races))
        self.assertNotIn("ofr", str(parsed.races))

    def test_empty_live_results_is_a_valid_no_match_snapshot(self):
        parsed = self._parse(
            {
                "results": [],
                "total": 0,
                "limit": 10,
                "skip": 0,
            }
        )

        self.assertEqual(parsed.races, ())
        self.assertEqual(parsed.phase, "provisional")

    def test_nonempty_malformed_live_results_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "runners"):
            self._parse(
                {
                    "results": [
                        {
                            "race_id": "rac_live_bad",
                            "off_dt": "2026-07-20T13:50:00+01:00",
                            "region": "GB",
                            "course": "Ascot",
                            "race_name": "Malformed Stakes",
                            "race_status": "Results",
                        }
                    ]
                }
            )


class RaceResultObservationRecorderTests(TestCase):
    OBSERVED_AT = datetime(2026, 7, 20, 8, 5, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="observation-recorder-event",
            original_name="Observation Recorder Stakes",
            chinese_name="观测记录锦标",
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="rac_fixture_1",
        )
        self.payload = {
            "external_race_id": "rac_fixture_1",
            "participants": [
                {
                    "external_runner_id": "hrs_fixture_1",
                    "position_raw": "1",
                }
            ],
        }

    def _record(self, **overrides):
        service = getattr(race_events, "record_race_result_observation", None)
        self.assertTrue(callable(service), "append-only observation recorder 尚未实现")
        values = {
            "source_identity_id": self.source.pk,
            "observed_at": self.OBSERVED_AT,
            "source_updated_at": None,
            "parser_version": "tra-free-fixture-v1",
            "raw_sha256": "a" * 64,
            "result_phase": "provisional",
            "normalized_payload": self.payload,
            "field_provenance": {"position_raw": "the_racing_api"},
            "parse_warnings": [],
            "permission_classification": "offline_fixture",
        }
        values.update(overrides)
        return service(**values)

    def test_records_append_only_observation_with_computed_normalized_digest(self):
        decision = self._record()
        self.assertIs(decision.created, True)
        observation = decision.observation
        self.assertEqual(observation.source_identity_id, self.source.pk)
        self.assertEqual(observation.result_phase, "provisional")
        self.assertEqual(observation.normalized_payload, self.payload)
        self.assertEqual(
            observation.normalized_sha256,
            race_events.build_race_live_canonical_sha256(
                normalized_payload=self.payload
            ),
        )
        self.assertEqual(observation.permission_classification, "offline_fixture")

    def test_exact_normalized_replay_is_idempotent_and_does_not_overwrite_evidence(self):
        first = self._record()
        replay = self._record(
            parser_version="changed-parser",
            raw_sha256="b" * 64,
            field_provenance={"changed": "should-not-overwrite"},
        )

        self.assertIs(replay.created, False)
        self.assertEqual(replay.observation.pk, first.observation.pk)
        replay.observation.refresh_from_db()
        self.assertEqual(replay.observation.parser_version, "tra-free-fixture-v1")
        self.assertEqual(replay.observation.raw_sha256, "a" * 64)
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 1)

    def test_same_payload_in_different_phase_is_a_distinct_observation(self):
        provisional = self._record()
        official = self._record(result_phase="official")

        self.assertIs(official.created, True)
        self.assertNotEqual(official.observation.pk, provisional.observation.pk)
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 2)

    def test_invalid_inputs_fail_closed_without_creating_observation(self):
        invalid_cases = (
            ({"source_identity_id": 999999}, "source_missing"),
            ({"observed_at": self.OBSERVED_AT.replace(tzinfo=None)}, "invalid_observed_at"),
            ({"source_updated_at": self.OBSERVED_AT.replace(tzinfo=None)}, "invalid_source_updated_at"),
            ({"parser_version": ""}, "invalid_parser_version"),
            ({"raw_sha256": "bad"}, "invalid_raw_digest"),
            ({"result_phase": "unexpected"}, "invalid_phase"),
            ({"normalized_payload": []}, "invalid_payload"),
            ({"field_provenance": []}, "invalid_provenance"),
            ({"parse_warnings": {}}, "invalid_warnings"),
            ({"permission_classification": ""}, "invalid_permission"),
        )
        for overrides, reason in invalid_cases:
            with self.subTest(reason=reason):
                decision = self._record(**overrides)
                self.assertIs(decision.recorded, False)
                self.assertEqual(decision.reason, reason)
        self.assertEqual(stable_models.RaceResultObservation.objects.count(), 0)


class RaceEventLiveCheckpointTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)
    TOKEN = "b" * 32

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="live-checkpoint-event",
            original_name="Live Checkpoint Stakes",
            chinese_name="准实时检查点锦标",
            country_region=stable_models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner="live",
            owner_generation=4,
            owner_manifest_sha256="a" * 64,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=2,
            active_attempt_token=self.TOKEN,
            claim_expires_at=self.NOW + timedelta(minutes=2),
        )

    def _complete(self, **overrides):
        service = getattr(race_events, "complete_race_event_live_checkpoint", None)
        self.assertTrue(callable(service), "准实时赛事 checkpoint CAS 尚未实现")
        values = {
            "event_id": self.event.pk,
            "expected_owner_generation": 4,
            "expected_claim_generation": 2,
            "attempt_token": self.TOKEN,
            "now": self.NOW + timedelta(seconds=10),
            "success": True,
            "next_poll_at": self.NOW + timedelta(minutes=3),
            "checkpoint_payload": {"source": "fixture", "status": "unchanged"},
            "observation_sha256": "c" * 64,
        }
        values.update(overrides)
        return service(**values)

    def test_success_checkpoint_updates_progress_and_releases_claim(self):
        decision = self._complete()
        self.assertIs(decision.applied, True)
        self.assertEqual(decision.reason, "checkpoint_applied")

        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.last_success_at, self.NOW + timedelta(seconds=10))
        self.assertEqual(self.tracking.last_observation_hash, "c" * 64)
        self.assertEqual(self.tracking.consecutive_failures, 0)
        self.assertEqual(self.tracking.next_poll_at, self.NOW + timedelta(minutes=3))
        self.assertEqual(
            self.tracking.checkpoint_payload,
            {"source": "fixture", "status": "unchanged"},
        )
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertIsNone(self.tracking.claim_expires_at)
        self.assertEqual(self.tracking.lock_version, 1)

    def test_failure_checkpoint_increments_failure_and_releases_claim(self):
        decision = self._complete(
            success=False,
            observation_sha256="",
            checkpoint_payload={"error": "timeout"},
        )
        self.assertIs(decision.applied, True)
        self.assertEqual(decision.reason, "checkpoint_applied")
        self.tracking.refresh_from_db()
        self.assertIsNone(self.tracking.last_success_at)
        self.assertEqual(self.tracking.last_observation_hash, "")
        self.assertEqual(self.tracking.consecutive_failures, 1)
        self.assertEqual(self.tracking.checkpoint_payload, {"error": "timeout"})
        self.assertEqual(self.tracking.active_attempt_token, "")

    def test_stale_claim_or_owner_response_is_rejected_without_mutation(self):
        for override, reason in (
            ({"attempt_token": "d" * 32}, "claim_mismatch"),
            ({"expected_claim_generation": 1}, "claim_mismatch"),
            ({"expected_owner_generation": 3}, "owner_mismatch"),
        ):
            with self.subTest(reason=reason, override=override):
                decision = self._complete(**override)
                self.assertIs(decision.applied, False)
                self.assertEqual(decision.reason, reason)
                self.tracking.refresh_from_db()
                self.assertEqual(self.tracking.active_attempt_token, self.TOKEN)
                self.assertEqual(self.tracking.lock_version, 0)


class RaceResultRevisionApplyTests(TestCase):
    NOW = datetime(2026, 7, 20, 14, 0, tzinfo=dt_timezone.utc)
    TOKEN = "apply-token"

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="result-revision-apply-event",
            original_name="Result Revision Apply Stakes",
            chinese_name="赛果修订应用锦标",
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        self.control = stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=stable_models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=4,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=stable_models.RaceEventLiveState.AWAITING_RESULT,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=2,
            active_attempt_token=self.TOKEN,
            claim_expires_at=self.NOW + timedelta(minutes=2),
        )
        self.source = stable_models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="fixture_source",
            external_race_id="race-1",
        )
        self.participants = []
        for index, name in enumerate(("Alpha", "Beta"), start=1):
            participant = stable_models.RaceEventParticipant.objects.create(
                event=self.event,
                stable_key=f"horse-{index}",
                canonical_name=name,
                review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            )
            stable_models.RaceEventParticipantSourceIdentity.objects.create(
                participant=participant,
                source_identity=self.source,
                external_runner_id=f"runner-{index}",
            )
            self.participants.append(participant)
        self.observation = self._make_observation("provisional", (1, 2), "a")

    def _payload(self, positions):
        return {
            "external_race_id": "race-1",
            "participants": [
                {
                    "external_runner_id": f"runner-{index}",
                    "official_finish_position": position,
                    "status": "finished",
                    "number": str(index),
                    "finish_time": "1:40.00" if index == 1 else "1:40.20",
                    "margin": "" if index == 1 else "1L",
                    "jockey_name": f"Jockey {index}",
                    "trainer_name": f"Trainer {index}",
                }
                for index, position in enumerate(positions, start=1)
            ],
        }

    def _make_observation(self, phase, positions, digest_letter):
        payload = self._payload(positions)
        return stable_models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW,
            parser_version="fixture-v1",
            raw_sha256=digest_letter * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=payload
            ),
            result_phase=phase,
            normalized_payload=payload,
            field_provenance={"participants": "fixture_source"},
            permission_classification="offline_fixture",
        )

    def _marker_evidence(self, observation, marker_type="result_status_official"):
        contract = stable_models.RaceLiveOfficialMarkerContract.objects.create(
            country_region=self.event.country_region,
            source_key=self.source.source_key,
            parser_version=observation.parser_version,
            allowed_marker_types=[
                "result_status_official",
                "stewards_amendment",
            ],
            contract_digest="7" * 64,
            valid_until=self.NOW + timedelta(days=30),
            review_status=stable_models.RaceLiveReviewStatus.APPROVED,
        )
        return stable_models.RaceLiveOfficialMarkerEvidence.objects.create(
            observation=observation,
            contract=contract,
            marker_type=marker_type,
            contract_digest=contract.contract_digest,
            parser_version=contract.parser_version,
            raw_sha256=observation.raw_sha256,
            source_timestamp=self.NOW,
        )

    def _apply(self, **overrides):
        service = getattr(
            race_events,
            "apply_race_result_observation_revision",
            None,
        )
        self.assertTrue(callable(service), "赛果 observation -> revision/pointer CAS 尚未实现")
        values = {
            "observation_id": self.observation.pk,
            "expected_owner_generation": 4,
            "expected_claim_generation": 2,
            "attempt_token": self.TOKEN,
            "now": self.NOW + timedelta(seconds=10),
            "source_authority": "supplemental",
            "official_marker": False,
            "identity_valid": True,
            "payload_complete": True,
            "manual_lock_conflict": False,
            "project_current": False,
        }
        values.update(overrides)
        return service(**values)

    def _renew_claim(self, generation=3, token="next-token"):
        stable_models.RaceEventLiveTracking.objects.filter(pk=self.tracking.pk).update(
            claim_generation=generation,
            active_attempt_token=token,
            claim_expires_at=self.NOW + timedelta(minutes=3),
        )

    def _enable_public_admission(self):
        self.event.race_datetime = self.NOW
        self.event.save(update_fields=("race_datetime", "updated_at"))
        self.source.source_key = "the_racing_api"
        self.source.review_status = stable_models.RaceLiveReviewStatus.APPROVED
        self.source.terms_status = stable_models.RaceSourceTermsStatus.APPROVED
        self.source.automation_allowed = True
        self.source.valid_until = self.NOW + timedelta(days=30)
        self.source.registry_digest = "a" * 64
        self.source.save(
            update_fields=(
                "source_key",
                "review_status",
                "terms_status",
                "automation_allowed",
                "valid_until",
                "registry_digest",
                "updated_at",
            )
        )
        stable_models.RaceLivePublicationPolicy.objects.create(
            scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL,
            scope_key="global",
            mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            registry_digest="a" * 64,
            coverage_proof_digest="b" * 64,
            valid_until=self.NOW + timedelta(days=30),
        )
        for scope_type, scope_key in (
            (
                stable_models.RaceLivePublicationScopeType.REGION,
                self.event.country_region,
            ),
            (
                stable_models.RaceLivePublicationScopeType.SOURCE,
                self.source.source_key,
            ),
            (
                stable_models.RaceLivePublicationScopeType.EVENT,
                str(self.event.pk),
            ),
        ):
            stable_models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                registry_digest="a" * 64,
                coverage_proof_digest="b" * 64,
                valid_until=self.NOW + timedelta(days=30),
            )
        stable_models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key=self.source.source_key,
            max_mode=stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest="b" * 64,
            official_verification_route="bha_result_verification",
            official_verification_route_version="bha-v1",
            official_verification_contract_digest="c" * 64,
            official_terms_evidence_digest="d" * 64,
            official_verification_valid_until=self.NOW + timedelta(days=30),
            enabled=True,
        )
        racecard = stable_models.RaceEventRevision.objects.create(
            event=self.event,
            kind=stable_models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=stable_models.RaceResultPhase.RACECARD,
            content_sha256="9" * 64,
            source_authority=stable_models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        for index, participant in enumerate(self.participants, start=1):
            stable_models.RaceEventRevisionItem.objects.create(
                revision=racecard,
                participant=participant,
                source_order=index,
                internal_order=index,
                status=stable_models.RaceEventRevisionItemStatus.DECLARED,
                horse_number=str(index),
            )
        self.control.current_racecard_revision = racecard
        self.control.last_known_good_racecard_revision = racecard
        self.control.next_racecard_revision_no = 2
        self.control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "next_racecard_revision_no",
                "updated_at",
            )
        )
        return racecard

    def _admit(self, **overrides):
        service = getattr(race_events, "admit_race_live_publication", None)
        self.assertTrue(callable(service), "唯一 publication admission service 尚未实现")
        values = {
            "observation_id": self.observation.pk,
            "expected_owner_generation": 4,
            "expected_claim_generation": 3,
            "attempt_token": "next-token",
            "now": self.NOW + timedelta(seconds=30),
        }
        values.update(overrides)
        return service(**values)

    def test_unique_admission_promotes_complete_tra_shadow_and_freezes_policy_snapshot(self):
        self._enable_public_admission()
        shadow = self._apply().revision
        self._renew_claim()

        decision = self._admit()

        self.assertIs(decision.applied, True)
        self.assertEqual(decision.action, "promote")
        self.assertEqual(decision.reason, "shadow_revision_promoted")
        self.assertEqual(decision.revision.pk, shadow.pk)
        shadow.refresh_from_db()
        self.assertEqual(shadow.published_at, self.NOW + timedelta(seconds=30))
        publication = stable_models.RaceEventRevisionPublication.objects.get(
            revision=shadow
        )
        self.assertEqual(
            publication.policy_versions,
            [
                ["global", "global", 1],
                ["region", self.event.country_region, 1],
                ["source", self.source.source_key, 1],
                ["event", str(self.event.pk), 1],
            ],
        )
        self.assertEqual(publication.allowlist_version, 1)
        self.assertEqual(publication.registry_digest, "a" * 64)
        self.assertEqual(publication.coverage_proof_digest, "b" * 64)
        incident = stable_models.RaceLiveOfficialVerificationIncident.objects.get(
            event=self.event,
            provisional_revision=shadow,
        )
        self.assertEqual(incident.official_route, "bha_result_verification")
        self.assertEqual(incident.official_route_version, "bha-v1")
        self.assertEqual(incident.deadline_at, self.NOW + timedelta(hours=2))
        self.assertEqual(incident.next_probe_at, self.NOW + timedelta(hours=2))
        self.assertEqual(incident.opened_at, self.NOW + timedelta(seconds=30))
        self.assertEqual(incident.status, "open")
        self.assertEqual(
            stable_models.RaceEventResult.objects.filter(event=self.event).count(),
            2,
        )
        self.event.refresh_from_db()
        self.assertEqual(
            self.event.status,
            stable_models.RaceEventStatus.FINISHED,
        )
        self.assertIsNone(self.event.result_confirmed_at)

        import inspect

        forbidden = {
            "project_current",
            "identity_valid",
            "payload_complete",
            "manual_lock_conflict",
        }
        self.assertTrue(
            forbidden.isdisjoint(inspect.signature(race_events.admit_race_live_publication).parameters)
        )

        replay = self._admit(now=self.NOW + timedelta(seconds=35))
        self.assertEqual(replay.action, "replay")
        incident.refresh_from_db()
        self.assertEqual(incident.opened_at, self.NOW + timedelta(seconds=30))
        self.assertEqual(
            stable_models.RaceLiveOfficialVerificationIncident.objects.filter(
                event=self.event,
                provisional_revision=shadow,
            ).count(),
            1,
        )

    def test_admission_requires_an_aware_off_time_before_publication(self):
        self._enable_public_admission()
        self.event.race_datetime = None
        self.event.save(update_fields=("race_datetime", "updated_at"))
        shadow = self._apply().revision
        self._renew_claim()

        decision = self._admit()

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.action, "reject")
        self.assertEqual(decision.reason, "official_deadline_unavailable")
        shadow.refresh_from_db()
        self.assertIsNone(shadow.published_at)
        self.assertEqual(
            stable_models.RaceLiveOfficialVerificationIncident.objects.count(),
            0,
        )

    def test_admission_derives_identity_completeness_and_manual_locks_from_database(self):
        racecard = self._enable_public_admission()
        shadow = self._apply().revision
        self._renew_claim()

        self.participants[0].review_status = stable_models.RaceLiveReviewStatus.PENDING
        self.participants[0].save(update_fields=("review_status", "updated_at"))
        self.assertEqual(self._admit().reason, "participant_not_approved")

        self.participants[0].review_status = stable_models.RaceLiveReviewStatus.APPROVED
        self.participants[0].save(update_fields=("review_status", "updated_at"))
        self.event.manual_lock_flags = {"results": True}
        self.event.save(update_fields=("manual_lock_flags", "updated_at"))
        self.assertEqual(self._admit().reason, "manual_lock_conflict")

        self.event.manual_lock_flags = {}
        self.event.save(update_fields=("manual_lock_flags", "updated_at"))
        racecard.items.filter(participant=self.participants[1]).delete()
        self.assertEqual(self._admit().reason, "participant_set_mismatch")

        shadow.refresh_from_db()
        self.assertIsNone(shadow.published_at)
        self.assertFalse(
            stable_models.RaceEventRevisionPublication.objects.filter(
                revision=shadow
            ).exists()
        )
        self.assertEqual(
            stable_models.RaceEventResult.objects.filter(event=self.event).count(),
            0,
        )

    def test_low_level_supplemental_apply_cannot_bypass_publication_admission(self):
        self._enable_public_admission()

        decision = self._apply(project_current=True)

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.action, "reject")
        self.assertEqual(decision.reason, "publication_admission_required")
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 1)
        self.assertEqual(
            stable_models.RaceEventRevision.objects.get().kind,
            stable_models.RaceEventRevisionKind.RACECARD,
        )
        self.assertEqual(stable_models.RaceEventRevisionPublication.objects.count(), 0)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)

    def test_shadow_apply_creates_immutable_revision_items_evidence_and_pointer_only(self):
        decision = self._apply()
        self.assertIs(decision.applied, True)
        self.assertEqual(decision.action, "apply")
        self.assertEqual(decision.reason, "provisional_result_accepted")
        revision = decision.revision
        self.assertEqual(revision.revision_no, 1)
        self.assertEqual(revision.phase, "provisional")
        self.assertIsNone(revision.published_at)
        self.assertEqual(revision.items.count(), 2)
        self.assertEqual(revision.evidence_links.get().observation_id, self.observation.pk)

        self.control.refresh_from_db()
        self.tracking.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, revision.pk)
        self.assertEqual(self.control.last_known_good_result_revision_id, revision.pk)
        self.assertEqual(self.control.next_result_revision_no, 2)
        self.assertEqual(self.tracking.state, "provisional_result")
        self.assertEqual(self.tracking.active_attempt_token, self.TOKEN)
        self.assertEqual(stable_models.RaceEventResult.objects.filter(event=self.event).count(), 0)

    def test_official_public_apply_supersedes_and_materializes_projection_atomically(self):
        provisional = self._apply().revision
        official = self._make_observation("official", (2, 1), "b")
        self.source.result_authority = "official"
        self.source.review_status = stable_models.RaceLiveReviewStatus.APPROVED
        self.source.reviewed_at = self.NOW
        self.source.save(
            update_fields=(
                "result_authority",
                "review_status",
                "reviewed_at",
                "updated_at",
            )
        )
        self._renew_claim()
        evidence = self._marker_evidence(official)

        decision = self._apply(
            observation_id=official.pk,
            expected_claim_generation=3,
            attempt_token="next-token",
            source_authority="official",
            official_marker=True,
            official_marker_evidence_id=evidence.pk,
            project_current=True,
            now=self.NOW + timedelta(seconds=20),
        )

        self.assertIs(decision.applied, True)
        revision = decision.revision
        self.assertEqual(revision.revision_no, 2)
        self.assertEqual(revision.phase, "official")
        self.assertEqual(revision.supersedes_id, provisional.pk)
        self.assertEqual(revision.published_at, self.NOW + timedelta(seconds=20))
        self.assertEqual(revision.official_confirmed_at, self.NOW + timedelta(seconds=20))
        self.control.refresh_from_db()
        self.tracking.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, revision.pk)
        self.assertEqual(self.control.last_known_good_result_revision_id, provisional.pk)
        self.assertEqual(self.tracking.state, "official_result")
        self.assertEqual(self.tracking.official_published_at, self.NOW + timedelta(seconds=20))
        self.assertEqual(self.event.result_confirmed_at, self.NOW + timedelta(seconds=20))
        publication = stable_models.RaceEventRevisionPublication.objects.get(
            revision=revision
        )
        self.assertEqual(publication.published_at, self.NOW + timedelta(seconds=20))
        self.assertEqual(publication.reason, "direct_public_apply")
        results = list(stable_models.RaceEventResult.objects.filter(event=self.event))
        self.assertEqual([row.finish_position for row in results], [1, 2])
        self.assertEqual([row.official_finish_position for row in results], [2, 1])
        self.assertTrue(all(row.is_confirmed for row in results))

    def test_non_finisher_projection_preserves_status_and_never_displays_internal_order_as_rank(self):
        payload = self._payload((1, None))
        payload["participants"][1]["status"] = "pulled_up"
        payload["participants"][1]["finish_time"] = ""
        payload["participants"][1]["margin"] = ""
        official = stable_models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW,
            parser_version="fixture-v1",
            raw_sha256="f" * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=payload
            ),
            result_phase="official",
            normalized_payload=payload,
            field_provenance={"participants": "fixture_source"},
            permission_classification="offline_fixture",
        )
        self.source.result_authority = "official"
        self.source.review_status = stable_models.RaceLiveReviewStatus.APPROVED
        self.source.reviewed_at = self.NOW
        self.source.save(
            update_fields=(
                "result_authority",
                "review_status",
                "reviewed_at",
                "updated_at",
            )
        )
        evidence = self._marker_evidence(official)

        decision = self._apply(
            observation_id=official.pk,
            source_authority="official",
            official_marker=True,
            official_marker_evidence_id=evidence.pk,
            project_current=True,
        )

        self.assertIs(decision.applied, True)
        non_finisher = stable_models.RaceEventResult.objects.get(
            event=self.event,
            horse_name="Beta",
        )
        self.assertIsNone(non_finisher.official_finish_position)
        self.assertEqual(non_finisher.running_status, "pulled_up")

        from stable import views as stable_views

        stable_views._attach_result_display_positions([non_finisher])
        self.assertEqual(non_finisher.display_finish_position, "中止")
        self.assertNotEqual(non_finisher.display_finish_position, non_finisher.finish_position)

    def test_caller_cannot_spoof_official_authority_for_supplemental_source(self):
        official = self._make_observation("official", (2, 1), "e")

        decision = self._apply(
            observation_id=official.pk,
            source_authority="official",
            official_marker=True,
            project_current=True,
        )

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.action, "reject")
        self.assertEqual(decision.reason, "source_authority_mismatch")
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 0)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)

    def test_official_public_apply_rejects_raw_marker_boolean_without_evidence(self):
        provisional = self._apply().revision
        official = self._make_observation("official", (2, 1), "6")
        self.source.result_authority = stable_models.RaceResultSourceAuthority.OFFICIAL
        self.source.review_status = stable_models.RaceLiveReviewStatus.APPROVED
        self.source.reviewed_at = self.NOW
        self.source.save(
            update_fields=(
                "result_authority",
                "review_status",
                "reviewed_at",
                "updated_at",
            )
        )
        self._renew_claim()

        decision = self._apply(
            observation_id=official.pk,
            expected_claim_generation=3,
            attempt_token="next-token",
            source_authority=stable_models.RaceResultSourceAuthority.OFFICIAL,
            official_marker=True,
            project_current=True,
            now=self.NOW + timedelta(seconds=20),
        )

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.action, "reject")
        self.assertEqual(decision.reason, "official_marker_evidence_required")
        self.assertEqual(
            stable_models.RaceEventRevision.objects.filter(
                kind=stable_models.RaceEventRevisionKind.RESULT
            ).count(),
            1,
        )
        provisional.refresh_from_db()
        self.assertIsNone(provisional.published_at)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)

    def test_same_revision_can_be_audited_and_promoted_from_shadow_to_public(self):
        self._enable_public_admission()
        shadow = self._apply().revision
        self._renew_claim()
        promoted_at = self.NOW + timedelta(seconds=30)

        decision = self._admit(now=promoted_at)

        self.assertIs(decision.applied, True)
        self.assertEqual(decision.action, "promote")
        self.assertEqual(decision.reason, "shadow_revision_promoted")
        self.assertEqual(decision.revision.pk, shadow.pk)
        self.assertEqual(
            stable_models.RaceEventRevision.objects.filter(
                kind=stable_models.RaceEventRevisionKind.RESULT,
            ).count(),
            1,
        )
        self.control.refresh_from_db()
        self.assertEqual(self.control.next_result_revision_no, 2)
        shadow.refresh_from_db()
        self.assertEqual(shadow.published_at, promoted_at)
        publication = stable_models.RaceEventRevisionPublication.objects.get(
            revision=shadow
        )
        self.assertEqual(publication.published_at, promoted_at)
        self.assertEqual(publication.reason, "shadow_promotion")
        self.assertEqual(
            stable_models.RaceEventResult.objects.filter(event=self.event).count(),
            2,
        )
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.provisional_published_at, promoted_at)

    def test_replay_is_idempotent_and_stale_claim_is_rejected_without_writes(self):
        revision = self._apply().revision
        self._renew_claim()
        replay = self._apply(
            expected_claim_generation=3,
            attempt_token="next-token",
        )
        self.assertIs(replay.applied, False)
        self.assertEqual(replay.action, "replay")
        self.assertEqual(replay.revision.pk, revision.pk)
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 1)

        stale = self._apply(
            expected_claim_generation=3,
            attempt_token="stale-token",
        )
        self.assertIs(stale.applied, False)
        self.assertEqual(stale.reason, "claim_mismatch")
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 1)

    def test_conflict_preserves_current_pointer_and_projection(self):
        revision = self._apply().revision
        disagreement = self._make_observation("provisional", (2, 1), "c")
        self._renew_claim()

        decision = self._apply(
            observation_id=disagreement.pk,
            expected_claim_generation=3,
            attempt_token="next-token",
        )

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.action, "conflict")
        self.assertEqual(decision.reason, "supplemental_result_conflict")
        self.control.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, revision.pk)
        self.assertEqual(revision.conflict_status, "pending")
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 1)
        self.assertEqual(stable_models.RaceEventResult.objects.count(), 0)

    def test_unknown_runner_and_expired_claim_fail_closed_before_revision(self):
        bad_payload = self._payload((1, 2))
        bad_payload["participants"][1]["external_runner_id"] = "missing-runner"
        bad = stable_models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW,
            parser_version="fixture-v1",
            raw_sha256="d" * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=bad_payload
            ),
            result_phase="provisional",
            normalized_payload=bad_payload,
        )
        unknown = self._apply(observation_id=bad.pk)
        self.assertIs(unknown.applied, False)
        self.assertEqual(unknown.reason, "participant_identity_missing")
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 0)

        stable_models.RaceEventLiveTracking.objects.filter(pk=self.tracking.pk).update(
            claim_expires_at=self.NOW + timedelta(seconds=5)
        )
        expired = self._apply(now=self.NOW + timedelta(seconds=5))
        self.assertIs(expired.applied, False)
        self.assertEqual(expired.reason, "claim_expired")
        self.assertEqual(stable_models.RaceEventRevision.objects.count(), 0)
class RaceEventLiveCheckpointLeaseValidationTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)
    TOKEN = "checkpoint-token"

    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug="checkpoint-lease-validation-event",
            original_name="Checkpoint Lease Validation Stakes",
            chinese_name="检查点租约验证锦标",
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
        )
        stable_models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=stable_models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=4,
        )
        self.tracking = stable_models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=2,
            active_attempt_token=self.TOKEN,
            claim_expires_at=self.NOW + timedelta(minutes=2),
        )

    def _complete(self, **overrides):
        values = {
            "event_id": self.event.pk,
            "expected_owner_generation": 4,
            "expected_claim_generation": 2,
            "attempt_token": self.TOKEN,
            "now": self.NOW + timedelta(seconds=10),
            "success": True,
            "next_poll_at": self.NOW + timedelta(minutes=3),
            "checkpoint_payload": {"source": "fixture", "status": "unchanged"},
            "observation_sha256": "c" * 64,
        }
        values.update(overrides)
        return race_events.complete_race_event_live_checkpoint(**values)

    def test_expired_claim_is_rejected_even_before_another_worker_reclaims_it(self):
        stable_models.RaceEventLiveTracking.objects.filter(pk=self.tracking.pk).update(
            claim_expires_at=self.NOW + timedelta(seconds=5)
        )

        decision = self._complete(now=self.NOW + timedelta(seconds=5))

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.reason, "claim_expired")
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, self.TOKEN)
        self.assertEqual(self.tracking.claim_generation, 2)
        self.assertEqual(self.tracking.lock_version, 0)
        self.assertEqual(self.tracking.checkpoint_payload, {})

    def test_claim_without_expiry_is_rejected_as_corrupt_lease_without_mutation(self):
        stable_models.RaceEventLiveTracking.objects.filter(pk=self.tracking.pk).update(
            claim_expires_at=None
        )

        decision = self._complete()

        self.assertIs(decision.applied, False)
        self.assertEqual(decision.reason, "claim_missing_expiry")
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.active_attempt_token, self.TOKEN)
        self.assertEqual(self.tracking.claim_generation, 2)
        self.assertEqual(self.tracking.lock_version, 0)
        self.assertEqual(self.tracking.checkpoint_payload, {})

    def test_invalid_payload_and_time_fail_closed(self):
        invalid_cases = (
            ({"success": "true"}, "invalid_success"),
            ({"checkpoint_payload": []}, "invalid_checkpoint"),
            ({"observation_sha256": "bad"}, "invalid_observation_digest"),
            ({"now": self.NOW.replace(tzinfo=None)}, "invalid_now"),
            (
                {"next_poll_at": self.NOW.replace(tzinfo=None)},
                "invalid_next_poll_at",
            ),
        )
        for override, reason in invalid_cases:
            with self.subTest(reason=reason):
                decision = self._complete(**override)
                self.assertIs(decision.applied, False)
                self.assertEqual(decision.reason, reason)
