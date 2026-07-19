from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
from threading import Barrier
import tempfile
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TransactionTestCase

from stable import models
from stable.services import race_events
from stable.services.race_live_manual_official_evidence import (
    apply_race_live_manual_official_evidence,
    load_race_live_manual_official_evidence,
    prepare_race_live_manual_official_evidence,
)
from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    apply_race_live_publication_transition,
)
from stable.test_race_live_publication_transition import (
    RaceLivePublicationTransitionTests,
)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class RaceLivePublicationTransitionPostgresTests(TransactionTestCase):
    reset_sequences = True
    NOW = RaceLivePublicationTransitionTests.NOW
    APPROVED_COMMIT = RaceLivePublicationTransitionTests.APPROVED_COMMIT
    REGISTRY_DIGEST = RaceLivePublicationTransitionTests.REGISTRY_DIGEST
    COVERAGE_DIGEST = RaceLivePublicationTransitionTests.COVERAGE_DIGEST

    setUp = RaceLivePublicationTransitionTests.setUp
    _bundle = RaceLivePublicationTransitionTests._bundle
    _loaded = RaceLivePublicationTransitionTests._loaded
    _provider_snapshot = RaceLivePublicationTransitionTests._provider_snapshot

    def test_rollback_validator_transaction_is_database_read_only(self):
        payload = {
            "event_id": self.event.pk,
            "expected_provisional_revision_id": self.result_revision.pk,
            "planned_policy_snapshot": {},
            "expected_allowlist_version": self.allowlist.version,
            "expected_publication_id": 1,
        }
        data = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollback-manifest.json"
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()

            def attempt_write(**_kwargs):
                models.OperationLog.objects.create(
                    action_type="validator_must_be_read_only",
                    target_type="race_event",
                    target_id=str(self.event.pk),
                )

            with patch(
                "stable.management.commands.validate_race_live_rollback_target.validate_race_live_provisional_rollback_target",
                side_effect=attempt_write,
            ):
                with self.assertRaises(DatabaseError):
                    call_command(
                        "validate_race_live_rollback_target",
                        "--manifest",
                        str(path),
                        "--expected-manifest-sha256",
                        digest,
                        stdout=StringIO(),
                    )
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="validator_must_be_read_only"
            ).exists()
        )

    def test_runner_claim_and_operator_promotion_share_lock_order_without_deadlock(self):
        manifest = self._loaded(self._bundle()["promotion"])
        barrier = Barrier(2)

        def promote():
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                    cursor.execute("SET statement_timeout = '6s'")
                barrier.wait(timeout=5)
                try:
                    result = apply_race_live_publication_transition(
                        manifest,
                        now=self.NOW,
                    )
                    return ("promoted", result["ok"])
                except RaceLivePublicationTransitionError as exc:
                    return ("blocked", str(exc))
            finally:
                connections.close_all()

        def claim():
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                    cursor.execute("SET statement_timeout = '6s'")
                barrier.wait(timeout=5)
                decision = race_events.claim_race_event_live_tracking(
                    event_id=self.event.pk,
                    expected_owner_generation=1,
                    now=self.NOW + self._claim_due_delta(),
                    ttl_seconds=120,
                )
                return ("claimed" if decision.claimed else "not_claimed", decision.reason)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(promote), pool.submit(claim))
            outcomes = [future.result(timeout=10) for future in futures]

        labels = {outcome[0] for outcome in outcomes}
        self.assertTrue(
            {"promoted", "claimed"} & labels,
            outcomes,
        )
        self.assertFalse(
            {"deadlock", "timeout"} & {
                str(value).lower() for outcome in outcomes for value in outcome
            },
            outcomes,
        )

    def test_two_operator_applies_serialize_to_one_apply_and_one_replay(self):
        manifest = self._loaded(self._bundle()["promotion"])
        barrier = Barrier(2)

        def promote():
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                    cursor.execute("SET statement_timeout = '6s'")
                barrier.wait(timeout=5)
                result = apply_race_live_publication_transition(
                    manifest,
                    now=self.NOW,
                )
                return result["replayed"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                future.result(timeout=10)
                for future in (pool.submit(promote), pool.submit(promote))
            ]

        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_publication_transition"
            ).count(),
            1,
        )
        self.assertEqual(
            models.RaceEventRevisionPublication.objects.count(),
            1,
        )

    def test_concurrent_policy_change_is_not_overwritten_by_operator(self):
        manifest = self._loaded(self._bundle()["promotion"])
        barrier = Barrier(2)

        def mutate_policy():
            close_old_connections()
            try:
                with transaction.atomic():
                    policy = (
                        models.RaceLivePublicationPolicy.objects.select_for_update()
                        .get(
                            scope_type=(
                                models.RaceLivePublicationScopeType.EVENT
                            ),
                            scope_key=str(self.event.pk),
                        )
                    )
                    barrier.wait(timeout=5)
                    policy.mode = models.RaceLivePublicationMode.OFF
                    policy.version = 2
                    policy.save(
                        update_fields=("mode", "version", "updated_at")
                    )
                return "mutated"
            finally:
                connections.close_all()

        def promote():
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                    cursor.execute("SET statement_timeout = '6s'")
                barrier.wait(timeout=5)
                try:
                    apply_race_live_publication_transition(
                        manifest,
                        now=self.NOW,
                    )
                    return "promoted"
                except RaceLivePublicationTransitionError:
                    return "blocked"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            mutate_future = pool.submit(mutate_policy)
            promote_future = pool.submit(promote)
            outcomes = {
                mutate_future.result(timeout=10),
                promote_future.result(timeout=10),
            }

        self.assertEqual(outcomes, {"mutated", "blocked"})
        policy = models.RaceLivePublicationPolicy.objects.get(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(self.event.pk),
        )
        self.assertEqual(policy.mode, models.RaceLivePublicationMode.OFF)
        self.assertEqual(policy.version, 2)
        self.assertFalse(
            models.RaceEventRevisionPublication.objects.exists()
        )

    def test_concurrent_allowlist_change_is_not_overwritten_by_operator(self):
        manifest = self._loaded(self._bundle()["promotion"])
        barrier = Barrier(2)

        def mutate_allowlist():
            close_old_connections()
            try:
                with transaction.atomic():
                    allowlist = (
                        models.RaceLiveEventPublicationAllowlist.objects.select_for_update()
                        .get(
                            event_id=self.event.pk,
                            source_key="the_racing_api",
                        )
                    )
                    barrier.wait(timeout=5)
                    allowlist.enabled = False
                    allowlist.version = 2
                    allowlist.save(
                        update_fields=(
                            "enabled",
                            "version",
                            "updated_at",
                        )
                    )
                return "mutated"
            finally:
                connections.close_all()

        def promote():
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                    cursor.execute("SET statement_timeout = '6s'")
                barrier.wait(timeout=5)
                try:
                    apply_race_live_publication_transition(
                        manifest,
                        now=self.NOW,
                    )
                    return "promoted"
                except RaceLivePublicationTransitionError:
                    return "blocked"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            mutate_future = pool.submit(mutate_allowlist)
            promote_future = pool.submit(promote)
            outcomes = {
                mutate_future.result(timeout=10),
                promote_future.result(timeout=10),
            }

        self.assertEqual(outcomes, {"mutated", "blocked"})
        allowlist = models.RaceLiveEventPublicationAllowlist.objects.get(
            event=self.event,
            source_key="the_racing_api",
        )
        self.assertFalse(allowlist.enabled)
        self.assertEqual(allowlist.version, 2)
        self.assertEqual(
            allowlist.official_verification_contract_digest,
            "",
        )
        self.assertFalse(
            models.RaceEventRevisionPublication.objects.exists()
        )

    def test_manual_conflict_evidence_and_disable_share_one_postgres_transaction(self):
        bundle = self._bundle()
        apply_race_live_publication_transition(
            self._loaded(bundle["promotion"]),
            now=self.NOW,
        )
        incident = models.RaceLiveOfficialVerificationIncident.objects.get(
            event=self.event
        )
        participants = [
            {
                "participant_id": participant.pk,
                "position": index,
            }
            for index, participant in enumerate(
                self.participants,
                start=1,
            )
        ]
        participants[0]["position"], participants[1]["position"] = (
            participants[1]["position"],
            participants[0]["position"],
        )
        submission = {
            "approved_commit": self.APPROVED_COMMIT,
            "event_id": self.event.pk,
            "revision_id": self.result_revision.pk,
            "incident_id": incident.pk,
            "source_url": (
                "https://www.britishhorseracing.com/racing/results/"
            ),
            "observed_at": self.NOW.isoformat(),
            "evidence_sha256": "9" * 64,
            "outcome": "available",
            "marker_type": "weighed_in",
            "participants": participants,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            prepared = prepare_race_live_manual_official_evidence(
                submission=submission,
                output_root=root,
                run_id="postgres-conflict",
            )
            receipt = load_race_live_manual_official_evidence(
                receipt_path=prepared["receipt_path"],
                expected_receipt_sha256=prepared["receipt_sha256"],
                expected_approved_commit=self.APPROVED_COMMIT,
            )
            result = apply_race_live_manual_official_evidence(
                receipt=receipt,
                receipt_sha256=prepared["receipt_sha256"],
                disable_manifest=self._loaded(bundle["disable"]),
                now=self.NOW,
            )

        self.assertEqual(result["comparison"], "conflict")
        incident.refresh_from_db()
        self.assertEqual(
            incident.status,
            models.RaceLiveOfficialVerificationIncidentStatus.ESCALATED,
        )
        event_policy = models.RaceLivePublicationPolicy.objects.get(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(self.event.pk),
        )
        self.assertEqual(event_policy.mode, models.RaceLivePublicationMode.SHADOW)
        self.assertTrue(
            models.RaceLiveOfficialMarkerEvidence.objects.exists()
        )

    def _claim_due_delta(self):
        # Keep the claim due relative to the fixture's persisted next_poll_at.
        from datetime import timedelta

        return timedelta(minutes=10)
