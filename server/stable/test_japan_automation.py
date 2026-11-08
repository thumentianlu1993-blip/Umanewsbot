"""日本自动采集的真实页面回归；测试只使用本地fixture。"""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from django.test import SimpleTestCase
from stable.services.race_data_source_adapters import SourceRoute, parse_nar_observation
from stable.services.race_pre_race import parse_jra_card

ROOT = Path(__file__).parent / 'fixtures/japan_automation'
NOW = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)
REGISTRATION = 'https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03tde000505031120261114/49'


class JapanRealPageTests(SimpleTestCase):
    def nar(self, name, url, venue):
        route = SourceRoute(dict(provider='nar', operator='nar', region='japan_nar',
            identity_namespace='nar-race-v1', allowed_hosts=['www.keiba.go.jp'],
            allowed_path_prefixes=['/KeibaWeb/TodayRaceInfo/'],
            venue_aliases=venue, timezone='Asia/Tokyo', parser_version='test'), 'a'*64)
        return parse_nar_observation((ROOT/name).read_text(), url=url, route=route, now=NOW)

    def test_nar_real_race_title_not_navigation_heading(self):
        value = self.nar('nar-result.html',
            'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=2026%2F09%2F01&k_raceNo=10&k_babaCode=10',
            {'nar:10': ['盛岡']})
        self.assertIn('不来方賞', value['raw_names'][0])
        self.assertEqual(len(value['roster']), 11)
        self.assertEqual(value['roster'][0]['horse_name'], 'イッテラッシャイ')
        self.assertEqual(value['roster'][0]['finish_time'], '2:00.9')

    def test_nar_cancellation_is_retained(self):
        value = self.nar('nar-cancelled.html',
            'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=2026%2F11%2F03&k_raceNo=7&k_babaCode=22',
            {'nar:22': ['金沢']})
        self.assertIn('レディスクラシック', value['raw_names'][0])
        self.assertEqual(len(value['roster']), 12)
        cancelled = next(r for r in value['roster'] if r['horse_name']=='ラブラブパイロ')
        self.assertEqual(cancelled['status'], 'withdrawn')
        self.assertIsNone(cancelled['reported_finish_position'])

    def test_jra_registration_without_time_or_numbers(self):
        event = SimpleNamespace(original_name='武蔵野S', chinese_name='',
            local_date=date(2026,11,14), racecourse='東京',
            aliases=SimpleNamespace(values_list=lambda *a, **k: []))
        result = parse_jra_card((ROOT/'jra-registration.html').read_text(), event=event, url=REGISTRATION)
        self.assertEqual(result['stage'], 'registration')
        self.assertEqual(len(result['items']), 20)
        self.assertFalse(result.get('off_time'))
        self.assertTrue(all(not r['horse_number'] and not r['barrier'] for r in result['items']))
        self.assertEqual(result['items'][0]['horse_name'], 'アピーリングルック')
        self.assertEqual(result['items'][0]['carried_weight'], '55.0')

    def test_registration_count_date_and_cname_must_agree(self):
        html = (ROOT/'jra-registration.html').read_text()
        event = SimpleNamespace(original_name='武蔵野S', chinese_name='',
            local_date=date(2026,11,14), racecourse='東京',
            aliases=SimpleNamespace(values_list=lambda *a, **k: []))
        for page, url in [(html.replace('20頭','21頭'), REGISTRATION),
                          (html, REGISTRATION.replace('20261114','20261115')),
                          (html.replace('2026年11月14日','2025年11月14日'), REGISTRATION)]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    parse_jra_card(page, event=event, url=url)


class BrowserTransportTests(SimpleTestCase):
    def test_browser_reply_must_preserve_requested_identity(self):
        import json
        from unittest.mock import MagicMock, patch
        from django.test import override_settings
        from stable.services.jra_browser_transport import fetch_browser_document
        value = dict(url=REGISTRATION, final_url='https://www.jra.go.jp/JRADB/accessT.html',
            html='<html><body>registration</body></html>',observed_at=NOW.isoformat(),
            navigation_count=2,resource_requests=31,elapsed_ms=4000)
        with override_settings(JRA_BROWSER_URL='http://jra_browser:8080'), patch('django.utils.timezone.now', return_value=NOW):
            for changed, accepted in [({},True),({'final_url':'https://evil.test/JRADB/accessT.html'},False),
                                     ({'url':REGISTRATION.replace('20261114','20261115')},False),
                                     ({'navigation_count':3},False),({'observed_at':'2026-01-01T00:00:00Z'},False)]:
                response=MagicMock();response.status_code=200
                response.iter_content.return_value=[json.dumps({**value,**changed}).encode()]
                response.__enter__.return_value=response
                with patch('requests.post',return_value=response) as post:
                    if accepted:
                        self.assertEqual(fetch_browser_document(REGISTRATION)['html'],value['html'])
                    else:
                        with self.assertRaises(ValueError):fetch_browser_document(REGISTRATION)
                    self.assertFalse(post.call_args.kwargs['allow_redirects'])


