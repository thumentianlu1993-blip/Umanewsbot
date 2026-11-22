from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.test import SimpleTestCase
from stable.services.race_pre_race import _fetch_bounded_html


class USTransportTests(SimpleTestCase):
    def test_pdf_bytes_share_budget_and_snapshot_without_text_reencoding(self):
        raw=b'%PDF-1.7\n\xff\xfe\n'
        response=Mock(status_code=200,headers={'Content-Type':'application/pdf'})
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.iter_content.return_value=[raw]
        def snapshot(**kw):
            payload,requests,used=kw['fetcher']()
            self.assertEqual(requests,1)
            return payload,used
        with patch('requests.get',return_value=response), patch('stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot',side_effect=snapshot), patch('stable.services.race_events.ensure_race_live_host_budget_floor'), patch('stable.services.race_pre_race._reserve_pre_race_request',return_value=SimpleNamespace(reservation_version=1)), patch('stable.services.race_events.record_race_live_host_outcome'):
            value=_fetch_bounded_html('https://www1.drf.com/chart.pdf',now=datetime.now(timezone.utc),provider='us_racing',region='united_states',validator=lambda u:None,enabled=lambda:True,binary=True)
        self.assertEqual(bytes(value),raw)
        self.assertIsNotNone(value.observed_at)

    def test_nsa_browser_uses_shared_budget_and_returns_source_bytes(self):
        from django.test import override_settings
        from unittest.mock import Mock
        import hashlib
        now=datetime.now(timezone.utc)
        html='<html><head><title>Racing</title></head><body>Colonial Cup</body></html>'
        fetch=Mock(return_value=dict(html=html,raw_sha256=hashlib.sha256(html.encode()).hexdigest(),observed_at=now.isoformat()))
        def snapshot(**kw):
            payload,count,used=kw['fetcher']()
            self.assertEqual((count,used),(1,1))
            return payload,used
        with override_settings(US_BROWSER_URL='http://us_browser:8080'), \
             patch.dict('sys.modules',{'stable.services.us_browser_transport':SimpleNamespace(fetch_browser_document=fetch,uses_browser=lambda u:True,browser_document_budget=lambda u:1)}), \
             patch('requests.get',side_effect=AssertionError('browser route must not use direct HTTP')), \
             patch('stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot',side_effect=snapshot), \
             patch('stable.services.race_events.ensure_race_live_host_budget_floor'), \
             patch('stable.services.race_pre_race._reserve_pre_race_request',return_value=SimpleNamespace(reservation_version=1)), \
             patch('stable.services.race_events.record_race_live_host_outcome'):
            value=_fetch_bounded_html('https://nationalsteeplechase.com/racing/',now=now,provider='us_racing',region='united_states',validator=lambda u:None,enabled=lambda:True,binary=True)
        self.assertEqual(bytes(value),html.encode())
        fetch.assert_called_once_with('https://nationalsteeplechase.com/racing/')

    def test_browser_contract_rejects_redirect_stale_navigation_and_large_payload(self):
        import json
        from datetime import timedelta
        from django.test import override_settings
        from stable.services.us_browser_transport import fetch_browser_document
        now=datetime.now(timezone.utc);url='https://nationalsteeplechase.com/racing/'
        good=dict(url=url,final_url=url,html='<html><body>Racing</body></html>',observed_at=now.isoformat(),navigation_count=1,resource_requests=4,elapsed_ms=1200)
        cases=[({},False),({'final_url':url+'?other=1'},True),({'navigation_count':2},True),({'resource_requests':97},True),
               ({'observed_at':(now-timedelta(minutes=2)).isoformat()},True),({'html':'<html>'+('x'*2097152)+'</html>'},True)]
        for changes,reject in cases:
            response=Mock(status_code=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            response.iter_content.return_value=[json.dumps({**good,**changes}).encode()]
            with self.subTest(changes=list(changes)),override_settings(US_BROWSER_URL='http://us_browser:8080'),patch('requests.post',return_value=response):
                if reject:
                    with self.assertRaises(ValueError):fetch_browser_document(url)
                else:self.assertEqual(fetch_browser_document(url)['html'],good['html'])

    def test_nsa_pdf_browser_contract_and_two_document_budget(self):
        import json,base64,hashlib
        from django.test import override_settings
        from stable.services import us_browser_transport as transport
        url='https://nationalsteeplechase.com/wp-content/uploads/2026/11/Colonial-Cup-Overnight.pdf'
        raw=b'%PDF-1.7\n\xff\xfe\n';now=datetime.now(timezone.utc)
        good=dict(url=url,final_url=url,directory_url='https://nationalsteeplechase.com/racing/',
            bytes_b64=base64.b64encode(raw).decode(),raw_sha256=hashlib.sha256(raw).hexdigest(),
            observed_at=now.isoformat(),navigation_count=1,document_requests=2,resource_requests=6,elapsed_ms=1200)
        with override_settings(US_BROWSER_URL='http://us_browser:8080'):
            self.assertTrue(transport.uses_browser(url))
            self.assertEqual(transport.browser_document_budget(url),2)
        cases=[({},False),({'raw_sha256':'0'*64},True),({'bytes_b64':'bad!'},True),
            ({'directory_url':'https://example.com/'},True),({'document_requests':1},True),({'final_url':url+'?x'},True),
            ({'bytes_b64':base64.b64encode(b'<html>Forbidden</html>').decode()},True)]
        for change,reject in cases:
            response=Mock(status_code=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            response.iter_content.return_value=[json.dumps({**good,**change}).encode()]
            with self.subTest(change=list(change)),override_settings(US_BROWSER_URL='http://us_browser:8080'),patch('requests.post',return_value=response):
                if reject:
                    with self.assertRaises(ValueError):transport.fetch_browser_document(url)
                else:self.assertEqual(base64.b64decode(transport.fetch_browser_document(url)['bytes_b64']),raw)
        def snapshot(**kw):
            self.assertEqual(kw['proposed_requests'],2)
            payload,count,used=kw['fetcher']();self.assertEqual((count,used),(2,1));return payload,used
        with override_settings(US_BROWSER_URL='http://us_browser:8080'),patch.object(transport,'fetch_browser_document',return_value=good), \
             patch('requests.get',side_effect=AssertionError('direct HTTP forbidden')), \
             patch('stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot',side_effect=snapshot), \
             patch('stable.services.race_events.ensure_race_live_host_budget_floor'), \
             patch('stable.services.race_pre_race._reserve_pre_race_request',return_value=SimpleNamespace(reservation_version=1)) as reserve, \
             patch('stable.services.race_events.record_race_live_host_outcome'):
            value=_fetch_bounded_html(url,now=now,provider='us_racing',region='united_states',validator=lambda u:None,enabled=lambda:True,binary=True)
            self.assertEqual(bytes(value),raw);self.assertEqual(reserve.call_count,2)


    def test_real_shared_snapshot_reserves_capacity_before_pdf_fetch(self):
        from django.test import override_settings
        from stable.services import race_data_sync_providers as shared
        from stable.services.race_pre_race import JraFetchError
        now=datetime.now(timezone.utc)
        query=Mock();query.values_list.return_value.first.return_value=None
        cases=[('https://nationalsteeplechase.com/racing/',1,2*1024*1024),
            ('https://nationalsteeplechase.com/wp-content/uploads/2026/11/Colonial-Cup-Overnight.pdf',2,2*1024*1024)]
        for url,requests,limit in cases:
            with self.subTest(url=url),override_settings(US_BROWSER_URL='http://us_browser:8080'), \
                 patch.object(shared,'claim_snapshot_lease',return_value=SimpleNamespace(action='acquired',generation=1)), \
                 patch.object(shared.models.RaceDataSnapshotLease.objects,'filter',return_value=query), \
                 patch.object(shared,'reserve_race_data_transport_capacity',return_value=SimpleNamespace(allowed=False,reason_code='capacity_probe')) as capacity, \
                 patch.object(shared,'fail_snapshot_lease'),patch('requests.post',side_effect=AssertionError('no capacity, no fetch')):
                with self.assertRaisesRegex(JraFetchError,'capacity_probe'):
                    _fetch_bounded_html(url,now=now,provider='us_racing',region='united_states',validator=lambda u:None,enabled=lambda:True,binary=True)
                self.assertEqual(capacity.call_args.kwargs['proposed_requests'],requests)
                self.assertEqual(capacity.call_args.kwargs['max_response_bytes_per_request'],limit)


from django.test import TestCase, override_settings


class USPDFCapacityTests(TestCase):
    @override_settings(RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2*1024*1024,
                       RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=4*1024*1024,
                       RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8*1024*1024,
                       RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=2048,
                       RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=1024*1024*1024,
                       RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=512*1024*1024,
                       RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
                       RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
                       RACE_DATA_RAW_CLEANUP_MAX_BYTES=64*1024*1024,
                       RACE_DATA_RAW_HOLD_ALERT_BYTES=256*1024*1024)
    def test_existing_two_mib_cap_reserves_both_documents_and_exhausts_daily_bytes(self):
        from stable.services.race_data_sync_pipeline import reserve_race_data_transport_capacity
        from stable.services.us_browser_transport import MAX_PDF, browser_document_budget
        from stable.models import RaceDataTransportCapacityLedger
        url='https://nationalsteeplechase.com/wp-content/uploads/2026/11/Colonial-Cup-Overnight.pdf'
        args=dict(provider='us_racing',region_code='united_states',now=datetime.now(timezone.utc),
                  proposed_requests=browser_document_budget(url),max_response_bytes_per_request=MAX_PDF)
        with patch('stable.services.race_data_sync_pipeline.inspect_race_data_artifact_capacity',return_value=(0,10**12)), \
             patch('stable.services.race_priority.priority_transport_active',return_value=False):
            allowed=reserve_race_data_transport_capacity(**args)
            self.assertTrue(allowed.allowed,allowed.reason_code)
            ledger=RaceDataTransportCapacityLedger.objects.get(provider='us_racing')
            self.assertEqual((ledger.request_count,ledger.budgeted_response_bytes),(2,4*1024*1024))
            denied=reserve_race_data_transport_capacity(**args)
            self.assertEqual(denied.reason_code,'artifact_daily_bytes_exceeded')
            oversized=reserve_race_data_transport_capacity(**{**args,'max_response_bytes_per_request':MAX_PDF+1})
            self.assertEqual(oversized.reason_code,'artifact_payload_compressed_too_large')
            ledger.refresh_from_db()
            self.assertEqual((ledger.request_count,ledger.budgeted_response_bytes),(2,4*1024*1024))
