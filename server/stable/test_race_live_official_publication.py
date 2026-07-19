from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import inspect
from io import StringIO
import json
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable.services import race_events
from stable.services import race_live_manual_official_evidence
from stable.services import race_live_publication_transition


REPO_ROOT = Path(__file__).resolve().parents[2]


class RaceLiveOfficialPublicationSchemaTests(SimpleTestCase):
    def test_additive_official_authorization_model_has_independent_route_gates(self):
        authorization = getattr(
            models,
            "RaceLiveOfficialPublicationAuthorization",
            None,
        )
        self.assertIsNotNone(
            authorization,
            "独立 official publication authorization 模型尚未实现",
        )
        field_names = {
            field.name for field in authorization._meta.get_fields()
        }
        self.assertTrue(
            {
                "event",
                "source_key",
                "route",
                "route_version",
                "route_registry_digest",
                "contract_digest",
                "terms_evidence_digest",
                "coverage_proof_digest",
                "max_phase",
                "enabled",
                "version",
                "valid_until",
            }.issubset(field_names)
        )

    def test_publication_audit_distinguishes_policy_from_official_route(self):
        field_names = {
            field.name
            for field in models.RaceEventRevisionPublication._meta.get_fields()
        }
        self.assertIn("authorization_kind", field_names)
        self.assertIn("official_authorization_version", field_names)

    def test_projection_control_has_a_dedicated_provisional_rollback_pointer(self):
        field_names = {
            field.name
            for field in models.RaceEventProjectionControl._meta.get_fields()
        }
        self.assertIn("last_provisional_result_revision", field_names)
        field = models.RaceEventProjectionControl._meta.get_field(
            "last_provisional_result_revision"
        )
        self.assertTrue(field.null)
        self.assertEqual(
            field.remote_field.model,
            models.RaceEventRevision,
        )

    def test_migration_0047_exists_as_the_additive_schema_boundary(self):
        migrations = sorted(
            path.name
            for path in (REPO_ROOT / "server" / "stable" / "migrations").glob(
                "0047_*.py"
            )
        )
        self.assertEqual(len(migrations), 1)


