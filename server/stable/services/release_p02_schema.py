"""P02精确schema与数据库身份；只接受经审核冻结的PG16 catalog。"""

import hashlib
import json
import copy
from pathlib import Path

from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from stable.services import release_p02_recovery as c

CATALOG_FILE = Path(__file__).resolve().parent.parent / "fixtures/release_p02_catalog.json"
CATALOG_SHA256 = "47d7605f29bd347ebf28b901304942b0c75bb55e9ef2c24fc92965830f5342c8"


def rows(cursor, query, params=()):
    cursor.execute(query, params)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def database_identity():
    # 仅同名DSN不足：重建数据库或切换集群也必须拒绝续跑。
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT s.system_identifier::text, d.oid::bigint, current_database(),
                   pg_encoding_to_char(d.encoding), d.datcollate, d.datctype
            FROM pg_control_system() s CROSS JOIN pg_database d
            WHERE d.datname=current_database()
        """)
        system, oid, database, encoding, collate, ctype = cursor.fetchone()
    return c.digest({"system": system, "database_oid": oid, "database": database,
                     "encoding": encoding, "collate": collate, "ctype": ctype})


def collect_catalog():
    """采集完整public结构；不含OID、序列当前位置、用户数据与凭据。"""
    with connection.cursor() as q:
        q.execute("SHOW server_version_num")
        if int(q.fetchone()[0]) // 10000 != 16:
            raise ValueError("P02 reviewed catalog requires PostgreSQL 16")
        q.execute("SELECT current_schema()")
        if q.fetchone()[0] != "public":
            raise ValueError("P02 schema must be public")
        catalog = {}
        catalog["relations"] = rows(q, """
            SELECT t.relname AS name,t.relkind AS kind,t.relpersistence AS persistence,
              t.relrowsecurity AS rls,t.relforcerowsecurity AS force_rls,
              t.relreplident AS replica_identity,t.reloptions AS options,
              t.relispartition AS partition
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname='public' AND t.relkind IN ('r','p','v','m','f') ORDER BY t.relname
        """)
        catalog["columns"] = rows(q, """
            SELECT t.relname AS table_name,a.attname AS name,
              format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull AS not_null,
              a.attidentity AS identity,a.attgenerated AS generated,
              pg_get_expr(d.adbin,d.adrelid) AS default_expr,
              co.collname AS collation
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            JOIN pg_attribute a ON a.attrelid=t.oid
            LEFT JOIN pg_attrdef d ON d.adrelid=t.oid AND d.adnum=a.attnum
            LEFT JOIN pg_collation co ON co.oid=a.attcollation
            WHERE n.nspname='public' AND t.relkind IN ('r','p','v','m','f')
              AND a.attnum>0 AND NOT a.attisdropped ORDER BY t.relname,a.attname
        """)
        catalog["constraints"] = rows(q, """
            SELECT t.relname AS table_name,k.conname AS name,k.contype AS type,
              k.condeferrable AS deferrable,k.condeferred AS deferred,
              k.convalidated AS validated,pg_get_constraintdef(k.oid,true) AS definition
            FROM pg_constraint k JOIN pg_class t ON t.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname='public' ORDER BY t.relname,k.conname
        """)
        catalog["indexes"] = rows(q, """
            SELECT t.relname AS table_name,ci.relname AS name,i.indisvalid AS valid,
              i.indisready AS ready,i.indislive AS live,pg_get_indexdef(i.indexrelid) AS definition
            FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
            JOIN pg_class ci ON ci.oid=i.indexrelid JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname='public' ORDER BY t.relname,ci.relname
        """)
        # 内部FK触发器名称含OID，使用约束名与触发器语义；不因此忽略禁用状态。
        catalog["triggers"] = rows(q, """
            SELECT t.relname AS table_name,
              CASE WHEN g.tgisinternal THEN k.conname ELSE g.tgname END AS name,
              g.tgisinternal AS internal,g.tgenabled AS enabled,g.tgtype AS type,
              pn.nspname AS function_schema,p.proname AS function_name,
              CASE WHEN g.tgisinternal THEN NULL ELSE pg_get_triggerdef(g.oid,true) END AS definition
            FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            JOIN pg_proc p ON p.oid=g.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace
            LEFT JOIN pg_constraint k ON k.oid=g.tgconstraint
            WHERE n.nspname='public'
            ORDER BY t.relname,name,pn.nspname,p.proname,g.tgtype
        """)
        catalog["functions"] = rows(q, """
            SELECT p.proname AS name,pg_get_function_identity_arguments(p.oid) AS args,
              pg_get_functiondef(p.oid) AS definition,p.prosecdef AS security_definer,
              p.proconfig AS config
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prokind IN ('f','p')
              AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
                AND d.objid=p.oid AND d.deptype='e')
            ORDER BY p.proname,args
        """)
        catalog["views"] = rows(q, """
            SELECT t.relname AS name,pg_get_viewdef(t.oid,true) AS definition
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname='public' AND t.relkind IN ('v','m') ORDER BY t.relname
        """)
        catalog["sequences"] = rows(q, """
            SELECT s.relname AS name,t.relname AS table_name,a.attname AS column_name,
              d.deptype AS dependency,format_type(q.seqtypid,NULL) AS type,
              q.seqstart AS start,q.seqincrement AS increment,q.seqmin AS min,
              q.seqmax AS max,q.seqcache AS cache,q.seqcycle AS cycle
            FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace
            JOIN pg_sequence q ON q.seqrelid=s.oid
            LEFT JOIN pg_depend d ON d.objid=s.oid AND d.classid='pg_class'::regclass
              AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')
            LEFT JOIN pg_class t ON t.oid=d.refobjid
            LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
            WHERE n.nspname='public' ORDER BY s.relname
        """)
        catalog["policies"] = rows(q, """
            SELECT tablename,policyname,permissive,roles,cmd,qual,with_check
            FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname
        """)
        catalog["extensions"] = rows(q, """
            SELECT e.extname AS name,e.extversion AS version,n.nspname AS schema
            FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname
        """)
        catalog["types"] = rows(q, """
            SELECT t.typname AS name,t.typtype AS kind,t.typnotnull AS not_null,
              t.typdefault AS default_expr,e.enumlabel AS label,e.enumsortorder::text AS sort_order
            FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
            LEFT JOIN pg_enum e ON e.enumtypid=t.oid
            WHERE n.nspname='public' AND t.typtype IN ('e','d') ORDER BY t.typname,e.enumsortorder
        """)
        return catalog


def catalog_contract():
    raw = CATALOG_FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("P02 reviewed catalog fixture drift")
    value = json.loads(raw)
    if value["migration_contract_sha256"] != c.migration_contract() or len(value["states"]) != 7:
        raise ValueError("P02 catalog generation differs")
    return value


def normalized_catalog(catalog, contract):
    """仅归一化完整匹配的、实测审核过的PG16恢复表达式。"""
    value = copy.deepcopy(catalog)
    for pair in contract["constraint_normalizations"]:
        value["constraints"] = [pair["original"] if row == pair["restored"] else row
                                for row in value["constraints"]]
    return value


def recorder():
    with connection.cursor() as cursor:
        cursor.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
        return cursor.fetchall()


def state():
    if connection.vendor != "postgresql":
        raise ValueError("P02 requires PostgreSQL")
    contract = catalog_contract()
    with transaction.atomic():
        # READ ONLY保护预检；执行器在每次DDL事务外调用，避免嵌套改变隔离级别。
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        loader = MigrationLoader(connection)
        loader.check_consistent_history(connection)
        if loader.graph.leaf_nodes("stable") != [("stable", c.STEPS[-1])]:
            raise ValueError("P02 migration graph leaf drift")
        recorded = recorder()
        prefix = c.applied_prefix(contract["source_recorder"], recorded)
        catalog = collect_catalog()
        raw_sha = c.digest(catalog)
        expected = contract["states"][prefix]
        if c.digest(normalized_catalog(catalog, contract)) != expected["canonical_catalog_sha256"]:
            raise ValueError(f"P02 catalog drift at prefix {prefix}")
        return {
            "bootstrap_role": bootstrap_role(),
            "prefix": prefix,
            "catalog_sha256": expected["canonical_catalog_sha256"],
            "raw_catalog_sha256": raw_sha,
            "recorder_sha256": c.digest({"recorded": sorted(recorded)}),
            "database_identity_sha256": database_identity(),
            "migration_contract_sha256": c.migration_contract(),
        }


def counts():
    """恢复核对每表排序行内容与业务序列；recorder序列允许事务回滚留下空号。"""
    result = {"tables": {}, "sequences": {}}
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        tables = [r[0] for r in cursor.fetchall()]
        cursor.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")
        sequences = [r[0] for r in cursor.fetchall()]
        for name in tables:
            cursor.execute(f"SELECT row_to_json(t)::text FROM public.{connection.ops.quote_name(name)} t ORDER BY row_to_json(t)::text COLLATE \"C\"")
            digest, count = hashlib.sha256(), 0
            while batch := cursor.fetchmany(500):
                for row in batch:
                    data = row[0].encode()
                    digest.update(len(data).to_bytes(8, "big"))
                    digest.update(data)
                    count += 1
            result["tables"][name] = {"count": count, "sha256": digest.hexdigest()}
        for name in sequences:
            if name == "django_migrations_id_seq":
                # PostgreSQL nextval不回滚；只有框架recorder允许空号，业务序列仍精确核对。
                cursor.execute("SELECT last_value + CASE WHEN is_called THEN 1 ELSE 0 END > COALESCE((SELECT max(id) FROM django_migrations), 0) FROM django_migrations_id_seq")
                if cursor.fetchone()[0] is not True:
                    raise ValueError("P02 recorder sequence is behind its rows")
                continue
            cursor.execute(f"SELECT last_value,is_called FROM public.{connection.ops.quote_name(name)}")
            result["sequences"][name] = list(cursor.fetchone())
    return result


def assert_no_other_clients():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
              AND pid<>pg_backend_pid() AND backend_type='client backend'
        """)
        if cursor.fetchone()[0]:
            raise ValueError("P02 other database clients remain")
        cursor.execute("SELECT count(*) FROM pg_prepared_xacts WHERE database=current_database()")
        if cursor.fetchone()[0]:
            raise ValueError("P02 prepared database transactions remain")


