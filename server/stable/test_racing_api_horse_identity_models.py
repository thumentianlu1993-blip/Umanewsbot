from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    ExternalDataSource,
    ExternalHorse,
    HorseExternalIdentity,
    HorseExternalIdentityStatus,
    HorseNameKind,
    HorseNameVariant,
    HorseProfile,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)


class RacingApiHorseIdentityModelTests(TestCase):
    def _reviewer(self):
        return get_user_model().objects.create_user(
            username=f"identity-reviewer-{get_user_model().objects.count()}",
        )

    def _profile(self, name: str) -> HorseProfile:
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja=name,
            target_zh="",
            racing_region=RacingRegion.OTHER,
            is_active=True,
        )
        return HorseProfile.objects.create(
            primary_term=term,
            original_name=name,
            english_name=name,
            racing_region=RacingRegion.OTHER,
        )

    def _external_horse(self, horse_id: str = "hrs_123") -> ExternalHorse:
        return ExternalHorse.objects.create(
            source=ExternalDataSource.THE_RACING_API,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.OTHER,
            horse_id=horse_id,
            horse_name="Montjeu (IRE)",
            horse_name_en="Montjeu",
            normalized_horse_name="montjeu",
            birth_date=datetime.date(1996, 4, 4),
            breeder_name="Sir James Goldsmith",
            father_name="Sadler's Wells",
            mother_name="Floripedes",
            damsire_name="Top Ville",
            sire_external_id="hrs_10",
            dam_external_id="hrs_11",
            damsire_external_id="hrs_12",
        )

    def test_the_racing_api_profile_fields_are_first_class(self):
        horse = self._external_horse()

        self.assertEqual(horse.source, "the_racing_api")
        self.assertEqual(horse.breeder_name, "Sir James Goldsmith")
        self.assertEqual(horse.damsire_name, "Top Ville")
        self.assertEqual(horse.sire_external_id, "hrs_10")
        self.assertEqual(horse.dam_external_id, "hrs_11")
        self.assertEqual(horse.damsire_external_id, "hrs_12")

    def test_provider_identity_is_globally_unique_within_namespace(self):
        first = self._profile("Montjeu")
        second = self._profile("Montjeu Duplicate")
        HorseExternalIdentity.objects.create(
            horse_profile=first,
            source=ExternalDataSource.THE_RACING_API,
            namespace="horse",
            external_id="hrs_123",
            status=HorseExternalIdentityStatus.VERIFIED,
            evidence_url="https://example.test/evidence/montjeu",
            payload_sha256="a" * 64,
            verified_at=timezone.now(),
            verified_by=self._reviewer(),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            HorseExternalIdentity.objects.create(
                horse_profile=second,
                source=ExternalDataSource.THE_RACING_API,
                namespace="horse",
                external_id="hrs_123",
            )

    def test_verified_identity_requires_hash_evidence_and_timestamp(self):
        identity = HorseExternalIdentity(
            horse_profile=self._profile("Evidence Horse"),
            source=ExternalDataSource.THE_RACING_API,
            namespace="horse",
            external_id="hrs_999",
            status=HorseExternalIdentityStatus.VERIFIED,
        )

        with self.assertRaises(ValidationError):
            identity.full_clean()

    def test_verified_identity_database_constraint_requires_reviewer(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            HorseExternalIdentity.objects.create(
                horse_profile=self._profile("Database Constraint Horse"),
                source=ExternalDataSource.THE_RACING_API,
                namespace="horse",
                external_id="hrs_db_guard",
                status=HorseExternalIdentityStatus.VERIFIED,
                evidence_url="https://example.test/evidence/db-guard",
                payload_sha256="b" * 64,
                verified_at=timezone.now(),
            )

    def test_identity_and_name_variant_payload_hashes_are_database_checked(self):
        profile = self._profile("Invalid Hash Horse")
        horse = self._external_horse("hrs_invalid_hash")

        with self.assertRaises(IntegrityError), transaction.atomic():
            HorseExternalIdentity.objects.create(
                horse_profile=profile,
                source=ExternalDataSource.THE_RACING_API,
                namespace="horse",
                external_id="hrs_bad_identity_hash",
                payload_sha256="not-a-sha",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HorseNameVariant.objects.create(
                external_horse=horse,
                name_text="Invalid Hash Horse",
                language=SourceLanguage.ENGLISH,
                script="latin",
                name_kind=HorseNameKind.SOURCE_DISPLAY,
                normalized_strict="invalid hash horse",
                normalized_loose="invalid hash horse",
                source=ExternalDataSource.THE_RACING_API,
                payload_sha256="not-a-sha",
            )

    def test_name_variant_requires_at_least_one_bound_entity(self):
        variant = HorseNameVariant(
            name_text="MONTJEU",
            language=SourceLanguage.ENGLISH,
            script="latin",
            name_kind=HorseNameKind.OFFICIAL_LATIN,
            normalized_strict="montjeu",
            normalized_loose="montjeu",
            source=ExternalDataSource.THE_RACING_API,
        )

        with self.assertRaises(ValidationError):
            variant.full_clean()

    def test_name_variant_cannot_bridge_canonical_and_external_entities(self):
        profile = self._profile("Almond Eye")
        external_horse = self._external_horse("hrs_almond")

        japanese = HorseNameVariant.objects.create(
            horse_profile=profile,
            name_text="アーモンドアイ",
            language=SourceLanguage.JAPANESE,
            script="katakana",
            name_kind=HorseNameKind.REGISTERED,
            normalized_strict="アーモンドアイ",
            normalized_loose="アーモンドアイ",
            source=ExternalDataSource.NETKEIBA,
            is_official=True,
        )
        overseas = HorseNameVariant.objects.create(
            external_horse=external_horse,
            name_text="Almond Eye (JPN)",
            language=SourceLanguage.ENGLISH,
            script="latin",
            name_kind=HorseNameKind.SOURCE_DISPLAY,
            country_suffix="JPN",
            normalized_strict="almond eye",
            normalized_loose="almond eye",
            source=ExternalDataSource.THE_RACING_API,
        )

        self.assertEqual(japanese.horse_profile_id, profile.pk)
        self.assertIsNone(overseas.horse_profile_id)
        self.assertEqual(overseas.external_horse_id, external_horse.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            HorseNameVariant.objects.create(
                horse_profile=profile,
                external_horse=external_horse,
                name_text="Almond Eye bridge",
                language=SourceLanguage.ENGLISH,
                script="latin",
                name_kind=HorseNameKind.SOURCE_DISPLAY,
                normalized_strict="almond eye bridge",
                normalized_loose="almond eye bridge",
                source=ExternalDataSource.THE_RACING_API,
            )
