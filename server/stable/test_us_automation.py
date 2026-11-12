"""美国采集回归：真实来源 fixture，禁止外网和业务数据库。"""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch, MagicMock
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from stable.services.race_data_source_adapters import (
    SourceRoute, discover_source_url, parse_reference_observation,
)

ROOT = Path(__file__).parent / 'fixtures/us_automation'
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
CARD = 'https://www.dmtc.com/racing/entries/2026-11-14'
FINAL_CARD = 'https://www.dmtc.com/racing/entries/2026-11-08'


def event(day=date(2026, 11, 14), name='Desi Arnaz Stakes'):
    return SimpleNamespace(local_date=day, original_name=name, chinese_name='',
        racecourse='Del Mar', timezone_name='America/Los_Angeles', source_refs={})


def route():
    return SourceRoute(dict(provider='del_mar', operator='del_mar',
        region='united_states', identity_namespace='del-mar-race-v1',
        allowed_hosts=['www.dmtc.com'], allowed_path_prefixes=['/racing/entries/'],
        venue_aliases={'DMR': ['Del Mar', '德尔马']}, timezone='America/Los_Angeles',
        parser_version='del-mar-v1'), 'a' * 64)


class DelMarAdapterTests(SimpleTestCase):
    def test_date_card_discovery_checks_named_race(self):
        fetch = Mock(return_value=(ROOT / 'dmtc-entries.html').read_text())
        self.assertEqual(discover_source_url(event=event(), route=route(), now=NOW, fetcher=fetch), CARD)
        self.assertEqual(fetch.call_args.args[0], CARD)

    def test_provisional_program_is_not_final_observation(self):
        with self.assertRaisesRegex(ValueError, 'us_card_not_final'):
            parse_reference_observation((ROOT / 'dmtc-entries.html').read_text(),
                url=CARD, route=route(), now=NOW, event=event())

    def test_published_program_preserves_scratches_and_positions(self):
        value = parse_reference_observation((ROOT / 'dmtc-entries-final.html').read_text(),
            url=FINAL_CARD, route=route(), now=NOW,
            event=event(date(2026, 11, 8), 'Betty Grable Stakes'))
        self.assertEqual(value['external_race_id'], 'DMR:20261108:8')
        self.assertEqual(len(value['roster']), 9)
        self.assertEqual(value['result_phase'], '')
        self.assertEqual(value['off_time'], '2026-11-08T16:03:00-08:00')
        scratched = [r['number'] for r in value['roster'] if r['status'] == 'non_runner']
        self.assertEqual(scratched, ['2', '5', '9'])
        lino = next(r for r in value['roster'] if r['horse_name'] == "Lino's Angel")
        self.assertEqual((lino['number'], lino['barrier']), ('3', '2'))
        self.assertEqual(lino['carried_weight'], '118 lb')

    def test_wrong_date_name_venue_and_timezone_are_rejected(self):
        page = (ROOT / 'dmtc-entries-final.html').read_text()
        for changed in [dict(local_date=date(2025, 11, 8)), dict(original_name='Wrong Stakes'),
                        dict(racecourse='Churchill Downs'), dict(timezone_name='America/New_York')]:
            obj = event(date(2026, 11, 8), 'Betty Grable Stakes')
            obj.__dict__.update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse_reference_observation(page, url=FINAL_CARD, route=route(), now=NOW, event=obj)


