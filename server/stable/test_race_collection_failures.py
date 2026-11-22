"""错误语义、有限原件留存与重试；不访问外网。"""
from datetime import datetime, timedelta, timezone
from django.test import SimpleTestCase

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)

class RetrySemanticsTests(SimpleTestCase):
    def test_unknown_parser_status_does_not_retry_every_minute(self):
        from .services.race_priority import retry_delay
        self.assertGreaterEqual(retry_delay(priority=True, reason='hkjc_status_unknown', now=NOW), timedelta(minutes=15))

    def test_explicit_waits_and_unknown_errors_are_not_conflated(self):
        from .services import race_collection_failures as f
        expected = {'not_published': 'not_published', 'result_incomplete': 'incomplete',
                    'snapshot_lease_busy': 'waiting', 'jra_host_rate_limited': 'waiting',
                    'http_503': 'network', 'us_browser_http_429': 'network', 'http_403': 'access',
                    'linked_card_identity_mismatch': 'identity', 'hkjc_status_unknown': 'parser',
                    'some_new_failure': 'parser', 'network_disabled': 'configuration'}
        for reason, kind in expected.items():
            with self.subTest(reason=reason):
                self.assertEqual(f.category(reason), kind)
                self.assertEqual(f.is_fault(reason), kind not in {'waiting','not_published','incomplete'})
        self.assertEqual(f.safe_code('request failed with token=SECRET'), 'source_parse_failed')

    def test_network_parser_and_daily_quota_backoff_are_bounded(self):
        from .services import race_collection_failures as f
        from .services.race_priority import retry_delay
        self.assertEqual(f.delay('timeout', attempts=1), timedelta(minutes=5))
        self.assertEqual(f.delay('timeout', attempts=1000), timedelta(hours=1))
        self.assertEqual(f.delay('hkjc_status_unknown', attempts=1000), timedelta(hours=3))
        self.assertEqual(f.delay('hkjc_status_unknown', repeated=True), timedelta(hours=1))
        for priority in (False, True):
            self.assertEqual(retry_delay(priority=priority, reason='artifact_daily_requests_exceeded', now=NOW), timedelta(hours=12))

    def test_existing_us_uk_waiting_and_incomplete_codes_are_not_parser_faults(self):
        from .services import race_collection_failures as f
        from .services.uk_race_source import source_observation
        for payload, expected in [({'stage':'nominations'}, 'not_published'),
                                  ({'stage':'declared_card','roster_complete':False}, 'incomplete')]:
            try:
                source_observation(payload,route=None,now=NOW)
            except ValueError as exc:
                self.assertEqual(f.category(str(exc)),expected)
                self.assertFalse(f.is_fault(str(exc)))
            else:
                self.fail('non-final card was accepted')
        self.assertEqual(f.category('us_card_not_final'),'not_published')
        self.assertEqual(f.category('us_result_incomplete'),'incomplete')


import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.test import TestCase, override_settings
from .services import race_collection_failures as f