class JapanDiscoveryTests(SimpleTestCase):
    def test_registration_index_discovers_real_action_not_address_bar(self):
        from stable.services.race_pre_race import jra_pre_race_links
        event = SimpleNamespace(original_name='武蔵野S', chinese_name='',
            local_date=date(2026,11,14), racecourse='東京',
            aliases=SimpleNamespace(values_list=lambda *a, **k: []))
        links = jra_pre_race_links((ROOT/'jra-registration-index.html').read_text(),event=event)
        self.assertEqual(links,[REGISTRATION])
        event.local_date=date(2025,11,14)
        self.assertEqual(jra_pre_race_links((ROOT/'jra-registration-index.html').read_text(),event=event),[])

    def test_jra_static_replay_result_uses_same_occurrence_identity(self):
        from stable.services.race_data_source_adapters import parse_jra_observation
        route = SourceRoute(dict(provider='jra',region='japan_jra',operator='jra',
            identity_namespace='jra-race-v1', allowed_hosts=['www.jra.go.jp'],
            allowed_path_prefixes=['/datafile/seiseki/'],venue_aliases={'kyoto':['京都']},
            timezone='Asia/Tokyo',parser_version='test'), 'a'*64)
        value=parse_jra_observation((ROOT/'jra-result.html').read_text(),
            url='https://www.jra.go.jp/datafile/seiseki/replay/2026/102.html',route=route,now=NOW)
        self.assertEqual(value['external_race_id'],'08202605021120261108')
        self.assertEqual(value['local_date'],'2026-11-08')
        self.assertIn('みやこS',value['raw_names'])
        self.assertEqual(len(value['roster']),16)
        self.assertEqual(value['result_phase'],'official')


from django.test import TestCase, override_settings
from stable.test_race_pre_race import FLAGS

@override_settings(**{**FLAGS, 'JRA_BROWSER_URL':'http://jra_browser:8080',
                      'RACE_DATA_SYNC_JAPAN_PRE_RACE_DAYS':21})
class JapanRegistrationWorkflowTests(TestCase):
    def test_discovery_write_preview_and_replay_without_invented_start_time(self):
        from datetime import timedelta
        from stable import models
        from stable.services import race_pre_race as pre
        event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='musashino',
            original_name='武蔵野S',country_region='japan',racecourse='東京',
            local_date=date(2026,11,14),timezone_name='Asia/Tokyo',visibility_status='published')
        pages={pre.CARD_INDEX_URL:(ROOT/'jra-card-index.html').read_text(),
               pre.REGISTRATION_INDEX_URL:(ROOT/'jra-registration-index.html').read_text(),
               REGISTRATION:(ROOT/'jra-registration.html').read_text()}
        calls=[]
        def fetch(url,**kw):calls.append(url);return pages[url]
        for now in (NOW,NOW+timedelta(hours=4)):
            result=pre.discover_jra_pre_race(now=now,fetcher=fetch,clock=lambda:now)
            self.assertEqual(result['checked'],1,result)
        event.refresh_from_db()
        self.assertIsNone(event.race_datetime)
        self.assertEqual(event.runners.count(),0)
        self.assertEqual(event.data_candidates.filter(module='runners').count(),1)
        view=pre.public_jra_preview(event,now=NOW+timedelta(hours=4))
        self.assertEqual(view['label'],'报名名单')
        self.assertEqual(len(view['rows']),20)
        self.assertEqual(calls.count(REGISTRATION),2)

    def test_ambiguous_ordinary_race_never_uses_other_page_failure_as_identity(self):
        from stable import models
        from stable.services import race_pre_race as pre
        from unittest.mock import Mock,patch
        event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='ambiguous-ordinary',
            original_name='3歳以上1勝クラス',country_region='japan',racecourse='東京',
            local_date=date(2026,11,8),timezone_name='Asia/Tokyo',visibility_status='published')
        fetch=Mock(return_value=(ROOT/'jra-meeting-index.html').read_text())
        # 即使下游一页可解析另一页不可解析，也不能从弱排除得到身份。
        with patch.object(pre,'parse_jra_card',side_effect=[{},ValueError('not_published')]) as parse:
            result=pre.discover_jra_pre_race(now=NOW,fetcher=fetch,clock=lambda:NOW)
            self.assertEqual(result['checked'],0)
            parse.assert_not_called()
        self.assertEqual(fetch.call_count,1)
        event.refresh_from_db()
        self.assertEqual(pre._state(event,pre.JRA)['reason'],'jra_race_identity_ambiguous')
        self.assertEqual(event.data_candidates.count(),0)
        self.assertIsNone(event.race_datetime)

    def test_unpublished_registration_is_a_successful_check(self):
        from stable import models
        from stable.services import race_pre_race as pre
        event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='fukushima',
            original_name='福島記念',country_region='japan',racecourse='福島',
            local_date=date(2026,11,21),timezone_name='Asia/Tokyo',visibility_status='published')
        pre.discover_jra_pre_race(now=NOW,clock=lambda:NOW,fetcher=lambda *a,**k:'<html><body></body></html>')
        event.refresh_from_db();state=pre._state(event,pre.JRA)
        self.assertEqual(state['reason'],'not_published')
        self.assertEqual(state['failures'],0)
        self.assertEqual(state['last_checked_at'],NOW.isoformat())
        self.assertEqual(event.data_candidates.count(),0)

