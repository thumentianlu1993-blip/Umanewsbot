"""对精确来源清单收口 2025 年英美历史目录；不联网、不自动猜测身份。"""
import hashlib
import json
from datetime import date
from pathlib import Path

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from stable import models as m
from .historical_race_calendar_admission import assert_historical_calendar_write_admitted
from .race_event_public_cache import invalidate_public_race_cache

ACTION = 'reconcile_historical_targets'
STAMP = 'historical_target_reconciliation'
PATCH_FIELDS = {'local_date', 'race_datetime', 'local_start_time', 'timezone_name',
                'grade_text', 'normalized_grade', 'distance_text', 'surface', 'eligibility_text'}
ROW_MODELS = {'runners': m.RaceEventRunner, 'results': m.RaceEventResult}


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True))


def _snapshot(obj):
    return _json({f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields
                  if f.name not in {'created_at', 'updated_at'}})


event_snapshot = target_snapshot = series_snapshot = _snapshot


def row_snapshot(event_id):
    return {kind: [_snapshot(x) for x in model.objects.filter(event_id=event_id).order_by('pk')]
            for kind, model in ROW_MODELS.items()}


def _state(events, targets):
    return {'events': {str(pk): _snapshot(e) for pk, e in events.items()},
            'targets': {str(pk): _snapshot(t) for pk, t in targets.items()},
            'rows': {str(pk): row_snapshot(pk) for pk in events}}


def _set_fields(obj, values):
    for key, value in values.items():
        field = obj._meta.get_field(key.removesuffix('_id') if key.endswith('_id') else key)
        setattr(obj, key, field.to_python(value) if not field.is_relation else value)
    # save() 的派生字段逻辑使用关系字段名，而不是数据库 attname。
    names = [obj._meta.get_field(k.removesuffix('_id') if k.endswith('_id') else k).name for k in values]
    obj.save(update_fields=[*names, 'updated_at'])
    obj.refresh_from_db()


def _validate_manifest(data, root):
    entries = data.get('entries', [])
    if (data.get('schema_version') != 1 or data.get('action') != ACTION or not 1 <= len(entries) <= 11
            or len({x['target_id'] for x in entries}) != len(entries)
            or len({x['event_id'] for x in entries}) != len(entries)):
        raise ValueError('manifest_scope')
    for e in entries:
        if e['action'] not in {'attach_results', 'cancelled', 'not_held', 'recover_results', 'complete_results'}:
            raise ValueError('action_scope')
        before, target = e['event_before'], e['target_before']
        if (before['id'] != e['event_id'] or target['id'] != e['target_id']
                or before['year'] != 2025 or target['year'] != 2025
                or (before['edition_year'] or before['year']) != 2025
                or before['country_region'] not in {'united_kingdom', 'united_states'}
                or before['country_region'] != target['country_region']
                or e['series_before']['id'] != target['race_series_id']
                or e['series_before']['country_region'] != target['country_region']):
            raise ValueError('identity_scope')
        if target['event_id'] is not None or target['resolution_status'] != 'pending' or target['expectation_status'] != 'held':
            raise ValueError('target_not_pending')
        if before['race_series_id'] not in {None, target['race_series_id']}:
            raise ValueError('event_series_conflict')
        if set(e['event_patch']) - PATCH_FIELDS or (e['action'] not in {'recover_results', 'cancelled'} and e['event_patch']):
            raise ValueError('event_patch_scope')
        if 'local_date' in e['event_patch'] and date.fromisoformat(e['event_patch']['local_date']).year != 2025:
            raise ValueError('patch_date_year')
        if not e['reason'] or not e['sources']:
            raise ValueError('source_missing')
        for source in e['sources']:
            path = (root / source['path']).resolve()
            if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                raise ValueError('source_digest')
            if not source['url'].startswith(('https://', 'nsa_official_pdf:sha256/')):
                raise ValueError('source_url')
        if e['action'] == 'recover_results':
            if before['status'] != 'cancelled' or before['visibility_status'] != 'draft' or any(e['rows_before'].values()):
                raise ValueError('recover_not_empty_cancelled')
            if 'local_date' not in e['event_patch']:
                raise ValueError('recovery_date_missing')
            runners, results = e['runners'], e['results']
            roster = lambda rows: [(x['horse_number'], x['horse_name']) for x in rows]
            if (not results or len(results) != e['expected_starters'] or len(runners) != len(results)
                    or len(set(x['horse_number'] for x in runners)) != len(runners)):
                raise ValueError('runner_count')
            if (sorted(roster(runners)) != sorted(roster(results))
                    or sorted(x['official_finish_position'] for x in results) != list(range(1, len(results)+1))
                    or any(x.get('is_confirmed') is not True or x['running_status'] != 'finished' for x in results)):
                raise ValueError('result_roster')
            for kind, rows in [('runners', runners), ('results', results)]:
                allowed = {f.name for f in ROW_MODELS[kind]._meta.concrete_fields} - {'id','event','created_at','updated_at'}
                if any(set(row) - allowed for row in rows):
                    raise ValueError('row_fields')
        elif e['action'] == 'complete_results':
            if e['runners'] or not e['results']:
                raise ValueError('supplement_rows')
            prior = {(row['horse_number'], row['horse_name']): row for row in e['rows_before']['runners']}
            changes = {row['id']: row['running_status'] for row in e['runner_statuses']}
            expected_changes = {}
            for row in e['results']:
                original = prior.get((row['horse_number'], row['horse_name']))
                status = {'PU': 'pulled_up', 'F': 'fell'}.get(original['source_refs'].get('official_order_text')) if original else None
                if (not status or row['running_status'] != status or row.get('official_finish_position') is not None
                        or row.get('reported_finish_position') is not None or row.get('is_confirmed') is not True):
                    raise ValueError('supplement_source_status')
                expected_changes[original['id']] = status
            if changes != expected_changes or len(changes) != len(e['runner_statuses']):
                raise ValueError('supplement_runner_status')
            allowed = {f.name for f in m.RaceEventResult._meta.concrete_fields} - {'id','event','created_at','updated_at'}
            if any(set(row) - allowed for row in e['results']):
                raise ValueError('row_fields')
        elif e['runners'] or e['results']:

            raise ValueError('unexpected_new_rows')
    return entries


