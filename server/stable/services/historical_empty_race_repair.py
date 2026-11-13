"""有来源证据的空表历史赛事修复。"""
import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from stable import models as m

ACTION = 'repair_historical_empty_races'
STAMP = 'historical_empty_repair'

EVENT_FIELDS = ('year', 'local_date', 'slug', 'original_name', 'country_region',
                'status', 'visibility_status', 'data_quality_status', 'source_refs')
TARGET_FIELDS = ('event_id', 'expectation_status', 'resolution_status', 'module_statuses', 'source_refs')
ROW_MODELS = {'runners':m.RaceEventRunner, 'results':m.RaceEventResult}


def event_snapshot(event):
    return {key: str(getattr(event, key)) if key == 'local_date' else getattr(event, key)
            for key in EVENT_FIELDS}


def execute(path, expected_sha256, *, mode='dry-run'):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('manifest_digest')
    data = json.loads(raw)
    entries = data.get('events', [])
    if (mode not in {'dry-run', 'apply', 'restore'} or data.get('schema_version') != 1
            or data.get('action') != ACTION or not 1 <= len(entries) <= 8
            or len({x['id'] for x in entries}) != len(entries)):
        raise ValueError('manifest_scope')
    for entry in entries:
        before = entry['before']
        if (set(before) != set(EVENT_FIELDS) or before['status'] != 'finished'
                or before['visibility_status'] != 'draft'
                or not date.fromisoformat(before['local_date']) < date(2026, 9, 1)
                or entry['mode'] not in {'cancel', 'fill'}
                or before['country_region'] != ('united_kingdom' if entry['mode'] == 'cancel' else 'france')):
            raise ValueError('event_scope')
        if not entry['sources']:
            raise ValueError('source_missing')
        for source in entry['sources']:
            u = urlsplit(source['url'])
            if (u.scheme != 'https' or u.netloc not in {'www.sportinglife.com', 'www.racingpost.com'}
                    or len(source['sha256']) != 64):
                raise ValueError('source_scope')
        runners, results = entry['runners'], entry['results']
        if entry['mode'] == 'cancel':
            if runners or results:
                raise ValueError('cancel_has_rows')
        else:
            keys = lambda rows: {(r['horse_number'], r['horse_name']) for r in rows}
            if (not 1 <= len(runners) <= 40 or len(runners) != len(results)
                    or len(keys(runners)) != len(runners) or keys(runners) != keys(results)
                    or sorted(r['finish_position'] for r in results) != list(range(1,len(results)+1))):
                raise ValueError('roster_mismatch')
            for kind, model in ROW_MODELS.items():
                allowed = {f.name for f in model._meta.fields} - {'id','event','created_at','updated_at'}
                for row in entry[kind]:
                    if not set(row) <= allowed:
                        raise ValueError('row_fields')
                    obj = model(**row)
                    obj.clean_fields(exclude=['event'])
        if (len({t['id'] for t in entry['targets']}) != len(entry['targets'])
                or any(set(t['before']) != set(TARGET_FIELDS) or t['before']['event_id'] != entry['id']
                       for t in entry['targets'])):
            raise ValueError('target_scope')

    ids = [e['id'] for e in entries]
    with transaction.atomic():
        events = {e.pk:e for e in m.RaceEvent.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
        if len(events) != len(ids):
            raise ValueError('event_missing')
        if any(any((e.manual_lock_flags or {}).values()) for e in events.values()):
            raise ValueError('manual_lock')
        if m.RaceEventFieldAuthority.objects.filter(event_id__in=ids,manual_lock=True).exists():
            raise ValueError('field_manual_lock')
        controls = list(m.RaceEventProjectionControl.objects.select_for_update().filter(event_id__in=ids))
        if any(c.write_owner != 'historical' for c in controls):
            raise ValueError('projection_owner')
        if m.RaceDataSyncEnrollment.objects.filter(event_id__in=ids).exists():
            raise ValueError('active_enrollment')
        targets = {t.pk:t for t in m.HistoricalRaceEventTarget.objects.select_for_update().filter(event_id__in=ids).order_by('pk')}
        if set(targets) != {t['id'] for e in entries for t in e['targets']}:
            raise ValueError('target_set_drift')
        current_rows = {kind:list(model.objects.select_for_update().filter(event_id__in=ids).order_by('pk').values())
                        for kind,model in ROW_MODELS.items()}
        receipt = m.OperationLog.objects.filter(action_type=ACTION,target_type='manifest',target_id=expected_sha256).first()
        restored = m.OperationLog.objects.filter(action_type=ACTION+'_restore',target_type='manifest',target_id=expected_sha256).exists()
        if restored and mode != 'restore':
            raise ValueError('already_restored')
        if mode == 'restore' and not receipt:
            raise ValueError('missing_receipt')
        after = json.loads(receipt.detail)['after'] if receipt and not restored else None
        if after:
            if _snapshot(events,targets,current_rows) != after:
                raise ValueError('after_drift')
        else:
            if any(current_rows.values()):
                raise ValueError('not_empty')
            for entry in entries:
                if event_snapshot(events[entry['id']]) != entry['before']:
                    raise ValueError('event_cas')
                for t in entry['targets']:
                    if _target_snapshot(targets[t['id']]) != t['before']:
                        raise ValueError('target_cas')
        replay = bool(restored or (receipt and mode != 'restore'))
        report = {'manifest_sha256':expected_sha256,'mode':mode,'replay':replay,
                  'event_count':len(ids),'cancelled':sum(e['mode']=='cancel' for e in entries),
                  'result_count':sum(len(e['results']) for e in entries)}
        if mode == 'dry-run' or replay:
            return report
        if mode == 'restore':
            if m.HorseRaceRecord.objects.filter(result_id__in=[r['id'] for r in current_rows['results']]).exists():
                raise ValueError('career_reference')
            if m.HorseP0Source.objects.filter(
                    Q(race_result_id__in=[r['id'] for r in current_rows['results']])
                    | Q(race_runner_id__in=[r['id'] for r in current_rows['runners']])).exists():
                raise ValueError('source_reference')
            for model in ROW_MODELS.values():
                model.objects.filter(event_id__in=ids).delete()
        for entry in entries:
            event = events[entry['id']]
            stamp = {'manifest_sha256':expected_sha256,'sources':entry['sources']}
            patch = {k:entry['before'][k] for k in ('status','visibility_status','data_quality_status','source_refs')}
            if mode == 'apply':
                patch['source_refs'] = {**patch['source_refs'],STAMP:stamp}
                if entry['mode'] == 'cancel':
                    patch['status'] = 'cancelled'
                else:
                    patch.update(visibility_status='published',data_quality_status='complete')
                    for kind,model in ROW_MODELS.items():
                        model.objects.bulk_create([model(event=event,**{
                            **row,'source_refs':{**row.get('source_refs',{}),STAMP:stamp}}) for row in entry[kind]])
            for key,value in patch.items():
                setattr(event,key,value)
            event.save(update_fields=[*patch,'updated_at'])
            for target_entry in entry['targets']:
                target = targets[target_entry['id']]
                target_patch = dict(target_entry['before'])
                if mode == 'apply':
                    target_patch['source_refs'] = {**target_patch['source_refs'],STAMP:stamp}
                    if entry['mode'] == 'cancel':
                        target_patch['expectation_status'] = 'cancelled'
                    else:
                        target_patch['resolution_status'] = 'imported'
                        target_patch['module_statuses'] = {**target_patch['module_statuses'],'runners':'complete','results':'complete'}
                for key,value in target_patch.items():
                    setattr(target,key,value)
                target.save(update_fields=[*target_patch,'updated_at'])
        if mode == 'apply':
            rows = {kind:list(model.objects.filter(event_id__in=ids).order_by('pk').values()) for kind,model in ROW_MODELS.items()}
            report['after'] = _snapshot(events,targets,rows)
        m.OperationLog.objects.create(action_type=ACTION+('_restore' if mode=='restore' else ''),
            target_type='manifest',target_id=expected_sha256,detail=json.dumps(report,cls=DjangoJSONEncoder,ensure_ascii=False))
        return {k:v for k,v in report.items() if k != 'after'}


def _target_snapshot(target):
    return {key:getattr(target,key) for key in TARGET_FIELDS}


def _snapshot(events,targets,rows):
    value = {'events':{str(pk):event_snapshot(e) for pk,e in events.items()},
             'targets':{str(pk):_target_snapshot(t) for pk,t in targets.items()},'rows':rows}
    return json.loads(json.dumps(value,cls=DjangoJSONEncoder))