class JapanResultDiscoveryTests(SimpleTestCase):
    def test_jra_annual_row_selects_date_venue_name_and_real_result_link(self):
        from stable.services.japan_source_discovery import jra_annual_result
        event=SimpleNamespace(original_name='みやこS',chinese_name='',local_date=date(2026,11,8),racecourse='京都')
        url='https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html'
        self.assertEqual(jra_annual_result((ROOT/'jra-annual.html').read_text(),url=url,event=event),
            'https://www.jra.go.jp/datafile/seiseki/replay/2026/102.html')
        event.local_date=date(2025,11,8)
        with self.assertRaises(ValueError):jra_annual_result((ROOT/'jra-annual.html').read_text(),url=url,event=event)

    def test_nar_topic_follows_real_card_and_checks_date(self):
        from stable.services.japan_source_discovery import nar_topic_card
        event=SimpleNamespace(local_date=date(2026,9,1))
        url='https://www.keiba.go.jp/dirtgraderace/2026/0901_kozukatasho/racecard.html'
        self.assertEqual(nar_topic_card((ROOT/'nar-topic.html').read_text(),url=url,event=event),
            'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026/09/01&k_raceNo=10&k_babaCode=10')
        event.local_date=date(2025,9,1)
        with self.assertRaises(ValueError):nar_topic_card((ROOT/'nar-topic.html').read_text(),url=url,event=event)

class NarIndependentRosterTests(SimpleTestCase):
    def test_card_then_result_establishes_complete_roster_without_existing_rows(self):
        from unittest.mock import MagicMock, patch
        from stable.services.race_data_source_adapters import fetch_bound_observation
        card='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026/09/01&k_raceNo=10&k_babaCode=10'
        result='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=2026%2F09%2F01&k_raceNo=10&k_babaCode=10'
        route=SourceRoute(dict(provider='nar',operator='nar',region='japan_nar',identity_namespace='nar-race-v1',
            allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/KeibaWeb/TodayRaceInfo/'],
            venue_aliases={'nar:10':['盛岡']},timezone='Asia/Tokyo',parser_version='test'),'a'*64)
        event=MagicMock();event.source_identities.filter.return_value.first.return_value=None
        event.runners.exists.return_value=False
        pages={card:(ROOT/'nar-card.html').read_text(),result:(ROOT/'nar-result.html').read_text()}
        with patch('stable.services.race_source_identity.seed_evidence',return_value=None),patch(
            'stable.services.race_data_source_adapters.discover_source_url',return_value=card):
            value=fetch_bound_observation(event=event,route=route,now=NOW,fetcher=lambda url,**k:pages[url])
        self.assertTrue(value['roster_complete'])
        self.assertEqual(value['roster_evidence']['url'],card)
        self.assertEqual(value['roster_evidence']['row_count'],11)

