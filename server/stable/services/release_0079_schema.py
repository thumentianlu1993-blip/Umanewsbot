"""0079 精确 recorder/catalog 合同；旧0078合同不变。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from stable.services import historical_calendar_release_b_schema as legacy
from stable.services import release_0079_recovery as contract

ENROLLMENT = "stable_racedatasyncenrollment"
NEW_TABLES = ("stable_racedatasyncsourcebinding", "stable_raceeventidentitykey")
NEW_COLUMNS = {
    "authority_version",
    "source_set_digest",
    "source_set_generation",
    "source_set_manifest",
}
CATALOG_FILE = (
    Path(__file__).resolve().parent.parent / "fixtures/release_0079_catalog.json"
)
CATALOG_SHA256 = "b42a71df0b39f694162f3662116e02bec088510b61f94fc4b1c8137c5848c597"


def normalize_restored_checks(rows):
    """PG16 dump/restore将varchar数组整体text cast改写为逐元素cast。

    只接受两个已审核枚举的两种完整等价表达式；不删除一般cast或运算符。
    """
    reviewed = {
        (ENROLLMENT, "race_data_enroll_state_valid"): (
            "proposed",
            "enrolled",
            "paused",
            "retired",
        ),
        ("stable_racedatasyncsourcebinding", "race_sync_binding_state"): (
            "active",
            "quarantined",
            "retired",
        ),
    }
    result = copy.deepcopy(rows)
    for row in result:
        values = reviewed.get((row["table_name"], row["name"]))
        if values and row["type"] == "c":
            items = ", ".join(f"'{v}'::character varying" for v in values)
            restored_items = ", ".join(
                f"'{v}'::character varying::text" for v in values
            )
            original = f"CHECK (state::text = ANY (ARRAY[{items}]::text[]))"
            restored = f"CHECK (state::text = ANY (ARRAY[{restored_items}]))"
            if row["definition"] == restored:
                row["definition"] = original
    return result


def collect_delta_catalog():
    """采集新增对象的完整列/约束/索引语义；不包含环境OID或schema名称。"""
    tables = [ENROLLMENT, *NEW_TABLES]
    with connection.cursor() as c:
        columns = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS table_name, a.attname AS column_name,
              format_type(a.atttypid,a.atttypmod) AS type, a.attnotnull AS not_null,
              a.attidentity AS identity, a.attgenerated AS generated,
              pg_get_expr(d.adbin,d.adrelid) AS default_expr
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            JOIN pg_attribute a ON a.attrelid=t.oid
            LEFT JOIN pg_attrdef d ON d.adrelid=t.oid AND d.adnum=a.attnum
            WHERE n.nspname=current_schema() AND t.relname=ANY(%s)
              AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY t.relname,a.attname""",
            (tables,),
        )
        constraints = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS table_name,k.conname AS name,k.contype AS type,
              k.condeferrable AS deferrable,k.condeferred AS deferred,
              k.convalidated AS validated,pg_get_constraintdef(k.oid,true) AS definition
            FROM pg_constraint k JOIN pg_class t ON t.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=current_schema() AND t.relname=ANY(%s)
            ORDER BY t.relname,k.conname""",
            (tables,),
        )
        indexes = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS table_name,ci.relname AS name,i.indisunique AS unique,
              i.indisprimary AS primary,i.indisvalid AS valid,i.indisready AS ready,
              i.indnkeyatts AS key_count,am.amname AS method,
              ARRAY(SELECT pg_get_indexdef(i.indexrelid,s,true)
                    FROM generate_series(1,i.indnatts) s) AS keys,
              pg_get_expr(i.indpred,i.indrelid) AS predicate
            FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
            JOIN pg_class ci ON ci.oid=i.indexrelid JOIN pg_am am ON am.oid=ci.relam
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=current_schema() AND t.relname=ANY(%s)
            ORDER BY t.relname,ci.relname""",
            (tables,),
        )
        triggers = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS table_name,g.tgname AS name,g.tgenabled AS enabled,
              pg_get_triggerdef(g.oid,true) AS definition
            FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=current_schema() AND t.relname=ANY(%s) AND NOT g.tgisinternal
            ORDER BY t.relname,g.tgname""",
            (tables,),
        )
        internal_triggers = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS constraint_table,k.conname AS constraint_name,
              tt.relname AS trigger_table,g.tgtype AS trigger_type,g.tgenabled AS enabled,
              pn.nspname AS function_schema,p.proname AS function_name,
              g.tgdeferrable AS deferrable,g.tginitdeferred AS initially_deferred
            FROM pg_trigger g JOIN pg_constraint k ON k.oid=g.tgconstraint
            JOIN pg_class t ON t.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            JOIN pg_class tt ON tt.oid=g.tgrelid
            JOIN pg_proc p ON p.oid=g.tgfoid
            JOIN pg_namespace pn ON pn.oid=p.pronamespace
            LEFT JOIN pg_class referenced ON referenced.oid=k.confrelid
            WHERE n.nspname=current_schema() AND g.tgisinternal
              AND (t.relname=ANY(%s) OR referenced.relname=ANY(%s))
            ORDER BY t.relname,k.conname,tt.relname,pn.nspname,p.proname,g.tgtype
            """,
            (tables, tables),
        )
        tables_meta = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS table_name,t.relkind AS kind,t.relpersistence AS persistence,
              t.relrowsecurity AS row_security,t.relforcerowsecurity AS force_row_security
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=current_schema() AND t.relname=ANY(%s) ORDER BY t.relname
            """,
            (tables,),
        )
        sequences = legacy._fetch_dicts(
            c,
            """
            SELECT t.relname AS table_name,a.attname AS column_name,s.relname AS name,
              d.deptype AS dependency,format_type(q.seqtypid,NULL) AS type,
              q.seqstart AS start,q.seqincrement AS increment,q.seqmin AS min,
              q.seqmax AS max,q.seqcache AS cache,q.seqcycle AS cycle
            FROM pg_class s JOIN pg_sequence q ON q.seqrelid=s.oid
            JOIN pg_depend d ON d.objid=s.oid AND d.classid='pg_class'::regclass
              AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')
            JOIN pg_class t ON t.oid=d.refobjid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
            WHERE n.nspname=current_schema() AND t.relname=ANY(%s)
            ORDER BY t.relname,a.attname,s.relname
            """,
            (tables,),
        )
    return dict(
        columns=columns,
        constraints=normalize_restored_checks(constraints),
        indexes=indexes,
        triggers=triggers,
        internal_triggers=internal_triggers,
        tables=tables_meta,
        sequences=sequences,
    )


def validate_catalog(*, old_catalog, delta, applied_nodes):
    target = contract.TARGET_LEAF in applied_nodes
    raw = CATALOG_FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("0079 reviewed catalog fixture drift")
    expected = json.loads(raw)["target" if target else "source"]
    drift = []
    legacy._diff_contract(expected, delta, "0079", drift)
    # 新增对象必须先通过完整独立合同；投影给旧纯validator时仅去掉已批准四列。
    projected = copy.deepcopy(old_catalog)
    if target:
        projected["columns"] = [
            r
            for r in projected["columns"]
            if not (r["table_name"] == ENROLLMENT and r["column_name"] in NEW_COLUMNS)
        ]
    old = legacy.validate_postgresql_catalog_contract(
        contract=projected, applied_nodes=applied_nodes
    )
    return sorted(set(drift + old["drift_paths"]))


def schema_state():
    if connection.vendor != "postgresql":
        raise ValueError("0079 production release requires PostgreSQL")
    contract.migration_contract()
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        loader.check_consistent_history(connection)
        known = {n for n in loader.graph.nodes if n[0] == "stable"}
        actual = {
            n
            for n in MigrationRecorder(connection).applied_migrations()
            if n[0] == "stable"
        }
        target = tuple(contract.TARGET_LEAF.split(".", 1))
        source = tuple(contract.SOURCE_LEAF.split(".", 1))
        expected_source = {
            n for n in loader.graph.forwards_plan(source) if n[0] == "stable"
        }
        expected_target = {
            n for n in loader.graph.forwards_plan(target) if n[0] == "stable"
        }
        if (
            loader.graph.leaf_nodes("stable") != [target]
            or actual not in (expected_source, expected_target)
            or actual - known
        ):
            raise ValueError("0079 recorder/graph is not exact source or target")
        nodes = {".".join(n) for n in actual}
        old = legacy.collect_postgresql_catalog_contract()
        delta = collect_delta_catalog()
        drift = validate_catalog(old_catalog=old, delta=delta, applied_nodes=nodes)
        if drift:
            raise ValueError("0079 catalog drift: " + ",".join(drift[:12]))
        leaf = contract.TARGET_LEAF if target in actual else contract.SOURCE_LEAF
        return dict(
            ok=True,
            migration_leaf_set=[leaf],
            migration_plan=[] if target in actual else [target[1]],
            migration_contract_sha256=contract.MIGRATION_CONTRACT_SHA256,
            database_identity_sha256=legacy._database_identity_sha256(),
            catalog_sha256=contract.digest({"legacy": old, "delta": delta}),
        )