def execute(path, expected_sha256, *, mode='dry-run'):
    path = Path(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('manifest_digest')
    if mode not in {'dry-run', 'apply', 'restore'}:
        raise ValueError('mode')
    entries = _validate_manifest(json.loads(raw), path.parent)
    ids = sorted(e['event_id'] for e in entries)
    tids = sorted(e['target_id'] for e in entries)
    with transaction.atomic():
        assert_historical_calendar_write_admitted()
        events = {e.pk: e for e in m.RaceEvent.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
        targets = {t.pk: t for t in m.HistoricalRaceEventTarget.objects.select_for_update().filter(pk__in=tids).order_by('pk')}
        series = {s.pk: s for s in m.RaceSeries.objects.select_for_update().filter(pk__in=[e['series_before']['id'] for e in entries]).order_by('pk')}
        if set(events) != set(ids) or set(targets) != set(tids):
            raise ValueError('missing_identity')
        for model in ROW_MODELS.values():
            locked_rows = list(model.objects.select_for_update().filter(event_id__in=ids).order_by('pk'))
            if any(getattr(row,'manual_lock_flags',{}) for row in locked_rows):
                raise ValueError('runner_manual_lock')
        if (any(e.manual_lock_flags for e in events.values())
                or any(s.manual_lock_flags for s in series.values())
                or m.RaceEventFieldAuthority.objects.select_for_update().filter(event_id__in=ids, manual_lock=True).exists()):
            raise ValueError('manual_lock')
        if (m.RaceDataSyncEnrollment.objects.filter(event_id__in=ids).exists()
                or m.RaceEventProjectionControl.objects.filter(event_id__in=ids).exclude(write_owner='historical').exists()):
            raise ValueError('live_owner')
        if m.HistoricalRaceEventTarget.objects.filter(event_id__in=ids).exclude(pk__in=tids).exists():
            raise ValueError('existing_target_binding')
        receipt = m.OperationLog.objects.filter(action_type=ACTION,target_type='manifest',target_id=expected_sha256).first()
        restored = m.OperationLog.objects.filter(action_type=ACTION+'_restore',target_type='manifest',target_id=expected_sha256).exists()
        state = _state(events, targets)
        if restored:
            if mode != 'restore':
                raise ValueError('already_restored')
            if state != json.loads(receipt.detail)['before']:
                raise ValueError('restore_after_drift')
            return dict(mode=mode,replay=True,events=len(ids))
        if receipt:
            if state != json.loads(receipt.detail)['after']:
                raise ValueError('after_drift')
        else:
            if mode == 'restore':
                raise ValueError('missing_receipt')
            for entry in entries:
                event, target = events[entry['event_id']], targets[entry['target_id']]
                if (_snapshot(event) != entry['event_before'] or _snapshot(target) != entry['target_before']
                        or _snapshot(series[target.race_series_id]) != entry['series_before']
                        or row_snapshot(event.pk) != entry['rows_before']):
                    raise ValueError('before_cas')
                rows = entry['rows_before']
                if entry['action'] in {'attach_results', 'complete_results'}:
                    # 旧来源可含已退赛但状态未规范化的行，按审核过的非出走名单核对。
                    key = lambda row: (row['horse_number'], row['horse_name'])
                    runners = [key(row) for row in rows['runners']]
                    results = [key(row) for row in rows['results'] + entry['results']]
                    nonstarters = [tuple(row) for row in entry.get('nonstarters', [])]
                    for row in rows['runners']:
                        if key(row) in nonstarters and (row['source_refs'].get('official_order_text') in {'PU','F','UR','BD','RO','DSQ'}
                                or row['running_status'] in {'pulled_up','fell','did_not_finish','unseated','disqualified'}):
                            raise ValueError('nonstarter_is_nonfinisher')
                    if (len(results) != entry['expected_starters']
                            or len(runners) != entry['expected_runners']
                            or len(set(runners)) != len(runners)
                            or len(set(results)) != len(results)
                            or sorted(results + nonstarters) != sorted(runners)):
                        raise ValueError('existing_roster_incomplete')
                    if (event.status != 'finished' or event.visibility_status != 'published' or not event.local_date
                            or not rows['results'] or any(not r['is_confirmed'] for r in rows['results'])
                            or not any(r['official_finish_position'] == 1 for r in rows['results'])):
                        raise ValueError('existing_results_not_confirmed')
                elif entry['action'] in {'not_held','cancelled'}:
                    if event.status != 'cancelled' or event.visibility_status != 'draft' or any(rows.values()):
                        raise ValueError('not_held_has_rows')
        report = dict(mode=mode,manifest_sha256=expected_sha256,events=len(ids),replay=bool(receipt))
        if mode == 'dry-run' or (receipt and mode == 'apply'):
            return report
        if mode == 'restore':
            saved = json.loads(receipt.detail)['before']
            original_ids = {kind: [row['id'] for rows in saved['rows'].values() for row in rows[kind]] for kind in ROW_MODELS}
            result_ids = list(m.RaceEventResult.objects.filter(event_id__in=ids).exclude(pk__in=original_ids['results']).values_list('pk',flat=True))
            runner_ids = list(m.RaceEventRunner.objects.filter(event_id__in=ids).exclude(pk__in=original_ids['runners']).values_list('pk',flat=True))
            if m.HorseRaceRecord.objects.filter(result_id__in=result_ids).exists():
                raise ValueError('career_reference')
            if m.HorseP0Source.objects.filter(Q(race_result_id__in=result_ids)|Q(race_runner_id__in=runner_ids)).exists():
                raise ValueError('source_reference')
            for kind, model in ROW_MODELS.items():
                model.objects.filter(pk__in=result_ids if kind=='results' else runner_ids).delete()
                for rows in saved['rows'].values():
                    for before_row in rows[kind]:
                        obj=model.objects.get(pk=before_row['id'])
                        patch={k:v for k,v in before_row.items() if k!='id' and _snapshot(obj).get(k)!=v}
                        if patch:_set_fields(obj,patch)
            saved = json.loads(receipt.detail)['before']
            for pk,event in events.items():
                before = saved['events'][str(pk)]
                _set_fields(event,{k:v for k,v in before.items() if k != 'id' and _snapshot(event).get(k) != v})
            for pk,target in targets.items():
                before = saved['targets'][str(pk)]
                _set_fields(target,{k:v for k,v in before.items() if k != 'id' and _snapshot(target).get(k) != v})
            if _state(events, targets) != saved:
                raise ValueError('restore_verification')
            m.OperationLog.objects.create(action_type=ACTION+'_restore',target_type='manifest',target_id=expected_sha256,detail=json.dumps(report))
        else:
            before = state
            for entry in entries:
                event, target = events[entry['event_id']], targets[entry['target_id']]
                action = entry['action']
                stamp = {'manifest_sha256':expected_sha256,'sources':entry['sources'],'reason':entry['reason']}
                refs = {**event.source_refs, **entry['source_patch'], STAMP:stamp}
                # 原错误断言移入审计收据，不再作为当前有效来源。
                if action == 'recover_results':
                    refs.pop('not_held_evidence',None);refs.pop('review',None)
                patch = {**entry['event_patch'],'source_refs':refs}
                if action != 'not_held':
                    patch['race_series_id'] = target.race_series_id
                if action in {'recover_results', 'complete_results'}:
                    patch.update(status='finished',visibility_status='published',data_quality_status='complete',result_confirmed_at=timezone.now())
                    for kind,model in ROW_MODELS.items():
                        model.objects.bulk_create([model(event=event,**{**row,'source_refs':{**row.get('source_refs',{}),STAMP:stamp}}) for row in entry[kind]])
                if action == 'complete_results':
                    for row in entry['runner_statuses']:
                        runner=m.RaceEventRunner.objects.get(pk=row['id'],event=event)
                        if runner.manual_lock_flags:raise ValueError('runner_manual_lock')
                        _set_fields(runner,{'running_status':row['running_status']})
                _set_fields(event,patch)
                completed = action in {'attach_results','recover_results','complete_results'}
                tp = dict(event_id=None if action=='not_held' else event.pk,
                          expectation_status='held' if completed else action,
                          resolution_status='imported' if completed else 'ready',
                          source_refs={**target.source_refs,STAMP:stamp},notes=entry['reason'],last_checked_at=timezone.now(),
                          module_statuses={**target.module_statuses,'runners':'complete' if completed else 'not_applicable','results':'complete' if completed else 'not_applicable'})
                if completed or action=='cancelled':
                    tp.update(local_date=event.local_date,grade_text=event.grade_text,normalized_grade=event.normalized_grade,distance_text=event.distance_text)
                for key,value in tp.items():setattr(target,key,value)
                target.clean()
                target.save(update_fields=[*tp,'updated_at'])
            m.OperationLog.objects.create(action_type=ACTION,target_type='manifest',target_id=expected_sha256,
                detail=json.dumps({'before':before,'after':_state(events,targets),'report':report},cls=DjangoJSONEncoder))
        transaction.on_commit(invalidate_public_race_cache)
        return report