class NarPreRaceTests(SimpleTestCase):
    def test_current_unpublished_page_ignores_commented_sample_horses(self):
        from stable.services.nar_pre_race import parse_nar_nominations
        event=SimpleNamespace(original_name='浦和記念',local_date=date(2026,11,25))
        value=parse_nar_nominations((ROOT/'nar-upcoming.html').read_text(),event=event,
            url='https://www.keiba.go.jp/dirtgraderace/2026/1125_urawakinen/racecard.html')
        self.assertEqual(value['stage'],'not_published')
        self.assertEqual(value['items'],[])
        self.assertIn('11月9日',value['schedule'])

    def test_nomination_template_keeps_reserve_and_planned_jockey_distinct(self):
        from stable.services.nar_pre_race import parse_nar_nominations
        event=SimpleNamespace(original_name='浦和記念',local_date=date(2026,11,25))
        # 结构测试：表头取自官网注释模板，非已经公开的本场名单。
        html='<html><head><title>浦和記念 2026年</title></head><body><section class="sec_nominate"><h2>補欠馬</h2><table><tr><td>馬名</td><td>斤量</td><td>調教師</td><td>騎乗予定騎手</td></tr><tr><td>テストホース</td><td>未定</td><td>テスト調教師</td><td>未定</td></tr></table></section></body></html>'
        value=parse_nar_nominations(html,event=event,url='https://www.keiba.go.jp/dirtgraderace/2026/1125_urawakinen/racecard.html')
        self.assertEqual(value['stage'],'registration')
        row=value['items'][0]
        self.assertEqual(row['source_refs']['selection_status'],'補欠馬')
        self.assertEqual(row['carried_weight'],'')
        self.assertEqual(row['jockey_name'],'')
        self.assertEqual(row['horse_number'],'')
        with self.assertRaises(ValueError):parse_nar_nominations(html.replace('2026年','2025年'),event=event,
            url='https://www.keiba.go.jp/dirtgraderace/2026/1125_urawakinen/racecard.html')

    def test_nar_actual_fragment_navigation_to_upcoming_page(self):
        from stable.services.japan_source_discovery import nar_topic_document
        base='https://www.keiba.go.jp/dirtgraderace/2026/1125_urawakinen/'
        event=SimpleNamespace(local_date=date(2026,11,25),source_refs={'detail':base+'introduction.html'})
        route=SourceRoute(dict(allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/dirtgraderace/2026/']), 'a'*64)
        pages={base+'introduction.html':(ROOT/'nar-introduction.html').read_text(),
            base+'common/navigation.html':(ROOT/'nar-navigation.html').read_text(),
            base+'racecard.html':(ROOT/'nar-upcoming.html').read_text()}
        url,page=nar_topic_document(event=event,route=route,now=NOW,fetcher=lambda u,**k:pages[u])
        self.assertEqual(url,base+'racecard.html')
        self.assertEqual(page,pages[url])

@override_settings(**{**FLAGS,'RACE_DATA_SYNC_NAR_PRE_RACE_ENABLED':True,
    'RACE_DATA_SYNC_ENABLED_PROVIDERS':('jra','nar'),
    'RACE_DATA_SYNC_ENABLED_REGIONS':('japan_jra','japan_nar'),
    'RACE_DATA_SYNC_JAPAN_PRE_RACE_DAYS':31})
class NarPreRaceWorkflowTests(TestCase):
    def setUp(self):
        from stable import models
        self.base='https://www.keiba.go.jp/dirtgraderace/2026/1125_urawakinen/'
        self.event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='urawa-2026',
            original_name='浦和記念',country_region='japan',racecourse='浦和',local_date=date(2026,11,25),
            timezone_name='Asia/Tokyo',visibility_status='published',source_refs={'detail':self.base+'introduction.html'})
        self.route=SourceRoute(dict(provider='nar',region='japan_nar',operator='nar',
            allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/dirtgraderace/2026/','/KeibaWeb/TodayRaceInfo/'],
            venue_aliases={'nar:18':['浦和']},valid_from='2026-01-01T00:00:00Z',valid_until='2027-01-01T00:00:00Z'), 'a'*64)
        self.policy=SimpleNamespace(routes=[self.route],valid=lambda n:True)
        self.pages={self.base+'introduction.html':(ROOT/'nar-introduction.html').read_text(),
            self.base+'common/navigation.html':(ROOT/'nar-navigation.html').read_text(),
            self.base+'racecard.html':(ROOT/'nar-upcoming.html').read_text()}

    def test_not_published_is_successful_check_without_sample_rows(self):
        from stable.services.nar_pre_race import discover_nar_pre_race,NAR,public_nar_preview
        from stable.services import race_pre_race as pre
        out=discover_nar_pre_race(now=NOW,policy=self.policy,fetcher=lambda u,**kw:self.pages[u],clock=lambda:NOW)
        self.assertEqual(out,dict(checked=1,attempted=1))
        self.event.refresh_from_db()
        self.assertEqual(self.event.data_candidates.count(),0)
        self.assertIsNone(public_nar_preview(self.event,now=NOW))
        state=pre._state(self.event,NAR)
        self.assertEqual(state['failures'],0)
        self.assertEqual(state['reason'],'not_published')
        self.assertIn('11月9日',state['publication_schedule'])

    def test_nomination_updates_are_idempotent_and_preview_marks_reserve(self):
        from datetime import timedelta
        from stable.services.nar_pre_race import discover_nar_pre_race,public_nar_preview
        self.pages[self.base+'racecard.html']='<html><head><title>浦和記念 2026年</title></head><body><section class="sec_nominate"><h2>補欠馬</h2><table><tr><td>馬名</td><td>斤量</td><td>調教師</td><td>騎乗予定騎手</td></tr><tr><td>テストホース</td><td>56.0</td><td>テスト調教師</td><td>未定</td></tr></table></section></body></html>'
        for now in [NOW,NOW+timedelta(hours=4)]:
            self.assertEqual(discover_nar_pre_race(now=now,policy=self.policy,
                fetcher=lambda u,**kw:self.pages[u],clock=lambda:now)['checked'],1)
        self.event.refresh_from_db()
        self.assertEqual(self.event.data_candidates.count(),1)
        self.assertEqual(self.event.runners.count(),0)
        self.assertIsNone(self.event.race_datetime)
        preview=public_nar_preview(self.event,now=NOW+timedelta(hours=4))
        self.assertIn('预定',preview['label'])
        self.assertEqual(preview['rows'][0].get_running_status_display(),'候补')

    def test_backend_cannot_apply_nar_registration_candidate(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from stable import models
        user=get_user_model().objects.create_superuser(username='nar-review',password='synthetic-local-only')
        self.client.force_login(user)
        for marked_by_source in (True,False):
            candidate=models.RaceEventDataCandidate.objects.create(event=self.event,module='runners',
                source_name='nar_pre_race_v1' if marked_by_source else 'renamed',
                raw_payload={} if marked_by_source else {'nar_pre_race_v1':{'validated':True}},
                candidate_payload={'items':[{'horse_name':'候补马'}]})
            response=self.client.post(reverse('console-race-event-apply-candidate',args=[candidate.pk]))
            self.assertEqual(response.status_code,302)
            candidate.refresh_from_db();self.assertEqual(candidate.status,'pending')
        self.assertEqual(self.event.runners.count(),0)

    def test_handoff_or_formal_roster_never_claims_or_fetches(self):
        from unittest.mock import Mock
        from stable.services.nar_pre_race import discover_nar_pre_race,NAR
        from stable.services import race_pre_race as pre
        fetch=Mock()
        self.event.source_refs={**self.event.source_refs,'pre_race_handoff':True};self.event.save()
        self.assertEqual(discover_nar_pre_race(now=NOW,policy=self.policy,fetcher=fetch,clock=lambda:NOW)['attempted'],0)
        self.event.source_refs.pop('pre_race_handoff');self.event.save()
        self.event.runners.create(horse_name='正式名單',horse_number='1')
        self.assertEqual(discover_nar_pre_race(now=NOW,policy=self.policy,fetcher=fetch,clock=lambda:NOW)['attempted'],0)
        self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source=NAR,now=NOW))
        fetch.assert_not_called()

    def test_concurrent_handoff_finishes_claim(self):
        from stable.services.nar_pre_race import discover_nar_pre_race,NAR
        from stable.services import race_pre_race as pre
        def fetch(url,**kwargs):
            self.event.refresh_from_db()
            self.event.source_refs={**self.event.source_refs,'pre_race_handoff':True};self.event.save()
            return self.pages[url]
        discover_nar_pre_race(now=NOW,policy=self.policy,fetcher=fetch,clock=lambda:NOW)
        self.event.refresh_from_db()
        self.assertEqual(pre._state(self.event,NAR).get('lease_token'),'')
        self.assertEqual(self.event.data_candidates.count(),0)

