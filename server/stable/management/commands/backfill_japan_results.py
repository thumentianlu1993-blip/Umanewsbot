"""固定证据包的日本历史赛果回填；默认事务回放后回滚，不联网。"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from stable import models
from stable.services.race_source_identity import event_snapshot, resolve_observation
from stable.services.race_data_source_adapters import load_multisource_policy, fetch_bound_observation, run_multisource_claim
from stable.services.race_data_sync_enrollment import attach_multisource_observation, rebind_multisource_enrollment, _lock_multisource_event
from stable.services.race_data_sync_control import claim_multisource_events, _establish_data_sync_lifecycle_evidence


def url_key(url):
    value=urlsplit(url);query=parse_qs(value.query)
    if 'k_raceDate' in query:
        query['k_raceDate']=['/'.join(str(int(v)) for v in query['k_raceDate'][0].split('/'))]
    return value.scheme,value.netloc,value.path,tuple(sorted((k,tuple(v)) for k,v in query.items()))


def read_artifact(root, spec):
    relative=Path(spec['file']);original=root/relative
    path=original.resolve()
    if relative.is_absolute() or original.is_symlink() or not path.is_relative_to(root.resolve()):raise ValueError('artifact_path')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise ValueError('artifact_digest')
    return path,raw


def execute(path, expected_sha256, *, apply=False, now=None):
    now=now or timezone.now();path=Path(path);raw=path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected_sha256:raise ValueError('manifest_digest')
    manifest=json.loads(raw);items=manifest.get('items',[])
    if (manifest.get('schema_version')!=1 or manifest.get('action')!='backfill_japan_official_results'
        or not 1<=len(items)<=1000 or len({r['event_id'] for r in items})!=len(items)):
        raise ValueError('manifest_scope')
    policy=load_multisource_policy(now=now)
    if policy.digest!=manifest.get('policy_digest'):raise ValueError('manifest_policy_drift')
    pages={}
    for spec in manifest['pages']:
        _,content=read_artifact(path.parent,spec);key=url_key(spec['url'])
        if key in pages:raise ValueError('duplicate_page')
        pages[key]=content.decode('utf-8')
    names=[]
    for kind in ('canonical_names','source_names'):
        file,_=read_artifact(path.parent,manifest[kind]);names.append((kind,file,manifest[kind]['sha256']))
    def fetch(url,**kwargs):
        try:return pages[url_key(url)]
        except KeyError:raise ValueError('unlisted_page') from None
    # 发布窗口须停写相关任务；全部事件原子回放，失败或dry-run不留下部分升级。
    with transaction.atomic():
        receipt=models.OperationLog.objects.filter(action_type='japan_result_backfill',target_type='manifest',target_id=digest).first()
        if receipt:return dict(manifest_sha256=digest,action='replay',events=json.loads(receipt.detail)['events'])
        locked={}
        for item in sorted(items,key=lambda r:r['event_id']):
            event,lifecycle=_lock_multisource_event(item['event_id']);locked[event.pk]=(event,lifecycle)
            if event.country_region!='japan' or event_snapshot(event)!=item['event_snapshot_sha256']:
                raise ValueError('event_baseline_drift')
            if lifecycle and lifecycle.manual_pause_reason:raise ValueError('event_manual_pause')
            if event.status in ('cancelled','postponed'):raise ValueError('event_not_runnable')
            if any((event.manual_lock_flags or {}).values()) or event.field_authorities.filter(manual_lock=True).exists():
                raise ValueError('event_manual_lock')
        for kind,file,sha in names:
            call_command('register_japan_series_names' if kind=='canonical_names' else 'register_japan_source_names',
                         manifest=str(file),expected_sha256=sha,apply=True,verbosity=0)
        report=[]
        for item in items:
            event,lifecycle=locked[item['event_id']]
            route=policy.route_for(item['source'])
            if route is None or route.provider not in ('jra','nar'):raise ValueError('non_japan_route')
            observation=fetch_bound_observation(event=event,route=route,now=now,fetcher=fetch,url_hint=item['url'])
            match=resolve_observation(observation,route=route,now=now)
            if (match.status!='exact' or match.event_id!=event.pk or observation['external_race_id']!=item['external_race_id']
                or observation.get('result_phase')!='official' or not observation.get('roster_complete')):
                raise ValueError('result_identity_or_completeness')
            source=event.source_identities.filter(source_key=route.provider,region_code=route.region,
                identity_namespace=route.identity_namespace).first()
            enrollment=getattr(event,'race_data_sync_enrollment',None)
            if source:
                if (source.external_race_id!=observation['external_race_id'] or source.canonical_url!=item.get('expected_source_url')):
                    raise ValueError('source_baseline_drift')
                source.canonical_url=observation['canonical_url'];source.save(update_fields=('canonical_url','updated_at'))
            elif item.get('expected_source_url') is not None:raise ValueError('source_missing')
            if enrollment:
                binding=enrollment.source_bindings.filter(state='active',source_identity=source).get()
                if binding.route_digest!=item.get('expected_route_digest'):raise ValueError('binding_baseline_drift')
                rebind_multisource_enrollment(event_id=event.pk,policy=policy,now=now,
                    expected_route_digest=binding.route_digest,apply=True)
                lifecycle.refresh_from_db()
                enrollment.refresh_from_db()
                if item.get('enable_lifecycle') is not True:raise ValueError('lifecycle_action_missing')
                _establish_data_sync_lifecycle_evidence(lifecycle=lifecycle,event=event,standing_policy_digest=policy.digest,
                    manifest_sha256=enrollment.manifest_sha256,entry_sha256=enrollment.entry_sha256,
                    owner_generation=event.projection_control.owner_generation,now=now)
            elif item.get('enable_lifecycle') is not True:raise ValueError('lifecycle_action_missing')
            decision=attach_multisource_observation(observation,policy=policy,now=now)
            if decision.action not in ('acquired','attached','replay'):raise ValueError('attach:'+decision.reason_code)
            claims=claim_multisource_events(event_ids=[event.pk],now=now,historical=True)
            if len(claims)!=1:raise ValueError(f'historical_claim_unavailable:{event.pk}')
            result=run_multisource_claim(claim=claims[0],now=now,fetcher=fetch)
            if not result.get('processed'):raise ValueError('apply:'+result.get('reason','unknown'))
            event.refresh_from_db();control=event.projection_control;revision=control.current_result_revision
            if (event.status!='finished' or not revision or not revision.published_at
                or event.results.count()!=len(observation['roster'])):raise ValueError('public_projection_incomplete')
            report.append(dict(event_id=event.pk,revision_id=revision.pk,rows=event.results.count()))
        if apply:
            models.OperationLog.objects.create(action_type='japan_result_backfill',target_type='manifest',target_id=digest,
                detail=json.dumps(dict(events=report),ensure_ascii=False))
        else:transaction.set_rollback(True)
        return dict(manifest_sha256=digest,action='applied' if apply else 'dry_run_rolled_back',events=report)


class Command(BaseCommand):
    help='按SHA固定的日本历史赛果证据包回放；默认全部事务回滚，--apply才保留'
    def add_arguments(self,parser):
        parser.add_argument('--manifest',required=True)
        parser.add_argument('--expected-sha256',required=True)
        parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        try:result=execute(options['manifest'],options['expected_sha256'],apply=options['apply'])
        except (ValueError,KeyError,TypeError,OSError) as exc:raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result,ensure_ascii=False))
