"""冻结清单驱动的日本历史空字段修复；不联网、不替换赛果、不触碰活跃版本。"""
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone
from stable import models

ACTION = 'repair_historical_jra_jockeys'
STAMP = 'historical_jockey_repair'
FIELDS_ACTION = 'repair_historical_jra_fields'
FILL_FIELDS = {'jockey_name', 'trainer_name', 'carried_weight', 'finish_time', 'margin', 'barrier', 'popularity', 'odds_value'}
ROW_MODELS = {'RaceEventResult': models.RaceEventResult, 'RaceEventRunner': models.RaceEventRunner}


def _manifest(path, expected_sha256):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('manifest_digest')
    data = json.loads(raw)
    items, events = data.get('items', []), data.get('events', [])
    version = data.get('schema_version')
    if (version not in (1, 2) or data.get('action') != (ACTION if version == 1 else FIELDS_ACTION)
            or not 1 <= len(items) <= 100000 or not events):
        raise ValueError('manifest_scope')
    if len({(i['model'], i['id']) for i in items}) != len(items):
        raise ValueError('duplicate_row')
    if len({e['id'] for e in events}) != len(events):
        raise ValueError('duplicate_event')
    if {i['event_id'] for i in items} != {e['id'] for e in events}:
        raise ValueError('event_set')
    for item in items:
        after = item['after']
        allowed = {'jockey_name'} if version == 1 else FILL_FIELDS
        if (item['model'] not in ROW_MODELS or not after or not set(after) <= allowed
                or item['before'] != {field: '' for field in after}
                or any(not isinstance(v,str) or not v.strip() or len(v) >
                       ROW_MODELS[item['model']]._meta.get_field(k).max_length for k,v in after.items())):
            raise ValueError('fill_only')
        if version == 2 and (item['model'] != 'RaceEventResult' or len(item.get('source_refs_sha256','')) != 64):
            raise ValueError('source_binding')
        url = urlsplit(item['source_url'])
        official_jra = url.netloc == 'www.jra.go.jp' and url.path.startswith('/datafile/seiseki/')
        official_nar = (version == 2 and url.netloc == 'www.keiba.go.jp'
                        and url.path == '/KeibaWeb/TodayRaceInfo/RaceMarkTable')
        if (url.scheme != 'https' or not (official_jra or official_nar) or len(item['source_sha256']) != 64):
            raise ValueError('source_scope')
    extras = data.get('extra_results', [])
    if extras and (version != 2 or len(extras) > 2 or len({e['event_id'] for e in extras}) != len(extras)):
        raise ValueError('extra_scope')
    for extra in extras:
        row = extra['row']
        allowed = {f.name for f in models.RaceEventResult._meta.fields} - {'id','event','created_at','updated_at'}
        if (extra['event_id'] not in {e['id'] for e in events} or not set(row) <= allowed
                or row.get('official_finish_position') is not None
                or row.get('running_status') not in {'pulled_up','fell','unseated_rider','did_not_finish','withdrawn'}
                or row.get('finish_position') != len(extra['before_result_ids'])+1
                or len(set(extra['before_result_ids'])) != len(extra['before_result_ids'])):
            raise ValueError('extra_scope')
        url = urlsplit(row.get('source_refs',{}).get('primary',''))
        official = ((url.netloc == 'www.jra.go.jp' and url.path.startswith('/datafile/seiseki/'))
                    or (url.netloc == 'www.keiba.go.jp' and url.path == '/KeibaWeb/TodayRaceInfo/RaceMarkTable'))
        if url.scheme != 'https' or not official:
            raise ValueError('source_scope')
        models.RaceEventResult(**row).clean_fields(exclude=['event'])
    return data


