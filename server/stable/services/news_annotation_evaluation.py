"""冻结标注及预测的离线评分；不调用模型、数据库或网络。"""
from collections import Counter
from copy import deepcopy
import hashlib
import json

from stable.services.news_entity_taxonomy import RACING_TYPES, entity_limit

SCHEMA = 'p01-annotated-news-v1'
SCORING_VERSION = 'p01-entity-score-v1'
STATUSES = {'complete', 'uncertain', 'timeout', 'truncated', 'protocol_error', 'not_run', 'capacity', 'review', 'provider_error'}
POSITION_KEYS = ('block_id', 'start', 'end', 'text', 'type')


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_map(source):
    if (type(source) is not dict or set(source) != {'title', 'blocks'} or type(source['title']) is not str
            or not source['title'] or type(source['blocks']) is not list or not 1 <= len(source['blocks']) <= 1000):
        raise ValueError('source_schema')
    texts = {'title':source['title']}
    for block in source['blocks']:
        if (type(block) is not dict or set(block) != {'id', 'text'} or type(block['id']) is not str
                or not block['id'] or block['id'] in texts or type(block['text']) is not str or not block['text']):
            raise ValueError('source_block_schema')
        texts[block['id']] = block['text']
    if sum(len(t) for t in texts.values()) > 1000000:
        raise ValueError('source_capacity')
    return texts


def _position(row, texts, *, allow_common=False):
    if type(row) is not dict or any(k not in row for k in POSITION_KEYS):
        raise ValueError('mention_schema')
    block, start, end, text, kind = (row[k] for k in POSITION_KEYS)
    types = RACING_TYPES if allow_common else RACING_TYPES - {'common_word'}
    if type(kind) is not str or kind not in types:
        raise ValueError('mention_type')
    if (type(block) is not str or block not in texts or type(start) is not int or type(end) is not int
            or type(text) is not str or not 0 <= start < end <= len(texts[block]) or texts[block][start:end] != text):
        raise ValueError('mention_span')
    return tuple(row[k] for k in POSITION_KEYS)


def _nonoverlap(rows):
    occupied = {}
    for block, start, end, *_ in rows:
        if any(start < b and end > a for a,b in occupied.get(block, [])):
            raise ValueError('mention_overlap_or_duplicate')
        occupied.setdefault(block, []).append((start,end))


def validate_reference(ref):
    if type(ref) is not dict or ref.get('schema') != SCHEMA:
        raise ValueError('reference_schema')
    for key in ('sample_id','language','original_split','leakage_group_id'):
        if type(ref.get(key)) is not str or not ref[key]: raise ValueError('reference_'+key)
    if ref.get('evaluation_role') not in {'development','regression','holdout'} or type(ref.get('exposed')) is not bool:
        raise ValueError('reference_role')
    if ref['evaluation_role']=='holdout' and (ref['exposed'] or ref.get('annotation_status')!='human_verified'):
        raise ValueError('holdout_not_independent')
    if ref.get('annotation_status') not in {'human_verified','ai_assisted_with_human_adjudications','ai_assisted'}:
        raise ValueError('reference_annotation_status')
    texts = source_map(ref.get('source'))
    if ref.get('source_sha') != sha(ref['source']): raise ValueError('source_sha_mismatch')
    mentions = ref.get('mentions')
    if type(mentions) is not list or len(mentions)>4096: raise ValueError('reference_mentions')
    keys = [_position(m,texts) for m in mentions]; _nonoverlap(keys)
    for m in mentions:
        variants=m.get('acceptable_variants',[])
        if type(variants) is not list or len(variants)>8: raise ValueError('reference_variants')
        for v in variants: _position(v,texts)
    groups=ref.get('name_groups',[])
    if type(groups) is not list: raise ValueError('reference_groups')
    seen=set();grouped=set()
    for group in groups:
        if (type(group) is not dict or type(group.get('id')) is not str or not group['id'] or group['id'] in seen
                or type(group.get('segments')) is not list or len(group['segments'])<2): raise ValueError('reference_group')
        seen.add(group['id'])
        segments=[_position(m,texts) for m in group['segments']]
        if len(set(segments))!=len(segments) or any(s not in keys or s in grouped for s in segments):
            raise ValueError('reference_group_segment')
        if len({s[-1] for s in segments}) != 1: raise ValueError('reference_group_type')
        grouped.update(segments)
    return ref