class EvidenceTests(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.settings_context = override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(self.root.name,))
        self.settings_context.enable()
        self.addCleanup(self.settings_context.disable)

    def capture(self, body='broken', *, at=NOW, previous=None, version='v1', reason='hkjc_status_unknown'):
        @f.attempt_scope
        def run():
            f.capture_document({'html': body, 'observed_at': at.isoformat()}, request_key='https://allowed.test/page?key=SECRET', provider='hkjc')
            return f.failure_state(previous, reason=reason, now=at, parser_version=version)
        return run()

    def test_raw_page_survives_replacement_and_repeated_fetch_deduplicates(self):
        first = self.capture()
        repeat = self.capture(at=NOW+timedelta(minutes=1), previous=first)
        self.assertEqual(first['evidence']['sha256'], repeat['evidence']['sha256'])
        self.assertEqual(repeat['attempts'], 2)
        self.assertTrue(repeat['repeated_content'])
        second = self.capture('corrected', previous=repeat)
        self.assertEqual(second['attempts'], 1)
        self.assertFalse(second['repeated_content'])
        self.assertEqual(len(list((Path(self.root.name)/'failures').glob('*.json'))), 2)
        body = (Path(self.root.name)/'failures'/(first['evidence']['sha256']+'.json')).read_bytes()
        self.assertNotIn(b'SECRET', body)
        self.assertEqual(json.loads(body)['documents'][0]['payload']['html'], 'broken')
        self.assertEqual((Path(self.root.name)/'failures').stat().st_mode & 0o777, 0o700)
        self.assertEqual((Path(self.root.name)/'failures'/(first['evidence']['sha256']+'.json')).stat().st_mode & 0o777, 0o600)

    def test_success_scope_and_next_attempt_do_not_leak_documents(self):
        @f.attempt_scope
        def run():
            f.capture_document({'html':'old'}, request_key='old')
            f.reset_capture()
            return f.failure_state({}, reason='timeout', now=NOW)
        self.assertEqual(run()['evidence']['status'], 'no_captured_response')
        self.assertEqual(f.evidence_payload()['documents'], [])
        self.assertFalse((Path(self.root.name)/'failures').exists())

    def test_mutation_cannot_rewrite_captured_response(self):
        @f.attempt_scope
        def run():
            payload = {'response': {'runners': ['old']}}
            f.capture_document(payload, request_key='x')
            payload['response']['runners'][0] = 'new'
            return f.evidence_payload()
        self.assertEqual(run()['documents'][0]['payload']['response']['runners'], ['old'])

    def test_capacity_age_and_corruption_are_explicit(self):
        with patch.object(f, 'MAX_ARCHIVES', 1):
            first = self.capture()
            second = self.capture('new', at=NOW+timedelta(seconds=1))
        directory = Path(self.root.name)/'failures'
        self.assertFalse((directory/(first['evidence']['sha256']+'.json')).exists())
        self.assertTrue((directory/(second['evidence']['sha256']+'.json')).exists())
        self.capture('later', at=NOW+timedelta(days=8))
        self.assertFalse((directory/(second['evidence']['sha256']+'.json')).exists())
        current = self.capture('corrupt', at=NOW+timedelta(days=8))
        path = directory/(current['evidence']['sha256']+'.json')
        path.write_text('tampered')
        import os
        os.utime(path, ((NOW+timedelta(days=8)).timestamp(),)*2)
        self.assertEqual(self.capture('corrupt', at=NOW+timedelta(days=8))['evidence']['status'], 'storage_unavailable')

    def test_symlink_and_busy_archive_never_follow_or_block(self):
        import fcntl
        with tempfile.TemporaryDirectory() as outside:
            directory=Path(self.root.name)/'failures'
            directory.symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.capture()['evidence']['status'], 'storage_unavailable')
            self.assertEqual(list(Path(outside).iterdir()), [])
            directory.unlink()
        self.capture()
        with (directory/'.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.capture('different')['evidence']['status'], 'storage_unavailable')

    def test_capture_limits_and_parser_version_reset_are_visible(self):
        @f.attempt_scope
        def run():
            f.capture_document({'html':'a'}, request_key='1')
            f.capture_document({'html':'b'}, request_key='2')
            return f.failure_state({}, reason='hkjc_status_unknown', now=NOW)
        with patch.object(f, 'MAX_DOCUMENTS', 1):
            state = run()
        self.assertEqual(state['evidence']['omitted_documents'], 1)
        first=self.capture()
        changed=self.capture(previous=first, version='v2')
        self.assertEqual(changed['attempts'], 1)
        self.assertFalse(changed['repeated_content'])
        with patch.object(f, 'MAX_CAPTURE_BYTES', 1):
            limited=self.capture('too large')
        self.assertEqual(limited['evidence']['status'], 'capture_limit')
        self.assertEqual(limited['evidence']['omitted_documents'], 1)

    def test_archive_byte_limit_and_pending_crash_recovery(self):
        with patch.object(f, 'MAX_ARCHIVE_BYTES', 10):
            self.assertEqual(self.capture()['evidence']['status'], 'capacity_limit')
        self.capture('first')
        directory=Path(self.root.name)/'failures'
        (directory/'.pending').write_text('crashed partial write')
        self.assertEqual(self.capture()['evidence']['status'], 'retained')
        self.assertFalse((directory/'.pending').exists())

    def test_snapshot_cache_hit_captures_without_network_and_keeps_versions(self):
        from .services import race_data_sync_providers as providers
        from types import SimpleNamespace
        @f.attempt_scope
        def run():
            with patch.object(providers, 'claim_snapshot_lease', return_value=SimpleNamespace(action='complete')), \
                 patch.object(providers.models.RaceDataSnapshotLease.objects, 'filter') as query, \
                 patch.object(providers, '_read_snapshot_artifact', return_value=({'html':'cached failed page'}, 'a'*64)):
                query.return_value.first.return_value=SimpleNamespace(manifest_data={})
                providers._get_or_fetch_shared_snapshot(provider='hkjc', region='hong_kong', scope_key='scope',
                    data_kind='result', registry_digest='a'*64, run_id='run', now=NOW, clock=lambda:NOW,
                    proposed_requests=1, sleeper=lambda _:None, fetcher=lambda:self.fail('network called'))
            return f.failure_state({}, reason='hkjc_status_unknown', now=NOW)
        state=run()
        self.assertEqual(state['evidence']['status'], 'retained')
        self.assertEqual(state['category'], 'parser')

    def test_process_cache_hit_after_claim_reset_keeps_the_response(self):
        @f.attempt_scope
        def run():
            cache=f.ResponseCache(provider='jra',region='japan_jra')
            cache['https://test/page']='same raw page'
            first=cache['https://test/page']
            f.reset_capture()
            second=cache['https://test/page']
            self.assertEqual(first,second)
            return f.failure_state({},reason='jra_header_identity_missing',now=NOW)
        state=run()
        self.assertEqual(state['evidence']['status'],'retained')
        self.assertEqual(f.inspect_evidence(state['evidence']['sha256']),'verified')

    def test_recovery_resets_consecutive_content_and_category_attempts(self):
        first=self.capture()
        failed=self.capture(previous=first)
        failed['resolved_at']=NOW.isoformat()
        fresh=self.capture(previous=failed)
        self.assertEqual(fresh['attempts'],1)
        self.assertEqual(fresh['category_attempts'],1)
        self.assertFalse(fresh['repeated_content'])

    def test_legacy_tra_snapshot_shapes_are_preserved(self):
        for payload in [{'racecards':[{'race_id':'r1'}]}, {'results':[{'race_id':'r1'}], 'page_sha256':['a'*64]}]:
            @f.attempt_scope
            def run():
                @f.capture_snapshot
                def snapshot(**kwargs):
                    return payload, 'a'*64
                snapshot(scope_key='test',provider='the_racing_api',region='united_kingdom',registry_digest='a'*64)
                return f.failure_state({},reason='provider_response_invalid',now=NOW)
            state=run()
            self.assertEqual(state['evidence']['status'],'retained')
            stored=json.loads((Path(self.root.name)/'failures'/(state['evidence']['sha256']+'.json')).read_text())
            self.assertEqual(stored['documents'][0]['payload']['response'],payload)

    def test_disk_low_water_refuses_new_file_but_keeps_existing_evidence(self):
        from types import SimpleNamespace
        first=self.capture()
        with patch.object(f.os,'fstatvfs',return_value=SimpleNamespace(f_bavail=0,f_frsize=4096)):
            self.assertEqual(self.capture('new body')['evidence']['status'],'disk_low')
            self.assertEqual(self.capture()['evidence']['status'],'retained')
        self.assertEqual(f.inspect_evidence(first['evidence']['sha256']),'verified')


from . import test_race_multisource_enrollment as enrollment_fixtures
from .test_race_multisource_identity import NOW as CLAIM_NOW

@override_settings(**enrollment_fixtures.MultisourceClaimTests._overridden_settings)
class ClaimFailureTests(TestCase):
    def setUp(self):
        enrollment_fixtures.MultisourceClaimTests.setUp(self)

    def claim(self):
        return enrollment_fixtures.MultisourceClaimTests.claim(self)[0]

    def checkpoint(self):
        from . import models
        return models.RaceEventLiveProviderCheckpoint.objects.get(tracking__event=self.event, data_kind='result', source_key='jra')

    def test_waiting_does_not_increment_failure_or_success_or_publish(self):
        from .services.race_data_sync_control import finish_multisource_claim
        claim=self.claim()
        finish_multisource_claim(claim=claim, now=CLAIM_NOW, success=False, reason_code='snapshot_lease_busy')
        checkpoint=self.checkpoint()
        self.assertEqual(checkpoint.consecutive_failures, 0)
        self.assertIsNone(checkpoint.last_success_at)
        self.assertEqual(checkpoint.failure_diagnostic['category'], 'waiting')
        self.assertGreater(checkpoint.next_poll_at, CLAIM_NOW)
        checkpoint.tracking.refresh_from_db()
        self.assertEqual(checkpoint.tracking.consecutive_failures, 0)
        self.assertFalse(self.event.results.exists())

    def test_fault_retry_after_and_stale_claim_guard_remain_enforced(self):
        from .services.race_data_sync_control import finish_multisource_claim
        claim=self.claim()
        finish_multisource_claim(claim=claim, now=CLAIM_NOW, success=False, reason_code='identity_conflict',
                                retry_at=CLAIM_NOW+timedelta(hours=2), parser_version='v1')
        checkpoint=self.checkpoint()
        self.assertEqual(checkpoint.consecutive_failures, 1)
        self.assertEqual(checkpoint.next_poll_at, CLAIM_NOW+timedelta(hours=2))
        self.assertTrue(checkpoint.failure_diagnostic['needs_attention'])
        before=checkpoint.failure_diagnostic
        finish_multisource_claim(claim=claim, now=CLAIM_NOW, success=True)
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.failure_diagnostic, before)
        self.assertIsNone(checkpoint.last_success_at)
        self.assertFalse(self.event.results.exists())

    def test_valid_success_marks_last_failure_resolved(self):
        from .services.race_data_sync_control import finish_multisource_claim
        checkpoint=self.checkpoint()
        checkpoint.failure_diagnostic=f.failure_state({}, reason='timeout', now=CLAIM_NOW-timedelta(hours=1))
        checkpoint.save()
        finish_multisource_claim(claim=self.claim(), now=CLAIM_NOW, success=True)
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.failure_diagnostic['resolved_at'], CLAIM_NOW.isoformat())
        self.assertEqual(checkpoint.failure_diagnostic['reason'], 'timeout')
        self.assertEqual(checkpoint.consecutive_failures, 0)

    def test_old_image_insert_can_omit_new_diagnostic_column(self):
        from django.db import connection
        from . import models
        row=self.checkpoint()
        fields=[field for field in row._meta.concrete_fields if field.name not in {'id','failure_diagnostic'}]
        values=[getattr(row, field.attname) if field.name!='source_key' else 'old_image_source' for field in fields]
        columns=', '.join(connection.ops.quote_name(field.column) for field in fields)
        placeholders=', '.join(['%s']*len(fields))
        with connection.cursor() as cursor:
            cursor.execute(f'INSERT INTO stable_raceeventliveprovidercheckpoint ({columns}) VALUES ({placeholders})', values)
        old=models.RaceEventLiveProviderCheckpoint.objects.get(tracking=row.tracking, source_key='old_image_source')
        self.assertEqual(old.failure_diagnostic, {})


