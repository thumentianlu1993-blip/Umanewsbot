"""A045 real business RED and GREEN contracts; only ROOT-isolated PostgreSQL.

No manual ORM eligibility repair in positive setup; no consumer/writer success
mock. Concurrency synchronization pauses a real call, retaining real PG locks.
"""
import hashlib
import io
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone as django_timezone

from stable import models
from stable.services import horse_race_records
from stable.services import horse_career_record_from_review as consumer
from stable.services.horse_career_record_link_from_cache import (
    apply_career_record_link_from_cache, PROFILE_DERIVED_FIELDS, RECORD_CHANGED_FIELDS,
)
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.services.horse_source_cache_reuse_adapter import adapt_hkjc_source_cache
from stable.services.horse_target_inventory import _sha
from stable.services.p0_horse_completion_adapters import _normalize_race_record
from stable.services.race_data_source_adapters import canonical_sha, load_multisource_policy
from stable.services.race_data_sync_admission import binding_admission_reason
from stable.services.race_data_sync_control import _canonical_json_bytes
from stable.test_horse_target_inventory import document, event, identity, row

FIXTURE = Path(__file__).parent / 'fixtures/h03_career_link/hkjc_synthetic.json'
NOW = datetime(2026, 10, 3, 1, tzinfo=timezone.utc)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode()


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class ReviewedCareerRecordConsumerTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor != 'postgresql':
            raise AssertionError('A045 requires ROOT-allocated isolated PostgreSQL')
        self.clock = patch('django.utils.timezone.now', return_value=NOW)
        self.clock_mock = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.client_clock = client_clock = patch('stable.services.p0_horse_completion_source_clients.datetime', FrozenDateTime)
        client_clock.start()
        self.addCleanup(client_clock.stop)
        self.actor = get_user_model().objects.create_user(username='a045-synthetic-actor', is_staff=True)
        self.term = models.TermEntry.objects.create(
            term_type='horse', source_language='en', source_ja='HARBOUR TEST',
            target_zh='', racing_region='hong_kong')
        self.profile = models.HorseProfile.objects.create(
            primary_term=self.term, original_name='HARBOUR TEST', racing_region='hong_kong',
            source_refs={'horse_identity_verified_keys': ['hkjc:hk-001']},
            display_name_zh='私有测试', owner_name='Existing Owner',
            official_or_source_start_count=9, official_start_count_source='existing-sentinel')
        self.event = models.RaceEvent.objects.create(
            year=2025, edition_year=2025, slug='a045-synthetic-class-two',
            original_name='Class 2 Handicap', country_region='hong_kong',
            racecourse='Sha Tin', local_date=date(2025, 12, 7), timezone_name='Asia/Hong_Kong')
        self.payload = json.loads(FIXTURE.read_bytes())
        selected = self.payload['career']['records'][0]
        self.temp = tempfile.TemporaryDirectory(prefix='a045-policy-')
        self.addCleanup(self.temp.cleanup)
        self.policy_path = Path(self.temp.name) / 'policy.json'
        route = dict(
            provider='hkjc', region='hong_kong', country_region='hong_kong',
            identity_namespace='hkjc-race-v1', operator='hkjc', source_class='official_operator',
            capabilities=['racecard'], allowed_hosts=['racing.hkjc.com'],
            allowed_path_prefixes=['/racing/information/English/Racing/'], parser_version='synthetic-v1',
            contract_digest='a' * 64, proof_digest='b' * 64, terms_sha256='c' * 64,
            automation_allowed=True, proof_network_allowed=True,
            valid_from='2025-01-01T00:00:00+00:00', valid_until=(NOW + timedelta(days=1)).isoformat(),
            tiebreak_order=10, venue_aliases={'sha_tin': ['Sha Tin', '沙田']}, timezone='Asia/Hong_Kong')
        self.policy_payload = dict(schema_version=3, policy_id='a045-synthetic-only',
                                   valid_from=route['valid_from'], valid_until=route['valid_until'], routes=[route])
        policy_bytes = _canonical_json_bytes(self.policy_payload)
        self.policy_path.write_bytes(policy_bytes)
        settings = override_settings(
            RACE_DATA_MULTISOURCE_POLICY_FILE=str(self.policy_path),
            RACE_DATA_MULTISOURCE_POLICY_SHA256=hashlib.sha256(policy_bytes).hexdigest(),
            RACE_DATA_SYNC_ENABLED=False, RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=(), RACE_DATA_SYNC_ENABLED_REGIONS=(),
            RACE_DATA_SYNC_ENABLED_DATA_KINDS=())
        settings.enable()
        self.addCleanup(settings.disable)
        # Real fixed-file loader/parser, never a mocked admission or policy.
        self.policy = load_multisource_policy(now=NOW)
        self.route = self.policy.routes[0]
        evidence = dict(provider='hkjc', region='hong_kong', identity_namespace='hkjc-race-v1',
                        external_race_id=selected['external_race_id'], operator='hkjc', venue_key='sha_tin',
                        local_date='2025-12-07', race_number='7', timezone='Asia/Hong_Kong')
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event, source_key='hkjc', region_code='hong_kong', identity_namespace='hkjc-race-v1',
            external_race_id=selected['external_race_id'],
            canonical_url='https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx?RaceNo=7',
            host='racing.hkjc.com', identity_fields={'multisource_v2': evidence},
            review_status='approved', terms_status='approved', automation_allowed=True,
            proof_network_allowed=True, valid_until=NOW + timedelta(days=1), registry_digest=self.route.digest,
            evidence_sha256=canonical_sha({'synthetic': True}), reviewed_by=self.actor, reviewed_at=NOW)
        self.enrollment = models.RaceDataSyncEnrollment.objects.create(
            event=self.event, source_identity=self.source, authority_version=2, state='enrolled',
            standing_policy_digest=self.policy.digest, route_digest=self.route.digest,
            event_snapshot_sha256='d' * 64, manifest_sha256='e' * 64, entry_sha256='f' * 64)
        manifest = dict(event_id=self.event.pk, source_identity_id=self.source.pk,
                        source_registry_digest=self.source.registry_digest,
                        route=self.route.payload, route_digest=self.route.digest,
                        identity_evidence=evidence, identity_evidence_sha256=canonical_sha(evidence),
                        policy_digest=self.policy.digest)
        self.binding = models.RaceDataSyncSourceBinding.objects.create(
            enrollment=self.enrollment, source_identity=self.source, capabilities=['racecard'],
            route_digest=self.route.digest, contract_digest=self.route.contract_digest,
            proof_digest=self.route.proof_digest, registry_schema_version=3,
            identity_evidence_sha256=canonical_sha(evidence), binding_manifest=manifest,
            binding_manifest_sha256=canonical_sha(manifest), valid_until=NOW + timedelta(days=1))
        self.assertEqual(binding_admission_reason(binding=self.binding, route=self.route, now=NOW,
                         capability='racecard', check_runtime=False), '', 'real binding contract prerequisite')
        for target in ('urllib.request.urlopen',
                       'stable.services.p0_horse_completion_source_clients._HKJCClient._fetch',
                       'stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter',
                       'stable.services.horse_profile_publish.auto_publish_profiles',
                       'stable.services.horse_profiles.transition_review_status',
                       'stable.services.race_data_source_adapters.fetch_bound_observation',
                       'stable.services.race_data_sync_enrollment.attach_multisource_observation'):
            guard = patch(target, side_effect=AssertionError('A045 producer/public/binding mutation forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def state(self):
        tables = (models.HorseProfile, models.HorseRaceRecord, models.HorseProfileDataCandidate,
                  models.OperationLog, models.TermEntry, models.RaceEvent, models.RaceEventResult,
                  models.RaceResultSourceIdentity, models.RaceDataSyncEnrollment, models.RaceDataSyncSourceBinding)
        return {table.__name__: deepcopy(list(table.objects.order_by('pk').values())) for table in tables}

    def request(self, *, payload=None, decision='approved', now=NOW, max_age_seconds=78 * 86400):
        self.profile.refresh_from_db()
        source = deepcopy(self.payload if payload is None else payload)
        raw = encoded(source)
        source_sha = hashlib.sha256(raw).hexdigest()
        snapshot = document()
        # H01 must explicitly observe this actual existing private fixture;
        # identities alone leave the layer unknown and cannot pass _prepare.
        exists = models.HorseProfile.objects.filter(pk=self.profile.pk).exists()
        self.assertTrue(exists, 'H01 fixture target must actually exist')
        self.assertIn(self.profile.review_status, (models.HorseProfileStatus.DRAFT, models.HorseProfileStatus.READY))
        self.assertIsNone(self.profile.hidden_at, 'H01 fixture must actually be private')
        layer = dict(target_key=f'profile:{self.profile.pk}', cache='present', staging='unknown',
                     profile_exists=exists, public_state='unpublished',
                     starts=self.profile.race_records.filter(start_status='started').count(), incomplete_modules=None)
        horse_key = 'hkjc:' + source['source']['external_horse_id']
        snapshot.update(events=[event(region='hong_kong')],
                        participations=[row(horse_key=horse_key, birth_year=2020)],
                        identities=[identity(horse_key, profile=self.profile.pk)], layers=[layer])
        versions = {f'profile:{self.profile.pk}': 'a045-v1'}
        cache = adapt_hkjc_source_cache(raw, expected_sha256=source_sha, ref='cache:a045', source_ref='fixture:a045')
        plan = plan_cache_reuse(snapshot, [cache], versions, as_of=now.isoformat(), max_age_seconds=max_age_seconds)
        self.assertEqual(plan['decisions'][0]['status'], 'reusable', 'actual adapter/planner prerequisite')
        self.assertIs(plan['decisions'][0]['profile_exists'], True, 'actual H01 existing profile prerequisite')
        self.assertEqual(plan['decisions'][0]['public_state'], 'unpublished', 'actual H01 private prerequisite')
        candidate = plan['candidates'][0]
        packet = {'schema_version': 'h03-prepare-input.v1', 'source_file': 'source.json',
                  'cache_ref': 'cache:a045', 'source_ref': 'fixture:a045', 'snapshot': snapshot,
                  'entity_versions': versions, 'as_of': now.isoformat(), 'max_age_seconds': max_age_seconds,
                  'profile_baseline': self.profile.updated_at.isoformat()}
        packet_raw = encoded(packet)
        selected = source['career']['records'][0]
        code_sha = os.environ.get('A045_TEST_CODE_SHA', '')
        self.assertRegex(code_sha, r'^[0-9a-f]{40}$', 'ROOT must supply frozen actual A045 code SHA')
        reviewed = {'schema_version': consumer.REVIEW_SCHEMA, 'code_sha': code_sha,
                    'inputs': {'packet': {'path': 'packet.json', 'sha256': hashlib.sha256(packet_raw).hexdigest()},
                               'cache': {'path': 'source.json', 'sha256': source_sha}},
                    'target': {'profile_id': self.profile.pk, 'entity_key': candidate['entity_key'],
                               'entity_version': candidate['entity_version'], 'h02_idempotency_key': candidate['idempotency_key'],
                               'inventory_sha256': plan['inventory_sha256'], 'h02_plan_sha256': plan['content_sha256']},
                    'scope': {'module': 'race_record', 'operation': 'create_unlinked',
                              'selected_row_sha': _sha(selected), 'event_id': None, 'result_id': None},
                    'module_reviews': {'race_record': {'status': decision, 'reviewed_by': self.actor.get_username(),
                        'approved_at': now.isoformat(), 'decision_source_reference': 'synthetic:independent-a045-review'}},
                    'reviewer_id': self.actor.pk,
                    'before': {'record_exists': False, 'profile_baseline': packet['profile_baseline']},
                    'after': _normalize_race_record(selected)}
        review_raw = encoded(reviewed)
        return dict(packet=packet_raw, source_raw=raw, reviewed_raw=review_raw,
                    expected_review_sha256=hashlib.sha256(review_raw).hexdigest(),
                    expected_row_sha256=_sha(selected), actor=self.actor, code_sha=code_sha, dry_run=False)

    def rereview(self, request, edit):
        changed = deepcopy(request)
        review = json.loads(changed['reviewed_raw'])
        edit(review)
        changed['reviewed_raw'] = encoded(review)
        changed['expected_review_sha256'] = hashlib.sha256(changed['reviewed_raw']).hexdigest()
        return changed

    def prepare(self, request):
        return consumer.prepare_reviewed_career_record(**request)

    def apply(self, request):
        self.prepare(request)  # actual real input prerequisite, not a mocked return
        result = consumer.consume_reviewed_career_record(**request)
        self.assertEqual(models.HorseRaceRecord.objects.filter(horse_profile=self.profile).count(), 1,
                         'A045 business RED: valid independent review must create one formal record (0 -> 1)')
        self.assertEqual(result['status'], 'applied')
        self.assertFalse(result['published'])
        self.assertTrue(result['committed'])
        self.record = models.HorseRaceRecord.objects.get(pk=result['record_id'])
        self.assertEqual(self.record.horse_profile_id, self.profile.pk)
        return result

    def positive_rollback(self):
        with transaction.atomic():
            self.apply(self.request())
            transaction.set_rollback(True)
        self.profile.refresh_from_db()

    def blocked(self, request, reason=None):
        before = self.state()
        try:
            result = consumer.consume_reviewed_career_record(**request)
        except CommandError as exc:
            if reason:
                self.assertIn(reason, str(exc))
        else:
            self.assertEqual(result['status'], 'blocked')
            if reason:
                self.assertEqual(result['reason'], reason)
        self.assertEqual(self.state(), before)

    def test_legacy_writer_preserves_explicit_eligibility(self):
        values = _normalize_race_record(deepcopy(self.payload['career']['records'][0]))
        values.update(race_date=date.fromisoformat(values['race_date']), race_region='hong_kong',
                      raw_payload=deepcopy(self.payload['career']['records'][0]))
        result = horse_race_records.upsert_race_record(self.profile, values)
        record = models.HorseRaceRecord.objects.get(pk=result.record.pk)
        self.assertEqual(record.eligibility_text, '3yo+', 'legacy writer business RED: explicit eligibility must persist')
        self.assertEqual(record.minimum_age, 3)
        self.assertIsNone(record.maximum_age)
        self.assertTrue(record.age_open_ended)
        self.assertEqual(record.normalization_issues, [])
        # GREEN must retain the existing value when a later writer payload omits key.
        without_key = {k: v for k, v in values.items() if k != 'eligibility_text'}
        horse_race_records.upsert_race_record(self.profile, without_key, record=record)
        record.refresh_from_db()
        self.assertEqual(record.eligibility_text, '3yo+')

    def test_create_replay_and_original_legal_link_same_record(self):
        request = self.request()
        bundle = self.prepare(request)
        before = self.state()
        self.clock_mock.return_value = NOW + timedelta(seconds=1)
        result = self.apply(request)
        after = self.state()
        self.assertEqual(self.record.raw_payload, bundle['selected'])
        self.assertEqual(_sha(self.record.raw_payload), request['expected_row_sha256'])
        self.assertEqual((self.record.event_id, self.record.result_id), (None, None))
        self.assertEqual((self.record.start_status, self.record.race_date_precision), ('started', 'exact'))
        self.assertEqual(self.record.eligibility_text, '3yo+')
        self.assertEqual(self.record.minimum_age, 3)
        self.assertTrue(self.record.age_open_ended)
        self.assertEqual(self.record.normalization_issues, [])
        self.assertTrue(self.record.idempotency_key)
        self.assertTrue(self.record.canonical_race_key)
        self.assertTrue(self.record.source_refs['sources'])
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.collected_start_count, self.profile.linked_race_event_count,
                          self.profile.unlinked_race_record_count), (1, 0, 1))
        old, new = before['HorseProfile'][0], after['HorseProfile'][0]
        for field in old.keys() - PROFILE_DERIVED_FIELDS:
            self.assertEqual(old[field], new[field], field)
        self.assertNotEqual(self.profile.career_history_status, 'complete')
        for name in before.keys() - {'HorseProfile', 'HorseRaceRecord', 'HorseProfileDataCandidate', 'OperationLog'}:
            self.assertEqual(before[name], after[name], name)
        self.assertEqual(len(after['HorseProfileDataCandidate']), 1)
        self.assertEqual(len(after['OperationLog']), 1)
        stored = models.HorseProfileDataCandidate.objects.get(pk=result['candidate_id'])
        self.assertEqual((stored.source_name, stored.module, stored.status, stored.confidence),
                         (consumer.SOURCE_ROLE, 'race_record', 'applied', 0))
        self.assertEqual(stored.applied_by_id, self.actor.pk)
        self.clock_mock.return_value = NOW + timedelta(seconds=2)
        replay = consumer.consume_reviewed_career_record(**request)
        self.assertEqual(replay['status'], 'already_applied')
        self.assertEqual(replay['record_id'], result['record_id'])
        self.assertEqual(self.state(), after, 'replay must not even refresh timestamps')
        p = bundle['packet']
        link_request = dict(snapshot=p['snapshot'], candidate=bundle['candidate'], raw_bytes=request['source_raw'],
            expected_sha256=hashlib.sha256(request['source_raw']).hexdigest(), ref=p['cache_ref'], source_ref=p['source_ref'],
            entity_versions=p['entity_versions'], as_of=p['as_of'], max_age_seconds=p['max_age_seconds'],
            expected_updated_at=self.profile.updated_at, actor=self.actor, selected_row_sha=request['expected_row_sha256'],
            record_pk=self.record.pk, source_identity_pk=self.source.pk, event_pk=self.event.pk, binding_pk=self.binding.pk,
            expected_binding_manifest_sha256=self.binding.binding_manifest_sha256, expected_record_updated_at=self.record.updated_at)
        linked = apply_career_record_link_from_cache(**link_request)
        self.assertEqual(linked['status'], 'applied', 'real original legal contract, no admission mock')
        self.assertEqual(linked['record_id'], result['record_id'])
        self.record.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.collected_start_count, self.profile.linked_race_event_count,
                          self.profile.unlinked_race_record_count), (1, 1, 0))
        linked_state = self.state()
        for field in after['HorseRaceRecord'][0].keys() - RECORD_CHANGED_FIELDS:
            self.assertEqual(after['HorseRaceRecord'][0][field], linked_state['HorseRaceRecord'][0][field], field)
        self.assertEqual(len(linked_state['HorseRaceRecord']), 1)
        self.assertEqual(len(linked_state['HorseProfileDataCandidate']), 2)
        self.assertEqual(len(linked_state['OperationLog']), 2)
        self.assertEqual(consumer.consume_reviewed_career_record(**request)['status'], 'already_applied')
        self.assertEqual(self.state(), linked_state)
        models.HorseRaceRecord.objects.filter(pk=self.record.pk).update(raw_payload={'tampered': True})
        self.blocked(request)

    def test_binding_private_baseline_identity_and_manual_lock_fail_closed(self):
        self.positive_rollback()
        request = self.request()
        self.blocked(dict(request, expected_review_sha256='0' * 64), 'review_sha_mismatch')
        self.blocked(dict(request, expected_row_sha256='1' * 64), 'selected_row_missing_or_ambiguous')
        self.blocked(dict(request, source_raw=request['source_raw'] + b' '), 'input_sha_mismatch')
        for edit in (
            lambda r: r.update(code_sha='0' * 40),
            lambda r: r.update(reviewer_id=self.actor.pk + 1000),
            lambda r: r['scope'].update(module='profile'),
            lambda r: r['scope'].update(event_id=self.event.pk),
            lambda r: r['scope'].update(selected_row_sha='0' * 64),
            lambda r: r['target'].update(profile_id=self.profile.pk + 1000),
            lambda r: r['target'].update(entity_version='wrong-version'),
            lambda r: r['target'].update(h02_plan_sha256='1' * 64),
            lambda r: r['inputs']['cache'].update(sha256='2' * 64),
            lambda r: r['before'].update(profile_baseline='2000-01-01T00:00:00+00:00'),
            lambda r: r['after'].update(race_name='Invented Name'),
            lambda r: r['module_reviews']['race_record'].update(approved_at=(NOW + timedelta(days=1)).isoformat()),
        ):
            with self.subTest(edit=edit):
                self.blocked(self.rereview(request, edit))
        for change in ({'is_staff': False}, {'is_active': False}):
            get_user_model().objects.filter(pk=self.actor.pk).update(**change)
            self.blocked(request, 'actor_not_staff')
            get_user_model().objects.filter(pk=self.actor.pk).update(is_staff=True, is_active=True)
        for change in ({'manual_lock_flags': {'race_record': True}}, {'review_status': 'published'},
                       {'hidden_at': NOW}, {'source_refs': {'horse_identity_verified_keys': ['hkjc:other']}},
                       {'updated_at': NOW + timedelta(days=1)}):
            old = models.HorseProfile.objects.get(pk=self.profile.pk)
            models.HorseProfile.objects.filter(pk=old.pk).update(**change)
            self.blocked(request)
            models.HorseProfile.objects.filter(pk=old.pk).update(**{k: getattr(old, k) for k in change})
        self.clock_mock.return_value = NOW + timedelta(days=3)
        self.blocked(request, 'source_expired')
        self.clock_mock.return_value = NOW
        values = self.prepare(request)['writer_payload']
        # Legacy preexistence is an actual existing record, not a fabricated receipt.
        horse_race_records.upsert_race_record(self.profile, values)
        self.blocked(request)

    def test_nonstarter_ignore_and_dry_run_do_not_consume(self):
        self.positive_rollback()
        # Shared cache coverage rejects these three inputs before the row gate.
        cases = (({'finish': 'WV'}, 'record_not_started_exact'),
                 ({'finish': 'WV', 'start_status': 'started'}, 'cache_validation'),
                 ({'finish': 'UNKNOWN'}, 'cache_validation'),
                 ({'race_date': '2025'}, 'cache_validation'))
        for changes, expected_reason in cases:
            source = deepcopy(self.payload)
            source['career']['records'][0].update(changes)
            source['career']['source_start_count'] = 0 if changes.get('finish') == 'WV' else 1
            with self.subTest(changes=changes):
                request = self.request(payload=source)
                before = self.state()
                try:
                    self.blocked(request, expected_reason)
                finally:
                    # Check all DB state even if the refusal-code assertion fails.
                    self.assertEqual(self.state(), before, 'refused input must have no DB side effects')
        ignored = self.request(decision='ignore')
        before = self.state()
        result = consumer.consume_reviewed_career_record(**ignored)
        self.assertEqual(result['status'], 'ignored')
        self.assertEqual(self.state(), before)
        request = self.request()
        calls = []
        writer = horse_race_records.upsert_race_record
        def actual_writer(*args, **kwargs):
            result = writer(*args, **kwargs)
            calls.append(result.record.pk)
            return result
        with patch('stable.services.horse_race_records.upsert_race_record', side_effect=actual_writer):
            result = consumer.consume_reviewed_career_record(**dict(request, dry_run=True))
        self.assertEqual(len(calls), 1, 'dry-run must reach real writer')
        self.assertEqual(result['status'], 'dry_run')
        self.assertFalse(result['committed'])
        self.assertIsNone(result['record_id'])
        self.assertIsNone(result['candidate_id'])
        self.assertEqual(self.state(), before)
        self.apply(request)  # neither ignore nor dry-run consumes key

    def test_writer_normalization_and_audit_failures_roll_back(self):
        self.positive_rollback()
        writer = horse_race_records.upsert_race_record
        for failure in ('writer', 'record_save', 'issues', 'candidate', 'log', 'expiry'):
            with self.subTest(failure=failure):
                request, before, calls = self.request(), self.state(), []
                def actual_then_fault(*args, **kwargs):
                    value = writer(*args, **kwargs)
                    calls.append(value.record.pk)
                    if failure == 'writer':
                        raise RuntimeError('a045 real writer post-write failure')
                    if failure == 'issues':
                        models.HorseRaceRecord.objects.filter(pk=value.record.pk).update(normalization_issues=['a045 issue'])
                        value.record.normalization_issues = []  # force actual DB readback, not just returned instance
                    if failure == 'expiry':
                        self.clock_mock.return_value = NOW + timedelta(days=3)
                    return value
                try:
                    with patch('stable.services.horse_race_records.upsert_race_record', side_effect=actual_then_fault):
                        if failure in ('candidate', 'log', 'record_save'):
                            model = {'candidate': models.HorseProfileDataCandidate, 'log': models.OperationLog,
                                     'record_save': models.HorseRaceRecord}[failure]
                            real_save = model.save
                            def save_then_fail(obj, *args, **kwargs):
                                real_save(obj, *args, **kwargs)
                                raise RuntimeError('a045 real save failure')
                            with patch.object(model, 'save', new=save_then_fail):
                                with self.assertRaisesRegex(RuntimeError, 'a045 real save failure'):
                                    consumer.consume_reviewed_career_record(**request)
                        elif failure == 'writer':
                            with self.assertRaisesRegex(RuntimeError, 'a045 real writer post-write failure'):
                                consumer.consume_reviewed_career_record(**request)
                        else:
                            self.blocked(request)
                    if failure != 'record_save':
                        self.assertEqual(len(calls), 1, 'failure must follow actual writer, not earlier input error')
                    self.assertEqual(self.state(), before)
                finally:
                    self.clock_mock.return_value = NOW

    def test_classification_preserves_explicit_source_attributes(self):
        self.positive_rollback()
        for grade, normalized, race_type in (('OP', 'OP', 'Open'), ('Listed', 'L', 'Listed'),
                                             ('NEWCOMER', 'NEWCOMER', 'Newcomer')):
            with self.subTest(grade=grade), transaction.atomic():
                source = deepcopy(self.payload)
                source['career']['records'][0].update(grade_text=grade, normalized_grade=normalized, race_type_text=race_type)
                request = self.request(payload=source)
                before = self.state()
                self.apply(request)
                self.record.refresh_from_db()
                self.assertEqual((self.record.grade_text, self.record.normalized_grade, self.record.race_type_text),
                                 (grade, normalized, race_type))
                self.assertNotEqual(self.record.normalized_grade, 'G1')
                self.assertEqual(self.record.eligibility_text, '3yo+')
                self.assertEqual(self.record.raw_payload, source['career']['records'][0])
                self.assertEqual(models.HorseRaceRecord.objects.filter(horse_profile=self.profile).count(), 1)
                transaction.set_rollback(True)
            self.assertEqual(self.state(), before)
            self.profile.refresh_from_db()

    def test_command_uses_private_frozen_files_and_postcommit_stdout_failure(self):
        self.positive_rollback()
        request = self.request()
        with tempfile.TemporaryDirectory(prefix='a045-input-') as source_root, tempfile.TemporaryDirectory(prefix='a045-review-') as review_root:
            for root in (source_root, review_root):
                Path(root).chmod(0o700)
            for path, raw in ((Path(source_root) / 'packet.json', request['packet']),
                              (Path(source_root) / 'source.json', request['source_raw']),
                              (Path(review_root) / 'reviewed.json', request['reviewed_raw'])):
                path.write_bytes(raw)
                path.chmod(0o600)
            options = dict(input_root=str(Path(source_root).resolve()), review_root=str(Path(review_root).resolve()),
                           review_input='reviewed.json', expected_reviewed_input_sha256=request['expected_review_sha256'],
                           expected_source_row_sha256=request['expected_row_sha256'], actor_id=self.actor.pk,
                           code_sha=request['code_sha'], commit=True)
            before = self.state()
            Path(review_root, 'reviewed.json').chmod(0o644)
            with self.assertRaises(CommandError):
                call_command('horse_career_record_from_review', stdout=io.StringIO(), **options)
            self.assertEqual(self.state(), before)
            Path(review_root, 'reviewed.json').chmod(0o600)
            class BrokenOutput(io.StringIO):
                def write(self, value):
                    raise BrokenPipeError('a045 aftercommit output')
            with self.assertRaisesRegex(BrokenPipeError, 'a045 aftercommit output'):
                call_command('horse_career_record_from_review', stdout=BrokenOutput(), **options)
            after = self.state()
            self.assertEqual(len(after['HorseRaceRecord']), 1)
            self.assertEqual(len(after['HorseProfileDataCandidate']), 1)
            self.assertEqual(len(after['OperationLog']), 1)
            output = io.StringIO()
            call_command('horse_career_record_from_review', stdout=output, **options)
            self.assertEqual(json.loads(output.getvalue())['status'], 'already_applied')
            self.assertEqual(self.state(), after)

    def _worker(self, fn, pids, label):
        close_old_connections()
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute("SET lock_timeout = '15s'")
                cursor.execute('SELECT pg_backend_pid()')
                pids[label] = cursor.fetchone()[0]
            return fn()
        finally:
            connections['default'].close()

    def _observe_block(self, pids, waiter, holder, future):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline and not future.done():
            if waiter in pids and holder in pids:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s', [pids[waiter]])
                    evidence = cursor.fetchone()
                if evidence and evidence[0] == 'Lock' and pids[holder] in evidence[1]:
                    print('A045_PG_LOCK_EVIDENCE ' + json.dumps({'holder': pids[holder], 'waiter': pids[waiter],
                          'wait_event_type': evidence[0], 'blocking_pids': evidence[1]}), flush=True)
                    return
            time.sleep(0.02)
        self.fail('must observe actual PG blocking; thread start or two reads is not evidence')

    def test_two_identical_requests_observe_real_lock_then_one_consumption(self):
        self.positive_rollback()
        request = self.request()
        pids, local = {}, threading.local()
        entered, release = threading.Event(), threading.Event()
        writer = horse_race_records.upsert_race_record
        def paused_writer(*args, **kwargs):
            if getattr(local, 'first', False):
                entered.set()
                if not release.wait(12):
                    raise AssertionError('a045 barrier timeout')
            return writer(*args, **kwargs)
        def invoke(first):
            local.first = first
            return consumer.consume_reviewed_career_record(**request)
        with patch('stable.services.horse_race_records.upsert_race_record', side_effect=paused_writer), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self._worker, lambda: invoke(True), pids, 'first')
            try:
                self.assertTrue(entered.wait(7), 'real writer entered under actual locks')
                second = pool.submit(self._worker, lambda: invoke(False), pids, 'second')
                self._observe_block(pids, 'second', 'first', second)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=18)['status'], 'applied')
            self.assertEqual(second.result(timeout=18)['status'], 'already_applied')
        self.assertEqual(models.HorseRaceRecord.objects.count(), 1)
        self.assertEqual(models.HorseProfileDataCandidate.objects.filter(source_name=consumer.SOURCE_ROLE).count(), 1)
        self.assertEqual(models.OperationLog.objects.count(), 1)

    def test_actor_revocation_serializes_consumption_and_replay(self):
        self.positive_rollback()
        for revoked_field in ('is_staff', 'is_active'):
            with self.subTest(revoked_field=revoked_field):
                get_user_model().objects.filter(pk=self.actor.pk).update(is_staff=True, is_active=True)
                request = self.request()
                # B actually commits revocation before A takes actor lock; actor argument stays stale.
                pids = {}
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(self._worker, lambda: get_user_model().objects.filter(pk=self.actor.pk).update(
                        **{revoked_field: False}), pids, 'revoke').result(timeout=10)
                self.blocked(request, 'actor_not_staff')
                get_user_model().objects.filter(pk=self.actor.pk).update(is_staff=True, is_active=True)
                entered, release = threading.Event(), threading.Event()
                writer = horse_race_records.upsert_race_record
                def paused_writer(*args, **kwargs):
                    entered.set()
                    if not release.wait(12):
                        raise AssertionError('a045 revocation barrier timeout')
                    return writer(*args, **kwargs)
                def revoke():
                    with transaction.atomic():
                        return get_user_model().objects.filter(pk=self.actor.pk).update(**{revoked_field: False})
                with patch('stable.services.horse_race_records.upsert_race_record', side_effect=paused_writer), ThreadPoolExecutor(max_workers=2) as pool:
                    apply = pool.submit(self._worker, lambda: consumer.consume_reviewed_career_record(**request), pids, 'apply')
                    try:
                        self.assertTrue(entered.wait(7), 'new consumer must hold actor lock before writer')
                        revocation = pool.submit(self._worker, revoke, pids, 'revoke')
                        self._observe_block(pids, 'revoke', 'apply', revocation)
                        self.assertFalse(revocation.done())
                    finally:
                        release.set()
                    self.assertEqual(apply.result(timeout=18)['status'], 'applied')
                    self.assertEqual(revocation.result(timeout=18), 1)
                current = get_user_model().objects.get(pk=self.actor.pk)
                self.assertFalse(getattr(current, revoked_field))
                self.blocked(request, 'actor_not_staff')
                self.assertEqual(models.HorseRaceRecord.objects.filter(horse_profile=self.profile).count(), 1)
                self.assertEqual(models.HorseProfileDataCandidate.objects.filter(profile=self.profile).count(), 1)
                self.assertEqual(models.OperationLog.objects.filter(target_type='horse_profile', target_id=str(self.profile.pk)).count(), 1)
                # Separate fixtures/keys for the next revoke variant, preserving real successful receipt.
                if revoked_field == 'is_staff':
                    self.term = models.TermEntry.objects.create(term_type='horse', source_language='en', source_ja='HARBOUR TEST')
                    self.profile = models.HorseProfile.objects.create(primary_term=self.term, original_name='HARBOUR TEST',
                        racing_region='hong_kong', source_refs={'horse_identity_verified_keys': ['hkjc:hk-002']})
                    self.payload = deepcopy(self.payload)
                    self.payload['source']['external_horse_id'] = 'HK-002'
                    self.payload['source']['url'] = 'https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK-002'
                    self.payload['career']['records'][0]['external_horse_id'] = 'HK-002'

    def test_actor_lock_wait_crossing_ttl_rejects_without_writes(self):
        self.positive_rollback()
        # Stop historical fixture clocks; this test proves actual elapsed UTC TTL.
        self.clock.stop()
        self.client_clock.stop()
        now = django_timezone.now().astimezone(timezone.utc)
        source = deepcopy(self.payload)
        source['source']['fetched_at'] = now.isoformat()
        source['career']['official_start_count_verified_at'] = now.isoformat()
        request = self.request(payload=source, now=now, max_age_seconds=6)
        self.prepare(request)
        before, pids = self.state(), {}
        holding, release = threading.Event(), threading.Event()
        def hold_actor():
            with transaction.atomic():
                actor = get_user_model().objects.select_for_update(no_key=True).get(pk=self.actor.pk)
                self.assertTrue(actor.is_active and actor.is_staff)
                holding.set()
                if not release.wait(12):
                    raise AssertionError('a045 TTL holder timeout')
                # No revocation: rejection must be TTL, not permissions.
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(self._worker, hold_actor, pids, 'holder')
            try:
                self.assertTrue(holding.wait(5))
                waiter = pool.submit(self._worker, lambda: consumer.consume_reviewed_career_record(**request), pids, 'waiter')
                self._observe_block(pids, 'waiter', 'holder', waiter)
                expiry = now + timedelta(seconds=6)
                deadline = time.monotonic() + 8
                while django_timezone.now() <= expiry and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreater(django_timezone.now(), expiry, 'must cross actual TTL before releasing lock')
                print('A045_TTL_WAIT_EVIDENCE ' + json.dumps({'source_time': now.isoformat(),
                      'expiry': expiry.isoformat(), 'release_time': django_timezone.now().isoformat()}), flush=True)
            finally:
                release.set()
            holder.result(timeout=18)
            try:
                response = waiter.result(timeout=18)
            except CommandError as exc:
                self.assertIn('source_expired', str(exc))
            else:
                self.assertEqual((response['status'], response['reason']), ('blocked', 'source_expired'))
        self.assertEqual(self.state(), before)
        self.assertTrue(get_user_model().objects.get(pk=self.actor.pk).is_staff)
