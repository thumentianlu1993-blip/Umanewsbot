"""HKJC 官方本地赛果字段合同，来源数字保持原赔率口径。"""
import re

UNITS = {'carried_weight': 'lb', 'margin': 'length', 'odds_value': 'decimal'}


def hkjc_source(source):
    return (source.source_key, source.region_code) == ('hkjc', 'hong_kong')


def margin_value(raw):
    value = str(raw or '').strip()
    if value in ('', '---', '-'):return ''
    names = {'N': 'neck', 'HD': 'head', 'SH': 'short head', 'NOSE': 'nose', 'DH': 'dead heat'}
    return names.get(value.upper(), re.sub(r'^(\d+)-(\d+/\d+)$', r'\1 \2', value))


def result_odds(provenance):
    value = str(provenance.get('win_odds') or '').strip()
    return value if re.fullmatch(r'\d+(?:\.\d+)?', value) else ''