from .test_race_pre_race import FLAGS as PRE_FLAGS, NOW as PRE_NOW, event as pre_event

@override_settings(**PRE_FLAGS)
class PreRaceFailureTests(TestCase):
    def test_waiting_and_missing_sources_never_forge_success(self):
        from .services import race_pre_race as pre
        e=pre_event()
        claim=pre.claim_pre_race(event_id=e.pk, source=pre.JRA, now=PRE_NOW)
        pre.finish_pre_race(claim, now=PRE_NOW, outcome_reason='not_published')
        e.refresh_from_db()
        state=pre._state(e, pre.JRA)
        self.assertEqual(state['failures'], 0)
        self.assertNotIn('last_success_at', state)
        self.assertEqual(state['failure_diagnostic']['category'], 'not_published')
        self.assertEqual(state['lease_token'], '')
        self.assertFalse(e.runners.exists())

    def test_expired_claim_cannot_overwrite_failure_diagnostic(self):
        from .services import race_pre_race as pre
        e=pre_event()
        old=pre.claim_pre_race(event_id=e.pk, source=pre.JRA, now=PRE_NOW)
        later=PRE_NOW+timedelta(seconds=121)
        new=pre.claim_pre_race(event_id=e.pk, source=pre.JRA, now=later)
        pre.finish_pre_race(new, now=later, reason='jra_pre_race_identity_mismatch')
        self.assertFalse(pre.finish_pre_race(old, now=later, reason='timeout'))
        e.refresh_from_db()
        self.assertEqual(pre._state(e,pre.JRA)['failure_diagnostic']['category'], 'identity')
        self.assertFalse(e.runners.exists())

    def test_diagnostic_command_is_read_only_and_reports_current_evidence(self):
        from django.core.management import call_command
        from io import StringIO
        from .services import race_pre_race as pre
        e=pre_event()
        claim=pre.claim_pre_race(event_id=e.pk, source=pre.JRA, now=PRE_NOW)
        pre.finish_pre_race(claim, now=PRE_NOW, reason='timeout')
        e.refresh_from_db()
        original=e.source_refs
        output=StringIO()
        call_command('inspect_race_collection_failures', event_id=e.pk, stdout=output)
        report=json.loads(output.getvalue())
        self.assertEqual(report['diagnostics'][0]['diagnostic']['category'], 'network')
        self.assertEqual(report['diagnostics'][0]['evidence_now'], 'not_recorded')
        e.refresh_from_db()
        self.assertEqual(e.source_refs, original)


