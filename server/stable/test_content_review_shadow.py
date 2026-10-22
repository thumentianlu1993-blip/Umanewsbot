"""Synthetic actual-parser draft seam tests; no real capture or publish authority."""
import copy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch
from stable.adapters.base import SourceArticleStub
from stable.adapters.international import HorseRacingNationAdapter, TDNFranceKeywordAdapter
from stable.models import SourceMode
from stable.services import content_review_decisions as kernel
from stable.services import content_review_shadow as shadow
from stable.services.text import normalize_whitespace

HTML = '<div class="article-body"><p>Horse Aurora finished second at Kyoto.</p><p>Explore the members archive on our companion portal.</p><p>The rider confirmed the next race is on Saturday.</p></div>'
COPY = dict(input_bytes=131072, output_bytes=131072, field_bytes=32768, container_items=256, nodes=8192, depth=20)

def fixture(adapter=None):
    adapter = adapter or HorseRacingNationAdapter()
    url = 'https://fixture.invalid/b140'
    detail = adapter.parse_detail_html(HTML.replace('article-body','entry-content') if isinstance(adapter,TDNFranceKeywordAdapter) else HTML, url=url)
    stub = SourceArticleStub(adapter.source_site, SourceMode.LATEST, 'TEST_ONLY:B140:article', url,
                             'TEST_ONLY title', datetime(2026,10,14,tzinfo=timezone.utc))
    draft = adapter.normalize_source_payload(stub, detail)
    snapshot = {k: getattr(draft,k) for k in ['source_article_id','source_url','body_ja_raw','body_ja_normalized']}
    snapshot.update(source_site=str(draft.source_site), canonical_source_site=str(draft.canonical_source_site) if draft.canonical_source_site is not None else None,
        metadata={k: copy.deepcopy(draft.metadata[k]) for k in ['body_parse_status','body_selector','body_cleaning','source_url','discovered_source_site']})
    snapshot['metadata']['discovered_source_site'] = str(snapshot['metadata']['discovered_source_site'])
    context = dict(expected=dict(source_site=snapshot['source_site'],source_article_id=snapshot['source_article_id'],source_url=url,
        body_html_sha256=snapshot['metadata']['body_cleaning']['body_html_sha256']),capture_ref='TEST_ONLY:B140:capture:1',policy_ref='TEST_ONLY:B140:shadow-v1',
        protection=dict(state='unknown',ref=None,protected_ids=[]),template=dict(state='unknown',ref=None,version=None))
    profile = dict(id='TEST_ONLY:B140:profile',purpose='TEST_ONLY',source_site=snapshot['source_site'],policy_ref=context['policy_ref'],
        limits=dict(packet_bytes=32768,verdict_bytes=16384,result_bytes=32768,blocks=64,field_bytes=8192,reason_bytes=1024,quote_bytes=8192,depth=12))
    return draft,snapshot,context,profile

def packet(snapshot, context):
    trace=snapshot['metadata']['body_cleaning']
    return dict(schema_version=1,source=dict(site=snapshot['source_site'],article_ref=snapshot['source_article_id'],capture_ref=context['capture_ref']),
        capture_sha256=trace['body_html_sha256'],policy_ref=context['policy_ref'],body_parse_status=snapshot['metadata']['body_parse_status'],
        protection=context['protection'],template=context['template'],trace=trace)

def verdict(snapshot,context,profile,deletes=(1,)):
    p=packet(snapshot,context)
    return dict(schema_version=1,input_digest=kernel.input_digest(p,profile),policy_ref=context['policy_ref'],decisions=[
        dict(block_id=b['block_id'],action='delete' if i in deletes else 'keep',reason='TEST_ONLY explicit reason',
             evidence=dict(start=0,end=len(b['text']),quote=b['text'])) for i,b in enumerate(p['trace']['blocks']) if b['text'] and b['decision'] in ('kept','modified')])

