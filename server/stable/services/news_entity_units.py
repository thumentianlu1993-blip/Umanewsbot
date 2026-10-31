"""实体短单元、精确原文映射及一次局部修复的纯函数契约。"""
from copy import deepcopy
import re

from stable.services.news_content import ContentBlocked, block_map, bounded_json, validate_entities
from stable.services.news_pipeline import digest

VERSION = 'entity-units-v2'
ROW_KEYS = {'text', 'type', 'context'}
TYPES = {'horse', 'person', 'race', 'organization', 'place', 'common_word'}


def build_units(clean):
    result = []
    for block, text in block_map(clean).items():
        ends = [len(text)] if block == 'title' else [m.end() for m in re.finditer(r'[。！？!?](?:[」』”\"])?|\.(?:\s+)|\n+', text)]
        if not ends or ends[-1] != len(text): ends.append(len(text))
        start = 0
        for end in ends:
            if end - start < 640 and end != len(text): continue
            left, right = max(0, start - 160), min(len(text), end + 160)
            result.append({'unit_id': 'title' if block == 'title' else f'{block}:{start}',
                           'block_id': block, 'start': start, 'end': end,
                           'text': text[start:end], 'window_start': left, 'window': text[left:right]})
            start = end
    if len(result) > 512: raise ContentBlocked('entity_unit_limit')
    return result


def initial_payload(clean, language):
    return {'entity_contract': VERSION, 'mode': 'initial', 'clean_sha': clean['clean_sha'],
            'language': language, 'units': build_units(clean)}


def repair_payload(clean, language, state, attempt_id):
    all_units = build_units(clean)
    pending = {i for i, u in enumerate(all_units) if u['unit_id'] in state['pending']}
    neighbors = ({0} | {j for i in pending for j in (i - 1, i + 1)
                        if 0 <= j < len(all_units)}) - pending
    context = []
    for i in sorted(neighbors):
        unit = all_units[i]
        # 前邻取末段，后邻取首段；只读语境不扩大可抽取单元。
        offset = max(0, len(unit['text']) - 640) if i + 1 in pending else 0
        text = unit['text'][offset:offset + 640]
        context.append({'unit_id': unit['unit_id'], 'block_id': unit['block_id'],
                        'start': unit['start'] + offset, 'text': text})
    return {'entity_contract': VERSION, 'mode': 'repair', 'clean_sha': clean['clean_sha'],
            'language': language, 'base_attempt_id': attempt_id,
            'units': [u for i, u in enumerate(all_units) if i in pending],
            'context_units': context,
            'accepted': deepcopy(state['accepted']), 'issues': deepcopy(state['issues'])}


def _positions(text, quote):
    pos = 0
    while True:
        pos = text.find(quote, pos)
        if pos < 0: return
        yield pos
        pos += 1


def locate(unit, row):
    if type(row) is not dict or set(row) != ROW_KEYS:
        return None, {'code': 'extra_or_missing_field'}
    if any(type(row[k]) is not str or not row[k] for k in ROW_KEYS) or row['type'] not in TYPES:
        return None, {'code': 'invalid_entity_value'}
    window, quote, context = unit['window'], row['text'], row['context']
    core, neighbors = set(), set()
    for c in _positions(window, context):
        for q in _positions(context, quote):
            position = unit['window_start'] + c + q
            if unit['start'] <= position < unit['end']:
                core.add(position)
                if len(core) > 128:
                    raise ContentBlocked('entity_candidate_limit')
            elif len(neighbors) <= 128:
                neighbors.add(position)
    if not core and len(neighbors) > 128:
        raise ContentBlocked('entity_candidate_limit')
    candidates = sorted(core or neighbors)
    if len(candidates) != 1:
        return None, {'code': 'ambiguous_occurrence' if candidates else 'quote_not_found',
                      'candidates': [{'start': s, 'end': s + len(quote),
                         'context': window[max(0, s-unit['window_start']-40):s-unit['window_start']+len(quote)+40]}
                         for s in candidates]}
    start = candidates[0]
    return {**row, 'unit_id': unit['unit_id'], 'block_id': unit['block_id'],
            'start': start, 'end': start + len(quote)}, None


def _same(a, b):
    return all(a[k] == b[k] for k in ('block_id', 'start', 'end', 'text', 'type'))