def _references(refs):
    if type(refs) is not list or not refs or len(refs)>10000: raise ValueError('reference_corpus')
    by_id={}; groups={}
    for ref in refs:
        validate_reference(ref)
        if ref['sample_id'] in by_id: raise ValueError('duplicate_reference_id')
        by_id[ref['sample_id']]=ref
        groups.setdefault(ref['leakage_group_id'],set()).add(ref['evaluation_role'])
    if any('holdout' in roles and len(roles)>1 for roles in groups.values()): raise ValueError('event_split_leakage')
    return by_id


def _matching(expected, actual, *, variants):
    # Augmenting paths give maximum cardinality, not greedy first-match assignment.
    edges=[]
    for m in expected:
        choices={tuple(m[k] for k in POSITION_KEYS)}
        if variants: choices.update(tuple(v[k] for k in POSITION_KEYS) for v in m.get('acceptable_variants',[]))
        edges.append([i for i,p in enumerate(actual) if p in choices])
    taken={}
    def augment(i, seen):
        for j in edges[i]:
            if j in seen: continue
            seen.add(j)
            if j not in taken or augment(taken[j],seen): taken[j]=i;return True
        return False
    for i in range(len(expected)): augment(i,set())
    return len(taken)


def _metrics(tp,fp,fn,passed):
    return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,
            'recall':tp/(tp+fn) if tp+fn else None,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
            'fully_passed':passed}


def evaluate_entities(references, predictions):
    refs=_references(references)
    if type(predictions) is not list: raise ValueError('predictions_schema')
    pred={}
    for p in predictions:
        if type(p) is not dict or type(p.get('sample_id')) is not str or p['sample_id'] not in refs:
            raise ValueError('unknown_prediction_id')
        if p['sample_id'] in pred: raise ValueError('duplicate_prediction_id')
        pred[p['sample_id']]=p
    totals={name:Counter() for name in ('canonical','acceptable')};details=[];statuses=Counter();contracts=set()
    for sid,ref in sorted(refs.items()):
        p=pred.get(sid); status='not_run' if p is None else p.get('status');actual=[];errors=[]
        version=p.get('contract_version') if p else None
        if p:
            try:
                if status not in STATUSES or p.get('phase') not in {'initial','repaired'}: raise ValueError('prediction_schema')
                if p.get('source_sha')!=ref['source_sha']: raise ValueError('prediction_source_sha')
                if p.get('reference_sha')!=sha(ref): raise ValueError('prediction_reference_sha')
                if version not in {'legacy','context-v2','context-v3'}: raise ValueError('prediction_contract')
                contracts.add(version)
                if status=='complete':
                    rows=p.get('mentions')
                    if type(rows) is not list: raise ValueError('prediction_mentions')
                    if len(rows)>entity_limit(version):
                        status='capacity';errors.append('entity_count_limit')
                    else:
                        allkeys=[_position(m,source_map(ref['source']),allow_common=True) for m in rows]
                        _nonoverlap(allkeys)
                        from stable.services.news_entity_taxonomy import entity_types
                        if any(k[-1] not in entity_types(version) for k in allkeys): raise ValueError('prediction_type_contract')
                        actual=[k for k in allkeys if k[-1]!='common_word']
            except (ValueError,TypeError,KeyError) as error:
                status='protocol_error';actual=[];errors.append(str(error))
        statuses[status]+=1
        expected=ref['mentions'];expected_keys={tuple(m[k] for k in POSITION_KEYS) for m in expected}
        if status=='complete':
            for got in actual:
                if got in expected_keys: continue
                if any(got[:4]==want[:4] for want in expected_keys): errors.append('type_error')
                elif any(got[0]==want[0] and got[1]<want[2] and got[2]>want[1] for want in expected_keys): errors.append('boundary_error')
                else: errors.append('false_positive')
        scores={}
        for name in totals:
            tp=_matching(expected,actual,variants=name=='acceptable');fp=len(actual)-tp;fn=len(expected)-tp
            passed=status=='complete' and fp==fn==0
            totals[name].update(tp=tp,fp=fp,fn=fn,fully_passed=int(passed))
            scores[name]={'tp':tp,'fp':fp,'fn':fn,'passed':passed}
        if scores['canonical']['fn']: errors.append('missing')
        details.append({'sample_id':sid,'status':status,'phase':p.get('phase') if p else None,
                        'contract_version':version,'errors':sorted(set(errors)),**scores,
                        'language':ref['language'],'original_split':ref['original_split'],
                        'reference_status':ref['annotation_status'],'semantic_name_groups':len(ref.get('name_groups',[]))})
    manifest=[{'sample_id':sid,'source_sha':ref['source_sha'],'reference_sha':sha(ref)} for sid,ref in sorted(refs.items())]
    metrics={name:_metrics(v['tp'],v['fp'],v['fn'],v['fully_passed']) for name,v in totals.items()}
    for metric in metrics.values():metric['article_pass_rate']=metric['fully_passed']/len(refs)
    return {'scoring_version':SCORING_VERSION,'manifest_sha':sha(manifest),'manifest':manifest,'articles':len(refs),
            'contracts':sorted(contracts),'status_counts':dict(statuses),**metrics,'details':details,
            'reference_is_full_human_gold':all(r['annotation_status']=='human_verified' for r in refs.values())}


