from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.services.news_production_integrity import apply_stale_crawl_manifest, build_stale_crawl_manifest


class Command(BaseCommand):
    help = "生成超时 CrawlJob 审核 manifest，或按 SHA 锁定的 manifest 收敛确认无活动证据的任务。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--stale-minutes",
            type=int,
            default=int(getattr(settings, "CRAWL_JOB_STALE_MINUTES", 60)),
        )
        parser.add_argument("--output", default="")
        parser.add_argument("--apply-manifest", default="")
        parser.add_argument("--expected-sha256", default="")
        parser.add_argument("--confirm-apply", action="store_true")
        parser.add_argument("--limit", type=int, default=int(getattr(settings, "CRAWL_JOB_RECONCILE_BATCH_SIZE", 100)))

    def handle(self, *args, **options):
        apply_path = str(options["apply_manifest"] or "").strip()
        if apply_path:
            if not options["confirm_apply"]:
                raise CommandError("apply 必须显式提供 --confirm-apply")
            expected_sha = str(options["expected_sha256"] or "").strip().lower()
            if len(expected_sha) != 64:
                raise CommandError("apply 必须提供 64 位 --expected-sha256")
            path = Path(apply_path)
            if not path.is_file():
                raise CommandError(f"manifest 不存在：{path}")
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                result = apply_stale_crawl_manifest(
                    manifest,
                    expected_sha256=expected_sha,
                    limit=options["limit"],
                )
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(json.dumps({"mode": "apply", **result}, ensure_ascii=False, sort_keys=True))
            return

        output = str(options["output"] or "").strip()
        output_path = Path(output) if output else None
        if output_path is not None and output_path.exists():
            raise CommandError(f"拒绝覆盖已存在的 manifest：{output_path}")
        manifest = build_stale_crawl_manifest(stale_minutes=options["stale_minutes"])
        if output:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with output_path.open("x", encoding="utf-8") as handle:
                    handle.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            except FileExistsError as exc:
                raise CommandError(f"拒绝覆盖已存在的 manifest：{output_path}") from exc
        self.stdout.write(
            json.dumps(
                {
                    "mode": "dry-run",
                    "output": output,
                    "manifest_sha256": manifest["manifest_sha256"],
                    "job_count": len(manifest["jobs"]),
                    "recommended_apply_count": sum(
                        row["recommended_action"] == "reconcile_failed" for row in manifest["jobs"]
                    ),
                    "activity_evidence_available": bool(manifest["activity_evidence"].get("available")),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
