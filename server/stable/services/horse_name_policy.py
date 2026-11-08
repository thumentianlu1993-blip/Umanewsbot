"""马匹公开译名与后续翻译共用的来源策略；不修改存储值。"""
from functools import lru_cache
import re
from urllib.parse import urlsplit

from django.conf import settings


def enabled():
    return bool(getattr(settings, 'HORSE_NAMES_REQUIRE_HKJC_ENABLED', False))


@lru_cache(maxsize=1)
def _traditional_converter():
    # 与 termbase_seed 的 t2s 转换一致；每进程复用词典，避免每匹马重复加载。
    try:
        from opencc import OpenCC
        return OpenCC('t2s')
    except Exception:
        return None


def _simplified(value):
    converter = _traditional_converter()
    if converter is not None:
        return converter.convert(value)
    from stable.services.termbase_seed import to_simplified_chinese
    return to_simplified_chinese(value)


@lru_cache(maxsize=32768)
def hkjc_name_is_verified(target, notes):
    if not (target or '').strip():
        return False
    metadata = {}
    for part in (notes or '').split(';'):
        key, separator, value = part.strip().partition('=')
        if not separator:
            continue
        if key in metadata:
            return False
        metadata[key] = value.strip()
    if (metadata.get('source') not in {'hkjc', 'hkjc_overseas'}
            or metadata.get('source_tier') != 'official'
            or metadata.get('requires_review') != 'false'):
        return False
    try:
        url = urlsplit(metadata.get('evidence', ''))
        hostname = (url.hostname or '').lower()
        if url.scheme not in {'https', 'http'} or url.username or url.password:
            return False
        if url.port not in {None, 80, 443} or not all(
                re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in hostname.split('.')):
            return False
        if not any(hostname == root or hostname.endswith('.' + root)
                   for root in ('hkjc.com', 'hkjc.com.hk')):
            return False
    except ValueError:
        return False
    originals = metadata.get('original_zh_hant')
    if originals is not None:
        if not originals or any(_simplified(value.strip()) != target.strip()
                                for value in originals.split('|')):
            return False
    return True


def effective_target(term):
    target = term.target_zh or ''
    if not enabled() or term.term_type != 'horse':
        return target
    target = target.strip()
    if (not getattr(term, 'is_active', True)
            or getattr(term, 'translation_status', 'translated') != 'translated'):
        return ''
    return target if hkjc_name_is_verified(target, term.notes) else ''


def safe_original(value):
    """无实体证据的纯汉字文本可能是中文译名；不冒充可信原名。"""
    value = (value or '').strip()
    if re.search(r'[\u3400-\u9fff]', value) and not re.search(r'[\u3040-\u30ff]', value):
        return ''
    return value


def profile_name(profile):
    if not enabled():
        return profile.display_name
    return (effective_target(profile.primary_term)
            or safe_original(profile.primary_term.source_ja)
            or safe_original(profile.original_name)
            or safe_original(profile.english_name)
            or safe_original(profile.japanese_name)
            or '名称待核实')


def pedigree_name(profile, relation):
    text = getattr(profile, relation + '_text')
    if not enabled():
        return text
    term = getattr(profile, relation + '_term')
    related = getattr(profile, relation + '_horse_profile') if term is None else None
    if term is None and related is not None:
        term = related.primary_term
    if term is not None:
        return effective_target(term) or safe_original(term.source_ja) or safe_original(text)
    return safe_original(text)


def race_original(value, canonical=''):
    if not enabled():
        return value
    return safe_original(value) or safe_original(canonical) or '名称待核实'


def translation_candidates(term):
    if enabled() and term.term_type == 'horse':
        target = effective_target(term)
        return [target] if target else []
    return [term.target_zh, *(term.aliases_zh or [])]
