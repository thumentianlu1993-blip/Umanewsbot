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
        self.language_block=None
        self.repeat_language_failure=False

    def fake_response(self, attempt, payload):
        response=super().fake_response(attempt,payload)
        if attempt.stage=='fact_audit' and self.fail_first_audit and self.audit_count==1:
            data=json.loads(response.choices[0].message.content)
            data.update(verdict='fail',issues=[{'kind':'unsupported_claims','source':{'block_id':'b1','quote':'27','context':'The prize is 27.'},
                'target':{'block_id':'b1','quote':'27','context':'奖金为27。'},'missing':False}])
            data['checks']['unsupported_claims']=False
            response.choices[0].message.content=json.dumps(data)
        if self.language_block:
            data=json.loads(response.choices[0].message.content)
            block=self.language_block
            if attempt.stage=='translate_full':
                if payload.get('mode')=='repair_blocks':
                    text={'title':'奖金调整公告','summary':'官方调整奖金','b1':'奖金为27。'}[block]
                    data['replacements']=[{'id':block,'text':text}]
                elif self.translation_count==1:
                    text={'title':'奖金调整调整公告','summary':'官方调整调整奖金','b1':'奖金为为27。'}[block]
                    if block in {'title','summary'}:data[block]=text
                    else:next(b for b in data['blocks'] if b['id']==block)['text']=text
            if attempt.stage=='fact_audit' and (self.audit_count==1 or self.repeat_language_failure):
                target=payload['target'];text=target[block] if block in {'title','summary'} else next(b['text'] for b in target['blocks'] if b['id']==block)
                source=payload['source'];source_id='title' if block=='title' else 'b1'
                quote=source['title'] if source_id=='title' else next(b['text'] for b in source['blocks'] if b['id']==source_id)
                data.update(verdict='fail',issues=[{'kind':'fluency','source':{'block_id':source_id,'quote':quote,'context':quote},
                    'target':{'block_id':block,'quote':text,'context':text},'missing':False}])
                data['checks']['fluency']=False
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

    def test_language_failure_repairs_body_title_and_summary_locally(self):
        for block in ['b1','title','summary']:
            with self.subTest(block=block):
                snapshot=deepcopy(self.run.source_snapshot)
                snapshot['title']='Notice '+{'b1':'body','title':'headline','summary':'summary'}[block]
                self.run=start_revision(self.article,snapshot=snapshot)
                self.language_block=block;self.audit_count=0;self.translation_count=0
                self.finish();self.assert_replay()
                self.assertEqual(self.run.repair_count,1)
                patch_attempt=self.run.attempts.filter(stage='translate_full').last()
                self.assertEqual(patch_attempt.usage['input']['required_block_ids'],[block])
                original=self.run.attempts.filter(stage='translate_full').first().result
                final=self.run.translation_snapshot
                if block!='title':self.assertEqual(original['title'],final['title'])
                if block!='summary':self.assertEqual(original['summary'],final['summary'])
                self.assertEqual(self.audit_count,2)

    def test_language_failure_after_one_patch_stops_for_review(self):
        self.language_block='b1';self.repeat_language_failure=True
        self.finish()
        self.assertEqual(self.run.state,'review',self.run.reason)
        self.assertEqual(self.run.repair_count,1)
        self.assertEqual(self.translation_count,2)
        self.assertEqual(self.audit_count,2)

    def test_publication_rejects_receipt_without_language_check(self):
        from stable.services.news_publication import check_publication_evidence
        self.finish();self.assert_replay()
        from stable.services.news_publication import _validated_attempt
        def without_language(run, attempt_id, stage):
            attempt=_validated_attempt(run,attempt_id,stage)
            if stage=='fact_audit':attempt.result['checks'].pop('fluency')
            return attempt
        # 不修改数据库封存证据；直接验证发布层仍拒绝缺少该检查的旧形状。
        with patch('stable.services.news_publication._validated_attempt',side_effect=without_language):
            with self.assertRaises(ContentBlocked):check_publication_evidence(self.run)

    def test_configured_deep_audit_replays_and_rejects_downgrade(self):
        from stable.services.news_publication import validate_context_chain
        policy=deepcopy(settings.NEWS_QUALITY_POLICY);policy['audit_min_profile']='deep'
        with self.settings(NEWS_QUALITY_POLICY=policy):
            self.run=start_revision(self.article)
            self.finish();self.assert_replay()
            audit=self.run.attempts.get(stage='fact_audit')
            self.assertEqual(audit.usage['price']['profile'],'deep')
            lower=SimpleNamespace(pk=audit.pk,usage={'price':{'profile':'base'}})
            with self.assertRaisesRegex(ContentBlocked,'deep_audit_missing'):
                validate_context_chain(self.run,lower)

    def test_configured_deep_uncertain_does_not_add_another_request(self):
        policy=deepcopy(settings.NEWS_QUALITY_POLICY);policy['audit_min_profile']='deep'
        with self.settings(NEWS_QUALITY_POLICY=policy):
            self.first_uncertain=True
            self.run=start_revision(self.article);self.finish()
            self.assertEqual(self.run.state,'review')
            self.assertEqual(self.run.reason,'deep_uncertain')
            self.assertEqual(self.audit_count,1)

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


