"""将已审 JSON DTO 的显式类型装配到真实 renderer；不查询或生成 expected。"""
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from django.template.loader import render_to_string
from django.template import engines
from django.test import override_settings
from stable.services.race_field_normalization import DisplayField

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/public_probe_template_v1'
PINNED = {
    'golden.json': '996bf69c2fb16c55edbc5f2db0cdff0ab338cfc48b57e8eeedfe7ed665f53cfa',
    'envelope.json': 'ccb6e34ba82ddd0ebcbf1e91d9ef575bca5a2c0727386edb64eea706e1a05588',
    'contract.json': '5fc516d81b17a82c95151c10ed76872b3d4518b91b22ed505efedd6ba4f9304c',
}


def fixture_bytes(name):
    raw = (FIXTURES / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PINNED[name]:
        raise AssertionError('fixed C020 fixture changed: ' + name)
    return raw


def approved_cases():
    # Original C020 bytes remain pinned; derived bytes are fixed by the execution manifest.
    fixture_bytes('golden.json')
    return json.loads((FIXTURES.parent / 'public_probe_template_v6/golden-derived.json').read_bytes())


def typed_context(value, key=None):
    if key == 'public_display':
        result = {}
        for name, data in value.items():
            data = deepcopy(data)
            if data['meters'] is not None:
                data['meters'] = Decimal(data['meters'])
            result[name] = DisplayField(**data)
        return result
    if isinstance(value, dict):
        return {k: typed_context(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [typed_context(v) for v in value]
    if value is not None and key in {'local_date', 'default_anchor_date', 'date'}:
        return date.fromisoformat(value)
    if value is not None and key == 'local_start_time':
        return time.fromisoformat(value)
    if value is not None and key in {'race_datetime', 'published_to_web_at', 'dynamic_updated_at', 'checked_at'}:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value


def render_case(case, projection=None):
    context = typed_context(deepcopy(case['template_context']))
    context.update(context.pop('shared'))
    if projection is not None:
        context['public_probe_projection'] = deepcopy(projection)
    name = 'race_detail' if case['page_type'] == 'detail' else 'race_calendar'
    with override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=case['mode'] == 'strict_display_v1'):
        return render_to_string('stable/public/' + name + '.html', context).encode('utf-8')


def render_approved_original(case):
    """真实 Django 渲染独立旧 source；与新模板无 projection 全字节比较。"""
    name = 'race_detail' if case['page_type'] == 'detail' else 'race_calendar'
    path = 'server/stable/templates/stable/public/' + name + '.html'
    envelope = json.loads(fixture_bytes('envelope.json'))
    program = next(item for item in envelope['template_programs'] if item['template'] == path)
    source = ''.join(token['source'] for token in program['tokens'])
    if hashlib.sha256(source.encode('utf-8')).hexdigest() != program['source']['sha256']:
        raise AssertionError('approved original program bytes changed')
    context = typed_context(deepcopy(case['template_context']))
    context.update(context.pop('shared'))
    with override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=case['mode'] == 'strict_display_v1'):
        return engines['django'].from_string(source).render(context).encode('utf-8')


def adapter_inputs(document, case):
    private = document['private_inputs'][case['case_id']]
    evidence = {}
    for table, refs in [('origins', 'origin_document_refs'),
                        ('permissions', 'permission_document_refs'),
                        ('f01_documents', 'f01_document_refs'),
                        ('display_mappings', 'display_mapping_refs')]:
        evidence[table] = {ref: deepcopy(document[table][ref]) for ref in private[refs]}
    return {
        'html': render_case(case, case['projection']),
        'context': deepcopy(case['response_context']),
        'private': deepcopy(document['private_inputs'][case['case_id']]),
        'expected_body': deepcopy(case['expected_body']),
        'expected': deepcopy(case['expected']),
        'anchor': deepcopy(case['anchor']),
        'now': '2026-10-04T00:02:02Z',
        'envelope_contract': (FIXTURES.parent / 'public_probe_template_v6/envelope.json').read_bytes(),
        'schema_contract': (FIXTURES.parent / 'public_probe_template_v6/contract.json').read_bytes(),
        'evidence_documents': json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':'), allow_nan=False).encode('utf-8'),
    }


# 精确 raw HTML 编辑：不使用会自动修补 DOM 的序列化器，不改无关字节。
from html.parser import HTMLParser
import re


class SourceNode:
    def __init__(self, tag, attrs, parent, start, opening_end):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.start, self.opening_end = start, opening_end
        self.closing_start, self.end = opening_end, opening_end
        self.children = []
    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()
    def has_class(self, value):
        return value in self.attrs.get('class', '').split()


