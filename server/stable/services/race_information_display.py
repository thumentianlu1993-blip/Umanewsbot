"""请求内赛事展示。只消费视图已准许公开的对象，不查赛果、不写业务数据。"""
from collections import Counter
from datetime import datetime, timezone, date, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit
import re
import unicodedata

from django.conf import settings

from stable.services.race_field_normalization import (
    display_field, parse_display_distance, parse_display_grade, parse_display_eligibility,
    parse_display_weight, parse_display_time, parse_display_margin, parse_display_number,
    parse_display_odds, parse_display_surface, parse_display_layout, parse_display_race_type, parse_display_money, _DISPLAY_CLASSES,
)
from stable.services.race_term_display import RaceTermResolver


def enabled():
    return getattr(settings, 'RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED', False)


def value(obj, name, default=''):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def attach(obj, fields):
    if isinstance(obj, dict):
        obj['public_display'] = fields
    else:
        obj.public_display = fields


def _catalog_meter_profile(obj, refs):
    """已核验官方目录的 m 字段合同；不对裸数字或仅有地区的记录推断单位。"""
    raw = unicodedata.normalize('NFKC', str(value(obj, 'distance_text') or '')).strip()
    if not re.fullmatch(r'\d+(?:\.\d+)?\s*m', raw, re.I):
        return ''
    region = value(obj, 'country_region') or value(obj, 'race_region')
    year = value(obj, 'year', None) or value(obj, 'race_year', None)
    if year != 2026:
        return ''

    def official_path(key, host):
        raw_url = refs.get(key)
        if not isinstance(raw_url, str):
            return ''
        try:
            url = urlsplit(raw_url)
            if (url.scheme != 'https' or url.hostname != host or url.username is not None
                    or url.password is not None or url.port not in (None, 443)):
                return ''
            return url.path
        except ValueError:
            return ''

    kind = refs.get('source_kind')
    if region == 'japan' and kind == 'jra_official_graded_race_list':
        if official_path('primary', 'www.jra.go.jp') == '/datafile/seiseki/replay/2026/jyusyo.html':
            return 'jra_graded_2026_meter_v1'
    if region == 'japan' and kind == 'keiba_go_jp_dirt_graded_race_list':
        if (official_path('primary', 'www.keiba.go.jp').startswith('/pdf/uploads/')
                and official_path('secondary', 'www.keiba.go.jp') == '/dirtgraderace/2026/racelist/index.html'):
            return 'nar_graded_2026_meter_v1'
    if region == 'france' and kind == 'france_galop_groupes_listed_2026':
        if re.fullmatch(r'/sites/default/files/2026-\d{2}/groupes_listed_(?:plat|obstacles)_2026_v\d+\.pdf',
                        official_path('primary', 'www.france-galop.com')):
            return 'france_galop_2026_meter_v1'
    # HKJC 本地赛事的官方途程字段为米。reviewed_import 是既有导入记录文字，
    # 不把它的真值当单位证据或发布批准；发布权限仍由现有视图控制。
    if (region == 'hong_kong' and refs.get('source_provider') == 'HKJC'
            and official_path('source_url', 'racing.hkjc.com')):
        return 'hkjc_local_2026_meter_v1'
    return ''


