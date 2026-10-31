"""实体短单元：离线原文映射与局部修复契约。"""
from copy import deepcopy
from django.test import SimpleTestCase
from stable.services.news_content import ContentBlocked
from stable.services import news_entity_units as units


CLEAN = {'title': '😀Alpha', 'blocks': [{'id': 'b0', 'text': 'Alpha wins. Alpha returns.'}],
         'source_sha': 'source', 'clean_sha': 'clean'}


def response(payload):
    return {'units': [{'unit_id': u['unit_id'], 'coverage': 'complete', 'entities': []} for u in payload['units']],
            **({'decisions': []} if payload['mode'] == 'repair' else {})}


def row(text='Alpha', context='Alpha wins.'):
    return {'text': text, 'type': 'horse', 'context': context}


class EntityUnitTests(SimpleTestCase):
    def test_title_is_explicit_and_missing_receipt_needs_repair(self):
        p = units.initial_payload(CLEAN, 'en')
        r = response(p); r['units'].pop(0)
        state = units.evaluate(CLEAN, p, r)
        self.assertEqual(state['pending'], ['title'])
        self.assertFalse(state['complete'])

    def test_unicode_and_repeated_names_map_to_original(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][0]['entities'] = [row(context='😀Alpha')]
        r['units'][1]['entities'] = [row(), row(context='Alpha returns.')]
        state = units.evaluate(CLEAN, p, r)
        self.assertTrue(state['complete'])
        out = units.occurrences(CLEAN, state)
        self.assertEqual([(x['block_id'], x['start']) for x in out], [('title', 1), ('b0', 0), ('b0', 12)])

    def test_local_repair_preserves_valid_rows_and_only_requests_failed_unit(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][0]['entities'] = [row(context='😀Alpha')]
        r['units'][1]['entities'] = [row(), {**row(context='Alpha returns.'), 'note': 'bad'}]
        first = units.evaluate(CLEAN, p, r)
        self.assertEqual(len(first['accepted']), 2)
        patch = units.repair_payload(CLEAN, 'en', first, 7)
        self.assertEqual(len(patch['units']), 1)
        rr = response(patch); rr['units'][0]['entities'] = [row(context='Alpha returns.')]
        final = units.evaluate(CLEAN, patch, rr, previous=first)
        self.assertTrue(final['complete'])
        self.assertEqual(len(units.occurrences(CLEAN, final)), 3)
        self.assertEqual(final['accepted'][:2], first['accepted'])

    def test_identical_frozen_row_is_idempotent_but_unrequested_unit_is_rejected(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(), row(context='absent')]
        first = units.evaluate(CLEAN, p, r); patch = units.repair_payload(CLEAN, 'en', first, 7)
        rr = response(patch); rr['units'][0]['entities'] = [row()]
        self.assertTrue(units.evaluate(CLEAN, patch, rr, previous=first)['complete'])
        rr['units'].append({'unit_id': 'title', 'coverage': 'complete', 'entities': []})
        with self.assertRaises(ContentBlocked): units.evaluate(CLEAN, patch, rr, previous=first)

    def test_ambiguous_quote_reports_candidates_without_first_match(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(context='Alpha')]
        state = units.evaluate(CLEAN, p, r)
        self.assertFalse(state['complete']); self.assertEqual(state['accepted'], [])
        self.assertEqual(len(state['issues'][0]['candidates']), 2)

    def test_units_preserve_all_text_and_long_sentence_not_cut(self):
        clean = deepcopy(CLEAN); clean['blocks'][0]['text'] = ('A sentence. ' * 130) + 'X' * 900
        p = units.initial_payload(clean, 'en')
        body = p['units'][1:]
        self.assertGreater(len(body), 1)
        self.assertEqual(''.join(u['text'] for u in body), clean['blocks'][0]['text'])
        self.assertTrue(any(len(u['text']) >= 900 for u in body))
        for u in body: self.assertEqual(u['text'], clean['blocks'][0]['text'][u['start']:u['end']])

    def test_common_word_not_published_as_name_and_uncertain_not_complete(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities'] = [{**row(), 'type': 'common_word'}]
        state = units.evaluate(CLEAN, p, r)
        self.assertEqual(units.occurrences(CLEAN, state), [])
        r['units'][0]['coverage'] = 'uncertain'
        self.assertFalse(units.evaluate(CLEAN, p, r)['complete'])

    def test_invalid_types_overlap_and_invented_quotes_do_not_pass(self):
        for bad in [{**row(), 'type': []}, row(context='fabricated'), {'text': 'Alpha'}]:
            p = units.initial_payload(CLEAN, 'en'); r = response(p); r['units'][1]['entities'] = [bad]
            self.assertFalse(units.evaluate(CLEAN, p, r)['complete'])

    def test_tampered_mapping_and_wrong_repair_base_rejected(self):
        p = units.initial_payload(CLEAN, 'en'); p['units'][1]['start'] = 1
        with self.assertRaises(ContentBlocked): units.evaluate(CLEAN, p, response(p))

    def test_cross_boundary_name_uses_window_and_belongs_to_starting_unit(self):
        clean = deepcopy(CLEAN)
        clean['blocks'][0]['text'] = 'A' * 639 + '. Alpha'
        p = units.initial_payload(clean, 'en'); r = response(p)
        name = 'A. Alpha'
        r['units'][1]['entities'] = [row(text=name, context=name)]
        state = units.evaluate(clean, p, r)
        self.assertTrue(state['complete'])
        out = units.occurrences(clean, state)
        self.assertEqual(out[0]['text'], name)
        self.assertEqual(out[0]['start'], 638)
        r['units'][2]['entities'] = [row(text=name, context=name)]
        deduped = units.evaluate(clean, p, r)
        self.assertTrue(deduped['complete'])
        self.assertEqual(len(units.occurrences(clean, deduped)), 1)

    def test_repeated_identical_sentences_in_distinct_units_have_distinct_offsets(self):
        clean = deepcopy(CLEAN); clean['blocks'][0]['text'] = ('X' * 635 + ' Alpha. ') * 2
        p = units.initial_payload(clean, 'en'); r = response(p)
        for receipt in r['units'][1:]: receipt['entities'] = [row(context=' Alpha. ')]
        state = units.evaluate(clean, p, r)
        self.assertTrue(state['complete'])
        self.assertEqual([r['start'] for r in units.occurrences(clean, state)], [636, 1279])

    def test_total_limit_includes_frozen_and_common_words(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities'] = [row()] * 129
        with self.assertRaisesRegex(ContentBlocked, 'entity_count_limit'): units.evaluate(CLEAN, p, r)

    def test_conflicting_initial_spans_are_all_repairable_not_first_wins(self):
        clean = deepcopy(CLEAN); clean['blocks'][0]['text'] = 'New York and Alpha.'
        p = units.initial_payload(clean, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(text='York', context='New York'),
            row(text='New York', context='New York'), row(context='and Alpha.')]
        first = units.evaluate(clean, p, r)
        self.assertEqual([r['text'] for r in first['accepted']], ['Alpha'])
        patch = units.repair_payload(clean, 'en', first, 7); rr = response(patch)
        rr['units'][0]['entities'] = [row(text='New York', context='New York')]
        self.assertTrue(units.evaluate(clean, patch, rr, previous=first)['complete'])

    def test_title_repair_has_readonly_neighbor_and_cannot_extract_it(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][0]['coverage'] = 'uncertain'
        state = units.evaluate(CLEAN, p, r); patch = units.repair_payload(CLEAN, 'en', state, 7)
        self.assertEqual(patch['context_units'][0]['text'], CLEAN['blocks'][0]['text'])
        rr = response(patch)
        rr['units'].append({'unit_id': patch['context_units'][0]['unit_id'], 'coverage': 'complete', 'entities': []})
        with self.assertRaises(ContentBlocked): units.evaluate(CLEAN, patch, rr, previous=state)

    def test_missing_unit_feedback_is_stable_across_worker_hash_seeds(self):
        import os, subprocess, sys
        script = '''import django; django.setup()
import json
from stable.services.news_entity_units import initial_payload,evaluate,repair_payload
c={'title':'Title','blocks':[{'id':'b'+str(i),'text':'Text.'} for i in range(8)],'source_sha':'s','clean_sha':'c'}
p=initial_payload(c,'en');s=evaluate(c,p,{'units':[]})
print(json.dumps(repair_payload(c,'en',s,1),sort_keys=True))'''
        outputs = [subprocess.check_output([sys.executable, '-c', script],
            env={**os.environ, 'PYTHONHASHSEED': seed}, text=True) for seed in ('1', '2', '3')]
        self.assertEqual(outputs[0], outputs[1]); self.assertEqual(outputs[1], outputs[2])


    def test_unique_neighbor_quote_moves_to_correct_core_without_copying_type_elsewhere(self):
        c = deepcopy(CLEAN); c['blocks'][0]['text'] = 'X' * 640 + '. Alpha arrives.'
        p = units.initial_payload(c, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(context='Alpha arrives.')]
        state = units.evaluate(c, p, r)
        self.assertTrue(state['complete'])
        self.assertEqual(state['accepted'][0]['unit_id'], p['units'][2]['unit_id'])
        self.assertEqual(state['accepted'][0]['start'], 642)

    def test_same_span_different_types_remains_conflict(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(), {**row(), 'type': 'place'}]
        state = units.evaluate(CLEAN, p, r)
        self.assertFalse(state['complete']); self.assertEqual(state['accepted'], [])

    def test_candidate_selection_resolves_one_position_with_original_context(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(context='Alpha')]
        first = units.evaluate(CLEAN, p, r); patch = units.repair_payload(CLEAN, 'en', first, 1)
        issue = patch['issues'][0]; candidate = issue['candidates'][1]
        rr = response(patch)
        rr['decisions'] = [{'issue_id': issue['issue_id'], 'picks': [{'candidate_id': candidate['candidate_id'], 'type': 'horse'}]}]
        final = units.evaluate(CLEAN, patch, rr, previous=first)
        self.assertTrue(final['complete'])
        out = units.occurrences(CLEAN, final)
        self.assertEqual(out[0]['start'], 12); self.assertIn('Alpha', out[0]['context'])

    def test_missing_or_unknown_candidate_decision_cannot_complete(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p); r['units'][1]['entities'] = [row(context='Alpha')]
        first = units.evaluate(CLEAN, p, r); patch = units.repair_payload(CLEAN, 'en', first, 1)
        self.assertFalse(units.evaluate(CLEAN, patch, response(patch), previous=first)['complete'])
        rr = response(patch); rr['decisions'] = [{'issue_id': patch['issues'][0]['issue_id'], 'picks': [{'candidate_id': 'invented', 'type': 'horse'}]}]
        with self.assertRaises(ContentBlocked): units.evaluate(CLEAN, patch, rr, previous=first)

    def test_candidate_id_binds_source_and_cannot_be_used_in_initial_response(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p); r['units'][1]['entities'] = [row(context='Alpha')]
        first = units.evaluate(CLEAN, p, r)
        c = deepcopy(CLEAN); c['clean_sha'] = 'changed'
        p2 = units.initial_payload(c, 'en'); second = units.evaluate(c, p2, r)
        self.assertNotEqual(first['issues'][0]['candidates'][0]['candidate_id'], second['issues'][0]['candidates'][0]['candidate_id'])
        r['units'][1]['entities'] = [{'candidate_id': first['issues'][0]['candidates'][0]['candidate_id'], 'type': 'horse'}]
        self.assertFalse(units.evaluate(CLEAN, p, r)['complete'])

    def test_repair_cannot_add_new_entity_from_readonly_neighbor(self):
        c = deepcopy(CLEAN); c['blocks'][0]['text'] = 'X' * 640 + '. Alpha arrives.'
        p = units.initial_payload(c, 'en'); r = response(p); r['units'][1]['coverage'] = 'uncertain'
        first = units.evaluate(c, p, r); patch = units.repair_payload(c, 'en', first, 1)
        rr = response(patch); rr['units'][0]['entities'] = [row(context='Alpha arrives.')]
        final = units.evaluate(c, patch, rr, previous=first)
        self.assertFalse(final['complete']); self.assertEqual(final['accepted'], [])

    def test_candidate_overlapping_frozen_boundary_still_fails(self):
        c = deepcopy(CLEAN); c['blocks'][0]['text'] = 'France Galop met France Galop Committee.'
        p = units.initial_payload(c, 'en'); r = response(p)
        r['units'][1]['entities'] = [row('France Galop', c['blocks'][0]['text']),
            row('France Galop Committee', 'France Galop Committee.')]
        first = units.evaluate(c, p, r); patch = units.repair_payload(c, 'en', first, 1)
        issue = patch['issues'][0]; candidate = next(c for c in issue['candidates'] if c['status']=='overlap_conflict')
        rr = response(patch); rr['decisions']=[{'issue_id':issue['issue_id'],'picks':[{'candidate_id':candidate['candidate_id'],'type':'horse'}]}]
        final = units.evaluate(c, patch, rr, previous=first)
        self.assertFalse(final['complete']); self.assertEqual(final['accepted'], first['accepted'])

    def test_same_text_at_two_positions_can_have_different_types(self):
        p = units.initial_payload(CLEAN, 'en'); r = response(p)
        r['units'][1]['entities']=[row(), {**row(context='Alpha returns.'),'type':'person'}]
        state=units.evaluate(CLEAN,p,r)
        self.assertTrue(state['complete'])
        self.assertEqual([x['type'] for x in state['accepted']],['horse','person'])

    def test_more_than_128_candidates_cannot_be_silently_truncated(self):
        c = deepcopy(CLEAN); c['blocks'][0]['text'] = 'Z ' * 129
        p = units.initial_payload(c, 'en'); r = response(p)
        r['units'][1]['entities'] = [row('Z', 'Z')]
        with self.assertRaisesRegex(ContentBlocked, 'entity_candidate_limit'):
            units.evaluate(c, p, r)

    def test_neighbor_ambiguous_candidates_include_owner_in_repair_scope(self):
        c = deepcopy(CLEAN); c['blocks'][0]['text'] = 'X' * 640 + '. Alpha Alpha.'
        p = units.initial_payload(c, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(context='Alpha')]
        first = units.evaluate(c, p, r); patch = units.repair_payload(c, 'en', first, 1)
        self.assertIn(p['units'][2]['unit_id'], first['pending'])
        issue = patch['issues'][0]; rr = response(patch)
        rr['decisions'] = [{'issue_id': issue['issue_id'], 'picks': [
            {'candidate_id': c['candidate_id'], 'type': 'horse'} for c in issue['candidates']]}]
        final = units.evaluate(c, patch, rr, previous=first)
        self.assertTrue(final['complete']); self.assertEqual(len(final['accepted']), 2)

    def test_neighbor_type_conflicts_include_actual_owner_for_correction(self):
        c = deepcopy(CLEAN); c['blocks'][0]['text'] = 'X' * 640 + '. Alpha.'
        p = units.initial_payload(c, 'en'); r = response(p)
        r['units'][1]['entities'] = [row(context='Alpha.'), {**row(context='Alpha.'),'type':'person'}]
        first = units.evaluate(c, p, r); patch = units.repair_payload(c, 'en', first, 1)
        self.assertIn(p['units'][2]['unit_id'], first['pending'])
        rr = response(patch)
        next(u for u in rr['units'] if u['unit_id']==p['units'][2]['unit_id'])['entities']=[row(context='Alpha.')]
        final = units.evaluate(c, patch, rr, previous=first)
        self.assertTrue(final['complete']); self.assertEqual(len(final['accepted']), 1)