class QualityBoundaryTests(SimpleTestCase):
    """Q1-Q3：预设响应验证程序边界，不证明模型能自行发现语义错误。"""
    def cases(self):
        return json.loads((Path(__file__).parent/'fixtures/p01_quality_boundaries_20261115.json').read_text())['cases']

    def target(self, case):
        return {'title':case['target'], 'summary':'摘要', 'body':case['target'],
                'blocks':[{'id':'b0','text':case['target']}]}

    def response(self, source, target, kind='fluency'):
        from stable.services.news_content import AUDIT_CHECKS
        return {'verdict':'fail', 'checks':{key:key!=kind for key in AUDIT_CHECKS | {'fluency'}}, 'issues':[
            {'kind':kind,'source':{'block_id':'b0','quote':source,'context':source},
             'target':{'block_id':'b0','quote':target,'context':target},'missing':False}]}

    def test_v3_requires_language_check_but_old_contracts_keep_nine(self):
        from stable.services.news_content import validate_audit, AUDIT_CHECKS
        source=clean('News');target=self.target({'target':'新闻'})
        old={'verdict':'pass','checks':{key:True for key in AUDIT_CHECKS},'issues':[]}
        for version in ['legacy','context-v2']:
            self.assertTrue(validate_audit(source,target,old,contract_version=version)['passed'])
        self.assertFalse(validate_audit(source,target,old,contract_version='context-v3')['passed'])
        new=deepcopy(old);new['checks']['fluency']=True
        self.assertTrue(validate_audit(source,target,new,contract_version='context-v3')['passed'])
        self.assertFalse(validate_audit(source,target,new,contract_version='context-v2')['evidence_valid'])

    def test_real_failures_accept_evidenced_language_issues_not_old_pass(self):
        from stable.services.news_content import validate_audit
        for case in self.cases():
            with self.subTest(sample=case['sample_id']):
                source=clean(case['source']);target=self.target(case)
                self.assertEqual(case['observed_model_audit']['verdict'],'pass')
                value=validate_audit(source,target,self.response(case['source'],case['target']),contract_version='context-v3')
                self.assertTrue(value['evidence_valid'],value)
                self.assertFalse(value['passed'])
                self.assertEqual(value['repair_block_ids'],['b0'])
                self.assertEqual(value['located_issues'][0]['located']['target'],[0,len(case['target'])])

    def test_issue_check_consistency_and_invalid_evidence_fail_closed(self):
        from stable.services.news_content import validate_audit
        case=self.cases()[-1];source=clean(case['source']);target=self.target(case)
        original=self.response(case['source'],case['target'])
        for mutate in [lambda r:r['checks'].update(fluency=True),
                       lambda r:r['checks'].update(attribution=False),
                       lambda r:r.update(verdict='pass'),
                       lambda r:r['issues'][0]['target'].update(quote='不存在'),
                       lambda r:r['checks'].update(style=True),
                       lambda r:r['issues'][0].update(kind='style'),
                       lambda r:r.update(issues=[])]:
            value=deepcopy(original);mutate(value)
            self.assertFalse(validate_audit(source,target,value,contract_version='context-v3')['evidence_valid'])
        # 新一致性约束也覆盖旧事实维度，而不是只检查fluency。
        bad=self.response(case['source'],case['target'],'attribution');bad['checks']['attribution']=True
        self.assertFalse(validate_audit(source,target,bad,contract_version='context-v3')['evidence_valid'])

    def test_plain_descriptions_unprotected_named_homonyms_preserved(self):
        from stable.services import news_entity_units as units
        from stable.services.news_content import protect_source
        for text in ['Second French Jockey Title','身元引受調教師','Spring Award','G1 Example Cup']:
            for kind in ['common_word','racing_honor','horse','race']:
                with self.subTest(text=text,kind=kind):
                    source=clean(text,title=text)
                    payload=units.initial_payload(source,'en',contract_version='context-v3')
                    response={'units':[{'unit_id':u['unit_id'],'coverage':'complete','entities':[
                        {'text':text,'type':kind,'context':text}]} for u in payload['units']]}
                    state=units.evaluate(source,payload,response)
                    rows=units.occurrences(source,state)
                    protected=protect_source(source,rows)
                    if kind=='common_word':
                        self.assertEqual(rows,[])
                        self.assertEqual(protected['title'],text)
                        self.assertEqual(protected['blocks'][0]['text'],text)
                    else:
                        self.assertEqual(len(rows),2)
                        self.assertNotEqual(protected['title'],text)
                        raw={'title':protected['title'],'summary':protected['title'],'blocks':protected['blocks']}
                        restored=restore_translation(source,rows,raw)
                        self.assertEqual(restored['title'],text)
                        self.assertEqual(restored['blocks'][0]['text'],text)

    def test_prompt_budget_legacy_identity_and_rendered_schema(self):
        import hashlib
        from stable.services.news_prompts import prompt_for
        baseline=json.loads((Path(__file__).parent/'fixtures/p01_quality_boundaries_20261115.json').read_text())['prompt_baseline']
        for version,stages in baseline['legacy_hashes'].items():
            for stage,sha in stages.items():
                self.assertEqual(hashlib.sha256(prompt_for(stage,version).encode()).hexdigest(),sha)
        for stage,limit in baseline['v3_char_limits'].items():
            self.assertLessEqual(len(prompt_for(stage,'context-v3')),limit,stage)
        audit=prompt_for('fact_audit','context-v3')
        schema,_=json.JSONDecoder().raw_decode(audit.split('返回且仅返回',1)[1])
        from stable.services.news_content import AUDIT_CHECKS
        self.assertEqual(set(schema['checks']),AUDIT_CHECKS | {'fluency'})
        for case in self.cases():
            for stage in baseline['v3_char_limits']:
                self.assertNotIn(case['target'],prompt_for(stage,'context-v3'))


