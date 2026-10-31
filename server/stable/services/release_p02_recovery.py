"""P02发布合同；不修改旧代际合同，不直接访问数据库或服务。"""

import hashlib
import os
import re
from pathlib import Path

from stable.services.release_0078_recovery import (
    digest, encoded, file_evidence, hex_value, publish_once, read_json,
)

SOURCE = "0079_multisource_race_enrollment"
STEPS = (
    "0080_translation_retry_budget",
    "0081_managed_readonly_steps",
    "0083_race_lifecycle_publication",
    "0084_race_lifecycle_evidence_guards",
    "0085_race_observation_acquisition",
    "0086_race_lifecycle_observation_watermarks",
)
BINDINGS = (
    "candidate_commit", "candidate_image_id", "database_identity_sha256",
    "config_sha256", "migration_contract_sha256",
)
VERSION = "p02-release/v1"
# 完整目录而非仅六个新文件；以后增加迁移必须重新审核此代际。
MIGRATION_CONTRACT_SHA256 = "9a86bb646f0437834e7df22b44d878dbf0df008d0aaa604d103d356d94f08c3b"


def applied_prefix(base, recorded):
    base = [tuple(row) for row in base]
    recorded = [tuple(row) for row in recorded]
    if len(set(recorded)) != len(recorded) or len(set(base)) != len(base):
        raise ValueError("P02 duplicate recorder")
    additions = [("stable", step) for step in STEPS]
    if ("stable", SOURCE) not in base or set(base).intersection(additions):
        raise ValueError("P02 source recorder is not 0079")
    for count in range(len(STEPS) + 1):
        if set(recorded) == set(base + additions[:count]):
            return count
    raise ValueError("P02 recorder is not an exact continuous prefix")


def validate_bindings(expected, observed):
    for key in BINDINGS:
        value = expected.get(key)
        size = 40 if key == "candidate_commit" else 64
        if key == "candidate_image_id":
            valid = isinstance(value, str) and value.startswith("sha256:") and hex_value(value[7:])
        else:
            valid = hex_value(value, size)
        if not valid or observed.get(key) != value:
            raise ValueError(f"P02 binding mismatch: {key}")


def migration_contract():
    directory = Path(__file__).resolve().parent.parent / "migrations"
    manifest = "".join(
        f"{p.relative_to(directory).as_posix()}:{hashlib.sha256(p.read_bytes()).hexdigest()}\n"
        for p in sorted(directory.rglob("*.py"))
    )
    actual = hashlib.sha256(manifest.encode()).hexdigest()
    if actual != MIGRATION_CONTRACT_SHA256:
        raise ValueError("P02 migration file/content contract drift")
    return actual


def read_artifact(path, *, kind, sha="", intent_sha=""):
    payload, identity = read_json(Path(path), sha)
    if payload.get("schema_version") != VERSION or payload.get("kind") != kind:
        raise ValueError(f"P02 {kind} artifact generation mismatch")
    if intent_sha and payload.get("intent_sha256") != intent_sha:
        raise ValueError(f"P02 {kind} artifact belongs to another intent")
    return payload, identity


def write_artifact(path, *, kind, intent_sha="", **payload):
    value = {"schema_version": VERSION, "kind": kind, **payload}
    if intent_sha:
        if not hex_value(intent_sha):
            raise ValueError("P02 invalid intent SHA")
        value["intent_sha256"] = intent_sha
    return publish_once(Path(path), value)


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, exist_ok=True)
    # 复用已审核的逐目录fd检查，不跟随符号链接。
    from stable.services.release_0078_recovery import _parent
    fd = _parent(path / "probe.json")
    os.close(fd)
    return path


def verified_intent(directory, sha, bindings):
    directory = Path(directory)
    if not hex_value(sha):
        raise ValueError("P02 original intent SHA is required")
    intent, identity = read_artifact(directory / "intent.json", kind="intent", sha=sha)
    validate_bindings(bindings, intent)
    if intent.get("migration_plan") != list(STEPS) or intent.get("source") != SOURCE:
        raise ValueError("P02 intent migration plan differs")
    if intent.get("backup_directory") != str(directory / "backup"):
        raise ValueError("P02 intent backup directory differs")
    if intent.get("p02_write") is not False or intent.get("p02_delivery") is not False or intent.get("cohort") != []:
        raise ValueError("P02 closed upgrade cannot activate lifecycle writers")
    return intent, identity


