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
             patch.dict('sys.modules',{'stable.services.us_browser_transport':SimpleNamespace(fetch_browser_document=fetch,uses_browser=lambda u:True)}), \
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