@override_settings(**enrollment_fixtures.MultisourceClaimTests._overridden_settings)
class AttemptIntegrationTests(TestCase):
    def setUp(self):
        enrollment_fixtures.MultisourceClaimTests.setUp(self)
        self.root=tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        settings=override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(self.root.name,), RACE_DATA_SYNC_ALLOW_NETWORK=True,
                                   RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=True)
        settings.enable()
        self.addCleanup(settings.disable)
        clock=patch('django.utils.timezone.now', return_value=CLAIM_NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def broken_fetch(self, **kwargs):
        f.capture_document({'html':'official page with unknown status'}, request_key='test-page',
                           provider=kwargs['route'].provider, registry_digest=kwargs['route'].digest)
        error=ValueError('hkjc_status_unknown')
        error.retry_after=CLAIM_NOW+timedelta(hours=7)
        raise error

    def test_worker_releases_claim_but_preserves_failed_response_and_identity_gate(self):
        from .services.race_data_source_adapters import run_multisource_claim
        from . import models
        claim=enrollment_fixtures.MultisourceClaimTests.claim(self)[0]
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation', side_effect=self.broken_fetch):
            result=run_multisource_claim(claim=claim, now=CLAIM_NOW)
        self.assertFalse(result['processed'])
        row=models.RaceEventLiveProviderCheckpoint.objects.get(tracking__event=self.event, data_kind='result', source_key='jra')
        self.assertEqual(row.next_poll_at, CLAIM_NOW+timedelta(hours=7))
        self.assertEqual(row.failure_diagnostic['evidence']['status'], 'retained')
        self.assertEqual(f.inspect_evidence(row.failure_diagnostic['evidence']['sha256']), 'verified')
        self.assertEqual(row.failure_diagnostic['evidence']['location'][-1]['module'], 'race_data_source_adapters.py')
        self.assertEqual(row.tracking.active_attempt_token, '')
        self.assertFalse(self.event.results.exists())
        self.assertEqual(f.evidence_payload()['documents'], [])

    def test_discovery_retains_separate_route_diagnostics_and_retry_after(self):
        from .services.race_data_sync_enrollment import discover_multisource_events
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation', side_effect=self.broken_fetch) as fetch:
            first=discover_multisource_events(now=CLAIM_NOW, policy=self.policy)
            second=discover_multisource_events(now=CLAIM_NOW, policy=self.policy)
        self.assertEqual(first['attempted'], 1)
        self.assertEqual(second['attempted'], 0)
        self.assertEqual(fetch.call_count, 2)
        self.event.refresh_from_db()
        state=self.event.source_refs['source_discovery_v2']
        self.assertEqual(state['next_poll_at'], (CLAIM_NOW+timedelta(hours=7)).isoformat())
        self.assertEqual(len(state['failure_diagnostics']), 2)
        for diagnostic in state['failure_diagnostics'].values():
            self.assertEqual(diagnostic['category'], 'parser')
            self.assertEqual(f.inspect_evidence(diagnostic['evidence']['sha256']), 'verified')
        self.assertFalse(self.event.results.exists())

    def test_healthy_discovery_route_does_not_cancel_other_route_backoff(self):
        from types import SimpleNamespace
        from .services.race_data_sync_enrollment import discover_multisource_events
        calls=[]
        def fetch(**kwargs):
            provider=kwargs['route'].provider
            calls.append(provider)
            f.capture_document({'html':'broken' if provider=='alternate' else 'good'},request_key=provider)
            if provider=='alternate':
                raise ValueError('hkjc_status_unknown')
            return {}
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation',side_effect=fetch),              patch('stable.services.race_data_sync_enrollment.attach_multisource_observation',return_value=SimpleNamespace(action='replay',reason_code='')):
            first=discover_multisource_events(now=CLAIM_NOW,policy=self.policy)
            self.assertEqual(first['attempted'],1)
            later=CLAIM_NOW+timedelta(minutes=10)
            with patch('django.utils.timezone.now',return_value=later):
                discover_multisource_events(now=later,policy=self.policy)
        self.assertEqual(calls.count('jra'),2)
        self.assertEqual(calls.count('alternate'),1)
        self.event.refresh_from_db()
        route=next(r for r in self.policy.routes if r.provider=='alternate')
        diagnostic=self.event.source_refs['source_discovery_v2']['failure_diagnostics'][route.digest]
        self.assertEqual(diagnostic['retry_not_before'],(CLAIM_NOW+timedelta(minutes=15)).isoformat())
        self.assertFalse(self.event.results.exists())


class TransportEvidenceTests(SimpleTestCase):
    def test_invalid_json_and_http_503_retain_bytes_and_differ_in_category(self):
        from types import SimpleNamespace
        from .services import race_data_sync_providers as p
        from .services.race_live_source_proof import RaceLiveProofHttpResponse
        import base64
        with tempfile.TemporaryDirectory() as root, override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(root,)):
            for status, reason, kind in [(200,'provider_response_invalid','parser'), (503,'http_503','network')]:
                @f.attempt_scope
                def run():
                    response=RaceLiveProofHttpResponse(status_code=status, content_type='application/json', body=b'{broken', elapsed_ms=1)
                    with patch.object(p,'reserve_race_live_host_request',return_value=SimpleNamespace(reserved=True,reservation_version=1)), \
                         patch.object(p,'record_race_live_host_outcome',return_value=SimpleNamespace(recorded=True)):
                        try:
                            p._fetch_json(transport=lambda **kw:response, endpoint_name='test', url='https://api.theracingapi.com/test',
                                          username='SECRET', password='PASSWORD', now=NOW, clock=lambda:NOW, sleeper=lambda _:None)
                        except p._ProviderSyncError as exc:
                            self.assertEqual(exc.reason_code, reason)
                            return f.failure_state({},reason=exc.reason_code,now=NOW)
                        self.fail('invalid response accepted')
                value=run()
                self.assertEqual(value['category'],kind)
                raw=(Path(root)/'failures'/(value['evidence']['sha256']+'.json')).read_text()
                self.assertNotIn('SECRET',raw)
                self.assertNotIn('PASSWORD',raw)
                payload=json.loads(raw)
                self.assertEqual(base64.b64decode(payload['documents'][0]['payload']['bytes_b64']),b'{broken')


