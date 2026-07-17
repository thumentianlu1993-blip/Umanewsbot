from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from stable.services.race_series_identity_review import (
    RaceSeriesIdentityReviewError,
    apply_race_series_identity_review,
    prepare_race_series_identity_review,
    rollback_race_series_identity_review,
    verify_race_series_identity_review,
)


class Command(BaseCommand):
    help = "准备、验证、应用或回滚赛事系列身份审核产物"

    def add_arguments(self, parser):
        parser.add_argument("--decisions", help="正式 identity decision JSON")
        parser.add_argument("--field-repairs", help="显式字段修复 JSON")
        parser.add_argument("--output-dir", help="prepare 新产物目录；必须不存在")
        parser.add_argument("--artifact-dir", help="已有 identity review artifact 目录")
        parser.add_argument("--commit", action="store_true", help="应用已批准审核")
        parser.add_argument("--verify", action="store_true", help="只读验证审核状态")
        parser.add_argument("--rollback", action="store_true", help="回滚本批审核")
        parser.add_argument(
            "--expected-state",
            choices=("prepared", "applied", "rolled_back"),
            default="applied",
            help="verifier 预期状态",
        )
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--approval", help="独立 approval.json 路径")
        parser.add_argument("--expected-approval-sha256")
        parser.add_argument("--rollback-ledger", help="rollback.jsonl 路径")
        parser.add_argument("--expected-rollback-sha256")
        parser.add_argument(
            "--actor-username",
            help="执行人用户名；必须与 approval.approved_by 精确一致",
        )

    def _required(self, options, *names: str) -> None:
        missing = [
            f"--{name.replace('_', '-')}" for name in names if not options.get(name)
        ]
        if missing:
            raise CommandError("缺少必要参数：" + ", ".join(missing))

    def _actor(self, username: str):
        user_model = get_user_model()
        lookup = {user_model.USERNAME_FIELD: username}
        try:
            return user_model._default_manager.get(**lookup)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"执行人不存在：{username}") from exc

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
                    "actor_username",
                )
                result = apply_race_series_identity_review(
                    artifact_dir=options["artifact_dir"],
                    expected_manifest_sha256=options[
                        "expected_manifest_sha256"
                    ],
                    approval_path=options["approval"],
                    expected_approval_sha256=options[
                        "expected_approval_sha256"
                    ],
                    actor=self._actor(options["actor_username"]),
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
                    "actor_username",
                )
                result = rollback_race_series_identity_review(
                    artifact_dir=options["artifact_dir"],
                    expected_manifest_sha256=options[
                        "expected_manifest_sha256"
                    ],
                    approval_path=options["approval"],
                    expected_approval_sha256=options[
                        "expected_approval_sha256"
                    ],
                    rollback_path=options["rollback_ledger"],
                    expected_rollback_sha256=options[
                        "expected_rollback_sha256"
                    ],
                    actor=self._actor(options["actor_username"]),
                )
            elif options["verify"]:
                self._required(
                    options, "artifact_dir", "expected_manifest_sha256"
                )
                result = verify_race_series_identity_review(
                    artifact_dir=options["artifact_dir"],
                    expected_manifest_sha256=options[
                        "expected_manifest_sha256"
                    ],
                    expected_state=options["expected_state"],
                )
                if not result["ok"]:
                    raise CommandError(
                        "verifier 失败：" + "; ".join(result["errors"])
                    )
            else:
                self._required(
                    options,
                    "decisions",
                    "field_repairs",
                    "output_dir",
                )
                result = prepare_race_series_identity_review(
                    decisions_path=Path(options["decisions"]),
                    field_repairs_path=Path(options["field_repairs"]),
                    output_dir=Path(options["output_dir"]),
                )
        except (OSError, ValueError, RaceSeriesIdentityReviewError) as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        )
