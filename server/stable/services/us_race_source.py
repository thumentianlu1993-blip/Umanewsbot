"""单场美国来源接入：复用已核验采集器与共享预算，不读写公开表。"""
from datetime import date, datetime
import hashlib
from .us_venues import VENUES
from .us_public_fields import result_participants


def source_observation(result, *, target, sources, route, now):
    from .race_data_source_adapters import canonical_sha, aware
    track = result.get('track') or result.get('venue')
    number = str(result['race_number'])
    expected_number=target.get('race_number') if target.get('provider')=='nsa' else target.get('source_race_id')
    if target.get('provider')=='nsa' and str(result.get('book_race_id',''))!=str(target.get('book_race_id') or target.get('source_race_id','')).split(':')[0]:
        raise ValueError('us_observation_book_identity')
    if (track != target['venue'] or result['local_date'] != target['local_date']
            or (expected_number and str(expected_number) != number)
            or track not in route.venue_aliases or VENUES[track][2] != route.timezone):
        raise ValueError('us_observation_identity')
    if len(sources) < 2 or any(not route.permits_url(s['url']) for s in sources.values()):
        raise ValueError('us_observation_sources')
    rows = result_participants(result)
    primary = sources.get('official_result', sources['chart'])
    observed = min(aware(s['fetched_at']) for s in sources.values())
    if any(aware(s['fetched_at']) > now for s in sources.values()):
        raise ValueError('us_observation_future_clock')
    for row in rows:
        row['field_provenance'].update(source_url=primary['url'],
            odds_source='DRF',odds_observed_at=sources['chart']['fetched_at'])
    evidence = dict(kind='us_independent_final_roster',row_count=len(rows),runner_count=result['runner_count'],
        sources=sources,roster_sha256=canonical_sha([(r['number'],r['horse_name']) for r in rows]))
    if result.get('runner_count_evidence'):
        evidence['runner_count_evidence'] = result['runner_count_evidence']
    return dict(provider=route.provider, region=route.region, identity_namespace=route.identity_namespace,
        operator=route.operator, external_race_id=track+':'+result['local_date']+':'+number,
        canonical_url=primary['url'],fetched_at=observed.isoformat(),
        raw_sha256=canonical_sha({k:v['sha256'] for k,v in sources.items()}),parser_version=route.parser_version,
        venue_key=track,local_date=result['local_date'],timezone=route.timezone,meeting_session='single',
        race_number=number,raw_names=[target['race_name']],off_time=result.get('off_time',''),roster=rows,
        result_phase='corrected' if result.get('correction_marker') else 'official',
        correction_evidence=dict(text=result.get('correction_marker',''),source=sources['chart']),roster_complete=True,roster_evidence=evidence,
        us_race_metadata=dict(going=result.get('going',''),winning_time=result.get('winning_time',''),fractional_times=result.get('fractional_times',[]),
            source_url=primary['url'],source_sha256=primary['sha256'],observed_at=observed.isoformat(),
            external_race_id=track+':'+result['local_date']+':'+number,local_date=result['local_date'],catalogue=result.get('catalogue',{})))


def validate_final_roster(value):
    from .race_data_source_adapters import canonical_sha, require_sha
    proof=value.get('roster_evidence',{})
    if proof.get('kind') != 'us_independent_final_roster' or proof.get('row_count') != len(value['roster']):
        return False
    if proof.get('roster_sha256') != canonical_sha([(r['number'],r['horse_name']) for r in value['roster']]):
        return False
    sources=proof.get('sources',{})
    if len(sources)<2 or 'chart' not in sources:
        return False
    for source in sources.values():
        require_sha(source['sha256'])
    return canonical_sha({k:v['sha256'] for k,v in sources.items()}) == value['raw_sha256']


class ObservationStore:
    """一次单场请求内复用字节；跨请求复用由受审fetcher的共享快照处理。"""
    def __init__(self, *, route, now, fetcher, max_requests=24):
        self.route,self.now,self.fetcher=route,now,fetcher
        self.docs={}
        self.archive_program_urls=getattr(fetcher,'archive_program_urls',())
        self.max_requests=max_requests
        self.request_count=0

    def get(self,url):
        from .us_prerelease_collection import prerelease_url_allowed
        if not self.route.permits_url(url) or not prerelease_url_allowed(url):
            raise ValueError('us_source_url_rejected')
        if url not in self.docs:
            if self.request_count >= self.max_requests:
                raise ValueError('us_single_event_request_limit')
            self.request_count+=1
            raw=self.fetcher(url,route=self.route,now=self.now)
            body=raw if isinstance(raw,bytes) else str(raw).encode()
            if len(body)>8*1024*1024:
                raise ValueError('us_source_bytes_limit')
            observed=getattr(raw,'observed_at',None) or self.now
            self.docs[url]=dict(body=body,url=url,sha256=hashlib.sha256(body).hexdigest(),fetched_at=observed.isoformat())
        return self.docs[url]

    def accept(self,doc):
        pass

    def reject(self,doc):
        pass


def fetch_us_observation(*, event, route, now, fetcher, kind):
    if kind != 'result':
        from .us_pre_race import fetch_preview, card_observation
        return card_observation(fetch_preview(event,route=route,now=now,fetcher=fetcher),route=route)
    from .us_flat_collection import collect_flat_results
    from .us_prerelease_collection import collect_nsa
    binding=(event.source_refs or {}).get('us_target_v1',{})
    if (binding.get('local_date') != str(event.local_date) or binding.get('venue') not in route.venue_aliases
            or not binding.get('candidate_key')):
        raise ValueError('us_event_target_missing')
    store=ObservationStore(route=route,now=now,fetcher=fetcher)
    day=date.fromisoformat(binding['local_date'])
    if binding['provider']=='nsa':
        report=collect_nsa(store,start=day,end=day)
        results=[r for r in report['results'] if r['candidate_key']==binding['candidate_key']]
    else:
        report=collect_flat_results(store,start=day,end=day,target_keys={binding['candidate_key']})
        results=report['results']
    if len(results)!=1:
        reasons=[x.get('reason','') for x in report.get('errors',[])]
        raise ValueError('us_result_unavailable:'+','.join(reasons) if reasons else 'not_published')
    result=results[0]
    if binding['provider']=='nsa':
        sources=result['sources']
    else:
        docs={d['sha256']:d for d in report['sources']}
        sources={k:{field:docs[sha][field] for field in ['url','sha256','fetched_at']} for k,sha in result['sources'].items()}
    from django.utils import timezone
    return source_observation(result,target=binding,sources=sources,route=route,now=timezone.now())
