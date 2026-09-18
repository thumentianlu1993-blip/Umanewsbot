#!/usr/bin/env python3
"""本轮已审赛前资料：仅补空赛时和参考候选，不创建 canonical runner。"""
import argparse
import copy
import importlib.util
import json
from datetime import datetime, timezone as tz
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from stable import models as m
from stable.services.race_pre_race import baseline, in_window

_spec=importlib.util.spec_from_file_location('gap_common',Path(__file__).with_name('backfill_reviewed_race_gaps.py'))
gap=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(gap)
require,digest,bytes_sha=gap.require,gap.digest,gap.bytes_sha
KEY='reviewed_pre_race_v1'
ACTION='reviewed_pre_race_backfill'
HOSTS={'sporting_life':'www.sportinglife.com','zeturf':'www.zeturf.fr','racing_post':'www.racingpost.com'}


def snapshot(eid):
 s=gap.snapshot(eid)
 s['candidates']=list(m.RaceEventDataCandidate.objects.filter(event_id=eid,source_name=KEY).order_by('id').values())
 return s


def guard(s):
 e=s['event']
 require(not s['lifecycle'] and not s['enrollment'] and not s['tracking'], 'managed_event')
 require(all(c['write_owner']=='unmanaged' for c in s['control']), 'managed_owner')
 require(not s['runners'] and not s['results'] and not s['canonical_links'], 'nonempty_or_duplicate')
 require(not any((e['manual_lock_flags'] or {}).values()) and not any(f['manual_lock'] for f in s['field_authorities']), 'manual_lock')
 require(e['visibility_status']=='published' and e['status']=='scheduled' and not e['source_refs'].get('pre_race_handoff'), 'event_not_upcoming')


def validate(entry,root):
 if 'before_path' in entry:
  path=root/entry['before_path']
  require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),'before_path_invalid')
  entry['before']=json.loads(path.read_text())
 b=entry['before'];require(digest(b)==entry['before_sha256'] and entry['event_id']==b['event']['id'],'baseline_invalid');guard(b)
 require(b['event']['race_datetime'] is None and b['event']['local_start_time'] is None,'time_not_empty')
 if 'reviewed_identity' in entry:
  require(entry['reviewed_identity']=={k:str(b['event'][k]) for k in ['id','year','slug','original_name','local_date','timezone_name','racecourse']},'reviewed_identity_mismatch')
 source=entry['source'];url=urlsplit(source['url'])
 require(url.scheme=='https' and url.hostname==HOSTS.get(source['provider']) and not url.username and not url.password and url.port in {None,443},'source_url_invalid')
 path=root/source['path'];require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and bytes_sha(path.read_bytes())==source['sha256'],'source_cache_drift')
 off=datetime.fromisoformat(entry['off_time']);require(timezone.is_aware(off),'timezone_missing')
 evidence=entry['time_evidence'];require(evidence.get('kind') in {'jsonld_startDate','data-depart'},'time_evidence_missing')
 raw=datetime.fromtimestamp(int(evidence['raw']),tz.utc) if evidence['kind']=='data-depart' else datetime.fromisoformat(evidence['raw'])
 require(timezone.is_aware(raw) and raw==off,'time_evidence_mismatch')
 local=off.astimezone(ZoneInfo(b['event']['timezone_name']));require(local.date().isoformat()==str(b['event']['local_date']),'local_date_mismatch')
 rows=entry['items'];require(entry['stage']=='numbered' and 0<len(rows)<=60,'invalid_roster')
 require(len({r['horse_number'] for r in rows})==len(rows),'duplicate_number')
 require(all(r['horse_name'] and r['horse_number'] and r['source_refs'].get('horse_id') and r['running_status'] in {'declared','withdrawn','non_runner'} for r in rows),'invalid_runner')
 require([r['sort_order'] for r in rows]==list(range(1,len(rows)+1)),'invalid_order')
 fetched=datetime.fromisoformat(source['fetched_at']);require(timezone.is_aware(fetched) and fetched<=timezone.now(),'invalid_fetch_time')
 return off,local,fetched


