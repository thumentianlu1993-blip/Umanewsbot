"""按来源场次建立美国清单；生产关系只是计划，不授予写入身份。"""
from collections import Counter
import hashlib
import json
import re

from .us_racing_sources import name_key


def calendar_window_rows(calendar, *, start, end):
    """冲突保留在分母并携带全部证据；不同场次的同名赛事仍分别保留。"""
    rows={r['candidate_key']:r for r in calendar['items']
          if r['grade'] in {'G1','G2','G3'} and start<=r['local_date']<=end}
    for conflict in calendar.get('conflicts',[]):
        if conflict['reason']!='source_conflict':continue
        evidence=conflict['evidence']
        relevant=[r for r in evidence if r['grade'] in {'G1','G2','G3'}
                  and r.get('local_date') and start<=r['local_date']<=end]
        if relevant:
            rows[conflict['candidate_key']]=dict(relevant[0],source_conflict=evidence)
    return list(rows.values())


def reconcile_inventory(flat_calendar, nsa_rows, events, *, start, end, reviewed_aliases=()):
    """已审别名必须绑定双方完整名称、赛场和年度；不做相似度合并。"""
    aliases={}
    for item in reviewed_aliases:
        k=(item['year'],item['venue'],name_key(item['source_name']))
        if k in aliases:
            raise ValueError('us_inventory_duplicate_alias')
        aliases[k]=item
    rows=[dict(r,race_kind='flat') for r in calendar_window_rows(flat_calendar,start=start,end=end)]
    rows += [dict(r,race_kind='hurdle') for r in nsa_rows
             if r['grade'] in {'G1','G2','G3'} and start<=r['local_date']<=end]
    if len({r['candidate_key'] for r in rows})!=len(rows):
        raise ValueError('us_inventory_duplicate_occurrence')
    planned=[]
    for r in rows:
        if r.get('source_conflict'):
            planned.append(dict(source=r,existing_event_id=None,action='source_conflict',
                date_before=None,date_change=False,alias_evidence=None,production_identity_granted=False))
            continue
        year=int(r['local_date'][:4]);alias=aliases.get((year,r['venue'],name_key(r['race_name'])))
        targets=[e for e in events if e['year']==year and
                 e.get('source_refs',{}).get('track_code')==r['venue'] and
                 name_key(e['original_name'])==name_key(alias['event_name'] if alias else r['race_name'])]
        if len(targets)>1:
            raise ValueError('us_inventory_multiple_events')
        event=targets[0] if targets else None
        if alias and (not event or event['id']!=alias['event_id']):
            raise ValueError('us_inventory_alias_baseline_drift')
        planned.append(dict(source=r,existing_event_id=event['id'] if event else None,
            action='update_existing' if event else 'create_candidate',
            date_before=event['local_date'] if event else None,
            date_change=bool(event and event['local_date']!=r['local_date']),
            alias_evidence=alias.get('evidence') if alias else None,
            production_identity_granted=False))
    counts=Counter(r['existing_event_id'] for r in planned if r['existing_event_id'] is not None)
    for row in planned:
        if counts[row['existing_event_id']]>1:
            # 例如Glen Cove两个分场：不能把两个结果都写入同一个旧年度赛事。
            row['action']='split_occurrences_required'
            row['write_event_id']=None
        else:
            row['write_event_id']=row['existing_event_id']
    annual=[]
    for r in flat_calendar['unresolved']:
        if r['grade'] not in {'G1','G2','G3'}:
            continue
        source_year=r.get('year')
        if source_year is None:
            match=re.fullmatch(r'https://toba\.org/graded-stakes/(\d{4})-races/',r.get('source_url',''))
            if not match:
                raise ValueError('us_inventory_annual_year')
            source_year=int(match[1])
        targets=[e for e in events if e['year']==source_year and
            e.get('source_refs',{}).get('track_code')==r['venue'] and name_key(e['original_name'])==name_key(r['race_name'])]
        annual.append(dict(source=r,window_membership='undated_not_run',
            existing_event_ids=[e['id'] for e in targets],prior_dates=[e['local_date'] for e in targets],
            reason='source_reports_not_run_without_date_or_cancellation_reason'))
    report=dict(schema_version=1,start=start,end=end,targets=planned,target_count=len(planned),
        source_counts=dict(Counter(r['source']['race_kind'] for r in planned)),
        action_counts=dict(Counter(r['action'] for r in planned)),annual_not_run=annual,
        production_identity_granted=False)
    report['inventory_sha256']=hashlib.sha256(json.dumps(report,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return report
