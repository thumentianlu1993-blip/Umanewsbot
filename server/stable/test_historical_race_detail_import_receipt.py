from __future__ import annotations

import hashlib

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    HistoricalBatchPhase,
    HistoricalBatchRun,
    HistoricalRaceDetailImportLayer,
    HistoricalRaceDetailImportReceipt,
    HistoricalRaceDetailImportReceiptStatus,
)


class HistoricalRaceDetailImportReceiptTests(TestCase):
    def setUp(self):
        self.runner = HistoricalBatchRun.objects.create(
            run_id="receipt-test-run",
            batch_id="historical-detail-import",
            phase=HistoricalBatchPhase.APPLY,
            network_enabled=False,
            write_enabled=True,
            image_id="sha256:" + "1" * 64,
            image_revision="a" * 40,
            artifact_root="/tmp/historical-detail-import",
            plan_sha256="2" * 64,
        )
        self.user = get_user_model().objects.create_user(username="receipt-reviewer")

    @staticmethod
    def _chunk_sha(seed: str = "chunk") -> str:
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def _payload(
        self,
        *,
        target_ids: list[int] | None = None,
        chunk_payload: str = "payload-v1",
        approval_identity: str = "approval-v1",
    ) -> dict:
        return {
            "target_ids": target_ids or [101, 102],
            "chunk_payload": chunk_payload,
            "approval_identity": approval_identity,
        }

    def _receipt(self, **overrides) -> HistoricalRaceDetailImportReceipt:
        chunk_sha256 = overrides.pop("chunk_sha256", self._chunk_sha())
        layer = overrides.pop(
            "layer", HistoricalRaceDetailImportLayer.HISTORICAL_THROUGH_2024
        )
        values = {
            "receipt_id": HistoricalRaceDetailImportReceipt.build_receipt_id(
                layer=layer,
                chunk_sha256=chunk_sha256,
            ),
            "runner": self.runner,
            "layer": layer,
            "bundle_sha256": "3" * 64,
            "chunk_sha256": chunk_sha256,
            "status": HistoricalRaceDetailImportReceiptStatus.STARTED,
            "target_count": 2,
            "initial_payload": self._payload(),
        }
        values.update(overrides)
        return HistoricalRaceDetailImportReceipt(**values)

    def _abandoned_receipt(self, **overrides) -> HistoricalRaceDetailImportReceipt:
        receipt = self._receipt(**overrides)
        receipt.save()
        receipt.status = HistoricalRaceDetailImportReceiptStatus.ABANDONED
        receipt.abandoned_at = timezone.now()
        receipt.abandoned_by = self.user
        receipt.abandon_reason = "write interrupted before completion"
        receipt.reconcile_payload = {"verified_target_ids": [101, 102]}
        receipt.save()
        return receipt

    def test_receipt_id_is_layer_nul_chunk_sha256(self):
        chunk_sha256 = self._chunk_sha("identity")
        expected = hashlib.sha256(
            (
                HistoricalRaceDetailImportLayer.CURRENT_YEAR_DUE
                + "\0"
                + chunk_sha256
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(
            HistoricalRaceDetailImportReceipt.build_receipt_id(
                layer=HistoricalRaceDetailImportLayer.CURRENT_YEAR_DUE,
                chunk_sha256=chunk_sha256,
            ),
            expected,
        )
        receipt = self._receipt(receipt_id="f" * 64)
        with self.assertRaises(ValidationError):
            receipt.full_clean()

    def test_started_receipt_validates_target_identity(self):
        receipt = self._receipt()
        receipt.full_clean()
        receipt.save()

        for changes in (
            {"target_count": 0},
            {"target_count": 3},
            {"initial_payload": {**self._payload(), "target_ids": [101, 101]}},
            {"bundle_sha256": "not-a-sha"},
        ):
            invalid = self._receipt(**changes)
            with self.assertRaises(ValidationError):
                invalid.full_clean()

    def test_database_constraint_enforces_mutually_exclusive_states(self):
        receipt = self._receipt()
        receipt.save()

        with self.assertRaises(IntegrityError), transaction.atomic():
            HistoricalRaceDetailImportReceipt.objects.filter(pk=receipt.pk).update(
                status=HistoricalRaceDetailImportReceiptStatus.COMPLETED,
                completed_at=timezone.now(),
                completion_payload={},
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            HistoricalRaceDetailImportReceipt.objects.filter(pk=receipt.pk).update(
                status=HistoricalRaceDetailImportReceiptStatus.ABANDONED,
                abandoned_at=timezone.now(),
                abandoned_by=self.user,
                abandon_reason="abandoned",
                reconcile_payload={"target_ids": [101, 102]},
                completed_at=timezone.now(),
                completion_payload={"target_ids": [101, 102]},
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            HistoricalRaceDetailImportReceipt.objects.filter(pk=receipt.pk).update(target_count=0)

        with self.assertRaises(IntegrityError), transaction.atomic():
            HistoricalRaceDetailImportReceipt.objects.filter(pk=receipt.pk).update(layer="unknown")

    def test_allows_only_started_to_terminal_transition(self):
        receipt = self._receipt()
        receipt.save()
        receipt.status = HistoricalRaceDetailImportReceiptStatus.COMPLETED
        receipt.completed_at = timezone.now()
        receipt.completion_payload = {"target_ids": [101, 102], "result": "ok"}
        receipt.save()

        receipt.status = HistoricalRaceDetailImportReceiptStatus.STARTED
        receipt.completed_at = None
        receipt.completion_payload = {}
        with self.assertRaises(ValidationError):
            receipt.save()

        receipt.refresh_from_db()
        receipt.completion_payload = {"target_ids": [101, 102], "result": "tampered"}
        with self.assertRaises(ValidationError):
            receipt.save()

        abandoned = self._abandoned_receipt(chunk_sha256=self._chunk_sha("abandoned"))
        abandoned.status = HistoricalRaceDetailImportReceiptStatus.COMPLETED
        abandoned.completed_at = timezone.now()
        abandoned.completion_payload = {"result": "late"}
        abandoned.abandoned_at = None
        abandoned.abandoned_by = None
        abandoned.abandon_reason = ""
        abandoned.reconcile_payload = {}
        with self.assertRaises(ValidationError):
            abandoned.save()

    def test_identity_fields_are_immutable_after_creation(self):
        receipt = self._receipt()
        receipt.save()

        changes = {
            "receipt_id": "f" * 64,
            "runner": HistoricalBatchRun.objects.create(
                run_id="another-receipt-run",
                batch_id="historical-detail-import",
                phase=HistoricalBatchPhase.APPLY,
                network_enabled=False,
                write_enabled=True,
                image_id="sha256:" + "4" * 64,
                image_revision="b" * 40,
                artifact_root="/tmp/another-historical-detail-import",
                plan_sha256="5" * 64,
            ),
            "layer": HistoricalRaceDetailImportLayer.CURRENT_YEAR_DUE,
            "bundle_sha256": "6" * 64,
            "chunk_sha256": self._chunk_sha("changed"),
            "target_count": 1,
            "initial_payload": self._payload(target_ids=[101]),
        }
        for field_name, value in changes.items():
            current = HistoricalRaceDetailImportReceipt.objects.get(pk=receipt.pk)
            setattr(current, field_name, value)
            with self.assertRaises(ValidationError, msg=field_name):
                current.save()

    def test_supersedes_requires_abandoned_matching_targets_and_new_identities(self):
        abandoned = self._abandoned_receipt()
        replacement = self._receipt(
            chunk_sha256=self._chunk_sha("replacement"),
            initial_payload=self._payload(
                chunk_payload="payload-v2",
                approval_identity="approval-v2",
            ),
            supersedes_receipt=abandoned,
        )
        replacement.full_clean()
        replacement.save()

        cases = (
            {
                "chunk_sha256": self._chunk_sha("wrong-targets"),
                "initial_payload": self._payload(
                    target_ids=[101, 103],
                    chunk_payload="payload-v3",
                    approval_identity="approval-v3",
                ),
            },
            {
                "chunk_sha256": self._chunk_sha("same-payload"),
                "initial_payload": self._payload(
                    chunk_payload="payload-v1",
                    approval_identity="approval-v4",
                ),
            },
            {
                "chunk_sha256": self._chunk_sha("same-approval"),
                "initial_payload": self._payload(
                    chunk_payload="payload-v4",
                    approval_identity="approval-v1",
                ),
            },
        )
        for values in cases:
            invalid = self._receipt(supersedes_receipt=abandoned, **values)
            with self.assertRaises(ValidationError):
                invalid.full_clean()

        active = self._receipt(chunk_sha256=self._chunk_sha("active"))
        active.save()
        invalid = self._receipt(
            chunk_sha256=self._chunk_sha("supersedes-active"),
            supersedes_receipt=active,
            initial_payload=self._payload(
                chunk_payload="payload-v5",
                approval_identity="approval-v5",
            ),
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_supersedes_rejects_self_reference_and_cycle(self):
        first = self._abandoned_receipt()
        first.supersedes_receipt = first
        with self.assertRaises(ValidationError):
            first.full_clean()
        first.refresh_from_db()

        second = self._abandoned_receipt(
            chunk_sha256=self._chunk_sha("second"),
            initial_payload=self._payload(
                chunk_payload="payload-v2",
                approval_identity="approval-v2",
            ),
            supersedes_receipt=first,
        )
        first.supersedes_receipt = second
        with self.assertRaises(ValidationError):
            first.full_clean()
