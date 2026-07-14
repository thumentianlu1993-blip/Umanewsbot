from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.models import MultiregionAttributionRun, MultiregionAttributionRunStatus
from stable.services.attribution_runs import (
    build_attribution_review_report,
    verify_attribution_run_manifest,
)


class Command(BaseCommand):
    help = "从已持久化的多地区归属 dry-run 导出审核报告，不重复执行归属推断。"

    def add_arguments(self, parser):
        parser.add_argument("--run-id", type=int, required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--review-sample-per-region", type=int)
        parser.add_argument(
            "--include-gate-validation",
            action="store_true",
            help="额外逐篇执行发布门禁；全量归属审核通常不需要，且可能耗时较长。",
        )
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--output",
            help="将完整 JSON 原子写入新文件；文件已存在时拒绝覆盖。",
        )

    def handle(self, *args, **options):
        try:
            run = MultiregionAttributionRun.objects.get(pk=options["run_id"])
        except MultiregionAttributionRun.DoesNotExist as exc:
            raise CommandError("归属 run 不存在") from exc
        if run.mode != "dry_run" or run.status not in {
            MultiregionAttributionRunStatus.COMPLETED,
            MultiregionAttributionRunStatus.PARTIAL,
        }:
            raise CommandError("只有成功或可续跑的 dry-run 可以导出")
        if run.manifest_sha256 != options["manifest_sha256"]:
            raise CommandError("run 与 manifest SHA-256 不匹配")
        if not verify_attribution_run_manifest(run):
            raise CommandError("run 内容已偏离原审核 manifest")

        report = build_attribution_review_report(
            run,
            include_gate_validation=options.get("include_gate_validation", False),
            review_sample_per_region=options.get("review_sample_per_region"),
        )
        report["exported_from_existing_run"] = True
        serialized = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if options.get("output"):
            output_path = Path(options["output"])
            if output_path.exists():
                raise CommandError("输出文件已存在，拒绝覆盖既有审核证据")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(serialized)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, output_path)
            except Exception:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
            self.stdout.write(
                f"run={run.id} candidates={report['candidate_count']} output={output_path}"
            )
            return
        if options["json"]:
            self.stdout.write(serialized)
            return
        self.stdout.write(
            f"run={run.id} candidates={report['candidate_count']} "
            f"review={len(report['review_checklist_ids'])} drifted={len(report['drifted_article_ids'])}"
        )
