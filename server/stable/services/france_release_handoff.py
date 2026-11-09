"""固定法国发布包内的旧登记交接；普通自动发现不调用此入口。"""
import json
import unicodedata

from stable import models


def control_snapshot(event, *, lock=False):
    """调用者先按 lifecycle → event 顺序锁定，再按登记链顺序获取控制行。"""
    value = {'event_id': event.pk}
    for key, model in [('projection', models.RaceEventProjectionControl),
                       ('tracking', models.RaceEventLiveTracking),
                       ('enrollment', models.RaceDataSyncEnrollment)]:
        query = model.objects.filter(event=event)
        if lock:
            query = query.select_for_update()
        value[key] = query.values().first()
    checkpoints = models.RaceEventLiveProviderCheckpoint.objects.filter(
        tracking__event=event).order_by('pk')
    if lock:
        checkpoints = checkpoints.select_for_update(of=('self',))
    value['checkpoints'] = list(checkpoints.values())
    value['lifecycle'] = models.RaceEventLifecycleControl.objects.filter(event=event).values().first()
    return json.loads(json.dumps(value, default=str))


def validate_handoff(event, expected):
    before = control_snapshot(event, lock=True)
    if before != {k:v for k,v in expected.items() if k != 'runner_crosswalk'}:
        raise ValueError('handoff_snapshot_drift')
    projection, enrollment, tracking = (before[k] for k in ('projection', 'enrollment', 'tracking'))
    if (event.country_region != 'france' or not all((projection, enrollment, tracking))
        or enrollment['authority_version'] != 1
        or (projection['write_owner'], enrollment['state']) not in (
            ('historical', 'retired'), ('data_sync', 'enrolled'))
        or enrollment['enrollment_generation'] > projection['owner_generation']
        or models.RaceDataSyncSourceBinding.objects.filter(enrollment_id=enrollment['id']).exists()):
        raise ValueError('handoff_legacy_state')
    lifecycle = before['lifecycle']
    if (tracking['active_attempt_token'] or tracking['claim_expires_at']
        or (lifecycle and (lifecycle['claim_token'] or lifecycle['claim_expires_at']))):
        raise ValueError('handoff_active_claim')
    if (any((event.manual_lock_flags or {}).values())
        or event.field_authorities.filter(manual_lock=True).exists()
        or (before['lifecycle'] and before['lifecycle']['manual_pause_reason'])):
        raise ValueError('manual_lock')
    return before


def record_handoff(event, *, before, manifest_sha256):
    models.OperationLog.objects.create(
        action_type='france_legacy_handoff', target_type='event', target_id=str(event.pk),
        detail=json.dumps({'manifest_sha256': manifest_sha256, 'before': before,
                           'after': control_snapshot(event)}, ensure_ascii=False))


def install_runner_crosswalk(event, source, observation, expected):
    """仅对固定交接包核验事件内名单：同马号且名称仅大小写/重音差异。"""
    from .race_data_source_adapters import canonical_sha
    runners = list(event.runners.select_for_update().order_by('pk'))
    crosswalk = expected.get('runner_crosswalk')
    if not runners and crosswalk is None:
        return
    rows = observation.get('roster', [])
    if (not isinstance(crosswalk, dict) or observation.get('roster_complete') is not True
        or crosswalk.get('source_external_race_id') != observation['external_race_id']
        or crosswalk.get('source_raw_sha256') != observation['raw_sha256']
        or not isinstance(crosswalk.get('runners'), dict)
        or len(rows) != len(runners) or len(crosswalk['runners']) != len(runners)
        or set(crosswalk['runners']) != {row['external_runner_id'] for row in rows}
        or set(crosswalk['runners'].values()) != {runner.pk for runner in runners}):
        raise ValueError('handoff_runner_crosswalk_scope')
    by_id = {runner.pk:runner for runner in runners}
    def name_key(value):
        return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value)
                               if not unicodedata.combining(c)).casefold().split())
    for row in rows:
        runner = by_id[crosswalk['runners'][row['external_runner_id']]]
        if (str(runner.horse_number) != str(row['number'])
            or not name_key(runner.horse_name) or name_key(runner.horse_name) != name_key(row['horse_name'])
            or any((runner.manual_lock_flags or {}).values())
            or runner.raw_payload.get('substitution') or row.get('field_provenance',{}).get('substitution')
            or (runner.barrier and row.get('barrier') and str(runner.barrier) != str(row['barrier']))
            or (runner.running_status in ('scratched','withdrawn','non_runner')
                and row['status'] not in ('scratched','withdrawn','non_runner'))):
            raise ValueError('handoff_runner_identity')
    value = dict(event_id=event.pk, evidence_sha256=canonical_sha(crosswalk), runners=crosswalk['runners'],
                 scope='france_legacy_handoff',
                 verified_names={row['external_runner_id']:[by_id[crosswalk['runners'][row['external_runner_id']]].horse_name,row['horse_name']]
                                 for row in rows})
    fields = dict(source.identity_fields or {})
    if fields.get('reviewed_runner_crosswalk') not in (None,value):
        raise ValueError('handoff_runner_crosswalk_drift')
    fields['reviewed_runner_crosswalk'] = value
    source.identity_fields = fields
    source.save(update_fields=('identity_fields','updated_at'))
