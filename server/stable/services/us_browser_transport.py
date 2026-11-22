"""美国官方目录浏览器传输合同；配额、lease和写入开关由调用方持有。"""
import base64
import binascii
import re
import hashlib
import json
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

MAX_HTML = 2 * 1024 * 1024
MAX_PDF = 2 * 1024 * 1024
NSA_INDEX = 'https://nationalsteeplechase.com/racing/'
PDF_PATTERN = r'https://nationalsteeplechase\.com/wp-content/uploads/[0-9]{4}/(?:0[1-9]|1[0-2])/[A-Za-z0-9_.-]+\.pdf'


URLS = frozenset({
    'https://nationalsteeplechase.com/racing/',
    'https://www.nyra.com/belmont/racing/stakes-schedule/',
    'https://www.dmtc.com/horsemen/nomforms',
    'https://www.dmtc.com/horsemen/nominations',
})


def is_nsa_pdf(url):
    return isinstance(url, str) and re.fullmatch(PDF_PATTERN, url) is not None


def browser_document_budget(url):
    return 2 if is_nsa_pdf(url) else 1


def uses_browser(url):
    return bool(getattr(settings, 'US_BROWSER_URL', '') and (url in URLS or is_nsa_pdf(url)))


def fetch_browser_document(url):
    endpoint = getattr(settings, 'US_BROWSER_URL', '')
    pdf = is_nsa_pdf(url)
    if not endpoint or not (url in URLS or pdf):
        raise ValueError('us_browser_disabled_or_host')
    with requests.post(endpoint.rstrip('/') + '/fetch', json={'url': url},
                       timeout=(3, 35), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise ValueError('us_browser_http_' + str(response.status_code))
        body = bytearray()
        for chunk in response.iter_content(16384):
            body.extend(chunk)
            if len(body) > 4 * 1024 * 1024:
                raise ValueError('us_browser_response_limit')
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError('us_browser_contract')
    html = value.get('html')
    source, final = urlsplit(url), urlsplit(value.get('final_url', ''))
    observed = parse_datetime(str(value.get('observed_at', '')))
    if (value.get('url') != url or final.scheme != 'https' or final.netloc != source.netloc
        or final.path != source.path or final.fragment
        or final.query != source.query
        or observed is None or timezone.is_naive(observed)
        or not 0 <= (timezone.now() - observed).total_seconds() <= 60
        or type(value.get('navigation_count')) is not int or value['navigation_count'] != 1
        or type(value.get('resource_requests')) is not int or not 1 <= value['resource_requests'] <= 96):
        raise ValueError('us_browser_contract')
    if pdf:
        try:
            raw = base64.b64decode(value.get('bytes_b64', ''), validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise ValueError('us_browser_pdf_contract') from None
        if (not raw.startswith(b'%PDF-') or len(raw) > MAX_PDF
                or value.get('raw_sha256') != hashlib.sha256(raw).hexdigest()
                or value.get('directory_url') != NSA_INDEX
                or type(value.get('document_requests')) is not int or value['document_requests'] != 2
                or value['resource_requests'] < 2):
            raise ValueError('us_browser_pdf_contract')
        return {'bytes_b64':value['bytes_b64'], 'raw_sha256':value['raw_sha256'],
                'observed_at':observed.isoformat(), 'browser':{k:value[k] for k in
                ('final_url','directory_url','navigation_count','document_requests','resource_requests','elapsed_ms')}}
    if not isinstance(html,str) or not html.rstrip().lower().endswith('</html>') or len(html.encode())>MAX_HTML:
        raise ValueError('us_browser_contract')
    return {'html': html, 'raw_sha256': hashlib.sha256(html.encode()).hexdigest(),
            'observed_at': observed.isoformat(), 'browser': {k: value[k] for k in
            ('final_url', 'navigation_count', 'resource_requests', 'elapsed_ms')}}
