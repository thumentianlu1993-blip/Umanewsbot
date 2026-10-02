from django import template
from stable.services.race_information_display import enabled, value

register = template.Library()


@register.simple_tag
def race_field(obj, field, legacy=''):
    if field == 'grade':
        from stable.services.race_information_display import event_grade_field
        return event_grade_field(obj).text
    if field in {'date', 'time'} and (hasattr(obj, 'local_date') or isinstance(obj, dict) and 'local_date' in obj):
        from stable.services.race_information_display import _time_fields
        return _time_fields(obj)[0 if field == 'date' else 1].text
    if field == 'eligibility':
        from stable.services.race_field_normalization import parse_display_eligibility
        parsed = parse_display_eligibility(value(obj, 'eligibility_text'))
        return parsed.text if parsed.state == 'normalized' else ''
    if not enabled():
        return legacy
    fields = value(obj, 'public_display', {}) or {}
    item = fields.get(field)
    # 新路径漏接入也不得把旧单位／不合规等级直接公开。
    return item.text if item is not None else '待核实'


@register.simple_tag
def race_grade_class(obj):
    from stable.services.race_information_display import event_grade_field
    code = event_grade_field(obj).code
    return 'g' + code[-1] if code in {'G1','G2','G3','JG1','JG2','JG3','JPN1','JPN2','JPN3'} else 'g-other'
