"""P02 T11/T13：持久化合同，真实数据库约束不由 SQLite 代替。"""
from django.apps import apps
from django.test import TestCase
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from stable import models


class LifecycleStorageTests(TestCase):
    def test_epoch_maturity_receipts_and_recoverable_delivery_are_persisted(self):
        models = {m.__name__: m for m in apps.get_app_config('stable').get_models()}
        for name in ('RaceLifecyclePublicState', 'RaceLifecycleEpochPublication',
                     'RaceLifecycleReceipt', 'RaceLifecycleDelivery'):
            self.assertIn(name, models, f'{name} 不能只放在内存中')
        state = {f.name for f in models['RaceLifecyclePublicState']._meta.fields}
        self.assertTrue({'racecard_maturity', 'result_maturity', 'racecard_deadline_at',
                         'result_deadline_at', 'epoch', 'schedule_generation'} <= state)
        delivery = {f.name for f in models['RaceLifecycleDelivery']._meta.fields}
        self.assertTrue({'lease_token', 'lease_expires_at', 'next_attempt_at'} <= delivery)

    def test_receipt_cannot_be_rewritten_through_queryset(self):
        receipt = models.RaceLifecycleReceipt.objects.create(
            idempotency_key="a" * 64, target_key="unmatched:JP:one",
            kind="scope", recorded_at=timezone.now())
        with self.assertRaises(DatabaseError), transaction.atomic():
            models.RaceLifecycleReceipt.objects.filter(pk=receipt.pk).update(payload={"erase": True})

    def test_visible_state_requires_content_and_epoch_unique(self):
        event = models.RaceEvent.objects.create(year=2026, slug="storage", original_name="Storage")
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.RaceLifecyclePublicState.objects.create(
                event=event, epoch=1, schedule_generation=1,
                result_visibility="visible", policy_digest="a" * 64)
        args = dict(event=event, epoch=1, schedule_generation=1,
                    writer_owner="data_sync", writer_generation=1,
                    snapshot={}, snapshot_sha256="b" * 64, authorization={},
                    admitted_at=timezone.now(), published_at=timezone.now(), reason="test")
        publication = models.RaceLifecycleEpochPublication.objects.create(
            **args, idempotency_key="c" * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.RaceLifecycleEpochPublication.objects.create(**args, idempotency_key="d" * 64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            models.RaceLifecycleEpochPublication.objects.filter(pk=publication.pk).update(snapshot={})