class RaceLiveOfficialAuthorizationResolverContractTests(SimpleTestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def test_manual_source_network_permission_remains_denied(self):
        decision = race_events.resolve_race_source_network_permission(
            mode="production",
            terms_status=models.RaceSourceTermsStatus.MANUAL,
            automation_allowed=False,
            proof_network_allowed=False,
            valid_until=self.NOW + timedelta(days=30),
            evidence_sha256="a" * 64,
            registry_digest="b" * 64,
            expected_registry_digest="b" * 64,
            manifest_approved=True,
            request_budget=1,
            historical_handoff_complete=True,
            now=self.NOW,
        )
        self.assertIs(decision.allowed, False)
        self.assertEqual(decision.reason, "terms_not_approved")

    def test_official_read_and_admission_share_an_independent_resolver(self):
        resolver = getattr(
            race_events,
            "resolve_race_live_official_publication_authorization",
            None,
        )
        self.assertTrue(
            callable(resolver),
            "official/corrected 独立 publication resolver 尚未实现",
        )

    def test_emergency_restore_is_an_explicit_service(self):
        restore = getattr(
            race_events,
            "restore_last_provisional_result",
            None,
        )
        self.assertTrue(
            callable(restore),
            "专用 provisional emergency restore 尚未实现",
        )

    def test_planned_policy_validator_is_an_explicit_service(self):
        validator = getattr(
            race_events,
            "validate_race_live_provisional_rollback_target",
            None,
        )
        self.assertTrue(
            callable(validator),
            "planned-policy rollback target validator 尚未实现",
        )


class RaceLiveOfficialAuthorizationBehaviorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)
    TRA_DIGEST = "a" * 64
    ROUTE_DIGEST = "b" * 64
    COVERAGE_DIGEST = "c" * 64
    CONTRACT_DIGEST = "d" * 64
    TERMS_DIGEST = "e" * 64

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="fr-official-authorization",
            original_name="French Official Test",
            chinese_name="法国正式授权测试",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
        )
        self.tra_source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="fr-tra-1",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=self.NOW + timedelta(days=30),
            evidence_sha256="f" * 64,
            registry_digest=self.TRA_DIGEST,
        )
        self.official_source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="france_galop",
            external_race_id="fr-official-1",
            host="www.france-galop.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.OFFICIAL,
            terms_status=models.RaceSourceTermsStatus.MANUAL,
            automation_allowed=False,
            valid_until=self.NOW + timedelta(days=30),
            evidence_sha256=self.TERMS_DIGEST,
            registry_digest=self.ROUTE_DIGEST,
        )
        self.observation = models.RaceResultObservation.objects.create(
            source_identity=self.official_source,
            observed_at=self.NOW,
            parser_version="manual-official-v1",
            raw_sha256="1" * 64,
            normalized_sha256="2" * 64,
            result_phase=models.RaceResultPhase.OFFICIAL,
        )
        contract = models.RaceLiveOfficialMarkerContract.objects.create(
            country_region=models.RacingRegion.FRANCE,
            source_key="france_galop",
            parser_version="manual-official-v1",
            allowed_marker_types=["official_result"],
            contract_digest=self.CONTRACT_DIGEST,
            valid_until=self.NOW + timedelta(days=30),
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceLiveOfficialMarkerEvidence.objects.create(
            observation=self.observation,
            contract=contract,
            marker_type="official_result",
            contract_digest=self.CONTRACT_DIGEST,
            parser_version="manual-official-v1",
            raw_sha256=self.observation.raw_sha256,
            source_timestamp=self.NOW,
        )
        for scope_type, scope_key in (
            (models.RaceLivePublicationScopeType.GLOBAL, "global"),
            (
                models.RaceLivePublicationScopeType.REGION,
                models.RacingRegion.FRANCE,
            ),
            (
                models.RaceLivePublicationScopeType.SOURCE,
                "the_racing_api",
            ),
            (
                models.RaceLivePublicationScopeType.EVENT,
                str(self.event.pk),
            ),
        ):
            models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=(
                    models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                    if scope_type == models.RaceLivePublicationScopeType.SOURCE
                    else models.RaceLivePublicationMode.OFFICIAL_PUBLIC
                ),
                registry_digest=self.TRA_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                valid_until=self.NOW + timedelta(days=30),
            )
        models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key="the_racing_api",
            max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            official_verification_route=(
                "france_galop_manual_verification"
            ),
            official_verification_route_version="manual-v1",
            official_verification_contract_digest=self.CONTRACT_DIGEST,
            official_terms_evidence_digest=self.TERMS_DIGEST,
            official_verification_valid_until=self.NOW + timedelta(days=30),
            enabled=True,
        )
        self.authorization = (
            models.RaceLiveOfficialPublicationAuthorization.objects.create(
                event=self.event,
                source_key="france_galop",
                route="france_galop_manual_verification",
                route_version="manual-v1",
                route_registry_digest=self.ROUTE_DIGEST,
                contract_digest=self.CONTRACT_DIGEST,
                terms_evidence_digest=self.TERMS_DIGEST,
                coverage_proof_digest=self.COVERAGE_DIGEST,
                max_phase=models.RaceResultPhase.OFFICIAL,
                enabled=True,
                valid_until=self.NOW + timedelta(days=30),
            )
        )

    def test_valid_official_route_is_allowed_without_automating_manual_source(self):
        decision = (
            race_events.resolve_race_live_official_publication_authorization(
                event_id=self.event.pk,
                observation_id=self.observation.pk,
                phase=models.RaceResultPhase.OFFICIAL,
                now=self.NOW,
            )
        )
        self.assertIs(decision.allowed, True)
        self.assertEqual(decision.authorization_version, 1)
        self.official_source.refresh_from_db()
        self.assertIs(self.official_source.automation_allowed, False)

    def test_route_version_drift_fails_closed(self):
        self.authorization.route_version = "manual-v2"
        self.authorization.save(update_fields=("route_version", "updated_at"))

        decision = (
            race_events.resolve_race_live_official_publication_authorization(
                event_id=self.event.pk,
                observation_id=self.observation.pk,
                phase=models.RaceResultPhase.OFFICIAL,
                now=self.NOW,
            )
        )

        self.assertIs(decision.allowed, False)
        self.assertEqual(decision.reason, "official_route_version_mismatch")


