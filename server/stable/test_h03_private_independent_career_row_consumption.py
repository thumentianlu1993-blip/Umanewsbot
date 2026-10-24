"""A162 frozen source; NOT EXECUTED. Synthetic private PG mechanism only.

Private API (all keyword-only):
 _apply_independent_career_row_transaction(*, packet, source_raw, reviewed_raw,
   expected_source_sha256, selected_row_sha256, expected_review_sha256,
   actor_id, code_sha, permission_binding, dry_run)
Returns applied/already_applied/ignored/dry_run, committed/published, nullable
record_id/candidate_id, entity_key, review_input_sha256 and LABELS. Dry-run has
simulated_status. already_applied refers to original persistence, not a new write.

REVIEW_FIELDS/REVIEW_SCHEMA below freeze the strict internal bytes contract.
inputs = packet/source {path,sha256}; target = profile_id/entity_key/entity_version/
profile_baseline; binding is EXACT real prepare['binding']; scope=create_unlinked
and null event/result; before=null, after=complete original selected row.
module_reviews.race_record has status approved|ignore, reviewed_by, approved_at,
decision_source_reference. code_sha is declared binding, not code attestation.

Receipt source_name/schema_version=ROLE; raw_payload requires prepared_binding,
review_input_binding={reviewed_input_sha256,decision}, h02_idempotency_key,
selected_row_sha, record_after (existing exact Decimal audit), before_counts,
after_counts, parent_career, h03_result. Existing candidate_payload is JSON-safe
{'items':[typed writer payload]}; diff_payload.record_id.after identifies record.
APPLIED/applied_by/applied_at must be actual saved metadata. Operation log follows
existing horse_candidate_applied/horse_profile/actual actor, detail identifies
candidate and record. No caller-built receipt/prepared dict is accepted as input.

Business failures raise CommandError with exact fixed reasons exercised below;
no blocked-result success, generic catch or system-error conversion. Missing ONLY
this module/private function => NOT_READY skip. Noncallable/signature/dependency/
fixture/PG failures => ERROR; no new implementation or historical RED claimed.
Implementation must expose log_operation alias for real-log fault injection and
call horse_race_records.upsert_race_record (not replace shared writer semantics).
Synthetic permission reference/hash NEVER grants real materialization authority.
"""
import importlib
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta
from queue import Empty, Queue
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from stable import models
from stable.services import horse_race_records
from stable.services.horse_career_record_from_review import _record_audit_state
from stable.services.horse_career_record_link_from_cache import PROFILE_DERIVED_FIELDS
from stable.services.horse_independent_career_row_prepare import _prepare_independent_career_row
from stable.test_h03_independent_career_row_prepare import (
    FIXTURE, FIXTURE_SHA, canonical, digest, encoded,
)
from stable.test_horse_target_inventory import document, event, identity, row

MODULE = 'stable.services.horse_independent_career_row_consume'
PRIVATE = '_apply_independent_career_row_transaction'
ROLE = 'h03_hkjc_independent_career_row.v1'
REVIEW_SCHEMA = 'h03-independent-career-row-reviewed-input.v1'
REVIEW_FIELDS = {'schema_version', 'code_sha', 'inputs', 'target', 'binding',
                 'scope', 'module_reviews', 'reviewer_id', 'before', 'after'}
CODE_BINDING = '4a25d2184d41b8ccf53157b64ad2cc901ddf9512'
VERSION = 'h03-career-row-v1:a162-generation-1'
SOURCE_REF = 'fixture:a162-inert-career-carrier'
PERMISSION = dict(reference='fixture:a162-inert-permission',
                  sha256=digest(b'A162 inert anchor, never a license or grant.\n'))
LABELS = dict(transaction_capability_only=True, source_permission_status='not_evaluated',
              public_consumer_authorized=False)


