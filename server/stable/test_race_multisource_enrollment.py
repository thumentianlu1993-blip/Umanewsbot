from stable import test_race_multisource_identity as fixtures
from datetime import timedelta
from unittest.mock import patch
from django.db import transaction
from django.test import override_settings, TestCase
from stable import models
from stable.test_race_multisource_identity import (
    NOW,
    observation,
    policy_payload,
)
from stable.services.race_data_source_adapters import parse_multisource_policy
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import (
    claim_due_enrollments,
    lock_and_validate_race_data_sync_claim_for_apply,
)


@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra", "alternate"),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
)
class MultisourceClaimTests(TestCase):
    def setUp(self):
        fixtures.IdentityTests.setUp(self)
        fixtures.IdentityTests.anchor(self)
        payload = policy_payload()
        payload["routes"] += policy_payload("alternate")["routes"]
        self.policy = parse_multisource_policy(payload, now=NOW)
        self.loader = patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=self.policy,
        )
        self.loader.start()
        self.addCleanup(self.loader.stop)
        attach_multisource_observation(observation(), policy=self.policy, now=NOW)

    # Inherited identity tests use a different fixture; only execute the contract methods here.
    def claim(self):
        return claim_due_enrollments(
            now=NOW,
            batch_size=20,
            ttl_seconds=240,
            enabled_providers=("jra", "alternate"),
            enabled_regions=("japan_jra",),
            enabled_data_kinds=("result",),
        )

    def test_single_claim_and_attach_invalidates_old_worker(self):
        claims = self.claim()
        self.assertEqual(len(claims), 1)
        self.assertEqual(len(self.claim()), 0)
        self.assertEqual(
            attach_multisource_observation(
                observation("alternate"), policy=self.policy, now=NOW
            ).action,
            "attached",
        )
        with transaction.atomic():
            result, locked = lock_and_validate_race_data_sync_claim_for_apply(
                claim=claims[0], now=NOW
            )
        self.assertIsNone(locked)
        self.assertIn(result.reason_code, ("claim_cas_stale", "claim_plan_drift"))

    def test_claim_contains_exact_binding_authority(self):
        claim = self.claim()[0]
        authority = claim.checkpoint_plan[0]["authority"]
        self.assertEqual(authority["authority_version"], 2)
        self.assertEqual(authority["source_set_generation"], 1)
        with transaction.atomic():
            result, locked = lock_and_validate_race_data_sync_claim_for_apply(
                claim=claim, now=NOW
            )
        self.assertEqual(result.action, "valid")
        self.assertIsNotNone(locked)

    def test_lifecycle_switch_closes_existing_enforce(self):
        from stable.services.race_data_sync_admission import (
            validate_data_sync_lifecycle_admission,
        )

        with override_settings(RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=False):
            self.assertFalse(
                validate_data_sync_lifecycle_admission(
                    event_id=self.event.pk, now=NOW
                ).admitted
            )

    def test_disabled_source_attach_is_zero_write(self):
        before = models.RaceResultSourceIdentity.objects.count()
        with override_settings(RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra",)):
            self.assertEqual(
                attach_multisource_observation(
                    observation("alternate"), policy=self.policy, now=NOW
                ).reason_code,
                "binding_runtime_disabled",
            )
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), before)

    def test_unselected_checkpoint_does_not_leave_parent_due(self):
        from stable.services.race_data_sync_control import finish_multisource_claim

        attach_multisource_observation(
            observation("alternate"), policy=self.policy, now=NOW
        )
        claim = self.claim()[0]
        self.assertEqual(
            finish_multisource_claim(claim=claim, now=NOW, success=True).action,
            "complete",
        )
        track = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertGreater(track.next_poll_at, NOW)

    def test_result_timeout_fallback_is_authorized_then_sticky(self):
        from stable.services.race_data_sync_control import finish_multisource_claim

        attach_multisource_observation(
            observation("alternate"), policy=self.policy, now=NOW
        )
        claim = self.claim()[0]
        finish_multisource_claim(
            claim=claim, now=NOW, success=False, reason_code="http_403"
        )
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        alternate = enrollment.source_set_manifest["alternate"]["result"]["binding_id"]
        next_claim = self.claim()[0]
        self.assertEqual(
            next_claim.checkpoint_plan[0]["authority"]["binding_id"], alternate
        )
        finish_multisource_claim(claim=next_claim, now=NOW, success=True)
        enrollment.refresh_from_db()
        self.assertEqual(
            enrollment.source_set_manifest["selected"]["result"], alternate
        )

    def test_partial_result_can_switch_to_authorized_alternate(self):
        from stable.services.race_data_sync_control import finish_multisource_claim
        attach_multisource_observation(observation("alternate"), policy=self.policy, now=NOW)
        claim = self.claim()[0]
        finish_multisource_claim(claim=claim, now=NOW, success=False, reason_code="result_incomplete")
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        alternate = enrollment.source_set_manifest["alternate"]["result"]["binding_id"]
        next_claim = self.claim()[0]
        self.assertEqual(next_claim.checkpoint_plan[0]["authority"]["binding_id"], alternate)

    def test_date_only_result_polls_without_fabricated_time(self):
        from stable.services.race_data_sync_control import (
            calculate_multisource_next_poll,
        )

        self.assertEqual(
            calculate_multisource_next_poll(event=self.event, kind="result", now=NOW),
            NOW + timedelta(minutes=30),
        )
        later = NOW + timedelta(days=1)
        self.assertEqual(
            calculate_multisource_next_poll(event=self.event, kind="result", now=later),
            later + timedelta(hours=6),
        )
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)

    def test_blocked_source_is_not_reselected_after_attach(self):
        source = models.RaceResultSourceIdentity.objects.get(source_key="jra")
        source.terms_status = "blocked"
        source.save(update_fields=("terms_status",))
        decision = attach_multisource_observation(
            observation("alternate"), policy=self.policy, now=NOW
        )
        self.assertEqual(decision.action, "attached", decision)
        claim = self.claim()[0]
        self.assertEqual(claim.checkpoint_plan[0]["source_key"], "alternate")


    def test_legacy_rotation_cannot_replace_multisource_authority(self):
        from stable.services.race_data_sync_control import rotate_enrollment
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        before = models.RaceDataSyncEnrollment.objects.values().get(pk=enrollment.pk)
        decision = rotate_enrollment(
            event_id=self.event.pk, source_identity_id=enrollment.source_identity_id,
            standing_policy_digest="c"*64, route_digest="d"*64,
            event_snapshot_sha256="e"*64, successor_manifest_sha256="f"*64,
            successor_entry_sha256="a"*64,
            expected_manifest_sha256=enrollment.manifest_sha256,
            expected_owner_generation=enrollment.projection_owner_generation,
            data_kinds=("result",), now=NOW)
        self.assertEqual(decision.reason_code, "multisource_claim_required")
        self.assertEqual(models.RaceDataSyncEnrollment.objects.values().get(pk=enrollment.pk), before)

    def _legacy_overwrite(self, *, rotate=False):
        from types import SimpleNamespace
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        if rotate:
            from stable.services.race_data_sync_control import rotate_enrollment
            # 仅关闭新增v2入口guard，运行真实旧轮转的全部写入逻辑。
            enrollment.authority_version = 1
            enrollment.save()
            route_binding = SimpleNamespace(contract_digest="a"*64, registry_digest="b"*64)
            mock=patch('stable.services.race_data_sync_control.resolve_source_route_admission', return_value=("",route_binding))
            mock.start();self.addCleanup(mock.stop)
            decision=rotate_enrollment(event_id=self.event.pk,source_identity_id=enrollment.source_identity_id,
                standing_policy_digest="c"*64,route_digest=enrollment.route_digest,
                event_snapshot_sha256="d"*64,successor_manifest_sha256="e"*64,successor_entry_sha256="f"*64,
                expected_manifest_sha256=enrollment.manifest_sha256,
                expected_owner_generation=enrollment.projection_owner_generation,data_kinds=("result",),now=NOW)
            self.assertEqual(decision.action,'rotated',decision)
            enrollment.refresh_from_db();enrollment.authority_version=2;enrollment.save()
        else:
            enrollment.standing_policy_digest = "c"*64
            enrollment.save()
        control = models.RaceEventLifecycleControl.objects.get(event=self.event)
        control.manifest_data['race_data_sync']['standing_policy_digest'] = "c"*64
        control.save()
        models.RaceEventLiveTracking.objects.filter(event=self.event).update(next_poll_at=None)
        models.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event=self.event).update(next_poll_at=None)
        source = enrollment.source_identity
        legacy = SimpleNamespace(digest="c"*64, valid_from=NOW-timedelta(days=1), valid_until=NOW+timedelta(days=1),
            routes=[SimpleNamespace(enrollment_eligible=True, country_region=self.event.country_region,
                provider=source.source_key, region_code=source.region_code,
                identity_namespace=source.identity_namespace, route_digest=enrollment.route_digest)])
        for target, value in [('load_standing_policy_file', {}), ('parse_standing_policy', legacy)]:
            mock=patch('stable.services.race_data_sync_enrollment.'+target, return_value=value)
            mock.start();self.addCleanup(mock.stop)

    @override_settings(RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=True)
    def test_discovery_recovers_proven_legacy_overwrite_without_network(self):
        from stable.services.race_data_sync_enrollment import discover_multisource_events, recover_legacy_rotated_multisource
        from stable.services.race_data_sync_admission import validate_multisource_admission
        self._legacy_overwrite()
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation', side_effect=AssertionError('recovery must not fetch')):
            outcome = discover_multisource_events(now=NOW, policy=self.policy)
        admission = validate_multisource_admission(event_id=self.event.pk, now=NOW, policy=self.policy)
        self.assertTrue(admission.admitted, outcome)
        self.assertEqual(recover_legacy_rotated_multisource(event_id=self.event.pk, policy=self.policy, now=NOW).action, 'unchanged')
        self.assertEqual(models.OperationLog.objects.filter(action_type='multisource_auto_recovery').count(),1)
        self.assertEqual(len(self.claim()), 1)

    def test_recovery_restores_real_legacy_rotation_generations_and_checkpoint(self):
        from stable.services.race_data_sync_enrollment import recover_legacy_rotated_multisource
        self._legacy_overwrite(rotate=True)
        decision=recover_legacy_rotated_multisource(event_id=self.event.pk,policy=self.policy,now=NOW)
        self.assertEqual(decision.action,'recovered',decision)
        self.assertEqual(len(self.claim()),1)
        enrollment=models.RaceDataSyncEnrollment.objects.get(event=self.event)
        self.assertEqual(enrollment.source_set_manifest['owner_generation'],enrollment.projection_owner_generation)

    def test_recovery_restores_alternate_or_returns_to_selected_after_expiry(self):
        from datetime import datetime
        from stable.services.race_data_sync_control import finish_multisource_claim
        from stable.services.race_data_sync_enrollment import recover_legacy_rotated_multisource
        attach_multisource_observation(observation('alternate'),policy=self.policy,now=NOW)
        finish_multisource_claim(claim=self.claim()[0],now=NOW,success=False,reason_code='http_403')
        enrollment=models.RaceDataSyncEnrollment.objects.get(event=self.event)
        expires=datetime.fromisoformat(enrollment.source_set_manifest['alternate']['result']['expires_at'])
        self._legacy_overwrite(rotate=True)
        for expired in [False, True]:
            with self.subTest(expired=expired),transaction.atomic():
                now=expires+timedelta(seconds=1) if expired else NOW
                decision=recover_legacy_rotated_multisource(event_id=self.event.pk,policy=self.policy,now=now)
                self.assertEqual(decision.action,'recovered',decision)
                claims=claim_due_enrollments(now=now,batch_size=20,ttl_seconds=240,
                    enabled_providers=('jra','alternate'),enabled_regions=('japan_jra',),enabled_data_kinds=('result',))
                self.assertEqual(len(claims),1)
                self.assertEqual(claims[0].checkpoint_plan[0]['source_key'],'jra' if expired else 'alternate')
                transaction.set_rollback(True)

    @override_settings(RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=True)
    def test_rejected_recovery_respects_discovery_due_and_persists_backoff(self):
        from stable.services.race_data_sync_enrollment import discover_multisource_events
        self._legacy_overwrite()
        models.RaceDataSyncSourceBinding.objects.filter(enrollment__event=self.event).update(valid_until=NOW-timedelta(seconds=1))
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation',side_effect=AssertionError('must not fetch')):
            first=discover_multisource_events(now=NOW,policy=self.policy)
            second=discover_multisource_events(now=NOW,policy=self.policy)
        self.assertEqual(first['attempted'],1)
        self.assertEqual(second['attempted'],0)
        self.event.refresh_from_db()
        self.assertGreater(self.event.source_refs['source_discovery_v2']['next_poll_at'],NOW.isoformat())

    def test_recovery_refuses_unknown_drift_manual_pause_and_live_claim(self):
        from stable.services.race_data_sync_enrollment import recover_legacy_rotated_multisource
        self._legacy_overwrite()
        for fault in ['manifest', 'generation', 'manual', 'claim', 'checkpoint', 'expired']:
            with self.subTest(fault=fault), transaction.atomic():
                if fault == 'manifest':
                    enrollment=models.RaceDataSyncEnrollment.objects.get(event=self.event)
                    enrollment.source_set_manifest['policy_digest']='f'*64;enrollment.save()
                elif fault == 'generation':
                    models.RaceEventProjectionControl.objects.filter(event=self.event).update(owner_generation=4)
                elif fault == 'manual':
                    models.RaceEventLifecycleControl.objects.filter(event=self.event).update(manual_pause_reason='operator')
                elif fault == 'claim':
                    models.RaceEventLiveTracking.objects.filter(event=self.event).update(active_attempt_token='worker',claim_expires_at=NOW+timedelta(minutes=2))
                elif fault == 'checkpoint':
                    models.RaceEventLiveProviderCheckpoint.objects.filter(tracking__event=self.event).update(contract_digest='f'*64)
                else:
                    models.RaceDataSyncSourceBinding.objects.filter(enrollment__event=self.event).update(valid_until=NOW-timedelta(seconds=1))
                before=list(models.RaceDataSyncEnrollment.objects.values())
                decision=recover_legacy_rotated_multisource(event_id=self.event.pk,policy=self.policy,now=NOW)
                self.assertEqual(decision.action,'rejected',decision)
                self.assertEqual(list(models.RaceDataSyncEnrollment.objects.values()),before)
                self.assertFalse(models.OperationLog.objects.filter(action_type='multisource_auto_recovery').exists())
                transaction.set_rollback(True)


