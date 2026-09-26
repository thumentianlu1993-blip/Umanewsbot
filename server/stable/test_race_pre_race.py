from datetime import date, datetime, timedelta, timezone as tz
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings
from stable import models
from stable.services import race_pre_race as pre
from stable.services.race_data_sync_policy import calculate_next_poll_at

NOW = datetime(2026, 9, 17, 3, tzinfo=tz.utc)
URL = 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604061120260920/D6'
HTML = '''<h1>出馬表</h1><table><caption><div class="race_header"><div class="date">2026年9月20日（日曜）4回中山6日</div><div class="time">発走時刻：15時45分</div><span class="race_name">テスト杯</span></div></caption><tbody><tr><td class="waku"></td><td class="num"></td><td class="horse"><div class="name"><a href="/horse/1">テスト馬</a></div><p class="trainer">調教師</p></td><td class="jockey"><p class="weight">57.0kg</p><p class="jockey">騎手</p></td></tr></tbody></table>'''
HTML = '<html><body>' + HTML + '</body></html>'
FLAGS = dict(RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=True, RACE_DATA_SYNC_ENABLED=True,
             RACE_DATA_SYNC_ALLOW_NETWORK=True, RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
             RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True, RACE_DATA_SYNC_ENABLED_REGIONS=('japan_jra',),
             RACE_DATA_SYNC_ENABLED_FIELDS=('off_time', 'local_start_time', 'timezone_name', 'participants.horse_name', 'participants.number'))


def event():
    return models.RaceEvent.objects.create(year=2026, slug='pre-test', chinese_name='测试杯', original_name='テスト杯',
        country_region='japan', racecourse='中山', local_date=date(2026,9,20), timezone_name='Asia/Tokyo', visibility_status='published')


class PollingBoundaryTests(SimpleTestCase):
    def test_date_only_four_days(self):
        self.assertEqual(calculate_next_poll_at(data_kind='racecard', now=NOW, race_datetime=None,
            local_date=date(2026,9,21), timezone_name='Asia/Tokyo'), NOW + timedelta(hours=3))

    def test_midnight_switch(self):
        now = datetime(2026,9,18,14,30,tzinfo=tz.utc)
        self.assertEqual(calculate_next_poll_at(data_kind='racecard', now=now, race_datetime=None,
            local_date=date(2026,9,20), timezone_name='Asia/Tokyo'), now + timedelta(minutes=30))


