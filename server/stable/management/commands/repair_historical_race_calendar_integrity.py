from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_calendar_integrity import (
    HistoricalRaceCalendarIntegrityError,
    apply_historical_race_calendar_integrity,
    default_artifact_root,
    prepare_historical_race_calendar_integrity,
    rollback_historical_race_calendar_integrity,
    verify_historical_race_calendar_integrity,
)
from stable.services.historical_race_calendar_admission import (
    HistoricalCalendarWriteBlocked,
    enter_historical_calendar_maintenance,
    exit_historical_calendar_maintenance,
)
from stable.models import HistoricalRaceCalendarMaintenanceGate


class Command(BaseCommand):
    help = "只读准备、受审批应用、验证或精确回滚历史赛事年份完整性修复"

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group(required=True)
        modes.add_argument("--prepare", action="store_true")
        modes.add_argument("--apply", action="store_true")
        modes.add_argument("--verify", action="store_true")
        modes.add_argument("--rollback", action="store_true")
        modes.add_argument("--enter-maintenance", action="store_true")
        modes.add_argument("--exit-maintenance", action="store_true")
        parser.add_argument("--all-regions", action="store_true")
        parser.add_argument("--output", help="prepare 新输出目录，必须是受控根的直接子目录")
        parser.add_argument("--artifact", help="prepare 生成的 manifest.json")
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--approval", help="独立 reviewer 的 approval.json")
        parser.add_argument("--expected-approval-sha256")
        parser.add_argument("--maintenance-evidence")
        parser.add_argument("--expected-maintenance-evidence-sha256")
        parser.add_argument("--rollback-artifact")
        parser.add_argument("--expected-rollback-sha256")
        parser.add_argument("--actor", help="执行人用户名")
        parser.add_argument("--action-scope-sha256")
        parser.add_argument("--confirm-reviewed-artifact", action="store_true")
        parser.add_argument(
            "--artifact-root",
            default=str(default_artifact_root()),
            help="受控 artifact 根；所有输入输出必须位于此根内",
        )

    @staticmethod
    def _required(options, *names: str) -> None:
        missing = [
            f"--{name.replace('_', '-')}" for name in names if not options.get(name)
        ]
        if missing:
            raise CommandError("缺少必要参数：" + ", ".join(missing))

    @staticmethod
    def _actor(username: str):
        user_model = get_user_model()
        lookup = {user_model.USERNAME_FIELD: username}
        try:
            return user_model._default_manager.get(**lookup)
        except user_model.DoesNotExist as exc:
            raise CommandError("执行人不存在") from exc

    def handle(self, *args, **options):
        try:
            if options["enter_maintenance"]:
                self._required(
                    options,
                    "expected_manifest_sha256",
                    "action_scope_sha256",
                    "actor",
                )
                gate = enter_historical_calendar_maintenance(
                    manifest_sha256=options["expected_manifest_sha256"],
                    action_scope_sha256=options["action_scope_sha256"],
                    actor=self._actor(options["actor"]),
                )
                result = {"status": gate.status, "gate_id": gate.pk}
            elif options["exit_maintenance"]:
                self._required(
                    options,
                    "expected_manifest_sha256",
                    "action_scope_sha256",
                    "actor",
                )
                actor = self._actor(options["actor"])
                try:
                    gate = HistoricalRaceCalendarMaintenanceGate.objects.get(
                        status="active",
                        manifest_sha256=options["expected_manifest_sha256"],
                        action_scope_sha256=options["action_scope_sha256"],
                        actor=actor,
                    )
                except HistoricalRaceCalendarMaintenanceGate.DoesNotExist as exc:
                    raise CommandError("找不到完全匹配的 active maintenance gate") from exc
                gate = exit_historical_calendar_maintenance(
                    gate=gate,
                    actor=actor,
                    manifest_sha256=options["expected_manifest_sha256"],
                    action_scope_sha256=options["action_scope_sha256"],
                )
                result = {"status": gate.status, "gate_id": gate.pk}
            elif options["prepare"]:
                self._required(options, "output")
                if not options["all_regions"]:
                    raise CommandError("--prepare 必须显式指定 --all-regions")
                result = prepare_historical_race_calendar_integrity(
                    output_dir=Path(options["output"]),
                    artifact_root=Path(options["artifact_root"]),
                    all_regions=True,
                )
            elif options["apply"]:
                # Approval is deliberately checked before artifact access so an
                # incomplete invocation cannot disclose artifact state.
                self._required(
                    options,
                    "approval",
                    "expected_approval_sha256",
                    "artifact",
                    "expected_manifest_sha256",
                    "maintenance_evidence",
                    "expected_maintenance_evidence_sha256",
                    "actor",
                )
                if not options["confirm_reviewed_artifact"]:
                    raise CommandError("--apply 必须指定 --confirm-reviewed-artifact")
                result = apply_historical_race_calendar_integrity(
                    manifest_path=options["artifact"],
                    expected_manifest_sha256=options[
                        "expected_manifest_sha256"
                    ],
                    approval_path=options["approval"],
                    expected_approval_sha256=options[
                        "expected_approval_sha256"
                    ],
                    maintenance_evidence_path=options["maintenance_evidence"],
                    expected_maintenance_evidence_sha256=options[
                        "expected_maintenance_evidence_sha256"
                    ],
                    actor=self._actor(options["actor"]),
                    artifact_root=Path(options["artifact_root"]),
                    confirm_reviewed_artifact=True,
                )
            elif options["verify"]:
                self._required(
                    options,
                    "artifact",
                    "expected_manifest_sha256",
                )
                result = verify_historical_race_calendar_integrity(
                    manifest_path=options["artifact"],
                    expected_manifest_sha256=options[
                        "expected_manifest_sha256"
                    ],
                    artifact_root=Path(options["artifact_root"]),
                    update_receipt=True,
                )
                if not result["ok"]:
                    raise CommandError(
                        "verifier 失败：" + "; ".join(result["errors"])
                    )
            else:
                self._required(
                    options,
                    "approval",
                    "expected_approval_sha256",
                    "artifact",
                    "expected_manifest_sha256",
                    "maintenance_evidence",
                    "expected_maintenance_evidence_sha256",
                    "rollback_artifact",
                    "expected_rollback_sha256",
                    "actor",
                )
                if not options["confirm_reviewed_artifact"]:
                    raise CommandError(
                        "--rollback 必须指定 --confirm-reviewed-artifact"
                    )
                result = rollback_historical_race_calendar_integrity(
                    manifest_path=options["artifact"],
                    expected_manifest_sha256=options[
                        "expected_manifest_sha256"
                    ],
                    approval_path=options["approval"],
                    expected_approval_sha256=options[
                        "expected_approval_sha256"
                    ],
                    maintenance_evidence_path=options["maintenance_evidence"],
                    expected_maintenance_evidence_sha256=options[
                        "expected_maintenance_evidence_sha256"
                    ],
                    rollback_path=options["rollback_artifact"],
                    expected_rollback_sha256=options[
                        "expected_rollback_sha256"
                    ],
                    actor=self._actor(options["actor"]),
                    artifact_root=Path(options["artifact_root"]),
                    confirm_reviewed_artifact=True,
                )
        except (
            HistoricalRaceCalendarIntegrityError,
            HistoricalCalendarWriteBlocked,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        )