from . import test_race_data_sync_providers as tra_fixtures

@override_settings(**tra_fixtures.TheRacingApiDataSyncAdapterTests._overridden_settings)
class LegacyExactFailureTests(TestCase):
    setUp = tra_fixtures.TheRacingApiDataSyncAdapterTests.setUp

    def test_exact_result_parser_failure_retains_response_and_location(self):
        from .services import race_data_sync_providers as provider
        from .services.race_live_source_proof import RaceLiveProofHttpResponse
        now=tra_fixtures.NOW
        self.event.local_date=(now-timedelta(days=1)).date()
        self.event.save(update_fields=('local_date',))
        payload={'race_id':self.source.external_race_id, 'runners':'invalid-list'}
        calls=[]
        def transport(**kwargs):
            calls.append(kwargs['endpoint_name'])
            return RaceLiveProofHttpResponse(status_code=200,content_type='application/json',
                body=json.dumps(payload).encode(),elapsed_ms=1)
        @f.attempt_scope
        def run():
            outcome=provider.run_the_racing_api_data_sync(event_id=self.event.pk,data_kinds=('result',),
                route=self.route,now=now,task_id='offline-exact',run_id='offline-exact',
                transport=transport,clock=lambda:now,sleeper=lambda _:None)
            return outcome, f.failure_state({},reason=outcome.reason_code,now=now)
        with patch.object(provider,'read_the_racing_api_automation_registry',return_value=(self.registry,tra_fixtures.SHA)), \
             patch.object(provider,'_read_secret',return_value=('dummy-user','dummy-secret')):
            outcome,diagnostic=run()
        self.assertEqual(outcome.reason_code,'provider_execution_failed')
        self.assertFalse(outcome.success)
        self.assertEqual(calls,['result_by_id'])
        self.assertEqual(diagnostic['evidence']['status'],'retained')
        self.assertTrue(diagnostic['evidence']['location'])
        archive=json.loads((Path(self.artifact_dir.name)/'failures'/(diagnostic['evidence']['sha256']+'.json')).read_text())
        self.assertEqual(archive['documents'][0]['payload']['response'],payload)
        self.assertNotIn('dummy-secret',json.dumps(archive))
        self.assertFalse(self.event.results.exists())
        self.assertEqual(f.evidence_payload()['documents'],[])
