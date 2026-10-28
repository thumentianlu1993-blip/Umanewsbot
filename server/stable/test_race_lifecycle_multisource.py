"""本地 JRA 原始样本走生产 writer；网络与容量证据均为隔离测试替身。"""
from unittest.mock import patch
from django.test import TestCase, override_settings
from stable import models, test_race_multisource_jra as fixtures
from stable.services.race_data_source_adapters import run_multisource_claim
from stable.services.race_data_sync_control import claim_due_enrollments
from stable.services.race_events import resolve_race_live_public_read


@override_settings(**fixtures.JraColdStartTests._overridden_settings)
@override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True)
class LifecycleMultisourceTests(TestCase):
    fetch = fixtures.JraColdStartTests.fetch
    enroll = fixtures.JraColdStartTests.enroll
    claim = fixtures.JraColdStartTests.claim

    def setUp(self):
        fixtures.JraColdStartTests.setUp(self)
        self.enroll()
        config = override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,))
        config.enable()
        self.addCleanup(config.disable)

    def test_no_capacity_proof_means_no_new_request(self):
        claims = claim_due_enrollments(now=fixtures.NOW, batch_size=20, ttl_seconds=240,
            enabled_providers=('jra',), enabled_regions=('japan_jra',), enabled_data_kinds=('result',))
        self.assertEqual(claims, ())
        self.assertFalse(models.RaceLifecyclePublicState.objects.exists())

    def test_saved_jra_result_reaches_epoch_reader_and_delivery(self):
        with patch('stable.services.race_lifecycle_projection.capacity_manifest', return_value=dict(targets=[dict(key=f'canonical:{self.event.pk}', region='japan_jra', key_race=True)], proofs=[dict(region='japan_jra', provider='jra', host='www.jra.go.jp', runtime_verified=True, identity=True, confirmed_card=True, complete_result=True, correction=True, evidence_refs=['synthetic'], discovery='full', requests_per_fetch=2)], budgets={'www.jra.go.jp': 1000})):
            outcome = run_multisource_claim(claim=self.claim(), now=fixtures.NOW, fetcher=self.fetch)
        self.assertTrue(outcome['processed'], outcome)
        state = models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual(state.result_maturity, 'confirmed')
        self.assertTrue(resolve_race_live_public_read(event_id=self.event.pk, now=fixtures.NOW).visible)
        self.assertEqual(models.RaceLifecycleDelivery.objects.count(), 2)
        from stable.services.race_lifecycle_projection import public_modules
        self.assertEqual(len(public_modules(self.event.pk, now=fixtures.NOW)['result']), 13)

    def test_expired_capacity_between_claim_and_fetch_blocks_network(self):
        manifest = dict(targets=[dict(key=f'canonical:{self.event.pk}', region='japan_jra', key_race=True)],
            proofs=[dict(region='japan_jra', provider='jra', host='www.jra.go.jp', runtime_verified=True, identity=True,
                confirmed_card=True, complete_result=True, correction=True, evidence_refs=['synthetic'], discovery='full', requests_per_fetch=2)],
            budgets={'www.jra.go.jp':1000})
        with patch('stable.services.race_lifecycle_projection.capacity_manifest', return_value=manifest):
            claim = self.claim()
        from unittest.mock import Mock
        fetcher = Mock(side_effect=self.fetch)
        with patch('stable.services.race_lifecycle_projection.capacity_manifest', side_effect=ValueError('capacity_manifest_expired')):
            outcome = run_multisource_claim(claim=claim, now=fixtures.NOW, fetcher=fetcher)
        self.assertFalse(outcome['processed'])
        fetcher.assert_not_called()


@override_settings(**fixtures.JraColdStartTests._overridden_settings)
@override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True, RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
                   RACE_DATA_SYNC_ENABLED_DATA_KINDS=('racecard',))
