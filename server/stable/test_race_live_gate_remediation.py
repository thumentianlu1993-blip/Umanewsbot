from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import get_commands, load_command_class
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable import test_race_live_multiregion_pipeline as multiregion_tests
from stable.services import race_events, race_live_racecard_sync
from stable.services.race_live_fixtures import (
    parse_the_racing_api_live_racecards_payload,
)
from stable.services.race_live_source_proof import RaceLiveProofHttpResponse


class CoupledRacecardParserRemediationTests(SimpleTestCase):
    @staticmethod
    def _race(*, race_id: str, runners: list[dict], race_name: str = "Test Stakes"):
        return {
            "race_id": race_id,
            "off_dt": "2026-07-20T14:40:00+01:00",
            "region": "gb",
            "course": "Ascot",
            "race_name": race_name,
            "race_status": "open",
            "runners": runners,
        }

    @staticmethod
    def _runner(*, horse_id: str, horse: str, number: str, draw: str):
        return {
            "horse_id": horse_id,
            "horse": horse,
            "number": number,
            "draw": draw,
            "jockey": f"{horse} Jockey",
            "jockey_id": f"{horse_id}-jockey",
        }

    def test_racecard_accepts_distinct_horses_with_shared_number(self):
        payload = {
            "racecards": [
                self._race(
                    race_id="coupled-race",
                    runners=[
                        self._runner(
                            horse_id="horse-a",
                            horse="Coupled Alpha",
                            number="1",
                            draw="2",
                        ),
                        self._runner(
                            horse_id="horse-b",
                            horse="Coupled Beta",
                            number="1",
                            draw="7",
                        ),
                    ],
                )
            ]
        }

        snapshot = parse_the_racing_api_live_racecards_payload(payload)

        self.assertEqual(
            [
                (
                    row["external_runner_id"],
                    row["number"],
                    row["draw"],
                )
                for row in snapshot.races[0]["participants"]
            ],
            [
                ("horse-a", "1", "2"),
                ("horse-b", "1", "7"),
            ],
        )

    def test_racecard_rejects_duplicate_horse_id_even_when_numbers_differ(self):
        payload = {
            "racecards": [
                self._race(
                    race_id="duplicate-id-race",
                    runners=[
                        self._runner(
                            horse_id="horse-a",
                            horse="Duplicate Alpha",
                            number="1",
                            draw="2",
                        ),
                        self._runner(
                            horse_id="horse-a",
                            horse="Duplicate Beta",
                            number="2",
                            draw="7",
                        ),
                    ],
                )
            ]
        }

        with self.assertRaisesRegex(ValueError, "duplicate horse_id"):
            parse_the_racing_api_live_racecards_payload(payload)


class CoupledRacecardPrepareRemediationTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)
    APPROVED_COMMIT = "c" * 40

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="target-test-stakes",
            original_name="Test Stakes",
            chinese_name="目标测试锦标",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name="Europe/London",
            local_date=self.NOW.astimezone().date(),
            status=models.RaceEventStatus.SCHEDULED,
        )

    @staticmethod
    def _response(payload: dict) -> RaceLiveProofHttpResponse:
        return RaceLiveProofHttpResponse(
            status_code=200,
            content_type="application/json",
            body=json.dumps(payload).encode("utf-8"),
            elapsed_ms=10,
        )

    def test_unrelated_coupled_race_does_not_poison_target_prepare(self):
        target = {
            "race_id": "target-race",
            "off_dt": "2026-07-20T14:40:00+01:00",
            "region": "gb",
            "course": "Ascot",
            "race_name": "Test Stakes",
            "runners": [
                {
                    "horse_id": "target-horse",
                    "horse": "Target Horse",
                    "number": "9",
                    "draw": "4",
                }
            ],
        }
        unrelated_coupled = {
            "race_id": "unrelated-coupled",
            "off_dt": "2026-07-20T13:00:00+01:00",
            "region": "gb",
            "course": "York",
            "race_name": "Unrelated Stakes",
            "runners": [
                {
                    "horse_id": "unrelated-a",
                    "horse": "Unrelated Alpha",
                    "number": "1",
                    "draw": "1",
                },
                {
                    "horse_id": "unrelated-b",
                    "horse": "Unrelated Beta",
                    "number": "1",
                    "draw": "2",
                },
            ],
        }
        responses = {
            "racecards_sync_today": self._response(
                {"racecards": [unrelated_coupled, target]}
            ),
            "racecards_sync_tomorrow": self._response({"racecards": []}),
        }

        def transport(*, endpoint_name, **_kwargs):
            return responses[endpoint_name]

        registry = {
            "schema_version": 1,
            "valid_until": (self.NOW + timedelta(days=30)).isoformat(),
        }
        write_artifact = Mock(return_value=Path("/tmp/remediation-run"))
        with (
            patch.object(
                race_live_racecard_sync,
                "_validate_root",
                return_value=Path("/tmp"),
            ),
            patch.object(
                race_live_racecard_sync,
                "read_the_racing_api_automation_registry",
                return_value=(registry, "a" * 64),
            ),
            patch.object(
                race_live_racecard_sync,
                "_read_secret",
                return_value=("fixture-user", "fixture-password"),
            ),
            patch.object(
                race_live_racecard_sync,
                "_bootstrap_host_budget",
            ),
            patch.object(
                race_live_racecard_sync,
                "_reserve_with_bounded_wait",
                return_value=(1, ""),
            ),
            patch.object(
                race_live_racecard_sync,
                "record_race_live_host_outcome",
                return_value=SimpleNamespace(recorded=True, reason="recorded"),
            ),
            patch.object(
                race_live_racecard_sync,
                "_write_artifact",
                write_artifact,
            ),
        ):
            result = race_live_racecard_sync.prepare_race_live_racecards(
                event_ids=[self.event.pk],
                region=models.RacingRegion.UNITED_KINGDOM,
                run_id="coupled-page-target-prepare",
                artifact_root="/tmp",
                secret_env_file="/tmp/unused-secret.env",
                registry_file="/tmp/unused-registry.json",
                expected_registry_sha256="a" * 64,
                approved_commit=self.APPROVED_COMMIT,
                coverage_proof_digest="b" * 64,
                terms_evidence_sha256="d" * 64,
                policy_valid_until=self.NOW + timedelta(days=20),
                official_verification_route="bha_manual_verification",
                official_verification_route_version="bha-manual-v1",
                official_verification_evidence_sha256="e" * 64,
                official_verification_valid_until=self.NOW
                + timedelta(days=20),
                now=self.NOW,
                transport=transport,
                sleep=lambda _seconds: None,
                clock=lambda: self.NOW,
                confirm_real_network=True,
            )

        self.assertTrue(result.completed, result.blocker_codes)
        manifest = write_artifact.call_args.kwargs["manifest_base"]
        self.assertEqual(
            [row["event_id"] for row in manifest["events"]],
            [self.event.pk],
        )
        self.assertEqual(
            [
                (
                    row["external_runner_id"],
                    row["horse_number"],
                )
                for row in manifest["events"][0]["participants"]
            ],
            [("target-horse", "9")],
        )


class LegacyRunnerIdentityRemediationTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="legacy-coupled-runner",
            original_name="Legacy Coupled Runner",
            chinese_name="旧投影并列号码测试",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
        )

    def _require_external_runner_id_field(self):
        fields = {
            field.name: field for field in models.RaceEventRunner._meta.fields
        }
        self.assertIn(
            "external_runner_id",
            fields,
            "RaceEventRunner 尚未持久化 provider external runner identity",
        )
        return fields["external_runner_id"]

    def test_runner_schema_uses_conditional_external_id_uniqueness(self):
        field = self._require_external_runner_id_field()
        self.assertTrue(field.blank)
        constraints = {
            constraint.name: constraint
            for constraint in models.RaceEventRunner._meta.constraints
        }
        self.assertNotIn("uq_race_runner_event_no", constraints)
        identity_constraint = constraints.get(
            "uq_race_runner_event_external_id"
        )
        self.assertIsNotNone(
            identity_constraint,
            "缺少 event + nonempty external_runner_id 条件唯一约束",
        )
        self.assertEqual(
            tuple(identity_constraint.fields),
            ("event", "external_runner_id"),
        )
        self.assertIsNotNone(identity_constraint.condition)

    def test_shared_number_persists_and_nonempty_external_id_remains_unique(self):
        self._require_external_runner_id_field()
        try:
            with transaction.atomic():
                models.RaceEventRunner.objects.create(
                    event=self.event,
                    horse_number="1",
                    horse_name="Coupled Alpha",
                    external_runner_id="provider-alpha",
                )
                models.RaceEventRunner.objects.create(
                    event=self.event,
                    horse_number="1",
                    horse_name="Coupled Beta",
                    external_runner_id="provider-beta",
                )
        except (IntegrityError, TypeError) as exc:
            self.fail(f"不同 external ID 的并列号码仍无法持久化: {exc}")
        self.assertEqual(
            list(
                self.event.runners.order_by("id").values_list(
                    "external_runner_id",
                    "horse_number",
                    "horse_name",
                )
            ),
            [
                ("provider-alpha", "1", "Coupled Alpha"),
                ("provider-beta", "1", "Coupled Beta"),
            ],
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                models.RaceEventRunner.objects.create(
                    event=self.event,
                    horse_number="2",
                    horse_name="Duplicate Identity",
                    external_runner_id="provider-alpha",
                )

    def test_blank_external_ids_remain_legacy_compatible(self):
        self._require_external_runner_id_field()
        try:
            with transaction.atomic():
                for name in ("Legacy Alpha", "Legacy Beta"):
                    models.RaceEventRunner.objects.create(
                        event=self.event,
                        horse_number="3",
                        horse_name=name,
                        external_runner_id="",
                    )
        except (IntegrityError, TypeError) as exc:
            self.fail(f"空 external ID 历史行不兼容: {exc}")
        self.assertEqual(self.event.runners.count(), 2)

    def test_dynamic_update_prefers_external_id_and_ambiguity_is_zero_write(self):
        self._require_external_runner_id_field()
        alpha = models.RaceEventRunner.objects.create(
            event=self.event,
            horse_number="1",
            horse_name="Coupled Alpha",
            external_runner_id="provider-alpha",
            odds_value="10",
        )
        beta = models.RaceEventRunner.objects.create(
            event=self.event,
            horse_number="1",
            horse_name="Coupled Beta",
            external_runner_id="provider-beta",
            odds_value="20",
        )

        decision = race_events.update_runner_dynamic_fields(
            self.event,
            [
                {
                    "external_runner_id": "provider-beta",
                    "horse_number": "1",
                    "odds_value": "2.5",
                }
            ],
            source_name="remediation-test",
        )
        alpha.refresh_from_db()
        beta.refresh_from_db()
        self.assertEqual(alpha.odds_value, "10")
        self.assertEqual(beta.odds_value, "2.5")
        self.assertEqual(decision["updated"], 1)

        decision = race_events.update_runner_dynamic_fields(
            self.event,
            [{"horse_number": "1", "odds_value": "1.8"}],
            source_name="remediation-test",
        )
        alpha.refresh_from_db()
        beta.refresh_from_db()
        self.assertEqual((alpha.odds_value, beta.odds_value), ("10", "2.5"))
        self.assertEqual(decision["updated"], 0)
        self.assertEqual(decision["skipped_ambiguous"], 1)

        decision = race_events.update_runner_dynamic_fields(
            self.event,
            [
                {
                    "horse_number": "1",
                    "horse_name": "Coupled Alpha",
                    "odds_value": "3.0",
                }
            ],
            source_name="remediation-test",
        )
        alpha.refresh_from_db()
        beta.refresh_from_db()
        self.assertEqual((alpha.odds_value, beta.odds_value), ("3.0", "2.5"))
        self.assertEqual(decision["updated"], 1)

    def test_dynamic_update_falls_back_to_unique_name_after_number_miss(self):
        runner = models.RaceEventRunner.objects.create(
            event=self.event,
            horse_number="7",
            horse_name="Unique Name Fallback",
            external_runner_id="provider-name-fallback",
            odds_value="12",
        )

        decision = race_events.update_runner_dynamic_fields(
            self.event,
            [
                {
                    "horse_number": "99",
                    "horse_name": "Unique Name Fallback",
                    "odds_value": "4.5",
                }
            ],
            source_name="remediation-test",
        )

        runner.refresh_from_db()
        self.assertEqual(runner.odds_value, "4.5")
        self.assertEqual(decision["updated"], 1)
        self.assertEqual(decision["skipped"], 0)
        self.assertEqual(decision["skipped_ambiguous"], 0)


class P0CoupledRunnerIdentityRemediationTests(TestCase):
    @staticmethod
    def _event(slug: str, name: str):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=name,
            chinese_name=f"{name} 中文",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            local_date=datetime(2026, 7, 20).date(),
            priority=models.RaceEventPriority.P0,
            status=models.RaceEventStatus.FINISHED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            source_refs={
                "official": "https://evidence.example.test/race"
            },
        )

    @staticmethod
    def _runner_result_pair(
        *,
        event,
        finish_position: int,
        horse_name: str,
        horse_number: str,
        external_runner_id: str,
        source_key: str,
    ):
        source_refs = {
            "source_key": source_key,
            "external_runner_id": external_runner_id,
            "source_url": "https://evidence.example.test/race",
        }
        runner = models.RaceEventRunner.objects.create(
            event=event,
            external_runner_id=external_runner_id,
            sort_order=finish_position,
            horse_number=horse_number,
            horse_name=horse_name,
            source_refs=source_refs,
        )
        result = models.RaceEventResult.objects.create(
            event=event,
            finish_position=finish_position,
            official_finish_position=finish_position,
            horse_number=horse_number,
            horse_name=horse_name,
            source_refs=source_refs,
        )
        return runner, result

    def test_coupled_number_sources_prefer_external_runner_identity(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = models.RaceEvent.objects.create(
            year=2026,
            slug="p0-coupled-external-runner-identity",
            original_name="P0 Coupled External Runner Identity",
            chinese_name="P0 并列号码来源身份测试",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            local_date=datetime(2026, 7, 20).date(),
            priority=models.RaceEventPriority.P0,
            status=models.RaceEventStatus.FINISHED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            source_refs={"official": "https://example.test/race"},
        )
        for sort_order, (external_id, horse_name) in enumerate(
            (
                ("tra-coupled-alpha", "Coupled Identity Alpha"),
                ("tra-coupled-beta", "Coupled Identity Beta"),
            ),
            start=1,
        ):
            models.RaceEventRunner.objects.create(
                event=event,
                external_runner_id=external_id,
                sort_order=sort_order,
                horse_number="1",
                horse_name=horse_name,
                source_refs={
                    "source_key": "the_racing_api",
                    "external_runner_id": external_id,
                },
            )

        summary = sync_p0_horse_sources(commit=True)

        sources = list(
            models.HorseP0Source.objects.filter(
                race_event=event,
                status=models.HorseP0SourceStatus.ACTIVE,
            ).order_by("participant_key")
        )
        self.assertEqual(summary["major_race_sources"], 2)
        self.assertEqual(len(sources), 2)
        self.assertEqual(len({source.profile_id for source in sources}), 2)
        self.assertEqual(len({source.participant_key for source in sources}), 2)
        self.assertTrue(
            all(
                source.participant_key.startswith("identity:")
                for source in sources
            )
        )

    def test_coupled_runner_and_result_pair_by_external_identity(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._event(
            "p0-coupled-runner-result-pairing",
            "P0 Coupled Runner Result Pairing",
        )
        for position, external_id, horse_name in (
            (1, "tra-coupled-alpha", "Coupled Pair Alpha"),
            (2, "tra-coupled-beta", "Coupled Pair Beta"),
        ):
            self._runner_result_pair(
                event=event,
                finish_position=position,
                horse_name=horse_name,
                horse_number="1",
                external_runner_id=external_id,
                source_key="the_racing_api",
            )

        summary = sync_p0_horse_sources(commit=True)

        sources = list(
            models.HorseP0Source.objects.filter(
                race_event=event,
                status=models.HorseP0SourceStatus.ACTIVE,
            )
            .select_related("race_runner", "race_result")
            .order_by("participant_key")
        )
        self.assertEqual(summary["major_race_sources"], 2)
        self.assertEqual(len(sources), 2)
        self.assertEqual(len({source.profile_id for source in sources}), 2)
        self.assertTrue(
            all(
                source.race_runner_id is not None
                and source.race_result_id is not None
                for source in sources
            )
        )
        self.assertEqual(
            {
                (
                    source.race_runner.source_refs["external_runner_id"],
                    source.race_result.source_refs["external_runner_id"],
                )
                for source in sources
            },
            {
                ("tra-coupled-alpha", "tra-coupled-alpha"),
                ("tra-coupled-beta", "tra-coupled-beta"),
            },
        )

    def test_external_identity_namespace_uses_source_key(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        tra_event = self._event(
            "p0-source-namespace-tra",
            "P0 Source Namespace TRA",
        )
        hkjc_event = self._event(
            "p0-source-namespace-hkjc",
            "P0 Source Namespace HKJC",
        )
        self._runner_result_pair(
            event=tra_event,
            finish_position=1,
            horse_name="Namespace TRA Horse",
            horse_number="1",
            external_runner_id="shared-external-id",
            source_key="the_racing_api",
        )
        self._runner_result_pair(
            event=hkjc_event,
            finish_position=1,
            horse_name="Namespace HKJC Horse",
            horse_number="1",
            external_runner_id="shared-external-id",
            source_key="hkjc",
        )

        sync_p0_horse_sources(commit=True)

        sources = list(
            models.HorseP0Source.objects.filter(
                race_event__in=(tra_event, hkjc_event),
                status=models.HorseP0SourceStatus.ACTIVE,
            ).order_by("race_event_id")
        )
        self.assertEqual(len(sources), 2)
        self.assertEqual(len({source.profile_id for source in sources}), 2)
        identity_by_event = {
            source.race_event_id: set(
                source.evidence_payload["horse_identity_keys"]
            )
            for source in sources
        }
        self.assertEqual(
            identity_by_event,
            {
                tra_event.pk: {
                    "the_racing_api:shared-external-id"
                },
                hkjc_event.pk: {"hkjc:shared-external-id"},
            },
        )


class RacecardReplayLegacyIdentityRemediationTests(TestCase):
    NOW = multiregion_tests.RaceLiveRacecardRefreshBehaviorTests.NOW
    setUp = multiregion_tests.RaceLiveRacecardRefreshBehaviorTests.setUp

    def _normalized_racecard(self):
        return {
            "external_race_id": "fr-refresh-1",
            "region": "FR",
            "course": "ParisLongchamp",
            "race_name": "France Racecard Refresh",
            "race_status": "Racecard",
            "participants": (
                {
                    "external_runner_id": "runner-1",
                    "horse_name": "Alpha",
                    "number": "1",
                    "draw": "",
                    "jockey_name": "Old Jockey",
                    "trainer_name": "",
                    "carried_weight": "",
                    "status": "declared",
                },
            ),
        }

    def _force_unchanged_revision(self, normalized_racecard):
        merged = race_live_racecard_sync.merge_race_live_racecard_participants(
            previous=(
                {
                    "external_runner_id": "runner-1",
                    "horse_name": "Alpha",
                    "number": "1",
                    "draw": "",
                    "jockey_name": "Old Jockey",
                    "trainer_name": "",
                    "carried_weight": "",
                    "status": "declared",
                },
            ),
            incoming=normalized_racecard["participants"],
        )
        canonical_payload = {
            **normalized_racecard,
            "participants": list(merged["participants"]),
            "missing_runner_source_gaps": list(
                merged["missing_runner_source_gaps"]
            ),
        }
        current = models.RaceEventRevision.objects.get(
            pk=self.control.current_racecard_revision_id
        )
        current_item = current.items.get()
        replay_revision = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=self.control.next_racecard_revision_no,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=canonical_payload
            ),
            source_authority=(
                models.RaceResultSourceAuthority.SUPPLEMENTAL
            ),
            decision_reason="existing unchanged replay fixture",
            supersedes=current,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=replay_revision,
            participant=current_item.participant,
            source_order=current_item.source_order,
            internal_order=current_item.internal_order,
            official_finish_position=(
                current_item.official_finish_position
            ),
            status=current_item.status,
            raw_status=current_item.raw_status,
            finish_time=current_item.finish_time,
            margin=current_item.margin,
            horse_number=current_item.horse_number,
            barrier=current_item.barrier,
            jockey_name=current_item.jockey_name,
            trainer_name=current_item.trainer_name,
            carried_weight=current_item.carried_weight,
            field_provenance=current_item.field_provenance,
        )
        self.control.current_racecard_revision = replay_revision
        self.control.last_known_good_racecard_revision = replay_revision
        self.control.next_racecard_revision_no += 1
        self.control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "next_racecard_revision_no",
                "updated_at",
            )
        )

    def _refresh(self, normalized_racecard):
        return race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="b" * 64,
            normalized_racecard=normalized_racecard,
        )

    def _racecard_write_state(self):
        return {
            "tracking": (
                models.RaceEventLiveTracking.objects.values().get(
                    event=self.event
                )
            ),
            "runners": list(
                models.RaceEventRunner.objects.filter(event=self.event)
                .order_by("id")
                .values()
            ),
            "observations": models.RaceResultObservation.objects.count(),
            "revisions": models.RaceEventRevision.objects.count(),
            "revision_items": models.RaceEventRevisionItem.objects.count(),
            "participants": models.RaceEventParticipant.objects.count(),
            "source_identities": (
                models.RaceEventParticipantSourceIdentity.objects.count()
            ),
        }

    def _assert_conflicting_legacy_identity_is_zero_write(
        self,
        normalized_racecard,
    ):
        models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="conflicting-column-id",
            sort_order=1,
            horse_number="1",
            horse_name="Alpha",
            source_refs={
                "source_key": "the_racing_api",
                "external_runner_id": "runner-1",
            },
        )
        before = self._racecard_write_state()

        decision = self._refresh(normalized_racecard)

        self.assertFalse(decision.applied)
        self.assertEqual(
            decision.reason,
            "legacy_runner_identity_conflict",
        )
        self.assertEqual(self._racecard_write_state(), before)

    def test_unchanged_replay_lazily_migrates_unique_legacy_source_identity(self):
        normalized = self._normalized_racecard()
        self._force_unchanged_revision(normalized)
        legacy = models.RaceEventRunner.objects.create(
            event=self.event,
            external_runner_id="",
            sort_order=1,
            horse_number="1",
            horse_name="Alpha",
            source_refs={
                "source_key": "the_racing_api",
                "external_runner_id": "runner-1",
            },
        )

        decision = self._refresh(normalized)

        self.assertTrue(decision.applied, decision.reason)
        self.assertTrue(decision.replayed)
        legacy.refresh_from_db()
        self.assertEqual(legacy.external_runner_id, "runner-1")
        self.assertEqual(
            models.RaceEventRunner.objects.filter(event=self.event).count(),
            1,
        )

    def test_unchanged_replay_ambiguous_legacy_identity_is_zero_write(self):
        normalized = self._normalized_racecard()
        self._force_unchanged_revision(normalized)
        for index in range(2):
            models.RaceEventRunner.objects.create(
                event=self.event,
                external_runner_id="",
                sort_order=index + 1,
                horse_number="1",
                horse_name=f"Alpha Legacy {index + 1}",
                source_refs={
                    "source_key": "the_racing_api",
                    "external_runner_id": "runner-1",
                },
            )
        tracking_before = models.RaceEventLiveTracking.objects.values().get(
            event=self.event
        )
        runners_before = list(
            models.RaceEventRunner.objects.filter(event=self.event)
            .order_by("id")
            .values()
        )
        counts_before = {
            "observations": models.RaceResultObservation.objects.count(),
            "revisions": models.RaceEventRevision.objects.count(),
            "participants": models.RaceEventParticipant.objects.count(),
        }

        decision = self._refresh(normalized)

        self.assertFalse(decision.applied)
        self.assertEqual(
            decision.reason,
            "legacy_runner_identity_ambiguous",
        )
        self.assertEqual(
            models.RaceEventLiveTracking.objects.values().get(
                event=self.event
            ),
            tracking_before,
        )
        self.assertEqual(
            list(
                models.RaceEventRunner.objects.filter(event=self.event)
                .order_by("id")
                .values()
            ),
            runners_before,
        )
        self.assertEqual(
            {
                "observations": models.RaceResultObservation.objects.count(),
                "revisions": models.RaceEventRevision.objects.count(),
                "participants": models.RaceEventParticipant.objects.count(),
            },
            counts_before,
        )

    def test_unchanged_replay_rejects_conflicting_legacy_identity_zero_write(self):
        normalized = self._normalized_racecard()
        self._force_unchanged_revision(normalized)

        self._assert_conflicting_legacy_identity_is_zero_write(
            normalized
        )

    def test_refresh_rejects_conflicting_legacy_identity_zero_write(self):
        self._assert_conflicting_legacy_identity_is_zero_write(
            self._normalized_racecard()
        )