def _overlaps(a, b):
    return a['block_id'] == b['block_id'] and a['start'] < b['end'] and a['end'] > b['start']


def _owner(all_units, row):
    return next(u['unit_id'] for u in all_units if u['block_id'] == row['block_id']
                and u['start'] <= row['start'] < u['end'])


def _issues_with_candidates(clean, all_units, issues, accepted):
    result = []
    for issue in issues:
        item = deepcopy(issue)
        item['issue_id'] = digest({'clean_sha': clean['clean_sha'], 'issue': issue})[:24]
        if issue.get('candidates'):
            raw = issue['row']
            block = next(u['block_id'] for u in all_units if u['unit_id'] == issue['unit_id'])
            for candidate in item['candidates']:
                candidate.update(block_id=block, text=raw['text'], type=raw['type'])
                candidate['unit_id'] = _owner(all_units, candidate)
                candidate['candidate_id'] = digest({'clean_sha': clean['clean_sha'],
                    **{k: candidate[k] for k in ('block_id', 'start', 'end', 'text')}})[:24]
                candidate['status'] = ('already_frozen' if any(_same(candidate, r) for r in accepted) else
                    'overlap_conflict' if any(_overlaps(candidate, r) for r in accepted) else 'available')
        if not any(r['issue_id'] == item['issue_id'] for r in result):
            result.append(item)
    return result


def evaluate(clean, payload, response, *, previous=None):
    bounded_json(response)
    expected = (initial_payload(clean, payload.get('language')) if previous is None else
                repair_payload(clean, payload.get('language'), previous, payload.get('base_attempt_id')))
    if payload != expected: raise ContentBlocked('entity_unit_input_changed')
    keys = {'units', 'decisions'} if previous is not None else {'units'}
    if type(response) is not dict or set(response) != keys or type(response['units']) is not list:
        raise ContentBlocked('entity_units_schema')
    all_units = build_units(clean)
    requested = {u['unit_id']: u for u in payload['units']}
    if len(response['units']) > len(requested): raise ContentBlocked('entity_units_schema')
    accepted = deepcopy(previous['accepted']) if previous else []
    issues, pending, seen, proposed = [], set(), set(), []
    total = len(accepted)

    def propose(uid, row, raw):
        row['unit_id'] = _owner(all_units, row)
        if row['unit_id'] not in requested and not any(_same(row, r) for r in accepted):
            pending.add(uid)
            issues.append({'unit_id': uid, 'row': deepcopy(raw), 'code': 'outside_requested_core',
                           'owner_unit_id': row['unit_id']})
        else:
            proposed.append((uid, row, raw))

    for receipt in response['units']:
        if (type(receipt) is not dict or set(receipt) != {'unit_id', 'coverage', 'entities'}
                or type(receipt['unit_id']) is not str or receipt['unit_id'] not in requested
                or receipt['unit_id'] in seen or type(receipt['entities']) is not list):
            raise ContentBlocked('entity_unit_receipt_invalid')
        uid = receipt['unit_id']; seen.add(uid)
        total += len(receipt['entities'])
        if total > 128: raise ContentBlocked('entity_count_limit')
        if receipt['coverage'] != 'complete':
            pending.add(uid); issues.append({'unit_id': uid, 'code': 'unit_uncertain'})
        for raw in receipt['entities']:
            row, error = locate(requested[uid], raw)
            if error:
                pending.add(uid); issues.append({'unit_id': uid, 'row': deepcopy(raw), **error})
            else:
                propose(uid, row, raw)

    if previous is not None:
        offered = {i['issue_id']: i for i in payload['issues'] if i.get('code') == 'ambiguous_occurrence'}
        decisions = response['decisions']; decided = set()
        if type(decisions) is not list or len(decisions) > len(offered):
            raise ContentBlocked('entity_decisions_schema')
        for decision in decisions:
            if (type(decision) is not dict or set(decision) != {'issue_id', 'picks'}
                    or type(decision['issue_id']) is not str or decision['issue_id'] not in offered
                    or decision['issue_id'] in decided or type(decision['picks']) is not list):
                raise ContentBlocked('entity_decision_invalid')
            issue = offered[decision['issue_id']]; decided.add(decision['issue_id'])
            candidates = {c['candidate_id']: c for c in issue['candidates']}; picked = set()
            total += len(decision['picks'])
            if total > 128: raise ContentBlocked('entity_count_limit')
            for pick in decision['picks']:
                if (type(pick) is not dict or set(pick) != {'candidate_id', 'type'}
                        or type(pick['candidate_id']) is not str or pick['candidate_id'] not in candidates
                        or pick['candidate_id'] in picked or type(pick['type']) is not str or pick['type'] not in TYPES):
                    raise ContentBlocked('entity_candidate_invalid')
                picked.add(pick['candidate_id']); candidate = candidates[pick['candidate_id']]
                row = {k: candidate[k] for k in ('block_id', 'start', 'end', 'text', 'context', 'unit_id')}
                row['type'] = pick['type']
                propose(issue['unit_id'], row, pick)
        for issue_id, issue in offered.items():
            if issue_id not in decided:
                pending.add(issue['unit_id'])
                issues.append({'unit_id': issue['unit_id'], 'code': 'candidate_decision_missing', 'for_issue_id': issue_id})

    # 完全相同提及幂等合并；同名不同位置/类型和重叠边界不能合并。
    frozen = list(accepted)
    for i, (uid, row, raw) in enumerate(proposed):
        if (any(_overlaps(row, r) and not _same(row, r) for r in frozen)
                or any(i != j and _overlaps(row, other) and not _same(row, other)
                       for j, (_, other, _) in enumerate(proposed))):
            pending.add(uid)
            issues.append({'unit_id': uid, 'row': deepcopy(raw), 'code': 'entity_overlap_or_type_conflict',
                           'owner_unit_id': row['unit_id']})
        elif not any(_same(row, r) for r in accepted):
            accepted.append(row)
    for uid in requested:
        if uid not in seen:
            pending.add(uid); issues.append({'unit_id': uid, 'code': 'unit_unprocessed'})
    enriched = _issues_with_candidates(clean, all_units, issues, accepted)
    # 已观察到的未决位置属于原始全文范围，将其实际owner显式纳入待修请求。
    # 未观察到问题的普通只读邻居仍不能新增实体。
    for issue in enriched:
        if issue['code'] == 'ambiguous_occurrence':
            pending.update(c['unit_id'] for c in issue['candidates'])
        if issue['code'] == 'entity_overlap_or_type_conflict':
            pending.add(issue['owner_unit_id'])
    return {'accepted': accepted, 'pending': [u['unit_id'] for u in all_units if u['unit_id'] in pending],
            'issues': enriched,
            'complete': not pending, 'unit_ids': [u['unit_id'] for u in all_units]}


