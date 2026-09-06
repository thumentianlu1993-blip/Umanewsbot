from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services import race_data_sync_lifecycle, race_data_sync_repair


class Command(BaseCommand):
    help = (
        "一次性审计修复停滞的 data-sync 赛事：默认 dry-run 生成 SHA 锁定候选，"
        "--apply 必须绑定候选文件 SHA。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--horizon-days", type=int, default=7)
        parser.add_argument("--batch-size", type=int, default=20)
        parser.add_argument("--as-of", help="ISO-8601 评估时点；默认当前时间。")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--candidate-file")
        parser.add_argument("--expected-sha256")

    def handle(self, *args, **options):
        as_of = options.get("as_of")
        if as_of:
            now = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
            if timezone.is_naive(now):
                raise CommandError("--as-of 必须包含时区")
        else:
            now = timezone.now()
        from stable.services.race_data_sync_enrollment import (
            load_standing_policy_file,
        )

        try:
            standing_policy = load_standing_policy_file(
                path=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE,
                expected_sha256=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise CommandError(f"standing policy 不可用: {exc}") from exc
        horizon_days = options["horizon_days"]
        batch_size = options["batch_size"]
        if options["apply"]:
            self._handle_apply(now=now, options=options, standing_policy=standing_policy)
            return

        with transaction.atomic():
            events = race_data_sync_repair.find_unclosed_data_sync_events(
                now=now,
                horizon_days=horizon_days,
                batch_size=batch_size,
            )
            adopt_reasons = {}
            for event in events:
                adopt_reasons[event.pk] = race_data_sync_repair.adopt_stalled_event_policy(
                    event=event,
                    now=now,
                    standing_policy=standing_policy,
                    adoption_token="dry-run",
                )
            reconcile_stats = (
                race_data_sync_lifecycle.reconcile_data_sync_lifecycle_admission(
                    now=now,
                    batch_size=batch_size,
                    standing_policy=standing_policy,
                )
            )
            entries = []
            for event in events:
                assessment = race_data_sync_repair.assess_stalled_event(
                    event=event,
                    now=now,
                    standing_policy=standing_policy,
                )
                adopt_reason = adopt_reasons.get(event.pk, "")
                if adopt_reason and not assessment.repairable:
                    assessment = race_data_sync_repair.StalledEventAssessment(
                        assessment.event_id,
                        assessment.revision_id,
                        assessment.observation_id,
                        False,
                        adopt_reason,
                    )
                entries.append(assessment.as_dict())
            transaction.set_rollback(True)
        payload = {
            "schema_version": 1,
            "created_at": now.isoformat(),
            "horizon_days": horizon_days,
            "entries": entries,
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        candidate_sha256 = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        output_dir = (
            Path(settings.BASE_DIR).parent
            / "runtime"
            / "race_data_sync_repairs"
            / now.strftime("%Y%m%dT%H%M%SZ")
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        candidate_file = output_dir / "candidates.json"
        candidate_file.write_text(rendered, encoding="utf-8")
        report = {
            "status": "dry_run",
            "writes": 0,
            "candidate_sha256": candidate_sha256,
            "candidate_file": str(candidate_file),
            "reconcile": reconcile_stats,
            "entries": entries,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))

    def _handle_apply(self, *, now, options, standing_policy) -> None:
        for flag in (
            "RACE_DATA_SYNC_ENABLED",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED",
            "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED",
            "RACE_DATA_SYNC_RESULT_APPLY_ENABLED",
            "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED",
        ):
            if getattr(settings, flag, False) is not True:
                raise CommandError(f"runtime flag {flag} is off")
        candidate_file = options.get("candidate_file")
        expected_sha256 = str(options.get("expected_sha256") or "").strip().lower()
        if not candidate_file or not expected_sha256:
            raise CommandError("--apply 需要 --candidate-file 和 --expected-sha256")
        raw = Path(candidate_file).read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            raise CommandError(
                f"candidate_sha256_mismatch: expected={expected_sha256} actual={actual_sha256}"
            )
        payload = json.loads(raw.decode("utf-8"))
        entries = payload.get("entries") or []
        if payload.get("schema_version") != 1 or not isinstance(entries, list):
            raise CommandError("candidate file schema is invalid")

        adopt_reasons = {}
        for entry in entries:
            event_id = entry.get("event_id")
            event = models.RaceEvent.objects.filter(pk=event_id).first()
            if event is not None:
                adopt_reasons[event_id] = (
                    race_data_sync_repair.adopt_stalled_event_policy(
                        event=event,
                        now=now,
                        standing_policy=standing_policy,
                        adoption_token=expected_sha256,
                    )
                )
        reconcile_stats = race_data_sync_lifecycle.reconcile_data_sync_lifecycle_admission(
            now=now,
            batch_size=options["batch_size"],
            standing_policy=standing_policy,
        )
        results = []
        for entry in entries:
            event_id = entry.get("event_id")
            event = models.RaceEvent.objects.filter(pk=event_id).first()
            if event is None:
                results.append({"event_id": event_id, "applied": False, "reason": "event_missing"})
                continue
            assessment = race_data_sync_repair.assess_stalled_event(
                event=event,
                now=now,
                standing_policy=standing_policy,
            )
            adopt_reason = adopt_reasons.get(event_id, "")
            if adopt_reason and not assessment.repairable:
                assessment = race_data_sync_repair.StalledEventAssessment(
                    assessment.event_id,
                    assessment.revision_id,
                    assessment.observation_id,
                    False,
                    adopt_reason,
                )
            if not assessment.repairable:
                results.append(
                    {
                        "event_id": event_id,
                        "applied": False,
                        "reason": assessment.reason_code,
                    }
                )
                continue
            if (
                entry.get("revision_id") != assessment.revision_id
                or entry.get("observation_id") != assessment.observation_id
            ):
                results.append(
                    {
                        "event_id": event_id,
                        "applied": False,
                        "reason": "candidate_entry_stale",
                    }
                )
                continue
            reason = race_data_sync_repair.apply_stalled_event_repair(
                assessment=assessment,
                now=now,
                standing_policy=standing_policy,
                operation_detail={"candidate_sha256": expected_sha256},
            )
            if reason:
                results.append(
                    {"event_id": event_id, "applied": False, "reason": reason}
                )
                continue
            results.append(
                {
                    "event_id": event_id,
                    "applied": True,
                    "reason": "",
                    "revision_id": assessment.revision_id,
                }
            )
        report = {
            "status": "applied",
            "candidate_sha256": expected_sha256,
            "reconcile": reconcile_stats,
            "results": results,
            "applied_count": sum(1 for item in results if item["applied"]),
            "rejected_count": sum(1 for item in results if not item["applied"]),
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
