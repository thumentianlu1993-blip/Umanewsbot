"""法国可见来源的受限基础字段合同；不由地区或马场猜测单位。"""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal

GROUP_FIELDS = {
    'distance': ('distance_text',),
    'discipline': ('normalized_race_type',),
    'surface': ('surface', 'normalized_surface'),
    'layout': ('course_layout_text',),
    'going': ('going_text',),
    'prize': ('prize_amount', 'prize_currency'),
    'eligibility': ('eligibility_text', 'minimum_age', 'maximum_age', 'age_open_ended', 'sex_restriction', 'eligibility_constraints'),
}
ALLOWED_FIELDS = tuple('france_basic.'+key for key in GROUP_FIELDS)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def basic_sha(value):
    # 抓取时间不制造内容修订；原文、每字段证据和身份仍属于内容。
    return digest({k: v for k, v in value.items() if k != 'observed_at'})


def validate_basic(value, *, sha, provider, region, external_id='', event=None):
    from datetime import date, datetime
    from urllib.parse import urlsplit
    from .france_sources import geny_key, name_key, race_name_keys, event_names
    if provider not in {'geny', 'france_galop'} or region != 'france':
        raise ValueError('france_basic_source')
    if (not isinstance(value, dict) or set(value) != {'version','identity','fields','source_url','raw_sha256','observed_at','parser_version'}
        or value['version'] != 1 or basic_sha(value) != sha or not re.fullmatch('[a-f0-9]{64}', str(value['raw_sha256']))):
        raise ValueError('france_basic_contract')
    identity = value['identity']
    if (not isinstance(identity, dict) or not {'local_date','race_name','venue'} <= set(identity)
        or set(identity) - {'local_date','race_name','venue','external_race_id'}
        or any(not isinstance(v,str) or not v or len(v)>255 for v in identity.values())):
        raise ValueError('france_basic_identity')
    date.fromisoformat(identity['local_date'])
    observed = datetime.fromisoformat(value['observed_at'].replace('Z','+00:00'))
    if observed.tzinfo is None or not isinstance(value['parser_version'], str) or not value['parser_version']:
        raise ValueError('france_basic_observed_at')
    if provider == 'geny':
        key = geny_key(value['source_url'])
        if key[2] != identity['local_date'] or key[1] != identity.get('external_race_id') or external_id and key[1] != external_id:
            raise ValueError('france_basic_identity')
    else:
        url = urlsplit(value['source_url'])
        if url.scheme != 'https' or url.netloc != 'www.france-galop.com' or url.query or url.fragment or not re.fullmatch(r'/fr/course/detail/\d{4}/[PO]/[A-Za-z0-9=]+',url.path):
            raise ValueError('france_basic_source')
    if event is not None and (event.country_region != 'france' or event.local_date.isoformat()!=identity['local_date']
        or name_key(event.racecourse)!=name_key(identity['venue'])
        or not race_name_keys(identity['race_name']) & {k for n in event_names(event) for k in race_name_keys(n)}):
        raise ValueError('france_basic_identity')
    fields = value['fields']
    if not isinstance(fields,dict) or set(fields)-set(GROUP_FIELDS):
        raise ValueError('france_basic_fields')
    keys = {'distance':{'unit'}, 'discipline':{'detail'}, 'surface':set(), 'layout':set(), 'going':{'penetrometer'},
        'prize':{'currency'}, 'eligibility':set(GROUP_FIELDS['eligibility'][1:])}
    for key, field in fields.items():
        if (not isinstance(field,dict) or set(field)!={'value','raw'}|keys[key]
            or not isinstance(field['raw'],str) or not field['raw'] or len(field['raw'])>20000
            or not isinstance(field['value'],str) or not field['value']):
            raise ValueError('france_basic_field_schema')
        v=field['value']
        valid = {
            'distance': lambda: field['unit']=='metre' and bool(re.fullmatch(r'[1-9]\d{2,4} m',v)),
            'discipline': lambda: (v,field['detail']) in {('flat','flat'),('jumps','hurdle'),('jumps','steeplechase')},
            'surface': lambda: v in {'turf','synthetic'},
            'layout': lambda: v in {'Droite','Gauche','Ligne droite'},
            'going': lambda: len(v)<=128 and isinstance(field['penetrometer'],str) and bool(re.fullmatch(r'|\d+(?:\.\d+)?',field['penetrometer'])),
            'prize': lambda: field['currency']=='EUR' and bool(re.fullmatch(r'\d{1,12}\.\d{2}',v)) and Decimal(v)>0,
            'eligibility': lambda: len(v)<=20000 and field == _eligibility(v),
        }[key]()
        if not valid:
            raise ValueError('france_basic_field_value')
    return observed