def protected(s):
 s=copy.deepcopy(s);s.pop('candidates')
 for k in ('race_datetime','local_start_time','updated_at'):s['event'].pop(k)
 s['event']['source_refs'].pop(KEY,None)
 return s


def execute(path,expected_sha,*,apply=False,fault_hook=None):
 path=Path(path);raw=path.read_bytes();require(bytes_sha(raw)==expected_sha,'manifest_sha_mismatch');manifest=json.loads(raw)
 ids=[x['event_id'] for x in manifest['events']];require(manifest['schema_version']==1 and manifest['reviewer'] and ids and len(ids)==len(set(ids)),'manifest_invalid');reports=[]
 for e in manifest['events']:
  try:
   off,local,fetched=validate(e,path.parent);eid=e['event_id']
   with transaction.atomic():
    gap._advisory_lock_event_ids([eid]);list(m.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=eid));event=m.RaceEvent.objects.select_for_update().get(pk=eid)
    for model in (m.RaceEventProjectionControl,m.RaceDataSyncEnrollment,m.RaceEventLiveTracking,m.RaceEventFieldAuthority,m.RaceEventRunner,m.RaceEventResult,m.RaceEventDataCandidate):list(model.objects.select_for_update().filter(event_id=eid))
    current=snapshot(eid);guard(current)
    log=m.OperationLog.objects.filter(action_type=ACTION,target_type='RaceEvent',target_id=str(eid),detail__contains=expected_sha).order_by('-id').first()
    if log:
     receipt=json.loads(log.detail);require(receipt['manifest_sha256']==expected_sha and digest(current)==receipt['after_sha256'],'applied_snapshot_drift');reports.append(dict(event_id=eid,status='already_applied',audit_id=log.pk));continue
    require(in_window(event,timezone.now()) and off>timezone.now(),'not_pre_race')
    require(digest(current)==e['before_sha256'],'database_baseline_drift')
    if not apply:reports.append(dict(event_id=eid,status='dry_run',rows=len(e['items'])));continue
    meta=dict(validated=True,baseline=baseline(event),authority='human_reviewed_reference',stage=e['stage'],row_count=len(e['items']),items_sha256=digest(e['items']),source_sha256=e['source']['sha256'],manifest_sha256=expected_sha,reviewer=manifest['reviewer'],time_evidence=e['time_evidence'])
    m.RaceEventDataCandidate.objects.create(event=event,module='runners',source_name=KEY,source_url=e['source']['url'],candidate_payload={'items':e['items']},raw_payload={KEY:meta},fetched_at=fetched)
    if fault_hook:fault_hook(event_id=eid,stage='after_candidate')
    event.race_datetime=off;event.local_start_time=local.timetz().replace(tzinfo=None);refs=dict(event.source_refs);refs[KEY]=dict(source_url=e['source']['url'],source_sha256=e['source']['sha256'],off_time=off.isoformat(),time_evidence=e['time_evidence'],manifest_sha256=expected_sha);event.source_refs=refs;event.save(update_fields=['race_datetime','local_start_time','source_refs','updated_at'])
    after=snapshot(eid);require(digest(protected(after))==digest(protected(e['before'])),'protected_field_drift')
    log=m.OperationLog.objects.create(action_type=ACTION,target_type='RaceEvent',target_id=str(eid),detail=json.dumps(dict(manifest_sha256=expected_sha,before_sha256=e['before_sha256'],after_sha256=digest(after),source_url=e['source']['url'],source_sha256=e['source']['sha256'],reviewer=manifest['reviewer']),ensure_ascii=False,sort_keys=True))
   reports.append(dict(event_id=eid,status='applied',rows=len(e['items']),audit_id=log.pk))
  except Exception as exc:reports.append(dict(event_id=e['event_id'],status='blocked',reason=(str(exc) if type(exc)is ValueError else type(exc).__name__)[:160]))
 return dict(manifest_sha256=expected_sha,events=reports)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--sha256',required=True);p.add_argument('--apply',action='store_true');o=p.parse_args();r=execute(o.manifest,o.sha256,apply=o.apply);print(json.dumps(r,ensure_ascii=False,sort_keys=True));return int(any(e['status']=='blocked' for e in r['events']))
if __name__=='__main__':raise SystemExit(main())