@override_settings(
    RACE_LIVE_SCHEDULER_ENABLED=False,
    RACE_LIVE_MONITOR_ENABLED=False,
)
class RaceLiveProvisionalRollbackBehaviorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)
    REGISTRY_DIGEST = "a" * 64
    COVERAGE_DIGEST = "b" * 64
    MANIFEST_DIGEST = "c" * 64

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="rollback-provisional-contract",
            original_name="Rollback Provisional Contract",
            chinese_name="暂定赛果回滚控制面测试",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            status=models.RaceEventStatus.FINISHED,
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="rollback-tra-1",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=self.NOW + timedelta(days=30),
            evidence_sha256="d" * 64,
            registry_digest=self.REGISTRY_DIGEST,
        )
        observation = models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW,
            parser_version="tra-v1",
            raw_sha256="e" * 64,
            normalized_sha256="f" * 64,
            result_phase=models.RaceResultPhase.PROVISIONAL,
        )
        participant = models.RaceEventParticipant.objects.create(
            event=self.event,
            stable_key="winner",
            canonical_name="Rollback Winner",
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        self.provisional = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256="1" * 64,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            primary_observation=observation,
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
        official_observation = models.RaceResultObservation.objects.create(
            source_identity=self.source,
            observed_at=self.NOW + timedelta(minutes=5),
            parser_version="tra-v1",
            raw_sha256="2" * 64,
            normalized_sha256="3" * 64,
            result_phase=models.RaceResultPhase.OFFICIAL,
        )
        self.current = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=2,
            phase=models.RaceResultPhase.OFFICIAL,
            content_sha256="4" * 64,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            primary_observation=official_observation,
            published_at=self.NOW + timedelta(minutes=5),
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            current_result_revision=self.current,
            last_known_good_result_revision=self.current,
            last_provisional_result_revision=self.provisional,
            next_result_revision_no=3,
        )
        self.tracking = models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=models.RaceEventLiveState.OFFICIAL_RESULT,
            official_published_at=self.current.published_at,
        )
        self.allowlist = models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key=self.source.source_key,
            max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            enabled=True,
        )
        self.publication = models.RaceEventRevisionPublication.objects.create(
            revision=self.provisional,
            published_at=self.provisional.published_at,
            reason="test_fixture",
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
            self.policies[f"{scope_type}:{scope_key}"] = (
                models.RaceLivePublicationPolicy.objects.create(
                    scope_type=scope_type,
                    scope_key=scope_key,
                    mode=models.RaceLivePublicationMode.OFF,
                    version=10,
                    registry_digest=self.REGISTRY_DIGEST,
                    coverage_proof_digest=self.COVERAGE_DIGEST,
                    valid_until=self.NOW + timedelta(days=30),
                )
            )
        models.RaceEventResult.objects.create(
            event=self.event,
            finish_position=1,
            official_finish_position=1,
            horse_name="Official Winner",
            is_confirmed=True,
        )

    def _policy_payload(self, policy, *, mode, version):
        return {
            "mode": mode,
            "version": version,
            "registry_digest": policy.registry_digest,
            "coverage_proof_digest": policy.coverage_proof_digest,
            "valid_until": policy.valid_until.isoformat(),
        }

    def _snapshot(self):
        result = {}
        for key, policy in self.policies.items():
            result[key] = {
                "maintenance": self._policy_payload(
                    policy,
                    mode=models.RaceLivePublicationMode.OFF,
                    version=10,
                ),
                "restore": self._policy_payload(
                    policy,
                    mode=(
                        models.RaceLivePublicationMode.OFFICIAL_PUBLIC
                        if key.startswith("global:")
                        or key.startswith("region:")
                        else models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                    ),
                    version=11,
                ),
            }
        return result

    def _restore_kwargs(self):
        return {
            "event_id": self.event.pk,
            "expected_current_revision_id": self.current.pk,
            "expected_provisional_revision_id": self.provisional.pk,
            "planned_policy_snapshot": self._snapshot(),
            "expected_allowlist_version": self.allowlist.version,
            "expected_publication_id": self.publication.pk,
            "expected_tracking_lock_version": self.tracking.lock_version,
            "expected_manifest_sha256": self.MANIFEST_DIGEST,
            "now": self.NOW,
        }

    def test_validator_accepts_hidden_maintenance_and_coarse_restore_states(self):
        decision = race_events.validate_race_live_provisional_rollback_target(
            event_id=self.event.pk,
            now=self.NOW,
            expected_provisional_revision_id=self.provisional.pk,
            planned_policy_snapshot=self._snapshot(),
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
        )
        self.assertTrue(decision.allowed, decision.reason)

        race_events.restore_race_live_provisional_policies(
            event_id=self.event.pk,
            planned_policy_snapshot=self._snapshot(),
            phase="coarse",
            expected_provisional_revision_id=self.provisional.pk,
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
            expected_manifest_sha256=self.MANIFEST_DIGEST,
            now=self.NOW,
        )
        decision = race_events.validate_race_live_provisional_rollback_target(
            event_id=self.event.pk,
            now=self.NOW,
            expected_provisional_revision_id=self.provisional.pk,
            planned_policy_snapshot=self._snapshot(),
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
        )
        self.assertTrue(decision.allowed, decision.reason)
        self.assertEqual(
            self.policies[
                f"event:{self.event.pk}"
            ].__class__.objects.get(pk=self.policies[f"event:{self.event.pk}"].pk).mode,
            models.RaceLivePublicationMode.OFF,
        )

    def test_restore_rebuilds_projection_and_writes_explicit_audit(self):
        decision = race_events.restore_last_provisional_result(
            **self._restore_kwargs()
        )
        self.assertTrue(decision.allowed, decision.reason)
        self.control.refresh_from_db()
        self.tracking.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(
            self.control.current_result_revision_id,
            self.provisional.pk,
        )
        self.assertEqual(
            self.tracking.state,
            models.RaceEventLiveState.PROVISIONAL_RESULT,
        )
        self.assertIsNone(self.event.result_confirmed_at)
        self.assertEqual(
            list(
                models.RaceEventResult.objects.filter(event=self.event)
                .values_list("horse_name", "is_confirmed")
            ),
            [("Rollback Winner", False)],
        )
        audit = models.OperationLog.objects.get(
            action_type="race_live_emergency_provisional_restore"
        )
        self.assertIn(self.MANIFEST_DIGEST, audit.detail)

    def test_manifest_cas_drift_is_zero_write(self):
        before = list(
            models.RaceEventResult.objects.filter(event=self.event)
            .values_list("horse_name", "is_confirmed")
        )
        kwargs = self._restore_kwargs()
        kwargs["expected_allowlist_version"] += 1
        decision = race_events.restore_last_provisional_result(**kwargs)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "provisional_allowlist_version_changed")
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_result_revision_id,
            self.current.pk,
        )
        self.assertEqual(
            list(
                models.RaceEventResult.objects.filter(event=self.event)
                .values_list("horse_name", "is_confirmed")
            ),
            before,
        )
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_emergency_provisional_restore"
            ).exists()
        )

    def test_policy_restore_late_scope_drift_is_zero_write(self):
        snapshot = self._snapshot()
        snapshot[f"event:{self.event.pk}"]["maintenance"]["version"] = 999

        decision = race_events.restore_race_live_provisional_policies(
            event_id=self.event.pk,
            planned_policy_snapshot=snapshot,
            phase="coarse",
            expected_provisional_revision_id=self.provisional.pk,
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
            expected_manifest_sha256=self.MANIFEST_DIGEST,
            now=self.NOW,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            "planned_policy_snapshot_invalid",
        )
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode",
                    "version",
                )
            ),
            {(models.RaceLivePublicationMode.OFF, 10)},
        )
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type=(
                    "race_live_emergency_provisional_policy_restore"
                )
            ).exists()
        )

    def test_policy_restore_rejects_source_official_public_target(self):
        snapshot = self._snapshot()
        snapshot["source:the_racing_api"]["restore"]["mode"] = (
            models.RaceLivePublicationMode.OFFICIAL_PUBLIC
        )

        validation = race_events.validate_race_live_provisional_rollback_target(
            event_id=self.event.pk,
            now=self.NOW,
            expected_provisional_revision_id=self.provisional.pk,
            planned_policy_snapshot=snapshot,
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
        )
        decision = race_events.restore_race_live_provisional_policies(
            event_id=self.event.pk,
            planned_policy_snapshot=snapshot,
            phase="coarse",
            expected_provisional_revision_id=self.provisional.pk,
            expected_allowlist_version=self.allowlist.version,
            expected_publication_id=self.publication.pk,
            expected_manifest_sha256=self.MANIFEST_DIGEST,
            now=self.NOW,
        )

        self.assertFalse(validation.allowed)
        self.assertEqual(validation.reason, "planned_source_policy_mode_invalid")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "planned_source_policy_mode_invalid")
        self.assertEqual(
            set(
                models.RaceLivePublicationPolicy.objects.values_list(
                    "mode",
                    "version",
                )
            ),
            {(models.RaceLivePublicationMode.OFF, 10)},
        )


class RaceLiveOfficialAuthorizationCommandTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="france-official-authorization-command",
            original_name="France Official Authorization Command",
            chinese_name="法国正式赛果授权命令测试",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            race_datetime=datetime(
                2026, 7, 20, 15, 0, tzinfo=dt_timezone.utc
            ),
            timezone_name="Europe/Paris",
        )
        registry, registry_digest = (
            race_live_publication_transition.read_manual_official_route_registry(
                route="france_galop_manual_verification",
                now=datetime(
                    2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc
                ),
            )
        )
        self.registry = registry
        self.registry_digest = registry_digest
        self.coverage_digest = "c" * 64
        models.RaceLiveEventPublicationAllowlist.objects.create(
            event=self.event,
            source_key="the_racing_api",
            max_mode=models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
            coverage_proof_digest=self.coverage_digest,
            official_verification_route=registry["route"],
            official_verification_route_version=registry["parser_version"],
            official_verification_contract_digest=registry["contract_digest"],
            official_terms_evidence_digest=registry["terms_evidence"]["sha256"],
            official_verification_valid_until=datetime(
                2026, 8, 1, tzinfo=dt_timezone.utc
            ),
            enabled=True,
        )

    def _call(self, *extra):
        stdout = StringIO()
        call_command(
            "authorize_race_live_official_publication",
            "--event-id",
            str(self.event.pk),
            "--max-phase",
            "corrected",
            "--valid-until",
            "2026-08-01T00:00:00+00:00",
            "--expected-version",
            "0",
            *extra,
            stdout=stdout,
        )
        return json.loads(stdout.getvalue())

    def test_authorization_command_is_dry_run_by_default_then_cas_applies(self):
        dry_run = self._call()
        self.assertEqual(dry_run["mode"], "dry_run")
        self.assertEqual(dry_run["event_id"], self.event.pk)
        self.assertFalse(
            models.RaceLiveOfficialPublicationAuthorization.objects.exists()
        )

        applied = self._call(
            "--apply",
            "--confirm",
            f"AUTHORIZE_OFFICIAL_EVENT_{self.event.pk}",
        )
        self.assertEqual(applied["mode"], "apply")
        authorization = (
            models.RaceLiveOfficialPublicationAuthorization.objects.get()
        )
        self.assertTrue(authorization.enabled)
        self.assertEqual(authorization.source_key, "france_galop")
        self.assertEqual(
            authorization.route,
            "france_galop_manual_verification",
        )
        self.assertEqual(authorization.max_phase, "corrected")
        self.assertEqual(authorization.version, 1)
        self.assertEqual(
            authorization.coverage_proof_digest,
            self.coverage_digest,
        )

    def test_authorization_command_rejects_wrong_confirmation_without_write(self):
        with self.assertRaises(Exception):
            self._call("--apply", "--confirm", "WRONG")
        self.assertFalse(
            models.RaceLiveOfficialPublicationAuthorization.objects.exists()
        )

    def test_authorization_apply_exact_replay_is_idempotent(self):
        self._call(
            "--apply",
            "--confirm",
            f"AUTHORIZE_OFFICIAL_EVENT_{self.event.pk}",
        )
        stdout = StringIO()
        call_command(
            "authorize_race_live_official_publication",
            "--event-id",
            str(self.event.pk),
            "--max-phase",
            "corrected",
            "--valid-until",
            "2026-08-01T00:00:00+00:00",
            "--expected-version",
            "1",
            "--apply",
            "--confirm",
            f"AUTHORIZE_OFFICIAL_EVENT_{self.event.pk}",
            stdout=stdout,
        )
        replay = json.loads(stdout.getvalue())
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["new_version"], 1)
        self.assertEqual(
            models.RaceLiveOfficialPublicationAuthorization.objects.count(),
            1,
        )
        self.assertEqual(
            models.RaceLiveOfficialPublicationAuthorization.objects.get().version,
            1,
        )

    @override_settings(RACE_LIVE_MONITOR_ENABLED=True)
    def test_authorization_apply_requires_all_background_controls_off(self):
        with self.assertRaises(Exception):
            self._call(
                "--apply",
                "--confirm",
                f"AUTHORIZE_OFFICIAL_EVENT_{self.event.pk}",
            )
        self.assertFalse(
            models.RaceLiveOfficialPublicationAuthorization.objects.exists()
        )

    @override_settings(
        RACE_LIVE_SCHEDULER_ENABLED=False,
        RACE_LIVE_MONITOR_ENABLED=False,
    )
    def test_authorization_apply_rechecks_global_active_claims_in_transaction(self):
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            active_attempt_token="active-claim",
        )
        with self.assertRaises(Exception):
            self._call(
                "--apply",
                "--confirm",
                f"AUTHORIZE_OFFICIAL_EVENT_{self.event.pk}",
            )
        self.assertFalse(
            models.RaceLiveOfficialPublicationAuthorization.objects.exists()
        )


