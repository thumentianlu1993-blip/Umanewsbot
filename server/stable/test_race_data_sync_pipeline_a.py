from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone as dt_timezone
import importlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, migrations, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable.services import race_events, race_live_fixtures, race_live_racecard_sync
from stable import test_race_live_multiregion_pipeline as _multiregion_tests


NOW = datetime(2026, 8, 2, 4, 0, tzinfo=dt_timezone.utc)


def _pipeline():
    """Load the slice-A public service without masking a missing implementation."""

    return importlib.import_module("stable.services.race_data_sync_pipeline")


def _contract(
    *,
    provider: str = "hkjc",
    region: str = "hong_kong",
    allowed_fields: list[str] | None = None,
    source_class: str | None = None,
) -> dict:
    roster = _pipeline().build_race_data_provider_roster()
    entry = next(
        item
        for item in roster.entries
        if item.provider == provider and region in item.regions
    )
    return {
        "schema_version": 1,
        "provider": provider,
        "region": region,
        "data_kind": "racecard",
        "contract_version": "racecard-v1",
        "contract_digest": entry.contract_digest,
        "registry_digest": roster.registry_digest,
        "source_class": source_class or entry.source_class,
        "automation_allowed": True,
        "allowed_fields": allowed_fields
        or [
                "participants.horse_name",
                "participants.number",
                "participants.draw",
                "participants.jockey_name",
                "participants.status",
                "off_time",
            ],
    }


def _payload(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "external_race_id": "hk-2026-08-02-01",
        "off_time": "2026-08-02T15:10:00+08:00",
        "region": "hong_kong",
        "course": "Sha Tin",
        "race_name": "Test Cup",
        "race_status": "racecard",
        "participants": [
            {
                "external_runner_id": "horse-1",
                "horse_name": "Alpha",
                "number": "1",
                "draw": "3",
                "jockey_name": "First Jockey",
                "status": "declared",
            }
        ],
    }
    payload.update(overrides)
    return payload


class RacecardNormalizedObservationContractTests(SimpleTestCase):
    def test_provider_neutral_normalization_preserves_complete_provenance(self):
        normalized = _pipeline().normalize_racecard_observation(
            payload=_payload(),
            contract=_contract(),
            observed_at=NOW,
            source_updated_at=NOW - timedelta(minutes=1),
            parser_version="hkjc-racecard-v1",
            raw_sha256="a" * 64,
            source_url="https://example.invalid/race/hk-1",
            task_id="celery-task-1",
            run_id="run-1",
        )

        self.assertEqual(normalized.normalized_payload, _payload())
        self.assertEqual(
            normalized.provenance,
            {
                "provider": "hkjc",
                "region": "hong_kong",
                "source_class": "official_operator",
                "source_url": "https://example.invalid/race/hk-1",
                "external_race_id": "hk-2026-08-02-01",
                "observed_at": NOW,
                "source_updated_at": NOW - timedelta(minutes=1),
                "parser_version": "hkjc-racecard-v1",
                "raw_sha256": "a" * 64,
                "normalized_sha256": normalized.normalized_sha256,
                "task_id": "celery-task-1",
                "run_id": "run-1",
                "registry_digest": _contract()["registry_digest"],
                "contract_version": "racecard-v1",
                "contract_digest": _contract()["contract_digest"],
                "automation_allowed": True,
                "allowed_fields": tuple(_contract()["allowed_fields"]),
            },
        )

    def test_strict_schema_rejects_extra_key_naive_time_nan_and_oversize(self):
        pipeline = _pipeline()
        invalid_payloads = (
            _payload(copyright_comment="must not enter normalized data"),
            _payload(off_time="2026-08-02T15:10:00"),
            _payload(odds=math.nan),
            _payload(participants=_payload()["participants"] * 101),
        )

        for payload in invalid_payloads:
            with self.subTest(payload=list(payload)):
                with self.assertRaises(ValueError):
                    pipeline.normalize_racecard_observation(
                        payload=payload,
                        contract=_contract(),
                        observed_at=NOW,
                        source_updated_at=None,
                        parser_version="hkjc-racecard-v1",
                        raw_sha256="a" * 64,
                        source_url="https://example.invalid/race/hk-1",
                        task_id="celery-task-1",
                        run_id="run-1",
                    )

    def test_secret_material_is_removed_before_raw_persistence_or_logging(self):
        sanitized = _pipeline().sanitize_provider_raw_payload(
            {
                "race": _payload(),
                "Authorization": "Basic very-secret",
                "api_key": "paid-secret",
                "password": "also-secret",
                "request_signature": "signed-secret",
            }
        )

        rendered = repr(sanitized)
        for secret in (
            "very-secret",
            "paid-secret",
            "also-secret",
            "signed-secret",
        ):
            self.assertNotIn(secret, rendered)
        self.assertEqual(sanitized["race"], _payload())

    def test_normalization_preserves_schedule_candidates_and_optional_odds(self):
        allowed_fields = [
            *_contract()["allowed_fields"],
            "local_start_time",
            "timezone_name",
            "status",
            "participants.odds",
            "participants.popularity",
        ]
        payload = _payload(
            local_start_time="15:10:00",
            timezone_name="Asia/Macau",
            race_status=models.RaceEventStatus.POSTPONED,
            participants=[
                {
                    **_payload()["participants"][0],
                    "odds": "7/4",
                    "popularity": "1",
                }
            ],
        )

        normalized = _pipeline().normalize_racecard_observation(
            payload=payload,
            contract=_contract(allowed_fields=allowed_fields),
            observed_at=NOW,
            source_updated_at=NOW,
            parser_version="hkjc-racecard-v1",
            raw_sha256="a" * 64,
            source_url="https://example.invalid/race/hk-1",
            task_id="celery-task-1",
            run_id="run-1",
        )

        self.assertEqual(normalized.normalized_payload, payload)


class RaceDataProviderRosterContractTests(SimpleTestCase):
    def test_versioned_roster_has_all_confirmed_providers_and_true_source_classes(self):
        roster = _pipeline().build_race_data_provider_roster()
        expected = {
            "hkjc": ({"hong_kong"}, "official_operator"),
            "jra": ({"japan_jra"}, "official_operator"),
            "nar": ({"japan_nar"}, "official_operator"),
            "france_galop": ({"france"}, "official_operator"),
            "equibase": ({"united_states"}, "official_operator"),
            "hri": ({"ireland"}, "official_operator"),
            "the_racing_api": (
                {
                    "hong_kong",
                    "japan_jra",
                    "japan_nar",
                    "united_kingdom",
                    "france",
                    "united_states",
                    "ireland",
                },
                "licensed_api",
            ),
            "sporting_life": (
                {"united_kingdom"},
                "trusted_publisher",
            ),
            "zeturf": ({"france"}, "trusted_publisher"),
            "horse_racing_nation": (
                {"united_states"},
                "trusted_publisher",
            ),
        }

        self.assertEqual(roster.schema_version, 2)
        self.assertRegex(roster.registry_digest, r"\A[0-9a-f]{64}\Z")
        self.assertTrue(roster.verify_digest())
        self.assertEqual(
            {entry.provider for entry in roster.entries},
            set(expected),
        )
        for entry in roster.entries:
            with self.subTest(provider=entry.provider):
                regions, source_class = expected[entry.provider]
                self.assertEqual(set(entry.regions), regions)
                self.assertEqual(entry.source_class, source_class)
                self.assertIn(entry.adapter_status, {"implemented", "proof_required"})
                self.assertFalse(entry.transport_enabled)
                self.assertFalse(entry.apply_enabled)
                self.assertRegex(entry.contract_version, r"\A[a-z0-9._-]+\Z")
                self.assertRegex(entry.contract_digest, r"\A[0-9a-f]{64}\Z")
                self.assertEqual(
                    tuple(entry.allowed_fields),
                    tuple(sorted(set(entry.allowed_fields))),
                )
                self.assertIn("participants.horse_name", entry.allowed_fields)

    def test_roster_lookup_fails_closed_for_unknown_region_field_and_bad_digest(self):
        roster = _pipeline().build_race_data_provider_roster()

        self.assertIsNone(
            roster.resolve(
                provider="hkjc",
                region="united_states",
                field_name="participants.horse_name",
            )
        )
        self.assertIsNone(
            roster.resolve(
                provider="hkjc",
                region="hong_kong",
                field_name="unregistered_field",
            )
        )
        with self.assertRaises(ValueError):
            _pipeline().build_race_data_provider_roster(
                expected_registry_digest="0" * 64
            )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api", "hkjc"),
        RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
        RACE_DATA_SYNC_ENABLED_FIELDS=("participants.jockey_name",),
    )
    def test_runtime_roster_admits_only_implemented_provider_and_enabled_field(self):
        roster = _pipeline().build_race_data_provider_roster()
        tra = next(entry for entry in roster.entries if entry.provider == "the_racing_api")
        hkjc = next(entry for entry in roster.entries if entry.provider == "hkjc")

        self.assertTrue(tra.apply_enabled)
        self.assertIn("participants.jockey_name", tra.allowed_fields)
        self.assertIn("off_time", tra.allowed_fields)
        self.assertFalse(hkjc.apply_enabled)
        self.assertEqual(hkjc.adapter_status, "proof_required")
        self.assertIsNone(
            roster.resolve(
                provider="hkjc",
                region="hong_kong",
                field_name="participants.jockey_name",
            )
        )


