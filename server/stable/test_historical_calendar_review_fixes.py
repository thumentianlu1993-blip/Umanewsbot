from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    HistoricalRaceCalendarMaintenanceGate,
    HistoricalRaceEventTarget,
    RaceEvent,
    RaceEventPublicPath,
    RaceEventPublicPathKind,
    RaceEventProductCanonicalLink,
    RaceSeries,
)
from stable.services.historical_race_calendar_admission import (
    HistoricalCalendarWriteBlocked,
    enter_historical_calendar_maintenance,
    exit_historical_calendar_maintenance,
)


def event_payload(**overrides):
    values = {
        "year": 2025,
        "edition_year": 2025,
        "slug": "review-fix",
        "original_name": "Review Fix",
        "chinese_name": "审核修复",
        "country_region": "hong_kong",
        "racecourse": "Sha Tin",
        "grade_text": "G1",
        "surface": "turf",
        "local_date": date(2025, 1, 1),
    }
    values.update(overrides)
    return values


class AuthoritativeRaceEventWriteTests(TestCase):
    def test_create_rejects_wrong_public_year(self):
        with self.assertRaises(ValidationError):
            RaceEvent.objects.create(**event_payload(year=2024))

    def test_create_rejects_cross_edition_without_evidence(self):
        with self.assertRaises(ValidationError):
            RaceEvent.objects.create(**event_payload(edition_year=2024))

    def test_update_or_create_uses_same_contract(self):
        event = RaceEvent.objects.create(**event_payload())
        with self.assertRaises(ValidationError):
            RaceEvent.objects.update_or_create(
                pk=event.pk, defaults={"year": 2024}
            )

    def test_queryset_identity_update_is_rejected(self):
        event = RaceEvent.objects.create(**event_payload())
        with self.assertRaises(ValidationError):
            RaceEvent.objects.filter(pk=event.pk).update(year=2024)

    def test_bulk_identity_update_is_rejected(self):
        event = RaceEvent.objects.create(**event_payload())
        event.year = 2024
        with self.assertRaises(ValidationError):
            RaceEvent.objects.bulk_update([event], ["year"])

    def test_legacy_bad_row_allows_non_identity_update(self):
        event = RaceEvent.objects.create(**event_payload())
        # Simulate a row predating Release A without going through the guarded writer.
        RaceEvent._base_manager.filter(pk=event.pk).update(year=2024)
        event.refresh_from_db()
        event.notes = "repair queued"
        event.save(update_fields={"notes"})
        self.assertEqual(event.notes, "repair queued")

    def test_update_fields_ignores_unpersisted_identity_memory(self):
        event = RaceEvent.objects.create(**event_payload())
        event.year = 2024
        event.slug = "must-not-be-persisted"
        event.notes = "notes only"
        event.save(update_fields={"notes"})
        event.refresh_from_db()
        self.assertEqual((event.year, event.slug), (2025, "review-fix"))
        self.assertTrue(
            RaceEventPublicPath.objects.filter(
                event=event,
                year=2025,
                slug="review-fix",
                path_kind=RaceEventPublicPathKind.CANONICAL,
            ).exists()
        )


class CanonicalPathWriteTests(TestCase):
    def test_create_reserves_canonical_path(self):
        event = RaceEvent.objects.create(**event_payload())
        self.assertTrue(
            RaceEventPublicPath.objects.filter(
                event=event,
                year=2025,
                slug="review-fix",
                path_kind=RaceEventPublicPathKind.CANONICAL,
            ).exists()
        )

    def test_bulk_create_uses_same_atomic_path_writer(self):
        event = RaceEvent(**event_payload(slug="bulk-path"))
        RaceEvent.objects.bulk_create([event])
        self.assertTrue(
            RaceEventPublicPath.objects.filter(
                event=event,
                year=2025,
                slug="bulk-path",
                path_kind=RaceEventPublicPathKind.CANONICAL,
            ).exists()
        )

    def test_event_delete_cascades_all_registry_paths(self):
        event = RaceEvent.objects.create(**event_payload(slug="delete-paths"))
        RaceEventPublicPath.objects.create(
            event=event,
            year=2024,
            slug="delete-paths-legacy",
            path_kind=RaceEventPublicPathKind.LEGACY,
        )
        event_id = event.pk

        event.delete()

        self.assertFalse(RaceEvent.objects.filter(pk=event_id).exists())
        self.assertFalse(RaceEventPublicPath.objects.filter(event_id=event_id).exists())

    def test_rename_rotates_old_canonical_to_legacy(self):
        event = RaceEvent.objects.create(**event_payload())
        event.slug = "review-fix-renamed"
        event.save(update_fields={"slug"})
        self.assertTrue(
            RaceEventPublicPath.objects.filter(
                event=event,
                year=2025,
                slug="review-fix",
                path_kind=RaceEventPublicPathKind.LEGACY,
            ).exists()
        )
        self.assertTrue(
            RaceEventPublicPath.objects.filter(
                event=event,
                year=2025,
                slug="review-fix-renamed",
                path_kind=RaceEventPublicPathKind.CANONICAL,
            ).exists()
        )

    def test_legacy_collision_rolls_back_event(self):
        first = RaceEvent.objects.create(**event_payload())
        first.slug = "first-renamed"
        first.save(update_fields={"slug"})
        with self.assertRaises(IntegrityError):
            RaceEvent.objects.create(
                **event_payload(slug="review-fix", original_name="Collision")
            )
        self.assertFalse(RaceEvent.objects.filter(original_name="Collision").exists())


class MaintenanceAdmissionTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="repair-actor")

    def test_active_gate_blocks_normal_writer_and_exit_restores_it(self):
        gate = enter_historical_calendar_maintenance(
            manifest_sha256="a" * 64,
            action_scope_sha256="b" * 64,
            actor=self.actor,
        )
        self.assertEqual(gate.status, "active")
        with self.assertRaises(HistoricalCalendarWriteBlocked):
            RaceEvent.objects.create(**event_payload())
        exit_historical_calendar_maintenance(
            gate=gate,
            actor=self.actor,
            manifest_sha256="a" * 64,
            action_scope_sha256="b" * 64,
        )
        RaceEvent.objects.create(**event_payload())

    def test_active_gate_blocks_target_and_registry_writers(self):
        event = RaceEvent.objects.create(**event_payload())
        series = RaceSeries.objects.create(
            key="gate-series",
            country_region="hong_kong",
            canonical_name_original="Gate Series",
            chinese_name="门禁系列",
        )
        path = RaceEventPublicPath.objects.get(
            event=event, path_kind=RaceEventPublicPathKind.CANONICAL
        )
        target = HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=2025,
            country_region="hong_kong",
        )
        enter_historical_calendar_maintenance(
            manifest_sha256="a" * 64,
            action_scope_sha256="b" * 64,
            actor=self.actor,
        )
        with self.assertRaises(HistoricalCalendarWriteBlocked):
            RaceEventPublicPath.objects.filter(event=event).update(
                reason="blocked"
            )
        with self.assertRaises(HistoricalCalendarWriteBlocked):
            path.delete()
        with self.assertRaises(HistoricalCalendarWriteBlocked):
            target.delete()
        with self.assertRaises(HistoricalCalendarWriteBlocked):
            event.delete()
        self.assertTrue(RaceEvent.objects.filter(pk=event.pk).exists())
        self.assertTrue(RaceEventPublicPath.objects.filter(pk=path.pk).exists())

    def test_only_one_gate_can_be_active(self):
        enter_historical_calendar_maintenance(
            manifest_sha256="a" * 64,
            action_scope_sha256="b" * 64,
            actor=self.actor,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HistoricalRaceCalendarMaintenanceGate.objects.create(
                    manifest_sha256="c" * 64,
                    action_scope_sha256="d" * 64,
                    actor=self.actor,
                    status="active",
                )


class DependencySnapshotTests(TestCase):
    def test_two_reverse_fks_to_same_model_are_kept_separately(self):
        actor = get_user_model().objects.create_user(username="dependency-reviewer")
        event = RaceEvent.objects.create(**event_payload(slug="dependency-main"))
        other = RaceEvent.objects.create(**event_payload(slug="dependency-other"))
        third = RaceEvent.objects.create(**event_payload(slug="dependency-third"))
        RaceEventProductCanonicalLink.objects.create(
            duplicate_event=event,
            canonical_event=other,
            identity_sha256="1" * 64,
            manifest_sha256="2" * 64,
            approved_by=actor,
            approved_at=timezone.now(),
            is_active=True,
        )
        RaceEventProductCanonicalLink.objects.create(
            duplicate_event=third,
            canonical_event=event,
            identity_sha256="3" * 64,
            manifest_sha256="4" * 64,
            approved_by=actor,
            approved_at=timezone.now(),
            is_active=True,
        )
        from stable.services.historical_race_calendar_integrity import (
            _event_dependencies,
        )

        dependencies = _event_dependencies(event)
        product_link_keys = [
            key
            for key in dependencies
            if key.startswith("stable.raceeventproductcanonicallink:")
        ]
        self.assertEqual(len(product_link_keys), 2)
        self.assertEqual(
            sorted(dependencies[key]["count"] for key in product_link_keys),
            [1, 1],
        )
