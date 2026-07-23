from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_series_identity_2026_review import (
    RaceSeriesIdentity2026ReviewError,
    build_decisions_from_reviewed_workbook,
    export_2026_review_snapshot,
    write_review_package,
)


class Command(BaseCommand):
    help = "只读导出 2026 赛事系列身份审核包，或离线构建既有写入引擎 decisions"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", required=True, help="新建输出目录；必须不存在")
        parser.add_argument("--year", type=int, default=2026, help="审核年度，当前仅支持 2026")
        parser.add_argument("--production-head", help="导出时的不可变生产 Git HEAD")
        parser.add_argument("--build-decisions", action="store_true", help="离线回读定稿工作簿")
        parser.add_argument("--original-package-dir")
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--reviewed-workbook")
        parser.add_argument("--expected-workbook-sha256")

    @staticmethod
    def _required(options, *names: str) -> None:
        missing = [f"--{name.replace('_', '-')}" for name in names if not options.get(name)]
        if missing:
            raise CommandError("缺少必要参数：" + ", ".join(missing))

    def handle(self, *args, **options):
        output = Path(options["output_dir"])
        if options["year"] != 2026:
            raise CommandError("当前审核适配层仅支持 2026")
        try:
            if options["build_decisions"]:
                self._required(
                    options,
                    "original_package_dir",
                    "expected_manifest_sha256",
                    "reviewed_workbook",
                    "expected_workbook_sha256",
                )
                if output.exists():
                    raise RaceSeriesIdentity2026ReviewError(
                        f"output directory already exists: {output}"
                    )
                result = build_decisions_from_reviewed_workbook(
                    original_package_dir=options["original_package_dir"],
                    expected_manifest_sha256=options["expected_manifest_sha256"],
                    reviewed_workbook=options["reviewed_workbook"],
                    expected_workbook_sha256=options["expected_workbook_sha256"],
                )
                output.mkdir(parents=True)
                try:
                    decisions_bytes = (
                        json.dumps(
                            result["decisions"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                    repairs_bytes = (
                        json.dumps(
                            result["field_repairs"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                    (output / "decisions.json").write_bytes(decisions_bytes)
                    (output / "field-repairs.json").write_bytes(repairs_bytes)
                except Exception:
                    for path in output.iterdir():
                        path.unlink()
                    output.rmdir()
                    raise
                response = {
                    "mode": "build-decisions",
                    "output_dir": str(output),
                    "decision_count": result["decision_count"],
                    "reviewed_workbook_sha256": result["reviewed_workbook_sha256"],
                }
            else:
                self._required(options, "production_head")
                head = str(options["production_head"]).strip().casefold()
                if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
                    raise RaceSeriesIdentity2026ReviewError(
                        "--production-head must be a full 40-character Git SHA"
                    )
                snapshot = export_2026_review_snapshot(year=options["year"])
                response = write_review_package(
                    snapshot=snapshot,
                    output_dir=output,
                    production_head=head,
                    as_of=snapshot["as_of"],
                )
                response["mode"] = "export"
        except (OSError, ValueError, RaceSeriesIdentity2026ReviewError) as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))
