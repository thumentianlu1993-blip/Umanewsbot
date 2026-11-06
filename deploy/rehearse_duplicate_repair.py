#!/usr/bin/env python3
"""仅供本机禁网恢复演练；没有生产DSN、远端Docker或通用生产apply入口。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from stable.services.duplicate_repair_rehearsal import build_plan, digest, NEWS, TERM, EVIDENCE, WINDOW

BACKUP_SHA = "01c339772037efec52628deda7eb73210e3daa678dc674368fa8d026fc1b19c9"
LABEL = "duplicate-repair-20261101"
CATALOG_REVISION = "81cea5c48a79edaa9297ae00edd6093238063bda"
KEEP_NEWS = {6809, 9649, 9772, 9783, 9786, 9797, 16303, 16517}
CONSTRAINTS = {
    NEWS: ("uq_article_source_article_id", "UNIQUE (source_site, source_article_id)"),
    TERM: ("uq_term_candidate_type_normalized", "UNIQUE (term_type, source_language, normalized_key)"),
}
NEWS_REFS = {"stable_articlehorselink", "stable_articleracelink", "stable_automationlog",
    "stable_homepageheadlineselection", "stable_homepageheadlinerecommendation", "stable_mediaasset",
    "stable_newsarticlerelatedregion", "stable_newsimage", "stable_newssnapshot", "stable_pushlog",
    "stable_qqpushdelivery", "stable_raceeventfieldauthority", "stable_raceeventfieldchange",
    "stable_racenewsexposure", EVIDENCE, "stable_translationrun", WINDOW, "stable_windowtargetdecision"}
EXPECTED_FKS = {(t, "article_id", NEWS) for t in NEWS_REFS} | {
    (NEWS, "duplicate_of_id", NEWS), (TERM, "merged_into_candidate_id", TERM), (EVIDENCE, "candidate_id", TERM)}


def literal(value):
    return "'" + json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("'", "''") + "'::jsonb"


def identifier(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value): raise ValueError("invalid SQL identifier")
    return '"' + value + '"'


def publish(path, value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data: raise ValueError("immutable artifact differs")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out: out.write(data); out.flush(); os.fsync(out.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


class LocalCopy:
    def __init__(self, name, directory):
        if not re.fullmatch(r"p02-rehearsal-repair-[a-z0-9-]+", name): raise ValueError("not an isolated repair name")
        self.name, self.directory = name, Path(directory)
        self.socket = Path.home() / ".colima/p02-evidence-20261029/docker.sock"
        if not stat.S_ISSOCK(self.socket.stat().st_mode): raise ValueError("local Unix Docker socket required")
        self.docker = ["docker", "--host", "unix://" + str(self.socket)]
        self.env = {k: v for k, v in os.environ.items() if k not in {"DOCKER_HOST", "DOCKER_CONTEXT"}}
        self.verify()

    def run(self, args, *, text=None):
        p = subprocess.run([*self.docker, *args], input=text, text=True, capture_output=True, env=self.env, timeout=180)
        if p.returncode:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (self.directory / "failure.private.log").open("a") as out: out.write(p.stderr)
            raise ValueError("isolated Docker/SQL command failed; private diagnostic retained")
        return p.stdout

    def verify(self):
        x = json.loads(self.run(["inspect", self.name]))[0]
        h = x["HostConfig"]
        if (h["NetworkMode"] != "none" or h.get("PortBindings") or
                any(m["Type"] != "volume" for m in x["Mounts"]) or
                x["Config"].get("Labels", {}).get("io.umanews.rehearsal") != LABEL or
                not x["State"]["Running"]):
            raise ValueError("container is not a running, network-isolated, volume-only rehearsal")
        self.container_id, self.image = x["Id"], x["Image"]

    def sql(self, sql):
        self.verify()
        return self.run(["exec", "-i", self.name, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                         "-U", "horse_news", "-d", "horse_news"], text=sql)

    def read(self, sql):
        return json.loads(self.sql("BEGIN READ ONLY; SET LOCAL statement_timeout='120s'; SET LOCAL enable_indexscan=off; "
            "SET LOCAL enable_bitmapscan=off; " + sql + "; COMMIT;"))

    def identity(self):
        return self.read("SELECT jsonb_build_object('system_identifier',(SELECT system_identifier::text FROM pg_control_system()),"
            "'database_oid',(SELECT oid::text FROM pg_database WHERE datname=current_database()),'database',current_database())")

    def catalog(self):
        return self.read("SELECT jsonb_build_object('columns',(SELECT jsonb_agg(to_jsonb(x) ORDER BY table_name,ordinal_position) "
            "FROM (SELECT table_name,ordinal_position,column_name,data_type,is_nullable,column_default FROM information_schema.columns "
            "WHERE table_schema='public') x),'constraints',(SELECT jsonb_agg(jsonb_build_array(conrelid::regclass::text,conname,"
            "pg_get_constraintdef(oid),convalidated) ORDER BY conrelid::regclass::text,conname) FROM pg_constraint WHERE connamespace='public'::regnamespace),"
            "'indexes',(SELECT jsonb_agg(jsonb_build_array(indexrelid::regclass::text,pg_get_indexdef(indexrelid),indisvalid,indisready) "
            "ORDER BY indexrelid::regclass::text) FROM pg_index WHERE indrelid IN (SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace)),"
            "'recorder',(SELECT jsonb_agg(jsonb_build_array(app,name) ORDER BY app,name) FROM django_migrations))")

    def reviewed_schema(self, image, *, repaired=False):
        info = json.loads(self.run(["image", "inspect", image]))[0]
        if info.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision") != CATALOG_REVISION:
            raise ValueError("catalog verifier image is not the reviewed candidate")
        script = """
