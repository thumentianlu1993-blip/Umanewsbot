"""法国赛前claim的受限写入上下文；与正式claim共享锁序及时间内核。"""
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from stable import models


@dataclass
class FrancePreRaceWriteClaim:
    event: object
    lifecycle: object
    control: object
    tracking: object
    enrollment: object
    guards: dict


def lock_context(event, lifecycle):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('france_claim_transaction_required')
    control = models.RaceEventProjectionControl.objects.select_for_update().filter(event=event).first()
    tracking = models.RaceEventLiveTracking.objects.select_for_update().filter(event=event).first()
    enrollment = models.RaceDataSyncEnrollment.objects.select_for_update().filter(event=event).first()
    def snapshot(obj, names):
        return {name:getattr(obj, name) for name in names} if obj else None
    guards = dict(
        projection=snapshot(control, ('pk', 'write_owner', 'owner_generation', 'owner_manifest_sha256')),
        enrollment=snapshot(enrollment, ('pk', 'state', 'authority_version', 'enrollment_generation',
            'source_set_generation', 'source_set_digest', 'standing_policy_digest', 'entry_sha256', 'manifest_sha256')),
        tracking=snapshot(tracking, ('pk', 'claim_generation')),
        lifecycle=snapshot(lifecycle, ('pk', 'mode', 'schedule_generation', 'manual_pause_reason')),
        policy_sha256=getattr(settings, 'RACE_DATA_MULTISOURCE_POLICY_SHA256', ''),
        release=getattr(settings, 'UMANEWS_RELEASE_COMMIT', ''))
    return FrancePreRaceWriteClaim(event, lifecycle, control, tracking, enrollment, guards)


def write_reason(context, *, now, route=None, capability='race_time'):
    """登记与未登记赛事分流；不借赛前token抢占活跃正式claim。"""
    event, control, enrollment = context.event, context.control, context.enrollment
    if control and control.write_owner not in {'unmanaged', 'data_sync'}:
        return 'writer_owner_conflict'
    if context.tracking and context.tracking.active_attempt_token and context.tracking.claim_expires_at and context.tracking.claim_expires_at > now:
        return 'formal_claim_active'
    if models.RaceEventLifecycleEnforceMembership.objects.filter(event=event, state='active',
        registry__state='active', registry__is_active=True, registry__runtime_valid_until__gt=now).exists():
        return 'lifecycle_authority_conflict'
    if enrollment is None:
        if control and control.write_owner != 'unmanaged':
            return 'enrollment_missing'
        if context.lifecycle and (context.lifecycle.manual_pause_reason or context.lifecycle.mode == 'enforce'):
            return 'lifecycle_authority_conflict'
        return ''
    if enrollment.authority_version != 2 or enrollment.state != 'enrolled':
        return 'enrollment_not_multisource'
    from .race_data_sync_admission import validate_multisource_admission
    decision = validate_multisource_admission(event_id=event.pk, now=now, capability=capability)
    if not decision.admitted:
        return decision.reason_code
    # 赛前来源必须是当前时间权威选定的来源，不能旁路另一选源合同。
    if route is not None and decision.route.digest != route.digest:
        return 'pre_race_time_source_not_selected'
    return ''


def apply_time(context, *, payload, url, page, route, candidate, now):
    from .france_sources import validate_event_identity
    from .race_data_sync_pipeline import _apply_schedule_fields_locked, RaceDataSyncFlags
    from .race_data_sync_policy import arbitrate_source_value
    event = context.event
    if not payload.get('off_time'):
        return ''
    reason = write_reason(context, now=now, route=route)
    if reason:
        return reason
    if not route.permits_url(url) or route.region != 'france' or route.provider not in {'geny', 'france_galop'}:
        return 'france_time_source'
    try:
        validate_event_identity(payload, event, route)
        stamp = datetime.fromisoformat(payload['off_time'].replace('Z', '+00:00'))
        if timezone.is_naive(stamp):
            return 'france_time_zone'
        local = stamp.astimezone(ZoneInfo('Europe/Paris'))
        if local.date() != event.local_date or local.hour == local.minute == 0:
            return 'france_time_invalid'
    except (KeyError, ValueError, TypeError):
        return 'france_time_identity'
    flags = RaceDataSyncFlags.from_settings()
    admitted = {'off_time', 'local_start_time', 'timezone_name'}
    if not flags.schedule_apply_enabled or not all(flags.allows(provider=route.provider, region='france', field_name=f) for f in admitted):
        return 'runtime_admission_closed'
    watermark = getattr(page, 'observed_at', None) or now
    if timezone.is_naive(watermark) or watermark > now:
        return 'france_observed_at_invalid'
    source_class = 'official_operator' if route.provider == 'france_galop' else 'trusted_publisher'
    # 三字段作为原子组；任意权限/旧值冲突都不产生混合时区时间。
    values = dict(race_datetime=stamp, local_start_time=local.time().replace(tzinfo=None), timezone_name='Europe/Paris')
    for name, value in values.items():
        authority = event.field_authorities.select_for_update().filter(subject_type='event', subject_key=str(event.pk), field_name=name).first()
        old = getattr(event, name)
        decision = arbitrate_source_value(current_source_key=authority.source_key if authority else '',
            current_source_class=authority.source_class if authority else '', current_observed_at=authority.observed_at if authority else None,
            candidate_source_key=route.provider, candidate_source_class=source_class, candidate_observed_at=watermark,
            has_current_value=old is not None and old != '', values_equal=old == value,
            manual_locked=bool((event.manual_lock_flags or {}).get(name) or authority and authority.manual_lock))
        if not decision.apply and decision.reason_code != 'idempotent_replay':
            return decision.reason_code
    source = SimpleNamespace(source_key=route.provider, canonical_url=url, external_race_id=str(payload.get('external_race_id', '')))
    audit = dict(source_key=route.provider, source_url=url, external_id=source.external_race_id,
        candidate=candidate, source_class=source_class, raw_sha256=getattr(page, 'raw_sha256', ''),
        normalized_sha256=candidate.raw_payload['france_pre_race_v1']['content_sha256'],
        registry_digest=route.digest, parser_version=getattr(route, 'parser_version', ''), operation_mode='france_pre_time')
    _apply_schedule_fields_locked(event=event, source=source,
        payload=dict(off_time=stamp.isoformat(), timezone_name='Europe/Paris', local_start_time=local.strftime('%H:%M:%S')),
        observation=None, lifecycle=context.lifecycle, locked_claim=context,
        admitted_fields=admitted, allow_schedule_apply=True, processed_fields=set(), audit=audit,
        candidate_watermark=watermark, candidate_source_class=source_class)
    return ''


def apply_basic(context, *, payload, route, candidate, now):
    from .france_basic_fields import apply_basic_locked, ALLOWED_FIELDS
    from .race_data_sync_pipeline import RaceDataSyncFlags
    flags = RaceDataSyncFlags.from_settings()
    admitted = {f for f in ALLOWED_FIELDS if flags.allows(provider=route.provider,region='france',field_name=f)}
    if not admitted or not (flags.schedule_apply_enabled or flags.racecard_apply_enabled):
        return {}
    reason = write_reason(context, now=now, route=route)
    if reason:
        return {'reason':reason}
    source = SimpleNamespace(source_key=route.provider, external_race_id=str(payload.get('external_race_id','')))
    return apply_basic_locked(event=context.event, basic=payload['france_basic_v1'], source=source,
        source_class='official_operator' if route.provider=='france_galop' else 'trusted_publisher',
        admitted_fields=admitted, audit=dict(candidate=candidate), now=now)