class ContentReviewShadowTests(unittest.TestCase):
    def setUp(self):
        self.draft,self.s,self.c,self.p=fixture()
        self.trace=self.s['metadata']['body_cleaning'];self.blocks=[b for b in self.trace['blocks'] if b['text'] and b['decision'] in ('kept','modified')]
        self.assertEqual(len(self.blocks),3);self.assertEqual(len({b['block_id'] for b in self.blocks}),3)
        self.assertTrue(all(b['decision']=='kept' for b in self.blocks))
        self.assertEqual(self.trace['after_text'],self.draft.body_ja_raw)
        self.assertEqual(normalize_whitespace(self.draft.body_ja_raw),self.draft.body_ja_normalized)
        self.v=verdict(self.s,self.c,self.p)
        self.args=dict(caller_context=self.c,profile=self.p,copy_limits=copy.deepcopy(COPY),attempt='available',verdict=self.v)
    def call(self):
        return shadow.shadow_review_draft(self.s,**self.args)
    def test_actual_fixture_control(self):
        self.assertEqual(self.s['metadata']['body_parse_status'],'ok')
        self.assertEqual(self.trace['after_text'],normalize_whitespace('\n\n'.join(b['text'] for b in self.blocks)))
    def test_actual_draft_candidate_manual_and_diff(self):
        before=copy.deepcopy((self.draft,self.s,self.args))
        result=self.call();self.assertEqual(result['adapter_gaps'],[])
        self.assertIsInstance(result['review'],dict)
        r=result['review'];self.assertEqual(r['status'],'needs_manual_review')
        self.assertEqual(r['candidate_text'],normalize_whitespace('\n\n'.join(self.blocks[i]['text'] for i in (0,2))))
        self.assertEqual(r['diff'],[dict(block_id=self.blocks[1]['block_id'],before_text=self.blocks[1]['text'],after_text='',action='delete',
            reason='TEST_ONLY explicit reason',evidence=self.v['decisions'][1]['evidence'])])
        self.assertEqual(r['input_digest'],self.v['input_digest']);self.assertIs(r['qualified'],False);self.assertIs(r['publish_eligible'],False)
        self.assertTrue({'quality_policy_unresolved','protection_context_unknown','template_baseline_missing','test_only_profile'}<=set(r['quality_gaps']))
        self.assertEqual((self.draft,self.s,self.args),before)

    def adapter_blocked(self, code):
        result=self.call();self.assertEqual(result,dict(adapter_gaps=[code],review=None))
    def kernel_blocked(self, code=None):
        result=self.call();self.assertEqual(result['adapter_gaps'],[])
        r=result['review'];self.assertEqual(r['status'],'review_blocked');self.assertIsNone(r['candidate_text']);self.assertEqual(r['diff'],[])
        self.assertIs(r['qualified'],False);self.assertIs(r['publish_eligible'],False)
        if code: self.assertEqual(r['reason'],code)
    def test_source_identity_against_independent_expected(self):
        self.s['source_article_id']='TEST_ONLY:another'
        self.args['verdict']=verdict(self.s,self.c,self.p)
        self.adapter_blocked('source_binding_mismatch')
    def test_snapshot_exact_shape(self):
        original=copy.deepcopy(self.s)
        for key in list(original)+['extra']:
            with self.subTest(key=key):
                self.s=copy.deepcopy(original)
                if key=='extra': self.s[key]='trusted'
                else: del self.s[key]
                self.adapter_blocked('snapshot_shape_invalid')
        self.s=copy.deepcopy(original);self.s['metadata']['html']='extra';self.adapter_blocked('snapshot_shape_invalid')
        self.s=copy.deepcopy(original);self.s['metadata']['body_selector']='';self.adapter_blocked('snapshot_shape_invalid')
        self.s=copy.deepcopy(original);self.s['metadata']['body_parse_status']='selector_not_found';self.adapter_blocked('snapshot_shape_invalid')
    def test_discovered_not_canonical(self):
        draft,s,c,p=fixture(TDNFranceKeywordAdapter())
        self.assertEqual(s['source_site'],'tdn_france');self.assertEqual(s['canonical_source_site'],'tdn')
        self.s=s;self.args.update(caller_context=c,profile=p,verdict=verdict(s,c,p))
        first=self.call();self.assertEqual(first['review']['status'],'needs_manual_review')
        self.s['canonical_source_site']='TEST_ONLY:other-canonical';self.assertEqual(self.call(),first)
        self.s['metadata']['discovered_source_site']='tdn';self.adapter_blocked('source_binding_mismatch')
    def test_source_url_and_discovered_drift(self):
        orig=copy.deepcopy(self.s)
        for path in [('source_url',),('metadata','source_url'),('metadata','discovered_source_site')]:
            with self.subTest(path=path):
                self.s=copy.deepcopy(orig);target=self.s
                for k in path[:-1]: target=target[k]
                target[path[-1]]='TEST_ONLY:drift';self.adapter_blocked('source_binding_mismatch')
    def test_context_capture_missing_or_drift(self):
        original=copy.deepcopy(self.c)
        for key in list(original)+['extra']:
            with self.subTest(key=key):
                c=copy.deepcopy(original)
                if key=='extra': c[key]=True
                else: del c[key]
                self.args['caller_context']=c;self.adapter_blocked('context_shape_invalid')
        for key in ['capture_ref','policy_ref']:
            for value in ['',None]:
                self.args['caller_context']=copy.deepcopy(original);self.args['caller_context'][key]=value;self.adapter_blocked('context_shape_invalid')
        self.args['caller_context']=copy.deepcopy(original);self.args['caller_context']['expected']['body_html_sha256']='0'*64;self.adapter_blocked('capture_binding_mismatch')
    def test_body_and_trace_binding_no_reparse(self):
        original=copy.deepcopy(self.s)
        for path in [('body_ja_raw',),('body_ja_normalized',),('metadata','body_cleaning','after_text')]:
            with self.subTest(path=path):
                self.s=copy.deepcopy(original);target=self.s
                for k in path[:-1]: target=target[k]
                target[path[-1]]+=' altered';self.adapter_blocked('body_binding_mismatch')
        self.s=copy.deepcopy(original);del self.s['metadata']['body_cleaning'];self.adapter_blocked('snapshot_shape_invalid')
    def test_trace_not_filtered_or_rebuilt(self):
        self.trace['extra']='not allowed';self.kernel_blocked('schema_invalid')
        del self.trace['extra'];self.trace['blocks'].append(copy.deepcopy(self.blocks[0]));self.kernel_blocked()
    def test_protection_attempt_profile_and_stale(self):
        self.c['protection']=dict(state='known',ref='TEST_ONLY:annotation',protected_ids=[self.blocks[1]['block_id']])
        self.args['verdict']=verdict(self.s,self.c,self.p);self.kernel_blocked('protected_block_delete')
        self.c['protection']=dict(state='unknown',ref=None,protected_ids=[])
        for attempt in ['unavailable','refused','timeout','invalid']:
            self.args.update(attempt=attempt,verdict=None);self.kernel_blocked('model_'+attempt)
        self.args.update(attempt='other',verdict=None);self.kernel_blocked('attempt_invalid')
        self.args.update(attempt='available',verdict=self.v,profile=None);self.kernel_blocked('profile_missing')
        self.args['profile']=self.p;self.v['input_digest']='0'*64;self.kernel_blocked('input_digest_mismatch')
    def test_keep_all_repeat_and_no_fake_error_success(self):
        self.args['verdict']=verdict(self.s,self.c,self.p,deletes=())
        r=self.call();self.assertEqual(r['review']['candidate_text'],self.trace['after_text']);self.assertEqual(r,self.call())
        self.c['protection']=dict(state='known',ref='TEST_ONLY:annotation',protected_ids=[])
        self.args['verdict']=verdict(self.s,self.c,self.p,deletes=())
        r=self.call()['review'];self.assertEqual(r['status'],'candidate_valid');self.assertIs(r['qualified'],False);self.assertIs(r['publish_eligible'],False)
        for error in [RuntimeError,KeyboardInterrupt,SystemExit]:
            with patch.object(kernel,'review_candidate',side_effect=error('TEST_ONLY defect')):
                with self.assertRaises(error): self.call()

    def frame(self):
        return dict(snapshot=self.s,caller_context=self.args['caller_context'],profile=self.args['profile'],attempt=self.args['attempt'],verdict=self.args['verdict'])
    def test_copy_limits_explicit(self):
        self.args['copy_limits']=None;self.adapter_blocked('copy_limits_invalid')
        for key in COPY:
            for value in [0,-1,True,1.0,2**31]:
                with self.subTest(key=key,value=value):
                    self.args['copy_limits']=dict(COPY,**{key:value});self.adapter_blocked('copy_limits_invalid')
        self.args['copy_limits']=dict(COPY,depth=65);self.adapter_blocked('copy_limits_invalid')
    def test_input_wire_exact_boundary(self):
        self.v['decisions'][0]['reason']='TEST_ONLY “é”\n\t\\quoted"'
        n=len(json.dumps(self.frame(),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        self.args['copy_limits']['input_bytes']=n;self.assertEqual(self.call()['review']['status'],'needs_manual_review')
        self.args['copy_limits']['input_bytes']=n-1;self.adapter_blocked('input_byte_limit')
    def test_field_bytes_and_surrogate(self):
        self.c['capture_ref']='é'*100
        self.v=verdict(self.s,self.c,self.p);self.args['verdict']=self.v
        self.args['copy_limits']['field_bytes']=200;self.assertEqual(self.call()['adapter_gaps'],[])
        self.args['copy_limits']['field_bytes']=199;self.adapter_blocked('input_field_limit')
        self.args['copy_limits']=dict(COPY);self.c['capture_ref']='\ud800';self.adapter_blocked('input_type_invalid')
    def test_cycle_and_exact_builtin_hooks(self):
        calls=[]
        class Evil:
            def __str__(self): calls.append('str');raise AssertionError('hook')
            def __len__(self): calls.append('len');raise AssertionError('hook')
            def __iter__(self): calls.append('iter');raise AssertionError('hook')
            def __deepcopy__(self,memo): calls.append('copy');raise AssertionError('hook')
        class DictSubclass(dict): pass
        class ListSubclass(list): pass
        class StrSubclass(str): pass
        class IntSubclass(int): pass
        for obj in [Evil(),DictSubclass(),ListSubclass(),StrSubclass('x'),IntSubclass(1),(),set(),b'x',1.0,2**64]:
            self.s['canonical_source_site']=obj;self.adapter_blocked('input_type_invalid')
        self.assertEqual(calls,[])
        old=self.s;self.s=self.draft;self.adapter_blocked('input_type_invalid');self.s=old
        self.s['canonical_source_site']=None
        cycle=[];cycle.append(cycle);self.s['extra']=cycle;self.adapter_blocked('input_cycle')
    def test_container_budget_early_stop(self):
        class Evil:
            def __len__(self): raise AssertionError('tail hook')
        self.s['extra']=[0]*256+[Evil()];self.adapter_blocked('input_container_limit')
    def test_input_output_alias_isolation(self):
        before=copy.deepcopy((self.s,self.c,self.p,self.v,self.draft))
        first=self.call();second=self.call();self.assertEqual(first,second)
        self.assertEqual((self.s,self.c,self.p,self.v,self.draft),before)
        frozen=copy.deepcopy(first)
        self.trace['blocks'][1]['reasons'].append('changed');self.c['protection']['protected_ids'].append('changed');self.p['limits']['depth']=1;self.v['decisions'][1]['evidence']['quote']='changed'
        self.assertEqual(first,frozen)
        first['review']['diff'][0]['evidence']['quote']='output-change';first['review']['quality_gaps'].append('changed')
        self.assertEqual(second,frozen);self.assertEqual(self.v['decisions'][1]['evidence']['quote'],'changed')
    def test_output_budget_fixed_error_and_kernel_reference_isolated(self):
        result=self.call();n=len(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        self.args['copy_limits']['output_bytes']=n;self.assertEqual(self.call(),result)
        self.args['copy_limits']['output_bytes']=n-1;self.adapter_blocked('output_copy_limit')
        self.args['copy_limits']['output_bytes']=1;self.adapter_blocked('output_copy_limit')
        self.args['copy_limits']=dict(COPY)
        with patch.object(kernel,'review_candidate',return_value=result['review']):
            isolated=self.call();isolated['review']['quality_gaps'].append('output-mutation')
        self.assertNotIn('output-mutation',result['review']['quality_gaps'])
    def test_adapter_and_kernel_caps_independent(self):
        self.p['limits']['packet_bytes']=100;self.kernel_blocked('byte_size_limit')
        self.p['limits']['packet_bytes']=32768;self.args['copy_limits']['input_bytes']=1;self.adapter_blocked('input_byte_limit')

    def test_metaclass_equality_hook_never_called(self):
        calls=[]
        class Meta(type):
            def __eq__(cls, other): calls.append('type-equality');return False
        class Evil(metaclass=Meta): pass
        self.s['canonical_source_site']=Evil();self.adapter_blocked('input_type_invalid')
        self.assertEqual(calls,[])
    def test_node_depth_container_exact_and_shared_occurrences(self):
        tree={'x':[1,2]};limits=dict(COPY,nodes=5,depth=2,container_items=2)
        self.assertEqual(shadow._bounded_copy(tree,limits,100),tree)
        for key,value,code in [('nodes',4,'input_node_limit'),('depth',1,'input_depth_limit'),('container_items',1,'input_container_limit')]:
            with self.subTest(key=key):
                with self.assertRaisesRegex(shadow._Gap,'^'+code+'$'):
                    shadow._bounded_copy(tree,dict(limits,**{key:value}),100)
        shared={'x':[]};tree=[shared,shared]
        result=shadow._bounded_copy(tree,dict(COPY,nodes=7),100);self.assertIsNot(result[0],result[1]);self.assertIsNot(result[0]['x'],result[1]['x'])
        with self.assertRaisesRegex(shadow._Gap,'^input_node_limit$'): shadow._bounded_copy(tree,dict(COPY,nodes=6),100)
        for tree in [{},[]]:
            if type(tree) is dict: tree['x']=tree
            else: tree.append(tree)
            with self.assertRaisesRegex(shadow._Gap,'^input_cycle$'): shadow._bounded_copy(tree,COPY,100)
    def test_second_pass_rechecks_no_public_callback(self):
        original=shadow._walk;calls=[]
        def inject(value,limits,byte_limit,*,clone):
            result=original(value,limits,byte_limit,clone=clone);calls.append(clone)
            if len(calls)==1: self.s['canonical_source_site']=b'illegal second pass'
            return result
        with patch.object(shadow,'_walk',side_effect=inject): self.adapter_blocked('input_type_invalid')
        self.assertEqual(calls,[False])
    def test_output_field_node_depth_and_custom_type_limits(self):
        for payload in ['x'*32769, [[0]*40]*220, [0]*257, [[[[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]]]], object()]:
            with self.subTest(kind=type(payload)):
                with patch.object(kernel,'review_candidate',return_value={'TEST_ONLY_output_probe':payload}): self.adapter_blocked('output_copy_limit')
    def test_unicode_preserved_and_no_hidden_call_edges(self):
        self.c['capture_ref']='TEST_ONLY:e\u0301'
        self.args['verdict']=verdict(self.s,self.c,self.p)
        result=self.call();self.assertEqual(result['review']['input_digest'],self.args['verdict']['input_digest'])
        self.assertEqual(self.c['capture_ref'],'TEST_ONLY:e\u0301')
        with patch.object(HorseRacingNationAdapter,'parse_detail_html',side_effect=AssertionError('no hidden reparse')), patch.object(HorseRacingNationAdapter,'normalize_source_payload',side_effect=AssertionError('no hidden projection')):
            self.assertEqual(self.call(),result)

    def test_copy_limit_shape_and_non_string_keys(self):
        for limits in [{},dict(COPY,extra=1),dict(COPY,depth=None)]:
            self.args['copy_limits']=limits;self.adapter_blocked('copy_limits_invalid')
        self.args['copy_limits']=dict(COPY);self.s[1]='nonstringkey';self.adapter_blocked('input_type_invalid')
    def test_trace_order_not_repaired(self):
        self.trace['blocks'].reverse();self.kernel_blocked('trace_reconstruction_invalid')
    def test_input_copy_does_not_alias_kernel_input(self):
        before=copy.deepcopy((self.s,self.c,self.p,self.v))
        real=kernel.review_candidate
        def mutate(packet,verdict,*,profile,attempt):
            result=real(packet,verdict,profile=profile,attempt=attempt)
            packet['trace']['blocks'][0]['reasons'].append('TEST_ONLY mutated kernel argument')
            verdict['decisions'][0]['reason']='mutated';profile['limits']['depth']=1
            return result
        with patch.object(kernel,'review_candidate',side_effect=mutate):self.assertEqual(self.call()['review']['status'],'needs_manual_review')
        self.assertEqual((self.s,self.c,self.p,self.v),before)
