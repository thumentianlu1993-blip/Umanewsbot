import json,hashlib
from pathlib import Path
from django.conf import settings
from django.db import connection,transaction
from stable import models as m
from stable.services.race_live_fixtures import parse_the_racing_api_live_racecards_payload
from stable.services.race_data_sync_providers import _match_discovery_race
out={'snapshots':[]}
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY');c.execute("SET LOCAL statement_timeout='12s'")
 for s in m.RaceDataSnapshotLease.objects.filter(id__in=[15,16,17]):
  manifest=s.manifest_data;root=Path(settings.RACE_DATA_RAW_ARTIFACT_ROOTS[0])/'snapshots'
  path=root/(hashlib.sha256(s.cache_key.encode()).hexdigest()+'-'+s.artifact_sha256+'.json')
  if not path.is_file():out['snapshots'].append({'id':s.id,'missing':True});continue
  raw=path.read_bytes();p=json.loads(raw)
  d={'id':s.id,'fetched_at':manifest.get('fetched_at'),'sha_valid':hashlib.sha256(raw).hexdigest()==s.artifact_sha256,'keys':list(p),'races':[]}
  for r in p.get('racecards',p.get('results',[])):
   if any(x in r.get('race_name','').lower() for x in ['chamb','lejeune','compiegne']):
    d['races'].append({k:r.get(k) for k in ['race_id','race_name','course','region','off_dt','race_status','status','is_official']})
    d['races'][-1]['race_status_present']='race_status' in r
    d['races'][-1]['runners_count']=len(r.get('runners',[]))
  if p.get('racecards'):
   snap=parse_the_racing_api_live_racecards_payload(p)
   event=m.RaceEvent.objects.select_related('race_series','major_race_event').prefetch_related('aliases','race_series__names').get(pk=829)
   counts={};match,reason=_match_discovery_race(event=event,races=snap.races,expected_region_code='FR',match_counts=counts)
   d['chambly_match']={'reason':reason,'counts':counts}
  out['snapshots'].append(d)
print(json.dumps(out,default=str,indent=2))
