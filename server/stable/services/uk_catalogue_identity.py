"""只读核验已提交英国目录收据；来源 JSON 和 event_id 均不能自行授予身份。"""
import json
from collections import Counter
from django.db import connection
from django.db.models import BinaryField
from django.db.models.functions import Cast, Length, Substr
from stable import models
from .race_data_source_adapters import canonical_sha, require_sha
from .uk_sources import PARSER_VERSION, name_key

# 只比较身份与审核依据；自然调度更新状态、时间和名单不撤销原年度目录身份。
EVENT_FIELDS = ('id', 'year', 'edition_year', 'original_name', 'country_region',
                'racecourse', 'timezone_name', 'local_date', 'race_series_id', 'division_parent_id')
TARGET_FIELDS = ('id', 'event_id', 'race_series_id', 'year', 'country_region',
                 'local_date', 'racecourse', 'resolution_status', 'superseded_by_id')

# PostgreSQL 16在数据库内裁剪历史快照；不得把整份年度收据传入worker。
MAX_RECEIPT_BYTES = 40 * 1024 * 1024
MAX_PROJECTION_BYTES = 256 * 1024


def _receipt_projection(receipt_id, event_ids, target_ids):
    if connection.vendor != 'postgresql':
        # SQLite开发环境只读取有界前缀；大收据不能回退成整文档Python解析。
        limit = min(MAX_RECEIPT_BYTES, MAX_PROJECTION_BYTES)
        row = models.OperationLog.objects.filter(pk=receipt_id, action_type='uk_release_data',
            target_type='manifest').annotate(prefix=Substr('detail', 1, limit + 1),
                detail_bytes=Length(Cast('detail', BinaryField()))).values_list('prefix', 'detail_bytes').first()
        if not row or not row[0]:
            return {}
        prefix, size = row
        # SQLite文本Substr/Length会在NUL处截断；BLOB长度必须与完整前缀字节数一致。
        if size > limit or len(prefix.encode('utf-8')) != size:
            return {}
        try:
            return json.loads(prefix)
        except ValueError:
            return {}
    table = connection.ops.quote_name(models.OperationLog._meta.db_table)
    # json保留文本表示；避免jsonb为整个30MB收据构造对象树的开销。
    # 每个数组先验证形状，数组内仅目标ID对应行进入聚合及客户端。
    def selected(kind, key, ids):
        expression = "value"
        identity = "item" if key is None else "item->'" + key + "'"
        # 不可过滤掉123.0后仅留下123，从而隐藏原本有歧义的两条身份行。
        valid = f"json_typeof({identity}) = 'number' AND ({identity})::text ~ '^[0-9]+$'"
        if key is not None:
            valid = f"json_typeof(item) = 'object' AND {identity} IS NOT NULL AND ({valid})"
        return f"""(SELECT CASE WHEN COALESCE(bool_and({valid}), true) THEN
            COALESCE(json_agg(item) FILTER (WHERE json_typeof({identity}) = 'number'
                AND ({identity})::text = ANY(%s)), '[]'::json) END
            FROM arrays CROSS JOIN LATERAL json_array_elements(CASE WHEN json_typeof({expression}) = 'array'
                THEN {expression} ELSE '[]'::json END) AS item
            WHERE kind = '{kind}')""", [str(pk) for pk in ids]
    parts = [selected('event_ids', None, event_ids),
             selected('report_events', 'event_id', event_ids),
             selected('released_events', 'id', event_ids),
             selected('released_targets', 'id', target_ids)]
    with connection.cursor() as cursor:
        cursor.execute(f"""
            WITH receipt AS MATERIALIZED (
                SELECT CASE WHEN octet_length(detail) <= %s THEN
                    CASE WHEN pg_input_is_valid(detail, 'json') THEN detail::json END
                    END AS doc
                FROM {table} WHERE id = %s AND action_type = 'uk_release_data'
                    AND target_type = 'manifest'
            ), parts AS MATERIALIZED (
                SELECT DISTINCT ON (part.key) part.key, part.value
                FROM receipt CROSS JOIN LATERAL json_each(CASE WHEN json_typeof(doc) = 'object'
                    THEN doc ELSE '{{}}'::json END) WITH ORDINALITY AS part(key, value, ordinal)
                WHERE part.key IN ('event_ids', 'report', 'after')
                ORDER BY part.key, part.ordinal DESC
            ), arrays AS MATERIALIZED (
                SELECT 'event_ids' AS kind, value FROM parts WHERE key = 'event_ids'
                UNION ALL SELECT 'report_events', value->'events' FROM parts WHERE key = 'report'
                UNION ALL
                SELECT CASE key WHEN 'RaceEvent' THEN 'released_events' ELSE 'released_targets' END, value
                FROM (
                    SELECT DISTINCT ON (part.key) part.key, part.value
                    FROM parts CROSS JOIN LATERAL json_each(CASE
                        WHEN parts.key = 'after' AND json_typeof(parts.value) = 'object'
                        THEN parts.value ELSE '{{}}'::json END) WITH ORDINALITY AS part(key, value, ordinal)
                    WHERE part.key IN ('RaceEvent', 'HistoricalRaceEventTarget')
                    ORDER BY part.key, part.ordinal DESC
                ) AS after_parts
            ), projection AS MATERIALIZED (
                SELECT json_build_object(
                    'event_ids', {parts[0][0]},
                    'report', json_build_object('events', {parts[1][0]}),
                    'after', json_build_object('RaceEvent', {parts[2][0]},
                        'HistoricalRaceEventTarget', {parts[3][0]}))::text AS detail
            )
            SELECT CASE WHEN octet_length(detail) <= %s THEN detail END FROM projection
        """, [MAX_RECEIPT_BYTES, receipt_id, *(part[1] for part in parts), MAX_PROJECTION_BYTES])
        row = cursor.fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def _same_fields(obj, saved, fields):
    return all(str(getattr(obj, key)) == str(saved.get(key)) for key in fields)


