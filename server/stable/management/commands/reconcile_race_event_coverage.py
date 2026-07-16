from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_event_reconciliation import (
    RaceEventReconciliationError,
    apply_race_event_coverage_reconciliation,
    export_race_event_coverage_reconciliation,
    rollback_race_event_coverage_reconciliation,
    verify_race_event_coverage_reconciliation,
)


class Command(BaseCommand):
    help = "生成、验证、应用或回滚赛事正式总账与既有 RaceEvent 的关联产物"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", help="dry-run 新产物目录；目录必须不存在")
        parser.add_argument("--artifact-dir", help="已有 reconciliation artifact 目录")
        parser.add_argument("--as-of", help="报告时点，ISO-8601；默认当前 UTC 时间")
        parser.add_argument("--result-grace-hours", type=float, default=2.0, help="赛果宽限小时数")
        parser.add_argument("--commit", action="store_true", help="显式执行已批准关联写入")
        parser.add_argument("--verify", action="store_true", help="只读验证产物和数据库守恒")
        parser.add_argument("--rollback", action="store_true", help="显式按 rollback ledger 解除本次关联")
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--approval", help="独立 approval.json 路径")
        parser.add_argument("--expected-approval-sha256")
        parser.add_argument("--rollback-ledger", help="rollback.jsonl 路径；apply 默认写入 artifact 目录")
        parser.add_argument("--expected-rollback-sha256")

    def _required(self, options, *names: str) -> None:
        missing = [f"--{name.replace('_', '-')}" for name in names if not options.get(name)]
        if missing:
            raise CommandError("缺少必要参数：" + ", ".join(missing))

    def handle(self, *args, **options):
        write_modes = int(options["commit"]) + int(options["rollback"])
        if write_modes > 1 or (options["verify"] and write_modes):
            raise CommandError("--commit、--rollback、--verify 不能组合使用")
        try:
            if options["commit"]:
                self._required(
                    options,
                    "artifact_dir",
                    "expected_manifest_sha256",
                    "approval",
                    "expected_approval_sha256",
                )
                result = apply_race_event_coverage_reconciliation(
                    artifact_dir=options["artifact_dir"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                    approval_path=options["approval"],
                    expected_approval_sha256=options["expected_approval_sha256"],
                    rollback_path=options["rollback_ledger"],
                )
            elif options["rollback"]:
                self._required(
                    options,
                    "artifact_dir",
                    "expected_manifest_sha256",
                    "approval",
                    "expected_approval_sha256",
                    "rollback_ledger",
                    "expected_rollback_sha256",
                )
                result = rollback_race_event_coverage_reconciliation(
                    artifact_dir=options["artifact_dir"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                    approval_path=options["approval"],
                    expected_approval_sha256=options["expected_approval_sha256"],
                    rollback_path=options["rollback_ledger"],
                    expected_rollback_sha256=options["expected_rollback_sha256"],
                )
            elif options["verify"]:
                self._required(options, "artifact_dir", "expected_manifest_sha256")
                result = verify_race_event_coverage_reconciliation(
                    artifact_dir=options["artifact_dir"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                )
                if not result["ok"]:
                    raise CommandError("verifier 失败：" + "; ".join(result["errors"]))
            else:
                self._required(options, "output_dir")
                as_of = timezone.now()
                if options["as_of"]:
                    as_of = datetime.fromisoformat(options["as_of"].replace("Z", "+00:00"))
                    if timezone.is_naive(as_of):
                        raise CommandError("--as-of 必须包含时区")
                if options["result_grace_hours"] < 0:
                    raise CommandError("--result-grace-hours 不能为负数")
                result = export_race_event_coverage_reconciliation(
                    output_dir=Path(options["output_dir"]),
                    as_of=as_of,
                    result_grace=timedelta(hours=options["result_grace_hours"]),
                )
        except (OSError, ValueError, RaceEventReconciliationError) as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
