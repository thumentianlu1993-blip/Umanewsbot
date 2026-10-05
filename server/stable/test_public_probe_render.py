"""固定C015 synthetic字节；标准unittest，禁止框架和网络。"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from stable.services.public_probe_render import parse_render

FIXTURE_SHA = '590751082dc941127ba053958aed24f2d265649726b2fc8eb5219dc469150218'


def fixture():
    raw = (Path(__file__).parent / 'fixtures/public_probe_render_v1/C015-result-golden.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
    return json.loads(raw)


def inputs(d, case):
    ref = case['profile_ref']; profile = copy.deepcopy(d['profiles'][ref]); w = d['c013_wires'][ref]
    for unused in ('golden_ref','wire_ref','marker_ref'): profile.pop(unused)
    private = {k: copy.deepcopy(d[k]) for k in ['private_token_index', 'private_row_token_index', 'origins', 'permissions', 'display_mappings', 'f01_documents', 'approved_styles', 'canonical_url_map']}
    private.update(candidate_sha=d['candidate_content_sha256'], profile=profile)
    patch = case['private_input_patch']; token = profile['private_token']; t = private['private_token_index'][token][0]
    for key in ['origin_ref', 'permission_ref', 'display_mapping_ref', 'approved_style_ref']:
        if key in patch:
            profile[key] = patch[key]
            if key in t:t[key] = patch[key]
    if 'origin_kind' in patch:profile['origin_kind'] = patch['origin_kind']
    if 'token_index_add_tuple' in patch:private['private_token_index'][token].append(copy.deepcopy(patch['token_index_add_tuple']))
    if 'token_audience_ref' in patch:t['audience_ref'] = patch['token_audience_ref']
    if 'row_proof_ref' in patch:
        for row in private['private_row_token_index'].values():row['proof_ref'] = patch['row_proof_ref']
    if 'origin_complete_under_fixture_rule' in patch:private['origins'][profile['origin_ref']]['complete_under_fixture_rule_only'] = patch['origin_complete_under_fixture_rule']
    context = dict(case['request_context'], scope_ref=w['expected']['scope_ref'], surface_ref=w['expected']['surface_ref'], capability=w['expected']['capability'], receipt_id='parsed:'+case['case_id'], request_started_at=w['receipt']['request_started_at'], response_completed_at=w['receipt']['response_completed_at'], clock_error_ms=0)
    return dict(html=case['html'].encode(),context=context,limits=None if patch.get('limits_bound') is False else copy.deepcopy(case['limits']),private=private,expected_body=copy.deepcopy(d['golden_bodies'][ref]),expected=copy.deepcopy(w['expected']),anchor=copy.deepcopy(w['anchor']),now=w['as_of'])


class RenderFixtures(unittest.TestCase):
    observed = {}
    def check_cases(self, predicate):
        d=fixture()
        for case in d['cases']:
            if not predicate(case):continue
            with self.subTest(case=case['case_id']):
                result=parse_render(**inputs(d,case)).to_dict(); e=case['expected_outcome']
                self.observed[case['case_id']] = result
                self.assertEqual((result['leaf_status'],result['reason'],result['c013_status']),(e['leaf_status'],e['reason'],e['c013_status']))
                if e['leaf_status']=='fixture_verified':
                    self.assertEqual(result['body'],d['golden_bodies'][case['profile_ref']])
                    self.assertEqual(result['receipt']['body_digest'],d['golden_body_sha256'][case['profile_ref']])
                    self.assertEqual(result['comparison']['sla'],'unverified')
                else:self.assertIsNone(result['receipt'])
    def test_positive_eight(self):self.check_cases(lambda c:c['case_id'].startswith('P-'))
    def test_resource_structure(self):self.check_cases(lambda c:c['case_id'].startswith(('N24','N25','N27','N28','N29','N30','N31','N32','N33','N34','N35','N38','N39','N41')))
    def test_private_binding(self):self.check_cases(lambda c:c['case_id'].startswith(('N12','N13','N14','N15','N17','N18','N19','N21','N26','N36','N37','N42','N43')))
    def test_visible_content(self):self.check_cases(lambda c:not c['case_id'].startswith(('P-','N24','N25','N27','N28','N29','N30','N31','N32','N33','N34','N35','N38','N39','N41','N12','N13','N14','N15','N17','N18','N19','N21','N26','N36','N37','N42','N43')))


class RenderBoundaries(unittest.TestCase):
    def base(self):
        d=fixture();return inputs(d,next(c for c in d['cases'] if c['case_id']=='P-correction-current-detail'))
    def test_input_types(self):
        from stable.services.content_contracts import ContractError
        mutations = [('status',True),('clock_error_ms',False),('requested_url',None),('body_state','future')]
        for key,value in mutations:
            with self.subTest(key=key):
                a=self.base();a['context'][key]=value
                with self.assertRaises(ContractError):parse_render(**a)
        for value in [True,0,-1,1.5,'32']:
            with self.subTest(limit=value):
                a=self.base();a['limits']['depth']=value
                with self.assertRaises(ContractError):parse_render(**a)
    def test_duplicate_attributes_and_invalid_utf8(self):
        a=self.base();a['html']=a['html'].replace(b'<main>',b'<main id="a" id="b">')
        self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_structure')
        a=self.base();a['html']=b'\xff';self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_encoding')
    def test_field_parent_and_role_hierarchy(self):
        a=self.base();a['html']=a['html'].replace(b'<td><span data-o03-field="horse_number">2</span></td>',b'<span data-o03-field="horse_number">2</span>')
        self.assertNotEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
        a=self.base();a['html']=a['html'].replace(b'<html><body>',b'<body><html>').replace(b'</body></html>',b'</html></body>')
        self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_structure')
    def test_private_typed_and_hash_binding(self):
        from stable.services.content_contracts import ContractError
        a=self.base();a['private']['profile']['declared_hero']=1
        with self.assertRaises(ContractError):parse_render(**a)
        a=self.base();a['private']['candidate_sha']='0'*64
        self.assertEqual(parse_render(**a).to_dict()['reason'],'token_binding')
        a=self.base();origin=next(iter(a['private']['origins'].values()));origin['raw_material']['participants'][0]['source_horse_name']='别名'
        # Alter the selected origin too, without re-signing the opaque tuple.
        ref=a['private']['profile']['origin_ref'];a['private']['origins'][ref]['raw_material']['participants'][0]['source_horse_name']='别名'
        self.assertEqual(parse_render(**a).to_dict()['reason'],'private_content_binding')
    def test_unknown_class_and_css(self):
        a=self.base();a['html']=a['html'].replace(b'class="winner-name"',b'class="not-approved-hidden"')
        self.assertEqual(parse_render(**a).to_dict()['reason'],'visibility_unbound')
    def test_missing_or_duplicate_row_index(self):
        a=self.base();token=next(r for r,v in a['private']['private_row_token_index'].items() if v['origin_ref']==a['private']['profile']['origin_ref'] and v['participant_ref'])
        a['private']['private_row_token_index'][token]=[a['private']['private_row_token_index'][token],{}]
        self.assertEqual(parse_render(**a).to_dict()['reason'],'row_identity_unbound')
    def test_resource_equal_boundary(self):
        a=self.base();a['limits'].update(wire_bytes=len(a['html']),decoded_bytes=len(a['html']),depth=9,nodes=187,markers=1,fields=49,rows=7)
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
    def test_marker_alone_cannot_supply_observed_body(self):
        a=self.base();a['html']=a['html'].replace('示例乙'.encode(),'另一匹'.encode())
        out=parse_render(**a).to_dict();self.assertNotEqual(out['leaf_status'],'fixture_verified');self.assertIsNone(out['receipt'])
    def test_duplicate_identical_tuple_and_private_immutable(self):
        a=self.base();t=a['private']['profile']['private_token'];a['private']['private_token_index'][t]*=2;before=copy.deepcopy(a)
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified');self.assertEqual(a,before)
    def test_request_redirect_and_permission_expired(self):
        a=self.base();a['context']['final_url']='https://elsewhere.invalid/races/2026/synthetic-final/'
        self.assertEqual(parse_render(**a).to_dict()['reason'],'subject_binding')
        a=self.base();a['now']='2026-10-06T00:00:00Z';self.assertEqual(parse_render(**a).to_dict()['reason'],'permission_unbound')
    def test_optional_hero_absence_has_null_from_dom(self):
        from stable.services import content_contracts as f01
        a=self.base();a['html']=a['html'].replace(b'<b><span data-o03-field="jockey_name">'+ '骑师乙'.encode()+b'</span></b>',b'',1)
        a['expected_body']['roles'][0]['fields']['jockey_name']=None
        digest=f01._sha(a['expected_body']);old=a['expected']['content_digest'];a['html']=a['html'].replace(old.encode(),digest.encode())
        a['expected']['content_digest']=digest;a['anchor']['expectation_sha']=f01._sha(a['expected'])
        out=parse_render(**a).to_dict();self.assertEqual(out['leaf_status'],'fixture_verified');self.assertIsNone(out['body']['roles'][0]['fields']['jockey_name'])


class RenderFurtherBoundaries(unittest.TestCase):
    base = RenderBoundaries.base
    def test_nested_field_cannot_hide_extra_visible_text(self):
        a=self.base();a['html']=a['html'].replace(b'<span data-o03-field="horse_number">2</span>',b'<span data-o03-field="horse_number">2</span>999',1)
        self.assertNotEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
    def test_nested_field_duplicate_not_success(self):
        a=self.base();a['html']=a['html'].replace(b'<span data-o03-field="horse_number">2</span>',b'<span data-o03-field="horse_number"><span data-o03-field="horse_number">2</span></span>',1)
        self.assertEqual(parse_render(**a).to_dict()['reason'],'duplicate_field')
    def test_opaque_row_attributes_not_nested(self):
        a=self.base();a['html']=a['html'].replace(b'<span data-o03-field="horse_number">2</span>',b'<span data-o03-row="fake"><span data-o03-field="horse_number">2</span></span>',1)
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'rejected')
    def test_field_outside_role_is_not_ignored(self):
        a=self.base();a['html']=a['html'].replace(b'</main>',b'<span data-o03-field="horse_name">FAKE</span></main>')
        self.assertNotEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
    def test_permission_bool_generation_not_accepted(self):
        a=self.base();ref=a['private']['profile']['permission_ref'];p=a['private']['permissions'][ref];p['permission_generation']=True
        # Rebind synthetic hashes independently, to expose semantic typed validation rather than an old hash.
        from stable.services import content_contracts as f01
        old=a['private']['profile']['private_token'];t=a['private']['private_token_index'].pop(old)[0]
        p['permission_version']='pp1:'+f01._sha({k:v for k,v in p.items() if k!='permission_version'});t['permission_sha256']=f01._sha(p)
        new='pv1:'+f01._sha(t);a['private']['private_token_index'][new]=[t];a['private']['profile']['private_token']=new
        a['html']=a['html'].replace(old.encode(),new.encode()).replace(a['expected']['permission_version'].encode(),p['permission_version'].encode())
        from stable.services.content_contracts import ContractError
        with self.assertRaises(ContractError):parse_render(**a)
    def test_hidden_ancestor_cannot_supply_optional_or_row(self):
        a=self.base();a['html']=a['html'].replace(b'class="race-hero"',b'class="race-hero" aria-hidden="true"',1)
        self.assertEqual(parse_render(**a).to_dict()['reason'],'missing_role')
    def test_unknown_state_and_clock_remain_unverified(self):
        a=self.base();a['context']['body_state']='unknown';self.assertEqual(parse_render(**a).to_dict()['reason'],'missing_evidence')
        a=self.base();a['context']['clock_error_ms']=None;out=parse_render(**a).to_dict();self.assertEqual(out['reason'],'comparison_unverified');self.assertIsNone(out['receipt'])
    def test_self_closing_metadata_script_rejected(self):
        a=self.base();a['html']=a['html'].replace(b'<main>',b'<main><script/>',1)
        self.assertEqual(parse_render(**a).to_dict()['reason'],'unexpected_script')


class RenderRoleBoundaries(unittest.TestCase):
    base = RenderBoundaries.base
    def resign_body(self, a, body):
        from stable.services import content_contracts as f01
        old=a['expected']['content_digest'];digest=f01._sha(body);a['expected_body']=body
        a['expected']['content_digest']=digest;a['anchor']['expectation_sha']=f01._sha(a['expected'])
        a['html']=a['html'].replace(old.encode(),digest.encode())
    def test_nav_misplaced_cannot_be_clone(self):
        a=self.base();a['html']=a['html'].replace(b'<nav class="race-subnav">',b'<div class="race-subnav">').replace(b'</nav>',b'</div>')
        self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_structure')
    def test_no_hero_roles_from_dom_and_private_declaration(self):
        a=self.base();start=a['html'].index(b'<section class="race-hero"');end=a['html'].index(b'</section>',start)+len(b'</section>')
        a['html']=a['html'][:start]+a['html'][end:];a['private']['profile'].update(declared_hero=False,declared_podium_rows=0)
        body=copy.deepcopy(a['expected_body']);body['roles']=body['roles'][2:];self.resign_body(a,body)
        out=parse_render(**a).to_dict();self.assertEqual(out['leaf_status'],'fixture_verified');self.assertEqual(len(out['body']['roles']),2)
    def test_stale_inside_hero_and_missing_stale(self):
        a=self.base();a['private']['profile']['declared_stale']=True
        stale=dict(role='detail.result.stale',fields=dict(text='数据可能已过期'));body=copy.deepcopy(a['expected_body']);body['roles'].insert(2,stale)
        value='<div data-o03-role="detail.result.stale"><span data-o03-field="text">数据可能已过期</span></div>'.encode()
        a['html']=a['html'].replace(b'</section><nav',value+b'</section><nav',1);self.resign_body(a,body)
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
        a['html']=a['html'].replace(value,b'');self.assertEqual(parse_render(**a).to_dict()['reason'],'missing_role')
    def test_podium_margin_missing_is_observed_null(self):
        a=self.base();a['html']=a['html'].replace('（<span data-o03-field="margin">1/2</span>）'.encode(),b'',1)
        body=copy.deepcopy(a['expected_body']);body['roles'][1]['rows'][0]['cells']['margin']=None;self.resign_body(a,body)
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
    def test_strict_profile_extra_key_and_expected_schema(self):
        from stable.services.content_contracts import ContractError
        a=self.base();a['private']['profile']['trust_everything']=True
        with self.assertRaises(ContractError):parse_render(**a)
        a=self.base();a['expected_body']['roles'][0]['fields']['horse_name']=False
        with self.assertRaises(ContractError):parse_render(**a)


class RenderVisibilityBoundaries(unittest.TestCase):
    base = RenderBoundaries.base
    def test_unknown_aria_state_is_not_visible_evidence(self):
        a=self.base();a['html']=a['html'].replace(b'class="winner-name"',b'class="winner-name" aria-hidden="maybe"')
        self.assertEqual(parse_render(**a).to_dict()['reason'],'visibility_unbound')
    def test_trimmed_aria_true_blocks_visible_field(self):
        a=self.base();a['html']=a['html'].replace(b'class="winner-name"',b'class="winner-name" aria-hidden=" true "')
        self.assertEqual(parse_render(**a).to_dict()['reason'],'missing_visible_field')
    def test_no_io_import_and_call_surface(self):
        import ast
        from stable.services import public_probe_render
        tree=ast.parse(Path(public_probe_render.__file__).read_text())
        names={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertFalse(names & {'open','eval','exec','__import__'})
        roots={n.module.split('.')[0] for n in tree.body if isinstance(n,ast.ImportFrom)}
        roots.update(n.names[0].name.split('.')[0] for n in tree.body if isinstance(n,ast.Import))
        self.assertFalse(roots & {'os','sys','pathlib','subprocess','socket','requests','django'})


class RenderPriorityBoundaries(unittest.TestCase):
    base = RenderBoundaries.base
    def test_duplicate_role_precedes_unbound_token(self):
        a=self.base();start=a['html'].index(b'<section class="race-hero"');end=a['html'].index(b'</section>',start)+len(b'</section>')
        a['html']=a['html'].replace(b'</main>',a['html'][start:end]+b'</main>')
        token=a['private']['profile']['private_token'];a['private']['private_token_index'].pop(token)
        self.assertEqual(parse_render(**a).to_dict()['reason'],'duplicate_role')
    def test_invalid_role_parent_precedes_unbound_token(self):
        a=self.base();a['html']=a['html'].replace(b'<nav class="race-subnav">',b'<div class="race-subnav">').replace(b'</nav>',b'</div>')
        token=a['private']['profile']['private_token'];a['private']['private_token_index'].pop(token)
        self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_structure')


class RenderSelectedTextRepairs(unittest.TestCase):
    base = RenderBoundaries.base
    def card(self):
        d=fixture();return inputs(d,next(c for c in d['cases'] if c['case_id']=='P-correction-current-card'))
    def check_edit(self, a, before, after, reason='unmodeled_visible_content'):
        self.assertEqual(a['html'].count(before),1);a['html']=a['html'].replace(before,after,1)
        out=parse_render(**a).to_dict();self.assertEqual(out['reason'],reason);self.assertIsNone(out['receipt'])
    def test_original_hero_extra_visible_text(self):
        self.check_edit(self.base(),b'<div class="winner-name">',b'<div class="winner-name">FAKE WINNER ')
    def test_original_nav_extra_visible_text(self):
        before=b'<span data-o03-field="text">'+'赛果'.encode();self.check_edit(self.base(),before,b'FAKE LINK '+before)
    def test_original_card_status_extra_visible_text(self):
        before=b'<span data-o03-field="status">';self.check_edit(self.card(),before,b'FAKE STATUS '+before)
    def test_original_nonwhite_root_text(self):
        a=self.base();a['html']+=b'FAKE ROOT TEXT';out=parse_render(**a).to_dict();self.assertEqual(out['reason'],'invalid_structure');self.assertIsNone(out['receipt'])
    def test_selected_container_suffix_and_crew_wrapper(self):
        for before,after in [(b'</div><div class="winner-crew">',b'wrong</div><div class="winner-crew">'),(b'<div class="winner-crew">',b'<div class="winner-crew">unmodeled'),(b'<span class="winner-ribbon">',b'<span class="winner-ribbon">unmodeled')]:
            with self.subTest(before=before):self.check_edit(self.base(),before,after)
    def test_card_outside_status_wrapper_and_prefix(self):
        before=b'<span class="cal-card-status">';self.check_edit(self.card(),before,b'noise'+before)
        before=b'<small>'+'冠军 '.encode();self.check_edit(self.card(),before,b'<small>'+'多余冠军 '.encode(),reason='related_role_mismatch')
    def test_table_and_podium_container_text(self):
        self.check_edit(self.base(),b'<tbody>',b'<tbody>unmodeled')
        self.check_edit(self.base(),b'<div class="podium-line" data-o03-role="detail.result.podium">',b'<div class="podium-line" data-o03-role="detail.result.podium">unmodeled')
    def test_stale_wrapper_text(self):
        a=self.base();a['private']['profile']['declared_stale']=True
        value='<div data-o03-role="detail.result.stale">EXTRA<span data-o03-field="text">数据可能已过期</span></div>'.encode()
        a['html']=a['html'].replace(b'</section><nav',value+b'</section><nav',1)
        self.assertEqual(parse_render(**a).to_dict()['reason'],'unmodeled_visible_content')
    def test_root_before_after_and_body_external_text(self):
        for edit in [lambda h:b'prefix'+h,lambda h:h+b'suffix',lambda h:h.replace(b'<html>',b'<html>outside-body',1),lambda h:h.replace(b'</body>',b'</body>outside-body',1),lambda h:h.replace(b'</body>',b'</body><div>outside-body</div>',1)]:
            with self.subTest(edit=edit):
                a=self.base();a['html']=edit(a['html']);self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_structure')
    def test_root_structure_before_binding(self):
        a=self.base();a['html']+=b'nonwhite';a['private']['private_token_index'].clear()
        self.assertEqual(parse_render(**a).to_dict()['reason'],'invalid_structure')
    def test_format_whitespace_comments_and_hidden_mirror_allowed(self):
        a=self.base();a['html']=b' \n<!--outside-->'+a['html']+b'\n<!--tail--> \t'
        a['html']=a['html'].replace(b'<html><body>',b'<html>\n\t<body>').replace(b'</body></html>',b'</body>\r\n</html>')
        a['html']=a['html'].replace(b'<div class="winner-name">',b'<div class="winner-name"> \n<span hidden>not visible</span>',1)
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
    def test_nonleaf_body_text_stays_outside_selected_scope(self):
        a=self.base();a['html']=a['html'].replace(b'</main>',b'</main><div>other page content</div>')
        self.assertEqual(parse_render(**a).to_dict()['leaf_status'],'fixture_verified')
