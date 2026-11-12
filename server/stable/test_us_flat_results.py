"""真实报纸 chart 的冲线、裁定和名单核对回归；禁止网络。"""
import json
from pathlib import Path
from unittest import TestCase

from stable.services.us_flat_results import parse_chart, parse_sporting_life, merge_result

FIXTURES = Path(__file__).parent / 'fixtures' / 'us_flat_results'
TARGETS = json.loads((FIXTURES / 'targets.json').read_text())


class USFlatResultTests(TestCase):
    def result(self, filename):
        target = next(t for t in TARGETS if t['drf']['url'].endswith(filename))
        chart = parse_chart((FIXTURES / filename).read_bytes(), target['drf'])
        supplement = parse_sporting_life((FIXTURES / filename.replace('.pdf', '.html')).read_bytes(), target['drf'])
        return merge_result(chart, supplement, expected_count=int(target['toba']['field_size_raw']))

    def test_river_city_keeps_program_post_and_time_semantics(self):
        result = self.result('CD2026110708.pdf')
        self.assertEqual(result['runner_count'], 6)
        self.assertEqual(len(result['scratches']), 2)
        horse = next(x for x in result['runners'] if x['horse_name'] == 'Ole Crazy Bone')
        self.assertEqual((horse['program_number'], horse['post_position']), (8, 6))
        self.assertEqual(result['winning_time'], '1:47.20')
        self.assertEqual(result['going'], 'firm')
        self.assertEqual(result['runners'][0]['odds_net'], '4.06')
        self.assertEqual(result['runners'][0]['margin_to_next'], '1/2')
        self.assertNotIn('race_time', horse)

    def test_demotion_retains_physical_finish(self):
        result = self.result('SA2026100302.pdf')
        horse = next(x for x in result['runners'] if x['horse_name'] == 'Paradise City')
        self.assertEqual((horse['finish_position'], horse['placing']), (1, 2))
        self.assertTrue(horse['demoted'])

    def test_breeders_cup_demotion(self):
        result = self.result('KEE2026103006.pdf')
        horse = next(x for x in result['runners'] if x['horse_name'] == "Harper's Corner")
        self.assertEqual((horse['finish_position'], horse['placing']), (3, 8))

    def test_dead_heat_and_non_finisher(self):
        result = self.result('KEE2026103105.pdf')
        self.assertEqual(sum(x['placing'] == 4 for x in result['runners']), 2)
        result = self.result('BEL2026102508.pdf')
        horse = next(x for x in result['runners'] if x['horse_name'] == 'R Slew Of Cash')
        self.assertIsNone(horse['placing'])
        self.assertEqual(horse['status'], 'did_not_finish')

    def test_british_midnight_keeps_us_race_date(self):
        self.assertEqual(self.result('DMR2026090510.pdf')['local_date'], '2026-09-05')

    def test_incomplete_roster_and_bad_pdf_fail(self):
        t = TARGETS[0]
        with self.assertRaises(ValueError):
            parse_chart(b'not a PDF', t['drf'])
        c = parse_chart((FIXTURES / 'CD2026110708.pdf').read_bytes(),
                        next(t['drf'] for t in TARGETS if t['drf']['url'].endswith('CD2026110708.pdf')))
        with self.assertRaises(ValueError):
            merge_result(c, {'runners': [], 'scratches': []}, expected_count=6)

    def test_parx_actual_programs_and_four_scratches(self):
        from stable.services.us_flat_results import parse_abr, parse_program_entries, supplement_programs
        # 整场名单+原始马号逐项核对，不能由空缺号码推算退赛号。
        for filename, page, entries, numbers in [
            ('PRX2026091912.pdf', 'abr-gallant-bob-s.html', 'tn-gallant-entries.html', {1, 3, 4}),
            ('PRX2026091914.pdf', 'abr-pennsylvania-derby.html', 'tn-derby-entries.html', {1}),
        ]:
            identity = next(t['drf'] for t in TARGETS if t['drf']['url'].endswith(filename))
            chart = parse_chart((FIXTURES / filename).read_bytes(), identity)
            supplement = parse_abr((FIXTURES / page).read_bytes(), identity)
            result = merge_result(chart, supplement, expected_count=len(chart['runners']))
            self.assertEqual(result['gaps'], ['scratch_program_number_missing'])
            table = parse_program_entries((FIXTURES / entries).read_bytes(), identity)
            result = supplement_programs(result, table)
            self.assertEqual(result['gaps'], [])
            self.assertEqual({r['program_number'] for r in result['scratches']}, numbers)
            table[0]['program_number'] = 99
            with self.assertRaises(ValueError):
                supplement_programs(result, table)

    def test_directory_distinguishes_same_name_two_races(self):
        from stable.services.us_flat_collection import drf_directory, select_chart
        rows = drf_directory((FIXTURES / 'drf-index.html').read_bytes())
        t = next(t['toba'] for t in TARGETS if t['drf']['url'].endswith('BEL2026102508.pdf'))
        self.assertEqual(select_chart(t, rows)['race_number'], 8)
        with self.assertRaises(ValueError):
            select_chart(dict(t, source_race_id=''), rows)

    def test_supplement_identity_and_roster_corruption_rejected(self):
        t = next(t for t in TARGETS if t['drf']['url'].endswith('CD2026110708.pdf'))
        raw = (FIXTURES / 'CD2026110708.html').read_bytes()
        with self.assertRaises(ValueError):
            parse_sporting_life(raw, dict(t['drf'], date='2026-11-08'))
        chart = parse_chart((FIXTURES / 'CD2026110708.pdf').read_bytes(), t['drf'])
        supplement = parse_sporting_life(raw, t['drf'])
        supplement['scratches'].pop()
        with self.assertRaises(ValueError):
            merge_result(chart, supplement, expected_count=6)

    def test_drf_allowlist_blocks_arbitrary_chart_paths_and_redirects(self):
        from stable.services.us_flat_collection import flat_url_allowed, FlatSourceStore
        from tempfile import TemporaryDirectory
        from unittest.mock import patch, MagicMock
        url = TARGETS[0]['drf']['url']
        self.assertTrue(flat_url_allowed(url))
        for bad in [url+'&url=https://example.com', url.replace('/download/', '/private/'),
                    url.replace('https:', 'http:'), url+'#x', 'https://www1.drf.com@evil.test/']:
            self.assertFalse(flat_url_allowed(bad))
        with TemporaryDirectory() as root, patch('stable.services.us_source_collection.requests.get') as get:
            response = MagicMock(status_code=302)
            get.return_value.__enter__.return_value = response
            store = FlatSourceStore(root, allow_network=True)
            with self.assertRaisesRegex(ValueError, 'us_http_302'):
                store.get(url)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            with self.assertRaises(ValueError):
                store.get(url)
            self.assertEqual(get.call_count, 1)

    def test_offline_cached_full_workflow(self):
        from stable.services.us_flat_collection import collect_flat_results, DRF_INDEX, SL_INDEX, FlatSourceStore
        from stable.services.us_source_collection import atomic_json
        from datetime import date, datetime, timezone
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import hashlib
        t = next(t for t in TARGETS if t['drf']['url'].endswith('CD2026110708.pdf'))
        urls = {DRF_INDEX: 'drf-index.html', SL_INDEX+'2026-11-07': 'sl-day.html',
                t['drf']['url']: 'CD2026110708.pdf', t['sporting_life'][0]['url']: 'CD2026110708.html'}
        now = datetime(2026, 11, 11, tzinfo=timezone.utc)
        with TemporaryDirectory() as root, patch('stable.services.us_source_collection.requests.get', side_effect=AssertionError('network forbidden')):
            root = Path(root); (root/'raw').mkdir(); docs = {}
            urls['https://toba.org/graded-stakes/2026-races/'] = None
            for url, f in urls.items():
                body = (FIXTURES/f).read_bytes() if f else b'toba mock'
                sha = hashlib.sha256(body).hexdigest(); (root/'raw'/(sha+'.bin')).write_bytes(body)
                docs[url] = dict(url=url, sha256=sha, bytes=len(body), fetched_at=now.isoformat())
            atomic_json(root/'receipts.json', dict(schema_version=1, documents=docs))
            with patch('stable.services.us_flat_collection.parse_toba_calendar', return_value={'items':[t['toba']], 'unresolved':[]}):
                report = collect_flat_results(FlatSourceStore(root, now=now), start=date(2026, 9, 1), end=date(2026,12,31))
            self.assertEqual(report['acceptance'], 'result_source_passed', report['errors'])
            self.assertEqual(report['network_requests'], 0)
            self.assertEqual(report['runner_count'], 6)
            conflict = dict(t['toba'], candidate_key='conflicting-target', race_name='Conflicted Stakes')
            with patch('stable.services.us_flat_collection.parse_toba_calendar', return_value={
                'items': [t['toba']], 'unresolved': [],
                'conflicts': [{'reason': 'source_conflict', 'candidate_key': 'conflicting-target',
                               'evidence': [conflict, dict(conflict, grade='G2')]}],
            }):
                report = collect_flat_results(FlatSourceStore(root, now=now), start=date(2026,9,1), end=date(2026,12,31))
            self.assertEqual(report['acceptance'], 'incomplete')
            self.assertEqual(report['targets'], 2)
            self.assertEqual(report['errors'][0]['reason'], 'us_calendar_source_conflict')
            self.assertEqual(len(report['catalogue_conflicts']), 1)

    def test_abr_missing_nodes_are_controlled_errors(self):
        from bs4 import BeautifulSoup
        from stable.services.us_flat_results import parse_abr
        identity = next(t['drf'] for t in TARGETS if t['drf']['url'].endswith('PRX2026091914.pdf'))
        for selector in ['.position', '.entry-header .title', '.entry-header .number']:
            soup = BeautifulSoup((FIXTURES/'abr-pennsylvania-derby.html').read_bytes(), 'lxml')
            soup.select_one(selector).decompose()
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                parse_abr(str(soup), identity)

    def test_abr_scratch_list_is_cross_checked(self):
        from stable.services.us_flat_results import parse_abr
        identity = next(t['drf'] for t in TARGETS if t['drf']['url'].endswith('PRX2026091914.pdf'))
        chart = parse_chart((FIXTURES/'PRX2026091914.pdf').read_bytes(), identity)
        other = parse_abr((FIXTURES/'abr-pennsylvania-derby.html').read_bytes(), identity)
        self.assertEqual(other['scratches'], [{'horse_name':'Zihnal', 'program_number':None}])
        chart['scratches'] = []
        with self.assertRaises(ValueError):
            merge_result(chart, other, expected_count=10)

