"""一次性TRA历史补采合同和请求前持久占用；不联网、不授予业务准入。"""
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat

_SHA = re.compile(r'[0-9a-f]{64}')
_CODE = re.compile(r'[0-9a-f]{40}')
_FIELDS = {'schema_version', 'purpose', 'code_sha', 'issued_at', 'expires_at',
           'endpoint', 'max_requests', 'receipt_directory', 'entries'}
_ENTRY_FIELDS = {'event_id', 'source_id', 'provider', 'identity_namespace',
                 'external_race_id', 'region', 'local_date', 'owner_generation',
                 'enrollment_generation', 'standing_policy_sha256',
                 'registry_sha256', 'route_sha256'}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('historical_manifest_duplicate_key')
        result[key] = value
    return result


def _receipt_directory(value):
    directory = Path(value)
    if (not directory.is_absolute() or '..' in directory.parts or directory.is_symlink()
            or not directory.is_dir()):
        raise ValueError('historical_receipt_directory_invalid')
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('historical_receipt_directory_not_private')
    return directory


def validate_manifest(*, raw, expected_sha256, expected_code_sha, now, receipt_directory):
    if (not isinstance(raw, bytes) or len(raw) > 65536
            or not isinstance(expected_sha256, str) or not _SHA.fullmatch(expected_sha256)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise ValueError('historical_manifest_digest_mismatch')
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError('historical_manifest_schema_invalid')
    if (type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['purpose'] != 'historical_result_backfill' or value['endpoint'] != 'result_by_id'
            or not isinstance(expected_code_sha, str) or not _CODE.fullmatch(expected_code_sha)
            or value['code_sha'] != expected_code_sha):
        raise ValueError('historical_manifest_scope_invalid')
    issued = datetime.fromisoformat(value['issued_at'])
    expires = datetime.fromisoformat(value['expires_at'])
    if (now.utcoffset() is None or issued.utcoffset() is None or expires.utcoffset() is None
            or not issued <= now < expires or not timedelta(0) < expires-issued <= timedelta(minutes=30)):
        raise ValueError('historical_manifest_expired')
    directory = _receipt_directory(receipt_directory)
    if value['receipt_directory'] != str(directory):
        raise ValueError('historical_receipt_directory_mismatch')
    entries = value['entries']
    if (not isinstance(entries, list) or not 1 <= len(entries) <= 19
            or type(value['max_requests']) is not int or value['max_requests'] != len(entries)):
        raise ValueError('historical_request_budget_invalid')
    event_ids, source_ids = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise ValueError('historical_entry_schema_invalid')
        for field in ('event_id', 'source_id', 'owner_generation', 'enrollment_generation'):
            if type(entry[field]) is not int or entry[field] <= 0:
                raise ValueError('historical_entry_identity_invalid')
        if entry['provider'] != 'the_racing_api':
            raise ValueError('historical_provider_invalid')
        for field in ('identity_namespace', 'external_race_id', 'region'):
            if not isinstance(entry[field], str) or not entry[field] or len(entry[field]) > 255:
                raise ValueError('historical_entry_identity_invalid')
        if date.fromisoformat(entry['local_date']) >= now.date():
            raise ValueError('historical_entry_date_invalid')
        for field in ('standing_policy_sha256', 'registry_sha256', 'route_sha256'):
            if not isinstance(entry[field], str) or not _SHA.fullmatch(entry[field]):
                raise ValueError('historical_entry_digest_invalid')
        if entry['event_id'] in event_ids or entry['source_id'] in source_ids:
            raise ValueError('historical_entry_duplicate')
        event_ids.add(entry['event_id'])
        source_ids.add(entry['source_id'])
    return value


def reserve_request(manifest, *, manifest_sha256, event_id, receipt_directory):
    """接收已核验合同；每条请求O_EXCL占用，未知结果也不自动重发。

    调用方仍须在网络前复核来源许可/身份/generation，并使用既有transport预算。
    """
    directory = _receipt_directory(receipt_directory)
    if (manifest['receipt_directory'] != str(directory) or not isinstance(manifest_sha256, str)
            or not _SHA.fullmatch(manifest_sha256) or type(event_id) is not int
            or event_id not in {entry['event_id'] for entry in manifest['entries']}):
        raise ValueError('historical_request_outside_manifest')
    filename = manifest_sha256 + '-' + str(event_id) + '.json'
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
        except FileExistsError:
            raise ValueError('historical_request_already_reserved') from None
        with os.fdopen(fd, 'w') as out:
            json.dump({'manifest_sha256': manifest_sha256, 'event_id': event_id,
                       'status': 'reserved_outcome_unknown'}, out)
            out.flush()
            os.fsync(out.fileno())
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return directory / filename


def validate_live_entry(manifest, *, event_id, current):
    """网络前比对实时DB/许可快照；current必须由既有admission和DB生成。"""
    entries = [entry for entry in manifest['entries'] if entry['event_id'] == event_id]
    if len(entries) != 1 or current.get('entry') != entries[0]:
        raise ValueError('historical_live_identity_drift')
    if (current.get('authority_version') != 1 or current.get('enrollment_state') != 'enrolled'
            or current.get('write_owner') != 'data_sync' or current.get('manual_blocked') is not False
            or current.get('admitted') is not True):
        raise ValueError('historical_live_admission_rejected')
    return entries[0]


def read_live_entry(*, event_id, now):
    """读取既有业务准入及DB身份；不得以冻结名单替代当前权限。"""
    from stable import models
    from stable.services.race_data_sync_admission import validate_data_sync_lifecycle_admission
    from stable.services.race_data_sync_control import resolve_source_route_admission

    tracking = models.RaceEventLiveTracking.objects.filter(event_id=event_id).first()
    if tracking and tracking.active_attempt_token and (
            tracking.claim_expires_at is None or tracking.claim_expires_at > now):
        raise ValueError('historical_target_claim_active')
    decision = validate_data_sync_lifecycle_admission(event_id=event_id, now=now)
    if not decision.admitted:
        raise ValueError('historical_live_admission_rejected')
    event, enrollment, source = decision.event, decision.enrollment, decision.source
    if (enrollment is None or enrollment.authority_version != 1 or source is None
            or event is None or event.local_date is None
            or source.event_id != event_id or source.source_key != 'the_racing_api'):
        raise ValueError('historical_live_identity_drift')
    projection = models.RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    if (projection is None or projection.write_owner != 'data_sync'
            or projection.owner_generation != enrollment.projection_owner_generation
            or projection.owner_manifest_sha256 != enrollment.manifest_sha256):
        raise ValueError('historical_live_owner_drift')
    reason, route = resolve_source_route_admission(
        source=source, route_digest=enrollment.route_digest, data_kinds=('result',), now=now)
    if reason or route is None:
        raise ValueError('historical_live_route_rejected')
    current = {
        'entry': {
            'event_id': event.pk, 'source_id': source.pk, 'provider': source.source_key,
            'identity_namespace': source.identity_namespace,
            'external_race_id': source.external_race_id, 'region': source.region_code,
            'local_date': event.local_date.isoformat(),
            'owner_generation': projection.owner_generation,
            'enrollment_generation': enrollment.enrollment_generation,
            'standing_policy_sha256': enrollment.standing_policy_digest,
            'registry_sha256': source.registry_digest, 'route_sha256': enrollment.route_digest,
        },
        'authority_version': enrollment.authority_version, 'enrollment_state': enrollment.state,
        'write_owner': projection.write_owner,
        'manual_blocked': bool(event.manual_lock_flags and any(event.manual_lock_flags.values()))
            or bool(decision.control is None or decision.control.manual_pause_reason),
        'admitted': True,
    }
    return current, route


def prepare_request(*, raw, expected_sha256, expected_code_sha, now,
                    receipt_directory, event_id):
    """按合同、实时业务准入、单次占用顺序完成请求准备；不发网络请求。"""
    manifest = validate_manifest(
        raw=raw, expected_sha256=expected_sha256, expected_code_sha=expected_code_sha,
        now=now, receipt_directory=receipt_directory)
    if type(event_id) is not int or event_id not in {entry['event_id'] for entry in manifest['entries']}:
        raise ValueError('historical_request_outside_manifest')
    current, route = read_live_entry(event_id=event_id, now=now)
    validate_live_entry(manifest, event_id=event_id, current=current)
    receipt = reserve_request(manifest, manifest_sha256=expected_sha256,
                              event_id=event_id, receipt_directory=receipt_directory)
    return manifest, route, receipt


def read_locked_live_entry(*, event_id, now):
    """网络后事务内重读；显式锁住冻结字段所属行，再复用正常准入。"""
    from django.db import transaction
    from stable import models

    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('historical_apply_requires_transaction')
    from stable.services.race_event_lifecycle_enforce import (
        acquire_registry_shared_advisory_lock, lock_current_runtime_registry_membership,
    )
    acquire_registry_shared_advisory_lock()
    # 若标准writer会读取legacy membership，先锁membership以维持全局顺序。
    if models.RaceEventLifecycleEnforceMembership.objects.filter(
            event_id=event_id, state='active', registry__state='active',
            registry__is_active=True, registry__runtime_valid_until__gt=now).exists():
        lock_current_runtime_registry_membership(event_id=event_id, now=now)
    # registry -> lifecycle -> event -> projection -> tracking -> enrollment -> source。
    models.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=event_id).first()
    models.RaceEvent.objects.select_for_update().filter(pk=event_id).first()
    models.RaceEventProjectionControl.objects.select_for_update().filter(event_id=event_id).first()
    models.RaceEventLiveTracking.objects.select_for_update().filter(event_id=event_id).first()
    enrollment = models.RaceDataSyncEnrollment.objects.select_for_update().filter(event_id=event_id).first()
    if enrollment is None or enrollment.authority_version != 1:
        raise ValueError('historical_live_identity_drift')
    models.RaceResultSourceIdentity.objects.select_for_update().filter(pk=enrollment.source_identity_id).first()
    return read_live_entry(event_id=event_id, now=now)