class RaceLiveBroadScopeTransitionCommandTests(TestCase):
    def setUp(self):
        self.policy = models.RaceLivePublicationPolicy.objects.create(
            scope_type=models.RaceLivePublicationScopeType.REGION,
            scope_key=models.RacingRegion.FRANCE,
            mode=models.RaceLivePublicationMode.SHADOW,
            version=1,
            registry_digest="a" * 64,
            coverage_proof_digest="b" * 64,
            valid_until=datetime(
                2026, 8, 1, tzinfo=dt_timezone.utc
            ),
        )

    def _call(self, *extra):
        stdout = StringIO()
        call_command(
            "transition_race_live_publication_scope",
            "--scope-type",
            "region",
            "--scope-key",
            "france",
            "--target-mode",
            "provisional_public",
            "--expected-version",
            "1",
            "--registry-sha256",
            "a" * 64,
            "--coverage-sha256",
            "b" * 64,
            *extra,
            stdout=stdout,
        )
        return json.loads(stdout.getvalue())

    def test_scope_transition_is_dry_run_by_default_then_exact_cas_applies(self):
        self.assertEqual(self._call()["mode"], "dry_run")
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.mode, "shadow")
        self.assertEqual(self.policy.version, 1)

        applied = self._call(
            "--apply",
            "--confirm",
            "TRANSITION_RACE_LIVE_SCOPE_region_france",
        )
        self.assertEqual(applied["mode"], "apply")
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.mode, "provisional_public")
        self.assertEqual(self.policy.version, 2)

    @override_settings(
        RACE_LIVE_SCHEDULER_ENABLED=False,
        RACE_LIVE_MONITOR_ENABLED=True,
    )
    def test_scope_apply_requires_monitor_off(self):
        with self.assertRaises(Exception):
            self._call(
                "--apply",
                "--confirm",
                "TRANSITION_RACE_LIVE_SCOPE_region_france",
            )
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.mode, "shadow")
        self.assertEqual(self.policy.version, 1)

    @override_settings(
        RACE_LIVE_SCHEDULER_ENABLED=False,
        RACE_LIVE_MONITOR_ENABLED=False,
    )
    def test_scope_apply_rechecks_global_active_claims_in_transaction(self):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="active-scope-transition-claim",
            original_name="Active Scope Transition Claim",
            country_region=models.RacingRegion.FRANCE,
        )
        models.RaceEventLiveTracking.objects.create(
            event=event,
            active_attempt_token="active-claim",
        )
        with self.assertRaises(Exception):
            self._call(
                "--apply",
                "--confirm",
                "TRANSITION_RACE_LIVE_SCOPE_region_france",
            )
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.mode, "shadow")
        self.assertEqual(self.policy.version, 1)