def released_catalogue_targets(value, *, route):
    """返回与来源相符的全部强锚点，由通用解析器拒绝歧义/其他锚点冲突。"""
    if (route.provider, route.region, route.parser_version) != (
            'the_racing_api', 'united_kingdom', PARSER_VERSION):
        return {}
    aliases = route.venue_aliases.get(value['venue_key'], ())
    targets = list(models.HistoricalRaceEventTarget.objects.filter(
        country_region='united_kingdom', local_date=value['local_date'],
        racecourse__in=aliases, resolution_status='imported', superseded_by__isnull=True,
        event__country_region='united_kingdom', event__local_date=value['local_date'],
        event__racecourse__in=aliases, event__race_series__review_status='approved',
        event__division_parent__isnull=True, event__divisions__isnull=True,
    ).select_related('event'))
    digests = {t.source_refs.get('uk_release_manifest') for t in targets}
    digests.discard(None)
    receipts = list(models.OperationLog.objects.filter(action_type='uk_release_data',
        target_type='manifest', target_id__in=digests).only('id', 'target_id'))
    counts = Counter(r.target_id for r in receipts)
    restored = set(models.OperationLog.objects.filter(action_type='uk_release_restore',
        target_type='manifest', target_id__in=digests).values_list('target_id', flat=True))
    by_digest = {r.target_id: r for r in receipts if counts[r.target_id] == 1 and r.target_id not in restored}
    # 同一调用内每份收据只投影一次，不跨调用缓存，撤销或新重复收据立即生效。
    saved_by_digest = {}
    for digest, receipt in by_digest.items():
        selected = [t for t in targets if t.source_refs.get('uk_release_manifest') == digest]
        saved_by_digest[digest] = _receipt_projection(receipt.pk,
            [t.event_id for t in selected], [t.pk for t in selected])
    matched = {}
    for target in targets:
        digest = target.source_refs.get('uk_release_manifest')
        receipt = by_digest.get(digest)
        if receipt is None:
            continue
        event = target.event
        try:
            require_sha(digest)
            saved = saved_by_digest[digest]
            released_events = [r for r in saved['after']['RaceEvent'] if r['id'] == event.pk]
            released_targets = [r for r in saved['after']['HistoricalRaceEventTarget'] if r['id'] == target.pk]
            if len(released_events) != 1 or len(released_targets) != 1:
                continue
            released, original_target = released_events[0], released_targets[0]
            if (event.pk not in saved['event_ids']
                    or event.pk not in [r['event_id'] for r in saved['report']['events']]
                    or not _same_fields(event, released, EVENT_FIELDS)
                    or not _same_fields(target, original_target, TARGET_FIELDS)
                    or original_target['source_refs'].get('uk_release_manifest') != digest):
                continue
            refs = event.source_refs
            spec, catalogue = refs['uk_target_v1'], refs['uk_catalogue_v1']
            if any(refs[k] != released['source_refs'].get(k) for k in ('uk_target_v1', 'uk_catalogue_v1')):
                continue
            require_sha(catalogue['source_sha256'])
            if (not catalogue.get('source_url') or spec['reviewed_date'] != str(event.local_date)
                    or spec['reviewed_course'] != event.racecourse
                    or event.timezone_name != route.timezone
                    or event.year != target.year or event.edition_year != event.year
                    or event.race_series_id != target.race_series_id
                    or (spec.get('external_race_id') and spec['external_race_id'] != value['external_race_id'])):
                continue
            terms = spec['name_keys']
            if (not isinstance(terms, list) or not terms
                    or any(not isinstance(t, str) or len(t) < 4 or t != name_key(t) for t in terms)):
                continue
            names = [name_key(n).replace('steeplechase', 'chase') for n in value['raw_names']]
            if not any(t.replace('steeplechase', 'chase') in n for t in terms for n in names):
                continue
        except (KeyError, TypeError, ValueError):
            # 缺失/损坏的历史收据不能当成新授权；不修改该收据或其他候选。
            continue
        matched[event.pk] = dict(manifest_sha256=digest, target_id=target.pk,
            catalogue_sha256=canonical_sha(catalogue), reviewed_target_sha256=canonical_sha(spec))
    return matched