import os,json
os.environ['DJANGO_SETTINGS_MODULE']='app.p02_readonly_settings'
import django
django.setup()
from django.db import connection,transaction
from stable.services import release_p02_schema as s
from stable.services import release_p02_recovery as c
with transaction.atomic():
    with connection.cursor() as q:
        q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    contract=s.catalog_contract()
    if sorted(map(tuple,s.recorder())) != sorted(map(tuple,contract['source_recorder'])):
        raise ValueError('repair requires exact 0079 recorder')
    catalog=s.collect_catalog()
    missing=[('stable_newsarticle','uq_article_source_article_id','source_site, source_article_id'),
             ('stable_termcandidate','uq_term_candidate_type_normalized','term_type, source_language, normalized_key')]
    if os.environ['REPAIRED'] == 'false':
        for table,name,columns in missing:
            if any(row['name']==name for key in ('constraints','indexes') for row in catalog[key]):
                raise ValueError('expected exactly the two missing unique constraints')
            catalog['constraints'].append(dict(table_name=table,name=name,type='u',deferrable=False,
                deferred=False,validated=True,definition='UNIQUE ('+columns+')'))
            catalog['indexes'].append(dict(table_name=table,name=name,valid=True,ready=True,live=True,
                definition='CREATE UNIQUE INDEX '+name+' ON public.'+table+' USING btree ('+columns+')'))
        for key in ('constraints','indexes'):
            catalog[key].sort(key=lambda row:(row['table_name'],row['name']))
    actual=c.digest(s.normalized_catalog(catalog,contract))
    if actual != contract['states'][0]['canonical_catalog_sha256']:
        raise ValueError('repair schema differs beyond the two reviewed missing constraints')
    print(json.dumps(dict(canonical_catalog_sha256=actual, database_identity_sha256=s.database_identity())))
