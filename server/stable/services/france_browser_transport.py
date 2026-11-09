"""法国内部浏览器传输合同；配额、lease和写入开关由调用方持有。"""
import hashlib
import json
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

MAX_HTML = 2 * 1024 * 1024


def fetch_browser_document(url):
    endpoint = getattr(settings, 'FRANCE_BROWSER_URL', '')
    if not endpoint or urlsplit(url).hostname not in {'www.france-galop.com','www.geny.com'}:
        raise ValueError('france_browser_disabled_or_host')
    with requests.post(endpoint.rstrip('/') + '/fetch', json={'url': url},
                       timeout=(3, 35), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise ValueError('france_browser_http_' + str(response.status_code))
        body = bytearray()
        for chunk in response.iter_content(16384):
            body.extend(chunk)
            if len(body) > 4 * 1024 * 1024:
                raise ValueError('france_browser_response_limit')
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError('france_browser_contract')
    html = value.get('html')
    source, final = urlsplit(url), urlsplit(value.get('final_url', ''))
    observed = parse_datetime(str(value.get('observed_at', '')))
    if (value.get('url') != url or final.scheme != 'https' or final.netloc != source.netloc
        or final.path != source.path or final.fragment
        or final.query != source.query
        or not isinstance(html, str) or not html.rstrip().lower().endswith('</html>')
        or len(html.encode()) > MAX_HTML or observed is None or timezone.is_naive(observed)
        or not 0 <= (timezone.now() - observed).total_seconds() <= 60
        or type(value.get('navigation_count')) is not int or not 1 <= value['navigation_count'] <= 1
        or type(value.get('resource_requests')) is not int or not 1 <= value['resource_requests'] <= 96):
        raise ValueError('france_browser_contract')
    return {'html': html, 'raw_sha256': hashlib.sha256(html.encode()).hexdigest(),
            'observed_at': observed.isoformat(), 'browser': {k: value[k] for k in
            ('final_url', 'navigation_count', 'resource_requests', 'elapsed_ms')}}