def source_context(obj):
    refs = value(obj, 'source_refs', {})
    refs = refs if isinstance(refs, dict) else {}
    # 单位仅接受明确结构化说明；不由国家、域名或数字大小推断。
    units = refs.get('field_units', {})
    units = units if isinstance(units, dict) else {}
    profile = _catalog_meter_profile(obj, refs)
    distance_unit = units.get('distance_text', '') if isinstance(units.get('distance_text'), str) else ''
    conflict = bool(profile and distance_unit and distance_unit.lower() not in {'m', 'meter', 'metre', 'meters', 'metres', '米'})
    return {
        'provider': value(obj, 'source_name') or refs.get('source_provider', ''),
        'schema': refs.get('parser_version', ''),
        'language': refs.get('source_language', ''),
        'region': value(obj, 'country_region') or value(obj, 'race_region'),
        'year': value(obj, 'year', None) or value(obj, 'race_year', None),
        'distance_unit': distance_unit or ('meter' if profile else ''),
        'distance_profile': profile,
        'distance_unit_conflict': conflict,
        'weight_unit': units.get('carried_weight', '') if isinstance(units.get('carried_weight'), str) else '',
        'odds_format': units.get('odds_value', '') if isinstance(units.get('odds_value'), str) else '',
        'margin_unit': units.get('margin', '') if isinstance(units.get('margin'), str) else '',
    }


def _time_fields(obj):
    day, clock, instant = value(obj, 'local_date', None), value(obj, 'local_start_time', None), value(obj, 'race_datetime', None)
    zone = value(obj, 'timezone_name')
    try:
        if isinstance(day, str): day = date.fromisoformat(day)
        if isinstance(clock, str): clock = time.fromisoformat(clock)
        if isinstance(instant, str): instant = datetime.fromisoformat(instant.replace('Z', '+00:00'))
    except ValueError:
        invalid = display_field({'date':day,'time':clock,'instant':instant}, state='unknown', reason='invalid_datetime')
        return invalid, invalid
    raw = {'date': day, 'time': clock, 'instant': instant, 'zone': zone}
    date_field = display_field(raw, day.isoformat()) if day else display_field(raw, state='missing', reason='missing')
    if not clock and not instant:
        return date_field, display_field(raw, state='missing', reason='missing')
    try:
        tz = ZoneInfo(zone)
        if instant:
            if instant.tzinfo is None:
                raise ValueError('naive instant')
            local = instant.astimezone(tz)
            if (day and local.date() != day) or (clock and local.time().replace(tzinfo=None) != clock):
                return date_field, display_field(raw, state='conflict', reason='time_conflict')
        elif day:
            naive = datetime.combine(day, clock)
            possible = set()
            for fold in (0, 1):
                candidate = naive.replace(tzinfo=tz, fold=fold)
                utc = candidate.astimezone(timezone.utc)
                if utc.astimezone(tz).replace(tzinfo=None) == naive:
                    possible.add(utc)
            if len(possible) != 1:
                return date_field, display_field(raw, f'{clock:%H:%M}（当地时间，时区待核实）',
                                                state='preserved', reason='dst_ambiguous_or_missing')
            local = next(iter(possible)).astimezone(tz)
        else:
            return date_field, display_field(raw, f'{clock:%H:%M}（当地时间，日期待核实）', state='preserved', reason='date_missing')
        date_field = display_field(raw, local.date().isoformat())
        beijing = local.astimezone(ZoneInfo('Asia/Shanghai'))
        return date_field, display_field(raw, f'{local:%H:%M}（当地时间，{zone}；北京时间{beijing:%Y-%m-%d %H:%M}）')
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return date_field, display_field(raw, f'{clock:%H:%M}（当地时间，时区待核实）' if clock else '待核实',
                                        state='preserved' if clock else 'unknown', reason='timezone_unknown')


