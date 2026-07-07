from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.term_maintenance import (
    apply_article_term_backfill,
    load_rows_from_json,
    merge_term_ids_from_rows,
    plan_article_term_backfill,
    write_csv_artifact,
    write_json_artifact,
)


class Command(BaseCommand):
    help = "已发布文章术语字段级 dry-run/apply 回填工具。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="写入数据库。默认只 dry-run。")
        parser.add_argument("--diff-file", help="已审核文章回填 diff JSON artifact。")
        parser.add_argument("--merge-plan-file", help="从 merge plan/apply artifact 读取目标 term id 范围。")
        parser.add_argument("--term-id", action="append", type=int, dest="term_ids", help="可重复指定术语 ID。")
        parser.add_argument("--article-id", action="append", type=int, dest="article_ids", help="可重复指定文章 ID。")
        parser.add_argument("--source-language", help="按文章 source_language 过滤。")
        parser.add_argument("--published-from", help="按 published_to_web_at 起始时间过滤，YYYY-MM-DD。")
        parser.add_argument("--published-to", help="按 published_to_web_at 结束时间过滤，YYYY-MM-DD。")
        parser.add_argument("--limit", type=int, default=None, help="限制扫描文章数。")
        parser.add_argument("--include-unpublished", action="store_true", help="包含未发布文章。生产不建议使用。")
        parser.add_argument("--output-dir", help="artifact 输出目录。默认写入 runtime/term_backfills。")

    def handle(self, *args, **options):
        output_dir = _output_dir(options.get("output_dir"), prefix="article-term-backfill")
        if options["apply"] and options.get("diff_file"):
            rows = load_rows_from_json(options["diff_file"])
            result = apply_article_term_backfill(rows)
            _write_backfill_artifacts(output_dir, "apply", result)
            summary = result["summary"]
            self.stdout.write(
                "文章术语回填 apply 完成："
                f"updated={summary['updated_fields']} skipped={summary['skipped_fields']} "
                f"stale={summary['stale_fields']} output={output_dir}"
            )
            return

        term_ids = _resolve_term_ids(options)
        if not term_ids:
            raise CommandError("必须通过 --term-id 或 --merge-plan-file 指定术语范围。")
        explicit_scope = _has_explicit_scope(options)
        if options["apply"] and not explicit_scope:
            raise CommandError("apply 模式必须提供已审核 --diff-file，或提供显式 article/date/source/limit 过滤范围。")
        plan = plan_article_term_backfill(
            term_ids=term_ids,
            article_ids=options.get("article_ids"),
            source_language=options.get("source_language"),
            published_from=_parse_date_start(options.get("published_from")),
            published_to=_parse_date_end(options.get("published_to")),
            limit=options.get("limit"),
            published_only=not options.get("include_unpublished"),
        )
        if options["apply"]:
            result = apply_article_term_backfill(plan["rows"])
            _write_backfill_artifacts(output_dir, "apply", result)
            summary = result["summary"]
            self.stdout.write(
                "文章术语回填 apply 完成："
                f"updated={summary['updated_fields']} skipped={summary['skipped_fields']} "
                f"stale={summary['stale_fields']} output={output_dir}"
            )
            return
        _write_backfill_artifacts(output_dir, "diff", plan)
        summary = plan["summary"]
        self.stdout.write(
            "文章术语回填 dry-run 完成："
            f"planned={summary['planned_fields']} skipped={summary['skipped_fields']} "
            f"scanned={summary['scanned_articles']} output={output_dir}"
        )


def _resolve_term_ids(options: dict) -> list[int]:
    term_ids = set(options.get("term_ids") or [])
    merge_plan_file = options.get("merge_plan_file")
    if merge_plan_file:
        term_ids.update(merge_term_ids_from_rows(load_rows_from_json(merge_plan_file)))
    return sorted(term_ids)


def _has_explicit_scope(options: dict) -> bool:
    return any(
        [
            options.get("article_ids"),
            options.get("source_language"),
            options.get("published_from"),
            options.get("published_to"),
            options.get("limit"),
        ]
    )


def _parse_date_start(value: str | None):
    if not value:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return timezone.make_aware(datetime.combine(parsed, time.min))


def _parse_date_end(value: str | None):
    if not value:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return timezone.make_aware(datetime.combine(parsed, time.max))


def _output_dir(raw: str | None, *, prefix: str) -> Path:
    if raw:
        return Path(raw).expanduser()
    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    return Path("runtime") / "term_backfills" / f"{prefix}-{stamp}"


def _write_backfill_artifacts(output_dir: Path, phase: str, payload: dict) -> None:
    rows = payload["rows"]
    write_json_artifact(output_dir / f"article_backfill_{phase}.json", payload)
    write_json_artifact(output_dir / "summary.json", payload["summary"])
    write_csv_artifact(
        output_dir / f"article_backfill_{phase}_review.csv",
        rows,
        [
            "action",
            "reason",
            "apply_reason",
            "article_id",
            "field",
            "source_language",
            "term_ids",
            "source_texts",
            "target_values",
            "replacement_count",
            "before_excerpt",
            "after_excerpt",
        ],
    )
