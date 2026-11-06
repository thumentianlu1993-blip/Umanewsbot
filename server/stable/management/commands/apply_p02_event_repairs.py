"""固定发布清单的未来赛事建档和时区修正；不发布、不抓取、不改变日期。"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from stable.models import HistoricalRaceEventTarget, RaceEvent, OperationLog
from stable.services.historical_race_batches import (materialize_scheduled_historical_event,
    materialization_snapshot, validate_historical_materialization, validate_materialized_historical_identity)
from stable.services.historical_race_inventory import InventoryValidationError
from stable.management.commands.register_p02_canonical_names import digest


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--expected-sha256', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        raw=Path(options['manifest']).read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if sha != options['expected_sha256']:raise CommandError('manifest_sha_mismatch')
        payload=json.loads(raw);actions=payload.get('actions',[])
        if payload.get('schema')!='p02-data-actions-v1' or not actions:
            raise CommandError('invalid_actions_manifest')
        keys=[(a.get('action'),a.get('target_id',a.get('event_id'))) for a in actions]
        if len(set(keys))!=len(keys):raise CommandError('duplicate_action')
        created=[]
        with transaction.atomic():
            receipt=OperationLog.objects.filter(action_type='p02_event_repairs_applied',target_type='manifest',target_id=sha).first()
            previous=json.loads(receipt.detail) if receipt else {}
            owned=previous.get('target_event_ids',{})
            for action in actions:
                pre=action['preconditions']
                if action['action']=='materialize_scheduled_historical_event':
                    target=HistoricalRaceEventTarget.objects.select_for_update().get(pk=action['target_id'])
                    for field in ('original_name','racecourse','local_date','expectation_status','resolution_status','race_series_id','artifact_sha256'):
                        if str(getattr(target,field))!=str(pre[field]):raise CommandError('target_snapshot_drift')
                    if (pre['event_id'] is not None or target.race_series.review_status!='approved'
                            or pre['race_series_review_status']!='approved'
                            or target.year!=2026 or target.local_date is None or target.local_date.year!=2026
                            or target.expectation_status!='not_due' or target.resolution_status!='source_unavailable'
                            or digest(target.source_refs)!=pre['source_refs_sha256']
                            or not target.local_date or target.local_date<=timezone.localdate()):
                        raise CommandError('target_not_materializable')
                    if digest(materialization_snapshot(target)) != pre.get('materialization_snapshot_sha256'):
                        raise CommandError('materialization_snapshot_drift')
                    try:
                        identity, slug = validate_historical_materialization(target, scheduled=True)
                    except InventoryValidationError as exc:
                        raise CommandError(str(exc)) from exc
                    if action.get('result')!={'status':'scheduled','visibility_status':'draft','coverage_status_unchanged':True}:
                        raise CommandError('unsupported_target_result')
                    if target.event_id:
                        if target.event_id!=owned.get(str(target.pk)):
                            raise CommandError('target_binding_drift')
                        event=RaceEvent.objects.select_for_update().get(pk=target.event_id)
                        try:
                            validate_materialized_historical_identity(event, target=target, identity=identity, slug=slug)
                        except InventoryValidationError as exc:
                            raise CommandError(str(exc)) from exc
                        if (event.race_series_id!=target.race_series_id or event.local_date!=target.local_date
                                or event.status!='scheduled' or event.visibility_status!='draft'
                                or event.original_name!=target.original_name or event.racecourse!=target.racecourse):
                            raise CommandError('materialized_event_drift')
                    elif receipt:
                        raise CommandError('recorded_target_binding_missing')
                    elif RaceEvent.objects.filter(race_series_id=target.race_series_id).filter(
                        Q(edition_year=2026)|Q(edition_year__isnull=True,year=2026)).exists():
                        raise CommandError('unexpected_existing_canonical_event')
                    elif options['apply']:
                        event=materialize_scheduled_historical_event(target)
                        if event is None or event.status!='scheduled' or event.visibility_status!='draft':
                            raise CommandError('unexpected_materialization_result')
                        created.append(event.pk);owned[str(target.pk)]=event.pk
                elif action['action']=='correct_timezone_name':
                    event=RaceEvent.objects.select_for_update().get(pk=action['event_id'])
                    for field in ('original_name','local_date','racecourse'):
                        if str(getattr(event,field))!=str(pre[field]):raise CommandError('timezone_event_identity_drift')
                    desired=action.get('set',{}).get('timezone_name')
                    if (set(action.get('set',{}))!={'timezone_name'} or pre['timezone_name']!='Asia/Shanghai'
                            or desired!={'france':'Europe/Paris','hong_kong':'Asia/Hong_Kong'}.get(event.country_region)):
                        raise CommandError('unsupported_timezone_correction')
                    expected=desired if receipt else pre['timezone_name']
                    if event.timezone_name!=expected:raise CommandError('timezone_precondition_drift')
                    if options['apply'] and not receipt:
                        event.timezone_name=desired;event.save(update_fields={'timezone_name','updated_at'})
                else:
                    raise CommandError('unsupported_action')
            if options['apply'] and not receipt:
                OperationLog.objects.create(action_type='p02_event_repairs_applied',target_type='manifest',target_id=sha,
                    detail=json.dumps({'target_event_ids':owned,'manifest_sha256':sha}))
        self.stdout.write(json.dumps({'manifest_sha256':sha,'checked':len(actions),'applied':bool(options['apply']),
            'created_event_ids':created,'target_event_ids':owned}))