def apply_basic_locked(*, event, basic, source, source_class, admitted_fields, audit, now):
    """调用者已验证写入claim/manifest并持赛事锁；每组分别仲裁并原子保留证据。"""
    from django.db import transaction
    from stable import models
    from .race_data_sync_policy import arbitrate_source_value, source_priority
    from .race_event_public_cache import invalidate_public_race_cache
    import copy
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('france_basic_transaction_required')
    observed = validate_basic(basic, sha=basic_sha(basic), provider=source.source_key, region='france',
        external_id=source.external_race_id, event=event)
    if observed > now:
        raise ValueError('france_basic_future_observation')
    refs = copy.deepcopy(event.source_refs or {})
    previous = refs.get('france_basic_v1', {})
    evidence = copy.deepcopy(previous.get('fields', {}))
    changed = set()
    decisions = {}
    for group, field in basic['fields'].items():
        if 'france_basic.'+group not in admitted_fields:
            decisions[group] = 'runtime_admission_closed'
            continue
        names = GROUP_FIELDS[group]
        if group == 'prize':
            values = dict(prize_amount=Decimal(field['value']), prize_currency=field['currency'])
        elif group == 'eligibility':
            values = {name:(field['value'] if name=='eligibility_text' else field[name]) for name in names}
        else:
            values = {name:field['value'] for name in names}
        if group=='distance' and re.sub(r'\s+', '', event.distance_text)==field['value'].replace(' ',''):
            values['distance_text']=event.distance_text
        authorities = {}
        rejection = ''
        for name, candidate_value in values.items():
            authority = event.field_authorities.select_for_update().filter(subject_type='event',subject_key=str(event.pk),field_name=name).first()
            authorities[name]=authority
            old = getattr(event,name)
            result = arbitrate_source_value(current_source_key=authority.source_key if authority else '',
                current_source_class=authority.source_class if authority else '',current_observed_at=authority.observed_at if authority else None,
                candidate_source_key=source.source_key,candidate_source_class=source_class,candidate_observed_at=observed,
                has_current_value=old not in (None,'',{},False,'unknown'),values_equal=old==candidate_value,
                manual_locked=bool((event.manual_lock_flags or {}).get(name) or (event.manual_lock_flags or {}).get('basic') or authority and authority.manual_lock))
            if authority and authority.source_key==source.source_key and authority.observed_at and observed<authority.observed_at:
                rejection='stale_same_source'
            elif not result.apply and result.reason_code!='idempotent_replay':
                rejection=result.reason_code
            if rejection:
                break
        if rejection:
            decisions[group]=rejection
            continue
        proof = {**field, **{k:basic[k] for k in ('source_url','raw_sha256','observed_at','parser_version')}}
        # 同值新证据/新水位仍需记录，保护后续restore；同一证据重放不写。
        if evidence.get(group)==proof and all(getattr(event,k)==v for k,v in values.items()):
            decisions[group]='replayed'
            continue
        for name, candidate_value in values.items():
            old = getattr(event,name)
            render=lambda v: str(v) if isinstance(v,Decimal) else v
            models.RaceEventFieldChange.objects.create(event=event,subject_type='event',subject_key=str(event.pk),field_name=name,
                old_value=render(old),new_value=render(candidate_value),applied=True,decision='applied',
                **{**audit,'source_key':source.source_key,'source_url':basic['source_url'],'source_class':source_class,
                   'authority_level':source_priority(source_class),'raw_sha256':basic['raw_sha256'],'operation_mode':'france_basic'})
            authority = authorities[name] or models.RaceEventFieldAuthority(event=event,subject_type='event',subject_key=str(event.pk),field_name=name)
            authority.source_key=source.source_key;authority.source_class=source_class;authority.source_url=basic['source_url']
            authority.external_id=source.external_race_id;authority.observed_at=observed
            authority.authority_level=source_priority(source_class);authority.value_sha256=digest(render(candidate_value))
            authority.save()
            setattr(event,name,candidate_value);changed.add(name)
        evidence[group]=proof
        if group=='distance':
            refs['field_units']={**refs.get('field_units',{}),'distance_text':'metre'}
        decisions[group]='applied'
    if changed:
        refs['france_basic_v1']={'version':1,'identity':basic['identity'],'fields':evidence}
        event.source_refs=refs
        event.save(update_fields=tuple(changed|{'source_refs','updated_at'}))
        transaction.on_commit(invalidate_public_race_cache)
    return decisions


