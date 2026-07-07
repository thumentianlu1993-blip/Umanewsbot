from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import SourceLanguage, TermType
from stable.services.term_maintenance import (
    apply_hkjc_ja_alias_merge,
    load_candidate_rows,
    load_rows_from_json,
    plan_hkjc_ja_alias_merge,
    write_csv_artifact,
    write_json_artifact,
)


class Command(BaseCommand):
    help = "HKJC horse 日语 alias 概念合并 dry-run/apply 工具。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="写入数据库。必须同时提供 --plan-file。")
        parser.add_argument("--plan-file", help="已审核 merge plan JSON artifact。")
        parser.add_argument("--candidate-file", help="可选候选 CSV/JSON，支持 target_term_id/source_text 列。")
        parser.add_argument("--output-dir", help="artifact 输出目录。默认写入 runtime/term_backfills。")
        parser.add_argument("--term-type", default=TermType.HORSE, help="术语类型，默认 horse。")
        parser.add_argument("--target-source-language", default=SourceLanguage.ENGLISH, help="目标概念原文语言，默认 en。")
        parser.add_argument("--alias-source-language", default=SourceLanguage.JAPANESE, help="待合并 alias 原文语言，默认 ja。")
        parser.add_argument("--racing-region", default=None, help="可选 racing_region 过滤。")
        parser.add_argument("--target-term-id", action="append", type=int, dest="target_term_ids", help="可重复指定目标 term id。")
        parser.add_argument("--limit", type=int, default=None, help="限制输出行数，用于小批 dry-run。")

    def handle(self, *args, **options):
        output_dir = _output_dir(options.get("output_dir"), prefix="hkjc-ja-alias-merge")
        if options["apply"]:
            plan_file = options.get("plan_file")
            if not plan_file:
                raise CommandError("apply 模式必须提供 --plan-file。")
            rows = load_rows_from_json(plan_file)
            result = apply_hkjc_ja_alias_merge(rows)
            _write_merge_artifacts(output_dir, "apply", result)
            summary = result["summary"]
            self.stdout.write(
                "合并 apply 完成："
                f"applied={summary['applied_count']} skipped={summary['skipped_count']} "
                f"unchanged={summary['unchanged_count']} output={output_dir}"
            )
            return

        candidate_rows = load_candidate_rows(options["candidate_file"]) if options.get("candidate_file") else None
        result = plan_hkjc_ja_alias_merge(
            term_type=options["term_type"],
            target_source_language=options["target_source_language"],
            alias_source_language=options["alias_source_language"],
            racing_region=options.get("racing_region"),
            target_term_ids=options.get("target_term_ids"),
            candidate_rows=candidate_rows,
            limit=options.get("limit"),
        )
        _write_merge_artifacts(output_dir, "plan", result)
        summary = result["summary"]
        self.stdout.write(
            "合并 dry-run 完成："
            f"candidate={summary['candidate_count']} skipped={summary['skipped_count']} "
            f"scanned={summary['scanned']} output={output_dir}"
        )


def _output_dir(raw: str | None, *, prefix: str) -> Path:
    if raw:
        return Path(raw).expanduser()
    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    return Path("runtime") / "term_backfills" / f"{prefix}-{stamp}"


def _write_merge_artifacts(output_dir: Path, phase: str, payload: dict) -> None:
    rows = payload["rows"]
    write_json_artifact(output_dir / f"merge_{phase}.json", payload)
    write_json_artifact(output_dir / "summary.json", payload["summary"])
    write_csv_artifact(
        output_dir / f"merge_{phase}_review.csv",
        rows,
        [
            "action",
            "reason",
            "apply_reason",
            "source_language",
            "source_text",
            "owner_kind",
            "owner_term_id",
            "owner_alias_id",
            "owner_target_zh",
            "alias_id",
            "deactivated_source_term_id",
            "target",
        ],
    )