class RacecardRunnerMergeContractTests(SimpleTestCase):
    def test_source_gap_preserves_runner_but_explicit_withdrawal_applies(self):
        previous = (
            {
                "external_runner_id": "horse-1",
                "horse_name": "Alpha",
                "number": "1",
                "status": "declared",
            },
            {
                "external_runner_id": "horse-2",
                "horse_name": "Beta",
                "number": "2",
                "status": "declared",
            },
        )

        source_gap = race_live_racecard_sync.merge_race_live_racecard_participants(
            previous=previous,
            incoming=(previous[0],),
        )
        self.assertEqual(source_gap["missing_runner_source_gaps"], ("horse-2",))
        self.assertEqual(source_gap["participants"][1]["status"], "declared")

        withdrawn = race_live_racecard_sync.merge_race_live_racecard_participants(
            previous=previous,
            incoming=(
                previous[0],
                {**previous[1], "status": "withdrawn"},
            ),
        )
        self.assertEqual(withdrawn["missing_runner_source_gaps"], ())
        self.assertEqual(withdrawn["participants"][1]["status"], "withdrawn")


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
    RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
)
class RacecardFieldReconciliationContractTests(TestCase):
    def setUp(self):
        self.event = self._event(slug="racecard-a")
        self.other_event = self._event(slug="racecard-b")
        self.hkjc = self._source(self.event, "hkjc")
        self.tra = self._source(self.event, "the_racing_api")

    @staticmethod
    def _event(*, slug: str):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name="Test Cup",
            chinese_name="测试杯",
            country_region=models.RacingRegion.HONG_KONG,
            racecourse="Sha Tin",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=datetime(2026, 8, 2, 7, 0, tzinfo=dt_timezone.utc),
            timezone_name="Asia/Hong_Kong",
            local_date=date(2026, 8, 2),
            local_start_time=datetime(2026, 8, 2, 15, 0).time(),
        )

    @staticmethod
    def _source(event, source_key):
        return models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key=source_key,
            external_race_id="hk-2026-08-02-01",
            host=f"{source_key}.example.invalid",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
        )

    def _observation(
        self,
        source,
        *,
        jockey="First Jockey",
        suffix="1",
        updated=NOW,
        observed=None,
        participant_overrides=None,
        payload_overrides=None,
        provenance_overrides=None,
        allowed_fields=None,
    ):
        participant = {
            **_payload()["participants"][0],
            "jockey_name": jockey,
            **(participant_overrides or {}),
        }
        payload = _payload(
            participants=[participant],
            **(payload_overrides or {}),
        )
        roster = _pipeline().build_race_data_provider_roster()
        roster_entry = next(
            entry for entry in roster.entries if entry.provider == source.source_key
        )
        provenance = {
            "provider": source.source_key,
            "region": "hong_kong",
            "source_class": roster_entry.source_class,
            "registry_digest": roster.registry_digest,
            "contract_version": roster_entry.contract_version,
            "contract_digest": roster_entry.contract_digest,
            "automation_allowed": True,
            "allowed_fields": allowed_fields or _contract()["allowed_fields"],
            **(provenance_overrides or {}),
        }
        decision = race_events.record_race_result_observation(
            source_identity_id=source.pk,
            observed_at=observed or NOW + timedelta(seconds=int(suffix)),
            source_updated_at=updated,
            parser_version="racecard-v1",
            raw_sha256=suffix.rjust(64, "a"),
            result_phase=models.RaceResultPhase.RACECARD,
            normalized_payload=payload,
            field_provenance=provenance,
            parse_warnings=[],
            permission_classification="trusted_automation",
        )
        self.assertTrue(decision.recorded, decision.reason)
        return decision.observation

    def _reconcile(self, observation, *, event=None, allow_schedule_apply=False):
        return _pipeline().reconcile_racecard_observation(
            observation_id=observation.pk,
            expected_event_id=(event or self.event).pk,
            allow_schedule_apply=allow_schedule_apply,
            task_id="celery-task-1",
            run_id="run-1",
        )

    def test_event_identity_mismatch_is_zero_write(self):
        observation = self._observation(self.tra)

        decision = self._reconcile(observation, event=self.other_event)

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason, "event_identity_mismatch")
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldChange.objects.exists())

    def test_same_value_replays_and_same_source_newer_version_corrects(self):
        observation = self._observation(self.tra, suffix="1")
        first = self._reconcile(observation)
        replay = self._reconcile(observation)
        correction = self._reconcile(
            self._observation(
                self.tra,
                jockey="Corrected Jockey",
                suffix="2",
                updated=NOW + timedelta(minutes=1),
            )
        )

        self.assertEqual(first.status, "applied")
        self.assertEqual(replay.status, "replayed")
        self.assertEqual(correction.status, "applied")
        runner = models.RaceEventRunner.objects.get(event=self.event)
        self.assertEqual(runner.jockey_name, "Corrected Jockey")

    def test_higher_priority_api_replaces_official_source_without_review(self):
        models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="horse-1",
            horse_name="Alpha",
            horse_number="1",
            barrier="3",
            jockey_name="HKJC Jockey",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={"the_racing_api": "horse-1"},
        )
        models.RaceEventFieldAuthority.objects.create(
            event=self.event,
            subject_type=models.RaceEventFieldSubjectType.PARTICIPANT,
            subject_key="horse-1",
            field_name="jockey_name",
            authority_level=200,
            source_class="official_operator",
            source_key="hkjc",
            observed_at=NOW,
            value_sha256="f" * 64,
        )

        conflict = self._reconcile(
            self._observation(self.tra, jockey="TRA Jockey", suffix="2")
        )

        self.assertEqual(conflict.status, "applied")
        runner = models.RaceEventRunner.objects.get(event=self.event)
        self.assertEqual(runner.jockey_name, "TRA Jockey")
        change = models.RaceEventFieldChange.objects.filter(
            event=self.event,
            field_name="jockey_name",
        ).latest("id")
        self.assertTrue(change.applied)
        self.assertEqual(change.decision, "applied")
        self.assertEqual(change.source_class, "licensed_api")

    def test_manual_lock_blocks_all_provider_overwrite(self):
        self._reconcile(self._observation(self.tra, jockey="Locked Jockey", suffix="1"))
        runner = models.RaceEventRunner.objects.get(event=self.event)
        runner.manual_lock_flags = {"jockey_name": True}
        runner.save(update_fields=("manual_lock_flags", "updated_at"))

        blocked = self._reconcile(
            self._observation(
                self.tra,
                jockey="Provider Correction",
                suffix="2",
                updated=NOW + timedelta(minutes=1),
            )
        )

        self.assertEqual(blocked.status, "replayed")
        runner.refresh_from_db()
        self.assertEqual(runner.jockey_name, "Locked Jockey")
        change = models.RaceEventFieldChange.objects.filter(
            event=self.event,
            field_name="jockey_name",
        ).latest("id")
        self.assertEqual(change.decision, "rejected")
        self.assertEqual(change.rejection_reason, "manual_lock")

    def test_contract_provider_mismatch_is_zero_write(self):
        observation = self._observation(
            self.tra,
            provenance_overrides={"provider": "hkjc"},
        )

        decision = self._reconcile(observation)

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason, "source_contract_mismatch")
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldChange.objects.exists())

    def test_contract_region_mismatch_is_zero_write(self):
        observation = self._observation(
            self.tra,
            provenance_overrides={"region": "united_states"},
        )

        decision = self._reconcile(observation)

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason, "source_contract_mismatch")
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldChange.objects.exists())

    def test_contract_allowed_fields_mismatch_is_zero_write(self):
        observation = self._observation(
            self.tra,
            allowed_fields=[
                "participants.horse_name",
                "participants.number",
                "off_time",
            ],
        )

        decision = self._reconcile(observation)

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason, "source_contract_mismatch")
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldChange.objects.exists())

    def _assert_schedule_candidates(self, race_status):
        original = {
            "race_datetime": self.event.race_datetime,
            "local_start_time": self.event.local_start_time,
            "timezone_name": self.event.timezone_name,
            "status": self.event.status,
        }
        schedule_fields = [
            "off_time",
            "local_start_time",
            "timezone_name",
            "status",
            "participants.horse_name",
            "participants.number",
            "participants.draw",
            "participants.jockey_name",
            "participants.status",
        ]
        observation = self._observation(
            self.tra,
            payload_overrides={
                "off_time": "2026-08-02T15:10:00+08:00",
                "local_start_time": "15:10:00",
                "timezone_name": "Asia/Macau",
                "race_status": race_status,
            },
            allowed_fields=schedule_fields,
        )

        decision = self._reconcile(observation)

        self.assertIn(decision.status, {"applied", "replayed"})
        self.event.refresh_from_db()
        self.assertEqual(
            {
                "race_datetime": self.event.race_datetime,
                "local_start_time": self.event.local_start_time,
                "timezone_name": self.event.timezone_name,
                "status": self.event.status,
            },
            original,
        )
        changes = {
            change.field_name: change
            for change in models.RaceEventFieldChange.objects.filter(
                event=self.event,
                subject_type=models.RaceEventFieldSubjectType.EVENT,
            )
        }
        self.assertEqual(
            set(changes),
            {
                "race_datetime",
                "local_date",
                "local_start_time",
                "timezone_name",
                "status",
            },
        )
        self.assertTrue(all(not change.applied for change in changes.values()))
        self.assertTrue(
            all(change.decision == "rejected" for change in changes.values())
        )
        self.assertTrue(
            all(
                change.rejection_reason == "schedule_apply_disabled"
                for change in changes.values()
            )
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED_FIELDS=(
            "off_time",
            "local_start_time",
            "timezone_name",
            "status",
            "participants.horse_name",
            "participants.number",
            "participants.draw",
            "participants.jockey_name",
            "participants.status",
        )
    )
    def test_schedule_tuple_applies_and_bumps_lifecycle_generation(self):
        models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.ENFORCE,
            schedule_generation=3,
            claim_token="active-claim",
            claim_generation=4,
            claim_expires_at=NOW + timedelta(minutes=5),
        )
        observation = self._observation(
            self.tra,
            payload_overrides={
                "off_time": "2026-08-03T15:10:00+08:00",
                "local_start_time": "15:10:00",
                "timezone_name": "Asia/Macau",
                "race_status": models.RaceEventStatus.POSTPONED,
            },
            allowed_fields=[
                "off_time",
                "local_start_time",
                "timezone_name",
                "status",
                "participants.horse_name",
                "participants.number",
                "participants.draw",
                "participants.jockey_name",
                "participants.status",
            ],
        )

        decision = self._reconcile(observation, allow_schedule_apply=True)

        self.assertEqual(decision.status, "applied")
        self.event.refresh_from_db()
        self.assertEqual(
            self.event.race_datetime,
            datetime(2026, 8, 3, 7, 10, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(self.event.local_date, date(2026, 8, 3))
        self.assertEqual(self.event.local_start_time.isoformat(), "15:10:00")
        self.assertEqual(self.event.timezone_name, "Asia/Macau")
        self.assertEqual(self.event.status, models.RaceEventStatus.POSTPONED)
        lifecycle = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.assertEqual(lifecycle.schedule_generation, 4)
        self.assertEqual(lifecycle.claim_token, "")
        self.assertIsNone(lifecycle.claim_expires_at)
        self.assertEqual(lifecycle.last_source_key, "the_racing_api")
        schedule_changes = models.RaceEventFieldChange.objects.filter(
            event=self.event,
            subject_type=models.RaceEventFieldSubjectType.EVENT,
        )
        self.assertEqual(schedule_changes.filter(applied=True).count(), 5)
        self.assertEqual(
            set(schedule_changes.values_list("operation_mode", flat=True)),
            {"slice_c"},
        )

    def test_postponed_and_full_schedule_tuple_are_candidates_only(self):
        self._assert_schedule_candidates(models.RaceEventStatus.POSTPONED)

    def test_cancelled_and_full_schedule_tuple_are_candidates_only(self):
        self._assert_schedule_candidates(models.RaceEventStatus.CANCELLED)

    @override_settings(
        RACE_DATA_SYNC_ENABLED_FIELDS=tuple(
            sorted(
                {
                    *_contract()["allowed_fields"],
                    "participants.odds",
                    "participants.popularity",
                }
            )
        )
    )
    def test_best_effort_odds_and_popularity_apply_with_full_audit(self):
        allowed_fields = [
            *_contract()["allowed_fields"],
            "participants.odds",
            "participants.popularity",
        ]
        observation = self._observation(
            self.tra,
            participant_overrides={"odds": "7/4", "popularity": "1"},
            allowed_fields=allowed_fields,
        )

        decision = self._reconcile(observation)

        self.assertEqual(decision.status, "applied")
        runner = models.RaceEventRunner.objects.get(event=self.event)
        self.assertEqual(runner.odds_value, "7/4")
        self.assertEqual(runner.popularity, "1")
        audited = set(
            models.RaceEventFieldChange.objects.filter(
                event=self.event,
                subject_key="horse-1",
            ).values_list("field_name", flat=True)
        )
        self.assertTrue({"odds_value", "popularity"}.issubset(audited))

    def test_odds_and_popularity_are_not_applied_when_runtime_fields_exclude_them(self):
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="horse-1",
            horse_name="Alpha",
            horse_number="1",
            barrier="3",
            jockey_name="First Jockey",
            odds_value="9/1",
            popularity="9",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={"the_racing_api": "horse-1"},
        )
        observation = self._observation(
            self.tra,
            participant_overrides={"odds": "7/4", "popularity": "1"},
            allowed_fields=[
                *_contract()["allowed_fields"],
                "participants.odds",
                "participants.popularity",
            ],
        )

        decision = self._reconcile(observation)

        self.assertIn(decision.status, {"applied", "replayed"})
        runner.refresh_from_db()
        self.assertEqual(runner.odds_value, "9/1")
        self.assertEqual(runner.popularity, "9")
        self.assertFalse(
            models.RaceEventFieldChange.objects.filter(
                observation=observation,
                field_name__in=("odds_value", "popularity"),
                applied=True,
            ).exists()
        )

    def test_missing_best_effort_odds_does_not_fail_racecard(self):
        decision = self._reconcile(self._observation(self.tra))

        self.assertEqual(decision.status, "applied")
        runner = models.RaceEventRunner.objects.get(event=self.event)
        self.assertEqual(runner.odds_value, "")
        self.assertEqual(runner.popularity, "")

    def test_same_opaque_runner_id_from_other_provider_requires_mapping_review(self):
        models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="horse-1",
            horse_name="Alpha",
            jockey_name="Shared Jockey",
            source_refs={"hkjc": "horse-1"},
        )
        decision = self._reconcile(
            self._observation(self.tra, jockey="Shared Jockey", suffix="2")
        )

        self.assertEqual(decision.status, "needs_review")
        self.assertEqual(
            models.RaceEventRunner.objects.filter(event=self.event).count(),
            1,
        )
        self.assertFalse(
            models.RaceEventFieldChange.objects.filter(
                observation_id=decision.observation_id,
                applied=True,
            ).exists()
        )

    def _assert_unmapped_legacy_runner_is_not_claimed(self, *, source_refs, suffix):
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id=f"legacy-runner-{suffix}",
            horse_name="Legacy Locked Horse",
            horse_number="8",
            barrier="9",
            jockey_name="Legacy Locked Jockey",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs=source_refs,
        )
        original = {
            "horse_name": runner.horse_name,
            "horse_number": runner.horse_number,
            "barrier": runner.barrier,
            "jockey_name": runner.jockey_name,
            "running_status": runner.running_status,
            "source_refs": runner.source_refs,
            "dynamic_updated_at": runner.dynamic_updated_at,
        }
        observation = self._observation(
            self.tra,
            suffix=suffix,
            participant_overrides={
                "external_runner_id": runner.external_runner_id,
                "horse_name": "Incoming Horse",
                "number": "1",
                "draw": "3",
                "jockey_name": "Incoming Jockey",
                "status": models.RaceRunnerStatus.WITHDRAWN,
            },
        )

        decision = self._reconcile(observation)

        self.assertEqual(decision.status, "needs_review")
        self.assertEqual(decision.reason, "runner_identity_mapping_required")
        runner.refresh_from_db()
        self.assertEqual(
            {
                "horse_name": runner.horse_name,
                "horse_number": runner.horse_number,
                "barrier": runner.barrier,
                "jockey_name": runner.jockey_name,
                "running_status": runner.running_status,
                "source_refs": runner.source_refs,
                "dynamic_updated_at": runner.dynamic_updated_at,
            },
            original,
        )
        self.assertFalse(
            models.RaceEventFieldChange.objects.filter(
                observation=observation,
                applied=True,
            ).exists()
        )

    def test_empty_source_refs_runner_requires_approved_mapping_before_takeover(self):
        self._assert_unmapped_legacy_runner_is_not_claimed(
            source_refs={},
            suffix="31",
        )

    def test_other_provider_legacy_source_refs_require_mapping_before_takeover(self):
        self._assert_unmapped_legacy_runner_is_not_claimed(
            source_refs={
                "source_key": "hkjc",
                "external_runner_id": "legacy-runner-32",
            },
            suffix="32",
        )

    def test_different_provider_ids_share_runner_only_with_deterministic_mapping(self):
        participant = models.RaceEventParticipant.objects.create(
            event=self.event,
            stable_key="mapped-horse",
            canonical_name="Mapped Horse",
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant,
            source_identity=self.tra,
            external_runner_id="tra-horse-1",
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant,
            source_identity=self.hkjc,
            external_runner_id="hkjc-horse-9",
        )
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="hkjc-horse-9",
            horse_name="Mapped Horse",
            jockey_name="Old Jockey",
            source_refs={
                "the_racing_api": "tra-horse-1",
                "hkjc": "hkjc-horse-9",
            },
        )

        decision = self._reconcile(
            self._observation(
                self.tra,
                jockey="Mapped New Jockey",
                suffix="2",
                participant_overrides={
                    "external_runner_id": "tra-horse-1",
                    "horse_name": "Mapped Horse",
                },
            )
        )

        self.assertEqual(decision.status, "applied")
        self.assertEqual(
            models.RaceEventRunner.objects.filter(event=self.event).count(),
            1,
        )
        runner.refresh_from_db()
        self.assertEqual(runner.jockey_name, "Mapped New Jockey")
        self.assertEqual(runner.source_refs["the_racing_api"], "tra-horse-1")

    def test_observed_at_is_watermark_when_source_updated_at_missing(self):
        first_observation = self._observation(
            self.tra,
            jockey="First Jockey",
            suffix="1",
            updated=None,
            observed=NOW + timedelta(seconds=10),
        )
        newer_observation = self._observation(
            self.tra,
            jockey="Newer Jockey",
            suffix="2",
            updated=None,
            observed=NOW + timedelta(seconds=20),
        )

        first = self._reconcile(first_observation)
        newer = self._reconcile(newer_observation)

        self.assertEqual(first.status, "applied")
        self.assertEqual(newer.status, "applied")
        self.assertEqual(
            models.RaceEventRunner.objects.get(event=self.event).jockey_name,
            "Newer Jockey",
        )
        self.assertEqual(
            models.RaceEventRunner.objects.get(event=self.event).dynamic_updated_at,
            NOW + timedelta(seconds=20),
        )

    def test_stale_and_equal_freshness_do_not_regress_runner_watermark(self):
        current = self._observation(
            self.tra,
            jockey="Current Jockey",
            suffix="41",
            updated=NOW + timedelta(seconds=30),
        )
        older = self._observation(
            self.tra,
            jockey="Older Jockey",
            suffix="42",
            updated=NOW + timedelta(seconds=20),
        )
        equal = self._observation(
            self.tra,
            jockey="Equal Conflict",
            suffix="43",
            updated=NOW + timedelta(seconds=30),
        )

        self.assertEqual(self._reconcile(current).status, "applied")
        runner = models.RaceEventRunner.objects.get(event=self.event)
        self.assertEqual(runner.dynamic_updated_at, NOW + timedelta(seconds=30))
        self.assertEqual(self._reconcile(current).status, "replayed")
        self.assertEqual(self._reconcile(older).status, "replayed")
        runner.refresh_from_db()
        self.assertEqual(runner.dynamic_updated_at, NOW + timedelta(seconds=30))
        self.assertEqual(self._reconcile(equal).status, "replayed")
        runner.refresh_from_db()
        self.assertEqual(runner.dynamic_updated_at, NOW + timedelta(seconds=30))

    def test_newer_observation_without_applied_field_does_not_advance_watermark(self):
        current = self._observation(
            self.tra,
            jockey="Stable Jockey",
            suffix="51",
            updated=NOW + timedelta(seconds=30),
        )
        metadata_only = self._observation(
            self.tra,
            jockey="Stable Jockey",
            suffix="52",
            updated=NOW + timedelta(seconds=40),
            payload_overrides={"race_name": "Metadata-only revision"},
        )

        self.assertEqual(self._reconcile(current).status, "applied")
        self.assertEqual(self._reconcile(metadata_only).status, "replayed")
        runner = models.RaceEventRunner.objects.get(event=self.event)
        self.assertEqual(runner.dynamic_updated_at, NOW + timedelta(seconds=30))

    def test_missing_source_time_out_of_order_is_review_and_equal_replay_is_stable(self):
        current = self._observation(
            self.tra,
            jockey="Current Jockey",
            suffix="1",
            updated=None,
            observed=NOW + timedelta(seconds=30),
        )
        older = self._observation(
            self.tra,
            jockey="Older Jockey",
            suffix="2",
            updated=None,
            observed=NOW + timedelta(seconds=20),
        )
        same_time_conflict = self._observation(
            self.tra,
            jockey="Same Time Conflict",
            suffix="3",
            updated=None,
            observed=NOW + timedelta(seconds=30),
        )

        self.assertEqual(self._reconcile(current).status, "applied")
        self.assertEqual(self._reconcile(current).status, "replayed")
        self.assertEqual(self._reconcile(older).status, "replayed")
        self.assertEqual(
            self._reconcile(same_time_conflict).status,
            "replayed",
        )
        self.assertEqual(
            models.RaceEventRunner.objects.get(event=self.event).jockey_name,
            "Current Jockey",
        )

    def test_source_priority_replaces_legacy_neutral_authority(self):
        models.RaceEventFieldAuthority.objects.create(
            event=self.event,
            subject_type=models.RaceEventFieldSubjectType.PARTICIPANT,
            subject_key="horse-1",
            field_name="jockey_name",
            authority_level=255,
            source_key="legacy-source",
            value_sha256="f" * 64,
        )

        decision = self._reconcile(
            self._observation(self.tra, jockey="Current Jockey", suffix="1")
        )

        self.assertEqual(decision.status, "applied")
        change = models.RaceEventFieldChange.objects.latest("id")
        self.assertEqual(change.authority_level, 0)
        authority = models.RaceEventFieldAuthority.objects.get(
            event=self.event,
            subject_key="horse-1",
            field_name="jockey_name",
        )
        self.assertEqual(authority.authority_level, 300)
        self.assertEqual(authority.source_class, "licensed_api")

    def test_field_change_schema_carries_provider_neutral_audit_contract(self):
        required_fields = {
            "observation",
            "source_class",
            "source_updated_at",
            "parser_version",
            "raw_sha256",
            "normalized_sha256",
            "registry_digest",
            "contract_version",
            "contract_digest",
            "celery_task_id",
            "decision",
        }

        missing = set()
        for field_name in required_fields:
            try:
                models.RaceEventFieldChange._meta.get_field(field_name)
            except FieldDoesNotExist:
                missing.add(field_name)
        self.assertEqual(missing, set())


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("france",),
    RACE_DATA_SYNC_ENABLED_FIELDS=(
        "off_time",
        "local_start_time",
        "participants.horse_name",
        "participants.number",
        "participants.draw",
        "participants.jockey_name",
        "participants.status",
    ),
)
class RacecardScheduleIsolationContractTests(TestCase):
    NOW = _multiregion_tests.RaceLiveRacecardRefreshBehaviorTests.NOW
    setUp = _multiregion_tests.RaceLiveRacecardRefreshBehaviorTests.setUp

    def _legacy_refresh(self, *, jockey="New Jockey"):
        return race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="9" * 64,
            normalized_racecard={
                "external_race_id": "fr-refresh-1",
                "off_time": "2026-07-20T13:05:00+00:00",
                "region": "FR",
                "course": "ParisLongchamp",
                "race_name": "France Racecard Refresh",
                "race_status": "Racecard",
                "participants": (
                    {
                        "external_runner_id": "runner-1",
                        "horse_name": "Alpha",
                        "number": "1",
                        "draw": "3",
                        "jockey_name": jockey,
                        "status": models.RaceRunnerStatus.WITHDRAWN,
                    },
                ),
            },
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=(),
        RACE_DATA_SYNC_ENABLED_REGIONS=(),
        RACE_DATA_SYNC_ENABLED_FIELDS=(),
    )
    def test_legacy_tra_default_closed_keeps_evidence_but_zero_mutation(self):
        before_revisions = models.RaceEventRevision.objects.count()
        before_revision_id = self.control.current_racecard_revision_id
        original_race_datetime = self.event.race_datetime
        original_local_start_time = self.event.local_start_time

        decision = self._legacy_refresh()

        self.assertFalse(decision.applied)
        self.assertEqual(decision.reason, "field_runtime_admission_closed")
        self.assertTrue(models.RaceResultObservation.objects.exists())
        self.assertEqual(models.RaceEventRevision.objects.count(), before_revisions)
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_racecard_revision_id,
            before_revision_id,
        )
        self.assertEqual(
            self.control.current_racecard_revision.items.count(),
            1,
        )
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldAuthority.objects.exists())
        self.assertFalse(
            models.RaceEventFieldChange.objects.filter(applied=True).exists()
        )
        self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime, original_race_datetime)
        self.assertEqual(self.event.local_start_time, original_local_start_time)

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
        RACE_DATA_SYNC_ENABLED_REGIONS=("france",),
        RACE_DATA_SYNC_ENABLED_FIELDS=("participants.jockey_name",),
    )
    def test_legacy_tra_partial_field_cannot_second_write_other_fields(self):
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="runner-1",
            horse_name="Alpha",
            horse_number="8",
            barrier="9",
            jockey_name="Old Jockey",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={
                "source_key": "the_racing_api",
                "external_runner_id": "runner-1",
            },
        )

        decision = self._legacy_refresh(jockey="Only New Jockey")

        self.assertTrue(decision.applied, decision.reason)
        runner.refresh_from_db()
        self.assertEqual(runner.jockey_name, "Only New Jockey")
        self.assertEqual(runner.horse_number, "8")
        self.assertEqual(runner.barrier, "9")
        self.assertEqual(runner.running_status, models.RaceRunnerStatus.DECLARED)
        self.assertEqual(
            set(
                models.RaceEventFieldChange.objects.filter(applied=True)
                .values_list("field_name", flat=True)
            ),
            {"jockey_name"},
        )

    def test_slice_a_does_not_apply_schedule_field_before_slice_c(self):
        original_race_datetime = self.event.race_datetime
        original_local_start_time = self.event.local_start_time

        decision = race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="e" * 64,
            normalized_racecard={
                "external_race_id": "fr-refresh-1",
                "off_time": "2026-07-20T13:05:00+00:00",
                "region": "FR",
                "course": "ParisLongchamp",
                "race_name": "France Racecard Refresh",
                "race_status": "Racecard",
                "participants": (
                    {
                        "external_runner_id": "runner-1",
                        "horse_name": "Alpha",
                        "number": "1",
                        "draw": "3",
                        "jockey_name": "New Jockey",
                        "status": "declared",
                    },
                ),
            },
        )

        self.assertTrue(decision.applied, decision.reason)
        self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime, original_race_datetime)
        self.assertEqual(self.event.local_start_time, original_local_start_time)
        self.assertTrue(
            models.RaceEventFieldChange.objects.filter(
                event=self.event,
                field_name="race_datetime",
                applied=False,
            ).exists()
        )

    def test_legacy_tra_refresh_cannot_bypass_provider_neutral_field_ledger(self):
        decision = race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="f" * 64,
            normalized_racecard={
                "external_race_id": "fr-refresh-1",
                "off_time": "2026-07-20T13:05:00+00:00",
                "region": "FR",
                "course": "ParisLongchamp",
                "race_name": "France Racecard Refresh",
                "race_status": "Racecard",
                "participants": (
                    {
                        "external_runner_id": "runner-1",
                        "horse_name": "Alpha",
                        "number": "9",
                        "draw": "3",
                        "jockey_name": "New Jockey",
                        "status": models.RaceRunnerStatus.WITHDRAWN,
                    },
                ),
            },
        )

        self.assertTrue(decision.applied, decision.reason)
        changes = list(
            models.RaceEventFieldChange.objects.filter(event=self.event)
            .select_related("observation")
            .order_by("id")
        )
        self.assertEqual(
            {change.field_name for change in changes},
            {
                "horse_name",
                "horse_number",
                "barrier",
                "jockey_name",
                "running_status",
                "race_datetime",
                "local_date",
                "local_start_time",
            },
        )
        for change in changes:
            with self.subTest(field=change.field_name):
                self.assertIsNotNone(change.observation_id)
                self.assertEqual(change.source_key, "the_racing_api")
                self.assertEqual(change.source_class, "licensed_api")
                self.assertEqual(change.authority_level, 0)
                self.assertRegex(change.raw_sha256, r"\A[0-9a-f]{64}\Z")
                self.assertRegex(change.normalized_sha256, r"\A[0-9a-f]{64}\Z")
                self.assertRegex(change.registry_digest, r"\A[0-9a-f]{64}\Z")
                self.assertTrue(change.contract_version)
                self.assertRegex(change.contract_digest, r"\A[0-9a-f]{64}\Z")
                self.assertEqual(
                    change.operation_mode,
                    (
                        "slice_c"
                        if change.field_name
                        in {"race_datetime", "local_date", "local_start_time"}
                        else "slice_a"
                    ),
                )
        schedule_changes = {
            change.field_name: change
            for change in changes
            if change.field_name
            in {"race_datetime", "local_date", "local_start_time"}
        }
        self.assertTrue(all(not row.applied for row in schedule_changes.values()))
        self.assertTrue(
            all(
                row.rejection_reason == "schedule_apply_disabled"
                for row in schedule_changes.values()
            )
        )


