\set ON_ERROR_STOP on
BEGIN;
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SELECT set_config('umanews.apply_lock_token_sha256', :'apply_lock_token_sha256', true);
SELECT set_config('umanews.executable_approval_sha256', :'executable_approval_sha256', true);
SELECT set_config('umanews.reviewed_sql_sha256', :'reviewed_sql_sha256', true);
SELECT set_config('umanews.reviewed_wrapper_sha256', :'reviewed_wrapper_sha256', true);

DO $reconcile$
DECLARE
    payload jsonb := pg_read_file('/tmp/stale-review-before.json')::jsonb;
    expected_ids bigint[] := ARRAY[39,43,44,45,46,47,48]::bigint[];
    claimed_ids bigint[];
    row_json jsonb;
    row_keys text[];
    actual stable_raceresultreviewrun%ROWTYPE;
    fixed_at timestamptz := clock_timestamp();
    affected integer := 0;
    changed integer;
BEGIN
    IF current_database() <> 'horse_news' THEN
        RAISE EXCEPTION 'database name mismatch';
    END IF;
    IF (SELECT system_identifier FROM pg_control_system()) <> 7634210956226523169 THEN
        RAISE EXCEPTION 'database system identifier mismatch';
    END IF;
    IF payload->>'schema_version' IS DISTINCT FROM 'stale-review-before/v1'
       OR payload->>'database_identity_sha256' IS DISTINCT FROM 'a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c'
       OR payload->'target_ids' IS DISTINCT FROM '[39,43,44,45,46,47,48]'::jsonb
       OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(payload) AS key)
          IS DISTINCT FROM ARRAY['database_identity_sha256','rows','schema_version','target_ids']::text[]
       OR jsonb_array_length(payload->'rows') IS DISTINCT FROM 7 THEN
        RAISE EXCEPTION 'before artifact metadata mismatch';
    END IF;

    PERFORM 1
      FROM stable_raceresultreviewrun
     WHERE status = 'claimed'
     ORDER BY id
     FOR UPDATE;
    SELECT array_agg(id ORDER BY id)
      INTO claimed_ids
      FROM stable_raceresultreviewrun
     WHERE status = 'claimed';
    IF claimed_ids IS DISTINCT FROM expected_ids THEN
        RAISE EXCEPTION 'global claimed ID set mismatch: %', claimed_ids;
    END IF;

    FOR row_json IN SELECT value FROM jsonb_array_elements(payload->'rows') ORDER BY (value->>'id')::bigint
    LOOP
        SELECT array_agg(key ORDER BY key)
          INTO row_keys
          FROM jsonb_object_keys(row_json) AS key;
        IF row_keys <> ARRAY[
            'bundle_sha256','created_at','cursor','finished_at','id','lease_expires_at',
            'schedule_slot','selector_sha256','status','terminal_summary','updated_at'
        ]::text[] THEN
            RAISE EXCEPTION 'before row field set mismatch for id %', row_json->>'id';
        END IF;

        SELECT *
          INTO STRICT actual
          FROM stable_raceresultreviewrun
         WHERE id = (row_json->>'id')::bigint
         FOR UPDATE;
        IF actual.created_at IS DISTINCT FROM (row_json->>'created_at')::timestamptz
           OR actual.updated_at IS DISTINCT FROM (row_json->>'updated_at')::timestamptz
           OR actual.schedule_slot IS DISTINCT FROM (row_json->>'schedule_slot')::timestamptz
           OR actual.status IS DISTINCT FROM row_json->>'status'
           OR actual.selector_sha256 IS DISTINCT FROM row_json->>'selector_sha256'
           OR actual.bundle_sha256 IS DISTINCT FROM row_json->>'bundle_sha256'
           OR actual.cursor IS DISTINCT FROM row_json->'cursor'
           OR actual.lease_expires_at IS DISTINCT FROM (row_json->>'lease_expires_at')::timestamptz
           OR actual.terminal_summary IS DISTINCT FROM row_json->'terminal_summary'
           OR actual.finished_at IS DISTINCT FROM NULLIF(row_json->>'finished_at','')::timestamptz
           OR actual.status <> 'claimed'
           OR actual.lease_expires_at IS NULL
           OR actual.lease_expires_at > fixed_at THEN
            RAISE EXCEPTION 'full before row mismatch for id %', row_json->>'id';
        END IF;

        UPDATE stable_raceresultreviewrun
           SET status = 'noop',
               lease_expires_at = NULL,
               finished_at = fixed_at,
               updated_at = fixed_at,
               terminal_summary = jsonb_build_object(
                   'schema_version', 'stale-review-reconciliation/v1',
                   'reason_code', 'stale_claim_reconciled',
                   'reason', 'stale_claim_owner_containers_gone_after_verified_shutdown',
                   'actor', 'release-coordinator',
                   'reconciled_at', to_char(fixed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                   'database_identity_sha256', 'a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c',
                   'database_system_identifier', '7634210956226523169',
                   'before_artifact_sha256', 'd8669dae5ddfe95e6cdce8243852037d793ae70fd83ff4e8216237260728b4d0',
                   'before_rows_sha256', '5670d44b5b25ee17805e90f6547f84ef00584da6d698891659e1ef60ba620057',
                   'scope_approval_sha256', '76789e32fd9bb0c9669c11ae497677288c8cf0ec4bf4a4ea500d425ce2251f7c',
                   'executable_approval_sha256', current_setting('umanews.executable_approval_sha256'),
                   'reviewed_sql_sha256', current_setting('umanews.reviewed_sql_sha256'),
                   'reviewed_wrapper_sha256', current_setting('umanews.reviewed_wrapper_sha256'),
                   'host_evidence_sha256', '109562de4c91c6499a08deeb9f4c33f26bf8ff4ba550bd3663cb43a937f4882e',
                   'backup_sha256', '09c9fd99f3a8ad120be0754b1da32b7561f3fa8713c7e6fdf9d83a364b39d7fc',
                   'apply_lock_token_sha256', current_setting('umanews.apply_lock_token_sha256'),
                   'original_before_row', row_json
               )
         WHERE id = actual.id
           AND status = 'claimed'
           AND cursor = actual.cursor
           AND updated_at = actual.updated_at;
        GET DIAGNOSTICS changed = ROW_COUNT;
        IF changed <> 1 THEN
            RAISE EXCEPTION 'CAS update count mismatch for id %', actual.id;
        END IF;
        affected := affected + changed;
    END LOOP;

    IF affected <> 7 THEN
        RAISE EXCEPTION 'total update count mismatch: %', affected;
    END IF;
    IF EXISTS (SELECT 1 FROM stable_raceresultreviewrun WHERE status = 'claimed') THEN
        RAISE EXCEPTION 'claimed rows remain after reconciliation';
    END IF;
END
$reconcile$;

COMMIT;