def apply_response(*, raw, expected_sha256, expected_code_sha, receipt_directory,
                   event_id, now, response, raw_sha256, result_url, clock=None):
    """下载后按新时钟重验合同与锁定身份，再使用共享标准writer。"""
    from django.db import transaction
    from stable import models
    from stable.services import race_data_sync_providers as provider
    from stable.services.race_data_sync_repair import verify_stalled_event_repair
    from django.utils import timezone
    clock = clock or timezone.now

    manifest = validate_manifest(raw=raw, expected_sha256=expected_sha256,
        expected_code_sha=expected_code_sha, now=now, receipt_directory=receipt_directory)
    if response.get('_not_found') is True:
        return 'provider_not_found'
    snapshot = provider.parse_the_racing_api_live_results_payload({'results': [response]})
    with transaction.atomic():
        read_locked_live_entry(event_id=event_id, now=now)
        now = clock()
        manifest = validate_manifest(raw=raw, expected_sha256=expected_sha256,
            expected_code_sha=expected_code_sha, now=now, receipt_directory=receipt_directory)
        current, route = read_live_entry(event_id=event_id, now=now)
        entry = validate_live_entry(manifest, event_id=event_id, current=current)
        normalized = next((race for race in snapshot.races
                           if race['external_race_id'] == entry['external_race_id']), None)
        if normalized is None:
            raise ValueError('historical_result_identity_mismatch')
        flags = provider.RaceDataSyncFlags.from_settings()
        if not (flags.result_apply_enabled and flags.result_public_enabled):
            raise ValueError('historical_result_apply_disabled')
        decision = provider._record_and_apply_the_racing_api_result(
            normalized_race=normalized,
            normalized_status=str(normalized.get('race_status') or '').strip().casefold(),
            event=models.RaceEvent.objects.get(pk=event_id),
            source=models.RaceResultSourceIdentity.objects.get(pk=entry['source_id']),
            route=route, raw_sha256=raw_sha256, result_url=result_url,
            detail_reason='historical_result_backfill', flags=flags, now=now,
        )
        if not decision.projected:
            raise ValueError('historical_result_not_projected')
        reason = verify_stalled_event_repair(event_id=event_id, revision_id=decision.revision_id, now=now)
        if reason:
            raise ValueError('historical_public_verification_' + reason)
    return 'projected'


