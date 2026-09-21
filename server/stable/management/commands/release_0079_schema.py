"""0079 只读预检、关闭态凭据和完成收据；迁移仍只有 shell owner。"""

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from stable.services import release_0079_recovery as c
from stable.services.release_0079_schema import schema_state
from stable.services.historical_calendar_release_b_handoff import (
    collect_writer_activity,
)


def bindings():
    values = {
        k: os.environ.get(k.upper(), "")
        for k in (
            "candidate_commit",
            "candidate_image_id",
            "database_identity_sha256",
            "compose_file",
        )
    }
    values["candidate_commit"] = os.environ.get("EXPECTED_CANDIDATE_COMMIT", "")
    values["candidate_image_id"] = os.environ.get("EXPECTED_CANDIDATE_IMAGE_ID", "")
    values["database_identity_sha256"] = os.environ.get(
        "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256", ""
    )
    values["compose_file"] = os.environ.get("COMPOSE_FILE", "")
    if (
        not c.hex_value(values["candidate_commit"], 40)
        or not values["candidate_image_id"].startswith("sha256:")
        or not c.hex_value(values["candidate_image_id"][7:])
    ):
        raise ValueError("0079 candidate binding is invalid")
    version = Path("/app/.umanews-release-commit")
    # 与镜像Dockerfile写入的不可变版本绑定，不信任仅传入的环境值。
    if (
        not version.is_file()
        or version.read_text().strip() != values["candidate_commit"]
    ):
        raise ValueError("0079 container code revision mismatch")
    if values["compose_file"] not in {
        "docker-compose.prod.yml",
        "docker-compose.prod.lowcost.yml",
    }:
        raise ValueError("0079 compose binding invalid")
    return values


def writers():
    value = collect_writer_activity()
    value["flags"] = {
        name: bool(getattr(settings, name, False)) for name in c.WRITER_FLAGS
    }
    value["ok"] = not any(value["counts"].values()) and not any(value["flags"].values())
    if not value["ok"]:
        raise ValueError("0079 writers are not closed")
    return value


def verify_artifact():
    values = bindings()
    path = Path(os.environ["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"])
    artifact = c.verify_admission(
        path,
        os.environ["RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"],
        {
            **values,
            "deployment_lock_token_sha256": os.environ[
                "EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256"
            ],
            "release_0079_recovery_binding_mode": "bound",
        },
    )
    c.recovery_binding(
        preflight=artifact["preflight"],
        candidate_commit=values["candidate_commit"],
        candidate_image_id=values["candidate_image_id"],
        **{
            "manifest_path": artifact["release_0079_recovery_manifest_path"],
            "manifest_sha256": artifact["release_0079_recovery_manifest_sha256"],
            "origin_handoff_sha256": artifact[
                "release_0079_recovery_origin_handoff_sha256"
            ],
            "intent_path": artifact["release_0079_intent_path"],
            "intent_sha256": artifact["release_0079_intent_sha256"],
        },
    )
    live = schema_state()
    if live["database_identity_sha256"] != values["database_identity_sha256"]:
        raise ValueError("0079 live database changed")
    writers()
    _, manifest = c.verify_intent(
        Path(artifact["release_0079_intent_path"]),
        artifact["release_0079_intent_sha256"],
        values,
    )
    return artifact, live, manifest


def marker_path(artifact):
    intent = Path(artifact["release_0079_intent_path"])
    return intent.parent.parent.parent / "restricted-recovery.json"


def exact_marker(artifact):
    path = marker_path(artifact)
    value, identity = c.read_json(path)
    binding = c.marker_binding(artifact)
    unsigned = {k: v for k, v in value.items() if k != "marker_sha256"}
    if (
        value.get("schema_version") != c.MARKER_SCHEMA
        or c.digest(unsigned) != value.get("marker_sha256")
        or any(value.get(k) != v for k, v in binding.items())
    ):
        raise ValueError("0079 active marker differs from this release")
    return path, value, identity


