from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_inventory import (
    HistoricalPublicationBlockedError,
    InventoryValidationError,
    apply_historical_publication,
    dry_run_historical_publication,
    verify_historical_publication,
)


class Command(BaseCommand):
    help = "按不可变 manifest 批量审计、发布或验证历史赛事"

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=("dry-run", "apply", "verify"))
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-manifest-sha256", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--actor-username")

    def _actor(self, username: str | None):
        if not username:
            raise CommandError("apply 模式必须提供 --actor-username")
        user_model = get_user_model()
        lookup = {user_model.USERNAME_FIELD: username}
        try:
            return user_model._default_manager.get(**lookup)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"执行人不存在：{username}") from exc

    def _write_output(self, output_path: str | Path, result: dict) -> dict[str, object]:
        path = Path(output_path)
        if path.exists():
            raise CommandError(f"输出文件已存在，拒绝覆盖：{path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
        ).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "path": str(path),
            "size": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    def handle(self, *args, **options):
        output = Path(options["output"])
        if output.exists():
            raise CommandError(f"输出文件已存在，拒绝覆盖：{output}")
        try:
            if options["mode"] == "dry-run":
                result = dry_run_historical_publication(
                    manifest_path=options["manifest"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                )
            elif options["mode"] == "verify":
                result = verify_historical_publication(
                    manifest_path=options["manifest"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                )
            else:
                result = apply_historical_publication(
                    manifest_path=options["manifest"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                    actor=self._actor(options["actor_username"]),
                )
        except (OSError, ValueError, InventoryValidationError, HistoricalPublicationBlockedError) as exc:
            raise CommandError(str(exc)) from exc
        identity = self._write_output(output, result)
        self.stdout.write(
            json.dumps(
                {
                    "mode": options["mode"],
                    "manifest_sha256": options["expected_manifest_sha256"],
                    "output": identity,
                    "summary": result.get("summary"),
                    "verifier": {
                        "ok": result.get("verifier", {}).get("ok"),
                        "checked_count": result.get("verifier", {}).get("checked_count"),
                        "error_count": result.get("verifier", {}).get("error_count"),
                    }
                    if "verifier" in result
                    else None,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
