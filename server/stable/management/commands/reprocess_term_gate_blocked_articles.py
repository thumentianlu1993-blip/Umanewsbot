from __future__ import annotations

import json
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.models import RacingRegion
from stable.services.term_gate_reprocessing import (
    ReprocessLeaseActive,
    apply_published_term_gate_audit_run,
    commit_reprocess_run,
    run_published_term_gate_audit_dry_run,
    run_reprocess_dry_run,
)


class Command(BaseCommand):
    help = "受控重处理近期因 core_term_missing 被挡住的文章。"

    def add_arguments(self, parser):
        parser.add_argument("--region", choices=[choice[0] for choice in RacingRegion.choices])
        parser.add_argument("--source", action="append")
        parser.add_argument("--hours", type=int)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--max-seconds", type=float)
        parser.add_argument("--cursor", default="")
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--manifest-sha256", default="")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--published-audit", action="store_true")
        parser.add_argument("--article-id", action="append", type=int, dest="article_ids")
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--operator", default="")
        parser.add_argument("--reviewer", default="")

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")
        if options.get("published_audit"):
            article_ids = options.get("article_ids") or []
            if not article_ids:
                raise CommandError("published audit 必须至少指定一个 --article-id")
            operator_identity = " ".join((options.get("operator") or "").split())
            reviewer_identity = " ".join((options.get("reviewer") or "").split())
            if not operator_identity or not reviewer_identity:
                raise CommandError(
                    "published audit 必须显式指定 --operator 和 --reviewer identity"
                )
            try:
                if options["commit"]:
                    if not options.get("run_id") or not options.get("manifest_sha256") or not options.get("confirm"):
                        raise CommandError(
                            "published audit commit 必须指定 --run-id、--manifest-sha256 和 --confirm"
                        )
                    payload = apply_published_term_gate_audit_run(
                        dry_run_id=options["run_id"],
                        manifest_sha256=options["manifest_sha256"],
                        article_ids=article_ids,
                        confirm=True,
                        operator_identity=operator_identity,
                        reviewer_identity=reviewer_identity,
                    )
                else:
                    payload = run_published_term_gate_audit_dry_run(
                        article_ids=article_ids,
                        owner_token=f"published-audit:{operator_identity}:{reviewer_identity}",
                        operator_identity=operator_identity,
                        reviewer_identity=reviewer_identity,
                    )
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            rendered = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
            self.stdout.write(
                rendered if options["json"] else json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            )
            return
        if options["commit"]:
            if not options.get("run_id") or not options.get("manifest_sha256"):
                raise CommandError("commit 必须指定 --run-id 和 --manifest-sha256")
            try:
                payload = commit_reprocess_run(
                    dry_run_id=options["run_id"],
                    manifest_sha256=options["manifest_sha256"],
                )
            except (ValueError, ReprocessLeaseActive) as exc:
                raise CommandError(str(exc)) from exc
        else:
            if not options.get("region"):
                raise CommandError("dry-run 必须指定 --region")
            hours = int(options.get("hours") or getattr(settings, "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", 3))
            limit = int(options.get("limit") or getattr(settings, "TERM_GATE_REPROCESS_DEFAULT_LIMIT", 100))
            max_seconds = float(options.get("max_seconds") or getattr(settings, "TERM_GATE_REPROCESS_MAX_SECONDS", 60))
            if hours <= 0 or limit <= 0 or max_seconds <= 0:
                raise CommandError("--hours、--limit 和 --max-seconds 必须大于 0")
            try:
                payload = run_reprocess_dry_run(
                    region=options["region"],
                    hours=hours,
                    limit=limit,
                    max_seconds=max_seconds,
                    source_filters={value.strip() for value in (options.get("source") or []) if value.strip()},
                    cursor_value=options.get("cursor") or "",
                    owner_token=uuid.uuid4().hex,
                )
            except (ValueError, ReprocessLeaseActive) as exc:
                raise CommandError(str(exc)) from exc
        rendered = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
        self.stdout.write(rendered if options["json"] else json.dumps(payload, ensure_ascii=False, indent=2, default=str))
