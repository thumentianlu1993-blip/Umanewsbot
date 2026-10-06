from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from stable.adapters.international import HorseRacingNationAdapter, SportingLifeAdapter, TDNAdapter

FIXTURES = Path(__file__).parent / 'fixtures' / 'news_content_boundaries'


class ArticleContentTraceTests(SimpleTestCase):
    def setUp(self):
        guard = patch('socket.socket.connect', side_effect=AssertionError('offline parser test'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_normal_article_exposes_reproducible_blocks_without_losing_text(self):
        html = (FIXTURES / 'hrn_normal_article.html').read_text()
        adapter = HorseRacingNationAdapter()
        first = adapter.parse_detail_html(html, url='https://fixture.invalid/normal')
        second = adapter.parse_detail_html(html, url='https://fixture.invalid/normal')
        evidence = first.metadata['body_cleaning']
        self.assertIn('blocks', evidence)
        self.assertTrue(evidence['blocks'])
        self.assertEqual(evidence['blocks'], second.metadata['body_cleaning']['blocks'])
        self.assertEqual(evidence['after_text'], first.body_ja_raw)
        self.assertTrue(first.body_ja_raw.startswith('The trainer opened the season'))
        self.assertTrue(first.body_ja_raw.endswith('full campaign remains intact.'))
        self.assertTrue(all(b['original_text'] and b['block_id'] and b['reasons'] for b in evidence['blocks']))

    def test_sporting_life_does_not_use_wide_article_or_main_as_body(self):
        for tag in ('article', 'main'):
            with self.subTest(tag=tag):
                detail = SportingLifeAdapter().parse_detail_html(
                    f'<{tag}><h1>Template drift</h1><p>Log in for free bets</p><p>Top Stories</p></{tag}>',
                    url='https://fixture.invalid/drift',
                )
                self.assertEqual(detail.metadata['body_parse_status'], 'selector_not_found')
                self.assertEqual(detail.body_ja_raw, '')
                self.assertEqual(detail.metadata['body_selector'], '')

    def test_pollution_and_inline_change_each_have_original_result_and_reason(self):
        detail = SportingLifeAdapter().parse_detail_html(
            '<div class="Article__ArticleBody">'
            '<nav>Navigation links</nav><p>Blue Horizon is 7/2 for the feature race.</p>'
            '<p>Book now the festival begins on Saturday.</p><p>Free bets sign up offer.</p></div>',
            url='https://fixture.invalid/pollution',
        )
        evidence = detail.metadata['body_cleaning']
        self.assertIn('blocks', evidence)
        removed = [b for b in evidence['blocks'] if b['decision'] == 'removed']
        self.assertEqual({b['original_text'] for b in removed}, {'Navigation links', 'Free bets sign up offer.'})
        changed = next(b for b in evidence['blocks'] if b['decision'] == 'modified')
        self.assertEqual(changed['text'], 'the festival begins on Saturday.')
        self.assertIn('link_cta', changed['reasons'])
        self.assertIn('Blue Horizon is 7/2', detail.body_ja_raw)

    def test_duplicate_paragraphs_have_distinct_ids(self):
        html = '<div class="article-body"><p>Same fact.</p><p>Same fact.</p></div>'
        evidence = HorseRacingNationAdapter().parse_detail_html(html, url='https://fixture.invalid/duplicate').metadata['body_cleaning']
        self.assertIn('blocks', evidence)
        ids = [b['block_id'] for b in evidence['blocks']]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_empty_after_noise_reports_gap_and_does_not_restore_navigation(self):
        detail = SportingLifeAdapter().parse_detail_html('<div class="Article__ArticleBody"><nav>Menu</nav></div>', url='https://fixture.invalid/empty')
        self.assertEqual(detail.metadata['body_parse_status'], 'empty_after_cleaning')
        self.assertEqual(detail.body_ja_raw, '')
        self.assertIn('blocks', detail.metadata['body_cleaning'])
        self.assertEqual(detail.metadata['body_cleaning']['blocks'][0]['decision'], 'removed')

    def test_existing_seven_fixtures_keep_base_text_status_and_rule_counts(self):
        import hashlib
        import json
        from stable.adapters import international
        baseline = json.loads((FIXTURES / 'b035_cleaning_baseline.json').read_text())
        for case in baseline['cases']:
            with self.subTest(fixture=case['fixture']):
                raw = (FIXTURES / case['fixture']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), case['input_sha256'])
                detail = getattr(international, case['adapter'])().parse_detail_html(raw.decode(), url='https://fixture.invalid/baseline')
                self.assertEqual(detail.body_ja_raw, case['body'])
                self.assertEqual(detail.metadata['body_parse_status'], case['status'])
                self.assertEqual(detail.metadata['body_cleaning']['removed_rules'], case['removed_rules'])
                self.assertEqual(detail.metadata['body_cleaning']['after_text'], case['body'])
                blocks = detail.metadata['body_cleaning']['blocks']
                self.assertEqual('\n\n'.join(b['text'] for b in blocks if b['text']), case['body'])

    def test_structural_noise_does_not_steal_same_text_from_legal_paragraph(self):
        detail = SportingLifeAdapter().parse_detail_html(
            '<div class="Article__ArticleBody"><p>Race Video</p><nav>Race Video</nav>'
            '<p>Blue Horizon wins the Sky Bet race at odds of 7/2.</p></div>',
            url='https://fixture.invalid/duplicate-noise',
        )
        matches = [b for b in detail.metadata['body_cleaning']['blocks'] if b['original_text'] == 'Race Video']
        self.assertEqual({b['decision'] for b in matches}, {'removed', 'kept'})
        self.assertEqual(len({b['block_id'] for b in matches}), 2)
        self.assertIn('Sky Bet race at odds of 7/2', detail.body_ja_raw)

    def test_legitimate_headings_quotes_table_and_caption_keep_dom_order(self):
        html = '<div class="Article__ArticleBody"><p>Opening fact.</p><h2>Race shape</h2>' \
               '<blockquote>The rider said keep the terms unchanged.</blockquote>' \
               '<table><tr><th>Runner</th><td>Blue Horizon</td></tr></table>' \
               '<figure><figcaption>Morning training at York.</figcaption></figure><p>Closing fact.</p></div>'
        detail = SportingLifeAdapter().parse_detail_html(html, url='https://fixture.invalid/structure')
        expected = ['Opening fact.', 'Race shape', 'The rider said keep the terms unchanged.', 'Runner', 'Blue Horizon', 'Morning training at York.', 'Closing fact.']
        positions = [detail.body_ja_raw.index(value) for value in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(all(b['decision'] == 'kept' for b in detail.metadata['body_cleaning']['blocks']))

    def test_source_specific_sponichi_and_tdn_rules_remain_traceable(self):
        from stable.adapters.international import SponichiAdapter
        sponichi = SponichiAdapter().parse_detail_html(
            '<div data-component="article-body"><p>東京で最終追い切りを終えた。</p>'
            '<figure><figcaption>写真の説明</figcaption></figure>'
            '<p>スポニチ予想は販売中</p><p>次走も同じ騎手を予定している。</p></div>',
            url='https://fixture.invalid/japan',
        )
        self.assertEqual(sponichi.body_ja_raw, '東京で最終追い切りを終えた。\n\n次走も同じ騎手を予定している。')
        reasons = {r for b in sponichi.metadata['body_cleaning']['blocks'] for r in b['reasons']}
        self.assertIn('sponichi_structured_noise', reasons)
        self.assertIn('sponichi_betting_promotion', reasons)
        tdn = TDNAdapter().parse_detail_html(
            '<span itemprop="articleBody"><p>Editor\'s Note: Subscribe.</p><p>First race fact.</p>'
            '<p>https://fixture.invalid/ad</p><p>Read Today\'s Paper</p><p>Other promotions</p></span>',
            url='https://fixture.invalid/tdn',
        )
        self.assertEqual(tdn.body_ja_raw, 'First race fact.')
        reasons = {r for b in tdn.metadata['body_cleaning']['blocks'] for r in b['reasons']}
        self.assertTrue({'tdn_editor_note', 'standalone_url', 'tdn_read_paper'}.issubset(reasons))

    def test_nested_noise_is_audited_before_dom_nodes_are_destroyed(self):
        detail = SportingLifeAdapter().parse_detail_html(
            '<div class="Article__ArticleBody"><nav>Outer menu<nav>Inner menu</nav></nav><p>Full fact.</p></div>',
            url='https://fixture.invalid/nested',
        )
        self.assertEqual(detail.body_ja_raw, 'Full fact.')
        self.assertEqual(detail.metadata['body_cleaning']['removed_rules']['structured_noise'], 2)
        self.assertTrue(any(b['original_text'] == 'Inner menu' for b in detail.metadata['body_cleaning']['blocks']))

    def test_script_style_root_noise_keeps_hash_and_locator_without_source_text(self):
        import hashlib
        import json
        html = '<div class="Article__ArticleBody"><script>window.inlineTracking = SCRIPT_SENTINEL;</script>' \
               '<style>.STYLE_SENTINEL{color:red}</style><p>Fact.</p></div>'
        detail = SportingLifeAdapter().parse_detail_html(html, url='https://fixture.invalid/executable-noise')
        evidence = detail.metadata['body_cleaning']
        self.assertEqual(detail.body_ja_raw, 'Fact.')
        self.assertEqual(evidence['before_text'], 'Fact.')
        self.assertEqual(evidence['removed_rules'], {'structured_noise': 2})
        serialized = json.dumps(evidence)
        self.assertNotIn('SCRIPT_SENTINEL', serialized)
        self.assertNotIn('STYLE_SENTINEL', serialized)
        removed = [b for b in evidence['blocks'] if b['decision'] == 'removed']
        self.assertEqual(len(removed), 2)
        for block in removed:
            self.assertEqual(block['original_text'], '')
            self.assertEqual(block['text'], '')
            self.assertEqual(block['reasons'], ['structured_noise'])
            self.assertTrue(block['locator'] and block['block_id'])
        expected = {
            hashlib.sha256(b'<script>window.inlineTracking = SCRIPT_SENTINEL;</script>').hexdigest(),
            hashlib.sha256(b'<style>.STYLE_SENTINEL{color:red}</style>').hexdigest(),
        }
        self.assertEqual({b['original_html_sha256'] for b in removed}, expected)
        self.assertIn('SCRIPT_SENTINEL', detail.original_content_html)
        self.assertIn('STYLE_SENTINEL', detail.original_content_html)

    def test_nested_script_style_inside_removed_navigation_do_not_enter_trace_text(self):
        import json
        html = '<div class="Article__ArticleBody"><nav>Menu<script>SCRIPT_SENTINEL</script>' \
               '<style>.STYLE_SENTINEL{color:red}</style></nav><p>Fact.</p></div>'
        detail = SportingLifeAdapter().parse_detail_html(html, url='https://fixture.invalid/nested-code')
        evidence = detail.metadata['body_cleaning']
        self.assertEqual(detail.body_ja_raw, 'Fact.')
        self.assertEqual(evidence['removed_rules'], {'structured_noise': 1})
        self.assertNotIn('SCRIPT_SENTINEL', json.dumps(evidence))
        self.assertNotIn('STYLE_SENTINEL', json.dumps(evidence))
        removed = [b for b in evidence['blocks'] if b['decision'] == 'removed']
        self.assertEqual([b['original_text'] for b in removed], ['Menu'])