class RaceLiveGenericTransitionContractTests(SimpleTestCase):
    def test_event_promotion_never_mutates_broad_publication_scopes(self):
        policies = [
            {
                "scope_type": scope_type,
                "scope_key": scope_key,
                "mode": (
                    models.RaceLivePublicationMode.SHADOW
                    if scope_type
                    == models.RaceLivePublicationScopeType.EVENT
                    else models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                ),
                "version": 7,
            }
            for scope_type, scope_key in (
                (models.RaceLivePublicationScopeType.GLOBAL, "global"),
                (models.RaceLivePublicationScopeType.REGION, "france"),
                (
                    models.RaceLivePublicationScopeType.SOURCE,
                    "the_racing_api",
                ),
                (models.RaceLivePublicationScopeType.EVENT, "123"),
            )
        ]
        snapshot = {
            "policies": policies,
            "allowlist": {
                "version": 1,
                "official_verification_contract_digest": "",
                "official_terms_evidence_digest": "",
            },
            "tracking": {
                "tracking_enabled": True,
                "next_poll_at": "2026-07-20T08:00:00+00:00",
                "provisional_published": False,
            },
            "result_revision": {
                "published": False,
                "participant_count": 2,
            },
            "counts": {
                "publication": 0,
                "legacy_result": 0,
                "incident": 0,
            },
            "event_status": models.RaceEventStatus.SCHEDULED,
            "result_confirmed": False,
        }

        target = race_live_publication_transition._predict_target(
            snapshot,
            transition_name="promote_shadow",
            contract_digest="a" * 64,
            terms_digest="b" * 64,
        )

        by_scope = {
            row["scope_type"]: row for row in target["policies"]
        }
        for broad_scope in (
            models.RaceLivePublicationScopeType.GLOBAL,
            models.RaceLivePublicationScopeType.REGION,
            models.RaceLivePublicationScopeType.SOURCE,
        ):
            self.assertEqual(
                by_scope[broad_scope],
                next(
                    row
                    for row in policies
                    if row["scope_type"] == broad_scope
                ),
            )
        self.assertEqual(
            by_scope[models.RaceLivePublicationScopeType.EVENT]["mode"],
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        )
        self.assertEqual(
            by_scope[models.RaceLivePublicationScopeType.EVENT]["version"],
            8,
        )

    def test_transition_no_longer_hardcodes_event_924_or_single_event_universe(self):
        source = inspect.getsource(race_live_publication_transition)
        forbidden_fragments = (
            "event_id != 924",
            'payload["event_id"] != 924',
            "只允许 event 924",
            "不是精确单赛事",
        )
        violations = [
            fragment for fragment in forbidden_fragments if fragment in source
        ]
        self.assertEqual(violations, [])
        self.assertIn("unrelated_scope_digest", source)

    def test_manual_official_service_is_route_driven_not_bha_event_specific(self):
        source = inspect.getsource(race_live_manual_official_evidence)
        forbidden_fragments = (
            "submission[\"event_id\"] != 924",
            "event_id=924",
            "只允许 event 924",
            "event 924 官方赛果",
        )
        violations = [
            fragment for fragment in forbidden_fragments if fragment in source
        ]
        self.assertEqual(violations, [])
        self.assertIn("official_route", source)

    def test_manual_route_registry_has_the_six_approved_region_routes(self):
        registry_path = (
            REPO_ROOT
            / "runtime"
            / "policies"
            / "race_live"
            / "official_routes_manual_v1.json"
        )
        self.assertTrue(
            registry_path.is_file(),
            "五地区 manual official route registry 尚未实现",
        )
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        routes = payload.get("routes", {})
        self.assertEqual(
            set(routes),
            {
                "bha_manual_verification",
                "france_galop_manual_verification",
                "hkjc_manual_verification",
                "jra_manual_verification",
                "nar_manual_verification",
                "us_official_manual_verification",
            },
        )
        for route, entry in routes.items():
            with self.subTest(route=route):
                self.assertEqual(entry.get("access_mode"), "manual_browser_only")
                self.assertIs(entry.get("automation_allowed"), False)
                self.assertTrue(entry.get("allowed_hosts"))
                self.assertTrue(entry.get("allowed_path_prefixes"))
                permission = dict(entry.get("permission_evidence", {}))
                permission_digest = permission.pop("sha256", "")
                terms = dict(entry.get("terms_evidence", {}))
                terms_digest = terms.pop("sha256", "")
                self.assertEqual(
                    permission.get("basis"),
                    "user_source_use_authorization_2026-07-19",
                )
                self.assertIs(permission.get("manual_access_allowed"), True)
                self.assertIs(permission.get("automation_allowed"), False)
                self.assertEqual(
                    terms.get("basis"),
                    "user_source_use_authorization_2026-07-19",
                )
                self.assertIs(terms.get("manual_access_allowed"), True)
                self.assertIs(terms.get("automation_allowed"), False)
                self.assertTrue(terms.get("observed_at"))
                self.assertTrue(terms.get("valid_until"))
                self.assertEqual(
                    permission_digest,
                    hashlib.sha256(
                        json.dumps(
                            permission,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                )
                self.assertEqual(
                    terms_digest,
                    hashlib.sha256(
                        json.dumps(
                            terms,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                )
                contract = dict(entry)
                contract_digest = contract.pop("contract_digest")
                self.assertEqual(
                    contract_digest,
                    hashlib.sha256(
                        json.dumps(
                            contract,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        ).hexdigest(),
                )
                self.assertNotEqual(terms_digest, contract_digest)
                self.assertNotEqual(permission_digest, contract_digest)

    def test_generic_manual_route_accepts_only_approved_host_and_path_prefix(self):
        registry, registry_digest = (
            race_live_publication_transition.read_manual_official_route_registry(
                route="france_galop_manual_verification",
                now=datetime(
                    2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc
                ),
            )
        )
        registry_file = json.loads(
            (
                REPO_ROOT
                / "runtime"
                / "policies"
                / "race_live"
                / "official_routes_manual_v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            registry_digest,
            hashlib.sha256(
                json.dumps(
                    {
                        "registry_version": registry_file[
                            "registry_version"
                        ],
                        "route": "france_galop_manual_verification",
                        "entry": registry_file["routes"][
                            "france_galop_manual_verification"
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )
        submission = {
            "approved_commit": "a" * 40,
            "event_id": 1,
            "revision_id": 2,
            "incident_id": 3,
            "source_url": (
                "https://www.france-galop.com/en/racing/"
                "detail/2026-07-20"
            ),
            "observed_at": "2026-07-20T08:00:00+00:00",
            "evidence_sha256": "b" * 64,
            "outcome": "available",
            "marker_type": "official_result",
            "participants": [{"participant_id": 4, "position": 1}],
        }

        normalized = (
            race_live_manual_official_evidence._validate_submission(
                submission,
                registry=registry,
                registry_digest=registry_digest,
            )
        )
        self.assertEqual(normalized["source_url"], submission["source_url"])

        for rejected_url in (
            "https://example.com/en/racing/detail/2026-07-20",
            "https://www.france-galop.com/press/detail/2026-07-20",
            "http://www.france-galop.com/en/racing/detail/2026-07-20",
        ):
            with self.subTest(source_url=rejected_url):
                invalid = {**submission, "source_url": rejected_url}
                with self.assertRaises(
                    race_live_manual_official_evidence.RaceLiveManualOfficialEvidenceError
                ):
                    race_live_manual_official_evidence._validate_submission(
                        invalid,
                        registry=registry,
                        registry_digest=registry_digest,
                    )