@override_settings(**FLAGS)
class PreRaceTests(TestCase):
    def setUp(self):
        self.event = event()

    def claim(self, now=NOW):
        return pre.claim_pre_race(event_id=self.event.pk, source=pre.JRA, now=now)

    def test_claim_and_expiry_fence(self):
        first = self.claim()
        self.assertIsNotNone(first)
        self.assertIsNone(self.claim())
        later = NOW + timedelta(seconds=121)
        second = self.claim(later)
        self.assertNotEqual(first['token'], second['token'])
        self.assertFalse(pre.complete_jra(first, html=HTML, url=URL, now=later))
        self.assertEqual(self.event.data_candidates.count(), 0)

    def test_candidate_only_and_idempotent(self):
        self.assertTrue(pre.complete_jra(self.claim(), html=HTML, url=URL, now=NOW))
        self.assertEqual(self.event.runners.count(), 0)
        self.assertEqual(models.RaceEventParticipant.objects.count(), 0)
        self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime.hour, 6)
        preview = pre.public_jra_preview(self.event, now=NOW)
        self.assertEqual(preview['rows'][0].horse_number, '')
        self.assertEqual(preview['label'], '参赛名单，马号待公布')
        count = self.event.data_candidates.count()
        later = NOW + timedelta(hours=3)
        self.assertTrue(pre.complete_jra(self.claim(later), html=HTML, url=URL, now=later))
        self.assertEqual(self.event.data_candidates.count(), count)

    def test_wrong_race_and_partial_page_rejected(self):
        for html in [HTML.replace('テスト杯','別の杯'), HTML.replace('テスト馬',''), HTML.replace('2026年9月20日','2026年9月19日')]:
            with self.subTest(html=html[:25]), self.assertRaises(ValueError):
                pre.parse_jra_card(html, event=self.event, url=URL)

    def test_url_rejected(self):
        for url in [URL.replace('www.jra.go.jp','evil.test'), URL.replace('https:', 'http:'), URL + '&next=https://evil.test']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                pre.parse_jra_card(HTML, event=self.event, url=url)

    def test_manual_lock_protects_time_and_preview(self):
        self.event.manual_lock_flags = {'basic': True, 'runners': True}
        self.event.save()
        pre.complete_jra(self.claim(), html=HTML, url=URL, now=NOW)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)
        self.assertIsNone(pre.public_jra_preview(self.event, now=NOW))

    def test_disabled_during_fetch_zero_write(self):
        claim = self.claim()
        with override_settings(RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=False):
            self.assertFalse(pre.complete_jra(claim, html=HTML, url=URL, now=NOW))
        self.assertEqual(self.event.data_candidates.count(), 0)

    def test_schedule_changed_during_fetch_zero_write(self):
        claim = self.claim()
        self.event.local_date = date(2026,9,21)
        self.event.save()
        self.assertFalse(pre.complete_jra(claim, html=HTML, url=URL, now=NOW))
        self.assertEqual(self.event.data_candidates.count(), 0)

    def test_other_source_metadata_preserved(self):
        claim = self.claim()
        self.event.refresh_from_db()
        self.event.source_refs['other_source'] = {'keep': 1}
        self.event.save()
        pre.complete_jra(claim, html=HTML, url=URL, now=NOW)
        self.event.refresh_from_db()
        self.assertEqual(self.event.source_refs['other_source'], {'keep': 1})

    def test_handoff_and_expiry_never_revive_preview(self):
        pre.complete_jra(self.claim(), html=HTML, url=URL, now=NOW)
        self.event.refresh_from_db()
        self.assertIsNotNone(pre.public_jra_preview(self.event, now=NOW))
        self.event.source_refs['pre_race_handoff'] = {'source': 'the_racing_api', 'revision_id': 1}
        self.event.save()
        self.assertIsNone(pre.public_jra_preview(self.event, now=NOW))
        self.event.source_refs.pop('pre_race_handoff')
        self.assertIsNone(pre.public_jra_preview(self.event, now=NOW+timedelta(days=4)))

    def test_plain_candidate_never_public(self):
        models.RaceEventDataCandidate.objects.create(event=self.event,module='runners',source_name='other',candidate_payload={'items':[]})
        self.assertIsNone(pre.public_jra_preview(self.event, now=NOW))

    def test_empty_numbered_or_older_response_does_not_replace(self):
        numbered = HTML.replace('<td class="num"></td>', '<td class="num">1</td>')
        pre.complete_jra(self.claim(), html=numbered, url=URL, now=NOW)
        later=NOW+timedelta(hours=3)
        pre.complete_jra(self.claim(later), html=HTML, url=URL, now=later)
        self.event.refresh_from_db()
        self.assertEqual(pre.public_jra_preview(self.event, now=later)['rows'][0].horse_number,'1')

    def test_five_days_outside_window(self):
        self.event.local_date = date(2026,9,22)
        self.event.save()
        self.assertIsNone(self.claim())

    def test_scheduled_discovery_has_clock_injection_and_no_duplicate_fetch(self):
        self.event.source_refs = {'jra_pre_race_url': URL}
        self.event.save()
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            return HTML
        self.assertEqual(pre.discover_jra_pre_race(now=NOW, clock=lambda: NOW, fetcher=fetch)['checked'], 1)
        self.assertEqual(pre.discover_jra_pre_race(now=NOW, clock=lambda: NOW, fetcher=fetch)['checked'], 0)
        self.assertEqual(calls, [URL])

    def test_end_to_end_deadline_rejects_long_network_work(self):
        self.event.source_refs = {'jra_pre_race_url': URL}
        self.event.save()
        times = iter([NOW, NOW, NOW + timedelta(seconds=91)] + [NOW + timedelta(seconds=91)] * 10)
        result = pre.discover_jra_pre_race(now=NOW, clock=lambda: next(times), fetcher=lambda *a, **k: HTML)
        self.assertEqual(result['checked'], 0)
        self.assertEqual(self.event.data_candidates.count(), 0)

    def test_reopen_keeps_previously_nonpublic_candidates_nonpublic(self):
        with override_settings(RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False):
            pre.complete_jra(self.claim(), html=HTML, url=URL, now=NOW)
        self.event.refresh_from_db()
        self.assertIsNone(pre.public_jra_preview(self.event, now=NOW))

    def test_other_source_time_is_not_overwritten(self):
        self.event.race_datetime = datetime(2026,9,20,7,tzinfo=tz.utc)
        self.event.save()
        pre.complete_jra(self.claim(), html=HTML, url=URL, now=NOW)
        self.event.refresh_from_db()
        self.assertEqual(self.event.race_datetime.hour, 7)

    def test_public_detail_renders_preview_and_only_beijing_time(self):
        pre.complete_jra(self.claim(), html=HTML, url=URL, now=NOW)
        with patch('django.utils.timezone.now', return_value=NOW):
            response=self.client.get(self.event.public_path)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'参赛名单，马号待公布')
        self.assertContains(response,'テスト馬')
        self.assertContains(response,'14:45')
        self.assertNotContains(response,'15:45')
        self.assertEqual(self.event.runners.count(),0)

    def test_backend_post_cannot_apply_marked_candidate(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        user=get_user_model().objects.create_superuser(username='race-review',password='synthetic-local-only')
        self.client.force_login(user)
        for module in ('runners','basic'):
            candidate=models.RaceEventDataCandidate.objects.create(event=self.event,module=module,
                source_name=pre.JRA,candidate_payload={'items':[{'horse_name':'Not canonical'}]})
            response=self.client.post(reverse('console-race-event-apply-candidate',args=[candidate.pk]))
            self.assertEqual(response.status_code,302)
            candidate.refresh_from_db()
            self.assertEqual(candidate.status,'pending')
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)
        self.assertEqual(self.event.runners.count(),0)

    def test_field_authority_manual_lock_blocks_basic(self):
        models.RaceEventFieldAuthority.objects.create(event=self.event,subject_type='event',
            subject_key=str(self.event.pk),field_name='race_datetime',manual_lock=True)
        pre.complete_jra(self.claim(),html=HTML,url=URL,now=NOW)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)

    def test_manual_time_component_change_is_not_overwritten(self):
        pre.complete_jra(self.claim(),html=HTML,url=URL,now=NOW)
        self.event.refresh_from_db()
        self.event.local_start_time=datetime.strptime('16:00','%H:%M').time()
        self.event.save()
        later=NOW+timedelta(hours=3)
        pre.complete_jra(self.claim(later),html=HTML.replace('15時45分','15時50分'),url=URL,now=later)
        self.event.refresh_from_db()
        self.assertEqual(self.event.local_start_time.hour,16)