def compare_entity_reports(baseline,candidate):
    if (baseline.get('scoring_version')!=SCORING_VERSION or candidate.get('scoring_version')!=SCORING_VERSION
            or baseline.get('manifest_sha')!=candidate.get('manifest_sha') or baseline.get('manifest')!=candidate.get('manifest')):
        raise ValueError('incomparable_evaluation_manifest')
    b={r['sample_id']:r['canonical']['passed'] for r in baseline['details']}
    c={r['sample_id']:r['canonical']['passed'] for r in candidate['details']}
    if set(b)!=set(c): raise ValueError('incomparable_evaluation_samples')
    return {'fixed':[sid for sid in sorted(b) if not b[sid] and c[sid]],
            'regressed':[sid for sid in sorted(b) if b[sid] and not c[sid]],
            'both_passed':[sid for sid in sorted(b) if b[sid] and c[sid]],
            'both_failed':[sid for sid in sorted(b) if not b[sid] and not c[sid]],
            'baseline_contracts':baseline['contracts'],'candidate_contracts':candidate['contracts']}


FACT_CATEGORIES = {'relationship', 'number_unit', 'date', 'placing', 'negation', 'plan', 'quotation', 'pedigree', 'source_conflict'}


def _evidence(rows, texts):
    if type(rows) is not list or not rows: raise ValueError('evidence_missing')
    for row in rows:
        _position({**row, 'type':'horse'}, texts)


def validate_fact_reference(ref):
    validate_reference(ref)
    if ref.get('fact_status') not in {'ai_assisted','human_verified'}: raise ValueError('fact_status')
    facts=ref.get('facts')
    if type(facts) is not list or not facts: raise ValueError('facts_missing')
    seen=set();texts=source_map(ref['source'])
    for f in facts:
        if (type(f) is not dict or type(f.get('id')) is not str or not f['id'] or f['id'] in seen
                or f.get('category') not in FACT_CATEGORIES): raise ValueError('fact_schema')
        seen.add(f['id']);_evidence(f.get('evidence'),texts)
        if type(f.get('proposition')) is not str or not f['proposition'].strip(): raise ValueError('fact_proposition')
        for k in ('acceptable_translations','pitfalls'):
            if type(f.get(k)) is not list or not f[k] or any(type(s) is not str or not s.strip() for s in f[k]):
                raise ValueError('fact_'+k)
    return ref


def translation_map(target):
    # Both raw translate_full output and restored snapshots contain a summary.
    if (type(target) is not dict or set(target) not in ({'title','summary','blocks'}, {'title','summary','blocks','body'})
            or type(target.get('summary')) is not str or not target['summary'].strip()):
        raise ValueError('target_schema')
    texts=source_map({'title':target['title'],'blocks':target['blocks']})
    if 'summary' in texts: raise ValueError('target_reserved_block')
    if 'body' in target and target['body']!='\n\n'.join(b['text'] for b in target['blocks']):
        raise ValueError('target_body_changed')
    texts['summary']=target['summary']
    return texts


