from __future__ import annotations

from pathlib import Path
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_live_source_proof import (
    run_the_racing_api_free_proof,
    the_racing_api_transport,
)


class Command(BaseCommand):
    help = "运行一次显式确认、限额且只输出去标识元数据的 The Racing API Free 来源 proof。"

    def add_arguments(self, parser):
        parser.add_argument("--secret-env-file", required=True)
        parser.add_argument("--registry-file", required=True)
        parser.add_argument("--registry-sha256", required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--max-requests", type=int, required=True)
        parser.add_argument("--region")
        parser.add_argument(
            "--confirm-network-proof",
            action="store_true",
            help="显式确认本次运行允许访问审核过的固定来源端点。",
        )

    def handle(self, *args, **options):
        if not options["confirm_network_proof"]:
            raise CommandError("必须显式传入 --confirm-network-proof")
        try:
            result = run_the_racing_api_free_proof(
                secret_env_file=options["secret_env_file"],
                registry_file=options["registry_file"],
                expected_registry_sha256=options["registry_sha256"],
                output_dir=options["output_dir"],
                now=timezone.now(),
                transport=the_racing_api_transport,
                sleep=time.sleep,
                max_requests=options["max_requests"],
                region=options["region"],
            )
        except (OSError, ValueError, PermissionError) as exc:
            raise CommandError(str(exc)) from exc
        if not result.completed:
            raise CommandError(
                f"来源 proof 未完成；审计报告已写入 {result.output_dir.name}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                "来源 proof 已完成："
                f"requests={result.request_count} report={result.output_dir.name}"
            )
        )
