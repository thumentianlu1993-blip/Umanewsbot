from django import template
from stable.services.race_information_display import enabled, value

register = template.Library()


@register.simple_tag
def race_field(obj, field, legacy=''):
    if not enabled():
        return legacy
    fields = value(obj, 'public_display', {}) or {}
    item = fields.get(field)
    # 新路径漏接入也不得把旧单位／不合规等级直接公开。
    return item.text if item is not None else '待核实'
