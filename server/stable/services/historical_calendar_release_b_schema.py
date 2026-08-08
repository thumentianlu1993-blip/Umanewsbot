from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from django.db import connection
from django.db.models import Count
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.recorder import MigrationRecorder

from stable.models import (
    HistoricalRaceEventTarget,
    HorseIdentityEvidenceCommitReceipt,
    OperationLog,
    RaceEvent,
)


SCHEMA_VERSION = "migration-history-repair-preflight/v2"
LEGACY_SCHEMA_VERSION = "historical-calendar-release-b-preflight/v1"
TARGET = ("stable", "0071_historical_calendar_release_b")
AUDIT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "changes"
    / "repair-production-migration-history"
    / "production_audit.json"
)

ALLOWED_FORWARD_STATES = {
    ("stable.0070_horse_identity_evidence_commit_receipt",): [
        "0068_race_data_sync_pipeline_a_field_audit",
        "0069_race_data_sync_pipeline_a_ledger_guards",
        "0071_historical_calendar_release_b",
    ],
    (
        "stable.0068_race_data_sync_pipeline_a_field_audit",
        "stable.0070_horse_identity_evidence_commit_receipt",
    ): [
        "0069_race_data_sync_pipeline_a_ledger_guards",
        "0071_historical_calendar_release_b",
    ],
    (
        "stable.0069_race_data_sync_pipeline_a_ledger_guards",
        "stable.0070_horse_identity_evidence_commit_receipt",
    ): ["0071_historical_calendar_release_b"],
    ("stable.0071_historical_calendar_release_b",): [],
}

# Exact recorder states reachable when Django executes the reviewed 0071 plan
# from the sole approved pre-0070 origin.  This is deliberately not merged
# into ALLOWED_FORWARD_STATES: ordinary Release B deploys must never acquire an
# initial-install bypass merely because they happen to see an old database.
INITIAL_INSTALL_FORWARD_STATES = {
    ("stable.0067_historical_calendar_release_a",): [
        "0070_horse_identity_evidence_commit_receipt",
        "0068_race_data_sync_pipeline_a_field_audit",
        "0069_race_data_sync_pipeline_a_ledger_guards",
        "0071_historical_calendar_release_b",
    ],
    ("stable.0070_horse_identity_evidence_commit_receipt",): [
        "0068_race_data_sync_pipeline_a_field_audit",
        "0069_race_data_sync_pipeline_a_ledger_guards",
        "0071_historical_calendar_release_b",
    ],
    (
        "stable.0068_race_data_sync_pipeline_a_field_audit",
        "stable.0070_horse_identity_evidence_commit_receipt",
    ): [
        "0069_race_data_sync_pipeline_a_ledger_guards",
        "0071_historical_calendar_release_b",
    ],
    (
        "stable.0069_race_data_sync_pipeline_a_ledger_guards",
        "stable.0070_horse_identity_evidence_commit_receipt",
    ): ["0071_historical_calendar_release_b"],
    ("stable.0071_historical_calendar_release_b",): [],
}

AUDIT_FIELDS = (
    "database_identity_sha256",
    "receipt_count",
    "receipt_rows_sha256",
    "operation_log_count",
    "operation_log_rows_sha256",
    "operation_log_fk_sha256",
)