from django.test import TransactionTestCase
from django.db import connection, close_old_connections
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks required')
@override_settings(**FLAGS)
class PreRacePostgresConcurrencyTests(TransactionTestCase):
    def test_two_workers_claim_once_and_preserve_other_source(self):
        target=event()
        target.source_refs={'other_source':{'keep':1}}
        target.save()
        barrier=Barrier(2)
        def claim():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return pre.claim_pre_race(event_id=target.pk,source=pre.JRA,now=NOW)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(claim) for _ in range(2)]
            claims=[f.result(timeout=10) for f in futures]
        self.assertEqual(sum(c is not None for c in claims),1)
        target.refresh_from_db()
        self.assertEqual(target.source_refs['other_source'],{'keep':1})


@override_settings(**FLAGS)
class ReviewRegressions(TestCase):
    def setUp(self):
        self.event=event()

    def complete(self, html=HTML, now=NOW):
        claim=pre.claim_pre_race(event_id=self.event.pk,source=pre.JRA,now=now)
        return pre.complete_jra(claim,html=html,url=URL,now=now)

    @override_settings(
        RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2*1024*1024,
        RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8*1024*1024,
        RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1024*1024*1024,
        RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=192,
        RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=1024*1024*1024,
        RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=512*1024*1024,
        RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
        RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
        RACE_DATA_RAW_CLEANUP_MAX_BYTES=64*1024*1024,
        RACE_DATA_RAW_HOLD_ALERT_BYTES=256*1024*1024,
    )
    def test_shift_jis_http_bytes_end_to_end_and_original_sha(self):
        import hashlib,tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        body=(Path(__file__).parent/'fixtures/jra_pre_race/all_comers_declared.html').read_bytes()
        self.event.original_name='産経賞オールカマー'
        self.event.save()
        response=MagicMock(status_code=200,headers={'Content-Type':'text/html'})
        response.__enter__.return_value=response
        response.iter_content.return_value=[body]
        with tempfile.TemporaryDirectory() as root, override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(root,)), patch('requests.get',return_value=response) as get, patch('django.utils.timezone.now',return_value=NOW):
            page=pre.fetch_jra_html(URL,now=NOW)
            self.assertTrue(self.complete(page))
            self.assertEqual(pre.fetch_jra_html(URL,now=NOW),page)
            self.assertEqual(get.call_count,1)
        self.event.refresh_from_db()
        preview=pre.public_jra_preview(self.event,now=NOW)
        self.assertEqual(len(preview['rows']),13)
        candidate=self.event.data_candidates.get(module='runners')
        self.assertEqual(candidate.raw_payload[pre.JRA]['raw_sha256'],hashlib.sha256(body).hexdigest())

    def test_truncated_source_never_replaces_complete(self):
        self.complete()
        later=NOW+timedelta(hours=3)
        claim=pre.claim_pre_race(event_id=self.event.pk,source=pre.JRA,now=later)
        with self.assertRaises(ValueError):
            pre.complete_jra(claim,html=HTML.split('</tr>')[0]+'</tr>',url=URL,now=later)
        self.assertEqual(self.event.data_candidates.filter(module='runners').count(),1)

    def test_field_scope_closed_and_optional_redaction(self):
        with override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=()):
            self.complete()
            self.event.refresh_from_db()
            self.assertIsNone(pre.public_jra_preview(self.event,now=NOW))
        later=NOW+timedelta(hours=3)
        self.complete(now=later)
        self.event.refresh_from_db()
        preview=pre.public_jra_preview(self.event,now=later)
        self.assertIsNotNone(preview)
        self.assertEqual(preview['rows'][0].jockey_name,'')
        with override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=()):
            self.assertIsNone(pre.public_jra_preview(self.event,now=later))

    def test_successful_url_reused_and_reschedule_invalidates_binding(self):
        calls=[]
        def fetch(url,**kwargs):
            calls.append(url)
            return '<a href="'+URL+'">出馬表</a>' if url==pre.INDEX_URL else HTML
        self.assertEqual(pre.discover_jra_pre_race(now=NOW,clock=lambda:NOW,fetcher=fetch)['checked'],1)
        later=NOW+timedelta(hours=3)
        self.assertEqual(pre.discover_jra_pre_race(now=later,clock=lambda:later,fetcher=fetch)['checked'],1)
        self.assertEqual(calls.count(pre.INDEX_URL),1)
        self.assertEqual(calls.count(URL),2)
        self.event.refresh_from_db()
        self.event.local_date+=timedelta(days=1)
        self.event.save()
        pre.discover_jra_pre_race(now=later,clock=lambda:later,fetcher=fetch)
        self.assertEqual(calls.count(pre.INDEX_URL),2)

    def test_nar_zero_claim_zero_network(self):
        self.event.racecourse='金沢'
        self.event.save()
        self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source=pre.JRA,now=NOW))
        with patch.object(pre,'fetch_jra_html') as fetch:
            pre.discover_jra_pre_race(now=NOW,clock=lambda:NOW)
        fetch.assert_not_called()

    def test_new_success_after_reopening_can_publish_identical_content(self):
        with override_settings(RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=False): self.complete()
        self.event.refresh_from_db()
        self.assertIsNone(pre.public_jra_preview(self.event,now=NOW))
        later=NOW+timedelta(hours=3)
        self.complete(now=later)
        self.event.refresh_from_db()
        self.assertIsNotNone(pre.public_jra_preview(self.event,now=later))
        self.assertEqual(self.event.data_candidates.filter(module='runners').count(),2)