class USAutoProgramTests(TestCase):
    def test_race_link_chain_discovers_complete_program_without_manual_map(self):
        from stable.services.us_flat_collection import discover_program_entries
        from stable.services.us_flat_results import supplement_programs
        root='https://www.americasbestracing.net'
        pages={root+'/races/2026-pennsylvania-derby':'abr-pennsylvania-discovery.html',
            root+'/gambling/2026-americas-best-racings-trifecta-picks-the-2026-pennsylvania-derby':'abr-pennsylvania-trifecta.html',
            root+'/the-sport/2026-2026-pennsylvania-derby-cheat-sheet':'abr-pennsylvania-cheat.html'}
        requested=[]
        def read(url):
            requested.append(url)
            return {'url':url,'body':(FIXTURES/pages[url]).read_bytes()}
        identity=dict(track='PRX',date='2026-09-19',race_number=14,name='Pennsylvania Derby (G1)')
        from stable.services.us_flat_results import parse_abr
        chart=parse_chart((FIXTURES/'PRX2026091914.pdf').read_bytes(),identity)
        result=merge_result(chart,parse_abr((FIXTURES/'abr-pennsylvania-derby.html').read_bytes(),identity),expected_count=len(chart['runners']))
        self.assertTrue(result['gaps'])
        entries,doc=discover_program_entries(identity,read=read,initial=read(root+'/races/2026-pennsylvania-derby'))
        merged=supplement_programs(result,entries)
        self.assertFalse(merged['gaps'])
        self.assertEqual(merged['scratches'][0]['program_number'],1)
        self.assertEqual(len(entries),11)
        self.assertEqual(len(requested),3)
        self.assertTrue(doc['url'].endswith('cheat-sheet'))


class USArchiveProgramTests(TestCase):
    def test_archive_index_selects_by_full_source_identity_without_url_map(self):
        from stable.services.us_flat_collection import archived_program_entries
        identity=next(t['drf'] for t in TARGETS if t['drf']['url'].endswith('PRX2026091912.pdf'))
        pages={'https://www.truenicks.com/articles/1/derby':(FIXTURES/'tn-derby-entries.html').read_bytes(),
               'https://www.truenicks.com/articles/2/gallant':(FIXTURES/'tn-gallant-entries.html').read_bytes()}
        entries,doc=archived_program_entries(identity,urls=pages,read=lambda url:dict(url=url,body=pages[url]))
        self.assertTrue(doc['url'].endswith('/gallant'))
        self.assertEqual(len(entries),12)
        with self.assertRaisesRegex(ValueError,'not_found'):
            archived_program_entries(dict(identity,race_number=99),urls=pages,read=lambda url:dict(url=url,body=pages[url]))
