"""只读核验已提交英国目录收据；来源 JSON 和 event_id 均不能自行授予身份。"""
import json
from collections import Counter
from stable import models
from .race_data_source_adapters import canonical_sha, require_sha
from .uk_sources import PARSER_VERSION, name_key

# 只比较身份与审核依据；自然调度更新状态、时间和名单不撤销原年度目录身份。
EVENT_FIELDS = ('id', 'year', 'edition_year', 'original_name', 'country_region',
                'racecourse', 'timezone_name', 'local_date', 'race_series_id', 'division_parent_id')
TARGET_FIELDS = ('id', 'event_id', 'race_series_id', 'year', 'country_region',
                 'local_date', 'racecourse', 'resolution_status', 'superseded_by_id')


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
        target_type='manifest', target_id__in=digests).only('target_id', 'detail'))
    counts = Counter(r.target_id for r in receipts)
    restored = set(models.OperationLog.objects.filter(action_type='uk_release_restore',
        target_type='manifest', target_id__in=digests).values_list('target_id', flat=True))
    by_digest = {r.target_id: r for r in receipts if counts[r.target_id] == 1 and r.target_id not in restored}
    matched = {}
    for target in targets:
        digest = target.source_refs.get('uk_release_manifest')
        receipt = by_digest.get(digest)
        if receipt is None:
            continue
        event = target.event
        try:
            require_sha(digest)
            saved = json.loads(receipt.detail)
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