@override_settings(**FLAGS)
class JraNameNormalizationTests(TestCase):
    """长短名等价归一与发现 reason 拆分（2026-09-26 シリウスS/スプリンターズS 根因回归）。"""

    def sirius(self):
        return models.RaceEvent.objects.create(year=2026, slug='sirius-test', chinese_name='天狼星锦标',
            original_name='シリウスS', country_region='japan', racecourse='阪神',
            local_date=date(2026,9,20), timezone_name='Asia/Tokyo', visibility_status='published')

    SIRIUS_URL = 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604081120260920/08'
    SIRIUS_HTML = ('<html><body><h1>出馬表</h1><table><caption><div class="race_header">'
        '<div class="date">2026年9月20日（日曜）3回阪神6日</div><div class="time">発走時刻：15時35分</div>'
        '<span class="race_name">シリウスステークス</span></div></caption>'
        '<tbody><tr><td class="waku"></td><td class="num"></td><td class="horse"><div class="name">'
        '<a href="/horse/1">テスト馬</a></div><p class="trainer">調教師</p></td>'
        '<td class="jockey"><p class="weight">57.0kg</p><p class="jockey">騎手</p></td></tr></tbody></table>'
        '</body></html>')

    def test_normalize_jra_race_name(self):
        cases = {'シリウスステークス': 'シリウスS', 'シリウスS': 'シリウスS', 'GⅢ シリウスS': 'シリウスS',
                 'J・GⅢ 阪神ジャンプS': '阪神ジャンプS', 'NHKマイルカップ': 'NHKマイルC', 'NHKマイルC': 'NHKマイルC',
                 '神戸新聞杯': '神戸新聞杯', '産経賞オールカマー': '産経賞オールカマー', '': '', None: ''}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(pre.normalize_jra_race_name(value), expected)

    def test_long_form_page_matches_short_event_name(self):
        target = self.sirius()
        self.assertEqual(pre.parse_jra_card(self.SIRIUS_HTML, event=target, url=self.SIRIUS_URL)['stage'], 'declared')

    def test_different_race_still_rejected(self):
        target = self.sirius()
        for html in [self.SIRIUS_HTML.replace('シリウスステークス', 'スプリンターズステークス'),
                     self.SIRIUS_HTML.replace('シリウスステークス', 'シリウス記念')]:
            with self.subTest(html=html[:30]), self.assertRaises(ValueError):
                pre.parse_jra_card(html, event=target, url=self.SIRIUS_URL)

    def discover(self, target, pages, now=NOW):
        index = ''.join('<a href="%s">出馬表</a>' % url for url, _ in pages)
        def fetch(url, **kwargs):
            return index if url == pre.INDEX_URL else dict(pages)[url]
        result = pre.discover_jra_pre_race(now=now, clock=lambda: now, fetcher=fetch)
        target.refresh_from_db()
        return result, target.source_refs['pre_race_checks']['jra_pre_race_v1']

    def test_discovery_long_form_name_completes_without_manual_alias(self):
        target = self.sirius()
        result, state = self.discover(target, [(self.SIRIUS_URL, self.SIRIUS_HTML)])
        self.assertEqual(result['checked'], 1)
        self.assertEqual(target.data_candidates.filter(module='runners', source_name=pre.JRA).count(), 1)

    def test_discovery_no_match_and_ambiguous_reasons_split(self):
        target = self.sirius()
        other = self.SIRIUS_URL.replace('/08', '/09')
        result, state = self.discover(target, [(self.SIRIUS_URL, self.SIRIUS_HTML.replace('シリウスステークス', '別の杯'))])
        self.assertEqual(result['checked'], 0)
        self.assertEqual(state['reason'], 'jra_race_identity_no_match')
        later = NOW + timedelta(hours=4)
        result, state = self.discover(target, [(self.SIRIUS_URL, self.SIRIUS_HTML), (other, self.SIRIUS_HTML)], now=later)
        self.assertEqual(result['checked'], 0)
        self.assertEqual(state['reason'], 'jra_race_identity_ambiguous')
        self.assertEqual(target.data_candidates.count(), 0)