def event_fields(obj):
    ctx = source_context(obj)
    date_field, time_field = _time_fields(obj)
    grade_raw = value(obj, 'grade_text')
    surface_raw = value(obj, 'surface')
    from .race_field_normalization import _display_text
    import re
    class_text = _display_text(grade_raw).upper()
    klass = _DISPLAY_CLASSES.get(class_text, '')
    wins = re.fullmatch(r'([123])勝(?:クラス)?', class_text)
    if wins: klass = wins[1] + '胜级'
    return {
        'name': display_field(value(obj, 'chinese_name') or value(obj, 'race_name') or value(obj, 'original_name'),
                              value(obj, 'chinese_name') or value(obj, 'race_name') or value(obj, 'original_name'), state='preserved'),
        'grade': parse_display_grade(grade_raw, normalized_grade=value(obj, 'normalized_grade'), context=ctx),
        'distance': (display_field(value(obj, 'distance_text'), state='conflict', reason='source_unit_conflict', context=ctx)
                     if ctx['distance_unit_conflict'] else
                     parse_display_distance(value(obj, 'distance_text'), unit_hint=ctx['distance_unit'], context=ctx)),
        'surface': parse_display_surface(surface_raw),
        'race_type': parse_display_race_type(value(obj,'race_type_text') or ('jumps' if surface_raw == 'jumps' else '')),
        'layout': parse_display_layout(value(obj,'course_layout_text')),
        'prize': parse_display_money(value(obj,'prize_text')),
        'weather': display_field('',state='missing',reason='unsupported_missing_source'),
        'going': display_field(value(obj,'going_text'),state='unknown' if value(obj,'going_text') else 'missing',reason='going_profile_required' if value(obj,'going_text') else 'unsupported_missing_source'),
        'race_class': display_field(grade_raw, klass) if klass else display_field('', state='missing', reason='missing'),
        'eligibility': parse_display_eligibility(value(obj, 'eligibility_text')),
        'racecourse': display_field(value(obj, 'racecourse'), value(obj, 'racecourse'), state='preserved'),
        'date': date_field, 'time': time_field,
    }


_STATUS_LABELS = {'did_not_finish': '未完赛', 'dnf': '未完赛', 'pulled_up': '拉停', 'unseated_rider': '骑师落马',
                  'fell': '跌倒', 'brought_down': '被碰倒', 'disqualified': '取消资格', 'scratched': '退赛',
                  'withdrawn': '取消出走', 'non_runner': '未出赛', 'declared': '已出走登记',
                  'refused': '拒跑', 'reinstated': '恢复出走', 'running': '进行中', 'unknown': '未知', 'finished': '完赛', 'dead_heat': '同着'}
_NON_FINISH = set(_STATUS_LABELS) - {'declared', 'running', 'reinstated', 'unknown', 'finished', 'dead_heat'}


def _position(row, *, horse_record=False):
    status = str(value(row, 'running_status') or value(row, 'normalized_result_status') or value(row, 'result_status')).lower()
    if status in _NON_FINISH:
        return display_field(status, _STATUS_LABELS[status])
    refs = value(row, 'source_refs', {}) or {}
    refs = refs if isinstance(refs, dict) else {}
    position = (value(row, 'reported_finish_position', None) or value(row, 'official_finish_position', None)
                or refs.get('official_finish_position'))
    if position is None and horse_record:
        position = value(row, 'finish_position')
        if not position and value(row, 'result_status') == 'won':
            position = 1
        abbreviations = {'DNF': '未完赛', 'PU': '拉停', 'SCR': '退赛', 'DQ': '取消资格'}
        if str(position).upper() in abbreviations:
            return display_field(position, abbreviations[str(position).upper()])
    if position is None:
        # 历史行已有视图投影可作为展示依据，不能把数据库排序字段当名次。
        position = value(row, 'public_position') or value(row, 'display_finish_position')
        if value(row, 'finish_position', None) == position and hasattr(row, 'official_finish_position'):
            return display_field(position, state='unknown', reason='ordering_position_unverified')
    if position is None or position == '':
        return display_field(position, state='missing', reason='missing')
    text = str(position)
    if not text.isdigit() or int(text) <= 0:
        return display_field(text, text, state='preserved') if text in _STATUS_LABELS.values() else display_field(text, state='unknown', reason='position_unknown')
    label = f'并列第{int(text)}' if status == 'dead_heat' else str(int(text))
    return display_field(position, label, code=str(int(text)))