class SourceDOM(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.source = html.decode('utf-8'); self.offsets = [0]
        for line in self.source.splitlines(keepends=True): self.offsets.append(self.offsets[-1]+len(line))
        self.root = SourceNode('#root', [], None, 0, 0); self.stack = [self.root]
        self.feed(self.source); self.close()
        if len(self.stack) != 1: raise AssertionError('source harness only accepts fixed well-formed base input')
    def raw_offset(self):
        line, column = self.getpos(); return self.offsets[line-1]+column
    def handle_starttag(self, tag, attrs):
        start=self.raw_offset(); node=SourceNode(tag,attrs,self.stack[-1],start,start+len(self.get_starttag_text()))
        self.stack[-1].children.append(node)
        if tag not in {'meta','link','input'}:self.stack.append(node)
    def handle_startendtag(self, tag, attrs):
        start=self.raw_offset();node=SourceNode(tag,attrs,self.stack[-1],start,start+len(self.get_starttag_text()));self.stack[-1].children.append(node)
    def handle_endtag(self, tag):
        if self.stack[-1].tag != tag:raise AssertionError(('harness nesting',tag,self.stack[-1].tag))
        node=self.stack.pop();node.closing_start=self.raw_offset();node.end=self.source.index('>',node.closing_start)+1
    def select(self, *, root=None, tag=None, cls=None, attr=None, value=None):
        root=root or self.root
        return [node for node in root.descendants() if (tag is None or node.tag==tag) and (cls is None or node.has_class(cls))
                and (attr is None or attr in node.attrs and (value is None or node.attrs[attr]==value))]
    def one(self, **selector):
        nodes=self.select(**selector)
        if len(nodes)!=1:raise AssertionError(('fixed selector count',selector,len(nodes)))
        return nodes[0]
    def replace(self, edits):
        ordered=sorted(edits,key=lambda edit:edit[0])
        if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):raise AssertionError('overlapping mutation edits')
        result=self.source
        for start,end,text in reversed(ordered):result=result[:start]+text+result[end:]
        return result.encode('utf-8')
    def inner_edit(self,node,text):return node.opening_end,node.closing_start,text
    def attribute_edit(self,node,name,value=None,*,remove=False):
        opening=self.source[node.start:node.opening_end]
        pattern=re.compile(r'\s'+re.escape(name)+r'="[^"]*"')
        match=pattern.search(opening)
        if remove:
            if match is None:raise AssertionError('attribute absent before removal')
            new=opening[:match.start()]+opening[match.end():]
        elif match:
            new=opening[:match.start()]+' '+name+'="'+value+'"'+opening[match.end():]
        else:new=opening[:-1]+' '+name+'="'+value+'">'
        return node.start,node.opening_end,new


def canonical_bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode('utf-8')


def marker_edit(inputs, mutate):
    dom=SourceDOM(inputs['html']);node=dom.one(tag='script',attr='data-o03-marker')
    marker=json.loads(dom.source[node.opening_end:node.closing_start]);mutate(marker)
    inputs['html']=dom.replace([dom.inner_edit(node,canonical_bytes(marker).decode())])


def rebind_tuple(inputs, tuple_mutation):
    private=inputs['private'];old_revision=next(iter(private['revision_token_index']));old=private['revision_token_index'][old_revision][0]
    changed=deepcopy(old);tuple_mutation(changed)
    digest=hashlib.sha256(canonical_bytes(changed)).hexdigest();revision='pv2:'+digest
    permission='pp2:'+hashlib.sha256(canonical_bytes({'tuple_sha256':digest,'permission_sha256':changed['permission_sha256']})).hexdigest()
    private['revision_token_index']={revision:[changed]};private['permission_token_index']={permission:[changed]}
    changes={}
    for token,row in private['row_token_index'].items():
        row=deepcopy(row);row['tuple_sha256']=digest
        changes[token]=(token[:4]+hashlib.sha256(canonical_bytes(row)).hexdigest(),row)
    private['row_token_index']={value[0]:value[1] for value in changes.values()}
    html=inputs['html'].decode()
    html=html.replace(old_revision,revision)
    for old_token,(new_token,unused) in changes.items():html=html.replace(old_token,new_token)
    inputs['html']=html.encode()
    marker_edit(inputs,lambda marker:marker.update(revision_ref=revision,permission_version=permission))