class HistoricalRosterEvidenceTests(SimpleTestCase):
    def test_fixed_independent_roster_checks_identity_and_all_rows(self):
        import tempfile,json,hashlib
        from unittest.mock import MagicMock,patch
        from django.test import override_settings
        from stable.services.race_source_identity import event_snapshot
        from stable.services.race_data_source_adapters import fetch_bound_observation,parse_jra_observation
        url='https://www.jra.go.jp/datafile/seiseki/replay/2026/102.html'
        route=SourceRoute(dict(provider='jra',operator='jra',region='japan_jra',identity_namespace='jra-race-v1',
            allowed_hosts=['www.jra.go.jp'],allowed_path_prefixes=['/datafile/seiseki/'],venue_aliases={'kyoto':['京都']},
            timezone='Asia/Tokyo',parser_version='test'), 'a'*64)
        page=(ROOT/'jra-result.html').read_text();value=parse_jra_observation(page,url=url,route=route,now=NOW)
        event=SimpleNamespace(pk=123,id=123,year=2026,original_name='みやこS',country_region='japan',racecourse='京都',
            local_date=date(2026,11,8),timezone_name='Asia/Tokyo',source_identities=MagicMock(),runners=MagicMock())
        event.source_identities.filter.return_value.first.return_value=None;event.runners.exists.return_value=False
        entry=dict(event_id=event.pk,event_snapshot_sha256=event_snapshot(event),provider='jra',
            external_race_id=value['external_race_id'],local_date=value['local_date'],
            roster=[[r['number'],r['horse_name']] for r in value['roster']],
            source_url='https://race.netkeiba.com/race/result.html?race_id=202608050211',source_sha256='b'*64)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rosters.json';raw=json.dumps(dict(schema_version=1,items=[entry])).encode();path.write_bytes(raw)
            with override_settings(RACE_DATA_SYNC_JAPAN_HISTORICAL_ROSTER_FILE=str(path),
                RACE_DATA_SYNC_JAPAN_HISTORICAL_ROSTER_SHA256=hashlib.sha256(raw).hexdigest()),patch(
                'stable.services.race_source_identity.seed_evidence',return_value=None),patch(
                'stable.services.race_data_source_adapters.discover_source_url',return_value=url):
                result=fetch_bound_observation(event=event,route=route,now=NOW,fetcher=lambda *a,**kw:page)
                self.assertTrue(result['roster_complete'])
                self.assertEqual(result['roster_evidence']['row_count'],16)
                with override_settings(RACE_DATA_SYNC_JAPAN_HISTORICAL_ROSTER_SHA256='c'*64):
                    with self.assertRaises(ValueError):fetch_bound_observation(event=event,route=route,now=NOW,fetcher=lambda *a,**kw:page)

