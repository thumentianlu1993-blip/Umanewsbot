from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.racing_api_horse_staging import (
    RacingApiStagingError,
    apply_targeted_materialization_collection,
    dry_run_targeted_materialization_collection,
    verify_targeted_materialization_collection,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def parse_binding(value: str) -> tuple[Path, str]:
    path_text, separator, manifest_sha = str(value or "").rpartition("=")
    if not separator or not path_text or not SHA256_RE.fullmatch(manifest_sha):
        raise CommandError(
            "--materialization 必须使用 <absolute-path>=<64-lower-hex-sha256>"
        )
    path = Path(path_text)
    if not path.is_absolute():
        raise CommandError("--materialization path 必须是绝对路径")
    return path, manifest_sha


class Command(BaseCommand):
    help = (
        "批量校验最多 25 个 TRA materialization parts；整组先零写 preflight，"
        "再按 part 独立事务 apply 或 verifier。"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--materialization",
            action="append",
            required=True,
            help="重复传入 <absolute-path>=<manifest-sha256>",
        )
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--allow-write", action="store_true")
        parser.add_argument("--verify", action="store_true")

    def handle(self, *args, **options):
        if options["allow_write"] and not options["apply"]:
            raise CommandError("--allow-write 只能与 --apply 同时使用")
        if options["apply"] and options["verify"]:
            raise CommandError("--apply 与 --verify 不能同时使用")
        bindings = [parse_binding(value) for value in options["materialization"]]
        try:
            if options["apply"]:
                report = apply_targeted_materialization_collection(
                    bindings,
                    allow_write=options["allow_write"],
                )
            elif options["verify"]:
                report = verify_targeted_materialization_collection(bindings)
            else:
                report = dry_run_targeted_materialization_collection(bindings)
        except RacingApiStagingError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        )
