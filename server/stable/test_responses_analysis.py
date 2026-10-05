"""纯 mock 合同；禁止 API/DB，所有正文/来源均为合成。"""
import ast
import copy
import importlib.util
from pathlib import Path
from dataclasses import replace
import hashlib
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from stable.services.content_contracts import build_input
from stable.services.responses_analysis import AnalysisInput, get_analysis_provider


def fixture(state='verified', kind='horse', canonical='horse:demo:1'):
    text = 'Horse A won.'
    h = hashlib.sha256(text.encode()).hexdigest()
    e = dict(evidence_id='e1', provider_key='demo', source_class='trusted_publisher',
             independence_key='demo', capability='identity', artifact_sha256=h,
             locator='/private/path?token=DO_NOT_SEND', observed_at='2026-10-05T00:00:00Z',
             source_time=dict(precision='unknown', published_at=None, last_absent_at=None, first_seen_at=None),
             contract_ref=dict(route_digest='0'*64, contract_digest='0'*64, proof_digest='0'*64,
                               valid_until='2027-01-01T00:00:00Z', revoked=False))
    entity = dict(kind=kind, canonical_id=canonical, source_refs=[], identity_state=state,
                  candidate_ids=['candidate-1'], evidence_refs=['e1'])
    loader = build_input(dict(entity=entity, materials=[], evidence=[e,dict(e,evidence_id='e2',artifact_sha256='1'*64)],
                            policy_ref='demo-policy', protection=dict(paused=False, fields=[], modules=[], reason='',
                            actor_ref=None, changed_at=None)), evaluated_at='2026-10-05T00:00:00Z', policy_ref='demo-policy',
                            generations=dict(owner=1,schedule=1,enrollment=1,source_set=1))
    return AnalysisInput(loader,text,h,dict(text_evidence_id='e1',input_content_sha256=loader.to_dict()['input_version']['content_sha256'],
        artifact_sha256=h,relation='identity',source_text=None,allowed_spans=[[0,12]]),
        [dict(candidate_id='candidate-1',entity_path='/snapshot/entity',expected_kind='horse',expected_state='verified',
              expected_canonical_id='horse:demo:1',mention_type='horse',mention_text='Horse A',mention_span=[0,7])], 'm01.v1')


def payload():
    return dict(schema_version='m01.analysis.v1',entities=[dict(mention_type='horse',name='Horse A',start=0,end=7,
        candidate_id='candidate-1',evidence_refs=['e1'])], facts=[dict(claim='Horse A won.',evidence_refs=['e1'])],
        evidence=[dict(evidence_id='e1',quote='Horse A',start=0,end=7)],gaps=[])


def response(p=None):
    return dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(p or payload()))])],
                model='mock-model',id='resp_mock',usage=dict(input_tokens=10,output_tokens=20,total_tokens=30))


def obj(v):
    if isinstance(v,dict):return SimpleNamespace(**{k:obj(x)for k,x in v.items()})
    if isinstance(v,list):return [obj(x)for x in v]
    return v


def config(**changes):
    d=dict(RESPONSES_ANALYSIS_ENABLED=True,RESPONSES_ANALYSIS_MODEL='mock-model',RESPONSES_ANALYSIS_BASE_URL='https://api.openai.com/v1',
           RESPONSES_ANALYSIS_TIMEOUT_SECONDS=90,RESPONSES_ANALYSIS_MAX_OUTPUT_TOKENS=2400,OPENAI_API_KEY='fake-key')
    d.update(changes);return SimpleNamespace(**d)


class ResponsesAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('socket.socket.connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def run_request(self, r=None, wire=None, cfg=None, exc=None):
        client=Mock();client.with_options.return_value=client
        if exc is not None:client.responses.create.side_effect=exc
        else:client.responses.create.return_value=response()if wire is None else wire
        factory=Mock(return_value=client)
        result=get_analysis_provider(cfg or config(),client=client,client_factory=factory,clock=lambda:1.0).analyze(r or fixture())
        return result,client,factory

    def test_disabled_does_not_read_key_or_construct_client(self):
        class Disabled:
            RESPONSES_ANALYSIS_ENABLED=False
            def __getattr__(self,name):raise AssertionError('disabled read '+name)
        result,client,factory=self.run_request(cfg=Disabled())
        self.assertEqual(result.status,'disabled');client.with_options.assert_not_called();client.responses.create.assert_not_called();factory.assert_not_called()

    def test_configuration_missing_zero_request(self):
        for field,value in [('RESPONSES_ANALYSIS_MODEL',''),('RESPONSES_ANALYSIS_BASE_URL',''),('RESPONSES_ANALYSIS_TIMEOUT_SECONDS',True)]:
            with self.subTest(field=field):
                result,c,_=self.run_request(cfg=config(**{field:value}));self.assertEqual(result.error['code'],'configuration_missing');c.responses.create.assert_not_called()

    def test_completed_object_and_dict_same_result_and_bounded_request(self):
        for wire in [response(),obj(response())]:
            with self.subTest(shape=type(wire)):
                result,c,_=self.run_request(wire=wire)
                self.assertEqual(result.status,'ok');self.assertEqual(result.payload['entities'][0]['entity_ref'],fixture().loader_input.to_dict()['snapshot']['entity'])
                args=c.responses.create.call_args.kwargs
                self.assertFalse(args['store']);self.assertFalse(args['stream']);self.assertEqual(args['truncation'],'disabled');c.with_options.assert_called_once_with(max_retries=0)
                self.assertEqual(args['text']['format']['type'],'json_schema');self.assertTrue(args['text']['format']['strict'])
                self.assertNotIn('DO_NOT_SEND',json.dumps(args));self.assertNotIn('protection',json.dumps(args));self.assertNotIn('tools',args)
                self.assertEqual(result.metadata['usage']['input_tokens'],10);self.assertEqual(c.responses.create.call_count,1)

    def test_input_binding_invalid_zero_request_and_key_read(self):
        cases=[];r=fixture()
        for key,value in [('text_evidence_id','e2'),('artifact_sha256','2'*64),('input_content_sha256','3'*64),('allowed_spans',[[0,13]]),('allowed_spans',[[False,7]]),('relation','guessed')]:
            cases.append(replace(r,text_binding={**r.text_binding,key:value}))
        cases += [replace(r,text='Other text'),replace(r,text_sha256='4'*64),fixture(state='ambiguous',canonical=None),fixture(state='revoked'),fixture(kind='race_event')]
        cases.append(replace(r,candidate_bindings=[{**r.candidate_bindings[0],'expected_canonical_id':'other'}]))
        class NoKey:
            def __init__(self):self.__dict__.update({k:v for k,v in vars(config()).items()if k!='OPENAI_API_KEY'})
            def __getattr__(self,n):raise AssertionError('invalid input read '+n)
        for case in cases:
            with self.subTest(binding=case.text_binding):
                result,c,f=self.run_request(r=case,cfg=NoKey());self.assertEqual(result.error['code'],'input_binding_invalid');c.responses.create.assert_not_called();c.with_options.assert_not_called();f.assert_not_called()

    def test_explicit_derived_lf_relation(self):
        r=fixture();source='Horse A won.\r\n';text=source.replace('\r\n','\n');h=hashlib.sha256(source.encode()).hexdigest()
        old=r.loader_input.to_dict();old['snapshot']['evidence'][0]['artifact_sha256']=h
        loader=build_input(old['snapshot'],evaluated_at=old['evaluated_at'],policy_ref=old['policy_ref'],generations=old['input_version']['generations'])
        r=replace(r,loader_input=loader,text=text,text_sha256=hashlib.sha256(text.encode()).hexdigest(),text_binding={**r.text_binding,
                  'artifact_sha256':h,'input_content_sha256':loader.to_dict()['input_version']['content_sha256'],'relation':'normalize_lf_v1','source_text':source,'allowed_spans':[[0,len(text)]]})
        result,_,_=self.run_request(r=r);self.assertEqual(result.status,'ok')

    def test_unbound_null_candidate_is_unresolved(self):
        r=replace(fixture(),candidate_bindings=[]);p=payload();p['entities'][0]['candidate_id']=None
        result,_,_=self.run_request(r=r,wire=response(p));self.assertEqual(result.payload['entities'][0]['entity_ref'],None);self.assertEqual(result.payload['entities'][0]['identity_state'],'unresolved')

    def test_invalid_output_reference_shape_and_spans(self):
        mutations=[lambda p:p['evidence'][0].update(evidence_id='e2'),lambda p:p['entities'][0].update(candidate_id='unbound'),
          lambda p:p['entities'][0].update(mention_type='race_event'),lambda p:p['evidence'][0].update(start=True),
          lambda p:p['evidence'][0].update(end=13),lambda p:p['evidence'][0].update(quote='Other'),
          lambda p:p['entities'][0].update(name='Other'),lambda p:p['facts'][0].update(evidence_refs=[]),
          lambda p:p['evidence'].append(copy.deepcopy(p['evidence'][0])),lambda p:p.update(extra=1),lambda p:p.pop('gaps'),
          lambda p:p.update(schema_version='unknown')]
        for mutate in mutations:
            p=payload();mutate(p)
            with self.subTest(mutation=mutate):
                result,c,_=self.run_request(wire=response(p));self.assertEqual(result.error['code'],'invalid_response');self.assertIsNone(result.payload);self.assertEqual(c.responses.create.call_count,1)

    def test_output_outside_allowed_span_rejected(self):
        r=fixture();r=replace(r,text_binding={**r.text_binding,'allowed_spans':[[0,6]]},candidate_bindings=[])
        p=payload();p['entities'][0]['candidate_id']=None
        result,_,_=self.run_request(r=r,wire=response(p));self.assertEqual(result.error['code'],'invalid_response')

    def test_refusal_in_later_content_wins(self):
        w=response();w['output'].append(dict(type='message',content=[dict(type='refusal',refusal='private refusal')]))
        result,c,_=self.run_request(wire=w);self.assertEqual(result.error['code'],'refused');self.assertIsNone(result.payload);self.assertNotIn('private refusal',str(result));self.assertEqual(c.responses.create.call_count,1)

    def test_incomplete_failed_and_unknown_do_not_parse(self):
        for status,expected in [('incomplete','incomplete'),('failed','provider_unavailable'),('queued','provider_unavailable')]:
            w=response();w['status']=status
            with self.subTest(status=status):
                result,c,_=self.run_request(wire=w);self.assertEqual(result.error['code'],expected);self.assertIsNone(result.payload);self.assertFalse(result.error['retryable']);self.assertEqual(c.responses.create.call_count,1)

    def test_duplicate_documents_and_bad_json(self):
        for text in ['{"schema_version":"a","schema_version":"b"}','{"x":NaN}','bad','[]']:
            w=response();w['output'][0]['content'][0]['text']=text
            result,_,_=self.run_request(wire=w);self.assertEqual(result.error['code'],'invalid_response')
        w=response();w['output'].append(copy.deepcopy(w['output'][0]));result,_,_=self.run_request(wire=w);self.assertEqual(result.error['code'],'invalid_response')

    def test_errors_single_call_safe_and_retry_bounds(self):
        for status,code,retry in [(429,'rate_limited',True),(503,'provider_unavailable',True),(401,'auth_error',False),(400,'unsupported_configuration',False),(500,'provider_unavailable',False)]:
            exc=RuntimeError('DO_NOT_LEAK');exc.response=SimpleNamespace(status_code=status,headers={'Retry-After':'99999','Authorization':'DO_NOT_LEAK'})
            with self.subTest(status=status):
                result,c,_=self.run_request(exc=exc);self.assertEqual(result.error['code'],code);self.assertEqual(result.error['retryable'],retry)
                self.assertNotIn('DO_NOT_LEAK',str(result));self.assertEqual(c.responses.create.call_count,1)
                if status==429:self.assertEqual(result.error['retry_after_seconds'],3600)
        result,c,_=self.run_request(exc=TimeoutError('DO_NOT_LEAK'));self.assertEqual(result.error['code'],'timeout');self.assertTrue(result.error['retryable']);self.assertEqual(c.responses.create.call_count,1)

    def test_missing_usage_is_null_and_version_is_bound(self):
        w=response();w.pop('usage');result,_,_=self.run_request(wire=w)
        self.assertIsNone(result.metadata['usage']);self.assertEqual(result.metadata['input_version'],fixture().loader_input.to_dict()['input_version']);self.assertEqual(result.metadata['prompt_version'],'m01.v1')

    def test_constructed_client_retry_zero_and_factory_failure_is_safe(self):
        c=Mock();c.with_options.return_value=c;c.responses.create.return_value=response()
        factory=Mock(return_value=c)
        result=get_analysis_provider(config(),client_factory=factory).analyze(fixture())
        self.assertEqual(result.status,'ok');self.assertEqual(factory.call_args.kwargs['max_retries'],0)
        self.assertEqual(factory.call_args.kwargs['api_key'],'fake-key');c.with_options.assert_called_once_with(max_retries=0)
        broken=Mock(side_effect=RuntimeError('DO_NOT_LEAK'))
        result=get_analysis_provider(config(),client_factory=broken).analyze(fixture())
        self.assertEqual(result.error['code'],'unsupported_configuration');self.assertNotIn('DO_NOT_LEAK',str(result))

    def test_input_and_output_resource_bounds(self):
        r=fixture()
        for case in [replace(r,text='x'*(512*1024+1)),replace(r,prompt_version='x'*129),
                     replace(r,text_binding={**r.text_binding,'allowed_spans':[[0,7],[6,12]]})]:
            result,c,_=self.run_request(r=case);self.assertEqual(result.error['code'],'input_binding_invalid');c.responses.create.assert_not_called()
        for raw in ['x'*(1024*1024+1),'['*65+'0'+']'*65]:
            w=response();w['output'][0]['content'][0]['text']=raw
            result,_,_=self.run_request(wire=w);self.assertEqual(result.error['code'],'invalid_response')
        p=payload();p['gaps']=[dict(code='missing',detail='unknown',evidence_refs=[])]*1001
        result,_,_=self.run_request(wire=response(p));self.assertEqual(result.error['code'],'invalid_response')

    def load_config_block(self, values):
        # 执行真实 env/env_bool 和完整旁路配置块，含其异常处理。
        path=Path(__file__).resolve().parents[1]/'app/settings.py'
        source=path.read_text();tree=ast.parse(source)
        helpers=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('env','env_bool')]
        block=source.split('# M01 分析旁路默认关闭；',1)[1].split('\n',1)[1].split('\nTRANSLATION_PROVIDER =',1)[0]
        nodes=helpers+ast.parse(block).body
        scope={'os':os}
        with patch.dict(os.environ,values,clear=True):
            exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope)
        return {k:v for k,v in scope.items() if k.startswith('RESPONSES_ANALYSIS_')}

    def test_config_block_defaults_off_and_empty_model(self):
        scope=self.load_config_block({})
        self.assertFalse(scope['RESPONSES_ANALYSIS_ENABLED']);self.assertEqual(scope['RESPONSES_ANALYSIS_MODEL'],'');self.assertEqual(scope['RESPONSES_ANALYSIS_BASE_URL'],'')
        self.assertEqual(scope['RESPONSES_ANALYSIS_TIMEOUT_SECONDS'],90)
        self.assertEqual(scope['RESPONSES_ANALYSIS_MAX_OUTPUT_TOKENS'],2400)
        valid=self.load_config_block({'RESPONSES_ANALYSIS_TIMEOUT_SECONDS':'30.5','RESPONSES_ANALYSIS_MAX_OUTPUT_TOKENS':'1200'})
        self.assertEqual(valid['RESPONSES_ANALYSIS_TIMEOUT_SECONDS'],30.5)
        self.assertEqual(valid['RESPONSES_ANALYSIS_MAX_OUTPUT_TOKENS'],1200)

    def check_invalid_env_config(self, enabled):
        class NoKey:
            def __init__(self,values):self.__dict__.update(values)
            def __getattr__(self,name):raise AssertionError('unexpected config/key access '+name)
        for field in ('RESPONSES_ANALYSIS_TIMEOUT_SECONDS','RESPONSES_ANALYSIS_MAX_OUTPUT_TOKENS'):
            for raw in ('','abc'):
                with self.subTest(field=field,raw=raw,enabled=enabled):
                    values={'RESPONSES_ANALYSIS_ENABLED':str(enabled).lower(),
                            'RESPONSES_ANALYSIS_MODEL':'mock-model',
                            'RESPONSES_ANALYSIS_BASE_URL':'https://api.openai.com/v1',field:raw}
                    cfg=NoKey(self.load_config_block(values));factory=Mock()
                    result=get_analysis_provider(cfg,client_factory=factory).analyze(fixture())
                    if enabled:self.assertEqual(result.error['code'],'configuration_missing')
                    else:self.assertEqual(result.status,'disabled')
                    self.assertIsNone(getattr(cfg,field));factory.assert_not_called()

    def test_invalid_numeric_env_disabled_safe_load_zero_key_and_client(self):
        self.check_invalid_env_config(False)

    def test_invalid_numeric_env_enabled_configuration_missing_zero_request(self):
        self.check_invalid_env_config(True)