def row_fields(row, *, horse_record=False):
    ctx = source_context(row)
    status = value(row, 'running_status') or value(row, 'result_status')
    return {
        'weight': parse_display_weight(value(row, 'carried_weight'), unit_hint=ctx['weight_unit']),
        'finish_time': parse_display_time(value(row, 'public_finish_time') if hasattr(row, 'public_finish_time') or isinstance(row, dict) and 'public_finish_time' in row else value(row, 'finish_time')),
        'margin': parse_display_margin(value(row, 'margin'), unit_hint=ctx['margin_unit']),
        'horse_number': parse_display_number(value(row, 'horse_number')),
        'barrier': parse_display_number(value(row, 'barrier')),
        'popularity': parse_display_number(value(row, 'popularity'), popularity=True),
        'odds': parse_display_odds(value(row, 'odds_value'), odds_format=ctx['odds_format']),
        'position': _position(row, horse_record=horse_record),
        'status': display_field(status, _STATUS_LABELS.get(status, '待核实')) if status else display_field(status, state='missing', reason='missing'),
    }



def horse_record_fields(record, *, event_source=None):
    """页面及盘点共用历史记录适配；只使用已加载的关联与既有公开计时。"""
    source = event_source or record
    fields = event_fields(source)
    if event_source is None or fields['date'].state == 'missing':
        day = value(record, 'race_date', None)
        fields['date'] = _time_fields({'local_date': day})[0]
        if not day and value(record, 'race_year', None):
            fields['date'] = display_field(value(record, 'race_year'), str(value(record, 'race_year')), state='preserved', reason='year_only')
    fields.update(row_fields(record, horse_record=True))
    if not hasattr(record, 'public_finish_time') and not (isinstance(record, dict) and 'public_finish_time' in record):
        linked = getattr(getattr(record, '_state', None), 'fields_cache', {}).get('result')
        fields['finish_time'] = parse_display_time(value(linked, 'finish_time') if linked is not None and value(linked, 'is_confirmed', False) else '')
    return fields


