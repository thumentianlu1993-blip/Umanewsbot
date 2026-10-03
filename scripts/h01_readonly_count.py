"""H01 fixed capacity preflight; defaults to printing templates, no connection.

Counts are raw database aggregates, not horse inventory or publication proof.
No credentials, source payloads, user text, writes, or streaming are emitted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import math
import multiprocessing
import tempfile

MAX_SECONDS=120
MAX_SELECTS=24
MAX_ROWS=500
MAX_BYTES=2*1024*1024
COLUMNS={
 'raceevent':'id country_region local_date timezone_name normalized_grade grade_text status visibility_status series_key source_refs',
 'raceeventproductcanonicallink':'id duplicate_event_id canonical_event_id is_active',
 'raceeventprojectioncontrol':'id event_id current_racecard_revision_id current_result_revision_id',
 'raceeventrevision':'id event_id kind revision_no phase content_sha256 supersedes_id published_at conflict_status',
 'raceeventrevisionpublication':'id revision_id published_at registry_digest coverage_proof_digest authorization_kind',
 'raceeventrevisionitem':'id revision_id participant_id source_order horse_number status',
 'raceeventparticipant':'id event_id stable_key horse_profile_id country_region review_status',
 'raceeventparticipantsourceidentity':'id participant_id source_identity_id external_runner_id',
 'raceresultsourceidentity':'id event_id source_key region_code identity_namespace external_race_id review_status registry_digest valid_until',
 'raceeventrunner':'id event_id external_runner_id horse_number running_status source_refs',
 'raceeventresult':'id event_id horse_number running_status is_confirmed source_refs',
 'horseracerecord':'id horse_profile_id event_id race_date race_date_precision race_region start_status result_status canonical_race_key idempotency_key source_name',
 'horseexternalidentity':'id horse_profile_id source namespace external_id status payload_sha256 verified_at rejected_at',
 'horseprofile':'id primary_term_id racing_region review_status completeness_status published_at hidden_at manual_lock_flags career_history_status official_or_source_start_count',
 'horsep0source':'id profile_id race_event_id race_runner_id race_result_id source_type status participant_key observed_at revoked_at',
 'externalhorse':'id source horse_id fetched_at last_seen_at',
 'articlehorselink':'id horse_profile_id article_id status',
 'newsarticle':'id racing_region published_at published_to_web_at withdrawn_at duplicate_of_id',
 'racedatasnapshotlease':'id cache_key state artifact_sha256 manifest_data',
}
REGIONS=('japan','hong_kong','united_kingdom','ireland','france','united_states','australia','germany','middle_east')
# Constants only: no caller-provided SQL, identifiers, window, or region expansion.
_values=','.join("('%s','%s')"%('stable_'+table,column) for table,cols in COLUMNS.items() for column in cols.split())
SCHEMA_SQL="""WITH expected(table_name,column_name) AS (VALUES %s)
SELECT e.table_name, bool_and(c.column_name IS NOT NULL)
FROM expected e LEFT JOIN information_schema.columns c
 ON c.table_schema='public' AND c.table_name=e.table_name AND c.column_name=e.column_name