@override_settings(RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,RACE_DATA_SYNC_SCHEDULER_ENABLED=True,RACE_DATA_SYNC_ALLOW_NETWORK=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,RACE_DATA_SYNC_ENABLED_PROVIDERS=('jra',),
    RACE_DATA_SYNC_ENABLED_REGIONS=('japan_jra',),RACE_DATA_SYNC_ENABLED_DATA_KINDS=('result',))
class JapanHistoricalClaimTests(TestCase):
    def test_historical_claim_is_explicit_scoped_and_regular_window_unchanged(self):
        from stable.test_race_multisource_jra import JraColdStartTests
        from stable.test_race_multisource_identity import NOW as SEPTEMBER
        from stable.services.race_data_sync_control import claim_multisource_events
        from unittest.mock import patch
        from datetime import timedelta
        JraColdStartTests.setUp(self)
        self.fetch=lambda *a,**kw:JraColdStartTests.fetch(self,*a,**kw)
        JraColdStartTests.enroll(self)
        now=SEPTEMBER+timedelta(days=10)
        with patch('django.utils.timezone.now',return_value=now):
            self.assertFalse(claim_multisource_events(event_ids=[self.event.pk+999],now=now,historical=True))
            self.assertFalse(claim_multisource_events(event_ids=[self.event.pk],now=now))
            claims=claim_multisource_events(event_ids=[self.event.pk],now=now,historical=True)
            self.assertEqual([c.event_id for c in claims],[self.event.pk])

class JapanGeneralDiscoveryTests(SimpleTestCase):
    def test_jra_meeting_navigation_is_not_limited_to_featured_races(self):
        from stable.services.race_pre_race import jra_meeting_links,jra_pre_race_links
        event=SimpleNamespace(original_name='アルゼンチン共和国杯',chinese_name='',local_date=date(2026,11,8),
            racecourse='東京',aliases=SimpleNamespace(values_list=lambda *a,**k:[]))
        self.assertEqual(jra_meeting_links((ROOT/'jra-card-index.html').read_text(),event=event),
            ['https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01drl00052026050220261108/30'])
        self.assertEqual(jra_pre_race_links((ROOT/'jra-meeting-index.html').read_text(),event=event),
            ['https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202605021120261108/65'])

    def test_fourth_upcoming_registration_is_discovered_without_manual_race_list(self):
        from stable.services.race_pre_race import jra_pre_race_links,parse_jra_card
        event=SimpleNamespace(original_name='マイルチャンピオンシップ',chinese_name='',local_date=date(2026,11,22),
            racecourse='京都',aliases=SimpleNamespace(values_list=lambda *a,**k:[]))
        links=jra_pre_race_links((ROOT/'jra-registration-index.html').read_text(),event=event)
        self.assertEqual(links,['https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03tde000805061120261122/F5'])
        payload=parse_jra_card((ROOT/'jra-mile-registration.html').read_text(),event=event,url=links[0])
        self.assertEqual(len(payload['items']),21)
        self.assertEqual(payload['items'][-1]['horse_name'],'エルデナリ')
        self.assertEqual(payload['items'][-1]['source_refs']['registration_category'],'地方馬・外国馬1')

