"""v3文章候选捕获与纯解码；材料不是身份许可或数据库外部签名。"""
from dataclasses import fields
from datetime import datetime
from types import SimpleNamespace
import hashlib
import json
import re

from django.db import models
from django.db.models import Q
from django.db.models.functions import Cast, Lower, Substr
from django.utils import timezone

from .term_capture_budget import (CaptureBudget, TermCaptureRefusal, canonical,
    capture_dict, capture_list, capture_set)

SCHEMA = 'article-term-snapshot-v1'
LIMITS = {'term': 64, 'alias': 128, 'external_alias': 64, 'runner': 128, 'result': 128}
KINDS = tuple(LIMITS)


def _invalid():
    raise TermCaptureRefusal('read_terms_invalid')


def _limit():
    raise TermCaptureRefusal('read_terms_limit')


def _int(value, minimum=1, maximum=2**63-1):
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid()


def _str(value, chars=255, size=1024, *, nonempty=False):
    if type(value) is not str or (nonempty and not value):
        _invalid()
    if len(value) > chars:
        _limit()
    try:
        actual_size = len(value.encode())
    except UnicodeError:
        _invalid()
    if actual_size > size:
        _limit()


def _time(value):
    if type(value) is not str:
        _invalid()
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() is None:
            _invalid()
        return stamp
    except (ValueError, OverflowError):
        _invalid()