def _write_private_artifact(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(value, out, ensure_ascii=False, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def execute_request(*, raw, expected_sha256, expected_code_sha, receipt_directory,
                    event_id, clock=None, transport=None, sleeper=None):
    """一次请求，无自动重试；下载材料先落盘，再进行独立事务投影。"""
    import time
    from django.conf import settings
    from django.utils import timezone
    from stable import models
    from stable.services import race_data_sync_providers as provider

    clock = clock or timezone.now
    transport = transport or provider.the_racing_api_transport
    sleeper = sleeper or time.sleep
    if getattr(settings, 'RACE_DATA_SYNC_ALLOW_NETWORK', False) is not True:
        raise ValueError('historical_network_disabled')
    require_result_write_flags()
    args = dict(raw=raw, expected_sha256=expected_sha256, expected_code_sha=expected_code_sha,
                receipt_directory=receipt_directory)
    now = clock()
    manifest = validate_manifest(**args, now=now)
    current, route = read_live_entry(event_id=event_id, now=now)
    entry = validate_live_entry(manifest, event_id=event_id, current=current)
    registry, digest = provider.read_the_racing_api_automation_registry(
        registry_file=settings.RACE_LIVE_TRA_REGISTRY_FILE,
        expected_registry_sha256=route.proof_digest, now=now)
    if digest != route.proof_digest:
        raise ValueError('historical_registry_drift')
    source = models.RaceResultSourceIdentity.objects.get(pk=entry['source_id'])
    event = models.RaceEvent.objects.get(pk=event_id)
    region = provider._registry_region(event_region=event.country_region, contract_region=source.region_code)
    username, password = provider._read_secret(settings.RACE_LIVE_TRA_SECRET_ENV_FILE)
    provider.ensure_race_live_host_budget_floor(
        host=provider._HOST, minimum_interval_ms=route.minimum_interval_seconds * 1000)
    require_result_write_flags()
    _, _, receipt = prepare_request(**args, event_id=event_id, now=clock())

    def guarded_transport(**kwargs):
        # _fetch_json在host等待结束后才调用transport；此时重新检查，不使用准备阶段时钟。
        request_now = clock()
        fresh_manifest = validate_manifest(**args, now=request_now)
        require_result_write_flags()
        fresh_current, fresh_route = read_live_entry(event_id=event_id, now=request_now)
        validate_live_entry(fresh_manifest, event_id=event_id, current=fresh_current)
        provider.read_the_racing_api_automation_registry(
            registry_file=settings.RACE_LIVE_TRA_REGISTRY_FILE,
            expected_registry_sha256=fresh_route.proof_digest, now=request_now)
        return transport(**kwargs)

    try:
        url, response, response_sha = provider._fetch_the_racing_api_result_by_id(
            registry=registry, source=source, provider_region=region, transport=guarded_transport,
            username=username, password=password, now=clock(), clock=clock, sleeper=sleeper)
        _write_private_artifact(receipt.with_suffix('.response.json'), {
            'event_id': event_id, 'manifest_sha256': expected_sha256,
            'source_url': url, 'raw_sha256': response_sha, 'response': response})
        status = apply_response(**args, event_id=event_id, now=clock(),
                                response=response, raw_sha256=response_sha, result_url=url, clock=clock)
    except BaseException as exc:
        _write_private_artifact(receipt.with_suffix('.outcome.json'), {
            'event_id': event_id, 'status': 'failed_or_unknown', 'error_type': type(exc).__name__})
        raise
    _write_private_artifact(receipt.with_suffix('.outcome.json'), {'event_id': event_id, 'status': status})
    return status


def require_result_write_flags():
    from django.conf import settings
    if not (getattr(settings, 'RACE_DATA_SYNC_RESULT_APPLY_ENABLED', False) is True
            and getattr(settings, 'RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED', False) is True):
        raise ValueError('historical_result_apply_disabled')