class NarGeneralCardTests(TestCase):
    def test_direct_card_does_not_require_graded_topic(self):
        from stable.services.nar_pre_race import fetch_nar_pre_race
        url='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026%2F09%2F01&k_raceNo=10&k_babaCode=10'
        route=SourceRoute(dict(provider='nar',operator='nar',region='japan_nar',identity_namespace='nar-race-v1',
            allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/KeibaWeb/TodayRaceInfo/'],
            venue_aliases={'nar:10':['盛岡']},timezone='Asia/Tokyo',parser_version='test'),'a'*64)
        from stable import models
        event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='nar-direct',country_region='japan',
            original_name='不来方賞',chinese_name='',local_date=date(2026,9,1),racecourse='盛岡',source_refs={'primary':url})
        fetch=lambda u,**k:(ROOT/'nar-card.html').read_text()
        actual,page,payload=fetch_nar_pre_race(event=event,route=route,now=NOW,fetcher=fetch)
        self.assertEqual(actual,url)
        self.assertEqual(payload['stage'],'numbered')
        self.assertEqual(len(payload['items']),11)
        listing='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceList?k_babaCode=10&k_raceDate=2026%2F09%2F01&k_raceNo=10'
        event.source_refs={'primary':listing}
        def listed_fetch(u,**kwargs):
            return (ROOT/('nar-racelist.html' if '/RaceList?' in u else 'nar-card.html')).read_text()
        self.assertEqual(fetch_nar_pre_race(event=event,route=route,now=NOW,fetcher=listed_fetch)[0],url)
        event.source_refs={'primary':listing,'detail':url}
        self.assertEqual(fetch_nar_pre_race(event=event,route=route,now=NOW,fetcher=listed_fetch)[0],url)
        event.source_refs={'primary':url}
        for field,value in [('original_name','別の競走'),('racecourse','金沢'),('local_date',date(2027,9,1))]:
            old=getattr(event,field);setattr(event,field,value)
            with self.subTest(field=field),self.assertRaises(ValueError):
                fetch_nar_pre_race(event=event,route=route,now=NOW,fetcher=fetch)
            setattr(event,field,old)

class JraBindingPriorityTests(SimpleTestCase):
    def test_bound_card_precedes_unpublished_or_unpermitted_annual_index(self):
        from unittest.mock import Mock
        from stable.services.race_data_source_adapters import discover_source_url
        from stable.services.race_pre_race import baseline
        event=SimpleNamespace(pk=1,original_name='武蔵野S',chinese_name='',local_date=date(2026,11,14),racecourse='東京',timezone_name='Asia/Tokyo')
        card='https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202605031120261114/49'
        event.source_refs={'primary':'https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html',
            'jra_pre_race_binding':{'url':card,'baseline':baseline(event)}}
        for paths in [['/JRADB/'],['/JRADB/','/datafile/seiseki/']]:
            fetch=Mock(side_effect=AssertionError('should not fetch annual before validated card'))
            route=SourceRoute(dict(provider='jra',allowed_hosts=['www.jra.go.jp'],allowed_path_prefixes=paths),'a'*64)
            self.assertEqual(discover_source_url(event=event,route=route,now=NOW,fetcher=fetch),card)
            fetch.assert_not_called()
            event.source_refs['jra_pre_race_binding']['url']=REGISTRATION
            with self.assertRaisesRegex(ValueError,'not_published'):
                discover_source_url(event=event,route=route,now=NOW,fetcher=fetch)
            fetch.assert_not_called()
            event.source_refs['jra_pre_race_binding']['url']=card
        conflict='https://www.jra.go.jp/datafile/seiseki/g1/tenno/result/tenno2026.html'
        route=SourceRoute(dict(provider='jra',allowed_hosts=['www.jra.go.jp'],allowed_path_prefixes=['/JRADB/','/datafile/seiseki/']),'a'*64)
        for key in ('primary','reference_urls'):
            event.source_refs={key:[conflict] if key=='reference_urls' else conflict,
                'jra_pre_race_binding':{'url':card,'baseline':baseline(event)}}
            with self.assertRaisesRegex(ValueError,'source_discovery_ambiguous'):
                discover_source_url(event=event,route=route,now=NOW,fetcher=fetch)
        fetch.assert_not_called()

class NarBaneiGeneralTests(SimpleTestCase):
    def test_banei_card_and_result_preserve_hundreds_of_kg_weight(self):
        route=SourceRoute(dict(provider='nar',operator='nar',region='japan_nar',identity_namespace='nar-race-v1',
            allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/KeibaWeb/TodayRaceInfo/'],
            venue_aliases={'nar:3':['帯広','帯広ば']},timezone='Asia/Tokyo',parser_version='test'),'a'*64)
        roster=[]
        for path,endpoint in [('nar-banei-card.html','DebaTable'),('nar-banei-result.html','RaceMarkTable')]:
            url=f'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/{endpoint}?k_raceDate=2026%2F11%2F01&k_raceNo=1&k_babaCode=3'
            result=parse_nar_observation((ROOT/path).read_text(),url=url,route=route,now=NOW)
            self.assertEqual(result['venue_key'],'nar:3')
            self.assertTrue(all(float(r['carried_weight'].replace('kg','').lstrip('☆★▲△◇◆ '))>100 for r in result['roster']))
            roster.append(sorted((r['number'],r['horse_name']) for r in result['roster']))
        self.assertEqual(roster[0],roster[1])
        self.assertGreater(len(roster[0]),1)