def _hash(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        _invalid()


def _builtin(value, depth=0, count=None):
    """在canonical编码分配前逐项核原生类型/node/总JSON字节。"""
    if count is None:
        count = [0, 0]
    count[0] += 1
    if count[0] > 8192 or depth > 12:
        _limit()
    def charge(size):
        if count[1]+size > 8192:
            _limit()
        count[1] += size
    if type(value) is dict:
        charge(2+max(0,len(value)-1))
        for key, child in value.items():
            if type(key) is not str:
                _invalid()
            _str(key,8192,24576)
            charge(len(canonical(key))+1)
            _builtin(child,depth+1,count)
    elif type(value) is list:
        if len(value) > 512:
            _limit()
        charge(2+max(0,len(value)-1))
        for child in value:
            _builtin(child,depth+1,count)
    elif type(value) in (str,int,bool,type(None)):
        if type(value) is str:
            _str(value,8192,24576)
        charge(len(canonical(value)))
    else:
        _invalid()


def source_view(article, expected):
    """只读已经live-fenced的字段；从__dict__取值，不触发deferred/FK查询。"""
    from . import translation_recovery as recovery
    names = ('title_ja', 'body_ja_normalized', 'body_ja_raw', 'source_language',
             'source_site', 'source_article_id')
    values = getattr(article, '__dict__', {})
    if any(name not in values for name in names):
        _invalid()
    view = SimpleNamespace(**{name: values[name] for name in names})
    if (recovery.translation_input_sha256(view) != expected['input_sha256']
            or view.source_site != expected['source_site']
            or view.source_article_id != expected['source_article_id']):
        _invalid()
    check_source(view)
    return view


def check_source(view):
    title, body = view.title_ja or '', view.body_ja_normalized or view.body_ja_raw or ''
    _str(title, 8192, 1024)
    _str(body, 8192, 8192)
    if len(title) + len(body) > 8192 or len(title.encode()) + len(body.encode()) > 9216:
        _limit()


class _Term(SimpleNamespace):
    def all_japanese_terms(self):
        return [self.source_ja, *self.aliases_ja]

    @property
    def has_translation(self):
        from stable.models import TermTranslationStatus
        return bool(self.target_zh.strip()) and self.translation_status == TermTranslationStatus.TRANSLATED


def _json_names(value):
    _str(value, 4096, 4096)
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        _invalid()
    if type(parsed) is not list:
        _invalid()
    if len(parsed) > 32:
        _limit()
    for item in parsed:
        _str(item)
    return parsed


def _project(query, kind, scalars, texts, json_fields=(), order=(), *, budget):
    annotations = {}
    for name, limit in texts.items():
        annotations['_cap_' + name] = Substr(name, 1, limit+1)
    for name in json_fields:
        annotations['_cap_' + name] = Substr(Cast(name, output_field=models.TextField()), 1, 4097)
    projected = query.annotate(**annotations).order_by(*order).values(*scalars, *annotations)
    if kind in ('runner', 'result'):
        projected = projected.distinct()
    rows = []
    for raw in projected[:LIMITS[kind]+1].iterator(chunk_size=16):
        if len(rows) == LIMITS[kind]:
            _limit()
        row = {key.removeprefix('_cap_'): value for key, value in raw.items()}
        for name, limit in texts.items():
            _str(row[name], limit, 4096 if name == 'notes' else 1024)
        for name in json_fields:
            _str(row[name], 4096, 4096)
        _int(row['id'])
        if type(row['updated_at']) is not datetime or row['updated_at'].utcoffset() is None:
            _invalid()
        size = len(_row_bytes(row))
        if budget.projection_bytes+size > 512*1024:
            _limit()
        budget.projection_bytes += size
        budget.charge('collection', {k: v.isoformat() if type(v) is datetime else v for k,v in row.items()})
        rows.append(row)
    return rows


def _row_bytes(row):
    return canonical({k: v.isoformat() if type(v) is datetime else v for k, v in row.items()})


def _record(kind, row, article_id):
    result = {'kind': kind, 'id': row['id'], 'updated_at': row['updated_at'].isoformat(),
              'row_sha256': hashlib.sha256(_row_bytes(row)).hexdigest()}
    if kind == 'alias':
        _int(row['term_id']); result['term_id'] = row['term_id']
    elif kind == 'external_alias':
        _str(row['external_horse_id'], 32, 128, nonempty=True)
        result['external_horse_id'] = row['external_horse_id']
    elif kind in ('runner', 'result'):
        from .terms import normalize_horse_entity_key
        _int(row['event_id'])
        result.update(event_id=row['event_id'], article_id=row['event__article_links__article_id'],
                      horse_name_key=normalize_horse_entity_key(row['horse_name']))
        if result['article_id'] != article_id:
            _invalid()
        _str(result['horse_name_key'], nonempty=True)
    return result


def _keys(text, language, budget):
    from . import terms
    raw = capture_set(budget=budget)
    variants = capture_set(budget=budget)
    for key in terms._iter_entity_candidate_keys(text, language):
        _str(key)
        if key not in raw:
            if len(raw) == 128:
                _limit()
            raw.add(key)
    for key in raw:
        normalized = terms.normalize_horse_entity_key(key)
        for variant in terms._term_query_key_variants(normalized):
            _str(variant)
            if variant not in variants:
                if len(variants) == 256:
                    _limit()
                variants.add(variant)
    return raw, variants


def capture(view, article_id, input_sha256, started_at):
    """最多5个N+1材料SELECT；调用者的Article SELECT为第6个。"""
    from stable.models import (SourceLanguage, TermEntry, TermAlias, ExternalHorseAlias,
        RaceEventRunner, RaceEventResult, ArticleRaceLinkStatus, TermType)
    from . import terms
    check_source(view)
    budget = CaptureBudget()
    budget.projection_bytes = 0
    title, body = terms.visible_source_parts(view)
    language = view.source_language or SourceLanguage.JAPANESE
    raw, variants = _keys('\n'.join(p for p in (title, body) if p), language, budget)
    material = {kind: [] for kind in KINDS}
    if raw:
        aliases = TermAlias.objects.filter(
            is_active=True,
            source_language=language
        ).annotate(
            candidate_key=Lower(
                'text'
            )
        )
        aliases = aliases.filter(
            candidate_key__in=variants
        ) if language == SourceLanguage.ENGLISH else aliases.filter(
            Q(
                text__in=raw
            ) | Q(
                candidate_key__in=variants
            )
        )
        material[
            'alias'
        ] = _project(
            aliases,
            'alias',
            [
                'id',
                'updated_at',
                'term_id',
                'source_language',
                'alias_type'
            ],
            {
                'text':255
            },
            order=(
                'term_id',
                'alias_type',
                'text',
                'pk'
            ),
            budget=budget
        )
        alias_ids = capture_set((row['term_id'] for row in material['alias']), budget)
        entry_filter = Q(candidate_key__in=variants) | Q(pk__in=alias_ids)
        if language != SourceLanguage.ENGLISH:
            entry_filter |= Q(source_ja__in=raw)
            if language in (SourceLanguage.CHINESE, SourceLanguage.CHINESE_TRADITIONAL):
                entry_filter |= Q(target_zh__in=raw)
        entries = TermEntry.objects.filter(
            is_active=True
        ).annotate(
            candidate_key=Lower(
                'source_ja'
            )
        ).filter(
            entry_filter
        )
        material['term'] = _project(entries, 'term', ['id','updated_at','is_active','priority'],
            {
                name: (
                    4096 if name == 'notes' else 255
                ) for name in (
                    'term_type',
                    'source_language',
                    'source_ja',
                    'target_zh',
                    'translation_status',
                    'race_grade',
                    'notes'
                )
            },
            ('aliases_ja','aliases_zh'), ('-priority','source_ja','id'), budget=budget)
        ext = ExternalHorseAlias.objects.filter(source_language=language).exclude(normalized_name='')
        ext = ext.annotate(
            candidate_key=Lower(
                'normalized_name'
            )
        ).filter(
            candidate_key__in=variants
        ) if language == SourceLanguage.ENGLISH else ext.filter(
            normalized_name__in=raw
        )
        material['external_alias'] = _project(ext, 'external_alias', ['id','updated_at','confidence','last_seen_at'],
            {
                name:255 for name in (
                    'source',
                    'source_language',
                    'external_horse_id',
                    'name_ja',
                    'name_en',
                    'normalized_name'
                )
            },
            order=('normalized_name','-confidence','-last_seen_at','external_horse_id','pk'), budget=budget)
    if language == SourceLanguage.ENGLISH:
        links = Q(event__article_links__article_id=article_id,
                  event__article_links__status__in=[ArticleRaceLinkStatus.AUTO,ArticleRaceLinkStatus.MANUAL],
                  event__article_links__removed_at__isnull=True)
        for kind, model in (('runner',RaceEventRunner),('result',RaceEventResult)):
            material[kind] = _project(model.objects.filter(links), kind,
                ['id','updated_at','event_id','event__article_links__article_id'], {'horse_name':255},
                order=(*model._meta.ordering,'pk'), budget=budget)
    total = 0
    inputs = capture_list(budget=budget)
    for kind in KINDS:
        for row in material[kind]:
            total += len(_row_bytes(row))
            if total > 512*1024:
                _limit()
            inputs.append(_record(kind, row, article_id))
    entries = capture_list(budget=budget)
    names = capture_dict(budget=budget)
    external = capture_list(budget=budget)
    non_horse = capture_set(terms._HORSE_STOPWORDS if language == SourceLanguage.JAPANESE else (), budget)
    for row in material['term']:
        values = dict(
            row,
            pk=row[
                'id'
            ],
            aliases_ja=_json_names(
                row[
                    'aliases_ja'
                ]
            ),
            aliases_zh=_json_names(
                row[
                    'aliases_zh'
                ]
            )
        )
        _int(values['priority'], -2**31, 2**31-1)
        if type(values['is_active']) is not bool:
            _invalid()
        entry = _Term(**values)
        entries.append(entry)
        field_names = names.setdefault(entry.id, capture_list(budget=budget))
        if entry.source_language == language:
            field_names.extend(entry.all_japanese_terms())
        if language in (SourceLanguage.CHINESE,SourceLanguage.CHINESE_TRADITIONAL):
            field_names.extend([entry.target_zh, *entry.aliases_zh])
    for row in material['alias']:
        names.setdefault(row['term_id'], capture_list(budget=budget)).append(row['text'])
    for key, values in names.items():
        # Preserve original dedupe/strip semantics, charge every copied reference before insertion.
        seen = capture_set(budget=budget); clean = capture_list(budget=budget)
        for value in values:
            value = value.strip()
            if value and value not in seen:
                seen.add(value); clean.append(value)
        names[key] = clean
    for entry in entries:
        if entry.term_type == TermType.FIXED_PHRASE and terms._NON_HORSE_NOTE_MARKER in entry.notes.casefold():
            non_horse.update(names.get(entry.id, ()))
    for row in material['external_alias']:
        _int(row['confidence'],0,65535)
        external.append(SimpleNamespace(**row))
    structured = capture_dict(budget=budget)
    for kind in ('runner','result'):
        for row in material[kind]:
            key = terms.normalize_horse_entity_key(row['horse_name'])
            structured.setdefault(
                key,
                capture_list(
                    budget=budget
                )
            ).append(
                f"race_{
                    kind
                }:{
                    row[
                        'id'
                    ]
                }:event:{
                    row[
                        'event_id'
                    ]
                }:horse_name"
            )
    index = terms.ArticleEntityIndex(
        {
            language:entries
        },
        {
            language:names
        },
        {
            language:external
        },
        {
            language:non_horse
        }
    )
    resolution = terms.resolve_article_entities(title,body,source_language=language,preloaded_index=index,
                                               structured_entities=structured,capture_budget=budget)
    snapshot = {'schema':SCHEMA,'article_id':article_id,'input_sha256':input_sha256,'source_language':str(language),
                'read_started_at':started_at,'read_finished_at':timezone.now().isoformat(),
                'inputs':list(inputs),'resolution':serialize_resolution(resolution)}
    decode(snapshot,view,article_id,input_sha256)
    return snapshot


