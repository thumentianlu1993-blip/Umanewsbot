from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from stable import models
from stable.services import race_data_sync_control, race_events
from stable.services.race_data_sync_pipeline import (
    _ROSTER_ALLOWED_FIELDS,
    build_race_data_provider_roster,
    resolve_race_data_provider_route,
)
from stable.services.race_data_sync_results import (
    apply_data_sync_result_observation,
)
from stable.services.race_data_sync_enrollment import parse_standing_policy
from stable.services.race_event_lifecycle_enrollment import _schedule_hash


NOW = datetime(2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc)
REGISTRY_ROOT = "1" * 64
REGISTRY_MEMBERSHIP = "2" * 64
REGISTRY_ACTIVATION = "3" * 64
REGISTRY_ENTRY = "4" * 64
LIFECYCLE_ENROLLMENT = "5" * 64


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@override_settings(
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api", "jra"),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",),
    RACE_LIVE_TRA_REGISTRY_SHA256="a" * 64,
    RACE_EVENT_LIFECYCLE_ENABLED=True,
    RACE_EVENT_LIFECYCLE_MODE="enforce",
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=REGISTRY_ROOT,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(
        REGISTRY_MEMBERSHIP
    ),
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=1,
    RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=REGISTRY_ACTIVATION,
)
class RaceDataSyncResultApplicationTests(TestCase):
    def setUp(self):
        self._policy_directory = TemporaryDirectory()
        self.addCleanup(self._policy_directory.cleanup)
        policy = {
            "schema_version": 2,
            "policy_id": "test-data-sync-standing-policy-v2",
            "approved_by": "test-reviewer",
            "approved_at": NOW.isoformat(),
            "valid_from": (NOW - timedelta(days=1)).isoformat(),
            "valid_until": (NOW + timedelta(days=30)).isoformat(),
            "routes": [
                {
                    "country_region": models.RacingRegion.JAPAN,
                    "provider": "the_racing_api",
                    "region_code": "japan_jra",
                    "identity_namespace": "the_racing_api-race-v1",
                    "route_digest": "8" * 64,
                    "data_kinds": [models.RaceDataSyncDataKind.RESULT],
                    "enrollment_eligible": False,
                    "tiebreak_order": 1,
                }
            ],
            "visibility_statuses": [models.RaceEventVisibility.PUBLISHED],
            "new_enrollment_statuses": [models.RaceEventStatus.FINISHED],
            "continuation_statuses": [models.RaceEventStatus.FINISHED],
        }
        raw = json.dumps(policy, indent=2).encode()
        policy_path = Path(self._policy_directory.name) / "standing_policy.json"
        policy_path.write_bytes(raw)
        self.standing_policy_raw_sha256 = hashlib.sha256(raw).hexdigest()
        self.standing_policy_digest = parse_standing_policy(policy).digest
        policy_settings = override_settings(
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE=str(policy_path),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=(
                self.standing_policy_raw_sha256
            ),
        )
        policy_settings.enable()
        self.addCleanup(policy_settings.disable)
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-result",
            original_name="Data Sync Result",
            chinese_name="自动赛果",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW - timedelta(minutes=10),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
        )
        self.lifecycle = models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.ENFORCE,
            schedule_generation=1,
            enrollment_manifest_sha256=LIFECYCLE_ENROLLMENT,
            manifest_data={
                "enforce_registry": {
                    "root_sha256": REGISTRY_ROOT,
                    "membership_sha256": REGISTRY_MEMBERSHIP,
                    "entry_sha256": REGISTRY_ENTRY,
                    "activation_state": "active",
                    "activation_id": REGISTRY_ACTIVATION,
                }
            },
        )
        registry = models.RaceEventLifecycleEnforceRegistry.objects.create(
            root_sha256=REGISTRY_ROOT,
            generation=1,
            membership_sha256=REGISTRY_MEMBERSHIP,
            member_count=1,
            state="active",
            is_active=True,
            activation_id=REGISTRY_ACTIVATION,
            approved_commit="6" * 40,
            selector_scope={},
            scope_sha256="7" * 64,
            census_cutoff=NOW - timedelta(days=1),
            apply_expires_at=NOW + timedelta(days=1),
            runtime_valid_until=NOW + timedelta(days=35),
            activated_at=NOW,
        )
        models.RaceEventLifecycleEnforceMembership.objects.create(
            registry=registry,
            event=self.event,
            state="active",
            entry_sha256=REGISTRY_ENTRY,
            source_enrollment_sha256=LIFECYCLE_ENROLLMENT,
            schedule_generation=1,
            schedule_hash=_schedule_hash(self.event),
            country_region=self.event.country_region,
            timezone_name=self.event.timezone_name,
            frozen_snapshot={},
        )
        self.roster = build_race_data_provider_roster(configuration_only=True)
        self.source = self._source(
            "the_racing_api", "licensed_api", "api-result"
        )
        for runner_id, name, number in (
            ("horse-1", "Alpha", "1"),
            ("horse-2", "Beta", "2"),
        ):
            models.RaceEventRunner.objects.create(
                event=self.event,
                external_runner_id=runner_id,
                horse_name=name,
                horse_number=number,
                source_refs={self.source.source_key: runner_id},
            )

    def _source(self, source_key, source_class, external_id):
        source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key=source_key,
            region_code="japan_jra",
            identity_namespace=f"{source_key}-race-v1",
            external_race_id=external_id,
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=NOW + timedelta(days=30),
            registry_digest=self.roster.registry_digest,
            identity_fields={"source_class": source_class},
        )
        for runner in models.RaceEventRunner.objects.filter(event=self.event):
            refs = runner.source_refs if isinstance(runner.source_refs, dict) else {}
            refs[source_key] = runner.external_runner_id
            runner.source_refs = refs
            runner.save(update_fields=("source_refs", "updated_at"))
        return source

    def _observation(
        self,
        source,
        source_class,
        rows,
        *,
        observed_at=NOW,
        race_status="complete",
        result_phase=models.RaceResultPhase.OFFICIAL,
        provenance_overrides=None,
    ):
        payload = {
            "external_race_id": source.external_race_id,
            "off_time": self.event.race_datetime.isoformat(),
            "region": source.region_code,
            "course": "Tokyo",
            "race_name": "Data Sync Result",
            "race_status": race_status,
            "participants": rows,
        }
        field_provenance = {
            "provider": source.source_key,
            "region": source.region_code,
            "source_class": source_class,
            "registry_digest": self.roster.registry_digest,
            "contract_version": next(
                entry.contract_version
                for entry in self.roster.entries
                if entry.provider == source.source_key
            ),
            "contract_digest": next(
                entry.contract_digest
                for entry in self.roster.entries
                if entry.provider == source.source_key
            ),
            "automation_allowed": True,
        }
        field_provenance.update(provenance_overrides or {})
        return models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=observed_at,
            source_updated_at=observed_at,
            parser_version="test-v1",
            raw_sha256=_sha(payload),
            normalized_sha256=_sha(payload),
            result_phase=result_phase,
            normalized_payload=payload,
            field_provenance=field_provenance,
        )

    def _claim_guard(
        self,
        *,
        expires_at=NOW + timedelta(minutes=4),
        data_kind=models.RaceDataSyncDataKind.RESULT,
    ):
        entry_sha256 = "a" * 64
        route_digest = "b" * 64
        tracking = self.event.live_tracking
        tracking.claim_generation = 1
        tracking.active_attempt_token = "result-claim-1"
        tracking.claim_expires_at = expires_at
        tracking.save(
            update_fields=(
                "claim_generation",
                "active_attempt_token",
                "claim_expires_at",
            )
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=self.source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="c" * 64,
            route_digest=route_digest,
            event_snapshot_sha256="d" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="e" * 64,
            entry_sha256=entry_sha256,
            effective_at=NOW,
        )
        models.RaceEventLiveProviderCheckpoint.objects.create(
            tracking=tracking,
            source_key=self.source.source_key,
            data_kind=data_kind,
            next_poll_at=NOW,
            lock_version=0,
        )
        checkpoint_plan = (
            {
                "source_key": self.source.source_key,
                "data_kind": data_kind,
                "lock_version": 0,
            },
        )
        plan_sha256 = race_data_sync_control._claim_plan_sha256(
            event_id=self.event.pk,
            enrollment_generation=1,
            owner_generation=1,
            claim_generation=1,
            attempt_token="result-claim-1",
            enrollment_entry_sha256=entry_sha256,
            route_digest=route_digest,
            checkpoint_plan=checkpoint_plan,
        )
        return race_data_sync_control.RaceDataSyncClaim(
            event_id=self.event.pk,
            enrollment_generation=1,
            owner_generation=1,
            claim_generation=1,
            attempt_token="result-claim-1",
            enrollment_entry_sha256=entry_sha256,
            route_digest=route_digest,
            checkpoint_plan=checkpoint_plan,
            plan_sha256=plan_sha256,
        )

    def _public_enrollment(self):
        route = resolve_race_data_provider_route(
            provider=self.source.source_key,
            region=self.source.region_code,
            identity_namespace=self.source.identity_namespace,
            data_kinds=(models.RaceDataSyncDataKind.RESULT,),
        )
        self.assertIsNotNone(route)
        self.control.owner_manifest_sha256 = "e" * 64
        self.control.save(
            update_fields=("owner_manifest_sha256", "updated_at")
        )
        self.source.proof_network_allowed = True
        self.source.evidence_url = "https://api.theracingapi.com/v1/results/api-result"
        self.source.evidence_sha256 = "a" * 64
        self.source.save(
            update_fields=(
                "proof_network_allowed",
                "evidence_url",
                "evidence_sha256",
                "updated_at",
            )
        )
        return models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=self.source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest=self.standing_policy_digest,
            route_digest=route.route_digest,
            event_snapshot_sha256="d" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="e" * 64,
            entry_sha256="b" * 64,
            effective_at=NOW - timedelta(minutes=1),
        )

    @staticmethod
    def _rows(first_name="Alpha", first_position=1):
        return [
            {
                "external_runner_id": "horse-1",
                "horse_name": first_name,
                "reported_finish_position": first_position,
                "status": models.RaceEventRevisionItemStatus.FINISHED,
                "number": "1",
            },
            {
                "external_runner_id": "horse-2",
                "horse_name": "Beta",
                "reported_finish_position": 2,
                "status": models.RaceEventRevisionItemStatus.FINISHED,
                "number": "2",
            },
        ]

    @override_settings(RACE_DATA_SYNC_ENABLED=True,
                       RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
                       RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True)
    def test_partial_result_public_then_official_replaces_without_correction_flag(self):
        self._public_enrollment()
        partial = self._observation(self.source, "licensed_api", self._rows()[:1],
                                    result_phase=models.RaceResultPhase.PROVISIONAL,
                                    race_status="provisional")
        decision = apply_data_sync_result_observation(
            observation_id=partial.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(decision.projected, decision)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.result_confirmed_at)
        self.assertEqual(list(self.event.results.values_list("horse_name", "is_confirmed")), [("Alpha", False)])
        public = race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW)
        self.assertTrue(public.visible, public)
        self.assertEqual(public.phase, "provisional")
        self.assertEqual(race_events.resolve_race_live_public_reads(event_ids=[self.event.pk], now=NOW)[self.event.pk], public)
        official = self._observation(self.source, "licensed_api", self._rows(), observed_at=NOW + timedelta(minutes=1))
        decision = apply_data_sync_result_observation(
            observation_id=official.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1), project_current=True, correction_apply_enabled=False)
        self.assertTrue(decision.projected, decision)
        self.assertEqual(self.event.results.filter(is_confirmed=True).count(), 2)
        self.assertEqual(self.event.results.count(), 2)
        delayed = self._observation(self.source, "licensed_api", self._rows()[:1],
                                    result_phase=models.RaceResultPhase.PROVISIONAL,
                                    observed_at=NOW + timedelta(minutes=2))
        decision = apply_data_sync_result_observation(
            observation_id=delayed.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=2), project_current=True, correction_apply_enabled=False)
        self.assertEqual(decision.reason_code, "result_phase_regression")
        self.assertEqual(self.event.results.filter(is_confirmed=True).count(), 2)

    def test_partial_known_second_place_without_winner_does_not_finish(self):
        rows = self._rows()
        rows[0].update(reported_finish_position=None, status="declared")
        observation = self._observation(self.source, "licensed_api", rows,
                                        result_phase=models.RaceResultPhase.PROVISIONAL)
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(decision.projected, decision)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)
        self.assertEqual(list(self.event.results.values_list("horse_name", "reported_finish_position", "is_confirmed")), [("Beta", 2, False)])
        revision = models.RaceEventRevision.objects.get(pk=decision.revision_id)
        self.assertEqual(revision.items.count(), 1)
        self.assertIsNone(revision.official_confirmed_at)

    def test_partial_dead_heat_can_precede_the_other_tied_runner(self):
        rows = self._rows()[1:]
        rows[0]['status'] = 'dead_heat'
        observation = self._observation(self.source, "licensed_api", rows, result_phase="provisional")
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(decision.projected, decision)
        self.assertEqual(self.event.results.get().reported_finish_position, 2)
        self.assertEqual(self.event.results.get().running_status, 'dead_heat')

    @override_settings(RACE_DATA_SYNC_ENABLED=True, RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
                       RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True)
    def test_unpublished_legacy_partial_with_unknown_rows_can_be_promoted(self):
        self._public_enrollment()
        rows = self._rows()
        rows[1].update(reported_finish_position=None, status='declared')
        observation = self._observation(self.source, 'licensed_api', rows, result_phase='provisional')
        shadow = apply_data_sync_result_observation(observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=False, correction_apply_enabled=False)
        revision = models.RaceEventRevision.objects.get(pk=shadow.revision_id)
        # 旧版暂定候选包含未知名次行；模拟真实升级前的不可变revision形状。
        participant = models.RaceEventParticipant.objects.create(event=self.event,
            stable_key='legacy-unknown', canonical_name='Beta', country_region='japan', review_status='approved')
        models.RaceEventParticipantSourceIdentity.objects.create(source_identity=self.source,
            external_runner_id='horse-2', participant=participant)
        models.RaceEventRevisionItem.objects.create(revision=revision, participant=participant,
            internal_order=2, source_order=2, status='declared', horse_number='2')
        published = apply_data_sync_result_observation(observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(published.projected, published)
        self.assertEqual(published.revision_id, shadow.revision_id)
        self.assertEqual(self.event.results.count(), 1)
        self.assertEqual(revision.items.count(), 2)  # 不重写旧审计证据。
        path, _ = models.RaceEventPublicPath.objects.get_or_create(event=self.event, path_kind='canonical',
            defaults={'year':2026, 'slug':self.event.slug})
        from stable.services.public_probe_orm_loader import _materialize
        snapshot = _materialize(self.event.pk, f'/races/{path.year}/{path.slug}/', NOW)
        self.assertEqual(snapshot.status, 'read_boundary_loaded', snapshot)
        self.assertEqual(len(snapshot.rows), 1)
        self.assertFalse(snapshot.rows[0].is_confirmed)
        rows[0]['finish_time'] = '1:30.0'
        update = self._observation(self.source, 'licensed_api', rows, result_phase='provisional',
                                   observed_at=NOW + timedelta(minutes=1))
        advanced = apply_data_sync_result_observation(observation_id=update.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1), project_current=True, correction_apply_enabled=False)
        self.assertTrue(advanced.projected, advanced)
        self.assertEqual(self.event.results.get().finish_time, '1:30.0')

    def test_same_facts_phase_upgrade_is_not_swallowed_by_replay(self):
        for phase in ("provisional", "official"):
            observation = self._observation(self.source, "licensed_api", self._rows(), result_phase=phase)
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk, expected_event_id=self.event.pk,
                now=NOW, project_current=True, correction_apply_enabled=False)
            self.assertTrue(decision.projected, decision)
        self.assertEqual(self.event.results.filter(is_confirmed=True).count(), 2)
        self.assertEqual(models.RaceEventRevision.objects.count(), 2)

    def test_partial_identity_mismatch_does_not_publish(self):
        rows = self._rows()[:1]
        rows[0]["external_runner_id"] = "unrelated-horse"
        observation = self._observation(self.source, "licensed_api", rows, result_phase="provisional")
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertFalse(decision.projected)
        self.assertFalse(self.event.results.exists())

    def test_partial_refresh_compares_canonical_participants_across_sources(self):
        fallback = self._source("jra", "official_operator", "fallback-result")
        for runner in self.event.runners.all():
            runner.source_refs['jra'] = 'jra-' + runner.external_runner_id
            runner.save()
        rows = self._rows()[:1]
        rows[0]['external_runner_id'] = 'jra-horse-1'
        first = self._observation(fallback, 'official_operator', rows, result_phase='provisional')
        initial = apply_data_sync_result_observation(observation_id=first.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(initial.projected, initial)
        participant = models.RaceEventRevision.objects.get(pk=initial.revision_id).items.get().participant_id
        next_observation = self._observation(self.source, 'licensed_api', self._rows(),
                                            result_phase='provisional', observed_at=NOW + timedelta(minutes=1))
        decision = apply_data_sync_result_observation(observation_id=next_observation.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1), project_current=True, correction_apply_enabled=False)
        self.assertTrue(decision.projected, decision)
        self.assertEqual(self.event.results.count(), 2)
        self.assertEqual(models.RaceEventRevision.objects.get(pk=decision.revision_id).items.get(reported_finish_position=1).participant_id, participant)

    def test_partial_refresh_cannot_erase_previously_known_popularity(self):
        source = self._source("jra", "official_operator", "jra-result")
        rows = self._rows()[:1]
        rows[0]['field_provenance'] = {'source_fields': {'popularity': '2'}}
        first = self._observation(source, 'official_operator', rows, result_phase='provisional')
        initial = apply_data_sync_result_observation(observation_id=first.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(initial.projected, initial)
        self.assertEqual(self.event.results.get().popularity, '2')
        next_observation = self._observation(source, 'official_operator', self._rows(),
                                            result_phase='provisional', observed_at=NOW + timedelta(minutes=1))
        decision = apply_data_sync_result_observation(observation_id=next_observation.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1), project_current=True, correction_apply_enabled=False)
        self.assertEqual(decision.reason_code, 'provisional_result_regression')
        self.assertEqual(self.event.results.get().popularity, '2')

    def test_partial_refresh_cannot_erase_previously_known_time(self):
        rows = self._rows()[:1]
        rows[0]['finish_time'] = '1:30.0'
        first = self._observation(self.source, 'licensed_api', rows, result_phase='provisional')
        initial = apply_data_sync_result_observation(observation_id=first.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=False)
        self.assertTrue(initial.projected, initial)
        next_observation = self._observation(self.source, 'licensed_api', self._rows(),
                                            result_phase='provisional', observed_at=NOW + timedelta(minutes=1))
        decision = apply_data_sync_result_observation(observation_id=next_observation.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1), project_current=True, correction_apply_enabled=False)
        self.assertEqual(decision.reason_code, 'provisional_result_regression')
        self.assertEqual(self.event.results.get().finish_time, '1:30.0')

    def test_partial_refresh_cannot_drop_existing_known_rows(self):
        for rows, at in ((self._rows(), NOW), (self._rows()[:1], NOW + timedelta(minutes=1))):
            observation = self._observation(self.source, "licensed_api", rows,
                                            result_phase="provisional", observed_at=at)
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk, expected_event_id=self.event.pk,
                now=at, project_current=True, correction_apply_enabled=False)
        self.assertEqual(decision.reason_code, "provisional_result_regression")
        self.assertEqual(self.event.results.count(), 2)

    def test_winner_only_publishes_provisional_without_confirming_complete_result(self):
        observation = self._observation(self.source, "licensed_api", self._rows()[:1],
                                        result_phase=models.RaceResultPhase.PROVISIONAL)
        apply_data_sync_result_observation(
            observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=True,
        )
        self.event.refresh_from_db()
        self.control.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertIsNone(self.event.result_confirmed_at)
        self.assertIsNotNone(self.control.current_result_revision_id)
        self.assertEqual(list(models.RaceEventResult.objects.values_list("is_confirmed", flat=True)), [False])
        self.assertTrue(models.RaceEventLifecycleTransition.objects.filter(
            event=self.event, reason_code="data_sync_winner_observed").exists())
        from stable.views import _with_winner_evidence, _public_race_status_label
        public_event = _with_winner_evidence(models.RaceEvent.objects.filter(pk=self.event.pk)).get()
        self.assertEqual(_public_race_status_label(public_event, NOW.date(), now=NOW), "已完赛")

    @override_settings(RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=1,
                       RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1,
                       RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2*1024**2,
                       RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8*1024**2,
                       RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=1024**3,
                       RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=512*1024**2,
                       RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1, RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
                       RACE_DATA_RAW_CLEANUP_MAX_BYTES=1024**2,
                       RACE_DATA_RAW_HOLD_ALERT_BYTES=1024**3)
    def test_verified_result_claim_bypasses_daily_budget_but_not_disk_protection(self):
        from stable.services.race_priority import result_transport_scope
        from stable.services.race_data_sync_pipeline import reserve_race_data_transport_capacity
        claim = self._claim_guard()
        models.RaceDataTransportCapacityLedger.objects.create(
            provider=self.source.source_key, region_code=self.source.region_code,
            usage_date=NOW.date(), request_count=1, budgeted_response_bytes=1,
        )
        def reserve():
            return reserve_race_data_transport_capacity(
                provider=self.source.source_key, region_code=self.source.region_code,
                now=NOW, proposed_requests=1, max_response_bytes_per_request=1024,
            )
        with patch("django.utils.timezone.now", return_value=NOW), patch(
            "stable.services.race_data_sync_pipeline.inspect_race_data_artifact_capacity",
            return_value=(0, 100 * 1024**3),
        ) as disk:
            self.assertFalse(reserve().allowed)
            with result_transport_scope(claim):
                self.assertTrue(reserve().allowed)
                disk.return_value = (0, 0)
                self.assertEqual(reserve().reason_code, "artifact_min_free_disk")
            disk.return_value = (0, 100 * 1024**3)
            self.assertFalse(reserve().allowed)

    def test_transport_metadata_does_not_create_result_correction(self):
        rows = self._rows()
        rows[0]["field_provenance"] = {"raw_sha256": "a" * 64, "observed_at": NOW.isoformat()}
        first = self._observation(self.source, "licensed_api", rows)
        original = apply_data_sync_result_observation(
            observation_id=first.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=True,
        )
        rows = self._rows()
        rows[0]["field_provenance"] = {"raw_sha256": "b" * 64, "observed_at": (NOW + timedelta(minutes=1)).isoformat()}
        second = self._observation(self.source, "licensed_api", rows, observed_at=NOW + timedelta(minutes=1))
        replay = apply_data_sync_result_observation(
            observation_id=second.pk, expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1), project_current=True, correction_apply_enabled=True,
        )
        self.assertEqual(replay.action, "replayed")
        self.assertEqual(replay.revision_id, original.revision_id)
        self.assertEqual(models.RaceEventRevision.objects.filter(event=self.event, kind="result").count(), 1)

    def test_same_source_can_fill_missing_time_but_cannot_change_existing_time(self):
        for index, finish_time in enumerate(("", "1:30.1", "1:31.2")):
            rows = self._rows()
            rows[0]["finish_time"] = finish_time
            observation = self._observation(self.source, "licensed_api", rows,
                                            observed_at=NOW + timedelta(minutes=index))
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk, expected_event_id=self.event.pk,
                now=NOW + timedelta(minutes=index), project_current=True,
                correction_apply_enabled=False,
            )
            if index < 2:
                self.assertTrue(decision.projected, decision)
            else:
                self.assertFalse(decision.projected, decision)
        self.assertEqual(self.event.results.get(reported_finish_position=1).finish_time, "1:30.1")

    def test_complete_result_projects_and_finishes_event_without_human_review(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(decision.action, "applied")
        self.assertTrue(decision.projected)
        self.event.refresh_from_db()
        self.control.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(self.event.result_confirmed_at, NOW)
        self.assertEqual(
            self.control.current_result_revision_id,
            decision.revision_id,
        )
        results = list(self.event.results.order_by("finish_position"))
        self.assertEqual([row.finish_position for row in results], [1, 2])
        self.assertEqual([row.reported_finish_position for row in results], [1, 2])
        self.assertTrue(all(row.is_confirmed for row in results))
        self.assertEqual(
            models.RaceEventLifecycleTransition.objects.get().reason_code,
            "data_sync_winner_observed",
        )

    def test_matching_shadow_revision_is_promoted_when_publication_opens(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        shadow = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=False,
            correction_apply_enabled=True,
        )
        self.assertEqual(shadow.action, "recorded")
        self.assertFalse(shadow.projected)
        revision = models.RaceEventRevision.objects.get(pk=shadow.revision_id)
        self.assertIsNone(revision.published_at)
        self.assertEqual(revision.official_confirmed_at, NOW)

        promoted = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1),
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(promoted.action, "applied")
        self.assertEqual(promoted.reason_code, "shadow_revision_promoted")
        self.assertEqual(promoted.revision_id, shadow.revision_id)
        self.assertTrue(promoted.projected)
        self.control.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, shadow.revision_id)
        self.assertEqual(self.control.next_result_revision_no, 2)
        self.assertEqual(models.RaceEventRevision.objects.count(), 1)
        self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 1)
        self.assertEqual(models.RaceEventResult.objects.count(), 2)

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    )
    def test_data_sync_publication_is_visible_in_detail_and_bulk_resolvers(self):
        self._public_enrollment()
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected, applied)

        detail = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=NOW + timedelta(seconds=1),
        )
        source_manager = models.RaceResultSourceIdentity.objects
        with patch.object(
            source_manager,
            "filter",
            wraps=source_manager.filter,
        ) as source_filter:
            bulk = race_events.resolve_race_live_public_reads(
                event_ids=[self.event.pk],
                now=NOW + timedelta(seconds=1),
            )[self.event.pk]

        self.assertTrue(detail.visible, detail.reason)
        self.assertNotEqual(
            self.standing_policy_raw_sha256,
            self.standing_policy_digest,
        )
        self.assertEqual(detail.reason, "data_sync_public_read_allowed")
        self.assertEqual(bulk, detail)
        self.assertEqual(source_filter.call_count, 1)

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    )
    def test_legacy_publication_survives_standing_policy_successor(self):
        enrollment = self._public_enrollment()
        observation = self._observation(self.source, "licensed_api", self._rows())
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected, applied)
        policy_path = Path(self._policy_directory.name) / "standing_policy.json"
        policy = json.loads(policy_path.read_bytes())
        policy["policy_id"] += "-successor"
        raw = json.dumps(policy, indent=2).encode()
        policy_path.write_bytes(raw)
        self.assertNotEqual(parse_standing_policy(policy).digest, enrollment.standing_policy_digest)
        tables = (
            models.RaceDataSyncEnrollment, models.RaceEventRevision,
            models.RaceEventRevisionPublication, models.RaceEventResult,
        )
        before = [list(model.objects.values()) for model in tables]

        with self.settings(RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=hashlib.sha256(raw).hexdigest()):
            detail = race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW + timedelta(seconds=1))
            bulk = race_events.resolve_race_live_public_reads(event_ids=[self.event.pk], now=NOW + timedelta(seconds=1))[self.event.pk]

        self.assertTrue(detail.visible, detail.reason)
        self.assertEqual(bulk, detail)
        self.assertEqual(before, [list(model.objects.values()) for model in tables])

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    )
    def test_legacy_policy_successor_does_not_bypass_remaining_guards(self):
        enrollment = self._public_enrollment()
        observation = self._observation(self.source, "licensed_api", self._rows())
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk, expected_event_id=self.event.pk,
            now=NOW, project_current=True, correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected, applied)
        enrollment.standing_policy_digest = "9" * 64
        enrollment.save(update_fields=("standing_policy_digest",))
        membership = models.RaceEventLifecycleEnforceMembership.objects.get(event=self.event)
        publication = models.RaceEventRevisionPublication.objects.get(revision_id=applied.revision_id)
        cases = (
            (membership, "state", "inactive"),
            (membership.registry, "runtime_valid_until", NOW),
            (self.lifecycle, "manual_pause_reason", "operator pause"),
            (self.source, "valid_until", NOW),
            (enrollment, "enrollment_generation", 2),
            (enrollment, "route_digest", "0" * 64),
            (publication, "registry_digest", "0" * 64),
        )
        for instance, field, changed in cases:
            with self.subTest(model=type(instance).__name__, field=field):
                original = getattr(instance, field)
                setattr(instance, field, changed)
                instance.save(update_fields=(field,))
                detail = race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW + timedelta(seconds=1))
                bulk = race_events.resolve_race_live_public_reads(event_ids=[self.event.pk], now=NOW + timedelta(seconds=1))[self.event.pk]
                self.assertFalse(detail.visible)
                self.assertEqual(bulk, detail)
                setattr(instance, field, original)
                instance.save(update_fields=(field,))

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api", "sporting_life"),
        RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra", "united_kingdom"),
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
        RACE_DATA_SYNC_REFERENCE_REGISTRY_SHA256="9" * 64,
    )
    def test_fallback_publication_retains_original_enrollment_evidence(self):
        self.roster = build_race_data_provider_roster(configuration_only=True)
        self.source.registry_digest = self.roster.registry_digest
        self.source.save(update_fields=("registry_digest", "updated_at"))
        enrollment = self._public_enrollment()
        fallback_source = self._source(
            "sporting_life", "trusted_publisher", "fallback-result"
        )
        fallback_source.region_code = "united_kingdom"
        fallback_source.identity_namespace = "sporting_life-race-v1"
        fallback_source.save(
            update_fields=("region_code", "identity_namespace", "updated_at")
        )
        fallback_route = resolve_race_data_provider_route(
            provider=fallback_source.source_key,
            region=fallback_source.region_code,
            identity_namespace=fallback_source.identity_namespace,
            data_kinds=(models.RaceDataSyncDataKind.RESULT,),
        )
        self.assertIsNotNone(fallback_route)
        fallback_source.proof_network_allowed = True
        fallback_source.evidence_url = "https://www.sportinglife.com/racing/results/"
        fallback_source.evidence_sha256 = "a" * 64
        fallback_source.registry_digest = fallback_route.registry_digest
        fallback_source.save(
            update_fields=(
                "proof_network_allowed",
                "evidence_url",
                "evidence_sha256",
                "registry_digest",
                "updated_at",
            )
        )
        observation = self._observation(
            fallback_source,
            "trusted_publisher",
            self._rows(first_name="Fallback Alpha"),
        )
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        # 仅赛果来源不能在初始投影中绕过获胜来源（决定①/F-R2）；
        # 其证据以 observation/revision 保留，enrollment 证据不被改写。
        self.assertFalse(applied.projected)
        revision = models.RaceEventRevision.objects.get(pk=applied.revision_id)
        self.assertIsNone(revision.published_at)
        self.assertEqual(revision.decision_reason, "not_granted_source")

        decision = race_events.resolve_race_live_public_read(
            event_id=self.event.pk,
            now=NOW + timedelta(seconds=1),
        )

        self.assertFalse(decision.visible)
        self.assertEqual(enrollment.source_identity_id, self.source.pk)
        self.assertNotEqual(
            observation.source_identity_id,
            enrollment.source_identity_id,
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    )
    def test_data_sync_public_read_fails_closed_on_contract_drift(self):
        enrollment = self._public_enrollment()
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected)
        lifecycle_membership = (
            models.RaceEventLifecycleEnforceMembership.objects.get(
                event=self.event
            )
        )
        cases = (
            (self.source, "valid_until", NOW),
            (enrollment, "enrollment_generation", 2),
            (observation, "field_provenance", {
                **observation.field_provenance,
                "contract_digest": "0" * 64,
            }),
            (
                models.RaceEventRevisionPublication.objects.get(
                    revision_id=applied.revision_id
                ),
                "registry_digest",
                "0" * 64,
            ),
            (lifecycle_membership, "state", "inactive"),
        )
        for instance, field, drifted in cases:
            with self.subTest(model=type(instance).__name__, field=field):
                original = getattr(instance, field)
                setattr(instance, field, drifted)
                instance.save(update_fields=(field, "updated_at"))
                detail = race_events.resolve_race_live_public_read(
                    event_id=self.event.pk,
                    now=NOW + timedelta(seconds=1),
                )
                bulk = race_events.resolve_race_live_public_reads(
                    event_ids=[self.event.pk],
                    now=NOW + timedelta(seconds=1),
                )[self.event.pk]
                self.assertFalse(detail.visible)
                self.assertEqual(bulk, detail)
                setattr(instance, field, original)
                instance.save(update_fields=(field, "updated_at"))

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
        RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
        RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    )
    def test_data_sync_public_read_fails_closed_on_policy_file_sha_drift(self):
        self._public_enrollment()
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        applied = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(applied.projected)

        with self.settings(
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256="0" * 64,
        ):
            detail = race_events.resolve_race_live_public_read(
                event_id=self.event.pk,
                now=NOW + timedelta(seconds=1),
            )
            bulk = race_events.resolve_race_live_public_reads(
                event_ids=[self.event.pk],
                now=NOW + timedelta(seconds=1),
            )[self.event.pk]

        self.assertFalse(detail.visible)
        self.assertEqual(detail.reason, "data_sync_standing_policy_unavailable")
        self.assertEqual(bulk, detail)

    def test_superseded_claim_cannot_project_result_before_completion_cas(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        guard = self._claim_guard()
        tracking = self.event.live_tracking
        tracking.claim_generation = 2
        tracking.active_attempt_token = "result-claim-2"
        tracking.save(
            update_fields=("claim_generation", "active_attempt_token")
        )

        with patch("stable.services.race_data_sync_results.timezone.now", return_value=NOW):
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW,
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=guard,
            )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_cas_stale")
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_expired_claim_cannot_project_result(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        guard = self._claim_guard(expires_at=NOW)

        with patch("stable.services.race_data_sync_results.timezone.now", return_value=NOW):
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW,
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=guard,
            )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_expired")
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_claim_for_another_data_kind_cannot_project_result(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        guard = self._claim_guard(data_kind=models.RaceDataSyncDataKind.RACECARD)

        with patch("stable.services.race_data_sync_results.timezone.now", return_value=NOW):
            decision = apply_data_sync_result_observation(
                observation_id=observation.pk,
                expected_event_id=self.event.pk,
                now=NOW,
                project_current=True,
                correction_apply_enabled=True,
                claim_guard=guard,
            )

        self.assertEqual(decision.action, "rejected")
        self.assertEqual(decision.reason_code, "claim_plan_drift")
        self.assertFalse(models.RaceEventRevision.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_dead_heat_keeps_duplicate_reported_positions_with_unique_internal_order(self):
        rows = self._rows(first_position=1)
        rows[1]["reported_finish_position"] = 1
        rows[0]["status"] = models.RaceEventRevisionItemStatus.DEAD_HEAT
        rows[1]["status"] = models.RaceEventRevisionItemStatus.DEAD_HEAT
        observation = self._observation(self.source, "licensed_api", rows)
        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(decision.action, "applied")
        results = list(self.event.results.order_by("finish_position"))
        self.assertEqual([row.finish_position for row in results], [1, 2])
        self.assertEqual([row.reported_finish_position for row in results], [1, 1])

    def test_provider_declaration_order_does_not_control_internal_result_order(self):
        rows = list(reversed(self._rows()))
        observation = self._observation(
            self.source, "licensed_api", rows
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.action, "applied")
        results = list(self.event.results.order_by("finish_position"))
        self.assertEqual(
            [(row.horse_name, row.reported_finish_position) for row in results],
            [("Alpha", 1), ("Beta", 2)],
        )

    def test_fallback_result_reuses_canonical_racecard_participants(self):
        canonical_participants = {}
        for runner in self.event.runners.order_by("horse_number"):
            participant = models.RaceEventParticipant.objects.create(
                event=self.event,
                stable_key=f"canonical:{runner.external_runner_id}",
                canonical_name=runner.horse_name,
                country_region=self.event.country_region,
                review_status=models.RaceLiveReviewStatus.APPROVED,
            )
            models.RaceEventParticipantSourceIdentity.objects.create(
                participant=participant,
                source_identity=self.source,
                external_runner_id=runner.external_runner_id,
            )
            canonical_participants[runner.horse_name] = participant
        fallback_source = self._source(
            "jra", "official_operator", "fallback-result"
        )
        for runner in self.event.runners.all():
            refs = dict(runner.source_refs)
            refs.pop(fallback_source.source_key, None)
            runner.source_refs = refs
            runner.save(update_fields=("source_refs", "updated_at"))
        rows = self._rows()
        for index, row in enumerate(rows, start=1):
            row["external_runner_id"] = f"fallback-horse-{index}"
        observation = self._observation(
            fallback_source, "official_operator", rows
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.action, "applied")
        revision = models.RaceEventRevision.objects.get(pk=decision.revision_id)
        self.assertEqual(
            set(revision.items.values_list("participant_id", flat=True)),
            {participant.pk for participant in canonical_participants.values()},
        )
        self.assertEqual(models.RaceEventParticipant.objects.count(), 2)
        for identity in fallback_source.participant_identities.select_related(
            "participant"
        ):
            self.assertEqual(
                identity.participant_id,
                canonical_participants[identity.participant.canonical_name].pk,
            )

    def test_lower_priority_result_is_recorded_but_does_not_replace_api(self):
        api = self._observation(self.source, "licensed_api", self._rows())
        first = apply_data_sync_result_observation(
            observation_id=api.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        official_source = self._source(
            "jra", "official_operator", "official-result"
        )
        official = self._observation(
            official_source,
            "official_operator",
            self._rows(first_name="Official Alpha"),
            observed_at=NOW + timedelta(minutes=1),
        )
        second = apply_data_sync_result_observation(
            observation_id=official.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1),
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(second.action, "recorded")
        self.assertFalse(second.projected)
        self.control.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, first.revision_id)
        self.assertEqual(self.event.results.get(finish_position=1).horse_name, "Alpha")

    def test_higher_priority_result_replaces_fallback_only_after_correction_gate(self):
        fallback_source = self._source(
            "jra", "official_operator", "official-result"
        )
        fallback = self._observation(
            fallback_source,
            "official_operator",
            self._rows(first_name="Fallback Alpha"),
        )
        first = apply_data_sync_result_observation(
            observation_id=fallback.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertTrue(first.projected)
        licensed = self._observation(
            self.source,
            "licensed_api",
            self._rows(first_name="Licensed Alpha"),
            observed_at=NOW + timedelta(minutes=1),
        )

        blocked = apply_data_sync_result_observation(
            observation_id=licensed.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1),
            project_current=True,
            correction_apply_enabled=False,
        )
        self.assertEqual(blocked.reason_code, "correction_apply_disabled")
        applied = apply_data_sync_result_observation(
            observation_id=licensed.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1),
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(applied.action, "applied")
        self.assertTrue(applied.projected)
        revision = models.RaceEventRevision.objects.get(pk=applied.revision_id)
        self.assertEqual(revision.supersedes_id, first.revision_id)
        self.assertEqual(
            self.event.results.get(finish_position=1).horse_name,
            "Licensed Alpha",
        )

    def test_same_source_correction_requires_flag_then_replaces_current(self):
        first_observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        apply_data_sync_result_observation(
            observation_id=first_observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        correction = self._observation(
            self.source,
            "licensed_api",
            self._rows(first_name="Corrected Alpha"),
            observed_at=NOW + timedelta(minutes=2),
            race_status="corrected",
            result_phase=models.RaceResultPhase.CORRECTED,
            provenance_overrides={"correction_marker": True},
        )
        blocked = apply_data_sync_result_observation(
            observation_id=correction.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=2),
            project_current=True,
            correction_apply_enabled=False,
        )
        self.assertEqual(blocked.reason_code, "correction_apply_disabled")
        applied = apply_data_sync_result_observation(
            observation_id=correction.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=2),
            project_current=True,
            correction_apply_enabled=True,
        )
        self.assertEqual(applied.action, "applied")
        self.assertEqual(
            self.event.results.get(finish_position=1).horse_name,
            "Corrected Alpha",
        )

    def test_changed_official_result_without_correction_marker_stays_conflict(self):
        baseline = self._observation(
            self.source, "licensed_api", self._rows()
        )
        applied = apply_data_sync_result_observation(
            observation_id=baseline.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        unmarked = self._observation(
            self.source,
            "licensed_api",
            self._rows(first_name="Unmarked Alpha"),
            observed_at=NOW + timedelta(minutes=2),
        )

        conflict = apply_data_sync_result_observation(
            observation_id=unmarked.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=2),
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(conflict.action, "recorded")
        self.assertEqual(conflict.reason_code, "correction_marker_missing")
        self.assertFalse(conflict.projected)
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_result_revision_id, applied.revision_id
        )
        revision = models.RaceEventRevision.objects.get(pk=conflict.revision_id)
        self.assertEqual(
            revision.conflict_status,
            models.RaceEventRevisionConflictStatus.PENDING,
        )
        self.assertEqual(
            self.event.results.get(finish_position=1).horse_name,
            "Alpha",
        )

    def test_terminal_result_requires_complete_competition_ranking(self):
        rows = self._rows()
        rows[1]["reported_finish_position"] = 3
        observation = self._observation(
            self.source, "licensed_api", rows
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.reason_code, "result_payload_incomplete")
        self.assertFalse(models.RaceEventRevision.objects.exists())

    def test_non_finisher_cannot_carry_numeric_finish_position(self):
        rows = self._rows()
        rows[1]["status"] = models.RaceEventRevisionItemStatus.DID_NOT_FINISH
        observation = self._observation(
            self.source, "licensed_api", rows
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.reason_code, "result_payload_incomplete")
        self.assertFalse(models.RaceEventRevision.objects.exists())

    def test_result_is_shadow_only_when_lifecycle_registry_membership_is_missing(self):
        models.RaceEventLifecycleEnforceMembership.objects.all().delete()
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.action, "recorded")
        self.assertFalse(decision.projected)
        self.assertNotEqual(decision.reason_code, "")
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_provisional_complete_roster_is_public_without_confirmation(self):
        observation = self._observation(
            self.source,
            "licensed_api",
            self._rows(),
            race_status="running",
            result_phase=models.RaceResultPhase.PROVISIONAL,
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.action, "applied")
        self.assertTrue(decision.projected)
        self.assertEqual(models.RaceEventResult.objects.filter(is_confirmed=False).count(), 2)
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.last_provisional_result_revision_id,
            decision.revision_id,
        )
        self.assertEqual(self.control.current_result_revision_id, decision.revision_id)

    def test_official_phase_without_registered_terminal_marker_is_rejected(self):
        observation = self._observation(
            self.source,
            "licensed_api",
            self._rows(),
            race_status="running",
        )

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.reason_code, "terminal_marker_missing")
        self.assertFalse(models.RaceEventRevision.objects.exists())

    def test_partial_terminal_result_cannot_replace_existing_public_result(self):
        baseline = self._observation(
            self.source, "licensed_api", self._rows()
        )
        applied = apply_data_sync_result_observation(
            observation_id=baseline.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )
        partial = self._observation(
            self.source,
            "licensed_api",
            self._rows(first_name="Partial Alpha")[:1],
            observed_at=NOW + timedelta(minutes=1),
        )

        decision = apply_data_sync_result_observation(
            observation_id=partial.pk,
            expected_event_id=self.event.pk,
            now=NOW + timedelta(minutes=1),
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.reason_code, "result_roster_incomplete")
        self.control.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, applied.revision_id)
        self.assertEqual(
            self.event.results.get(finish_position=1).horse_name,
            "Alpha",
        )

    def test_expired_source_contract_is_rejected_at_apply_time(self):
        observation = self._observation(
            self.source, "licensed_api", self._rows()
        )
        self.source.valid_until = NOW
        self.source.save(update_fields=("valid_until", "updated_at"))

        decision = apply_data_sync_result_observation(
            observation_id=observation.pk,
            expected_event_id=self.event.pk,
            now=NOW,
            project_current=True,
            correction_apply_enabled=True,
        )

        self.assertEqual(decision.reason_code, "source_contract_mismatch")
        self.assertFalse(models.RaceEventRevision.objects.exists())

    def test_registry_and_contract_drift_are_rejected_at_apply_time(self):
        for key in ("registry_digest", "contract_digest"):
            with self.subTest(key=key):
                observation = self._observation(
                    self.source,
                    "licensed_api",
                    self._rows(),
                    provenance_overrides={key: "f" * 64},
                )
                decision = apply_data_sync_result_observation(
                    observation_id=observation.pk,
                    expected_event_id=self.event.pk,
                    now=NOW,
                    project_current=True,
                    correction_apply_enabled=True,
                )
                self.assertEqual(
                    decision.reason_code,
                    "source_contract_mismatch",
                )
                observation.delete()
                self.assertFalse(models.RaceEventRevision.objects.exists())
