"""PostgreSQL-only RED contracts for recovery concurrency.

SQLite covers functional semantics in the sibling test modules.  It is not an
equivalent substitute for PostgreSQL advisory locks and row locks.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
from pathlib import Path
from threading import Barrier
import tempfile
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from stable import models
from stable.tests.test_race_result_recovery_application_projection import (
    APPROVAL_SHA,
    MANIFEST_SHA,
    NOW,
    RecoveryApplicationFixtureMixin,
)


@skipUnless(
    connection.vendor == "postgresql",
    "PostgreSQL advisory/row-lock recovery contract",
)
class RaceResultRecoveryPostgresConcurrencyTests(
    RecoveryApplicationFixtureMixin,
    TransactionTestCase,
):
    reset_sequences = True

    def _projection_service(self):
        return importlib.import_module(
            "stable.services.race_result_recovery_projection"
        )

    def _prepared_projection(self, slug):
        event = self._event(slug)
        source = self._source(event)
        for index, name in enumerate(
            ("Horse Alpha", "Horse Beta", "Horse Gamma"), start=1
        ):
            self._participant(
                event,
                source,
                runner_id=f"runner-{index}",
                number=str(index),
                name=name,
            )
        control = models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
            owner_generation=0,
        )
        receipt_service = importlib.import_module(
            "stable.services.race_result_recovery_receipts"
        )
        validated = receipt_service.validate_recovery_official_receipt(
            receipt=self._receipt(event),
            route_registry=self._route_registry(),
            expected_event_id=event.pk,
            now=NOW,
        )
        return event, control, validated, self._projection_service()

    def test_concurrent_shared_endpoint_approvals_cannot_form_a_chain(self):
        service = self._projection_service()
        event_a = self._event("pg-canonical-a")
        event_b = self._event("pg-canonical-b")
        event_c = self._event("pg-canonical-c")
        barrier = Barrier(2)

        def approve(duplicate_id, canonical_id, digest):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                link = service.approve_canonical_link(
                    duplicate_event_id=duplicate_id,
                    canonical_event_id=canonical_id,
                    identity_sha256=digest,
                    manifest_sha256=MANIFEST_SHA,
                    approved_by_id=self.user.pk,
                    approved_at=NOW,
                )
                return ("applied", link.pk)
            except service.CanonicalIdentityApprovalError as exc:
                return ("blocked", exc.reason_code)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                approve, event_a.pk, event_b.pk, "1" * 64
            )
            second = executor.submit(
                approve, event_b.pk, event_c.pk, "2" * 64
            )
            outcomes = [first.result(timeout=20), second.result(timeout=20)]

        self.assertEqual(
            sorted(item[0] for item in outcomes),
            ["applied", "blocked"],
        )
        self.assertIn(
            next(value for state, value in outcomes if state == "blocked"),
            {"canonical_chain_forbidden", "canonical_cycle_forbidden"},
        )
        link_model = models.RaceEventProductCanonicalLink
        self.assertEqual(link_model.objects.filter(is_active=True).count(), 1)

    def test_concurrent_same_manifest_apply_is_one_write_and_one_idempotent_replay(
        self,
    ):
        event, control, validated, projection = self._prepared_projection(
            "pg-concurrent-apply"
        )
        barrier = Barrier(2)

        with tempfile.TemporaryDirectory() as temporary:
            ledger_root = Path(temporary)

            def apply():
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    result = projection.apply_recovery_event(
                        event_id=event.pk,
                        validated_receipt=validated,
                        manifest_sha256=MANIFEST_SHA,
                        approval_sha256=APPROVAL_SHA,
                        expected_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
                        expected_generation=control.owner_generation,
                        expected_before_identity=projection.current_recovery_event_identity(
                            event.pk
                        ),
                        route_registry=self._route_registry(),
                        ledger_root=ledger_root,
                        applied_by_id=self.user.pk,
                        now=NOW,
                    )
                    return result["status"]
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(apply)
                second = executor.submit(apply)
                outcomes = [first.result(timeout=30), second.result(timeout=30)]

        self.assertEqual(sorted(outcomes), ["already_applied", "applied"])
        event.refresh_from_db()
        control.refresh_from_db()
        self.assertEqual(event.results.count(), 3)
        self.assertEqual(
            models.RaceResultObservation.objects.filter(
                source_identity__event=event
            ).count(),
            1,
        )
        self.assertEqual(
            models.RaceEventRevision.objects.filter(
                event=event,
                kind=models.RaceEventRevisionKind.RESULT,
                phase=models.RaceResultPhase.OFFICIAL,
            ).count(),
            1,
        )
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_result_recovery_apply",
                target_id=str(event.pk),
            ).count(),
            1,
        )
        self.assertEqual(
            control.write_owner,
            models.RaceEventProjectionWriteOwner.HISTORICAL,
        )
        self.assertEqual(control.owner_generation, 1)