def _review_translation(ref, target, review):
    texts=translation_map(target)
    if type(review) is not dict: raise ValueError('review_missing')
    for k,expected in [('sample_id',ref['sample_id']),('source_sha',ref['source_sha']),('reference_sha',sha(ref)),('target_sha',sha(target))]:
        if review.get(k)!=expected: raise ValueError('review_binding_'+k)
    who=review.get('reviewer')
    if (type(who) is not dict or who.get('kind') not in {'human','external_model'} or who.get('independent') is not True
            or type(who.get('id')) is not str or not who['id'].strip()): raise ValueError('review_provenance')
    if review.get('coverage')!='full_article': raise ValueError('review_coverage')
    judgments=review.get('facts');expected={f['id'] for f in ref['facts']}
    if (type(judgments) is not list or any(type(j) is not dict for j in judgments)
            or len(judgments)!=len(expected) or {j.get('id') for j in judgments}!=expected): raise ValueError('review_fact_coverage')
    supported=0
    for j in judgments:
        if j.get('verdict') not in {'supported','contradicted','missing','uncertain'}: raise ValueError('review_fact_verdict')
        if type(j.get('reason')) is not str or not j['reason'].strip(): raise ValueError('review_fact_reason')
        if j['verdict'] in {'supported','contradicted'}: _evidence(j.get('target_evidence'),texts)
        supported+=j['verdict']=='supported'
    for key,verdicts in [('additional_claims',{'none','present','uncertain'}),('omissions',{'none','present','uncertain'}),('fluency',{'pass','fail','uncertain'})]:
        row=review.get(key)
        if (type(row) is not dict or row.get('verdict') not in verdicts or type(row.get('reason')) is not str
                or not row['reason'].strip()): raise ValueError('review_'+key)
    faithful=(supported==len(expected) and review['additional_claims']['verdict']=='none'
              and review['omissions']['verdict']=='none')
    fluent=review['fluency']['verdict']=='pass'
    return {'facts_supported':supported,'faithful':faithful,'fluent':fluent,'review_passed':faithful and fluent,
            'reviewer_kind':who['kind']}


def evaluate_translations(references, predictions):
    refs=_references(references)
    for ref in refs.values(): validate_fact_reference(ref)
    if type(predictions) is not list: raise ValueError('predictions_schema')
    pred={}
    for p in predictions:
        if type(p) is not dict or p.get('sample_id') not in refs: raise ValueError('unknown_prediction_id')
        if p['sample_id'] in pred: raise ValueError('duplicate_prediction_id')
        pred[p['sample_id']]=p
    details=[]
    for sid,ref in sorted(refs.items()):
        p=pred.get(sid);row={'sample_id':sid,'status':'not_run' if p is None else p.get('status'),
                           'structure_passed':False,'review_passed':False,'faithful':False,'fluent':False,'facts_supported':0}
        if p is not None:
            try:
                if p.get('status') not in STATUSES: raise ValueError('prediction_status')
                if p['status']=='complete':
                    target=p.get('target');translation_map(target)
                    if [b['id'] for b in target['blocks']]!=[b['id'] for b in ref['source']['blocks']]: raise ValueError('target_block_coverage')
                    row['structure_passed']=True
                    row.update(_review_translation(ref,target,p.get('review')))
            except (ValueError,TypeError,KeyError) as error:row.update(status='review_invalid',error=str(error))
        details.append(row)
    return {'scoring_version':'p01-translation-review-v1','articles':len(refs),
            'manifest_sha':sha([{'sample_id':sid,'reference_sha':sha(r)} for sid,r in sorted(refs.items())]),
            'structure_passed':sum(r['structure_passed'] for r in details),'review_passed':sum(r['review_passed'] for r in details),
            'faithful':sum(r['faithful'] for r in details),'fluent':sum(r['fluent'] for r in details),
            'reference_is_full_human_gold':all(r['fact_status']=='human_verified' for r in refs.values()),
            'semantic_judgment_source':'external_review_not_program_verified','details':details}


