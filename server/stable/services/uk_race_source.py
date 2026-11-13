"""英国付费原件到既有多源 observation；不自行授予写入权。"""
from .uk_collection import fetch_payload,_venue,api_url
from .uk_sources import PARSER_VERSION


def source_observation(payload,*,route,now):
    from .race_data_source_adapters import canonical_sha,aware,require_sha
    if payload.get('stage') in {'not_published','nominations','weights_published'}:
        raise ValueError('uk_awaiting_final_card')
    if payload.get('gaps') or not payload.get('roster_complete'):raise ValueError('uk_roster_incomplete')
    docs=payload['source_documents'];external=payload['external_race_id']
    result=bool(payload.get('result_phase'));primary=payload.get('primary_source_url') or api_url('result' if result else 'card',race_id=external)
    sources={doc['url']:doc for doc in docs}
    for doc in docs:
        require_sha(doc['sha256'])
        if not route.permits_url(doc['url']) or aware(doc['fetched_at'])>now:raise ValueError('uk_document_invalid')
    if primary not in sources or api_url('card',race_id=external) not in sources:
        # 列表返回的完整卡必须绑定其实际原件，不伪装成请求过单场 URL。
        if result or not any('/v1/racecards/pro?' in url or '/v1/racecards/big-races?' in url for url in sources):
            raise ValueError('uk_document_missing')
        if primary not in sources:raise ValueError('uk_primary_document_missing')
    rows=payload['roster']
    for row in rows:
        row['field_provenance'].update(uk_paid_v1=True,source_url=primary,
            odds_observed_at=sources[primary]['fetched_at'])
    evidence=dict(kind='uk_card_result_roster',row_count=len(rows),sources=sources,
        roster_sha256=canonical_sha([(r['external_runner_id'],r['number'],r['horse_name']) for r in rows]))
    return dict(provider=route.provider,region=route.region,identity_namespace=route.identity_namespace,
        operator=route.operator,external_race_id=external,canonical_url=primary,
        fetched_at=min(aware(doc['fetched_at']) for doc in docs).isoformat(),
        raw_sha256=canonical_sha({url:doc['sha256'] for url,doc in sources.items()}),parser_version=route.parser_version,
        venue_key=_venue(payload['course'],route),local_date=payload['local_date'],timezone=route.timezone,
        meeting_session='',race_number='',raw_names=[payload['race_name']],off_time=payload['off_time'],
        roster=rows,result_phase=payload.get('result_phase',''),roster_complete=True,roster_evidence=evidence,
        uk_race_metadata={**payload.get('metadata',{}),'external_race_id':external,'local_date':payload['local_date'],
            'source_url':primary,'source_sha256':sources[primary]['sha256'],'observed_at':sources[primary]['fetched_at']})


def fetch_observation(*,event,route,now,fetcher=None):
    from django.utils import timezone
    payload=fetch_payload(event=event,route=route,now=now,fetcher=fetcher)
    return source_observation(payload,route=route,now=max(now,timezone.now()))


def validate_final_roster(value):
    from .race_data_source_adapters import canonical_sha,require_sha
    if (value.get('provider'),value.get('region'),value.get('parser_version'))!=('the_racing_api','united_kingdom',PARSER_VERSION):return False
    proof=value.get('roster_evidence',{});sources=proof.get('sources',{});external=value['external_race_id']
    if (proof.get('kind')!='uk_card_result_roster' or proof.get('row_count')!=len(value['roster'])
            or api_url('card',race_id=external) not in sources or api_url('result',race_id=external) not in sources
            or proof.get('roster_sha256')!=canonical_sha([(r['external_runner_id'],r['number'],r['horse_name']) for r in value['roster']])):
        return False
    for source in sources.values():require_sha(source['sha256'])
    return canonical_sha({url:doc['sha256'] for url,doc in sources.items()})==value['raw_sha256']