class RaceDataRawRetentionContractTests(TestCase):
    def setUp(self):
        self.event = RacecardFieldReconciliationContractTests._event(
            slug="retention-race"
        )
        self.source = RacecardFieldReconciliationContractTests._source(
            self.event, "hkjc"
        )
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _observation(self, name, *, retention_until, hold=False):
        path = self.root / name
        path.write_text('{"race":"raw"}', encoding="utf-8")
        return models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=NOW - timedelta(days=100),
            parser_version="hkjc-racecard-v1",
            raw_sha256=(name[0] * 64),
            normalized_sha256=(name[-1] * 64),
            result_phase=models.RaceResultPhase.RACECARD,
            normalized_payload=_payload(),
            field_provenance={"raw_hold": hold},
            raw_artifact_path=str(path),
            raw_size_bytes=path.stat().st_size,
            retention_until=retention_until,
            permission_classification="trusted_automation",
        )

    def test_cleanup_removes_only_expired_unheld_raw_and_keeps_hash_and_ledger(self):
        expired = self._observation(
            "a1", retention_until=NOW - timedelta(seconds=1)
        )
        held = self._observation(
            "b2", retention_until=NOW - timedelta(seconds=1), hold=True
        )
        current = self._observation(
            "c3", retention_until=NOW + timedelta(days=1)
        )

        result = _pipeline().cleanup_expired_race_data_raw_payloads(
            now=NOW,
            batch_size=100,
        )

        self.assertEqual(result.cleaned, 1)
        self.assertEqual(result.held, 1)
        expired.refresh_from_db()
        held.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(expired.raw_artifact_path, "")
        self.assertIsNone(expired.raw_size_bytes)
        self.assertEqual(expired.raw_sha256, "a" * 64)
        self.assertFalse((self.root / "a1").exists())
        self.assertTrue((self.root / "b2").exists())
        self.assertTrue((self.root / "c3").exists())
        self.assertTrue(models.RaceResultObservation.objects.filter(pk=expired.pk).exists())

    def test_cleanup_never_deletes_symlink_target_or_out_of_root_path(self):
        symlinked = self._observation(
            "d4", retention_until=NOW - timedelta(seconds=1)
        )
        with TemporaryDirectory() as outside_directory:
            outside_root = Path(outside_directory)
            symlink_target = outside_root / "target.json"
            symlink_target.write_text("target", encoding="utf-8")
            symlink_path = Path(symlinked.raw_artifact_path)
            symlink_path.unlink()
            symlink_path.symlink_to(symlink_target)

            outside_path = outside_root / "outside.json"
            outside_path.write_text("outside", encoding="utf-8")
            out_of_root = self._observation(
                "e5", retention_until=NOW - timedelta(seconds=1)
            )
            out_of_root.raw_artifact_path = str(outside_path)
            out_of_root.save(update_fields=("raw_artifact_path", "updated_at"))

            with self.settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)):
                result = _pipeline().cleanup_expired_race_data_raw_payloads(
                    now=NOW,
                    batch_size=100,
                )

            self.assertEqual(result.cleaned, 0)
            self.assertEqual(result.skipped, 2)
            self.assertTrue(symlink_path.is_symlink())
            self.assertEqual(symlink_target.read_text(encoding="utf-8"), "target")
            self.assertEqual(outside_path.read_text(encoding="utf-8"), "outside")
            symlinked.refresh_from_db()
            out_of_root.refresh_from_db()
            self.assertEqual(symlinked.raw_artifact_path, str(symlink_path))
            self.assertEqual(out_of_root.raw_artifact_path, str(outside_path))

    def test_cleanup_cas_does_not_clear_concurrently_replaced_artifact_path(self):
        observation = self._observation(
            "f6", retention_until=NOW - timedelta(seconds=1)
        )
        original_path = Path(observation.raw_artifact_path)
        replacement_path = self.root / "replacement.json"
        replacement_path.write_text("replacement", encoding="utf-8")

        pipeline = _pipeline()
        real_unlink = pipeline.os.unlink

        def replace_path_during_unlink(path, *args, **kwargs):
            real_unlink(path, *args, **kwargs)
            models.RaceResultObservation.objects.filter(pk=observation.pk).update(
                raw_artifact_path=str(replacement_path),
                raw_size_bytes=replacement_path.stat().st_size,
            )

        with self.settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(str(self.root),)):
            with patch.object(
                pipeline.os,
                "unlink",
                side_effect=replace_path_during_unlink,
            ):
                result = pipeline.cleanup_expired_race_data_raw_payloads(
                    now=NOW,
                    batch_size=100,
                )

        self.assertFalse(original_path.exists())
        self.assertTrue(replacement_path.exists())
        self.assertEqual(result.cleaned, 0)
        self.assertEqual(result.skipped, 1)
        observation.refresh_from_db()
        self.assertEqual(observation.raw_artifact_path, str(replacement_path))
        self.assertEqual(observation.raw_size_bytes, replacement_path.stat().st_size)