def import_annotation_package(directory, checksum_manifest_sha):
    """Import a caller-pinned package. SHA is an integrity binding, not human-gold certification."""
    from pathlib import Path
    root=Path(directory).resolve();manifest=(root/'SHA256SUMS.txt').read_bytes()
    if hashlib.sha256(manifest).hexdigest()!=checksum_manifest_sha: raise ValueError('checksum_manifest_mismatch')
    files={}
    for line in manifest.decode().splitlines():
        checksum,name=line.split('  ',1);path=(root/name).resolve()
        if not path.is_relative_to(root) or name in files: raise ValueError('checksum_path')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=checksum: raise ValueError('checksum_file_mismatch:'+name)
        files[name]=data
    def read(name,lines=False):
        if name not in files: raise ValueError('checksum_file_unlisted:'+name)
        return [json.loads(line) for line in files[name].decode().splitlines() if line.strip()] if lines else json.loads(files[name])
    decisions=read('human-decisions.json');refs=[];seen_mentions=set()
    if type(decisions) is not dict: raise ValueError('human_decisions_schema')
    for name in sorted(files):
        if not name.endswith('/原始输入.jsonl'):continue
        folder=name.rsplit('/',1)[0];sources=read(name,True);annotations=read(folder+'/按确认规则标注.jsonl',True)
        by_id={a['sample_id']:a for a in annotations}
        if len(by_id)!=len(annotations) or len(sources)!=len(annotations):raise ValueError('package_sample_ids')
        used=set()
        for article in sources:
            sid=article['sample_id']
            if sid not in by_id or sid in used: raise ValueError('package_sample_ids')
            used.add(sid);ann=by_id[sid];source={'title':article['title'],'blocks':[{'id':b['id'],'text':b['text']} for b in article['blocks'] if b['id']!='title']}
            for key,value in [('title_sha256',article['title']),('body_sha256',article['body'])]:
                if key in ann and hashlib.sha256(value.encode()).hexdigest()!=ann[key]:raise ValueError('package_source_binding')
            mentions=deepcopy(ann['mentions']);groups={}
            for m in mentions:
                mid=m['mention_id']
                if mid in seen_mentions:raise ValueError('duplicate_mention_id')
                seen_mentions.add(mid)
                if m.get('review_status')=='human_adjudicated' and m.get('human_decision')!=decisions.get(mid):
                    raise ValueError('human_decision_binding')
                if m.get('name_segments'):
                    gid=m.get('entity_group_id')
                    if not gid:raise ValueError('name_group_id')
                    group={'id':gid,'segments':[{**s,'type':m['type']} for s in m['name_segments']]}
                    if gid in groups and groups[gid]!=group:raise ValueError('name_group_conflict')
                    groups[gid]=group
            ref={'schema':SCHEMA,'sample_id':sid,'source':source,'source_sha':sha(source),
                 'language':article.get('source_language',article.get('language')),'original_split':ann['split'],
                 'evaluation_role':'development' if ann['split']=='development' else 'regression','exposed':True,
                 'leakage_group_id':article.get('leakage_group_id') or sid,
                 'annotation_status':'ai_assisted_with_human_adjudications','mentions':mentions,'name_groups':list(groups.values()),
                 'provenance':{'checksum_manifest_sha':checksum_manifest_sha,'source_file':name,'annotation_file':folder+'/按确认规则标注.jsonl',
                               'human_decisions':{k:v for k,v in decisions.items() if k.startswith(sid+'-')}}}
            validate_reference(ref);refs.append(ref)
    # Known cross-split event links from the frozen package audit; retain all original split labels.
    parent={r['sample_id']:r['sample_id'] for r in refs}
    def find(x):
        while parent[x]!=x:x=parent[x]
        return x
    def union(a,b):parent[find(b)]=find(a)
    events={}
    for r in refs:
        if r['leakage_group_id'] in events:union(events[r['leakage_group_id']],r['sample_id'])
        else:events[r['leakage_group_id']]=r['sample_id']
    for group in [('D006','T004'),('D003','T005','T008'),('D004','R002'),('D007','T002')]:
        present=[sid for sid in group if sid in parent]
        for sid in present[1:]:union(present[0],sid)
    for r in refs:r['leakage_group_id']='event:'+find(r['sample_id'])
    _references(refs)
    return sorted(refs,key=lambda r:r['sample_id']),{'checksum_manifest_sha':checksum_manifest_sha,'articles':len(refs),
        'mentions':sum(len(r['mentions']) for r in refs),'human_decisions':len(decisions),
        'types':dict(Counter(m['type'] for r in refs for m in r['mentions'])), 'all_exposed':True,'full_human_gold':False}
