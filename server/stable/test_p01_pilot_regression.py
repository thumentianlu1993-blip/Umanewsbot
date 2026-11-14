"""真实小批试跑发现的问题及边界回归；不调用外部服务。"""
from django.test import SimpleTestCase
from stable.services.news_numeric_equivalence import audit_equivalent_numbers, explicit_date


class PilotNumericTests(SimpleTestCase):
    def test_month_abbreviations_in_dates(self):
        for source, target in [('Nov. 27', '11月27日'), ('27 Sept. 2026', '2026年9月27日'), ('Jan 2', '1月2日')]:
            with self.subTest(source=source):
                self.assertFalse(audit_equivalent_numbers(source, target)['differences'])
        self.assertEqual(explicit_date('27 Sept. 2026'), '2026-09-27')
        self.assertIsNone(explicit_date('Nov. 27'))
        self.assertIsNone(explicit_date('Feb. 30, 2026'))
        self.assertTrue(audit_equivalent_numbers('Nov. 27', '10月27日')['differences'])
        self.assertTrue(audit_equivalent_numbers('Nov. 27', '2026年11月27日')['differences'])
        self.assertTrue(audit_equivalent_numbers('Nov', '11')['differences'])

    def test_racing_length_fractions(self):
        for source, target in [('a length-and-a-half', '1.5个马位'), ('one-and-a-half lengths', '一个半马位'), ('two-and-a-quarter lengths', '两个又四分之一马位')]:
            with self.subTest(source=source):
                self.assertFalse(audit_equivalent_numbers(source, target)['differences'])
        for target in ['2.5个马位', '1个马位', '领先获胜']:
            self.assertTrue(audit_equivalent_numbers('a length-and-a-half', target)['differences'])
        self.assertTrue(audit_equivalent_numbers('Half Moon', '0.5')['differences'])

from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import json
from unittest.mock import patch
from django.test import override_settings
from stable.services.news_content import ContentBlocked, validate_entities, restore_translation
from stable.services.news_pipeline import context_payload, context_projection, digest
from stable.test_p01_annotation_translation import clean, occurrence


def fixture_cases():
    return json.loads((Path(__file__).parent / 'fixtures/p01_live_pilot_failures_20261114.json').read_text())['cases']


@override_settings(NEWS_QUALITY_POLICY={'contract_version': 'context-v3'})
class PilotPayloadTests(SimpleTestCase):
    def test_full_hong_kong_audit_fits_without_duplicate_body(self):
        c = next(c for c in fixture_cases() if c['sample_id'] == 'D006')
        run = SimpleNamespace(stage='fact_audit', clean_snapshot=c['clean'], translation_snapshot=c['target'],
                              entity_snapshot={'occurrences': c['entities']}, editorial_snapshot={})
        payload = context_payload(run)
        self.assertNotIn('body', payload['target'])
        self.assertEqual(payload['target']['blocks'], c['target']['blocks'])
        self.assertEqual(payload['target_sha'], digest(c['target']))
        self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode()), 50000)

    def test_neutral_honorific_enters_bounded_repair(self):
        source = clean('Alex氏が来日。')
        rows = validate_entities(source, {'coverage':'complete', 'entities':[occurrence(source, 'Alex', 'person')]}, contract_version='racing-spans-v1')
        raw = {'title':'消息', 'summary':'Alex来访。', 'blocks':[{'id':'b0', 'text':rows[0]['token']+'先生来日。'}]}
        run = SimpleNamespace(clean_snapshot=source, entity_snapshot={'occurrences':rows}, quality_snapshot={}, repair_count=0, manual_target={})
        result = context_projection(run, SimpleNamespace(stage='translate_full',result=raw,pk=1,usage={'input':{'mode':'full'}}))
        self.assertEqual(result['stage'], 'translate_full')
        self.assertEqual(result['quality_snapshot']['repair_block_ids'], ['b0'])
        self.assertIn('neutral_honorific', str(result['quality_snapshot']['repair_task']))

    def test_event_payload_uses_quotes_in_both_contracts(self):
        run=SimpleNamespace(stage='event_classify',clean_snapshot=clean(),source_snapshot={'source_site':'x'},manual_target={},editor_provenance={})
        with patch('stable.services.news_pipeline._event_candidates', return_value=[]):
            payload=context_payload(run)
        self.assertIn('quote', str(payload['response_schema']))
        self.assertIn('quote', str(payload['identity_contract']))