"""
        self.verify()
        result = self.run(["run", "--rm", "-i", "--network", "container:" + self.container_id,
            "--read-only", "--cap-drop", "ALL", "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
            "-e", "DB_ENGINE=postgres", "-e", "POSTGRES_HOST=127.0.0.1", "-e", "POSTGRES_USER=horse_news",
            "-e", "POSTGRES_DB=horse_news", "-e", "POSTGRES_PASSWORD=", "-e", "REPAIRED=" + str(repaired).lower(),
            info["Id"], "python", "-"], text=script)
        return {**json.loads(result), "catalog_image": info["Id"]}

    def scopes(self):
        fks = self.read("SELECT jsonb_agg(jsonb_build_array(conrelid::regclass::text,a.attname,confrelid::regclass::text)) "
            "FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1] WHERE contype='f' "
            "AND confrelid IN ('stable_newsarticle'::regclass,'stable_termcandidate'::regclass)")
        if {tuple(x) for x in fks} != EXPECTED_FKS: raise ValueError("inbound FK set changed")
        child_refs = self.read("SELECT to_jsonb(count(*)) FROM pg_constraint WHERE contype='f' "
            "AND confrelid IN ('stable_termcandidateevidence'::regclass,'stable_windowcandidatedecision'::regclass)")
        if child_refs: raise ValueError("child rows have unreviewed inbound references")
        ids = {}
        for table, keys, count in [(NEWS, "source_site,source_article_id", 47), (TERM, "term_type,source_language,normalized_key", 532)]:
            rows = self.read(f"SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb) FROM {table} WHERE ({keys}) IN "
                f"(SELECT {keys} FROM {table} GROUP BY {keys} HAVING count(*)>1)")
            if len(rows) != count: raise ValueError("fixed backup duplicate scope differs")
            ids[table] = ','.join(str(int(i)) for i in rows)
        scopes = {NEWS: f"id IN ({ids[NEWS]}) OR duplicate_of_id IN ({ids[NEWS]})",
                  TERM: f"id IN ({ids[TERM]}) OR merged_into_candidate_id IN ({ids[TERM]})"}
        for table in NEWS_REFS: scopes[table] = f"article_id IN ({ids[NEWS]})"
        scopes[EVIDENCE] += f" OR candidate_id IN ({ids[TERM]})"
        scopes["stable_productionwindow"] = (f"id IN (SELECT window_id FROM {WINDOW} WHERE {scopes[WINDOW]}) "
            f"OR id IN (SELECT window_id FROM stable_windowtargetdecision WHERE {scopes['stable_windowtargetdecision']})")
        return scopes

    def capture(self, scopes):
        return {table: self.read(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id),'[]'::jsonb) FROM {identifier(table)} t WHERE {where}")
                for table, where in sorted(scopes.items())}


def validate_plan(plan):
    computed = build_plan(plan["before"], KEEP_NEWS, {405}, observed_at=plan["observed_at"])
    for key, value in computed.items():
        if json.loads(json.dumps(value)) != plan[key]:
            raise ValueError("plan derivation differs: " + key)
    ids = {table: ','.join(str(int(r["id"])) for r in sorted(plan["before"][table], key=lambda r: r["id"]))
           for table in (NEWS, TERM)}
    scopes = {NEWS: f"id IN ({ids[NEWS]}) OR duplicate_of_id IN ({ids[NEWS]})",
              TERM: f"id IN ({ids[TERM]}) OR merged_into_candidate_id IN ({ids[TERM]})"}
    for table in NEWS_REFS: scopes[table] = f"article_id IN ({ids[NEWS]})"
    scopes[EVIDENCE] += f" OR candidate_id IN ({ids[TERM]})"
    scopes["stable_productionwindow"] = (f"id IN (SELECT window_id FROM {WINDOW} WHERE {scopes[WINDOW]}) "
        f"OR id IN (SELECT window_id FROM stable_windowtargetdecision WHERE {scopes['stable_windowtargetdecision']})")
    if plan["scopes"] != scopes or set(plan["before"]) != set(scopes):
        raise ValueError("plan scope differs")
    if plan["backup_sha256"] != BACKUP_SHA:
        raise ValueError("plan backup differs")


def guard_sql(table, where, expected):
    return (f"DO $guard$ BEGIN IF (SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id),'[]'::jsonb) FROM {identifier(table)} t "
            f"WHERE {where}) IS DISTINCT FROM {literal(expected)} THEN RAISE EXCEPTION 'rehearsal row drift: {table}'; "
            "END IF; END $guard$;")


def make_sql(plan, plan_sha, fail_at=None):
    before, after = plan["before"], plan["after"]
    tables = sorted(set(before) | {"stable_operationlog"})
    statements = ["BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='120s'; SET LOCAL enable_indexscan=off; SET LOCAL enable_bitmapscan=off;",
                  "SELECT pg_advisory_xact_lock(904201101);",
                  "LOCK TABLE " + ','.join(identifier(t) for t in tables) + " IN ACCESS EXCLUSIVE MODE;",
                  "DO $g$ BEGIN IF EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()) "
                  "THEN RAISE EXCEPTION 'residual database client'; END IF; END $g$;"]
    for table, where in plan["scopes"].items(): statements.append(guard_sql(table, where, before[table]))
    # Parent deletes follow child remapping; FK checks remain deferred until the final verification.
    order = [EVIDENCE, WINDOW] + [t for t in sorted(before) if t not in {EVIDENCE, WINDOW, NEWS, TERM}] + [TERM, NEWS]
    for table in order:
        prior = {r['id']: r for r in before[table]}; final = {r['id']: r for r in after[table]}
        removed = sorted(prior.keys() - final.keys())
        if removed: statements.append(f"DELETE FROM {identifier(table)} WHERE id IN ({','.join(map(str,removed))});")
        for pk, row in sorted(final.items()):
            changed = [k for k in row if row[k] != prior[pk][k]]
            if changed:
                cols = ','.join(identifier(k) for k in changed)
                statements.append(f"UPDATE {identifier(table)} SET ({cols})=(SELECT {cols} FROM jsonb_populate_record(NULL::{identifier(table)},"
                    f"{literal(row)})) WHERE id={int(pk)};")
        if fail_at == table: statements.append("SELECT 1/0;")
    statements.append("SET CONSTRAINTS ALL IMMEDIATE;")
    for table, (name, definition) in CONSTRAINTS.items(): statements.append(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition};")
    for table, where in plan["scopes"].items(): statements.append(guard_sql(table, where, after[table]))
    detail = json.dumps({"plan_sha256": plan_sha, "after_sha256": plan["after_sha256"], "isolation_only": True}, sort_keys=True).replace("'", "''")
    statements.append("INSERT INTO stable_operationlog(created_at,action_type,target_type,target_id,detail,admin_id) "
        f"VALUES (now(),'rehearsal_duplicate_repair','isolated_restore','{plan_sha}','{detail}',NULL);")
    if fail_at == "before_commit": statements.append("SELECT 1/0;")
    statements.append("COMMIT;")
    return '\n'.join(statements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "apply"])
    parser.add_argument("--container", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--catalog-image", default="p02-rehearsal-app:81cea5c4")
    parser.add_argument("--fail-at", choices=[EVIDENCE, WINDOW, TERM, NEWS, "before_commit", "after_commit"])
    args = parser.parse_args()
    directory = args.directory
    if directory.is_symlink(): raise ValueError("private artifact directory cannot be a symlink")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077: raise ValueError("artifact directory must be private")
    os.umask(0o077)
    runtime = LocalCopy(args.container, directory)
    code_sha = digest({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__), ROOT / "server/stable/services/duplicate_repair_rehearsal.py"]})
    path = directory / "plan.private.json"
    if args.mode == "prepare":
        if not args.backup or hashlib.file_digest(args.backup.open('rb'), 'sha256').hexdigest() != BACKUP_SHA:
            raise ValueError("reviewed backup identity differs")
        schema_proof = runtime.reviewed_schema(args.catalog_image)
        scopes = runtime.scopes(); before = runtime.capture(scopes)
        catalog = runtime.catalog()
        if any(c[1] in {v[0] for v in CONSTRAINTS.values()} for c in catalog['constraints']):
            raise ValueError("expected only the failed restore copy with missing unique constraints")
        observed_at = datetime.now(timezone.utc).isoformat()
        plan = build_plan(before, KEEP_NEWS, {405}, observed_at=observed_at)
        plan.update(before=before, scopes=scopes, code_sha256=code_sha, backup_sha256=BACKUP_SHA,
                    container_id=runtime.container_id, image=runtime.image, database=runtime.identity(), catalog=catalog, observed_at=observed_at, schema_proof=schema_proof)
        publish(path, plan)
        print(json.dumps({"status": "prepared_isolated_only", "plan_sha256": digest(json.loads(path.read_text()))})); return
    if path.is_symlink() or path.stat().st_mode & 0o077: raise ValueError("plan must be a private regular artifact")
    plan = json.loads(path.read_text()); sha = digest(plan)
    if not args.plan_sha256 or sha != args.plan_sha256: raise ValueError("explicit exact plan SHA required")
    if (plan['code_sha256'] != code_sha or plan['container_id'] != runtime.container_id or
            plan['image'] != runtime.image or plan['database'] != runtime.identity()): raise ValueError("binding drift")
    validate_plan(plan)
    receipts = runtime.read(f"SELECT coalesce(jsonb_agg(detail),'[]'::jsonb) FROM stable_operationlog WHERE action_type='rehearsal_duplicate_repair' "
        f"AND target_type='isolated_restore' AND target_id='{sha}'")
    if receipts:
        if runtime.reviewed_schema(plan["schema_proof"]["catalog_image"], repaired=True) != plan["schema_proof"]:
            raise ValueError("repaired schema binding differs")
        if len(receipts) != 1 or json.loads(receipts[0]).get('after_sha256') != plan['after_sha256']:
            raise ValueError("receipt differs")
        if digest(runtime.capture(plan['scopes'])) != plan['after_sha256']: raise ValueError("post-commit row drift")
        catalog = runtime.catalog()
        for table, (name, definition) in CONSTRAINTS.items():
            if [table, name, definition, True] not in catalog['constraints']: raise ValueError("restored constraint missing")
        publish(directory / "committed.json", {"plan_sha256": sha, "after_sha256": plan['after_sha256']})
        print(json.dumps({"status": "already_applied", "plan_sha256": sha})); return
    if runtime.reviewed_schema(plan["schema_proof"]["catalog_image"]) != plan["schema_proof"]:
        raise ValueError("source schema binding differs")
    if runtime.scopes() != plan["scopes"]: raise ValueError("scope drift")
    if runtime.catalog() != plan['catalog']: raise ValueError("catalog drift")
    if digest(runtime.capture(plan['scopes'])) != plan['before_sha256']: raise ValueError("before-image drift")
    publish(directory / "ready.json", {"plan_sha256": sha, "before_sha256": plan['before_sha256']})
    runtime.sql(make_sql(plan, sha, args.fail_at))
    if args.fail_at == "after_commit": raise ValueError("injected after-commit receipt interruption")
    publish(directory / "committed.json", {"plan_sha256": sha, "after_sha256": plan['after_sha256']})
    print(json.dumps({"status": "applied_isolated_only", "plan_sha256": sha}))


if __name__ == "__main__": main()