class PrivateIndependentCareerRowConsumptionTests(TransactionTestCase):
    def need(self):
        try:
            module = importlib.import_module(MODULE)
        except ModuleNotFoundError as error:
            if error.name == MODULE:
                self.skipTest('NOT_READY: ' + MODULE)
            raise
        if not hasattr(module, PRIVATE):
            self.skipTest('NOT_READY: ' + MODULE + ':' + PRIVATE)
        private = getattr(module, PRIVATE)
        if not callable(private):
            raise TypeError('A162 private API is not callable')
        return module, private

    def setUp(self):
        super().setUp()
        self.consumer, self.private = self.need()
        if connection.vendor != 'postgresql':
            raise RuntimeError('A162 requires ROOT-allocated isolated PostgreSQL; no DB-name grants')
        self.actor = get_user_model().objects.create_user(
            username='a162-private-staff', is_staff=True, is_active=True)
        self.term = models.TermEntry.objects.create(term_type='horse', source_language='en',
            source_ja='HARBOUR TEST', target_zh='', racing_region='hong_kong')
        self.profile = models.HorseProfile.objects.create(primary_term=self.term,
            original_name='HARBOUR TEST', racing_region='hong_kong', owner_name='Protected owner',
            official_or_source_start_count=9, official_start_count_source='existing-sentinel',
            source_refs={'horse_identity_verified_keys': ['hkjc:HK-001']})
        raw = FIXTURE.read_bytes()
        if digest(raw) != FIXTURE_SHA:
            raise RuntimeError('A162 original fixture drift')
        self.carrier = json.loads(raw)
        self.carrier['career']['records'] = self.carrier['career']['records'][:1]
        self.carrier['career']['source_start_count'] = 2
        for target in ('urllib.request.urlopen',
                       'stable.services.p0_horse_completion_source_clients._HKJCClient._fetch',
                       'stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter',
                       'stable.services.horse_profile_publish.auto_publish_profiles',
                       'stable.services.horse_profiles.transition_review_status'):
            guard = patch(target, side_effect=AssertionError('A162 network/public mutation forbidden'))
            mocked = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mocked.assert_not_called)

    def state(self):
        return dict(profile=models.HorseProfile.objects.values().get(pk=self.profile.pk),
            term=models.TermEntry.objects.values().get(pk=self.term.pk),
            records=list(models.HorseRaceRecord.objects.values().order_by('pk')),
            candidates=list(models.HorseProfileDataCandidate.objects.values().order_by('pk')),
            logs=list(models.OperationLog.objects.values().order_by('pk')))

    def snapshot(self, now):
        value = document()
        key = f'profile:{self.profile.pk}'
        value.update(as_of=now.date().isoformat(), snapshot_at=now.isoformat(),
            events=[event(region='hong_kong', local_date=(now.date()-timedelta(days=1)).isoformat())],
            participations=[row(horse_key='hkjc:HK-001', birth_year=2020)],
            identities=[identity('hkjc:HK-001', profile=self.profile.pk,
                                 verified_at=(now-timedelta(minutes=2)).isoformat())],
            layers=[dict(target_key=key, cache='present', staging='matched', profile_exists=True,
                         public_state='unpublished', starts=None, incomplete_modules=None)])
        return value

    def request(self, *, carrier=None, selected_index=0, version=VERSION):
        self.profile.refresh_from_db()
        now = timezone.now()
        source = deepcopy(self.carrier if carrier is None else carrier)
        source['source']['fetched_at'] = (now-timedelta(minutes=1)).isoformat()
        source_raw = encoded(source)
        selected = source['career']['records'][selected_index]
        row_sha = digest(canonical(selected))
        key = f'profile:{self.profile.pk}'
        packet = dict(schema_version='h03-prepare-input.v1', source_file='source.json',
            cache_ref='h03-career-row:'+row_sha, source_ref=SOURCE_REF,
            snapshot=self.snapshot(now), entity_versions={key:version}, as_of=now.isoformat(),
            max_age_seconds=3600, profile_baseline=self.profile.updated_at.isoformat())
        packet_raw = encoded(packet)
        prepared = _prepare_independent_career_row(packet=packet_raw, source_raw=source_raw,
            expected_source_sha256=digest(source_raw), selected_row_sha256=row_sha,
            permission_binding=deepcopy(PERMISSION))
        # A real prepare/identity/normalizer failure is an ERROR precondition.
        parent = prepared['row_module']['coverage']['parent_career']
        if (prepared['candidate']['action'] != 'reusable' or prepared['committed'] is not False
                or prepared['public_consumer_authorized'] is not False
                or prepared['source_permission_status'] != 'not_evaluated'
                or prepared['candidate']['entity_key'] != key
                or prepared['writer_payload']['start_status'] != 'started'
                or prepared['writer_payload']['race_date_precision'] != 'exact'
                or parent['status'] != 'partial'):
            raise RuntimeError('A162 real prepare/partial parent precondition failed')
        review = dict(schema_version=REVIEW_SCHEMA, code_sha=CODE_BINDING,
            inputs={name:dict(path=path, sha256=digest(raw)) for name,path,raw in
                    (('packet','packet.json',packet_raw),('source','source.json',source_raw))},
            target=dict(profile_id=self.profile.pk, entity_key=key, entity_version=version,
                        profile_baseline=packet['profile_baseline']),
            binding=deepcopy(prepared['binding']),
            scope=dict(module='race_record', operation='create_unlinked',
                       selected_row_sha=row_sha, event_id=None, result_id=None),
            module_reviews={'race_record':dict(status='approved', reviewed_by=self.actor.get_username(),
                approved_at=now.isoformat(), decision_source_reference='fixture:a162-independent-review')},
            reviewer_id=self.actor.pk, before=None, after=deepcopy(selected))
        if set(review) != REVIEW_FIELDS:
            raise RuntimeError('A162 review fixture shape')
        reviewed_raw = encoded(review)
        return dict(packet=packet_raw, source_raw=source_raw, reviewed_raw=reviewed_raw,
            expected_source_sha256=digest(source_raw), selected_row_sha256=row_sha,
            expected_review_sha256=digest(reviewed_raw), actor_id=self.actor.pk,
            code_sha=CODE_BINDING, permission_binding=deepcopy(PERMISSION), dry_run=False)

    def prepare(self, request):
        return _prepare_independent_career_row(**{k:request[k] for k in
            ('packet','source_raw','expected_source_sha256','selected_row_sha256','permission_binding')})

    def invoke(self, request):
        return self.private(**request)  # TypeError/dependency/system exceptions remain ERROR.

    def reviewed(self, request, change):
        value = json.loads(request['reviewed_raw'])
        change(value)
        raw = encoded(value)
        return dict(request, reviewed_raw=raw, expected_review_sha256=digest(raw))

    def refused(self, request, reason):
        before = self.state()
        with self.assertRaisesRegex(CommandError, '^'+reason+'$'):
            self.invoke(request)
        self.assertEqual(self.state(), before)

    def labels(self, result):
        for key,value in LABELS.items():
            self.assertEqual(result[key], value)
        self.assertIs(result['published'], False)

    def typed_payload(self, request):
        value = deepcopy(self.prepare(request)['writer_payload'])
        value.update(race_date=date.fromisoformat(value['race_date']), race_region='hong_kong',
                     raw_payload=json.loads(request['reviewed_raw'])['after'], event_id=None, result_id=None)
        return value

    def second_carrier(self):
        value = deepcopy(self.carrier)
        second = deepcopy(value['career']['records'][0])
        second.update(race_name='Second synthetic handicap', race_date='2025-12-14', race_number='8',
            external_race_id='HK-20251214-8', source_url='https://example.test/hkjc/race/HK-20251214-8')
        value['career']['records'].append(second)
        value['career']['source_start_count'] = 3  # Two observed starts, still partial.
        return value

    def test_real_create_one_record_receipt_log_complete_binding_and_profile_protection(self):
        request = self.request(); before = self.state(); prepared = self.prepare(request)
        real = horse_race_records.upsert_race_record
        with patch.object(horse_race_records, 'upsert_race_record', wraps=real) as writer:
            result = self.invoke(request)
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(result['status'], 'applied'); self.assertIs(result['committed'], True)
        self.labels(result)
        after = self.state()
        for key in ('records','candidates','logs'):
            self.assertEqual(len(after[key]), len(before[key])+1)
        self.assertEqual(after['term'], before['term'])
        for key,value in before['profile'].items():
            if key not in PROFILE_DERIVED_FIELDS:
                self.assertEqual(after['profile'][key], value, key)
        record = models.HorseRaceRecord.objects.get(pk=result['record_id'])
        self.assertEqual(record.raw_payload, json.loads(request['reviewed_raw'])['after'])
        self.assertEqual((record.event_id,record.result_id,record.start_status,record.race_date_precision),
                         (None,None,'started','exact'))
        self.assertFalse(record.normalization_issues)
        payload = self.typed_payload(request)
        self.assertTrue(horse_race_records.race_record_matches_upsert_payload(record,payload))
        self.assertEqual(record.idempotency_key,horse_race_records.record_idempotency_key(self.profile,payload))
        self.assertEqual(record.canonical_race_key,horse_race_records.canonical_race_key(self.profile,payload))
        self.assertEqual((after['profile']['collected_start_count'],after['profile']['unlinked_race_record_count'],
                          after['profile']['linked_race_event_count']), (1,1,0))
        stored = models.HorseProfileDataCandidate.objects.get(pk=result['candidate_id'])
        self.assertEqual((stored.source_name,stored.module,stored.status,stored.applied_by_id),
            (ROLE,models.HorseProfileModule.RACE_RECORD,models.HorseProfileCandidateStatus.APPLIED,self.actor.pk))
        self.assertIsNotNone(stored.applied_at)
        audit=stored.raw_payload
        self.assertEqual(audit['schema_version'],ROLE)
        self.assertEqual(audit['prepared_binding'],prepared['binding'])
        self.assertEqual(audit['review_input_binding'],dict(reviewed_input_sha256=request['expected_review_sha256'],
                                                          decision=json.loads(request['reviewed_raw'])))
        self.assertEqual(audit['selected_row_sha'],request['selected_row_sha256'])
        self.assertEqual(audit['h02_idempotency_key'],prepared['candidate']['idempotency_key'])
        self.assertEqual(audit['record_after'],_record_audit_state(record))
        self.assertEqual(audit['parent_career'],prepared['row_module']['coverage']['parent_career'])
        self.assertEqual(audit['before_counts'],dict(records=0,collected_start_count=0,
                         linked_race_event_count=0,unlinked_race_record_count=0))
        self.assertEqual(audit['after_counts'],dict(records=1,collected_start_count=1,
                         linked_race_event_count=0,unlinked_race_record_count=1))
        self.assertEqual(audit['h03_result'],result)
        self.assertEqual(stored.diff_payload['record_id'],dict(before=None,after=record.pk))
        expected_payload=json.loads(json.dumps({'items':[payload]},default=lambda v:v.isoformat()))
        self.assertEqual(stored.candidate_payload,expected_payload)
        log=models.OperationLog.objects.get(pk=after['logs'][-1]['id'])
        self.assertEqual((log.action_type,log.target_type,log.target_id,log.admin_id),
                         ('horse_candidate_applied','horse_profile',str(self.profile.pk),self.actor.pk))
        self.assertIn('candidate='+str(stored.pk),log.detail); self.assertIn('record='+str(record.pk),log.detail)

    def test_exact_original_bytes_unlinked_replay_is_same_ids_and_zero_writes(self):
        request=self.request(); first=self.invoke(request); before=self.state()
        with patch.object(horse_race_records,'upsert_race_record',side_effect=AssertionError('replay writer forbidden')):
            replay=self.invoke(request)
        self.assertEqual(replay['status'],'already_applied'); self.labels(replay)
        self.assertIs(replay['committed'],True)
        for key in ('record_id','candidate_id','entity_key','review_input_sha256'):
            self.assertEqual(replay[key],first[key])
        self.assertEqual(self.state(),before)

    def test_old_role_receipt_cannot_authorize_adoption_of_real_existing_record(self):
        request=self.request()
        written=horse_race_records.upsert_race_record(self.profile,self.typed_payload(request))
        self.assertEqual(written.action,'created')
        prepared=self.prepare(request)
        stored=models.HorseProfileDataCandidate.objects.create(profile=self.profile,
            module=models.HorseProfileModule.RACE_RECORD,source_name='h03_hkjc_career_record_review.v1',
            status=models.HorseProfileCandidateStatus.APPLIED,applied_by=self.actor,applied_at=timezone.now(),
            raw_payload=dict(h02_idempotency_key=prepared['candidate']['idempotency_key'],
                             selected_row_sha=request['selected_row_sha256']))
        request=self.request()  # Current baseline, no adoption even with an old applied receipt.
        self.refused(request,'existing_unreviewed_record')
        self.assertEqual(models.HorseProfileDataCandidate.objects.get(pk=stored.pk).source_name,
                         'h03_hkjc_career_record_review.v1')

    def test_second_distinct_row_requires_current_baseline_and_keeps_two_row_receipts(self):
        carrier=self.second_carrier()
        first_request=self.request(carrier=carrier)
        stale_second=self.request(carrier=carrier,selected_index=1)
        self.assertEqual(self.prepare(first_request)['candidate']['idempotency_key'],
                         self.prepare(stale_second)['candidate']['idempotency_key'])
        first=self.invoke(first_request)
        self.refused(stale_second,'stale_baseline')
        second_request=self.request(carrier=carrier,selected_index=1)
        second=self.invoke(second_request)
        self.assertNotEqual(first['record_id'],second['record_id'])
        self.assertNotEqual(first['candidate_id'],second['candidate_id'])
        receipts=list(models.HorseProfileDataCandidate.objects.filter(source_name=ROLE))
        self.assertEqual(len(receipts),2)
        self.assertEqual({r.raw_payload['selected_row_sha'] for r in receipts},
                         {first_request['selected_row_sha256'],second_request['selected_row_sha256']})
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.collected_start_count,self.profile.unlinked_race_record_count),(2,2))

    def test_caller_advanced_entity_version_requires_new_candidate_key_and_current_review(self):
        carrier=self.second_carrier()
        first_request=self.request(carrier=carrier); first=self.invoke(first_request)
        next_request=self.request(carrier=carrier,selected_index=1,version=VERSION+'-advanced')
        self.assertNotEqual(self.prepare(first_request)['candidate']['idempotency_key'],
                            self.prepare(next_request)['candidate']['idempotency_key'])
        second=self.invoke(next_request)
        self.assertNotEqual(first['record_id'],second['record_id'])
        self.assertNotEqual(first['candidate_id'],second['candidate_id'])

    def test_changed_row_hash_same_physical_race_is_not_a_correction_or_new_record(self):
        first=self.invoke(self.request())
        value=deepcopy(self.carrier); value['career']['records'][0]['eligibility_text']='Changed but same race'
        request=self.request(carrier=value)
        self.refused(request,'existing_unreviewed_record')
        self.assertEqual(models.HorseRaceRecord.objects.get().pk,first['record_id'])

    def test_input_review_scope_actor_code_and_prepared_bindings_cannot_be_forged(self):
        request=self.request()
        variants=[(dict(request,source_raw=request['source_raw']+b' '),'input_sha_mismatch'),
            (dict(request,reviewed_raw=request['reviewed_raw']+b' '),'review_sha_mismatch'),
            (dict(request,code_sha='a'*40),'review_code_mismatch'),
            (dict(request,permission_binding=dict(PERMISSION,reference='fixture:a162-other-anchor')),'review_binding_mismatch'),
            (self.reviewed(request,lambda r:r['scope'].update(event_id=123)),'review_scope_mismatch'),
            (self.reviewed(request,lambda r:r['target'].update(profile_id=self.profile.pk+1)),'review_target_mismatch'),
            (self.reviewed(request,lambda r:r.update(reviewer_id=self.actor.pk+1)),'review_actor_mismatch'),
            (self.reviewed(request,lambda r:r['binding'].update(projection_sha256='b'*64)),'review_binding_mismatch'),
            (self.reviewed(request,lambda r:r['after'].update(distance_text='9999m')),'review_before_after_mismatch')]
        for bad,reason in variants:
            with self.subTest(reason=reason): self.refused(bad,reason)

    def test_same_row_key_with_rebound_source_or_review_is_a_receipt_conflict(self):
        request=self.request(); self.invoke(request)
        for kind in ('source','review'):
            bad=dict(request)
            review=json.loads(request['reviewed_raw'])
            if kind=='source':
                bad['source_raw']=request['source_raw']+b' '
                bad['expected_source_sha256']=digest(bad['source_raw'])
                rebuilt=self.prepare(bad)
                review['binding']=rebuilt['binding']
                review['inputs']['source']['sha256']=bad['expected_source_sha256']
            else:
                review['module_reviews']['race_record']['decision_source_reference']='fixture:a162-other-review'
            bad['reviewed_raw']=encoded(review)
            bad['expected_review_sha256']=digest(bad['reviewed_raw'])
            with self.subTest(kind=kind): self.refused(bad,'consumption_binding_mismatch')

    def test_current_staff_private_identity_baseline_and_module_lock_guards(self):
        request=self.request()
        attacks=[('staff','actor_not_staff'),('active','actor_not_staff'),('hidden','target_not_private'),
            ('public','target_not_private'),('identity','strong_identity_missing'),
            ('conflict','identity_conflict'),('baseline','stale_baseline'),('lock','module_locked')]
        for attack,reason in attacks:
            with self.subTest(attack=attack),transaction.atomic():
                if attack in ('staff','active'):
                    get_user_model().objects.filter(pk=self.actor.pk).update(**{'is_'+attack:False})
                else:
                    changes={'hidden':dict(hidden_at=timezone.now()),'public':dict(review_status=models.HorseProfileStatus.PUBLISHED),
                        'identity':dict(source_refs={}),
                        'conflict':dict(source_refs={'horse_identity_verified_keys':['hkjc:HK-001','hkjc:HK-OTHER']}),
                        'baseline':dict(updated_at=timezone.now()+timedelta(seconds=1)),
                        'lock':dict(manual_lock_flags={'race_record':True})}[attack]
                    models.HorseProfile.objects.filter(pk=self.profile.pk).update(**changes)
                self.refused(request,reason)
                transaction.set_rollback(True)

    def test_real_writer_noop_raw_profile_and_count_pollution_roll_back(self):
        real=horse_race_records.upsert_race_record
        for kind,reason in (('noop','writer_not_created'),('raw','writer_source_drift'),
                            ('profile','writer_profile_protection'),('counts','writer_count_protection')):
            request=self.request(); before=self.state()
            def fault(profile,payload):
                written=real(profile,payload)
                if kind=='noop': return SimpleNamespace(record=written.record,action='unchanged')
                if kind=='raw':
                    models.HorseRaceRecord.objects.filter(pk=written.record.pk).update(raw_payload={'forged':True})
                if kind=='profile': models.HorseProfile.objects.filter(pk=profile.pk).update(owner_name='FORBIDDEN')
                if kind=='counts': models.HorseProfile.objects.filter(pk=profile.pk).update(collected_start_count=999)
                return written
            with self.subTest(kind=kind),patch.object(horse_race_records,'upsert_race_record',side_effect=fault):
                with self.assertRaisesRegex(CommandError,'^'+reason+'$'): self.invoke(request)
            self.assertEqual(self.state(),before)

    def test_real_post_insert_writer_candidate_and_log_exceptions_propagate_and_roll_back(self):
        real_writer=horse_race_records.upsert_race_record
        real_save=models.HorseProfileDataCandidate.save
        real_log=self.consumer.log_operation
        for kind in ('writer','candidate','log'):
            request=self.request(); before=self.state(); failure=RuntimeError('A162 actual post-insert '+kind)
            reached=[]
            def writer_then_fail(profile,payload):
                result=real_writer(profile,payload); reached.append(result.record.pk); raise failure
            def candidate_then_fail(stored,*args,**kwargs):
                result=real_save(stored,*args,**kwargs)
                if stored.source_name==ROLE:
                    reached.append(stored.pk); raise failure
                return result
            def log_then_fail(**kwargs):
                value=real_log(**kwargs); reached.append(value.pk); raise failure
            context={'writer':patch.object(horse_race_records,'upsert_race_record',side_effect=writer_then_fail),
                'candidate':patch.object(models.HorseProfileDataCandidate,'save',candidate_then_fail),
                'log':patch.object(self.consumer,'log_operation',side_effect=log_then_fail)}[kind]
            with self.subTest(kind=kind),context:
                with self.assertRaises(RuntimeError) as caught: self.invoke(request)
                self.assertIs(caught.exception,failure)
                self.assertTrue(reached,'must execute real insertion before injected exception')
            self.assertEqual(self.state(),before)

    def test_result_serialization_error_after_real_rows_propagates_and_rolls_back(self):
        request=self.request(); before=self.state(); real=json.dumps
        failure=RuntimeError('A162 final result serialization'); reached=[]
        def serialize(value,*args,**kwargs):
            if (isinstance(value,dict) and value.get('status')=='applied'
                    and value.get('committed') is True and value.get('record_id') is not None
                    and models.OperationLog.objects.filter(target_id=str(self.profile.pk)).exists()):
                reached.append(dict(records=models.HorseRaceRecord.objects.count(),
                    candidates=models.HorseProfileDataCandidate.objects.filter(source_name=ROLE).count(),
                    logs=models.OperationLog.objects.count()))
                raise failure
            return real(value,*args,**kwargs)
        with patch.object(json,'dumps',side_effect=serialize):
            with self.assertRaises(RuntimeError) as caught: self.invoke(request)
            self.assertIs(caught.exception,failure)
        self.assertTrue(reached,'must serialize result after actual record/candidate/log insert')
        self.assertTrue(all(v['records']==1 and v['candidates']==1 and v['logs']==1 for v in reached))
        self.assertEqual(self.state(),before)

    def test_dropped_real_operation_log_rejects_and_rolls_back_all_rows(self):
        request=self.request(); before=self.state(); real=self.consumer.log_operation
        def dropped(**kwargs):
            obj=real(**kwargs)
            models.OperationLog.objects.filter(pk=obj.pk).delete()
            return obj
        with patch.object(self.consumer,'log_operation',side_effect=dropped):
            with self.assertRaisesRegex(CommandError,'^operation_readback_mismatch$'): self.invoke(request)
        self.assertEqual(self.state(),before)

    def test_dry_run_real_writer_rolls_back_and_ignore_never_consumes(self):
        request=self.request(); before=self.state()
        with patch.object(horse_race_records,'upsert_race_record',wraps=horse_race_records.upsert_race_record) as writer:
            result=self.invoke(dict(request,dry_run=True))
        self.assertEqual(writer.call_count,1)
        self.assertEqual((result['status'],result['simulated_status']),('dry_run','applied'))
        self.assertIs(result['committed'],False); self.labels(result)
        self.assertIsNone(result['record_id']); self.assertIsNone(result['candidate_id'])
        self.assertEqual(self.state(),before)
        ignored=self.reviewed(request,lambda r:r['module_reviews']['race_record'].update(status='ignore'))
        with patch.object(horse_race_records,'upsert_race_record',side_effect=AssertionError('ignore writer forbidden')):
            result=self.invoke(ignored)
        self.assertEqual(result['status'],'ignored'); self.assertIs(result['committed'],False); self.labels(result)
        self.assertIsNone(result['record_id']); self.assertIsNone(result['candidate_id'])
        self.assertEqual(self.state(),before)

    def test_replay_receipt_binding_record_drift_and_missing_record_reject_without_repair(self):
        request=self.request(); result=self.invoke(request)
        for kind,reason in (('binding','consumption_binding_mismatch'),('record','consumption_record_mismatch'),
                            ('missing','consumption_record_mismatch'),('ambiguous','consumption_ambiguous')):
            with self.subTest(kind=kind),transaction.atomic():
                stored=models.HorseProfileDataCandidate.objects.get(pk=result['candidate_id'])
                if kind=='binding':
                    raw=deepcopy(stored.raw_payload); raw['prepared_binding']['source_sha256']='a'*64
                    models.HorseProfileDataCandidate.objects.filter(pk=stored.pk).update(raw_payload=raw)
                if kind=='record': models.HorseRaceRecord.objects.filter(pk=result['record_id']).update(race_name='DRIFT')
                if kind=='missing': models.HorseRaceRecord.objects.filter(pk=result['record_id']).delete()
                if kind=='ambiguous':
                    stored.pk=None; stored.save(force_insert=True)
                self.refused(request,reason)
                transaction.set_rollback(True)

    def test_linked_record_replay_refuses_without_unlinking_or_cloning(self):
        request=self.request(); result=self.invoke(request)
        linked=models.RaceEvent.objects.create(year=2025,edition_year=2025,slug='a162-linked-fixture',
            original_name='Class 2 Handicap',country_region='hong_kong',racecourse='Sha Tin',
            local_date=date(2025,12,7),timezone_name='Asia/Hong_Kong')
        models.HorseRaceRecord.objects.filter(pk=result['record_id']).update(event=linked)
        self.refused(request,'consumption_record_mismatch')
        self.assertEqual(models.HorseRaceRecord.objects.get(pk=result['record_id']).event_id,linked.pk)

    def test_future_source_packet_or_review_is_not_current_write_authority(self):
        future=timezone.now()+timedelta(hours=2)
        with patch('django.utils.timezone.now',return_value=future):
            request=self.request()  # Real prepare is reusable at its declared future as_of.
        self.refused(request,'source_or_packet_future')
        request=self.request()
        request=self.reviewed(request,lambda r:r['module_reviews']['race_record'].update(approved_at=future.isoformat()))
        self.refused(request,'review_future')

    def test_expired_replay_cannot_bypass_current_time_checks(self):
        request=self.request(); self.invoke(request)
        source=datetime.fromisoformat(json.loads(request['source_raw'])['source']['fetched_at'])
        expires=source+timedelta(seconds=json.loads(request['packet'])['max_age_seconds']+1)
        with patch('django.utils.timezone.now',return_value=expires):
            self.refused(request,'source_expired')

    @staticmethod
    def backend(cursor):
        cursor.execute('SELECT pg_backend_pid(),current_database(),current_user')
        return dict(zip(('pid','database','user'),cursor.fetchone()))

    def lock_exercise(self, *, case):
        """External holder/observer; real worker connections, positive blocker graph.

        No service/writer mock for concurrency. Controlled time changes only after
        positive actual Lock sample, with holder still holding the relevant row.
        All futures are joined after holder release even on assertion/error paths.
        """
        import psycopg
        request=self.request(); before=self.state(); channel=Queue(); now=[timezone.now()]
        source_time=datetime.fromisoformat(json.loads(request['source_raw'])['source']['fetched_at'])
        source_deadline=source_time+timedelta(seconds=json.loads(request['packet'])['max_age_seconds'])
        diag=dict(case=case,events=[],samples=[],workers=[],cleanup='UNKNOWN',
                  original_source_deadline=source_deadline.isoformat(),initial_clock=now[0].isoformat())
        pool=ThreadPoolExecutor(max_workers=2)
        futures=[]; holder=None; observer=None; primary=None; outcomes=[]
        def worker(index):
            try:
                close_old_connections(); connection.ensure_connection()
                with connection.cursor() as cursor: ident=self.backend(cursor)
                channel.put(dict(phase='ready',index=index,at=time.monotonic(),**ident))
                result=self.invoke(request)
                channel.put(dict(phase='returned',index=index,result=result))
                return result
            except BaseException as error:
                channel.put(dict(phase='error',index=index,type=type(error).__name__,message=str(error),
                                 traceback=''.join(traceback.format_exception(error))))
                raise
            finally:
                connection.close()
                channel.put(dict(phase='closed',index=index,at=time.monotonic()))
        def connect(name):
            configured=connection.get_connection_params()
            params={k:configured[k] for k in ('dbname','user','password','host','port') if k in configured}
            return psycopg.connect(**params,connect_timeout=5,application_name=name,autocommit=True)
        def observe_blocked(ident):
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                # Fresh autocommit statement; blocker chain covers queued sibling.
                with observer.cursor() as cursor:
                    cursor.execute('SELECT pid,datname,usename,state,wait_event_type,wait_event,pg_blocking_pids(pid) '
                                   'FROM pg_stat_activity WHERE datname=current_database()')
                    activity={r[0]:dict(zip(('pid','database','user','state','wait_type','wait','blockers'),r))
                              for r in cursor.fetchall()}
                current=activity.get(ident['pid']); seen=set(); pending=[ident['pid']]
                while pending:
                    pid=pending.pop()
                    if pid in seen: continue
                    seen.add(pid)
                    pending.extend(activity.get(pid,{}).get('blockers',[]))
                sample=dict(at=time.monotonic(),worker=ident['pid'],activity=current,
                            blocker_path_nodes=sorted(seen),holder_pid=diag['holder']['pid'],
                            blocker_graph={str(pid):activity.get(pid) for pid in seen})
                diag['samples'].append(sample)
                if (current and current['database']==ident['database'] and current['user']==ident['user']
                    and current['state']=='active' and current['wait_type']=='Lock'
                    and diag['holder']['pid'] in seen):
                    return
                if any(f.done() for f in futures):
                    raise RuntimeError('A162 worker completed before positive PG lock evidence')
                time.sleep(.02)  # Poll cadence, never the evidence of blocking.
            raise RuntimeError('A162 PG observer failed to establish positive lock sample')
        with patch('django.utils.timezone.now',side_effect=lambda:now[0]):
            try:
                holder=connect('a162-holder'); observer=connect('a162-autocommit-observer')
                with observer.cursor() as cursor:
                    cursor.execute('SET statement_timeout=1000'); diag['observer']=self.backend(cursor)
                with holder.cursor() as cursor:
                    cursor.execute('SET statement_timeout=10000'); cursor.execute('BEGIN')
                    diag['holder']=self.backend(cursor)
                    model=self.profile if case=='profile_expiry' else self.actor
                    table=model._meta.db_table
                    cursor.execute('SELECT id FROM "'+table+'" WHERE id=%s FOR NO KEY UPDATE',[model.pk])
                count=2 if case=='concurrent' else 1
                for index in range(count):
                    futures.append(pool.submit(worker,index))
                    ready=channel.get(timeout=5); diag['events'].append(ready)
                    if ready['phase']!='ready':
                        raise RuntimeError('A162 worker could not establish ready backend: '+repr(ready))
                    ident={k:ready[k] for k in ('pid','database','user')}; diag['workers'].append(ident)
                    for reference in (diag['holder'],diag['observer']):
                        self.assertEqual(ident['database'],reference['database'])
                        self.assertEqual(ident['user'],reference['user'])
                    self.assertEqual(len({d['pid'] for d in diag['workers']+[diag['holder'],diag['observer']]}),
                                     len(diag['workers'])+2)
                    observe_blocked(ident)
                if case=='revoked':
                    with holder.cursor() as cursor:
                        cursor.execute('UPDATE "'+self.actor._meta.db_table+'" SET is_staff=false WHERE id=%s',[self.actor.pk])
                if case in ('actor_expiry','profile_expiry'):
                    source=datetime.fromisoformat(json.loads(request['source_raw'])['source']['fetched_at'])
                    now[0]=source+timedelta(seconds=json.loads(request['packet'])['max_age_seconds']+1)
                    diag['advanced_after_positive_wait']=now[0].isoformat()
            except BaseException as error:
                primary=error
            finally:
                # Release holder BEFORE joining, including failed observation paths.
                if holder is not None:
                    try:
                        if case=='revoked' and primary is None:
                            holder.commit(); diag['holder_outcome']='COMMIT_REVOCATION'
                        else:
                            holder.rollback(); diag['holder_outcome']='ROLLBACK_RELEASE'
                        diag['holder_released']=True
                    except BaseException as error:
                        if primary is None: primary=error
                for future in futures:
                    try: outcomes.append(future.result(timeout=20))
                    except BaseException as error: outcomes.append(error)
                diag['futures_done']=[f.done() for f in futures]
                for label,session in (('holder',holder),('observer',observer)):
                    if session is not None:
                        try: session.close()
                        except BaseException as error:
                            diag[label+'_close_error']=repr(error)
                            if primary is None: primary=error
                diag['holder_closed']=holder is None or holder.closed
                diag['observer_closed']=observer is None or observer.closed
                pool.shutdown(wait=False,cancel_futures=True)
                while True:
                    try: diag['events'].append(channel.get_nowait())
                    except Empty: break
                closed={e['index'] for e in diag['events'] if e['phase']=='closed'}
                if all(diag['futures_done']) and closed==set(range(len(futures))):
                    diag['cleanup']='COMPLETE'
                print('A162_PG_LOCK_DIAGNOSTICS '+json.dumps(diag,default=str,sort_keys=True),flush=True)
        if primary is not None: raise primary.with_traceback(primary.__traceback__)
        if diag['cleanup']!='COMPLETE': raise RuntimeError('A162 worker/connection cleanup UNKNOWN')
        for value in outcomes:
            if isinstance(value,BaseException) and not isinstance(value,CommandError): raise value
        if case=='concurrent':
            self.assertTrue(all(isinstance(r,dict) for r in outcomes),repr(outcomes))
            self.assertEqual(sorted(r['status'] for r in outcomes),['already_applied','applied'])
            self.assertEqual(len({r['record_id'] for r in outcomes}),1)
            self.assertEqual(len({r['candidate_id'] for r in outcomes}),1)
            for value in outcomes: self.labels(value)
            after=self.state()
            for key in ('records','candidates','logs'): self.assertEqual(len(after[key]),len(before[key])+1)
        else:
            self.assertEqual(len(outcomes),1)
            self.assertIsInstance(outcomes[0],CommandError)
            self.assertEqual(str(outcomes[0]),'actor_not_staff' if case=='revoked' else 'source_expired')
            if case=='revoked':
                self.assertFalse(get_user_model().objects.get(pk=self.actor.pk).is_staff)
            self.assertEqual(self.state(),before)

    def test_two_identical_requests_real_pg_wait_one_create_one_replay(self):
        self.lock_exercise(case='concurrent')

    def test_actor_lock_wait_crosses_source_ttl_and_refuses_all_writes(self):
        self.lock_exercise(case='actor_expiry')

    def test_profile_lock_wait_crosses_source_ttl_and_refuses_all_writes(self):
        self.lock_exercise(case='profile_expiry')

    def test_actor_revoked_while_real_lock_waiting_refuses_all_writes(self):
        self.lock_exercise(case='revoked')
