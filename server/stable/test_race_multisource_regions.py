"""多地区离线合同；标注为 synthetic 的变体不作为生产抓取/条款 proof。"""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from stable import models
from stable.test_race_multisource_identity import NOW, policy_payload
from stable.services.race_data_source_adapters import (
    parse_multisource_policy,
    parse_reference_observation,
    parse_nar_observation,
    parse_hkjc_observation,
    discover_source_url,
)
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_source_identity import identity_key

ROOT = Path(__file__).parent


def route_for(provider, region, country, zone, venue, names, host, prefix, kinds=()):
    data = policy_payload(provider, region, kinds=kinds)
    data["routes"][0].update(
        country_region=country,
        operator={"japan_nar": "nar", "hong_kong": "hkjc"}.get(region, region),
        source_class=(
            "licensed_api"
            if provider == "the_racing_api"
            else (
                "official_operator"
                if provider in ("jra", "nar", "hkjc", "official")
                else "trusted_publisher"
            )
        ),
        timezone=zone,
        venue_aliases={venue: names},
        allowed_hosts=[host],
        allowed_path_prefixes=[prefix],
    )
    return parse_multisource_policy(data, now=NOW).routes[0]


class RegionAdapterTests(TestCase):
    def zeturf_directory_case(self):
        route = route_for('zeturf', 'france', 'france', 'Europe/Paris',
                          'paris-longchamp', ['ParisLongchamp', 'Paris-Longchamp'],
                          'www.zeturf.fr', '/fr/')
        index = 'https://www.zeturf.fr/fr/resultats-et-rapports-du-jour/2026-09-20'
        meeting = 'https://www.zeturf.fr/fr/reunion-du-jour/2026-09-20/R1-paris-longchamp'
        detail = 'https://www.zeturf.fr/fr/course-du-jour/2026-09-20/R1C5-exact-race'
        route.payload['discovery_urls_by_date'] = {'2026-09-20': [index]}
        event = SimpleNamespace(original_name='Exact Race', chinese_name='', source_refs={},
                                local_date=date(2026, 9, 20), racecourse='ParisLongchamp')
        return route, event, index, meeting, detail

    def test_zeturf_directory_uses_same_day_venue_and_exact_race(self):
        route, event, index, meeting, detail = self.zeturf_directory_case()
        pages = {index: f'<a href="{meeting}#races">R1</a><a href="{meeting}#results">Results</a>'
                 f'<a href="{meeting.replace("2026-09-20", "2026-09-21")}">Today</a>',
                 meeting: f'<a href="{detail}">Exact Race</a>'
                 f'<a href="{detail.replace("R1C5", "R2C5")}">Exact Race</a>'
                 f'<a href="{detail.replace("2026-09-20", "2026-09-21")}">Exact Race</a>'}
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            return pages[url]
        self.assertEqual(discover_source_url(event=event, route=route, now=NOW, fetcher=fetch), detail)
        self.assertEqual(calls, [index, meeting])
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())

    def test_zeturf_programme_and_result_switch_at_local_midnight(self):
        route, event, historical, meeting, detail = self.zeturf_directory_case()
        programme = 'https://www.zeturf.fr/fr/programmes-et-pronostics-du-jour'
        route.payload['discovery_urls_by_date'] = {'2026-09-20': [historical, programme]}
        for now, selected in ((datetime(2026,9,19,20,tzinfo=timezone.utc), programme),
                              (datetime(2026,9,20,20,tzinfo=timezone.utc), programme),
                              (datetime(2026,9,20,22,tzinfo=timezone.utc), historical)):
            with self.subTest(now=now):
                calls = []
                pages = {selected: f'<a href="{meeting}">Meeting</a>',
                         meeting: f'<a href="{detail}">Exact Race</a>'}
                def fetch(url, **kwargs):
                    calls.append(url)
                    return pages[url]
                self.assertEqual(discover_source_url(event=event, route=route, now=now, fetcher=fetch), detail)
                self.assertEqual(calls, [selected, meeting])

    def test_zeturf_directory_rejects_unmatched_or_ambiguous_meetings_before_fetch(self):
        route, event, index, meeting, detail = self.zeturf_directory_case()
        for target in (meeting.replace('2026-09-20', '2026-09-19'),
                       meeting.replace('paris-longchamp', 'strasbourg'),
                       meeting.replace('www.zeturf.fr', 'foreign.invalid'), meeting+'?other=1'):
            calls = []
            def fetch(url, **kwargs):
                calls.append(url)
                return f'<a href="{target}">R1</a>'
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'source_not_found'):
                discover_source_url(event=event, route=route, now=NOW, fetcher=fetch)
            self.assertEqual(calls, [index])
        with self.assertRaisesRegex(ValueError, 'source_discovery_ambiguous'):
            discover_source_url(event=event, route=route, now=NOW, fetcher=lambda *a, **k:
                f'<a href="{meeting}">R1</a><a href="{meeting.replace("R1-", "R2-")}#results">R2</a>')

    def test_zeturf_directory_keeps_name_and_detail_permission_checks(self):
        route, event, index, meeting, detail = self.zeturf_directory_case()
        for markup in (f'<a href="{detail}">Sponsored Exact Race</a>',
                       f'<a href="{detail.replace("www.zeturf.fr", "foreign.invalid")}">Exact Race</a>',
                       f'<a href="{detail}?x=1">Exact Race</a>',
                       f'<a href="{detail}">Exact Race</a><a href="{detail.replace("C5-", "C6-")}">Exact Race</a>'):
            with self.subTest(markup=markup), self.assertRaises(ValueError):
                discover_source_url(event=event, route=route, now=NOW, fetcher=lambda url, **k:
                    f'<a href="{meeting}">R1</a>' if url == index else markup)

    def test_real_sporting_cards_uk_us_and_synthetic_ireland_independent_route(self):
        from stable.race_reference_parsers.sporting_life import _next_data
        import json

        for file, region, country, zone, course, day, url in [
            (
                "sl-969.html",
                "united_kingdom",
                "united_kingdom",
                "Europe/London",
                "Ayr",
                date(2026, 9, 19),
                "https://www.sportinglife.com/racing/racecards/2026-09-19/ayr/racecard/939242/firth-of-clyde",
            ),
            (
                "sl-491.html",
                "united_states",
                "united_states",
                "America/New_York",
                "Belmont Park",
                date(2026, 9, 18),
                "https://www.sportinglife.com/racing/racecards/2026-09-18/belmont-at-the-big-a/racecard/939192/jockey-club-gold-cup",
            ),
            (
                "sl-969.html",
                "ireland",
                "other",
                "Europe/Dublin",
                "Curragh",
                date(2026, 9, 19),
                "https://www.sportinglife.com/racing/racecards/2026-09-19/curragh/racecard/939242/contract-example",
            ),
        ]:
            with self.subTest(region=region):
                page = (ROOT / "tests/fixtures/pre_race_refresh" / file).read_text()
                data = _next_data(page)
                summary = data["props"]["pageProps"]["race"]["race_summary"]
                if region == "ireland":
                    summary["course_name"] = "Curragh"
                    page = (
                        '<html><body><script id="__NEXT_DATA__">'
                        + json.dumps(data)
                        + "</script></body></html>"
                    )
                if region == "united_states":
                    url = url.replace(
                        "939192", str(summary["race_summary_reference"]["id"])
                    )
                route = route_for(
                    "sporting_life",
                    region,
                    country,
                    zone,
                    course,
                    [course],
                    "www.sportinglife.com",
                    "/racing/",
                )
                event = SimpleNamespace(
                    local_date=day, timezone_name=zone, race_datetime=None
                )
                value = parse_reference_observation(
                    page, url=url, route=route, now=NOW, event=event
                )
                self.assertEqual(value["region"], region)
                self.assertTrue(value["roster"])
                self.assertEqual(value["result_phase"], "")
                self.assertTrue(value["roster_complete"])

    def test_real_zeturf_gallop_and_synthetic_trot_exclusion(self):
        route = route_for(
            "zeturf",
            "france",
            "france",
            "Europe/Paris",
            "chantilly",
            ["Chantilly"],
            "www.zeturf.fr",
            "/fr/course-du-jour/",
        )
        page = (ROOT / "tests/fixtures/pre_race_refresh/zt-770.html").read_text()
        url = "https://www.zeturf.fr/fr/course-du-jour/2026-09-19/R1C3-chantilly-prix-eclipse"
        with self.assertRaisesRegex(RuntimeError, "uniquely prove"):
            parse_reference_observation(page, url=url, route=route, now=NOW)
        # 缩减旧 fixture 未保留 canonical；此行是标注过的合同变体，不是原站实测。
        page = page.replace("<head>", '<head><link rel="canonical" href="' + url + '">')
        value = parse_reference_observation(page, url=url, route=route, now=NOW)
        self.assertEqual((value["meeting_session"], value["race_number"]), ("1", "3"))
        self.assertEqual(value["result_phase"], "")
        with self.assertRaisesMessage(ValueError, "unsupported_race_type"):
            parse_reference_observation(
                page.replace("<title>", "<title>Trot attelé "),
                url=url,
                route=route,
                now=NOW,
            )

    def test_nar_real_roster_plus_synthetic_title_does_not_use_jra_operator(self):
        route = route_for(
            "nar",
            "japan_nar",
            "japan",
            "Asia/Tokyo",
            "nar:22",
            ["金沢", "金 沢", "金泽"],
            "www.keiba.go.jp",
            "/KeibaWeb/",
        )
        page = (
            (ROOT / "tests/fixtures/pre_race_refresh/nar.html")
            .read_text()
            .replace("<body>", "<body><h2>白山大賞典</h2>")
        )
        url = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11"
        value = parse_nar_observation(page, url=url, route=route, now=NOW)
        self.assertEqual(len(value["roster"]), 12)
        self.assertEqual(value["external_race_id"], "nar:2026-09-22:22:11")
        with self.assertRaisesMessage(ValueError, "nar_course_code_mismatch"):
            parse_nar_observation(
                page, url=url.replace("Code=22", "Code=20"), route=route, now=NOW
            )

    def test_hkjc_fixture_plus_synthetic_date_header(self):
        route = route_for(
            "hkjc",
            "hong_kong",
            "hong_kong",
            "Asia/Hong_Kong",
            "hkjc:HV",
            ["Happy Valley", "跑馬地", "跑马地"],
            "racing.hkjc.com",
            "/racing/",
        )
        page = (
            (ROOT / "fixtures/hkjc/html/localresults-race-sample.html")
            .read_text()
            .replace("<body>", "<body><p>2026/06/21</p>")
        )
        value = parse_hkjc_observation(
            page,
            url="https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx?RaceDate=2026/06/21&Racecourse=HV&RaceNo=1",
            route=route,
            now=NOW,
        )
        self.assertEqual(value["external_race_id"], "HK20260621HV01")
        self.assertEqual(value["race_number"], "1")
        self.assertTrue(value["roster"])

    def test_explicit_discovery_date_selects_historical_page(self):
        payload=policy_payload()
        payload['routes'][0]['discovery_urls_by_date']={
            '2026-09-01':['https://www.jra.go.jp/JRADB/day1.html'],
            '2026-09-20':['https://www.jra.go.jp/JRADB/day20.html']}
        route=parse_multisource_policy(payload,now=NOW).routes[0]
        event=SimpleNamespace(original_name='オールカマー',chinese_name='',source_refs={},local_date=date(2026,9,1))
        calls=[]
        def fetch(url, **kwargs):
            calls.append(url)
            return '<a href="/JRADB/detail.html">オールカマー</a>'
        self.assertEqual(discover_source_url(event=event,route=route,now=NOW,fetcher=fetch),
                         'https://www.jra.go.jp/JRADB/detail.html')
        self.assertEqual(calls,['https://www.jra.go.jp/JRADB/day1.html'])
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())

    def test_missing_explicit_date_does_not_fetch_generic_fallback(self):
        payload=policy_payload()
        payload['routes'][0].update(discovery_urls=['https://www.jra.go.jp/JRADB/generic.html'],
            discovery_urls_by_date={'2026-09-01':['https://www.jra.go.jp/JRADB/day1.html']})
        route=parse_multisource_policy(payload,now=NOW).routes[0]
        event=SimpleNamespace(original_name='x',chinese_name='',source_refs={},local_date=date(2026,9,2))
        from unittest.mock import Mock
        fetch=Mock()
        with self.assertRaisesRegex(ValueError,'source_discovery_date_missing'):
            discover_source_url(event=event,route=route,now=NOW,fetcher=fetch)
        fetch.assert_not_called()

    def test_date_pages_must_resolve_one_detail_across_all_pages(self):
        payload=policy_payload()
        payload['routes'][0]['discovery_urls_by_date']={'2026-09-01':[
            'https://www.jra.go.jp/JRADB/one.html','https://www.jra.go.jp/JRADB/two.html']}
        route=parse_multisource_policy(payload,now=NOW).routes[0]
        event=SimpleNamespace(original_name='same',chinese_name='',source_refs={},local_date=date(2026,9,1))
        calls=[]
        def fetch(url, **kwargs):
            calls.append(url)
            return '<a href="'+url.replace('.html','-detail.html')+'">same</a>'
        with self.assertRaisesRegex(ValueError,'source_discovery_ambiguous'):
            discover_source_url(event=event,route=route,now=NOW,fetcher=fetch)
        self.assertEqual(len(calls),2)

    def test_date_discovery_rejects_invalid_date_and_foreign_host(self):
        for dates in ({'2026-02-30':['https://www.jra.go.jp/JRADB/day.html']},
                      {'2026-09-01':['https://foreign.invalid/JRADB/day.html']}):
            payload=policy_payload();payload['routes'][0]['discovery_urls_by_date']=dates
            with self.assertRaises(ValueError):parse_multisource_policy(payload,now=NOW)

    def test_discovery_uses_provider_race_title_not_link_metadata(self):
        cases = [
            ('sporting_life', 'united_kingdom', 'Europe/London', 'www.sportinglife.com',
             '/racing/', '/racing/racecards/2026-09-20/venue/racecard/123/race',
             '<span>12:40</span><span data-testid="racecard-meeting-race-name">Exact Race<span>4 Runners, Class 3</span></span>'),
            ('galopp_statistik', 'germany', 'Europe/Berlin', 'www.galopp-statistik.de',
             '/RennenDetails.php', '/RennenDetails.php?Datum=2026-09-20&Ort=Bad&Nummer=6',
             '<div class="nr-des-rennens">6</div><div class="titel-des-rennens">Exact Race</div><div>15:55 55000 EUR</div>'),
        ]
        cases.append(('galopp_statistik', 'germany', 'Europe/Berlin', 'www.galopp-statistik.de',
                      '/DisplayErgebnis.php', '/DisplayErgebnis.php?id=14631',
                      '<div class="nr-des-rennens">5</div><div class="titel-des-rennens">Exact Race</div><div>15:45 55000 EUR</div>'))
        for provider, region, zone, host, prefix, detail, markup in cases:
            with self.subTest(provider=provider):
                route=route_for(provider,region,region,zone,'venue',['Venue'],host,prefix)
                route.payload['discovery_urls']=['https://'+host+prefix+'index']
                event=SimpleNamespace(original_name='Exact Race',chinese_name='',source_refs={},local_date=date(2026,9,20))
                page='<a href="'+detail+'">'+markup+'</a>'
                self.assertEqual(discover_source_url(event=event,route=route,now=NOW,fetcher=lambda *a,**k:page),'https://'+host+detail)
                event.original_name='Exact'
                with self.assertRaisesRegex(ValueError,'source_not_found'):
                    discover_source_url(event=event,route=route,now=NOW,fetcher=lambda *a,**k:page)
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())

    def test_hkjc_declared_pair_switches_at_hong_kong_midnight(self):
        from datetime import datetime, timezone
        card = 'https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/10/28&Racecourse=ST&RaceNo=1'
        result = card.replace('/racecard?', '/localresults?')
        route = route_for('hkjc','hong_kong','hong_kong','Asia/Hong_Kong',
                          'hkjc:ST',['Sha Tin'],'racing.hkjc.com','/en-us/local/information/')
        route.payload['discovery_urls_by_date'] = {'2026-10-28':[card,result]}
        event = SimpleNamespace(original_name='Target', chinese_name='', source_refs={},
                                local_date=date(2026,10,28), racecourse='Sha Tin')
        for hour, expected in [(15,card),(16,result)]:
            calls = []
            with patch('stable.services.race_data_source_adapters.discover_hkjc_meeting',
                       return_value={expected}):
                discover_source_url(event=event,route=route,
                    now=datetime(2026,10,28,hour,tzinfo=timezone.utc),
                    fetcher=lambda url,**kw: calls.append(url) or '')
            self.assertEqual(calls,[expected])
        route.payload['discovery_urls_by_date'] = {'2026-10-28':[card]}
        calls.clear()
        with patch('stable.services.race_data_source_adapters.discover_hkjc_meeting',return_value={card}):
            discover_source_url(event=event,route=route,
                now=datetime(2026,10,29,tzinfo=timezone.utc),
                fetcher=lambda url,**kw: calls.append(url) or '')
        self.assertEqual(calls,[card])

    def test_hkjc_image_navigation_uses_same_meeting_pages_with_bounded_requests(self):
        from datetime import datetime, timezone
        base = 'https://racing.hkjc.com/en-us/local/information/racecard'
        index = base+'?racedate=2026/10/28&Racecourse=ST&RaceNo=1'
        detail = base+'?racedate=2026/10/28&Racecourse=ST&RaceNo=2'
        route = route_for('hkjc','hong_kong','hong_kong','Asia/Hong_Kong',
                          'hkjc:ST',['Sha Tin'],'racing.hkjc.com','/en-us/local/information/')
        route.payload['valid_until'] = '2026-11-30T00:00:00+00:00'
        route.payload['discovery_urls_by_date'] = {'2026-10-28':[index]}
        event = SimpleNamespace(original_name='Target Race', chinese_name='', source_refs={},
            local_date=date(2026,10,28), racecourse='Sha Tin')
        page = (ROOT/'tests/fixtures/regional_lifecycle/hk-card.html').read_text()
        target = page.replace('Race 1 - WA MEI SHAN HANDICAP','Race 2 - Target Race')
        links = '<a href="'+detail+'"><img src="race2.gif"></a>'
        for rejected in [detail.replace('ST','HV'),detail.replace('10/28','10/29'),
                         detail.replace('racing.hkjc.com','unapproved.test')]:
            links += '<a href="'+rejected+'"><img></a>'
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            return page+links if url == index else target
        now = datetime(2026,10,28,tzinfo=timezone.utc)
        self.assertEqual(discover_source_url(event=event,route=route,now=now,fetcher=fetch), detail)
        self.assertEqual(calls,[index,detail])
        excessive = ''.join('<a href="'+base+'?racedate=2026/10/28&Racecourse=ST&RaceNo='+str(n)+'"><img></a>' for n in range(2,13))
        calls.clear()
        with self.assertRaisesRegex(ValueError,'hkjc_discovery_page_limit'):
            discover_source_url(event=event,route=route,now=now,
                fetcher=lambda url,**kw: calls.append(url) or page+excessive)
        self.assertEqual(calls,[index])

    def test_sporting_discovery_rolls_declared_pair_by_route_local_date(self):
        from datetime import datetime, timezone
        card_index = 'https://www.sportinglife.com/racing/racecards'
        result_index = 'https://www.sportinglife.com/racing/results/2026-09-20'
        event = SimpleNamespace(original_name='Exact Race', chinese_name='',
                                source_refs={}, local_date=date(2026, 9, 20))
        now = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)
        for zone, selected in [('Europe/London', result_index),
                               ('America/Los_Angeles', card_index)]:
            with self.subTest(zone=zone):
                route = route_for('sporting_life', 'united_states', 'united_states',
                                  zone, 'venue', ['Venue'], 'www.sportinglife.com', '/racing/')
                route.payload['discovery_urls_by_date'] = {
                    '2026-09-20': [card_index, result_index]}
                calls = []
                def fetch(url, **kwargs):
                    calls.append(url)
                    return '<a href="/racing/results/2026-09-20/venue/123/exact">Exact Race</a>'
                discover_source_url(event=event, route=route, now=now, fetcher=fetch)
                self.assertEqual(calls, [selected])
        # A legacy single-entry policy cannot authorize a synthesized result URL.
        route.payload['discovery_urls_by_date'] = {'2026-09-20': [card_index]}
        calls.clear()
        discover_source_url(event=event, route=route, now=now, fetcher=fetch)
        self.assertEqual(calls, [card_index])

    def test_sporting_rollover_ignores_old_card_hints_and_bindings(self):
        from datetime import datetime, timezone
        from unittest.mock import Mock
        from stable.services.race_data_source_adapters import fetch_bound_observation
        card = 'https://www.sportinglife.com/racing/racecards/2026-09-20/venue/racecard/123/exact'
        index = 'https://www.sportinglife.com/racing/results/2026-09-20'
        detail = 'https://www.sportinglife.com/racing/results/2026-09-20/venue/123/exact'
        route = route_for('sporting_life', 'united_kingdom', 'united_kingdom',
                          'Europe/London', 'venue', ['Venue'], 'www.sportinglife.com', '/racing/')
        route.payload['discovery_urls_by_date'] = {'2026-09-20': [
            'https://www.sportinglife.com/racing/racecards', index]}
        now = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)
        for binding in ['source', 'seed', 'primary']:
            with self.subTest(binding=binding):
                sources = Mock()
                sources.filter.return_value.first.return_value = (
                    SimpleNamespace(canonical_url=card) if binding == 'source' else None)
                event = SimpleNamespace(original_name='Exact Race', chinese_name='',
                    source_refs={'primary': card} if binding == 'primary' else {},
                    local_date=date(2026, 9, 20), source_identities=sources)
                calls = []
                def fetch(url, **kwargs):
                    calls.append(url)
                    return '<a href="'+detail+'">Exact Race</a>'
                with patch('stable.services.race_source_identity.seed_evidence',
                           return_value={'canonical_url':card} if binding == 'seed' else None), \
                     patch('stable.services.race_data_source_adapters.parse_reference_observation',
                           side_effect=RuntimeError('parser_reached')):
                    with self.assertRaisesRegex(RuntimeError, 'parser_reached'):
                        fetch_bound_observation(event=event, route=route, now=now, fetcher=fetch)
                self.assertEqual(calls, [index, detail])

    def test_sporting_rollover_preserves_verified_seed_identity_receipt(self):
        from datetime import datetime, timezone
        from stable.services.race_data_source_adapters import fetch_bound_observation
        from stable.services.race_source_identity import event_snapshot, resolve_observation
        from stable.test_race_multisource_identity import observation
        now = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)
        card = 'https://www.sportinglife.com/racing/racecards/2026-09-20/venue/racecard/123/exact'
        index = 'https://www.sportinglife.com/racing/results/2026-09-20'
        detail = 'https://www.sportinglife.com/racing/results/2026-09-20/venue/123/exact'
        route = route_for('sporting_life', 'united_kingdom', 'united_kingdom',
                          'Europe/London', 'venue', ['Venue'], 'www.sportinglife.com', '/racing/')
        route.payload['discovery_urls_by_date'] = {'2026-09-20': [
            'https://www.sportinglife.com/racing/racecards', index]}
        event = models.RaceEvent.objects.create(year=2026, slug='sl-seed',
            original_name='Exact Race', country_region='united_kingdom', racecourse='Venue',
            local_date=date(2026, 9, 20), timezone_name='Europe/London', status='scheduled')
        previous = dict(candidate_id=1, event_snapshot_sha256=event_snapshot(event),
                        raw_sha256='e'*64, canonical_url=card, roster=[('1', 'horse')])
        value = observation('sporting_life', region=route.region, operator=route.operator,
            canonical_url=detail, external_race_id='123', venue_key='venue',
            timezone=route.timezone, fetched_at=now.isoformat(), raw_names=['Exact Race'],
            roster=[{'number':'1', 'horse_name':'Horse'}], result_phase='official')
        def fetch(url, **kwargs):
            return '<a href="'+detail+'">Exact Race</a>' if url == index else ''
        with patch('stable.services.race_source_identity.seed_evidence', return_value=previous), \
             patch('stable.services.race_data_source_adapters.parse_reference_observation',
                   side_effect=lambda *a, **k: dict(value)):
            result = fetch_bound_observation(event=event, route=route, now=now, fetcher=fetch)
            self.assertEqual(result['identity_seed_receipt']['link_chain'], [card, detail])
            self.assertEqual(resolve_observation(result, route=route, now=now).event_id, event.pk)
            for bad in [card.replace('/123/', '/999/'), card.replace('/venue/', '/other/')]:
                previous['canonical_url'] = bad
                with self.assertRaisesRegex(ValueError, 'linked_result_identity_mismatch'):
                    fetch_bound_observation(event=event, route=route, now=now, fetcher=fetch)

    def test_sporting_life_result_discovery_uses_exact_structured_name_and_actual_link(self):
        import json
        route=route_for('sporting_life','united_kingdom','united_kingdom','Europe/London',
                        'venue',['Venue'],'www.sportinglife.com','/racing/')
        route.payload['discovery_urls_by_date']={'2026-09-20':['https://www.sportinglife.com/racing/results/2026-09-20']}
        event=SimpleNamespace(original_name='Exact Race',chinese_name='',source_refs={},local_date=date(2026,9,20))
        detail='https://www.sportinglife.com/racing/results/2026-09-20/venue/123/exact-race'
        data={'props':{'pageProps':{'meetings':[{'races':[{'name':'Exact Race','race_summary_reference':{'id':123}}]}]}}}
        page='<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script><a href="'+detail+'">Results 12:40</a>'
        self.assertEqual(discover_source_url(event=event,route=route,now=NOW,fetcher=lambda *a,**k:page),detail)
        for bad in (page.replace('Exact Race','Exact Race Extra'),page.replace('/123/', '/124/')):
            with self.assertRaisesRegex(ValueError,'source_not_found'):
                discover_source_url(event=event,route=route,now=NOW,fetcher=lambda *a,**k:bad)
        duplicate=page+'<a href="'+detail.replace('exact-race','other')+'">Results</a>'
        with self.assertRaisesRegex(ValueError,'source_discovery_ambiguous'):
            discover_source_url(event=event,route=route,now=NOW,fetcher=lambda *a,**k:duplicate)
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())

    def test_declared_discovery_index_hint_is_not_returned_as_race_detail(self):
        route=route_for('jra','japan_jra','japan','Asia/Tokyo','nakayama',['中山'],
                        'www.jra.go.jp','/JRADB/')
        index='https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html'
        route.payload['allowed_path_prefixes']=['/datafile/seiseki/replay/', '/JRADB/']
        route.payload['discovery_urls_by_date']={'2026-09-20':[index]}
        event=SimpleNamespace(original_name='Exact Race',chinese_name='',source_refs={'primary':index},local_date=date(2026,9,20))
        detail='https://www.jra.go.jp/JRADB/detail.html'
        self.assertEqual(discover_source_url(event=event,route=route,now=NOW,
            fetcher=lambda *a,**k:'<a href="'+detail+'">Exact Race</a>'),detail)

    def test_discovery_uses_only_current_evidenced_approved_series_aliases(self):
        series=models.RaceSeries.objects.create(key='test-source-alias',country_region='france',
            canonical_name_original='Canonical Race',review_status='approved')
        alias=models.RaceSeriesName.objects.create(series=series,text='Sponsored Exact Race',
            valid_from_year=2026,valid_to_year=2026,source_refs={'official':'https://source.example/evidence'})
        route=route_for('zeturf','france','france','Europe/Paris','chantilly',['Chantilly'],
                        'www.zeturf.fr','/fr/')
        route.payload['discovery_urls']=['https://www.zeturf.fr/fr/index']
        event=SimpleNamespace(original_name='Canonical Race',chinese_name='',source_refs={},
            local_date=date(2026,9,19),edition_year=2026,race_series_id=series.pk)
        detail='https://www.zeturf.fr/fr/course-du-jour/exact'
        fetch=lambda *a,**k:'<a href="'+detail+'">Sponsored Exact Race</a>'
        self.assertEqual(discover_source_url(event=event,route=route,now=NOW,fetcher=fetch),detail)
        for changes in ({'is_active':False},{'source_refs':{}},{'valid_from_year':2024,'valid_to_year':2025},{'valid_from_year':2027,'valid_to_year':2028}):
            for field,value in changes.items():setattr(alias,field,value)
            alias.save()
            with self.assertRaisesRegex(ValueError,'source_not_found'):
                discover_source_url(event=event,route=route,now=NOW,fetcher=fetch)
            alias.is_active=True;alias.source_refs={'official':'https://source.example/evidence'}
            alias.valid_from_year=2026;alias.valid_to_year=2026;alias.save()
        series.review_status='pending';series.save()
        with self.assertRaisesRegex(ValueError,'source_not_found'):
            discover_source_url(event=event,route=route,now=NOW,fetcher=fetch)
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())

    def test_discovery_names_only_select_request_never_identity(self):

        payload = policy_payload()
        payload["routes"][0]["discovery_urls"] = [
            "https://www.jra.go.jp/JRADB/index.html"
        ]
        route = parse_multisource_policy(payload, now=NOW).routes[0]
        event = SimpleNamespace(
            original_name="オールカマー",
            chinese_name="",
            source_refs={},
            local_date=date(2026, 9, 20),
        )
        fetch = lambda *a, **kw: '<a href="/JRADB/real-detail.html">オールカマー</a>'
        self.assertEqual(
            discover_source_url(event=event, route=route, now=NOW, fetcher=fetch),
            "https://www.jra.go.jp/JRADB/real-detail.html",
        )
        self.assertFalse(models.RaceResultSourceIdentity.objects.exists())


