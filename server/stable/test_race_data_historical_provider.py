"""TRA单场结果底层提取回归；所有网络及额度读写均mock。"""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from django.utils import timezone
from stable.services import race_data_sync_providers as provider


class HistoricalResultFetchTests(SimpleTestCase):
    def call_fetch(self):
        return provider._fetch_the_racing_api_result_by_id(
            registry={}, source=SimpleNamespace(source_key='the_racing_api',region_code='united_kingdom',external_race_id='race_123'),
            provider_region='gb',transport=object(),username='dummy',password='dummy',
            now=timezone.now(),clock=timezone.now,sleeper=lambda _:None)

    def test_exhausted_daily_capacity_never_calls_transport(self):
        with patch.object(provider,'reserve_race_data_transport_capacity',return_value=SimpleNamespace(allowed=False,reason_code='budget_exhausted')),patch.object(provider,'_fetch_json') as fetch:
            with self.assertRaises(provider._ProviderSyncError):self.call_fetch()
            fetch.assert_not_called()

    def test_one_request_preserves_exact_id_route_and_not_found(self):
        with patch.object(provider,'reserve_race_data_transport_capacity',return_value=SimpleNamespace(allowed=True)) as capacity,patch.object(provider,'build_the_racing_api_route_url',return_value='https://api.theracingapi.com/v1/results/race_123') as route,patch.object(provider,'_fetch_json',return_value=({'_not_found':True},'a'*64)) as fetch:
            url,payload,sha=self.call_fetch()
            self.assertTrue(payload['_not_found'])
            self.assertEqual(sha,'a'*64)
            self.assertEqual(route.call_args.kwargs['race_id'],'race_123')
            self.assertEqual(capacity.call_args.kwargs['proposed_requests'],1)
            self.assertEqual(fetch.call_count,1)
            self.assertTrue(fetch.call_args.kwargs['allow_not_found'])