@override_settings(
    RACE_DATA_SYNC_ENABLED=False,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=(),
    RACE_DATA_SYNC_ENABLED_REGIONS=(),
    RACE_DATA_SYNC_ENABLED_FIELDS=(),
)
class RaceDataSyncFlagContractTests(SimpleTestCase):
    def test_provider_region_and_field_must_all_be_enabled(self):
        flags = _pipeline().RaceDataSyncFlags.from_settings()
        self.assertFalse(
            flags.allows(
                provider="hkjc",
                region="hong_kong",
                field_name="participants.jockey_name",
            )
        )

        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("hkjc",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=("participants.jockey_name",),
        ):
            flags = _pipeline().RaceDataSyncFlags.from_settings()
            self.assertTrue(
                flags.allows(
                    provider="hkjc",
                    region="hong_kong",
                    field_name="participants.jockey_name",
                )
            )
            self.assertFalse(
                flags.allows(
                    provider="the_racing_api",
                    region="hong_kong",
                    field_name="participants.jockey_name",
                )
            )
            self.assertFalse(
                flags.allows(
                    provider="hkjc",
                    region="japan_jra",
                    field_name="participants.jockey_name",
                )
            )
            self.assertFalse(
                flags.allows(
                    provider="hkjc",
                    region="hong_kong",
                    field_name="off_time",
                )
            )


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("france",),
    RACE_DATA_SYNC_ENABLED_FIELDS=tuple(
        _contract(provider="the_racing_api", region="france")["allowed_fields"]
    ),
)
class RaceDataRaceLiveRefreshAdmissionTests(TestCase):
    NOW = datetime(2026, 8, 2, 12, 0, tzinfo=dt_timezone.utc)
    TOKEN = "slice-a-refresh-token"

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="slice-a-live-refresh",
            original_name="Slice A Live Refresh",
            chinese_name="Slice A 实时刷新",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=datetime(2026, 8, 2, 13, 0, tzinfo=dt_timezone.utc),
            timezone_name="Europe/Paris",
            local_date=date(2026, 8, 2),
            local_start_time=datetime(2026, 8, 2, 15, 0).time(),
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=3,
            next_racecard_revision_no=2,
        )
        self.tracking = models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=models.RaceEventLiveState.RACECARD_READY,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            last_attempt_at=self.NOW,
            claim_generation=4,
            active_attempt_token=self.TOKEN,
            claim_expires_at=self.NOW + timedelta(minutes=5),
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="fr-slice-a-refresh-1",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
        )
        self.participant = models.RaceEventParticipant.objects.create(
            event=self.event,
            stable_key="runner-1",
            canonical_name="Alpha",
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=self.participant,
            source_identity=self.source,
            external_runner_id="runner-1",
        )
        self.initial_revision = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256="a" * 64,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=self.initial_revision,
            participant=self.participant,
            source_order=1,
            internal_order=1,
            status=models.RaceEventRevisionItemStatus.DECLARED,
            horse_number="1",
            barrier="3",
            jockey_name="Old Jockey",
        )
        self.control.current_racecard_revision = self.initial_revision
        self.control.last_known_good_racecard_revision = self.initial_revision
        self.control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "updated_at",
            )
        )
        self.runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="runner-1",
            horse_name="Alpha",
            horse_number="1",
            barrier="3",
            jockey_name="Old Jockey",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={"the_racing_api": "runner-1"},
        )

    def _payload(self, **participant_overrides):
        participant = {
            "external_runner_id": "runner-1",
            "horse_name": "Incoming Alpha",
            "number": "9",
            "draw": "8",
            "jockey_name": "New Jockey",
            "status": models.RaceRunnerStatus.WITHDRAWN,
            **participant_overrides,
        }
        return {
            "schema_version": 1,
            "external_race_id": self.source.external_race_id,
            "off_time": "2026-08-02T15:00:00+02:00",
            "region": "france",
            "course": "ParisLongchamp",
            "race_name": "Slice A Live Refresh",
            "race_status": "racecard",
            "participants": (participant,),
        }

    def _refresh(self, *, raw_sha256, payload=None):
        return race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token=self.TOKEN,
            now=self.NOW,
            raw_sha256=raw_sha256,
            normalized_racecard=payload or self._payload(),
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=False,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=(),
        RACE_DATA_SYNC_ENABLED_REGIONS=(),
        RACE_DATA_SYNC_ENABLED_FIELDS=(),
    )
    def test_global_closed_refresh_records_observation_without_canonical_write(self):
        decision = self._refresh(raw_sha256="b" * 64)

        self.assertFalse(decision.applied)
        self.assertEqual(decision.reason, "field_runtime_admission_closed")
        self.assertEqual(models.RaceResultObservation.objects.count(), 1)
        self.assertEqual(models.RaceEventRevision.objects.count(), 1)
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_racecard_revision_id,
            self.initial_revision.pk,
        )
        self.assertEqual(self.initial_revision.items.count(), 1)
        self.runner.refresh_from_db()
        self.assertEqual(self.runner.horse_name, "Alpha")
        self.assertEqual(self.runner.horse_number, "1")
        self.assertEqual(self.runner.barrier, "3")
        self.assertEqual(self.runner.jockey_name, "Old Jockey")
        self.assertEqual(
            self.runner.running_status,
            models.RaceRunnerStatus.DECLARED,
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED_FIELDS=("participants.jockey_name",),
    )
    def test_partial_refresh_canonical_revision_contains_only_admitted_changes(self):
        decision = self._refresh(raw_sha256="c" * 64)

        self.assertTrue(decision.applied)
        self.runner.refresh_from_db()
        self.assertEqual(self.runner.horse_name, "Alpha")
        self.assertEqual(self.runner.horse_number, "1")
        self.assertEqual(self.runner.barrier, "3")
        self.assertEqual(self.runner.jockey_name, "New Jockey")
        self.assertEqual(
            self.runner.running_status,
            models.RaceRunnerStatus.DECLARED,
        )
        self.control.refresh_from_db()
        revision = self.control.current_racecard_revision
        self.assertNotEqual(revision.pk, self.initial_revision.pk)
        item = revision.items.get(participant=self.participant)
        self.assertEqual(item.horse_number, "1")
        self.assertEqual(item.barrier, "3")
        self.assertEqual(item.jockey_name, "New Jockey")
        self.assertEqual(item.status, models.RaceEventRevisionItemStatus.DECLARED)

    def test_real_tra_jockey_id_is_observation_evidence_not_a_writable_field(self):
        parsed = race_live_fixtures.parse_the_racing_api_live_racecards_payload(
            {
                "racecards": [
                    {
                        "race_id": self.source.external_race_id,
                        "off_dt": "2026-08-02T15:00:00+02:00",
                        "region": "FR",
                        "course": "ParisLongchamp",
                        "race_name": "Slice A Live Refresh",
                        "race_status": "Racecard",
                        "runners": [
                            {
                                "horse_id": "runner-1",
                                "horse": "Alpha",
                                "number": "1",
                                "draw": "3",
                                "jockey": "Fixture Jockey",
                                "jockey_id": "fixture-jockey-1",
                                "form": "11111",
                                "ofr": "123",
                                "rating": "123",
                                "odds": "7/4",
                                "prize": "100000",
                                "pedigree": {"sire": "Not normalized"},
                                "comments": "Not normalized",
                            }
                        ],
                    }
                ],
                "total": 1,
                "limit": 500,
                "skip": 0,
            }
        )

        decision = self._refresh(
            raw_sha256="e" * 64,
            payload=parsed.races[0],
        )

        self.assertTrue(decision.applied, decision.reason)
        observation = models.RaceResultObservation.objects.get()
        participant = observation.normalized_payload["participants"][0]
        self.assertEqual(participant["jockey_id"], "fixture-jockey-1")
        self.assertEqual(observation.raw_sha256, "e" * 64)
        self.assertEqual(
            observation.field_provenance["provider"],
            "the_racing_api",
        )
        self.runner.refresh_from_db()
        self.assertEqual(self.runner.jockey_name, "Fixture Jockey")
        with self.assertRaises(FieldDoesNotExist):
            models.RaceEventRunner._meta.get_field("jockey_id")
        self.assertFalse(
            models.RaceEventFieldChange.objects.filter(
                observation=observation,
                field_name="jockey_id",
                applied=True,
            ).exists()
        )

    def _mark_event_as_other(self, *, event_marker=None, source_marker=None):
        self.event.country_region = models.RacingRegion.OTHER
        self.event.timezone_name = "Europe/Dublin"
        self.event.source_refs = event_marker or {}
        self.event.save(
            update_fields=(
                "country_region",
                "timezone_name",
                "source_refs",
                "updated_at",
            )
        )
        self.source.identity_fields = source_marker or {}
        self.source.save(update_fields=("identity_fields", "updated_at"))

    def _assert_provider_contract_missing_without_projection(self, *, raw_sha256):
        before_revision_id = self.control.current_racecard_revision_id
        before_revision_count = models.RaceEventRevision.objects.count()

        decision = self._refresh(
            raw_sha256=raw_sha256,
            payload={**self._payload(), "region": "IE"},
        )

        self.assertFalse(decision.applied)
        self.assertEqual(decision.reason, "provider_contract_missing")
        self.assertFalse(models.RaceResultObservation.objects.exists())
        self.assertEqual(
            models.RaceEventRevision.objects.count(),
            before_revision_count,
        )
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_racecard_revision_id,
            before_revision_id,
        )
        return decision

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_unmarked_other_region_does_not_route_to_ireland(self):
        self._mark_event_as_other()
        self._assert_provider_contract_missing_without_projection(
            raw_sha256="1" * 64,
        )

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_audited_event_source_ref_can_route_other_region_to_ireland(self):
        self._mark_event_as_other(
            event_marker={"race_data_region": "ireland"},
        )

        decision = self._refresh(
            raw_sha256="2" * 64,
            payload={**self._payload(), "region": "IE"},
        )

        self.assertTrue(decision.applied, decision.reason)
        observation = models.RaceResultObservation.objects.get()
        self.assertEqual(observation.field_provenance["region"], "ireland")
        self.control.refresh_from_db()
        self.assertNotEqual(
            self.control.current_racecard_revision_id,
            self.initial_revision.pk,
        )

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_audited_source_identity_marker_can_route_other_region_to_ireland(self):
        self._mark_event_as_other(
            source_marker={"race_data_region": "ireland"},
        )

        decision = self._refresh(
            raw_sha256="3" * 64,
            payload={**self._payload(), "region": "IE"},
        )

        self.assertTrue(decision.applied, decision.reason)
        observation = models.RaceResultObservation.objects.get()
        self.assertEqual(observation.field_provenance["region"], "ireland")

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_matching_event_and_source_ireland_markers_are_allowed(self):
        self._mark_event_as_other(
            event_marker={"race_data_region": "ireland"},
            source_marker={"race_data_region": "ireland"},
        )

        decision = self._refresh(
            raw_sha256="4" * 64,
            payload={**self._payload(), "region": "IE"},
        )

        self.assertTrue(decision.applied, decision.reason)
        observation = models.RaceResultObservation.objects.get()
        self.assertEqual(observation.field_provenance["region"], "ireland")

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_event_ireland_and_approved_source_france_marker_conflict_is_rejected(self):
        self._mark_event_as_other(
            event_marker={"race_data_region": "ireland"},
            source_marker={"race_data_region": "france"},
        )

        self._assert_provider_contract_missing_without_projection(
            raw_sha256="5" * 64,
        )

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_event_france_and_approved_source_ireland_marker_conflict_is_rejected(self):
        self._mark_event_as_other(
            event_marker={"race_data_region": "france"},
            source_marker={"race_data_region": "ireland"},
        )

        self._assert_provider_contract_missing_without_projection(
            raw_sha256="6" * 64,
        )

    @override_settings(RACE_DATA_SYNC_ENABLED_REGIONS=("ireland",))
    def test_noncanonical_or_non_ireland_single_marker_is_fail_closed(self):
        cases = (
            ({"race_data_region": "Ireland"}, None),
            ({"race_data_region": "france"}, None),
            (None, {"race_data_region": "IRELAND"}),
            (None, {"race_data_region": 1}),
        )
        for index, (event_marker, source_marker) in enumerate(cases, start=7):
            with self.subTest(
                event_marker=event_marker,
                source_marker=source_marker,
            ):
                self._mark_event_as_other(
                    event_marker=event_marker,
                    source_marker=source_marker,
                )
                self._assert_provider_contract_missing_without_projection(
                    raw_sha256=f"{index:x}" * 64,
                )

    def _refresh_with_late_cross_source_conflict(self):
        models.RaceEventFieldAuthority.objects.create(
            event=self.event,
            subject_type=models.RaceEventFieldSubjectType.PARTICIPANT,
            subject_key="runner-1",
            field_name="jockey_name",
            source_key="hkjc",
            observed_at=self.NOW - timedelta(minutes=1),
            value_sha256="f" * 64,
        )
        return self._refresh(
            raw_sha256="d" * 64,
            payload=self._payload(
                horse_name="Changed Before Conflict",
                number="1",
                draw="3",
                jockey_name="Conflicting Jockey",
                status=models.RaceRunnerStatus.DECLARED,
            ),
        )

    def test_higher_priority_refresh_replaces_unclassified_authority(self):
        decision = self._refresh_with_late_cross_source_conflict()

        self.assertTrue(decision.applied)
        self.assertEqual(decision.reason, "racecard_refreshed")
        self.runner.refresh_from_db()
        self.assertEqual(self.runner.horse_name, "Changed Before Conflict")
        self.assertEqual(self.runner.jockey_name, "Conflicting Jockey")
        self.assertTrue(
            models.RaceEventFieldChange.objects.filter(
                event=self.event,
                applied=True,
            ).exists()
        )
        self.control.refresh_from_db()
        self.assertNotEqual(
            self.control.current_racecard_revision_id, self.initial_revision.pk
        )
        self.assertEqual(models.RaceEventRevision.objects.count(), 2)

    def test_prior_unclassified_authority_completes_claim_and_checkpoints_outcome(self):
        decision = self._refresh_with_late_cross_source_conflict()

        self.assertTrue(decision.applied)
        self.assertEqual(decision.reason, "racecard_refreshed")
        observation = models.RaceResultObservation.objects.get()
        self.tracking.refresh_from_db()
        self.assertEqual(self.tracking.claim_generation, 4)
        self.assertEqual(self.tracking.active_attempt_token, "")
        self.assertIsNone(self.tracking.claim_expires_at)
        self.assertEqual(
            self.tracking.checkpoint_payload.get("status"),
            "racecard_refreshed",
        )
        self.assertIsNotNone(self.tracking.checkpoint_payload.get("revision_id"))
        self.assertEqual(
            self.tracking.last_observation_hash,
            observation.normalized_sha256,
        )


