#!/usr/bin/env python3
"""P02关闭态发布协调器；每个副作用前验证同一候选与存活锁。"""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from stable.services import release_p02_recovery as c

SERVICES = ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")


class Coordinator:
    def __init__(self, directory, plan, plan_sha, runtime):
        self.directory = Path(directory)
        self.plan = plan
        self.plan_sha = plan_sha
        self.runtime = runtime

    def checked(self, name, *args):
        self.runtime.verify()
        return getattr(self.runtime, name)(*args)

    def read(self, name, kind, intent_sha):
        return c.read_artifact(self.directory / name, kind=kind, intent_sha=intent_sha)

    def run(self, *, resume_sha="", checkpoint=lambda stage: None):
        directory, runtime = self.directory, self.runtime
        c.validate_bindings(self.plan, self.plan)
        if self.plan.get("schema_version") != c.VERSION or self.plan.get("kind") != "plan":
            raise ValueError("P02 plan generation differs")
        if not c.hex_value(self.plan_sha) or self.plan.get("migration_contract_sha256") != c.migration_contract():
            raise ValueError("P02 plan migration contract differs")
        self.checked("verify_rehearsal")
        if (directory / "intent.json").exists():
            intent, identity = c.verified_intent(directory, resume_sha, self.plan)
            if intent.get("plan_sha256") != self.plan_sha:
                raise ValueError("P02 resume plan differs from original intent")
        else:
            if resume_sha:
                raise ValueError("P02 original intent is missing")
            self.checked("guard_legacy")
            initial = self.checked("snapshot")
            c.validate_bindings(self.plan, initial)
            if initial["prefix"] != 0:
                raise ValueError("P02 initial deployment requires exact 0079")
            services = initial["services"]
            if set(services) != set(SERVICES) or any(type(value) is not bool for value in services.values()):
                raise ValueError("P02 source service inventory is incomplete")
            if not services["web"] or not services["nginx"]:
                raise ValueError("P02 source requires web and nginx for public probe")
            identity = c.write_artifact(directory / "intent.json", kind="intent",
                **{key: self.plan[key] for key in c.BINDINGS}, plan_sha256=self.plan_sha,
                source=c.SOURCE, migration_plan=list(c.STEPS), backup_directory=str(directory / "backup"),
                source_catalog_sha256=initial["catalog_sha256"],
                restore_services=services, old_image_ids=initial["old_image_ids"],
                p02_write=False, p02_delivery=False, cohort=[])
            intent, _ = c.verified_intent(directory, identity["sha256"], self.plan)
        intent_sha = identity["sha256"]
        checkpoint("intent")
        try:
            self.checked("ensure_marker", intent_sha)
            if (directory / "restored.json").exists():
                self.read("restored.json", "restored", intent_sha)
            if not (directory / "complete.json").exists():
                self.checked("close", intent)
                checkpoint("stopped")
                live = self.checked("closed_snapshot")
                if not (directory / "closed.json").exists():
                    if live["prefix"] != 0:
                        raise ValueError("P02 closed cut missing after migration")
                    c.write_artifact(directory / "closed.json", kind="closed", intent_sha=intent_sha,
                        services_stopped=True, clients=0, source_counts_sha256=live["counts_sha256"],
                        source_catalog_sha256=live["catalog_sha256"], source_security_sha256=live["security_sha256"])
                closed, closed_id = self.read("closed.json", "closed", intent_sha)
                if live["prefix"] == 0 and any(
                        live[key] != closed["source_" + key]
                        for key in ("counts_sha256", "catalog_sha256", "security_sha256")):
                    raise ValueError("P02 source changed since closed backup cut")
                checkpoint("closed")
                if not (directory / "backup.json").exists():
                    if live["prefix"] != 0 or live["counts_sha256"] != closed["source_counts_sha256"] or live["security_sha256"] != closed["source_security_sha256"]:
                        raise ValueError("P02 source changed since closed backup cut")
                    evidence = self.checked("backup_and_restore", intent, closed)
                    c.write_artifact(directory / "backup.json", kind="backup", intent_sha=intent_sha,
                        closed_sha256=closed_id["sha256"], source_catalog_sha256=intent["source_catalog_sha256"],
                        source_counts_sha256=closed["source_counts_sha256"], **evidence)
                _, backup_id = c.verified_backup(directory, intent_sha, intent)
                checkpoint("backup")
                c.write_artifact(directory / "handoff.json", kind="handoff", intent_sha=intent_sha,
                    closed_sha256=closed_id["sha256"], backup_sha256=backup_id["sha256"])
                checkpoint("handoff")
                # 即使schema完成也重新验证其精确内容；apply在target只读核对，不再执行DDL。
                self.checked("apply_schema", intent_sha)
                schema_receipt, schema_id = self.read("schema-complete.json", "schema-complete", intent_sha)
                checkpoint("schema")
                if not (directory / "static.json").exists():
                    evidence = self.checked("collect_static")
                    c.write_artifact(directory / "static.json", kind="static", intent_sha=intent_sha, **evidence)
                static, static_id = self.read("static.json", "static", intent_sha)
                self.checked("verify_static", static)
                checkpoint("static")
                # HTTP/只读数据库探针每次恢复关闭态后重验；旧成功记录不是当前成功证明。
                evidence = self.checked("readonly_probe", intent)
                if evidence.get("ok") is not True:
                    raise ValueError("P02 readonly public probes failed")
                probe_id = c.write_artifact(directory / "probe.json", kind="probe", intent_sha=intent_sha,
                    static_sha256=static_id["sha256"], catalog_sha256=schema_receipt["catalog_sha256"],
                    readonly=True, paths=evidence["paths"])
                checkpoint("probe")
                c.write_artifact(directory / "complete.json", kind="complete", intent_sha=intent_sha,
                    schema_sha256=schema_id["sha256"], static_sha256=static_id["sha256"], probe_sha256=probe_id["sha256"])
            complete, _ = self.read("complete.json", "complete", intent_sha)
            for filename, kind, key in (("schema-complete.json", "schema-complete", "schema_sha256"),
                                        ("static.json", "static", "static_sha256"), ("probe.json", "probe", "probe_sha256")):
                c.read_artifact(directory / filename, kind=kind, sha=complete[key], intent_sha=intent_sha)
            self.checked("verify_static", self.read("static.json", "static", intent_sha)[0])
            self.checked("verify_schema_complete", self.read("schema-complete.json", "schema-complete", intent_sha)[0])
            checkpoint("complete")
            self.checked("restore_services", intent)
            checkpoint("restoring")
            self.checked("verify_restored", intent)
            c.write_artifact(directory / "restored.json", kind="restored", intent_sha=intent_sha,
                complete_sha256=c.read_json(directory / "complete.json")[1]["sha256"],
                services=intent["restore_services"], candidate_image_id=self.plan["candidate_image_id"])
            checkpoint("restored")
            self.checked("clear_marker", intent_sha)
            return {"status": "restored", "intent_sha256": intent_sha}
        except BaseException:
            # intent之后所有副作用/收尾失败均停写；清理失败显式保留异常链。
            runtime.emergency_close(intent)
            raise



def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--resume-intent-sha256", default="")
    args = parser.parse_args()
    from p02_release_lock import ReleaseLock
    from p02_release_runtime import DockerRuntime
    plan, _ = c.read_artifact(args.plan, kind="plan", sha=args.plan_sha256)
    root = Path(__file__).resolve().parents[1]
    directory = c.private_directory(args.directory)
    # 与旧入口使用同一宿主资源域，不能由plan指定另一个锁逃避互斥。
    lock_dir = Path(os.environ.get("DEPLOYMENT_LOCK_DIR", "/tmp/umanews-deployment.lock")).resolve()
    metadata = {key: plan[key] for key in ("owner", "thread", "operation", "candidate_commit", "resource_domain")}
    with ReleaseLock(lock_dir, metadata) as lock:
        runtime = DockerRuntime(root, directory, plan, lock)
        result = Coordinator(directory, plan, args.plan_sha256, runtime).run(resume_sha=args.resume_intent_sha256)
    print(c.encoded(result).decode())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, RuntimeError):
        raise SystemExit("P02 release refused; preserve intent and inspect bounded evidence before resuming")