def occurrences(clean, state):
    if not state['complete']: raise ContentBlocked('entity_units_incomplete')
    rows = validate_entities(clean, {'coverage': 'complete', 'entities': [
        {k: r[k] for k in ('block_id', 'start', 'end', 'text', 'type')} for r in state['accepted']]})
    refs = {(r['block_id'], r['start'], r['end']): r for r in state['accepted']}
    return [r | {'context': refs[(r['block_id'], r['start'], r['end'])]['context'],
                 'unit_id': refs[(r['block_id'], r['start'], r['end'])]['unit_id'],
                 'contract_version': VERSION} for r in rows]


def replay(run, attempt, validate_attempt):
    """重建首轮/一次修复证据；不信任snapshot中的accepted行。"""
    payload = attempt.usage['input']
    first_id = run.entity_snapshot.get('initial_attempt_id')
    language = run.source_snapshot['language']
    if payload.get('mode') == 'repair':
        if not first_id or first_id == attempt.pk or payload.get('base_attempt_id') != first_id:
            raise ContentBlocked('entity_repair_base_invalid')
        first = validate_attempt(run, first_id, 'entity_check')
        if first.seq >= attempt.seq or first.usage['input'] != initial_payload(run.clean_snapshot, language):
            raise ContentBlocked('entity_repair_base_invalid')
        state = evaluate(run.clean_snapshot, first.usage['input'], first.result)
        if state['complete'] or payload != repair_payload(run.clean_snapshot, language, state, first.pk):
            raise ContentBlocked('entity_repair_input_changed')
        return evaluate(run.clean_snapshot, payload, attempt.result, previous=state)
    if first_id and first_id != attempt.pk:
        raise ContentBlocked('entity_initial_binding_changed')
    if payload != initial_payload(run.clean_snapshot, language):
        raise ContentBlocked('entity_unit_input_changed')
    return evaluate(run.clean_snapshot, payload, attempt.result)