class PilotRequestTests(SimpleTestCase):
    def test_effort_is_bounded_to_thinking_profile(self):
        from stable.services.news_model_gateway import request_spec, RequestDenied
        spec = {'provider':'openai','model':'model','prompt_version':'pilot-v1','input_per_million':'1',
                'output_per_million':'2','max_output_tokens':16384,'max_input_bytes':50000,
                'quality_tier':'strong','thinking':'enabled','http_timeout_seconds':120,'reasoning_effort':'invalid'}
        policy={'contract_version':'context-v3','models':{'fact_audit':{'deep':spec}}}
        with override_settings(NEWS_QUALITY_POLICY=policy), self.assertRaises(RequestDenied):
            request_spec('fact_audit',profile='deep')
        spec['reasoning_effort']='low'
        with override_settings(NEWS_QUALITY_POLICY=policy):
            self.assertEqual(request_spec('fact_audit',profile='deep')['reasoning_effort'],'low')
        spec['thinking']='disabled'
        policy['models']['fact_audit']=spec
        with override_settings(NEWS_QUALITY_POLICY=policy), self.assertRaises(RequestDenied):
            request_spec('fact_audit')

@override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3'})
class PilotEvidenceTests(SimpleTestCase):
    def test_compact_target_replays_each_revision_and_manual_and_rejects_tampering(self):
        from stable.services.news_translation_quality import expected_audit_payload, audit_target_from_payload, validate_audit_payload
        from stable.services.news_content import manual_translation
        source=clean('News')
        for target in [{'title':'新闻','summary':'摘要','body':'旧译文','blocks':[{'id':'b0','text':'旧译文'}]},
                       {'title':'新闻','summary':'摘要','body':'新译文','blocks':[{'id':'b0','text':'新译文'}]},
                       manual_translation({'title':'新闻','summary':'摘要','body':'人工内容'})]:
            run=SimpleNamespace(clean_snapshot=source,entity_snapshot={'occurrences':[]},editorial_snapshot={})
            payload=expected_audit_payload(source,target,[],{})
            self.assertEqual(audit_target_from_payload(payload),target)
            validate_audit_payload(run,payload,target)
            for mutate in [lambda p:p['target']['blocks'].clear(),lambda p:p.update(target_sha='x'),
                           lambda p:p['target'].pop('manual',None) if 'manual' in p['target'] else p['target'].update(summary='changed'),
                           lambda p:p['source'].update(title='changed')]:
                bad=deepcopy(payload);mutate(bad)
                with self.assertRaises(ContentBlocked):validate_audit_payload(run,bad,target)

    def test_neutral_honorific_exceptions_are_person_bound(self):
        from stable.services.news_translation_quality import translation_issues
        for original, translated, bad in [('Alex氏は来日。','Alex先生来日。',True),('Alex氏は来日。','Alex来日。',False),
                ('Mr. Alex。Alex氏は来日。','Alex先生来日。',False),('Mr. Bob。Alex氏は来日。','Alex先生来日。',True),('Mr. Alex-Smith。Alex氏は来日。','Alex先生来日。',True),('Mr. Alex’Lee。Alex氏は来日。','Alex先生来日。',True),
                ('Alex氏名を記入。','Alex先生来日。',False),('Alex氏は来日。','Alex说老师先生来了。',False)]:
            source=clean(original);start=original.rindex('Alex')
            row={'type':'person','block_id':'b0','start':start,'end':start+4,'text':'Alex','replacement':'Alex'}
            target={'title':'新闻','summary':'摘要','blocks':[{'id':'b0','text':translated}]}
            self.assertEqual(bool(translation_issues(source,target,[row])),bad,original)

    def test_name_form_hints_do_not_merge_ambiguous_surnames(self):
        from stable.services.news_translation_quality import name_form_hints
        source=clean('Alex Smith. Smith. Bob Smith. Smith.')
        def row(text,start):return {'type':'person','text':text,'block_id':'b0','start':start,'end':start+len(text)}
        rows=[row('Alex Smith',0),row('Smith',12)]
        self.assertEqual(len(name_form_hints(source,rows)),1)
        self.assertEqual(name_form_hints(source,rows+[row('Bob Smith',19),row('Smith',30)]),[])
        self.assertEqual(name_form_hints(source,[rows[1]]),[])

    def test_phrase_catalog_provenance_is_type_and_version_bound(self):
        from stable.services.news_translation_quality import apply_phrases, valid_phrase
        from stable.services.news_content import translation_glossary
        for kind in ['place','horse','person']:
            source=clean('Hong Kong')
            rows=validate_entities(source,{'coverage':'complete','entities':[occurrence(source,'Hong Kong',kind)]},contract_version='racing-spans-v1')
            rows=apply_phrases(rows)
            self.assertEqual(rows[0]['replacement'],'香港' if kind=='place' else 'Hong Kong')
            translation_glossary(source,rows)
            if kind=='place':
                self.assertTrue(valid_phrase(rows[0]))
                for key,value in [('catalog_version','bad'),('type','horse'),('replacement','other')]:
                    bad=deepcopy(rows);bad[0][key]=value
                    with self.assertRaises(ContentBlocked):translation_glossary(source,bad)

    def test_quoted_editorial_preserves_identity_rules_and_old_failures(self):
        from stable.services.news_editorial import validate_editorial
        source=clean('Race ID R42.')
        response={'priority':'regional','primary_region':'japan','reason':'赛事结果',
                  'identity':{'kind':'race','fields':{'source_race_id':'R42'},'evidence':{'source_race_id':{'block_id':'b0','quote':'R42','context':'Race ID R42.'}}},
                  'facts':[{'subject_ref':'R42','predicate':'announced','object':'Race','effective_time':'','modality':'happened','source_span':{'block_id':'b0','quote':'Race ID R42.','context':'Race ID R42.'},'importance':'major','relation':'new','prior_fact_ids':[]}],'comparison':{'event_id':None,'version':0}}
        self.assertEqual(validate_editorial(source,response,source_scope='jra')['identity']['evidence']['source_race_id'], {'block_id':'b0','start':8,'end':11})
        for mutate in [lambda r:r['identity']['fields'].update(source_race_id='invented'),
                       lambda r:r['identity']['evidence']['source_race_id'].update(extra=True),
                       lambda r:r['identity']['evidence']['source_race_id'].update(quote='absent')]:
            bad=deepcopy(response);mutate(bad)
            with self.assertRaises(ContentBlocked):validate_editorial(source,bad,source_scope='jra')
        for c in fixture_cases():
            with self.subTest(sample=c['sample_id']), self.assertRaises(ContentBlocked):
                validate_editorial(c['clean'],c['editorial_response'],source_scope=c['source_site'])

    def test_actual_request_passes_reasoning_effort_to_sdk(self):
        from stable.services.news_model_gateway import _single_request
        spec={'contract_version':'context-v3','thinking':'enabled','reasoning_effort':'low','max_output_tokens':16384}
        with override_settings(NEWS_QUALITY_API_KEY='fixture'), patch('openai.OpenAI') as client:
            _single_request(SimpleNamespace(stage='fact_audit',model='model',usage={'price':spec}),{})
            kwargs=client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs['reasoning_effort'],'low')
        self.assertEqual(kwargs['max_tokens'],16384)