class USDocumentTests(SimpleTestCase):
    def parse(self, provider, kind, file, **kwargs):
        from stable.services.us_racing_sources import parse_document
        import json
        refs = {r['file']: r['source_url'] for r in json.loads((ROOT / 'provenance.json').read_text())}
        return parse_document(provider, kind, (ROOT / file).read_bytes(), url=refs[file], **kwargs)

    def test_toba_keeps_all_grades_before_window_selection(self):
        data = self.parse('toba', 'calendar', 'toba.html')
        targets = [r for r in data['items'] if r['grade'] in {'G1', 'G2', 'G3'}
                   and r['local_date'] and '2026-09-01' <= r['local_date'] <= '2026-12-31']
        self.assertEqual(len(targets), 143)
        glen = next(c for c in data['conflicts'] if c['evidence'][0]['race_name']=='GLEN COVE S.')
        self.assertEqual({r['source_race_id'] for r in glen['evidence']}, {'5','8'})
        same_day = [r for r in targets if (r['venue'], r['local_date']) == ('DMR', '2026-11-28')]
        self.assertEqual(len(same_day), 3)
        self.assertEqual(len({r['candidate_key'] for r in same_day}), 3)
        bob = next(r for r in data['items'] if r['race_name'] == 'BOB HOPE S.')
        self.assertEqual(bob['grade'], 'L')
        self.assertEqual(len([r for r in data['unresolved'] if r['grade'] in {'G1','G2','G3'}]), 6)
        self.assertTrue(all(r['local_date'] is None for r in data['unresolved']))

    def test_toba_duplicate_does_not_swallow_conflicting_grade(self):
        from stable.services.us_racing_sources import parse_document
        from bs4 import BeautifulSoup
        raw = (ROOT / 'toba.html').read_text()
        soup = BeautifulSoup(raw, 'lxml')
        row = next(r for r in soup.select('tr') if 'HOLLYWOOD DERBY' in r.get_text())
        same = raw.replace('</tbody>', str(row) + '</tbody>')
        self.assertEqual(len(parse_document('toba', 'calendar', same, url='https://toba.org/graded-stakes/2026-races/')['items']),
                         len(self.parse('toba', 'calendar', 'toba.html')['items']))
        row.select('td')[4].string = '2'
        conflict = raw.replace('</tbody>', str(row) + '</tbody>')
        result = parse_document('toba', 'calendar', conflict, url='https://toba.org/graded-stakes/2026-races/')
        added = next(c for c in result['conflicts'] if c['evidence'][0]['race_name']=='HOLLYWOOD DERBY')
        self.assertEqual({r['grade'] for r in added['evidence']}, {'G1', 'G2'})

    def test_nsa_condition_book_carries_meeting_across_pages(self):
        result = self.parse('nsa', 'calendar', 'nsa-fall.pdf')
        self.assertEqual(len(result['items']), 6)
        colonial = next(r for r in result['items'] if 'COLONIAL CUP' in r['race_name'])
        self.assertEqual((colonial['local_date'], colonial['grade']), ('2026-11-22', 'G1'))
        self.assertTrue(all(r['local_date'].startswith('2026-') for r in result['items']))
        self.assertNotIn('Cool Jet', str(result['items']))

    def test_future_colonial_cup_retains_published_basic_conditions(self):
        rows=self.parse('nsa','calendar','nsa-fall.pdf')['items']
        row=next(r for r in rows if r['race_name']=='COLONIAL CUP')
        self.assertEqual(row['purse_raw'],'$150,000')
        self.assertEqual(row['age_condition'],'4U')
        self.assertEqual(row['distance_text'],'2 5/8 miles')
        self.assertNotIn('HOBKIRK',row['conditions_raw'])

    def test_nsa_result_has_every_runner_and_explicit_gaps(self):
        result = self.parse('nsa', 'result', 'nsa-far-hills.pdf')
        race = next(r for r in result['items'] if 'American Grand National' in r['race_name'])
        self.assertEqual(len(race['runners']), 7)
        self.assertEqual(race['runners'][-1]['status'], 'pulled_up')
        self.assertEqual(race['runners'][0]['trainer_name'], 'Gordon Elliott')
        self.assertEqual(race['race_time_raw'], '5:45 2/5')
        self.assertTrue(all(not r['finish_time'] and not r['margin'] for r in race['runners']))
        self.assertIn('runner_odds', race['gaps'])
        self.assertFalse(race['production_complete'])
        self.assertEqual(race['local_date'], '2026-10-17')

    def test_nsa_september_graded_results_are_catalogue_candidates(self):
        rows = []
        for file in ['nsa-saratoga-sep.pdf', 'nsa-colonial-sep.pdf']:
            rows += [r for r in self.parse('nsa', 'result', file)['items'] if r['grade']]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['grade'] for r in rows}, {'G1','G2'})

    def test_nomination_pdf_is_not_numbered_card(self):
        obj = event(date(2026, 11, 15), 'Bob Hope Stakes')
        result = self.parse('del_mar', 'nominations', 'dmtc-bob-hope-noms.pdf', event=obj)
        self.assertEqual((result['stage'], len(result['items']), result['grade']), ('registration', 11, 'G3'))
        self.assertEqual(result['items'][0]['horse_name'], 'ALA SAWAB')
        self.assertTrue(all(not r['horse_number'] and not r['jockey_name'] for r in result['items']))
        self.assertEqual(result['local_date'], '2026-11-15')
        with self.assertRaisesRegex(ValueError, 'us_nomination_identity'):
            self.parse('del_mar', 'nominations', 'dmtc-bob-hope-noms.pdf', event=event())

    def test_changes_are_date_bound_and_keep_original_and_new_weight(self):
        obj = event(date(2026, 11, 8), 'Betty Grable Stakes')
        result = self.parse('del_mar', 'changes', 'dmtc-changes.html', event=obj)
        race = next(r for r in result['items'] if r['race_number'] == '8')
        self.assertEqual([r['horse_number'] for r in race['changes'] if r['kind']=='scratch'], ['2','5','9'])
        weight = next(r for r in race['changes'] if r['kind']=='weight')
        self.assertEqual((weight['old_weight'],weight['new_weight']), ('118 lb','120 lb'))
        self.assertEqual(race['going'], 'Fast')
        with self.assertRaisesRegex(ValueError, 'us_changes_date_mismatch'):
            self.parse('del_mar', 'changes', 'dmtc-changes.html', event=event())

    def test_bob_hope_conflict_preserves_both_sources(self):
        from stable.services.us_racing_sources import parse_document
        toba = self.parse('toba', 'calendar', 'toba.html')
        noms = self.parse('del_mar', 'nominations', 'dmtc-bob-hope-noms.pdf',
                          event=event(date(2026,11,15), 'Bob Hope Stakes'))
        report = parse_document('us', 'reconcile', [toba, noms], url='')
        self.assertEqual(len(report['conflicts']), 1)
        self.assertEqual({r['grade'] for r in report['conflicts'][0]['evidence']}, {'L','G3'})
        self.assertTrue(all(r['source_url'] and r['raw_sha256'] for r in report['conflicts'][0]['evidence']))
        self.assertFalse(report['production_identity_granted'])

    def test_nsa_divisions_share_book_number_but_keep_separate_rosters(self):
        data = self.parse('nsa','result','nsa-montpelier.pdf')
        self.assertEqual(len(data['items']),7)
        divisions = [r for r in data['items'] if r['source_race_id'].startswith('123:')]
        self.assertEqual(len(divisions),2)
        self.assertEqual([len(r['runners']) for r in divisions],[5,4])
        graded = next(r for r in data['items'] if r['grade']=='G2')
        self.assertEqual((graded['source_race_id'],len(graded['runners'])),('126',6))
        self.assertEqual(graded['runners'][-1]['status'],'unseated_rider')

    def test_grey_roan_nominees_are_not_dropped(self):
        data = self.parse('del_mar','nominations','dmtc-let-it-ride-noms.pdf',
                          event=event(date(2026,11,6),'Let It Ride Stakes'))
        self.assertEqual(len(data['items']),16)
        self.assertEqual(next(r for r in data['items'] if r['horse_name']=='ESSOS')['description_raw'],'gr/ro.g.3')

    def test_grade_suffix_is_not_part_of_race_name_and_unpublished_is_explicit(self):
        data = self.parse('del_mar','card','dmtc-september.html',
                          event=event(date(2026,9,5),'DEL MAR DEBUTANTE S.'))
        self.assertEqual(data['race_name'],'Del Mar Debutante Stakes (G1)')
        missing = self.parse('del_mar','card','dmtc-not-published.html',
                             event=event(date(2026,11,15),'Bob Hope Stakes'))
        self.assertEqual(missing['stage'],'not_published')
        self.assertEqual(missing['items'],[])


