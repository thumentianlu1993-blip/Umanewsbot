"""固定法国发布包内的旧登记交接；普通自动发现不调用此入口。"""
import json

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
    if before != expected:
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
