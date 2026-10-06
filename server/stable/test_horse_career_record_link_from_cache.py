"""A034 五组业务 RED：只在 ROOT 分配的隔离 PostgreSQL 执行。"""
import hashlib
import json
import tempfile
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings

from stable import models
from stable.services import horse_race_records
from stable.services.horse_career_record_link_from_cache import apply_career_record_link_from_cache
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


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class CareerRecordLinkFromCacheTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor != 'postgresql':
            raise AssertionError('A034 requires ROOT-allocated isolated PostgreSQL')
        self.clock = patch('django.utils.timezone.now', return_value=NOW)
        self.clock_mock = self.clock.start()
        self.addCleanup(self.clock.stop)
        client_clock = patch('stable.services.p0_horse_completion_source_clients.datetime', FrozenDateTime)
        client_clock.start()
        self.addCleanup(client_clock.stop)
        self.actor = get_user_model().objects.create_user(username='a034-synthetic-actor')
        self.term = models.TermEntry.objects.create(
            term_type='horse', source_language='en', source_ja='HARBOUR TEST',
            target_zh='', racing_region='hong_kong')
        self.profile = models.HorseProfile.objects.create(
            primary_term=self.term, original_name='HARBOUR TEST', racing_region='hong_kong',
            source_refs={'horse_identity_verified_keys': ['hkjc:hk-001']})
        self.event = models.RaceEvent.objects.create(
            year=2025, edition_year=2025, slug='a034-synthetic-class-two',
            original_name='Class 2 Handicap', country_region='hong_kong',
            racecourse='Sha Tin', local_date=date(2025, 12, 7), timezone_name='Asia/Hong_Kong')
        self.payload = json.loads(FIXTURE.read_bytes())
        selected = self.payload['career']['records'][0]
        # Only setup uses the existing writer; this does not authorize service writes.
        values = _normalize_race_record(selected)
        values.update(race_region='hong_kong', surface='turf', raw_payload=deepcopy(selected))
        self.record = horse_race_records.upsert_race_record(self.profile, values).record
        # Eligibility is not a managed field in the legacy writer; prepare the
        # existing synthetic row explicitly, then run the real normalizer.
        self.record.eligibility_text = selected["eligibility_text"]
        self.record.save(update_fields=["eligibility_text"])
        horse_race_records._normalize_race_record(self.record)
        self.assertEqual(self.record.normalization_issues, [], 'fixture normalization must be valid before RED')
        self.assertIsNone(self.record.event_id)
        self.assertEqual(self.record.start_status, 'started')
        self.temp = tempfile.TemporaryDirectory(prefix='a034-policy-')
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
        self.policy_payload = dict(schema_version=3, policy_id='a034-synthetic-only',
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
            guard = patch(target, side_effect=AssertionError('A034 producer/public/binding mutation forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def request(self, *, payload=None, version='a034-v1'):
        payload = deepcopy(self.payload if payload is None else payload)
        raw = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode()
        digest = hashlib.sha256(raw).hexdigest()
        snapshot = document()
        snapshot.update(events=[event(region='hong_kong')],
                        participations=[row(horse_key='hkjc:HK-001', birth_year=2020)],
                        identities=[identity('hkjc:HK-001', profile=self.profile.pk)])
        cache = adapt_hkjc_source_cache(raw, expected_sha256=digest, ref='cache:a034', source_ref='fixture:a034')
        versions = {f'profile:{self.profile.pk}': version}
        plan = plan_cache_reuse(snapshot, [cache], versions, as_of=NOW.isoformat(), max_age_seconds=78 * 86400)
        self.assertEqual(plan['decisions'][0]['status'], 'reusable', 'H02 prerequisite before business RED')
        self.profile.refresh_from_db()
        self.record.refresh_from_db()
        return dict(snapshot=snapshot, candidate=deepcopy(plan['candidates'][0]), raw_bytes=raw,
                    expected_sha256=digest, ref='cache:a034', source_ref='fixture:a034',
                    entity_versions=versions, as_of=NOW.isoformat(), max_age_seconds=78 * 86400,
                    expected_updated_at=self.profile.updated_at, actor=self.actor,
                    selected_row_sha=_sha(payload['career']['records'][0]), record_pk=self.record.pk,
                    source_identity_pk=self.source.pk, event_pk=self.event.pk, binding_pk=self.binding.pk,
                    expected_binding_manifest_sha256=self.binding.binding_manifest_sha256,
                    expected_record_updated_at=self.record.updated_at)

    def state(self):
        # All owned and downstream business tables, including seed data/counts.
        tables = (models.HorseProfile, models.HorseRaceRecord, models.HorseProfileDataCandidate,
                  models.OperationLog, models.TermEntry, models.RaceEvent, models.RaceEventResult,
                  models.RaceResultSourceIdentity, models.RaceDataSyncEnrollment, models.RaceDataSyncSourceBinding)
        return {table.__name__: deepcopy(list(table.objects.order_by('pk').values())) for table in tables}

    def assert_linked(self, request=None):
        request = request or self.request()
        self.clock_mock.return_value = NOW + timedelta(seconds=1)
        response = apply_career_record_link_from_cache(**request)
        self.record.refresh_from_db()
        # Designated business RED: imported complete-signature stub leaves actual FK NULL.
        self.assertEqual(self.record.event_id, self.event.pk, 'H03 must actually link the existing record')
        self.assertEqual(response['status'], 'applied')
        self.assertFalse(response['published'])
        return response

    def assert_positive_then_rollback(self):
        with transaction.atomic():
            self.assert_linked()
            transaction.set_rollback(True)
        self.profile.refresh_from_db()
        self.record.refresh_from_db()
        self.clock_mock.return_value = NOW

    def assert_blocked_zero_write(self, request):
        before = self.state()
        result = apply_career_record_link_from_cache(**request)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.state(), before)

    def test_existing_record_link_preserves_facts_and_only_derives_counters(self):
        request = self.request()
        before = self.state()
        self.assert_linked(request)
        after = self.state()
        old, new = before['HorseRaceRecord'][0], after['HorseRaceRecord'][0]
        allowed = {'event_id', 'canonical_race_key', 'updated_at', 'normalized_at',
                   'normalization_input_sha256', 'normalization_version', 'normalization_issues'}
        for field in old.keys() - allowed:
            self.assertEqual(new[field], old[field], field)
        self.assertEqual(len(after['HorseRaceRecord']), len(before['HorseRaceRecord']))
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.collected_start_count, self.profile.linked_race_event_count,
                          self.profile.unlinked_race_record_count), (1, 1, 0))
        for field in ('official_or_source_start_count', 'official_start_count_source',
                      'career_record_authority_status', 'published_at', 'display_name_zh', 'source_refs'):
            self.assertEqual(after['HorseProfile'][0][field], before['HorseProfile'][0][field])
        for name in ('TermEntry', 'RaceEvent', 'RaceEventResult', 'RaceResultSourceIdentity',
                     'RaceDataSyncEnrollment', 'RaceDataSyncSourceBinding'):
            self.assertEqual(after[name], before[name], name)
        self.assertEqual(len(after['HorseProfileDataCandidate']), len(before['HorseProfileDataCandidate']) + 1)
        self.assertEqual(len(after['OperationLog']), len(before['OperationLog']) + 1)
        candidate = models.HorseProfileDataCandidate.objects.get(profile=self.profile)
        self.assertEqual(candidate.status, models.HorseProfileCandidateStatus.APPLIED)
        self.assertEqual(candidate.module, models.HorseProfileModule.RACE_RECORD)
        self.assertEqual(candidate.confidence, 0)
        json.dumps(candidate.diff_payload, allow_nan=False)

    def test_original_baseline_replay_and_changed_binding_input(self):
        request = self.request()
        self.assert_linked(request)
        before = self.state()
        self.assertNotEqual(models.HorseProfile.objects.get(pk=self.profile.pk).updated_at, request['expected_updated_at'])
        replay = apply_career_record_link_from_cache(**request)
        self.assertEqual(replay['status'], 'already_applied')
        self.assertEqual(self.state(), before)
        changed = dict(request, expected_binding_manifest_sha256='0' * 64)
        self.assert_blocked_zero_write(changed)
        changed = dict(request, selected_row_sha='1' * 64)
        self.assert_blocked_zero_write(changed)

    def test_identity_contract_expiration_and_revocation_fail_closed(self):
        self.assert_positive_then_rollback()
        cases = [
            (self.source, {'automation_allowed': False}),
            (self.source, {'proof_network_allowed': False}),
            (self.source, {'review_status': 'pending'}),
            (self.source, {'terms_status': 'unknown'}),
            (self.source, {'valid_until': NOW}),
            (self.source, {'registry_digest': '0' * 64}),
            (self.source, {'identity_fields': {'identity_invalidated': True}}),
            (self.source, {'identity_fields': {'publication_revoked': True}}),
            (self.source, {'external_race_id': 'OTHER-SLOT'}),
            (self.source, {'identity_fields': {'multisource_v2': {**self.source.identity_fields['multisource_v2'], 'race_number': '8'}}}),
            (self.source, {'identity_fields': {'multisource_v2': {**self.source.identity_fields['multisource_v2'], 'operator': 'OTHER'}}}),
            (self.source, {'identity_namespace': 'OTHER'}),
            (self.binding, {'state': 'quarantined'}),
            (self.binding, {'valid_until': NOW}),
            (self.binding, {'registry_schema_version': 2}),
            (self.binding, {'binding_manifest': {**self.binding.binding_manifest, 'identity_evidence': {}}}),
            (self.binding, {'identity_evidence_sha256': '0' * 64}),
            (self.enrollment, {'state': 'paused'}),
            (self.enrollment, {'retired_at': NOW}),
            (self.event, {'edition_year': 2026}),
            (self.event, {'local_date': date(2025, 12, 8)}),
            (self.profile, {'manual_lock_flags': {models.HorseProfileModule.RACE_RECORD: True}}),
            (self.profile, {'review_status': models.HorseProfileStatus.PUBLISHED}),
            (self.profile, {'hidden_at': NOW}),
            (self.profile, {'source_refs': {'horse_identity_verified_keys': ['hkjc:OTHER']}}),
        ]
        for target, changes in cases:
            with self.subTest(model=type(target).__name__, changes=changes), transaction.atomic():
                type(target).objects.filter(pk=target.pk).update(**changes)
                # Original valid-cache as_of cannot bypass the service's live contract time.
                self.assert_blocked_zero_write(self.request())
                transaction.set_rollback(True)
        for field in ('external_race_id', 'venue_key', 'race_number', 'external_horse_id'):
            with self.subTest(missing=field):
                payload = deepcopy(self.payload)
                payload['career']['records'][0].pop(field)
                self.assert_blocked_zero_write(self.request(payload=payload))
        with patch('django.utils.timezone.now', return_value=NOW + timedelta(days=2)):
            self.assert_blocked_zero_write(self.request())
        original = self.policy_path.read_bytes()
        try:
            self.policy_path.write_bytes(_canonical_json_bytes({**self.policy_payload, 'policy_id': 'tampered'}))
            self.assert_blocked_zero_write(self.request())
        finally:
            self.policy_path.write_bytes(original)

    def test_post_write_failures_issues_and_expiration_roll_back_all(self):
        self.assert_positive_then_rollback()
        real_writer = horse_race_records.upsert_race_record
        for failure in ('writer', 'candidate', 'log', 'memory_issue', 'persistent_issue', 'expiry'):
            with self.subTest(failure=failure):
                request = self.request()
                before = self.state()
                calls = []
                def write_then_fault(*args, **kwargs):
                    value = real_writer(*args, **kwargs)
                    calls.append(value.record.pk)
                    if failure == 'writer':
                        raise RuntimeError('a034 synthetic post-write failure')
                    if failure == 'memory_issue':
                        value.record.normalization_issues = ['a034 synthetic swallowed issue']
                    if failure == 'persistent_issue':
                        models.HorseRaceRecord.objects.filter(pk=value.record.pk).update(normalization_issues=['a034 synthetic swallowed issue'])
                        value.record.normalization_issues = []
                    if failure == 'expiry':
                        self.clock_mock.return_value = NOW + timedelta(days=2)
                    return value
                try:
                    with patch('stable.services.horse_race_records.upsert_race_record', side_effect=write_then_fault):
                        if failure in ('candidate', 'log'):
                            model = models.HorseProfileDataCandidate if failure == 'candidate' else models.OperationLog
                            with patch.object(model, 'save', side_effect=RuntimeError('a034 synthetic post-write failure')):
                                with self.assertRaisesRegex(RuntimeError, 'a034 synthetic post-write failure'):
                                    apply_career_record_link_from_cache(**request)
                        elif failure == 'writer':
                            with self.assertRaisesRegex(RuntimeError, 'a034 synthetic post-write failure'):
                                apply_career_record_link_from_cache(**request)
                        else:
                            response = apply_career_record_link_from_cache(**request)
                            self.assertEqual(response['status'], 'blocked')
                    self.assertEqual(calls, [self.record.pk], 'fault must follow actual existing writer change')
                    self.assertEqual(self.state(), before)
                finally:
                    self.clock_mock.return_value = NOW

    def test_two_identical_requests_observe_pg_lock_then_one_consumption(self):
        self.assert_positive_then_rollback()
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections, connections
        request = self.request()
        self.clock_mock.return_value = NOW + timedelta(seconds=1)
        first_in_writer, release_first = threading.Event(), threading.Event()
        local = threading.local()
        pids = {True: [], False: []}
        real_writer = horse_race_records.upsert_race_record
        before = self.state()
        def paused_writer(*args, **kwargs):
            if getattr(local, 'first', False):
                first_in_writer.set()
                if not release_first.wait(10):
                    raise AssertionError('A034 writer release timeout')
            return real_writer(*args, **kwargs)
        def invoke(first):
            close_old_connections()
            local.first = first
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids[first].append(cursor.fetchone()[0])
                return apply_career_record_link_from_cache(**request)
            finally:
                connections['default'].close()
        with patch('stable.services.horse_race_records.upsert_race_record', side_effect=paused_writer):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(invoke, True)
                try:
                    self.assertTrue(first_in_writer.wait(5), 'must enter writer under profile lock')
                    second = pool.submit(invoke, False)
                    deadline = time.monotonic() + 5
                    seen = False
                    while time.monotonic() < deadline and not second.done():
                        if pids[False]:
                            with connection.cursor() as cursor:
                                cursor.execute('SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s', [pids[False][0]])
                                lock = cursor.fetchone()
                            if lock and lock[0] == 'Lock':
                                self.assertIn(pids[True][0], lock[1])
                                print('A034_PG_LOCK_EVIDENCE ' + json.dumps(dict(first_pid=pids[True][0], second_pid=pids[False][0], wait_event_type=lock[0], blocking_pids=lock[1])), flush=True)
                                seen = True
                                break
                        time.sleep(0.02)
                    self.assertTrue(seen, 'must observe actual PG lock and blocker')
                finally:
                    release_first.set()
                self.assertEqual(first.result(timeout=10)['status'], 'applied')
                self.assertEqual(second.result(timeout=10)['status'], 'already_applied')
        self.record.refresh_from_db()
        self.assertEqual(self.record.event_id, self.event.pk)
        after = self.state()
        self.assertEqual(len(after['HorseProfileDataCandidate']), len(before['HorseProfileDataCandidate']) + 1)
        self.assertEqual(len(after['OperationLog']), len(before['OperationLog']) + 1)