class LifecycleJraCardTests(TestCase):
    fetch = fixtures.JraColdStartTests.fetch

    def test_explicit_final_card_maturity_flows_from_parser_to_public_state(self):
        from stable.services.race_data_source_adapters import parse_multisource_policy, fetch_bound_observation
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS
        fixtures.JraColdStartTests.setUp(self)
        policy = parse_multisource_policy(fixtures.policy_payload(kinds=('racecard',)), now=fixtures.NOW)
        with patch('stable.services.race_data_source_adapters.load_multisource_policy', return_value=policy), \
             override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,), RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_ROSTER_ALLOWED_FIELDS), RACE_DATA_SYNC_ENABLED_DATA_KINDS=("racecard",)):
            value = fetch_bound_observation(event=self.event, route=policy.routes[0], now=fixtures.NOW, fetcher=self.fetch, kind='racecard')
            self.assertEqual(value.get('declaration_status'), 'confirmed', '明确出馬表语义未由 producer 保存')
            decision = attach_multisource_observation(value, policy=policy, now=fixtures.NOW)
            self.assertEqual(decision.action, 'acquired', decision)
            from stable.services.race_data_sync_admission import validate_multisource_admission
            admission = validate_multisource_admission(event_id=self.event.pk, now=fixtures.NOW, capability='racecard', policy=policy)
            self.assertTrue(admission.admitted, admission.reason_code)
            with patch('stable.services.race_lifecycle_projection.capacity_manifest', return_value=dict(targets=[dict(key=f'canonical:{self.event.pk}', region='japan_jra', key_race=True)], proofs=[dict(region='japan_jra', provider='jra', host='www.jra.go.jp', runtime_verified=True, identity=True, confirmed_card=True, complete_result=True, correction=True, evidence_refs=['synthetic'], discovery='full', requests_per_fetch=2)], budgets={'www.jra.go.jp': 1000})):
                claims = claim_due_enrollments(now=fixtures.NOW, batch_size=20, ttl_seconds=240,
                    enabled_providers=('jra',), enabled_regions=('japan_jra',), enabled_data_kinds=('racecard',))
                self.assertTrue(claims, list(models.RaceEventLiveProviderCheckpoint.objects.values('next_poll_at', 'data_kind', 'circuit_reason')))
                result = run_multisource_claim(claim=claims[0], now=fixtures.NOW, fetcher=self.fetch)
            self.assertTrue(result['processed'], result)
            state = models.RaceLifecyclePublicState.objects.get(event=self.event)
            self.assertEqual(state.racecard_maturity, 'confirmed')
            self.assertIsNone(state.racecard_deadline_at)

    # 此类仅验证名单 producer；来源容量绑定另由结果入口测试。


