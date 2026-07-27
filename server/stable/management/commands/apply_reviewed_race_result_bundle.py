from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable import models
from stable.services.scheduled_race_result_review import (
    ReviewBundleDrift,
    apply_reviewed_event_payloads,
    compute_reviewed_row_digest,
    compute_event_baseline,
    verify_bundle,
)


class Command(BaseCommand):
    help = "按 exact bundle SHA 与 event:digest scope dry-run/apply/verify 审核赛果。"

    def add_arguments(self, parser):
        parser.add_argument("--bundle-dir", required=True)
        parser.add_argument("--expected-bundle-sha256", required=True)
        parser.add_argument("--approve", action="append", default=[])
        parser.add_argument("--reviewer", default="")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-apply", action="store_true")
        parser.add_argument("--verify", action="store_true")

    def handle(self, *args, **options):
        if options["apply"] and options["verify"]:
            raise CommandError("--apply 与 --verify 不能同时使用")
        if options["confirm_apply"] and not options["apply"]:
            raise CommandError("--confirm-apply 只能与 --apply 同时使用")
        try:
            verified = verify_bundle(
                bundle_dir=Path(options["bundle_dir"]),
                expected_bundle_sha256=options["expected_bundle_sha256"],
            )
        except (OSError, ValueError, ReviewBundleDrift) as exc:
            raise CommandError(f"bundle verify blocked: {getattr(exc, 'reason_code', type(exc).__name__)}") from exc
        payloads = verified["payload"].get("events", [])
        approvals = {}
        for raw in options["approve"]:
            try:
                event_text, digest = raw.split(":", 1)
                event_id = int(event_text)
            except (TypeError, ValueError) as exc:
                raise CommandError("--approve 必须为 EVENT_ID:REVIEWED_ROW_DIGEST") from exc
            if len(digest) != 64 or event_id in approvals:
                raise CommandError("--approve scope/digest 无效或重复")
            approvals[event_id] = digest
        by_id = {int(row["event_id"]): row for row in payloads}
        if set(approvals) - set(by_id):
            raise CommandError("批准 scope 含 bundle 外 event")
        if options["verify"] and not approvals:
            raise CommandError("--verify 需要至少一个 --approve")
        for event_id, digest in approvals.items():
            row = by_id[event_id]
            if row.get("reviewed_row_digest") != digest:
                raise CommandError(f"event {event_id} reviewed-row digest drift")
            if compute_reviewed_row_digest(row.get("results", [])) != digest:
                raise CommandError(f"event {event_id} result rows digest drift")
        if options["verify"]:
            events = []
            for event_id, digest in approvals.items():
                event = models.RaceEvent.objects.prefetch_related("results").get(pk=event_id)
                approval = models.RaceResultReviewApproval.objects.filter(
                    bundle_sha256=options["expected_bundle_sha256"],
                    event=event,
                    reviewed_row_digest=digest,
                ).first()
                expected = by_id[event_id]
                ok = (
                    approval is not None
                    and approval.authority == expected["authority"]
                    and event.status == models.RaceEventStatus.FINISHED
                    and event.result_confirmed_at is not None
                    and compute_reviewed_row_digest(
                        [
                            {
                                "finish_position": row.finish_position,
                                "horse_number": row.horse_number,
                                "horse_name": row.horse_name,
                                "running_status": row.running_status,
                            }
                            for row in event.results.all()
                        ]
                    )
                    == expected["reviewed_row_digest"]
                )
                if expected["authority"] == "official":
                    ok = ok and all(
                        row.official_finish_position == row.finish_position
                        for row in event.results.all()
                    )
                else:
                    ok = ok and all(
                        row.official_finish_position is None
                        for row in event.results.all()
                    )
                events.append({"event_id": event_id, "verified": ok})
            if not all(item["verified"] for item in events):
                raise CommandError(json.dumps({"status": "blocked", "events": events}))
            self.stdout.write(json.dumps({"status": "verified", "events": events}))
            return
        for event_id in approvals:
            row = by_id[event_id]
            already_applied = models.RaceResultReviewApproval.objects.filter(
                bundle_sha256=options["expected_bundle_sha256"],
                event_id=event_id,
                reviewed_row_digest=row["reviewed_row_digest"],
            ).exists()
            if already_applied:
                continue
            event = models.RaceEvent.objects.prefetch_related("results").get(pk=event_id)
            if compute_event_baseline(event) != row.get("baseline_sha256"):
                raise CommandError(f"event {event_id} database baseline drift")
        dry_run = {
            "status": "dry_run",
            "bundle_sha256": options["expected_bundle_sha256"],
            "approved_event_ids": list(approvals),
            "result_rows": sum(len(by_id[event_id].get("results", [])) for event_id in approvals),
        }
        if not options["apply"]:
            self.stdout.write(json.dumps(dry_run, sort_keys=True))
            return
        if not options["confirm_apply"] or not options["reviewer"] or not approvals:
            raise CommandError("--apply 需要 --confirm-apply、--reviewer 和至少一个 --approve")
        result = apply_reviewed_event_payloads(
            bundle_sha256=options["expected_bundle_sha256"],
            approved_event_ids=list(approvals),
            reviewer=options["reviewer"],
            event_payloads=payloads,
            confirmed_at=timezone.now(),
        )
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.stdout.write(rendered)
        returned_events = result.get("events")
        returned_ids = (
            {
                int(item["event_id"])
                for item in returned_events
                if isinstance(item, dict) and isinstance(item.get("event_id"), int)
            }
            if isinstance(returned_events, list)
            else set()
        )
        allowed_statuses = {"applied", "already_applied"}
        incomplete = (
            not isinstance(returned_events, list)
            or returned_ids != set(approvals)
            or any(
                not isinstance(item, dict)
                or item.get("status") not in allowed_statuses
                for item in (returned_events or [])
            )
            or bool(result.get("unexpected"))
        )
        if incomplete:
            raise CommandError("apply scope 未全部成功；详见逐 event summary")
