#!/usr/bin/env python3
"""0078 prepare/resume coordinator; migration remains in run-release-tasks.sh."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from stable.services import release_0078_recovery as contract


ROOT = Path(os.environ.get("UMANEWS_ROOT_DIR") or Path(__file__).resolve().parents[1]).absolute()
REPAIR = ROOT / "runtime/migration_history_repair"
RELEASES = REPAIR / "release-0078-recovery"
COMPOSE_FILES = {"docker-compose.prod.yml", "docker-compose.prod.lowcost.yml"}


def run(argv, *, env=None, stdin=None) -> str:
    try:
        result = subprocess.run(
            [str(value) for value in argv], cwd=ROOT, env=env,
            stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        # Child output may contain a Compose configuration or database secret.
        raise ValueError(f"0078 release command failed: {Path(str(argv[0])).name}") from exc
    return result.stdout.decode("utf-8").strip()


def compose(args, env):
    return run([ROOT / "deploy/docker/compose-wrapper.sh", "-f", env["COMPOSE_FILE"], *args], env=env)


def private_directory(path):
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    fd = contract._parent(path / "probe.json")
    os.close(fd)


def reject_legacy_service_intent(env):
    lock_dir = env.get("DEPLOYMENT_LOCK_DIR", "/tmp/umanews-deployment.lock")
    if any(os.path.lexists(lock_dir + suffix) for suffix in (".race-live-state", ".race-data-sync-state")):
        raise ValueError("old service restore intent must be completed by its original control image")


def guard():
    reject_legacy_service_intent(os.environ)
    if os.path.lexists(RELEASES / "active.json"):
        raise ValueError("0078 release is in progress; use resume_migration_history_repair.sh with the original intent")
    for path in RELEASES.glob("*/intent.json"):
        if not os.path.lexists(path.parent / "complete.json"):
            raise ValueError("0078 preparation is incomplete; resume the original release")


def probe(service, env):
    ids = compose(["ps", "--all", "-q", service], env).split()
    if not ids:
        return {"running": False, "node": "", "container": ""}
    if len(ids) != 1:
        raise ValueError(f"0078 requires at most one {service} container")
    values = run(["docker", "inspect", "--format", "{{.State.Running}} {{.State.Status}} {{.Config.Hostname}}", ids[0]], env=env).split()
    if len(values) != 3 or values[0] not in {"true", "false"} or values[1] not in {"running", "exited", "created"}:
        raise ValueError(f"0078 cannot establish {service} state")
    return {"running": values[0] == "true", "node": values[2], "container": ids[0]}


def candidate(env):
    if env.get("COMPOSE_FILE") not in COMPOSE_FILES:
        raise ValueError("0078 compose file is not allowlisted")
    if not contract.hex_value(env.get("EXPECTED_CANDIDATE_COMMIT"), 40):
        raise ValueError("0078 exact candidate commit is required")
    if run(["git", "rev-parse", "HEAD"], env=env) != env["EXPECTED_CANDIDATE_COMMIT"]:
        raise ValueError("0078 candidate checkout changed")
    actual = run(["docker", "image", "inspect", "--format", "{{.Id}}", "umanewsbot:prod"], env=env)
    if actual != env.get("EXPECTED_CANDIDATE_IMAGE_ID"):
        raise ValueError("0078 candidate image changed")
    revision = run(["docker", "image", "inspect", "--format", '{{index .Config.Labels "org.opencontainers.image.revision"}}', "umanewsbot:prod"], env=env)
    if revision != env["EXPECTED_CANDIDATE_COMMIT"]:
        raise ValueError("0078 image revision differs from candidate")
    contract.migration_contract()


def schema_state(env, expected_leaf=None):
    candidate(env)
    args = ["run", "--rm", "--no-deps", "web", "python", "manage.py", "check_historical_calendar_release_b_schema", "--direction=forward", "--json"]
    if expected_leaf:
        args.append("--expected-migration-leaf-set=" + expected_leaf)
    result = json.loads(compose(args, env))
    if result.get("ok") is not True or result.get("database_identity_sha256") != env["EXPECTED_PRODUCTION_DB_IDENTITY_SHA256"]:
        raise ValueError("0078 live database/schema binding changed")
    return result


def config_sha():
    return hashlib.sha256((ROOT / ".env").read_bytes()).hexdigest()


def binding_env(intent_path, identity, intent):
    return {
        "RELEASE_0078_INTENT_PATH": str(intent_path), "RELEASE_0078_INTENT_SHA256": identity["sha256"],
        "RELEASE_0078_RECOVERY_MANIFEST_PATH": str(intent_path.parent / "manifest.json"),
        "RELEASE_0078_RECOVERY_MANIFEST_SHA256": intent["manifest_sha256"],
        "RELEASE_0078_RECOVERY_ORIGIN_HANDOFF_SHA256": intent["origin_handoff_sha256"],
        "RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256": intent["origin_handoff_sha256"],
        "RESTRICTED_RECOVERY_ATTEMPT_MODE": "required",
    }


def prepare(env, *, resume):
    private_directory(RELEASES)
    if not resume:
        guard()
    intent_path_arg = env.get("RELEASE_0078_INTENT_PATH")
    if resume and intent_path_arg:
        intent_path = Path(intent_path_arg)
        if intent_path.parent.parent != RELEASES:
            raise ValueError("0078 intent belongs to a different checkout")
        intent, identity = contract.read_json(intent_path, env.get("RELEASE_0078_INTENT_SHA256", ""))
        if not env.get("RELEASE_0078_INTENT_SHA256"):
            raise ValueError("0078 resume requires the original intent SHA")
        env["EXPECTED_PRODUCTION_DB_IDENTITY_SHA256"] = intent["database_identity_sha256"]
        env["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"] = intent["origin_handoff_path"]
        env["RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"] = intent["origin_handoff_sha256"]
    origin_path = Path(env.get("RELEASE_B_PREFLIGHT_ARTIFACT_PATH", ""))
    origin_sha = env.get("RELEASE_B_PREFLIGHT_ARTIFACT_SHA256", "")
    bindings = {
        "candidate_commit": env["EXPECTED_CANDIDATE_COMMIT"],
        "candidate_image_id": env["EXPECTED_CANDIDATE_IMAGE_ID"],
        "compose_file": env["COMPOSE_FILE"], "artifact_path": str(origin_path),
    }
    if not resume:
        bindings["deployment_lock_token_sha256"] = run(["cat", Path(env.get("DEPLOYMENT_LOCK_DIR", "/tmp/umanews-deployment.lock")) / "token_sha256"], env=env)
    origin = contract.verify_admission(origin_path, origin_sha, bindings)
    if origin.get("handoff_action") not in {"deploy", "manual-release"} or origin.get("release_0078_recovery_binding_mode") != "admission-only":
        raise ValueError("0078 preparation requires its original admission handoff")
    if env.get("EXPECTED_PRODUCTION_DB_IDENTITY_SHA256") != origin["database_identity_sha256"]:
        raise ValueError("0078 admission database differs from release")
    release_dir = RELEASES / origin_sha
    private_directory(release_dir)
    manifest_path = release_dir / "manifest.json"
    intent_path = release_dir / "intent.json"
    expected = {key: origin[key] for key in ("candidate_commit", "candidate_image_id", "database_identity_sha256", "compose_file")}
    expected.update(release_id=origin_sha, origin_handoff_sha256=origin_sha)
    if os.path.lexists(intent_path):
        if not resume:
            raise ValueError("0078 intent exists; use the resume entry")
        intent, identity = contract.read_json(intent_path, env.get("RELEASE_0078_INTENT_SHA256", ""))
        active = os.path.lexists(RELEASES / "active.json")
        intent, manifest = contract.verify_intent(intent_path, identity["sha256"], expected, active_required=active)
        if not active and not os.path.lexists(release_dir / "complete.json"):
            actual = {service: probe(service, env)["running"] for service in contract.SERVICES}
            if actual != intent["restore_services"]:
                raise ValueError("0078 cannot prove preparation stopped before the first service action")
        if intent["config_sha256"] != config_sha():
            raise ValueError("0078 configuration changed since preparation")
    else:
        if os.path.lexists(RELEASES / "active.json"):
            raise ValueError("another 0078 release owns the active pointer")
        if any(os.path.lexists(REPAIR / name) for name in ("restricted-recovery.json", "restricted-recovery.transition.json", "restricted-recovery-control.json")):
            raise ValueError("old recovery marker must be completed by its original control image")
        source_leaf = origin["preflight"]["migration_leaf_set"][0]
        schema_state(env, source_leaf)
        services = {service: probe(service, env) for service in contract.SERVICES}
        if origin["handoff_action"] == "manual-release" and any(services[service]["running"] for service in contract.SERVICES if service != "nginx"):
            raise ValueError("manual 0078 release requires stopped application services")
        restore = {service: values["running"] for service, values in services.items()}
        if os.path.lexists(manifest_path):
            if not resume or not env.get("RELEASE_0078_RECOVERY_MANIFEST_SHA256"):
                raise ValueError("0078 backup proof exists; resume with its original SHA")
            manifest = contract.verify_manifest(manifest_path, env["RELEASE_0078_RECOVERY_MANIFEST_SHA256"], expected)
            if manifest["restore_services"] != restore or manifest["config_sha256"] != config_sha():
                raise ValueError("0078 cannot prove the original preparation boundary")
        else:
            backup_dir = release_dir / "backup"
            private_directory(backup_dir)
            if any(backup_dir.iterdir()):
                raise ValueError("0078 unpublished backup exists; preserve it and reconcile preparation before retry")
            project = env.get("EXPECTED_COMPOSE_PROJECT", "")
            for service in contract.SERVICES:
                cid = services[service]["container"]
                if cid:
                    observed = run(["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}', cid], env=env)
                    if project and project != observed:
                        raise ValueError("0078 Compose project identity mismatch")
                    project = observed
            if not re.fullmatch(r"[a-z0-9_-]+", project):
                raise ValueError("0078 backup requires an exact EXPECTED_COMPOSE_PROJECT")
            output = run([ROOT / "deploy/backup_db.sh"], env={**env, "BACKUP_TARGET": "local", "BACKUP_DIR": str(backup_dir), "EXPECTED_COMPOSE_PROJECT": project})
            paths = [line.removeprefix("Backup created: ") for line in output.splitlines() if line.startswith("Backup created: ")]
            if len(paths) != 1:
                raise ValueError("0078 backup producer did not return one file")
            backup = Path(paths[0]).absolute()
            if backup.parent != backup_dir:
                raise ValueError("0078 backup producer used another release directory")
            _, evidence = contract.file_evidence(backup)
            with backup.open("rb") as stream:
                if env["COMPOSE_FILE"] == "docker-compose.prod.lowcost.yml":
                    toc = run([ROOT / "deploy/docker/compose-wrapper.sh", "-f", env["COMPOSE_FILE"], "--project-name", project, "exec", "-T", "db", "pg_restore", "--list"], env=env, stdin=stream)
                else:
                    toc = run(["docker", "run", "--rm", "-i", "postgres:16", "pg_restore", "--list"], env=env, stdin=stream)
            if not toc:
                raise ValueError("0078 backup TOC is empty")
            if contract.file_evidence(backup)[1] != evidence:
                raise ValueError("0078 backup changed during TOC validation")
            schema_state(env, source_leaf)
            manifest = {
                "schema_version": contract.MANIFEST_SCHEMA, **expected,
                "source_leaf": source_leaf, "target_leaf": contract.TARGET_LEAF,
                "operation": "upgrade" if source_leaf == contract.SOURCE_LEAF else "same-schema",
                "migration_contract_sha256": contract.migration_contract(),
                "backup_path": str(backup), "backup_file": evidence,
                "pg_restore_list_sha256": hashlib.sha256(toc.encode("utf-8")).hexdigest(),
                "pg_restore_list_line_count": len(toc.splitlines()),
                "restore_services": restore, "config_sha256": config_sha(),
                "writer_flags": origin["writer_activity"]["flags"],
                "initial_lock_sha256": origin["deployment_lock_token_sha256"],
            }
            contract.publish_once(manifest_path, manifest)
        manifest_sha = contract.read_json(manifest_path)[1]["sha256"]
        contract.verify_manifest(manifest_path, manifest_sha, expected)
        intent = {
            "schema_version": contract.INTENT_SCHEMA, **expected,
            "manifest_sha256": manifest_sha, "origin_handoff_path": str(origin_path),
            "source_leaf": manifest["source_leaf"],
            **{key: manifest[key] for key in ("restore_services", "config_sha256", "initial_lock_sha256")},
        }
        identity = contract.publish_once(intent_path, intent)
    if not os.path.lexists(release_dir / "complete.json"):
        contract.publish_once(RELEASES / "active.json", {"release_id": origin_sha, "intent_path": str(intent_path), "intent_file": identity})
    env.update(binding_env(intent_path, identity, intent))
    return intent_path, intent


def verify_service_image(service, current, env):
    if service != "nginx" and current["running"]:
        image = run(["docker", "inspect", "--format", "{{.Image}}", current["container"]], env=env)
        if image != env["EXPECTED_CANDIDATE_IMAGE_ID"]:
            raise ValueError(f"0078 running {service} image differs from the original candidate")


def finish(env, intent_path, intent, receipt):
    schema_state(env, contract.TARGET_LEAF)
    restore = intent["restore_services"]
    current_services = {service: probe(service, env) for service in contract.SERVICES}
    for service, current in current_services.items():
        verify_service_image(service, current, env)
    for service in ("web", "worker", "race_sync_v2_worker", "race_live_worker", "beat", "nginx"):
        current = current_services[service]
        if not restore[service]:
            if current["running"]:
                raise ValueError(f"0078 {service} is running outside the original restore intent")
            continue
        if not current["running"]:
            candidate(env)
            compose(["up", "-d", "--no-deps", service], env)
            current = probe(service, env)
            if not current["running"]:
                raise ValueError(f"0078 {service} did not start")
            verify_service_image(service, current, env)
        if service == "web":
            run([ROOT / "deploy/wait_for_compose_service_healthy.sh"], env={**env, "SERVICE_NAME": "web"})
        if service == "nginx" and restore["web"]:
            compose(["exec", "-T", "nginx", "nginx", "-s", "reload"], env)
    actual = {service: probe(service, env)["running"] for service in contract.SERVICES}
    if actual != restore or config_sha() != intent["config_sha256"]:
        raise ValueError("0078 final service/config state differs from original intent")
    complete = {"intent_sha256": env["RELEASE_0078_INTENT_SHA256"], "schema_receipt_path": str(receipt[0]), "schema_receipt_file": receipt[1], "restore_services": restore}
    contract.publish_once(intent_path.parent / "complete.json", complete)
    pointer_path = RELEASES / "active.json"
    if os.path.lexists(pointer_path):
        contract.verify_intent(intent_path, env["RELEASE_0078_INTENT_SHA256"], {})
        _, identity = contract.read_json(pointer_path)
        fd = contract._parent(pointer_path)
        try:
            info = os.stat(pointer_path.name, dir_fd=fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (identity["device"], identity["inode"]):
                raise ValueError("0078 active pointer changed during completion")
            os.unlink(pointer_path.name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
    print("0078 release completed; original service intent restored")


def release(env, *, resume=False):
    run([ROOT / "deploy/deployment_lock.sh", "verify"], env=env)
    reject_legacy_service_intent(env)
    if os.path.lexists(REPAIR / "restricted-recovery-control.json"):
        raise ValueError("old control-image recovery must use its original entry")
    candidate(env)
    intent_path, intent = prepare(env, resume=resume)
    marker_binding = contract.marker_binding({
        **intent, "release_0078_recovery_binding_mode": "bound",
        **{key: env[key.upper()] for key in contract.BINDING_FIELDS},
    })
    live = schema_state(env)
    if live.get("migration_leaf_set") not in ([intent["source_leaf"]], [contract.TARGET_LEAF]):
        raise ValueError("0078 live state differs from prepared source/target")
    markers = [REPAIR / name for name in ("restricted-recovery.json", "restricted-recovery.transition.json") if os.path.lexists(REPAIR / name)]
    if len(markers) > 1:
        raise ValueError("active and transition marker conflict")
    if markers:
        marker, _ = contract.read_json(markers[0])
        unsigned = {key: value for key, value in marker.items() if key != "marker_sha256"}
        if marker.get("schema_version") != contract.MARKER_SCHEMA or contract.digest(unsigned) != marker.get("marker_sha256") or any(marker.get(key) != value for key, value in marker_binding.items()):
            raise ValueError("0078 active DDL marker belongs to another release")
    receipt = contract.completed_marker(REPAIR, marker_binding)
    if receipt is None:
        current = {service: probe(service, env) for service in contract.SERVICES}
        if current["beat"]["running"]:
            compose(["stop", "beat"], env)
        nodes = [current[service]["node"] for service in ("worker", "race_live_worker", "race_sync_v2_worker") if current[service]["running"]]
        if nodes:
            run([ROOT / "deploy/wait_for_celery_drain.sh"], env={**env, "EXPECTED_CELERY_WORKERS": " ".join(nodes)})
        for service in ("worker", "race_live_worker", "race_sync_v2_worker", "web"):
            if probe(service, env)["running"]:
                compose(["stop", service], env)
        if any(probe(service, env)["running"] for service in contract.SERVICES if service != "nginx"):
            raise ValueError("0078 closed state still has application services")
        private_directory(REPAIR / "preflight")
        directory = Path(tempfile.mkdtemp(prefix="closed-0078-", dir=REPAIR / "preflight"))
        closed_path = directory / "preflight.json"
        closed_env = {
            **env, "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(closed_path),
            "RELEASE_B_PREFLIGHT_ACTION": "forward-resume",
            "RELEASE_B_EXPECTED_MIGRATION_LEAF_SET": "",
        }
        run([ROOT / "deploy/run_historical_calendar_release_b_preflight.sh"], env=closed_env)
        closed, _ = contract.read_json(closed_path)
        closed_env["RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"] = closed.get("artifact_sha256", "")
        contract.verify_admission(closed_path, closed_env["RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"], {
            "candidate_commit": env["EXPECTED_CANDIDATE_COMMIT"], "candidate_image_id": env["EXPECTED_CANDIDATE_IMAGE_ID"],
            "database_identity_sha256": env["EXPECTED_PRODUCTION_DB_IDENTITY_SHA256"],
            "release_0078_recovery_binding_mode": "bound", "handoff_action": "forward-resume",
            **{key: env[key.upper()] for key in contract.BINDING_FIELDS},
        })
        run([ROOT / "deploy/run_release_tasks.sh"], env=closed_env)
        receipt = contract.completed_marker(REPAIR, marker_binding)
        if receipt is None:
            raise ValueError("0078 release task did not publish its exact schema completion")
    finish(env, intent_path, intent, receipt)


def main():
    if sys.argv[1:] == ["guard"]:
        guard()
    elif sys.argv[1:] in (["release"], ["resume"]):
        release(dict(os.environ), resume=sys.argv[1] == "resume")
    elif sys.argv[1:] == ["verify"]:
        env = dict(os.environ)
        expected = {key: env[key.upper()] for key in contract.BINDING_FIELDS}
        expected.update(
            candidate_commit=env["EXPECTED_CANDIDATE_COMMIT"],
            candidate_image_id=env["EXPECTED_CANDIDATE_IMAGE_ID"],
            database_identity_sha256=env["EXPECTED_PRODUCTION_DB_IDENTITY_SHA256"],
            compose_file=env["COMPOSE_FILE"], release_0078_recovery_binding_mode="bound",
        )
        artifact = contract.verify_admission(Path(env["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"]), env["RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"], expected)
        contract.verify_intent(Path(artifact["release_0078_intent_path"]), artifact["release_0078_intent_sha256"], {key: artifact[key] for key in ("candidate_commit", "candidate_image_id", "database_identity_sha256", "compose_file")})
    else:
        raise ValueError("usage: release_0078.py guard|release|resume|verify")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError) as exc:
        print(f"0078 release refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
