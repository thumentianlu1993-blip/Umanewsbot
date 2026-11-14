"""九类实体协议、翻译保护及离线评估的行为回归。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings

from stable.services.news_content import ContentBlocked, validate_entities, protect_source, restore_translation
from stable.services import news_entity_units as units
from stable.services.news_pipeline import digest


def clean(text='Spring Festival and Silver Award.', title='News'):
    source = {'title': title, 'blocks': [{'id': 'b0', 'text': text}]}
    return {**source, 'source_sha': digest(source), 'clean_sha': digest(source)}


def occurrence(source, text, kind, block='b0'):
    value = source['title'] if block == 'title' else source['blocks'][0]['text']
    start = value.index(text)
    return {'block_id': block, 'start': start, 'end': start + len(text), 'text': text, 'type': kind}


class RacingTaxonomyContractTests(SimpleTestCase):
    def test_new_types_are_explicitly_versioned_and_legacy_remains_strict(self):
        for kind in ['race_related', 'racing_honor', 'auction', 'umamusume']:
            source = clean('Named Example')
            response = {'coverage': 'complete', 'entities': [occurrence(source, 'Named Example', kind)]}
            with self.assertRaises(ContentBlocked): validate_entities(source, response)
            result = validate_entities(source, response, contract_version='racing-spans-v1')
            self.assertEqual(result[0]['type'], kind)
            self.assertEqual(result[0]['replacement'], 'Named Example')
        with self.assertRaises(ContentBlocked):
            validate_entities(source, {'coverage': 'complete', 'entities': []}, contract_version='invented')

    def test_v3_unit_repair_preserves_new_type_and_does_not_mix_v2(self):
        source = clean()
        payload = units.initial_payload(source, 'en', contract_version='context-v3')
        response = {'units': [{'unit_id': u['unit_id'], 'coverage': 'complete', 'entities': []} for u in payload['units']]}
        response['units'][1]['entities'] = [
            {'text': 'Spring Festival', 'type': 'race_related', 'context': source['blocks'][0]['text']},
            {'text': 'absent', 'type': 'racing_honor', 'context': 'absent'}]
        first = units.evaluate(source, payload, response)
        self.assertFalse(first['complete'])
        repair = units.repair_payload(source, 'en', first, 9)
        final = units.evaluate(source, repair, {'units': [{'unit_id': repair['units'][0]['unit_id'],
            'coverage': 'complete', 'entities': [{'text': 'Silver Award', 'type': 'racing_honor',
            'context': source['blocks'][0]['text']}]}], 'decisions': []}, previous=first)
        self.assertEqual([r['type'] for r in units.occurrences(source, final)], ['race_related', 'racing_honor'])
        self.assertEqual(repair['entity_contract'], 'entity-units-v3')
        tampered = deepcopy(repair); tampered['entity_contract'] = 'entity-units-v2'
        with self.assertRaises(ContentBlocked): units.evaluate(source, tampered, {'units': [], 'decisions': []}, previous=first)

    def test_translation_glossary_and_roundtrip_preserve_new_names_and_plain_words(self):
        from stable.services.news_content import translation_glossary
        source = clean('😀Spring Festival reports a final run.', title='Spring Festival')
        entities = validate_entities(source, {'coverage': 'complete', 'entities': [
            occurrence(source, 'Spring Festival', 'race_related', 'title'),
            occurrence(source, 'Spring Festival', 'race_related')]}, contract_version='racing-spans-v1')
        glossary = translation_glossary(source, entities)
        self.assertEqual(len(glossary), 2)
        self.assertEqual(glossary[0]['type'], 'race_related')
        protected = protect_source(source, entities)
        body_token = next(r['token'] for r in entities if r['block_id']=='b0')
        response = {'title': protected['title'], 'summary': '最后一战的消息',
                    'blocks': [{'id': 'b0', 'text': '😀'+body_token+'报道最后一战。'}]}
        target = restore_translation(source, entities, response)
        self.assertEqual(target['body'], '😀Spring Festival报道最后一战。')
        response['blocks'][0]['text'] += body_token
        with self.assertRaises(ContentBlocked): restore_translation(source, entities, response)
        changed = deepcopy(entities); changed[0]['replacement'] = '捏造译名'
        with self.assertRaises(ContentBlocked): translation_glossary(source, changed)

    def test_glossary_refuses_conflicting_confirmed_target_for_same_term(self):
        from stable.services.news_content import translation_glossary
        source = clean('Alpha', title='Alpha')
        entities = validate_entities(source, {'coverage':'complete','entities':[
            occurrence(source, 'Alpha', 'horse', 'title'), occurrence(source, 'Alpha', 'horse')]})
        for i, row in enumerate(entities):
            row.update(term_id=123, replacement=['甲','乙'][i], provenance='confirmed_term_occurrence')
        with self.assertRaisesRegex(ContentBlocked, 'term_translation_conflict'): translation_glossary(source, entities)

    def test_v3_capacity_is_256_but_v2_stays_at_128(self):
        for count in [129,256,257]:
            source=clean(' '.join('Horse%03d'%i for i in range(count)))
            entities=[occurrence(source,'Horse%03d'%i,'horse') for i in range(count)]
            response={'coverage':'complete','entities':entities}
            with self.assertRaisesRegex(ContentBlocked, 'entity_count_limit'): validate_entities(source,response)
            if count<=256:
                self.assertEqual(len(validate_entities(source,response,contract_version='racing-spans-v1')),count)
            else:
                with self.assertRaisesRegex(ContentBlocked,'entity_count_limit'):
                    validate_entities(source,response,contract_version='racing-spans-v1')

    def test_v3_prompt_separates_initial_and_repair_and_never_enables_horse_lookup(self):
        from stable.services.news_prompts import prompt_for
        old = prompt_for('entity_check', 'context-v2')
        new = prompt_for('entity_check', 'context-v3')
        self.assertNotEqual(old, new)
        for kind in ['race_related','racing_honor','auction','umamusume']: self.assertIn(kind, new)
        self.assertIn('initial', new)
        self.assertIn('信息库', new)
        self.assertIn('entity_glossary', prompt_for('translate_full', 'context-v3'))


def reference(sid='D001', text='Alpha and Alpha.'):
    source = {'title':'News','blocks':[{'id':'b0','text':text}]}
    first = {'block_id':'b0','start':0,'end':5,'text':'Alpha','type':'horse'}
    second = {**first, 'start':10,'end':15}
    return {'schema':'p01-annotated-news-v1', 'sample_id':sid, 'source':source,
            'source_sha':digest(source), 'language':'en', 'original_split':'development',
            'evaluation_role':'development', 'leakage_group_id':sid, 'exposed':True,
            'annotation_status':'ai_assisted_with_human_adjudications', 'mentions':[first,second], 'name_groups':[]}


def prediction(ref, *, status='complete', mentions=None):
    return {'sample_id':ref['sample_id'], 'source_sha':ref['source_sha'], 'status':status,
            'phase':'initial', 'reference_sha':digest(ref), 'contract_version':'context-v3', 'mentions':deepcopy(ref['mentions'] if mentions is None else mentions)}


class AnnotationEvaluationTests(SimpleTestCase):
    def test_each_occurrence_and_failed_article_stay_in_denominator(self):
        from stable.services.news_annotation_evaluation import evaluate_entities
        a,b=reference(),reference('D002')
        report=evaluate_entities([a,b],[prediction(a,mentions=a['mentions'][:1]),prediction(b,status='timeout')])
        self.assertEqual(report['articles'],2)
        self.assertEqual(report['canonical']['tp'],1)
        self.assertEqual(report['canonical']['fn'],3)
        self.assertEqual(report['canonical']['fully_passed'],0)
        self.assertEqual(report['status_counts']['timeout'],1)

    def test_unknown_duplicate_sample_ids_and_forged_reference_fail_closed(self):
        from stable.services.news_annotation_evaluation import evaluate_entities, validate_reference
        a=reference()
        with self.assertRaises(ValueError): evaluate_entities([a],[prediction(a),prediction(a)])
        bad=prediction(a);bad['sample_id']='foreign'
        with self.assertRaises(ValueError): evaluate_entities([a],[bad])
        a['mentions'][0]['start']=True
        with self.assertRaises(ValueError): validate_reference(a)

    def test_overlap_invalidates_article_and_wrong_type_reports_fp_and_fn(self):
        from stable.services.news_annotation_evaluation import evaluate_entities
        a=reference();p=prediction(a);p['mentions'][0]['type']='person'
        r=evaluate_entities([a],[p]);self.assertEqual(r['canonical']['fp'],1);self.assertEqual(r['canonical']['fn'],1)
        self.assertIn('type_error',r['details'][0]['errors'])
        p=prediction(a);p['mentions'].append(p['mentions'][0])
        r=evaluate_entities([a],[p]);self.assertEqual(r['status_counts']['protocol_error'],1)
        self.assertEqual(r['canonical']['fn'],2)

    def test_canonical_and_acceptable_boundary_are_reported_separately(self):
        from stable.services.news_annotation_evaluation import evaluate_entities
        a=reference(text='Alpha Cup.');a['mentions']=a['mentions'][:1]
        a['mentions'][0]['acceptable_variants']=[{'block_id':'b0','start':0,'end':9,'text':'Alpha Cup','type':'horse'}]
        p=prediction(a,mentions=a['mentions'][0]['acceptable_variants'])
        r=evaluate_entities([a],[p]);self.assertEqual(r['canonical']['fully_passed'],0)
        self.assertEqual(r['acceptable']['fully_passed'],1)

    def test_missing_prediction_zero_entity_and_regression_comparison(self):
        from stable.services.news_annotation_evaluation import evaluate_entities, compare_entity_reports
        a=reference();a['mentions']=[]
        base=evaluate_entities([a],[prediction(a)])
        candidate=evaluate_entities([a],[])
        self.assertEqual(base['canonical']['fully_passed'],1)
        self.assertIsNone(base['canonical']['precision'])
        self.assertEqual(candidate['status_counts']['not_run'],1)
        self.assertEqual(compare_entity_reports(base,candidate)['regressed'],['D001'])

    def test_source_reference_and_variant_drift_cannot_be_compared(self):
        from stable.services.news_annotation_evaluation import evaluate_entities, compare_entity_reports
        a=reference();p=prediction(a)
        p['source_sha']='0'*64
        self.assertEqual(evaluate_entities([a],[p])['status_counts'],{'protocol_error':1})
        base=evaluate_entities([a],[prediction(a)])
        a['mentions'][0]['acceptable_variants']=[deepcopy(a['mentions'][0])]
        self.assertEqual(evaluate_entities([a],[prediction(reference())])['status_counts'],{'protocol_error':1})
        with self.assertRaises(ValueError):compare_entity_reports(base,evaluate_entities([a],[prediction(a)]))


class TranslationEvidenceTests(SimpleTestCase):
    def fixture(self):
        from stable.services.news_annotation_evaluation import sha
        ref=reference();ref['facts']=[{'id':'f1','category':'relationship','evidence':[{'block_id':'b0','start':0,'end':15,'text':'Alpha and Alpha'}], 'proposition':'两次提及Alpha','acceptable_translations':['Alpha与Alpha'], 'pitfalls':['不可改名']}]
        ref['fact_status']='ai_assisted';target={'title':'消息','summary':'两次提及Alpha','blocks':[{'id':'b0','text':'Alpha与Alpha。'}]}
        review={'sample_id':'D001','source_sha':ref['source_sha'],'reference_sha':sha(ref),'target_sha':sha(target),
            'reviewer':{'kind':'human','id':'fixture-reviewer','independent':True},
            'facts':[{'id':'f1','verdict':'supported','target_evidence':[{'block_id':'b0','start':0,'end':11,'text':'Alpha与Alpha'}],'reason':'两处名称保留'}],
            'additional_claims':{'verdict':'none','reason':'全文对照未发现新增事实'},
            'omissions':{'verdict':'none','reason':'全文无关键遗漏'},'fluency':{'verdict':'pass','reason':'可读'},'coverage':'full_article'}
        return ref,{'sample_id':'D001','status':'complete','target':target,'review':review}

    def test_evidence_bound_review_and_provisional_reference(self):
        from stable.services.news_annotation_evaluation import evaluate_translations
        ref,p=self.fixture();r=evaluate_translations([ref],[p]);self.assertEqual(r['review_passed'],1)
        self.assertFalse(r['reference_is_full_human_gold'])
        p['target']['title']='变更'
        self.assertEqual(evaluate_translations([ref],[p])['review_passed'],0)

    def test_summary_is_bound_and_available_as_review_evidence(self):
        from stable.services.news_annotation_evaluation import evaluate_translations, sha
        ref,p=self.fixture()
        p['review']['facts'][0]['target_evidence']=[{'block_id':'summary','start':0,'end':9,'text':'两次提及Alpha'}]
        self.assertEqual(evaluate_translations([ref],[p])['review_passed'],1)
        p['target']['summary']='虚构了获胜事实'
        self.assertEqual(evaluate_translations([ref],[p])['review_passed'],0)
        del p['target']['summary']
        p['review']['target_sha']=sha(p['target'])
        self.assertEqual(evaluate_translations([ref],[p])['review_passed'],0)

    def test_missing_false_self_review_and_wrong_quote_never_pass(self):
        from stable.services.news_annotation_evaluation import evaluate_translations
        ref,p=self.fixture()
        self.assertEqual(evaluate_translations([ref],[])['articles'],1)
        for change in ['self','quote','missing']:
            q=deepcopy(p)
            if change=='self':q['review']['reviewer']['independent']=False
            elif change=='quote':q['review']['facts'][0]['target_evidence'][0]['text']='fabricated'
            else:q['review']['facts']=[]
            self.assertEqual(evaluate_translations([ref],[q])['review_passed'],0)

    def test_fact_source_and_duplicate_ids_rejected(self):
        from stable.services.news_annotation_evaluation import evaluate_translations
        ref,p=self.fixture();ref['facts'][0]['evidence'][0]['end']=999
        with self.assertRaises(ValueError):evaluate_translations([ref],[p])


class PackageImportTests(SimpleTestCase):
    def test_checksum_binding_and_source_positions(self):
        from stable.services.news_annotation_evaluation import import_annotation_package
        import tempfile,json,hashlib
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);g=p/'开发集50篇';g.mkdir()
            source={'sample_id':'D001','title':'News','body':'Alpha','blocks':[{'id':'b0','text':'Alpha'}], 'source_language':'en','leakage_group_id':'event'}
            ann={'sample_id':'D001','split':'development','mentions':[{'mention_id':'D001-0001','block_id':'b0','start':0,'end':5,'text':'Alpha','type':'horse'}]}
            for path,obj in [(g/'原始输入.jsonl',source),(g/'按确认规则标注.jsonl',ann),(p/'human-decisions.json',{})]:path.write_text(json.dumps(obj)+'\n')
            manifest='\n'.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(p)) for f in sorted(p.rglob('*')) if f.is_file())
            (p/'SHA256SUMS.txt').write_text(manifest)
            digest=hashlib.sha256(manifest.encode()).hexdigest()
            refs,meta=import_annotation_package(p,digest)
            self.assertEqual(len(refs),1);self.assertTrue(refs[0]['exposed']);self.assertEqual(meta['mentions'],1)
            (g/'按确认规则标注.jsonl').write_text('{}')
            with self.assertRaisesRegex(ValueError,'checksum'):import_annotation_package(p,digest)


class VersionedPipelineTests(SimpleTestCase):
    @override_settings(NEWS_QUALITY_POLICY={'contract_version':'context-v3'})
    def test_full_and_repair_receive_same_glossary_and_publication_rejects_drift(self):
        from stable.services.news_pipeline import context_payload
        from stable.services.news_publication import validate_translation_glossary
        source=clean('Spring Festival')
        entities=validate_entities(source,{'coverage':'complete','entities':[occurrence(source,'Spring Festival','race_related')]},contract_version='racing-spans-v1')
        run=SimpleNamespace(stage='translate_full',clean_snapshot=source,entity_snapshot={'occurrences':entities},quality_snapshot={},repair_count=0)
        full=context_payload(run);validate_translation_glossary(run,full)
        run.repair_count=1;run.quality_snapshot={'repair_task':{'mode':'repair_blocks','required_block_ids':['b0'],'evidence':[]},'repair_base':{'raw':{'title':'新闻','summary':'摘要','blocks':[{'id':'b0','text':'bad'}]}}}
        repaired=context_payload(run)
        self.assertEqual(full['entity_glossary'],repaired['entity_glossary'])
        changed=deepcopy(full);changed['entity_glossary'][0]['replacement']='错误'
        with self.assertRaisesRegex(ContentBlocked,'translation_glossary_changed'):validate_translation_glossary(run,changed)

    def test_policy_version_and_new_rollback_revision_change_identity(self):
        from stable.services.news_pipeline import policy_sha
        values=[]
        for policy in [{'contract_version':'context-v2'},{'contract_version':'context-v3'}, {'contract_version':'context-v2','rollout_revision':'rollback-1'}]:
            with self.settings(NEWS_QUALITY_POLICY=policy):values.append(policy_sha())
        self.assertEqual(len(set(values)),3)


import json
from django.test import TransactionTestCase
from django.conf import settings
from stable.test_p01_news_workflow import WorkflowFixture
from stable.services.news_pipeline import start_revision
from stable.models import NewsPublicationReceipt

class V3Workflow(WorkflowFixture,TransactionTestCase):
    def setUp(self):
        super().setUp()
        policy=deepcopy(settings.NEWS_QUALITY_POLICY);policy.update(contract_version='context-v3',article_cap='5')
        for spec in policy['models'].values():
            spec.update(thinking='disabled',http_timeout_seconds=30)
            spec['deep']={**spec,'thinking':'enabled'}
        change=self.settings(NEWS_QUALITY_POLICY=policy);change.enable();self.addCleanup(change.disable)
        self.run=start_revision(self.article)

    def fake_response(self,attempt,payload):
        if attempt.stage=='entity_check':
            self.calls.append(attempt.stage)
            data={'units':[{'unit_id':u['unit_id'],'coverage':'complete','entities':([{'text':'Authority','type':'race_related','context':u['text']}] if 'Authority' in u['text'] else [])} for u in payload['units']]}
            response=SimpleNamespace(id='fixture-'+str(attempt.pk),choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data),tool_calls=None))],usage=SimpleNamespace(prompt_tokens=50,completion_tokens=20))
        else:
            response=super().fake_response(attempt,payload)
        response.choices[0].finish_reason='stop'
        return response

    def test_v3_full_publish(self):
        with self.settings(NEWS_QUALITY_MODE='enforce',NEWS_QUALITY_FEED_ENABLED=True):self.finish()
        self.assertEqual(self.run.state,'published',self.run.reason)
        self.assertEqual(self.run.entity_snapshot['contract_version'],'entity-units-v3')
        self.assertEqual(self.run.entity_snapshot['occurrences'][0]['type'],'race_related')
        translated=self.run.attempts.get(stage='translate_full')
        self.assertEqual(translated.usage['input']['entity_glossary'][0]['replacement'],'Authority')
        self.assertTrue(NewsPublicationReceipt.objects.filter(run=self.run).exists())
