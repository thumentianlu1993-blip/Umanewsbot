from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.models import HistoricalBatchRun
from stable.services.historical_batch_runner import (
    create_runner_run,
    execute_runner_plan,
    runner_secret_values_from_environment,
    runner_status_payload,
    validate_runner_plan,
)


class Command(BaseCommand):
    help = "按不可变 plan 执行一个独立历史赛事 runner 阶段。"

    def add_arguments(self, parser):
        parser.add_argument("--plan", required=True)
        parser.add_argument("--owner-token-file", required=True)
        parser.add_argument("--lock-file", required=True)
        parser.add_argument("--run-id")

    def handle(self, *args, **options):
        plan_path = Path(options["plan"]).resolve()
        token_path = Path(options["owner_token_file"]).resolve()
        try:
            plan_bytes = plan_path.read_bytes()
            plan = validate_runner_plan(json.loads(plan_bytes))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError(f"runner plan 无效：{exc}") from exc
        try:
            mode = stat.S_IMODE(token_path.stat().st_mode)
            if mode != 0o600:
                raise CommandError("owner token 文件权限必须精确为 0600。")
            owner_token = token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CommandError(f"无法读取 owner token 文件：{exc}") from exc
        artifact_root = Path(plan["artifact_root"]).resolve()
        try:
            token_path.relative_to(artifact_root)
        except ValueError:
            pass
        else:
            raise CommandError("owner token 文件不能位于 artifact 目录内。")
        if not owner_token:
            raise CommandError("owner token 文件为空。")
        plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
        run_id = options.get("run_id")
        run = HistoricalBatchRun.objects.filter(run_id=run_id).first() if run_id else None
        if run is None:
            run = create_runner_run(
                run_id=run_id,
                batch_id=plan["batch_id"],
                phase=plan["phase"],
                artifact_root=plan["artifact_root"],
                plan_sha256=plan_sha256,
                image_id=plan["image_id"],
                image_revision=plan["image_revision"],
            )
        try:
            run = execute_runner_plan(
                run=run,
                plan_path=plan_path,
                owner_token=owner_token,
                lock_path=options["lock_file"],
                secret_values=runner_secret_values_from_environment([owner_token]),
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(runner_status_payload(run), ensure_ascii=False, sort_keys=True))