def security_state():
    """只返回摘要，角色口令仅由私有pg_dumpall原件保存。"""
    with connection.cursor() as cursor:
        roles = rows(cursor, """
            SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,
              rolreplication,rolconnlimit,rolvaliduntil::text,rolbypassrls,rolconfig,actual_password AS rolpassword
            FROM (SELECT r.*,a.rolpassword AS actual_password FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid) role_state
            ORDER BY rolname
        """)
        grants = rows(cursor, """
            SELECT t.relname AS name,pg_get_userbyid(t.relowner) AS owner,CASE WHEN t.relacl IS NULL THEN NULL ELSE ARRAY(SELECT v::text FROM unnest(t.relacl) v ORDER BY v::text) END AS acl
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname='public' AND t.relkind IN ('r','p','v','m','S') ORDER BY t.relname
        """)
        membership = rows(cursor, """
            SELECT pg_get_userbyid(roleid) AS role,pg_get_userbyid(member) AS member,pg_get_userbyid(grantor) AS grantor,
              admin_option,inherit_option,set_option
            FROM pg_auth_members ORDER BY role,member,grantor
        """)
        defaults = rows(cursor, """
            SELECT pg_get_userbyid(d.defaclrole) AS role,n.nspname AS schema,d.defaclobjtype AS type,CASE WHEN d.defaclacl IS NULL THEN NULL ELSE ARRAY(SELECT v::text FROM unnest(d.defaclacl) v ORDER BY v::text) END AS acl
            FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
            ORDER BY role,n.nspname,d.defaclobjtype
        """)
        namespaces = rows(cursor, """
            SELECT nspname,pg_get_userbyid(nspowner) AS owner,CASE WHEN nspacl IS NULL THEN NULL ELSE ARRAY(SELECT v::text FROM unnest(nspacl) v ORDER BY v::text) END AS acl
            FROM pg_namespace WHERE nspname='public' ORDER BY nspname
        """)
        functions = rows(cursor, """
            SELECT p.proname,pg_get_function_identity_arguments(p.oid) AS args,
              pg_get_userbyid(p.proowner) AS owner,CASE WHEN p.proacl IS NULL THEN NULL ELSE ARRAY(SELECT v::text FROM unnest(p.proacl) v ORDER BY v::text) END AS acl
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' ORDER BY p.proname,args
        """)
        database = rows(cursor, """
            SELECT pg_get_userbyid(datdba) AS owner,CASE WHEN datacl IS NULL THEN NULL ELSE ARRAY(SELECT v::text FROM unnest(datacl) v ORDER BY v::text) END AS acl,
              datconnlimit AS connection_limit,datallowconn AS allow_connections
            FROM pg_database WHERE datname=current_database()
        """)
    return {"roles": roles, "grants": grants, "membership": membership, "defaults": defaults,
            "namespaces": namespaces, "functions": functions, "database": database}


def security_snapshot():
    return c.digest(security_state())

def bootstrap_role():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolname,rolsuper FROM pg_roles WHERE oid=10")
        row = cursor.fetchone()
        if not row or row[1] is not True:
            raise ValueError("P02 restore requires an unchanged superuser initdb role")
        return row[0]