def serialize_resolution(resolution):
    def row(obj):
        return {field.name: list(value) if isinstance(value := getattr(obj,field.name),list) else value
                for field in fields(obj)}
    return {'source_language':str(resolution.source_language),
            'entities':[row(v) for v in resolution.entities],
            'suppressed_candidates':[row(v) for v in resolution.suppressed_candidates],
            'accepted_terms':[row(v) for v in resolution.accepted_terms],
            'machine_horse_tags':list(resolution.machine_horse_tags)}


def decode(snapshot, view, article_id, input_sha256):
    """完整live-fenced可见文本纯验证，不访问任何材料表/关联。"""
    from . import terms
    from . import translation_recovery as recovery
    from stable.models import SourceLanguage
    _int(article_id)
    _hash(input_sha256)
    _builtin(snapshot)
    if len(canonical(snapshot)) > 8192:
        _limit()
    if type(
        snapshot
    ) is not dict or set(
        snapshot
    ) != {
        'schema',
        'article_id',
        'input_sha256',
        'source_language',
        'read_started_at',
        'read_finished_at',
        'inputs',
        'resolution'
    }:
        _invalid()
    if type(view) is not SimpleNamespace or any(name not in view.__dict__ for name in
            (
                'title_ja',
                'body_ja_normalized',
                'body_ja_raw',
                'source_language',
                'source_site',
                'source_article_id'
            )):
        _invalid()
    check_source(view)
    if recovery.translation_input_sha256(view) != input_sha256:
        _invalid()
    _int(snapshot['article_id']); _hash(snapshot['input_sha256'])
    if (snapshot['schema'] != SCHEMA or snapshot['article_id'] != article_id
            or snapshot['input_sha256'] != input_sha256 or type(snapshot['source_language']) is not str
            or snapshot['source_language'] != (view.source_language or SourceLanguage.JAPANESE)):
        _invalid()
    if _time(snapshot['read_started_at']) > _time(snapshot['read_finished_at']):
        _invalid()
    records = snapshot['inputs']
    if type(records) is not list:
        _invalid()
    seen = set(); term_ids = set(); external_ids = set(); structured = {}; counts = dict.fromkeys(KINDS,0)
    previous = -1
    for record in records:
        if type(record) is not dict or type(record.get('kind')) is not str or record['kind'] not in KINDS:
            _invalid()
        kind = record['kind']; position = KINDS.index(kind)
        extras = {
            'alias':{
                'term_id'
            },
            'external_alias':{
                'external_horse_id'
            },
            'runner':{
                'event_id',
                'article_id',
                'horse_name_key'
            },
            'result':{
                'event_id',
                'article_id',
                'horse_name_key'
            }
        }.get(
            kind,
            set()
        )
        if set(record) != {'kind','id','updated_at','row_sha256'} | extras or position < previous:
            _invalid()
        previous = position; _int(record['id']); _time(record['updated_at']); _hash(record['row_sha256'])
        identity = kind,record['id']
        if identity in seen:
            _invalid()
        seen.add(identity); counts[kind]+=1
        if counts[kind] > LIMITS[kind]:
            _limit()
        if kind == 'term':term_ids.add(record['id'])
        elif kind == 'alias':_int(record['term_id'])
        elif kind == 'external_alias':
            _str(
                record[
                    'external_horse_id'
                ],
                32,
                128,
                nonempty=True
            ); external_ids.add(
                record[
                    'external_horse_id'
                ]
            )
        else:
            _int(record['event_id']); _int(record['article_id']); _str(record['horse_name_key'],nonempty=True)
            if record['article_id'] != article_id:_invalid()
            structured[
                f"race_{
                    kind
                }:{
                    record[
                        'id'
                    ]
                }:event:{
                    record[
                        'event_id'
                    ]
                }:horse_name"
            ] = record[
                'horse_name_key'
            ]
    resolution = snapshot['resolution']
    if type(
        resolution
    ) is not dict or set(
        resolution
    ) != {
        'source_language',
        'entities',
        'suppressed_candidates',
        'accepted_terms',
        'machine_horse_tags'
    } or resolution[
        'source_language'
    ] != snapshot[
        'source_language'
    ]:
        _invalid()
    title, body = terms.visible_source_parts(view); parts={'title':title,'body':body}
    def collection(name, limit):
        values = resolution[name]
        if type(values) is not list:_invalid()
        if len(values)>limit:_limit()
        return values
    decoded = {}
    entity_rows = collection('entities',32) + collection('suppressed_candidates',32)
    for item in entity_rows:
        if type(item) is not dict or set(item) != {f.name for f in fields(terms.ArticleEntity)}:_invalid()
        for name in (
            'entity_type',
            'matched_text',
            'canonical_text',
            'target_zh',
            'field_name',
            'term_type',
            'classification',
            'reason',
            'matched_context'
        ):
            _str(item[name],1024,4096)
        if item['entity_type'] not in ('horse','unknown_horse','person','term','common_word','ambiguous'):
            _invalid()
        if item['classification'] not in ('','confirmed_horse','common_word','uncertain'):
            _invalid()
        for name in ('start','end'):_int(item[name],0)
        _int(item['confidence'],0,65535); _int(item['priority'],-2**31,2**31-1)
        if type(item['needs_preserve']) is not bool:_invalid()
        if item['term_id'] is not None:
            _int(item['term_id'])
            if item['term_id'] not in term_ids:_invalid()
        field = parts.get(item['field_name'])
        if field is None or not 0<=item[
            'start'
        ]<item[
            'end'
        ]<=len(
            field
        ) or field[
            item[
                'start'
            ]:item[
                'end'
            ]
        ] != item[
            'matched_text'
        ]:_invalid()
        for name in ('external_horse_ids','evidence','entity_evidence','conflict_flags'):
            values=item[name]
            if type(values) is not list:_invalid()
            if len(values)>64:_limit()
            for value in values:
                _str(value,1024,1024)
                if name=='external_horse_ids' and value not in external_ids:_invalid()
                if name in (
                    'evidence',
                    'entity_evidence'
                ) and value.startswith(
                    (
                        'race_runner:',
                        'race_result:'
                    )
                ):
                    if structured.get(
                        value
                    ) != terms.normalize_horse_entity_key(
                        item[
                            'matched_text'
                        ]
                    ):_invalid()
    for name in ('entities','suppressed_candidates'):
        decoded[name]=[terms.ArticleEntity(**v) for v in resolution[name]]
    accepted=collection('accepted_terms',32)
    for item in accepted:
        if type(item) is not dict or set(item)!={f.name for f in fields(terms.ResolvedTerm)}:_invalid()
        for name in ('term_type','source_ja','target_zh','matched_text','race_grade'):_str(item[name])
        _str(item['notes'],4096,4096);_int(item['priority'],-2**31,2**31-1)
        if not any(e['term_id'] in term_ids and e['term_type']==item['term_type'] and e['target_zh']==item['target_zh']
                   and e[
                       'matched_text'
                   ]==item[
                       'matched_text'
                   ] and e[
                       'canonical_text'
                   ]==item[
                       'source_ja'
                   ] for e in resolution[
                       'entities'
                   ]):_invalid()
    tags=collection('machine_horse_tags',12)
    for tag in tags:_str(tag)
    expected_tags = []
    for entity in resolution['entities']:
        if entity['entity_type'] in ('horse','unknown_horse'):
            tag = (entity['target_zh'] or (entity['matched_text'] if entity['needs_preserve'] else '')).strip()
            if tag and tag not in expected_tags:
                expected_tags.append(tag)
    if tags != expected_tags[:12]:_invalid()
    return terms.ArticleEntityResolution(resolution['source_language'],decoded['entities'],decoded['suppressed_candidates'],
                                        [terms.ResolvedTerm(**v) for v in accepted],list(tags))