@override_settings(
    RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
)
class MultisourcePolicyIncidentTests(TestCase):
    """policy 失效只记录 record-only 内部 incident；登记行为 fail-closed 不变。"""

    def discover(self, at, **kwargs):
        from stable.services.race_data_sync_enrollment import (
            discover_multisource_events,
        )

        return discover_multisource_events(now=at, **kwargs)

    def unavailable(self):
        return patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            side_effect=ValueError("multisource_policy_expired"),
        )

    def test_policy_unavailable_stages_internal_incident(self):
        with self.unavailable():
            result = self.discover(NOW)
        self.assertEqual(
            result, {"enabled": True, "reason": "multisource_policy_unavailable"}
        )
        incident = models.RaceLiveAlertIncident.objects.get()
        self.assertEqual(incident.scope_type, "multisource_policy")
        self.assertEqual(incident.status, "open")
        self.assertIsNone(incident.next_attempt_at)
        self.assertEqual(incident.delivery_attempts, 0)
        self.assertEqual(
            incident.details["issue"], "multisource_policy_unavailable"
        )
        self.assertEqual(incident.details["reason"], "multisource_policy_expired")
        # 持续失败不重复建行，只推进 last_seen 与最新原因。
        later = NOW + timedelta(minutes=10)
        with patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            side_effect=ValueError("multisource_policy_sha_mismatch"),
        ):
            self.assertEqual(
                self.discover(later)["reason"], "multisource_policy_unavailable"
            )
        self.assertEqual(models.RaceLiveAlertIncident.objects.count(), 1)
        incident.refresh_from_db()
        self.assertEqual(incident.status, "open")
        self.assertEqual(incident.last_seen_at, later)
        self.assertEqual(incident.details["reason"], "multisource_policy_sha_mismatch")

    def test_policy_incident_resolves_on_recovery_and_reopens_on_refailure(self):
        with self.unavailable():
            self.discover(NOW)
        incident = models.RaceLiveAlertIncident.objects.get()
        policy = parse_multisource_policy(policy_payload(), now=NOW)
        recovered = NOW + timedelta(minutes=20)
        result = self.discover(recovered, policy=policy)
        self.assertTrue(result["enabled"])
        incident.refresh_from_db()
        self.assertEqual(incident.status, "resolved")
        self.assertEqual(incident.resolved_at, recovered)
        # 恢复后再次失效：同一条 incident 重新打开，不另起新行。
        refailed = NOW + timedelta(minutes=30)
        with self.unavailable():
            self.discover(refailed)
        incident.refresh_from_db()
        self.assertEqual(incident.status, "open")
        self.assertEqual(incident.opened_at, refailed)
        self.assertIsNone(incident.resolved_at)
        self.assertEqual(models.RaceLiveAlertIncident.objects.count(), 1)