def prepare_context(context, *, force=False):
    """明确遍历公开context白名单；绝不访问event.results或其他reverse manager。"""
    if not force and not enabled():
        return context
    context['race_information_enabled'] = True
    events, rows, records, winner_entries = [], [], [], []
    candidate_previews = []
    for key in ('event', 'next_key_race', 'teaser_event', 'canonical_product_event'):
        if context.get(key) is not None:
            events.append(context[key])
    for key in ('focus_events', 'series_events'):
        events.extend(context.get(key) or [])
    for group in context.get('groups') or []:
        events.extend(group['events'])
    for entry in context.get('today_races') or []:
        events.append(entry['event'])
        if entry.get('winner'):
            row = SimpleNamespace(horse_name=entry['winner'])
            rows.append((entry['event'], row))
            winner_entries.append((entry, row))
    for link in context.get('race_links') or []:
        events.append(link.event)
    for key in ('race_records', 'major_wins'):
        for record in context.get(key) or []:
            records.append(record)
    event = context.get('event')
    for key in ('runners', 'results', 'history_winners', 'top_results'):
        rows.extend((event, row) for row in context.get(key) or [])
    if context.get('winner') is not None and not isinstance(context['winner'], str):
        rows.append((event, context['winner']))
    # 仅后台context提供候选；临时复制，不更改候选diff、状态或人工锁。
    for candidate in context.get('candidates') or []:
        payload = value(candidate, 'candidate_payload', {})
        candidate.normalized_preview = []
        if value(candidate, 'module') == 'basic' and isinstance(payload, dict):
            preview = {key: value(event, key) for key in ('chinese_name', 'original_name', 'grade_text', 'distance_text', 'racecourse', 'country_region', 'year', 'source_refs')}
            preview.update({key: val for key, val in payload.items() if key in preview})
            if 'distance_text' in payload:
                # 新候选距离必须使用自身证据，不能继承旧字段的来源单位。
                preview['source_refs'] = payload.get('source_refs', {})
            events.append(preview)
            candidate_previews.append((candidate, preview))
        elif value(candidate, 'module') in {'runners', 'results', 'history_winners'}:
            items = payload if isinstance(payload, list) else payload.get('items', []) if isinstance(payload, dict) else []
            for item in items[:20]:
                if isinstance(item, dict):
                    preview = dict(item)
                    if value(candidate, 'module') == 'results':
                        # 仅后台候选合同：apply将finish_position投影为官方名次。
                        preview['reported_finish_position'] = item.get('official_finish_position') or item.get('finish_position')
                    rows.append((event, preview))
                    candidate_previews.append((candidate, preview))
    events = list({id(e): e for e in events}.values())
    records = list({id(r): r for r in records}.values())
    for e in events:
        rows.extend((e, row) for row in value(e, 'top_results', []) or [])
        winner = value(e, 'public_winner_result', None)
        if winner is not None:
            rows.append((e, winner))
    rows = list({id(r): (e, r) for e, r in rows}.values())
    resolver = RaceTermResolver(mode='strict_display_v1').strict
    name_requests = []

    def add_name(obj, key, raw, kind, ctx):
        args = (str(raw or ''), kind, ctx['region'], ctx['language'], ctx['year'])
        resolver.add(*args)
        name_requests.append((obj, key, args))

    for e in events + records:
        source = e
        if e in records:
            # 只复用select_related已经取出的公开关联，不触发隐式查询。
            linked = getattr(getattr(e, '_state', None), 'fields_cache', {}).get('event')
            if linked is not None and value(linked, 'visibility_status') == 'published':
                source = linked
        fields = horse_record_fields(e, event_source=source if source is not e else None) if e in records else event_fields(source)
        attach(e, fields)
        ctx = source_context(source)
        raw_name = value(source, 'original_name') or value(source, 'race_name')
        chinese = value(source, 'chinese_name')
        if not chinese or chinese == raw_name:
            add_name(e, 'name', raw_name, 'race', ctx)
        add_name(e, 'racecourse', value(source, 'racecourse'), 'racecourse', ctx)
    for e, row in rows:
        attach(row, row_fields(row))
        ctx = source_context(row)
        event_ctx = source_context(e) if e is not None else {}
        for key in ('region', 'year'):
            ctx[key] = ctx[key] or event_ctx.get(key)
        for key, kind in (('horse_name', 'horse'), ('jockey_name', 'jockey'), ('trainer_name', 'trainer')):
            add_name(row, key, value(row, key), kind, ctx)
    resolver.resolve()
    for obj, key, args in name_requests:
        value(obj, 'public_display')[key] = resolver.field(*args)
    preview_labels = {'name': '赛事', 'grade': '等级', 'distance': '距离', 'racecourse': '马场',
                      'horse_name': '马匹', 'jockey_name': '骑师', 'trainer_name': '练马师',
                      'weight': '负重', 'finish_time': '计时', 'position': '名次', 'margin': '差距'}
    for candidate, preview in candidate_previews:
        fields = value(preview, 'public_display')
        candidate.normalized_preview.append([(label, fields[key].text) for key, label in preview_labels.items() if key in fields])
    for entry, row in winner_entries:
        entry['display_winner'] = row.public_display['horse_name'].text
    for e in events:
        winner = value(e, 'public_winner_result', None)
        if winner is not None:
            e.public_display['winner'] = value(winner, 'public_display')['horse_name']
    # 同着在完整已公开结果集合内判断，不由切片排名或来源行序推断。
    results = context.get('results') or []
    places = Counter(value(r, 'public_display')['position'].code for r in results)
    for row in results:
        field = value(row, 'public_display')['position']
        if field.code and (places[field.code] > 1 or value(row, 'margin') in {'同着', 'DH', 'dead heat'}):
            value(row, 'public_display')['position'] = display_field(field.text, f'并列第{field.code}', code=field.code)
    return context