@override_settings(NEWS_QUALITY_POLICY={'contract_version': 'context-v3'})
class StageBoundaryTests(SimpleTestCase):
    def cases(self):
        return json.loads((Path(__file__).parent/'fixtures/p01_stage_boundary_failures_20261115.json').read_text())

    def test_actual_quote_repair_has_no_candidate_operation(self):
        from stable.services import news_entity_units as units
        case = self.cases()['entity']; source = case['clean']
        first = units.evaluate(source, units.initial_payload(source, 'en', contract_version='context-v3'), case['initial_response'])
        payload = units.repair_payload(source, 'en', first, 2)
        self.assertEqual(payload['response_fields'], ['units'])
        self.assertEqual([i['code'] for i in payload['issues']], ['quote_not_found'])
        with self.assertRaises(ContentBlocked):
            units.evaluate(source, payload, case['observed_repair_response'], previous=first)
        corrected = {'units': deepcopy(case['observed_repair_response']['units'])}
        corrected['units'][0]['entities'] = [r for r in corrected['units'][0]['entities'] if r['text'] == 'Happy Valley']
        result = units.evaluate(source, payload, corrected, previous=first)
        self.assertTrue(result['complete'])
        self.assertEqual(len([r for r in result['accepted'] if r['text'] == 'Happy Valley']), 3)

    def test_actual_equivalent_mixed_fraction_is_not_a_translation_failure(self):
        from stable.services.news_content import hard_translation_checks
        c = self.cases()['numeric']
        self.assertEqual(hard_translation_checks(c['clean'], c['target'])['numeric']['b010']['status'], 'surface_match')
        self.assertTrue(hard_translation_checks(c['clean'], c['target'])['passed'])

    def test_generic_mixed_fractions_preserve_exact_value(self):
        from fractions import Fraction
        for whole, numerator, denominator in [(1,1,2), (2,3,4), (7,5,8), (0,7,10), (12,3,16)]:
            value = str(float(Fraction(whole) + Fraction(numerator, denominator)))
            for separator in ['又', ' ']:
                with self.subTest(whole=whole,numerator=numerator,denominator=denominator,separator=separator):
                    target = f'{whole}{separator}{numerator}/{denominator}马位'
                    self.assertEqual(audit_equivalent_numbers(value+' lengths', target)['status'], 'surface_match')
                    self.assertEqual(audit_equivalent_numbers(str(whole+2)+' lengths', target)['status'], 'surface_difference')
        self.assertEqual(audit_equivalent_numbers('1又1/3马位', '1又2/6马位')['status'], 'surface_match')
        self.assertEqual(audit_equivalent_numbers('1又1/3马位', '1.333333马位')['status'], 'surface_difference')
        for text in ['4/9 favourite', '2026/11/15', '1/2月']:
            self.assertEqual(audit_equivalent_numbers(text,text)['status'], 'surface_match')

    def test_unsupported_numeric_form_is_review_not_false_error_or_retry(self):
        from stable.services.news_content import hard_translation_checks, validate_audit
        from stable.services.news_prompts import audit_check_keys
        source = clean('Won by 1.5 lengths.', title='News')
        raw = {'title':'消息','summary':'获胜。','blocks':[{'id':'b0','text':'领先1又1/0马位获胜。'}]}
        target = {**raw, 'body': raw['blocks'][0]['text']}
        hard = hard_translation_checks(source, target)
        self.assertFalse(hard['passed'])
        self.assertEqual(hard['numeric']['b0']['status'], 'not_comparable')
        run = SimpleNamespace(clean_snapshot=source, entity_snapshot={'occurrences':[]}, quality_snapshot={}, repair_count=0, manual_target={})
        result = context_projection(run, SimpleNamespace(stage='translate_full',result=raw,pk=1,usage={'input':{'mode':'full'}}))
        self.assertEqual(result['state'], 'review')
        self.assertEqual(result['reason'], 'numeric_not_comparable')
        self.assertNotIn('repair_count', result)
        response = {'verdict':'pass','checks':dict.fromkeys(audit_check_keys('context-v3'),True),'issues':[]}
        self.assertFalse(validate_audit(source,target,response,contract_version='context-v3')['passed'])

    def test_audit_request_is_evidence_first_without_prefilled_success(self):
        from stable.services.news_prompts import prompt_for
        prompt = prompt_for('fact_audit','context-v3')
        schema,_ = json.JSONDecoder().raw_decode(prompt.split('返回且仅返回',1)[1])
        self.assertEqual(next(iter(schema)), 'issues')
        self.assertNotIn(True, schema['checks'].values())

    def test_v3_candidate_operations_and_v2_contract_remain_bound(self):
        from stable.services import news_entity_units as units
        source = clean('Alpha and Alpha.')
        for contract in ['context-v3','context-v2']:
            p = units.initial_payload(source,'en',contract_version=contract)
            response = {'units':[{'unit_id':u['unit_id'],'coverage':'complete','entities':[]}
                                 for u in p['units']]}
            response['units'][1]['entities'] = [{'text':'Alpha','type':'horse','context':'Alpha'}]
            first = units.evaluate(source,p,response)
            repair = units.repair_payload(source,'en',first,1)
            if contract == 'context-v3':
                self.assertEqual(p['response_fields'],['units'])
                self.assertEqual(repair['response_fields'],['units','decisions'])
                tampered = deepcopy(repair);tampered['response_fields']=['units']
                with self.assertRaisesRegex(ContentBlocked,'entity_unit_input_changed'):
                    units.evaluate(source,tampered,{'units':[]},previous=first)
            else:
                self.assertNotIn('response_fields',p)
                self.assertNotIn('response_fields',repair)
            issue = repair['issues'][0]
            corrected = {'units':[{'unit_id':u['unit_id'],'coverage':'complete','entities':[]} for u in repair['units']],
                'decisions':[{'issue_id':issue['issue_id'],'picks':[{'candidate_id':c['candidate_id'],'type':'horse'} for c in issue['candidates']]}]}
            final = units.evaluate(source,repair,corrected,previous=first)
            self.assertTrue(final['complete'])
            self.assertEqual([r['start'] for r in final['accepted']],[0,10])
            bad = deepcopy(corrected);bad['decisions'][0]['picks'][0]['candidate_id']='invented'
            with self.assertRaisesRegex(ContentBlocked,'entity_candidate_invalid'):
                units.evaluate(source,repair,bad,previous=first)

    def test_unknown_numeric_all_fields_manual_and_audit_cannot_bypass(self):
        from stable.services.news_content import hard_translation_checks, validate_audit, manual_translation
        from stable.services.news_prompts import audit_check_keys
        for location in ['title','body','summary','source']:
            for manual in [False,True]:
                with self.subTest(location=location,manual=manual):
                    source = clean('Won by 1.5 lengths.',title='News')
                    raw = {'title':'消息','summary':'获胜。','blocks':[{'id':'b0','text':'领先1.5马位获胜。'}]}
                    unknown = '领先1又1/0马位。'
                    if location == 'source':source['blocks'][0]['text']=unknown
                    elif location == 'body':raw['blocks'][0]['text']=unknown
                    else:raw[location]=unknown
                    target = {**raw,'body':raw['blocks'][0]['text']}
                    if manual:target = manual_translation({k:target[k] for k in ['title','summary','body']})
                    hard = hard_translation_checks(source,target)
                    self.assertFalse(hard['passed'])
                    self.assertTrue(hard['numeric_not_comparable'])
                    response = {'verdict':'pass','checks':dict.fromkeys(audit_check_keys('context-v3'),True),'issues':[]}
                    result = validate_audit(source,target,response,contract_version='context-v3')
                    self.assertFalse(result['passed'])
                    self.assertEqual(result['reason'],'numeric_not_comparable')
                    run = SimpleNamespace(clean_snapshot=source,translation_snapshot=target,editorial_snapshot={},entity_snapshot={"occurrences":[]},
                        quality_snapshot={},policy_sha='test',manual_target=target if manual else {},repair_count=0)
                    projection = context_projection(run, SimpleNamespace(stage='fact_audit',result=response,pk=4,input_sha='test',usage={'price':{'profile':'base'}}))
                    self.assertEqual(projection['state'],'review')
                    self.assertEqual(projection['reason'],'numeric_not_comparable')
                    self.assertNotIn('repair_count',projection)
                    self.assertNotIn('deep_required',projection['quality_snapshot'])
        # 相同未知表达也不能相互抵消；负带分数不冒充普通无符号数字。
        for text in ['1又1/0马位','-1又1/2马位','1又1/马位','1又1/-2马位','1又1/2/3马位','1又1/2.5马位']:
            self.assertEqual(audit_equivalent_numbers(text,text)['status'],'not_comparable')
        self.assertEqual(audit_equivalent_numbers('2026 11/15','2026年11月15日')['status'],'surface_match')

    def test_actual_sdk_messages_use_the_same_entity_response_fields(self):
        from stable.services import news_entity_units as units
        from stable.services.news_model_gateway import _single_request
        spec = {'contract_version':'context-v3','thinking':'disabled','max_output_tokens':8192}
        source = clean('Alpha and Alpha.')
        initial = units.initial_payload(source,'en',contract_version='context-v3')
        payloads = [initial]
        for text,context in [('absent','absent'),('Alpha','Alpha')]:
            response = {'units':[{'unit_id':u['unit_id'],'coverage':'complete','entities':[]} for u in initial['units']]}
            response['units'][1]['entities'] = [{'text':text,'context':context,'type':'horse'}]
            state = units.evaluate(source,initial,response)
            payloads.append(units.repair_payload(source,'en',state,1))
        for payload,fields in zip(payloads,[['units'],['units'],['units','decisions']]):
            with override_settings(NEWS_QUALITY_API_KEY='fixture'),patch('openai.OpenAI') as client:
                _single_request(SimpleNamespace(stage='entity_check',model='fixture',usage={'price':spec}),payload)
                messages = client.return_value.chat.completions.create.call_args.kwargs['messages']
            self.assertEqual(json.loads(messages[1]['content'])['response_fields'],fields)
            self.assertIn('顶层字段严格等于response_fields',messages[0]['content'])
            self.assertNotIn('无歧义decisions为空',messages[0]['content'])

    def test_audit_minimum_profile_is_validated_and_cannot_reduce_risk(self):
        from stable.services.news_pipeline import required_profile
        run=SimpleNamespace(stage='fact_audit',clean_snapshot=clean('A report.'),editorial_snapshot={},quality_snapshot={})
        for minimum,expected in [('base','base'),('deep','deep')]:
            with override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3','audit_min_profile':minimum}):
                self.assertEqual(required_profile(run),expected)
        with override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3','audit_min_profile':'invalid'}),self.assertRaises(ContentBlocked):
            required_profile(run)
        with override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v2','audit_min_profile':'deep'}):
            self.assertEqual(required_profile(run),'base')
        run.clean_snapshot=clean('A horse retired.')
        with override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3','audit_min_profile':'base'}):
            self.assertEqual(required_profile(run),'deep')


