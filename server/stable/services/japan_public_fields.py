"""日本官方来源的公开字段合同；仅由已通过身份和发布校验的写入链路调用。"""
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import re
from django.conf import settings
from stable import models
from .race_data_sync_policy import source_priority


def japan_source(source):
    return (source.source_key, source.region_code) in {('jra', 'japan_jra'), ('nar', 'japan_nar')}


def result_popularity(provenance):
    raw = str((provenance.get('source_fields') or {}).get('popularity') or '').strip()
    return raw if re.fullmatch(r'[1-9]\d?', raw) else ''


def fill_result_time(*, event, observation, revision, now, time_evidence=None):
    """官方完整赛果只补缺失时间，已有冲突及人工锁均保留；调用方持有赛事行锁。"""
    source = observation.source_identity
    if (not japan_source(source) or event.country_region != 'japan'
        or not settings.RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED
        or not {'off_time', 'local_start_time', 'timezone_name'}.issubset(settings.RACE_DATA_SYNC_ENABLED_FIELDS)):
        return False
    evidence = time_evidence or observation.field_provenance.get('time_evidence') or {}
    try:
        stamp = datetime.fromisoformat(evidence.get('off_time') or observation.normalized_payload.get('off_time') or '')
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return False
        local = stamp.astimezone(ZoneInfo('Asia/Tokyo'))
    except (TypeError, ValueError):
        return False
    if local.date() != event.local_date:
        return False
    proposed = dict(race_datetime=stamp, local_start_time=local.time().replace(tzinfo=None), timezone_name='Asia/Tokyo')
    if any(getattr(event, k) not in (None, '', v) for k, v in proposed.items()):
        return False
    locks = event.manual_lock_flags or {}
    fields = set(proposed) | {'basic', 'race_time', 'off_time', 'local_date'}
    if any(locks.get(k) for k in fields) or event.field_authorities.filter(
        subject_type='event', field_name__in=fields, manual_lock=True).exists():
        return False
    source_url = evidence.get('url') or observation.field_provenance.get('source_url') or source.canonical_url
    source_class = observation.field_provenance.get('source_class', '')
    changed = []
    for field, value in proposed.items():
        old = getattr(event, field)
        if old == value:
            continue
        rendered = value.isoformat() if hasattr(value, 'isoformat') else value
        authority, _ = models.RaceEventFieldAuthority.objects.get_or_create(
            event=event, subject_type='event', subject_key=str(event.pk), field_name=field)
        authority.source_key = source.source_key
        authority.source_class = source_class
        authority.authority_level = source_priority(source_class)
        authority.source_url = source_url
        authority.observed_at = observation.observed_at
        authority.revision = revision
        authority.value_sha256 = hashlib.sha256(json.dumps(rendered).encode()).hexdigest()
        authority.save()
        models.RaceEventFieldChange.objects.create(event=event, subject_type='event', subject_key=str(event.pk),
            field_name=field, old_value=old.isoformat() if hasattr(old, 'isoformat') else old,
            new_value=rendered, source_key=source.source_key, source_url=source_url,
            source_class=source_class, authority_level=authority.authority_level,
            observation=observation, revision=revision, decision='applied', applied=True,
            raw_sha256=evidence.get('sha256') or observation.raw_sha256,
            trigger_task='japan_result_public_fields')
        setattr(event, field, value)
        changed.append(field)
    if changed:
        event.save(update_fields=(*changed, 'updated_at'))
    return bool(changed)
