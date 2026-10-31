"""单连接、逐事务P02迁移owner；宿主协调器先建立真实停写与恢复面。"""

from contextlib import contextmanager
from pathlib import Path
import time

from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from stable.services import release_0079_recovery as old
from stable.services import release_p02_recovery as c
from stable.services import release_p02_schema as schema

LOCK_KEY = 704020086
WRITER_FLAGS = (*old.WRITER_FLAGS, "RACE_LIFECYCLE_V2_WRITE_ENABLED", "RACE_LIFECYCLE_DELIVERY_ENABLED")


def assert_closed_settings():
    if any(bool(getattr(settings, key, False)) for key in WRITER_FLAGS):
        raise ValueError("P02 control settings contain an enabled writer")
    if getattr(settings, "RACE_LIFECYCLE_V2_EVENT_IDS", ()):
        raise ValueError("P02 closed upgrade requires an empty cohort")


@contextmanager
def migration_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        if not cursor.fetchone()[0]:
            raise ValueError("P02 migration coordinator already holds the database lock")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def admission(directory, intent_sha, bindings):
    assert_closed_settings()
    intent, _ = c.verified_intent(directory, intent_sha, bindings)
    expected = schema.catalog_contract()["states"][0]["canonical_catalog_sha256"]
    if intent.get("source_catalog_sha256") != expected:
        raise ValueError("P02 intent source catalog differs from reviewed source")
    backup, identity = c.verified_backup(directory, intent_sha, intent)
    handoff, _ = c.read_artifact(Path(directory) / "handoff.json", kind="handoff", intent_sha=intent_sha)
    if (handoff.get("backup_sha256") != identity["sha256"]
            or handoff.get("closed_sha256") != backup["closed_sha256"]):
        raise ValueError("P02 handoff is not bound to this backup and closed cut")
    live = schema.state()
    c.validate_bindings(bindings, {**bindings,
        "database_identity_sha256": live["database_identity_sha256"],
        "migration_contract_sha256": live["migration_contract_sha256"],
    })
    schema.assert_no_other_clients()
    if live["prefix"] == 0:
        closed, _ = c.read_artifact(Path(directory) / "closed.json", kind="closed",
            sha=backup["closed_sha256"], intent_sha=intent_sha)
        if (c.digest(schema.counts()) != closed["source_counts_sha256"]
                or schema.security_snapshot() != closed["source_security_sha256"]):
            raise ValueError("P02 source changed since closed backup cut")
    return live


def step_intent(directory, intent_sha, index):
    states = schema.catalog_contract()["states"]
    return c.write_artifact(Path(directory) / f"step-{index}.json", kind="step", intent_sha=intent_sha,
        index=index, migration=c.STEPS[index - 1],
        before_catalog_sha256=states[index - 1]["canonical_catalog_sha256"],
        after_catalog_sha256=states[index]["canonical_catalog_sha256"])


def step_complete(directory, intent_sha, index, step_sha):
    return c.write_artifact(Path(directory) / f"step-{index}-complete.json", kind="step-complete",
        intent_sha=intent_sha, index=index, step_sha256=step_sha,
        catalog_sha256=schema.catalog_contract()["states"][index]["canonical_catalog_sha256"])


def apply(directory, intent_sha, bindings, *, checkpoint=lambda stage: None):
    """checkpoint仅供故障测试注入；生产命令没有跳过、fake或强制参数。"""
    directory = Path(directory)
    timings = []
    if connection.in_atomic_block:
        raise ValueError("P02 migration owner must own its transaction boundaries")
    with migration_lock():
        live = admission(directory, intent_sha, bindings)
        completed = c.verify_journal(directory, intent_sha, live["prefix"])
        # 重验所有现有step内容，不能只相信可自洽的SHA引用。
        for index in range(1, live["prefix"] + 1):
            identity = step_intent(directory, intent_sha, index)
            if index <= completed:
                step_complete(directory, intent_sha, index, identity["sha256"])
        if live["prefix"] == completed + 1:
            index = live["prefix"]
            identity = step_intent(directory, intent_sha, index)
            step_complete(directory, intent_sha, index, identity["sha256"])
            checkpoint(f"recovered-{index}")
        for index in range(live["prefix"] + 1, len(c.STEPS) + 1):
            live = admission(directory, intent_sha, bindings)
            if live["prefix"] != index - 1:
                raise ValueError("P02 recorder changed between migration steps")
            c.verify_journal(directory, intent_sha, live["prefix"])
            identity = step_intent(directory, intent_sha, index)
            checkpoint(f"before-{index}")
            executor = MigrationExecutor(connection)
            target = ("stable", c.STEPS[index - 1])
            plan = executor.migration_plan([target])
            if [(m.app_label, m.name, backwards) for m, backwards in plan] != [("stable", target[1], False)]:
                raise ValueError("P02 executor plan is not the exact next migration")
            if not plan[0][0].atomic:
                raise ValueError("P02 requires an atomic migration")
            started = time.monotonic()
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout='5s'")
                    cursor.execute("SET LOCAL statement_timeout='120s'")
                executor.migrate([target], plan=plan)
                contract = schema.catalog_contract()
                if c.applied_prefix(contract["source_recorder"], schema.recorder()) != index:
                    raise ValueError("P02 recorder changed inside migration")
                if c.digest(schema.normalized_catalog(schema.collect_catalog(), contract)) != contract["states"][index]["canonical_catalog_sha256"]:
                    raise ValueError("P02 catalog drift inside migration transaction")
                checkpoint(f"inside-{index}")
            timings.append({"index": index, "seconds": time.monotonic() - started})
            checkpoint(f"committed-{index}")
            step_complete(directory, intent_sha, index, identity["sha256"])
            checkpoint(f"receipted-{index}")
        live = admission(directory, intent_sha, bindings)
        if live["prefix"] != len(c.STEPS) or c.verify_journal(directory, intent_sha, live["prefix"]) != len(c.STEPS):
            raise ValueError("P02 target is not complete")
        identity = c.write_artifact(directory / "schema-complete.json", kind="schema-complete",
            intent_sha=intent_sha, catalog_sha256=live["catalog_sha256"],
            recorder_sha256=live["recorder_sha256"], target=c.STEPS[-1])
        return {"status": "schema-complete", "receipt_sha256": identity["sha256"], "timings": timings}