class RaceDataRuntimeAdmissionContractTests(TestCase):
    setUp = RacecardFieldReconciliationContractTests.setUp
    _event = staticmethod(RacecardFieldReconciliationContractTests._event)
    _source = staticmethod(RacecardFieldReconciliationContractTests._source)
    _observation = RacecardFieldReconciliationContractTests._observation
    _reconcile = RacecardFieldReconciliationContractTests._reconcile

    def _assert_zero_apply(self, decision):
        self.assertEqual(decision.status, "rejected")
        self.assertIn(
            decision.reason,
            {"runtime_admission_closed", "source_contract_mismatch"},
        )
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldAuthority.objects.exists())
        self.assertFalse(
            models.RaceEventFieldChange.objects.filter(applied=True).exists()
        )

    def test_default_closed_reconcile_keeps_observation_but_zero_business_write(self):
        observation = self._observation(self.tra)

        decision = self._reconcile(observation)

        self._assert_zero_apply(decision)
        self.assertTrue(
            models.RaceResultObservation.objects.filter(pk=observation.pk).exists()
        )

    def test_provider_only_is_still_closed(self):
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
            RACE_DATA_SYNC_ENABLED_REGIONS=(),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
        ):
            observation = self._observation(self.tra)
            decision = self._reconcile(observation)

        self._assert_zero_apply(decision)

    def test_region_only_is_still_closed(self):
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=(),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
        ):
            observation = self._observation(self.tra)
            decision = self._reconcile(observation)

        self._assert_zero_apply(decision)

    def test_prerecorded_observation_cannot_bypass_proof_required_roster_entry(self):
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("hkjc",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
        ):
            roster = _pipeline().build_race_data_provider_roster()
            entry = next(item for item in roster.entries if item.provider == "hkjc")
            self.assertEqual(entry.adapter_status, "proof_required")
            self.assertFalse(entry.transport_enabled)
            self.assertFalse(entry.apply_enabled)
            self.assertEqual(self.hkjc.review_status, models.RaceLiveReviewStatus.APPROVED)
            self.assertTrue(self.hkjc.automation_allowed)

            observation = self._observation(self.hkjc)
            self.assertIsNotNone(observation.pk)
            decision = self._reconcile(observation)

        self._assert_zero_apply(decision)
        self.assertTrue(
            models.RaceResultObservation.objects.filter(pk=observation.pk).exists()
        )

    def _assert_roster_entry_switch_is_required(
        self, *, transport_enabled: bool, apply_enabled: bool
    ):
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
        ):
            observation = self._observation(self.tra)
            roster = _pipeline().build_race_data_provider_roster()
            original = next(
                item for item in roster.entries if item.provider == "the_racing_api"
            )
            gated = replace(
                original,
                transport_enabled=transport_enabled,
                apply_enabled=apply_enabled,
            )
            gated_roster = replace(
                roster,
                entries=tuple(
                    gated if item.provider == gated.provider else item
                    for item in roster.entries
                ),
            )
            self.assertTrue(gated_roster.verify_digest())
            with patch.object(
                _pipeline(),
                "build_race_data_provider_roster",
                return_value=gated_roster,
            ):
                decision = self._reconcile(observation)

        self._assert_zero_apply(decision)

    def test_transport_disabled_roster_entry_rejects_prerecorded_observation(self):
        self._assert_roster_entry_switch_is_required(
            transport_enabled=False,
            apply_enabled=True,
        )

    def test_apply_disabled_roster_entry_rejects_prerecorded_observation(self):
        self._assert_roster_entry_switch_is_required(
            transport_enabled=True,
            apply_enabled=False,
        )

    def test_partial_field_admission_applies_only_jockey(self):
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="horse-1",
            horse_name="Locked Identity",
            horse_number="8",
            barrier="9",
            jockey_name="Old Jockey",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={"the_racing_api": "horse-1"},
        )
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=("participants.jockey_name",),
        ):
            observation = self._observation(
                self.tra,
                jockey="Only New Jockey",
                participant_overrides={
                    "number": "1",
                    "draw": "3",
                    "status": models.RaceRunnerStatus.WITHDRAWN,
                },
                allowed_fields=[
                    "participants.horse_name",
                    "participants.number",
                    "participants.draw",
                    "participants.jockey_name",
                    "participants.status",
                    "off_time",
                ],
            )
            decision = self._reconcile(observation)

        self.assertIn(decision.status, {"applied", "needs_review"})
        runner.refresh_from_db()
        self.assertEqual(runner.jockey_name, "Only New Jockey")
        self.assertEqual(runner.horse_name, "Locked Identity")
        self.assertEqual(runner.horse_number, "8")
        self.assertEqual(runner.barrier, "9")
        self.assertEqual(runner.running_status, models.RaceRunnerStatus.DECLARED)
        self.assertEqual(
            set(
                models.RaceEventFieldChange.objects.filter(applied=True)
                .values_list("field_name", flat=True)
            ),
            {"jockey_name"},
        )

    def test_same_observation_can_apply_new_fields_after_allowlist_expands(self):
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="horse-1",
            horse_name="Locked Identity",
            horse_number="8",
            barrier="9",
            jockey_name="Old Jockey",
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={"the_racing_api": "horse-1"},
        )
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=("participants.jockey_name",),
        ):
            observation = self._observation(
                self.tra,
                jockey="Expanded Jockey",
                participant_overrides={
                    "horse_name": "Expanded Horse",
                    "number": "1",
                    "draw": "3",
                    "status": models.RaceRunnerStatus.WITHDRAWN,
                },
                allowed_fields=_contract()["allowed_fields"],
            )
            partial = self._reconcile(observation)

        self.assertEqual(partial.status, "applied")
        runner.refresh_from_db()
        self.assertEqual(runner.jockey_name, "Expanded Jockey")
        self.assertEqual(runner.horse_name, "Locked Identity")
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
        ):
            expanded = self._reconcile(observation)

        self.assertEqual(expanded.status, "applied")
        runner.refresh_from_db()
        self.assertEqual(runner.horse_name, "Expanded Horse")
        self.assertEqual(runner.horse_number, "1")
        self.assertEqual(runner.barrier, "3")
        self.assertEqual(runner.jockey_name, "Expanded Jockey")
        self.assertEqual(
            runner.running_status,
            models.RaceRunnerStatus.WITHDRAWN,
        )
        self.assertEqual(
            models.RaceEventFieldChange.objects.filter(
                observation=observation,
                field_name="jockey_name",
            ).count(),
            1,
        )

    def _assert_contract_mutation_rejected(self, mutation):
        with self.settings(
            RACE_DATA_SYNC_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
            RACE_DATA_SYNC_ENABLED_REGIONS=("hong_kong",),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_contract()["allowed_fields"]),
        ):
            observation = self._observation(
                self.tra,
                provenance_overrides=mutation,
            )
            decision = self._reconcile(observation)
        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason, "source_contract_mismatch")
        self.assertFalse(models.RaceEventRunner.objects.exists())
        self.assertFalse(models.RaceEventFieldAuthority.objects.exists())

    def test_stale_registry_digest_is_zero_write(self):
        self._assert_contract_mutation_rejected({"registry_digest": "0" * 64})

    def test_stale_contract_version_and_digest_are_zero_write(self):
        self._assert_contract_mutation_rejected(
            {"contract_version": "racecard-v0", "contract_digest": "1" * 64}
        )

    def test_source_class_mismatch_is_zero_write(self):
        self._assert_contract_mutation_rejected({"source_class": "official_operator"})