def _eligibility(raw):
    lead = re.sub(r'\s+', ' ', raw.split('Poids')[0])
    age = re.search(r'de (\d{1,2})(?:\s*(?:et|à)\s*(\d{1,2}))? ans', lead)
    result = dict(value=raw, raw=raw, minimum_age=None, maximum_age=None,
                  age_open_ended=False, sex_restriction='unknown', eligibility_constraints={})
    if age:
        result['minimum_age'] = int(age[1])
        result['age_open_ended'] = bool(re.match(r'\s*(?:et (?:au-dessus|plus))', lead[age.end():]))
        result['maximum_age'] = None if result['age_open_ended'] else int(age[2] or age[1])
    if re.match(r'Pour (?:pouliches|juments)(?:\s|,)', lead, re.I) and not re.search(r'poulains|hongres|chevaux', lead, re.I):
        result['sex_restriction'] = 'female'
    if re.search(r'Autres Que Pur[- ]Sang', lead, re.I):
        result['eligibility_constraints']['horse_category'] = 'AQPS'
    return result


def parse_basic(doc, *, identity, raw_sha256='', observed_at='', parser_version='france-basic-v1'):
    """只读取本场头部，完整条件保留换行，不能吞入名单/历届冠军。"""
    from urllib.parse import urlsplit
    host = urlsplit(doc['url']).hostname
    raw = doc.get('text', '')
    fg = host == 'www.france-galop.com'
    if host not in {'www.france-galop.com', 'www.geny.com'}:
        raise ValueError('france_basic_source')
    if fg:
        section = raw.split('Legal notice', 1)[0]
    else:
        departure = re.search(r'Départ\s*\d{1,2}h\d{2}', raw)
        section = raw[departure.end():] if departure else ''
        section = re.split(r'Paris PMU|Paris Genybet|Arrivée/Rapports|Partants / Pronos|Rapports probables', section, maxsplit=1)[0]
    header, sep, conditions = section.partition('Pour ')
    eligibility = ('Pour ' + re.split(r'Terrain\s*:', conditions, maxsplit=1)[0]).strip() if sep else ''
    header_text = unicodedata.normalize('NFKC', header)
    fields = {}
    distance = re.search(r'(\d{1,3}(?:[ .]\d{3})+|\d{3,5})\s*(mètres|m)(?=\s|Gazon|Piste|PSF|Corde|Droite|Gauche|Pour|$)', header_text)
    if distance:
        fields['distance'] = dict(value=re.sub(r'[ .]', '', distance[1])+' m', unit='metre', raw=distance[0])
    discipline = re.search(r'PLAT|HAIES|STEEPLE(?:-CHASE)?', header_text, re.I)
    if discipline:
        code = 'flat' if discipline[0].upper() == 'PLAT' else 'jumps'
        fields['discipline'] = dict(value=code, detail={'PLAT':'flat','HAIES':'hurdle'}.get(discipline[0].upper(), 'steeplechase'), raw=discipline[0])
    surface = re.search(r'Gazon|Piste en sable fibré|PSF', header_text, re.I)
    if surface:
        fields['surface'] = dict(value='turf' if surface[0].lower() == 'gazon' else 'synthetic', raw=surface[0])
    layout = re.search(r'Ligne droite|Corde à\s+(?:DROITE|GAUCHE)|Droite|Gauche', header_text, re.I)
    if layout:
        label = re.sub(r'^Corde à\s+', '', layout[0], flags=re.I).lower()
        fields['layout'] = dict(value={'droite':'Droite','gauche':'Gauche','ligne droite':'Ligne droite'}[label], raw=layout[0])
    # 法国场况独立词表，边界不吞入NP或下注内容。
    going = re.search(r'Terrain\s*:\s*(Très souple|Bon souple|Très lourd|Souple|Lourd|Bon|Léger|Collant)(?:\s*\(Pén\s*:\s*([\d.,]+)\))?', section, re.I)
    if going:
        fields['going'] = dict(value=going[1], penetrometer=(going[2] or '').replace(',', '.'), raw=going[0])
    prize = re.search(r'(\d{1,3}(?:[ .]\d{3})+|\d+)(?:,(\d{2}))?\s*€', header_text)
    if prize:
        fields['prize'] = dict(value=re.sub(r'[ .]', '', prize[1])+'.'+(prize[2] or '00'), currency='EUR', raw=prize[0])
    if fg and 'prize' not in fields:
        # France Galop正式programme以EUR列示allocation；网页详情省略币种符号。
        # 仅接受头部独占一行、含名次分配的基础金额，不匹配带马主补贴的后续行。
        # 合同证据见docs/changes/france-public-field-gaps/design.md。
        allocation = re.search(r'(?m)^[ \t]*(\d{1,3}(?:[ .]\d{3})+|\d+) \(([\d., ]+)\)[ \t]*$', header_text)
        if allocation:
            total = Decimal(re.sub(r'[ .]', '', allocation[1]))
            parts = [Decimal(re.sub(r'[ .]', '', v)) for v in allocation[2].split(',')]
            if total > 0 and sum(parts) == total:
                fields['prize'] = dict(value=f'{total:.2f}', currency='EUR', raw=allocation[0].strip())
    if eligibility:
        fields['eligibility'] = _eligibility(eligibility)
    return dict(version=1, identity=identity, fields=fields, source_url=doc['url'],
                raw_sha256=raw_sha256 or digest(doc), observed_at=observed_at, parser_version=parser_version)