def negative_inputs(document, spec):
    """ID 仅路由固定测试操作；observer 不接 ID。匹配策略固定，不看结果调整。"""
    case=next(case for case in document['positive_and_missing_cases'] if case['case_id']==spec['base_case_id'])
    inputs=adapter_inputs(document,case);number=int(spec['case_id'][1:3]);dom=SourceDOM(inputs['html']);edits=[]
    table=dom.select(attr='id',value='results')
    rows=dom.select(root=table[0],tag='tr')[1:] if table else []
    def field(name,index=0):
        nodes=dom.select(root=rows[index],attr='data-o03-field',value=name)
        if len(nodes)!=1:raise AssertionError((name,index,len(nodes)))
        return nodes[0]
    if number==1:
        oldcase=next(c for c in document['positive_and_missing_cases'] if c['case_id']=='P-official-old-detail-strict_display_v1')
        old=SourceDOM(render_case(oldcase,oldcase['projection']));node=old.one(attr='id',value='results')
        edits=[(table[0].start,table[0].end,old.source[node.start:node.end])]
    elif number==2:
        edits=[dom.inner_edit(field('horse_name'),'错误'),(table[0].closing_start,table[0].closing_start,'<span hidden>正确</span>')]
    elif number==3:edits=[dom.inner_edit(field('horse_name'),'错误'),dom.attribute_edit(field('horse_name'),'data-probe-text','正确')]
    elif number in (4,35):edits=[dom.inner_edit(dom.one(cls='winner-name'),'示例甲' if number==4 else '错误冠军')]
    elif number==5:edits=[(rows[-1].start,rows[-1].end,'')]
    elif number==6:
        text=dom.source[rows[-1].start:rows[-1].end];text=text.replace(rows[-1].attrs['data-o03-row'],'pr2:'+'0'*64)
        edits=[(rows[-1].end,rows[-1].end,text)]
    elif number==7:edits=[(rows[-1].end,rows[-1].end,dom.source[rows[0].start:rows[0].end])]
    elif number==8:edits=[dom.attribute_edit(field('horse_name'),'data-o03-field',remove=True)]
    elif number==9:edits=[dom.attribute_edit(row.children[3],'data-o03-field','horse_name') for row in rows]  # 全部四行 td[4]。
    elif number==10:edits=[dom.attribute_edit(table[0],'data-o03-role',remove=True)]
    elif number==11:
        node=dom.one(cls='winner-name');edits=[(node.end,node.end,dom.source[node.start:node.end])]
    elif number in (12,13,15,16,63):
        key={12:'subject',13:'revision_ref',15:'surface_ref',16:'content_digest',63:'extra'}[number]
        value={12:'/races/2026/other-event/',13:'pv2:'+'0'*64,15:'detail.result-family',16:next(iter(document['origins'].values()))['raw_material_sha256'],63:True}[number]
        if number==16:value=document['origins'][case['origin_ref']]['raw_material_sha256']
        marker_edit(inputs,lambda marker:marker.update({key:value}));return inputs
    elif number==14:
        entry=next(iter(inputs['private']['revision_token_index'].values()));other=deepcopy(entry[0]);other['generation']='conflicting-generation';entry.append(other);return inputs
    elif number==17:return inputs
    elif number in (18,19):inputs['context']['status']=403 if number==18 else 404;inputs['html']=b'<!doctype html><html lang="zh-Hans"><head></head><body>generic denial</body></html>';return inputs
    elif number==20:
        nodes=dom.select(attr='data-o03-role')+dom.select(tag='script',attr='data-o03-marker');top=[node for node in nodes if not any(parent.start<=node.start and parent.end>=node.end and parent is not node for parent in nodes)]
        edits=[(node.start,node.end,'') for node in top]
    elif number==21:edits=[dom.inner_edit(field('horse_name'),'待核实')]
    elif number==22:
        token=rows[0].attrs['data-o03-row'];ref=inputs['private']['row_token_index'][token]['proof_ref'];inputs['private']['proof_documents']=[proof for proof in inputs['private']['proof_documents'] if proof['proof_ref']!=ref];return inputs
    elif number==23:edits=[dom.inner_edit(field('horse_name',2),'Café &amp;amp; 星')]
    elif number==24:edits=[dom.inner_edit(field('horse_number',1),'２')]
    elif number==25:
        tbody=dom.one(root=table[0],tag='tbody');edits=[(tbody.closing_start,tbody.end,'')]
    elif number==26:
        body=dom.one(tag='body');edits=[(body.closing_start,body.closing_start,'<script>alert(1)</script>')]
    elif number in (27,28):
        node=next(node for node in dom.select(tag='script') if 'data-o03-marker' not in node.attrs)
        if number==27:edits=[dom.inner_edit(node,dom.source[node.opening_end:node.closing_start].replace('axis.scrollLeft = anchor.offsetLeft - (axis.clientWidth - anchor.offsetWidth) / 2;','axis.scrollLeft = 0;'))]
        else:
            axis=dom.one(cls='date-axis');text=dom.source[node.start:node.end];edits=[(node.start,node.end,''),(axis.start,axis.start,text)]
    elif number==29:inputs['private']['css_sha256']='0'*64;return inputs
    elif number in (30,31):edits=[dom.attribute_edit(dom.one(cls='race-hero' if number==30 else 'race-page'),'style' if number==30 else 'aria-hidden','display:none' if number==30 else 'true')]
    elif number==32:
        crew=dom.one(cls='winner-crew');label=dom.select(root=crew,tag='span')[0];edits=[dom.inner_edit(label,'骑师额外')]
    elif number==33:
        node=dom.one(cls='winner-name');edits=[(node.end,node.end,'额外冠军')]
    elif number==34:
        node=dom.one(tag='a',attr='data-o03-role',value='detail.result.nav');footer=dom.one(tag='footer');edits=[(node.start,node.end,''),(footer.closing_start,footer.closing_start,dom.source[node.start:node.end])]
    elif number in (36,37):
        cards=dom.select(tag='a',cls='cal-card');node=dom.select(root=cards[0],attr='data-o03-field',value='winner')[0];edits=[dom.inner_edit(node,'错误冠军')]
        if number==37:
            other=dom.select(root=cards[1],tag='small')[0];edits.append(dom.inner_edit(other,'冠军 '+case['expected_body']['roles'][0]['fields']['winner']))
    elif number in (38,39,40,41):
        cards=dom.select(tag='a',cls='cal-card')
        if number==38:edits=[(cards[2].start,cards[2].end,'')]
        elif number==39:edits=[(cards[-1].end,cards[-1].end,dom.source[cards[-1].start:cards[-1].end])]
        elif number==40:edits=[(cards[1].start,cards[1].end,''),(cards[0].start,cards[0].start,dom.source[cards[1].start:cards[1].end])]
        else:edits=[dom.attribute_edit(cards[0],'href','/races/2026/other-event/')]
    elif number==42:inputs['context']['final_url']='https://synthetic.invalid/races/?tab=key';return inputs
    elif number in (43,68):
        token=rows[0].attrs['data-o03-row'];row=inputs['private']['row_token_index'].pop(token)
        row['generation' if number==43 else 'participant_ref']='fixture-generation:official-old' if number==43 else 'fixture:P-other-same-name'
        new='pr2:'+hashlib.sha256(canonical_bytes(row)).hexdigest();inputs['private']['row_token_index'][new]=row;inputs['html']=inputs['html'].replace(token.encode(),new.encode());return inputs
    elif number==44:inputs['now']='2026-10-05T00:02:02Z';inputs['context']['request_started_at']='2026-10-05T00:02:00Z';inputs['context']['response_completed_at']='2026-10-05T00:02:01Z';return inputs
    elif number==45:
        docs=json.loads(inputs['evidence_documents']);next(iter(docs['permissions'].values()))['permission_generation']=True;inputs['evidence_documents']=canonical_bytes(docs);return inputs
    elif number==46:
        mapping=document['display_mappings']['official-old:legacy'];rebind_tuple(inputs,lambda value:value.update(display_mapping_ref='official-old:legacy',display_mapping_sha256=hashlib.sha256(canonical_bytes(mapping)).hexdigest()));return inputs
    elif number==47:
        odds,pop=field('odds'),field('popularity');edits=[(odds.start,odds.end,dom.source[pop.start:pop.end]),(pop.start,pop.end,dom.source[odds.start:odds.end])]
    elif number==48:
        podium=dom.one(cls='podium-line');node=podium.children[0];text=dom.source[node.opening_end:node.closing_start].replace('（','').replace('）','');edits=[dom.inner_edit(node,text)]
    elif number==49:edits=[dom.inner_edit(dom.one(root=dom.one(cls='winner-crew'),attr='data-o03-field',value='popularity'),'2')]
    elif number==50:
        node=dom.one(cls='race-result-status');edits=[(node.start,node.end,'')]
    elif number==51:edits=[(0,0,'outside visible text')]
    elif number==52:edits=[(len(dom.source),len(dom.source),'outside visible text')]
    elif number==53:
        node=dom.select(tag='meta')[0];edits=[(node.start,node.end,'<meta><span>bad</span></meta>')]
    elif number==54:inputs['context']['limits']['nodes']=True;return inputs
    elif number in (55,56,57,58):inputs['context']['limits'][{55:'wire_bytes',56:'decoded_bytes',57:'depth',58:'nodes'}[number]]=1;return inputs
    elif number in (59,60,61):
        parent=dom.one(cls='agenda-races') if number==59 else dom.one(tag='body')
        text='<script type="application/json" data-o03-marker="result-family">{}</script>'*65 if number==59 else '<span data-o03-field="horse_name">x</span>'*4097 if number==60 else '<tr></tr>'*513
        edits=[(parent.closing_start,parent.closing_start,text)]
    elif number==64:inputs['context']['targets']=[];return inputs
    elif number==66:edits=[dom.inner_edit(field('position',len(rows)-1),'4')]
    elif number==69:inputs['context']['body_state']='truncated';return inputs
    elif number==70:inputs['context']['clock_error_ms']=None;return inputs
    elif number in (71,72):
        data=inputs['private']['template_context']
        if number==71:
            for key in ('jockey_name','display_jockey_name','trainer_name','finish_time','popularity'):data['winner'][key]=''
        else:data['results']=data['results'][:1];data['top_results']=data['top_results'][:1]
        inputs['private']['template_context_sha256']=hashlib.sha256(canonical_bytes(data)).hexdigest()
        changed=deepcopy(case);changed['template_context']=deepcopy(data);inputs['html']=render_case(changed,case['projection']);return inputs
    elif number==73:edits=[dom.inner_edit(field('odds',2),'5/2')]
    elif number==74:
        docs=json.loads(inputs['evidence_documents']);next(iter(docs['origins'].values()))['raw_material']['participants'][0]['source_horse_name']=None;inputs['evidence_documents']=canonical_bytes(docs);return inputs
    elif number==75:edits=[dom.inner_edit(field('odds',3),'13.0（十进制）')]
    else:raise AssertionError(('not a behavioral mutation',spec['case_id']))
    inputs['html']=dom.replace(edits);return inputs