@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("official", "the_racing_api"),
)
class SevenBucketDedupTests(TestCase):
    def setUp(self):
        clock=patch("django.utils.timezone.now",return_value=NOW)
        clock.start();self.addCleanup(clock.stop)

    def test_all_buckets_both_arrival_orders_cross_language_one_event_owner(self):
        buckets = [
            ("japan_jra", "japan", "Asia/Tokyo"),
            ("japan_nar", "japan", "Asia/Tokyo"),
            ("hong_kong", "hong_kong", "Asia/Hong_Kong"),
            ("united_kingdom", "united_kingdom", "Europe/London"),
            ("ireland", "other", "Europe/Dublin"),
            ("france", "france", "Europe/Paris"),
            ("united_states", "united_states", "America/New_York"),
        ]
        for region, country, zone in buckets:
            for order in [
                ("official", "the_racing_api"),
                ("the_racing_api", "official"),
            ]:
                with self.subTest(region=region, order=order), override_settings(
                    RACE_DATA_SYNC_ENABLED_REGIONS=(region,)
                ):
                    event = models.RaceEvent.objects.create(
                        year=2026,
                        slug=region + "-" + order[0],
                        original_name="原名",
                        country_region=country,
                        racecourse=region,
                        local_date=date(2026, 9, 20),
                        timezone_name=zone,
                        visibility_status="published",
                    )
                    payload = policy_payload()
                    payload["routes"] = []
                    for provider in order:
                        route = route_for(
                            provider,
                            region,
                            country,
                            zone,
                            region,
                            [region],
                            "www.example.com",
                            "/races/",
                        )
                        payload["routes"].append(route.payload)
                    policy = parse_multisource_policy(payload, now=NOW)
                    value = dict(
                        region=region,
                        operator=region,
                        venue_key=region,
                        local_date="2026-09-20",
                        timezone=zone,
                        meeting_session=order[0],
                        race_number="1",
                        raw_names=["原名"],
                        fetched_at=NOW.isoformat(),
                        raw_sha256="d" * 64,
                        parser_version="test-v1",
                    )
                    models.RaceEventIdentityKey.objects.create(
                        event=event,
                        **identity_key(value),
                        evidence={"fixture": "synthetic reviewed key"},
                        matcher_version="v2"
                    )
                    for index, provider in enumerate(order):
                        observation = {
                            **value,
                            "provider": provider,
                            "operator": policy.routes[index].operator,
                            "identity_namespace": provider + "-race-v1",
                            "external_race_id": event.slug,
                            "canonical_url": "https://www.example.com/races/"
                            + event.slug,
                            "raw_names": ["完全不同语种" if index else "原名"],
                        }
                        # NAR/HKJC canonical operator is shared by all providers.
                        if index == 0 and observation["operator"] != value["operator"]:
                            models.RaceEventIdentityKey.objects.filter(
                                event=event
                            ).delete()
                            models.RaceEventIdentityKey.objects.create(
                                event=event,
                                **identity_key(observation),
                                evidence={"fixture": "synthetic reviewed key"},
                                matcher_version="v2"
                            )
                        decision = attach_multisource_observation(
                            observation, policy=policy, now=NOW
                        )
                        self.assertEqual(
                            decision.action,
                            "acquired" if index == 0 else "attached",
                            decision,
                        )
                    self.assertEqual(
                        event.race_data_sync_enrollment.source_bindings.count(), 2
                    )
                    self.assertEqual(event.projection_control.owner_generation, 1)