class USCollectionTests(SimpleTestCase):
    def response(self, body=b'<html><body>source</body></html>', status=200):
        response = MagicMock()
        response.status_code = status
        response.iter_content.return_value = [body]
        response.__enter__.return_value = response
        return response

    def test_cache_replay_preserves_sha_and_observed_time_without_network(self):
        from stable.services.us_source_collection import SourceStore
        import hashlib
        with TemporaryDirectory() as root, patch('requests.get', return_value=self.response()) as get:
            live = SourceStore(root, allow_network=True, now=NOW).get(CARD)
            replay = SourceStore(root, now=NOW.replace(year=2027)).get(CARD)
            self.assertEqual(replay, live)
            self.assertEqual(live['fetched_at'], NOW.isoformat())
            self.assertEqual(live['sha256'], hashlib.sha256(live['body']).hexdigest())
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_disallowed_source_redirect_and_limits_never_become_success(self):
        from stable.services.us_source_collection import SourceStore
        with TemporaryDirectory() as root, patch('requests.get', return_value=self.response()) as get:
            store = SourceStore(root, allow_network=True, now=NOW, max_requests=1)
            for url in ['https://tvg.equibase.com/static/entry/CD.html',
                        'https://www.dmtc.com.evil.test/racing/entries/2026-11-14',
                        'https://www.dmtc.com/racing/entries/../private',
                        'https://www.dmtc.com/racing/entries/2026-11-14?redirect=evil']:
                with self.subTest(url=url), self.assertRaisesRegex(ValueError,'us_source_url_rejected'):
                    store.get(url)
            get.assert_not_called()
            store.get(CARD)
            with self.assertRaisesRegex(ValueError, 'us_request_limit'):
                store.get(FINAL_CARD)
            self.assertEqual(get.call_count, 1)
        for status in [302, 401, 403, 404]:
            with TemporaryDirectory() as root, patch('requests.get', return_value=self.response(status=status)):
                with self.assertRaisesRegex(ValueError, f'us_http_{status}'):
                    SourceStore(root, allow_network=True, now=NOW).get(CARD)
        with TemporaryDirectory() as root, patch('requests.get', return_value=self.response(b'x'*11)):
            with self.assertRaisesRegex(ValueError, 'us_document_too_large'):
                SourceStore(root, allow_network=True, now=NOW, max_bytes=10).get(CARD)

    def test_offline_missing_and_corrupt_cache_fail_closed(self):
        from stable.services.us_source_collection import SourceStore
        with TemporaryDirectory() as root, patch('requests.get') as get:
            with self.assertRaisesRegex(ValueError, 'us_offline_cache_missing'):
                SourceStore(root, now=NOW).get(CARD)
            get.assert_not_called()
        with TemporaryDirectory() as root, patch('requests.get', return_value=self.response()):
            doc = SourceStore(root, allow_network=True, now=NOW).get(CARD)
            (Path(root)/'raw'/(doc['sha256']+'.bin')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'us_cache_digest_mismatch'):
                SourceStore(root, now=NOW).get(CARD)

    def test_timeout_is_not_retried_for_same_url_in_one_run(self):
        from stable.services.us_source_collection import SourceStore
        import requests
        with TemporaryDirectory() as root, patch('requests.get', side_effect=requests.Timeout) as get:
            store = SourceStore(root, allow_network=True, now=NOW)
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'us_network_timeout'):
                    store.get(CARD)
            self.assertEqual(get.call_count,1)

    def test_collection_reports_source_failure_without_erasing_other_evidence(self):
        from stable.services.us_source_collection import SourceStore, collect_sources
        import hashlib
        raw = (ROOT/'toba.html').read_bytes()
        class FakeStore(SourceStore):
            def get(self, url):
                if 'toba.org' in url:
                    return dict(body=raw, url=url, sha256=hashlib.sha256(raw).hexdigest(), fetched_at=NOW.isoformat())
                raise ValueError('us_http_403')
        with TemporaryDirectory() as root:
            report = collect_sources(FakeStore(root, now=NOW), start=date(2026,9,1), end=date(2026,12,31))
        self.assertGreaterEqual(len(report['targets']), 143)
        self.assertTrue(report['errors'])
        self.assertEqual(report['acceptance'], 'incomplete')
        self.assertFalse(report['production_ready'])