@override_settings(**fixtures.JraColdStartTests._overridden_settings)
@override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True)
class LifecycleSourceEvidenceTests(TestCase):
    setUp=fixtures.JraColdStartTests.setUp
    fetch=fixtures.JraColdStartTests.fetch
    enroll=fixtures.JraColdStartTests.enroll
    claim=fixtures.JraColdStartTests.claim

    def capacity(self):
        return dict(targets=[dict(key=f'canonical:{self.event.pk}',region='japan_jra',key_race=True)],
            proofs=[dict(region='japan_jra',provider=p,host='www.jra.go.jp',runtime_verified=True,identity=True,
                confirmed_card=True,complete_result=True,correction=True,evidence_refs=['synthetic'],discovery='full',requests_per_fetch=2)
                for p in ('jra','alternate')],budgets={'www.jra.go.jp':1000})

    def test_identical_cross_language_result_remains_visible(self):
        with override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,)), patch(
                'stable.services.race_lifecycle_projection.capacity_manifest',return_value=self.capacity()):
            fixtures.JraColdStartTests.test_same_result_crosslanguage_alternate(self)
            from datetime import timedelta
            with patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=self.policy), override_settings(RACE_DATA_SYNC_ENABLED_PROVIDERS=('jra','alternate')):
                self.assertTrue(resolve_race_live_public_read(event_id=self.event.pk,now=fixtures.NOW+timedelta(hours=6,minutes=1)).visible)

    def test_real_producer_republishes_a_b_a_without_payload_metadata_changes(self):
        from copy import deepcopy
        from datetime import timedelta
        from stable.services.race_data_source_adapters import fetch_bound_observation
        self.enroll()
        base=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=fixtures.NOW,fetcher=self.fetch)
        base['result_phase']='corrected'
        revisions=[]
        with override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,)), patch(
                'stable.services.race_lifecycle_projection.capacity_manifest',return_value=self.capacity()):
            for i in range(3):
                at=fixtures.NOW+timedelta(minutes=2*i)
                value=deepcopy(base);value['fetched_at']=at.isoformat()
                if i==1:
                    value['roster'][0]['reported_finish_position'],value['roster'][1]['reported_finish_position']=value['roster'][1]['reported_finish_position'],value['roster'][0]['reported_finish_position']
                with patch('django.utils.timezone.now',return_value=at),patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
                    claim=claim_due_enrollments(now=at,batch_size=20,ttl_seconds=240,enabled_providers=('jra',),enabled_regions=('japan_jra',),enabled_data_kinds=('result',))[0]
                    result=run_multisource_claim(claim=claim,now=at,fetcher=self.fetch)
                self.assertTrue(result['processed'],result)
                state=models.RaceLifecyclePublicState.objects.get(event=self.event)
                self.assertEqual(state.epoch,i+1)
                revisions.append(state.result_revision_id)
        self.assertEqual(revisions[0],revisions[2])
        self.assertNotEqual(revisions[0],revisions[1])

    def _publish_then_candidate(self, *, conflict=False, phase='corrected', offset=4, changed=False, initial_phase='corrected'):
        from copy import deepcopy
        from datetime import timedelta
        from stable.services import race_events
        from stable.services.race_data_source_adapters import fetch_bound_observation, canonical_sha
        self.enroll()
        value=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=fixtures.NOW,fetcher=self.fetch)
        value['result_phase']=initial_phase
        config=override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,))
        config.enable();self.addCleanup(config.disable)
        capacity=patch('stable.services.race_lifecycle_projection.capacity_manifest',return_value=self.capacity())
        capacity.start();self.addCleanup(capacity.stop)
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
            self.assertTrue(run_multisource_claim(claim=self.claim(),now=fixtures.NOW,fetcher=self.fetch)['processed'])
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        original=models.RaceResultObservation.objects.get(pk=state.result_evidence['observation_id'])
        if conflict:
            value=deepcopy(value);value['result_phase']='official'
            value['roster'][0]['reported_finish_position'],value['roster'][1]['reported_finish_position']=value['roster'][1]['reported_finish_position'],value['roster'][0]['reported_finish_position']
            at=fixtures.NOW+timedelta(minutes=2)
            with patch('django.utils.timezone.now',return_value=at),patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
                claim=self._claim_at(at)
                run_multisource_claim(claim=claim,now=at,fetcher=self.fetch)
            state.refresh_from_db();self.assertEqual(state.result_visibility,'verifying')
        payload=deepcopy(original.normalized_payload)
        if changed:
            rows=payload['participants'];rows[0]['reported_finish_position'],rows[1]['reported_finish_position']=rows[1]['reported_finish_position'],rows[0]['reported_finish_position']
        if phase=='provisional':payload['race_status']='pending'
        provenance=dict(original.field_provenance,correction_marker=phase=='corrected')
        candidate=race_events.record_race_result_observation(source_identity_id=original.source_identity_id,
            observed_at=fixtures.NOW+timedelta(minutes=offset),source_updated_at=None,
            parser_version=original.parser_version,raw_sha256=canonical_sha(payload),result_phase=phase,
            normalized_payload=payload,field_provenance=provenance,parse_warnings=[],
            permission_classification='synthetic',acquisition_key=canonical_sha([phase,offset,changed])).observation
        return original,candidate,state.epoch

    def _claim_at(self, at):
        return claim_due_enrollments(now=at,batch_size=20,ttl_seconds=240,enabled_providers=('jra',),
            enabled_regions=('japan_jra',),enabled_data_kinds=('result',))[0]

    def _apply_candidate(self, observation, *, enabled=True):
        from datetime import timedelta
        from stable.services.race_data_sync_results import apply_data_sync_result_observation
        at=fixtures.NOW+timedelta(minutes=30)
        return apply_data_sync_result_observation(observation_id=observation.pk,expected_event_id=self.event.pk,
            now=at,project_current=True,correction_apply_enabled=enabled,claim_guard=self._claim_at(at))

    def test_old_corrected_replay_does_not_clear_newer_conflict(self):
        original,_,epoch=self._publish_then_candidate(conflict=True)
        self._apply_candidate(original)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_visibility),(epoch,'verifying'))

    def test_disabled_correction_does_not_clear_same_facts_conflict(self):
        _,candidate,epoch=self._publish_then_candidate(conflict=True)
        self._apply_candidate(candidate,enabled=False)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_visibility),(epoch,'verifying'))

    def test_correction_older_than_conflict_does_not_restore_visibility(self):
        _,candidate,epoch=self._publish_then_candidate(conflict=True,offset=1)
        self._apply_candidate(candidate)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_visibility),(epoch,'verifying'))

    def test_same_facts_provisional_cannot_downgrade_confirmed_result(self):
        _,candidate,epoch=self._publish_then_candidate(phase='provisional')
        self._apply_candidate(candidate)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_maturity,state.result_visibility),(epoch,'corrected','visible'))

    def test_older_different_result_cannot_hide_current_result(self):
        _,candidate,epoch=self._publish_then_candidate(phase='official',offset=-1,changed=True)
        self._apply_candidate(candidate)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_visibility),(epoch,'visible'))

    def test_older_conflict_cannot_replace_newer_conflict_watermark(self):
        _,candidate,epoch=self._publish_then_candidate(conflict=True,phase='official',offset=1,changed=True)
        self._apply_candidate(candidate)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_visibility),(epoch,'verifying'))

    def test_fresh_enabled_correction_restores_same_facts_conflict(self):
        _,candidate,epoch=self._publish_then_candidate(conflict=True)
        self._apply_candidate(candidate)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_visibility),(epoch+1,'visible'))

    def test_disabled_same_content_correction_cannot_change_maturity(self):
        _,candidate,epoch=self._publish_then_candidate(initial_phase='official')
        self._apply_candidate(candidate,enabled=False)
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch,state.result_maturity),(epoch,'confirmed'))