class HistoricalExecutionTests(SimpleTestCase):
    def test_request_receipts_survive_failure_and_replay_never_fetches_twice(self):
        from contextlib import ExitStack
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.test import override_settings
        from stable.services import race_data_historical_request as historical
        from stable.test_race_data_historical_request import manifest, encode, NOW, CODE
        for fail_apply in (False, True, "expired_before_transport"):
            with self.subTest(fail_apply=fail_apply), TemporaryDirectory() as root, ExitStack() as stack:
                value = manifest(Path(root)); raw, sha = encode(value)
                current = {'entry':value['entries'][0], 'authority_version':1,
                    'enrollment_state':'enrolled', 'write_owner':'data_sync', 'manual_blocked':False, 'admitted':True}
                route = SimpleNamespace(proof_digest='a'*64, minimum_interval_seconds=1)
                stack.enter_context(override_settings(RACE_DATA_SYNC_ALLOW_NETWORK=True, RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True, RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True))
                stack.enter_context(patch.object(historical,'read_live_entry',return_value=(current,route)))
                stack.enter_context(patch.object(provider,'read_the_racing_api_automation_registry',return_value=({},'a'*64)))
                stack.enter_context(patch.object(provider,'_read_secret',return_value=('test','test')))
                stack.enter_context(patch.object(provider,'ensure_race_live_host_budget_floor'))
                stack.enter_context(patch.object(provider,'_registry_region',return_value='gb'))
                stack.enter_context(patch('stable.models.RaceResultSourceIdentity.objects.get',return_value=SimpleNamespace(region_code='united_kingdom')))
                stack.enter_context(patch('stable.models.RaceEvent.objects.get',return_value=SimpleNamespace(country_region='GB')))
                fetch=stack.enter_context(patch.object(provider,'_fetch_the_racing_api_result_by_id',return_value=('https://api.theracingapi.com/v1/results/race_123',{'_not_found':True},'b'*64)))
                if fail_apply is True:
                    stack.enter_context(patch.object(historical,'apply_response',side_effect=ValueError('test rollback')))
                tick = [NOW]
                from unittest.mock import Mock
                from datetime import timedelta
                actual_transport = Mock()
                if fail_apply == "expired_before_transport":
                    def wait_then_fetch(**kwargs):
                        tick[0] = NOW + timedelta(hours=1)
                        return kwargs['transport']()
                    fetch.side_effect = wait_then_fetch
                args=dict(raw=raw,expected_sha256=sha,expected_code_sha=CODE,
                    receipt_directory=Path(root),event_id=19,clock=lambda:tick[0],transport=actual_transport)
                if fail_apply:
                    with self.assertRaises(ValueError):historical.execute_request(**args)
                else:
                    self.assertEqual(historical.execute_request(**args),'provider_not_found')
                tick[0] = NOW
                with self.assertRaisesRegex(ValueError,'already_reserved'):
                    historical.execute_request(**args)
                self.assertEqual(fetch.call_count,1)
                if fail_apply == 'expired_before_transport':
                    actual_transport.assert_not_called()
                    self.assertFalse((Path(root)/(sha+'-19.response.json')).exists())
                else:
                    saved=json.loads((Path(root)/(sha+'-19.response.json')).read_text())
                    self.assertTrue(saved['response']['_not_found'])
                outcome=json.loads((Path(root)/(sha+'-19.outcome.json')).read_text())
                self.assertEqual(outcome['status'],'failed_or_unknown' if fail_apply else 'provider_not_found')

    def test_network_disabled_rejects_before_fetch(self):
        from django.test import override_settings
        from stable.services.race_data_historical_request import execute_request
        with override_settings(RACE_DATA_SYNC_ALLOW_NETWORK=False), patch.object(provider,'_fetch_the_racing_api_result_by_id') as fetch:
            with self.assertRaisesRegex(ValueError,'network_disabled'):
                execute_request(raw=b'',expected_sha256='',expected_code_sha='',receipt_directory='',event_id=19)
            fetch.assert_not_called()

    def test_command_dry_run_does_not_reserve_or_fetch(self):
        from io import StringIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.core.management import call_command
        from stable.test_race_data_historical_request import manifest, encode, NOW, CODE
        from stable.management.commands import backfill_historical_tra_result as command
        with TemporaryDirectory() as root:
            value=manifest(Path(root));raw,sha=encode(value)
            target=Path(root)/'manifest.json';target.write_bytes(raw)
            current={'entry':value['entries'][0],'authority_version':1,'enrollment_state':'enrolled',
                     'write_owner':'data_sync','manual_blocked':False,'admitted':True}
            with patch.object(command,'require_result_write_flags'), patch.object(Path,'read_text',return_value=CODE), patch.object(command,'read_live_entry',return_value=(current,None)), patch.object(command,'execute_request') as execute, patch('django.utils.timezone.now',return_value=NOW):
                output=StringIO()
                call_command('backfill_historical_tra_result',manifest=str(target),manifest_sha256=sha,
                    event_id=19,receipt_directory=root,stdout=output)
                self.assertIn('dry_run',output.getvalue())
                execute.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()),[target])

    def test_closed_result_flags_reject_before_identity_or_reservation(self):
        from django.test import override_settings
        from stable.services import race_data_historical_request as historical
        for setting in ('RACE_DATA_SYNC_RESULT_APPLY_ENABLED', 'RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED'):
            with self.subTest(setting=setting), override_settings(RACE_DATA_SYNC_ALLOW_NETWORK=True, **{setting:False}), patch.object(historical,'read_live_entry') as read, patch.object(historical,'prepare_request') as reserve:
                with self.assertRaisesRegex(ValueError,'result_apply_disabled'):
                    historical.execute_request(raw=b'',expected_sha256='',expected_code_sha='',receipt_directory='',event_id=19)
                read.assert_not_called()
                reserve.assert_not_called()

    def test_lock_wait_expiry_rejects_before_writer(self):
        from contextlib import nullcontext
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from datetime import timedelta
        from stable.services import race_data_historical_request as historical
        from stable.test_race_data_historical_request import manifest, encode, NOW, CODE
        with TemporaryDirectory() as root:
            raw,sha=encode(manifest(Path(root)))
            with patch('django.db.transaction.atomic',return_value=nullcontext()), patch.object(historical,'read_locked_live_entry'), patch.object(provider,'parse_the_racing_api_live_results_payload',return_value=SimpleNamespace(races=[])), patch.object(provider,'_record_and_apply_the_racing_api_result') as writer:
                with self.assertRaisesRegex(ValueError,'manifest_expired'):
                    historical.apply_response(raw=raw,expected_sha256=sha,expected_code_sha=CODE,
                        receipt_directory=Path(root),event_id=19,now=NOW,response={},
                        raw_sha256='b'*64,result_url='',clock=lambda:NOW+timedelta(hours=1))
                writer.assert_not_called()