def baseline_reason_inputs(original, operation):
    """有限补充构造；保持独立expected/evidence，不看observer输出选策略。"""
    inputs = deepcopy(original)
    dom = SourceDOM(inputs['html'])
    if operation == 'same-cardinality-duplicate-row':
        table = dom.one(attr='id', value='results')
        rows = dom.select(root=table, tag='tr')[1:]
        if len(rows) != 4: raise AssertionError('fixed four-row baseline required')
        inputs['html'] = dom.replace([(rows[-1].start, rows[-1].end,
                                       dom.source[rows[0].start:rows[0].end])])
    elif operation == 'linked-double-entity':
        table = dom.one(attr='id', value='results')
        rows = dom.select(root=table, tag='tr')[1:]
        if len(rows) != 4: raise AssertionError('fixed four-row baseline required')
        token = rows[2].attrs['data-o03-row']
        table_name = dom.one(root=rows[2], attr='data-o03-field', value='horse_name')
        podium = dom.one(cls='podium-line')
        podium_row = dom.one(root=podium, attr='data-o03-row', value=token)
        podium_name = dom.one(root=podium_row, attr='data-o03-field', value='horse_name')
        inputs['html'] = dom.replace([dom.inner_edit(table_name, 'Café &amp;amp; 星'),
                                       dom.inner_edit(podium_name, 'Café &amp;amp; 星')])
    elif operation == 'position-valid-unauthorized-script-type':
        scripts = [node for node in dom.select(tag='script') if 'data-o03-marker' not in node.attrs]
        if len(scripts) != 1 or scripts[0].attrs: raise AssertionError('one original attribute-free calendar script required')
        inputs['html'] = dom.replace([dom.attribute_edit(scripts[0], 'type', 'text/javascript')])
    elif operation == 'private-results-only-retained-html':
        data = inputs['private']['template_context']
        if len(data['results']) != 4 or len(data['top_results']) != 4:
            raise AssertionError('complete private context baseline required')
        data['results'] = data['results'][:1]
        inputs['private']['template_context_sha256'] = hashlib.sha256(canonical_bytes(data)).hexdigest()
    elif operation == 'context-targets-null':
        inputs['context']['targets'] = None
    else:
        raise AssertionError(('unknown supplementary operation', operation))
    return inputs