@override_settings(**fixtures.JraColdStartTests._overridden_settings)
@override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True,RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
                   RACE_DATA_SYNC_ENABLED_PROVIDERS=('jra','alternate'),RACE_DATA_SYNC_ENABLED_DATA_KINDS=('racecard',))
class LifecycleCrossLanguageCardTests(TestCase):
    setUp=fixtures.JraColdStartTests.setUp
    fetch=fixtures.JraColdStartTests.fetch
    capacity=LifecycleSourceEvidenceTests.capacity

    def _check_translated_card(self, *, verified=True, changed=False, renumber=False, marker=False, locked=False):
        from datetime import timedelta
        from stable.services.race_data_source_adapters import parse_multisource_policy,fetch_bound_observation
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS
        from stable.services.race_data_sync_control import finish_multisource_claim
        payload=fixtures.policy_payload(kinds=('racecard',))
        payload['routes']+=fixtures.policy_payload('alternate',kinds=('racecard',))['routes']
        self.policy=parse_multisource_policy(payload,now=fixtures.NOW)
        with override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,),RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_ROSTER_ALLOWED_FIELDS),
                RACE_DATA_SYNC_ENABLED_DATA_KINDS=('racecard',),RACE_DATA_SYNC_ENABLED_PROVIDERS=('jra','alternate')),patch(
                'stable.services.race_data_source_adapters.load_multisource_policy',return_value=self.policy),patch(
                'stable.services.race_lifecycle_projection.capacity_manifest',return_value=self.capacity()):
            value=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=fixtures.NOW,fetcher=self.fetch,kind='racecard')
            self.assertEqual(attach_multisource_observation(value,policy=self.policy,now=fixtures.NOW).action,'acquired')
            def claim(at):
                return claim_due_enrollments(now=at,batch_size=20,ttl_seconds=240,enabled_providers=('jra','alternate'),
                    enabled_regions=('japan_jra',),enabled_data_kinds=('racecard',))[0]
            self.assertTrue(run_multisource_claim(claim=claim(fixtures.NOW),now=fixtures.NOW,fetcher=self.fetch)['processed'])
            state=models.RaceLifecyclePublicState.objects.get(event=self.event)
            value.update(provider='alternate',identity_namespace='alternate-race-v1')
            for row in value['roster']:
                row.update(external_runner_id='alt:'+row['number'],horse_name='English Horse '+row['number'],
                           jockey_name='English Rider '+row['number'],trainer_name='English Trainer '+row['number'])
            self.assertEqual(attach_multisource_observation(value,policy=self.policy,now=fixtures.NOW).action,'attached')
            source=models.RaceResultSourceIdentity.objects.get(event=self.event,source_key='alternate')
            if verified:
                for item in state.racecard_revision.items.all():
                    models.RaceEventParticipantSourceIdentity.objects.create(source_identity=source,
                        external_runner_id='alt:'+item.horse_number,participant=item.participant)
            original_number=value['roster'][0]['number']
            if changed:
                value['roster'][0]['carried_weight']='99'
            if renumber:
                value['roster'][0]['number']='99'
            if marker:
                value['card_correction_marker']=True
            if locked:
                runner=models.RaceEventRunner.objects.get(event=self.event,horse_number=original_number)
                runner.manual_lock_flags={'horse_number':True};runner.save()
            later=fixtures.NOW+timedelta(hours=6,minutes=1)
            value['fetched_at']=later.isoformat()
            with patch('django.utils.timezone.now',return_value=later):
                first=claim(later);self.assertEqual(first.checkpoint_plan[0]['source_key'],'jra')
                finish_multisource_claim(claim=first,now=later,success=False,reason_code='http_403')
                alternate=claim(later);self.assertEqual(alternate.checkpoint_plan[0]['source_key'],'alternate')
                with patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
                    outcome=run_multisource_claim(claim=alternate,now=later,fetcher=self.fetch)
            state.refresh_from_db()
            conflict=(changed or renumber) and verified and not marker
            self.assertEqual(state.racecard_visibility,'verifying' if conflict else 'visible',outcome)
            self.assertEqual(outcome['processed'],verified and not conflict,outcome)
            from stable.services.race_lifecycle_projection import public_modules
            modules=public_modules(self.event.pk,now=later)
            self.assertEqual(modules['visibility']['racecard'],'verifying' if conflict else 'visible')
            if renumber and marker and verified:
                numbers=[row.horse_number for row in modules['racecard']]
                self.assertIn(original_number if locked else '99',numbers)
                self.assertNotIn('99' if locked else original_number,numbers)

    def test_reviewed_translated_card_is_not_a_source_conflict(self):
        self._check_translated_card()

    def test_reviewed_card_still_hides_real_weight_conflict(self):
        self._check_translated_card(changed=True)

    def test_unverified_translated_card_is_rejected_without_hiding_approved_card(self):
        self._check_translated_card(verified=False)

    def test_explicit_cross_source_number_correction_reaches_public_revision(self):
        self._check_translated_card(renumber=True,marker=True)

    def test_unmarked_cross_source_number_change_is_still_a_conflict(self):
        self._check_translated_card(renumber=True)

    def test_explicit_cross_source_number_correction_preserves_manual_lock(self):
        self._check_translated_card(renumber=True,marker=True,locked=True)

    def test_combined_claim_applies_cancellation_without_claiming_card_success(self):
        from stable.services.race_data_source_adapters import parse_multisource_policy,fetch_bound_observation
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS
        self.policy=parse_multisource_policy(fixtures.policy_payload(kinds=('racecard','race_time')),now=fixtures.NOW)
        with override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,),RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_ROSTER_ALLOWED_FIELDS),
                RACE_DATA_SYNC_ENABLED_DATA_KINDS=('racecard','race_time'),RACE_DATA_SYNC_ENABLED_PROVIDERS=('jra',),
                RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True),patch(
                'stable.services.race_data_source_adapters.load_multisource_policy',return_value=self.policy),patch(
                'stable.services.race_lifecycle_projection.capacity_manifest',return_value=self.capacity()):
            value=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=fixtures.NOW,fetcher=self.fetch,kind='racecard')
            self.assertEqual(attach_multisource_observation(value,policy=self.policy,now=fixtures.NOW).action,'acquired')
            claim=claim_due_enrollments(now=fixtures.NOW,batch_size=20,ttl_seconds=240,enabled_providers=('jra',),
                enabled_regions=('japan_jra',),enabled_data_kinds=('racecard','race_time'))[0]
            self.assertEqual(set(claim.data_kinds),{'racecard','race_time'})
            value.update(race_status='cancelled',roster_complete=False)
            with patch('stable.services.race_data_source_adapters.fetch_bound_observation',return_value=value):
                outcome=run_multisource_claim(claim=claim,now=fixtures.NOW,fetcher=self.fetch)
            self.event.refresh_from_db();self.assertEqual(self.event.status,'cancelled',outcome)
            self.assertTrue(outcome['processed'],outcome)
            self.assertEqual(outcome['applied_kinds'],['race_time'])
            self.assertFalse(models.RaceLifecyclePublicState.objects.filter(event=self.event).exists())