def execute(path, expected_sha256, *, mode='dry-run'):
    data = _manifest(path, expected_sha256)
    if mode not in {'dry-run', 'apply', 'restore'}:
        raise ValueError('mode')
    items = data['items']
    version = data['schema_version']
    action = data['action']
    stamp_key = STAMP if version == 1 else 'historical_fields_repair'
    expected_events = {e['id']: e for e in data['events']}
    now = timezone.now()
    with transaction.atomic():
        events = list(models.RaceEvent.objects.select_for_update().filter(pk__in=expected_events).order_by('pk'))
        if len(events) != len(expected_events):
            raise ValueError('event_missing')
        for event in events:
            expected = expected_events[event.pk]
            if (event.country_region != 'japan' or event.status != 'finished'
                    or not event.local_date or event.local_date >= date(2026, 9, 1)
                    or any(str(getattr(event, key)) != str(expected[key])
                           for key in ('year', 'local_date', 'original_name', 'slug'))):
                raise ValueError('event_scope')
            if any((event.manual_lock_flags or {}).values()):
                raise ValueError('event_manual_lock')
        if models.RaceEventFieldAuthority.objects.filter(event_id__in=expected_events, manual_lock=True).exists():
            raise ValueError('field_manual_lock')
        controls = list(models.RaceEventProjectionControl.objects.select_for_update().filter(event_id__in=expected_events))
        if any(control.write_owner != 'historical' for control in controls):
            raise ValueError('projection_owner')
        if models.RaceDataSyncEnrollment.objects.filter(event_id__in=expected_events).exists():
            raise ValueError('active_enrollment')
        receipt = models.OperationLog.objects.filter(action_type=action, target_type='manifest', target_id=expected_sha256).first()
        restored = models.OperationLog.objects.filter(action_type=action+'_restore', target_type='manifest', target_id=expected_sha256).exists()
        if restored and mode != 'restore':
            raise ValueError('already_restored')
        if mode == 'restore' and not receipt:
            raise ValueError('missing_receipt')
        expect_after = bool(receipt) and not restored
        extra_rows = []
        for extra in data.get('extra_results', []):
            rows = list(models.RaceEventResult.objects.select_for_update().filter(event_id=extra['event_id']).order_by('pk'))
            stamped = [r for r in rows if (r.source_refs or {}).get(stamp_key,{}).get('manifest_sha256') == expected_sha256
                       and (r.source_refs or {}).get(stamp_key,{}).get('created_result') is True]
            expected_ids = set(extra['before_result_ids'])
            if {r.pk for r in rows if r not in stamped} != expected_ids or len(stamped) != int(expect_after):
                raise ValueError('extra_membership_drift')
            if expect_after:
                row = stamped[0]
                expected = {**extra['row'],'source_refs':{**extra['row'].get('source_refs',{}),stamp_key:{
                    'manifest_sha256':expected_sha256,'created_result':True}}}
                expected_row = models.RaceEventResult(**expected)
                checked_fields = {f.name for f in models.RaceEventResult._meta.fields} - {'id','event','created_at','updated_at'}
                if any(getattr(row,k) != getattr(expected_row,k) for k in checked_fields):
                    raise ValueError('extra_after_drift')
                if mode == 'restore' and (models.HorseRaceRecord.objects.filter(result=row).exists()
                        or models.HorseP0Source.objects.filter(race_result=row).exists()):
                    raise ValueError('extra_reference')
                extra_rows.append(row)
            elif any(r.horse_number == extra['row']['horse_number'] or r.horse_name == extra['row']['horse_name'] for r in rows):
                raise ValueError('extra_identity_exists')
        grouped = {name: [] for name in ROW_MODELS}
        for item in items:
            grouped[item['model']].append(item)
        changed = {}
        for name, entries in grouped.items():
            rows = {r.pk: r for r in ROW_MODELS[name].objects.select_for_update().filter(
                pk__in=[i['id'] for i in entries]).order_by('pk')}
            if len(rows) != len(entries):
                raise ValueError('row_missing')
            for item in entries:
                row = rows[item['id']]
                if (row.event_id != item['event_id'] or row.horse_number != item['horse_number']
                        or row.horse_name != item['horse_name']
                        or (version == 2 and row.finish_position != item['finish_position'])):
                    raise ValueError('row_identity')
                if any((getattr(row, 'manual_lock_flags', None) or {}).values()):
                    raise ValueError('row_manual_lock')
                refs = row.source_refs or {}
                original_refs = {k:v for k,v in refs.items() if k != stamp_key}
                legacy_source = (refs.get('primary') == item['source_url']
                                 and refs.get('source_cache_identity', {}).get('sha256') == item['source_sha256'])
                refs_digest = hashlib.sha256(json.dumps(original_refs,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if (version == 1 and not legacy_source) or (version == 2 and refs_digest != item['source_refs_sha256']):
                    raise ValueError('source_identity')
                stamp = {'manifest_sha256': expected_sha256, 'source_sha256': item['source_sha256'],
                         'source_url': item['source_url'], 'field': 'jockey_name'}
                if version == 2:
                    stamp.pop('field')
                    stamp['fields'] = sorted(item['after'])
                expected_values = item['after' if expect_after else 'before']
                if (any(getattr(row,k) != v for k,v in expected_values.items())
                        or (refs.get(stamp_key) != stamp if expect_after else stamp_key in refs)):
                    raise ValueError('row_cas')
                for key,value in item['before' if mode == 'restore' else 'after'].items():
                    setattr(row,key,value)
                row.source_refs = dict(refs)
                if mode == 'restore':
                    row.source_refs.pop(stamp_key, None)
                else:
                    row.source_refs[stamp_key] = stamp
                row.updated_at = now
            changed[name] = list(rows.values())
        replay = bool(restored or (receipt and mode != 'restore'))
        counts = dict(Counter(i['model'] for i in items))
        report = {'manifest_sha256': expected_sha256, 'mode': mode, 'replay': replay,
                  'event_count': len(events), 'row_counts': counts, 'at': now.isoformat()}
        if mode != 'dry-run' and not replay:
            for name, rows in changed.items():
                fields = sorted({k for item in grouped[name] for k in item['after']})
                ROW_MODELS[name].objects.bulk_update(rows, [*fields, 'source_refs', 'updated_at'], batch_size=250)
            if mode == 'restore':
                for row in extra_rows:
                    row.delete()
            else:
                for extra in data.get('extra_results', []):
                    payload = {**extra['row'],'source_refs':{**extra['row'].get('source_refs',{}),stamp_key:{
                        'manifest_sha256':expected_sha256,'created_result':True}}}
                    models.RaceEventResult.objects.create(event_id=extra['event_id'],**payload)
            report['created_results'] = len(data.get('extra_results', []))
            models.OperationLog.objects.create(action_type=action+('_restore' if mode=='restore' else ''),
                target_type='manifest', target_id=expected_sha256, detail=json.dumps(report, ensure_ascii=False))
        return report