from django.test import TransactionTestCase
from django.conf import settings
from stable.test_p01_news_workflow import ContextWorkflowFixture
from stable.services.news_pipeline import start_revision

class PilotCompactWorkflow(ContextWorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        policy=deepcopy(settings.NEWS_QUALITY_POLICY);policy['contract_version']='context-v3'
        change=self.settings(NEWS_QUALITY_POLICY=policy);change.enable();self.addCleanup(change.disable)
        self.run=start_revision(self.article)
        self.fail_first_audit=False

    def fake_response(self, attempt, payload):
        response=super().fake_response(attempt,payload)
        if attempt.stage=='fact_audit' and self.fail_first_audit and self.audit_count==1:
            data=json.loads(response.choices[0].message.content)
            data.update(verdict='fail',issues=[{'kind':'unsupported_claims','source':{'block_id':'b1','quote':'27','context':'The prize is 27.'},
                'target':{'block_id':'b1','quote':'27','context':'奖金为27。'},'missing':False}])
            data['checks']['unsupported_claims']=False
            response.choices[0].message.content=json.dumps(data)
        return response

    def assert_replay(self):
        from stable.services.news_publication import check_publication_evidence
        from stable.services.news_translation_quality import audit_target_from_payload
        self.assertEqual(self.run.state,'shadow',self.run.reason)
        check_publication_evidence(self.run)
        for attempt in self.run.attempts.filter(stage='fact_audit'):
            payload=attempt.usage['input']
            self.assertNotIn('body',payload['target'])
            self.assertTrue(audit_target_from_payload(payload)['body'])

    def test_hard_repair_chain(self):
        self.first_bad_number=True;self.finish();self.assert_replay()
        self.assertEqual(self.run.repair_count,1)

    def test_uncertain_to_deep_chain(self):
        self.first_uncertain=True;self.finish();self.assert_replay()
        self.assertEqual(self.profiles,['base','deep'])

    def test_failed_audit_then_patch_chain(self):
        self.fail_first_audit=True;self.finish();self.assert_replay()
        self.assertEqual(self.run.repair_count,1)

class PilotEditorialProfileTests(SimpleTestCase):
    def test_v3_editorial_uses_existing_deep_profile_without_changing_v2(self):
        from stable.services.news_pipeline import required_profile
        run=SimpleNamespace(stage='event_classify')
        with override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3'}):
            self.assertEqual(required_profile(run),'deep')
        with override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v2'}):
            self.assertEqual(required_profile(run),'base')

    @override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3'})
    def test_real_editorial_hallucinations_stay_rejected(self):
        from stable.services.news_editorial import validate_editorial
        fixtures=json.loads((Path(__file__).parent/'fixtures/p01_live_pilot_failures_20261114.json').read_text())
        sources={c['sample_id']:c for c in fixtures['cases']}
        for row in fixtures['retest_editorial_failures']:
            c=sources[row['sample_id']]
            with self.subTest(sample=row['sample_id']), self.assertRaises(ContentBlocked):
                validate_editorial(c['clean'],row['response'],source_scope=c['source_site'])

@override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3'})
class PilotRepairCapacityTests(SimpleTestCase):
    def test_real_hong_kong_local_repair_stays_within_payload_limit(self):
        from stable.services.news_model_gateway import reservation_amount
        f=json.loads((Path(__file__).parent/'fixtures/p01_live_pilot_failures_20261114.json').read_text())
        c=next(c for c in f['cases'] if c['sample_id']=='D006');repair=f['repair_regression']
        run=SimpleNamespace(stage='translate_full',clean_snapshot=c['clean'],entity_snapshot={'occurrences':repair['entities']},quality_snapshot=repair['quality'],repair_count=1)
        payload=context_payload(run)
        reservation_amount(payload,{'max_input_bytes':50000,'input_per_million':'0.3','output_per_million':'1.2','max_output_tokens':8192})
        self.assertEqual(payload['required_block_ids'],['b002'])
        self.assertEqual(len(payload['entity_glossary']),len(repair['entities']))

    def test_japanese_nonpast_announcement_does_not_add_completed_state(self):
        from stable.services.news_translation_quality import translation_issues
        for original,target,bad in [('短期騎手免許を交付しますので、お知らせします。','现通知，已向Alex发放短期骑师执照。',True),
                                    ('短期騎手免許を交付しますので、お知らせします。','现通知，将向Alex发放短期骑师执照。',False),
                                    ('短期騎手免許を交付しました。','已向Alex发放短期骑师执照。',False),
                                    ('短期騎手免許を交付しますので、お知らせします。','已公布将向Alex发放短期骑师执照。',False)]:
            t={'title':'公告','summary':'执照公告','blocks':[{'id':'b0','text':target}]}
            self.assertEqual(bool(translation_issues(clean(original),t,[])),bad)
