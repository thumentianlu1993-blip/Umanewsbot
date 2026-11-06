#!/usr/bin/env python3
"""在专用回环PG16库生成待审核catalog；不是生产准入工具。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from stable.services import release_p02_recovery as c
    from stable.services import release_p02_schema as s
    import psycopg
    from psycopg import sql

    conf = connection.settings_dict
    if (connection.vendor != "postgresql" or conf["HOST"] != "127.0.0.1"
            or conf["NAME"] != "release_p02_catalog_source"
            or os.environ.get("P02_CATALOG_GENERATION") != "isolated-only"):
        raise ValueError("catalog generation requires the explicit isolated loopback database")
    if args.output.exists():
        raise ValueError("catalog candidate already exists; preserve original evidence")
    args.evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    params = {"host": "127.0.0.1", "port": conf["PORT"], "user": conf["USER"], "password": conf["PASSWORD"]}
    admin = psycopg.connect(dbname="postgres", autocommit=True, **params)
    with connection.cursor() as q:
        q.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        if q.fetchone()[0]:
            raise ValueError("catalog generation source must be empty")
    executor = MigrationExecutor(connection)
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "stable"]
    executor.migrate([*targets, ("stable", c.SOURCE)])
    result = {"migration_contract_sha256": c.migration_contract(), "source_recorder": s.recorder(),
              "states": [], "constraint_normalizations": []}
    env = {**os.environ, "PGPASSWORD": conf["PASSWORD"]}
    pgargs = ["-h", "127.0.0.1", "-p", str(conf["PORT"]), "-U", conf["USER"]]
    for index in range(7):
        if index:
            MigrationExecutor(connection).migrate([("stable", c.STEPS[index - 1])])
        original = s.collect_catalog()
        sha = c.digest(original)
        (args.evidence / f"catalog-{index}.json").write_bytes(c.encoded(original))
        dump = args.evidence / f"catalog-{index}.dump"
        subprocess.run(["pg_dump", *pgargs, "-d", conf["NAME"], "-Fc", "-f", str(dump)], env=env, check=True, capture_output=True)
        restored_name = f"release_p02_catalog_restore_{index}"
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_name)))
        try:
            subprocess.run(["pg_restore", *pgargs, "--exit-on-error", "-d", restored_name, str(dump)], env=env, check=True, capture_output=True)
            connection.close()
            conf["NAME"] = restored_name
            restored = s.collect_catalog()
            (args.evidence / f"catalog-{index}-restored.json").write_bytes(c.encoded(restored))
            restored_sha = c.digest(restored)
            for key in original:
                if key != "constraints" and original[key] != restored[key]:
                    raise ValueError(f"unreviewed restore semantic change: {key}")
            if len(original["constraints"]) != len(restored["constraints"]):
                raise ValueError("restored constraint count differs")
            for before, after in zip(original["constraints"], restored["constraints"]):
                if before == after:
                    continue
                expected = before["definition"].replace("::character varying", "::character varying::text").replace("]::text[]", "]")
                if before["type"] != "c" or after != {**before, "definition": expected}:
                    raise ValueError("unreviewed restore constraint change")
                pair = {"original": before, "restored": after}
                if pair not in result["constraint_normalizations"]:
                    result["constraint_normalizations"].append(pair)
            result["states"].append({"prefix": index, "canonical_catalog_sha256": sha,
                                     "accepted_catalog_sha256": sorted({sha, restored_sha})})
        finally:
            connection.close()
            conf["NAME"] = "release_p02_catalog_source"
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restored_name)))
        print(f"prefix {index}: migrated and fully restored", flush=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    admin.close()
    connection.close()


if __name__ == "__main__":
    main()