class TraBindingAdapterTests(TestCase):
    @override_settings(
        RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ALLOW_NETWORK=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
        RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    )
    def test_free_card_transport_initializes_host_budget_without_network(self):
        import json
        from stable.services.race_data_source_adapters import fetch_tra_observation

        registry = json.loads(
            (
                ROOT.parents[1]
                / "runtime/policies/race_live/source_registry_the_racing_api_free.json"
            ).read_text()
        )
        route = route_for(
            "the_racing_api",
            "japan_jra",
            "japan",
            "Asia/Tokyo",
            "nakayama",
            ["Nakayama"],
            "api.theracingapi.com",
            "/v1/",
            kinds=("racecard",),
        )
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="tra-adapter",
            original_name="All Comers",
            racecourse="Nakayama",
            country_region="japan",
            local_date=date(2026, 9, 20),
            timezone_name="Asia/Tokyo",
        )
        body = {
            "racecards": [
                {
                    "race_id": "race_1",
                    "race_name": "All Comers",
                    "off_dt": "2026-09-20T06:45:00Z",
                    "region": "jpn",
                    "course": "Nakayama",
                    "runners": [
                        {
                            "horse_id": "hrs_1",
                            "horse": "Horse",
                            "number": "1",
                            "jockey": "Jockey",
                        }
                    ],
                }
            ]
        }

        def cache(**kw):
            return kw["fetcher"]()[0], "e" * 64

        with patch(
            "stable.services.race_live_source_proof.read_the_racing_api_automation_registry",
            return_value=(registry, route.proof_digest),
        ), patch(
            "stable.services.race_live_source_proof._read_secret",
            return_value=("test-only", "test-only"),
        ), patch(
            "stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot",
            side_effect=cache,
        ), patch(
            "stable.services.race_data_sync_providers._fetch_json",
            return_value=(body, "d" * 64),
        ) as transport, patch(
            "django.utils.timezone.now", return_value=NOW
        ):
            value = fetch_tra_observation(
                event=event, route=route, now=NOW, kind="racecard"
            )
        self.assertEqual(value["external_race_id"], "race_1")
        self.assertFalse(value["roster"][0]["status_reported"])
        self.assertEqual(transport.call_count, 1)
        self.assertGreaterEqual(
            models.RaceLiveHostBudget.objects.get(
                host="api.theracingapi.com"
            ).min_interval_ms,
            2000,
        )