def _canonicalize(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_reviewed_production_audit() -> dict:
    payload = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "migration-history-repair-production-audit/v1":
        raise ValueError("unsupported production audit schema_version")
    missing = [field for field in AUDIT_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"production audit missing fields: {','.join(missing)}")
    return payload


def compare_production_audit_baseline(*, expected: dict, live: dict) -> dict:
    drift_fields = [
        field for field in AUDIT_FIELDS if expected.get(field) != live.get(field)
    ]
    return {"ok": not drift_fields, "drift_fields": drift_fields}


def _diff_contract(expected: Any, live: Any, path: str, output: list[str]) -> None:
    if isinstance(expected, dict):
        if not isinstance(live, dict):
            output.append(path or "$")
            return
        for key in sorted(set(expected) | set(live)):
            child = f"{path}.{key}" if path else key
            if key not in expected or key not in live:
                output.append(child)
            else:
                _diff_contract(expected[key], live[key], child, output)
        return
    if isinstance(expected, list):
        if not isinstance(live, list) or expected != live:
            output.append(path or "$")
        return
    if expected != live:
        output.append(path or "$")


def compare_catalog_contract(*, expected: dict, live: dict) -> dict:
    drift_paths: list[str] = []
    _diff_contract(expected, live, "", drift_paths)
    return {"ok": not drift_paths, "drift_paths": sorted(set(drift_paths))}


def collect_live_production_audit() -> dict:
    receipt_fields = (
        "id",
        "created_at",
        "updated_at",
        "approved_sha256",
        "artifact_sha256",
        "approved_by",
        "approved_profile_ids",
        "before_after",
        "evidence_summary",
        "result_payload",
        "operation_log_id",
    )
    operation_fields = (
        "id",
        "action_type",
        "target_type",
        "target_id",
        "detail",
        "created_at",
        "admin_id",
    )
    receipts = list(
        HorseIdentityEvidenceCommitReceipt._base_manager.order_by("pk").values(
            *receipt_fields
        )
    )
    operation_ids = [row["operation_log_id"] for row in receipts]
    operations = list(
        OperationLog.objects.filter(pk__in=operation_ids).order_by("pk").values(
            *operation_fields
        )
    )
    fk_set = [row["operation_log_id"] for row in receipts]
    return {
        "database_identity_sha256": _database_identity_sha256(),
        "receipt_count": len(receipts),
        "receipt_rows_sha256": _digest(receipts),
        "operation_log_count": len(operations),
        "operation_log_rows_sha256": _digest(operations),
        "operation_log_fk_sha256": _digest(fk_set),
    }


def _format_node(node: tuple[str, str]) -> str:
    return f"{node[0]}.{node[1]}"


def _migration_state() -> dict:
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    try:
        loader.check_consistent_history(connection)
    except InconsistentMigrationHistory as exc:
        detail = re.sub(r"\s+", " ", str(exc)).strip()
        return {
            "applied_nodes": [],
            "migration_leaf_set": [],
            "migration_plan": [],
            "unknown_applied_migrations": [],
            "migration_graph_known": True,
            "migration_history_consistent": False,
            "migration_history_consistency_detail": {
                "error": "InconsistentMigrationHistory",
                "message": detail,
                "message_sha256": _digest(detail),
            },
            "migration_state_allowed": False,
            "expected_plan_for_leaf_set": None,
        }
    recorded = {
        node
        for node in MigrationRecorder(connection).applied_migrations()
        if node[0] == "stable"
    }
    known_nodes = set(loader.graph.node_map)
    unknown = sorted(recorded - known_nodes)
    applied = recorded & known_nodes
    leaves = sorted(
        node
        for node in applied
        if not any(child in applied for child in loader.graph.node_map[node].children)
    )
    plan = [
        name
        for app, name in loader.graph.forwards_plan(TARGET)
        if app == "stable" and (app, name) not in applied and name >= "0068"
    ]
    leaf_set = tuple(_format_node(node) for node in leaves)
    expected_plan = ALLOWED_FORWARD_STATES.get(leaf_set)
    return {
        "applied_nodes": sorted(_format_node(node) for node in applied),
        "migration_leaf_set": list(leaf_set),
        "migration_plan": plan,
        "unknown_applied_migrations": [_format_node(node) for node in unknown],
        "migration_graph_known": not unknown,
        "migration_history_consistent": True,
        "migration_history_consistency_detail": None,
        "migration_state_allowed": expected_plan is not None and plan == expected_plan,
        "expected_plan_for_leaf_set": expected_plan,
    }


def _database_identity_sha256() -> str:
    settings = connection.settings_dict
    return _digest(
        {
            "engine": settings.get("ENGINE", ""),
            "host": settings.get("HOST", ""),
            "name": settings.get("NAME", ""),
            "port": str(settings.get("PORT", "")),
            "vendor": connection.vendor,
        }
    )


def _fetch_dicts(cursor, sql: str, params: tuple = ()) -> list[dict]:
    cursor.execute(sql, params)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def collect_postgresql_catalog_contract() -> dict:
    """Collect normalized pg_catalog semantics used by the Release B gate."""
    if connection.vendor != "postgresql":
        return {"vendor": connection.vendor, "checked": False}
    tables = (
        "stable_horseidentityevidencecommitreceipt",
        "stable_raceeventfieldchange",
        "stable_raceevent",
        "stable_historicalraceeventtarget",
    )
    release_b_index_names = (
        "uq_race_event_series_edition",
        "uq_hist_target_active_series_year",
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        schema_name = cursor.fetchone()[0] or ""
        columns = _fetch_dicts(
            cursor,
            """
            SELECT c.relname AS table_name, a.attname AS column_name,
                   a.attnum AS ordinal, pg_catalog.format_type(a.atttypid, a.atttypmod) AS type,
                   a.attnotnull AS not_null,
                   a.attidentity AS identity,
                   COALESCE(pg_get_expr(d.adbin, d.adrelid), '') AS default_expr
              FROM pg_attribute a
              JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
         LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
             WHERE n.nspname = current_schema()
               AND c.relname = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
          ORDER BY c.relname, a.attnum
            """,
            (list(tables),),
        )
        constraints = _fetch_dicts(
            cursor,
            """
            SELECT c.relname AS table_name, con.conname AS name, con.contype AS type,
                   con.convalidated AS validated, con.condeferrable AS deferrable,
                   con.condeferred AS initially_deferred,
                   pg_get_constraintdef(con.oid, false) AS definition,
                   COALESCE(rt.relname, '') AS target_table,
                   ARRAY(
                       SELECT a.attname
                         FROM unnest(con.conkey) WITH ORDINALITY AS x(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.conrelid
                                            AND a.attnum = x.attnum
                        ORDER BY x.ord
                   ) AS columns,
                   ARRAY(
                       SELECT a.attname
                         FROM unnest(con.confkey) WITH ORDINALITY AS x(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.confrelid
                                            AND a.attnum = x.attnum
                        ORDER BY x.ord
                   ) AS target_columns,
                   con.confupdtype AS update_action, con.confdeltype AS delete_action,
                   con.confmatchtype AS match_type
              FROM pg_constraint con
              JOIN pg_class c ON c.oid = con.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
         LEFT JOIN pg_class rt ON rt.oid = con.confrelid
             WHERE n.nspname = current_schema() AND c.relname = ANY(%s)
          ORDER BY c.relname, con.conname
            """,
            (list(tables),),
        )
        indexes = _fetch_dicts(
            cursor,
            """
            SELECT n.nspname AS schema_name, c.relname AS table_name,
                   i.relname AS name, am.amname AS method,
                   ix.indisunique AS unique, ix.indisvalid AS valid,
                   ix.indisready AS ready, ix.indislive AS live,
                   pg_get_indexdef(ix.indexrelid, 0, false) AS definition,
                   COALESCE(pg_get_expr(ix.indpred, ix.indrelid), '') AS predicate,
                   ARRAY(
                       SELECT pg_get_indexdef(ix.indexrelid, ord, true)
                         FROM generate_series(1, ix.indnkeyatts) AS ord
                        ORDER BY ord
                   ) AS columns,
                   ARRAY(
                       SELECT opc.opcname
                         FROM unnest(ix.indclass::oid[]) WITH ORDINALITY AS x(opcoid, ord)
                         JOIN pg_opclass opc ON opc.oid = x.opcoid
                        ORDER BY x.ord
                   ) AS operator_classes
              FROM pg_index ix
              JOIN pg_class c ON c.oid = ix.indrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_class i ON i.oid = ix.indexrelid
              JOIN pg_am am ON am.oid = i.relam
             WHERE n.nspname = current_schema()
               AND (c.relname = ANY(%s) OR i.relname = ANY(%s))
          ORDER BY c.relname, i.relname
            """,
            (list(tables), list(release_b_index_names)),
        )
        sequences = _fetch_dicts(
            cursor,
            """
            SELECT s.relname AS name, t.relname AS owned_table, a.attname AS owned_column,
                   format_type(seq.seqtypid, NULL) AS type,
                   seq.seqstart AS start, seq.seqincrement AS increment,
                   seq.seqmin AS min, seq.seqmax AS max, seq.seqcache AS cache,
                   seq.seqcycle AS cycle
              FROM pg_sequence seq
              JOIN pg_class s ON s.oid = seq.seqrelid
              JOIN pg_namespace n ON n.oid = s.relnamespace
         LEFT JOIN pg_depend dep ON dep.objid = s.oid AND dep.deptype IN ('a', 'i')
         LEFT JOIN pg_class t ON t.oid = dep.refobjid
         LEFT JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = dep.refobjsubid
             WHERE n.nspname = current_schema()
               AND t.relname = 'stable_horseidentityevidencecommitreceipt'
          ORDER BY s.relname
            """,
        )
        triggers = _fetch_dicts(
            cursor,
            """
            SELECT c.relname AS table_name, tg.tgname AS name, tg.tgenabled AS enabled,
                   CASE WHEN (tg.tgtype & 2) <> 0 THEN 'BEFORE' ELSE 'AFTER' END AS timing,
                   (tg.tgtype & 1) <> 0 AS row_level,
                   ARRAY_REMOVE(ARRAY[
                       CASE WHEN (tg.tgtype & 4) <> 0 THEN 'INSERT' END,
                       CASE WHEN (tg.tgtype & 8) <> 0 THEN 'DELETE' END,
                       CASE WHEN (tg.tgtype & 16) <> 0 THEN 'UPDATE' END,
                       CASE WHEN (tg.tgtype & 32) <> 0 THEN 'TRUNCATE' END
                   ], NULL) AS events,
                   pg_get_triggerdef(tg.oid, false) AS definition,
                   p.proname AS function_name, l.lanname AS function_language,
                   pg_get_function_identity_arguments(p.oid) AS function_identity_arguments,
                   pg_get_function_result(p.oid) AS function_return_type,
                   p.provolatile AS function_volatility,
                   p.prosecdef AS function_security_definer,
                   regexp_replace(p.prosrc, '\\s+', ' ', 'g') AS function_body
              FROM pg_trigger tg
              JOIN pg_class c ON c.oid = tg.tgrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_proc p ON p.oid = tg.tgfoid
              JOIN pg_language l ON l.oid = p.prolang
             WHERE n.nspname = current_schema() AND NOT tg.tgisinternal
               AND c.relname = 'stable_raceeventfieldchange'
          ORDER BY tg.tgname
            """,
        )
        functions = _fetch_dicts(
            cursor,
            """
            SELECT p.proname AS name, l.lanname AS language,
                   pg_get_function_identity_arguments(p.oid) AS identity_arguments,
                   pg_get_function_result(p.oid) AS return_type,
                   p.provolatile AS volatility, p.prosecdef AS security_definer,
                   regexp_replace(p.prosrc, '\\s+', ' ', 'g') AS body
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
              JOIN pg_language l ON l.oid = p.prolang
             WHERE n.nspname = current_schema()
               AND p.proname = 'stable_reject_race_field_change_mutation'
          ORDER BY p.oid
            """,
        )
    for row in triggers:
        row["function_body_sha256"] = hashlib.sha256(
            row.pop("function_body").encode("utf-8")
        ).hexdigest()
    for row in functions:
        row["body_sha256"] = hashlib.sha256(row.pop("body").encode("utf-8")).hexdigest()
    return {
        "vendor": "postgresql",
        "checked": True,
        "schema_name": schema_name,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "sequences": sequences,
        "triggers": triggers,
        "functions": functions,
    }


FIELD_AUDIT_COLUMNS = {
    "celery_task_id",
    "contract_digest",
    "contract_version",
    "decision",
    "normalized_sha256",
    "observation_id",
    "parser_version",
    "raw_sha256",
    "registry_digest",
    "source_class",
    "source_updated_at",
}

DECISION_CHECK_CANONICAL = (
    "checkdecision=''ordecision=anyarray["
    "'applied','replayed','needs_review','rejected']"
)
RELEASE_B_PARTIAL_INDEX_PREDICATES = {
    "uq_race_event_series_edition": (
        "edition_yearisnotnullandrace_series_idisnotnull"
    ),
    "uq_hist_target_active_series_year": (
        "notresolution_status='superseded'"
    ),
}
GUARD_FUNCTION_BODY_SHA256 = (
    "2598a9fa2f8512b79d7a2ed5bfc09bbe09cb2f1e319fbdf713588325c7e467dd"
)

RECEIPT_CONSTRAINT_SET = [
    {
        "name": "stable_horseidentity_operation_log_id_f50ded4b_fk_stable_op",
        "type": "f",
        "validated": True,
        "deferrable": True,
        "initially_deferred": True,
        "definition": (
            "FOREIGN KEY (operation_log_id) REFERENCES "
            "stable_operationlog(id) DEFERRABLE INITIALLY DEFERRED"
        ),
        "target_table": "stable_operationlog",
        "columns": ["operation_log_id"],
        "target_columns": ["id"],
        "update_action": "a",
        "delete_action": "a",
        "match_type": "s",
    },
    {
        "name": "stable_horseidentityevidencecommitreceipt_approved_sha256_key",
        "type": "u",
        "validated": True,
        "deferrable": False,
        "initially_deferred": False,
        "definition": "UNIQUE (approved_sha256)",
        "target_table": "",
        "columns": ["approved_sha256"],
        "target_columns": [],
        "update_action": " ",
        "delete_action": " ",
        "match_type": " ",
    },
    {
        "name": "stable_horseidentityevidencecommitreceipt_operation_log_id_key",
        "type": "u",
        "validated": True,
        "deferrable": False,
        "initially_deferred": False,
        "definition": "UNIQUE (operation_log_id)",
        "target_table": "",
        "columns": ["operation_log_id"],
        "target_columns": [],
        "update_action": " ",
        "delete_action": " ",
        "match_type": " ",
    },
    {
        "name": "stable_horseidentityevidencecommitreceipt_pkey",
        "type": "p",
        "validated": True,
        "deferrable": False,
        "initially_deferred": False,
        "definition": "PRIMARY KEY (id)",
        "target_table": "",
        "columns": ["id"],
        "target_columns": [],
        "update_action": " ",
        "delete_action": " ",
        "match_type": " ",
    },
]

RECEIPT_INDEX_SET = [
    {
        "name": "stable_horseidentityevid_approved_sha256_bcbc5b6f_like",
        "method": "btree",
        "unique": False,
        "valid": True,
        "ready": True,
        "live": True,
        "predicate": "",
        "columns": ["approved_sha256"],
        "operator_classes": ["varchar_pattern_ops"],
    },
    {
        "name": "stable_horseidentityevidencecommitreceipt_approved_sha256_key",
        "method": "btree",
        "unique": True,
        "valid": True,
        "ready": True,
        "live": True,
        "predicate": "",
        "columns": ["approved_sha256"],
        "operator_classes": ["text_ops"],
    },
    {
        "name": "stable_horseidentityevidencecommitreceipt_operation_log_id_key",
        "method": "btree",
        "unique": True,
        "valid": True,
        "ready": True,
        "live": True,
        "predicate": "",
        "columns": ["operation_log_id"],
        "operator_classes": ["int8_ops"],
    },
    {
        "name": "stable_horseidentityevidencecommitreceipt_pkey",
        "method": "btree",
        "unique": True,
        "valid": True,
        "ready": True,
        "live": True,
        "predicate": "",
        "columns": ["id"],
        "operator_classes": ["int8_ops"],
    },
]


def _catalog_projection(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    return sorted(
        ({field: row.get(field) for field in fields} for row in rows),
        key=lambda row: row["name"],
    )


def validate_decision_check_definition(definition: str) -> bool:
    """Accept only Django/PostgreSQL's exact empty-or-four-values predicate."""
    compact = re.sub(r"\s+", "", (definition or "").lower())
    for cast in ("::charactervarying", "::text[]", "::text"):
        compact = compact.replace(cast, "")
    compact = compact.translate(str.maketrans("", "", "()"))
    return compact == DECISION_CHECK_CANONICAL


def validate_guard_function_contract(rows: list[dict]) -> bool:
    """Reject missing, drifted, or overloaded guard function definitions."""
    if len(rows) != 1:
        return False
    function = rows[0]
    return (
        function.get("name") == "stable_reject_race_field_change_mutation"
        and function.get("identity_arguments") == ""
        and function.get("language") == "plpgsql"
        and function.get("return_type") == "trigger"
        and function.get("volatility") == "v"
        and function.get("security_definer") is False
        and function.get("body_sha256") == GUARD_FUNCTION_BODY_SHA256
    )


def validate_release_b_partial_index_predicate(
    *, index_name: str, predicate: str
) -> bool:
    expected = RELEASE_B_PARTIAL_INDEX_PREDICATES.get(index_name)
    if expected is None:
        return False
    compact = re.sub(r"\s+", "", (predicate or "").lower())
    for cast in ("::charactervarying", "::text[]", "::text"):
        compact = compact.replace(cast, "")
    compact = compact.translate(str.maketrans("", "", "()"))
    return compact == expected


RELEASE_B_INDEX_OWNERS = {
    "uq_race_event_series_edition": "stable_raceevent",
    "uq_hist_target_active_series_year": "stable_historicalraceeventtarget",
}


def validate_release_b_index_owner(
    *,
    index_name: str,
    schema_name: str,
    table_name: str,
    expected_schema_name: str,
) -> bool:
    """Bind each Release B unique index to the exact current-schema relation."""
    expected_table_name = RELEASE_B_INDEX_OWNERS.get(index_name)
    return bool(
        expected_table_name
        and expected_schema_name
        and schema_name == expected_schema_name
        and table_name == expected_table_name
    )


def validate_legacy_event_partial_predicate(predicate: str) -> bool:
    compact = re.sub(r"\s+", "", (predicate or "").lower())
    compact = compact.translate(str.maketrans("", "", "()"))
    return compact == "race_series_idisnotnull"


def _legacy_constraint_contract_drift(
    *, constraints: list[dict], indexes: list[dict]
) -> list[str]:
    drift: list[str] = []
    event_name = "uq_race_event_series_year"
    target_name = "uq_historical_target_series_year"
    event_constraints = [row for row in constraints if row["name"] == event_name]
    event_indexes = [row for row in indexes if row["name"] == event_name]
    if event_constraints:
        drift.append("0071.legacy_event_constraint_absent")
    if len(event_indexes) != 1:
        drift.append("0071.legacy_event_index")
    else:
        row = event_indexes[0]
        if (
            row["table_name"] != "stable_raceevent"
            or row["method"] != "btree"
            or not row["unique"]
            or not row["valid"]
            or not row["ready"]
            or not row["live"]
            or row["columns"] != ["race_series_id", "year"]
            or row["operator_classes"] != ["int8_ops", "int2_ops"]
            or not validate_legacy_event_partial_predicate(row["predicate"])
        ):
            drift.append("0071.legacy_event_index")

    target_constraints = [row for row in constraints if row["name"] == target_name]
    target_indexes = [row for row in indexes if row["name"] == target_name]
    if len(target_constraints) != 1:
        drift.append("0071.legacy_target_constraint")
    else:
        row = target_constraints[0]
        if (
            row["table_name"] != "stable_historicalraceeventtarget"
            or row["type"] != "u"
            or not row["validated"]
            or row["deferrable"]
            or row["initially_deferred"]
            or row["columns"] != ["race_series_id", "year"]
            or row["target_table"]
            or row["target_columns"]
        ):
            drift.append("0071.legacy_target_constraint")
    if len(target_indexes) != 1:
        drift.append("0071.legacy_target_index")
    else:
        row = target_indexes[0]
        if (
            row["table_name"] != "stable_historicalraceeventtarget"
            or row["method"] != "btree"
            or not row["unique"]
            or not row["valid"]
            or not row["ready"]
            or not row["live"]
            or row["predicate"]
            or row["columns"] != ["race_series_id", "year"]
            or row["operator_classes"] != ["int8_ops", "int2_ops"]
        ):
            drift.append("0071.legacy_target_index")
    return drift


def database_vendor_contract() -> dict:
    """Return the fail-closed database-engine contract without issuing SQL."""
    actual = connection.vendor
    return {
        "ok": actual == "postgresql",
        "expected": "postgresql",
        "actual": actual,
    }


def _postgres_catalog_state(
    contract: dict,
    applied_nodes: set[str],
    *,
    allow_unchecked_nonproduction: bool = False,
) -> dict:
    if not contract.get("checked"):
        vendor = contract.get("vendor", "unknown")
        allowed = allow_unchecked_nonproduction and vendor != "postgresql"
        return {
            "ok": allowed,
            "drift_paths": [] if allowed else ["database.catalog_checked"],
            "catalog_sha256": _digest(contract),
        }
    by_table: dict[str, list[dict]] = {}
    for row in contract["columns"]:
        by_table.setdefault(row["table_name"], []).append(row)
    constraints = {row["name"]: row for row in contract["constraints"]}
    indexes = {row["name"]: row for row in contract["indexes"]}
    triggers = {row["name"]: row for row in contract["triggers"]}
    guard_functions = [
        row
        for row in contract["functions"]
        if row["name"] == "stable_reject_race_field_change_mutation"
    ]
    sequences = contract["sequences"]
    drift: list[str] = []

    receipt_applied = "stable.0070_horse_identity_evidence_commit_receipt" in applied_nodes
    receipt_columns = by_table.get("stable_horseidentityevidencecommitreceipt", [])
    receipt_names = {row["column_name"] for row in receipt_columns}
    expected_receipt = {
        "id", "created_at", "updated_at", "approved_sha256", "artifact_sha256",
        "approved_by", "approved_profile_ids", "before_after", "evidence_summary",
        "result_payload", "operation_log_id",
    }
    if receipt_applied != bool(receipt_columns):
        drift.append("0070.table_presence")
    if receipt_applied and receipt_names != expected_receipt:
        drift.append("0070.columns")
    if receipt_applied:
        receipt_column_contract = {
            row["column_name"]: (row["type"], row["not_null"])
            for row in receipt_columns
        }
        expected_column_contract = {
            "id": ("bigint", True),
            "created_at": ("timestamp with time zone", True),
            "updated_at": ("timestamp with time zone", True),
            "approved_sha256": ("character varying(64)", True),
            "artifact_sha256": ("character varying(64)", True),
            "approved_by": ("character varying(255)", True),
            "approved_profile_ids": ("jsonb", True),
            "before_after": ("jsonb", True),
            "evidence_summary": ("jsonb", True),
            "result_payload": ("jsonb", True),
            "operation_log_id": ("bigint", True),
        }
        if receipt_column_contract != expected_column_contract:
            drift.append("0070.column_semantics")
        if any(row["default_expr"] for row in receipt_columns):
            drift.append("0070.column_defaults")
        receipt_id = next(
            (row for row in receipt_columns if row["column_name"] == "id"), None
        )
        if not receipt_id or receipt_id["identity"] != "d":
            drift.append("0070.id_identity")
        receipt_cons = [r for r in contract["constraints"] if r["table_name"] == "stable_horseidentityevidencecommitreceipt"]
        constraint_fields = (
            "name", "type", "validated", "deferrable", "initially_deferred",
            "definition", "target_table", "columns", "target_columns",
            "update_action", "delete_action", "match_type",
        )
        if _catalog_projection(receipt_cons, constraint_fields) != RECEIPT_CONSTRAINT_SET:
            drift.append("0070.constraint_set")
        if not any(r["type"] == "p" and r["validated"] and r["columns"] == ["id"] for r in receipt_cons):
            drift.append("0070.primary_key")
        if not any(r["type"] == "u" and r["columns"] == ["approved_sha256"] and r["validated"] for r in receipt_cons):
            drift.append("0070.approved_sha256_unique")
        if not any(r["type"] == "u" and r["columns"] == ["operation_log_id"] and r["validated"] for r in receipt_cons):
            drift.append("0070.operation_log_unique")
        fk = [r for r in receipt_cons if r["type"] == "f" and "operation_log_id" in r["definition"]]
        if (
            len(fk) != 1
            or not fk[0]["validated"]
            or fk[0]["delete_action"] != "a"
            or fk[0]["update_action"] != "a"
            or fk[0]["match_type"] != "s"
            or not fk[0]["deferrable"]
            or not fk[0]["initially_deferred"]
            or fk[0]["target_table"] != "stable_operationlog"
            or fk[0]["columns"] != ["operation_log_id"]
            or fk[0]["target_columns"] != ["id"]
        ):
            drift.append("0070.operation_log_fk")
        receipt_indexes = [r for r in contract["indexes"] if r["table_name"] == "stable_horseidentityevidencecommitreceipt"]
        index_fields = (
            "name", "method", "unique", "valid", "ready", "live",
            "predicate", "columns", "operator_classes",
        )
        if _catalog_projection(receipt_indexes, index_fields) != RECEIPT_INDEX_SET:
            drift.append("0070.index_set")
        if not receipt_indexes or any(not r["valid"] or not r["ready"] or not r["live"] for r in receipt_indexes):
            drift.append("0070.index_validity")
        if not any(
            r["method"] == "btree"
            and r["columns"] == ["approved_sha256"]
            and r["operator_classes"] == ["varchar_pattern_ops"]
            and not r["predicate"]
            for r in receipt_indexes
        ):
            drift.append("0070.pattern_index")
        if (
            len(sequences) != 1
            or sequences[0]["owned_table"] != "stable_horseidentityevidencecommitreceipt"
            or sequences[0]["owned_column"] != "id"
            or sequences[0]["type"] != "bigint"
            or sequences[0]["start"] != 1
            or sequences[0]["increment"] != 1
            or sequences[0]["min"] != 1
            or sequences[0]["max"] != 9223372036854775807
            or sequences[0]["cache"] != 1
            or sequences[0]["cycle"]
        ):
            drift.append("0070.sequence")

    field_columns = {
        row["column_name"]
        for row in by_table.get("stable_raceeventfieldchange", [])
    }
    present_fields = field_columns & FIELD_AUDIT_COLUMNS
    m68 = "stable.0068_race_data_sync_pipeline_a_field_audit" in applied_nodes
    if (m68 and present_fields != FIELD_AUDIT_COLUMNS) or (not m68 and present_fields):
        drift.append("0068.columns")
    if m68:
        field_contract = {
            row["column_name"]: (row["type"], row["not_null"])
            for row in by_table.get("stable_raceeventfieldchange", [])
            if row["column_name"] in FIELD_AUDIT_COLUMNS
        }
        expected_field_contract = {
            "celery_task_id": ("character varying(255)", True),
            "contract_digest": ("character varying(64)", True),
            "contract_version": ("character varying(64)", True),
            "decision": ("character varying(16)", True),
            "normalized_sha256": ("character varying(64)", True),
            "observation_id": ("bigint", False),
            "parser_version": ("character varying(64)", True),
            "raw_sha256": ("character varying(64)", True),
            "registry_digest": ("character varying(64)", True),
            "source_class": ("character varying(32)", True),
            "source_updated_at": ("timestamp with time zone", False),
        }
        if field_contract != expected_field_contract:
            drift.append("0068.column_semantics")
        if any(
            row["default_expr"]
            for row in by_table.get("stable_raceeventfieldchange", [])
            if row["column_name"] in FIELD_AUDIT_COLUMNS
        ):
            drift.append("0068.column_defaults")
        obs = [r for r in contract["constraints"] if r["table_name"] == "stable_raceeventfieldchange" and r["type"] == "f" and "observation_id" in r["definition"]]
        if (
            len(obs) != 1
            or not obs[0]["validated"]
            or obs[0]["delete_action"] != "a"
            or obs[0]["update_action"] != "a"
            or not obs[0]["deferrable"]
            or not obs[0]["initially_deferred"]
            or obs[0]["target_table"] != "stable_raceresultobservation"
            or obs[0]["columns"] != ["observation_id"]
            or obs[0]["target_columns"] != ["id"]
        ):
            drift.append("0068.observation_fk")

    m69 = "stable.0069_race_data_sync_pipeline_a_ledger_guards" in applied_nodes
    check = constraints.get("race_field_change_decision_valid")
    trigger = triggers.get("stable_race_field_change_append_only")
    guard_present = bool(check or trigger or guard_functions)
    if m69 != guard_present:
        drift.append("0069.object_presence")
    if m69:
        if (
            not check
            or not check["validated"]
            or not validate_decision_check_definition(check["definition"])
        ):
            drift.append("0069.decision_check")
        if (
            not trigger
            or trigger["enabled"] not in {"O", "A"}
            or trigger["timing"] != "BEFORE"
            or not trigger["row_level"]
            or sorted(trigger["events"]) != ["DELETE", "UPDATE"]
            or trigger["function_name"]
            != "stable_reject_race_field_change_mutation"
            or trigger["function_identity_arguments"] != ""
        ):
            drift.append("0069.trigger")
        elif trigger["function_language"] != "plpgsql" or trigger["function_return_type"] != "trigger" or trigger["function_security_definer"]:
            drift.append("0069.function")
        if (
            not validate_guard_function_contract(guard_functions)
        ):
            drift.append("0069.function")

    m71 = "stable.0071_historical_calendar_release_b" in applied_nodes
    old_names = {"uq_race_event_series_year", "uq_historical_target_series_year"}
    new_names = {"uq_race_event_series_edition", "uq_hist_target_active_series_year"}
    present_old = old_names & set(indexes)
    present_new = new_names & set(indexes)
    if m71:
        expected_schema_name = contract.get("schema_name", "")
        old_constraint_names = {
            row["name"] for row in contract["constraints"] if row["name"] in old_names
        }
        if present_old or old_constraint_names or present_new != new_names:
            drift.append("0071.constraint_matrix")
        for name in new_names:
            row = indexes.get(name)
            if row and (
                not row["unique"]
                or row["method"] != "btree"
                or not row["predicate"]
                or not row["valid"]
                or not row["ready"]
                or not row["live"]
            ):
                drift.append(f"0071.{name}")
        event_unique = indexes.get("uq_race_event_series_edition")
        if event_unique and (
            not validate_release_b_index_owner(
                index_name="uq_race_event_series_edition",
                schema_name=event_unique.get("schema_name", ""),
                table_name=event_unique.get("table_name", ""),
                expected_schema_name=expected_schema_name,
            )
            or event_unique["columns"] != ["race_series_id", "edition_year"]
            or not validate_release_b_partial_index_predicate(
                index_name="uq_race_event_series_edition",
                predicate=event_unique["predicate"],
            )
        ):
            drift.append("0071.uq_race_event_series_edition")
        target_unique = indexes.get("uq_hist_target_active_series_year")
        if target_unique and (
            not validate_release_b_index_owner(
                index_name="uq_hist_target_active_series_year",
                schema_name=target_unique.get("schema_name", ""),
                table_name=target_unique.get("table_name", ""),
                expected_schema_name=expected_schema_name,
            )
            or target_unique["columns"] != ["race_series_id", "year"]
            or not validate_release_b_partial_index_predicate(
                index_name="uq_hist_target_active_series_year",
                predicate=target_unique["predicate"],
            )
        ):
            drift.append("0071.uq_hist_target_active_series_year")
    else:
        if present_new:
            drift.append("0071.constraint_matrix")
        drift.extend(_legacy_constraint_contract_drift(
            constraints=contract["constraints"],
            indexes=contract["indexes"],
        ))
    return {
        "ok": not drift,
        "drift_paths": sorted(set(drift)),
        "catalog_sha256": _digest(contract),
    }


def validate_postgresql_catalog_contract(
    *,
    contract: dict,
    applied_nodes: set[str],
    allow_unchecked_nonproduction: bool = False,
) -> dict:
    """Public pure validator used by fixture tests and the closed-state verifier."""
    return _postgres_catalog_state(
        contract,
        applied_nodes,
        allow_unchecked_nonproduction=allow_unchecked_nonproduction,
    )


def _event_conflicts(direction: str) -> list[dict]:
    field = "edition_year" if direction == "forward" else "year"
    queryset = RaceEvent._base_manager.filter(race_series__isnull=False)
    if direction == "forward":
        queryset = queryset.filter(edition_year__isnull=False)
    groups = queryset.values("race_series_id", field).annotate(row_count=Count("pk")).filter(row_count__gt=1).order_by("race_series_id", field)
    rows = []
    for group in groups.iterator(chunk_size=500):
        ids = list(queryset.filter(race_series_id=group["race_series_id"], **{field: group[field]}).order_by("pk").values_list("pk", flat=True))
        rows.append({"race_series_id": group["race_series_id"], field: group[field], "event_ids": ids})
    return rows


def _target_conflicts(direction: str) -> list[dict]:
    queryset = HistoricalRaceEventTarget._base_manager.all()
    if direction == "forward":
        queryset = queryset.exclude(resolution_status="superseded")
    groups = queryset.values("race_series_id", "year").annotate(row_count=Count("pk")).filter(row_count__gt=1).order_by("race_series_id", "year")
    rows = []
    for group in groups.iterator(chunk_size=500):
        ids = list(queryset.filter(race_series_id=group["race_series_id"], year=group["year"]).order_by("pk").values_list("pk", flat=True))
        rows.append({"race_series_id": group["race_series_id"], "year": group["year"], "target_ids": ids})
    return rows


def _initial_legacy_counts() -> dict[str, int]:
    return {
        "race_events": RaceEvent._base_manager.count(),
        "historical_targets": HistoricalRaceEventTarget._base_manager.count(),
    }


def check_release_b_schema_compatibility(
    *,
    direction: Literal["forward", "reverse"],
    enforce_production_audit: bool = False,
    allow_nonproduction_database: bool = False,
) -> dict:
    if direction not in {"forward", "reverse"}:
        raise ValueError("direction must be forward or reverse")
    vendor = database_vendor_contract()
    if not vendor["ok"] and not allow_nonproduction_database:
        catalog = {"vendor": vendor["actual"], "checked": False}
        return {
            "schema_version": SCHEMA_VERSION,
            "legacy_schema_version": LEGACY_SCHEMA_VERSION,
            "direction": direction,
            "applied_nodes": [],
            "migration_leaf_set": [],
            "migration_leaf": "",
            "migration_plan": [],
            "unknown_applied_migrations": [],
            "migration_graph_known": False,
            "migration_state_allowed": False,
            "expected_plan_for_leaf_set": None,
            "database_identity_sha256": _database_identity_sha256(),
            "database_vendor": vendor,
            "event_conflict_count": 0,
            "target_conflict_count": 0,
            "rows_sha256": _digest({}),
            "catalog_sha256": _digest(catalog),
            "catalog_ok": False,
            "catalog_drift_paths": ["database.catalog_checked"],
            "production_audit_ok": False,
            "production_audit_drift_fields": [],
            "production_audit_live": None,
            "schema_checks_complete": False,
            "receipt_audit_safe": False,
            "ok": False,
            "drift_paths": ["database.vendor"],
        }
    # Recorder and pg_catalog are the only safe first read. In particular,
    # never let the receipt ORM touch a table/column merely because 0070 is
    # recorded: catalog drift must become structured output, not a backend
    # ProgrammingError. Database operational failures intentionally propagate.
    state = _migration_state()
    catalog = collect_postgresql_catalog_contract()
    catalog_state = _postgres_catalog_state(
        catalog,
        set(state["applied_nodes"]),
        allow_unchecked_nonproduction=allow_nonproduction_database,
    )
    schema_drift_paths = list(catalog_state["drift_paths"])
    if not state.get("migration_history_consistent", True):
        schema_drift_paths.append("migration.history_consistency")
    if not state["migration_graph_known"]:
        schema_drift_paths.append("migration.unknown_applied_migrations")
    if not state["migration_state_allowed"]:
        schema_drift_paths.append("migration.state")
    schema_safe = not schema_drift_paths

    event_conflicts: list[dict] = []
    target_conflicts: list[dict] = []
    audit_result = {"ok": True, "drift_fields": [], "live": None}
    if schema_safe:
        event_conflicts = _event_conflicts(direction)
        target_conflicts = _target_conflicts(direction)
    if schema_safe and enforce_production_audit:
        live = collect_live_production_audit()
        audit_result = {
            **compare_production_audit_baseline(
                expected=load_reviewed_production_audit(), live=live
            ),
            "live": live,
        }
    rows = {
        "event_conflicts": event_conflicts,
        "target_conflicts": target_conflicts,
        "unknown_applied_migrations": state["unknown_applied_migrations"],
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "legacy_schema_version": LEGACY_SCHEMA_VERSION,
        "direction": direction,
        **state,
        "migration_leaf": ",".join(state["migration_leaf_set"]),
        "database_identity_sha256": _database_identity_sha256(),
        "database_vendor": vendor,
        "event_conflict_count": len(event_conflicts),
        "target_conflict_count": len(target_conflicts),
        "rows_sha256": _digest(rows),
        "catalog_sha256": catalog_state["catalog_sha256"],
        "catalog_ok": catalog_state["ok"],
        "catalog_drift_paths": catalog_state["drift_paths"],
        "production_audit_ok": audit_result["ok"],
        "production_audit_drift_fields": audit_result["drift_fields"],
        "production_audit_live": audit_result["live"],
        "schema_checks_complete": True,
        "receipt_audit_safe": schema_safe,
    }
    result["ok"] = (
        state.get("migration_history_consistent", True)
        and state["migration_graph_known"]
        and state["migration_state_allowed"]
        and catalog_state["ok"]
        and audit_result["ok"]
        and not event_conflicts
        and not target_conflicts
    )
    drift_paths = list(schema_drift_paths)
    if event_conflicts:
        drift_paths.append("data.event_conflicts")
    if target_conflicts:
        drift_paths.append("data.target_conflicts")
    drift_paths.extend(
        f"production_audit.{field}" for field in audit_result["drift_fields"]
    )
    result["drift_paths"] = sorted(set(drift_paths))
    return result


def check_initial_install_schema_compatibility() -> dict:
    """Validate the exact legacy origin/progress without the 7-row audit."""
    vendor = database_vendor_contract()
    if not vendor["ok"]:
        return {
            "ok": False,
            "database_vendor": vendor,
            "drift_paths": ["database.vendor"],
            "schema_checks_complete": False,
        }
    state = _migration_state()
    leaf_set = tuple(state["migration_leaf_set"])
    expected_plan = INITIAL_INSTALL_FORWARD_STATES.get(leaf_set)
    progress_allowed = expected_plan is not None and state["migration_plan"] == expected_plan
    catalog = collect_postgresql_catalog_contract()
    catalog_state = _postgres_catalog_state(catalog, set(state["applied_nodes"]))
    drift = list(catalog_state["drift_paths"])
    if not state.get("migration_history_consistent", True):
        drift.append("migration.history_consistency")
    if not state["migration_graph_known"]:
        drift.append("migration.unknown_applied_migrations")
    if not progress_allowed:
        drift.append("migration.initial_install_progress")
    schema_safe = not drift
    event_conflicts = _event_conflicts("forward") if schema_safe else []
    target_conflicts = _target_conflicts("forward") if schema_safe else []
    legacy_counts = (
        _initial_legacy_counts()
        if schema_safe
        else {"race_events": None, "historical_targets": None}
    )
    if event_conflicts:
        drift.append("data.event_conflicts")
    if target_conflicts:
        drift.append("data.target_conflicts")
    result = {
        "schema_version": SCHEMA_VERSION,
        "legacy_schema_version": LEGACY_SCHEMA_VERSION,
        "direction": "forward",
        **state,
        "migration_state_allowed": progress_allowed,
        "expected_plan_for_leaf_set": expected_plan,
        "migration_leaf": ",".join(state["migration_leaf_set"]),
        "database_identity_sha256": _database_identity_sha256(),
        "database_vendor": vendor,
        "event_conflict_count": len(event_conflicts),
        "target_conflict_count": len(target_conflicts),
        "rows_sha256": _digest({
            "event_conflicts": event_conflicts,
            "target_conflicts": target_conflicts,
            "unknown_applied_migrations": state["unknown_applied_migrations"],
            "legacy_counts": legacy_counts,
        }),
        "catalog_sha256": catalog_state["catalog_sha256"],
        "catalog_ok": catalog_state["ok"],
        "catalog_drift_paths": catalog_state["drift_paths"],
        "production_audit_ok": True,
        "production_audit_drift_fields": [],
        "production_audit_live": None,
        "production_audit_policy": "initial-install-legacy-compatible",
        "schema_checks_complete": True,
        "receipt_audit_safe": False,
        "initial_install_origin": leaf_set
        == ("stable.0067_historical_calendar_release_a",),
        "initial_install_progress_allowed": progress_allowed,
        "initial_install_data_state": (
            "empty"
            if schema_safe and not any(legacy_counts.values())
            else "legacy-compatible" if schema_safe else "unchecked"
        ),
        "initial_install_legacy_counts": legacy_counts,
    }
    result["ok"] = (
        state.get("migration_history_consistent", True)
        and state["migration_graph_known"]
        and progress_allowed
        and catalog_state["ok"]
        and not event_conflicts
        and not target_conflicts
    )
    result["drift_paths"] = sorted(set(drift))
    return result


def collect_initial_install_completion_audit(*, expected: dict) -> dict:
    """Validate that an initial-install migration changed schema, not data."""
    live_counts = _initial_legacy_counts()
    receipt_count = HorseIdentityEvidenceCommitReceipt._base_manager.count()
    drift: list[str] = []
    if receipt_count != 0:
        drift.append("initial_install.receipt_count")
    if expected.get("data_state") not in {"empty", "legacy-compatible"}:
        drift.append("initial_install.data_state")
    if expected.get("legacy_counts") != live_counts:
        drift.append("initial_install.legacy_counts")
    return {
        "ok": not drift,
        "drift_paths": sorted(drift),
        "receipt_count": receipt_count,
        "legacy_counts": live_counts,
        "expected": expected,
    }
