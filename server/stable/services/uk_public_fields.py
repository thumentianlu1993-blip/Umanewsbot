"""英国已核验付费字段的公开单位；不以地区推测旧数据单位。"""
import re


def uk_source(source):
    return (source.source_key,source.region_code)==('the_racing_api','united_kingdom')


def result_odds(provenance):
    value=provenance.get('win_odds','')
    return value if provenance.get('uk_paid_v1') and isinstance(value,str) and re.fullmatch(r'\d+(?:\.\d+)?',value) else ''


def public_refs(provenance):
    if not provenance.get('uk_paid_v1'):return {}
    return dict(uk_paid_v1=True,primary=provenance.get('source_url',''),field_units={'carried_weight':'lb','odds_value':'decimal','margin':'length'},
        margin_basis='previous',odds_source=provenance.get('odds_source',''),odds_observed_at=provenance.get('odds_observed_at',''))
