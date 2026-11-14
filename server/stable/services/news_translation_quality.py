"""文章内可核翻译约束及紧凑审校载荷，不建立跨文章身份。"""
from copy import deepcopy
import re
from stable.services.news_pipeline import digest

CATALOG_VERSION = 'racing-phrases-v1'
# 地域与普通赛马词，不包含人名、马名或具体赛事译名。
PHRASES = {
    'place': {'フランス': '法国', 'イタリア': '意大利', '日本': '日本', 'Hong Kong': '香港',
              'Sha Tin': '沙田', 'Happy Valley': '跑马地', 'France': '法国', 'Italy': '意大利', 'UAE': '阿联酋'},
    'race_related': {'重賞': '分级赛', 'Thoroughbred racing': '纯血马赛马', 'Oaklawn meet': 'Oaklawn赛季'},
    'racing_honor': {'重賞': '分级赛', 'フランスリーディング': '法国骑师榜', 'Hong Kong Champion Jockey': '香港冠军骑师'},
}


def phrase_translation(row):
    return PHRASES.get(row.get('type'), {}).get(row.get('text'))


def valid_phrase(row):
    return (row.get('provenance') == 'reviewed_phrase_catalog' and row.get('catalog_version') == CATALOG_VERSION
            and not row.get('term_id') and bool(phrase_translation(row)) and row.get('replacement') == phrase_translation(row))


def apply_phrases(rows):
    result = deepcopy(rows)
    for row in result:
        translated = phrase_translation(row)
        if translated and not row.get('term_id'):
            row.update(replacement=translated, provenance='reviewed_phrase_catalog', catalog_version=CATALOG_VERSION)
    return result


def name_form_hints(clean, entities):
    """仅返回原文候选线索；同姓有多个全名时不关联，不传播译名。"""
    people = [e for e in entities if e['type'] == 'person']
    full = {}
    for e in people:
        words = e['text'].split()
        if len(words) >= 2 and all(re.fullmatch(r"[A-Za-z][A-Za-z’'-]*", w) for w in words):
            full.setdefault(words[-1], set()).add(e['text'])
    hints = []
    for i, e in enumerate(people):
        names = full.get(e['text'], set())
        if len(names) == 1:
            name = next(iter(names))
            earlier = [p for p in people[:i] if p['text'] == name]
            if earlier:
                hints.append({'full': name, 'short': e['text'], 'full_block': earlier[-1]['block_id'],
                              'short_block': e['block_id'], 'status': 'source_candidate_only'})
    return hints


def translation_issues(clean, target, entities):
    texts = {'title': clean['title'], **{b['id']: b['text'] for b in clean['blocks']}}
    targets = {'title': target['title'], 'summary': target['summary'], **{b['id']: b['text'] for b in target['blocks']}}
    issues = []
    for row in entities:
        if row['type'] != 'person':
            continue
        original = texts[row['block_id']]
        if not re.match(r'氏(?!名)', original[row['end']:]):
            continue
        name = row['text']
        # 例外必须绑定该姓名，不能由同文其他人的 Mr. 放行。
        explicit = re.compile(r'\b(?:Mr|Mrs|Ms|Miss)\.?\s+' + re.escape(name) + r'(?![A-Za-z])|'
                              + re.escape(name) + r'(?:先生|女士|夫人|女史)')
        if any(explicit.search(t) for t in texts.values()):
            continue
        for block in {'summary', 'body' if target.get('manual') and row['block_id'] != 'title' else row['block_id']}:
            text = targets.get(block, '')
            if re.search(re.escape(row['replacement']) + r'\s*(?:先生|女士|夫人)', text):
                issues.append({'kind':'neutral_honorific', 'block_id':block, 'source_block':row['block_id'],
                               'source_quote':name+'氏', 'instruction':'氏为中性敬称，删除新增性别称谓，保留姓名。'})
    for hint in name_form_hints(clean, entities):
        if re.search(re.escape(hint['full']) + r'\s*(?:和|与|及|、)\s*' + re.escape(hint['short']) + r'.{0,8}各', target['summary']):
            issues.append({'kind':'name_form_double_count', 'block_id':'summary', 'source_hint':hint,
                           'instruction':'核对全名和简称是否同一人，摘要不得凭名称形式拆成两人各自获胜。'})
    return issues


AUDIT_PAYLOAD_VERSION = 'compact-audit-v1'
AUDIT_ENTITY_KEYS = ('block_id','start','end','text','type','token','replacement')


def expected_audit_payload(clean, target, entities, editorial):
    from stable.services.news_content import stable_source, ContentBlocked
    compact = deepcopy(target)
    body = '\n\n'.join(b['text'] for b in compact['blocks'])
    if compact.get('body') != body:
        raise ContentBlocked('audit_target_body_changed')
    compact.pop('body')
    return {'audit_payload_version':AUDIT_PAYLOAD_VERSION, 'target_sha':digest(target),
            'source':stable_source(clean), 'target':compact,
            'entities':[{key:e[key] for key in AUDIT_ENTITY_KEYS} for e in entities], 'editorial':deepcopy(editorial)}


def audit_target_from_payload(payload):
    from stable.services.news_content import ContentBlocked
    if 'audit_payload_version' not in payload:
        return deepcopy(payload['target'])
    if payload['audit_payload_version'] != AUDIT_PAYLOAD_VERSION:
        raise ContentBlocked('audit_payload_version')
    target = deepcopy(payload['target'])
    if 'body' in target or type(target.get('blocks')) is not list:
        raise ContentBlocked('audit_target_shape')
    try:
        target['body'] = '\n\n'.join(b['text'] for b in target['blocks'])
    except (KeyError, TypeError):
        raise ContentBlocked('audit_target_shape') from None
    if digest(target) != payload.get('target_sha'):
        raise ContentBlocked('audit_target_changed')
    return target


def validate_audit_payload(run, payload, target):
    from stable.services.news_content import ContentBlocked
    from stable.services.news_pipeline import context_contract_version
    if context_contract_version() == 'context-v3':
        expected = expected_audit_payload(run.clean_snapshot, target, run.entity_snapshot['occurrences'], run.editorial_snapshot)
        if payload != expected or audit_target_from_payload(payload) != target:
            raise ContentBlocked('audit_input_changed')
