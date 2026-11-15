"""HKJC 来源的只读名称展示目录；不创建或合并实体。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit


KINDS = {'horse', 'jockey', 'trainer'}
COUNTRIES = 'JPN|GB|IRE|FR|USA|GER|AUS|NZ|CAN|ARG|BRZ|CHI|SAF|ITY|UAE|HK'
logger = logging.getLogger(__name__)


def country_suffix(value):
    found = re.search(r'\((' + COUNTRIES + r')\)\s*$', unicodedata.normalize('NFKC', value or ''), re.I)
    return found.group(1).upper() if found else ''


def positive_int(value):
    return int(value) if not isinstance(value, bool) and re.fullmatch(r'[1-9][0-9]{0,3}', str(value)) else None


def context_key(context):
    """名称解析请求按身份上下文隔离；不把整块 raw_payload 放入键中。"""
    return tuple((k, str(v)) for k, v in sorted((context or {}).items())
                 if k in {'country', 'birth_year', 'sire', 'dam', 'age', 'race_year', 'full_name'}
                 and v is not None and str(v).strip())


def name_key(value, kind):
    text = unicodedata.normalize('NFKC', value or '').strip().casefold()
    if kind == 'horse':
        text = re.sub(r'\s*\((?:' + COUNTRIES.lower() + r')\)\s*$', '', text)
    text = text.translate(str.maketrans({'’': "'", '‘': "'", '‐': '-', '‑': '-', '–': '-'}))
    # 重音折叠只作用于拉丁字符，不分解日语浊音。
    text = ''.join(''.join(c for c in unicodedata.normalize('NFD', ch)
                           if not unicodedata.combining(c))
                   if 'LATIN' in unicodedata.name(ch, '') else ch for ch in text)
    if kind != 'horse':
        text = text.replace('.', ' ')
        if re.search(r'[\u3040-\u30ff\u3400-\u9fff]', text):
            text = re.sub(r'\s+', '', text)
        else:
            # 法国来源常用“姓 + 首字母”；只反转明确缩写，不猜全名顺序。
            parts = text.replace(',', ' ').split()
            if len(parts) >= 2 and len(parts[0]) > 1 and all(re.fullmatch('[a-z]', p) for p in parts[1:]):
                text = ' '.join(parts[1:] + parts[:1])
    return ' '.join(text.split())


def person_tokens(key):
    # 多人、团体、单词姓名不生成首字母猜测；姓氏中的连字符/撇号保留。
    if not re.fullmatch(r"[a-z][a-z '\-]*", key):
        return []
    parts = key.split()
    if not 2 <= len(parts) <= 5 or any(p in {'and', 'et', 'jr', 'sr'} for p in parts):
        return []
    return parts


def initials_keys(key):
    parts = person_tokens(key)
    if not parts or len(parts[-1]) < 2 or any(len(p) < 2 for p in parts[:-1]):
        return set()
    # 保留全部中间名首字母；不擅自丢中间名、换姓氏顺序或生成姓氏单独匹配。
    return {' '.join([*(p[0] for p in parts[:-1]), parts[-1]])}


def is_initials(key):
    parts = person_tokens(key)
    return bool(parts and len(parts[-1]) > 1 and all(len(p) == 1 for p in parts[:-1]))


def official_source(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password
                and parsed.port in {None, 80, 443}
                and any(host == root or host.endswith('.' + root) for root in ('hkjc.com', 'hkjc.com.hk')))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class NameMatch:
    text: str
    state: str
    reason: str
    evidence_ids: tuple = ()


class NameCatalog:
    def __init__(self, entries):
        if not isinstance(entries, (list, tuple)):
            raise ValueError('HKJC entries must be an array')
        self.entries = list(entries)
        self.exact = defaultdict(set)
        self.initials = defaultdict(set)
        self.full_names = {}
        for index, row in enumerate(self.entries):
            if (not isinstance(row, dict)
                    or any(not isinstance(row.get(field), str) or not row[field].strip()
                           for field in ('id', 'kind', 'target', 'source'))
                    or not isinstance(row.get('names'), list) or not row['names']
                    or any(not isinstance(name, str) or not name.strip() for name in row['names'])):
                raise ValueError('invalid HKJC entry structure')
            kind = row['kind']
            if (kind not in KINDS or not row['target'].strip() or not row['names']
                    or not official_source(row['source'])):
                raise ValueError('invalid HKJC name evidence')
            if 'identity_group' in row and (not isinstance(row['identity_group'], str) or not row['identity_group']):
                raise ValueError('invalid reviewed identity group')
            identity = row.get('identity', {})
            if not isinstance(identity, dict) or any(
                    k not in {'country', 'birth_year', 'sire', 'dam'}
                    or (k == 'birth_year' and positive_int(v) is None)
                    or (k != 'birth_year' and (not isinstance(v, str) or not v.strip()))
                    for k, v in identity.items()):
                raise ValueError('invalid horse identity')
            years = row.get('active_years')
            if 'active_years' in row and (not isinstance(years, list) or len(years) != 2
                    or any(v is not None and positive_int(v) is None for v in years)
                    or (all(v is not None for v in years) and int(years[0]) > int(years[1]))):
                raise ValueError('invalid role dates')
            full_names = set()
            for name in row['names']:
                key = name_key(name, kind)
                if not key:
                    raise ValueError('empty name')
                self.exact[kind, key].add(index)
                if kind != 'horse':
                    keys = initials_keys(key)
                    if keys:
                        full_names.add(key)
                    for short in keys:
                        self.initials[kind, short].add(index)
            self.full_names[index] = full_names

    def match(self, value, kind, context=None):
        key = name_key(value, kind)
        indices = set(self.exact.get((kind, key), ()))
        abbreviated = kind != 'horse' and is_initials(key)
        if abbreviated:
            indices.update(self.initials.get((kind, key), ()))
        if not indices:
            return NameMatch(value, 'preserved', 'hkjc_name_missing')
        original_indices = set(indices)
        context = dict(context_key(context))
        # 产地来自马名后缀或明确身份字段，绝不使用赛事举办地区。
        if kind == 'horse':
            supported = set()
            country = country_suffix(value)
            if country and context.get('country') and country != context['country'].upper():
                return self._conflict(value, original_indices)
            country = country or context.get('country', '').upper()
            birth = positive_int(context.get('birth_year'))
            age, year = positive_int(context.get('age')), positive_int(context.get('race_year'))
            estimated = year - age if year and age else None
            if birth and estimated and birth != estimated:
                return self._conflict(value, original_indices)
            wanted = {'country': country, 'birth_year': birth or estimated,
                      'sire': context.get('sire'), 'dam': context.get('dam')}
            for field, expected in wanted.items():
                if not expected:
                    continue
                # 缺失身份字段不能被当作不符而排除，否则可能制造伪唯一。
                def compatible(i):
                    actual = self.entries[i].get('identity', {}).get(field)
                    if field == 'country' and not actual:
                        actual = next((country_suffix(n) for n in self.entries[i]['names'] if country_suffix(n)), '')
                    if not actual:
                        return True
                    agrees = (int(actual) == int(expected) if field == 'birth_year'
                              else name_key(actual, 'horse') == name_key(str(expected), 'horse'))
                    if agrees:
                        supported.add(i)
                    return agrees
                indices = {i for i in indices if compatible(i)}
            if indices != original_indices and not (indices & supported):
                return self._conflict(value, original_indices)
        else:
            year = positive_int(context.get('race_year'))
            if year:
                indices = {i for i in indices if self._active(i, year)}
            full = context.get('full_name')
            if full:
                confirmed = self.exact.get((kind, name_key(full, kind)), set())
                indices &= confirmed
        if not indices:
            return self._conflict(value, original_indices)
        targets = {self.entries[i]['target'] for i in indices}
        full_names = {self.entries[i].get('identity_group', name)
                      for i in indices for name in self.full_names[i]
                      if key in initials_keys(name)} if abbreviated else set()
        ids = tuple(sorted({self.entries[i]['id'] for i in indices}))
        if len(targets) != 1 or len(full_names) > 1:
            return NameMatch(value, 'conflict', 'hkjc_name_conflict', ids)
        reason = 'hkjc_initials' if abbreviated else 'hkjc_exact_alias'
        if indices != original_indices:
            reason = 'hkjc_identity_context'
        return NameMatch(next(iter(targets)), 'normalized', reason, ids)

    def _active(self, index, year):
        start, end = self.entries[index].get('active_years', [None, None])
        return (start is None or year >= int(start)) and (end is None or year <= int(end))

    def _conflict(self, value, indices):
        return NameMatch(value, 'conflict', 'hkjc_name_conflict',
                         tuple(sorted({self.entries[i]['id'] for i in indices})))


@lru_cache(maxsize=2)
def load_catalog(path, expected_sha256):
    data = Path(path).read_bytes()
    if not expected_sha256 or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('HKJC catalog SHA mismatch')
    payload = json.loads(data)
    if not isinstance(payload, dict) or payload.get('schema') != 'hkjc-name-display-v1':
        raise ValueError('unsupported HKJC name catalog')
    return NameCatalog(payload['entries'])


def configured_catalog():
    from django.conf import settings
    path = getattr(settings, 'RACE_HKJC_NAME_CATALOG_PATH', '')
    if not path:
        return None
    try:
        return load_catalog(path, getattr(settings, 'RACE_HKJC_NAME_CATALOG_SHA256', ''))
    except (OSError, ValueError, KeyError, TypeError):
        # 不输出目录内容；配置错误恢复既有展示，不采用未绑定的新目录。
        logger.error('HKJC name catalog unavailable or invalid')
        return NameCatalog([])