class USCommandTests(SimpleTestCase):
    def test_offline_command_writes_failure_report_without_network_or_database(self):
        from django.core.management import call_command, CommandError
        from io import StringIO
        import json
        with TemporaryDirectory() as root, patch('requests.get') as get:
            with self.assertRaisesRegex(CommandError, 'us_source_acceptance_incomplete'):
                call_command('verify_us_sources', '--start','2026-09-01','--end','2026-12-31',
                             '--output-dir',root, stdout=StringIO())
            report = json.loads((Path(root)/'report.json').read_text())
            self.assertEqual(report['acceptance'],'incomplete')
            self.assertFalse(report['production_ready'])
            self.assertTrue(report['errors'])
            get.assert_not_called()


class USReviewRegressionTests(SimpleTestCase):
    response = USCollectionTests.response

    def test_failed_refresh_keeps_previous_replay_receipt(self):
        from stable.services.us_source_collection import SourceStore, collect_sources
        url = 'https://toba.org/graded-stakes/2026-races/'
        with TemporaryDirectory() as root:
            with patch('requests.get',return_value=self.response((ROOT/'toba.html').read_bytes())):
                old = SourceStore(root,allow_network=True,now=NOW).get(url)
            with patch('requests.get',return_value=self.response(b'<html>Access denied</html>')):
                report = collect_sources(SourceStore(root,allow_network=True,now=NOW),
                    start=date(2026,9,1),end=date(2026,12,31))
            self.assertTrue(any(e['reason']=='us_calendar_headers' for e in report['errors']))
            self.assertEqual(SourceStore(root,now=NOW).get(url),old)

    def test_invalid_pdf_is_reported_without_aborting_collection(self):
        from stable.services.us_source_collection import SourceStore, collect_sources
        import hashlib
        class BrokenPDFStore(SourceStore):
            def get(self,url):
                if 'toba.org' in url:raw=(ROOT/'toba.html').read_bytes()
                elif url.endswith('/racing/'):raw=(ROOT/'nsa-racing.html').read_bytes()
                elif url.endswith('.pdf'):raw=b'%PDF-1.4\ntruncated'
                else:raise ValueError('us_offline_cache_missing')
                return dict(body=raw,url=url,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=NOW.isoformat())
        with TemporaryDirectory() as root:
            report=collect_sources(BrokenPDFStore(root,now=NOW),start=date(2026,9,1),end=date(2026,12,31))
        self.assertGreaterEqual(len(report['targets']),143)
        self.assertTrue(any(e['reason']=='us_pdf_invalid' for e in report['errors']))

    def test_cross_year_replay_keeps_nomination_source_year(self):
        from stable.services.us_source_collection import SourceStore, collect_sources
        import json,hashlib
        refs={r['source_url']:r['file'] for r in json.loads((ROOT/'provenance.json').read_text())}
        class FixtureStore(SourceStore):
            def get(self,url):
                if url not in refs:raise ValueError('us_offline_cache_missing')
                raw=(ROOT/refs[url]).read_bytes()
                return dict(body=raw,url=url,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=NOW.isoformat())
        with TemporaryDirectory() as root:
            reports=[collect_sources(FixtureStore(root,now=now),start=date(2026,9,1),end=date(2026,12,31))
                     for now in (NOW,NOW.replace(year=2027))]
        noms=[[d['data'] for d in r['source_documents'] if d['kind']=='nominations'] for r in reports]
        self.assertTrue(noms[0]);self.assertEqual(noms[0],noms[1])

    def test_overlapping_medication_marker_preserves_country_suffix(self):
        from stable.services.us_racing_sources import parse_document
        result=parse_document('nsa','result',(ROOT/'nsa-montpelier.pdf').read_bytes(),url='fixture')
        race=next(r for r in result['items'] if r['grade']=='G2')
        self.assertEqual(race['runners'][4]['horse_name'],"SCORPION'S REVENGE (IRE)")

    def test_failed_directory_refresh_keeps_previous_replay_receipts(self):
        from stable.services.us_source_collection import SourceStore, collect_sources
        cases = [('https://nationalsteeplechase.com/racing/','nsa-racing.html','us_nsa_directory_schema'),
                 ('https://www.dmtc.com/horsemen/nominations','dmtc-nominations.html','us_nomination_directory_schema')]
        for url,file,reason in cases:
            with self.subTest(url=url), TemporaryDirectory() as root:
                with patch('requests.get',return_value=self.response((ROOT/file).read_bytes())):
                    old=SourceStore(root,allow_network=True,now=NOW).get(url)
                with patch('requests.get',return_value=self.response(b'<html>Access denied</html>')):
                    report=collect_sources(SourceStore(root,allow_network=True,now=NOW),
                        start=date(2026,9,1),end=date(2026,12,31))
                self.assertTrue(any(e['reason']==reason for e in report['errors']))
                self.assertEqual(SourceStore(root,now=NOW).get(url)['sha256'],old['sha256'])