class Command(BaseCommand):
    help = "0079精确schema及发布凭据；不执行DDL或业务数据写入。"

    def add_arguments(self, parser):
        parser.add_argument(
            "action", choices=("check", "handoff", "ensure", "complete")
        )
        parser.add_argument("--expected-leaf", default="")
        parser.add_argument("--expected-marker-device", type=int)
        parser.add_argument("--expected-marker-inode", type=int)

    def handle(self, *args, **options):
        try:
            result = self.perform(
                options["action"],
                expected_identity=(
                    options["expected_marker_device"],
                    options["expected_marker_inode"],
                ),
            )
            if options["expected_leaf"] and result.get("migration_leaf_set") != [
                options["expected_leaf"]
            ]:
                raise ValueError("0079 expected leaf differs")
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

    def perform(self, action, *, expected_identity=(None, None)):
        if action == "check":
            return schema_state()
        if action == "handoff":
            values = bindings()
            live = schema_state()
            activity = writers()
            if (
                values["database_identity_sha256"]
                and values["database_identity_sha256"]
                != live["database_identity_sha256"]
            ):
                raise ValueError("0079 handoff database differs")
            values["database_identity_sha256"] = live["database_identity_sha256"]
            path = Path(os.environ["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"])
            binding = c.recovery_binding(
                preflight=live,
                candidate_commit=values["candidate_commit"],
                candidate_image_id=values["candidate_image_id"],
                manifest_path=os.environ.get("RELEASE_0079_RECOVERY_MANIFEST_PATH", ""),
                manifest_sha256=os.environ.get(
                    "RELEASE_0079_RECOVERY_MANIFEST_SHA256", ""
                ),
                origin_handoff_sha256=os.environ.get(
                    "RELEASE_0079_RECOVERY_ORIGIN_HANDOFF_SHA256", ""
                ),
                intent_path=os.environ.get("RELEASE_0079_INTENT_PATH", ""),
                intent_sha256=os.environ.get("RELEASE_0079_INTENT_SHA256", ""),
            )
            result = dict(
                schema_version=c.HANDOFF_SCHEMA,
                **values,
                **binding,
                target_leaf_set=[c.TARGET_LEAF],
                migration_contract_sha256=c.migration_contract(),
                artifact_path=str(path),
                handoff_action=os.environ["RELEASE_B_PREFLIGHT_ACTION"],
                deployment_lock_token_sha256=os.environ[
                    "EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256"
                ],
                preflight=live,
                writer_activity=activity,
            )
            if not c.hex_value(result["deployment_lock_token_sha256"]) or result[
                "handoff_action"
            ] not in ("deploy", "manual-release", "forward-resume"):
                raise ValueError("0079 handoff action/lock invalid")
            result["artifact_sha256"] = c.digest(result)
            c.publish_once(path, result)
            return result
        artifact, live, manifest = verify_artifact()
        path = marker_path(artifact)
        if action == "ensure":
            if os.path.lexists(path):
                exact_marker(artifact)
            else:
                if (
                    c.completed_marker(path.parent, c.marker_binding(artifact))
                    is not None
                ):
                    raise ValueError(
                        "0079 completion already exists; resume through coordinator"
                    )
                if live["migration_leaf_set"] != [manifest["source_leaf"]]:
                    raise ValueError("0079 missing marker after source leaf changed")
                marker = dict(
                    schema_version=c.MARKER_SCHEMA,
                    **c.marker_binding(artifact),
                    initial_leaf_set=[manifest["source_leaf"]],
                )
                marker["marker_sha256"] = c.digest(marker)
                c.publish_once(path, marker)
            _, marker, identity = exact_marker(artifact)
            if marker.get("initial_leaf_set") != [manifest["source_leaf"]]:
                raise ValueError("0079 marker source differs from original backup")
            return dict(
                ok=True,
                migration_leaf_set=live["migration_leaf_set"],
                marker_device=identity["device"],
                marker_inode=identity["inode"],
            )
        if live["migration_leaf_set"] != [c.TARGET_LEAF]:
            raise ValueError("0079 completion requires exact target schema")
        path, marker, identity = exact_marker(artifact)
        if any(type(value) is not int or value < 0 for value in expected_identity):
            raise ValueError("0079 completion requires ensure marker identity")
        if expected_identity != (identity["device"], identity["inode"]):
            raise ValueError("0079 marker changed since ensure")
        if marker.get("initial_leaf_set") != [manifest["source_leaf"]]:
            raise ValueError("0079 marker source differs from original backup")
        completed = (
            path.parent
            / f"restricted-recovery.completed.{marker['marker_sha256']}.json"
        )
        # 同目录原子rename，避免completed/active两份文件之间的中断窗口。
        fd = c._parent(path)
        try:
            st = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            if (st.st_dev, st.st_ino) != (identity["device"], identity["inode"]):
                raise ValueError("0079 marker changed during completion")
            if os.path.lexists(completed):
                raise ValueError("0079 completion destination already exists")
            os.rename(path.name, completed.name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
        return dict(
            ok=True,
            migration_leaf_set=live["migration_leaf_set"],
            receipt=str(completed),
        )