def verified_backup(directory, intent_sha, intent):
    """恢复证明只接受完整恢复及同一停写切点；检查每个原始文件。"""
    directory = Path(directory)
    value, identity = read_artifact(directory / "backup.json", kind="backup", intent_sha=intent_sha)
    if value.get("source_catalog_sha256") != intent.get("source_catalog_sha256"):
        raise ValueError("P02 backup source catalog differs")
    restored = value.get("restore") or {}
    if (
        restored.get("status") != "verified"
        or restored.get("catalog_sha256") != intent.get("source_catalog_sha256")
        or restored.get("counts_sha256") != value.get("source_counts_sha256")
        or not hex_value(value.get("source_counts_sha256"))
        or not hex_value(restored.get("database_identity_sha256"))
        or restored.get("database_identity_sha256") == intent["database_identity_sha256"]
    ):
        raise ValueError("P02 complete isolated restore proof is required")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != {
        "database.dump", "roles.sql", "config.tar", "assets.tar", "images.tar",
    }:
        raise ValueError("P02 backup recovery surface is incomplete")
    for name, evidence in files.items():
        _, actual = file_evidence(directory / "backup" / name)
        if actual != evidence or actual["size"] <= 0:
            raise ValueError("P02 backup bytes or identity changed")
    if not hex_value(value.get("closed_sha256")):
        raise ValueError("P02 backup has no closed-state cut")
    closed, _ = read_artifact(directory / "closed.json", kind="closed", sha=value["closed_sha256"], intent_sha=intent_sha)
    if (closed.get("services_stopped") is not True or closed.get("clients") != 0
            or closed.get("source_catalog_sha256") != value["source_catalog_sha256"]
            or closed.get("source_counts_sha256") != value["source_counts_sha256"]
            or not hex_value(closed.get("source_security_sha256"))
            or restored.get("security_sha256") != closed["source_security_sha256"]):
        raise ValueError("P02 backup does not bind the closed data and permission cut")
    return value, identity


def verify_journal(directory, intent_sha, prefix):
    """已提交但尚未落回执只允许跨一步；无step intent绝不推断成功。"""
    directory = Path(directory)
    if type(prefix) is not int or not 0 <= prefix <= len(STEPS):
        raise ValueError("P02 invalid migration prefix")
    allowed = {f"step-{i}{suffix}.json" for i in range(1, 7) for suffix in ("", "-complete")}
    if any(path.name not in allowed for path in directory.glob("step-*.json")):
        raise ValueError("P02 journal contains an unknown migration step")
    completed = 0
    for index, step in enumerate(STEPS, 1):
        pending = directory / f"step-{index}.json"
        receipt = directory / f"step-{index}-complete.json"
        if pending.exists():
            value, pending_id = read_artifact(pending, kind="step", intent_sha=intent_sha)
            if value.get("index") != index or value.get("migration") != step:
                raise ValueError("P02 step intent mismatch")
            if index > completed + 1:
                raise ValueError("P02 journal is not contiguous")
        elif receipt.exists() or index <= prefix:
            raise ValueError("P02 committed migration has no original step intent")
        if receipt.exists():
            value, _ = read_artifact(receipt, kind="step-complete", intent_sha=intent_sha)
            if value.get("step_sha256") != pending_id["sha256"] or value.get("index") != index or index > prefix:
                raise ValueError("P02 step receipt differs from recorder")
            completed = index
    if prefix not in {completed, completed + 1}:
        raise ValueError("P02 unreceipted recorder drift")
    return completed

def restore_roles_sql(raw, bootstrap_role):
    """仅跳过全新恢复集群已存在的同名OID10角色CREATE；不改ALTER或任何授权。"""
    if not bootstrap_role or any(ch in bootstrap_role for ch in "\r\n"):
        raise ValueError("P02 unsupported bootstrap role")
    replaced, output = 0, []
    pattern = re.compile(r'^CREATE ROLE (?:"((?:""|[^"])*)"|([a-z_][a-z0-9_$]*));$')
    for line in raw.decode("utf-8").splitlines(keepends=True):
        match = pattern.fullmatch(line.rstrip("\r\n"))
        name = (match.group(1).replace('""', '"') if match.group(1) is not None else match.group(2)) if match else None
        if name == bootstrap_role:
            replaced += 1
            output.append("-- Existing isolated initdb role; original ALTER and GRANT retained.\n")
        else:
            output.append(line)
    if replaced != 1:
        raise ValueError("P02 roles backup must create the exact bootstrap role once")
    return "".join(output).encode("utf-8")