@unittest.skipUnless(importlib.util.find_spec('django') and importlib.util.find_spec('openai'), 'host lacks existing Django/SDK; run in cached image')
class ExistingProviderCompatibilityTests(unittest.TestCase):
    def test_legacy_factory_selection_contracts_unchanged(self):
        import django
        django.setup()
        from django.test import override_settings
        from stable.services.translation import get_translation_provider, DummyTranslationProvider, OpenAICompatibleTranslationProvider
        from stable.services.rewriting import get_rewrite_provider, FallbackRewriteProvider, OpenAICompatibleRewriteProvider
        with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')):
            with override_settings(TRANSLATION_PROVIDER='dummy',REWRITE_PROVIDER='fallback',OPENAI_API_KEY='',RESPONSES_ANALYSIS_ENABLED=True):
                self.assertIsInstance(get_translation_provider(),DummyTranslationProvider)
                self.assertIsInstance(get_rewrite_provider(),FallbackRewriteProvider)
            with override_settings(TRANSLATION_PROVIDER='openai-compatible',REWRITE_PROVIDER='openai-compatible',OPENAI_API_KEY='fake-key',OPENAI_BASE_URL='https://example.com/v1',RESPONSES_ANALYSIS_ENABLED=False):
                self.assertIsInstance(get_translation_provider(),OpenAICompatibleTranslationProvider)
                self.assertIsInstance(get_rewrite_provider(),OpenAICompatibleRewriteProvider)


if __name__=='__main__':unittest.main()