class AuditProtectedNameTests(SimpleTestCase):
    def case(self, text='Alex (North)', kind='fluency'):
        from stable.services.news_prompts import audit_check_keys
        source = clean(text, title='News')
        target = {'title':'消息','summary':'','blocks':[{'id':'b0','text':text}], 'body':text}
        entities = [{'block_id':'b0','start':0,'end':4,'text':'Alex','replacement':'Alex','type':'person'},
                    {'block_id':'b0','start':6,'end':11,'text':'North','replacement':'North','type':'place'}]
        ref = {'block_id':'b0','quote':text,'context':text}
        response = {'verdict':'fail','checks':dict.fromkeys(audit_check_keys('context-v3'),True),
                    'issues':[{'kind':kind,'source':ref.copy(),'target':ref.copy(),'missing':False}]}
        response['checks'][kind] = False
        return source,target,entities,response

    def test_preserved_original_names_are_not_a_repairable_fluency_error(self):
        from stable.services.news_content import validate_audit
        source,target,entities,response = self.case()
        result = validate_audit(source,target,response,contract_version='context-v3',entities=entities)
        self.assertFalse(result['passed'])
        self.assertFalse(result['evidence_valid'])
        self.assertEqual(result['reason'],'audit_protected_name_fluency')
        self.assertEqual(result['repair_block_ids'],[])

    def test_real_words_outside_protected_spans_still_need_review(self):
        from stable.services.news_content import validate_audit
        for text,kind in [('Alex (North) 在于在比赛。','fluency'),('Alex (North)','attribution')]:
            with self.subTest(text=text,kind=kind):
                source,target,entities,response = self.case(text,kind)
                result = validate_audit(source,target,response,contract_version='context-v3',entities=entities)
                self.assertTrue(result['evidence_valid'])
                self.assertFalse(result['passed'])
                self.assertEqual(result['repair_block_ids'],['b0'])

    def test_no_entity_or_common_word_is_not_silently_exempted(self):
        from stable.services.news_content import validate_audit
        source,target,entities,response = self.case()
        for rows in [[],[{**e,'type':'common_word'} for e in entities]]:
            result = validate_audit(source,target,response,contract_version='context-v3',entities=rows)
            self.assertTrue(result['evidence_valid'])
            self.assertFalse(result['passed'])

    @override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3'})
    def test_protected_only_issue_stops_before_spending_repair(self):
        source,target,entities,response = self.case()
        run = SimpleNamespace(clean_snapshot=source, translation_snapshot=target,
                              entity_snapshot={'occurrences':entities}, editorial_snapshot={},
                              quality_snapshot={}, policy_sha='policy', repair_count=0)
        attempt = SimpleNamespace(stage='fact_audit', result=response, pk=1, input_sha='input',
                                  usage={'price':{'profile':'base'}})
        result = context_projection(run,attempt)
        self.assertEqual(result['state'],'review')
        self.assertEqual(result['reason'],'audit_evidence_invalid')
        self.assertEqual(result['quality_snapshot']['reason'],'audit_protected_name_fluency')
        self.assertNotIn('repair_count',result)

    def test_mixed_issues_cannot_be_silently_dropped_to_pass(self):
        from stable.services.news_content import validate_audit
        source,target,entities,response = self.case()
        other = deepcopy(response['issues'][0]); other['kind']='attribution'
        response['issues'].insert(0,other); response['checks']['attribution']=False
        result=validate_audit(source,target,response,contract_version='context-v3',entities=entities)
        self.assertFalse(result['passed'])
        self.assertFalse(result['evidence_valid'])
        self.assertEqual(result['repair_block_ids'],[])
