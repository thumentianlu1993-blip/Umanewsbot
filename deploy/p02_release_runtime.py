"""当前lowcost生产拓扑的P02物理操作；只由受锁协调器调用。"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlsplit

from stable.services import release_p02_recovery as c
from p02_release_assets import backup as archive_directories, config_inventory, materialize_config

APPS = ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker")
SERVICES = (*APPS, "nginx")
# 与镜像内同一列表，宿主不导入Django设置。
from stable.services.release_0079_recovery import WRITER_FLAGS as OLD_FLAGS
FLAGS = (*OLD_FLAGS, "RACE_LIFECYCLE_V2_WRITE_ENABLED", "RACE_LIFECYCLE_DELIVERY_ENABLED")


class DockerRuntime:
    def __init__(self, root, directory, plan, lock):
        self.root, self.directory, self.plan, self.lock = Path(root), Path(directory), plan, lock
        if plan.get("compose_file") != "docker-compose.prod.lowcost.yml":
            raise ValueError("P02 v1 executor supports the reviewed lowcost topology only")
        if not re.fullmatch(r"[a-z0-9_-]+", plan.get("compose_project", "")):
            raise ValueError("P02 explicit Compose project is required")
        self.env = {**os.environ, "COMPOSE_FILE": plan["compose_file"], "EXPECTED_COMPOSE_PROJECT": plan["compose_project"],
                    "COMPOSE_PROJECT_NAME": plan["compose_project"], "SERVICE_NAME": "web",
                    "SERVICE_HEALTH_TIMEOUT_SECONDS": "150",
                    "DEPLOYMENT_LOCK_DIR": str(lock.directory), "DEPLOYMENT_LOCK_TOKEN": lock.token,
                    "UMANEWS_RELEASE_COMMIT": plan["candidate_commit"], "UMANEWS_ROOT_DIR": str(self.root)}
        self.marker = self.root / "runtime/migration_history_repair/restricted-recovery.json"
        self.config = self.current_config()
        self.db_env = self.config["services"]["db"]["environment"]
        self.image_override = self.directory / "candidate-compose.json"
        self.readonly_override = self.directory / "readonly-compose.json"
        self._private_json(self.image_override, {"services": {s: {"image": plan["candidate_image_id"]} for s in APPS}})
        readonly_env = {key: "false" for key in FLAGS}
        readonly_env.update(RACE_LIFECYCLE_V2_EVENT_IDS="", PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=120000",
                            DJANGO_SETTINGS_MODULE="app.p02_readonly_settings",
                            CELERY_BROKER_URL="memory://", DJANGO_SUPERUSER_USERNAME="", DJANGO_SUPERUSER_PASSWORD="")
        self._private_json(self.readonly_override, {"services": {"web": {
            "image": plan["candidate_image_id"], "environment": readonly_env,
            "command": ["gunicorn", "app.p02_readonly_wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "1"],
        }}})

    def run(self, argv, *, stdin=None, stdout=None, timeout=180):
        self.lock.verify()
        try:
            result = subprocess.run([str(x) for x in argv], cwd=self.root, env=self.env,
                stdin=stdin, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, check=True, pass_fds=self.lock.pass_fds)
        except (subprocess.SubprocessError, OSError) as exc:
            # 原始stderr可能包含Compose环境、数据库密码或HTTP内容，不能输出。
            raise ValueError(f"P02 bounded command failed: {Path(str(argv[0])).name}") from exc
        return result.stdout.decode().strip() if stdout is None else ""

    def compose_argv(self, *, overlay=None):
        argv = [self.root / "deploy/docker/compose-wrapper.sh", "--project-directory", self.root,
                "--project-name", self.plan["compose_project"], "-f", self.plan["compose_file"]]
        if overlay:
            argv.extend(["-f", overlay])
        return argv

    def current_config(self):
        return json.loads(self.run([*self.compose_argv(), "config", "--format", "json"]))

    def configuration_digest(self):
        return c.digest({"compose": self.current_config(),
            "env_sha256": hashlib.sha256((self.root / ".env").read_bytes()).hexdigest()})

    def compose(self, args, *, overlay=None, timeout=180, stdin=None, stdout=None):
        if self.configuration_digest() != self.plan["config_sha256"]:
            raise ValueError("P02 effective configuration changed")
        return self.run([*self.compose_argv(overlay=overlay), *args], timeout=timeout, stdin=stdin, stdout=stdout)

    def _private_json(self, path, value):
        c.publish_once(path, value)

    def verify(self):
        self.lock.verify()
        if self.run(["git", "rev-parse", "HEAD"]) != self.plan["candidate_commit"]:
            raise ValueError("P02 checkout commit changed")
        status = self.run(["git", "status", "--porcelain", "--untracked-files=all"])
        own = "?? runtime/migration_history_repair/restricted-recovery.json"
        for line in status.splitlines():
            if line != own:
                raise ValueError("P02 candidate worktree must be clean")
            intent, identity = c.read_artifact(self.directory / "intent.json", kind="intent")
            c.validate_bindings(self.plan, intent)
            marker, _ = c.read_artifact(self.marker, kind="active", intent_sha=identity["sha256"])
            if marker.get("directory") != str(self.directory) or marker.get("candidate_commit") != self.plan["candidate_commit"]:
                raise ValueError("P02 foreign recovery marker")
        if self.configuration_digest() != self.plan["config_sha256"]:
            raise ValueError("P02 configuration binding changed")
        image = json.loads(self.run(["docker", "image", "inspect", self.plan["candidate_image_id"]]))[0]
        if (image["Id"] != self.plan["candidate_image_id"]
                or image["Config"].get("Labels", {}).get("org.opencontainers.image.revision") != self.plan["candidate_commit"]):
            raise ValueError("P02 exact image/revision changed")
        if self.run(["docker", "info", "--format", "{{.ID}}"]) != self.plan.get("docker_engine_id"):
            raise ValueError("P02 Docker engine identity changed")
        for service in APPS:
            env = self.config["services"][service].get("environment") or {}
            for flag in ("RACE_LIFECYCLE_V2_WRITE_ENABLED", "RACE_LIFECYCLE_DELIVERY_ENABLED"):
                if str(env.get(flag, "false")).lower() not in {"", "0", "false", "no", "off"}:
                    raise ValueError("P02 production lifecycle flag must remain false")
            if env.get("RACE_LIFECYCLE_V2_EVENT_IDS"):
                raise ValueError("P02 cohort must remain empty")

    def verify_rehearsal(self):
        # 在任何停服副作用前确认挂载能完整备份。
        self.configuration_inventory()
        proof, _ = c.read_artifact(Path(self.plan["rehearsal_path"]), kind="rehearsal", sha=self.plan["rehearsal_sha256"])
        if (proof.get("status") != "verified" or proof.get("production_shape") is not True
                or proof.get("candidate_commit") != self.plan["candidate_commit"]
                or proof.get("candidate_image_id") != self.plan["candidate_image_id"]
                or proof.get("source_database_identity_sha256") != self.plan["database_identity_sha256"]
                or proof.get("migration_contract_sha256") != c.migration_contract()
                or proof.get("budgets") != {"lock_timeout_ms": 5000, "statement_timeout_ms": 120000}
                or proof.get("recovery_surface") != ["database", "roles", "config", "assets", "images"]):
            raise ValueError("P02 exact production-shape rehearsal proof is incomplete")

    def guard_legacy(self):
        self.run(["python3", self.root / "deploy/release_0079.py", "guard"])
        if self.marker.exists():
            raise ValueError("P02 old recovery marker must be handled by its original generation")

    def ensure_marker(self, intent_sha):
        c.private_directory(self.marker.parent)
        c.write_artifact(self.marker, kind="active", intent_sha=intent_sha,
            directory=str(self.directory), candidate_commit=self.plan["candidate_commit"])

    def clear_marker(self, intent_sha):
        if not self.marker.exists():
            return
        _, identity = c.read_artifact(self.marker, kind="active", intent_sha=intent_sha)
        from stable.services.release_0078_recovery import _parent
        fd = _parent(self.marker)
        try:
            current = os.stat(self.marker.name, dir_fd=fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (identity["device"], identity["inode"]):
                raise ValueError("P02 marker changed before completion")
            os.unlink(self.marker.name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)

    def probe_service(self, service):
        ids = self.compose(["ps", "--all", "-q", service]).split()
        if not ids:
            return {"running": False, "id": "", "node": "", "image": ""}
        if len(ids) != 1:
            raise ValueError("P02 exactly one container per service is required")
        data = json.loads(self.run(["docker", "inspect", ids[0]]))[0]
        if data["State"]["Status"] not in {"running", "exited", "created"}:
            raise ValueError("P02 ambiguous container state")
        if data["Config"].get("Labels", {}).get("com.docker.compose.project") != self.plan["compose_project"]:
            raise ValueError("P02 foreign Compose container")
        return {"running": data["State"]["Running"], "id": ids[0], "node": data["Config"]["Hostname"], "image": data["Image"]}

    def control(self, action, *args):
        command = ["run", "--rm", "--no-deps", "--user", f"{os.getuid()}:{os.getgid()}",
                   "--entrypoint", "python", "-v", f"{self.directory}:{self.directory}:rw"]
        values = {key: "false" for key in FLAGS}
        values.update(P02_RELEASE_BINDINGS=c.encoded({key: self.plan[key] for key in c.BINDINGS}).decode(),
                      RACE_LIFECYCLE_V2_EVENT_IDS="", LOG_DIR="/tmp/p02-logs",
                      CELERY_BROKER_URL="memory://",
                      PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=120000")
        for key, value in values.items():
            command.extend(["-e", f"{key}={value}"])
        command.extend(["web", "manage.py", "release_p02", action, *args])
        return json.loads(self.compose(command, overlay=self.image_override, timeout=1800))

    def snapshot(self):
        state = self.control("state")
        services = {s: self.probe_service(s) for s in SERVICES}
        all_images = {v["image"] for v in services.values() if v["image"]}
        for service in ("db", "redis"):
            image = self.probe_service(service)["image"]
            if image:
                all_images.add(image)
        if not all_images:
            raise ValueError("P02 old image inventory is empty")
        return {**self.plan, **state, "services": {s: v["running"] for s, v in services.items()}, "old_image_ids": sorted(all_images)}

    def close(self, intent):
        try:
            self._graceful_close(intent)
        except BaseException:
            self.emergency_close(intent)
            raise

    def _graceful_close(self, intent):
        if self.probe_service("beat")["running"]:
            self.compose(["stop", "--timeout", "120", "beat"])
        workers = [self.probe_service(s) for s in ("worker", "race_live_worker", "race_sync_v2_worker")]
        nodes = [row["node"] for row in workers if row["running"]]
        if nodes:
            if not self.probe_service("web")["running"]:
                raise ValueError("P02 cannot verify drain without the original web control")
            self.env["EXPECTED_CELERY_WORKERS"] = " ".join(nodes)
            self.run([self.root / "deploy/wait_for_celery_drain.sh"], timeout=930)
        for service in ("worker", "race_live_worker", "race_sync_v2_worker", "web"):
            if self.probe_service(service)["running"]:
                self.compose(["stop", "--timeout", "120", service], timeout=150)
        if any(self.probe_service(s)["running"] for s in APPS):
            raise ValueError("P02 application writers remain running")

    def closed_snapshot(self):
        if any(self.probe_service(s)["running"] for s in APPS):
            raise ValueError("P02 closed service snapshot rejected")
        return self.control("closed")

    def _produce(self, path, argv, *, timeout=1800):
        if path.exists():
            c.file_evidence(path)
            return
        partial = path.with_name(path.name + ".partial")
        fd = os.open(partial, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            self.run(argv, stdout=stream, timeout=timeout)
            stream.flush()
            os.fsync(stream.fileno())
        if not partial.stat().st_size:
            raise ValueError("P02 backup producer returned an empty file")
        os.link(partial, path, follow_symlinks=False)
        partial.unlink()

    def configuration_paths(self):
        paths = {str(self.root / ".env"), str(self.root / self.plan["compose_file"])}
        for service in self.config["services"].values():
            for mount in service.get("volumes", []):
                if mount.get("type") == "bind":
                    paths.add(mount["source"])
        return sorted(paths)

    def configuration_inventory(self):
        result = {}
        for raw in self.configuration_paths():
            source = Path(raw)
            if self.directory == source or self.directory.is_relative_to(source):
                raise ValueError("P02 backup cannot include its own artifacts")
            result[raw] = config_inventory(source)
        return result

    def emergency_close(self, intent):
        failures = []
        # 不依赖web存活、排空成功或配置摘要仍然匹配；始终固定原Compose资源域。
        for service in ("beat", "worker", "race_live_worker", "race_sync_v2_worker", "web"):
            try:
                self.emergency_stop(service)
            except Exception:
                failures.append(service)
        if failures:
            raise ValueError("P02 emergency stop failed for: " + ",".join(failures))

    def emergency_stop(self, service):
        self.run([*self.compose_argv(), "stop", "--timeout", "120", service], timeout=150)
        ids = self.run([*self.compose_argv(), "ps", "--all", "-q", service]).split()
        for container in ids:
            data = json.loads(self.run(["docker", "inspect", container]))[0]
            if data["State"]["Running"]:
                raise ValueError("P02 writer remains running")

    def backup_and_restore(self, intent, closed):
        directory = c.private_directory(self.directory / "backup")
        db_user = self.db_env["POSTGRES_USER"]
        db_name = self.db_env["POSTGRES_DB"]
        prefix = [*self.compose_argv(), "exec", "-T", "db"]
        self._produce(directory / "database.dump", [*prefix, "pg_dump", "-U", db_user, "-d", db_name, "--format=custom", "--create"])
        self._produce(directory / "roles.sql", [*prefix, "pg_dumpall", "-U", db_user, "--roles-only"])
        staging = Path(tempfile.mkdtemp(prefix="config-copy-", dir=self.directory))
        try:
            before = self.configuration_inventory()
            self._private_json(staging / "compose-effective.json", self.config)
            paths = self.configuration_paths()
            for index, source in enumerate(paths):
                materialize_config(Path(source), staging / f"mount-{index}")
            self._private_json(staging / "paths.json", {"paths": paths})
            if before != self.configuration_inventory():
                raise ValueError("P02 configuration changed during backup")
            archive_directories({"config": staging}, directory / "config.tar")
        finally:
            shutil.rmtree(staging)
        asset_command = ["run", "--rm", "--no-deps", "--entrypoint", "python", "-v", f"{directory}:{directory}:rw",
                         "web", "/app/deploy/p02_release_assets.py", "backup", "--output", str(directory / "assets.tar"),
                         "--static", "/app/server/staticfiles", "--media", "/app/server/media"]
        self.compose(asset_command, overlay=self.image_override, timeout=1800)
        self._produce(directory / "images.tar", ["docker", "image", "save", *intent["old_image_ids"]])
        with (directory / "images.tar").open("rb") as stream:
            self.run(["docker", "image", "load"], stdin=stream, timeout=1800)
        for image in intent["old_image_ids"]:
            if self.run(["docker", "image", "inspect", "--format", "{{.Id}}", image]) != image:
                raise ValueError("P02 old image restore failed")
        restored = self.restore_database(directory)
        if restored["counts_sha256"] != closed["source_counts_sha256"] or restored["security_sha256"] != closed["source_security_sha256"]:
            raise ValueError("P02 database restore data or permissions differ")
        current = self.closed_snapshot()
        if any(current[key] != closed["source_" + key] for key in ("counts_sha256", "catalog_sha256", "security_sha256")):
            raise ValueError("P02 source changed while producing backup")
        files = {name: c.file_evidence(directory / name)[1] for name in
                 ("database.dump", "roles.sql", "config.tar", "assets.tar", "images.tar")}
        return {"files": files, "restore": {"status": "verified", **restored}}

    def restore_database(self, directory):
        name = "p02-restore-" + uuid.uuid4().hex
        admin = self.control("state")["bootstrap_role"]
        source_name = self.db_env["POSTGRES_DB"]
        if source_name in {"postgres", "template0", "template1", "p02_restore"}:
            raise ValueError("P02 source database name conflicts with isolated restore control")
        image = self.probe_service("db")["image"]
        if not image:
            raise ValueError("P02 database image missing")
        self.run(["docker", "run", "-d", "--network", "none", "--name", name,
                  "-e", f"POSTGRES_USER={admin}", "-e", "POSTGRES_DB=p02_restore",
                  "-e", "POSTGRES_HOST_AUTH_METHOD=trust", image])
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    self.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", admin, "-d", "p02_restore"], timeout=5)
                    break
                except ValueError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.5)
            with tempfile.TemporaryFile(mode="w+b") as stream:
                stream.write(c.restore_roles_sql((directory / "roles.sql").read_bytes(), admin))
                stream.seek(0)
                self.run(["docker", "exec", "-i", name, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", admin, "-d", "p02_restore"], stdin=stream, timeout=180)
            with (directory / "database.dump").open("rb") as stream:
                self.run(["docker", "exec", "-i", name, "pg_restore", "--exit-on-error", "--create", "--role", self.db_env["POSTGRES_USER"], "-U", admin, "-d", "p02_restore"], stdin=stream, timeout=1800)
            args = ["docker", "run", "--rm", "--network", f"container:{name}", "--entrypoint", "python"]
            env = {"DB_ENGINE": "postgres", "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432",
                   "POSTGRES_USER": admin, "POSTGRES_DB": source_name, "POSTGRES_PASSWORD": "",
                   "P02_RELEASE_BINDINGS": c.encoded({key: self.plan[key] for key in c.BINDINGS}).decode(),
                   "RACE_LIFECYCLE_V2_EVENT_IDS": "", "LOG_DIR": "/tmp/p02-logs", **{key: "false" for key in FLAGS}}
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])
            args.extend([self.plan["candidate_image_id"], "manage.py", "release_p02", "restore-proof"])
            return json.loads(self.run(args, timeout=180))
        finally:
            self.run(["docker", "rm", "-f", "-v", name])

    def apply_schema(self, intent_sha):
        return self.control("apply", "--directory", str(self.directory), "--intent-sha256", intent_sha)

    def static_inventory(self):
        output = self.compose(["run", "--rm", "--no-deps", "--entrypoint", "python", "web",
            "/app/deploy/p02_release_assets.py", "static", "--static", "/app/server/staticfiles"], overlay=self.image_override)
        return json.loads(output)

    def collect_static(self):
        args = ["run", "--rm", "--no-deps", "--entrypoint", "python"]
        for key, value in {**dict.fromkeys(FLAGS, "false"), "RACE_LIFECYCLE_V2_EVENT_IDS": "",
                           "CELERY_BROKER_URL": "memory://", "PGOPTIONS": "-c default_transaction_read_only=on"}.items():
            args.extend(["-e", f"{key}={value}"])
        self.compose([*args, "web", "manage.py", "collectstatic", "--noinput"], overlay=self.image_override)
        value = self.static_inventory()
        if value["file_count"] <= 0:
            raise ValueError("P02 static output is empty")
        return value

    def verify_static(self, evidence):
        actual = self.static_inventory()
        if any(evidence.get(key) != value for key, value in actual.items()):
            raise ValueError("P02 static/media inventory changed")

    def verify_schema_complete(self, evidence):
        actual = self.control("state")
        if actual["prefix"] != 6 or any(actual[key] != evidence.get(key) for key in ("catalog_sha256", "recorder_sha256")):
            raise ValueError("P02 target schema changed before service restart")

    def public_probe(self, *, readonly=False):
        origin = self.plan.get("public_origin", "")
        parts = urlsplit(origin)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("P02 exact HTTPS public origin is required")
        for path in ("/healthz/", "/races/"):
            output = self.run(["curl", "--silent", "--show-error", "--max-time", "20", "--dump-header", "-", "--output", "/dev/null", "--write-out", "%{http_code}", origin.rstrip("/") + path], timeout=25)
            if output.splitlines()[-1] != "200":
                raise ValueError("P02 public HTTPS probe failed")
            if readonly:
                markers = [line.split(":", 1)[1].strip() for line in output.splitlines()
                           if line.lower().startswith("x-umanews-p02-readonly:")]
                if markers != [self.plan["candidate_commit"]]:
                    raise ValueError("P02 public origin does not prove this readonly candidate")

    def readonly_probe(self, intent):
        try:
            self.compose(["up", "-d", "--no-deps", "--no-build", "web"], overlay=self.readonly_override)
            self.run([self.root / "deploy/wait_for_compose_service_healthy.sh"], timeout=180)
            args = ["exec", "-T", "-e", "P02_RELEASE_BINDINGS=" + c.encoded({key: self.plan[key] for key in c.BINDINGS}).decode(),
                    "web", "python", "manage.py", "release_p02", "readonly"]
            if json.loads(self.compose(args, overlay=self.readonly_override)).get("readonly") is not True:
                raise ValueError("P02 readonly connection proof missing")
            self.compose(["exec", "-T", "nginx", "nginx", "-s", "reload"])
            self.public_probe(readonly=True)
            return {"ok": True, "paths": ["/healthz/", "/races/"]}
        finally:
            self.compose(["stop", "--timeout", "120", "web"], overlay=self.readonly_override)

    def restore_services(self, intent):
        # 强制按正常配置重建web，不能把只读探针容器当正常web。
        for service in ("web", "worker", "race_sync_v2_worker", "race_live_worker", "beat", "nginx"):
            if intent["restore_services"][service]:
                self.compose(["up", "-d", "--no-deps", "--no-build", service], overlay=self.image_override)
                if service == "web":
                    self.run([self.root / "deploy/wait_for_compose_service_healthy.sh"], timeout=180)
        self.compose(["exec", "-T", "nginx", "nginx", "-s", "reload"])

    def verify_restored(self, intent):
        for service in SERVICES:
            actual = self.probe_service(service)
            if actual["running"] != intent["restore_services"][service]:
                raise ValueError("P02 restored service inventory differs")
            if actual["running"] and service in APPS:
                if actual["image"] != self.plan["candidate_image_id"]:
                    raise ValueError("P02 restored image differs")
                container = json.loads(self.run(["docker", "inspect", actual["id"]]))[0]["Config"]
                expected = self.config["services"][service]
                env = dict(item.split("=", 1) for item in container.get("Env", []) if "=" in item)
                if any(env.get(key) != str(value) for key, value in (expected.get("environment") or {}).items()):
                    raise ValueError("P02 restored effective environment differs")
                if container.get("Cmd") != expected.get("command"):
                    raise ValueError("P02 restored command differs")
                if env.get("DJANGO_SETTINGS_MODULE") == "app.p02_readonly_settings":
                    raise ValueError("P02 readonly container cannot count as restored")
        if self.control("state")["prefix"] != 6:
            raise ValueError("P02 restored schema differs")
        self.public_probe()