class HostReservationTests(SimpleTestCase):
    def test_early_wakeup_waits_again_without_bypassing_reservation(self):
        from unittest.mock import patch
        from datetime import timedelta
        from stable.services.race_pre_race import _reserve_pre_race_request
        blocked=SimpleNamespace(reserved=False,reason='rate_limited',next_allowed_at=NOW+timedelta(seconds=2))
        accepted=SimpleNamespace(reserved=True)
        with patch('stable.services.race_events.reserve_race_live_host_request',side_effect=[blocked,blocked,accepted]) as reserve, patch('django.utils.timezone.now',side_effect=[NOW,NOW,NOW,NOW+timedelta(seconds=1.8),NOW]), patch('time.sleep') as sleep:
            self.assertIs(_reserve_pre_race_request('www.jra.go.jp'),accepted)
            self.assertEqual(reserve.call_count,3)
            self.assertEqual(sleep.call_count,2)

    def test_circuit_or_long_delay_stops_without_sleep(self):
        from unittest.mock import patch
        from datetime import timedelta
        from stable.services.race_pre_race import _reserve_pre_race_request,JraFetchError
        for reason in ['circuit_open','rate_limited']:
            blocked=SimpleNamespace(reserved=False,reason=reason,next_allowed_at=NOW+timedelta(seconds=30))
            with patch('stable.services.race_events.reserve_race_live_host_request',return_value=blocked), patch('django.utils.timezone.now',return_value=NOW), patch('time.sleep') as sleep:
                with self.assertRaisesRegex(JraFetchError,'jra_host_'+reason):_reserve_pre_race_request('www.jra.go.jp')
                sleep.assert_not_called()

class JapanGeneralIdentityTests(TestCase):
    def test_nar_only_numbered_verified_candidate_can_seed_identity(self):
        from stable import models
        from stable.services.race_source_identity import seed_evidence
        from stable.services.race_pre_race import baseline
        event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='nar-seed',country_region='japan',
            original_name='不来方賞',local_date=date(2026,9,1),racecourse='盛岡',timezone_name='Asia/Tokyo')
        url='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026%2F09%2F01&k_raceNo=10&k_babaCode=10'
        candidate=event.data_candidates.create(module='runners',source_name='nar_pre_race_v1',source_url=url,
            candidate_payload={'items':[{'horse_name':'テスト馬','horse_number':'1'}]},
            raw_payload={'nar_pre_race_v1':{'validated':True,'baseline':baseline(event),'raw_sha256':'a'*64,'stage':'registration'}})
        self.assertIsNone(seed_evidence(event))
        candidate.raw_payload['nar_pre_race_v1']['stage']='numbered';candidate.save()
        self.assertEqual(seed_evidence(event)['candidate_id'],candidate.pk)
        candidate.candidate_payload['items'][0]['horse_number']='';candidate.save()
        self.assertIsNone(seed_evidence(event))
        from stable.services.race_data_source_adapters import fetch_bound_observation
        from stable.services.race_source_identity import resolve_observation
        route=SourceRoute(dict(provider='nar',operator='nar',region='japan_nar',country_region='japan',identity_namespace='nar-race-v1',
            valid_from='2026-01-01T00:00:00Z',valid_until='2027-01-01T00:00:00Z',
            allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/KeibaWeb/TodayRaceInfo/'],
            venue_aliases={'nar:10':['盛岡']},timezone='Asia/Tokyo',parser_version='test'),'a'*64)
        page=(ROOT/'nar-card.html').read_text()
        parsed=parse_nar_observation(page,url=url,route=route,now=NOW)
        candidate.candidate_payload={'items':[{'horse_name':r['horse_name'],'horse_number':r['number']} for r in parsed['roster']]}
        candidate.save();event.source_refs={'primary':url};event.save()
        observation=fetch_bound_observation(event=event,route=route,now=NOW,kind='racecard',fetcher=lambda *a,**k:page)
        self.assertEqual(resolve_observation(observation,route=route,now=NOW).event_id,event.pk)

class JraOrdinaryMeetingTests(SimpleTestCase):
    def test_conditions_are_separate_and_existing_time_disambiguates(self):
        from datetime import time
        from stable.services.race_pre_race import jra_pre_race_links
        event=SimpleNamespace(original_name='3歳以上1勝クラス',chinese_name='',racecourse='東京',
            local_date=date(2026,11,8),local_start_time=None,race_datetime=None,
            aliases=SimpleNamespace(values_list=lambda *a,**k:[]))
        page=(ROOT/'jra-meeting-index.html').read_text()
        with self.assertRaisesRegex(ValueError,'jra_race_identity_ambiguous'):
            jra_pre_race_links(page,event=event)
        event.local_start_time=time(12,50)
        self.assertEqual(jra_pre_race_links(page,event=event),['https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202605020620261108/9C'])
