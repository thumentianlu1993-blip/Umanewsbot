"""法国来源公开字段合同；保留原始公斤和报价平台。"""
import re


def france_source(source):
    return (source.source_key, source.region_code) == ('geny', 'france')


def result_odds(provenance):
    value=str(provenance.get('win_odds') or '')
    return value if re.fullmatch(r'\d+(?:\.\d+)?',value) else ''


def public_refs(provenance):
    return dict(field_units={'carried_weight':'kg','odds_value':'decimal','margin':'length'},
        primary=provenance.get('source_url',''),margin_basis=provenance.get('margin_relation',''),
        odds_source=provenance.get('odds_source',''),odds_observed_at=provenance.get('odds_observed_at',''),
        allocated_weight=provenance.get('allocated_weight',''),adjusted_weight=provenance.get('adjusted_weight',''))
