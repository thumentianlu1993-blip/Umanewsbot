from __future__ import annotations

import json
import stat
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import HistoricalBatchLock, HistoricalBatchRun
from stable.services.historical_batch_runner import (
    request_runner_pause,
    resume_runner_run,
    runner_checkpoint_matches,
    runner_has_active_db_sessions,
    runner_status_payload,
    takeover_runner_lease,
)


class Command(BaseCommand):
    help = "查询、暂停、恢复或审计接管历史赛事 runner。"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "pause", "resume", "takeover", "preflight"])
        parser.add_argument("--run-id")
        parser.add_argument("--owner-token-file")
        parser.add_argument("--actor")
        parser.add_argument("--reason")
        parser.add_argument("--container-absent", action="store_true")
        parser.add_argument("--state-file")
        parser.add_argument("--json", action="store_true")

    def _run(self, run_id: str | None, *, required: bool = True):
        queryset = HistoricalBatchRun.objects.order_by("-created_at", "-id")
        if run_id:
            run = queryset.filter(run_id=run_id).first()
        else:
            lock = HistoricalBatchLock.objects.select_related("locked_by_run").filter(key="global").first()
            run = lock.locked_by_run if lock and lock.locked_by_run_id else queryset.first()
        if required and run is None:
            raise CommandError("找不到历史 runner 记录。")
        return run

    def handle(self, *args, **options):
        action = options["action"]
        run = self._run(options.get("run_id"), required=action not in {"status", "preflight"})
        if action == "pause":
            request_runner_pause(
                run=run,
                requested_by=options.get("actor") or "operator",
                reason=options.get("reason") or "operator request",
            )
        elif action == "resume":
            owner_token = self._owner_token(options.get("owner_token_file"))
            run = resume_runner_run(run=run, owner_token=owner_token)
        elif action == "takeover":
            owner_token = self._owner_token(options.get("owner_token_file"))
            takeover_runner_lease(
                run=run,
                new_owner_token=owner_token,
                actor=options.get("actor") or "",
                reason=options.get("reason") or "",
                container_absent=options["container_absent"],
                no_active_db_session=not runner_has_active_db_sessions(run),
                checkpoint_matches=runner_checkpoint_matches(run, options.get("state_file")),
            )
            run.refresh_from_db()
        elif action == "preflight":
            if HistoricalBatchRun.objects.filter(status="running").exists():
                raise CommandError("仍有 running historical runner 记录，禁止迁移。")
            lock = HistoricalBatchLock.objects.select_related("locked_by_run").filter(key="global").first()
            if lock and lock.locked_by_run_id and lock.lease_expires_at and lock.lease_expires_at > timezone.now():
                raise CommandError("仍有未过期 historical runner 租约，禁止迁移。")
            if runner_has_active_db_sessions():
                raise CommandError("仍有 historical runner 数据库连接或事务，禁止迁移。")
            payload = {"state": "migration_safe", "run": None}
            self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return
        payload = runner_status_payload(run)
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=None if options["json"] else 2, sort_keys=True))

    def _owner_token(self, file_name: str | None) -> str:
        if not file_name:
            raise CommandError("resume/takeover 必须提供 --owner-token-file。")
        path = Path(file_name)
        try:
            if stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise CommandError("owner token 文件权限必须精确为 0600。")
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CommandError(f"无法读取 owner token 文件：{exc}") from exc
        if not value:
            raise CommandError("owner token 文件为空。")
        return value