class RaceDataFieldLedgerGovernanceTests(TestCase):
    def setUp(self):
        self.event = RacecardFieldReconciliationContractTests._event(
            slug="field-ledger-governance"
        )

    def _change(self, **overrides):
        values = {
            "event": self.event,
            "subject_type": models.RaceEventFieldSubjectType.EVENT,
            "subject_key": str(self.event.pk),
            "field_name": "racecourse",
            "old_value": "Old",
            "new_value": "New",
            "decision": "",
            "applied": False,
        }
        values.update(overrides)
        return models.RaceEventFieldChange.objects.create(**values)

    def test_decision_enum_and_database_check_allow_only_history_or_known_values(self):
        decision_field = models.RaceEventFieldChange._meta.get_field("decision")
        self.assertEqual(
            {value for value, _label in decision_field.choices},
            {"applied", "replayed", "needs_review", "rejected"},
        )
        historical = self._change()
        self.assertEqual(historical.decision, "")
        for decision in ("applied", "replayed", "needs_review", "rejected"):
            with self.subTest(decision=decision):
                self._change(field_name=f"field_{decision}", decision=decision)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._change(field_name="invalid", decision="unexpected")

    def test_admin_exposes_decision_provenance_and_explicit_legacy_authority_label(self):
        change_admin = admin.site._registry[models.RaceEventFieldChange]
        authority_admin = admin.site._registry[models.RaceEventFieldAuthority]
        required = {
            "decision",
            "source_class",
            "observation",
            "contract_version",
            "contract_digest",
            "registry_digest",
            "raw_sha256",
            "normalized_sha256",
            "celery_task_id",
        }

        self.assertTrue(required.issubset(set(change_admin.list_display)))
        self.assertTrue(required.issubset(set(change_admin.readonly_fields)))
        self.assertIn("legacy_authority_level", authority_admin.list_display)
        self.assertIn("legacy", authority_admin.legacy_authority_level.short_description.lower())

    def test_postgres_ledger_guard_migration_has_explicit_reverse_sql(self):
        guard_migration = importlib.import_module(
            "stable.migrations.0069_race_data_sync_pipeline_a_ledger_guards"
        )
        sql_operations = [
            operation
            for operation in guard_migration.Migration.operations
            if isinstance(operation, migrations.RunSQL)
        ]
        self.assertTrue(sql_operations)
        self.assertTrue(
            all(
                operation.reverse_sql
                not in {None, migrations.RunSQL.noop}
                for operation in sql_operations
            )
        )