class RollbackGateCommandSurfaceRemediationTests(SimpleTestCase):
    EXPECTED_GENERATOR_ARGUMENTS = {
        "event_id",
        "reviewed_release_image_id",
        "filtered_env_sha256",
        "approved_commit",
        "run_id",
        "output_root",
    }
    EXPECTED_MAINTENANCE_ARGUMENTS = {
        "manifest",
        "expected_manifest_sha256",
        "expected_approved_commit",
        "apply",
        "confirm",
    }

    @staticmethod
    def _argument_dests(command_name: str) -> set[str]:
        app_name = get_commands()[command_name]
        command = load_command_class(app_name, command_name)
        parser = command.create_parser("manage.py", command_name)
        return {
            action.dest
            for action in parser._actions
            if action.dest not in {"help", "version", "verbosity", "settings",
                                   "pythonpath", "traceback", "no_color",
                                   "force_color", "skip_checks"}
        }

    def test_rollback_bundle_generator_command_has_frozen_arguments(self):
        self.assertIn(
            "prepare_race_live_rollback_bundle",
            get_commands(),
            "rollback bundle generator command 尚未注册",
        )
        self.assertEqual(
            self._argument_dests("prepare_race_live_rollback_bundle"),
            self.EXPECTED_GENERATOR_ARGUMENTS,
        )

    def test_rollback_maintenance_command_has_dry_run_apply_contract(self):
        self.assertIn(
            "transition_race_live_rollback_maintenance",
            get_commands(),
            "rollback maintenance command 尚未注册",
        )
        self.assertEqual(
            self._argument_dests(
                "transition_race_live_rollback_maintenance"
            ),
            self.EXPECTED_MAINTENANCE_ARGUMENTS,
        )

    def test_rollback_service_surface_covers_schema_permissions_and_full_off_gate(self):
        required_symbols = {
            "build_race_live_rollback_bundle",
            "prepare_race_live_rollback_bundle",
            "load_race_live_rollback_manifest",
            "transition_race_live_rollback_maintenance",
        }
        missing = sorted(
            name
            for name in required_symbols
            if not callable(getattr(race_events, name, None))
        )
        self.assertEqual(
            missing,
            [],
            "rollback exact-schema/权限/全关门禁 service surface 缺失",
        )

    def test_restore_service_requires_expected_current_revision_cas(self):
        parameters = inspect.signature(
            race_events.restore_race_live_provisional_policies
        ).parameters
        self.assertIn(
            "expected_current_revision_id",
            parameters,
            "restore service 未接收 manifest current revision CAS 指针",
        )


