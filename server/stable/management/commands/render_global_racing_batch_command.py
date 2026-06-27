from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.global_racing_plan import GlobalRacingPlanError, build_plan_batch_command, build_plan_batch_commands


class Command(BaseCommand):
    help = "从全球赛马数据库 plan-only JSON 渲染指定批次的精确 dry-run/commit 命令；只读，不发网络请求。"

    def add_arguments(self, parser):
        parser.add_argument("--plan-file", required=True, help="plan-only JSON 文件路径")
        batch_group = parser.add_mutually_exclusive_group(required=True)
        batch_group.add_argument("--batch", type=int, help="要渲染的 batch_index/batch_no")
        batch_group.add_argument("--all-batches", action="store_true", help="渲染 plan 文件中的全部批次")
        parser.add_argument("--limit-horses", type=int, help="追加到渲染命令的 --limit-horses 值")
        parser.add_argument("--output-dir", help="用于生成 suggested_output_path 的地区输出目录；只渲染，不创建目录。")
        parser.add_argument("--commit", action="store_true", help="渲染带 --commit 的命令；默认渲染 dry-run 命令")

    def handle(self, *args, **options):
        plan_path = Path(options["plan_file"])
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read plan file: {exc}") from exc
        if not isinstance(plan, dict):
            raise CommandError("plan file must contain a JSON object")

        try:
            if options["all_batches"]:
                commands = build_plan_batch_commands(
                    plan,
                    limit_horses=options.get("limit_horses"),
                    commit=options["commit"],
                    output_dir=options.get("output_dir"),
                )
                rendered = {
                    "artifact_type": "global_racing_batch_commands",
                    "source": plan.get("source"),
                    "plan_file": str(plan_path),
                    "batch_count": len(commands),
                    "commands": commands,
                }
            else:
                rendered = build_plan_batch_command(
                    plan,
                    batch_number=options["batch"],
                    limit_horses=options.get("limit_horses"),
                    commit=options["commit"],
                    output_dir=options.get("output_dir"),
                )
        except GlobalRacingPlanError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(rendered, ensure_ascii=False, indent=2))