def display_fields(event, fields):
    """仅使用与当前值一致的法国证据；旧值变化后不得沿用旧翻译/测量。"""
    from .race_information_display import value
    from .race_field_normalization import display_field, parse_display_race_type
    refs = value(event, 'source_refs', {}) or {}
    basic = refs.get('france_basic_v1', {}) if isinstance(refs, dict) else {}
    evidence = basic.get('fields', {}) if isinstance(basic, dict) else {}
    if value(event, 'country_region') != 'france' or basic.get('version') != 1 or not isinstance(evidence, dict):
        return fields
    discipline = evidence.get('discipline', {})
    if discipline.get('value') == value(event, 'normalized_race_type'):
        fields['race_type'] = parse_display_race_type(discipline.get('detail', discipline['value']))
    layout = evidence.get('layout', {})
    if layout.get('value') == value(event, 'course_layout_text'):
        label = {'Droite':'右转', 'Gauche':'左转', 'Ligne droite':'直路'}.get(layout['value'])
        if label:
            fields['layout'] = display_field(layout['value'], label)
    going = evidence.get('going', {})
    if going.get('value') == value(event, 'going_text'):
        label = {'très souple':'很软', 'souple':'软', 'bon souple':'良好偏软', 'bon':'良好', 'léger':'轻快',
                 'collant':'黏重', 'lourd':'重', 'très lourd':'很重'}.get(str(going['value']).lower())
        if label:
            pen = going.get('penetrometer', '')
            suffix = '；Pén ' + pen if re.fullmatch(r'\d+(?:\.\d+)?', pen) else ''
            fields['going'] = display_field(going['value'], label+'（法国：'+going['value']+suffix+'）')
    eligibility = evidence.get('eligibility', {})
    if eligibility.get('value') == value(event, 'eligibility_text'):
        age = eligibility.get('minimum_age')
        maximum = eligibility.get('maximum_age')
        label = str(age)+'岁' if age else ''
        if age and eligibility.get('age_open_ended'):
            label += '及以上'
        elif age and maximum and maximum != age:
            label = str(age)+'—'+str(maximum)+'岁'
        if eligibility.get('sex_restriction') == 'female':
            label += '雌马'
        if eligibility.get('eligibility_constraints', {}).get('horse_category') == 'AQPS':
            label += ' · AQPS（非纯血马）' if label else 'AQPS（非纯血马）'
        if label:
            fields['eligibility'] = display_field(eligibility['value'], label+'；其他限制见完整条件')
    return fields