GROUP BY e.table_name ORDER BY e.table_name"""%_values
EVENTS="""WITH scoped_events AS (SELECT id,country_region,normalized_grade,local_date
FROM public.stable_raceevent WHERE country_region=ANY(%%s)
AND (local_date BETWEEN DATE '2020-01-01' AND DATE '2026-11-02' OR local_date IS NULL)) """
TARGETS=EVENTS+""", scoped_profiles AS (
SELECT DISTINCT p.horse_profile_id AS id FROM public.stable_raceeventparticipant p
JOIN scoped_events e ON e.id=p.event_id WHERE p.horse_profile_id IS NOT NULL
UNION SELECT DISTINCT r.horse_profile_id FROM public.stable_horseracerecord r
WHERE r.race_region=ANY(%%s) AND r.race_date_precision='exact' AND r.start_status='started'
AND r.race_date BETWEEN DATE '2023-10-03' AND DATE '2026-10-03') """
# Replace escaped placeholders after composition; parameterization remains DB-API.
EVENTS=EVENTS.replace('%%s','%s');TARGETS=TARGETS.replace('%%s','%s')
QUERIES=(
 ('schema',SCHEMA_SQL,None),
 ('snapshot',"SELECT transaction_timestamp()::text,current_setting('transaction_read_only'),current_setting('transaction_isolation'),current_setting('server_version_num')",None),
 ('indexes',"SELECT tablename,count(*) FROM pg_catalog.pg_indexes WHERE schemaname='public' AND tablename=ANY(%s) GROUP BY tablename ORDER BY tablename",(['stable_'+n for n in COLUMNS],)),
 ('event_counts',EVENTS+"SELECT country_region,normalized_grade,count(*),count(*) FILTER (WHERE local_date IS NULL) FROM scoped_events GROUP BY country_region,normalized_grade ORDER BY country_region,normalized_grade",(list(REGIONS),)),
 ('roster_rows',EVENTS+"SELECT e.country_region,count(p.id),count(p.id) FILTER (WHERE p.horse_profile_id IS NULL) FROM scoped_events e LEFT JOIN public.stable_raceeventparticipant p ON p.event_id=e.id GROUP BY e.country_region ORDER BY e.country_region",(list(REGIONS),)),
 ('legacy_runner_rows',EVENTS+"SELECT e.country_region,count(r.id) FROM scoped_events e LEFT JOIN public.stable_raceeventrunner r ON r.event_id=e.id GROUP BY e.country_region ORDER BY e.country_region",(list(REGIONS),)),
 ('legacy_result_rows',EVENTS+"SELECT e.country_region,count(r.id) FROM scoped_events e LEFT JOIN public.stable_raceeventresult r ON r.event_id=e.id GROUP BY e.country_region ORDER BY e.country_region",(list(REGIONS),)),
 ('revision_pointers',EVENTS+"SELECT e.country_region,count(c.id),count(c.id) FILTER (WHERE c.current_result_revision_id IS NULL AND c.current_racecard_revision_id IS NULL) FROM scoped_events e LEFT JOIN public.stable_raceeventprojectioncontrol c ON c.event_id=e.id GROUP BY e.country_region ORDER BY e.country_region",(list(REGIONS),)),
 ('identity_states',TARGETS+"SELECT i.status,count(*) FROM public.stable_horseexternalidentity i JOIN scoped_profiles p ON p.id=i.horse_profile_id GROUP BY i.status ORDER BY i.status",(list(REGIONS),list(REGIONS))),
 ('profile_states',TARGETS+"SELECT h.review_status,h.completeness_status,count(*),count(*) FILTER (WHERE h.published_at IS NOT NULL AND h.hidden_at IS NULL) FROM public.stable_horseprofile h JOIN scoped_profiles p ON p.id=h.id GROUP BY h.review_status,h.completeness_status ORDER BY h.review_status,h.completeness_status",(list(REGIONS),list(REGIONS))),
 ('staging_source_id_candidates',TARGETS+"SELECT x.source,count(DISTINCT x.id) FROM public.stable_externalhorse x JOIN public.stable_horseexternalidentity i ON i.source=x.source AND i.external_id=x.horse_id JOIN scoped_profiles p ON p.id=i.horse_profile_id GROUP BY x.source ORDER BY x.source",(list(REGIONS),list(REGIONS))),
 ('recent_news_links',TARGETS+"SELECT l.status,count(*) FROM public.stable_articlehorselink l JOIN scoped_profiles p ON p.id=l.horse_profile_id JOIN public.stable_newsarticle n ON n.id=l.article_id WHERE n.published_to_web_at >= TIMESTAMPTZ '2026-07-05 00:00:00+08' AND n.published_to_web_at < TIMESTAMPTZ '2026-10-04 00:00:00+08' AND n.withdrawn_at IS NULL GROUP BY l.status ORDER BY l.status",(list(REGIONS),list(REGIONS))),
)


def templates():
    return [{'name':n,'sql':sql,'params':params,'sha256':hashlib.sha256(sql.encode()).hexdigest()} for n,sql,params in QUERIES]


def run_counts(connection, *, revision, clock=time.monotonic, deadline=None):
    result=dict(status='partial',reason='not_started',declared_revision=revision if type(revision) is str and re.fullmatch('[0-9a-f]{40}',revision) else None,revision_binding='caller_metadata; not independently verified by reader',selects=0,rows=0,queries=[],inventory_complete=False,cache_coverage='unknown',account_entitlements='unknown')
    cursor=None
    try:
        start=clock();deadline=start+MAX_SECONDS if deadline is None else min(deadline,start+MAX_SECONDS)
        if type(revision) is not str or not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('revision_binding')
        from psycopg import IsolationLevel
        connection.set_autocommit(False)
        connection.set_read_only(True)
        connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
        cursor=connection.cursor()
        for name,sql,params in QUERIES:
            remaining=deadline-clock()
            if remaining<=0:result['reason']='wall_time';break
            if result['selects']>=MAX_SELECTS:result['reason']='query_limit';break
            # Round down: never grant a statement more than its remaining budget.
            milliseconds=min(5000,int(remaining*1000))
            if milliseconds<1:result['reason']='wall_time';break
            cursor.execute('SET LOCAL statement_timeout = '+str(milliseconds))
            cursor.execute('SET LOCAL lock_timeout = '+str(min(250,milliseconds)))
            cursor.execute('SET LOCAL idle_in_transaction_session_timeout = '+str(milliseconds))
            remaining=deadline-clock()
            if remaining<=0:result['reason']='wall_time';break
            milliseconds=min(5000,int(remaining*1000))
            if milliseconds<1:result['reason']='wall_time';break
            cursor.execute('SET LOCAL statement_timeout = '+str(milliseconds))
            began=clock();result['selects']+=1
            cursor.execute(sql,params)
            rows=cursor.fetchmany(MAX_ROWS-result['rows']+1)
            elapsed=clock()-began
            if clock()>=deadline or elapsed>5:result['reason']='wall_time' if clock()>=deadline else 'statement_time';break
            if result['rows']+len(rows)>MAX_ROWS:result['reason']='row_limit';break
            if name=='schema' and (len(rows)!=len(COLUMNS) or {r[0] for r in rows}!={'stable_'+t for t in COLUMNS} or any(r[1] is not True for r in rows)):
                result['reason']='schema_mismatch';break
            if name=='snapshot' and (len(rows)!=1 or rows[0][1]!='on' or rows[0][2]!='repeatable read'):
                result['reason']='transaction_mismatch';break
            entry=dict(name=name,template_sha256=hashlib.sha256(sql.encode()).hexdigest(),params_sha256=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest(),elapsed_seconds=elapsed,rows=rows)
            candidate={**result,'queries':result['queries']+[entry],'rows':result['rows']+len(rows)}
            if len(json.dumps(candidate,ensure_ascii=False,default=str).encode())>MAX_BYTES:result['reason']='byte_limit';break
            result=candidate
        else:result.update(status='capacity_preflight_finished',reason='bounded_queries_finished')
    except Exception:
        # Do not return exception text, SQL, DSNs, or parameters from the driver.
        result.update(status='partial',reason='database_or_input_error')
    finally:
        if cursor is not None:
            try:cursor.close()
            except Exception:result.update(status='partial',reason='cleanup_error')
        try:connection.rollback()
        except Exception:result.update(status='partial',reason='cleanup_error')
        try:connection.close()
        except Exception:result.update(status='partial',reason='cleanup_error')
    return result


def _bounded_worker(operation, *, deadline):
    """Mandatory CLI envelope: forked worker owns all DB calls, including cleanup.

    No driver/thread cancellation is trusted. Parent kills a still-live process
    at the deadline, closing its DB socket; backend rollback requires PG proof.
    Direct run_counts is a diagnostic helper, not the production execution API.
    """
    partial=dict(status='partial',reason='wall_time',inventory_complete=False)
    if 'fork' not in multiprocessing.get_all_start_methods():
        return {**partial,'reason':'bounded_runtime_unavailable'}
    with tempfile.TemporaryDirectory(prefix='h01-count-') as directory:
        output=Path(directory)/'result.json'
        def work():
            try:
                value=operation()
                output.write_text(json.dumps(value,ensure_ascii=False,default=str))
            except BaseException:
                output.write_text(json.dumps({**partial,'reason':'database_or_input_error'}))
        process=multiprocessing.get_context('fork').Process(target=work)
        try:
            if time.monotonic()>=deadline:return partial
            process.start()
            process.join(max(0,deadline-time.monotonic()))
            if process.is_alive() or time.monotonic()>=deadline:
                return partial
            if process.exitcode!=0 or not output.exists():
                return {**partial,'reason':'worker_failed'}
            if output.stat().st_size>MAX_BYTES:
                return {**partial,'reason':'byte_limit'}
            return json.loads(output.read_text())
        finally:
            if process.pid is not None:
                if process.is_alive():process.kill()
                process.join(timeout=0.1)
                if not process.is_alive():process.close()


def _execute_database(revision, *, deadline):
    try:
        import psycopg
        remaining=deadline-time.monotonic()
        if remaining<=0:return dict(status='partial',reason='wall_time',inventory_complete=False)
        connection=psycopg.connect(os.environ['H01_READONLY_DSN'],connect_timeout=max(1,min(3,math.floor(remaining))))
    except Exception:
        return dict(status='partial',reason='connection_failed',inventory_complete=False)
    # Connect time consumes the same fixed outer budget; it is never added back.
    remaining=deadline-time.monotonic()
    if remaining<=0:
        connection.close()
        return dict(status='partial',reason='wall_time',inventory_complete=False)
    return run_counts(connection,revision=revision,deadline=deadline)


def main(argv=None):
    deadline=time.monotonic()+MAX_SECONDS
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--revision')
    parser.add_argument('--expected-tool-sha256')
    args=parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(dict(mode='templates_only',templates=templates()),ensure_ascii=False));return 0
    digest=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.expected_tool_sha256!=digest or not args.revision or not re.fullmatch('[0-9a-f]{40}',args.revision):
        print(json.dumps(dict(status='partial',reason='fixed_package_binding_missing')));return 2
    result=_bounded_worker(lambda:_execute_database(args.revision,deadline=deadline),deadline=deadline)
    print(json.dumps(result,ensure_ascii=False,default=str));return 0 if result['status']=='capacity_preflight_finished' else 2

if __name__=='__main__':raise SystemExit(main())