@override_settings(
    RACE_LIVE_SCHEDULER_ENABLED=False,
    RACE_LIVE_MONITOR_ENABLED=False,
    RACE_LIVE_ENABLED_REGIONS=(),
)
class RollbackGateBehaviorRemediationTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)
    IMAGE_ID = "sha256:" + ("1" * 64)
    ENV_DIGEST = "2" * 64
    APPROVED_COMMIT = "3" * 40
    REGISTRY_DIGEST = "4" * 64
    COVERAGE_DIGEST = "5" * 64
    EXPECTED_MANIFEST_KEYS = {
        "schema_version",
        "event_id",
        "reviewed_release_image_id",
        "filtered_env_sha256",
        "approved_commit",
        "generated_at",
        "expected_current_revision_id",
        "expected_provisional_revision_id",
        "expected_allowlist_version",
        "expected_publication_id",
        "expected_tracking_lock_version",
        "planned_policy_snapshot",
        "baseline_policies",
        "expected_tracking_state",
        "maintenance_confirmation",
    }

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="rollback-gate-remediation",
            original_name="Rollback Gate Remediation",
            chinese_name="回滚门禁修复测试",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            status=models.RaceEventStatus.FINISHED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="rollback-remediation-tra",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=self.NOW + timedelta(days=30),
            evidence_sha256="6" * 64,
            registry_digest=self.REGISTRY_DIGEST,
        )
        self.observation = models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW,
            parser_version="tra-v1",
            raw_sha256="7" * 64,
            normalized_sha256="8" * 64,
            result_phase=models.RaceResultPhase.PROVISIONAL,
        )
        participant = models.RaceEventParticipant.objects.create(
            event=self.event,
            stable_key="rollback-winner",
            canonical_name="Rollback Winner",
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        self.provisional = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256=self.observation.normalized_sha256,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            primary_observation=self.observation,
            published_at=self.NOW,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=self.provisional,
            participant=participant,
            source_order=1,
            internal_order=1,
            official_finish_position=1,
            status=models.RaceEventRevisionItemStatus.FINISHED,
            horse_number="1",
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            current_result_revision=self.provisional,
            last_known_good_result_revision=self.provisional,
            last_provisional_result_revision=self.provisional,
            next_result_revision_no=2,
        )
        self.tracking = models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=models.RaceEventLiveState.PROVISIONAL_RESULT,
            tracking_enabled=False,
            next_poll_at=None,
            active_attempt_token="",
            claim_expires_at=None,
            provisional_published_at=self.NOW,
            lock_version=7,
        )
        self.allowlist = models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key=self.source.source_key,
            max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            official_verification_route=(
                "france_galop_manual_verification"
            ),
            official_verification_route_version="france-galop-manual-v1",
            official_verification_contract_digest="a" * 64,
            official_terms_evidence_digest="b" * 64,
            official_verification_valid_until=(
                self.NOW + timedelta(days=30)
            ),
            enabled=True,
            version=4,
        )
        self.publication = models.RaceEventRevisionPublication.objects.create(
            revision=self.provisional,
            published_at=self.provisional.published_at,
            reason="remediation-test",
            policy_versions=[],
            allowlist_version=self.allowlist.version,
            registry_digest=self.REGISTRY_DIGEST,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            authorization_kind="provisional_policy",
            official_authorization_version=0,
        )
        self.policies = {}
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
            (
                models.RaceLivePublicationScopeType.EVENT,
                str(self.event.pk),
            ),
        ):
            key = f"{scope_type}:{scope_key}"
            self.policies[key] = models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                version=10,
                registry_digest=self.REGISTRY_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                valid_until=self.NOW + timedelta(days=30),
            )

    def _builder(self):
        builder = getattr(
            race_events,
            "build_race_live_rollback_bundle",
            None,
        )
        self.assertTrue(
            callable(builder),
            "完整 provisional baseline rollback bundle builder 尚未实现",
        )
        return builder

    def _transition(self):
        transition = getattr(
            race_events,
            "transition_race_live_rollback_maintenance",
            None,
        )
        self.assertTrue(
            callable(transition),
            "四层 maintenance 原子 CAS service 尚未实现",
        )
        return transition

    def _bundle(self):
        return self._builder()(
            event_id=self.event.pk,
            reviewed_release_image_id=self.IMAGE_ID,
            filtered_env_sha256=self.ENV_DIGEST,
            approved_commit=self.APPROVED_COMMIT,
            generated_at=self.NOW,
        )

    @staticmethod
    def _manifest_digest(manifest: dict) -> str:
        return hashlib.sha256(
            (
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()

    def _transition_kwargs(self, manifest: dict, *, apply: bool):
        return {
            "manifest": manifest,
            "expected_manifest_sha256": self._manifest_digest(manifest),
            "expected_approved_commit": self.APPROVED_COMMIT,
            "apply": apply,
            "now": self.NOW,
        }

    def _policy_state(self):
        return list(
            models.RaceLivePublicationPolicy.objects.order_by(
                "scope_type",
                "scope_key",
            ).values_list(
                "scope_type",
                "scope_key",
                "mode",
                "version",
                "registry_digest",
                "coverage_proof_digest",
                "valid_until",
            )
        )

    def test_complete_provisional_baseline_builds_exact_deterministic_manifest(self):
        public_read = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=self.NOW,
        )
        self.assertTrue(public_read.visible, public_read.reason)

        first = self._bundle()
        second = self._bundle()
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"manifest", "report"})
        manifest = first["manifest"]
        self.assertEqual(set(manifest), self.EXPECTED_MANIFEST_KEYS)
        self.assertEqual(manifest["event_id"], self.event.pk)
        self.assertEqual(
            manifest["reviewed_release_image_id"],
            self.IMAGE_ID,
        )
        self.assertEqual(manifest["filtered_env_sha256"], self.ENV_DIGEST)
        self.assertEqual(manifest["approved_commit"], self.APPROVED_COMMIT)
        self.assertEqual(
            manifest["expected_current_revision_id"],
            self.provisional.pk,
        )
        self.assertEqual(
            manifest["expected_provisional_revision_id"],
            self.provisional.pk,
        )
        self.assertEqual(
            manifest["expected_publication_id"],
            self.publication.pk,
        )
        self.assertEqual(
            manifest["expected_allowlist_version"],
            self.allowlist.version,
        )
        self.assertEqual(
            manifest["expected_tracking_state"],
            {
                "tracking_enabled": False,
                "next_poll_at": None,
                "active_attempt_token": "",
                "claim_expires_at": None,
                "lock_version": 7,
            },
        )
        self.assertEqual(
            manifest["maintenance_confirmation"],
            f"ENTER_RACE_LIVE_ROLLBACK_MAINTENANCE_{self.event.pk}",
        )
        self.assertEqual(
            set(manifest["planned_policy_snapshot"]),
            set(self.policies),
        )
        for key, policy in self.policies.items():
            planned = manifest["planned_policy_snapshot"][key]
            self.assertEqual(
                (planned["maintenance"]["mode"],
                 planned["maintenance"]["version"]),
                (models.RaceLivePublicationMode.OFF, policy.version + 1),
            )
            self.assertEqual(
                (planned["restore"]["mode"],
                 planned["restore"]["version"]),
                (
                    models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                    policy.version + 2,
                ),
            )
            for field in (
                "registry_digest",
                "coverage_proof_digest",
                "valid_until",
            ):
                self.assertEqual(
                    planned["maintenance"][field],
                    planned["restore"][field],
                )

    def test_builder_rejects_expired_official_route_gate_without_writes(self):
        self.allowlist.official_verification_valid_until = self.NOW
        self.allowlist.save(
            update_fields=(
                "official_verification_valid_until",
                "updated_at",
            )
        )
        public_read = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=self.NOW,
        )
        self.assertFalse(public_read.visible)
        self.assertEqual(
            public_read.reason,
            "policy_official_route_expired",
        )
        before = {
            "policies": self._policy_state(),
            "allowlist": models.RaceLiveEventPublicationAllowlist.objects.values().get(
                pk=self.allowlist.pk
            ),
            "control": models.RaceEventProjectionControl.objects.values().get(
                pk=self.control.pk
            ),
            "tracking": models.RaceEventLiveTracking.objects.values().get(
                pk=self.tracking.pk
            ),
            "operation_logs": models.OperationLog.objects.count(),
        }

        with self.assertRaises((ValueError, PermissionError)):
            self._bundle()

        self.assertEqual(self._policy_state(), before["policies"])
        self.assertEqual(
            models.RaceLiveEventPublicationAllowlist.objects.values().get(
                pk=self.allowlist.pk
            ),
            before["allowlist"],
        )
        self.assertEqual(
            models.RaceEventProjectionControl.objects.values().get(
                pk=self.control.pk
            ),
            before["control"],
        )
        self.assertEqual(
            models.RaceEventLiveTracking.objects.values().get(
                pk=self.tracking.pk
            ),
            before["tracking"],
        )
        self.assertEqual(models.OperationLog.objects.count(), before["operation_logs"])

    def test_builder_rejects_observation_revision_hash_mismatch_without_writes(self):
        prior_provisional = self.provisional
        prior_item = prior_provisional.items.get()
        self.provisional = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=2,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256="f" * 64,
            source_authority=(
                models.RaceResultSourceAuthority.SUPPLEMENTAL
            ),
            decision_reason="legal mismatch fixture",
            primary_observation=self.observation,
            supersedes=prior_provisional,
            published_at=self.NOW,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=self.provisional,
            participant=prior_item.participant,
            source_order=prior_item.source_order,
            internal_order=prior_item.internal_order,
            official_finish_position=(
                prior_item.official_finish_position
            ),
            status=prior_item.status,
            raw_status=prior_item.raw_status,
            finish_time=prior_item.finish_time,
            margin=prior_item.margin,
            horse_number=prior_item.horse_number,
            barrier=prior_item.barrier,
            jockey_name=prior_item.jockey_name,
            trainer_name=prior_item.trainer_name,
            carried_weight=prior_item.carried_weight,
            field_provenance=prior_item.field_provenance,
        )
        self.publication = (
            models.RaceEventRevisionPublication.objects.create(
                revision=self.provisional,
                published_at=self.provisional.published_at,
                reason="legal-mismatch-remediation-test",
                policy_versions=[],
                allowlist_version=self.allowlist.version,
                registry_digest=self.REGISTRY_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                authorization_kind="provisional_policy",
                official_authorization_version=0,
            )
        )
        self.control.current_result_revision = self.provisional
        self.control.last_known_good_result_revision = self.provisional
        self.control.last_provisional_result_revision = self.provisional
        self.control.next_result_revision_no = 3
        self.control.save(
            update_fields=(
                "current_result_revision",
                "last_known_good_result_revision",
                "last_provisional_result_revision",
                "next_result_revision_no",
                "updated_at",
            )
        )
        public_read = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=self.NOW,
        )
        self.assertFalse(public_read.visible)
        self.assertEqual(
            public_read.reason,
            "observation_revision_mismatch",
        )
        before = {
            "policies": self._policy_state(),
            "revision": models.RaceEventRevision.objects.values().get(
                pk=self.provisional.pk
            ),
            "control": models.RaceEventProjectionControl.objects.values().get(
                pk=self.control.pk
            ),
            "tracking": models.RaceEventLiveTracking.objects.values().get(
                pk=self.tracking.pk
            ),
            "operation_logs": models.OperationLog.objects.count(),
        }

        with self.assertRaises((ValueError, PermissionError)):
            self._bundle()

        self.assertEqual(self._policy_state(), before["policies"])
        self.assertEqual(
            models.RaceEventRevision.objects.values().get(
                pk=self.provisional.pk
            ),
            before["revision"],
        )
        self.assertEqual(
            models.RaceEventProjectionControl.objects.values().get(
                pk=self.control.pk
            ),
            before["control"],
        )
        self.assertEqual(
            models.RaceEventLiveTracking.objects.values().get(
                pk=self.tracking.pk
            ),
            before["tracking"],
        )
        self.assertEqual(models.OperationLog.objects.count(), before["operation_logs"])

    def test_restore_command_forwards_expected_current_revision_id(self):
        manifest = self._bundle()["manifest"]
        manifest_bytes = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        app_name = get_commands()[
            "restore_race_live_provisional_policies"
        ]
        command = load_command_class(
            app_name,
            "restore_race_live_provisional_policies",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(manifest_bytes)
            with patch(
                "stable.management.commands."
                "restore_race_live_provisional_policies."
                "restore_race_live_provisional_policies",
                return_value=SimpleNamespace(
                    allowed=True,
                    reason="restore_ready",
                ),
            ) as restore:
                command.handle(
                    manifest=str(path),
                    expected_manifest_sha256=manifest_sha256,
                    phase="coarse",
                )

        forwarded = restore.call_args.kwargs
        self.assertIn("expected_current_revision_id", forwarded)
        self.assertEqual(
            forwarded["expected_current_revision_id"],
            manifest["expected_current_revision_id"],
        )

    def test_validator_rejects_scheduler_or_monitor_without_writes(self):
        manifest = self._bundle()["manifest"]
        before = {
            "policies": self._policy_state(),
            "control": models.RaceEventProjectionControl.objects.values().get(
                pk=self.control.pk
            ),
            "tracking": models.RaceEventLiveTracking.objects.values().get(
                pk=self.tracking.pk
            ),
            "operation_logs": models.OperationLog.objects.count(),
        }

        for setting_name in (
            "RACE_LIVE_SCHEDULER_ENABLED",
            "RACE_LIVE_MONITOR_ENABLED",
        ):
            with self.subTest(setting=setting_name):
                with override_settings(**{setting_name: True}):
                    decision = (
                        race_events
                        .validate_race_live_provisional_rollback_target(
                            event_id=self.event.pk,
                            now=self.NOW,
                            expected_provisional_revision_id=(
                                manifest[
                                    "expected_provisional_revision_id"
                                ]
                            ),
                            expected_allowlist_version=manifest[
                                "expected_allowlist_version"
                            ],
                            expected_publication_id=manifest[
                                "expected_publication_id"
                            ],
                            expected_tracking_lock_version=manifest[
                                "expected_tracking_lock_version"
                            ],
                        )
                    )
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "invalid_input")
                self.assertEqual(
                    self._policy_state(),
                    before["policies"],
                )
                self.assertEqual(
                    models.RaceEventProjectionControl.objects.values().get(
                        pk=self.control.pk
                    ),
                    before["control"],
                )
                self.assertEqual(
                    models.RaceEventLiveTracking.objects.values().get(
                        pk=self.tracking.pk
                    ),
                    before["tracking"],
                )
                self.assertEqual(
                    models.OperationLog.objects.count(),
                    before["operation_logs"],
                )

    @override_settings(RACE_LIVE_ENABLED_REGIONS=("france",))
    def test_builder_rejects_enabled_regions_without_writes(self):
        before = self._policy_state()
        with self.assertRaises((ValueError, PermissionError)):
            self._bundle()
        self.assertEqual(self._policy_state(), before)
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).exists()
        )

    def test_builder_rejects_background_tasks_claims_and_tracking_fence(self):
        for setting_name in (
            "RACE_LIVE_SCHEDULER_ENABLED",
            "RACE_LIVE_MONITOR_ENABLED",
        ):
            with self.subTest(setting=setting_name):
                with override_settings(**{setting_name: True}):
                    with self.assertRaises((ValueError, PermissionError)):
                        self._bundle()

        self.tracking.active_attempt_token = "active-claim"
        self.tracking.claim_expires_at = self.NOW + timedelta(minutes=5)
        self.tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_expires_at",
                "updated_at",
            )
        )
        with self.assertRaises((ValueError, PermissionError)):
            self._bundle()
        self.tracking.active_attempt_token = ""
        self.tracking.claim_expires_at = None
        self.tracking.next_poll_at = self.NOW
        self.tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_expires_at",
                "next_poll_at",
                "updated_at",
            )
        )
        with self.assertRaises((ValueError, PermissionError)):
            self._bundle()

    def test_generator_requires_root_and_does_not_publish_partial_directory(self):
        prepare = getattr(
            race_events,
            "prepare_race_live_rollback_bundle",
            None,
        )
        self.assertTrue(
            callable(prepare),
            "root-owned rollback bundle publisher 尚未实现",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            with (
                patch.object(os, "geteuid", return_value=501),
                self.assertRaises((ValueError, PermissionError, OSError)),
            ):
                prepare(
                    event_id=self.event.pk,
                    reviewed_release_image_id=self.IMAGE_ID,
                    filtered_env_sha256=self.ENV_DIGEST,
                    approved_commit=self.APPROVED_COMMIT,
                    run_id="non-root-rejected",
                    output_root=root,
                    generated_at=self.NOW,
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace(self):
        prepare = getattr(
            race_events,
            "prepare_race_live_rollback_bundle",
            None,
        )
        self.assertTrue(
            callable(prepare),
            "root-owned rollback bundle publisher 尚未实现",
        )
        if os.geteuid() != 0:
            self.skipTest("root-owned artifact contract requires root EUID")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            kwargs = {
                "event_id": self.event.pk,
                "reviewed_release_image_id": self.IMAGE_ID,
                "filtered_env_sha256": self.ENV_DIGEST,
                "approved_commit": self.APPROVED_COMMIT,
                "run_id": "root-artifact-contract",
                "output_root": root,
                "generated_at": self.NOW,
            }
            result = prepare(**kwargs)
            output_dir = Path(result["output_dir"])
            output_stat = output_dir.lstat()
            self.assertTrue(stat.S_ISDIR(output_stat.st_mode))
            self.assertFalse(stat.S_ISLNK(output_stat.st_mode))
            self.assertEqual(stat.S_IMODE(output_stat.st_mode), 0o700)
            self.assertEqual((output_stat.st_uid, output_stat.st_gid), (0, 0))
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {"manifest.json", "report.json", "sha256s.json"},
            )
            for path in output_dir.iterdir():
                file_stat = path.lstat()
                self.assertTrue(stat.S_ISREG(file_stat.st_mode), path.name)
                self.assertFalse(stat.S_ISLNK(file_stat.st_mode), path.name)
                self.assertEqual(
                    stat.S_IMODE(file_stat.st_mode),
                    0o600,
                    path.name,
                )
                self.assertEqual(
                    (file_stat.st_uid, file_stat.st_gid),
                    (0, 0),
                    path.name,
                )
                self.assertLessEqual(file_stat.st_size, 1024 * 1024)
            artifact_text = "\n".join(
                (output_dir / name).read_text(encoding="utf-8")
                for name in ("manifest.json", "report.json")
            )
            for forbidden in (
                "THE_RACING_API",
                "password",
                "SMTP",
                "notify",
                "fixture-password",
            ):
                self.assertNotIn(forbidden, artifact_text)
            load = getattr(
                race_events,
                "load_race_live_rollback_manifest",
                None,
            )
            self.assertTrue(
                callable(load),
                "strict rollback manifest loader 尚未实现",
            )
            manifest_path = output_dir / "manifest.json"
            valid_text = manifest_path.read_text(encoding="utf-8")
            invalid_inputs = {
                "duplicate-key.json": valid_text.replace(
                    "{",
                    '{"schema_version":999,',
                    1,
                ),
                "unknown-key.json": valid_text.replace(
                    "{",
                    '{"unexpected_key":true,',
                    1,
                ),
            }
            for filename, payload in invalid_inputs.items():
                with self.subTest(filename=filename):
                    invalid_path = root / filename
                    invalid_path.write_text(payload, encoding="utf-8")
                    invalid_path.chmod(0o600)
                    with self.assertRaises(
                        (ValueError, PermissionError)
                    ):
                        load(
                            manifest_path=invalid_path,
                            expected_manifest_sha256=hashlib.sha256(
                                invalid_path.read_bytes()
                            ).hexdigest(),
                            expected_approved_commit=self.APPROVED_COMMIT,
                        )
            with self.assertRaises(
                (FileExistsError, ValueError, PermissionError)
            ):
                prepare(**kwargs)

    def test_maintenance_dry_run_is_zero_write_and_reports_all_scopes(self):
        manifest = self._bundle()["manifest"]
        before = self._policy_state()
        result = self._transition()(
            **self._transition_kwargs(manifest, apply=False)
        )
        self.assertEqual(self._policy_state(), before)
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(
            set(result["policy_transitions"]),
            set(self.policies),
        )
        self.assertEqual(
            result["manifest_sha256"],
            self._manifest_digest(manifest),
        )
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).exists()
        )

    def test_maintenance_apply_is_atomic_hidden_and_replay_is_zero_write(self):
        manifest = self._bundle()["manifest"]
        first = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertEqual(first["reason"], "maintenance_applied")
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode",
                    "version",
                )
            ),
            {(models.RaceLivePublicationMode.OFF, 11)},
        )
        self.assertFalse(
            race_events.resolve_race_live_public_read(
                event_id=self.event.pk,
                now=self.NOW,
            ).visible
        )
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).count(),
            1,
        )
        before = self._policy_state()
        replay = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertEqual(replay["reason"], "already_maintenance")
        self.assertEqual(self._policy_state(), before)
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).count(),
            1,
        )

    def test_maintenance_scope_or_tracking_drift_is_zero_write(self):
        manifest = self._bundle()["manifest"]
        event_policy = self.policies[
            f"{models.RaceLivePublicationScopeType.EVENT}:{self.event.pk}"
        ]
        event_policy.version += 1
        event_policy.save(update_fields=("version", "updated_at"))
        before = self._policy_state()
        result = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(self._policy_state(), before)
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).exists()
        )

        event_policy.version -= 1
        event_policy.save(update_fields=("version", "updated_at"))
        self.tracking.tracking_enabled = True
        self.tracking.save(
            update_fields=("tracking_enabled", "updated_at")
        )
        before = self._policy_state()
        result = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(self._policy_state(), before)
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).exists()
        )

    def test_maintenance_enabled_regions_or_active_claim_is_zero_write(self):
        manifest = self._bundle()["manifest"]
        before = self._policy_state()
        with override_settings(RACE_LIVE_ENABLED_REGIONS=("france",)):
            result = self._transition()(
                **self._transition_kwargs(manifest, apply=True)
            )
        self.assertFalse(result["ok"])
        self.assertEqual(self._policy_state(), before)

        self.tracking.active_attempt_token = "late-claim"
        self.tracking.claim_expires_at = self.NOW + timedelta(minutes=5)
        self.tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_expires_at",
                "updated_at",
            )
        )
        result = self._transition()(
            **self._transition_kwargs(manifest, apply=True)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(self._policy_state(), before)
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_rollback_maintenance"
            ).exists()
        )
